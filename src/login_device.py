from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import stat
import threading
import time
from typing import Optional, Tuple

import fsio

__all__ = ["COOKIE", "MAX_DEVICES", "ABS_DAYS", "IDLE_DAYS", "DeviceStore", "tid_of"]

log = logging.getLogger("tj-web")

COOKIE = "tj_device"
MAX_DEVICES = 20
ABS_DAYS = 365
IDLE_DAYS = 90
SEEN_SAVE_SEC = 600
_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]{43}")


def tid_of(tok: str) -> str:
    return hashlib.sha256(tok.encode("ascii")).hexdigest()


def _sig(path):
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size, st.st_mode)


def _alive(ent, now) -> bool:
    return now < ent["e"] and now - ent["s"] <= IDLE_DAYS * 86400


def _clock(now) -> float:
    return time.time() if now is None else now


class DeviceStore:

    def __init__(self, path: str):
        self.path = path
        self.lock = threading.RLock()
        self._sig = False
        self._d = {}
        self._saved = 0.0

    def _load(self) -> dict:
        sig = _sig(self.path)
        if sig != self._sig:
            d = {}
            if sig is not None:
                try:
                    if os.stat(self.path).st_mode & (stat.S_IRWXG | stat.S_IRWXO):
                        os.chmod(self.path, 0o600)
                    with open(self.path, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                    d = {k: v for k, v in raw.items() if isinstance(k, str) and len(k) == 64 and isinstance(v, dict)
                         and all(type(v.get(x)) is int for x in ("c", "s", "e")) and all(isinstance(v.get(x), str) for x in ("pg", "sg"))
                         } if isinstance(raw, dict) else {}
                except (OSError, ValueError):
                    log.warning("state/auth_devices.json 을 읽지 못함 — 등록 기기 전부 무효(다음 로그인 때 다시 등록)")
                    d = {}
                sig = _sig(self.path)
            self._sig, self._d = sig, d
        return self._d

    def _save(self, now) -> None:
        try:
            fsio.atomic_write_text(self.path, json.dumps(self._d, separators=(",", ":")), mode=0o600)
        except OSError:
            self._sig = False
            raise
        self._sig, self._saved = _sig(self.path), now

    def _valid(self, tid, pg, sg, now) -> bool:
        d = self._load()
        ent = d.get(tid)
        if ent is None or not pg or not sg or ent["pg"] != pg or ent["sg"] != sg:
            return False
        if not _alive(ent, now):
            d.pop(tid, None)
            try:
                self._save(now)
            except OSError as e:
                log.warning("만료 기기 정리 저장 실패: %s", type(e).__name__)
            return False
        return True

    def issue(self, pg: str, sg: str, now: Optional[float] = None) -> Tuple[str, int]:
        if not pg or not sg:
            raise ValueError("세대 없음")
        tok = secrets.token_urlsafe(32)
        now = int(_clock(now))
        with self.lock:
            d = self._load()
            for k in [k for k, v in d.items() if not _alive(v, now) or v["pg"] != pg or v["sg"] != sg]:
                d.pop(k, None)
            while len(d) >= MAX_DEVICES:
                d.pop(min(d, key=lambda k: (d[k]["s"], d[k]["c"])), None)
            d[tid_of(tok)] = {"c": now, "s": now, "pg": pg, "sg": sg, "e": now + ABS_DAYS * 86400}
            self._save(now)
        return tok, ABS_DAYS * 86400

    def check(self, tok: object, pg: str, sg: Optional[str], now: Optional[float] = None) -> Optional[str]:
        if not isinstance(tok, str) or not _TOKEN_RE.fullmatch(tok):
            return None
        tid = tid_of(tok)
        with self.lock:
            return tid if self._valid(tid, pg, sg, _clock(now)) else None

    def touch(self, tid: str, pg: str, sg: Optional[str], now: Optional[float] = None) -> bool:
        now = _clock(now)
        with self.lock:
            if not self._valid(tid, pg, sg, now):
                return False
            ent = self._d[tid]
            if now - ent["s"] >= 60:
                ent["s"] = int(now)
                if now - self._saved >= SEEN_SAVE_SEC:
                    try:
                        self._save(now)
                    except OSError as e:
                        log.warning("기기 사용 시각 저장 실패: %s", type(e).__name__)
            return True

    def revoke_all(self, keep: Optional[str] = None) -> int:
        with self.lock:
            d = self._load()
            ks = [k for k in d if k != keep]
            for k in ks:
                d.pop(k, None)
            if ks or self._sig is not None:
                self._save(time.time())
            return len(ks)
