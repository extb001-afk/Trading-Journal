"""Charles Schwab Trader API positions adapter (read-only, UNVERIFIED)."""
from __future__ import annotations

import base64
import urllib.parse

from .base import Adapter as _Base, BrokerError, fnum


class Adapter(_Base):
    KEY = "schwab"
    NAME = "Charles Schwab"
    DOCS = ("https://developer.schwab.com/products/trader-api--individual",)
    REQUIRED = ("app_key", "app_secret", "refresh_token")
    OPTIONAL = ()
    BASE = "https://api.schwabapi.com"

    def token(self):
        ck = self.token_cache_key(self.BASE, self.cfg.get("app_key"), self.cfg.get("refresh_token"))
        t = self.cached_token(ck)
        if t:
            return t
        basic = base64.b64encode(("%s:%s" % (self.cfg["app_key"], self.cfg["app_secret"])).encode()).decode()
        body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": self.cfg["refresh_token"]})
        j, _ = self.req("POST", self.BASE + "/v1/oauth/token", {"Authorization": "Basic " + basic, "Content-Type": "application/x-www-form-urlencoded"}, body)
        tok = j.get("access_token")
        if not tok:
            raise BrokerError("토큰 갱신 실패 — refresh_token 만료(7일)면 다시 승인")
        self.keep_token(ck, tok, fnum(j.get("expires_in")) or 1800)
        return tok

    def fetch(self):
        rows, _ = self.req("GET", self.BASE + "/trader/v1/accounts?fields=positions", {"Authorization": "Bearer " + self.token()})
        pos, cash, acct = [], [], ""
        for a in self.need(rows, list, "계좌 목록"):
            sa = (a or {}).get("securitiesAccount") if isinstance(a, dict) else None
            if not isinstance(sa, dict):
                continue
            acct = acct or str(sa.get("accountNumber") or "")
            for p in self.need_list(sa, "positions", "보유"):
                ins = p.get("instrument") or {}
                if str(ins.get("assetType") or "") not in ("EQUITY", "COLLECTIVE_INVESTMENT", "ETF"):
                    continue
                q = (fnum(p.get("longQuantity")) or 0) - (fnum(p.get("shortQuantity")) or 0)
                if q > 0:
                    mv = fnum(p.get("marketValue"))
                    pos.append({"sym": str(ins.get("symbol") or "").strip(), "name": str(ins.get("description") or ins.get("symbol") or ""), "qty": q,
                                "avg": fnum(p.get("averagePrice")), "px": (mv / q) if mv else None, "cur": "USD"})
            c = fnum((sa.get("currentBalances") or {}).get("cashBalance"))
            if c is not None:
                cash.append({"cur": "USD", "amount": c})
        return {"positions": pos, "cash": cash, "acct": acct}
