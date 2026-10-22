from __future__ import annotations

import bisect
import json
import logging
from decimal import Decimal

import accounting_util
import calcguard
import logs, paths, seeds

from view_common import STABLE_GROUPS
from view_common import _ex_stable_sym
from view_order import NOPX_LEGS_MAX

log = logging.getLogger('tj-web')


def _leaks(loc: dict, names: tuple) -> dict:
    return {k: loc[k] for k in names if k in loc}


def credited_index(conn):
    credited_txh = set()
    credited_gid = {}
    for r0 in conn.execute(
            "SELECT t.chain_txhash, t.qty_base, a.group_id, a.decimals FROM transfers t"
            " JOIN assets a ON a.asset_id = t.asset_id WHERE t.state='credited'").fetchall():
        if r0["chain_txhash"]:
            credited_txh.add(r0["chain_txhash"])
        gid0 = r0["group_id"]
        if gid0 is not None:
            qn0 = Decimal(int(r0["qty_base"])) / (Decimal(10) ** int(18 if r0["decimals"] is None else r0["decimals"]))
            credited_gid[gid0] = credited_gid.get(gid0, Decimal(0)) + qn0
    return credited_txh, credited_gid, _leaks(locals(), ('r0', 'gid0', 'qn0'))


def bridge_dep_index(rows, gsym):
    bridge_dep_ts = {}
    for r in rows:
        if r["event"] == "BRIDGE" and r["leg_kind"] == "move_out":
            bridge_dep_ts.setdefault(gsym(r), []).append(r["event_ts"])
    return bridge_dep_ts, _leaks(locals(), ('r',))


def pay_index(rows, gsym):
    _PAY_NAT = {"ETH", "WETH", "SOL", "WSOL", "BNB", "WBNB"}

    def _qk(r9):
        s9 = (r9["symbol"] or "").upper()
        if (r9["gname"] or "") in STABLE_GROUPS or (r9["kind"] == "exchange_currency" and _ex_stable_sym(s9)):
            return "st"
        if r9["kind"] == "exchange_currency" and s9 == "KRW":
            return "fiat"
        return "nat" if gsym(r9).upper() in _PAY_NAT else "tok"
    pay_tx = {}
    conv_cp = {}
    tx_legsym = {}
    for r in rows:
        if r["leg_kind"] in ("acq", "disp") and r["event"] in ("SWAP", "EXF_BUY", "EXF_SELL", "EX_BUY", "EX_SELL"):
            qk9 = _qk(r)
            pay_tx.setdefault((r["source_ns"], r["source_id"]), []).append((r["posting_id"], r["leg_kind"], qk9))
            tl9 = tx_legsym.setdefault((r["source_ns"], r["source_id"]), {}).setdefault(r["leg_kind"], [])
            if len(tl9) < 4:
                tl9.append(("원화" if qk9 == "fiat" else gsym(r), qk9))
            if r["leg_kind"] == "acq" and qk9 in ("st", "fiat"):
                cp9 = conv_cp.setdefault((r["source_ns"], r["source_id"]), [])
                s9 = "원화" if qk9 == "fiat" else gsym(r)
                if s9 not in cp9:
                    cp9.append(s9)
    pay_pid = set()
    for legs9 in pay_tx.values():
        acq9 = {c9 for _p9, lk9, c9 in legs9 if lk9 == "acq"}
        tokd9 = any(lk9 == "disp" and c9 == "tok" for _p9, lk9, c9 in legs9)
        for p9, lk9, c9 in legs9:
            if lk9 == "disp" and ((c9 == "st" and acq9 & {"tok", "nat"}) or (c9 == "nat" and ("tok" in acq9 or tokd9))):
                pay_pid.add(p9)
    pay_tx = None
    return conv_cp, tx_legsym, pay_pid, _leaks(locals(), ('r', 'cp9', 's9', 'legs9', 'acq9', 'p9', 'lk9', 'c9'))


