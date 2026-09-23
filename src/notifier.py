"""Send digest notifications via email."""

import logging
import smtplib
import time
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

from src.models import Article, Language, Subscriber, Topic

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
MAX_RETRIES = 3


def _build_html(articles: list[Article], language: Language = Language.KO, welcome_message: str = "", recipient_email: str = "") -> str:
    """Build a mobile-friendly HTML email body from articles."""
    today = datetime.now(KST).strftime("%Y-%m-%d")

    header_text = "Hacker News Daily Top 5" if language == Language.EN else "Hacker News 데일리 Top 5"

    # Build unsubscribe URL
    unsub_url = f"https://minjungsung.github.io/hackdigest/?action=unsubscribe&email={recipient_email}" if recipient_email else ""

    rows = ""

    if welcome_message:
        rows += f"""
        <div style="margin: 0 0 24px 0; padding: 16px; background: #fff8f0;
                    border-radius: 10px; border: 1px solid #ff6600;">
            <div style="font-size: 15px; color: #333; line-height: 1.7;">
                {welcome_message}
            </div>
        </div>
        """

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
                ⬆ {article.score} {"pts" if language == Language.EN else "점"} &nbsp;&bull;&nbsp;
                💬 {article.comment_count} {"comments" if language == Language.EN else "댓글"} &nbsp;&bull;&nbsp;
                <a href="{article.hn_url}" style="color: #ff6600; text-decoration: none;">
                    {"Discussion →" if language == Language.EN else "토론 →"}
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
                    {header_text} &mdash; {today}
                </div>
            </div>

            <!-- Body -->
            <div style="background: #f5f5f5; padding: 20px 16px; border-radius: 0 0 12px 12px;">
                {rows}
            </div>

            <!-- Footer -->
            <div style="text-align: center; font-size: 11px; color: #aaa;
                        margin-top: 16px; padding-bottom: 20px;">
                {"Delivered daily" if language == Language.EN else "매일 배달"} &middot; Powered by
                <a href="https://news.ycombinator.com"
                   style="color: #ff6600; text-decoration: none;">Hacker News</a>
                {f'<br><a href="{unsub_url}" style="color: #888; text-decoration: underline;">{"Unsubscribe" if language == Language.EN else "구독 해제"}</a>' if unsub_url else ''}
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


def _topic_label(topic: Topic | None) -> dict:
    """Return display label and emoji for a topic."""
    labels = {
        Topic.TECH: {"emoji": "💻", "name_ko": "기술", "name_en": "Tech", "source": "Hacker News"},
        Topic.STOCKS: {"emoji": "📈", "name_ko": "주식", "name_en": "Stocks", "source": "Yahoo Finance"},
        Topic.REALESTATE: {"emoji": "🏠", "name_ko": "부동산", "name_en": "Real Estate", "source": "Zillow · HousingWire · CNBC"},
    }
    return labels.get(topic, {"emoji": "🔥", "name_ko": "뉴스", "name_en": "News", "source": ""})


def send_email_to_subscriber(
    articles: list[Article],
    subscriber: Subscriber,
    from_email: str = "",
    app_password: str = "",
    topic: Topic | None = None,
    smtp_host: str = "smtp.gmail.com",
    smtp_port: int = 587,
) -> None:
    """Send digest articles to a single subscriber. If topic is specified, filter for that topic."""
    if topic:
        filtered = [a for a in articles if a.topic == topic]
    else:
        filtered = [a for a in articles if a.topic in subscriber.topics]

    if not filtered:
        logger.info("No matching articles for subscriber %s (topic: %s)", subscriber.email, topic)
        return

    today = datetime.now(KST).strftime("%Y-%m-%d")
    label = _topic_label(topic)
    topic_name = label['name_en'] if subscriber.language == Language.EN else label['name_ko']

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{label['emoji']} HackDigest {topic_name} ({today})"
    msg["From"] = from_email
    msg["To"] = subscriber.email

    html_body = _build_html(filtered, language=subscriber.language, recipient_email=subscriber.email)
    msg.attach(MIMEText(html_body, "html"))

    logger.info("Sending email to subscriber %s (lang=%s, topics=%s)...",
                subscriber.email, subscriber.language.value, [t.value for t in subscriber.topics])
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

    logger.info("Email sent successfully to subscriber %s!", subscriber.email)


