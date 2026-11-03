import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
import xml.etree.ElementTree as ET

from .core import Listing, money, valid_url

ONBID_ENDPOINT = "https://apis.data.go.kr/B010003/OnbidRlstListSrvc2/getRlstCltrList2"


class SourceError(Exception):
    pass


class FeedRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        previous, target = urlsplit(req.full_url), urlsplit(newurl)
        if target.scheme != "https" or target.netloc != previous.netloc:
            raise SourceError("Feed redirects must remain on the original HTTPS origin")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def read_records(path):
    path = Path(path)
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    with path.open(encoding="utf-8-sig") as f:
        data = json.load(f)
    records = data.get("listings") if isinstance(data, dict) else data
    if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
        raise SourceError("Expected a JSON array of records or an object with a listings array")
    return records


def parse_onbid_response(raw):
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            raise SourceError("Onbid returned an invalid JSON/XML response") from None
        code = root.findtext(".//resultCode") or root.findtext(".//returnReasonCode")
        if code and code not in {"0", "00", "0000", "000"}:
            raise SourceError(f"Onbid API error code {code}")
        if code is None:
            raise SourceError("Onbid response has no result code")
        records = [{c.tag: c.text or "" for c in item} for item in root.findall(".//items/item")]
        total = root.findtext(".//totalCount")
    else:
        if not isinstance(data, dict):
            raise SourceError("Onbid returned an unexpected JSON shape")
        data = data.get("response", data)
        code = str(data.get("header", {}).get("resultCode", ""))
        if code not in {"0", "00", "0000", "000"}:
            raise SourceError(f"Onbid API error code {code or 'missing'}")
        body = data.get("body", {})
        items = body.get("items") or {}
        records = items.get("item", []) if isinstance(items, dict) else items
        if isinstance(records, dict):
            records = [records]
        if records is None or records == "":
            records = []
        total = body.get("totalCount")
    try:
        total = int(total)
    except (TypeError, ValueError):
        raise SourceError("Onbid response is missing a valid totalCount") from None
    if total < 0 or not isinstance(records, list) or any(not isinstance(x, dict) for x in records):
        raise SourceError("Onbid returned invalid items")
    return records, total


def normalize_onbid(row, observed_at):
    def text(key):
        return str(row.get(key) or "").strip()
    listing_id = text("cltrMngNo")
    if not listing_id:
        raise SourceError("Onbid item is missing cltrMngNo")
    category_text = " ".join(text(k) for k in ("cltrUsgLclsCtgrNm", "cltrUsgMclsCtgrNm", "cltrUsgSclsCtgrNm"))
    category = "office" if any(k in category_text for k in ("업무", "사무")) else "commercial" if any(k in category_text for k in ("근린", "상가", "판매", "상업")) else "unknown"
    flags = []
    if text("alcYn").upper() == "Y":
        flags.append("share")
    if text("batcBidYn").upper() == "Y":
        flags.append("bundle")
    if text("totalamtUnpcDivCd") != "0001":
        flags.append("unit_price")
    status = {"0001": "upcoming", "0002": "active", "0009": "private_contract"}.get(text("pbctStatCd"), "inactive")
    # The list API does not prove that an asset is an entire building or
    # give the date and scope of the underlying appraisal. A review supplies these.
    return Listing(
        source="onbid", listing_id=listing_id, title=text("onbidCltrNm"),
        address=" ".join(text(k) for k in ("lctnSdnm", "lctnSggnm", "lctnEmdNm")),
        city=text("lctnSdnm"), category=category,
        transaction="sale" if text("dspsMthodCd") == "0001" else "rental",
        status=status, price_krw=money(row.get("lowstBidPrcIndctCont")),
        price_kind="minimum_bid", appraisal_krw=money(row.get("apslEvlAmt")),
        source_url="https://www.onbid.co.kr", observed_at=observed_at,
        bid_end=text("cltrBidEndDt"),
        round_id=":".join(text(k) for k in ("pbctCdtnNo", "pbctNo", "pbctNsq")), flags=tuple(flags),
    )


