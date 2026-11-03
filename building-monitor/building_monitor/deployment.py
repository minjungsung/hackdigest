"""Run the monitor with the existing HackDigest GitHub Actions mail secrets."""

import argparse
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
import json
import os
from pathlib import Path
import sys

from .__main__ import run_once, write_json
from .notifications import send_email


def prepare_config(base):
    config = json.loads((base / "config.example.json").read_text())
    config["data_dir"] = "data/cloud"
    config["reviews_path"] = "data/cloud/reviews.csv"
    config["email"]["password_env"] = "EMAIL_APP_PASSWORD"
    config["email"]["to_env"] = "BUILDING_ALERT_TO"
    os.environ.setdefault("SMTP_HOST", "smtp.gmail.com")
    os.environ.setdefault("SMTP_USERNAME", os.environ.get("EMAIL_FROM", ""))
    review_path = base / config["reviews_path"]
    review_path.parent.mkdir(parents=True, exist_ok=True)
    reviews = os.environ.get("BUILDING_REVIEWS_CSV", "")
    if not reviews:
        reviews = (base / "examples/reviews.csv").read_text()
    review_path.write_text(reviews)
    if os.environ.get("BUILDING_FEED_URL"):
        config["feeds"] = [{"name": "broker-feed", "url": os.environ["BUILDING_FEED_URL"]}]
        if os.environ.get("BUILDING_FEED_TOKEN"):
            config["feeds"][0]["token_env"] = "BUILDING_FEED_TOKEN"
    return config


def waiting_report(config):
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "collection_status": "awaiting_onbid_credentials",
        "sources": [{"source": "onbid", "status": "blocked", "message": "The public-data portal service key has not been connected."}],
        "collected": 0,
        "eligible": 0,
        "new_matches": 0,
        "delivery": "no_listing_collection",
        "coverage": {"general_sale": "configured_feeds_only" if config["feeds"] else "not_connected", "court_auction": "not_connected"},
    }


def status_email(report, config):
    message = EmailMessage()
    message["From"] = os.environ.get("EMAIL_FROM", "monitor@example.invalid")
    message["To"] = os.environ.get("BUILDING_ALERT_TO", "recipient@example.invalid")
    message["Subject"] = "Seoul building monitor: deployment and collection status"
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(domain="building-monitor.invalid")
    lines = [
        "The hourly GitHub Actions runner has been deployed.",
        "This message verifies the existing HackDigest Gmail delivery route.",
        "", "Search: Seoul commercial and office whole-building sales.",
        "Alert rule: asking price or minimum bid at least 40% below a verified whole-property formal appraisal.",
        "Schedule: hourly; GitHub may delay scheduled runs.",
        f"Last attempt: {report['checked_at']}",
        f"Collected listings: {report.get('collected', 0)}",
        f"Eligible listings: {report.get('eligible', 0)}", "",
    ]
    for source in report.get("sources", []):
        lines.append(f"Source {source['source']}: {source['status']}")
        if source.get("message"):
            lines.append(source["message"])
    coverage = report.get("coverage", {})
    lines.extend(["", f"Regular-sale supply: {coverage.get('general_sale', 'not_connected')}",
                  f"Court-auction supply: {coverage.get('court_auction', 'not_connected')}"])
    if report.get("collection_status") == "awaiting_onbid_credentials":
        lines.extend(["", "Listing monitoring has NOT started: the Onbid service key is still required.",
                      "The runner will collect listings after the approved key is connected."])
    else:
        lines.extend(["", "Only successfully collected sources are monitored.",
                      "Unconfirmed appraisal dates, property identities, or valuation scopes remain excluded from discount alerts."])
    message.set_content("\n".join(lines))
    return message


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=".")
    parser.add_argument("--send-status", action="store_true", help="Email a one-time deployment and actual collection status")
    args = parser.parse_args()
    os.umask(0o077)
    base = Path(args.base).resolve()
    config = prepare_config(base)
    if not os.environ.get("ONBID_SERVICE_KEY") and not config["feeds"]:
        report = waiting_report(config)
        write_json(base / config["data_dir"] / "health.json", report)
        print(json.dumps(report, indent=2))
        result = 0  # An explicit onboarding state, not successful collection.
    else:
        result = run_once(config, base)
        report = json.loads((base / config["data_dir"] / "health.json").read_text())
    if args.send_status:
        send_email(status_email(report, config), config["email"])
        print("Deployment status email accepted by the SMTP server.")
    return result


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"Cloud monitor stopped: {type(exc).__name__}. Check the protected configuration.", file=sys.stderr)
        sys.exit(1)
