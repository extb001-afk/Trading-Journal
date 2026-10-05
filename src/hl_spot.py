from __future__ import annotations

import collections
import hashlib
import json
import logging
import math
import os
import re
import threading
import time
import uuid as uuidlib
from decimal import Decimal, InvalidOperation

import common

log = logging.getLogger("tj-exf")

VENUE = "hyperliquid"
NAME = "Hyperliquid"
HL_URL = "https://api.hyperliquid.xyz/info"
BRIDGE2 = "0x2df1c51e09aecf9cacb7bc98cb1742757f163df7"
SYS_HYPE = "0x2222222222222222222222222222222222222222"
_SYS_RE = re.compile(r"^0x20{2,}[0-9a-f]{1,8}$")

WEIGHT_CAP_MIN = 400
PACE = 0.6
CYCLE_BUDGET = 60
DEX_SCAN_SEC = 24 * 3600
META_TTL = 24 * 3600
META_RETRY = 3600
FILLS_PAGE = 2000
LEDGER_FULL = 100
MAX_PAGES = 200
LATE_MARGIN = 120
SEEN_KEEP_MS = 14 * 86400 * 1000
T_MIN_MS = 1577836800000
AMT_MAX = Decimal("1e15")
BACKOFF_MAX = 3600
STABLE_FACE = ("USDC", "USDT")
WEIGHTS = {"clearinghouseState": 2, "spotClearinghouseState": 2, "allMids": 2, "l2Book": 2, "exchangeStatus": 2}
EXTRA_PER = {"userFillsByTime": 20, "userNonFundingLedgerUpdates": 20, "userFunding": 20, "candleSnapshot": 60}
RESERVE = {"userFillsByTime": 100, "userNonFundingLedgerUpdates": 25, "userFunding": 25, "candleSnapshot": 10}

SAME_COIN = {"HYPE": ("HYPE", "hyperliquid"), "UBTC": ("BTC", "bitcoin"), "UETH": ("ETH", "ethereum"), "USOL": ("SOL", "solana"),
             "USDT0": ("USDT", "tether"), "USDE": ("USDE", "ethena-usde"), "XAUT0": ("XAUT", "tether-gold"),
             "UFART": ("FARTCOIN", "fartcoin"), "UPUMP": ("PUMP", "pump-fun"), "UENA": ("ENA", "ethena"), "UZEC": ("ZEC", "zcash"),
             "UXPL": ("XPL", "plasma"), "LINK0": ("LINK", "chainlink"), "AAVE0": ("AAVE", "aave")}
PX_ORDER = ("binance", "bybit")
IDENT_LO, IDENT_HI = 0.5, 2.0
QUOTE_PREF = ("USDC", "USDT0", "USDE", "USDH")

INTERNAL_TYPES = ("accountClassTransfer", "cStakingTransfer", "liquidation")
MODE_STANDARD = ("default", "disabled", "dexabstraction", "standard")
MODE_UNIFIED = ("unifiedaccount", "portfoliomargin", "unified")
_DEX_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


class Budget(Exception):
    pass


class MetaHold(RuntimeError):
    pass


class HLError(RuntimeError):
    def __init__(self, code, msg, retry_after=None):
        super().__init__(f"HTTP {code} {msg}")
        self.code, self.retry_after = code, retry_after


def _http_default(url, body=None, timeout=20):
    import perp_dex
    try:
        return perp_dex._http_default(url, body, timeout)
    except perp_dex.PerpHTTPError as e:
        raise HLError(e.code, str(e), e.retry_after) from None


HTTP = _http_default
SLEEP = time.sleep
CLOCK = time.time


def settings(cfg) -> dict:
    s = (cfg or {}).get("hyperliquid")
    return s if isinstance(s, dict) else {}


def enabled(cfg) -> bool:
    return bool(settings(cfg).get("spot"))


def addresses(cfg) -> list:
    if not enabled(cfg):
        return []
    try:
        import perp_dex
        lst = [a["address"].lower() for a in (perp_dex.configured(cfg).get(VENUE) or [])]
    except Exception:
        return []
    ex = {str(x).lower() for x in (settings(cfg).get("spot_exclude") or []) if isinstance(x, str)}
    out = []
    for a in lst:
        if re.fullmatch(r"0x[0-9a-f]{40}", a) and a not in ex and a not in out:
            out.append(a)
    return out


def known_addresses(cfg, state=None) -> set:
    out = set(addresses(cfg))
    try:
        st = state if state is not None else (common.read_json(os.path.join(common.STATE_DIR, "exf_state.json"), {}) or {})
        hs = st.get(VENUE) if isinstance(st, dict) else None
        if isinstance(hs, dict):
            out |= {a for a in (hs.get("ever") or []) if isinstance(a, str) and re.fullmatch(r"0x[0-9a-f]{40}", a)}
            out |= {a for a in (hs.get("hl") or {}) if isinstance(a, str) and re.fullmatch(r"0x[0-9a-f]{40}", a)}
    except (Exception, SystemExit):
        pass
    return out


def window_t0(cfg, now=None) -> int:
    now = time.time() if now is None else now
    if (cfg or {}).get("backfill_full_history"):
        return 0
    months = float((cfg or {}).get("backfill_months") or 5)
    t = int(now - months * 30 * 86400)
    try:
        import bf_engine
        vals = [v for v in (bf_engine.SINCE.target(None), bf_engine.SINCE.target(VENUE)) if v]
    except Exception:
        vals = []
    return int(min([t] + [int(v) for v in vals]))


class Gov:

    def __init__(self, cap=WEIGHT_CAP_MIN, pace=PACE):
        self.cap, self.pace = int(cap), float(pace)
        self.q = collections.deque()
        self.last = 0.0
        self.lock = threading.Lock()
        self.calls = 0
        self.weight = 0

    def _used(self, now):
        while self.q and self.q[0][0] <= now - 60:
            self.q.popleft()
        return sum(e[1] for e in self.q)

    def admit(self, w, deadline, pace=None, reserve=0):
        w, rs = int(w), max(0, int(reserve))
        pc = self.pace if pace is None else float(pace)
        while True:
            if CLOCK() > deadline:
                raise Budget()
            with self.lock:
                now = CLOCK()
                used = self._used(now)
                gap = (pc - (now - self.last)) if (self.last and pc > 0) else 0.0
                if used + w + rs <= self.cap and gap <= 0:
                    self.last = now
                    e = [now, w + rs]
                    self.q.append(e)
                    self.calls += 1
                    self.weight += w
                    return e
                wait = gap
                if used + w + rs > self.cap and self.q:
                    wait = max(wait, self.q[0][0] + 60.05 - now)
            if CLOCK() + wait > deadline:
                raise Budget()
            SLEEP(max(0.01, wait))

    def settle(self, e, w, base=0):
        with self.lock:
            e[1] = int(w)
            self.weight += max(0, int(w) - int(base))

    def used_now(self):
        with self.lock:
            return self._used(CLOCK())


