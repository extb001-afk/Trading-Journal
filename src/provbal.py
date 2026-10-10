from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation

import common
import pricing

FILE = "prov_bal.json"


def load(state_dir: str = None) -> dict:
    try:
        d = common.read_json(os.path.join(state_dir or common.STATE_DIR, FILE), {})
    except (Exception, SystemExit):
        d = {}
    return d if isinstance(d, dict) else {}


def _dec(raw, dec) -> Decimal | None:
    try:
        return Decimal(int(raw)) / (Decimal(10) ** int(dec))
    except (TypeError, ValueError, InvalidOperation):
        return None


def items(prov: dict, *, done_chain, asset_of, ledger, ainfo) -> list:
    out = []
    for chain, ent in sorted((prov or {}).items()):
        if not isinstance(ent, dict) or ent.get("mode") != "chain" or done_chain(chain):
            continue
        try:
            at = int(ent.get("at"))
        except (TypeError, ValueError):
            continue
        try:
            seen_t = int(ent.get("bts") or ent.get("t1") or at)
        except (TypeError, ValueError):
            seen_t = at
        for w, wb in sorted((ent.get("wallets") or {}).items()):
            if not isinstance(wb, dict):
                continue
            loc = f"wallet:{chain}:{w}"
            led_w, amb_w = ledger(loc, ent)
            led_w, amb_w = led_w or {}, set(amb_w or ())
            q = wb.get("q")
            qset = {str(x).lower() for x in q} if isinstance(q, list) else None
            unobs = {str(x).lower() for x in (wb.get("unobs") or ())}
            seen = set()
            rows = []
            if "native" in wb:
                rows.append(("native", None, wb["native"], None, None))
            for ca, v in (wb.get("tok") or {}).items():
                if isinstance(v, list) and len(v) == 3 and str(ca).lower() not in unobs:
                    rows.append(("token", ca, v[0], v[1], v[2]))
            for kind, addr, raw, sym0, dec0 in rows:
                a = asset_of(chain, kind, addr)
                aid, gid, sym, dec = (a if a else (None, None, sym0, dec0))
                if dec is None:
                    dec = dec0 if dec0 is not None else (9 if chain == "sol" and kind == "native" else 18 if kind == "native" else None)
                if dec is None:
                    continue
                b = _dec(raw, dec)
                if b is None:
                    continue
                if aid is not None:
                    seen.add(aid)
                    if aid in amb_w:
                        continue
                led = led_w.get(aid, Decimal(0)) if aid is not None else Decimal(0)
                if led is None:
                    continue
                out.append({"chain": chain, "wallet": w, "loc": loc, "kind": kind, "addr": addr, "aid": aid, "gid": gid,
                            "sym": sym or sym0 or "?", "dec": dec, "bal": b, "led": led, "qty": b - led, "at": at, "seen": seen_t})
            for aid, led in sorted(led_w.items()):
                if aid in seen or aid in amb_w or not led:
                    continue
                inf = ainfo(aid)
                if not inf:
                    continue
                kind, addr, sym, dec, gid = inf
                if kind == "native":
                    if "native" not in wb:
                        continue
                elif kind == "token":
                    a9 = str(addr or "").lower()
                    if not a9 or a9 in unobs or (qset is not None and a9 not in qset):
                        continue
                else:
                    continue
                out.append({"chain": chain, "wallet": w, "loc": loc, "kind": kind, "addr": addr, "aid": aid, "gid": gid,
                            "sym": sym or "?", "dec": dec, "bal": Decimal(0), "led": led, "qty": -led, "at": at, "seen": seen_t})
    return [it for it in out if it["qty"] != 0]


def _unit(it, native_sym=None) -> str | None:
    if it.get("kind") == "native":
        s9 = str((native_sym(it.get("chain")) if native_sym else None) or "").strip()
        if not s9:
            s9 = str(it.get("sym") or "").strip()
        s9 = s9.upper()
        return s9 if s9 and s9 != "?" else None
    ca = str(it.get("addr") or "")
    if it.get("chain") == "sol":
        st = pricing.STABLE_MINTS.get(ca)
    else:
        st = (pricing.STABLE_CAS.get(it.get("chain")) or {}).get(ca.lower())
    return str(st).upper() if st else None


def net_pending(its: list, pend: list, *, chain_of, norm, native_sym=None) -> list:
    ents = []
    for e in pend or ():
        if not isinstance(e, dict) or e.get("state") != "pending" or e.get("cls") != "wallet" or not e.get("addr"):
            continue
        try:
            q = Decimal(str(e.get("qty") or 0))
            st = int(e.get("start") or e.get("ts") or 0)
        except (InvalidOperation, ValueError, TypeError):
            continue
        if not q.is_finite() or q <= 0:
            continue
        ents.append({"left": q, "start": st, "chain": chain_of(e.get("net"), e.get("sym"), e.get("addr")), "w": norm(e["addr"]),
                     "cur": str(e.get("sym") or "").upper() or None, "gid": e.get("gid")})
    if not ents:
        return its
    out = []
    for it in its:
        if it["qty"] > 0:
            wa, u, g = norm(it["wallet"]), _unit(it, native_sym), it.get("gid")
            try:
                seen = int(it.get("seen") or it.get("at") or 0)
            except (TypeError, ValueError):
                seen = 0
            q = it["qty"]
            for en in ents:
                if q <= 0:
                    break
                if en["left"] <= 0 or en["w"] != wa or en["chain"] not in (None, it.get("chain")) or seen < en["start"]:
                    continue
                if not ((u is not None and en["cur"] == u) or (g is not None and en["gid"] == g)):
                    continue
                t = min(en["left"], q)
                q -= t
                en["left"] -= t
            if q != it["qty"]:
                it = dict(it, qty=q, transit=it["qty"] - q)
        if it["qty"] != 0:
            out.append(it)
    return out


def merge(coins: list, stables: list, its: list, *, price_of, labels: dict, chain_names: dict, short, now: float) -> dict:
    by_key = {str(r.get("key")): r for r in list(coins) + list(stables)}
    usd, n, skipped, chains = 0.0, 0, {}, {}
    for it in its:
        q = float(it["qty"])
        if q <= 0:
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
        lab = labels.get(it["wallet"]) or short(it["wallet"])
        wl = lab if str(lab).rstrip().endswith("지갑") else f"{lab} 지갑"
        ch = chain_names.get(it["chain"], it["chain"])
        loc = {"w": wl, "ch": ch, "sub": f"{ch} · {short(it['wallet'])} · 지금 잔고(옛 기록 받는 중)", "qty": q, "pv": 1}
        key = f"pv:{it['chain']}:{it['addr'] or 'native'}"
        row = by_key.get(key)
        if row is None:
            row = {"key": key, "sym": it["sym"], "name": f"{it['sym']} · {ch}", "qty": 0.0, "price": px, "avg": 0, "kqty": 0,
                   "fbQty": 0, "fbCost": 0, "locs": [], "pxSrc": it.get("src") or "prov", "pvQty": 0.0}
            (stables if it.get("stable") else coins).append(row)
            by_key[key] = row
        row["qty"] = float(row.get("qty") or 0) + q
        row["fbQty"] = row["qty"]
        row["pvQty"] = float(row.get("pvQty") or 0) + q
        row.setdefault("locs", []).append(loc)
        usd += u
        n += 1
        c9 = chains.setdefault(it["chain"], {"usd": 0.0, "n": 0})
        c9["usd"] = round(c9["usd"] + u, 2)
        c9["n"] += 1
    return {"usd": round(usd, 2), "n": n, "skipped": skipped, "chains": chains}
