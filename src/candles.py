"""Candle (OHLCV) fetcher with venue fallback chain and local cache."""
from __future__ import annotations

import contextlib
import gzip
import hashlib
import json
import os
import re
import threading
import time
import urllib.parse
import zlib
from datetime import datetime, timezone

import bf_engine
import fsio, logs, num_parse, paths, statefile
import calcguard  # noqa: E402

from timeutil import KST
CACHE_DIR = paths.state("candles")
IV_SEC = {"1m": 60, "5m": 300, "1h": 3600, "1d": 86400}
MAX_PAGES = 12
CLOSED_AFTER_S = 3600
NEG_TTL_S = 6 * 3600
POOL_TTL_S = 7 * 86400
POOL_SRC = "token-pairs"
POOL_CAND_MAX = 30
POOL_KEEP_MAX = 200
GT_PAGE_ROWS = 20
POOL_TRY_MAX = 4
DEX_EMPTY_TTL_S = 60 * 86400
DEADLINE_S = 45.0
GT_MAX_AGE_S = 179 * 86400
GATE_MAX_POINTS = 9990
USD_LIKE = {"USDT", "USDC", "USD", "FDUSD", "USD1", "BUSD", "TUSD", "DAI", "USDE", "PYUSD", "USDG"}

HOST_POLICY = {
    "api.geckoterminal.com": {"rate": 0.2, "burst": 1, "conc": 1, "share": "gt_free", "share_rate": 0.15, "share_burst": 1, "share_xproc": True},
    "api.dexscreener.com": {"rate": 2.0, "burst": 3, "conc": 1},
    "api.upbit.com": {"rate": 4.0, "burst": 4, "conc": 2},
    "api.bithumb.com": {"rate": 4.0, "burst": 4, "conc": 2},
    "api.binance.com": {"rate": 4.0, "burst": 4, "conc": 2},
    "fapi.binance.com": {"rate": 0.5, "burst": 2, "conc": 1},
    "api.bybit.com": {"rate": 4.0, "burst": 4, "conc": 2},
    "www.okx.com": {"rate": 4.0, "burst": 4, "conc": 2},
    "api.gateio.ws": {"rate": 4.0, "burst": 4, "conc": 2},
    "api.kucoin.com": {"rate": 4.0, "burst": 4, "conc": 2},
    "api.coinbase.com": {"rate": 4.0, "burst": 4, "conc": 2},
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
    import pricing as _px, token_tables
    GT_NETWORK.update(getattr(_px, "GT_NETWORK", {}) or {})
    DS_CHAIN.update(getattr(token_tables, "DS_CHAIN", {}) or {})
except Exception as e_cg:   # noqa: BLE001 [optional]
    calcguard.swallowed("candles:<module>[pricing_tables]", e_cg)
    pass

VENUE_KO = {"upbit": "업비트", "bithumb": "빗썸", "binance": "바이낸스", "binance_futures": "바이낸스 선물", "bybit": "바이빗", "bybit_linear": "바이빗 선물",
            "okx": "OKX", "gate": "게이트", "kucoin": "쿠코인", "coinbase": "코인베이스", "dex": "DEX"}
CHAIN_KO = {"eth": "Ethereum", "bsc": "BSC", "base": "Base", "sol": "Solana", "arbitrum": "Arbitrum", "polygon": "Polygon",
            "optimism": "Optimism", "zksync": "zkSync", "megaeth": "MegaETH", "robinhood": "Robinhood"}

CALLS = {"n": 0, "by_host": {}}
CALL_CAP = [None]
_CALL_LOCK = threading.Lock()


class BudgetExceeded(RuntimeError):
    pass


class Result:
    __slots__ = ("candles", "why", "note", "cached", "calls", "complete", "sure")

    def __init__(self, candles=None, why=None, note=None, cached=False, calls=0, complete=True, sure=False):
        self.candles, self.why, self.note, self.cached, self.calls = candles, why, note, cached, calls
        self.complete = complete
        self.sure = sure

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


FG_DEFER_WAIT_S = 10.0
BG_PACE_S = 60.0
BG_KEY_FRAC = 0.5
DEFER_WHYS = ("deferred", "bg_pace", "bg_stop")
LATER_WHYS = DEFER_WHYS + ("net", "time", "budget")
DEFER_NOTE = "오늘 몫 소진 — DEX 봉은 나중에 채움"
BG_PACE_NOTE = "미리 받기 간격(분당 1회) — 다음 차례에"
BG_STOP_NOTE = "오늘 미리 받기 멈춤(호출 제한 429) — 내일 다시"
_BG = {"last": {}, "stop": {}}
_BG_LOCK = threading.Lock()
BG_SLEEP = [time.sleep]


@contextlib.contextmanager
def chart_mode(mode):
    prev = getattr(_TL, "mode", None)
    _TL.mode = mode
    try:
        yield
    finally:
        _TL.mode = prev


def chart_mode_now():
    return getattr(_TL, "mode", None)


@contextlib.contextmanager
def count_calls():
    prev = getattr(_TL, "ncalls", None)
    cell = [0]
    _TL.ncalls = cell
    try:
        yield cell
    finally:
        _TL.ncalls = prev
        if prev is not None:
            prev[0] += cell[0]


def _kst_day(t=None) -> str:
    return datetime.fromtimestamp(time.time() if t is None else t, KST).strftime("%Y-%m-%d")


def bg_stopped(host="api.geckoterminal.com") -> bool:
    with _BG_LOCK:
        return _BG["stop"].get(host) == _kst_day()


def _bg_mark_429(host, e) -> bool:
    if chart_mode_now() != "bg" or getattr(e, "kind", "") not in ("http429", "quota"):
        return False
    with _BG_LOCK:
        _BG["stop"][host] = _kst_day()
    return True


def _keyless_room(host, deadline=None):
    mode = chart_mode_now()
    if mode == "fg":
        try:
            w = bf_engine.gate_wait(host)
        except Exception as _cg9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("candles:_keyless_room", _cg9)
            w = 0.0
        return ("deferred", DEFER_NOTE) if w > FG_DEFER_WAIT_S else None
    if mode != "bg":
        return None
    while True:
        with _BG_LOCK:
            now = time.time()
            if _BG["stop"].get(host) == _kst_day(now):
                return "bg_stop", BG_STOP_NOTE
            w = float(_BG["last"].get(host) or 0.0) + BG_PACE_S - now
            if w <= 0:
                _BG["last"][host] = now
                return None
        lims = [x for x in (getattr(_TL, "dl", None), deadline) if x is not None]
        if lims and now + w > min(lims) - 15:
            return "bg_pace", BG_PACE_NOTE
        BG_SLEEP[0](min(w, 5.0))


def _bg_key_ok() -> bool:
    try:
        import cgkey
        import nft
        k = cgkey.key()
        if not k:
            return False
        plan, rec = cgkey.plan_of(k)
        if plan != "pro":
            return False
        b = cgkey.budget()
        _r, share = cgkey._record(k)
        if cgplan_basis(rec, b, share) != "pro":
            return False
        _pm, pd = nft.cg_key_windows(rec, b, share)
        return int(b.cg_usage().get("total") or 0) + 1 <= int(pd) * BG_KEY_FRAC
    except Exception as _cg9:   # noqa: BLE001 [probe]
        calcguard.swallowed("candles:_bg_key_ok", _cg9)
        return False


def cgplan_basis(rec, b, share) -> str:
    import cgplan
    return str(cgplan.budget(rec, b.now(), share, b.month_count("coingecko_key")).get("basis") or "")


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
            nc9 = getattr(_TL, "ncalls", None)
            if nc9 is not None:
                nc9[0] += 1
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
    except Exception as _cg9:   # noqa: BLE001 [fallback]
        calcguard.swallowed("candles:_keyed", _cg9)
        return "skip", "import"
    if not cgkey.key():
        return "skip", "nokey"
    if chart_mode_now() == "bg" and not _bg_key_ok():
        return "skip", "bg"
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
    return num_parse.to_float(x)


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


def parse_coinbase(d: object):
    rows = d.get("candles") if isinstance(d, dict) else None
    if not isinstance(rows, list):
        return None
    out = []
    for r in rows:
        if isinstance(r, dict) and r.get("start") not in (None, ""):
            x = _row(int(float(r["start"])), r.get("open"), r.get("high"), r.get("low"), r.get("close"), r.get("volume"))
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


def parse_ds_pairs(d, chain_id, bad: list | None = None):
    if isinstance(d, dict):
        d = d.get("pairs") or []
    if not isinstance(d, list):
        return None
    out = []
    for p in d:
        if not isinstance(p, dict) or not p.get("pairAddress"):
            if bad is not None:
                bad[0] += 1
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


def parse_gt_pools(d: object, bad: list | None = None) -> list | None:
    rows = d.get("data") if isinstance(d, dict) else None
    if not isinstance(rows, list):
        return None
    out = []
    for p in rows:
        a = p.get("attributes") if isinstance(p, dict) else None
        if not isinstance(a, dict) or not a.get("address"):
            if bad is not None:
                bad[0] += 1
            continue
        nm = str(a.get("name") or "")
        qsym = nm.split("/", 1)[1].strip().split(" ")[0] if "/" in nm else ""
        try:
            cr = _utc_s(a["pool_created_at"]) if a.get("pool_created_at") else 0
        except (ValueError, TypeError):
            cr = 0
        dx = ((((p.get("relationships") or {}).get("dex") or {}).get("data") or {}).get("id")) if isinstance(p.get("relationships"), dict) else None
        out.append({"pool": str(a["address"]), "dex": str(dx or ""), "liq": _f(a.get("reserve_in_usd")) or 0.0, "base": "", "quote": "",
                    "qsym": qsym, "created": int(cr)})
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
    if venue in ("binance", "binance_futures", "bybit", "bybit_linear"):
        return f"{b}{q}"
    if venue in ("okx", "kucoin", "coinbase"):
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
        with open(path, "rb") as f:
            raw = f.read()
        if raw[:2] == b"\x1f\x8b":
            return _bars_unpack(json.loads(gzip.decompress(raw).decode("utf-8")))
        return json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, EOFError, TypeError, zlib.error):
        return None


