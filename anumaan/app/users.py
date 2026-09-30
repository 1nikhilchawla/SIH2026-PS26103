#!/usr/bin/env python3
"""Ministry-scoped logins.

Two roles, matching who reads ANUMAAN:
    mospi      MoSPI / IPMD. Sees every ministry's projects, can export.
    ministry   One ministry's nodal officers. Sees only that ministry's
               projects - every list, project page, what-if, snapshot and
               offline bundle is filtered, and another ministry's project
               answers 404 exactly as if it did not exist.

Where users come from:
    ANUMAAN_USERS_FILE   JSON written by `python scripts/users.py add ...`:
        {"users": [{"user": "morth.nodal", "role": "ministry",
                    "ministry": "Ministry of Road Transport & Highways",
                    "password": "scrypt$16384$8$1$<salt-hex>$<hash-hex>"}]}
    ANUMAAN_VIEW_USER / ANUMAAN_VIEW_PASSWORD
        the older single login; treated as one `mospi` user.

Passwords are stored only as scrypt hashes (salted, memory-hard). Checking a
scrypt hash costs tens of milliseconds by design, so a verified credential is
cached for AUTH_CACHE_TTL_S under an HMAC of the header with a per-process
random key - the cache never holds the password, and a restart empties it.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

ROLES = ("mospi", "ministry")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.@-]{3,64}$")
SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN = 2 ** 14, 8, 1, 32
MIN_PASSWORD_CHARS = 12
AUTH_CACHE_TTL_S = 300
AUTH_CACHE_MAX = 1000


@dataclass(frozen=True)
class Principal:
    user: str
    role: str                   # "mospi" | "ministry" | "open"
    ministry: str | None = None

    def can_see(self, ministry: object) -> bool:
        if self.role in ("mospi", "open"):
            return True
        return self.role == "ministry" and ministry == self.ministry

    def public(self) -> dict:
        return {"user": self.user, "role": self.role, "ministry": self.ministry}


# "open" = no viewer authentication configured (development only; production
# refuses to start without logins).
OPEN = Principal(user="anonymous", role="open")


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_CHARS:
        raise ValueError(f"password must be at least {MIN_PASSWORD_CHARS} characters")
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R,
                        p=SCRYPT_P, dklen=SCRYPT_DKLEN, maxmem=64 * 1024 * 1024)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    parts = stored.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return False
    try:
        n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        salt, want = bytes.fromhex(parts[4]), bytes.fromhex(parts[5])
    except ValueError:
        return False
    got = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
                         dklen=len(want), maxmem=64 * 1024 * 1024)
    return hmac.compare_digest(got, want)


# A real hash of a random password: unknown user names still pay one scrypt
# evaluation, so response time does not reveal which user names exist.
_DUMMY_HASH = hash_password(base64.b64encode(os.urandom(24)).decode())


class UserStore:
    def __init__(self, users: dict[str, dict]):
        self._users = users

    @classmethod
    def from_file(cls, path: Path) -> "UserStore":
        blob = json.loads(Path(path).read_text(encoding="utf-8"))
        rows = blob.get("users") if isinstance(blob, dict) else None
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"{path}: expected {{\"users\": [...]}} with at least one user")
        users: dict[str, dict] = {}
        for i, u in enumerate(rows):
            name = u.get("user", "")
            if not USERNAME_RE.fullmatch(name):
                raise ValueError(f"{path}: user #{i} has an invalid name {name!r}")
            if name in users:
                raise ValueError(f"{path}: duplicate user {name!r}")
            role = u.get("role")
            if role not in ROLES:
                raise ValueError(f"{path}: user {name!r} role must be one of {ROLES}")
            ministry = u.get("ministry")
            if role == "ministry" and not ministry:
                raise ValueError(f"{path}: ministry user {name!r} needs a ministry")
            if role == "mospi" and ministry:
                raise ValueError(f"{path}: mospi user {name!r} must not name a ministry")
            if not str(u.get("password", "")).startswith("scrypt$"):
                raise ValueError(f"{path}: user {name!r} password is not a scrypt hash")
            users[name] = {"role": role, "ministry": ministry, "password": u["password"]}
        return cls(users)

    @classmethod
    def single(cls, user: str, password: str) -> "UserStore":
        """The legacy ANUMAAN_VIEW_USER / _PASSWORD login, as one mospi user."""
        return cls({user: {"role": "mospi", "ministry": None, "plain": password}})

    def ministries(self) -> set[str]:
        return {u["ministry"] for u in self._users.values() if u["ministry"]}

    def __len__(self) -> int:
        return len(self._users)

    def authenticate(self, user: str, password: str) -> Principal | None:
        rec = self._users.get(user)
        if rec is None:
            verify_password(password, _DUMMY_HASH)
            return None
        if "plain" in rec:
            ok = hmac.compare_digest(password.encode("utf-8"), rec["plain"].encode("utf-8"))
        else:
            ok = verify_password(password, rec["password"])
        return Principal(user=user, role=rec["role"], ministry=rec["ministry"]) if ok else None


class AuthCache:
    """Header digest -> Principal, for AUTH_CACHE_TTL_S. Bounded; LRU eviction."""

    def __init__(self) -> None:
        self._key = os.urandom(32)
        self._items: OrderedDict[bytes, tuple[float, Principal]] = OrderedDict()
        self._lock = threading.Lock()

    def _digest(self, header: str) -> bytes:
        return hmac.new(self._key, header.encode("utf-8"), hashlib.sha256).digest()

    def get(self, header: str) -> Principal | None:
        d = self._digest(header)
        now = time.monotonic()
        with self._lock:
            hit = self._items.get(d)
            if hit is None:
                return None
            if hit[0] < now:
                del self._items[d]
                return None
            self._items.move_to_end(d)
            return hit[1]

    def put(self, header: str, principal: Principal) -> None:
        d = self._digest(header)
        with self._lock:
            self._items[d] = (time.monotonic() + AUTH_CACHE_TTL_S, principal)
            self._items.move_to_end(d)
            while len(self._items) > AUTH_CACHE_MAX:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


def parse_basic(header: str | None) -> tuple[str, str] | None:
    if not header or not header.startswith("Basic "):
        return None
    try:
        raw = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    user, sep, pw = raw.partition(":")
    return (user, pw) if sep else None
