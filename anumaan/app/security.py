#!/usr/bin/env python3
"""Request-level security for the ANUMAAN service.

Everything here is enforced by the server, not by the page: a check that only
the browser runs is a check an agent with curl skips.

What this module owns
    - Settings read from the environment, validated once at startup.
      In production (ANUMAAN_ENV=production) a missing secret is a startup
      error, never a silent downgrade to an open service.
    - Viewer authentication (HTTP Basic) for every route except the health
      check, when viewer credentials are configured. Always required in
      production.
    - Admin authorisation for the one route that changes server state
      (/api/retrain): a bearer token in X-Admin-Token, compared in constant
      time. With no token configured the route is closed, except to a
      loopback client in development so the local demo still works.
    - Host allow-list, request-size cap, per-client rate limits.
    - Security headers on every response (CSP, frame-ancestors, nosniff,
      HSTS in production, no-store on the API).
    - One JSON audit line per request on stdout. Credentials are never
      logged; the query string is not logged either.

What it deliberately does NOT do
    - CORS. No CORSMiddleware is installed, so browsers refuse cross-origin
      reads of the API. Adding one is a decision, not a default.
    - Trust X-Forwarded-For. uvicorn only honours it from 127.0.0.1 (its
      default). Behind a proxy every client therefore shares one rate-limit
      bucket - which fails towards throttling, not towards letting a spoofed
      header buy a fresh bucket per request.
"""
from __future__ import annotations

import hmac
import os
import re
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from pathlib import Path

from app.audit import AuditLog
from app.users import OPEN, AuthCache, Principal, UserStore, parse_basic

MIN_SECRET_CHARS = 32
LOOPBACK = {"127.0.0.1", "::1", "localhost"}

# Paths that must answer without credentials: the platform health probe, and
# the service worker and web-app manifest, which browsers fetch without
# credentials. None of the three carries any data.
PUBLIC_PATHS = {"/api/health", "/sw.js", "/manifest.webmanifest"}
# Interactive API docs load Swagger UI from a CDN, so the strict CSP would
# break them. They are disabled entirely in production (see app/main.py).
DOCS_PATHS = {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
       "object-src 'none'; base-uri 'none'; form-action 'self'; "
       "frame-ancestors 'none'")


@dataclass(frozen=True)
class Settings:
    production: bool
    view_user: str | None
    view_password: str | None
    admin_token: str | None
    integrity_key: str | None
    allowed_hosts: tuple[str, ...]
    max_body_bytes: int
    rate_api_per_min: int
    rate_score_per_min: int
    rate_retrain_per_hour: int
    users_file: str | None = None
    audit_file: str | None = None
    laya_url: str | None = None
    laya_token: str | None = None
    rate_remark_per_min: int = 20
    problems: tuple[str, ...] = field(default=())

    @property
    def viewer_auth_on(self) -> bool:
        return bool(self.users_file or (self.view_user and self.view_password))


