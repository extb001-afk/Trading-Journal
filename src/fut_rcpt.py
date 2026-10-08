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
_SAFE_RE = re.compile(r"[^A-Za-z0-9._:/-]")

OKX_OPEN = {"3": "LONG", "4": "SHORT", "206": "LONG", "207": "SHORT"}
OKX_CLOSE = {"5": "LONG", "6": "SHORT", "100": "LONG", "101": "SHORT", "104": "LONG", "105": "SHORT", "208": "LONG", "209": "SHORT"}
OKX_LIQ = {"100", "101", "104", "105"}


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
                 liq=True if str(c.get("execType") or "") == "BustTrade" else None)
        if r:
            out.append(r)
    return out


def rows_okx(bills):
    out = []
    for b in bills or ():
        if not isinstance(b, dict):
            continue
        st = str(b.get("subType") or "")
        role, sd = ("close", OKX_CLOSE[st]) if st in OKX_CLOSE else ("open", OKX_OPEN[st]) if st in OKX_OPEN else (None, None)
        if role is None:
            continue
        bid = b.get("billId")
        r = _row(f"ok:{bid}:p" if role == "close" else f"ok:{bid}:o", b.get("instId"), b.get("ts"), role, sd, b.get("px"),
                 qty_ct=pnum(b.get("sz")), pnl=num(b.get("pnl")) if role == "close" else None, oid=safe(b.get("ordId"), 80) or None,
                 liq=True if st in OKX_LIQ else None)
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
                     entry_px=_derive_entry(close_side, px, pnl, close_q), entry_src="derived", oid=oid, liq=liq, acct=safe(addr, 120))
            if r:
                out.append(r)
        if open_side:
            r = _row(f"hl:{addr}:{tid}:o", sym, f.get("time"), "open", open_side, px, qty_base=open_q, oid=oid, acct=safe(addr, 120))
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
        closing = pnl is not None and pnl != 0
        if ps in ("LONG", "SHORT"):
            side = ps
        else:
            side = ("LONG" if sd0 == "SELL" else "SHORT") if closing else ("LONG" if sd0 == "BUY" else "SHORT")
        r = _row(f"bnt:{safe(t.get('symbol'), 40)}:{t.get('id')}", t.get("symbol"), t.get("time"), "close" if closing else "open", side, px, qty_base=q,
                 pnl=pnl if closing else None, entry_px=_derive_entry(side, px, pnl, q) if closing else None,
                 entry_src="derived" if closing else None, oid=safe(t.get("orderId"), 40) or None)
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


_CACHE = {}
_CLOCK = threading.Lock()
_NONE = {}


def load_cached(ex):
    p = px_path(ex)
    try:
        st = os.stat(p)
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        return _NONE
    with _CLOCK:
        hit = _CACHE.get(ex)
        if hit and hit[0] == key:
            return hit[1]
    d = load(ex)
    with _CLOCK:
        _CACHE[ex] = (key, d)
    return d


def _r(x, n=8):
    if x is None or not math.isfinite(x):
        return None
    return float(f"{x:.{n}g}")


def _ts_s(ms):
    return round(ms / 1000.0, 3)


CEX_KEYS = ("binance", "bybit", "okx")


