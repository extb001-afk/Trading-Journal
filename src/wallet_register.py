"""Wallet registration helpers."""
from __future__ import annotations

import json
import os
import time

import common
import settings_store as ss

MANUAL = "pm2 restart tj-evm tj-sol tj-bsc tj-core tj-web"
RELOAD_PATH = os.path.join(common.STATE_DIR, "wallet_reload.json")


def _units_for(kind: str, chains: list) -> list:
    u = set()
    if kind == "sol":
        u.add("tj-sol")
    for c in chains or []:
        u.add("tj-bsc" if c == "bsc" else ("tj-sol" if c == "sol" else "tj-evm"))
    return sorted(u | {"tj-core", "tj-web"})


def apply_info(units=None) -> dict:
    try:
        runner = bool(ss.runner_status())
    except Exception:
        runner = False
    return {"runner": runner, "manual": MANUAL, "units": list(units or [])}


def _record_reload(entry: dict) -> None:
    try:
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
