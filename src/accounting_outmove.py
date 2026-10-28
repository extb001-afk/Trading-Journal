from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

import accounting_util
import calcguard
import logs
import flow_trace
import flowev
import outflow_match
import salelink
import spamguard
from view_common import CHAIN_NAME
from view_common import EPS
from timeutil import KST
from view_common import OF_BASIS_KO

log = logging.getLogger('tj-web')


class OutMove:

    def __init__(omx, px, *, _un, movein, fns):
        omx.px = px
        omx.sb = px.sb
        omx._ro = movein.ro
        omx._un = _un
        omx.br_transit = movein.br_transit
        omx.cv_label = fns.cv_label
        omx.ever_in = movein.ever_in
        omx.ex_transit = movein.ex_transit
        omx.extra_ev = fns.extra_ev
        omx.extra_events = px.books.extra_events
        omx.fs_on = px.ctx.fs_on
        omx.fxdep_transit = movein.fxdep_transit
        omx.my_all9 = movein.my_all
        omx.now = px.ctx.now
        omx.of_bridge = movein.of_bridge
        omx.of_dec9 = movein.of_dec
        omx.of_match = movein.of_match
        omx.of_noauto = movein.of_noauto
        omx.rt_back = movein.rt_back
        omx.rt_same = movein.rt_same
        omx.rt_transit = movein.rt_transit
        omx.sale_bid9 = movein.sale_bid
        omx.signer9 = movein.signer
        omx.up_dep_uid_ts = movein.up_dep_uid_ts
        omx.up_win_t0 = movein.up_win_t0
        omx.cb = px.cb

    def out_move(omx, r9, g9, q9, ts9, chain9, txh9):
        sale9 = False
        srf9 = False
        loc9 = r9["location"] or ""
        dest9 = loc9.split(":", 2)[2] if loc9.count(":") >= 2 else "?"
        t9n = (txh9 or "").lower() if (txh9 or "").startswith("0x") else txh9
        o9 = omx.px.slx.ob.setdefault(dest9, {"chains": set(), "first": ts9, "last": ts9, "txs": set(), "tokens": {}, "list": [],
                                   "auto": None})
        o9["chains"].add(chain9)
        o9["first"] = min(o9["first"], ts9)
        o9["last"] = max(o9["last"], ts9)
        o9["txs"].add(txh9)
        for l0 in ((omx._ro.get((r9["source_ns"], r9["source_id"])) or {}).get("loc") or ()):
            p0 = str(l0).split(":")
            if len(p0) >= 3 and p0[2]:
                o9.setdefault("from_w", set()).add("w:" + p0[2])
        o9.setdefault("txsyms", {}).setdefault(txh9, set()).add(g9["sym"])
        usd_send = Decimal(r9["cost_usd"]) if r9["cost_usd"] is not None else None
        mc9, mk9, mu9 = omx.px.cpx.consume(g9, q9)
        cp_o9 = omx.px.cpx.cp_last[0]
        kr9 = omx.px.kpx.krw_took(mc9, ts9)
        kc9r, kk9r = omx.px.kpx.krw_rec(mc9)
        fk9r = omx.px.fsx.fs_rec()
        stl9r = omx.px.kpx.stl_out(kc9r)
        o9.setdefault("sends", []).append((int(ts9), g9["gid"], usd_send, (mk9 + mu9) if g9["gid"] in omx.ever_in else Decimal(0),
                                           bool(r9["kind"] == "native" or g9["is_stable"]),
                                           Decimal(str(r9["cost_krw"])) if r9["cost_krw"] is not None else None, omx.sb._of_key(r9),
                                           omx.sb._of_asset(r9), str(r9["qty_base"]), False))
        omx.cb.snapshot(g9, ts9, -q9)
        tk9 = o9["tokens"].setdefault(g9["sym"], {"qty": Decimal(0), "cost": Decimal(0), "usd_send": Decimal(0),
                                                   "usd_send_known": True, "gid": g9["gid"], "unknown": Decimal(0),
                                                   "held": Decimal(0), "stable": bool(g9["is_stable"])})
        tk9["qty"] += q9
        tk9["held"] += (mk9 + mu9) if g9["gid"] in omx.ever_in else Decimal(0)
        tk9["cost"] += mc9
        tk9["unknown"] += mu9 + max(Decimal(0), q9 - (mk9 + mu9))
        if usd_send is None:
            tk9["usd_send_known"] = False
        else:
            tk9["usd_send"] += usd_send
            o9["wusd"] = o9.get("wusd", 0.0) + float(usd_send)
            dk9 = datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d")
            wd9 = o9.setdefault("wdays", {})
            wd9[dk9] = wd9.get(dk9, 0.0) + float(usd_send)
        s9o = omx.signer9.get((r9["source_ns"], r9["source_id"]))
        sg9o = (None if not s9o or spamguard.snapshot_synth(s9o[1], s9o[2]) or not s9o[0]
                else spamguard.signer_mine(*s9o, omx.my_all9))
        li9 = omx.sb._of_list_add(o9, {"ts": int(ts9), "t": datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d %H:%M"),
                                     "chain": chain9, "tx": txh9, "sym": g9["sym"], "qty": float(q9),
                                     "usdAtSend": float(usd_send) if usd_send is not None else None, "costUsd": float(mc9),
                                     "signed": sg9o, "key": omx.sb._of_key(r9)})
        qs9 = f"{q9:,.4f}".rstrip("0").rstrip(".")
        ex_fx = omx.px.slx.fx_dep_tx.get(t9n) or omx.px.slx.fx_dep_tx.get(txh9)
        u_up = omx.px.slx.up_dep_by_tx.get(t9n) or omx.px.slx.up_dep_by_tx.get(txh9)
        am9 = omx.of_match.get(r9["posting_id"])
        if dest9 in omx.of_noauto:
            ex_fx = u_up = am9 = None
        elif am9 and not (ex_fx or u_up):
            if am9["ex"] == "upbit":
                u_up = am9.get("uuid") or "addr"
            else:
                ex_fx = am9["ex"]
        basis9 = (am9 or {}).get("basis") or "txid"
        bm9 = None if (ex_fx or u_up or dest9 in omx.of_noauto) else omx.of_bridge.get(r9["posting_id"])
        if g9["gid"] in omx.ever_in:
            o9.setdefault("rtx", set()).add(txh9)
        if bm9:
            o9.setdefault("mtx", set()).add(txh9)
            o9.setdefault("basis", set()).add("bridge")
            o9["musd"] = o9.get("musd", 0.0) + (float(usd_send) if usd_send is not None and g9["gid"] in omx.ever_in else 0.0)
            arr9 = {"basis": "bridge", "chain": bm9["chain"], "tx": bm9["tx"], "wallet": bm9.get("wallet") or "",
                    "sym": bm9["sym"], "qty": float(bm9["qty"]), "dt": int(bm9["ts"] - ts9)}
            o9.setdefault("arrivals", []).append(dict(arr9, ts=int(bm9["ts"]), sentSym=g9["sym"], sentQty=float(q9)))
            if li9 is not None:
                li9["match"] = arr9
        elif ex_fx or u_up:
            if basis9 in ("txid", "amount_time", "hop_split"):
                g9["risk_allow"] = True
            o9.setdefault("mtx", set()).add(txh9)
            o9.setdefault("basis", set()).add(basis9)
            o9["musd"] = o9.get("musd", 0.0) + (float(usd_send) if usd_send is not None and g9["gid"] in omx.ever_in else 0.0)
            if li9 is not None:
                li9["match"] = {"basis": basis9, "exchange": omx.px.ofx.fx_name.get(ex_fx, ex_fx) if ex_fx else "업비트"}
        if ex_fx:
            e5 = omx.fxdep_transit.setdefault((t9n, g9["sym"]), {"qty": Decimal(0), "cost": Decimal(0), "known": Decimal(0),
                                                              "unknown": Decimal(0), "left": Decimal(0), "gid": g9["gid"],
                                                              "sym": g9["sym"], "ex": ex_fx})
            e5["ts"] = max(int(e5.get("ts") or 0), int(ts9 or 0))
            e5["qty"] += q9; e5["cost"] += mc9; e5["known"] += mk9
            e5["krw"] = e5.get("krw", Decimal(0)) + kr9
            e5["kc"] = e5.get("kc", Decimal(0)) + kc9r; e5["kk"] = e5.get("kk", Decimal(0)) + kk9r
            e5["fk"] = e5.get("fk", Decimal(0)) + fk9r
            if stl9r:
                e5.setdefault("_stl", []).extend(stl9r)
            e5.setdefault("_src", []).append((r9["posting_id"], 1.0))
            e5["_cmp"] = accounting_util.cp_merge(e5.get("_cmp") or {}, cp_o9)
            e5.setdefault("cycs", []).append((g9["cur"], q9, mc9))
            e5["unknown"] += mu9 + max(Decimal(0), q9 - (mk9 + mu9))
            if not (basis9 == "address" and not (am9 or {}).get("uuid") and omx.now - float(ts9) > outflow_match.WIN_AFTER):
                e5["left"] += q9
            o9["auto"] = ("exchange", omx.px.ofx.fx_name.get(ex_fx, ex_fx), ex_fx)
            d9 = (f"{CHAIN_NAME.get(chain9, chain9)} → {dest9[:6]}…{dest9[-4:]} → {omx.px.ofx.fx_name.get(ex_fx, ex_fx)} 입금 {len(am9.get('uuids') or [])}건"
                  if basis9 == "hop_split" else f"{CHAIN_NAME.get(chain9, chain9)} → {omx.px.ofx.fx_name.get(ex_fx, ex_fx)} 입금") \
                + f" ({OF_BASIS_KO.get(basis9, basis9)} 자동 매칭 · 원가 이관)"
        elif u_up and basis9 == "hop_split" and am9.get("amts"):
            amts9 = [Decimal(str(a)) for a in am9["amts"]]
            tot9 = sum(amts9, Decimal(0))
            unk9h = mu9 + max(Decimal(0), q9 - (mk9 + mu9))
            for a9h in amts9:
                f9h = a9h / tot9 if tot9 > 0 else Decimal(0)
                omx.ex_transit.setdefault(txh9, []).append(
                    {"gid": g9["gid"], "sym": g9["sym"], "qty": q9 * f9h, "cost": mc9 * f9h, "krw": kr9 * f9h, "kc": kc9r * f9h, "kk": kk9r * f9h, "fk": fk9r * f9h,
                     "_stl": [[x9[0], x9[1]] + [v9 * float(f9h) for v9 in x9[2:]] for x9 in stl9r], "known": mk9 * f9h,
                     "unknown": unk9h * f9h, "raw_sym": (r9["symbol"] or "").upper(), "credited": True, "used": False, "split": True,
                     "_src": [(r9["posting_id"], float(f9h))], "_cmp": accounting_util.cp_merge({}, cp_o9, float(f9h))})
            omx.px.slx.diag["ex_out_cost"] += mc9
            omx.px.slx.diag["ex_out_n"] += 1
            o9["auto"] = ("exchange", "업비트", "upbit")
            d9 = (f"{CHAIN_NAME.get(chain9, chain9)} → {dest9[:6]}…{dest9[-4:]} → 업비트 입금 {len(amts9)}건 "
                  f"({OF_BASIS_KO.get(basis9, basis9)} 자동 매칭 · 원가 이관)")
        elif u_up:
            omx.ex_transit.setdefault(txh9, []).append(
                {"gid": g9["gid"], "sym": g9["sym"], "qty": q9, "cost": mc9, "krw": kr9, "kc": kc9r, "kk": kk9r, "fk": fk9r, "_stl": stl9r, "known": mk9,
                 "unknown": mu9 + max(Decimal(0), q9 - (mk9 + mu9)), "raw_sym": (r9["symbol"] or "").upper(),
                 "credited": not (u_up == "addr" and omx.now - float(ts9) <= outflow_match.WIN_AFTER), "used": False, "ts": int(ts9 or 0),
                 "cyc": g9["cur"], "_src": [(r9["posting_id"], 1.0)], "_cmp": accounting_util.cp_merge({}, cp_o9)})
            omx.px.slx.diag["ex_out_cost"] += mc9
            omx.px.slx.diag["ex_out_n"] += 1
            o9["auto"] = ("exchange", "업비트", "upbit")
            ut9 = omx.up_dep_uid_ts.get(u_up) if isinstance(u_up, str) else None
            if ut9 is not None and omx.up_win_t0 is not None and ut9 < omx.up_win_t0 - 60:
                o9["prewin"] = o9.get("prewin", 0) + 1
                d9 = f"{CHAIN_NAME.get(chain9, chain9)} → 업비트 입금 ({OF_BASIS_KO.get(basis9, basis9)} 자동 매칭 · 창 이전 입금 · 원가 이관 없음)"
            else:
                d9 = f"{CHAIN_NAME.get(chain9, chain9)} → 업비트 입금 ({OF_BASIS_KO.get(basis9, basis9)} 자동 매칭 · 원가 이관)"
        elif bm9:
            bt_q, bt_k, bt_u = q9, mk9, mu9 + max(Decimal(0), q9 - (mk9 + mu9))
            aq9 = Decimal(str(bm9.get("qty") or 0))
            if aq9 > 0 and q9 > 0 and outflow_match.family(bm9.get("sym")) != outflow_match.family(g9["sym"]):
                r9x = aq9 / q9
                bt_q, bt_k, bt_u = aq9, mk9 * r9x, bt_u * r9x
            omx.br_transit[bm9["key"]] = {"sym": g9["sym"], "qty": bt_q, "ts": ts9, "cost": mc9, "known": bt_k,
                                      "unknown": bt_u, "left": bt_q, "gid": g9["gid"], "_src": [(r9["posting_id"], 1.0)], "_cmp": accounting_util.cp_merge({}, cp_o9),
                                      "krw": kr9, "kc": kc9r, "kk": kk9r, "fk": fk9r, "_stl": stl9r, "id_link": bool(bm9.get("id_link"))}
            if bt_q is aq9:
                omx.br_transit[bm9["key"]]["_cv"] = {"from": omx.cv_label(cp_o9, g9["sym"]), "ratio": float(r9x)}
            d9 = (f"{CHAIN_NAME.get(chain9, chain9)} → 브릿지 → 내 {CHAIN_NAME.get(bm9['chain'], bm9['chain'])} 지갑 "
                  f"(자동 매칭 · {max(0, int(bm9['ts'] - ts9)) // 60}분 뒤 도착 · 원가 이관)")
        elif (chain9, str(txh9 or "").lower(), dest9) in omx.sale_bid9 and dest9 not in omx.of_noauto:
            sale9 = True
            lb9 = omx.sale_bid9[(chain9, str(txh9 or "").lower(), dest9)]
            o9.setdefault("mtx", set()).add(txh9)
            o9.setdefault("basis", set()).add("sale")
            o9["musd"] = o9.get("musd", 0.0) + (float(usd_send) if usd_send is not None and g9["gid"] in omx.ever_in else 0.0)
            o9["auto"] = ("sale", "토큰 세일 입찰", None)
            if li9 is not None:
                li9["match"] = {"basis": "sale", "exchange": "토큰 세일 입찰", "lot": lb9["id"]}
            d9 = f"{CHAIN_NAME.get(chain9, chain9)} → 토큰 세일 입찰 ({lb9['label']} · 원가는 수령 토큰으로 이어짐)"
            rb9s = [e9 for e9 in omx.px.slx.sale_rf_bid.get((chain9, str(txh9 or "").lower()), ())
                    if e9["auction"] == dest9 and (r9["kind"] == "native" if not e9["cur"]
                                                   else (r9["kind"] == "token" and str(r9["address"] or "").lower() == e9["cur"]))]
            am9s = sum((e9["amt"] for e9 in rb9s), Decimal(0))
            un9s = mu9 + max(Decimal(0), q9 - (mk9 + mu9))
            for e9 in rb9s:
                sh9 = e9["amt"] / am9s if am9s > 0 else Decimal(1) / len(rb9s)
                p9 = e9["pool"] = e9["pool"] or {"qty": Decimal(0), "cost": Decimal(0), "known": Decimal(0), "unknown": Decimal(0),
                                                 "krw": Decimal(0), "left": Decimal(0), "_cmp": {}}
                p9["qty"] += q9 * sh9; p9["left"] += q9 * sh9; p9["cost"] += mc9 * sh9; p9["known"] += mk9 * sh9
                p9["unknown"] += un9s * sh9; p9["krw"] += kr9 * sh9
                p9["kc"] = p9.get("kc", Decimal(0)) + kc9r * sh9
                p9["kk"] = p9.get("kk", Decimal(0)) + kk9r * sh9
                p9["_cmp"] = accounting_util.cp_merge(p9["_cmp"], cp_o9, float(sh9))
            try:
                omx.px.slx.sale_pay_take(r9, g9, q9, ts9, chain9, txh9, dest9, mc9, mk9, cp_o9)
            except Exception as e9:   # noqa: BLE001 [optional]
                calcguard.swallowed("view_b_replay:ReplayMixin._build_replay.out_move[sale_pay_take]", e9)
                log.warning("토큰 세일 사용분 처분 재료 실패(이 입찰 종전 경로): %s", logs.safe_err(e9)[:160])
        else:
            if omx.px.slx.sale_rf_bid and dest9 not in omx.of_noauto:
                try:
                    srf9 = omx.px.slx.sale_rf_load(r9, g9, q9, chain9, txh9, dest9, mc9, mk9, mu9, kr9, cp_o9)
                except Exception as e9:   # noqa: BLE001 [fallback]
                    calcguard.swallowed("view_b_replay:ReplayMixin._build_replay.out_move[srf9]", e9)
                    log.warning("토큰 세일 정산 환불 재료 실패(종전 경로): %s", logs.safe_err(e9)[:160])
                    srf9 = False
            if omx.px.of_pay_on and not srf9 and ("of:" + dest9) in omx.px.slx.sale_lot_by:
                try:
                    omx.px.slx.of_pay_take(r9, g9, q9, ts9, chain9, txh9, dest9, mc9, mk9, cp_o9, kr9)
                except Exception as e9:   # noqa: BLE001 [optional]
                    calcguard.swallowed("view_b_replay:ReplayMixin._build_replay.out_move[of_pay_take]", e9)
                    log.warning("수동 참가금 처분 재료 실패(종전 경로): %s", logs.safe_err(e9)[:160])
            unk9 = mu9 + max(Decimal(0), q9 - (mk9 + mu9))
            if unk9 <= EPS:
                c9t = f"원가 ${float(mc9):,.2f}"
            elif mc9 > 0:
                c9t = f"원가 ${float(mc9):,.2f} + 원가 미확인분"
            else:
                c9t = "원가 미확인"
            dl9 = {"multi": "여러 수령처", "?": "수령처 미상"}.get(dest9) or f"외부 {dest9[:8]}…{dest9[-4:]}"
            d9 = f"{CHAIN_NAME.get(chain9, chain9)} → {dl9} (보낸 내역 · {c9t} 유출)"
        if (r9["source_ns"], txh9) in omx.px.slx.rt_out and not (ex_fx or u_up or bm9 or sale9 or srf9):
            rt9 = omx.rt_transit.setdefault((r9["source_ns"], txh9, g9["gid"]), {"qty": Decimal(0), "cost": Decimal(0), "known": Decimal(0),
                                                                              "unknown": Decimal(0), "left": Decimal(0)})
            rt9["qty"] += q9; rt9["left"] += q9; rt9["cost"] += mc9; rt9["known"] += mk9
            rt9.setdefault("_src", []).append((r9["posting_id"], 1.0))
            rt9["_cmp"] = accounting_util.cp_merge(rt9.get("_cmp") or {}, cp_o9)
            rt9["krw"] = rt9.get("krw", Decimal(0)) + kr9
            rt9["kc"] = rt9.get("kc", Decimal(0)) + kc9r
            rt9["kk"] = rt9.get("kk", Decimal(0)) + kk9r
            rt9["fk"] = rt9.get("fk", Decimal(0)) + fk9r
            if stl9r:
                rt9.setdefault("_stl", []).extend(stl9r)
            rt9["unknown"] += mu9 + max(Decimal(0), q9 - (mk9 + mu9))
            d9 += " · 프로그램 예치(왕복 — 복귀 시 원가 복원)"
        elif (omx.fs_on and not (ex_fx or u_up or bm9 or sale9 or srf9) and not g9["is_stable"] and not g9.get("is_fiat")
              and dest9 not in ("multi", "?") and not flow_trace.is_burn(dest9)):
            rp9 = omx.px.fsx.ret_pool.setdefault(g9["gid"], {}).setdefault(dest9, {"qty": Decimal(0), "left": Decimal(0), "cost": Decimal(0), "known": Decimal(0),
                                                                        "unknown": Decimal(0), "krw": Decimal(0)})
            rp9["qty"] += q9; rp9["left"] += q9; rp9["cost"] += mc9; rp9["known"] += mk9; rp9["krw"] += kr9
            rp9["unknown"] += mu9 + max(Decimal(0), q9 - (mk9 + mu9))
            rp9["_cmp"] = accounting_util.cp_merge(rp9.get("_cmp") or {}, cp_o9)
        rb9 = omx.rt_back.get((r9["source_ns"], txh9)) if (dest9 in ("multi", "?") and (r9["source_ns"], txh9) in omx.rt_same
                                                       and not (ex_fx or u_up or bm9 or sale9) and dest9 not in omx.of_noauto) else None
        if rb9 and r9["asset_id"] in rb9[0]:
            if rb9[1]:
                o9.setdefault("mtx", set()).add(txh9)
            o9.setdefault("basis", set()).add("roundtrip")
            o9["musd"] = o9.get("musd", 0.0) + (float(usd_send) if usd_send is not None and g9["gid"] in omx.ever_in else 0.0)
            if li9 is not None:
                li9["match"] = {"basis": "roundtrip", "exchange": "프로그램 예치 왕복"}
            if g9["is_stable"]:
                d9 += " · 프로그램 예치(왕복 — 같은 지갑으로 전액 복귀)"
        if (li9.get("match") or {}).get("basis") in ("sale", "roundtrip") and ts9 >= omx.now - flowev.WINDOW:
            o9.setdefault("flow_matches", []).append(li9)
        g9["last_out"] = {"ex": None, "tx": txh9}
        a9 = f"${float(usd_send):,.2f}" if usd_send is not None and g9["gid"] in omx.ever_in else f"${float(mc9):,.2f}"
        un9 = omx._un(q9, usd_send if usd_send is not None and g9["gid"] in omx.ever_in else mc9)
        if g9["cur"] is not None:
            g9["cur"]["moved_qty"] += q9
            g9["cur"]["moved_cost"] += mc9
            lab9 = (omx.px.ofx.fx_name.get(ex_fx, ex_fx) if ex_fx else "업비트" if u_up
                    else f"{CHAIN_NAME.get(bm9['chain'], bm9['chain'])} 지갑" if bm9 else "토큰 세일 입찰" if sale9
                    else "프로그램 예치 (같은 지갑 복귀)" if (rb9 and r9["asset_id"] in rb9[0]) else None)
            accounting_util.mv_note(g9["cur"], lab9 or "외부 주소", q9, own=bool(lab9))
            if g9["is_stable"]:
                omx.extra_ev(ts9, g9, "외부 전송", d9, qs9, a9, txh9, un=un9)
                of_ev9 = omx.extra_events[-1]
            else:
                omx.px.cpx.ev(g9["cur"], ts9, "외부 전송", d9, qs9, a9, txh9, un=un9)
                of_ev9 = g9["cur"]["events"][-1]
            if g9["qty_known"] + g9["qty_unknown"] <= Decimal("0.000001"):
                g9["cur"] = None
        else:
            omx.extra_ev(ts9, g9, "외부 전송", d9, qs9, a9 if usd_send is not None and g9["gid"] in omx.ever_in else "—", txh9,
                     un=un9 if usd_send is not None and g9["gid"] in omx.ever_in else None)
            of_ev9 = omx.extra_events[-1]
        if not (ex_fx or u_up or bm9):
            try:
                if sale9:
                    of9 = {"c": "sale_auto", "nm": "토큰 세일 입찰", "lab": d9}
                else:
                    of9 = salelink.label(CHAIN_NAME.get(chain9, chain9), dest9, omx.of_dec9.get(dest9), c9t,
                                         system=(dest9 == "0x0000000000000000000000000000000000008001" and chain9 == "zksync"),
                                         roundtrip=bool(rb9 and r9["asset_id"] in rb9[0]))
                lw9 = sorted(str(l0).split(":", 2)[2] for l0 in ((omx._ro.get((r9["source_ns"], r9["source_id"])) or {}).get("loc") or ())
                             if str(l0).count(":") >= 2)
                of_ev9["of"] = dict(of9, a=dest9, ch=chain9, tx=str(txh9 or ""), w=lw9[0] if lw9 else "", **({} if sale9 else {"cost": c9t}))
            except Exception as e9:   # noqa: BLE001 [optional]
                calcguard.swallowed("view_b_replay:ReplayMixin._build_replay.out_move[sale9]", e9)
                log.debug("외부 전송 분류 표식 실패: %s", e9)
