"""Wallet registration helpers."""
from __future__ import annotations

import json
import time

import paths, statefile
import settings_store as ss, address_codec, runner_fp, settings_wallets
import bf_engine, chaincatalog, token_tables
import evm_rpcw

MANUAL = "pm2 restart tj-evm tj-sol tj-bsc tj-core tj-web"
RELOAD_UNITS = ("tj-evm", "tj-sol", "tj-bsc", "tj-core", "tj-web")
try:
    import chain_registry as _reg
    RELOAD_UNITS = RELOAD_UNITS + tuple(_reg.SPECS[c].unit for c in _reg.CHAINS)
except Exception:   # noqa: BLE001 [optional]
    pass


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
    cur = _read_json(paths.state("wallet_reload.json"), {})
    done = _read_json(paths.state("wallet_reload_done.json"), {})
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
        return any(isinstance(h, dict) and h.get("by") == "reload" for h in runner_fp.runner_status().values())
    except Exception:  # noqa: BLE001 [fallback]
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
        rs = runner_fp.runner_status()
        runner = bool(rs)
        mode = "reload" if rs and all(isinstance(h, dict) and h.get("by") == "reload" for h in rs.values()) else ("runner" if rs else "")
    except Exception:  # noqa: BLE001 [fallback]
        runner, mode = False, ""
    return {"runner": runner, "mode": mode, "manual": ("pm2 restart " + " ".join(units)) if units else MANUAL, "units": list(units or [])}


def _record_reload(entry: dict) -> None:
    try:
        with ss.LOCK:
            try:
                with open(paths.state("wallet_reload.json"), "r", encoding="utf-8") as f:
                    cur = json.load(f)
            except (OSError, ValueError):
                cur = {}
            reqs = [x for x in (cur.get("requests") or []) if isinstance(x, dict)][-19:] if isinstance(cur, dict) else []
            reqs.append(entry)
            statefile.atomic_write_json(paths.state("wallet_reload.json"), {"version": 1, "requests": reqs})
    except Exception:  # noqa: BLE001 [optional]
        pass


SANITY_USD = 1_000_000
SANITY_CHAINS = 4
SANITY_DEADLINE = 8.0
_SANITY_PREF = ("eth", "base", "bsc", "arbitrum", "optimism", "polygon")


class NeedConfirm(ValueError):
    pass


def _sanity_rpcs(cfg: dict, chain: str) -> list:
    nodes = evm_rpcw.rpc_nodes(cfg, chain)
    urls = list(nodes.get("detail") or [])
    sweep_row = chaincatalog.SWEEP_CHAINS.get(chain)
    if not urls and sweep_row:
        urls = list(sweep_row[3] or [])
    return [u for u in urls if isinstance(u, str) and u.startswith("http")][:2]


def _have_pairs(cfg: dict) -> set:
    return {(c, str(w.get("address") or "").lower()) for w in settings_wallets.wallet_list(cfg) for c in w.get("chains") or ()}


def sanity_check(address: str, chains: list, cfg: dict = None) -> dict:
    out = {"confirm": [], "unchecked": []}
    a = str(address or "").strip().lower()
    if not (a.startswith("0x") and len(a) == 42):
        return out
    cfg = cfg if isinstance(cfg, dict) else ss.read_config_raw()
    allowed = {k for k, _n in ss.evm_chains(cfg)}
    chs = [c for c in dict.fromkeys(chains or []) if isinstance(c, str) and c in allowed]
    chs = sorted(chs, key=lambda c: (_SANITY_PREF.index(c) if c in _SANITY_PREF else 99, c))
    out["unchecked"] += chs[SANITY_CHAINS:]
    chs = chs[:SANITY_CHAINS]
    spot = statefile.read_json(paths.state("spot.json"), {}) or {}
    usd = spot.get("usd") if isinstance(spot, dict) and isinstance(spot.get("usd"), dict) else {}
    t_end = time.time() + SANITY_DEADLINE
    pad = a[2:].rjust(64, "0")
    for c in chs:
        urls = _sanity_rpcs(cfg, c)
        if not urls or time.time() > t_end:
            out["unchecked"].append(c)
            continue
        stables = list((token_tables.STABLE_CAS.get(c) or {}).items())[:2]
        calls = [("eth_getCode", [a, "latest"]), ("eth_getBalance", [a, "latest"])]
        for ca, _sym in stables:
            calls += [("eth_call", [{"to": ca, "data": "0x70a08231" + pad}, "latest"]), ("eth_call", [{"to": ca, "data": "0x313ce567"}, "latest"])]
        got = None
        for u in urls:
            left = t_end - time.time()
            if left <= 0.5:
                break
            try:
                res = bf_engine.rpc_batch(u, calls, timeout=min(6.0, left), retries=1, deadline=t_end, sem_timeout=min(3.0, left))
            except Exception:  # noqa: BLE001 [fallback]
                continue
            vals = [None if isinstance(r, Exception) else r for r in (res or [])]
            if any(isinstance(v, str) for v in vals):
                got = dict(enumerate(vals))
                break
        if got is None:
            out["unchecked"].append(c)
            continue
        if not all(isinstance(got.get(i), str) for i in range(len(calls))):
            out["unchecked"].append(c)
        code = str(got.get(0) or "0x").lower() if isinstance(got.get(0), str) else "0x"
        if code not in ("0x", "0x0", ""):
            out["confirm"].append(f"{c}: 컨트랙트 코드가 있는 주소예요" + (" (EIP-7702 위임 지갑)" if code.startswith("0xef0100") else
                                                                    " — 거래소·브릿지·토큰 주소일 수 있어요"))
        tot = 0.0
        try:
            nat_amt = int(str(got.get(1)), 16) / 1e18
            nat_sym = (chaincatalog.SWEEP_CHAINS.get(c) or (None, None, None))[2]
            nat_px = usd.get(str(nat_sym or "").upper())
            if isinstance(nat_px, (int, float)) and not isinstance(nat_px, bool):
                tot += nat_amt * float(nat_px)
        except (TypeError, ValueError):
            pass
        for i, (ca, _sym) in enumerate(stables):
            try:
                bal_raw = int(str(got.get(2 + 2 * i)), 16)
                dec = int(str(got.get(3 + 2 * i)), 16)
                if 0 <= dec <= 36:
                    tot += bal_raw / (10 ** dec)
            except (TypeError, ValueError):
                continue
        if tot >= SANITY_USD:
            out["confirm"].append(f"{c}: 잔고가 약 ${tot:,.0f} 예요 — 거래소·컨트랙트·남의 지갑이 아닌지 확인해 주세요")
    return out


