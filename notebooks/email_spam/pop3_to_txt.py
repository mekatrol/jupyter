#!/usr/bin/env python3
"""
pop3_to_csv.py
Download emails from a POP3/POP3S server and write them to a CSV
with header: ,label,text,label_num

- Prefers text/plain; falls back to stripped text/html
- Optional: trust X-Spam-Flag / X-Spam-Status headers
"""

import os
import argparse
import getpass
import html
import poplib
import re
import ssl
import string
from typing import Optional, Tuple, List
from email import message_from_bytes
from email.message import Message
from pop3_config import *


def html_to_text(html_content: str) -> str:
    """Very lightweight HTML -> text conversion without external deps."""
    # Remove script/style contents
    html_content = re.sub(
        r"(?is)<(script|style).*?>.*?</\1>", "", html_content)
    # Replace <br> and <p> with newlines
    html_content = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", html_content)
    html_content = re.sub(r"(?i)<\s*/?\s*p\s*>", "\n", html_content)
    # Strip all remaining tags
    text = re.sub(r"(?s)<.*?>", "", html_content)
    # Unescape entities
    text = html.unescape(text)
    # Normalize whitespace
    text = re.sub(r"[ \t\r\f]+", " ", text)
    text = re.sub(r"\n\s*\n\s*", "\n", text)
    return text.strip()


def decode_best_effort(b: bytes, default: str = "utf-8") -> str:
    try:
        return b.decode(default, errors="replace")
    except Exception:
        return b.decode("latin-1", errors="replace")


def extract_body(msg: Message) -> str:
    """Prefer text/plain; fallback to text/html converted to text."""
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
        # Fallback: any text/* we can decode
        texts: List[str] = []
        for part in msg.walk():
            if part.get_content_maintype() == "text":
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                try:
                    texts.append(payload.decode(charset, errors="replace"))
                except Exception:
                    texts.append(decode_best_effort(payload))
        return " ".join(t.strip() for t in texts if t.strip())
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


def infer_label_from_headers(msg: Message, default_label: str = "ham", trust_spam_headers: bool = False) -> str:
    if not trust_spam_headers:
        return default_label
    x_spam_flag = (msg.get("X-Spam-Flag") or "").strip().lower()
    if x_spam_flag in {"yes", "true"}:
        return "spam"
    x_spam_status = (msg.get("X-Spam-Status") or "").lower()
    if x_spam_status.startswith("yes"):
        return "spam"
    return default_label


def label_to_num(label: str) -> int:
    # Kaggle-style: ham=0, spam=1
    return 1 if label.lower() == "spam" else 0


def fetch_messages(
    server: str,
    user: str,
    password: str,
    port: int = 995,
    use_ssl: bool = True,
    max_messages: Optional[int] = None,
) -> List[Message]:
    """Fetch up to max_messages and return parsed Message objects (newest first)."""
    conn = None
    try:
        if use_ssl:
            context = ssl.create_default_context()
            conn = poplib.POP3_SSL(server, port, context=context, timeout=60)
        else:
            conn = poplib.POP3(server, port, timeout=60)
        conn.user(user)
        conn.pass_(password)
        # Message list
        _resp, listings, _octets = conn.list()
        indices = [int(line.split()[0]) for line in listings]
        indices.sort(reverse=True)  # newest first
        if max_messages is not None:
            indices = indices[: max(0, int(max_messages))]
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


def write_email_file(rows: List[str], out_path: str) -> None:
    with open(out_path, "w", encoding="utf-8") as f:
        for text in rows:
            # Each email body on its own line
            f.write(text.strip().replace("\n", " ") + "\n")


def main():
    server = ''
    if pop3_config["smtp"] is not None:
        server = pop3_config["smtp"]

    user = ''
    if pop3_config["email_addr"] is not None:
        user = pop3_config["email_addr"]

    ap = argparse.ArgumentParser(
        description="Download emails via POP3/POP3S and export to Kaggle-style CSV.")
    ap.add_argument("--server",
                    help="POP3 server hostname (e.g., pop.gmail.com)")
    ap.add_argument("--port", type=int, default=995,
                    help="POP3 port (995 SSL, 110 plain)")
    ap.add_argument("--user", help="Username/email address")
    ap.add_argument("--ssl", dest="use_ssl",
                    action="store_true", help="Use SSL (default)")
    ap.add_argument("--no-ssl", dest="use_ssl",
                    action="store_false", help="Disable SSL")
    ap.add_argument("--max", type=int, default=None,
                    help="Max messages to fetch (default: all)")
    ap.add_argument("--out",
                    help="Output TXT path (e.g., emails.txt)")
    ap.add_argument("--default-label", choices=["ham", "spam"],
                    default="ham", help="Default label (if not trusting headers)")
    ap.add_argument("--trust-spam-headers", action="store_true",
                    help="Honor X-Spam-Flag / X-Spam-Status")

    ap.set_defaults(use_ssl=True)
    ap.set_defaults(server=server)
    ap.set_defaults(user=user)
    ap.set_defaults(out='emails.txt')

    args = ap.parse_args()

    password = ''
    if pop3_config["email_pwd"] is not None:
        password = pop3_config["email_pwd"]
    else:
        password = getpass.getpass(f"Password for {args.user}@{args.server}: ")

    msgs = fetch_messages(
        server=server,
        user=user,
        password=password,
        port=args.port,
        use_ssl=args.use_ssl,
        max_messages=args.max,
    )

    rows: List[str] = []
    for msg in msgs:
        email_body = extract_body(msg)
        email_body = email_body.replace("\r\n", " ")
        email_text=email_body.lower().translate(
            str.maketrans('', '', string.punctuation)).split()
        email_text=' '.join(email_text)
        rows.append(email_text)

    # Directory where this script lives
    script_dir=os.path.dirname(os.path.abspath(__file__))

    # Join with desired filename
    default_out=os.path.join(script_dir, args.out)

    write_email_file(rows, default_out)
    print(f"Wrote {len(rows)} messages to {default_out}")


if __name__ == "__main__":
    main()
