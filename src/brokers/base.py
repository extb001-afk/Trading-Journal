"""Broker adapter base class and safe HTTP helper (read-only, UNVERIFIED)."""
from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

UNVERIFIED = "미검증 — 공개 문서만 보고 작성, 실제 계정으로 시험 안 함(완벽하지 않음)"
UA = "tj-bot/0.1 (personal trade journal; read-only holdings)"


ERR_BODY = "증권사 오류 응답 — 응답 내용은 보안상 표시 안 함"


class BrokerError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def default_http(method: str, url: str, headers: dict | None = None, body=None, timeout: float = 15.0, verify: bool = True):
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" and u.hostname not in ("localhost", "127.0.0.1"):
        raise BrokerError("https 주소만 허용")
    data = None
    hd = {"User-Agent": UA, "Accept": "application/json"}
    hd.update(headers or {})
    if isinstance(body, (dict, list)):
        data = json.dumps(body).encode()
        hd.setdefault("Content-Type", "application/json; charset=utf-8")
    elif isinstance(body, str):
        data = body.encode()
    ctx = None
    if u.scheme == "https" and not verify:
        if u.hostname not in ("localhost", "127.0.0.1"):
            raise BrokerError("인증서 검사 끄기는 localhost 에서만")
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, data=data, method=method, headers=hd)
    opener = urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(context=ctx))
    try:
        with opener.open(req, timeout=timeout) as r:
            raw = r.read(4 * 1024 * 1024)
            st, rh = r.status, {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        raw = e.read(256 * 1024) if hasattr(e, "read") else b""
        st, rh = e.code, {k.lower(): v for k, v in (e.headers or {}).items()}
    except Exception as e:
        raise BrokerError("증권사 서버에 연결하지 못했어요(%s)" % type(e).__name__) from None
    try:
        j = json.loads(raw.decode("utf-8")) if raw else None
    except (ValueError, UnicodeDecodeError):
        j = None
    return st, j, rh


def fnum(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        s = str(v).replace(",", "").strip()
        if not s:
            return None
        neg = s.startswith("-")
        s = s.lstrip("+-").lstrip("0") or "0"
        return -float(s) if neg else float(s)
    except ValueError:
        return None


def redact(text, cfg: dict) -> str:
    t = str(text or "")
    vals = []

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)
        elif isinstance(o, str) and len(o) >= 4:
            vals.append(o)
    walk(cfg or {})
    for v in sorted(set(vals), key=len, reverse=True):
        t = t.replace(v, "***")
        if "-" in v:
            t = t.replace(v.replace("-", ""), "***")
    return t[:300]


class Adapter:
    KEY = ""
    NAME = ""
    DOCS: tuple = ()
    REQUIRED: tuple = ()
    OPTIONAL: tuple = ()
    NOTE = UNVERIFIED
    _tokens: dict = {}

    def __init__(self, cfg: dict, http=None, now=None):
        self.cfg = cfg or {}
        self.http = http or default_http
        self.now = now or time.time

    def req(self, method, url, headers=None, body=None, verify=True, ok=(200,)):
        st, j, rh = self.http(method, url, headers or {}, body, 15.0, verify)
        if st not in ok:
            kind = ("인증 실패" if st in (401, 403) else "요청 한도" if st == 429 else "리다이렉트 거부" if 300 <= st < 400
                    else "증권사 서버 오류" if st >= 500 else "요청 거부")
            raise BrokerError("HTTP %s %s(%s)" % (st, kind, ERR_BODY))
        if not isinstance(j, (dict, list)):
            raise BrokerError("증권사 응답 형식 오류(JSON 아님) — 기존 항목 유지")
        return j, rh

    def token_cache_key(self, *parts) -> str:
        import hashlib
        return self.KEY + ":" + hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:16]

    def cached_token(self, ck):
        t = Adapter._tokens.get(ck)
        if t and t[1] - 60 > self.now():
            return t[0]
        return None

    def keep_token(self, ck, tok, ttl_sec):
        Adapter._tokens[ck] = (tok, self.now() + max(60, float(ttl_sec or 0)))

    @staticmethod
    def need(v, typ, what):
        if not isinstance(v, typ):
            raise BrokerError("증권사 응답 형식 오류(%s) — 기존 항목 유지" % what)
        return v

    def need_list(self, parent, key, what):
        p = self.need(parent, dict, what)
        if key not in p or p[key] is None:
            raise BrokerError("증권사 응답에 %s 블록(%s)이 없어요 — 기존 항목 유지" % (what, key))
        o = p[key]
        if isinstance(o, dict):
            o = [o]
        return [x for x in self.need(o, list, what) if isinstance(x, dict)]

    def incomplete(self):
        raise BrokerError("연속 조회 상한(%d쪽)에서 다음 쪽이 남았어요 — 불완전한 보유 목록이라 반영하지 않았어요" % self.MAX_PAGES)

    def fetch(self) -> dict:
        raise NotImplementedError
