from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from decimal import InvalidOperation

import histmark
import num_parse
from timeutil import KST

__all__ = ["UrBuild", "attach", "by_symbol", "day_excl", "leg_index", "flow_prev_reprice", "nopx_flow_px", "past_flow_px", "prev_band_px", "prev_only", "prev_out", "unv_live_keep"]


def _num(v: object) -> float:
    return num_parse.to_float(v, 0.0)


def _sym(G: dict, gid: int) -> str:
    return str((G.get(gid) or {}).get("sym") or "?").upper()


def prev_only(own: dict, pdx: dict, ppx: dict, moved: Callable, G: dict, moves: dict, int_ev: frozenset) -> set:
    prev = {g for g in own if not _num(pdx.get(str(g))) and _num(ppx.get(str(g))) and moved(g)
            and not any(e not in int_ev and q for e, q in (moves.get(g) or {}).items())}
    day_syms = {_sym(G, g) for g in own if _num(pdx.get(str(g)))}
    return {g for g in prev if _sym(G, g) in day_syms}


def day_excl(day: str, opening: dict, fut: dict, debt: dict, real: dict | None, live: bool = False) -> set:
    out = set(opening.get(day) or ()) | set(fut.get(day) or ()) | set(debt.get(day) or ())
    return out if live else out | set((((real or {}).get("unv") or {}).get(day) or {}))


def by_symbol(own: dict, G: dict, skip: set) -> dict:
    out = {}
    for gid in own:
        if gid not in skip:
            out.setdefault(_sym(G, gid), []).append(gid)
    return out


def prev_band_px(prev: set, own: dict, bands: dict, live_px: dict | None, G: dict, band: tuple, pdx: dict) -> dict:
    lo, hi = band
    out = {}
    for gid in sorted(prev):
        bs = bands.get(_sym(G, gid)) or ()
        if any(gid in gs and any(g not in prev for g in gs) for _bp, gs in bs):
            continue
        cv = _num(live_px.get(gid)) if live_px is not None else own[gid]
        fit = [bp for bp, gs in bs if any(_num(pdx.get(str(g))) for g in gs) and lo <= cv / bp <= hi]
        if fit:
            out[gid] = min(fit, key=lambda bp: abs(cv / bp - 1))
    prev.intersection_update(out)
    return out


def unv_live_keep(band_px: Callable, prev: set, unv: dict, flow_px: dict, day: str, bands: dict) -> dict:
    cand = prev & set(unv)
    prev.difference_update(cand)
    out = band_px(prev)
    alt = band_px(set(cand)) if cand else {}
    for gs in (gs for bs in bands.values() for _bp, gs in bs if cand & set(gs)):
        if set(gs) <= cand and all(g in alt and abs(alt[g] - _num(flow_px.get((day, g)))) <= 1e-9 * alt[g] for g in gs):
            out.update({g: alt[g] for g in gs})
            prev.update(gs)
    return out


def flow_prev_reprice(acc: dict, px: tuple, G: dict, src: tuple, today_iso: str, band: tuple, held: dict) -> dict:
    (dpx, att_src), out = src, {}
    for ck, syms in acc.items():
        sd = att_src.get(ck)
        if ck >= today_iso or not sd or not isinstance(sd[0], dict):
            continue
        cut = ((dpx.get(ck) or {}).get("p") or {}, sd[0], sd[1] or {})
        for sym, gm in syms.items():
            if (ck, sym) not in held:
                out.update(_reprice_one(ck, gm, cut, px, G, band))
    return out


def _chain(pc: dict) -> list:
    cl = []
    for g in sorted(pc, key=lambda g: (pc[g], g)):
        if cl and pc[g] <= cl[-1][0] * 1.2:
            cl[-1][1].append(g)
        else:
            cl.append([pc[g], [g]])
    return cl


def _reprice_one(ck: str, gm: dict, cut: tuple, px: tuple, G: dict, band: tuple) -> dict:
    (gpx, gpxc, gsrc), (lo, hi), (dp, gd, pd) = px, band, cut
    if any((G.get(g) or {}).get("is_stable") or not gpxc.get((ck, g)) for g in gm):
        return {}
    pc = {g: gpxc[(ck, g)] for g in gm}
    pf = {g for g in pc if not _num(dp.get(str(g))) and not _num(gd.get(str(g))) and not _num(pd.get(str(g)))}
    cl = _chain(pc)
    if not pf or {frozenset(gs) for _p, gs in cl} != {frozenset(gs) for _p, gs in _chain({g: _num(gpx.get((ck, g))) for g in pc})}:
        return {}
    refs = [max(gs, key=lambda g: (sum(abs(v) for v in gm[g].values()), -g)) for _p, gs in cl]
    refs = [r for r in refs if _num(dp.get(str(r)))]
    out = {}
    for _p, gs in cl:
        if set(gs) - pf:
            continue
        tg = {min((r for r in refs if lo <= pc[g] / pc[r] <= hi), key=lambda r: abs(pc[g] / pc[r] - 1), default=None) for g in gs}
        if len(tg) != 1 or None in tg:
            continue
        r = tg.pop()
        for g in gs:
            gpx[(ck, g)], gpxc[(ck, g)], gsrc[(ck, g)] = gpx[(ck, r)], pc[r], {}
            out[(ck, g)] = pc[r]
    return out


def nopx_flow_px(legs: dict, moves: dict, skip: set, own: dict, flow_px: dict, day: str) -> dict:
    out = {}
    for g, q in legs.items():
        f = _num(flow_px.get((day, g)))
        if f and g not in own and g not in skip and not sum(q, Decimal(0)) + sum((moves.get(g) or {}).values(), Decimal(0)):
            out[g] = f
    return out


