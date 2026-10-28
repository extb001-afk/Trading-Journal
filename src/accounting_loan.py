from __future__ import annotations

from decimal import Decimal

import accounting_util
from view_common import EPS
from view_fspin import FS_EX


class LoanBook:

    def __init__(lnx, px, *, _qfmt, lf_pend, loan_px):
        lnx.px = px
        lnx._qfmt = _qfmt
        lnx.lf_pend = lf_pend
        lnx.loan_px = loan_px
        lnx.tax_rows = px.books.tax_rows
        lnx.cb = px.cb

    def loan_settle(lnx):
        for g9, lf9, ts9, dk9, ch9, tx9, loc9, _k9, row9 in lnx.lf_pend:
            qp9 = sum((t9 for w9, t9 in lf9 if w9 in lnx.loan_px), Decimal(0))
            if qp9 <= EPS:
                continue
            unit9 = sum((lnx.loan_px[w9] * t9 for w9, t9 in lf9 if w9 in lnx.loan_px), Decimal(0)) / qp9
            fk9 = min(qp9, g9["qty_known"])
            mc9 = (g9["cost"] / g9["qty_known"]) * fk9 if g9["qty_known"] > EPS else Decimal(0)
            mck9 = lnx.px.kpx.consume_krw(g9, mc9)
            mix9, stl9 = lnx.px.kpx.krw_mix[0], lnx.px.kpx.krw_stl[0]
            accounting_util.oa_take(g9, fk9)
            cmp9 = lnx.px.cpx.cp_emit(lnx.px.cpx.cp_take(g9, fk9, mc9), qp9 - fk9, qp9, mc9)
            lnx.cb.sub_known(g9, fk9)
            lnx.cb.sub_cost(g9, mc9)
            lnx.cb.floor_sub_unknown(g9, qp9 - fk9)
            ex9 = loc9.split(":")[1] if loc9.count(":") >= 1 else loc9
            n0 = len(lnx.tax_rows)
            gain9 = lnx.px.fbx.fee_gain(g9, unit9, fk9, mc9, ts9, dk9, ch9, mck9, mix9=mix9, stl9=stl9, cmp9=cmp9,
                             lab9=f"{lnx.px.ofx.fx_name.get(ex9, ex9)} 대출 상환(빌린 코인 · 빌린 시각 시가로 정산)", fsm9=False)
            fl9 = g9["cur"] or lnx.px.flow_of(g9, ts9, ch9)
            if len(lnx.tax_rows) > n0:
                t9 = lnx.tax_rows[-1]
                t9["ex"] = str(t9.get("ex") or "") + FS_EX
                lnx.px.unx.fs_sum["rows"] += 1
                lnx.px.fsx.fs_sales.append((fl9, t9, 1.0, float(mc9), float(t9.get("rate") or 0), dk9))
            cr9, cs9 = lnx.px.cpx.cur_row[0], lnx.px.cpx.cur_src[0]
            lnx.px.cpx.cur_row[0], lnx.px.cpx.cur_src[0] = row9, "ex:" + ex9
            lnx.px.cpx.ev(fl9, ts9, "전송", f"{lnx.px.ofx.fx_name.get(ex9, ex9)} 대출 상환 · 빌린 {lnx._qfmt(qp9)} {g9['sym']} 갚음 — 빌린 시각 시가 ${float(unit9):,.6g} 로 정산"
               f"(추정 · 실현 ${float(gain9):,.2f})", lnx._qfmt(qp9), "—", tx9)
            lnx.px.cpx.cur_row[0], lnx.px.cpx.cur_src[0] = cr9, cs9
            lnx.px.unx.fs_sum["loan"]["settled"] += 1
            lnx.px.unx.fs_sum["loan"]["v0"] += float(unit9 * qp9)
            lnx.px.unx.fs_sum["loan"]["gain"] += float(gain9)
            if g9["qty_known"] + g9["qty_unknown"] <= Decimal("0.000001"):
                g9["cur"] = None
        lnx.lf_pend.clear()
