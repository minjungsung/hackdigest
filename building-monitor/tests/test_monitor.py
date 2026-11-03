from contextlib import redirect_stdout
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

from building_monitor.core import Listing, apply_review, assess, fingerprint, money
from building_monitor.__main__ import load_env, load_reviews, run_once
from building_monitor.notifications import build_email, send_email
from building_monitor.sources import FeedRedirectHandler, SourceError, fetch_feed, fetch_onbid, normalize_onbid, parse_onbid_response
from building_monitor.store import Store

NOW = datetime(2026, 11, 3, 1, 0, tzinfo=timezone.utc)


def listing(now=NOW, **changes):
    values = dict(source="broker", listing_id="building-1", title="Synthetic building", address="Seoul",
                  city="서울특별시", category="commercial", transaction="sale", status="active",
                  price_krw=3_000_000_000, price_kind="asking_price", source_url="https://example.invalid/listing/1",
                  observed_at=now.isoformat(), property_id="property-1", sale_scope="whole_property",
                  appraisal_krw=5_000_000_000, appraisal_date=(now - timedelta(days=30)).date().isoformat(),
                  appraisal_scope="whole_property", appraisal_kind="formal", appraisal_verified=True,
                  appraisal_evidence_url="https://example.invalid/appraisal/1")
    values.update(changes)
    return Listing(**values)


def onbid_item(**changes):
    row = dict(cltrMngNo="demo-management-id", pbctCdtnNo="11", pbctNo="21", pbctNsq="2",
               onbidCltrNm="Synthetic building", cltrUsgMclsCtgrNm="근린생활시설",
               lctnSdnm="서울특별시", lctnSggnm="Synthetic district", lctnEmdNm="Synthetic area",
               dspsMthodCd="0001", totalamtUnpcDivCd="0001", pbctStatCd="0002", alcYn="N", batcBidYn="N",
               apslEvlAmt="5000000000", lowstBidPrcIndctCont="3,000,000,000",
               cltrBidEndDt="202611101200")
    row.update(changes)
    return row


def response(items, total=None):
    return json.dumps({"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": items}, "totalCount": len(items) if total is None else total}}}).encode()


