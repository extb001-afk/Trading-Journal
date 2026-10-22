from __future__ import annotations

from decimal import Decimal

from view_common import EPS
from view_common import _f
from view_misc import fx_candle_near


class FeeBook:

    def __init__(fbx, sb, books, kst_fmt, cb):
        fbx.sb = sb
        fbx.realized_by_loc = books.realized_by_loc
        fbx.realized_krw_by_date = books.realized_krw_by_date
        fbx.realized_by_date = books.realized_by_date
        fbx.gas_expense = books.gas_expense
        fbx.gas_by_chain = books.gas_by_chain
        fbx.gas_by_month = books.gas_by_month
        fbx.tax_rows = books.tax_rows
        fbx.fee_day = books.fee_day
        fbx.ex_fee = books.ex_fee
        fbx.ex_fee_m = books.ex_fee_m
        fbx.wd_fee = books.wd_fee
        fbx.wd_fee_m = books.wd_fee_m
        fbx.kst_fmt = kst_fmt
        fbx.cb = cb

    def tax_krw_acq(fbx, tax9, g, flow, cc9, cck9, rate_s, dkey, venue_loc=None, mix9=None):
        if g["is_stable"]:
            part9 = cc9 - (mix9 or Decimal(0))
            if cck9 is None or part9 <= EPS or not (0.5 <= (float(cck9) / float(part9)) / max(rate_s, 1.0) <= 2.0):
                return
            tax9["_akr"] = float(cck9) + float(mix9 or 0) * rate_s
            tax9["akr"] = round(tax9["_akr"])
            return
        fck9, fcu9 = float(flow.get("cost_krw") or 0), float(flow.get("cost") or 0)
        if fck9 > 0 and fcu9 > 0 and 0.5 <= (fck9 / fcu9) / max(rate_s, 1.0) <= 2.0:
            tax9["_akr"] = float(cc9) * fck9 / fcu9
            if cck9 is not None and cc9 > 0 and \
                    0.5 <= (float(cck9) / float(cc9)) / max(rate_s, 1.0) <= 2.0:
                tax9["_akr"] = float(cck9)
            tax9["akr"] = round(tax9["_akr"])
            if float(flow.get("kmc") or 0) >= 0.99 * fcu9:
                if cck9 is not None:
                    tax9["_akr"] = float(cck9)
                    tax9["akr"] = round(tax9["_akr"])
                if not g["is_stable"]:
                    adj9 = float(cc9) * rate_s - tax9["_akr"]
                    flow["rbdk"][dkey] = flow["rbdk"].get(dkey, 0.0) + adj9
                    fbx.realized_krw_by_date[dkey] = fbx.realized_krw_by_date.get(dkey, 0) + adj9
                    if venue_loc is not None:
                        fbx.realized_by_loc.setdefault((venue_loc, dkey), [0.0, 0.0])[1] += adj9
                    tax9["_akm"] = 1

    def fee_unit(fbx, g9, ts9, wac9=None):
        if g9["is_stable"]:
            return Decimal(1)
        if not g9.get("is_fiat"):
            c9 = fx_candle_near(fbx.fxb, g9["sym"], ts9)
            if c9:
                return Decimal(str(c9))
        if wac9 is not None and wac9 > 0:
            return wac9
        if g9["qty_known"] > EPS:
            return g9["cost"] / g9["qty_known"]
        return None

    def fee_expense(fbx, usd9, ts9, dkey9, kind9, where9):
        if usd9 <= 0:
            return
        rt9 = fbx.fxb.rate_at(ts9)
        fbx.realized_by_date[dkey9] = fbx.realized_by_date.get(dkey9, 0) - float(usd9)
        fbx.realized_krw_by_date[dkey9] = fbx.realized_krw_by_date.get(dkey9, 0) - float(usd9) * rt9
        ge9 = fbx.gas_expense.setdefault(dkey9, [Decimal(0), 0, 0.0, {}])
        ge9[0] += usd9
        ge9[1] += 1
        ge9[2] += float(usd9) * rt9
        kd9 = ge9[3].setdefault(kind9, [Decimal(0), 0, Decimal(0), 0, ""])
        kd9[0] += usd9
        kd9[1] += 1
        if usd9 > kd9[2]:
            kd9[2], kd9[3], kd9[4] = usd9, int(ts9 or 0), where9

    def br_fee_add(fbx, chain9, usd9, ts9):
        if usd9 <= 0:
            return
        fbx.fee_day_add(usd9, ts9)
        for a9 in (fbx.gas_by_chain.setdefault(chain9, {"usd": Decimal(0), "tx": 0}),
                   fbx.gas_by_month.setdefault(fbx.kst_fmt(ts9, "%Y-%m"), {}).setdefault(chain9, {"usd": Decimal(0), "tx": 0})):
            a9["usd"] += usd9
            a9["br"] = a9.get("br", Decimal(0)) + usd9

    def fee_day_add(fbx, usd9, ts9):
        if usd9 > 0:
            d9 = fbx.fee_day.setdefault(fbx.kst_fmt(ts9, "%Y-%m-%d"), [Decimal(0), 0.0])
            d9[0] += usd9
            d9[1] += float(usd9) * fbx.fxb.rate_at(ts9)

    def ex_fee_add(fbx, ex9, usd9, ts9):
        if usd9 <= 0:
            return
        fbx.fee_day_add(usd9, ts9)
        a9 = fbx.ex_fee.setdefault(ex9, {"usd": Decimal(0), "tx": 0})
        a9["usd"] += usd9
        a9["tx"] += 1
        m9 = fbx.ex_fee_m.setdefault(fbx.kst_fmt(ts9, "%Y-%m"), {}).setdefault(ex9, {"usd": Decimal(0), "tx": 0})
        m9["usd"] += usd9
        m9["tx"] += 1

    def wd_fee_add(fbx, ex9, usd9, ts9):
        if usd9 <= 0:
            return
        fbx.fee_day_add(usd9, ts9)
        for a9 in (fbx.wd_fee.setdefault(ex9, {"usd": Decimal(0), "tx": 0}),
                   fbx.wd_fee_m.setdefault(fbx.kst_fmt(ts9, "%Y-%m"), {}).setdefault(ex9, {"usd": Decimal(0), "tx": 0})):
            a9["usd"] += usd9
            a9["tx"] += 1

    def wd_fee_q(fbx, ex9, uid9, evk9, wq9):
        if (evk9 == "EX_WITHDRAW") != (ex9 == "upbit") or (evk9 == "EXF_WITHDRAW" and ex9 not in fbx.WD_FEE_IN_AMT):
            return Decimal(0)
        p9 = fbx.wd_raw9.get((ex9, uid9))
        if not isinstance(p9, dict) or str(p9.get("state") or "").upper() != "DONE":
            return Decimal(0)
        fc9 = str(p9.get("fee_ccy") or p9.get("fee_currency") or "").upper()
        if fc9 and fc9 != str(p9.get("currency") or "").upper():
            return Decimal(0)
        try:
            f9, a9 = Decimal(str(p9.get("fee") or "0")), Decimal(str(p9.get("amount") or "0"))
        except ArithmeticError:
            return Decimal(0)
        if not (f9.is_finite() and a9.is_finite()) or f9 <= 0 or f9 >= wq9:
            return Decimal(0)
        want9 = a9 + f9 if evk9 == "EX_WITHDRAW" else a9
        if abs(wq9 - want9) > max(want9 * Decimal("0.000001"), Decimal("0.00000001")):
            return Decimal(0)
        return f9

    def fee_gain(fbx, g9, unit9, mk9, mc9, ts9, dkey9, chain9, mck9=None, mix9=None, stl9=None, cmp9=None, fs9=None, lab9=None, fsm9=True):
        if unit9 is None or mk9 <= EPS or unit9 <= 0 or g9.get("is_fiat"):
            return Decimal(0)
        gain9 = unit9 * mk9 - mc9
        rt9, rs9 = fbx.fxb.rate_src(ts9)
        fl9 = g9["cur"] or fbx.flow_of(g9, ts9, chain9)
        fbx.cb.realize(g9, gain9)
        fl9["realized"] += gain9
        fl9["rbd"][dkey9] = fl9["rbd"].get(dkey9, Decimal(0)) + gain9
        fl9["rbdk"][dkey9] = fl9["rbdk"].get(dkey9, 0.0) + float(gain9) * rt9
        fl9.setdefault("rch", {}).setdefault(dkey9, set()).add(fbx.cur_lab[0] or "?")
        fbx.realized_by_date[dkey9] = fbx.realized_by_date.get(dkey9, 0) + float(gain9)
        fbx.realized_krw_by_date[dkey9] = fbx.realized_krw_by_date.get(dkey9, 0) + float(gain9) * rt9
        d9 = unit9 * mk9
        t9 = {"sold": dkey9, "sym": g9["sym"], "ticker": g9["sym"], "ex": lab9 or "수수료로 쓴 코인(처분)",
              "qty": _f(mk9, 4), "acq": _f(mc9, 2), "disp": _f(d9, 2), "fee": 0, "rate": round(rt9, 4), "rateSrc": rs9,
              "_acq": float(mc9), "_disp": float(d9), "_qty": float(mk9)}
        if rs9 not in ("spot", "default"):
            fbx.tax_krw_acq(t9, g9, fl9, mc9, mck9, rt9, dkey9, mix9=mix9)
        if not fsm9:
            pass
        elif fs9 is not None:
            sv9 = fbx.fs_last[0]
            fbx.fs_last[0] = fs9
            fbx.fs_mark(g9, fl9, t9, cmp9, mk9, d9, mc9, rt9, dkey9)
            fbx.fs_last[0] = sv9
        else:
            fbx.fs_mark(g9, fl9, t9, cmp9, mk9, d9, mc9, rt9, dkey9)
        if g9["is_stable"]:
            fbx.stable_fx_mark(t9, mc9, False, stl9=stl9, cck9=mck9, mix9=mix9, use9="수수료")
        fbx.tax_rows.append(t9)
        return gain9
