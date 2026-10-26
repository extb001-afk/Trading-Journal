from __future__ import annotations
import acct_norm, histmark, paths, statefile, view_attur
import histcurve
import os
import time
import xparts
from datetime import datetime
from datetime import timedelta
from decimal import Decimal
from decimal import InvalidOperation
from view_common import DAILY_LIVE_WIN
from view_common import DAILY_LQ_V
from view_common import DAILY_PX_KEEP
from view_common import DAILY_V
from view_common import DC_SMALL_USD
from view_common import EPS
from view_common import HL_MAXWAIT_S
from view_common import HL_SETTLE_S
from timeutil import KST
from view_common import STABLE_GROUPS
from view_common import _f
from view_misc import _px_took
from view_misc import _rate_state
from view_pxfix import _bind_px_blocks
from view_pxfix import _capture_px_blocks
from view_pxfix import _migrate_px_blocks
from view_pxfix import _px1004_reset
from view_pxfix import _pxfix_backup
from view_pxfix import _reprice_now_days
from view_regroup import daily_inval_apply
from view_regroup import _relabel_daily_gids
from view_txkey import _txk
from view_xv import XQ_X_KEYS
from view_xv import _ufc_ku
from view_xv import _x_end
from view_xv import _x_sync_entry
from view_xv import _xv_checked
from view_xv import _xv_disk
from view_xv import _xv_ob
from view_xv import _xv_obs_parts
from view_xv import _xv_parts
import logging
import calcguard  # noqa: E402

log = logging.getLogger('tj-web')