def swap_index(rows, gsym, norm, fx_uid_tx, pay_pid):
    tx_group = {}
    swap_gas = {}
    swap_recv = {}
    swap_pay = {}
    swap_wd_pre = {}
    for r in rows:
        if r["event"] == "EX_WITHDRAW" and r["leg_kind"] == "move_out":
            t9w = fx_uid_tx.get(r["source_id"]) or ""
            if t9w.startswith("swap_"):
                swap_wd_pre[t9w] = {"sym": gsym(r), "gid": r["group_id"] or -r["asset_id"]}
        if r["leg_kind"] == "disp" and r["event"] == "SWAP":
            swap_pay.setdefault((r["source_ns"], r["source_id"]), []).append((gsym(r), -norm(r)))
        if r["leg_kind"] in ("acq", "disp") and r["event"] == "SWAP":
            key = (r["source_ns"], r["source_id"])
            gid_r = r["group_id"] or -r["asset_id"]
            st_r = (r["gname"] or "") in STABLE_GROUPS
            prev = tx_group.get(key)
            pl_r = st_r or r["posting_id"] in pay_pid
            if prev is None or (prev[1] and not pl_r):
                tx_group[key] = (gid_r, pl_r)
            sg9 = swap_gas.setdefault(key, {"usd": Decimal(0), "sell": None, "buy": None, "done": False})
            if not st_r and r["kind"] != "exchange_currency":
                if r["leg_kind"] == "disp" and sg9["sell"] is None and r["posting_id"] not in pay_pid:
                    sg9["sell"] = gid_r
                elif r["leg_kind"] == "acq" and sg9["buy"] is None:
                    sg9["buy"] = gid_r
            if r["leg_kind"] == "acq":
                swap_recv.setdefault(key, []).append((gid_r, r["kind"], r["chain"], r["address"], st_r))
        if r["leg_kind"] == "gas" and r["event"] == "SWAP" and r["cost_usd"] is not None:
            sg9 = swap_gas.setdefault((r["source_ns"], r["source_id"]), {"usd": Decimal(0), "sell": None, "buy": None, "done": False})
            sg9["usd"] += Decimal(r["cost_usd"])
    return tx_group, swap_gas, swap_recv, swap_pay, swap_wd_pre, _leaks(locals(), ('key', 'r', 'sg9'))


def arr_index(rows):
    arr_groups = {}
    arr_tx_chain = {}
    for r in rows:
        if r["leg_kind"] == "acq" and r["event"] in ("TRANSFER_IN", "PROGRAM_IN"):
            arr_groups.setdefault((r["source_ns"], r["source_id"]), set()).add(r["group_id"] or -r["asset_id"])
            arr_tx_chain.setdefault(r["source_id"], r["chain"] or r["source_ns"])
    return arr_groups, arr_tx_chain, _leaks(locals(), ('r',))


def lp_index(conn):
    lp_by_tx = {}
    for r9 in conn.execute("SELECT chain, txhash, detail FROM tx_class WHERE event LIKE 'LP\\_%' ESCAPE '\\'").fetchall():
        try:
            d9 = (json.loads(r9["detail"] or "{}") or {}).get("lp") or {}
        except (json.JSONDecodeError, TypeError, AttributeError):
            d9 = {}
        if d9:
            lp_by_tx[(r9["chain"], r9["txhash"])] = d9
    lp_meta_by = {}
    for (ch9, _h9), d9 in lp_by_tx.items():
        if d9.get("mgr"):
            m9 = lp_meta_by.setdefault((ch9, str(d9["mgr"])), {"proto": d9.get("proto"), "name": d9.get("name")})
            if d9.get("lpSym") and not m9.get("lpSym"):
                m9["lpSym"] = d9["lpSym"]
            for t9, g9 in (d9.get("stake") or {}).items():
                m9.setdefault("stake", {})[str(t9)] = g9
                if d9.get("who"):
                    m9.setdefault("who", {})[str(t9)] = d9["who"]
            for t9, mm9 in (d9.get("mints") or {}).items():
                m9.setdefault("mints", {})[str(t9)] = mm9
            for t9 in (d9.get("unstake") or {}):
                (m9.get("stake") or {}).pop(str(t9), None)
    return lp_by_tx, lp_meta_by, _leaks(locals(), ('ch9', 'd9', 'g9', 'm9', 'mm9', 'r9', 't9'))


