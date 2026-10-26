"""Read-only broker adapters (UNVERIFIED: written from public docs only)."""
from __future__ import annotations

import hashlib
import time
from typing import Callable

from .base import UNVERIFIED, Adapter, BrokerError, TokenRejected, redact
from . import kis, kiwoom, ls, alpaca, ibkr, schwab, toss, dbsec

ADAPTERS = {m.Adapter.KEY: m.Adapter for m in (kis, kiwoom, ls, dbsec, toss, alpaca, ibkr, schwab)}
_ACK_HOW = "config.json 에 \"other_assets\": {\"brokers\": {\"experimental_ack\": true}} 를 넣고 tj-web 다시 시작"
ACK_TXT = {"gate": "실험 확인 필요 — 동기화 안 함 · " + _ACK_HOW,
           "noack": "실험 확인 없음(전부터 켜 둔 연결이라 계속 동기화) — 확인하려면 " + _ACK_HOW}


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
        try:
            ad = A(cfg, http=http, now=now)
            r = ad.fetch()
        except TokenRejected:
            ad = A(cfg, http=http, now=now)
            r = ad.fetch()
        t = Adapter._tokens.get(ad._ck) if ad._ck else None
        if t:
            Adapter._tokens[ad._ck] = (t[0], t[1], True)
    except BrokerError as e:
        toks = [t[0] for t in list(Adapter._tokens.values()) if isinstance(t, tuple) and t and isinstance(t[0], str)]
        return {"ok": False, "at": at, "err": redact(str(e), {"cfg": cfg, "tok": toks})}
    except Exception as e:   # noqa: BLE001 [fallback]
        return {"ok": False, "at": at, "err": "응답 해석 실패(%s) — 문서와 실제가 다를 수 있어요(미검증)" % type(e).__name__}
    pos = [p for p in (r.get("positions") or []) if isinstance(p, dict)]
    cash = [c for c in (r.get("cash") or []) if isinstance(c, dict)]
    acct = hashlib.sha256(("%s|%s" % (key, r.get("acct") or cfg.get("account") or "")).encode()).hexdigest()[:16]
    return {"ok": True, "at": at, "n": len(pos), "positions": pos, "cash": cash, "acct": acct}


def gate(oa: dict | None, bcfg: dict | None, bst: dict | None, load: Callable) -> tuple:
    b = oa.get("brokers") if isinstance(oa, dict) else None
    if isinstance(b, dict) and b.get("experimental_ack") is True:
        return True, frozenset()
    on = [k for k, v in (bcfg or {}).items() if k in ADAPTERS and isinstance(v, dict) and v.get("enabled") is True]
    seen = {k for k, v in (bst or {}).items() if isinstance(v, dict) and "at" in v}
    if not seen.issuperset(on):
        try:
            d = load()
        except Exception:   # noqa: BLE001 [fallback]
            return False, frozenset()
        sb = d.get("bst") if isinstance(d, dict) else None
        seen.update(k for k in (sb if isinstance(sb, dict) else {}) if isinstance(k, str))
        seen.update(x.get("broker") for x in ((d.get("items") if isinstance(d, dict) else None) or []) if isinstance(x, dict) and x.get("broker"))
    return False, frozenset(k for k in on if k not in seen)


def broker_list(bcfg: dict, bst: dict) -> list:
    out = []
    for key, A in ADAPTERS.items():
        c = (bcfg or {}).get(key) if isinstance((bcfg or {}).get(key), dict) else {}
        st = (bst or {}).get(key) or {}
        out.append({"key": key, "name": A.NAME, "enabled": c.get("enabled") is True,
                    "configured": all(str(c.get(f) or "").strip() for f in A.REQUIRED),
                    "fields": list(A.REQUIRED) + list(A.OPTIONAL), "docs": A.DOCS[0] if A.DOCS else "",
                    "verified": False, "note": UNVERIFIED,
                    "status": {k: st.get(k) for k in ("at", "ok", "n", "err", "gate", "noack") if k in st},
                    "ack": ACK_TXT["gate"] if st.get("gate") else ACK_TXT["noack"] if st.get("noack") else ""})
    return out
