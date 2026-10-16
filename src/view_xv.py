from __future__ import annotations
import copy
from datetime import datetime
from decimal import Decimal
import histcurve
import xparts
from view_common import _f

XV_V = 1


def _xv_sum(xv) -> float:
    p9 = xv.get("p") if isinstance(xv, dict) else None
    if not isinstance(p9, dict):
        return 0.0
    fx9 = float(xv.get("fx") or 0)
    k9 = sum(float(p9[k][0] or 0) for k in ("ku", "kb") if isinstance(p9.get(k), list) and p9[k])
    r9 = float(p9["rest"][0] or 0) if isinstance(p9.get("rest"), list) and p9["rest"] else 0.0
    u9 = sum(float(v or 0) for v in xv["ubv"].values()) if isinstance(xv.get("ubv"), dict) else 0.0
    return (k9 / fx9 if fx9 > 0 else 0.0) + r9 + u9


def _xv_checked(xv, x):
    if not isinstance(xv, dict) or not isinstance(xv.get("p"), dict) or not xv["p"]:
        return None
    out = copy.deepcopy(xv)
    out.pop("dx", None)
    try:
        dx = round(float(x) - _xv_sum(out), 2)
    except (TypeError, ValueError, IndexError, AttributeError):
        return None
    if abs(dx) > 0.05 + 0.005 * len(out.get("ubv") or ()):
        out["dx"] = dx
    return out


def _xv_parts(xv):
    if not isinstance(xv, dict) or not isinstance(xv.get("p"), dict):
        return None
    ubv = xv.get("ubv") if isinstance(xv.get("ubv"), dict) else {}
    out = {}
    for key, v in xv["p"].items():
        if key not in xparts.KEYS or not (isinstance(v, (list, tuple)) and len(v) >= 2 and v[1] in xparts.RANK):
            continue
        if key == "ub":
            q9 = v[0] if isinstance(v[0], dict) else {}
            out["ub"] = [xparts.ub_norm({s9: [a9[0] if isinstance(a9, (list, tuple)) else a9,
                                              (a9[1] if isinstance(a9, (list, tuple)) and len(a9) > 1 else ubv.get(s9, 0.0))]
                                         for s9, a9 in q9.items()}), v[1]]
        else:
            f9 = xparts.num(v[0])
            out[key] = [f9 if f9 is not None else 0.0, v[1]]
    return out


def _xv_disk(parts, fx, how, **meta):
    p9, ubv9 = {}, {}
    for key in xparts.KEYS:
        v = (parts or {}).get(key)
        if not (isinstance(v, (list, tuple)) and len(v) >= 2):
            continue
        if key == "ub":
            u9 = xparts.ub_norm(v[0])
            p9["ub"] = [{s9: round(a9[0], 12) for s9, a9 in sorted(u9.items())}, v[1]]
            ubv9 = {s9: round(a9[1], 2) for s9, a9 in sorted(u9.items())}
        else:
            p9[key] = [round(float(v[0] or 0), 2), v[1]]
    out = {"v": xparts.GEN, "p": p9, "fx": float(fx) if fx else None, "how": how}
    if ubv9:
        out["ubv"] = ubv9
    for k9, v9 in meta.items():
        if v9 is not None:
            out[k9] = v9
    return out


def _xv_ob(xv):
    out = []
    if not isinstance(xv, dict):
        return out
    if xv.get("v") == xparts.GEN:
        for key, a9 in (xv.get("ob") or {}).items():
            if key == "ku" and xv.get("ufk"):
                continue
            if key in xparts.KRW and isinstance(a9, (list, tuple)) and len(a9) >= 2 and xparts.num(a9[0]) and xparts.num(a9[1]) is not None:
                out.append((key, float(a9[0]), float(a9[1])))
        return out
    rt9 = xv.get("rt") if isinstance(xv.get("rt"), dict) else {}
    p9 = xv.get("p") if isinstance(xv.get("p"), dict) else {}
    for key, ex9 in (("ku", "upbit"), ("kb", "bithumb")):
        if key == "ku" and xv.get("ufk"):
            continue
        v9 = p9.get(key)
        t9 = xparts.num(rt9.get(ex9))
        if t9 and isinstance(v9, (list, tuple)) and len(v9) >= 2 and xparts.num(v9[0]) is not None:
            out.append((key, t9, float(v9[0])))
    return out


