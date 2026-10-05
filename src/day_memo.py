"""Per-day, per-coin trade rationale memos."""
from __future__ import annotations

import json
import os
import re
import threading
import time
import unicodedata
from datetime import datetime

import common

VERSION = 1
MEMO_MAX = 500
SYM_MAX = 40
ENTRIES_MAX = 3000
WRITE_MAX_BYTES = 6 * 1024 * 1024
FILE_MAX_BYTES = 8 * 1024 * 1024
DATE_RE = re.compile(r"20\d\d-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])")
_SYM_BAD = re.compile(r"[\s|<>\"'`\\\x00-\x1f\x7f\u00ad\u200b-\u200f\u2028-\u202e\u2060-\u206f\ufeff\ue000-\uf8ff]")
_MEMO_BAD = re.compile(r"[\x00-\x1f\x7f\u2028\u2029\u202a-\u202e\u2066-\u2069\ufeff\ue000-\uf8ff]")


def default_path() -> str:
    return os.path.join(common.STATE_DIR, "day_memos.json")


def norm_date(d):
    if not isinstance(d, str) or not DATE_RE.fullmatch(d):
        return None
    try:
        return d if datetime.strptime(d, "%Y-%m-%d").strftime("%Y-%m-%d") == d else None
    except ValueError:
        return None


def norm_sym(s):
    if not isinstance(s, str):
        return None
    s = unicodedata.normalize("NFC", s.strip()).upper()
    if not (1 <= len(s) <= SYM_MAX) or _SYM_BAD.search(s):
        return None
    return s


def norm_memo(m):
    if not isinstance(m, str):
        return None, "memo 는 문자열"
    m = unicodedata.normalize("NFC", m.strip())
    if len(m) > MEMO_MAX:
        return None, f"memo 는 {MEMO_MAX}자 이하"
    if _MEMO_BAD.search(m):
        return None, "memo 에 쓸 수 없는 글자(줄바꿈·제어 문자 등)"
    return m, None


def key(date, sym) -> str:
    return f"{date}|{sym}"


def canon_map(syms) -> dict:
    syms = {s for s in syms if s}
    out = {}
    for s in syms:
        b = s[1:] if s.startswith("$") and len(s) > 1 else s
        if b != s and b in syms:
            out[s] = b
            continue
        m = re.match(r"^(.*[A-Za-z])\d$", b)
        if m and m.group(1) in syms and m.group(1) != s:
            out[s] = m.group(1)
    return out


class Corrupt(Exception):
    pass


class Full(Exception):
    pass


class TooBig(Full):
    pass


class Store:
    def __init__(self, path=None):
        self._path = path
        self.mu = threading.Lock()

    @property
    def path(self) -> str:
        return self._path or default_path()

    def read(self):
        p = self.path
        try:
            st = os.stat(p)
        except FileNotFoundError:
            return {}, None
        except OSError as e:
            return {}, f"읽기 실패({type(e).__name__})"
        if st.st_size > FILE_MAX_BYTES:
            return {}, "파일이 너무 큼"
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return {}, "JSON 손상"
        if not isinstance(d, dict) or d.get("v") != VERSION:
            return {}, "모르는 형식·버전"
        mm = d.get("memos")
        if not isinstance(mm, dict):
            return {}, "형식 이상(memos)"
        out = {}
        for k, v in mm.items():
            if not isinstance(k, str) or "|" not in k or not isinstance(v, dict):
                return {}, "형식 이상(항목)"
            d9, s9 = k.split("|", 1)
            if norm_date(d9) != d9 or norm_sym(s9) != s9:
                return {}, "형식 이상(키)"
            m9, e9 = norm_memo(v.get("memo"))
            at9 = v.get("at")
            if e9 or not m9 or type(at9) is not int or at9 < 0:
                return {}, "형식 이상(값)"
            out[k] = {"memo": m9, "at": at9}
        return out, None

    def for_date(self, date) -> dict:
        mm, _e = self.read()
        pre = f"{date}|"
        return {k[len(pre):]: v["memo"] for k, v in mm.items() if k.startswith(pre)}

    def get(self, date, sym):
        mm, _e = self.read()
        v = mm.get(key(date, sym))
        return v["memo"] if v else None

    def put(self, date, sym, memo, now=None):
        with self.mu:
            mm, err = self.read()
            if err:
                raise Corrupt(err)
            k = key(date, sym)
            if memo:
                if k not in mm and len(mm) >= ENTRIES_MAX:
                    raise Full(f"메모는 {ENTRIES_MAX}개까지")
                rec = {"memo": memo, "at": int(now if now is not None else time.time())}
                mm[k] = rec
            else:
                rec = None
                if k not in mm:
                    return None
                mm.pop(k, None)
            doc = {"v": VERSION, "memos": dict(sorted(mm.items()))}
            size = len(json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            if size > WRITE_MAX_BYTES:
                raise TooBig(f"근거 메모 파일 용량 한도({WRITE_MAX_BYTES // (1024 * 1024)}MB) — 옛 메모를 줄이거나 지운 뒤 다시")
            common.atomic_write_json(self.path, doc)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
            return rec