BAR_SIG = 6


def _sig(x, sig):
    if sig and type(x) is float and x == x and x not in (float("inf"), float("-inf")):
        return float(format(x, ".%dg" % sig))
    return x


def _bars_pack(rec, sig=BAR_SIG):
    rows = rec.get("candles") if isinstance(rec, dict) else None
    if not (isinstance(rows, list) and all(isinstance(r, list) and len(r) == 6 for r in rows)):
        return rec
    cz = []
    for r in rows:
        r = [r[0]] + [_sig(x, sig) for x in r[1:]]
        o = r[1]
        cz.append([r[0], o, r[5]] if all(type(x) is type(o) and repr(x) == repr(o) for x in r[2:5]) else r)
    return {("cz" if k == "candles" else k): (cz if k == "candles" else v) for k, v in rec.items()}


def _bars_unpack(d):
    if isinstance(d, dict) and isinstance(d.get("cz"), list) and "candles" not in d:
        if not all(isinstance(r, list) and len(r) in (3, 6) for r in d["cz"]):
            raise ValueError("봉 행 꼴 아님")
        rows = [[r[0], r[1], r[1], r[1], r[1], r[2]] if len(r) == 3 else r for r in d["cz"]]
        d = {("candles" if k == "cz" else k): (rows if k == "cz" else v) for k, v in d.items()}
    return d


