"""Settings, secrets file and CSRF token storage."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time

import common

ENV_PATH = common.ENV_PATH
SETTINGS_PATH = os.path.join(common.STATE_DIR, "settings.json")
TOKEN_PATH = os.path.join(common.STATE_DIR, "setup_token")
LOCK = threading.RLock()

EXPLORERS = {
    "helius": {"name": "Helius (Solana)", "fields": [("TJ_HELIUS_KEY", "API Key")]},
    "etherscan": {"name": "Etherscan (EVM 가속)", "fields": [("TJ_ETHERSCAN_KEY", "API Key")]},
    "opensea": {"name": "OpenSea (NFT 바닥가 — 넣으면 최우선)", "fields": [("TJ_OPENSEA_KEY", "API Key")]},
    "coingecko": {"name": "CoinGecko (시세·DEX·차트·NFT 바닥가 — 무료 데모 또는 유료 프로 키, 자동 판별)", "fields": [("TJ_COINGECKO_KEY", "API Key (Demo · Pro)")]},
    "nodereal": {"name": "NodeReal (BSC 옛 기록 — 무료 키로도 됨)", "fields": [("TJ_NODEREAL_KEY", "API Key")]},
    "ankr": {"name": "Ankr (BSC·Base 옛 기록 — 무료 키로도 됨)", "fields": [("TJ_ANKR_KEY", "API Key")]},
    "quicknode": {"name": "QuickNode (유료 — 체인별 엔드포인트 주소)", "fields": [("TJ_QUICKNODE_BSC_KEY", "BSC 엔드포인트 주소"),
                                                                      ("TJ_QUICKNODE_BASE_KEY", "Base 엔드포인트 주소")]},
}
NODE_GROUPS = ("nodereal", "ankr", "quicknode")
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
}
TG_TOKEN, TG_CHAT = "TJ_TG_TOKEN", "TJ_TG_CHAT"
GROUPS = dict(EXPLORERS, **EXCHANGES)
SECRET_KEYS = {f for g in GROUPS.values() for f, _ in g["fields"]} | {TG_TOKEN, TG_CHAT}
PUBLIC_KEY_FIELDS = frozenset(g["fields"][0][0] for g in EXCHANGES.values())

_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_VAL_RE = re.compile(r"^[\x21-\x7e]{1,512}$")


def _parse_env_line(line: str):
    s = line.strip()
    if not s or s.startswith("#") or "=" not in s:
        return None
    if s.startswith("export "):
        s = s[7:].lstrip()
    k, v = s.split("=", 1)
    return k.strip(), v.strip()


def read_env() -> dict:
    out = {}
    try:
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                kv = _parse_env_line(line)
                if kv and kv[0]:
                    out[kv[0]] = kv[1]
    except OSError:
        pass
    return out


def env_value(key: str) -> str:
    return os.environ.get(key) or read_env().get(key, "")


def _atomic_write_text(path: str, text: str, mode: int = 0o600) -> None:
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp_set_")
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        dfd = os.open(d, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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
        try:
            with open(ENV_PATH, "r", encoding="utf-8") as f:
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
        _atomic_write_text(ENV_PATH, "\n".join(out).rstrip("\n") + "\n", 0o600)


def mask(v: str, public: bool = False) -> str:
    v = v or ""
    if not v:
        return ""
    return "••••" + (v[-4:] if public and len(v) >= 10 else "")


def read_settings() -> dict:
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def update_settings(**kw) -> dict:
    with LOCK:
        s = read_settings()
        for k, v in kw.items():
            if v is None:
                s.pop(k, None)
            else:
                s[k] = v
        s["updated_at"] = int(time.time())
        common.atomic_write_json(SETTINGS_PATH, s)
        return s


def csrf_token() -> str:
    import secrets
    with LOCK:
        try:
            with open(TOKEN_PATH, "r", encoding="utf-8") as f:
                t = f.read().strip()
            if len(t) >= 32:
                return t
        except OSError:
            pass
        t = secrets.token_urlsafe(32)
        _atomic_write_text(TOKEN_PATH, t + "\n", 0o600)
        return t


def rotate_csrf_token() -> None:
    import secrets
    with LOCK:
        _atomic_write_text(TOKEN_PATH, secrets.token_urlsafe(32) + "\n", 0o600)


_RC = [0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
       0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
       0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
       0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
       0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
       0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008]
_ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]
_M64 = (1 << 64) - 1


def _keccak_f(s):
    for rc in _RC:
        c = [s[x][0] ^ s[x][1] ^ s[x][2] ^ s[x][3] ^ s[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ (((c[(x + 1) % 5] << 1) | (c[(x + 1) % 5] >> 63)) & _M64) for x in range(5)]
        s = [[s[x][y] ^ d[x] for y in range(5)] for x in range(5)]
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                r = _ROT[x][y]
                v = s[x][y]
                b[y][(2 * x + 3 * y) % 5] = ((v << r) | (v >> (64 - r))) & _M64 if r else v
        s = [[b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y]) for y in range(5)] for x in range(5)]
        s[0][0] ^= rc
    return s


def keccak256(data: bytes) -> bytes:
    rate = 136
    msg = bytearray(data) + b"\x01"
    while len(msg) % rate:
        msg.append(0)
    msg[-1] |= 0x80
    s = [[0] * 5 for _ in range(5)]
    for off in range(0, len(msg), rate):
        blk = msg[off:off + rate]
        for i in range(rate // 8):
            x, y = i % 5, i // 5
            s[x][y] ^= int.from_bytes(blk[i * 8:i * 8 + 8], "little")
        s = _keccak_f(s)
    out = b""
    for i in range(4):
        out += s[i % 5][i // 5].to_bytes(8, "little")
    return out


def to_checksum(addr: str) -> str:
    a = addr.lower().replace("0x", "")
    h = keccak256(a.encode()).hex()
    return "0x" + "".join(ch.upper() if ch.isalpha() and int(h[i], 16) >= 8 else ch for i, ch in enumerate(a))


_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        i = _B58.find(ch)
        if i < 0:
            raise ValueError("base58 아닌 문자")
        n = n * 58 + i
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + raw


def validate_address(addr: str):
    a = (addr or "").strip()
    if a.lower().startswith("0x"):
        body = a[2:]
        if len(body) != 40 or not re.fullmatch(r"[0-9a-fA-F]{40}", body):
            raise ValueError("EVM 주소는 0x + 16진수 40자입니다")
        if int(body, 16) == 0:
            raise ValueError("0 주소는 추적할 수 없습니다")
        note = ""
        if body != body.lower() and body != body.upper():
            if to_checksum(a) != "0x" + body:
                raise ValueError("체크섬이 맞지 않습니다 — 대소문자가 섞인 주소는 한 글자만 틀려도 거부합니다. 복사한 원문을 확인하세요")
            note = "체크섬 확인됨"
        else:
            note = "체크섬 없는 주소(전부 소문자/대문자) — 오타 여부를 한 번 더 확인하세요"
        return "evm", "0x" + body.lower(), note
    if not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", a):
        raise ValueError("0x… EVM 주소 또는 Solana(base58) 주소가 아닙니다")
    if len(b58decode(a)) != 32:
        raise ValueError("Solana 주소는 base58 로 32바이트여야 합니다")
    return "sol", a, "Solana 주소 형식 확인됨"


MAX_ADDRESSES = 500


def cap_error(n_now: int) -> str:
    return (f"지갑은 최대 {MAX_ADDRESSES}개까지 등록할 수 있습니다 (지금 {n_now}개) — 안 쓰는 주소를 목록에서 빼면 그만큼 더 넣을 수 있어요."
            " 이미 등록된 주소에 체인을 더하는 건 개수와 상관없이 됩니다")


def read_config_raw() -> dict:
    with open(common.CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def write_config_raw(cfg: dict) -> None:
    try:
        mode = (os.stat(common.CONFIG_PATH).st_mode & 0o700) or 0o600
    except OSError:
        mode = 0o600
    _atomic_write_text(common.CONFIG_PATH, json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", mode)


def evm_chains(cfg: dict) -> list:
    names = {"eth": "Ethereum", "base": "Base", "arbitrum": "Arbitrum", "optimism": "Optimism",
             "polygon": "Polygon", "scroll": "Scroll", "zksync": "zkSync", "gnosis": "Gnosis", "bsc": "BNB Chain",
             "robinhood": "Robinhood", "arc": "Arc"}
    common.fill_chain_table(names)
    out = [(k, names.get(k, k)) for k, cc in (cfg.get("chains") or {}).items() if common.chain_enabled(k, cc)]
    if isinstance(cfg.get("bsc"), dict):
        out.append(("bsc", names["bsc"]))
    return out


def needs_etherscan(cfg: dict) -> bool:
    for w in (cfg or {}).get("wallets") or []:
        if isinstance(w, dict) and str(w.get("type", "evm")) == "evm" and w.get("address"):
            return True
    return False


def _label_ok(label: str) -> str:
    s = (label or "").strip()
    if not s or len(s) > 24 or any(ord(c) < 32 for c in s) or any(c in s for c in "<>\"'`"):
        raise ValueError("이름은 1~24자, 꺾쇠·따옴표 없이 입력하세요")
    return s


def wallet_list(cfg: dict) -> list:
    by = {}
    for w in cfg.get("wallets") or []:
        t = w.get("type", "evm")
        a = w.get("address") or ""
        key = a if t == "sol" else a.lower()
        e = by.setdefault(key, {"address": a if t == "sol" else a.lower(), "kind": "sol" if t == "sol" else "evm",
                                "label": w.get("label") or "", "chains": []})
        ch = "sol" if t == "sol" else w.get("chain") or "?"
        if ch not in e["chains"]:
            e["chains"].append(ch)
        if not e["label"] and w.get("label"):
            e["label"] = w["label"]
    return list(by.values())


def add_wallet(address: str, label: str, chains: list) -> dict:
    kind, addr, note = validate_address(address)
    label = _label_ok(label)
    with LOCK:
        cfg = read_config_raw()
        wallets = cfg.setdefault("wallets", [])
        keys9 = {_addr_key(w) for w in wallets}
        if addr not in keys9 and len(keys9) >= MAX_ADDRESSES:
            raise ValueError(cap_error(len(keys9)))
        have = {(w.get("type", "evm"), w.get("chain"), (w.get("address") or "") if w.get("type") == "sol"
                 else (w.get("address") or "").lower()) for w in wallets}
        added = []
        if kind == "sol":
            ent = ("sol", "sol", addr)
            if ent not in have:
                wallets.append({"type": "sol", "chain": "sol", "address": addr, "label": label})
                added.append("sol")
        else:
            allowed = {k for k, _ in evm_chains(cfg)}
            sel = [c for c in (chains or []) if c in allowed]
            if not sel:
                raise ValueError("체인을 하나 이상 고르세요")
            for c in sel:
                t = "bsc_rpc" if c == "bsc" else "evm"
                if (t, c, addr) in have:
                    continue
                wallets.append({"type": t, "chain": c, "address": addr, "label": label})
                added.append(c)
        if not added:
            raise ValueError("이미 같은 체인으로 등록된 주소입니다")
        write_config_raw(cfg)
    return {"kind": kind, "address": addr, "chains": added, "note": note}


MAX_BATCH = 50
ADDR_SPLIT = re.compile(r"[\s,;，；、]+")


def split_addresses(text) -> list:
    return [t for t in ADDR_SPLIT.split(str(text or "")) if t]


_HEX64 = re.compile(r"[0-9a-fA-F]{64}")
_WORD = re.compile(r"[A-Za-z]{3,8}")


def secret_like(tokens) -> str:
    toks = [t for t in tokens if isinstance(t, str)]
    if _HEX64.search(ADDR_SPLIT.sub("", "".join(toks))):
        return "개인 키(16진수 64자)처럼 보이는 값이 있어 아무것도 저장하지 않았습니다 — 지우고 주소만 넣으세요. 개인 키는 절대 입력하지 마세요"
    if sum(1 for t in toks for w in ADDR_SPLIT.split(t) if _WORD.fullmatch(w)) >= 12:
        return "시드 문구(단어 12·24개)처럼 보이는 값이 있어 아무것도 저장하지 않았습니다 — 지우고 주소만 넣으세요. 시드는 절대 입력하지 마세요"
    return ""


def _addr_key(w: dict) -> str:
    a = w.get("address") or ""
    return a if w.get("type") == "sol" else a.lower()


def _auto_label(kind: str, n: int, used: set) -> str:
    stem = "Solana" if kind == "sol" else "지갑"
    while f"{stem} {n}" in used:
        n += 1
    return f"{stem} {n}"


def add_wallets(addresses, chains: list) -> list:
    if isinstance(addresses, str):
        addresses = split_addresses(addresses)
    if not isinstance(addresses, list) or not addresses:
        raise ValueError("추가할 주소가 없습니다")
    if len(addresses) > MAX_BATCH:
        raise ValueError(f"한 번에 최대 {MAX_BATCH}개까지 추가할 수 있습니다 (지금 {len(addresses)}개) — {MAX_BATCH}개씩 나눠서 여러 번 넣어 주세요"
                         f" (전체 최대 {MAX_ADDRESSES}개)")
    if not isinstance(chains, list) or len(chains) > 40 or any(not isinstance(c, str) for c in chains):
        raise ValueError("chains 는 체인 이름 배열입니다")
    why = secret_like(addresses)
    if why:
        raise ValueError(why)
    out = []
    with LOCK:
        cfg = read_config_raw()
        wallets = cfg.setdefault("wallets", [])
        if not isinstance(wallets, list):
            raise ValueError("config.json wallets 형식 오류")
        allowed = {k for k, _ in evm_chains(cfg)}
        sel = [c for c in dict.fromkeys(chains) if c in allowed]
        key_of = _addr_key
        have = {(w.get("type", "evm"), w.get("chain"), key_of(w)) for w in wallets}
        labels = {}
        for w in wallets:
            if w.get("label") and key_of(w) not in labels:
                labels[key_of(w)] = w["label"]
        used = {w.get("label") for w in wallets if w.get("label")}
        n_addr = len({key_of(w) for w in wallets})
        seen = set()
        wrote = False
        for raw in addresses:
            r = {"input": raw if isinstance(raw, str) else "", "chains": []}
            out.append(r)
            if not isinstance(raw, str) or not raw.strip() or len(raw) > 128:
                r.update(status="invalid", error="주소 형식이 아닙니다")
                continue
            try:
                kind, addr, note = validate_address(raw)
            except ValueError as e:
                r.update(status="invalid", error=common.safe_err(e))
                continue
            r.update(kind=kind, address=addr, note=note)
            if addr in seen:
                r.update(status="dup", error="이번 입력에 같은 주소가 또 있습니다")
                continue
            seen.add(addr)
            known = addr in labels or any(k == addr for _t, _c, k in have)
            if kind == "sol":
                todo = [] if any(t == "sol" and k == addr for t, _c, k in have) else ["sol"]
            else:
                if not sel:
                    r.update(status="error", error="체인을 하나 이상 고르세요")
                    continue
                todo = [c for c in sel if ("bsc_rpc" if c == "bsc" else "evm", c, addr) not in have]
            if not todo:
                r.update(status="exists", error="이미 같은 체인으로 등록된 주소입니다", label=labels.get(addr) or "")
                continue
            if not known:
                if n_addr >= MAX_ADDRESSES:
                    r.update(status="error", error=cap_error(n_addr))
                    continue
                n_addr += 1
                labels[addr] = _auto_label(kind, n_addr, used)
                used.add(labels[addr])
            label = labels.get(addr) or _auto_label(kind, n_addr, used)
            for c in todo:
                t = "sol" if kind == "sol" else ("bsc_rpc" if c == "bsc" else "evm")
                wallets.append({"type": t, "chain": c, "address": addr, "label": label})
                have.add((t, c, addr))
            r.update(status="added", chains=todo, label=label)
            wrote = True
        if wrote:
            write_config_raw(cfg)
    return out


def remove_wallet(address: str) -> int:
    a = (address or "").strip()
    with LOCK:
        cfg = read_config_raw()
        before = len(cfg.get("wallets") or [])
        cfg["wallets"] = [w for w in (cfg.get("wallets") or [])
                          if not ((w.get("address") or "") == a or (w.get("type") != "sol"
                                  and (w.get("address") or "").lower() == a.lower()))]
        n = before - len(cfg["wallets"])
        if n:
            write_config_raw(cfg)
    return n


def rename_wallet(address: str, label: str) -> int:
    label = _label_ok(label)
    a = (address or "").strip()
    n = 0
    with LOCK:
        cfg = read_config_raw()
        for w in cfg.get("wallets") or []:
            wa = w.get("address") or ""
            if wa == a or (w.get("type") != "sol" and wa.lower() == a.lower()):
                w["label"] = label
                n += 1
        if n:
            write_config_raw(cfg)
    return n


MAX_PERP = 30


def perp_list(cfg: dict) -> list:
    import perp_dex
    return [{"dex": d, "name": perp_dex.NAMES[d], "address": a["address"], "label": a["label"]}
            for d, lst in perp_dex.configured(cfg).items() for a in lst]


def add_perp(dex: str, address: str, label: str) -> dict:
    import perp_dex
    addr, note = perp_dex.validate_address(dex, address)
    label = _label_ok(label)
    with LOCK:
        cfg = read_config_raw()
        pw = cfg.setdefault("perp_wallets", [])
        if not isinstance(pw, list):
            raise ValueError("config.json perp_wallets 형식 오류")
        have = {(d, a["address"]) for d, lst in perp_dex.configured(cfg).items() for a in lst}
        if (dex, addr) in have:
            raise ValueError("이미 등록된 주소입니다")
        if len(have) >= MAX_PERP:
            raise ValueError(f"퍼프 덱스 주소는 최대 {MAX_PERP}개까지 등록할 수 있습니다")
        pw.append({"dex": dex, "address": addr, "label": label})
        write_config_raw(cfg)
    return {"dex": dex, "address": addr, "note": note}


def remove_perp(dex: str, address: str) -> int:
    import perp_dex
    a = (address or "").strip()
    with LOCK:
        cfg = read_config_raw()
        before = list(cfg.get("perp_wallets") or [])

        def same(w):
            if not isinstance(w, dict) or w.get("dex") != dex:
                return False
            wa = str(w.get("address") or "")
            return wa == a or (perp_dex.DEXES.get(dex, {}).get("kind") != "sol" and wa.lower() == a.lower())
        cfg["perp_wallets"] = [w for w in before if not same(w)]
        n = len(before) - len(cfg["perp_wallets"])
        if n:
            write_config_raw(cfg)
    return n


def load_config_quiet() -> dict:
    cfg = read_config_raw()
    for key in ("chains", "wallets"):
        if key not in cfg:
            raise ValueError(f"config.json 에 필수 키 없음: {key}")
    try:
        common.apply_activity_gate(cfg)
    except (Exception, SystemExit):
        pass
    chains = cfg.get("chains") or {}
    off = sorted(n for n, cc in chains.items() if not common.chain_enabled(n, cc))
    if off:
        for n in off:
            chains.pop(n, None)
        cfg["wallets"] = [w for w in (cfg.get("wallets") or [])
                          if not (w.get("type", "evm") == "evm" and w.get("chain") in off)]
        cfg["_disabled_chains"] = off
    return cfg


def _h(v) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def unit_inputs(unit: str, cfg: dict | None = None, env: dict | None = None):
    cfg = cfg if cfg is not None else load_config_quiet()
    env = env if env is not None else read_env()
    genv = lambda k: os.environ.get(k) or env.get(k, "")
    ws = cfg.get("wallets") or []
    evm = sorted({(w.get("chain"), (w.get("address") or "").lower()) for w in ws if w.get("type", "evm") == "evm"})
    sol = sorted({w.get("address") for w in ws if w.get("type") == "sol"})
    bsc = sorted({(w.get("address") or "").lower() for w in ws if w.get("type") == "bsc_rpc"})
    hk = hashlib.sha256(genv("TJ_HELIUS_KEY").encode()).hexdigest()[:8] if genv("TJ_HELIUS_KEY") else ""
    ek = hashlib.sha256(genv("TJ_ETHERSCAN_KEY").encode()).hexdigest()[:8] if genv("TJ_ETHERSCAN_KEY") else ""
    try:
        import nodekeys
        nk = nodekeys.fingerprint()
    except Exception:
        nk = ""
    if unit == "evm":
        used = sorted({c for c, _ in evm})
        fp = _h([evm, {c: (cfg.get("chains") or {}).get(c) for c in used}, ek, cfg.get("evm_poll_sec"), nk])
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
        return (bool(bsc), "BSC 지갑 없음" if not bsc else "", _h([bsc, cfg.get("bsc"), nk]))
    if unit == "core":
        allw = sorted({(w.get("type", "evm"), w.get("chain"), w.get("address") if w.get("type") == "sol"
                        else (w.get("address") or "").lower()) for w in ws})
        return True, "", _h([allw, cfg.get("exchange_addresses"), hk, nk, cfg.get("backfill_months"),
                             cfg.get("backfill_full_history")])
    if unit == "web":
        return True, "", _h([web_restart_view(cfg), nk])
    return True, "", _h([unit])


WEB_HOT_TOP = ("perp_wallets",)
WEB_HOT_WALLET_FIELDS = ("label",)


def web_restart_view(cfg: dict) -> dict:
    v = {k: x for k, x in (cfg or {}).items() if k not in WEB_HOT_TOP}
    for k in ("wallets", "_disabled_wallets"):
        if isinstance(v.get(k), list):
            v[k] = [{f: y for f, y in w.items() if f not in WEB_HOT_WALLET_FIELDS} if isinstance(w, dict) else w for w in v[k]]
    return v


RUNNER_UNITS = ("evm", "sol", "bsc", "core", "web")


def runner_status(path_fmt: str | None = None) -> dict:
    out = {}
    for u in RUNNER_UNITS:
        p = os.path.join(common.STATE_DIR, f"runner_{u}.json")
        try:
            with open(p, "r", encoding="utf-8") as f:
                hb = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(hb, dict) and time.time() - float(hb.get("ts") or 0) < 120:
            out[u] = hb
    return out
