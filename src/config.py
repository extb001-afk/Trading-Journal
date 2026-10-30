import json
import urllib.parse
import logging
import os

import cfg_schema, chaincatalog, envfile, net_http, paths, statefile

__all__ = ["load_config", "chain_enabled", "chain_discovery", "bs_blocked", "token_logos_on", "history_wallets", "auto_off_block",
           "fill_chain_table", "gate_decisions", "apply_activity_gate", "exf_poll_sec", "upbit_poll_sec", "exf_fresh_sec", "upbit_fresh_sec",
           "EXF_POLL_DEFAULT", "UPBIT_POLL_DEFAULT", "DEFAULT_DISABLED_CHAINS", "DEFAULT_DISCOVERY", "BS_BLOCKED"]


DEFAULT_DISABLED_CHAINS = set()

DEFAULT_DISCOVERY = {"robinhood": "rpc", "arc": "rpc",
                     "base": "rpc"}


BS_BLOCKED = frozenset(("base", "arbitrum", "polygon"))


def bs_blocked(name: str, cc) -> bool:
    v = (cc or {}).get("discovery") if isinstance(cc, dict) else None
    return name in BS_BLOCKED and str(v or "").lower() != "explorer"


def chain_discovery(name: str, cc) -> str:
    v = (cc or {}).get("discovery") if isinstance(cc, dict) else None
    v = str(v or DEFAULT_DISCOVERY.get(name) or "explorer").lower()
    return "rpc" if v == "rpc" else "explorer"


def chain_enabled(name: str, cc) -> bool:
    if isinstance(cc, dict) and "enabled" in cc:
        return cc.get("enabled") is True
    return name not in DEFAULT_DISABLED_CHAINS


def token_logos_on(cfg) -> bool:
    w = cfg.get("web") if isinstance(cfg, dict) else None
    return isinstance(w, dict) and w.get("token_logos") is True


def fill_chain_table(tbl: dict, col: int = 0) -> dict:
    for k, v in chaincatalog.EXTRA_CHAINS.items():
        tbl.setdefault(k, str(v[col]) if col == 2 else v[col])
    try:
        idx9 = {0: 0, 1: 2, 2: 1}.get(col)
        for k, v in chaincatalog.SWEEP_CHAINS.items():
            if idx9 is not None and k not in tbl:
                tbl[k] = str(v[idx9]) if col == 2 else v[idx9]
    except Exception:   # noqa: BLE001 [optional]
        pass
    return tbl


def _registered_evm(cfg: dict):
    labels = {}
    for w in cfg.get("wallets") or []:
        if w.get("type", "evm") in ("evm", "bsc_rpc"):
            a = str(w.get("address") or "").lower()
            if a.startswith("0x") and len(a) == 42 and a not in labels:
                labels[a] = w.get("label") or ""
    return labels


def gate_decisions(cfg: dict, gate: dict = None, speed: dict = None) -> list:
    gate = statefile.read_json(paths.ACTIVITY_GATE_PATH, {}) if gate is None else gate
    speed = statefile.read_json(paths.BACKFILL_SPEED_PATH, {}) if speed is None else speed
    labels = _registered_evm(cfg)
    chains = cfg.get("chains") or {}
    explicit = {(w.get("chain"), str(w.get("address") or "").lower()) for w in cfg.get("wallets") or []
                if w.get("type", "evm") == "evm"}
    configured = {c for c, cc in chains.items() if isinstance(cc, dict) and not cc.get("_auto")}
    es9 = {}
    cursor_keys = {}
    out = []
    for key, ent in sorted(((gate or {}).get("pairs") or {}).items()):
        if not isinstance(ent, dict) or not ent.get("active") or ":" not in key:
            continue
        c, a = key.split(":", 1)
        a = a.lower()
        if c == "bsc" or a not in labels or (c, a) in explicit:
            continue
        since = ent.get("since_block")
        d = {"chain": c, "addr": a, "label": labels[a], "since": since, "since_state": ent.get("since_state"),
             "ok": False, "reason": "", "block": None}
        cc = chains.get(c)
        if isinstance(cc, dict) and "enabled" in cc and cc.get("enabled") is not True:
            d["reason"] = "설정에서 끈 체인"
        elif c in configured:
            if since is None:
                d["reason"] = "이미 이력이 있는 지갑 — 자동으로는 안 켜요 · 설정 › 지갑 추가에서 같은 주소에 이 체인을 고르면 등록"
            else:
                d["ok"], d["reason"] = True, "새 활동(추적 체인)"
        else:
            try:
                import chaincatalog
                speed_row = ((speed or {}).get("chains") or {}).get(c)
                collected = (since is None and not (isinstance(speed_row, dict) and speed_row.get("autoOk"))
                             and _pair_collected(c, a, cursor_keys))
                blk, why = chaincatalog.block_for(c, since is not None or collected, speed_row)
                if collected and blk is not None and why == "generic":
                    why = "이미 수집 중 — 켠 채로 유지"
                if blk is not None and chaincatalog.es_only(blk) and not _es_key_or_collected(c, es9):
                    blk, why = None, "이더스캔 무료 키 필요 — 설정 › 연결·키 › Etherscan 에 넣으면 자동으로 켜져요"
            except ImportError:
                blk, why = None, "카탈로그 없음"
            d["block"], d["ok"], d["reason"] = blk, blk is not None, why
        out.append(d)
    return out


