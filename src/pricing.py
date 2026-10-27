"""Price sources and valuation."""
from __future__ import annotations

import json
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable
import acct_norm  # noqa: E402
import ex_sign, logs, net_http, num_parse  # noqa: E402
import fsio  # noqa: E402
import calcguard  # noqa: E402
import token_tables

_UA = {"Accept": "application/json", "User-Agent": "tj-bot/0.1 (personal trade journal)"}

DOLLAR_NATIVES = {"XDAI", "USDC", "USDT"}

MAJOR_CANDLE_SYMS = {"ETH", "BTC", "SOL", "POL", "BNB", "AVAX"}
NATIVE_EX_TICKER = {"TON": "GRAM"}


UPBIT_CANDLE_GAP = 0.15
_UPBIT_PACE = {"next": 0.0}
_UPBIT_PACE_LOCK = threading.Lock()


def _upbit_pace(url: str) -> None:
    if not str(url).startswith("https://api.upbit.com/v1/candles/"):
        return
    with _UPBIT_PACE_LOCK:
        now9 = time.monotonic()
        at9 = max(now9, _UPBIT_PACE["next"])
        _UPBIT_PACE["next"] = at9 + UPBIT_CANDLE_GAP
    if at9 > now9:
        time.sleep(at9 - now9)


def _gj(url: str, timeout: float = 10.0):
    _upbit_pace(url)
    req = net_http.request(url, headers=_UA)
    with net_http.urlopen(req, timeout=timeout) as r:
        return json.loads(net_http.read_capped(r).decode())


class BulkError(RuntimeError):

    def __init__(self, ex, body):
        super().__init__(f"{ex} 벌크 시세 오류 응답: {str(body)[:120]}")


