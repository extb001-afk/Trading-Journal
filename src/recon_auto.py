from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import Callable, Optional

import acct_norm
import autofix
import calcguard

__all__ = ["AUTO_WAIT_SEC", "NEG_RUN_DAYS", "SITE_AUTO", "SITE_AUTO_KO", "auto_cells", "info_lines", "is_auto_anchor", "mark", "neg_runs", "venue_gaps", "venue_t0"]

SITE_AUTO = "K11"
SITE_AUTO_KO = "자동 처리 행(창 안 미확인 유출 — 숫자 맞춰 둠)"
AUTO_WAIT_SEC = 72 * 3600
NEG_RUN_DAYS = 7
DAY = 86400


def auto_cells(conn: sqlite3.Connection, rows: list = ()) -> tuple:
    try:
        rec = autofix.read_receipts(conn)
    except sqlite3.Error:
        rec = {}
    off = set()
    try:
        for (key,) in conn.execute("SELECT k FROM meta WHERE k >= ? AND k < ?", (autofix.OFF, autofix.OFF[:-1] + ";")):
            ex, _, sym = str(key)[len(autofix.OFF):].partition(":")
            if ex and sym:
                off.add((ex, sym.upper()))
    except sqlite3.Error:
        pass
    b0s = {}
    for r in rows:
        got = autofix.parse_sid(r.get("sid")) if r.get("site") == SITE_AUTO else None
        if got is not None:
            b0s[(r["venue"], got[0])] = got[1]
    return rec, off, b0s


def _in_vgap(r: dict, vgap: dict) -> bool:
    for g in vgap.get(r["venue"]) or ():
        try:
            if int(g["t0"]) <= int(r["ts"]) < int(g["full_t0"]):
                return True
        except (KeyError, TypeError, ValueError):
            continue
    return False


def is_auto_anchor(r: dict, cells: tuple) -> bool:
    rec, _off, b0s = cells
    key = (r["venue"], r["sym"].upper())
    return (r["site"] == "K7" and b0s.get(key) is not None and r["bts"] == b0s[key]
            and (rec.get(key) or {}).get("state") in autofix.STATES)


def mark(r: dict, cells: tuple, vgap: dict, auto_on: bool, now: float) -> None:
    _rec, off, _b0s = cells
    key = (r["venue"], r["sym"].upper())
    first7 = r["site"] == "K7" and bool(r.get("first"))
    r["auto"] = r["site"] == SITE_AUTO or is_auto_anchor(r, cells)
    r["kept"] = not r["auto"] and first7 and key in off and r["red"] == "prewin_rows"
    r["wait"] = r["r1"] = False
    if r["kept"] and r["red"] == "prewin_rows":
        r["red"] = None
    elif auto_on and r["red"] == "prewin_rows" and first7 and not r["auto"]:
        young = now - float(r["bts"] if r["bts"] is not None else r["made"]) < AUTO_WAIT_SEC
        r["wait"], r["r1"] = young, not young
        if young:
            r["red"] = None
    r["vgap"] = r["site"] == "K7" and _in_vgap(r, vgap)


def venue_gaps(conn: sqlite3.Connection, venues: set, now: float, gap_fn: Optional[Callable] = None) -> dict:
    fn = gap_fn or autofix.venue_gap
    out = {}
    for ex in sorted(venues):
        try:
            got = fn(conn, ex, int(now))
        except Exception as e:  # noqa: BLE001 [fallback]
            calcguard.swallowed("recon_auto:venue_gaps", e)
            got = []
        out[ex] = [g for g in (got or []) if isinstance(g, dict)]
    return out


def venue_t0(rows: list) -> dict:
    out = {}
    for r in rows:
        if r.get("t0"):
            out[r["venue"]] = min(out.get(r["venue"], int(r["t0"])), int(r["t0"]))
    return out


def _cells_series(conn: sqlite3.Connection) -> dict:
    agg = {}
    for loc, sym, ts, qb, dec in conn.execute(
            "SELECT p.location, upper(a.symbol), p.event_ts, p.qty_base, a.decimals FROM postings p JOIN assets a ON a.asset_id = p.asset_id"
            " WHERE p.location >= 'exchange:' AND p.location < 'exchange;'"):
        parts = str(loc).split(":")
        if len(parts) != 2 or str(sym or "") in acct_norm.ex_off_ledger(parts[1]):
            continue
        try:
            q = Decimal(int(qb)).scaleb(-int(dec if dec is not None else 8))
        except (TypeError, ValueError, ArithmeticError):
            continue
        cell = agg.setdefault((parts[1], str(sym or "")), {})
        cell[int(ts)] = cell.get(int(ts), Decimal(0)) + q
    return agg


def _t0_or_none(t0_of: Optional[Callable], ex: str) -> Optional[int]:
    if t0_of is None:
        return None
    try:
        got = t0_of(ex)
    except Exception as e:  # noqa: BLE001 [fallback]
        calcguard.swallowed("recon_auto:_t0_or_none", e)
        return None
    return int(got) if got else None


def neg_runs(conn: sqlite3.Connection, t0s: Optional[dict] = None, min_days: int = NEG_RUN_DAYS, t0_of: Optional[Callable] = None) -> dict:
    t0s = t0s or {}
    tol, lim = Decimal("0.00000001"), int(min_days) * DAY
    cells, runs, longest, venues = 0, 0, 0, {}
    for (ex, _sym), series in _cells_series(conn).items():
        cum, start, n, w0 = Decimal(0), None, 0, t0s.get(ex) if ex in t0s else _t0_or_none(t0_of, ex)
        for ts in sorted(series):
            cum += series[ts]
            if cum < -tol:
                start = ts if start is None else start
            elif start is not None:
                if ts - start > lim and (w0 is None or start >= w0):
                    n += 1
                    longest = max(longest, ts - start)
                start = None
        if n:
            cells, runs = cells + 1, runs + n
            venues[ex] = venues.get(ex, 0) + 1
    return {"cells": cells, "runs": runs, "max_days": round(longest / DAY, 1), "min_days": int(min_days), "venues": dict(sorted(venues.items()))}


def info_lines(doc: dict, fmt_row: Callable[[dict], str]) -> list:
    g = doc.get("gray") if isinstance(doc.get("gray"), dict) else {}
    out = []
    if g.get("auto_n"):
        out.append(f"자동 처리 {int(g['auto_n'])}칸(" + " · ".join(fmt_row(r).split("(")[0] for r in (g.get("auto") or [])[:3]) + " — 숫자 맞춰 둠)")
    if g.get("wait_n"):
        out.append(f"자동 처리 대기 {int(g['wait_n'])}칸(첫 대사 72시간 뒤 자동으로 닫음)")
    if g.get("kept_n"):
        out.append(f"그대로 둔 칸 {int(g['kept_n'])}(자동 처리 끔)")
    if g.get("gap_n"):
        out.append(f"빈 구간 보정 {int(g['gap_n'])}건 ${float(g.get('gap_usd') or 0):,.0f}(기록 종류별 보존 기한 차이)")
    nr = doc.get("neg_runs") if isinstance(doc.get("neg_runs"), dict) else {}
    if nr.get("cells"):
        out.append(f"창 안 음수 구간 {int(nr['cells'])}칸({int(nr.get('min_days') or NEG_RUN_DAYS)}일 넘게 · 가장 긴 {float(nr.get('max_days') or 0):,.0f}일)"
                   " — 끝 잔고는 맞음(기록 순서 문제 · 숫자 무변)")
    return out
