"""
Email tool pack: read the inbox and draft/send mail — the GREEN/RED demo.

Reading (list recent, read one body) is `autonomous`: it only measures the inbox.
Sending is `ask_first`: the agent may PREPARE the message freely, but the loop's
human gate must approve before smtplib actually delivers it.

Stdlib only: imaplib + smtplib + email. Config comes from env ONLY — never code:
  EMAIL_IMAP_HOST, EMAIL_SMTP_HOST, EMAIL_ADDRESS, EMAIL_PASSWORD  (+ optional EMAIL_SMTP_PORT)
If any required value is missing every tool returns a friendly "set EMAIL_* in .env"
string — it never crashes and never echoes the credential values.

Register it by importing EMAIL_TOOLS (the integrator wires it into the CLI).
"""
from __future__ import annotations

import email
import imaplib
import os
import smtplib
from email.header import decode_header, make_header
from email.message import EmailMessage

from .loop import Tool

_REQUIRED = ("EMAIL_IMAP_HOST", "EMAIL_SMTP_HOST", "EMAIL_ADDRESS", "EMAIL_PASSWORD")


def _cfg() -> dict | None:
    """Read creds from env. Return None (caller -> friendly error) if any are missing."""
    cfg = {k: (os.environ.get(k) or "").strip() for k in _REQUIRED}
    if not all(cfg.values()):
        return None
    cfg["EMAIL_SMTP_PORT"] = (os.environ.get("EMAIL_SMTP_PORT") or "465").strip()
    return cfg


_MISSING = ("ERROR: email not configured — set EMAIL_IMAP_HOST, EMAIL_SMTP_HOST, "
            "EMAIL_ADDRESS and EMAIL_PASSWORD (and optionally EMAIL_SMTP_PORT) in your .env")


def _decode(raw) -> str:
    """Decode an RFC-2047 header (bytes or str) to a plain string; defensive."""
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return str(raw)


def _plain_body(msg: email.message.Message) -> str:
    """Pull the text/plain part out of a parsed message."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(
                    part.get("Content-Disposition") or "").lower():
                payload = part.get_payload(decode=True)
                if payload is not None:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, "replace")
        return ""
    payload = msg.get_payload(decode=True)
    if payload is None:
        return ""
    return payload.decode(msg.get_content_charset() or "utf-8", "replace")


def _email_list_recent(args: dict) -> str:
    cfg = _cfg()
    if not cfg:
        return _MISSING
    try:
        n = int(args.get("count") or 10)
    except (TypeError, ValueError):
        n = 10
    n = max(1, min(n, 50))
    try:
        conn = imaplib.IMAP4_SSL(cfg["EMAIL_IMAP_HOST"])
        try:
            conn.login(cfg["EMAIL_ADDRESS"], cfg["EMAIL_PASSWORD"])
            conn.select("INBOX")
            typ, data = conn.search(None, "ALL")
            if typ != "OK" or not data or not data[0]:
                return "INBOX is empty."
            ids = data[0].split()
            recent = ids[-n:][::-1]  # newest first
            lines = []
            for mid in recent:
                typ, mdata = conn.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM)])")
                if typ != "OK" or not mdata or not mdata[0]:
                    continue
                hdr = mdata[0][1]
                if isinstance(hdr, bytes):
                    hdr = hdr.decode("utf-8", "replace")
                parsed = email.message_from_string(hdr)
                mid_s = mid.decode() if isinstance(mid, bytes) else str(mid)
                lines.append(f"[{mid_s}] From: {_decode(parsed.get('From'))} | "
                             f"Subject: {_decode(parsed.get('Subject'))}")
            return "\n".join(lines) if lines else "No messages parsed."
        finally:
            try:
                conn.logout()
            except Exception:
                pass
    except Exception as e:
        return f"ERROR reading inbox: {e}"


def _email_read(args: dict) -> str:
    cfg = _cfg()
    if not cfg:
        return _MISSING
    mid = str(args.get("id") or "").strip()
    if not mid:
        return "ERROR: need a message id (from email_list_recent)"
    try:
        conn = imaplib.IMAP4_SSL(cfg["EMAIL_IMAP_HOST"])
        try:
            conn.login(cfg["EMAIL_ADDRESS"], cfg["EMAIL_PASSWORD"])
            conn.select("INBOX")
            typ, mdata = conn.fetch(mid.encode(), "(RFC822)")
            if typ != "OK" or not mdata or not mdata[0]:
                return f"ERROR: message {mid} not found"
            raw = mdata[0][1]
            if isinstance(raw, str):
                raw = raw.encode("utf-8", "replace")
            msg = email.message_from_bytes(raw)
            body = _plain_body(msg)[:8000]
            return (f"From: {_decode(msg.get('From'))}\n"
                    f"To: {_decode(msg.get('To'))}\n"
                    f"Subject: {_decode(msg.get('Subject'))}\n"
                    f"Date: {_decode(msg.get('Date'))}\n\n"
                    f"{body or '(no plain-text body)'}")
        finally:
            try:
                conn.logout()
            except Exception:
                pass
    except Exception as e:
        return f"ERROR reading message: {e}"


def _email_send(args: dict) -> str:
    cfg = _cfg()
    if not cfg:
        return _MISSING
    to = str(args.get("to") or "").strip()
    subject = str(args.get("subject") or "").strip()
    body = str(args.get("body") or "")
    if not to:
        return "ERROR: need a 'to' recipient"
    if "@" not in to:
        return "ERROR: 'to' does not look like an email address"
    msg = EmailMessage()
    msg["From"] = cfg["EMAIL_ADDRESS"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        port = int(cfg["EMAIL_SMTP_PORT"])
    except (TypeError, ValueError):
        port = 465
    try:
        server = smtplib.SMTP_SSL(cfg["EMAIL_SMTP_HOST"], port)
        try:
            server.login(cfg["EMAIL_ADDRESS"], cfg["EMAIL_PASSWORD"])
            server.sendmail(cfg["EMAIL_ADDRESS"], [to], msg.as_string())
        finally:
            try:
                server.quit()
            except Exception:
                pass
        return f"SENT: to={to} subject={subject!r} ({len(body)} chars)"
    except Exception as e:
        return f"ERROR sending mail: {e}"


EMAIL_TOOLS = [
    Tool("email_list_recent",
         "List the most recent INBOX messages (subject + sender) with an id you can pass to "
         "email_read. Read-only.",
         {"type": "object",
          "properties": {"count": {"type": "integer",
                                   "description": "how many recent messages (1-50, default 10)"}}},
         _email_list_recent, "autonomous"),
    Tool("email_read",
         "Read one INBOX message's plain-text body by its id (from email_list_recent). Read-only.",
         {"type": "object",
          "properties": {"id": {"type": "string", "description": "message id from email_list_recent"}},
          "required": ["id"]},
         _email_read, "autonomous"),
    Tool("email_send",
         "Send an email (to, subject, body). PREPARE freely, but delivery needs operator approval.",
         {"type": "object",
          "properties": {"to": {"type": "string", "description": "recipient address"},
                         "subject": {"type": "string"},
                         "body": {"type": "string"}},
          "required": ["to", "subject", "body"]},
         _email_send, "ask_first"),
]
