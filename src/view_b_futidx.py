from __future__ import annotations
import acct_norm
from datetime import timedelta
import logging
import calcguard

log = logging.getLogger('tj-web')


class FutIdxMixin:

    def _build_futidx(self, _bs9):
        (att_ok9, conn, ev_hid9, ev_main9, ev_wd9, fxb, lp_events, now, pos_ev_full, positions, realized_by_date, stab_ev, tax_rows, today_kst,) = (_bs9["att_ok9"], _bs9["ctx"].conn, _bs9["ev_hid9"], _bs9["ev_main9"], _bs9["ev_wd9"], _bs9["ctx"].fxb, _bs9["lp_events"], _bs9["ctx"].now, _bs9["pos_ev_full"], _bs9["positions"], _bs9["realized_by_date"], _bs9["stab_ev"], _bs9["tax_rows"], _bs9["ctx"].today_kst,)
        if "e9" in _bs9:
            e9 = _bs9["e9"]
        if "ex9" in _bs9:
            ex9 = _bs9["ex9"]
        if "k9" in _bs9:
            k9 = _bs9["k9"]
        if "lo9" in _bs9:
            lo9 = _bs9["lo9"]
        if "src9" in _bs9:
            src9 = _bs9["src9"]
        fut = self._futures_view(fxb)
        lo9 = (today_kst - timedelta(days=40)).strftime("%Y-%m-%d")
        review_realized = {}
        for src9 in (realized_by_date, fut.get("realizedByDate") or {}):
            for day9, pnl9 in src9.items():
                if len(day9) == 10 and day9 < lo9:
                    continue
                k9 = acct_norm.mmdd(day9)
                review_realized[k9] = review_realized.get(k9, 0) + pnl9
        self._ph("futures")
        day_ix, day_acts = self._day_index(pos_ev_full, ev_main9 + ev_wd9, ev_hid9, lp_events)
        stab_ix = self._stab_index(stab_ev, day_acts)
        try:
            krw_ix9 = self._krw_day_index(conn, day_acts)
        except Exception as e9:
            calcguard.swallowed("view_b_futidx:FutIdxMixin._build_futidx", e9)
            log.warning("그날 기록 원화 입출금 색인 실패(목록에서 빠짐): %s", e9)
            krw_ix9 = {}
        idx9 = {"builtAt": int(now), "ix": day_ix, "rbd": realized_by_date, "stab": stab_ix, "krw": krw_ix9,
                         "fut": fut.get("realizedByDate") or {},
                         "tax": tax_rows, "taxToday": today_kst,
                         "futDetail": getattr(self, "_fut_detail", None),
                         "futEv": getattr(self, "_fut_ev", None), "futStale": list(fut.get("staleExchanges") or ()),
                         "futAccts": getattr(self, "_fut_accts", None) or {},
                         "pos": positions}
        det9 = (self.__dict__.get("_att_det_new") or {}) if att_ok9 else {}
        self._att_det_new = None
        try:
            idx9["attFut"] = self._att_fut_pack(idx9.get("futEv"), det9)
        except Exception as ex9:
            calcguard.swallowed("view_b_futidx:FutIdxMixin._build_futidx", ex9)
            idx9["attFut"] = {}
            log.debug("분해 상세 선물 색인 실패: %s", type(ex9).__name__)
        idx9["attDet"] = det9
        self._att_det = det9
        self._day_idx = idx9
        acts_md9 = {acct_norm.mmdd(k9): v9 for k9, v9 in day_acts.items() if k9 >= lo9}
        self._ph("day_index")
        _bs9.update((k9, v9) for k9, v9 in locals().items() if k9 != "_bs9")