def lp_rows_index(rows):
    lp_tx_rows = {}
    for r0 in rows:
        if str(r0["event"] or "").startswith("LP_") and r0["leg_kind"] in ("disp", "acq"):
            lp_tx_rows.setdefault((r0["source_ns"], r0["source_id"]), []).append(r0)
    return lp_tx_rows, _leaks(locals(), ('r0',))


def nopx_index(rows, gsym, norm, fxb):
    nopx_swap = {}
    nopx_bad = set()
    nopx_legs = {}
    for r in rows:
        if r["leg_kind"] not in ("acq", "disp"):
            continue
        key9 = (r["source_ns"], r["source_id"])
        if r["event"] not in ("SWAP", "UNKNOWN") or r["cost_usd"] is not None:
            nopx_bad.add(key9)
            continue
        nopx_legs.setdefault(key9, []).append(r)
    try:
        zv9 = {str(x).strip().lower() for x in ((seeds.seed_json("zero_value_companions.json", {}, base_dir=paths.BASE_DIR) or {}).get("tokens") or [])
               if isinstance(x, str)}
    except (Exception, SystemExit) as e9:   # noqa: BLE001 [fallback]
        calcguard.swallowed("view_b_replay:ReplayMixin._build_replay[zv9]", e9)
        log.warning("동반 토큰 목록(zero_value_companions.json) 읽기 실패 — 이번 빌드 규칙 없음: %s", logs.safe_err(e9)[:160])
        zv9 = set()

    def zv_leg(r9):
        return bool(zv9) and f"{r9['chain'] or ''}:{str(r9['address'] or '').lower()}" in zv9

    nopx_px_ok = accounting_util.nopx_px_ok

    for key9, legs9 in nopx_legs.items():
        if key9 in nopx_bad:
            continue
        dg9 = {r9["group_id"] or -r9["asset_id"] for r9 in legs9 if r9["leg_kind"] == "disp"}
        ag9 = {r9["group_id"] or -r9["asset_id"] for r9 in legs9 if r9["leg_kind"] == "acq"}
        if (len(dg9) == 1 and len(ag9) == 1) or (dg9 and ag9 and dg9.isdisjoint(ag9) and len(dg9) + len(ag9) <= NOPX_LEGS_MAX):
            a9 = [r9 for r9 in legs9 if r9["leg_kind"] == "acq"]
            gq9, gs9, gst9, gz9, gpx9 = {}, {}, {}, {}, {}
            for r9 in a9:
                k9 = r9["group_id"] or -r9["asset_id"]
                gq9[k9] = gq9.get(k9, Decimal(0)) + norm(r9)
                gs9.setdefault(k9, gsym(r9))
                gst9.setdefault(k9, (r9["gname"] or "") in STABLE_GROUPS)
                gz9[k9] = gz9.get(k9, True) and zv_leg(r9)
                gpx9[k9] = gpx9.get(k9, True) and nopx_px_ok(r9)
            zc9 = {k9 for k9, z9 in gz9.items() if z9}
            if len(zc9) == len(gq9):
                zc9 = set()
            gqa9, gq9 = gq9, {k9: q9 for k9, q9 in gq9.items() if k9 not in zc9}
            est9, fx9 = False, None
            if len(gq9) == 1:
                w9 = {k9: Decimal(1) for k9 in gq9}
            else:
                v9 = {}
                for k9, q9 in gq9.items():
                    p9 = Decimal(1) if gst9[k9] else (fxb.candle(gs9[k9], int(a9[0]["event_ts"])) if q9 > 0 and gpx9[k9] else None)
                    if p9 and p9 > 0 and q9 > 0:
                        v9[k9] = q9 * Decimal(str(p9))
                if len(v9) == len(gq9):
                    w9 = {k9: v9[k9] / sum(v9.values()) for k9 in gq9}
                else:
                    n9u = len(gq9) - len(v9)
                    w9 = {k9: (Decimal(0) if k9 in v9 else Decimal(1) / n9u) for k9 in gq9}
                    fx9 = v9 or None
                    est9 = n9u > 1
            w9.update({k9: Decimal(0) for k9 in zc9})
            nopx_swap[key9] = {"acq": next(iter(ag9)), "aq": sum(gqa9.values(), Decimal(0)), "asym": " + ".join(gs9[k9] for k9 in gqa9),
                               "gw": {k9: (w9[k9], gqa9[k9]) for k9 in gqa9}, "est": est9, "fx": fx9, "z": zc9 or None}
    nopx_legs = nopx_bad = None
    return nopx_swap, zv_leg, nopx_px_ok, _leaks(locals(), ('a9', 'ag9', 'est9', 'fx9', 'gpx9', 'gq9', 'gs9', 'gz9', 'k9', 'key9', 'legs9', 'p9', 'q9', 'r', 'r9', 'v9', 'w9', 'zc9'))


