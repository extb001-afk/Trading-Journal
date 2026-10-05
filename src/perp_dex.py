"""Perpetual DEX position readers."""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import math
import os
import re
import threading
import time
import zlib
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import common

log = logging.getLogger("tj-exf")

POLL_SEC = 600
TICK_SEC = 15
FRESH_SEC = 1800
DENY_COOL_SEC = 6 * 3600
BACKOFF_MAX = 3600
DAY_MS = 86400 * 1000
UA = "Mozilla/5.0 (tj-bot perp read-only)"
MAX_PAGES = 400
MAX_BYTES = 8 * 1024 * 1024
FILE_VER = 2
T_MIN_MS = 1420070400000
AMT_MAX = 1e13

DEXES = {
    "hyperliquid": {"name": "Hyperliquid", "kind": "evm", "pace": 1.0, "budget": 120},
    "dydx": {"name": "dYdX", "kind": "dydx", "pace": 0.4, "budget": 120},
    "lighter": {"name": "Lighter", "kind": "evm", "pace": 0.6, "budget": 120},
    "gmx": {"name": "GMX", "kind": "evm", "pace": 0.6, "budget": 120},
    "jupiter": {"name": "Jupiter", "kind": "sol", "pace": 0.6, "budget": 120},
    "pacifica": {"name": "Pacifica", "kind": "sol", "pace": 7.0, "budget": 240},
}
NAMES = {k: v["name"] for k, v in DEXES.items()}


_BECH = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _bech32_ok(s: str, hrp: str) -> bool:
    s = s.lower()
    if not s.startswith(hrp + "1"):
        return False
    data = s[len(hrp) + 1:]
    if len(data) < 7 or any(c not in _BECH for c in data):
        return False
    vals = [_BECH.index(c) for c in data]
    gen = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    chk = 1
    for v in [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp] + vals:
        b = chk >> 25
        chk = ((chk & 0x1ffffff) << 5) ^ v
        for i in range(5):
            chk ^= gen[i] if ((b >> i) & 1) else 0
    return chk == 1


def validate_address(dex: str, addr: str):
    if dex not in DEXES:
        raise ValueError("알 수 없는 퍼프 덱스입니다")
    kind = DEXES[dex]["kind"]
    a = (addr or "").strip()
    if kind == "dydx":
        if not re.fullmatch(r"dydx1[02-9ac-hj-np-z]{38}", a.lower()) or (a != a.lower() and a != a.upper()):
            raise ValueError("dYdX 주소는 dydx1 로 시작하는 43자입니다")
        if not _bech32_ok(a, "dydx"):
            raise ValueError("dYdX 주소 체크섬이 맞지 않습니다 — 원문을 다시 복사하세요")
        return a.lower(), "dYdX 주소 확인됨"
    import settings_store as ss
    k2, norm, note = ss.validate_address(a)
    if kind == "evm" and k2 != "evm":
        raise ValueError(f"{NAMES[dex]} 은 0x… EVM 주소를 씁니다")
    if kind == "sol" and k2 != "sol":
        raise ValueError(f"{NAMES[dex]} 는 Solana 주소를 씁니다")
    return norm, note


def configured(cfg: dict) -> dict:
    out = {}
    for w in (cfg or {}).get("perp_wallets") or []:
        if not isinstance(w, dict) or w.get("dex") not in DEXES:
            continue
        try:
            a, _ = validate_address(w["dex"], w.get("address"))
        except (ValueError, KeyError):
            continue
        lst = out.setdefault(w["dex"], [])
        if a not in [x["address"] for x in lst]:
            lst.append({"address": a, "label": str(w.get("label") or "")[:24]})
    return out


def fut_path(dex: str) -> str:
    return os.path.join(common.STATE_DIR, f"futures_{dex}.json")


class PerpHTTPError(RuntimeError):
    def __init__(self, code, msg, retry_after=None):
        super().__init__(f"HTTP {code} {msg}")
        self.code, self.retry_after = code, retry_after


class Budget(Exception):
    pass


def _http_default(url, body=None, timeout=15):
    data = json.dumps(body).encode() if body is not None else None
    h = {"User-Agent": UA, "Accept": "application/json", "Accept-Encoding": "gzip"}
    if data is not None:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError(f"퍼프 응답 크기 초과(>{MAX_BYTES // 1048576}MB)")
            if (r.headers.get("Content-Encoding") or "").lower() == "gzip":
                dz = zlib.decompressobj(16 + zlib.MAX_WBITS)
                out = dz.decompress(raw, MAX_BYTES + 1)
                if len(out) > MAX_BYTES or dz.unconsumed_tail:
                    raise ValueError(f"퍼프 응답 압축 해제 크기 초과(>{MAX_BYTES // 1048576}MB)")
                raw = out
            return json.loads(raw.decode() or "null")
    except urllib.error.HTTPError as e:
        ra = e.headers.get("Retry-After") if e.headers else None
        try:
            txt = e.read(512).decode("utf-8", "replace")
        except Exception:
            txt = ""
        raise PerpHTTPError(e.code, re.sub(r"\s+", " ", _txt(txt))[:160], ra) from None


HTTP = _http_default
SLEEP = time.sleep
_GATE = {}
_GATE_LOCK = threading.Lock()


def gate_open(dex, now=None):
    g = _GATE.get(dex) or {}
    return (now or time.time()) >= float(g.get("until") or 0)


def _gate_fail(dex, e, now=None):
    now = now or time.time()
    with _GATE_LOCK:
        g = _GATE.setdefault(dex, {"fail": 0, "until": 0})
        g["fail"] = int(g.get("fail") or 0) + 1
        code = getattr(e, "code", None)
        if code in (401, 403):
            wait = DENY_COOL_SEC
        elif code == 429:
            try:
                wait = max(30.0, float(getattr(e, "retry_after", None) or 0))
            except (TypeError, ValueError):
                wait = 0
            wait = wait or min(BACKOFF_MAX, 60 * 2 ** min(20, g["fail"] - 1))
        else:
            wait = min(BACKOFF_MAX, 60 * 2 ** min(20, g["fail"] - 1))
        g["until"] = now + wait
        g["why"] = common.safe_err(e)[:160]
        return wait


def _gate_ok(dex):
    with _GATE_LOCK:
        _GATE[dex] = {"fail": 0, "until": 0}


