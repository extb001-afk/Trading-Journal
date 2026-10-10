from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

ZERO = Decimal(0)


def _dec(v, dflt=None):
    if v is None or v == "" or isinstance(v, bool):
        return dflt
    try:
        d = Decimal(str(v).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    return d if d.is_finite() else None


def order_fill(o) -> dict | None:
    if not isinstance(o, dict) or not o.get("uuid"):
        return None
    market = str(o.get("market") or "")
    if "-" not in market:
        return None
    quote, base = (s.strip().upper() for s in market.split("-", 1))
    side = str(o.get("side") or "").lower()
    if not quote or not base or side not in ("bid", "ask"):
        return None
    vol = _dec(o.get("executed_volume"), ZERO)
    fee = _dec(o.get("paid_fee"), ZERO)
    funds = _dec(o.get("executed_funds"))
    if funds is None and o.get("executed_funds") in (None, ""):
        px = _dec(o.get("price"))
        funds = (px * vol) if (px is not None and vol is not None) else (ZERO if vol == ZERO else None)
    if vol is None or fee is None or funds is None or vol < 0 or fee < 0 or funds < 0:
        return None
    return {"uuid": str(o["uuid"]), "quote": quote, "base": base, "side": side, "vol": vol, "funds": funds, "fee": fee}


def booked(conn, uuids, ts_of=None) -> dict:
    out = {}
    us = sorted({str(u) for u in uuids if u})
    for i in range(0, len(us), 400):
        part = us[i:i + 400]
        rows = conn.execute("SELECT uuid, revision, payload FROM raw_ex WHERE exchange='upbit' AND kind='order' AND uuid IN (%s)"
                            " ORDER BY uuid, revision" % ",".join("?" * len(part)), part).fetchall()
        for r in rows:
            try:
                pl = json.loads(r[2])
                f = order_fill(dict(pl, uuid=r[0]))
            except (json.JSONDecodeError, TypeError, ValueError):
                f = None
            if f is not None and ts_of is not None:
                try:
                    f["ts"] = ts_of(pl)
                except Exception:
                    f["ts"] = None
            out[str(r[0])] = f if f is not None else False
    return out


def deltas(open_orders, booked_map, snap_ts=None) -> dict | None:
    if not isinstance(open_orders, list):
        return None
    out = {}
    krw = {}

    def add(sym, dq, cost_ccy=None, cost=None):
        if sym == "KRW" or dq == 0:
            return
        e = out.setdefault(sym, {"dq": ZERO, "k": ZERO, "c": {}, "n": 0})
        e["dq"] += dq
        e["n"] += 1
        if dq > 0 and cost_ccy is not None and cost is not None and cost >= 0:
            e["k"] += dq
            e["c"][cost_ccy] = e["c"].get(cost_ccy, ZERO) + cost

    for o in open_orders:
        f = order_fill(o)
        if f is None:
            return None
        b = booked_map.get(f["uuid"]) if booked_map else None
        if b is False:
            continue
        if b is None:
            b = {"vol": ZERO, "funds": ZERO, "fee": ZERO, "side": f["side"], "quote": f["quote"], "base": f["base"]}
        elif (b["side"], b["quote"], b["base"]) != (f["side"], f["quote"], f["base"]):
            continue
        dv = f["vol"] - b["vol"]
        if f["quote"] == "KRW":
            kl = (f["funds"] - f["fee"]) if f["side"] == "ask" else -(f["funds"] + f["fee"])
            bt = b.get("ts")
            if b.get("uuid") and bt is not None and snap_ts is not None and int(bt) <= int(snap_ts):
                kl -= (b["funds"] - b["fee"]) if b["side"] == "ask" else -(b["funds"] + b["fee"])
            krw[f["base"]] = krw.get(f["base"], ZERO) + kl
        if f["side"] == "bid":
            dqt = -((f["funds"] + f["fee"]) - (b["funds"] + b["fee"]))
            add(f["base"], dv, f["quote"], (f["funds"] + f["fee"]) - (b["funds"] + b["fee"]))
            add(f["quote"], dqt)
        else:
            dqt = (f["funds"] - f["fee"]) - (b["funds"] - b["fee"])
            add(f["base"], -dv)
            add(f["quote"], dqt, f["quote"], dqt)
    for sym, e in out.items():
        e["krw"] = krw.get(sym, ZERO)
    for e in out.values():
        if e["k"] > e["dq"]:
            r = (e["dq"] / e["k"]) if (e["k"] > 0 and e["dq"] > 0) else ZERO
            e["k"] = max(e["dq"], ZERO)
            e["c"] = {c: v * r for c, v in e["c"].items()}
    return out


def snapshot_deltas(conn, snap, ts_of=None) -> tuple:
    if not isinstance(snap, dict):
        return None, "no_snap"
    oo = snap.get("open_orders")
    if not isinstance(oo, list):
        return None, "no_open_orders"
    if not oo:
        return {}, "ok"
    uu = []
    for o in oo:
        if not isinstance(o, dict) or not o.get("uuid"):
            return None, "bad_order"
        uu.append(str(o["uuid"]))
    d = deltas(oo, booked(conn, uu, ts_of), snap.get("ts"))
    return (d, "ok") if d is not None else (None, "bad_order")
