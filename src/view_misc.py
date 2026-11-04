from __future__ import annotations
import os
from datetime import datetime
from datetime import timedelta
from decimal import Decimal
from decimal import InvalidOperation
import num_parse, paths, statefile
import bisect
import calcguard  # noqa: E402
import db as dbm
import histcurve
import logging
import threading
from timeutil import KST
from typing import Any, Callable

log = logging.getLogger("tj-web")


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


def vf_add(vf: dict, vf_day: dict | None, loc: str, iso: str, inflow: bool, usd: float) -> None:
    cell = vf.setdefault(loc, [0.0, 0.0])
    cell[0 if inflow else 1] += usd
    if vf_day is not None:
        day_cell = vf_day.setdefault(loc, {}).setdefault(iso, [0.0, 0.0])
        day_cell[0 if inflow else 1] += usd


def _venue_flows30(vflow, real_loc, venue_w, today_kst, keep=None, conn=None):
    lo9 = (today_kst - timedelta(days=29)).strftime("%Y-%m-%d")
    if keep is not None:
        locs = set(vflow or ()) | {loc for loc, _day in (real_loc or ())} | {"exchange:upbit", "exchange:bithumb"}
        if conn is not None:
            locs |= {row[0] for row in conn.execute("SELECT DISTINCT location FROM postings WHERE location NOT LIKE 'out:%' AND location NOT LIKE 'lp:%'")}
        keep._venue_kit = {"name": {loc: venue_w(loc) for loc in sorted(locs)}, "real": real_loc, "today": today_kst.strftime("%Y-%m-%d")}
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


_VN_DAYS = (7, 30, 90, 0)
_VN_WIN = 30
_VN_LOCK = threading.Lock()


def _vn_days(query) -> int | None:
    val = ""
    for part in str(query or "").split("&"):
        if part.startswith("days="):
            val = part[5:].strip()
    if not val:
        return _VN_WIN
    return int(val) if val.isdigit() and int(val) in _VN_DAYS else None