class Ctx:

    def __init__(self, dex, t0_ms, now=None, budget=None, cache=None):
        self.dex, self.t0 = dex, int(t0_ms)
        meta = DEXES[dex]
        self.pace = float(meta["pace"])
        self.deadline = time.time() + float(meta["budget"] if budget is None else budget)
        self.now = int(now or time.time())
        self.calls, self._last = 0, 0.0
        self.cache = cache if cache is not None else {}
        self.got_pos = {}

    def pos(self, addr, poss, info):
        self.got_pos[addr] = (poss, info)
        return poss, info

    def call(self, url, body=None):
        if time.time() > self.deadline:
            raise Budget()
        gap = self.pace - (time.time() - self._last)
        if self._last and gap > 0:
            SLEEP(gap)
        if self.dex == "hyperliquid":
            import hl_spot
            typ = str((body or {}).get("type") or "")
            base = hl_spot.WEIGHTS.get(typ, 20)
            try:
                e = hl_spot.GOV.admit(base, self.deadline, pace=0, reserve=hl_spot.RESERVE.get(typ, 0))
            except hl_spot.Budget:
                raise Budget() from None
            self._last = time.time()
            self.calls += 1
            r = None
            try:
                r = HTTP(url, body)
            finally:
                if typ in hl_spot.RESERVE:
                    hl_spot.GOV.settle(e, base + (len(r) // 20 if isinstance(r, list) else 0), base)
            return r
        self._last = time.time()
        self.calls += 1
        return HTTP(url, body)


def _f(v, d=0.0):
    try:
        x = float(v)
    except (TypeError, ValueError, OverflowError):
        return d
    return x if math.isfinite(x) and abs(x) <= 1e15 else d


def _big(v, d=0.0):
    try:
        x = float(v)
    except (TypeError, ValueError, OverflowError):
        return d
    return x if math.isfinite(x) else d


def _dec(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        d = v
    elif isinstance(v, str) and re.fullmatch(r"\d{1,2}", v.strip()):
        d = int(v.strip())
    else:
        return None
    return d if 0 <= d <= 36 else None


def _sym(v, n=40) -> str:
    return re.sub(r"[^A-Za-z0-9._:/-]", "", str(v if v is not None else ""))[:n] or "?"


def _txt(v, n=200) -> str:
    return re.sub(r"[<>\"'`\x00-\x1f]", "", str(v or ""))[:n]


def _lev(v):
    x = _f(v, 0.0)
    if not (0 < x <= 1000):
        return None
    return int(x) if x == int(x) else round(x, 2)


def _usd(base) -> str:
    b = _sym(base)
    b = re.sub(r"[-_/]?(USDT|USDC|USD)?[-_]?PERP$", "", b, flags=re.I) or b
    return b if re.search(r"[-_/](USDT|USDC|USD)$", b, re.I) else b + "-USD"


def _ev(add, t_ms, sym, kind, amt, uid, liq=False):
    try:
        t = int(t_ms)
        a = float(amt)
    except (TypeError, ValueError, OverflowError):
        return
    if not (T_MIN_MS <= t <= (time.time() + 86400) * 1000) or not math.isfinite(a) or abs(a) > AMT_MAX or abs(a) < 1e-12:
        return
    e = {"t": t, "symbol": _sym(sym), "kind": kind, "amount": round(a, 8), "uid": _sym(uid, 300)}
    if liq:
        e["liq"] = True
    add(e)


def desc_pages(ctx, st, key, fetch, pos_of, t_of, handle, limit, open_floor=None, full=False):
    s = st.setdefault(key, {})
    top = s.get("top")
    if top is not None:
        stop_at = top if open_floor is None else min(top, open_floor)
        before, newest, done = None, None, False
        for _ in range(MAX_PAGES):
            items = fetch(before)
            if not items:
                done = True
                break
            ps = [pos_of(x) for x in items]
            newest = max(ps) if newest is None else max(newest, max(ps))
            for x in items:
                if pos_of(x) >= stop_at:
                    handle(x)
            if min(ps) <= stop_at or len(items) < limit:
                done = True
                break
            if before is not None and min(ps) >= before:
                raise RuntimeError(f"{ctx.dex} 페이지 커서 미전진({key})")
            before = min(ps)
        if done and newest is not None:
            s["top"] = max(top, newest)
    if s.get("bf_done") and int(s.get("bf_floor") or 0) <= ctx.t0:
        return
    if s.get("bf_done"):
        s["bf_done"] = False
    before = s.get("bf")
    for _ in range(MAX_PAGES):
        items = fetch(before)
        if not items:
            s["bf_done"], s["bf_floor"] = True, ctx.t0
            break
        ps = [pos_of(x) for x in items]
        if s.get("top") is None:
            s["top"] = max(ps)
        for x in items:
            if t_of(x) >= ctx.t0:
                handle(x)
        if before is not None and min(ps) >= before:
            raise RuntimeError(f"{ctx.dex} 과거 페이지 커서 미전진({key})")
        before = min(ps)
        s["bf"] = before
        if len(items) < limit or (not full and min(t_of(x) for x in items) < ctx.t0):
            s["bf_done"], s["bf_floor"] = True, ctx.t0
            break


def page_pages(ctx, st, key, fetch_page, pos_of, t_of, handle, limit):
    s = st.setdefault(key, {})
    top = s.get("top")
    if top is not None:
        newest, done = top, False
        for pg in range(1, MAX_PAGES + 1):
            items = fetch_page(pg)
            if not items:
                done = True
                break
            ps = [pos_of(x) for x in items]
            newest = max(newest, max(ps))
            for x in items:
                if pos_of(x) >= top:
                    handle(x)
            if min(ps) <= top or len(items) < limit:
                done = True
                break
        if done:
            s["top"] = newest
    if s.get("bf_done") and int(s.get("bf_floor") or 0) <= ctx.t0:
        return
    s["bf_done"] = False
    pg = int(s.get("bf_page") or 1)
    for _ in range(MAX_PAGES):
        items = fetch_page(pg)
        if items and s.get("top") is None:
            s["top"] = max(pos_of(x) for x in items)
        for x in items:
            if t_of(x) >= ctx.t0:
                handle(x)
        if not items or len(items) < limit or min(t_of(x) for x in items) < ctx.t0:
            s["bf_done"], s["bf_floor"] = True, ctx.t0
            break
        pg += 1
        s["bf_page"] = pg


def asc_pages(ctx, st, key, fetch, t_of, handle, limit):
    s = st.setdefault(key, {})
    lo = s.get("lo")
    if lo is not None and ctx.t0 < lo:
        start = ctx.t0
        for _ in range(MAX_PAGES):
            rows = fetch(start)
            if not rows:
                break
            for r in rows:
                if t_of(r) < lo:
                    handle(r)
            last = max(t_of(r) for r in rows)
            if last >= lo or len(rows) < limit:
                break
            if last <= start:
                raise RuntimeError(f"{ctx.dex} 커서 전진 불가({key})")
            start = last
        s["lo"] = ctx.t0
    start = int(s.get("next") or ctx.t0)
    if lo is None:
        s["lo"] = min(start, ctx.t0)
    for _ in range(MAX_PAGES):
        rows = fetch(start)
        if not rows:
            break
        for r in rows:
            handle(r)
        last = max(t_of(r) for r in rows)
        if len(rows) >= limit and last <= start:
            raise RuntimeError(f"{ctx.dex} 커서 전진 불가({key}) — 같은 ms {len(rows)}건")
        start = max(start, last)
        s["next"] = start
        if len(rows) < limit:
            break


HL_URL = "https://api.hyperliquid.xyz/info"


def _hl_perp(coin) -> bool:
    c = str(coin or "")
    return bool(c) and not c.startswith("@") and "/" not in c


def fetch_hyperliquid(ctx, addr, st, add):
    ch = ctx.call(HL_URL, {"type": "clearinghouseState", "user": addr}) or {}
    poss = []
    for ap in ch.get("assetPositions") or []:
        p = (ap or {}).get("position") or {}
        szi = _f(p.get("szi"))
        if szi == 0:
            continue
        pv = _f(p.get("positionValue"))
        poss.append({"symbol": _usd(p.get("coin")), "side": "LONG" if szi > 0 else "SHORT", "qty": abs(szi),
                     "entry": _f(p.get("entryPx")), "mark": abs(pv / szi) if szi else 0.0,
                     "upnl": _f(p.get("unrealizedPnl")), "leverage": _lev((p.get("leverage") or {}).get("value")),
                     "liq": _f(p.get("liquidationPx"))})
    ms = ch.get("marginSummary") or {}
    info = {"equity": _f(ms.get("accountValue")), "maint": _f(ch.get("crossMaintenanceMarginUsed"))}
    ctx.pos(addr, poss, info)

    def fills(start):
        return ctx.call(HL_URL, {"type": "userFillsByTime", "user": addr, "startTime": int(start), "aggregateByTime": False}) or []

    def on_fill(r):
        if not _hl_perp(r.get("coin")) or r.get("dir") in ("Buy", "Sell"):
            return
        t, sym, tid = int(r.get("time") or 0), _usd(r.get("coin")), r.get("tid") or r.get("hash")
        liq = bool(r.get("liquidation"))
        _ev(add, t, sym, "REALIZED", _f(r.get("closedPnl")), f"hl:{addr}:{tid}:p", liq)
        if str(r.get("feeToken") or "USDC").upper() == "USDC":
            _ev(add, t, sym, "FEE", -_f(r.get("fee")), f"hl:{addr}:{tid}:f", liq)

    def funding(start):
        return ctx.call(HL_URL, {"type": "userFunding", "user": addr, "startTime": int(start)}) or []

    def on_fund(r):
        d = r.get("delta") or {}
        if d.get("type") not in (None, "funding"):
            return
        _ev(add, int(r.get("time") or 0), _usd(d.get("coin")), "FUNDING", _f(d.get("usdc")),
            f"hl:{addr}:fd:{r.get('time')}:{d.get('coin')}")

    asc_pages(ctx, st, "fills", fills, lambda r: int(r.get("time") or 0), on_fill, 2000)
    asc_pages(ctx, st, "funding", funding, lambda r: int(r.get("time") or 0), on_fund, 500)
    return poss, info


DYDX_IDX = "https://indexer.dydx.trade/v4"


def _iso_ms(s) -> int:
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp() * 1000)
    except (TypeError, ValueError):
        return 0


def fetch_dydx(ctx, addr, st, add):
    q = urllib.parse.quote(addr)
    try:
        a = ctx.call(f"{DYDX_IDX}/addresses/{q}") or {}
    except PerpHTTPError as e:
        if e.code == 404:
            return [], {"equity": 0.0}
        raise
    poss, eq = [], 0.0
    subs = sorted({int(s.get("subaccountNumber") or 0) for s in a.get("subaccounts") or []})
    open_h = {}
    for s in a.get("subaccounts") or []:
        n = int(s.get("subaccountNumber") or 0)
        eq += _f(s.get("equity"))
        for mk, p in (s.get("openPerpetualPositions") or {}).items():
            sz = _f(p.get("size"))
            if sz == 0:
                continue
            ent, up = _f(p.get("entryPrice")), _f(p.get("unrealizedPnl"))
            poss.append({"symbol": _usd(p.get("market") or mk), "side": "LONG" if sz > 0 else "SHORT", "qty": abs(sz),
                         "entry": ent, "mark": ent + up / sz if sz else 0.0, "upnl": up, "leverage": None, "liq": 0.0})
            h = int(_f(p.get("createdAtHeight"), 0))
            open_h[str(n)] = min(open_h.get(str(n), h), h)
    ctx.pos(addr, poss, {"equity": eq})
    prev_h = st.get("open_h") or {}
    for n in subs:
        base = f"address={q}&subaccountNumber={n}&limit=1000"

        def pager(path, key, n=n, base=base):
            def fetch(before):
                u = f"{DYDX_IDX}/{path}?{base}" + (f"&createdBeforeOrAtHeight={int(before)}" if before is not None else "")
                return (ctx.call(u) or {}).get(key) or []
            return fetch

        def on_pos(p, n=n):
            if str(p.get("status")) not in ("CLOSED", "LIQUIDATED"):
                return
            sgn = 1 if str(p.get("side")) == "LONG" else -1
            pnl = (_f(p.get("exitPrice")) - _f(p.get("entryPrice"))) * _f(p.get("sumClose")) * sgn
            _ev(add, _iso_ms(p.get("closedAt")), _usd(p.get("market")), "REALIZED", pnl,
                f"dy:{addr}:{n}:{p.get('market')}:{p.get('createdAtHeight')}", str(p.get("status")) == "LIQUIDATED")

        def on_fill(r, n=n):
            if str(r.get("marketType") or "PERPETUAL") != "PERPETUAL":
                return
            _ev(add, _iso_ms(r.get("createdAt")), _usd(r.get("market")), "FEE", -_f(r.get("fee")),
                f"dy:{addr}:{r.get('id')}:f", str(r.get("type")) in ("LIQUIDATED", "DELEVERAGED"))

        def on_fund(r, n=n):
            _ev(add, _iso_ms(r.get("createdAt")), _usd(r.get("ticker")), "FUNDING", _f(r.get("payment")),
                f"dy:{addr}:{n}:fd:{r.get('createdAtHeight')}:{r.get('ticker')}")

        h_of = lambda x: int(_f(x.get("createdAtHeight"), 0))
        fl = [int(v) for v in (prev_h.get(str(n)), open_h.get(str(n))) if v is not None]
        desc_pages(ctx, st, f"s{n}:pos", pager("perpetualPositions", "positions"), h_of,
                   lambda x: _iso_ms(x.get("closedAt") or x.get("createdAt")), on_pos, 1000, open_floor=min(fl) if fl else None, full=True)
        desc_pages(ctx, st, f"s{n}:fills", pager("fills", "fills"), h_of, lambda x: _iso_ms(x.get("createdAt")), on_fill, 1000)
        page_pages(ctx, st, f"s{n}:fundp",
                   lambda pg, base=base: (ctx.call(f"{DYDX_IDX}/fundingPayments?{base}&page={int(pg)}") or {}).get("fundingPayments") or [],
                   h_of, lambda x: _iso_ms(x.get("createdAt")), on_fund, 1000)
    st["open_h"] = open_h
    return poss, {"equity": eq}


LT_URL = "https://mainnet.zklighter.elliot.ai/api/v1"


def _lt_side(trade, me):
    me_bid = int(trade.get("bid_account_id") or -1) == me
    maker_is_bid = not bool(trade.get("is_maker_ask"))
    return (1 if me_bid else -1), ("maker" if me_bid == maker_is_bid else "taker")


def lighter_infer(trade, me, after):
    d, pre = _lt_side(trade, me)
    S0, Q = _f(trade.get(pre + "_position_size_before")), abs(_f(trade.get(pre + "_entry_quote_before")))
    qn, px = _f(trade.get("size")), _f(trade.get("price"))
    if S0 == 0:
        return 0, 0.0, True
    S = abs(S0)
    if S0 < 0:
        sg = -1
    else:
        if after is None:
            return None, 0.0, False
        sa, za = after
        tol = max(1e-9, 1e-6 * (S + qn))
        cand = {d: (d, S + qn), -d: ((d if qn > S + tol else (-d if qn < S - tol else 0)), abs(qn - S))}
        hit = [k for k, (s2, z2) in cand.items() if abs(z2 - za) <= tol and (z2 <= tol or s2 == sa)]
        if len(hit) != 1:
            return None, 0.0, False
        sg = hit[0]
    if sg == d:
        return sg, 0.0, True
    return sg, (px - Q / S) * min(qn, S) * sg, True


def fetch_lighter(ctx, addr, st, add):
    d = ctx.call(f"{LT_URL}/account?by=l1_address&value={addr}") or {}
    poss, eq, mm, unk = [], 0.0, 0.0, 0
    accs = []
    for a in d.get("accounts") or []:
        if not isinstance(a, dict):
            continue
        idx = int(a.get("index") or a.get("account_index") or 0)
        eq += _f(a.get("total_asset_value"))
        mm += _f(a.get("cross_maintenance_margin_requirement"))
        cur, syms = {}, {}
        for p in a.get("positions") or []:
            mid = int(p.get("market_id") or 0)
            syms[mid] = p.get("symbol") or f"M{mid}"
            z, sg = _f(p.get("position")), (-1 if int(_f(p.get("sign"), 1)) < 0 else 1)
            cur[mid] = (sg if z != 0 else 0, abs(z))
            if z == 0:
                continue
            imf = _f(p.get("initial_margin_fraction"))
            poss.append({"symbol": _usd(syms[mid]), "side": "LONG" if sg > 0 else "SHORT", "qty": abs(z),
                         "entry": _f(p.get("avg_entry_price")), "mark": abs(_f(p.get("position_value")) / z),
                         "upnl": _f(p.get("unrealized_pnl")), "leverage": round(100 / imf, 1) if imf > 0 else None,
                         "liq": max(0.0, _f(p.get("liquidation_price")))})
        accs.append((idx, cur, syms))
    info = {"equity": eq, "maint": mm}
    ctx.pos(addr, poss, info)
    ts_of = lambda t: int(t.get("timestamp") or 0)

    for idx, cur, syms in accs:
        sst = st.setdefault(f"a{idx}", {})

        def fetch(cursor, idx=idx):
            u = f"{LT_URL}/trades?account_index={idx}&sort_by=timestamp&sort_dir=desc&limit=100" + (f"&cursor={urllib.parse.quote(cursor)}" if cursor else "")
            j = ctx.call(u) or {}
            return [t for t in j.get("trades") or [] if isinstance(t, dict)], j.get("next_cursor")

        def process(items, after, idx=idx, syms=syms):
            nonlocal unk
            for t in items:
                if str(t.get("market_kind") or "perps") != "perps":
                    continue
                mid = int(t.get("market_id") or 0)
                sg, rz, ok = lighter_infer(t, idx, after.get(mid, (0, 0.0)))
                _dd, pre = _lt_side(t, idx)
                ts, sym = ts_of(t), _usd(syms.get(mid) or f"M{mid}")
                uid = f"lt:{addr}:{t.get('trade_id_str') or t.get('trade_id')}"
                liq = str(t.get("type") or "trade") in ("liquidation", "deleverage")
                if ok:
                    _ev(add, ts, sym, "REALIZED", rz, uid + ":p", liq)
                else:
                    unk += 1
                fee_i = t.get(pre + "_fee")
                if fee_i is not None:
                    _ev(add, ts, sym, "FEE", -_f(t.get("usd_amount")) * _f(fee_i) / 1e6, uid + ":f", liq)
                S = abs(_f(t.get(pre + "_position_size_before")))
                after[mid] = (sg, S) if ok else None

        top = sst.get("top")
        if top is not None:
            cursor, got, newest, done = None, [], top, False
            old_ids = set(sst.get("top_ids") or [])
            for _ in range(MAX_PAGES):
                items, nxt = fetch(cursor)
                if not items:
                    done = True
                    break
                newest = max([newest] + [ts_of(t) for t in items])
                got += [t for t in items if ts_of(t) > top or (ts_of(t) == top and str(t.get("trade_id")) not in old_ids)]
                if min(ts_of(t) for t in items) <= top or not nxt:
                    done = True
                    break
                cursor = nxt
            if done:
                process(got, dict(cur))
                ids = {str(t.get("trade_id")) for t in got if ts_of(t) == newest} | (old_ids if newest == top else set())
                sst["top"], sst["top_ids"] = newest, sorted(ids)
        if sst.get("bf_done") and int(sst.get("bf_floor") or 0) <= ctx.t0:
            continue
        if sst.get("bf_done"):
            for k in ("bf_cursor", "bf_after"):
                sst.pop(k, None)
            sst["bf_started"] = False
        sst["bf_done"] = False
        cursor = sst.get("bf_cursor")
        after = dict(cur)
        if cursor:
            for k, v in (sst.get("bf_after") or {}).items():
                after[int(k)] = tuple(v) if isinstance(v, list) else None
        for _ in range(MAX_PAGES):
            items, nxt = fetch(cursor)
            if not sst.get("bf_started"):
                sst["bf_started"] = True
                if sst.get("top") is None:
                    sst["top"] = max([ts_of(t) for t in items] or [0])
                    sst["top_ids"] = sorted(str(t.get("trade_id")) for t in items if ts_of(t) == sst["top"])
            keep = [t for t in items if ts_of(t) >= ctx.t0]
            process(keep, after)
            sst["bf_after"] = {str(k): (list(v) if v is not None else None) for k, v in after.items()}
            if not items or not nxt or len(keep) < len(items):
                sst["bf_done"], sst["bf_floor"] = True, ctx.t0
                sst.pop("bf_cursor", None)
                break
            cursor = nxt
            sst["bf_cursor"] = cursor
    if unk:
        info["unk"] = unk
    return poss, info


JUP_URL = "https://perps-api.jup.ag/v1"
JUP_MINTS = {"So11111111111111111111111111111111111111112": "SOL", "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs": "ETH",
             "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh": "BTC"}
JUP_PAGE = 50


def fetch_jupiter(ctx, addr, st, add):
    j = ctx.call(f"{JUP_URL}/positions?walletAddress={addr}") or {}
    poss, eq = [], 0.0
    for p in j.get("dataList") or []:
        size, ent = _f(p.get("size")), _f(p.get("entryPrice"))
        if size <= 0:
            continue
        eq += _f(p.get("value"))
        sym = JUP_MINTS.get(p.get("marketMint")) or str(p.get("marketMint") or "?")[:4]
        poss.append({"symbol": _usd(sym), "side": "LONG" if str(p.get("side")) == "long" else "SHORT",
                     "qty": size / ent if ent else 0.0, "entry": ent, "mark": _f(p.get("markPrice")),
                     "upnl": _f(p.get("pnlBeforeFeesUsd")), "leverage": _lev(p.get("leverage")), "liq": _f(p.get("liquidationPrice"))})
    ctx.pos(addr, poss, {"equity": eq})

    def fetch(before):
        off = int(before or 0)
        r = ctx.call(f"{JUP_URL}/trades?walletAddress={addr}&start={off}&end={off + JUP_PAGE}") or {}
        rows = [x for x in r.get("dataList") or [] if isinstance(x, dict)]
        for i, x in enumerate(rows):
            x["_off"] = off + i
        return rows

    def on_tr(x):
        t = int(_f(x.get("createdTime"))) * 1000
        sym = _usd(x.get("positionName") or JUP_MINTS.get(x.get("mint")) or "?")
        uid = f"jup:{addr}:{x.get('txHash')}:{x.get('positionPubkey')}:{x.get('action')}"
        liq = str(x.get("orderType")) == "Liquidation"
        if x.get("pnl") is not None:
            _ev(add, t, sym, "REALIZED", _f(x.get("pnl")), uid + ":p", liq)
        bf = _f(x.get("borrowFee"))
        _ev(add, t, sym, "FEE", -(_f(x.get("fee")) - bf), uid + ":f", liq)
        _ev(add, t, sym, "FUNDING", -bf, uid + ":b", liq)

    s = st.setdefault("trades", {})
    top = s.get("top")
    if top is not None:
        off, newest, done = 0, None, False
        for _ in range(MAX_PAGES):
            rows = fetch(off)
            if not rows:
                done = True
                break
            ts = [int(_f(x.get("createdTime"))) for x in rows]
            newest = max(ts + [newest or 0])
            for x in rows:
                if int(_f(x.get("createdTime"))) >= top:
                    on_tr(x)
            if min(ts) < top or len(rows) < JUP_PAGE:
                done = True
                break
            off += len(rows)
        if done and newest:
            s["top"] = max(top, newest)
    if not (s.get("bf_done") and int(s.get("bf_floor") or 0) <= ctx.t0):
        s["bf_done"] = False
        off = int(s.get("bf_off") or 0)
        for _ in range(MAX_PAGES):
            rows = fetch(off)
            if s.get("top") is None:
                s["top"] = max([int(_f(x.get("createdTime"))) for x in rows] or [0])
            keep = [x for x in rows if int(_f(x.get("createdTime"))) * 1000 >= ctx.t0]
            for x in keep:
                on_tr(x)
            off += len(rows)
            s["bf_off"] = off
            if len(rows) < JUP_PAGE or len(keep) < len(rows):
                s["bf_done"], s["bf_floor"] = True, ctx.t0
                break
    return poss, {"equity": eq}


GMX_CHAINS = {"arbitrum": ("https://gmx.squids.live/gmx-synthetics-arbitrum:prod/api/graphql", "https://arbitrum-api.gmxinfra.io"),
              "avalanche": ("https://gmx.squids.live/gmx-synthetics-avalanche:prod/api/graphql", "https://avalanche-api.gmxinfra.io")}
GMX_PAGE = 200
GMX_ORDER_TYPES = [2, 3, 4, 5, 6, 7, 8]
E30 = 10 ** 30


def _gmx_meta(ctx, ch):
    if ch in ctx.cache:
        return ctx.cache[ch]
    rest = GMX_CHAINS[ch][1]
    mk = (ctx.call(rest + "/markets") or {}).get("markets") or []
    tk = (ctx.call(rest + "/tokens") or {}).get("tokens") or []
    px = ctx.call(rest + "/prices/tickers") or []
    toks = {str(t.get("address") or "").lower(): t for t in tk if isinstance(t, dict)}
    mkts = {str(m.get("marketToken") or "").lower(): str(m.get("indexToken") or "").lower() for m in mk if isinstance(m, dict)}
    pxs = {str(p.get("tokenAddress") or "").lower(): (_big(p.get("minPrice")) + _big(p.get("maxPrice"))) / 2 for p in px if isinstance(p, dict)}
    ctx.cache[ch] = (mkts, toks, pxs)
    return ctx.cache[ch]


def fetch_gmx(ctx, addr, st, add):
    import settings_store as ss
    acc = ss.to_checksum(addr)
    poss = []
    metas = {}
    for ch, (sq, _rest) in GMX_CHAINS.items():
        mkts, toks, pxs = metas[ch] = _gmx_meta(ctx, ch)
        q = ('{ positions(limit: 100, where: {account_eq: "%s", isSnapshot_eq: false, sizeInUsd_gt: 0}) '
             '{ market isLong sizeInTokens sizeInUsd entryPrice leverage } }') % acc
        for p in ((ctx.call(sq, {"query": q}) or {}).get("data") or {}).get("positions") or []:
            idx = mkts.get(str(p.get("market") or "").lower(), "")
            t = toks.get(idx) or {}
            dec = _dec(t.get("decimals"))
            if dec is None:
                log.warning("GMX %s 토큰 decimals 이상(%r) — 포지션 제외", _sym(t.get("symbol")), str(t.get("decimals"))[:20])
                continue
            qty = _big(p.get("sizeInTokens")) / 10 ** dec
            size = _big(p.get("sizeInUsd")) / E30
            mark = pxs.get(idx, 0.0) / 10 ** (30 - dec)
            lg = bool(p.get("isLong"))
            upnl = (qty * mark - size) if lg else (size - qty * mark)
            poss.append({"symbol": _usd(t.get("symbol") or "?"), "side": "LONG" if lg else "SHORT", "qty": qty,
                         "entry": _big(p.get("entryPrice")) / 10 ** (30 - dec), "mark": mark, "upnl": upnl if mark else 0.0,
                         "leverage": round(_big(p.get("leverage")) / 1e4, 2) or None, "liq": 0.0})
    ctx.pos(addr, poss, {})
    for ch, (sq, _rest) in GMX_CHAINS.items():
        mkts, toks, _pxs = metas[ch]

        def fetch(before, sq=sq):
            w = 'account_eq: "%s", eventName_eq: "OrderExecuted", orderType_in: %s' % (acc, json.dumps(GMX_ORDER_TYPES))
            if before is not None:
                w += ", timestamp_lt: %d" % int(before)
            q2 = ('{ tradeActions(limit: %d, orderBy: [timestamp_DESC, id_DESC], where: {%s}) { id orderType marketAddress '
                  'pnlUsd basePnlUsd positionFeeAmount borrowingFeeAmount fundingFeeAmount liquidationFeeAmount collateralTokenPriceMin '
                  'timestamp } }') % (GMX_PAGE, w)
            return ((ctx.call(sq, {"query": q2}) or {}).get("data") or {}).get("tradeActions") or []

        def on_ta(x, ch=ch, mkts=mkts, toks=toks):
            cp = _big(x.get("collateralTokenPriceMin"))
            fee = (_big(x.get("positionFeeAmount")) + _big(x.get("liquidationFeeAmount"))) * cp / E30
            fund = (_big(x.get("borrowingFeeAmount")) + _big(x.get("fundingFeeAmount"))) * cp / E30
            pnl = x.get("pnlUsd")
            gross = (_big(pnl) / E30 + fee + fund) if pnl is not None else _big(x.get("basePnlUsd")) / E30
            idx = mkts.get(str(x.get("marketAddress") or "").lower(), "")
            sym = _usd((toks.get(idx) or {}).get("symbol") or "?")
            t, uid, liq = int(_big(x.get("timestamp"))) * 1000, f"gmx:{addr}:{ch}:{x.get('id')}", int(_big(x.get("orderType"))) == 7
            _ev(add, t, sym, "REALIZED", gross, uid + ":p", liq)
            _ev(add, t, sym, "FEE", -fee, uid + ":f", liq)
            _ev(add, t, sym, "FUNDING", -fund, uid + ":b", liq)

        desc_pages(ctx, st, f"{ch}:ta", fetch, lambda x: int(_big(x.get("timestamp"))) + 1, lambda x: int(_big(x.get("timestamp"))) * 1000,
                   on_ta, GMX_PAGE)
    return poss, {}


PAC_URL = "https://api.pacifica.fi/api/v1"


def fetch_pacifica(ctx, addr, st, add):
    if "px" not in ctx.cache:
        ctx.cache["px"] = {str(p.get("symbol")): _f(p.get("mark")) for p in ((ctx.call(f"{PAC_URL}/info/prices") or {}).get("data") or [])
                           if isinstance(p, dict)}
    pxs = ctx.cache["px"]
    poss = []
    for p in (ctx.call(f"{PAC_URL}/positions?account={addr}") or {}).get("data") or []:
        z = _f(p.get("amount"))
        if z <= 0:
            continue
        lg, ent, mk = str(p.get("side")) == "bid", _f(p.get("entry_price")), pxs.get(str(p.get("symbol")), 0.0)
        poss.append({"symbol": _usd(p.get("symbol")), "side": "LONG" if lg else "SHORT", "qty": z, "entry": ent, "mark": mk,
                     "upnl": ((mk - ent) * z if lg else (ent - mk) * z) if mk else 0.0, "leverage": None,
                     "liq": max(0.0, _f(p.get("liquidation_price")))})
    acc = (ctx.call(f"{PAC_URL}/account?account={addr}") or {}).get("data") or {}
    info = {"equity": _f(acc.get("account_equity")), "maint": _f(acc.get("cross_mmr"))}
    ctx.pos(addr, poss, info)

    def cur_pager(path, key):
        s = st.setdefault(key, {})
        top = s.get("top")

        def fetch(cursor):
            j = ctx.call(f"{PAC_URL}/{path}?account={addr}&limit=100" + (f"&cursor={urllib.parse.quote(cursor)}" if cursor else "")) or {}
            return [x for x in j.get("data") or [] if isinstance(x, dict)], (j.get("next_cursor") if j.get("has_more") else None)
        return s, top, fetch

    def on_tr(x):
        t, sym, uid = int(_f(x.get("created_at"))), _usd(x.get("symbol")), f"pac:{addr}:{x.get('history_id')}"
        liq = "liquidat" in str(x.get("cause") or "")
        fee = _f(x.get("fee"))
        if str(x.get("side") or "").startswith("close"):
            _ev(add, t, sym, "REALIZED", _f(x.get("pnl")) + fee, uid + ":p", liq)
        _ev(add, t, sym, "FEE", -fee, uid + ":f", liq)

    def on_fd(x):
        _ev(add, int(_f(x.get("created_at"))), _usd(x.get("symbol")), "FUNDING", _f(x.get("payout")), f"pac:{addr}:fd:{x.get('history_id')}")

    for path, key, h in (("trades/history", "trades", on_tr), ("funding/history", "funding", on_fd)):
        s, top, fetch = cur_pager(path, key)
        hid = lambda x: int(_f(x.get("history_id")))
        if top is not None:
            cursor, newest, done = None, None, False
            for _ in range(MAX_PAGES):
                rows, nxt = fetch(cursor)
                if not rows:
                    done = True
                    break
                newest = max([hid(x) for x in rows] + [newest or 0])
                for x in rows:
                    if hid(x) > top:
                        h(x)
                if min(hid(x) for x in rows) <= top or not nxt:
                    done = True
                    break
                cursor = nxt
            if done and newest:
                s["top"] = max(top, newest)
        if not (s.get("bf_done") and int(s.get("bf_floor") or 0) <= ctx.t0):
            if s.get("bf_done"):
                s.pop("bf_cursor", None)
                s["bf_started"] = False
            s["bf_done"] = False
            cursor = s.get("bf_cursor")
            for _ in range(MAX_PAGES):
                rows, nxt = fetch(cursor)
                if not s.get("bf_started"):
                    s["bf_started"] = True
                    if s.get("top") is None:
                        s["top"] = max([hid(x) for x in rows] or [0])
                keep = [x for x in rows if int(_f(x.get("created_at"))) >= ctx.t0]
                for x in keep:
                    h(x)
                if not rows or not nxt or len(keep) < len(rows):
                    s["bf_done"], s["bf_floor"] = True, ctx.t0
                    s.pop("bf_cursor", None)
                    break
                cursor = nxt
                s["bf_cursor"] = cursor
    return poss, info


FETCHERS = {"hyperliquid": fetch_hyperliquid, "dydx": fetch_dydx, "lighter": fetch_lighter, "gmx": fetch_gmx,
            "jupiter": fetch_jupiter, "pacifica": fetch_pacifica}


def _clean_pos(p, addr):
    return {"symbol": _sym(p.get("symbol")), "side": "SHORT" if p.get("side") == "SHORT" else "LONG",
            "qty": _f(p.get("qty")), "entry": _f(p.get("entry")), "mark": _f(p.get("mark")), "upnl": _f(p.get("upnl")),
            "leverage": _lev(p.get("leverage")), "liq": max(0.0, _f(p.get("liq"))), "acct": addr}


def snapshot_dex(dex, accts, t0_ms, now=None, note=None):
    now = int(now or time.time())
    path = fut_path(dex)
    try:
        old = common.read_json(path, {})
    except SystemExit:
        log.warning("%s 퍼프 스냅숏 손상 — 새로 받습니다", dex)
        old = {}
    want = {a["address"]: a for a in accts}
    ev = [e for e in old.get("events") or [] if e.get("acct") in want]
    cursor = {k: v for k, v in (old.get("cursor") or {}).items() if k in want}
    if old and int(_f(old.get("v"), 1)) < FILE_VER:
        log.warning("%s 퍼프 스냅숏이 옛 판(v%s)입니다 — 기록은 그대로 두고 이어서 받습니다(판 %d 로 저장)", dex, old.get("v", 1), FILE_VER)
    seen = {e.get("uid") for e in ev}
    ameta = {k: v for k, v in (old.get("accts") or {}).items() if k in want}
    pos_old = [p for p in old.get("positions") or [] if p.get("acct") in want]
    poss, ok_any, http_err, last_err = [], False, None, None
    share = max(20.0, float(DEXES[dex]["budget"]) / max(1, len(accts)))
    cache, calls, last_call = {}, 0, 0.0
    ctx = None
    for a in accts:
        ctx = Ctx(dex, t0_ms, now, budget=share, cache=cache)
        ctx._last = last_call
        addr = a["address"]
        m = dict(ameta.get(addr) or {}, label=a.get("label") or "")
        if http_err is not None:
            m["err"] = "덱스 전체 대기(한도·권한): " + _txt(http_err, 120)
            poss += [p for p in pos_old if p.get("acct") == addr]
            ameta[addr] = m
            continue
        st = json.loads(json.dumps(cursor.get(addr) or {}))
        new_ev = []

        def add(e, addr=addr, new_ev=new_ev):
            if e["uid"] in seen:
                return
            seen.add(e["uid"])
            new_ev.append(dict(e, acct=addr))
        try:
            p9, info = FETCHERS[dex](ctx, addr, st, add)
            poss += [_clean_pos(p, addr) for p in p9]
            m.update({"ts": now, "equity": round(_f(info.get("equity")), 2) if info.get("equity") is not None else None})
            m.pop("err", None)
            for k9 in ("maint", "unk"):
                if info.get(k9):
                    m[k9] = round(_f(info[k9]), 4) if k9 == "maint" else int(info[k9])
                else:
                    m.pop(k9, None)
            ok_any = True
        except Budget:
            if addr in ctx.got_pos:
                p9, info = ctx.got_pos[addr]
                poss += [_clean_pos(p, addr) for p in p9]
                m.update({"ts": now, "equity": round(_f(info.get("equity")), 2) if info.get("equity") is not None else m.get("equity")})
                ok_any = True
                m["err"] = "과거 기록 이어 받는 중(주기당 시간 예산) — 다음 주기에 계속"
            else:
                m["err"] = "시간 예산 소진 — 다음 주기에 이어 받음"
                poss += [p for p in pos_old if p.get("acct") == addr]
        except PerpHTTPError as e:
            m["err"] = _txt(e, 160)
            poss += [p for p in pos_old if p.get("acct") == addr]
            if e.code in (401, 403, 429):
                http_err = e
            last_err = e
            new_ev, st = [], cursor.get(addr) or {}
        except Exception as e:
            m["err"] = _txt(type(e).__name__ + ": " + common.safe_err(e), 160)
            poss += [p for p in pos_old if p.get("acct") == addr]
            last_err = e
            new_ev, st = [], cursor.get(addr) or {}
        ev += new_ev
        cursor[addr] = st
        ameta[addr] = m
        calls += ctx.calls
        last_call = ctx._last
    eq = [_f(m.get("equity")) for m in ameta.values() if m.get("equity") is not None]
    mm = [_f(m.get("maint")) for m in ameta.values() if m.get("maint")]
    wallet = {"balance": None, "equity": round(sum(eq), 2) if eq else None,
              "note": (f"계정 가치 {sum(eq):,.2f} · " if eq else "") + (note or "덱스 담보 — 총자산 미반영(표시 전용)")}
    if mm and eq and sum(eq) > 0:
        wallet.update({"maint_margin": round(sum(mm), 4), "margin_balance": round(sum(eq), 4)})
    ev.sort(key=lambda r: r["t"])
    if len(ev) > 20000:
        log.warning("%s 퍼프 정산 이벤트 %d건 (파일 비대) — 보존 유지", dex, len(ev))
    out = {"v": FILE_VER, "ts": now if ok_any else int(old.get("ts") or 0), "dex": dex, "wallet": wallet, "positions": poss,
           "events": ev, "cursor": cursor, "accts": ameta}
    common.atomic_write_json(path, out)
    if http_err is not None:
        raise http_err
    if not ok_any and last_err is not None:
        raise last_err
    return out, calls


def _t0_ms(cfg, now=None):
    try:
        import bf_engine
        t = bf_engine.effective_backfill_t0(cfg, now)
    except Exception:
        months = float((cfg or {}).get("backfill_months") or 5)
        t = (now or time.time()) - months * 30 * 86400
    return int(max(0, t) * 1000)


def snapshot_all(cfg=None, now=None):
    if cfg is None:
        cfg = _read_cfg()
    if cfg is None:
        return {}
    conf = configured(cfg)
    rows9 = {w.get("dex") for w in ((cfg or {}).get("perp_wallets") or []) if isinstance(w, dict)}
    for dex in DEXES:
        if dex not in conf:
            if dex in rows9:
                if os.path.exists(fut_path(dex)):
                    log.warning("%s 퍼프 주소 형식 오류 — 수집은 건너뛰고 누적 기록 파일은 지우지 않아요(config perp_wallets 확인)", dex)
                continue
            try:
                os.remove(fut_path(dex))
                log.info("%s 퍼프 주소가 없어 스냅숏을 지웠어요", dex)
            except FileNotFoundError:
                pass
    t0 = _t0_ms(cfg, now)
    res = {}

    def one(dex):
        if not gate_open(dex):
            return dex, "대기(백오프)"
        try:
            out, n = snapshot_dex(dex, conf[dex], t0, now, note=_note(dex, cfg))
            _gate_ok(dex)
            errs = sum(1 for m in out["accts"].values() if m.get("err"))
            return dex, f"ok 콜 {n} · 이벤트 {len(out['events'])} · 포지션 {len(out['positions'])}" + (f" · 주소 오류 {errs}" if errs else "")
        except (Exception, SystemExit) as e:
            w = _gate_fail(dex, e)
            return dex, f"실패 → {int(w)}초 대기: {common.safe_err(e)[:120]}"
    todo = [d for d in DEXES if d in conf]
    if not todo:
        return res
    with ThreadPoolExecutor(max_workers=len(todo), thread_name_prefix="perp") as pool:
        for dex, msg in pool.map(one, todo):
            res[dex] = msg
            (log.info if msg.startswith(("ok", "대기")) else log.warning)("퍼프 %s: %s", dex, msg)
    return res


def _note(dex, cfg):
    if dex != "hyperliquid":
        return None
    try:
        import hl_spot
        if hl_spot.addresses(cfg):
            return "현금(USDC)은 Hyperliquid 잔고로 총자산 반영(현물 수집 주소) · 미실현 손익은 표시 전용"
    except Exception:
        pass
    return None


def _read_cfg():
    try:
        with open(common.CONFIG_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _fp(cfg):
    return hashlib.sha1(json.dumps(configured(cfg), sort_keys=True).encode()).hexdigest()


_BG = {"started": False}


def start_background():
    if _BG["started"]:
        return
    _BG["started"] = True

    def loop():
        last_fp, next_at = None, 0.0
        while True:
            try:
                cfg = _read_cfg()
                if cfg is None:
                    time.sleep(TICK_SEC)
                    continue
                fp = _fp(cfg)
                if fp != last_fp or time.time() >= next_at:
                    if configured(cfg) or last_fp is not None:
                        snapshot_all(cfg)
                    last_fp, next_at = fp, time.time() + POLL_SEC
            except Exception as e:
                log.warning("퍼프 덱스 수집 주기 실패(다음 주기): %s", repr(e)[:160])
                next_at = time.time() + POLL_SEC
            time.sleep(TICK_SEC)
    threading.Thread(target=loop, name="perp-dex", daemon=True).start()


def status(cfg=None) -> dict:
    conf = configured(cfg if cfg is not None else (_read_cfg() or {}))
    out = {}
    for dex, lst in conf.items():
        try:
            d = common.read_json(fut_path(dex), {})
        except SystemExit:
            d = {}
        ac = d.get("accts") or {}
        out[dex] = {"ts": int(d.get("ts") or 0), "events": len(d.get("events") or []), "positions": len(d.get("positions") or []),
                    "accts": {a["address"]: {k: v for k, v in (ac.get(a["address"]) or {}).items() if k in ("ts", "err", "equity", "unk")}
                              for a in lst},
                    "wait": None if gate_open(dex) else (_GATE.get(dex) or {}).get("why")}
    return out
