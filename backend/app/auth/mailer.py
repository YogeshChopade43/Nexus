"""Sending account email (verify your address, reset your password).

One of, from the environment:
- SMTP: NEXUS_SMTP_HOST (+ NEXUS_SMTP_PORT, NEXUS_SMTP_USER, NEXUS_SMTP_PASSWORD, NEXUS_SMTP_STARTTLS=true by default)
- Resend: NEXUS_RESEND_API_KEY
- a folder (development, tests): NEXUS_MAIL_DIR, one .eml file per message
The sender is NEXUS_MAIL_FROM. With none set, no email is sent, so nothing that needs one (verification) is required.
"""
from __future__ import annotations

import logging
import os
import secrets
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)
TRANSPORT: Optional[httpx.BaseTransport] = None  # tests put a fake Resend here


def configured() -> bool:
    return any(os.getenv(name) for name in ("NEXUS_SMTP_HOST", "NEXUS_RESEND_API_KEY", "NEXUS_MAIL_DIR"))


def app_url() -> str:
    """Where people open Nexus (links in emails, the return from Google)."""
    from app.core.config import CORS_ORIGINS

    return (os.getenv("NEXUS_APP_URL") or (CORS_ORIGINS[0] if CORS_ORIGINS else "http://localhost:5173")).rstrip("/")


def _sender() -> str:
    return os.getenv("NEXUS_MAIL_FROM") or "Nexus <no-reply@localhost>"


def send(to: str, subject: str, text: str) -> None:
    """Send one plain-text email. Raises RuntimeError when delivery fails (the caller decides what to say)."""
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = _sender(), to, subject
    message.set_content(text, cte="8bit")  # links stay on one line (no quoted-printable breaks)
    try:
        if folder := os.getenv("NEXUS_MAIL_DIR"):
            path = Path(folder)
            path.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
            (path / f"{stamp}-{secrets.token_hex(3)}.eml").write_text(message.as_string(), encoding="utf-8")
        elif key := os.getenv("NEXUS_RESEND_API_KEY"):
            with httpx.Client(timeout=20, transport=TRANSPORT) as client:
                response = client.post("https://api.resend.com/emails", headers={"Authorization": f"Bearer {key}"},
                                       json={"from": _sender(), "to": [to], "subject": subject, "text": text})
            response.raise_for_status()
        elif host := os.getenv("NEXUS_SMTP_HOST"):
            with smtplib.SMTP(host, int(os.getenv("NEXUS_SMTP_PORT") or 587), timeout=20) as smtp:
                if os.getenv("NEXUS_SMTP_STARTTLS", "true").lower() != "false":
                    smtp.starttls()
                if user := os.getenv("NEXUS_SMTP_USER"):
                    smtp.login(user, os.getenv("NEXUS_SMTP_PASSWORD", ""))
                smtp.send_message(message)
        else:
            return
    except Exception as exc:
        logger.warning("Couldn't send '%s' to %s: %s", subject, to, exc)
        raise RuntimeError("The email couldn't be sent. Try again in a minute.") from exc


def send_verification(to: str, token: str) -> None:
    send(to, "Confirm your email for Nexus",
         f"Welcome to Nexus!\n\nConfirm this is your email address:\n{app_url()}/verify-email?token={token}\n\n"
         "The link works once, for 48 hours. If you didn't sign up, ignore this email.")


def send_reset(to: str, token: str) -> None:
    send(to, "Reset your Nexus password",
         f"Someone (hopefully you) asked to reset your Nexus password.\n\nChoose a new one here:\n"
         f"{app_url()}/reset-password?token={token}\n\nThe link works once, for 1 hour. If it wasn't you, ignore this "
         "email: your password stays the same.")
