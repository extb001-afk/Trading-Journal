from __future__ import annotations
import os
from datetime import datetime
from datetime import timedelta
from decimal import Decimal
from decimal import InvalidOperation
import num_parse, paths, statefile
import bisect
import calcguard  # noqa: E402


STAKE_STATE_KO = {"activating": "스테이킹 활성화 대기", "active": "스테이킹 중", "deactivating": "스테이킹 해제 중",
                  "inactive": "스테이킹 해제됨 · 인출 가능", "undelegated": "위임 안 됨", "closed": "닫힘"}


def _sol_stake_accounts() -> dict:
    try:
        d = statefile.read_json(paths.state("sol_stake.json"), {}) or {}
        acc = d.get("accounts") or {}
        return acc if isinstance(acc, dict) else {}
    except (Exception, SystemExit) as _cg9:  # noqa: BLE001 [fallback]
        calcguard.swallowed("view_misc:_sol_stake_accounts", _cg9)
        return {}


def _recon_q(q) -> str:
    try:
        d = Decimal(str(q))
    except (InvalidOperation, ValueError, TypeError):
        return str(q)
    if not d.is_finite() or d == 0:
        return "0"
    a = abs(d)
    nd = 4 if a >= 1 else min(12, max(4, 3 - a.adjusted()))
    t = f"{a:,.{nd}f}"
    t = t.rstrip("0").rstrip(".") if "." in t else t
    return "0" if t in ("0", "") else ("-" if d < 0 else "") + t


def _rate_state(spot, now=None) -> str:
    f9 = getattr(spot, "rate_state", None)
    if callable(f9):
        return f9(now)
    return "live" if getattr(spot, "rate", None) else "none"


def _px_took(px) -> bool:
    f9 = getattr(px, "took_pending", None)
    return bool(f9()) if f9 else False


HIST_NF = "nf"


def _hist_kit_rows(daily, today_iso, cache, flow_nf=(), val_nf=()):
    rows = list(daily or ())
    n = len(rows)
    t0 = datetime.strptime(today_iso, "%Y-%m-%d")
    fnf = set(flow_nf or ())
    vnf = set(val_nf or ())
    out, nf, past, fin = [], set(), 0, 0
    for i, r in enumerate(rows):
        iso = (t0 - timedelta(days=n - 1 - i)).strftime("%Y-%m-%d")
        r2 = dict(r)
        if iso < today_iso:
            past += 1
            c = (cache or {}).get(iso)
            if iso in vnf or not (isinstance(c, dict) and c.get("val") is not None):
                r2[HIST_NF] = ("val", "flow")
                r2["val"] = None
                r2["flow"] = None
                nf.add(iso)
            else:
                fin += 1
                if iso in fnf:
                    r2[HIST_NF] = ("flow",)
                    r2["flow"] = None
                    nf.add(iso)
        out.append(r2)
    return out, nf, (past == 0 or fin > 0)


def _px_recent(px, sym, ms):
    f9 = getattr(px, "candle_recent", None)
    return f9(sym, ms) if f9 else px.candle_usd(sym, ms)


def _dec_or0(x) -> Decimal:
    return num_parse.to_dec(x, Decimal(0))


class _BuildObsolete(Exception):
    pass


def _fx_candle_near(fxb, sym, ts, within_s=3600):
    c0 = fxb.candle(sym, ts)
    if not c0:
        return None
    idx = getattr(fxb, "_csym", {}).get(str(sym or "").upper())
    if idx is None:
        return c0
    ks, pts = idx
    m = (int(ts) * 1000 // 60_000) * 60_000
    if m in pts:
        return pts[m]
    j = bisect.bisect_left(ks, m)
    best = None
    for i in (j - 1, j):
        if 0 <= i < len(ks):
            d = abs(ks[i] - m)
            if d <= int(within_s) * 1000 and (best is None or d < best[0]):
                best = (d, ks[i])
    return pts[best[1]] if best else None


fx_candle_near = _fx_candle_near


def _venue_flows30(vflow, real_loc, venue_w, today_kst):
    lo9 = (today_kst - timedelta(days=29)).strftime("%Y-%m-%d")
    by = {}

    def slot(loc):
        w9 = venue_w(loc)
        if not w9:
            return None
        return by.setdefault(w9, {"in": 0.0, "out": 0.0, "realized": 0.0, "realizedKrw": 0.0})
    for loc9, v9 in (vflow or {}).items():
        b9 = slot(loc9)
        if b9 is not None:
            b9["in"] += float(v9[0])
            b9["out"] += float(v9[1])
    for (loc9, d9), v9 in (real_loc or {}).items():
        if str(d9) < lo9:
            continue
        b9 = slot(loc9)
        if b9 is not None:
            b9["realized"] += float(v9[0])
            b9["realizedKrw"] += float(v9[1])
    return {"days": 30, "flowOk": vflow is not None,
            "by": {k9: {"in": round(b9["in"], 2), "out": round(b9["out"], 2), "realized": round(b9["realized"], 2),
                        "realizedKrw": round(b9["realizedKrw"])} for k9, b9 in by.items()}}


def build_stats(hist) -> dict:
    h = [int(x) for x in hist if isinstance(x, (int, float))]
    if not h:
        return {"last_ms": None, "p50": None, "p95": None, "n": 0}
    srt = sorted(h)

    def q(p):
        return srt[min(len(srt) - 1, max(0, int(round(p * (len(srt) - 1)))))]
    return {"last_ms": h[-1], "p50": q(0.5), "p95": q(0.95), "n": len(h)}


def _cfg_file_sig():
    try:
        st9 = os.stat(paths.CONFIG_PATH)
        return (st9.st_mtime_ns, st9.st_size)
    except OSError:
        return None