class EligibilityTests(unittest.TestCase):
    def test_exact_forty_percent_and_one_won_above(self):
        self.assertTrue(assess(listing(), {}, NOW)["eligible"])
        self.assertFalse(assess(listing(price_krw=3_000_000_001), {}, NOW)["eligible"])

    def test_regular_sale_and_minimum_bid_both_qualify(self):
        self.assertTrue(assess(listing(), {}, NOW)["eligible"])
        bid = listing(price_kind="minimum_bid", bid_end="202611101200")
        self.assertTrue(assess(bid, {}, NOW)["eligible"])

    def test_filtering_incompatible_assets(self):
        cases = [dict(city="부산광역시"), dict(category="residential"), dict(transaction="rental"),
                 dict(status="sold"), dict(sale_scope="unit"), dict(sale_scope="share"),
                 dict(appraisal_scope="building_only"), dict(property_id=""), dict(price_kind="unit_price"),
                 dict(flags=("share",)), dict(flags=("bundle",))]
        for change in cases:
            with self.subTest(change=change):
                self.assertFalse(assess(listing(**change), {}, NOW)["eligible"])

    def test_unsubstantiated_appraisal_never_alerts(self):
        cases = [dict(appraisal_krw=None), dict(appraisal_verified=False), dict(appraisal_kind="ai_estimate"),
                 dict(appraisal_kind="tax_assessment"), dict(appraisal_evidence_url=""), dict(appraisal_date=""),
                 dict(appraisal_evidence_url="javascript:alert(1)")]
        for change in cases:
            with self.subTest(change=change):
                self.assertFalse(assess(listing(**change), {}, NOW)["eligible"])

    def test_stale_and_future_observations_and_appraisals(self):
        for change in [dict(observed_at=(NOW - timedelta(days=8)).isoformat()),
                       dict(observed_at=(NOW + timedelta(days=1)).isoformat()),
                       dict(appraisal_date="2024-01-01"), dict(appraisal_date="2026-11-04")]:
            with self.subTest(change=change):
                self.assertFalse(assess(listing(**change), {}, NOW)["eligible"])

    def test_expired_bids_are_excluded(self):
        for end in ["", "invalid", "202611030900", "202611020900"]:
            self.assertFalse(assess(listing(price_kind="minimum_bid", bid_end=end), {}, NOW)["eligible"])

    def test_private_contract_can_have_no_deadline(self):
        self.assertTrue(assess(listing(price_kind="minimum_bid", status="private_contract"), {}, NOW)["eligible"])

    def test_money_does_not_guess_units_or_hidden_prices(self):
        self.assertEqual(money("3,000,000,000원"), 3_000_000_000)
        for value in ["30억", "비공개", "3,000,000원/㎡", "약 3000000000", "3-5억원", "1,23", 0, -1, True, 1.5, "NaN"]:
            self.assertIsNone(money(value), value)

    def test_invalid_threshold(self):
        for value in [0, 100, "NaN", "Infinity"]:
            with self.assertRaises(ValueError):
                assess(listing(), {"discount_percent": value}, NOW)

    def test_identity_review_and_appraisal_conflicts(self):
        raw = normalize_onbid(onbid_item(), NOW.isoformat())
        review = {"property_id": "property-1", "sale_scope": "whole_property", "category": "commercial",
                  "appraisal_krw": "5000000000", "appraisal_date": "2026-10-01", "appraisal_scope": "whole_property",
                  "appraisal_kind": "formal", "appraisal_verified": "true", "appraisal_evidence_url": "https://example.invalid/appraisal/1"}
        reviewed = apply_review(raw, {raw.key: review})
        self.assertTrue(assess(reviewed, {}, NOW)["eligible"])
        bad_value = apply_review(raw, {raw.key: {**review, "appraisal_krw": "9000000000"}})
        self.assertFalse(assess(bad_value, {}, NOW)["eligible"])
        bad_identity = apply_review(listing(), {listing().key: review | {"property_id": "other-property"}})
        self.assertFalse(assess(bad_identity, {}, NOW)["eligible"])
        no_amount = {k: v for k, v in review.items() if k != "appraisal_krw"}
        self.assertFalse(assess(apply_review(raw, {raw.key: no_amount}), {}, NOW)["eligible"])

    def test_deduplication_uses_property_and_economic_values(self):
        self.assertEqual(fingerprint(listing()), fingerprint(listing(source="other", listing_id="other-id")))
        self.assertNotEqual(fingerprint(listing()), fingerprint(listing(price_krw=2_900_000_000)))
        self.assertNotEqual(fingerprint(listing()), fingerprint(listing(round_id="new-round")))


