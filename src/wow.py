from __future__ import annotations

import math
import os
import re
import threading
from datetime import datetime, timedelta, timezone

import common

KST = timezone(timedelta(hours=9))
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
_EX_ORDER = ("binance", "bybit", "upbit", "okx", "gate", "bithumb", "kucoin")
_LOCK = threading.Lock()
_PX = {"sig": None, "by_sym": None}
_CACHE = {}


def _px_files():
    return (os.path.join(common.STATE_DIR, "curve_hist_px.json"), os.path.join(common.STATE_DIR, "daily_close_px.json"))


def _sig():
    out = []
    for p in _px_files():
        try:
            st = os.stat(p)
            out.append((p, st.st_mtime_ns, st.st_size))
        except OSError:
            out.append((p, None, None))
    return tuple(out)


def _clean(pmap) -> dict:
    out = {}
    if not isinstance(pmap, dict):
        return out
    for d, v in pmap.items():
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if _ISO.fullmatch(str(d)) and math.isfinite(f) and f > 0:
            out[str(d)] = f
    return out


def px_by_sym() -> dict:
    sig = _sig()
    with _LOCK:
        if _PX["sig"] == sig and _PX["by_sym"] is not None:
            return _PX["by_sym"]
    specs = {}
    for i, p in enumerate(_px_files()):
        try:
            d = common.read_json(p, {}) if os.path.exists(p) else {}
        except (SystemExit, Exception):
            d = {}
        if not isinstance(d, dict):
            continue
        src = (d.get("specs") if i == 0 else d.get("s")) or {}
        if not isinstance(src, dict):
            continue
        for k, v in src.items():
            pm = _clean((v or {}).get("p") if isinstance(v, dict) else None)
            if pm:
                specs.setdefault(str(k), {}).update(pm)
    rank = {}
    by_sym = {}
    for k, pm in specs.items():
        parts = k.split(":")
        if parts[0] == "sym" and len(parts) == 2:
            sym, r = parts[1].upper(), 0
        elif parts[0] == "ex" and len(parts) == 3:
            sym = parts[2].upper()
            r = 1 + (_EX_ORDER.index(parts[1]) if parts[1] in _EX_ORDER else len(_EX_ORDER))
        else:
            continue
        if sym not in by_sym or r < rank[sym]:
            by_sym[sym], rank[sym] = dict(pm), r
        elif r == rank[sym]:
            by_sym[sym].update(pm)
    with _LOCK:
        _PX.update(sig=sig, by_sym=by_sym)
    return by_sym


def _price_on(pm: dict, keys: list, iso: str):
    import bisect
    i = bisect.bisect_right(keys, iso) - 1
    if i < 0:
        return None
    d0 = keys[i]
    try:
        if (datetime.strptime(iso, "%Y-%m-%d") - datetime.strptime(d0, "%Y-%m-%d")).days > 7:
            return None
    except ValueError:
        return None
    return pm[d0]


_NOT_SALE_EX = ("유동성(DEX LP)", "스테이킹 보상")


def _not_sale(r) -> bool:
    return bool(r.get("fut") or r.get("ticker") == "LP" or str(r.get("ex") or "").startswith(_NOT_SALE_EX))


def _sells(idx, since_iso: str) -> dict:
    out = {}
    for r in idx.get("tax") or ():
        if _not_sale(r):
            continue
        d = str(r.get("sold") or "")
        if not _ISO.fullmatch(d) or d < since_iso:
            continue
        try:
            q = float(r.get("_qty", r.get("qty")) or 0)
            disp = float(r.get("_disp", r.get("xd", r.get("disp"))) or 0)
            acq = float(r.get("_acq", r.get("xa", r.get("acq"))) or 0)
        except (TypeError, ValueError):
            continue
        if not (q > 0 and disp > 0):
            continue
        k = (d, str(r.get("sym") or "?").upper())
        a = out.setdefault(k, [0.0, 0.0, 0.0])
        a[0] += q
        a[1] += disp
        a[2] += acq
    return out


def bench(idx, today_iso: str = None) -> dict:
    if not idx or idx.get("tax") is None:
        return {"hold": {}, "holdCov": None, "nSell": 0}
    today_iso = today_iso or datetime.now(KST).strftime("%Y-%m-%d")
    key = ("bench", idx.get("builtAt"), _sig(), today_iso)
    with _LOCK:
        if _CACHE.get("bench_k") == key:
            return _CACHE["bench_v"]
    since = (datetime.strptime(today_iso, "%Y-%m-%d") - timedelta(days=400)).strftime("%Y-%m-%d")
    sells = _sells(idx, since)
    pxs = px_by_sym()
    by_sym = {}
    tot, cov = 0.0, 0.0
    live = {}
    for (d, sym), (q, disp, _acq) in sells.items():
        tot += disp
        if sym in pxs:
            if sym not in live:
                pm = pxs[sym]
                live[sym] = _price_on(pm, sorted(pm), today_iso) is not None
            if live[sym]:
                cov += disp
            by_sym.setdefault(sym, []).append((d, q, disp))
    hold = {}
    if by_sym:
        d0 = min(d for v in by_sym.values() for d, _q, _p in v)
        days = []
        x = datetime.strptime(d0, "%Y-%m-%d")
        end = datetime.strptime(today_iso, "%Y-%m-%d")
        while x <= end:
            days.append(x.strftime("%Y-%m-%d"))
            x += timedelta(days=1)
        acc = dict.fromkeys(days, 0.0)
        for sym, rows in by_sym.items():
            pm = pxs[sym]
            keys = sorted(pm)
            rows.sort()
            j, cq, cp = 0, 0.0, 0.0
            for dd in days:
                while j < len(rows) and rows[j][0] <= dd:
                    cq += rows[j][1]
                    cp += rows[j][2]
                    j += 1
                if cq <= 0:
                    continue
                p = _price_on(pm, keys, dd)
                if p is None:
                    continue
                acc[dd] += cq * p - cp
        hold = {k: round(v, 2) for k, v in acc.items() if v}
    out = {"hold": hold, "holdCov": round(cov / tot, 4) if tot > 0 else None, "nSell": len(sells)}
    with _LOCK:
        _CACHE.update(bench_k=key, bench_v=out)
    return out