def _int_env(name: str, default: int, lo: int, hi: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    if not re.fullmatch(r"\d+", raw.strip()):
        raise RuntimeError(f"{name} must be a whole number, got {raw!r}")
    v = int(raw.strip())
    if not lo <= v <= hi:
        raise RuntimeError(f"{name}={v} is outside the allowed range {lo}..{hi}")
    return v


def load_settings() -> Settings:
    """Read and validate settings. Problems are collected, and enforce()
    turns any of them into a startup failure."""
    env = os.environ.get("ANUMAAN_ENV", "development").strip().lower()
    if env not in ("development", "production"):
        raise RuntimeError(f"ANUMAAN_ENV must be development or production, got {env!r}")
    production = env == "production"

    view_user = os.environ.get("ANUMAAN_VIEW_USER") or None
    view_password = os.environ.get("ANUMAAN_VIEW_PASSWORD") or None
    admin_token = os.environ.get("ANUMAAN_ADMIN_TOKEN") or None
    integrity_key = os.environ.get("ANUMAAN_INTEGRITY_KEY") or None
    hosts_raw = os.environ.get("ANUMAAN_ALLOWED_HOSTS", "")
    hosts = tuple(h.strip().lower() for h in hosts_raw.split(",") if h.strip())
    if not hosts and not production:
        hosts = ("127.0.0.1", "localhost", "testserver")

    problems: list[str] = []
    if bool(view_user) != bool(view_password):
        problems.append("set both ANUMAAN_VIEW_USER and ANUMAAN_VIEW_PASSWORD, or neither")
    if view_password and len(view_password) < 12:
        problems.append("ANUMAAN_VIEW_PASSWORD must be at least 12 characters")
    if admin_token and len(admin_token) < MIN_SECRET_CHARS:
        problems.append(f"ANUMAAN_ADMIN_TOKEN must be at least {MIN_SECRET_CHARS} characters")
    if integrity_key and len(integrity_key) < MIN_SECRET_CHARS:
        problems.append(f"ANUMAAN_INTEGRITY_KEY must be at least {MIN_SECRET_CHARS} characters")
    if "*" in hosts:
        problems.append("ANUMAAN_ALLOWED_HOSTS must list real host names, not '*'")

    users_file = os.environ.get("ANUMAAN_USERS_FILE") or None
    if users_file and not os.path.isfile(users_file):
        problems.append(f"ANUMAAN_USERS_FILE {users_file!r} does not exist "
                        "(create it with: python scripts/users.py add ...)")
    audit_file = os.environ.get("ANUMAAN_AUDIT_FILE") or None
    if audit_file and not os.path.isdir(os.path.dirname(os.path.abspath(audit_file))):
        problems.append(f"ANUMAAN_AUDIT_FILE directory for {audit_file!r} does not exist")
    laya_url = os.environ.get("ANUMAAN_LAYA_URL") or None
    laya_token = os.environ.get("ANUMAAN_LAYA_TOKEN") or None
    if laya_url:
        if not re.fullmatch(r"https?://[A-Za-z0-9.-]+(:\d{1,5})?/?", laya_url):
            problems.append("ANUMAAN_LAYA_URL must be http(s)://host[:port] with no path")
        if not laya_token or len(laya_token) < MIN_SECRET_CHARS:
            problems.append(f"ANUMAAN_LAYA_TOKEN must be set to {MIN_SECRET_CHARS}+ characters "
                            "when ANUMAAN_LAYA_URL is set")

    if production:
        if not (users_file or (view_user and view_password)):
            problems.append("production requires logins: ANUMAAN_USERS_FILE, or "
                            "ANUMAAN_VIEW_USER and ANUMAAN_VIEW_PASSWORD")
        if not admin_token:
            problems.append("production requires ANUMAAN_ADMIN_TOKEN")
        if not integrity_key:
            problems.append("production requires ANUMAAN_INTEGRITY_KEY")
        if not hosts:
            problems.append("production requires ANUMAAN_ALLOWED_HOSTS "
                            "(e.g. your-app.up.railway.app)")

    return Settings(
        production=production,
        view_user=view_user, view_password=view_password,
        admin_token=admin_token, integrity_key=integrity_key,
        allowed_hosts=hosts,
        max_body_bytes=_int_env("ANUMAAN_MAX_BODY_BYTES", 4096, 256, 1 << 20),
        rate_api_per_min=_int_env("ANUMAAN_RATE_API_PER_MIN", 240, 1, 100000),
        rate_score_per_min=_int_env("ANUMAAN_RATE_SCORE_PER_MIN", 30, 1, 10000),
        rate_retrain_per_hour=_int_env("ANUMAAN_RATE_RETRAIN_PER_HOUR", 6, 1, 1000),
        users_file=users_file, audit_file=audit_file,
        laya_url=laya_url, laya_token=laya_token,
        rate_remark_per_min=_int_env("ANUMAAN_RATE_REMARK_PER_MIN", 20, 1, 1000),
        problems=tuple(problems),
    )


def enforce(settings: Settings) -> None:
    """Refuse to start on any settings problem. Development is not exempt:
    a half-configured secret is a mistake in either mode."""
    if settings.problems:
        raise RuntimeError("insecure configuration, refusing to start:\n  - "
                           + "\n  - ".join(settings.problems))


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def _eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def build_user_store(settings: Settings) -> UserStore | None:
    """The user store for this process, or None when viewer auth is off
    (development only - production refuses to start without logins)."""
    if settings.users_file:
        return UserStore.from_file(Path(settings.users_file))
    if settings.view_user and settings.view_password:
        return UserStore.single(settings.view_user, settings.view_password)
    return None


def resolve_principal(store: UserStore | None, cache: AuthCache,
                      authorization: str | None) -> Principal | None:
    """Principal for this request, or None if the credentials are missing or
    wrong. With no store configured everyone is the development OPEN
    principal."""
    if store is None:
        return OPEN
    if not authorization:
        return None
    hit = cache.get(authorization)
    if hit is not None:
        return hit
    creds = parse_basic(authorization)
    if creds is None:
        return None
    principal = store.authenticate(*creds)
    if principal is not None:
        cache.put(authorization, principal)
    return principal


def admin_ok(settings: Settings, token: str | None, client_host: str | None) -> tuple[bool, str]:
    """Return (allowed, principal). Development + loopback + no token
    configured is the only unauthenticated path, so the local demo keeps
    its Retrain button without a secret on the laptop."""
    if settings.admin_token:
        if token and _eq(token, settings.admin_token):
            return True, "admin"
        return False, "anonymous"
    if not settings.production and client_host in LOOPBACK:
        return True, "loopback-dev"
    return False, "anonymous"


# ---------------------------------------------------------------------------
# Rate limiting - sliding window, in memory, bounded
# ---------------------------------------------------------------------------

class RateLimiter:
    """Sliding-window counter per (bucket, client). Memory is bounded: at most
    `max_keys` clients are tracked and the least recently seen is evicted.

    Single-process only. With more than one replica each has its own window,
    so the effective limit is limit x replicas; a shared store (Redis) is the
    fix when the service scales out."""

    def __init__(self, max_keys: int = 10000) -> None:
        self._hits: OrderedDict[tuple[str, str], deque] = OrderedDict()
        self._lock = threading.Lock()
        self._max_keys = max_keys

    def allow(self, bucket: str, client: str, limit: int, window_s: float) -> tuple[bool, int]:
        now = time.monotonic()
        key = (bucket, client)
        with self._lock:
            q = self._hits.get(key)
            if q is None:
                q = deque()
                self._hits[key] = q
                if len(self._hits) > self._max_keys:
                    self._hits.popitem(last=False)
            else:
                self._hits.move_to_end(key)
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                retry = max(1, int(window_s - (now - q[0])) + 1)
                return False, retry
            q.append(now)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


LIMITER = RateLimiter()


# ---------------------------------------------------------------------------
# Headers and audit
# ---------------------------------------------------------------------------

def security_headers(settings: Settings, path: str) -> dict[str, str]:
    h = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Resource-Policy": "same-origin",
    }
    if path not in DOCS_PATHS:
        h["Content-Security-Policy"] = CSP
    if path.startswith("/api/"):
        h["Cache-Control"] = "no-store"
    if settings.production:
        h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return h


# Replaced at startup by app/main.py with AuditLog(settings.audit_file), so
# every event is also appended to the hash-chained file when one is set.
AUDIT = AuditLog(None)


def audit(event: dict) -> None:
    """One JSON line on stdout, and in ANUMAAN_AUDIT_FILE as a hash chain
    (app/audit.py). CERT-In (Directions of 28 Apr 2022) expects 180 days of
    logs kept in India - a retention setting on the log drain."""
    AUDIT.write(event)
