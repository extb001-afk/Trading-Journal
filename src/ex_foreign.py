"""Collectors for global exchanges (Binance, Bybit, OKX, KuCoin, Gate)."""
from __future__ import annotations

import base64
import email.utils
import functools
import hashlib
import hmac
import json
import logging
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid as uuidlib
from decimal import Decimal, InvalidOperation

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
if __name__ == "__main__":
    common.cpu_reserve_apply()
import unit_beat
import bf_engine
import calendar
import depaddr
from inbox import SegmentWriter
try:
    import fut_rcpt
except Exception:
    fut_rcpt = None

log = logging.getLogger("tj-exf")
_exf_fmt = logging.Formatter("%(asctime)s %(levelname)s [tj-exf] %(message)s")
_exf_out = logging.StreamHandler(sys.stdout)
_exf_out.setLevel(logging.INFO)
_exf_out.addFilter(lambda r: r.levelno < logging.WARNING)
_exf_out.setFormatter(_exf_fmt)
_exf_err = logging.StreamHandler(sys.stderr)
_exf_err.setLevel(logging.WARNING)
_exf_err.setFormatter(_exf_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_exf_out, _exf_err])
common.add_secret_filter([_exf_out, _exf_err])

POLL_SEC = 600
PACE = 0.35
STATE_PATH = os.path.join(common.STATE_DIR, "exf_state.json")
_quiet_n = {}
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
DAY = 86400


def _env() -> dict:
    return common.read_env_file()


def _xm(v) -> str:
    return common.redact_secret_text("" if v is None else str(v))


HTTP_MAX_BYTES = 32 * 1024 * 1024
HTTP_MAX_BYTES_PATH = {"/api/v3/exchangeInfo": 64 * 1024 * 1024}
ERR_BODY_MAX = 64 * 1024


class ResponseTooLarge(RuntimeError):
    pass


def _read_capped(r, cap: int, what: str = "") -> bytes:
    raw = r.read(cap + 1)
    if len(raw) > cap:
        raise ResponseTooLarge(f"{what} 응답 크기 초과(>{cap // 1048576}MB) — 이 요청 실패")
    return raw


def _err_body(e, n: int = ERR_BODY_MAX) -> str:
    d9 = getattr(e, "__dict__", None)
    c9 = d9.get("_tj_body") if isinstance(d9, dict) else None
    if isinstance(c9, str):
        return c9[:n]
    try:
        s9 = e.read(ERR_BODY_MAX).decode("utf-8", "replace") if getattr(e, "fp", None) else ""
    except Exception:
        s9 = ""
    if isinstance(d9, dict):
        d9["_tj_body"] = s9
    return s9[:n]


class RateLimited(RuntimeError):

    def __init__(self, msg, code=429):
        super().__init__(msg)
        self.code = code


class SignatureExpired(RuntimeError):
    pass


_BN_W_API = {"/api/v3/myTrades": 20, "/api/v3/account": 20, "/api/v3/exchangeInfo": 20, "/api/v3/openOrders": 80,
             "/api/v3/time": 1}
_BN_W_SAPI = {"/sapi/v1/margin/myTrades": 10, "/sapi/v1/margin/account": 10, "/sapi/v1/margin/isolated/account": 10,
              "/sapi/v1/capital/withdraw/history": 10, "/sapi/v1/simple-earn/flexible/position": 150,
              "/sapi/v1/simple-earn/locked/position": 150, "/sapi/v2/loan/flexible/ongoing/orders": 300,
              "/sapi/v1/margin/tradeCoeff": 10, "/sapi/v1/margin/crossMarginData": 1,
              "/sapi/v2/loan/flexible/collateral/data": 400, "/sapi/v2/loan/flexible/loanable/data": 400}
_BN_W_UID = {"/sapi/v1/capital/withdraw/history": 18000, "/sapi/v1/convert/tradeFlow": 3000}
_BN_W_FAPI = {"/fapi/v1/income": 30, "/fapi/v2/account": 5, "/fapi/v2/positionRisk": 5, "/fapi/v2/balance": 5,
              "/fapi/v1/userTrades": 5}
_KC_W = {"/api/v1/accounts": 5, "/api/v1/withdrawals": 20, "/api/v1/deposits": 5, "/api/v1/fills": 10,
         "/api/v1/hf/fills": 2, "/api/v1/hf/accounts/ledgers": 2, "/api/v1/timestamp": 3,
         "/api/v3/margin/accounts": 15, "/api/v1/convert/order/history": 5,
         "/api/v3/isolated/accounts": 15, "/api/v1/margin/config": 25, "/api/v1/isolated/symbols": 3,
         "/api/v3/margin/borrowRate": 5}
_KC_MGMT = ("/api/v1/accounts", "/api/v1/withdrawals", "/api/v1/deposits")
GOV_BUCKETS = (
    ("bn_api", "api.binance.com", lambda p: p.startswith("/api/"), 60, 3000, lambda p: _BN_W_API.get(p, 20)),
    ("bn_sapi", "api.binance.com", lambda p: p.startswith("/sapi/"), 60, 6000, lambda p: _BN_W_SAPI.get(p, 1)),
    ("bn_uid", "api.binance.com", lambda p: p in _BN_W_UID, 60, 90000, lambda p: _BN_W_UID.get(p, 0)),
    ("bn_fapi", "fapi.binance.com", lambda p: True, 60, 1200, lambda p: _BN_W_FAPI.get(p, 5)),
    ("bybit_ip", "api.bybit.com", lambda p: True, 5, 300, lambda p: 1),
    ("bybit_asset", "api.bybit.com", lambda p: p.startswith("/v5/asset/"), 60, 50, lambda p: 1),
    ("okx_path", "www.okx.com", None, 2, 2, lambda p: 1),
    ("kc_mgmt", "api.kucoin.com", lambda p: p in _KC_MGMT, 30, 1000, lambda p: _KC_W.get(p, 5)),
    ("kc_spot", "api.kucoin.com", lambda p: p not in _KC_MGMT, 30, 2000, lambda p: _KC_W.get(p, 10)),
    ("gate", "api.gateio.ws", lambda p: True, 10, 100, lambda p: 1),
    ("bithumb", "api.bithumb.com", lambda p: True, 1, 5, lambda p: 1),
    ("bn_dapi", "dapi.binance.com", lambda p: True, 60, 1200, lambda p: {"/dapi/v1/positionRisk": 1}.get(p, 5)),
    ("kc_fut", "api-futures.kucoin.com", lambda p: True, 30, 1000, lambda p: {"/api/v1/positions": 2}.get(p, 5)),
)
GOV_BN_HDR = {"bn_api": ("x-mbx-used-weight-1m", 3000), "bn_sapi": ("x-sapi-used-ip-weight-1m", 6000), "bn_dapi": ("x-mbx-used-weight-1m", 1200),
              "bn_uid": ("x-sapi-used-uid-weight-1m", 90000), "bn_fapi": ("x-mbx-used-weight-1m", 1200)}
GOV_MAX_WAIT = 65.0
_GOV_LOCK = threading.Lock()
_GOV_Q = {}
_GOV_HOLD = {}
_HTTP_TL = threading.local()


def _gov_route(url: str):
    try:
        u = urllib.parse.urlsplit(url)
        return (u.hostname or "").lower(), u.path or "/"
    except ValueError:
        return "", "/"


def _gov_buckets(host: str, path: str):
    out = []
    for name, h9, match, win, budget, wfn in GOV_BUCKETS:
        if h9 != host:
            continue
        if match is None:
            key = f"{name}:{path}"
        elif match(path):
            key = name
        else:
            continue
        w = int(wfn(path) or 0)
        if w > 0:
            out.append((key, name, win, budget, w))
    return out


def _gov_wait_for(key: str, win: float, budget: int, w: int, now: float) -> float:
    q = _GOV_Q.setdefault(key, [])
    while q and q[0][0] <= now - win:
        q.pop(0)
    wait = max(0.0, float(_GOV_HOLD.get(key, 0)) - now)
    used = sum(x[1] for x in q)
    if used + w > budget:
        need = used + w - budget
        for t9, w9 in q:
            need -= w9
            if need <= 0:
                wait = max(wait, t9 + win - now + 0.01)
                break
        else:
            wait = max(wait, win)
    return wait


def _gov_admit(host: str, path: str) -> None:
    bks = _gov_buckets(host, path)
    if not bks:
        return
    with _GOV_LOCK:
        now = time.time()
        wait = max(_gov_wait_for(k, win, b, w, now) for k, _n, win, b, w in bks)
    if wait > 0:
        time.sleep(min(GOV_MAX_WAIT, wait))
    with _GOV_LOCK:
        now = time.time()
        for k, _n, win, b, w in bks:
            _GOV_Q.setdefault(k, []).append((now, w))


