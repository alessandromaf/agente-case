import imaplib
import email
import email.message
from email.header import decode_header


KNOWN_SENDERS = [
    "immobiliare.it",
    "idealista.it",
    "casa.it",
]


def _decode_payload(msg: email.message.Message) -> str:
    """Extract HTML or plain text body from an email message."""
    if msg.is_multipart():
        html_part = ""
        text_part = ""
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/html":
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                html_part = payload.decode(charset, errors="replace")
            elif ct == "text/plain" and not text_part:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                text_part = payload.decode(charset, errors="replace")
        return html_part or text_part
    else:
        payload = msg.get_payload(decode=True)
        charset = msg.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace") if payload else ""


def _decode_subject(msg: email.message.Message) -> str:
    raw = msg.get("Subject", "")
    parts = decode_header(raw)
    decoded = []
    for data, charset in parts:
        if isinstance(data, bytes):
            decoded.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(data)
    return " ".join(decoded)


def _is_alert_email(from_addr: str) -> bool:
    from_lower = from_addr.lower()
    return any(sender in from_lower for sender in KNOWN_SENDERS)


def fetch_new_alerts(gmail_email: str, app_password: str) -> list[dict]:
    """Connect to Gmail via IMAP, fetch unread alert emails, mark as read.

    Returns list of dicts: {source, subject, html, from_addr}
    """
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(gmail_email, app_password)
    mail.select("INBOX")

    # Search for unread emails from known real estate senders
    alerts = []
    for sender in KNOWN_SENDERS:
        _, msg_ids = mail.search(None, f'(UNSEEN FROM "{sender}")')
        ids = msg_ids[0].split()
        for mid in ids:
            _, msg_data = mail.fetch(mid, "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            from_addr = msg.get("From", "")
            subject = _decode_subject(msg)
            body = _decode_payload(msg)

            source = "unknown"
            for s in KNOWN_SENDERS:
                if s in from_addr.lower():
                    source = s.replace(".it", "")
                    break

            alerts.append({
                "source": source,
                "subject": subject,
                "html": body,
                "from_addr": from_addr,
            })

            # Mark as read
            mail.store(mid, "+FLAGS", "\\Seen")

    mail.logout()
    print(f"Fetched {len(alerts)} new alert emails")
    return alerts
