"""Google (Gmail, Calendar, Drive) through the user's own OAuth client.

Self-hosted Nexus can't share one Google app across installs, so each user creates a client in Google Cloud
(the Marketplace shows the steps and the redirect address). Nexus signs in with it, keeps the refresh token
encrypted, and refreshes the access token whenever it runs out.
"""
from __future__ import annotations

import asyncio
import base64
import io
import secrets
import time
from datetime import datetime, time as clock, timedelta
from email.message import EmailMessage
from typing import Any, Optional
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx

from app.integrations import store
from app.integrations.base import Field, IntegrationTool, Kind, strip_html

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CALENDAR = "https://www.googleapis.com/calendar/v3/calendars"
DRIVE = "https://www.googleapis.com/drive/v3/files"
SCOPES = ["openid", "email", "https://www.googleapis.com/auth/gmail.modify",
          "https://www.googleapis.com/auth/calendar.events", "https://www.googleapis.com/auth/drive.readonly"]
CALLBACK_PATH = "api/integrations/google/callback"
MAX_TEXT = 20_000
TRANSPORT: Optional[httpx.AsyncBaseTransport] = None  # tests put a fake Google here
TOKEN_KEYS = {"access_token", "refresh_token", "expires_at"}  # stored, never shown

FIELDS = [
    Field("client_id", "OAuth client ID", help="Ends in .apps.googleusercontent.com"),
    Field("client_secret", "OAuth client secret", "password"),
]

# Sign-ins waiting for Google to send the user back: state -> (integration id, redirect address).
_pending: dict[str, tuple[int, str]] = {}


def user_timezone() -> str:
    from app.api.routes.settings import user_timezone as saved  # imported late: the routes import this package

    return saved() or "UTC"


# ---- tokens ---------------------------------------------------------------------------------------

def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=30, transport=TRANSPORT)


async def _token(form: dict[str, str]) -> dict[str, Any]:
    async with _client() as client:
        response = await client.post(TOKEN_URL, data=form)
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    if response.status_code >= 400:
        if body.get("error") == "invalid_grant":
            raise ValueError("Google sign-in has expired or was revoked (clients in Testing mode expire after 7 days). "
                             "Sign in again from the Marketplace.")
        raise ValueError(f"Google refused the sign-in: {body.get('error_description') or body.get('error') or response.status_code}")
    return body


def auth_url(integration_id: int, config: dict[str, Any], redirect_uri: str) -> str:
    state = secrets.token_urlsafe(24)
    _pending[state] = (integration_id, redirect_uri)
    return AUTH_URL + "?" + urlencode({
        "client_id": config["client_id"], "redirect_uri": redirect_uri, "response_type": "code",
        "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent",  # always hand out a refresh token
        "include_granted_scopes": "true", "state": state,
    })


async def finish_sign_in(state: str, code: str) -> Optional[dict[str, Any]]:
    """Trade Google's code for tokens; None for an unknown or used sign-in link."""
    pending = _pending.pop(state, None)
    integration = store.get_integration(pending[0], all_owners=True) if pending else None  # checked by state
    if integration is None:
        return None
    config = dict(integration["config"])
    tokens = await _token({"grant_type": "authorization_code", "code": code, "redirect_uri": pending[1],
                           "client_id": config["client_id"], "client_secret": config["client_secret"]})
    config.update(access_token=tokens["access_token"], refresh_token=tokens.get("refresh_token") or config.get("refresh_token"),
                  expires_at=time.time() + int(tokens.get("expires_in") or 3600) - 60)
    config["account"] = (await call(config, "GET", f"{GMAIL}/profile")).get("emailAddress", "")
    return store.update_integration(integration["id"], config=config)


async def _access_token(config: dict[str, Any], force: bool = False) -> str:
    if not force and config.get("access_token") and float(config.get("expires_at") or 0) > time.time():
        return config["access_token"]
    if not config.get("refresh_token"):
        raise ValueError("Not signed in to Google yet: finish signing in from the Marketplace")
    tokens = await _token({"grant_type": "refresh_token", "refresh_token": config["refresh_token"],
                           "client_id": config["client_id"], "client_secret": config["client_secret"]})
    config.update(access_token=tokens["access_token"], expires_at=time.time() + int(tokens.get("expires_in") or 3600) - 60)
    integration_id = config.get("_integration_id")
    saved = store.get_integration(integration_id, all_owners=True) if integration_id else None
    if saved:  # keep the new token for the next call and the next start
        store.update_integration(integration_id, config={**saved["config"], "access_token": config["access_token"],
                                                         "expires_at": config["expires_at"]})
    return config["access_token"]


