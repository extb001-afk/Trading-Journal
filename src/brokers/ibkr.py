"""Interactive Brokers Client Portal positions adapter (read-only, UNVERIFIED)."""
from __future__ import annotations

import urllib.parse

from .base import Adapter as _Base, BrokerError, fnum


class Adapter(_Base):
    KEY = "ibkr"
    NAME = "Interactive Brokers"
    DOCS = ("https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/",)
    REQUIRED = ()
    OPTIONAL = ("gateway_url", "account_id")
    MAX_PAGES = 10

    def base(self):
        u = str(self.cfg.get("gateway_url") or "https://localhost:5000/v1/api").rstrip("/")
        h = urllib.parse.urlsplit(u).hostname
        if h not in ("localhost", "127.0.0.1"):
            raise BrokerError("gateway_url 은 이 기기(localhost) 게이트웨이만")
        return u

    def get(self, path, method="GET"):
        j, _ = self.req(method, self.base() + path, {}, None, verify=False)
        return j

    def fetch(self):
        st = self.get("/iserver/auth/status", "POST") or {}
        if st.get("authenticated") is not True:
            raise BrokerError("게이트웨이 로그인 필요(브라우저로 https://localhost:5000 로그인)")
        accts = self.get("/portfolio/accounts") or []
        aid = str(self.cfg.get("account_id") or "").strip()
        if not aid:
            a0 = next((a for a in accts if isinstance(a, dict)), None)
            aid = str((a0 or {}).get("accountId") or (a0 or {}).get("id") or "")
        if not aid or not aid.replace("-", "").isalnum():
            raise BrokerError("계좌를 찾지 못했어요")
        pos = []
        for page in range(self.MAX_PAGES):
            rows = self.need(self.get("/portfolio/%s/positions/%d" % (urllib.parse.quote(aid, safe=""), page)), list, "보유 목록")
            for r in rows:
                if not isinstance(r, dict) or str(r.get("assetClass") or "STK") != "STK":
                    continue
                q = fnum(r.get("position"))
                s = str(r.get("ticker") or r.get("contractDesc") or "").strip().split(" ")[0]
                if q and q > 0 and s:
                    pos.append({"sym": s, "name": str(r.get("name") or s), "qty": q, "avg": fnum(r.get("avgPrice")),
                                "px": fnum(r.get("mktPrice")), "cur": str(r.get("currency") or "USD").upper()})
            if len(rows) < 100:
                break
        else:
            self.incomplete()
        cash = []
        led = self.need(self.get("/portfolio/%s/ledger" % urllib.parse.quote(aid, safe="")), dict, "원장")
        for k, v in (led.items() if isinstance(led, dict) else []):
            if k == "BASE" or not isinstance(v, dict):
                continue
            a = fnum(v.get("cashbalance"))
            if a is not None and str(v.get("currency") or k).upper() in ("USD", "KRW"):
                cash.append({"cur": str(v.get("currency") or k).upper(), "amount": a})
        return {"positions": pos, "cash": cash, "acct": aid}
