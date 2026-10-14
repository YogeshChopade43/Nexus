"""Sign in (and up) with Google, using OpenID Connect's authorization code flow.

A separate Google client from the Gmail integration's (NEXUS_GOOGLE_CLIENT_ID / NEXUS_GOOGLE_CLIENT_SECRET), with
the redirect URI ``<NEXUS_PUBLIC_URL or this server>/api/auth/google/callback``. Each sign-in carries a random
``state`` that works once, for 10 minutes. Who signed in comes from Google's userinfo endpoint (over TLS, with the
access token just issued), so no token signature handling is needed here.

Accounts are matched by Google's id; else by email, but only one Google says is verified (then linked); else a
new account is made, if sign-ups are open (or it's the very first account, the owner).
"""
from __future__ import annotations

import os
import secrets
import time
from typing import Any, Optional
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from app.api.routes.auth import COOKIE, signups_open
from app.auth import mailer, store

router = APIRouter(prefix="/api/auth/google", tags=["auth"])

AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"
STATE_SECONDS = 600
TRANSPORT: Optional[httpx.BaseTransport] = None  # tests put a fake Google here
_states: dict[str, float] = {}  # state -> when it stops working


def configured() -> bool:
    return bool(os.getenv("NEXUS_GOOGLE_CLIENT_ID") and os.getenv("NEXUS_GOOGLE_CLIENT_SECRET"))


def _redirect_uri(request: Request) -> str:
    base = (os.getenv("NEXUS_PUBLIC_URL") or str(request.base_url)).rstrip("/")
    return f"{base}/api/auth/google/callback"


def _back(error: Optional[str] = None) -> RedirectResponse:
    target = f"{mailer.app_url()}/" if error is None else f"{mailer.app_url()}/login?error={quote(error)}"
    return RedirectResponse(target, status_code=302)


@router.get("/start")
def start(request: Request) -> Response:
    if not configured():
        raise HTTPException(status_code=404, detail="Google sign-in isn't set up on this Nexus")
    now = time.monotonic()
    for old in [s for s, until in _states.items() if until < now]:
        _states.pop(old, None)
    state = secrets.token_urlsafe(24)
    _states[state] = now + STATE_SECONDS
    query = urlencode({"client_id": os.environ["NEXUS_GOOGLE_CLIENT_ID"], "redirect_uri": _redirect_uri(request),
                       "response_type": "code", "scope": "openid email profile", "state": state,
                       "prompt": "select_account"})
    return RedirectResponse(f"{AUTHORIZE}?{query}", status_code=302)


def _profile(request: Request, code: str) -> dict[str, Any]:
    with httpx.Client(timeout=20, transport=TRANSPORT) as client:
        token = client.post(TOKEN, data={"code": code, "client_id": os.environ["NEXUS_GOOGLE_CLIENT_ID"],
                                         "client_secret": os.environ["NEXUS_GOOGLE_CLIENT_SECRET"],
                                         "redirect_uri": _redirect_uri(request), "grant_type": "authorization_code"})
        token.raise_for_status()
        info = client.get(USERINFO, headers={"Authorization": f"Bearer {token.json()['access_token']}"})
        info.raise_for_status()
    return info.json()


def _account_for(profile: dict[str, Any]) -> dict[str, Any]:
    """The Nexus account for this Google profile (linked or made now). Raises ValueError with what to tell them."""
    sub, verified = str(profile.get("sub") or ""), bool(profile.get("email_verified"))
    email = store.normalise_email(str(profile.get("email") or ""))
    if not sub or not email:
        raise ValueError("Google didn't share your email address")
    user = store._row("google_sub = ?", sub)
    if user is None:
        existing = store._row("email = ?", email)
        if existing is not None:
            if not verified:
                raise ValueError("Google hasn't verified that email address, so it can't be linked to your account")
            store._update_user(existing["id"], "google_sub = ?, email_verified = 1", sub)
            user = store.get_user(existing["id"])
        elif not signups_open():
            raise ValueError("Sign-ups are closed on this Nexus. Ask its owner for an account.")
        else:
            user = store.create_user(email, None, str(profile.get("name") or ""), email_verified=verified, google_sub=sub)
    if user["disabled"]:
        raise ValueError("This account is disabled")
    return user


@router.get("/callback")
def callback(request: Request, code: str = "", state: str = "", error: str = "") -> Response:
    if error:
        return _back("Google sign-in was cancelled")
    until = _states.pop(state, None)  # once only
    if until is None or until < time.monotonic() or not code:
        return _back("That sign-in link expired. Try again.")
    try:
        user = _account_for(_profile(request, code))
    except ValueError as exc:
        return _back(str(exc))
    except httpx.HTTPError:
        return _back("Couldn't reach Google. Try again.")
    response = _back()
    secure = request.url.scheme == "https" or os.getenv("NEXUS_SECURE_COOKIES", "").lower() == "true"
    response.set_cookie(COOKIE, store.create_session(user["id"], request.headers.get("user-agent", "")),
                        max_age=store.SESSION_DAYS * 86400, httponly=True, samesite="lax", secure=secure, path="/")
    return response
