from __future__ import annotations
import acct_norm
import attfreeze
import histmark, logs, paths
import flowev
import histcurve
import os
import rabby
import ubfill
from datetime import datetime
from decimal import Decimal
from view_common import CHAIN_NAME
from view_common import DAYCLOSE_ON
from view_common import EPS
from view_common import STABLE_GROUPS
from view_fspin import _fs_pin_save
from view_fspin import kd_pin_save
from view_misc import _hist_kit_rows
from view_regroup import _daily_krw
from view_regroup import _stable_regroup_aliases
from view_xv import _xq_sets
import logging
import calcguard  # noqa: E402

log = logging.getLogger('tj-web')


def _ufc_of(xv9u):
    if not isinstance(xv9u, dict):
        return []
    o = [str(u) for u in xv9u["ufc"]] if isinstance(xv9u.get("ufc"), dict) else []
    for z in (xv9u["ufz"].values() if isinstance(xv9u.get("ufz"), dict) else ()):
        o.extend(str(u) for u in (z if isinstance(z, dict) else ()))
    return o


class DailyBuildMixin:

    def _build_daily(self, _bs9):
        (G, _bf_since, ask9, ca_all, coins, conn, debt_capg9, diag, ex_c9, ex_gid, fs_need, fs_pin_new, fs_sum, gid_pairs_all, hl_cash_syms9, hold_qty, live_px, lp_total, lpb, native_c9, now, ob, of_bridge, of_deps, of_match, of_sends, offc_dep, offc_on, offc_self_wd, offc_wd, outflows_out, override_px, pending_gids, quarantined, rate_fx, rb_debts, rb_net, rb_view, realized_by_date, rows, spoof_keys, stables, stake_inc, today_kst, uf_dl9, unv9, unv_fb9, unverified, wallet_label, x_fiat, x_ok, xf_links, xtra9, wdt_all,) = (_bs9["G"], _bs9["_bf_since"], _bs9["ask9"], _bs9["ca_all"], _bs9["coins"], _bs9["ctx"].conn, _bs9["debt_capg9"], _bs9["diag"], _bs9["ex_c9"], _bs9["ex_gid"], _bs9["fs_need"], _bs9["fs_pin_new"], _bs9["fs_sum"], _bs9["gid_pairs_all"], _bs9["hl_cash_syms9"], _bs9["hold_qty"], _bs9["live_px"], _bs9["lp_total"], _bs9["lpb"], _bs9["native_c9"], _bs9["ctx"].now, _bs9["ob"], _bs9["of_bridge"], _bs9["of_deps"], _bs9["of_match"], _bs9["of_sends"], _bs9["offc_dep"], _bs9["ctx"].offc_on, _bs9["offc_self_wd"], _bs9["offc_wd"], _bs9["outflows_out"], _bs9["override_px"], _bs9["pending_gids"], _bs9["quarantined"], _bs9["rate_fx"], _bs9["rb_debts"], _bs9["rb_net"], _bs9["rb_view"], _bs9["realized_by_date"], _bs9["rows"], _bs9["spoof_keys"], _bs9["stables"], _bs9["stake_inc"], _bs9["ctx"].today_kst, _bs9["uf_dl9"], _bs9["unv9"], _bs9["unv_fb9"], _bs9["unverified"], _bs9["wallet_label"], _bs9["x_fiat"], _bs9["x_ok"], _bs9["xf_links"], _bs9["xtra9"], _bs9["wdt_all"],)
        hl_cash9 = frozenset(gid9 for gid9, ex9 in ex_gid.items()
                             if ex9 == "hyperliquid" and str((G.get(gid9) or {}).get("sym") or "").upper() in hl_cash_syms9)
        try:
            self._hl_neg_mark(G, hl_cash9)
        except Exception as e9:   # noqa: BLE001 [optional]
            calcguard.swallowed("view_b_daily:DailyBuildMixin._build_daily[_hl_neg_mark#1]", e9)
            log.warning("Hyperliquid 음수 허용 그룹 장기 곡선 표식 실패(다음 빌드): %s", e9)
        try:
            lg9 = conn.execute("SELECT v FROM meta WHERE k='ext_rebuilt_at'").fetchone()
            led_gen9 = int(float(lg9[0])) if lg9 and lg9[0] else 0
        except Exception as _cg9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_b_daily:DailyBuildMixin._build_daily[_hl_neg_mark#2]", _cg9)
            led_gen9 = 0
        hl_marks9 = histmark.hist_late_read(conn)
        hl_pw9 = histmark.hist_late_pw(conn)
        try:
            mk9 = paths.state("backfill_done")
            try:
                mts9 = float(open(mk9).read().strip() or 0) if os.path.exists(mk9) else 0.0
            except (OSError, ValueError):
                mts9 = os.path.getmtime(mk9) if os.path.exists(mk9) else 0.0
            mrow9 = conn.execute("SELECT k, v FROM meta WHERE k='recon_done_upbit' OR k LIKE 'recon\\_done\\_exf\\_%' ESCAPE '\\'").fetchall()
            if isinstance((self.daily_px or {}).get("_xqb"), dict):
                xq9, xqb9 = _xq_sets(mrow9, {}, 0)[0], None
            else:
                fs9 = {str(e9): t9 for e9, t9 in conn.execute("SELECT exchange, MIN(observed_at) FROM raw_ex GROUP BY exchange").fetchall()}
                xq9, xqb9 = _xq_sets(mrow9, fs9, mts9)
        except Exception as e9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_b_daily:DailyBuildMixin._build_daily[_hl_neg_mark#3]", e9)
            log.warning("거래소 지문 읽기 실패(이번 빌드 종전대로): %s", e9)
            xq9, xqb9 = None, None
        self._xq9 = (xq9, xqb9)
        curve_G9 = G
        uf_inf9 = self.__dict__.get("_ub_fill_info") or {}
        uf_ts9 = int(uf_inf9.get("ts") or now)
        if uf_dl9:
            curve_G9 = dict(G)
            for (gid9, _l9), dq9 in sorted(uf_dl9.items()):
                g9 = curve_G9.get(gid9)
                if g9 is not None and dq9:
                    curve_G9[gid9] = dict(g9, qty_timeline=list(g9.get("qty_timeline") or ()) + [(uf_ts9, dq9)])
        krw_tl9 = float(uf_inf9.get("krw_tl") or uf_inf9.get("krw_st") or 0)
        xs9 = xtra9.get("xsrc")
        if krw_tl9 and isinstance(xs9, dict) and isinstance(xs9.get("tl"), dict) and xs9["tl"].get("ku") is not None:
            xs9 = xtra9["xsrc"] = dict(xs9, tl=dict(xs9["tl"], ku=sorted(list(xs9["tl"]["ku"]) + [(uf_ts9, krw_tl9)], key=lambda t9: t9[0])))
        if uf_inf9.get("ubf") and isinstance(xs9, dict) and isinstance(xs9.get("now"), dict) and isinstance(xs9["now"].get("ub"), dict):
            xtra9["xsrc"] = dict(xs9, now=dict(xs9["now"], ubf=[uf_ts9, dict(uf_inf9["ubf"])]))
        try:
            uu9 = set()
            for k9 in ("_live", "_live_ok"):
                uu9.update(_ufc_of((self.daily.get(k9) or {}).get("xv") if isinstance(self.daily.get(k9), dict) else None))
            for e9 in (self.daily_px or {}).values():
                if isinstance(e9, dict):
                    uu9.update(_ufc_of(e9.get("xv")))
                    uu9.update(_ufc_of((e9.get("partial") or {}).get("xv") if isinstance(e9.get("partial"), dict) else None))
            xs9 = xtra9.get("xsrc")
            if uu9 and isinstance(xs9, dict) and isinstance(xs9.get("now"), dict):
                def ts_uf9(pl9):
                    try:
                        return acct_norm.fill_ts(pl9) or datetime.fromisoformat(str(pl9["created_at"])).timestamp()
                    except (ValueError, TypeError, KeyError):
                        return None
                bk9 = ubfill.booked(conn, uu9, ts_uf9)
                ufp9 = {}
                for u9 in sorted(uu9):
                    b9 = bk9.get(u9)
                    if b9 is False or (isinstance(b9, dict) and b9.get("ts") is None):
                        ufp9[u9] = None
                    elif isinstance(b9, dict):
                        ufp9[u9] = float(min(p[0] for p in b9["parts"]) if b9.get("parts") else b9["ts"])
                    elif u9 in (uf_inf9.get("ufc") or {}) or any(u9 in z9 for z9 in (uf_inf9.get("ufz") or {}).values()):
                        ufp9[u9] = float(uf_ts9)
                xtra9["xsrc"] = dict(xs9, now=dict(xs9["now"], ufp=ufp9))
        except Exception as e9:   # noqa: BLE001 [optional]
            calcguard.swallowed("view_b_daily:DailyBuildMixin._build_daily[_hl_neg_mark#4]", e9)
            log.warning("업비트 체결 관측 경계 재료 실패(종전대로): %s", logs.safe_err(e9)[:160])
        if uf_inf9.get("stale_fill"):
            xtra9["ufd"] = 1
        daily = self._daily_series(curve_G9, today_kst, override_px, live_px,
                                   ca_gids=ca_all, ex_gids=set(ex_gid),
                                   skip_gids=quarantined, pending_gids=pending_gids, native_c=native_c9 | ex_c9,
                                   hold_qty=hold_qty, extra=xtra9, extra_ok=x_ok, now_ts=now, led_gen=led_gen9, hist_late=hl_marks9,
                                   led_pw=hl_pw9, late_after=(lambda pw9, t9, _c=conn: histmark.hist_late_after(_c, pw9, t9)),
                                   neg_ok=hl_cash9,
                                   debt_neg=debt_capg9,
                                   debt_moves=self._debt_redate_moves(conn),
                                   transit=[e9 for e9 in wdt_all if e9["state"] == "pending"],
                                   dep_transit=_bs9.get("dep_tr9") or (),
                                   stable_aliases=_stable_regroup_aliases(conn),
                                   day_close=(histcurve.DAYCLOSE.resolver(G, ca_all, ex_gid, native_c9 | ex_c9, override_px, gid_pairs_all,
                                                                          STABLE_GROUPS, now) if DAYCLOSE_ON else None),
                                   xq=xq9, xq_base=xqb9,
                                   inval=_bs9.get("daily_inval"))
        self._xq9 = (xq9, ((self.daily_px or {}).get("_xqb") or {}).get("xq", xqb9) if xq9 is not None else None)
        if fs_pin_new:
            _fs_pin_save(fs_pin_new)
        if (fs_sum.get("kd") or {}).get("pin_new"):
            kd_pin_save(fs_sum["kd"]["at"], fs_sum["kd"]["pin_new"])
        if DAYCLOSE_ON and fs_need:
            try:
                ask9 = {}
                for (sp9, iso9), (gid9, q9) in fs_need.items():
                    if gid9 in quarantined:
                        continue
                    a9 = ask9.setdefault(sp9, [set(), 0.0])
                    a9[0].add(iso9)
                    a9[1] = max(a9[1], float(q9) * float(live_px.get(gid9) or 0))
                for sp9, (ds9, w9) in ask9.items():
                    histcurve.DAYCLOSE.ask_old(sp9, ds9, w9, now)
                fs_sum["ask_old"] = {"specs": len(ask9), "days": sum(len(v9[0]) for v9 in ask9.values())}
            except Exception as e9:   # noqa: BLE001 [optional]
                calcguard.swallowed("view_b_daily:DailyBuildMixin._build_daily[ask9]", e9)
                log.warning("옛날 날 시세 요청 실패(다음 빌드): %s", type(e9).__name__)
        if DAYCLOSE_ON:
            histcurve.DAYCLOSE.kick()
        rb_dc9 = {}
        try:
            if rb_view is not None or os.path.exists(paths.state("rabby_daily.json")):
                tiso9 = today_kst.strftime("%Y-%m-%d")
                pw9 = {}
                if rb_view is not None:
                    for a9, wv9 in rb_view["wallets"].items():
                        pw9[a9] = round(wv9["only"] + wv9["onlyDebt"], 2)
                rb_note9 = rabby.daily_note(paths.state("rabby_daily.json"), tiso9, rb_net, now, per_wallet=pw9) if rb_view is not None \
                    else rabby.load_state(paths.state("rabby_daily.json"))
                rabby.daily_overlay(daily, rb_note9, tiso9, rb_net)
                rb_dc9 = rabby.day_values(rb_note9, [k9 for k9 in self.daily if len(str(k9)) == 10 and str(k9)[4] == "-" and str(k9) < tiso9],
                                          tiso9, rb_net)
        except Exception as e9:   # noqa: BLE001 [optional]
            calcguard.swallowed("view_b_daily:DailyBuildMixin._build_daily[rb_view]", e9)
            log.warning("Rabby 일별 보강 실패: %s", e9)
        offc_ids9 = frozenset()
        vflow_loc9 = None
        try:
            offc_ids9 = frozenset({(f"{e9}:withdraw", u9) for e9, u9 in offc_wd if offc_self_wd(e9, u9)}
                                  | {(f"{e9}:deposit", u9) for e9, u9 in offc_dep if e9 in offc_on})
            flows9 = self._daily_flows(conn, daily, G, today_kst, live_px, frozenset(quarantined), rate_fx, transit=wdt_all,
                                       offc_ids=offc_ids9)
            vflow_loc9 = getattr(self, "_venue_flow", None)
            for row9 in daily:
                fl9 = flows9.get(row9.get("date"))
                row9["flow"] = fl9[0] if fl9 else 0
                if fl9 and fl9[1]:
                    row9["flowTop"] = fl9[1]
                if row9.get("rbNew"):
                    row9["flow"] = round(float(row9.get("flow") or 0) + float(row9["rbNew"]), 2)
                    row9["flowTop"] = [["Rabby 기준 첫 반영(봇 미추적 보유)", round(float(row9["rbNew"]), 2)]] + list(row9.get("flowTop") or [])[:2]
        except Exception as e9:   # noqa: BLE001 [optional]
            calcguard.swallowed("view_b_daily:DailyBuildMixin._build_daily[offc_ids9]", e9)
            log.warning("일별 순유입 계산 실패: %s", e9)
        pvu9 = float((self.__dict__.get("_prov_view") or {}).get("usd") or 0)
        if abs(pvu9) >= 0.005 and daily:
            tk9 = today_kst.strftime("%m-%d")
            for row9 in daily:
                if row9.get("date") == tk9:
                    row9["val"] = round(float(row9.get("val") or 0) + pvu9, 2)
                    row9["pv"] = round(pvu9, 2)
                    row9["flow"] = round(float(row9.get("flow") or 0) + pvu9, 2)
                    row9["flowTop"] = [["옛 기록 받는 중인 지갑·거래소의 지금 잔고 반영", round(pvu9, 2)]] + list(row9.get("flowTop") or [])[:2]
        try:
            pid_gid9, spoof_pids9 = {}, set()
            for r9 in rows:
                if r9["event"] not in flowev.EV_ALL:
                    continue
                if (r9["source_ns"], r9["source_id"], r9["asset_id"]) in spoof_keys or int(r9["qty_base"]) == 0:
                    spoof_pids9.add(r9["posting_id"])
                if r9["leg_kind"] == "move_in" and (r9["location"] or "").startswith("out:"):
                    pid_gid9[r9["posting_id"]] = r9["group_id"] or -r9["asset_id"]
            fm9 = {a9: o9["flow_matches"] for a9, o9 in ob.items() if o9.get("flow_matches")}
            of_rows_fe9 = [dict(r9, txs=list(r9.get("txs") or ()) + fm9[r9["address"]]) if r9.get("address") in fm9 else r9 for r9 in outflows_out]
            self._flow_ev = flowev.collect(
                conn, G, live_px, now, transit=wdt_all, of_rows=of_rows_fe9, of_match=of_match, of_bridge=of_bridge, deps=of_deps,
                offc_ids=offc_ids9, debts=type(self)._flow_debts(), skip_gids=frozenset(quarantined),
                names={"chain": CHAIN_NAME, "wallet": wallet_label}, fx=lambda t9: self.px.fx_at(int(t9 * 1000)) or rate_fx, xf_links=xf_links,
                proof_sends=[dict(s9, gid=pid_gid9.get(s9["pid"])) for s9 in of_sends], deposit_exchange=self._deposit_exchange,
                skip_pids=frozenset(spoof_pids9))
        except Exception as e9:   # noqa: BLE001 [optional]
            calcguard.swallowed("view_b_daily:DailyBuildMixin._build_daily[pid_gid9]", e9)
            log.warning("큰 출금 재료(flowev) 실패 — 이번 빌드는 판정 재료 없음: %s", e9)
        att_ok9, att_args = False, None
        self._att_det_new = None
        try:
            lpf9 = {}
            for b9 in lpb.values():
                for d9, v9 in (b9.get("rbd") or {}).items():
                    lpf9[d9] = lpf9.get(d9, 0.0) + float(v9)
            unv9 = {}
            for gid9, u9 in unverified.items():
                for d9, ud9 in (u9.get("by_date") or {}).items():
                    fb9 = (unv_fb9.get(d9) or {}).get(gid9) or (Decimal(0), Decimal(0))
                    q9, p9 = Decimal(ud9["qty"]) - fb9[0], Decimal(ud9["proceeds"]) - fb9[1]
                    if q9 > EPS or abs(p9) >= Decimal("0.005"):
                        unv9.setdefault(d9, {})[gid9] = (float(max(q9, Decimal(0))), float(p9))
            real9 = {"rbd": realized_by_date, "lpf": lpf9,
                     "stk": {d9: float(sum(v9[0] for v9 in s9.values())) for d9, s9 in stake_inc.items()}, "unv": unv9}
            pxd9 = (ca_all, ex_gid, native_c9 | ex_c9, override_px, gid_pairs_all, STABLE_GROUPS)
            pxs9 = (lambda gid9: histcurve.spec_of(histcurve.group_desc(gid9, G[gid9], *pxd9)) if gid9 in G else None) if DAYCLOSE_ON else None
            att9 = self._daily_attrib(conn, daily, G, today_kst, live_px, frozenset(quarantined), xtra9, real=real9, px_src=pxs9)
            att_ok9, att_args = True, (G, today_kst, live_px, frozenset(quarantined), xtra9, real9, pxs9)
            for row9 in daily:
                if row9.get("date") in att9:
                    row9["att"] = att9[row9["date"]]
        except Exception as e9:   # noqa: BLE001 [optional]
            calcguard.swallowed("view_b_daily:DailyBuildMixin._build_daily[lpf9]", e9)
            log.warning("일별 자산 변동 분해 실패: %s", e9)
        if not att_ok9:
            self._att_by_today = {}
        try:
            hold_today9, spark7_9 = self._hold_today(coins, G, live_px, today_kst, self.daily_px, getattr(self, "_att_by_today", None))
        except Exception as e9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_b_daily:DailyBuildMixin._build_daily[hold_today9]", e9)
            log.warning("보유표 오늘 변동·7일 추이 재료 실패: %s", e9)
            hold_today9, spark7_9 = {}, {}
        _daily_krw(daily, today_kst.strftime("%m-%d"))
        try:
            td9 = today_kst.strftime("%Y-%m-%d")
            hd9, hnf9, hok9 = _hist_kit_rows(daily, td9, self.daily, self.__dict__.get("_flow_nf") or (),
                                             val_nf=self.__dict__.get("_daily_nf") or ())
            if hnf9:
                log.debug("장기 곡선 재료: 비확정 지난날 %d(%s…) — 값 비워 넘김", len(hnf9), min(hnf9))
            attfreeze.note_marks(self)
            if hok9:
                dex_guarded = sorted(g for g, prs in gid_pairs_all.items() if any(self.spot.guarded.get(f"{c}:{a}") for c, a in prs or ()))
                histcurve.HIST.offer(td9, kit_fn := (lambda: dict(histcurve.make_kit(
                    td9, curve_G9, hold_qty, quarantined, ca_all, ex_gid, native_c9 | ex_c9, override_px, live_px, gid_pairs_all,
                    [e9 for e9 in wdt_all if e9["state"] == "pending"] + list(_bs9.get("dep_tr9") or ()),
                    xtra9, hd9, self.daily, stable_syms=STABLE_GROUPS,
                    flow_kit=self._hist_flow_kit(G, quarantined, offc_ids9, wdt_all, rate_fx, td9, daily),
                    neg_ok=hl_cash9, xkit=self.__dict__.get("_x_kit"),
                    debt_neg=dict(debt_capg9),
                    debt_days={k9: dict(v9) for k9, v9 in ((self.daily_px or {}).get("_dbt") or {}).items() if isinstance(v9, dict)},
                    rb_days=dict(rb_dc9),
                    first_floor=None if self.cfg.get("backfill_full_history") else _bf_since,
                    xq=(self.__dict__.get("_xq9") or (None, None))[0], xq_base=(self.__dict__.get("_xq9") or (None, None))[1]), dg=dex_guarded)))
                attfreeze.backfill(self, conn, kit_fn, att_args)
        except Exception as e9:   # noqa: BLE001 [optional]
            calcguard.swallowed("view_b_daily:DailyBuildMixin._build_daily[td9]", e9)
            log.warning("장기 곡선 재료 실패: %s", e9)
        disp_total = (sum(c["qty"] * (c.get("price") or 0) for c in coins)
                      + sum(s["qty"] * (s.get("price") or 0) for s in stables) + x_fiat + lp_total
                      + sum(d9["usd"] for d9 in rb_debts))
        if daily:
            gap9 = daily[-1]["val"] - disp_total
            diag["daily_today_gap_usd"] = round(gap9, 2)
            if abs(gap9) > 1:
                log.warning("일별 오늘값 ≠ 화면 총자산: %.2f vs %.2f (차 %.2f)", daily[-1]["val"], disp_total, gap9)

        self._ph("daily")
        _bs9.update((k9, v9) for k9, v9 in locals().items() if k9 != "_bs9")
