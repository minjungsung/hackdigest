from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def money(value):
    """Accept integer KRW, never guess Korean units or extract a hidden price."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.0+)?(?:\s*원)?", text):
        return None
    try:
        amount = Decimal(text.removesuffix("원").strip().replace(",", ""))
        return int(amount) if amount > 0 else None
    except InvalidOperation:
        return None


def parse_datetime(value):
    if not value:
        return None
    text = str(value).strip()
    try:
        if re.fullmatch(r"\d{12}|\d{14}", text):
            return datetime.strptime(text, "%Y%m%d%H%M" if len(text) == 12 else "%Y%m%d%H%M%S").replace(tzinfo=KST)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=KST)
    except ValueError:
        return None


def valid_url(value):
    try:
        p = urlsplit(str(value))
        return p.scheme in {"http", "https"} and bool(p.hostname) and not p.username and not p.password
    except ValueError:
        return False


@dataclass(frozen=True)
class Listing:
    source: str
    listing_id: str
    title: str
    address: str
    city: str
    category: str
    transaction: str
    status: str
    price_krw: int | None
    price_kind: str
    source_url: str
    observed_at: str
    property_id: str = ""
    sale_scope: str = "unknown"
    appraisal_krw: int | None = None
    appraisal_date: str = ""
    appraisal_scope: str = "unknown"
    appraisal_kind: str = "unknown"
    appraisal_verified: bool = False
    appraisal_evidence_url: str = ""
    bid_end: str = ""
    round_id: str = ""
    flags: tuple = ()

    @property
    def key(self):
        return f"{self.source}:{self.listing_id}"

    @classmethod
    def from_record(cls, record, source):
        allowed = set(cls.__dataclass_fields__) - {"source", "flags"}
        values = {k: v for k, v in record.items() if k in allowed}
        values["price_krw"] = money(values.get("price_krw"))
        values["appraisal_krw"] = money(values.get("appraisal_krw"))
        values["appraisal_verified"] = values.get("appraisal_verified") is True or str(values.get("appraisal_verified", "")).lower() == "true"
        for key in allowed - {"price_krw", "appraisal_krw", "appraisal_verified"}:
            if key in values:
                values[key] = "" if values[key] is None else str(values[key]).strip()
        defaults = dict(listing_id="", title="", address="", city="", category="unknown", transaction="unknown", status="unknown", price_kind="unknown", source_url="", observed_at="")
        defaults.update(values)
        if not defaults["listing_id"]:
            raise ValueError("A listing_id is required")
        flags = record.get("flags", ())
        if isinstance(flags, str):
            flags = tuple(x.strip() for x in flags.split("|") if x.strip())
        elif isinstance(flags, (tuple, list)):
            flags = tuple(str(x) for x in flags)
        else:
            raise ValueError("flags must be a list or pipe-delimited text")
        return cls(source=source, flags=flags, **defaults)


def apply_review(listing, reviews):
    """Only explicit provider/listing identifiers establish property identity."""
    row = reviews.get(listing.key)
    if not row:
        return listing
    reviewed_property = str(row.get("property_id", "")).strip()
    if not reviewed_property or (listing.property_id and listing.property_id != reviewed_property):
        return replace(listing, flags=listing.flags + ("review_identity_conflict",))
    values = {"property_id": reviewed_property}
    for key in ("sale_scope", "category", "appraisal_date", "appraisal_scope", "appraisal_kind", "appraisal_evidence_url"):
        if row.get(key):
            values[key] = str(row[key]).strip()
    if row.get("appraisal_krw"):
        # A conflicting current provider value needs a fresh review.
        amount = money(row["appraisal_krw"])
        if listing.appraisal_krw and amount != listing.appraisal_krw:
            return replace(listing, flags=listing.flags + ("review_appraisal_conflict",))
        values["appraisal_krw"] = amount
    values["appraisal_verified"] = str(row.get("appraisal_verified", "")).lower() == "true" and money(row.get("appraisal_krw")) is not None
    return replace(listing, **values)


def assess(listing, policy, now=None):
    now = now or datetime.now(timezone.utc)
    reasons = []
    if listing.city not in {"서울", "서울시", "서울특별시", "Seoul"}:
        reasons.append("outside_seoul")
    if listing.category not in {"commercial", "office"}:
        reasons.append("not_commercial_or_office")
    if listing.transaction != "sale":
        reasons.append("not_a_sale")
    if listing.status not in {"active", "upcoming", "private_contract"}:
        reasons.append("inactive_listing")
    if listing.sale_scope != "whole_property" or not listing.property_id:
        reasons.append("whole_property_identity_unconfirmed")
    if any(f in listing.flags for f in ("share", "unit", "unit_price", "bundle", "review_identity_conflict", "review_appraisal_conflict")):
        reasons.append("incompatible_sale_scope")
    if listing.price_kind not in {"asking_price", "minimum_bid"}:
        reasons.append("unknown_price_basis")
    if not listing.price_krw:
        reasons.append("price_unavailable")
    if not listing.appraisal_krw:
        reasons.append("appraisal_unavailable")
    if listing.appraisal_kind != "formal" or not listing.appraisal_verified or not valid_url(listing.appraisal_evidence_url):
        reasons.append("formal_appraisal_unverified")
    if listing.appraisal_scope != "whole_property":
        reasons.append("appraisal_scope_mismatch")
    if not valid_url(listing.source_url):
        reasons.append("source_link_unavailable")
    observed = parse_datetime(listing.observed_at)
    if not observed or observed > now + timedelta(minutes=5) or now - observed > timedelta(days=policy.get("max_listing_age_days", 7)):
        reasons.append("listing_observation_stale_or_invalid")
    try:
        appraisal_day = date.fromisoformat(listing.appraisal_date)
        age = (now.astimezone(KST).date() - appraisal_day).days
        if not 0 <= age <= policy.get("max_appraisal_age_days", 365):
            reasons.append("appraisal_stale_or_future")
    except ValueError:
        reasons.append("appraisal_date_unavailable")
    if listing.price_kind == "minimum_bid" and listing.status != "private_contract":
        end = parse_datetime(listing.bid_end)
        if not end or end <= now:
            reasons.append("bid_expired_or_deadline_unknown")
    threshold = Decimal(str(policy.get("discount_percent", 40)))
    if not threshold.is_finite() or not 0 < threshold < 100:
        raise ValueError("discount_percent must be between 0 and 100")
    discount = None
    if listing.price_krw and listing.appraisal_krw:
        discount = (Decimal(listing.appraisal_krw) - Decimal(listing.price_krw)) * 100 / Decimal(listing.appraisal_krw)
        # Compare integer money exactly at the inclusive boundary.
        if Decimal(listing.price_krw) * 100 > Decimal(listing.appraisal_krw) * (100 - threshold):
            reasons.append("discount_below_threshold")
    return {"eligible": not reasons, "discount_percent": str(discount) if discount is not None else None, "reasons": reasons, "listing": asdict(listing)}


def fingerprint(listing):
    material = [listing.property_id, listing.price_kind, listing.price_krw, listing.appraisal_krw,
                listing.appraisal_date, listing.appraisal_scope, listing.appraisal_evidence_url,
                listing.round_id, listing.bid_end]
    return sha256(json.dumps(material, ensure_ascii=False).encode()).hexdigest()
