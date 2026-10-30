"""Sign up, log in, log out, and who is signed in.

The session lives in an HttpOnly cookie (scripts can't read it), SameSite=Lax, and Secure over HTTPS. The first
account is the owner (admin); anyone else can sign up too, unless the admin closes sign-ups (Settings › Admin, or
NEXUS_SIGNUPS=closed). Every account's data is its own (see app/auth/owner.py).

The sign-in page asks for the email first, then /lookup says what comes next: the password, Google, creating the
account, or nothing (sign-ups closed).
"""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.auth import mailer, store

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE = "nexus_session"
MAX_FAILURES, WINDOW_SECONDS = 10, 60  # failed logins per IP per minute before it has to wait
SIGNUP_LIMIT = 5   # new accounts per IP per minute (stops mass sign-up abuse when sign-ups are open)
EMAIL_LIMIT = 5    # emails sent per IP per minute (reset / resend): stops mailbox flooding and token spam
LOOKUP_LIMIT = 20  # email lookups per IP per minute: plenty for typos, too few to sweep a list of addresses
FAILED_LOGINS: dict[str, deque[float]] = defaultdict(deque)
RATE_BUCKETS: dict[tuple[str, str], deque[float]] = defaultdict(deque)
WRONG = "Wrong email or password"


def _rate_limit(bucket: str, request: Request, limit: int, window: int = WINDOW_SECONDS) -> None:
    """Allow ``limit`` requests to ``bucket`` per IP per ``window`` seconds, else 429. Per process (one deployment)."""
    hits = RATE_BUCKETS[(bucket, _client(request))]
    now = time.monotonic()
    while hits and now - hits[0] > window:
        hits.popleft()
    if len(hits) >= limit:
        raise HTTPException(status_code=429, detail="Too many attempts. Please wait a minute and try again.")
    hits.append(now)
    if len(RATE_BUCKETS) > 10_000:  # bound memory under IP churn: drop buckets that have emptied out
        for key in [k for k, v in RATE_BUCKETS.items() if not v]:
            del RATE_BUCKETS[key]


def reset_rate_limits() -> None:
    FAILED_LOGINS.clear()
    RATE_BUCKETS.clear()


class SignupIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)
    name: str = Field(default="", max_length=80)


class TokenIn(BaseModel):
    token: str = Field(max_length=200)


class EmailIn(BaseModel):
    email: str = Field(max_length=254)


class ResetIn(BaseModel):
    token: str = Field(max_length=200)
    password: str = Field(max_length=200)


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


def signups_open() -> bool:
    from app.quota import signups_setting

    return store.user_count() == 0 or signups_setting()


def session_user(request: Request) -> Optional[dict[str, Any]]:
    return store.user_for_session(request.cookies.get(COOKIE))


def _sign_in(request: Request, response: Response, user: dict[str, Any]) -> dict[str, Any]:
    token = store.create_session(user["id"], request.headers.get("user-agent", ""))
    secure = request.url.scheme == "https" or os.getenv("NEXUS_SECURE_COOKIES", "").lower() == "true"
    response.set_cookie(COOKIE, token, max_age=store.SESSION_DAYS * 86400, httponly=True, samesite="lax",
                        secure=secure, path="/")
    return store.public(user)


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _recent_failures(ip: str) -> deque[float]:
    failures = FAILED_LOGINS[ip]
    while failures and time.monotonic() - failures[0] > WINDOW_SECONDS:
        failures.popleft()
    return failures


@router.get("/status")
def status(request: Request) -> dict[str, Any]:
    user = session_user(request)
    from app.api.routes.auth_google import configured as google_ready

    from app.quota import instance

    links = instance()
    return {"hasUsers": store.user_count() > 0, "signupsOpen": signups_open(), "user": store.public(user) if user else None,
            "google": google_ready(), "email": mailer.configured(),
            "privacyUrl": links["privacyUrl"], "termsUrl": links["termsUrl"]}


