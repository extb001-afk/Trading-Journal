import paths

__all__ = ["parse_env_line", "read_env_file", "EX_KEYS", "SUB_EXCHANGES", "SUB_MAX", "sub_key_names", "exchange_accounts",
           "acct_progress", "acct_hist", "acct_hist_slot", "IDENT_FILE", "acct_key", "ident_build", "ident_read",
           "ident_snapshot", "ident_held", "ident_slots", "main_ident"]
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402


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


def acct_progress(v: dict) -> int:
    fills = v.get("fills") if isinstance(v.get("fills"), dict) else {}
    return max([int(x) for x in (v.get("backfilled_until"), fills.get("backfilled_until")) if isinstance(x, (int, float)) and not isinstance(x, bool)] or [0])


def acct_hist(v: dict) -> bool:
    if not isinstance(v, dict):
        return False
    fills = v.get("fills") if isinstance(v.get("fills"), dict) else {}
    return bool(acct_progress(v) or v.get("seen") or fills.get("seen") or isinstance(v.get("last_bal"), dict) or v.get("rmap"))


def _slot_rank(tag: str) -> int:
    t = str(tag or "")
    return 0 if not t else (int(t[1:]) if t[1:].isdigit() else 1 << 20)


def acct_hist_slot(subs: dict, tag: str, uid: str, kfp: str, live: dict = None, ex: str = None) -> str:
    held = ident_held(ex, subs) if ex and isinstance(subs, dict) else set()
    if tag and tag not in held and held:
        return sorted(held)[0]
    subs = dict(ident_slots(ex), **subs) if ex and isinstance(subs, dict) else subs
    for slot, st in sorted((subs or {}).items()) if isinstance(subs, dict) else ():
        base = str(slot).split("@")[0]
        if base == tag or not acct_hist(st):
            continue
        if not ((uid and str(st.get("uid") or "") == str(uid)) or (kfp and st.get("kfp") == kfp)):
            continue
        live_uid, live_kfp = (live or {}).get(slot) or (None, None)
        if ("@" not in slot and live_kfp and ((live_uid and str(st.get("uid") or "") == str(live_uid)) or st.get("kfp") == live_kfp)
                and _slot_rank(slot) < _slot_rank(tag)):
            continue
        return base
    return None


IDENT_FILE = "exf_ident.json"
_ID_RX = re.compile(r"[A-Za-z0-9_-]{1,64}")


def acct_key(v: object, tag: str = "") -> dict:
    d = v if isinstance(v, dict) else {}
    uid, kfp = str(d.get("uid") or ""), str(d.get("kfp") or "")
    rest = str(tag or "").split("@", 1)[1] if "@" in str(tag or "") else ""
    if not uid and rest.startswith("u"):
        uid = rest[1:]
    if not kfp and rest.startswith("k"):
        kfp = rest[1:]
    out = {k: x for k, x in (("uid", uid), ("kfp", kfp)) if x and _ID_RX.fullmatch(x)}
    return out or None


def ident_build(state: dict, prev: dict = None) -> dict:
    out = {}
    pex = prev.get("ex") if isinstance(prev, dict) and isinstance(prev.get("ex"), dict) else {}
    for ex in sorted(set(state if isinstance(state, dict) else ()) | set(pex)):
        st = state.get(ex) if isinstance(state, dict) else None
        subs = st.get("accts") if isinstance(st, dict) and isinstance(st.get("accts"), dict) else {}
        pe = pex.get(ex) if isinstance(pex.get(ex), dict) else {}
        hist = {b: [a for a in v if isinstance(a, dict)] for b, v in (pe.get("hist") or {}).items() if isinstance(v, list)}
        active, hold = {}, set()
        keep = {t for t in (pe.get("fut_keep") or ()) if isinstance(t, str) and re.fullmatch(r"s\d{1,2}", t)}
        for tag, v in sorted(subs.items()):
            k = acct_key(v, tag)
            if not isinstance(v, dict):
                continue
            if v.get("fut_keep"):
                keep.add(tag.split("@", 1)[0])
            if not k:
                hold |= {tag} if "@" not in tag and acct_hist(v) else set()
                continue
            if "@" not in tag:
                active[tag] = k
            if acct_hist(v):
                lst = hist.setdefault(tag.split("@", 1)[0], [])
                if k not in lst:
                    lst.append(k)
        hold = sorted(hold | {t for t in (pe.get("hold") or ()) if isinstance(t, str) and not (acct_hist(subs.get(t)) and acct_key(subs.get(t)))})
        main = acct_key(st.get("main_id") if isinstance(st, dict) else None) or acct_key(pe.get("main"))
        if hist or active or hold or keep:
            out[ex] = dict({"active": active, "hist": hist}, **({"hold": hold} if hold else {}), **({"fut_keep": sorted(keep)} if keep else {}),
                           **({"main": main} if main else {}))
    return {"v": 1, "ex": out}


