from __future__ import annotations
import addr_ai
import attfreeze
import balcheck
import buildproc
import config, paths, prefs_ident, statefile
import histcurve
import json
import netpace
import os
import px_alt
import spamguard
import time
import xfer_match
from datetime import datetime
from decimal import Decimal
from http_assets import WEB_DIR
from view_common import CHAIN_NAME
from view_common import DAYCLOSE_ON
from view_common import GOPLUS_STATUS
from view_common import GOPLUS_T0
from timeutil import KST
from view_common import _f
from view_hero import _ago_ko
from view_misc import _dec_or0
from view_misc import _rate_state
from view_misc import _venue_flows30
from view_misc import build_stats
from view_offc import _offc_tx
from view_pending import NEG_DIAG_MIN_USD
from view_pending import dust_usd_eff
from view_pending import unpriced_facts
from view_review import review_fill_req_view
from view_review import review_len_eff
from view_review import review_pause_eff
from view_review import review_progress
from view_tax import _tax_fee_merge
from view_tax import _tax_stable_fx
from view_tax import _tax_summary
import logging
import calcguard  # noqa: E402

log = logging.getLogger('tj-web')


def _tally_unknown_wd(wd_rows, fx_transit, unk):
    for w in wd_rows:
        if w["cls"] != "unknown":
            continue
        e = fx_transit.get(w["txid"]) if w["txid"] else None
        u = unk.setdefault(w["addr"], {"address": w["addr"], "n": 0, "costUsd": 0.0, "costKnown": 0, "syms": set(), "exchanges": set(),
                                          "networks": set(), "first": w["ts"], "last": w["ts"], "sentToMine": 0, "walletTx": 0, "hop": 0,
                                          "offcN": 0})
        u["n"] += 1
        if _offc_tx(w["txid"]):
            u["offcN"] += 1
        if e and e.get("qty") and not e.get("ambiguous"):
            q = _dec_or0(w["qty"])
            u["costUsd"] += float(e["cost"] * (q / e["qty"])) if e["qty"] > 0 else 0.0
            u["costKnown"] += 1
        u["syms"].add(w["sym"]); u["exchanges"].add(w["ex"])
        if w["network"]:
            u["networks"].add(w["network"])
        u["first"] = min(u["first"], w["ts"]); u["last"] = max(u["last"], w["ts"])


def _enrich_unknown_wd(unk, origin_cache, sb, conn, G, unverified):
    if unk:
        for t, oc in (origin_cache or {}).items():
            f = xfer_match.norm_addr((oc or {}).get("from"))
            if f in unk:
                unk[f]["sentToMine"] += 1
        for xl in (getattr(sb, "_xfer_links_last", None) or {}).values():
            if xl.get("via") in unk:
                unk[xl["via"]]["hop"] += 1
        for f, n in sb._raw_from_counts(conn).items():
            if f in unk:
                unk[f]["walletTx"] += n
        for gid, g in G.items():
            srcs = g.get("unk_src") or []
            u = unverified.get(gid)
            if not srcs or not u or float(u["proceeds"]) < 1.0:
                continue
            by = {}
            for x in srcs:
                f = x.get("from") or ((origin_cache or {}).get(str(x.get("ref") or "").lower()) or {}).get("from")
                f = xfer_match.norm_addr(f) if f else None
                if f in unk and not x.get("via"):
                    by[f] = by.get(f, 0.0) + float(x["qty"])
            tot = sum(float(x["qty"]) for x in srcs)
            for a, q in by.items():
                r = unk[a].setdefault("_res", {})
                r[g.get("sym") or "?"] = r.get(g.get("sym") or "?", 0.0) + float(u["proceeds"]) * min(1.0, q / tot if tot > 0 else 0.0)
        for u in unk.values():
            r = u.pop("_res", None) or {}
            if r:
                u["resolveUsd"] = round(sum(r.values()), 2)
                u["resolveSyms"] = [[s, round(v, 2)] for s, v in sorted(r.items(), key=lambda kv: -kv[1])[:6]]


