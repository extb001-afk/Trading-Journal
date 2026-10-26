from __future__ import annotations
import email.utils
import functools
import json
import os
import threading
import time
import urllib.request
import bf_engine, config, logs, net_http, num_parse, paths, statefile
import logging

log = logging.getLogger('tj-exf')

try:
    import fut_rcpt  # noqa: E402
except Exception:   # noqa: BLE001 [optional]
    fut_rcpt = None


POLL_SEC = 600


PACE = 0.35


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


DAY = 86400


def _xm(v) -> str:
    return logs.redact_secret_text("" if v is None else str(v))


_ACCT_TL = threading.local()


def _acct() -> str:
    return getattr(_ACCT_TL, "tag", "") or ""


def _ak(ex: str) -> str:
    t9 = _acct()
    return ex if not t9 else f"{ex}~{t9}"


def _save_state(state) -> None:
    root = getattr(state, "root", None)
    statefile.atomic_write_json(paths.state("exf_state.json"), root if root is not None else state)


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
    except Exception:   # noqa: BLE001 [fallback]
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
              "/sapi/v1/asset/assetDividend": 10,
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
    ("cb_hr", "api.coinbase.com", lambda p: True, 3600, 8000, lambda p: 1),
    ("cb_s", "api.coinbase.com", lambda p: True, 10, 80, lambda p: 1),
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
              "api-futures.kucoin.com": "kucoin", "api.gateio.ws": "gate", "api.bithumb.com": "bithumb",
              "api.coinbase.com": "coinbase"}


CLOCK_SRC = {"binance": "https://api.binance.com/api/v3/time", "bybit": "https://api.bybit.com/v5/market/time",
             "okx": "https://www.okx.com/api/v5/public/time", "kucoin": "https://api.kucoin.com/api/v1/timestamp",
             "gate": "https://api.gateio.ws/api/v4/spot/time", "bithumb": "https://api.bithumb.com/v1/ticker?markets=KRW-BTC",
             "coinbase": "https://api.coinbase.com/v2/time"}


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
        if ex == "coinbase":
            epoch_s = float(d["data"]["epoch"])
            return int(epoch_s * 1000) + (500 if epoch_s == int(epoch_s) else 0) if epoch_s > 0 else None
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
    req = net_http.request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    t0 = time.time()
    try:
        with net_http.urlopen(req, timeout=10) as r:
            raw = _read_capped(r, 256 * 1024, host + path)
            dh = r.headers.get("Date") if r.headers is not None else None
        t1 = time.time()
        d = json.loads(raw.decode("utf-8")) if raw else None
    except urllib.error.HTTPError as e:
        if e.code in (429, 418):
            _rl_hit(host, e)
        log.warning("%s 서버 시각 조회 실패: HTTP %s", ex, e.code)
        return None
    except Exception as e:   # noqa: BLE001 [fallback]
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
        statefile.atomic_write_json(paths.state(CLOCK_PATH_NAME), doc)
    except Exception as e:   # noqa: BLE001 [optional]
        log.warning("서버 시각 차이 기록 실패: %s", e)


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


_CLOCK_FILE = {"at": 0.0, "ex": {}}
CLOCK_FILE_MAX_AGE = 6 * 3600


def sign_ms(ex: str) -> int:
    now = time.time()
    if _CLOCK_ON[0]:
        c = _CLOCK.get(ex) or {}
        try:
            fresh = now - float(c.get("at") or 0) <= CLOCK_FILE_MAX_AGE
            return int(now * 1000) + (int(c.get("off") or 0) if fresh else 0)
        except (TypeError, ValueError):
            return int(now * 1000)
    if now - _CLOCK_FILE["at"] >= 60:
        _CLOCK_FILE["at"] = now
        try:
            with open(paths.state(CLOCK_PATH_NAME), encoding="utf-8") as f:
                d9 = (json.load(f) or {}).get("ex") or {}
            _CLOCK_FILE["ex"] = d9 if isinstance(d9, dict) else {}
        except (OSError, ValueError, AttributeError):
            _CLOCK_FILE["ex"] = {}
    c = _CLOCK_FILE["ex"].get(ex)
    off = 0
    try:
        if isinstance(c, dict) and now - float(c.get("at") or 0) <= CLOCK_FILE_MAX_AGE:
            off = int(c.get("off") or 0)
    except (TypeError, ValueError):
        off = 0
    return int(now * 1000) + off


def iso_ms(ms: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ms / 1000.0)) + f".{int(ms) % 1000:03d}Z"


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
        except Exception:  # noqa: BLE001 [fallback]
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
    req = net_http.request(url, headers=h, data=data, method=method)
    try:
        with net_http.auth_urlopen(req, timeout=timeout) as r:
            try:
                _gov_headers(host, path, r.headers)
            except Exception:   # noqa: BLE001 [optional]
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


def _int_or(v, d=-999):
    return num_parse.to_int(v, d)


_DEP_DENIED = set()


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


BN_UNI_TTL = 24 * 3600


BN_UNI_RETRY = 3600


RECON_HOLD_CAP = 6 * 3600


_WD_TOUCH = {}


_POLL_HINT = [POLL_SEC]


def _dstr(x) -> str:
    d = num_parse.to_dec(x)
    if d is None:
        return "0"
    return format(d.normalize(), "f") if d != 0 else "0"


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