async def call(config: dict[str, Any], method: str, url: str, *, params: Any = None, body: Any = None,
               mode: str = "json") -> Any:
    """A Google API call as the signed-in user (refreshing the token once if Google says it's stale)."""
    for attempt in range(2):
        token = await _access_token(config, force=attempt > 0)
        async with _client() as client:
            response = await client.request(method, url, params=params, json=body, headers={"Authorization": f"Bearer {token}"})
        if response.status_code == 401 and attempt == 0:
            continue
        if response.status_code >= 400:
            try:
                message = response.json().get("error", {}).get("message")
            except ValueError:
                message = None
            raise ValueError(f"Google said: {message or response.status_code}")
        return response.json() if mode == "json" else response.text if mode == "text" else response.content
    raise ValueError("Google keeps refusing the sign-in: sign in again from the Marketplace")


# ---- helpers ---------------------------------------------------------------------------------------

def _when(value: str, zone: ZoneInfo, fallback: datetime) -> datetime:
    if not value:
        return fallback
    parsed = datetime.fromisoformat(value.strip())
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=zone)


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _body(payload: dict[str, Any]) -> tuple[str, list[str]]:
    """(text, attachment names) of a Gmail message: plain text preferred, HTML made readable otherwise."""
    plain, html, attachments = [], [], []

    def walk(part: dict[str, Any]) -> None:
        if part.get("filename"):
            attachments.append(part["filename"])
        elif part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            plain.append(_decode(part["body"]["data"]))
        elif part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
            html.append(_decode(part["body"]["data"]))
        for child in part.get("parts") or []:
            walk(child)

    walk(payload)
    text = "\n".join(plain) if plain else strip_html("\n".join(html), MAX_TEXT)
    return text[:MAX_TEXT], attachments


def _headers(message: dict[str, Any]) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in message.get("payload", {}).get("headers", [])}


# ---- tools -----------------------------------------------------------------------------------------