class SourceTests(unittest.TestCase):
    def test_json_singleton_and_empty_items(self):
        records, total = parse_onbid_response(response(onbid_item(), 1))
        self.assertEqual(total, 1)
        self.assertEqual(records[0]["cltrMngNo"], "demo-management-id")
        self.assertEqual(parse_onbid_response(response([], 0)), ([], 0))

    def test_xml_success_and_error_envelope(self):
        raw = b'<response><header><resultCode>00</resultCode></header><body><items><item><cltrMngNo>demo</cltrMngNo></item></items><totalCount>1</totalCount></body></response>'
        self.assertEqual(parse_onbid_response(raw), ([{"cltrMngNo": "demo"}], 1))
        with self.assertRaisesRegex(SourceError, "30"):
            parse_onbid_response(b'<OpenAPI_ServiceResponse><cmmMsgHeader><returnReasonCode>30</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>')

    def test_malformed_response_is_not_an_empty_success(self):
        for raw in [b'<html>blocked</html>', b'{}', b'{"header":{"resultCode":"00"},"body":{}}']:
            with self.assertRaises(SourceError):
                parse_onbid_response(raw)

    def test_onbid_requires_scope_review_and_excludes_hidden_prices(self):
        raw = normalize_onbid(onbid_item(), NOW.isoformat())
        self.assertFalse(assess(raw, {}, NOW)["eligible"])
        self.assertIsNone(normalize_onbid(onbid_item(lowstBidPrcIndctCont="비공개"), NOW.isoformat()).price_krw)
        self.assertIn("share", normalize_onbid(onbid_item(alcYn="Y"), NOW.isoformat()).flags)
        self.assertIn("unit_price", normalize_onbid(onbid_item(totalamtUnpcDivCd="0002"), NOW.isoformat()).flags)

    def test_request_parameters_pagination_and_encoded_key(self):
        requests = []
        def opener(req, timeout):
            query = parse_qs(urlsplit(req.full_url).query)
            requests.append(query)
            self.assertEqual(query["serviceKey"], ["test+key/value="])
            self.assertEqual(query["lctnSdnm"], ["서울특별시"])
            self.assertEqual(query["dspsMthodCd"], ["0001"])
            self.assertTrue(req.full_url.startswith("https://apis.data.go.kr/B010003/OnbidRlstListSrvc2/getRlstCltrList2?"))
            p = query["pageNo"][0]
            items = [onbid_item(cltrMngNo="demo-" + p)] if query["pvctTrgtYn"] == ["N"] else []
            return BytesIO(response(items, 2 if items else 0))
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"ONBID_SERVICE_KEY": "test%2Bkey%2Fvalue%3D"}):
            store = Store(Path(directory) / "state.db")
            try:
                records = fetch_onbid({"rows_per_page": 1, "request_delay_seconds": 0}, store, opener)
                self.assertEqual(len(records), 2)
                self.assertEqual(len(requests), 3)
            finally:
                store.close()

    def test_page_limit_is_an_error(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"ONBID_SERVICE_KEY": "test-key"}):
            store = Store(Path(directory) / "state.db")
            try:
                with self.assertRaisesRegex(SourceError, "incomplete"):
                    fetch_onbid({"rows_per_page": 1, "max_pages_per_query": 1, "request_delay_seconds": 0}, store,
                                lambda req, timeout: BytesIO(response([onbid_item()], 2)))
            finally:
                store.close()

    def test_daily_budget_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.db"
            first = Store(path)
            first.reserve_request("onbid", 1)
            first.close()
            second = Store(path)
            try:
                with self.assertRaisesRegex(ValueError, "budget"):
                    second.reserve_request("onbid", 1)
            finally:
                second.close()

    def test_csv_feed_preserves_observation_and_missing_appraisal(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "feed.csv").write_text('listing_id,title,address,city,category,transaction,status,price_krw,price_kind,source_url,observed_at\n1,Synthetic building,Seoul,Seoul,office,sale,active,3000000000,asking_price,https://example.invalid/1,2026-10-01T00:00:00Z\n')
            item = fetch_feed({"name": "broker", "path": "feed.csv"}, base)[0]
            self.assertEqual(item.observed_at, "2026-10-01T00:00:00Z")
            self.assertIsNone(item.appraisal_krw)
            self.assertFalse(assess(item, {}, NOW)["eligible"])

    def test_duplicate_review_rows_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reviews.csv"
            path.write_text('source,listing_id,property_id\nbroker,1,property-1\nbroker,1,property-2\n')
            with self.assertRaises(ValueError):
                load_reviews(path)

    def test_literal_env_does_not_execute_shell_content(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / ".env"
            path.write_text('MONITOR_TEST="$(touch should-not-exist)"\n')
            load_env(path)
            self.assertEqual(os.environ["MONITOR_TEST"], "$(touch should-not-exist)")
            self.assertFalse((Path(directory) / "should-not-exist").exists())

    def test_remote_feed_cannot_redirect_credentials_to_another_origin(self):
        handler = FeedRedirectHandler()
        req = Request("https://supplier.example/feed", headers={"Authorization": "Bearer test-token"})
        for target in ["https://other.example/feed", "http://supplier.example/feed"]:
            with self.assertRaises(SourceError):
                handler.redirect_request(req, None, 302, "Found", {}, target)
        redirected = handler.redirect_request(req, None, 302, "Found", {}, "https://supplier.example/new-feed")
        self.assertEqual(redirected.get_header("Authorization"), "Bearer test-token")


class DeliveryTests(unittest.TestCase):
    def test_end_to_end_delivery_dedup_and_new_price(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(StringIO()):
            base = Path(directory)
            now = datetime.now(timezone.utc)
            row = asdict(listing(now=now))
            feed = base / "feed.json"
            feed.write_text(json.dumps([row, {**row, "listing_id": "duplicate"}]))
            config = {"feeds": [{"name": "broker", "path": "feed.json"}]}
            messages = []
            self.assertEqual(run_once(config, base, True, lambda m, s: messages.append(m)), 0)
            self.assertEqual(messages, [])
            self.assertTrue((base / "data/email-preview.eml").exists())
            self.assertEqual(run_once(config, base, False, lambda m, s: messages.append(m)), 0)
            self.assertEqual(len(messages), 1)
            self.assertIn("1 listing(s)", str(messages[0]["Subject"]))
            self.assertEqual(run_once(config, base, False, lambda m, s: messages.append(m)), 0)
            self.assertEqual(len(messages), 1)
            feed.write_text(json.dumps([{**row, "price_krw": 2_900_000_000}]))
            self.assertEqual(run_once(config, base, False, lambda m, s: messages.append(m)), 0)
            self.assertEqual(len(messages), 2)

    def test_failed_delivery_retries_without_marking_sent(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(StringIO()):
            base = Path(directory)
            (base / "feed.json").write_text(json.dumps([asdict(listing(now=datetime.now(timezone.utc)))]))
            config = {"feeds": [{"name": "broker", "path": "feed.json"}]}
            def fail(message, settings):
                raise OSError("test failure")
            self.assertEqual(run_once(config, base, False, fail), 1)
            messages = []
            self.assertEqual(run_once(config, base, False, lambda m, s: messages.append(m)), 0)
            self.assertEqual(len(messages), 1)

    def test_one_failed_source_does_not_block_a_healthy_feed(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(StringIO()), patch.dict(os.environ, {"ONBID_SERVICE_KEY": ""}):
            base = Path(directory)
            (base / "feed.json").write_text(json.dumps([asdict(listing(now=datetime.now(timezone.utc)))]))
            config = {"onbid": {"enabled": True}, "feeds": [{"name": "broker", "path": "feed.json"}]}
            messages = []
            self.assertEqual(run_once(config, base, False, lambda m, s: messages.append(m)), 1)
            health = json.loads((base / "data/health.json").read_text())
            self.assertEqual(health["sources"][0]["status"], "error")
            self.assertEqual(len(messages), 1)

    def test_no_sources_is_not_successful_monitoring(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(StringIO()):
            self.assertEqual(run_once({}, Path(directory), True), 1)

    def test_email_distinguishes_minimum_bid_from_asking_price(self):
        result = assess(listing(price_kind="minimum_bid", bid_end="202611101200"), {}, NOW)
        message = build_email([result], {}, 40)
        self.assertIn("final winning price may be higher", message.get_content())
        self.assertIn("2026-10-04", message.get_content())

    def test_smtp_uses_starttls_before_login_and_explicit_recipient(self):
        calls = []
        class SMTP:
            def __init__(self, *args, **kwargs): calls.append("connect")
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def ehlo(self): calls.append("ehlo")
            def starttls(self, **kwargs): calls.append("tls")
            def login(self, *args): calls.append("login")
            def send_message(self, message, from_addr, to_addrs):
                calls.append("send")
                self.assert_recipient = to_addrs
                if to_addrs != ["recipient@example.test"]: raise AssertionError(to_addrs)
                return {}
        env = dict(SMTP_HOST="smtp.example.test", SMTP_USERNAME="test", SMTP_PASSWORD="test-password",
                   EMAIL_FROM="sender@example.test", EMAIL_TO="recipient@example.test")
        with patch.dict(os.environ, env):
            message = build_email([assess(listing(), {}, NOW)], {}, 40)
            send_email(message, {"tls": "starttls"}, smtp=SMTP)
        self.assertLess(calls.index("tls"), calls.index("login"))
        self.assertEqual(calls[-1], "send")


if __name__ == "__main__":
    unittest.main()