CV_QUOTE_PREF = ("USDT", "USDC", "FDUSD", "USD", "USDG", "USDE", "DAI", "BUSD", "TUSD", "KRW", "BTC", "ETH", "BNB")


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


class _PartialConvertRows(list):
    def __init__(self, rows, error):
        super().__init__(rows)
        self.error = error


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
        except Exception:  # noqa: BLE001 [fallback]
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
    return paths.state(COOL_PATH_NAME)


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
            statefile.atomic_write_json(_cool_path(), out)
        except Exception as e:   # noqa: BLE001 [optional]
            log.warning("쿨다운 기록 실패(메모리 값은 유지): %s", logs.safe_err(e)[:120])


_BAL_SRC_OFF = _CoolMap("bal")


_BAL_SRC_HAD_PATH = "exf_balance_sources.json"


_BAL_SRC_HAD = None


def _bal_src_had_load():
    global _BAL_SRC_HAD
    if _BAL_SRC_HAD is None:
        path = paths.state(_BAL_SRC_HAD_PATH)
        try:
            d = statefile.read_json(path, {})
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
    exk9 = _ak(ex)
    key = f"{exk9}:{src}"

    def _omit_or_hold(reason):
        if had.get(key):
            _invalidate_balance_snapshot(ex)
            raise RuntimeError(f"{ex} {src}: 직전 실보유 소스 조회 불가({reason}) — 부분 잔고 발행 보류")

    if time.time() < _BAL_SRC_OFF.get((exk9, src), 0):
        _omit_or_hold("쿨다운")
        return
    local = _Bal()
    try:
        fn(local)
    except Exception as e:
        msg = _xm(repr(e))
        deny = any(k in msg for k in _DENY_SIGS + tuple(extra_deny))
        if deny or lenient:
            _BAL_SRC_OFF[(exk9, src)] = time.time() + (DENY_COOL_SEC if deny else 1800)
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
        statefile.atomic_write_json(paths.state(_BAL_SRC_HAD_PATH), had)
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


SEEN_NOTIME = "#notime"


def _has_time(r) -> bool:
    return bool(_iso_epoch(r.get("created_at")) or _iso_epoch(r.get("done_at")))


def _is_time_fix(r, seen) -> bool:
    return isinstance(r, dict) and seen.get(r.get("uuid")) == str(r.get("state")) + SEEN_NOTIME and _has_time(r)


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


def _invalidate_balance_snapshot(ex):
    bp = paths.state(f"exf_balances_{ex}.json")
    _keep_view(bp, bp + ".pending")
    for p in (bp, bp + ".pending"):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass


_RL_OFF = _CoolMap("rl")


_WD_OFF = _CoolMap("wd")


_FUT_MULTI = {}


def _fut_path(ex):
    if _FUT_MULTI.get(ex):
        return paths.state(f"futraw_{ex}_{_acct() or 'main'}.json")
    return paths.state(f"futures_{ex}.json")


def fut_first_t0(ex: str, now: float):
    try:
        win_t0 = int(bf_engine.effective_backfill_t0(config.load_config(), now))
        since_t0 = bf_engine.SINCE.target(ex)
        return int(min(win_t0, since_t0)) if since_t0 else win_t0
    except (Exception, SystemExit) as e:   # noqa: BLE001 [fallback]
        log.warning("%s 선물 첫 하한 계산 실패(종전 기본): %s", ex, _xm(repr(e))[:120])
        return None


def _fut_write(ex, wallet, positions, events, cursor, covered_through=None):
    events = sorted(events, key=lambda r: r["t"])
    if len(events) > 20000:
        log.warning("%s 선물 정산 이벤트 %d건 (파일 비대) — 보존 유지, 보관정책 검토 필요", ex, len(events))
    ts9 = int(time.time())
    d9 = {"ts": ts9, "wallet": wallet, "positions": positions, "events": events, "cursor": cursor}
    if covered_through is not None:
        d9["inc_cov_ts"] = min(ts9, int(covered_through))
    statefile.atomic_write_json(_fut_path(ex), d9)


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


PX_CALLS_MAX = 20


PX_BN_FAIL_MAX = 3


PX_BN_REPLAN_MS = DAY * 1000


def _px_safe(ex, fn):
    if fut_rcpt is None or _acct():
        return
    try:
        fn()
    except (Exception, SystemExit) as e:   # noqa: BLE001 [optional]
        log.warning("%s 선물 가격 옆 파일 실패(정산 무관 · 다음 주기): %s", ex, _xm(repr(e))[:160])


def _keep_view(bp9, pend_bp):
    try:
        best = None
        for p9 in (bp9, pend_bp):
            if os.path.exists(p9):
                d9 = statefile.read_json(p9, {})
                if isinstance(d9, dict) and isinstance(d9.get("balances"), dict):
                    if best is None or float(d9.get("ts") or 0) > float(best.get("ts") or 0):
                        best = d9
        if best is None:
            return
        vp9 = bp9 + ".view"
        cur9 = statefile.read_json(vp9, {}) if os.path.exists(vp9) else {}
        if not isinstance(cur9, dict) or float(best.get("ts") or 0) >= float(cur9.get("ts") or 0):
            statefile.atomic_write_json(vp9, best)
    except (Exception, SystemExit) as e:   # noqa: BLE001 [optional]
        log.warning("잔고 표시 사본 보존 실패: %s", repr(e)[:120])