def _gov_headers(host: str, path: str, hdrs) -> None:
    if not hdrs or not host.endswith("binance.com"):
        return
    for k, name, _win, _b, _w in _gov_buckets(host, path):
        hk = GOV_BN_HDR.get(name)
        if not hk:
            continue
        try:
            used = int(str(hdrs.get(hk[0]) or hdrs.get(hk[0].upper()) or "").strip() or -1)
        except (TypeError, ValueError, AttributeError):
            continue
        if used >= hk[1]:
            now = time.time()
            with _GOV_LOCK:
                _GOV_HOLD[k] = max(float(_GOV_HOLD.get(k, 0)), (int(now // 60) + 1) * 60 + 1.0)
            log.info("%s 사용량 %d (예산 %d = 공개 한도의 50%%) — 다음 분까지 보류", name, used, hk[1])


def _rl_key(host: str) -> str:
    return host


def _rl_check(host: str) -> None:
    until = float(_RL_OFF.get(_rl_key(host), 0) or 0)
    now = time.time()
    if now < until:
        raise RateLimited(f"{host} 레이트 제한 백오프 중 — {int(until - now)}초 남음(호출 안 함)")


def _rl_hit(host: str, e) -> float:
    ra = None
    try:
        ra = float(str((e.headers or {}).get("Retry-After") or "").strip())
    except (TypeError, ValueError, AttributeError):
        ra = None
    if ra is None or ra != ra or ra <= 0:
        ra = 120.0 if e.code == 418 else 60.0
    ra = min(ra, 3 * DAY)
    _RL_OFF[_rl_key(host)] = time.time() + ra
    log.warning("%s HTTP %s(레이트 한도%s) — %d초 동안 이 호스트 호출 중단", host, e.code, "·IP 차단" if e.code == 418 else "", int(ra))
    return ra


def _gov_prepare(host: str, path: str) -> None:
    if http_json is not _HTTP_JSON_IMPL:
        return
    _rl_check(host)
    _gov_admit(host, path)
    _HTTP_TL.admitted = (host, path)


CLOCK_PATH_NAME = "exf_clock.json"
CLOCK_TTL = 3600
CLOCK_ERR_GAP = 60
CLOCK_FAIL_GAP = 600
CLOCK_MAX_OFF_MS = 86400 * 1000
CLOCK_WARN_MS = 2000
CLOCK_HOST = {"api.binance.com": "binance", "fapi.binance.com": "binance", "dapi.binance.com": "binance",
              "api.bybit.com": "bybit", "www.okx.com": "okx", "api.kucoin.com": "kucoin",
              "api-futures.kucoin.com": "kucoin", "api.gateio.ws": "gate", "api.bithumb.com": "bithumb"}
CLOCK_SRC = {"binance": "https://api.binance.com/api/v3/time", "bybit": "https://api.bybit.com/v5/market/time",
             "okx": "https://www.okx.com/api/v5/public/time", "kucoin": "https://api.kucoin.com/api/v1/timestamp",
             "gate": "https://api.gateio.ws/api/v4/spot/time", "bithumb": "https://api.bithumb.com/v1/ticker?markets=KRW-BTC"}
_CLOCK_ON = [False]
_CLOCK = {}
_CLOCK_LOCK = threading.Lock()


def _clock_parse(ex: str, d, date_hdr):
    try:
        if ex == "binance":
            return int(d["serverTime"])
        if ex == "bybit":
            if d.get("time"):
                return int(d["time"])
            r9 = d.get("result") or {}
            return int(r9["timeNano"]) // 1000000 if r9.get("timeNano") else int(r9["timeSecond"]) * 1000
        if ex == "okx":
            return int(d["data"][0]["ts"])
        if ex == "kucoin":
            return int(d["data"]) if str(d.get("code")) == "200000" else None
        if ex == "gate":
            return int(d["server_time"])
        if ex == "bithumb":
            return int(email.utils.parsedate_to_datetime(date_hdr).timestamp() * 1000) + 500 if date_hdr else None
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        return None
    return None


def _clock_fetch(ex: str):
    url = CLOCK_SRC.get(ex)
    if not url:
        return None
    host, path = _gov_route(url)
    try:
        _rl_check(host)
    except RateLimited:
        return None
    _gov_admit(host, path)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = _read_capped(r, 256 * 1024, host + path)
            dh = r.headers.get("Date") if r.headers is not None else None
        t1 = time.time()
        d = json.loads(raw.decode("utf-8")) if raw else None
    except urllib.error.HTTPError as e:
        if e.code in (429, 418):
            _rl_hit(host, e)
        log.warning("%s 서버 시각 조회 실패: HTTP %s", ex, e.code)
        return None
    except Exception as e:
        log.warning("%s 서버 시각 조회 실패: %s", ex, _xm(repr(e))[:120])
        return None
    srv = _clock_parse(ex, d if isinstance(d, dict) else {}, dh)
    if not srv:
        log.warning("%s 서버 시각 응답 형식 오류 — 보정은 직전 값 그대로", ex)
        return None
    off = srv - (t0 + t1) / 2.0 * 1000.0
    if abs(off) > CLOCK_MAX_OFF_MS:
        log.warning("%s 서버 시각 차이 %.0f초 — 응답 이상으로 보고 버림", ex, off / 1000.0)
        return None
    return int(round(off)), int((t1 - t0) * 1000)


def _clock_save() -> None:
    if not _CLOCK_ON[0]:
        return
    with _CLOCK_LOCK:
        doc = {"v": 1, "ex": {k: {k2: v[k2] for k2 in ("off", "at", "rtt") if k2 in v} for k, v in _CLOCK.items() if "at" in v}}
    try:
        common.atomic_write_json(os.path.join(common.STATE_DIR, CLOCK_PATH_NAME), doc)
    except Exception as e:
        log.warning("서버 시각 차이 기록 실패: %s", e)


def _clock_restore() -> int:
    p9 = os.path.join(common.STATE_DIR, CLOCK_PATH_NAME)
    try:
        d = common.read_json(p9, {}) if os.path.exists(p9) else {}
    except SystemExit:
        d = {}
    n = 0
    for ex, v in ((d.get("ex") or {}).items() if isinstance(d, dict) and isinstance(d.get("ex"), dict) else ()):
        try:
            off9, at9 = int(v["off"]), float(v["at"])
        except (KeyError, TypeError, ValueError):
            continue
        if ex in CLOCK_SRC and abs(off9) <= CLOCK_MAX_OFF_MS:
            _CLOCK[ex] = {"off": off9, "at": at9, "rtt": int(v.get("rtt") or 0)}
            n += 1
    _CLOCK_ON[0] = True
    return n


def _clock_sync(ex: str, why: str, gap: float) -> bool:
    if http_json is not _HTTP_JSON_IMPL:
        return False
    now = time.time()
    with _CLOCK_LOCK:
        c = _CLOCK.setdefault(ex, {})
        if now - float(c.get("try") or 0) < gap:
            return False
        c["try"] = now
        old = c.get("off")
    got = _clock_fetch(ex)
    if got is None:
        return False
    off, rtt = got
    with _CLOCK_LOCK:
        c = _CLOCK.setdefault(ex, {})
        c.update(off=off, at=time.time(), rtt=rtt)
    _clock_save()
    if abs(off) >= CLOCK_WARN_MS and (old is None or abs(int(old) - off) >= 1000 or why != "1시간마다"):
        log.warning("%s 서버 시각과 이 서버 시계가 %+.1f초 다름(%s) — 서명 시각을 거래소 시각에 맞춰 보냄(서버 시간 동기화 확인 권장)",
                    ex, off / 1000.0, why)
    elif why != "1시간마다":
        log.info("%s 서버 시각 다시 잼(%s): 차이 %+d ms · 왕복 %d ms", ex, why, off, rtt)
    return True


def _srv_ms(host: str) -> int:
    ex = CLOCK_HOST.get(host)
    off = 0
    if ex and _CLOCK_ON[0]:
        c = _CLOCK.get(ex) or {}
        if time.time() - float(c.get("at") or 0) >= CLOCK_TTL:
            _clock_sync(ex, "1시간마다", CLOCK_FAIL_GAP)
            c = _CLOCK.get(ex) or {}
        off = int(c.get("off") or 0)
    return int(time.time() * 1000) + off


def _okx_ts(ms: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ms // 1000)) + f".{ms % 1000:03d}Z"


_CLOCK_ERR = {"binance": lambda d: str(d.get("code")) == "-1021",
              "bybit": lambda d: str(d.get("retCode")) == "10002",
              "okx": lambda d: str(d.get("code")) == "50102",
              "kucoin": lambda d: str(d.get("code")) == "400002",
              "gate": lambda d: str(d.get("label")) == "REQUEST_EXPIRED"}


def _clock_seen(host: str, d=None, err=None) -> None:
    ex = CLOCK_HOST.get(host)
    if not ex or not _CLOCK_ON[0] or ex not in _CLOCK_ERR:
        return
    if err is not None:
        if getattr(err, "code", None) not in (400, 401, 403):
            return
        try:
            d = json.loads(_err_body(err) or "null")
        except ValueError:
            return
    if not isinstance(d, dict) or not _CLOCK_ERR[ex](d):
        return
    if _clock_sync(ex, "서명 시각 오류", CLOCK_ERR_GAP):
        _HTTP_TL.clock_hit = ex


def _clock_retry(fn):
    @functools.wraps(fn)
    def w(*a, **k):
        _HTTP_TL.clock_hit = None
        try:
            r = fn(*a, **k)
        except Exception:
            if not getattr(_HTTP_TL, "clock_hit", None):
                raise
            _HTTP_TL.clock_hit = None
            return fn(*a, **k)
        if getattr(_HTTP_TL, "clock_hit", None):
            _HTTP_TL.clock_hit = None
            return fn(*a, **k)
        return r
    return w


def http_json(url: str, headers: dict | None = None, data: bytes | None = None,
              method: str | None = None, timeout: int = 20):
    host, path = _gov_route(url)
    _rl_check(host)
    adm = getattr(_HTTP_TL, "admitted", None)
    _HTTP_TL.admitted = None
    if adm != (host, path):
        _gov_admit(host, path)
    h = {"User-Agent": UA, "Accept": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            try:
                _gov_headers(host, path, r.headers)
            except Exception:
                pass
            out9 = json.loads(_read_capped(r, HTTP_MAX_BYTES_PATH.get(path, HTTP_MAX_BYTES), host + path).decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (429, 418):
            ra = _rl_hit(host, e)
            raise RateLimited(f"{host} HTTP {e.code} — {int(ra)}초 백오프", e.code) from None
        _clock_seen(host, err=e)
        raise
    _clock_seen(host, out9)
    return out9


_HTTP_JSON_IMPL = http_json


def _iso(ms_or_s) -> str:
    try:
        v = float(ms_or_s)
    except (TypeError, ValueError):
        s = str(ms_or_s or "")
        if len(s) >= 19 and s[4] == "-" and ("+" not in s[10:] and "Z" not in s):
            return s[:10] + "T" + s[11:19] + "+00:00"
        return s
    if v > 10**12:
        v /= 1000.0
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(v)) + "+00:00"


DEST_FIELDS = ("address", "tag", "network")


def norm_row(ex: str, native_id: str, currency: str, amount, fee, txid, state: str,
             created, done, address=None, tag=None, network=None) -> dict:
    r = {"uuid": f"{ex}:{native_id}", "currency": str(currency or "").upper(),
         "amount": str(amount or "0"), "fee": str(fee or "0"),
         "txid": str(txid or ""), "state": state,
         "created_at": _iso(created), "done_at": _iso(done or created)}
    for k, v in (("address", address), ("tag", tag), ("network", network)):
        if v not in (None, "") and str(v).strip():
            r[k] = str(v).strip()
    return r


_BN_WD_FAIL = {1: "CANCELLED", 3: "REJECTED", 5: "FAILED"}
_BN_DEP_FAIL = {2: "REJECTED", 7: "FAILED"}
_BB_WD_FAIL = {"cancelbyuser": "CANCELLED", "reject": "REJECTED", "fail": "FAILED"}
_OKX_WD_FAIL = {"-2": "CANCELLED", "-1": "FAILED"}
_GATE_FAIL = {"CANCEL": "CANCELLED", "FAIL": "FAILED", "INVALID": "FAILED"}


def _int_or(v, d=-999):
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


def fetch_binance(env, t0: int, t1: int):
    key, sec = env["TJ_BINANCE_KEY"], env["TJ_BINANCE_SECRET"]
    out_w, out_d = [], []

    @_clock_retry
    def call(path, extra):
        _gov_prepare("api.binance.com", path)
        q = dict(extra)
        q["timestamp"] = _srv_ms("api.binance.com")
        q["recvWindow"] = 10000
        qs = urllib.parse.urlencode(q)
        sig = hmac.new(sec.encode(), qs.encode(), hashlib.sha256).hexdigest()
        return http_json(f"https://api.binance.com{path}?{qs}&signature={sig}",
                         {"X-MBX-APIKEY": key})

    def paged(path, s, e):
        out, off, prev = [], 0, None
        while True:
            rows = call(path, {"startTime": s * 1000, "endTime": e * 1000, "limit": 1000, "offset": off}) or []
            if not isinstance(rows, list):
                raise RuntimeError(f"binance {path} 응답 형식 오류 — 다음 주기 재시도")
            sig = tuple(json.dumps(r, sort_keys=True) for r in rows[:3])
            if off and rows and sig == prev:
                raise RuntimeError(f"binance {path} offset 미전진(같은 페이지 반복) — 다음 주기 재시도")
            prev = sig
            out.extend(rows)
            time.sleep(PACE)
            if len(rows) < 1000:
                return out
            off += 1000
            if off >= 100000:
                raise RuntimeError(f"binance {path} 창 하나에 10만 건 초과 — 다음 주기 재시도")

    s = t0
    while s < t1:
        e = min(s + 89 * DAY, t1)
        rows_w = paged("/sapi/v1/capital/withdraw/history", s, e)
        for row in rows_w:
            st = "DONE" if _int_or(row.get("status")) == 6 else _BN_WD_FAIL.get(_int_or(row.get("status")), "PENDING")
            out_w.append(norm_row("binance", row.get("id") or row.get("txId") or "",
                                  row.get("coin"), row.get("amount"),
                                  row.get("transactionFee"), row.get("txId"), st,
                                  row.get("applyTime"), row.get("completeTime"),
                                  row.get("address"), row.get("addressTag"), row.get("network")))
        rows_d = paged("/sapi/v1/capital/deposit/hisrec", s, e)
        for row in rows_d:
            st = "ACCEPTED" if _int_or(row.get("status")) in (1, 6) else _BN_DEP_FAIL.get(_int_or(row.get("status")), "PENDING")
            nid = row.get("id") or f"{row.get('coin')}:{row.get('txId')}"
            out_d.append(norm_row("binance", nid, row.get("coin"), row.get("amount"),
                                  0, row.get("txId"), st,
                                  row.get("insertTime"), row.get("insertTime"),
                                  network=row.get("network")))
        s = e
    return out_w, out_d


def fetch_bybit(env, t0: int, t1: int):
    key, sec = env["TJ_BYBIT_KEY"], env["TJ_BYBIT_SECRET"]
    out_w, out_d = [], []

    @_clock_retry
    def call(path, params):
        _gov_prepare("api.bybit.com", path)
        qs = urllib.parse.urlencode(params)
        ts = str(_srv_ms("api.bybit.com"))
        recv = "10000"
        sig = hmac.new(sec.encode(), (ts + key + recv + qs).encode(), hashlib.sha256).hexdigest()
        d = http_json(f"https://api.bybit.com{path}?{qs}",
                      {"X-BAPI-API-KEY": key, "X-BAPI-TIMESTAMP": ts,
                       "X-BAPI-RECV-WINDOW": recv, "X-BAPI-SIGN": sig})
        if d.get("retCode") != 0:
            raise RuntimeError(f"bybit {d.get('retCode')} {_xm(d.get('retMsg'))}")
        return d.get("result") or {}

    s = t0
    while s < t1:
        e = min(s + 29 * DAY, t1)
        srcs = [("/v5/asset/withdraw/query-record", "w"), ("/v5/asset/deposit/query-record", "d")]
        for path, bucket in srcs:
            cursor = ""
            seen_cursors = set()
            while True:
                p = {"startTime": s * 1000, "endTime": e * 1000, "limit": 50}
                if bucket == "w":
                    p["withdrawType"] = 2
                if cursor:
                    p["cursor"] = cursor
                res = call(path, p)
                rows = res.get("rows") or []
                for row in rows:
                    if bucket == "w":
                        st9 = str(row.get("status", "")).lower()
                        st = "DONE" if st9 == "success" else _BB_WD_FAIL.get(st9, "PENDING")
                        int9 = str(row.get("withdrawType")) == "1"
                        net9 = row.get("chain") or ("BYBIT_INTERNAL" if int9 else None)
                        r9 = norm_row("bybit", row.get("withdrawId"), row.get("coin"),
                                      row.get("amount"), row.get("withdrawFee"),
                                      row.get("txID"), st,
                                      row.get("createTime"), row.get("updateTime"),
                                      row.get("toAddress"), row.get("tag"), net9)
                        if int9:
                            r9["late"] = 1
                        out_w.append(r9)
                    else:
                        st = "ACCEPTED" if _int_or(row.get("status"), 0) == 3 else \
                            ("FAILED" if _int_or(row.get("status"), 0) == 4 else "PENDING")
                        nid = row.get("id") or f"{row.get('coin')}:{row.get('txID')}"
                        out_d.append(norm_row("bybit", nid, row.get("coin"), row.get("amount"),
                                              0, row.get("txID"), st,
                                              row.get("successAt"), row.get("successAt"),
                                              network=row.get("chain")))
                cursor = res.get("nextPageCursor") or ""
                if cursor and cursor in seen_cursors:
                    raise RuntimeError("bybit 입출금 페이지 커서 순환 — 다음 주기 재시도")
                seen_cursors.add(cursor)
                time.sleep(PACE)
                if not cursor or not rows:
                    break
        s = e
    return out_w, out_d


def _bybit_internal_rows(env, t0: int, t1: int) -> list:
    out = []
    s = int(t0)
    while s < t1:
        e = min(s + 29 * DAY, int(t1))
        cursor, seen_c = "", set()
        while True:
            p = {"startTime": s * 1000, "endTime": e * 1000, "limit": 50}
            if cursor:
                p["cursor"] = cursor
            res = _bybit_get(env, "/v5/asset/deposit/query-internal-record", p)
            rows = res.get("rows")
            if not isinstance(rows, list):
                raise RuntimeError("bybit internal-record rows 누락/형식 오류")
            for row in rows:
                if not isinstance(row, dict) or not row.get("id"):
                    continue
                sti = _int_or(row.get("status"), 0)
                st = "ACCEPTED" if sti == 2 else ("FAILED" if sti == 3 else "PENDING")
                out.append(norm_row("bybit", f"int:{row.get('id')}", row.get("coin"), row.get("amount"),
                                    0, row.get("txID"), st, row.get("createdTime"), row.get("createdTime"),
                                    network="BYBIT_INTERNAL"))
            cursor = str(res.get("nextPageCursor") or "")
            time.sleep(PACE)
            if not cursor or not rows:
                break
            if cursor in seen_c:
                raise RuntimeError("bybit internal-record 커서 순환")
            seen_c.add(cursor)
        s = e
    return out


BB_INT_DENY = ("retCode=10005", "retCode=10003", "retCode=10004", "retCode=10010")


def bybit_internal_pass(env: dict, state: dict, writer, now: int, window: int) -> str:
    need = FETCHERS.get("bybit", (None, ()))[1]
    if "bybit" not in FETCHERS or not all(env.get(k) for k in need) or "bybit" not in state:
        return "skip"
    st = state["bybit"]
    if not st.get("backfilled_until"):
        return "wait"
    if time.time() < float(_WD_OFF.get("bybit:internal", 0) or 0):
        return "cooldown"
    it = st.setdefault("int", {})
    lo_want = int(now - window)
    ext = st.get("ext") or {}
    if ext.get("wd_from"):
        lo_want = min(lo_want, int(ext["wd_from"]))
    tg9 = bf_engine.SINCE.target("bybit")
    if tg9:
        lo_want = min(lo_want, int(tg9))
    hist_done = bool(it.get("lo")) and int(it["lo"]) <= lo_want + 60
    t0 = max(lo_want, min(int(now - 7 * DAY), int(it.get("until") or lo_want))) if hist_done else lo_want
    try:
        rows = _bybit_internal_rows(env, t0, now)
    except Exception as e:
        msg = _xm(repr(e))[:200]
        if any(k in msg for k in _DENY_SIGS + BB_INT_DENY):
            _WD_OFF["bybit:internal"] = time.time() + DENY_COOL_SEC
            log.warning("bybit 내부 이체 입금 조회 권한 없음 — 6h 뒤 재시도(수집 하한 유지 · 권한이 생기면 빠진 구간부터): %s", msg[:120])
            return "denied"
        log.warning("bybit 내부 이체 입금 조회 실패(다음 주기): %s", msg[:140])
        return "error"
    seen, seen_txids, seen_dest = st.setdefault("seen", {}), st.setdefault("seen_txids", {}), st.setdefault("seen_dest", {})
    new_d = _rows_to_emit(rows, seen, seen_txids)
    for r in new_d:
        r["late"] = 1
    if new_d:
        _invalidate_balance_snapshot("bybit")
        lb9 = f"bybit:int:{int(now)}:{uuidlib.uuid4().hex[:10]}"
        nch9 = (len(new_d) + 499) // 500
        for k9, i in enumerate(range(0, len(new_d), 500)):
            writer.append(_late_tag({"v": 1, "kind": "ex_snapshot", "exchange": "bybit", "ts": int(now), "deposits": new_d[i:i + 500],
                                     "withdraws": [], "lb": lb9, "lbi": k9, "lbn": nch9}, "bybit", force=True))
        _mark_seen(new_d, seen, seen_txids, seen_dest, st.setdefault("pend_ts", {}))
    if not hist_done:
        it["lo"] = int(lo_want)
        log.info("bybit 내부 이체 입금 이력(%s~): %d건 · 신규 방출 %d", time.strftime("%Y-%m-%d", time.gmtime(lo_want)), len(rows), len(new_d))
    it["until"] = int(now)
    state["bybit"] = st
    common.atomic_write_json(STATE_PATH, state)
    return "ok"


def fetch_okx(env, t0: int, t1: int):
    key, sec, pph = env["TJ_OKX_KEY"], env["TJ_OKX_SECRET"], env["TJ_OKX_PASSPHRASE"]
    out_w, out_d = [], []

    @_clock_retry
    def call(path, params):
        _gov_prepare("www.okx.com", path)
        qs = urllib.parse.urlencode(params)
        full = path + ("?" + qs if qs else "")
        ts = _okx_ts(_srv_ms("www.okx.com"))
        sig = base64.b64encode(hmac.new(sec.encode(), (ts + "GET" + full).encode(),
                                        hashlib.sha256).digest()).decode()
        d = http_json("https://www.okx.com" + full,
                      {"OK-ACCESS-KEY": key, "OK-ACCESS-SIGN": sig,
                       "OK-ACCESS-TIMESTAMP": ts, "OK-ACCESS-PASSPHRASE": pph})
        if d.get("code") != "0":
            raise RuntimeError(f"okx {d.get('code')} {_xm(d.get('msg'))}")
        return d.get("data") or []

    for path, bucket in (("/api/v5/asset/withdrawal-history", "w"),
                         ("/api/v5/asset/deposit-history", "d")):
        after = ""
        got = set()
        while True:
            p = {"limit": 100}
            if after:
                p["after"] = after
            rows = call(path, p)
            if not rows:
                break
            n_new = 0
            for row in rows:
                ts_ms = int(row.get("ts") or 0)
                if bucket == "w":
                    st = "DONE" if str(row.get("state")) == "2" else _OKX_WD_FAIL.get(str(row.get("state")), "PENDING")
                    r9 = norm_row("okx", row.get("wdId"), row.get("ccy"),
                                  row.get("amt"), row.get("fee"), row.get("txId"),
                                  st, ts_ms, ts_ms, row.get("to"),
                                  row.get("tag") or row.get("memo") or row.get("pmtId"), row.get("chain"))
                else:
                    st = "ACCEPTED" if str(row.get("state")) == "2" else "PENDING"
                    nid = row.get("depId") or f"{row.get('ccy')}:{row.get('txId')}"
                    r9 = norm_row("okx", nid, row.get("ccy"), row.get("amt"),
                                  0, row.get("txId"), st, ts_ms, ts_ms, network=row.get("chain"))
                if r9["uuid"] in got:
                    continue
                got.add(r9["uuid"])
                n_new += 1
                (out_w if bucket == "w" else out_d).append(r9)
            oldest = min(int(r.get("ts") or 0) for r in rows)
            time.sleep(PACE)
            if oldest // 1000 <= t0 or len(rows) < 100:
                break
            if after and n_new == 0:
                raise RuntimeError("okx 입출금 페이지 시각 미전진 — 다음 주기 재시도")
            after = str(oldest + 1)
    return out_w, out_d


def fetch_kucoin(env, t0: int, t1: int):
    key, sec, pph = env["TJ_KUCOIN_KEY"], env["TJ_KUCOIN_SECRET"], env["TJ_KUCOIN_PASSPHRASE"]
    out_w, out_d = [], []

    @_clock_retry
    def call(path_with_qs):
        _gov_prepare("api.kucoin.com", path_with_qs.split("?", 1)[0])
        ts = str(_srv_ms("api.kucoin.com"))
        sig = base64.b64encode(hmac.new(sec.encode(), (ts + "GET" + path_with_qs).encode(),
                                        hashlib.sha256).digest()).decode()
        pph_sig = base64.b64encode(hmac.new(sec.encode(), pph.encode(),
                                            hashlib.sha256).digest()).decode()
        d = http_json("https://api.kucoin.com" + path_with_qs,
                      {"KC-API-KEY": key, "KC-API-SIGN": sig, "KC-API-TIMESTAMP": ts,
                       "KC-API-PASSPHRASE": pph_sig, "KC-API-KEY-VERSION": "2"})
        if d.get("code") != "200000":
            raise RuntimeError(f"kucoin {d.get('code')} {_xm(d.get('msg'))}")
        return d.get("data") or {}

    s = t0
    while s < t1:
        e = min(s + 7 * DAY, t1)
        for path, bucket in (("/api/v1/withdrawals", "w"), ("/api/v1/deposits", "d")):
            page = 1
            while True:
                qs = urllib.parse.urlencode({"startAt": s * 1000, "endAt": e * 1000,
                                             "pageSize": 50, "currentPage": page})
                data = call(f"{path}?{qs}")
                items = data.get("items") or []
                for row in items:
                    txid = str(row.get("walletTxId") or "").split("@")[0]
                    if bucket == "w":
                        st9 = str(row.get("status", "")).upper()
                        st = "DONE" if st9 == "SUCCESS" else ("FAILED" if st9 == "FAILURE" else "PENDING")
                        out_w.append(norm_row("kucoin", row.get("id"), row.get("currency"),
                                              row.get("amount"), row.get("fee"), txid, st,
                                              row.get("createdAt"), row.get("updatedAt"),
                                              row.get("address"), row.get("memo"), row.get("chain")))
                    else:
                        st9 = str(row.get("status", "")).upper()
                        st = "ACCEPTED" if st9 == "SUCCESS" else ("FAILED" if st9 == "FAILURE" else "PENDING")
                        nid = f"{row.get('currency')}:{txid}:{row.get('createdAt')}"
                        out_d.append(norm_row("kucoin", nid, row.get("currency"),
                                              row.get("amount"), 0, txid, st,
                                              row.get("createdAt"), row.get("updatedAt"), network=row.get("chain")))
                time.sleep(PACE)
                if page >= int(data.get("totalPage") or 1):
                    break
                page += 1
        s = e
    return out_w, out_d


_DEP_DENIED = set()


def _wd_window(st: dict, now: int, window: int) -> tuple:
    t0 = max(now - window, min(now - 7 * DAY, int(st.get("backfilled_until") or now - window)))
    hold = st.get("dep_hold")
    floor = now - window
    ew = (st.get("ext") or {}).get("wd_from") if isinstance(st.get("ext"), dict) else None
    if isinstance(ew, int) and ew < floor:
        floor = ew
    dt0 = max(floor, min(t0, int(hold))) if isinstance(hold, int) else t0
    return t0, dt0


DEP_HOLD_V = 1


def _dep_hold_migrate(ex: str, st: dict, now: int, window: int) -> bool:
    if ex != "gate" or st.get("dep_hold_v") == DEP_HOLD_V:
        return False
    floor = int(now - window)
    ew = (st.get("ext") or {}).get("wd_from") if isinstance(st.get("ext"), dict) else None
    if isinstance(ew, int) and ew < floor:
        floor = ew
    h = st.get("dep_hold")
    st["dep_hold"] = min(int(h), floor) if isinstance(h, int) else floor
    st["dep_hold_v"] = DEP_HOLD_V
    log.info("gate 입금 보류 표식 1회 이관 — 입금을 %s 부터 다시 확인(배포 전 권한 거부로 빠졌을 수 있는 입금 · late 흡수)",
             time.strftime("%Y-%m-%d", time.gmtime(st["dep_hold"])))
    return True


def _dep_hold_update(ex: str, st: dict, dep_t0: int):
    if ex in _DEP_DENIED:
        h = st.get("dep_hold")
        st["dep_hold"] = min(int(h), int(dep_t0)) if isinstance(h, int) else int(dep_t0)
    else:
        st.pop("dep_hold", None)


def fetch_gate(env, t0: int, t1: int, dep_t0: int = None):
    key, sec = env["TJ_GATE_KEY"], env["TJ_GATE_SECRET"]
    out_w, out_d = [], []
    _DEP_DENIED.discard("gate")

    @_clock_retry
    def call(path, params):
        _gov_prepare("api.gateio.ws", path)
        qs = urllib.parse.urlencode(params)
        ts = str(_srv_ms("api.gateio.ws") // 1000)
        body_hash = hashlib.sha512(b"").hexdigest()
        payload = f"GET\n{path}\n{qs}\n{body_hash}\n{ts}"
        sig = hmac.new(sec.encode(), payload.encode(), hashlib.sha512).hexdigest()
        return http_json(f"https://api.gateio.ws{path}?{qs}",
                         {"KEY": key, "Timestamp": ts, "SIGN": sig})

    dep_denied = False
    d0 = t0 if dep_t0 is None else min(int(dep_t0), int(t0))
    s = d0
    while s < t1:
        e = min(s + 29 * DAY, t1)
        for path, bucket in (("/api/v4/wallet/withdrawals", "w"),
                             ("/api/v4/wallet/deposits", "d")):
            if bucket == "d" and dep_denied:
                continue
            if bucket == "w" and e <= t0:
                continue
            try:
                _gate_range(call, path, bucket, max(s, t0) if bucket == "w" else s, e, out_w, out_d)
            except urllib.error.HTTPError as ge:
                if bucket == "d" and ge.code == 403:
                    dep_denied = True
                    _DEP_DENIED.add("gate")
                    log.warning("gate 입금 조회 권한 없음 — 출금만 수집 (Wallet 읽기 켜면 완성 · 입금은 그때 이 구간부터 다시)")
                    continue
                raise
        s = e
    if dep_t0 is not None and int(dep_t0) < int(t0) and not dep_denied:
        for r in out_d:
            r["late"] = 1
    return out_w, out_d


def _gate_range(call, path, bucket, s, e, out_w, out_d):
    offset = 0
    while True:
        rows = call(path, {"from": s, "to": e, "limit": 500, "offset": offset}) or []
        for row in rows:
            if bucket == "w":
                st = "DONE" if str(row.get("status", "")).upper() in ("DONE", "SUCCESS") \
                    else _GATE_FAIL.get(str(row.get("status", "")).upper(), "PENDING")
                out_w.append(norm_row("gate", row.get("id"), row.get("currency"),
                                      row.get("amount"), row.get("fee"), row.get("txid"),
                                      st, row.get("timestamp"), row.get("timestamp"),
                                      row.get("address"), row.get("memo"), row.get("chain")))
            else:
                st = "ACCEPTED" if str(row.get("status", "")).upper() in ("DONE", "SUCCESS") \
                    else _GATE_FAIL.get(str(row.get("status", "")).upper(), "PENDING")
                out_d.append(norm_row("gate", row.get("id"), row.get("currency"),
                                      row.get("amount"), 0, row.get("txid"), st,
                                      row.get("timestamp"), row.get("timestamp"), network=row.get("chain")))
        time.sleep(PACE)
        if len(rows) < 500:
            break
        offset += 500


def fetch_bithumb(env, t0: int, t1: int):
    key, sec = env["TJ_BITHUMB_KEY"], env["TJ_BITHUMB_SECRET"]
    out_w, out_d = [], []

    def call(path, params):
        _gov_prepare("api.bithumb.com", path)
        payload = {"access_key": key, "nonce": str(uuidlib.uuid4()),
                   "timestamp": _srv_ms("api.bithumb.com")}
        if params:
            raw_qs = "&".join(f"{k}={v}" for k, v in params.items())
            payload["query_hash"] = hashlib.sha512(raw_qs.encode()).hexdigest()
            payload["query_hash_alg"] = "SHA512"

        def b64u(b):
            return base64.urlsafe_b64encode(b).rstrip(b"=")
        h = b64u(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        p = b64u(json.dumps(payload).encode())
        sgn = b64u(hmac.new(sec.encode(), h + b"." + p, hashlib.sha256).digest())
        tok = (h + b"." + p + b"." + sgn).decode()
        qs = urllib.parse.urlencode(params) if params else ""
        url = f"https://api.bithumb.com{path}" + (f"?{qs}" if qs else "")
        return http_json(url, {"Authorization": f"Bearer {tok}"})

    for path, bucket in (("/v1/withdraws", "w"), ("/v1/deposits", "d")):
        page = 1
        stop = False
        while not stop:
            if page > 200:
                raise RuntimeError(f"bithumb {path} 200페이지 초과 — 다음 주기 재시도")
            rows = call(path, {"limit": 100, "page": page, "order_by": "desc"})
            if not isinstance(rows, list):
                raise RuntimeError(f"bithumb {path} 응답이 목록이 아님 — 입출금 창 완료 보류: {str(rows)[:120]}")
            if not rows:
                break
            for row in rows:
                created = str(row.get("created_at") or "")
                try:
                    import datetime as _dt
                    cts = int(_dt.datetime.fromisoformat(created).timestamp())
                except (ValueError, TypeError):
                    cts = t1
                if cts < t0:
                    stop = True
                    break
                st_raw = str(row.get("state") or "").upper()
                nid = row.get("uuid") or f"{row.get('currency')}:{row.get('txid')}"
                if bucket == "w":
                    st = "DONE" if st_raw == "DONE" else (
                        {"CANCELED": "CANCELLED", "CANCELLED": "CANCELLED", "REJECTED": "REJECTED",
                         "FAILED": "FAILED"}.get(st_raw, "PENDING"))
                    out_w.append(norm_row("bithumb", nid, row.get("currency"),
                                          row.get("amount"), row.get("fee"), row.get("txid"),
                                          st, created, row.get("done_at"),
                                          row.get("address") or row.get("to_address"),
                                          row.get("secondary_address"), row.get("net_type")))
                else:
                    st = "ACCEPTED" if st_raw in ("ACCEPTED", "DONE", "DEPOSIT_ACCEPTED") \
                        else "PENDING"
                    out_d.append(norm_row("bithumb", nid, row.get("currency"),
                                          row.get("amount"), 0, row.get("txid"),
                                          st, created, row.get("done_at"), network=row.get("net_type")))
            time.sleep(PACE)
            page += 1
    w9, d9 = fetch_bithumb_krw(env, t0, t1, call=call)
    return out_w + w9, out_d + d9


BITHUMB_KRW_ST = {"ACCEPTED": "ACCEPTED", "DONE": "DONE", "CANCELLED": "CANCELLED", "CANCELED": "CANCELLED",
                  "REJECTED": "REJECTED", "FAILED": "FAILED"}
_BITHUMB_KRW_DENY = {"n": 0}


def fetch_bithumb_krw(env, t0: int, t1: int, call=None, require_complete: bool = False):
    call = call or _bithumb_caller(env)
    out_w, out_d = [], []
    for path, bucket in (("/v1/withdraws/krw", "w"), ("/v1/deposits/krw", "d")):
        page = 1
        stop = False
        while not stop:
            if page > 200:
                raise RuntimeError(f"bithumb {path} 200페이지 초과 — 다음 주기 재시도")
            try:
                rows = call(path, {"limit": 100, "page": page, "order_by": "desc"})
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    _BITHUMB_KRW_DENY["n"] += 1
                    if _BITHUMB_KRW_DENY["n"] % 144 == 1:
                        log.warning("bithumb 원화 입출금 조회 권한 없음(HTTP %s) — 원화 목록 생략(코인 입출금은 계속)", e.code)
                    if require_complete:
                        raise
                    return [], []
                raise
            if not isinstance(rows, list):
                raise RuntimeError(f"bithumb {path} 응답이 목록이 아님 — 원화 입출금 창 완료 보류: {str(rows)[:120]}")
            if not rows:
                break
            for row in rows:
                created = str(row.get("created_at") or "")
                try:
                    import datetime as _dt
                    cts = int(_dt.datetime.fromisoformat(created).timestamp())
                except (ValueError, TypeError):
                    cts = t1
                if cts < t0:
                    stop = True
                    break
                st_raw = str(row.get("state") or "").upper()
                st = BITHUMB_KRW_ST.get(st_raw, "PENDING")
                if bucket == "w" and st == "ACCEPTED":
                    st = "PENDING"
                if bucket == "d" and st == "DONE":
                    st = "ACCEPTED"
                nid = row.get("uuid") or f"KRW:{row.get('txid')}"
                r9 = norm_row("bithumb", nid, "KRW", row.get("amount"), row.get("fee") if bucket == "w" else 0,
                              row.get("txid"), st, created, row.get("done_at"))
                if row.get("transaction_type"):
                    r9["transaction_type"] = str(row["transaction_type"])
                (out_w if bucket == "w" else out_d).append(r9)
            if len(rows) < 100:
                break
            time.sleep(PACE)
            page += 1
    return out_w, out_d


FETCHERS = {
    "binance": (fetch_binance, ("TJ_BINANCE_KEY", "TJ_BINANCE_SECRET")),
    "bybit": (fetch_bybit, ("TJ_BYBIT_KEY", "TJ_BYBIT_SECRET")),
    "okx": (fetch_okx, ("TJ_OKX_KEY", "TJ_OKX_SECRET", "TJ_OKX_PASSPHRASE")),
    "kucoin": (fetch_kucoin, ("TJ_KUCOIN_KEY", "TJ_KUCOIN_SECRET", "TJ_KUCOIN_PASSPHRASE")),
    "gate": (fetch_gate, ("TJ_GATE_KEY", "TJ_GATE_SECRET")),
    "bithumb": (fetch_bithumb, ("TJ_BITHUMB_KEY", "TJ_BITHUMB_SECRET")),
}


QUOTES = ("USDT", "USDC", "FDUSD", "BUSD", "BTC", "BNB", "ETH", "KRW", "USD")


def split_pair(sym: str):
    s = sym.upper().replace("-", "").replace("_", "")
    for q in sorted(QUOTES, key=len, reverse=True):
        if s.endswith(q) and len(s) > len(q):
            return s[:-len(q)], q
    return s, ""


def norm_fill(ex, fid, ts_ms, base, quote, side, price, qty, fee, fee_ccy):
    return {"id": f"{ex}:{fid}", "ts": int(float(ts_ms)),
            "base": str(base or "").upper(),
            "quote": str(quote or "").upper(), "side": side,
            "price": str(price or "0"), "qty": str(qty or "0"),
            "fee": str(fee or "0"), "fee_ccy": str(fee_ccy or "").upper()}


def _binance_caller(env):
    key, sec = env["TJ_BINANCE_KEY"], env["TJ_BINANCE_SECRET"]

    @_clock_retry
    def call(path, extra):
        _gov_prepare("api.binance.com", path)
        q = dict(extra)
        q["timestamp"] = _srv_ms("api.binance.com")
        q["recvWindow"] = 10000
        qs = urllib.parse.urlencode(q)
        sig = hmac.new(sec.encode(), qs.encode(), hashlib.sha256).hexdigest()
        return http_json(f"https://api.binance.com{path}?{qs}&signature={sig}",
                         {"X-MBX-APIKEY": key})
    return call


def fills_binance_replay(env, fst: dict, rp: dict, deadline: float, emit, save) -> bool:
    call = _binance_caller(env)
    lo_ms, hi_ms = int(rp["lo"]) * 1000, int(rp["hi"]) * 1000
    pos = rp.setdefault("pos", {})
    done = set(rp.get("done") or [])
    keys = [("s:" + p9, int(c9 or 0)) for p9, c9 in (fst.get("pair_cursor") or {}).items()]
    keys += [(ck, int(c9 or 0)) for ck, c9 in (fst.get("margin_cursor") or {}).items()]
    inv9 = {"s:" + p9 for p9 in (fst.get("invalid_pairs") or [])} | set(fst.get("margin_invalid") or [])
    unav = set(rp.get("unavailable") or [])
    for k9, lim in sorted(keys):
        if k9 in done:
            continue
        if k9 in inv9 or k9 in unav:
            unav.add(k9)
            done.add(k9)
            rp["unavailable"], rp["done"] = sorted(unav), sorted(done)
            continue
        kind, pair = k9.split(":", 1)
        spot = kind == "s"
        base9, quote9 = _bn_split(pair, fst.get("pair_bq") or {}, _BN_UNI.get("sym"))
        page = 1000 if spot else 500
        while True:
            from_id = int(pos.get(k9) or 0)
            if lim and from_id >= lim:
                break
            if time.time() >= deadline:
                rp["done"] = sorted(done)
                save()
                return False
            try:
                if spot:
                    rows = call("/api/v3/myTrades", {"symbol": pair, "fromId": from_id, "limit": page})
                else:
                    rows = call("/sapi/v1/margin/myTrades", {"symbol": pair, "isIsolated": "TRUE" if kind == "i" else "FALSE",
                                                             "fromId": from_id, "limit": page})
            except urllib.error.HTTPError as e:
                body9 = _err_body(e)[:120]
                if e.code == 400 and ("-1121" in body9 or (not spot and "-11001" in body9)):
                    log.warning("binance 재조회 %s: 무효 페어(%s) — 조회 불가로 건너뜀", k9, body9[:60])
                    unav.add(k9)
                    rp["unavailable"] = sorted(unav)
                    break
                raise
            if not rows:
                break
            out = []
            for r in rows:
                if lim and int(r["id"]) >= lim:
                    continue
                if not (lo_ms <= int(r["time"]) < hi_ms):
                    continue
                fid = f"{pair}:{r['id']}" if spot else f"m{'i' if kind == 'i' else ''}:{pair}:{r['id']}"
                out.append(norm_fill("binance", fid, r["time"], base9, quote9,
                                     "buy" if r.get("isBuyer") else "sell",
                                     r.get("price"), r.get("qty"), r.get("commission"), r.get("commissionAsset")))
            if out:
                emit(out)
            pos[k9] = int(rows[-1]["id"]) + 1
            save()
            time.sleep(0.25)
            if len(rows) < page or int(rows[-1]["time"]) >= hi_ms:
                break
        done.add(k9)
        rp["done"] = sorted(done)
        save()
    return True


def bn_gap_step(env, st: dict, ext: dict, stop_at: int, now: int, deadline: float, emit, save) -> bool:
    lo9 = int((ext.get("bn_replay") or {}).get("hi") or ext.get("hi0") or stop_at)
    gp = ext.get("bn_gap")
    if not isinstance(gp, dict) or int(gp.get("lo") or 0) != lo9:
        gp = ext["bn_gap"] = {"lo": lo9, "hi": int(now), "pos": {}, "done": []}
        save()
    try:
        fin = FILL_REPLAY["binance"](env, st.get("fills") or {}, gp, deadline, emit, save)
    except Exception as e:
        ext["fills_err"] = _xm(repr(e))[:160]
        save()
        return False
    if fin:
        ext["bn_gap_done"] = int(time.time())
        ext.pop("fills_err", None)
        save()
    return bool(fin)


def binance_fills_t0(st: dict, now: int, window: int) -> int:
    t0 = int(now - window)
    ext = (st or {}).get("ext")
    if isinstance(ext, dict) and isinstance(ext.get("fills_from"), (int, float)):
        t0 = min(t0, int(ext["fills_from"]))
    return t0


BINANCE_QUOTES = ("USDT", "USDC", "BTC", "BNB", "FDUSD")
BN_UNI_NAME = "exf_binance_symbols.json"
BN_UNI_TTL = 24 * 3600
BN_UNI_RETRY = 3600
BN_IDLE_SEC = 6 * 3600
BN_SWEEP_SEC = 24 * 3600
BN_INVALID_RECHECK = 7 * DAY
BN_RECENT_SEC = 7 * DAY
BN_LATE_MARGIN = 120
BN_FIRST_SWEEP_SEC = 180
RECON_HOLD_CAP = 6 * 3600
_BN_UNI = {"ts": 0.0, "fail": 0.0, "sym": None, "path": None}
_WD_TOUCH = {}
_POLL_HINT = [POLL_SEC]


def _dstr(x) -> str:
    try:
        d = Decimal(str(x))
    except (InvalidOperation, TypeError, ValueError):
        return "0"
    if not d.is_finite():
        return "0"
    return format(d.normalize(), "f") if d != 0 else "0"


def _bn_universe(now: float):
    u = _BN_UNI
    p = os.path.join(common.STATE_DIR, BN_UNI_NAME)
    if u.get("path") != p:
        u.update(ts=0.0, fail=0.0, sym=None, path=p)
        try:
            d = common.read_json(p, {}) if os.path.exists(p) else {}
        except SystemExit:
            d = {}
        sy = d.get("symbols") if isinstance(d, dict) else None
        if isinstance(sy, dict) and sy:
            u["sym"] = {str(k): (str(v[0]), str(v[1]), str(v[2]), int(v[3] if len(v) > 3 else 0))
                        for k, v in sy.items() if isinstance(v, list) and len(v) >= 3}
            try:
                u["ts"] = float(d.get("ts") or 0)
            except (TypeError, ValueError):
                u["ts"] = 0.0
    if now - u["ts"] >= BN_UNI_TTL and now - u["fail"] >= BN_UNI_RETRY:
        try:
            d = http_json("https://api.binance.com/api/v3/exchangeInfo", timeout=60)
            rows = d.get("symbols") if isinstance(d, dict) else None
            if not isinstance(rows, list) or not rows:
                raise RuntimeError("exchangeInfo symbols 누락/형식 오류")
            sym = {}
            for r in rows:
                if not isinstance(r, dict):
                    continue
                s9 = str(r.get("symbol") or "").upper()
                b9 = str(r.get("baseAsset") or "").upper()
                q9 = str(r.get("quoteAsset") or "").upper()
                if s9 and b9 and q9:
                    sym[s9] = (b9, q9, str(r.get("status") or ""), 1 if r.get("isMarginTradingAllowed") else 0)
            if not sym:
                raise RuntimeError("exchangeInfo 심볼 0")
            u["sym"], u["ts"] = sym, float(now)
            common.atomic_write_json(p, {"ts": int(now), "symbols": {k: list(v) for k, v in sym.items()}})
            log.info("binance 심볼 목록 갱신: %d개(상장 폐지 포함)", len(sym))
        except Exception as e:
            u["fail"] = float(now)
            log.warning("binance exchangeInfo 갱신 실패(%s · 1시간 뒤 재시도): %s",
                        "직전 목록 사용" if u["sym"] else "종전 주요 쿼트 5종으로", _xm(repr(e))[:140])
    return u["sym"]


def _bn_split(pair: str, bq: dict, uni):
    v = bq.get(pair) if isinstance(bq, dict) else None
    if isinstance(v, (list, tuple)) and len(v) >= 2 and v[0] and v[1]:
        return str(v[0]), str(v[1])
    if uni and pair in uni:
        return uni[pair][0], uni[pair][1]
    b9 = next((pair[:-len(q)] for q in BINANCE_QUOTES if pair.endswith(q) and len(pair) > len(q)), None)
    if b9:
        return b9, pair[len(b9):]
    return split_pair(pair)


def _bn_inv_load(lst, at, uni, now):
    out = {}
    for p, t in (at.items() if isinstance(at, dict) else ()):
        try:
            out[str(p)] = float(t)
        except (TypeError, ValueError):
            continue
    for p in (lst or []):
        p = str(p)
        if p in out:
            continue
        if uni and p in uni:
            continue
        out[p] = float(now)
    return {p: t for p, t in out.items() if now - t < BN_INVALID_RECHECK}


def _recon_hold(fst: dict, key: str, now: int, why: str) -> bool:
    hs = fst.get("hold_since")
    if not isinstance(hs, dict):
        hs = fst["hold_since"] = {}
    try:
        t0 = int(hs.get(key) or 0) or int(now)
    except (TypeError, ValueError):
        t0 = int(now)
    hs[key] = t0
    if int(now) - t0 > RECON_HOLD_CAP:
        return False
    rh = fst.get("recon_hold")
    fst["recon_hold"] = (str(rh) + " · " if rh else "") + str(why)[:120]
    return True


def _recon_hold_clear(fst: dict, key: str) -> None:
    hs = fst.get("hold_since")
    if isinstance(hs, dict):
        hs.pop(key, None)
        if not hs:
            fst.pop("hold_since", None)


def fills_binance(env, st, t0: int, t1: int):
    call = _binance_caller(env)
    now9 = int(time.time())
    late_before = int(st.get("bn_acct_at") or st.get("backfilled_until") or 0)
    if not st.get("backfilled_until") and not st.get("bn_sweep_full") and not isinstance(st.get("bn_first_sweep"), dict):
        st["bn_first_sweep"] = {"at": now9, "n": 0, "done": []}
    acct = call("/api/v3/account", {"omitZeroBalances": "true"})
    acct_at = int(time.time())
    cur = {}
    for b in acct.get("balances", []):
        try:
            fr, lk = Decimal(str(b.get("free") or 0)), Decimal(str(b.get("locked") or 0))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if fr + lk > 0:
            cur[str(b["asset"]).upper()] = [_dstr(fr), _dstr(lk)]
    bases = set(cur)
    st["extra_bases"] = sorted(set(st.get("extra_bases") or []) | bases)
    bases |= set(st.get("extra_bases") or [])
    prev = st.get("bn_bal") if isinstance(st.get("bn_bal"), dict) else None
    touch = {str(x).upper() for x in (_WD_TOUCH.get("binance") or ()) if x}
    dirty = {str(x).upper() for x in (st.get("bn_dirty") or [])} | touch
    lock_chg = False
    if prev is None:
        dirty |= set(cur)
        lock_chg = True
    else:
        for a in set(cur) | set(prev):
            p0, c0 = prev.get(a) or ["0", "0"], cur.get(a) or ["0", "0"]
            try:
                if Decimal(str(p0[0])) + Decimal(str(p0[1])) != Decimal(c0[0]) + Decimal(c0[1]):
                    dirty.add(a)
                elif str(p0[1]) != c0[1]:
                    lock_chg = True
            except (InvalidOperation, TypeError, ValueError, IndexError):
                dirty.add(a)
    st["bn_dirty"] = sorted(dirty)
    st["bn_last_dirty"] = sorted(dirty)
    uni = _bn_universe(now9)
    by_base, quotes_all = {}, set(BINANCE_QUOTES)
    if uni:
        for s9, v9 in uni.items():
            by_base.setdefault(v9[0], []).append(s9)
            quotes_all.add(v9[1])
    cursors = dict(st.get("pair_cursor") or {})
    bq = dict(st.get("pair_bq") or {})
    chk = {str(k): float(v) for k, v in (st.get("pair_chk") or {}).items() if isinstance(v, (int, float))}
    last = {str(k): float(v) for k, v in (st.get("pair_last") or {}).items() if isinstance(v, (int, float))}
    open_prev = set(st.get("bn_open") or [])
    inv = _bn_inv_load(st.get("invalid_pairs"), st.get("invalid_at"), uni, now9)
    bases |= {_bn_split(p9, bq, uni)[0] for p9 in cursors}
    bases |= {_bn_split(s9, bq, uni)[0] for s9 in open_prev}
    bases |= dirty

    def pairs_of(b):
        if uni:
            return [(s9, uni[s9][0], uni[s9][1]) for s9 in by_base.get(b, ())]
        return [(b + q, b, q) for q in BINANCE_QUOTES if b != q]

    cand = {}
    for b in bases:
        for p9, b9, q9 in pairs_of(b):
            cand[p9] = (b9, q9)
    for p9 in cursors:
        cand.setdefault(p9, _bn_split(p9, bq, uni))
    cand = {p9: v9 for p9, v9 in cand.items() if p9 not in inv and v9[0] != v9[1]}
    fills, polled, explained = [], set(), set()
    partial = None
    n_calls = [0]

    def poll(pair, b, q):
        from_id = int(cursors.get(pair) or 0)
        while True:
            try:
                n_calls[0] += 1
                rows = call("/api/v3/myTrades", {"symbol": pair, "fromId": from_id, "limit": 1000})
            except urllib.error.HTTPError as e:
                body = _err_body(e)[:120]
                if e.code == 400 and "-1121" in body:
                    inv[pair] = float(now9)
                    break
                if e.code == 400 and "-1021" in body:
                    raise SignatureExpired(f"binance myTrades {pair} -1021(타임스탬프 창 밖)") from None
                raise
            if not isinstance(rows, list):
                raise RuntimeError(f"binance myTrades {pair} 응답 형식 오류")
            if not rows:
                break
            for r in rows:
                fills.append(norm_fill("binance", f"{pair}:{r['id']}", r["time"], b, q,
                                       "buy" if r.get("isBuyer") else "sell",
                                       r.get("price"), r.get("qty"),
                                       r.get("commission"), r.get("commissionAsset")))
                explained.update({b, q, str(r.get("commissionAsset") or "").upper()})
            from_id = int(rows[-1]["id"]) + 1
            cursors[pair] = from_id
            bq[pair] = [b, q]
            last[pair] = max(last.get(pair, 0.0), int(rows[-1]["time"]) / 1000.0)
            time.sleep(0.25)
            if len(rows) < 1000:
                break
        chk[pair] = float(now9)
        polled.add(pair)
        time.sleep(0.15)

    n_dirty = n_tgt = n_safe = n_sweep = 0
    open_now = None
    try:
        if lock_chg or any(a in quotes_all or pairs_of(a) for a in dirty):
            try:
                oo = call("/api/v3/openOrders", {})
                if isinstance(oo, list):
                    open_now = sorted({str(o.get("symbol") or "").upper() for o in oo if isinstance(o, dict) and o.get("symbol")})
            except RateLimited:
                raise
            except Exception as e9:
                log.warning("binance 미체결 주문 조회 실패(표적 조회 재료만 생략): %s", _xm(repr(e9))[:120])
        for p9 in sorted(p for p, v in cand.items() if v[0] in dirty):
            poll(p9, *cand[p9])
            n_dirty += 1
        unexpl = {a for a in dirty if a in quotes_all and a not in explained and a not in touch}
        if unexpl:
            recent = {_bn_split(p9, bq, uni)[0] for p9, t9 in last.items() if now9 - t9 < BN_RECENT_SEC}
            opn = {_bn_split(s9, bq, uni)[0] for s9 in (open_prev | set(open_now or ()))}
            tb = set(cur) | recent | opn
            tgt = set()
            for b9 in tb:
                for p9, bb9, qq9 in pairs_of(b9):
                    if qq9 in unexpl and p9 not in polled and p9 not in inv and bb9 != qq9:
                        tgt.add((p9, bb9, qq9))
            for p9, bb9, qq9 in sorted(tgt):
                poll(p9, bb9, qq9)
                n_tgt += 1
                cand.setdefault(p9, (bb9, qq9))
        poll9 = max(60, int(_POLL_HINT[0] or POLL_SEC))
        due = sorted((p for p in cand if p not in polled and now9 - chk.get(p, 0.0) >= BN_IDLE_SEC), key=lambda p: (chk.get(p, 0.0), p))
        cap1 = max(8, int(len(cand) * poll9 * 1.25 / BN_IDLE_SEC) + 1)
        for p9 in due[:cap1]:
            if p9 in inv:
                continue
            poll(p9, *cand[p9])
            n_safe += 1
        fs9 = st.get("bn_first_sweep") if isinstance(st.get("bn_first_sweep"), dict) else None
        if uni and fs9 is not None:
            done9 = {str(x) for x in (fs9.get("done") or [])} | polled
            need9 = {s9 for s9 in uni if s9 not in inv and uni[s9][0] != uni[s9][1]}
            todo9 = sorted(need9 - done9)
            fs9["done"], fs9["n"] = sorted(done9), len(done9 & need9)
            n2 = int(len(need9) * poll9 / BN_SWEEP_SEC) + 1
            t_end9 = time.time() + BN_FIRST_SWEEP_SEC
            for k9, p9 in enumerate(todo9):
                if k9 >= n2 and time.time() >= t_end9:
                    break
                poll(p9, uni[p9][0], uni[p9][1])
                n_sweep += 1
                fs9["done"].append(p9)
                done9.add(p9)
                fs9["n"] = len(done9 & need9)
            if not (need9 - done9 - set(inv)):
                st.pop("bn_first_sweep", None)
                st["bn_sweep_full"] = now9
                _recon_hold_clear(st, "first_sweep")
                fs9 = None
                log.info("binance 전 심볼 안전망 첫 바퀴 완료(%d개) — 이제 잔고 대사 시작", len(need9))
        elif uni:
            rest = sorted(s9 for s9 in uni if s9 not in cand and s9 not in inv and uni[s9][0] != uni[s9][1])
            if rest:
                n2 = int(len(rest) * poll9 / BN_SWEEP_SEC) + 1
                pos = int(st.get("bn_sweep_pos") or 0) % len(rest)
                for p9 in (rest[pos:] + rest[:pos])[:n2]:
                    poll(p9, uni[p9][0], uni[p9][1])
                    n_sweep += 1
                st["bn_sweep_pos"] = (pos + n2) % len(rest)
    except (RateLimited, SignatureExpired) as e:
        partial = _xm(str(e))[:160]
    if isinstance(st.get("bn_first_sweep"), dict) and polled:
        fsd9 = st["bn_first_sweep"]
        fsd9["done"] = sorted({str(x) for x in (fsd9.get("done") or [])} | polled)
    if open_now is not None:
        st["bn_open"] = open_now
    if isinstance(st.get("bn_first_sweep"), dict):
        if not _recon_hold(st, "first_sweep", now9, "후보 밖 전 심볼 첫 바퀴 진행 중(%d개 확인)" % int(st["bn_first_sweep"].get("n") or 0)):
            st.pop("bn_first_sweep", None)
            _recon_hold_clear(st, "first_sweep")
            log.warning("binance 전 심볼 첫 바퀴가 %d시간 넘게 못 끝남 — 잔고 대사 보류 해제(늦게 찾은 체결은 core 늦은 행 흡수)", RECON_HOLD_CAP // 3600)
    st["extra_bases"] = sorted(set(st["extra_bases"]) | {cand[p9][0] for p9 in polled if p9 in cursors and p9 in cand})
    st["invalid_at"] = {p9: int(t9) for p9, t9 in inv.items()}
    st["invalid_pairs"] = sorted(inv)
    st["pair_cursor"] = cursors
    st["pair_bq"] = {p9: v9 for p9, v9 in bq.items() if p9 in cursors}
    st["pair_chk"] = {p9: int(t9) for p9, t9 in chk.items() if p9 in cand or p9 in cursors}
    st["pair_last"] = {p9: int(t9) for p9, t9 in last.items() if p9 in cursors}

    m_cursors = dict(st.get("margin_cursor") or {})
    m_inv = _bn_inv_load(st.get("margin_invalid"), st.get("margin_invalid_at"), None, now9)
    m_chk = {str(k): float(v) for k, v in (st.get("margin_chk") or {}).items() if isinstance(v, (int, float))}
    n_margin = 0
    if partial is None:
        try:
            d2 = call("/sapi/v1/margin/account", {})
            mcur = {}
            for a in d2.get("userAssets") or []:
                vals = [_dstr(a.get(k) or 0) for k in ("free", "locked", "borrowed", "interest", "netAsset")]
                if any(v9 != "0" for v9 in vals):
                    mcur[str(a.get("asset") or "").upper()] = vals
            d3 = call("/sapi/v1/margin/isolated/account", {})
            icur = {}
            for p in d3.get("assets") or []:
                if not p.get("symbol"):
                    continue
                sig9 = []
                for side in ("baseAsset", "quoteAsset"):
                    a9 = p.get(side) or {}
                    sig9 += [str(a9.get("asset") or "").upper()] + [_dstr(a9.get(k) or 0) for k in ("free", "locked", "borrowed", "interest", "netAsset")]
                icur[str(p["symbol"]).upper()] = sig9
            mprev = st.get("m_bal") if isinstance(st.get("m_bal"), dict) else None
            iprev = st.get("m_iso") if isinstance(st.get("m_iso"), dict) else None
            mdirty = set(mcur) if mprev is None else {a for a in set(mcur) | set(mprev) if mprev.get(a) != mcur.get(a)}
            idirty = set(icur) if iprev is None else {s9 for s9 in set(icur) | set(iprev) if iprev.get(s9) != icur.get(s9)}
            mpairs = {}
            for ck in m_cursors:
                pr = ck[2:]
                b9, q9 = _bn_split(pr, bq, uni)
                mpairs[ck] = (pr, "TRUE" if ck.startswith("i:") else "FALSE", b9, q9)
            for b9 in sorted(mcur):
                for q9 in BINANCE_QUOTES:
                    if b9 != q9 and (not uni or b9 + q9 in uni):
                        mpairs.setdefault(f"c:{b9}{q9}", (b9 + q9, "FALSE", b9, q9))
            for s9 in icur:
                b9, q9 = _bn_split(s9, bq, uni)
                mpairs.setdefault(f"i:{s9}", (s9, "TRUE", b9, q9))
            for ck in sorted(mpairs):
                pair, iso_flag, b9, q9 = mpairs[ck]
                if ck in m_inv:
                    continue
                if not b9 or not q9 or b9 == q9:
                    log.warning("binance 마진 페어 쿼트 미상 %s — 스킵", pair)
                    m_inv[ck] = float(now9)
                    continue
                hit = (pair in idirty) if iso_flag == "TRUE" else (b9 in mdirty or q9 in mdirty)
                if not hit and now9 - m_chk.get(ck, 0.0) < BN_IDLE_SEC:
                    continue
                from_id = int(m_cursors.get(ck) or 0)
                while True:
                    try:
                        n_margin += 1
                        rows = call("/sapi/v1/margin/myTrades",
                                    {"symbol": pair, "isIsolated": iso_flag,
                                     "fromId": from_id, "limit": 500})
                    except urllib.error.HTTPError as e:
                        body = _err_body(e)[:120]
                        if e.code == 400 and ("-1121" in body or "-11001" in body):
                            m_inv[ck] = float(now9)
                            break
                        if e.code == 400 and "-1021" in body:
                            raise SignatureExpired(f"binance margin myTrades {pair} -1021(타임스탬프 창 밖)") from None
                        raise
                    if not rows:
                        break
                    for r in rows:
                        fills.append(norm_fill(
                            "binance", f"m{'i' if iso_flag == 'TRUE' else ''}:{pair}:{r['id']}",
                            r["time"], b9, q9,
                            "buy" if r.get("isBuyer") else "sell",
                            r.get("price"), r.get("qty"),
                            r.get("commission"), r.get("commissionAsset")))
                    from_id = int(rows[-1]["id"]) + 1
                    m_cursors[ck] = from_id
                    bq.setdefault(pair, [b9, q9])
                    time.sleep(0.25)
                    if len(rows) < 500:
                        break
                m_chk[ck] = float(now9)
                time.sleep(0.15)
            st["m_bal"], st["m_iso"] = mcur, icur
            st["margin_chk"] = {k9: int(v9) for k9, v9 in m_chk.items() if k9 in mpairs}
            _recon_hold_clear(st, "margin")
        except (RateLimited, SignatureExpired) as e9m:
            partial = _xm(str(e9m))[:160]
        except Exception as e9m:
            msg9m = _xm(repr(e9m))
            if isinstance(e9m, urllib.error.HTTPError):
                msg9m += " " + _xm(_err_body(e9m)[:200])
            if any(k9 in msg9m for k9 in _DENY_SIGS):
                _recon_hold_clear(st, "margin")
                log.warning("binance 마진 체결 수집 생략(권한 없음/마진 미개설 — 스팟은 정상): %s", msg9m[:140])
            else:
                held9 = _recon_hold(st, "margin", now9, "마진 체결 수집 실패")
                log.warning("binance 마진 체결 수집 생략(다음 주기 재시도 — 스팟은 정상 · %s): %s",
                            "이번 주기 잔고 승격 보류" if held9 else "보류 상한 지남 — 대사 계속", msg9m[:140])
    st["margin_invalid_at"] = {k9: int(v9) for k9, v9 in m_inv.items()}
    st["margin_invalid"] = sorted(m_inv)
    st["margin_cursor"] = m_cursors
    st["pair_bq"] = {p9: v9 for p9, v9 in bq.items() if p9 in cursors or any(ck[2:] == p9 for ck in m_cursors)}
    if partial is None:
        st["bn_bal"] = cur
        st["bn_dirty"] = []
        st["bn_acct_at"] = acct_at
    else:
        st["partial"] = partial
    st["bn_stats"] = {"calls": n_calls[0] + 1 + n_margin, "dirty": n_dirty, "target": n_tgt, "safety": n_safe, "sweep": n_sweep,
                      "margin": n_margin, "cand": len(cand), "at": now9}
    if late_before:
        lim9 = (late_before - BN_LATE_MARGIN) * 1000
        for f in fills:
            if f["ts"] < lim9:
                f["late"] = 1
    collected_until = int(time.time() * 1000) + 60000
    return [f for f in fills if t0 * 1000 <= f["ts"] <= collected_until]


BB_UNI_NAME = "exf_bybit_symbols.json"
BB_UNI_URL = "https://api.bybit.com/v5/market/instruments-info"
BB_HOLD_MAX = 2000
_BB_UNI = {"ts": 0.0, "fail": 0.0, "sym": None, "path": None}


def _bb_universe(now: float, need: bool = False):
    u = _BB_UNI
    p = os.path.join(common.STATE_DIR, BB_UNI_NAME)
    if u.get("path") != p:
        u.update(ts=0.0, fail=0.0, sym=None, path=p)
        try:
            d = common.read_json(p, {}) if os.path.exists(p) else {}
        except SystemExit:
            d = {}
        sy = d.get("symbols") if isinstance(d, dict) else None
        if isinstance(sy, dict) and sy:
            u["sym"] = {str(k): (str(v[0]), str(v[1])) for k, v in sy.items() if isinstance(v, list) and len(v) >= 2 and v[0] and v[1]}
            try:
                u["ts"] = float(d.get("ts") or 0)
            except (TypeError, ValueError):
                u["ts"] = 0.0
    due = now - u["ts"] >= BN_UNI_TTL or (need and now - u["ts"] >= BN_UNI_RETRY)
    if due and now - u["fail"] >= BN_UNI_RETRY:
        try:
            sym, cur, seen9 = {}, "", set()
            for _pg in range(10):
                q9 = {"category": "spot", "limit": 1000}
                if cur:
                    q9["cursor"] = cur
                d = http_json(BB_UNI_URL + "?" + urllib.parse.urlencode(q9), timeout=30)
                if not isinstance(d, dict) or d.get("retCode") != 0 or not isinstance((d.get("result") or {}).get("list"), list):
                    raise RuntimeError(f"instruments-info 형식 오류 {_xm((d or {}).get('retCode') if isinstance(d, dict) else type(d).__name__)}")
                for r in d["result"]["list"]:
                    if not isinstance(r, dict):
                        continue
                    s9 = str(r.get("symbol") or "").upper()
                    b9, q9b = str(r.get("baseCoin") or "").upper(), str(r.get("quoteCoin") or "").upper()
                    if s9 and b9 and q9b and b9 != q9b:
                        sym[s9] = (b9, q9b)
                cur = str(d["result"].get("nextPageCursor") or "")
                if not cur or cur in seen9:
                    break
                seen9.add(cur)
            if not sym:
                raise RuntimeError("instruments-info 종목 0")
            u["sym"], u["ts"] = dict(u["sym"] or {}, **sym), float(now)
            common.atomic_write_json(p, {"ts": int(now), "symbols": {k: list(v) for k, v in u["sym"].items()}})
            log.info("bybit 종목 목록 갱신: %d개(이번 응답 %d)", len(u["sym"]), len(sym))
        except Exception as e:
            u["fail"] = float(now)
            log.warning("bybit instruments-info 갱신 실패(%s · 1시간 뒤 재시도): %s",
                        "직전 목록 사용" if u["sym"] else "종전 주요 쿼트로", _xm(repr(e))[:140])
    return u["sym"]


def _bb_split(sym: str, uni):
    s = str(sym or "").upper()
    if uni and s in uni:
        return uni[s]
    b, q = split_pair(s)
    return (b, q) if (b and q) else (None, None)


def _bb_fill(r, b, q):
    return norm_fill("bybit", r.get("execId"), r.get("execTime"), b, q, str(r.get("side", "")).lower(),
                     r.get("execPrice"), r.get("execQty"), r.get("execFee"), r.get("feeCurrency") or q)


def _bb_hold_keep(st: dict, cp: dict) -> bool:
    h9 = cp.get("bb_hold") if isinstance(cp, dict) else None
    if not isinstance(h9, dict) or not h9:
        return False
    dst = (st.setdefault("fills", {})).setdefault("bb_hold", {})
    add = {k: v for k, v in h9.items() if k not in dst}
    dst.update(add)
    return bool(add)


def fills_bybit(env, st, t0: int, t1: int):
    key, sec = env["TJ_BYBIT_KEY"], env["TJ_BYBIT_SECRET"]

    @_clock_retry
    def call(params):
        _gov_prepare("api.bybit.com", "/v5/execution/list")
        qs = urllib.parse.urlencode(params)
        ts = str(_srv_ms("api.bybit.com"))
        recv = "10000"
        sig = hmac.new(sec.encode(), (ts + key + recv + qs).encode(), hashlib.sha256).hexdigest()
        d = http_json(f"https://api.bybit.com/v5/execution/list?{qs}",
                      {"X-BAPI-API-KEY": key, "X-BAPI-TIMESTAMP": ts,
                       "X-BAPI-RECV-WINDOW": recv, "X-BAPI-SIGN": sig})
        if d.get("retCode") != 0:
            raise RuntimeError(f"bybit {d.get('retCode')} {_xm(d.get('retMsg'))}")
        return d.get("result") or {}

    fills = []
    now9 = int(time.time())
    uni = [_bb_universe(now9), False]

    def split9(sym):
        b9, q9 = _bb_split(sym, uni[0])
        if not q9 and not uni[1]:
            uni[1] = True
            uni[0] = _bb_universe(now9, need=True)
            b9, q9 = _bb_split(sym, uni[0])
        return b9, q9
    hold = st.get("bb_hold") if isinstance(st.get("bb_hold"), dict) else {}
    st["bb_hold"] = hold
    out9 = set()
    for k9 in sorted(hold, key=lambda k: str((hold[k] or {}).get("execTime") or "")):
        r9 = hold[k9] if isinstance(hold[k9], dict) else {}
        b9, q9 = split9(r9.get("symbol"))
        if q9:
            f9 = _bb_fill(r9, b9, q9)
            f9["late"] = 1
            fills.append(f9)
            out9.add(k9)
    for k9 in out9:
        hold.pop(k9, None)
    if out9:
        log.info("bybit 보류 체결 %d건 방출(종목 목록으로 대금 통화 확인)", len(out9))
    s = t0
    while s < t1:
        e = min(s + 6 * DAY, t1)
        cursor = ""
        seen_cursors = set()
        while True:
            p = {"category": "spot", "startTime": s * 1000, "endTime": e * 1000, "limit": 100}
            if cursor:
                p["cursor"] = cursor
            res = call(p)
            rows = res.get("list") or []
            for r in rows:
                k9 = str(r.get("execId") or "")
                if k9 in out9:
                    continue
                b, q = split9(r.get("symbol"))
                if not q:
                    if k9 and k9 not in hold and str(r.get("symbol") or "").strip():
                        hold[k9] = {kk: r.get(kk) for kk in ("symbol", "execId", "execTime", "side", "execPrice", "execQty", "execFee", "feeCurrency")}
                        hold[k9]["held_at"] = now9
                        log.warning("bybit 체결 보류 — 종목 목록에 없는 심볼 %s(대금 통화 모름): %s", _xm(r.get("symbol"))[:24], k9[:24])
                    continue
                fills.append(_bb_fill(r, b, q))
            cursor = res.get("nextPageCursor") or ""
            if cursor and cursor in seen_cursors:
                raise RuntimeError("bybit 체결 페이지 커서 순환 — 다음 주기 재시도")
            seen_cursors.add(cursor)
            time.sleep(PACE)
            if not cursor or not rows:
                break
        s = e
    if len(hold) > BB_HOLD_MAX:
        for k9 in sorted(hold, key=lambda k: int((hold[k] or {}).get("held_at") or 0))[:len(hold) - BB_HOLD_MAX]:
            hold.pop(k9, None)
        log.warning("bybit 보류 체결 상한 %d 초과 — 가장 오래된 것부터 버림", BB_HOLD_MAX)
    if hold:
        _recon_hold(st, "bb_split", now9, f"바이비트 대금 통화 모르는 체결 {len(hold)}건 보류")
    else:
        st.pop("bb_hold", None)
        _recon_hold_clear(st, "bb_split")
    return fills


def fills_okx(env, st, t0: int, t1: int):
    key, sec, pph = env["TJ_OKX_KEY"], env["TJ_OKX_SECRET"], env["TJ_OKX_PASSPHRASE"]

    @_clock_retry
    def call(params):
        _gov_prepare("www.okx.com", "/api/v5/trade/fills-history")
        qs = urllib.parse.urlencode(params)
        full = "/api/v5/trade/fills-history" + ("?" + qs if qs else "")
        ts = _okx_ts(_srv_ms("www.okx.com"))
        sig = base64.b64encode(hmac.new(sec.encode(), (ts + "GET" + full).encode(),
                                        hashlib.sha256).digest()).decode()
        d = http_json("https://www.okx.com" + full,
                      {"OK-ACCESS-KEY": key, "OK-ACCESS-SIGN": sig,
                       "OK-ACCESS-TIMESTAMP": ts, "OK-ACCESS-PASSPHRASE": pph})
        if d.get("code") != "0":
            raise RuntimeError(f"okx {d.get('code')} {_xm(d.get('msg'))}")
        return d.get("data") or []

    fills = []
    after = ""
    seen_pages = set()
    while True:
        p = {"instType": "SPOT", "limit": 100}
        if after:
            p["after"] = after
        rows = call(p)
        if not rows:
            break
        for r in rows:
            if int(r.get("ts") or 0) < t0 * 1000:
                continue
            inst = str(r.get("instId") or "")
            b, _, q = inst.partition("-")
            try:
                fee_ok = -float(r.get("fee") or 0)
            except (TypeError, ValueError):
                fee_ok = 0
            fills.append(norm_fill("okx", r.get("billId"), r.get("ts"), b, q,
                                   str(r.get("side", "")).lower(), r.get("fillPx"),
                                   r.get("fillSz"), fee_ok, r.get("feeCcy")))
        oldest = min(int(r.get("ts") or 0) for r in rows)
        time.sleep(PACE)
        if oldest // 1000 <= t0 or len(rows) < 100:
            break
        nxt = rows[-1].get("billId") or str(oldest)
        if nxt in seen_pages:
            raise RuntimeError("okx 체결 페이지 커서 순환 — 다음 주기 재시도")
        seen_pages.add(nxt)
        after = nxt
    return fills


def fills_kucoin(env, st, t0: int, t1: int):
    key, sec, pph = env["TJ_KUCOIN_KEY"], env["TJ_KUCOIN_SECRET"], env["TJ_KUCOIN_PASSPHRASE"]

    @_clock_retry
    def call(path_with_qs):
        _gov_prepare("api.kucoin.com", path_with_qs.split("?", 1)[0])
        ts = str(_srv_ms("api.kucoin.com"))
        sig = base64.b64encode(hmac.new(sec.encode(), (ts + "GET" + path_with_qs).encode(),
                                        hashlib.sha256).digest()).decode()
        pph_sig = base64.b64encode(hmac.new(sec.encode(), pph.encode(),
                                            hashlib.sha256).digest()).decode()
        d = http_json("https://api.kucoin.com" + path_with_qs,
                      {"KC-API-KEY": key, "KC-API-SIGN": sig, "KC-API-TIMESTAMP": ts,
                       "KC-API-PASSPHRASE": pph_sig, "KC-API-KEY-VERSION": "2"})
        if d.get("code") != "200000":
            raise RuntimeError(f"kucoin {d.get('code')} {_xm(d.get('msg'))}")
        return d.get("data") or {}

    fills = []
    s = t0
    while s < t1:
        e = min(s + 6 * DAY, t1)
        page = 1
        while True:
            qs = urllib.parse.urlencode({"startAt": s * 1000, "endAt": e * 1000,
                                         "pageSize": 500, "currentPage": page})
            data = call(f"/api/v1/fills?{qs}")
            items = data.get("items") or []
            for r in items:
                b, _, q = str(r.get("symbol") or "").partition("-")
                fills.append(norm_fill("kucoin", f"{r.get('symbol')}:{r.get('tradeId')}",
                                       r.get("createdAt"),
                                       b, q, str(r.get("side", "")).lower(), r.get("price"),
                                       r.get("size"), r.get("fee"), r.get("feeCurrency")))
            time.sleep(PACE)
            if page >= int(data.get("totalPage") or 1):
                break
            page += 1
        s = e
    return fills + _kucoin_hf_pass(call, st, t0, t1, fills)


KC_HF_LEDGER_PAGES = 50
KC_HF_FILL_PAGES = 100
KC_HF_DENY = ("kucoin 400007", "kucoin 400006", "kucoin 400003", "kucoin 404", "HTTPError 404", "HTTP Error 404", "HTTPError 401", "HTTPError 403",
              "HTTP Error 401", "HTTP Error 403")


def _kc_ctx_symbol(r):
    c9 = r.get("context") if isinstance(r, dict) else None
    if isinstance(c9, str):
        try:
            c9 = json.loads(c9)
        except ValueError:
            m9 = re.search(r'"symbol"\s*:\s*"([A-Za-z0-9]+-[A-Za-z0-9]+)"', c9)
            return m9.group(1).upper() if m9 else None
    if isinstance(c9, dict) and "-" in str(c9.get("symbol") or ""):
        return str(c9["symbol"]).upper()
    return None


def _kucoin_hf_window(call, s, e, have_ids):
    syms, last = set(), None
    for _ in range(KC_HF_LEDGER_PAGES):
        q9 = {"bizType": "TRADE_EXCHANGE", "startAt": s * 1000, "endAt": e * 1000, "limit": 200}
        if last:
            q9["lastId"] = last
        rows = call("/api/v1/hf/accounts/ledgers?" + urllib.parse.urlencode(q9))
        if isinstance(rows, dict):
            rows = rows.get("items") if "items" in rows else ([] if not rows else None)
        if not isinstance(rows, list):
            raise RuntimeError("kucoin hf ledgers 응답 형식 오류")
        for r in rows:
            sy = _kc_ctx_symbol(r)
            if sy:
                syms.add(sy)
        if len(rows) < 200:
            break
        last = rows[-1].get("id") if isinstance(rows[-1], dict) else None
        if not last:
            raise RuntimeError("kucoin hf ledgers 다음 쪽 id 없음")
        time.sleep(PACE)
    else:
        raise RuntimeError(f"kucoin hf ledgers {KC_HF_LEDGER_PAGES}쪽 초과")
    out = []
    for sy in sorted(syms):
        last = None
        for _ in range(KC_HF_FILL_PAGES):
            time.sleep(PACE)
            q9 = {"symbol": sy, "startAt": s * 1000, "endAt": e * 1000, "limit": 100}
            if last:
                q9["lastId"] = last
            data = call("/api/v1/hf/fills?" + urllib.parse.urlencode(q9))
            items = data.get("items") if isinstance(data, dict) else None
            if items is None and data in ({}, None):
                items = []
            if not isinstance(items, list):
                raise RuntimeError(f"kucoin hf fills {sy} 응답 형식 오류")
            for r in items:
                b, _, q = str(r.get("symbol") or sy).partition("-")
                f9 = norm_fill("kucoin", f"{r.get('symbol') or sy}:{r.get('tradeId')}", r.get("createdAt"),
                               b, q, str(r.get("side", "")).lower(), r.get("price"), r.get("size"), r.get("fee"), r.get("feeCurrency"))
                if f9["id"] in have_ids:
                    continue
                have_ids.add(f9["id"])
                out.append(f9)
            if len(items) < 100:
                break
            last = data.get("lastId") or (items[-1].get("id") if isinstance(items[-1], dict) else None)
            if not last:
                raise RuntimeError(f"kucoin hf fills {sy} 다음 쪽 id 없음")
        else:
            raise RuntimeError(f"kucoin hf fills {sy} {KC_HF_FILL_PAGES}쪽 초과")
    return out


def _kc_hf_transient(e, msg: str) -> bool:
    if isinstance(e, urllib.error.HTTPError):
        return int(getattr(e, "code", 0) or 0) >= 500
    if isinstance(e, (urllib.error.URLError, TimeoutError, ConnectionError)) or type(e) is OSError:
        return True
    m9 = re.search(r"kucoin (\d{6})", msg or "")
    if m9:
        return m9.group(1).startswith("5") or m9.group(1) == "429000"
    return "쪽 초과" in (msg or "")


def _kucoin_hf_pass(call, st, t0: int, t1: int, classic: list) -> list:
    now9 = int(time.time())
    regular = t1 >= now9 - 3600
    if float(st.get("kc_hf_off") or 0) > now9:
        return []
    have_ids = {f["id"] for f in classic}
    gap9 = int(st.get("kc_hf_gap") or 0) if regular else 0
    h0 = min(int(t0), gap9) if gap9 else int(t0)
    out = []
    s9 = h0
    try:
        while s9 < t1:
            e9 = min(s9 + 6 * DAY, t1)
            out += _kucoin_hf_window(call, s9, e9, have_ids)
            s9 = e9
    except (RateLimited, SignatureExpired):
        if regular:
            st["kc_hf_gap"] = h0
        raise
    except Exception as e9:
        msg9 = _xm(repr(e9))
        if isinstance(e9, urllib.error.HTTPError):
            msg9 += " " + _xm(_err_body(e9)[:200])
        tr9 = _kc_hf_transient(e9, msg9) and not any(k9 in msg9 for k9 in KC_HF_DENY)
        if not regular:
            if tr9:
                raise RuntimeError(f"kucoin HF 체결(과거 창) 일시 실패 — 이 조각 다음 주기에 다시: {msg9[:160]}") from None
            log.warning("kucoin HF 체결(과거 창) 결정적 오류 — 이 조각의 HF 체결 생략(옛 계정 체결은 정상): %s", msg9[:160])
            return []
        if not tr9:
            st["kc_hf_off"] = now9 + DENY_COOL_SEC
            _recon_hold_clear(st, "kc_hf")
            if gap9:
                st["kc_hf_lost"] = {"from": int(h0), "to": int(t0), "at": now9}
                st.pop("kc_hf_gap", None)
                log.warning("★kucoin HF 밀린 구간 %s~%s 회수 불가(결정적 오류) — 그 구간 HF 체결은 빠질 수 있음(수동 확인)★: %s",
                            time.strftime("%Y-%m-%d", time.localtime(h0)), time.strftime("%Y-%m-%d", time.localtime(t0)), msg9[:160])
            log.warning("kucoin HF 체결 조회 거부·결정적 오류 — %d시간 쉼(옛 계정 체결은 정상): %s", DENY_COOL_SEC // 3600, msg9[:160])
            return []
        st["kc_hf_gap"] = h0
        st["partial"] = (str(st.get("partial")) + " · " if st.get("partial") else "") + "쿠코인 HF 체결 일시 실패(밀린 하한 보존 — 다음 주기 다시)"
        _recon_hold_clear(st, "kc_hf")
        log.warning("kucoin HF 체결 조회 일시 실패(다음 주기에 %s 부터 다시 — 옛 계정 체결은 정상 · 이번 주기 완주·잔고 승격 보류): %s",
                    time.strftime("%m-%d %H:%M", time.localtime(h0)), msg9[:160])
        return []
    if regular:
        _recon_hold_clear(st, "kc_hf")
        st.pop("kc_hf_off", None)
        st.pop("kc_hf_gap", None)
        on9 = int(st.get("kc_hf_on") or 0)
        if not on9:
            on9 = st["kc_hf_on"] = now9
        for f in out:
            if gap9 or f["ts"] < on9 * 1000:
                f["late"] = 1
        if out:
            log.info("kucoin HF 계정 체결 %d건(옛 계정 체결과 겹침 제외%s)", len(out), " · 밀린 구간 회수" if gap9 else "")
    return out


def fills_gate(env, st, t0: int, t1: int):
    key, sec = env["TJ_GATE_KEY"], env["TJ_GATE_SECRET"]

    @_clock_retry
    def call(params):
        _gov_prepare("api.gateio.ws", "/api/v4/spot/my_trades")
        qs = urllib.parse.urlencode(params)
        ts = str(_srv_ms("api.gateio.ws") // 1000)
        body_hash = hashlib.sha512(b"").hexdigest()
        path = "/api/v4/spot/my_trades"
        payload = f"GET\n{path}\n{qs}\n{body_hash}\n{ts}"
        sig = hmac.new(sec.encode(), payload.encode(), hashlib.sha512).hexdigest()
        return http_json(f"https://api.gateio.ws{path}?{qs}",
                         {"KEY": key, "Timestamp": ts, "SIGN": sig})

    fills = []
    s = t0
    while s < t1:
        e = min(s + 29 * DAY, t1)
        page = 1
        while True:
            rows = call({"from": s, "to": e, "limit": 1000, "page": page}) or []
            for r in rows:
                b, _, q = str(r.get("currency_pair") or "").partition("_")
                fills.append(norm_fill("gate", f"{r.get('currency_pair')}:{r.get('id')}",
                                       r.get("create_time_ms"),
                                       b, q, str(r.get("side", "")).lower(), r.get("price"),
                                       r.get("amount"), r.get("fee"), r.get("fee_currency")))
            time.sleep(PACE)
            if len(rows) < 1000:
                break
            page += 1
        s = e
    return fills


def _bithumb_caller(env):
    key, sec = env["TJ_BITHUMB_KEY"], env["TJ_BITHUMB_SECRET"]

    def call(path, params):
        _gov_prepare("api.bithumb.com", path)
        payload = {"access_key": key, "nonce": str(uuidlib.uuid4()),
                   "timestamp": _srv_ms("api.bithumb.com")}
        if params:
            raw_qs = "&".join(f"{k}={v}" for k, v in params.items())
            payload["query_hash"] = hashlib.sha512(raw_qs.encode()).hexdigest()
            payload["query_hash_alg"] = "SHA512"

        def b64u(b):
            return base64.urlsafe_b64encode(b).rstrip(b"=")
        h = b64u(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        p = b64u(json.dumps(payload).encode())
        sgn = b64u(hmac.new(sec.encode(), h + b"." + p, hashlib.sha256).digest())
        tok = (h + b"." + p + b"." + sgn).decode()
        qs = urllib.parse.urlencode(params) if params else ""
        return http_json(f"https://api.bithumb.com{path}" + (f"?{qs}" if qs else ""),
                         {"Authorization": f"Bearer {tok}"})

    return call


def fills_bithumb(env, st, t0: int, t1: int):
    call = _bithumb_caller(env)
    fills = []
    raw = {}
    regular = t1 >= time.time() - 3600
    pend = []
    reg9 = st.get("bt_reg") or {}
    order9 = sorted(("done", "cancel"), key=lambda q: 0 if (regular and isinstance(reg9.get(q), dict)) else 1)
    for st_q in order9:
        if regular and isinstance((st.get("bt_reg") or {}).get(st_q), dict):
            f9, ok9 = _bithumb_reg_catchup(call, st, st_q, t0, t1, raw, time.time() + BITHUMB_REG_BUDGET)
        else:
            try:
                f9, ok9 = _bithumb_orders_state(call, st_q, t0, t1, raw), True
            except _BithumbDeep as e:
                if not regular:
                    raise
                log.warning("bithumb 체결(%s) 정규 창 200페이지 초과 — 오름차순 재개형 따라잡기로 전환", st_q)
                st.setdefault("bt_reg", {})[st_q] = {"t0": int(t0)}
                f9b, ok9 = _bithumb_reg_catchup(call, st, st_q, t0, t1, raw, time.time() + BITHUMB_REG_BUDGET)
                f9 = e.fills + f9b
        fills.extend(f9)
        if not ok9:
            pend.append(st_q)
    if pend:
        st["partial"] = f"bithumb 체결 따라잡기 진행 중({', '.join(pend)} — 오름차순 재개형)"
    if t1 < time.time() - 3600:
        track = st.get("open_track")
        tracked = {f"bithumb:{u}" for u in track} if isinstance(track, dict) else set()
        return [f for f in fills if f["id"] not in tracked]
    return _bithumb_track(call, st, fills, raw, time.time())


BITHUMB_TRACK_MIN_AGE = 1800
BITHUMB_RESOLVE_MAX = 40
BITHUMB_NOTFOUND_DROP = 3


def _bithumb_open(call, max_pages: int = 20):
    out = []
    try:
        for page in range(1, max_pages + 1):
            rows = call("/v1/orders", {"limit": 100, "order_by": "desc", "page": page, "state": "wait"})
            if not isinstance(rows, list):
                return None
            out.extend(rows)
            if len(rows) < 100:
                return out
            time.sleep(PACE)
    except Exception as e:
        log.warning("bithumb 미체결 주문 조회 실패(이번 추적 판정 보류): %s", repr(e)[:140])
        return None
    return None


def _bithumb_track(call, st, fills, raw, now):
    import acct_norm
    track = st.get("open_track") if isinstance(st.get("open_track"), dict) else {}
    track = {str(k): dict(v) if isinstance(v, dict) else {} for k, v in track.items()}
    fseen = st.get("seen") or {}
    keep = []
    for f in fills:
        u = f["id"].split(":", 1)[1]
        if f["id"] in fseen:
            keep.append(f)
            continue
        if u in track or f["ts"] / 1000.0 < now - BITHUMB_TRACK_MIN_AGE:
            r9 = raw.get(u) or {}
            ent = track.setdefault(u, {"c": r9.get("created_at"), "m": r9.get("market")})
            ent["closed"] = True
        else:
            keep.append(f)
    oo = _bithumb_open(call)
    if oo is not None:
        ids = set()
        for o in oo:
            if isinstance(o, dict) and o.get("uuid"):
                u = str(o["uuid"])
                ids.add(u)
                if u not in track and f"bithumb:{u}" not in fseen:
                    track[u] = {"c": o.get("created_at"), "m": o.get("market")}
        for u, ent in track.items():
            if u not in ids:
                ent["closed"] = True
    out = []
    n = 0
    for u in sorted(track, key=lambda k: str((track[k] or {}).get("c") or "")):
        ent = track[u]
        if f"bithumb:{u}" in fseen:
            del track[u]
            continue
        if not ent.get("closed"):
            continue
        if n >= BITHUMB_RESOLVE_MAX:
            break
        n += 1
        try:
            o = call("/v1/order", {"uuid": u})
        except urllib.error.HTTPError as e:
            if e.code == 404:
                ent["nf"] = int(ent.get("nf") or 0) + 1
                if ent["nf"] >= BITHUMB_NOTFOUND_DROP:
                    r9 = raw.get(u)
                    if r9:
                        try:
                            out.append(_bithumb_fill(r9, None))
                        except RuntimeError as e9:
                            log.warning("bithumb 추적 주문 %s 목록 행 방출 실패: %s", u, e9)
                            continue
                    log.warning("bithumb 추적 주문 %s 단건 404 %d회 — 추적 종료%s", u, ent["nf"],
                                "(목록 행 방출)" if r9 else "(수동 확인 필요)")
                    del track[u]
                continue
            log.warning("bithumb 추적 주문 %s 단건 조회 실패(다음 주기 재시도): %s", u, repr(e)[:120])
            continue
        except Exception as e:
            log.warning("bithumb 추적 주문 %s 단건 조회 실패(다음 주기 재시도): %s", u, repr(e)[:120])
            continue
        finally:
            time.sleep(PACE)
        if not isinstance(o, dict) or str(o.get("uuid") or "") != u:
            log.warning("bithumb 추적 주문 %s 단건 응답 형식 오류 — 다음 주기 재시도", u)
            continue
        ent.pop("nf", None)
        state9 = str(o.get("state") or "")
        if state9 in ("wait", "watch"):
            ent["closed"] = False
            continue
        if state9 not in ("done", "cancel"):
            log.warning("bithumb 추적 주문 %s 상태 미상(%s) — 다음 주기 재시도", u, state9)
            continue
        try:
            ev = float(o.get("executed_volume"))
        except (TypeError, ValueError):
            log.warning("bithumb 추적 주문 %s 체결수량 파싱 실패 — 다음 주기 재시도", u)
            continue
        if ev > 0:
            merged = dict(raw.get(u) or {})
            merged.update(o)
            if merged.get("executed_funds") in (None, "") and isinstance(o.get("trades"), list) and o["trades"]:
                try:
                    if o.get("trades_count") is None or int(o["trades_count"]) == len(o["trades"]):
                        merged["executed_funds"] = str(sum(float(t["funds"]) for t in o["trades"]))
                except (KeyError, TypeError, ValueError):
                    pass
            fts = acct_norm.fill_ts(merged)
            try:
                out.append(_bithumb_fill(merged, fts * 1000 if fts else None))
            except RuntimeError as e9:
                log.warning("bithumb 추적 주문 %s 기장 보류(다음 주기 재시도): %s", u, e9)
                continue
        del track[u]
    st["open_track"] = track
    st["track_pending"] = sum(1 for e in track.values() if e.get("closed"))
    st["open_unknown"] = oo is None
    if out:
        log.info("bithumb 오래 걸린 주문 체결 확정 %d건 (추적 %d · 확정 대기 %d)", len(out), len(track), st["track_pending"])
    return keep + out


def _bithumb_fill(r, ts_ms):
    created = str(r.get("created_at") or "")
    if ts_ms is None:
        import datetime as _dt
        try:
            ts_ms = int(_dt.datetime.fromisoformat(created).timestamp()) * 1000
        except (ValueError, TypeError):
            ts_ms = int(time.time()) * 1000
    ev = r.get("executed_volume")
    mk = str(r.get("market") or "")
    q, _, b = mk.partition("-")
    funds = r.get("executed_funds")
    try:
        if funds is not None and float(funds) > 0:
            px = str(float(funds) / float(ev))
        else:
            avg = r.get("avg_price")
            if avg is not None and float(avg) > 0:
                px = str(float(avg))
            elif str(r.get("ord_type") or "") == "limit" and float(r.get("price") or 0) > 0:
                px = str(float(r.get("price")))
            else:
                raise RuntimeError(f"bithumb 주문 {r.get('uuid')} 단가 미상(정산총액·평균가 없음, ord_type="
                                   f"{r.get('ord_type')}) — 체결 창 완료 보류, 다음 주기 재조회")
    except (TypeError, ValueError, ZeroDivisionError) as e:
        raise RuntimeError(f"bithumb 주문 {r.get('uuid')} 단가 파싱 실패({e!r}) — 체결 창 완료 보류") from None
    side = "buy" if str(r.get("side")) == "bid" else "sell"
    f9 = norm_fill("bithumb", r.get("uuid"), ts_ms, b, q, side,
                   px, ev, r.get("paid_fee"), q)
    f9["funds"] = str(funds or "")
    return f9


_BITHUMB_ASC_CACHE = {}
BITHUMB_ASC_CACHE_SEC = 3600
BITHUMB_ASC_SCAN_MAX = 200


def _bithumb_row_ts(r, dflt):
    try:
        import datetime as _dt
        return int(_dt.datetime.fromisoformat(str(r.get("created_at") or "")).timestamp())
    except (ValueError, TypeError):
        return dflt


def _bithumb_asc_pager(call, st_q):
    cache = _BITHUMB_ASC_CACHE.setdefault(st_q, {})
    now9 = time.time()
    for p9 in [p for p, v in cache.items() if now9 - v[3] > BITHUMB_ASC_CACHE_SEC]:
        cache.pop(p9, None)
    got = {}

    def page_rows(p):
        if p in got:
            return got[p]
        rows = call("/v1/orders", {"limit": 100, "order_by": "asc", "page": p, "state": st_q})
        if not isinstance(rows, list):
            raise RuntimeError(f"bithumb orders({st_q}, asc p{p}) 응답이 목록이 아님: {str(rows)[:120]}")
        time.sleep(PACE)
        got[p] = rows
        if rows:
            cache[p] = (_bithumb_row_ts(rows[0], 0), _bithumb_row_ts(rows[-1], 0), len(rows), time.time())
        else:
            cache[p] = (None, None, 0, time.time())
        return rows

    def meta(p):
        v = cache.get(p)
        if v is None:
            page_rows(p)
            v = cache[p]
        return v

    return page_rows, meta


def _bithumb_asc_start(meta, st_q, t0, deadline=None):
    lo, hi = 0, 1
    while True:
        if deadline is not None and time.time() >= deadline:
            return None
        m = meta(hi)
        if m[2] == 0 or (m[1] is not None and m[1] >= t0):
            break
        lo, hi = hi, hi * 2
        if hi > 1 << 20:
            raise RuntimeError(f"bithumb orders({st_q}) 오름차순 탐색 상한 초과")
    while hi - lo > 1:
        if deadline is not None and time.time() >= deadline:
            return None
        mid = (lo + hi) // 2
        m = meta(mid)
        if m[2] == 0 or (m[1] is not None and m[1] >= t0):
            hi = mid
        else:
            lo = mid
    return max(1, hi - 1)


def _bithumb_asc_page(rows, t0, t1, raw=None):
    fills, past = [], False
    for r in rows:
        cts = _bithumb_row_ts(r, None)
        if cts is None:
            continue
        if cts > t1:
            past = True
            continue
        if cts < t0:
            continue
        ev = r.get("executed_volume")
        if not ev or float(ev) <= 0:
            continue
        fills.append(_bithumb_fill(r, cts * 1000))
        if raw is not None and r.get("uuid"):
            raw[str(r["uuid"])] = r
    return fills, past


def _bithumb_orders_asc(call, st_q, t0, t1, raw=None):
    page_rows, meta = _bithumb_asc_pager(call, st_q)
    fills, page, n = [], _bithumb_asc_start(meta, st_q, t0), 0
    while True:
        if n >= BITHUMB_ASC_SCAN_MAX:
            raise RuntimeError(f"bithumb orders({st_q}) 창 안 {BITHUMB_ASC_SCAN_MAX}페이지 초과 — 다음 주기 재시도")
        rows = page_rows(page)
        n += 1
        if not rows:
            break
        f9, past = _bithumb_asc_page(rows, t0, t1, raw)
        fills.extend(f9)
        if past or len(rows) < 100:
            break
        page += 1
    return fills


BITHUMB_EXT_STATES = ("done", "cancel")


def _bithumb_ext_fills(call, st, ext, a, b, deadline, emit, save):
    sc = ext.get("bt_scan")
    if not isinstance(sc, dict) or int(sc.get("a") or -1) != int(a) or int(sc.get("b") or -1) != int(b) \
            or not isinstance(sc.get("st"), dict):
        sc = ext["bt_scan"] = {"a": int(a), "b": int(b), "st": {}}
        save()
    track = st.get("open_track")
    tracked = {f"bithumb:{u}" for u in track} if isinstance(track, dict) else set()
    for st_q in BITHUMB_EXT_STATES:
        cur = sc["st"].setdefault(st_q, {})
        if cur.get("fin"):
            continue
        page_rows, meta = _bithumb_asc_pager(call, st_q)
        if not cur.get("page"):
            p0 = _bithumb_asc_start(meta, st_q, int(a), deadline)
            if p0 is None:
                return False
            cur.update(page=int(p0), p0=int(p0), n=0)
            save()
            page = int(p0)
        else:
            page = max(int(cur.get("p0") or 1), int(cur["page"]) - 1)
        while True:
            if time.time() >= deadline:
                return False
            rows = page_rows(page)
            if not rows:
                cur["fin"] = True
                save()
                break
            raw9 = {}
            f9, past = _bithumb_asc_page(rows, int(a), int(b), raw9)
            f9 = [f for f in f9 if f["id"] not in tracked]
            rt9 = ext.setdefault("bt_rt", {})
            try:
                f9 = _bithumb_retime(call, f9, raw9, rt9, deadline)
            except _BithumbBudget:
                save()
                return False
            if f9:
                emit(f9)
            if len(rt9) > BITHUMB_RT_KEEP:
                ext["bt_rt"] = dict(list(rt9.items())[-BITHUMB_RT_KEEP:])
            ts9 = [t for t in (_bithumb_row_ts(r, None) for r in rows) if t is not None]
            cur["page"] = page + 1
            cur["n"] = int(cur.get("n") or 0) + 1
            if ts9:
                cur["ts"] = max(int(cur.get("ts") or 0), max(ts9))
            if past or len(rows) < 100:
                cur["fin"] = True
                save()
                break
            save()
            page += 1
    return all((sc["st"].get(q) or {}).get("fin") for q in BITHUMB_EXT_STATES)


BITHUMB_RT_KEEP = 400


class _BithumbBudget(RuntimeError):
    pass


def _bithumb_retime(call, fills, raw, cache=None, deadline=None):
    import acct_norm
    cache = {} if cache is None else cache
    out = []
    for f in fills:
        u = f["id"].split(":", 1)[1]
        r = raw.get(u) or {}
        if str(r.get("ord_type") or "") != "limit":
            out.append(f)
            continue
        if u not in cache:
            if deadline is not None and time.time() >= deadline:
                raise _BithumbBudget("bithumb 과거 창 체결 시각 확인 — 시간 예산 소진")
            try:
                o = call("/v1/order", {"uuid": u})
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
                o = None
            finally:
                time.sleep(PACE)
            fts = None
            if isinstance(o, dict) and str(o.get("uuid") or "") == u and str(o.get("state") or "") in ("done", "cancel"):
                merged = dict(r)
                merged.update(o)
                fts = acct_norm.fill_ts(merged)
                if fts and int(fts) * 1000 != int(f["ts"]):
                    try:
                        f2 = _bithumb_fill(merged, int(fts) * 1000)
                    except RuntimeError:
                        f2 = None
                    if f2 is None or _dstr(f2["qty"]) != _dstr(f["qty"]):
                        fts = None
            cache[u] = int(fts) * 1000 if fts else 0
        if cache[u] and int(cache[u]) != int(f["ts"]):
            f = dict(f, ts=int(cache[u]))
        out.append(f)
    return out


def _bithumb_ext_part(ext):
    sc = ext.get("bt_scan")
    if not isinstance(sc, dict) or int(sc.get("b") or -1) != int(ext.get("fills_from") or 0):
        return 0
    a9, b9 = int(sc.get("a") or 0), int(sc.get("b") or 0)
    tot = 0
    for q in BITHUMB_EXT_STATES:
        c9 = (sc.get("st") or {}).get(q) or {}
        tot += (b9 - a9) if c9.get("fin") else max(0, min(b9, int(c9.get("ts") or 0)) - a9)
    return tot // len(BITHUMB_EXT_STATES)


BITHUMB_REG_BUDGET = 120


class _BithumbDeep(RuntimeError):

    def __init__(self, msg, fills):
        super().__init__(msg)
        self.fills = fills


def _bithumb_reg_catchup(call, st, st_q, t0, t1, raw, deadline):
    reg = st.setdefault("bt_reg", {})
    cur = reg.get(st_q)
    if not isinstance(cur, dict) or not cur.get("t0") or int(t0) < int(cur.get("t0") or 0) - 60:
        cur = reg[st_q] = {"t0": int(t0)}
    page_rows, meta = _bithumb_asc_pager(call, st_q)
    lo9 = int(cur["t0"])
    if not cur.get("page"):
        p0 = _bithumb_asc_start(meta, st_q, lo9, deadline)
        if p0 is None:
            return [], False
        cur.update(page=int(p0), p0=int(p0))
        page = int(p0)
    else:
        page = max(int(cur.get("p0") or 1), int(cur["page"]) - 1)
    out = []
    while True:
        if time.time() >= deadline:
            return out, False
        rows = page_rows(page)
        if not rows:
            reg.pop(st_q, None)
            return out, True
        f9, past = _bithumb_asc_page(rows, lo9, int(t1), raw)
        out.extend(f9)
        cur["page"] = page + 1
        if past or len(rows) < 100:
            reg.pop(st_q, None)
            return out, True
        page += 1


def _bithumb_orders_state(call, st_q, t0, t1, raw=None):
    if t1 < time.time() - 3600:
        return _bithumb_orders_asc(call, st_q, t0, t1, raw)
    fills = []
    page = 1
    while page <= 200:
        rows = call("/v1/orders", {"limit": 100, "order_by": "desc", "page": page,
                                   "state": st_q})
        if not isinstance(rows, list):
            raise RuntimeError(f"bithumb orders({st_q}) 응답이 목록이 아님: {str(rows)[:120]}")
        if not rows:
            break
        stop = False
        for r in rows:
            created = str(r.get("created_at") or "")
            try:
                import datetime as _dt
                cts = int(_dt.datetime.fromisoformat(created).timestamp())
            except (ValueError, TypeError):
                cts = t1
            if cts < t0:
                stop = True
                break
            ev = r.get("executed_volume")
            if not ev or float(ev) <= 0:
                continue
            fills.append(_bithumb_fill(r, cts * 1000))
            if raw is not None and r.get("uuid"):
                raw[str(r["uuid"])] = r
        if stop:
            break
        time.sleep(PACE)
        page += 1
    else:
        raise _BithumbDeep(f"bithumb orders({st_q}) 200페이지 초과 — 다음 주기 재시도", fills)
    return fills


CV_QUOTE_PREF = ("USDT", "USDC", "FDUSD", "USD", "USDG", "USDE", "DAI", "BUSD", "TUSD", "KRW", "BTC", "ETH", "BNB")
CV_DENY = ("retCode=10005", "retCode=10003", "retCode=10004", "okx 50120", "okx 50030", "okx 50125", "okx 50119",
           '"code":-2015', '"code":-1002',
           "kucoin 400007", "kucoin 400006", "HTTPError 404", "HTTP 404")


def _cv_fill(ex, cid, ts_ms, from_ccy, from_amt, to_ccy, to_amt):
    from decimal import Decimal, InvalidOperation
    f9, t9 = str(from_ccy or "").strip().upper(), str(to_ccy or "").strip().upper()
    try:
        fa, ta = Decimal(str(from_amt)), Decimal(str(to_amt))
        tsv = int(float(ts_ms))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not cid or not f9 or not t9 or f9 == t9 or not (fa.is_finite() and ta.is_finite()) or fa <= 0 or ta <= 0 or tsv <= 0:
        return None
    if tsv < 10 ** 12:
        tsv *= 1000
    rank = {q: i for i, q in enumerate(CV_QUOTE_PREF)}
    if t9 in rank and (f9 not in rank or rank[t9] <= rank[f9]):
        base, bq, quote, qq, side = f9, fa, t9, ta, "sell"
    elif f9 in rank:
        base, bq, quote, qq, side = t9, ta, f9, fa, "buy"
    else:
        base, bq, quote, qq, side = f9, fa, t9, ta, "sell"
    px = qq / bq
    fl = norm_fill(ex, f"cv:{cid}", tsv, base, quote, side, format(px, "f"), format(bq, "f"), 0, "")
    fl["src"] = "convert"
    fl["cv"] = {"from": f9, "from_amt": format(fa, "f"), "to": t9, "to_amt": format(ta, "f")}
    return fl


def convert_binance(env, t0: int, t1: int):
    call = _binance_caller(env)
    out = []
    s = int(t0)
    while s < t1:
        e = min(s + 30 * DAY - 1, int(t1))
        start = s * 1000
        for _pg in range(50):
            d = call("/sapi/v1/convert/tradeFlow", {"startTime": start, "endTime": e * 1000, "limit": 1000})
            rows = d.get("list") if isinstance(d, dict) else None
            if not isinstance(rows, list):
                raise RuntimeError(f"binance convert 응답 형식 오류: {str(d)[:100]}")
            for r in rows:
                if not isinstance(r, dict) or str(r.get("orderStatus") or "").upper() != "SUCCESS":
                    continue
                f9 = _cv_fill("binance", r.get("orderId") or r.get("quoteId"), r.get("createTime"), r.get("fromAsset"),
                              r.get("fromAmount"), r.get("toAsset"), r.get("toAmount"))
                if f9 is None:
                    raise RuntimeError("binance convert SUCCESS 필드 누락/형식 오류")
                out.append(f9)
            time.sleep(PACE)
            if not d.get("moreData") or not rows:
                break
            mx = max(int(float(r.get("createTime") or 0)) for r in rows if isinstance(r, dict))
            if mx < start:
                raise RuntimeError("binance convert 페이지 시각 미전진")
            start = mx + 1
        else:
            raise RuntimeError("binance convert 30일 창 50페이지 초과")
        s = e + 1
    return out


def convert_okx(env, t0: int, t1: int):
    out, got = [], set()
    after = ""
    for _pg in range(200):
        p = {"limit": 100}
        if after:
            p["after"] = after
        rows = _okx_get(env, "/api/v5/asset/convert/history", p)
        if not isinstance(rows, list):
            raise RuntimeError("okx convert data 형식 오류")
        if not rows:
            break
        n_new = 0
        for r in rows:
            if not isinstance(r, dict):
                continue
            tid = str(r.get("tradeId") or r.get("clTReqId") or "")
            if not tid or tid in got:
                continue
            got.add(tid)
            n_new += 1
            if str(r.get("state") or "").lower() not in ("fullyfilled", "filled", "success"):
                continue
            if int(float(r.get("ts") or 0)) < t0 * 1000:
                continue
            side = str(r.get("side") or "").lower()
            if side not in ("buy", "sell"):
                raise RuntimeError("okx convert side 누락/형식 오류")
            if side == "buy":
                f9 = _cv_fill("okx", tid, r.get("ts"), r.get("quoteCcy"), r.get("fillQuoteSz"), r.get("baseCcy"), r.get("fillBaseSz"))
            else:
                f9 = _cv_fill("okx", tid, r.get("ts"), r.get("baseCcy"), r.get("fillBaseSz"), r.get("quoteCcy"), r.get("fillQuoteSz"))
            if f9 is None:
                raise RuntimeError("okx convert 체결 필드 누락/형식 오류")
            out.append(f9)
        oldest = min(int(float(r.get("ts") or 0)) for r in rows if isinstance(r, dict)) if rows else 0
        time.sleep(PACE)
        if oldest // 1000 <= t0 or len(rows) < 100:
            break
        if after and n_new == 0:
            raise RuntimeError("okx convert 페이지 시각 미전진")
        after = str(oldest + 1)
    else:
        raise RuntimeError("okx convert 200페이지 초과")
    return out


class _PartialConvertRows(list):
    def __init__(self, rows, error):
        super().__init__(rows)
        self.error = error


def convert_bybit(env, t0: int, t1: int):
    out, got, errs = [], set(), []
    invalid = set()
    try:
        for idx in range(1, 101):
            res = _bybit_get(env, "/v5/asset/exchange/query-convert-history", {"index": idx, "limit": 100})
            rows = res.get("list")
            if not isinstance(rows, list):
                raise RuntimeError("bybit convert list 형식 오류")
            ts9 = []
            for r in rows:
                if not isinstance(r, dict):
                    continue
                tid = str(r.get("exchangeTxId") or "")
                try:
                    ts9.append(int(float(r.get("createdAt") or 0)))
                except (TypeError, ValueError):
                    pass
                if not tid or tid in got or str(r.get("exchangeStatus") or "").lower() != "success":
                    continue
                if int(float(r.get("createdAt") or 0)) < t0 * 1000:
                    continue
                f9 = _cv_fill("bybit", tid, r.get("createdAt"), r.get("fromCoin"), r.get("fromAmount"),
                              r.get("toCoin"), r.get("toAmount"))
                if f9:
                    got.add(tid)
                    out.append(f9)
                else:
                    invalid.add(tid)
            time.sleep(PACE)
            if len(rows) < 100:
                break
            if len(ts9) >= 2 and ts9[0] >= ts9[-1] and ts9[-1] < t0 * 1000:
                break
    except Exception as e:
        errs.append(_xm(repr(e))[:160])
    try:
        cursor, seen_c = "", set()
        for _pg in range(100):
            p = {"limit": 50}
            if cursor:
                p["cursor"] = cursor
            res = _bybit_get(env, "/v5/asset/exchange/order-record", p)
            rows = res.get("orderBody")
            if not isinstance(rows, list):
                raise RuntimeError("bybit order-record orderBody 형식 오류")
            old9 = False
            for r in rows:
                if not isinstance(r, dict):
                    continue
                tid = str(r.get("exchangeTxId") or "")
                try:
                    tsr = int(float(r.get("createdTime") or 0))
                except (TypeError, ValueError):
                    continue
                tsr_ms = tsr * 1000 if tsr < 10 ** 12 else tsr
                if tsr_ms < t0 * 1000:
                    old9 = True
                    continue
                if not tid or tid in got:
                    continue
                f9 = _cv_fill("bybit", tid, tsr_ms, r.get("fromCoin"), r.get("fromAmount"), r.get("toCoin"), r.get("toAmount"))
                if f9:
                    got.add(tid)
                    out.append(f9)
                else:
                    invalid.add(tid)
            time.sleep(PACE)
            cursor = str(res.get("nextPageCursor") or "")
            if not rows or not cursor or old9:
                break
            if cursor in seen_c:
                raise RuntimeError("bybit order-record 커서 순환")
            seen_c.add(cursor)
    except Exception as e:
        errs.append(_xm(repr(e))[:160])
    if len(errs) == 2:
        raise RuntimeError("bybit 전환 두 경로 모두 실패: " + " | ".join(errs))
    if invalid - got:
        raise RuntimeError("bybit convert 체결 필드 누락/형식 오류")
    if errs:
        log.warning("bybit 전환 내역 한 경로 실패(다른 경로 결과만 반영): %s", errs[0])
        return _PartialConvertRows(out, errs[0])
    return out


def convert_binance_dust(env, t0: int, t1: int):
    call = _binance_caller(env)
    out = []
    s = int(t0)
    while s < t1:
        e = min(s + 90 * DAY - 1, int(t1))
        d = call("/sapi/v1/asset/dribblet", {"startTime": s * 1000, "endTime": e * 1000})
        if not isinstance(d, dict):
            raise RuntimeError("binance dribblet 응답 형식 오류")
        rows = d.get("userAssetDribblets")
        if rows is None and int(d.get("total") or 0) == 0:
            rows = []
        if not isinstance(rows, list):
            raise RuntimeError("binance dribblet 목록 누락/형식 오류")
        if int(d.get("total") or 0) > len(rows) and len(rows) >= 100:
            raise RuntimeError("binance dribblet 조각 하나에 100건 초과(목록 상한) — 조각 완료 보류")
        for g in rows:
            if not isinstance(g, dict):
                continue
            for det in g.get("userAssetDribbletDetails") or []:
                if not isinstance(det, dict):
                    continue
                fa = str(det.get("fromAsset") or "").upper()
                tid = det.get("transId") or g.get("transId")
                ta = str(det.get("targetAsset") or g.get("targetAsset") or "BNB").strip().upper() or "BNB"
                f9 = _cv_fill("binance", f"dust:{tid}:{fa}", det.get("operateTime") or g.get("operateTime"), fa, det.get("amount"),
                              ta, det.get("transferedAmount"))
                if f9 is None:
                    raise RuntimeError("binance dribblet 세부 필드 누락/형식 오류")
                f9["cv"]["kind"] = "dust"
                out.append(f9)
        time.sleep(PACE)
        s = e + 1
    return out


@_clock_retry
def _kucoin_call(env, path_with_qs):
    _gov_prepare("api.kucoin.com", path_with_qs.split("?", 1)[0])
    key, sec, pph = env["TJ_KUCOIN_KEY"], env["TJ_KUCOIN_SECRET"], env["TJ_KUCOIN_PASSPHRASE"]
    ts = str(_srv_ms("api.kucoin.com"))
    sig = base64.b64encode(hmac.new(sec.encode(), (ts + "GET" + path_with_qs).encode(), hashlib.sha256).digest()).decode()
    pph_sig = base64.b64encode(hmac.new(sec.encode(), pph.encode(), hashlib.sha256).digest()).decode()
    d = http_json("https://api.kucoin.com" + path_with_qs,
                  {"KC-API-KEY": key, "KC-API-SIGN": sig, "KC-API-TIMESTAMP": ts,
                   "KC-API-PASSPHRASE": pph_sig, "KC-API-KEY-VERSION": "2"})
    if not isinstance(d, dict) or d.get("code") != "200000":
        raise RuntimeError(f"kucoin {(d or {}).get('code') if isinstance(d, dict) else '?'} "
                           f"{_xm((d or {}).get('msg')) if isinstance(d, dict) else _xm(str(d)[:80])}")
    return d.get("data")


def convert_kucoin(env, t0: int, t1: int):
    out, got = [], set()
    s = int(t0)
    while s < t1:
        e = min(s + 30 * DAY, int(t1))
        page = 1
        while True:
            qs = urllib.parse.urlencode({"startAt": s * 1000, "endAt": e * 1000, "page": page, "pageSize": 50})
            data = _kucoin_call(env, f"/api/v1/convert/order/history?{qs}")
            if not isinstance(data, dict) or not isinstance(data.get("items"), list):
                raise RuntimeError("kucoin convert items 누락/형식 오류")
            for r in data["items"]:
                if not isinstance(r, dict) or str(r.get("status") or "").upper() != "SUCCESS":
                    continue
                f9 = _cv_fill("kucoin", r.get("orderId") or r.get("clientOrderId"), r.get("orderTime") or r.get("createdAt"),
                              r.get("fromCurrency"), r.get("fromCurrencySize"), r.get("toCurrency"), r.get("toCurrencySize"))
                if f9 is None:
                    raise RuntimeError("kucoin convert SUCCESS 필드 누락/형식 오류")
                if f9["id"] in got:
                    continue
                got.add(f9["id"])
                out.append(f9)
            time.sleep(PACE)
            if page >= int(data.get("totalPage") or 1) or not data["items"]:
                break
            page += 1
            if page > 200:
                raise RuntimeError("kucoin convert 200페이지 초과")
        s = e
    return out


def convert_gate(env, t0: int, t1: int):
    out, got = [], set()
    for page in range(1, 51):
        rows = _gate_get(env, "/api/v4/flash_swap/orders", {"status": 1, "limit": 100, "page": page})
        if not isinstance(rows, list):
            raise RuntimeError("gate flash_swap 응답 형식 오류")
        old9 = False
        for r in rows:
            if not isinstance(r, dict):
                continue
            try:
                ts9 = int(float(r.get("create_time") or 0))
            except (TypeError, ValueError):
                raise RuntimeError("gate flash_swap create_time 형식 오류") from None
            ts_ms = ts9 * 1000 if ts9 < 10 ** 12 else ts9
            if ts_ms < t0 * 1000:
                old9 = True
                continue
            if str(r.get("status")) not in ("1", "success", "SUCCESS"):
                continue
            tid = str(r.get("id") or "")
            if not tid or tid in got:
                continue
            f9 = _cv_fill("gate", tid, ts_ms, r.get("sell_currency"), r.get("sell_amount"), r.get("buy_currency"), r.get("buy_amount"))
            if f9 is None:
                raise RuntimeError("gate flash_swap 필드 누락/형식 오류")
            got.add(tid)
            out.append(f9)
        time.sleep(PACE)
        if old9 or len(rows) < 100:
            return out
    raise RuntimeError("gate flash_swap 50페이지 초과")


CONVERT_FETCHERS = {"binance": convert_binance, "okx": convert_okx, "bybit": convert_bybit,
                    "kucoin": convert_kucoin, "gate": convert_gate}
CONVERT_EXTRA = {"binance": (("dust", convert_binance_dust),)}
CONVERT_LABEL = {"cv": "간편전환", "cv_dust": "소액 자산 BNB 전환"}
CV_RETRY_SEC = 1800
DUST_IDLE_SEC = 24 * 3600


def convert_rows(ex, env, fst: dict, now: int, window: int) -> list:
    out = []
    fn = CONVERT_FETCHERS.get(ex)
    if fn is not None:
        out += _convert_src(ex, "cv", fn, env, fst, now, window)
    for key9, fn9 in CONVERT_EXTRA.get(ex, ()):
        out += _convert_src(ex, "cv_" + key9, fn9, env, fst, now, window)
    if ex == "binance" and out:
        fst["extra_bases"] = sorted(set(fst.get("extra_bases") or []) | {f["base"] for f in out if f.get("base")}
                                    | {f["quote"] for f in out if f.get("quote")})
    return out


def _convert_src(ex, key, fn, env, fst: dict, now: int, window: int) -> list:
    cv = fst.setdefault(key, {})
    label = CONVERT_LABEL.get(key, key)
    ck9 = f"{ex}:{key}"
    hk9 = "cv:" + key
    unres9 = hk9 in (fst.get("hold_since") or {})
    if time.time() < max(float(cv.get("off_until") or 0), float(_CV_OFF.get(ck9, 0) or 0) if _COOL_ON[0] else 0.0):
        if unres9:
            _recon_hold(fst, hk9, now, f"{label} 조회 실패 뒤 재시도 대기")
        return []
    if key == "cv_dust" and cv.get("bf") and now - int(cv.get("until") or 0) < DUST_IDLE_SEC \
            and not (fst.get("bn_last_dirty") or []) and not unres9:
        return []
    lo = int(now - window)
    t0 = lo if not cv.get("bf") else max(lo, min(int(now - 3 * DAY), int(cv.get("until") or lo)))
    tg9 = bf_engine.SINCE.target(ex)
    ext_lo = int(tg9) if tg9 and int(tg9) < lo else None
    if ext_lo is not None and int(cv.get("bf_lo") or lo) > ext_lo + 60:
        t0 = ext_lo
    try:
        rows = fn(env, t0, now)
    except RateLimited:
        _recon_hold(fst, hk9, now, f"{label} 조회 레이트 제한")
        return []
    except Exception as e:
        msg = _xm(repr(e))[:200]
        deny = any(k in msg for k in _DENY_SIGS + CV_DENY)
        cv["off_until"] = time.time() + (DENY_COOL_SEC if deny else CV_RETRY_SEC)
        _CV_OFF[ck9] = cv["off_until"]
        cv["err"], cv["err_at"] = msg, int(now)
        held9 = False
        if deny:
            _recon_hold_clear(fst, hk9)
        else:
            held9 = _recon_hold(fst, hk9, now, f"{label} 조회 실패")
        log.warning("%s %s 내역 조회 생략(%s — 체결·잔고 수집은 계속%s): %s", ex, label,
                    "권한 없음 · 6h 뒤 재시도" if deny else "30분 뒤 재시도", " · 성공 때까지 잔고 대사 보류" if held9 else "", msg[:160])
        return []
    if isinstance(rows, _PartialConvertRows):
        msg = rows.error
        deny = any(k in msg for k in _DENY_SIGS + CV_DENY)
        cv["off_until"] = time.time() + (DENY_COOL_SEC if deny else CV_RETRY_SEC)
        _CV_OFF[ck9] = cv["off_until"]
        cv["err"], cv["err_at"] = msg, int(now)
        if deny:
            _recon_hold_clear(fst, hk9)
        else:
            _recon_hold(fst, hk9, now, f"{label} 일부만 조회")
        return list(rows)
    if not cv.get("bf"):
        log.info("%s %s 과거분 백필 완료: %d건 (창 %s~)", ex, label, len(rows), time.strftime("%Y-%m-%d", time.gmtime(t0)))
    cv["bf"] = cv.get("bf") or int(now)
    if ext_lo is not None and t0 == ext_lo:
        cv["bf_lo"] = int(ext_lo)
        log.info("%s %s 과거 창 확장: %d건 (%s~)", ex, label, len(rows), time.strftime("%Y-%m-%d", time.gmtime(ext_lo)))
    cv["until"] = int(now)
    cv.pop("err", None)
    cv.pop("off_until", None)
    _CV_OFF.pop(ck9, None)
    _recon_hold_clear(fst, hk9)
    return rows


def _http_json_err(url, headers=None, data=None, method=None, timeout=20):
    try:
        return http_json(url, headers, data, method, timeout)
    except urllib.error.HTTPError as e:
        try:
            body = _err_body(e)
            try:
                body = json.dumps(json.loads(body), separators=(",", ":"))
            except ValueError:
                pass
            body = body[:300]
        except Exception:
            body = ""
        raise RuntimeError(f"HTTP {e.code}: {_xm(body)}") from e


_DENY_SIGS = ('"code":-3003', '"code":-11001', '"code":-2015', '"code":-1002',
              'USER_NOT_FOUND', 'HTTP 401', 'HTTP 403', 'HTTPError 401', 'HTTPError 403')
DENY_COOL_SEC = 6 * 3600


COOL_PATH_NAME = "exf_cooldown.json"
_COOL_ON = [False]
_COOL_MAPS = {}
_COOL_LOCK = threading.Lock()


class _CoolMap(dict):

    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        _COOL_MAPS[kind] = self

    def __setitem__(self, k, v):
        super().__setitem__(k, v)
        _cool_save()

    def pop(self, k, *d):
        had = k in self
        v = super().pop(k, *d)
        if had:
            _cool_save()
        return v


def _cool_path():
    return os.path.join(common.STATE_DIR, COOL_PATH_NAME)


def _cool_save():
    if not _COOL_ON[0]:
        return
    with _COOL_LOCK:
        now = time.time()
        out = {}
        for kind, m in _COOL_MAPS.items():
            d9 = {}
            for k, v in list(m.items()):
                try:
                    if float(v) > now:
                        d9["|".join(k) if isinstance(k, tuple) else str(k)] = float(v)
                except (TypeError, ValueError):
                    continue
            out[kind] = d9
        try:
            common.atomic_write_json(_cool_path(), out)
        except Exception as e:
            log.warning("쿨다운 기록 실패(메모리 값은 유지): %s", common.safe_err(e)[:120])


def _cool_restore():
    now = time.time()
    try:
        d = common.read_json(_cool_path(), {}) if os.path.exists(_cool_path()) else {}
    except SystemExit:
        d = {}
    n = 0
    for kind, m in _COOL_MAPS.items():
        dict.clear(m)
        src = d.get(kind) if isinstance(d, dict) else None
        for k, v in (src.items() if isinstance(src, dict) else ()):
            try:
                if float(v) <= now:
                    continue
            except (TypeError, ValueError):
                continue
            kk = tuple(k.split("|", 1)) if kind == "bal" and "|" in k else k
            dict.__setitem__(m, kk, float(v))
            n += 1
    _COOL_ON[0] = True
    if n:
        log.info("쿨다운 복원 %d건(권한 거부·레이트 제한 — 만료 후 자동 재시도)", n)
    return n


_BAL_SRC_OFF = _CoolMap("bal")
_BAL_SRC_HAD_PATH = "exf_balance_sources.json"
_BAL_SRC_HAD = None


def _bal_src_had_load():
    global _BAL_SRC_HAD
    if _BAL_SRC_HAD is None:
        path = os.path.join(common.STATE_DIR, _BAL_SRC_HAD_PATH)
        try:
            d = common.read_json(path, {})
        except SystemExit as e:
            raise RuntimeError(f"잔고 소스 메타 손상 — 잔고 발행 보류: {e}") from None
        if not isinstance(d, dict):
            raise RuntimeError("잔고 소스 메타 형식 오류 — 잔고 발행 보류")
        _BAL_SRC_HAD = d
    return _BAL_SRC_HAD


class _Bal(dict):

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.debts = {}
        self.sources = []
        self.by_src = {}
        self.loans = []


def _debt_add(o, ex, src, asset, v):
    _debt_warn(ex, src, asset, v)
    if v < 0 and asset and isinstance(getattr(o, "debts", None), dict):
        k = str(asset).upper()
        o.debts[k] = o.debts.get(k, 0) + v


def _sub_bal(ex, src, fn, out, extra_deny=(), lenient=False):
    had = _bal_src_had_load()
    key = f"{ex}:{src}"

    def _omit_or_hold(reason):
        if had.get(key):
            _invalidate_balance_snapshot(ex)
            raise RuntimeError(f"{ex} {src}: 직전 실보유 소스 조회 불가({reason}) — 부분 잔고 발행 보류")

    if time.time() < _BAL_SRC_OFF.get((ex, src), 0):
        _omit_or_hold("쿨다운")
        return
    local = _Bal()
    try:
        fn(local)
    except Exception as e:
        msg = _xm(repr(e))
        deny = any(k in msg for k in _DENY_SIGS + tuple(extra_deny))
        if deny or lenient:
            _BAL_SRC_OFF[(ex, src)] = time.time() + (DENY_COOL_SEC if deny else 1800)
            if lenient:
                log.warning("%s %s 잔고 소스 제외(%s — 그 밖 잔고·대사는 계속): %s", ex, src,
                            "권한 없음/미개설 · 6h 뒤 재시도" if deny else "조회 실패 · 30분 뒤 재시도", msg[:140])
            else:
                log.error("★%s %s 잔고 소스 6h 제외(미개설/권한 거부/IP 불일치) — 만료 후 자동 재시도: %s★",
                          ex, src, msg[:140])
            _omit_or_hold("거부" if deny else "조회 실패")
            return
        raise
    has9 = bool(local) or bool(local.debts)
    if had.get(key) != has9:
        had[key] = has9
        common.atomic_write_json(os.path.join(common.STATE_DIR, _BAL_SRC_HAD_PATH), had)
    for k9, v9 in local.items():
        out[k9] = out.get(k9, 0) + v9
    if isinstance(getattr(out, "debts", None), dict):
        for k9, v9 in local.debts.items():
            out.debts[k9] = out.debts.get(k9, 0) + v9
    if isinstance(getattr(out, "loans", None), list):
        out.loans.extend(local.loans)
    if isinstance(getattr(out, "sources", None), list):
        out.sources.append(src)
    if isinstance(getattr(out, "by_src", None), dict):
        out.by_src[src] = dict(local)


_DEBT_SEEN = {}


def _debt_warn(ex, src, asset, v):
    k = (ex, src, str(asset))
    prev = _DEBT_SEEN.get(k)
    now = time.time()
    if prev is not None:
        pv, pt = prev
        same = abs(v - pv) <= max(abs(pv) * 0.01, 1e-12)
        if same and now - pt < 3600:
            return
    _DEBT_SEEN[k] = (v, now)
    log.info("★%s %s 부채 감지: %s %.8f — 잔고 스냅샷 debts 로 반영(총자산 차감, 같은 값은 1시간마다만 기록)★", ex, src, asset, v)


def _loan_amt(row, sym_key, amt_key, what):
    if not isinstance(row, dict):
        raise RuntimeError(f"{what} 행 형식 오류")
    sym = row.get(sym_key)
    if not isinstance(sym, str) or not sym.strip() or row.get(amt_key) in (None, ""):
        raise RuntimeError(f"{what} 통화/수량 필드 누락({sym_key}/{amt_key})")
    v = float(row[amt_key])
    if not 0 <= v < float("inf"):
        raise RuntimeError(f"{what} 수량 형식 오류")
    return sym.strip().upper(), v


def _loan_add(o, ex, src, product, label, collateral, debt, since=None, extra=None):
    for sym, v in (collateral or {}).items():
        _add_to(o, sym, v)
    for sym, v in (debt or {}).items():
        if v > 0:
            _debt_add(o, ex, src, sym, -v)
    if (collateral or debt) and isinstance(getattr(o, "loans", None), list):
        rec = {"ex": ex, "src": src, "product": product, "label": label,
               "collateral": {k: v for k, v in (collateral or {}).items() if v > 0},
               "debt": {k: v for k, v in (debt or {}).items() if v > 0}}
        if since:
            rec["since"] = int(since)
        if extra:
            rec.update(extra)
        o.loans.append(rec)


@_clock_retry
def _binance_signed(env, path, params=None, method="GET"):
    _gov_prepare("api.binance.com", path)
    key, sec = env["TJ_BINANCE_KEY"], env["TJ_BINANCE_SECRET"]
    p = dict(params or {})
    p["timestamp"] = _srv_ms("api.binance.com")
    p["recvWindow"] = 10000
    qs = urllib.parse.urlencode(p)
    sig = hmac.new(sec.encode(), qs.encode(), hashlib.sha256).hexdigest()
    url = f"https://api.binance.com{path}?{qs}&signature={sig}"
    return _http_json_err(url, {"X-MBX-APIKEY": key},
                          data=(b"" if method == "POST" else None),
                          method=(method if method != "GET" else None))


def _add_to(d, sym, v):
    if v > 0 and sym:
        d[str(sym).upper()] = d.get(str(sym).upper(), 0) + v


def _earn_amount(out, row, symbol_key, amount_key):
    if not isinstance(row, dict):
        raise RuntimeError("Earn 잔고 행 형식 오류")
    sym = row.get(symbol_key)
    if not isinstance(sym, str) or not sym.strip() or row.get(amount_key) in (None, ""):
        raise RuntimeError("Earn 통화/수량 필드 누락")
    value = float(row[amount_key])
    if not 0 <= value < float("inf"):
        raise RuntimeError("Earn 잔고 수량 형식 오류")
    _add_to(out, sym.strip(), value)


def _balance_rows(rows):
    if not isinstance(rows, list):
        raise RuntimeError("잔고 응답의 필수 목록 누락/형식 오류 — 부분 잔고 발행 보류")
    return rows


def _bn_amt(row, key, what):
    if not isinstance(row, dict):
        raise RuntimeError(f"{what} 행 형식 오류 — 부분 잔고 발행 보류")
    v = row.get(key)
    if v is None or isinstance(v, bool) or (isinstance(v, str) and not v.strip()):
        raise RuntimeError(f"{what} 금액 필드 누락({key}) — 부분 잔고 발행 보류")
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise RuntimeError(f"{what} 금액 형식 오류({key}) — 부분 잔고 발행 보류") from None
    if f != f or f in (float("inf"), float("-inf")):
        raise RuntimeError(f"{what} 금액 형식 오류({key}) — 부분 잔고 발행 보류")
    return f


def _bn_sym(row, key, what):
    v = row.get(key) if isinstance(row, dict) else None
    if not isinstance(v, str) or not v.strip():
        raise RuntimeError(f"{what} 통화 필드 누락({key}) — 부분 잔고 발행 보류")
    return v.strip().upper()


_BN_TOTAL_WARNED = set()


def _bn_total_check(total, got, what):
    if total is None:
        if what not in _BN_TOTAL_WARNED:
            _BN_TOTAL_WARNED.add(what)
            log.warning("%s 응답에 total 없음 — 목록 완전성 검증 생략(명세와 다름 · 종전대로 진행)", what)
        return
    try:
        n = int(str(total).strip())
    except (TypeError, ValueError, AttributeError):
        raise RuntimeError(f"{what} total 형식 오류 — 부분 잔고 발행 보류") from None
    if n != int(got):
        raise RuntimeError(f"{what} 받은 행 {int(got)} ≠ total {n} — 부분 잔고 발행 보류(다음 주기 재조회)")


def _bal_binance(env):
    out = _Bal()
    d = _binance_signed(env, "/api/v3/account")
    spot_ld = {}
    if not isinstance(d, dict):
        raise RuntimeError("binance 스팟 잔고 응답 형식 오류 — 부분 잔고 발행 보류")
    for b in _balance_rows(d.get("balances")):
        a0 = _bn_sym(b, "asset", "binance 스팟")
        v0 = _bn_amt(b, "free", "binance 스팟") + _bn_amt(b, "locked", "binance 스팟")
        _add_to(out, a0, v0)
        if a0.startswith("LD") and len(a0) > 2 and v0 > 0:
            spot_ld[a0] = v0
    earn_flex = []
    earn_coll = {}

    def _cross(o):
        d2 = _binance_signed(env, "/sapi/v1/margin/account")
        if not isinstance(d2, dict):
            raise RuntimeError("binance 교차 마진 응답 형식 오류 — 부분 잔고 발행 보류")
        for a in _balance_rows(d2.get("userAssets")):
            sym = _bn_sym(a, "asset", "binance 교차 마진")
            v = _bn_amt(a, "netAsset", "binance 교차 마진")
            if v < 0:
                _debt_add(o, "binance", "margin", sym, v)
            else:
                _add_to(o, sym, v)

    def _iso(o):
        d2 = _binance_signed(env, "/sapi/v1/margin/isolated/account")
        if not isinstance(d2, dict):
            raise RuntimeError("binance 격리 마진 응답 형식 오류 — 부분 잔고 발행 보류")
        for pair in _balance_rows(d2.get("assets")):
            if not isinstance(pair, dict):
                raise RuntimeError("binance 격리 마진 행 형식 오류 — 부분 잔고 발행 보류")
            for side in ("baseAsset", "quoteAsset"):
                a = pair.get(side)
                if not isinstance(a, dict):
                    raise RuntimeError(f"binance 격리 마진 {side} 누락 — 부분 잔고 발행 보류")
                sym = _bn_sym(a, "asset", "binance 격리 마진")
                v = _bn_amt(a, "netAsset", "binance 격리 마진")
                if v < 0:
                    _debt_add(o, "binance", "isolated", sym, v)
                else:
                    _add_to(o, sym, v)

    def _fund(o):
        rows = _binance_signed(env, "/sapi/v1/asset/get-funding-asset", method="POST")
        for a in _balance_rows(rows):
            _add_to(o, _bn_sym(a, "asset", "binance 펀딩"),
                    sum(_bn_amt(a, k9, "binance 펀딩") for k9 in ("free", "locked", "freeze", "withdrawing")))

    def _futures(o):
        key2, sec2 = env["TJ_BINANCE_KEY"], env["TJ_BINANCE_SECRET"]
        _gov_prepare("fapi.binance.com", "/fapi/v2/balance")
        q2 = urllib.parse.urlencode({"timestamp": _srv_ms("fapi.binance.com"),
                                     "recvWindow": 10000})
        sig2 = hmac.new(sec2.encode(), q2.encode(), hashlib.sha256).hexdigest()
        rows = _http_json_err(f"https://fapi.binance.com/fapi/v2/balance?{q2}&signature={sig2}",
                              {"X-MBX-APIKEY": key2})
        for a in _balance_rows(rows):
            _add_to(o, _bn_sym(a, "asset", "binance 선물"), _bn_amt(a, "balance", "binance 선물"))

    def _earn(o):
        flex9 = set()
        coll9 = {}
        for path, amt_key in (("/sapi/v1/simple-earn/flexible/position", "totalAmount"),
                              ("/sapi/v1/simple-earn/locked/position", "amount")):
            page, got9 = 1, 0
            while page <= 20:
                d2 = _binance_signed(env, path, {"current": page, "size": 100})
                if not isinstance(d2, dict):
                    raise RuntimeError("binance Earn 응답 형식 오류 — 부분 잔고 발행 보류")
                rows = _balance_rows(d2.get("rows"))
                for r2 in rows:
                    _earn_amount(o, r2, "asset", amt_key)
                    if amt_key == "totalAmount":
                        a9 = r2["asset"].strip().upper()
                        flex9.add(a9)
                        c9 = r2.get("collateralAmount")
                        if c9 not in (None, ""):
                            try:
                                cv9 = float(c9)
                            except (TypeError, ValueError):
                                raise RuntimeError("binance Earn 담보량 형식 오류 — 부분 잔고 발행 보류") from None
                            if cv9 > 0:
                                coll9[a9] = coll9.get(a9, 0.0) + cv9
                got9 += len(rows)
                if len(rows) < 100:
                    break
                page += 1
                time.sleep(PACE)
            else:
                raise RuntimeError("binance Earn 20페이지 초과 — 부분 잔고 폐기(상한 조정 필요)")
            _bn_total_check(d2.get("total"), got9, "binance Earn " + ("유동" if amt_key == "totalAmount" else "고정"))
        earn_flex[:] = sorted(flex9)
        earn_coll.clear()
        earn_coll.update(coll9)

    def _loan(o):
        page, got9 = 1, 0
        while page <= 20:
            d2 = _binance_signed(env, "/sapi/v2/loan/flexible/ongoing/orders", {"current": page, "limit": 100})
            if not isinstance(d2, dict):
                raise RuntimeError("binance flexible loan 응답 형식 오류")
            rows = _balance_rows(d2.get("rows"))
            got9 += len(rows)
            for r2 in rows:
                ck, cv = _loan_amt(r2, "collateralCoin", "collateralAmount", "binance 대출 담보")
                lk, lv = _loan_amt(r2, "loanCoin", "totalDebt", "binance 대출 차입")
                ex9 = {}
                try:
                    ex9["ltv"] = float(r2.get("currentLTV"))
                except (TypeError, ValueError):
                    pass
                _loan_add(o, "binance", "loan", "flexible-loan", "바이낸스 담보대출", {ck: cv}, {lk: lv}, extra=ex9)
            if len(rows) < 100:
                _bn_total_check(d2.get("total"), got9, "binance 담보대출")
                return
            page += 1
            time.sleep(PACE)
        raise RuntimeError("binance flexible loan 20페이지 초과 — 부분 잔고 폐기")

    for src, fn in (("margin", _cross), ("isolated", _iso),
                    ("funding", _fund), ("earn", _earn), ("futures", _futures)):
        time.sleep(PACE)
        _sub_bal("binance", src, fn, out)
    time.sleep(PACE)
    _sub_bal("binance", "loan", _loan, out, lenient=True)
    if "earn" in out.sources:
        for x9 in earn_flex:
            k9 = "LD" + x9
            if k9 in spot_ld and k9 in out:
                out[k9] -= spot_ld[k9]
                if out[k9] <= 1e-12:
                    del out[k9]
    if "earn" in out.sources and "loan" in out.sources and earn_coll:
        lc9 = {}
        for ln9 in out.loans:
            if isinstance(ln9, dict) and ln9.get("ex") == "binance":
                for k9, v9 in (ln9.get("collateral") or {}).items():
                    lc9[k9] = lc9.get(k9, 0.0) + float(v9)
        for k9, v9 in lc9.items():
            dup9 = min(v9, earn_coll.get(k9, 0.0))
            if dup9 > 0 and k9 in out:
                out[k9] -= dup9
                if out[k9] <= 1e-12:
                    del out[k9]
    return out


@_clock_retry
def _bybit_get(env, path, params):
    _gov_prepare("api.bybit.com", path)
    key, sec = env["TJ_BYBIT_KEY"], env["TJ_BYBIT_SECRET"]
    qs = urllib.parse.urlencode(params or {})
    ts = str(_srv_ms("api.bybit.com"))
    sig = hmac.new(sec.encode(), (ts + key + "10000" + qs).encode(), hashlib.sha256).hexdigest()
    d = http_json(f"https://api.bybit.com{path}" + (f"?{qs}" if qs else ""),
                  {"X-BAPI-API-KEY": key, "X-BAPI-TIMESTAMP": ts,
                   "X-BAPI-RECV-WINDOW": "10000", "X-BAPI-SIGN": sig})
    if not isinstance(d, dict) or d.get("retCode") != 0:
        rc = d.get("retCode") if isinstance(d, dict) else None
        raise RuntimeError(f"bybit {path} retCode={rc} {_xm((d or {}).get('retMsg')) if isinstance(d, dict) else _xm(str(d)[:80])}")
    return d.get("result") or {}


def _bal_bybit(env):
    _gov_prepare("api.bybit.com", "/v5/account/wallet-balance")
    key, sec = env["TJ_BYBIT_KEY"], env["TJ_BYBIT_SECRET"]
    q = "accountType=UNIFIED"
    ts = str(_srv_ms("api.bybit.com"))
    sig = hmac.new(sec.encode(), (ts + key + "10000" + q).encode(), hashlib.sha256).hexdigest()
    d = http_json(f"https://api.bybit.com/v5/account/wallet-balance?{q}",
                  {"X-BAPI-API-KEY": key, "X-BAPI-TIMESTAMP": ts,
                   "X-BAPI-RECV-WINDOW": "10000", "X-BAPI-SIGN": sig})
    if d.get("retCode") != 0:
        raise RuntimeError(f"bybit {_xm(d.get('retMsg'))}")
    out = _Bal()
    for acct in _balance_rows((d.get("result") or {}).get("list")):
        for c in _balance_rows(acct.get("coin")):
            v = float(c.get("walletBalance") or 0) - float(c.get("spotBorrow") or 0)
            if v < 0:
                _debt_add(out, "bybit", "UNIFIED", c.get("coin"), v)
            if v > 0:
                out[str(c["coin"]).upper()] = out.get(str(c["coin"]).upper(), 0) + v
    time.sleep(PACE)
    _gov_prepare("api.bybit.com", "/v5/asset/transfer/query-account-coins-balance")
    q2 = "accountType=FUND"
    ts2 = str(_srv_ms("api.bybit.com"))
    sig2 = hmac.new(sec.encode(), (ts2 + key + "10000" + q2).encode(),
                    hashlib.sha256).hexdigest()
    d2 = http_json(f"https://api.bybit.com/v5/asset/transfer/query-account-coins-balance?{q2}",
                   {"X-BAPI-API-KEY": key, "X-BAPI-TIMESTAMP": ts2,
                    "X-BAPI-RECV-WINDOW": "10000", "X-BAPI-SIGN": sig2})
    if d2.get("retCode") != 0:
        raise RuntimeError(f"bybit FUND {_xm(d2.get('retMsg'))}")
    for c in _balance_rows((d2.get("result") or {}).get("balance")):
        v = float(c.get("walletBalance") or 0)
        if v > 0:
            out[str(c["coin"]).upper()] = out.get(str(c["coin"]).upper(), 0) + v

    def _earn(o):
        for cat in ("FlexibleSaving", "OnChain"):
            res = _bybit_get(env, "/v5/earn/position", {"category": cat})
            rows = res.get("list")
            if not isinstance(rows, list):
                raise RuntimeError(f"bybit earn {cat} list 누락")
            for r2 in rows:
                _earn_amount(o, r2, "coin", "amount")
            time.sleep(PACE)

    def _loan(o):
        res = _bybit_get(env, "/v5/crypto-loan-common/position", {})
        if not isinstance(res, dict):
            raise RuntimeError("bybit crypto-loan position 형식 오류")
        coll, debt = {}, {}
        for key9 in ("collateralList", "supplyList"):
            rows = res.get(key9)
            if not isinstance(rows, list):
                raise RuntimeError(f"bybit crypto-loan {key9} 누락")
            for r2 in rows:
                k9, v9 = _loan_amt(r2, "currency", "amount", f"bybit 대출 {key9}")
                coll[k9] = coll.get(k9, 0) + v9
        rows = res.get("borrowList")
        if not isinstance(rows, list):
            raise RuntimeError("bybit crypto-loan borrowList 누락")
        for r2 in rows:
            if not isinstance(r2, dict) or not isinstance(r2.get("loanCurrency"), str) or not r2["loanCurrency"].strip():
                raise RuntimeError("bybit 대출 차입 행 형식 오류(loanCurrency)")
            parts9 = [r2.get(f9) for f9 in ("fixedTotalDebt", "flexibleTotalDebt") if r2.get(f9) not in (None, "")]
            if not parts9:
                raise RuntimeError("bybit 대출 차입 수량 필드 누락(fixedTotalDebt/flexibleTotalDebt)")
            v9 = sum(float(x) for x in parts9)
            if not 0 <= v9 < float("inf"):
                raise RuntimeError("bybit 대출 차입 수량 형식 오류")
            debt[r2["loanCurrency"].strip().upper()] = debt.get(r2["loanCurrency"].strip().upper(), 0) + v9
        try:
            td9 = float(res.get("totalDebt") or 0)
        except (TypeError, ValueError):
            td9 = 0.0
        if td9 > 0 and not any(v > 0 for v in debt.values()):
            raise RuntimeError("bybit crypto-loan totalDebt>0 인데 차입 행 없음 — 형식 변경 의심")
        ex9 = {}
        try:
            ex9["ltv"] = float(res.get("ltv"))
        except (TypeError, ValueError):
            pass
        _loan_add(o, "bybit", "loan", "crypto-loan", "바이빗 담보대출", coll, debt, extra=ex9)

    time.sleep(PACE)
    _sub_bal("bybit", "earn", _earn, out, extra_deny=("retCode=10005", "retCode=10003", "retCode=10004"), lenient=True)
    time.sleep(PACE)
    _sub_bal("bybit", "loan", _loan, out, extra_deny=("retCode=10005", "retCode=10003", "retCode=10004"), lenient=True)
    return out


@_clock_retry
def _okx_get(env, path, params=None):
    _gov_prepare("www.okx.com", path)
    key, sec, pph = env["TJ_OKX_KEY"], env["TJ_OKX_SECRET"], env["TJ_OKX_PASSPHRASE"]
    qs = urllib.parse.urlencode(params or {})
    full = path + ("?" + qs if qs else "")
    ts = _okx_ts(_srv_ms("www.okx.com"))
    sig = base64.b64encode(hmac.new(sec.encode(), (ts + "GET" + full).encode(),
                                    hashlib.sha256).digest()).decode()
    d = http_json("https://www.okx.com" + full,
                  {"OK-ACCESS-KEY": key, "OK-ACCESS-SIGN": sig,
                   "OK-ACCESS-TIMESTAMP": ts, "OK-ACCESS-PASSPHRASE": pph})
    if d.get("code") != "0":
        raise RuntimeError(f"okx {d.get('code')} {_xm(d.get('msg'))}")
    if path in ("/api/v5/account/balance", "/api/v5/asset/balances", "/api/v5/finance/savings/balance",
                "/api/v5/finance/staking-defi/orders-active", "/api/v5/finance/flexible-loan/loan-info",
                "/api/v5/account/positions",
                "/api/v5/account/bills", "/api/v5/account/bills-archive"):
        return _balance_rows(d.get("data"))
    return d.get("data") or []


def _bal_okx(env):
    out = _Bal()
    for row in _okx_get(env, "/api/v5/account/balance"):
        for c in _balance_rows(row.get("details")):
            v = float(c.get("cashBal") or c.get("availBal") or 0)
            if v > 0:
                out[str(c["ccy"]).upper()] = out.get(str(c["ccy"]).upper(), 0) + v
            elif v < 0:
                _debt_add(out, "okx", "trading", c.get("ccy"), v)
    time.sleep(PACE)
    for c in _okx_get(env, "/api/v5/asset/balances"):
        v = float(c.get("bal") or 0)
        if v > 0:
            out[str(c["ccy"]).upper()] = out.get(str(c["ccy"]).upper(), 0) + v

    def _savings(o):
        rows = _okx_get(env, "/api/v5/finance/savings/balance")
        if not isinstance(rows, list):
            raise RuntimeError("okx savings data 형식 오류")
        for r2 in rows:
            _earn_amount(o, r2, "ccy", "amt")

    def _staking(o):
        after9, seen9 = "", set()
        for _p in range(20):
            p9 = {"limit": 100}
            if after9:
                p9["after"] = after9
            rows = _okx_get(env, "/api/v5/finance/staking-defi/orders-active", p9)
            if not isinstance(rows, list):
                raise RuntimeError("okx staking data 형식 오류")
            for r2 in rows:
                if not isinstance(r2, dict):
                    raise RuntimeError("okx staking 행 형식 오류")
                for inv in _balance_rows(r2.get("investData")):
                    _earn_amount(o, inv, "ccy", "amt")
            if len(rows) < 100:
                return
            nxt = str(rows[-1].get("ordId") or "")
            if not nxt or nxt in seen9:
                raise RuntimeError("okx staking 페이지 미전진")
            seen9.add(nxt)
            after9 = nxt
            time.sleep(PACE)
        raise RuntimeError("okx staking 20페이지 초과 — 부분 잔고 폐기")

    def _loan(o):
        rows = _okx_get(env, "/api/v5/finance/flexible-loan/loan-info")
        recs = []
        for r in rows:
            if not isinstance(r, dict):
                raise RuntimeError("okx loan-info 행 형식 오류")
            coll, debt = {}, {}
            for c in _balance_rows(r.get("collateralData")):
                k9, v9 = _loan_amt(c, "ccy", "amt", "okx 대출 담보")
                coll[k9] = coll.get(k9, 0) + v9
            for c in _balance_rows(r.get("loanData")):
                k9, v9 = _loan_amt(c, "ccy", "amt", "okx 대출 차입")
                debt[k9] = debt.get(k9, 0) + v9
            if any(v > 0 for v in coll.values()) or any(v > 0 for v in debt.values()):
                recs.append((r, coll, debt))
        if not recs:
            return
        since, evs, prin, prin_bad = None, [], {}, False
        if any(v > 0 for _, _, d9 in recs for v in d9.values()):
            time.sleep(PACE)
            hist = _okx_get(env, "/api/v5/finance/flexible-loan/loan-history", {"limit": "100"})
            if not isinstance(hist, list):
                raise RuntimeError("okx loan-history data 형식 오류")
            for h9 in hist:
                if not isinstance(h9, dict):
                    raise RuntimeError("okx loan-history 행 형식 오류")
                try:
                    t9 = int(int(h9.get("ts")) / 1000)
                except (TypeError, ValueError):
                    raise RuntimeError("okx loan-history ts 형식 오류") from None
                typ9 = str(h9.get("type") or "")
                if typ9 in ("borrowed", "collateral_locked"):
                    since = t9 if since is None else min(since, t9)
                if typ9 in ("borrowed", "repaid"):
                    try:
                        c9 = str(h9.get("ccy") or "").upper()
                        prin[c9] = prin.get(c9, 0.0) + (abs(float(h9.get("amt"))) * (1 if typ9 == "borrowed" else -1))
                    except (TypeError, ValueError):
                        prin_bad = True
                if len(evs) < 20:
                    try:
                        a9 = float(h9.get("amt"))
                    except (TypeError, ValueError):
                        a9 = None
                    evs.append({"ts": t9, "type": typ9, "ccy": str(h9.get("ccy") or "").upper(), "amt": a9})
        for r, coll, debt in recs:
            ex9 = {}
            for k9, f9 in (("curLTV", "ltv"), ("liqLTV", "liqLtv"), ("marginCallLTV", "callLtv")):
                try:
                    ex9[f9] = float(r.get(k9))
                except (TypeError, ValueError):
                    pass
            try:
                ex9["liqPx"] = float((r.get("riskWarningData") or {}).get("liqPx"))
                ex9["liqPair"] = str((r.get("riskWarningData") or {}).get("instId") or "")
            except (TypeError, ValueError, AttributeError):
                pass
            if evs:
                ex9["events"] = evs
            if prin and not prin_bad and len(hist) < 100:
                ex9["principal"] = {k9: v9 for k9, v9 in prin.items() if v9 > 0}
            _loan_add(o, "okx", "loan", "flexible-loan", "OKX 담보대출", coll, debt, since=since, extra=ex9)

    okx_deny = ("okx 50120", "okx 50030", "okx 50125", "okx 50119", "okx 58350")
    for src, fn in (("savings", _savings), ("staking", _staking), ("loan", _loan)):
        time.sleep(PACE)
        _sub_bal("okx", src, fn, out, extra_deny=okx_deny, lenient=True)
    return out


@_clock_retry
def _kucoin_get(env, path_with_qs):
    _gov_prepare("api.kucoin.com", path_with_qs.split("?", 1)[0])
    key, sec, pph = env["TJ_KUCOIN_KEY"], env["TJ_KUCOIN_SECRET"], env["TJ_KUCOIN_PASSPHRASE"]
    ts = str(_srv_ms("api.kucoin.com"))
    sig = base64.b64encode(hmac.new(sec.encode(), (ts + "GET" + path_with_qs).encode(),
                                    hashlib.sha256).digest()).decode()
    pph_sig = base64.b64encode(hmac.new(sec.encode(), pph.encode(),
                                        hashlib.sha256).digest()).decode()
    d = http_json("https://api.kucoin.com" + path_with_qs,
                  {"KC-API-KEY": key, "KC-API-SIGN": sig, "KC-API-TIMESTAMP": ts,
                   "KC-API-PASSPHRASE": pph_sig, "KC-API-KEY-VERSION": "2"})
    if d.get("code") != "200000":
        raise RuntimeError(f"kucoin {_xm(d.get('msg'))}")
    return d.get("data")


def _bal_kucoin(env):
    out = _Bal()
    v1_margin = {}
    for a in _balance_rows(_kucoin_get(env, "/api/v1/accounts")):
        v = float(a.get("balance") or 0)
        if v > 0:
            out[str(a["currency"]).upper()] = out.get(str(a["currency"]).upper(), 0) + v
            if str(a.get("type") or "").lower() in ("margin", "margin_v2"):
                _add_to(v1_margin, a["currency"], v)

    def _margin(o):
        d2 = _kucoin_get(env, "/api/v3/margin/accounts?quoteCurrency=USDT")
        if not isinstance(d2, dict):
            raise RuntimeError("kucoin margin 응답 형식 오류")
        for a2 in _balance_rows(d2.get("accounts")):
            k9, t9 = _loan_amt(a2, "currency", "total", "kucoin 마진 자산")
            k9, v9 = _loan_amt(a2, "currency", "liability", "kucoin 마진 부채")
            _add_to(o, k9, t9)
            if v9 > 0:
                _debt_add(o, "kucoin", "margin", k9, -v9)

    time.sleep(PACE)
    _sub_bal("kucoin", "margin", _margin, out, extra_deny=("enable the margin trading",), lenient=True)
    if "margin" in out.sources:
        for k9, v9 in v1_margin.items():
            out[k9] = out.get(k9, 0) - v9
            if out[k9] <= 1e-12:
                del out[k9]
    return out


@_clock_retry
def _gate_get(env, path, params=None):
    _gov_prepare("api.gateio.ws", path)
    key, sec = env["TJ_GATE_KEY"], env["TJ_GATE_SECRET"]
    qs = urllib.parse.urlencode(params or {})
    ts = str(_srv_ms("api.gateio.ws") // 1000)
    bh = hashlib.sha512(b"").hexdigest()
    sig = hmac.new(sec.encode(), f"GET\n{path}\n{qs}\n{bh}\n{ts}".encode(),
                   hashlib.sha512).hexdigest()
    return http_json(f"https://api.gateio.ws{path}" + (f"?{qs}" if qs else ""),
                     {"KEY": key, "Timestamp": ts, "SIGN": sig})


def _bal_gate(env):
    out = _Bal()
    for a in _balance_rows(_gate_get(env, "/api/v4/spot/accounts")):
        _add_to(out, a["currency"], float(a.get("available") or 0) + float(a.get("locked") or 0))

    def _gmargin(o):
        for pair in _balance_rows(_gate_get(env, "/api/v4/margin/accounts")):
            for side in ("base", "quote"):
                a2 = pair.get(side) or {}
                v = (float(a2.get("available") or 0) + float(a2.get("locked") or 0)
                     - float(a2.get("borrowed") or 0))
                if v < 0:
                    _debt_add(o, "gate", "margin", a2.get("currency"), v)
                else:
                    _add_to(o, a2.get("currency"), v)

    time.sleep(PACE)
    _sub_bal("gate", "margin", _gmargin, out)
    spot9 = dict(out)

    def _gcross(o):
        d2 = _gate_get(env, "/api/v4/margin/cross/accounts")
        bals = d2.get("balances") if isinstance(d2, dict) else None
        if not isinstance(bals, dict):
            raise RuntimeError("gate cross balances 누락/형식 오류")
        for ccy, b2 in bals.items():
            if not isinstance(b2, dict):
                raise RuntimeError("gate cross 행 형식 오류")
            held = float(b2.get("available") or 0) + float(b2.get("freeze") or 0)
            if held > 1e-8 and spot9.get(str(ccy).upper(), 0) < held * 0.5:
                raise RuntimeError(f"gate 교차 잔고 {ccy} 가 스팟에 없음 — 클래식 교차마진(별도 계정) 추정, 미지원")
            liab = float(b2.get("total_liab") or 0)
            if liab > 1e-6:
                _debt_add(o, "gate", "cross", ccy, -liab)

    time.sleep(PACE)
    _sub_bal("gate", "cross", _gcross, out, lenient=True)
    return out


def _bithumb_get(env, path, params=None):
    _gov_prepare("api.bithumb.com", path)
    key, sec = env["TJ_BITHUMB_KEY"], env["TJ_BITHUMB_SECRET"]
    payload = {"access_key": key, "nonce": str(uuidlib.uuid4()),
               "timestamp": _srv_ms("api.bithumb.com")}
    if params:
        raw_qs = "&".join(f"{k}={v}" for k, v in params.items())
        payload["query_hash"] = hashlib.sha512(raw_qs.encode()).hexdigest()
        payload["query_hash_alg"] = "SHA512"

    def b64u(b):
        return base64.urlsafe_b64encode(b).rstrip(b"=")
    h = b64u(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    p = b64u(json.dumps(payload).encode())
    s = b64u(hmac.new(sec.encode(), h + b"." + p, hashlib.sha256).digest())
    tok = (h + b"." + p + b"." + s).decode()
    qs = urllib.parse.urlencode(params) if params else ""
    return http_json(f"https://api.bithumb.com{path}" + (f"?{qs}" if qs else ""),
                     {"Authorization": f"Bearer {tok}"})


def _bal_bithumb(env):
    out = _Bal()
    for a in _balance_rows(_bithumb_get(env, "/v1/accounts")):
        v = float(a.get("balance") or 0) + float(a.get("locked") or 0)
        if v > 0:
            out[str(a["currency"]).upper()] = v
    return out


BAL_FETCHERS = {"binance": _bal_binance, "bybit": _bal_bybit, "okx": _bal_okx,
                "kucoin": _bal_kucoin, "gate": _bal_gate, "bithumb": _bal_bithumb}


FILL_FETCHERS = {
    "binance": fills_binance, "bybit": fills_bybit, "okx": fills_okx,
    "kucoin": fills_kucoin, "gate": fills_gate, "bithumb": fills_bithumb,
}
FILL_REPLAY = {"binance": fills_binance_replay}


SEEN_NOTIME = "#notime"


def _has_time(r) -> bool:
    return bool(_iso_epoch(r.get("created_at")) or _iso_epoch(r.get("done_at")))


def _is_time_fix(r, seen) -> bool:
    return isinstance(r, dict) and seen.get(r.get("uuid")) == str(r.get("state")) + SEEN_NOTIME and _has_time(r)


def _seen_state(v) -> str:
    return str(v or "").split("#", 1)[0]


def _rows_to_emit(rows, seen, seen_txids, seen_dest=None):
    def changed(r):
        s9 = seen.get(r["uuid"])
        if s9 == r["state"]:
            return False
        if s9 == str(r["state"]) + SEEN_NOTIME:
            if not _is_time_fix(r, seen):
                return False
            r["late"] = 1
            return True
        return True
    return [r for r in rows
            if changed(r)
            or (r.get("txid") and not seen_txids.get(r["uuid"]))
            or (seen_dest is not None and r.get("address") and not seen_dest.get(r["uuid"]))]


PEND_FINAL = ("DONE", "ACCEPTED", "CANCELLED", "REJECTED", "FAILED")

_LATE_CYC = {"id": None, "ex": set()}


def _late_tag(rec: dict, ex: str, force: bool = False) -> dict:
    lc = _LATE_CYC.get("id")
    if not lc:
        return rec
    rows = (rec.get("fills") or []) + (rec.get("deposits") or []) + (rec.get("withdraws") or [])
    if force or any(isinstance(r, dict) and (r.get("late") or r.get("src") == "convert") for r in rows):
        rec["lc"] = lc
        _LATE_CYC["ex"].add(ex)
    return rec


class _CycleWriter:

    def __init__(self, writer, state: dict):
        self.w, self.state = writer, state

    def append(self, rec):
        if isinstance(rec, dict) and rec.get("kind") in ("ex_snapshot", "exf_fills") and not rec.get("lc"):
            ex = str(rec.get("exchange") or "")
            st = self.state.get(ex) if isinstance(self.state, dict) else None
            seen = st.get("seen") if isinstance(st, dict) and isinstance(st.get("seen"), dict) else {}
            fix = 0
            for r in (rec.get("deposits") or []) + (rec.get("withdraws") or []):
                if _is_time_fix(r, seen):
                    if not r.get("late"):
                        fix += 1
                    r["late"] = 1
            if fix:
                _invalidate_balance_snapshot(ex)
            _late_tag(rec, ex)
        return self.w.append(rec)


def _iso_epoch(s):
    try:
        import datetime as _dt
        s9 = str(s or "")
        if s9.endswith("Z"):
            s9 = s9[:-1] + "+00:00"
        return int(_dt.datetime.fromisoformat(s9).timestamp())
    except (ValueError, TypeError):
        return None


def _mark_seen(rows, seen, seen_txids, seen_dest, pend=None):
    for r in rows:
        seen[r["uuid"]] = r["state"] if _has_time(r) else str(r["state"]) + SEEN_NOTIME
        if r.get("txid"):
            seen_txids[r["uuid"]] = True
        if r.get("address"):
            seen_dest[r["uuid"]] = True
        if pend is not None:
            if str(r.get("state") or "").upper() in PEND_FINAL:
                pend.pop(r["uuid"], None)
            elif r["uuid"] not in pend:
                c9 = _iso_epoch(r.get("created_at"))
                if c9:
                    pend[r["uuid"]] = [c9, int(time.time())]


PEND_RECHECK_SEC = 6 * 3600
PEND_MAX_QUERIES = 28
PEND_MAX_WINDOWS = 3


def _pend_nq(v) -> int:
    try:
        return int(v[2]) if isinstance(v, list) and len(v) > 2 else 0
    except (TypeError, ValueError):
        return 0


def pending_recheck_pass(env: dict, state: dict, writer, now: int, window: int, fetchers=None) -> dict:
    out = {}
    for ex, (fn, need) in (fetchers or FETCHERS).items():
        if not all(env.get(k) for k in need) or ex not in state:
            continue
        st = state[ex]
        if not st.get("backfilled_until"):
            continue
        rc = st.setdefault("pend_rc", {})
        if now - int(rc.get("at") or 0) < PEND_RECHECK_SEC:
            continue
        seen = st.setdefault("seen", {})
        pend = st.setdefault("pend_ts", {})
        reg_lo = max(now - window, min(now - 7 * DAY, int(st.get("backfilled_until") or now)))
        scan = not st.get("pend_scan")
        legacy = {u for u, s9 in seen.items() if str(s9).upper() not in PEND_FINAL and u not in pend}
        wins = []
        if scan:
            ext = st.get("ext") or {}
            lo9 = int(now - window)
            if ext.get("wd_from"):
                lo9 = min(lo9, int(ext["wd_from"]))
            wins.append((min(lo9, reg_lo), now))
        else:
            for u in [u for u, v in pend.items() if not isinstance(v, list) or len(v) < 2
                      or _seen_state(seen.get(u)).upper() in PEND_FINAL or _pend_nq(v) >= PEND_MAX_QUERIES]:
                v9 = pend.pop(u)
                if _seen_state(seen.get(u)).upper() not in PEND_FINAL and isinstance(v9, list) and len(v9) >= 2:
                    log.info("%s 비종결 입출금 %s 상태 재확인 %d회 — 거래소가 그대로라 추적 종료(%s)", ex, u, _pend_nq(v9), seen.get(u))
            olds = sorted((int(v[0]), _pend_nq(v)) for v in pend.values() if int(v[0]) < reg_lo)
            allw = []
            for t9, nq9 in olds:
                if allw and t9 - DAY <= allw[-1][1]:
                    allw[-1] = [allw[-1][0], max(allw[-1][1], t9 + DAY), min(allw[-1][2], nq9)]
                else:
                    allw.append([t9 - DAY, t9 + DAY, nq9])
            wins = [(w9[0], w9[1]) for w9 in sorted(allw, key=lambda w9: (w9[2], w9[0]))[:PEND_MAX_WINDOWS]]
        rc["at"] = int(now)
        if not wins:
            if scan:
                st["pend_scan"] = int(now)
            common.atomic_write_json(STATE_PATH, state)
            continue
        rows_w, rows_d = [], []
        int_ok = None
        try:
            for a9, b9 in wins:
                w9, d9 = fn(env, int(a9), int(min(b9, now)))
                rows_w += w9
                rows_d += d9
                if ex == "bybit" and not scan and any(str(u).startswith("bybit:int:") and isinstance(v, list) and len(v) >= 2
                                                      and a9 <= int(v[0]) <= b9 for u, v in pend.items()):
                    if time.time() < float(_WD_OFF.get("bybit:internal", 0) or 0):
                        int_ok = False
                        continue
                    try:
                        rows_d += _bybit_internal_rows(env, int(a9), int(min(b9, now)))
                        int_ok = True if int_ok is None else int_ok
                    except Exception as e9:
                        int_ok = False
                        if any(k in _xm(repr(e9)) for k in _DENY_SIGS + BB_INT_DENY):
                            _WD_OFF["bybit:internal"] = time.time() + DENY_COOL_SEC
                        log.warning("bybit 내부 입금 상태 재확인 실패(그 행만 다음 회): %s", _xm(repr(e9))[:120])
        except Exception as e:
            rc["err"] = _xm(repr(e))[:160]
            common.atomic_write_json(STATE_PATH, state)
            log.warning("%s 비종결 입출금 재확인 실패(6시간 뒤 다시): %s", ex, rc["err"])
            out[ex] = "error"
            continue
        rc.pop("err", None)
        if not scan:
            for u, v in pend.items():
                if str(u).startswith("bybit:int:") and int_ok is False:
                    continue
                if isinstance(v, list) and len(v) >= 2 and any(a9 <= int(v[0]) <= b9 for a9, b9 in wins):
                    pend[u] = [int(v[0]), int(v[1]), _pend_nq(v) + 1]
        seen_txids, seen_dest = st.setdefault("seen_txids", {}), st.setdefault("seen_dest", {})
        new_w = _rows_to_emit(rows_w, seen, seen_txids, seen_dest)
        new_d = _rows_to_emit(rows_d, seen, seen_txids)
        for r in new_w + new_d:
            r["late"] = 1
        if new_w or new_d:
            _invalidate_balance_snapshot(ex)
            both = sorted([("d", r) for r in new_d] + [("w", r) for r in new_w], key=lambda x: (str(x[1].get("currency") or ""), x[1]["uuid"]))
            lb9 = f"{ex}:pend:{int(now)}:{uuidlib.uuid4().hex[:10]}"
            nch9 = (len(both) + 499) // 500
            for k9, i in enumerate(range(0, len(both), 500)):
                ch9 = both[i:i + 500]
                writer.append(_late_tag({"v": 1, "kind": "ex_snapshot", "exchange": ex, "ts": int(now),
                                         "deposits": [r for t9, r in ch9 if t9 == "d"], "withdraws": [r for t9, r in ch9 if t9 == "w"],
                                         "lb": lb9, "lbi": k9, "lbn": nch9}, ex, force=True))
        _mark_seen(new_w + new_d, seen, seen_txids, seen_dest, pend)
        if scan:
            for r in rows_w + rows_d:
                if r["uuid"] in legacy and str(r.get("state") or "").upper() not in PEND_FINAL and r["uuid"] not in pend:
                    c9 = _iso_epoch(r.get("created_at"))
                    if c9:
                        pend[r["uuid"]] = [c9, int(now)]
            miss9 = sum(1 for u in legacy if u not in pend and _seen_state(seen.get(u)).upper() not in PEND_FINAL)
            st["pend_scan"] = int(now)
            log.info("%s 입출금 저장 창 재조회(1회): 행 %d · 상태 변경·신규 방출 %d · 비종결 추적 %d%s", ex, len(rows_w) + len(rows_d),
                     len(new_w) + len(new_d), len(pend), f" · 거래소가 더는 안 주는 비종결 {miss9}건" if miss9 else "")
        elif new_w or new_d:
            log.info("%s 비종결 입출금 재확인: 상태 변경 방출 %d건(추적 %d)", ex, len(new_w) + len(new_d), len(pend))
        common.atomic_write_json(STATE_PATH, state)
        out[ex] = len(new_w) + len(new_d)
    return out


def dest_backfill_pass(env: dict, state: dict, writer, now: int, window: int, fetchers=None) -> dict:
    out = {}
    for ex, (fn, need) in (fetchers or FETCHERS).items():
        if not all(env.get(k) for k in need):
            continue
        st = state.setdefault(ex, {"seen": {}, "backfilled_until": 0})
        if st.get("dest_bf"):
            continue
        fail9 = st.get("dest_bf_fail") or {}
        if now < int(fail9.get("next") or 0):
            out[ex] = "backoff"
            continue
        lo = int(now - window)
        ext = st.get("ext") or {}
        if ext.get("wd_from"):
            lo = min(lo, int(ext["wd_from"]))
        try:
            w_rows, _d = fn(env, lo, now)
        except Exception as e:
            n9 = int(fail9.get("n") or 0) + 1
            wait9 = min(12 * 3600, 1800 * (2 ** (n9 - 1)))
            st["dest_bf_fail"] = {"n": n9, "next": int(now + wait9)}
            state[ex] = st
            common.atomic_write_json(STATE_PATH, state)
            log.warning("%s 출금 목적지 소급 실패 %d회(%d분 뒤 재시도): %s", ex, n9, wait9 // 60, repr(e)[:140])
            out[ex] = "error"
            continue
        seen, seen_txids, seen_dest = st["seen"], st.setdefault("seen_txids", {}), st.setdefault("seen_dest", {})
        new_w = [r for r in w_rows if r["uuid"] in seen and r.get("address") and not seen_dest.get(r["uuid"])]
        for i in range(0, len(new_w), 500):
            writer.append({"v": 1, "kind": "ex_snapshot", "exchange": ex, "ts": now,
                           "deposits": [], "withdraws": new_w[i:i + 500]})
        for r in new_w:
            seen_dest[r["uuid"]] = True
        st["dest_bf"] = now
        st.pop("dest_bf_fail", None)
        state[ex] = st
        common.atomic_write_json(STATE_PATH, state)
        log.info("%s 출금 목적지 소급: 조회 %d · 보강 방출 %d", ex, len(w_rows), len(new_w))
        out[ex] = len(new_w)
    return out


def krw_backfill_pass(env: dict, state: dict, writer, now: int, window: int) -> str:
    need = FETCHERS.get("bithumb", (None, ()))[1]
    if "bithumb" not in FETCHERS or not all(env.get(k) for k in need):
        return "skip"
    st = state.setdefault("bithumb", {"seen": {}, "backfilled_until": 0})
    lo = int(now - window)
    t9 = bf_engine.SINCE.target("bithumb")
    if t9:
        lo = min(lo, int(t9))
    ext = st.get("ext") or {}
    if ext.get("wd_from"):
        lo = min(lo, int(ext["wd_from"]))
    if int(st.get("krw_bf_from") or (1 << 62)) <= lo:
        return "done"
    try:
        w_rows, d_rows = fetch_bithumb_krw(env, lo, now, require_complete=True)
    except Exception as e:
        log.warning("bithumb 원화 입출금 소급 실패(다음 주기): %s", repr(e)[:140])
        return "error"
    seen, seen_txids, seen_dest = st["seen"], st.setdefault("seen_txids", {}), st.setdefault("seen_dest", {})
    new_w = _rows_to_emit(w_rows, seen, seen_txids, seen_dest)
    new_d = _rows_to_emit(d_rows, seen, seen_txids)
    if new_w or new_d:
        _invalidate_balance_snapshot("bithumb")
        writer.append({"v": 1, "kind": "ex_snapshot", "exchange": "bithumb", "ts": now, "deposits": new_d, "withdraws": new_w})
        _mark_seen(new_w + new_d, seen, seen_txids, seen_dest, st.setdefault("pend_ts", {}))
    st["krw_bf_from"] = lo
    state["bithumb"] = st
    common.atomic_write_json(STATE_PATH, state)
    log.info("bithumb 원화 입출금 소급(%s~): 입금 %d · 출금 %d (신규 방출 %d)", time.strftime("%Y-%m-%d", time.gmtime(lo)),
             len(d_rows), len(w_rows), len(new_w) + len(new_d))
    return "ok"


WD_FLY_MAX = 24 * 3600
_WD_TERMINAL = set(PEND_FINAL) | {"CANCELED", "REFUNDED"}
SNAP_AGREE_REL = 1e-4
SNAP_AGREE_ABS = 1e-6
_SNAP_MISS = {}
SNAP_MISS_CAP = 6
SNAP_MISS_PATH = os.path.join(common.STATE_DIR, "exf_snap_miss.json")
_SNAP_MISS_ST = {}


def _wd_inflight(rows, now: int) -> list:
    out = []
    for r in rows or ():
        if not isinstance(r, dict) or str(r.get("state") or "").upper() in _WD_TERMINAL:
            continue
        c9 = _iso_epoch(r.get("created_at"))
        if c9 and int(now) - c9 <= WD_FLY_MAX:
            out.append(r)
    return out


def _snap_flat(snap: dict):
    out = {}
    for fld, pfx in (("balances", ""), ("debts", "부채 ")):
        d = snap.get(fld) if isinstance(snap, dict) else None
        if d is None:
            continue
        if not isinstance(d, dict):
            return None
        for k, v in d.items():
            ku = str(k).upper()
            if ku in ("KRW", "USD"):
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                return None
            if fv != fv:
                return None
            out[pfx + ku] = out.get(pfx + ku, 0.0) + fv
    return out


def _snap_agree(a: dict, b: dict):
    fa, fb = _snap_flat(a), _snap_flat(b)
    if fa is None or fb is None:
        return False, "형식 오류"
    pa, pb = (a or {}).get("fut_part"), (b or {}).get("fut_part")
    if isinstance(pa, dict) and isinstance(pb, dict):
        for fx9, p9 in ((fa, pa), (fb, pb)):
            for k9, v9 in p9.items():
                ku9 = str(k9).upper()
                try:
                    fv9 = float(v9)
                except (TypeError, ValueError):
                    return False, "형식 오류"
                if ku9 in fx9:
                    fx9[ku9] -= fv9
    for k in sorted(set(fa) | set(fb)):
        x, y = fa.get(k, 0.0), fb.get(k, 0.0)
        m = max(abs(x), abs(y))
        if abs(x - y) > max(SNAP_AGREE_REL * m, SNAP_AGREE_ABS):
            return False, f"{k} {(y - x) / m * 100:+.4f}%" if m else k
    return True, ""


def _snap_miss_save():
    try:
        _SNAP_MISS_ST["seen"] = set(_SNAP_MISS_ST.get("seen") or ()) | set(_SNAP_MISS_ST.get("ex") or {})
        common.atomic_write_json(SNAP_MISS_PATH, {"v": 1, "ts": int(time.time()), "ex": _SNAP_MISS_ST.get("ex") or {},
                                                  "seen": sorted(_SNAP_MISS_ST["seen"])})
    except Exception as e:
        log.warning("잔고 표본 불일치 상태 쓰기 실패: %s", repr(e)[:120])


def _snap_promote_ok(ex, prevp, snap9, now=None):
    now = int(time.time() if now is None else now)
    if "ex" not in _SNAP_MISS_ST:
        try:
            d9 = common.read_json(SNAP_MISS_PATH, {}) or {}
        except (Exception, SystemExit):
            d9 = {}
        _SNAP_MISS_ST["ex"] = {str(k): v for k, v in ((d9.get("ex") if isinstance(d9.get("ex"), dict) else {}) or {}).items() if isinstance(v, dict)}
        _SNAP_MISS_ST["seen"] = {str(x) for x in (d9.get("seen") if isinstance(d9.get("seen"), list) else [])}
    st9 = _SNAP_MISS_ST["ex"]
    agree9, why9 = _snap_agree(prevp, snap9)
    if agree9:
        _SNAP_MISS.pop(ex, None)
        if st9.pop(ex, None) is not None:
            _SNAP_MISS_ST.setdefault("seen", set()).add(ex)
            _snap_miss_save()
        return True, ""
    e9 = st9.setdefault(ex, {"since": now, "n": 0, "k": 0})
    e9["n"] = int(e9.get("n") or 0) + 1
    e9["k"] = int(e9.get("k") or 0) + 1
    e9["why"], e9["at"] = str(why9)[:80], now
    _SNAP_MISS[ex] = e9["n"]
    if e9["n"] % 6 == 1:
        log.info("%s 잔고 표본 불일치(%s · 연속 %d주기) — 승격 보류, 다음 주기 표본과 다시 비교", ex, why9, e9["n"])
    if e9["k"] >= SNAP_MISS_CAP:
        e9["k"], e9["forced"], e9["nf"] = 0, now, int(e9.get("nf") or 0) + 1
        _snap_miss_save()
        log.warning("★%s 잔고 표본이 %d주기 연속 달라(%s) — 일치 확인 없이 직전 표본 반영(대사가 멈춰 총자산이 굳지 않게 · 상태 패널 '잔고 표본 계속 다름')★",
                    ex, SNAP_MISS_CAP, why9)
        return "forced", why9
    _snap_miss_save()
    return False, why9


def _invalidate_balance_snapshot(ex):
    bp = os.path.join(common.STATE_DIR, f"exf_balances_{ex}.json")
    _keep_view(bp, bp + ".pending")
    for p in (bp, bp + ".pending"):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass


_FUT_OFF = _CoolMap("fut")
_RL_OFF = _CoolMap("rl")
_WD_OFF = _CoolMap("wd")
_CV_OFF = _CoolMap("cv")


def _fut_path(ex):
    return os.path.join(common.STATE_DIR, f"futures_{ex}.json")


def _fut_write(ex, wallet, positions, events, cursor, covered_through=None):
    events = sorted(events, key=lambda r: r["t"])
    if len(events) > 20000:
        log.warning("%s 선물 정산 이벤트 %d건 (파일 비대) — 보존 유지, 보관정책 검토 필요", ex, len(events))
    ts9 = int(time.time())
    d9 = {"ts": ts9, "wallet": wallet, "positions": positions, "events": events, "cursor": cursor}
    if covered_through is not None:
        d9["inc_cov_ts"] = min(ts9, int(covered_through))
    common.atomic_write_json(_fut_path(ex), d9)


def _fut_req(v, what):
    try:
        x9 = float(v) if v is not None and not isinstance(v, bool) and str(v).strip() != "" else None
    except (TypeError, ValueError):
        x9 = None
    if x9 is None or x9 != x9 or abs(x9) == float("inf"):
        raise RuntimeError(f"선물 포지션 {what} 모름 — 스냅숏 보류")
    return x9


def _fut_opt(v):
    try:
        x9 = float(v) if v is not None and not isinstance(v, bool) and str(v).strip() != "" else None
    except (TypeError, ValueError):
        return None
    return x9 if x9 is not None and x9 == x9 and abs(x9) != float("inf") else None


BN_INCOME_MS_PAGES = 20


def _fut_binance(env):
    key, sec = env["TJ_BINANCE_KEY"], env["TJ_BINANCE_SECRET"]

    @_clock_retry
    def fcall(path, extra=None):
        _gov_prepare("fapi.binance.com", path)
        q = dict(extra or {})
        q["timestamp"] = _srv_ms("fapi.binance.com")
        q["recvWindow"] = 10000
        qs = urllib.parse.urlencode(q)
        sig = hmac.new(sec.encode(), qs.encode(), hashlib.sha256).hexdigest()
        return _http_json_err(f"https://fapi.binance.com{path}?{qs}&signature={sig}",
                              {"X-MBX-APIKEY": key})

    st = common.read_json(_fut_path("binance"), {})
    acct = fcall("/fapi/v2/account")
    poss = []
    rows9 = fcall("/fapi/v2/positionRisk")
    if not isinstance(rows9, list) or any(not isinstance(p, dict) for p in rows9):
        raise RuntimeError("binance positionRisk 형식 오류 — 스냅숏 보류")
    for p in rows9:
        amt = _fut_req(p.get("positionAmt"), "수량(positionAmt)")
        if amt == 0:
            continue
        poss.append({"symbol": p.get("symbol"), "side": "LONG" if amt > 0 else "SHORT",
                     "qty": abs(amt), "entry": float(p.get("entryPrice") or 0),
                     "mark": float(p.get("markPrice") or 0),
                     "upnl": _fut_opt(p.get("unRealizedProfit")),
                     "leverage": p.get("leverage"),
                     "margin_mode": (str(p.get("marginType")).lower() if str(p.get("marginType") or "").lower() in ("cross", "isolated") else None),
                     "liq": float(p.get("liquidationPrice") or 0)})
    cross_syms9 = {str(p9.get("symbol") or "") for p9 in poss if p9.get("margin_mode") != "isolated"}
    cur = int((st.get("cursor") or {}).get("income")
              or (int(time.time()) - 150 * 86400) * 1000)
    ev = list(st.get("events") or [])
    seen = {(r.get("uid") or f"{r['t']}:{r['kind']}:{r['amount']}") for r in ev}
    kmap = {"REALIZED_PNL": "REALIZED", "FUNDING_FEE": "FUNDING",
            "COMMISSION": "FEE", "TRANSFER": "TRANSFER",
            "INSURANCE_CLEAR": "REALIZED", "DELIVERED_SETTELMENT": "REALIZED", "DELIVERED_SETTLEMENT": "REALIZED",
            "COMMISSION_REBATE": "FEE", "API_REBATE": "FEE", "REFERRAL_KICKBACK": "FEE"}
    pages = 0
    cov9 = None
    n_ev0 = len(ev)
    while pages < 5:
        time.sleep(PACE)
        rows = fcall("/fapi/v1/income", {"startTime": cur, "limit": 1000}) or []

        def _take(rows9):
            n9 = 0
            for r in rows9:
                uid = f"bn:{r.get('tranId')}:{r.get('incomeType')}:{r.get('time')}"
                if uid in seen:
                    continue
                seen.add(uid)
                n9 += 1
                e9 = {"t": int(r.get("time") or 0), "symbol": r.get("symbol") or "",
                      "kind": kmap.get(r.get("incomeType"), "OTHER"),
                      "amount": float(r.get("income") or 0), "uid": uid}
                if str(r.get("asset") or "").strip():
                    e9["asset"] = str(r.get("asset")).strip().upper()
                ev.append(e9)
            return n9
        _take(rows)
        if rows:
            nxt = max(int(r.get("time") or 0) for r in rows)
            if len(rows) >= 1000 and nxt <= cur:
                for pg9 in range(1, BN_INCOME_MS_PAGES + 1):
                    time.sleep(PACE)
                    rows_ms = fcall("/fapi/v1/income", {"startTime": cur, "endTime": cur, "page": pg9, "limit": 1000}) or []
                    if any(int(r.get("time") or 0) != cur for r in rows_ms):
                        raise RuntimeError("binance income 같은 ms 페이지 응답에 다른 시각 — 스냅샷 보류")
                    if _take(rows_ms) == 0 and pg9 > 1 and len(rows_ms) >= 1000:
                        raise RuntimeError("binance income 같은 ms 페이지가 새 줄을 안 줌(page 미지원?) — 스냅샷 보류")
                    if len(rows_ms) < 1000:
                        break
                else:
                    raise RuntimeError(f"binance income 같은 ms {BN_INCOME_MS_PAGES * 1000}건 초과 — 스냅샷 보류(다음 주기 다시)")
                nxt = cur + 1
            cur = max(cur, nxt)
        if len(rows) < 1000:
            break
        pages += 1
    else:
        cov9 = (int(cur) - 1) // 1000
        log.info("binance 선물 정산 따라잡는 중(5쪽 상한) — 파일 시각 = 확인된 정산 끝 %s", time.strftime("%m-%d %H:%M:%S", time.localtime(cov9)))
    _fnum9 = _fut_opt
    ap9, cmm9 = acct.get("positions"), None
    if (isinstance(ap9, list) and all(isinstance(a9, dict) and isinstance(a9.get("isolated"), bool) for a9 in ap9)
            and cross_syms9 <= {str(a9.get("symbol") or "") for a9 in ap9 if a9["isolated"] is False}):
        vals9 = [_fnum9(a9.get("maintMargin")) for a9 in ap9 if a9["isolated"] is False]
        if all(v9 is not None and v9 >= 0 for v9 in vals9):
            cmm9 = sum(vals9)
    cwb9, cup9 = _fnum9(acct.get("totalCrossWalletBalance")), _fnum9(acct.get("totalCrossUnPnl"))
    cmb9 = (cwb9 + cup9) if cwb9 is not None and cup9 is not None else None
    cross_ok9 = cmm9 is not None and cmb9 is not None
    _fut_write("binance",
               {"balance": float(acct.get("totalWalletBalance") or 0),
                "note": f"가용 증거금 {float(acct.get('availableBalance') or 0):,.2f} USDT",
                "maint_margin": cmm9 if cross_ok9 else None,
                "margin_balance": cmb9 if cross_ok9 else None,
                "init_margin": float(acct.get("totalInitialMargin") or 0),
                "mm_scope": "cross" if cross_ok9 else None},
               poss, ev, {"income": cur}, covered_through=cov9)
    _px_safe("binance", lambda: _px_binance(fcall, ev, ev[n_ev0:]))


BB_TLOG_TYPES = frozenset(("TRADE", "SETTLEMENT", "DELIVERY", "LIQUIDATION", "ADL"))
BB_TLOG_CALLS_MAX = 40
BB_TLOG_OVERLAP_MS = 3600 * 1000
BB_TLOG_LAG_MS = 120 * 1000
BB_TLOG_QUIET_MS = 300 * 1000
BB_TLOG_OFF_MS = 6 * 3600 * 1000


def _bb_num(v):
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return 0.0
    return _fut_opt(v)


def _bb_tlog_events(rows, tl_from, seen, ev):
    n9 = bad9 = 0
    for r in rows:
        if str(r.get("type") or "") not in BB_TLOG_TYPES or str(r.get("category") or "linear") != "linear":
            continue
        rid, t9 = str(r.get("id") or "").strip(), _fut_opt(r.get("transactionTime"))
        cf9, fd9, fe9 = _bb_num(r.get("cashFlow")), _bb_num(r.get("funding")), _bb_num(r.get("fee"))
        if not rid or t9 is None or t9 <= 0 or None in (cf9, fd9, fe9):
            bad9 += 1
            continue
        if int(t9) < tl_from:
            continue
        base9 = {"t": int(t9), "symbol": r.get("symbol") or ""}
        if str(r.get("currency") or "").strip():
            base9["asset"] = str(r.get("currency")).strip().upper()
        for suf9, kind9, amt9 in ((":p", "REALIZED", cf9), (":f", "FEE", -fe9), (":n", "FUNDING", fd9)):
            uid9 = f"bbt:{rid}{suf9}"
            if amt9 == 0 or uid9 in seen:
                continue
            seen.add(uid9)
            e9 = dict(base9, kind=kind9, amount=amt9, uid=uid9)
            if kind9 == "REALIZED":
                if str(r.get("orderId") or "").strip():
                    e9["oid"] = str(r.get("orderId")).strip()
                if str(r.get("type")) == "LIQUIDATION":
                    e9["liq"] = True
            ev.append(e9)
            n9 += 1
    if bad9:
        log.warning("bybit 거래 내역 형식 이상 %d줄 — 그 줄만 뺌(대사 나머지가 흡수)", bad9)
    return n9


def _bb_tlog_window(bcall, cur, s, e, out, budget):
    p9 = cur.get("tlog_pg")
    cursor = ""
    if isinstance(p9, dict):
        ps9, pe9, pc9 = _fut_opt(p9.get("s")), _fut_opt(p9.get("e")), p9.get("cursor")
        if ps9 == s and pe9 is not None and s < pe9 <= s + 7 * DAY * 1000 and isinstance(pc9, str) and pc9:
            e, cursor = int(pe9), pc9
        else:
            cur.pop("tlog_pg", None)
    seen9 = {cursor} if cursor else set()
    while True:
        if budget[0] >= BB_TLOG_CALLS_MAX:
            return None
        q9 = {"accountType": "UNIFIED", "category": "linear", "limit": 50, "startTime": s, "endTime": e}
        if cursor:
            q9["cursor"] = cursor
        time.sleep(PACE)
        budget[0] += 1
        try:
            res9 = bcall("/v5/account/transaction-log", q9)
            rows9 = res9.get("list") if isinstance(res9, dict) else None
            if not isinstance(rows9, list) or any(not isinstance(x9, dict) for x9 in rows9):
                raise RuntimeError("bybit transaction-log 목록 결손·형식 오류")
        except Exception:
            if cursor:
                cur.pop("tlog_pg", None)
            raise
        out.extend(rows9)
        nxt9 = res9.get("nextPageCursor") or ""
        if not nxt9 or not rows9:
            cur.pop("tlog_pg", None)
            return e
        if nxt9 in seen9:
            cur.pop("tlog_pg", None)
            raise RuntimeError("bybit transaction-log 페이지 커서 미전진")
        seen9.add(nxt9)
        cursor = nxt9
        cur["tlog_pg"] = {"s": s, "e": e, "cursor": cursor}


def _bb_tlog_pass(bcall, cur0, ev, seen, now_ms):
    cur = {k: cur0[k] for k in ("tlog_from", "tlog", "tlog_pg", "tlog_off", "tlog_err") if k in cur0}
    tl_from = cur.get("tlog_from")
    raw9 = []
    if not (isinstance(tl_from, int) and not isinstance(tl_from, bool) and tl_from > 0):
        cur.pop("tlog_from", None)
        if now_ms < (_fut_opt(cur.get("tlog_off")) or 0):
            return cur, None, raw9
        try:
            _bb_tlog_window(bcall, {}, now_ms - 3 * BB_TLOG_QUIET_MS, now_ms, raw9, [0])
            tm9 = [int(_fut_opt(r.get("transactionTime")) or 0) for r in raw9 if str(r.get("type") or "") in BB_TLOG_TYPES]
            open9 = False
            if not any(t9 >= now_ms - BB_TLOG_QUIET_MS for t9 in tm9):
                for sc9 in ("USDT", "USDC"):
                    pos9 = bcall("/v5/position/list", {"category": "linear", "settleCoin": sc9, "limit": 200})
                    pp9 = pos9.get("list") if isinstance(pos9, dict) else None
                    if not isinstance(pp9, list) or any(not isinstance(p9, dict) for p9 in pp9):
                        raise RuntimeError("bybit 전환 포지션 목록 결손·형식 오류")
                    if pos9.get("nextPageCursor") or any(_fut_req(p9.get("size"), "수량(size)") != 0 for p9 in pp9):
                        open9 = True
                        break
        except RateLimited:
            return cur, None, []
        except Exception as e9:
            cur["tlog_off"] = now_ms + BB_TLOG_OFF_MS
            log.warning("bybit 거래 내역(transaction-log) 조회 실패 — 선물 수수료·펀딩은 종전처럼 청산 시각(6시간 뒤 다시): %s", _xm(repr(e9))[:160])
            return cur, None, []
        cur.pop("tlog_off", None)
        if any(t9 >= now_ms - BB_TLOG_QUIET_MS for t9 in tm9):
            log.info("bybit 거래 내역 전환 미룸 — 최근 5분 선물 체결·정산 있음(다음 주기)")
            return cur, None, []
        if open9:
            log.info("bybit 거래 내역 전환 미룸 — 미청산 linear 포지션 있음(다음 주기)")
            return cur, None, []
        cur["tlog_from"] = cur["tlog"] = now_ms
        log.info("★bybit 선물 수수료·펀딩 = 낸 시각(transaction-log) 전환 — %s 부터(그 앞은 종전 closed-pnl)★",
                 time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_ms / 1000)))
        return cur, (now_ms - BB_TLOG_LAG_MS) // 1000, []
    c9 = _fut_opt(cur.get("tlog"))
    done9 = int(c9) if c9 is not None and tl_from <= c9 <= now_ms else tl_from
    s9 = max(tl_from, done9 - BB_TLOG_OVERLAP_MS)
    budget = [0]
    try:
        while s9 < now_ms:
            got9 = []
            try:
                e9 = _bb_tlog_window(bcall, cur, s9, min(s9 + 7 * DAY * 1000 - 1000, now_ms), got9, budget)
            finally:
                raw9.extend(got9)
                _bb_tlog_events(got9, tl_from, seen, ev)
            if e9 is None:
                log.info("bybit 거래 내역 따라잡는 중(주기 상한 %d쪽) — 덮은 시각 %s", BB_TLOG_CALLS_MAX,
                         time.strftime("%m-%d %H:%M", time.localtime(done9 / 1000)))
                break
            done9 = max(done9, e9)
            s9 = e9
        cur.pop("tlog_err", None)
    except Exception as e9:
        if now_ms - (_fut_opt(cur.get("tlog_err")) or 0) >= 3600 * 1000:
            cur["tlog_err"] = now_ms
            log.warning("bybit 거래 내역(transaction-log) 수집 실패 — 선물 정산 %s 까지만(다음 주기 다시): %s",
                        time.strftime("%m-%d %H:%M", time.localtime(done9 / 1000)), _xm(repr(e9))[:160])
    cur["tlog"] = done9
    return cur, (min(done9, now_ms) - BB_TLOG_LAG_MS) // 1000, raw9


def _fut_bybit(env):
    key, sec = env["TJ_BYBIT_KEY"], env["TJ_BYBIT_SECRET"]

    @_clock_retry
    def bcall(path, q):
        _gov_prepare("api.bybit.com", path)
        qs = urllib.parse.urlencode(q)
        ts = str(_srv_ms("api.bybit.com"))
        sig = hmac.new(sec.encode(), (ts + key + "10000" + qs).encode(),
                       hashlib.sha256).hexdigest()
        d = http_json(f"https://api.bybit.com{path}?{qs}",
                      {"X-BAPI-API-KEY": key, "X-BAPI-TIMESTAMP": ts,
                       "X-BAPI-RECV-WINDOW": "10000", "X-BAPI-SIGN": sig})
        if d.get("retCode") != 0:
            if str(d.get("retCode")) == "10006":
                raise RateLimited(f"bybit 10006 {_xm(d.get('retMsg'))}", 429)
            raise RuntimeError(f"bybit {d.get('retCode')} {_xm(d.get('retMsg'))}")
        return d.get("result") or {}

    def bpages(path, params):
        params = dict(params)
        cursors = set()
        while True:
            result = bcall(path, params)
            rows = result.get("list")
            if not isinstance(rows, list) or any(not isinstance(r9, dict) for r9 in rows):
                raise RuntimeError(f"bybit {path} 목록 결손·형식 오류 — 스냅숏 보류")
            yield from rows
            cursor = result.get("nextPageCursor") or ""
            if not cursor:
                break
            if not rows or cursor in cursors:
                raise RuntimeError("bybit 선물 페이지 커서 미전진")
            cursors.add(cursor)
            params["cursor"] = cursor
            time.sleep(PACE)

    def bpage(path, params):
        result = bcall(path, params)
        rows = result.get("list")
        if not isinstance(rows, list) or any(not isinstance(r9, dict) for r9 in rows):
            raise RuntimeError(f"bybit {path} 목록 결손·형식 오류 — 가격 보강 보류")
        cur9 = result.get("nextPageCursor")
        return rows, (cur9 if isinstance(cur9, str) else "")

    st = common.read_json(_fut_path("bybit"), {})
    poss = []
    for p in bpages("/v5/position/list", {"category": "linear", "settleCoin": "USDT"}):
        if not isinstance(p, dict):
            raise RuntimeError("bybit position 행 형식 오류 — 스냅숏 보류")
        sz = _fut_req(p.get("size"), "수량(size)")
        if sz == 0:
            continue
        if p.get("side") not in ("Buy", "Sell"):
            raise RuntimeError("bybit position 방향(side) 모름 — 스냅숏 보류")
        poss.append({"symbol": p.get("symbol"),
                     "side": "LONG" if p.get("side") == "Buy" else "SHORT",
                     "qty": sz, "entry": float(p.get("avgPrice") or 0),
                     "mark": float(p.get("markPrice") or 0),
                     "upnl": _fut_opt(p.get("unrealisedPnl")),
                     "leverage": p.get("leverage"),
                     "liq": float(p.get("liqPrice") or 0)})
    ev = list(st.get("events") or [])
    seen = {r.get("uid") for r in ev}
    now_ms = int(time.time() * 1000)
    tlc9, tlcov9, tlraw9 = _bb_tlog_pass(bcall, dict(st.get("cursor") or {}), ev, seen, now_ms)
    tl9 = tlc9.get("tlog_from") if isinstance(tlc9.get("tlog_from"), int) else None

    def _cp_take(c):
        uid = f"bb:{c.get('orderId')}:{c.get('updatedTime')}"
        if uid in seen:
            return
        seen.add(uid)
        t9 = int(c.get("updatedTime") or 0)
        if tl9 is not None and t9 >= tl9:
            ev.append({"t": t9, "symbol": c.get("symbol") or "", "kind": "CLOSEDPNL", "amount": 0.0,
                       "net": _fut_opt(c.get("closedPnl")), "uid": uid})
            return
        ev.append({"t": t9, "symbol": c.get("symbol") or "", "kind": "REALIZED", "amount": float(c.get("closedPnl") or 0), "uid": uid})
    c0 = (st.get("cursor") or {}).get("closed_pnl")
    if isinstance(c0, (int, float)) and c0 > 0:
        s_ms = int(c0) - DAY * 1000
    else:
        bb_t = [int(r.get("t") or 0) for r in ev if str(r.get("uid") or "").startswith("bb:")]
        s_ms = (max(bb_t) - DAY * 1000) if bb_t else now_ms
    s_ms = max(now_ms - 729 * DAY * 1000, min(s_ms, now_ms - 7 * DAY * 1000))
    pxraw = []
    while s_ms < now_ms:
        e_ms = min(s_ms + 7 * DAY * 1000 - 1000, now_ms)
        time.sleep(PACE)
        for c in bpages("/v5/position/closed-pnl", {"category": "linear", "limit": 100,
                                                     "startTime": s_ms, "endTime": e_ms}):
            pxraw.append(c)
            _cp_take(c)
        s_ms = e_ms
    hist_lo = (st.get("cursor") or {}).get("hist_lo")
    tg9 = bf_engine.SINCE.target("bybit")
    if tg9:
        want9 = max(int(tg9) * 1000, now_ms - 729 * DAY * 1000)
        if not (isinstance(hist_lo, (int, float)) and hist_lo <= want9):
            bb_t9 = [int(r.get("t") or 0) for r in ev if str(r.get("uid") or "").startswith("bb:")]
            end9 = min((min(bb_t9) + DAY * 1000) if bb_t9 else now_ms, now_ms)
            try:
                add9, h9 = [], want9
                while h9 < end9:
                    e9 = min(h9 + 7 * DAY * 1000 - 1000, end9)
                    time.sleep(PACE)
                    add9.extend(bpages("/v5/position/closed-pnl", {"category": "linear", "limit": 100, "startTime": h9, "endTime": e9}))
                    h9 = e9
                pxraw.extend(add9)
                for c in add9:
                    _cp_take(c)
                hist_lo = want9
                log.info("bybit 선물 과거 청산손익 채움 %s~ · %d건", time.strftime("%Y-%m-%d", time.gmtime(want9 / 1000)), len(add9))
            except Exception as e:
                log.warning("bybit 선물 과거 청산손익 채움 실패(다음 주기 재시도): %s", str(e)[:160])
    _fut_write("bybit", {"balance": None, "note": "통합계좌에 포함 — 잔고는 현물 집계에"},
               poss, ev, dict({"closed_pnl": now_ms}, **({"hist_lo": hist_lo} if hist_lo else {}), **tlc9),
               covered_through=tlcov9)
    _px_safe("bybit", lambda: _px_bybit(bpage, pxraw, ev, now_ms, tl=(tl9, tlraw9)))


def _okx_notional(p, pos, ct_get):
    nu = _fut_opt(p.get("notionalUsd"))
    if nu:
        return abs(nu)
    cv, mk = _fut_opt(ct_get(p.get("instId"))), _fut_opt(p.get("markPx"))
    return abs(pos) * cv * mk if (cv and mk and cv > 0 and mk > 0) else None


def _fut_okx(env):
    poss = []
    ct9 = []

    def ct_get(iid):
        if not ct9:
            try:
                ct9.append((fut_rcpt.load("okx").get("ct") or {}) if fut_rcpt else {})
            except Exception:
                ct9.append({})
        return ct9[0].get(iid)
    for p in _okx_get(env, "/api/v5/account/positions"):
        if not isinstance(p, dict):
            raise RuntimeError("okx position 행 형식 오류 — 스냅숏 보류")
        pos = _fut_req(p.get("pos"), "수량(pos)")
        if pos == 0:
            continue
        if p.get("posSide") not in ("long", "short", "net"):
            raise RuntimeError("okx position 방향(posSide) 모름 — 스냅숏 보류")
        poss.append({"symbol": p.get("instId"), "notional": _okx_notional(p, pos, ct_get),
                     "side": (str(p.get("posSide")).upper() if p.get("posSide") in ("long", "short")
                              else ("LONG" if pos > 0 else "SHORT")),
                     "qty": abs(pos), "entry": float(p.get("avgPx") or 0),
                     "mark": float(p.get("markPx") or 0),
                     "upnl": _fut_opt(p.get("upl")), "leverage": p.get("lever"),
                     "liq": float(p.get("liqPx") or 0),
                     "settle": (str(p.get("ccy") or "").strip().upper() or None), "inst_type": p.get("instType") or None})
    st = common.read_json(_fut_path("okx"), {})
    ev = list(st.get("events") or [])
    seen = {r.get("uid") for r in ev}
    time.sleep(PACE)
    def bills(path="/api/v5/account/bills", extra=None):
        params = {"instType": "SWAP", "limit": "100"}
        params.update(extra or {})
        cursors = set()
        while True:
            rows = _okx_get(env, path, params)
            yield from rows
            if len(rows) < 100:
                break
            cursor = rows[-1].get("billId")
            if not cursor or cursor in cursors:
                raise RuntimeError("okx 선물 페이지 커서 미전진")
            cursors.add(cursor)
            params["after"] = cursor
            time.sleep(PACE)

    now_ms = int(time.time() * 1000)
    c0 = (st.get("cursor") or {}).get("bills")
    if isinstance(c0, (int, float)) and c0 > 0:
        begin = int(c0) - DAY * 1000
    else:
        ok_t = [int(r.get("t") or 0) for r in ev if str(r.get("uid") or "").startswith("ok:")]
        begin = (max(ok_t) - DAY * 1000) if ok_t else None
    srcs = [bills()]
    if begin is not None and begin < now_ms - 6 * DAY * 1000:
        lo9 = now_ms - 89 * DAY * 1000
        if begin < lo9:
            log.warning("okx 선물 정산 공백이 3개월 초과(%s~) — %s 이전은 API 로 조회 불가",
                        time.strftime("%Y-%m-%d", time.gmtime(begin / 1000)), time.strftime("%Y-%m-%d", time.gmtime(lo9 / 1000)))
            begin = lo9
        srcs.append(bills("/api/v5/account/bills-archive", {"begin": str(begin), "end": str(now_ms - 6 * DAY * 1000)}))
    hist_lo = (st.get("cursor") or {}).get("hist_lo")
    tg9 = bf_engine.SINCE.target("okx")
    if tg9:
        g9 = time.gmtime(now_ms / 1000)
        y9, m9 = g9.tm_year, g9.tm_mon - 3
        if m9 <= 0:
            y9, m9 = y9 - 1, m9 + 12
        floor9 = (calendar.timegm((y9, m9, 1, 0, 0, 0)) + 3600) * 1000
        want9 = max(int(tg9) * 1000, floor9)
        if not (isinstance(hist_lo, (int, float)) and hist_lo <= want9):
            ok_t9 = [int(r.get("t") or 0) for r in ev if str(r.get("uid") or "").startswith("ok:")]
            end9 = min((min(ok_t9) + DAY * 1000) if ok_t9 else now_ms, now_ms - 6 * DAY * 1000)
            try:
                hist9 = list(bills("/api/v5/account/bills-archive", {"begin": str(want9), "end": str(end9)})) if want9 < end9 else []
                srcs.append(hist9)
                hist_lo = want9
                log.info("okx 선물 과거 정산 채움 %s~%s · %d건", time.strftime("%Y-%m-%d", time.gmtime(want9 / 1000)),
                         time.strftime("%Y-%m-%d", time.gmtime(end9 / 1000)), len(hist9))
            except Exception as e:
                log.warning("okx 선물 과거 정산 채움 실패(다음 주기 재시도): %s", str(e)[:160])
    import itertools as _it
    pxraw = []
    for b in _it.chain(*srcs):
        pxraw.append(b)
        bid = b.get("billId")
        t9 = int(b.get("ts") or 0)
        base_uid = f"ok:{bid}"
        pnl = float(b.get("pnl") or 0)
        fee = float(b.get("fee") or 0)
        kind9 = "FUNDING" if str(b.get("type")) == "8" else "REALIZED"
        ccy9 = {"asset": str(b.get("ccy")).strip().upper()} if str(b.get("ccy") or "").strip() else {}
        if pnl != 0 and base_uid + ":p" not in seen:
            seen.add(base_uid + ":p")
            ev.append(dict({"t": t9, "symbol": b.get("instId") or "", "kind": kind9,
                            "amount": pnl, "uid": base_uid + ":p"}, **ccy9))
        if fee != 0 and base_uid + ":f" not in seen:
            seen.add(base_uid + ":f")
            ev.append(dict({"t": t9, "symbol": b.get("instId") or "", "kind": "FEE",
                            "amount": fee, "uid": base_uid + ":f"}, **ccy9))
    _fut_write("okx", {"balance": None, "note": "트레이딩 계정에 포함 — 잔고는 현물 집계에"},
               poss, ev, dict({"bills": now_ms}, **({"hist_lo": hist_lo} if hist_lo else {})))
    _px_safe("okx", lambda: _px_okx(bills, pxraw, now_ms))


PX_CALLS_MAX = 20
PX_OKX_CT_MAX = 5
PX_OKX_BF_V = getattr(fut_rcpt, "OKX_BF_V", 2)
PX_BN_FAIL_MAX = 3
PX_BN_REPLAN_MS = DAY * 1000


def _px_safe(ex, fn):
    if fut_rcpt is None:
        return
    try:
        fn()
    except (Exception, SystemExit) as e:
        log.warning("%s 선물 가격 옆 파일 실패(정산 무관 · 다음 주기): %s", ex, _xm(repr(e))[:160])


PX_BB_EX_OFF_MS = 6 * 3600 * 1000
PX_BB_EX_PAD_MS = 30 * DAY * 1000


def _px_bb_window(bpage, cur, slot, path, s, e, conv, rows, budget):
    p9 = cur.get(slot)
    cursor = ""
    if isinstance(p9, dict):
        ps, pe, pc = fut_rcpt.num(p9.get("s")), fut_rcpt.num(p9.get("e")), p9.get("cursor")
        if ps is not None and pe is not None and 0 < ps <= pe and pe - ps < 7 * DAY * 1000 and isinstance(pc, str) and pc:
            s, e, cursor = int(ps), int(pe), pc
        else:
            cur.pop(slot, None)
    seen = {cursor} if cursor else set()
    while True:
        if budget[0] >= PX_CALLS_MAX:
            return None
        params = {"category": "linear", "limit": 100, "startTime": s, "endTime": e}
        if cursor:
            params["cursor"] = cursor
        time.sleep(PACE)
        budget[0] += 1
        try:
            got, nxt = bpage(path, params)
        except RateLimited:
            raise
        except Exception:
            if cursor:
                cur.pop(slot, None)
            raise
        rows.extend(conv(got))
        if not nxt or not got:
            cur.pop(slot, None)
            return s, e
        if nxt in seen:
            cur.pop(slot, None)
            raise RuntimeError("bybit 선물 페이지 커서 미전진")
        seen.add(nxt)
        cursor = nxt
        cur[slot] = {"s": s, "e": e, "cursor": cursor}


def _px_bybit_exec(bpage, cur, ev, now_ms, budget, rows):
    hi0 = fut_rcpt.num(cur.get("ex_hi"))
    first = hi0 is None
    s = int(hi0) - 3600 * 1000 if hi0 is not None and now_ms - 729 * DAY * 1000 < hi0 <= now_ms else now_ms - 7 * DAY * 1000 + 1000
    while s < now_ms:
        w = _px_bb_window(bpage, cur, "ex_rp", "/v5/execution/list", s, min(s + 7 * DAY * 1000 - 1000, now_ms), fut_rcpt.rows_bybit_exec, rows, budget)
        if w is None:
            return
        if first and not cur.get("ex_done") and fut_rcpt.num(cur.get("ex_lo")) is None:
            cur["ex_lo"] = w[0]
        first = False
        cur["ex_hi"] = w[1]
        s = w[1]
    if not cur.get("ex_done"):
        h9 = fut_rcpt.num(cur.get("ex_lo"))
        if h9 is None:
            return
        bb_t = [int(r.get("t") or 0) for r in ev if str(r.get("uid") or "").startswith(("bb:", "bbt:"))]
        if not bb_t:
            return
        lo = max(now_ms - 729 * DAY * 1000, min(bb_t) - PX_BB_EX_PAD_MS)
        hi = int(h9)
        while hi > lo:
            w = _px_bb_window(bpage, cur, "ex_hp", "/v5/execution/list", max(lo, hi - 7 * DAY * 1000 + 1000), hi, fut_rcpt.rows_bybit_exec, rows, budget)
            if w is None:
                return
            hi = w[0]
            cur["ex_lo"] = hi
        cur["ex_done"] = True
        cur.pop("ex_lo", None)
        log.info("bybit 선물 진입 체결 과거 채움 끝")


def _px_bybit(bpage, raw, ev, now_ms, tl=None):
    tl_from, tlraw = tl if isinstance(tl, tuple) and len(tl) == 2 else (None, ())
    st = fut_rcpt.load("bybit")
    cur = dict(st.get("cursor") or {})
    rows, budget = fut_rcpt.rows_bybit(raw), [0]
    if tl_from is not None:
        rows.extend(fut_rcpt.rows_bybit_tlog(tlraw, cp=raw))
    try:
        if not cur.get("bf_done"):
            bb_t = [int(r.get("t") or 0) for r in ev if str(r.get("uid") or "").startswith("bb:")]
            lo = max(now_ms - 729 * DAY * 1000, (min(bb_t) - DAY * 1000) if bb_t else now_ms)
            hi9 = fut_rcpt.num(cur.get("bf_hi"))
            hi = int(hi9) if hi9 is not None and lo < hi9 <= now_ms else now_ms - 6 * DAY * 1000
            while hi > lo:
                w = _px_bb_window(bpage, cur, "bf_pg", "/v5/position/closed-pnl", max(lo, hi - 7 * DAY * 1000 + 1000), hi, fut_rcpt.rows_bybit, rows, budget)
                if w is None:
                    break
                hi = w[0]
                cur["bf_hi"] = hi
            if hi <= lo:
                cur["bf_done"] = True
                cur.pop("bf_hi", None)
                log.info("bybit 선물 가격 과거 채움 끝(%d콜)", budget[0])
        if now_ms >= (fut_rcpt.num(cur.get("ex_off")) or 0):
            try:
                _px_bybit_exec(bpage, cur, ev, now_ms, budget, rows)
                cur.pop("ex_off", None)
            except RateLimited:
                raise
            except Exception as e9:
                cur["ex_off"] = now_ms + PX_BB_EX_OFF_MS
                log.warning("bybit 선물 진입 체결 조회 실패(6시간 뒤 다시 · 정산 무관): %s", _xm(repr(e9))[:160])
    finally:
        fut_rcpt.update("bybit", rows, now_ms, cursor=cur,
                        keep=None if tl_from is None else (lambda r9: not (str(r9.get("uid") or "").startswith("bb:") and r9["ts_ms"] >= tl_from)))


def _px_okx(bills, raw, now_ms):
    st = fut_rcpt.load("okx")
    cur, ct = dict(st.get("cursor") or {}), dict(st.get("ct") or {})
    rows = fut_rcpt.rows_okx(raw)
    try:
        if not cur.get("bf_done") or cur.get("bf_v") != PX_OKX_BF_V:
            job = cur.get("bf_job") if isinstance(cur.get("bf_job"), dict) else {}
            b9, e9, a9 = fut_rcpt.num(job.get("b")), fut_rcpt.num(job.get("e")), job.get("after")
            if job.get("v") != PX_OKX_BF_V or b9 is None or e9 is None or not 0 < b9 < e9:
                b9, e9, a9 = now_ms - 89 * DAY * 1000, now_ms - 6 * DAY * 1000, None
            a9 = fut_rcpt.safe(a9, 40) if isinstance(a9, str) else ""
            ex9 = dict({"begin": str(int(b9)), "end": str(int(e9))}, **({"after": a9} if a9 else {}))
            got, last9, done9 = [], a9, False
            try:
                for b in bills("/api/v5/account/bills-archive", ex9):
                    got.append(b)
                    if isinstance(b, dict) and b.get("billId"):
                        last9 = fut_rcpt.safe(b.get("billId"), 40) or last9
                    if len(got) >= PX_CALLS_MAX * 100:
                        break
                else:
                    done9 = True
            finally:
                rows += fut_rcpt.rows_okx(got)
                if done9:
                    cur["bf_done"], cur["bf_v"] = True, PX_OKX_BF_V
                    cur.pop("bf_job", None)
                    log.info("okx 선물 가격 과거 채움 끝(bills %d건)", len(got))
                else:
                    cur["bf_job"] = {"v": PX_OKX_BF_V, "b": int(b9), "e": int(e9), "after": last9}
                    log.info("okx 선물 가격 과거 채움 이어서(이번 bills %d건 · 다음 주기)", len(got))
        miss = {k: v for k, v in (cur.get("ct_miss") or {}).items() if isinstance(v, (int, float)) and v > now_ms - DAY * 1000}
        need = sorted({r["symbol"] for r in rows + list(st.get("rows") or []) if isinstance(r, dict) and r.get("qty_ct") and r.get("symbol") not in ct and r.get("symbol") not in miss})
        for iid in need[:PX_OKX_CT_MAX]:
            time.sleep(PACE)
            miss[iid] = now_ms
            d9 = http_json("https://www.okx.com/api/v5/public/instruments?" + urllib.parse.urlencode({"instType": "SWAP", "instId": iid}))
            if isinstance(d9, dict) and str(d9.get("code")) == "0":
                ct.update(fut_rcpt.okx_ct(d9.get("data")))
            if iid in ct:
                miss.pop(iid, None)
        cur["ct_miss"] = miss
    finally:
        fut_rcpt.update("okx", rows, now_ms, cursor=cur, ct=ct)


def _px_binance(fcall, ev, new_ev):
    now_ms = int(time.time() * 1000)
    st = fut_rcpt.load("binance")
    cur = dict(st.get("cursor") or {})

    def ok_job(x):
        return (isinstance(x, (list, tuple)) and len(x) == 3 and isinstance(x[0], str) and x[0]
                and fut_rcpt.num(x[1]) is not None and fut_rcpt.num(x[2]) is not None and fut_rcpt.num(x[1]) <= fut_rcpt.num(x[2]))
    plan = [[x[0], int(x[1]), int(x[2])] for x in (cur.get("bf_plan") if isinstance(cur.get("bf_plan"), list) else []) if ok_job(x)]
    if not cur.get("bf_done") and not isinstance(cur.get("bf_plan"), list):
        plan = fut_rcpt.bn_plan(ev, now_ms)
        log.info("binance 선물 가격 과거 채움 계획 %d창", len(plan))
    elif cur.get("bf_done") and not plan and now_ms - (fut_rcpt.num(cur.get("rp_at")) or 0) >= PX_BN_REPLAN_MS:
        lo9 = now_ms - fut_rcpt.RETAIN_MS["binance"]
        tried = {u for u in (cur.get("rp_tried") if isinstance(cur.get("rp_tried"), list) else []) if isinstance(u, str)}
        miss = [e for e in fut_rcpt.bn_unmatched(ev, st.get("rows"), now_ms) if e.get("uid") not in tried]
        plan = fut_rcpt.bn_plan(miss, now_ms)
        live9 = {e.get("uid") for e in ev if isinstance(e, dict) and (fut_rcpt.num(e.get("t")) or 0) >= lo9}
        cur["rp_tried"] = sorted((tried & live9) | {e.get("uid") for e in miss if isinstance(e.get("uid"), str)})
        cur["rp_at"] = now_ms
        if plan:
            log.info("binance 선물 가격 다시 계획 — 가격 행 없는 정산 %d건 · %d창", len(miss), len(plan))
    jobs = fut_rcpt.bn_plan(new_ev, now_ms) + plan
    fails = {k: v for k, v in (cur.get("bf_fail") or {}).items() if isinstance(v, int)} if isinstance(cur.get("bf_fail"), dict) else {}
    rows, calls = [], 0
    try:
        while jobs and calls < PX_CALLS_MAX:
            sym, s9, e9 = jobs[0]
            start, end, finished = int(s9), int(e9), False
            try:
                while calls < PX_CALLS_MAX:
                    time.sleep(PACE)
                    got = fcall("/fapi/v1/userTrades", {"symbol": sym, "startTime": start, "endTime": end, "limit": 1000})
                    calls += 1
                    if not isinstance(got, list):
                        raise RuntimeError("binance userTrades 형식 오류")
                    rows += fut_rcpt.rows_binance(got)
                    if len(got) < 1000:
                        finished = True
                        break
                    nxt = max((int(fut_rcpt.num(t.get("time")) or 0) for t in got if isinstance(t, dict)), default=start)
                    if nxt >= end:
                        finished = True
                        break
                    if nxt <= start:
                        log.warning("binance userTrades %s 같은 ms 1,000건 넘음 — 그 창 나머지는 건너뜀(가격 일부 없음)", sym)
                        finished = True
                        break
                    start = nxt
                    jobs[0] = [sym, start, end]
            except RateLimited:
                raise
            except Exception as e9x:
                fk = f"{sym}:{end}"
                n9 = fails.get(fk, 0) + 1
                msg9 = _xm(repr(e9x))
                if n9 >= PX_BN_FAIL_MAX or '"code":-1121' in msg9:
                    jobs.pop(0)
                    fails.pop(fk, None)
                    log.warning("binance 선물 가격 창 버림(%s · %d번 실패 — 다른 창은 계속): %s", sym, n9, msg9[:160])
                else:
                    fails[fk] = n9
                    jobs.append(jobs.pop(0))
                    log.warning("binance 선물 가격 창 실패 %d/%d(%s — 맨 뒤로 · 다음 주기): %s", n9, PX_BN_FAIL_MAX, sym, msg9[:160])
                break
            if finished:
                jobs.pop(0)
                fails.pop(f"{sym}:{end}", None)
            else:
                jobs[0] = [sym, start, end]
    finally:
        cur["bf_plan"] = jobs
        live_f = {f"{x[0]}:{int(x[2])}" for x in jobs}
        cur["bf_fail"] = {k: v for k, v in fails.items() if k in live_f}
        if not cur["bf_fail"]:
            cur.pop("bf_fail", None)
        if not jobs:
            if not cur.get("bf_done"):
                log.info("binance 선물 가격 과거 채움 끝")
                cur["rp_at"] = now_ms
            cur["bf_done"] = True
            cur.pop("bf_plan", None)
        fut_rcpt.update("binance", rows, now_ms, cursor=cur)


def _keep_view(bp9, pend_bp):
    try:
        best = None
        for p9 in (bp9, pend_bp):
            if os.path.exists(p9):
                d9 = common.read_json(p9, {})
                if isinstance(d9, dict) and isinstance(d9.get("balances"), dict):
                    if best is None or float(d9.get("ts") or 0) > float(best.get("ts") or 0):
                        best = d9
        if best is None:
            return
        vp9 = bp9 + ".view"
        cur9 = common.read_json(vp9, {}) if os.path.exists(vp9) else {}
        if not isinstance(cur9, dict) or float(best.get("ts") or 0) >= float(cur9.get("ts") or 0):
            common.atomic_write_json(vp9, best)
    except (Exception, SystemExit) as e:
        log.warning("잔고 표시 사본 보존 실패: %s", repr(e)[:120])


def futures_snapshot_all(env):
    for ex, fn, need in (("binance", _fut_binance, ("TJ_BINANCE_KEY", "TJ_BINANCE_SECRET")),
                         ("bybit", _fut_bybit, ("TJ_BYBIT_KEY", "TJ_BYBIT_SECRET")),
                         ("okx", _fut_okx, ("TJ_OKX_KEY", "TJ_OKX_SECRET",
                                            "TJ_OKX_PASSPHRASE"))):
        if time.time() < _FUT_OFF.get(ex, 0) or not all(env.get(k) for k in need):
            continue
        try:
            fn(env)
        except (Exception, SystemExit) as e:
            msg = _xm(repr(e))
            if any(k in msg for k in ("HTTP 401", "HTTP 403", "HTTPError 401",
                                      "HTTPError 403", '"code":-2015', '"code":-1002')):
                _FUT_OFF[ex] = time.time() + DENY_COOL_SEC
                log.error("★%s 선물 스냅샷 6h 비활성(권한/IP 불일치) — 만료 후 자동 재시도: %s★",
                          ex, msg[:120])
            else:
                log.warning("%s 선물 스냅샷 실패(다음 주기): %s", ex, msg[:140])


@_clock_retry
def _bn_deriv_get(env, host, path, params=None):
    _gov_prepare(host, path)
    key, sec = env["TJ_BINANCE_KEY"], env["TJ_BINANCE_SECRET"]
    q = dict(params or {})
    q["timestamp"] = _srv_ms(host)
    q["recvWindow"] = 10000
    qs = urllib.parse.urlencode(q)
    sig = hmac.new(sec.encode(), qs.encode(), hashlib.sha256).hexdigest()
    return _http_json_err(f"https://{host}{path}?{qs}&signature={sig}", {"X-MBX-APIKEY": key})


@_clock_retry
def _kucoin_fut_get(env, path_with_qs):
    _gov_prepare("api-futures.kucoin.com", path_with_qs.split("?", 1)[0])
    key, sec, pph = env["TJ_KUCOIN_KEY"], env["TJ_KUCOIN_SECRET"], env["TJ_KUCOIN_PASSPHRASE"]
    ts = str(_srv_ms("api-futures.kucoin.com"))
    sig = base64.b64encode(hmac.new(sec.encode(), (ts + "GET" + path_with_qs).encode(), hashlib.sha256).digest()).decode()
    pph_sig = base64.b64encode(hmac.new(sec.encode(), pph.encode(), hashlib.sha256).digest()).decode()
    d = http_json("https://api-futures.kucoin.com" + path_with_qs,
                  {"KC-API-KEY": key, "KC-API-SIGN": sig, "KC-API-TIMESTAMP": ts,
                   "KC-API-PASSPHRASE": pph_sig, "KC-API-KEY-VERSION": "2"})
    if not isinstance(d, dict) or d.get("code") != "200000":
        raise RuntimeError(f"kucoin futures {_xm((d or {}).get('code') if isinstance(d, dict) else '')} {_xm((d or {}).get('msg') if isinstance(d, dict) else str(d)[:80])}")
    return d.get("data")


def _kucoin_pub_get(path_with_qs):
    d = http_json("https://api.kucoin.com" + path_with_qs)
    if not isinstance(d, dict) or d.get("code") != "200000":
        raise RuntimeError(f"kucoin public {_xm((d or {}).get('msg') if isinstance(d, dict) else str(d)[:80])}")
    return d.get("data")


def _lev_body(fn, rl_host=None):
    def f(*a, **k):
        try:
            return fn(*a, **k)
        except urllib.error.HTTPError as e:
            try:
                body = _err_body(e)[:300]
            except Exception:
                body = ""
            if rl_host and e.code == 403 and "too frequent" in body.lower():
                k9 = _rl_key(rl_host)
                _RL_OFF[k9] = max(float(_RL_OFF.get(k9, 0) or 0), time.time() + 600.0)
                log.warning("%s HTTP 403(IP 한도 — access too frequent) — 600초 동안 이 호스트 호출 중단", rl_host)
                raise RateLimited(f"{rl_host} HTTP 403 — access too frequent · 600초 백오프", 403) from None
            raise RuntimeError(f"HTTP {e.code}: {_xm(body)}") from None
    return f


def leverage_getters(env):
    return {
        "binance": {"sapi": lambda p, q=None: _binance_signed(env, p, q),
                    "fapi": lambda p, q=None: _bn_deriv_get(env, "fapi.binance.com", p, q),
                    "dapi": lambda p, q=None: _bn_deriv_get(env, "dapi.binance.com", p, q)},
        "bybit": {"get": _lev_body(lambda p, q=None: _bybit_get(env, p, q), rl_host="api.bybit.com")},
        "okx": {"get": _lev_body(lambda p, q=None: _okx_get(env, p, q))},
        "kucoin": {"get": _lev_body(lambda p: _kucoin_get(env, p)), "fut": _lev_body(lambda p: _kucoin_fut_get(env, p)), "pub": _lev_body(_kucoin_pub_get)},
        "gate": {"get": _lev_body(lambda p, q=None: _gate_get(env, p, q))},
    }


def leverage_pass(env, cfg=None):
    cfg = cfg if isinstance(cfg, dict) else {}
    xc9 = cfg.get("exf")
    if isinstance(xc9, dict) and xc9.get("leverage") is False:
        return None
    import leverage
    doc = leverage.collect(env, leverage_getters(env), now=int(time.time()), cycle_sec=common.exf_poll_sec(cfg),
                           fresh_sec=common.exf_fresh_sec(cfg), pace=lambda: time.sleep(PACE), log=log, cfg=cfg)
    leverage.write(doc)
    bad = [f"{p['ex']}:{p['product']}={p['status']}" for p in doc["products"] if p["status"] in ("error", "rate_limited")]
    if bad:
        log.info("레버리지·대출 스냅숏: 조회 실패 %d줄(%s) — 직전 값은 '낡음' 표시로 유지", len(bad), ", ".join(bad)[:200])
    return doc


EXT_CHUNK = 30 * DAY
EXT_BUDGET = 240
EXT_HARD_LIMIT = {("okx", "fills"): 90 * DAY}
EXT_HARD_LIMIT[("bybit", "fills")] = 730 * DAY - DAY
_EXT_LIMIT_RX = (
    (re.compile(r"(?:earlier|older) than (\d+) years?", re.I), 365),
    (re.compile(r"(?:earlier|older) than (\d+) days?", re.I), 1),
    (re.compile(r"more than (\d+) days", re.I), 1),
)
_EXT_LIMIT_STRICT = 2
_EXT_RANGE_WORDS = re.compile(r"range|interval|span|between|window|period|duration|start_?time|end_?time|startAt|endAt|"
                              r"time difference|gap|exceed|too (?:long|wide|large)|maximum", re.I)
EXT_SOFT_LIMIT_SEC = 7 * DAY


def _okx_fills_floor(now: int) -> int:
    t = time.gmtime(now)
    y, m = t.tm_year, t.tm_mon - 3
    while m <= 0:
        y, m = y - 1, m + 12
    import calendar
    return int(calendar.timegm((y, m, 1, 0, 0, 0)))


def ext_fills_floor(ex: str, now: int, ext: dict = None):
    cands = []
    if ex == "okx":
        cands.append(_okx_fills_floor(now))
    elif (ex, "fills") in EXT_HARD_LIMIT:
        cands.append(int(now - EXT_HARD_LIMIT[(ex, "fills")]))
    days = (ext or {}).get("fills_hard_days")
    if days:
        try:
            cands.append(int(now - float(days) * DAY + DAY))
        except (TypeError, ValueError):
            pass
    soft = (ext or {}).get("fills_soft_limit")
    if isinstance(soft, dict):
        try:
            if now < float(soft.get("until") or 0):
                cands.append(int(now - float(soft["days"]) * DAY + DAY))
        except (TypeError, ValueError, KeyError):
            pass
    return max(cands) if cands else None


def _learn_fills_limit(msg: str):
    return _fills_limit_kind(msg)[0]


def _fills_limit_kind(msg: str):
    m9 = msg or ""
    for i, (rx, mul) in enumerate(_EXT_LIMIT_RX):
        m = rx.search(m9)
        if m:
            try:
                d9 = int(m.group(1)) * mul
            except ValueError:
                return None, None
            if i >= _EXT_LIMIT_STRICT and _EXT_RANGE_WORDS.search(m9):
                return None, None
            return d9, ("strict" if i < _EXT_LIMIT_STRICT else "soft")
    return None, None


def ext_trigger_target(now: int, window: int):
    target9 = bf_engine.SINCE.target(None) or (now - window)
    if any(int(bf_engine.SINCE.target(ex9) or target9) < now - window for ex9 in FETCHERS):
        return int(target9)
    return None


def extension_pass(env: dict, state: dict, writer, target: int, now: int, window: int):
    import threading as _th
    from concurrent.futures import ThreadPoolExecutor as _TPE
    wlock = _th.Lock()
    active = [ex for ex, (fn, need) in FETCHERS.items() if all(env.get(k) for k in need) and ex in state]
    prog = bf_engine.progress("exf")

    def _save():
        with wlock:
            for i9 in range(3):
                try:
                    snap9 = json.loads(json.dumps(state, ensure_ascii=False))
                    break
                except RuntimeError:
                    if i9 == 2:
                        raise
            common.atomic_write_json(STATE_PATH, snap9)

    def one(ex, target=target):
        target = min(int(target), int(bf_engine.SINCE.target(ex) or target))
        if target >= now - window:
            return
        fn = FETCHERS[ex][0]
        st = state[ex]
        ext = st.setdefault("ext", {})
        if ext.get("fills_hard_days") and ext.get("fills_hard_src") != "strict":
            try:
                d9 = int(float(ext["fills_hard_days"]))
            except (TypeError, ValueError):
                d9 = 0
            ext.pop("fills_hard_days", None)
            if d9 > 0:
                ext["fills_soft_limit"] = {"days": d9, "until": int(now + EXT_SOFT_LIMIT_SEC)}
            log.info("%s 옛 체결 보존 한도(%s일 · 출처 미상) → 7일 임시 한도로 전환(만료 뒤 다시 시도)", ex, d9)
            _save()
        if ext.get("target") != target:
            ext["target"] = int(target)
            ext["n_emit"] = 0
            ext.setdefault("wd_from", int(now - window))
            ext.setdefault("fills_from", int(now - window))
        hi0 = int(ext.setdefault("hi0", max(int(ext["wd_from"]), int(ext["fills_from"]), int(now - window))))
        deadline = time.time() + EXT_BUDGET
        n_w = n_f = 0
        while ext["wd_from"] > target and time.time() < deadline:
            a, b = max(int(target), int(ext["wd_from"]) - EXT_CHUNK), int(ext["wd_from"])
            try:
                w_rows, d_rows = fn(env, a, b)
            except Exception as e:
                ext["wd_err"] = _xm(repr(e))[:160]
                break
            seen, seen_txids, seen_dest = st["seen"], st.setdefault("seen_txids", {}), st.setdefault("seen_dest", {})
            if ex in _DEP_DENIED:
                h9 = st.get("dep_hold")
                st["dep_hold"] = min(int(h9), int(a)) if isinstance(h9, int) else int(a)
            new_w = _rows_to_emit(w_rows, seen, seen_txids, seen_dest)
            new_d = _rows_to_emit(d_rows, seen, seen_txids)
            if new_w or new_d:
                _invalidate_balance_snapshot(ex)
                with wlock:
                    writer.append({"v": 1, "kind": "ex_snapshot", "exchange": ex, "ts": int(time.time()),
                                   "deposits": new_d, "withdraws": new_w, "ext": True})
                _mark_seen(new_w + new_d, seen, seen_txids, seen_dest, st.setdefault("pend_ts", {}))
                n_w += len(new_w) + len(new_d)
            eb_new = {str(r.get("currency") or "").upper() for r in (w_rows or []) + (d_rows or []) if r.get("currency")}
            if eb_new:
                f9 = st.setdefault("fills", {})
                eb0 = set(f9.get("extra_bases") or [])
                if not eb_new <= eb0:
                    f9["extra_bases"] = sorted(eb0 | eb_new)
                ext["n_emit"] = int(ext.get("n_emit") or 0) + len(new_w) + len(new_d)
            ext["wd_from"] = a
            ext.pop("wd_err", None)
            _save()
        floor = ext_fills_floor(ex, now, ext)
        stop_at = max(int(target), floor) if floor else int(target)
        if floor and floor > target:
            ext["fills_limit"] = f"API 이력 한도: {time.strftime('%Y-%m-%d', time.gmtime(floor))} 이전 체결은 이 API 로 불가"
        if ex == "binance" and ext["fills_from"] > stop_at and time.time() < deadline:
            rp = ext.get("bn_replay")
            if not isinstance(rp, dict) or int(rp.get("lo") or 0) != int(stop_at):
                rp = ext["bn_replay"] = {"lo": int(stop_at), "hi": int(ext["fills_from"]), "pos": {}, "done": []}
                _save()

            def _emit(rows):
                nonlocal n_f
                _invalidate_balance_snapshot(ex)
                with wlock:
                    for i in range(0, len(rows), 500):
                        writer.append({"v": 1, "kind": "exf_fills", "exchange": ex, "ts": int(time.time()),
                                       "fills": rows[i:i + 500], "ext": True})
                n_f += len(rows)
                ext["n_emit"] = int(ext.get("n_emit") or 0) + len(rows)
            try:
                fin = FILL_REPLAY["binance"](env, st.get("fills") or {}, rp, deadline, _emit, _save)
            except Exception as e:
                ext["fills_err"] = _xm(repr(e))[:160]
                fin = False
            if fin:
                ext["fills_from"] = int(stop_at)
                ext.pop("fills_err", None)
            _save()
        if ex == "binance" and ext["fills_from"] <= stop_at and not ext.get("bn_gap_done") and time.time() < deadline:
            def _emit_g(rows):
                nonlocal n_f
                _invalidate_balance_snapshot(ex)
                with wlock:
                    for i in range(0, len(rows), 500):
                        writer.append({"v": 1, "kind": "exf_fills", "exchange": ex, "ts": int(time.time()),
                                       "fills": rows[i:i + 500], "ext": True})
                n_f += len(rows)
                ext["n_emit"] = int(ext.get("n_emit") or 0) + len(rows)
            bn_gap_step(env, st, ext, stop_at, now, deadline, _emit_g, _save)
        while ex != "binance" and ext["fills_from"] > stop_at and time.time() < deadline:
            a, b = max(stop_at, int(ext["fills_from"]) - EXT_CHUNK), int(ext["fills_from"])
            if ex == "bithumb" and "bithumb" in FILL_FETCHERS:
                def _emit_bt(rows):
                    nonlocal n_f
                    _invalidate_balance_snapshot(ex)
                    with wlock:
                        for i in range(0, len(rows), 500):
                            writer.append({"v": 1, "kind": "exf_fills", "exchange": ex, "ts": int(time.time()),
                                           "fills": rows[i:i + 500], "ext": True})
                    n_f += len(rows)
                    ext["n_emit"] = int(ext.get("n_emit") or 0) + len(rows)
                try:
                    fin = _bithumb_ext_fills(_bithumb_caller(env), st.get("fills") or {}, ext, a, b, deadline, _emit_bt, _save)
                except Exception as e:
                    ext["fills_err"] = _xm(repr(e))[:160]
                    _save()
                    break
                if not fin:
                    ext.pop("fills_err", None)
                    _save()
                    break
                ext.pop("bt_scan", None)
                ext["fills_from"] = a
                ext.pop("fills_err", None)
                _save()
                continue
            try:
                cp9 = json.loads(json.dumps(st.get("fills") or {}))
                rows = FILL_FETCHERS[ex](env, cp9, a, b)
                if _bb_hold_keep(st, cp9):
                    _save()
            except Exception as e:
                ext["fills_err"] = _xm(repr(e))[:160]
                days9, kind9 = _fills_limit_kind(repr(e))
                sl9 = ext.get("fills_soft_limit") if isinstance(ext.get("fills_soft_limit"), dict) else {}
                if days9 and ((kind9 == "strict" and int(ext.get("fills_hard_days") or 0) != days9)
                              or (kind9 == "soft" and (int(sl9.get("days") or 0) != days9 or now >= float(sl9.get("until") or 0)))):
                    if kind9 == "strict":
                        ext["fills_hard_days"] = days9
                        ext["fills_hard_src"] = "strict"
                    else:
                        ext["fills_soft_limit"] = {"days": days9, "until": int(now + EXT_SOFT_LIMIT_SEC)}
                    fl9 = ext_fills_floor(ex, now, ext)
                    if fl9 and fl9 > stop_at:
                        stop_at = fl9
                        ext["fills_limit"] = (f"API 이력 한도: {time.strftime('%Y-%m-%d', time.gmtime(fl9))} 이전 체결은 이 API 로 불가"
                                              f"(거래소 응답 {days9}일)")
                        log.warning("%s 과거 체결 보존 한도 %d일(API 응답) — %s 에서 멈춤", ex, days9,
                                    time.strftime("%Y-%m-%d", time.gmtime(fl9)))
                        _save()
                        continue
                break
            rows = [f for f in rows if a * 1000 <= int(f.get("ts") or 0) <= b * 1000]
            if rows:
                _invalidate_balance_snapshot(ex)
                with wlock:
                    for i in range(0, len(rows), 500):
                        writer.append({"v": 1, "kind": "exf_fills", "exchange": ex, "ts": int(time.time()),
                                       "fills": rows[i:i + 500], "ext": True})
                n_f += len(rows)
                ext["n_emit"] = int(ext.get("n_emit") or 0) + len(rows)
            ext["fills_from"] = a
            ext.pop("fills_err", None)
            _save()
        if ext["fills_from"] <= stop_at:
            ext.pop("fills_err", None)
        span = max(1, hi0 - target)
        part9 = _bithumb_ext_part(ext) if ex == "bithumb" else 0
        done = (min(span, max(0, hi0 - ext["wd_from"])) + (min(span, max(0, hi0 - ext["fills_from"] + part9))
                                                           if ext["fills_from"] > stop_at else span)) / 2.0
        gap9 = ex == "binance" and not ext.get("bn_gap_done")
        if gap9 and ext["fills_from"] <= stop_at:
            fs9 = st.get("fills") or {}
            nk9 = len(fs9.get("pair_cursor") or {}) + len(fs9.get("margin_cursor") or {})
            done = min(done, span * len((ext.get("bn_gap") or {}).get("done") or []) / max(1, nk9))
        phase9 = "extend" if (ext["wd_from"] > target or ext["fills_from"] > stop_at or gap9) else "done"
        note9 = ext.get("fills_limit") or ext.get("wd_err") or ext.get("fills_err")
        sig9 = [phase9, int(ext["wd_from"]), int(ext["fills_from"]), note9, int(target), int(ext.get("n_emit") or 0), int(part9), int(done)]
        if ext.get("_psig") != sig9 or (phase9 != "done" and time.time() - float(ext.get("_pat") or 0) >= 1800):
            prog.update(f"{ex}:extend", phase=phase9, unit="sec", done=int(done), total=int(span),
                        target=time.strftime("%Y-%m-%d", time.gmtime(target)), note=note9,
                        wd_from=ext["wd_from"], fills_from=ext["fills_from"], emitted=int(ext.get("n_emit") or 0))
            old9 = ext.get("_psig")
            keep9 = (phase9 == "done" and isinstance(old9, list) and len(old9) >= 7 and old9[0] == "done"
                     and all(old9[i] == sig9[i] for i in (1, 2, 4, 5, 6)) and ext.get("_pat"))
            ext["_psig"], ext["_pat"] = sig9, (int(ext["_pat"]) if keep9 else int(time.time()))
            _save()
        if n_w or n_f:
            log.info("%s 과거 창 확장: 입출금 %d · 체결 %d (하한 입출금 %s / 체결 %s)", ex, n_w, n_f,
                     time.strftime("%Y-%m-%d", time.gmtime(ext["wd_from"])),
                     time.strftime("%Y-%m-%d", time.gmtime(ext["fills_from"])))

    if not active:
        return
    with _TPE(max_workers=len(active)) as ex9:
        list(ex9.map(one, active))


def _hl_on(cfg) -> bool:
    try:
        import hl_spot
        return bool(hl_spot.addresses(cfg))
    except Exception:
        return False


def main():
    common.cpu_reserve_apply()
    common.ensure_dirs()
    unit_beat.start("exf")
    writer = SegmentWriter(os.path.join(common.INBOX_DIR, "ex"))
    n9 = common.scrub_secret_file(STATE_PATH)
    if n9:
        log.info("exf_state: 수정 전 오류 문구 %d칸 비밀값 가림", n9)
    state = common.read_json(STATE_PATH, {})
    _cool_restore()
    _clock_restore()
    depaddr.start_background(_env)
    try:
        import perp_dex
        perp_dex.start_background()
    except Exception as e:
        log.warning("퍼프 덱스 수집 스레드 시작 실패(거래소 수집은 계속): %s", repr(e)[:160])
    try:
        import liq_watch
        liq_watch.start_background(_env, _RL_OFF)
    except Exception as e:
        log.warning("청산 빠른 감시 스레드 시작 실패(거래소 수집은 계속): %s", repr(e)[:160])
    while True:
        env = _env()
        cfg = common.load_config()
        poll9 = common.exf_poll_sec(cfg)
        _POLL_HINT[0] = poll9
        months = 0 if cfg.get("backfill_full_history") else float(cfg.get("backfill_months") or 5)
        window = int((months or 5) * 30 * DAY)
        now = int(time.time())
        hl_on9 = _hl_on(cfg)
        try:
            common.atomic_write_json(os.path.join(common.STATE_DIR, "exf_active.json"),
                                     {"v": 1, "ts": now, "active": sorted([ex for ex, (_f9, need) in FETCHERS.items()
                                                                           if all(env.get(k) for k in need)] + (["hyperliquid"] if hl_on9 else []))})
        except Exception as e:
            log.warning("연결 거래소 목록 기록 실패(무시): %s", repr(e)[:120])
        _LATE_CYC["id"], _LATE_CYC["ex"] = f"c{now}:{uuidlib.uuid4().hex[:10]}", set()
        cw = _CycleWriter(writer, state)
        for ex, (fn, need) in FETCHERS.items():
            if not all(env.get(k) for k in need):
                continue
            st = state.setdefault(ex, {"seen": {}, "backfilled_until": 0})
            _quiet_n[ex] = _quiet_n.get(ex, 0) + 1
            loud9 = _quiet_n[ex] % 10 == 1
            _dep_hold_migrate(ex, st, now, window)
            t0, dep_t0 = _wd_window(st, now, window)
            wd_ok = True
            try:
                w_rows, d_rows = fn(env, t0, now, dep_t0=dep_t0) if ex == "gate" else fn(env, t0, now)
            except Exception as e:
                log.warning("%s 입출금 수집 실패(다음 주기 재시도): %s", ex, repr(e)[:140])
                w_rows, d_rows = [], []
                wd_ok = False
                _invalidate_balance_snapshot(ex)
            seen = st["seen"]
            seen_txids = st.setdefault("seen_txids", {})
            seen_dest = st.setdefault("seen_dest", {})
            new_w = _rows_to_emit(w_rows, seen, seen_txids, seen_dest)
            new_d = _rows_to_emit(d_rows, seen, seen_txids)
            if new_w or new_d:
                _invalidate_balance_snapshot(ex)
                cw.append(_late_tag({"v": 1, "kind": "ex_snapshot", "exchange": ex,
                                     "ts": now, "deposits": new_d, "withdraws": new_w}, ex))
                if new_d:
                    depaddr.notify(ex)
                _mark_seen(new_w + new_d, seen, seen_txids, seen_dest, st.setdefault("pend_ts", {}))
            if wd_ok:
                st["backfilled_until"] = now
                _dep_hold_update(ex, st, dep_t0)
            state[ex] = st
            common.atomic_write_json(STATE_PATH, state)
            if new_w or new_d or loud9:
                log.info("%s: 출금 %d(신규 %d) · 입금 %d(신규 %d)",
                         ex, len(w_rows), len(new_w), len(d_rows), len(new_d))
            wd_fly9 = _wd_inflight(w_rows, now) if wd_ok else []
            fills_ok, fills_new = False, 0
            fills_rl = False
            fst = None
            try:
                fst = json.loads(json.dumps(st.get("fills") or {}))
                fst["extra_bases"] = sorted(set(fst.get("extra_bases") or []) |
                                            {r["currency"] for r in w_rows + d_rows
                                             if r.get("currency")})
                _WD_TOUCH[ex] = {str(r["currency"]).upper() for r in new_w + new_d if r.get("currency")}
                ft0 = max(now - window, min(now - 3 * DAY, int(fst.get("backfilled_until") or now - window)))
                if ex == "binance":
                    ft0 = binance_fills_t0(st, now, window)
                f_rows = FILL_FETCHERS[ex](env, fst, ft0, now)
                partial9 = fst.pop("partial", None)
                f_rows = f_rows + convert_rows(ex, env, fst, now, window)
                hold9 = fst.pop("recon_hold", None)
                fseen = fst.setdefault("seen", {})
                new_f = [f for f in f_rows if f["id"] not in fseen]
                if new_f:
                    _invalidate_balance_snapshot(ex)
                lb9 = f"{ex}:{now}:{uuidlib.uuid4().hex[:10]}" if any(f.get("late") or f.get("src") == "convert" for f in new_f) else None
                nch9 = (len(new_f) + 499) // 500
                for k9, i in enumerate(range(0, len(new_f), 500)):
                    rec9 = {"v": 1, "kind": "exf_fills", "exchange": ex, "ts": now, "fills": new_f[i:i + 500]}
                    if lb9:
                        rec9.update(lb=lb9, lbi=k9, lbn=nch9)
                    cw.append(_late_tag(rec9, ex, force=bool(lb9)))
                cutoff = (now - 14 * DAY) * 1000
                for f in new_f:
                    fseen[f["id"]] = f["ts"]
                for k in [k for k, v in fseen.items() if v < cutoff]:
                    del fseen[k]
                if not partial9:
                    fst["backfilled_until"] = now
                st["fills"] = fst
                common.atomic_write_json(STATE_PATH, state)
                fills_ok, fills_new = not partial9 and not hold9, len(new_f)
                fills_rl = bool(partial9) and ex == "binance"
                if new_f or loud9:
                    log.info("%s: 체결 %d건 (신규 %d)", ex, len(f_rows), len(new_f))
                if hold9 and not partial9:
                    log.info("%s 잔고 승격 보류(부가 수집 미완 — %s): 받은 체결·커서는 반영, 다음 주기 다시", ex, str(hold9)[:200])
                if partial9:
                    log.info("%s 체결 부분 주기(받은 몫·커서 보존, 백필 도장·잔고 승격 보류 — 다음 주기에 이어서): %s", ex, partial9)
            except Exception as e:
                fills_rl = isinstance(e, RateLimited)
                log.warning("%s 체결 수집 실패(다음 주기 재시도): %s", ex, repr(e)[:140])
                try:
                    eb9 = set((st.get("fills") or {}).get("extra_bases") or []) | set((fst or {}).get("extra_bases") or [])
                    bd9 = set((st.get("fills") or {}).get("bn_dirty") or []) | set((fst or {}).get("bn_dirty") or [])
                    if eb9 != set((st.get("fills") or {}).get("extra_bases") or []) or bd9 != set((st.get("fills") or {}).get("bn_dirty") or []):
                        st.setdefault("fills", {})["extra_bases"] = sorted(eb9)
                        if bd9:
                            st["fills"]["bn_dirty"] = sorted(bd9)
                        common.atomic_write_json(STATE_PATH, state)
                except Exception as e9:
                    log.warning("%s 체결 후보 통화 보존 실패: %s", ex, repr(e9)[:120])
            bp9 = os.path.join(common.STATE_DIR, f"exf_balances_{ex}.json")
            pend_bp = bp9 + ".pending"
            try:
                if wd_fly9 and fills_ok and not fills_new and loud9:
                    log.info("%s 진행 중 출금 %d건(종결 전) — 잔고 승격 보류(출금 기장 전 잔고로 대사 금지)", ex, len(wd_fly9))
                if (not fills_ok or fills_new or wd_fly9 or (st.get("fills") or {}).get("track_pending")
                        or (st.get("fills") or {}).get("open_unknown")):
                    _keep_view(bp9, pend_bp)
                    for p9 in (bp9, pend_bp):
                        if os.path.exists(p9):
                            os.remove(p9)
                    if (not fills_ok or (wd_fly9 and not fills_new)) and not fills_rl:
                        try:
                            bal9 = BAL_FETCHERS[ex](env)
                            snap9 = {"ts": int(time.time()), "balances": dict(bal9)}
                            if isinstance(getattr(bal9, "debts", None), dict):
                                snap9["debts"] = {k9: v9 for k9, v9 in bal9.debts.items() if v9 < 0}
                            if isinstance(getattr(bal9, "sources", None), list):
                                snap9["sources"] = sorted(set(bal9.sources))
                            if getattr(bal9, "loans", None):
                                snap9["loans"] = list(bal9.loans)
                            common.atomic_write_json(bp9 + ".view", snap9)
                        except (Exception, SystemExit) as e9v:
                            if loud9:
                                log.info("%s 표시용 잔고 갱신 생략(체결 실패 주기): %s", ex, _xm(repr(e9v))[:120])
                else:
                    bal9 = BAL_FETCHERS[ex](env)
                    prevp = common.read_json(pend_bp, {})
                    prev_balances = prevp.get("balances")
                    snap9 = {"ts": int(time.time()), "balances": dict(bal9)}
                    if isinstance(getattr(bal9, "debts", None), dict):
                        snap9["debts"] = {k9: v9 for k9, v9 in bal9.debts.items() if v9 < 0}
                    if isinstance(getattr(bal9, "sources", None), list):
                        snap9["sources"] = sorted(set(bal9.sources))
                    if getattr(bal9, "loans", None):
                        snap9["loans"] = list(bal9.loans)
                    if ex == "binance" and isinstance((getattr(bal9, "by_src", None) or {}).get("futures"), dict):
                        snap9["fut_part"] = dict(bal9.by_src["futures"])
                    if isinstance(prev_balances, dict) and (prev_balances or not bal9):
                        agree9, why9 = _snap_promote_ok(ex, prevp, snap9)
                        if agree9:
                            common.atomic_write_json(bp9, prevp)
                            if loud9:
                                log.info("%s: 잔고 스냅샷 승격 (%d종)%s", ex, len(prev_balances), " — 일치 확인 없이(연속 불일치 상한)" if agree9 == "forced" else "")
                    common.atomic_write_json(pend_bp, snap9)
                    common.atomic_write_json(bp9 + ".view", snap9)
                    if loud9:
                        log.info("%s: 잔고 %d종 (pending)", ex, len(bal9))
            except (Exception, SystemExit) as e:
                log.warning("%s 잔고·주소 수집 실패(다음 주기): %s", ex, repr(e)[:140])
        if hl_on9:
            try:
                import hl_spot
                msg9 = hl_spot.run_pass(state, cw, cfg, now=now, save=lambda: common.atomic_write_json(STATE_PATH, state))
                (log.info if msg9.startswith(("ok", "off", "대기")) else log.warning)("hyperliquid 현물: %s", msg9)
            except Exception as e:
                log.warning("hyperliquid 현물 수집 실패(다음 주기): %s", repr(e)[:160])
        try:
            dest_backfill_pass(env, state, cw, now, window)
        except Exception as e:
            log.warning("출금 목적지 소급 실패(다음 주기): %s", repr(e)[:160])
        try:
            krw_backfill_pass(env, state, cw, now, window)
        except Exception as e:
            log.warning("빗썸 원화 입출금 소급 실패(다음 주기): %s", repr(e)[:160])
        try:
            bybit_internal_pass(env, state, cw, now, window)
        except Exception as e:
            log.warning("바이비트 내부 입금 패스 실패(다음 주기): %s", repr(e)[:160])
        try:
            pending_recheck_pass(env, state, cw, now, window)
        except Exception as e:
            log.warning("비종결 입출금 재확인 실패(다음 주기): %s", repr(e)[:160])
        for ex9 in sorted(_LATE_CYC["ex"]):
            try:
                writer.append({"v": 1, "kind": "exf_late_cycle", "exchange": ex9, "ts": int(time.time()), "lc": _LATE_CYC["id"]})
            except Exception as e:
                log.warning("%s 늦은 행 주기 끝 표시 실패(core 는 1시간 뒤 흡수): %s", ex9, repr(e)[:120])
        _LATE_CYC["id"], _LATE_CYC["ex"] = None, set()
        target9 = ext_trigger_target(now, window)
        ext_sec = 0.0
        if target9 is not None:
            t_ext = time.time()
            try:
                extension_pass(env, state, writer, int(target9), now, window)
            except Exception as e:
                log.warning("과거 창 확장 실패(다음 주기): %s", repr(e)[:160])
            ext_sec = time.time() - t_ext
        futures_snapshot_all(env)
        try:
            leverage_pass(env, cfg)
        except Exception as e:
            log.warning("레버리지·대출 스냅숏 실패(다음 주기): %s", common.safe_err(repr(e))[:160])
        active = any(all(env.get(k) for k in need) for _, need in FETCHERS.values()) or hl_on9
        time.sleep(max(60.0, poll9 - ext_sec) if active else 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("정지 신호(SIGINT) — 종료")