def _ufc_ku(p9, fx9, how9, m9, end_ts, src):
    uc9 = (m9 or {}).get("ufc")
    uc9 = dict(uc9) if isinstance(uc9, dict) else {}
    uz9 = (m9 or {}).get("ufz")
    if isinstance(uz9, dict) and uz9:
        ufp0 = ((src or {}).get("now") or {}).get("ufp") or {}

        def in_day9(u9):
            t9 = xparts.num(ufp0.get(u9)) if u9 in ufp0 else None
            return t9 is not None and t9 <= end_ts
        for z9 in uz9.values():
            if isinstance(z9, dict) and any(in_day9(u9) for u9 in z9):
                for u9, k9 in z9.items():
                    uc9.setdefault(u9, k9)
    if not uc9 and xparts.num((m9 or {}).get("ku0")) is None:
        return p9, fx9, how9, m9
    ku9 = (p9 or {}).get("ku")
    if not (isinstance(ku9, (list, tuple)) and len(ku9) >= 2 and ku9[1] in ("snap", "carry")):
        return p9, fx9, how9, m9
    base9 = xparts.num((m9 or {}).get("ku0"))
    if base9 is None:
        base9 = xparts.num(ku9[0]) or 0.0
    ufp9 = ((src or {}).get("now") or {}).get("ufp") or {}
    adj9 = 0.0
    for u9, k9 in uc9.items():
        k9 = xparts.num(k9)
        if not k9:
            continue
        if u9 in ufp9:
            t9 = xparts.num(ufp9[u9])
            if t9 is None or t9 <= end_ts:
                continue
        adj9 -= k9
    m9 = dict(m9, ku0=round(base9, 2))
    p9 = dict(p9, ku=[round(max(base9 + adj9, 0.0), 2), ku9[1]])
    return p9, fx9, how9, m9


def _xv_obs_parts(xv):
    p9 = _xv_parts(xv)
    if p9 is not None and isinstance(xv, dict) and xparts.num(xv.get("ku0")) is not None and isinstance(p9.get("ku"), list):
        p9 = dict(p9, ku=[xparts.num(xv["ku0"]), p9["ku"][1]])
    return p9


XQ_X_KEYS = histcurve.XQ_X_KEYS


def _xq_sets(meta_rows, first_seen, marker_ts) -> tuple:
    now9, late9 = set(), set()
    for k9, _v9 in meta_rows or ():
        k9 = str(k9)
        ex9 = "upbit" if k9 == "recon_done_upbit" else k9[len("recon_done_exf_"):] if k9.startswith("recon_done_exf_") else ""
        if not ex9:
            continue
        now9.add(ex9)
        f9 = xparts.num((first_seen or {}).get(ex9))
        if marker_ts and f9 and f9 > float(marker_ts) + 3600:
            late9.add(ex9)
    return ",".join(sorted(now9)), ",".join(sorted(now9 - late9))


def _x_end(iso, tz):
    return datetime.strptime(str(iso), "%Y-%m-%d").replace(tzinfo=tz, hour=23, minute=59, second=59).timestamp()


def _x_sync_entry(c, parts, fx, ref):
    raw = round(xparts.total_usd(parts, fx), 2)
    d = round(raw - float(ref), 2)
    cut = max(0.0, float(ref) - float(c.get("x") or 0))
    ch = False
    if abs(d) >= 0.005:
        c["val"] = _f(Decimal(str(c["val"])) + Decimal(str(d)), 2) or 0
        c["x"] = round(float(c["x"]) + d, 2)
        ch = True
    ub9 = xparts.ub_norm((parts.get("ub") or [None])[0]) if parts.get("ub") else {}
    if ub9 and cut < 0.005:
        cur9 = c.get("xu") if isinstance(c.get("xu"), dict) else {}
        add9 = {s9: [round(a9[0], 12), round(a9[1], 2)] for s9, a9 in sorted(ub9.items()) if s9 not in cur9}
        if add9:
            c["xu"] = dict(cur9, **add9)
            ch = True
    cr = xparts.carry_usd(parts, fx)
    if (parts.get("ub") or [None, None])[1] == "carry":
        cr -= cut
    xc_new = round(cr, 2) if cr >= 1 else None
    if c.get("xc") != xc_new:
        if xc_new is None:
            c.pop("xc", None)
        else:
            c["xc"] = xc_new
        ch = True
    if c.get("xraw") != raw:
        c["xraw"] = raw
        ch = True
    return d if ch else None
