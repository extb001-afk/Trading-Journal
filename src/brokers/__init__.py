"""Read-only broker adapters (UNVERIFIED: written from public docs only)."""
from __future__ import annotations

import hashlib
import time

from .base import UNVERIFIED, Adapter, BrokerError, redact
from . import kis, kiwoom, ls, alpaca, ibkr, schwab, toss, dbsec

ADAPTERS = {m.Adapter.KEY: m.Adapter for m in (kis, kiwoom, ls, dbsec, toss, alpaca, ibkr, schwab)}


def run_sync(key: str, cfg: dict, http=None, now=None) -> dict:
    now_f = now or time.time
    at = int(now_f())
    A = ADAPTERS.get(key)
    if A is None:
        return {"ok": False, "at": at, "err": "모르는 증권사"}
    miss = [f for f in A.REQUIRED if not str((cfg or {}).get(f) or "").strip()]
    if miss:
        return {"ok": False, "at": at, "err": "설정 빠짐: " + ", ".join(miss)}
    try:
        r = A(cfg, http=http, now=now).fetch()
    except BrokerError as e:
        toks = [t[0] for t in list(Adapter._tokens.values()) if isinstance(t, tuple) and t and isinstance(t[0], str)]
        return {"ok": False, "at": at, "err": redact(str(e), {"cfg": cfg, "tok": toks})}
    except Exception as e:
        return {"ok": False, "at": at, "err": "응답 해석 실패(%s) — 문서와 실제가 다를 수 있어요(미검증)" % type(e).__name__}
    pos = [p for p in (r.get("positions") or []) if isinstance(p, dict)]
    cash = [c for c in (r.get("cash") or []) if isinstance(c, dict)]
    acct = hashlib.sha256(("%s|%s" % (key, r.get("acct") or cfg.get("account") or "")).encode()).hexdigest()[:16]
    return {"ok": True, "at": at, "n": len(pos), "positions": pos, "cash": cash, "acct": acct}


def broker_list(bcfg: dict, bst: dict) -> list:
    out = []
    for key, A in ADAPTERS.items():
        c = (bcfg or {}).get(key) if isinstance((bcfg or {}).get(key), dict) else {}
        st = (bst or {}).get(key) or {}
        out.append({"key": key, "name": A.NAME, "enabled": c.get("enabled") is True,
                    "configured": all(str(c.get(f) or "").strip() for f in A.REQUIRED),
                    "fields": list(A.REQUIRED) + list(A.OPTIONAL), "docs": A.DOCS[0] if A.DOCS else "",
                    "verified": False, "note": UNVERIFIED,
                    "status": {k: st.get(k) for k in ("at", "ok", "n", "err") if k in st}})
    return out
