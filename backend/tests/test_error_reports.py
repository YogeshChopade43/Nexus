"""Unexpected errors go to Sentry when SENTRY_DSN is set, without passwords, cookies or personal data."""
from __future__ import annotations

import sentry_sdk

from app.main import setup_error_reports


def test_nothing_is_sent_without_a_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    calls = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: calls.append(kw))
    assert setup_error_reports() is False and calls == []


def test_errors_are_reported_without_personal_data(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://key@sentry.example/1")
    calls = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: calls.append(kw))
    assert setup_error_reports() is True
    options = calls[0]
    assert options["dsn"] == "https://key@sentry.example/1"
    assert options["send_default_pii"] is False  # no cookies, IPs or user emails
    assert options["max_request_body_size"] == "never"  # sign-in bodies carry passwords
