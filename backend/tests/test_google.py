"""Google (Gmail, Calendar, Drive) with the user's own OAuth client: sign-in, token refresh and the tools."""
from __future__ import annotations

import asyncio
import base64
import email
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from app.integrations import google, store
from app.main import app
from app.mcp import server_states
from app.tools import get_tool_registry

CALLS: list[httpx.Request] = []


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def fake_google(request: httpx.Request) -> httpx.Response:
    CALLS.append(request)
    url, path = str(request.url), request.url.path
    if url.startswith("https://oauth2.googleapis.com/token"):
        form = parse_qs(request.content.decode())
        if form["grant_type"] == ["authorization_code"]:
            assert form["code"] == ["the-code"] and form["redirect_uri"][0].endswith("/api/integrations/google/callback")
            return httpx.Response(200, json={"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 3600})
        assert form["grant_type"] == ["refresh_token"] and form["refresh_token"] == ["refresh-1"]
        return httpx.Response(200, json={"access_token": "access-2", "expires_in": 3600})
    if request.headers.get("authorization") not in ("Bearer access-1", "Bearer access-2"):
        return httpx.Response(401, json={"error": {"message": "Invalid Credentials"}})
    if path == "/gmail/v1/users/me/profile":
        return httpx.Response(200, json={"emailAddress": "me@gmail.com"})
    if path == "/gmail/v1/users/me/messages":
        assert request.url.params["q"] == "is:unread"
        return httpx.Response(200, json={"messages": [{"id": "m1"}, {"id": "m2"}]})
    if path.startswith("/gmail/v1/users/me/messages/m"):
        mid = path.rsplit("/", 1)[1]
        headers = [{"name": "From", "value": f"Sender {mid} <{mid}@x.com>"}, {"name": "Subject", "value": f"Subject {mid}"},
                   {"name": "Date", "value": "Mon, 12 Oct 2026 09:00:00 +0000"}]
        body = {"mimeType": "multipart/alternative", "parts": [
            {"mimeType": "text/plain", "body": {"data": b64(f"Hello from {mid}")}},
            {"mimeType": "text/html", "body": {"data": b64(f"<p>Hello from {mid}</p>")}}]}
        return httpx.Response(200, json={"id": mid, "threadId": "t1", "snippet": f"Hello from {mid}", "labelIds": ["UNREAD"],
                                         "payload": {"headers": headers, **body}})
    if path == "/gmail/v1/users/me/messages/send":
        return httpx.Response(200, json={"id": "sent-1"})
    if path == "/gmail/v1/users/me/drafts":
        return httpx.Response(200, json={"id": "draft-1", "message": {"id": "m9"}})
    if path == "/calendar/v3/calendars/primary/events" and request.method == "GET":
        assert request.url.params["singleEvents"] == "true"
        return httpx.Response(200, json={"items": [
            {"id": "e1", "summary": "Standup", "start": {"dateTime": "2026-10-12T09:30:00+05:30"},
             "end": {"dateTime": "2026-10-12T09:45:00+05:30"}, "htmlLink": "https://cal/e1"},
            {"id": "e2", "summary": "Holiday", "start": {"date": "2026-10-14"}, "end": {"date": "2026-10-15"}}]})
    if path == "/calendar/v3/calendars/primary/events" and request.method == "POST":
        return httpx.Response(200, json={"id": "new", "htmlLink": "https://cal/new", **json.loads(request.content)})
    if path == "/drive/v3/files" and "q" in request.url.params:
        assert "fullText contains 'budget'" in request.url.params["q"]
        return httpx.Response(200, json={"files": [{"id": "d1", "name": "Budget 2026", "mimeType": "application/vnd.google-apps.document",
                                                    "modifiedTime": "2026-10-01T00:00:00Z", "webViewLink": "https://docs/d1"}]})
    if path == "/drive/v3/files/d1":
        return httpx.Response(200, json={"id": "d1", "name": "Budget 2026", "mimeType": "application/vnd.google-apps.document"})
    if path == "/drive/v3/files/d1/export":
        assert request.url.params["mimeType"] == "text/plain"
        return httpx.Response(200, text="Budget: 120k for tools")
    return httpx.Response(404, json={"error": {"message": f"unexpected {request.method} {url}"}})


@pytest.fixture(autouse=True)
def mock_google(monkeypatch):
    monkeypatch.setattr(google, "TRANSPORT", httpx.MockTransport(fake_google))
    monkeypatch.setattr(google, "user_timezone", lambda: "Asia/Kolkata")
    CALLS.clear()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def run(name, **parameters):
    return asyncio.run(get_tool_registry().get_tool(name).execute(parameters))


def signed_in(client):
    started = client.post("/api/integrations/google/start", json={"name": "Google",
                          "config": {"client_id": "cid.apps.googleusercontent.com", "client_secret": "shh"}})
    assert started.status_code == 200, started.text
    auth = urlparse(started.json()["auth_url"])
    params = parse_qs(auth.query)
    page = client.get("/api/integrations/google/callback", params={"code": "the-code", "state": params["state"][0]})
    return started.json(), params, page


def test_sign_in_with_the_users_own_client(client):
    started, params, page = signed_in(client)
    assert started["integration"]["status"] == "needs_auth"
    assert params["client_id"] == ["cid.apps.googleusercontent.com"] and params["access_type"] == ["offline"]
    assert params["prompt"] == ["consent"] and "gmail.modify" in params["scope"][0] and "drive.readonly" in params["scope"][0]
    assert page.status_code == 200 and "Signed in" in page.text
    item = next(i for i in client.get("/api/integrations").json() if i["id"] == started["integration"]["id"])
    assert item["status"] == "connected" and item["settings"]["account"] == "me@gmail.com"
    assert "refresh_token" not in str(item) and "shh" not in str(item)  # secrets never come back
    assert {t["remote_name"] for t in item["tools"]} >= {"gmail_search", "gmail_send", "calendar_list_events", "drive_read"}
    assert server_states()["google"]["available"] is True
    client.delete(f"/api/integrations/{item['id']}")


def test_an_unknown_sign_in_link_is_refused(client):
    page = client.get("/api/integrations/google/callback", params={"code": "x", "state": "forged"})
    assert "expired" in page.text


def test_gmail_search_read_send_and_token_refresh(client):
    started, _, _ = signed_in(client)
    integration_id = started["integration"]["id"]
    emails = run("google__gmail_search", query="is:unread")["data"]["emails"]
    assert [e["subject"] for e in emails] == ["Subject m1", "Subject m2"] and emails[0]["unread"] is True
    assert run("google__gmail_read", id="m1")["data"]["body"] == "Hello from m1"

    run("google__gmail_send", to="ravi@x.com", subject="Hi", body="See you at 1")
    raw = json.loads(CALLS[-1].content)["raw"]
    sent = email.message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    assert sent["To"] == "ravi@x.com" and "See you at 1" in sent.get_payload()

    # An expired access token is refreshed once, used, and saved for next time.
    config = store.get_integration(integration_id)["config"]
    store.update_integration(integration_id, config={**config, "access_token": "stale", "expires_at": time.time() - 10})
    from app.integrations import integration_manager
    integration_manager.apply(store.get_integration(integration_id))
    CALLS.clear()
    run("google__gmail_search", query="is:unread")
    assert any(str(c.url).startswith("https://oauth2.googleapis.com/token") for c in CALLS)
    assert store.get_integration(integration_id)["config"]["access_token"] == "access-2"
    client.delete(f"/api/integrations/{integration_id}")


def test_calendar_and_drive(client):
    started, _, _ = signed_in(client)
    events = run("google__calendar_list_events", start="2026-10-12", end="2026-10-19")["data"]["events"]
    assert events[0]["title"] == "Standup" and events[1]["all_day"] is True
    listed = CALLS[-1].url.params
    assert listed["timeMin"].startswith("2026-10-12T00:00:00+05:30")  # dates are read in the user's timezone

    run("google__calendar_create_event", title="Dentist", start="2026-10-20T15:00", end="2026-10-20T16:00")
    body = json.loads(CALLS[-1].content)
    assert body["summary"] == "Dentist" and body["start"] == {"dateTime": "2026-10-20T15:00:00", "timeZone": "Asia/Kolkata"}

    files = run("google__drive_search", query="budget")["data"]["files"]
    assert files[0]["name"] == "Budget 2026"
    assert run("google__drive_read", id="d1")["data"]["text"] == "Budget: 120k for tools"
    client.delete(f"/api/integrations/{started['integration']['id']}")


def test_writes_wait_for_approval(client):
    started, _, _ = signed_in(client)
    policies = {t.remote_name: t.policy for t in get_tool_registry().get_tools_for_app("google", app_connected=True)}
    assert policies["gmail_send"] == "ask" and policies["calendar_create_event"] == "ask"
    assert policies["gmail_search"] == policies["drive_read"] == "allow"
    client.delete(f"/api/integrations/{started['integration']['id']}")


def test_drafts_are_saved_not_sent_and_need_no_approval(client):
    started, _, _ = signed_in(client)
    tool = get_tool_registry().get_tool("google__gmail_draft")
    assert tool.policy == "allow"
    run("google__gmail_draft", to="ravi@x.com", subject="Re: Lunch", body="Yes, 1 works.", reply_to_id="m1")
    body = json.loads(CALLS[-1].content)
    assert CALLS[-1].url.path == "/gmail/v1/users/me/drafts" and body["message"]["threadId"] == "t1"
    raw = body["message"]["raw"]
    draft = email.message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    assert draft["To"] == "ravi@x.com" and "1 works" in draft.get_payload()
    client.delete(f"/api/integrations/{started['integration']['id']}")


def test_files_can_be_attached(client):
    from app.files import create_file

    started, _, _ = signed_in(client)
    made = create_file("report.csv", "a,b\n1,2")
    run("google__gmail_send", to="ravi@x.com", subject="Report", body="Attached.", attachments=made["id"])
    raw = json.loads(CALLS[-1].content)["raw"]
    sent = email.message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    parts = [p.get_filename() for p in sent.walk() if p.get_filename()]
    assert parts == ["report.csv"]
    client.delete(f"/api/integrations/{started['integration']['id']}")
