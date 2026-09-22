"""Send digest notifications via email or Teams webhook."""

import logging
import smtplib
import time
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

from src.models import Article

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
MAX_RETRIES = 3


def _build_html(articles: list[Article]) -> str:
    """Build an HTML email body from articles."""
    today = datetime.now(KST).strftime("%Y-%m-%d")
    html_parts = [
        f"""
        <html><body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 700px; margin: 0 auto; padding: 20px;">
        <h1 style="color: #ff6600; border-bottom: 2px solid #ff6600; padding-bottom: 10px;">
            🔥 Hacker News Daily Top 5 — {today}
        </h1>
        """
    ]

    for i, article in enumerate(articles, 1):
        html_parts.append(f"""
        <div style="margin: 20px 0; padding: 15px; background: #f8f9fa; border-radius: 8px; border-left: 4px solid #ff6600;">
            <h2 style="margin: 0 0 8px 0; font-size: 18px;">
                #{i} <a href="{article.url}" style="color: #1a1a1a; text-decoration: none;">{article.title}</a>
            </h2>
            <p style="margin: 4px 0; color: #666; font-size: 14px;">
                ⬆ {article.score} points | 💬 {article.comment_count} comments |
                <a href="{article.hn_url}" style="color: #ff6600;">HN Discussion</a>
            </p>
            <p style="margin: 10px 0 0 0; color: #333; font-size: 14px; line-height: 1.6;">
                {article.summary}
            </p>
        </div>
        """)

    html_parts.append("</body></html>")
    return "".join(html_parts)


def send_email(
    articles: list[Article],
    to_email: str,
    smtp_host: str = "smtp.gmail.com",
    smtp_port: int = 587,
    from_email: str = "",
    app_password: str = "",
) -> None:
    """Send digest as HTML email via SMTP."""
    today = datetime.now(KST).strftime("%Y-%m-%d")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🔥 HackDigest — Hacker News Top 5 ({today})"
    msg["From"] = from_email
    msg["To"] = to_email

    html_body = _build_html(articles)
    msg.attach(MIMEText(html_body, "html"))

    logger.info("Sending email to %s...", to_email)
    try:
        # Try SSL first (port 465) - works on networks that block port 587
        with smtplib.SMTP_SSL(smtp_host, 465, timeout=30) as server:
            server.login(from_email, app_password)
            server.send_message(msg)
    except Exception as ssl_err:
        logger.warning("SMTP_SSL failed: %s. Trying STARTTLS on port %d...", ssl_err, smtp_port)
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.starttls()
            server.login(from_email, app_password)
            server.send_message(msg)

    logger.info("Email sent successfully!")


def send_to_teams(articles: list[Article], webhook_url: str) -> None:
    """Send digest as Adaptive Card to Teams Incoming Webhook."""
    today = datetime.now(KST).strftime("%Y-%m-%d")

    body_items = [
        {
            "type": "TextBlock",
            "text": f"🔥 Hacker News Daily Top 5 — {today}",
            "weight": "Bolder",
            "size": "Large",
        }
    ]

    for i, article in enumerate(articles, 1):
        body_items.extend([
            {"type": "TextBlock", "text": "---", "spacing": "Medium"},
            {
                "type": "TextBlock",
                "text": f"**#{i} [{article.title}]({article.url})**",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": f"⬆ {article.score} | 💬 {article.comment_count} | [HN Discussion]({article.hn_url})",
                "spacing": "None",
                "isSubtle": True,
            },
            {
                "type": "TextBlock",
                "text": article.summary,
                "wrap": True,
                "spacing": "Small",
            },
        ])

    card = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": body_items,
                },
            }
        ],
    }

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(webhook_url, json=card, timeout=10)
            resp.raise_for_status()
            logger.info("Teams notification sent successfully!")
            return
        except requests.RequestException as e:
            logger.warning("Teams send failed (attempt %d/%d): %s", attempt + 1, MAX_RETRIES, e)
            if attempt < MAX_RETRIES - 1:
                time.sleep(1)
            else:
                raise