def swap_fill_index(rows, gsym, norm, fxb, zv_leg, nopx_px_ok, swap_gas, pay_pid, tx_group):
    swap_fill, swap_fill_est, swap_fill_zero = {}, set(), set()
    sw9 = {}
    if rows:
        K9s = (lambda c9: c9) if isinstance(rows[0], dict) else list(rows[0].keys()).index
        iE9s, iL9s, iC9s = K9s("event"), K9s("leg_kind"), K9s("cost_usd")
        hn9 = set()
        for r in rows:
            if r[iE9s] == "SWAP" and (r[iL9s] == "acq" or r[iL9s] == "disp"):
                k9 = (r["source_ns"], r["source_id"])
                sw9.setdefault(k9, []).append(r)
                if r[iC9s] is None:
                    hn9.add(k9)
        sw9 = {k9: sw9[k9] for k9 in hn9}
    for key9, legs9 in sw9.items():
        for side9 in ("acq", "disp"):
            o9 = [r9 for r9 in legs9 if r9["leg_kind"] != side9]
            s9 = [r9 for r9 in legs9 if r9["leg_kind"] == side9]
            n9 = [r9 for r9 in s9 if r9["cost_usd"] is None]
            if not o9 or len(n9) < 2 or any(r9["cost_usd"] is None for r9 in o9):
                continue
            og9 = {r9["group_id"] or -r9["asset_id"] for r9 in o9}
            sg9 = {r9["group_id"] or -r9["asset_id"] for r9 in s9}
            if not og9.isdisjoint(sg9) or len(og9) + len(sg9) > NOPX_LEGS_MAX:
                continue
            R9 = (sum((Decimal(r9["cost_usd"]) for r9 in o9), Decimal(0))
                  - sum((Decimal(r9["cost_usd"]) for r9 in s9 if r9["cost_usd"] is not None), Decimal(0)))
            if R9 <= 0:
                continue
            gq9, v9, gz9, gpx9 = {}, {}, {}, {}
            for r9 in n9:
                k9 = r9["group_id"] or -r9["asset_id"]
                gq9[k9] = gq9.get(k9, Decimal(0)) + abs(norm(r9))
                gz9[k9] = gz9.get(k9, True) and zv_leg(r9)
                gpx9[k9] = gpx9.get(k9, True) and nopx_px_ok(r9)
            zc9 = {k9 for k9, z9 in gz9.items() if z9}
            if len(zc9) == len(gq9):
                continue
            gqa9, gq9 = gq9, {k9: q9 for k9, q9 in gq9.items() if k9 not in zc9}
            for k9, q9 in gq9.items():
                r0 = next(r9 for r9 in n9 if (r9["group_id"] or -r9["asset_id"]) == k9)
                p9 = Decimal(1) if (r0["gname"] or "") in STABLE_GROUPS else (fxb.candle(gsym(r0), int(r0["event_ts"])) if gpx9[k9] else None)
                if p9 and p9 > 0 and q9 > 0:
                    v9[k9] = q9 * Decimal(str(p9))
            sv9, nu9 = sum(v9.values(), Decimal(0)), len(gq9) - len(v9)
            if not nu9 or sv9 >= R9:
                al9 = {k9: (R9 * v9[k9] / sv9 if k9 in v9 and sv9 > 0 else Decimal(0)) for k9 in gq9}
            else:
                al9 = {k9: (v9[k9] if k9 in v9 else (R9 - sv9) / nu9) for k9 in gq9}
            for r9 in n9:
                k9 = r9["group_id"] or -r9["asset_id"]
                if k9 in zc9:
                    swap_fill[r9["posting_id"]] = Decimal(0)
                    swap_fill_zero.add(r9["posting_id"])
                elif gq9[k9] > 0:
                    swap_fill[r9["posting_id"]] = al9[k9] * abs(norm(r9)) / gq9[k9]
                    if nu9 > 1:
                        swap_fill_est.add(r9["posting_id"])
            break
    if swap_fill_zero:
        for key9, legs9 in sw9.items():
            zg9 = {r9["group_id"] or -r9["asset_id"] for r9 in legs9 if r9["posting_id"] in swap_fill_zero}
            sg9 = swap_gas.get(key9)
            if not zg9 or not sg9:
                continue
            for side9, lk9 in (("buy", "acq"), ("sell", "disp")):
                if sg9[side9] in zg9:
                    b9 = next((r9 for r9 in legs9 if r9["leg_kind"] == lk9 and (r9["group_id"] or -r9["asset_id"]) not in zg9
                               and (r9["gname"] or "") not in STABLE_GROUPS and r9["kind"] != "exchange_currency"
                               and (lk9 == "acq" or r9["posting_id"] not in pay_pid)), None)
                    sg9[side9] = (b9["group_id"] or -b9["asset_id"]) if b9 is not None else None
            tg9 = tx_group.get(key9)
            if tg9 is not None and tg9[0] in zg9 and (sg9["sell"] or sg9["buy"]) is not None:
                tx_group[key9] = (sg9["sell"] or sg9["buy"], False)
    sw9 = None
    return swap_fill, swap_fill_est, swap_fill_zero, sw9, _leaks(locals(), ('b9', 'k9', 'key9', 'legs9', 'lk9', 'n9', 'o9', 'og9', 'p9', 'q9', 'r', 'r0', 'r9', 's9', 'sg9', 'sv9', 'v9', 'zg9'))


