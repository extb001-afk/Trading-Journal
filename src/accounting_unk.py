from __future__ import annotations

from decimal import Decimal

import accounting_util
import calcguard
from view_common import EPS


class UnkBook:

    def __init__(unx, px, *, cost_ov, fs_on, krw_of):
        unx.px = px
        unx.sb = px.sb
        unx.cost_ov = cost_ov
        unx.fs_on = fs_on
        unx.krw_of = krw_of
        unx.cb = px.cb
        unx.fs_sum = {"n": 0, "q": Decimal(0), "usd": Decimal(0), "miss": 0, "miss_q": {}, "src": {}, "rows": 0, "real": Decimal(0),
                      "st_n": 0, "st_usd": Decimal(0), "st_miss": 0, "be_skip": 0,
                      "bk": {}, "g": {}, "mk": {}, "ur": {}, "up": {}}

    def apply_ov(unx, fl9, pend9):
        ts9, take, unit_d, txt9, ref9, badd9 = pend9
        fl9["cost"] += take * unit_d
        fl9["cost_krw"] += unx.krw_of(take * unit_d, ts9)
        fl9["bought"] += badd9
        unx.px.cpx.ev(fl9, ts9, "원가 지정", txt9, f"{float(take):,.4f}".rstrip("0").rstrip("."), f"${float(take * unit_d):,.2f}", ref9,
           un=accounting_util._un(take, take * unit_d))

    def note_unk(unx, g9, ts9, kind9, qty9, ref9, ex9=None, chain9=None, up_gid=None, unc9=None, via9=None, fs9=None):
        try:
            q9 = float(qty9)
        except (TypeError, ValueError):
            return
        if q9 <= 1e-9:
            return
        lst9 = g9.setdefault("unk_src", [])
        ref = str(ref9 or "")
        ov9 = unx.cost_ov.get(f"g{g9.get('gid')}") if isinstance(unx.cost_ov, dict) else None
        applied9 = None
        if isinstance(ov9, dict) and ov9.get("mode") in ("unit", "market"):
            unit9 = 0.0
            if ov9.get("mode") == "market":
                try:
                    unit9 = float(unx.sb.px.candle_usd(g9.get("sym") or "", int(ts9) * 1000) or 0)
                except Exception as _cg9:  # noqa: BLE001 [fallback]
                    calcguard.swallowed("view_b_replay:ReplayMixin._build_replay.note_unk", _cg9)
                    unit9 = 0.0
            else:
                try:
                    unit9 = float(ov9.get("unit") or 0)
                except (TypeError, ValueError):
                    unit9 = 0.0
            if unit9 > 0:
                dq = Decimal(str(qty9))
                take = min(dq, g9["qty_unknown"])
                if take > 0:
                    unx.cb.sub_unknown(g9, take)
                    unx.cb.add_known(g9, take)
                    g9["cost"] += take * Decimal(str(unit9))
                    unx.cb.note_cost(g9, take, unit9)
                    unc_d = dq if unc9 is None else max(Decimal(0), min(dq, Decimal(str(unc9))))
                    pend9 = (ts9, take, Decimal(str(unit9)), ("개당 지정 단가" if ov9.get("mode") != "market" else "유입 당시 시세") + f" ${unit9:,.6g} 적용",
                             ref if ref.startswith("0x") else "", take * unc_d / dq)
                    if g9.get("cur") is not None:
                        unx.apply_ov(g9["cur"], pend9)
                    else:
                        g9.setdefault("_ov_pend", []).append(pend9)
                    applied9 = {"mode": ov9.get("mode"), "unit": unit9, "qty": float(take)}
        fsa9 = None
        if applied9 is None and unx.fs_on and not g9.get("is_stable") and not g9.get("is_fiat"):
            dq9 = Decimal(str(qty9))
            fq9 = dq9 if fs9 is None else max(Decimal(0), min(dq9, Decimal(str(fs9))))
            if fq9 > EPS:
                fsa9 = unx.px.fsx.fs_conv(g9, ts9, fq9, dq9, unc9, kind9)
            if dq9 - fq9 > EPS:
                unx.px.fsx.fs_why(g9, "fs0", kind9, dq9 - fq9)
                if up_gid is not None:
                    u9 = unx.fs_sum["up"].setdefault(str(g9["gid"]), {})
                    u9[str(up_gid)] = u9.get(str(up_gid), 0.0) + float(dq9 - fq9)
        if applied9 is not None:
            ovs9 = g9.setdefault("ov_applied", [Decimal(0), Decimal(0)])
            ovs9[0] += Decimal(str(applied9["qty"])); ovs9[1] += Decimal(str(applied9["qty"])) * Decimal(str(applied9["unit"]))
        ent9 = {"ts": int(ts9), "kind": kind9, "qty": q9, "ref": ref, "ex": ex9,
                "chain": chain9, "from": None, "to": None, "up_gid": up_gid, "ov": applied9, "via": via9,
                **({"fs": {"qty": float(fsa9[0]), "unit": fsa9[1]}} if fsa9 else {})}
        if not ref:
            for y9 in lst9:
                if not y9["ref"] and y9["kind"] == kind9:
                    y9["qty"] += q9; y9["ts"] = min(y9["ts"], int(ts9))
                    if applied9 is not None:
                        y9["ov"] = y9["ov"] or {"mode": applied9["mode"], "unit": applied9["unit"], "qty": 0.0}
                        y9["ov"]["qty"] += applied9["qty"]
                    if fsa9:
                        f0 = y9.get("fs") or {"qty": 0.0, "unit": fsa9[1]}
                        f0["qty"] += float(fsa9[0])
                        y9["fs"] = f0
                    break
            else:
                lst9.append(ent9)
        elif len(lst9) < 60:
            lst9.append(ent9)
        else:
            i_min = min(range(len(lst9)), key=lambda i9: lst9[i9]["qty"])
            if lst9[i_min]["qty"] < q9:
                lst9[i_min] = ent9