def _es_key_or_collected(chain: str, memo: dict) -> bool:
    if "key" not in memo:
        memo["key"] = bool(str(envfile.read_env_file().get("TJ_ETHERSCAN_KEY") or "").strip())
    if memo["key"]:
        return True
    try:
        cur = statefile.read_json(paths.state(f"cursor_evm_{chain}.json"), {})
    except (Exception, SystemExit):   # noqa: BLE001 [fallback]
        return True
    return isinstance(cur, dict) and any(not str(k).startswith("_") for k in cur)


def _pair_collected(chain: str, addr: str, memo: dict) -> bool:
    if chain not in memo:
        try:
            cur = statefile.read_json(paths.state(f"cursor_evm_{chain}.json"), {})
            memo[chain] = ({str(k).lower() for k in cur if not str(k).startswith("_")}
                           if isinstance(cur, dict) else None)
        except (Exception, SystemExit):   # noqa: BLE001 [fallback]
            memo[chain] = None
    ks = memo[chain]
    return ks is None or str(addr).lower() in ks


def apply_activity_gate(cfg: dict) -> list:
    sw = cfg.get("chain_sweep")
    if not isinstance(sw, dict) or sw.get("auto_enable") is not True:
        return []
    added = []
    chains = cfg.setdefault("chains", {})
    for d in gate_decisions(cfg):
        if not d["ok"]:
            continue
        c = d["chain"]
        if c not in chains and d["block"]:
            chains[c] = d["block"]
            try:
                import chaincatalog
                rt9 = chaincatalog.recon_tokens_for(cfg, c)
            except ImportError:
                rt9 = {}
            if rt9:
                chains[c]["recon_tokens"] = dict(chains[c].get("recon_tokens") or {}, **rt9)
            try:
                import chaincatalog
                sym, wr = chaincatalog.native_of(c)
            except ImportError:
                sym, wr = None, None
            if sym:
                cfg.setdefault("native_symbol", {}).setdefault(c, sym)
            if wr:
                cfg.setdefault("wrapped_native", {}).setdefault(c, wr)
        if c not in chains:
            continue
        row = {"type": "evm", "chain": c, "address": d["addr"], "label": d["label"], "_auto": "activity"}
        if d["since"] is not None:
            row["since_block"] = int(d["since"])
            if isinstance(d.get("since_state"), list) and len(d["since_state"]) == 2:
                row["since_state"] = [int(d["since_state"][0]), str(d["since_state"][1])]
        cfg.setdefault("wallets", []).append(row)
        added.append((c, d["addr"]))
    if added:
        cfg["_auto_pairs"] = sorted(f"{c}:{a}" for c, a in added)
    off9 = {n for n, cc in chains.items() if isinstance(cc, dict) and not chain_enabled(n, cc)}
    if off9:
        for d in gate_decisions(_as_enabled(cfg)):
            if d["ok"] and d["chain"] in off9:
                _keep_disabled_pair(cfg, d)
    return added


def _as_enabled(cfg: dict) -> dict:
    c2 = dict(cfg)
    ch = dict(cfg.get("chains") or {})
    for n, cc in list(ch.items()):
        if isinstance(cc, dict) and not chain_enabled(n, cc):
            if auto_off_block(cc):
                ch.pop(n)
            else:
                ch[n] = {k: v for k, v in cc.items() if k not in ("enabled", "_chainoff")}
    c2["chains"] = ch
    return c2


def auto_off_block(cc) -> bool:
    if not isinstance(cc, dict):
        return False
    mk = cc.get("_chainoff") if isinstance(cc.get("_chainoff"), dict) else {}
    if mk.get("created"):
        return True
    return not mk and {k for k in cc if not str(k).startswith("_")} == {"enabled"}


def history_wallets(cfg: dict) -> list:
    return list((cfg or {}).get("wallets") or []) + [w for w in ((cfg or {}).get("_disabled_wallets") or []) if isinstance(w, dict)]


def _keep_disabled_pair(cfg: dict, d: dict) -> None:
    c = d["chain"]
    cfg.setdefault("_disabled_wallets", []).append({"type": "evm", "chain": c, "address": d["addr"], "label": d.get("label") or "", "_auto": "activity"})
    try:
        import chaincatalog
        sym, wr = chaincatalog.native_of(c)
    except ImportError:
        sym, wr = None, None
    if sym:
        cfg.setdefault("native_symbol", {}).setdefault(c, sym)
    if wr:
        cfg.setdefault("wrapped_native", {}).setdefault(c, wr)


