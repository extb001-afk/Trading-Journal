"""Candle (OHLCV) fetcher with venue fallback chain and local cache."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import bf_engine
import common

KST = timezone(timedelta(hours=9))
CACHE_DIR = os.path.join(common.STATE_DIR, "candles")
IV_SEC = {"1m": 60, "5m": 300, "1h": 3600, "1d": 86400}
MAX_PAGES = 12
CLOSED_AFTER_S = 3600
NEG_TTL_S = 6 * 3600
POOL_TTL_S = 7 * 86400
DEADLINE_S = 45.0
GT_MAX_AGE_S = 179 * 86400
GATE_MAX_POINTS = 9990
USD_LIKE = {"USDT", "USDC", "USD", "FDUSD", "USD1", "BUSD", "TUSD", "DAI", "USDE", "PYUSD", "USDG"}

HOST_POLICY = {
    "api.geckoterminal.com": {"rate": 0.2, "burst": 1, "conc": 1},
    "api.dexscreener.com": {"rate": 2.0, "burst": 3, "conc": 1},
    "api.upbit.com": {"rate": 4.0, "burst": 4, "conc": 2},
    "api.bithumb.com": {"rate": 4.0, "burst": 4, "conc": 2},
    "api.binance.com": {"rate": 4.0, "burst": 4, "conc": 2},
    "fapi.binance.com": {"rate": 4.0, "burst": 4, "conc": 2},
    "api.bybit.com": {"rate": 4.0, "burst": 4, "conc": 2},
    "www.okx.com": {"rate": 4.0, "burst": 4, "conc": 2},
    "api.gateio.ws": {"rate": 4.0, "burst": 4, "conc": 2},
    "api.kucoin.com": {"rate": 4.0, "burst": 4, "conc": 2},
    "api.coingecko.com": {"rate": 0.1, "burst": 1, "conc": 1},
}
for _h, _p in HOST_POLICY.items():
    bf_engine.HOST_POLICIES.setdefault(_h, _p)

GT_NETWORK = {"eth": "eth", "base": "base", "bsc": "bsc", "arbitrum": "arbitrum", "optimism": "optimism",
              "polygon": "polygon_pos", "scroll": "scroll", "zksync": "zksync", "gnosis": "xdai", "sol": "solana",
              "monad": "monad", "megaeth": "megaeth", "plasma": "plasma", "xlayer": "x-layer", "kaia": "kaia",
              "fraxtal": "fraxtal", "bob": "bob-network", "somnia": "somnia", "avalanche": "avax", "story": "story",
              "abstract": "abstract", "robinhood": "robinhood"}
DS_CHAIN = {"eth": "ethereum", "bsc": "bsc", "base": "base", "arbitrum": "arbitrum", "optimism": "optimism",
            "polygon": "polygon", "sol": "solana", "zksync": "zksync", "scroll": "scroll", "monad": "monad",
            "megaeth": "megaeth", "plasma": "plasma", "xlayer": "xlayer", "kaia": "kaia", "fraxtal": "fraxtal",
            "bob": "bob", "story": "story", "somnia": "somnia", "avalanche": "avalanche", "abstract": "abstract",
            "robinhood": "robinhood"}
try:
    import pricing as _px
    GT_NETWORK.update(getattr(_px, "GT_NETWORK", {}) or {})
    DS_CHAIN.update(getattr(_px, "DS_CHAIN", {}) or {})
except Exception:
    pass

VENUE_KO = {"upbit": "업비트", "bithumb": "빗썸", "binance": "바이낸스", "binance_futures": "바이낸스 선물", "bybit": "바이빗",
            "okx": "OKX", "gate": "게이트", "kucoin": "쿠코인", "dex": "DEX"}
CHAIN_KO = {"eth": "Ethereum", "bsc": "BSC", "base": "Base", "sol": "Solana", "arbitrum": "Arbitrum", "polygon": "Polygon",
            "optimism": "Optimism", "zksync": "zkSync", "megaeth": "MegaETH", "robinhood": "Robinhood"}

CALLS = {"n": 0, "by_host": {}}
CALL_CAP = [None]
_CALL_LOCK = threading.Lock()


class BudgetExceeded(RuntimeError):
    pass


class Result:
    __slots__ = ("candles", "why", "note", "cached", "calls", "complete")

    def __init__(self, candles=None, why=None, note=None, cached=False, calls=0, complete=True):
        self.candles, self.why, self.note, self.cached, self.calls = candles, why, note, cached, calls
        self.complete = complete

    @property
    def ok(self):
        return bool(self.candles)

    def __repr__(self):
        return f"Result(n={len(self.candles or [])}, why={self.why}, cached={self.cached}, calls={self.calls})"


_TL = threading.local()


@contextlib.contextmanager
def hard_deadline(t):
    prev = getattr(_TL, "dl", None)
    _TL.dl = t if prev is None else min(prev, t)
    try:
        yield
    finally:
        _TL.dl = prev


@contextlib.contextmanager
def call_budget(n):
    prev = getattr(_TL, "bud", None)
    cell = [max(0, int(n))]
    _TL.bud = cell if prev is None else _Nested(cell, prev)
    try:
        yield cell
    finally:
        _TL.bud = prev


class _Nested:
    __slots__ = ("cells",)

    def __init__(self, inner, outer):
        self.cells = [inner] + (outer.cells if isinstance(outer, _Nested) else [outer])

    def left(self):
        return min(c[0] for c in self.cells)

    def take(self):
        for c in self.cells:
            c[0] -= 1


def _bud_left(b):
    return b.left() if isinstance(b, _Nested) else b[0]


def _bud_take(b):
    if isinstance(b, _Nested):
        b.take()
    else:
        b[0] -= 1


def budget_left():
    b = getattr(_TL, "bud", None)
    return None if b is None else _bud_left(b)


def _get(url, headers=None, timeout=20.0, deadline=None, inline_wait=10.0, gate_host=None, single=False):
    host = (urllib.parse.urlsplit(url).hostname or "?").lower()
    dl = getattr(_TL, "dl", None)
    if dl is not None:
        left = dl - time.time()
        if left <= 0.05:
            raise bf_engine.NetError(f"budget: 요청 마감 지남({host})", "budget", host=host)
        deadline = dl if deadline is None else min(deadline, dl)
        timeout = max(0.05, min(float(timeout), left))
        inline_wait = min(inline_wait, left)
    tries = 1 if single else (3 if inline_wait > 10 else 2)
    gk9 = {"gate_host": gate_host} if gate_host else {}
    bud = getattr(_TL, "bud", None)
    for i in range(tries if bud is not None else 1):
        sem_to = max(0.05, (deadline - time.time())) if deadline is not None else float(timeout)
        with _CALL_LOCK:
            if CALL_CAP[0] is not None and CALLS["n"] >= CALL_CAP[0]:
                raise BudgetExceeded(f"외부 호출 상한 {CALL_CAP[0]} 도달")
            if bud is not None:
                if _bud_left(bud) <= 0:
                    raise BudgetExceeded("이 실행의 외부 호출 예산 소진")
                _bud_take(bud)
            CALLS["n"] += 1
            CALLS["by_host"][host] = CALLS["by_host"].get(host, 0) + 1
        if bud is None:
            return bf_engine.http_json(url, headers=headers, timeout=timeout, retries=tries, retry_5xx=True,
                                       deadline=deadline, max_inline_wait=inline_wait, breaker_5xx=True, sem_timeout=sem_to, **gk9)
        try:
            return bf_engine.http_json(url, headers=headers, timeout=timeout, retries=1, retry_5xx=True,
                                       deadline=deadline, max_inline_wait=inline_wait, breaker_5xx=True, sem_timeout=sem_to, **gk9)
        except bf_engine.NetError as e:
            if e.kind not in bf_engine.RETRYABLE or e.kind == "quota" or i + 1 >= tries or _bud_left(bud) <= 0:
                raise
            wait = e.retry_after if (e.kind == "http429" and getattr(e, "retry_after", None) is not None) else bf_engine._backoff(i)
            if wait > inline_wait or (deadline is not None and time.time() + wait > deadline):
                raise
            time.sleep(wait)
    raise bf_engine.NetError("요청 실패", "other", host=host)


def _keyed(url, lane, allow, valid, deadline):
    if not allow:
        return "skip", "allow"
    try:
        import cgkey
    except Exception:
        return "skip", "import"
    if not cgkey.key():
        return "skip", "nokey"
    if url.startswith("https://api.coingecko.com/api/v3"):
        path = url[len("https://api.coingecko.com/api/v3"):]
    elif url.startswith(cgkey.GT_ROOT):
        path = cgkey.onchain(url)
    else:
        return "skip", "url"

    def via(u, h, g):
        return _get(u, headers=h, gate_host=g, single=True, deadline=deadline, inline_wait=10.0)
    kind, v = cgkey.request(path, lane, via, valid=valid)
    if kind == "fail":
        cgkey.mark_fallback(lane)
    return kind, v


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None


def _row(t, o, h, l, c, v):
    vals = [_f(o), _f(h), _f(l), _f(c)]
    if None in vals or min(vals) <= 0:
        return None
    vv = _f(v)
    return [int(t), vals[0], vals[1], vals[2], vals[3], vv if vv is not None and vv >= 0 else 0.0]


def _utc_s(s):
    return int(datetime.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())


def parse_upbit(d):
    if not isinstance(d, list):
        return None
    out = []
    for r in d:
        if not isinstance(r, dict) or not r.get("candle_date_time_utc"):
            continue
        try:
            t = _utc_s(r["candle_date_time_utc"])
        except ValueError:
            continue
        x = _row(t, r.get("opening_price"), r.get("high_price"), r.get("low_price"), r.get("trade_price"),
                 r.get("candle_acc_trade_volume"))
        if x:
            out.append(x)
    return out


def parse_binance(d):
    if not isinstance(d, list):
        return None
    out = []
    for r in d:
        if isinstance(r, list) and len(r) >= 6:
            x = _row(int(r[0]) // 1000, r[1], r[2], r[3], r[4], r[5])
            if x:
                out.append(x)
    return out


def parse_bybit(d):
    if not isinstance(d, dict) or d.get("retCode") not in (0, "0"):
        return None
    out = []
    for r in ((d.get("result") or {}).get("list") or []):
        if isinstance(r, list) and len(r) >= 6:
            x = _row(int(r[0]) // 1000, r[1], r[2], r[3], r[4], r[5])
            if x:
                out.append(x)
    return out


def parse_okx(d):
    if not isinstance(d, dict) or str(d.get("code")) != "0":
        return None
    out = []
    for r in (d.get("data") or []):
        if isinstance(r, list) and len(r) >= 6:
            x = _row(int(r[0]) // 1000, r[1], r[2], r[3], r[4], r[5])
            if x:
                out.append(x)
    return out


def parse_gate(d):
    if not isinstance(d, list):
        return None
    out = []
    for r in d:
        if isinstance(r, list) and len(r) >= 6:
            v = r[6] if len(r) >= 7 else None
            if v is None:
                q, c = _f(r[1]), _f(r[2])
                v = (q / c) if (q is not None and c) else 0
            x = _row(int(float(r[0])), r[5], r[3], r[4], r[2], v)
            if x:
                out.append(x)
    return out


def parse_kucoin(d):
    if not isinstance(d, dict) or str(d.get("code")) != "200000":
        return None
    out = []
    for r in (d.get("data") or []):
        if isinstance(r, list) and len(r) >= 6:
            x = _row(int(float(r[0])), r[1], r[3], r[4], r[2], r[5])
            if x:
                out.append(x)
    return out


def parse_gt(d):
    try:
        rows = d["data"]["attributes"]["ohlcv_list"]
    except (KeyError, TypeError):
        return None
    if not isinstance(rows, list):
        return None
    out = []
    for r in rows:
        if isinstance(r, list) and len(r) >= 6:
            x = _row(int(float(r[0])), r[1], r[2], r[3], r[4], r[5])
            if x:
                out.append(x)
    return out


def parse_ds_pairs(d, chain_id):
    if isinstance(d, dict):
        d = d.get("pairs") or []
    if not isinstance(d, list):
        return None
    out = []
    for p in d:
        if not isinstance(p, dict) or not p.get("pairAddress"):
            continue
        if p.get("chainId") and p.get("chainId") != chain_id:
            continue
        liq = _f(((p.get("liquidity") or {}) if isinstance(p.get("liquidity"), dict) else {}).get("usd")) or 0.0
        out.append({"pool": str(p["pairAddress"]), "dex": str(p.get("dexId") or ""), "liq": liq,
                    "base": str((p.get("baseToken") or {}).get("address") or ""),
                    "quote": str((p.get("quoteToken") or {}).get("address") or ""),
                    "qsym": str((p.get("quoteToken") or {}).get("symbol") or ""),
                    "created": int(_f(p.get("pairCreatedAt")) or 0) // 1000})
    out.sort(key=lambda x: -x["liq"])
    return out


def norm(rows, t0=None, t1=None):
    seen, out = set(), []
    for r in sorted(rows or (), key=lambda x: x[0]):
        if r[0] in seen:
            continue
        if t0 is not None and r[0] < t0:
            continue
        if t1 is not None and r[0] >= t1:
            continue
        seen.add(r[0])
        out.append(r)
    return out


def market_name(venue, base, quote):
    b, q = str(base or "").upper(), str(quote or "").upper()
    if venue in ("upbit", "bithumb"):
        return f"{q}-{b}"
    if venue in ("binance", "binance_futures", "bybit"):
        return f"{b}{q}"
    if venue in ("okx", "kucoin"):
        return f"{b}-{q}"
    if venue == "gate":
        return f"{b}_{q}"
    return f"{b}/{q}"


def spec_label(spec):
    if spec.get("venue") == "dex":
        ch = CHAIN_KO.get(spec.get("chain"), spec.get("chain") or "?")
        pair = spec.get("pair") or ""
        return f"DEX {ch}" + (f" {pair}" if pair else "") + (f" ({spec['dex']})" if spec.get("dex") else "")
    if spec.get("venue") == "coingecko":
        return "코인게코 시세 점(고·저 없음)" if (spec.get("token") or spec.get("id")) else "코인게코"
    return f"{VENUE_KO.get(spec.get('venue'), spec.get('venue'))} {market_name(spec['venue'], spec.get('base'), spec.get('quote'))}"


def spec_key(spec):
    if spec.get("venue") == "dex":
        return f"dex:{spec.get('chain')}:{str(spec.get('pool') or spec.get('token') or '').lower()}"
    if spec.get("venue") == "coingecko":
        if spec.get("id"):
            return f"cgid:{spec['id']}"
        return f"cg:{spec.get('chain')}:{str(spec.get('token') or '').lower()}"
    return f"{spec['venue']}:{market_name(spec['venue'], spec.get('base'), spec.get('quote'))}"


_CACHE_LOCK = threading.Lock()
_INFLIGHT = {}


def _cpath(*parts):
    h = hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:24]
    return os.path.join(CACHE_DIR, str(parts[0]).split(":")[0], h + ".json")


def _cache_get(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


CACHE_V = 2


def _cache_ok(c, now):
    if not isinstance(c, dict) or not isinstance(c.get("candles"), list):
        return False
    if c.get("complete") == CACHE_V and c["candles"]:
        return True
    u = c.get("until")
    return isinstance(u, (int, float)) and u > now


def _cache_store(path, key, out, why, note, complete, now):
    if not complete:
        return
    rec = {"key": key, "candles": out, "why": why, "note": note, "at": int(now), "complete": CACHE_V}
    if not out:
        rec["until"] = int(now + NEG_TTL_S)
    _cache_put(path, rec)


def _cache_put(path, obj):
    try:
        common.atomic_write_json(path, obj)
    except Exception:
        pass


def _neg_path():
    return os.path.join(CACHE_DIR, "neg.json")


def neg_get(key, now=None):
    with _CACHE_LOCK:
        d = _cache_get(_neg_path()) or {}
    e = d.get(key) if isinstance(d, dict) else None
    if isinstance(e, dict) and float(e.get("until") or 0) > (now or time.time()):
        return e.get("why") or "no_market"
    return None


def neg_put(key, why, ttl=NEG_TTL_S, now=None):
    now = now or time.time()
    with _CACHE_LOCK:
        d = _cache_get(_neg_path()) or {}
        if not isinstance(d, dict):
            d = {}
        d = {k: v for k, v in d.items() if isinstance(v, dict) and float(v.get("until") or 0) > now}
        d[key] = {"why": why, "until": int(now + ttl)}
        _cache_put(_neg_path(), d)


def _iso_utc(ts):
    return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_kst(ts):
    return datetime.fromtimestamp(int(ts), KST).strftime("%Y-%m-%d %H:%M:%S")


PAGE_N = {"upbit": 200, "bithumb": 200, "binance": 1000, "binance_futures": 1000, "bybit": 1000, "okx": 100,
          "gate": 900, "kucoin": 1500, "dex": 1000}


def _page_url(venue, mk, iv, a, b):
    s = IV_SEC[iv]
    q = urllib.parse.quote
    if venue in ("upbit", "bithumb"):
        n = min(200, max(1, -(-(b - a) // s)))
        host = "https://api.upbit.com" if venue == "upbit" else "https://api.bithumb.com"
        to = _iso_utc(b) if venue == "upbit" else _iso_kst(b)
        if iv == "1d":
            return f"{host}/v1/candles/days?market={q(mk)}&to={q(to)}&count={n}", parse_upbit
        unit = {"1m": 1, "5m": 5, "1h": 60}[iv]
        return f"{host}/v1/candles/minutes/{unit}?market={q(mk)}&to={q(to)}&count={n}", parse_upbit
    if venue in ("binance", "binance_futures"):
        host = "https://api.binance.com/api/v3/klines" if venue == "binance" else "https://fapi.binance.com/fapi/v1/klines"
        return (f"{host}?symbol={q(mk)}&interval={iv}&startTime={a * 1000}&endTime={b * 1000 - 1}&limit=1000",
                parse_binance)
    if venue == "bybit":
        ivb = {"1m": "1", "5m": "5", "1h": "60", "1d": "D"}[iv]
        return (f"https://api.bybit.com/v5/market/kline?category=spot&symbol={q(mk)}&interval={ivb}"
                f"&start={a * 1000}&end={b * 1000 - 1}&limit=1000", parse_bybit)
    if venue == "okx":
        bar = {"1m": "1m", "5m": "5m", "1h": "1H", "1d": "1Dutc"}[iv]
        return (f"https://www.okx.com/api/v5/market/history-candles?instId={q(mk)}&bar={bar}"
                f"&after={b * 1000}&before={a * 1000 - 1}&limit=100", parse_okx)
    if venue == "gate":
        return (f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={q(mk)}&interval={iv}"
                f"&from={a}&to={b - 1}", parse_gate)
    if venue == "kucoin":
        typ = {"1m": "1min", "5m": "5min", "1h": "1hour", "1d": "1day"}[iv]
        return (f"https://api.kucoin.com/api/v1/market/candles?type={typ}&symbol={q(mk)}&startAt={a}&endAt={b - 1}",
                parse_kucoin)
    raise ValueError(venue)


def _no_market(venue, err=None, body=None):
    if err is not None:
        msg = str(err).lower()
        if getattr(err, "kind", "") != "http4xx":
            return False
        code = getattr(err, "code", None)
        if venue in ("upbit", "bithumb"):
            return code in (400, 404) and ("market" in msg or "code not found" in msg or "not found" in msg or "invalid" in msg)
        if venue in ("binance", "binance_futures"):
            return code == 400 and ("invalid symbol" in msg or "-1121" in msg)
        if venue == "gate":
            return code in (400, 404) and ("invalid_currency" in msg or "currency_pair" in msg or "not found" in msg)
        if venue == "kucoin":
            return code in (400, 404)
        if venue == "okx":
            return code == 400 and ("51001" in msg or "doesn't exist" in msg)
        return code == 404
    if isinstance(body, dict):
        if venue in ("upbit", "bithumb"):
            e9 = body.get("error") if isinstance(body.get("error"), dict) else None
            if e9 is None:
                return False
            m9 = str(e9.get("message") or "").lower()
            return str(e9.get("name")) in ("404", "400") and ("code not found" in m9 or "market" in m9 or "not found" in m9)
        if venue == "bybit":
            return body.get("retCode") in (10001, "10001") or "symbol" in str(body.get("retMsg") or "").lower()
        if venue == "okx":
            return str(body.get("code")) in ("51001", "51000")
        if venue == "kucoin":
            return str(body.get("code")) in ("400100", "900001")
    return False


def banned_market(venue, quote) -> bool:
    return str(venue or "") in ("upbit", "bithumb") and str(quote or "").upper() != "KRW"


def fetch_cex(venue, base, quote, iv, t0, t1, now=None):
    if venue not in PAGE_N or venue == "dex" or iv not in IV_SEC:
        return Result(why="unsupported")
    if banned_market(venue, quote):
        return Result(why="no_market", note=f"{VENUE_KO.get(venue, venue)} {market_name(venue, base, quote)} 시세는 쓰지 않음(원화 아닌 마켓)",
                      cached=True)
    now = now or time.time()
    mk = market_name(venue, base, quote)
    s = IV_SEC[iv]
    t0 = int(t0) // s * s
    t1 = -(-int(t1) // s) * s
    nk = f"{venue}:{mk}"
    if neg_get(nk, now):
        return Result(why="no_market", note=f"{VENUE_KO.get(venue, venue)} {mk} 마켓 없음(최근 확인)", cached=True)
    closed = t1 + CLOSED_AFTER_S < now
    cp = _cpath(venue, mk, iv, t0, t1)
    if closed:
        c = _cache_get(cp)
        if _cache_ok(c, now):
            return Result(candles=c["candles"] or None, why=None if c["candles"] else (c.get("why") or "no_data"),
                          note=c.get("note"), cached=True)
    if venue == "gate" and (now - t0) / s > GATE_MAX_POINTS:
        return Result(why="too_old", note=f"게이트 {iv} 봉은 최근 {int(GATE_MAX_POINTS * s / 86400)}일까지만(공개 API 한도)")
    span = PAGE_N[venue] * s
    rows, calls, deadline = [], 0, time.time() + DEADLINE_S
    b = min(t1, int(now) // s * s + s)
    pages = 0
    try:
        while b > t0 and pages < MAX_PAGES:
            a = max(t0, b - span)
            url, parser = _page_url(venue, mk, iv, a, b)
            calls += 1
            pages += 1
            try:
                d = _get(url, deadline=deadline)
            except bf_engine.NetError as e:
                if getattr(e, "kind", "") == "budget":
                    return Result(why="time", note=f"{VENUE_KO.get(venue, venue)} 봉 조회 시간 초과(요청 마감)", calls=calls)
                if "too long ago" in str(e).lower():
                    return Result(why="too_old", note=f"{VENUE_KO.get(venue, venue)} {iv} 봉 보존 기간 밖(공개 API 한도)", calls=calls)
                if _no_market(venue, err=e):
                    neg_put(nk, "no_market")
                    return Result(why="no_market", note=f"{VENUE_KO.get(venue, venue)} {mk} 마켓 없음", calls=calls)
                return Result(why="net", note=f"{VENUE_KO.get(venue, venue)} 봉 조회 실패({getattr(e, 'kind', '?')}: {common.safe_err(e)[:80]})",
                              calls=calls)
            got = parser(d)
            if got is None:
                if _no_market(venue, body=d):
                    neg_put(nk, "no_market")
                    return Result(why="no_market", note=f"{VENUE_KO.get(venue, venue)} {mk} 마켓 없음", calls=calls)
                return Result(why="bad", note=f"{VENUE_KO.get(venue, venue)} 응답 형식 이상: {str(d)[:100]}", calls=calls)
            rows.extend(got)
            if venue in ("upbit", "bithumb") and got:
                b = min(a, min(r[0] for r in got))
            else:
                b = a
    except BudgetExceeded as e:
        return Result(why="budget", note=common.safe_err(e), calls=calls)
    out = norm(rows, t0, t1)
    complete = b <= t0
    why = None if out else "no_data"
    note = None if out else f"{VENUE_KO.get(venue, venue)} {mk} 그 구간 봉 없음(보존 기간 밖·상장 전·거래 없음)"
    if out and not complete:
        note = f"{VENUE_KO.get(venue, venue)} {mk} 봉 일부만(쪽 상한)"
    if closed:
        _cache_store(cp, [venue, mk, iv, t0, t1], out, why, note, complete, now)
    return Result(candles=out or None, why=why, note=note, calls=calls, complete=complete)


_MAJOR_Q = {"USDC", "USDT", "WETH", "ETH", "WBNB", "BNB", "SOL", "WSOL", "USD1", "USDE", "DAI", "CBBTC", "WBTC", "USDC.E", "USDT0"}


def _pools_path():
    return os.path.join(CACHE_DIR, "pools.json")


def find_pool(chain, token, tx_addrs=(), now=None):
    now = now or time.time()
    net = DS_CHAIN.get(chain)
    if not net or not token:
        return None, "unsupported", 0
    evm = chain != "sol"
    tk = token.lower() if evm else token
    key = f"{chain}:{tk}"
    with _CACHE_LOCK:
        pc = _cache_get(_pools_path()) or {}
    ent = pc.get(key) if isinstance(pc, dict) else None
    pairs = None
    if isinstance(ent, dict) and float(ent.get("until") or 0) > now:
        pairs = ent.get("pairs")
        if pairs is None:
            return None, "no_pool", 0
    calls = 0
    if pairs is None:
        calls = 1
        try:
            d = _get(f"https://api.dexscreener.com/tokens/v1/{net}/{urllib.parse.quote(token, safe='')}", deadline=time.time() + 20)
        except BudgetExceeded:
            return None, "budget", 0
        except bf_engine.NetError as e:
            return None, f"net:{getattr(e, 'kind', '?')}", calls
        pairs = parse_ds_pairs(d, net)
        if pairs is None:
            return None, "bad", calls
        pairs = pairs[:30]
        with _CACHE_LOCK:
            pc = _cache_get(_pools_path()) or {}
            if not isinstance(pc, dict):
                pc = {}
            pc = {k: v for k, v in pc.items() if isinstance(v, dict) and float(v.get("until") or 0) > now}
            pc[key] = {"pairs": pairs or None, "until": int(now + (POOL_TTL_S if pairs else NEG_TTL_S))}
            _cache_put(_pools_path(), pc)
        if not pairs:
            return None, "no_pool", calls
    touched = {(a.lower() if evm else a) for a in (tx_addrs or ())}
    hit = [p for p in pairs if (p["pool"].lower() if evm else p["pool"]) in touched]
    best = hit[0] if hit else sorted(pairs, key=lambda p: (str(p.get("qsym") or "").upper() not in _MAJOR_Q, -p["liq"]))[0]
    best = dict(best, matched=bool(hit))
    return best, None, calls


def fetch_gt(chain, pool, token, iv, t0, t1, now=None, res="minute", keyed=True):
    now = now or time.time()
    net = GT_NETWORK.get(chain)
    if not net or not pool:
        return Result(why="unsupported", note=f"GeckoTerminal 미지원 체인 {chain}")
    if res == "hour":
        iv, agg, tf = "1h", 1, "hour"
    elif res == "day":
        iv, agg, tf = "1d", 1, "day"
    else:
        agg = {"1m": 1, "5m": 5}.get(iv)
        tf = "minute"
        if not agg:
            return Result(why="unsupported")
    s = IV_SEC[iv]
    t0 = int(t0) // s * s
    t1 = -(-int(t1) // s) * s
    if now - t0 > GT_MAX_AGE_S:
        return Result(why="too_old", note="GeckoTerminal 무료 API 는 지난 180일까지만")
    nk = f"gt:{chain}:{pool.lower()}"
    if neg_get(nk, now):
        return Result(why="no_market", note="GeckoTerminal 풀 없음(최근 확인)", cached=True)
    closed = t1 + CLOSED_AFTER_S < now
    cp = _cpath("dex", chain, pool.lower(), str(token or "").lower(), iv, t0, t1)
    if closed:
        c = _cache_get(cp)
        if _cache_ok(c, now):
            return Result(candles=c["candles"] or None, why=None if c["candles"] else (c.get("why") or "no_data"),
                          note=c.get("note"), cached=True)
    rows, calls, deadline = [], 0, time.time() + DEADLINE_S + 30
    b = min(t1, int(now))
    complete = False
    oldest_seen = None
    pages = 0
    try:
        while b > t0 and pages < MAX_PAGES:
            n = min(1000, max(1, -(-(b - t0) // s)))
            url = (f"https://api.geckoterminal.com/api/v2/networks/{net}/pools/{urllib.parse.quote(pool, safe='')}/ohlcv/{tf}"
                   f"?aggregate={agg}&before_timestamp={b}&limit={n}&currency=usd"
                   + (f"&token={urllib.parse.quote(token, safe='')}" if token else ""))
            calls += 1
            pages += 1
            try:
                kind9, kv9 = _keyed(url, "past", keyed, lambda d9: parse_gt(d9) is not None, deadline)
                if kind9 == "ok":
                    d = kv9
                elif kind9 == "err":
                    raise kv9
                else:
                    d = _get(url, headers={"Accept": "application/json;version=20230302"}, deadline=deadline, inline_wait=30.0)
            except bf_engine.NetError as e:
                if getattr(e, "kind", "") == "budget":
                    return Result(why="time", note="GeckoTerminal 조회 시간 초과(요청 마감)", calls=calls)
                if getattr(e, "code", None) == 401 and "180 days" in str(e):
                    return Result(why="too_old", note="GeckoTerminal 무료 API 는 지난 180일까지만", calls=calls)
                if getattr(e, "kind", "") == "http4xx" and getattr(e, "code", None) == 404:
                    neg_put(nk, "no_market")
                    return Result(why="no_market", note="GeckoTerminal 풀 없음", calls=calls)
                return Result(why="net", note=f"GeckoTerminal 조회 실패({getattr(e, 'kind', '?')}: {common.safe_err(e)[:80]})", calls=calls)
            got = parse_gt(d)
            if got is None:
                return Result(why="bad", note=f"GeckoTerminal 응답 형식 이상: {str(d)[:100]}", calls=calls)
            rows.extend(got)
            if not got:
                complete = True
                break
            oldest = min(r[0] for r in got)
            if oldest_seen is not None and oldest >= oldest_seen:
                break
            oldest_seen = oldest
            if oldest <= t0:
                complete = True
                break
            b = oldest - 1
    except BudgetExceeded as e:
        return Result(why="budget", note=common.safe_err(e), calls=calls)
    out = norm(rows, t0, t1)
    why = None if out else "no_data"
    note = None if out else "GeckoTerminal 그 구간 봉 없음(무료 API 과거 한도·풀 생성 전·거래 없음)"
    if closed:
        _cache_store(cp, ["dex", chain, pool, token, iv, t0, t1], out, why, note, complete, now)
    return Result(candles=out or None, why=why, note=note, calls=calls, complete=complete)


def fetch_spec(spec, iv, t0, t1, now=None, res=None):
    v = spec.get("venue")
    if v == "dex":
        sp = dict(spec)
        calls0 = 0
        if (now or time.time()) - int(t0) > GT_MAX_AGE_S:
            sp.pop("tx_addrs", None)
            return Result(why="too_old", note="GeckoTerminal 무료 API 는 지난 180일까지만"), sp
        if not sp.get("pool"):
            pool, why, calls0 = find_pool(sp.get("chain"), sp.get("token"), sp.get("tx_addrs") or (), now=now)
            if not pool:
                note = {"no_pool": "DEX 풀 못 찾음(DexScreener 페어 없음)", "unsupported": f"DEX 미지원 체인 {sp.get('chain')}"}.get(
                    why, f"DEX 풀 조회 실패({why})")
                return Result(why="no_market" if why in ("no_pool", "unsupported") else ("budget" if why == "budget" else "net"),
                              note=note, calls=calls0), sp
            sp.update(pool=pool["pool"], dex=pool.get("dex"), poolMatched=pool.get("matched"), liq=pool.get("liq"),
                      pair=None)
        sp.pop("tx_addrs", None)
        r = fetch_gt(sp["chain"], sp["pool"], sp.get("token"), iv, t0, t1, now=now, res=res or "minute")
        r.calls += calls0
        return r, sp
    if v == "coingecko":
        if spec.get("id"):
            return fetch_cg_id_hourly(spec["id"], t0, t1, now=now), dict(spec)
        return fetch_cg_hourly(spec.get("chain"), spec.get("token"), t0, t1, now=now), dict(spec)
    if res == "hour":
        iv = "1h"
    key = (spec_key(spec), iv, int(t0), int(t1))
    with _CACHE_LOCK:
        ev = _INFLIGHT.get(key)
        mine = ev is None
        if mine:
            ev = _INFLIGHT[key] = threading.Event()
    if not mine:
        ev.wait(DEADLINE_S + 5)
    try:
        return fetch_cex(v, spec.get("base"), spec.get("quote"), iv, t0, t1, now=now), dict(spec)
    finally:
        if mine:
            with _CACHE_LOCK:
                _INFLIGHT.pop(key, None)
            ev.set()


CEX_ORDER_USD = ("binance", "bybit")
CEX_ORDER_KRW = ("upbit", "bithumb")


def plan_chain(primary, base_sym, display_cur, dex_specs=(), max_cex_alts=5):
    out, seen = [], set()
    base_sym = re.sub(r"[^A-Za-z0-9]", "", str(base_sym or "").split("#", 1)[0])

    def add(sp, res, tag):
        if sp.get("venue") != "dex" and banned_market(sp.get("venue"), sp.get("quote")) and tag != "primary":
            return
        k = (spec_key(sp), res)
        if k in seen:
            return
        seen.add(k)
        out.append((sp, res, tag))
    if primary:
        add(primary, None, "primary")
    b = str(base_sym or "").upper()
    n_alt = 0
    krw_first = display_cur == "KRW"
    order = (CEX_ORDER_KRW + CEX_ORDER_USD) if krw_first else (CEX_ORDER_USD + CEX_ORDER_KRW)
    if b:
        for v in order:
            if n_alt >= max_cex_alts:
                break
            if not krw_first and v in CEX_ORDER_KRW:
                break
            q = "KRW" if v in CEX_ORDER_KRW else "USDT"
            sp = {"venue": v, "base": b, "quote": q}
            if primary and spec_key(sp) == spec_key(primary):
                continue
            add(sp, None, "alt_cex")
            n_alt += 1
    for d in dex_specs or ():
        add(d, None, "dex")
    if primary and primary.get("venue") != "dex" and not banned_market(primary.get("venue"), primary.get("quote")):
        add(primary, "hour", "lowres")
    if b:
        add({"venue": "binance", "base": b, "quote": "USDT"}, "hour", "lowres")
        add({"venue": "bybit", "base": b, "quote": "USDT"}, "hour", "lowres")
    for d in (dex_specs or ())[:1]:
        add(d, "hour", "lowres")
    return out


def quote_cur(spec):
    if spec.get("venue") == "dex" or spec.get("venue") == "coingecko":
        return "USD"
    q = str(spec.get("quote") or "").upper()
    if q == "KRW":
        return "KRW"
    if q in USD_LIKE:
        return "USD"
    return q or "?"


def convert(candles, factor_rows, mode):
    if not candles or not factor_rows:
        return None
    fr = sorted((r[0], r[4]) for r in factor_rows if r[4] > 0)
    if not fr:
        return None
    out, j = [], 0
    for r in candles:
        while j + 1 < len(fr) and fr[j + 1][0] <= r[0]:
            j += 1
        k = fr[j][1]
        if mode == "mul":
            out.append([r[0], r[1] * k, r[2] * k, r[3] * k, r[4] * k, r[5]])
        else:
            out.append([r[0], r[1] / k, r[2] / k, r[3] / k, r[4] / k, r[5]])
    return out


def too_old_rule(spec, res, iv, t0, now=None):
    now = now or time.time()
    age = now - int(t0)
    v = spec.get("venue")
    if v == "dex":
        return "GeckoTerminal 무료 API 는 지난 180일까지만" if age > GT_MAX_AGE_S else None
    if v == "coingecko":
        return "코인게코 무키 API 는 지난 365일까지만" if age > CG_MAX_AGE_S else None
    if v == "gate":
        use_iv = "1h" if res == "hour" else iv
        s = IV_SEC.get(use_iv)
        if s and age / s > GATE_MAX_POINTS:
            return f"게이트 {use_iv} 봉은 최근 {int(GATE_MAX_POINTS * s / 86400)}일까지만(공개 API 한도)"
    return None


def date_aware(chain_plan, iv, t0, now=None):
    now = now or time.time()
    out = list(chain_plan)
    seen = {(spec_key(sp), res) for sp, res, _t in out}
    extra = []
    for sp, res, tag in chain_plan:
        if too_old_rule(sp, res, iv, t0, now) is None:
            continue
        if sp.get("venue") == "gate" and res != "hour":
            extra.append((0, ({k: v for k, v in sp.items()}, "hour", "lowres")))
        elif sp.get("venue") == "dex" and sp.get("token") and CG_PLATFORM.get(sp.get("chain")):
            extra.append((1, ({"venue": "coingecko", "chain": sp.get("chain"), "token": sp.get("token")}, "hour", "lowres")))
    for _o, (sp, res, tag) in sorted(extra, key=lambda x: x[0]):
        k = (spec_key(sp), res)
        if k in seen or too_old_rule(sp, res, iv, t0, now) is not None:
            continue
        seen.add(k)
        out.append((sp, res, tag))
    return out


def median_px(fills):
    xs = sorted(float(f.get("px") or 0) for f in fills or () if isinstance(f, dict) and (f.get("px") or 0) > 0)
    return xs[len(xs) // 2] if xs else None


def _ref_ok(cands, ref_px):
    if not ref_px or not cands:
        return True, ""
    cl = sorted(float(c[4]) for c in cands if c[4] > 0)
    if not cl:
        return True, ""
    r = cl[len(cl) // 2] / float(ref_px)
    return (IDENT_LO <= r <= IDENT_HI), f"봉 시세가 체결가의 {r:.2f}배 — 동명 다른 코인 의심"


def best_chart(chain_plan, iv, t0, t1, display_cur, now=None, max_tries=8, fx_rows_fn=None, budget_s=None, by_date=True, ref_px=None):
    tried, calls = [], 0
    holder9 = next((sp.get("venue") for sp, res, tag in chain_plan if tag == "primary"), None)
    t_start = time.time()
    plan = date_aware(chain_plan, iv, t0, now=now) if by_date else list(chain_plan)
    if by_date and holder9 in CG_EX_ID:
        b9 = next((sp.get("base") for sp, res, tag in chain_plan if tag == "primary"), None)
        cid9 = holder_cg_id(holder9, b9, now=now, fetch=False) if b9 else None
        if cid9:
            plan.append(({"venue": "coingecko", "id": cid9}, "hour", "lowres"))
    n_try = 0
    for i, (sp, res, tag) in enumerate(plan):
        if n_try >= max_tries:
            break
        if budget_s is not None and time.time() - t_start > budget_s:
            tried.append({"label": spec_label(sp), "iv": "1h" if res == "hour" else iv, "why": "time", "note": "시간 초과로 시도 안 함"})
            break
        r, sp2 = fetch_spec(sp, iv, t0, t1, now=now, res=res)
        calls += r.calls
        if r.ok or r.calls:
            n_try += 1
        use_iv = "1h" if res == "hour" else iv
        if not r.ok:
            tried.append({"label": spec_label(sp2), "iv": use_iv, "why": r.why, "note": r.note})
            if r.why == "budget":
                break
            continue
        cands = r.candles
        if tag != "primary" and sp2.get("venue") not in ("dex", "coingecko") and holder9 and sp2.get("venue") != holder9:
            ok9, note9 = same_coin(holder9, sp2.get("venue"), sp2.get("base"), now=now, fetch=False)
            if ok9 is False:
                tried.append({"label": spec_label(sp2), "iv": use_iv, "why": "same_name", "note": note9})
                continue
        qc = quote_cur(sp2)
        fx = None
        if display_cur in ("KRW", "USD") and qc != display_cur:
            if qc not in ("KRW", "USD"):
                tried.append({"label": spec_label(sp2), "iv": use_iv, "why": "quote", "note": f"{qc} 표기 마켓 — 환산 불가"})
                continue
            fxr = fx_rows_fn(use_iv, t0, t1) if fx_rows_fn else None
            fx_c = (fxr.candles if fxr is not None else None)
            if fxr is not None:
                calls += fxr.calls
            conv = convert(cands, fx_c, "mul" if display_cur == "KRW" else "div")
            if not conv:
                tried.append({"label": spec_label(sp2), "iv": use_iv, "why": "fx", "note": "환율(업비트 KRW-USDT) 봉 없음 — 환산 불가"})
                continue
            cands = conv
            fx = {"src": "업비트 KRW-USDT", "mode": "USD→KRW" if display_cur == "KRW" else "KRW→USD",
                  "avg": round(sum(r9[4] for r9 in fx_c) / len(fx_c), 2)}
        if tag != "primary" and sp2.get("venue") not in ("dex", "coingecko"):
            ok9, note9 = _ref_ok(cands, ref_px)
            if not ok9:
                tried.append({"label": spec_label(sp2), "iv": use_iv, "why": "same_name", "note": note9})
                continue
        src = {"label": spec_label(sp2), "key": spec_key(sp2), "venue": sp2.get("venue"), "iv": use_iv, "res": use_iv,
               "tag": tag, "fallback": i > 0, "cur": display_cur, "fx": fx, "cached": r.cached}
        if sp2.get("venue") == "dex":
            src.update(chain=sp2.get("chain"), pool=sp2.get("pool"), dex=sp2.get("dex"), poolMatched=bool(sp2.get("poolMatched")))
        return {"ok": True, "candles": cands, "src": src, "tried": tried, "calls": calls, "complete": bool(r.complete), "spec": sp2, "res": res}
    return {"ok": False, "candles": None, "src": None, "tried": tried, "calls": calls}


def fx_rows(iv, t0, t1, now=None):
    return fetch_cex("upbit", "USDT", "KRW", iv, t0, t1, now=now)


CG_PLATFORM = {"eth": "ethereum", "bsc": "binance-smart-chain", "base": "base", "arbitrum": "arbitrum-one",
               "optimism": "optimistic-ethereum", "polygon": "polygon-pos", "sol": "solana", "gnosis": "xdai",
               "zksync": "zksync", "avalanche": "avalanche", "berachain": "berachain", "plasma": "plasma",
               "scroll": "scroll", "fraxtal": "fraxtal", "kaia": "kaia", "abstract": "abstract", "monad": "monad",
               "megaeth": "megaeth", "story": "story", "bob": "bob-network", "xlayer": "x-layer", "robinhood": "robinhood"}
CG_MAX_AGE_S = 364 * 86400


def parse_cg_range(d):
    if not isinstance(d, dict) or not isinstance(d.get("prices"), list):
        return None
    out = []
    for r in d["prices"]:
        if isinstance(r, list) and len(r) >= 2:
            x = _row(int(float(r[0])) // 1000, r[1], r[1], r[1], r[1], 0)
            if x:
                out.append(x)
    return out


def fetch_cg(chain, token, t0, t1, now=None, keyed=True):
    now = now or time.time()
    plat = CG_PLATFORM.get(chain)
    if not plat or not token:
        return Result(why="unsupported", note=f"코인게코 미지원 체인 {chain}")
    t0 = max(int(t0), int(now - CG_MAX_AGE_S))
    t1 = int(t1)
    if t1 <= t0:
        return Result(why="too_old", note="코인게코 무키 API 는 지난 365일까지만")
    tk = token.lower() if chain != "sol" else token
    nk = f"cg:{chain}:{tk}"
    if neg_get(nk, now):
        return Result(why="no_market", note="코인게코 미추적 토큰(최근 확인)", cached=True)
    t0d, t1d = t0 // 86400 * 86400, -(-t1 // 86400) * 86400
    closed = t1d + CLOSED_AFTER_S < now
    cp = _cpath("cg", chain, tk, t0d, t1d)
    if closed:
        c = _cache_get(cp)
        if _cache_ok(c, now):
            return Result(candles=c["candles"] or None, why=None if c["candles"] else (c.get("why") or "no_data"),
                          note=c.get("note"), cached=True)
    url = (f"https://api.coingecko.com/api/v3/coins/{plat}/contract/{urllib.parse.quote(tk, safe='')}/market_chart/range"
           f"?vs_currency=usd&from={t0d}&to={t1d}")
    try:
        dl9 = time.time() + DEADLINE_S + 60
        kind9, kv9 = _keyed(url, "past", keyed, lambda d9: parse_cg_range(d9) is not None, dl9)
        if kind9 == "ok":
            d = kv9
        elif kind9 == "err":
            raise kv9
        else:
            d = _get(url, deadline=dl9, inline_wait=60.0)
    except BudgetExceeded as e:
        return Result(why="budget", note=common.safe_err(e))
    except bf_engine.NetError as e:
        if getattr(e, "kind", "") == "budget":
            return Result(why="time", note="코인게코 조회 시간 초과(요청 마감)", calls=1)
        if getattr(e, "kind", "") == "http4xx" and getattr(e, "code", None) == 404:
            neg_put(nk, "no_market", ttl=7 * 86400)
            return Result(why="no_market", note="코인게코 미추적 토큰", calls=1)
        if getattr(e, "code", None) == 401:
            return Result(why="too_old", note=f"코인게코 무키 API 한도({common.safe_err(e)[:80]})", calls=1)
        return Result(why="net", note=f"코인게코 조회 실패({getattr(e, 'kind', '?')}: {common.safe_err(e)[:80]})", calls=1)
    got = parse_cg_range(d)
    if got is None:
        return Result(why="bad", note=f"코인게코 응답 형식 이상: {str(d)[:100]}", calls=1)
    out = norm(got, t0d, t1d)
    why = None if out else "no_data"
    if closed:
        _cache_store(cp, ["cg", chain, tk, t0d, t1d], out, why, None if out else "코인게코 그 구간 시세 없음", True, now)
    return Result(candles=out or None, why=why, note=None if out else "코인게코 그 구간 시세 없음", calls=1)


def points_to_hourly(points, t0, t1):
    s = 3600
    a, b = int(t0) // s * s, int(t1)
    buckets = {}
    for r in sorted(points or (), key=lambda x: x[0]):
        k = int(r[0]) // s * s
        if k < a or k >= b:
            continue
        e = buckets.get(k)
        if e is None:
            buckets[k] = [k, r[4], r[4], r[4], r[4], 0.0]
        else:
            e[2], e[3], e[4] = max(e[2], r[4]), min(e[3], r[4]), r[4]
    return [buckets[k] for k in sorted(buckets)]


def fetch_cg_hourly(chain, token, t0, t1, now=None):
    now = now or time.time()
    if now - int(t0) > CG_MAX_AGE_S:
        return Result(why="too_old", note="코인게코 무키 API 는 지난 365일까지만")
    r = fetch_cg(chain, token, int(t0) // 3600 * 3600, t1, now=now)
    if not r.ok:
        return r
    out = points_to_hourly(r.candles, t0, t1)
    if not out:
        return Result(why="no_data", note="코인게코 그 구간 시세 점 없음", cached=r.cached, calls=r.calls)
    return Result(candles=out, cached=r.cached, calls=r.calls, complete=True,
                  note="코인게코 1시간 시세 점(체결 봉 아님 — 고·저는 점의 최고·최저, 거래량 없음)")


CG_EX_ID = {"binance": "binance", "bybit": "bybit_spot", "upbit": "upbit", "bithumb": "bithumb"}
CG_MAP_TTL_S = 7 * 86400
CG_MAP_PAGES = 3
IDENT_LO, IDENT_HI = 0.5, 2.0
_CGX_LOCK = threading.Lock()
KNOWN_CG_ID = {"BTC": "bitcoin", "ETH": "ethereum", "BNB": "binancecoin", "SOL": "solana", "AVAX": "avalanche-2", "OKB": "okb",
               "XRP": "ripple", "DOGE": "dogecoin", "TRX": "tron", "ADA": "cardano", "POL": "polygon-ecosystem-token"}


def parse_cg_ex_tickers(d):
    if not isinstance(d, dict) or not isinstance(d.get("tickers"), list):
        return None
    return [(str(t["base"]).upper(), str(t["coin_id"])) for t in d["tickers"]
            if isinstance(t, dict) and t.get("base") and t.get("coin_id")]


def _cgx_path(ex):
    return os.path.join(CACHE_DIR, f"cgx_{ex}.json")


def cg_exmap(ex, now=None, fetch=True, pages=CG_MAP_PAGES):
    cgid = CG_EX_ID.get(ex)
    if not cgid:
        return None
    now = now or time.time()
    c = _cache_get(_cgx_path(ex))
    c = c if isinstance(c, dict) else {}

    def full(c9):
        m9 = c9.get("map") if c9.get("done") else c9.get("prev")
        return m9 if isinstance(m9, dict) else None
    if not fetch or (c.get("done") and now - float(c.get("at") or 0) < CG_MAP_TTL_S):
        return full(c)
    if not _CGX_LOCK.acquire(blocking=False):
        return full(c)
    try:
        c = _cache_get(_cgx_path(ex))
        c = c if isinstance(c, dict) else {}
        if c.get("done") and now - float(c.get("at") or 0) < CG_MAP_TTL_S:
            return full(c)
        if c.get("done") or not c.get("page"):
            c = {"page": 1, "done": False, "map": {}, "prev": c.get("map") if c.get("done") else c.get("prev")}
        m = c.setdefault("map", {})
        for _i in range(max(0, int(pages))):
            url = f"https://api.coingecko.com/api/v3/exchanges/{cgid}/tickers?page={int(c['page'])}&depth=false"
            try:
                d = _get(url, deadline=time.time() + DEADLINE_S + 60, inline_wait=60.0)
            except (BudgetExceeded, bf_engine.NetError):
                break
            got = parse_cg_ex_tickers(d)
            if got is None:
                break
            for b9, cid9 in got:
                lst9 = m.setdefault(b9, [])
                if cid9 not in lst9:
                    lst9.append(cid9)
            if len(d.get("tickers") or ()) < 100:
                c.update(done=True, at=int(now))
                c.pop("prev", None)
                break
            c["page"] = int(c["page"]) + 1
        _cache_put(_cgx_path(ex), c)
        return full(c)
    finally:
        _CGX_LOCK.release()


def cg_ids(ex, base, now=None, fetch=True):
    m = cg_exmap(ex, now=now, fetch=fetch)
    return None if m is None else set(m.get(str(base or "").upper()) or ())


def same_coin(holder, venue, base, now=None, fetch=True):
    if not holder or not venue or holder == venue:
        return None, ""
    h = cg_ids(holder, base, now, fetch)
    if not h:
        return None, ""
    v = cg_ids(venue, base, now, fetch)
    if not v:
        return None, ""
    if h & v:
        return True, f"코인게코 {sorted(h & v)[0]}"
    return False, (f"{VENUE_KO.get(venue, venue)} {str(base).upper()} = 다른 코인(코인게코 {','.join(sorted(v))[:60]} ≠ "
                   f"{VENUE_KO.get(holder, holder)} {','.join(sorted(h))[:60]})")


def holder_cg_id(holder, base, now=None, fetch=True):
    h = cg_ids(holder, base, now, fetch) if holder else None
    return next(iter(h)) if h and len(h) == 1 else None


def fetch_cg_id(cid, t0, t1, now=None, keyed=True):
    now = now or time.time()
    if not cid or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,99}", str(cid)):
        return Result(why="unsupported", note="코인게코 id 없음")
    t0 = max(int(t0), int(now - CG_MAX_AGE_S))
    t1 = int(t1)
    if t1 <= t0:
        return Result(why="too_old", note="코인게코 무키 API 는 지난 365일까지만")
    nk = f"cgid:{cid}"
    if neg_get(nk, now):
        return Result(why="no_market", note="코인게코 id 없음(최근 확인)", cached=True)
    t0d, t1d = t0 // 86400 * 86400, -(-t1 // 86400) * 86400
    closed = t1d + CLOSED_AFTER_S < now
    cp = _cpath("cg", "id", cid, t0d, t1d)
    if closed:
        c = _cache_get(cp)
        if _cache_ok(c, now):
            return Result(candles=c["candles"] or None, why=None if c["candles"] else (c.get("why") or "no_data"), note=c.get("note"), cached=True)
    url = f"https://api.coingecko.com/api/v3/coins/{cid}/market_chart/range?vs_currency=usd&from={t0d}&to={t1d}"
    try:
        dl9 = time.time() + DEADLINE_S + 60
        kind9, kv9 = _keyed(url, "past", keyed, lambda d9: parse_cg_range(d9) is not None, dl9)
        if kind9 == "ok":
            d = kv9
        elif kind9 == "err":
            raise kv9
        else:
            d = _get(url, deadline=dl9, inline_wait=60.0)
    except BudgetExceeded as e:
        return Result(why="budget", note=common.safe_err(e))
    except bf_engine.NetError as e:
        if getattr(e, "kind", "") == "budget":
            return Result(why="time", note="코인게코 조회 시간 초과(요청 마감)", calls=1)
        if getattr(e, "kind", "") == "http4xx" and getattr(e, "code", None) == 404:
            neg_put(nk, "no_market", ttl=7 * 86400)
            return Result(why="no_market", note="코인게코 id 없음", calls=1)
        return Result(why="net", note=f"코인게코 조회 실패({getattr(e, 'kind', '?')}: {common.safe_err(e)[:80]})", calls=1)
    got = parse_cg_range(d)
    if got is None:
        return Result(why="bad", note=f"코인게코 응답 형식 이상: {str(d)[:100]}", calls=1)
    out = norm(got, t0d, t1d)
    if closed:
        _cache_store(cp, ["cg", "id", cid, t0d, t1d], out, None if out else "no_data", None, True, now)
    return Result(candles=out or None, why=None if out else "no_data", calls=1)


_CG_SIMPLE = {}


def _cg_error_body(d) -> bool:
    if not isinstance(d, dict):
        return True
    st9 = d.get("status")
    if isinstance(st9, dict) and ("error_code" in st9 or "error_message" in st9):
        return True
    er9 = d.get("error")
    return er9 is not None and not (isinstance(er9, dict) and "usd" in er9)


def cg_simple_usd(ids, now=None, ttl=600, fail=None, keyed=False, key_only=False):
    now = now or time.time()
    ids = sorted({str(i) for i in ids or () if i and re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,99}", str(i))})
    want = [i for i in ids if not (i in _CG_SIMPLE and now - _CG_SIMPLE[i][0] < ttl)]
    if want:
        u9 = "https://api.coingecko.com/api/v3/simple/price?ids=" + urllib.parse.quote(",".join(want[:100])) + "&vs_currencies=usd"
        try:
            kind9, kv9 = _keyed(u9, "live", keyed or key_only, lambda d9: not _cg_error_body(d9), time.time() + 30)
            if kind9 == "ok":
                d = kv9
            elif kind9 == "err":
                d = None
            elif key_only:
                return {i: _CG_SIMPLE[i][1] for i in ids if i in _CG_SIMPLE and _CG_SIMPLE[i][1]}
            else:
                d = _get(u9, deadline=time.time() + 30, inline_wait=10.0)
        except (BudgetExceeded, bf_engine.NetError):
            d = None
        if d is None or _cg_error_body(d):
            d = None
            if fail is not None:
                fail.append("coingecko")
        for i in want[:100]:
            v = _f(((d or {}).get(i) or {}).get("usd")) if isinstance(d, dict) else None
            if v and v > 0:
                _CG_SIMPLE[i] = (now, v)
            elif isinstance(d, dict):
                _CG_SIMPLE[i] = (now, None)
    return {i: _CG_SIMPLE[i][1] for i in ids if i in _CG_SIMPLE and _CG_SIMPLE[i][1]}


def fetch_cg_id_hourly(cid, t0, t1, now=None):
    now = now or time.time()
    if now - int(t0) > CG_MAX_AGE_S:
        return Result(why="too_old", note="코인게코 무키 API 는 지난 365일까지만")
    r = fetch_cg_id(cid, int(t0) // 3600 * 3600, t1, now=now)
    if not r.ok:
        return r
    out = points_to_hourly(r.candles, t0, t1)
    if not out:
        return Result(why="no_data", note="코인게코 그 구간 시세 점 없음", cached=r.cached, calls=r.calls)
    return Result(candles=out, cached=r.cached, calls=r.calls, complete=True,
                  note="코인게코 1시간 시세 점(체결 봉 아님 — 고·저는 점의 최고·최저, 거래량 없음)")
