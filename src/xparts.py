from __future__ import annotations

import math

GEN = 2
KEYS = ("ku", "kb", "ub", "rest")
KRW = ("ku", "kb")
RANK = {"snap": 3, "tl": 2, "carry": 1, "zero": 0}
TOL_KRW = 1000.0
CHK_TOL_KRW = 100_000.0
CHK_TOL_PCT = 0.01
REST_SEEN_USD = 1.0


def num(v):
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def ub_norm(v) -> dict:
    out = {}
    for s, a in (v.items() if isinstance(v, dict) else ()):
        try:
            q, u = num(a[0]), num(a[1])
        except (TypeError, IndexError, KeyError):
            continue
        if q is not None and u is not None and q > 0 and u >= 0:
            out[str(s).upper()] = [q, u]
    return out


def ub_usd(ub) -> float:
    return sum(a[1] for a in ub_norm(ub).values())


def _zero(key):
    return {} if key == "ub" else 0.0


def krw_at(base, tl, end_ts):
    if tl is None or not base:
        return None
    amt, ts = num(base[0]), num(base[1])
    if amt is None or not ts:
        return None
    if end_ts < ts:
        b = amt - sum(d for t, d in tl if end_ts < t <= ts)
    else:
        b = amt + sum(d for t, d in tl if ts < t <= end_ts)
    return max(b, 0.0) if b >= -TOL_KRW else None


def tl_value(key, end_ts, src):
    bad = num((src.get("bad") or {}).get(key)) or 0
    if bad and end_ts <= bad:
        return None
    return krw_at((src.get("base") or {}).get(key), (src.get("tl") or {}).get(key), end_ts)


def tl_bad(base, tl, obs):
    if tl is None or not base:
        return 0
    bad = 0
    for t, v in obs or ():
        t, v = num(t), num(v)
        if not t or v is None:
            continue
        r = krw_at(base, tl, t)
        if r is None or abs(r - v) > max(CHK_TOL_KRW, CHK_TOL_PCT * abs(v)):
            bad = max(bad, t)
    return bad


def nearest(obs, end_ts, now_ts, key):
    best = None
    for iso in sorted(obs or {}):
        o = obs[iso]
        if not isinstance(o, dict) or key not in o or num(o.get("end")) is None:
            continue
        d = abs(float(o["end"]) - end_ts)
        if best is None or d < best[0] or (d == best[0] and float(o["end"]) > best[1]):
            best = (d, float(o["end"]), o)
    if best is None or (now_ts is not None and abs(now_ts - end_ts) <= best[0]):
        return None
    return best[2]


def _val(key, v):
    if key == "ub":
        return ub_norm(v)
    f = num(v)
    return f if f is not None else 0.0


def resolve(end_ts, src, pinned=None) -> dict:
    now = src.get("now") or {}
    first = src.get("first") or {}
    obs = src.get("obs") or {}
    pinned = pinned or {}
    out = {}
    for key in KEYS:
        old = pinned.get(key)
        if isinstance(old, (list, tuple)) and len(old) >= 2 and old[1] in ("snap", "carry"):
            out[key] = [_val(key, old[0]), old[1]]
            continue
        f = num(first.get(key))
        if f is not None and end_ts < f:
            out[key] = [_zero(key), "zero"]
            continue
        if key in KRW:
            v = tl_value(key, end_ts, src)
            if v is not None:
                out[key] = [round(v, 2), "tl"]
                continue
            bad = num((src.get("bad") or {}).get(key)) or 0
            if isinstance(old, (list, tuple)) and len(old) >= 2 and old[1] == "tl" and not (bad and end_ts <= bad):
                out[key] = [_val(key, old[0]), "tl"]
                continue
        near = nearest(obs, end_ts, num(now.get("ts")), key)
        v = near[key] if near is not None else now.get(key)
        out[key] = [_val(key, v), "carry"]
    return out


def total_usd(parts, fx) -> float:
    fx = num(fx) or 0.0
    k = sum(num((parts.get(key) or [0])[0]) or 0.0 for key in KRW)
    r = num((parts.get("rest") or [0])[0]) or 0.0
    return (k / fx if fx > 0 else 0.0) + r + ub_usd((parts.get("ub") or [{}])[0])


def carry_usd(parts, fx) -> float:
    fx = num(fx) or 0.0
    out = 0.0
    for key in KEYS:
        p = parts.get(key)
        if not (isinstance(p, (list, tuple)) and len(p) >= 2 and p[1] == "carry"):
            continue
        if key == "ub":
            out += ub_usd(p[0])
        elif key == "rest":
            out += num(p[0]) or 0.0
        elif fx > 0:
            out += (num(p[0]) or 0.0) / fx
    return out


