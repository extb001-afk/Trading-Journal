"""Alpaca positions adapter (read-only, UNVERIFIED)."""
from __future__ import annotations

from .base import Adapter as _Base, fnum


class Adapter(_Base):
    KEY = "alpaca"
    NAME = "Alpaca"
    DOCS = ("https://docs.alpaca.markets/reference/getallopenpositions", "https://docs.alpaca.markets/reference/getaccount-1")
    REQUIRED = ("key_id", "secret_key")
    OPTIONAL = ("paper",)

    def base(self):
        return "https://paper-api.alpaca.markets" if self.cfg.get("paper") is True else "https://api.alpaca.markets"

    def hd(self):
        return {"APCA-API-KEY-ID": self.cfg["key_id"], "APCA-API-SECRET-KEY": self.cfg["secret_key"]}

    def fetch(self):
        rows, _ = self.req("GET", self.base() + "/v2/positions", self.hd())
        pos = []
        for r in self.need(rows, list, "보유 목록"):
            if not isinstance(r, dict) or str(r.get("side") or "long") != "long" or str(r.get("asset_class") or "us_equity") != "us_equity":
                continue
            q = fnum(r.get("qty"))
            if q and q > 0:
                pos.append({"sym": str(r.get("symbol") or "").strip(), "name": str(r.get("symbol") or ""), "qty": q,
                            "avg": fnum(r.get("avg_entry_price")), "px": fnum(r.get("current_price")), "cur": "USD"})
        acc, _ = self.req("GET", self.base() + "/v2/account", self.hd())
        self.need(acc, dict, "계좌")
        cash = []
        c = fnum((acc or {}).get("cash"))
        if c is not None:
            cash.append({"cur": str((acc or {}).get("currency") or "USD").upper(), "amount": c})
        return {"positions": pos, "cash": cash, "acct": (acc or {}).get("account_number") or self.cfg.get("key_id")}
