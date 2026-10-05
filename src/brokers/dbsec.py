"""DB Securities holdings adapter (read-only, UNVERIFIED)."""
from __future__ import annotations

import urllib.parse

from .base import Adapter as _Base, BrokerError, fnum, ERR_BODY


class Adapter(_Base):
    KEY = "dbsec"
    NAME = "DB증권"
    DOCS = ("https://openapi.dbsec.co.kr/apiservice",)
    REQUIRED = ("app_key", "app_secret")
    OPTIONAL = ("overseas",)
    BASE = "https://openapi.dbsec.co.kr:8443"
    MAX_PAGES = 10

    def token(self):
        ck = self.token_cache_key(self.BASE, self.cfg.get("app_key"))
        t = self.cached_token(ck)
        if t:
            return t
        body = urllib.parse.urlencode({"appkey": self.cfg["app_key"], "appsecretkey": self.cfg["app_secret"], "grant_type": "client_credentials", "scope": "oob"})
        j, _ = self.req("POST", self.BASE + "/oauth2/token", {"Content-Type": "application/x-www-form-urlencoded"}, body)
        tok = j.get("access_token")
        if not tok:
            raise BrokerError("토큰 응답에 access_token 없음")
        self.keep_token(ck, tok, fnum(j.get("expires_in")) or 3600)
        return tok

    def call(self, path, body, list_key):
        rows, last, cont, key = [], {}, "N", ""
        for _ in range(self.MAX_PAGES):
            j, rh = self.req("POST", self.BASE + path, {"Content-Type": "application/json; charset=utf-8", "authorization": "Bearer " + self.token(),
                                                       "cont_yn": cont, "cont_key": key, "mac_address": ""}, body)
            rc = str(j.get("rsp_cd", "00000"))
            if rc not in ("00000", "0"):
                raise BrokerError("조회 실패(%s)" % ERR_BODY)
            last = j
            rows += self.need_list(j, list_key, "보유·예수금")
            if str(rh.get("cont_yn") or "N") != "Y":
                break
            cont, key = "Y", str(rh.get("cont_key") or "")
        else:
            self.incomplete()
        return rows, last

    @staticmethod
    def code(c):
        c = str(c or "").strip()
        return c[1:] if len(c) == 7 and c[:1].isalpha() and c[1:2].isdigit() else c

    def fetch(self):
        pos, cash = [], []
        rows, _ = self.call("/api/v1/trading/kr-stock/inquiry/balance", {"In": {"QryTpCode0": "0"}}, "Out1")
        for r in rows:
            q = fnum(r.get("BalQty0")) if r.get("BalQty0") is not None else fnum(r.get("BalQty"))
            if q and q > 0:
                pos.append({"sym": self.code(r.get("IsuNo")), "name": str(r.get("IsuNm") or "").strip(), "qty": q,
                            "avg": fnum(r.get("BookUprc")), "px": fnum(r.get("NowPrc")), "cur": "KRW"})
        rows, _ = self.call("/api/v1/trading/kr-stock/inquiry/acnt-deposit", {"In": {}}, "Out1")
        if rows:
            a = fnum(rows[0].get("DpsBalAmt"))
            if a is not None:
                cash.append({"cur": "KRW", "amount": a})
        if self.cfg.get("overseas") is True:
            rows, _ = self.call("/api/v1/trading/overseas-stock/inquiry/balance-margin",
                                {"In": {"TrxTpCode": "2", "CmsnTpCode": "2", "WonFcurrTpCode": "2", "DpntBalTpCode": "0"}}, "Out2")
            for r in rows:
                q = fnum(r.get("AstkExecBaseQty"))
                if q and q > 0:
                    pos.append({"sym": str(r.get("SymCode") or "").strip(), "name": str(r.get("AstkHanglIsuNm") or "").strip(), "qty": q,
                                "avg": fnum(r.get("AstkAvrPchsPrc")), "px": fnum(r.get("AstkNowPrc")), "cur": str(r.get("CrcyCode") or "USD").upper()})
        return {"positions": pos, "cash": cash, "acct": self.cfg.get("app_key")}