def ident_read(sd: str = None) -> dict:
    try:
        with open(os.path.join(sd, IDENT_FILE) if sd else paths.state(IDENT_FILE), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) and isinstance(d.get("ex"), dict) else {}


def _read_strict(path: str):
    try:
        with open(path, "rb") as f:
            return json.loads(f.read().decode("utf-8"))
    except FileNotFoundError:
        return {}


def ident_snapshot(sd: str, before: tuple = None) -> tuple:
    try:
        st, prev = _read_strict(os.path.join(sd, "exf_state.json")), _read_strict(os.path.join(sd, IDENT_FILE))
    except (OSError, ValueError) as e:
        return None, f"exf_state.json·{IDENT_FILE} {type(e).__name__}"
    if not isinstance(prev, dict) or (prev and not isinstance(prev.get("ex"), dict)):
        return None, f"{IDENT_FILE} 모양 다름"
    if isinstance(st, dict) and any(isinstance(v, dict) and v.get("fut_retag") for v in st.values()):
        return None, "계정 교체 일지가 아직 남음(선물 원본과 지도를 함께 확정 못 함 · 다음 사본에)"
    m = ident_build(st, prev)
    out = (json.dumps(m, ensure_ascii=False, sort_keys=True).encode("utf-8") if m["ex"] else None), None
    return out if before is None or before == out else (None, "사본 중 계정 지도가 바뀜(다음 사본에)")


def ident_held(ex: str, subs: dict = None, sd: str = None) -> set:
    e = (ident_read(sd).get("ex") or {}).get(ex)
    hold = e.get("hold") if isinstance(e, dict) and isinstance(e.get("hold"), list) else []
    return {t for t in hold if isinstance(t, str) and re.fullmatch(r"s\d{1,2}", t) and not acct_hist((subs or {}).get(t))}


def ident_slots(ex: str, sd: str = None) -> dict:
    e = (ident_read(sd).get("ex") or {}).get(ex)
    hist = e.get("hist") if isinstance(e, dict) and isinstance(e.get("hist"), dict) else {}
    out = {}
    for base, lst in sorted(hist.items()):
        for i, a in enumerate(lst if isinstance(lst, list) and re.fullmatch(r"s\d{1,2}", str(base)) else ()):
            k = acct_key(a)
            if k:
                out[f"{base}@r{i}"] = dict(k, rmap=1)
    return out


def main_ident(stx: dict, uid: str, kfp: str, ex: str) -> tuple:
    cur = {k: str(v) for k, v in (("uid", uid), ("kfp", kfp)) if v and _ID_RX.fullmatch(str(v))}
    stx = stx if isinstance(stx, dict) else {}
    e = (ident_read().get("ex") or {}).get(ex)
    rec = acct_key(stx.get("main_id")) or acct_key(e.get("main") if isinstance(e, dict) else None)
    if not rec:
        return "first", cur, None
    if (rec["uid"] == cur["uid"]) if rec.get("uid") and cur.get("uid") else (rec.get("kfp") is not None and rec.get("kfp") == cur.get("kfp")):
        return "same", dict(rec, **cur), None
    other = acct_hist_slot(stx.get("accts") if isinstance(stx.get("accts"), dict) else {}, "", cur.get("uid"), cur.get("kfp"), None, ex)
    return ("hold", None, other) if other is not None else ("new", cur, None)


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
