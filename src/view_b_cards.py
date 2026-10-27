from __future__ import annotations
import accounting_util
import acct_norm
import cgca
import chain_registry
import chaincatalog, config, logs, paths, seeds, statefile
import exprov
import os
import provbal
import rabby
import re
import spamguard
import time
from datetime import datetime
from types import SimpleNamespace
from decimal import Decimal
from view_common import CHAIN_NAME
from view_common import EPS
from view_common import EX_CANDLE_SYMS
from timeutil import KST
from view_common import STABLE_GROUPS
from view_common import _ex_stable_sym
from view_common import _f
from view_misc import STAKE_STATE_KO
from view_misc import _px_recent
from view_misc import _px_took
from view_misc import _sol_stake_accounts
from view_pending import merge_scoped, unpriced_ent, unpriced_pairs
from view_spot import Spot
from view_text import _scam_name
from view_text import _short_addr
import logging
import calcguard  # noqa: E402

log = logging.getLogger('tj-web')


def _pre_mkt(sym, *, sb):
    return bool(sb.spot.upbit_krw) and (sym not in sb.spot.upbit_krw and sym not in sb.spot.upbit_alt or _pre_listed(sym, sb=sb))


def _pre_listed(sym, *, sb):
    sp = sb.spot
    return sym in sp.upbit_krw and sym in (getattr(sp, "upbit_answered", None) or ()) and f"upbit:{sym}" not in sp.ex_ts


def _cex_px_for(gid, *, cex_proof, sb):
    for ex, cur in cex_proof.get(gid) or ():
        p = sb.spot.ex_price(ex, cur)
        if p:
            return float(p), ex, cur
    return 0.0, None, None


def _gp_info(gid12, *, gid_pairs_all, gp_cache):
    worst12 = None
    for ch12, ca12 in gid_pairs_all.get(gid12, []):
        ent12 = (gp_cache.get(f"{ch12}:{(ca12 or '').lower()}") or {}).get("risk")
        if ent12:
            if ent12.get("strong"):
                return ent12
            worst12 = worst12 or ent12
    return worst12


def _wdisp(ch, wa, *, disp):
    if not chain_registry.is_nonevm(ch):
        return wa
    d = disp.get((ch, wa))
    if d is not None:
        return d or None
    if ch == "btc":
        return None
    try:
        return chain_registry.display_owner(ch, wa) or None
    except (TypeError, ValueError):
        return None


def _meta_sym(gid, *, gid_pairs, sb):
    for ch, ca in gid_pairs.get(gid) or ():
        m = sb.spot.token_meta.get(f"{ch}:{ca}")
        s = spamguard.clean((m or ["", ""])[0]).strip()
        if not s or len(s) > 20 or s.upper() in ("TOKEN", "?") or s.upper() in STABLE_GROUPS:
            continue
        if _scam_name(s) or spamguard.major_of(s) or spamguard.impostor_of(s) or spamguard.odd_symbol(s):
            continue
        return s
    return None


def _glob_age(sym, *, sb):
    ts = sb.spot.usd_ts.get(sym)
    return (time.time() - float(ts)) if ts else None


