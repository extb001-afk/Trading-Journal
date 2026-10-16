from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import buychart
from view_common import CHAIN_NAME
from view_common import EPS
from view_common import KST
from view_common import SUB_SID_RE


class CostPools:

    def __init__(cpx, G, kst_fmt, _ak, krw_mix, consume_krw, krw_last, oa_last, oa_take, CP_EMIT_MAX, cp_last, cp_ev, cp_pool):
        cpx.G = G
        cpx.kst_fmt = kst_fmt
        cpx._ak = _ak
        cpx.krw_mix = krw_mix
        cpx.consume_krw = consume_krw
        cpx.krw_last = krw_last
        cpx.oa_last = oa_last
        cpx.oa_take = oa_take
        cpx.CP_EMIT_MAX = CP_EMIT_MAX
        cpx.cp_last = cp_last
        cpx.cp_ev = cp_ev
        cpx.cp_pool = cp_pool

    def cp_add(cpx, g, key, q9, c9):
        p9 = cpx.cp_pool(g)
        if p9 is not None:
            p9.add(key, q9, c9)

    def cp_add_map(cpx, g, mp9, s9):
        p9 = cpx.cp_pool(g) if mp9 else None
        if p9 is not None:
            p9.add_map(mp9, s9)

    def cp_sync(cpx, g, key=None):
        p9 = cpx.cp_pool(g)
        if p9 is not None:
            p9.sync(g["qty_known"], g["cost"], key if key is not None else ("u", g["gid"]))

    def cp_take(cpx, g, take9, cost9, want=True):
        p9 = cpx.cp_pool(g)
        if p9 is None or float(take9) <= 0:
            return None
        cpx.cp_sync(g)
        return p9.take(g["qty_known"], take9, cost9, ("m", g["gid"]), cpx.CP_EMIT_MAX, want=want)

    def cp_emit(cpx, mp9, unk9, q9, c9):
        if mp9 is None and not unk9:
            return None
        return {"o": [(cpx.cp_ev.get(k9), k9, v9[0], v9[1]) for k9, v9 in (mp9 or {}).items()], "unk": float(unk9 or 0), "q": float(q9), "c": float(c9)}

    def cp_xc(cpx, g, r9, xc9, cov9, inh9, ch9, ts9):
        p9 = cpx.cp_pool(g)
        if p9 is None or cov9 <= 0:
            return
        lv9 = buychart.xc_leaves(xc9.get("lots"))
        kq9, kc9 = sum(x9["known"] for x9 in lv9), sum(x9["cost"] for x9 in lv9)
        if not lv9 or kq9 <= 0:
            return
        fq9 = float(cov9) / kq9
        for i9, x9 in enumerate(lv9):
            q9 = x9["known"] * fq9
            c9 = (x9["cost"] * float(inh9) / kc9) if kc9 > 0 else float(inh9) * x9["known"] / kq9
            cc9 = str(x9.get("chain") or ch9 or "")
            tk9 = r9["address"] if cc9 == ch9 else None
            if tk9 is None and x9.get("btx"):
                bt9 = cpx.xc_tok9.get(str(x9["btx"]).lower())
                tk9 = bt9[1] if bt9 and bt9[0] == cc9 else None
            tsx9 = buychart.xc_lot_ts(cpx.xc_stx9, cpx.xc_blk9, cc9, x9["tx"], x9.get("block"))
            buy9 = x9["kind"] == "swap"
            info9 = {"chain": cc9, "chainKo": CHAIN_NAME.get(cc9, cc9), "tx": x9["tx"], "block": x9.get("block"), "token": tk9,
                     "arrPid": r9["posting_id"], "arrTs": int(ts9), "via": xc9.get("via") or "", "lot": x9.get("lot"), "depth": x9.get("depth"),
                     "cut": x9.get("cut")}
            if not buy9:
                info9["rule"] = buychart.in_rule("경유") if x9.get("lot") == "hop" else "경유 역추적 원가 · 더 앞 원천을 못 찾음(그 로트 원가 그대로)"
            rec9 = {"t": datetime.fromtimestamp(tsx9 or ts9, KST).strftime("%m-%d %H:%M"),
                    "k": "온체인 매수" if buy9 else "전송",
                    "d": (f"{CHAIN_NAME.get(cc9, cc9)} · 스왑 매수 · {xc9.get('label') or '경유 역추적'} (원장 밖 · 경유 역추적)" if buy9
                          else f"{xc9.get('label') or '경유 역추적'} · 원가 이관"),
                    "q": f"{q9:.10f}", "a": f"${c9:,.2f}", "tx": "—", "src": None, "_ts": tsx9 if buy9 else int(ts9), "_pid": None,
                    "_xc": info9}
            if buy9 and x9.get("un"):
                rec9["un"] = x9["un"]
            if buy9:
                rec9 = cpx.cp_xrec.setdefault((cc9, str(x9["tx"]).lower(), r9["posting_id"]), rec9)
            key9 = ("xc", r9["posting_id"], i9)
            cpx.cp_add(g, key9, q9, c9)
            cpx.cp_ev[key9] = rec9

    def consume(cpx, g, qty, cp=True):
        cpx.oa_last[0] = Decimal(0)
        cpx.krw_last[0] = None
        cpx.krw_mix[0] = Decimal(0)
        cost_taken = Decimal(0)
        from_unknown = min(qty, g["qty_unknown"])
        g["qty_unknown"] -= from_unknown
        rem = qty - from_unknown
        take = Decimal(0)
        cpx.cp_last[0] = None
        if rem > 0 and g["qty_known"] > EPS:
            wac = g["cost"] / g["qty_known"]
            take = min(rem, g["qty_known"])
            cpx.oa_last[0] = cpx.oa_take(g, take)
            cpx.cp_last[0] = cpx.cp_take(g, take, wac * take, cp)
            g["qty_known"] -= take
            cost_taken = wac * take
            cpx.krw_last[0] = cpx.consume_krw(g, cost_taken)
            g["cost"] -= cost_taken
        return cost_taken, take, from_unknown

    def ev(cpx, flow, ts, k, d, q, a, tx, un=None):
        r0s9 = cpx.cur_row[0]
        if r0s9 is not None and str(r0s9["location"] or "").startswith("exchange:"):
            ms9 = SUB_SID_RE.match(str(r0s9["source_id"] or ""))
            if ms9 and " · 서브" not in str(d):
                d = f"{d} · 서브{ms9.group(1)[1:]}"
        e0 = {
            "t": cpx.kst_fmt(ts, "%m-%d %H:%M"),
            "k": k, "d": d, "q": q, "a": a,
            "tx": (tx[:6] + "…" + tx[-4:]) if tx else "—", "src": cpx.cur_src[0],
            "_ts": int(ts or 0),
            "_pid": cpx.cur_row[0]["posting_id"] if cpx.cur_row[0] is not None else None}
        if un is not None:
            e0["un"] = un
        ak9 = cpx._ak(a, ts, cpx.cur_row[0])
        if ak9 is not None:
            e0["aK"] = ak9
        flow["events"].append(e0)
        if cpx.cur_row[0] is not None and flow.get("_gid") is not None and (("매수" in k and "매도" not in k) or k == "LP 수수료 수령"):
            g9b = cpx.G.get(flow["_gid"])
            if g9b is not None and not g9b.get("is_stable"):
                key9 = (cpx.cur_row[0]["posting_id"], flow["_gid"])
                cpx.cp_sync(g9b, key9)
                cpx.cp_ev.setdefault(key9, e0)
        elif (cpx.cur_row[0] is not None and flow.get("_gid") is not None and k in ("전송", "입금 확인")
              and cpx.cur_row[0]["leg_kind"] in ("acq", "move_in") and (cpx.cur_row[0]["group_id"] or -cpx.cur_row[0]["asset_id"]) == flow["_gid"]):
            g9b = cpx.G.get(flow["_gid"])
            if g9b is not None and not g9b.get("is_stable"):
                key9 = ("in", cpx.cur_row[0]["posting_id"], flow["_gid"])
                cpx.cp_sync(g9b, key9)
                cpx.cp_ev.setdefault(key9, e0)
        if "매수" in k and "매도" not in k:
            flow["nb"] = flow.get("nb", 0) + 1
