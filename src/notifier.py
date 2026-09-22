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
    """Build a mobile-friendly HTML email body from articles."""
    today = datetime.now(KST).strftime("%Y-%m-%d")

    rows = ""
    for i, article in enumerate(articles, 1):
        rows += f"""
        <div style="margin: 0 0 24px 0; padding: 16px; background: #ffffff;
                    border-radius: 10px; border: 1px solid #e8e8e8;">
            <div style="display: flex; align-items: center; margin-bottom: 10px;">
                <span style="background: #ff6600; color: white; display: inline-block;
                             width: 28px; height: 28px; border-radius: 50%; text-align: center;
                             line-height: 28px; font-weight: bold; font-size: 14px;
                             margin-right: 10px; flex-shrink: 0;">{i}</span>
                <a href="{article.url}" style="color: #1a1a1a; text-decoration: none;
                          font-size: 16px; font-weight: 600; line-height: 1.4;">
                    {article.title}
                </a>
            </div>
            <div style="font-size: 13px; color: #888; margin-bottom: 12px;">
                ⬆ {article.score} pts &nbsp;&bull;&nbsp;
                💬 {article.comment_count} comments &nbsp;&bull;&nbsp;
                <a href="{article.hn_url}" style="color: #ff6600; text-decoration: none;">
                    Discussion →
                </a>
            </div>
            <div style="font-size: 15px; color: #333; line-height: 1.7;
                        padding: 12px 16px; background: #f9f9f9; border-radius: 8px;">
                {article.summary}
            </div>
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{ margin: 0; padding: 0; }}
            @media only screen and (max-width: 600px) {{
                .container {{ width: 100% !important; padding: 12px !important; }}
                .header {{ padding: 20px 16px !important; }}
                .card {{ padding: 14px !important; margin-bottom: 16px !important; }}
            }}
        </style>
    </head>
    <body style="margin: 0; padding: 0; background: #f0f0f0;
                 font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
                              'Helvetica Neue', Arial, sans-serif;">
        <div class="container" style="max-width: 600px; margin: 0 auto; padding: 16px;">
            <!-- Header -->
            <div class="header" style="background: #ff6600; padding: 24px 20px;
                        border-radius: 12px 12px 0 0; text-align: center;">
                <div style="font-size: 26px; margin-bottom: 2px;">🔥</div>
                <div style="color: white; font-size: 20px; font-weight: 700;">HackDigest</div>
                <div style="color: rgba(255,255,255,0.8); font-size: 13px; margin-top: 4px;">
                    Hacker News Daily Top 5 &mdash; {today}
                </div>
            </div>

            <!-- Body -->
            <div style="background: #f5f5f5; padding: 20px 16px; border-radius: 0 0 12px 12px;">
                {rows}
            </div>

            <!-- Footer -->
            <div style="text-align: center; font-size: 11px; color: #aaa;
                        margin-top: 16px; padding-bottom: 20px;">
                Delivered daily &middot; Powered by
                <a href="https://news.ycombinator.com"
                   style="color: #ff6600; text-decoration: none;">Hacker News</a>
            </div>
        </div>
    </body>
    </html>
    """


def send_email(
    articles: list[Article],
    to_emails: list[str],
    smtp_host: str = "smtp.gmail.com",
    smtp_port: int = 587,
    from_email: str = "",
    app_password: str = "",
) -> None:
    """Send digest as HTML email via SMTP to multiple recipients."""
    today = datetime.now(KST).strftime("%Y-%m-%d")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"\U0001f525 HackDigest ({today})"
    msg["From"] = from_email
    msg["To"] = ", ".join(to_emails)

    html_body = _build_html(articles)
    msg.attach(MIMEText(html_body, "html"))

    logger.info("Sending email to %s...", ", ".join(to_emails))
    try:
        with smtplib.SMTP_SSL(smtp_host, 465, timeout=30) as server:
            server.login(from_email, app_password)
            server.send_message(msg)
    except Exception as ssl_err:
        logger.warning("SMTP_SSL failed: %s. Trying STARTTLS on port %d...", ssl_err, smtp_port)
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.starttls()
            server.login(from_email, app_password)
            server.send_message(msg)

    logger.info("Email sent successfully to %d recipient(s)!", len(to_emails))


def send_to_teams(articles: list[Article], webhook_url: str) -> None:
    """Send digest as Adaptive Card to Teams Incoming Webhook."""
    today = datetime.now(KST).strftime("%Y-%m-%d")

    body_items = [
        {
            "type": "TextBlock",
            "text": f"\U0001f525 Hacker News Daily Top 5 \u2014 {today}",
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
                "text": (
                    f"\u2b06 {article.score} pts | \U0001f4ac {article.comment_count} comments"
                    f" | [Discussion]({article.hn_url})"
                ),
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
            logger.warning(
                "Teams send failed (attempt %d/%d): %s", attempt + 1, MAX_RETRIES, e
            )
            if attempt < MAX_RETRIES - 1:
                time.sleep(1)
            else:
                raise
