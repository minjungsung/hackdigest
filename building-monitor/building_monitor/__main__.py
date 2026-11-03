import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
import time

from .core import Listing, apply_review, assess, fingerprint
from .notifications import build_email, send_email
from .sources import SourceError, fetch_feed, fetch_onbid, read_records
from .store import Store


def load_env(path):
    """Load literal KEY=VALUE pairs without shell evaluation."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not key.strip().replace("_", "").isalnum() or key.strip()[0].isdigit():
            raise ValueError("Invalid .env entry")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
        temporary = Path(f.name)
    temporary.replace(path)


def load_reviews(path):
    reviews = {}
    for row in read_records(path):
        key = f"{row.get('source', '')}:{row.get('listing_id', '')}"
        if not row.get("source") or not row.get("listing_id") or key in reviews:
            raise ValueError("Review rows require unique source and listing_id pairs")
        reviews[key] = row
    return reviews


def run_once(config, base, dry_run=False, sender=send_email):
    data_dir = base / config.get("data_dir", "data")
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / "monitor.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another monitor run is already active") from None
        store = Store(data_dir / "state.sqlite3")
        try:
            return collect_and_notify(config, base, data_dir, store, dry_run, sender)
        finally:
            store.close()


def collect_and_notify(config, base, data_dir, store, dry_run, sender):
    now = datetime.now(timezone.utc)
    listings, source_health = [], []
    sources = []
    if config.get("onbid", {}).get("enabled"):
        sources.append(("onbid", lambda: fetch_onbid(config["onbid"], store)))
    feed_names = set()
    for feed in config.get("feeds", []):
        if feed.get("enabled", True):
            if feed.get("name") in feed_names or feed.get("name") == "onbid":
                raise ValueError("Enabled source names must be unique")
            feed_names.add(feed.get("name"))
            sources.append((feed.get("name", "unnamed"), lambda feed=feed: fetch_feed(feed, base)))
    reviews = load_reviews(base / config["reviews_path"]) if config.get("reviews_path") else {}
    for name, fetch in sources:
        try:
            found = fetch()
            listings.extend(apply_review(item, reviews) for item in found)
            source_health.append({"source": name, "status": "ok", "count": len(found)})
        except SourceError as exc:
            source_health.append({"source": name, "status": "error", "error_type": type(exc).__name__, "message": str(exc)})
        except (ValueError, OSError, RuntimeError) as exc:
            source_health.append({"source": name, "status": "error", "error_type": type(exc).__name__})
        except Exception as exc:
            # Provider messages and tracebacks can contain credential-bearing URLs.
            source_health.append({"source": name, "status": "error", "error_type": type(exc).__name__})
    assessments = [assess(item, config.get("policy", {}), now) for item in listings]
    pending, pending_ids = [], set()
    for listing, result in zip(listings, assessments):
        token = fingerprint(listing)
        if result["eligible"] and token not in pending_ids and not store.seen(token):
            pending.append(result)
            pending_ids.add(token)
    delivery, delivery_error = "no_new_matches", None
    if pending:
        message = build_email(pending, config.get("email", {}), config.get("policy", {}).get("discount_percent", 40))
        if dry_run:
            (data_dir / "email-preview.eml").write_bytes(message.as_bytes())
            delivery = "preview_saved"
        else:
            try:
                sender(message, config.get("email", {}))
            except Exception as exc:
                delivery, delivery_error = "failed", type(exc).__name__
            else:
                store.mark_sent(pending_ids)
                delivery = "sent"
    snapshot = {"checked_at": now.isoformat(), "dry_run": dry_run, "sources": source_health,
                "listings": assessments, "delivery": delivery}
    write_json(data_dir / "latest.json", snapshot)
    summary = {"checked_at": now.isoformat(), "sources": source_health, "collected": len(listings),
               "eligible": sum(r["eligible"] for r in assessments), "new_matches": len(pending),
               "delivery": delivery, "delivery_error_type": delivery_error,
               "exclusion_counts": dict(Counter(reason for r in assessments for reason in r["reasons"])),
               "coverage": {"general_sale": "configured_feeds_only" if feed_names else "not_connected",
                            "court_auction": "not_connected",
                            "onbid": "configured" if config.get("onbid", {}).get("enabled") else "not_connected"}}
    write_json(data_dir / "health.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if not sources or any(x["status"] == "error" for x in source_health) or delivery == "failed" else 0


def demo(base):
    now = datetime.now(timezone.utc)
    common = dict(title="Synthetic Seoul commercial building — demonstration only", address="Seoul (synthetic example)",
                  city="Seoul", category="commercial", transaction="sale", status="active", price_kind="asking_price",
                  source_url="https://example.invalid/listing/demo", observed_at=now.isoformat(),
                  property_id="demo-property", sale_scope="whole_property", appraisal_krw=5_000_000_000,
                  appraisal_date=(now - timedelta(days=30)).date().isoformat(), appraisal_scope="whole_property",
                  appraisal_kind="formal", appraisal_verified=True, appraisal_evidence_url="https://example.invalid/appraisal/demo")
    sample = [asdict(Listing(source="demo", listing_id="exact-40", price_krw=3_000_000_000, **common)),
              asdict(Listing(source="demo", listing_id="below-40", price_krw=3_000_000_001, **{**common, "property_id": "demo-below"})),
              asdict(Listing(source="demo", listing_id="missing-appraisal", price_krw=2_000_000_000, **{**common, "property_id": "demo-missing", "appraisal_krw": None, "appraisal_verified": False})),
              asdict(Listing(source="demo", listing_id="unit", price_krw=2_000_000_000, **{**common, "property_id": "demo-unit", "sale_scope": "unit"}))]
    write_json(base / "data/demo/listings.json", sample)
    return run_once({"data_dir": "data/demo", "policy": {"discount_percent": 40},
                     "feeds": [{"name": "demo", "path": "data/demo/listings.json"}]}, base, dry_run=True)


def main():
    parser = argparse.ArgumentParser(description="Seoul whole-building appraisal discount monitor")
    parser.add_argument("command", choices=["demo", "run", "watch"])
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--dry-run", action="store_true", help="Save email preview without sending or marking alerts sent")
    parser.add_argument("--interval", type=int, default=3600, help="Polling interval in seconds (minimum 300)")
    args = parser.parse_args()
    os.umask(0o077)
    if args.command == "demo":
        return demo(Path.cwd())
    config_path = Path(args.config).resolve()
    base = config_path.parent
    load_env(base / ".env")
    with config_path.open() as f:
        config = json.load(f)
    if args.command == "run":
        return run_once(config, base, args.dry_run)
    if args.interval < 300:
        raise ValueError("Polling interval must be at least 300 seconds")
    while True:
        run_once(config, base, args.dry_run)
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        print(f"Monitor stopped: {type(exc).__name__}. Check configuration and input formats.", file=sys.stderr)
        sys.exit(1)
