from __future__ import annotations

import bisect
import logging
from datetime import datetime
from decimal import Decimal

import acct_norm
import calcguard
import common
import sale_match
import xfer_match
from view_common import CHAIN_NAME
from view_common import EPS
from view_common import KST
from view_common import OF_NATIVE_SYMS
from view_common import _f

log = logging.getLogger('tj-web')


class SaleBook:

    def __init__(slx, sb, _ro, _un, arr_tx_chain, be_done, be_take, be_tax, cp_add_map, cp_emit, cp_merge, cur_lab, cur_row, cur_src, diag, ev, flow_of, fs_last, fs_mark, fs_rec, fx_dep_tx, fx_name, fxb, krw_last, krw_mix, krw_of, krw_stl, note_unk, oa_last, ob, of_applied, of_cands, offc_sold, realized_by_date, realized_by_loc, realized_krw_by_date, ret_pool, rt_out, sale_links, sale_lot_by, sale_pay_bid, sale_pay_q, sale_pay_seq, sale_rf_bid, sale_rf_exit, sale_used, stable_fx_mark, tax_krw_acq, tax_rows, unk_tag, unverified, up_dep_by_tx, wd_raw9, wd_tr, xf_wd9):
        slx.sb = sb
        slx._ro = _ro
        slx._un = _un
        slx.arr_tx_chain = arr_tx_chain
        slx.be_done = be_done
        slx.be_take = be_take
        slx.be_tax = be_tax
        slx.cp_add_map = cp_add_map
        slx.cp_emit = cp_emit
        slx.cp_merge = cp_merge
        slx.cur_lab = cur_lab
        slx.cur_row = cur_row
        slx.cur_src = cur_src
        slx.diag = diag
        slx.ev = ev
        slx.flow_of = flow_of
        slx.fs_last = fs_last
        slx.fs_mark = fs_mark
        slx.fs_rec = fs_rec
        slx.fx_dep_tx = fx_dep_tx
        slx.fx_name = fx_name
        slx.fxb = fxb
        slx.krw_last = krw_last
        slx.krw_mix = krw_mix
        slx.krw_of = krw_of
        slx.krw_stl = krw_stl
        slx.note_unk = note_unk
        slx.oa_last = oa_last
        slx.ob = ob
        slx.of_applied = of_applied
        slx.of_cands = of_cands
        slx.offc_sold = offc_sold
        slx.realized_by_date = realized_by_date
        slx.realized_by_loc = realized_by_loc
        slx.realized_krw_by_date = realized_krw_by_date
        slx.ret_pool = ret_pool
        slx.rt_out = rt_out
        slx.sale_links = sale_links
        slx.sale_lot_by = sale_lot_by
        slx.sale_pay_bid = sale_pay_bid
        slx.sale_pay_q = sale_pay_q
        slx.sale_pay_seq = sale_pay_seq
        slx.sale_rf_bid = sale_rf_bid
        slx.sale_rf_exit = sale_rf_exit
        slx.sale_used = sale_used
        slx.stable_fx_mark = stable_fx_mark
        slx.tax_krw_acq = tax_krw_acq
        slx.tax_rows = tax_rows
        slx.unk_tag = unk_tag
        slx.unverified = unverified
        slx.up_dep_by_tx = up_dep_by_tx
        slx.wd_raw9 = wd_raw9
        slx.wd_tr = wd_tr
        slx.xf_wd9 = xf_wd9

    def of_cand(slx, r9, g9, q9, ts9, ref9, own9=False):
        try:
            if q9 <= 0 or g9.get("is_fiat") or own9:
                return False
            k9 = slx.sb._of_key(r9)
            sl9 = slx.sale_links.get(r9["posting_id"])
            slx.of_cands[k9] = {"key": k9, "pid": r9["posting_id"], "sym": g9["sym"], "qty": float(q9), "ts": int(ts9),
                            "stable": bool(g9["is_stable"]), "where": slx.cur_src[0] or "", "chain": r9["chain"] or "",
                            "ref": str(ref9 or ""), "ev": r9["event"], "gid": g9["gid"],
                            "sale": bool(sl9 and not sl9.get("manual")), "asset": slx.sb._of_asset(r9), "qb": str(r9["qty_base"])}
        except Exception as _cg9:
            calcguard.swallowed("view_b_replay:ReplayMixin._build_replay.of_cand", _cg9)
            pass
        return False

    def of_finalize(slx, lot9):
        if lot9.get("fin") is not None:
            return lot9["fin"]
        by9 = {}
        snd9 = list((slx.ob.get(lot9["manual"]) or {}).get("sends") or ())
        for w0 in slx.wd_tr:
            if w0["ts"] > lot9["t_first"]:
                continue
            p0 = slx.wd_raw9.get((w0["ex"], w0["uuid"])) or {}
            a0 = xfer_match.norm_addr(str(p0.get("address") or "").strip()) if str(p0.get("address") or "").strip() else ""
            if (a0 or slx.sb._wd_key(w0["ex"], w0["uuid"])) != lot9["manual"]:
                continue
            n0 = str(w0["sym"] or "").upper() in OF_NATIVE_SYMS
            if w0["stable"]:
                u0 = Decimal(w0["qty"])
            else:
                try:
                    px0 = float(slx.sb.px.candle_usd(str(w0["sym"] or ""), int(w0["ts"]) * 1000) or 0) if n0 else 0.0
                except Exception as _cg9:
                    calcguard.swallowed("view_b_replay:ReplayMixin._build_replay.of_finalize", _cg9)
                    px0 = 0.0
                u0 = Decimal(w0["qty"]) * Decimal(str(px0)) if px0 > 0 else None
            t0 = str(w0.get("txid") or "")
            sw0 = bool(t0 and (t0 in slx.arr_tx_chain or t0.lower() in slx.arr_tx_chain or t0 in slx.up_dep_by_tx
                               or t0 in slx.fx_dep_tx)) or w0["uuid"] in slx.xf_wd9
            snd9.append((int(w0["ts"]), w0["gid"], u0, w0.get("held") or Decimal(0), bool(w0["stable"] or n0), None,
                         slx.sb._wd_key(w0["ex"], w0["uuid"]), None, None, sw0))
        by_key9 = {x0[6]: x0 for x0 in snd9 if x0[6]}

        def fits9(x0, xe):
            return not isinstance(xe, dict) or (x0[7] == xe.get("asset") and x0[8] == (None if xe.get("qb") is None else str(xe.get("qb"))))
        excl9, miss9 = set(), False
        for xe in lot9.get("excl", ()):
            ke = str(xe.get("key") if isinstance(xe, dict) else xe)
            if ke in by_key9 and fits9(by_key9[ke], xe):
                excl9.add(ke)
                continue
            c0 = [x0 for x0 in snd9 if isinstance(xe, dict) and x0[6] and ke.count("|") >= 3 and x0[6].rsplit("|", 1)[0] == ke.rsplit("|", 1)[0]
                  and fits9(x0, xe)]
            if len(c0) == 1:
                excl9.add(c0[0][6])
            else:
                miss9 = True
        selfov9 = False
        for ts0, gid0, usd0, held0, ok0, krw0, key0, _as0, _qb0, sw0 in snd9:
            if ts0 > lot9["t_first"] or key0 in excl9:
                continue
            if sw0:
                selfov9 = True
            b9 = by9.setdefault(gid0, {"held": Decimal(0), "usd": Decimal(0), "krw": Decimal(0), "known": True, "ok": ok0})
            b9["held"] += held0
            if usd0 is None:
                b9["known"] = False
            else:
                b9["usd"] += usd0
                b9["krw"] += krw0 if krw0 is not None else slx.krw_of(usd0, ts0)
        inc9 = [b9 for b9 in by9.values() if b9["held"] > EPS]
        paid9 = sum((b9["usd"] for b9 in inc9), Decimal(0))
        if miss9:
            fin9 = ("excl_missing", paid9)
        elif selfov9:
            fin9 = ("self_overlap", paid9)
        elif not inc9:
            fin9 = ("no_cost", paid9)
        elif not all(b9["ok"] for b9 in inc9):
            fin9 = ("mixed", paid9)
        elif not all(b9["known"] for b9 in inc9) or paid9 - lot9["refund"] < 0:
            fin9 = ("no_cost", paid9)
        else:
            cost9 = paid9 - lot9["refund"]
            kt9 = max(Decimal(0), sum((b9["krw"] for b9 in inc9), Decimal(0)) - lot9["refund_krw"]) if cost9 > 0 else Decimal(0)
            fin9 = ("ok", paid9, cost9, kt9)
            lot9["desc"] = (f"토큰 세일 매수 · 보낸 내역 참가금 연결 · 참가 ${float(paid9):,.2f}"
                            + (f" · 환불 ${float(lot9['refund']):,.2f}" if lot9["refund"] > 0 else "")
                            + f" · 원가 ${float(cost9):,.2f}" + (f" (수령 {lot9['n']}건에 나눔)" if lot9["n"] > 1 else ""))
        lot9["fin"] = fin9
        if fin9[0] == "ok" and slx.of_pay_on:
            try:
                slx.of_pay_plan(lot9, [x0 for x0 in snd9 if x0[0] <= lot9["t_first"] and x0[6] not in excl9
                                   and (by9.get(x0[1]) or {}).get("held", Decimal(0)) > EPS], paid9)
            except Exception as e9:
                calcguard.swallowed("view_b_replay:ReplayMixin._build_replay.of_finalize", e9)
                lot9["pay_hold"] = "error"
                log.warning("수동 참가금 결제 코인 처분 실패(종전 경로): %s", common.safe_err(e9)[:160])
        return fin9

    def sale_book(slx, g9, r9, q9, ts9, chain9, ref9):
        sl9 = slx.sale_links.get(r9["posting_id"])
        lot9 = slx.sale_lot_by.get(sl9["lot"]) if sl9 else None
        if not lot9 or g9["is_stable"] or q9 <= 0:
            return None
        if sl9.get("unit") is None and not sl9.get("manual"):
            g9["risk_allow"] = True
            return None
        if sl9.get("manual"):
            fin9 = slx.of_finalize(lot9)
            if fin9[0] != "ok":
                return None
            sl9["cost"] = fin9[2] * sl9["wsh"]
            sl9["unit"] = sl9["cost"] / sl9["qty"] if sl9["qty"] > 0 else Decimal(0)
            sl9["unit_krw"] = fin9[3] * sl9["wsh"] / sl9["qty"] if sl9["qty"] > 0 else Decimal(0)
        take9 = min(q9, sl9["take"])
        c9 = take9 * sl9["unit"]
        g9["qty_known"] += take9
        g9["cost"] += c9
        g9["qty_unknown"] += q9 - take9
        slx.note_unk(g9, ts9, "토큰 세일 · 로트 잔량 초과분(원가 없음)", q9 - take9, ref9, chain9=chain9)
        g9["risk_allow"] = True
        fl9 = slx.flow_of(g9, ts9, chain9)
        fl9["bought"] += take9
        fl9["cost"] += c9
        pdk9 = lot9.get("_pay_basis") if lot9.get("_pay") and not sl9.get("manual") else None
        fl9["cost_krw"] += (take9 * sl9["unit_krw"] if sl9.get("unit_krw") is not None
                            else c9 * pdk9["krw"] / pdk9["usd"] if pdk9 and pdk9["usd"] > 0 else slx.krw_of(c9, ts9))
        slx.ev(fl9, ts9, "세일 매수", lot9.get("desc") or sale_match.desc(lot9), f"{take9:,.4f}".rstrip("0").rstrip("."), f"${float(c9):,.2f}", ref9,
           un=slx._un(take9, c9))
        if sl9.get("manual"):
            slx.of_applied[r9["posting_id"]] = (take9, c9)
        u9 = slx.sale_used.setdefault(lot9["id"], {"qty": Decimal(0), "cost": Decimal(0), "n": 0, "rows": []})
        u9["qty"] += take9 * (lot9.get("ratio") or 1) if sl9.get("rcpt") else take9
        u9["cost"] += c9
        u9["n"] += 1
        if len(u9["rows"]) < 20:
            u9["rows"].append({"t": datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d %H:%M"), "q": _f(take9, 4),
                               "ref": str(ref9 or ""), "where": slx.cur_src[0]})
        return take9, c9

    def sale_refund(slx, g9, r9, q9, ts9, chain9, txh9, flow9):
        loc9 = str(r9["location"] or "")
        if q9 <= EPS or not loc9.startswith("wallet:"):
            return None
        w9 = loc9.split(":")[-1].lower()
        cs9 = [e9 for e9 in slx.sale_rf_exit.get((chain9, str(txh9 or "").lower()), ())
               if e9["owner"] == w9 and e9["pool"] is not None and e9["pool"]["left"] > EPS and e9["ref"] - e9["used"] > EPS
               and (r9["kind"] == "native" if not e9["cur"] else (r9["kind"] == "token" and str(r9["address"] or "").lower() == e9["cur"]))]
        if not cs9:
            return None
        room9 = sum((min(e9["ref"] - e9["used"], e9["pool"]["left"]) for e9 in cs9), Decimal(0))
        took9 = min(q9, room9)
        if took9 <= EPS:
            return None
        inh9 = kn9 = un9 = kr9 = Decimal(0)
        for e9 in cs9:
            p9 = e9["pool"]
            tk9 = took9 * min(e9["ref"] - e9["used"], p9["left"]) / room9
            if tk9 <= 0:
                continue
            sc9 = min(Decimal(1), tk9 / p9["qty"]) if p9["qty"] > 0 else Decimal(0)
            inh9 += p9["cost"] * sc9
            kn9 += p9["known"] * sc9
            un9 += p9["unknown"] * sc9
            kr9 += p9["krw"] * sc9
            slx.cp_add_map(g9, p9.get("_cmp"), float(sc9))
            e9["used"] += tk9
            e9["bc"] = e9.get("bc", Decimal(0)) + p9["cost"] * sc9
            p9["left"] -= tk9
        rem9 = q9 - took9
        g9["qty_known"] += kn9
        g9["cost"] += inh9
        g9["qty_unknown"] += un9 + rem9
        g9["risk_allow"] = True
        flow9["bought"] += took9
        flow9["cost"] += inh9
        flow9["cost_krw"] += kr9
        if un9 + rem9 > EPS:
            slx.note_unk(g9, ts9, f"{CHAIN_NAME.get(chain9, chain9)} 토큰 세일 환불(입찰 때부터 원가 미상 몫 · 확인 환불량 초과분)",
                     un9 + rem9, txh9, chain9=chain9, unc9=rem9, fs9=rem9)
        slx.diag["sale_refund_n"] += 1
        slx.diag["sale_refund_q"] += took9
        slx.diag["sale_refund_cost"] += inh9
        return f" · 토큰 세일 환불 · 입찰 원가 복원 (${float(inh9):,.2f})"

    def sale_pay_take(slx, r9, g9, q9, ts9, chain9, txh9, dest9, mc9, mk9, cmp9):
        if q9 <= EPS:
            return
        es9 = [e9 for e9 in slx.sale_pay_bid.get((chain9, str(txh9 or "").lower()), ())
               if e9["auction"] == dest9 and e9["left"] > EPS and (r9["kind"] == "native" if not e9["cur"]
                                                                  else (r9["kind"] == "token" and str(r9["address"] or "").lower() == e9["cur"]))]
        wl9 = sorted((slx._ro.get((r9["source_ns"], r9["source_id"])) or {}).get("loc") or ())
        for e9 in es9:
            own9 = f"wallet:{chain9}:{e9['lot']['bidder']}"
            loc9w = next((l0 for l0 in wl9 if str(l0).lower() == own9), None) or (wl9[0] if len(wl9) == 1 else own9)
            pw9 = str(loc9w).split(":")
            take9 = min(q9 * e9["use"] / e9["txamt"] if e9["txamt"] > 0 else Decimal(0), e9["left"])
            if take9 <= EPS:
                continue
            e9["left"] -= take9
            f9 = take9 / q9
            ff9 = float(f9)
            p9 = {"g": g9, "fl": g9["cur"], "q": take9, "cost": mc9 * f9, "known": mk9 * f9, "unk": max(Decimal(0), q9 - mk9) * f9,
                  "cck": slx.krw_last[0] * f9 if slx.krw_last[0] is not None else None, "mix": slx.krw_mix[0] * f9, "fs": slx.fs_last[0] * f9,
                  "stl": ({"l": [(x9[0], x9[1], x9[2] * ff9, x9[3] * ff9, x9[4], x9[5] * ff9) for x9 in slx.krw_stl[0]["l"]], "o": slx.krw_stl[0]["o"]}
                          if slx.krw_stl[0] else None),
                  "oa": slx.oa_last[0] * f9, "cmp": {k9: [v9[0] * ff9, v9[1] * ff9] for k9, v9 in cmp9.items()} if cmp9 else None,
                  "usd": e9["usd"] * take9 / e9["use"], "ts": max(int(e9["ts"] or 0), int(ts9)), "row": r9,
                  "src": f"w:{pw9[2]}" if len(pw9) >= 3 and pw9[2] else "w:?", "lab": slx.cur_lab[0],
                  "loc": loc9w, "chain": chain9, "tx": e9["exit_tx"] or txh9, "lot": e9["lot"]}
            if p9["ts"] <= int(ts9):
                slx.sale_pay_emit(p9)
            else:
                slx.sale_pay_seq[0] += 1
                bisect.insort(slx.sale_pay_q, (p9["ts"], slx.sale_pay_seq[0], id(p9)))
                slx.sale_pay_q_d[id(p9)] = p9

    def sale_pay_flush(slx, t9):
        while slx.sale_pay_q and (t9 is None or slx.sale_pay_q[0][0] <= t9):
            _t9, _n9, k9 = slx.sale_pay_q.pop(0)
            try:
                slx.sale_pay_emit(slx.sale_pay_q_d.pop(k9))
            except Exception as e9:
                calcguard.swallowed("view_b_replay:ReplayMixin._build_replay.sale_pay_flush", e9)
                log.warning("토큰 세일 사용분 처분 출력 실패: %s", common.safe_err(e9)[:160])

    def sale_pay_emit(slx, e9):
        g9, ts9, q9 = e9["g"], e9["ts"], e9["q"]
        dk9 = acct_norm.iso_day(ts9)
        sv9 = (slx.cur_row[0], slx.cur_src[0], slx.cur_lab[0], slx.fs_last[0])
        slx.cur_row[0], slx.cur_src[0], slx.cur_lab[0] = e9["row"], e9["src"], e9["lab"]
        try:
            fl9 = e9["fl"]
            if fl9 is None:
                new9 = g9["cur"] is None
                fl9 = g9["cur"] or slx.flow_of(g9, ts9, e9["chain"])
                if new9 and g9["qty_known"] + g9["qty_unknown"] <= Decimal("0.000001"):
                    g9["cur"] = None
            else:
                fl9["moved_qty"] -= q9
                fl9["moved_cost"] -= e9["cost"]
                mv9 = (fl9.get("mv_to") or {}).get(e9.get("mvl", "토큰 세일 입찰"))
                if mv9:
                    mv9[0] = max(Decimal(0), mv9[0] - q9)
            fl9["paid"] = fl9.get("paid", Decimal(0)) + q9
            rate9, rsrc9 = slx.fxb.rate_src(e9["rts"], e9.get("rrow")) if e9.get("rts") else slx.fxb.rate_src(ts9)
            kn9, un9, cc9, pr9, lot9 = e9["known"], e9["unk"], e9["cost"], e9["usd"], e9["lot"]
            cmp9 = slx.cp_emit(e9["cmp"], un9, q9, cc9)
            tax9 = u9 = ud9 = None
            be9 = fsm9 = False
            pnl9 = Decimal(0)
            if kn9 > 0:
                pk9 = pr9 * kn9 / q9
                pnl9 = pk9 - cc9
                g9["realized"] += pnl9
                fl9["realized"] += pnl9
                fl9["pay_real"] = fl9.get("pay_real", Decimal(0)) + pnl9
                fl9["rbd"][dk9] = fl9["rbd"].get(dk9, Decimal(0)) + pnl9
                fl9["rbdk"][dk9] = fl9["rbdk"].get(dk9, 0.0) + float(pnl9) * rate9
                fl9.setdefault("rch", {}).setdefault(dk9, set()).add(slx.cur_lab[0] or "?")
                slx.realized_by_date[dk9] = slx.realized_by_date.get(dk9, 0) + float(pnl9)
                slx.realized_krw_by_date[dk9] = slx.realized_krw_by_date.get(dk9, 0) + float(pnl9) * rate9
                _rl9 = slx.realized_by_loc.setdefault((e9["loc"], dk9), [0.0, 0.0]); _rl9[0] += float(pnl9); _rl9[1] += float(pnl9) * rate9
                tax9 = {"sold": dk9, "sym": g9["sym"], "ticker": g9["sym"], "ex": "온체인(토큰 세일)", "qty": _f(kn9, 4), "acq": _f(cc9, 2),
                        "disp": _f(pk9, 2), "fee": 0, "rate": round(rate9, 4), "rateSrc": rsrc9,
                        "_acq": float(cc9), "_disp": float(pk9), "_qty": float(kn9)}
                oa9 = min(e9["oa"], kn9)
                if oa9 > EPS:
                    tax9["oa"] = _f(oa9, 4)
                    fl9["oa_sold"] = fl9.get("oa_sold", Decimal(0)) + oa9
                    fl9["oa_real"] = fl9.get("oa_real", Decimal(0)) + pnl9 * oa9 / kn9
                    slx.offc_sold[0] += 1
                    slx.offc_sold[1] += pnl9 * oa9 / kn9
                slx.tax_krw_acq(tax9, g9, fl9, cc9, e9["cck"], rate9, dk9, venue_loc=e9["loc"], mix9=e9["mix"])
                slx.fs_last[0] = e9["fs"]
                fsm9 = slx.fs_mark(g9, fl9, tax9, cmp9, kn9, pk9, cc9, rate9, dk9)
                if g9["is_stable"]:
                    slx.stable_fx_mark(tax9, cc9, False, stl9=e9["stl"], cck9=e9["cck"], mix9=e9["mix"], use9=f"{lot9.get('tsym') or lot9['sym']} 매수 대금")
                slx.tax_rows.append(tax9)
            if un9 > EPS and g9["is_stable"]:
                pass
            elif un9 > EPS and slx.be_take(g9["gid"], ts9, un9):
                pu9 = pr9 * un9 / q9
                be9 = True
                u9 = slx.be_done.setdefault(g9["gid"], {"sym": g9["sym"], "qty": Decimal(0), "proceeds": Decimal(0), "n": 0,
                                                    "first": dk9, "last": dk9, "sales": []})
                ud9 = {"qty": un9, "proceeds": pu9}
                u9["qty"] += un9
                u9["proceeds"] += pu9
                u9["n"] += 1
                u9["last"] = dk9
                u9["sales"].append(ud9)
                slx.be_tax.append((ud9, {"sold": dk9, "sym": g9["sym"], "ticker": g9["sym"], "ex": "온체인(토큰 세일) · 매수가=매도가",
                                     "qty": _f(un9, 4), "acq": 0, "disp": 0, "fee": 0, "rate": round(rate9, 4), "rateSrc": rsrc9, "be": 1,
                                     "_qty": float(un9)}))
                slx.tax_rows.append(slx.be_tax[-1][1])
            elif un9 > EPS:
                pu9 = pr9 * un9 / q9
                u9 = slx.unverified.setdefault(g9["gid"], {"sym": g9["sym"], "qty": Decimal(0), "proceeds": Decimal(0), "n": 0,
                                                       "last": dk9, "by_date": {}})
                u9["qty"] += un9
                u9["proceeds"] += pu9
                u9["n"] += 1
                u9["last"] = dk9
                ud9 = u9["by_date"].setdefault(dk9, {"qty": Decimal(0), "proceeds": Decimal(0)})
                ud9["qty"] += un9
                ud9["proceeds"] += pu9
                fu9 = fl9["ubd"].setdefault(dk9, [0, Decimal(0)])
                fu9[0] += 1
                fu9[1] += pu9
                ubq9 = fl9.setdefault("ubq", {})
                ubq9[dk9] = ubq9.get(dk9, Decimal(0)) + un9
            fl9.setdefault("pay_dates", []).append(dk9)
            fl9["paid_usd"] = fl9.get("paid_usd", Decimal(0)) + pr9
            ch9 = e9["chain"]
            slx.ev(fl9, ts9, "온체인 매도", (e9.get("evd") or f"{CHAIN_NAME.get(ch9, ch9)} · 토큰 세일 대금 지불 · {g9['sym']} → {lot9['sym']} "
               f"(입찰 사용분 · 경매 종료로 확정 · 대가 = 받은 토큰 원가)")
               + slx.unk_tag(kn9, un9, pr9, q9, g9["is_stable"], be9)
               + ((" · 원화 원가 일부 최초 인식 시가(그때 환율)" if g9["is_stable"] else " · 원가 일부 최초 인식 시가") if fsm9 else ""),
               f"{q9:,.4f}".rstrip("0").rstrip("."), f"${float(pr9):,.2f}", e9["tx"], un=slx._un(q9, pr9))
            fl9["events"][-1]["_pay"] = True
            fl9["events"][-1]["_ccapay"] = True
            fl9["events"][-1]["_tax"] = tax9 if tax9 is not None else (slx.be_tax[-1][1] if be9 and slx.be_tax else None)
            if cmp9 is not None:
                fl9["events"][-1]["_cmp"] = cmp9
            pd9 = lot9.setdefault("_pay", {"q": Decimal(0), "cost": Decimal(0), "usd": Decimal(0), "rz": Decimal(0), "krw": Decimal(0), "unk": Decimal(0), "n": 0})
            pd9["q"] += q9
            pd9["cost"] += cc9
            pd9["usd"] += pr9
            pd9["rz"] += pnl9
            pd9["unk"] += un9
            pd9["krw"] += pr9 * Decimal(str(rate9))
            pd9["n"] += 1
            slx.diag["sale_pay_n"] = slx.diag.get("sale_pay_n", 0) + 1
        finally:
            slx.cur_row[0], slx.cur_src[0], slx.cur_lab[0], slx.fs_last[0] = sv9

    def of_pay_take(slx, r9, g9, q9, ts9, chain9, txh9, dest9, mc9, mk9, cmp9, kr9):
        if q9 <= EPS or g9.get("is_fiat"):
            return
        if (r9["source_ns"], txh9) in slx.rt_out and not g9["is_stable"]:
            return
        wl9 = sorted((slx._ro.get((r9["source_ns"], r9["source_id"])) or {}).get("loc") or ())
        loc9w = wl9[0] if wl9 else f"wallet:{chain9}:?"
        pw9 = str(loc9w).split(":")
        slx.of_pay_cap.setdefault(dest9, {})[slx.sb._of_key(r9)] = {
            "g": g9, "fl": g9["cur"], "q": q9, "cost": mc9, "known": mk9, "unk": max(Decimal(0), q9 - mk9),
            "cck": slx.krw_last[0], "mix": slx.krw_mix[0], "fs": slx.fs_rec(), "stl": {"l": list(slx.krw_stl[0]["l"]), "o": slx.krw_stl[0]["o"]} if slx.krw_stl[0] else None,
            "oa": slx.oa_last[0], "cmp": dict(cmp9) if cmp9 else None, "ts": int(ts9), "row": r9, "rrow": r9,
            "krw": kr9,
            "src": f"w:{pw9[2]}" if len(pw9) >= 3 and pw9[2] else "w:?", "lab": slx.cur_lab[0], "loc": loc9w, "chain": chain9, "tx": txh9,
            "mvl": "외부 주소", "wd": False}

    def of_wd_take(slx, g9, r9, nq9, q09, mc9, mk9, pk9, fk9, oa9, cmp9, ts9, ex9, txid9):
        if nq9 <= EPS or g9.get("is_fiat"):
            return
        s9 = nq9 / q09 if q09 > 0 else Decimal(1)
        sf9 = float(s9)
        kl9, km9, ks9 = pk9
        slx.of_wd_cap[slx.sb._wd_key(ex9, r9["source_id"])] = {
            "g": g9, "fl": g9["cur"], "q": nq9, "cost": mc9, "known": mk9, "unk": max(Decimal(0), nq9 - mk9),
            "cck": kl9 * s9 if kl9 is not None else None, "mix": km9 * s9, "fs": fk9,
            "stl": {"l": [(x9[0], x9[1], x9[2] * sf9, x9[3] * sf9, x9[4], x9[5] * sf9) for x9 in ks9["l"]], "o": ks9["o"]} if ks9 else None,
            "oa": oa9, "cmp": dict(cmp9) if cmp9 else None, "ts": int(ts9), "row": r9, "rrow": None,
            "src": f"ex:{ex9}", "lab": slx.cur_lab[0], "loc": str(r9["location"] or f"exchange:{ex9}"), "chain": r9["chain"] or ex9,
            "tx": txid9 or r9["source_id"], "mvl": "온체인 주소" if txid9 else None, "wd": True, "ex": ex9}

    def of_pay_plan(slx, lot9, legs9, paid9):
        caps9 = []
        for x0 in legs9:
            k0 = str(x0[6] or "")
            c0 = slx.of_wd_cap.get(k0) if k0.startswith("wd:") else (slx.of_pay_cap.get(lot9["manual"]) or {}).get(k0)
            if c0 is None or x0[2] is None:
                lot9["pay_hold"] = "no_basis"
                return
            caps9.append((x0, c0))
        if not caps9 or paid9 <= 0:
            return
        gids9 = {c0["g"]["gid"] for _x, c0 in caps9}
        as9 = {("st", str(c0["g"]["sym"] or "").upper()) if c0["g"]["is_stable"] else ("g", c0["g"]["gid"]) for _x, c0 in caps9}
        rg9 = set(lot9.get("refund_assets") or ())
        f9 = Decimal(1)
        if lot9["refund"] > 0 and as9 & rg9:
            if not (as9 == rg9 and len(as9) == 1 and all(c0["g"]["is_stable"] for _x, c0 in caps9)):
                lot9["pay_hold"] = "mixed_refund"
                return
            f9 = max(Decimal(0), (paid9 - lot9["refund"]) / paid9)
        rp_cut9 = []
        for gid9 in gids9:
            rp9 = (slx.ret_pool.get(gid9) or {}).get(lot9["manual"])
            if rp9 is None:
                continue
            tq9 = sum((c0["q"] for c0 in (slx.of_pay_cap.get(lot9["manual"]) or {}).values() if c0["g"]["gid"] == gid9), Decimal(0))
            if rp9["qty"] + EPS < tq9:
                lot9["pay_hold"] = "returned"
                return
            cuts9 = [c0 for _x, c0 in caps9 if c0["g"]["gid"] == gid9 and not c0["wd"]]
            if cuts9:
                rp_cut9.append((rp9, cuts9))
        for rp9, cuts9 in rp_cut9:
            for k7, c7 in (("qty", "q"), ("cost", "cost"), ("known", "known"), ("unknown", "unk"), ("krw", "krw")):
                rp9[k7] = max(Decimal(0), rp9[k7] - sum((c0[c7] * f9 for c0 in cuts9), Decimal(0)))
            rp9["left"] = rp9["qty"]
            if rp9.get("_cmp"):
                for c0 in cuts9:
                    slx.cp_merge(rp9["_cmp"], c0.get("cmp"), -float(f9))
        sf9 = float(f9)
        n9 = 0
        for x0, c0 in caps9:
            e9 = dict(c0)
            for k7 in ("q", "cost", "known", "unk", "mix", "fs", "oa"):
                e9[k7] = c0[k7] * f9
            if e9["q"] <= EPS:
                continue
            e9["cck"] = c0["cck"] * f9 if c0["cck"] is not None else None
            e9["stl"] = ({"l": [(y9[0], y9[1], y9[2] * sf9, y9[3] * sf9, y9[4], y9[5] * sf9) for y9 in c0["stl"]["l"]], "o": c0["stl"]["o"]}
                         if c0["stl"] else None)
            e9["cmp"] = {k7: [v7[0] * sf9, v7[1] * sf9] for k7, v7 in c0["cmp"].items()} if c0["cmp"] else None
            e9["usd"] = x0[2] * f9
            e9["ts"] = max(int(lot9["t_first"]), int(c0["ts"]))
            e9["rts"] = int(c0["ts"])
            e9["lot"] = lot9
            where9 = slx.fx_name.get(c0["ex"], c0["ex"]) + " 출금" if c0["wd"] else CHAIN_NAME.get(c0["chain"], c0["chain"])
            e9["evd"] = (f"{where9} · 토큰 세일 대금 지불 · {c0['g']['sym']} → {lot9.get('tsym') or '받은 토큰'} "
                         f"(보낸 내역 참가금 연결 · 첫 토큰 수령으로 확정 · 대가 = 보낸 때 평가" + (" · 환불 뺀 사용분" if f9 < 1 else "") + ")")
            slx.sale_pay_emit(e9)
            n9 += 1
        slx.diag["of_pay_n"] = slx.diag.get("of_pay_n", 0) + n9

    def sale_rf_load(slx, r9, g9, q9, chain9, txh9, dest9, mc9, mk9, mu9, kr9, cp_o9):
        if q9 <= EPS:
            return False
        rb9s = [e9 for e9 in slx.sale_rf_bid.get((chain9, str(txh9 or "").lower()), ())
                if e9.get("solo") and e9["auction"] == dest9 and (r9["kind"] == "native" if not e9["cur"]
                                                                   else (r9["kind"] == "token" and str(r9["address"] or "").lower() == e9["cur"]))]
        if not rb9s:
            return False
        am9s = sum((e9["amt"] for e9 in rb9s), Decimal(0))
        un9s = mu9 + max(Decimal(0), q9 - (mk9 + mu9))
        for e9 in rb9s:
            sh9 = e9["amt"] / am9s if am9s > 0 else Decimal(1) / len(rb9s)
            p9 = e9["pool"] = e9["pool"] or {"qty": Decimal(0), "cost": Decimal(0), "known": Decimal(0), "unknown": Decimal(0),
                                             "krw": Decimal(0), "left": Decimal(0), "_cmp": {}}
            p9["qty"] += q9 * sh9; p9["left"] += q9 * sh9; p9["cost"] += mc9 * sh9; p9["known"] += mk9 * sh9
            p9["unknown"] += un9s * sh9; p9["krw"] += kr9 * sh9
            p9["_cmp"] = slx.cp_merge(p9["_cmp"], cp_o9, float(sh9))
        return True
