from __future__ import annotations

from decimal import Decimal

import calcguard
from view_common import EPS

POOL_DUST_USD = Decimal("0.000001")


class KrwPools:

    def __init__(kpx, fxb, krw_mkt, up_mkt, fx_name):
        kpx.fxb = fxb
        kpx.krw_mkt = krw_mkt
        kpx.up_mkt = up_mkt
        kpx.fx_name = fx_name

    def krw_of(kpx, usd, ts9, row9=None):
        try:
            usd = Decimal(usd)
        except Exception as _cg9:  # noqa: BLE001 [fallback]
            calcguard.swallowed("view_b_replay:ReplayMixin._build_replay.krw_of[usd]", _cg9)
            return Decimal(0)
        if row9 is not None and row9["cost_krw"] is not None and row9["cost_usd"] is not None:
            try:
                cu9 = Decimal(row9["cost_usd"])
                if cu9 > 0:
                    return usd * Decimal(row9["cost_krw"]) / cu9
            except Exception as _cg9:  # noqa: BLE001 [optional]
                calcguard.swallowed("view_b_replay:ReplayMixin._build_replay.krw_of[cu9]", _cg9)
                pass
        return usd * Decimal(str(kpx.fxb.rate_at(ts9)))

    def consume_krw(kpx, g, cost):
        kpx.krw_mix[0] = Decimal(0)
        kpx.fs_last[0] = Decimal(0)
        kpx.krw_flow[0] = None
        kpx.krw_stl[0] = None
        flow = g.get("cur")
        if flow is None or cost <= 0:
            return None
        used = flow.get("_cost_used", Decimal(0))
        left = flow["cost"] - used
        if left <= EPS:
            return None
        dust_res = g["cost"] - left
        if not g["is_stable"] and not flow.get("_krw_stale") and EPS < dust_res <= POOL_DUST_USD:
            used_krw = flow.get("_cost_krw_used", Decimal(0))
            flow["_cost_krw_used"] = used_krw - (flow["cost_krw"] - used_krw) * dust_res / left
            flow["_cost_used"] = used = used - dust_res
            left = flow["cost"] - used
        if abs(left - g["cost"]) > EPS:
            if not (g["is_stable"] and g["cost"] > left + EPS):
                flow["_krw_stale"] = True
                return None
            take9 = cost * left / g["cost"]
            kpx.krw_mix[0] = cost - take9
            cost = take9
        used_krw = flow.get("_cost_krw_used", Decimal(0))
        taken = (flow["cost_krw"] - used_krw) * cost / left
        flow["_cost_used"] = used + cost
        flow["_cost_krw_used"] = used_krw + taken
        if flow.get("fs_kc"):
            kpx.fs_last[0] = flow["fs_kc"] * cost / left
            flow["fs_kc"] -= kpx.fs_last[0]
        kpx.krw_flow[0] = flow
        if flow.get("_stl"):
            kpx.stl_take(flow, float(cost) / float(left), float(left))
        return taken

    def krw_took(kpx, mc9, ts9):
        if kpx.krw_last[0] is None:
            return kpx.krw_of(mc9, ts9)
        return kpx.krw_last[0] + (kpx.krw_of(kpx.krw_mix[0], ts9) if kpx.krw_mix[0] > 0 else Decimal(0))

    def krw_rec(kpx, mc9):
        if kpx.krw_last[0] is None:
            return Decimal(0), Decimal(0)
        return mc9 - kpx.krw_mix[0], kpx.krw_last[0]

    def krw_inh(kpx, e9, part9, ts9):
        k9, c9 = e9.get("krw"), e9.get("cost")
        if k9 is not None and c9 is not None and c9 > 0:
            return k9 * part9 / c9
        return kpx.krw_of(part9, ts9)

    def stl_krw_mkt(kpx, r9):
        return (r9["source_ns"], r9["source_id"]) in kpx.krw_mkt or (r9["source_ns"] == "upbit:order" and kpx.up_mkt.get(r9["source_id"], "KRW") == "KRW")

    def stl_ex(kpx, r9):
        l9 = str(r9["location"] or "")
        return kpx.fx_name.get(l9.split(":")[-1], l9.split(":")[-1]) if l9.startswith("exchange:") else "온체인"

    def stl_src(kpx, r9, evk9):
        if kpx.stl_krw_mkt(r9):
            return f"{kpx.stl_ex(r9)} 원화 매수"
        d9 = [(s9, k9) for s9, k9 in (kpx.tx_legsym.get((r9["source_ns"], r9["source_id"])) or {}).get("disp", ()) if k9 != "fiat"]
        tok9 = [s9 for s9, k9 in d9 if k9 in ("tok", "nat")]
        if tok9:
            return f"{tok9[0]} 매도 대금"
        if d9:
            return f"{d9[0][0]} 교환"
        return {"EX_DEPOSIT": "입금", "EXF_DEPOSIT": "입금", "TRANSFER_IN": "입금"}.get(evk9, "취득")

    def stl_use(kpx, r9, krw_sale9):
        if krw_sale9:
            return "원화 매도"
        a9 = [(s9, k9) for s9, k9 in (kpx.tx_legsym.get((r9["source_ns"], r9["source_id"])) or {}).get("acq", ()) if k9 != "fiat"]
        tok9 = [s9 for s9, k9 in a9 if k9 in ("tok", "nat")]
        if tok9:
            return f"{tok9[0]} 매수 대금"
        if a9:
            return f"{a9[0][0]} 교환"
        return "처분"

    def stl_add(kpx, fl9, day9, lab9, usd9, krw9, qty9=None):
        if fl9 is None or usd9 <= 0:
            return
        d9 = fl9.get("_stl")
        if d9 is None:
            d9 = fl9["_stl"] = {}
            fl9["_stlt"] = []
            fl9["_stlm"] = 1.0
        m9 = fl9["_stlm"]
        if m9 < 1e-9:
            for a9 in d9.values():
                a9[0] *= m9
                a9[1] *= m9
                a9[2] *= m9
            m9 = fl9["_stlm"] = 1.0
        k9 = (day9, lab9)
        a9 = d9.get(k9)
        if a9 is None:
            a9 = d9[k9] = [0.0, 0.0, 0.0]
        a9[0] += float(usd9) / m9
        a9[1] += float(krw9) / m9
        a9[2] += float(usd9 if qty9 is None else qty9) / m9
        t9 = fl9["_stlt"]
        if k9 in t9 or len(t9) < kpx.STL_TOP or a9[0] > d9[t9[-1]][0]:
            if k9 not in t9:
                t9.append(k9)
            t9.sort(key=lambda x9: -d9[x9][0])
            del t9[kpx.STL_TOP:]

    def stl_take(kpx, fl9, f9, left9):
        d9, m9 = fl9["_stl"], fl9["_stlm"]
        top9 = []
        for k9 in fl9["_stlt"][:5]:
            u9, w9, n9 = d9[k9][0] * m9, d9[k9][1] * m9, d9[k9][2] * m9
            top9.append((k9[0], k9[1], u9 * f9, w9 * f9, min(1.0, u9 / left9) if left9 > 0 else 0.0, n9 * f9))
        kpx.krw_stl[0] = {"l": top9, "o": max(0.0, 1.0 - sum(x9[4] for x9 in top9[:3]))}
        fl9["_stlm"] = m9 * max(0.0, 1.0 - f9)

    def stl_out(kpx, kc9):
        if kc9 <= 0 or not kpx.krw_stl[0]:
            return []
        return [[d9, l9, u9, w9, n9] for d9, l9, u9, w9, _x9, n9 in kpx.krw_stl[0]["l"]]

    def stl_carry(kpx, e9, kc9):
        e9.setdefault("_stl", []).extend(kpx.stl_out(kc9))

    def stl_in(kpx, fl9, e9, sc9):
        if fl9 is None or sc9 <= 0:
            return
        f9 = float(sc9)
        for x9 in e9.get("_stl") or ():
            kpx.stl_add(fl9, x9[0], x9[1], x9[2] * f9, x9[3] * f9, (x9[4] if len(x9) > 4 else x9[2]) * f9)
