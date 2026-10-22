from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import acct_norm
import lpdec
from view_common import CHAIN_NAME
from view_common import EPS
from timeutil import KST
from view_common import LP_CONV_MIN_USD
from view_common import _f


def _lp_small(x, *, rent, lpx):
    if int(x["asset_id"]) in rent:
        return True
    if x["cost_usd"] is not None:
        return abs(Decimal(x["cost_usd"])) < LP_CONV_MIN_USD
    gx = lpx.gstate(x)
    wac = lpx.cb.wac_or_none(gx)
    return wac is not None and wac * (-lpx.sb._norm(x)) < LP_CONV_MIN_USD


class LpBook:

    def __init__(lpx, px, *, _un, gstate, lpin, fns):
        lpx.sb = px.sb
        lpx._ak = fns.ak
        lpx._un = _un
        lpx.consume_krw = px.kpx.consume_krw
        lpx.cp_emit = px.cpx.cp_emit
        lpx.cp_sync = px.cpx.cp_sync
        lpx.cp_take = px.cpx.cp_take
        lpx.cur_lab = px.fbx.cur_lab
        lpx.cur_row = px.cpx.cur_row
        lpx.cur_src = px.cpx.cur_src
        lpx.ev = px.cpx.ev
        lpx.flow_of = px.fbx.flow_of
        lpx.fxb = px.fbx.fxb
        lpx.gstate = gstate
        lpx.krw_of = px.kpx.krw_of
        lpx.lp_by_tx = lpin.lp_by_tx
        lpx.lp_dep_seen = lpin.lp_dep_seen
        lpx.lp_events = px.books.lp_events
        lpx.lp_meta_by = lpin.lp_meta_by
        lpx.lp_mgrs = lpin.lp_mgrs
        lpx.lp_tx_rows = lpin.lp_tx_rows
        lpx.lpb = lpin.lpb
        lpx.note_unk = px.unx.note_unk
        lpx.realized_by_date = px.books.realized_by_date
        lpx.realized_krw_by_date = px.books.realized_krw_by_date
        lpx.tax_krw_acq = px.fbx.tax_krw_acq
        lpx.tax_rows = px.books.tax_rows
        lpx.cb = px.cb

    def lp_bucket(lpx, loc9, chain9, ts9):
        b9 = lpx.lpb.get(loc9)
        if b9 is None:
            parts9 = loc9.split(":")
            mgr9 = parts9[2] if len(parts9) > 2 else ""
            meta9 = (lpx.lp_mgrs.get(chain9) or {}).get(mgr9) or lpx.lp_meta_by.get((chain9, mgr9)) or {}
            b9 = lpx.lpb[loc9] = {"loc": loc9, "chain": chain9, "mgr": mgr9, "id": parts9[3] if len(parts9) > 3 else "?",
                              "proto": meta9.get("proto"), "name": meta9.get("name") or "LP",
                              "units": {}, "ucost": {}, "gids": {}, "deposited": Decimal(0),
                              "opened": ts9, "last": ts9, "realized": Decimal(0), "income": Decimal(0),
                              "returned": {}, "converted": {}, "acq": {}, "rbd": {}, "rbdk": {}}
        b9["last"] = max(b9["last"], ts9)
        return b9

    def lp_event(lpx, b9, ts9, k9, d9, q9, a9, tx9):
        lpx.lp_events.append({"t": datetime.fromtimestamp(ts9, KST).strftime("%m-%d %H:%M"), "_ts": int(ts9), "lp": b9["loc"],
                          "sym": b9.get("pool") or lpx.lp_label(b9), "k": k9, "d": d9, "q": q9, "a": a9,
                          "tx": (tx9[:6] + "…" + tx9[-4:]) if tx9 else "—", "src": lpx.cur_src[0]})
        ak9 = lpx._ak(a9, ts9)
        if ak9 is not None:
            lpx.lp_events[-1]["aK"] = ak9

    def lp_move(lpx, r9, g9, q9, ts9, lk9, chain9, txh9):
        loc9 = r9["location"] or ""
        if not loc9.startswith("lp:"):
            return
        b9 = lpx.lp_bucket(loc9, chain9, ts9)
        sym9 = g9["sym"]
        b9["gids"][sym9] = g9["gid"]
        qs9 = f"{abs(q9):,.4f}".rstrip("0").rstrip(".")
        if lk9 == "move_in":
            wac9 = (g9["cost"] / g9["qty_known"]) if g9["qty_known"] > EPS else (Decimal(1) if g9["is_stable"] else Decimal(0))
            b9["units"][sym9] = b9["units"].get(sym9, Decimal(0)) + q9
            b9["ucost"][sym9] = b9["ucost"].get(sym9, Decimal(0)) + wac9 * q9
            b9["deposited"] += wac9 * q9
            lpx.lp_dep_seen.add(loc9)
            lpx.lp_event(b9, ts9, "유동성 예치", f"{CHAIN_NAME.get(chain9, chain9)} · {lpx.lp_label(b9)}", f"{qs9} {sym9}",
                     f"${float(wac9 * q9):,.2f}", txh9)
        else:
            qa = -q9
            u0 = b9["units"].get(sym9, Decimal(0))
            c_back = (b9["ucost"].get(sym9, Decimal(0)) * min(qa, u0) / u0) if u0 > EPS else Decimal(0)
            b9["units"][sym9] = max(Decimal(0), u0 - qa)
            b9["ucost"][sym9] = max(Decimal(0), b9["ucost"].get(sym9, Decimal(0)) - c_back)
            b9["returned"][sym9] = b9["returned"].get(sym9, Decimal(0)) + qa
            lpx.lp_event(b9, ts9, "유동성 회수", f"{CHAIN_NAME.get(chain9, chain9)} · {lpx.lp_label(b9)} · 원금 복귀", f"{qs9} {sym9}",
                     f"${float(c_back):,.2f}", txh9)

    def lp_tx(lpx, r9):
        chain9, txh9, ts9 = r9["chain"] or "?", r9["source_id"], r9["event_ts"]
        dkey9 = acct_norm.iso_day(ts9)
        legs9 = lpx.lp_tx_rows.get((r9["source_ns"], txh9)) or [r9]
        lpi9 = lpx.lp_by_tx.get((r9["source_ns"], txh9)) or {}
        pre9 = f"lp:{chain9}:{lpi9.get('mgr') or ''}"
        cand_locs = [f"{pre9}:{t}" for t in (lpdec.lp_tid(i) for i in (lpi9.get("wd_ids") or [])) if t is not None] \
            + [x for x in (lpi9.get("unk_loc"), lpi9.get("dep_loc"), lpi9.get("loc")) if x]
        disp9 = [x for x in legs9 if x["leg_kind"] == "disp"]
        acq9 = [x for x in legs9 if x["leg_kind"] == "acq"]
        home = next((x["location"] for x in disp9 if (x["location"] or "").startswith("lp:")), None) \
            or next((l for l in cand_locs if l in lpx.lpb), None) or (cand_locs[0] if cand_locs else f"{pre9}:?")
        b9 = lpx.lp_bucket(home, chain9, ts9)
        rent9 = {int(a) for a in (lpi9.get("rent_aids") or []) if str(a).lstrip("-").isdigit()}

        conv9 = [x for x in disp9 if not _lp_small(x, rent=rent9, lpx=lpx)]
        rent_only = bool(disp9) and not conv9
        B = Decimal(0); w_all = Decimal(0); w_known = Decimal(0); conv_txt = []
        dinfo = []
        for x in disp9:
            gx = lpx.gstate(x)
            qx = -lpx.sb._norm(x)
            if qx <= 0:
                continue
            fk = min(qx, gx["qty_known"]); fu = qx - fk
            wac = lpx.cb.wac(gx)
            bk = wac * fk
            krw9 = lpx.consume_krw(gx, bk)
            cp9x = lpx.cp_take(gx, fk, bk)
            lpx.cb.release(gx, fk, bk, fu)
            lpx.cb.snapshot(gx, ts9, -qx)
            mv = Decimal(x["cost_usd"]) if x["cost_usd"] is not None else None
            wt = mv if (mv is not None and mv > 0) else (bk if bk > 0 else qx)
            B += bk; w_all += wt; w_known += wt * (fk / qx)
            bx = lpx.lp_bucket(x["location"], chain9, ts9) if (x["location"] or "").startswith("lp:") else b9
            u0 = bx["units"].get(gx["sym"], Decimal(0))
            c_cv = (bx["ucost"].get(gx["sym"], Decimal(0)) * min(qx, u0) / u0) if u0 > EPS else Decimal(0)
            bx["units"][gx["sym"]] = max(Decimal(0), u0 - qx)
            bx["ucost"][gx["sym"]] = max(Decimal(0), bx["ucost"].get(gx["sym"], Decimal(0)) - c_cv)
            if rent_only:
                if gx["qty_known"] + gx["qty_unknown"] <= Decimal("0.000001"):
                    gx["cur"] = None
                continue
            bx["converted"][gx["sym"]] = bx["converted"].get(gx["sym"], Decimal(0)) + qx
            conv_txt.append(f"{float(qx):,.4f}".rstrip("0").rstrip(".") + f" {gx['sym']}")
            dinfo.append({"g": gx, "qx": qx, "fk": fk, "bk": bk, "wk": wt * (fk / qx), "krw": krw9, "bx": bx, "_cp": cp9x,
                          "fl": None if gx["is_stable"] else (gx["cur"] or lpx.flow_of(gx, ts9, chain9))})
        k9 = (w_known / w_all) if w_all > 0 else Decimal(1)
        B_rent = Decimal(0)
        if rent_only:
            B_rent, B = B, Decimal(0)
            disp9 = []
        priced = [(x, Decimal(x["cost_usd"])) for x in acq9 if x["cost_usd"] is not None]
        unpriced = [x for x in acq9 if x["cost_usd"] is None]
        M = sum((m for _x, m in priced), Decimal(0))
        no_dep = (not disp9) and not any(l in lpx.lp_dep_seen for l in cand_locs)
        cost_of = {}
        realized9 = Decimal(0)
        income9 = Decimal(0)
        if disp9:
            kB = B
            if priced and M > 0 and (not unpriced or M >= kB):
                for x, m in priced:
                    cost_of[x["posting_id"]] = kB * m / M
                for x in unpriced:
                    cost_of[x["posting_id"]] = Decimal(0)
            elif priced:
                for x, m in priced:
                    cost_of[x["posting_id"]] = m
                for x in unpriced:
                    cost_of[x["posting_id"]] = (kB - M) / len(unpriced)
            elif acq9:
                for x in acq9:
                    cost_of[x["posting_id"]] = kB / len(acq9)
            realized9 = Decimal(0)
        elif not no_dep:
            for x, m in priced:
                if int(x["asset_id"]) in rent9:
                    cost_of[x["posting_id"]] = Decimal(0)
                    continue
                cost_of[x["posting_id"]] = m
                income9 += m
            for x in unpriced:
                cost_of[x["posting_id"]] = Decimal(0)
        sale9 = {}
        if disp9 and dinfo and B > 0 and k9 > 0:
            st_acq = [x for x in acq9 if lpx.gstate(x)["is_stable"] and lpx.sb._norm(x) > 0 and x["posting_id"] in cost_of]
            ns_ix = [i for i, d in enumerate(dinfo) if d["fl"] is not None and d["fk"] > 0]
            wk_all = sum((d["wk"] for d in dinfo), Decimal(0))
            wk_ns = sum((dinfo[i]["wk"] for i in ns_ix), Decimal(0))
            c_st = sum((cost_of[x["posting_id"]] for x in st_acq), Decimal(0))
            if st_acq and ns_ix and wk_all > 0 and wk_ns > 0 and c_st > 0:
                ns9 = wk_ns / wk_all
                fs9 = min(Decimal(1), c_st / B)
                C_R = fs9 * sum((dinfo[i]["bk"] for i in ns_ix), Decimal(0))
                faces = {x["posting_id"]: (Decimal(x["cost_usd"]) if x["cost_usd"] is not None else lpx.sb._norm(x)) * k9 for x in st_acq}
                P_R = ns9 * sum(faces.values(), Decimal(0))
                for x in st_acq:
                    c = cost_of[x["posting_id"]]
                    cost_of[x["posting_id"]] = c - C_R * c / c_st + ns9 * faces[x["posting_id"]]
                for i in ns_ix:
                    d = dinfo[i]
                    sale9[i] = (d["fk"] * fs9, d["bk"] * fs9, P_R * d["wk"] / wk_ns, (d["krw"] * fs9) if d["krw"] is not None else None)
        st_real9 = Decimal(0)
        for i, d in enumerate(dinfo):
            gx, fl9, qx, bk = d["g"], d["fl"], d["qx"], d["bk"]
            if fl9 is None:
                continue
            qi, ci, pi, ki = sale9.get(i, (Decimal(0), Decimal(0), Decimal(0), None))
            if qi > 0:
                pnl9 = pi - ci
                st_real9 += pnl9
                rate9, rsrc9 = lpx.fxb.rate_src(ts9)
                lpx.cb.realize(gx, pnl9)
                fl9["realized"] += pnl9
                fl9["rbd"][dkey9] = fl9["rbd"].get(dkey9, Decimal(0)) + pnl9
                fl9["rbdk"][dkey9] = fl9["rbdk"].get(dkey9, 0.0) + float(pnl9) * rate9
                fl9.setdefault("rch", {}).setdefault(dkey9, set()).add(lpx.cur_lab[0] or "?")
                lpx.realized_by_date[dkey9] = lpx.realized_by_date.get(dkey9, 0) + float(pnl9)
                lpx.realized_krw_by_date[dkey9] = lpx.realized_krw_by_date.get(dkey9, 0) + float(pnl9) * rate9
                tax9 = {"sold": dkey9, "sym": gx["sym"], "ticker": gx["sym"], "ex": "유동성(DEX LP) · 스테이블 전환",
                        "qty": _f(qi, 4), "acq": _f(ci, 2), "disp": _f(pi, 2), "fee": 0, "rate": round(rate9, 4), "rateSrc": rsrc9,
                        "_acq": float(ci), "_disp": float(pi), "_qty": float(qi)}
                lpx.tax_krw_acq(tax9, gx, fl9, ci, ki, rate9, dkey9)
                lpx.tax_rows.append(tax9)
                fl9["sold"] += qi
                fl9["sold_dates"].append(dkey9)
                fl9["proceeds"] = fl9.get("proceeds", Decimal(0)) + pi
                fl9["proceeds_krw"] = fl9.get("proceeds_krw", Decimal(0)) + lpx.krw_of(pi, ts9)
                lpx.ev(fl9, ts9, "LP 전환 매도", f"{lpx.lp_label(d['bx'])} · 풀 안에서 스테이블로 전환된 원금(= 매도 · 실현 "
                   + f"{'+' if pnl9 >= 0 else '−'}${abs(float(pnl9)):,.2f})",
                   f"{float(qi):,.4f}".rstrip("0").rstrip("."), f"${float(pi):,.2f}", txh9, un=lpx._un(qi, pi))
                fl9["events"][-1]["_tax"] = tax9
                if d.get("_cp") and d["fk"] > 0:
                    fs9x = float(qi / d["fk"])
                    cmx = {k9: [v9[0] * fs9x, v9[1] * fs9x] for k9, v9 in d["_cp"].items()}
                    tcx = sum(v9[1] for v9 in cmx.values())
                    for v9 in cmx.values():
                        v9[1] = v9[1] * float(ci) / tcx if tcx > 0 else 0.0
                    fl9["events"][-1]["_cmp"] = lpx.cp_emit(cmx, 0, qi, ci)
            qr = qx - qi
            if qr > Decimal("0.000001") or qi <= 0:
                fl9["lpconv"] = fl9.get("lpconv", Decimal(0)) + qr
                lpx.ev(fl9, ts9, "LP 전환", f"{lpx.lp_label(d['bx'])} · 풀 안에서 다른 자산으로 전환된 원금",
                   f"{float(qr):,.4f}".rstrip("0").rstrip("."), f"${float(bk - ci):,.2f}", txh9, un=lpx._un(qr, bk - ci))
            if gx["qty_known"] + gx["qty_unknown"] <= Decimal("0.000001"):
                gx["cur"] = None
        realized9 -= B_rent
        for x in acq9:
            gx = lpx.gstate(x)
            qx = lpx.sb._norm(x)
            if qx <= 0:
                continue
            lpx.cp_sync(gx)
            lpx.cb.snapshot(gx, ts9, qx)
            gx["risk_allow"] = True
            flow = lpx.flow_of(gx, ts9, chain9)
            qsx = f"{float(qx):,.4f}".rstrip("0").rstrip(".")
            b9["acq"][gx["sym"]] = b9["acq"].get(gx["sym"], Decimal(0)) + qx
            if no_dep:
                if gx["is_stable"]:
                    lpx.cb.acquire(gx, qx, qx)
                else:
                    lpx.cb.add_unknown(gx, qx)
                    cr9 = lpx.cur_row[0]
                    lpx.cur_row[0] = x
                    try:
                        lpx.note_unk(gx, ts9, f"LP 회수 · 예치 기록 없음(수집 창 이전 예치) · {lpx.lp_label(b9)}", qx, txh9, chain9=chain9)
                    finally:
                        lpx.cur_row[0] = cr9
                flow["bought"] += qx
                lpx.ev(flow, ts9, "LP 회수", f"{lpx.lp_label(b9)} · 예치 기록 없음(원가 미상)", qsx, "—", txh9)
                lpx.lp_event(b9, ts9, "유동성 회수", f"{CHAIN_NAME.get(chain9, chain9)} · {lpx.lp_label(b9)} · 예치 기록 없음",
                         f"{qsx} {gx['sym']}", "—", txh9)
                continue
            c = cost_of.get(x["posting_id"], Decimal(0))
            kq = qx * k9 if disp9 else qx
            uq = qx - kq
            lpx.cb.acquire(gx, kq, c)
            if uq > EPS:
                lpx.cb.add_unknown(gx, uq)
                lpx.note_unk(gx, ts9, f"LP 전환 취득 · 원가미상 원금분 · {lpx.lp_label(b9)}", uq, txh9, chain9=chain9, fs9=0)
            flow["bought"] += qx; flow["cost"] += c
            if disp9 and not gx["is_stable"] and B > 0:
                flow["cost_krw"] += sum(((d["krw"] if (d["krw"] is not None and not d["g"]["is_stable"]) else lpx.krw_of(d["bk"], ts9))
                                         for d in dinfo), Decimal(0)) * c / B
            else:
                flow["cost_krw"] += lpx.krw_of(c, ts9, x)
            rw9 = bool(lpi9.get("via")) and not disp9
            rn9 = (not disp9) and int(x["asset_id"]) in rent9
            how = ("스테이블 수령 · 액면 원가(스테이블로 바뀐 전환 원금 = 매도 실현)" if (disp9 and sale9 and gx["is_stable"]) else
                   "풀 전환가 · 전환 원금 원가 승계" if disp9 else
                   "계정 임대료 환급(수익 아님 · 원가 0)" if rn9 else
                   (("스테이킹 리워드(시가)" if rw9 else "수수료 수익(시가)") if x["cost_usd"] is not None
                    else ("스테이킹 리워드(시세 없음 · 원가 0)" if rw9 else "수수료(시세 없음 · 원가 0)")))
            kname = "LP 전환 매수" if disp9 else ("LP 임대료 환급" if rn9 else ("LP 리워드 수령" if rw9 else "LP 수수료 수령"))
            unit9 = f" · 개당 ${float(c / qx):,.6g}" if qx > 0 and c > 0 else ""
            lpx.ev(flow, ts9, kname, f"{lpx.lp_label(b9)} · {how}{unit9}", qsx, f"${float(c):,.2f}", txh9, un=lpx._un(qx, c))
            lpx.lp_event(b9, ts9, kname, f"{CHAIN_NAME.get(chain9, chain9)} · {lpx.lp_label(b9)} · {how}",
                     f"{qsx} {gx['sym']}", f"${float(c):,.2f}", txh9)
        gain9 = realized9 + income9
        if abs(gain9) >= Decimal("0.005"):
            lpx.realized_by_date[dkey9] = lpx.realized_by_date.get(dkey9, 0) + float(gain9)
            b9["rbd"][dkey9] = b9["rbd"].get(dkey9, Decimal(0)) + gain9
            rt9x, rsrc9x = lpx.fxb.rate_src(ts9)
            lpx.realized_krw_by_date[dkey9] = lpx.realized_krw_by_date.get(dkey9, 0) + float(gain9) * rt9x
            b9["rbdk"][dkey9] = b9["rbdk"].get(dkey9, 0.0) + float(gain9) * rt9x
            b9["realized"] += realized9
            b9["income"] += income9
            lpx.tax_rows.append({"sold": dkey9, "sym": b9.get("pool") or lpx.lp_label(b9), "ticker": "LP",
                             "ex": "유동성(DEX LP)" if disp9 else ("유동성 리워드" if lpi9.get("via") else "유동성 수수료"),
                             "qty": _f(float(sum((-lpx.sb._norm(x) for x in disp9), Decimal(0))), 4) if disp9 else 0,
                             "acq": _f(float(B), 2) if disp9 else _f(float(B_rent), 2),
                             "disp": _f(float(k9 * M if disp9 else income9), 2), "fee": 0, "rate": round(rt9x, 4), "rateSrc": rsrc9x,
                             "_acq": float(B) if disp9 else float(B_rent), "_disp": float(k9 * M if disp9 else income9),
                             **({} if disp9 else {"tk": "inc"})})
        if disp9 and B >= Decimal("0.005"):
            lpx.lp_event(b9, ts9, "LP 전환", f"{CHAIN_NAME.get(chain9, chain9)} · {lpx.lp_label(b9)} · 원금 전환 "
                     + " + ".join(conv_txt) + (f" · 손익 {'+' if realized9 >= 0 else ''}${float(realized9):,.2f}" if abs(realized9) > EPS else "")
                     + (f" · 스테이블 전환 실현 {'+' if st_real9 >= 0 else '−'}${abs(float(st_real9)):,.2f}(코인 카드)" if sale9 else ""),
                     "—", f"${float(B):,.2f}", txh9)
