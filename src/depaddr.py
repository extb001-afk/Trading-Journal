"""Exchange deposit-address discovery and matching."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid as uuidlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

log = logging.getLogger("tj-depaddr")

STORE_NAME = "deposit_addresses.json"
REQ_NAME = "depaddr_request.json"
EXCHANGES = ("upbit", "bithumb", "binance", "bybit", "okx", "kucoin", "gate")
NEED = {
    "upbit": ("UPBIT_ACCESS", "UPBIT_SECRET"),
    "bithumb": ("TJ_BITHUMB_KEY", "TJ_BITHUMB_SECRET"),
    "binance": ("TJ_BINANCE_KEY", "TJ_BINANCE_SECRET"),
    "bybit": ("TJ_BYBIT_KEY", "TJ_BYBIT_SECRET"),
    "okx": ("TJ_OKX_KEY", "TJ_OKX_SECRET", "TJ_OKX_PASSPHRASE"),
    "kucoin": ("TJ_KUCOIN_KEY", "TJ_KUCOIN_SECRET", "TJ_KUCOIN_PASSPHRASE"),
    "gate": ("TJ_GATE_KEY", "TJ_GATE_SECRET"),
}
EX_NAME = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX", "kucoin": "쿠코인", "gate": "게이트",
           "bithumb": "빗썸", "upbit": "업비트", "hyperliquid": "Hyperliquid"}
HL_BRIDGE2 = "0x2df1c51e09aecf9cacb7bc98cb1742757f163df7"
RESTRICTED = {"binance", "bybit", "okx", "gate"}
STRICT = {"bybit", "okx", "gate"}
FIAT = {"KRW", "USD", "EUR", "JPY", "GBP", "AUD", "CAD", "CHF", "TRY", "BRL", "RUB", "UAH", "NGN", "ZAR", "PLN",
        "ARS", "MXN", "CZK", "KZT", "VND", "PHP", "INR", "IDR", "HKD", "SGD", "TWD", "THB", "AED", "COP", "PEN"}

DAY = 86400
PACE = float(os.environ.get("TJ_DEPADDR_PACE") or 0.4)
MAX_CALLS = 900
HIST_DAYS = 730
CAND_EVERY = 300
TICK = 10
BACKOFF = (300, 1800, 3600, 3 * 3600, 6 * 3600)
UA = "tj-bot/1.0 (self-hosted trade journal; read-only)"

_LOCK = threading.RLock()
_NOTIFY = {}
_CACHE = {"mt": None, "idx": None, "path": None, "exmeta": None, "at": 0}
_CFG_CACHE = {"mt": None, "rows": []}


def store_path() -> str:
    return os.path.join(common.STATE_DIR, STORE_NAME)


def req_path() -> str:
    return os.path.join(common.STATE_DIR, REQ_NAME)


_EVM_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_ADDR_OK = re.compile(r"^[A-Za-z0-9:._\-]{3,160}$")
EVM_CHAINS = {"eth", "bsc", "arbitrum", "base", "optimism", "polygon", "zksync", "scroll", "gnosis", "robinhood", "arc",
              "linea", "avalanche", "mantle", "blast", "opbnb", "celo", "kava"}
EVM_CHAINS |= set(common.EXTRA_CHAINS)

_NET_ALIASES = {
    "eth": ("ETH", "ERC20", "ERC-20", "ETHEREUM", "ETHEREUM(ERC20)", "ETH-ERC20", "ETHEREUM (ERC20)", "ETHER"),
    "bsc": ("BSC", "BEP20", "BEP-20", "BEP20(BSC)", "BNB SMART CHAIN", "BNB SMART CHAIN (BEP20)", "BSC_BNB",
            "BNB_BSC", "BNBSMARTCHAIN", "BINANCE SMART CHAIN", "BSC(BEP20)"),
    "arbitrum": ("ARBITRUM", "ARBITRUM ONE", "ARBITRUMONE", "ARB", "ARBI", "ARBEVM", "ARB_ETH", "ARBONE",
                 "ARBITRUM ONE (ARB)", "ARBITRUM_ONE", "ARBETH"),
    "base": ("BASE", "BASEEVM", "BASE_ETH", "BASE MAINNET", "BASEETH"),
    "optimism": ("OPTIMISM", "OP", "OPETH", "OP_ETH", "OPTIMISM (V2)", "OPT", "OP MAINNET", "OPTIMISM_ETH"),
    "polygon": ("MATIC", "POLYGON", "POLYGON POS", "POL", "MATIC_POLYGON", "POLYGONPOS", "PLG", "POLYGON (POS)",
                "MATICPOLY"),
    "zksync": ("ZKSYNC", "ZKSYNCERA", "ZKSYNC ERA", "ZKSERA", "ERA", "ZKSYNC_ERA", "ZKSYNC2"),
    "scroll": ("SCROLL", "SCR", "SCROLLETH"),
    "gnosis": ("GNOSIS", "XDAI", "GNO", "GNOSIS CHAIN"),
    "sol": ("SOL", "SOLANA", "SPL", "SOL_SOL"),
}
_NET_MAP = {a: k for k, v in _NET_ALIASES.items() for a in v}


def norm_addr(a) -> str:
    s = str(a or "").strip()
    return s.lower() if _EVM_RE.match(s) else s


def is_evm(a) -> bool:
    return bool(_EVM_RE.match(str(a or "").strip()))


def chain_of(network, currency=None, address=None):
    n = str(network or "").strip().upper()
    if not n:
        return None
    cur = str(currency or "").strip().upper()
    cands = [n]
    if "-" in n:
        head, _, tail = n.partition("-")
        if head == cur or not cur:
            cands.append(tail.strip())
        cands.append(tail.strip())
    if "(" in n:
        cands.append(n.split("(", 1)[0].strip())
        cands.append(n.split("(", 1)[1].rstrip(")").strip())
    for c in cands:
        if c in _NET_MAP:
            return _NET_MAP[c]
    parts = [p for p in re.split(r"[_\s/]+", n) if p]
    hit = [(_NET_MAP[p]) for p in parts if p in _NET_MAP and p not in ("ETH",)]
    if hit:
        return hit[0]
    if "ETH" in parts:
        return "eth"
    return None


def looks_like_address(a) -> bool:
    s = str(a or "").strip()
    if not s or "@" in s or " " in s or s.isdigit():
        return False
    return bool(_ADDR_OK.match(s))


def _empty_store() -> dict:
    return {"v": 1, "records": [], "exchanges": {}, "updated": 0}


def load_store(path: str | None = None) -> dict:
    p = path or store_path()
    try:
        d = common.read_json(p, None)
    except SystemExit as e:
        raise RuntimeError(f"입금주소 저장소 손상 — 이번 실행 보류: {e}") from None
    if d is None:
        return _empty_store()
    if not isinstance(d, dict) or not isinstance(d.get("records"), list):
        raise RuntimeError("입금주소 저장소 형식 오류 — 이번 실행 보류")
    d.setdefault("exchanges", {})
    return d


def _rkey(r) -> tuple:
    return (r["exchange"], str(r.get("currency") or "").upper(), str(r.get("network") or "").upper(),
            norm_addr(r["address"]), str(r.get("tag") or "").strip())


def merge(store: dict, ex: str, observed: list, now: int, api_seen: bool = True) -> dict:
    idx = {_rkey(r): r for r in store["records"]}
    added = updated = 0
    for o in observed:
        a = str(o.get("address") or "").strip()
        if not looks_like_address(a):
            continue
        rec = {"exchange": ex, "currency": str(o.get("currency") or "").upper(),
               "network": str(o.get("network") or "").strip(), "address": a,
               "tag": str(o.get("tag") or "").strip()}
        k = _rkey(rec)
        cur = idx.get(k)
        src = o.get("source") or "api"
        if cur is None:
            if rec["network"]:
                k0 = (k[0], k[1], "", k[3], k[4])
                if k0 in idx:
                    cur = idx.pop(k0)
                    cur["network"] = rec["network"]
                    cur["chain"] = chain_of(rec["network"], rec["currency"], a)
                    idx[k] = cur
            else:
                cur = next((v for kk, v in idx.items() if kk[0] == k[0] and kk[1] == k[1] and kk[3] == k[3]
                            and kk[4] == k[4]), None)
        if cur is None:
            rec.update({"chain": chain_of(rec["network"], rec["currency"], a), "first_seen": now, "last_seen": now,
                        "sources": [src]})
            if src != "history":
                rec["last_seen_api"] = now
            store["records"].append(rec)
            idx[k] = rec
            cur = rec
            added += 1
        else:
            cur["last_seen"] = max(int(cur.get("last_seen") or 0), now)
            if src not in cur.get("sources", []):
                cur.setdefault("sources", []).append(src)
            if src != "history":
                cur["last_seen_api"] = now
            if not cur.get("chain"):
                cur["chain"] = chain_of(cur.get("network"), cur.get("currency"), cur.get("address"))
            updated += 1
        u = o.get("used_ts")
        if u:
            u = int(u)
            cur["first_used"] = min(int(cur.get("first_used") or u), u)
            cur["last_used"] = max(int(cur.get("last_used") or u), u)
    store["updated"] = now
    return {"added": added, "updated": updated}


def save_store(store: dict, path: str | None = None) -> None:
    common.atomic_write_json(path or store_path(), store)
    _CACHE["idx"] = None


def write_compat(store: dict, ex: str, now: int) -> None:
    addrs, seen = [], set()
    for r in store["records"]:
        if r["exchange"] != ex:
            continue
        k = (norm_addr(r["address"]), r.get("network"), r.get("currency"), r.get("tag"))
        if k in seen:
            continue
        seen.add(k)
        addrs.append({"currency": r.get("currency"), "chain": r.get("network") or r.get("currency"),
                      "address": r["address"], "tag": r.get("tag") or ""})
    common.atomic_write_json(os.path.join(common.STATE_DIR, f"exf_addrs_{ex}.json"), {"ts": now, "addrs": addrs})


def _import_compat(store: dict, now: int) -> int:
    n = 0
    for ex in EXCHANGES:
        p = os.path.join(common.STATE_DIR, f"exf_addrs_{ex}.json")
        try:
            d = common.read_json(p, None)
        except SystemExit:
            continue
        if not isinstance(d, dict):
            continue
        ts = int(d.get("ts") or now)
        obs = []
        for a in d.get("addrs") or []:
            if not isinstance(a, dict):
                continue
            net = a.get("chain") or ""
            if ex == "binance" and str(net).upper() == str(a.get("currency") or "").upper():
                net = ""
            obs.append({"currency": a.get("currency"), "network": net, "address": a.get("address"),
                        "tag": a.get("tag"), "source": "legacy"})
        if obs:
            r = merge(store, ex, obs, ts)
            n += r["added"]
    return n


class ApiError(Exception):

    def __init__(self, msg, status=0, fatal=False):
        super().__init__(common.redact_secret_text(msg))
        self.status, self.fatal = status, fatal


_FATAL_CODES = {
    "binance": {"-2014", "-2015", "-1022", "-1021", "-1003", "-1002"},
    "bybit": {"10002", "10003", "10004", "10005", "10006", "10010", "10018", "33004"},
    "okx": {"50011", "50013", "50102", "50105", "50110", "50111", "50113", "50114", "50100", "50101"},
    "kucoin": {"400001", "400002", "400003", "400004", "400005", "400006", "400007", "411100", "429000"},
    "gate": {"INVALID_KEY", "INVALID_SIGNATURE", "FORBIDDEN", "IP_FORBIDDEN", "MISSING_REQUIRED_HEADER",
             "REQUEST_EXPIRED", "TOO_MANY_REQUESTS", "INVALID_CREDENTIALS", "READ_ONLY"},
    "upbit": {"invalid_access_key", "jwt_verification", "expired_access_key", "no_authorization_ip",
              "out_of_scope", "invalid_query_payload", "nonce_used", "too_many_requests", "invalid_access"},
}
_FATAL_CODES["bithumb"] = _FATAL_CODES["upbit"]


def _is_fatal(status, body: str = "", ex: str = "", code=None) -> bool:
    if status in (401, 403, 418, 429) or (status and status >= 500):
        return True
    if code is not None:
        return str(code) in _FATAL_CODES.get(ex, set())
    b = body or ""
    return any(c in b for c in _FATAL_CODES.get(ex, set()) if len(c) >= 5 or c.startswith("-"))


def http_get(url: str, headers: dict, timeout: int = 20, ex: str = ""):
    h = {"User-Agent": UA, "Accept": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")), dict(r.headers)
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "ignore")[:400]
        except Exception:
            body = ""
        raise ApiError(f"HTTP {e.code}: {body[:200]}", e.code, _is_fatal(e.code, body, ex)) from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ApiError(f"network: {type(e).__name__}: {str(e)[:120]}", 0, True) from None


def _jwt(access, secret, params, with_ts=False) -> str:
    def b64u(b):
        return base64.urlsafe_b64encode(b).rstrip(b"=")
    payload = {"access_key": access, "nonce": str(uuidlib.uuid4())}
    if with_ts:
        payload["timestamp"] = int(time.time() * 1000)
    if params:
        raw = "&".join(f"{k}={v}" for k, v in params.items())
        payload["query_hash"] = hashlib.sha512(raw.encode()).hexdigest()
        payload["query_hash_alg"] = "SHA512"
    h = b64u(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    p = b64u(json.dumps(payload).encode())
    s = b64u(hmac.new(secret.encode(), h + b"." + p, hashlib.sha256).digest())
    return (h + b"." + p + b"." + s).decode()


class Client:

    def __init__(self, ex: str, env: dict, pace: float | None = None):
        self.ex, self.env = ex, env
        self.pace = PACE if pace is None else pace
        self.calls = 0
        self._last = 0.0

    def _wait(self):
        dt = time.time() - self._last
        if dt < self.pace:
            time.sleep(self.pace - dt)
        self._last = time.time()
        self.calls += 1

    def get(self, path: str, params: dict | None = None):
        try:
            return self._get(path, params)
        except ApiError as e9:
            sec = [v for k, v in (self.env or {}).items() if common._secret_name(k)]
            raise ApiError(common.redact_secret_text(str(e9), extra=sec), e9.status, e9.fatal) from None

    def _get(self, path: str, params: dict | None = None):
        self._wait()
        e, p = self.env, dict(params or {})
        ex = self.ex
        if ex in ("upbit", "bithumb"):
            if ex == "upbit":
                a, s, host, ts = e["UPBIT_ACCESS"], e["UPBIT_SECRET"], "https://api.upbit.com", False
            else:
                a, s, host, ts = e["TJ_BITHUMB_KEY"], e["TJ_BITHUMB_SECRET"], "https://api.bithumb.com", True
            qs = urllib.parse.urlencode(p)
            d, hdr = http_get(host + path + ("?" + qs if qs else ""), {"Authorization": "Bearer " + _jwt(a, s, p, ts)},
                              ex=ex)
            rem = str((hdr or {}).get("Remaining-Req") or "")
            m = re.search(r"sec=(\d+)", rem)
            if m and int(m.group(1)) <= 1:
                time.sleep(1.0)
            if isinstance(d, dict) and d.get("error"):
                err = d["error"] if isinstance(d["error"], dict) else {"name": str(d["error"])}
                nm = str(err.get("name") or "")
                raise ApiError(f"{ex} {nm}: {str(err.get('message') or '')[:120]}", 200, _is_fatal(0, ex=ex, code=nm))
            return d
        if ex == "binance":
            p["timestamp"] = int(time.time() * 1000)
            p["recvWindow"] = 10000
            qs = urllib.parse.urlencode(p)
            sig = hmac.new(e["TJ_BINANCE_SECRET"].encode(), qs.encode(), hashlib.sha256).hexdigest()
            d, _ = http_get(f"https://api.binance.com{path}?{qs}&signature={sig}", {"X-MBX-APIKEY": e["TJ_BINANCE_KEY"]}, ex=ex)
            if isinstance(d, dict) and "code" in d and isinstance(d.get("code"), int) and d["code"] < 0:
                raise ApiError(f"binance {d['code']} {str(d.get('msg'))[:120]}", 200, _is_fatal(0, ex=ex, code=d["code"]))
            return d
        if ex == "bybit":
            qs = urllib.parse.urlencode(p)
            t = str(int(time.time() * 1000))
            sig = hmac.new(e["TJ_BYBIT_SECRET"].encode(), (t + e["TJ_BYBIT_KEY"] + "10000" + qs).encode(),
                           hashlib.sha256).hexdigest()
            d, _ = http_get(f"https://api.bybit.com{path}?{qs}",
                            {"X-BAPI-API-KEY": e["TJ_BYBIT_KEY"], "X-BAPI-TIMESTAMP": t,
                             "X-BAPI-RECV-WINDOW": "10000", "X-BAPI-SIGN": sig}, ex=ex)
            if not isinstance(d, dict) or d.get("retCode") != 0:
                code = str((d or {}).get("retCode")) if isinstance(d, dict) else "?"
                raise ApiError(f"bybit {code} {str((d or {}).get('retMsg') if isinstance(d, dict) else d)[:120]}",
                               200, _is_fatal(0, ex=ex, code=code))
            return d.get("result") or {}
        if ex in ("okx", "kucoin"):
            qs = urllib.parse.urlencode(p)
            full = path + ("?" + qs if qs else "")
            if ex == "okx":
                t = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time() * 1000) % 1000:03d}Z"
                sig = base64.b64encode(hmac.new(e["TJ_OKX_SECRET"].encode(), (t + "GET" + full).encode(),
                                                hashlib.sha256).digest()).decode()
                d, _ = http_get("https://www.okx.com" + full,
                                {"OK-ACCESS-KEY": e["TJ_OKX_KEY"], "OK-ACCESS-SIGN": sig, "OK-ACCESS-TIMESTAMP": t,
                                 "OK-ACCESS-PASSPHRASE": e["TJ_OKX_PASSPHRASE"]}, ex=ex)
                if not isinstance(d, dict) or d.get("code") != "0":
                    code = str((d or {}).get("code")) if isinstance(d, dict) else "?"
                    raise ApiError(f"okx {code} {str((d or {}).get('msg') if isinstance(d, dict) else d)[:120]}",
                                   200, _is_fatal(0, ex=ex, code=code))
                return d.get("data") or []
            t = str(int(time.time() * 1000))
            sec = e["TJ_KUCOIN_SECRET"].encode()
            sig = base64.b64encode(hmac.new(sec, (t + "GET" + full).encode(), hashlib.sha256).digest()).decode()
            pph = base64.b64encode(hmac.new(sec, e["TJ_KUCOIN_PASSPHRASE"].encode(), hashlib.sha256).digest()).decode()
            d, _ = http_get("https://api.kucoin.com" + full,
                            {"KC-API-KEY": e["TJ_KUCOIN_KEY"], "KC-API-SIGN": sig, "KC-API-TIMESTAMP": t,
                             "KC-API-PASSPHRASE": pph, "KC-API-KEY-VERSION": "2"}, ex=ex)
            if not isinstance(d, dict) or d.get("code") != "200000":
                code = str((d or {}).get("code")) if isinstance(d, dict) else "?"
                raise ApiError(f"kucoin {code} {str((d or {}).get('msg') if isinstance(d, dict) else d)[:120]}",
                               200, _is_fatal(0, ex=ex, code=code))
            return d.get("data")
        if ex == "gate":
            qs = urllib.parse.urlencode(p)
            t = str(int(time.time()))
            bh = hashlib.sha512(b"").hexdigest()
            sig = hmac.new(e["TJ_GATE_SECRET"].encode(), f"GET\n{path}\n{qs}\n{bh}\n{t}".encode(),
                           hashlib.sha512).hexdigest()
            d, _ = http_get(f"https://api.gateio.ws{path}" + (f"?{qs}" if qs else ""),
                            {"KEY": e["TJ_GATE_KEY"], "Timestamp": t, "SIGN": sig}, ex=ex)
            if isinstance(d, dict) and d.get("label") and not d.get("address") and "multichain_addresses" not in d:
                raise ApiError(f"gate {d.get('label')} {str(d.get('message'))[:120]}", 200, _is_fatal(0, ex=ex, code=d["label"]))
            return d
        raise ValueError("unknown exchange")


def _db_currencies(ex: str) -> dict:
    out = {"deposit": set(), "withdraw": set(), "trade": set(), "pairs": set()}
    if not os.path.exists(common.DB_PATH):
        return out
    try:
        c = sqlite3.connect(common.sqlite_ro_uri(common.DB_PATH), uri=True, timeout=5)
    except sqlite3.Error:
        return out
    try:
        q = ("SELECT kind, json_extract(payload,'$.currency'), json_extract(payload,'$.net_type'),"
             " json_extract(payload,'$.base'), json_extract(payload,'$.quote'), json_extract(payload,'$.market')"
             " FROM raw_ex WHERE exchange=? GROUP BY 1,2,3,4,5,6")
        rows = c.execute(q, (ex,)).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        c.close()
    for kind, cur, net, base, quote, market in rows:
        cur = str(cur or "").upper()
        if kind == "deposit" and cur:
            out["deposit"].add(cur)
            if net:
                out["pairs"].add((cur, str(net)))
        elif kind == "withdraw" and cur:
            out["withdraw"].add(cur)
            if net:
                out["pairs"].add((cur, str(net)))
        elif kind in ("trade", "order"):
            for s in (base, quote):
                if s:
                    out["trade"].add(str(s).upper())
            if market and "-" in str(market):
                for s in str(market).split("-"):
                    out["trade"].add(s.upper())
    return out


def _held(ex: str) -> set:
    out = set()
    if ex == "upbit":
        try:
            d = common.read_json(os.path.join(common.STATE_DIR, "upbit_balances.json"), {}) or {}
        except SystemExit:
            d = {}
        for a in d.get("accounts") or [] if isinstance(d, dict) else []:
            try:
                if float(a.get("balance") or 0) + float(a.get("locked") or 0) > 0:
                    out.add(str(a.get("currency") or "").upper())
            except (TypeError, ValueError, AttributeError):
                pass
        return out
    for suf in ("", ".pending"):
        try:
            d = common.read_json(os.path.join(common.STATE_DIR, f"exf_balances_{ex}.json{suf}"), {}) or {}
        except SystemExit:
            continue
        b = d.get("balances") if isinstance(d, dict) else None
        if isinstance(b, dict):
            out |= {str(k).upper() for k in b}
    return out


def candidates(ex: str, store: dict) -> dict:
    db = _db_currencies(ex)
    held = _held(ex)
    known = {str(r.get("currency") or "").upper() for r in store["records"] if r["exchange"] == ex}
    known |= {str(p[0]).upper() for p in (store["exchanges"].get(ex) or {}).get("hist_pairs") or []}
    allc = (db["deposit"] | db["withdraw"] | db["trade"] | held | known) - FIAT
    restricted = (db["deposit"] | held | known) - FIAT
    allc = {c for c in allc if re.match(r"^[A-Z0-9]{1,20}$", c)}
    restricted = {c for c in restricted if re.match(r"^[A-Z0-9]{1,20}$", c)}
    strict = {c for c in (db["deposit"] | known) - FIAT if re.match(r"^[A-Z0-9]{1,20}$", c)}
    return {"all": allc, "restricted": restricted, "strict": strict, "pairs": db["pairs"], "deposit": db["deposit"]}


def _pool(ex: str, c: dict) -> set:
    return c["strict"] if ex in STRICT else c["restricted"] if ex in RESTRICTED else c["all"]


def _ts(v):
    try:
        f = float(v)
        return int(f / 1000) if f > 10 ** 12 else int(f)
    except (TypeError, ValueError):
        pass
    try:
        from datetime import datetime
        s = str(v).replace("Z", "+00:00")
        if len(s) == 19:
            s += "+00:00"
        return int(datetime.fromisoformat(s).timestamp())
    except (ValueError, TypeError):
        return None


def _windows(t0: int, t1: int, span: int):
    e = t1
    while e > t0:
        s = max(t0, e - span)
        yield s, e
        e = s


def hist_binance(cl, t0, t1):
    out = []
    for s, e in _windows(t0, t1, 89 * DAY):
        off = 0
        while True:
            rows = cl.get("/sapi/v1/capital/deposit/hisrec",
                          {"startTime": s * 1000, "endTime": e * 1000, "limit": 1000, "offset": off}) or []
            if not isinstance(rows, list):
                raise ApiError("binance hisrec 형식 오류")
            for r in rows:
                if int(r.get("transferType") or 0) == 1:
                    continue
                out.append({"currency": r.get("coin"), "network": r.get("network"), "address": r.get("address"),
                            "tag": r.get("addressTag"), "source": "history", "used_ts": _ts(r.get("insertTime"))})
            if len(rows) < 1000:
                break
            off += 1000
        yield s, out
        out = []


def hist_bybit(cl, t0, t1):
    for s, e in _windows(t0, t1, 29 * DAY):
        out, cursor, seen = [], "", set()
        while True:
            p = {"startTime": s * 1000, "endTime": e * 1000, "limit": 50}
            if cursor:
                p["cursor"] = cursor
            res = cl.get("/v5/asset/deposit/query-record", p)
            rows = res.get("rows") or []
            for r in rows:
                out.append({"currency": r.get("coin"), "network": r.get("chain"), "address": r.get("toAddress"),
                            "tag": r.get("tag"), "source": "history", "used_ts": _ts(r.get("successAt"))})
            cursor = res.get("nextPageCursor") or ""
            if not cursor or not rows:
                break
            if cursor in seen:
                raise ApiError("bybit 이력 커서 순환")
            seen.add(cursor)
        yield s, out


def hist_okx(cl, t0, t1):
    after, out = "", []
    got = set()
    while True:
        p = {"limit": 100}
        if after:
            p["after"] = after
        rows = cl.get("/api/v5/asset/deposit-history", p)
        if not rows:
            break
        n_new = 0
        for r in rows:
            k9 = (str(r.get("depId") or ""), str(r.get("txId") or ""), str(r.get("ts") or ""), str(r.get("ccy") or ""))
            if k9 in got:
                continue
            got.add(k9)
            n_new += 1
            if r.get("from") and not r.get("txId"):
                continue
            out.append({"currency": r.get("ccy"), "network": r.get("chain"), "address": r.get("to"),
                        "tag": r.get("tag") or r.get("memo") or "", "source": "history", "used_ts": _ts(r.get("ts"))})
        oldest = min(int(r.get("ts") or 0) for r in rows)
        if oldest // 1000 <= t0 or len(rows) < 100:
            break
        if after and n_new == 0:
            raise ApiError("okx 이력 시각 미전진")
        after = str(oldest + 1)
        yield max(t0, oldest // 1000), out
        out = []
    yield t0, out


def hist_kucoin(cl, t0, t1):
    for s, e in _windows(t0, t1, 7 * DAY):
        out, page = [], 1
        while True:
            qs = {"startAt": s * 1000, "endAt": e * 1000, "pageSize": 100, "currentPage": page}
            d = cl.get("/api/v1/deposits", qs) or {}
            for r in d.get("items") or []:
                if r.get("isInner"):
                    continue
                out.append({"currency": r.get("currency"), "network": r.get("chain"), "address": r.get("address"),
                            "tag": r.get("memo"), "source": "history", "used_ts": _ts(r.get("createdAt"))})
            if page >= int(d.get("totalPage") or 1):
                break
            if page >= 50:
                raise ApiError(f"kucoin 입금 이력 7일 창 50페이지 초과({time.strftime('%Y-%m-%d', time.gmtime(s))}~)")
            page += 1
        yield s, out


def hist_gate(cl, t0, t1):
    for s, e in _windows(t0, t1, 29 * DAY):
        out, off = [], 0
        while True:
            rows = cl.get("/api/v4/wallet/deposits", {"from": s, "to": e, "limit": 500, "offset": off}) or []
            if not isinstance(rows, list):
                raise ApiError("gate deposits 형식 오류")
            for r in rows:
                out.append({"currency": r.get("currency"), "network": r.get("chain"), "address": r.get("address"),
                            "tag": r.get("memo") or r.get("payment_id") or "", "source": "history",
                            "used_ts": _ts(r.get("timestamp"))})
            if len(rows) < 500:
                break
            off += 500
        yield s, out


def hist_pairs_upbitlike(cl, t0, t1):
    pairs, page = set(), 1
    while True:
        if page > 100:
            e9 = ApiError("업비트·빗썸 입금 이력 100페이지 초과(창 하한 미도달)")
            e9.partial = pairs
            raise e9
        rows = cl.get("/v1/deposits", {"limit": 100, "page": page, "order_by": "desc"})
        if not isinstance(rows, list):
            raise ApiError("deposits 형식 오류")
        if not rows:
            break
        stop = False
        for r in rows:
            c, n = str(r.get("currency") or "").upper(), r.get("net_type")
            if c and n:
                pairs.add((c, str(n)))
            t = _ts(r.get("created_at"))
            if t and t < t0:
                stop = True
        if stop or len(rows) < 100:
            break
        page += 1
    return pairs


HIST = {"binance": hist_binance, "bybit": hist_bybit, "okx": hist_okx, "kucoin": hist_kucoin, "gate": hist_gate}


def _collect_upbitlike(cl, cands, meta, only=None):
    obs, checked, errs = [], set(), []
    rows = cl.get("/v1/deposits/coin_addresses")
    if not isinstance(rows, list):
        raise ApiError("coin_addresses 형식 오류")
    have = set()
    for r in rows:
        c = str(r.get("currency") or "").upper()
        n = r.get("net_type") or r.get("net_name") or ""
        if r.get("deposit_address"):
            obs.append({"currency": c, "network": n, "address": r["deposit_address"],
                        "tag": r.get("secondary_address") or "", "source": "api"})
        have.add((c, str(n)))
        checked.add(c)
    pairs = set(cands["pairs"]) | {tuple(p) for p in meta.get("hist_pairs") or []}
    for c, n in sorted(pairs):
        if (c, n) in have or c in FIAT or (only is not None and c not in only):
            continue
        if cl.calls >= MAX_CALLS:
            break
        try:
            r = cl.get("/v1/deposits/coin_address", {"currency": c, "net_type": n})
        except ApiError as e:
            if e.fatal:
                raise
            errs.append(f"{c}/{n}: {str(e)[:60]}")
            checked.add(c)
            continue
        if isinstance(r, dict) and r.get("deposit_address"):
            obs.append({"currency": c, "network": r.get("net_type") or n, "address": r["deposit_address"],
                        "tag": r.get("secondary_address") or "", "source": "api"})
        checked.add(c)
    return obs, checked, errs


def _binance_meta(cl):
    rows = cl.get("/sapi/v1/capital/config/getall") or []
    out = {}
    for c in rows if isinstance(rows, list) else []:
        nets = c.get("networkList") or []
        out[str(c.get("coin") or "").upper()] = {
            "default": next((n.get("network") for n in nets if n.get("isDefault")), None),
            "nets": {n.get("network") for n in nets if n.get("depositEnable")},
            "legal": bool(c.get("isLegalMoney"))}
    return out


def _collect_binance(cl, cands, store, only=None, hist_obs=()):
    obs, checked, errs = [], set(), []
    cm = _binance_meta(cl)
    used = {}
    for r in list(store["records"]) + [dict(o, exchange="binance") for o in hist_obs]:
        if r["exchange"] == "binance" and r.get("network"):
            used.setdefault(str(r.get("currency") or "").upper(), set()).add(r["network"])
    pool = cands["restricted"] | set(used)
    coins = sorted((only if only is not None else pool) - FIAT)
    for c in coins:
        m = cm.get(c)
        if m is None or m["legal"] or not m["nets"]:
            checked.add(c)
            continue
        if cl.calls >= MAX_CALLS:
            break
        try:
            rows = cl.get("/sapi/v1/capital/deposit/address/list", {"coin": c}) or []
        except ApiError as e:
            if e.fatal:
                raise
            errs.append(f"{c}: {str(e)[:60]}")
            checked.add(c)
            continue
        for r in rows if isinstance(rows, list) else []:
            if r.get("address"):
                obs.append({"currency": c, "network": r.get("network") or m["default"] or "",
                            "address": r["address"], "tag": r.get("tag") or "", "source": "api"})
        checked.add(c)
        for n in sorted((used.get(c) or set()) & m["nets"] - {m["default"]}):
            if cl.calls >= MAX_CALLS:
                break
            try:
                rows = cl.get("/sapi/v1/capital/deposit/address/list", {"coin": c, "network": n}) or []
            except ApiError as e:
                if e.fatal:
                    raise
                errs.append(f"{c}/{n}: {str(e)[:60]}")
                continue
            for r in rows if isinstance(rows, list) else []:
                if r.get("address"):
                    obs.append({"currency": c, "network": n, "address": r["address"], "tag": r.get("tag") or "",
                                "source": "api"})
    return obs, checked, errs


def _collect_percoin(ex, cl, coins):
    obs, checked, errs = [], set(), []
    for c in sorted(coins):
        if cl.calls >= MAX_CALLS:
            break
        try:
            if ex == "okx":
                for r in cl.get("/api/v5/asset/deposit-address", {"ccy": c}) or []:
                    if r.get("addr"):
                        obs.append({"currency": c, "network": r.get("chain") or "", "address": r["addr"],
                                    "tag": r.get("tag") or r.get("memo") or r.get("pmtId") or "", "source": "api"})
            elif ex == "bybit":
                res = cl.get("/v5/asset/deposit/query-address", {"coin": c})
                for ch in res.get("chains") or []:
                    if ch.get("addressDeposit"):
                        obs.append({"currency": c, "network": ch.get("chain") or ch.get("chainType") or "",
                                    "address": ch["addressDeposit"], "tag": ch.get("tagDeposit") or "",
                                    "source": "api"})
            elif ex == "kucoin":
                for r in cl.get("/api/v3/deposit-addresses", {"currency": c}) or []:
                    if r.get("address"):
                        obs.append({"currency": c, "network": r.get("chainId") or r.get("chainName") or r.get("chain")
                                    or "", "address": r["address"], "tag": r.get("memo") or "", "source": "api"})
            elif ex == "gate":
                d = cl.get("/api/v4/wallet/deposit_address", {"currency": c}) or {}
                for r in d.get("multichain_addresses") or []:
                    if r.get("address") and not int(r.get("obtain_failed") or 0):
                        obs.append({"currency": c, "network": r.get("chain") or "", "address": r["address"],
                                    "tag": r.get("payment_id") or "", "source": "api"})
        except ApiError as e:
            if e.fatal:
                raise
            errs.append(f"{c}: {str(e)[:60]}")
        checked.add(c)
    return obs, checked, errs


def _hist_depth(now: int) -> int:
    t0 = now - HIST_DAYS * DAY
    try:
        cfg = common.read_json(common.CONFIG_PATH, {}) or {}
        m = float(cfg.get("backfill_months") or 5)
        t0 = min(t0, int(now - m * 30 * DAY))
    except (SystemExit, TypeError, ValueError):
        pass
    try:
        import bf_engine
        tg = bf_engine.SINCE.target(None)
        if tg:
            t0 = min(t0, int(tg))
    except Exception:
        pass
    return int(t0)


def _key_fp(ex, env) -> str:
    return hashlib.sha256(("tj-depaddr:" + env.get(NEED[ex][0], "")).encode()).hexdigest()[:12]


def refresh(ex: str, env: dict, reason: str = "manual", only=None, hist_only: bool = False,
            now: int | None = None, pace: float | None = None) -> dict:
    now = int(now or time.time())
    cl = Client(ex, env, pace)
    res = {"exchange": ex, "reason": reason, "ok": False, "added": 0, "calls": 0, "errors": [], "hist": None}
    with _LOCK:
        store = load_store()
        if not store["records"] and not store.get("imported"):
            _import_compat(store, now)
            store["imported"] = now
        meta = store["exchanges"].setdefault(ex, {})
        meta["running"] = now
        save_store(store)
    obs, checked, errs = [], set(), []
    hist_note = None
    fatal = None
    try:
        cands = candidates(ex, store)
        if ex in HIST:
            want_from = _hist_depth(now)
            h_from = int(meta.get("hist_from") or 0)
            h_until = int(meta.get("hist_until") or 0)
            spans = []
            if h_until:
                spans.append((max(want_from, h_until - 2 * DAY), now, "inc"))
                if want_from < h_from and not hist_only:
                    spans.append((want_from, h_from, "back"))
            else:
                spans.append((want_from, now, "full"))
            for a0, b0, kind in spans:
                reached = b0
                done = True
                try:
                    for s_edge, rows in HIST[ex](cl, a0, b0):
                        obs.extend(rows)
                        reached = s_edge
                except ApiError as e:
                    if e.fatal:
                        raise
                    done = False
                    hist_note = f"입금 이력 일부 조회 실패({time.strftime('%Y-%m-%d', time.gmtime(reached))} 이전): {str(e)[:80]}"
                if kind == "inc":
                    if done:
                        meta["hist_until"] = now
                elif kind == "full":
                    if reached < b0 or done:
                        meta["hist_until"] = now
                        meta["hist_from"] = int(a0 if done else reached)
                else:
                    meta["hist_from"] = int(a0 if done else min(h_from, reached))
        elif ex in ("upbit", "bithumb") and not hist_only:
            try:
                pairs = hist_pairs_upbitlike(cl, _hist_depth(now), now)
            except ApiError as e:
                if e.fatal or not hasattr(e, "partial"):
                    raise
                pairs = set(e.partial)
                hist_note = f"입금 이력 일부만 조회: {str(e)[:80]}"
            hp = {tuple(p) for p in meta.get("hist_pairs") or []} | pairs | set(cands["pairs"])
            meta["hist_pairs"] = sorted([list(p) for p in hp])
        if not hist_only:
            if ex in ("upbit", "bithumb"):
                o, ck, er = _collect_upbitlike(cl, cands, meta, only)
                ck = ck | (cands["all"] if only is None else set(only))
            elif ex == "binance":
                o, ck, er = _collect_binance(cl, cands, store, only, obs)
            else:
                pool = _pool(ex, cands)
                pool = (pool | {str(x.get("currency") or "").upper() for x in obs}) - FIAT
                o, ck, er = _collect_percoin(ex, cl, (set(only) & pool) if only is not None else pool)
            obs.extend(o)
            checked |= ck
            errs.extend(er)
    except ApiError as e:
        fatal = common.redact_secret_text(str(e))[:200]
    except Exception as e:
        fatal = f"{type(e).__name__}: {common.redact_secret_text(str(e))[:160]}"
    res["calls"] = cl.calls
    with _LOCK:
        store2 = load_store()
        meta2 = store2["exchanges"].setdefault(ex, {})
        for k in ("hist_from", "hist_until", "hist_pairs"):
            if k in meta and fatal is None:
                meta2[k] = meta[k]
        m = merge(store2, ex, obs, now) if obs else {"added": 0, "updated": 0}
        res["added"] = m["added"]
        meta2.pop("running", None)
        meta2["last_attempt"] = now
        meta2["last_reason"] = reason
        meta2["calls"] = cl.calls
        if fatal is None:
            res["ok"] = True
            meta2["key_fp"] = _key_fp(ex, env)
            meta2["last_ok"] = now
            if only is None and not hist_only:
                meta2["last_full"] = now
                meta2["checked"] = sorted(checked)
            elif only is not None:
                meta2["checked"] = sorted(set(meta2.get("checked") or []) | set(only))
            meta2["fail_count"] = 0
            meta2["next_try"] = 0
            meta2["last_error"] = common.redact_secret_text(hist_note) if hist_note else hist_note
            meta2["partial_errors"] = len(errs)
            meta2["partial_sample"] = [common.redact_secret_text(x) for x in errs[:5]]
        else:
            fc = int(meta2.get("fail_count") or 0) + 1
            meta2["fail_count"] = fc
            meta2["next_try"] = now + BACKOFF[min(fc, len(BACKOFF)) - 1]
            meta2["last_error"] = fatal
            res["errors"].append(fatal)
        meta2["count"] = sum(1 for r in store2["records"] if r["exchange"] == ex)
        save_store(store2)
        try:
            write_compat(store2, ex, now)
        except OSError as e:
            log.warning("exf_addrs_%s 호환 파일 쓰기 실패: %s", ex, e)
    res["errors"] += errs[:5]
    res["hist"] = hist_note
    lvl = logging.INFO if fatal is None else logging.WARNING
    log.log(lvl, "입금주소 %s(%s): %s · 관측 %d · 신규 %d · 총 %d · 콜 %d%s", ex, reason,
            "성공" if fatal is None else "실패(기존 보존) " + fatal[:120], len(obs), res["added"],
            meta2["count"], cl.calls, f" · 개별 오류 {len(errs)}" if errs else "")
    return res


def request_refresh(ex: str = "all") -> dict:
    p = req_path()
    with _LOCK:
        try:
            d = common.read_json(p, {}) or {}
        except SystemExit:
            d = {}
        rq = d.get("requests") if isinstance(d.get("requests"), dict) else {}
        now = round(time.time(), 3)
        for e in (EXCHANGES if ex == "all" else (ex,)):
            rq[e] = now
        common.atomic_write_json(p, {"requests": rq})
    return {"requested": list(EXCHANGES) if ex == "all" else [ex], "ts": now}


def notify(ex: str, what: str = "deposit") -> None:
    _NOTIFY[ex] = int(time.time())


def _requests() -> dict:
    try:
        d = common.read_json(req_path(), {}) or {}
    except SystemExit:
        return {}
    r = d.get("requests") if isinstance(d, dict) else None
    return r if isinstance(r, dict) else {}


def due(ex: str, env: dict, store: dict, now: int, cand_cache: dict):
    meta = store["exchanges"].get(ex) or {}
    req = float(_requests().get(ex) or 0)
    if int(meta.get("next_try") or 0) > now:
        return None
    if req > float(meta.get("req_done") or 0):
        return ("request", None, False, req)
    if not meta.get("last_full") or meta.get("key_fp") != _key_fp(ex, env):
        return ("first" if not meta.get("last_full") else "key_changed", None, False, 0)
    if now - int(meta["last_full"]) >= DAY:
        return ("daily", None, False, 0)
    if int(_NOTIFY.get(ex) or 0) > int(meta.get("last_attempt") or 0):
        return ("new_deposit", None, True, 0)
    if now - int(cand_cache.get(ex, 0)) >= CAND_EVERY:
        cand_cache[ex] = now
        c = candidates(ex, store)
        pool = _pool(ex, c)
        new = pool - set(meta.get("checked") or [])
        if ex in ("upbit", "bithumb"):
            hp = {tuple(p) for p in meta.get("hist_pairs") or []}
            newp = {p for p in c["pairs"] if tuple(p) not in hp}
            if newp:
                return ("new_network", {p[0] for p in newp} | new, False, 0)
        if new:
            return ("new_currency", new, False, 0)
    return None


def tick(env_fn, cand_cache: dict) -> list:
    out = []
    env = env_fn() or {}
    now = int(time.time())
    for ex in EXCHANGES:
        if not all(env.get(k) for k in NEED[ex]):
            continue
        try:
            store = load_store()
            d = due(ex, env, store, now, cand_cache)
        except Exception as e:
            log.warning("입금주소 %s 판정 실패: %s", ex, common.redact_secret_text(repr(e))[:120])
            continue
        if not d:
            continue
        reason, only, hist_only, req_ts = d
        if reason == "new_network" and ex in ("upbit", "bithumb"):
            with _LOCK:
                st = load_store()
                m = st["exchanges"].setdefault(ex, {})
                c = candidates(ex, st)
                m["hist_pairs"] = sorted({tuple(p) for p in m.get("hist_pairs") or []} | set(c["pairs"]))
                m["hist_pairs"] = [list(p) for p in m["hist_pairs"]]
                save_store(st)
        r = refresh(ex, env, reason, only=only, hist_only=hist_only)
        if req_ts:
            with _LOCK:
                st = load_store()
                st["exchanges"].setdefault(ex, {})["req_done"] = req_ts
                save_store(st)
        out.append(r)
    return out


_THREAD = {"t": None}


def start_background(env_fn) -> threading.Thread:
    if _THREAD["t"] and _THREAD["t"].is_alive():
        return _THREAD["t"]
    try:
        with _LOCK:
            n9 = common.scrub_secret_file(store_path(), ("exchanges",))
        if n9:
            log.info("입금주소 저장소: 수정 전 오류 문구 %d칸 비밀값 가림", n9)
    except Exception:
        pass

    def loop():
        cache = {}
        time.sleep(3)
        while True:
            try:
                tick(env_fn, cache)
            except Exception as e:
                log.warning("입금주소 스레드 예외(계속): %s", common.redact_secret_text(repr(e))[:160])
            time.sleep(TICK)
    t = threading.Thread(target=loop, name="tj-depaddr", daemon=True)
    t.start()
    _THREAD["t"] = t
    return t


def _manual_rows() -> list:
    try:
        mt = os.path.getmtime(common.CONFIG_PATH)
    except OSError:
        return []
    if _CFG_CACHE["mt"] != mt:
        try:
            cfg = common.read_json(common.CONFIG_PATH, {}) or {}
        except SystemExit:
            cfg = {}
        rows = []
        hl9 = cfg.get("hyperliquid") if isinstance(cfg.get("hyperliquid"), dict) else {}
        if hl9.get("spot"):
            rows.append({"exchange": "hyperliquid", "currency": "USDC", "network": "arbitrum", "address": HL_BRIDGE2, "tag": "",
                         "chain": "arbitrum", "sources": ["manual", "static"]})
        for e in cfg.get("exchange_addresses") or []:
            if isinstance(e, dict) and e.get("address"):
                rows.append({"exchange": e.get("exchange") or "?", "currency": str(e.get("currency") or "").upper(),
                             "network": e.get("chain") or "", "address": e["address"],
                             "tag": str(e.get("memo") or "") if e.get("memo") not in (None, "—") else "",
                             "chain": e.get("chain") if e.get("chain") in EVM_CHAINS | {"sol"} else
                             chain_of(e.get("chain")), "sources": ["manual"]})
        _CFG_CACHE.update(mt=mt, rows=rows)
    return _CFG_CACHE["rows"]


def _load_index(path: str | None = None):
    p = path or store_path()
    try:
        mt = os.path.getmtime(p)
    except OSError:
        mt = None
    with _LOCK:
        c = _CACHE
        if c["idx"] is not None and c["path"] == p and (
                (mt is not None and c["mt"] == mt) or (mt is None and c["mt"] is None and time.time() - c.get("at", 0) < 60)):
            return c["idx"], c.get("exmeta") or {}
        exmeta = {}
        if mt is not None:
            try:
                st = load_store(p)
                recs, exmeta = st["records"], st.get("exchanges") or {}
            except RuntimeError:
                recs = []
        else:
            tmp = _empty_store()
            _import_compat(tmp, int(time.time()))
            recs = tmp["records"]
        idx = {}
        for r in recs:
            idx.setdefault(norm_addr(r["address"]), []).append(r)
        c.update(mt=mt, idx=idx, path=p, exmeta=exmeta, at=time.time())
        return idx, exmeta


def _index(path: str | None = None) -> dict:
    return _load_index(path)[0]


def _is_current(r: dict, exmeta: dict) -> bool:
    lf = int((exmeta or {}).get("last_full") or 0)
    la = int(r.get("last_seen_api") or 0)
    return bool(la) and (not lf or la >= lf)


def lookup_all(chain, address, tag=None, currency=None, include_manual=True) -> list:
    a = norm_addr(address)
    if not a:
        return []
    idx, exmeta = _load_index()
    rows = list(idx.get(a) or [])
    if include_manual:
        rows += [r for r in _manual_rows() if norm_addr(r["address"]) == a]
    if not rows:
        return []
    q_chain = str(chain or "").strip().lower() or None
    q_tag = str(tag).strip() if tag not in (None, "") else None
    out = []
    for r in rows:
        rt = str(r.get("tag") or "").strip()
        if rt and q_tag is not None and rt != q_tag:
            continue
        rc = r.get("chain") or chain_of(r.get("network"), r.get("currency"), r.get("address"))
        if q_chain and rc == q_chain:
            match, sc = "exact", 3
        elif q_chain and q_chain != "sol" and is_evm(r["address"]) and (rc is None or rc in EVM_CHAINS):
            match, sc = "family", 2
        elif q_chain and rc and rc != q_chain:
            match, sc = "other_chain", 0
        else:
            match, sc = "address", 1
        if currency and str(r.get("currency") or "").upper() == str(currency).upper():
            sc += 0.5
        cur = "manual" in (r.get("sources") or []) or _is_current(r, exmeta.get(r["exchange"]))
        sc += 0.2 if cur else 0
        out.append((sc, {"exchange": r["exchange"], "currency": r.get("currency") or "", "network": r.get("network") or "",
                         "chain": rc, "address": r["address"], "tag": rt, "match": match,
                         "tag_match": (True if (rt and q_tag == rt) else None),
                         "tag_required": bool(rt) and q_tag is None, "current": cur,
                         "first_seen": r.get("first_seen"), "last_seen": r.get("last_seen"),
                         "first_used": r.get("first_used"), "last_used": r.get("last_used"),
                         "sources": list(r.get("sources") or [])}))
    out.sort(key=lambda x: -x[0])
    return [o for s, o in out if s > 0] + [o for s, o in out if s <= 0]


def lookup(chain, address, tag=None, currency=None, include_manual=True):
    rows = [r for r in lookup_all(chain, address, tag, currency, include_manual) if r["match"] != "other_chain"]
    if not rows:
        return None
    best = dict(rows[0])
    exs = sorted({r["exchange"] for r in rows})
    best["currencies"] = sorted({r["currency"] for r in rows if r["exchange"] == best["exchange"] and r["currency"]})
    best["ambiguous"] = len(exs) > 1
    best["exchanges"] = exs
    return best


def hint_index() -> dict:
    out = {}
    for r in _manual_rows():
        if "static" in (r.get("sources") or []):
            out.setdefault(norm_addr(r["address"]), []).append((r["exchange"], EX_NAME.get(r["exchange"], r["exchange"]) + " 브릿지(공용 입금 컨트랙트)"))
    for a, recs in _index().items():
        seen = set()
        for r in recs:
            ex = r["exchange"]
            lab = EX_NAME.get(ex, ex) + (" 입금주소(메모 필요)" if r.get("tag") else " 입금주소(내 계정)")
            if (ex, lab) in seen:
                continue
            seen.add((ex, lab))
            out.setdefault(a, []).append((ex, lab))
    return out


def summary(env: dict | None = None) -> dict:
    try:
        st = load_store() if os.path.exists(store_path()) else _empty_store()
    except RuntimeError as e:
        return {"error": common.safe_err(e)}
    rq = _requests()
    now = time.time()
    out = {}
    for ex in EXCHANGES:
        recs = [r for r in st["records"] if r["exchange"] == ex]
        m = st["exchanges"].get(ex) or {}
        if not recs and not m and not (env and all(env.get(k) for k in NEED[ex])):
            continue
        running = m.get("running")
        out[ex] = {"count": len(recs), "addresses": len({norm_addr(r["address"]) for r in recs}),
                   "currencies": len({r.get("currency") for r in recs}),
                   "current": sum(1 for r in recs if _is_current(r, m)),
                   "fromHistory": sum(1 for r in recs if "history" in (r.get("sources") or [])),
                   "lastRefresh": m.get("last_ok"), "lastFull": m.get("last_full"),
                   "lastError": common.redact_secret_text(m.get("last_error")),
                   "lastAttempt": m.get("last_attempt"),
                   "running": bool(running and now - float(running) < 1800),
                   "requested": float(rq.get(ex) or 0) > float(m.get("req_done") or 0),
                   "nextTry": m.get("next_try") or None}
    return out


def deposit_rows(limit_per_ex: int = 12) -> list:
    rows, seen = [], set()
    try:
        recs = load_store()["records"] if os.path.exists(store_path()) else []
    except RuntimeError:
        return []
    per = {}
    for r in recs:
        ch = r.get("chain")
        evm = is_evm(r["address"])
        if not (evm or ch == "sol") or r.get("tag"):
            continue
        k = (r["exchange"], norm_addr(r["address"]))
        if k in seen:
            per[k]["n"] += 1
            continue
        seen.add(k)
        per[k] = {"ex": EX_NAME.get(r["exchange"], r["exchange"]), "net": "EVM" if evm else "SOL",
                  "addr": r["address"], "n": 1, "exk": r["exchange"]}
    cnt = {}
    for k, v in per.items():
        cnt[v["exk"]] = cnt.get(v["exk"], 0) + 1
        if cnt[v["exk"]] > limit_per_ex:
            continue
        rows.append({"ex": v["ex"], "net": v["net"], "addr": v["addr"],
                     "memo": f"자동 수집 · {v['n']}개 통화", "ok": True})
    return rows


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [tj-depaddr] %(message)s")
    import ex_foreign as _xf
    env0 = _xf._env()
    env0.update({k: v for k, v in os.environ.items() if k.startswith(("TJ_", "UPBIT_"))})
    for ex0 in (sys.argv[1:] or EXCHANGES):
        if all(env0.get(k) for k in NEED.get(ex0, ("?",))):
            r0 = refresh(ex0, env0, "cli")
            print(ex0, "ok" if r0["ok"] else "fail", "added", r0["added"], "calls", r0["calls"])