@router.post("/lookup")
def lookup(body: EmailIn, request: Request) -> dict[str, str]:
    """What the sign-in page asks after the email. This tells whether an email has an account, which sign-up has to
    say anyway (with open sign-ups); the rate limit keeps it from being used to sweep a list of addresses."""
    _rate_limit("lookup", request, LOOKUP_LIMIT)
    email = store.normalise_email(body.email)
    if not store.EMAIL.match(email):
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    user = store._row("email = ?", email)
    if user is not None:  # disabled accounts too: sign-in itself refuses them without saying why
        return {"next": "password" if user["password_hash"] else "google"}
    return {"next": "create" if signups_open() else "closed"}


@router.post("/signup")
def signup(body: SignupIn, request: Request, response: Response) -> dict[str, Any]:
    _rate_limit("signup", request, SIGNUP_LIMIT)
    if not signups_open():
        raise HTTPException(status_code=403, detail="Sign-ups are closed on this Nexus. Ask its owner for an account.")
    try:
        user = store.create_user(body.email, body.password, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=409 if "already" in str(exc) else 422, detail=str(exc))
    signed_in = _sign_in(request, response, user)
    if store.needs_verification(user):
        try:
            mailer.send_verification(user["email"], store.issue_token(user["id"], "verify", 48))
        except RuntimeError:
            pass  # they can ask for it again from the "check your email" screen
    return signed_in


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response) -> dict[str, Any]:
    failures = _recent_failures(_client(request))
    if len(failures) >= MAX_FAILURES:
        raise HTTPException(status_code=429, detail="Too many wrong passwords. Wait a minute and try again.")
    user = store.authenticate(body.email, body.password)
    if user is None:
        failures.append(time.monotonic())
        raise HTTPException(status_code=401, detail=WRONG)
    return _sign_in(request, response, user)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response) -> Response:
    store.end_session(request.cookies.get(COOKIE))
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path="/")
    return response


@router.post("/verify-email")
def verify_email(body: TokenIn) -> dict[str, Any]:
    user_id = store.use_token(body.token, "verify")
    if user_id is None:
        raise HTTPException(status_code=400, detail="This link has expired or was already used. Ask for a new one.")
    store.mark_verified(user_id)
    return store.public(store.get_user(user_id))


@router.post("/resend-verification", status_code=204)
def resend_verification(request: Request) -> Response:
    user = session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to use Nexus")
    _rate_limit("email", request, EMAIL_LIMIT)
    if store.needs_verification(user):
        try:
            mailer.send_verification(user["email"], store.issue_token(user["id"], "verify", 48))
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
    return Response(status_code=204)


@router.post("/forgot-password", status_code=204)
def forgot_password(body: EmailIn, request: Request) -> Response:
    """Always the same answer, so it never tells whether an email has an account."""
    _rate_limit("email", request, EMAIL_LIMIT)
    user = store._row("email = ?", store.normalise_email(body.email))
    if user is not None and not user["disabled"] and mailer.configured():
        try:
            mailer.send_reset(user["email"], store.issue_token(user["id"], "reset", 1))
        except RuntimeError:
            pass
    return Response(status_code=204)


@router.post("/reset-password")
def reset_password(body: ResetIn, request: Request, response: Response) -> dict[str, Any]:
    try:
        store.check_password_rules(body.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    user_id = store.use_token(body.token, "reset")
    if user_id is None:
        raise HTTPException(status_code=400, detail="This link has expired or was already used. Ask for a new one.")
    store.set_password(user_id, body.password)
    store.mark_verified(user_id)  # they read an email sent to it
    store.end_all_sessions(user_id)  # whoever had the old password is signed out
    return _sign_in(request, response, store.get_user(user_id))


@router.get("/me")
def me(request: Request) -> dict[str, Any]:
    user = session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to use Nexus")
    return store.public(user)