def assemble(iso, fev, px, exn, byex_fn, now_ms, stale=(), accts=None):
    day = [x for x in fev or () if x[0] == iso]
    if not day:
        return {"ok": True, "empty": True, "date": iso}
    tot_u = tot_k = 0.0
    kinds = {"REALIZED": 0.0, "FEE": 0.0, "FUNDING": 0.0}
    by_ex = {}
    for dk, t, a, k, r in day:
        tot_u += a
        tot_k += k
        kinds[r.get("kind")] = kinds.get(r.get("kind"), 0.0) + a
        x9 = by_ex.setdefault((dk, r.get("ex")), [0.0, 0.0, 0, 0])
        x9[0] += a
        x9[1] += k
        x9[2] += 1 if r.get("kind") == "REALIZED" else 0
        x9[3] = max(x9[3], t)
    uidmap, bnmap, closes, opens = {}, {}, {}, {}
    ct = (px.get("okx") or {}).get("ct") or {}
    have_rows = set()
    on = {k: set(v or ()) for k, v in (accts or {}).items()}
    for ex, d in px.items():
        dex = ex not in CEX_KEYS
        for r in d.get("rows") or ():
            if not isinstance(r, dict) or r.get("side") not in ("LONG", "SHORT") or not isinstance(r.get("ts_ms"), (int, float)):
                continue
            if dex and r.get("acct") not in on.get(ex, ()):
                continue
            have_rows.add(ex)
            key = (ex, r.get("symbol"), r["side"])
            if r.get("role") == "close":
                closes.setdefault(key, []).append(r["ts_ms"])
                if ex == "binance":
                    bnmap.setdefault((r.get("symbol"), int(r["ts_ms"])), []).append(r)
                else:
                    uidmap[r.get("uid")] = (ex, r)
            elif r.get("role") == "open":
                opens.setdefault(key, []).append(r)
    for v in closes.values():
        v.sort()
    for v in opens.values():
        v.sort(key=lambda r: r["ts_ms"])

    def qty_of(ex, r):
        if ex == "okx":
            c = num(ct.get(r.get("symbol")))
            return r["qty_ct"] * c if c and r.get("qty_ct") else None
        return num(r.get("qty_base"))

    def px_of(ex, r, amt):
        q = qty_of(ex, r)
        xp = num(r.get("px"))
        if ex == "okx":
            ep, src = (_derive_entry(r["side"], xp, num(r.get("pnl")), q), "derived") if q else (None, "none")
        else:
            ep, src = num(r.get("entry_px")), (r.get("entry_src") or "none")
        if not xp or not q:
            return r["side"], xp, None, q, "none", ("계약 크기 모름" if ex == "okx" and not q else "가격 칸 없음")
        if not ep:
            return r["side"], xp, None, q, "none", "진입가 없음"
        sg = 1 if r["side"] == "LONG" else -1
        gross = (xp - ep) * q * sg
        want = amt
        if r.get("fee_incl"):
            want = amt + abs(num(r.get("fee_open")) or 0) + abs(num(r.get("fee_close")) or 0)
        tol = max(abs(want) * PX_TOL_PCT / 100, abs(xp * q) * 0.0002, 0.01)
        if abs(gross - want) > tol or abs(ep / xp - 1) > 0.9:
            return r["side"], None, None, q, "none", "가격 칸 어긋남"
        return r["side"], xp, ep, q, src, None

    used_bn = set()
    groups, order = {}, []
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
            fee_ev.append((t, a, k, ex, sym))
            continue
        if kind == "FUNDING":
            fund_ev.append((t, a, k, ex, sym))
            continue
        row = None
        if ex == "binance":
            for c in bnmap.get((safe(sym, 60), int(t))) or ():
                if id(c) in used_bn:
                    continue
                if num(c.get("pnl")) is not None and abs(num(c.get("pnl")) - a) <= max(1e-6, abs(a) * 1e-6):
                    row = c
                    used_bn.add(id(c))
                    break
        else:
            hit = uidmap.get(safe(r.get("uid")))
            if hit and hit[0] == ex:
                row = hit[1]
        if row is not None:
            side, xp, ep, q, src, why = px_of(ex, row, a)
        else:
            side = xp = ep = q = None
            src = "none"
            ret = RETAIN_MS.get(ex)
            if ex not in PX_EX:
                why = "이 거래소는 가격 수집 안 함"
            elif ret and t < now_ms - ret:
                why = "거래소 보존 기간 밖(3개월)"
            else:
                why = "체결 보강 전"
        oid = row.get("oid") if row is not None and src != "none" else None
        gk = (ex, sym, ("o", oid) if oid else ("t", t, src == "none"))
        g = groups.get(gk)
        if g is None:
            g = groups[gk] = {"ex": ex, "sym": sym, "ts": [], "pnl": 0.0, "pnlKrw": 0.0, "n": 0, "q": 0.0, "xq": 0.0, "eq": 0.0,
                              "side": side, "src": src, "why": why, "lev": None, "liq": False, "feeIncl": False, "feeInfo": 0.0}
            order.append(gk)
        g["ts"].append(t)
        g["pnl"] += a
        g["pnlKrw"] += k
        g["n"] += 1
        if row is not None:
            g["lev"] = g["lev"] or num(row.get("lev"))
            g["liq"] = g["liq"] or bool(row.get("liq"))
            if row.get("fee_incl"):
                g["feeIncl"] = True
                g["feeInfo"] -= abs(num(row.get("fee_open")) or 0) + abs(num(row.get("fee_close")) or 0)
        if src != "none" and q:
            g["q"] += q
            g["xq"] += xp * q
            g["eq"] += ep * q
        elif g["src"] != "none":
            g["src"], g["why"] = "none", why
    ms_of = {}
    for gk in order:
        for t in groups[gk]["ts"]:
            ms_of.setdefault((groups[gk]["ex"], groups[gk]["sym"], t), gk)
    loose_fee = []
    for t, a, k, ex, sym in fee_ev:
        gk = ms_of.get((ex, sym, t))
        if gk is not None:
            g = groups[gk]
            g["fee"] = g.get("fee", 0.0) + a
            g["feeKrw"] = g.get("feeKrw", 0.0) + k
        else:
            loose_fee.append((t, a, k, ex, sym))
    coins = {}

    def coin(sym):
        c0 = coin_of(sym)
        c = coins.get(c0)
        if c is None:
            c = coins[c0] = {"coin": c0, "label": c0 + " 무기한", "usd": 0.0, "krw": 0.0, "realized": 0.0, "fee": 0.0, "funding": 0.0,
                             "closes": 0, "wins": 0, "losses": 0, "venues": {}, "trades": [], "funding_l": [], "syms": set()}
        c["syms"].add(sym)
        return c

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
        c["realized" if kd == "REALIZED" else "fee" if kd == "FEE" else "funding"] += a
        v = venue(c, r.get("ex"), sym, a)
        if kd == "REALIZED":
            v["n"] += 1
    for t, a, k, ex, sym in fund_ev:
        coin(sym)["funding_l"].append({"ts": _ts_s(t), "exKey": ex, "ex": exn.get(ex, ex), "usd": round(a, 6), "krw": round(k)})
    unp = {}
    for i, gk in enumerate(order):
        g = groups[gk]
        c = coin(g["sym"])
        t_exit = max(g["ts"])
        priced = g["src"] != "none" and g["q"] > 0
        side = g["side"] if g["src"] != "none" or g["side"] else None
        entry_ts = None
        if priced and side:
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
        c["trades"].append(tr)
        c["closes"] += 1
        if g["pnl"] > 0:
            c["wins"] += 1
        elif g["pnl"] < 0:
            c["losses"] += 1
        if not priced:
            u = unp.setdefault(g["ex"], {})
            u[tr["why"]] = u.get(tr["why"], 0) + 1
    d0 = int(datetime.strptime(iso, "%Y-%m-%d").replace(tzinfo=KST).timestamp() * 1000)
    lo_o, hi_o = d0 - 36 * 3600 * 1000, d0 + DAY_MS
    out_coins = []
    for c in coins.values():
        ops = []
        for (ex, sym, side), lst in opens.items():
            if sym not in c["syms"]:
                continue
            for o in lst:
                if lo_o <= o["ts_ms"] < hi_o:
                    q = qty_of(ex, o)
                    if num(o.get("px")):
                        ops.append({"ts": _ts_s(o["ts_ms"]), "exKey": ex, "side": side, "px": _r(num(o["px"])), "q": _r(q) if q else None})
        ops.sort(key=lambda x: x["ts"])
        trs = c["trades"]
        if len(trs) > TRADES_MAX:
            keep = set(id(x) for x in sorted(trs, key=lambda x: -abs(x["pnl"]))[:TRADES_MAX])
            trs = [x for x in trs if id(x) in keep]
        trs.sort(key=lambda x: (x["exitTs"], x["id"]))
        vs = sorted(c["venues"].values(), key=lambda v: (-abs(v["usd"]), v["exKey"], v["symbol"]))
        for v in vs:
            v["usd"] = round(v["usd"], 6)
        out_coins.append({"coin": c["coin"], "label": c["label"], "usd": round(c["usd"], 6), "krw": round(c["krw"]),
                          "realized": round(c["realized"], 6), "fee": round(c["fee"], 6), "funding": round(c["funding"], 6),
                          "closes": c["closes"], "wins": c["wins"], "losses": c["losses"], "venues": vs,
                          "priced": {"n": sum(1 for x in c["trades"] if x["px"] != "none"), "of": len(c["trades"])},
                          "trades": trs, "tradesTotal": len(c["trades"]), "opens": ops[-OPENS_MAX:],
                          "fundingRows": sorted(c["funding_l"], key=lambda x: x["ts"]),
                          "looseFee": round(sum(a for t, a, k, ex, sym in loose_fee if sym in c["syms"]), 6)})
    out_coins.sort(key=lambda c: (-abs(c["usd"]), c["coin"]))
    wins = sum(c["wins"] for c in out_coins)
    losses = sum(c["losses"] for c in out_coins)
    return {"ok": True, "date": iso,
            "total": {"usd": round(tot_u, 2), "krw": round(tot_k), "realized": round(kinds["REALIZED"], 6), "fee": round(kinds["FEE"], 6),
                      "funding": round(kinds["FUNDING"], 6), "closes": sum(c["closes"] for c in out_coins), "wins": wins, "losses": losses,
                      "events": len(day)},
            "byEx": byex_fn(by_ex, exn).get(iso, []),
            "coins": out_coins,
            "other": {k: (round(v) if k == "krw" else round(v, 6)) for k, v in other.items()},
            "unpriced": [{"exKey": ex, "ex": exn.get(ex, ex), "n": sum(u.values()), "reason": max(u.items(), key=lambda kv: kv[1])[0]}
                         for ex, u in sorted(unp.items())],
            "stale": sorted(set(stale) & {r.get("ex") for _d, _t, _a, _k, r in day})}
