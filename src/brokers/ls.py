"""LS Securities holdings adapter (read-only, UNVERIFIED)."""
from __future__ import annotations

import urllib.parse
from datetime import datetime, timedelta, timezone

from .base import Adapter as _Base, BrokerError, fnum, ERR_BODY

KST = timezone(timedelta(hours=9))


class Adapter(_Base):
    KEY = "ls"
    NAME = "LS증권"
    DOCS = ("https://openapi.ls-sec.co.kr/apiservice",)
    REQUIRED = ("app_key", "app_secret")
    OPTIONAL = ("overseas",)
    BASE = "https://openapi.ls-sec.co.kr:8080"
    MAX_PAGES = 10

    def token(self):
        ck = self.token_cache_key(self.BASE, self.cfg.get("app_key"))
        t = self.cached_token(ck)
        if t:
            return t
        body = urllib.parse.urlencode({"grant_type": "client_credentials", "appkey": self.cfg["app_key"], "appsecretkey": self.cfg["app_secret"], "scope": "oob"})
        j, _ = self.req("POST", self.BASE + "/oauth2/token", {"Content-Type": "application/x-www-form-urlencoded"}, body)
        tok = j.get("access_token")
        if not tok:
            raise BrokerError("토큰 응답에 access_token 없음")
        self.keep_token(ck, tok, fnum(j.get("expires_in") or j.get("expire_in")) or 3600)
        return tok

    def call(self, path, tr, body, cont="N", key=""):
        return self.req("POST", self.BASE + path, {"Content-Type": "application/json; charset=utf-8", "authorization": "Bearer " + self.token(),
                                                   "tr_cd": tr, "tr_cont": cont, "tr_cont_key": key, "mac_address": ""}, body)

    def fetch(self):
        pos, cash, cts, cont = [], [], "", "N"
        head = {}
        for _ in range(self.MAX_PAGES):
            j, _rh = self.call("/stock/accno", "t0424", {"t0424InBlock": {"prcgb": "1", "chegb": "2", "dangb": "0", "charge": "1", "cts_expcode": cts}}, cont)
            if str(j.get("rsp_cd", "00000")) not in ("00000", "00136", "0"):
                raise BrokerError("조회 실패(%s)" % ERR_BODY)
            head = self.need(j.get("t0424OutBlock"), dict, "잔고 요약(t0424OutBlock)")
            for r in self.need_list(j, "t0424OutBlock1", "보유"):
                q = fnum(r.get("janqty"))
                if q and q > 0:
                    pos.append({"sym": str(r.get("expcode") or "").strip(), "name": str(r.get("hname") or "").strip(), "qty": q,
                                "avg": fnum(r.get("pamt")), "px": fnum(r.get("price")), "cur": "KRW"})
            cts = str(head.get("cts_expcode") or "").strip()
            if not cts:
                break
            cont = "Y"
        else:
            self.incomplete()
        c = fnum((head or {}).get("sunamt1"))
        if c is not None:
            cash.append({"cur": "KRW", "amount": c})
        if self.cfg.get("overseas") is True:
            today = datetime.fromtimestamp(self.now(), KST).strftime("%Y%m%d")
            j, _ = self.call("/overseas-stock/accno", "COSOQ00201",
                             {"COSOQ00201InBlock1": {"RecCnt": 1, "BaseDt": today, "CrcyCode": "ALL", "AstkBalTpCode": "00"}})
            for r in self.need_list(j, "COSOQ00201OutBlock4", "해외 보유"):
                q = fnum(r.get("AstkBalQty"))
                if q and q > 0:
                    pos.append({"sym": str(r.get("ShtnIsuNo") or "").strip(), "name": str(r.get("JpnMktHanglIsuNm") or "").strip(), "qty": q,
                                "avg": fnum(r.get("FcstckUprc")), "px": fnum(r.get("OvrsScrtsCurpri")), "cur": str(r.get("CrcyCode") or "USD").upper()})
            for r in self.need_list(j, "COSOQ00201OutBlock3", "외화 예수금"):
                a = fnum(r.get("FcurrDps"))
                if a is not None and str(r.get("CrcyCode") or "").upper() == "USD":
                    cash.append({"cur": "USD", "amount": a})
        return {"positions": pos, "cash": cash, "acct": self.cfg.get("app_key")}