def rest_first(lp_first, obs, now=None, seen=None) -> tuple:
    cand = []
    for o in (obs or {}).values():
        if isinstance(o, dict) and (num(o.get("rest")) or 0.0) >= REST_SEEN_USD and num(o.get("end")):
            cand.append(float(o["end"]))
    n = now if isinstance(now, dict) else {}
    if (num(n.get("rest")) or 0.0) >= REST_SEEN_USD and num(n.get("ts")):
        cand.append(float(n["ts"]))
    if num(seen):
        cand.append(float(seen))
    seen2 = min(cand) if cand else None
    f = [t for t in (num(lp_first), seen2) if t]
    return (min(f) if f else None), seen2


def obs_entry(end_ts, parts, kinds=("snap",)) -> dict:
    o = {"end": float(end_ts)}
    for key in KEYS:
        p = (parts or {}).get(key)
        if isinstance(p, (list, tuple)) and len(p) >= 2 and p[1] in kinds and p[1] != "zero":
            o[key] = p[0]
    return o


def migrate_legacy(end_ts, x, xk, fx, xu, src, add_missing=True) -> dict:
    ub = ub_norm(xu)
    if xk not in ("live", "seed"):
        return {"p": resolve(end_ts, src, pinned={"ub": [ub, "carry"]}), "note": "calc→규칙 재계산"}
    x = num(x) or 0.0
    fx = num(fx) or 0.0
    ku, kb = tl_value("ku", end_ts, src), tl_value("kb", end_ts, src)
    ku = round(ku, 2) if ku is not None else None
    kb = round(kb, 2) if kb is not None else None
    uu = sum(a[1] for a in ub.values())
    tol = max(50.0, 0.01 * abs(x))
    if fx > 0:
        for use_ku, use_kb in ((True, True), (True, False), (False, True), (False, False)):
            k_u = ku if use_ku and ku is not None else 0.0
            k_b = kb if use_kb and kb is not None else 0.0
            r = x - (k_u + k_b) / fx - uu
            if r < -tol:
                continue
            p = {"ku": [k_u, "snap"], "kb": [k_b, "snap"], "ub": [ub, "snap"], "rest": [round(r, 2), "snap"]}
            added, odd = [], []
            if not use_kb and kb is not None and kb > 0 and add_missing:
                p["kb"] = [kb, "tl"]
                added.append("kb")
            if not use_ku and ku is not None and ku > 0:
                odd.append("ku")
            note = "live 보존" + (" + 원화 추가(" + "·".join(added) + ")" if added else "") + \
                (" · 분해 불가(" + "·".join(odd) + " — 옛 마감 합계가 그 원화 이력보다 작음 → 0 관측 그대로)" if odd else "")
            return {"p": p, "note": note}
    return {"p": {"ku": [0.0, "snap"], "kb": [0.0, "snap"], "ub": [ub, "snap"], "rest": [round(x - uu, 2), "snap"]}, "note": "분해 불가(덩어리)"}


def upgrade_obs(p1, end_ts, src) -> dict:
    pinned = {}
    for key in KEYS:
        v = (p1 or {}).get(key)
        if not (isinstance(v, (list, tuple)) and len(v) >= 2):
            continue
        if v[1] == "snap":
            pinned[key] = [_val(key, v[0]), "snap"]
        elif key in KRW and tl_value(key, end_ts, src) is not None:
            continue
        else:
            pinned[key] = [_val(key, v[0]), "carry"]
    return resolve(end_ts, src, pinned=pinned)


def ub_cut(ub, end_ts, sym_tl, qty_of) -> tuple:
    cut, rest = 0.0, {}
    for s, (q, u) in ub_norm(ub).items():
        qu = 0.0
        for gid, tl in sym_tl.get(s, ()):
            qg = 0.0
            for t, d in tl:
                if t > end_ts:
                    break
                qg += d
            qu += max(0.0, min(qg, float(qty_of(gid) or 0.0)))
        if qu > 1e-12:
            f = min(1.0, qu / q)
            cut += u * f
            if f < 1.0:
                rest[s] = [round(q * (1 - f), 12), round(u * (1 - f), 2)]
        else:
            rest[s] = [q, u]
    return cut, rest


def same(a, b, tol=0.005) -> bool:
    for key in KEYS:
        pa, pb = (a or {}).get(key), (b or {}).get(key)
        if (pa is None) != (pb is None):
            return False
        if pa is None:
            continue
        if pa[1] != pb[1]:
            return False
        if key == "ub":
            ua, ubb = ub_norm(pa[0]), ub_norm(pb[0])
            if set(ua) != set(ubb) or any(abs(ua[s][0] - ubb[s][0]) > 1e-9 * max(1.0, ua[s][0]) or abs(ua[s][1] - ubb[s][1]) > tol for s in ua):
                return False
        elif abs((num(pa[0]) or 0.0) - (num(pb[0]) or 0.0)) > tol:
            return False
    return True