def tools(slug: str, name: str, config: dict[str, Any]) -> list[IntegrationTool]:
    if not config.get("refresh_token"):
        return []  # not signed in yet: nothing to offer
    account = config.get("account") or "your Google account"

    async def gmail_search(p: dict[str, Any]) -> Any:
        listed = await call(config, "GET", f"{GMAIL}/messages",
                            params={"q": str(p.get("query") or ""), "maxResults": max(1, min(int(p.get("limit") or 10), 50))})
        ids = [m["id"] for m in listed.get("messages") or []]
        meta = [("format", "metadata"), ("metadataHeaders", "From"), ("metadataHeaders", "Subject"), ("metadataHeaders", "Date")]
        messages = await asyncio.gather(*(call(config, "GET", f"{GMAIL}/messages/{mid}", params=meta) for mid in ids))
        return {"emails": [{"id": m["id"], "thread_id": m.get("threadId"), "from": _headers(m).get("from", ""),
                            "subject": _headers(m).get("subject", ""), "date": _headers(m).get("date", ""),
                            "snippet": m.get("snippet", ""), "unread": "UNREAD" in (m.get("labelIds") or [])}
                           for m in messages]}

    async def gmail_read(p: dict[str, Any]) -> Any:
        message = await call(config, "GET", f"{GMAIL}/messages/{p.get('id')}", params={"format": "full"})
        headers = _headers(message)
        text, attachments = _body(message.get("payload") or {})
        return {"id": message["id"], "thread_id": message.get("threadId"), "from": headers.get("from", ""),
                "to": headers.get("to", ""), "cc": headers.get("cc", ""), "subject": headers.get("subject", ""),
                "date": headers.get("date", ""), "body": text, "attachments": attachments}

    async def compose(p: dict[str, Any]) -> tuple[EmailMessage, dict[str, Any]]:
        """The email to send or draft, threaded under ``reply_to_id`` when given."""
        msg = EmailMessage()
        msg["To"], msg["Subject"] = str(p.get("to") or ""), str(p.get("subject") or "")
        if config.get("account"):
            msg["From"] = config["account"]
        if p.get("cc"):
            msg["Cc"] = str(p["cc"])
        payload: dict[str, Any] = {}
        if p.get("reply_to_id"):  # stay in the same thread
            original = await call(config, "GET", f"{GMAIL}/messages/{p['reply_to_id']}",
                                  params=[("format", "metadata"), ("metadataHeaders", "Message-ID")])
            message_id = _headers(original).get("message-id")
            if message_id:
                msg["In-Reply-To"] = msg["References"] = message_id
            payload["threadId"] = original.get("threadId")
        msg.set_content(str(p.get("body") or ""))
        if p.get("attachments"):
            from app.files import attach_to

            attach_to(msg, str(p["attachments"]))
        payload["raw"] = base64.urlsafe_b64encode(msg.as_bytes()).decode().rstrip("=")
        return msg, payload

    async def gmail_send(p: dict[str, Any]) -> Any:
        msg, payload = await compose(p)
        sent = await call(config, "POST", f"{GMAIL}/messages/send", body=payload)
        return f"Sent \"{msg['Subject']}\" to {msg['To']} (message {sent.get('id')})."

    async def gmail_draft(p: dict[str, Any]) -> Any:
        msg, payload = await compose(p)
        draft = await call(config, "POST", f"{GMAIL}/drafts", body={"message": payload})
        return f"Saved a draft \"{msg['Subject']}\" to {msg['To']} in Gmail Drafts (not sent; draft {draft.get('id')})."

    async def calendar_list_events(p: dict[str, Any]) -> Any:
        zone = ZoneInfo(user_timezone())
        today = datetime.combine(datetime.now(zone).date(), clock.min, tzinfo=zone)
        start = _when(str(p.get("start") or ""), zone, today)
        end = _when(str(p.get("end") or ""), zone, start + timedelta(days=7))
        listed = await call(config, "GET", f"{CALENDAR}/{p.get('calendar_id') or 'primary'}/events", params={
            "timeMin": start.isoformat(), "timeMax": end.isoformat(), "singleEvents": "true", "orderBy": "startTime",
            "maxResults": 100, **({"q": str(p["query"])} if p.get("query") else {})})
        return {"timezone": str(zone), "events": [{
            "id": e["id"], "title": e.get("summary") or "(no title)",
            "start": e.get("start", {}).get("dateTime") or e.get("start", {}).get("date"),
            "end": e.get("end", {}).get("dateTime") or e.get("end", {}).get("date"),
            "all_day": "date" in e.get("start", {}), "location": e.get("location", ""),
            "description": strip_html(e.get("description") or "", 300), "link": e.get("htmlLink", "")}
            for e in listed.get("items") or []]}

    async def calendar_create_event(p: dict[str, Any]) -> Any:
        zone = user_timezone()
        start, end = str(p.get("start") or ""), str(p.get("end") or "")
        if len(start) == 10:  # a date: an all-day event
            last = end or (datetime.fromisoformat(start) + timedelta(days=1)).date().isoformat()
            when = {"start": {"date": start}, "end": {"date": last}}
        else:
            begins = datetime.fromisoformat(start)
            ends = datetime.fromisoformat(end) if end else begins + timedelta(hours=1)
            when = {"start": {"dateTime": begins.isoformat(), "timeZone": zone}, "end": {"dateTime": ends.isoformat(), "timeZone": zone}}
        attendees = [{"email": a.strip()} for a in str(p.get("attendees") or "").split(",") if a.strip()]
        event = {"summary": str(p.get("title") or ""), "description": str(p.get("description") or ""),
                 "location": str(p.get("location") or ""), **when, **({"attendees": attendees} if attendees else {})}
        created = await call(config, "POST", f"{CALENDAR}/{p.get('calendar_id') or 'primary'}/events", body=event)
        return {"id": created.get("id"), "link": created.get("htmlLink"), "title": event["summary"]}

    async def drive_search(p: dict[str, Any]) -> Any:
        words = str(p.get("query") or "").replace("\\", "\\\\").replace("'", "\\'")
        query = (f"(name contains '{words}' or fullText contains '{words}') and trashed = false" if words else "trashed = false")
        params = {"q": query, "pageSize": max(1, min(int(p.get("limit") or 10), 50)),
                  "fields": "files(id,name,mimeType,modifiedTime,webViewLink)"}
        if not words:  # with words, Drive orders by relevance
            params["orderBy"] = "modifiedTime desc"
        listed = await call(config, "GET", DRIVE, params=params)
        return {"files": [{"id": f["id"], "name": f["name"], "type": f.get("mimeType"), "modified": f.get("modifiedTime"),
                           "link": f.get("webViewLink")} for f in listed.get("files") or []]}

    async def drive_read(p: dict[str, Any]) -> Any:
        file_id = str(p.get("id") or "")
        meta = await call(config, "GET", f"{DRIVE}/{file_id}", params={"fields": "id,name,mimeType"})
        mime = meta.get("mimeType", "")
        exports = {"application/vnd.google-apps.document": "text/plain", "application/vnd.google-apps.spreadsheet": "text/csv",
                   "application/vnd.google-apps.presentation": "text/plain"}
        if mime in exports:
            text = await call(config, "GET", f"{DRIVE}/{file_id}/export", params={"mimeType": exports[mime]}, mode="text")
        elif mime == "application/pdf":
            from pypdf import PdfReader

            data = await call(config, "GET", f"{DRIVE}/{file_id}", params={"alt": "media"}, mode="bytes")
            text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)
        elif mime.startswith("text/") or mime in ("application/json", "application/xml"):
            text = await call(config, "GET", f"{DRIVE}/{file_id}", params={"alt": "media"}, mode="text")
        else:
            raise ValueError(f"Nexus can't read {mime or 'this kind of file'} yet: Docs, Sheets, Slides, PDFs and text files work")
        return {"id": file_id, "name": meta.get("name"), "type": mime, "text": text[:MAX_TEXT],
                "truncated": len(text) > MAX_TEXT}

    when = {"type": "string", "description": "ISO date or date-time in the user's timezone, e.g. 2026-10-20T15:00"}
    return [
        IntegrationTool(slug, name, "gmail_search", f"Search Gmail ({account}) with Gmail search syntax, e.g. 'is:unread', "
                        "'from:alex newer_than:7d', 'subject:invoice'. Newest first: id, from, subject, date, snippet.", {
                            "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "description": "Default 10, max 50"}}},
                        gmail_search, title="Search Gmail"),
        IntegrationTool(slug, name, "gmail_read", "Read one Gmail message in full by its id.", {
            "properties": {"id": {"type": "string"}}, "required": ["id"]}, gmail_read, title="Read email"),
        IntegrationTool(slug, name, "gmail_send", f"Send an email from {account}; give reply_to_id to answer in a thread.", {
            "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string", "description": "Plain text"},
                           "cc": {"type": "string"}, "reply_to_id": {"type": "string", "description": "Id of the email being answered"},
                           "attachments": {"type": "string", "description": "File ids from files__create_file, comma separated"}},
            "required": ["to", "subject", "body"]}, gmail_send, read_only=False, title="Send email"),
        IntegrationTool(slug, name, "gmail_draft", "Write a reply or new email into Gmail Drafts for the user to review "
                        "and send themselves (nothing is sent). Give reply_to_id to reply in a thread.", {
                            "properties": {"to": {"type": "string"}, "subject": {"type": "string"},
                                           "body": {"type": "string", "description": "Plain text"}, "cc": {"type": "string"},
                                           "reply_to_id": {"type": "string", "description": "Id of the email being answered"},
                                           "attachments": {"type": "string", "description": "File ids from files__create_file, comma separated"}},
                            "required": ["to", "subject", "body"]}, gmail_draft, read_only=False, policy="allow",
                        title="Draft email"),
        IntegrationTool(slug, name, "calendar_list_events", "List Google Calendar events between two dates "
                        "(default: the next 7 days), repeating events included, optionally matching some words.", {
                            "properties": {"start": when, "end": when, "query": {"type": "string"},
                                           "calendar_id": {"type": "string", "description": "Default: the main calendar"}}},
                        calendar_list_events, title="List events"),
        IntegrationTool(slug, name, "calendar_create_event", "Add an event to Google Calendar. A date alone makes an "
                        "all-day event; without an end it lasts an hour.", {
                            "properties": {"title": {"type": "string"}, "start": when, "end": when,
                                           "description": {"type": "string"}, "location": {"type": "string"},
                                           "attendees": {"type": "string", "description": "Email addresses, comma separated"}},
                            "required": ["title", "start"]}, calendar_create_event, read_only=False, title="Create event"),
        IntegrationTool(slug, name, "drive_search", "Find Google Drive files by name or the words in them; newest first "
                        "without words.", {"properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}},
                        drive_search, title="Search Drive"),
        IntegrationTool(slug, name, "drive_read", "Read a Google Drive file's text by its id: Docs, Sheets (as CSV), "
                        "Slides, PDFs and text files.", {"properties": {"id": {"type": "string"}}, "required": ["id"]},
                        drive_read, title="Read file"),
    ]


async def check(config: dict[str, Any]) -> str:
    profile = await call(config, "GET", f"{GMAIL}/profile")
    return f"Signed in as {profile.get('emailAddress')}"


KIND = Kind("google", "Google (Gmail, Calendar, Drive)",
            "Search, read and send Gmail, see and add Calendar events, and read Drive files. Uses your own Google client.",
            "Google", FIELDS, check, tools)
