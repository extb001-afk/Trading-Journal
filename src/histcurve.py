"""Long-range total-asset curve and daily close prices."""
from __future__ import annotations

import functools
import os
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone

import candles
import common
import xparts

log = common.setup_logging("tj-web")

KST = timezone(timedelta(hours=9))
HIST_V = 1
FLOW_V = 3
FIRST_DAY = "2026-01-01"
RUN_CALLS = 150
RUN_GAP_S = 600
ADOPT_GAP_S = 3600
MAX_TRIES = 3
DIRTY_MARGIN_S = 1800
SMALL_USD = 1.0
EPS = 1e-12
FFILL_DAYS = 10
FFILL_MIN_DENSITY = 0.5
STABLE_SYMS = {"USDT", "USDC", "DAI", "BUSD", "USDG", "USDE", "CUSD", "USD1", "NUSD", "USDM"}
GLOBAL_USD = ("binance", "bybit")
SYM_ORDER = tuple((v9, "USDT") for v9 in GLOBAL_USD) + (("coingecko", None), ("upbit", "KRW"), ("bithumb", "KRW"))
EX_QUOTE = {"upbit": "KRW", "bithumb": "KRW", "binance": "USDT", "bybit": "USDT", "okx": "USDT", "gate": "USDT", "kucoin": "USDT"}
PX1004_V = 1
RETRY_S = 12 * 3600
IDP_RETRY_S = RETRY_S


def day_end(iso) -> int:
    d = datetime.strptime(iso, "%Y-%m-%d").replace(tzinfo=KST)
    return int((d + timedelta(days=1)).timestamp())


def days_between(a, b):
    return list(_days_between_t(a, b))


@functools.lru_cache(maxsize=256)
def _days_between_t(a, b):
    d = datetime.strptime(a, "%Y-%m-%d")
    e = datetime.strptime(b, "%Y-%m-%d")
    if 1000 <= d.year and e.year <= 9999:
        return tuple(date.fromordinal(o).isoformat() for o in range(d.toordinal(), e.toordinal() + 1))
    out = []
    while d <= e:
        out.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return tuple(out)


def px_at(rows, T, step=86400, pts=False):
    if not rows:
        return None
    lo, hi = 0, len(rows)
    while lo < hi:
        mid = (lo + hi) // 2
        if rows[mid][0] <= T:
            lo = mid + 1
        else:
            hi = mid
    i = lo - 1
    if i < 0:
        return None
    r = rows[i]
    if pts:
        if i + 1 < len(rows) and rows[i + 1][0] - r[0] <= 2 * 86400 and rows[i + 1][0] > r[0]:
            a, b = r, rows[i + 1]
            return a[4] + (b[4] - a[4]) * (T - a[0]) / (b[0] - a[0])
        return r[4] if T - r[0] <= 2 * 86400 else None
    if T < r[0] + step:
        if r[1] > 0 and r[4] > 0 and max(r[1] / r[4], r[4] / r[1]) > 3:
            return r[4]
        return r[1] + (r[4] - r[1]) * (T - r[0]) / step
    return r[4] if T - (r[0] + step) <= 3 * 86400 else None


def _row_idx(rows, T):
    lo, hi = 0, len(rows or ())
    while lo < hi:
        mid = (lo + hi) // 2
        if rows[mid][0] <= T:
            lo = mid + 1
        else:
            hi = mid
    return lo - 1 if lo > 0 else None


def banned_src(src) -> bool:
    for s9 in src or ():
        v9, _, mk9 = str(s9).partition(":")
        if "-" in mk9 and candles.banned_market(v9, mk9.split("-", 1)[0]):
            return True
    return False


def entry_venue(e, iso):
    ps9 = e.get("ps") if isinstance(e.get("ps"), dict) else {}
    src9 = [x for x in e.get("src") or () if x]
    lab9 = ps9.get(iso) or (src9[0] if len(src9) == 1 else None)
    return str(lab9).split(":", 1)[0] if lab9 else "?"


def clean_entry(e, blocked):
    if not isinstance(e, dict) or not blocked or not isinstance(e.get("p"), dict):
        return e
    src9 = [x for x in e.get("src") or () if x]
    amb9 = not isinstance(e.get("ps"), dict) and len(src9) > 1 and any(str(x).split(":", 1)[0] in blocked for x in src9)
    p9 = {} if amb9 else {d9: v9 for d9, v9 in e["p"].items() if entry_venue(e, d9) not in blocked}
    if len(p9) == len(e["p"]):
        return e
    return dict(e, p=p9, st="cleaned", pend=sorted(set(e.get("pend") or ()) | (set(e["p"]) - set(p9))))


def pend_days(e) -> set:
    if not isinstance(e, dict):
        return set()
    return set(e.get("pend") or ())


def pmap_of(e, upto):
    if not isinstance(e, dict):
        return {}
    pd9 = pend_days(e)
    pm9 = {d9: v9 for d9, v9 in (e.get("p") or {}).items() if d9 not in pd9}
    ff9 = ffill_map(pm9, upto)
    if not pd9 or not ff9:
        return ff9
    out9, cut9 = {}, False
    for d9 in days_between(min(ff9), max(ff9)):
        if d9 in pd9:
            cut9 = True
        elif d9 in pm9 and pm9[d9]:
            cut9 = False
            out9[d9] = ff9[d9]
        elif d9 in ff9 and not cut9:
            out9[d9] = ff9[d9]
    return out9


def served_map(e, upto=None) -> dict:
    if not isinstance(e, dict) or not isinstance(e.get("p"), dict):
        return {}
    pm9 = pmap_of(e, upto if upto is not None else (e.get("hi") or ""))
    own9 = {d9 for d9, v9 in e["p"].items() if v9} - pend_days(e)
    out9, src9 = {}, None
    for d9 in sorted(pm9):
        if d9 in own9:
            src9 = d9
        out9[d9] = (pm9[d9], entry_venue(e, src9) if src9 else "?")
    return out9


def served_days(e, venues) -> set:
    return {d9 for d9, (_v9, ven9) in served_map(e).items() if ven9 in venues or ven9 == "?"}


def is_final(e) -> bool:
    return isinstance(e, dict) and e.get("st") in ("ok", "none")


def day_state(e, iso, pm) -> str:
    if not isinstance(e, dict) or iso in pend_days(e):
        return "retry"
    v9 = (pm or {}).get(iso)
    if v9 and v9 > 0:
        return "ok"
    return "none" if is_final(e) else "retry"


def due(e, now) -> bool:
    if not isinstance(e, dict):
        return True
    st = e.get("st")
    if st in ("ok", "none"):
        return False
    if st == "wait" or (st == "err" and int(e.get("n") or 0) < MAX_TRIES):
        return True
    return now - int(e.get("at") or 0) >= RETRY_S


_MB_MEMO = {}
MB_TTL_S = 120


def map_blocked(spec, now=None) -> set:
    kind, _, rest = str(spec or "").partition(":")
    if kind != "ex":
        return set()
    v0, _, b = rest.partition(":")
    if EX_QUOTE.get(v0) != "KRW" or not b:
        return set()
    t9 = time.time()
    m9 = _MB_MEMO.get(spec)
    if m9 and t9 - m9[0] < MB_TTL_S:
        return set(m9[1])
    out9 = {v for v in GLOBAL_USD if candles.same_coin(v0, v, b, now=now, fetch=False)[0] is False}
    if len(_MB_MEMO) > 5000:
        _MB_MEMO.clear()
    _MB_MEMO[spec] = (t9, frozenset(out9))
    return out9


def map_blocked_days(spec, e, venues=None) -> set:
    mb9 = set(venues) if venues is not None else map_blocked(spec)
    if not mb9 or not isinstance(e, dict):
        return set()
    amb9 = any(str(x).split(":", 1)[0] in mb9 for x in e.get("src") or ())
    return {d9 for d9, (_v9, ven9) in served_map(e).items() if ven9 in mb9 or (ven9 == "?" and amb9)}


def blocked_union(*entries) -> set:
    out = set()
    for x in entries:
        if isinstance(x, dict):
            out |= set(x.get("blk") or ())
    return out


def view(e, blocked, borrowed=False, spec=None):
    b9 = set(blocked or ())
    if borrowed and isinstance(e, dict) and spec:
        kd9, _, r9 = str(spec).partition(":")
        if kd9 == "sym" or (kd9 == "ex" and r9.split(":", 1)[0] in ("upbit", "bithumb")):
            b9 |= set(GLOBAL_USD) - set(e.get("idok") or ())
    return clean_entry(e, b9) if b9 else e


def stale_src(k, src) -> bool:
    if banned_src(src):
        return True
    kind9, _, rest9 = str(k).partition(":")
    if kind9 == "sym" or (kind9 == "ex" and rest9.split(":", 1)[0] in ("upbit", "bithumb")):
        return any(str(s9).split(":", 1)[0] in ("okx", "gate", "kucoin") for s9 in src or ())
    return False


def ffill_map(pm, upto):
    out9, last9, gap9 = {}, None, 0
    if pm and len(pm) < FFILL_MIN_DENSITY * len(days_between(min(pm), max(pm))):
        out9 = dict(pm)
    elif pm:
        for iso9 in days_between(min(pm), max(upto, max(pm))):
            if pm.get(iso9):
                last9, gap9 = pm[iso9], 0
            else:
                gap9 += 1
            if last9 is not None and gap9 <= FFILL_DAYS:
                out9[iso9] = pm.get(iso9) or last9
    return out9


def ap_flag(val, est, xc) -> int:
    return 1 if (float(est or 0) + float(xc or 0)) >= max(50.0, 0.005 * abs(float(val or 0))) else 0


def base_sym(sym):
    return re.sub(r"[^A-Za-z0-9]", "", str(sym or "").split("#", 1)[0]).upper()


def group_desc(gid, g, ca_gids, ex_gid, major_gids, override_px, pairs, stable_syms=None):
    stable_syms = stable_syms or STABLE_SYMS
    ca = gid in ca_gids
    ex = ex_gid.get(gid)
    ov = override_px.get(gid)
    sym = str(g.get("sym") or "")
    return {"sym": sym, "st": bool(g.get("is_stable")),
            "fake": (not g.get("is_stable") and sym in stable_syms and not ca and not ex and ov is None),
            "ca": [(str(c), str(a)) for c, a in (pairs.get(gid) or ())] if ca else None,
            "ex": ex, "maj": gid in (major_gids or ()), "ov": float(ov) if ov is not None else None}