def _drop_disabled_chains(cfg: dict) -> None:
    chains = cfg.get("chains") or {}
    off = sorted(n for n, cc in chains.items() if not chain_enabled(n, cc))
    if not off:
        return
    for n in off:
        chains.pop(n, None)
    keep = []
    for w in (cfg.get("wallets") or []):
        if w.get("type", "evm") == "evm" and w.get("chain") in off:
            cfg.setdefault("_disabled_wallets", []).append(dict(w))
        else:
            keep.append(w)
    cfg["wallets"] = keep
    cfg["_disabled_chains"] = off
    if _OFF_LOGGED[0] != off:
        _OFF_LOGGED[0] = list(off)
        logging.getLogger("tj").info("비활성 체인(설정 제외): %s — 켜려면 chains.<name>.enabled=true", ", ".join(off))


_OFF_LOGGED = [None]


_CFG_LOADED = [False]


def _config_fail(msg: str, exc=None):
    if _CFG_LOADED[0]:
        if exc is not None:
            raise exc
        raise SystemExit(msg)
    logging.getLogger("tj").critical("★%s — 고친 뒤 저절로 다시 떠요(pm2)★", msg)
    if os.environ.get("pm_id") is not None:
        try:
            wait = float(os.environ.get("TJ_CONFIG_FAIL_WAIT") or 45)
        except ValueError:
            wait = 45.0
        import time as _t
        _t.sleep(max(0.0, min(wait, 600.0)))
    raise SystemExit(msg)


def load_config() -> dict:
    try:
        with open(paths.CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except json.JSONDecodeError as e:
        _config_fail(f"설정 파일 형식 오류: {os.path.basename(paths.CONFIG_PATH)} {e.lineno}줄 {e.colno}칸 — {e.msg}", e)
    if not isinstance(cfg, dict):
        _config_fail(f"설정 파일이 JSON 객체가 아님: {os.path.basename(paths.CONFIG_PATH)}")
    for key in ("chains", "wallets"):
        if key not in cfg:
            _config_fail(f"config.json 에 필수 키 없음: {key}")
    cfg_schema.warn_once(cfg)
    try:
        apply_activity_gate(cfg)
    except (Exception, SystemExit) as e:   # noqa: BLE001 [optional]
        logging.getLogger("tj").warning("활동 게이트 적용 실패(게이트 없이 계속): %s", e)
    _drop_disabled_chains(cfg)
    ns9 = cfg.get("native_symbol")
    if not isinstance(ns9, dict):
        ns9 = cfg["native_symbol"] = {}
    _book9 = set(cfg.get("chains") or {}) | set(cfg.get("_disabled_chains") or [])
    for _name, _sym in chaincatalog.DEFAULT_NATIVE_SYMBOL.items():
        if _name in _book9:
            ns9.setdefault(_name, _sym)
    net_http.BROWSER_UA_HOSTS.clear()
    for _name, _cc in (cfg.get("chains") or {}).items():
        if isinstance(_cc, dict) and _cc.get("browser_ua") and _cc.get("blockscout"):
            _h = urllib.parse.urlsplit(str(_cc["blockscout"])).hostname
            if _h:
                net_http.BROWSER_UA_HOSTS.add(_h.lower())
    for _name, _meta in chaincatalog.EXTRA_CHAINS.items():
        if _name in _book9:
            if not isinstance(cfg.get("native_symbol"), dict):
                cfg["native_symbol"] = {}
            if not isinstance(cfg.get("wrapped_native"), dict):
                cfg["wrapped_native"] = {}
            cfg["native_symbol"].setdefault(_name, _meta[1])
            if _meta[3]:
                cfg["wrapped_native"].setdefault(_name, _meta[3])
    _CFG_LOADED[0] = True
    try:
        import nodekeys
        nodekeys.apply(cfg)
    except Exception as e:   # noqa: BLE001 [optional]
        logging.getLogger("tj").warning("노드 키 적용 실패(종전 설정으로 계속): %s", type(e).__name__)
    return cfg


EXF_POLL_DEFAULT = 600
UPBIT_POLL_DEFAULT = 60


def _poll_cfg(cfg, sect: str, dflt: int, lo: int, hi: int) -> int:
    try:
        v = float(((cfg or {}).get(sect) or {}).get("poll_sec"))
    except (TypeError, ValueError, AttributeError):
        return dflt
    if v != v or v <= 0:
        return dflt
    return int(min(hi, max(lo, v)))


def exf_poll_sec(cfg) -> int:
    return _poll_cfg(cfg, "exf", EXF_POLL_DEFAULT, 60, 6 * 3600)


def exf_binance_dividends(cfg: dict, sect: str = "exf") -> bool:
    blk = (cfg or {}).get(sect) if isinstance(cfg, dict) else None
    return not (isinstance(blk, dict) and blk.get("binance_dividends") is False)


def autofix_enabled(cfg: dict, sect: str = "autofix") -> bool:
    blk = (cfg or {}).get(sect) if isinstance(cfg, dict) else None
    return isinstance(blk, dict) and blk.get("enabled") is True


def upbit_poll_sec(cfg) -> int:
    return _poll_cfg(cfg, "upbit", UPBIT_POLL_DEFAULT, 10, 3600)


def exf_fresh_sec(cfg) -> int:
    return max(1800, 3 * exf_poll_sec(cfg))


def upbit_fresh_sec(cfg) -> int:
    return max(600, 4 * upbit_poll_sec(cfg))