def _sanity_text(chk: dict) -> str:
    return " · ".join(chk.get("confirm") or []) + " — 내 지갑이 맞으면 한 번 더 확인해 주세요"


def _sanity_warn(chk: dict) -> str:
    left = chk.get("unchecked") or []
    return ("코드·잔고 확인 못 함(" + ", ".join(left) + " — 네트워크) · 내 지갑이 맞는지 한 번 더 보세요") if left else ""


def register_wallets(addresses, chains: list, source: str = "", confirm: list = ()) -> dict:
    if isinstance(addresses, str):
        addresses = address_codec.split_addresses(addresses)
    held, warns = {}, {}
    if isinstance(addresses, list) and isinstance(chains, list) and 0 < len(addresses) <= settings_wallets.MAX_BATCH \
            and not address_codec.secret_like(addresses):
        confirmed = {str(x).strip().lower() for x in (confirm or ()) if isinstance(x, str)}
        cfg_now = ss.read_config_raw()
        have = _have_pairs(cfg_now)
        for raw in addresses:
            if not isinstance(raw, str) or not raw.strip().lower().startswith("0x") or raw.strip().lower() in confirmed or raw in held:
                continue
            try:
                _kind, addr_l, _note = address_codec.validate_address(raw)
            except ValueError:
                continue
            new_chains = [c for c in chains if isinstance(c, str) and (c, addr_l.lower()) not in have]
            if not new_chains:
                continue
            verdict = sanity_check(addr_l, new_chains, cfg_now)
            if verdict["confirm"]:
                held[raw] = _sanity_text(verdict)
            elif verdict["unchecked"]:
                warns[addr_l.lower()] = _sanity_warn(verdict)
    if held:
        rest = [x for x in addresses if x not in held]
        res_iter = iter(settings_wallets.add_wallets(rest, list(chains)) if rest else [])
        res = [{"input": x, "status": "confirm", "chains": [], "error": held[x]} if x in held else next(res_iter) for x in addresses]
    else:
        res = settings_wallets.add_wallets(addresses, list(chains or []) if isinstance(chains, list) else chains)
    for r in res:
        warn_text = warns.get(str(r.get("address") or "").lower())
        if warn_text and r.get("status") == "added":
            r["warn"] = warn_text
    ok = [r for r in res if r.get("status") == "added"]
    units = set()
    for r in ok:
        units |= set(_units_for(r.get("kind"), r.get("chains")))
    if ok:
        _record_reload({"ts": int(time.time()), "address": ok[0].get("address"), "addresses": [r.get("address") for r in ok],
                        "chains": sorted({c for r in ok for c in r.get("chains") or []}), "source": source or "",
                        "units": sorted(units)})
    return {"results": res, "added": len(ok), "apply": apply_info(sorted(units))}


def register_chain_wallet(chain: str, address=None, label=None, mode: str = "address", descriptor=None, gap_limit=20,
                          source: str = "", script_type=None) -> dict:
    import chain_registry as reg
    r = settings_wallets.add_chain_wallet(chain, address=address, label=label, mode=mode, descriptor=descriptor, gap_limit=gap_limit,
                            script_type=script_type)
    units = sorted({reg.spec(chain).unit, "tj-core", "tj-web"})
    _record_reload({"ts": int(time.time()), "address": r.get("key"), "chains": [chain], "source": source or "", "units": units})
    r = dict(r)
    r["apply"] = apply_info(units)
    return r


def register_wallet(address: str, chains: list, alias: str, source: str = "", idempotent: bool = False, confirm: bool = False) -> dict:
    warn_text = ""
    if not confirm and isinstance(address, str) and address.strip().lower().startswith("0x"):
        cfg_now = ss.read_config_raw()
        addr_l = address.strip().lower()
        have = _have_pairs(cfg_now)
        new_chains = [c for c in (chains or []) if isinstance(c, str) and (c, addr_l) not in have]
        if new_chains:
            verdict = sanity_check(addr_l, new_chains, cfg_now)
            if verdict["confirm"]:
                raise NeedConfirm(_sanity_text(verdict))
            warn_text = _sanity_warn(verdict)
    try:
        r = settings_wallets.add_wallet(address, alias, list(chains or []))
    except ValueError as e:
        if idempotent and "이미 같은 체인으로 등록된" in str(e):
            kind, addr, _note = address_codec.validate_address(address)
            return {"kind": kind, "address": addr, "chains": [], "note": "이미 등록된 주소·체인",
                    "apply": apply_info()}
        raise
    units = _units_for(r.get("kind"), r.get("chains"))
    _record_reload({"ts": int(time.time()), "address": r.get("address"), "chains": r.get("chains") or [],
                    "source": source or "", "units": units})
    r = dict(r)
    r["apply"] = apply_info(units)
    if warn_text:
        r["warn"] = warn_text
    return r