_AMT = re.compile(r"[-−]?\$?([\d,]+(?:\.\d+)?)")


def _usd_of(e) -> float:
    m = _AMT.search(str(e.get("a") or ""))
    try:
        return float(m.group(1).replace(",", "")) if m else 0.0
    except ValueError:
        return 0.0


def habits(idx, today_iso: str = None) -> dict:
    if not idx or idx.get("pos") is None or idx.get("tax") is None:
        return {"ok": False, "why": "building"}
    today_iso = today_iso or datetime.now(KST).strftime("%Y-%m-%d")
    key = ("habits", idx.get("builtAt"), _sig(), today_iso)
    with _LOCK:
        if _CACHE.get("hab_k") == key:
            return _CACHE["hab_v"]
    since = (datetime.strptime(today_iso, "%Y-%m-%d") - timedelta(days=365)).strftime("%Y-%m-%d")
    real, opened = {}, {}
    for p in idx["pos"]:
        if p.get("kind") in ("gas", "lp") or str(p.get("key", "")).startswith("lp:"):
            continue
        sym = str(p.get("sym") or "?").upper()
        ots = p.get("_ots")
        for d, v in (p.get("realizedByDay") or {}).items():
            if not _ISO.fullmatch(str(d)) or d < since:
                continue
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            k = (d, sym)
            real[k] = real.get(k, 0.0) + f
            if isinstance(ots, (int, float)) and ots > 0:
                prev = opened.get(k)
                if prev is None or abs(f) > prev[1]:
                    opened[k] = (float(ots), abs(f))
    when = {}
    for d, rows in (idx.get("ix") or {}).items():
        if not _ISO.fullmatch(str(d)) or d < since:
            continue
        for ts, kind, e, meta in rows:
            k9 = str(e.get("k") or "")
            if kind in ("hidden", "lp") or "매도" not in k9 or k9.startswith("LP"):
                continue
            sym = str((meta[1] if meta else None) or e.get("sym") or "?").upper()
            u = _usd_of(e)
            k = (d, sym)
            if k not in when or u > when[k][1]:
                when[k] = (int(ts or 0), u)
    grid = [[[0, 0] for _ in range(12)] for _ in range(7)]
    n = w = 0
    for k, r in real.items():
        if abs(r) < 1.0 or k not in when or not when[k][0]:
            continue
        dt = datetime.fromtimestamp(when[k][0], KST)
        c = grid[dt.weekday()][dt.hour // 2]
        c[0] += 1
        n += 1
        if r > 0:
            c[1] += 1
            w += 1
    BK = [(1, "하루 안"), (7, "1주 안"), (30, "1달 안"), (90, "3달 안"), (100000, "3달 넘게")]
    hold = [[lab, 0.0, 0.0, 0] for _d, lab in BK]
    sells = _sells(idx, since)
    for (d, sym), (q, disp, acq) in sells.items():
        o = opened.get((d, sym))
        if not o or acq <= 0:
            continue
        try:
            days = (datetime.strptime(d, "%Y-%m-%d") - datetime.fromtimestamp(o[0], KST).replace(tzinfo=None)).total_seconds() / 86400
        except (ValueError, OSError):
            continue
        for i, (lim, _lab) in enumerate(BK):
            if days < lim:
                hold[i][1] += acq
                hold[i][2] += disp - acq
                hold[i][3] += 1
                break
    pxs = px_by_sym()
    up = seen = 0
    chg = []
    for (d, sym), (q, disp, _acq) in sells.items():
        pm = pxs.get(sym)
        if not pm or q <= 0:
            continue
        nd = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        if nd >= today_iso or nd not in pm:
            continue
        sp = disp / q
        if sp <= 0:
            continue
        r = pm[nd] / sp - 1
        if abs(r) > 5:
            continue
        seen += 1
        chg.append(r)
        if r > 0.01:
            up += 1
    out = {"ok": True, "since": since, "n": n, "win": w, "grid": grid,
           "hold": [{"k": h[0], "cost": round(h[1], 2), "pnl": round(h[2], 2), "n": h[3]} for h in hold],
           "next": [up, seen], "nextAvg": round(sum(chg) / len(chg) * 100, 2) if chg else None}
    with _LOCK:
        _CACHE.update(hab_k=key, hab_v=out)
    return out
