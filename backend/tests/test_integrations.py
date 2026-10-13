"""Built-in integrations that need no app sign-up: email (IMAP/SMTP), calendar feeds (ICS) and RSS/Atom feeds."""
from __future__ import annotations

import asyncio
import email
from email.message import EmailMessage

import pytest
from fastapi.testclient import TestClient

from app.integrations import base, calendar_feed, mail, rss
from app.main import app
from app.mcp import server_states
from app.tools import get_tool_registry

# ---- fakes --------------------------------------------------------------------------------------

def _message(uid: int, sender: str, subject: str, body: str) -> bytes:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, "me@example.com", subject
    msg["Date"] = "Mon, 12 Oct 2026 09:00:00 +0000"
    msg.set_content(body)
    return msg.as_bytes()


MAILBOX = {1: (_message(1, "Asha <asha@example.com>", "Invoice 42", "Please pay invoice 42 by Friday."), True),
           2: (_message(2, "Ravi <ravi@example.com>", "Lunch?", "Lunch at 1 tomorrow?"), False)}
SENT: list[EmailMessage] = []
APPENDED: list = []


class FakeIMAP:
    def __init__(self, host, port, timeout=None):
        self.host = host

    def login(self, user, password):
        if password != "app-password":
            raise mail.imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")
        return "OK", [b"Logged in"]

    def select(self, folder="INBOX", readonly=False):
        return "OK", [str(len(MAILBOX)).encode()]

    def uid(self, command, *args):
        if command == "SEARCH":
            words = " ".join(a.decode() if isinstance(a, bytes) else a for a in args)
            hits = [uid for uid, (raw, seen) in MAILBOX.items()
                    if ("UNSEEN" not in words or not seen)
                    and ("TEXT" not in words or words.split("TEXT ", 1)[1].strip('"').lower() in raw.decode().lower())]
            return "OK", [" ".join(map(str, hits)).encode()]
        if command == "FETCH":
            uids = args[0].decode() if isinstance(args[0], bytes) else args[0]
            out = []
            for uid in uids.split(","):
                raw, seen = MAILBOX[int(uid)]
                flags = "\\Seen" if seen else ""
                out += [(f"{uid} (UID {uid} FLAGS ({flags}) BODY[] {{{len(raw)}}}".encode(), raw), b")"]
            return "OK", out
        raise AssertionError(command)

    def list(self, directory='""', pattern="*"):
        return "OK", [b'(\HasNoChildren) "/" "INBOX"', b'(\HasNoChildren \Drafts) "/" "[Gmail]/Drafts"']

    def append(self, mailbox, flags, date_time, message):
        APPENDED.append((mailbox, flags, message))
        return "OK", [b"APPEND completed"]

    def logout(self):
        return "BYE", []


