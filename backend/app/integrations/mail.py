"""Any email account over IMAP (read) and SMTP (send), signed in with an app password: Gmail, Outlook, Yahoo,
iCloud, Fastmail, Zoho, company mail... no OAuth app needed."""
from __future__ import annotations

import asyncio
import email
import imaplib
import re
import time
import smtplib
import ssl
from email.message import EmailMessage
from email.policy import default as email_policy
from email.utils import getaddresses
from typing import Any

from app.integrations.base import Field, IntegrationTool, Kind, strip_html

MAX_BODY = 20_000

# ponytail: the providers people use most; anything else defaults to imap./smtp.<domain> and can be edited.
PRESETS: dict[str, tuple[str, str, int]] = {
    "gmail.com": ("imap.gmail.com", "smtp.gmail.com", 465),
    "googlemail.com": ("imap.gmail.com", "smtp.gmail.com", 465),
    "outlook.com": ("outlook.office365.com", "smtp-mail.outlook.com", 587),
    "hotmail.com": ("outlook.office365.com", "smtp-mail.outlook.com", 587),
    "live.com": ("outlook.office365.com", "smtp-mail.outlook.com", 587),
    "yahoo.com": ("imap.mail.yahoo.com", "smtp.mail.yahoo.com", 465),
    "icloud.com": ("imap.mail.me.com", "smtp.mail.me.com", 587),
    "me.com": ("imap.mail.me.com", "smtp.mail.me.com", 587),
    "zoho.com": ("imap.zoho.com", "smtp.zoho.com", 465),
    "fastmail.com": ("imap.fastmail.com", "smtp.fastmail.com", 465),
}

FIELDS = [
    Field("address", "Email address", "email"),
    Field("password", "App password", "password",
          help="Gmail, Outlook, Yahoo and iCloud need an app password (made in your account's security settings) "
               "when 2-step verification is on; your normal password won't work there."),
    Field("imap_host", "IMAP server", required=False, advanced=True, help="Filled in for common providers"),
    Field("imap_port", "IMAP port", "number", required=False, default=993, advanced=True),
    Field("smtp_host", "SMTP server", required=False, advanced=True),
    Field("smtp_port", "SMTP port", "number", required=False, default=465, advanced=True,
          help="465 (SSL) or 587 (STARTTLS)"),
]


def prepare(config: dict[str, Any]) -> dict[str, Any]:
    """Fill in the servers for the address's provider unless they were given."""
    domain = str(config.get("address") or "").rpartition("@")[2].lower()
    imap, smtp, port = PRESETS.get(domain, (f"imap.{domain}", f"smtp.{domain}", 465))
    return {**config, "imap_host": config.get("imap_host") or imap, "smtp_host": config.get("smtp_host") or smtp,
            "imap_port": int(config.get("imap_port") or 993),
            "smtp_port": int(config.get("smtp_port") or (port if not config.get("smtp_host") else 465))}


def _imap(config: dict[str, Any]) -> imaplib.IMAP4_SSL:
    conn = imaplib.IMAP4_SSL(config["imap_host"], int(config["imap_port"]), timeout=30)
    try:
        conn.login(config["address"], config["password"])
    except imaplib.IMAP4.error as exc:
        raise ValueError(f"The email server refused the sign-in: {exc}") from exc
    return conn


def _decode(value: Any) -> str:
    return str(value or "").strip()


def _fetch(conn: imaplib.IMAP4_SSL, uids: list[str], what: str) -> list[tuple[str, bool, email.message.EmailMessage]]:
    status, data = conn.uid("FETCH", ",".join(uids), f"(UID FLAGS {what})")
    out = []
    for part in data:
        if not isinstance(part, tuple):
            continue
        meta = part[0].decode(errors="replace")
        uid = meta.split("UID ", 1)[1].split()[0] if "UID " in meta else meta.split()[0]
        unread = "\\Seen" not in meta
        out.append((uid, unread, email.message_from_bytes(part[1], policy=email_policy)))
    return out


def _search(config: dict[str, Any], query: str, unread_only: bool, folder: str, limit: int) -> dict[str, Any]:
    conn = _imap(config)
    try:
        conn.select(folder or "INBOX", readonly=True)
        criteria = ["UNSEEN" if unread_only else "ALL"]
        if query:
            criteria += ["TEXT", '"' + query.replace('"', "").encode("ascii", "ignore").decode() + '"']
        status, data = conn.uid("SEARCH", *criteria)
        uids = (data[0] or b"").decode().split()[-max(1, min(limit, 50)):]  # the newest ones
        emails = []
        for uid, unread, msg in reversed(_fetch(conn, uids, "BODY.PEEK[]")) if uids else []:
            body = msg.get_body(preferencelist=("plain", "html"))
            text = body.get_content() if body else ""
            emails.append({"id": uid, "from": _decode(msg["From"]), "subject": _decode(msg["Subject"]),
                           "date": _decode(msg["Date"]), "unread": unread,
                           "snippet": strip_html(text, 160) if body and body.get_content_subtype() == "html" else " ".join(text.split())[:160]})
        return {"emails": emails}
    finally:
        conn.logout()


def _read(config: dict[str, Any], uid: str, folder: str) -> dict[str, Any]:
    conn = _imap(config)
    try:
        conn.select(folder or "INBOX", readonly=True)
        found = _fetch(conn, [str(uid)], "BODY.PEEK[]")
        if not found:
            raise ValueError(f"No email with id {uid} in {folder or 'INBOX'}")
        _, unread, msg = found[0]
        body = msg.get_body(preferencelist=("plain", "html"))
        text = body.get_content() if body else ""
        if body is not None and body.get_content_subtype() == "html":
            text = strip_html(text, MAX_BODY)
        attachments = [part.get_filename() for part in msg.iter_attachments() if part.get_filename()]
        return {"id": str(uid), "from": _decode(msg["From"]), "to": _decode(msg["To"]), "cc": _decode(msg["Cc"]),
                "subject": _decode(msg["Subject"]), "date": _decode(msg["Date"]), "unread": unread,
                "body": text[:MAX_BODY], "attachments": attachments}
    finally:
        conn.logout()


