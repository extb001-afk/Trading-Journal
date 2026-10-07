"""Wallet registration helpers."""
from __future__ import annotations

import json
import os
import time

import common
import settings_store as ss

MANUAL = "pm2 restart tj-evm tj-sol tj-bsc tj-core tj-web"
RELOAD_PATH = os.path.join(common.STATE_DIR, "wallet_reload.json")
RELOAD_DONE_PATH = os.path.join(common.STATE_DIR, "wallet_reload_done.json")
RELOAD_UNITS = ("tj-evm", "tj-sol", "tj-bsc", "tj-core", "tj-web")


def req_fp(entry: dict) -> str:
    import hashlib
    return hashlib.sha1(json.dumps(entry, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]


def _read_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, type(default)) else default
    except (OSError, ValueError):
        return default


def pending_requests() -> list:
    cur = _read_json(RELOAD_PATH, {})
    done = _read_json(RELOAD_DONE_PATH, {})
    seen = set(x for x in (done.get("fps") or []) if isinstance(x, str))
    floor = float(done.get("floor") or 0) if isinstance(done.get("floor"), (int, float)) else 0.0
    out = []
    for e in cur.get("requests") or []:
        if not isinstance(e, dict):
            continue
        try:
            ts = float(e.get("ts") or 0)
        except (TypeError, ValueError):
            continue
        fp = req_fp(e)
        if fp in seen or ts < floor:
            continue
        out.append((fp, e))
    out.sort(key=lambda x: float(x[1].get("ts") or 0))
    return out


def _addr_norm(a) -> str:
    a = str(a or "")
    return a.lower() if a.startswith("0x") else a


def pending_addrs() -> set:
    out = set()
    for _fp, e in pending_requests():
        for a in [e.get("address")] + list(e.get("addresses") or []):
            if a:
                out.add(_addr_norm(a))
    return out


def auto_reload_alive() -> bool:
    try:
        return any(isinstance(h, dict) and h.get("by") == "reload" for h in ss.runner_status().values())
    except Exception:
        return False


def _units_for(kind: str, chains: list) -> list:
    u = set()
    if kind == "sol":
        u.add("tj-sol")
    for c in chains or []:
        u.add("tj-bsc" if c == "bsc" else ("tj-sol" if c == "sol" else "tj-evm"))
    return sorted(u | {"tj-core", "tj-web"})


def apply_info(units=None) -> dict:
    try:
        rs = ss.runner_status()
        runner = bool(rs)
        mode = "reload" if rs and all(isinstance(h, dict) and h.get("by") == "reload" for h in rs.values()) else ("runner" if rs else "")
    except Exception:
        runner, mode = False, ""
    return {"runner": runner, "mode": mode, "manual": MANUAL, "units": list(units or [])}


def _record_reload(entry: dict) -> None:
    try:
        with ss.LOCK:
            try:
                with open(RELOAD_PATH, "r", encoding="utf-8") as f:
                    cur = json.load(f)
            except (OSError, ValueError):
                cur = {}
            reqs = [x for x in (cur.get("requests") or []) if isinstance(x, dict)][-19:] if isinstance(cur, dict) else []
            reqs.append(entry)
            common.atomic_write_json(RELOAD_PATH, {"version": 1, "requests": reqs})
    except Exception:
        pass


def register_wallets(addresses, chains: list, source: str = "") -> dict:
    res = ss.add_wallets(addresses, list(chains or []) if isinstance(chains, list) else chains)
    ok = [r for r in res if r.get("status") == "added"]
    units = set()
    for r in ok:
        units |= set(_units_for(r.get("kind"), r.get("chains")))
    if ok:
        _record_reload({"ts": int(time.time()), "address": ok[0].get("address"), "addresses": [r.get("address") for r in ok],
                        "chains": sorted({c for r in ok for c in r.get("chains") or []}), "source": source or "",
                        "units": sorted(units)})
    return {"results": res, "added": len(ok), "apply": apply_info(sorted(units))}


def register_wallet(address: str, chains: list, alias: str, source: str = "", idempotent: bool = False) -> dict:
    try:
        r = ss.add_wallet(address, alias, list(chains or []))
    except ValueError as e:
        if idempotent and "이미 같은 체인으로 등록된" in str(e):
            kind, addr, _note = ss.validate_address(address)
            return {"kind": kind, "address": addr, "chains": [], "note": "이미 등록된 주소·체인",
                    "apply": apply_info()}
        raise
    units = _units_for(r.get("kind"), r.get("chains"))
    _record_reload({"ts": int(time.time()), "address": r.get("address"), "chains": r.get("chains") or [],
                    "source": source or "", "units": units})
    r = dict(r)
    r["apply"] = apply_info(units)
    return r
