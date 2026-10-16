from __future__ import annotations
from decimal import Decimal
import bf_engine
from view_common import EPS

BR_QTY_LO, BR_QTY_HI = Decimal("0.98"), Decimal("1.02")

BR_UNIQ_LO = Decimal("0.90")

BR_WIN = (-600, 21600)

BR_SPLIT_MAX = 6


def _bridge_plan(deps, arrs, links=None, amb=None) -> dict:
    from itertools import combinations
    links = links or {}
    by_sym = {}
    for a in arrs:
        by_sym.setdefault(a["sym"], []).append(a)
    for v in by_sym.values():
        v.sort(key=lambda a: a["ord"])
    used, out = set(), {}

    def fits(d, a):
        return (a["pid"] not in used and a["chain"] != d["chain"] and not a.get("spam")
                and links.get(a["link"], d["link"]) == d["link"]
                and d["ts"] + BR_WIN[0] <= a["ts"] <= d["ts"] + BR_WIN[1] and 0 < a["qty"] <= d["qty"] * BR_QTY_HI)
    deps = sorted(deps, key=lambda x: x["ord"])
    id_done = set()
    for d in deps:
        if not d["qty"] > 0:
            continue
        tot = Decimal(0)
        for a in by_sym.get(d["sym"], ()):
            if links.get(a["link"]) == d["link"] and fits(d, a) and tot + a["qty"] <= d["qty"] * BR_QTY_HI:
                used.add(a["pid"])
                out[a["pid"]] = d["pid"]
                tot += a["qty"]
                id_done.add(d["pid"])
    for d in deps:
        if not d["qty"] > 0 or d["pid"] in id_done:
            continue
        cs = [a for a in by_sym.get(d["sym"], ()) if fits(d, a)]
        if not cs:
            continue
        near = [a for a in cs if a["qty"] >= d["qty"] * BR_QTY_LO]
        if near:
            tier = ([a for a in near if (a["addr"] or "") == (d["addr"] or "")] or [a for a in near if a.get("bridge")] or near)
            if len({a["addr"] or "" for a in tier}) > 1:
                if amb is not None:
                    for a in near:
                        amb.setdefault(a["pid"], d["pid"])
                continue
            pick = [min(tier, key=lambda a: (0 if a.get("bridge") else 1, 0 if a["ts"] >= d["ts"] else 1, a["ord"]))]
        else:
            pick = []
        if not pick:
            small = [a for a in cs if a["qty"] < d["qty"] * BR_QTY_LO][:BR_SPLIT_MAX]
            best = None
            for k9 in range(2, len(small) + 1):
                for comb in combinations(small, k9):
                    s9 = sum((a["qty"] for a in comb), Decimal(0))
                    if d["qty"] * BR_QTY_LO <= s9 <= d["qty"] * BR_QTY_HI:
                        key9 = (abs(s9 - d["qty"]), max(a["ord"] for a in comb))
                        if best is None or key9 < best[0]:
                            best = (key9, list(comb))
                if best:
                    break
            pick = best[1] if best else []
        if not pick and len(cs) == 1 and d["qty"] * BR_UNIQ_LO <= cs[0]["qty"] < d["qty"] * BR_QTY_LO:
            if not any(d2 is not d and d2["sym"] == d["sym"] and d2["qty"] > 0 and fits(d2, cs[0]) for d2 in deps):
                pick = cs
        for a in pick:
            used.add(a["pid"])
            out[a["pid"]] = d["pid"]
    return out

LOAN_MIN_S = 6 * 3600

LOAN_SKIP_EX = ("upbit", "bithumb", "hyperliquid")


def _loan_windows(cfg_v) -> dict:
    out = {}
    for w9 in (cfg_v if isinstance(cfg_v, list) else ()):
        if not isinstance(w9, dict):
            continue
        ex9, as9 = str(w9.get("exchange") or "").strip().lower(), str(w9.get("asset") or "").strip().upper()
        f9, t9 = bf_engine.parse_date_ts(w9.get("from")), bf_engine.parse_date_ts(w9.get("to"))
        if not ex9 or not as9 or f9 is None or t9 is None:
            continue
        if not isinstance(w9.get("to"), (int, float)):
            t9 += 86400 - 1
        if t9 >= f9:
            out.setdefault((ex9, as9), []).append((int(f9), int(t9)))
    return out


def _loan_plan(items, min_s=LOAN_MIN_S, allow=None):
    from collections import deque
    qty, shorts, wd, fill = {}, {}, {}, {}
    for pid, key, kind, ts, q in items:
        pre = qty.get(key, Decimal(0))
        post = pre + q
        qty[key] = post
        if q < 0:
            dig = max(Decimal(0), -post) - max(Decimal(0), -pre)
            if dig > EPS:
                shorts.setdefault(key, deque()).append([pid if kind == "wd" else None, dig, ts])
        elif q > 0 and pre < -EPS:
            f = min(q, -pre)
            dq = shorts.get(key)
            while f > EPS and dq:
                s = dq[0]
                take = min(f, s[1])
                if kind == "in" and s[0] is not None and ts - s[2] >= min_s and (allow is None or allow(key, s[2], ts)):
                    wd[s[0]] = wd.get(s[0], Decimal(0)) + take
                    fill.setdefault(pid, []).append((s[0], take))
                s[1] -= take
                f -= take
                if s[1] <= EPS:
                    dq.popleft()
    return wd, fill
