import paths

__all__ = ["parse_env_line", "read_env_file", "EX_KEYS", "SUB_EXCHANGES", "SUB_MAX", "sub_key_names", "exchange_accounts"]


def parse_env_line(line: str):
    s = str(line or "").strip()
    if not s or s.startswith("#") or "=" not in s:
        return None
    if s.startswith("export "):
        s = s[7:].lstrip()
    k, v = s.split("=", 1)
    k, v = k.strip(), v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        v = v[1:-1]
    return (k, v) if k else None


EX_KEYS = {
    "upbit": ("UPBIT_ACCESS", "UPBIT_SECRET"),
    "bithumb": ("TJ_BITHUMB_KEY", "TJ_BITHUMB_SECRET"),
    "binance": ("TJ_BINANCE_KEY", "TJ_BINANCE_SECRET"),
    "bybit": ("TJ_BYBIT_KEY", "TJ_BYBIT_SECRET"),
    "okx": ("TJ_OKX_KEY", "TJ_OKX_SECRET", "TJ_OKX_PASSPHRASE"),
    "kucoin": ("TJ_KUCOIN_KEY", "TJ_KUCOIN_SECRET", "TJ_KUCOIN_PASSPHRASE"),
    "gate": ("TJ_GATE_KEY", "TJ_GATE_SECRET"),
    "coinbase": ("TJ_COINBASE_KEY_NAME", "TJ_COINBASE_SECRET"),
}


SUB_EXCHANGES = ("binance", "bybit", "okx", "kucoin", "gate")
SUB_MAX = 5


def sub_key_names(ex: str, n: int, need) -> list:
    p9 = f"TJ_{str(ex).upper()}_"
    return [p9 + f"SUB{int(n)}_" + k[len(p9):] if str(k).startswith(p9) else k for k in need]


def exchange_accounts(env: dict, ex: str, need) -> list:
    need = tuple(need or ())
    env = env or {}
    if not need or not all(env.get(k) for k in need):
        return []
    out = [("", env)]
    if ex not in SUB_EXCHANGES:
        return out
    for n in range(1, SUB_MAX + 1):
        names = sub_key_names(ex, n, need)
        if not all(env.get(k) for k in names):
            continue
        e9 = dict(env)
        for k, k2 in zip(need, names):
            e9[k] = env[k2]
        out.append((f"s{n}", e9))
    return out


def read_env_file(path: str = None) -> dict:
    out = {}
    try:
        with open(path or paths.ENV_PATH, "r", encoding="utf-8-sig") as f:
            for line in f:
                kv = parse_env_line(line)
                if kv:
                    out[kv[0]] = kv[1]
    except OSError:
        pass
    return out
