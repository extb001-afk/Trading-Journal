from __future__ import annotations

from decimal import Decimal

import acct_norm
import num_parse

SKIP_SYMS = ("KRW", "USD")


def _num(v) -> Decimal | None:
    return num_parse.to_dec(v)


def actual_of(snap: dict, ex: str = "") -> dict:
    skip_syms = acct_norm.ex_off_ledger(ex) if ex else SKIP_SYMS
    out = {}
    bal = snap.get("balances") if isinstance(snap, dict) else None
    if not isinstance(bal, dict):
        return out
    for k, v in bal.items():
        s = str(k).upper()
        d = _num(v)
        if s in skip_syms or d is None:
            continue
        out[s] = out.get(s, Decimal(0)) + d
    debts = snap.get("debts") if isinstance(snap.get("debts"), dict) else {}
    for k, v in debts.items():
        s = str(k).upper()
        d = _num(v)
        if s in skip_syms or d is None or d >= 0:
            continue
        out[s] = out.get(s, Decimal(0)) + d
    return out


def items(exb: dict, *, done, ledger) -> list:
    out = []
    for ex, (path, snap) in sorted((exb or {}).items()):
        if done(ex) or not isinstance(snap, dict):
            continue
        try:
            bts = int(float(snap.get("ts") or 0))
        except (TypeError, ValueError):
            continue
        if bts <= 0:
            continue
        act = actual_of(snap, ex)
        lr = ledger(ex, bts)
        led, amb = lr[0] or {}, set(lr[1] or ())
        tot = (lr[2] or {}) if len(lr) > 2 else {}
        loc = f"exchange:{ex}"
        for sym in sorted(set(act) | set(led)):
            if sym in amb or sym in acct_norm.ex_off_ledger(ex):
                continue
            per = led.get(sym) or {}
            if any(v is None for v in per.values()):
                continue
            lq = sum(per.values(), Decimal(0))
            q = act.get(sym, Decimal(0)) - lq
            if q == 0:
                continue
            gid = max(per, key=lambda g: (abs(per[g]), g)) if per else None
            out.append({"ex": ex, "loc": loc, "sym": sym, "gid": gid, "bal": act.get(sym, Decimal(0)), "led": lq, "qty": q,
                        "seen": bts, "path": path, "gids": sorted(per, key=str), "now": tot.get(sym, lq)})
    return out


def blocked(lr) -> frozenset:
    led, amb = (lr[0] or {}), set(lr[1] or ())
    return frozenset(amb | {s for s, per in led.items() if any(v is None for v in (per or {}).values())})


def merge(coins: list, stables: list, its: list, *, price_of, names: dict) -> dict:
    by_key = {str(r.get("key")): r for r in list(coins) + list(stables)}
    usd, n, skipped, chains = 0.0, 0, {}, {}
    for it in its:
        q = float(it["qty"])
        if q == 0:
            continue
        px, why = price_of(it)
        if why:
            skipped[why] = skipped.get(why, 0) + 1
            continue
        px = float(px or 0)
        if px <= 0:
            skipped["시세 없음"] = skipped.get("시세 없음", 0) + 1
            continue
        u = q * px
        nm = names.get(it["ex"], it["ex"])
        loc = {"w": nm, "sub": "거래소 지금 잔고(옛 기록 받는 중)" if q > 0 else "빌린 몫 · 잔고를 넘은 차입(총자산에서 차감 · 옛 기록 받는 중)", "qty": q, "pv": 1}
        key = f"pvx:{it['ex']}:{it['sym']}"
        row = by_key.get(key)
        if row is None:
            row = {"key": key, "sym": it["sym"], "name": f"{it['sym']} · {nm}", "qty": 0.0, "price": px, "avg": 0, "kqty": 0,
                   "fbQty": 0, "fbCost": 0, "locs": [], "pxSrc": it.get("src") or "prov", "pvQty": 0.0}
            (stables if it.get("stable") else coins).append(row)
            by_key[key] = row
        row["qty"] = float(row.get("qty") or 0) + q
        row["fbQty"] = max(row["qty"], 0.0)
        row["pvQty"] = float(row.get("pvQty") or 0) + q
        row.setdefault("locs", []).append(loc)
        usd += u
        n += 1
        c9 = chains.setdefault(it["loc"], {"usd": 0.0, "n": 0})
        c9["usd"] = round(c9["usd"] + u, 2)
        c9["n"] += 1
    return {"usd": round(usd, 2), "n": n, "skipped": skipped, "chains": chains}


def covered(e: dict, *, chain_seen: dict, ex_seen: dict, chain_of, norm, ex_block=None) -> bool:
    try:
        st = int(e.get("start") or e.get("ts") or 0)
    except (TypeError, ValueError):
        return False
    if st <= 0:
        return False
    dex = e.get("dex")
    if dex:
        if str(e.get("sym") or "").upper() in ((ex_block or {}).get(dex) or ()):
            return False
        t = ex_seen.get(dex)
        return t is not None and int(t) >= st
    a = str(e.get("addr") or "").strip()
    if not a or not (e.get("cls") == "wallet" or e.get("verdict") == "own"):
        return False
    w = norm(a)
    ch = chain_of(e.get("net"), e.get("sym"), w)
    sym = str(e.get("sym") or "").upper()
    for (c, w2), v in chain_seen.items():
        t, units = v if isinstance(v, tuple) else (v, None)
        if w2 == w and (ch is None or c == ch) and int(t) >= st and (units is None or sym in units):
            return True
    return False