class FakeSMTP:
    def __init__(self, host, port, timeout=None, context=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        pass

    def send_message(self, msg):
        SENT.append(msg)


ICS = """BEGIN:VCALENDAR
VERSION:2.0
X-WR-CALNAME:Work
BEGIN:VEVENT
UID:standup@x
SUMMARY:Standup
DTSTART:20261012T093000Z
DTEND:20261012T094500Z
RRULE:FREQ=DAILY;COUNT=5
END:VEVENT
BEGIN:VEVENT
UID:review@x
SUMMARY:Quarterly review
LOCATION:Room 4
DTSTART;VALUE=DATE:20261014
DTEND;VALUE=DATE:20261015
END:VEVENT
END:VCALENDAR
"""

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Nexus blog</title>
<item><title>Release 0.3</title><link>https://ex.com/0.3</link><guid>r03</guid><pubDate>Mon, 12 Oct 2026 08:00:00 GMT</pubDate>
<description>&lt;p&gt;Workflows on a &lt;b&gt;canvas&lt;/b&gt;&lt;/p&gt;</description></item>
<item><title>Release 0.2</title><link>https://ex.com/0.2</link><guid>r02</guid></item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Changelog</title>
<entry><title>Fix login</title><id>tag:ex,1</id><link href="https://ex.com/1"/><updated>2026-10-11T10:00:00Z</updated>
<summary>Sign-in works again</summary></entry></feed>"""


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    monkeypatch.setattr(mail.imaplib, "IMAP4_SSL", FakeIMAP)
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSMTP)
    feeds = {"https://cal.example/work.ics": ICS, "https://ex.com/feed": RSS, "https://ex.com/atom": ATOM}

    async def fetch(url):
        if url not in feeds:
            raise ValueError(f"Couldn't download {url}: 404")
        return feeds[url]

    monkeypatch.setattr(base, "fetch_text", fetch)
    SENT.clear()
    APPENDED.clear()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def run(tool_name, **parameters):
    return asyncio.run(get_tool_registry().get_tool(tool_name).execute(parameters))


# ---- email --------------------------------------------------------------------------------------

def test_mail_servers_are_guessed_from_the_address():
    assert mail.prepare({"address": "me@gmail.com"})["imap_host"] == "imap.gmail.com"
    assert mail.prepare({"address": "me@outlook.com"})["smtp_port"] == 587
    assert mail.prepare({"address": "me@corp.io", "imap_host": "mail.corp.io"})["imap_host"] == "mail.corp.io"


def test_email_connects_searches_reads_and_sends(client):
    bad = client.post("/api/integrations", json={"kind": "email", "name": "Work email",
                                                  "config": {"address": "me@example.com", "password": "wrong"}})
    assert bad.status_code == 422 and "AUTHENTICATIONFAILED" in bad.json()["detail"]

    created = client.post("/api/integrations", json={"kind": "email", "name": "Work email",
                                                      "config": {"address": "me@example.com", "password": "app-password"}})
    assert created.status_code == 200, created.text
    item = created.json()
    assert item["slug"] == "work_email" and item["status"] == "connected"
    assert "password" not in str(item)  # secrets never come back
    names = {t["name"]: t for t in item["tools"]}
    assert names["work_email__send_email"]["policy"] == "ask" and names["work_email__search_emails"]["policy"] == "allow"
    assert server_states()["work_email"]["available"] is True

    unread = run("work_email__search_emails", unread_only=True)["data"]["emails"]
    assert [e["subject"] for e in unread] == ["Lunch?"] and unread[0]["unread"] is True
    found = run("work_email__search_emails", query="invoice")["data"]["emails"]
    assert [e["id"] for e in found] == ["1"]
    letter = run("work_email__read_email", id="1")["data"]
    assert "pay invoice 42" in letter["body"] and letter["from"] == "Asha <asha@example.com>"

    run("work_email__send_email", to="ravi@example.com", subject="Re: Lunch?", body="Yes, 1 works.")
    assert SENT[0]["To"] == "ravi@example.com" and "1 works" in SENT[0].get_content()

    assert client.delete(f"/api/integrations/{item['id']}").status_code == 204
    assert "work_email" not in server_states()
    with pytest.raises(Exception):
        get_tool_registry().get_tool("work_email__search_emails")


# ---- calendar feeds ----------------------------------------------------------------------------

def test_calendar_feed_lists_events_with_repeats_expanded(client, monkeypatch):
    monkeypatch.setattr(calendar_feed, "user_timezone", lambda: "UTC")
    created = client.post("/api/integrations", json={"kind": "calendar", "name": "Work calendar",
                                                      "config": {"url": "webcal://cal.example/work.ics"}}).json()
    assert created["status"] == "connected" and "Work" in created["message"]
    events = run("work_calendar__list_events", start="2026-10-12", end="2026-10-15")["data"]["events"]
    titles = [e["title"] for e in events]
    assert titles.count("Standup") == 3 and "Quarterly review" in titles  # 12, 13, 14 Oct; the rest fall later
    review = next(e for e in events if e["title"] == "Quarterly review")
    assert review["all_day"] is True and review["location"] == "Room 4"
    assert len({e["id"] for e in events}) == len(events)  # each occurrence is its own item (for "new event" triggers)
    client.delete(f"/api/integrations/{created['id']}")


# ---- feeds ---------------------------------------------------------------------------------------

def test_rss_and_atom_feeds(client):
    created = client.post("/api/integrations", json={"kind": "rss", "name": "Nexus blog", "config": {"url": "https://ex.com/feed"}}).json()
    items = run("nexus_blog__latest_items")["data"]["items"]
    assert [i["title"] for i in items] == ["Release 0.3", "Release 0.2"]
    assert items[0]["id"] == "r03" and items[0]["summary"] == "Workflows on a canvas"
    client.delete(f"/api/integrations/{created['id']}")

    atom = client.post("/api/integrations", json={"kind": "rss", "name": "Changelog", "config": {"url": "https://ex.com/atom"}}).json()
    entry = run("changelog__latest_items")["data"]["items"][0]
    assert entry["link"] == "https://ex.com/1" and entry["summary"] == "Sign-in works again"
    client.delete(f"/api/integrations/{atom['id']}")

    broken = client.post("/api/integrations", json={"kind": "rss", "name": "Gone", "config": {"url": "https://ex.com/missing"}})
    assert broken.status_code == 422 and "404" in broken.json()["detail"]


def test_kinds_describe_their_forms(client):
    kinds = {k["id"]: k for k in client.get("/api/integrations/kinds").json()}
    assert {"email", "calendar", "rss"} <= set(kinds)
    password = next(f for f in kinds["email"]["fields"] if f["name"] == "password")
    assert password["type"] == "password" and password["required"] is True


def test_slugs_never_clash(client):
    a = client.post("/api/integrations", json={"kind": "rss", "name": "Feed", "config": {"url": "https://ex.com/feed"}}).json()
    b = client.post("/api/integrations", json={"kind": "rss", "name": "Feed", "config": {"url": "https://ex.com/feed"}}).json()
    assert a["slug"] == "feed" and b["slug"] == "feed_2"
    for item in (a, b):
        client.delete(f"/api/integrations/{item['id']}")


def test_mentioning_an_integration_points_the_agent_at_it(client, monkeypatch):
    import app.api.routes.agent as agent_route
    from app.llm.metering import Metered
    from tests.test_chatbot import ScriptedLLM

    llm = ScriptedLLM()
    monkeypatch.setattr(agent_route, "get_default_llm_provider", lambda: (Metered(llm, None, {"model": "m"}), {}))
    feed = client.post("/api/integrations", json={"kind": "rss", "name": "Team news", "config": {"url": "https://ex.com/feed"}}).json()
    sid = client.post("/api/agent/sessions", json={}).json()["session_id"]
    client.post("/api/agent/run", json={"message": "@Team news anything new?", "session_id": sid})
    call = next(c for c in llm.calls if c["kind"] == "tools")
    assert "team_news__latest_items" in call["tools"]
    assert "the app Team news" in call["messages"][0]["content"]
    client.delete(f"/api/integrations/{feed['id']}")


def test_email_drafts_go_to_the_drafts_folder(client):
    created = client.post("/api/integrations", json={"kind": "email", "name": "Drafty",
                                                      "config": {"address": "me@example.com", "password": "app-password"}}).json()
    assert get_tool_registry().get_tool("drafty__save_draft").policy == "allow"  # nothing is sent
    run("drafty__save_draft", to="ravi@example.com", subject="Re: Lunch?", body="Yes, 1 works.")
    mailbox, flags, raw = APPENDED[0]
    assert mailbox == '"[Gmail]/Drafts"' and "Draft" in flags
    assert b"1 works" in raw and b"ravi@example.com" in raw
    client.delete(f"/api/integrations/{created['id']}")
