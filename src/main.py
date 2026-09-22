"""HackDigest — Hacker News Daily Top 5 digest."""

import logging
import os
import sys

from src.fetcher import fetch_top_articles
from src.summarizer import summarize
from src.notifier import send_to_teams, send_email

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    # 1. Fetch top articles
    articles = fetch_top_articles(count=5)
    if not articles:
        logger.warning("No articles fetched. Skipping notification.")
        return

    # 2. Summarize each article
    for article in articles:
        summarize(article)

    # 3. Send notification
    webhook_url = os.environ.get("TEAMS_WEBHOOK_URL")
    email_to = os.environ.get("EMAIL_TO")
    email_from = os.environ.get("EMAIL_FROM")
    email_password = os.environ.get("EMAIL_APP_PASSWORD")

    sent = False

    if webhook_url:
        try:
            send_to_teams(articles, webhook_url)
            sent = True
        except Exception as e:
            logger.error("Failed to send Teams notification: %s", e)

    if email_to and email_from and email_password:
        try:
            send_email(articles, to_email=email_to, from_email=email_from, app_password=email_password)
            sent = True
        except Exception as e:
            logger.error("Failed to send email: %s", e)

    if not sent:
        logger.error("No notification channel configured or all channels failed.")
        sys.exit(1)

    logger.info("Done!")


if __name__ == "__main__":
    main()
