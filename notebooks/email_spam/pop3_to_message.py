#!/usr/bin/env python3
"""
pop3_parse_emails.py

Connects to a POP3/POP3S server, fetches messages, and parses them into a
structured list including: subject, body (plain text), sender display name,
sender email address, plus some optional metadata.

Usage (PowerShell/CMD):
  python pop3_parse_emails.py --server pop.gmail.com --user you@gmail.com --max 50
  python pop3_parse_emails.py --server mail.example.com --user you@example.com --no-ssl --port 110

Notes:
- Prompts for your password securely.
- Prefers text/plain; falls back to text/html (tags stripped).
- Handles RFC 2047-encoded headers (Subject, From, etc.).
"""

import os
import argparse
import getpass
import html
import poplib
import re
import ssl
import json
from typing import List, Dict, Any, Tuple
from email import message_from_bytes
from email.message import Message
from email.header import decode_header, make_header
from email.utils import parseaddr, getaddresses
from pop3_config import *

# ------------------ Helpers ------------------


def decode_header_str(value: str) -> str:
    """Decode RFC 2047/encoded-words header into a readable unicode string."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value  # best effort


def html_to_text(html_content: str) -> str:
    """Very lightweight HTML -> text conversion without external deps."""
    # Remove script/style contents
    html_content = re.sub(
        r"(?is)<(script|style).*?>.*?</\1>", "", html_content)
    # Replace common block elements with newlines
    html_content = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", html_content)
    html_content = re.sub(
        r"(?i)</\s*(p|div|h[1-6]|li|tr)\s*>", "\n", html_content)
    # Strip all remaining tags
    text = re.sub(r"(?s)<.*?>", "", html_content)
    # Unescape entities and normalize whitespace
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f]+", " ", text).strip()
    # Collapse repeated newlines
    text = re.sub(r"\n\s*\n\s*", "\n", text)
    return text


def decode_best_effort(b: bytes, preferred: str = "utf-8") -> str:
    try:
        return b.decode(preferred, errors="replace")
    except Exception:
        return b.decode("latin-1", errors="replace")


def extract_text_body(msg: Message) -> str:
    """
    Prefer text/plain (non-attachment). If missing, fallback to text/html -> text.
    If still nothing, try any text/*.
    """
    if msg.is_multipart():
        plain_parts: List[str] = []
        html_parts: List[str] = []
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            disp = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                continue
            if ctype == "text/plain":
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                try:
                    plain_parts.append(payload.decode(
                        charset, errors="replace"))
                except Exception:
                    plain_parts.append(decode_best_effort(payload))
            elif ctype == "text/html":
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                try:
                    html_parts.append(payload.decode(
                        charset, errors="replace"))
                except Exception:
                    html_parts.append(decode_best_effort(payload))
        if plain_parts:
            return "\n\n".join(p.strip() for p in plain_parts if p.strip())
        if html_parts:
            return "\n\n".join(html_to_text(h) for h in html_parts if h.strip())
        # fallback: any text/*
        texts: List[str] = []
        for part in msg.walk():
            if part.get_content_maintype() == "text":
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                try:
                    texts.append(payload.decode(charset, errors="replace"))
                except Exception:
                    texts.append(decode_best_effort(payload))
        return "\n\n".join(t.strip() for t in texts if t.strip())
    else:
        payload = msg.get_payload(decode=True) or b""
        ctype = (msg.get_content_type() or "").lower()
        charset = msg.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="replace")
        except Exception:
            text = decode_best_effort(payload)
        if ctype == "text/html":
            return html_to_text(text)
        return text


def parse_from_header(val: str) -> Tuple[str, str]:
    """
    Parse "From" into display name and email address.
    Handles encoded names.
    """
    if not val:
        return ("", "")
    name, addr = parseaddr(val)
    return (decode_header_str(name), addr or "")


def parse_addr_list(val: str) -> List[Tuple[str, str]]:
    """Parse address list headers (To/Cc) into [(name, email), ...]."""
    pairs = []
    for name, addr in getaddresses([val or ""]):
        pairs.append((decode_header_str(name), addr))
    return pairs


# ------------------ POP3 fetch ------------------

def fetch_messages(server: str, user: str, password: str,
                   port: int = 995, use_ssl: bool = True,
                   max_messages: int | None = None) -> List[Message]:
    """
    Connect to POP3(S), list messages, retrieve up to max_messages (newest first),
    return parsed email.message.Message objects.
    """
    conn = None
    try:
        if use_ssl:
            context = ssl.create_default_context()
            conn = poplib.POP3_SSL(server, port, context=context, timeout=60)
        else:
            conn = poplib.POP3(server, port, timeout=60)

        conn.user(user)
        conn.pass_(password)

        _resp, listings, _octets = conn.list()
        indices = [int(line.split()[0]) for line in listings]
        indices.sort(reverse=True)  # newest first
        if max_messages is not None:
            indices = indices[:max_messages]

        messages: List[Message] = []
        for i in indices:
            _resp, lines, _octets = conn.retr(i)
            raw = b"\r\n".join(lines)
            msg = message_from_bytes(raw)
            messages.append(msg)
        return messages

    finally:
        try:
            if conn is not None:
                conn.quit()
        except Exception:
            pass


def message_to_struct(msg: Message) -> Dict[str, Any]:
    """
    Convert a Message into a clean dict: subject, body, from_name, from_email,
    plus optional metadata (date, message_id, to, cc).
    """
    subject = decode_header_str(msg.get("Subject", ""))
    from_name, from_email = parse_from_header(msg.get("From", ""))
    body = extract_text_body(msg)

    to_list = parse_addr_list(msg.get("To", ""))
    cc_list = parse_addr_list(msg.get("Cc", ""))

    return {
        "subject": subject,
        "body": body,
        "from_name": from_name,
        "from_email": from_email,
        # Optional-but-useful fields:
        "date": decode_header_str(msg.get("Date", "")),
        "message_id": msg.get("Message-ID", ""),
        "to": [{"name": n, "email": a} for n, a in to_list],
        "cc": [{"name": n, "email": a} for n, a in cc_list],
    }


# ------------------ CLI ------------------

def main():
    server = ''
    if pop3_config["smtp"] is not None:
        server = pop3_config["smtp"]

    user = ''
    if pop3_config["email_addr"] is not None:
        user = pop3_config["email_addr"]

    ap = argparse.ArgumentParser(
        description="Fetch and parse emails from POP3/POP3S.")
    ap.add_argument("--server",
                    help="POP3 server (e.g., pop.gmail.com)")
    ap.add_argument("--user", help="Username/email address")
    ap.add_argument("--port", type=int, default=995,
                    help="Port (995 SSL, 110 plain)")
    ap.add_argument("--no-ssl", dest="use_ssl",
                    action="store_false", help="Disable SSL (default: SSL on)")
    ap.add_argument("--out", help="Output JSON path (e.g., emails.json)")
    ap.add_argument("--max", type=int, default=10,
                    help="Max messages to fetch (newest first)")
    ap.set_defaults(use_ssl=True)
    ap.set_defaults(server=server)
    ap.set_defaults(user=user)
    ap.set_defaults(out='emails.json')

    args = ap.parse_args()

    password = ''
    if pop3_config["email_pwd"] is not None:
        password = pop3_config["email_pwd"]
    else:
        password = getpass.getpass(f"Password for {args.user}@{args.server}: ")

    msgs = fetch_messages(
        server=args.server,
        user=args.user,
        password=password,
        port=args.port,
        use_ssl=args.use_ssl,
        max_messages=args.max,
    )

    structs = [message_to_struct(m) for m in msgs]

    # Print a readable summary; replace with JSON dump if you prefer
    for i, s in enumerate(structs, start=1):
        preview = s["body"][:120].replace("\r", " ").replace("\n", " ")
        print(f"\n--- Message {i} ---")
        print(f"From: {s['from_name']} <{s['from_email']}>")
        print(f"Subject: {s['subject']}")
        print(f"Date: {s['date']}")
        print(f"Preview: {preview}{'...' if len(s['body']) > 120 else ''}")
        
        # Directory where this script lives
    script_dir=os.path.dirname(os.path.abspath(__file__))

    # Join with desired filename
    default_out=os.path.join(script_dir, args.out)

    with open(default_out, "w", encoding="utf-8") as f:
        json.dump(structs, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