GOV = Gov()
_GATE = {"fail": 0, "until": 0.0, "why": ""}


def gate_open(now=None):
    return (now or CLOCK()) >= float(_GATE.get("until") or 0)


def _gate_fail(e, now=None):
    now = now or CLOCK()
    _GATE["fail"] = int(_GATE.get("fail") or 0) + 1
    code = getattr(e, "code", None)
    if code == 429:
        try:
            wait = max(60.0, float(getattr(e, "retry_after", None) or 0))
        except (TypeError, ValueError):
            wait = 60.0
    elif code in (401, 403):
        wait = 6 * 3600.0
    else:
        wait = float(min(BACKOFF_MAX, 60 * 2 ** min(10, _GATE["fail"] - 1)))
    _GATE["until"] = now + wait
    _GATE["why"] = common.safe_err(e)[:160]
    return wait


def call(body, deadline, gov=None):
    gov = gov or GOV
    typ = str(body.get("type") or "")
    base = WEIGHTS.get(typ, 20)
    e = gov.admit(base, deadline, reserve=RESERVE.get(typ, 0))
    r = None
    try:
        r = HTTP(HL_URL, body)
    finally:
        if typ in RESERVE:
            gov.settle(e, base + (len(r) // EXTRA_PER.get(typ, 20) if isinstance(r, list) else 0), base)
    return r


def pair_for(meta, key):
    best = None
    for pn, (b, q) in (meta.pairs or {}).items():
        if b != key or q not in QUOTE_PREF or not (pn.startswith("@") or "/" in pn):
            continue
        rk = QUOTE_PREF.index(q)
        if best is None or rk < best[0]:
            best = (rk, pn, q)
    return (best[1], best[2]) if best else (None, None)


def _daily_rows(coin, t0, t1, deadline):
    r = call({"type": "candleSnapshot", "req": {"coin": coin, "interval": "1d", "startTime": int(t0) * 1000, "endTime": int(t1) * 1000}}, deadline)
    out = []
    for c in r if isinstance(r, list) else ():
        try:
            row = [int(c["t"]) // 1000, float(c["o"]), float(c["h"]), float(c["l"]), float(c["c"]), float(c.get("v") or 0)]
        except (KeyError, TypeError, ValueError):
            continue
        if all(math.isfinite(x) for x in row[1:5]) and row[4] > 0 and row[1] > 0:
            out.append(row)
    return sorted(out)


def daily_candles(key, t0, t1, now=None, budget=30.0):
    import candles
    now = now or CLOCK()
    dl = CLOCK() + float(budget)
    try:
        meta = load_meta(dl, now)
        coin, q = pair_for(meta, str(key or "").upper())
        if not coin:
            return candles.Result(why="no_market", note=f"Hyperliquid 현물 페어 없음({str(key)[:24]})")
        rows = _daily_rows(coin, t0, t1, dl)
        if rows and q != "USDC":
            qc, qq = pair_for(meta, q)
            if not qc or qq != "USDC":
                return candles.Result(why="no_market", note=f"Hyperliquid {q} 의 USDC 페어 없음")
            qr = {r9[0]: r9[4] for r9 in _daily_rows(qc, t0, t1, dl)}
            rows = [[t9, o9 * qr[t9], h9 * qr[t9], l9 * qr[t9], c9 * qr[t9], v9] for t9, o9, h9, l9, c9, v9 in rows if qr.get(t9)]
        return candles.Result(candles=rows or None, why=None if rows else "no_data", calls=1)
    except Budget:
        return candles.Result(why="budget", note="Hyperliquid 무게 예산")
    except Exception as e:
        return candles.Result(why="net", note=common.safe_err(e)[:120])


def _dec(v):
    if isinstance(v, bool) or v is None:
        return None
    try:
        d = Decimal(str(v).strip())
    except (InvalidOperation, ValueError):
        return None
    if not d.is_finite() or abs(d) > AMT_MAX:
        return None
    return d


def _ds(d) -> str:
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def tok_name(v) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(v or ""))[:20].upper()


def _addr(v) -> str:
    s = str(v or "").strip().lower()
    return s if re.fullmatch(r"0x[0-9a-f]{40}", s) else ""


def _a8(addr) -> str:
    return addr[2:10]


def _iso(ms) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(int(ms) / 1000.0)) + "+00:00"


def _sys_addr(a) -> bool:
    return a == SYS_HYPE or bool(_SYS_RE.match(a or ""))


def _ms_ok(t, now_ms=None) -> bool:
    now_ms = now_ms or int(CLOCK() * 1000)
    return isinstance(t, int) and T_MIN_MS <= t <= now_ms + 86400 * 1000


def meta_path() -> str:
    return os.path.join(common.STATE_DIR, "hl_spot_meta.json")


PINNED = {"USDC": 0, "PURR": 1, "HYPE": 150, "UBTC": 197, "UETH": 221, "USDE": 235, "USOL": 254, "USDT0": 268, "UFART": 269,
          "XAUT0": 297, "UPUMP": 299, "UENA": 338, "LINK0": 341, "UXPL": 343, "AAVE0": 346, "USDH": 360, "UZEC": 419}


class Meta:

    def __init__(self, raw: dict, ts: float = 0.0):
        self.ts = float(ts or 0)
        self.names, self.tids = {}, {}
        for t in (raw or {}).get("tokens") or []:
            if not isinstance(t, dict):
                continue
            try:
                i = int(t.get("index"))
            except (TypeError, ValueError):
                continue
            n = tok_name(t.get("name"))
            if n:
                self.names[i] = n
                tid = str(t.get("tokenId") or "").lower()
                if re.fullmatch(r"0x[0-9a-f]{32}", tid):
                    self.tids[tid] = i
        by = {}
        for i, n in self.names.items():
            by.setdefault(n, []).append(i)
        self.dup = {n for n, ix in by.items() if len(ix) > 1}
        self.uniq = {n: ix[0] for n, ix in by.items() if len(ix) == 1}
        self.keys = {i: (n if PINNED.get(n) == i else f"{n}@{i}") for i, n in self.names.items()}
        self.pairs, self.pair_names = {}, {}
        for u in (raw or {}).get("universe") or []:
            if not isinstance(u, dict):
                continue
            tk = u.get("tokens") or []
            if not (isinstance(tk, list) and len(tk) == 2):
                continue
            try:
                b, q = int(tk[0]), int(tk[1])
            except (TypeError, ValueError):
                continue
            if b in self.keys and q in self.keys:
                kv, nv = (self.keys[b], self.keys[q]), (self.names[b], self.names[q])
                nm = str(u.get("name") or "")
                if nm:
                    self.pairs[nm], self.pair_names[nm] = kv, nv
                try:
                    k9 = f"@{int(u.get('index'))}"
                    if k9 not in self.pairs:
                        self.pairs[k9], self.pair_names[k9] = kv, nv
                except (TypeError, ValueError):
                    pass
        self.ok = bool(self.names) and bool(self.pairs)

    def pair(self, coin):
        return self.pairs.get(str(coin or ""))

    def key(self, idx):
        try:
            return self.keys.get(int(idx))
        except (TypeError, ValueError):
            return None

    def name(self, idx=None, coin=None):
        k = self.key(idx) if idx is not None else None
        return k or tok_name(coin)

    def ledger_key(self, token):
        t = str(token or "")
        if ":" in t:
            _nm, tid = t.split(":", 1)
            i = self.tids.get(tid.strip().lower())
            return (self.keys.get(i), None) if i is not None else (None, "miss")
        n = tok_name(t)
        if not n:
            return None, "miss"
        if n in self.dup:
            return None, "ambig"
        i = self.uniq.get(n)
        return (self.keys.get(i), None) if i is not None else (None, "miss")


_META = {"m": None, "forced": 0.0}


def load_meta(deadline=None, now=None, force=False, fetch=True) -> Meta:
    now = now or CLOCK()
    m = _META.get("m")
    if m is not None and m.ok and now - m.ts < META_TTL and not force:
        return m
    if not force:
        try:
            d = common.read_json(meta_path(), {}) if os.path.exists(meta_path()) else {}
        except (Exception, SystemExit):
            d = {}
        if isinstance(d, dict) and d.get("raw") and now - float(d.get("ts") or 0) < META_TTL:
            m2 = Meta(d["raw"], d.get("ts"))
            if m2.ok:
                _META["m"] = m2
                return m2
    if not fetch:
        return m if m is not None else Meta({}, 0)
    if force and now - float(_META.get("forced") or 0) < META_RETRY and m is not None and m.ok:
        return m
    raw = call({"type": "spotMeta"}, deadline if deadline is not None else now + 60)
    m3 = Meta(raw if isinstance(raw, dict) else {}, now)
    if not m3.ok:
        raise ValueError("spotMeta 응답 형식 오류")
    _META["m"] = m3
    if force:
        _META["forced"] = now
    try:
        common.atomic_write_json(meta_path(), {"v": 1, "ts": int(now), "raw": {"tokens": [
            {"name": t.get("name"), "index": t.get("index"), "tokenId": t.get("tokenId")} for t in raw.get("tokens") or [] if isinstance(t, dict)],
            "universe": [{"name": u.get("name"), "index": u.get("index"), "tokens": u.get("tokens")}
                         for u in raw.get("universe") or [] if isinstance(u, dict)]}})
    except Exception as e:
        log.warning("HL spotMeta 캐시 저장 실패: %s", repr(e)[:120])
    return m3


def parse_mode(r):
    v = r
    if isinstance(r, dict):
        v = r.get("abstraction") if r.get("abstraction") is not None else (r.get("mode") if r.get("mode") is not None else r.get("type"))
    if not isinstance(v, str):
        return None
    k = v.strip().lower().replace("_", "")
    if k in MODE_STANDARD:
        return "standard"
    if k in MODE_UNIFIED:
        return "unified"
    return None


def parse_dexes(r):
    if not isinstance(r, list):
        return None
    out = []
    for e in r:
        if e is None:
            continue
        if not isinstance(e, dict) or not _DEX_RE.match(str(e.get("name") or "")):
            return None
        out.append(str(e["name"]))
    return out


def load_dexes(deadline, now=None):
    now = now or CLOCK()
    c = _META.get("dexes")
    if c and now - c[0] < META_TTL:
        return list(c[1])
    lst = parse_dexes(call({"type": "perpDexs"}, deadline))
    if lst is None:
        raise ValueError("perpDexs 응답 형식 오류")
    _META["dexes"] = (now, lst)
    return list(lst)


def dex_collateral(name, meta, deadline, now=None):
    if not name:
        return "USDC"
    now = now or CLOCK()
    cc = _META.setdefault("coll", {})
    c = cc.get(name)
    if c and now - c[0] < META_TTL:
        return c[1]
    r = call({"type": "meta", "dex": name}, deadline)
    idx = (r or {}).get("collateralToken") if isinstance(r, dict) else None
    tok = meta.key(idx) if isinstance(idx, int) and not isinstance(idx, bool) else None
    cc[name] = (now, tok)
    return tok


def led_uid(addr, u) -> str:
    me = _a8(addr)
    if not isinstance(u, dict):
        return f"u:{me}:x:" + hashlib.sha1(repr(u).encode()).hexdigest()[:16]
    d = u.get("delta") if isinstance(u.get("delta"), dict) else {}
    h = str(u.get("hash") or "")
    hx = h.lower()[2:14] if re.fullmatch(r"0x[0-9a-fA-F]{64}", h) else "nohash"
    sig = hashlib.sha1(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:12]
    return f"u:{me}:{re.sub('[^0-9]', '', str(u.get('time')))[:16]}:{hx}:{re.sub('[^A-Za-z]', '', str(d.get('type')))[:24]}:{sig}"


def hl_book(meta: Meta, mids: dict) -> dict:
    best = {}
    for pn, (b, q) in (meta.pairs or {}).items():
        if not pn.startswith("@") and "/" not in pn:
            continue
        v = _dec((mids or {}).get(pn))
        if v is None or v <= 0:
            continue
        rk = QUOTE_PREF.index(q) if q in QUOTE_PREF else None
        if rk is None:
            continue
        cur = best.get(b)
        if cur is None or rk < cur[0]:
            best[b] = (rk, q, float(v))
    out = {"USDC": 1.0}
    for b, (rk, q, v) in best.items():
        if b == "USDC":
            continue
        if q == "USDC":
            out[b] = v
    for b, (rk, q, v) in best.items():
        if q != "USDC" and b not in out:
            qv = out.get(q)
            if qv:
                out[b] = v * qv
    return {k: v for k, v in out.items() if math.isfinite(v) and v > 0}


def venue_prices(hl: dict, book, cg=None, notes=None) -> dict:
    out = {}
    names = set(hl or {}) | set(SAME_COIN)
    for n in sorted(names):
        mid = (hl or {}).get(n)
        if n in STABLE_FACE:
            out[n] = (1.0, "face")
            continue
        m = SAME_COIN.get(n)
        if m:
            sym, cid = m
            got = None
            if sym in STABLE_FACE:
                got = (1.0, "face")
            for ex in ([] if got else PX_ORDER):
                v = (book(ex) or {}).get(sym) if book else None
                try:
                    v = float(v) if v is not None else None
                except (TypeError, ValueError):
                    v = None
                if not v or not math.isfinite(v) or v <= 0:
                    continue
                if mid and not (IDENT_LO <= v / mid <= IDENT_HI):
                    if notes is not None:
                        notes.setdefault(n, []).append(f"{ex} {sym} 시세가 HL 중간가의 {v / mid:.2f}배 — 제외")
                    continue
                got = (v, ex)
                break
            if got is None and cid and cg:
                v = (cg([cid]) or {}).get(cid)
                if v and math.isfinite(v) and v > 0 and (not mid or IDENT_LO <= v / mid <= IDENT_HI):
                    got = (float(v), "coingecko")
                elif v and notes is not None:
                    notes.setdefault(n, []).append(f"코인게코 {cid} 시세가 HL 중간가와 어긋남 — 제외")
            if got:
                out[n] = got
                continue
        if mid:
            out[n] = (float(mid), "hyperliquid")
    return out


def fetch_book(now=None, deadline=None) -> dict:
    now = now or CLOCK()
    dl = deadline if deadline is not None else now + 30
    meta = load_meta(dl, now)
    mids = call({"type": "allMids"}, dl)
    return hl_book(meta, mids if isinstance(mids, dict) else {})


def norm_row(native_id, currency, amount, fee, txid, state, t_ms, address=None, network=None, extra=None) -> dict:
    r = {"uuid": f"{VENUE}:{native_id}", "currency": str(currency or "").upper(), "amount": str(amount or "0"),
         "fee": str(fee or "0"), "txid": str(txid or ""), "state": state, "created_at": _iso(t_ms), "done_at": _iso(t_ms)}
    for k, v in (("address", address), ("network", network)):
        if v not in (None, "") and str(v).strip():
            r[k] = str(v).strip()
    if extra:
        r.update(extra)
    return r


def map_fill(addr: str, f: dict, meta: Meta, now_ms=None):
    coin = str(f.get("coin") or "")
    if not (coin.startswith("@") or "/" in coin):
        return None
    pr = meta.pair(coin)
    if pr is None:
        raise KeyError(coin)
    base, quote = pr
    side = {"B": "buy", "A": "sell"}.get(str(f.get("side") or ""))
    px, sz, fee = _dec(f.get("px")), _dec(f.get("sz")), _dec(f.get("fee") if f.get("fee") not in (None, "") else "0")
    try:
        t = int(f.get("time"))
    except (TypeError, ValueError):
        t = None
    tid = re.sub(r"[^0-9A-Za-z]", "", str(f.get("tid") or ""))[:40]
    if side is None or px is None or px <= 0 or sz is None or sz <= 0 or fee is None or not _ms_ok(t, now_ms) or not tid:
        raise ValueError(f"HL 체결 형식 오류({coin})")
    fn, (nb, nq) = tok_name(f.get("feeToken")), (meta.pair_names.get(coin) or (base, quote))
    if nb == nq or not fn:
        fee_ccy = base if side == "buy" else quote
    else:
        fee_ccy = base if fn == nb else quote if fn == nq else (meta.ledger_key(fn)[0] or (base if side == "buy" else quote))
    return {"id": f"{VENUE}:{_a8(addr)}:{tid}:{side[0]}", "ts": t, "base": base, "quote": quote, "side": side,
            "price": _ds(px), "qty": _ds(sz), "fee": _ds(fee), "fee_ccy": fee_ccy if fee != 0 else ""}


def map_ledger(addr: str, u: dict, tracked: set, now_ms=None, meta=None):
    me = addr.lower()
    d = u.get("delta") if isinstance(u.get("delta"), dict) else {}
    typ = str(d.get("type") or "")
    try:
        t = int(u.get("time"))
    except (TypeError, ValueError):
        return "unk", "시각 없음"
    if not _ms_ok(t, now_ms):
        return "unk", "시각 범위 밖"
    h = str(u.get("hash") or "")
    hx = h.lower() if re.fullmatch(r"0x[0-9a-fA-F]{64}", h) else ""
    if hx and int(hx, 16) == 0:
        hx = ""

    def row(kind, cur, amt, fee=None, txid="", net=None, peer=None, tok=False):
        if tok:
            if meta is None:
                cur = tok_name(cur)
            else:
                cur, why9 = meta.ledger_key(cur)
                if why9 == "miss":
                    return "meta", f"{typ} 모르는 토큰({str(d.get('token'))[:40]})"
                if cur is None:
                    return "unk", f"{typ} 동명 토큰(어느 번호인지 모름)"
        a = _dec(amt)
        f9 = _dec(fee) if fee not in (None, "") else Decimal(0)
        if not cur or a is None or a <= 0:
            return "unk", f"{typ} 금액·통화 형식 오류"
        f9 = f9 if (f9 is not None and f9 >= 0) else Decimal(0)
        nid = f"{_a8(me)}:{t}:{(hx[2:14] if hx else 'nohash')}:{re.sub('[^A-Za-z]', '', typ)[:24]}:{cur}:{kind}:{_ds(a)}"
        ex9 = {"hl_type": typ}
        if hx and not txid:
            ex9["hl_hash"] = hx
        r = norm_row(nid, cur, _ds(a), _ds(f9), txid, "ACCEPTED" if kind == "d" else "DONE", t,
                     address=(peer if kind == "w" else None), network=net, extra=ex9)
        if kind == "d" and peer:
            r["from"] = peer
        return kind, r

    if typ in INTERNAL_TYPES:
        return ("stake" if typ == "cStakingTransfer" else "skip"), typ
    if typ == "deposit":
        return row("d", "USDC", d.get("usdc"), txid=hx, net="arbitrum", peer=BRIDGE2)
    if typ == "withdraw":
        return row("w", "USDC", d.get("usdc"), fee=d.get("fee"), txid="", net="arbitrum")
    if typ in ("internalTransfer", "subAccountTransfer", "spotTransfer", "send"):
        snd, rcv = _addr(d.get("user")), _addr(d.get("destination"))
        if typ == "send" and snd == rcv == me:
            return "skip", "send(같은 주소 — 현물↔무기한)"
        usdc_kind = typ in ("internalTransfer", "subAccountTransfer")
        cur = "USDC" if usdc_kind else d.get("token")
        amt = d.get("usdc") if usdc_kind else d.get("amount")
        if snd == me and rcv in tracked or rcv == me and snd in tracked:
            return "skip", f"{typ}(등록한 HL 주소끼리)"
        if snd == me:
            peer = rcv
            net = "hyperevm" if _sys_addr(peer) else "hypercore"
            fee = d.get("fee") if usdc_kind else None
            return row("w", cur, amt, fee=fee, txid=hx, net=net, peer=peer, tok=not usdc_kind)
        if rcv == me:
            peer = snd
            net = "hyperevm" if _sys_addr(peer) else "hypercore"
            a = _dec(amt)
            if usdc_kind and a is not None:
                f9 = _dec(d.get("fee")) or Decimal(0)
                if Decimal(0) < f9 < a:
                    amt = a - f9
            return row("d", cur, amt, txid=hx, net=net, peer=peer, tok=not usdc_kind)
        return "unk", f"{typ}(보낸·받은 주소가 이 주소 아님)"
    if typ == "spotGenesis":
        return row("d", d.get("token"), d.get("amount"), net="hypercore", peer="genesis", tok=True)
    if typ == "rewardsClaim":
        return row("d", d.get("token") or "USDC", d.get("amount"), net="hypercore", peer="rewards", tok=bool(d.get("token")))
    if typ in ("vaultDeposit", "vaultCreate"):
        return row("w", "USDC", d.get("usdc"), net="hl-vault", peer=_addr(d.get("vault")) or "vault")
    if typ == "vaultWithdraw":
        amt = d.get("netWithdrawnUsd") if d.get("netWithdrawnUsd") not in (None, "") else d.get("usdc")
        return row("d", "USDC", amt, net="hl-vault", peer=_addr(d.get("vault")) or "vault")
    if typ in ("vaultDistribution", "vaultLeaderCommission"):
        return row("d", "USDC", d.get("usdc"), net="hl-vault", peer=_addr(d.get("vault")) or "vault")
    if typ == "deployGasAuction":
        return row("w", d.get("token") or "USDC", d.get("amount"), net="hypercore", peer="gas-auction", tok=bool(d.get("token")))
    return "unk", typ or "?"


USDC_ARB = "0xaf88d065e77c8cc2239327c5edb3a432268e5831"
BRIDGE_WINDOW = 6 * 3600
BRIDGE_EARLY = 120


def match_bridge_withdrawals(wds, inflows, window=BRIDGE_WINDOW, early=BRIDGE_EARLY) -> dict:
    eps = Decimal("0.000001")
    ws = []
    for w in wds or ():
        try:
            net = Decimal(str(w["amount"])) - Decimal(str(w.get("fee") or 0))
            ws.append((int(w["ts"]), str(w["uuid"]), net))
        except (KeyError, ArithmeticError, TypeError, ValueError):
            continue
    ins = []
    for i in inflows or ():
        try:
            ins.append((int(i["ts"]), str(i["tx"]), str(i.get("loc") or ""), Decimal(str(i["qty"]))))
        except (KeyError, ArithmeticError, TypeError, ValueError):
            continue
    ws.sort()
    ins.sort()
    used, out = set(), {}
    for ts, u, net in ws:
        if net <= 0:
            continue
        for its, tx, loc, q in ins:
            if (tx, loc) in used or abs(q - net) > eps or not (-early <= its - ts <= window):
                continue
            out[u] = tx
            used.add((tx, loc))
            break
    return out


def asc_fetch(fetch, st, t0_ms, page_full, handle, t_of):
    lo = st.get("lo")
    if lo is not None and t0_ms < int(lo):
        if st.get("ext_t0") is None or int(t0_ms) < int(st["ext_t0"]):
            st["ext_t0"], st["ext_next"] = int(t0_ms), None
        start = max(int(st.get("ext_next") or t0_ms), int(t0_ms))
        done = False
        for _ in range(MAX_PAGES):
            rows = fetch(start)
            if not rows:
                done = True
                break
            for r in rows:
                if t_of(r) < int(lo):
                    handle(r, True)
            last = max(t_of(r) for r in rows)
            if last >= int(lo) or len(rows) < page_full:
                done = True
                break
            if last <= start:
                raise RuntimeError("HL 이력 커서 전진 불가(창 앞당김)")
            start = last
            st["ext_next"] = int(start)
        if not done:
            return False
        st["lo"] = int(t0_ms)
        st.pop("ext_next", None)
        st.pop("ext_t0", None)
    elif "ext_t0" in st:
        st.pop("ext_next", None)
        st.pop("ext_t0", None)
    start = int(st.get("next") or t0_ms)
    if lo is None:
        st["lo"] = int(min(start, t0_ms))
    for _ in range(MAX_PAGES):
        rows = fetch(start)
        if not rows:
            return True
        for r in rows:
            handle(r, False)
        last = max(t_of(r) for r in rows)
        if len(rows) >= page_full and last <= start:
            raise RuntimeError(f"HL 이력 커서 전진 불가 — 같은 ms {len(rows)}건")
        start = max(start, last)
        st["next"] = int(start)
        if len(rows) < page_full:
            return True
    return False


def bal_path() -> str:
    return os.path.join(common.STATE_DIR, f"exf_balances_{VENUE}.json")


def _keep_view():
    bp = bal_path()
    try:
        best = None
        for p9 in (bp, bp + ".pending"):
            if os.path.exists(p9):
                d9 = common.read_json(p9, {})
                if isinstance(d9, dict) and isinstance(d9.get("balances"), dict):
                    if best is None or float(d9.get("ts") or 0) > float(best.get("ts") or 0):
                        best = d9
        if best is None:
            return
        cur9 = common.read_json(bp + ".view", {}) if os.path.exists(bp + ".view") else {}
        if not isinstance(cur9, dict) or float(best.get("ts") or 0) >= float(cur9.get("ts") or 0):
            common.atomic_write_json(bp + ".view", best)
    except (Exception, SystemExit) as e:
        log.warning("HL 잔고 표시 사본 보존 실패: %s", repr(e)[:120])


def invalidate_balance():
    _keep_view()
    for p in (bal_path(), bal_path() + ".pending"):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass


def _cash(ch):
    ms = ch.get("marginSummary") if isinstance(ch, dict) else None
    av = _dec((ms or {}).get("accountValue"))
    if av is None or not isinstance(ch.get("assetPositions", []), list):
        raise ValueError("clearinghouseState 형식 오류")
    upnl, npos = Decimal(0), 0
    for ap in ch.get("assetPositions") or []:
        p = (ap or {}).get("position") or {}
        u9 = _dec(p.get("unrealizedPnl"))
        if u9 is None:
            raise ValueError("clearinghouseState 포지션 형식 오류")
        upnl += u9
        if (_dec(p.get("szi")) or 0) != 0:
            npos += 1
    return av - upnl, (av != 0 or npos > 0), npos


def fetch_balances(addr: str, meta: Meta, deadline, ast: dict, now=None):
    now = int(now or CLOCK())
    out, ok, why = {}, True, ""
    sp = call({"type": "spotClearinghouseState", "user": addr}, deadline) or {}
    if not isinstance(sp, dict) or not isinstance(sp.get("balances"), list):
        raise ValueError("spotClearinghouseState 형식 오류")
    for b in sp["balances"]:
        if not isinstance(b, dict):
            raise ValueError("HL 현물 잔고 행 형식 오류")
        n = meta.key(b.get("token"))
        v = _dec(b.get("total"))
        if v is None:
            raise ValueError("HL 현물 잔고 행 형식 오류")
        if not n:
            if v != 0:
                load_meta(deadline, now, force=True)
                raise ValueError(f"HL 모르는 토큰 번호 {str(b.get('token'))[:12]} — spotMeta 갱신 후 다음 주기")
            continue
        if v != 0:
            out[n] = out.get(n, Decimal(0)) + v
    mode = parse_mode(call({"type": "userAbstraction", "user": addr}, deadline))
    ast["mode"], ast["mode_at"] = (mode or "?"), now
    if mode in ("standard", "unified"):
        full = mode == "unified" or now - int(ast.get("dex_scan_at") or 0) >= DEX_SCAN_SEC
        names = [""] + (load_dexes(deadline, now) if full else sorted(set(ast.get("dex_active") or []) | set(ast.get("dex_seen") or [])))
        active = set()
        for nm in names:
            ch = call({"type": "clearinghouseState", "user": addr, **({"dex": nm} if nm else {})}, deadline) or {}
            if mode == "unified":
                aps = ch.get("assetPositions") if isinstance(ch, dict) else None
                if not isinstance(aps, list):
                    ok, why = False, f"통합 계정 {nm or '기본'} DEX 포지션 형식 오류"
                    continue
                if any((_dec(((ap or {}).get("position") or {}).get("szi")) or 0) != 0 for ap in aps):
                    if nm:
                        active.add(nm)
                    ok, why = False, f"통합 계정 무기한 포지션 보유({nm or '기본'} DEX) — 미실현 손익이 현물 잔고에 섞여 대사 보류"
                continue
            cash, used, _npos = _cash(ch)
            if nm and used:
                active.add(nm)
            if cash == 0:
                continue
            coll = dex_collateral(nm, meta, deadline, now)
            if not coll:
                ok, why = False, f"퍼프 DEX {nm} 담보 토큰 미상"
                continue
            out[coll] = out.get(coll, Decimal(0)) + cash
            ast.setdefault("cash_syms", [])
            if coll not in ast["cash_syms"]:
                ast["cash_syms"].append(coll)
        ast["dex_active"] = sorted(active)
        ast["dex_seen"] = []
        if full:
            ast["dex_scan_at"] = now
    elif mode is None:
        ok, why = False, "계정 모드 미상(userAbstraction)"
    tot = Decimal(0)
    ds = call({"type": "delegatorSummary", "user": addr}, deadline)
    bad9 = not isinstance(ds, dict)
    if not bad9:
        for k in ("delegated", "undelegated", "totalPendingWithdrawal"):
            v = _dec(ds.get(k))
            if v is None or v < 0:
                bad9 = True
                break
            tot += v
    if bad9:
        ok, why, tot = False, "delegatorSummary 형식 오류", Decimal(0)
    if tot:
        out["HYPE"] = out.get("HYPE", Decimal(0)) + tot
    return out, [f"spot:{_a8(addr)}", f"perp:{_a8(addr)}", f"stake:{_a8(addr)}"], ok, why


def run_pass(state: dict, writer, cfg: dict, now=None, save=None, budget=None) -> str:
    addrs = addresses(cfg)
    if not addrs:
        return "off"
    now = int(now or CLOCK())
    if not gate_open():
        return "대기(백오프): " + str(_GATE.get("why") or "")[:80]
    if budget is None:
        nd9 = len((_META.get("dexes") or (0, [None] * 8))[1])
        est9 = len(addrs) * (100 + 2 * (1 + nd9))
        budget = min(240.0, max(float(CYCLE_BUDGET), 60.0 * est9 / WEIGHT_CAP_MIN + 30.0))
    deadline = CLOCK() + float(budget)
    hs = state.setdefault(VENUE, {"seen": {}, "backfilled_until": 0})
    hs.setdefault("seen", {})
    first_mem = "member" not in hs
    ever9 = hs.setdefault("ever", [])
    ever9 += [a for a in addresses(cfg) if a not in ever9]
    mem9 = hs.setdefault("member", {})
    for a in ever9:
        iv9 = mem9.setdefault(a, [])
        if not iv9 or iv9[-1][1] is not None:
            iv9.append([0 if first_mem else int(now), None])
    fst = hs.setdefault("fills", {})
    per = hs.setdefault("hl", {})
    t0_ms = window_t0(cfg, now) * 1000
    now_ms = now * 1000
    try:
        M = [load_meta(deadline, now)]
    except Budget:
        invalidate_balance()
        return "예산 소진(spotMeta)"
    except Exception as e:
        w = _gate_fail(e)
        invalidate_balance()
        log.warning("HL spotMeta 실패 → %d초 대기: %s", int(w), common.safe_err(e)[:120])
        return "실패(spotMeta)"
    tracked = set(addrs)

    def own_at(me, t_ms):
        t9 = int(t_ms) // 1000

        def mem(a):
            return any(int(s9) <= t9 and (e9 is None or t9 < int(e9)) for s9, e9 in (mem9.get(a) or ()))
        if not mem(me):
            return set()
        return {a for a in mem9 if mem(a)}
    seen_l = hs.setdefault("seen_led", {})
    seen_f = fst.setdefault("seen", {})
    work = {}
    ok_all, partial, http_err = True, None, None
    bal_why = []
    unk = collections.Counter()
    pass_ids = set()
    rr9 = int(hs.get("rr") or 0) % len(addrs)
    stop_at = None
    for a in addrs[rr9:] + addrs[:rr9]:
        ast = json.loads(json.dumps(per.get(a) or {}))
        a_deps, a_wds, a_fills, a_uids = [], [], [], []
        la = ast.get("bal_at")
        lim_ms = (int(la) - LATE_MARGIN) * 1000 if la else None

        def late(t_ms, lim_ms=lim_ms):
            return lim_ms is not None and t_ms < lim_ms

        def on_led(u, ext, a=a, a_deps=a_deps, a_wds=a_wds, a_uids=a_uids, ast=ast):
            uid = led_uid(a, u)
            if uid in seen_l:
                seen_l[uid] = now_ms
                return
            if uid in pass_ids:
                return
            pass_ids.add(uid)
            a_uids.append(uid)
            if not isinstance(u, dict):
                unk["형식 오류"] += 1
                return
            d9 = u.get("delta") if isinstance(u.get("delta"), dict) else {}
            if d9.get("type") == "send":
                for k9 in ("sourceDex", "destinationDex"):
                    v9 = str(d9.get(k9) or "")
                    if v9 and v9 != "spot" and _DEX_RE.match(v9):
                        ast.setdefault("dex_seen", [])
                        if v9 not in ast["dex_seen"]:
                            ast["dex_seen"].append(v9)
            own9 = own_at(a, int(u.get("time") or 0)) if isinstance(u.get("time"), (int, float)) else set()
            k, r = map_ledger(a, u, own9, now_ms, M[0])
            if k == "meta":
                t9 = int(u.get("time"))
                if M[0].ts * 1000 < t9 + 60000:
                    m2 = load_meta(deadline, now, force=True)
                    if m2 is M[0] or m2.ts * 1000 < t9:
                        raise MetaHold(r)
                    M[0] = m2
                    k, r = map_ledger(a, u, own9, now_ms, M[0])
                if k == "meta":
                    unk[str(r)[:40]] += 1
                    return
            if k in ("stake", "skip"):
                return
            if k == "unk":
                unk[str(r)[:40]] += 1
                return
            if late(int(u.get("time"))):
                r["late"] = 1
            (a_deps if k == "d" else a_wds).append(r)

        def on_fill(f, ext, a=a, a_fills=a_fills):
            if not isinstance(f, dict):
                unk["형식 오류"] += 1
                return
            try:
                r = map_fill(a, f, M[0], now_ms)
            except ValueError as e9:
                unk[str(e9)[:40]] += 1
                return
            if r is None:
                return
            if r["id"] in seen_f:
                seen_f[r["id"]] = now_ms
                return
            if r["id"] in pass_ids:
                return
            pass_ids.add(r["id"])
            if late(r["ts"]):
                r["late"] = 1
            a_fills.append(r)

        led_st, fil_st = ast.setdefault("led", {}), ast.setdefault("fil", {})
        try:
            d1 = asc_fetch(lambda s, a=a: call({"type": "userNonFundingLedgerUpdates", "user": a, "startTime": int(s)}, deadline) or [],
                           led_st, t0_ms, LEDGER_FULL, on_led, lambda r: int((r or {}).get("time") or 0) if isinstance(r, dict) else 0)
            try:
                d2 = asc_fetch(lambda s, a=a: call({"type": "userFillsByTime", "user": a, "startTime": int(s), "aggregateByTime": False},
                                                   deadline) or [], fil_st, t0_ms, FILLS_PAGE, on_fill, lambda r: int((r or {}).get("time") or 0))
            except KeyError as e9:
                M[0] = load_meta(deadline, now, force=True)
                raise RuntimeError(f"HL 모르는 현물 페어 {str(e9)[:20]} — spotMeta 갱신 후 다음 주기") from None
        except Budget:
            partial = "예산 소진"
            ast["led_done"] = ast["fil_done"] = False
            work[a] = (ast, a_deps, a_wds, a_fills, None, None, a_uids)
            ok_all = False
            stop_at = a
            break
        except HLError as e:
            ok_all = False
            if e.code in (401, 403, 429):
                http_err = e
                stop_at = a
                break
            log.warning("HL %s… 수집 실패(이 주소만 — 다음 주기 같은 지점부터): %s", a[:6], common.safe_err(e)[:140])
            continue
        except Exception as e:
            ok_all = False
            log.warning("HL %s… 수집 실패(이 주소만 — 다음 주기 같은 지점부터): %s", a[:6], common.safe_err(e)[:140])
            continue
        ast["led_done"], ast["fil_done"] = bool(d1), bool(d2)
        if not (d1 and d2):
            partial = partial or "쪽 상한"
            work[a] = (ast, a_deps, a_wds, a_fills, None, None, a_uids)
            continue
        try:
            b9, s9, ok9, why9 = fetch_balances(a, M[0], deadline, ast, now)
            ast["last_bal"] = {k: _ds(v) for k, v in b9.items() if v != 0}
            if not ok9:
                bal_why.append(f"{a[:6]}…: {why9}")
                b9 = None
            work[a] = (ast, a_deps, a_wds, a_fills, b9, s9, a_uids)
        except Budget:
            partial = "예산 소진(잔고)"
            work[a] = (ast, a_deps, a_wds, a_fills, None, None, a_uids)
            ok_all = False
            stop_at = a
            break
        except HLError as e:
            work[a] = (ast, a_deps, a_wds, a_fills, None, None, a_uids)
            ok_all = False
            if e.code in (401, 403, 429):
                http_err = e
                stop_at = a
                break
            bal_why.append(f"{a[:6]}…: {common.safe_err(e)[:80]}")
        except Exception as e:
            work[a] = (ast, a_deps, a_wds, a_fills, None, None, a_uids)
            bal_why.append(f"{a[:6]}…: {common.safe_err(e)[:80]}")
    if stop_at is not None:
        hs["rr"] = addrs.index(stop_at)
    deps = [r for v in work.values() for r in v[1]]
    wds = [r for v in work.values() for r in v[2]]
    fills = [r for v in work.values() for r in v[3]]
    uids = [u for v in work.values() for u in v[6]]
    moved = bool(deps or wds or fills or uids)
    streams_done = (ok_all and http_err is None and len(work) == len(addrs)
                    and all(v[0].get("led_done") and v[0].get("fil_done") for v in work.values()))
    stg_path = os.path.join(common.STATE_DIR, "hl_late_stage.json")
    try:
        stg = common.read_json(stg_path, {}) if os.path.exists(stg_path) else {}
    except SystemExit:
        stg = {}
    stg_rows = stg.get("rows") if isinstance(stg.get("rows"), dict) else {}
    stg_dirty = any(a not in tracked for a in stg_rows)
    stg_rows = {a: v for a, v in stg_rows.items() if a in tracked}
    n_late = sum(1 for r in deps + wds + fills if r.get("late"))
    if n_late and not streams_done:
        for a, v in work.items():
            for k9, lst in (("d", v[1]), ("w", v[2]), ("f", v[3])):
                for r in lst:
                    if r.get("late"):
                        stg_rows.setdefault(a, {}).setdefault(k9, {})[str(r.get("uuid") or r.get("id"))] = r
        deps = [r for r in deps if not r.get("late")]
        wds = [r for r in wds if not r.get("late")]
        fills = [r for r in fills if not r.get("late")]
        stg_dirty = True
    elif streams_done and stg_rows:
        have = {str(r.get("uuid") or r.get("id")) for r in deps + wds + fills}
        for v9 in stg_rows.values():
            deps += [r for k, r in (v9.get("d") or {}).items() if k not in have]
            wds += [r for k, r in (v9.get("w") or {}).items() if k not in have]
            fills += [r for k, r in (v9.get("f") or {}).items() if k not in have]
        stg_rows, stg_dirty = {}, True
    if stg_dirty and stg_rows:
        common.atomic_write_json(stg_path, {"v": 1, "rows": stg_rows})
    if deps or wds or fills:
        invalidate_balance()
        both = [("d", r) for r in deps] + [("w", r) for r in wds]
        recs = []
        for i in range(0, len(both), 500):
            ch = both[i:i + 500]
            recs.append({"v": 1, "kind": "ex_snapshot", "exchange": VENUE, "ts": now,
                         "deposits": [r for k, r in ch if k == "d"], "withdraws": [r for k, r in ch if k == "w"]})
        for i in range(0, len(fills), 500):
            recs.append({"v": 1, "kind": "exf_fills", "exchange": VENUE, "ts": now, "fills": fills[i:i + 500]})
        lc = None
        if any(r.get("late") for r in deps + wds + fills):
            lc = f"{VENUE}:{now}:{uuidlib.uuid4().hex[:10]}"
            for i, rec in enumerate(recs):
                rec.update(lb=lc, lbi=i, lbn=len(recs), lc=lc)
        for rec in recs:
            writer.append(rec)
        if lc:
            writer.append({"v": 1, "kind": "exf_late_cycle", "exchange": VENUE, "ts": now, "lc": lc})
    if stg_dirty and not stg_rows:
        try:
            os.remove(stg_path)
        except FileNotFoundError:
            pass
    for u9 in uids:
        seen_l[u9] = now_ms
    for f in fills:
        seen_f[f["id"]] = now_ms
    cut = now_ms - SEEN_KEEP_MS
    for d9 in (seen_l, seen_f):
        for k in [k for k, v in d9.items() if int(v or 0) < cut]:
            del d9[k]
    for a in [a for a in per if a not in tracked]:
        lb9 = per[a].get("last_bal")
        if isinstance(lb9, dict) and not lb9:
            del per[a]
            if a in ever9:
                ever9.remove(a)
            for iv9 in mem9.get(a) or ():
                if iv9[1] is None:
                    iv9[1] = int(now)
    for a in [a for a in ever9 if a not in tracked and a not in per]:
        ever9.remove(a)
        for iv9 in mem9.get(a) or ():
            if iv9[1] is None:
                iv9[1] = int(now)
    held = [a for a in ever9 if a not in tracked]
    for a, v in work.items():
        per[a] = v[0]
    if streams_done:
        hs["backfilled_until"] = now
        fst["backfilled_until"] = now
    complete = streams_done and all(v[4] is not None for v in work.values())
    if unk:
        u9 = dict(hs.get("unk_types") or {})
        for k, v in unk.items():
            u9[k] = int(u9.get(k) or 0) + int(v)
        hs["unk_types"] = dict(sorted(u9.items())[:40])
    if held:
        bal_why.insert(0, "HL 주소 제외됨 — 대사 보류(뺀 주소 잔고가 0 이 아님 · 다시 넣으면 풀림): " + ", ".join(a[:6] + "…" + a[-4:] for a in held))
        log.warning("hyperliquid: %s", bal_why[0])
    hs["bal_why"] = bal_why[:8]
    bal, srcs = {}, []
    if complete and not held:
        for v in work.values():
            for k, q in v[4].items():
                bal[k] = bal.get(k, Decimal(0)) + q
            srcs += v[5]
        snap = {"ts": int(CLOCK()), "balances": {k: float(v) for k, v in sorted(bal.items()) if v != 0},
                "sources": sorted(set(srcs)), "addrs": len(addrs)}
    else:
        snap = None
    bp = bal_path()
    try:
        if moved or not complete or held:
            invalidate_balance()
            if snap is not None:
                common.atomic_write_json(bp + ".view", snap)
        else:
            prev = common.read_json(bp + ".pending", {}) if os.path.exists(bp + ".pending") else {}
            pb = prev.get("balances") if isinstance(prev, dict) else None
            if isinstance(pb, dict) and (pb or not snap["balances"]) and sorted(prev.get("sources") or []) == snap["sources"]:
                common.atomic_write_json(bp, prev)
            common.atomic_write_json(bp + ".pending", snap)
            common.atomic_write_json(bp + ".view", snap)
            for a in addrs:
                per[a]["bal_at"] = snap["ts"]
    except (Exception, SystemExit) as e:
        log.warning("HL 잔고 스냅숏 기록 실패: %s", repr(e)[:140])
    try:
        cp9 = os.path.join(common.STATE_DIR, "hl_cash_syms.json")
        have9 = set((common.read_json(cp9, {}) or {}).get("syms") or []) if os.path.exists(cp9) else set()
        want9 = have9 | {"USDC"} | {c for v in per.values() for c in (v.get("cash_syms") or [])}
        if want9 != have9:
            common.atomic_write_json(cp9, {"v": 1, "syms": sorted(want9)})
    except (Exception, SystemExit) as e:
        log.warning("HL 담보 기호 기록 실패: %s", repr(e)[:120])
    if save:
        save()
    if bal_why:
        log.warning("HL 잔고 대사 후보 아님(이번 주기): %s", "; ".join(bal_why)[:300])
    if http_err is not None:
        w = _gate_fail(http_err)
        return f"한도·권한 → {int(w)}초 대기 · 입금 {len(deps)} · 출금 {len(wds)} · 체결 {len(fills)}"
    if not ok_all and not work:
        w = _gate_fail(RuntimeError("모든 주소 실패"))
        return f"전 주소 실패 → {int(w)}초 대기"
    _GATE.update(fail=0, until=0.0)
    return (f"ok 주소 {len(addrs)} · 입금 {len(deps)} · 출금 {len(wds)} · 체결 {len(fills)} · 새 갱신 {len(uids)}"
            + (f" · 대사 보류(뺀 주소 {len(held)})" if held else "")
            + (f" · 부분({partial})" if partial else "") + (" · 잔고 pending" if complete and not moved else "")
            + (" · 잔고 후보 아님" if bal_why else "") + f" · 무게/분 {GOV.used_now()}")


def status(state: dict, cfg: dict) -> dict:
    hs = (state or {}).get(VENUE) or {}
    return {"on": enabled(cfg), "addrs": len(addresses(cfg)), "backfilled_until": hs.get("backfilled_until"),
            "fills_until": (hs.get("fills") or {}).get("backfilled_until"), "unk": hs.get("unk_types") or {},
            "balWhy": hs.get("bal_why") or [], "modes": {a[:6] + "…": v.get("mode") for a, v in (hs.get("hl") or {}).items()},
            "wait": None if gate_open() else _GATE.get("why")}
