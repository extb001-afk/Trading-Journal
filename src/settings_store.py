"""Settings, secrets file and CSRF token storage."""
from __future__ import annotations

import json
import logging
import os
import re
import time

import config, envfile, paths, statefile
import fsio

CONFIG_LOCK_NAME = "config.json.lock"


def config_lock_path() -> str:
    return paths.state(CONFIG_LOCK_NAME)


def config_lock_for(path: str) -> str:
    if os.path.realpath(path) == os.path.realpath(paths.CONFIG_PATH):
        return config_lock_path()
    return os.path.join(os.path.dirname(os.path.abspath(path)), "state", CONFIG_LOCK_NAME)


def config_mode(path: str = None) -> int:
    try:
        return (os.stat(path or paths.CONFIG_PATH).st_mode & 0o700) or 0o600
    except OSError:
        return 0o600


LOCK = fsio.FileRLock(config_lock_path)

EXPLORERS = {
    "helius": {"name": "Helius (Solana)", "fields": [("TJ_HELIUS_KEY", "API Key")]},
    "etherscan": {"name": "Etherscan (EVM 가속)", "fields": [("TJ_ETHERSCAN_KEY", "API Key")]},
    "opensea": {"name": "OpenSea (NFT 바닥가 — 넣으면 최우선)", "fields": [("TJ_OPENSEA_KEY", "API Key")]},
    "coingecko": {"name": "CoinGecko (시세·DEX·차트·NFT 바닥가 — 무료 데모 또는 유료 프로 키, 자동 판별)", "fields": [("TJ_COINGECKO_KEY", "API Key (Demo · Pro)")]},
    "nodereal": {"name": "NodeReal (BSC 옛 기록 — 무료 키로도 됨)", "fields": [("TJ_NODEREAL_KEY", "API Key")]},
    "ankr": {"name": "Ankr (받은 토큰 확인 · BSC·Base 옛 기록 — 무료 키)", "fields": [("TJ_ANKR_KEY", "API Key")]},
    "quicknode": {"name": "QuickNode (유료 요금제나 1개월 무료 체험 키 — 멀티체인 엔드포인트 주소 하나)", "fields": [("TJ_QUICKNODE_KEY", "멀티체인 엔드포인트 주소")],
                  "legacy": ("TJ_QUICKNODE_BSC_KEY", "TJ_QUICKNODE_BASE_KEY")},
    "chainnodes": {"name": "Chainnodes (무료 Core 월 1,250만 요청·초당 25 — Base 내부 이동 확인(trace) 우선)", "fields": [("TJ_CHAINNODES_KEY", "API 키 (또는 Base 주소)")]},
    "alchemy": {"name": "Alchemy (EVM 지갑 토큰·잔고 찾기 — 무료 키)", "fields": [("TJ_ALCHEMY_KEY", "API Key")]},
}
NODE_GROUPS = ("nodereal", "ankr", "quicknode", "chainnodes", "alchemy")
EXCHANGES = {
    "upbit": {"name": "업비트", "fields": [("UPBIT_ACCESS", "Access Key"), ("UPBIT_SECRET", "Secret Key")]},
    "bithumb": {"name": "빗썸", "fields": [("TJ_BITHUMB_KEY", "API Key"), ("TJ_BITHUMB_SECRET", "Secret Key")]},
    "binance": {"name": "바이낸스", "fields": [("TJ_BINANCE_KEY", "API Key"), ("TJ_BINANCE_SECRET", "Secret Key")]},
    "bybit": {"name": "바이빗", "fields": [("TJ_BYBIT_KEY", "API Key"), ("TJ_BYBIT_SECRET", "Secret Key")]},
    "okx": {"name": "OKX", "fields": [("TJ_OKX_KEY", "API Key"), ("TJ_OKX_SECRET", "Secret Key"),
                                      ("TJ_OKX_PASSPHRASE", "Passphrase")]},
    "kucoin": {"name": "쿠코인", "fields": [("TJ_KUCOIN_KEY", "API Key"), ("TJ_KUCOIN_SECRET", "Secret Key"),
                                          ("TJ_KUCOIN_PASSPHRASE", "Passphrase")]},
    "gate": {"name": "게이트", "fields": [("TJ_GATE_KEY", "API Key"), ("TJ_GATE_SECRET", "Secret Key")]},
    "coinbase": {"name": "코인베이스", "fields": [("TJ_COINBASE_KEY_NAME", "API 키 이름 (organizations/…/apiKeys/…)"),
                                             ("TJ_COINBASE_SECRET", "비밀키 (-----BEGIN EC PRIVATE KEY----- 부터 끝까지 통째로)")]},
}
SUB_GROUPS = {f"{ex}_sub{n}": {"name": f"{EXCHANGES[ex]['name']} 서브{n}", "base": ex, "sub": n,
                               "fields": [(k2, lab) for (k, lab), k2 in zip(EXCHANGES[ex]["fields"],
                                                                         envfile.sub_key_names(ex, n, [k for k, _l in EXCHANGES[ex]["fields"]]))]}
              for ex in envfile.SUB_EXCHANGES for n in range(1, envfile.SUB_MAX + 1)}