def _fin(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def _kl_zero(row, vi, qi) -> bool:
    try:
        return len(row) > max(vi, qi) and _vol_zero(row[vi]) and _vol_zero(row[qi])
    except TypeError:
        return False


def _c_binance(sym, ms):
    arr = _gj(f"https://api.binance.com/api/v3/klines?symbol={urllib.parse.quote(sym, safe='')}USDT&interval=1m"
              f"&startTime={ms}&endTime={ms + 59_999}&limit=1")
    if arr and _fin(float(arr[0][1])) and not _kl_zero(arr[0], 5, 7):
        return float(arr[0][1])
    return None


def _c_bybit(sym, ms):
    d = _gj(f"https://api.bybit.com/v5/market/kline?category=spot&symbol={urllib.parse.quote(sym, safe='')}USDT"
            f"&interval=1&start={ms}&end={ms + 59_999}&limit=1")
    rows = ((d.get("result") or {}).get("list")) or []
    if rows and _fin(float(rows[0][1])) and not _kl_zero(rows[0], 5, 6):
        return float(rows[0][1])
    return None


def _c_gate(sym, ms):
    arr = _gj(f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={urllib.parse.quote(sym, safe='')}_USDT"
              f"&interval=1m&from={ms // 1000}&to={ms // 1000 + 59}")
    if arr and len(arr[0]) >= 6 and _fin(float(arr[0][5])):
        return float(arr[0][5])
    return None


def _c_kucoin(sym, ms):
    d = _gj(f"https://api.kucoin.com/api/v1/market/candles?type=1min&symbol={urllib.parse.quote(sym, safe='')}-USDT"
            f"&startAt={ms // 1000}&endAt={ms // 1000 + 60}")
    rows = d.get("data") or []
    want = ms // 1000
    for row in rows:
        try:
            if int(row[0]) == want and _fin(float(row[1])):
                return float(row[1])
        except (TypeError, ValueError, IndexError):
            continue
    if rows and _fin(float(rows[0][1])):
        return float(rows[0][1])
    return None


def _upbit_code(sym: str) -> str:
    try:
        import acct_norm
        for code, canon in (acct_norm._aliases().get("upbit") or {}).items():
            if canon == sym and code != sym:
                return code
    except Exception as _cg9:  # noqa: BLE001 [optional]
        calcguard.swallowed("pricing:_upbit_code", _cg9)
        pass
    return sym


def _c_upbit_krw(sym, ms):
    krw = _upbit_krw_minute(_upbit_code(sym), ms)
    if not krw:
        return None
    fx = _fx_candle_krw_per_usdt(ms)
    return krw / fx if fx and _fin(fx) else None


CG_MIN_GAP_S = 60.0
CG_DAY_CAP = 200
_CG_PACE = {"last": 0.0, "day": "", "n": 0}
_CG_PACE_LOCK = threading.Lock()
_CG_MEM = {}
CG_404_SEC = 6 * 3600
_CG_404 = {}


def _key_h(k) -> int:
    import hashlib
    return int(hashlib.sha1(str(k).encode()).hexdigest()[:12], 16)


def _cg_take() -> bool:
    with _CG_PACE_LOCK:
        now = time.time()
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        if _CG_PACE["day"] != day:
            _CG_PACE.update(day=day, n=0)
        if now - _CG_PACE["last"] < CG_MIN_GAP_S or _CG_PACE["n"] >= CG_DAY_CAP:
            return False
        _CG_PACE["last"] = now
        _CG_PACE["n"] += 1
        return True


def _cg_pts_at(pts, ms):
    pts = sorted((int(a), float(b)) for a, b in pts or () if b and float(b) > 0)
    if not pts:
        return None
    before = [x for x in pts if x[0] <= ms]
    after = [x for x in pts if x[0] > ms]
    if before and after and after[0][0] - before[-1][0] <= 86_400_000:
        (a0, p0), (a1, p1) = before[-1], after[0]
        return p0 + (p1 - p0) * (ms - a0) / (a1 - a0)
    gap = 86_400_000 if len(pts) <= 3 else 7_200_000
    near = min(pts, key=lambda x: abs(x[0] - ms))
    return near[1] if abs(near[0] - ms) <= gap else None


def _cg_sym_id(sym):
    try:
        import candles as _cd
    except Exception as _cg9:   # noqa: BLE001 [fallback]
        calcguard.swallowed("pricing:_cg_sym_id", _cg9)
        return None
    s9 = str(sym or "").upper()
    if _cd.KNOWN_CG_ID.get(s9):
        return _cd.KNOWN_CG_ID[s9]
    ids = set()
    for ex in _cd.CG_EX_ID:
        ids |= _cd.cg_ids(ex, s9, fetch=False) or set()
    return next(iter(ids)) if len(ids) == 1 else None


def cg_body_ok(d) -> bool:
    if not isinstance(d, dict) or not isinstance(d.get("prices"), list):
        return False
    st9 = d.get("status")
    return not (isinstance(st9, dict) and ("error_code" in st9 or "error_message" in st9)) and d.get("error") is None


def _cg_keyed(url, lane, allow, valid, timeout=15.0):
    if not allow:
        return "skip", "allow"
    try:
        import cgkey
    except Exception as _cg9:   # noqa: BLE001 [fallback]
        calcguard.swallowed("pricing:_cg_keyed", _cg9)
        return "skip", "import"
    if not cgkey.key():
        return "skip", "nokey"
    if url.startswith("https://api.coingecko.com/api/v3"):
        path = url[len("https://api.coingecko.com/api/v3"):]
    elif url.startswith(cgkey.GT_ROOT):
        path = cgkey.onchain(url)
    else:
        return "skip", "url"
    kind, v = cgkey.request(path, lane, cgkey.bf_via(timeout), allow=True, valid=valid)
    if kind == "fail":
        cgkey.mark_fallback(lane)
    return kind, v


def cg_points_day(key, url_base, day0, store=None, keyed=False):
    dk = f"{key}:{int(day0)}"
    if store is not None and dk in store:
        return store[dk]
    m = _CG_MEM.get(dk)
    if m and time.time() - m[0] < 600:
        return m[1]
    t404 = _CG_404.get(key)
    if t404 is not None and time.time() - t404 < CG_404_SEC:
        return []
    url = f"{url_base}/market_chart/range?vs_currency=usd&from={int(day0) - 3600}&to={int(day0) + 86400 + 3600}"
    kind, kv = _cg_keyed(url, "past", keyed, cg_body_ok)
    try:
        if kind == "ok":
            d = kv
        elif kind == "err":
            raise kv
        else:
            if not _cg_take():
                return None
            d = _gj(url, timeout=15)
        if not cg_body_ok(d):
            return None
        pts = [[int(float(r[0])), float(r[1])] for r in d["prices"] if isinstance(r, list) and len(r) >= 2 and r[1]]
    except urllib.error.HTTPError as e:
        if e.code != 404:
            return None
        pts = []
        _CG_404[key] = time.time()
    except Exception as e:   # noqa: BLE001 [fallback]
        calcguard.swallowed("pricing:cg_points_day", e)
        if getattr(e, "code", None) == 404 and getattr(e, "kind", "") == "http4xx":
            pts = []
            _CG_404[key] = time.time()
        else:
            return None
    if store is not None and int(day0) + 86400 + 7200 < time.time():
        store[dk] = pts
    else:
        _CG_MEM[dk] = (time.time(), pts)
    return pts


def _c_coingecko(sym, ms, cache=None):
    cid = _cg_sym_id(sym)
    if not cid:
        return None
    day0 = (int(ms) // 1000) // 86400 * 86400
    key, url = f"id:{cid}", f"https://api.coingecko.com/api/v3/coins/{urllib.parse.quote(cid, safe='')}"
    if cache is None:
        store = _CG_STORE[0]
        pts = cg_points_day(key, url, day0, store, keyed=True)
    else:
        dk = f"{key}:{int(day0)}"
        with cache.lock:
            own = cache.d.setdefault("cgday", {})
            tmp = {dk: own[dk]} if dk in own else {}
        pts = cg_points_day(key, url, day0, tmp, keyed=True)
        if dk in tmp:
            with cache.lock:
                if dk not in own:
                    own[dk] = tmp[dk]
                    cache._dirty += 1
    v = _cg_pts_at(pts, int(ms)) if pts else None
    if v:
        import logging
        logging.getLogger("tj").info("1분봉 없음 → 코인게코 %s 근사 %s @%d", cid, v, int(ms) // 1000)
    return v


_CG_STORE = [None]


CANDLE_ORDER = (("binance", _c_binance), ("bybit", _c_bybit),
                ("upbit_krw", _c_upbit_krw),
                ("coingecko", _c_coingecko))


UPBIT_NOMKT_SEC = 3600
_UPBIT_NOMKT = {}


def _upbit_krw_minute(sym: str, ms: int) -> float | None:
    from datetime import datetime, timezone
    started = time.time()
    t404 = _UPBIT_NOMKT.get(sym)
    if t404 is not None and started - t404 < UPBIT_NOMKT_SEC and (ms // 60_000 + 1) * 60 <= t404:
        return None
    to_s = datetime.fromtimestamp(ms / 1000 + 60, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        arr = _gj(f"https://api.upbit.com/v1/candles/minutes/1?market=KRW-{urllib.parse.quote(sym, safe='')}&to={to_s}&count=30")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            _UPBIT_NOMKT[sym] = started
        raise
    _UPBIT_NOMKT.pop(sym, None)
    best = None
    for c in arr or []:
        ts = datetime.strptime(c["candle_date_time_utc"], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp() * 1000
        if ms - 30 * 60_000 < ts <= ms and _fin(float(c["opening_price"])):
            if best is None or ts > best[0]:
                best = (ts, float(c["opening_price"]))
    return best[1] if best else None


def _fx_candle_krw_per_usdt(ms) -> float | None:
    from datetime import datetime, timezone
    to_s = datetime.fromtimestamp(ms / 1000 + 60, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    arr = _gj(f"https://api.upbit.com/v1/candles/minutes/1?market=KRW-USDT&to={to_s}&count=30")
    best = None
    for c in arr or []:
        ts = datetime.strptime(c["candle_date_time_utc"], "%Y-%m-%dT%H:%M:%S") \
            .replace(tzinfo=timezone.utc).timestamp() * 1000
        if ts <= ms and _fin(float(c["opening_price"])):
            if best is None or ts > best[0]:
                best = (ts, float(c["opening_price"]))
    if best is None and ms < FX_USDT_FIRST_MS + 86_400_000:
        return _fx_cross_btc(ms)
    return best[1] if best else None


FX_USDT_FIRST_MS = 1717718400000


def _fx_cross_btc(ms) -> float | None:
    from datetime import datetime, timezone
    to_s = datetime.fromtimestamp(ms / 1000 + 60, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    arr = _gj(f"https://api.upbit.com/v1/candles/minutes/1?market=KRW-BTC&to={to_s}&count=30")
    ub = []
    for c in arr or []:
        try:
            ub.append((datetime.strptime(c["candle_date_time_utc"], "%Y-%m-%dT%H:%M:%S")
                       .replace(tzinfo=timezone.utc).timestamp() * 1000, float(c["opening_price"])))
        except (KeyError, TypeError, ValueError):
            continue
    kl = _gj(f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&startTime={int(ms) - 29 * 60_000}"
             f"&endTime={int(ms) + 59_999}&limit=30")
    bn = []
    for row in kl or []:
        try:
            bn.append((int(row[0]), float(row[1])))
        except (TypeError, ValueError, IndexError):
            continue
    return _cross_at(ms, ub, bn)


def _cross_at(m, ub, bn) -> float | None:
    krw = {ts: px for ts, px in ub
           if m - 30 * 60_000 < ts <= m and _fin(px) and px > 0}
    usdt = {ts: px for ts, px in bn
            if m - 30 * 60_000 < ts <= m and _fin(px) and px > 0}
    for ts in sorted(krw.keys() & usdt.keys(), reverse=True):
        fx = krw[ts] / usdt[ts]
        if _fin(fx):
            return fx
    return None


class PxCache:

    NEG_TTL = 6 * 3600
    NEG_MIN = 300

    def neg_ttl(self, sym: str) -> float:
        n = self.d.get("neg_n", {}).get(sym)
        if n is None:
            return float(self.NEG_TTL)
        try:
            return float(min(self.NEG_TTL, self.NEG_MIN * (2 ** max(0, min(int(n), 20) - 1))))
        except (TypeError, ValueError):
            return float(self.NEG_TTL)

    def neg_active(self, sym: str, now: float = None) -> bool:
        sym = str(sym).upper()
        with self.lock:
            neg = self.d["neg_ts"].get(sym, 0)
            ttl = self.neg_ttl(sym)
        return (time.time() if now is None else now) - float(neg or 0) < ttl

    def __init__(self, path: str, track_legacy: bool = False):
        self.path = path
        self.lock = threading.Lock()
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.d = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self.d = {}
        if not isinstance(self.d, dict):
            self.d = {}
        self.d.setdefault("candle", {})
        self.d.setdefault("neg_ts", {})
        self.d.setdefault("neg_n", {})
        self.d.setdefault("fx", {})
        _CG_STORE[0] = self.d.setdefault("cgday", {})
        self._legacy = set()
        new_leg9 = False
        if track_legacy:
            if not isinstance(self.d.get("cven_legacy"), list):
                new_leg9 = True
                cv9 = self.d.get("cven") or {}
                self.d["cven_legacy"] = sorted({_key_h(k9) for k9 in self.d["candle"] if ":" in k9 and k9 not in cv9
                                                and not k9.startswith(("UPBITKRW2:", "JPYUSD:"))})
                self.d["cven_t0"] = int(time.time() * 1000)
            self._legacy = set(int(x) for x in self.d.get("cven_legacy") or ())
        self.d["candle"] = {k: v for k, v in self.d["candle"].items() if v}
        self.d["fx"] = {k: v for k, v in self.d["fx"].items() if v}
        self._dirty = 20 if new_leg9 else 0
        self._flat = acct_norm.flat_keys(self.d["candle"])
        self._flat_syms = frozenset(k.rpartition(":")[0] for k in self._flat)
        self._tl = threading.local()

    def nb_begin(self):
        self._tl.nb = set()
        self._tl.took = False

    def nb_end(self) -> set:
        q = getattr(self._tl, "nb", None)
        self._tl.nb = None
        self._tl.took = False
        return q or set()

    def took_pending(self) -> bool:
        t = bool(getattr(self._tl, "took", False))
        self._tl.took = False
        return t

    def _nb(self):
        nb = getattr(self._tl, "nb", None)
        if nb is not None:
            self._tl.took = False
        return nb

    def candle_recent(self, sym: str, ts_ms: int, back_min: int = 10) -> float | None:
        nb = self._nb()
        if nb is None:
            return self.candle_usd(sym, ts_ms)
        sym_u = sym.upper()
        m = (ts_ms // 60_000) * 60_000
        with self.lock:
            v = self._cget(f"{sym_u}:{m}")
        if v:
            return v
        if sym_u in ("USDT", "USDC", "DAI"):
            return self.candle_usd(sym, ts_ms)
        with self.lock:
            for i in range(1, max(0, int(back_min)) + 1):
                v = self._cget(f"{sym_u}:{m - i * 60_000}")
                if v:
                    break
        if v:
            nb.add(("c", sym_u, m))
            self._tl.took = True
            return v
        return self.candle_usd(sym, ts_ms)

    def _cget(self, key):
        return None if key in self._flat else self.d["candle"].get(key)

    def _save(self):
        s9 = json.dumps(self.d, separators=(",", ":"))
        fsio.atomic_write_text(self.path, s9, mode=None, fsync=False, dir_fsync=False, makedirs=False)
        self._dirty = 0

    def maybe_save(self):
        with self.lock:
            if self._dirty >= 20:
                self._save()

    def flush(self):
        with self.lock:
            if self._dirty:
                self._save()

    def candle_usd(self, sym: str, ts_ms: int) -> float | None:
        self._nb()
        sym = sym.upper()
        m = (ts_ms // 60_000) * 60_000
        key = f"{sym}:{m}"
        with self.lock:
            if key in self.d["candle"] and key not in self._flat:
                v = self.d["candle"][key]
                return v if v else None
            neg = self.d["neg_ts"].get(sym, 0)
            ttl = self.neg_ttl(sym)
        if time.time() - neg < ttl:
            return None
        if sym in ("USDT", "USDC", "DAI"):
            return 1.0
        nb = getattr(self._tl, "nb", None)
        if nb is not None:
            nb.add(("c", sym, m))
            self._tl.took = True
            return None
        px = None
        ven9 = None
        alt9 = NATIVE_EX_TICKER.get(sym)
        url_ok9 = sym.isascii()
        for _name, fn in CANDLE_ORDER:
            if not url_ok9 and fn is not _c_coingecko:
                continue
            try:
                if fn is _c_coingecko:
                    px = fn(sym, m, cache=self)
                elif alt9 and _name == "upbit_krw":
                    px = fn(alt9, m)
                else:
                    px = fn(sym, m)
            except Exception as _cg9:  # noqa: BLE001 [fallback]
                calcguard.swallowed("pricing:PxCache.candle_usd[fn]", _cg9)
                px = None
            if not px and alt9 and _name in ("binance", "bybit"):
                try:
                    px = fn(alt9, m)
                except Exception as _cg9:  # noqa: BLE001 [fallback]
                    calcguard.swallowed("pricing:PxCache.candle_usd[px]", _cg9)
                    px = None
            if px:
                ven9 = _name
                break
        with self.lock:
            if px:
                self.d["candle"][key] = px
                self._flat.discard(key)
                self.d.setdefault("cven", {})[key] = ven9
                self.d["neg_ts"].pop(sym, None)
                self.d["neg_n"].pop(sym, None)
                self._dirty += 1
            else:
                self.d["neg_ts"][sym] = int(time.time())
                self.d["neg_n"][sym] = int(self.d["neg_n"].get(sym) or 0) + 1
                self._dirty += 1
        self.maybe_save()
        return px

    def jpy_stable_usd(self, sym: str, ts_ms: int) -> float | None:
        sym = sym.upper()
        m = (ts_ms // 60_000) * 60_000
        key = f"UPBITKRW2:{sym}:{m}"
        with self.lock:
            v = self.d["candle"].get(key)
        if v is None:
            try:
                v = _upbit_krw_minute(sym, m)
            except urllib.error.HTTPError as e:
                if getattr(e, "code", None) not in (400, 404):
                    return None
                v = None
            except Exception as _cg9:     # noqa: BLE001 [fallback]
                calcguard.swallowed("pricing:PxCache.jpy_stable_usd[v]", _cg9)
                return None
            if v:
                with self.lock:
                    self.d["candle"][key] = v
                    self._dirty += 1
        if v:
            fx = self.fx_at(m)
            if fx:
                return v / fx
            return None
        day = time.strftime("%Y-%m-%d", time.gmtime(m / 1000))
        dkey = f"JPYUSD:{day}"
        with self.lock:
            jv = self.d["candle"].get(dkey)
        if jv is None:
            try:
                d = _gj(f"https://api.frankfurter.app/{day}?from=JPY&to=USD")
                jv = float(((d or {}).get("rates") or {}).get("USD") or 0) or None
            except Exception as _cg9:  # noqa: BLE001 [fallback]
                calcguard.swallowed("pricing:PxCache.jpy_stable_usd[d]", _cg9)
                jv = None
            if jv:
                with self.lock:
                    self.d["candle"][dkey] = jv
                    self._dirty += 1
        self.maybe_save()
        return jv

    FX_WIN = 200
    KLINE_WIN = 1000

    def prefetch_fx(self, ms_list, max_calls: int = 60, deadline: float = None, pace: float = 0.15) -> dict:
        mins = sorted({(int(t) // 60_000) * 60_000 for t in ms_list})
        with self.lock:
            mins = [m for m in mins if str(m) not in self.d["fx"]]
        calls = filled = 0
        stop = False

        def _rest():
            with self.lock:
                return time.time() - float(self.d["neg_ts"].get("_fx", 0) or 0) < self.FX_NEG_SEC

        def _fail():
            with self.lock:
                self.d["neg_ts"]["_fx"] = int(time.time())
                self._dirty += 1
        if mins and _rest():
            return {"calls": 0, "filled": 0, "left": len(mins), "done": False}
        from datetime import datetime, timezone
        i = 0
        while i < len(mins) and calls < max_calls and (deadline is None or time.time() < deadline) and not stop and not _rest():
            end = mins[i] + (self.FX_WIN - 1) * 60_000
            grp = [m for m in mins[i:] if m <= end]
            if grp[-1] < FX_USDT_FIRST_MS:
                i += len(grp)
                continue
            to_s = datetime.fromtimestamp(end / 1000 + 60, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            try:
                arr = _gj(f"https://api.upbit.com/v1/candles/minutes/1?market=KRW-USDT&to={to_s}&count={self.FX_WIN}")
            except Exception as _cg9:  # noqa: BLE001 [fallback]
                calcguard.swallowed("pricing:PxCache.prefetch_fx[arr]", _cg9)
                arr = None
            calls += 1
            i += len(grp)
            if not isinstance(arr, list):
                _fail()
                stop = True
                break
            bars = []
            for c in arr or []:
                try:
                    ts = datetime.strptime(c["candle_date_time_utc"], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp() * 1000
                    px = float(c["opening_price"])
                except (KeyError, TypeError, ValueError):
                    continue
                if _fin(px):
                    bars.append((ts, px))
            bars.sort()
            if bars:
                with self.lock:
                    for m in grp:
                        if m < bars[0][0]:
                            continue
                        best = None
                        for ts, px in bars:
                            if ts <= m:
                                best = px
                            else:
                                break
                        if best:
                            self.d["fx"][str(m)] = best
                            filled += 1
                            self._dirty += 1
            if pace:
                time.sleep(pace)
        with self.lock:
            pre = [m for m in mins[:i] if m < FX_USDT_FIRST_MS + 86_400_000 and str(m) not in self.d["fx"]]
        j = 0
        while j < len(pre) and calls < max_calls and (deadline is None or time.time() < deadline) and not stop and not _rest():
            start = pre[j]
            end = start + (self.FX_WIN - 31) * 60_000
            grp = [m for m in pre[j:] if m <= end]
            j += len(grp)
            to_s = datetime.fromtimestamp(end / 1000 + 60, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            ub, bn = [], []
            try:
                for c in _gj(f"https://api.upbit.com/v1/candles/minutes/1?market=KRW-BTC&to={to_s}&count={self.FX_WIN}") or []:
                    try:
                        ub.append((datetime.strptime(c["candle_date_time_utc"], "%Y-%m-%dT%H:%M:%S")
                                   .replace(tzinfo=timezone.utc).timestamp() * 1000, float(c["opening_price"])))
                    except (KeyError, TypeError, ValueError):
                        continue
                for row in _gj(f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&startTime={start - 29 * 60_000}"
                               f"&endTime={end + 59_999}&limit={self.FX_WIN + 30}") or []:
                    try:
                        bn.append((int(row[0]), float(row[1])))
                    except (TypeError, ValueError, IndexError):
                        continue
            except Exception as _cg9:  # noqa: BLE001 [fallback]
                calcguard.swallowed("pricing:PxCache.prefetch_fx[_gj]", _cg9)
                ub, bn = [], []
                _fail()
                stop = True
            calls += 2
            if stop:
                break
            with self.lock:
                for m in grp:
                    v = _cross_at(m, ub, bn)
                    if v:
                        self.d["fx"][str(m)] = v
                        filled += 1
                        self._dirty += 1
            if pace:
                time.sleep(pace)
        self.maybe_save()
        return {"calls": calls, "filled": filled, "left": max(0, len(mins) - filled), "done": not stop and i >= len(mins) and j >= len(pre)}

    def prefetch_fx_patient(self, ms_list, max_calls: int, deadline: float = None, tries: int = 5, sleep=None) -> dict:
        sl = sleep or time.sleep
        tot = {"calls": 0, "filled": 0, "left": 0, "done": False}
        for k in range(max(1, int(tries))):
            if k:
                if deadline is not None and time.time() + self.FX_NEG_SEC + 1 >= deadline:
                    break
                sl(self.FX_NEG_SEC + 1)
            st = self.prefetch_fx(ms_list, max_calls=max(0, int(max_calls) - tot["calls"]), deadline=deadline)
            tot.update(calls=tot["calls"] + int(st.get("calls") or 0), filled=tot["filled"] + int(st.get("filled") or 0),
                       left=int(st.get("left") or 0), done=bool(st.get("done")))
            if tot["done"] or tot["calls"] >= int(max_calls) or (deadline is not None and time.time() >= deadline):
                break
        return tot

    def prefetch_candles(self, pairs, max_calls: int = 40, deadline: float = None, pace: float = 0.15) -> dict:
        by = {}
        now9 = time.time()
        with self.lock:
            for sym, t in pairs:
                s9 = str(sym or "").upper()
                if not s9 or not s9.isascii() or s9 in ("USDT", "USDC", "DAI") or now9 - self.d["neg_ts"].get(s9, 0) < self.NEG_TTL:
                    continue
                m = (int(t) // 60_000) * 60_000
                if f"{s9}:{m}" not in self.d["candle"] or f"{s9}:{m}" in self._flat:
                    by.setdefault(s9, set()).add(m)
        calls = filled = 0
        dead = self.__dict__.setdefault("_bulk_dead", {})
        for s9 in sorted(by):
            if now9 - dead.get(s9, 0) < self.NEG_TTL:
                continue
            mins = sorted(by[s9])
            i = 0
            while i < len(mins) and calls < max_calls and (deadline is None or time.time() < deadline):
                start = mins[i]
                end = start + (self.KLINE_WIN - 1) * 60_000
                grp = [m for m in mins[i:] if m <= end]
                i += len(grp)
                calls += 1
                try:
                    arr = _gj(f"https://api.binance.com/api/v3/klines?symbol={s9}USDT&interval=1m"
                              f"&startTime={start}&endTime={end + 59_999}&limit={self.KLINE_WIN}")
                except urllib.error.HTTPError as e:
                    if e.code == 400:
                        dead[s9] = time.time()
                        break
                    arr = None
                except Exception as _cg9:  # noqa: BLE001 [fallback]
                    calcguard.swallowed("pricing:PxCache.prefetch_candles", _cg9)
                    arr = None
                opens = {}
                for row in arr or []:
                    if _kl_zero(row, 5, 7):
                        continue
                    try:
                        opens[int(row[0])] = float(row[1])
                    except (TypeError, ValueError, IndexError):
                        continue
                with self.lock:
                    for m in grp:
                        px = opens.get(m)
                        if _fin(px):
                            self.d["candle"][f"{s9}:{m}"] = px
                            self._flat.discard(f"{s9}:{m}")
                            self.d.setdefault("cven", {})[f"{s9}:{m}"] = "binance"
                            filled += 1
                            self._dirty += 1
                if pace:
                    time.sleep(pace)
            if calls >= max_calls or (deadline is not None and time.time() >= deadline):
                break
        self.maybe_save()
        return {"calls": calls, "filled": filled}

    def candle_venue(self, sym: str, ts_ms: int):
        m = (int(ts_ms) // 60_000) * 60_000
        key = f"{str(sym or '').upper()}:{m}"
        with self.lock:
            v = (self.d.get("cven") or {}).get(key)
            if v:
                return v
            return "legacy" if (self._legacy and key in self.d["candle"] and _key_h(key) in self._legacy) else None

    def cg_usd_at(self, ts_ms: int, chain: str = None, ca: str = None, keyed: bool = False) -> float | None:
        try:
            import candles as _cd
        except Exception as _cg9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("pricing:PxCache.cg_usd_at", _cg9)
            return None
        plat = _cd.CG_PLATFORM.get(chain or "")
        if not plat or not ca:
            return None
        tk = ca.lower() if chain != "sol" else ca
        with self.lock:
            store = self.d.setdefault("cgday", {})
        n0 = len(store)
        pts = cg_points_day(f"ca:{chain}:{tk}", f"https://api.coingecko.com/api/v3/coins/{plat}/contract/{urllib.parse.quote(tk, safe='')}",
                            (int(ts_ms) // 1000) // 86400 * 86400, store, keyed=keyed)
        if len(store) != n0:
            with self.lock:
                self._dirty += 1
            self.maybe_save()
        return _cg_pts_at(pts, int(ts_ms)) if pts else None

    def token_usd_checked(self, sym: str, ts_ms: int, chain: str, ca: str, cex_px: float | None) -> float | None:
        ref = self.cg_usd_at(ts_ms, chain, ca, keyed=not cex_px)
        if not ref:
            return None
        if cex_px:
            r = cex_px / ref
            if IDENT_LO <= r <= IDENT_HI:
                return cex_px
            import logging
            logging.getLogger("tj").warning("원가 동명 거르기: %s(%s:%s…) 1분봉 %.6g 가 코인게코 컨트랙트 시세 %.6g 의 %.2f배 — 코인게코 값(근사)으로",
                                            sym, chain, str(ca)[:10], cex_px, ref, r)
        return ref

    def fx_at(self, ts_ms: int) -> float | None:
        nb = self._nb()
        m = (ts_ms // 60_000) * 60_000
        key = str(m)
        with self.lock:
            if key in self.d["fx"]:
                return self.d["fx"][key]
            neg = self.d["neg_ts"].get("_fx", 0)
        if time.time() - neg < 60:
            return None
        if nb is not None:
            nb.add(("fx", "", m))
            self._tl.took = True
            return None
        try:
            fx = _fx_candle_krw_per_usdt(m)
        except Exception as _cg9:  # noqa: BLE001 [fallback]
            calcguard.swallowed("pricing:PxCache.fx_at", _cg9)
            fx = None
        with self.lock:
            if fx:
                self.d["fx"][key] = fx
                if self.d["neg_ts"].get("_fx", 0) == neg:
                    self.d["neg_ts"].pop("_fx", None)
            else:
                self.d["neg_ts"]["_fx"] = int(time.time())
            self._dirty += 1
        self.maybe_save()
        return fx

    FX_WARM_SPAN = 200
    FX_WARM_MAX_CALLS = 40
    FX_WARM_GAP = 0.15
    FX_WARM_BUDGET = 30.0
    FX_NEG_SEC = 60

    def fx_warm(self, ts_ms_list, max_calls: int = None) -> int:
        from datetime import datetime, timezone
        mins = sorted({(int(t) // 60_000) * 60_000 for t in (ts_ms_list or ()) if int(t) > FX_USDT_FIRST_MS + 86_400_000})
        with self.lock:
            mins = [m for m in mins if str(m) not in self.d["fx"]]
            neg = self.d["neg_ts"].get("_fx", 0)
        if not mins or time.time() - neg < self.FX_NEG_SEC:
            return 0
        groups = []
        for m in mins:
            if groups and m - groups[-1][0] < (self.FX_WARM_SPAN - 1) * 60_000:
                groups[-1].append(m)
            else:
                groups.append([m])
        cap = self.FX_WARM_MAX_CALLS if max_calls is None else int(max_calls)
        t_end = time.time() + self.FX_WARM_BUDGET
        n, failed = 0, False
        for i, g in enumerate(groups[:max(0, cap)]):
            if time.time() >= t_end:
                break
            if i:
                time.sleep(self.FX_WARM_GAP)
            with self.lock:
                neg = self.d["neg_ts"].get("_fx", 0)
            if time.time() - float(neg or 0) < self.FX_NEG_SEC:
                break
            to_s = datetime.fromtimestamp(g[-1] / 1000 + 60, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            try:
                arr = _gj(f"https://api.upbit.com/v1/candles/minutes/1?market=KRW-USDT&to={to_s}&count={self.FX_WARM_SPAN}")
            except Exception as _cg9:   # noqa: BLE001 [fallback]
                calcguard.swallowed("pricing:PxCache.fx_warm", _cg9)
                arr = None
            if not isinstance(arr, list):
                with self.lock:
                    self.d["neg_ts"]["_fx"] = int(time.time())
                    self._dirty += 1
                failed = True
                break
            cs = []
            for c in arr:
                try:
                    ts = datetime.strptime(c["candle_date_time_utc"], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp() * 1000
                    op = float(c["opening_price"])
                except (KeyError, TypeError, ValueError):
                    continue
                if _fin(op):
                    cs.append((ts, op))
            cs.sort()
            put, j, best = {}, 0, None
            for m in g:
                while j < len(cs) and cs[j][0] <= m:
                    best = cs[j][1]
                    j += 1
                if best is not None:
                    put[str(m)] = best
            if put:
                with self.lock:
                    for k, v in put.items():
                        if k not in self.d["fx"]:
                            self.d["fx"][k] = v
                            n += 1
                    self._dirty += len(put)
        if n or failed:
            self.maybe_save()
        return n


class PxFetchQueue:

    def __init__(self, px: "PxCache", name: str = "pxq-worker"):
        self.px = px
        self.name = name
        self.q = set()
        self.lock = threading.Lock()
        self.ev = threading.Event()
        self.th = None
        self.stats = {"done": 0, "batches": 0, "last_s": 0.0}

    def add(self, items):
        if not items:
            return
        with self.lock:
            self.q |= set(items)
            if self.th is None:
                self.th = threading.Thread(target=self._loop, daemon=True, name=self.name)
                self.th.start()
        self.ev.set()

    def pending(self) -> int:
        with self.lock:
            return len(self.q)

    def drain(self) -> int:
        with self.lock:
            items = sorted(self.q, key=lambda x: (x[0], str(x[1] or ""), -int(x[2])))
            self.q.clear()
        t0 = time.time()
        for kind, sym, m in items:
            try:
                if kind == "c":
                    self.px.candle_usd(sym, m)
                elif kind == "fx":
                    self.px.fx_at(m)
            except Exception as _cg9:   # noqa: BLE001 [isolate]
                calcguard.swallowed("pricing:PxFetchQueue.drain", _cg9)
                pass
        if items:
            self.px.maybe_save()
            self.stats["done"] += len(items)
            self.stats["batches"] += 1
            self.stats["last_s"] = round(time.time() - t0, 2)
        return len(items)

    def _loop(self):
        while True:
            self.ev.wait()
            self.ev.clear()
            try:
                self.drain()
            except Exception as _cg9:   # noqa: BLE001 [boundary]
                calcguard.swallowed("pricing:PxFetchQueue._loop", _cg9)
                time.sleep(5)


class FxWarmQueue(PxFetchQueue):

    RETRIES = 2
    RETRY_SEC = 61.0

    def __init__(self, px: "PxCache", name: str = "fxwarm-worker"):
        super().__init__(px, name=name)
        self.busy = False

    def _missing(self, items):
        with self.px.lock:
            return [(k, s, m) for k, s, m in items
                    if not (self.px.d["fx"].get(str(m)) if k == "fx" else self.px._cget(f"{s}:{m}"))]

    def drain(self) -> int:
        with self.lock:
            items = sorted(self.q, key=lambda x: (x[0], str(x[1] or ""), int(x[2])))
            self.q.clear()
            self.busy = bool(items)
        if not items:
            return 0
        t0 = time.time()
        gap = float(getattr(self.px, "FX_WARM_GAP", 0.15) or 0)
        try:
            left = self._missing(items)
            for attempt in range(self.RETRIES + 1):
                if attempt:
                    time.sleep(self.RETRY_SEC)
                    left = self._missing(left)
                fx_ms = [m for k, _s, m in left if k == "fx"]
                for _ in range(64):
                    try:
                        if not fx_ms or self.px.fx_warm(fx_ms) <= 0:
                            break
                    except Exception as _cg9:   # noqa: BLE001 [fallback]
                        calcguard.swallowed("pricing:FxWarmQueue.drain[not]", _cg9)
                        break
                    fx_ms = [m for k, _s, m in self._missing([("fx", "", m9) for m9 in fx_ms])]
                for kind, sym, m in self._missing(left):
                    try:
                        if kind == "fx":
                            self.px.fx_at(m)
                        elif kind == "c":
                            self.px.candle_usd(sym, m)
                    except Exception as _cg9:   # noqa: BLE001 [isolate]
                        calcguard.swallowed("pricing:FxWarmQueue.drain[kind]", _cg9)
                        pass
                    if gap:
                        time.sleep(gap)
                left = self._missing(left)
                if not left:
                    break
            self.px.maybe_save()
            self.stats["done"] += len(items)
            self.stats["batches"] += 1
            self.stats["last_s"] = round(time.time() - t0, 2)
        finally:
            with self.lock:
                self.busy = False
        return len(items)

    def wait_idle(self, timeout: float) -> bool:
        t_end = time.time() + float(timeout)
        while True:
            with self.lock:
                if not self.q and not self.busy:
                    return True
            if time.time() >= t_end:
                return False
            time.sleep(0.02)


def upbit_krw_markets() -> set:
    return upbit_markets().get("KRW", set())


def upbit_markets() -> dict:
    arr = _gj("https://api.upbit.com/v1/market/all")
    out = {}
    for m in arr or []:
        mk = str((m or {}).get("market") or "") if isinstance(m, dict) else ""
        if "-" not in mk:
            continue
        q, b = mk.split("-", 1)
        out.setdefault(q, set()).add(b)
    return out


def upbit_tickers(markets: list) -> dict:
    out = {}
    markets = [m for m in dict.fromkeys(markets) if m]
    for i in range(0, len(markets), 50):
        mk = ",".join(markets[i:i + 50])
        try:
            arr = _gj(f"https://api.upbit.com/v1/ticker?markets={urllib.parse.quote(mk)}")
        except Exception as _cg9:  # noqa: BLE001 [isolate]
            calcguard.swallowed("pricing:upbit_tickers", _cg9)
            continue
        finally:
            time.sleep(0.12)
        for t in arr or []:
            try:
                px = float(t["trade_price"])
                vol = float(t.get("acc_trade_price_24h") or 0)
            except (KeyError, TypeError, ValueError):
                continue
            if _fin(px):
                out[str(t.get("market"))] = (px, vol if math.isfinite(vol) and vol > 0 else 0.0)
    return out


GLOBAL_USD_ORDER = ("binance", "bybit")
IDENT_LO, IDENT_HI = 0.5, 2.0


def pick_global_usd(syms, book, order=GLOBAL_USD_ORDER, ident=None, ref=None, notes=None, failed=None) -> dict:
    out = {}
    for s in syms:
        for ex in order:
            v = (book(ex) or {}).get(s)
            if not _fin(v or 0):
                continue
            ok, why = global_ident(s, ex, v, book, order, (ident, ref, failed))
            if ok is False:
                if notes is not None:
                    notes.setdefault(s, []).append(why)
                continue
            out[s] = (float(v), f"{ex} {s}USDT" + (f" · {why}" if why else ""))
            break
    return out


def global_ident(s: str, ex: str, v: float, book: Callable, order: tuple, hooks: tuple = (None, None, None)) -> tuple:
    ident, ref, failed = hooks
    ok, why = ident(s, ex) if ident else (None, "")
    if ok is None and ref:
        rf = ref(s)
        if rf and _fin(rf[0] or 0):
            ratio = v / rf[0]
            ok, why = (True, f"{rf[1]} 기준 {ratio:.2f}배") if IDENT_LO <= ratio <= IDENT_HI else (
                False, f"{ex} {s} 시세가 {rf[1]}의 {ratio:.2f}배 — 동명 다른 코인 의심")
    if ok is None:
        unknown_ex = None
        for ex2 in order:
            if ex2 == ex or (ident and ident(s, ex2)[0] is False):
                continue
            other_book = book(ex2)
            if failed and failed(ex2):
                unknown_ex = unknown_ex or ex2
                continue
            w = (other_book or {}).get(s)
            if _fin(w or 0) and not (IDENT_LO <= v / w <= IDENT_HI):
                ok, why = False, f"{ex}·{ex2} {s} 시세가 {v / w:.2f}배 달라 같은 코인인지 확인 불가"
                break
        if ok is None and unknown_ex:
            ok, why = False, f"{ex} {s} — 비교할 {unknown_ex} 시세 조회 실패(동일성 판정 못 함 · 이번엔 안 씀)"
    return ok, why


UPBIT_ALT_DIVERGE = 0.20


def upbit_alt_usd(syms: list, alt: dict, tickers: dict, btc_usd: float, global_px: dict) -> dict:
    out = {}
    for s in syms:
        cands = []
        if "BTC" in alt.get(s, ()) and btc_usd and f"BTC-{s}" in tickers:
            px, vol = tickers[f"BTC-{s}"]
            cands.append((vol * btc_usd, 1, px * btc_usd, "upbit BTC-" + s))
        if "USDT" in alt.get(s, ()) and f"USDT-{s}" in tickers:
            px, vol = tickers[f"USDT-{s}"]
            cands.append((vol, 0, px, "upbit USDT-" + s))
        if not cands:
            continue
        cands.sort(reverse=True)
        usd, why = cands[0][2], cands[0][3]
        g = global_px.get(s)
        if _fin(usd) and _fin(g or 0) and abs(usd - g) / max(usd, g) > UPBIT_ALT_DIVERGE:
            if g < usd:
                why += f" → 글로벌 {g:.6g} 로 상한(괴리 {usd / g - 1:+.0%})"
            usd = min(usd, g)
        if _fin(usd):
            out[s] = (usd, why)
    return out


def timed_out(e: BaseException) -> bool:
    if isinstance(e, urllib.error.HTTPError) or not isinstance(e, OSError):
        return False
    r = getattr(e, "reason", None) if isinstance(e, urllib.error.URLError) else None
    x = r if isinstance(r, BaseException) else e
    return isinstance(x, TimeoutError) or "timed out" in str(x).lower()


UPBIT_404_DEPTH = 7
UPBIT_404_CALLS = 16


def _upbit_404_parts(grp: list, dep: int, seen) -> list:
    if len(grp) < 2 or dep >= UPBIT_404_DEPTH:
        return []
    if dep == 0 and seen is not None:
        a, b = [s for s in grp if s in seen], [s for s in grp if s not in seen]
        if a and b:
            return [(a, 1), (b, 1)]
    h = len(grp) // 2
    return [(grp[:h], dep + 1), (grp[h:], dep + 1)]


def upbit_spot_krw(syms: list, dead: set | None = None, answered: set | None = None, seen: set | None = None) -> dict:
    out = {}
    syms = [s for s in syms if s]
    todo = [(syms[i:i + 50], 0) for i in range(0, len(syms), 50)]
    spent = 0
    while todo:
        if dead is not None and "upbit" in dead:
            break
        grp, dep = todo.pop(0)
        if dep:
            if spent >= UPBIT_404_CALLS:
                continue
            spent += 1
            time.sleep(1.0 if spent == 1 else 0.12)
        elif spent:
            time.sleep(0.12)
        mk = ",".join(f"KRW-{s}" for s in grp)
        try:
            arr = _gj(f"https://api.upbit.com/v1/ticker?markets={urllib.parse.quote(mk)}")
        except Exception as _cg9:  # noqa: BLE001 [isolate]
            calcguard.swallowed("pricing:upbit_spot_krw", _cg9)
            if dead is not None and timed_out(_cg9):
                dead.add("upbit")
            if isinstance(_cg9, urllib.error.HTTPError) and _cg9.code == 404:
                if answered is not None:
                    answered.update(grp)
                todo[0:0] = _upbit_404_parts(grp, dep, seen)
            elif dep:
                todo = [t for t in todo if not t[1]]
            continue
        if answered is not None:
            answered.update(grp)
        for t in arr or []:
            try:
                px = float(t["trade_price"])
                if _fin(px):
                    out[t["market"][4:]] = px
            except (KeyError, TypeError, ValueError):
                pass
        time.sleep(0.12)
    return out


def ex_spot_usd(ex: str, usdt_krw: float = 0) -> dict:
    out = {}

    def _put(sym, px, vol=None, qv=None):
        try:
            px = float(px or 0)
        except (TypeError, ValueError):
            return
        if _vol_zero(vol):
            EX_DEAD[ex] = EX_DEAD.get(ex, 0) + 1
            dead9.add(str(sym).upper())
            return
        if _fin(px) and px > 0:
            out[str(sym).upper()] = px
            qvols[str(sym).upper()] = num_parse.to_float(qv)

    EX_DEAD[ex] = 0
    dead9, qvols = set(), {}
    if ex == "binance":
        return binance_spot_usdt()
    if ex == "hyperliquid":
        import hl_spot
        return hl_spot.fetch_book()
    try:
        got = _ex_spot_usd_body(ex, usdt_krw, out, _put)
        EX_QVOL[ex] = (time.time(), qvols)
        return got
    finally:
        EX_DEAD_SYMS[ex] = frozenset(dead9)


def _bulk_rows(ex, d):
    ok9 = rows9 = None
    if ex == "bybit":
        ok9 = isinstance(d, dict) and d.get("retCode") in (0, "0")
        rows9 = ((d.get("result") or {}).get("list") if ok9 and isinstance(d.get("result"), dict) else None)
    elif ex == "gate":
        ok9, rows9 = isinstance(d, list), d
    elif ex == "kucoin":
        ok9 = isinstance(d, dict) and str(d.get("code")) == "200000"
        rows9 = ((d.get("data") or {}).get("ticker") if ok9 and isinstance(d.get("data"), dict) else None)
    elif ex == "okx":
        ok9 = isinstance(d, dict) and str(d.get("code")) == "0"
        rows9 = d.get("data") if ok9 else None
    elif ex == "coinbase":
        ok9 = isinstance(d, dict) and isinstance(d.get("products"), list)
        rows9 = d.get("products") if ok9 else None
    elif ex == "bithumb":
        ok9 = isinstance(d, dict) and str(d.get("status")) == "0000"
        rows9 = d.get("data") if ok9 else None
        if isinstance(rows9, dict) and rows9:
            return rows9
        raise BulkError(ex, d)
    if not ok9 or not isinstance(rows9, list) or not rows9:
        raise BulkError(ex, d)
    return rows9


def _coinbase_books() -> dict:
    base_url = "https://api.coinbase.com/api/v3/brokerage/market/products?product_type=SPOT"
    rows, url, seen_c = [], base_url, set()
    for _ in range(50):
        d = _gj(url, timeout=20)
        rows += _bulk_rows("coinbase", d)
        pg = d.get("pagination") if isinstance(d.get("pagination"), dict) else {}
        if pg.get("has_next") is not True:
            break
        cur = str(pg.get("next_cursor") or "")
        if not cur or cur in seen_c:
            raise BulkError("coinbase", {"error": "상품 목록 다음 쪽 커서 이상"})
        seen_c.add(cur)
        url = base_url + "&cursor=" + urllib.parse.quote(cur, safe="")
    else:
        raise BulkError("coinbase", {"error": "상품 목록 쪽 상한 초과"})
    best = {}
    for t in rows:
        if (not isinstance(t, dict) or t.get("trading_disabled") is True or t.get("is_disabled") is True
                or str(t.get("status") or "online").lower() != "online"):
            continue
        b, q = str(t.get("base_currency_id") or "").upper(), str(t.get("quote_currency_id") or "").upper()
        if b and q in ("USD", "USDC") and (q == "USD" or b not in best):
            best[b] = t
    return best


def _ex_spot_usd_body(ex, usdt_krw, out, _put):
    if ex == "bybit":
        d = _gj("https://api.bybit.com/v5/market/tickers?category=spot", timeout=15)
        for t in _bulk_rows(ex, d):
            if not isinstance(t, dict):
                continue
            s = str(t.get("symbol") or "")
            if s.endswith("USDT"):
                v9 = t.get("volume24h")
                if v9 in (None, ""):
                    v9 = t.get("turnover24h")
                _put(s[:-4], t.get("lastPrice"), v9, t.get("turnover24h"))
    elif ex == "gate":
        arr = _gj("https://api.gateio.ws/api/v4/spot/tickers", timeout=20)
        for t in _bulk_rows(ex, arr):
            if not isinstance(t, dict):
                continue
            s = str(t.get("currency_pair") or "")
            if s.endswith("_USDT"):
                _put(s[:-5], t.get("last"), t.get("quote_volume"), t.get("quote_volume"))
    elif ex == "kucoin":
        d = _gj("https://api.kucoin.com/api/v1/market/allTickers", timeout=20)
        for t in _bulk_rows(ex, d):
            if not isinstance(t, dict):
                continue
            s = str(t.get("symbol") or "")
            if s.endswith("-USDT"):
                _put(s[:-5], t.get("last"), t.get("vol"), t.get("volValue"))
    elif ex == "okx":
        d = _gj("https://www.okx.com/api/v5/market/tickers?instType=SPOT", timeout=20)
        for t in _bulk_rows(ex, d):
            if not isinstance(t, dict):
                continue
            s = str(t.get("instId") or "")
            if s.endswith("-USDT"):
                _put(s[:-5], t.get("last"), t.get("vol24h"), t.get("volCcy24h"))
    elif ex == "coinbase":
        for b, t in _coinbase_books().items():
            _put(b, t.get("price"), t.get("volume_24h"), t.get("approximate_quote_24h_volume"))
    elif ex == "bithumb":
        if not usdt_krw:
            return out
        d = _gj("https://api.bithumb.com/public/ticker/ALL_KRW", timeout=20)
        for s, t in _bulk_rows(ex, d).items():
            if isinstance(t, dict):
                try:
                    px = float(t.get("closing_price") or 0)
                except (TypeError, ValueError):
                    continue
                if _fin(px) and px > 0:
                    _put(s, px / usdt_krw, t.get("units_traded_24H"))
    return out


EX_DEAD = {}
EX_DEAD_SYMS = {}
EX_QVOL = {}


def _vol_zero(v) -> bool:
    if v is None or v == "":
        return False
    f = num_parse.to_float(v)
    return f is not None and f == 0.0


BN_DEAD_EVERY = 600
BN_DEAD_AGE = 86400
_BN_DEAD = {"at": 0.0, "syms": frozenset()}


def binance_dead_syms(now: float = None) -> frozenset:
    now = time.time() if now is None else now
    if now - _BN_DEAD["at"] < BN_DEAD_EVERY:
        return _BN_DEAD["syms"]
    _BN_DEAD["at"] = now
    try:
        arr = _gj("https://api.binance.com/api/v3/ticker/24hr?type=MINI", timeout=20)
    except Exception as _cg9:   # noqa: BLE001 [fallback]
        calcguard.swallowed("pricing:binance_dead_syms", _cg9)
        return _BN_DEAD["syms"]
    if not isinstance(arr, list):
        return _BN_DEAD["syms"]
    dead, qvols = set(), {}
    for t in arr:
        if not isinstance(t, dict):
            continue
        s = str(t.get("symbol") or "")
        if not s.endswith("USDT"):
            continue
        qvols[s[:-4]] = num_parse.to_float(t.get("quoteVolume"))
        cnt, ct = t.get("count"), t.get("closeTime")
        stale = False
        try:
            ct = float(ct) / 1000.0 if ct not in (None, "") else None
            stale = bool(ct and ct > 0 and now - ct > BN_DEAD_AGE)
        except (TypeError, ValueError):
            stale = False
        if _vol_zero(cnt) or stale:
            dead.add(s[:-4])
    _BN_DEAD["syms"] = frozenset(dead)
    EX_QVOL["binance"] = (now, qvols)
    return _BN_DEAD["syms"]


def binance_spot_usdt() -> dict:
    arr = _gj("https://api.binance.com/api/v3/ticker/price", timeout=15)
    if not isinstance(arr, list) or not arr:
        raise BulkError("binance", arr)
    dead = binance_dead_syms()
    out = {}
    n_dead = 0
    dead9 = set()
    for t in arr or []:
        s = t.get("symbol", "")
        if s.endswith("USDT"):
            if s[:-4] in dead:
                n_dead += 1
                dead9.add(s[:-4])
                continue
            try:
                px = float(t["price"])
                if _fin(px):
                    out[s[:-4]] = px
            except (TypeError, ValueError):
                pass
    EX_DEAD["binance"] = n_dead
    EX_DEAD_SYMS["binance"] = frozenset(dead9)
    return out


def usdt_krw_ask() -> float | None:
    d = _gj("https://api.upbit.com/v1/orderbook?markets=KRW-USDT")
    try:
        units = d[0]["orderbook_units"]
        px = float(units[0]["ask_price"])
        return px if _fin(px) else None
    except (KeyError, IndexError, TypeError, ValueError):
        return None


GT_NETWORK = {"eth": "eth", "base": "base", "bsc": "bsc", "arbitrum": "arbitrum",
              "optimism": "optimism", "polygon": "polygon_pos", "scroll": "scroll",
              "zksync": "zksync", "gnosis": "xdai", "sol": "solana",
              "monad": "monad", "megaeth": "megaeth", "plasma": "plasma", "xlayer": "x-layer", "kaia": "kaia",
              "fraxtal": "fraxtal", "bob": "bob-network", "somnia": "somnia", "avalanche": "avax",
              "story": "story",
              "abstract": "abstract",
              "hyperevm": "hyperevm"}


_GT_ERR = None


def gt_take_error():
    global _GT_ERR
    e, _GT_ERR = _GT_ERR, None
    return e


_GT_UNRESOLVED = set()


def gt_take_unresolved() -> set:
    global _GT_UNRESOLVED
    u, _GT_UNRESOLVED = _GT_UNRESOLVED, set()
    return u


def gt_token_prices(chain: str, cas: list) -> dict:
    return gt_token_prices_ex(chain, cas)[0]


def _gt_ok(d):
    if not isinstance(d, dict) or not isinstance(d.get("data"), dict):
        return False
    a = d["data"].get("attributes")
    if not isinstance(a, dict):
        return False
    if isinstance(a.get("total_reserve_in_usd"), dict) or not a.get("token_prices"):
        return True
    return "family"


GT_FREE_HOST = "api.geckoterminal.com"
GT_FREE_WAIT_S = 12.0
GT_FREE_PAUSE_S = 60.0


class GtGateWait(urllib.error.HTTPError):
    pass


def _gt_free(url, timeout=15.0):
    g = None
    try:
        import bf_engine
        import candles  # noqa: F401
        g = bf_engine.gate(GT_FREE_HOST)
    except ImportError:
        g = None
    if g is not None:
        try:
            g.acquire("bg", deadline=time.time() + GT_FREE_WAIT_S)
        except bf_engine.NetError as e:
            ra9 = max(GT_FREE_PAUSE_S, bf_engine.gate_wait(GT_FREE_HOST))
            raise GtGateWait(url.split("?", 1)[0], 429, "게이트 대기 — " + logs.safe_err(e)[:80],  # noqa: B904
                             {"Retry-After": str(int(min(300.0, ra9)))}, None)
    try:
        return _gj(url, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code == 429 and g is not None:
            try:
                ra = float((e.headers or {}).get("Retry-After") or 0)
            except (TypeError, ValueError, AttributeError):
                ra = 0.0
            with g.lock:
                g.pause_until = max(g.pause_until, time.time() + min(300.0, max(GT_FREE_PAUSE_S, ra)))
        raise


def gt_token_prices_ex(chain: str, cas: list, keyed: bool = True):
    global _GT_ERR  # noqa: PLW0603
    net = GT_NETWORK.get(chain)
    if not net or not cas:
        return {}, {}
    out = {}
    res_out = {}
    for i in range(0, len(cas), 30):
        batch = cas[i:i + 30]
        url = (f"https://api.geckoterminal.com/api/v2/simple/networks/{net}"
               f"/token_price/{','.join(batch)}?include_total_reserve_in_usd=true")
        keyed9 = False
        try:
            kind9, kv9 = _cg_keyed(url, "live", keyed, _gt_ok)
            if kind9 == "ok":
                d = kv9
                keyed9 = True
            elif kind9 == "err":
                raise urllib.error.HTTPError(url.split("?", 1)[0], 404, "Not Found", None, None)
            else:
                d = _gt_free(url, timeout=15)
        except urllib.error.HTTPError as e:
            ra = None
            try:
                ra = (e.headers or {}).get("Retry-After")
            except Exception as _cg9:   # noqa: BLE001 [isolate]
                calcguard.swallowed("pricing:gt_token_prices_ex[ra]", _cg9)
                pass
            _GT_ERR = ("rate" if e.code == 429 else "http", "gate" if isinstance(e, GtGateWait) else e.code, str(ra or ""))
            if e.code == 429:
                break
            continue
        except Exception as e:   # noqa: BLE001 [isolate]
            calcguard.swallowed("pricing:gt_token_prices_ex[kind9]", e)
            _GT_ERR = ("net", None, f"{type(e).__name__}: {logs.safe_err(e)[:80]}")
            continue
        finally:
            time.sleep(2.1)
        if not isinstance(d, dict):
            _GT_ERR = ("net", None, "응답 형식 이상")
            continue
        b_px, b_res = _gt_parse(d, batch)
        if keyed9:
            miss9 = [c for c in batch if c in b_px and b_px[c] > 0 and c not in b_res]
            for c in miss9:
                b_px.pop(c, None)
            if miss9:
                u2 = (f"https://api.geckoterminal.com/api/v2/simple/networks/{net}"
                      f"/token_price/{','.join(miss9)}?include_total_reserve_in_usd=true")
                try:
                    d2 = _gt_free(u2, timeout=15)
                    if isinstance(d2, dict):
                        p2, r2 = _gt_parse(d2, miss9)
                        b_px.update(p2)
                        b_res.update(r2)
                    else:
                        _GT_UNRESOLVED.update(miss9)
                except urllib.error.HTTPError as e:
                    _GT_ERR = ("rate" if e.code == 429 else "http", "gate" if isinstance(e, GtGateWait) else e.code, "")
                    if e.code != 404:
                        _GT_UNRESOLVED.update(miss9)
                except Exception as e:   # noqa: BLE001 [fallback]
                    calcguard.swallowed("pricing:gt_token_prices_ex[d2]", e)
                    _GT_ERR = ("net", None, f"{type(e).__name__}: {logs.safe_err(e)[:80]}")
                    _GT_UNRESOLVED.update(miss9)
                finally:
                    time.sleep(2.1)
        out.update(b_px)
        res_out.update(b_res)
    return out, res_out


def _gt_parse(d, batch):
    out, res_out = {}, {}
    attrs = ((d.get("data") or {}).get("attributes") or {})
    prices = attrs.get("token_prices") or {}
    reserves = attrs.get("total_reserve_in_usd") or {}
    exact = set(batch)
    low_map = {}
    for c in batch:
        lc = c.lower()
        low_map[lc] = c if low_map.get(lc, c) == c else None
    for k, v in prices.items():
        try:
            px = float(v)
        except (TypeError, ValueError):
            continue
        if _fin(px) or (isinstance(px, float) and px == 0.0):
            orig = k if k in exact else low_map.get(k.lower())
            if orig is None:
                continue
            out[orig] = px
    if isinstance(reserves, dict):
        for k, v in reserves.items():
            try:
                rv = float(v)
            except (TypeError, ValueError):
                continue
            if not (math.isfinite(rv) and rv >= 0):
                continue
            orig = k if k in exact else low_map.get(k.lower())
            if orig is not None:
                res_out[orig] = rv
    return out, res_out


_DS_ERR = None
_DS_META = {}


def ds_take_meta() -> dict:
    global _DS_META
    m, _DS_META = _DS_META, {}
    return m


def ds_take_error():
    global _DS_ERR
    e, _DS_ERR = _DS_ERR, None
    return e


def ds_token_prices(chain: str, cas: list):
    global _DS_ERR, _DS_META  # noqa: PLW0603
    _DS_META = {}
    net = token_tables.DS_CHAIN.get(chain)
    if not net or not cas:
        return {}, {}
    batch = list(cas)[:30]
    url = f"https://api.dexscreener.com/tokens/v1/{net}/{','.join(batch)}"
    try:
        d = _gj(url, timeout=15)
    except urllib.error.HTTPError as e:
        _DS_ERR = ("rate" if e.code == 429 else "http", e.code, "")
        return {}, {}
    except Exception as e:   # noqa: BLE001 [fallback]
        calcguard.swallowed("pricing:ds_token_prices", e)
        _DS_ERR = ("net", None, f"{type(e).__name__}: {logs.safe_err(e)[:80]}")
        return {}, {}
    finally:
        time.sleep(0.5)
    if isinstance(d, dict):
        d = d.get("pairs") or []
    if not isinstance(d, list):
        _DS_ERR = ("net", None, "응답 형식 이상")
        return {}, {}
    evm = chain != "sol"
    want = {(c.lower() if evm else c): c for c in batch}
    best, res = {}, {}
    meta = {}
    for pr in d:
        if not isinstance(pr, dict) or (pr.get("chainId") and pr.get("chainId") != net):
            continue
        lq0 = (pr.get("liquidity") or {}).get("usd") if isinstance(pr.get("liquidity"), dict) else None
        liq = num_parse.to_float(lq0, allow_bool=False) if lq0 not in (None, "") else None
        if liq is not None and liq < 0:
            liq = None
        for side in ("baseToken", "quoteToken"):
            tk = pr.get(side)
            if not isinstance(tk, dict):
                continue
            a = str(tk.get("address") or "")
            orig = want.get(a.lower() if evm else a)
            if orig is None:
                continue
            if orig not in meta and (tk.get("symbol") or tk.get("name")):
                meta[orig] = (str(tk.get("symbol") or "").strip()[:40], str(tk.get("name") or "").strip()[:80])
            if liq is not None:
                res[orig] = res.get(orig, 0.0) + liq
            if side == "baseToken":
                px = num_parse.to_float(pr.get("priceUsd") or 0, 0.0, allow_bool=False)
                if liq is not None and _fin(px) and (orig not in best or liq > best[orig][0]):
                    best[orig] = (liq, px)
    _DS_META = meta
    best = {k: v for k, v in best.items() if math.isfinite(res[k])}
    return {k: v[1] for k, v in best.items()}, {k: v for k, v in res.items() if k in best}


OKX_HOST = "https://www.okx.com"
OKX_PRICE_PATH = "/api/v6/dex/market/price"
OKX_CHAIN_INDEX = {"eth": "1", "base": "8453", "sol": "501", "bsc": "56",
                   "arbitrum": "42161", "optimism": "10", "polygon": "137",
                   "scroll": "534352", "zksync": "324", "gnosis": "100"}
def _okx_anchor_for(chain: str):
    if chain == "sol":
        for mint, sym in token_tables.STABLE_MINTS.items():
            if sym == "USDC":
                return mint
        return None
    cas = token_tables.STABLE_CAS.get(chain) or {}
    for sym_want in ("USDC", "USDT"):
        for ca, sym in cas.items():
            if sym == sym_want:
                return ca
    return None


def okx_headers(creds: dict, method: str, path: str, body: str):
    key, sec, pw = creds.get("key"), creds.get("secret"), creds.get("passphrase")
    if not (key and sec and pw):
        return None
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    sign = ex_sign.okx_sign(sec, ts, method, path, body)
    return {"OK-ACCESS-KEY": key, "OK-ACCESS-SIGN": sign, "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": pw, "Content-Type": "application/json",
            "User-Agent": _UA["User-Agent"], "Accept": "application/json"}


OKX_OFF_SEC = 6 * 3600
_OKX_OFF = {}


def _okx_fp(creds: dict) -> str:
    import hashlib
    return hashlib.sha256("\x00".join(str(creds.get(k) or "") for k in ("key", "secret", "passphrase")).encode()).hexdigest()[:16]


def _okx_skip(key_fp: str) -> bool:
    o = dict(_OKX_OFF)
    return bool(o) and o.get("fp") == key_fp and time.time() < o["until"]


def _okx_off_note(e, key_fp: str) -> bool:
    if not (isinstance(e, urllib.error.HTTPError) and e.code in (401, 403)):
        return False
    t_off = time.time()
    _OKX_OFF.clear()
    _OKX_OFF.update(until=t_off + OKX_OFF_SEC, at=t_off, why=f"HTTP {e.code}", fp=key_fp)
    return True


def okx_off_state(now: float = None) -> dict:
    t = time.time() if now is None else now
    o = dict(_OKX_OFF)
    return {"until": int(o["until"]), "at": int(o["at"]), "why": o["why"]} if o and o["until"] > t else {}


def okx_off_part() -> dict:
    st = okx_off_state()
    return {"okx_off": st} if st else {}


def okx_dex_prices(creds: dict, pairs: list) -> dict:
    items = []
    back = {}
    back_low = {}
    chains_used = set()
    for ch, ca in pairs:
        idx = OKX_CHAIN_INDEX.get(ch)
        if not idx or not _okx_anchor_for(ch):
            continue
        items.append({"chainIndex": idx, "tokenContractAddress": ca})
        back[(idx, ca)] = (ch, ca)
        lk = (idx, ca.lower())
        back_low[lk] = (ch, ca) if back_low.get(lk, (ch, ca)) == (ch, ca) else None
        chains_used.add(ch)
    if not items:
        return {}
    key_fp = _okx_fp(creds)
    if _okx_skip(key_fp):
        return {}
    out = {}
    for i in range(0, len(items), 90):
        batch = list(items[i:i + 90])
        anchors_req = []
        anchor_by_chain = {}
        for ch in chains_used:
            a = _okx_anchor_for(ch)
            idx = OKX_CHAIN_INDEX[ch]
            anchors_req.append({"chainIndex": idx, "tokenContractAddress": a})
            anchor_by_chain[(idx, a.lower())] = False
        body = json.dumps(batch + anchors_req)
        hdrs = okx_headers(creds, "POST", OKX_PRICE_PATH, body)
        if hdrs is None:
            return {}
        req = net_http.request(OKX_HOST + OKX_PRICE_PATH, data=body.encode(),
                               headers=hdrs)
        try:
            try:
                with net_http.auth_urlopen(req, timeout=12) as r:
                    d = json.loads(net_http.read_capped(r).decode())
            except Exception as _cg9:  # noqa: BLE001 [isolate]
                calcguard.swallowed("pricing:okx_dex_prices", _cg9)
                if _okx_off_note(_cg9, key_fp):
                    return out
                continue
            _OKX_OFF.clear()
            if str(d.get("code")) != "0":
                continue
            rows = d.get("data") or []
            got = {}
            anchor_seen = dict(anchor_by_chain)
            anchor_ok = True
            for row in rows:
                try:
                    px = float(row.get("price"))
                    idx9 = str(row.get("chainIndex"))
                    ca9 = str(row.get("tokenContractAddress"))
                except (TypeError, ValueError):
                    continue
                k = (idx9, ca9.lower())
                if k in anchor_seen:
                    anchor_seen[k] = True
                    if not (0.95 <= px <= 1.05):
                        anchor_ok = False
                    continue
                pair = back.get((idx9, ca9)) or back_low.get(k)
                if _fin(px) and pair:
                    got[pair] = px
            if anchor_ok and all(anchor_seen.values()):
                out.update(got)
        finally:
            time.sleep(0.3)
    return out


def fx_basis_krw_per_usd() -> float | None:
    try:
        d = _gj("https://open.er-api.com/v6/latest/USD", timeout=15)
        v = float((d.get("rates") or {}).get("KRW") or 0)
        return v if _fin(v) else None
    except Exception as _cg9:  # noqa: BLE001 [fallback]
        calcguard.swallowed("pricing:fx_basis_krw_per_usd", _cg9)
        return None
