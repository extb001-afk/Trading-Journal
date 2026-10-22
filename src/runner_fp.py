from __future__ import annotations

import hashlib
import json
import os
import time

import paths
import settings_store

__all__ = ["unit_inputs", "web_restart_view", "WEB_HOT_TOP", "WEB_HOT_WALLET_FIELDS", "RUNNER_UNITS", "runner_units", "runner_status"]


def _h(v) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def unit_inputs(unit: str, cfg: dict | None = None, env: dict | None = None):
    cfg = cfg if cfg is not None else settings_store.load_config_quiet()
    env = env if env is not None else settings_store.read_env()
    genv = lambda k: os.environ.get(k) or env.get(k, "")  # noqa: E731
    ws = cfg.get("wallets") or []
    evm = sorted({(w.get("chain"), (w.get("address") or "").lower()) for w in ws if w.get("type", "evm") == "evm"})
    sol = sorted({w.get("address") for w in ws if w.get("type") == "sol"})
    bsc = sorted({(w.get("address") or "").lower() for w in ws if w.get("type") == "bsc_rpc"})
    hk = hashlib.sha256(genv("TJ_HELIUS_KEY").encode()).hexdigest()[:8] if genv("TJ_HELIUS_KEY") else ""
    ek = hashlib.sha256(genv("TJ_ETHERSCAN_KEY").encode()).hexdigest()[:8] if genv("TJ_ETHERSCAN_KEY") else ""
    try:
        import nodekeys
        nk = nodekeys.fingerprint()
    except Exception:   # noqa: BLE001 [fallback]
        nk = ""
    if unit in ("evm", "bsc"):
        try:
            import nodekeys
            qr = nodekeys.route_fp("base" if unit == "evm" else "bsc")
        except Exception:   # noqa: BLE001 [fallback]
            qr = ""
    if unit == "evm":
        used = sorted({c for c, _ in evm})
        fp = _h([evm, {c: (cfg.get("chains") or {}).get(c) for c in used}, ek, cfg.get("evm_poll_sec"), nk] + ([qr] if qr else []))
        return (bool(evm), "EVM 지갑 없음" if not evm else "", fp)
    if unit == "sol":
        need_key = (cfg.get("sol") or {}).get("rpc") == "helius"
        fp = _h([sol, cfg.get("sol"), hk])
        if not sol:
            return False, "Solana 지갑 없음", fp
        if need_key and not hk:
            return False, "Helius 키 없음(Solana 수집에 필요 — 무료 발급)", fp
        return True, "", fp
    if unit == "bsc":
        return (bool(bsc), "BSC 지갑 없음" if not bsc else "", _h([bsc, cfg.get("bsc"), nk] + ([qr] if qr else [])))
    if unit == "core":
        allw = sorted({(w.get("type", "evm"), w.get("chain"), w.get("address") if w.get("type") == "sol"
                        else (w.get("address") or "").lower()) for w in ws})
        parts = [allw, cfg.get("exchange_addresses"), hk, nk, cfg.get("backfill_months"), cfg.get("backfill_full_history")]
        try:
            import rabby
            if rabby.enabled(cfg):
                parts.append("rabby")
        except Exception:   # noqa: BLE001 [optional]
            pass
        nev = _nonevm_core_view(cfg)
        if nev:
            parts.append(nev)
            parts.append([(c9, _nonevm_chain_fp(c9, cfg, genv)) for c9 in sorted({c9 for c9, _k9 in nev})])
        return True, "", _h(parts)
    if unit in _nonevm_units():
        return _nonevm_unit_inputs(unit, cfg, genv)
    if unit == "web":
        return True, "", _h([web_restart_view(cfg), nk])
    return True, "", _h([unit])


WEB_HOT_TOP = ("perp_wallets", "runner")


WEB_HOT_WALLET_FIELDS = ("label",)


def web_restart_view(cfg: dict) -> dict:
    v = {k: x for k, x in (cfg or {}).items() if k not in WEB_HOT_TOP}
    for k in ("wallets", "_disabled_wallets"):
        if isinstance(v.get(k), list):
            v[k] = [{f: y for f, y in w.items() if f not in WEB_HOT_WALLET_FIELDS} if isinstance(w, dict) else w for w in v[k]]
    return v


RUNNER_UNITS = ("evm", "sol", "bsc", "core", "web")


def _nonevm_units() -> tuple:
    try:
        import chain_registry as reg
        return reg.CHAINS
    except Exception:   # noqa: BLE001 [fallback]
        return ()


def _nonevm_core_view(cfg: dict) -> list:
    try:
        import chain_registry as reg
        return sorted((r["chain"], r["key"]) for r in reg.wallets(cfg))
    except Exception:   # noqa: BLE001 [fallback]
        return []


def _nonevm_chain_fp(chain: str, cfg: dict, genv) -> str:
    try:
        return _nonevm_unit_inputs(chain, cfg, genv)[2]
    except Exception:   # noqa: BLE001 [fallback]
        return ""


def _nonevm_unit_inputs(unit: str, cfg: dict, genv):
    import chain_registry as reg
    sp = reg.spec(unit)
    rows = reg.wallets(cfg, unit)
    keys = sorted(r["key"] for r in rows)
    kh = hashlib.sha256(genv(sp.key_env).encode()).hexdigest()[:8] if sp.key_env and genv(sp.key_env) else ""
    parts = [keys, (cfg.get(reg.CFG_CHAIN_KEY) or {}).get(unit) if isinstance(cfg.get(reg.CFG_CHAIN_KEY), dict) else None, kh]
    hd = [r for r in rows if unit == "btc" and r["mode"] == "descriptor"]
    if hd:
        from btc_watch import MAX_INDEX
        ranges = []
        for r in hd:
            e = r["entry"]
            end = e.get("range_end")
            end = end if isinstance(end, int) and not isinstance(end, bool) and 0 <= end < MAX_INDEX else None
            ranges.append((r["key"], int(e.get("gap_limit", 20)), end))
        parts.append(sorted(ranges))
    fp = _h(parts)
    if not keys:
        return False, f"{sp.name} 지갑 없음", fp
    if not reg.available(unit):
        return False, f"{sp.name} 수집기 준비 중(이 판 미포함)", fp
    if sp.key_policy == "required" and not kh:
        return False, f"{sp.name} 키 없음", fp
    return True, "", fp


def runner_units(cfg: dict = None) -> tuple:
    try:
        import chain_registry as reg
        extra = tuple(c for c in reg.configured_chains(cfg if cfg is not None else settings_store.load_config_quiet()))
    except Exception:   # noqa: BLE001 [fallback]
        extra = ()
    return RUNNER_UNITS + extra


def runner_status(path_fmt: str | None = None) -> dict:
    out = {}
    for u in RUNNER_UNITS + _nonevm_units():
        p = paths.state(f"runner_{u}.json")
        try:
            with open(p, "r", encoding="utf-8") as f:
                hb = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(hb, dict) and time.time() - float(hb.get("ts") or 0) < 120:
            out[u] = hb
    return out