def base_ex(group: str):
    if group in EXCHANGES:
        return group
    g9 = SUB_GROUPS.get(group)
    return g9["base"] if g9 else None


TG_TOKEN, TG_CHAT = "TJ_TG_TOKEN", "TJ_TG_CHAT"
GROUPS = dict(EXPLORERS, **EXCHANGES, **SUB_GROUPS)
SECRET_KEYS = {f for g in GROUPS.values() for f, _ in g["fields"]} | {TG_TOKEN, TG_CHAT}
PUBLIC_KEY_FIELDS = frozenset(g["fields"][0][0] for g in list(EXCHANGES.values()) + list(SUB_GROUPS.values()))

_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_VAL_RE = re.compile(r"^[\x21-\x7e]{1,512}$")


def _parse_env_line(line: str):
    return envfile.parse_env_line(line)


def read_env() -> dict:
    return envfile.read_env_file(paths.ENV_PATH)


def env_value(key: str) -> str:
    return os.environ.get(key) or read_env().get(key, "")


def _atomic_write_text(path: str, text: str, mode: int = 0o600) -> None:
    fsio.atomic_write_text(path, text, mode=mode)


def validate_env_value(key: str, value: str) -> str:
    if not _KEY_RE.match(key or ""):
        raise ValueError("키 이름 형식 오류")
    v = (value or "").strip()
    if not _VAL_RE.match(v):
        raise ValueError("값에 공백·줄바꿈·비ASCII 문자는 넣을 수 없습니다 (1~512자)")
    return v


def write_env(updates: dict) -> None:
    clean = {}
    for k, v in updates.items():
        if not _KEY_RE.match(k or ""):
            raise ValueError("키 이름 형식 오류")
        clean[k] = None if v is None else validate_env_value(k, v)
    with LOCK:
        env_path = paths.ENV_PATH
        try:
            with open(env_path, "r", encoding="utf-8-sig") as f:
                lines = f.read().splitlines()
        except FileNotFoundError:
            lines = ["# tj-bot 비밀값 — 웹 설정 화면이 관리합니다 (직접 수정해도 됩니다). 절대 공유·커밋 금지."]
        out, done = [], set()
        for line in lines:
            kv = _parse_env_line(line)
            if kv and kv[0] in clean:
                k = kv[0]
                if k in done or clean[k] is None:
                    continue
                out.append(f"{k}={clean[k]}")
                done.add(k)
            else:
                out.append(line)
        for k, v in clean.items():
            if k not in done and v is not None:
                out.append(f"{k}={v}")
        _atomic_write_text(env_path, "\n".join(out).rstrip("\n") + "\n", 0o600)


def mask(v: str, public: bool = False) -> str:
    v = v or ""
    if not v:
        return ""
    return "••••" + (v[-4:] if public and len(v) >= 10 else "")