def bridge_rcpt_index(rows, gsym, norm, zv_leg, nopx_swap):
    br_legs9 = {}
    if rows:
        K9r = (lambda c9: c9) if isinstance(rows[0], dict) else list(rows[0].keys()).index
        iE9r, iL9r = K9r("event"), K9r("leg_kind")
        for k9, r in enumerate(rows):
            if r[iE9r] == "BRIDGE" and (r[iL9r] == "move_out" or r[iL9r] == "move_in"):
                br_legs9.setdefault((r["source_ns"], r["source_id"]), []).append(k9)
    for key9, ks9 in br_legs9.items():
        legs9 = [rows[k9] for k9 in ks9]
        o9 = [r9 for r9 in legs9 if r9["leg_kind"] == "move_out"]
        i9 = [r9 for r9 in legs9 if r9["leg_kind"] == "move_in"]
        if (not o9 or not i9 or not all(str(r9["location"] or "").startswith("wallet:") for r9 in legs9)
                or any(int(r9["qty_base"]) >= 0 for r9 in o9) or any(int(r9["qty_base"]) <= 0 or r9["cost_usd"] is not None for r9 in i9)):
            continue
        og9 = {r9["group_id"] or -r9["asset_id"] for r9 in o9}
        zi9 = [r9 for r9 in i9 if zv_leg(r9)]
        i9 = [r9 for r9 in i9 if not (r9["kind"] == "native" or (r9["gname"] or "") in STABLE_GROUPS or zv_leg(r9))] or i9
        ig9 = {r9["group_id"] or -r9["asset_id"] for r9 in i9}
        if (len(og9) != 1 or len(ig9) != 1 or og9 == ig9 or i9[0]["kind"] == "native" or (i9[0]["gname"] or "") in STABLE_GROUPS):
            continue
        zg9 = {}
        for r9 in zi9:
            if not any(r9 is x9 for x9 in i9):
                zg9[r9["group_id"] or -r9["asset_id"]] = zg9.get(r9["group_id"] or -r9["asset_id"], Decimal(0)) + norm(r9)
        zg9 = {k9: v9 for k9, v9 in zg9.items() if k9 not in ig9 and k9 not in og9}
        nopx_swap[key9] = {"acq": next(iter(ig9)), "aq": sum((norm(r9) for r9 in i9), Decimal(0)), "asym": gsym(i9[0]),
                           "gw": {next(iter(ig9)): (Decimal(1), sum((norm(r9) for r9 in i9), Decimal(0))), **{k9: (Decimal(0), v9) for k9, v9 in zg9.items()}},
                           "est": False, "rcpt": True, "z": set(zg9) or None}
        if max(k9 for k9 in ks9 if rows[k9]["leg_kind"] == "move_out") > min(k9 for k9 in ks9 if rows[k9]["leg_kind"] == "move_in"):
            lo9 = min(ks9)
            while lo9 > 0 and (rows[lo9 - 1]["source_ns"], rows[lo9 - 1]["source_id"]) == key9:
                lo9 -= 1
            hi9 = lo9
            while hi9 < len(rows) and (rows[hi9]["source_ns"], rows[hi9]["source_id"]) == key9:
                hi9 += 1
            if all(lo9 <= k9 < hi9 for k9 in ks9):
                rows[lo9:hi9] = sorted(rows[lo9:hi9], key=lambda r9: {"move_out": 0, "move_in": 1}.get(r9["leg_kind"], 2))
    br_legs9 = None
    return br_legs9, _leaks(locals(), ('i9', 'k9', 'key9', 'ks9', 'legs9', 'lo9', 'o9', 'og9', 'r', 'r9'))