def _ref_px(sym, own, *, sb, fx_name):
    vals = sorted((float(p), ex) for ex in sb.CEX_PX_ORDER if ex != own
                   for p in (sb.spot.ex_price(ex, sym),) if p)
    if not vals:
        return None
    n = len(vals)
    med = vals[n // 2][0] if n % 2 else (vals[n // 2 - 1][0] + vals[n // 2][0]) / 2
    return {"px": med, "srcs": [fx_name.get(e, e) for _v, e in vals], "note": "다른 거래소 참고가(동일 코인 미확인)"}


def _liq_real(gid12, *, cex_proof, sb, gid_pairs_all):
    if _cex_px_for(gid12, cex_proof=cex_proof, sb=sb)[0]:
        return True
    for ch12, ca12 in gid_pairs_all.get(gid12, []):
        k12 = (ca12 or "").lower() if ch12 != "sol" else ca12
        rv12 = sb.spot.dex_reserve(ch12, k12)
        if rv12 is not None and rv12 >= sb.spot.min_reserve_usd and sb.spot.dex_price(ch12, k12):
            return True
    return False


def _calc_err_mark(pos, fl, g):
    for site, ts, nxt in calcguard.row_errs(g["gid"]):
        if fl is not None:
            before = [f for f in g["flows"] if f["opened"] <= ts]
            after = [f for f in g["flows"] if f["opened"] >= ts]
            target = (after[0] if after else None) if nxt else (before[-1] if before else (after[0] if after else None))
            if target is not fl:
                continue
        pos["calcErr"] = site
        return


def _add_gas_card(gas_expense, positions, tax_rows):
    if gas_expense:
        gx_rbd = {k: round(-float(v[0]), 2) for k, v in sorted(gas_expense.items())}
        gx_o = min(int(datetime.strptime(k, "%Y-%m-%d").replace(tzinfo=KST).timestamp()) for k in gas_expense)
        positions.append({
            "realizedByDay": gx_rbd, "actByDay": {}, "unvByDay": {},
            "realizedKrwByDay": {k: round(-v[2]) for k, v in sorted(gas_expense.items())},
            "_gid": None, "kind": "gas", "unknownQty": 0, "fbAvg": 0, "fbCost": 0, "unvQty": 0, "unvProceeds": 0, "realizedFb": 0,
            "soldProceeds": 0, "avgSell": 0, "avgKrw": 0, "avgSellKrw": 0, "costKrw": 0, "soldProceedsKrw": 0,
            "key": "sgas", "sym": "가스 비용", "chain": "매매 외 가스(실패·승인·전송·브릿지·LP)",
            "status": "종료", "held": 0, "bought": 0, "movedQty": 0, "movedCost": 0, "soldQty": 0,
            "avg": 0, "cost": 0, "realized": round(-float(sum(v[0] for v in gas_expense.values())), 2), "unreal": 0,
            "opened": datetime.fromtimestamp(gx_o, KST).strftime("%m-%d"), "_ots": gx_o,
            "fee": f"${float(sum(v[0] for v in gas_expense.values())):,.2f}",
            "realizedKrw": round(-sum(v[2] for v in gas_expense.values())),
            "steps": ["가스 비용"], "events": []})
        for k, v in sorted(gas_expense.items()):
            tax_rows.append({"sold": k, "sym": "가스", "ticker": "GAS", "ex": "기타 비용(가스)", "qty": 0, "acq": 0, "disp": 0,
                             "fee": _f(v[0], 2), "rate": round(v[2] / float(v[0]), 4) if v[0] > 0 else 0,
                             "_fee": float(v[0]), "tx": v[1]})


def _add_stake_card(stake_inc, positions, tax_rows):
    if stake_inc:
        sk_rbd = {k: round(float(sum(v[0] for v in d.values())), 2) for k, d in sorted(stake_inc.items())}
        sk_o = min(int(datetime.strptime(k, "%Y-%m-%d").replace(tzinfo=KST).timestamp()) for k in stake_inc)
        sk_syms = sorted({s for d in stake_inc.values() for s in d})
        positions.append({
            "realizedByDay": sk_rbd, "actByDay": {}, "unvByDay": {},
            "realizedKrwByDay": {k: round(sum(v[3] for v in d.values())) for k, d in sorted(stake_inc.items())},
            "rwdByDay": {k: sum(v[2] for v in d.values()) for k, d in sorted(stake_inc.items())},
            "_gid": None, "kind": "stake", "unknownQty": 0, "fbAvg": 0, "fbCost": 0, "unvQty": 0, "unvProceeds": 0, "realizedFb": 0,
            "soldProceeds": 0, "avgSell": 0, "avgKrw": 0, "avgSellKrw": 0, "costKrw": 0, "soldProceedsKrw": 0,
            "key": "sstake", "sym": "스테이킹 보상", "chain": " · ".join(sk_syms) + " 스테이킹(에폭 보상·MEV 팁)",
            "status": "종료", "held": 0, "bought": 0, "movedQty": 0, "movedCost": 0, "soldQty": 0,
            "avg": 0, "cost": 0, "realized": round(float(sum(v[0] for d in stake_inc.values() for v in d.values())), 2), "unreal": 0,
            "opened": datetime.fromtimestamp(sk_o, KST).strftime("%m-%d"), "_ots": sk_o, "fee": "$0.00",
            "realizedKrw": round(sum(v[3] for d in stake_inc.values() for v in d.values())),
            "steps": ["스테이킹 보상"], "events": []})
        for k, d in sorted(stake_inc.items()):
            for s, v in sorted(d.items()):
                tax_rows.append({"sold": k, "sym": s, "ticker": s, "ex": "스테이킹 보상", "tk": "inc", "qty": _f(float(v[1]), 6), "acq": 0,
                                 "disp": _f(float(v[0]), 2), "fee": 0,
                                 "rate": round(v[3] / float(v[0]), 4) if v[0] > 0 else 0,
                                 "_acq": 0.0, "_disp": float(v[0]), "tx": v[2]})


class CardsMixin:

    def _build_cards(self, _bs9):
        (G, conn, debt_neg9, debt_take9, ex_gid, fb_cov9, fb_on, fs_on, fx_name, fx_transit, fxb, gas_expense, gid_pairs, hl_neg, led_by_gid, led_upbit_gids, live, locs_by_gid, lp_pos_rows, my_all9, now, pid_row, prefs, price_groups, pv_dl9, pv_unk9, realized_by_date, realized_krw_by_date, signer9, spoof_keys, stake_inc, stake_rwd, tax_rows, tok_pairs9, ub_snap9, uf_dl9, uncred_cost, uncred_fx, uncred_gid, uncred_known, unv_fb9, unverified, upbit_transit_gids, wdt_gid, xp_unk9,) = (_bs9["G"], _bs9["ctx"].conn, _bs9["debt_neg9"], _bs9["debt_take9"], _bs9["ex_gid"], _bs9["fb_cov9"], _bs9["ctx"].fb_on, _bs9["ctx"].fs_on, _bs9["fx_name"], _bs9["fx_transit"], _bs9["ctx"].fxb, _bs9["gas_expense"], _bs9["gid_pairs"], _bs9["hl_neg"], _bs9["led_by_gid"], _bs9["led_upbit_gids"], _bs9["live"], _bs9["locs_by_gid"], _bs9["lp_pos_rows"], _bs9["my_all9"], _bs9["ctx"].now, _bs9["pid_row"], _bs9["ctx"].prefs, _bs9["price_groups"], _bs9["pv_dl9"], _bs9["pv_unk9"], _bs9["realized_by_date"], _bs9["realized_krw_by_date"], _bs9["signer9"], _bs9["spoof_keys"], _bs9["stake_inc"], _bs9["stake_rwd"], _bs9["tax_rows"], _bs9["tok_pairs9"], _bs9["ub_snap9"], _bs9["uf_dl9"], _bs9["uncred_cost"], _bs9["uncred_fx"], _bs9["uncred_gid"], _bs9["uncred_known"], _bs9["unv_fb9"], _bs9["unverified"], _bs9["upbit_transit_gids"], _bs9["wdt_gid"], _bs9["xp_unk9"],)
        cst = SimpleNamespace(G=G, conn=conn, debt_neg9=debt_neg9, debt_take9=debt_take9, ex_gid=ex_gid, fb_cov9=fb_cov9, fb_on=fb_on, fs_on=fs_on, fx_name=fx_name, fx_transit=fx_transit, fxb=fxb, gas_expense=gas_expense, gid_pairs=gid_pairs, hl_neg=hl_neg, led_by_gid=led_by_gid, led_upbit_gids=led_upbit_gids, live=live, locs_by_gid=locs_by_gid, lp_pos_rows=lp_pos_rows, my_all9=my_all9, now=now, pid_row=pid_row, prefs=prefs, price_groups=price_groups, pv_dl9=pv_dl9, pv_unk9=pv_unk9, realized_by_date=realized_by_date, realized_krw_by_date=realized_krw_by_date, signer9=signer9, spoof_keys=spoof_keys, stake_inc=stake_inc, stake_rwd=stake_rwd, tax_rows=tax_rows, tok_pairs9=tok_pairs9, ub_snap9=ub_snap9, uf_dl9=uf_dl9, uncred_cost=uncred_cost, uncred_fx=uncred_fx, uncred_gid=uncred_gid, uncred_known=uncred_known, unv_fb9=unv_fb9, unverified=unverified, upbit_transit_gids=upbit_transit_gids, wdt_gid=wdt_gid, xp_unk9=xp_unk9)
        self._cards_risk(cst)
        self._cards_hold_prep(cst)
        self._cards_holdings(cst)
        self._cards_extra(cst)
        self._cards_prov_events(cst)
        self._cards_positions(cst)
        self._cards_daily_gates(cst)
        (_pos_all_dbg, aliases, ca_all, coins, disp9, dust_ev, ev_hide, ev_usd, ex_c9, gid_pairs_all, guard_held9, invck9, live_px, native_c9, override_px, overrides9, pending_gids, pos_cut9, pos_ev_full, pos_hid9, positions, quarantined, rb_debts, rb_net, rb_view, spam_view, stab_ev, stables, syms9, ub2, ub_path2, unpriced_w, unv9, venue_w, wl9, xv_up_coin9,) = (cst._pos_all_dbg, cst.aliases, cst.ca_all, cst.coins, cst.disp9, cst.dust_ev, cst.ev_hide, cst.ev_usd, cst.ex_c9, cst.gid_pairs_all, cst.guard_held9, cst.invck9, cst.live_px, cst.native_c9, cst.override_px, cst.overrides9, cst.pending_gids, cst.pos_cut9, cst.pos_ev_full, cst.pos_hid9, cst.positions, cst.quarantined, cst.rb_debts, cst.rb_net, cst.rb_view, cst.spam_view, cst.stab_ev, cst.stables, cst.syms9, cst.ub2, cst.ub_path2, cst.unpriced_w, cst.unv9, cst.venue_w, cst.wl9, cst.xv_up_coin9,)
        self._ph("cex_proof·prices")
        invck9.to_diag(_bs9["diag"])
        _bs9.update((k9, v9) for k9, v9 in locals().items() if k9 != "_bs9")

    def _cards_risk(self, cst):
        (G, conn, ex_gid, gid_pairs, prefs, price_groups, tok_pairs9,) = (cst.G, cst.conn, cst.ex_gid, cst.gid_pairs, cst.prefs, cst.price_groups, cst.tok_pairs9,)
        cex_proof = self._cex_proof(conn)
        self.spot.want_ex({ex9 for gid9, lst9 in cex_proof.items() if gid9 in gid_pairs for ex9, _c9 in lst9})
        exk9 = {}
        for gid9, ex9 in ex_gid.items():
            s9 = acct_norm.canon((G.get(gid9) or {}).get("sym"), ex9) if ex9 == "upbit" else None
            if s9:
                exk9.setdefault(s9, []).append(gid9)
        pre_og9 = {}
        for og9 in sorted(cex_proof):
            if (G.get(og9) or {}).get("is_stable"):
                continue
            for ex9, cur9 in cex_proof[og9]:
                for xg9 in (exk9.get(acct_norm.canon(cur9, ex9)) or ()) if ex9 == "upbit" else ():
                    if og9 not in pre_og9.setdefault(xg9, []):
                        pre_og9[xg9].append(og9)
        pre_want9 = [xg9 for xg9 in pre_og9 if xg9 in price_groups and _pre_mkt(price_groups[xg9]["sym"], sb=self)
                     and not self.spot.ex_price("upbit", price_groups[xg9]["sym"])]
        self.spot.want_tokens([p9 for xg9 in pre_want9 for og9 in pre_og9[xg9] for p9 in tok_pairs9.get(og9) or ()], slot="expre")
        self.spot.want_ex({ex9 for xg9 in pre_want9 for og9 in pre_og9[xg9] for ex9, _c9 in cex_proof.get(og9) or ()})
        overrides9 = prefs.get("risk_overrides") or {}
        wl9 = {str(a).lower() for a in (prefs.get("src_whitelist") or []) if a}
        gp_cache9 = statefile.read_json(paths.state("goplus_cache.json"), {}) if os.path.exists(paths.state("goplus_cache.json")) else {}
        gid_pairs_all = {}
        for r12 in conn.execute("SELECT group_id, chain, address FROM assets"
                                " WHERE kind='token' AND address IS NOT NULL"
                                " AND group_id IS NOT NULL").fetchall():
            gid_pairs_all.setdefault(r12["group_id"], []).append(
                (r12["chain"], r12["address"]))
        native_gids9 = {r12[0] for r12 in conn.execute(
            "SELECT DISTINCT group_id FROM assets WHERE kind != 'token' AND group_id IS NOT NULL").fetchall()}
        native_kind9 = {r12[0] for r12 in conn.execute(
            "SELECT DISTINCT group_id FROM assets WHERE kind = 'native' AND group_id IS NOT NULL").fetchall()}
        proven_ca9 = {}
        for gidp9, lstp9 in cex_proof.items():
            if lstp9:
                for chp9, cap9 in gid_pairs_all.get(gidp9, []):
                    if chp9 != "sol" and cap9:
                        proven_ca9.setdefault(cap9.lower(), set()).add(chp9)
        quarantined = set()
        airdrop_only = set()
        open_cg9 = set()
        cg_px_want9 = set()
        cg_want9 = {}

        def cg_open9(gid12, g12):
            prs12 = gid_pairs_all.get(gid12) or []
            if not prs12 or gid12 in native_gids9 or g12.get("is_stable") or g12.get("is_fiat"):
                return None
            if any(g12.get(k9) for k9 in ("px_seen", "ex_seen", "mv_seen", "risk_allow", "risk_allow_bridge", "risk_airdrop_signed", "risk_airdrop")):
                return None
            if any(spamguard.is_genuine(ch12, ca12) or spamguard.is_user_genuine(ch12, ca12) for ch12, ca12 in prs12) or _cex_px_for(gid12, cex_proof=cex_proof, sb=self)[0]:
                return None
            q12 = sum(float(dq12) for _t12, dq12 in g12.get("qty_timeline") or ())
            st12 = None
            for ch12, ca12 in prs12:
                k12 = (ca12 or "").lower() if ch12 != "sol" else ca12
                dx12 = float(self.spot.dex_usd.get(f"{ch12}:{k12}") or 0)
                if dx12 > 0:
                    cg_want9[(ch12, k12)] = max(cg_want9.get((ch12, k12), 0.0), max(0.0, q12) * dx12)
                s12 = cgca.status(ch12, k12)
                if s12 is True:
                    st12 = True
                elif s12 is False and st12 is None:
                    st12 = False
            if st12:
                open_cg9.add(gid12)
            if st12 is False and g12.get("cg_mine"):
                return None
            return st12
        goplus_want9 = set()
        unv9 = set()
        real_sym9 = {}
        for gid9r, g9r in G.items():
            if g9r.get("px_seen") or g9r.get("ex_seen"):
                sk9r = acct_norm.canon(spamguard.clean(g9r.get("sym") or ""))
                if sk9r:
                    real_sym9.setdefault(sk9r, set()).add(gid9r)
        def fake_ticker9(gid12, g12):
            if gid12 not in gid_pairs_all or gid12 in native_gids9 or g12.get("is_stable") or g12.get("is_fiat") or not g12.get("sent_n"):
                return None
            if any(g12.get(k9) for k9 in ("px_seen", "ex_seen", "mv_seen", "risk_allow", "risk_allow_bridge", "risk_airdrop_signed", "risk_airdrop")):
                return None
            for ch12, ca12 in gid_pairs_all.get(gid12, []):
                if spamguard.is_genuine(ch12, ca12):
                    return None
                k12 = f"{ch12}:{(ca12 or '').lower() if ch12 != 'sol' else ca12}"
                if self.spot.dex_usd.get(k12) or float(self.spot.dex_res.get(k12) or 0) >= 1000:
                    return None
            sym9f = spamguard.clean(g12.get("sym") or "").strip()
            sk9 = acct_norm.canon(sym9f)
            if not sk9 or re.fullmatch(r"TOKEN|NATIVE:.*|\?", sk9) or not (real_sym9.get(sk9, set()) - {gid12}):
                return None
            if _cex_px_for(gid12, cex_proof=cex_proof, sb=self)[0] or any(ch12 != "sol" and (proven_ca9.get((ca12 or "").lower()) or set())
                                           for ch12, ca12 in gid_pairs_all.get(gid12, [])):
                return None
            if any(self.spot.dex_price(ch12, (ca12 or "").lower() if ch12 != "sol" else ca12)
                   for ch12, ca12 in gid_pairs_all.get(gid12, [])):
                return None
            return f"가짜 {sym9f} — 원장의 정품 {sym9f}(체결·거래소 이력)와 다른 컨트랙트 · 시세·체결 없음"
        for gid12, g12 in G.items():
            ov12 = overrides9.get(f"g{gid12}")
            why12 = self._impostor_reason(
                g12, gid12 in gid_pairs_all, gid_pairs_all.get(gid12), gid12 in native_gids9,
                priced=not g12.get("spoof_soft") or bool(_cex_px_for(gid12, cex_proof=cex_proof, sb=self)[0])
                or any(self.spot.dex_price(ch12, (ca12 or "").lower() if ch12 != "sol" else ca12)
                       for ch12, ca12 in gid_pairs_all.get(gid12, [])),
                liquid=lambda gid12=gid12: _liq_real(gid12, cex_proof=cex_proof, sb=self, gid_pairs_all=gid_pairs_all)) \
                if ov12 not in ("visible", "spam") else None
            if not why12 and ov12 not in ("visible", "spam"):
                why12 = fake_ticker9(gid12, g12)
            if why12:
                g12["risk_reason"] = why12
                quarantined.add(gid12)
                continue
            if g12.get("risk_unv"):
                g12["risk_reason"] = f"확인 필요 — 정품 목록에 없는 {g12['risk_unv']} 컨트랙트 · 유동성 있는 시세 없음(확인 전 합계·기록 제외)"
                quarantined.add(gid12)
                unv9.add(gid12)
                continue
            if not any(dq12 > 0 for _, dq12 in g12["qty_timeline"]):
                continue
            if ov12 == "spam":
                g12["risk_reason"] = "유저 확정 스팸"
                quarantined.add(gid12)
                continue
            if g12.get("is_stable") or g12.get("is_fiat") or g12.get("risk_allow"):
                continue
            if any(k12 in ("native", "exchange_currency") or st12 or spamguard.is_genuine(ch12, ca12)
                   or (((G.get(cg12) or {}).get("ex_seen") or (G.get(cg12) or {}).get("mv_seen")) and cg12 not in quarantined)
                   for cg12, k12, ch12, ca12, st12 in g12.get("risk_disp_cp") or ()):
                continue
            if ov12 == "visible":
                continue
            if wl9 and g12.get("risk_srcs") and self._risk_wl_hit(conn, g12, wl9):
                continue
            if g12.get("risk_allow_bridge"):
                goplus_want9.update(gid_pairs_all.get(gid12, []))
                gpb12 = _gp_info(gid12, gid_pairs_all=gid_pairs_all, gp_cache=gp_cache9)
                if not (gpb12 and gpb12.get("strong")):
                    continue
                g12["risk_reason"] = f"브릿지 매칭 자산 · 고플러스 {gpb12['label']}"
                quarantined.add(gid12)
                continue
            airdrop12 = bool(g12.get("risk_airdrop"))
            if not airdrop12 and g12.get("risk_airdrop_signed"):
                liq12 = bool(_cex_px_for(gid12, cex_proof=cex_proof, sb=self)[0]) or any(
                    self.spot.dex_price(ch12, (ca12 or "").lower() if ch12 != "sol" else ca12)
                    and (self.spot.dex_reserve(ch12, (ca12 or "").lower() if ch12 != "sol" else ca12) or 0) >= self.spot.min_reserve_usd
                    for ch12, ca12 in gid_pairs_all.get(gid12, []))
                if liq12:
                    goplus_want9.update(gid_pairs_all.get(gid12, []))
                    gps12 = _gp_info(gid12, gid_pairs_all=gid_pairs_all, gp_cache=gp_cache9)
                    if gps12 and gps12.get("strong"):
                        g12["risk_reason"] = f"내 서명 수령 · 고플러스 {gps12['label']}"
                        quarantined.add(gid12)
                        continue
                airdrop12 = not liq12
                if liq12:
                    g12["risk_signed_ok"] = True
            open12 = bool(g12.get("risk_open_unk"))
            if not (airdrop12 or open12):
                continue
            if any(ch12 != "sol" and (proven_ca9.get((ca12 or "").lower()) or set()) - {ch12}
                   for ch12, ca12 in gid_pairs_all.get(gid12, [])):
                continue
            gp12 = _gp_info(gid12, gid_pairs_all=gid_pairs_all, gp_cache=gp_cache9)
            goplus_want9.update(gid_pairs_all.get(gid12, []))
            if airdrop12 and not (gp12 and gp12.get("strong")) and any(spamguard.is_user_genuine(ch12, ca12) for ch12, ca12 in gid_pairs_all.get(gid12, [])):
                airdrop12 = False
                if not (open12 and g12.get("risk_rebal_neg")):
                    continue
            if airdrop12:
                g12["risk_reason"] = "실매수 이력 없는 에어드랍 유입" + \
                    (f" · 고플러스 {gp12['label']}" if gp12 else " · 고플러스 조회 중")
                quarantined.add(gid12)
                if not (gp12 and gp12.get("strong")):
                    airdrop_only.add(gid12)
            elif open12 and g12.get("risk_rebal_neg"):
                g12["risk_reason"] = "기초잔고 앵커 → 재정렬 실측 소거 (잔고 대사 잔여분)"
                quarantined.add(gid12)
            elif gp12 and gp12.get("strong"):
                g12["risk_reason"] = f"기초잔고 앵커 + 고플러스 {gp12['label']}"
                quarantined.add(gid12)
            elif open12 and not airdrop12 and cg_open9(gid12, g12) is False:
                g12["risk_reason"] = "창 이전 수령(기초잔고) · 코인게코 시세 없음 — 이 기간에 사고판 이력 없음(평가 제외)"
                quarantined.add(gid12)
        off12 = set(self.cfg.get("_disabled_chains") or ())
        self._goplus_want = sorted(p for p in goplus_want9 if p[0] not in off12)
        self._risk_quarantined = quarantined
        self._risk_unverified = frozenset(unv9)
        self._unv_pairs = {(c9, a9): str(G[g9].get("risk_unv") or G[g9].get("sym") or "")
                           for g9 in unv9 for c9, a9 in gid_pairs_all.get(g9, ()) if a9}
        self._risk_airdrop_only = frozenset(g9 for g9 in airdrop_only & quarantined
                                            if str(G[g9].get("risk_reason") or "").startswith("실매수 이력 없는 에어드랍 유입"))
        self._risk_reasons = {gid14: (G[gid14].get("risk_reason") or "")
                              for gid14 in quarantined}
        spam_view = []

        override_px = {}
        for k, v in (self.cfg.get("price_overrides") or {}).items():
            if not isinstance(k, str) or ":" not in k:
                continue
            ch, ca = k.split(":", 1)
            row = conn.execute("SELECT group_id FROM assets WHERE chain=? AND address=?",
                               (ch, ca if ch == "sol" else ca.lower())).fetchone()
            if row and row["group_id"]:
                try:
                    override_px[row["group_id"]] = float(v)
                except (TypeError, ValueError):
                    pass
        (cst.cex_proof, cst.cg_px_want9, cst.cg_want9, cst.gid_pairs_all, cst.native_kind9, cst.open_cg9, cst.override_px, cst.overrides9, cst.pre_og9, cst.quarantined, cst.spam_view, cst.unv9, cst.wl9,) = (cex_proof, cg_px_want9, cg_want9, gid_pairs_all, native_kind9, open_cg9, override_px, overrides9, pre_og9, quarantined, spam_view, unv9, wl9,)

    def _cards_hold_prep(self, cst):
        (G, cex_proof, conn, debt_take9, fx_name, hl_neg, locs_by_gid, now, pre_og9, prefs, pv_dl9, stake_rwd, tok_pairs9, ub_snap9, uf_dl9, uncred_fx, upbit_transit_gids, wdt_gid,) = (cst.G, cst.cex_proof, cst.conn, cst.debt_take9, cst.fx_name, cst.hl_neg, cst.locs_by_gid, cst.now, cst.pre_og9, cst.prefs, cst.pv_dl9, cst.stake_rwd, cst.tok_pairs9, cst.ub_snap9, cst.uf_dl9, cst.uncred_fx, cst.upbit_transit_gids, cst.wdt_gid,)
        aliases = prefs.get("aliases") or {}
        stake_meta = _sol_stake_accounts()
        disp9 = {(cw["chain"], cw["key"]): cw["disp"] for cw in self._chain_disp_wallets(self.cfg)}
        def locs_for(gid, uncred=Decimal(0), ubq=Decimal(0)):
            outl = []
            for row in locs_by_gid.get(gid, []):
                qn = float(Decimal(row["qty_norm"]))
                if qn <= 1e-9:
                    if gid in hl_neg and row["location"] == "exchange:hyperliquid" and qn < 0:
                        outl.append({"w": fx_name.get("hyperliquid", "Hyperliquid"), "qty": qn,
                                     "sub": "무기한 현금 음수(미실현 이익 인출 — 포지션 청산 때 메워짐 · 총자산에서 차감)"})
                    elif (gid, row["location"]) in debt_take9:
                        ex9 = (row["location"] or "").split(":", 1)[1]
                        outl.append({"w": fx_name.get(ex9, ex9), "qty": -float(debt_take9[(gid, row["location"])]),
                                     "sub": "빌린 몫 · 잔고를 넘은 차입(총자산에서 차감)"})
                    continue
                parts = (row["location"] or "").split(":")
                if parts[0] == "exchange":
                    exn = fx_name.get(parts[1], parts[1])
                    outl.append({"w": exn, "sub": "거래소 잔고 (입금·체결 원장)", "qty": qn})
                    if (gid, row["location"]) in pv_dl9:
                        outl[-1].update(sub="거래소 지금 잔고(옛 기록 받는 중)", pv=1)
                    if (gid, row["location"]) in uf_dl9:
                        outl[-1]["sub"] += " · 미체결 주문 체결분 포함(원장 기록 전)"
                    continue
                ch = parts[1] if len(parts) >= 2 else "?"
                wa = parts[2] if len(parts) >= 3 and parts[2] else None
                if wa and len(parts) >= 5 and parts[3] == "stake":
                    label = aliases.get(wa) or self.addr_label.get(wa) or wa[:8]
                    sa9 = parts[4]
                    sm9 = stake_meta.get(sa9) or {}
                    v9 = sm9.get("voter")
                    rw9 = stake_rwd.get(row["location"] or "")
                    sub9 = (f"{CHAIN_NAME.get(ch, ch)} · SOL ({STAKE_STATE_KO.get(sm9.get('state'), '스테이킹')}"
                            f" · 검증인 {(v9[:4] + '…' + v9[-4:]) if v9 else '미상'}) · 계정 {sa9[:4]}…{sa9[-4:]} · {wa[:6]}…{wa[-4:]}")
                    if rw9 and rw9[0] > 0:
                        sub9 += f" · 누적 보상 {float(rw9[0]):,.4f} SOL"
                    outl.append({"w": (f"{label} · 스테이킹" if str(label).rstrip().endswith("지갑") else f"{label} 지갑 · 스테이킹"),
                                 "ch": CHAIN_NAME.get(ch, ch), "sub": sub9, "qty": qn})
                    if (gid, row["location"]) in pv_dl9:
                        outl[-1].update(sub=outl[-1]["sub"] + " · 지금 잔고(옛 기록 받는 중)", pv=1)
                    continue
                if wa:
                    wd9 = _wdisp(ch, wa, disp=disp9)
                    label = aliases.get(wa) or self.addr_label.get(wa) or (wd9 or wa)[:8]
                    short = f"{wd9[:6]}…{wd9[-4:]}" if wd9 else ""
                    outl.append({"w": label if str(label).rstrip().endswith("지갑") else f"{label} 지갑", "ch": CHAIN_NAME.get(ch, ch),
                                 "sub": f"{CHAIN_NAME.get(ch, ch)} · {short}" if short else CHAIN_NAME.get(ch, ch), "qty": qn})
                    if (gid, row["location"]) in pv_dl9:
                        outl[-1].update(sub=outl[-1]["sub"] + " · 지금 잔고(옛 기록 받는 중)", pv=1)
                else:
                    outl.append({"w": "SOL 지갑" if ch == "sol" else "EVM 지갑",
                                 "sub": f"{CHAIN_NAME.get(ch, ch)} · 합산(구형 기록)", "qty": qn})
            tr9 = wdt_gid.get(gid) or ()
            uncred_old9 = uncred - sum((e9["qty"] for e9 in tr9), Decimal(0))
            if uncred_old9 > EPS:
                w_u = "업비트" if (gid in upbit_transit_gids or gid not in uncred_fx) else fx_name.get(uncred_fx[gid], uncred_fx[gid])
                outl.append({"w": w_u, "sub": "입금확인 대기 · 대사 전", "qty": float(uncred_old9)})
            for e9 in tr9:
                outl.append(self._transit_loc(e9, now))
            if outl:
                return outl
            g9 = G.get(gid) or {}
            last_out = (g9.get("last_out") or {})
            if last_out.get("ex"):
                return [{"w": fx_name.get(last_out["ex"], last_out["ex"]),
                         "sub": "입금 확인 대기 · 거래소 대사 전", "qty": 0}]
            d9 = self._transfer_out_dest(conn).get((g9.get("sym") or "").upper())
            if d9:
                return [{"w": d9["label"],
                         "sub": f"외부 전송 확인 · {(d9.get('to') or '')[:12]}…", "qty": 0}]
            return [{"w": "확인 필요", "sub": "원장 위치 없음 — 미매칭 탭 참조", "qty": 0}]

        ub_coins = {}
        ub2 = {}
        xv_up_coin9 = None
        ub_path2 = paths.state("upbit_balances.json")
        if os.path.exists(ub_path2):
            ub2 = ub_snap9 if ub_snap9 is not None else statefile.read_json(ub_path2, {})
            if time.time() - (ub2.get("ts") or 0) < config.upbit_fresh_sec(self.cfg):
                xv_up_coin9 = float(ub2.get("ts") or 0)
                for acc in ub2.get("accounts") or []:
                    cur3 = str(acc.get("currency") or "")
                    if cur3 in ("", "KRW"):
                        continue
                    try:
                        q3 = float(acc.get("balance") or 0) + float(acc.get("locked") or 0)
                    except (TypeError, ValueError):
                        continue
                    if q3 > 0:
                        ub_coins[cur3.upper()] = ub_coins.get(cur3.upper(), 0) + q3
        stables, coins = [], []
        unpriced = []
        unpriced_w = []
        guard_held9 = set()
        hold_prio = {}
        cex_px_pairs = set()
        live_px = {}
        pending_gids = set()
        px_wait9 = self._px_wait_gids = set()
        proof_div9 = []
        meta_want9 = set()
        pre_used9 = self._px_pre_gids = {}
        def pre_px9(xg9, sym9, qty9):
            ogs9 = pre_og9.get(xg9) or ()
            for og9 in ogs9:
                for ex9, cur9 in cex_proof.get(og9) or ():
                    p9 = self.spot.ex_price(ex9, cur9) if ex9 != "upbit" else None
                    if p9:
                        return float(p9), f"cex:{fx_name.get(ex9, ex9)}", self.spot.ex_age(ex9, cur9), None, 0
            vs9 = []
            for ex9 in self.CEX_PX_ORDER:
                p9 = self.spot.ex_price(ex9, sym9) if ex9 != "upbit" else None
                if p9 and p9 > 0:
                    vs9.append((ex9, float(p9), self.spot.ex_age(ex9, sym9)))
            gp9 = self.spot.price(sym9)
            if gp9 and gp9 > 0 and not any(e9 == "binance" for e9, _p9, _a9 in vs9):
                vs9.append(("글로벌", float(gp9), _glob_age(sym9, sb=self)))
            if not ogs9:
                for ex9, p9, a9 in vs9:
                    n9 = sum(1 for _e9, q9, _a9 in vs9 if max(p9, q9) / min(p9, q9) <= self.PRE_DIVERGE)
                    if n9 >= 2:
                        return p9, f"cex:{fx_name.get(ex9, ex9)}", a9, None, n9
                return 0.0, None, None, None, 0
            dref9, dval9 = None, None
            for og9 in ogs9:
                for ch9, ca9 in tok_pairs9.get(og9) or ():
                    dp9 = self.spot.dex_price(ch9, ca9)
                    if not dp9:
                        continue
                    dref9 = dref9 or float(dp9)
                    rv9 = self.spot.dex_reserve(ch9, ca9)
                    if rv9 is not None and qty9 > 0 and dp9 * qty9 > rv9:
                        continue
                    dval9 = (float(dp9), (ch9, ca9))
                    break
                if dval9:
                    break
            for ex9, p9, a9 in vs9:
                if dref9 and max(p9, dref9) / min(p9, dref9) > self.PRE_DIVERGE:
                    continue
                if not dref9:
                    n9 = sum(1 for _e9, q9, _a9 in vs9 if max(p9, q9) / min(p9, q9) <= self.PRE_DIVERGE)
                    if n9 < 2:
                        continue
                    return p9, f"cex:{fx_name.get(ex9, ex9)}", a9, None, n9
                return p9, f"cex:{fx_name.get(ex9, ex9)}", a9, None, 0
            if dval9:
                k9 = dval9[1]
                return dval9[0], "dex:" + self.spot.dex_src.get(f"{k9[0]}:{k9[1]}", "gecko"), self.spot.dex_age(*k9), k9, 0
            return 0.0, None, None, None, 0

        invck9 = accounting_util.Invariants()
        (cst.aliases, cst.cex_px_pairs, cst.coins, cst.disp9, cst.guard_held9, cst.hold_prio, cst.invck9, cst.live_px, cst.locs_for, cst.meta_want9, cst.pending_gids, cst.pre_px9, cst.pre_used9, cst.proof_div9, cst.px_wait9, cst.stables, cst.ub2, cst.ub_coins, cst.ub_path2, cst.unpriced, cst.unpriced_w, cst.xv_up_coin9,) = (aliases, cex_px_pairs, coins, disp9, guard_held9, hold_prio, invck9, live_px, locs_for, meta_want9, pending_gids, pre_px9, pre_used9, proof_div9, px_wait9, stables, ub2, ub_coins, ub_path2, unpriced, unpriced_w, xv_up_coin9,)

    def _cards_holdings(self, cst):
        (cex_proof, cex_px_pairs, cg_px_want9, coins, ex_gid, fb_on, fs_on, fx_name, gid_pairs, gid_pairs_all, guard_held9, hold_prio, invck9, led_by_gid, led_upbit_gids, live, live_px, locs_for, meta_want9, native_kind9, now, open_cg9, override_px, pending_gids, pre_px9, pre_used9, price_groups, proof_div9, px_wait9, quarantined, spam_view, stables, ub_coins, uncred_cost, uncred_gid, uncred_known, unpriced, unpriced_w, unv9, upbit_transit_gids,) = (cst.cex_proof, cst.cex_px_pairs, cst.cg_px_want9, cst.coins, cst.ex_gid, cst.fb_on, cst.fs_on, cst.fx_name, cst.gid_pairs, cst.gid_pairs_all, cst.guard_held9, cst.hold_prio, cst.invck9, cst.led_by_gid, cst.led_upbit_gids, cst.live, cst.live_px, cst.locs_for, cst.meta_want9, cst.native_kind9, cst.now, cst.open_cg9, cst.override_px, cst.pending_gids, cst.pre_px9, cst.pre_used9, cst.price_groups, cst.proof_div9, cst.px_wait9, cst.quarantined, cst.spam_view, cst.stables, cst.ub_coins, cst.uncred_cost, cst.uncred_gid, cst.uncred_known, cst.unpriced, cst.unpriced_w, cst.unv9, cst.upbit_transit_gids,)
        for gid, g in sorted(price_groups.items(), key=lambda kv: kv[1]["sym"]):
            sym = g["sym"]
            uncred = uncred_gid.get(gid, Decimal(0))
            if gid in led_upbit_gids or gid in upbit_transit_gids:
                ub_coins.pop(sym, None)
            qty_dec = led_by_gid.get(gid, Decimal(0)) + uncred
            qty = float(qty_dec)
            k_all = g["qty_known"] + uncred_known.get(gid, Decimal(0))
            c_all = g["cost"] + uncred_cost.get(gid, Decimal(0))
            avg = float(c_all / k_all) if k_all > EPS else 0
            if not g.get("is_fiat"):
                invck9.check(gid, sym, qty_dec, k_all, c_all)
            if g["is_stable"]:
                if gid not in live:
                    continue
                if gid in quarantined:
                    spam_view.append((gid, g, qty, 1))
                    continue
                stables.append({"key": f"g{gid}", "sym": sym, "name": sym,
                                "qty": qty, "price": 1, "avg": 1,
                                "locs": locs_for(gid, uncred)})
                continue
            dex_px = 0
            dex_key = None
            cex_px, cex_ex, cex_cur = _cex_px_for(gid, cex_proof=cex_proof, sb=self) if gid not in ex_gid else (0.0, None, None)
            if cex_px:
                cex_px_pairs.update(gid_pairs.get(gid, []))
            for ch2, ca2 in gid_pairs.get(gid, []):
                dp = self.spot.dex_price(ch2, ca2)
                if dp:
                    rv2 = self.spot.dex_reserve(ch2, ca2)
                    if rv2 is not None and qty > 0 and dp * qty > rv2:
                        self.spot._guard_note(f"{ch2}:{ca2}", f"보유 평가 ${dp * qty:,.0f} > 풀 유동성 ${rv2:,.0f}")
                        continue
                    if self.spot.guarded.get(f"{ch2}:{ca2}", "").startswith("보유 평가"):
                        self.spot._guard_note(f"{ch2}:{ca2}", None)
                    dex_px = dp
                    dex_key = (ch2, ca2)
                    break
            has_ca = bool(gid_pairs.get(gid))
            src9, age9 = None, None
            if gid in override_px:
                px = override_px[gid]
            elif gid in ex_gid:
                px = self.spot.ex_price(ex_gid[gid], sym) or 0
                src9 = f"cex:{fx_name.get(ex_gid[gid], ex_gid[gid])}"
                if ex_gid[gid] == "upbit" and sym in (getattr(self.spot, "upbit_alt_src", None) or {}):
                    src9 = "cex:" + self.spot.upbit_alt_src[sym]
                elif ex_gid[gid] == "hyperliquid" and sym in (getattr(self.spot, "hl_src", None) or {}):
                    src9 = "cex:" + self.spot.hl_src[sym]
                age9 = self.spot.ex_age(ex_gid[gid], sym)
                if not px and (self.spot.ex_pending(ex_gid[gid])
                               or (ex_gid[gid] == "upbit" and (sym in self.spot.upbit_krw
                                                               or (sym in self.spot.upbit_alt
                                                                   and sym not in (getattr(self.spot, "upbit_alt_miss", None) or ()))))):
                    pending_gids.add(gid)
                if not px and ex_gid[gid] == "upbit" and (gid not in pending_gids or _pre_listed(sym, sb=self)) and _pre_mkt(sym, sb=self):
                    pp9, ps9, pa9, pk9, pn9 = pre_px9(gid, sym, qty)
                    if pp9:
                        px, src9, age9 = pp9, ps9, pa9
                        pre_used9[gid] = (ps9, pk9, pp9, pn9)
            elif gid in native_kind9 and has_ca and self.spot.price(sym):
                px = self.spot.price(sym)
                src9, age9 = "cex:글로벌", _glob_age(sym, sb=self)
            elif cex_px:
                px = cex_px
                src9 = f"cex:{fx_name.get(cex_ex, cex_ex)}"
                age9 = self.spot.ex_age(cex_ex, cex_cur)
            elif dex_px:
                px = dex_px
                src9 = "dex:" + self.spot.dex_src.get(f"{dex_key[0]}:{dex_key[1]}", "gecko")
                age9 = self.spot.dex_age(*dex_key)
            elif has_ca:
                px = 0
                m9p = spamguard.major_of(sym) if gid_pairs.get(gid) and all(
                    spamguard.is_genuine(c9, a9) for c9, a9 in gid_pairs[gid]) else None
                if m9p in spamguard.STABLE_MAJ and any(spamguard.is_user_genuine(c9, a9) for c9, a9 in gid_pairs[gid]):
                    px = 1.0
                elif m9p and m9p not in STABLE_GROUPS:
                    ms9 = {"WETH": "ETH", "WBTC": "BTC", "WBNB": "BNB", "WSOL": "SOL", "WPOL": "POL"}.get(m9p, m9p)
                    px = self.spot.price(ms9) or 0
                    if px:
                        src9, age9 = "cex:글로벌", _glob_age(ms9, sb=self)
                if not px and gid in open_cg9:
                    for ch2, ca2 in gid_pairs.get(gid, []):
                        k2 = (ca2 or "").lower() if ch2 != "sol" else ca2
                        cg_px_want9.add((ch2, k2))
                        off2 = ch2 in self.spot.off_chains
                        cp2 = cgca.price_at(ch2, k2, now=self.spot.off_at.get(ch2) if off2 else None)
                        if cp2:
                            px, src9, age9 = cp2[0], "coingecko", (None if off2 else max(0.0, now - cp2[1]))
                            break
                if not px and any(self.spot.dex_pending(ch2, ca2) for ch2, ca2 in gid_pairs.get(gid, [])):
                    pending_gids.add(gid)
            elif sym in STABLE_GROUPS:
                px = 0
            else:
                px = self.spot.price(sym) or 0
                src9, age9 = "cex:글로벌", _glob_age(sym, sb=self)
                if not px:
                    px = _px_recent(self.px, sym, int(now * 1000)) or 0
                    if _px_took(self.px):
                        px_wait9.add(gid)
                    age9 = None
            live_px[gid] = px
            if cex_px and px == cex_px and dex_px and dex_key and gid in live and gid not in quarantined:
                rv5 = self.spot.dex_reserve(*dex_key)
                ag5 = self.spot.dex_age(*dex_key)
                if rv5 is not None and rv5 >= self.spot.min_reserve_usd and ag5 is not None and ag5 <= 2 * Spot.GT_PROOF_EVERY \
                        and abs(cex_px - dex_px) / min(cex_px, dex_px) > Spot.PROOF_DIVERGE:
                    proof_div9.append({"gid": gid, "sym": sym, "ex": cex_ex, "cex": cex_px, "dex": dex_px, "res": round(rv5),
                                       "pair": f"{dex_key[0]}:{dex_key[1]}", "diff": round(dex_px / cex_px - 1, 4),
                                       "usd": round(qty * cex_px, 2)})
            if gid in live and gid not in quarantined and gid_pairs.get(gid) and qty > 0:
                for ch2, ca2 in gid_pairs[gid]:
                    lp9 = self.spot.dex_usd.get(f"{ch2}:{ca2}") or px or 0
                    hold_prio[(ch2, ca2)] = max(hold_prio.get((ch2, ca2), 0.0), float(lp9 or 0) * qty)
            if gid in pre_used9 and pre_used9[gid][1] and gid in live and gid not in quarantined and qty > 0:
                hold_prio[pre_used9[gid][1]] = max(hold_prio.get(pre_used9[gid][1], 0.0), float(px or 0) * qty)
            if gid not in live:
                continue
            if gid in unv9:
                if qty <= 0:
                    continue
                px = 0
            elif gid in quarantined:
                spam_view.append((gid, g, qty, px))
                continue
            dsym9 = None
            if sym == "TOKEN" and gid_pairs.get(gid):
                meta_want9.update(gid_pairs[gid])
                dsym9 = _meta_sym(gid, gid_pairs=gid_pairs, sb=self)
            row = {"key": f"g{gid}", "sym": dsym9 or sym,
                   "name": (dsym9 or sym) + (" · " + "/".join(sorted(CHAIN_NAME.get(c, c) for c in g["chains"]))),
                   "qty": qty, "price": px, "avg": avg,
                   "kqty": float(max(min(qty_dec, k_all), Decimal(0))),
                   "fbQty": _f(max(float(qty) - float(k_all), 0.0), 6) or 0,
                   "fbCost": _f(max(float(qty) - float(k_all), 0.0) * avg, 2) if (fb_on and avg > 0) else 0,
                   "locs": locs_for(gid, uncred)}
            cpf9 = g.get("_cp") if fs_on else None
            if cpf9 is not None:
                fsc9 = sum(a9[1] for k9, a9 in cpf9.it.items() if isinstance(k9, tuple) and k9 and k9[0] == "fs") * cpf9.m
                if fsc9 >= 0.005:
                    row["fsc"] = round(fsc9, 2)
            if src9 and px:
                row["pxSrc"] = src9
                if src9.startswith("dex:") and dex_key and dex_key[0] in self.spot.off_chains:
                    row["pxFrozen"] = True
                if age9 is not None:
                    row["pxAge"] = int(max(0, age9))
                if gid in pre_used9:
                    row["pxPre"] = 1
                    if pre_used9[gid][3]:
                        row["pxPreN"] = pre_used9[gid][3]
                    pk9 = pre_used9[gid][1]
                    if pk9 and pk9[0] in self.spot.off_chains:
                        row["pxFrozen"] = True
            if gid_pairs.get(gid) and qty * (px or 0) >= 1:
                row["ck"], row["ca"] = gid_pairs[gid][0][0], gid_pairs[gid][0][1]
            if dsym9:
                row["symSrc"] = "dexscreener"
            if not px and qty > 0 and gid in ex_gid:
                rf9 = _ref_px(sym, ex_gid[gid], sb=self, fx_name=fx_name)
                if rf9:
                    row["pxRef"] = rf9
            if not px and qty > 0 and gid not in unv9:
                gk9 = [f"{c9}:{a9}" for c9, a9 in gid_pairs.get(gid) or () if f"{c9}:{a9}" in self.spot.guarded]
                if gk9:
                    row["guard"] = 1
                    guard_held9.update(gk9)
                    if not row.get("ca"):
                        ck9, ca9 = gk9[0].split(":", 1)
                        row["ck"], row["ca"] = ck9, ca9
            if gid in unv9:
                row["unv"] = str(g.get("risk_unv") or sym)
                pr9 = (gid_pairs.get(gid) or gid_pairs_all.get(gid) or [(None, None)])[0]
                if pr9[1]:
                    row["ck"], row["ca"] = pr9[0], pr9[1]
            elif gid_pairs.get(gid) and any(spamguard.is_user_genuine(c9, a9) for c9, a9 in gid_pairs[gid]):
                row["genU"] = 1
                if not row.get("ca"):
                    row["ck"], row["ca"] = gid_pairs[gid][0][0], gid_pairs[gid][0][1]
            coins.append(row)
            if not px and qty > 0 and gid not in unv9:
                unpriced.append(dsym9 or sym)
                unpriced_w.append({"sym": dsym9 or sym, "qty": float(qty), "cost": float(avg) * float(qty) if avg else 0.0,
                                   "ref": float((row.get("pxRef") or {}).get("px") or 0) * float(qty),
                                   "where": fx_name.get(ex_gid.get(gid), ex_gid.get(gid)) if gid in ex_gid else "지갑",
                                   "ent": unpriced_ent(gid_pairs_all.get(gid) or gid_pairs.get(gid), ex_gid.get(gid), dsym9 or sym)})

    def _cards_extra(self, cst):
        (G, aliases, cex_px_pairs, cg_px_want9, cg_want9, coins, conn, fx_name, gid_pairs, gid_pairs_all, hold_prio, live_px, locs_by_gid, lp_pos_rows, meta_want9, now, override_px, pre_og9, pre_used9, proof_div9, pv_unk9, quarantined, stables, ub_coins, unpriced, unpriced_w, xp_unk9,) = (cst.G, cst.aliases, cst.cex_px_pairs, cst.cg_px_want9, cst.cg_want9, cst.coins, cst.conn, cst.fx_name, cst.gid_pairs, cst.gid_pairs_all, cst.hold_prio, cst.live_px, cst.locs_by_gid, cst.lp_pos_rows, cst.meta_want9, cst.now, cst.override_px, cst.pre_og9, cst.pre_used9, cst.proof_div9, cst.pv_unk9, cst.quarantined, cst.stables, cst.ub_coins, cst.unpriced, cst.unpriced_w, cst.xp_unk9,)
        pv_unk_px9 = []
        try:
            pv_unk_px9 = self._prov_price(pv_unk9, now, cg_want9, cg_px_want9, hold_prio)
        except Exception as e9:   # noqa: BLE001 [optional]
            calcguard.swallowed("view_b_cards:CardsMixin._build_cards[pv_unk_px9]", e9)
            log.warning("지금 잔고(첫 대사 전) 평가 실패(원장 숫자만): %s", logs.safe_err(e9)[:160])
        xp_unk_px9 = []
        if xp_unk9:
            self.spot.want_ex({it9["ex"] for it9 in xp_unk9})
            for it9 in xp_unk9:
                if _ex_stable_sym(it9["sym"]) or it9["sym"] in STABLE_GROUPS:
                    it9["stable"] = True
                    xp_unk_px9.append((it9, 1.0, None))
                else:
                    px9 = self.spot.ex_price(it9["ex"], it9["sym"])
                    xp_unk_px9.append((it9, float(px9 or 0), None))
                    if px9:
                        it9["src"] = "cex:" + it9["ex"]
        off9w = set(self.spot.off_chains or ())
        self._cgca_want = ({p9: u9 for p9, u9 in cg_want9.items() if p9[0] not in off9w}, {p9 for p9 in cg_px_want9 if p9[0] not in off9w})
        cgca.want(*self._cgca_want)
        self.spot.set_token_prio(hold_prio, skip=cex_px_pairs,
                                 slow={p9 for gid9 in quarantined for p9 in gid_pairs.get(gid9, ())}, meta_want=meta_want9)
        self.spot.proof_div = proof_div9
        new_div9 = {d9["gid"] for d9 in proof_div9} - set(self.__dict__.get("_proof_div_seen") or ())
        for d9 in proof_div9:
            if d9["gid"] in new_div9:
                log.warning("증명 거래소 시세 교차검증 괴리: %s g%s %s $%.6g vs DEX %s $%.6g (%+.0f%%, 풀 유동성 $%s, 보유 $%s)",
                            d9["sym"], d9["gid"], d9["ex"], d9["cex"], d9["pair"], d9["dex"], d9["diff"] * 100,
                            f"{d9['res']:,}", f"{d9['usd']:,.0f}")
        self.__dict__["_proof_div_seen"] = {d9["gid"] for d9 in proof_div9}
        for g9 in sorted(set(pre_used9) - set(self.__dict__.get("_pre_seen") or ())):
            log.info("거래 시작 전 평가: g%s %s — 업비트 마켓 없음 → %s $%.6g (%s)", g9, (G.get(g9) or {}).get("sym"), pre_used9[g9][0], pre_used9[g9][2],
                     ("입출금 증명 g" + ",".join(str(o9) for o9 in pre_og9[g9])) if pre_og9.get(g9) else f"증명 없음 · 거래소 {pre_used9[g9][3]}곳 일치")
        self.__dict__["_pre_seen"] = set(pre_used9)
        self._live_px = dict(live_px)
        okx_thresh = float((self.cfg.get("okx_dex") or {}).get("krw_threshold", 1_000_000))
        rate_now = self.spot.rate or 1400
        big_pairs = []
        for c2 in coins:
            if (c2.get("price") or 0) * c2["qty"] * rate_now >= okx_thresh \
                    and c2["key"].startswith("g") and c2["key"][1:].isdigit():
                big_pairs += gid_pairs.get(int(c2["key"][1:]), [])
        self.spot.want_okx(big_pairs)

        for cur4, q4 in sorted(ub_coins.items()):
            if q4 <= 0:
                continue
            entry = {"key": f"ub:{cur4}", "sym": cur4, "name": f"{cur4} · 업비트",
                     "qty": q4, "avg": 0,
                     "locs": [{"w": "업비트", "sub": "거래소 잔고 (실시간)", "qty": q4}]}
            if cur4 in STABLE_GROUPS:
                entry.update({"price": 1, "avg": 1})
                stables.append(entry)
            else:
                self.spot.want([cur4])
                entry["price"] = self.spot.ex_price("upbit", cur4) or 0
                if entry["price"]:
                    entry["pxSrc"] = f"cex:{fx_name.get('upbit', '업비트')}"
                    ag9 = self.spot.ex_age("upbit", cur4)
                    if ag9 is not None:
                        entry["pxAge"] = int(max(0, ag9))
                if not entry["price"]:
                    rf9 = _ref_px(cur4, "upbit", sb=self, fx_name=fx_name)
                    if rf9:
                        entry["pxRef"] = rf9
                coins.append(entry)
                if not entry["price"]:
                    unpriced.append(cur4)
                    unpriced_w.append({"sym": cur4, "qty": float(q4), "cost": 0.0,
                                       "ref": float((entry.get("pxRef") or {}).get("px") or 0) * float(q4), "where": "업비트",
                                       "ent": unpriced_ent((), "upbit", cur4)})

        rb_view, rb_debts = None, []
        rb_pairs9 = set()
        try:
            rb_st = rabby.load_state(paths.state("rabby_portfolio.json"))
            if (rb_st.get("wallets") or {}):
                known9 = {(ch9, rabby.ZERO if kd9 == "native" else str(ad9 or "").lower()) for ch9, ad9, kd9 in conn.execute("SELECT chain, address, kind FROM assets")}
                nopx_by_wallet = unpriced_pairs(coins, gid_pairs_all, locs_by_gid, seeds.seed_json("zero_value_companions.json", {}, base_dir=paths.BASE_DIR), set(override_px))
                for ch9, (mca9, _sc9) in chaincatalog.NATIVE_MIRROR.items():
                    known9.add((ch9, mca9))
                held9 = set()
                priced9 = {}
                row_px9 = {c9["key"]: float(c9.get("price") or 0) for c9 in coins + stables}
                for gid9, lr9 in locs_by_gid.items():
                    px9 = row_px9.get(f"g{gid9}", 0.0)
                    sym9 = str((G.get(gid9) or {}).get("sym") or "").upper()
                    for l9 in lr9:
                        p9 = str(l9["location"] or "").split(":")
                        if p9[0] != "wallet" or len(p9) < 3 or not p9[2]:
                            continue
                        held9.add((p9[1], p9[2].lower()))
                        u9 = float(Decimal(l9["qty_norm"])) * px9
                        if u9 > 0:
                            priced9.setdefault((p9[1], p9[2].lower()), []).append((sym9, u9))
                for it9, px9, why9 in pv_unk_px9:
                    if why9 or not px9:
                        continue
                    k9 = (it9["chain"], str(it9["wallet"]).lower())
                    held9.add(k9)
                    priced9.setdefault(k9, []).append((str(it9["sym"] or "").upper(), float(it9["qty"]) * float(px9)))
                lp_ids9 = set()
                lpf9 = statefile.read_json(paths.state("lp_positions.json"), {}) or {}
                for loc9 in list((lpf9.get("positions") or {}).keys()) + [l9 for _g9, l9, _q9 in lp_pos_rows]:
                    p9 = str(loc9).split(":")
                    if len(p9) >= 4:
                        lp_ids9.add((p9[1], p9[3]))
                        if p9[3].startswith("0x") and len(p9[3]) == 42 and p9[2].startswith("0x"):
                            known9.add((p9[1], p9[2].lower()))

                def rb_spam9(sym9, bc9, ca9):
                    why9 = _scam_name(sym9)
                    if why9:
                        return why9
                    ca9 = str(ca9 or "").lower()
                    if bc9 and ca9.startswith("0x") and len(ca9) == 42 and spamguard.major_of(sym9) \
                            and not spamguard.is_genuine(bc9, ca9):
                        return "가짜 대표 심볼(정품 CA 아님)"
                    return None
                labels9 = {a9: (aliases.get(a9) or self.addr_label.get(a9) or a9[:8]) for a9 in rabby.evm_wallets(self.cfg, include_disabled=True)}
                watch9 = set(rabby.watch_addrs(rb_st, list(labels9), self.__dict__.get("_bot_wallet_usd"), rabby.settings(self.cfg)["min_wallet_usd"]))
                labels9 = {a9: l9 for a9, l9 in labels9.items() if a9 in watch9}
                try:
                    import hl_spot
                    hl9 = hl_spot.known_addresses(self.cfg)
                except Exception as _cg9:   # noqa: BLE001 [fallback]
                    calcguard.swallowed("view_b_cards:CardsMixin._build_cards[override_pxrowgroup_id]", _cg9)
                    hl9 = set()
                rb_view = merge_scoped(rabby.merge, nopx_by_wallet, rb_st, resolve=rabby.chain_resolver(self.cfg, rb_st),
                                      wallet_chains_set=rabby.wallet_chains(self.cfg), known_pairs=known9, held_chains=held9,
                                      lp_ids=lp_ids9, priced_held=priced9, spam_fn=rb_spam9, labels=labels9,
                                      chain_names=CHAIN_NAME, now=now, min_usd=rabby.settings(self.cfg)["min_usd"],
                                      only_addrs=set(labels9),
                                      skip_proto=(lambda a9, p9, n9: "Hyperliquid 현물 원장에 반영" if (str(a9).lower() in hl9
                                                                                                and rabby.hl_proto(p9, n9)) else None))
                rb_pairs9 = {(x9.get("bc"), x9.get("ca"), str(x9.get("addr") or "").lower()) for x9 in rb_view.get("items") or ()
                             if x9.get("kind") in ("missed", "chain") and x9.get("ca")}
                coins.extend(rabby.rows_for(rb_view, labels9, now))
                rb_debts = rabby.debt_rows(rb_view, labels9)
                rb_view["labels"] = labels9
                rb_view["state"] = {"backoffUntil": rb_st.get("backoffUntil"), "lastErr": rb_st.get("lastErr"),
                                    "calls": rb_st.get("calls"), "enabled": rabby.settings(self.cfg)["enabled"],
                                    "minUsd": rabby.settings(self.cfg)["min_wallet_usd"]}
        except Exception as e9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_b_cards:CardsMixin._build_cards[rb_st]", e9)
            log.warning("Rabby 보강 실패(봇 숫자만 표시): %s", e9)
            rb_view, rb_debts = None, []
        rb_net = round((rb_view or {}).get("onlyUsd", 0.0) + sum(d9["usd"] for d9 in rb_debts), 2)
        (cst.pv_unk_px9, cst.rb_debts, cst.rb_net, cst.rb_pairs9, cst.rb_view, cst.xp_unk_px9,) = (pv_unk_px9, rb_debts, rb_net, rb_pairs9, rb_view, xp_unk_px9,)

    def _cards_prov_events(self, cst):
        (G, aliases, coins, fx_name, fx_transit, gid_pairs_all, live_px, my_all9, now, pid_row, prefs, pv_dl9, pv_unk_px9, quarantined, rb_pairs9, signer9, spoof_keys, stables, xp_unk_px9,) = (cst.G, cst.aliases, cst.coins, cst.fx_name, cst.fx_transit, cst.gid_pairs_all, cst.live_px, cst.my_all9, cst.now, cst.pid_row, cst.prefs, cst.pv_dl9, cst.pv_unk_px9, cst.quarantined, cst.rb_pairs9, cst.signer9, cst.spoof_keys, cst.stables, cst.xp_unk_px9,)
        pv9 = {"usd": 0.0, "n": 0, "skipped": {}, "chains": {}}
        try:
            if pv_dl9 or pv_unk_px9 or xp_unk_px9:
                rowpx9 = {str(c9.get("key")): c9 for c9 in coins + stables}
                for (gid9, loc9), d9 in sorted(pv_dl9.items(), key=lambda kv: (kv[0][0], kv[0][1])):
                    if not d9 or gid9 in quarantined:
                        continue
                    r9 = rowpx9.get(f"g{gid9}")
                    if r9 is not None:
                        r9["pvQty"] = float(r9.get("pvQty") or 0) + float(d9)
                        px9 = float(r9.get("price") or 0)
                    else:
                        px9 = 1.0 if (G.get(gid9) or {}).get("is_stable") else float(live_px.get(gid9) or 0)
                    u9 = float(d9) * px9
                    ch9 = loc9 if loc9.startswith("exchange:") else (loc9.split(":")[1] if loc9.count(":") >= 2 else "?")
                    c9 = pv9["chains"].setdefault(ch9, {"usd": 0.0, "n": 0})
                    c9["usd"] = round(c9["usd"] + u9, 2)
                    c9["n"] += 1
                    pv9["usd"] += u9
                    pv9["n"] += 1
                keep9 = []
                for it9, px9, why9 in pv_unk_px9:
                    if (it9["chain"], str(it9["addr"] or "").lower() if it9["chain"] != "sol" else it9["addr"], str(it9["wallet"]).lower()) in rb_pairs9:
                        pv9["skipped"]["Rabby 기준 행으로 표시"] = pv9["skipped"].get("Rabby 기준 행으로 표시", 0) + 1
                        continue
                    keep9.append((it9, px9, why9))
                px_of9 = {id(it9): (px9, why9) for it9, px9, why9 in keep9}
                labels_pv9 = {a9: (aliases.get(a9) or self.addr_label.get(a9) or a9[:8]) for a9 in {it9["wallet"] for it9, _p, _w in keep9}}
                m9 = provbal.merge(coins, stables, [it9 for it9, _p, _w in keep9], price_of=lambda it9: px_of9[id(it9)],
                                   labels=labels_pv9, chain_names=CHAIN_NAME, short=_short_addr, now=now)
                pv9["usd"] = round(pv9["usd"] + m9["usd"], 2)
                pv9["n"] += m9["n"]
                for k9, v9 in m9["skipped"].items():
                    pv9["skipped"][k9] = pv9["skipped"].get(k9, 0) + v9
                for ch9, v9 in m9["chains"].items():
                    c9 = pv9["chains"].setdefault(ch9, {"usd": 0.0, "n": 0})
                    c9["usd"] = round(c9["usd"] + v9["usd"], 2)
                    c9["n"] += v9["n"]
                if xp_unk_px9:
                    xpx9 = {id(it9): (px9, why9) for it9, px9, why9 in xp_unk_px9}
                    m9 = exprov.merge(coins, stables, [it9 for it9, _p, _w in xp_unk_px9], price_of=lambda it9: xpx9[id(it9)], names=fx_name)
                    pv9["usd"] = round(pv9["usd"] + m9["usd"], 2)
                    pv9["n"] += m9["n"]
                    for k9, v9 in m9["skipped"].items():
                        pv9["skipped"][k9] = pv9["skipped"].get(k9, 0) + v9
                    for ch9, v9 in m9["chains"].items():
                        c9 = pv9["chains"].setdefault(ch9, {"usd": 0.0, "n": 0})
                        c9["usd"] = round(c9["usd"] + v9["usd"], 2)
                        c9["n"] += v9["n"]
        except Exception as e9:   # noqa: BLE001 [optional]
            calcguard.swallowed("view_b_cards:CardsMixin._build_cards[pv_dl9]", e9)
            log.warning("지금 잔고(첫 대사 전) 집계 실패: %s", logs.safe_err(e9)[:160])
        pv9["usd"] = round(pv9["usd"], 2)
        self._prov_view = pv9
        grp4r = {}
        for e4r in fx_transit.values():
            st4r, fl4r = e4r.get("story"), e4r.get("story_flow")
            if st4r and fl4r is not None:
                grp4r.setdefault(id(fl4r), (fl4r, []))[1].append(st4r)
                e4r["story"] = []
        for fl4r, sts4r in grp4r.values():
            cat4r = []
            for st4r in reversed(sts4r):
                cat4r += st4r
            fl4r["events"] = sorted(cat4r + fl4r["events"], key=lambda e9: (e9.get("_ts") or 0, e9["t"]))
        d9j = prefs.get("dust_usd")
        try:
            dust_ev = 1.0 if d9j is None else max(0.0, float(d9j or 0))
        except (TypeError, ValueError):
            dust_ev = 1.0
        xfer_k9 = ("전송", "외부 전송", "입금 확인")
        stab_sym9 = set(STABLE_GROUPS) | {"FDUSD", "TUSD", "USDP", "PYUSD", "USD1", "USDS", "USD", "RLUSD"}
        def ev_usd(r9, g9):
            qn = abs(float(self._norm(r9)))
            if g9.get("is_stable"):
                return qn
            px9 = live_px.get(g9["gid"])
            if not px9 and not g9.get("is_fiat"):
                pairs9 = gid_pairs_all.get(g9["gid"]) or []
                if not pairs9:
                    px9 = self.spot.price(g9["sym"])
                elif all(spamguard.is_genuine(c9, a9) for c9, a9 in pairs9) and spamguard.major_of(g9["sym"]):
                    m9 = spamguard.major_of(g9["sym"])
                    px9 = self.spot.price({"WETH": "ETH", "WBTC": "BTC", "WBNB": "BNB", "WSOL": "SOL", "WPOL": "POL"}.get(m9, m9))
            then9 = float(r9["cost_usd"]) if (r9["cost_usd"] is not None and float(r9["cost_usd"]) > 0) else None
            if px9:
                return max(qn * float(px9), then9 or 0.0)
            return then9
        def ev_hide(e9):
            r9 = pid_row.get(e9.get("_pid"))
            if r9 is not None:
                if (r9["source_ns"], r9["source_id"], r9["asset_id"]) in spoof_keys:
                    return "scam", "가짜 전송 — 내가 서명하지 않은 tx 로 보유한 적 없는 수량을 '보냄'(주소 오염)"
                if int(r9["qty_base"]) == 0:
                    return "scam", "수량 0 전송(주소 오염)"
            if e9.get("k") not in xfer_k9 or dust_ev <= 0:
                return None
            if r9 is not None:
                g9 = G.get(r9["group_id"] or -r9["asset_id"]) or {}
                if not g9:
                    return None
                usd9 = ev_usd(r9, g9)
            else:
                try:
                    qn9 = abs(float(str(e9.get("q") or "").replace(",", "")))
                except ValueError:
                    return None
                s9 = str(e9.get("sym") or "").upper()
                px9 = 1.0 if s9 in stab_sym9 else (self.spot.ex_price("upbit", s9) or self.spot.price(s9))
                usd9 = qn9 * float(px9) if px9 else None
            if usd9 is None or usd9 >= dust_ev:
                return None
            if r9 is not None and r9["leg_kind"] == "acq" and r9["event"] in ("TRANSFER_IN", "PROGRAM_IN") and usd9 < 0.01:
                s9 = signer9.get((r9["source_ns"], r9["source_id"]))
                if not (s9 and spamguard.signer_mine(*s9, my_all9)):
                    return "scam", f"주소 오염 의심 초소액 수령 (${usd9:.4f})"
            return "dust", f"소액 ${usd9:,.2f} (기준 ${dust_ev:g} 미만)"
        pos_hid9 = []
        (cst.dust_ev, cst.ev_hide, cst.ev_usd, cst.pos_hid9,) = (dust_ev, ev_hide, ev_usd, pos_hid9,)

    def _cards_positions(self, cst):
        (G, aliases, debt_neg9, dust_ev, ev_hide, fb_cov9, fb_on, fx_name, fxb, gas_expense, gid_pairs, led_by_gid, live_px, pos_hid9, quarantined, realized_by_date, realized_krw_by_date, stake_inc, tax_rows, uncred_cost, uncred_gid, uncred_known, unv_fb9, unverified,) = (cst.G, cst.aliases, cst.debt_neg9, cst.dust_ev, cst.ev_hide, cst.fb_cov9, cst.fb_on, cst.fx_name, cst.fxb, cst.gas_expense, cst.gid_pairs, cst.led_by_gid, cst.live_px, cst.pos_hid9, cst.quarantined, cst.realized_by_date, cst.realized_krw_by_date, cst.stake_inc, cst.tax_rows, cst.uncred_cost, cst.uncred_gid, cst.uncred_known, cst.unv_fb9, cst.unverified,)
        wallet_disp = cst.disp9
        disp9 = {}
        for gid9, g9 in G.items():
            if g9.get("sym") == "TOKEN" and gid9 not in quarantined and gid_pairs.get(gid9):
                s9 = _meta_sym(gid9, gid_pairs=gid_pairs, sb=self)
                if s9:
                    disp9[gid9] = s9
        def venue_w(loc):
            parts = str(loc or "").split(":")
            if parts[0] == "exchange" and len(parts) >= 2:
                return fx_name.get(parts[1], parts[1])
            if parts[0] != "wallet":
                return None
            ch = parts[1] if len(parts) >= 2 else "?"
            wa = parts[2] if len(parts) >= 3 and parts[2] else None
            if not wa:
                return "SOL 지갑" if ch == "sol" else "EVM 지갑"
            label = aliases.get(wa) or self.addr_label.get(wa) or (_wdisp(ch, wa, disp=wallet_disp) or wa)[:8]
            if len(parts) >= 5 and parts[3] == "stake":
                return f"{label} · 스테이킹" if str(label).rstrip().endswith("지갑") else f"{label} 지갑 · 스테이킹"
            return label if str(label).rstrip().endswith("지갑") else f"{label} 지갑"
        positions = []
        pos_ev_full = []
        stab_ev = []
        for gid, g in sorted(G.items(), key=lambda kv: -(kv[1]["flows"][-1]["opened"] if kv[1]["flows"] else 0)):
            if g.get("is_fiat"):
                continue
            if g["is_stable"] or gid in quarantined:
                if g["is_stable"] and gid not in quarantined:
                    for fl in g["flows"]:
                        stab_ev.append((f"s{gid}", g["sym"], "스테이블 환전", fl["events"]))
                if gid in quarantined and not g["is_stable"]:
                    for fl in g["flows"]:
                        for e9 in fl["events"]:
                            pos_hid9.append(dict(e9, sym=g["sym"], _gid=gid, hide=g.get("risk_reason") or "격리(스팸) 자산", hideKind="scam"))
                rbd_s, ubd_s, sbd_s, rbdk_s, pbd_s = {}, {}, {}, {}, {}
                for fl in g["flows"]:
                    for k9, v9 in fl["rbd"].items():
                        rbd_s[k9] = rbd_s.get(k9, 0.0) + float(v9)
                    for k9, v9 in fl["rbdk"].items():
                        rbdk_s[k9] = rbdk_s.get(k9, 0.0) + float(v9)
                    for k9, v9 in fl["ubd"].items():
                        u9 = ubd_s.setdefault(k9, [0, 0.0]); u9[0] += v9[0]; u9[1] += float(v9[1])
                    for d9 in fl["sold_dates"]:
                        a9 = sbd_s.setdefault(d9, [0, 0]); a9[1] += 1
                    for d9 in fl.get("pay_dates") or ():
                        pbd_s[d9] = pbd_s.get(d9, 0) + 1
                rbd_s = {k9: round(v9, 2) for k9, v9 in sorted(rbd_s.items()) if abs(v9) >= 0.005 or abs(rbdk_s.get(k9, 0.0)) >= 0.5}
                if not (rbd_s or ubd_s):
                    continue
                o9 = min(fl["opened"] for fl in g["flows"])
                positions.append({
                    "realizedByDay": rbd_s, "actByDay": sbd_s, "payByDay": dict(sorted(pbd_s.items())),
                    "realizedKrwByDay": {k9: round(v9) for k9, v9 in sorted(rbdk_s.items()) if k9 in rbd_s},
                    "unvByDay": {k9: [v9[0], round(v9[1], 2)] for k9, v9 in sorted(ubd_s.items())},
                    "_gid": gid, "kind": "stable" if g["is_stable"] else "quarantined",
                    "unknownQty": 0, "fbAvg": 0, "fbCost": 0,
                    "unvQty": _f(float((unverified.get(gid) or {}).get("qty") or 0), 6) or 0,
                    "unvProceeds": _f(sum(v9[1] for v9 in ubd_s.values()), 2) or 0, "realizedFb": 0,
                    "soldProceeds": 0, "avgSell": 0, "avgKrw": 0, "avgSellKrw": 0, "costKrw": 0, "soldProceedsKrw": 0,
                    "key": f"s{gid}", "sym": g["sym"], "chain": "스테이블 환전" if g["is_stable"] else "격리 자산",
                    "status": "종료", "held": 0, "bought": 0, "movedQty": 0, "movedCost": 0, "soldQty": 0,
                    "avg": 0, "cost": 0, "realized": _f(sum(rbd_s.values()), 2) or 0, "unreal": 0,
                    "opened": datetime.fromtimestamp(o9, KST).strftime("%m-%d"), "_ots": o9, "fee": "$0.00",
                    "realizedKrw": round(sum(v9 for k9, v9 in rbdk_s.items() if k9 in rbd_s)),
                    "steps": ["스테이블 환전 차익" if g["is_stable"] else "격리 자산 매도"], "events": [],
                })
                _calc_err_mark(positions[-1], None, g)
                continue
            px = live_px.get(gid) or 0
            total_flows = len(g["flows"])
            k_all = g["qty_known"] + uncred_known.get(gid, Decimal(0))
            c_all = g["cost"] + uncred_cost.get(gid, Decimal(0))
            for i, fl in enumerate(g["flows"]):
                if fl["events"]:
                    vis9 = []
                    for e9 in fl["events"]:
                        h9 = ev_hide(e9)
                        if h9:
                            pos_hid9.append(dict(e9, sym=disp9.get(gid) or g["sym"], _gid=gid, hide=h9[1], hideKind=h9[0]))
                        else:
                            vis9.append(e9)
                    fl["events"] = vis9
                active = (g["cur"] is fl)
                held = float(led_by_gid.get(gid, Decimal(0)) + uncred_gid.get(gid, Decimal(0)) + debt_neg9.get(gid, Decimal(0))) if active else 0
                held_known = min(held, float(k_all))
                bought = float(fl["bought"])
                if bought <= 0 and not fl["events"] and not (fl["rbd"] or fl["ubd"]):
                    continue
                avg = float(c_all / k_all) if (active and k_all > EPS) \
                    else (float(fl["cost"] / fl["bought"]) if fl["bought"] > 0 else 0)
                status = "보유" if active and fl["realized"] - fl.get("pay_real", Decimal(0)) == 0 else \
                         ("부분 매도" if active else "종료")
                if active and not held > 0:
                    status = "종료"
                steps = ["거래소 매수" if any(e["k"] == "거래소 매수" for e in fl["events"])
                         else ("토큰 세일 매수" if any(e["k"] == "세일 매수" for e in fl["events"]) else "온체인 매수")]
                if any(e["k"] == "전송" and "업비트" in e["d"] for e in fl["events"]):
                    steps.append("거래소 입금")
                if fl["realized"] - fl.get("pay_real", Decimal(0)) != 0 or fl["sold_dates"]:
                    steps.append("전량 매도" if not active else "매도 진행")
                unreal = held_known * (px - avg) if (px and active and avg > 0) else 0
                unk_q = max(0.0, held - held_known)
                fb_avg = avg if (fb_on and avg > 0) else 0.0
                fb_cost = unk_q * fb_avg if fb_avg else 0.0
                if fb_avg and px and active and unk_q > 0:
                    unreal += unk_q * (px - fb_avg)
                fl_ub9 = fl["ubd"]
                u_fb = ({"qty": sum((fl.get("ubq") or {}).values(), Decimal(0)),
                         "proceeds": sum((v9[1] for v9 in fl_ub9.values()), Decimal(0)),
                         "by_date": {d9: {"qty": (fl.get("ubq") or {}).get(d9, Decimal(0)), "proceeds": v9[1]} for d9, v9 in fl_ub9.items()}}
                        if fl_ub9 and gid in unverified else None)
                fbr9 = avg if (fb_on and avg > 0) else 0.0
                unv_q = float(u_fb["qty"]) if u_fb else 0.0
                unv_p = float(u_fb["proceeds"]) if u_fb else 0.0
                realized_fb = (unv_p - unv_q * fbr9) if (u_fb and fbr9) else 0.0
                rbd_c = {k9: float(v9) for k9, v9 in fl["rbd"].items()}
                rbdk_c = {k9: float(v9) for k9, v9 in fl["rbdk"].items()}
                if u_fb and fbr9:
                    fc9 = fb_cov9.setdefault(gid, [0.0, 0.0, 0.0])
                    fc9[0] += unv_q
                    fc9[1] += unv_q * fbr9
                    fc9[2] += realized_fb
                    for dk_f, ud_f in sorted((u_fb.get("by_date") or {}).items()):
                        pnl_f = float(ud_f["proceeds"]) - float(ud_f["qty"]) * fbr9
                        rt_f, rsrc_f = fxb.rate_src(int(datetime.strptime(dk_f + " 23:59", "%Y-%m-%d %H:%M").replace(tzinfo=KST).timestamp()))
                        realized_by_date[dk_f] = realized_by_date.get(dk_f, 0) + pnl_f
                        realized_krw_by_date[dk_f] = realized_krw_by_date.get(dk_f, 0) + pnl_f * rt_f
                        uf9 = unv_fb9.setdefault(dk_f, {}).setdefault(gid, [Decimal(0), Decimal(0)])
                        uf9[0] += Decimal(ud_f["qty"])
                        uf9[1] += Decimal(ud_f["proceeds"])
                        rbd_c[dk_f] = rbd_c.get(dk_f, 0.0) + pnl_f
                        rbdk_c[dk_f] = rbdk_c.get(dk_f, 0.0) + pnl_f * rt_f
                        tax_rows.append({"sold": dk_f, "sym": g["sym"], "ticker": g["sym"], "ex": "평균가 폴백",
                                         "qty": _f(float(ud_f["qty"]), 4), "acq": _f(float(ud_f["qty"]) * fbr9, 2),
                                         "disp": _f(float(ud_f["proceeds"]), 2), "fee": 0, "rate": round(rt_f, 4), "rateSrc": rsrc_f,
                                         "_acq": float(ud_f["qty"]) * fbr9, "_disp": float(ud_f["proceeds"]), "_qty": float(ud_f["qty"])})
                sold_q = float(fl["sold"]); proceeds_f = float(fl.get("proceeds", Decimal(0)))
                act_c = {}
                src_c = {}
                pay_c = {}
                for e9 in fl["events"]:
                    k9 = e9["k"]
                    j9 = 1 if "매도" in k9 else (0 if "매수" in k9 else -1)
                    if j9 == 1 and e9.get("_pay"):
                        j9 = -1
                        dk9p = acct_norm.iso_day(e9["_ts"]) if e9.get("_ts") else e9["t"][:5]
                        pay_c[dk9p] = pay_c.get(dk9p, 0) + 1
                    dk9 = acct_norm.iso_day(e9["_ts"]) if e9.get("_ts") else e9["t"][:5]
                    if j9 >= 0:
                        a9 = act_c.setdefault(dk9, [0, 0])
                        a9[j9] += 1
                    if k9 != "평단 갱신":
                        c9 = src_c.setdefault(e9.get("src") or "", {}).setdefault(dk9, [0, 0, 0, 0])
                        c9[0] += 1
                        if j9 >= 0:
                            c9[1 + j9] += 1
                        if k9 == "입금 확인":
                            c9[3] += 1
                rbd_o = {k9: round(v9, 2) for k9, v9 in sorted(rbd_c.items())
                         if abs(v9) >= 0.005 or abs(rbdk_c.get(k9, 0.0)) >= 0.5}
                positions.append({
                    "realizedByDay": rbd_o,
                    "realizedKrwByDay": {k9: round(v9) for k9, v9 in sorted(rbdk_c.items()) if k9 in rbd_o},
                    "realizedKrw": round(sum(v9 for k9, v9 in rbdk_c.items() if k9 in rbd_o)),
                    "actByDay": act_c, "srcAct": src_c, "evN": len(fl["events"]),
                    "payByDay": pay_c,
                    "paidQty": _f(fl.get("paid", Decimal(0)), 6) or 0, "paidUsd": _f(fl.get("paid_usd", Decimal(0)), 2) or 0,
                    "payReal": _f(fl.get("pay_real", Decimal(0)), 2) or 0,
                    "unvByDay": {k9: [v9[0], round(float(v9[1]), 2)] for k9, v9 in sorted(fl["ubd"].items())},
                    "_gid": gid, "_act": active,
                    "unknownQty": _f(unk_q, 6) or 0, "fbAvg": _f(fbr9 if (u_fb and fbr9) else fb_avg, 6) or 0, "fbCost": _f(fb_cost, 2) or 0,
                    "unvQty": _f(unv_q, 6) or 0, "unvProceeds": _f(unv_p, 2) or 0, "realizedFb": _f(realized_fb, 2) or 0,
                    "soldProceeds": _f(proceeds_f, 2) or 0,
                    "avgSell": _f(proceeds_f / sold_q, 6) if sold_q > 0 else 0,
                    "avgKrw": _f(float(fl.get("cost_krw", 0)) / bought, 4) if bought > 0 else 0,
                    "avgSellKrw": _f(float(fl.get("proceeds_krw", 0)) / sold_q, 4) if sold_q > 0 else 0,
                    "costKrw": _f(float(fl.get("cost_krw", 0)), 0) or 0,
                    "soldProceedsKrw": _f(float(fl.get("proceeds_krw", 0)), 0) or 0,
                    "key": f"g{gid}" if active else f"g{gid}f{i}",
                    "sym": disp9.get(gid) or g["sym"], "chain": self._flow_chain(fl),
                    **({"symSrc": "dexscreener"} if gid in disp9 else {}),
                    "realizedChainByDay": {d9: " · ".join(sorted(v9)) for d9, v9 in (fl.get("rch") or {}).items()},
                    "status": status, "held": held, "bought": bought,
                    "movedQty": _f(fl["moved_qty"], 6) or 0,
                    "movedCost": _f(fl["moved_cost"], 2) or 0,
                    **({"movedTo": [[k9, _f(v9[0], 6), bool(v9[1])] for k9, v9 in sorted(fl["mv_to"].items(), key=lambda x9: -x9[1][0])]} if fl.get("mv_to") else {}),
                    **({"inFrom": [[k9, _f(v9[0], 6), _f(v9[1], 2), round(v9[2])] for k9, v9 in sorted(fl["in_from"].items(), key=lambda x9: -x9[1][0])]} if fl.get("in_from") else {}),
                    "nBuy": fl.get("nb", 0),
                    "soldQty": _f(fl["sold"], 6) or 0,
                    "lpConvQty": _f(fl.get("lpconv", Decimal(0)), 6) or 0,
                    "avg": _f(avg, 6) or 0, "cost": _f(fl["cost"], 2) or 0,
                    "realized": _f(fl["realized"], 2) or 0,
                    "unreal": _f(unreal, 2) or 0,
                    "opened": datetime.fromtimestamp(fl["opened"], KST).strftime("%m-%d"),
                    "_ots": fl["opened"],
                    "fee": f"${float(fl['fee']):,.2f}",
                    "steps": steps, "events": [{k9: v9 for k9, v9 in e9.items() if not k9.startswith("_")} for e9 in fl["events"][-(60 + min(100, fl.get("story_n", 0))):]],
                    "dust": bool(active and held > 0 and px and held * px < dust_ev),
                })
                if fl.get("oa_sold"):
                    positions[-1]["offcA"] = {"qty": _f(fl["oa_sold"], 6) or 0, "realized": _f(fl.get("oa_real", Decimal(0)), 2) or 0}
                if fl.get("fs_c") or fl.get("fs_rz"):
                    positions[-1]["fsEst"] = {"cost": _f(fl.get("fs_c", Decimal(0)), 2) or 0, "qty": _f(fl.get("fs_q", Decimal(0)), 6) or 0,
                                              "real": round(float(fl.get("fs_rz") or 0), 2)}
                _calc_err_mark(positions[-1], fl, g)
                pos_ev_full.append((positions[-1]["key"], positions[-1]["sym"], positions[-1]["chain"], fl["events"]))
        _add_gas_card(gas_expense, positions, tax_rows)
        _add_stake_card(stake_inc, positions, tax_rows)
        positions.sort(key=lambda p: (not p.get("_act"), -p["_ots"]))
        _pos_all_dbg = positions if os.environ.get("TJ_REPLAY_DEBUG") == "1" else None
        head9 = positions[:400]
        syms9 = {acct_norm.canon(p9["sym"]) for p9 in head9}
        tail9 = [p9 for p9 in positions[400:]
                 if p9.get("realizedByDay") or p9.get("unvByDay") or (p9.get("soldQty") or 0) > 0 or p9.get("actByDay")]
        syms9 |= {acct_norm.canon(p9["sym"]) for p9 in tail9}
        in9 = {id(p9) for p9 in tail9}
        tail9 += [p9 for p9 in positions[400:] if id(p9) not in in9 and (p9.get("movedQty") or 0) > 0 and acct_norm.canon(p9["sym"]) in syms9]
        pos_cut9 = {"total": len(positions), "kept": len(head9) + len(tail9), "dropped": len(positions) - len(head9) - len(tail9)}
        positions = head9 + sorted(tail9, key=lambda p9: -p9["_ots"])
        for p9 in positions:
            p9.pop("_act", None)
        if _pos_all_dbg is None:
            for p9 in positions:
                p9.pop("_gid", None)
        (cst._pos_all_dbg, cst.disp9, cst.pos_cut9, cst.pos_ev_full, cst.positions, cst.stab_ev, cst.syms9, cst.venue_w,) = (_pos_all_dbg, disp9, pos_cut9, pos_ev_full, positions, stab_ev, syms9, venue_w,)

    def _cards_daily_gates(self, cst):
        (G, conn, ex_gid, gid_pairs_all, native_kind9,) = (cst.G, cst.conn, cst.ex_gid, cst.gid_pairs_all, cst.native_kind9,)
        ca_all = {r10["group_id"] for r10 in conn.execute(
            "SELECT DISTINCT group_id FROM assets WHERE kind='token'"
            " AND address IS NOT NULL AND group_id IS NOT NULL").fetchall()}
        native_c9 = set()
        for gid9 in sorted(native_kind9 & ca_all):
            g9 = G.get(gid9)
            prs9 = gid_pairs_all.get(gid9) or []
            m9 = spamguard.major_of(g9["sym"]) if g9 else None
            if prs9 and m9 and m9 == str(g9["sym"]).upper() and m9 not in STABLE_GROUPS \
                    and all(spamguard.is_genuine(c9, a9) for c9, a9 in prs9):
                native_c9.add(gid9)
        ca_all -= native_c9
        ex_c9 = set()
        for gid9 in sorted(ex_gid):
            g9 = G.get(gid9)
            m9 = spamguard.major_of(g9["sym"]) if g9 else None
            if g9 and str(g9["sym"]).upper() in EX_CANDLE_SYMS and not g9.get("is_stable") and not g9.get("is_fiat"):
                ex_c9.add(gid9)
                continue
            if (m9 and m9 == str(g9["sym"]).upper() and "USD" not in m9 and m9 != "DAI"
                    and not g9.get("is_stable") and not g9.get("is_fiat")):
                ex_c9.add(gid9)
        (cst.ca_all, cst.ex_c9, cst.native_c9,) = (ca_all, ex_c9, native_c9,)
