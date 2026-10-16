from __future__ import annotations
import xfer_match

OFFC_EXCHANGES = ("binance", "bybit", "okx", "kucoin", "gate", "bithumb")

OFFC_TX_PREFIX = "off-chain transfer"


def _offc_tx(t) -> bool:
    return str(t or "").strip().lower().startswith(OFFC_TX_PREFIX)


def _offc_on(prefs) -> frozenset:
    v = prefs.get("offchain_self") if isinstance(prefs, dict) else None
    if not isinstance(v, dict):
        return frozenset()
    return frozenset(k for k, on in v.items() if k in OFFC_EXCHANGES and on is True)


def _offc_answered(prefs) -> dict:
    v = prefs.get("offchain_self") if isinstance(prefs, dict) else None
    return {k: on for k, on in v.items() if k in OFFC_EXCHANGES and isinstance(on, bool)} if isinstance(v, dict) else {}


def _offc_excl(prefs) -> dict:
    v = prefs.get("offchain_self_excl") if isinstance(prefs, dict) else None
    if not isinstance(v, dict):
        return {}
    return {k: frozenset(xfer_match.norm_addr(a) for a in lst if isinstance(a, str) and a.strip())
            for k, lst in v.items() if k in OFFC_EXCHANGES and isinstance(lst, list)}