def send_welcome_email(
    subscriber: Subscriber,
    articles: list[Article],
    from_email: str = "",
    app_password: str = "",
    smtp_host: str = "smtp.gmail.com",
    smtp_port: int = 587,
) -> None:
    """Send a welcome email to a newly added subscriber with today's cached articles."""
    filtered = [a for a in articles if a.topic in subscriber.topics]

    if subscriber.language == Language.EN:
        subject = "🔥 Welcome to HackDigest!"
        welcome_message = (
            "Welcome to HackDigest! 🎉 You'll receive a daily digest of the top Hacker News stories "
            "delivered straight to your inbox every morning. Here's today's edition to get you started:"
        )
    else:
        subject = "🔥 HackDigest에 오신 것을 환영합니다!"
        welcome_message = (
            "HackDigest에 오신 것을 환영합니다! 🎉 매일 아침 Hacker News의 인기 기사를 "
            "요약해서 보내드릴게요. 오늘의 소식부터 시작해 볼까요:"
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = subscriber.email

    html_body = _build_html(filtered, language=subscriber.language, welcome_message=welcome_message, recipient_email=subscriber.email)
    msg.attach(MIMEText(html_body, "html"))

    logger.info("Sending welcome email to %s (lang=%s)...", subscriber.email, subscriber.language.value)
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

    logger.info("Welcome email sent successfully to %s!", subscriber.email)


def send_goodbye_email(
    email: str,
    language: str = "ko",
    from_email: str = "",
    app_password: str = "",
    smtp_host: str = "smtp.gmail.com",
    smtp_port: int = 587,
) -> None:
    """Send a goodbye email to an unsubscribed user."""
    today = datetime.now(KST).strftime("%Y-%m-%d")
    resubscribe_url = "https://minjungsung.github.io/hackdigest/"

    if language == "en":
        subject = "👋 You've been unsubscribed from HackDigest"
        body_html = f"""
        <div style="font-size: 15px; color: #333; line-height: 1.7;">
            <p>You've been successfully unsubscribed from HackDigest.</p>
            <p>We're sorry to see you go! 😢</p>
            <p>If you ever want to come back, you can resubscribe anytime:</p>
            <p style="text-align: center; margin: 24px 0;">
                <a href="{resubscribe_url}" style="background: #ff6600; color: white;
                   padding: 12px 24px; border-radius: 8px; text-decoration: none;
                   font-weight: 600;">Resubscribe</a>
            </p>
        </div>
        """
    else:
        subject = "👋 HackDigest 구독이 해제되었습니다"
        body_html = f"""
        <div style="font-size: 15px; color: #333; line-height: 1.7;">
            <p>HackDigest 구독이 정상적으로 해제되었습니다.</p>
            <p>아쉽지만 다음에 또 만나요! 😢</p>
            <p>다시 구독하고 싶으시면 언제든지:</p>
            <p style="text-align: center; margin: 24px 0;">
                <a href="{resubscribe_url}" style="background: #ff6600; color: white;
                   padding: 12px 24px; border-radius: 8px; text-decoration: none;
                   font-weight: 600;">다시 구독하기</a>
            </p>
        </div>
        """

    full_html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
    <body style="margin: 0; padding: 0; background: #f0f0f0;
                 font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
        <div style="max-width: 600px; margin: 0 auto; padding: 16px;">
            <div style="background: #ff6600; padding: 24px 20px; border-radius: 12px 12px 0 0; text-align: center;">
                <div style="font-size: 26px; margin-bottom: 2px;">👋</div>
                <div style="color: white; font-size: 20px; font-weight: 700;">HackDigest</div>
            </div>
            <div style="background: #f5f5f5; padding: 20px 16px; border-radius: 0 0 12px 12px;">
                {body_html}
            </div>
        </div>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = email
    msg.attach(MIMEText(full_html, "html"))

    logger.info("Sending goodbye email to %s...", email)
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

    logger.info("Goodbye email sent to %s!", email)