def roundtrip_index(rows, norm):
    rt_pair = {}
    rt_transit = {}
    _ro, _ri = {}, {}
    for r0 in rows:
        loc0 = r0["location"] or ""
        if r0["event"] == "TRANSFER_OUT" and r0["leg_kind"] == "move_out" and loc0.startswith("wallet:"):
            o0 = _ro.setdefault((r0["source_ns"], r0["source_id"]), {"ts": int(r0["event_ts"]), "loc": set(), "a": {}})
            o0["loc"].add(loc0); o0["a"][r0["asset_id"]] = o0["a"].get(r0["asset_id"], Decimal(0)) - norm(r0)
        elif r0["event"] == "PROGRAM_IN" and r0["leg_kind"] == "acq":
            i0 = _ri.setdefault((r0["source_ns"], r0["source_id"]), {"ts": int(r0["event_ts"]), "loc": set(), "a": {}, "priced": False})
            i0["loc"].add(loc0); i0["a"][r0["asset_id"]] = i0["a"].get(r0["asset_id"], Decimal(0)) + norm(r0)
            i0["priced"] = i0["priced"] or r0["cost_usd"] is not None
    _rc_o, _rc_i = {}, {}
    _ri_l = sorted(_ri.items(), key=lambda kv: kv[1]["ts"])
    _ri_ts = [kv[1]["ts"] for kv in _ri_l]
    for ko, o0 in _ro.items():
        if len(o0["loc"]) != 1:
            continue
        for j0 in range(bisect.bisect_left(_ri_ts, o0["ts"]), bisect.bisect_right(_ri_ts, o0["ts"] + 6 * 3600)):
            ki, i0 = _ri_l[j0]
            if ki[0] != ko[0]:
                continue
            if i0["priced"] or i0["loc"] != o0["loc"] or not i0["a"] or set(i0["a"]) - set(o0["a"]):
                continue
            if all(o0["a"][a0] > 0 and o0["a"][a0] * Decimal("0.995") <= q0 <= o0["a"][a0] * Decimal("1.005") for a0, q0 in i0["a"].items()):
                _rc_o.setdefault(ko, []).append(ki); _rc_i.setdefault(ki, []).append(ko)
    rt_back = {}
    for ko, kis in _rc_o.items():
        if len(kis) == 1 and len(_rc_i.get(kis[0], ())) == 1:
            rt_pair[kis[0]] = ko
            rt_back[ko] = (set(_ri[kis[0]]["a"]), set(_ri[kis[0]]["a"]) == set(_ro[ko]["a"]))
    rt_out = set(rt_pair.values())
    return rt_pair, rt_transit, rt_back, rt_out, _leaks(locals(), ('_ro', 'loc0', 'r0'))