def fetch_onbid(settings, store, opener=urlopen):
    key = os.environ.get(settings.get("service_key_env", "ONBID_SERVICE_KEY"), "")
    if not key:
        raise SourceError("ONBID_SERVICE_KEY is not configured")
    key = unquote(key)  # Accept either encoded or decoded public-data keys.
    rows_per_page = int(settings.get("rows_per_page", 100))
    max_pages = int(settings.get("max_pages_per_query", 10))
    delay = float(settings.get("request_delay_seconds", 1))
    if not 1 <= rows_per_page <= 100 or max_pages < 1 or delay < 0:
        raise SourceError("Invalid Onbid pagination or request delay settings")
    observed = datetime.now(timezone.utc).isoformat()
    results = {}
    for private_contract in ("N", "Y"):
        for page in range(1, max_pages + 1):
            params = dict(serviceKey=key, pageNo=page, numOfRows=rows_per_page, resultType="json",
                          prptDivCd=settings.get("property_types", "0007,0010,0005,0002,0003,0006,0008,0011,0013"),
                          pvctTrgtYn=private_contract, dspsMthodCd="0001", lctnSdnm="서울특별시", alcYn="N")
            raw = None
            for attempt in range(3):
                store.reserve_request("onbid", int(settings.get("daily_request_limit", 900)))
                if delay:
                    time.sleep(delay)
                try:
                    req = Request(ONBID_ENDPOINT + "?" + urlencode(params), headers={"User-Agent": "BuildingDiscountMonitor/0.1"})
                    with opener(req, timeout=30) as response:
                        raw = response.read(8_000_001)
                    if len(raw) > 8_000_000:
                        raise SourceError("Onbid response exceeded size limit")
                    break
                except HTTPError as exc:
                    if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                        raise SourceError(f"Onbid HTTP error {exc.code}") from None
                except (URLError, TimeoutError, OSError):
                    if attempt == 2:
                        raise SourceError("Onbid network request failed after retries") from None
                time.sleep(2 ** attempt)
            records, total = parse_onbid_response(raw)
            for record in records:
                listing = normalize_onbid(record, observed)
                results[(listing.key, listing.round_id)] = listing
            if page * rows_per_page >= total:
                break
            if not records:
                raise SourceError("Onbid pagination returned an empty page before totalCount")
        else:
            raise SourceError("Onbid page limit reached; collection is incomplete. Increase the limit or narrow the query")
    return list(results.values())


def fetch_feed(settings, base, opener=None):
    name = settings.get("name", "")
    if not name or name == "onbid":
        raise SourceError("A feed needs a unique name other than onbid")
    if settings.get("path"):
        records = read_records(base / settings["path"])
    elif settings.get("url"):
        opener = opener or build_opener(FeedRedirectHandler()).open
        url = settings["url"]
        if not valid_url(url) or not url.startswith("https://"):
            raise SourceError("A remote feed requires an HTTPS URL without embedded credentials")
        headers = {"User-Agent": "BuildingDiscountMonitor/0.1", "Accept": "application/json"}
        if settings.get("token_env"):
            token = os.environ.get(settings["token_env"])
            if not token:
                raise SourceError("Feed authorization token is missing")
            headers["Authorization"] = "Bearer " + token
        try:
            with opener(Request(url, headers=headers), timeout=30) as response:
                raw = response.read(8_000_001)
            if len(raw) > 8_000_000:
                raise SourceError("Feed response exceeded size limit")
            data = json.loads(raw)
        except (HTTPError, URLError, TimeoutError, OSError):
            raise SourceError("Feed request failed") from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise SourceError("Feed returned invalid JSON") from None
        records = data.get("listings") if isinstance(data, dict) else data
        if not isinstance(records, list):
            raise SourceError("Feed must contain a listings array")
    else:
        raise SourceError("Feed needs a path or URL")
    if any(not isinstance(row, dict) for row in records):
        raise SourceError("Feed contains an invalid record")
    return [Listing.from_record(row, name) for row in records]