def make_kit(today_iso, G, hold_qty, skip_gids, ca_gids, ex_gid, major_gids, override_px, live_px, pairs, transit,
             extra, daily_rows, daily_cache, stable_syms=None, first_day=FIRST_DAY, flow_kit=None, neg_ok=None, xkit=None, rb_days=None):
    stable_syms = stable_syms or STABLE_SYMS
    groups = {}
    for gid, g in G.items():
        if g.get("is_fiat"):
            continue
        tl = g.get("qty_timeline") or ()
        hq = hold_qty.get(gid)
        if not tl and not hq:
            continue
        groups[gid] = dict(group_desc(gid, g, ca_gids, ex_gid, major_gids, override_px, pairs, stable_syms),
                           skip=gid in (skip_gids or ()), lp=float(live_px.get(gid) or 0), hold=float(hq or 0),
                           tl=sorted((int(ts), float(dq)) for ts, dq in tl))
        if neg_ok and gid in neg_ok:
            groups[gid]["neg"] = True
    n = len(daily_rows or ())
    t0 = datetime.strptime(today_iso, "%Y-%m-%d")
    rows = []
    for i, r in enumerate(daily_rows or ()):
        iso = (t0 - timedelta(days=n - 1 - i)).strftime("%Y-%m-%d")
        if iso >= today_iso:
            continue
        v = r.get("val")
        if not isinstance(v, (int, float)):
            continue
        k = r.get("valKrw")
        fl = r.get("flow")
        fl = (round(float(fl), 2), [[str(t[0]), round(float(t[1]), 2)] for t in (r.get("flowTop") or ())][:3]) \
            if isinstance(fl, (int, float)) and not isinstance(fl, bool) else None
        rows.append([iso, round(float(v), 2), round(float(k)) if isinstance(k, (int, float)) and not isinstance(k, bool) else None,
                     ap_flag(v, r.get("est"), r.get("xc")), float(r.get("usdt") or 0) or None,
                     round(float(r.get("est") or 0) + float(r.get("xc") or 0), 2), fl])
    xk = dict(xkit or {})
    if not isinstance(xk.get("src"), dict):
        x_now = float(extra.get("ub") or 0) + float(extra.get("fiat") or 0) + float(extra.get("lp") or 0)
        xk = {"src": {"now": {"ts": time.time(), "ku": 0.0, "kb": 0.0, "ub": {}, "rest": x_now}}, "obs": {}, "days": {}}
    sym_tl = {}
    for gid9, tl9 in sorted((extra.get("ub_tl") or {}).items() if isinstance(extra.get("ub_tl"), dict) else ()):
        if gid9 in groups:
            sym_tl.setdefault(str(groups[gid9].get("sym") or "").upper(), []).append((gid9, [(int(t), float(d)) for t, d in tl9]))
    xk["sym_tl"] = sym_tl
    xk["rate"] = float(extra.get("rate") or 0) or None
    win9 = {r[0] for r in rows}
    lo9 = min(win9) if win9 else today_iso
    dcv = {}
    for iso, c in sorted((daily_cache or {}).items()):
        if not (isinstance(c, dict) and len(str(iso)) == 10 and str(iso)[4] == "-" and str(iso) < lo9 and str(iso) in (xk.get("days") or {})
                and c.get("xraw") is not None and isinstance(c.get("val"), (int, float))):
            continue
        u9 = float(c.get("usdt") or 0)
        v9 = round(float(c["val"]) + float((rb_days or {}).get(iso) or 0), 2)
        ap9 = ap_flag(v9, c.get("est"), c.get("xc"))
        dcv[iso] = [v9, round(v9 * u9) if u9 > 0 else None, ap9, "dc", round(float(c.get("est") or 0) + float(c.get("xc") or 0), 2) if ap9 else 0]
    return {
        "v": HIST_V, "today": today_iso, "first": first_day, "groups": groups,
        "transit": [(e["gid"], int(e["ts"]), float(e["qty"])) for e in (transit or ())],
        "xk": xk, "dcv": dcv,
        "daily": rows, "made": time.time(), "fk": flow_kit,
    }


def rewind(kit, days):
    ends = sorted(((day_end(d) - 1, d) for d in days), reverse=True)
    tr = {}
    for gid, ts, q in kit.get("transit") or ():
        tr.setdefault(gid, []).append((ts, q))
    out = {}
    for gid, g in kit["groups"].items():
        q = g["hold"]
        tl = g["tl"]
        j = len(tl) - 1
        res = {}
        for e, d in ends:
            while j >= 0 and tl[j][0] > e:
                q -= tl[j][1]
                j -= 1
            qq = q - sum(tq for t9, tq in tr.get(gid, ()) if e < t9)
            if qq > EPS or (g.get("neg") and qq < -EPS):
                res[d] = qq
        if res:
            out[gid] = res
    return out


def spec_of(g):
    if g.get("ov") is not None:
        return "ov"
    if g.get("st"):
        return "stable"
    if g.get("fake"):
        return None
    if g.get("ex") == "hyperliquid":
        import hl_spot
        k = str(g.get("sym") or "").upper()
        m = hl_spot.SAME_COIN.get(k)
        if m:
            return "stable" if m[0] in hl_spot.STABLE_FACE else f"sym:{m[0]}"
        return f"ex:hyperliquid:{k}" if re.fullmatch(r"[A-Z0-9]{1,20}(@[0-9]{1,7})?", k) else None
    b = base_sym(g["sym"])
    if g.get("maj") or (not g.get("ca") and not g.get("ex")):
        return f"sym:{b}" if b else None
    if g.get("ex"):
        return f"ex:{g['ex']}:{b}" if b and g["ex"] in EX_QUOTE else None
    for c, a in g.get("ca") or ():
        if c in candles.CG_PLATFORM or c in candles.GT_NETWORK:
            if not valid_addr(c, a):
                continue
            return f"ca:{c}:{a.lower() if c != 'sol' else a}"
    return None


_EVM_ADDR = re.compile(r"0x[0-9a-fA-F]{40}")
_SOL_ADDR = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")


def valid_addr(chain, a) -> bool:
    return isinstance(a, str) and bool((_SOL_ADDR if chain == "sol" else _EVM_ADDR).fullmatch(a))


def off_chains_now() -> set:
    try:
        cfg = common.read_json(common.CONFIG_PATH, {}) or {}
    except (Exception, SystemExit):
        return set()
    ch = cfg.get("chains") if isinstance(cfg.get("chains"), dict) else {}
    return {c for c, cc in ch.items() if isinstance(cc, dict) and not common.chain_enabled(c, cc)}


def spec_off(k, off) -> bool:
    return bool(off) and str(k).startswith("ca:") and str(k).split(":", 2)[1] in off