def _fpx(ck, gid, *, dpx, gsrc, today_iso, live_px):
    e = dpx.get(ck) or {}
    sid = str(gid)
    cur = float((e.get("p") or {}).get(sid) or 0)
    gsrc[(ck, gid)] = e
    if not cur and ck < today_iso:
        pk = (datetime.strptime(ck, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        cur = float(((dpx.get(pk) or {}).get("p") or {}).get(sid) or 0)
        if cur:
            e = dpx.get(pk) or {}
            gsrc[(ck, gid)] = e
    elif not cur:
        cur = float(live_px.get(gid) or 0)
    b = (e.get("fp") or {}).get(sid)
    return (float(b) if b else cur), cur


def _wset(ck, *, tiso, now, sb):
    if ck == tiso:
        return now
    c = (getattr(sb, "daily", None) or {}).get(ck)
    w = c.get("wdt") if isinstance(c, dict) else None
    return w if isinstance(w, dict) else {}


def _add(ck, grp, lbl, usd, *, keys, acc_k):
    if ck not in keys:
        return
    a = acc_k.setdefault(ck, {}).setdefault(grp, {})
    a[lbl] = a.get(lbl, 0.0) + usd


def _bands(ck, gm, bases):
    par = {g0: g0 for g0 in gm}

    def root(g0):
        while par[g0] != g0:
            par[g0] = par[par[g0]]
            g0 = par[g0]
        return g0
    for pm in bases:
        cl = []
        for gid in sorted((g0 for g0 in gm if pm(g0) > 0), key=lambda g0: (pm(g0), g0)):
            if cl and pm(gid) <= cl[-1][0] * 1.2:
                cl[-1][1].append(gid)
            else:
                cl.append([pm(gid), [gid]])
        for _p, gs in cl:
            for g0 in gs[1:]:
                par[root(g0)] = root(gs[0])
    out = {}
    for g0 in sorted(gm):
        out.setdefault(root(g0), []).append(g0)
    return list(out.values())


def _ref(gm, gs):
    return max(gs, key=lambda g0: (sum(abs(v) for v in gm[g0].values()), -g0))


def _sroot(i, *, sup):
    while sup[i] != i:
        sup[i] = sup[sup[i]]
        i = sup[i]
    return i


def _day_ts(ck):
    d = datetime.strptime(ck, "%Y-%m-%d").replace(tzinfo=KST)
    return d.timestamp(), d.replace(hour=23, minute=59, second=59).timestamp()


def _rate_of(row, *, keys, today_ck, rate_now):
    if keys.get(row.get("date")) == today_ck:
        return rate_now
    u = row.get("usdt")
    return float(u) if u else None


def _gsum(g, *, skip9s):
    return sum(float(v) for k, v in (g or {}).items() if k not in skip9s)


def _xu_px(xu):
    out = {}
    for s, a in (xu.items() if isinstance(xu, dict) else ()):
        try:
            q, u = float(a[0]), float(a[1])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        if q > 0 and u >= 0:
            out[str(s).upper()] = (q, u / q)
    return out


def _fnum(v):
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _xu_of(v):
    out = {}
    for s, a in (v.items() if isinstance(v, dict) else ()):
        try:
            q, u = float(a[0]), float(a[1])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        if q > 0 and u >= 0:
            out[str(s).upper()] = (q, u)
    return out


def _frozen_ub_cut(c, end_ts, added, *, ub_tl, G, xu_cut):
    only = {g for g in added if g in ub_tl and g in G}
    if not only or not c.get("xu"):
        return 0.0
    cut, rest, _p = xu_cut(c["xu"], end_ts, only)
    if cut <= 0:
        return 0.0
    c["val"] = _f(Decimal(str(c["val"])) - Decimal(str(cut)), 2) or 0
    c["x"] = round(float(c.get("x") or 0) - cut, 2)
    if c.get("xc"):
        xc = float(c["xc"]) - cut
        if xc >= 1:
            c["xc"] = round(xc, 2)
        else:
            c.pop("xc", None)
    if rest:
        c["xu"] = rest
    else:
        c.pop("xu", None)
    log.info("일별 동결 항목: 새로 소급한 업비트 원장 그룹 %s — 원장 밖 잔고 x 에서 %.2f 뺌(이중 계상 방지)", sorted(only), cut)
    return cut


def _led_old(lg, ts, *, lg_now):
    if not lg_now:
        return False
    try:
        return int(float(lg)) != lg_now if lg is not None else float(ts or 0) < lg_now
    except (TypeError, ValueError):
        return True


def _wdt_at(end_ts, *, tr_by):
    return {u: [g, float(q)] for g, lst in tr_by.items() for t, q, u in lst if t <= end_ts}


def _lp_after(gid, to_ms, *, lp_tls):
    s = Decimal(0)
    for ts, dq in reversed(lp_tls.get(gid, ())):
        if ts * 1000 <= to_ms:
            break
        s += dq
    return s


def _lp_obs_set(end_ts, parts, ts=None, *, lp_to):
    to = xparts.rest_obs_at(parts, end_ts, ts)
    k = int(end_ts * 1000)
    if to is None:
        lp_to.pop(k, None)
    else:
        lp_to[k] = int(to * 1000)


def _lp_moved_after(to_ms, *, lp_tls, skip_gids):
    for g, tl in lp_tls.items():
        if skip_gids and g in skip_gids:
            continue
        for ts, dq in reversed(tl):
            if ts * 1000 <= to_ms:
                break
            if abs(dq) > EPS:
                return True
    return False


def _xq_new(have, *, xq):
    return {e for e in str(xq or "").split(",") if e} - {e for e in str(have or "").split(",") if e}


def _pxfix_key(*, day_close, today_kst, now_ts, dpx, sb):
    return (getattr(day_close, "gen", None), today_kst.strftime("%Y-%m-%d"), int(now_ts // 3600),
            sum(len(e.get("p") or {}) - len(e.get("k") or {}) - len(e.get("dcn") or ())
                for k, e in dpx.items() if not k.startswith("_") and isinstance(e, dict)),
            sum(len(c.get("g") or ()) for k, c in sb.daily.items() if not k.startswith("_") and isinstance(c, dict)))


def _live_allow(c):
    if c.get("src") != "live":
        return None
    return {str(x) for x in (c.get("z") or ())}


def _krw_close(ck, *, dpx, krw_at):
    xv = (dpx.get(ck) or {}).get("xv")
    p = _xv_parts(xv) if isinstance(xv, dict) and xv.get("v") == xparts.GEN else None
    if p and any(k in p for k in xparts.KRW):
        return sum(float((p.get(k) or (0,))[0] or 0) for k in xparts.KRW)
    return krw_at(_day_ts(ck)[1])


def _krw_sum(lst, ck):
    a, b = _day_ts(ck)
    return float(sum((d for t, d in lst if a <= t <= b), Decimal(0)))


def _xu_keep(v):
    return {s: [round(q, 12), round(u, 2)] for s, (q, u) in _xu_of(v).items()}


class DailyMixin:

    def _hist_flow_kit(self, G, skip_gids, offc_ids, transit, rate_now, today_iso, daily) -> dict:
        try:
            return self._hist_flow_kit_x(G, skip_gids, offc_ids, transit, rate_now, today_iso, daily)
        except Exception as e9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_daily:DailyMixin._hist_flow_kit", e9)
            log.warning("장기 곡선 입출금 재료 실패: %s", e9)
            return None

    def _hist_flow_kit_x(self, G, skip_gids, offc_ids, transit, rate_now, today_iso, daily) -> dict:
        f0 = (datetime.strptime(today_iso, "%Y-%m-%d") - timedelta(days=len(daily) - 1)).strftime("%Y-%m-%d") if daily else None
        dpx9 = self.daily_px or {}
        return {
            "today": today_iso,
            "G": {gid: {"sym": g.get("sym"), "is_fiat": bool(g.get("is_fiat")), "is_stable": bool(g.get("is_stable"))} for gid, g in G.items()},
            "skip": frozenset(skip_gids or ()), "offc": frozenset(offc_ids or ()), "rate": rate_now,
            "transit": [dict(e9) for e9 in (transit or ()) if isinstance(e9, dict)],
            "wdt": {k9: {"wdt": dict(c9["wdt"])} for k9, c9 in (self.daily or {}).items()
                    if isinstance(c9, dict) and isinstance(c9.get("wdt"), dict)},
            "dpx_dc": {k9: {kk: (dict(vv) if isinstance(vv, dict) else vv) for kk, vv in v9.items() if kk in ("p", "fp", "lp")}
                       for k9, v9 in dpx9.items() if isinstance(v9, dict) and len(k9) == 10 and k9[4] == "-"
                       and k9 >= histcurve.FIRST_DAY and (f0 is None or k9 < f0)},
        }

    def _daily_flows(self, conn, daily, G, today_kst, live_px, skip_gids=frozenset(), rate_now=None, transit=None, offc_ids=frozenset(),
                     days=None, dpx=None, fx_day=None) -> dict:
        hist9, bf_box = days is not None, self.__dict__.get("_att_bf")
        if not hist9:
            self._venue_flow = None
            self._flow_px_delta, self._flow_att_px, self._flow_att_rep = {}, {}, {}
            self._flow_nf = set()
        if not daily and not hist9:
            return {}
        keys = {}
        if hist9:
            keys = {str(d9): str(d9) for d9 in days}
            if not keys:
                return {}
        else:
            for i in range(29, -1, -1):
                d9 = today_kst - timedelta(days=i)
                keys[d9.strftime("%Y-%m-%d")] = d9.strftime("%m-%d")
        lo_ts = datetime.strptime(min(keys), "%Y-%m-%d").replace(tzinfo=KST).timestamp()
        vflow9 = {} if not hist9 else None
        flow_px_at = self._flow_att_px if not hist9 else {} if bf_box is None else bf_box.setdefault("px", {})
        dpx = (self.daily_px or {}) if dpx is None else dpx
        today_iso9 = today_kst.strftime("%Y-%m-%d")
        acc = {}
        gpx = {}
        gpxc = {}
        gsrc9 = {}
        held9 = {}
        held_ext9 = set()
        def hold9(ck9, sym9, gid9, lbl9, q9, is_ext9):
            h9 = held9.setdefault((ck9, str(sym9).upper()), {}).setdefault(gid9, {})
            h9[lbl9] = h9.get(lbl9, Decimal(0)) + q9
            if is_ext9:
                held_ext9.add(lbl9)
        nofx9 = {}
        ext9 = set()
        sale_tx9 = getattr(self, "_sale_send_tx", None) or set()
        arr_tx9 = set()
        for w9 in (transit or ()):
            if not isinstance(w9, dict) or w9.get("state") != "arrived":
                continue
            t9 = str(w9.get("txid_raw") or "").strip() or (str(w9.get("txid") or "") if not str(w9.get("txid") or "").startswith("amt:") else "")
            if t9:
                arr_tx9.add(_txk(t9))
        acc_k = {}
        debts9 = type(self)._flow_debts()
        for ts9, qb9, dec9, gid9, ev9, lk9, ns9, rsym9, lseq9, sid9, loc9 in conn.execute(
                "SELECT p.event_ts, p.qty_base, a.decimals, COALESCE(a.group_id, -a.asset_id), p.event, p.leg_kind, p.source_ns, a.symbol,"
                " p.leg_seq, p.source_id, p.location"
                " FROM postings p JOIN assets a ON a.asset_id = p.asset_id WHERE p.event_ts >= ?"
                " AND p.location NOT LIKE 'out:%' AND p.location NOT LIKE 'lp:%'", (int(lo_ts),)):
            if ev9 in self.FLOW_SKIP_EV or lk9 in ("fee", "gas") or gid9 in skip_gids:
                continue
            if histmark.exf_is_debt_int(ev9, lseq9, ns9, sid9):
                continue
            if histmark.exf_is_fut(ev9, ns9):
                continue
            g9 = G.get(gid9)
            if not g9 or g9.get("is_fiat"):
                continue
            ck9 = datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d")
            if ck9 not in keys:
                continue
            if g9.get("is_stable"):
                px9 = pxc9 = 1.0
            else:
                px9, pxc9 = _fpx(ck9, gid9, dpx=dpx, gsrc=gsrc9, today_iso=today_iso9, live_px=live_px)
            try:
                q9 = Decimal(int(qb9)) / (Decimal(10) ** int(dec9 if dec9 is not None else 18))
            except (TypeError, ValueError, InvalidOperation):
                continue
            sym9 = g9.get("sym") or "?"
            lbl9 = f"{self.FLOW_KO.get(ev9, ev9)} {sym9}"
            if ev9 == "TRANSFER_OUT" and str(sid9 or "").lower() in sale_tx9:
                lbl9 = f"세일 참가금 {sym9}"
            if offc_ids and (ns9, sid9) in offc_ids:
                lbl9 = f"{self.FLOW_OFFC_KO[0 if q9 < 0 else 1]} {sym9}"
            if ev9 == "EXF_ADJUST" and str(sid9 or "").startswith("exflate:"):
                lbl9 = f"{type(self).FLOW_LATE_KO} {sym9}"
            elif ev9 in ("EXF_ADJUST", "EX_ADJUST") and q9 < 0:
                db9 = (debts9.get(ns9) or {}).get(str(rsym9 or "").upper())
                if db9 is not None and -db9 * Decimal("0.5") <= -q9 <= -db9 * Decimal("1.01") + EPS:
                    lbl9 = f"{type(self).FLOW_DEBT_KO} {sym9}"
                    try:
                        if int(ts9) < int(str(sid9).rsplit(":", 1)[1]) - 60:
                            lbl9 = f"{type(self).FLOW_DEBT_FIRST_KO} {sym9}"
                    except (IndexError, ValueError, TypeError):
                        pass
            if ev9 in ("TRANSFER_IN", "PROGRAM_IN") and arr_tx9 and _txk(str(sid9 or "")) in arr_tx9:
                lbl9 = f"{type(self).FLOW_ARR_KO} {sym9}"
                is_ext9 = False
            else:
                is_ext9 = ev9 not in type(self).FLOW_INT_EV
            if not px9:
                if ck9 < today_iso9:
                    hold9(ck9, sym9, gid9, lbl9, q9, is_ext9)
                continue
            if is_ext9:
                ext9.add(lbl9)
            a9 = acc.setdefault(ck9, {}).setdefault(sym9.upper(), {}).setdefault(gid9, {})
            a9[lbl9] = a9.get(lbl9, Decimal(0)) + q9
            gpx[(ck9, gid9)] = px9
            gpxc[(ck9, gid9)] = pxc9
            if vflow9 is not None and q9:
                vf9 = vflow9.setdefault(str(loc9 or ""), [0.0, 0.0])
                vf9[0 if q9 > 0 else 1] += abs(float(q9) * float(px9))
        if transit is not None:
            st9 = {str(e9["uuid"]): e9.get("state") for e9 in transit}
            now9 = {str(e9["uuid"]): [e9["gid"], float(e9["qty"])] for e9 in transit if e9.get("state") == "pending"}
            tiso9 = today_kst.strftime("%Y-%m-%d")
            for ck9 in sorted(keys):
                pk9 = (datetime.strptime(ck9, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
                cur9, prv9 = _wset(ck9, tiso=tiso9, now=now9, sb=self), _wset(pk9, tiso=tiso9, now=now9, sb=self)
                for u9, v9, sg9 in [(u9, v9, 1) for u9, v9 in cur9.items() if u9 not in prv9] + \
                                   [(u9, v9, -1) for u9, v9 in prv9.items() if u9 not in cur9]:
                    try:
                        gid9, q9 = int(v9[0]), Decimal(str(v9[1])) * sg9
                    except (TypeError, ValueError, IndexError, InvalidOperation):
                        continue
                    g9 = G.get(gid9)
                    if not g9 or g9.get("is_fiat") or gid9 in skip_gids:
                        continue
                    px9, pxc9 = (1.0, 1.0) if g9.get("is_stable") else _fpx(ck9, gid9, dpx=dpx, gsrc=gsrc9, today_iso=today_iso9, live_px=live_px)
                    sym9 = g9.get("sym") or "?"
                    if not px9:
                        if ck9 < today_iso9:
                            out9 = sg9 < 0 and st9.get(u9) == "out"
                            hold9(ck9, sym9, gid9, f"{self.FLOW_KO.get('EXF_WITHDRAW', '거래소 출금')} {sym9} · 도착 없음" if out9 else f"전송 중 {sym9}", q9, out9)
                        continue
                    if sg9 < 0 and st9.get(u9) == "out":
                        lbl9 = f"{self.FLOW_KO.get('EXF_WITHDRAW', '거래소 출금')} {sym9} · 도착 없음"
                        ext9.add(lbl9)
                    else:
                        lbl9 = f"전송 중 {sym9}"
                    a9 = acc.setdefault(ck9, {}).setdefault(sym9.upper(), {}).setdefault(gid9, {})
                    a9[lbl9] = a9.get(lbl9, Decimal(0)) + q9
                    gpx.setdefault((ck9, gid9), px9)
                    gpxc.setdefault((ck9, gid9), pxc9)
        if not hist9 or bf_box is not None:
            (bf_box.setdefault("rep", {}) if hist9 else self._flow_att_rep).update(view_attur.flow_prev_reprice(acc, (gpx, gpxc, gsrc9), G, (dpx, (bf_box.get("src") if hist9 else self.__dict__.get("_daily_att_src")) or {}), today_iso9, type(self).ATT_NOPX_BAND, held9))
        for (ck9, su9), gh9 in sorted(held9.items()):
            gm9 = (acc.get(ck9) or {}).get(su9) or {}
            if not gm9:
                continue
            s_h9 = sum((v9 for lv9 in gh9.values() for v9 in lv9.values()), Decimal(0))
            s_p9 = sum((v9 for lv9 in gm9.values() for v9 in lv9.values()), Decimal(0))
            if not s_h9 or not s_p9 or (s_h9 > 0) == (s_p9 > 0):
                continue
            fr9 = min(Decimal(1), abs(s_p9) / abs(s_h9))
            net9 = {g0: sum(lv9.values(), Decimal(0)) for g0, lv9 in gm9.items()}
            ref9g = max((g0 for g0 in gm9 if net9[g0] * s_p9 > 0), key=lambda g0: (abs(net9[g0]), -g0))
            for gid9, lv9 in gh9.items():
                a9 = acc[ck9][su9].setdefault(gid9, {})
                for l9, q9 in lv9.items():
                    a9[l9] = a9.get(l9, Decimal(0)) + q9 * fr9
                    if l9 in held_ext9:
                        ext9.add(l9)
                gpx[(ck9, gid9)] = gpx[(ck9, ref9g)]
                gpxc[(ck9, gid9)] = gpxc[(ck9, ref9g)]
                gsrc9[(ck9, gid9)] = {}
        try:
            for ex9, ts9, k9, int9 in type(self)._krw_bank_moves(conn, ("upbit", "bithumb")):
                up9 = ex9 == "upbit"
                if ts9 < lo_ts:
                    continue
                if fx_day is not None:
                    if datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d") not in keys:
                        continue
                    d9 = datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d")
                    fx9 = float((self._att_fx_at(int(ts9 * 1000)) if self.__dict__.get("_att_fx_at") else fx_day(d9)) or 0)
                    if not fx9 > 0:
                        nofx9[d9] = nofx9.get(d9, 0.0) + k9
                        continue
                else:
                    fxr9 = self.px.fx_at(int(ts9 * 1000))
                    if not fxr9:
                        _px_took(self.px)
                        self._flow_nf.add(datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d"))
                    fx9 = float(fxr9 or rate_now or self.spot.rate or acct_norm.DEFAULT_KRW_USD)
                if up9:
                    _add(datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d"), "krw:" + ("int" if int9 else "in" if k9 > 0 else "out"),
                        "업비트 원화 지급(예치금 이용료 등·은행 아님)" if int9 else "원화 입금(은행에서)" if k9 > 0 else "원화 출금(은행으로)", k9 / fx9, keys=keys, acc_k=acc_k)
                else:
                    _add(datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d"), f"krw:{ex9}:" + ("int" if int9 else "in" if k9 > 0 else "out"),
                        "빗썸 원화 지급(거래소 내부·은행 아님)" if int9 else "빗썸 원화 입금(은행에서)" if k9 > 0 else "빗썸 원화 출금(은행으로)", k9 / fx9, keys=keys, acc_k=acc_k)
                if vflow9 is not None and k9 and datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d") in keys:
                    vf9 = vflow9.setdefault(f"exchange:{ex9}", [0.0, 0.0])
                    vf9[0 if k9 > 0 else 1] += abs(k9 / fx9)
        except Exception as e9:   # noqa: BLE001 [fallback]
            if hist9:
                raise
            calcguard.swallowed("view_daily:DailyMixin._daily_flows[krw_bank]", e9)
            vflow9 = None
            log.warning("일별 순유입: 원화 입출금(업비트·빗썸) 조회 실패: %s", e9)
        out = {}
        fpd9 = {}
        fdet9 = None
        if not hist9:
            self._flow_px_delta = fpd9
            fdet9 = self._flow_det = {}
        for ck9 in sorted(set(acc) | set(acc_k)):
            tot9 = 0.0
            top9 = []
            dlt9 = 0.0
            for sym9, gm9 in (acc.get(ck9) or {}).items():
                e_ck9 = dpx.get(ck9) or {}
                def lp9(g0, ck9=ck9, e_ck9=e_ck9):
                    src9 = gsrc9.get((ck9, g0), e_ck9)
                    lpm9 = src9.get("lp") if isinstance(src9.get("lp"), dict) else {}
                    return float(lpm9.get(str(g0)) or gpx[(ck9, g0)])
                cl_d9 = _bands(ck9, gm9, (lambda g0: gpx[(ck9, g0)],))
                has_int9 = [any(l9 not in ext9 and v9 for g0 in gs9 for l9, v9 in gm9[g0].items()) for gs9 in cl_d9]
                sup9 = list(range(len(cl_d9)))
                if sum(has_int9) >= 2:
                    of9 = {g0: i9 for i9, gs9 in enumerate(cl_d9) for g0 in gs9}
                    int_gm9 = {g0: gm9[g0] for g0 in gm9 if any(l9 not in ext9 and v9 for l9, v9 in gm9[g0].items())}
                    for gs9 in _bands(ck9, int_gm9, (lambda g0: gpxc[(ck9, g0)], lp9)):
                        ids9 = sorted({of9[g0] for g0 in gs9 if has_int9[of9[g0]]})
                        for i9 in ids9[1:]:
                            sup9[_sroot(i9, sup=sup9)] = _sroot(ids9[0], sup=sup9)
                    sup9 = [_sroot(i9, sup=sup9) for i9 in range(len(cl_d9))]
                cur9 = 0.0
                for gs9 in _bands(ck9, gm9, (lambda g0: gpxc[(ck9, g0)],)):
                    cur9 += float(sum((v for g0 in gs9 for v in gm9[g0].values()), Decimal(0))) * gpxc[(ck9, _ref(gm9, gs9))]
                    flow_px_at.update(((ck9, g0), gpxc[(ck9, _ref(gm9, gs9))]) for g0 in gs9)
                shown9 = 0.0
                for r9 in sorted(set(sup9)):
                    mem9 = [i9 for i9 in range(len(cl_d9)) if sup9[i9] == r9]
                    allg9 = [g0 for i9 in mem9 for g0 in cl_d9[i9]]
                    pi9 = gpx[(ck9, _ref(gm9, allg9))]
                    lv9 = {}
                    for i9 in mem9:
                        pe9 = gpx[(ck9, _ref(gm9, cl_d9[i9]))]
                        for g0 in cl_d9[i9]:
                            for l9, v9 in gm9[g0].items():
                                px9 = pe9 if (len(mem9) == 1 or l9 in ext9) else pi9
                                lv9[l9] = lv9.get(l9, 0.0) + float(v9) * px9
                    if len(mem9) == 1:
                        gs9 = cl_d9[mem9[0]]
                        n9 = float(sum((v for g0 in gs9 for v in gm9[g0].values()), Decimal(0))) * gpx[(ck9, _ref(gm9, gs9))]
                    else:
                        n9 = sum(lv9.values())
                    tot9 += n9
                    shown9 += n9
                    if abs(n9) >= 1 or (fdet9 is not None and abs(n9) >= 0.005 and lv9):
                        ex9 = [kv for kv in lv9.items() if kv[0] in ext9 and kv[1] * n9 > 0]
                        pick9 = min(ex9 or lv9.items(), key=lambda kv: (abs(kv[1] - n9), -abs(kv[1]), kv[0]))[0]
                        if abs(n9) >= 1:
                            top9.append((pick9, n9))
                        if fdet9 is not None:
                            fdet9.setdefault(ck9, []).append([pick9, round(n9, 2), [[l9, round(v9, 2)] for l9, v9 in sorted(
                                lv9.items(), key=lambda kv: (-abs(kv[1]), kv[0])) if abs(v9) >= 0.005][:6]])
                dlt9 += cur9 - shown9
            for g9 in (acc_k.get(ck9) or {}).values():
                n9 = sum(g9.values())
                tot9 += n9
                if abs(n9) >= 1:
                    top9.append((next(iter(g9)), n9))
                if fdet9 is not None and abs(n9) >= 0.005:
                    fdet9.setdefault(ck9, []).append([next(iter(g9)), round(n9, 2), []])
            top9.sort(key=lambda kv: -abs(kv[1]))
            out[keys[ck9]] = (round(tot9, 2), [[k, round(v, 2)] for k, v in top9[:3]])
            if abs(dlt9) >= 0.005:
                fpd9[keys[ck9]] = round(dlt9, 2)
        if hist9 and nofx9:
            out["_nofx"] = {d9: round(v9, 2) for d9, v9 in nofx9.items()}
        if vflow9 is not None:
            self._venue_flow = vflow9
        return out

    def _daily_attrib(self, conn, daily, G, today_kst, live_px, skip_gids=frozenset(), extra=None, real=None, px_src=None) -> dict:
        src = getattr(self, "_daily_att_src", None) or {}
        by_today = {}
        det_all = {}
        try:
            self._att_by_today = by_today
            self._att_det_new = det_all
        except Exception as _cg9:   # noqa: BLE001 [optional]
            calcguard.swallowed("view_daily:DailyMixin._daily_attrib[_att_by_today]", _cg9)
        if len(daily) < 2 or not src:
            return {}
        extra = extra or {}
        keys = {}
        for i in range(29, -1, -1):
            d9 = today_kst - timedelta(days=i)
            keys[d9.strftime("%m-%d")] = d9.strftime("%Y-%m-%d")
        ck_set = set(keys.values())
        today_ck = today_kst.strftime("%Y-%m-%d")
        skip9s = {str(x) for x in (skip_gids or ())}
        rate_now = float(extra.get("rate") or self.spot.rate or acct_norm.DEFAULT_KRW_USD)
        dpx = self.daily_px or {}
        legs = {}
        mv9 = {}
        lo_ts = _day_ts(min(ck_set))[0]
        dbi9 = {}
        fb9 = {}
        fbx9 = {}
        opn9 = {}
        for gid9, g9 in G.items():
            if not g9.get("open_tl") or g9.get("is_fiat") or gid9 in skip_gids:
                continue
            for t9, q9 in g9["open_tl"]:
                ck9 = datetime.fromtimestamp(t9, KST).strftime("%Y-%m-%d")
                if ck9 in ck_set and q9:
                    o9 = opn9.setdefault(ck9, {})
                    o9[gid9] = o9.get(gid9, Decimal(0)) + Decimal(q9)
        sql9 = ("SELECT p.event_ts, p.qty_base, a.decimals, COALESCE(a.group_id, -a.asset_id), p.event, p.leg_kind, p.location{}"
                " FROM postings p JOIN assets a ON a.asset_id = p.asset_id WHERE p.event_ts >= ?"
                " AND p.location NOT LIKE 'out:%'")
        try:
            rows9 = conn.execute(sql9.format(", p.leg_seq, p.source_ns, p.source_id, p.cost_usd"), (int(lo_ts),)).fetchall()
        except Exception as e9:   # noqa: BLE001 [fallback]
            if "no such column" not in str(e9):
                raise
            calcguard.swallowed("view_daily:DailyMixin._daily_attrib[old_cols]", e9)
            rows9 = [tuple(r9) + (None, None, None, None) for r9 in conn.execute(sql9.format(""), (int(lo_ts),))]
        krwf9 = {}
        for ts9, qb9, dec9, gid9, ev9, lk9, loc9, lseq9, ns9, sid9, _cost_usd in rows9:
            if gid9 in skip_gids:
                continue
            g9 = G.get(gid9)
            if g9 and g9.get("is_fiat"):
                loc9s = str(loc9 or "")
                if (loc9s.startswith("exchange:") and not loc9s.startswith("exchange:upbit")
                        and (lk9 in ("fee", "gas") or ev9 in self.ATT_TRADE_EV)):
                    ck9 = datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d")
                    if ck9 in ck_set:
                        try:
                            krwf9[ck9] = krwf9.get(ck9, Decimal(0)) + Decimal(int(qb9)) / (Decimal(10) ** int(dec9 if dec9 is not None else 8))
                        except (TypeError, ValueError, InvalidOperation):
                            pass
                continue
            if not g9:
                continue
            is_lp9 = str(loc9 or "").startswith("lp:")
            if histmark.exf_is_fut(ev9, ns9):
                ck9 = datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d")
                if ck9 in ck_set:
                    try:
                        q9 = Decimal(int(qb9)) / (Decimal(10) ** int(dec9 if dec9 is not None else 18))
                    except (TypeError, ValueError, InvalidOperation):
                        continue
                    f9 = fb9.setdefault(ck9, {})
                    f9[gid9] = f9.get(gid9, Decimal(0)) + q9
                    fbd9 = fbx9.setdefault(ck9, {})
                    fbk9 = (str(ns9 or "").split(":")[0], gid9)
                    fbd9[fbk9] = fbd9.get(fbk9, Decimal(0)) + q9
                    m9 = mv9.setdefault(ck9, {}).setdefault(gid9, {})
                    m9[ev9] = m9.get(ev9, Decimal(0)) + q9
                continue
            int9 = histmark.exf_is_debt_int(ev9, lseq9, ns9, sid9)
            if lk9 in ("fee", "gas") or int9:
                slot9 = 1
            elif ev9 in self.ATT_TRADE_EV:
                slot9 = 0
            elif ev9 in self.ATT_LP_EV:
                slot9 = 2
            else:
                slot9 = None
            if slot9 is None and (is_lp9 or ev9 in type(self).FLOW_SKIP_EV):
                continue
            ck9 = datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d")
            if ck9 not in ck_set:
                continue
            try:
                q9 = Decimal(int(qb9)) / (Decimal(10) ** int(dec9 if dec9 is not None else 18))
            except (TypeError, ValueError, InvalidOperation):
                continue
            if slot9 is None:
                m9 = mv9.setdefault(ck9, {}).setdefault(gid9, {})
                m9[ev9] = m9.get(ev9, Decimal(0)) + q9
                continue
            if is_lp9:
                slot9 = 3
            legs.setdefault(ck9, {}).setdefault(gid9, [Decimal(0), Decimal(0), Decimal(0), Decimal(0)])[slot9] += q9
            if int9:
                d9 = dbi9.setdefault(ck9, {})
                d9[gid9] = d9.get(gid9, Decimal(0)) + q9
        tl9 = extra.get("krw_up_tl")
        if tl9 is None and callable(getattr(self, "_upbit_krw_timeline", None)):
            tl9 = self._upbit_krw_timeline(conn)
        tc9 = getattr(self, "_upbit_krw_tl", None)
        tlo_ok9 = tl9 is not None and isinstance(tc9, tuple) and len(tc9) > 2 and tc9[1] is tl9
        tlo9 = tc9[2] if tlo_ok9 else []
        try:
            krwb9 = [(t9, k9) for _e9, t9, k9, _i9 in type(self)._krw_bank_moves(conn, ("bithumb",))]
        except Exception as e9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_daily:DailyMixin._daily_attrib[krwb9]", e9)
            log.debug("자산 변동 분해: 빗썸 원화 입출금 조회 실패(종전대로): %s", e9)
            krwb9 = []
        krw_up_now = float(extra.get("krw_up") or 0)
        krw_other_now = float(extra.get("krw_other") or 0)
        has_krw9 = "krw_up" in extra
        def krw_at(end9):
            if tl9 is None:
                return krw_up_now + krw_other_now
            k9 = Decimal(str(krw_up_now)) - sum((d9 for t9, d9 in tl9 if t9 > end9), Decimal(0))
            return (float(max(k9, Decimal(0))) if k9 >= Decimal(-1000) else krw_up_now) + krw_other_now
        real = real if isinstance(real, dict) else None
        out, ur_build = {}, view_attur.UrBuild(rows9, G, frozenset(skip_gids or ()), self.ATT_TRADE_EV, self.ATT_DET_CAP)
        for i9 in range(1, len(daily)):
            rd, rp9 = daily[i9], daily[i9 - 1]
            ckd, ckp = keys.get(rd.get("date")), keys.get(rp9.get("date"))
            sd, sp = src.get(ckd), src.get(ckp)
            if not sd or not sp or not isinstance(sd[0], dict) or not isinstance(sp[0], dict):
                continue
            gd, pdx = sd[0], sd[1] or {}
            gp, ppx = sp[0], sp[1] or {}
            ud, up9 = _rate_of(rd, keys=keys, today_ck=today_ck, rate_now=rate_now), _rate_of(rp9, keys=keys, today_ck=today_ck, rate_now=rate_now)
            is_today9 = ckd == today_ck
            by9, base9 = {}, {}
            det9 = {}
            def moved9(gid9, ck9=ckd):
                return gid9 in (legs.get(ck9) or {}) or gid9 in (mv9.get(ck9) or {}) or gid9 in (opn9.get(ck9) or {})
            unp_n, unp_v = 0, 0.0
            unpl9 = []
            for sid9, vp9 in gp.items():
                if sid9 in skip9s:
                    continue
                try:
                    g9 = G.get(int(sid9))
                except ValueError:
                    g9 = None
                if not g9 or g9.get("is_stable"):
                    continue
                vp9 = float(vp9)
                pa9, pb9 = ppx.get(sid9), pdx.get(sid9)
                if pa9 and pb9 and vp9:
                    sym9 = str(g9.get("sym") or "?").upper()
                    by9[sym9] = by9.get(sym9, 0.0) + vp9 * (float(pb9) / float(pa9) - 1)
                    base9[sym9] = base9.get(sym9, 0.0) + vp9
                    det9.setdefault(sym9, []).append((sid9, vp9, float(pa9), float(pb9)))
                    if is_today9:
                        by_today[sid9] = (vp9 * (float(pb9) / float(pa9) - 1), vp9)
                elif vp9 and sid9 in gd and abs(float(gd[sid9]) - vp9) >= 0.005:
                    unp_n += 1
                    unp_v += float(gd[sid9]) - vp9
                    unpl9.append((str(g9.get("sym") or "?").upper(), float(gd[sid9]) - vp9, "one"))
                elif vp9 >= 0.005 and pa9 and not pb9 and sid9 not in gd and not moved9(int(sid9)):
                    unp_n += 1
                    unp_v -= vp9
                    unpl9.append((str(g9.get("sym") or "?").upper(), -vp9, "cut"))
            for sid9, vd9 in gd.items():
                if sid9 in gp or sid9 in skip9s:
                    continue
                try:
                    g9 = G.get(int(sid9))
                except ValueError:
                    continue
                if (g9 and not g9.get("is_stable") and float(vd9) >= 0.005 and pdx.get(sid9) and not ppx.get(sid9)
                        and not moved9(int(sid9))):
                    unp_n += 1
                    unp_v += float(vd9)
                    unpl9.append((str(g9.get("sym") or "?").upper(), float(vd9), "new"))
            kx = 0.0
            if has_krw9 and ud and up9 and ud != up9:
                kx = _krw_close(ckp, dpx=dpx, krw_at=krw_at) * (1 / ud - 1 / up9)
            kx0 = kx
            fxat9 = self.__dict__.get("_att_fx_at") or getattr(getattr(self, "px", None), "fx_at", None)
            if tlo_ok9 and ud and callable(fxat9):
                a9, b9 = _day_ts(ckd)
                o9 = {}
                for t9, d9 in tlo9:
                    if a9 <= t9 <= b9:
                        o9[(t9, d9)] = o9.get((t9, d9), 0) + 1
                for t9, d9 in tl9:
                    if not (a9 <= t9 <= b9):
                        continue
                    if o9.get((t9, d9)):
                        o9[(t9, d9)] -= 1
                        continue
                    fx9 = float(fxat9(int(t9 * 1000)) or rate_now or acct_norm.DEFAULT_KRW_USD)
                    kx += float(d9) * (1 / ud - 1 / fx9)
            kxa9 = kx
            if has_krw9 and krwb9 and ud and callable(fxat9):
                a9, b9 = _day_ts(ckd)
                for t9, d9 in krwb9:
                    if a9 <= t9 <= b9:
                        fx9 = float(fxat9(int(t9 * 1000)) or rate_now or acct_norm.DEFAULT_KRW_USD)
                        kx += float(d9) * (1 / ud - 1 / fx9)
            mk = sum(by9.values()) + kx
            dfx9 = (dpx.get(ckd) or {}).get("p") or {}
            lg9 = legs.get(ckd) or {}
            mvd9 = mv9.get(ckd) or {}
            own9 = {}
            cand9 = {}
            gids9 = set(lg9)
            for s9 in set(gd) | set(gp):
                try:
                    gids9.add(int(s9))
                except ValueError:
                    continue
            for gid9 in gids9:
                g9 = G.get(gid9) or {}
                sid9 = str(gid9)
                if g9.get("is_stable") or g9.get("is_fiat") or sid9 in skip9s or not g9:
                    continue
                p9 = _fnum(pdx.get(sid9)) or _fnum(ppx.get(sid9)) or _fnum(dfx9.get(sid9))
                if not p9 and is_today9:
                    p9 = _fnum(live_px.get(gid9))
                if p9 > 0:
                    own9[gid9] = p9
                elif gid9 in lg9 and _fnum(live_px.get(gid9)) > 0:
                    cand9[gid9] = _fnum(live_px.get(gid9))
            def wt9(gid9):
                m9 = mvd9.get(gid9) or {}
                l9 = lg9.get(gid9) or ()
                return (float(sum((abs(v9) for v9 in m9.values()), Decimal(0))), float(sum((abs(v9) for v9 in l9), Decimal(0))),
                        abs(_fnum(gd.get(str(gid9)))) + abs(_fnum(gp.get(str(gid9)))), -gid9)
            prev_only = view_attur.prev_only(own9, pdx, ppx, moved9, G, mvd9, type(self).FLOW_INT_EV) - view_attur.day_excl(ckd, opn9, fb9, dbi9, real, is_today9)
            fl_att = {} if is_today9 else view_attur.past_flow_px(prev_only, self.__dict__.get("_flow_att_rep") or {}, self.__dict__.get("_flow_att_px") or {}, ckd)
            fl_att.update({} if is_today9 else view_attur.nopx_flow_px(lg9, mvd9, set(opn9.get(ckd) or ()) | set(fb9.get(ckd) or ()), own9, self.__dict__.get("_flow_att_px") or {}, ckd))
            by_sym9 = view_attur.by_symbol(own9, G, set())
            leg_px9 = {}
            bands9 = {}
            for sym9, gs9 in by_sym9.items():
                cl9 = []
                for gid9 in sorted(gs9, key=lambda g0: (own9[g0], g0)):
                    if cl9 and own9[gid9] <= cl9[-1][0] * type(self).ATT_BAND:
                        cl9[-1][1].append(gid9)
                    else:
                        cl9.append([own9[gid9], [gid9]])
                for _p9, gs0 in cl9:
                    ref9 = max(gs0, key=wt9)
                    for gid9 in gs0:
                        leg_px9[gid9] = own9[ref9]
                bands9[sym9] = [(own9[max(gs0, key=wt9)], gs0) for _p9, gs0 in cl9]
            lo9, hi9 = type(self).ATT_NOPX_BAND
            pb9 = lambda p9: view_attur.prev_band_px(p9, own9, bands9, live_px if is_today9 else None, G, (lo9, hi9), pdx)   # noqa: E731
            leg_px9.update(view_attur.unv_live_keep(pb9, prev_only, ((real or {}).get("unv") or {}).get(ckd) or {}, self.__dict__.get("_flow_att_px") or {}, ckd, bands9))
            leg_px9.update(fl_att)
            prev_only.update(fl_att)
            for gid9, lv9 in ((g, v) for g, v in cand9.items() if g not in fl_att):
                sym9 = str((G.get(gid9) or {}).get("sym") or "?").upper()
                fit9 = [bp9 for bp9, _g in bands9.get(sym9) or () if lo9 <= lv9 / bp9 <= hi9]
                if fit9:
                    leg_px9[gid9] = min(fit9, key=lambda bp9: abs(lv9 / bp9 - 1))
            gx = 0.0
            for gid9, p9 in own9.items():
                lp9 = leg_px9.get(gid9)
                if not lp9 or abs(lp9 - p9) <= 1e-15 * max(p9, 1.0):
                    continue
                sid9 = str(gid9)
                gdv9, gpv9 = _fnum(gd.get(sid9)), _fnum(gp.get(sid9))
                pd9, pp9 = _fnum(pdx.get(sid9)), _fnum(ppx.get(sid9))
                if gdv9 and gpv9:
                    if not (pd9 and pp9):
                        continue
                    b9, po9 = gdv9 - gpv9 * pd9 / pp9, pd9
                elif gdv9:
                    if not pd9:
                        continue
                    b9, po9 = gdv9, pd9
                elif gpv9:
                    if not pp9:
                        continue
                    b9, po9 = view_attur.prev_out(gid9, gpv9, pp9, prev_only, is_today9 or gid9 in fl_att, mvd9, type(self).FLOW_INT_EV), pp9
                else:
                    continue
                gx += b9 * (1 - lp9 / po9)
            tr = fee = lpv = tall = 0.0
            np9 = 0
            for gid9, (qt9, qf9, ql9, qx9) in lg9.items():
                g9 = G.get(gid9) or {}
                px9 = 1.0 if g9.get("is_stable") else leg_px9.get(gid9, 0.0)
                if not px9:
                    if qt9 or qf9 or ql9 or qx9:
                        np9 += 1
                    continue
                tr += float(qt9 + qf9) * px9
                fee += float(qf9) * px9
                lpv += float(ql9) * px9
                tall += float(qt9 + qf9 + ql9 + qx9) * px9
            ord9 = dep9 = 0.0
            if tl9 is not None and ud:
                ord9 = _krw_sum(tlo9, ckd) / ud
                dep9 = _krw_sum(tl9, ckd) / ud - ord9
            ordb9 = depb9 = 0.0
            if ud:
                ordb9 = float(krwf9.get(ckd) or 0) / ud
                lob9, hib9 = _day_ts(ckd)
                depb9 = sum(k9 for t9, k9 in krwb9 if lob9 <= t9 <= hib9) / ud
            tr += ord9 + ordb9
            tall += ord9 + ordb9
            dv = float(rd.get("val") or 0) - float(rp9.get("val") or 0)
            fl = float(rd.get("flow") or 0)
            rs = dv - mk - fl - tr
            dx = (float(rd.get("val") or 0) - _gsum(gd, skip9s=skip9s)) - (float(rp9.get("val") or 0) - _gsum(gp, skip9s=skip9s))
            xo = dx - ord9 - dep9 - ordb9 - depb9 - kx0
            mv = sorted(((s9, v9) for s9, v9 in by9.items() if abs(v9) >= 0.005), key=lambda kv: (-abs(kv[1]), kv[0]))
            top = [[s9, round(v9 / base9[s9] * 100, 2) if base9.get(s9) else None, round(v9, 2)] for s9, v9 in mv[:self.ATT_TOP]]
            rest9 = mv[self.ATT_TOP:]
            a9 = {"mk": round(mk, 2), "top": top, "etc": [len(rest9), round(sum(v9 for _s, v9 in rest9), 2)],
                  "kx": round(kx, 2), "tr": round(tr, 2), "fee": round(fee, 2), "lp": round(lpv, 2), "xo": round(xo, 2), "rs": round(rs, 2)}
            if unp_n:
                a9["unp"] = [unp_n, round(unp_v, 2)]
            if top and det9:
                try:
                    tx9 = self._att_topx(top, det9, ckd, ckp, dpx, today_ck, src, px_src)
                except Exception as ex9:   # noqa: BLE001 [fallback]
                    calcguard.swallowed("view_daily:DailyMixin._daily_attrib[tx9]", ex9)
                    log.debug("자산 변동 분해 코인별 재료(topx) 실패 %s: %s", ckd, ex9)
                    tx9 = None
                if tx9:
                    a9["topx"] = tx9
            if real is not None:
                xp9, xd9 = _xu_px(sp[2] if len(sp) > 2 else None), _xu_px(sd[2] if len(sd) > 2 else None)
                xm = sum(q9 * (xd9[s9][1] - pu9) for s9, (q9, pu9) in xp9.items() if s9 in xd9)
                rbd9 = _fnum((real.get("rbd") or {}).get(ckd))
                lpf = _fnum((real.get("lpf") or {}).get(ckd))
                stk = _fnum((real.get("stk") or {}).get(ckd))
                rz = rbd9 - lpf - stk
                un = 0.0
                for gid9, (uq9, upr9) in ((real.get("unv") or {}).get(ckd) or {}).items():
                    if gid9 in skip_gids:
                        continue
                    g9 = G.get(gid9) or {}
                    un += float(upr9) - float(uq9) * (1.0 if g9.get("is_stable") else leg_px9.get(gid9, 0.0))
                ur = tall + gx - rz - lpf - un
                mkc = mk - kx
                fpx9 = float((getattr(self, "_flow_px_delta", None) or {}).get(rd.get("date")) or 0)
                ev9 = mkc + xm + ur + fpx9
                fbv9 = sum(float(q9) * (1.0 if (G.get(gid9) or {}).get("is_stable") else leg_px9.get(gid9, 0.0))
                           for gid9, q9 in (fb9.get(ckd) or {}).items())
                opv9 = sum(float(q9) * (1.0 if (G.get(gid9) or {}).get("is_stable") else leg_px9.get(gid9, 0.0))
                           for gid9, q9 in (opn9.get(ckd) or {}).items())
                rest = dv - (ev9 + rz + lpf + fl + kx + un + fbv9 + opv9)
                if abs(opv9) >= 0.005:
                    a9["op"] = round(opv9, 2)
                a9.update({"v": type(self).ATT_V, "ev": round(ev9, 2), "xm": round(xm, 2), "ur": round(ur, 2), "rz": round(rz, 2),
                           "lpf": round(lpf, 2), "stk": round(stk, 2), "un": round(un, 2), "gx": round(gx, 2), "rest": round(rest, 2)})
                if abs(fbv9) >= 0.005:
                    a9["fb"] = round(fbv9, 2)
                if fpx9:
                    a9["fpx"] = round(fpx9, 2)
                if np9:
                    a9["np"] = np9
                rbd9, rbp9 = _fnum(rd.get("rb")), _fnum(rp9.get("rb"))
                rbv9 = (rbd9 - rbp9) - _fnum(rd.get("rbNew"))
                lpcd9, lpcp9 = (getattr(self, "_daily_lpc", None) or {}).get(ckd) or {}, (getattr(self, "_daily_lpc", None) or {}).get(ckp) or {}
                lpcv9 = 0.0
                for gid9 in set(lpcd9) | set(lpcp9):
                    if gid9 in skip_gids:
                        continue
                    lpcv9 += (lpcd9.get(gid9, 0.0) - lpcp9.get(gid9, 0.0)) * (1.0 if (G.get(gid9) or {}).get("is_stable") else own9.get(gid9, 0.0))
                xr9 = xo - xm - (rbd9 - rbp9) + lpcv9 - (_fnum(rd.get("pv")) - _fnum(rp9.get("pv")))
                if abs(xr9) >= 0.005:
                    a9["xr"] = round(xr9, 2)
                    if _fnum(rd.get("xc")) >= 1 or _fnum(rp9.get("xc")) >= 1:
                        a9["xca"] = 1
                if abs(rbv9) >= 0.005:
                    a9["rbv"] = round(rbv9, 2)
                dbv9 = sum(float(q9) * (1.0 if (G.get(gid9) or {}).get("is_stable") else leg_px9.get(gid9, 0.0))
                           for gid9, q9 in (dbi9.get(ckd) or {}).items())
                if abs(dbv9) >= 0.005:
                    a9["dbi"] = round(dbv9, 2)
            try:
                det_all[ckd] = self._att_det_pack(rd, by9, base9, det9, unpl9, (kx0, kxa9 - kx0, kx - kxa9),
                                                  _xu_px(sp[2] if len(sp) > 2 else None), _xu_px(sd[2] if len(sd) > 2 else None),
                                                  ((real or {}).get("unv") or {}).get(ckd) or {}, opn9.get(ckd) or {},
                                                  fbx9.get(ckd) or {}, leg_px9, G, skip_gids, ckd)
                view_attur.attach(det_all[ckd], ur_build, ckd, a9, lg9, leg_px9, real)
            except Exception as ex9:   # noqa: BLE001 [isolate]
                calcguard.swallowed("view_daily:DailyMixin._daily_attrib[float]", ex9)
                log.debug("자산 변동 분해 상세 재료 실패 %s: %s", ckd, ex9)
            out[rd.get("date")] = a9
        return out

    @staticmethod
    def _att_cap(lst, n, key, more, vi=1):
        if len(lst) <= n:
            return lst
        rest9 = lst[n:]
        more[key] = [len(rest9), round(sum(float(x[vi]) for x in rest9), 2)]
        return lst[:n]

    def _att_det_pack(self, rd, by9, base9, det9, unpl9, kxp9, xp9, xd9, unv9, opn9, fbx9, leg_px9, G, skip_gids, ckd) -> dict:
        r2 = lambda v: round(float(v), 2)   # noqa: E731
        sym_of = lambda g: str((G.get(g) or {}).get("sym") or "?").upper()   # noqa: E731
        px_of = lambda g: 1.0 if (G.get(g) or {}).get("is_stable") else float(leg_px9.get(g, 0.0))   # noqa: E731
        mk = []
        for s9, v9 in sorted(by9.items(), key=lambda kv: (-abs(kv[1]), kv[0])):
            if abs(v9) < 0.005:
                continue
            q9 = p0 = p1 = None
            gl9 = det9.get(s9) or ()
            if gl9:
                qq9 = sum(vp / pa for _sid, vp, pa, _pb in gl9 if pa)
                if qq9 > 0:
                    q9 = qq9
                    p0 = sum(vp for _sid, vp, _pa, _pb in gl9) / qq9
                    p1 = sum(vp / pa * pb for _sid, vp, pa, pb in gl9 if pa) / qq9
            pct9 = round(v9 / base9[s9] * 100, 2) if base9.get(s9) else None
            mk.append([s9, r2(v9), pct9] + ([float("%.8g" % q9), float("%.8g" % p0), float("%.8g" % p1)] if q9 else []))
        more = {}
        out = {"mk": self._att_cap(mk, self.ATT_DET_MK, "mk", more), "mkN": len(mk), "more": more}
        xm = [[s9, r2(q9 * (xd9[s9][1] - pu9))] for s9, (q9, pu9) in (xp9 or {}).items() if s9 in (xd9 or {})]
        out["xm"] = self._att_cap(sorted((x for x in xm if abs(x[1]) >= 0.005), key=lambda x: (-abs(x[1]), x[0])), self.ATT_DET_CAP, "xm", more)
        out["kx"] = [r2(v) for v in kxp9]
        acc9 = {}
        for s9, v9, w9 in unpl9 or ():
            k9 = (s9, w9)
            acc9[k9] = acc9.get(k9, 0.0) + float(v9)
        out["unp"] = self._att_cap(sorted(([k9[0], r2(v9), k9[1]] for k9, v9 in acc9.items() if abs(v9) >= 0.005), key=lambda x: (-abs(x[1]), x[0])),
                                   self.ATT_DET_CAP, "unp", more)
        def by_sym(pairs):
            a9 = {}
            for s9, v9 in pairs:
                a9[s9] = a9.get(s9, 0.0) + v9
            return sorted(([s9, r2(v9)] for s9, v9 in a9.items() if abs(v9) >= 0.005), key=lambda x: (-abs(x[1]), x[0]))
        out["un"] = self._att_cap(by_sym((sym_of(g), float(p9) - float(q9) * px_of(g)) for g, (q9, p9) in unv9.items() if g not in skip_gids), self.ATT_DET_CAP, "un", more)
        out["op"] = self._att_cap(by_sym((sym_of(g), float(q9) * px_of(g)) for g, q9 in opn9.items()), self.ATT_DET_CAP, "op", more)
        out["fb"] = by_sym((ex9 or "?", float(q9) * px_of(g)) for (ex9, g), q9 in fbx9.items())
        fd9 = getattr(self, "_flow_det", None)
        rbn9, pv9 = float(rd.get("rbNew") or 0), float(rd.get("pv") or 0)
        if isinstance(fd9, dict):
            fl9 = sorted(fd9.get(ckd) or (), key=lambda x: (-abs(x[1]), str(x[0])))
            if abs(sum(x[1] for x in fl9) + rbn9 + pv9 - float(rd.get("flow") or 0)) <= max(0.05, 0.006 * (len(fl9) + 2)):
                out["fl"] = self._att_cap(fl9, self.ATT_DET_FL, "fl", more)
                if abs(rbn9) >= 0.005:
                    out["rbNew"] = r2(rbn9)
                if abs(pv9) >= 0.005:
                    out["pv"] = r2(pv9)
        return out

    def _att_topx(self, top, det, ckd, ckp, dpx, today_ck, src, px_src=None) -> list:
        X = float(self.ATT_SPIKE)
        def px_of(ck9):
            e9 = src.get(ck9)
            p9 = e9[1] if isinstance(e9, (tuple, list)) and len(e9) > 1 else None
            return p9 if isinstance(p9, dict) else {}

        def shift(ck9, n9):
            return (datetime.strptime(ck9, "%Y-%m-%d") + timedelta(days=n9)).strftime("%Y-%m-%d")
        pn9, pq9 = px_of(shift(ckd, 1)), px_of(shift(ckp, -1))

        def kind(ck9, sid9, p9):
            if ck9 == today_ck:
                return "live"
            e9 = dpx.get(ck9) if isinstance(dpx, dict) else None
            if not isinstance(e9, dict):
                return None
            try:
                f9 = float((e9.get("p") or {}).get(sid9) or 0)
            except (TypeError, ValueError):
                return None
            if not f9 or abs(f9 - p9) > 1e-9 * abs(p9):
                return None
            return str((e9.get("k") or {}).get(sid9) or "now")
        memo9 = {}

        def src_of(ck9, sid9, k9):
            if k9 != "d" or px_src is None:
                return None
            if (ck9, sid9) not in memo9:
                try:
                    memo9[(ck9, sid9)] = self._att_dc_src(px_src(int(sid9)), ck9)
                except Exception as _cg9:   # noqa: BLE001 [fallback]
                    calcguard.swallowed("view_daily:DailyMixin._att_topx.src_of", _cg9)
                    memo9[(ck9, sid9)] = None
            return memo9[(ck9, sid9)]

        def off(a9, b9):
            try:
                a9, b9 = float(a9 or 0), float(b9 or 0)
            except (TypeError, ValueError):
                return None
            if a9 <= 0 or b9 <= 0:
                return None
            r9 = a9 / b9
            return r9 if (r9 > X or r9 < 1.0 / X) else None
        out = []
        for s9, pct9, usd9 in top:
            gs9 = det.get(s9) or ()
            rows9 = []
            for sid9, vp9, p0, p1 in gs9:
                q9 = vp9 / p0
                r9 = {"q": q9, "p0": p0, "p1": p1, "usd": vp9 * (p1 / p0 - 1), "vp": vp9, "k": kind(ckd, sid9, p1), "k0": kind(ckp, sid9, p0)}
                r9["src"] = src_of(ckd, sid9, r9["k"])
                s0 = src_of(ckp, sid9, r9["k0"])
                if s0 and s0 != r9["src"]:
                    r9["src0"] = s0
                for fr9, x9 in (("day", off(p1, p0)), ("next", off(p1, pn9.get(sid9))), ("prev", off(p0, pq9.get(sid9)))):
                    if x9:
                        r9.update(flag="spike", fr=fr9, rx=round(x9, 4))
                        break
                rows9.append(r9)
            if not rows9:
                continue
            q_all = sum(r9["q"] for r9 in rows9)
            if not q_all:
                continue
            rows9.sort(key=lambda r0: -abs(r0["usd"]))
            dom9 = rows9[0]
            fl9 = [r9 for r9 in rows9 if r9.get("flag")]
            it9 = {"sym": s9, "q": q_all, "p0": sum(r9["vp"] for r9 in rows9) / q_all, "p1": sum(r9["q"] * r9["p1"] for r9 in rows9) / q_all,
                   "pct": pct9, "usd": usd9,
                   "k": dom9["k"] if all(r9["k"] == dom9["k"] for r9 in rows9) else "mix",
                   "k0": dom9["k0"] if all(r9["k0"] == dom9["k0"] for r9 in rows9) else "mix",
                   "src": dom9["src"]}
            if dom9.get("src0"):
                it9["src0"] = dom9["src0"]
            if fl9:
                it9.update(flag="spike", fr=fl9[0]["fr"], rx=fl9[0]["rx"])
            if len(rows9) > 1:
                it9["gn"] = len(rows9)
                it9["gs"] = [{k9: (round(v9, 6) if k9 == "usd" else v9) for k9, v9 in r9.items() if k9 != "vp" and v9 is not None}
                             for r9 in rows9[:self.ATT_TOPX_GS]]
            out.append(it9)
        return out

    @staticmethod
    def _att_dc_src(spec, iso):
        if not spec or spec in ("stable", "ov"):
            return None
        dc9 = getattr(histcurve, "DAYCLOSE", None)
        if dc9 is None:
            return None
        for e9 in dc9._sources(spec):
            if dc9.covers(e9, iso) and (dc9._ffp(e9).get(iso) or 0) > 0:
                s9 = e9.get("src")
                if isinstance(s9, (list, tuple)):
                    s9 = " · ".join(str(x9) for x9 in s9[:3] if x9)
                return str(s9)[:80] if s9 else None
        return None

    @staticmethod
    def _hold_today(coins, G, live_px, today_kst, dpx, by_today):
        TWIN_X = 1.5
        by_today = by_today if isinstance(by_today, dict) else {}
        rows9 = {}
        for c9 in coins or ():
            if not isinstance(c9, dict) or c9.get("symSrc"):
                continue
            try:
                q9, p9 = float(c9.get("qty") or 0), float(c9.get("price") or 0)
            except (TypeError, ValueError):
                continue
            if not (q9 > 0 and p9 > 0):
                continue
            k9 = str(c9.get("key") or "")
            gid9 = int(k9[1:]) if k9.startswith("g") and k9[1:].isdigit() else None
            if gid9 is not None:
                g9 = (G or {}).get(gid9) or {}
                if not g9 or g9.get("is_stable") or g9.get("is_fiat"):
                    continue
            rows9.setdefault(str(c9.get("sym") or "?").upper(), []).append((q9 * p9, p9, gid9))
        main9, mem9 = {}, {}
        for s9, rs9 in rows9.items():
            rs9.sort(key=lambda r9: -r9[0])
            p0 = rs9[0][1]
            band9 = [r9 for r9 in rs9 if r9[2] is not None and p0 / TWIN_X <= r9[1] <= p0 * TWIN_X]
            if band9:
                main9[s9] = band9[0][2]
                mem9[s9] = {str(r9[2]) for r9 in band9}
        today9 = {}
        for s9, m9 in mem9.items():
            v9 = b9 = 0.0
            hit9 = False
            for sid9, e9 in by_today.items():
                if sid9 in m9 and isinstance(e9, (list, tuple)) and len(e9) >= 2:
                    v9 += float(e9[0])
                    b9 += float(e9[1])
                    hit9 = True
            if hit9:
                today9[s9] = [round(v9 / b9 * 100, 2) if b9 else None, round(v9, 2)]
        def fpos(v9):
            try:
                v9 = float(v9)
            except (TypeError, ValueError):
                return None
            return float(f"{v9:.8g}") if v9 > 0 and v9 == v9 and v9 != float("inf") else None
        days9 = [(today_kst - timedelta(days=i9)).strftime("%Y-%m-%d") for i9 in range(6, 0, -1)]
        spark9 = {}
        for s9, gid9 in main9.items():
            sid9 = str(gid9)
            pts9 = []
            for ck9 in days9:
                e9 = (dpx or {}).get(ck9)
                e9 = e9 if isinstance(e9, dict) else {}
                p9 = (e9.get("p") or {}).get(sid9) if isinstance(e9.get("p"), dict) else None
                if p9 is None:
                    part9 = e9.get("partial")
                    if isinstance(part9, dict) and isinstance(part9.get("p"), dict):
                        p9 = part9["p"].get(sid9)
                pts9.append(fpos(p9))
            pts9.append(fpos((live_px or {}).get(gid9)))
            if sum(1 for p9 in pts9 if p9 is not None) >= 2:
                spark9[s9] = pts9
        return today9, spark9

    @staticmethod
    def _debt_redate_moves(conn):
        try:
            if not conn.execute("SELECT 1 FROM meta WHERE k='exf_debt_redate_t'").fetchone():
                return None
            d9 = statefile.read_json(paths.state("exf_debt_redate_t.json"), {}) or {}
        except (Exception, SystemExit) as _cg9:  # noqa: BLE001 [fallback]
            calcguard.swallowed("view_daily:DailyMixin._debt_redate_moves", _cg9)
            return None
        out = []
        for m9 in (d9.get("moves") if isinstance(d9, dict) and isinstance(d9.get("moves"), list) else ()):
            try:
                r9 = conn.execute("SELECT COALESCE(group_id, -asset_id), decimals FROM assets WHERE asset_id=?",
                                  (int(m9["asset_id"]),)).fetchone()
                if not r9:
                    continue
                q9 = -Decimal(int(m9["new_qty_base"])) / (Decimal(10) ** (8 if r9[1] is None else int(r9[1])))
                if q9 > 0 and int(m9["new_ts"]) < int(m9["old_ts"]):
                    out.append({"pid": str(int(m9["posting_id"])), "gid": int(r9[0]), "q": q9,
                                "t_new": int(m9["new_ts"]), "t_old": int(m9["old_ts"])})
            except (KeyError, TypeError, ValueError, ArithmeticError):
                continue
        return out

    @staticmethod
    def _x_src_of(extra, now_ts) -> dict:
        xs = extra.get("xsrc") if isinstance(extra, dict) else None
        if isinstance(xs, dict) and isinstance(xs.get("now"), dict):
            return {"now": dict(xs["now"]), "base": dict(xs.get("base") or {}), "tl": dict(xs.get("tl") or {}), "first": dict(xs.get("first") or {})}
        extra = extra or {}
        ubs = xparts.ub_norm(extra.get("ubs"))
        ub_left = max(0.0, float(extra.get("ub") or 0) - xparts.ub_usd(ubs))
        if "krw_up" not in extra:
            return {"now": {"ts": float(now_ts), "ku": 0.0, "kb": 0.0, "ub": ubs,
                            "rest": float(extra.get("fiat") or 0) + float(extra.get("lp") or 0) + ub_left},
                    "base": {}, "tl": {}, "first": {}}
        ku = float(extra.get("krw_up") or 0)
        tl = extra.get("krw_up_tl")
        return {"now": {"ts": float(now_ts), "ku": ku, "kb": float(extra.get("krw_other") or 0), "ub": ubs,
                        "rest": float(extra.get("lp") or 0) + ub_left},
                "base": {"ku": [ku, float(now_ts)]} if tl is not None else {},
                "tl": {"ku": [(int(t9), float(d9)) for t9, d9 in tl] if tl is not None else None}, "first": {}}

    def _x_pass(self, src, dpx, daily, today_kst, rate_now, run=True) -> dict:
        tz = today_kst.tzinfo
        td = today_kst.strftime("%Y-%m-%d")
        lo = (today_kst - timedelta(days=DAILY_PX_KEEP)).strftime("%Y-%m-%d")
        out = {"dpx": 0, "daily": 0, "mig": []}
        def isday(k9):
            k9 = str(k9)
            return len(k9) == 10 and k9[4] == "-" and lo <= k9 < td
        ob9 = {"ku": [], "kb": []}
        xvs9 = [e9.get("xv") for k9, e9 in dpx.items() if isday(k9) and isinstance(e9, dict)]
        xvs9 += [(daily.get(k9) or {}).get("xv") for k9 in ("_live", "_live_ok") if isinstance(daily.get(k9), dict)]
        for xv9 in xvs9:
            for key, t9, v9 in _xv_ob(xv9):
                ob9[key].append((t9, v9))
        base9, tl9 = src.get("base") or {}, src.get("tl") or {}
        src["bad"] = {key: xparts.tl_bad(base9.get(key), tl9.get(key), sorted(set(ob9[key]))) for key in xparts.KRW}
        if any(src["bad"].values()) and self.__dict__.get("_x_bad_logged") != src["bad"]:
            self._x_bad_logged = dict(src["bad"])
            log.warning("원장 밖 금액 자가 점검: 원화 이력이 그 순간 잔고 관측과 안 맞음 — 이 시각 이전 되감기는 안 쓰고 이월 %s",
                        {k9: datetime.fromtimestamp(v9, tz).strftime("%Y-%m-%d %H:%M") for k9, v9 in src["bad"].items() if v9})
        plan9 = {}
        for ck in sorted(set(k9 for k9 in dpx if isday(k9)) | set(k9 for k9 in daily if isday(k9))):
            e9 = dpx.get(ck) if isinstance(dpx.get(ck), dict) else {}
            c9 = daily.get(ck) if isinstance(daily.get(ck), dict) and "val" in daily[ck] else None
            xv9 = e9.get("xv") if isinstance(e9.get("xv"), dict) else None
            end9 = _x_end(ck, tz)
            fxc9 = float(c9["usdt"]) if c9 and xparts.num(c9.get("usdt")) else None
            if xv9 is not None and xv9.get("v") == xparts.GEN and _xv_parts(xv9) is not None:
                plan9[ck] = ["gen", _xv_parts(xv9), xparts.num(xv9.get("fx")) or fxc9 or rate_now, None,
                             {k9: xv9[k9] for k9 in ("ob", "x0", "ts", "part", "xq", "ufc", "ufz", "ku0") if k9 in xv9}]
                continue
            if not run:
                continue
            meta9 = {}
            if xv9 is not None and xv9.get("v") == 1 and xv9.get("dx") is None and _xv_parts(xv9):
                ob0 = {key: [t9, v9] for key, t9, v9 in _xv_ob(xv9)}
                meta9 = {"ob": ob0 or None, "ts": xv9.get("ts"), "part": xv9.get("part")}
                plan9[ck] = ["v1", _xv_parts(xv9), xparts.num(xv9.get("fx")) or fxc9 or rate_now,
                             xparts.num(e9.get("x")) if e9.get("x") is not None else None, meta9]
                continue
            if e9.get("x") is not None:
                x9, xk9, xu9 = e9.get("x"), e9.get("xk") or "live", e9.get("xu")
            elif c9 is not None and c9.get("x") is not None:
                x9 = c9["x0"] if c9.get("x0") is not None else c9["x"]
                xk9 = "live" if c9.get("src") in ("live", "partial") else "calc"
                xu9 = c9.get("xu0") if c9.get("x0") is not None else c9.get("xu")
            else:
                continue
            if xparts.num(x9) is None:
                continue
            fx9 = fxc9 or (self.px.fx_at(int(end9 * 1000)) if hasattr(self.px, "fx_at") else None) or rate_now
            plan9[ck] = ["mig:" + str(xk9), [float(x9), str(xk9), xparts.ub_norm(xu9)], float(fx9), float(x9), meta9]
        for ck, pl9 in plan9.items():
            if pl9[0] in ("mig:live", "mig:seed"):
                x9, xk9, xu9 = pl9[1]
                m9 = xparts.migrate_legacy(_x_end(ck, tz), x9, xk9, pl9[2], xu9, src)
                pl9[1] = m9["p"]
                pl9[4]["note"] = m9["note"]
        obs9 = {}
        for ck, pl9 in plan9.items():
            if pl9[0] in ("gen", "mig:live", "mig:seed"):
                p9 = pl9[1]
            elif pl9[0] == "v1":
                p9 = _xv_parts(dpx[ck]["xv"]) or {}
            else:
                continue
            o9 = xparts.obs_entry(_x_end(ck, tz), p9)
            if len(o9) > 1:
                obs9[ck] = o9
        src["obs"] = obs9
        f9 = src.get("first") if isinstance(src.get("first"), dict) else None
        if f9 is not None and "rest" in f9:
            xf9 = dpx.get("_xfirst") if isinstance(dpx.get("_xfirst"), dict) else {}
            rf9, seen9 = xparts.rest_first(f9.get("rest"), obs9, src.get("now"), xf9.get("rest"))
            src["first"] = dict(f9, rest=rf9)
            if run and seen9 and int(seen9) != xparts.num(xf9.get("rest")):
                dpx["_xfirst"] = dict(xf9, rest=int(seen9))
                out["dpx"] += 1
        if not run:
            return out
        for ck, pl9 in sorted(plan9.items()):
            end9 = _x_end(ck, tz)
            kind9 = pl9[0]
            if kind9 == "gen":
                p9 = xparts.resolve(end9, src, pinned=pl9[1])
            elif kind9 == "v1":
                p9 = xparts.upgrade_obs(pl9[1], end9, src)
            elif kind9.startswith("mig:") and kind9 not in ("mig:live", "mig:seed"):
                x9, xk9, xu9 = pl9[1]
                m9 = xparts.migrate_legacy(end9, x9, xk9, pl9[2], xu9, src)
                p9 = m9["p"]
                pl9[4]["note"] = m9["note"]
            else:
                p9 = pl9[1]
            e9 = dpx.setdefault(ck, {"p": {}, "k": {}})
            old9 = e9.get("xv") if isinstance(e9.get("xv"), dict) else None
            meta9 = dict(pl9[4])
            note9 = meta9.pop("note", None)
            if kind9 != "gen" and pl9[3] is not None:
                meta9["x0"] = round(pl9[3], 2)
            how9 = (old9 or {}).get("how") if kind9 == "gen" else ("obs" if kind9 == "v1" else kind9)
            new9 = _xv_disk(p9, pl9[2], how9 or "calc", **meta9)
            p9 = _xv_parts(new9)
            if old9 != new9:
                e9["xv"] = new9
                raw9 = xparts.total_usd(p9, pl9[2])
                e9["x"], e9["xk"] = round(raw9, 2), ("live" if all(v9[1] == "snap" for v9 in p9.values()) else "calc")
                cr9 = xparts.carry_usd(p9, pl9[2])
                if cr9 >= 1:
                    e9["xc"] = round(cr9, 2)
                else:
                    e9.pop("xc", None)
                u9 = xparts.ub_norm(p9["ub"][0]) if p9.get("ub") else {}
                if u9:
                    e9["xu"] = {s9: [round(a9[0], 12), round(a9[1], 2)] for s9, a9 in sorted(u9.items())}
                else:
                    e9.pop("xu", None)
                out["dpx"] += 1
            pl9[1] = p9
            pl9[4]["note"] = note9
        for ck, pl9 in sorted(plan9.items()):
            c9 = daily.get(ck)
            raw9 = round(xparts.total_usd(pl9[1], pl9[2]), 2)
            if not isinstance(c9, dict) or "val" not in c9 or c9.get("x") is None:
                if pl9[0] != "gen":
                    out["mig"].append((ck, pl9[0], round(float(pl9[3]), 2) if pl9[3] is not None else None, raw9, None, None, pl9[4].get("note")))
                continue
            ref9 = c9.get("xraw")
            if ref9 is None:
                ref9 = pl9[3] if pl9[3] is not None else (c9["x0"] if c9.get("x0") is not None else c9["x"])
            val0 = c9["val"]
            dv9 = _x_sync_entry(c9, pl9[1], pl9[2], float(ref9))
            if dv9 is not None:
                out["daily"] += 1
            if pl9[0] != "gen":
                out["mig"].append((ck, pl9[0], round(float(ref9), 2), raw9, val0, c9["val"], pl9[4].get("note")))
            elif dv9 is not None and abs(dv9) >= 0.005:
                log.info("일별 %s: 원장 밖 금액 구성요소 정정(원화 이력 되감기 등) x %+.2f → 그날 값 %s", ck, dv9, c9["val"])
        if out["mig"]:
            def _n9(v9, w9):
                return ("%" + str(w9) + ".2f") % v9 if v9 is not None else " " * (w9 - 1) + "—"
            lines9 = ["  %s · %-9s · x %s → %s (%s) · val %s → %s · %s" % (
                r9[0], r9[1], _n9(r9[2], 12), _n9(r9[3], 12), _n9((r9[3] - r9[2]) if r9[2] is not None else None, 11),
                _n9(r9[4], 14), _n9(r9[5], 14), r9[6] or "") for r9 in out["mig"]]
            log.warning("원장 밖 금액 구성요소 이관(세대 %d) — %d일 · 날짜 · 경로 · 빼기 전 x 전 → 후 (차) · 동결 그날 값 전 → 후(— = 동결 항목 없음):\n%s",
                        xparts.GEN, len(out["mig"]), "\n".join(lines9))
        return out

    @staticmethod
    def _x_obs_parts(sn, end_ts, src, rate_now):
        xv9 = sn.get("xv") if isinstance(sn, dict) else None
        fxbad9 = isinstance(xv9, dict) and bool(xv9.get("fxd") or xv9.get("fxs"))
        if isinstance(xv9, dict) and _xv_parts(xv9) and xv9.get("dx") is None:
            ob9 = {k9: [t9, v9] for k9, t9, v9 in _xv_ob(xv9)}
            return (xparts.upgrade_obs(_xv_parts(xv9), end_ts, src), None if fxbad9 else (xparts.num(xv9.get("fx")) or rate_now),
                    {"ob": ob9 or None, "ts": xv9.get("ts"), "ufc": xv9.get("ufc") if isinstance(xv9.get("ufc"), dict) else None,
                     "ufz": xv9.get("ufz") if isinstance(xv9.get("ufz"), dict) else None})
        fx9 = (None if fxbad9 else xparts.num((sn or {}).get("usdt"))) or rate_now
        return xparts.migrate_legacy(end_ts, (sn or {}).get("x") or 0, "live", fx9, (sn or {}).get("xu"), src)["p"], fx9, {}

    def _x_day(self, ck, end_ts, part1, close_sn, live_snap, fixed, seed_x, src, rate_now):
        fxv9 = (fixed or {}).get("xv")
        if isinstance(fxv9, dict) and fxv9.get("v") == xparts.GEN and _xv_parts(fxv9) is not None:
            return _ufc_ku(xparts.resolve(end_ts, src, pinned=_xv_parts(fxv9)), xparts.num(fxv9.get("fx")), "fixed",
                           {k9: fxv9[k9] for k9 in ("ob", "x0", "ts", "part", "xq", "ufc", "ufz", "ku0") if k9 in fxv9}, end_ts, src)
        if part1 is not None:
            p9, fx9, m9 = self._x_obs_parts(part1, end_ts, src, rate_now)
            return _ufc_ku(p9, fx9, "part", dict(m9, part=1), end_ts, src)
        if close_sn is not None:
            p9, fx9, m9 = self._x_obs_parts(close_sn, end_ts, src, rate_now)
            return _ufc_ku(p9, fx9, "snap", m9, end_ts, src)
        if live_snap and live_snap.get("date") == ck:
            xv9 = live_snap.get("xv")
            if isinstance(xv9, dict) and _xv_parts(xv9):
                o9 = {"end": float(xv9.get("ts") or live_snap.get("ts") or end_ts)}
                for key, v9 in _xv_parts(xv9).items():
                    o9[key] = v9[0]
                return xparts.resolve(end_ts, dict(src, obs=dict(src.get("obs") or {}, _day=o9))), None, "day", {}
            fx9 = xparts.num(live_snap.get("usdt")) or rate_now
            p9 = xparts.migrate_legacy(end_ts, live_snap.get("x") or 0, "live", fx9, live_snap.get("xu"), src)["p"]
            return {k9: [v9[0], "carry" if v9[1] == "snap" else v9[1]] for k9, v9 in p9.items()}, fx9, "day", {}
        if fixed and fixed.get("x") is not None:
            m9 = xparts.migrate_legacy(end_ts, fixed["x"], fixed.get("xk") or "live", rate_now, fixed.get("xu"), src)
            return m9["p"], rate_now, "mig:" + str(fixed.get("xk") or "live"), {}
        if seed_x and seed_x.get("x") is not None:
            fx9 = xparts.num(seed_x.get("usdt")) or rate_now
            return xparts.migrate_legacy(end_ts, seed_x["x"], "seed", fx9, None, src)["p"], fx9, "seed", {}
        return xparts.resolve(end_ts, src), None, "calc", {}

    def _daily_series(self, G, today_kst, override_px=None, live_px=None, ca_gids=None,
                      skip_gids=None,
                      ex_gids=None, pending_gids=None,
                      hold_qty=None, extra=None, extra_ok=True, now_ts=None, native_c=None, debt_moves=None, transit=None, dep_transit=None,
                      stable_aliases=None, day_close=None, neg_ok=None, led_gen=None, xq=None, xq_base=None, debt_neg=None, hist_late=None,
                      led_pw=None, late_after=None, inval=None) -> list:
        lo_bind9 = (today_kst - timedelta(days=DAILY_PX_KEEP)).strftime("%Y-%m-%d")
        bound9, legacy9 = _bind_px_blocks(self.daily, self.daily_px, lo_bind9)
        if legacy9:
            if not isinstance(self.daily_px.get("_pxfix"), dict):
                ts9 = int(now_ts if now_ts is not None else time.time())
                bak9 = _pxfix_backup(ts9)
                self.daily_px["_pxfix"] = {"v": 1, "bak": ts9, "at": ts9}
                log.info("pxfix: 동결 항목 가격 블록 1회 이관 — 백업 %s", bak9)
            migrated9 = _migrate_px_blocks(self.daily, self.daily_px, legacy9)
            log.info("pxfix: 옛 형식 동결 항목 %d일에 가격 블록 이관", migrated9)
        else:
            migrated9 = 0
        relabeled9 = _relabel_daily_gids(self.daily, self.daily_px, stable_aliases)
        if relabeled9:
            log.info("일별: 스테이블 재그룹 — 동결 그룹 평가액 키 %d개 이관 %s", relabeled9, stable_aliases)
        override_px = override_px or {}
        live_px = live_px or {}
        ca_gids = ca_gids or set()
        ex_gids = ex_gids or set()
        pending_gids = pending_gids or set()
        px_wait9 = self.__dict__.get("_px_wait_gids") or set()
        extra = extra or {}
        x_now = float(extra.get("ub") or 0) + float(extra.get("fiat") or 0) + float(extra.get("lp") or 0)
        ubs_now = ({str(k9).upper(): v9 for k9, v9 in extra["ubs"].items()} if isinstance(extra.get("ubs"), dict) else {})
        ub_tl9 = extra.get("ub_tl") if isinstance(extra.get("ub_tl"), dict) else {}
        ub_sym9 = {}
        for gid9 in ub_tl9:
            if gid9 in G:
                ub_sym9.setdefault(str(G[gid9].get("sym") or "").upper(), []).append(gid9)
        def xu_cut(v9, end_ts9, only=None):
            cut9, rest9, px9 = 0.0, {}, {}
            for s9, (q9, u9) in _xu_of(v9).items():
                qu9 = Decimal(0)
                for gid9 in ub_sym9.get(s9, ()):
                    if only is not None and gid9 not in only:
                        continue
                    qg9 = Decimal(0)
                    for t9, d9 in ub_tl9[gid9]:
                        if t9 > end_ts9:
                            break
                        qg9 += d9
                    qu9 += max(Decimal(0), min(qg9, qty_at(gid9, int(end_ts9 * 1000))))
                if qu9 > EPS:
                    f9 = min(1.0, float(qu9) / q9)
                    cut9 += u9 * f9
                    if u9 > 0:
                        px9[s9] = u9 / q9
                    if f9 < 1.0:
                        rest9[s9] = [round(q9 * (1 - f9), 12), round(u9 * (1 - f9), 2)]
                else:
                    rest9[s9] = [round(q9, 12), round(u9, 2)]
            return cut9, rest9, px9
        rate_now = float(extra.get("rate") or self.spot.rate or acct_norm.DEFAULT_KRW_USD)
        now_ts = time.time() if now_ts is None else float(now_ts)
        now_ms = int(now_ts * 1000)
        days = []
        att_src9 = {}
        self._daily_att_src = att_src9
        nf9 = set()
        self._daily_nf = nf9
        frozen_ok = os.path.exists(paths.state("backfill_done"))
        bf_at9 = 0.0
        if frozen_ok:
            try:
                with open(paths.state("backfill_done"), encoding="utf-8") as f9:
                    bf_at9 = float(f9.read(64).strip() or 0)
            except (OSError, ValueError):
                bf_at9 = 0.0
        meta_keys = ("_v", "_risk_rev", "_live", "_live_ok", "_reset_at", "_inval")
        xsrc9 = self._x_src_of(extra, now_ts)
        xpass9 = self._x_pass(xsrc9, self.daily_px, self.daily, today_kst, rate_now, run=hold_qty is not None and frozen_ok)
        pinned9 = xpass9["dpx"]
        self.daily, stamp_moved = daily_inval_apply(self.daily, inval, today_kst, not os.path.exists(paths.state("daily_cache.json")), meta_keys)
        if not any(k not in meta_keys for k in self.daily) and not self.daily.get("_reset_at"):
            self.daily["_reset_at"] = int(time.time())
        rev9 = ",".join(str(x) for x in sorted(skip_gids or ()))
        skip9s = {str(x) for x in (skip_gids or ())}
        if self.daily.get("_risk_rev") != rev9:
            kept9 = {"_v": DAILY_V, "_risk_rev": rev9}
            if self.daily.get("_reset_at"):
                kept9["_reset_at"] = self.daily["_reset_at"]
            if self.daily.get("_inval") is not None:
                kept9["_inval"] = self.daily["_inval"]
            for lk9 in ("_live", "_live_ok"):
                if isinstance(self.daily.get(lk9), dict):
                    kept9[lk9] = self.daily[lk9]
            n_re, n_drop = 0, 0
            for ck9, c9 in self.daily.items():
                if ck9 in meta_keys or not isinstance(c9, dict):
                    continue
                gv9 = c9.get("g")
                if isinstance(gv9, dict):
                    v9 = sum(float(v) for k, v in gv9.items() if k not in skip9s) + float(c9.get("x") or 0)
                    kept9[ck9] = dict(c9, val=_f(v9, 2) or 0)
                    n_re += 1
                else:
                    n_drop += 1
            self.daily = kept9
            log.info("격리 집합 변경 — 동결 과거일 %d일은 그룹별 마감값으로 재산출, 구형식 %d일은 재계산", n_re, n_drop)
            if frozen_ok:
                statefile.atomic_write_json(paths.state("daily_cache.json"), self.daily)
        lg_now9 = int(led_gen or 0)
        old9 = set()
        if lg_now9 and hold_qty is not None and frozen_ok:
            lo9, td9 = (today_kst - timedelta(days=29)).strftime("%Y-%m-%d"), today_kst.strftime("%Y-%m-%d")
            old9 = {ck9 for ck9, c9 in self.daily.items()
                    if not str(ck9).startswith("_") and isinstance(c9, dict) and lo9 <= str(ck9) < td9
                    and c9.get("src") == "live" and c9.get("snap") and _led_old(c9.get("lg"), c9.get("snap"), lg_now=lg_now9)}
            if old9 and self.__dict__.get("_led_old_logged") != (lg_now9, tuple(sorted(old9))):
                self._led_old_logged = (lg_now9, tuple(sorted(old9)))
                log.warning("일별: 원장 교체(세대 %s) 전 마감 스냅샷으로 동결된 날 %s — 지금 원장 수량으로 다시 계산(가격·x 는 그날 고정값)",
                            lg_now9, sorted(old9))
        live_snap = self.daily.get("_live") if isinstance(self.daily.get("_live"), dict) else None
        live_ok = self.daily.get("_live_ok") if isinstance(self.daily.get("_live_ok"), dict) else None
        timelines = {}
        for gid, g in G.items():
            tl = sorted(g["qty_timeline"])
            timelines[gid] = tl
        changed = bool(relabeled9 or migrated9 or xpass9["daily"] or self.__dict__.get("_daily_dirty"))
        changed = changed or stamp_moved
        px_changed = bool(pinned9 or relabeled9 or bound9 or migrated9 or self.__dict__.get("_dpx_dirty"))
        dpx = self.daily_px
        stable_gids9 = sorted(gid for gid, g in G.items() if g.get("is_stable") and not g.get("is_fiat"))
        stable_base9 = ",".join(str(x) for x in stable_gids9)
        neg9 = sorted(g9 for g9 in (neg_ok or ()) if g9 in G)
        stable_rev9 = stable_base9 + ("|n:" + ",".join(str(x) for x in neg9) if neg9 else "")
        dbt_now9 = {str(g9): round(float(q9), 8) for g9, q9 in sorted((debt_neg or {}).items()) if g9 in G and q9 > 0}
        def dbt_day(ck9, *sns9):
            for v9 in ((dpx.get("_dbt") or {}).get(ck9),) + tuple((s9 or {}).get("dbt") for s9 in sns9):
                if isinstance(v9, dict):
                    return v9
            return dbt_now9
        tr_by9 = {}
        for e9 in (transit or ()):
            tr_by9.setdefault(e9["gid"], []).append((int(e9["ts"]), Decimal(e9["qty"]), str(e9["uuid"])))
        dtr_by9 = {}
        for e9 in (dep_transit or ()):
            dtr_by9.setdefault(e9["gid"], []).append((int(e9["ts"]), Decimal(e9["qty"])))
        lp_tls9 = {gid: sorted(g["lp_tl"]) for gid, g in G.items() if g.get("lp_tl")}
        lp_to9 = {}
        if lp_tls9 and hold_qty is not None:
            for i9 in range(1, max(30, DAILY_PX_KEEP + 1)):
                d9 = today_kst - timedelta(days=i9)
                e9x = (self.daily_px.get(d9.strftime("%Y-%m-%d")) or {}).get("xv")
                if isinstance(e9x, dict) and e9x.get("v") == xparts.GEN:
                    _lp_obs_set(d9.replace(hour=23, minute=59, second=59, microsecond=0).timestamp(), _xv_parts(e9x), e9x.get("ts"), lp_to=lp_to9)
        def qty_at(gid9, end_ms9):
            q9 = hold_qty.get(gid9, Decimal(0))
            if end_ms9 < now_ms:
                for ts9, dq9 in reversed(timelines[gid9]):
                    if ts9 * 1000 <= end_ms9:
                        break
                    q9 -= dq9
                for t9, tq9, _u9 in tr_by9.get(gid9, ()):
                    if end_ms9 < t9 * 1000:
                        q9 -= tq9
                for t9, tq9 in dtr_by9.get(gid9, ()):
                    if end_ms9 < t9 * 1000:
                        q9 -= tq9
                if gid9 in lp_tls9 and end_ms9 in lp_to9:
                    q9 += _lp_after(gid9, lp_to9[end_ms9], lp_tls=lp_tls9)
            return q9
        lpfix9 = set()
        dfp9 = histcurve.disc_fp(G) if hold_qty is not None else ""
        xq9 = xq if (xq is not None and hold_qty is not None) else None
        xqb9 = None
        if xq9 is not None:
            st9x = self.daily_px.get("_xqb") if isinstance(self.daily_px.get("_xqb"), dict) else None
            if st9x is None:
                st9x = {"xq": xq_base if xq_base is not None else xq9, "at": int(now_ts)}
                self.daily_px["_xqb"] = st9x
                px_changed = True
            xqb9 = str(st9x.get("xq") or "")
        n_xq9 = 0
        if hold_qty is not None and frozen_ok:
            lo9q, td9q = (today_kst - timedelta(days=max(29, DAILY_PX_KEEP))).strftime("%Y-%m-%d"), today_kst.strftime("%Y-%m-%d")
            n_lq9, n_dq9 = 0, 0
            for ck9, c9 in self.daily.items():
                if str(ck9).startswith("_") or not isinstance(c9, dict) or not (lo9q <= str(ck9) < td9q):
                    continue
                if xq9 is not None:
                    nx9 = _xq_new(c9.get("xq", xqb9), xq=xq9)
                    if nx9:
                        lpfix9.add(ck9)
                        n_xq9 += 1
                        continue
                    if "xq" not in c9:
                        c9["xq"] = xq9
                        changed = True
                if c9.get("dq", "") != dfp9:
                    lpfix9.add(ck9)
                    n_dq9 += 1
                    continue
                if c9.get("src") != "live" and c9.get("lq") != DAILY_LQ_V:
                    if lp_tls9:
                        try:
                            e9q = int(datetime.strptime(str(ck9), "%Y-%m-%d").replace(tzinfo=today_kst.tzinfo, hour=23, minute=59, second=59).timestamp() * 1000)
                        except ValueError:
                            continue
                        if e9q in lp_to9 and _lp_moved_after(lp_to9[e9q], lp_tls=lp_tls9, skip_gids=skip_gids):
                            lpfix9.add(ck9)
                            continue
                    c9["lq"] = DAILY_LQ_V
                    n_lq9 += 1
                if "dq" not in c9:
                    c9["dq"] = dfp9
                    n_lq9 += 1
            if n_lq9:
                changed = True
            if lpfix9:
                old9 = set(old9) | lpfix9
                log.warning("일별: LP 위치 레그 보정·발견 시점 기초 잔고(지난날 포함 %d일)·새 거래소(%d일 · %s) — 옛 되감기로 동결된 날 %s 다시 계산"
                            "(가격·환율은 그날 고정값 · 수량·새 거래소 원장 밖 구성요소만)", n_dq9, n_xq9, xq9, sorted(lpfix9))
        hl9 = [m for m in (hist_late or ()) if isinstance(m, (list, tuple)) and len(m) >= 4] if hold_qty is not None else []
        hq_now9 = max((int(m[0]) for m in hl9), default=0)
        pw_memo9 = {}
        def pw_late9(sn9, end9):
            if late_after is None or hold_qty is None:
                return False
            try:
                pw9 = int(sn9.get("pw")) if sn9.get("pw") is not None else None
            except (TypeError, ValueError):
                pw9 = None
            if pw9 is None:
                return False
            k9 = (pw9, int(end9) + 1)
            if k9 not in pw_memo9:
                try:
                    pw_memo9[k9] = bool(late_after(pw9, int(end9) + 1))
                except Exception as e9:   # noqa: BLE001 [fallback]
                    calcguard.swallowed("view_daily:DailyMixin._daily_series.pw_late9", e9)
                    log.warning("일별: 마감 스냅숏 원장 수위 검사 실패(표식 검사만): %s", e9)
                    pw_memo9[k9] = False
            return pw_memo9[k9]
        hlr9 = set()
        if hl9:
            quiet9 = now_ts - max(int(m[3]) for m in hl9) >= HL_SETTLE_S
            rdy9 = [m for m in hl9 if quiet9 or now_ts - int(m[3]) >= HL_MAXWAIT_S]
            if rdy9 and frozen_ok:
                lo9h, td9h = (today_kst - timedelta(days=max(29, DAILY_PX_KEEP))).strftime("%Y-%m-%d"), today_kst.strftime("%Y-%m-%d")
                for ck9, c9 in self.daily.items():
                    if str(ck9).startswith("_") or not isinstance(c9, dict) or not (lo9h <= str(ck9) < td9h):
                        continue
                    try:
                        hq9 = int(c9.get("hq") or 0)
                    except (TypeError, ValueError):
                        hq9 = 0
                    if any(m[1] <= str(ck9) and int(m[0]) > hq9 for m in rdy9):
                        hlr9.add(ck9)
                if hlr9:
                    old9 = set(old9) | hlr9
                    if self.__dict__.get("_hl_logged") != (hq_now9, len(hlr9)):
                        self._hl_logged = (hq_now9, len(hlr9))
                        log.warning("일별: 늦게 들어온 원장 행(%s 부터) — 그 뒤 동결된 날 %d일(%s~%s) 다시 계산(가격·환율·원장 밖 금액은 그날 고정값 · 수량만)",
                                    min(m[1] for m in rdy9), len(hlr9), min(hlr9), max(hlr9))
            fw9 = self.daily_px.get("_hlf") if isinstance(self.daily_px.get("_hlf"), dict) else {}
            try:
                fwid9 = int(fw9.get("id") or 0)
            except (TypeError, ValueError):
                fwid9 = 0
            new9 = [m for m in rdy9 if int(m[0]) > fwid9] if frozen_ok else []
            if new9:
                min9 = min(m[1] for m in new9)
                if min9 <= (today_kst - timedelta(days=29)).strftime("%Y-%m-%d"):
                    try:
                        t9h = int(datetime.strptime(min9, "%Y-%m-%d").replace(tzinfo=today_kst.tzinfo, hour=12).timestamp())
                        log.info("장기 곡선 다시 계산 표식(늦은 원장 행): %s 부터", histmark.mark_hist_dirty(t9h))
                    except Exception as e9:   # noqa: BLE001 [fallback]
                        calcguard.swallowed("view_daily:DailyMixin._daily_series", e9)
                        log.warning("장기 곡선 다시 계산 표식(늦은 원장 행) 실패: %s", e9)
                        new9 = []
                if new9:
                    self.daily_px["_hlf"] = {"id": max(int(m[0]) for m in new9), "at": int(now_ts)}
                    px_changed = True
        if xq9 is not None:
            lo9x = (today_kst - timedelta(days=DAILY_PX_KEEP)).strftime("%Y-%m-%d")
            for ck9, e9 in dpx.items():
                xv9 = e9.get("xv") if isinstance(e9, dict) and not str(ck9).startswith("_") and str(ck9) >= lo9x else None
                if not (isinstance(xv9, dict) and isinstance(xv9.get("p"), dict)):
                    continue
                nx9 = _xq_new(xv9.get("xq", xqb9), xq=xq9)
                redo9 = not (frozen_ok and isinstance(self.daily.get(ck9), dict)) or ck9 in old9
                for ex9 in (sorted(nx9) if redo9 else ()):
                    for key9 in XQ_X_KEYS.get(ex9, ()):
                        v9 = xv9["p"].get(key9)
                        if isinstance(v9, (list, tuple)) and len(v9) >= 2 and v9[1] in ("carry", "zero"):
                            xv9["p"].pop(key9, None)
                if xv9.get("xq") != xq9:
                    xv9["xq"] = xq9
                    px_changed = True
        for gid9 in sorted(native_c or ()):
            if gid9 not in G:
                continue
            sid9, sym9 = str(gid9), G[gid9]["sym"]
            for ck9 in sorted(k9 for k9 in dpx if not k9.startswith("_")):
                e9 = dpx.get(ck9)
                if not isinstance(e9, dict) or ck9 >= today_kst.strftime("%Y-%m-%d"):
                    continue
                op9 = (e9.get("p") or {}).get(sid9)
                if not op9 or (e9.get("k") or {}).get(sid9):
                    continue
                try:
                    d9 = datetime.strptime(ck9, "%Y-%m-%d").replace(tzinfo=today_kst.tzinfo)
                except ValueError:
                    continue
                c9 = self.daily.get(ck9)
                done9 = (c9.get("native_c") or {}).get(sid9) if isinstance(c9, dict) and isinstance(c9.get("native_c"), dict) else None
                if done9 is not None:
                    e9["p"][sid9] = float(done9)
                    e9.setdefault("k", {})[sid9] = "c"
                    px_changed = True
                    continue
                c9p = self.px.candle_usd(sym9, int(d9.replace(hour=23, minute=59, second=59).timestamp() * 1000))
                if not c9p:
                    continue
                e9["p"][sid9] = float(c9p)
                e9.setdefault("k", {})[sid9] = "c"
                px_changed = True
                c9 = self.daily.get(ck9)
                if isinstance(c9, dict) and isinstance(c9.get("g"), dict) and sid9 in c9["g"]:
                    ov9 = Decimal(str(c9["g"][sid9]))
                    nv9 = ov9 * Decimal(str(c9p)) / Decimal(str(op9))
                    c9["g"][sid9] = round(float(nv9), 4)
                    if not (skip_gids and gid9 in skip_gids):
                        c9["val"] = _f(Decimal(str(c9["val"])) + nv9 - ov9, 2) or 0
                        if c9.get("est"):
                            e9s = float(c9["est"]) - abs(float(ov9))
                            if e9s >= 1:
                                c9["est"] = round(e9s, 2)
                            else:
                                c9.pop("est", None)
                    c9["src9"] = "native_candle"
                    c9.setdefault("native_c", {})[sid9] = float(c9p)
                    changed = True
                    log.info("일별 %s: 네이티브 %s(g%s) 근사가 $%.2f → 1분봉 $%.2f (%+.2f)", ck9, sym9, sid9, float(op9), float(c9p),
                             float(nv9 - ov9))
        if day_close is not None and hold_qty is not None and frozen_ok:
            r10 = _px1004_reset(self.daily, dpx, G, today_kst.strftime("%Y-%m-%d"), day_close, live_px, skip_gids, now_ts)
            if r10["n"]:
                changed = changed or r10["changed"]
                px_changed = True
                log.warning("일별: px1004 업비트·빗썸 USDT·BTC 마켓 그날 마감가 %d개 근사로 되돌림 — 총자산 차 %+.2f · 새 순서로 다시 받는다", r10["n"], r10["dv"])
            if self.__dict__.get("_pxfix_key") != _pxfix_key(day_close=day_close, today_kst=today_kst, now_ts=now_ts, dpx=dpx, sb=self):
                r9 = _reprice_now_days(self.daily, dpx, G, today_kst.strftime("%Y-%m-%d"), now_ts, day_close, skip_gids)
                self._pxfix_last = r9
                if r9["changed"]:
                    changed = True
                if r9["px_changed"]:
                    px_changed = True
                self._pxfix_key = _pxfix_key(day_close=day_close, today_kst=today_kst, now_ts=now_ts, dpx=dpx, sb=self)
                if r9["rep"] or r9["fin"]:
                    log.info("일별: 그날 마감가 재평가 %d · 근사 확정 %d · 대기 %d · 총자산 차 %+.2f", r9["rep"], r9["fin"], r9["pend"], r9["dv"])
        drd_all9 = {m9["pid"]: 0 for m9 in (debt_moves or ())}
        for m9 in (debt_moves or ()):
            sid9, gid9 = str(m9["gid"]), m9["gid"]
            g09 = G.get(gid9) or {}
            for ck9, c9 in sorted(self.daily.items()):
                if ck9.startswith("_") or not isinstance(c9, dict) or not isinstance(c9.get("g"), dict) or ck9 >= today_kst.strftime("%Y-%m-%d"):
                    continue
                if m9["pid"] in (c9.get("drd") or {}):
                    continue
                try:
                    end9 = datetime.strptime(ck9, "%Y-%m-%d").replace(tzinfo=today_kst.tzinfo, hour=23, minute=59, second=59).timestamp()
                except ValueError:
                    continue
                if not (m9["t_new"] <= end9 < m9["t_old"]):
                    continue
                ov9 = Decimal(str(c9["g"].get(sid9) or 0))
                if g09.get("is_stable") and not g09.get("is_fiat"):
                    p9 = Decimal(1)
                else:
                    fp9 = ((dpx.get(ck9) or {}).get("p") or {}).get(sid9)
                    p9 = Decimal(str(fp9)) if fp9 else Decimal(0)
                nv9 = ov9
                if p9 > 0:
                    q9 = ov9 / p9 - m9["q"]
                    nv9 = q9 * p9 if q9 > EPS else Decimal(0)
                dv9 = nv9 - ov9
                if nv9 > 0:
                    c9["g"][sid9] = round(float(nv9), 4)
                else:
                    c9["g"].pop(sid9, None)
                if dv9 and not (skip_gids and gid9 in skip_gids):
                    c9["val"] = _f(Decimal(str(c9["val"])) + dv9, 2) or 0
                    if c9.get("est") and not g09.get("is_stable") and not ((dpx.get(ck9) or {}).get("k") or {}).get(sid9):
                        e9s = float(c9["est"]) + float(dv9)
                        if e9s >= 1:
                            c9["est"] = round(e9s, 2)
                        else:
                            c9.pop("est", None)
                c9.setdefault("drd", {})[m9["pid"]] = round(float(dv9), 2)
                c9["src9"] = "debt_redate"
                changed = True
                log.info("일별 %s: 기존 부채 첫 반영 소급(posting %s) %s %s × $%s → %+.2f", ck9, m9["pid"], g09.get("sym"),
                         format(m9["q"], "f"), format(p9, "f"), float(dv9))
        pre9 = self.__dict__.get("_px_pre_gids") or {}
        bf_gids9 = sorted(gid9 for gid9 in (set(ca_gids) | set(ex_gids)) if gid9 in G and gid9 not in override_px and gid9 not in pre9
                          and not G[gid9].get("is_stable") and not G[gid9].get("is_fiat") and (live_px.get(gid9) or 0) > 0)
        bf_rev9 = ",".join(str(x) for x in bf_gids9)
        bf_seen9 = self.__dict__.setdefault("_px_bf_seen", {})
        def px_backfill(ck9, d9, c9):
            sn9 = bf_seen9.get(ck9)
            if sn9 and sn9[0] == bf_rev9 and sn9[1] is c9:
                return False
            bf_seen9[ck9] = (bf_rev9, c9)
            allow9 = _live_allow(c9)
            if allow9 is not None and not allow9:
                return False
            end_ms9 = int(d9.replace(hour=23, minute=59, second=59, microsecond=0).timestamp() * 1000)
            fx9 = dpx.get(ck9) or {}
            fp9, fk9 = fx9.get("p") or {}, fx9.get("k") or {}
            sd9 = (self._daily_seed.get(ck9) or {}).get("g") or {}
            add9, est9, n9 = Decimal(0), Decimal(0), 0
            ubp9 = xu_cut(c9.get("xu"), end_ms9 / 1000)[2] if c9.get("xu") else {}
            added9 = []
            wait9 = False
            for gid9 in bf_gids9:
                sid9 = str(gid9)
                if sid9 in c9["g"] or (allow9 is not None and sid9 not in allow9):
                    continue
                q9 = qty_at(gid9, end_ms9)
                if q9 <= EPS:
                    continue
                c9b = None
                if not (sid9 in fp9 and fp9[sid9]) and native_c and gid9 in native_c:
                    c9b = self.px.candle_usd(G[gid9]["sym"], end_ms9)
                    if c9b is None and _px_took(self.px):
                        wait9 = True
                        continue
                ubs9 = str(G[gid9].get("sym") or "").upper()
                if sid9 in fp9 and fp9[sid9]:
                    p9, k9 = float(fp9[sid9]), fk9.get(sid9) or "now"
                elif gid9 in ub_tl9 and ubs9 in ubp9:
                    p9, k9 = ubp9[ubs9], "ub"
                elif c9b:
                    p9, k9 = float(c9b), "c"
                else:
                    p9, k9 = float(live_px[gid9]), "now"
                    sv9 = sd9.get(sid9)
                    try:
                        sp9 = float(Decimal(str(sv9)) / q9) if sv9 is not None else None
                    except (InvalidOperation, ValueError, ZeroDivisionError):
                        sp9 = None
                    if sp9 and 0.5 <= sp9 / p9 <= 2.0:
                        p9, k9 = sp9, "seed"
                    elif day_close is not None and float(q9) * p9 >= DC_SMALL_USD:
                        dcb9 = day_close(gid9, ck9, float(q9) * p9, ref=p9)[0]
                        if dcb9:
                            p9, k9 = float(dcb9), "d"
                v9 = q9 * Decimal(str(p9))
                if abs(v9) < Decimal("0.00005"):
                    continue
                c9["g"][sid9] = round(float(v9), 4)
                n9 += 1
                added9.append(gid9)
                if sid9 not in fp9:
                    e9 = dpx.setdefault(ck9, {"p": {}, "k": {}})
                    e9.setdefault("p", {})[sid9] = p9
                    if k9 != "now":
                        e9.setdefault("k", {})[sid9] = k9
                    if k9 in ("d", "c") and (live_px.get(gid9) or 0) > 0:
                        e9.setdefault("lp", {}).setdefault(sid9, float(live_px[gid9]))
                if not (skip_gids and gid9 in skip_gids):
                    add9 += v9
                    if k9 == "now":
                        est9 += v9
            if wait9:
                bf_seen9.pop(ck9, None)
            if not n9:
                return False
            if add9:
                c9["val"] = _f(Decimal(str(c9["val"])) + add9, 2) or 0
            if est9 >= 1:
                c9["est"] = round(float(c9.get("est") or 0) + float(est9), 2)
            _frozen_ub_cut(c9, end_ms9 / 1000, added9, ub_tl=ub_tl9, G=G, xu_cut=xu_cut)
            c9["src9"] = "px_backfill"
            log.info("일별 %s: 늦게 가격이 생긴 그룹 %d개 소급 %+.2f (근사 %.2f)", ck9, n9, float(add9), float(est9))
            return True

        for i in range(max(29, DAILY_PX_KEEP), -1, -1):
            d = (today_kst - timedelta(days=i))
            dkey = d.strftime("%m-%d")
            dow = "일월화수목금토"[int(d.strftime("%w"))]
            is_today = (i == 0)
            ck = d.strftime("%Y-%m-%d")
            if i >= 30 and ck not in lpfix9 and ck not in hlr9:
                continue
            if not is_today and frozen_ok and ck in self.daily and ck not in old9:
                c = self.daily[ck]
                z_st9 = (c.get("src") == "live" and isinstance(c.get("z"), list) and isinstance(c.get("g"), dict)
                         and any(str(gid9) in c["z"] and str(gid9) not in c["g"] for gid9 in stable_gids9))
                if hold_qty is not None and isinstance(c.get("g"), dict) and (c.get("st") != stable_rev9 or z_st9):
                    end_ms9 = int(d.replace(hour=23, minute=59, second=59, microsecond=0).timestamp() * 1000)
                    add9 = Decimal(0)
                    allow_st9 = _live_allow(c)
                    added_st9 = []
                    only_neg9 = c.get("st") != stable_rev9 and str(c.get("st") or "").split("|n:", 1)[0] == stable_base9
                    for gid9 in stable_gids9:
                        neg_g9 = bool(neg_ok and gid9 in neg_ok)
                        if only_neg9 and not neg_g9:
                            continue
                        if str(gid9) in c["g"]:
                            continue
                        out_z9 = allow_st9 is not None and str(gid9) not in allow_st9
                        if out_z9 and not neg_g9:
                            continue
                        q9 = qty_at(gid9, end_ms9)
                        if out_z9 and not q9 < Decimal("-0.00005"):
                            continue
                        if q9 > Decimal("0.00005") or (neg_g9 and q9 < Decimal("-0.00005")):
                            c["g"][str(gid9)] = round(float(q9), 4)
                            added_st9.append(gid9)
                            if not (skip_gids and gid9 in skip_gids):
                                add9 += q9
                    if add9:
                        c["val"] = _f(Decimal(str(c["val"])) + add9, 2) or 0
                        c["src9"] = "stable_backfill"
                    _frozen_ub_cut(c, end_ms9 / 1000, added_st9, ub_tl=ub_tl9, G=G, xu_cut=xu_cut)
                    c["st"] = stable_rev9
                    changed = True
                if hold_qty is not None and isinstance(c.get("g"), dict) and bf_gids9 and px_backfill(ck, d, c):
                    changed = True
                    px_changed = True
                row9 = {"date": dkey, "dow": dow, "val": c["val"], "usdt": c.get("usdt"), "kimp": c.get("kimp")}
                if c.get("est"):
                    row9["est"] = c["est"]
                if c.get("xc"):
                    row9["xc"] = c["xc"]
                days.append(row9)
                att_src9[ck] = (c.get("g"), (dpx.get(ck) or {}).get("p"), c.get("xu"))
                continue
            end = d.replace(hour=23, minute=59, second=59, microsecond=0)
            end_ts = end.timestamp()
            end_ms = now_ms if is_today else int(end_ts * 1000)
            snap1 = None
            part1 = None
            old1 = False
            old_sn1 = None
            if not is_today and hold_qty is not None:
                for sn9 in (live_snap, live_ok, (dpx.get(ck) or {}).get("partial")):
                    if (sn9 and sn9.get("date") == ck and isinstance(sn9.get("g"), dict)
                            and float(sn9.get("ts") or 0) >= end_ts - DAILY_LIVE_WIN):
                        if not sn9.get("defer"):
                            gen9 = _led_old(sn9.get("lg"), sn9.get("ts"), lg_now=lg_now9) or bool(sn9.get("led_other"))
                            late9 = (any(m[1] <= ck and int(m[0]) > int(sn9.get("hq") or 0) for m in hl9)
                                     or pw_late9(sn9, end_ts))
                            if (gen9 or sn9.get("dq", "") != dfp9
                                    or (xq9 is not None and _xq_new(sn9.get("xq", xqb9), xq=xq9))
                                    or float(sn9.get("ts") or 0) < bf_at9
                                    or late9):
                                old1 = True
                                old_sn1 = old_sn1 or sn9
                                if (float(sn9.get("ts") or 0) < bf_at9 or (late9 and not gen9)) and isinstance(sn9.get("p"), dict):
                                    e9p = dpx.setdefault(ck, {"p": {}, "k": {}})
                                    for sid9, px9 in sn9["p"].items():
                                        if px9 and str(sid9) not in e9p.setdefault("p", {}):
                                            e9p["p"][str(sid9)] = px9
                                            e9p.setdefault("k", {})[str(sid9)] = "live"
                                            px_changed = True
                                continue
                            snap1 = sn9
                            break
                        if part1 is None:
                            part1 = sn9
            if part1 is not None and snap1 is None and frozen_ok and (dpx.get(ck) or {}).get("partial") is not part1:
                dpx.setdefault(ck, {"p": {}, "k": {}})["partial"] = part1
                px_changed = True
            if snap1 is not None:
                gs = snap1["g"]
                fxv1 = (dpx.get(ck) or {}).get("xv")
                if isinstance(fxv1, dict) and fxv1.get("v") == xparts.GEN and _xv_parts(fxv1) is not None:
                    xs_p9 = xparts.resolve(end_ts, xsrc9, pinned=_xv_obs_parts(fxv1))
                    xs_fx9 = xparts.num(fxv1.get("fx")) or xparts.num(snap1.get("usdt")) or rate_now
                    xs_m9 = {k9: fxv1[k9] for k9 in ("ob", "x0", "ts", "part", "xq", "ufc", "ufz") if k9 in fxv1}
                else:
                    xs_p9, xs_fx9, xs_m9 = self._x_obs_parts(snap1, end_ts, xsrc9, rate_now)
                    if xs_fx9 is None:
                        xs_fx9 = self.px.fx_at(int(end_ts) * 1000) or rate_now
                xs_p9 = _xv_parts(_xv_disk(xs_p9, None, "snap"))
                if lp_tls9:
                    _lp_obs_set(end_ts, xs_p9, snap1.get("ts"), lp_to=lp_to9)
                xs_raw9 = round(xparts.total_usd(xs_p9, xs_fx9), 2)
                xs = float(snap1.get("x") or 0)
                if abs(xs_raw9 - xs) >= 0.005:
                    if frozen_ok:
                        log.info("일별 %s: 마감 스냅숏에 없던 원장 밖 금액 구성요소 채움 %+.2f(원화 이력·이월)", ck, xs_raw9 - xs)
                    xs = xs_raw9
                xu_sn9 = ({s9: list(a9) for s9, a9 in xs_p9["ub"][0].items()} if xs_p9.get("ub") and xs_p9["ub"][0]
                          else snap1.get("xu"))
                v1 = _f(sum(float(v) for k, v in gs.items() if k not in skip9s) + xs, 2) or 0
                days.append({"date": dkey, "dow": dow, "val": v1,
                             "usdt": snap1.get("usdt"), "kimp": snap1.get("kimp")})
                if frozen_ok:
                    self.daily[ck] = {"val": v1, "usdt": snap1.get("usdt"), "kimp": snap1.get("kimp"),
                                      "g": dict(gs), "x": round(xs, 2), "src": "live", "st": stable_rev9,
                                      "snap": int(float(snap1.get("ts") or 0)), "dq": dfp9}
                    if xq9 is not None:
                        self.daily[ck]["xq"] = xq9
                    if snap1.get("lg") is not None:
                        self.daily[ck]["lg"] = snap1["lg"]
                    if hq_now9:
                        self.daily[ck]["hq"] = hq_now9
                    self.daily[ck]["xraw"] = xs_raw9
                    xc_sn9 = xparts.carry_usd(xs_p9, xs_fx9)
                    if xc_sn9 >= 1:
                        self.daily[ck]["xc"] = round(xc_sn9, 2)
                    xu9s = _xu_keep(xu_sn9)
                    if xu9s:
                        self.daily[ck]["xu"] = xu9s
                    if snap1.get("z"):
                        self.daily[ck]["z"] = list(snap1["z"])
                    if isinstance(snap1.get("wdt"), dict) and snap1["wdt"]:
                        self.daily[ck]["wdt"] = snap1["wdt"]
                    if isinstance(snap1.get("drd"), list):
                        self.daily[ck]["drd"] = {str(k9): 0 for k9 in snap1["drd"]}
                    changed = True
                    lp9 = snap1.get("p")
                    if not isinstance(lp9, dict):
                        lp9 = {}
                        for k9, v9 in gs.items():
                            try:
                                gid9 = int(k9)
                            except ValueError:
                                continue
                            if gid9 in G and not G[gid9].get("is_stable"):
                                q9 = qty_at(gid9, int(end_ts * 1000))
                                if q9 > EPS and float(v9) > 0:
                                    lp9[k9] = float(Decimal(str(v9)) / q9)
                    dpx[ck] = {"p": {k9: v9 for k9, v9 in lp9.items() if v9}, "k": {k9: "live" for k9, v9 in lp9.items() if v9},
                               "x": round(xs, 2), "xk": "live"}
                    if isinstance(snap1.get("dbt"), dict):
                        dpx.setdefault("_dbt", {})[ck] = dict(snap1["dbt"])
                    if xu9s:
                        dpx[ck]["xu"] = xu9s
                    dpx[ck]["xv"] = _xv_disk(xs_p9, xs_fx9, "snap", **dict(xs_m9, **({"xq": xq9} if xq9 is not None else {})))
                    if xc_sn9 >= 1:
                        dpx[ck]["xc"] = round(xc_sn9, 2)
                    px_changed = True
                att_src9[ck] = (gs, snap1.get("p") if isinstance(snap1.get("p"), dict) else (dpx.get(ck) or {}).get("p"), xu_sn9)
                continue
            px_live = is_today or end_ms >= now_ms - 120_000
            fixed = (dpx.get(ck) or {}) if not is_today else {}
            fixed_p, fixed_k = fixed.get("p") or {}, fixed.get("k") or {}
            seed = self._daily_seed.get(ck) if not is_today else None
            seed_x = seed if ck not in dpx else None
            new_p, new_k = {}, {}
            new_lp = {}
            pxu9 = {}
            est = Decimal(0)
            total = Decimal(0)
            gvals = {}
            defer = False
            pend9 = []
            z9 = []
            n_est9 = 0
            x_stale9 = False
            fx_wait9 = False
            part_g9, part_p9, part_pend9 = None, {}, set()
            xp9, xfx9, xhow9, xmeta9 = None, None, None, {}
            if hold_qty is not None and not is_today:
                xp9, xfx9, xhow9, xmeta9 = self._x_day(ck, end_ts, part1, old_sn1, live_snap, fixed, seed_x, xsrc9, rate_now)
                xp9 = _xv_parts(_xv_disk(xp9, None, xhow9))
                if lp_tls9:
                    _lp_obs_set(end_ts, xp9, (xmeta9 or {}).get("ts"), lp_to=lp_to9)
            xu_src9 = {s9: list(a9) for s9, a9 in xp9["ub"][0].items()} if xp9 and xp9.get("ub") and xp9["ub"][0] else None
            xcut9, xrest9, ubpx9 = xu_cut(xu_src9, end_ts) if xu_src9 else (0.0, {}, {})
            if part1 is not None:
                part_g9 = part1["g"]
                part_p9 = part1.get("p") if isinstance(part1.get("p"), dict) else {}
                part_pend9 = {str(x9) for x9 in (part1.get("pend") or ())}
            dn9 = dbt_now9 if is_today else dbt_day(ck, part1, old_sn1)
            for gid, g in G.items():
                skip9 = bool(skip_gids and gid in skip_gids)
                if g.get("is_fiat"):
                    continue
                if hold_qty is not None:
                    qty = qty_at(gid, end_ms)
                else:
                    qty = Decimal(0)
                    for ts, dq in timelines[gid]:
                        if ts * 1000 <= end_ms:
                            qty += dq
                if qty <= EPS and not (qty < -EPS and neg_ok and gid in neg_ok):
                    dc9 = dn9.get(str(gid)) if qty < -EPS else None
                    if not dc9:
                        continue
                    qty = max(qty, -Decimal(str(dc9)))
                sym = g["sym"]
                sid = str(gid)
                if g["is_stable"]:
                    gvals[sid] = qty
                    if not skip9:
                        total += qty
                    continue
                if (sym in STABLE_GROUPS and gid not in ca_gids
                        and gid not in ex_gids and gid not in override_px):
                    continue
                ov = override_px.get(gid)
                if ov is not None and not ((ck in old9 or old1) and sid in fixed_p):
                    pxu9[sid] = float(ov)
                    gvals[sid] = qty * Decimal(str(ov))
                    if not skip9:
                        total += gvals[sid]
                    if is_today:
                        new_p[sid] = float(ov)
                    continue
                kind = None
                if sid in fixed_p:
                    px = fixed_p[sid]
                    kind = fixed_k.get(sid) or "now"
                elif part_g9 is not None and sid in part_g9 and sid not in part_pend9 and float(part_g9[sid]) != 0:
                    px = part_p9.get(sid) or float(Decimal(str(part_g9[sid])) / qty)
                    kind = "live"
                elif gid in ub_tl9 and str(sym or "").upper() in ubpx9:
                    px = ubpx9[str(sym or "").upper()]
                    kind = "ub"
                elif gid in ca_gids:
                    px = live_px.get(gid) or 0
                    kind = "live" if px_live else "now"
                    if gid in pending_gids and not skip9:
                        defer = True
                        pend9.append(sid)
                elif gid in ex_gids:
                    c9x = None
                    if not px_live and native_c and gid in native_c:
                        c9x = self.px.candle_usd(sym, end_ms)
                        if c9x is None and _px_took(self.px) and not skip9:
                            defer = True
                            pend9.append(sid)
                    if c9x:
                        px, kind = c9x, "c"
                    else:
                        px = live_px.get(gid) or 0
                        kind = "live" if px_live else "now"
                        if gid in pending_gids and not skip9:
                            defer = True
                            pend9.append(sid)
                elif px_live and (is_today or sid not in part_pend9):
                    _px_took(self.px)
                    px = live_px[gid] if gid in live_px else (
                        self.spot.price(sym) or self.px.candle_usd(sym, end_ms) or 0)
                    kind = "live"
                    if not skip9 and (gid in px_wait9 or (not px and _px_took(self.px))):
                        defer = True
                        pend9.append(sid)
                else:
                    px = self.px.candle_usd(sym, end_ms) or 0
                    kind = "c"
                    if not px and _px_took(self.px) and not skip9:
                        defer = True
                        pend9.append(sid)
                if kind == "now" and seed and px and sid not in fixed_p:
                    sv9 = (seed.get("g") or {}).get(sid)
                    try:
                        sp9 = float(Decimal(str(sv9)) / qty) if sv9 is not None else None
                    except (InvalidOperation, ValueError, ZeroDivisionError):
                        sp9 = None
                    if sp9 and 0.5 <= sp9 / float(px) <= 2.0:
                        px, kind = sp9, "seed"
                if (kind == "now" and day_close is not None and hold_qty is not None and sid not in fixed_p
                        and abs(float(qty) * float(px or 0)) >= DC_SMALL_USD):
                    dcp9 = day_close(gid, ck, abs(float(qty) * float(px or 0)), ref=px)[0]
                    if dcp9:
                        px, kind = dcp9, "d"
                if px and sid not in fixed_p:
                    new_p[sid] = float(px)
                    if kind != "now":
                        new_k[sid] = kind
                    if kind in ("d", "c") and not is_today and (live_px.get(gid) or 0) > 0:
                        new_lp[sid] = float(live_px[gid])
                if is_today and not px and not skip9 and (gid in ca_gids or gid in ex_gids):
                    z9.append(sid)
                gvals[sid] = qty * Decimal(str(px))
                if px:
                    pxu9[sid] = float(px)
                if not skip9:
                    total += gvals[sid]
                    if kind == "now" and not is_today:
                        est += abs(gvals[sid])
                        n_est9 += 1
            usdt = None
            kimp = None
            fx = None
            fix9 = ck in old9 or old1
            fx_src9 = ((self.daily.get(ck) if ck in old9 else None) or old_sn1 or {}) if fix9 else {}
            if fix9 and fx_src9.get("usdt"):
                usdt = fx_src9["usdt"]
                kimp = fx_src9.get("kimp")
                fx = float(usdt)
            elif px_live:
                usdt = self.spot.rate or None
                if usdt and self.spot.fx_basis:
                    kimp = round((usdt / self.spot.fx_basis - 1) * 100, 2)
                if _rate_state(self.spot, now_ts) != "live":
                    defer = True
                    fx_wait9 = True
            else:
                fx = self.px.fx_at(end_ms)
                if fx is None and (_px_took(self.px) or fix9):
                    defer = True
                usdt = round(fx) if fx else None
                if usdt and self.spot.fx_basis:
                    kimp = round((usdt / self.spot.fx_basis - 1) * 100, 2)
            x_carry = 0.0
            x_kind = None
            if hold_qty is None:
                x_day = 0.0
            elif is_today:
                x_day = x_now
                if extra and extra.get("ufd"):
                    defer = x_stale9 = True
            else:
                xfx9 = xfx9 or float(fx or rate_now)
                x_day = round(xparts.total_usd(xp9, xfx9), 2)
                x_carry = xparts.carry_usd(xp9, xfx9)
                x_kind = ({"part": "live", "snap": "live", "day": "live", "seed": "seed"}.get(xhow9)
                          or ("live" if all(v9[1] == "snap" for v9 in xp9.values()) else "calc"))
                if xhow9 == "calc" and not extra_ok:
                    defer = True
                    x_stale9 = True
            x_raw9, xc_raw9 = x_day, x_carry
            if xcut9:
                x_day -= xcut9
                if (xp9.get("ub") or [None, None])[1] == "carry":
                    x_carry = max(0.0, x_carry - xcut9)
            total += Decimal(str(x_day))
            entry = {"date": dkey, "dow": dow,
                     "val": _f(total, 2) or 0, "usdt": usdt, "kimp": kimp}
            if est >= 1:
                entry["est"] = round(float(est), 2)
            if x_carry >= 1:
                entry["xc"] = round(x_carry, 2)
            days.append(entry)
            if ck in old9 and defer:
                nf9.add(ck)
            g_out = {k: round(float(v), 4) for k, v in gvals.items() if abs(v) >= Decimal("0.00005")}
            att_src9[ck] = (g_out, pxu9, (ubs_now if hold_qty is not None else {}) if is_today else xrest9)
            if is_today and hold_qty is not None:
                self.daily["_live"] = {"date": ck, "ts": round(now_ts, 3), "val": entry["val"], "usdt": usdt,
                                       "kimp": kimp, "g": g_out, "x": round(x_day, 2), "defer": defer,
                                       "p": {k9: round(v9, 12) for k9, v9 in new_p.items()}}
                if dbt_now9:
                    self.daily["_live"]["dbt"] = dict(dbt_now9)
                if lg_now9:
                    self.daily["_live"]["lg"] = lg_now9
                self.daily["_live"]["dq"] = dfp9
                if hq_now9:
                    self.daily["_live"]["hq"] = hq_now9
                if led_pw is not None:
                    self.daily["_live"]["pw"] = int(led_pw)
                if xq9 is not None:
                    self.daily["_live"]["xq"] = xq9
                if ubs_now:
                    self.daily["_live"]["xu"] = _xu_keep(ubs_now)
                xv9 = _xv_checked(extra.get("xv"), round(x_day, 2))
                if xv9 is not None:
                    xv9["ts"] = int(now_ts)
                    self.daily["_live"]["xv"] = xv9
                    if xv9.get("dx") is not None and self.__dict__.get("_xv_dx_day") != ck:
                        self._xv_dx_day = ck
                        log.warning("일별 오늘(%s): 원장 밖 금액 구성요소 합이 x 와 다름(x − 합 = %+.2f) — 구성요소 기록만, x 는 무변", ck, xv9["dx"])
                if pend9:
                    self.daily["_live"]["pend"] = sorted(set(pend9))
                if z9:
                    self.daily["_live"]["z"] = sorted(set(z9))
                if x_stale9:
                    self.daily["_live"]["xs"] = 1
                if fx_wait9:
                    self.daily["_live"]["fxw"] = 1
                if usdt and getattr(self.spot, "rate_ts", None):
                    self.daily["_live"]["fxt"] = int(self.spot.rate_ts)
                if debt_moves is not None:
                    self.daily["_live"]["drd"] = sorted(drd_all9)
                wdt9 = _wdt_at(now_ts, tr_by=tr_by9)
                if wdt9:
                    self.daily["_live"]["wdt"] = wdt9
                in_win9 = now_ts >= end_ts - DAILY_LIVE_WIN
                if in_win9 and not defer:
                    self.daily["_live_ok"] = self.daily["_live"]
                if in_win9 and now_ts - getattr(self, "_live_saved_at", 0) >= 50:
                    self._live_saved_at = now_ts
                    changed = True
            elif not is_today and frozen_ok and not defer:
                self.daily[ck] = {"val": entry["val"], "usdt": usdt, "kimp": kimp, "g": g_out,
                                  "x": round(x_day, 2), "src": "partial" if part1 is not None else "calc", "st": stable_rev9,
                                  "lq": DAILY_LQ_V, "dq": dfp9}
                if xq9 is not None:
                    self.daily[ck]["xq"] = xq9
                if hq_now9:
                    self.daily[ck]["hq"] = hq_now9
                if xp9 is not None:
                    self.daily[ck]["xraw"] = round(x_raw9, 2)
                if xrest9:
                    self.daily[ck]["xu"] = xrest9
                if xcut9:
                    self.daily[ck]["x0"] = round(x_raw9, 2)
                    self.daily[ck]["xu0"] = _xu_keep(xu_src9)
                if debt_moves is not None:
                    self.daily[ck]["drd"] = dict(drd_all9)
                wdt9 = _wdt_at(end_ts, tr_by=tr_by9)
                if wdt9:
                    self.daily[ck]["wdt"] = wdt9
                if (dpx.get(ck) or {}).pop("partial", None) is not None:
                    px_changed = True
                if hold_qty is not None:
                    if part1 is not None:
                        self.daily[ck]["snap"] = int(float(part1.get("ts") or 0))
                        self.daily[ck]["pend"] = len(part_pend9) if part1.get("pend") is not None else n_est9
                        if part1.get("xs"):
                            self.daily[ck]["xs"] = 1
                    else:
                        self.daily[ck]["why"] = "led" if old1 else "no_snap"
                if entry.get("est"):
                    self.daily[ck]["est"] = entry["est"]
                if entry.get("xc"):
                    self.daily[ck]["xc"] = entry["xc"]
                changed = True
                if hold_qty is not None:
                    e9 = dpx.setdefault(ck, {"p": {}, "k": {}})
                    e9.setdefault("p", {}).update(new_p)
                    e9.setdefault("k", {}).update(new_k)
                    if dn9 and not isinstance((dpx.get("_dbt") or {}).get(ck), dict):
                        dpx.setdefault("_dbt", {})[ck] = dict(dn9)
                    for k9, v9 in new_lp.items():
                        e9.setdefault("lp", {}).setdefault(k9, v9)
                    if xp9 is not None:
                        how9 = ((e9.get("xv") or {}).get("how") or "calc") if xhow9 == "fixed" else xhow9
                        xv_new9 = _xv_disk(xp9, xfx9, how9, **dict(xmeta9, **({"xq": xq9} if xq9 is not None else {})))
                        if e9.get("xv") != xv_new9:
                            e9["xv"] = xv_new9
                        e9["x"], e9["xk"] = round(x_raw9, 2), (x_kind if x_kind in ("live", "seed") else "calc")
                        if xc_raw9 >= 1:
                            e9["xc"] = round(xc_raw9, 2)
                        else:
                            e9.pop("xc", None)
                        xu9p = _xu_keep(xu_src9) if xu_src9 else {}
                        if xu9p:
                            e9["xu"] = xu9p
                        else:
                            e9.pop("xu", None)
                    px_changed = True
        xd9, xo9 = {}, {}
        for ck9, e9 in dpx.items():
            xv9 = e9.get("xv") if isinstance(e9, dict) and len(str(ck9)) == 10 and str(ck9)[4] == "-" else None
            p9 = _xv_parts(xv9) if isinstance(xv9, dict) and xv9.get("v") == xparts.GEN else None
            if p9 is None:
                continue
            xd9[ck9] = {"p": p9, "fx": xparts.num(xv9.get("fx"))}
            if xparts.num(xv9.get("ts")):
                xd9[ck9]["ts"] = float(xv9["ts"])
            o9 = xparts.obs_entry(_x_end(ck9, today_kst.tzinfo), p9, ("snap", "tl", "carry"))
            if len(o9) > 1:
                xo9[ck9] = o9
        self._x_kit = {"src": {k9: xsrc9.get(k9) for k9 in ("now", "base", "tl", "first", "bad")}, "obs": xo9, "days": xd9}
        lpc9 = {}
        for i9 in range(1, 30):
            d9 = today_kst - timedelta(days=i9)
            to9 = lp_to9.get(int(d9.replace(hour=23, minute=59, second=59, microsecond=0).timestamp() * 1000))
            if to9 is None:
                continue
            c9 = {g9: float(v9) for g9 in lp_tls9 for v9 in (_lp_after(g9, to9, lp_tls=lp_tls9),) if abs(v9) > EPS}
            if c9:
                lpc9[d9.strftime("%Y-%m-%d")] = c9
        self._daily_lpc = lpc9
        if _capture_px_blocks(self.daily, dpx, lo_bind9) or px_changed:
            changed = True
        if changed:
            self._daily_dirty = True
        if px_changed and frozen_ok:
            self._dpx_dirty = True
        if changed:
            statefile.atomic_write_json(paths.state("daily_cache.json"), self.daily)
            self._daily_dirty = False
        if px_changed and frozen_ok:
            lo9 = (today_kst - timedelta(days=DAILY_PX_KEEP)).strftime("%Y-%m-%d")
            for k9 in [k9 for k9 in dpx if not k9.startswith("_") and k9 < lo9]:
                dpx.pop(k9, None)
            statefile.atomic_write_json(paths.state("daily_px.json"), dpx)
            self._dpx_dirty = False
        self.px.flush()
        return days[-30:]
