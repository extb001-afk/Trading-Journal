"""Kiwoom Securities REST holdings adapter (read-only, UNVERIFIED)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .base import Adapter as _Base, BrokerError, fnum, ERR_BODY

KST = timezone(timedelta(hours=9))


class Adapter(_Base):
    KEY = "kiwoom"
    NAME = "키움증권"
    DOCS = ("https://openapi.kiwoom.com/guide/apiguide?jobTpCode=08",)
    REQUIRED = ("app_key", "secret_key")
    OPTIONAL = ("mock", "us")
    MAX_PAGES = 10

    def base(self):
        return "https://mockapi.kiwoom.com" if self.cfg.get("mock") is True else "https://api.kiwoom.com"

    def token(self):
        ck = self.token_cache_key(self.base(), self.cfg.get("app_key"))
        t = self.cached_token(ck)
        if t:
            return t
        j, _ = self.req("POST", self.base() + "/oauth2/token", {"Content-Type": "application/json;charset=UTF-8"},
                        {"grant_type": "client_credentials", "appkey": self.cfg["app_key"], "secretkey": self.cfg["secret_key"]})
        tok = j.get("token")
        if not tok:
            raise BrokerError("토큰 발급 실패(%s)" % ERR_BODY)
        ttl = 3600.0
        try:
            ttl = datetime.strptime(str(j.get("expires_dt")), "%Y%m%d%H%M%S").replace(tzinfo=KST).timestamp() - self.now()
        except ValueError:
            pass
        self.keep_token(ck, tok, ttl)
        return tok

    def call(self, path, api_id, body, list_key=None):
        rows, cont, nxt, last = [], "N", "", {}
        for _ in range(self.MAX_PAGES):
            j, rh = self.req("POST", self.base() + path, {"Content-Type": "application/json;charset=UTF-8", "authorization": "Bearer " + self.token(),
                                                         "api-id": api_id, "cont-yn": cont, "next-key": nxt}, dict(body))
            if str(j.get("return_code", "0")) not in ("0", "00"):
                raise BrokerError("조회 실패(%s)" % ERR_BODY)
            last = j
            if list_key:
                rows += self.need_list(j, list_key, "보유")
            if str(rh.get("cont-yn") or "N") != "Y" or not list_key:
                break
            cont, nxt = "Y", str(rh.get("next-key") or "")
        else:
            self.incomplete()
        return rows, last

    @staticmethod
    def code(c):
        c = str(c or "").strip()
        return c[1:] if len(c) == 7 and c[:1].isalpha() and c[1:2].isdigit() else c

    def fetch(self):
        pos, cash = [], []
        rows, _ = self.call("/api/dostk/acnt", "kt00018", {"qry_tp": "1", "dmst_stex_tp": "KRX"}, "acnt_evlt_remn_indv_tot")
        for r in rows:
            q = fnum(r.get("rmnd_qty"))
            if q and q > 0:
                pos.append({"sym": self.code(r.get("stk_cd")), "name": str(r.get("stk_nm") or "").strip(), "qty": q,
                            "avg": fnum(r.get("pur_pric")), "px": abs(fnum(r.get("cur_prc")) or 0) or None, "cur": "KRW"})
        _, dj = self.call("/api/dostk/acnt", "kt00001", {"qry_tp": "3"})
        if "entr" not in dj:
            raise BrokerError("증권사 응답에 예수금(entr) 값이 없어요 — 기존 항목 유지")
        e = fnum(dj.get("entr"))
        if e is not None:
            cash.append({"cur": "KRW", "amount": e})
        if self.cfg.get("us") is True:
            seen = set()
            for ex in ("ND", "NY", "NA"):
                rows, _ = self.call("/api/us/acnt", "ust21070", {"stex_tp": ex, "stk_cd": ""}, "result_list")
                for r in rows:
                    s = str(r.get("stk_cd") or "").strip()
                    q = fnum(r.get("poss_qty"))
                    if s and s not in seen and q and q > 0:
                        seen.add(s)
                        pos.append({"sym": s, "name": r.get("frgn_stk_nm") or s, "qty": q, "avg": fnum(r.get("frgn_stk_book_uv")),
                                    "px": fnum(r.get("now_pric")), "cur": str(r.get("crnc_code") or "USD").upper()})
        return {"positions": pos, "cash": cash, "acct": self.cfg.get("app_key")}