def span(lo, hi):
    t0 = (day_end(lo) // 86400 - 4) * 86400
    t1 = (day_end(hi) // 86400 + 1) * 86400
    return t0, t1


def _prev_fails(e, lo, hi) -> int:
    return int(e.get("n") or 0) if (e.get("lo") or "9999") <= lo and (e.get("hi") or "") >= hi else 0


def fetch_fx_entry(lo, hi, now, prev=None):
    t0, t1 = span(lo, hi)
    r = candles.fetch_cex("upbit", "USDT", "KRW", "1d", t0, t1, now=now)
    e = prev if isinstance(prev, dict) else {}
    if r.ok:
        p = {iso: round(v, 4) for iso in days_between(lo, hi) for v in [px_at(r.candles, day_end(iso))] if v}
        return {"st": "ok", "lo": lo, "hi": hi, "p": p, "src": "upbit:KRW-USDT", "at": int(now)}
    st = "wait" if r.why == "budget" else "err"
    return {"st": st, "n": _prev_fails(e, lo, hi) + (1 if st == "err" else 0), "lo": lo, "hi": hi, "p": e.get("p") or {}, "why": r.why,
            "at": int(now)}


HL_CALLS_PER_FETCH = 2


def _hl_charge() -> bool:
    b = getattr(candles._TL, "bud", None)
    if b is None:
        return True
    if candles._bud_left(b) < HL_CALLS_PER_FETCH:
        return False
    for _i in range(HL_CALLS_PER_FETCH):
        candles._bud_take(b)
    with candles._CALL_LOCK:
        candles.CALLS["n"] += HL_CALLS_PER_FETCH
        candles.CALLS["by_host"]["api.hyperliquid.xyz"] = candles.CALLS["by_host"].get("api.hyperliquid.xyz", 0) + HL_CALLS_PER_FETCH
    return True


def fetch_entry(k, lo, hi, now, need=None, fx_get=None, prev=None, xref=None, blocked=None):
    t0, t1 = span(lo, hi)
    days = days_between(lo, hi)
    need = set(need or days)
    p, srcs, whys, transient = {}, [], [], False
    waiting, fx_miss = False, False
    fx_get = fx_get or (lambda iso: None)
    ps = {}

    def take(rows, conv=None, is_pts=False, label=""):
        nonlocal fx_miss
        n9 = 0
        for iso in days:
            if iso in p:
                continue
            v = px_at(rows, day_end(iso), pts=is_pts)
            if v and conv is not None:
                f9 = fx_get(iso)
                if not f9:
                    fx_miss = True
                v = v / f9 if f9 else None
            if v and v > 0:
                p[iso] = v
                ps[iso] = label
                n9 += 1
        if n9:
            srcs.append(label)

    def fail(r, tag):
        nonlocal transient, waiting
        whys.append(f"{tag}:{r.why}")
        transient = transient or r.why in ("net", "time", "bad")
        waiting = waiting or r.why == "budget"

    def filled():
        return need <= set(p)

    rejv = {}
    mapx9 = set()
    proven9 = set()
    conf9 = set()
    idok9 = set(((prev or {}).get("idok") or ()) if isinstance(prev, dict) else ())
    prevp = {d9: float(v9) for d9, v9 in ((prev or {}).get("p") or {}).items() if v9} if isinstance(prev, dict) else {}
    cgr = {}

    def cg_rows(cid, keyed=False):
        if cid not in cgr:
            cgr[cid] = candles.fetch_cg_id(cid, t0, t1, now=now, keyed=keyed)
        return cgr[cid]

    own9 = {}
    _pps = (prev or {}).get("ps") if isinstance((prev or {}).get("ps"), dict) else {}
    _psrc = [s9 for s9 in ((prev or {}).get("src") or ()) if s9] if isinstance(prev, dict) else []

    blk_prev = (set((prev or {}).get("blk") or ()) if isinstance(prev, dict) else set()) | set(blocked or ())
    idp9 = [False]
    idq9 = [False]
    unv9 = set()

    def prev_venue(iso):
        lab9 = _pps.get(iso) or (_psrc[0] if len(_psrc) == 1 else None)
        return (str(lab9).split(":", 1)[0], str(lab9)) if lab9 else ("?", "")

    mapv9 = {}

    def map_verdict(v2, b, holder):
        k9 = (v2, b, holder)
        if k9 not in mapv9:
            mapv9[k9] = candles.same_coin(holder, v2, b, now=now, fetch=True)
            if mapv9[k9][0] is False:
                mapx9.add(v2)
        return mapv9[k9]

    def ident(v, b, rows, holder):
        ok9, note9 = map_verdict(v, b, holder)
        if ok9 is not None:
            return ok9, note9
        refs9 = {}
        cid9 = candles.holder_cg_id(holder, b, now=now, fetch=True) if holder else None
        if cid9:
            r9 = cg_rows(cid9)
            if r9.ok:
                for iso in days:
                    x9 = px_at(r9.candles, day_end(iso), pts=True)
                    if x9:
                        refs9.setdefault(iso, (x9, f"코인게코 {cid9}"))
        for iso, x9 in own9.items():
            refs9.setdefault(iso, (x9, "보유 거래소 원화 시세"))
        for iso, x9 in prevp.items():
            pv9, lab9 = prev_venue(iso)
            if pv9 == v or pv9 == "?":
                continue
            if (holder and pv9 == holder) or (cid9 and lab9 == f"coingecko:{cid9}") or (
                    pv9 in GLOBAL_USD and map_verdict(pv9, b, holder)[0] is True):
                refs9.setdefault(iso, (x9, "지난 값"))
        rs9 = sorted((px_at(rows, day_end(iso)) or 0) / refs9[iso][0] for iso in days if iso in refs9 and px_at(rows, day_end(iso)))
        if not rs9:
            return None, "기준 없음"
        r9 = rs9[len(rs9) // 2]
        nm9 = next(iter(refs9.values()))[1]
        if candles.IDENT_LO <= r9 <= candles.IDENT_HI:
            return True, f"{nm9} 기준 {r9:.2f}배"
        return False, f"{candles.VENUE_KO.get(v, v)} {b} 시세가 {nm9}의 {r9:.2f}배 — 동명 다른 코인 의심"

    def med_ratio(rows_a, rows_b):
        xs9 = sorted(px_at(rows_a, day_end(iso)) / px_at(rows_b, day_end(iso)) for iso in days
                     if px_at(rows_a, day_end(iso)) and px_at(rows_b, day_end(iso)))
        return xs9[len(xs9) // 2] if xs9 else None

    def usd_venue(v, q, b, holder):
        if holder and map_verdict(v, b, holder)[0] is False:
            note9 = map_verdict(v, b, holder)[1]
            proven9.add(v)
            rejv[v] = note9
            whys.append(f"{v}:동명:{note9}"[:160])
            return True
        r = candles.fetch_cex(v, b, q, "1d", t0, t1, now=now)
        if not r.ok:
            fail(r, f"{v}:{candles.market_name(v, b, q)}")
            return r.why != "budget"
        ok9, note9 = ident(v, b, r.candles, holder)
        pf9 = ok9 is False
        if v in blk_prev and ok9 is not True:
            if ok9 is None:
                idp9[0] = True
                note9 = f"{candles.VENUE_KO.get(v, v)} {b} = 전에 다른 코인으로 막힘(코인게코 매핑·기준가 확인 전엔 안 씀)"
            ok9, pf9 = False, True
        unv_here9 = False
        if ok9 is None:
            for v2 in GLOBAL_USD:
                if v2 == v or v2 in proven9 or v2 in blk_prev or map_verdict(v2, b, holder)[0] is False:
                    continue
                r2 = candles.fetch_cex(v2, b, "USDT", "1d", t0, t1, now=now)
                if not r2.ok and r2.why in ("net", "time", "bad", "budget"):
                    fail(r2, f"{v2}:비교")
                    if r2.why == "budget":
                        return False
                    idq9[0] = True
                    unv_here9 = True
                    break
                x9 = med_ratio(r.candles, r2.candles) if r2.ok else None
                if x9 is not None and not (candles.IDENT_LO <= x9 <= candles.IDENT_HI):
                    ok9, note9 = False, (f"{candles.VENUE_KO.get(v, v)}·{candles.VENUE_KO.get(v2, v2)} {b} 시세가 {x9:.2f}배 달라 "
                                         f"같은 코인인지 확인 불가(코인게코 매핑·기준가 없음)")
                    idp9[0] = True
                    break
        if ok9 is True:
            idok9.add(v)
            conf9.add(v)
        if ok9 is False:
            if pf9:
                proven9.add(v)
            if not pf9 or v not in mapx9:
                idp9[0] = True
            rejv[v] = note9
            whys.append(f"{v}:동명:{note9}"[:160])
            return True
        had9 = set(p)
        take(r.candles, label=f"{v}:{candles.market_name(v, b, q)}")
        if unv_here9:
            unv9.update(set(p) - had9)
        return True

    def cg_venue(cid):
        if not cid:
            return
        r = cg_rows(cid, keyed=True)
        if r.ok:
            take(r.candles, is_pts=True, label=f"coingecko:{cid}")
        else:
            fail(r, "cg")

    def sym_cg_id(b):
        if candles.KNOWN_CG_ID.get(str(b).upper()):
            return candles.KNOWN_CG_ID[str(b).upper()]
        ids9, unk9 = set(), False
        for ex9 in candles.CG_EX_ID:
            x9 = candles.cg_ids(ex9, b, now=now, fetch=False)
            unk9 = unk9 or x9 is None
            ids9 |= x9 or set()
        if len(ids9) != 1 and unk9:
            idp9[0] = True
        return next(iter(ids9)) if len(ids9) == 1 else None

    kind, _, rest = k.partition(":")
    if kind == "sym":
        b = rest
        for v, q in SYM_ORDER:
            if filled() or len(srcs) >= 3:
                break
            if v == "coingecko":
                cg_venue(sym_cg_id(b))
                continue
            if v in GLOBAL_USD:
                if not usd_venue(v, q, b, None):
                    break
                continue
            r = candles.fetch_cex(v, b, q, "1d", t0, t1, now=now)
            if r.ok:
                take(r.candles, conv=(q == "KRW") or None, label=f"{v}:{candles.market_name(v, b, q)}")
            else:
                fail(r, v)
                if r.why == "budget":
                    break
    elif kind == "ex" and rest.startswith("hyperliquid:"):
        b = rest.split(":", 1)[1]
        import hl_spot
        if _hl_charge():
            r = hl_spot.daily_candles(b, t0, t1, now=now)
        else:
            r = candles.Result(why="budget", note="호출 예산")
        if r.ok:
            take(r.candles, label=f"hyperliquid:{b}")
        else:
            fail(r, f"hyperliquid:{b}")
    elif kind == "ex":
        v0, _, b = rest.partition(":")
        q0 = EX_QUOTE.get(v0)
        if q0 == "KRW":
            for v in GLOBAL_USD:
                map_verdict(v, b, v0)
        r = candles.fetch_cex(v0, b, q0, "1d", t0, t1, now=now)
        if r.ok:
            take(r.candles, conv=(q0 == "KRW") or None, label=f"{v0}:{candles.market_name(v0, b, q0)}")
            own9.update({iso: v9 for iso, v9 in p.items()})
        else:
            fail(r, f"{v0}:{candles.market_name(v0, b, q0)}")
        own_ok9 = r.ok or r.why in ("no_market", "no_data", "too_old")
        if q0 == "KRW" and own_ok9 and r.why != "budget":
            for v in GLOBAL_USD:
                if filled() or not usd_venue(v, "USDT", b, v0):
                    break
            if not filled() and not waiting:
                cid9 = candles.holder_cg_id(v0, b, now=now, fetch=True)
                if cid9 is None and candles.cg_ids(v0, b, now=now, fetch=False) is None:
                    idp9[0] = True
                cg_venue(cid9)
    elif kind == "ca":
        ch, _, tk = rest.partition(":")
        r = candles.fetch_cg(ch, tk, t0, t1, now=now)
        if r.ok:
            take(r.candles, is_pts=True, label="coingecko")
        else:
            fail(r, "cg")
        gt_lo = (datetime.fromtimestamp(now - candles.GT_MAX_AGE_S, KST) + timedelta(days=1)).strftime("%Y-%m-%d")
        miss = [x for x in need if x not in p and x >= gt_lo]
        if miss and ch in candles.GT_NETWORK and not (waiting and not r.ok):
            t0g = max(t0, (int(now - candles.GT_MAX_AGE_S) // 86400 + 1) * 86400)
            rg, _sp = candles.fetch_spec({"venue": "dex", "chain": ch, "token": tk}, "1d", t0g, t1, now=now, res="day")
            if rg.ok:
                take(rg.candles, label="geckoterminal")
            else:
                fail(rg, "gt")
    e = prev if isinstance(prev, dict) else {}
    fresh9 = set(p)
    drop9 = set()
    used9 = {str(l9).split(":", 1)[0] for l9 in ps.values()}
    blk9 = ((set(e.get("blk") or ()) - conf9) | (mapx9 & set(GLOBAL_USD))) - used9
    drop9v = blk9 | set(rejv)
    pps9 = e.get("ps") if isinstance(e.get("ps"), dict) else {}
    psrc9 = [s9 for s9 in e.get("src") or () if s9]
    one9 = psrc9[0] if len(psrc9) == 1 else None
    amb9 = bool(drop9v) and not pps9 and len(psrc9) > 1 and any(str(s9).split(":", 1)[0] in drop9v for s9 in psrc9)
    gone9 = set()
    if isinstance(e.get("p"), dict) and e["p"]:
        for iso, v in e["p"].items():
            if not v or iso in p:
                continue
            if iso in drop9:
                gone9.add(iso)
                continue
            lab9 = pps9.get(iso) or one9
            if amb9 or (lab9 and str(lab9).split(":", 1)[0] in drop9v):
                gone9.add(iso)
                continue
            p[iso] = float(v)
            if lab9:
                ps[iso] = lab9
        for s9 in psrc9:
            if s9 not in srcs and not banned_src([s9]) and str(s9).split(":", 1)[0] not in drop9v and not amb9:
                srcs.append(s9)
    short = not need <= set(p)
    gated9 = bool(rejv) or bool(blk_prev & {v9 for v9 in GLOBAL_USD}) or bool(gone9 & need)
    if waiting and short:
        st = "wait"
    elif (transient or fx_miss) and (short or idq9[0]):
        st = "err"
    elif (idp9[0] or gated9) and short:
        st = "idp"
    elif p:
        st = "ok"
    else:
        st = "none"
    if fx_miss:
        whys.append("fx:missing")
    pend9 = {d9 for d9 in (e.get("pend") or ()) if d9 not in fresh9 and lo <= d9 <= hi} if isinstance(e.get("pend"), list) else set()
    pend9 |= unv9 & set(p)
    if st == "idp":
        pend9 |= {d9 for d9 in need if d9 not in p}
    if pend9 and st in ("ok", "none"):
        st = "idp"
    out = {"st": st, "n": _prev_fails(e, lo, hi) + (1 if st == "err" else 0), "lo": lo, "hi": hi,
           "p": {iso: float(f"{v:.10g}") for iso, v in p.items()}, "src": srcs, "why": whys[:6], "at": int(now)}
    if pend9:
        out["pend"] = sorted(pend9)
    if rejv:
        out["rejv"] = rejv
    if blk9:
        out["blk"] = sorted(blk9)
    if idok9 - blk9:
        out["idok"] = sorted(idok9 - blk9)
    if len(set(ps.values())) > 1:
        out["ps"] = {iso: ps[iso] for iso in sorted(ps) if iso in p}
    out["_drop"] = sorted(gone9)
    sv0 = served_map(e)
    sv1 = served_map(dict(out, ps=out.get("ps") or ps), max(hi, e.get("hi") or "")) if sv0 else {}
    chg9 = []
    for iso, (v, pv9) in sv0.items():
        nv, nv9 = sv1.get(iso, (None, "?"))
        if nv is None or abs(float(nv) - float(v)) > 1e-9 * max(1.0, abs(float(v))) or (pv9 != "?" and nv9 != "?" and pv9 != nv9):
            chg9.append(iso)
    out["_chg"] = sorted(chg9)
    return out


def xref_fn(k, stores):
    kind, _, rest = str(k).partition(":")
    if kind not in ("sym", "ex"):
        return None
    b = rest.rsplit(":", 1)[-1]
    others = []
    for st9 in stores:
        for k9, e9 in (st9 or {}).items():
            if k9 == k or not isinstance(e9, dict) or not isinstance(e9.get("p"), dict) or banned_src(e9.get("src")):
                continue
            kd9, _, r9 = str(k9).partition(":")
            if kd9 in ("sym", "ex") and r9.rsplit(":", 1)[-1] == b and not stale_src(k9, e9.get("src")):
                others.append(({str(s9).split(":", 1)[0] for s9 in e9.get("src") or ()}, e9["p"]))
    if not others:
        return None
    return lambda iso, excl=None: [float(p9[iso]) for vs9, p9 in others if p9.get(iso) and not (excl and excl in vs9)]


class HistCurve:
    def __init__(self, path=None, px_path=None, run_calls=RUN_CALLS, gap=RUN_GAP_S):
        self.path = path or os.path.join(common.STATE_DIR, "curve_hist.json")
        self.px_path = px_path or os.path.join(common.STATE_DIR, "curve_hist_px.json")
        self.run_calls = run_calls
        self.gap = gap
        self.lock = threading.Lock()
        self.run_lock = threading.Lock()
        self.ev = threading.Event()
        self.kit = None
        self.last_offer = 0.0
        self.last_run = None
        self.flow_fn = None
        st = common.read_json(self.path, None) if os.path.exists(self.path) else None
        self.st = st if isinstance(st, dict) and st.get("_v") == HIST_V else {"_v": HIST_V, "d": {}, "s": {}, "meta": {}}
        if isinstance(st, dict) and st.get("_v") != HIST_V:
            self.st["d"] = {k: v for k, v in (st.get("d") or {}).items() if isinstance(v, list) and len(v) >= 4 and v[3] == "dc"}
            self.st["f"] = {k: v for k, v in (st.get("f") or {}).items() if isinstance(v, list) and len(v) >= 4 and v[3] == "dc"}
        f9 = self.st.get("f") if isinstance(self.st.get("f"), dict) else {}
        fv_new9 = self.st.get("fv") != FLOW_V
        if fv_new9:
            f9 = {k: v for k, v in f9.items() if isinstance(v, list) and len(v) >= 4 and v[3] == "dc"}
        self.st["f"], self.st["fv"] = f9, FLOW_V
        px = common.read_json(self.px_path, None) if os.path.exists(self.px_path) else None
        self.px = px if isinstance(px, dict) and px.get("_v") == 1 else {"_v": 1, "specs": {}, "fx": None}
        m9 = self.st.get("meta") or {}
        self.pending = bool(m9.get("pending", True))
        self.progress = dict(m9.get("progress") or {"specs": 0, "done": 0, "pending": None}, calls=int(m9.get("calls") or 0))
        self.flow_pending = fv_new9 or bool(m9.get("flow_pending", True))
        self.flow_fails = 0
        self.dirty_fails = 0
        self.dirty_fail_key = None

    def _dirty_marks(self):
        try:
            cur = common.read_json(os.path.join(common.STATE_DIR, common.HIST_DIRTY), None)
        except SystemExit:
            return []
        return [m for m in ((cur or {}).get("marks") or []) if isinstance(m, list) and len(m) >= 3] if isinstance(cur, dict) else []

    def _dirty_ready(self, made):
        ms = [m for m in self._dirty_marks() if float(m[2]) < float(made) - DIRTY_MARGIN_S]
        return (min(m[1] for m in ms), {int(m[0]) for m in ms}) if ms else None

    @staticmethod
    def _dirty_key(ready):
        return (ready[0], max(ready[1])) if ready else None

    def _dirty_blocked(self, ready) -> bool:
        return bool(ready) and self.dirty_fails >= MAX_TRIES and self._dirty_key(ready) == self.dirty_fail_key

    def _dirty_take(self, made):
        ready = self._dirty_ready(made)
        if ready is None:
            return None
        if self._dirty_key(ready) != self.dirty_fail_key:
            self.dirty_fails, self.dirty_fail_key = 0, None
        return None if self._dirty_blocked(ready) else ready

    def _dirty_done(self, seqs):
        def upd(cur):
            if not cur:
                return None
            left = [m for m in (cur.get("marks") or []) if isinstance(m, list) and len(m) >= 3 and int(m[0]) not in seqs]
            return dict(cur, marks=left, **{"from": min(m[1] for m in left)}) if left else None
        common.hist_dirty_update(upd)

    def need(self, today_iso, now=None) -> bool:
        now = time.time() if now is None else now
        if now - self.last_offer < self.gap:
            return False
        m = self.st.get("meta") or {}
        rd9 = self._dirty_ready(now)
        return bool(self.pending or (self.flow_pending and self.flow_fn is not None and self.flow_fails < MAX_TRIES)
                    or (rd9 is not None and not self._dirty_blocked(rd9))
                    or m.get("adopted_day") != today_iso or now - float(m.get("adopted_at") or 0) >= ADOPT_GAP_S)

    def offer(self, today_iso, kit_fn, now=None) -> bool:
        if not self.need(today_iso, now):
            if self.kit is None:
                kit = kit_fn()
                with self.lock:
                    if self.kit is None:
                        self.kit = kit
            return False
        self.last_offer = time.time() if now is None else now
        t9 = time.time()
        kit = kit_fn()
        log.info("장기 곡선 재료: 그룹 %d · %.2f초", len(kit.get("groups") or ()), time.time() - t9)
        with self.lock:
            self.kit = kit
        self.ev.set()
        return True

    def worker(self):
        while True:
            self.ev.wait(3600)
            self.ev.clear()
            with self.lock:
                kit = self.kit
            if kit is None:
                continue
            try:
                self.run_once(kit)
            except Exception as e:
                log.warning("장기 곡선 계산 실패(다음에 다시): %s", e)

    def run_once(self, kit, cap=None, overlap=False, now=None) -> dict:
        with self.run_lock:
            dirty9 = self._dirty_take(kit.get("made") or 0)
            try:
                rep = self._run(kit, self.run_calls if cap is None else cap, overlap, time.time() if now is None else now, dirty9)
            except Exception:
                if dirty9:
                    self.dirty_fails += 1
                    self.dirty_fail_key = self._dirty_key(dirty9)
                raise
            if dirty9:
                self.dirty_fails, self.dirty_fail_key = 0, None
            return rep

    def _run(self, kit, cap, overlap, now, dirty9=None):
        rep = {"adopted": 0, "computed": 0, "calls": 0, "by_host": {}, "fetched": 0, "specs": 0, "done": 0}
        n0 = candles.CALLS["n"]
        h0 = dict(candles.CALLS["by_host"])
        today = kit["today"]
        d = dict(self.st.get("d") or {})
        s = dict(self.st.get("s") or {})
        f = dict(self.st.get("f") or {})
        xs = dict(self.st.get("x") or {})
        win = set()
        for row9 in kit.get("daily") or ():
            iso, usd, krw, ap, _u, apu = row9[:6]
            win.add(iso)
            fl9 = row9[6] if len(row9) > 6 else None
            if fl9 is not None:
                fv9 = [round(float(fl9[0]), 2), _u, [list(t) for t in fl9[1]] or None, "dc"]
                if f.get(iso) != fv9:
                    f[iso] = fv9
            v = [usd, krw, ap, "dc", apu if ap else 0]
            if d.get(iso) != v:
                d[iso] = v
                rep["adopted"] += 1
        first = kit.get("first") or FIRST_DAY
        oldest = min(win) if win else today
        last_hc = (datetime.strptime(oldest, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        rep["dirty_from"] = dirty9[0] if dirty9 else None
        if dirty9:
            for iso in [k for k in d if k >= dirty9[0] and k not in win and k < today]:
                d.pop(iso, None)
                s.pop(iso, None)
                xs.pop(iso, None)
            for iso in [k for k in f if k >= dirty9[0] and k not in win and k < today]:
                f.pop(iso, None)
        rep["vblk"] = 0
        for k9, e9 in list((self.px.get("specs") or {}).items()):
            if not isinstance(e9, dict) or not isinstance(e9.get("p"), dict) or not e9["p"]:
                continue
            ub9, vb9 = blocked_union(e9, self._dc_entry(k9)) | map_blocked(k9), set(e9.get("vblk") or ())
            if ub9 == vb9:
                continue
            flip9 = ub9 ^ vb9
            ds9 = sorted(served_days(e9, flip9))
            if ds9:
                t9 = int(datetime.strptime(min(ds9), "%Y-%m-%d").replace(tzinfo=KST, hour=12).timestamp())
                (getattr(self, "mark", None) or common.mark_hist_dirty)(t9)
                log.warning("장기 곡선: %s 막힌 거래소 바뀜 %s — %s 부터 다시 계산 표식", k9, sorted(flip9), min(ds9))
            self._note_dc(k9, set(ds9), flip9)
            if (ub9 - vb9) & (map_blocked(k9) - set(e9.get("blk") or ())) and ds9:
                e9["at"] = 0
            e9["vblk"] = sorted(ub9)
            rep["vblk"] += 1
        todo = [x for x in days_between(first, last_hc) if x not in d or d[x][3] == "hp"] if first <= last_hc else []
        ov_days = sorted(win) if overlap else []
        need_days = sorted(set(todo) | set(ov_days))
        if need_days:
            qty = rewind(kit, need_days)
            G = kit["groups"]
            want = {}
            for gid, qd in qty.items():
                g = G[gid]
                if g.get("skip"):
                    continue
                sp = spec_of(g)
                if sp in (None, "ov", "stable"):
                    continue
                w = want.setdefault(sp, {"days": set(), "imp": 0.0, "lp": False})
                w["days"].update(qd)
                w["imp"] = max(w["imp"], max(abs(v9) for v9 in qd.values()) * g["lp"])
                w["lp"] = w["lp"] or g["lp"] > 0
            specs = self.px.setdefault("specs", {})
            lo, hi = need_days[0], need_days[-1]

            def covered(k):
                e = specs.get(k)
                return isinstance(e, dict) and (e.get("lo") or "9999") <= min(want[k]["days"]) and (e.get("hi") or "") >= max(want[k]["days"])

            def fetch_now(k):
                return not covered(k) or due(self._clean(k, specs), now)

            def final_k(k):
                return covered(k) and is_final(self._clean(k, specs))
            small = {k for k, w in want.items() if w["lp"] and w["imp"] < SMALL_USD}
            order = sorted((k for k in want if k not in small), key=lambda k: (not want[k]["lp"], -want[k]["imp"], k))
            fx_ok = self._fx_ready(lo, hi)
            with candles.call_budget(cap):
                def over():
                    return candles.CALLS["n"] - n0 >= cap or (candles.budget_left() or 0) <= 0
                if not fx_ok and not over() and self._fx_due(lo, hi, now):
                    self._fetch_fx(lo, hi, now)
                    fx_ok = self._fx_ready(lo, hi)
                off9 = off_chains_now()
                for k in order:
                    if over():
                        break
                    if spec_off(k, off9):
                        continue
                    if not fetch_now(k):
                        continue
                    self._fetch_spec(k, lo, hi, now, need=want[k]["days"])
                    rep["fetched"] += 1
            rep["specs"] = len(order)
            fin9 = {k: final_k(k) for k in order}
            vw9 = {k: self._clean(k, specs) for k in order}
            pm9 = {k: pmap_of(vw9[k], need_days[-1]) for k in order}

            def spec_day_final(k, iso):
                return covered(k) and day_state(vw9[k], iso, pm9[k]) != "retry"
            rep["done"] = sum(1 for k in order if fin9[k])
            rep["small"] = len(small)
            need_by9 = {}
            for gid9, qd9 in qty.items():
                g9 = G[gid9]
                sp9 = None if g9.get("skip") else spec_of(g9)
                if sp9 in (None, "ov", "stable") or sp9 in small:
                    continue
                for iso9 in qd9:
                    need_by9.setdefault(iso9, set()).add(sp9)

            def day_final(iso):
                return fx_ok and all(spec_day_final(k9, iso) for k9 in need_by9.get(iso, ()) if k9 in fin9)
            all_done = all(day_final(iso) for iso in todo)
            vals = self._compute(kit, need_days, qty)
            for iso in todo:
                v9 = vals.get(iso)
                if v9 is None:
                    continue
                row = list(v9["row"])
                if not day_final(iso):
                    row = self._row(v9["cov"][0], v9["cov"][1], v9["xr"], self.fx(iso), "hp")
                d[iso] = row
                s[iso] = v9["cov"]
                xs[iso] = v9["xr"]
                rep["computed"] += 1
            if overlap:
                rep["overlap"] = {iso: vals[iso] for iso in ov_days if iso in vals}
            rep["hc_detail"] = {iso: vals[iso] for iso in todo if iso in vals}
            rep["final"] = all_done
            self.pending = not all_done and bool(todo)
            self.progress = {"specs": len(order) + 1, "done": rep["done"] + (1 if fx_ok else 0),
                             "pending": sum(1 for iso in todo if not day_final(iso))}
        else:
            self.pending = False
            self.progress = {"specs": 0, "done": 0, "pending": 0}
        rep["xfix"] = self._x_refresh(kit, d, s, xs, win, today)
        rep["calls"] = candles.CALLS["n"] - n0
        rep["by_host"] = {h: n - h0.get(h, 0) for h, n in candles.CALLS["by_host"].items() if n - h0.get(h, 0)}
        rep["flows"], rep["flow_left"] = self._flows(kit, d, f, win, today)
        meta = dict(self.st.get("meta") or {})
        meta.update(adopted_day=today, adopted_at=int(now), first=first, updated=int(now),
                    calls=int(meta.get("calls") or 0) + rep["calls"], runs=int(meta.get("runs") or 0) + 1)
        self.progress["calls"] = meta["calls"]
        meta.update(pending=bool(self.pending), progress={k9: v9 for k9, v9 in self.progress.items() if k9 != "calls"},
                    flow_pending=bool(self.flow_pending))
        xs = {k9: v9 for k9, v9 in xs.items() if k9 in d and isinstance(d[k9], list) and len(d[k9]) >= 4 and d[k9][3] in ("hc", "hp")}
        with self.lock:
            self.st = {"_v": HIST_V, "d": d, "s": s, "f": f, "fv": FLOW_V, "meta": meta, "x": xs}
        common.atomic_write_json(self.path, self.st)
        if rep["fetched"] or rep["calls"] or rep.get("vblk"):
            common.atomic_write_json(self.px_path, self.px)
        if dirty9:
            self._dirty_done(dirty9[1])
            log.warning("장기 곡선: 원장 지난 시각 변경 표식 — %s 부터 창 밖 동결 날 다시 계산(%d일)", dirty9[0], rep["computed"])
        self.last_run = rep
        log.info("장기 곡선: 받은 날 %d · 계산·동결 %d · 가격 출처 %d/%d · 외부 호출 %d %s · 남은 날 %s · 입출금 %d일(남은 %d) · 원장 밖 금액 다시 %d일",
                 rep["adopted"], rep["computed"], rep["done"], rep["specs"], rep["calls"], rep["by_host"], self.progress.get("pending"),
                 rep["flows"], rep["flow_left"], rep["xfix"])
        return rep

    def flow_prices(self, kit, days):
        specs = self.px.get("specs") or {}
        out = {iso: {"p": {}} for iso in days}
        if not days:
            return out
        upto = max(days)
        ff = {}
        for gid, g in (kit.get("groups") or {}).items():
            if g.get("skip"):
                continue
            sp = spec_of(g)
            if sp in (None, "stable"):
                continue
            if sp == "ov":
                for iso in days:
                    out[iso]["p"][str(gid)] = float(g["ov"])
                continue
            if sp not in ff:
                ff[sp] = pmap_of(self._clean(sp, specs), upto)
            pm = ff[sp]
            for iso in days:
                p9 = pm.get(iso)
                if p9 and p9 > 0:
                    out[iso]["p"][str(gid)] = float(p9)
        return out

    def _flows(self, kit, d, f, win, today):
        todo = sorted(iso for iso, r in d.items() if iso not in win and iso < today and iso not in f
                      and isinstance(r, list) and len(r) >= 4 and r[3] in ("hc", "dc"))
        waiting = any(isinstance(r, list) and len(r) >= 4 and r[3] == "hp" for r in d.values())
        fn, fk = self.flow_fn, kit.get("fk")
        if not todo or fn is None or fk is None:
            self.flow_pending = bool(todo) or waiting
            return 0, len(todo)
        t9 = time.time()
        hc_days = [iso for iso in todo if d[iso][3] == "hc"]
        dpx = self.flow_prices(kit, hc_days)
        dc_px = fk.get("dpx_dc") or {}

        def table(iso):
            r9 = d.get(iso)
            if isinstance(r9, list) and len(r9) >= 4 and r9[3] == "dc" and dc_px.get(iso):
                return dc_px[iso]
            return self.flow_prices(kit, [iso])[iso]
        for iso in todo:
            if d[iso][3] == "dc":
                dpx[iso] = table(iso)
        for iso in todo:
            pk9 = (datetime.strptime(iso, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
            if pk9 not in dpx:
                dpx[pk9] = table(pk9)

        def flow_fx(iso):
            r9 = d.get(iso)
            if isinstance(r9, list) and len(r9) >= 4 and r9[3] == "dc":
                return round(float(r9[1]) / float(r9[0]), 4) if r9[0] and r9[1] else None
            return self.fx(iso)
        try:
            res = fn(fk, todo, dpx, flow_fx) or {}
        except Exception as e:
            self.flow_fails += 1
            self.flow_pending = True
            log.warning("장기 곡선 입출금 계산 실패(%d회): %s", self.flow_fails, e)
            return 0, len(todo)
        self.flow_fails = 0
        nofx = res.pop("_nofx", None) or {}
        held = 0
        for iso in todo:
            r9 = d[iso]
            v9 = res.get(iso)
            usdt = flow_fx(iso)
            top9 = [list(t) for t in (v9[1] or ())][:3] if v9 else []
            row9 = [round(float(v9[0]), 2) if v9 else 0.0, usdt, top9 or None, "hc"]
            if iso in nofx:
                if r9[3] == "hc" and not self._fx_ready(iso, iso):
                    held += 1
                    continue
                row9.append({"nofx": round(float(nofx[iso]), 2)})
            f[iso] = row9
        self.flow_pending = waiting or bool(held)
        log.info("장기 곡선 입출금: %d일 · %.1f초 · 환율 대기 %d일", len(todo) - held, time.time() - t9, held)
        return len(todo) - held, held

    def _span(self, lo, hi):
        return span(lo, hi)

    def _fx_ready(self, lo, hi):
        fx = self.px.get("fx")
        return isinstance(fx, dict) and (fx.get("lo") or "9999") <= lo and (fx.get("hi") or "") >= hi and fx.get("st") == "ok"

    def _fx_due(self, lo, hi, now):
        fx = self.px.get("fx")
        if not isinstance(fx, dict) or not ((fx.get("lo") or "9999") <= lo and (fx.get("hi") or "") >= hi):
            return True
        return fx.get("st") != "ok" and due(fx, now)

    def _fetch_fx(self, lo, hi, now):
        t0, t1 = self._span(lo, hi)
        self.px["fx"] = fetch_fx_entry(lo, hi, now, self.px.get("fx"))

    def fx(self, iso):
        return ((self.px.get("fx") or {}).get("p") or {}).get(iso)

    def _fetch_spec(self, k, lo, hi, now, need=None):
        prev = self.px["specs"].get(k) if isinstance(self.px["specs"].get(k), dict) else {}
        e9 = fetch_entry(k, lo, hi, now, need=need, fx_get=self.fx, prev=prev, xref=xref_fn(k, (self.px.get("specs") or {},)),
                         blocked=blocked_union(self._dc_entry(k)))
        chg9 = e9.pop("_chg", None) or []
        e9.pop("_drop", None)
        self.px["specs"][k] = e9
        if chg9:
            t9 = int(datetime.strptime(min(chg9), "%Y-%m-%d").replace(tzinfo=KST, hour=12).timestamp())
            (getattr(self, "mark", None) or common.mark_hist_dirty)(t9)
            log.warning("장기 곡선: %s 그날 값·출처 바뀜 %d일 — %s 부터 다시 계산 표식", k, len(chg9), min(chg9))
        self._note_dc(k, set(chg9), set(e9.get("blk") or ()) ^ set(prev.get("blk") or ()))

    def _note_dc(self, k, days, flip):
        dc9 = globals().get("DAYCLOSE")
        if dc9 is None or getattr(dc9, "hist", None) is not self:
            return
        ds9 = set(days or ())
        de9 = self._dc_entry(k)
        if flip and isinstance(de9, dict) and isinstance(de9.get("p"), dict):
            ds9 |= served_days(de9, flip)
        if ds9:
            dc9.note_change(k, ds9, invalidate=True)

    def _dc_entry(self, sp):
        dc9 = globals().get("DAYCLOSE")
        if dc9 is not None and getattr(dc9, "hist", None) is self:
            return ((dc9.st.get("s") or {}).get(sp)) or None
        return None

    def _clean(self, sp, specs):
        e9 = specs.get(sp)
        return view(e9, blocked_union(e9, self._dc_entry(sp)) | map_blocked(sp))

    @staticmethod
    def _x_src(kit):
        xk = kit.get("xk") or {}
        src = dict(xk.get("src") or {})
        src["obs"] = xk.get("obs") or {}
        return src

    @staticmethod
    def _x_fin(xr):
        parts, fx = xr["p"], xr.get("fx")
        uu = xparts.ub_usd((parts.get("ub") or [{}])[0])
        cut = min(float(xr.get("cut") or 0.0), uu)
        cr = xparts.carry_usd(parts, fx) - (cut if (parts.get("ub") or [None, None])[1] == "carry" else 0.0)
        xr["cut"] = round(cut, 2)
        xr["x"] = round(xparts.total_usd(parts, fx) - cut, 2)
        xr["xc"] = round(max(cr, 0.0), 2)
        return xr

    def _x_rec(self, kit, iso, qty_of, old=None, qcache=None):
        xk = kit.get("xk") or {}
        e9 = day_end(iso) - 1
        dd = (xk.get("days") or {}).get(iso)
        src = self._x_src(kit)
        now9 = xparts.num((src.get("now") or {}).get("ts"))
        if isinstance(dd, dict) and isinstance(dd.get("p"), dict):
            parts = {k9: [xparts.ub_norm(v9[0]) if k9 == "ub" else v9[0], v9[1]] for k9, v9 in dd["p"].items()}
            fx = dd.get("fx") or self.fx(iso) or xk.get("rate")
            uat = e9
        else:
            pin9 = (old or {}).get("p")
            parts = xparts.resolve(e9, src, pinned=pin9)
            fx = self.fx(iso) or xparts.num((old or {}).get("fx")) or xk.get("rate")
            pu9 = (pin9 or {}).get("ub")
            if old and xparts.num(old.get("uat")) and isinstance(pu9, (list, tuple)) and len(pu9) >= 2 and pu9[1] in ("snap", "carry"):
                uat = float(old["uat"])
            else:
                near9 = xparts.nearest(src.get("obs") or {}, e9, now9, "ub")
                uat = float(near9["end"]) if near9 is not None else (now9 or e9)
        cut = self._ub_cut_at(kit, (parts.get("ub") or [{}])[0], uat, iso, qty_of, qcache)
        return self._x_fin({"p": parts, "fx": fx, "cut": cut, "uat": uat})

    @staticmethod
    def _ub_cut_at(kit, ub, uat, iso, qty_of, qcache=None):
        if not ub:
            return 0.0
        xk = kit.get("xk") or {}
        if abs(float(uat) - (day_end(iso) - 1)) < 1:
            q_of = qty_of
        else:
            iso_o = datetime.fromtimestamp(float(uat), KST).strftime("%Y-%m-%d")
            if iso_o >= str(kit.get("today") or ""):
                grp9 = kit.get("groups") or {}

                def q_of(gid):
                    return float((grp9.get(gid) or {}).get("hold") or 0.0)
            else:
                qc9 = qcache if qcache is not None else {}
                if iso_o not in qc9:
                    qc9[iso_o] = rewind(kit, [iso_o])
                q9 = qc9[iso_o]

                def q_of(gid):
                    return (q9.get(gid) or {}).get(iso_o, 0.0)
        return xparts.ub_cut(ub, float(uat), xk.get("sym_tl") or {}, q_of)[0]

    @staticmethod
    def _row(priced, miss, xr, fx, kind):
        usd = round(float(priced) + float(xr["x"]), 2)
        krw = round(usd * fx) if fx else None
        if kind == "hp":
            return [usd, krw, 1, "hp", round(float(miss) + float(xr["xc"]), 2) or 1.0]
        ap = ap_flag(usd, miss, xr["xc"])
        return [usd, krw, ap, "hc", round(float(miss) + float(xr["xc"]), 2) if ap else 0]

    def _x_refresh(self, kit, d, s, xs, win, today):
        xk = kit.get("xk") or {}
        days9 = xk.get("days") or {}
        src = self._x_src(kit)
        n, redo = 0, []
        for iso in sorted(d):
            r = d[iso]
            if iso in win or iso >= today or not isinstance(r, list) or len(r) < 4 or r[3] not in ("hc", "hp"):
                continue
            cov = s.get(iso)
            if not (isinstance(cov, list) and len(cov) >= 4):
                continue
            if len(cov) < 5:
                redo.append(iso)
                continue
            old = xs.get(iso) if isinstance(xs.get(iso), dict) else None
            dd = days9.get(iso)
            e9 = day_end(iso) - 1
            if isinstance(dd, dict) and isinstance(dd.get("p"), dict):
                parts = {k9: [xparts.ub_norm(v9[0]) if k9 == "ub" else v9[0], v9[1]] for k9, v9 in dd["p"].items()}
                fx = dd.get("fx") or self.fx(iso) or xk.get("rate")
            else:
                parts = xparts.resolve(e9, src, pinned=(old or {}).get("p"))
                fx = self.fx(iso) or xparts.num((old or {}).get("fx")) or xk.get("rate")
            uat9 = (e9 if isinstance(dd, dict) and isinstance(dd.get("p"), dict) else xparts.num((old or {}).get("uat")))
            if old and xparts.same(parts, old.get("p")) and old.get("fx") == fx and uat9 == xparts.num(old.get("uat")):
                continue
            if old and uat9 and uat9 == xparts.num(old.get("uat")) and xparts.same({"ub": parts.get("ub")}, {"ub": (old.get("p") or {}).get("ub")}):
                xr = self._x_fin({"p": parts, "fx": fx, "cut": old.get("cut", cov[4]), "uat": uat9})
            else:
                redo.append(iso)
                continue
            xs[iso] = xr
            s[iso] = [cov[0], cov[1], xr["xc"], cov[3], xr["cut"]]
            d[iso] = self._row(cov[0], cov[1], xr, self.fx(iso), r[3])
            n += 1
        if redo:
            qty = rewind(kit, redo)
            qc9 = {}
            for iso in redo:
                cov = s[iso]
                xr = self._x_rec(kit, iso, lambda gid, _i=iso: (qty.get(gid) or {}).get(_i, 0.0), old=xs.get(iso), qcache=qc9)
                xs[iso] = xr
                s[iso] = [cov[0], cov[1], xr["xc"], cov[3], xr["cut"]]
                d[iso] = self._row(cov[0], cov[1], xr, self.fx(iso), d[iso][3])
                n += 1
        for iso, row in sorted((kit.get("dcv") or {}).items()):
            r9 = d.get(iso)
            if iso not in win and iso < today and isinstance(r9, list) and len(r9) >= 4 and r9[3] == "dc" and list(r9[:5]) != list(row):
                d[iso] = list(row)
                n += 1
        return n

    def _compute(self, kit, days, qty):
        G = kit["groups"]
        specs = self.px.get("specs") or {}
        st_x = (self.st or {}).get("x") or {}
        qc9 = {}
        ff_cache = {}

        def ffill(pm):
            key = id(pm)
            if key in ff_cache:
                return ff_cache[key][1]
            out9 = ffill_map(pm, max(days))
            ff_cache[key] = (pm, out9)
            return out9
        acc = {iso: [0.0, 0.0, 0] for iso in days}
        for gid, qd in qty.items():
            g = G[gid]
            if g.get("skip"):
                continue
            sp = spec_of(g)
            if sp is None:
                continue
            pmap = None if sp in ("stable", "ov") else pmap_of(self._clean(sp, specs), max(days))
            for iso, q in qd.items():
                a9 = acc.get(iso)
                if a9 is None:
                    continue
                if sp == "stable":
                    a9[0] += q
                elif sp == "ov":
                    a9[0] += q * g["ov"]
                else:
                    p9 = pmap.get(iso)
                    if p9:
                        a9[0] += q * p9
                    else:
                        a9[1] += q * g["lp"]
                        a9[2] += 1
        out = {}
        for iso in days:
            priced, miss, n_miss = acc[iso]
            fx = self.fx(iso)
            xr = self._x_rec(kit, iso, lambda gid, _i=iso: (qty.get(gid) or {}).get(_i, 0.0), old=st_x.get(iso), qcache=qc9)
            out[iso] = {"row": self._row(priced, miss, xr, fx, "hc"),
                        "cov": [round(priced, 2), round(miss, 2), xr["xc"], n_miss, xr["cut"]], "x": xr["x"], "xr": xr}
        return out

    def view(self, rng):
        def nofx_of(v9):
            x9 = v9[4] if isinstance(v9, list) and len(v9) > 4 and isinstance(v9[4], dict) else {}
            return x9.get("nofx")
        with self.lock:
            d = self.st.get("d") or {}
            f = self.st.get("f") or {}
            s9 = self.st.get("s") or {}
            x9 = self.st.get("x") or {}
            meta = dict(self.st.get("meta") or {})
            keys = sorted(d)
        today = datetime.now(KST).strftime("%Y-%m-%d")

        def row_of(k):
            r9 = d[k]
            c9, xr9 = s9.get(k), x9.get(k)
            if (isinstance(r9, list) and len(r9) >= 4 and r9[3] in ("hc", "hp") and isinstance(c9, list) and len(c9) >= 5
                    and isinstance(xr9, dict) and xr9.get("x") is not None):
                return self._row(c9[0], c9[1], xr9, self.fx(k), r9[3])
            return r9
        if rng:
            lo = (datetime.now(KST) - timedelta(days=int(rng) - 1)).strftime("%Y-%m-%d")
            keys = [k for k in keys if k >= lo]
        rows9 = {k: row_of(k) for k in keys if k < today}
        days = [[k, rows9[k][0], rows9[k][1], int(rows9[k][2] or 0), (rows9[k][4] if len(rows9[k]) > 4 else 0) or 0]
                + (list(f[k][:3]) if isinstance(f.get(k), list) and len(f[k]) >= 3 else [None, None, None])
                + [nofx_of(f.get(k))] for k in keys if k < today]
        building = bool(self.pending)
        body = {"ok": True, "days": days, "building": building, "flowBuilding": bool(self.flow_pending), "first": meta.get("first") or FIRST_DAY,
                "progress": dict(self.progress), "updated": meta.get("updated")}
        return (202 if building else 200), body


DC_RUN_CALLS = 60
DC_DAY_CALLS = 600
DC_GAP_S = 300
DC_SETTLE_S = 1800
DC_KEEP_DAYS = 50
DC_OLD_RUN_CALLS = 40
DC_OLD_BUSY_CALLS = 10
DC_REQ_TTL_S = 3 * 86400


def settle_ts(iso) -> int:
    return (day_end(iso) // 86400 + 1) * 86400 + DC_SETTLE_S


def needs_krw(k) -> bool:
    return str(k).startswith(("sym:", "ex:upbit:", "ex:bithumb:"))


def _final(e) -> bool:
    return is_final(e)


class DayClose:
    def __init__(self, path=None, hist=None, run_calls=DC_RUN_CALLS, gap=DC_GAP_S, day_calls=DC_DAY_CALLS):
        self.path = path or os.path.join(common.STATE_DIR, "daily_close_px.json")
        self.hist = hist
        self.run_calls, self.gap, self.day_calls = run_calls, gap, day_calls
        self.lock = threading.Lock()
        self.run_lock = threading.Lock()
        self.ev = threading.Event()
        st = common.read_json(self.path, None) if os.path.exists(self.path) else None
        self.st = st if isinstance(st, dict) and st.get("_v") == 1 else {"_v": 1, "s": {}, "fx": None, "calls": []}
        self.want = {}
        self.want_old = {}
        self.gen = 0
        self.last_kick = 0.0
        self.last_run = None
        self._ff = {}

    @staticmethod
    def covers(e, iso) -> bool:
        return (isinstance(e, dict) and (e.get("lo") or "9999") <= iso <= (e.get("hi") or "")
                and int(e.get("at") or 0) >= settle_ts(iso) - DC_SETTLE_S)

    def _ffp(self, e):
        c = self._ff.get(id(e))
        if c is None or c[0] is not e:
            if len(self._ff) > 4000:
                self._ff.clear()
            c = (e, pmap_of(e, e.get("hi") or ""))
            self._ff[id(e)] = c
        return c[1]

    def _sources(self, spec):
        own = (self.st.get("s") or {}).get(spec)
        hs = ((getattr(self.hist, "px", None) or {}).get("specs") or {}).get(spec) if self.hist is not None else None
        old9 = (self.st.get("o") or {}).get(spec)
        blk9 = blocked_union(own, hs, old9) | map_blocked(spec)
        c9 = self.__dict__.setdefault("_views", {})
        if len(c9) > 4000:
            c9.clear()
        out = []
        for e9, bor9 in ((own, False), (hs, True), (old9, False)):
            if not isinstance(e9, dict):
                out.append(e9)
                continue
            key9 = (id(e9), bor9, tuple(sorted(blk9)), len(e9.get("p") or ()), e9.get("st"), tuple(e9.get("idok") or ()))
            if key9 not in c9:
                c9[key9] = (e9, view(e9, blk9, borrowed=bor9, spec=spec))
            elif c9[key9][0] is not e9:
                c9[key9] = (e9, view(e9, blk9, borrowed=bor9, spec=spec))
            out.append(c9[key9][1])
        return tuple(out)

    def lookup(self, spec, iso, now=None, w=0.0, ask=True, old=False):
        now = time.time() if now is None else now
        if spec == "stable":
            return 1.0, "ok"
        if not spec or spec == "ov":
            return None, "none"
        if now < settle_ts(iso):
            return None, "wait"
        srcs = self._sources(spec)
        dst9 = [(e, day_state(e, iso, self._ffp(e))) for e in srcs if self.covers(e, iso)]
        for e, st9 in dst9:
            if st9 == "ok":
                return float(self._ffp(e)[iso]), "ok"
        if any(st9 == "none" for _e, st9 in dst9):
            return None, "none"
        retry9 = bool(dst9)
        if not ask:
            return None, ("retry" if retry9 else "pending")
        if old and iso < (datetime.fromtimestamp(now, KST) - timedelta(days=DC_KEEP_DAYS)).strftime("%Y-%m-%d"):
            with self.lock:
                r = self.want_old.setdefault(spec, {"days": set(), "w": 0.0, "t0": now})
                r["days"].add(iso)
            return None, ("retry" if retry9 else "pending")
        with self.lock:
            r = self.want.setdefault(spec, {"days": set(), "w": 0.0, "t0": now})
            r["days"].add(iso)
            r["w"] = max(r["w"], float(w or 0))
        return None, ("retry" if retry9 else "pending")

    def map_recheck(self) -> int:
        n9 = 0
        for sp9, e9 in list((self.st.get("s") or {}).items()):
            mb9 = map_blocked(sp9) - set((e9 or {}).get("blk") or ()) if isinstance(e9, dict) else set()
            ds9 = map_blocked_days(sp9, e9, mb9) if mb9 else set()
            if ds9:
                log.warning("그날 마감가: %s 저장 값 출처(%s) = 지금 매핑으로 다른 코인 — %d일 지우고 다시 받기", sp9, sorted(mb9), len(ds9))
                n9 += self.note_change(sp9, ds9, invalidate=True) or 1
        return n9

    def resolver(self, G, ca_gids, ex_gid, major_gids, override_px, pairs, stable_syms=None, now=None):
        memo = {}
        now = time.time() if now is None else now
        try:
            self.map_recheck()
        except Exception as e9:
            log.warning("그날 마감가: 매핑 재확인 실패(다음에): %s", e9)

        def spec9(gid):
            if gid not in memo:
                g = G.get(gid)
                memo[gid] = spec_of(group_desc(gid, g, ca_gids, ex_gid, major_gids, override_px, pairs, stable_syms)) if g else None
            return memo[gid]

        def f(gid, iso, w=0.0):
            return self.lookup(spec9(gid), iso, now, w)
        f.gen = self.gen
        f.spec = spec9
        m9 = self.st.get("px1004") if isinstance(self.st.get("px1004"), dict) else {}
        f.redo = frozenset(m9.get("specs") or ())
        f.redo_at = int(m9.get("last") or m9.get("at") or 0)
        chg9 = self.st.get("chg") if isinstance(self.st.get("chg"), dict) else {}
        f.chg = lambda sp: chg9.get(sp) or {}
        return f

    def kick(self, now=None):
        now = time.time() if now is None else now
        if (self.want or self.want_old) and now - self.last_kick >= self.gap:
            self.last_kick = now
            self.ev.set()
            return True
        return False

    def worker(self):
        while True:
            self.ev.wait(self.gap * 2)
            self.ev.clear()
            if not self.want and not self.want_old:
                continue
            try:
                self.run_once()
            except Exception as e:
                log.warning("그날 마감가 받기 실패(다음에 다시): %s", e)

    def _run_old(self, items, o, fxo, now, rep):
        hpx9 = (getattr(self.hist, "px", None) or {}) if self.hist is not None else {}
        hs9 = hpx9.get("specs") or {}
        off9 = off_chains_now()
        fxp = {}
        for e9 in (hpx9.get("fx"), fxo):
            if isinstance(e9, dict) and isinstance(e9.get("p"), dict):
                fxp.update(e9["p"])
        kd = sorted({d for k, ds, _w in items if needs_krw(k) for d in ds})
        miss9 = [d for d in kd if d not in fxp]
        out9 = [d for d in miss9 if not (isinstance(fxo, dict) and (fxo.get("lo") or "9999") <= d <= (fxo.get("hi") or ""))]
        if miss9 and (candles.budget_left() or 0) > 0 and (out9 or due(fxo if isinstance(fxo, dict) else None, now)):
            flo = (datetime.strptime(miss9[0], "%Y-%m-%d") - timedelta(days=FFILL_DAYS)).strftime("%Y-%m-%d")
            fhi = miss9[-1]
            if isinstance(fxo, dict) and fxo.get("lo") and fxo.get("hi"):
                flo, fhi = min(flo, fxo["lo"]), max(fhi, fxo["hi"])
            fxn = fetch_fx_entry(flo, fhi, now, fxo)
            if isinstance(fxn, dict) and isinstance(fxo, dict) and fxn.get("st") != "ok":
                fxn = dict(fxn, p=dict(fxo.get("p") or {}, **(fxn.get("p") or {})))
            fxo = fxn
            if isinstance(fxo, dict):
                fxp.update(fxo.get("p") or {})
        for k, ds, _w in items:
            if (candles.budget_left() or 0) <= 0:
                break
            ds = {d for d in ds if self.lookup_state(k, d, now) == "pending"}
            if not ds or spec_off(k, off9):
                continue
            if needs_krw(k) and k.startswith("ex:") and any(d not in fxp for d in ds):
                continue
            prev = o.get(k) if isinstance(o.get(k), dict) else None
            hsk9 = hs9.get(k) if isinstance(hs9.get(k), dict) else None
            if prev and all(self.covers(prev, d9) for d9 in ds) and not due(view(prev, blocked_union(prev, hsk9) | map_blocked(k)), now):
                continue
            lo = (datetime.strptime(min(ds), "%Y-%m-%d") - timedelta(days=FFILL_DAYS)).strftime("%Y-%m-%d")
            hi = max(ds)
            if prev and prev.get("lo") and prev.get("hi"):
                lo, hi = min(lo, prev["lo"]), max(hi, prev["hi"])
            e = fetch_entry(k, lo, hi, now, need=ds, fx_get=fxp.get, prev=prev, xref=xref_fn(k, (o, hs9)), blocked=blocked_union(hsk9))
            gone9 = set(e.pop("_drop", None) or ())
            e.pop("_chg", None)
            if prev and isinstance(prev.get("p"), dict) and not is_final(e):
                e["p"] = dict({d9: v9 for d9, v9 in prev["p"].items() if d9 not in gone9}, **(e.get("p") or {}))
            o[k] = e
            rep["old_fetched"] = rep.get("old_fetched", 0) + 1
        return fxo

    def ask_old(self, spec, days, w=0.0, now=None):
        if not spec or spec in ("stable", "ov") or not days:
            return
        now = time.time() if now is None else now
        with self.lock:
            r = self.want_old.setdefault(spec, {"days": set(), "w": 0.0, "t0": now})
            r["days"] |= set(days)
            r["w"] = max(float(r.get("w") or 0), float(w or 0))

    def old_status(self) -> dict:
        with self.lock:
            left = {k: len(v.get("days") or ()) for k, v in self.want_old.items()}
        lr = self.last_run if isinstance(self.last_run, dict) else {}
        return {"specs": len(left), "days": sum(left.values()), "done": len(self.st.get("o") or {}), "last": int(lr.get("old_fetched") or 0)}

    def _fx_ok(self, fx, lo, hi):
        return isinstance(fx, dict) and (fx.get("lo") or "9999") <= lo and (fx.get("hi") or "") >= hi and int(fx.get("at") or 0) >= settle_ts(hi) - DC_SETTLE_S \
            and fx.get("st") == "ok"

    def run_once(self, cap=None, now=None) -> dict:
        with self.run_lock:
            return self._run(self.run_calls if cap is None else cap, time.time() if now is None else now)

    def _run(self, cap, now):
        rep = {"fetched": 0, "calls": 0, "resolved": 0, "left": 0}
        calls9 = [(int(t), int(n)) for t, n in (self.st.get("calls") or []) if now - int(t) < 86400]
        cap = max(0, min(int(cap), self.day_calls - sum(n for _t, n in calls9)))
        with self.lock:
            items = sorted(((k, set(v["days"]), v["w"]) for k, v in self.want.items()), key=lambda x: (-x[2], x[0]))
            items_old = sorted(((k, set(v["days"]), v["w"]) for k, v in self.want_old.items()), key=lambda x: (-x[2], -len(x[1]), x[0]))
        lo_keep = (datetime.fromtimestamp(now, KST) - timedelta(days=DC_KEEP_DAYS)).strftime("%Y-%m-%d")
        o = dict(self.st.get("o") or {})
        fxo = self.st.get("fxo")
        s = dict(self.st.get("s") or {})
        chg_log = {k: dict(v) for k, v in (self.st.get("chg") or {}).items() if isinstance(v, dict)}
        chg_new = {}
        t_run0 = time.time()
        fx = self.st.get("fx")
        n0 = candles.CALLS["n"]
        done = set()
        if (items or items_old) and cap > 0:
            with candles.call_budget(cap) as bud:
                ready = [(k, {d for d in ds if now >= settle_ts(d) and d >= lo_keep}, w) for k, ds, w in items]
                fx_days = sorted({d for k, ds, _w in ready if needs_krw(k) for d in ds})
                if fx_days:
                    flo = (datetime.strptime(fx_days[0], "%Y-%m-%d") - timedelta(days=FFILL_DAYS)).strftime("%Y-%m-%d")
                    if not self._fx_ok(fx, flo, fx_days[-1]) and bud[0] > 0 and (
                            not (isinstance(fx, dict) and (fx.get("lo") or "9999") <= flo and (fx.get("hi") or "") >= fx_days[-1]
                                 and int(fx.get("at") or 0) >= settle_ts(fx_days[-1]) - DC_SETTLE_S) or due(fx, now)):
                        fx = fetch_fx_entry(flo, fx_days[-1], now, fx)
                fxp = dict((fx or {}).get("p") or {}) if isinstance(fx, dict) else {}
                fx_ready = not fx_days or self._fx_ok(fx, fx_days[0], fx_days[-1])
                off9 = off_chains_now()
                for k, ds, _w in ready:
                    if (candles.budget_left() or 0) <= 0:
                        break
                    if not ds or spec_off(k, off9):
                        continue
                    if needs_krw(k) and not fx_ready and k.startswith("ex:"):
                        continue
                    lo = (datetime.strptime(min(ds), "%Y-%m-%d") - timedelta(days=FFILL_DAYS)).strftime("%Y-%m-%d")
                    hi = max(ds)
                    prev = s.get(k) if isinstance(s.get(k), dict) else None
                    hs9 = ((getattr(self.hist, "px", None) or {}).get("specs") or {}) if self.hist is not None else {}
                    hsk9 = hs9.get(k) if isinstance(hs9.get(k), dict) else None
                    if prev and all(self.covers(prev, d9) for d9 in ds) and not due(view(prev, blocked_union(prev, hsk9) | map_blocked(k)), now):
                        continue
                    if prev and prev.get("lo") and prev.get("hi"):
                        lo, hi = max(lo_keep, min(lo, prev["lo"])), max(hi, prev["hi"])
                    e = fetch_entry(k, lo, hi, now, need=ds, fx_get=fxp.get, prev=prev, xref=xref_fn(k, (s, hs9)),
                                    blocked=blocked_union(hsk9))
                    gone9 = set(e.pop("_drop", None) or ())
                    chg9 = set(e.pop("_chg", None) or ())
                    if chg9:
                        chg_new.setdefault(k, set()).update(chg9)
                    flip9 = set(e.get("blk") or ()) ^ set((prev or {}).get("blk") or ())
                    if flip9 and isinstance((prev or {}).get("p"), dict):
                        chg_new.setdefault(k, set()).update(served_days(prev, flip9))
                    mk9 = set(chg9)
                    if flip9 and hsk9 and isinstance(hsk9.get("p"), dict):
                        mk9 |= served_days(hsk9, flip9)
                    if mk9:
                        self._mark_dirty(min(mk9))
                    if prev and isinstance(prev.get("p"), dict) and not is_final(e):
                        drop9 = gone9
                        e["p"] = dict({d9: v9 for d9, v9 in prev["p"].items() if d9 not in drop9}, **(e.get("p") or {}))
                    s[k] = e
                    rep["fetched"] += 1
                if items_old and (candles.budget_left() or 0) > 0:
                    ob9 = DC_OLD_BUSY_CALLS if getattr(self.hist, "pending", False) else DC_OLD_RUN_CALLS
                    with candles.call_budget(ob9):
                        fxo = self._run_old(items_old, o, fxo, now, rep)
            rep["calls"] = cap - max(0, bud[0])
        s = {k: v for k, v in s.items() if isinstance(v, dict) and (v.get("hi") or "") >= lo_keep}
        if rep["calls"]:
            calls9.append((int(now), rep["calls"]))
        with self.lock:
            tc9 = int(now + (time.time() - t_run0)) + 1
            for k, ds9 in chg_new.items():
                cl9 = chg_log.setdefault(k, {})
                for d9 in ds9:
                    cl9[d9] = tc9
            inv9 = self.__dict__.pop("_inv", None) or {}
            st_tmp9 = {"s": s}
            for k, lst9 in inv9.items():
                ds9 = set().union(*[d9 for t9, d9 in lst9 if t9 >= t_run0])
                if ds9:
                    st_tmp9 = self._invalidate(st_tmp9, k, ds9)
            s = st_tmp9["s"]
            for k, v in (self.st.get("chg") or {}).items():
                if isinstance(v, dict):
                    cl9 = chg_log.setdefault(k, {})
                    for d9, t9 in v.items():
                        cl9[d9] = max(int(cl9.get(d9) or 0), int(t9 or 0))
            chg_log = {k: {d9: t9 for d9, t9 in v.items() if d9 == "*" or d9 >= lo_keep} for k, v in chg_log.items()}
            chg_log = {k: v for k, v in chg_log.items() if v}
            self.st = dict({"_v": 1, "s": s, "fx": fx, "calls": calls9},
                           **({"px1004": self.st["px1004"]} if isinstance(self.st.get("px1004"), dict) else {}),
                           **({"chg": chg_log} if chg_log else {}),
                           **({"o": o} if o else {}), **({"fxo": fxo} if fxo else {}))
            self.gen += 1
            for k, ds, _w in items:
                left = {d for d in ds if d >= lo_keep and self.lookup_state(k, d, now) in ("pending",)}
                r = self.want.get(k)
                if r is None:
                    continue
                if now - float(r.get("t0") or now) > DC_REQ_TTL_S:
                    log.info("그날 마감가: 오래 못 받은 요청 버림 %s %s", k, sorted(r["days"])[:3])
                    left = set()
                    r["days"] = set(ds)
                r["days"] -= (ds - left)
                if not r["days"]:
                    self.want.pop(k, None)
                    done.add(k)
            for k, ds, _w in items_old:
                r = self.want_old.get(k)
                if r is None:
                    continue
                r["days"] -= {d for d in ds if self.lookup_state(k, d, now) != "pending"}
                if not r["days"]:
                    self.want_old.pop(k, None)
            rep["resolved"] = len(done)
            rep["left"] = len(self.want)
            rep["old_left"] = len(self.want_old)
        if rep["fetched"] or rep["calls"]:
            with self.lock:
                common.atomic_write_json(self.path, self.st)
        rep["by_host_calls"] = candles.CALLS["n"] - n0
        self.last_run = rep
        log.info("그날 마감가: 받은 출처 %d · HTTP 시도 %d · 풀린 요청 %d · 남은 요청 %d", rep["fetched"], rep["calls"], rep["resolved"], rep["left"])
        return rep

    def _invalidate(self, st9, spec, days):
        s9 = st9.get("s") or {}
        e9 = s9.get(spec)
        if not isinstance(e9, dict):
            return st9
        p9 = e9.get("p") if isinstance(e9.get("p"), dict) else {}
        in9 = {d9 for d9 in days if (e9.get("lo") or "9999") <= d9 <= (e9.get("hi") or "")}
        if not in9:
            return st9
        ps9 = e9.get("ps") if isinstance(e9.get("ps"), dict) else None
        ne9 = dict(e9, p={d9: v9 for d9, v9 in p9.items() if d9 not in in9}, st="idp", at=0,
                   pend=sorted(set(e9.get("pend") or ()) | in9))
        if ps9 is not None:
            ne9["ps"] = {d9: v9 for d9, v9 in ps9.items() if d9 not in in9}
        return dict(st9, s=dict(s9, **{spec: ne9}))

    def note_change(self, spec, days, ts=None, invalidate=False):
        days = sorted({d for d in days or () if d})
        if not spec or not days:
            return 0
        t9 = int(time.time() if ts is None else ts) + 1
        with self.lock:
            st9 = dict(self.st)
            if invalidate:
                st9 = self._invalidate(st9, spec, days)
                inv9 = self.__dict__.setdefault("_inv", {})
                inv9.setdefault(spec, []).append((time.time(), set(days)))
            chg9 = {k: dict(v) for k, v in (st9.get("chg") or {}).items() if isinstance(v, dict)}
            cl9 = chg9.setdefault(spec, {})
            for d9 in days:
                cl9[d9] = max(int(cl9.get(d9) or 0), t9)
            st9["chg"] = chg9
            self.st = st9
            self.gen += 1
            common.atomic_write_json(self.path, self.st)
        log.warning("그날 마감가 변경 기록(장기 곡선 쪽 동명 차단·대체): %s %d일(%s~)", spec, len(days), days[0])
        return len(days)

    def _mark_dirty(self, iso):
        t9 = int(datetime.strptime(iso, "%Y-%m-%d").replace(tzinfo=KST, hour=12).timestamp())
        (getattr(self, "mark", None) or common.mark_hist_dirty)(t9)
        log.warning("동명 차단·동일성 확인 뒤 장기 곡선 다시 계산 표식: %s 부터", iso)

    def lookup_state(self, spec, iso, now):
        if now < settle_ts(iso):
            return "wait"
        sts9 = {day_state(e, iso, self._ffp(e)) for e in self._sources(spec) if self.covers(e, iso)}
        return "ok" if "ok" in sts9 else ("none" if "none" in sts9 else "pending")


def _px1004_backup(paths, ts):
    import shutil
    out = []
    for src9 in paths:
        if os.path.exists(src9):
            dst9 = f"{src9}.bak_px1004_{int(ts)}"
            shutil.copy2(src9, dst9)
            out.append(dst9)
    return out


def migrate_px1004(dc=None, hist=None, now=None, backup=_px1004_backup, mark=None) -> dict | None:
    dc = dc if dc is not None else DAYCLOSE
    hist = hist if hist is not None else HIST
    now = time.time() if now is None else now
    ts = int(now)
    m0 = dict(dc.st.get("px1004") or {}) if isinstance(dc.st.get("px1004"), dict) else {}
    bad_dc = sorted(k for k, e in ((dc.st.get("s") or {}) if dc is not None else {}).items() if isinstance(e, dict) and stale_src(k, e.get("src")))
    hs = ((hist.px.get("specs") or {}) if hist is not None else {})
    hpend0 = set(m0.get("hpend") or ())
    bad_h = sorted({k for k, e in hs.items() if isinstance(e, dict) and stale_src(k, e.get("src"))} | (hpend0 & set(hs)))
    if not bad_dc and not bad_h and not hpend0:
        return None
    first = min((min(hs[k]["p"]) for k in bad_h if isinstance(hs[k].get("p"), dict) and hs[k]["p"]), default=None) or m0.get("hfrom")
    dirty_p = os.path.join(common.STATE_DIR, common.HIST_DIRTY)
    files9 = [dc.path] + ([hist.px_path] if bad_h else []) + ([dirty_p] if (bad_h or hpend0) and first and os.path.exists(dirty_p) else [])
    try:
        bak = backup(files9, ts) if backup else []
    except Exception as e9:
        log.warning("px1004: 이관 전 백업 실패 — 이번 기동은 안 바꿈: %s", e9)
        return None
    rep = {"dc": bad_dc, "hist": bad_h, "from": first, "bak": bak}
    hpend9 = sorted(set(bad_h) | hpend0)

    def save_dc(hpend):
        with dc.run_lock:
            with dc.lock:
                m9 = dict(dc.st.get("px1004") or {}) if isinstance(dc.st.get("px1004"), dict) else {}
                s9 = {k: v for k, v in (dc.st.get("s") or {}).items() if k not in set(bad_dc)}
                rec9 = {"v": PX1004_V, "at": int(m9.get("at") or ts), "last": ts,
                        "specs": sorted(set(m9.get("specs") or ()) | set(bad_dc) | set(bad_h)),
                        "bak": list(dict.fromkeys(list(m9.get("bak") or ()) + bak))}
                if hpend:
                    rec9.update(hpend=hpend, hfrom=first)
                chg9 = {k9: dict(v9) for k9, v9 in (dc.st.get("chg") or {}).items() if isinstance(v9, dict)}
                for k9 in set(bad_dc) | set(bad_h):
                    chg9.setdefault(k9, {})["*"] = max(int(chg9.get(k9, {}).get("*") or 0), ts)
                dc.st = dict(dc.st, s=s9, px1004=rec9, chg=chg9)
                dc.gen += 1
                dc._ff = {}
            common.atomic_write_json(dc.path, dc.st)
    save_dc(hpend9)
    if hpend9:
        if first:
            t9 = int(datetime.strptime(first, "%Y-%m-%d").replace(tzinfo=KST, hour=12).timestamp())
            (mark or common.mark_hist_dirty)(t9)
        with hist.run_lock:
            with hist.lock:
                for k in hpend9:
                    hist.px["specs"].pop(k, None)
            common.atomic_write_json(hist.px_path, hist.px)
        save_dc(None)
    log.warning("px1004: 새 규칙 밖 출처(업비트·빗썸 USDT·BTC · OKX·게이트·쿠코인 대체) 시세 저장본 지움 — 그날 마감가 %d개 %s · 장기 곡선 %d개(다시 계산 %s 부터) · 백업 %s",
                len(bad_dc), bad_dc[:12], len(hpend9), first, bak)
    return rep


HIST = HistCurve()
DAYCLOSE = DayClose(hist=HIST)
