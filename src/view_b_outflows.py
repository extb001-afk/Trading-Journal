from __future__ import annotations
import acct_norm
import salelink
from view_common import CHAIN_NAME
from view_common import _f
from view_misc import _rate_state
from view_xv import XV_V
import logging
import calcguard  # noqa: E402

log = logging.getLogger('tj-web')


def _ofc_cp(dst, src):
    if len(dst) != len(src) or any(c.get("t") != s.get("t") or c.get("k") != s.get("k") or c.get("tx") != s.get("tx") for c, s in zip(dst, src)):
        return
    for c, s in zip(dst, src):
        if s.get("ofc"):
            c["ofc"] = dict(s["ofc"])
        else:
            c.pop("ofc", None)


class OutflowsBuildMixin:

    def _build_outflows(self, _bs9):
        (G, _k9, _nopid9, ask9, conn, ev_hid9, ev_main9, ev_wd9, extra_events, extra_events_hidden, extra_events_out, fiats, hid_kind_n9, live_px, lp_total, lps_pending, n_wd_hid9, now, ob, overrides9, pendings, pos_ev_full, positions, quarantined, rate_fx, ub2, up_fresh9, x_fiat, x_ub, x_ubs, xv_krw9, xv_up_coin9, xv_up_krw9, xv_up_krw_st9, dust_ev, wdt_all,) = (_bs9["G"], _bs9["_k9"], _bs9["_nopid9"], _bs9["ask9"], _bs9["ctx"].conn, _bs9["ev_hid9"], _bs9["ev_main9"], _bs9["ev_wd9"], _bs9["extra_events"], _bs9["extra_events_hidden"], _bs9["extra_events_out"], _bs9["fiats"], _bs9["hid_kind_n9"], _bs9["live_px"], _bs9["lp_total"], _bs9["lps_pending"], _bs9["n_wd_hid9"], _bs9["ctx"].now, _bs9["ob"], _bs9["overrides9"], _bs9["pendings"], _bs9["pos_ev_full"], _bs9["positions"], _bs9["quarantined"], _bs9["rate_fx"], _bs9["ub2"], _bs9["up_fresh9"], _bs9["x_fiat"], _bs9["x_ub"], _bs9["x_ubs"], _bs9["xv_krw9"], _bs9["xv_up_coin9"], _bs9["xv_up_krw9"], _bs9["xv_up_krw_st9"], _bs9["dust_ev"], _bs9["wdt_all"],)
        outflows_out, outflows_pending, of_tot = self._outflows(
            conn, ob, live_px, G, frozenset(quarantined), dust_ev,
            exwd=[e9 for e9 in wdt_all if e9["state"] == "out" and e9["ts"] >= ask9])
        try:
            st9 = getattr(self, "_outflow_status", None) or {}
            for e9 in (x9 for _k0, _s0, _c0, evs0 in pos_ev_full for x9 in evs0):
                o9 = e9.get("of")
                if o9 and o9.get("c") == "pending":
                    salelink.relabel(o9, st9.get(o9.get("a")), CHAIN_NAME.get(o9.get("ch"), o9.get("ch")))
            for e9 in extra_events + ev_main9 + ev_wd9 + ev_hid9:
                o9 = e9.get("of")
                if o9 and o9.get("c") == "pending":
                    salelink.relabel(o9, st9.get(o9.get("a")), CHAIN_NAME.get(o9.get("ch"), o9.get("ch")))
            spam9 = {id(e9) for e9 in ev_main9 + ev_wd9
                     if (e9.get("of") or {}).get("c") == "spam" and overrides9.get(f"g{e9.get('_gid')}") != "visible"}
            if spam9:
                why9s = "사칭·스팸 로그 — 보낸 내역이 주소 오염 가짜 전송으로 정함(실제로 나간 돈 아님)"
                mv9 = [dict(e9, hide=why9s, hideKind="scam") for e9 in ev_main9 + ev_wd9 if id(e9) in spam9]
                n_wd_hid9 += sum(1 for e9 in ev_wd9 if id(e9) in spam9)
                ev_main9 = [e9 for e9 in ev_main9 if id(e9) not in spam9]
                ev_wd9 = [e9 for e9 in ev_wd9 if id(e9) not in spam9]
                ev_hid9 = ev_hid9 + mv9
                extra_events_out = [_nopid9(e9) for e9 in sorted(sorted(ev_main9, key=_k9)[-150:] + sorted(ev_wd9, key=_k9)[-150:], key=_k9)]
                extra_events_hidden = [_nopid9(e9) for e9 in sorted(ev_hid9, key=_k9)[-150:]]
                hid_kind_n9["scam"] = hid_kind_n9.get("scam", 0) + len(mv9)
            sug9 = getattr(self, "_of_sug_pid", None) or {}
            if sug9:
                for _k0, _s0, _c0, evs0 in pos_ev_full:
                    for e9 in evs0:
                        x9 = sug9.get(e9.get("_pid"))
                        if x9 and "매도" not in str(e9.get("k") or ""):
                            e9["ofc"] = dict(x9)
                for e9 in extra_events + ev_hid9:
                    x9 = sug9.get(e9.get("_pid"))
                    if x9 and "매도" not in str(e9.get("k") or ""):
                        e9["ofc"] = dict(x9)
            src_ev9 = {k0: evs0 for k0, _s0, _c0, evs0 in pos_ev_full}
            for p9 in positions:
                cp9 = p9.get("events")
                if cp9 and p9.get("key") in src_ev9:
                    _ofc_cp(cp9, src_ev9[p9["key"]][-len(cp9):])
            _ofc_cp(extra_events_out, sorted(sorted(ev_main9, key=_k9)[-150:] + sorted(ev_wd9, key=_k9)[-150:], key=_k9))
            _ofc_cp(extra_events_hidden, sorted(ev_hid9, key=_k9)[-150:])
        except Exception as e9:   # noqa: BLE001 [optional]
            calcguard.swallowed("view_b_outflows:OutflowsBuildMixin._build_outflows[st9#1]", e9)
            log.debug("세일 연결 제안 표식 실패: %s", e9)
        for p9 in pendings:
            h9 = (getattr(self, "_of_untracked_hint", None) or {}).get(acct_norm.canon(p9.get("sym")))
            if h9 and str(p9.get("key") or "").startswith(("unv:", "unkh:")):
                p9["bridgeSugg"] = {"day": h9["day"], "ex": h9["ex"], "net": h9["net"], "qty": _f(h9["qty"], 6),
                                    "bridgeUsd": _f(h9["usd"], 2), "bridges": h9["names"][:3]}
                p9["why"] = (p9.get("why") or "") + (f" · 같은 날({h9['day'][5:]}) 미추적 체인 브릿지({'·'.join(h9['names'][:3])}) 로 ${h9['usd']:,.0f} 를 보낸 뒤 "
                                                     f"{h9['net']} 네트워크로 {p9.get('sym')} {h9['qty']:,.6g} 입금 — 그 돈으로 산 코인이면 원가를 지정해 주세요(자동 연결 안 함)")

        xtra9 = {"ub": x_ub, "fiat": x_fiat, "lp": lp_total,
                 "ubs": x_ubs, "ub_tl": self._upbit_led_timeline(conn),
                 "krw_up": sum(f5["krw"] for f5 in fiats if f5["ex"] == "업비트"),
                 "krw_other": sum(f5["krw"] for f5 in fiats if f5["ex"] != "업비트"),
                 "rate": self.spot.rate or None,
                 "krw_up_tl": self._upbit_krw_timeline(conn) if up_fresh9 else None}
        xv_p9 = {}
        if xv_up_krw9 is not None:
            xv_p9["ku"] = [round(xtra9["krw_up"], 2), "carry" if xv_up_krw_st9 else "snap"]
        if "bithumb" in xv_krw9:
            xv_p9["kb"] = [round(xv_krw9["bithumb"][0], 2), "carry" if xv_krw9["bithumb"][2] else "snap"]
        if xv_up_coin9 is not None:
            xv_p9["ub"] = [{s9: round(a9[0], 12) for s9, a9 in sorted(x_ubs.items())}, "snap"]
        oth9 = [v9 for e9, v9 in xv_krw9.items() if e9 != "bithumb"]
        xv_p9["rest"] = [round(lp_total + sum(v9[0] for v9 in oth9) / rate_fx, 2),
                         "carry" if any(v9[2] and v9[0] > 0 for v9 in oth9) else "snap"]
        rt9 = {e9: int(v9[1]) for e9, v9 in sorted(xv_krw9.items()) if v9[1]}
        if ub2 and float(ub2.get("ts") or 0):
            rt9["upbit"] = int(float(ub2["ts"]))
        xv9 = {"v": XV_V, "p": xv_p9, "fx": rate_fx, "rt": rt9}
        if ((self.__dict__.get("_ub_fill_info") or {}).get("krw_tl") or (self.__dict__.get("_ub_fill_info") or {}).get("krw_st")
                or (self.__dict__.get("_ub_fill_info") or {}).get("ufx")):
            xv9["ufk"] = 1
        if (self.__dict__.get("_ub_fill_info") or {}).get("ufc"):
            xv9["ufc"] = dict(self._ub_fill_info["ufc"])
        if (self.__dict__.get("_ub_fill_info") or {}).get("ufz"):
            xv9["ufz"] = {s9: dict(z9) for s9, z9 in self._ub_fill_info["ufz"].items()}
        if x_ubs and xv_up_coin9 is not None:
            xv9["ubv"] = {s9: round(a9[1], 2) for s9, a9 in sorted(x_ubs.items())}
        if not self.spot.rate:
            xv9["fxd"] = 1
        elif _rate_state(self.spot, now) == "stale":
            xv9["fxs"] = 1
        if lps_pending:
            xv9["lpp"] = len(lps_pending)
        xtra9["xv"] = xv9
        try:
            xtra9["xsrc"] = self._x_src(conn, ub2, xv_krw9, x_ubs if xv_up_coin9 is not None else None, lp_total, rate_fx, now)
        except Exception as e9:   # noqa: BLE001 [optional]
            calcguard.swallowed("view_b_outflows:OutflowsBuildMixin._build_outflows[st9#2]", e9)
            log.warning("원장 밖 금액 규칙 재료 실패(지난날 = 지금 값 이월): %s", e9)
        self._ph("outflows")
        _bs9.update((k9, v9) for k9, v9 in locals().items() if k9 != "_bs9")
