"""Price sources and valuation."""
from __future__ import annotations

import json
import math
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import common

_UA = {"Accept": "application/json", "User-Agent": "tj-bot/0.1 (personal trade journal)"}

_USDE_OFT = "0x5d3a1ff2b6bab83b63cd9ad0787074081a52ef34"
STABLE_CAS = {
    "eth": {
        "0xdac17f958d2ee523a2206206994597c13d831ec7": "USDT",
        "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC",
        "0x6b175474e89094c44da98b954eedeac495271d0f": "DAI",
        "0x4c9edd5852cd905f086c759e8383e09bff1e68b3": "USDE",
        "0xcccc62962d17b8914c62d74ffb843d73b2a3cccc": "CUSD",
        "0x8d0d000ee44948fc98c9b98a4fa4921476f08b0d": "USD1",
        "0xe556aba6fe6036275ec1f87eda296be72c811bce": "NUSD",
    },
    "base": {
        "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": "USDC",
        "0xfde4c96c8593536e31f229ea8f37b2ada2699bb2": "USDT",
        "0x50c5725949a6f0c72e6c4a641f24049a917db0cb": "DAI",
    },
    "arbitrum": {
        "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9": "USDT",
        "0xaf88d065e77c8cc2239327c5edb3a432268e5831": "USDC",
        "0xff970a61a04b1ca14834a43f5de4533ebddb5cc8": "USDC",
        "0xda10009cbd5d07dd0cecc66161fc93d7c9000da1": "DAI",
    },
    "optimism": {
        "0x94b008aa00579c1307b0ef2c499ad98a8ce58e58": "USDT",
        "0x0b2c639c533813f4aa9d7837caf62653d097ff85": "USDC",
        "0x7f5c764cbc14f9669b88837ca1490cca17c31607": "USDC",
        "0xda10009cbd5d07dd0cecc66161fc93d7c9000da1": "DAI",
    },
    "polygon": {
        "0xc2132d05d31c914a87c6611c10748aeb04b58e8f": "USDT",
        "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359": "USDC",
        "0x2791bca1f2de4661ed88a30c99a7a9449aa84174": "USDC",
        "0x8f3cf7ad23cd3cadbd9735aff958023239c6a063": "DAI",
    },
    "scroll": {
        "0xf55bec9cafdbe8730f096aa55dad6d22d44099df": "USDT",
        "0x06efdbff2a14a7c8e15944d1f4a48f9f95f663a4": "USDC",
    },
    "zksync": {
        "0x493257fd37edb34451f62edf8d2a0c418852ba4c": "USDT",
        "0x1d17cbcf0d6d143135ae902365d2e5e2a16538d4": "USDC",
        "0x3355df6d4c9c3035724fd0e3914de96a5a83aaf4": "USDC",
    },
    "gnosis": {
        "0x4ecaba5870353805a9f068101a40e0f32ed605c6": "USDT",
        "0xddafbb505ad214d7b80b1f830fccc89b60fb7a83": "USDC",
    },
    "bsc": {
        "0x55d398326f99059ff775485246999027b3197955": "USDT",
        "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d": "USDC",
        "0x1af3f329e8be154074d8769d1ffa4ee058b1dbc3": "DAI",
        "0xe9e7cea3dedca5984780bafc599bd69add087d56": "BUSD",
        "0x8d0d000ee44948fc98c9b98a4fa4921476f08b0d": "USD1",
    },
    "robinhood": {
        "0x5fc5360d0400a0fd4f2af552add042d716f1d168": "USDG",
    },
}
for _ch in ("base", "arbitrum", "optimism", "scroll", "bsc", "robinhood"):
    STABLE_CAS[_ch][_USDE_OFT] = "USDE"