class TailMixin:

    def _build_tail(self, _bs9):
        (G, _pos_all_dbg, acts_md9, bal_src9, be_done, be_until, chain_wallet_rows, coins, conn, cost_be, cost_decided_rows, cost_ov, daily, day_acts, day_ix, day_memos9, day_memos_err9, deposit_rows, diag, ev_hid9, ev_main9, ev_wd9, ex_debts, ex_fee_m, ex_gid, ex_transit, exfee_lab, extra_events_hidden, extra_events_out, fb_on, fee_day, fee_diag, fiats, fs_floor9, fs_on, fs_pref, fs_rbd, fs_sum, fut, fx_name, fx_transit, gas_by_month, gas_expense, gas_list, guard_held9, hid_kind_n9, live_px, lp_events_out, lpb, lps_closed, lps_out, lps_pending, n_wd_hid9, neg_hold, now, oc_fresh, of_tot, offc_summary, offc_wd_addr, origin_cache, origin_pending, outflows_out, outflows_pending, pendings, plan_memos, plans_out, pos_cut9, positions, prefs, quarantined, rb_debts, rb_recon, rb_view, realized_by_date, realized_by_loc, realized_krw_by_date, realized_month, review_realized, sale_links, sale_lots, sale_rf_bid, sale_used, src_chips, stables, stake_inc, tax_gas, tax_rows, today_kst, ub2, unpriced_w, unverified, venue_w, vflow_loc9, wallet_rows, wd_fee_m, wdfee_lab, xc_cands, xc_used, hold_today9, spark7_9, wdt_all,) = (_bs9["G"], _bs9["_pos_all_dbg"], _bs9["acts_md9"], _bs9["bal_src9"], _bs9["be_done"], _bs9["be_until"], _bs9["chain_wallet_rows"], _bs9["coins"], _bs9["ctx"].conn, _bs9["cost_be"], _bs9["cost_decided_rows"], _bs9["cost_ov"], _bs9["daily"], _bs9["day_acts"], _bs9["day_ix"], _bs9["day_memos9"], _bs9["day_memos_err9"], _bs9["deposit_rows"], _bs9["diag"], _bs9["ev_hid9"], _bs9["ev_main9"], _bs9["ev_wd9"], _bs9["ex_debts"], _bs9["ex_fee_m"], _bs9["ex_gid"], _bs9["ex_transit"], _bs9["exfee_lab"], _bs9["extra_events_hidden"], _bs9["extra_events_out"], _bs9["ctx"].fb_on, _bs9["fee_day"], _bs9["fee_diag"], _bs9["fiats"], _bs9["fs_floor9"], _bs9["ctx"].fs_on, _bs9["ctx"].fs_pref, _bs9["fs_rbd"], _bs9["fs_sum"], _bs9["fut"], _bs9["fx_name"], _bs9["fx_transit"], _bs9["gas_by_month"], _bs9["gas_expense"], _bs9["gas_list"], _bs9["guard_held9"], _bs9["hid_kind_n9"], _bs9["live_px"], _bs9["lp_events_out"], _bs9["lpb"], _bs9["lps_closed"], _bs9["lps_out"], _bs9["lps_pending"], _bs9["n_wd_hid9"], _bs9["neg_hold"], _bs9["ctx"].now, _bs9["oc_fresh"], _bs9["of_tot"], _bs9["offc_summary"], _bs9["offc_wd_addr"], _bs9["origin_cache"], _bs9["origin_pending"], _bs9["outflows_out"], _bs9["outflows_pending"], _bs9["pendings"], _bs9["plan_memos"], _bs9["plans_out"], _bs9["pos_cut9"], _bs9["positions"], _bs9["ctx"].prefs, _bs9["quarantined"], _bs9["rb_debts"], _bs9["rb_recon"], _bs9["rb_view"], _bs9["realized_by_date"], _bs9["realized_by_loc"], _bs9["realized_krw_by_date"], _bs9["realized_month"], _bs9["review_realized"], _bs9["sale_links"], _bs9["sale_lots"], _bs9["sale_rf_bid"], _bs9["sale_used"], _bs9["src_chips"], _bs9["stables"], _bs9["stake_inc"], _bs9["tax_gas"], _bs9["tax_rows"], _bs9["ctx"].today_kst, _bs9["ub2"], _bs9["unpriced_w"], _bs9["unverified"], _bs9["venue_w"], _bs9["vflow_loc9"], _bs9["wallet_rows"], _bs9["wd_fee_m"], _bs9["wdfee_lab"], _bs9["xc_cands"], _bs9["xc_used"], _bs9["hold_today9"], _bs9["spark7_9"], _bs9["wdt_all"],)
        d9: object
        reviews = self._auto_reviews(daily, review_realized, acts_md9)
        reviews_weekly = self._merge_llm_reviews(reviews, day_ix, realized_by_date, fut.get("realizedByDate") or {},
                                                 today_kst.strftime("%Y-%m-%d"),
                                                 {k9: round(v9) for k9, v9 in realized_krw_by_date.items() if k9 in realized_by_date},
                                                 fut.get("realizedKrwByDate") or {})
        review_prog = None
        if review_progress is not None:
            try:
                rdays9 = sorted({str(k9) for src9 in (realized_by_date, fut.get("realizedByDate") or {}) for k9, v9 in src9.items()
                                 if len(str(k9)) == 10 and abs(float(v9 or 0)) >= 0.5})
                drv9 = {rv9["iso"]: rv9 for rv9 in reviews.values() if isinstance(rv9, dict) and rv9.get("iso") and isinstance(rv9.get("fp"), dict)}
                review_prog = review_progress.view(paths.state("review_progress.json"), drv9, reviews_weekly, rdays9, today_kst.strftime("%Y-%m-%d"),
                                                   prefs.get("review_fill"))
                review_prog["fillReq"] = review_fill_req_view()
            except Exception as e:   # noqa: BLE001 [optional]
                calcguard.swallowed("view_b_tail:TailMixin._build_tail[rdays9]", e)
                log.warning("AI 리뷰 진행 상황 읽기 실패(표시 생략): %s", e)

        coin_dex = coin_cex = 0.0
        for c9 in coins:
            px9 = c9.get("price") or 0
            for l9 in c9.get("locs") or []:
                q9 = (l9.get("qty") or 0) * px9
                if "지갑" in (l9.get("w") or ""):
                    coin_dex += q9
                else:
                    coin_cex += q9
        for lst9 in ex_transit.values():
            for e9 in lst9:
                if not e9.get("used"):
                    diag["ex_transit_unused_cost"] += e9.get("cost", Decimal(0))
        diag.update({"fee_" + k9: v9 for k9, v9 in fee_diag.items()})
        diag_out = {k: (float(v) if isinstance(v, Decimal) else v) for k, v in diag.items()}
        offc_sum9 = offc_summary()
        self._offc_addrs = {}
        for (e9, u9), a9 in offc_wd_addr.items():
            if a9:
                self._offc_addrs.setdefault(e9, set()).add(a9)

        with self._origin_lock:
            self._origin_pending |= {t for t in origin_pending if not oc_fresh(t)}
        cost_ov_rows = []
        for k9, v9 in (cost_ov.items() if isinstance(cost_ov, dict) else []):
            try:
                gid9 = int(str(k9)[1:])
            except ValueError:
                continue
            g9 = G.get(gid9) or {}
            ovs9 = g9.get("ov_applied") or [Decimal(0), Decimal(0)]
            v9 = v9 if isinstance(v9, dict) else {}
            cost_ov_rows.append({"key": str(k9), "sym": g9.get("sym") or str(k9), "mode": str(v9.get("mode") or "unit"),
                                 "unit": _f(float(v9.get("unit") or 0), 6) or 0,
                                 "qty": _f(float(ovs9[0]), 4) or 0, "cost": _f(float(ovs9[1]), 2) or 0})
        for k9 in sorted(cost_be):
            try:
                gid9 = int(str(k9)[1:])
            except ValueError:
                continue
            if be_until(gid9) is None:
                continue
            bd9 = be_done.get(gid9) or {}
            cost_ov_rows.append({"key": str(k9) + ":be", "gkey": str(k9), "sym": (G.get(gid9) or {}).get("sym") or bd9.get("sym") or str(k9), "mode": "breakeven", "unit": 0,
                                 "qty": _f(float(bd9.get("qty") or 0), 4) or 0, "cost": _f(float(bd9.get("proceeds") or 0), 2) or 0,
                                 "n": bd9.get("n") or 0, "untilT": datetime.fromtimestamp(be_until(gid9), KST).strftime("%m-%d %H:%M")})
        wd_rows9 = getattr(self, "_wd_dest_rows", None) or []
        unk9 = {}
        _tally_unknown_wd(wd_rows9, fx_transit, unk9)
        _enrich_unknown_wd(unk9, origin_cache, self, conn, G, unverified)
        wd_dest_unknown = sorted(({**u9, "syms": sorted(u9["syms"])[:12], "exchanges": sorted(u9["exchanges"]), "networks": sorted(u9["networks"])[:8],
                                   "costUsd": round(u9["costUsd"], 2), "strong": bool(u9["sentToMine"] or u9["walletTx"] or u9["hop"])}
                                  for u9 in unk9.values()), key=lambda u9: (not u9["strong"], -(u9.get("resolveUsd") or 0), -u9["costUsd"], -u9["n"]))
        self._wd_dest_unknown = {u9["address"]: u9 for u9 in wd_dest_unknown}
        try:
            self._attach_flows(conn, outflows_out, live_px, G)
        except Exception as e:   # noqa: BLE001 [optional]
            calcguard.swallowed("view_b_tail:TailMixin._build_tail[_attach_flows]", e)
            log.warning("flow 붙이기 실패: %s", e)
        try:
            self._addr_ai_targets = addr_ai.attach(outflows_out, pendings, self.cfg)
        except Exception as e:   # noqa: BLE001 [optional]
            calcguard.swallowed("view_b_tail:TailMixin._build_tail[_addr_ai_targets]", e)
            log.warning("AI 주소 의견 붙이기 실패: %s", type(e).__name__)
        cls_n9 = {}
        for w9 in wd_rows9:
            cls_n9[w9["cls"]] = cls_n9.get(w9["cls"], 0) + 1
        xl_all9 = getattr(self, "_xfer_links_all", None) or {}
        xl_on9 = getattr(self, "_xfer_links_last", None) or {}
        xfer_links_out = [{"dep": k9, "wd": v9["wd_uuid"], "sym": v9["sym"], "qty": v9["qty"], "wdEx": v9["wd_ex"], "depEx": v9["dep_ex"],
                           "rule": v9["rule"], "label": v9["label"], "dt": v9["dt"], "via": v9.get("via"), "off": k9 not in xl_on9}
                          for k9, v9 in sorted(xl_all9.items(), key=lambda kv: (kv[1]["sym"], kv[0]))]
        my_w9 = {str(w9.get("address") or "").lower() for w9 in self._hist_wallets() if isinstance(w9, dict)}
        sale_out = []
        for l9 in sale_lots:
            u9 = sale_used.get(l9["id"]) or {}
            sale_out.append({"lot": l9["id"], "sym": l9["sym"], "chain": l9["chain"], "auction": l9["auction"], "bidder": l9["bidder"],
                             "bidderMine": l9["bidder"] in my_w9, "label": l9["label"], "cur": l9["cur"], "bids": l9["bids"],
                             "paid": _f(l9["paid"], 6), "refund": _f(l9["refund"], 6), "paidUsd": _f(l9["paid_usd"], 2),
                             "refundUsd": _f(l9["refund_usd"], 2), "costUsd": _f(l9["cost"], 2), "qty": _f(l9["qty"], 6),
                             "unit": None if l9["unit"] is None else float(l9["unit"]), "receiptSym": l9.get("receipt_sym"), "bidTx": l9["bid_tx"][:5], "claimTx": l9["claim_tx"][:5],
                             "usedQty": _f(u9.get("qty") or 0, 6) or 0, "usedCost": _f(u9.get("cost") or 0, 2) or 0, "usedN": u9.get("n") or 0,
                             "rows": u9.get("rows") or [], "off": bool(l9["off"]),
                             "refundBackQty": _f(sum((e9["used"] for e9s in sale_rf_bid.values() for e9 in e9s if e9["lot"] == l9["id"]), Decimal(0)), 6) or 0,
                             "refundBackCost": _f(sum((e9.get("bc", Decimal(0)) for e9s in sale_rf_bid.values() for e9 in e9s if e9["lot"] == l9["id"]), Decimal(0)), 2) or 0,
                             **({"payQty": _f(l9["_pay"]["q"], 6) or 0, "payCost": _f(l9["_pay"]["cost"], 2) or 0, "payProceeds": _f(l9["_pay"]["usd"], 2) or 0,
                                 "payRealized": _f(l9["_pay"]["rz"], 2) or 0, "payUnkQty": _f(l9["_pay"]["unk"], 6) or 0, "payN": l9["_pay"]["n"]}
                                if l9.get("_pay") else {})})
        self._sale_lot_ids = {l9["id"] for l9 in sale_lots}
        self._sale_prio = {str(u9.get("sym") or "").upper() for u9 in unverified.values() if u9.get("sym")}
        diag_out["open_cancel_pairs"] = getattr(self, "_open_cancel_n", 0)
        diag_out["unv_all"] = {"rows": len(unverified), "proceeds": round(float(sum((u9["proceeds"] for u9 in unverified.values()), Decimal(0))), 2),
                               "by": {str(g9): round(float(u9["proceeds"]), 2) for g9, u9 in unverified.items()}}
        diag_out["sale_lots"] = len(sale_lots)
        diag_out["sale_links"] = len(sale_links)
        diag_out["sale_cost_usd"] = round(float(sum((u9["cost"] for u9 in sale_used.values()), Decimal(0))), 2)
        diag_out["sale_heuristic"] = len((statefile.read_json(paths.state("sale_bids.json"), {}) or {}).get("heuristic") or [])
        diag_out["workers"] = sorted(n9 for n9 in self._thread_names() if n9.endswith("-worker"))
        diag_out["net_pace"] = netpace.stats()
        diag_out["proof_diverge"] = list(self.spot.proof_div)
        diag_out["goplus"] = dict(GOPLUS_STATUS)
        diag_out["ex_dead"] = dict(self.spot.ex_dead)
        diag_out["pos_cut"] = pos_cut9
        dead_held9 = []
        for c9 in coins:
            k9 = c9.get("key") or ""
            if not (k9.startswith("g") and k9[1:].isdigit()):
                continue
            gid9 = int(k9[1:])
            ex9 = ex_gid.get(gid9)
            sym9 = (G.get(gid9) or {}).get("sym")
            if ex9 and (c9.get("qty") or 0) > 0 and not c9.get("price") and sym9 in (self.spot.ex_dead_syms.get(ex9) or ()):
                dead_held9.append({"ex": ex9, "sym": sym9, "qty": c9["qty"], "ref": (c9.get("pxRef") or {}).get("px")})
        diag_out["ex_dead_held"] = dead_held9
        try:
            with open(paths.state("recon_adj.json"), encoding="utf-8") as fh_adj:
                adj_doc = json.load(fh_adj)
        except (OSError, ValueError):
            adj_doc = None
        adj_une = adj_doc.get("unexplained") if isinstance(adj_doc, dict) else None
        if isinstance(adj_une, dict) and isinstance(adj_doc.get("by_class"), dict):
            diag_out.update({"adj_unexplained_usd": adj_une.get("usd"), "adj_by_class": adj_doc["by_class"]})
        diag_out["unpriced_held"] = [{"sym": w9["sym"], "where": w9["where"], "qty": w9["qty"], "cost": round(w9["cost"], 2), "ref": round(w9["ref"], 2)}
                                     for w9 in sorted(unpriced_w, key=lambda w9: -max(w9["cost"], w9["ref"]))[:10]
                                     if max(w9["cost"], w9["ref"]) >= 1]
        dex_rows9 = sorted((float(c9.get("pxAge") or 0), c9["qty"] * float(c9.get("price") or 0)) for c9 in coins
                           if str(c9.get("pxSrc") or "").startswith("dex:") and c9.get("pxAge") is not None and not c9.get("pxFrozen")
                           and (c9.get("price") or 0) > 0 and (c9.get("qty") or 0) > 0)
        dex_tot9 = sum(v9 for _a9, v9 in dex_rows9)
        p90w9, acc9 = None, 0.0
        for a9, v9 in dex_rows9:
            acc9 += v9
            if dex_tot9 > 0 and acc9 >= 0.9 * dex_tot9:
                p90w9 = a9
                break
        neg_nd9 = [n9 for n9 in neg_hold if not n9.get("debt") and n9["usd"] <= -NEG_DIAG_MIN_USD]
        neg_pd9 = [n9 for n9 in neg_nd9 if n9.get("pend")]
        wd9 = {"ts": int(now),
               "neg": {"n": len(neg_nd9), "usd": round(sum(n9["usd"] for n9 in neg_nd9), 2),
                       "top": [{k9: n9[k9] for k9 in ("sym", "loc", "usd")} | ({"pend": True} if n9.get("pend") else {}) for n9 in neg_nd9[:3]],
                       "pend": {"n": len(neg_pd9), "usd": round(sum(n9["usd"] for n9 in neg_pd9), 2)}},
               "proof_div": list(self.spot.proof_div), "ex_dead": dict(self.spot.ex_dead), "ex_dead_held": dead_held9,
               "alt_spread": px_alt.held_spread(getattr(self.spot, "alt_spread", None) or {}, coins, ex_gid, G, set(self.spot.upbit_alt) - set(self.spot.upbit_krw)),
               "unpriced_held": unpriced_facts(unpriced_w), "prefid": prefs_ident.diag(self.__dict__.get("_prefid")),
               "gt": dict(self.spot.gt_stat), "ds": dict(self.spot.ds_stat), "goplus": dict(GOPLUS_STATUS, started=int(GOPLUS_T0)),
               "dex_age": {"n": len(dex_rows9), "usd": round(dex_tot9, 2), "p90w": p90w9,
                           "max": dex_rows9[-1][0] if dex_rows9 else None},
               "build": dict(build_stats(self.__dict__.get("_build_hist") or []), cold_ms=self.__dict__.get("_build_cold_ms")),
               "build_hist": list(self.__dict__.get("_build_hist") or []),
               "build_ex": [dict(x9) for x9 in (self.__dict__.get("_build_ex") or [])],
               "phases": self._ph_view(),
               "build_proc": buildproc.status(),
               "rabby": ({"wallets": [{k9: r9[k9] for k9 in ("addr", "label", "bot", "rabby", "diff", "only", "rest", "fetchedAt", "top") if k9 in r9}
                                      | ({"gapSince": r9["gapSince"]} if r9.get("gapSince") else {})
                                      for r9 in rb_recon], "status": rb_view["state"]} if rb_view is not None else None)}
        diag_out["dex_age"] = wd9["dex_age"]
        if time.time() - self.__dict__.get("_wdiag_at", 0) >= 60:
            try:
                statefile.atomic_write_json(paths.state("web_diag.json"), wd9)
                self._wdiag_at = time.time()
            except OSError as e9:
                log.warning("web_diag.json 쓰기 실패: %s", e9)
        if not self.spot.rate and time.time() - float(self.__dict__.get("_rate_fb_warn") or 0) > 3600:
            self._rate_fb_warn = time.time()
            log.warning("지금 환율(KRW/USDT)을 아직 못 받아 원화 환산에 고정 대체값 1384 를 씀 — 시세 수집이 돌면 저절로 바뀜 · 그동안 오늘 마감 보류")
        elif _rate_state(self.spot) == "stale" and time.time() - float(self.__dict__.get("_rate_fb_warn") or 0) > 3600:
            self._rate_fb_warn = time.time()
            log.warning("지금 환율(KRW/USDT)이 %s째 갱신 안 됨(마지막 값 %s 유지) — 그동안 오늘 마감 보류(그날은 그 시각 1분봉 환율로 닫힘)",
                        _ago_ko(time.time() - float(getattr(self.spot, "rate_ts", 0) or 0)) if getattr(self.spot, "rate_ts", 0) else "알 수 없는 시간",
                        self.spot.rate)
        fields = {
            "costOverrideRows": cost_ov_rows,
            "costDecidedRows": cost_decided_rows,
            "saleLinks": sale_out,
            "xferLinks": xfer_links_out, "wdDestStats": cls_n9, "wdDestUnknown": wd_dest_unknown[:100], "wdDestUnknownTotal": len(wd_dest_unknown),
            "xchainLinks": sorted(xc_used.values(), key=lambda x9: -x9["ts"])[:200], "xchainPending": len(xc_cands),
            "coinDexUsd": round(coin_dex, 2), "coinCexUsd": round(coin_cex, 2),
            "futures": fut,
            "_diag": diag_out,
            "stables": stables, "coins": coins, "fiats": fiats, "exDebts": ex_debts, "negHoldings": neg_hold[:50],
            "rabbyDebts": rb_debts,
            "rabby": ({"wallets": rb_recon, "onlyUsd": rb_view["onlyUsd"], "debtUsd": round(sum(d9["usd"] for d9 in rb_debts), 2),
                       "at": rb_view["at"], "status": rb_view["state"]} if rb_view is not None else None),
            "outflows": outflows_out, "outflowsPending": outflows_pending, "outflowsTotals": of_tot,
            "walletAuto": bool(self.__dict__.get("_of_auto_reload")),
            "saleCandAlert": prefs.get("sale_cand_alert") is not False,
            "tokenLogos": config.token_logos_on(self.cfg),
            "krwFlows": self._krw_flows(conn),
            "transits": [dict(self._transit_loc(e9, now)["tr"], sym=e9["sym"], qty=float(e9["qty"]), key=f"g{e9['gid']}")
                         for e9 in wdt_all if e9["state"] == "pending"],
            "lps": lps_out, "lpEvents": lp_events_out,
            "lpsPending": lps_pending, "lpsClosed": lps_closed[:200] + [l9 for l9 in lps_closed[200:] if l9.get("realizedByDay")],
            "lpRealized": _f(float(sum((b9["realized"] + b9["income"]) for b9 in lpb.values())), 2) or 0,
            "stakeRealized": _f(float(sum(v9[0] for d9 in stake_inc.values() for v9 in d9.values())), 2) or 0,
            "positions": positions, "plans": plans_out, "planMemos": plan_memos,
            "dayMemos": day_memos9, "dayMemosOk": True, **({"dayMemosErr": day_memos_err9} if day_memos_err9 else {}),
            "pendings": pendings, "gasByChain": gas_list,
            "taxRows": [{k9: v9 for k9, v9 in r9.items() if not k9.startswith("_")}
                         for r9 in sorted(_tax_fee_merge(tax_rows), key=lambda r9: str(r9.get("sold") or ""))[-100:]],
            "extraEvents": extra_events_out, "extraEventsHidden": extra_events_hidden,
            "dayActs": day_acts,
            "extraEventsTotal": {"main": len(ev_main9), "wd": len(ev_wd9), "hidden": len(ev_hid9),
                                 "hiddenScam": hid_kind_n9.get("scam", 0), "hiddenDust": hid_kind_n9.get("dust", 0),
                                 "wdHidden": n_wd_hid9},
            "taxSummary": _tax_summary(tax_rows, today_kst), "taxRowsTotal": len(tax_rows),
            "taxStableFx": _tax_stable_fx(tax_rows, today_kst),
            "srcWhitelist": list(prefs.get("src_whitelist") or []),
            "realizedByDate": {k: round(v, 2) for k, v in realized_by_date.items()},
            "dateKeys": "iso",
            "realizedKrwByDate": {k: round(v) for k, v in realized_krw_by_date.items() if k in realized_by_date},
            "reviews": reviews,
            "reviewsWeekly": reviews_weekly,
            "rate": self.spot.rate or 1384,
            "fxRate": self.spot.fx_basis or (self.spot.rate or 1384),
            "rateSrc": {"live": "live", "stale": "stale"}.get(_rate_state(self.spot), "fallback"),
            "rateAt": int(self.spot.rate_ts) if self.spot.rate and getattr(self.spot, "rate_ts", 0) else None,
            "dailySeries": daily,
            "todayByCoin": hold_today9, "spark7": spark7_9,
            "usdtByDate": {d["date"]: {"usdt": d["usdt"], "kimp": d["kimp"]} for d in daily},
            "lastScan": self._last_scan_str(),
            "upbitConnected": (bool(ub2)
                               and time.time() - (ub2.get("ts") or 0) < config.upbit_fresh_sec(self.cfg)),
            "srcChips": src_chips, "walletRows": wallet_rows,
            "chainWalletRows": chain_wallet_rows,
            "venueFlows30": _venue_flows30(vflow_loc9, realized_by_loc, venue_w, today_kst),
            "exBalTs": dict({fx_name.get(e9, e9): round(t9) for e9, (_p9, t9) in bal_src9.items() if t9 > 0},
                            **({"업비트": round(float(ub2.get("ts") or 0))} if float(ub2.get("ts") or 0) > 0 else {})),
            "depositRows": deposit_rows, "aliasRows": [],
            "unpricedSyms": [w9["sym"] for w9 in sorted(unpriced_w, key=lambda w9: -max(w9["cost"], w9["ref"]))],
            "unpricedTop": [dict(w9, cost=round(w9["cost"], 2), ref=round(w9["ref"], 2))
                            for w9 in sorted(unpriced_w, key=lambda w9: -max(w9["cost"], w9["ref"]))[:20] if max(w9["cost"], w9["ref"]) >= 1],
            "backfillProgress": self._backfill_progress(conn),
            "backfillSince": self._backfill_since_view(conn),
            "gasByMonth": {m: [{"chain": CHAIN_NAME.get(c, c), "spot": _f(v["usd"], 2) or 0,
                                "tx": v["tx"], **({"br": _f(v["br"], 2)} if v.get("br") else {})}
                               for c, v in sorted(mm.items(), key=lambda kv: -kv[1]["usd"])]
                           + [{"chain": exfee_lab(e9), "spot": _f(v9["usd"], 2) or 0, "tx": v9["tx"], "kind": "exfee", "ex": e9}
                              for e9, v9 in sorted((ex_fee_m.get(m) or {}).items(), key=lambda kv: -kv[1]["usd"])]
                           + [{"chain": wdfee_lab(e9), "spot": _f(v9["usd"], 2) or 0, "tx": v9["tx"], "kind": "exfee", "ex": e9}
                              for e9, v9 in sorted((wd_fee_m.get(m) or {}).items(), key=lambda kv: -kv[1]["usd"])]
                           for m in sorted(set(gas_by_month) | set(ex_fee_m) | set(wd_fee_m)) for mm in [gas_by_month.get(m) or {}]},
            "taxGas": tax_gas,
            "feeAllByDate": {k9: [_f(v9[0], 2), round(v9[1])] for k9, v9 in sorted(fee_day.items()) if v9[0] >= Decimal("0.005")},
            "gasExpenseByDate": {k9: [_f(v9[0], 2), v9[1],
                                      {kk9: {"usd": _f(x9[0], 2), "n": x9[1],
                                             "top": {"usd": _f(x9[2], 2), "ts": x9[3],
                                                     "t": datetime.fromtimestamp(x9[3], KST).strftime("%H:%M") if x9[3] else "",
                                                     "chain": x9[4]}}
                                       for kk9, x9 in sorted(v9[3].items(), key=lambda kv9: -kv9[1][0])}]
                                 for k9, v9 in sorted(gas_expense.items())},
            "walletAlias": {r9["key"]: r9["alias"] for r9 in chain_wallet_rows} | {(w["address"] if w.get("type") == "sol"
                             else w["address"].lower()):
                            (prefs.get("aliases", {}).get(
                                w["address"] if w.get("type") == "sol"
                                else w["address"].lower())
                             or w.get("label") or w["address"][:8])
                            for w in self._hist_wallets()},
            "dustUsd": dust_usd_eff(prefs),
            "fallbackOn": fb_on,
            "firstSeen": {"on": fs_pref, "eff": fs_on, "fb": fb_on, "n": fs_sum["n"], "usd": _f(fs_sum["usd"], 2) or 0,
                          "miss": fs_sum["miss"], "rows": fs_sum["rows"], "real": _f(fs_sum["real"], 2) or 0,
                          "stN": fs_sum["st_n"], "stUsd": _f(fs_sum["st_usd"], 2) or 0,
                          "hold": dict(fs_sum["hold"]) if fs_on else {},
                          "wait": sum(int(u9["n"]) for gid9, u9 in unverified.items()
                                      if fs_on and ((G.get(gid9) or {}).get("_fsh") or {}).get("wait")),
                          "ret": fs_sum["ret_n"], "sd": fs_sum["sd"], "pin": fs_sum["pin"],
                          "note": bool(prefs.get("first_seen_note")),
                          "fill": dict(histcurve.DAYCLOSE.old_status(), since=fs_floor9) if DAYCLOSE_ON else None},
            "fsRealByDate": {k9: [round(v9[0], 2), round(v9[1])] for k9, v9 in sorted(fs_rbd.items()) if abs(v9[0]) >= 0.005 or abs(v9[1]) >= 0.5},
            "offchainSelf": offc_sum9,
            "reviewLen": review_len_eff(prefs),
            "reviewProgress": review_prog,
            "reviewFill": review_progress.fill_eff(prefs.get("review_fill")) if review_progress is not None else None,
            "reviewPause": review_pause_eff(prefs),
            "legacyPages": {"classic": os.path.isfile(os.path.join(WEB_DIR, "index.html")), "futures": os.path.isfile(os.path.join(WEB_DIR, "futures.html"))},
            "originPending": len(origin_pending),
            "costOverrides": cost_ov,
            "costBreakeven": cost_be,
            "priceGuard": {k9: v9 for k9, v9 in self.spot.guarded.items() if k9 in guard_held9},
            "balanceCheck": balcheck.view(),
        }
        fields["prov"] = self._prov_field(fields.get("backfillProgress"))
        if os.environ.get("TJ_REPLAY_DEBUG") == "1":
            fields["_taxRowsAll"] = tax_rows
            fields["_positionsAll"] = _pos_all_dbg
            fields["_xferLinks"] = getattr(self, "_xfer_links_last", None)
            fields["_groupsDbg"] = {str(gid9): {"sym": g9["sym"], "stable": bool(g9["is_stable"]), "fiat": bool(g9.get("is_fiat")),
                                                "quar": gid9 in quarantined,
                                                "rbd": {k9: float(v9) for fl9 in g9["flows"] for k9, v9 in fl9["rbd"].items()}}
                                    for gid9, g9 in G.items() if any(fl9["rbd"] for fl9 in g9["flows"])}
            fields["_lpRbd"] = {k9: {d9: float(v9) for d9, v9 in b9["rbd"].items()} for k9, b9 in lpb.items() if b9["rbd"]}
            fs_sum["unv"] = {str(k9): [v9["sym"], float(v9["qty"]), float(v9["proceeds"]), k9 in quarantined,
                                       float((G.get(k9) or {}).get("qty_unknown") or 0)] for k9, v9 in unverified.items()}
            fs_sum["c_held"] = sum(a9[1] * g9["_cp"].m for g9 in G.values() if g9.get("_cp") is not None
                                   for k9, a9 in g9["_cp"].it.items() if isinstance(k9, tuple) and k9 and k9[0] == "fs")
            fields["_fsDbg"] = {k9: (v9 if not isinstance(v9, Decimal) else float(v9)) for k9, v9 in fs_sum.items()}
        try:
            spamguard.annotate(fields)
        except Exception as e9:  # noqa: BLE001 [optional]
            calcguard.swallowed("view_b_tail:TailMixin._build_tail[annotate]", e9)
            log.warning("심볼 정리 실패(무시): %s", e9)
        attfreeze.hook(self, fields, today_kst.strftime("%Y-%m-%d"), now)
        return {"fields": fields, "todayKey": today_kst.strftime("%m-%d"), "todayIso": today_kst.strftime("%Y-%m-%d"),
                "realizedMonth": round(realized_month, 2), "builtAt": int(now)}
