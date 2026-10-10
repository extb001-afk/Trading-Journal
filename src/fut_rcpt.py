from __future__ import annotations

import json
import math
import os
import re
import threading
from datetime import datetime, timedelta, timezone

import common

KST = timezone(timedelta(hours=9))
PX_V = 1
ROWS_MAX = 60000
KEEP_MS = 800 * 86400 * 1000
DAY_MS = 86400 * 1000
RETAIN_MS = {"binance": 90 * DAY_MS, "okx": 89 * DAY_MS}
PX_EX = ("binance", "bybit", "okx", "hyperliquid")
TRADES_MAX = 200
OPENS_MAX = 400
PX_TOL_PCT = 1.0
_COIN_RE = re.compile(r"[-_/]?(USDT|USDC|USD)([-_]?(SWAP|PERP|M))?$", re.I)
_SAFE_RE = re.compile(r"[^\w.:/-]")

OKX_OPEN = {"3": "LONG", "4": "SHORT", "206": "LONG", "207": "SHORT"}
OKX_CLOSE = {"5": "LONG", "6": "SHORT", "100": "LONG", "101": "SHORT", "102": "SHORT", "103": "LONG", "104": "LONG", "105": "SHORT",
             "106": "SHORT", "107": "LONG", "125": "LONG", "126": "SHORT", "127": "SHORT", "128": "LONG", "208": "LONG", "209": "SHORT"}
OKX_LIQ = {"100", "101", "102", "103", "104", "105", "106", "107"}
OKX_NET = {"1": ("LONG", "SHORT"), "2": ("SHORT", "LONG"), "204": ("LONG", "SHORT"), "205": ("SHORT", "LONG")}
OKX_NET_ANYTYPE = {"204", "205"}
OKX_BF_V = 3


def num(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, str) and not v.strip():
        return None
    try:
        x = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return x if math.isfinite(x) else None


def pnum(v):
    x = num(v)
    return x if x is not None and x > 0 else None


def safe(v, n=300):
    return _SAFE_RE.sub("", str(v if v is not None else ""))[:n]


def coin_of(sym) -> str:
    s = str(sym or "")
    return _COIN_RE.sub("", s, count=1) or s


def quote_of(sym) -> str:
    m9 = _COIN_RE.search(str(sym or ""))
    return m9.group(1).upper() if m9 else "USDT"


def px_path(ex):
    return os.path.join(common.STATE_DIR, f"futures_px_{ex}.json")