for _ch, _m in {
    "monad": {"0x754704bc059f8c67012fed69bc8a327a5aafb603": "USDC", "0xe7cd86e13ac4309349f30b3435a9d337750fc82d": "USDT"},
    "plasma": {"0xb8ce59fc3717ada4c02eadf9682a9e934f625ebb": "USDT"},
    "megaeth": {"0xb8ce59fc3717ada4c02eadf9682a9e934f625ebb": "USDT", "0xfafddbb3fc7688494971a79cc65dca3ef82079e7": "USDM"},
    "xlayer": {"0x779ded0c9e1022225f8e0630b35a9b54be713736": "USDT", "0x74b7f16337b8972027f6196a17a631ac6de26d22": "USDC"},
    "kaia": {"0xd077a400968890eacc75cdc901f0356c943e4fdb": "USDT"},
    "bob": {"0xe75d0fb2c24a55ca1e3f96781a2bcc7bdba058f0": "USDC", "0x05d032ac25d322df992303dca074ee7392c117b9": "USDT"},
    "avalanche": {"0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e": "USDC", "0x9702230a8ea53601f5cd2dc00fdbc13d4df4a8c7": "USDT"},
    "story": {"0xf1815bd50389c46847f0bda824ec8da914045d14": "USDC"},
    "abstract": {"0x84a71ccd554cc1b02749b35d22f684cc8ec987e1": "USDC", "0x0709f39376deee2a2dfc94a58edeb2eb9df012bd": "USDT"},
}.items():
    STABLE_CAS.setdefault(_ch, {}).update(_m)
STABLE_SYMS = {"USDT", "USDC", "DAI"}
JPY_STABLE_CAS = {
    "eth": {"0xe7c3d8c9a439fede00d2600032d5db0be71c3c29": "JPYC"},
    "polygon": {"0xe7c3d8c9a439fede00d2600032d5db0be71c3c29": "JPYC"},
}
DOLLAR_NATIVES = {"XDAI", "USDC", "USDT"}
STABLE_MINTS = {
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "2u1tszSeqZ3qBWF3uNGPFc8TzMk2tdiwknnRMWGWjGWH": "USDG",
}

MAJOR_CANDLE_SYMS = {"ETH", "BTC", "SOL", "POL", "BNB", "AVAX"}


def _gj(url: str, timeout: float = 10.0):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


class BulkError(RuntimeError):

    def __init__(self, ex, body):
        super().__init__(f"{ex} 벌크 시세 오류 응답: {str(body)[:120]}")