def _venue_hist_flows(b: Any, hist: Any, days: list) -> dict:
    kit = getattr(hist, "kit", None) or {}
    fk = kit.get("fk") if isinstance(kit, dict) else None
    if not isinstance(fk, dict) or not days:
        raise ValueError("장기 곡선 재료(kit.fk) 없음")
    prev_day = (datetime.strptime(days[0], "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    dpx = hist.flow_prices(kit, [prev_day] + list(days))
    for iso, table in (fk.get("dpx_dc") or {}).items():
        if iso in dpx and table:
            dpx[iso] = table
    shell = object.__new__(type(b))
    shell.daily = fk.get("wdt") or {}
    shell.daily_px = {}
    shell._flow_px_delta, shell._att_fx_at, shell._att_bf = {}, None, None
    shell._venue_acc = acc = {}
    today = datetime.strptime(fk.get("today") or days[-1], "%Y-%m-%d").replace(tzinfo=KST)
    day_rows = (getattr(hist, "st", None) or {}).get("d") or {}

    def flow_fx(iso):
        row = day_rows.get(iso)
        if isinstance(row, list) and len(row) >= 4 and row[3] == "dc":
            return round(float(row[1]) / float(row[0]), 4) if row[0] and row[1] else None
        return hist.fx(iso)
    conn = dbm.open_db(paths.DB_PATH, readonly=True)
    try:
        type(b)._daily_flows(shell, conn, None, fk.get("G") or {}, today, {}, fk.get("skip") or frozenset(), fk.get("rate"),
                             transit=fk.get("transit") or [], offc_ids=fk.get("offc") or frozenset(), days=list(days), dpx=dpx, fx_day=flow_fx)
    finally:
        conn.close()
    return acc


def venue_flows_view(b: Any, hist: Any, query: str | None) -> tuple:
    days_n = _vn_days(query)
    if days_n is None:
        return 400, {"ok": False, "error": "days 는 7·30·90·0(전체) 중 하나"}
    last = getattr(b, "_last_out", None)
    fields = last.get("fields") if isinstance(last, dict) else None
    v30 = fields.get("venueFlows30") if isinstance(fields, dict) else None
    if days_n == _VN_WIN:
        return 200, dict(v30, ok=True) if isinstance(v30, dict) else {"ok": True, "days": 30, "flowOk": False, "by": {}, "why": "building"}
    kit = getattr(b, "_venue_kit", None)
    if not isinstance(kit, dict):
        return 200, {"ok": True, "days": days_n, "flowOk": False, "by": {}, "why": "building"}
    cache = kit.setdefault("_cache", {})
    hit = cache.get(days_n)
    if hit is None:
        with _VN_LOCK:
            hit = cache.get(days_n)
            if hit is None:
                hit = _venue_period(b, hist, kit, days_n)
                if not hit.get("partial"):
                    cache[days_n] = hit
    return 200, hit


def _venue_period(b: Any, hist: Any, kit: dict, days_n: int) -> dict:
    today = datetime.strptime(kit["today"], "%Y-%m-%d")
    since = (today - timedelta(days=days_n - 1)).strftime("%Y-%m-%d") if days_n else ""
    win0 = (today - timedelta(days=_VN_WIN - 1)).strftime("%Y-%m-%d")
    flow_day = getattr(b, "_venue_flow_day", None)
    by, names = {}, kit["name"]

    def slot(loc):
        name = names.get(loc)
        return None if not name else by.setdefault(name, [0.0, 0.0, 0.0, 0.0])

    def add_flow(loc, pair, ok):
        cell = slot(loc) if ok else None
        if cell is not None:
            cell[0] += float(pair[0])
            cell[1] += float(pair[1])
    for loc, by_day in (flow_day or {}).items():
        for iso, pair in by_day.items():
            add_flow(loc, pair, iso >= since)
    flow_from, partial = (win0 if flow_day is not None else None), False
    if flow_day is not None and (not days_n or since < win0):
        start = since or (getattr(hist, "kit", None) or {}).get("first") or histcurve.FIRST_DAY
        days, cursor = [], datetime.strptime(start, "%Y-%m-%d")
        while cursor.strftime("%Y-%m-%d") < win0:
            days.append(cursor.strftime("%Y-%m-%d"))
            cursor += timedelta(days=1)
        if not days:
            flow_from = start
        else:
            try:
                for loc, pair in _venue_hist_flows(b, hist, days).items():
                    add_flow(loc, pair, True)
                flow_from = start
            except Exception as exc:   # noqa: BLE001 [optional]
                calcguard.swallowed("view_misc:venue_flows_view[hist]", exc, expected=isinstance(exc, ValueError))
                log.warning("보관처 드나든 돈 창 밖 계산 실패(창 안만 표시): %s", exc)
                partial = True
    for (loc, day), pair in (kit.get("real") or {}).items():
        cell = slot(loc) if str(day) >= since else None
        if cell is not None:
            cell[2] += float(pair[0])
            cell[3] += float(pair[1])
    return {"ok": True, "days": days_n, "since": since or None, "flowOk": flow_day is not None, "flowFrom": flow_from, **({"partial": True} if partial else {}),
            "by": {name: {"in": round(vals[0], 2), "out": round(vals[1], 2), "realized": round(vals[2], 2), "realizedKrw": round(vals[3])}
                   for name, vals in by.items()}}


def gas_rows_by_date(gas_by_date: dict | None, chain_name: dict, exfee_lab: Callable, wdfee_lab: Callable) -> dict:
    def usd6(val):
        return round(float(val), 6) or 0

    def row(key, val):
        kind, name = key
        if kind == "c":
            return {"chain": chain_name.get(name, name), "spot": usd6(val["usd"]), "tx": val["tx"], **({"br": usd6(val["br"])} if val.get("br") else {})}
        return {"chain": (exfee_lab if kind == "x" else wdfee_lab)(name), "spot": usd6(val["usd"]), "tx": val["tx"], "kind": "exfee", "ex": name}
    order = {"c": 0, "x": 1, "w": 2}
    return {day: [row(key, val) for key, val in sorted(rows.items(), key=lambda kv: (order.get(kv[0][0], 9), -kv[1]["usd"]))]
            for day, rows in sorted((gas_by_date or {}).items())}


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