def read_settings() -> dict:
    try:
        with open(paths.state("settings.json"), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _read_settings_for_write() -> dict:
    try:
        with open(paths.state("settings.json"), "r", encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        return {}
    except ValueError:
        d = None
    if isinstance(d, dict):
        return d
    bad = paths.state("settings.json") + f".bad.{int(time.time())}"
    try:
        os.replace(paths.state("settings.json"), bad)
    except OSError:
        pass
    logging.getLogger("tj-settings").error("state/settings.json 손상 — %s 로 옮기고 새로 씀(텔레그램 연결 정보 등은 다시 저장 필요할 수 있음)", bad)
    return {}


def update_settings(**kw) -> dict:
    with LOCK:
        s = _read_settings_for_write()
        for k, v in kw.items():
            if v is None:
                s.pop(k, None)
            else:
                s[k] = v
        s["updated_at"] = int(time.time())
        statefile.atomic_write_json(paths.state("settings.json"), s)
        return s


def csrf_token() -> str:
    import secrets
    with LOCK:
        try:
            with open(paths.state("setup_token"), "r", encoding="utf-8") as f:
                t = f.read().strip()
            if len(t) >= 32:
                return t
        except OSError:
            pass
        t = secrets.token_urlsafe(32)
        _atomic_write_text(paths.state("setup_token"), t + "\n", 0o600)
        return t


def rotate_csrf_token() -> None:
    import secrets
    with LOCK:
        _atomic_write_text(paths.state("setup_token"), secrets.token_urlsafe(32) + "\n", 0o600)


def read_config_raw() -> dict:
    with open(paths.CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def write_config_raw(cfg: dict) -> None:
    _atomic_write_text(paths.CONFIG_PATH, json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", config_mode())


def evm_chains(cfg: dict) -> list:
    names = {"eth": "Ethereum", "base": "Base", "arbitrum": "Arbitrum", "optimism": "Optimism",
             "polygon": "Polygon", "scroll": "Scroll", "zksync": "zkSync", "gnosis": "Gnosis", "bsc": "BNB Chain",
             "robinhood": "Robinhood", "arc": "Arc"}
    config.fill_chain_table(names)
    out = [(k, names.get(k, k)) for k, cc in (cfg.get("chains") or {}).items() if config.chain_enabled(k, cc)]
    if isinstance(cfg.get("bsc"), dict):
        out.append(("bsc", names["bsc"]))
    return out


def needs_etherscan(cfg: dict) -> bool:
    for w in (cfg or {}).get("wallets") or []:
        if isinstance(w, dict) and str(w.get("type", "evm")) == "evm" and w.get("address"):
            return True
    return False


def needs_alchemy(cfg: dict) -> bool:
    ws = (cfg or {}).get("wallets") if isinstance(cfg, dict) else None
    for w in ws if isinstance(ws, list) else []:
        if isinstance(w, dict) and str(w.get("type", "evm")) in ("evm", "bsc_rpc") and w.get("address"):
            return True
    return False


def needs_helius(cfg: dict) -> bool:
    if not isinstance(cfg, dict) or (cfg.get("sol") or {}).get("rpc") != "helius":
        return False
    return any(isinstance(w, dict) and w.get("type") == "sol" and w.get("address") for w in cfg.get("wallets") or [])


def needs_ankr(cfg: dict) -> bool:
    return needs_alchemy(cfg)


def load_config_quiet() -> dict:
    cfg = read_config_raw()
    for key in ("chains", "wallets"):
        if key not in cfg:
            raise ValueError(f"config.json 에 필수 키 없음: {key}")
    try:
        config.apply_activity_gate(cfg)
    except (Exception, SystemExit):   # noqa: BLE001 [optional]
        pass
    chains = cfg.get("chains") or {}
    off = sorted(n for n, cc in chains.items() if not config.chain_enabled(n, cc))
    if off:
        for n in off:
            chains.pop(n, None)
        cfg["wallets"] = [w for w in (cfg.get("wallets") or [])
                          if not (w.get("type", "evm") == "evm" and w.get("chain") in off)]
        cfg["_disabled_chains"] = off
    return cfg
