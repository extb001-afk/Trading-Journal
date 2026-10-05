"""Network request pacing and rate limiting."""
from __future__ import annotations

import threading
import time
import urllib.error
import urllib.parse

EXPLORER_SEC = 3.0
OTHER_SEC = 0.35
COOLDOWN_SEC = 300.0
_EXPLORER_MARKS = ("blockscout", "wormholescan", "etherscan", "bscscan", "debridge", "relay.link")

_lock = threading.Lock()
_next = {}
_cool = {}
_stats = {}


class Cooldown(OSError):
    pass


def configure(cfg: dict | None):
    global EXPLORER_SEC, OTHER_SEC, COOLDOWN_SEC
    np_ = (cfg or {}).get("net_pace") or {}
    try:
        EXPLORER_SEC = float(np_.get("explorer_sec", EXPLORER_SEC))
        OTHER_SEC = float(np_.get("other_sec", OTHER_SEC))
        COOLDOWN_SEC = float(np_.get("cooldown_sec", COOLDOWN_SEC))
    except (TypeError, ValueError):
        pass


def host_of(url: str) -> str:
    try:
        return (urllib.parse.urlsplit(str(url)).hostname or "").lower()
    except ValueError:
        return ""


def cool_key(url: str) -> str:
    try:
        u = urllib.parse.urlsplit(str(url))
    except ValueError:
        return ""
    path = u.path or ""
    br = "v2" if path.startswith("/api/v2") else ("v1" if path.startswith("/api") else "")
    return (u.hostname or "").lower() + (":" + br if br else "")


def interval_for(host: str) -> float:
    return EXPLORER_SEC if any(m in host for m in _EXPLORER_MARKS) else OTHER_SEC


def wait(url: str, now=time.time, sleep=time.sleep):
    h, ck = host_of(url), cool_key(url)
    with _lock:
        t = now()
        st = _stats.setdefault(h, {"n": 0, "rl": 0, "skip": 0})
        if _cool.get(ck, 0) > t:
            st["skip"] += 1
            raise Cooldown(f"{ck} 429 쉼 {int(_cool[ck] - t)}초 남음")
        slot = max(t, _next.get(h, 0.0))
        _next[h] = slot + interval_for(h)
        st["n"] += 1
    d = slot - t
    if d > 0:
        sleep(d)


def note_error(url: str, err, now=time.time):
    code = getattr(err, "code", None)
    msg = str(err or "")
    ratelike = code == 429 or "429" in msg or "Too Many" in msg or "rate limit" in msg.lower()
    if ratelike:
        h = host_of(url)
        wait = COOLDOWN_SEC
        try:
            hdr = getattr(err, "headers", None)
            rs = float(hdr.get("x-ratelimit-reset")) if hdr is not None and hdr.get("x-ratelimit-reset") else 0.0
            if rs > 0:
                wait = min(3600.0, max(COOLDOWN_SEC, rs / 1000.0 + 5))
        except (TypeError, ValueError, AttributeError):
            pass
        ck = cool_key(url)
        with _lock:
            _cool[ck] = max(_cool.get(ck, 0.0), now() + wait)
            _stats.setdefault(h, {"n": 0, "rl": 0, "skip": 0})["rl"] += 1
    return ratelike


def cool_left(url: str) -> float:
    with _lock:
        return max(0.0, _cool.get(cool_key(url), 0.0) - time.time())


def stats() -> dict:
    with _lock:
        t = time.time()
        return {h: dict(v, cool=max([0] + [int(c - t) for k, c in _cool.items() if k == h or k.startswith(h + ":")]))
                for h, v in _stats.items()}


def _reset():
    with _lock:
        _next.clear(); _cool.clear(); _stats.clear()
