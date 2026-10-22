from __future__ import annotations

import math
from typing import Callable, Optional

import candles
import pricing

__all__ = ["ALT_EXS", "QVOL_MAX_AGE", "SPREAD_WARN", "held_spread", "pick", "spread_text", "vol_of"]

ALT_EXS = ("binance", "bybit", "okx", "gate", "kucoin")
SPREAD_WARN = 1.5
QVOL_MAX_AGE = 1800


def _pos(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def vol_of(ex: str, sym: str, now: float) -> Optional[float]:
    got_at, vols = pricing.EX_QVOL.get(ex) or (0, {})
    qvol = (vols or {}).get(sym)
    return float(qvol) if now - float(got_at or 0) <= QVOL_MAX_AGE and _pos(qvol) else None


def pick(syms: list, book: Callable, now: float, hooks: tuple, base: dict) -> tuple:
    failed = hooks[2]
    out = dict(base)
    spread = {}
    for s in syms:
        if s not in out or out[s][1].split(" ", 1)[0] not in pricing.GLOBAL_USD_ORDER:
            continue
        rows, whole = [], True
        for ex in ALT_EXS:
            ex_book = book(ex) or {}
            v = ex_book.get(s)
            if not ex_book or (failed and failed(ex)):
                whole = False
                continue
            if not _pos(v):
                continue
            ok, why = pricing.global_ident(s, ex, v, book, ALT_EXS, hooks)
            if ok is not False:
                rows.append((ex, float(v), vol_of(ex, s, now), why))
        if len(rows) < 2:
            continue
        if whole and all(row[2] is not None for row in rows):
            best_ex, best_px, best_qv, best_why = max(rows, key=lambda row: row[2])
            out[s] = (best_px, f"{best_ex} {s}USDT · 24h 거래대금 최대 ${best_qv:,.0f}" + (f" · {best_why}" if best_why else ""))
        low, high = min(row[1] for row in rows), max(row[1] for row in rows)
        if high / low > SPREAD_WARN:
            spread[s] = {"sym": s, "x": round(high / low, 2), "used": out[s][1].split(" ", 1)[0], "px": out[s][0],
                         "rows": [{"ex": row[0], "px": row[1], "qv": row[2]} for row in rows]}
    return out, spread


def held_spread(spread: dict, coins: list, ex_gid: dict, groups: dict, alt: object = None) -> list:
    live = {sym: item for sym, item in spread.items() if alt is None or sym in alt}
    held = {}
    for coin in coins:
        key = str(coin.get("key") or "")
        if not (key.startswith("g") and key[1:].isdigit()) or ex_gid.get(int(key[1:])) != "upbit":
            continue
        sym = (groups.get(int(key[1:])) or {}).get("sym")
        if sym in live:
            held[sym] = held.get(sym, 0.0) + float(coin.get("qty") or 0) * float(coin.get("price") or 0)
    items = sorted((dict(live[sym], usd=round(usd, 2)) for sym, usd in held.items() if usd > 0), key=lambda item: -item["usd"])
    return [dict(item, text=spread_text(item)) for item in items]


def _ko(ex: str) -> str:
    return candles.VENUE_KO.get(ex, ex)


def spread_text(x: dict) -> str:
    parts = " · ".join(f"{_ko(str(row.get('ex')))} ${float(row.get('px') or 0):,.4g}"
                       + (f"(거래대금 ${float(row['qv']):,.0f})" if row.get("qv") else "(거래대금 모름)") for row in (x.get("rows") or []))
    return (f"{x.get('sym')} 거래소 간 {float(x.get('x') or 0):.2f}배: {parts} → 쓴 가격 {_ko(str(x.get('used')))} ${float(x.get('px') or 0):,.4g}"
            f"(보유 ${float(x.get('usd') or 0):,.0f})")