def _send(config: dict[str, Any], to: str, subject: str, body: str, cc: str, files: str = "") -> str:
    recipients = [addr for _, addr in getaddresses([to, cc]) if addr]
    if not recipients:
        raise ValueError("Say who to send it to")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = config["address"], to, subject
    if cc:
        msg["Cc"] = cc
    msg.set_content(body)
    if files:
        from app.files import attach_to

        attach_to(msg, files)
    port = int(config["smtp_port"])
    context = ssl.create_default_context()
    if port == 465:
        server = smtplib.SMTP_SSL(config["smtp_host"], port, timeout=30, context=context)
    else:
        server = smtplib.SMTP(config["smtp_host"], port, timeout=30)
    with server:
        if port != 465:
            server.starttls(context=context)
        server.login(config["address"], config["password"])
        server.send_message(msg)
    return f"Sent \"{subject}\" to {', '.join(recipients)}."


def _drafts_folder(conn: imaplib.IMAP4_SSL) -> str:
    """The mailbox flagged as Drafts (RFC 6154), e.g. "[Gmail]/Drafts"; plain "Drafts" otherwise."""
    status, folders = conn.list()
    for line in folders or []:
        text = line.decode(errors="replace") if isinstance(line, bytes) else str(line)
        if "\\Drafts" in text:
            names = re.findall(r'"([^"]+)"\s*$', text) or [text.rsplit(" ", 1)[-1]]
            return names[0]
    return "Drafts"


def _save_draft(config: dict[str, Any], to: str, subject: str, body: str, cc: str, files: str = "") -> str:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = config["address"], to, subject
    if cc:
        msg["Cc"] = cc
    msg.set_content(body)
    if files:
        from app.files import attach_to

        attach_to(msg, files)
    conn = _imap(config)
    try:
        folder = _drafts_folder(conn)
        conn.append(f'"{folder}"', "\\Draft", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
    finally:
        conn.logout()
    return f"Saved a draft \"{subject}\" to {to} in {folder} (not sent)."


async def check(config: dict[str, Any]) -> str:
    def probe() -> str:
        conn = _imap(config)
        try:
            conn.select("INBOX", readonly=True)
        finally:
            conn.logout()
        return f"Signed in as {config['address']}"
    return await asyncio.to_thread(probe)


def tools(slug: str, name: str, config: dict[str, Any]) -> list[IntegrationTool]:
    async def search(p: dict[str, Any]) -> Any:
        return await asyncio.to_thread(_search, config, str(p.get("query") or ""), bool(p.get("unread_only")),
                                       str(p.get("folder") or "INBOX"), int(p.get("limit") or 10))

    async def read(p: dict[str, Any]) -> Any:
        return await asyncio.to_thread(_read, config, str(p.get("id") or ""), str(p.get("folder") or "INBOX"))

    async def send(p: dict[str, Any]) -> Any:
        return await asyncio.to_thread(_send, config, str(p.get("to") or ""), str(p.get("subject") or ""),
                                       str(p.get("body") or ""), str(p.get("cc") or ""), str(p.get("attachments") or ""))

    async def draft(p: dict[str, Any]) -> Any:
        return await asyncio.to_thread(_save_draft, config, str(p.get("to") or ""), str(p.get("subject") or ""),
                                       str(p.get("body") or ""), str(p.get("cc") or ""), str(p.get("attachments") or ""))

    folder = {"type": "string", "description": "Mailbox folder (default INBOX)"}
    return [
        IntegrationTool(slug, name, "search_emails", f"Search the emails in {config['address']}, newest first: "
                        "by words in them, or only unread ones. Returns id, from, subject, date and a snippet.", {
                            "properties": {"query": {"type": "string", "description": "Words to look for (optional)"},
                                           "unread_only": {"type": "boolean"}, "folder": folder,
                                           "limit": {"type": "integer", "description": "How many (default 10, max 50)"}}},
                        search, title="Search emails"),
        IntegrationTool(slug, name, "read_email", "Read one email in full by its id (from search_emails).", {
            "properties": {"id": {"type": "string"}, "folder": folder}, "required": ["id"]}, read, title="Read email"),
        IntegrationTool(slug, name, "send_email", f"Send an email from {config['address']}.", {
            "properties": {"to": {"type": "string", "description": "Recipient address(es), comma separated"},
                           "subject": {"type": "string"}, "body": {"type": "string", "description": "Plain text"},
                           "cc": {"type": "string"}, "attachments": {"type": "string", "description": "File ids from files__create_file, comma separated"}},
            "required": ["to", "subject", "body"]}, send, read_only=False, title="Send email"),
        IntegrationTool(slug, name, "save_draft", "Write an email into the Drafts folder for the user to review and send "
                        "themselves (nothing is sent).", {
                            "properties": {"to": {"type": "string"}, "subject": {"type": "string"},
                                           "body": {"type": "string", "description": "Plain text"}, "cc": {"type": "string"},
                                           "attachments": {"type": "string", "description": "File ids from files__create_file, comma separated"}},
                            "required": ["to", "subject", "body"]}, draft, read_only=False, policy="allow", title="Draft email"),
    ]


KIND = Kind("email", "Email (IMAP/SMTP)", "Read, search and send email from any provider with an app password.",
            "Mail", FIELDS, check, tools, prepare)