def bars_encode(rec: dict, sig: int | None = BAR_SIG) -> bytes:
    return gzip.compress(json.dumps(_bars_pack(rec, sig), ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 6, mtime=0)


def _bars_put(path, rec):
    try:
        fsio.atomic_write_bytes(path, bars_encode(rec))
    except Exception as exc:   # noqa: BLE001 [optional]
        calcguard.swallowed("candles:_bars_put", exc)


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
    _bars_put(path, rec)


def _cache_put(path, obj):
    try:
        statefile.atomic_write_json(path, obj)
    except Exception as _cg9:   # noqa: BLE001 [optional]
        calcguard.swallowed("candles:_cache_put", _cg9)
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


PAGE_N = {"upbit": 200, "bithumb": 200, "binance": 1000, "binance_futures": 1000, "bybit": 1000, "bybit_linear": 1000, "okx": 100,
          "gate": 900, "kucoin": 1500, "coinbase": 300, "dex": 1000}


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
    if venue in ("bybit", "bybit_linear"):
        ivb = {"1m": "1", "5m": "5", "1h": "60", "1d": "D"}[iv]
        return (f"https://api.bybit.com/v5/market/kline?category={'linear' if venue == 'bybit_linear' else 'spot'}&symbol={q(mk)}&interval={ivb}"
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
    if venue == "coinbase":
        g = {"1m": "ONE_MINUTE", "5m": "FIVE_MINUTE", "1h": "ONE_HOUR", "1d": "ONE_DAY"}[iv]
        return (f"https://api.coinbase.com/api/v3/brokerage/market/products/{q(mk)}/candles?start={a}&end={b - 1}&granularity={g}",
                parse_coinbase)
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
        if venue in ("kucoin", "coinbase"):
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
        if venue in ("bybit", "bybit_linear"):
            return body.get("retCode") in (10001, "10001") or "symbol" in str(body.get("retMsg") or "").lower()
        if venue == "okx":
            return str(body.get("code")) in ("51001", "51000")
        if venue == "kucoin":
            return str(body.get("code")) in ("400100", "900001")
    return False


def _day_live(rows, iv):
    if iv != "1d" or not rows:
        return rows
    return [r for r in rows if isinstance(r, list) and len(r) >= 6 and r[5] and r[5] > 0]


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
            kept = _day_live(c["candles"], iv)
            return Result(candles=kept or None, why=None if kept else (c.get("why") or "no_data"),
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
                return Result(why="net", note=f"{VENUE_KO.get(venue, venue)} 봉 조회 실패({getattr(e, 'kind', '?')}: {logs.safe_err(e)[:80]})",
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
        return Result(why="budget", note=logs.safe_err(e), calls=calls)
    out = _day_live(norm(rows, t0, t1), iv)
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
    cands, why, calls = pool_candidates(chain, token, tx_addrs, now=now)
    return (cands[0] if cands else None), why, calls


def _keep_cut_miss(ent: dict, touched: set, evm: bool, now: float) -> bool:
    pairs = ent.get("pairs") or ()
    if not (ent.get("cut") and touched and len(pairs) >= POOL_KEEP_MAX):
        return False
    if now < max(float(ent.get("until") or 0) - POOL_TTL_S, float(ent.get("missAt") or 0)) + NEG_TTL_S:
        return False
    return not any((str(p.get("pool") or "").lower() if evm else p.get("pool")) in touched for p in pairs if isinstance(p, dict))


def pool_candidates(chain: str, token: str, tx_addrs: tuple | list = (), now: float | None = None) -> tuple:
    now = now or time.time()
    net = DS_CHAIN.get(chain)
    if not net or not token:
        return None, "unsupported", 0
    evm = chain != "sol"
    tk = token.lower() if evm else token
    key = f"{chain}:{tk}"
    touched = {(a.lower() if evm else a) for a in (tx_addrs or ())}
    pairs, cut = None, False
    with _CACHE_LOCK:
        pc = _cache_get(_pools_path()) or {}
        ent = pc.get(key) if isinstance(pc, dict) else None
        live = isinstance(ent, dict) and float(ent.get("until") or 0) > now and ent.get("src") == POOL_SRC
        miss = live and _keep_cut_miss(ent, touched, evm, now)
        if miss:
            pc[key] = dict(ent, missAt=int(now))
            _cache_put(_pools_path(), pc)
    if (live and not miss
            and not ("cut" not in ent and len(ent.get("pairs") or ()) >= min(GT_PAGE_ROWS, POOL_CAND_MAX))):
        pairs, cut = ent.get("pairs"), bool(ent.get("cut"))
        if pairs is None:
            return None, "no_pool", 0
    calls = 0
    if pairs is None:
        calls = 1
        try:
            d = _get(f"https://api.dexscreener.com/token-pairs/v1/{net}/{urllib.parse.quote(token, safe='')}", deadline=time.time() + 20)
        except BudgetExceeded:
            return None, "budget", 0
        except bf_engine.NetError as e:
            return None, f"net:{getattr(e, 'kind', '?')}", calls
        bad = [0]
        pairs = parse_ds_pairs(d, net, bad)
        if pairs is None:
            return None, "bad", calls
        cut = bad[0] > 0
        if not pairs and GT_NETWORK.get(chain):
            gt_pairs, gt_why, gt_calls, gt_cut = _gt_token_pools(chain, token)
            calls += gt_calls
            if gt_why:
                return None, gt_why, calls
            pairs, cut = gt_pairs or [], cut or gt_cut
        if not pairs and cut:
            return None, "bad", calls
        if len(pairs) > POOL_KEEP_MAX:
            ids = {id(p) for p in [q for q in pairs if (q["pool"].lower() if evm else q["pool"]) in touched][:POOL_KEEP_MAX]}
            ids |= {id(p) for p in [q for q in pairs if id(q) not in ids][:max(0, POOL_KEEP_MAX - len(ids))]}
            pairs, cut = [p for p in pairs if id(p) in ids], True
        with _CACHE_LOCK:
            pc = _cache_get(_pools_path()) or {}
            if not isinstance(pc, dict):
                pc = {}
            pc = {k: v for k, v in pc.items() if isinstance(v, dict) and float(v.get("until") or 0) > now}
            pc[key] = {"pairs": pairs or None, "until": int(now + (POOL_TTL_S if pairs else NEG_TTL_S)), "src": POOL_SRC, "cut": cut}
            _cache_put(_pools_path(), pc)
        if not pairs:
            return None, "no_pool", calls
    hit = [p for p in pairs if (p["pool"].lower() if evm else p["pool"]) in touched]
    rest = sorted((p for p in pairs if p not in hit), key=lambda p: (str(p.get("qsym") or "").upper() not in _MAJOR_Q, -p["liq"]))
    out = [dict(p, matched=True) for p in hit] + [dict(p, matched=False) for p in rest]
    if len(out) > POOL_CAND_MAX:
        out, cut = out[:POOL_CAND_MAX], True
    if cut:
        for p in out:
            p["poolsCut"] = True
    return out, None, calls


def _gt_token_pools(chain, token):
    url = (f"https://api.geckoterminal.com/api/v2/networks/{GT_NETWORK[chain]}/tokens/{urllib.parse.quote(token, safe='')}/pools?page=1")
    deadline = time.time() + DEADLINE_S
    room = _keyless_room("api.geckoterminal.com", deadline)
    if room:
        return None, room[0], 0, False
    try:
        d = _get(url, headers={"Accept": "application/json;version=20230302"}, deadline=deadline, inline_wait=30.0,
                 **({"single": True} if chart_mode_now() == "bg" else {}))
    except BudgetExceeded:
        return None, "budget", 0, False
    except bf_engine.NetError as e:
        if _bg_mark_429("api.geckoterminal.com", e):
            return None, "bg_stop", 1, False
        if getattr(e, "kind", "") == "http4xx" and getattr(e, "code", None) == 404:
            return [], None, 1, False
        return None, f"net:{getattr(e, 'kind', '?')}", 1, False
    bad = [0]
    pools = parse_gt_pools(d, bad)
    if pools is None:
        return None, "bad", 1, False
    return pools, None, 1, len(d["data"]) >= GT_PAGE_ROWS or bad[0] > 0


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
    nk = f"gt:{chain}:{pool.lower()}"
    closed = t1 + CLOSED_AFTER_S < now
    cp = _cpath("dex", chain, pool.lower(), str(token or "").lower(), iv, t0, t1)
    if closed:
        c = _cache_get(cp)
        if _cache_ok(c, now) and (c["candles"] or now - t0 <= GT_MAX_AGE_S):
            return Result(candles=c["candles"] or None, why=None if c["candles"] else (c.get("why") or "no_data"),
                          note=c.get("note"), cached=True)
    if now - t0 > GT_MAX_AGE_S:
        return Result(why="too_old", note="GeckoTerminal 무료 API 는 지난 180일까지만")
    if neg_get(nk, now):
        return Result(why="no_market", note="GeckoTerminal 풀 없음(최근 확인)", cached=True)
    rows, calls, deadline = [], 0, time.time() + DEADLINE_S + 30
    if chart_mode_now() == "bg" and getattr(_TL, "dl", None) is not None:
        deadline = max(deadline, _TL.dl)
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
                    rm9 = _keyless_room("api.geckoterminal.com", deadline)
                    if rm9:
                        return Result(why=rm9[0], note=rm9[1], calls=calls - 1 + (1 if kind9 == "fail" else 0), complete=False)
                    bg9 = chart_mode_now() == "bg"
                    if bg9:
                        deadline = max(deadline, time.time() + 30)
                    d = _get(url, headers={"Accept": "application/json;version=20230302"}, deadline=deadline, inline_wait=30.0,
                             **({"single": True} if bg9 else {}))
            except bf_engine.NetError as e:
                if _bg_mark_429("api.geckoterminal.com", e):
                    return Result(why="bg_stop", note=BG_STOP_NOTE, calls=calls)
                if getattr(e, "kind", "") == "budget":
                    return Result(why="time", note="GeckoTerminal 조회 시간 초과(요청 마감)", calls=calls)
                if getattr(e, "code", None) == 401 and "180 days" in str(e):
                    return Result(why="too_old", note="GeckoTerminal 무료 API 는 지난 180일까지만", calls=calls)
                if getattr(e, "kind", "") == "http4xx" and getattr(e, "code", None) == 404:
                    neg_put(nk, "no_market", ttl=DEX_EMPTY_TTL_S)
                    return Result(why="no_market", note="GeckoTerminal 풀 없음", calls=calls)
                return Result(why="net", note=f"GeckoTerminal 조회 실패({getattr(e, 'kind', '?')}: {logs.safe_err(e)[:80]})", calls=calls)
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
        return Result(why="budget", note=logs.safe_err(e), calls=calls)
    out = norm(rows, t0, t1)
    why = None if out else "no_data"
    note = None if out else "GeckoTerminal 그 구간 봉 없음(무료 API 과거 한도·풀 생성 전·거래 없음)"
    if closed:
        _cache_store(cp, ["dex", chain, pool, token, iv, t0, t1], out, why, note, complete, now)
        if complete and not out:
            _bars_put(cp, dict(_cache_get(cp) or {}, until=int(now + DEX_EMPTY_TTL_S)))
    return Result(candles=out or None, why=why, note=note, calls=calls, complete=complete)


def fetch_spec(spec, iv, t0, t1, now=None, res=None):
    v = spec.get("venue")
    if v == "dex":
        sp = dict(spec)
        calls0 = 0
        if (now or time.time()) - int(t0) > GT_MAX_AGE_S:
            sp.pop("tx_addrs", None)
            return _dex_old(sp, iv, t0, t1, now, res)
        if not sp.get("pool"):
            cands, why, calls0 = pool_candidates(sp.get("chain"), sp.get("token"), sp.get("tx_addrs") or (), now=now)
            if not cands and why in DEFER_WHYS:
                return Result(why=why, note={"deferred": DEFER_NOTE, "bg_pace": BG_PACE_NOTE, "bg_stop": BG_STOP_NOTE}[why],
                              calls=calls0, complete=False), sp
            if not cands:
                note = {"no_pool": "DEX 풀 못 찾음(DexScreener·GeckoTerminal 풀 없음)", "unsupported": f"DEX 미지원 체인 {sp.get('chain')}"}.get(
                    why, f"DEX 풀 조회 실패({why})")
                return Result(why="no_market" if why in ("no_pool", "unsupported") else ("budget" if why == "budget" else "net"),
                              note=note, calls=calls0), sp
            had_tx = bool(sp.pop("tx_addrs", None))
            return _fetch_pools(sp, cands, had_tx, calls0, (iv, t0, t1, now, res))
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


_DEX_IDX = {"mt": None, "map": {}}


def _dex_norm(iv, t0, t1, res):
    iv = "1h" if res == "hour" else ("1d" if res == "day" else iv)
    s = IV_SEC.get(iv)
    if not s:
        return None
    return iv, int(t0) // s * s, -(-int(t1) // s) * s


def _dex_index(now):
    d = os.path.join(CACHE_DIR, "dex")
    try:
        mt = os.stat(d).st_mtime_ns
    except OSError:
        return {}
    with _CACHE_LOCK:
        if _DEX_IDX["mt"] == mt:
            return _DEX_IDX["map"]
    idx = {}
    for ent in os.scandir(d):
        if not ent.name.endswith(".json"):
            continue
        c = _cache_get(ent.path)
        k = c.get("key") if isinstance(c, dict) else None
        if not (isinstance(k, list) and len(k) == 7 and _cache_ok(c, now) and c["candles"]):
            continue
        try:
            kk = (str(k[1]), str(k[3] or "").lower(), str(k[4]), int(k[5]), int(k[6]))
        except (TypeError, ValueError):
            continue
        if len(c["candles"]) > idx.get(kk, (0, ""))[0]:
            idx[kk] = (len(c["candles"]), ent.path)
    with _CACHE_LOCK:
        _DEX_IDX.update(mt=mt, map=idx)
    return idx


def _dex_old(sp, iv, t0, t1, now, res):
    now = now or time.time()
    if sp.get("pool"):
        return fetch_gt(sp["chain"], sp["pool"], sp.get("token"), iv, t0, t1, now=now, res=res or "minute"), sp
    nk = _dex_norm(iv, t0, t1, res)
    hit = _dex_index(now).get((str(sp.get("chain")), str(sp.get("token") or "").lower()) + nk) if nk else None
    c = _cache_get(hit[1]) if hit else None
    if isinstance(c, dict) and c.get("candles"):
        k = c.get("key") or []
        return Result(candles=c["candles"], note=c.get("note"), cached=True), dict(sp, pool=str(k[2]), pair=None)
    return Result(why="too_old", note="GeckoTerminal 무료 API 는 지난 180일까지만"), sp


def _cg_old_cached(parts, t0, t1, now):
    t0d, t1d = int(t0) // 86400 * 86400, -(-int(t1) // 86400) * 86400
    if t1d + CLOSED_AFTER_S >= now:
        return None
    c = _cache_get(_cpath(*parts, t0d, t1d))
    if _cache_ok(c, now) and c["candles"]:
        return Result(candles=c["candles"], note=c.get("note"), cached=True)
    return None


def _fetch_pools(sp, cands, had_tx, calls0, win):
    iv, t0, t1, now, res = win
    calls, asked, paid, born, first = calls0, 0, 0, 0, None
    for p in cands:
        if int(p.get("created") or 0) and int(p["created"]) >= int(t1):
            born += 1
            continue
        if paid >= POOL_TRY_MAX:
            break
        asked += 1
        sp2 = dict(sp, pool=p["pool"], dex=p.get("dex"), poolMatched=p.get("matched"), liq=p.get("liq"), pair=None)
        r = fetch_gt(sp2["chain"], sp2["pool"], sp2.get("token"), iv, t0, t1, now=now, res=res or "minute")
        calls += r.calls
        paid += 1 if r.calls else 0
        if first is None:
            first = sp2
        if r.ok:
            r.calls = calls
            return r, sp2
        if r.why not in ("no_data", "no_market") or (r.why == "no_data" and not r.complete):
            r.calls = calls
            return r, sp2
    n_cand = len(cands)
    n_seen = born + asked
    part = any(p.get("poolsCut") for p in cands)
    miss = had_tx and not any(p.get("matched") for p in cands)
    sure = n_seen >= n_cand and not part and not miss
    again = "" if sure else (" — 풀 목록이 다 오지 않아 다음에 다시" if part else " — 다음에 다시")
    if not asked:
        note = f"DEX 풀 {n_cand}개 모두 그 구간 뒤에 생김(풀 생성 전) — 그 구간 봉 없음" + again
    elif n_seen >= n_cand:
        note = f"DEX 후보 풀 {asked}개 모두 그 구간 봉 없음" + (f"(그 밖 {born}개는 구간 뒤 생성)" if born else "") + again
    else:
        note = f"DEX 후보 풀 {n_cand}개 중 {n_seen}개만 확인(모두 봉 없음) — 나머지는 다음에 다시"
    if had_tx and not any(p.get("matched") for p in cands):
        note = "체결 풀을 DEX 페어 목록에서 못 찾음 · " + note
    sp_out = first or dict(sp, pool=cands[0]["pool"], dex=cands[0].get("dex"), poolMatched=cands[0].get("matched"),
                           liq=cands[0].get("liq"), pair=None)
    return Result(why="no_data", note=note, calls=calls, complete=True, sure=sure), sp_out


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
        if k in seen or (sp.get("venue") != "coingecko" and too_old_rule(sp, res, iv, t0, now) is not None):
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
    kw = dict(now=now, max_tries=max_tries, fx_rows_fn=fx_rows_fn, by_date=by_date, ref_px=ref_px)
    mode = chart_mode_now()
    t_start = time.time()
    r = _best_chart(chain_plan, iv, t0, t1, display_cur, budget_s=budget_s, defer_stop=(mode == "fg"), **kw)
    if mode != "fg" or r["ok"] or not any(t9.get("why") == "deferred" for t9 in r["tried"]) \
            or all(tag == "bridge" for _sp, _res, tag in chain_plan):
        return r
    left9 = None if budget_s is None else max(0.0, budget_s - (time.time() - t_start))
    _TL.mode = None
    try:
        r2 = _best_chart(chain_plan, iv, t0, t1, display_cur, budget_s=left9, defer_stop=False, **kw)
    finally:
        _TL.mode = mode
    r2["calls"] = r2.get("calls", 0) + r.get("calls", 0)
    return r2


def _best_chart(chain_plan, iv, t0, t1, display_cur, now=None, max_tries=8, fx_rows_fn=None, budget_s=None, by_date=True, ref_px=None,
                defer_stop=False):
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
    later = None
    for i, (sp, res, tag) in enumerate(plan):
        if n_try >= max_tries:
            break
        if defer_stop and tag == "lowres" and any(t9.get("why") == "deferred" for t9 in tried):
            break
        if budget_s is not None and time.time() - t_start > budget_s:
            tried.append({"label": spec_label(sp), "iv": "1h" if res == "hour" else iv, "why": "time", "note": "시간 초과로 시도 안 함"})
            if sp.get("venue") in ("dex", "coingecko") and later is None:
                later = "time"
            break
        r, sp2 = fetch_spec(sp, iv, t0, t1, now=now, res=res)
        calls += r.calls
        if r.ok or r.calls:
            n_try += 1
        use_iv = "1h" if res == "hour" else iv
        if not r.ok:
            tried.append({"label": spec_label(sp2), "iv": use_iv, "why": r.why, "note": r.note})
            if sp2.get("venue") == "dex" and r.why == "no_data":
                tried[-1]["sure"] = bool(r.sure)
            if later is None and r.why in LATER_WHYS and sp2.get("venue") in ("dex", "coingecko"):
                later = r.why
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
        return {"ok": True, "candles": cands, "src": src, "tried": tried, "calls": calls, "complete": bool(r.complete), "spec": sp2, "res": res,
                "dexLater": None if (sp2.get("venue") == "dex" and res != "hour") else later}
    return {"ok": False, "candles": None, "src": None, "tried": tried, "calls": calls, "dexLater": later}


def fx_rows(iv, t0, t1, now=None):
    return fetch_cex("upbit", "USDT", "KRW", iv, t0, t1, now=now)


CG_PLATFORM = {"eth": "ethereum", "bsc": "binance-smart-chain", "base": "base", "arbitrum": "arbitrum-one",
               "optimism": "optimistic-ethereum", "polygon": "polygon-pos", "sol": "solana", "gnosis": "xdai",
               "zksync": "zksync", "avalanche": "avalanche", "berachain": "berachain", "plasma": "plasma",
               "scroll": "scroll", "fraxtal": "fraxtal", "kaia": "kaia", "abstract": "abstract", "monad": "monad",
               "megaeth": "megaeth", "story": "story", "bob": "bob-network", "xlayer": "x-layer", "robinhood": "robinhood",
               "hyperevm": "hyperevm"}
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
            if chart_mode_now() == "bg":
                rm9 = _keyless_room("api.coingecko.com", dl9)
                if rm9:
                    return Result(why=rm9[0], note=rm9[1], calls=1 if kind9 == "fail" else 0)
                dl9 = max(dl9, time.time() + 30)
            d = _get(url, deadline=dl9, inline_wait=60.0, **({"single": True} if chart_mode_now() == "bg" else {}))
    except BudgetExceeded as e:
        return Result(why="budget", note=logs.safe_err(e))
    except bf_engine.NetError as e:
        if _bg_mark_429("api.coingecko.com", e):
            return Result(why="bg_stop", note=BG_STOP_NOTE, calls=1)
        if getattr(e, "kind", "") == "budget":
            return Result(why="time", note="코인게코 조회 시간 초과(요청 마감)", calls=1)
        if getattr(e, "kind", "") == "http4xx" and getattr(e, "code", None) == 404:
            neg_put(nk, "no_market", ttl=7 * 86400)
            return Result(why="no_market", note="코인게코 미추적 토큰", calls=1)
        if getattr(e, "code", None) == 401:
            return Result(why="too_old", note=f"코인게코 무키 API 한도({logs.safe_err(e)[:80]})", calls=1)
        return Result(why="net", note=f"코인게코 조회 실패({getattr(e, 'kind', '?')}: {logs.safe_err(e)[:80]})", calls=1)
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
        tk = token.lower() if chain != "sol" else token
        r = _cg_old_cached(("cg", chain, tk), int(t0) // 3600 * 3600, t1, now) if token else None
        if r is None:
            return Result(why="too_old", note="코인게코 무키 API 는 지난 365일까지만")
    else:
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
               "XRP": "ripple", "DOGE": "dogecoin", "TRX": "tron", "ADA": "cardano", "POL": "polygon-ecosystem-token",
               "HYPE": "hyperliquid", "SUI": "sui", "TON": "the-open-network"}


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
            if chart_mode_now() == "bg":
                rm9 = _keyless_room("api.coingecko.com", dl9)
                if rm9:
                    return Result(why=rm9[0], note=rm9[1], calls=1 if kind9 == "fail" else 0)
                dl9 = max(dl9, time.time() + 30)
            d = _get(url, deadline=dl9, inline_wait=60.0, **({"single": True} if chart_mode_now() == "bg" else {}))
    except BudgetExceeded as e:
        return Result(why="budget", note=logs.safe_err(e))
    except bf_engine.NetError as e:
        if _bg_mark_429("api.coingecko.com", e):
            return Result(why="bg_stop", note=BG_STOP_NOTE, calls=1)
        if getattr(e, "kind", "") == "budget":
            return Result(why="time", note="코인게코 조회 시간 초과(요청 마감)", calls=1)
        if getattr(e, "kind", "") == "http4xx" and getattr(e, "code", None) == 404:
            neg_put(nk, "no_market", ttl=7 * 86400)
            return Result(why="no_market", note="코인게코 id 없음", calls=1)
        return Result(why="net", note=f"코인게코 조회 실패({getattr(e, 'kind', '?')}: {logs.safe_err(e)[:80]})", calls=1)
    got = parse_cg_range(d)
    if got is None:
        return Result(why="bad", note=f"코인게코 응답 형식 이상: {str(d)[:100]}", calls=1)
    out = norm(got, t0d, t1d)
    if closed:
        _cache_store(cp, ["cg", "id", cid, t0d, t1d], out, None if out else "no_data", None, True, now)
    return Result(candles=out or None, why=None if out else "no_data", calls=1)


_CG_SIMPLE = {}
CG_SIMPLE_MAX_AGE_S = 3600


def _cg_error_body(d) -> bool:
    if not isinstance(d, dict):
        return True
    st9 = d.get("status")
    if isinstance(st9, dict) and ("error_code" in st9 or "error_message" in st9):
        return True
    er9 = d.get("error")
    return er9 is not None and not (isinstance(er9, dict) and "usd" in er9)


def cg_simple_usd(ids, now=None, ttl=600, fail=None, keyed=False, key_only=False, at: dict = None):
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
                return _cg_simple_have(ids, now, ttl, at)
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
    return _cg_simple_have(ids, now, ttl, at)


def _cg_simple_have(ids, now, ttl, at=None):
    lim = max(float(ttl or 0), CG_SIMPLE_MAX_AGE_S)
    out = {i: _CG_SIMPLE[i] for i in ids if i in _CG_SIMPLE and _CG_SIMPLE[i][1] and now - _CG_SIMPLE[i][0] <= lim}
    if at is not None:
        at.update({i: e[0] for i, e in out.items()})
    return {i: e[1] for i, e in out.items()}


def fetch_cg_id_hourly(cid, t0, t1, now=None):
    now = now or time.time()
    if now - int(t0) > CG_MAX_AGE_S:
        r = _cg_old_cached(("cg", "id", cid), int(t0) // 3600 * 3600, t1, now) if cid else None
        if r is None:
            return Result(why="too_old", note="코인게코 무키 API 는 지난 365일까지만")
    else:
        r = fetch_cg_id(cid, int(t0) // 3600 * 3600, t1, now=now)
    if not r.ok:
        return r
    out = points_to_hourly(r.candles, t0, t1)
    if not out:
        return Result(why="no_data", note="코인게코 그 구간 시세 점 없음", cached=r.cached, calls=r.calls)
    return Result(candles=out, cached=r.cached, calls=r.calls, complete=True,
                  note="코인게코 1시간 시세 점(체결 봉 아님 — 고·저는 점의 최고·최저, 거래량 없음)")