def load(ex) -> dict:
    try:
        with open(px_path(ex), "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(d, dict) or d.get("v") != PX_V or not isinstance(d.get("rows"), list):
        return {}
    d["cursor"] = d["cursor"] if isinstance(d.get("cursor"), dict) else {}
    d["ct"] = d["ct"] if isinstance(d.get("ct"), dict) else {}
    d["rows"] = [r for r in d["rows"] if isinstance(r, dict)]
    return d


def save(ex, d) -> None:
    common.atomic_write_json(px_path(ex), d)


def merge(old_rows, new_rows, now_ms, keep=None):
    by = {}
    for r in list(old_rows or ()) + list(new_rows or ()):
        if isinstance(r, dict) and r.get("uid") and isinstance(r.get("ts_ms"), (int, float)) and (keep is None or keep(r)):
            by[r["uid"]] = r
    lo = now_ms - KEEP_MS
    rows = sorted((r for r in by.values() if r["ts_ms"] >= lo), key=lambda r: (r["ts_ms"], r["uid"]))
    return rows[-ROWS_MAX:]


def update(ex, new_rows, now_ms, cursor=None, ct=None, keep=None):
    d = load(ex)
    out = {"v": PX_V, "ts": int(now_ms // 1000), "cursor": dict(d.get("cursor") or {}) if cursor is None else dict(cursor),
           "rows": merge(d.get("rows"), new_rows, now_ms, keep)}
    ct0 = dict(d.get("ct") or {})
    if ct:
        ct0.update(ct)
    if ct0:
        out["ct"] = ct0
    save(ex, out)
    return out


def _row(uid, sym, ts, role, side, px, **kw):
    t = num(ts)
    if not uid or not sym or t is None or t <= 0 or side not in ("LONG", "SHORT") or role not in ("open", "close"):
        return None
    r = {"uid": safe(uid), "symbol": safe(sym, 60), "ts_ms": int(t), "role": role, "side": side, "px": pnum(px)}
    for k, v in kw.items():
        if v is not None:
            r[k] = v
    return r


def _derive_entry(side, exit_px, pnl, qty):
    if exit_px is None or pnl is None or not qty:
        return None
    e = exit_px - pnl / qty if side == "LONG" else exit_px + pnl / qty
    return e if math.isfinite(e) and e > 0 else None


def rows_bybit(items):
    out = []
    for c in items or ():
        if not isinstance(c, dict):
            continue
        sd = {"Sell": "LONG", "Buy": "SHORT"}.get(c.get("side"))
        q = pnum(c.get("closedSize")) or pnum(c.get("qty"))
        r = _row(f"bb:{c.get('orderId')}:{c.get('updatedTime')}", c.get("symbol"), c.get("updatedTime"), "close", sd, c.get("avgExitPrice"),
                 qty_base=q, pnl=num(c.get("closedPnl")), entry_px=pnum(c.get("avgEntryPrice")), entry_src="exchange" if pnum(c.get("avgEntryPrice")) else None,
                 lev=num(c.get("leverage")), oid=safe(c.get("orderId"), 80) or None, fee_incl=True,
                 fee_open=num(c.get("openFee")), fee_close=num(c.get("closeFee")),
                 liq=True if str(c.get("execType") or "") == "BustTrade" else None,
                 pm="hedge")
        if r:
            out.append(r)
    return out


def rows_bybit_exec(items):
    out = []
    for x in items or ():
        if not isinstance(x, dict) or str(x.get("execType") or "") != "Trade":
            continue
        sd = {"Buy": "LONG", "Sell": "SHORT"}.get(x.get("side"))
        q, cs = pnum(x.get("execQty")), num(x.get("closedSize"))
        if not sd or not q or cs is None or cs < 0 or q - cs <= q * 1e-9:
            continue
        r = _row(f"bbx:{x.get('execId')}", x.get("symbol"), x.get("execTime"), "open", sd, x.get("execPrice"), qty_base=q - cs,
                 oid=safe(x.get("orderId"), 80) or None, pm="hedge")
        if r and x.get("execId"):
            out.append(r)
    return out


def rows_bybit_tlog(items, cp=()):
    lev = {}
    for c in cp or ():
        if isinstance(c, dict) and c.get("orderId") and num(c.get("leverage")) is not None:
            lev[str(c.get("orderId"))] = num(c.get("leverage"))
    out = []
    for x in items or ():
        if not isinstance(x, dict) or str(x.get("type") or "") not in ("TRADE", "LIQUIDATION", "ADL") or str(x.get("category") or "linear") != "linear":
            continue
        pnl, xp, q = num(x.get("cashFlow")), pnum(x.get("tradePrice")), pnum(x.get("qty"))
        sd = {"Sell": "LONG", "Buy": "SHORT"}.get(x.get("side"))
        if not pnl or not xp or not q or not sd or not x.get("id"):
            continue
        sz = num(x.get("size"))
        if sz is not None:
            before = sz + (q if sd == "LONG" else -q)
            if (before > 0) == (sd == "LONG") and abs(before) > 0:
                q = min(q, abs(before))
        r = _row(f"bbt:{x.get('id')}:p", x.get("symbol"), x.get("transactionTime"), "close", sd, xp, qty_base=q, pnl=pnl,
                 entry_px=_derive_entry(sd, xp, pnl, q), entry_src="derived", lev=lev.get(str(x.get("orderId") or "")),
                 oid=safe(x.get("orderId"), 80) or None, liq=True if str(x.get("type")) == "LIQUIDATION" else None, pm="hedge")
        if r and r.get("entry_px"):
            out.append(r)
    return out


def rows_okx(bills):
    out = []
    for b in bills or ():
        if not isinstance(b, dict):
            continue
        st = str(b.get("subType") or "")
        role, sd = ("close", OKX_CLOSE[st]) if st in OKX_CLOSE else ("open", OKX_OPEN[st]) if st in OKX_OPEN else (None, None)
        if (role is None and st in OKX_NET and (str(b.get("type") or "") == "2" or st in OKX_NET_ANYTYPE)
                and str(b.get("instType") or "SWAP") == "SWAP" and str(b.get("instId") or "").upper().endswith("-SWAP")):
            p9 = num(b.get("pnl"))
            role, sd = ("close", OKX_NET[st][1]) if p9 else ("open", OKX_NET[st][0])
        if role is None:
            continue
        bid = b.get("billId")
        r = _row(f"ok:{bid}:p" if role == "close" else f"ok:{bid}:o", b.get("instId"), b.get("ts"), role, sd, b.get("px"),
                 qty_ct=pnum(b.get("sz")), pnl=num(b.get("pnl")) if role == "close" else None, oid=safe(b.get("ordId"), 80) or None,
                 liq=True if st in OKX_LIQ else None,
                 pm="net" if st in OKX_NET else "hedge")
        if r:
            out.append(r)
    return out


def okx_ct(inst_rows):
    out = {}
    for x in inst_rows or ():
        if not isinstance(x, dict):
            continue
        iid, cv = safe(x.get("instId"), 60), pnum(x.get("ctVal"))
        base = str(x.get("ctValCcy") or "").upper()
        if iid and cv and base and base == coin_of(iid).upper() and str(x.get("ctType") or "linear") == "linear":
            out[iid] = cv
    return out


def rows_hl(fills, addr, sym_fn=None):
    out = []
    for f in fills or ():
        if not isinstance(f, dict):
            continue
        coin = str(f.get("coin") or "")
        if not coin or coin.startswith("@") or "/" in coin:
            continue
        sym = sym_fn(coin) if sym_fn else coin + "-USD"
        d = str(f.get("dir") or "")
        tid = f.get("tid") or f.get("hash")
        px, sz, sp = pnum(f.get("px")), pnum(f.get("sz")), num(f.get("startPosition"))
        pnl = num(f.get("closedPnl"))
        liq = True if f.get("liquidation") else None
        oid = safe(f.get("oid"), 40) or None
        close_side = open_side = None
        close_q = open_q = None
        if d in ("Close Long", "Close Short"):
            close_side, close_q = d.split()[1].upper(), sz
        elif d in ("Open Long", "Open Short"):
            open_side, open_q = d.split()[1].upper(), sz
        elif d in ("Long > Short", "Short > Long"):
            close_side = "LONG" if d.startswith("Long") else "SHORT"
            open_side = "SHORT" if close_side == "LONG" else "LONG"
            close_q = abs(sp) if sp else None
            open_q = (sz - close_q) if (sz and close_q is not None and sz > close_q) else None
        elif liq and sp:
            close_side, close_q = ("LONG" if sp > 0 else "SHORT"), sz
        if close_side:
            r = _row(f"hl:{addr}:{tid}:p", sym, f.get("time"), "close", close_side, px, qty_base=close_q, pnl=pnl,
                     entry_px=_derive_entry(close_side, px, pnl, close_q), entry_src="derived", oid=oid, liq=liq, acct=safe(addr, 120), pm="hedge")
            if r:
                out.append(r)
        if open_side:
            r = _row(f"hl:{addr}:{tid}:o", sym, f.get("time"), "open", open_side, px, qty_base=open_q, oid=oid, acct=safe(addr, 120), pm="hedge")
            if r:
                out.append(r)
    return out


def rows_binance(trades):
    out = []
    for t in trades or ():
        if not isinstance(t, dict):
            continue
        ps, sd0 = str(t.get("positionSide") or "BOTH").upper(), str(t.get("side") or "").upper()
        if sd0 not in ("BUY", "SELL"):
            continue
        pnl, q, px = num(t.get("realizedPnl")), pnum(t.get("qty")), pnum(t.get("price"))
        if ps in ("LONG", "SHORT"):
            side = ps
            closing = (pnl is not None and pnl != 0) or ((sd0 == "SELL") if ps == "LONG" else (sd0 == "BUY"))
        else:
            closing = pnl is not None and pnl != 0
            side = ("LONG" if sd0 == "SELL" else "SHORT") if closing else ("LONG" if sd0 == "BUY" else "SHORT")
        r = _row(f"bnt:{safe(t.get('symbol'), 40)}:{t.get('id')}", t.get("symbol"), t.get("time"), "close" if closing else "open", side, px, qty_base=q,
                 pnl=pnl if closing else None, entry_px=_derive_entry(side, px, pnl, q) if closing else None,
                 entry_src="derived" if closing else None, oid=safe(t.get("orderId"), 40) or None,
                 pm="hedge" if ps in ("LONG", "SHORT") else "net")
        if r and t.get("id") is not None:
            out.append(r)
    return out


def bn_plan(events, now_ms, lo_ms=None):
    lo = max(int(lo_ms or 0), now_ms - RETAIN_MS["binance"] + DAY_MS)
    by = {}
    for e in events or ():
        if not isinstance(e, dict) or e.get("kind") not in ("REALIZED", "FEE") or not e.get("symbol"):
            continue
        t = num(e.get("t"))
        if t is None or t < lo or t > now_ms:
            continue
        by.setdefault(safe(e["symbol"], 40), []).append(int(t))
    out = []
    for sym in sorted(by):
        end = -1
        for t in sorted(by[sym]):
            if t <= end:
                continue
            s = max(lo, t - 1000)
            end = min(s + 7 * DAY_MS - 1001, now_ms)
            out.append([sym, s, end])
    return out


def bn_match(rows):
    m = {}
    for r in rows or ():
        if isinstance(r, dict) and r.get("role") == "close" and isinstance(r.get("ts_ms"), (int, float)):
            m.setdefault((r.get("symbol"), int(r["ts_ms"]) // 1000), []).append(r)
    return m


def bn_pnl_eq(row, amt):
    p = num(row.get("pnl"))
    return p is not None and abs(p - amt) <= max(1e-6, abs(amt) * 1e-6)


def bn_unmatched(events, rows, now_ms, settle_ms=15 * 60 * 1000):
    lo = now_ms - RETAIN_MS["binance"] + DAY_MS
    idx = bn_match(rows)
    out = []
    for e in events or ():
        if not isinstance(e, dict) or e.get("kind") != "REALIZED" or not e.get("symbol"):
            continue
        t, a = num(e.get("t")), num(e.get("amount"))
        if t is None or a is None or t < lo or t > now_ms - settle_ms:
            continue
        if not any(bn_pnl_eq(c, a) for c in idx.get((safe(e["symbol"], 60), int(t) // 1000)) or ()):
            out.append(e)
    return out


_CACHE = {}
_CLOCK = threading.Lock()
_NONE = {}


def load_cached_k(ex):
    p = px_path(ex)
    try:
        st = os.stat(p)
        key = (st.st_mtime_ns, st.st_size, st.st_ino)
    except OSError:
        return None, _NONE
    with _CLOCK:
        hit = _CACHE.get(ex)
        if hit and hit[0] == key:
            return key, hit[1]
    d = load(ex)
    with _CLOCK:
        _CACHE[ex] = (key, d)
    return key, d


def load_cached(ex):
    return load_cached_k(ex)[1]


def _r(x, n=8):
    if x is None or not math.isfinite(x):
        return None
    return float(f"{x:.{n}g}")


def _ts_s(ms):
    return round(ms / 1000.0, 3)


CEX_KEYS = ("binance", "bybit", "okx")
WALK_TOL = 1e-9
REV_TOL = 1e-4
AVG_TOL = 2e-3
ANCHOR_WORK = (16, 1024)
ZERO_TOL = 1e-6
FUND_H_MAX = 0.03
STALE_MS = 7 * DAY_MS
STALE_MULT = 2.0
PX_RATIO_MAX = 10.0
_FB = object()


def _seq(r):
    p = str(r.get("uid") or "").split(":")
    n = p[-1] if p[0] == "bnt" and len(p) >= 3 else p[1] if p[0] == "ok" and len(p) == 3 else ""
    return int(n) if n.isdigit() else None


def _pair(uid):
    u = str(uid or "")
    if u.startswith("bn:"):
        p = u.split(":")
        return "bn:" + p[1] if len(p) >= 3 and p[1].isdigit() else None
    return u[:-2] if len(u) > 2 and u[-2:] in (":p", ":f") else None


def _row_entry(r, q):
    e = pnum(r.get("entry_px"))
    if e or r.get("fee_incl"):
        return e
    return _derive_entry(r.get("side"), num(r.get("px")), num(r.get("pnl")), q)


def _walk(rows, qty_of):
    qs = [qty_of(r) for r in rows]
    if not rows or any(q is None or q <= 0 for q in qs):
        return list(rows), {}
    eps = WALK_TOL * max(qs)
    st = {"LONG": [0.0, 0.0, None, True, [], 0.0], "SHORT": [0.0, 0.0, None, True, [], 0.0]}
    idl = {"LONG": [-1, 0.0], "SHORT": [-1, 0.0]}
    estp = {"LONG": False, "SHORT": False}
    out, ent = [], {}
    work = [ANCHOR_WORK[0] * len(rows) + ANCHOR_WORK[1]]

    def flat(sd):
        st[sd][:] = [0.0, 0.0, None, True, [], 0.0]
        idl[sd][:] = [-1, 0.0]
        estp[sd] = False

    def add(sd, q, p, ts, idle=False):
        s = st[sd]
        if s[0] <= eps:
            s[:] = [0.0, 0.0, ts, True, [], 0.0]
            idl[sd][:] = [-1, 0.0]
            idle = False
        raw = q * s[5] / s[0] if s[0] > eps and s[5] > 0 else q
        s[0] += q
        if p:
            s[1] += p * q
        else:
            s[3] = False
        s[4].append((ts, raw, p))
        s[5] += raw
        if idle:
            idl[sd][:] = [len(s[4]) - 1, raw]
        elif idl[sd][0] >= 0:
            idl[sd][1] += raw

    def anchor(sd, q, ep):
        s = st[sd]
        lots, Q, PQ, best = s[4], 0.0, 0.0, None
        f = s[0] / s[5] if s[5] > 0 else 0.0
        if f > 0 and len(lots) <= work[0]:
            work[0] -= len(lots)
            for k in range(len(lots) - 1, -1, -1):
                t9, q9, p9 = lots[k]
                if not p9:
                    break
                Q += q9
                PQ += p9 * q9
                if Q * f + eps >= q and abs(ep / (PQ / Q) - 1) <= AVG_TOL:
                    best = (k, Q, PQ)
        if best:
            k, Q, PQ = best
            s[:] = [Q * f, PQ * f, lots[k][0], True, lots[k:], Q]
            i9 = idl[sd][0]
            idl[sd][:] = [i9 - k, idl[sd][1]] if i9 > k else [-1, 0.0]
        else:
            s[:] = [s[0], ep * s[0], None, True, [(None, s[0], ep)], s[0]]
            idl[sd][:] = [-1, 0.0]

    def idle_anchor(sd, q):
        s, (i9, R9) = st[sd], idl[sd]
        f = s[0] / s[5] if s[5] > 0 else 0.0
        if R9 * f + eps < q or len(s[4]) - i9 > work[0]:
            return False
        lots = s[4][i9:]
        work[0] -= len(lots)
        PQ = sum(p9 * q9 for _t9, q9, p9 in lots if p9)
        s[:] = [R9 * f, PQ * f, lots[0][0], all(p9 for _t9, _q9, p9 in lots), lots, R9]
        idl[sd][:] = [-1, 0.0]
        return True

    def avg(sd):
        s = st[sd]
        return s[1] / s[0] if s[0] > eps and s[3] and s[1] > 0 else None

    def take(sd, q):
        s = st[sd]
        e = avg(sd)
        s[0] -= q
        if e:
            s[1] = e * s[0]
        if s[0] <= eps:
            flat(sd)
        elif s[5] > 0 and s[0] < s[5] * 1e-12:
            s[4][:] = [(s[2], s[0], e or (s[1] / s[0] if s[0] else None))]
            s[5] = s[0]
            idl[sd][:] = [-1, 0.0]

    sq = [_seq(r) for r in rows]
    by_id = all(x is not None for x in sq)
    order = sorted(range(len(rows)), key=(lambda i: (rows[i]["ts_ms"], sq[i], i)) if by_id else
                   (lambda i: (rows[i]["ts_ms"], 0 if rows[i].get("role") == "close" else 1, i)))
    last = None
    for i in order:
        r, q = rows[i], qs[i]
        sd, ts, xp = r["side"], r["ts_ms"], num(r.get("px"))
        gap, last = (ts - last if last is not None else 0), ts
        net = r.get("pm") != "hedge"
        o = "SHORT" if sd == "LONG" else "LONG"
        if r.get("role") == "open":
            e = avg(o)
            if net and e and xp and abs(xp / e - 1) <= ZERO_TOL:
                cq = min(q, st[o][0])
                c = dict(r, role="close", side=o, pnl=0.0, _q=cq, entry_px=e, entry_src="derived")
                ent[id(c)] = st[o][2]
                take(o, cq)
                out.append(c)
                if q - cq > eps:
                    add(sd, q - cq, xp, ts)
                    out.append(dict(r, _q=q - cq, uid=f"{r.get('uid')}:r"))
                continue
            add(sd, q, xp, ts, idle=gap >= STALE_MS)
            out.append(r)
            continue
        P = st[sd][0]
        if P <= eps:
            out.append(r)
            continue
        if q > P + eps:
            e, ep = avg(sd), _derive_entry(sd, xp, num(r.get("pnl")), P)
            if net and e and ep and abs(ep / e - 1) <= REV_TOL:
                c = dict(r, _q=P, entry_px=ep, entry_src="derived")
                ent[id(c)] = st[sd][2]
                flat(sd)
                out.append(c)
                add(o, q - P, xp, ts)
                out.append(dict(r, role="open", side=o, _q=q - P, uid=f"{r.get('uid')}:r", pnl=None, entry_px=None, entry_src=None, liq=None))
                continue
            flat(sd)
            out.append(r)
            continue
        e, ep = avg(sd), (None if r.get("fee_incl") else _row_entry(r, q))
        if e and ep and abs(ep / e - 1) > AVG_TOL:
            anchor(sd, q, ep)
            estp[sd] = False
        elif idl[sd][0] > 0 and P >= STALE_MULT * q and idle_anchor(sd, q):
            estp[sd] = True
        if estp[sd]:
            r = dict(r, _est=True)
        ent[id(r)] = st[sd][2]
        take(sd, q)
        out.append(r)
    return out, ent


def assemble(iso, fev, px, exn, byex_fn, now_ms, stale=(), accts=None):
    day = [x for x in fev or () if x[0] == iso]
    if not day:
        return {"ok": True, "empty": True, "date": iso}
    tot_u = tot_k = 0.0
    kinds = {"REALIZED": 0.0, "FEE": 0.0, "FUNDING": 0.0}
    kinds_k = {"REALIZED": 0.0, "FEE": 0.0, "FUNDING": 0.0}
    exk = {}
    by_ex = {}
    for dk, t, a, k, r in day:
        tot_u += a
        tot_k += k
        kd = r.get("kind")
        kinds[kd] = kinds.get(kd, 0.0) + a
        kinds_k[kd] = kinds_k.get(kd, 0.0) + k
        e9 = exk.setdefault(r.get("ex"), {"REALIZED": [0.0, 0.0], "FEE": [0.0, 0.0], "FUNDING": [0.0, 0.0]})
        e9.setdefault(kd, [0.0, 0.0])
        e9[kd][0] += a
        e9[kd][1] += k
        x9 = by_ex.setdefault((dk, r.get("ex")), [0.0, 0.0, 0, 0])
        x9[0] += a
        x9[1] += k
        x9[2] += 1 if kd == "REALIZED" else 0
        x9[3] = max(x9[3], t)
    uidmap, bnmap, closes, opens, ent = {}, {}, {}, {}, {}
    keep = []
    ct = (px.get("okx") or {}).get("ct") or {}
    have_rows = set()
    on = {k: set(v or ()) for k, v in (accts or {}).items()}

    def qty_of(ex, r):
        if r.get("_q") is not None:
            return num(r.get("_q"))
        if ex == "okx":
            c, n9 = num(ct.get(r.get("symbol"))), num(r.get("qty_ct"))
            return n9 * c if c and n9 else None
        return num(r.get("qty_base"))

    for ex, d in px.items():
        dex = ex not in CEX_KEYS
        grp = {}
        for r in d.get("rows") or ():
            if not isinstance(r, dict) or r.get("side") not in ("LONG", "SHORT") or not isinstance(r.get("ts_ms"), (int, float)) \
                    or r.get("role") not in ("open", "close"):
                continue
            if dex and r.get("acct") not in on.get(ex, ()):
                continue
            have_rows.add(ex)
            grp.setdefault((r.get("acct"), r.get("symbol")), []).append(r)
        for (_a9, sym9), lst in grp.items():
            rows9, ent9 = _walk(lst, lambda r9, ex=ex: qty_of(ex, r9))
            keep.append(rows9)
            ent.update(ent9)
            for r in rows9:
                key = (ex, sym9, r["side"])
                if r["role"] == "close":
                    closes.setdefault(key, []).append(r["ts_ms"])
                    if ex == "binance":
                        bnmap.setdefault((sym9, int(r["ts_ms"]) // 1000), []).append(r)
                    else:
                        uidmap[r.get("uid")] = (ex, r)
                else:
                    opens.setdefault(key, []).append(r)
    for v in closes.values():
        v.sort()
    for v in opens.values():
        v.sort(key=lambda r: r["ts_ms"])

    def px_of(ex, r, amt, ets=None):
        q = qty_of(ex, r)
        xp = num(r.get("px"))
        if ex == "okx":
            ep, src = (_derive_entry(r["side"], xp, num(r.get("pnl")), q), "derived") if q else (None, "none")
        else:
            ep, src = num(r.get("entry_px")), (r.get("entry_src") or "none")
        if not xp or not q:
            return r["side"], xp, None, q, "none", ("계약 크기 모름" if ex == "okx" and not q else "가격 칸 없음"), 0.0, False
        if not ep:
            return r["side"], xp, None, q, "none", "진입가 없음", 0.0, False
        sg = 1 if r["side"] == "LONG" else -1
        gross = (xp - ep) * q * sg
        want = amt
        if r.get("fee_incl"):
            want = amt + abs(num(r.get("fee_open")) or 0) + abs(num(r.get("fee_close")) or 0)
        tol = max(abs(want) * PX_TOL_PCT / 100, abs(xp * q) * 0.0002, 0.01)
        if max(ep, xp) / min(ep, xp) > PX_RATIO_MAX:
            return r["side"], None, None, q, "none", "진입·청산가 10배 넘게 차이(가격 칸 의심)", 0.0, False
        if abs(gross - want) > tol:
            known = isinstance(ets, (int, float)) and ets > 0
            nh = int(r["ts_ms"]) // 3600000 - int(ets) // 3600000 if known else 1
            fund = want - gross
            if not (src == "exchange" and nh >= 1 and abs(fund) <= abs(ep * q) * FUND_H_MAX * nh):
                return r["side"], None, None, q, "none", "거래소 값끼리 안 맞음(가격 × 수량 ≠ 정산)", 0.0, False
            return r["side"], xp, ep, q, src, None, fund, not known
        return r["side"], xp, ep, q, src, None, 0.0, False

    def pend_why(ex, t):
        d = px.get(ex) or {}
        cur = d.get("cursor") if isinstance(d.get("cursor"), dict) else {}
        if ex == "binance" and isinstance(cur.get("bf_plan"), list) and cur["bf_plan"]:
            return f"체결 보강 중(남은 {len(cur['bf_plan'])}구간)"
        if ex not in CEX_KEYS or not d or not cur.get("bf_done") or (ex == "okx" and cur.get("bf_v") != OKX_BF_V):
            return "체결 보강 전"
        ts9 = num(d.get("ts"))
        if ts9 is None or t >= ts9 * 1000 - 60000:
            return "체결 보강 전"
        return "체결 기록에서 못 찾음"

    used_bn = set()
    groups, order, pair_of = {}, [], {}
    fee_ev, fund_ev, other = [], [], {"usd": 0.0, "krw": 0.0, "fee": 0.0, "funding": 0.0}
    for dk, t, a, k, r in day:
        ex, sym, kind = r.get("ex"), str(r.get("symbol") or ""), r.get("kind")
        if not sym:
            other["usd"] += a
            other["krw"] += k
            if kind == "FEE":
                other["fee"] += a
            elif kind == "FUNDING":
                other["funding"] += a
            continue
        if kind == "FEE":
            fee_ev.append((t, a, k, ex, sym, r.get("uid")))
            continue
        if kind == "FUNDING":
            fund_ev.append((t, a, k, ex, sym))
            continue
        row = None
        if ex == "binance":
            for c in bnmap.get((safe(sym, 60), int(t) // 1000)) or ():
                if id(c) in used_bn:
                    continue
                if bn_pnl_eq(c, a):
                    row = c
                    used_bn.add(id(c))
                    break
        else:
            hit = uidmap.get(safe(r.get("uid")))
            if hit and hit[0] == ex:
                row = hit[1]
        fund9, may9 = 0.0, False
        if row is not None:
            side, xp, ep, q, src, why, fund9, may9 = px_of(ex, row, a, ent.get(id(row)))
        else:
            side = xp = ep = q = None
            src = "none"
            ret = RETAIN_MS.get(ex)
            if ex not in PX_EX:
                why = "이 거래소는 가격 수집 안 함"
            elif ret and t < now_ms - ret:
                why = "거래소 보존 기간 밖(3개월)"
            else:
                why = pend_why(ex, t)
        oid = row.get("oid") if row is not None and src != "none" else None
        gk = (ex, sym, ("o", oid) if oid else ("t", t, src == "none"))
        g = groups.get(gk)
        if g is None:
            g = groups[gk] = {"ex": ex, "sym": sym, "ts": [], "pnl": 0.0, "pnlKrw": 0.0, "n": 0, "q": 0.0, "xq": 0.0, "eq": 0.0,
                              "side": side, "src": src, "why": why, "lev": None, "liq": False, "feeIncl": False, "feeInfo": 0.0, "ent": [],
                              "fund": 0.0, "est": False, "fmay": False}
            order.append(gk)
        g["ts"].append(t)
        pk9 = _pair(r.get("uid"))
        if pk9:
            pair_of.setdefault((ex, pk9), gk)
        g["pnl"] += a
        g["pnlKrw"] += k
        g["n"] += 1
        g["ent"].append(ent.get(id(row), _FB) if row is not None else _FB)
        if row is not None:
            g["lev"] = g["lev"] or num(row.get("lev"))
            g["liq"] = g["liq"] or bool(row.get("liq"))
            g["est"] = g["est"] or bool(row.get("_est"))
            if row.get("fee_incl"):
                g["feeIncl"] = True
                g["feeInfo"] -= abs(num(row.get("fee_open")) or 0) + abs(num(row.get("fee_close")) or 0)
        if src != "none" and q:
            g["q"] += q
            g["xq"] += xp * q
            g["eq"] += ep * q
            g["fund"] += fund9
            g["fmay"] = g["fmay"] or may9
        elif g["src"] != "none":
            g["src"], g["why"] = "none", why
    ms_of = {}
    for gk in order:
        for t in groups[gk]["ts"]:
            ms_of.setdefault((groups[gk]["ex"], groups[gk]["sym"], t), gk)
    pair_ex = {ex for t, a, k, ex, sym, u in fee_ev if _pair(u) and (ex, _pair(u)) in pair_of}
    loose_fee = []
    for t, a, k, ex, sym, u in fee_ev:
        if ex in pair_ex:
            pk9 = _pair(u)
            gk = pair_of.get((ex, pk9)) if pk9 else None
            if gk is not None and groups[gk]["sym"] != sym:
                gk = None
        else:
            gk = ms_of.get((ex, sym, t))
        if gk is not None:
            g = groups[gk]
            g["fee"] = g.get("fee", 0.0) + a
            g["feeKrw"] = g.get("feeKrw", 0.0) + k
        else:
            loose_fee.append((t, a, k, ex, sym, u))
    coins = {}

    def coin(sym):
        c0 = coin_of(sym)
        c = coins.get(c0)
        if c is None:
            c = coins[c0] = {"coin": c0, "label": c0 + " 무기한", "usd": 0.0, "krw": 0.0, "realized": 0.0, "fee": 0.0, "funding": 0.0,
                             "realizedKrw": 0.0, "feeKrw": 0.0, "fundingKrw": 0.0,
                             "closes": 0, "wins": 0, "losses": 0, "venues": {}, "trades": [], "funding_l": [], "syms": set(), "exs": {}}
        c["syms"].add(sym)
        return c

    def cex(c, ex):
        x = c["exs"].get(ex)
        if x is None:
            x = c["exs"][ex] = {"usd": 0.0, "krw": 0.0, "realized": 0.0, "fee": 0.0, "funding": 0.0, "realizedKrw": 0.0, "feeKrw": 0.0,
                                "fundingKrw": 0.0, "closes": 0, "priced": 0, "wins": 0, "losses": 0}
        return x

    def venue(c, ex, sym, a):
        v = c["venues"].setdefault((ex, sym), {"exKey": ex, "ex": exn.get(ex, ex), "symbol": sym, "usd": 0.0, "n": 0})
        v["usd"] += a
        return v

    for dk, t, a, k, r in day:
        sym = str(r.get("symbol") or "")
        if not sym:
            continue
        c = coin(sym)
        c["usd"] += a
        c["krw"] += k
        kd = r.get("kind")
        f9 = "realized" if kd == "REALIZED" else "fee" if kd == "FEE" else "funding"
        c[f9] += a
        c[f9 + "Krw"] += k
        x9 = cex(c, r.get("ex"))
        x9["usd"] += a
        x9["krw"] += k
        x9[f9] += a
        x9[f9 + "Krw"] += k
        v = venue(c, r.get("ex"), sym, a)
        if kd == "REALIZED":
            v["n"] += 1
    for t, a, k, ex, sym in fund_ev:
        coin(sym)["funding_l"].append({"ts": _ts_s(t), "exKey": ex, "ex": exn.get(ex, ex), "usd": round(a, 6), "krw": round(k)})
    unp = {}
    exc = {}
    for i, gk in enumerate(order):
        g = groups[gk]
        c = coin(g["sym"])
        t_exit = max(g["ts"])
        priced = g["src"] != "none" and g["q"] > 0
        side = g["side"] if g["src"] != "none" or g["side"] else None
        entry_ts, est = None, False
        if priced and side:
            es = g["ent"]
            if es and all(e is not _FB for e in es):
                vals = [e for e in es if e is not None]
                entry_ts = min(vals) if vals else None
                est = g["est"] and entry_ts is not None
            else:
                key = (g["ex"], g["sym"], side)
                prev = [x for x in closes.get(key, ()) if x < min(g["ts"])]
                tp = prev[-1] if prev else None
                cand = [o["ts_ms"] for o in opens.get(key, ()) if o["ts_ms"] <= t_exit and (tp is None or o["ts_ms"] > tp)]
                entry_ts = min(cand) if cand else None
        tr = {"id": f"{g['ex']}:{i}", "exKey": g["ex"], "ex": exn.get(g["ex"], g["ex"]), "symbol": g["sym"],
              "side": side, "lev": _r(g["lev"], 4) if g["lev"] else None,
              "qty": _r(g["q"]) if priced else None,
              "entryPx": _r(g["eq"] / g["q"]) if priced else None, "exitPx": _r(g["xq"] / g["q"]) if priced else None,
              "entryTs": _ts_s(entry_ts) if entry_ts else None, "exitTs": _ts_s(t_exit),
              "holdS": int((t_exit - entry_ts) / 1000) if entry_ts else None,
              "pnl": round(g["pnl"], 6), "pnlKrw": round(g["pnlKrw"]), "fee": round(g.get("fee", 0.0), 6), "feeKrw": round(g.get("feeKrw", 0.0)),
              "feeIncl": g["feeIncl"] or g["ex"] == "bybit", "liq": g["liq"], "rows": g["n"], "px": g["src"] if priced else "none",
              "why": None if priced else (g["why"] or "가격 칸 없음")}
        if g["feeIncl"] and g["feeInfo"]:
            tr["feeInfo"] = round(g["feeInfo"], 6)
        if priced and abs(g["fund"]) >= 5e-7:
            tr["fundIncl"] = round(g["fund"], 6)
            if g["fmay"]:
                tr["fundMaybe"] = True
        if est:
            tr["entryEst"] = True
        c["trades"].append(tr)
        c["closes"] += 1
        x9 = exc.setdefault(g["ex"], [0, 0, 0])
        x9[0] += 1
        y9 = cex(c, g["ex"])
        y9["closes"] += 1
        y9["priced"] += 1 if priced else 0
        if g["pnl"] > 0:
            c["wins"] += 1
            x9[1] += 1
            y9["wins"] += 1
        elif g["pnl"] < 0:
            c["losses"] += 1
            x9[2] += 1
            y9["losses"] += 1
        if not priced:
            u = unp.setdefault(g["ex"], {})
            u[tr["why"]] = u.get(tr["why"], 0) + 1
    d0 = int(datetime.strptime(iso, "%Y-%m-%d").replace(tzinfo=KST).timestamp() * 1000)
    lo_o, hi_o = d0 - 36 * 3600 * 1000, d0 + DAY_MS
    out_coins = []
    for c in coins.values():
        agg = {}
        for (ex, sym, side), lst in opens.items():
            if sym not in c["syms"]:
                continue
            for o in lst:
                p9 = num(o.get("px"))
                if not (lo_o <= o["ts_ms"] < hi_o) or not p9:
                    continue
                q = qty_of(ex, o)
                k9 = (ex, sym, side, ("o", o["oid"]) if o.get("oid") else ("t", o["ts_ms"], p9))
                a9 = agg.get(k9)
                if a9 is None:
                    a9 = agg[k9] = {"ts": o["ts_ms"], "exKey": ex, "side": side, "pq": 0.0, "q": 0.0, "p0": p9, "qok": True, "n": 0}
                a9["ts"] = min(a9["ts"], o["ts_ms"])
                a9["n"] += 1
                if q:
                    a9["pq"] += p9 * q
                    a9["q"] += q
                else:
                    a9["qok"] = False
        ops = []
        for a9 in agg.values():
            qk = a9["qok"] and a9["q"] > 0
            o9 = {"ts": _ts_s(a9["ts"]), "exKey": a9["exKey"], "side": a9["side"], "px": _r(a9["pq"] / a9["q"] if qk else a9["p0"]),
                  "q": _r(a9["q"]) if qk else None}
            if a9["n"] > 1:
                o9["fills"] = a9["n"]
            ops.append(o9)
        ops.sort(key=lambda x: (x["ts"], x["exKey"]))
        trs = c["trades"]
        tot_ex = {}
        for x in trs:
            tot_ex[x["exKey"]] = tot_ex.get(x["exKey"], 0) + 1
        if len(trs) > TRADES_MAX:
            ranked = sorted(trs, key=lambda x: (-abs(x["pnl"]), x["id"]))
            share = max(1, TRADES_MAX // max(1, len(tot_ex)))
            keep_ids, got = set(), {}
            for x in ranked:
                if got.get(x["exKey"], 0) < share and len(keep_ids) < TRADES_MAX:
                    keep_ids.add(id(x))
                    got[x["exKey"]] = got.get(x["exKey"], 0) + 1
            for x in ranked:
                if len(keep_ids) >= TRADES_MAX:
                    break
                keep_ids.add(id(x))
            trs = [x for x in trs if id(x) in keep_ids]
        trs.sort(key=lambda x: (x["exitTs"], x["id"]))
        vs = sorted(c["venues"].values(), key=lambda v: (-abs(v["usd"]), v["exKey"], v["symbol"]))
        for v in vs:
            v["usd"] = round(v["usd"], 6)
        out_coins.append({"coin": c["coin"], "label": c["label"], "usd": round(c["usd"], 6), "krw": round(c["krw"]),
                          "realized": round(c["realized"], 6), "fee": round(c["fee"], 6), "funding": round(c["funding"], 6),
                          "realizedKrw": round(c["realizedKrw"]), "feeKrw": round(c["feeKrw"]), "fundingKrw": round(c["fundingKrw"]),
                          "closes": c["closes"], "wins": c["wins"], "losses": c["losses"], "venues": vs,
                          "priced": {"n": sum(1 for x in c["trades"] if x["px"] != "none"), "of": len(c["trades"])},
                          "trades": trs, "tradesTotal": len(c["trades"]), "tradesTotalEx": tot_ex, "opens": ops[-OPENS_MAX:],
                          "exStats": {ex: {**{k: (round(v) if k.endswith("Krw") or k == "krw" else round(v, 6)) for k, v in e.items() if isinstance(v, float)},
                                           "closes": e["closes"], "wins": e["wins"], "losses": e["losses"], "priced": {"n": e["priced"], "of": e["closes"]}}
                                      for ex, e in sorted(c["exs"].items(), key=lambda kv: str(kv[0]))},
                          "fundingRows": sorted(c["funding_l"], key=lambda x: x["ts"]),
                          "looseFee": round(sum(a for t, a, k, ex, sym, u in loose_fee if sym in c["syms"]), 6)})
    out_coins.sort(key=lambda c: (-abs(c["usd"]), c["coin"]))
    wins = sum(c["wins"] for c in out_coins)
    losses = sum(c["losses"] for c in out_coins)
    ex_kinds = {}
    for ex, e9 in exk.items():
        x9 = exc.get(ex, [0, 0, 0])
        ex_kinds[ex] = {"realized": round(e9["REALIZED"][0], 6), "fee": round(e9["FEE"][0], 6), "funding": round(e9["FUNDING"][0], 6),
                        "realizedKrw": round(e9["REALIZED"][1]), "feeKrw": round(e9["FEE"][1]), "fundingKrw": round(e9["FUNDING"][1]),
                        "closes": x9[0], "wins": x9[1], "losses": x9[2]}
    return {"ok": True, "date": iso,
            "total": {"usd": round(tot_u, 2), "krw": round(tot_k), "realized": round(kinds["REALIZED"], 6), "fee": round(kinds["FEE"], 6),
                      "funding": round(kinds["FUNDING"], 6),
                      "realizedKrw": round(kinds_k["REALIZED"]), "feeKrw": round(kinds_k["FEE"]), "fundingKrw": round(kinds_k["FUNDING"]),
                      "closes": sum(c["closes"] for c in out_coins), "wins": wins, "losses": losses,
                      "events": len(day)},
            "byEx": byex_fn(by_ex, exn).get(iso, []),
            "exKinds": ex_kinds,
            "coins": out_coins,
            "other": {k: (round(v) if k == "krw" else round(v, 6)) for k, v in other.items()},
            "unpriced": [{"exKey": ex, "ex": exn.get(ex, ex), "n": sum(u.values()), "reason": max(u.items(), key=lambda kv: kv[1])[0]}
                         for ex, u in sorted(unp.items())],
            "stale": sorted(set(stale) & {r.get("ex") for _d, _t, _a, _k, r in day}),
            "coinEst": sum(1 for _d, _t, _a, _k, r in day if isinstance(r, dict) and r.get("px_est"))}
