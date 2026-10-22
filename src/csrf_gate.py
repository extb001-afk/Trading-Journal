from __future__ import annotations

import hmac
from typing import Any

import settings_store as ss

__all__ = ["HDR", "begin", "use_session", "token_for", "check"]

HDR = "X-TJ-CSRF"


def begin(h: Any) -> None:
    h.tj_csrf_mode, h.tj_csrf_expect = "install", ""


def use_session(h: Any, expect: str) -> None:
    h.tj_csrf_mode, h.tj_csrf_expect = "session", expect or ""


def token_for(h: Any) -> str:
    if getattr(h, "tj_csrf_mode", "install") == "session":
        return getattr(h, "tj_csrf_expect", "") or ""
    return ss.csrf_token()


def check(h: Any) -> bool:
    got = (h.headers.get(HDR) or "").encode("utf-8", "replace")
    want = token_for(h).encode("utf-8", "replace")
    return bool(got) and bool(want) and hmac.compare_digest(got, want)
