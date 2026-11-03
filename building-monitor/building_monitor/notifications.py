from decimal import Decimal
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
import os
import smtplib
import ssl


def build_email(assessments, settings, threshold):
    message = EmailMessage()
    message["Subject"] = f"Seoul building alert: {len(assessments)} listing(s) at least {threshold}% below appraisal"
    message["From"] = os.environ.get(settings.get("from_env", "EMAIL_FROM"), "monitor@example.invalid")
    message["To"] = os.environ.get(settings.get("to_env", "EMAIL_TO"), "recipient@example.invalid")
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(domain="building-monitor.invalid")
    parts = ["Seoul commercial / office buildings with documented whole-property appraisals.", ""]
    for result in assessments:
        row = result["listing"]
        label = "Asking price" if row["price_kind"] == "asking_price" else "Minimum bid (final winning price may be higher)"
        parts.extend([
            row["title"], row["address"],
            f"{label}: KRW {row['price_krw']:,}",
            f"Formal appraisal: KRW {row['appraisal_krw']:,} ({row['appraisal_date']})",
            f"Discount versus appraisal: {Decimal(result['discount_percent']):.2f}%",
            "Scope: entire property, including the land and building",
            f"Property ID: {row['property_id']}",
            f"Source: {row['source']} / {row['listing_id']}",
            f"Listing: {row['source_url']}",
            f"Appraisal evidence: {row['appraisal_evidence_url']}",
            f"Last observed: {row['observed_at']}",
        ])
        if row["bid_end"]:
            parts.append(f"Bid deadline (Asia/Seoul unless offset is supplied): {row['bid_end']}")
        if row["flags"]:
            parts.append("Source notes: " + ", ".join(row["flags"]))
        parts.append("")
    parts.append("This compares the advertised price with a dated appraisal; it does not establish current market value.")
    message.set_content("\n".join(parts))
    return message


def send_email(message, settings, smtp_ssl=smtplib.SMTP_SSL, smtp=smtplib.SMTP):
    def env(key, default):
        return os.environ.get(settings.get(key + "_env", default), "")
    host = env("host", "SMTP_HOST")
    username = env("username", "SMTP_USERNAME")
    password = env("password", "SMTP_PASSWORD")
    sender = env("from", "EMAIL_FROM")
    recipient = env("to", "EMAIL_TO")
    if not host or not sender or not recipient or "example.invalid" in sender + recipient:
        raise ValueError("SMTP_HOST, EMAIL_FROM and EMAIL_TO must be configured")
    if bool(username) != bool(password):
        raise ValueError("Configure both SMTP_USERNAME and SMTP_PASSWORD")
    mode = settings.get("tls", "ssl")
    if mode not in {"ssl", "starttls"}:
        raise ValueError("SMTP requires ssl or starttls")
    port = int(os.environ.get("SMTP_PORT", settings.get("port", 465 if mode == "ssl" else 587)))
    context = ssl.create_default_context()
    if mode == "ssl":
        client = smtp_ssl(host, port, timeout=30, context=context)
    else:
        client = smtp(host, port, timeout=30)
    with client:
        if mode == "starttls":
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
        if username:
            client.login(username, password)
        refused = client.send_message(message, from_addr=sender, to_addrs=[recipient])
        if refused:
            raise RuntimeError("SMTP did not accept the recipient")
