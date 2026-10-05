"""Toss Securities holdings adapter (read-only, UNVERIFIED)."""
from __future__ import annotations

import urllib.parse

from .base import Adapter as _Base, BrokerError, fnum


class Adapter(_Base):
    KEY = "toss"
    NAME = "토스증권"
    DOCS = ("https://developers.tossinvest.com/docs", "https://openapi.tossinvest.com/openapi-docs/latest/openapi.json")
    REQUIRED = ("client_id", "client_secret")
    OPTIONAL = ("account_seq", "cash")
    BASE = "https://openapi.tossinvest.com"

    def token(self):
        ck = self.token_cache_key(self.BASE, self.cfg.get("client_id"))
        t = self.cached_token(ck)
        if t:
            return t
        body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": self.cfg["client_id"], "client_secret": self.cfg["client_secret"]})
        j, _ = self.req("POST", self.BASE + "/oauth2/token", {"Content-Type": "application/x-www-form-urlencoded"}, body)
        tok = j.get("access_token")
        if not tok:
            raise BrokerError("토큰 응답에 access_token 없음")
        self.keep_token(ck, tok, fnum(j.get("expires_in")) or 1800)
        return tok

    def get(self, path, extra=None):
        h = {"Authorization": "Bearer " + self.token()}
        h.update(extra or {})
        j, _ = self.req("GET", self.BASE + path, h)
        return j.get("result") if isinstance(j, dict) else None

    def fetch(self):
        seq = str(self.cfg.get("account_seq") or "").strip()
        if not seq:
            accts = self.get("/api/v1/accounts") or []
            acc = next((a for a in accts if isinstance(a, dict) and str(a.get("accountType") or "BROKERAGE") == "BROKERAGE"), None)
            if not acc or acc.get("accountSeq") in (None, ""):
                raise BrokerError("계좌를 찾지 못했어요")
            seq = str(acc["accountSeq"])
        res = self.need(self.get("/api/v1/holdings", {"X-Tossinvest-Account": seq}), dict, "보유")
        pos, cash = [], []
        for r in self.need_list(res, "items", "보유"):
            if not isinstance(r, dict):
                continue
            q = fnum(r.get("quantity"))
            s = str(r.get("symbol") or "").strip()
            if str(r.get("marketCountry") or "") == "KR" and len(s) > 6:
                s = s[-6:]
            if q and q > 0 and s:
                pos.append({"sym": s, "name": str(r.get("name") or "").strip(), "qty": q, "avg": fnum(r.get("averagePurchasePrice")),
                            "px": fnum(r.get("lastPrice")), "cur": str(r.get("currency") or "").upper()})
        if self.cfg.get("cash") is True:
            for cur in ("KRW", "USD"):
                bp = self.get("/api/v1/buying-power?currency=" + cur, {"X-Tossinvest-Account": seq}) or {}
                a = fnum(bp.get("cashBuyingPower"))
                if a is not None:
                    cash.append({"cur": cur, "amount": a})
        return {"positions": pos, "cash": cash, "acct": seq}
