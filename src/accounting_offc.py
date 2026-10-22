from __future__ import annotations

from decimal import Decimal

from view_common import EPS
from view_common import _f


class OffcView:

    def __init__(ofx, *, offcin):
        ofx.fx_name = offcin.fx_name
        ofx.offc_ans = offcin.offc_ans
        ofx.offc_excl = offcin.offc_excl
        ofx.offc_on = offcin.offc_on
        ofx.offc_pool = offcin.offc_pool
        ofx.offc_st = offcin.offc_st
        ofx.offc_wd_addr = offcin.offc_wd_addr

    def offc_s(ofx: OffcView, ex: str) -> dict:
        return ofx.offc_st.setdefault(ex, {"wdN": 0, "wdCost": Decimal(0), "wdUnkQty": Decimal(0), "depN": 0, "inhN": 0,
                                           "inhCost": Decimal(0), "inhQty": Decimal(0), "inhUnkQty": Decimal(0),
                                           "excessQty": Decimal(0), "excessN": 0, "syms": set(),
                                           "wdCostStable": Decimal(0), "inhCostStable": Decimal(0), "bySym": {}, "byAddr": {},
                                           "exclN": 0, "exclCost": Decimal(0)})

    def offc_addr_add(ofx: OffcView, ex: str, uid: str, cost: Decimal) -> None:
        addr = ofx.offc_wd_addr.get((ex, uid)) or ""
        ent = ofx.offc_s(ex)["byAddr"].setdefault(addr, [0, Decimal(0)])
        ent[0] += 1
        ent[1] += cost
        if addr and addr in ofx.offc_excl.get(ex, ()) and ex in ofx.offc_on:
            ofx.offc_s(ex)["exclN"] += 1
            ofx.offc_s(ex)["exclCost"] += cost

    def offc_add(ofx: OffcView, ex: str, sym: str, stable: bool, wd: Decimal | None = None, dep: bool = False,
                 inh: Decimal | None = None) -> None:
        st = ofx.offc_s(ex)
        ent = st["bySym"].setdefault(sym, {"wdN": 0, "wdCost": Decimal(0), "depN": 0, "inhN": 0, "inhCost": Decimal(0), "stable": bool(stable)})
        if wd is not None:
            ent["wdN"] += 1
            ent["wdCost"] += wd
            if stable:
                st["wdCostStable"] += wd
        if dep:
            ent["depN"] += 1
        if inh is not None:
            ent["inhN"] += 1
            ent["inhCost"] += inh
            if stable:
                st["inhCostStable"] += inh

    def offc_summary(ofx):
        out9 = {}
        for ex9 in sorted(set(ofx.offc_st) | set(ofx.offc_on) | set(ofx.offc_ans)):
            s9 = ofx.offc_s(ex9)
            left9 = {}
            for (e9, _k9), ls9 in ofx.offc_pool.items():
                if e9 != ex9:
                    continue
                for l9 in ls9:
                    if l9["left"] > EPS and l9["qty"] > 0:
                        a9 = left9.setdefault(l9["sym"], [Decimal(0), Decimal(0), 0])
                        a9[0] += l9["left"]
                        a9[1] += l9["cost"] * l9["left"] / l9["qty"]
                        a9[2] += 1
            out9[ex9] = {"on": ex9 in ofx.offc_on, "name": ofx.fx_name.get(ex9, ex9),
                         "answered": ex9 in ofx.offc_ans,
                         "excl": sorted(ofx.offc_excl.get(ex9, ())), "exclN": s9["exclN"], "exclCost": _f(s9["exclCost"], 2) or 0,
                         "byAddr": [{"addr": a0, "n": v9[0], "cost": _f(v9[1], 2) or 0, "excl": bool(a0 and a0 in ofx.offc_excl.get(ex9, ()))}
                                    for a0, v9 in sorted(s9["byAddr"].items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))[:40]],
                         "assumedSold": {"n": ofx.offc_sold[0], "realized": _f(ofx.offc_sold[1], 2) or 0} if ex9 in ofx.offc_on else None,
                         "wdN": s9["wdN"], "wdCost": _f(s9["wdCost"], 2) or 0, "depN": s9["depN"], "syms": len(s9["syms"]),
                         "inhN": s9["inhN"], "inhCost": _f(s9["inhCost"], 2) or 0,
                         "excessN": s9["excessN"],
                         "poolLeftN": sum(v9[2] for v9 in left9.values()),
                         "poolLeftCost": _f(sum((v9[1] for v9 in left9.values()), Decimal(0)), 2) or 0,
                         "poolLeft": [[s0, _f(v9[0], 6) or 0, _f(v9[1], 2) or 0]
                                      for s0, v9 in sorted(left9.items(), key=lambda kv: -kv[1][1])[:12]],
                         "wdCostStable": _f(s9["wdCostStable"], 2) or 0, "inhCostStable": _f(s9["inhCostStable"], 2) or 0,
                         "bySym": [{"sym": s0, "wdN": b9["wdN"], "wdCost": _f(b9["wdCost"], 2) or 0, "depN": b9["depN"], "inhN": b9["inhN"],
                                    "inhCost": _f(b9["inhCost"], 2) or 0, "stable": b9["stable"],
                                    "leftCost": _f(left9.get(s0, [0, Decimal(0)])[1], 2) or 0}
                                   for s0, b9 in sorted(s9["bySym"].items(), key=lambda kv: (kv[1]["stable"], -kv[1]["wdCost"], kv[0]))[:30]]}
        return out9