def past_flow_px(prev: set, rep: dict, flow_px: dict, day: str) -> dict:
    out = {g: _num(flow_px.get((d, g))) for (d, g) in rep if d == day and _num(flow_px.get((d, g)))}
    prev.difference_update(out)
    return out


def prev_out(gid: int, gpv: float, pp: float, prev: set, live: bool, moves: dict, int_ev: frozenset) -> float:
    if gid not in prev or live:
        return -gpv
    ext_q = float(sum((v for e, v in (moves.get(gid) or {}).items() if e not in int_ev), Decimal(0)))
    return -(gpv / pp + ext_q) * pp


@dataclass
class UrBuild:
    rows: list
    G: dict
    skip: frozenset
    trade_ev: frozenset
    cap: int
    ix: dict = field(default=None)
    rz: dict = field(default=None)


def leg_index(rows: list, G: dict, skip: frozenset, trade_ev: frozenset) -> dict:
    out = {}
    for ts, qb, dec, gid, ev, lk, loc, lseq, ns, sid, cu in rows:
        g = G.get(gid)
        if gid in skip or not g or g.get("is_fiat") or str(loc or "").startswith("lp:") or histmark.exf_is_fut(ev, ns):
            continue
        if lk in ("fee", "gas") or histmark.exf_is_debt_int(ev, lseq, ns, sid) or ev not in trade_ev:
            continue
        try:
            q = Decimal(int(qb)) / (Decimal(10) ** int(dec if dec is not None else 18))
        except (TypeError, ValueError, InvalidOperation):
            continue
        if not q:
            continue
        day = datetime.fromtimestamp(ts, KST).strftime("%Y-%m-%d")
        e = out.setdefault(day, {}).setdefault(gid, [Decimal(0)] * 6)
        buy = q > 0
        e[0 if buy else 1] += abs(q)
        c = num_parse.to_dec(cu) if cu is not None else None
        if c is None:
            e[4 if buy else 5] += abs(q)
        else:
            e[2 if buy else 3] += abs(c)
    return out


def _realized(G: dict, skip: frozenset) -> dict:
    out = {}
    for gid, g in G.items():
        if gid in skip or not isinstance(g, dict) or g.get("is_fiat") or g.get("is_stable"):
            continue
        for fl in g.get("flows") or ():
            for day, v in ((fl or {}).get("rbd") or {}).items():
                if v:
                    o = out.setdefault(str(day), {})
                    o[gid] = o.get(gid, 0.0) + float(v)
    return out


def _rows(ub: UrBuild, day: str, px_of, unv: dict) -> dict:
    ix, rz = ub.ix.get(day) or {}, ub.rz.get(day) or {}
    acc = {}
    for gid in set(ix) | set(rz) | set(unv):
        g = ub.G.get(gid) or {}
        if gid in ub.skip or not g or g.get("is_stable") or g.get("is_fiat"):
            continue
        qb, qs, bc, sc, nb, ns = (float(x) for x in (ix.get(gid) or [0] * 6))
        p = px_of(gid)
        bu, su = bc + nb * p, sc + ns * p
        r = rz.get(gid, 0.0)
        uq, up = unv.get(gid) or (0.0, 0.0)
        tot = (qb - qs) * p + su - bu - r - (float(up) - float(uq) * p)
        a = acc.setdefault(str(g.get("sym") or "?").upper(), [0.0] * 8)
        for i, x in enumerate((su, bu, r, tot, float(up), qb, qs, qb * p)):
            a[i] += x
    by = {}
    for sym, (su, bu, r, tot, up, qb, qs, qbp) in acc.items():
        qn = qb - qs
        mn = qn * qbp / qb - bu * qn / qb if qn > 0 and qb > 0 else 0.0
        cn = bu * min(qs, qb) / qb if qb > 0 and qs > 0 else 0.0
        by[sym] = [su, bu, r, tot - mn, mn, tot, cn, up]
    return by


def attach(det: dict, ub: UrBuild, day: str, att: dict, legs: dict, leg_px: dict, real: dict | None) -> None:
    if "ur" not in att or not isinstance(real, dict):
        return
    if ub.ix is None:
        ub.ix, ub.rz = leg_index(ub.rows, ub.G, ub.skip, ub.trade_ev), _realized(ub.G, ub.skip)

    def px_of(gid):
        return 1.0 if (ub.G.get(gid) or {}).get("is_stable") else float(leg_px.get(gid, 0.0))

    def r2(v):
        return round(float(v), 2)
    by = _rows(ub, day, px_of, (real.get("unv") or {}).get(day) or {})
    lst = sorted(([s] + [r2(x) for x in v] for s, v in by.items() if any(abs(x) >= 0.005 for x in v)), key=lambda x: (-abs(x[6]), x[0]))
    fee = lp = 0.0
    for gid, (_qt, qf, ql, qx) in (legs or {}).items():
        p = px_of(gid)
        if p:
            fee += float(qf) * p
            lp += float(ql + qx) * p
    gx = r2(att.get("gx") or 0)
    if len(lst) > ub.cap:
        det.setdefault("more", {})["ur"] = [len(lst) - ub.cap, r2(sum(x[6] for x in lst[ub.cap:]))]
    etc = r2(float(att["ur"]) - sum(x[6] for x in lst) - r2(fee) - r2(lp) - gx)
    det["ur"] = {"rows": lst[:ub.cap], "n": len(lst), "fee": r2(fee), "lp": r2(lp), "gx": gx, "etc": etc}
