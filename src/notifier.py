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
    """Build a polished HTML email body from articles."""
    today = datetime.now(KST).strftime("%Y-%m-%d")

    badge_colors = ["#ff6600", "#ff8533", "#ffa366", "#ffc299", "#ffd9bf"]

    rows = ""
    for i, article in enumerate(articles, 1):
        color = badge_colors[i - 1] if i <= len(badge_colors) else "#ff6600"
        rows += f"""
        <tr>
            <td style="padding: 20px 24px; border-bottom: 1px solid #eee;">
                <table cellpadding="0" cellspacing="0" width="100%">
                    <tr>
                        <td width="40" valign="top">
                            <div style="background: {color}; color: white; width: 32px; height: 32px;
                                        border-radius: 50%; text-align: center; line-height: 32px;
                                        font-weight: bold; font-size: 14px;">{i}</div>
                        </td>
                        <td style="padding-left: 12px;">
                            <a href="{article.url}" style="color: #1a1a1a; text-decoration: none;
                                      font-size: 17px; font-weight: 600; line-height: 1.3;">
                                {article.title}
                            </a>
                            <div style="margin-top: 6px; font-size: 13px; color: #888;">
                                ⬆ {article.score} pts &nbsp;|&nbsp;
                                💬 {article.comment_count} comments &nbsp;|&nbsp;
                                <a href="{article.hn_url}" style="color: #ff6600; text-decoration: none;">HN Discussion →</a>
                            </div>
                            <div style="margin-top: 10px; font-size: 14px; color: #444; line-height: 1.7;
                                        background: #fafafa; padding: 12px 14px; border-radius: 6px;
                                        border-left: 3px solid {color};">
                                {article.summary}
                            </div>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
        """

    return f"""
    <html>
    <body style="margin: 0; padding: 0; background: #f4f4f4;
                 font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
        <table cellpadding="0" cellspacing="0" width="100%"
               style="background: #f4f4f4; padding: 20px 0;">
            <tr><td align="center">
                <table cellpadding="0" cellspacing="0" width="640"
                       style="background: white; border-radius: 12px;
                              box-shadow: 0 2px 8px rgba(0,0,0,0.08); overflow: hidden;">
                    <!-- Header -->
                    <tr>
                        <td style="background: linear-gradient(135deg, #ff6600, #ff8533);
                                   padding: 28px 24px; text-align: center;">
                            <div style="font-size: 28px; margin-bottom: 4px;">🔥</div>
                            <div style="color: white; font-size: 22px; font-weight: 700;">HackDigest</div>
                            <div style="color: rgba(255,255,255,0.85); font-size: 14px; margin-top: 4px;">
                                Hacker News Daily Top 5 &mdash; {today}
                            </div>
                        </td>
                    </tr>
                    <!-- Articles -->
                    {rows}
                    <!-- Footer -->
                    <tr>
                        <td style="padding: 16px 24px; text-align: center;
                                   font-size: 12px; color: #aaa; border-top: 1px solid #eee;">
                            Delivered daily &middot; Powered by
                            <a href="https://news.ycombinator.com"
                               style="color: #ff6600; text-decoration: none;">Hacker News</a>
                        </td>
                    </tr>
                </table>
            </td></tr>
        </table>
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
    msg["Subject"] = f"\U0001f525 HackDigest \u2014 Hacker News Top 5 ({today})"
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
                    f" | [HN Discussion]({article.hn_url})"
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