def _fin(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def _c_binance(sym, ms):
    arr = _gj(f"https://api.binance.com/api/v3/klines?symbol={sym}USDT&interval=1m"
              f"&startTime={ms}&endTime={ms + 59_999}&limit=1")
    if arr and _fin(float(arr[0][1])):
        return float(arr[0][1])
    return None


def _c_bybit(sym, ms):
    d = _gj(f"https://api.bybit.com/v5/market/kline?category=spot&symbol={sym}USDT"
            f"&interval=1&start={ms}&end={ms + 59_999}&limit=1")
    rows = ((d.get("result") or {}).get("list")) or []
    if rows and _fin(float(rows[0][1])):
        return float(rows[0][1])
    return None


def _c_gate(sym, ms):
    arr = _gj(f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={sym}_USDT"
              f"&interval=1m&from={ms // 1000}&to={ms // 1000 + 59}")
    if arr and len(arr[0]) >= 6 and _fin(float(arr[0][5])):
        return float(arr[0][5])
    return None


def _c_kucoin(sym, ms):
    d = _gj(f"https://api.kucoin.com/api/v1/market/candles?type=1min&symbol={sym}-USDT"
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
    except Exception:
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
    except Exception:
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
    except Exception as e:
        if getattr(e, "code", None) == 404 and getattr(e, "kind", "") == "http4xx":
            pts = []
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


def _upbit_krw_minute(sym: str, ms: int) -> float | None:
    from datetime import datetime, timezone
    to_s = datetime.fromtimestamp(ms / 1000 + 60, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    arr = _gj(f"https://api.upbit.com/v1/candles/minutes/1?market=KRW-{sym}&to={to_s}&count=30")
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
            v = self.d["candle"].get(f"{sym_u}:{m}")
            neg = self.d["neg_ts"].get(sym_u, 0)
        if v:
            return v
        if time.time() - neg < self.NEG_TTL or sym_u in ("USDT", "USDC", "DAI"):
            return self.candle_usd(sym, ts_ms)
        with self.lock:
            for i in range(1, max(0, int(back_min)) + 1):
                v = self.d["candle"].get(f"{sym_u}:{m - i * 60_000}")
                if v:
                    break
        if v:
            nb.add(("c", sym_u, m))
            self._tl.took = True
            return v
        return self.candle_usd(sym, ts_ms)

    def _save(self):
        s9 = json.dumps(self.d, separators=(",", ":"))
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(s9)
        os.replace(tmp, self.path)
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
            if key in self.d["candle"]:
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
        for _name, fn in CANDLE_ORDER:
            try:
                px = fn(sym, m, cache=self) if fn is _c_coingecko else fn(sym, m)
            except Exception:
                px = None
            if px:
                ven9 = _name
                break
        with self.lock:
            if px:
                self.d["candle"][key] = px
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
            except Exception:
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
            except Exception:
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
        from datetime import datetime, timezone
        i = 0
        while i < len(mins) and calls < max_calls and (deadline is None or time.time() < deadline):
            end = mins[i] + (self.FX_WIN - 1) * 60_000
            grp = [m for m in mins[i:] if m <= end]
            if grp[-1] < FX_USDT_FIRST_MS:
                i += len(grp)
                continue
            to_s = datetime.fromtimestamp(end / 1000 + 60, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            try:
                arr = _gj(f"https://api.upbit.com/v1/candles/minutes/1?market=KRW-USDT&to={to_s}&count={self.FX_WIN}")
            except Exception:
                arr = None
            calls += 1
            i += len(grp)
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
        while j < len(pre) and calls < max_calls and (deadline is None or time.time() < deadline):
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
            except Exception:
                ub, bn = [], []
            calls += 2
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
        return {"calls": calls, "filled": filled, "left": max(0, len(mins) - filled), "done": i >= len(mins) and j >= len(pre)}

    def prefetch_candles(self, pairs, max_calls: int = 40, deadline: float = None, pace: float = 0.15) -> dict:
        by = {}
        now9 = time.time()
        with self.lock:
            for sym, t in pairs:
                s9 = str(sym or "").upper()
                if not s9 or s9 in ("USDT", "USDC", "DAI") or now9 - self.d["neg_ts"].get(s9, 0) < self.NEG_TTL:
                    continue
                m = (int(t) // 60_000) * 60_000
                if f"{s9}:{m}" not in self.d["candle"]:
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
                except Exception:
                    arr = None
                opens = {}
                for row in arr or []:
                    try:
                        opens[int(row[0])] = float(row[1])
                    except (TypeError, ValueError, IndexError):
                        continue
                with self.lock:
                    for m in grp:
                        px = opens.get(m)
                        if _fin(px):
                            self.d["candle"][f"{s9}:{m}"] = px
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
        except Exception:
            return None
        plat = _cd.CG_PLATFORM.get(chain or "")
        if not plat or not ca:
            return None
        tk = ca.lower() if chain != "sol" else ca
        with self.lock:
            store = self.d.setdefault("cgday", {})
            if len(store) > 4000:
                for k9 in sorted(store)[:1000]:
                    store.pop(k9, None)
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
        except Exception:
            fx = None
        with self.lock:
            if fx:
                self.d["fx"][key] = fx
                self.d["neg_ts"].pop("_fx", None)
            else:
                self.d["neg_ts"]["_fx"] = int(time.time())
            self._dirty += 1
        self.maybe_save()
        return fx


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
            items = sorted(self.q, key=lambda x: (x[0], str(x[1] or ""), int(x[2])))
            self.q.clear()
        t0 = time.time()
        for kind, sym, m in items:
            try:
                if kind == "c":
                    self.px.candle_usd(sym, m)
                elif kind == "fx":
                    self.px.fx_at(m)
            except Exception:
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
            except Exception:
                time.sleep(5)


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
        except Exception:
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
            ok, why = ident(s, ex) if ident else (None, "")
            if ok is None and ref:
                rf = ref(s)
                if rf and _fin(rf[0] or 0):
                    r9 = v / rf[0]
                    ok, why = (True, f"{rf[1]} 기준 {r9:.2f}배") if IDENT_LO <= r9 <= IDENT_HI else (
                        False, f"{ex} {s} 시세가 {rf[1]}의 {r9:.2f}배 — 동명 다른 코인 의심")
            if ok is None:
                unk9 = None
                for ex2 in order:
                    if ex2 == ex or (ident and ident(s, ex2)[0] is False):
                        continue
                    bk9 = book(ex2)
                    if failed and failed(ex2):
                        unk9 = unk9 or ex2
                        continue
                    w = (bk9 or {}).get(s)
                    if _fin(w or 0) and not (IDENT_LO <= v / w <= IDENT_HI):
                        ok, why = False, f"{ex}·{ex2} {s} 시세가 {v / w:.2f}배 달라 같은 코인인지 확인 불가"
                        break
                if ok is None and unk9:
                    ok, why = False, f"{ex} {s} — 비교할 {unk9} 시세 조회 실패(동일성 판정 못 함 · 이번엔 안 씀)"
            if ok is False:
                if notes is not None:
                    notes.setdefault(s, []).append(why)
                continue
            out[s] = (float(v), f"{ex} {s}USDT" + (f" · {why}" if why else ""))
            break
    return out


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


def upbit_spot_krw(syms: list) -> dict:
    out = {}
    syms = [s for s in syms if s]
    for i in range(0, len(syms), 50):
        mk = ",".join(f"KRW-{s}" for s in syms[i:i + 50])
        try:
            arr = _gj(f"https://api.upbit.com/v1/ticker?markets={urllib.parse.quote(mk)}")
        except Exception:
            continue
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

    def _put(sym, px, vol=None):
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

    EX_DEAD[ex] = 0
    dead9 = set()
    if ex == "binance":
        return binance_spot_usdt()
    if ex == "hyperliquid":
        import hl_spot
        return hl_spot.fetch_book()
    try:
        return _ex_spot_usd_body(ex, usdt_krw, out, _put)
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
    elif ex == "bithumb":
        ok9 = isinstance(d, dict) and str(d.get("status")) == "0000"
        rows9 = d.get("data") if ok9 else None
        if isinstance(rows9, dict) and rows9:
            return rows9
        raise BulkError(ex, d)
    if not ok9 or not isinstance(rows9, list) or not rows9:
        raise BulkError(ex, d)
    return rows9


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
                _put(s[:-4], t.get("lastPrice"), v9)
    elif ex == "gate":
        arr = _gj("https://api.gateio.ws/api/v4/spot/tickers", timeout=20)
        for t in _bulk_rows(ex, arr):
            if not isinstance(t, dict):
                continue
            s = str(t.get("currency_pair") or "")
            if s.endswith("_USDT"):
                _put(s[:-5], t.get("last"), t.get("quote_volume"))
    elif ex == "kucoin":
        d = _gj("https://api.kucoin.com/api/v1/market/allTickers", timeout=20)
        for t in _bulk_rows(ex, d):
            if not isinstance(t, dict):
                continue
            s = str(t.get("symbol") or "")
            if s.endswith("-USDT"):
                _put(s[:-5], t.get("last"), t.get("vol"))
    elif ex == "okx":
        d = _gj("https://www.okx.com/api/v5/market/tickers?instType=SPOT", timeout=20)
        for t in _bulk_rows(ex, d):
            if not isinstance(t, dict):
                continue
            s = str(t.get("instId") or "")
            if s.endswith("-USDT"):
                _put(s[:-5], t.get("last"), t.get("vol24h"))
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


def _vol_zero(v) -> bool:
    if v is None or v == "":
        return False
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f) and f == 0.0


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
    except Exception:
        return _BN_DEAD["syms"]
    if not isinstance(arr, list):
        return _BN_DEAD["syms"]
    dead = set()
    for t in arr:
        if not isinstance(t, dict):
            continue
        s = str(t.get("symbol") or "")
        if not s.endswith("USDT"):
            continue
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
              "abstract": "abstract"}


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


def gt_token_prices_ex(chain: str, cas: list, keyed: bool = True):
    global _GT_ERR
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
                d = _gj(url, timeout=15)
        except urllib.error.HTTPError as e:
            ra = None
            try:
                ra = (e.headers or {}).get("Retry-After")
            except Exception:
                pass
            _GT_ERR = ("rate" if e.code == 429 else "http", e.code, str(ra or ""))
            if e.code == 429:
                break
            continue
        except Exception as e:
            _GT_ERR = ("net", None, f"{type(e).__name__}: {common.safe_err(e)[:80]}")
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
                    d2 = _gj(u2, timeout=15)
                    if isinstance(d2, dict):
                        p2, r2 = _gt_parse(d2, miss9)
                        b_px.update(p2)
                        b_res.update(r2)
                    else:
                        _GT_UNRESOLVED.update(miss9)
                except urllib.error.HTTPError as e:
                    _GT_ERR = ("rate" if e.code == 429 else "http", e.code, "")
                    if e.code != 404:
                        _GT_UNRESOLVED.update(miss9)
                except Exception as e:
                    _GT_ERR = ("net", None, f"{type(e).__name__}: {common.safe_err(e)[:80]}")
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


DS_CHAIN = {"eth": "ethereum", "bsc": "bsc", "base": "base", "arbitrum": "arbitrum", "optimism": "optimism",
            "polygon": "polygon", "sol": "solana", "zksync": "zksync", "scroll": "scroll",
            "monad": "monad", "megaeth": "megaeth", "plasma": "plasma", "xlayer": "xlayer", "kaia": "kaia",
            "fraxtal": "fraxtal", "bob": "bob", "story": "story", "somnia": "somnia", "avalanche": "avalanche",
            "abstract": "abstract"}
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
    global _DS_ERR, _DS_META
    _DS_META = {}
    net = DS_CHAIN.get(chain)
    if not net or not cas:
        return {}, {}
    batch = list(cas)[:30]
    url = f"https://api.dexscreener.com/tokens/v1/{net}/{','.join(batch)}"
    try:
        d = _gj(url, timeout=15)
    except urllib.error.HTTPError as e:
        _DS_ERR = ("rate" if e.code == 429 else "http", e.code, "")
        return {}, {}
    except Exception as e:
        _DS_ERR = ("net", None, f"{type(e).__name__}: {common.safe_err(e)[:80]}")
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
        try:
            liq = float(lq0) if lq0 not in (None, "") else None
        except (TypeError, ValueError):
            liq = None
        if liq is not None and not (math.isfinite(liq) and liq >= 0):
            liq = None
        for side in ("baseToken", "quoteToken"):
            tk = pr.get(side) or {}
            a = str(tk.get("address") or "")
            orig = want.get(a.lower() if evm else a)
            if orig is None:
                continue
            if orig not in meta and (tk.get("symbol") or tk.get("name")):
                meta[orig] = (str(tk.get("symbol") or "").strip()[:40], str(tk.get("name") or "").strip()[:80])
            if liq is not None:
                res[orig] = res.get(orig, 0.0) + liq
            if side == "baseToken":
                try:
                    px = float(pr.get("priceUsd") or 0)
                except (TypeError, ValueError):
                    continue
                if _fin(px) and (orig not in best or (liq or 0.0) > best[orig][0]):
                    best[orig] = (liq or 0.0, px)
    _DS_META = meta
    return {k: v[1] for k, v in best.items()}, {k: v for k, v in res.items() if k in best}


OKX_HOST = "https://www.okx.com"
OKX_PRICE_PATH = "/api/v6/dex/market/price"
OKX_CHAIN_INDEX = {"eth": "1", "base": "8453", "sol": "501", "bsc": "56",
                   "arbitrum": "42161", "optimism": "10", "polygon": "137",
                   "scroll": "534352", "zksync": "324", "gnosis": "100"}
def _okx_anchor_for(chain: str):
    if chain == "sol":
        for mint, sym in STABLE_MINTS.items():
            if sym == "USDC":
                return mint
        return None
    cas = STABLE_CAS.get(chain) or {}
    for sym_want in ("USDC", "USDT"):
        for ca, sym in cas.items():
            if sym == sym_want:
                return ca
    return None


def okx_headers(creds: dict, method: str, path: str, body: str):
    key, sec, pw = creds.get("key"), creds.get("secret"), creds.get("passphrase")
    if not (key and sec and pw):
        return None
    import base64
    import hashlib
    import hmac
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    sign = base64.b64encode(
        hmac.new(sec.encode(), (ts + method + path + body).encode(),
                 hashlib.sha256).digest()).decode()
    return {"OK-ACCESS-KEY": key, "OK-ACCESS-SIGN": sign, "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": pw, "Content-Type": "application/json",
            "User-Agent": _UA["User-Agent"], "Accept": "application/json"}


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
        req = urllib.request.Request(OKX_HOST + OKX_PRICE_PATH, data=body.encode(),
                                     headers=hdrs)
        try:
            try:
                with urllib.request.urlopen(req, timeout=12) as r:
                    d = json.loads(r.read().decode())
            except Exception:
                continue
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
    except Exception:
        return None
