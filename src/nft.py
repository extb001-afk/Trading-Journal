from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import logging
import math
import os
import re
import secrets
import threading
import time
import unicodedata
import urllib.parse
from datetime import datetime, timedelta, timezone

import alert_watch
import bf_engine
import cgplan
import common
import spamguard

log = logging.getLogger("tj-web")
KST = timezone(timedelta(hours=9))
SCHEMA = 1
HOLD_PATH = os.path.join(common.STATE_DIR, "nft_holdings.json")
FP_PATH = os.path.join(common.STATE_DIR, "nft_fp.json")
PREFS_PATH = os.path.join(common.STATE_DIR, "nft_prefs.json")
BUDGET_PATH = os.path.join(common.STATE_DIR, "nft_budget.json")
STATE_FILES = ("nft_holdings.json", "nft_fp.json", "nft_prefs.json", "nft_budget.json")

SCAN_EVERY = 86400
FP_EVERY = 3600
CAND_FP_EVERY = 86400
NEG_TTL = 7 * 86400
UNSUP_TTL = 86400
ACQ_RETRY = 86400
ACQ_TRIES = 3
FIRST_DELAY = 600
MIN_GAP = 1.0
MASS_N = 20
MASS_HOLDERS = 50000
STALE_SEC = 3 * 3600
MAX_HIST = 400
MAX_WATCH = 50
MAX_PREF_KEYS = 2000
PAGES_MAX = 20
ES_PAGE = 1000
ES_MAX_ROWS = 30000
ES_PAGES_PER_BLOCKRUN = 10
ACQ_PER_SCAN = 40
PAIRS_PER_CYCLE = 60
PAIR_RETRY = 3600
LABEL_MAX = 60
CG_KEY_ENV = "TJ_COINGECKO_KEY"
CG_KEY_HDR = "x-cg-demo-api-key"
CG_KEY_HOST = "api.coingecko.com#key"
CG_PRO_HOST = "pro-api.coingecko.com"
CG_PRO_HDR = cgplan.HDR["pro"]
KEY_BAD_RETRY = 6 * 3600
NOTICE_BACKLOG = 20
NOTIFY_EVERY = 86400
CG_KEY_URL = "https://www.coingecko.com/en/developers/dashboard"
NOTICE_SLOW = ("NFT 바닥가 조회가 코인게코 무료 호출 제한에 걸려 늦어지고 있어요 — 지금은 몇 시간 걸릴 수 있어요. "
               "설정 › 연결·키에 오픈시 API 키나 코인게코 무료 API 키(데모)를 넣으면 금방 채워져요 — "
               "오픈시 키가 있으면 오픈시를 먼저 써서 작은 컬렉션까지 더 원활하게 추적해요.")
OS_KEY_URL = "https://docs.opensea.io/reference/api-keys"
NOTICE_KEY_BAD = "코인게코 키가 맞지 않아요 — 설정 › 연결·키에서 다시 넣어 주세요"

BUDGET = {
    "coingecko": (30, 3600),
    "coingecko_key": ((24, 60), (260, 86400)),
    "coingecko_info": (cgplan.INFO_PER_DAY, 86400),
    "magiceden": (60, 3600),
    "opensea": (450, 3600),
    "blockscout": (800, 86400),
    "etherscan": (300, 86400),
    "helius": (120, 86400),
    "pairs": (60, 3600),
}
CG_LANES = ("live", "past", "nft")
CG_FLOOR = {"live": 0.5, "nft": 0.3, "past": 0.2}
CG_LIVE_MIN = 0.25
CG_ACTIVE_S = 7200
CG_G = "coingecko_key"
CG_L = {ln: "cgk_" + ln for ln in CG_LANES}
for _ln in CG_LANES:
    BUDGET[CG_L[_ln]] = ((130 if _ln == "live" else 78 if _ln == "nft" else 52, 86400),)
HOST_GAP = {"blockscout": 4.5, "coingecko_key": 2.5}
HOST_POLICY = {
    "api.coingecko.com": {"rate": 0.1, "burst": 1, "conc": 1},
    CG_KEY_HOST: {"rate": 0.4, "burst": 1, "conc": 1},
    CG_PRO_HOST: {"rate": 1.0, "burst": 1, "conc": 1},
    "api-mainnet.magiceden.dev": {"rate": 0.5, "burst": 1, "conc": 1},
    "api.opensea.io": {"rate": 1.0, "burst": 1, "conc": 1},
}
for _h, _p in HOST_POLICY.items():
    bf_engine.HOST_POLICIES.setdefault(_h, _p)

LEGACY_NFT = {
    "eth": {
        "0xb47e3cd837ddf8e4c57f05d70ab865de6e193bbb": ("CryptoPunks", "PUNK"),
        "0x60cd862c9c687a9de49aecdc3a99b74a4fc54ab6": ("MoonCatRescue", "MCAT"),
    },
}

AB_NAME = "Art Blocks"
AB_DIV = 1_000_000
AB_CONTRACTS = {
    "eth": {
        "0x059edd72cd353df5106d2b9cc5ab83a52287ac3a": "V0",
        "0xa7d8d9ef8d8ce8992df33d8b8cf4aebabd5bd270": "V1",
        "0x99a9b7c1116f9ceeb1652de04d5969cce509b069": "V3",
        "0xab0000000000aa06f89b268d604a9c1c41524ac6": "V3.2",
        "0xab00000000002ade39f58f9d8278a31574ffbe77": "V3.2 Flex",
        "0x942bc2d3e7a589fe5bd4a5c6ef9727dfd82f5c8a": "Explorations",
    },
}
SER_RE = re.compile(r"^([a-z0-9_\-]{2,24}):(0x[0-9a-f]{40})/p(\d{1,9})$")
TID_RE = re.compile(r"^\d{1,40}$")
OS_TRACK_EVERY = 900
OS_CAND_EVERY = 6 * 3600
LAST_SALE_EVERY = 86400
THIN_FULL_DAYS = 90
THIN_MAX_DAYS = 365
AB_MIG_V = 1
ERR_RETRY = 1800
BAK_SUFFIX = ".bak_ab1006"
AB_BLOCK_UNTIL = 253402300799.0

CG_HOST = "https://api.coingecko.com"
ME_HOST = "https://api-mainnet.magiceden.dev"
OS_HOST = "https://api.opensea.io"
ES_API = "https://api.etherscan.io/v2/api"
HELIUS_RPC = "https://mainnet.helius-rpc.com/?api-key="

CG_PLATFORM = {"eth": "ethereum", "arbitrum": "arbitrum-one", "base": "base", "optimism": "optimistic-ethereum",
               "polygon": "polygon-pos", "bsc": "binance-smart-chain", "avalanche": "avalanche", "blast": "blast", "abstract": "abstract",
               "berachain": "berachain", "hyperevm": "hyperevm", "robinhood": "robinhood", "kaia": "klay-token", "apechain": "apechain",
               "ronin": "ronin"}
ES_CHAINID = {"eth": 1, "arbitrum": 42161, "polygon": 137, "base": 8453, "optimism": 10, "scroll": 534352, "zksync": 324,
              "gnosis": 100, "bsc": 56, "avalanche": 43114, "blast": 81457, "abstract": 2741, "berachain": 80094,
              "hyperevm": 999}
ES_PROBE_ALL = ("hyperevm",)
NATIVE_SYM = {"eth": "ETH", "base": "ETH", "arbitrum": "ETH", "optimism": "ETH", "scroll": "ETH", "zksync": "ETH", "blast": "ETH",
              "abstract": "ETH", "polygon": "POL", "bsc": "BNB", "gnosis": "XDAI", "avalanche": "AVAX", "berachain": "BERA",
              "hyperevm": "HYPE", "kaia": "KAIA", "sol": "SOL"}
OS_CHAIN = {"eth": "ethereum", "arbitrum": "arbitrum", "base": "base", "optimism": "optimism", "polygon": "matic",
            "zksync": "zksync", "avalanche": "avalanche", "blast": "blast", "abstract": "abstract", "berachain": "berachain"}
EXPLORER = {"eth": "https://etherscan.io/token/", "base": "https://basescan.org/token/", "arbitrum": "https://arbiscan.io/token/",
            "optimism": "https://optimistic.etherscan.io/token/", "polygon": "https://polygonscan.com/token/",
            "bsc": "https://bscscan.com/token/", "scroll": "https://scrollscan.com/token/", "zksync": "https://era.zksync.network/token/",
            "gnosis": "https://gnosisscan.io/token/", "sol": "https://solscan.io/token/", "hyperevm": "https://hyperevmscan.io/token/",
            "avalanche": "https://snowtrace.io/token/", "blast": "https://blastscan.io/token/", "berachain": "https://berascan.com/token/",
            "abstract": "https://abscan.org/token/"}

ZERO = "0x" + "0" * 40
TOPIC_TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
TOPIC_1155_SINGLE = "0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62"
TOPIC_1155_BATCH = "0x4a39dc06d4c0dbc64b70af90fd698a233a518aa5d07e595d983b8c0526c8f7fb"
ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
TXH_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
SOL_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
SIG_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{64,90}$")
ME_SYM_RE = re.compile(r"^[A-Za-z0-9_\-]{1,80}$")
OS_SLUG_RE = re.compile(r"^[a-z0-9_\-]{1,100}$")
CHAIN_RE = re.compile(r"^[a-z0-9_\-]{2,24}$")
KEY_RE = re.compile(r"^[a-z0-9_\-]{2,24}:[A-Za-z0-9/_.\-]{2,120}$")
CTRL_RE = re.compile(r"[\x00-\x1f\x7f​-‏‪-‮⁦-⁩]")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MARKET_RE = re.compile(r"fulfill|buy|purchase|execute|match|take|sweep|swap|order", re.I)
LP_NAME_RE = re.compile(r"positions?\s*nft|UNI-V[34]-POS|slipstream|whirlpool\s*position|concentrated\s*liquidity|\bCL-POS\b", re.I)

_LURE_NAME = re.compile(r"(https?:|www\.|t\.me\b|t\.ly\b|bit\.ly\b|telegram|discord\.gg|"
                        r"(?<![\w.])[a-z0-9][a-z0-9-]{1,62}\s?\.\s?(?:" + spamguard.LURE_TLD + r")(?![\w-])|"
                        r"\bclaim|\bvisit\b|\breward|\bairdrop|\bvoucher|\beligib|\bredeem|\bbonus|\bgift|🎁|✅|"
                        r"\$\s?\d|\d[\d,.]*\s?\$|^\W{0,3}\$\s?[A-Za-z]|\bwin\b|\bfree\b|空投|免费|返佣|@\w{3,}bot\b)", re.I)
_LURE_DESC = re.compile(r"(https?:|www\.|t\.me\b|telegram|"
                        r"(?<![\w.])[a-z0-9][a-z0-9-]{1,62}\s?[.․•]\s?(?:" + spamguard.LURE_TLD + r")(?![\w-])|"
                        r"\bclaim|\bvisit\b|\breward|\bairdrop|\bvoucher|\beligib|\bredeem|\bbonus|\bgift|🎁|"
                        r"\$\s?\d|receive\s+your|congratulations|\bwin\b|open\s+it\s+now)", re.I)

REASON_KO = {
    "priced": "바닥가·거래량 있음",
    "promoted": "직접 추적에 넣음",
    "price_no_volume": "바닥가는 있는데 최근 거래량 없음",
    "lure_but_priced": "이름이 수상하지만 바닥가·거래량 있음",
    "bought_no_price": "돈 주고 샀는데 시세 없음",
    "self_no_price": "직접 민트·수령했는데 시세 없음",
    "internal_no_price": "내 다른 지갑에서 옮겨 옴 · 시세 없음",
    "checking": "들어온 경위 확인 중",
    "acq_unknown": "들어온 경위를 확인 못 함 · 시세 없음",
    "rep_scam": "탐색기 평판: 스캠",
    "lure": "링크·보상 유도 이름",
    "unicode": "사칭 문자(보이지 않는 글자·전각·수학 글꼴·혼용)",
    "desc_lure": "설명에 링크·보상 유도 · 시세 없음",
    "mass_airdrop": "대량 에어드랍(한 번에 여러 지갑) · 시세 없음",
    "mass_holders": "보유자 5만+ · 시세 없음(대량 배포)",
    "free_noprice": "남이 공짜로 보냄 · 시세 없음",
    "owner_notspam": "직접 '정상으로' 옮김 · 시세 없음",
    "partial_history": "전송 기록이 너무 많아 개수 미확정 — 합계에 안 넣음",
    "thin": "거래 뜸 — 최근 거래가 있어 바닥가로 평가",
    "thin_old": "거래 뜸 — 마지막 거래 90일+ · 평가는 하되 총자산에선 뺌",
    "platform_airdrop": "알려진 플랫폼 계약 · 한 번에 여러 지갑으로 발송(경매 낙찰분 등) — 시세 확인",
    "platform_received": "알려진 플랫폼 계약 · 남이 보냄 — 시세 확인",
    "ab_split": "아트블럭 — 시리즈별로 나누는 중(다음 발견 때)",
}
ACQ_KO = {"bought": "구매", "mint_paid": "유료 민트", "mint_free": "무료 민트(직접)", "claim": "직접 수령(무료)",
          "internal": "내 지갑 간 이동", "received": "남이 보냄(무료)", "airdrop_mass": "대량 에어드랍", "unknown": "확인 안 됨"}
SELF_KINDS = ("bought", "mint_paid", "mint_free", "claim")
SRC_KO = {"cg": "코인게코", "me": "매직에덴", "os": "오픈시"}


class StoreError(Exception):
    pass


def _now() -> float:
    return time.time()


def today_iso(now: float | None = None) -> str:
    return datetime.fromtimestamp(now if now is not None else _now(), KST).strftime("%Y-%m-%d")


def _fin(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _num(v):
    if isinstance(v, bool) or v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and abs(x) < 1e18 else None


def _jsafe(o):
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _jsafe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsafe(v) for v in o]
    return o


def short(a) -> str:
    a = str(a or "")
    return (a[:6] + "…" + a[-4:]) if len(a) > 14 else a


def _txt(v, lim=120) -> str:
    return CTRL_RE.sub("", str(v or ""))[:lim]


def _h(o) -> str:
    if isinstance(o, dict):
        o = o.get("hash")
    s = str(o or "").lower()
    return s if ADDR_RE.match(s) else ""


def _https(u, lim=400):
    u = str(u or "")
    return u if u.startswith("https://") and len(u) <= lim and not CTRL_RE.search(u) else None


def ab_ver(chain, ca):
    return (AB_CONTRACTS.get(str(chain or "")) or {}).get(str(ca or "").lower())


def ser_key(chain, ca, tid):
    ca = str(ca or "").lower()
    if not ab_ver(chain, ca):
        return None
    t = str(tid if tid is not None else "").strip()
    if not TID_RE.match(t):
        return None
    return f"{chain}:{ca}/p{int(t) // AB_DIV}"


def ser_parse(key):
    m = SER_RE.match(str(key or ""))
    if not m or not ab_ver(m.group(1), m.group(2)):
        return None
    return m.group(1), m.group(2), int(m.group(3))


def _pref_keys(prefs) -> set:
    p = prefs if isinstance(prefs, dict) else {}
    out = set()
    for fld in ("hidden", "promoted", "notspam"):
        v = p.get(fld)
        out |= {k for k in (v if isinstance(v, list) else []) if isinstance(k, str)}
    for w in p.get("watch") if isinstance(p.get("watch"), list) else []:
        if not isinstance(w, dict):
            continue
        if isinstance(w.get("key"), str):
            out.add(w["key"])
        if isinstance(w.get("chain"), str) and isinstance(w.get("ca"), str):
            out.add(f"{w['chain']}:{w['ca']}")
    ab = p.get("abinh") if isinstance(p.get("abinh"), dict) else {}
    for book in ab.values():
        for par, kids in (book.items() if isinstance(book, dict) else ()):
            if isinstance(par, str):
                out.add(par)
            out |= {k for k in (kids if isinstance(kids, list) else []) if isinstance(k, str)}
    return out


def ab_parent_key(key) -> bool:
    k = str(key or "")
    if ":" not in k:
        return False
    c, a = k.split(":", 1)
    return bool(ADDR_RE.match(a)) and bool(ab_ver(c, a))


def tid_in(tid, proj) -> bool:
    t = str(tid if tid is not None else "")
    return bool(TID_RE.match(t)) and int(t) // AB_DIV == int(proj)


def is_platform(col: dict) -> bool:
    col = col or {}
    return bool(ab_ver(col.get("chain"), col.get("pca") or col.get("ca")))


def col_ab_parent(col: dict) -> bool:
    col = col or {}
    return col.get("proj") is None and bool(ADDR_RE.match(str(col.get("ca") or ""))) and bool(ab_ver(col.get("chain"), col.get("ca")))


def ser_name(mname, proj=None) -> str:
    s = re.sub(r"\s*#\s*\d+\s*$", "", _txt(mname, 120)).strip()
    return s or (f"{AB_NAME} #{proj}" if proj is not None else AB_NAME)


VOL_FRESH_DAYS = 7


def _obs_age(rec, now):
    at = _num(rec.get("at")) if isinstance(rec, dict) else None
    if at is None or at <= 0 or at > now + 3600:
        return None
    return max(0.0, now - at) / 86400


def last_trade(rec, now=None):
    if not isinstance(rec, dict):
        return None
    now = _now() if now is None else float(now)
    age = _obs_age(rec, now)
    win, n = None, None
    if age is not None:
        if (_num(rec.get("vol24")) or 0) > 0 or (_num(rec.get("sales24")) or 0) > 0:
            win = 1
        elif (_num(rec.get("vol7")) or 0) > 0 or (_num(rec.get("sales7")) or 0) > 0:
            win, n = 7, int(_num(rec.get("sales7")) or 0) or None
        elif (_num(rec.get("sales30")) or 0) > 0:
            win, n = 30, int(_num(rec.get("sales30")))
    la = rec.get("last") if isinstance(rec.get("last"), dict) else {}
    at = _num(la.get("at"))
    ex = (max(0.0, now - at) / 86400) if (at and at > 0 and at <= now + 3600) else None
    wb = (win + age) if win is not None else None
    if ex is not None and (wb is None or ex <= wb):
        out = {"px": _num(la.get("px")), "sym": la.get("sym"), "days": int(ex), "exact": True, "age_days": ex}
        if n:
            out["n"] = n
        return out
    if wb is None:
        return None
    w = win + int(age)
    out = {"days": w, "exact": False, "within": w, "age_days": wb}
    if n:
        out["n"] = n
    return out


def atomic_write(path: str, obj) -> None:
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, ".nft_%s_%s.tmp" % (os.getpid(), secrets.token_hex(4)))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        try:
            dfd = os.open(d, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_cache(path, empty):
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return empty()
    if not isinstance(d, dict) or not isinstance(d.get("v"), int) or d["v"] > SCHEMA:
        return empty()
    base = empty()
    for k, v in base.items():
        x = d.get(k)
        ok = _fin(x) if isinstance(v, (int, float)) else isinstance(x, type(v))
        if not ok:
            d[k] = v
    return d


def empty_hold() -> dict:
    return {"v": SCHEMA, "at": 0, "pairs": {}, "cols": {}, "acq": {}, "scan": {}}


def empty_fp() -> dict:
    return {"v": SCHEMA, "fp": {}, "neg": {}, "map": {}, "hist": {}, "hosts": {}, "chk": {}, "cgkey": {}, "notify": {}, "retry": {}}


def empty_prefs() -> dict:
    return {"v": SCHEMA, "promoted": [], "hidden": [], "watch": [], "notspam": [], "include_in_total": False, "updated": 0}


def load_prefs(path: str | None = None) -> dict:
    path = path or PREFS_PATH
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        return empty_prefs()
    except (OSError, ValueError) as e:
        raise StoreError("NFT 설정 파일을 읽지 못했어요(손상) — 덮어쓰지 않았어요") from e
    if not isinstance(d, dict) or not isinstance(d.get("v"), int) or d["v"] > SCHEMA:
        raise StoreError("NFT 설정 파일 형식·버전이 맞지 않아요 — 덮어쓰지 않았어요")
    for k in ("promoted", "hidden", "watch"):
        if not isinstance(d.get(k), list):
            raise StoreError("NFT 설정 파일 형식이 맞지 않아요 — 덮어쓰지 않았어요")
    if not isinstance(d.get("notspam", []), list):
        raise StoreError("NFT 설정 파일 형식이 맞지 않아요 — 덮어쓰지 않았어요")
    d.setdefault("notspam", [])
    d["include_in_total"] = d.get("include_in_total") is True
    return d


def registered(cfg: dict):
    evm, sol = {}, {}
    for w in (cfg or {}).get("wallets") or []:
        if not isinstance(w, dict):
            continue
        a = str(w.get("address") or "")
        t = w.get("type", "evm") or "evm"
        if t in ("evm", "bsc_rpc") and ADDR_RE.match(a):
            evm.setdefault(a.lower(), w.get("label") or "")
        elif t == "sol" and SOL_RE.match(a):
            sol.setdefault(a, w.get("label") or "")
    return evm, sol


def _off_chains(cfg: dict) -> set:
    cfg = cfg if isinstance(cfg, dict) else {}
    off = set(cfg.get("_disabled_chains") or [])
    off.update(c for c, cc in (cfg.get("chains") or {}).items() if isinstance(cc, dict) and not common.chain_enabled(c, cc))
    return off


def evm_targets(cfg: dict, gate: dict | None = None) -> list:
    cfg = cfg or {}
    evm, _sol = registered(cfg)
    chains = cfg.get("chains") or {}
    pairs = set()
    for w in cfg.get("wallets") or []:
        if not isinstance(w, dict):
            continue
        a = str(w.get("address") or "").lower()
        t = w.get("type", "evm") or "evm"
        if a in evm and t == "evm" and w.get("chain"):
            pairs.add((str(w["chain"]), a))
        elif a in evm and t == "bsc_rpc":
            pairs.add(("bsc", a))
    gp = (((gate or {}).get("pairs") or {}) if isinstance(gate, dict) else {})
    for key, ent in gp.items():
        if isinstance(ent, dict) and ent.get("active") and ":" in str(key):
            c, a = str(key).split(":", 1)
            if a.lower() in evm:
                pairs.add((c, a.lower()))
    for c in ES_PROBE_ALL:
        for a in evm:
            ent = gp.get(f"{c}:{a}")
            if not (isinstance(ent, dict) and not ent.get("active")):
                pairs.add((c, a))
    out = []
    off9 = set(cfg.get("_disabled_chains") or [])
    for c, a in sorted(pairs):
        if not CHAIN_RE.match(c):
            continue
        cc = chains.get(c) if isinstance(chains.get(c), dict) else None
        if c in off9 or (cc is not None and not common.chain_enabled(c, cc)):
            continue
        bs = None
        if cc and cc.get("blockscout") and common.chain_discovery(c, cc) != "rpc":
            u = str(cc["blockscout"]).rstrip("/")
            if u.startswith("https://"):
                bs = u
        es = None
        try:
            es = int((cc or {}).get("etherscan_chainid") or ES_CHAINID.get(c) or 0) or None
        except (TypeError, ValueError):
            es = ES_CHAINID.get(c)
        if bs or es:
            out.append((c, a, bs, es))
    return out


def is_lp(chain: str, ca: str, name, sym) -> bool:
    try:
        import lpdec
        m = (lpdec.lp_managers() or {}).get(chain) or {}
        ent = m.get(str(ca or "").lower())
        if ent and ent.get("proto") in tuple(lpdec.NFT_PROTOS) + ("stake",):
            return True
    except Exception:
        pass
    return bool(LP_NAME_RE.search(str(name or "")) or LP_NAME_RE.search(str(sym or "")))


def parse_bs_nft(d):
    if not isinstance(d, dict) or not isinstance(d.get("items"), list):
        return None, None
    out = []
    for it in d["items"]:
        if not isinstance(it, dict):
            continue
        t = it.get("token") if isinstance(it.get("token"), dict) else {}
        ca = _h(t.get("address_hash") or t.get("address"))
        if not ca:
            continue
        std = str(t.get("type") or it.get("token_type") or "")
        n = 1
        if std == "ERC-1155":
            n = _num(it.get("value"))
            n = int(n) if n and n > 0 else 1
        md = it.get("metadata") if isinstance(it.get("metadata"), dict) else {}
        out.append({"ca": ca, "name": _txt(t.get("name"), 120), "sym": _txt(t.get("symbol"), 40), "std": std[:12],
                    "holders": _num(t.get("holders_count") or t.get("holders")), "supply": _num(t.get("total_supply")),
                    "rep": _txt(t.get("reputation"), 16) or None, "id": _txt(it.get("id"), 80), "n": n,
                    "mname": _txt(md.get("name"), 120), "mdesc": str(md.get("description") or "")[:400],
                    "img": _https(it.get("image_url"))})
    npp = d.get("next_page_params")
    return out, (npp if isinstance(npp, dict) and npp else None)


def parse_bs_legacy(d, chain: str):
    if not isinstance(d, list):
        return None
    want = LEGACY_NFT.get(chain) or {}
    out = []
    for it in d:
        if not isinstance(it, dict) or not isinstance(it.get("token"), dict):
            continue
        t = it["token"]
        ca = _h(t.get("address_hash") or t.get("address"))
        if ca not in want:
            continue
        n = _num(it.get("value"))
        if n is None:
            return None
        n = int(n)
        if n <= 0:
            continue
        nm, sy = want[ca]
        out.append({"ca": ca, "name": nm, "sym": sy, "std": "pre-721", "holders": _num(t.get("holders_count") or t.get("holders")),
                    "supply": None, "rep": _txt(t.get("reputation"), 16) or None, "id": None, "n": n,
                    "mname": "", "mdesc": "", "img": None})
    return out


def parse_es_nft(rows, addr: str):
    bal, meta, first_in = {}, {}, {}
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        ca = _h(r.get("contractAddress"))
        tid = _txt(r.get("tokenID"), 80)
        if not ca or not tid:
            continue
        q = _num(r.get("tokenValue")) if r.get("tokenValue") not in (None, "") else 1.0
        q = q if q and q > 0 else 1.0
        k = (ca, tid)
        if _h(r.get("to")) == addr:
            bal[k] = bal.get(k, 0) + q
            h9 = str(r.get("hash") or "")
            if ca not in first_in and TXH_RE.match(h9):
                first_in[ca] = (h9.lower(), _h(r.get("from")))
        if _h(r.get("from")) == addr:
            bal[k] = bal.get(k, 0) - q
        meta[ca] = (_txt(r.get("tokenName"), 120), _txt(r.get("tokenSymbol"), 40), "ERC-1155" if "tokenValue" in r else "ERC-721")
    out = []
    for (ca, tid), q in bal.items():
        if q > 0:
            nm, sy, std = meta.get(ca, ("", "", "ERC-721"))
            tx9, fr9 = first_in.get(ca, (None, None))
            out.append({"ca": ca, "name": nm, "sym": sy, "std": std, "holders": None, "supply": None, "rep": None,
                        "id": tid, "n": int(q), "mname": "", "mdesc": "", "img": None, "tx": tx9, "from": fr9})
    return out


def parse_das(res):
    if not isinstance(res, dict) or not isinstance(res.get("items"), list):
        return None
    out = []
    for it in res["items"]:
        if not isinstance(it, dict) or it.get("burnt"):
            continue
        iface = str(it.get("interface") or "")
        if iface.startswith("Fungible"):
            continue
        mint = str(it.get("id") or "")
        if not SOL_RE.match(mint):
            continue
        content = it.get("content") if isinstance(it.get("content"), dict) else {}
        md = content.get("metadata") if isinstance(content.get("metadata"), dict) else {}
        grp = [g for g in (it.get("grouping") or []) if isinstance(g, dict) and g.get("group_key") == "collection"]
        coll = str(grp[0].get("group_value") or "") if grp else ""
        cm = (grp[0].get("collection_metadata") if grp else None) or {}
        cm = cm if isinstance(cm, dict) else {}
        links = content.get("links") if isinstance(content.get("links"), dict) else {}
        img = _https(links.get("image"))
        if not img:
            for f in content.get("files") or []:
                if isinstance(f, dict):
                    img = _https(f.get("cdn_uri")) or _https(f.get("uri"))
                    if img:
                        break
        comp = bool((it.get("compression") or {}).get("compressed")) if isinstance(it.get("compression"), dict) else False
        std = "cNFT" if comp else ("pNFT" if "Programmable" in iface else "NFT")
        ver = bool(grp and grp[0].get("verified") is True)
        claimed = coll if (coll and not ver and SOL_RE.match(coll)) else ""
        coll = coll if ver else ""
        out.append({"coll": coll if SOL_RE.match(coll) else "", "claimed": claimed, "mint": mint, "name": _txt(md.get("name"), 120),
                    "sym": _txt(md.get("symbol"), 40), "cname": _txt(cm.get("name"), 120), "csym": _txt(cm.get("symbol"), 40),
                    "desc": str(md.get("description") or cm.get("description") or "")[:400], "std": std, "compressed": comp,
                    "verified": ver, "img": img,
                    "frozen": bool((it.get("ownership") or {}).get("frozen")) if isinstance(it.get("ownership"), dict) else False})
    return out


def _pct(v):
    if isinstance(v, dict):
        v = v.get("native_currency", v.get("usd"))
    x = _num(v)
    return x if x is not None and abs(x) < 1e6 else None


def _cur_sym(v):
    if not isinstance(v, str):
        return None
    t = v.strip().upper()[:10]
    return t if re.search(r"[A-Z]", t) else None


def parse_cg(d):
    if not isinstance(d, dict):
        return None
    fp = d.get("floor_price") if isinstance(d.get("floor_price"), dict) else {}
    vol = d.get("volume_24h") if isinstance(d.get("volume_24h"), dict) else {}
    nat = _num(fp.get("native_currency"))
    if nat is None or nat <= 0:
        return None
    sym = _cur_sym(d.get("native_currency_symbol"))
    if not sym:
        return None
    return {"src": "cg", "native": nat, "sym": "ETH" if sym == "WETH" else sym, "usd": _num(fp.get("usd")),
            "vol24": _num(vol.get("native_currency")), "vol7": None, "sales24": _num(d.get("one_day_sales")),
            "chg24": _pct(d.get("floor_price_24h_percentage_change")), "chg7": _pct(d.get("floor_price_7d_percentage_change")),
            "listed": None, "id": _txt(d.get("id"), 80), "name": _txt(d.get("name"), 120),
            "url": ("https://www.coingecko.com/en/nft/" + urllib.parse.quote(str(d.get("id")), safe="")) if d.get("id") else None}


def parse_me_stats(d, symbol: str):
    if not isinstance(d, dict):
        return None
    fp = _num(d.get("floorPrice"))
    if fp is None or fp <= 0:
        return None
    v7 = _num(d.get("volume7d"))
    v24 = _num(d.get("volume24hr"))
    avg = _num(d.get("avgPrice24hr"))
    return {"src": "me", "native": fp / 1e9, "sym": "SOL", "usd": None, "vol24": (v24 / 1e9) if v24 else None,
            "vol7": (v7 / 1e9) if v7 else None, "sales24": 1.0 if (avg and avg > 0 and not v24) else None,
            "chg24": None, "chg7": None, "listed": _num(d.get("listedCount")), "id": symbol, "name": None,
            "url": "https://magiceden.io/marketplace/" + urllib.parse.quote(symbol, safe="")}


def parse_os_stats(d, slug: str):
    if not isinstance(d, dict) or not isinstance(d.get("total"), dict):
        return None
    tot = d["total"]
    fp = _num(tot.get("floor_price"))
    if fp is None or fp <= 0:
        return None
    iv = {str(x.get("interval")): x for x in (d.get("intervals") or []) if isinstance(x, dict)}
    sym = _cur_sym(tot.get("floor_price_symbol"))
    return {"src": "os", "native": fp, "sym": "ETH" if sym == "WETH" else sym, "usd": None,
            "vol24": _num((iv.get("one_day") or {}).get("volume")), "vol7": _num((iv.get("seven_day") or {}).get("volume")),
            "sales24": _num((iv.get("one_day") or {}).get("sales")), "chg24": None, "chg7": None, "listed": None, "id": slug,
            "sales7": _num((iv.get("seven_day") or {}).get("sales")), "sales30": _num((iv.get("thirty_day") or {}).get("sales")),
            "vol30": _num((iv.get("thirty_day") or {}).get("volume")),
            "name": None, "url": "https://opensea.io/collection/" + urllib.parse.quote(slug, safe="")}


def parse_os_nft(d):
    n = d.get("nft") if isinstance(d, dict) else None
    if not isinstance(n, dict):
        return None
    slug = str(n.get("collection") or "")
    if not OS_SLUG_RE.match(slug):
        return None
    return {"slug": slug, "ca": _h(n.get("contract")), "id": _txt(n.get("identifier"), 80), "name": _txt(n.get("name"), 120),
            "img": _https(n.get("display_image_url")) or _https(n.get("image_url")), "susp": n.get("is_suspicious") is True}


def parse_os_last_sale(d, slug=None):
    if not isinstance(d, dict) or not isinstance(d.get("asset_events"), list):
        return None
    out = None
    for ev in d["asset_events"]:
        if not isinstance(ev, dict) or str(ev.get("event_type") or "") != "sale":
            return None
        nft9 = ev.get("nft") if isinstance(ev.get("nft"), dict) else {}
        if slug is not None and str(nft9.get("collection") or "") != slug:
            return None
        at = _num(ev.get("event_timestamp")) or _num(ev.get("closing_date"))
        if not at or at <= 0:
            return None
        pay = ev.get("payment") if isinstance(ev.get("payment"), dict) else {}
        if not isinstance(pay.get("symbol"), str) or not pay["symbol"].strip():
            return None
        sym = pay["symbol"].strip().upper()[:10]
        px = None
        if sym in ("ETH", "WETH"):
            try:
                q = int(str(pay.get("quantity") or ""))
                dec = _num(pay.get("decimals"))
                cnt = _num(ev.get("quantity", 1))
                if q <= 0 or dec is None or dec != int(dec) or not 0 <= dec <= 36 or cnt is None or cnt <= 0 or cnt != int(cnt):
                    return None
                dec = int(dec)
                px = q / (10 ** dec) / int(cnt)
            except (TypeError, ValueError, OverflowError):
                return None
            if not math.isfinite(px):
                return None
        if out is None:
            out = {"at": float(at), "px": px, "sym": "ETH" if sym in ("ETH", "WETH") else sym}
    return out or {"at": None, "px": None, "sym": None}


def floor_shape(d, field, parent=None) -> bool:
    if parent is not None:
        d = d.get(parent) if isinstance(d, dict) else None
    if not isinstance(d, dict) or field not in d:
        return False
    v = d[field]
    n = _num(v)
    return v is None or (n is not None and n >= 0)


def id_match(d, field, want, norm=str) -> str:
    if not isinstance(d, dict) or d.get(field) in (None, ""):
        return "miss"
    try:
        a, b = norm(d[field]), norm(want)
    except Exception:
        return "diff"
    return "same" if (a and a == b) else "diff"


def coll_shape(d, field, rx):
    if not isinstance(d, dict) or field not in d:
        return "err", None
    v = d[field]
    if v is None or v == "":
        return "none", ""
    if isinstance(v, str) and rx.match(v):
        return "ok", v
    return "err", None


def _norm(s) -> str:
    return unicodedata.normalize("NFKC", spamguard.clean(str(s or "")))


_INVIS_CH = set("\u200b\u200c\u200e\u200f\u2060\u2061\u2062\u2063\u2064\ufeff\u00ad\u034f\u115f\u1160\u17b4\u17b5\u180e\u3164\uffa0")


def _invis_n(raw: str) -> int:
    return sum(1 for ch in raw if ch in _INVIS_CH or (unicodedata.category(ch) == "Cf" and ch != "\u200d")
               or 0xFFF0 <= ord(ch) <= 0xFFF8)


def unicode_trick(s, desc: bool = False) -> bool:
    raw = str(s or "")
    if not raw or raw.isascii():
        return False
    if desc:
        return _invis_n(raw) >= 3
    if _invis_n(raw):
        return True
    for ch in raw:
        o = ord(ch)
        if 0xFF10 <= o <= 0xFF19 or 0xFF21 <= o <= 0xFF3A or 0xFF41 <= o <= 0xFF5A or o == 0xFF0E or 0x1D400 <= o <= 0x1D7FF:
            return True
    why = spamguard.odd_symbol(raw)
    return bool(why) and "결합 부호" not in why


def has_volume(rec, hist_rows=None, now=None) -> bool:
    if not rec:
        return False
    now = _now() if now is None else float(now)
    age = _obs_age(rec, now)
    if age is not None and age <= VOL_FRESH_DAYS and any((_num(rec.get(k)) or 0) > 0 for k in ("vol24", "vol7", "sales24")):
        return True
    for r in hist_rows or []:
        if isinstance(r, list) and len(r) >= 4 and (_num(r[3]) or 0) > 0:
            return True
    return False


def _has_fp_src(col: dict) -> bool:
    ch = col.get("chain")
    return ch == "sol" or ch in CG_PLATFORM


def strong_spam(col: dict):
    if str(col.get("rep") or "").lower() in ("scam", "spam"):
        return "rep_scam"
    texts = [col.get("name"), col.get("sym"), col.get("mname"), col.get("cname")]
    if any(unicode_trick(t) for t in texts if t) or unicode_trick(col.get("desc"), desc=True):
        return "unicode"
    if any(_LURE_NAME.search(_norm(t)) for t in texts if t):
        return "lure"
    return None


def _thin(rec, now):
    lt = last_trade(rec, now)
    if not lt:
        return None
    d = _num(lt.get("age_days"))
    if d is None:
        d = float(lt.get("days") or 0)
    return "thin" if d <= THIN_FULL_DAYS else ("thin_old" if d <= THIN_MAX_DAYS else None)


def _sure(col, acq, trust=False) -> bool:
    kind = (acq or {}).get("kind")
    return bool(trust) or (is_platform(col or {}) and str((col or {}).get("rep") or "").lower() == "ok") or kind in SELF_KINDS or kind == "internal"


def price_rec(col, rec, acq, trust=False, now=None):
    if not isinstance(rec, dict):
        return None
    now = _now() if now is None else float(now)
    age = _obs_age(rec, now)
    if age is None or age > THIN_MAX_DAYS:
        return None
    if rec.get("basis") == "last" and not (_sure(col, acq, trust) and _thin(rec, now) is not None):
        return None
    return rec


def _hist_row_ok(r, col, acq, trust=False) -> bool:
    if not isinstance(r, list) or len(r) < 4:
        return False
    if len(r) < 5:
        return True
    m = r[4]
    if not isinstance(m, dict) or m.get("basis") != "last":
        return False
    at = _num(m.get("at"))
    if not at:
        return False
    rec9 = {"basis": "last", "native": r[1], "last": m.get("last") if isinstance(m.get("last"), dict) else {},
            "sales7": m.get("sales7"), "sales30": m.get("sales30"), "at": at}
    return price_rec(col, rec9, acq, trust, at) is not None


def classify(col: dict, rec: dict | None, acq: dict | None, hist_rows=None, trust: bool = False, now=None):
    kind = (acq or {}).get("kind")
    plat = is_platform(col) and str(col.get("rep") or "").lower() == "ok"
    sure = _sure(col, acq, trust)
    if col_ab_parent(col):
        return ("spam", "rep_scam") if strong_spam(col) == "rep_scam" else ("candidate", "ab_split")
    last_only = bool(rec and rec.get("basis") == "last")
    priced = bool(price_rec(col, rec, acq, trust, now) and (_num(rec.get("native")) or 0) > 0)
    vol = has_volume(rec, hist_rows, now) and not last_only
    thin = _thin(rec, now) if (priced and not vol) else None
    if col.get("partial"):
        sp, why = classify(dict(col, partial=False), rec, acq, hist_rows, trust, now)
        return (sp, why) if sp == "spam" else ("candidate", "partial_history")
    if trust:
        if priced:
            return ("auto", "priced") if vol else (("auto", thin) if thin else ("candidate", "price_no_volume"))
        return "candidate", "owner_notspam"
    ss = strong_spam(col)
    if ss == "rep_scam":
        return "spam", ss
    if ss:
        return ("candidate", "lure_but_priced") if (priced and vol) else ("spam", ss)
    if priced:
        if vol:
            return "auto", "priced"
        return ("auto", thin) if (thin and sure) else ("candidate", "price_no_volume")
    if kind in ("bought", "mint_paid"):
        return "candidate", "bought_no_price"
    if kind in ("mint_free", "claim"):
        return "candidate", "self_no_price"
    if kind == "internal":
        return "candidate", "internal_no_price"
    if plat:
        if kind == "airdrop_mass":
            return "candidate", "platform_airdrop"
        if kind == "received":
            return "candidate", "platform_received"
    elif _LURE_DESC.search(_norm(col.get("desc"))):
        return "spam", "desc_lure"
    if kind == "airdrop_mass":
        return "spam", "mass_airdrop"
    if (_num(col.get("holders")) or 0) >= MASS_HOLDERS:
        return "spam", "mass_holders"
    if kind == "received":
        return "spam", "free_noprice"
    if kind == "unknown" and int((acq or {}).get("tries") or 0) >= ACQ_TRIES:
        return "candidate", "acq_unknown"
    return "candidate", "checking"


def value_of(rec: dict | None, count: float, native_usd, rate):
    if not rec or not _fin(count) or count <= 0:
        return None
    fp = _num(rec.get("native"))
    if fp is None or fp <= 0:
        return None
    px = native_usd if (_fin(native_usd) and native_usd > 0) else None
    if px is None and _num(rec.get("usd")):
        px = _num(rec["usd"]) / fp
    v_nat = fp * count
    usd = v_nat * px if px else None
    krw = usd * rate if (usd is not None and _fin(rate) and rate > 0) else None
    return {"native": v_nat, "sym": rec.get("sym"), "usd": usd, "krw": krw, "px": px}


_EXPL_HOST = {"etherscan.io": "eth", "basescan.org": "base", "arbiscan.io": "arbitrum", "optimistic.etherscan.io": "optimism",
              "polygonscan.com": "polygon", "bscscan.com": "bsc", "scrollscan.com": "scroll", "gnosisscan.io": "gnosis",
              "eth.blockscout.com": "eth", "base.blockscout.com": "base", "arbitrum.blockscout.com": "arbitrum",
              "optimism.blockscout.com": "optimism", "polygon.blockscout.com": "polygon", "scroll.blockscout.com": "scroll",
              "zksync.blockscout.com": "zksync", "gnosis.blockscout.com": "gnosis", "era.zksync.network": "zksync"}
_OS_CHAIN_REV = {v: k for k, v in OS_CHAIN.items()}


def parse_watch(body: dict):
    link = str(body.get("link") or "").strip()
    if link:
        if len(link) > 300 or CTRL_RE.search(link):
            return None, "링크가 너무 길거나 형식이 맞지 않아요"
        try:
            u = urllib.parse.urlsplit(link if "://" in link else "https://" + link)
        except ValueError:
            return None, "링크 형식이 맞지 않아요"
        host = (u.hostname or "").lower()
        host = host[4:] if host.startswith("www.") else host
        parts = [p for p in u.path.split("/") if p]
        if host == "magiceden.io":
            if "marketplace" in parts and parts.index("marketplace") + 1 < len(parts):
                sym = parts[parts.index("marketplace") + 1]
                if ME_SYM_RE.match(sym):
                    return {"key": "sol:me/" + sym, "chain": "sol", "me": sym}, None
            return None, "매직에덴 링크는 magiceden.io/marketplace/<컬렉션> 꼴이어야 해요"
        if host == "opensea.io":
            if len(parts) >= 3 and parts[0] in ("assets", "item"):
                ch = _OS_CHAIN_REV.get(parts[1])
                if ch and ADDR_RE.match(parts[2]):
                    return _watch_ca(ch, parts[2].lower(), parts[3] if len(parts) >= 4 else None)
            if len(parts) >= 2 and parts[0] == "collection" and OS_SLUG_RE.match(parts[1]):
                return {"key": "os:" + parts[1], "chain": "os", "os": parts[1]}, None
            return None, "오픈시 링크 형식을 모르겠어요 — 체인과 컨트랙트 주소로 넣어 주세요"
        ch = _EXPL_HOST.get(host)
        if ch:
            for i, p in enumerate(parts):
                if p in ("token", "address", "nft") and i + 1 < len(parts) and ADDR_RE.match(parts[i + 1]):
                    tid = parts[i + 2] if (p == "nft" and i + 2 < len(parts)) else (urllib.parse.parse_qs(u.query).get("a") or [None])[0]
                    return _watch_ca(ch, parts[i + 1].lower(), tid)
            return None, "탐색기 링크에서 컨트랙트 주소를 못 찾았어요"
        return None, "지원하는 링크: 매직에덴·오픈시·이더스캔 계열·블록스카웃"
    sym = str(body.get("symbol") or "").strip()
    if sym:
        if not ME_SYM_RE.match(sym):
            return None, "매직에덴 컬렉션 심볼 형식이 맞지 않아요(영문·숫자·_·-)"
        return {"key": "sol:me/" + sym, "chain": "sol", "me": sym}, None
    ch = str(body.get("chain") or "").strip().lower()
    ca = str(body.get("address") or "").strip()
    if not CHAIN_RE.match(ch):
        return None, "체인을 골라 주세요"
    if ch == "sol":
        if not SOL_RE.match(ca):
            return None, "솔라나 컬렉션 주소 형식이 맞지 않아요(또는 매직에덴 심볼로)"
        return {"key": "sol:" + ca, "chain": "sol", "ca": ca}, None
    if not ADDR_RE.match(ca):
        return None, "컨트랙트 주소 형식이 맞지 않아요(0x + 40자리)"
    if ch not in CG_PLATFORM and ch not in OS_CHAIN:
        return None, "그 체인은 바닥가 출처가 없어요"
    return _watch_ca(ch, ca.lower(), body.get("token_id"))


AB_WATCH_ERR = "아트블럭은 한 계약에 여러 시리즈가 있어요 — 오픈시 아이템 링크(opensea.io/item/ethereum/계약/토큰번호)로 넣어 주세요"


def _watch_ca(ch, ca, tid=None):
    if ab_ver(ch, ca):
        sk = ser_key(ch, ca, tid)
        if not sk:
            return None, AB_WATCH_ERR
        proj = ser_parse(sk)[2]
        return {"key": sk, "chain": ch, "ca": f"{ca}/p{proj}", "pca": ca, "proj": proj, "sample": str(int(str(tid).strip()))}, None
    return {"key": f"{ch}:{ca}", "chain": ch, "ca": ca}, None


def default_http(url: str, data=None, headers=None, timeout: float = 20.0):
    try:
        body = json.dumps(data).encode() if data is not None else None
        kw = {"gate_host": CG_KEY_HOST} if headers and CG_KEY_HDR in headers else {}
        return 200, bf_engine.http_json(url, data=body, headers=headers, timeout=timeout, retries=1, prio="bg", max_inline_wait=5.0, **kw)
    except bf_engine.NetError as e:
        code = e.code if isinstance(e.code, int) else 0
        if not code and e.kind in ("http429", "quota"):
            code = 429
        if "coingecko.com" in url and cgplan.wrong_root(getattr(e, "body", "") or ""):
            return WRONGROOT, None
        return code, None
    except Exception:
        return 0, None


def _wins(key) -> tuple:
    v = BUDGET[key]
    return tuple(v) if isinstance(v[0], (tuple, list)) else (v,)


class _NoLock(Exception):
    pass


class _Budget:

    def __init__(self, now, path=None):
        self.now = now
        self.path = path
        self.t = {}
        self.dyn = {}
        self.mc = {}
        self.act = {}
        self.lock = threading.Lock()
        self._sig = None
        if path:
            self._load(force=True)

    def _load(self, force=False) -> None:
        if not self.path:
            return
        try:
            st = os.stat(self.path)
            sig = (st.st_mtime_ns, st.st_size, st.st_ino)
        except OSError:
            sig = None
        if not force and sig == self._sig:
            return
        self._sig = sig
        t, mc, act = {}, {}, {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            n0 = self.now()
            for k, q in ((d or {}).get("t") or {}).items():
                if k in BUDGET and isinstance(q, list):
                    win = max(w for _c, w in self._w(k))
                    t[k] = [float(x) for x in q if _fin(x) and n0 - win < x <= n0 + 60]
            m = (d or {}).get("m") if isinstance(d, dict) else None
            for k in MONTH_KEYS:
                v = m.get(k) if isinstance(m, dict) else None
                if (isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and re.fullmatch(r"\d{4}-\d{2}", v[0])
                        and type(v[1]) is int and 0 <= v[1] < 10 ** 9):
                    mc[k] = [v[0], v[1]]
            a = (d or {}).get("a") if isinstance(d, dict) else None
            for k in CG_LANES:
                v = a.get(k) if isinstance(a, dict) else None
                if _fin(v) and v <= n0 + 60:
                    act[k] = float(v)
        except (OSError, ValueError, TypeError, AttributeError):
            t, mc, act = {}, {}, {}
        self.t, self.mc, self.act = t, mc, act

    @contextlib.contextmanager
    def _xlock(self):
        with self.lock:
            if not self.path:
                yield
                return
            try:
                os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
                fd = os.open(self.path + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
            except OSError as e:
                raise _NoLock() from e
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX)
                except OSError as e:
                    raise _NoLock() from e
                self._load()
                yield
            finally:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:
                    pass
                os.close(fd)

    def month_count(self, key, now=None) -> int:
        with self.lock:
            self._load()
            c = self.mc.get(key)
            return c[1] if c and c[0] == _ym_utc(self.now() if now is None else now) else 0

    def _w(self, key) -> tuple:
        v = self.dyn.get(key)
        return tuple(v) if v else _wins(key)

    def _persist(self) -> bool:
        if not self.path:
            return True
        try:
            atomic_write(self.path, {"v": SCHEMA, "t": self.t, "m": self.mc, "a": self.act})
            try:
                st = os.stat(self.path)
                self._sig = (st.st_mtime_ns, st.st_size, st.st_ino)
            except OSError:
                self._sig = None
            return True
        except (OSError, ValueError):
            return False

    def take(self, key, wins=None, permit=None) -> bool:
        return self.take_all([(key, wins)], permit=permit)

    def take_all(self, reqs, permit=None) -> bool:
        try:
            with self._xlock():
                return self._take_all(reqs, permit)
        except _NoLock:
            return False

    def _take_all(self, reqs, permit=None) -> bool:
        n0 = self.now()
        got = {}
        for key, wins in reqs:
            wins = tuple(wins) if wins else self._w(key)
            keep = max([w for _c, w in wins] + [w for _c, w in self._w(key)])
            q = [x for x in self.t.get(key, ()) if x > n0 - keep]
            if any(sum(1 for x in q if x > n0 - win) >= cap for cap, win in wins):
                self.t[key] = q
                return False
            got[key] = q
        if permit is not None and not permit():
            return False
        prev_mc = {k: (list(v) if v else None) for k, v in ((k, self.mc.get(k)) for k in got if k in MONTH_KEYS)}
        ym = _ym_utc(n0)
        for key, q in got.items():
            q.append(n0)
            self.t[key] = q
            if key in MONTH_KEYS:
                c = self.mc.get(key)
                self.mc[key] = [ym, (c[1] if c and c[0] == ym else 0) + 1]
        if not self._persist():
            for q in got.values():
                q.pop()
            for k, v in prev_mc.items():
                if v is None:
                    self.mc.pop(k, None)
                else:
                    self.mc[k] = v
            return False
        return True

    def _cg_why(self, lane, pol, n0) -> str:
        def cnt(k9, win):
            return sum(1 for x in self.t.get(k9, ()) if x > n0 - win)
        others = {ln for ln in CG_LANES if ln != lane and n0 - float(self.act.get(ln) or 0.0) < CG_ACTIVE_S}
        mcap = pol["per_min"] - (pol["min_reserve"] if lane != "live" and "live" in others else 0)
        if cnt(CG_G, 60) >= mcap:
            return "minute"
        if cnt(CG_G, 86400) >= pol["per_day"]:
            return "day"
        hc = pol["hour"].get(lane)
        if hc is not None and cnt(CG_L[lane], 3600) >= hc:
            return "hour"
        used = {ln: cnt(CG_L[ln], 86400) for ln in CG_LANES}
        if used[lane] >= pol["floor"][lane]:
            left = pol["per_day"] - cnt(CG_G, 86400)
            resv = sum(max(0, pol["floor"][m] - used[m]) for m in others)
            if left - 1 < resv:
                return "share"
        return ""

    def take_cg(self, lane, per_min, per_day) -> str:
        if lane not in CG_LANES:
            return "lane"
        pol = cg_policy(per_min, per_day)
        try:
            with self._xlock():
                n0 = self.now()
                touch = n0 - float(self.act.get(lane) or 0.0) >= 60
                if touch:
                    self.act[lane] = n0
                fl = pol["floor"][lane]
                self.dyn[CG_L[lane]] = (((pol["hour"][lane], 3600),) if lane in pol["hour"] else ()) + ((max(0, fl), 86400),)
                why = self._cg_why(lane, pol, n0)
                if why:
                    if touch:
                        self._persist()
                    return why
                keep = max([86400] + [w for _c, w in self._w(CG_G)])
                qg = [x for x in self.t.get(CG_G, ()) if x > n0 - keep]
                ql = [x for x in self.t.get(CG_L[lane], ()) if x > n0 - 86400]
                prev_mc = list(self.mc[CG_G]) if self.mc.get(CG_G) else None
                qg.append(n0)
                ql.append(n0)
                self.t[CG_G], self.t[CG_L[lane]] = qg, ql
                ym = _ym_utc(n0)
                c = self.mc.get(CG_G)
                self.mc[CG_G] = [ym, (c[1] if c and c[0] == ym else 0) + 1]
                if not self._persist():
                    qg.pop()
                    ql.pop()
                    if prev_mc is None:
                        self.mc.pop(CG_G, None)
                    else:
                        self.mc[CG_G] = prev_mc
                    return "store"
                return ""
        except _NoLock:
            return "store"

    def cg_wait(self, lane, per_min, per_day) -> float:
        pol = cg_policy(per_min, per_day)
        with self.lock:
            self._load()
            n0 = self.now()
            if self._cg_why(lane, pol, n0) != "minute":
                return 0.0
            others = {ln for ln in CG_LANES if ln != lane and n0 - float(self.act.get(ln) or 0.0) < CG_ACTIVE_S}
            mcap = pol["per_min"] - (pol["min_reserve"] if lane != "live" and "live" in others else 0)
            q = sorted(x for x in self.t.get(CG_G, ()) if x > n0 - 60)
            if mcap <= 0:
                return 60.0
            return max(0.0, q[len(q) - mcap] + 60 - n0 + 0.01) if len(q) >= mcap else 0.0

    def cg_usage(self) -> dict:
        with self.lock:
            self._load()
            n0 = self.now()
            out = {ln: sum(1 for x in self.t.get(CG_L[ln], ()) if x > n0 - 86400) for ln in CG_LANES}
            out["total"] = sum(1 for x in self.t.get(CG_G, ()) if x > n0 - 86400)
            return out

    def _left_w(self, key, cap, win) -> int:
        n0 = self.now()
        return cap - sum(1 for x in self.t.get(key, ()) if x > n0 - win)

    def left(self, key) -> int:
        with self.lock:
            self._load()
            return min(self._left_w(key, cap, win) for cap, win in self._w(key))

    def free_in(self, key, wins=None) -> float:
        with self.lock:
            self._load()
            n0, w = self.now(), 0.0
            for cap, win in (tuple(wins) if wins else self._w(key)):
                q = sorted(x for x in self.t.get(key, ()) if x > n0 - win)
                if cap <= 0:
                    w = max(w, float(win))
                elif len(q) >= cap:
                    w = max(w, q[len(q) - cap] + win - n0 + 0.01)
            return w

    def snap(self) -> dict:
        out = {}
        with self.lock:
            self._load()
            for k in BUDGET:
                ws = [{"used": cap - self._left_w(k, cap, win), "cap": cap, "window": win} for cap, win in self._w(k)]
                out[k] = ws[0] if len(ws) == 1 else dict(max(ws, key=lambda x: x["window"]), windows=ws)
        return out


MONTH_KEYS = ("coingecko_key",)


def cg_policy(per_min, per_day) -> dict:
    pm, pd = max(0, int(per_min or 0)), max(0, int(per_day or 0))
    fl = {ln: int(pd * CG_FLOOR[ln]) for ln in CG_LANES}
    fl["live"] += pd - sum(fl.values())
    return {"per_min": pm, "per_day": pd, "floor": fl, "min_reserve": int(pm * CG_LIVE_MIN),
            "hour": {"live": (-(-pd // 24)) if pd > 0 else 0}}


def cg_key_windows(rec, budget=None, share=None) -> tuple:
    b = budget or shared_budget()
    if isinstance(rec, dict) and rec.get("plan") == "pro":
        bb = cgplan.budget(rec, b.now(), share, b.month_count(CG_G))
        if bb["basis"] == "pro":
            return int(bb["per_min"]), int(bb["per_day"])
    w = {win: cap for cap, win in _wins(CG_G)}
    return int(w.get(60, cgplan.DEMO_BUDGET[0])), int(w.get(86400, cgplan.DEMO_BUDGET[1]))


def _ym_utc(t) -> str:
    return datetime.fromtimestamp(float(t), timezone.utc).strftime("%Y-%m")


_SHARED = {}
_SHARED_LOCK = threading.Lock()


def shared_budget() -> "_Budget":
    with _SHARED_LOCK:
        b = _SHARED.get(BUDGET_PATH)
        if b is None:
            b = _SHARED[BUDGET_PATH] = _Budget(_now, BUDGET_PATH)
        return b


def cg_reserve(key: str, wait_max: float = 5.0, sleep=None, budget=None) -> str:
    b = budget or shared_budget()
    st = cgplan.Store()
    try:
        rec = st.load(key)
    except Exception:
        rec = None
    bb = cgplan.budget(rec, b.now(), st.share(), b.month_count("coingecko_key"))
    wins = ((int(bb["per_min"]), 60), (int(bb["per_day"]), 86400))
    if b.take("coingecko_key", wins=wins):
        return ""
    w = b.free_in("coingecko_key", wins=wins)
    if 0 < w <= wait_max:
        (sleep or time.sleep)(w)
        if b.take("coingecko_key", wins=wins):
            return ""
        w = b.free_in("coingecko_key", wins=wins)
    if w <= 0:
        return "store"
    return "minute" if b.free_in("coingecko_key", wins=wins[1:]) <= 0 else "day"


BLOCKED, NOBUDGET = -429, -1
HIDDEN = -2
WRONGROOT = -10010


class Tracker:

    def __init__(self, cfg_fn=None, px_fn=None, rate_fn=None, http=None, sleep=None, now=None, env_fn=None,
                 hold_path=None, fp_path=None, prefs_path=None, gate_fn=None, budget_path=None, alert_fn=None, cg_store=None):
        self.cg_store = cg_store or cgplan.Store()
        self.alert_fn = alert_fn
        self.cfg_fn = cfg_fn or (lambda: {})
        self.px_fn = px_fn or (lambda sym: None)
        self.rate_fn = rate_fn or (lambda: 0.0)
        self.http = http or default_http
        self.sleep = sleep or time.sleep
        self.now = now or _now
        self.env_fn = env_fn or _env
        self.gate_fn = gate_fn or (lambda: common.read_json(common.ACTIVITY_GATE_PATH, {}))
        self.hold_path = hold_path or HOLD_PATH
        self.fp_path = fp_path or FP_PATH
        self.prefs_path = prefs_path or PREFS_PATH
        self.lock = threading.RLock()
        self.prefs_lock = threading.RLock()
        self.run_lock = threading.Lock()
        self.hold = _load_cache(self.hold_path, empty_hold)
        self.fp = _load_cache(self.fp_path, empty_fp)
        if budget_path is None and hold_path is None and now is None:
            self.budget = shared_budget()
        else:
            self.budget = _Budget(self.now, budget_path or (os.path.join(os.path.dirname(self.hold_path), "nft_budget.json")
                                                              if hold_path else BUDGET_PATH))
        self.wake = threading.Event()
        self._tl = threading.local()
        self.calls = {}
        self._last_call = 0.0
        self._host_last = {}
        self._gap_dyn = {}
        self._last_st = None
        self.urgent = set()

    def prefs(self) -> dict:
        with self.prefs_lock:
            return load_prefs(self.prefs_path)

    def _cfg(self) -> dict:
        try:
            c = self.cfg_fn() or {}
        except Exception:
            c = {}
        return c if isinstance(c, dict) else {}

    def enabled(self) -> bool:
        n = self._cfg().get("nft")
        return not (isinstance(n, dict) and n.get("enabled") is False)

    def _blocked(self, host) -> bool:
        return self.now() < float(((self.fp.get("hosts") or {}).get(host) or {}).get("until") or 0)

    def _call(self, bkey, url, data=None, headers=None, hkey=None, take=None):
        host = hkey or (urllib.parse.urlsplit(url).hostname or "?").lower()
        if self._item_hid():
            self._last_st = HIDDEN
            return HIDDEN, None
        if self._blocked(host):
            self._last_st = BLOCKED
            return BLOCKED, None
        if bkey == "helius":
            try:
                bf_engine.helius_configure(self._cfg())
            except Exception:
                pass
        hl9 = (lambda: bf_engine.HELIUS.take("web", 10, kind="aux")) if bkey == "helius" else None
        if bkey in ("etherscan", "helius") and not take:
            ok9 = self.budget.take(bkey, permit=hl9 or (lambda: bf_engine.es_budget_take("web", kind="aux")))
        else:
            ok9 = take() if take else self.budget.take(bkey)
            if ok9 and bkey == "etherscan":
                ok9 = bf_engine.es_budget_take("web", kind="aux")
            elif ok9 and hl9:
                ok9 = hl9()
        if not ok9:
            self._last_st = NOBUDGET
            return NOBUDGET, None
        gap = MIN_GAP - (self.now() - self._last_call)
        hg = self._gap_dyn.get(bkey, HOST_GAP.get(bkey))
        if hg:
            gap = max(gap, hg - (self.now() - self._host_last.get(host, -1e18)))
        if gap > 0:
            self.sleep(gap)
            if self._item_hid():
                self._last_st = HIDDEN
                return HIDDEN, None
        self._last_call = self.now()
        self._host_last[host] = self._last_call
        self.calls[host] = self.calls.get(host, 0) + 1
        st, j = self.http(url, data=data, headers=headers)
        self._last_st = st
        with self.lock:
            hs = self.fp.setdefault("hosts", {})
            if st == 429:
                prev = float((hs.get(host) or {}).get("back") or 0)
                back = min(7200.0, max(900.0, prev * 2 if prev else 900.0))
                hs[host] = {"until": self.now() + back, "back": back}
            elif st == 200 and host in hs:
                hs.pop(host, None)
        return st, j

    def _cg_key(self) -> str:
        try:
            return str(self.env_fn(CG_KEY_ENV) or "").strip()
        except Exception:
            return ""

    def _key_bad(self, k: str) -> bool:
        kb = self.fp.get("cgkey")
        if not (bool(k) and isinstance(kb, dict) and bool(kb.get("bad")) and kb.get("fp") == _kfp(k)):
            return False
        try:
            rec = self.cg_store.load(k)
        except Exception:
            rec = None
        at = _num((rec or {}).get("at")) if isinstance(rec, dict) else None
        return not (at and at > (_num(kb.get("at")) or 0))

    def _cg_mode(self, k: str):
        try:
            rec = self.cg_store.load(k)
        except Exception as e:
            _warn("코인게코 키 등급 기록 읽기 실패: %s", type(e).__name__)
            rec = None
        plan = rec.get("plan") if isinstance(rec, dict) and rec.get("plan") in cgplan.PLANS else "demo"
        b = cgplan.budget(rec if plan == "pro" else None, self.now(), self._cg_share(), self.budget.month_count("coingecko_key"))
        if plan == "pro" and b["basis"] == "pro":
            self.budget.dyn["coingecko_key"] = ((int(b["per_min"]), 60), (int(b["per_day"]), 86400))
            self._gap_dyn["coingecko_key"] = 60.0 / max(1, int(b["per_min"]))
        else:
            self.budget.dyn.pop("coingecko_key", None)
            self._gap_dyn.pop("coingecko_key", None)
        return plan, rec

    def _cg_share(self) -> int:
        try:
            return cgplan.norm_share(self.cg_store.share())
        except Exception:
            return cgplan.DEFAULT_SHARE

    def _cg_key_call(self, plan: str, path: str, k: str):
        root, hdr = cgplan.endpoint(plan)
        hkey = CG_PRO_HOST if plan == "pro" else CG_KEY_HOST
        wd = {win: cap for cap, win in self.budget._w(CG_G)}
        pm, pd = int(wd.get(60, cgplan.DEMO_BUDGET[0])), int(wd.get(86400, cgplan.DEMO_BUDGET[1]))

        def take():
            return not self.budget.take_cg("nft", pm, pd)
        st, d = self._call("coingecko_key", root + path, headers={hdr: k}, hkey=hkey, take=take)
        if st == NOBUDGET:
            w = self.budget.cg_wait("nft", pm, pd)
            if 0 < w <= 61:
                self.sleep(w)
                st, d = self._call("coingecko_key", root + path, headers={hdr: k}, hkey=hkey, take=take)
        return st, d

    @staticmethod
    def _wrong_root(st, d) -> bool:
        return st == WRONGROOT or (st != 200 and isinstance(d, (dict, str)) and cgplan.wrong_root(d)) or (
            st == 200 and isinstance(d, dict) and "status" in d and cgplan.wrong_root(d))

    def _cg_remember(self, k: str, **fields):
        try:
            return self.cg_store.save(k, **fields)
        except Exception as e:
            _warn("코인게코 키 등급 기록 실패: %s", type(e).__name__)
            return None

    def _cg_info_refresh(self, k: str, rec) -> None:
        if not isinstance(rec, dict) or rec.get("plan") != "pro":
            return
        now = self.now()
        ist = cgplan.info_state(rec, now)
        ia, ta = _num(rec.get("info_at")) or 0.0, _num(rec.get("info_try_at")) or 0.0
        if ist == "ok" and now - ia < cgplan.INFO_EVERY:
            return
        if ist != "ok" and ta and ta <= now + 3600 and now - ta < cgplan.INFO_RETRY:
            return
        root, hdr = cgplan.endpoint("pro")
        mins = tuple(w for w in self.budget._w("coingecko_key") if w[1] <= 60) or ((cgplan.DEMO_BUDGET[0], 60),)
        st, d = self._call("coingecko_key", root + "/key", headers={hdr: k}, hkey=CG_PRO_HOST,
                           take=lambda: self.budget.take_all([("coingecko_info", None), ("coingecko_key", mins)]))
        if st in (NOBUDGET, BLOCKED, HIDDEN):
            return
        info = cgplan.parse_key_info(d) if st == 200 else None
        if info:
            self._cg_remember(k, info=info, info_at=now, info_try_at=now)
        else:
            self._cg_remember(k, info=None, info_at=None, info_try_at=now)
            _warn("코인게코 프로 사용량(/key) 읽기 실패(HTTP %s) — 데모 수준 예산으로", st)
        self._cg_mode(k)

    def cg_info_tick(self) -> None:
        k = self._cg_key()
        if not k:
            return
        with self.lock:
            if self._key_bad(k):
                return
        plan, rec = self._cg_mode(k)
        if plan == "pro":
            self._cg_info_refresh(k, rec)

    def _cg_get(self, url):
        root0 = cgplan.ROOT["demo"]
        path = url[len(root0):] if url.startswith(root0) else url
        k = self._cg_key()
        if k:
            with self.lock:
                kb = self.fp.get("cgkey") if self._key_bad(k) else None
            if not kb or self.now() - float(kb.get("at") or 0) >= KEY_BAD_RETRY:
                plan, rec = self._cg_mode(k)
                if plan == "pro":
                    self._cg_info_refresh(k, rec)
                st, d = self._cg_key_call(plan, path, k)
                if self._wrong_root(st, d):
                    alt = cgplan.other(plan)
                    st2, d2 = self._cg_key_call(alt, path, k)
                    if st2 in (200, 404) and not self._wrong_root(st2, d2):
                        _warn("코인게코 키 등급 자동 전환: %s → %s (루트 URL 오류)", cgplan.PLAN_KO[plan], cgplan.PLAN_KO[alt])
                        self._cg_remember(k, plan=alt, at=self.now(), how="runtime")
                        plan, st, d = alt, st2, d2
                        if alt == "pro":
                            self._cg_info_refresh(k, self._cg_mode(k)[1])
                        else:
                            self._cg_mode(k)
                    elif st2 in (401, 403) or self._wrong_root(st2, d2):
                        st, d = (st2 if st2 in (401, 403) else 401), None
                    else:
                        st, d = st2, d2
                if st in (401, 403):
                    with self.lock:
                        self.fp["cgkey"] = {"bad": True, "fp": _kfp(k), "at": self.now(), "st": st}
                    _warn("코인게코 %s 키 거부(HTTP %s) — 무키로 계속 · 설정 › 연결·키에서 다시 넣어야 해요", cgplan.PLAN_KO[plan], st)
                elif st not in (NOBUDGET, BLOCKED, WRONGROOT) and not self._wrong_root(st, d):
                    if st in (200, 404):
                        with self.lock:
                            if self.fp.get("cgkey"):
                                self.fp["cgkey"] = {}
                    return st, d
        return self._call("coingecko", root0 + path)

    def cg_waiting(self, prefs=None) -> int:
        with self.lock:
            chk = set(self.fp.get("chk") or {})
        n = 0
        for raw, c in self.due_fp(prefs):
            if c.get("chain") in CG_PLATFORM and ADDR_RE.match(str(c.get("ca") or "")) and raw not in chk and self.canon(raw) not in chk:
                n += 1
        return n

    def notice(self, prefs=None):
        k = self._cg_key()
        if k:
            with self.lock:
                bad = self._key_bad(k)
            return {"kind": "key_bad", "text": NOTICE_KEY_BAD, "waiting": self.cg_waiting(prefs), "blocked_until": None, "action": "keys"} if bad else None
        if self.env_fn("TJ_OPENSEA_KEY"):
            return None
        now = self.now()
        with self.lock:
            bu = float(((self.fp.get("hosts") or {}).get("api.coingecko.com") or {}).get("until") or 0)
        w = self.cg_waiting(prefs)
        if bu <= now and w < NOTICE_BACKLOG:
            return None
        return {"kind": "slow", "text": NOTICE_SLOW, "waiting": w, "blocked_until": bu if bu > now else None, "action": "keys"}

    def maybe_alert(self, prefs=None) -> bool:
        if not self.alert_fn or self._cg_key() or self.env_fn("TJ_OPENSEA_KEY"):
            return False
        now = self.now()
        with self.lock:
            last = _num((self.fp.get("notify") or {}).get("cg_slow")) or 0.0
        if last and last <= now + 3600 and now - last < NOTIFY_EVERY:
            return False
        n = self.notice(prefs)
        if not n or n.get("kind") != "slow":
            return False
        text = (f"⏳ {NOTICE_SLOW}\n지금 바닥가를 기다리는 EVM 컬렉션 {int(n.get('waiting') or 0)}개"
                + (" · 코인게코 무키 호출 쉬는 중" if n.get("blocked_until") else "")
                + f"\n키 발급: 오픈시 {OS_KEY_URL} (넣으면 최우선) · 코인게코 {CG_KEY_URL} (가입 → Demo 키, 무료)")
        line = alert_watch._alert("NFT_CG_SLOW", text)
        try:
            ok = self.alert_fn(line) is True
        except Exception as e:
            _warn("NFT 코인게코 지연 알림 적재 실패: %s", type(e).__name__)
            ok = False
        if ok:
            with self.lock:
                self.fp.setdefault("notify", {})["cg_slow"] = now
            self.save()
        return ok

    def _helius(self, method, params):
        key = self.env_fn("TJ_HELIUS_KEY")
        if not key:
            return 0, None
        st, j = self._call("helius", HELIUS_RPC + key, data={"jsonrpc": "2.0", "id": "tjnft", "method": method, "params": params})
        if st == 200 and isinstance(j, dict) and "result" in j:
            return 200, j["result"]
        return (st if st != 200 else 0), None

    def _scan_bs(self, base, addr):
        items, pp, pages = [], None, 0
        while pages < PAGES_MAX:
            url = f"{base}/api/v2/addresses/{addr}/nft?type=ERC-721%2CERC-1155"
            if pp:
                url += "&" + urllib.parse.urlencode({k: v for k, v in pp.items() if isinstance(v, (str, int, float)) and not isinstance(v, bool)})
            st, d = self._call("blockscout", url)
            pages += 1
            got, pp = parse_bs_nft(d) if st == 200 else (None, None)
            if got is None:
                return None, f"http{st}" if st > 0 else ("budget" if st == NOBUDGET else ("wait" if st == BLOCKED else "net"))
            items.extend(got)
            if not pp:
                break
        else:
            if pp:
                self._bs_trunc = True
        return items, None

    def _scan_legacy(self, base, chain, addr):
        if not LEGACY_NFT.get(chain):
            return [], None
        st, d = self._call("blockscout", f"{base}/api/v2/addresses/{addr}/token-balances")
        got = parse_bs_legacy(d, chain) if st == 200 else None
        if got is None:
            return None, f"http{st}" if st > 0 else ("budget" if st == NOBUDGET else ("wait" if st == BLOCKED else "net"))
        return got, None

    def _legacy_prev(self, pk, chain):
        want = LEGACY_NFT.get(chain) or {}
        out = []
        with self.lock:
            items = ((self.hold["pairs"].get(pk) or {}).get("items") or {})
            for key, a in items.items():
                ca = key.split(":", 1)[1] if ":" in key else ""
                if ca in want and int((a or {}).get("n") or 0) > 0:
                    c = self.hold["cols"].get(key) or {}
                    nm, sy = want[ca]
                    out.append({"ca": ca, "name": nm, "sym": sy, "std": "pre-721", "holders": c.get("holders"), "supply": None,
                                "rep": c.get("rep"), "id": None, "n": int(a["n"]), "mname": "", "mdesc": "", "img": None})
        return out

    def _scan_es(self, chain, cid, addr):
        key = self.env_fn("TJ_ETHERSCAN_KEY")
        if not key:
            return None, "nokey"
        rows, partial = [], False
        for act in ("tokennfttx", "token1155tx"):
            got, startblock, page = 0, 0, 1
            carry, tail, tail_blk = {}, {}, None
            while True:
                q = urllib.parse.urlencode({"chainid": cid, "module": "account", "action": act, "address": addr, "page": page,
                                            "offset": ES_PAGE, "sort": "asc", "startblock": startblock, "apikey": key})
                for _try in (0, 1):
                    st, d = self._call("etherscan", ES_API + "?" + q)
                    if _try == 0 and isinstance(d, dict) and str(d.get("status")) != "1" and "rate limit" in (str(d.get("result")) + str(d.get("message"))).lower():
                        self.sleep(2.0)
                        continue
                    break
                if st != 200 or not isinstance(d, dict):
                    return None, f"http{st}" if st > 0 else "net"
                res = d.get("result")
                if str(d.get("status")) != "1":
                    msg = (str(res) if not isinstance(res, list) else "") + " " + str(d.get("message") or "")
                    if "not supported for this chain" in msg or "upgrade your api plan" in msg.lower() or "unsupported chain" in msg.lower():
                        return None, "unsupported"
                    if "no transactions found" in msg.lower() or (isinstance(res, list) and not res):
                        break
                    return None, "es_rate" if "rate limit" in msg.lower() else "es_error"
                if not isinstance(res, list):
                    return None, "es_error"
                for r9 in res:
                    if not isinstance(r9, dict):
                        continue
                    fp9 = (r9.get("hash"), r9.get("logIndex"), r9.get("contractAddress"), r9.get("tokenID"), r9.get("from"), r9.get("to"), r9.get("tokenValue"))
                    b9 = str(r9.get("blockNumber") or "")
                    if carry.get((b9, fp9), 0) > 0:
                        carry[(b9, fp9)] -= 1
                        continue
                    if b9 != tail_blk:
                        tail, tail_blk = {}, b9
                    tail[(b9, fp9)] = tail.get((b9, fp9), 0) + 1
                    rows.append(r9)
                    got += 1
                if len(res) < ES_PAGE:
                    break
                if got >= ES_MAX_ROWS:
                    partial = True
                    break
                if page < ES_PAGES_PER_BLOCKRUN:
                    page += 1
                    continue
                try:
                    nb = int(str(res[-1].get("blockNumber") or "0"))
                except (TypeError, ValueError, AttributeError):
                    nb = 0
                if nb <= startblock:
                    partial = True
                    break
                startblock, page = nb, 1
                carry = {k9: v9 for k9, v9 in tail.items()} if tail_blk == str(nb) else {}
        items = parse_es_nft(rows, addr)
        if partial:
            for it in items:
                it["partial"] = True
        return items, None

    def targets(self, cfg=None) -> list:
        cfg = cfg if cfg is not None else self._cfg()
        try:
            gate = self.gate_fn() or {}
        except (Exception, SystemExit):
            gate = {}
        out = [(f"{c}:{a}", c, a, bs, es) for c, a, bs, es in evm_targets(cfg, gate)]
        _evm, sol = registered(cfg)
        out += [(f"sol:{a}", "sol", a, None, None) for a in sorted(sol)]
        return out

    def scan(self, limit: int = PAIRS_PER_CYCLE) -> int:
        cfg = self._cfg()
        tg = self.targets(cfg)
        now = self.now()
        es_kv = str(self.env_fn("TJ_ETHERSCAN_KEY") or "")
        es_key = bool(es_kv)
        ekf = _kfp(es_kv) if es_kv else ""
        unsup = {c: v for c, v in ((self.hold.get("scan") or {}).get("unsupported") or {}).items()
                 if isinstance(v, dict) and ekf and v.get("kfp") == ekf}
        helius = bool(self.env_fn("TJ_HELIUS_KEY"))
        due = []
        with self.lock:
            pairs = self.hold["pairs"]
            for t in tg:
                pk, chain, addr, bs, es = t
                if chain == "sol" and not helius:
                    continue
                if not bs and chain != "sol" and (not es or not es_key or float((unsup.get(chain) or {}).get("until") or 0) > now):
                    continue
                p = pairs.get(pk) or {}
                at, tried = float(p.get("at") or 0), float(p.get("tried") or 0)
                if p.get("err") and now - tried < PAIR_RETRY:
                    continue
                if p.get("rs"):
                    due.append((-1, 0.0, t))
                    continue
                if not p.get("err") and at and now - at < SCAN_EVERY:
                    continue
                due.append((0 if not at else 1, at, t))
        due.sort(key=lambda x: (x[0], x[1]))
        due = _rr(due, lambda x: x[2][1])
        n = 0
        for _o, _a, (pk, chain, addr, bs, es) in due:
            if n >= limit:
                break
            if chain != "sol" and not bs and float((unsup.get(chain) or {}).get("until") or 0) > now:
                continue
            if not self.budget.take("pairs"):
                break
            n += 1
            if chain == "sol":
                got, err = self._scan_sol(addr)
                src = "helius"
            else:
                got, err, src = None, None, None
                if bs:
                    self._bs_trunc = False
                    got, err = self._scan_bs(bs, addr)
                    src = "blockscout"
                if got is None and es and es_key and float((unsup.get(chain) or {}).get("until") or 0) <= now:
                    got, err2 = self._scan_es(chain, es, addr)
                    src = "etherscan"
                    if err2 == "unsupported":
                        unsup[chain] = {"why": "etherscan_free", "until": now + UNSUP_TTL, "kfp": ekf}
                    err = err2 if (err2 == "unsupported" or not err) else err
                if got is not None and LEGACY_NFT.get(chain):
                    leg, lerr = self._scan_legacy(bs, chain, addr) if bs else (None, "no_blockscout")
                    if leg is None:
                        leg = self._legacy_prev(pk, chain)
                        self._leg_err = lerr
                    got = got + leg
            if got is None:
                with self.lock:
                    p = self.hold["pairs"].setdefault(pk, {"items": {}})
                    p.update({"err": err, "tried": now, "src": src})
                continue
            if chain == "sol":
                self._merge_sol(pk, got, now)
            else:
                self._merge_pair(pk, chain, got, now, src)
                if src == "blockscout" and getattr(self, "_bs_trunc", False):
                    with self.lock:
                        self.hold["pairs"][pk]["trunc"] = True
                if getattr(self, "_leg_err", None):
                    with self.lock:
                        self.hold["pairs"][pk]["leg_err"] = self._leg_err
            self._leg_err = None
        live = {t[0] for t in tg}
        off9 = _off_chains(cfg)
        with self.lock:
            for pk in list(self.hold["pairs"]):
                if pk not in live and pk.split(":", 1)[0] not in off9:
                    self.hold["pairs"].pop(pk, None)
            held = {k for p in self.hold["pairs"].values() for k in (p.get("items") or {})}
            for k in list(self.hold["cols"]):
                if k not in held and now - float(self.hold["cols"][k].get("seen") or 0) > 30 * 86400:
                    self.hold["cols"].pop(k, None)
            summ, fresh = {}, 0
            for pk, chain, _a, _b, _e in tg:
                p = self.hold["pairs"].get(pk) or {}
                s9 = summ.setdefault(chain, {"ok": 0, "err": 0, "wait": 0, "src": p.get("src")})
                if p.get("at") and not p.get("err"):
                    s9["ok"] += 1
                    fresh += 1 if now - float(p["at"]) < SCAN_EVERY + PAIR_RETRY else 0
                elif p.get("err"):
                    s9["err"] += 1
                else:
                    s9["wait"] += 1
                if p.get("src"):
                    s9["src"] = p["src"]
            self.hold["scan"] = {"at": now, "chains": summ, "done": fresh, "total": len(tg),
                                 "unsupported": {c: v for c, v in unsup.items() if float(v.get("until") or 0) > now}}
            self.hold["at"] = now
        if n:
            self.save()
        return n

    def _scan_sol(self, addr):
        got, page = [], 1
        while page <= 3:
            st, res = self._helius("getAssetsByOwner", {"ownerAddress": addr, "page": page, "limit": 1000,
                                                         "displayOptions": {"showFungible": False, "showCollectionMetadata": True,
                                                                            "showUnverifiedCollections": True}})
            part = parse_das(res) if st == 200 else None
            if part is None:
                return None, (f"http{st}" if st > 0 else ("budget" if st == NOBUDGET else ("wait" if st == BLOCKED else "net")))
            got.extend(part)
            if len((res or {}).get("items") or []) < 1000:
                break
            page += 1
        return got, None

    def _merge_pair(self, pk, chain, items, now, src):
        agg = {}
        split = (not any(ab_ver(chain, it.get("ca")) for it in items)) or self._ab_backup()
        with self.lock:
            cols = self.hold["cols"]
            for it in items:
                sk = ser_key(chain, it["ca"], it.get("id")) if split else None
                if sk:
                    self._merge_ser(cols, agg, sk, chain, it, now, src)
                    continue
                key = f"{chain}:{it['ca']}"
                a = agg.setdefault(key, {"n": 0, "ids": []})
                if split and ab_parent_key(key):
                    a["unsplit"] = True
                a["n"] += int(it.get("n") or 1)
                if len(a["ids"]) < 5 and it.get("id"):
                    a["ids"].append(it["id"])
                if it.get("tx") and not a.get("tx"):
                    a["tx"], a["from"] = it["tx"], it.get("from") or ""
                if it.get("partial"):
                    a["partial"] = True
                c = cols.get(key) or {}
                lp = is_lp(chain, it["ca"], it.get("name"), it.get("sym"))
                c.update({"chain": chain, "ca": it["ca"], "name": it.get("name") or c.get("name") or "",
                          "sym": it.get("sym") or c.get("sym") or "", "std": it.get("std") or c.get("std") or "",
                          "holders": it.get("holders") if it.get("holders") is not None else c.get("holders"),
                          "supply": it.get("supply") if it.get("supply") is not None else c.get("supply"),
                          "rep": it.get("rep") or c.get("rep"), "mname": it.get("mname") or c.get("mname") or "",
                          "desc": it.get("mdesc") or c.get("desc") or "", "img": it.get("img") or c.get("img"),
                          "lp": lp, "seen": now, "src": src})
                c.setdefault("first", now)
                cols[key] = c
            self.hold["pairs"][pk] = {"items": agg, "at": now, "err": None, "src": src}

    @staticmethod
    def _merge_ser(cols, agg, sk, chain, it, now, src):
        _c, ca, proj = ser_parse(sk)
        a = agg.setdefault(sk, {"n": 0, "ids": []})
        a["n"] += int(it.get("n") or 1)
        if len(a["ids"]) < 5 and it.get("id"):
            a["ids"].append(it["id"])
        if it.get("partial"):
            a["partial"] = True
        c = cols.get(sk) or {}
        nm = ser_name(it.get("mname"), proj) if it.get("mname") else (c.get("name") or ser_name("", proj))
        c.update({"chain": chain, "ca": f"{ca}/p{proj}", "pca": ca, "proj": proj, "plat": AB_NAME, "ver": ab_ver(chain, ca),
                  "name": nm, "sym": it.get("sym") or c.get("sym") or "", "std": it.get("std") or c.get("std") or "",
                  "holders": None, "supply": None, "rep": it.get("rep") or c.get("rep"),
                  "mname": it.get("mname") or c.get("mname") or "", "desc": it.get("mdesc") or c.get("desc") or "",
                  "img": it.get("img") or c.get("img"), "lp": False, "seen": now, "src": src,
                  "sample": c.get("sample") if c.get("sample") in a["ids"] else (a["ids"][0] if a["ids"] else c.get("sample"))})
        c.setdefault("first", now)
        cols[sk] = c

    def _merge_sol(self, pk, items, now):
        agg = {}
        with self.lock:
            cols = self.hold["cols"]
            for it in items:
                key = "sol:" + (it["coll"] if it["coll"] else "mint/" + it["mint"])
                a = agg.setdefault(key, {"n": 0, "ids": []})
                a["n"] += 1
                if len(a["ids"]) < 5:
                    a["ids"].append(it["mint"])
                c = cols.get(key) or {}
                nm = (it.get("cname") if it["coll"] else "") or it.get("name") or ""
                c.update({"chain": "sol", "ca": it["coll"] or it["mint"], "name": nm, "sym": (it.get("csym") if it["coll"] else "") or it.get("sym") or "",
                          "claimed": it.get("claimed") or "",
                          "std": it["std"], "mname": it.get("name") or "", "desc": it.get("desc") or c.get("desc") or "",
                          "img": it.get("img") or c.get("img"), "compressed": it["compressed"], "verified": it["verified"],
                          "lp": is_lp("sol", "", nm, it.get("sym")), "seen": now, "src": "helius",
                          "sample": c.get("sample") if c.get("sample") in a["ids"] else it["mint"]})
                c.setdefault("first", now)
                cols[key] = c
            self.hold["pairs"][pk] = {"items": agg, "at": now, "err": None, "src": "helius"}

    def acquire_lookups(self, cfg=None, limit=ACQ_PER_SCAN) -> int:
        cfg = cfg if cfg is not None else self._cfg()
        evm, sol = registered(cfg)
        chains = cfg.get("chains") or {}
        now = self.now()
        todo = []
        prefs = self._prefs_or_empty()
        trusted = set(prefs.get("notspam") or [])
        ishid = self._hid_fn(prefs)
        with self.lock:
            fpm = self.fp.get("fp") or {}
            off9 = set(cfg.get("_disabled_chains") or [])
            for key, c in self.hold["cols"].items():
                ch9 = c.get("chain")
                if ch9 in off9 or (isinstance(chains.get(ch9), dict) and not common.chain_enabled(ch9, chains.get(ch9))):
                    continue
                if ishid(self.canon(key)):
                    continue
                if c.get("lp") or (strong_spam(c) and self.canon(key) not in trusted):
                    continue
                if ab_parent_key(key) or col_ab_parent(c):
                    continue
                r9 = fpm.get(self.canon(key)) or {}
                if (_num(r9.get("native")) or 0) > 0 and has_volume(r9, None, now) and r9.get("basis") != "last" and not ser_parse(key):
                    continue
                if key not in (self.fp.get("chk") or {}) and _has_fp_src(c):
                    continue
                a = self.hold["acq"].get(key) or {}
                if a.get("kind") and a["kind"] != "unknown":
                    continue
                if int(a.get("tries") or 0) >= ACQ_TRIES or (a and now - float(a.get("at") or 0) < ACQ_RETRY):
                    continue
                own = self._owner_of(key)
                if own:
                    todo.append((key, c, own[0], own[1], own[2]))
        done = 0
        todo = _rr(todo, lambda x: x[1].get("chain"))
        for key, c, owner, sample, item in todo[:limit]:
            if self._hid_now(key):
                continue
            with self._item(key):
                r, final = self._acq_one(key, c, owner, sample, item, cfg, chains, evm, sol)
                hid9 = self._hid_seen()
            if hid9:
                continue
            if r is None and self._last_st in (NOBUDGET, BLOCKED, 429):
                break
            with self.lock:
                prev = self.hold["acq"].get(key) or {}
                if final:
                    self.hold["acq"][key] = {"kind": "unknown", "at": now, "tries": ACQ_TRIES}
                elif r is None:
                    self.hold["acq"][key] = {"kind": "unknown", "at": now, "tries": int(prev.get("tries") or 0) + 1}
                else:
                    r.update({"at": now, "tries": int(prev.get("tries") or 0) + 1})
                    self.hold["acq"][key] = r
            done += 1
        return done

    def _acq_one(self, key, c, owner, sample, item, cfg, chains, evm, sol):
        final = False
        self._last_st = None
        ch = c.get("chain")
        nat = (cfg.get("native_symbol") or {}).get(ch) or NATIVE_SYM.get(ch) or "ETH"
        if ch == "sol":
            r = self._acq_sol(owner, c, set(sol), sample)
        else:
            cc = chains.get(ch) if isinstance(chains.get(ch), dict) else {}
            base = str(cc.get("blockscout") or "").rstrip("/")
            try:
                cid = int(cc.get("etherscan_chainid") or ES_CHAINID.get(ch) or 0) or None
            except (TypeError, ValueError):
                cid = ES_CHAINID.get(ch)
            sp9 = ser_parse(key)
            if sp9:
                if base.startswith("https://") and common.chain_discovery(ch, cc) != "rpc" and tid_in(sample, sp9[2]):
                    r = self._acq_ser(base, owner, sp9[1], str(sample), set(evm), nat)
                else:
                    r, final = {"kind": "unknown"}, True
            elif base.startswith("https://") and common.chain_discovery(ch, cc) != "rpc":
                r = self._acq_evm(base, owner, c["ca"], set(evm), nat)
            elif cid and self.env_fn("TJ_ETHERSCAN_KEY") and TXH_RE.match(str(item.get("tx") or "")):
                r = self._acq_es(cid, owner, str(item["tx"]), str(item.get("from") or ""), set(evm), nat)
            else:
                r, final = {"kind": "unknown"}, True
        return r, final

    def _owner_of(self, key):
        for pk in sorted(self.hold["pairs"]):
            it = ((self.hold["pairs"][pk] or {}).get("items") or {}).get(key)
            if it:
                ids = it.get("ids") or []
                return pk.split(":", 1)[1], (ids[0] if ids else None), it
        return None

    def _acq_es(self, cid, addr, txh, frm, mine, native_sym):
        key = self.env_fn("TJ_ETHERSCAN_KEY")
        frm = _h(frm)
        if not frm:
            return None

        def proxy(action):
            q = urllib.parse.urlencode({"chainid": cid, "module": "proxy", "action": action, "txhash": txh, "apikey": key})
            st, d = self._call("etherscan", ES_API + "?" + q)
            return d.get("result") if st == 200 and isinstance(d, dict) and isinstance(d.get("result"), dict) else None
        tx = proxy("eth_getTransactionByHash")
        if tx is None:
            return None
        signer = _h(tx.get("from"))
        try:
            value = int(tx.get("value"), 16) if isinstance(tx.get("value"), str) else None
        except ValueError:
            value = None
        if not signer or value is None or value < 0:
            return None
        paid = value / 1e18 if value > 0 else None
        if signer in mine:
            if frm in mine and frm != addr:
                return {"kind": "internal"}
            if frm == ZERO:
                return {"kind": "mint_paid" if value > 0 else "mint_free", "paid": paid, "sym": native_sym}
            return {"kind": "bought", "paid": paid, "sym": native_sym} if value > 0 else {"kind": "claim"}
        if frm in mine:
            return {"kind": "internal"}
        rc = proxy("eth_getTransactionReceipt")
        if rc is None or not isinstance(rc.get("logs"), list):
            return None
        rec, erc20_paid = set(), False
        for lg in rc.get("logs") or []:
            tp = [str(t).lower() for t in (lg.get("topics") or [])] if isinstance(lg, dict) else []
            if not tp:
                continue
            if tp[0] == TOPIC_TRANSFER and len(tp) == 4:
                rec.add("0x" + tp[2][-40:])
            elif tp[0] in (TOPIC_1155_SINGLE, TOPIC_1155_BATCH) and len(tp) == 4:
                rec.add("0x" + tp[3][-40:])
            elif tp[0] == TOPIC_TRANSFER and len(tp) == 3 and "0x" + tp[1][-40:] == addr:
                erc20_paid = True
        if erc20_paid:
            return {"kind": "bought"}
        if len(rec) >= MASS_N:
            return {"kind": "airdrop_mass", "n": len(rec)}
        return {"kind": "received", "n": len(rec)}

    def _acq_evm(self, base, addr, ca, mine, native_sym):
        legacy = any(ca in v for v in LEGACY_NFT.values())
        typ9 = "ERC-20" if legacy else "ERC-721%2CERC-1155"
        st, d = self._call("blockscout", f"{base}/api/v2/addresses/{addr}/token-transfers?type={typ9}&token={ca}")
        if st != 200 or not isinstance(d, dict):
            return None
        inc = [t for t in (d.get("items") or []) if isinstance(t, dict) and _h(t.get("to")) == addr]
        if not inc:
            return {"kind": "unknown"}
        t = inc[-1]
        txh = str(t.get("transaction_hash") or t.get("tx_hash") or "")
        if not TXH_RE.match(txh) or not _h(t.get("from")):
            return None
        return self._acq_tx(base, addr, ca, txh, _h(t.get("from")), mine, native_sym, legacy)

    def _acq_ser(self, base, addr, ca, tid, mine, native_sym):
        st, d = self._call("blockscout", f"{base}/api/v2/tokens/{ca}/instances/{tid}/transfers")
        if st != 200 or not isinstance(d, dict):
            return None

        def same_tok(t):
            tot = t.get("total") if isinstance(t.get("total"), dict) else {}
            tk = t.get("token") if isinstance(t.get("token"), dict) else {}
            ta = _h(tk.get("address_hash") or tk.get("address")) if tk else ""
            return str(tot.get("token_id") or "") == str(tid) and (not tk or ta == ca)
        inc = [t for t in (d.get("items") or []) if isinstance(t, dict) and _h(t.get("to")) == addr and same_tok(t)]
        if not inc:
            return {"kind": "unknown"}
        t = inc[0]
        txh = str(t.get("transaction_hash") or t.get("tx_hash") or "")
        if not TXH_RE.match(txh) or not _h(t.get("from")):
            return None
        return self._acq_tx(base, addr, ca, txh, _h(t.get("from")), mine, native_sym, False)

    def _acq_tx(self, base, addr, ca, txh, frm, mine, native_sym, legacy):
        if not frm:
            return None
        st, tx = self._call("blockscout", f"{base}/api/v2/transactions/{txh}")
        if st != 200 or not isinstance(tx, dict):
            return None
        signer = _h(tx.get("from"))
        try:
            value = int(str(tx.get("value"))) if isinstance(tx.get("value"), (str, int)) and not isinstance(tx.get("value"), bool) else None
        except ValueError:
            value = None
        if not signer or value is None or value < 0:
            return None
        paid = value / 1e18 if value > 0 else None
        if signer in mine:
            if frm in mine and frm != addr:
                return {"kind": "internal"}
            if frm == ZERO:
                return {"kind": "mint_paid" if value > 0 else "mint_free", "paid": paid, "sym": native_sym}
            if value > 0 or MARKET_RE.search(str(tx.get("method") or "")):
                return {"kind": "bought", "paid": paid, "sym": native_sym}
            return {"kind": "claim"}
        if frm in mine:
            return {"kind": "internal"}
        st, tt = self._call("blockscout", f"{base}/api/v2/transactions/{txh}/token-transfers")
        if st != 200 or not isinstance(tt, dict) or not isinstance(tt.get("items"), list):
            return None
        rec, erc20_paid = set(), False
        for x in tt.get("items") or []:
            if not isinstance(x, dict):
                continue
            typ = str((x.get("token") or {}).get("type") or "") if isinstance(x.get("token"), dict) else ""
            tca = _h((x.get("token") or {}).get("address_hash") or (x.get("token") or {}).get("address")) if isinstance(x.get("token"), dict) else ""
            if typ in ("ERC-721", "ERC-1155", "ERC-404") or (legacy and tca == ca):
                to9 = _h(x.get("to"))
                if to9:
                    rec.add(to9)
            elif typ == "ERC-20" and _h(x.get("from")) == addr:
                erc20_paid = True
        if erc20_paid:
            return {"kind": "bought"}
        if len(rec) >= MASS_N:
            return {"kind": "airdrop_mass", "n": len(rec)}
        return {"kind": "received", "n": len(rec)}

    def _acq_sol(self, owner, col, mine, mint=None):
        mint = mint or col.get("sample")
        if not mint or not SOL_RE.match(str(mint)):
            return None
        sig = None
        if col.get("compressed"):
            st, res = self._helius("getSignaturesForAsset", {"id": mint, "page": 1, "limit": 100})
            items = (res or {}).get("items") if isinstance(res, dict) else None
            if st != 200 or not isinstance(items, list):
                return None
            if items and isinstance(items[-1], list) and items[-1]:
                sig = str(items[-1][0])
        else:
            st, res = self._helius("getTokenAccountsByOwner", [owner, {"mint": mint}, {"encoding": "jsonParsed"}])
            vals = (res or {}).get("value") if isinstance(res, dict) else None
            if st != 200 or not isinstance(vals, list):
                return None
            if not vals or not SOL_RE.match(str((vals[0] or {}).get("pubkey") or "")):
                return {"kind": "unknown"}
            st, sigs = self._helius("getSignaturesForAddress", [vals[0]["pubkey"], {"limit": 100}])
            if st != 200 or not isinstance(sigs, list):
                return None
            if sigs and isinstance(sigs[-1], dict):
                sig = str(sigs[-1].get("signature") or "")
        if not sig or not SIG_RE.match(sig):
            return {"kind": "unknown"}
        st, tx = self._helius("getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}])
        return parse_sol_acq(tx, owner, mine) if st == 200 else None

    def canon(self, key: str) -> str:
        if key.startswith("sol:") and not key.startswith("sol:me/"):
            sym = ((self.fp.get("map") or {}).get(key) or {}).get("me")
            if sym and ME_SYM_RE.match(sym):
                return "sol:me/" + sym
        return key

    def _neg(self, key) -> bool:
        return float(((self.fp.get("neg") or {}).get(key) or {}).get("until") or 0) > self.now()

    def _set_neg(self, key, src):
        with self.lock:
            now = self.now()
            until = now + NEG_TTL
            m = (self.fp.get("map") or {}).get(key)
            if isinstance(m, dict) and (m.get("os") == "" or m.get("me") == ""):
                rt = _num(m.get("retry"))
                if rt is not None and now < rt < until:
                    until = rt
            self.fp.setdefault("neg", {})[key] = {"until": until, "src": src}

    def _mark(self, key, out):
        if out == "budget":
            return
        with self.lock:
            now = self.now()
            self.fp.setdefault("chk", {})[key] = now
            rt = self.fp.setdefault("retry", {})
            if out in ("ok", "none"):
                rt.pop(key, None)
            else:
                rt[key] = now

    def fetch_fp(self, key, col):
        if ser_parse(key) or ab_parent_key(key) or col_ab_parent(col):
            return self._fetch_series(key, col)
        chain = col.get("chain")
        rec, out = None, "err"
        if chain == "sol" or chain == "os":
            if chain == "os":
                rec, out = self._fp_os_slug(col.get("os") or "", key)
            else:
                sym, out = (col.get("me"), "ok") if col.get("me") else self._me_symbol(key, col)
                if out == "ok" and not sym:
                    out = "none"
                if out == "ok":
                    ck = "sol:me/" + sym
                    prev = (self.fp.get("fp") or {}).get(ck)
                    if prev and self.now() - float(prev.get("at") or 0) < 600 and key != ck:
                        self._mark(key, "ok")
                        return "ok"
                    st, d = self._call("magiceden", f"{ME_HOST}/v2/collections/{urllib.parse.quote(sym, safe='')}/stats")
                    out = self._st_out(st)
                    if st == 200:
                        im = id_match(d, "symbol", sym)
                        rec = parse_me_stats(d, sym) if im == "same" else None
                        out = "ok" if rec else ("none" if (im == "same" and floor_shape(d, "floorPrice")) else "err")
                    self._mark(key, out)
                    key = ck
        else:
            os_first = bool(self._os_key()) and chain in OS_CHAIN and ADDR_RE.match(str(col.get("ca") or ""))
            os_out, os_last = None, None
            if os_first:
                rec, out = self._fp_os_contract(key, chain, col.get("ca"))
                os_out = out
                if out == "ok" and rec:
                    rec.setdefault("src", "os")
                    if rec.get("basis") == "last":
                        os_last, rec, out = rec, None, "none"
            plat = CG_PLATFORM.get(chain)
            if not (os_first and out == "ok" and rec) and plat and ADDR_RE.match(str(col.get("ca") or "")):
                rec, out = None, "none"
                st, d = self._cg_get(f"{CG_HOST}/api/v3/nfts/{plat}/contract/{col['ca']}")
                out = self._st_out(st)
                if st == 200:
                    im = id_match(d, "contract_address", col["ca"], _h)
                    rec = parse_cg(d) if im == "same" else None
                    out = "ok" if rec else ("none" if (im == "same" and floor_shape(d, "native_currency", parent="floor_price")) else "err")
                    fp9 = d.get("floor_price") if isinstance(d, dict) and isinstance(d.get("floor_price"), dict) else {}
                    if rec is None and (_num(fp9.get("native_currency")) or 0) > 0:
                        out = "err"
                if out == "none" and os_out not in (None, "none", "ok"):
                    rec, out = None, os_out
            if os_last and not (out == "ok" and rec):
                rec, out = os_last, "ok"
        if self._hid_seen():
            return "budget"
        now = self.now()
        self._mark(key, out)
        with self.lock:
            if out == "ok" and rec:
                rec["at"] = now
                self.fp["fp"][key] = rec
                (self.fp.get("neg") or {}).pop(key, None)
                self._hist_put(key, rec)
            elif out == "none":
                self._set_neg(key, "cg" if chain not in ("sol", "os") else ("me" if chain == "sol" else "os"))
                self.fp["fp"].pop(key, None)
            elif key in self.fp["fp"]:
                self.fp["fp"][key]["err"] = out
        return out

    def _ser_sample(self, key, col, proj):
        with self.lock:
            own = self._owner_of(key)
        for t in ([own[1]] if own else []) + [(col or {}).get("sample")]:
            if t is not None and tid_in(t, proj):
                return str(t)
        return None

    def _fetch_series(self, key, col):
        now = self.now()
        sp = ser_parse(key)
        if not sp:
            self._mark(key, "none")
            return "none"
        ch, ca, proj = sp
        k = self._os_key()
        rec, out, nm = None, "none", None
        tid = self._ser_sample(key, col, proj)
        if not k or ch not in OS_CHAIN or not tid:
            out = "nosrc"
        else:
            hk = {"x-api-key": k, "accept": "application/json"}
            with self.lock:
                m = dict((self.fp.get("map") or {}).get(key) or {})
            slug = m.get("os") if (m.get("ca") == ca and tid_in(m.get("tid"), proj)) else None
            if slug == "" and not (m.get("okf") == _kfp(k) and now < float(m.get("retry") or 0)):
                slug = None
            if slug is None:
                st, d = self._call("opensea", f"{OS_HOST}/api/v2/chain/{OS_CHAIN[ch]}/contract/{ca}/nfts/{tid}", headers=hk)
                n9 = d.get("nft") if (st == 200 and isinstance(d, dict)) else None
                if st == 200 and not (isinstance(n9, dict) and _h(n9.get("contract")) == ca and str(n9.get("identifier") or "") == str(tid)):
                    out = "err"
                elif st == 200 and coll_shape(n9, "collection", OS_SLUG_RE)[0] == "err":
                    out = "err"
                elif st in (200, 404):
                    info = parse_os_nft(d) if st == 200 else None
                    slug = info["slug"] if info else ""
                    nm = (info or {}).get("name") or None
                    ent = {"os": slug, "ca": ca, "tid": str(tid), "at": now}
                    if not slug:
                        ent.update({"okf": _kfp(k), "retry": now + NEG_TTL})
                    if nm:
                        ent["name"] = nm
                    with self.lock:
                        self.fp.setdefault("map", {})[key] = ent
                    if not slug:
                        out = "none"
                else:
                    out = self._st_out(st)
            if slug:
                rec, out = self._fp_os_slug(slug, key)
        if self._hid_seen():
            return "budget"
        self._mark(key, out)
        with self.lock:
            fpm = self.fp.setdefault("fp", {})
            prev = fpm.get(key)
            if isinstance(prev, dict) and prev.get("ser") != key:
                fpm.pop(key, None)
                (self.fp.get("hist") or {}).pop(key, None)
                prev = None
            if out == "ok" and rec:
                rec.update({"at": now, "ser": key, "src": "os"})
                fpm[key] = rec
                (self.fp.get("neg") or {}).pop(key, None)
                self._hist_put(key, rec)
            elif out == "none":
                self._set_neg(key, "os")
                fpm.pop(key, None)
            elif prev is not None:
                prev["err"] = "nokey" if out == "nosrc" else out
            c9 = self.hold["cols"].get(key)
            if nm and isinstance(c9, dict) and str(c9.get("name") or "").startswith(AB_NAME + " #"):
                c9["name"] = ser_name(nm, proj)
        return "err" if out == "nosrc" else out

    @staticmethod
    def _st_out(st):
        if st == 200:
            return "ok"
        if st == 404:
            return "none"
        return "budget" if st in (NOBUDGET, BLOCKED, 429, HIDDEN) else "err"

    def _me_symbol(self, key, col):
        now = self.now()
        m = (self.fp.get("map") or {}).get(key) or {}
        if "me" in m:
            s0 = m.get("me")
            if s0 and ME_SYM_RE.match(str(s0)):
                return s0, "ok"
            if s0 == "" and now < float(m.get("retry") or 0):
                return "", "ok"
        mint = col.get("sample") or col.get("ca")
        if not mint or not SOL_RE.match(str(mint)):
            return None, "err"
        st, d = self._call("magiceden", f"{ME_HOST}/v2/tokens/{mint}")
        if st == 200:
            if id_match(d, "mintAddress", mint) != "same":
                return None, "err"
            cs, sym = coll_shape(d, "collection", ME_SYM_RE)
            if cs == "err" and "collection" not in d:
                cs, sym = "none", ""
            if cs == "err":
                return None, "err"
        elif st == 404:
            sym = ""
        else:
            return None, self._st_out(st)
        ent = {"me": sym, "at": now}
        if not sym:
            ent["retry"] = now + NEG_TTL
        with self.lock:
            self.fp.setdefault("map", {})[key] = ent
        return sym, "ok"

    def _fp_os_contract(self, key, chain, ca):
        now = self.now()
        k = self._os_key()
        with self.lock:
            m = dict((self.fp.get("map") or {}).get(key) or {})
        slug = m.get("os")
        if slug == "" and not (m.get("okf") == _kfp(k) and now < float(m.get("retry") or 0)):
            slug = None
        hk = {"x-api-key": k, "accept": "application/json"}
        if slug is None:
            st, d = self._call("opensea", f"{OS_HOST}/api/v2/chain/{OS_CHAIN[chain]}/contract/{ca}", headers=hk)
            if st not in (200, 404):
                return None, self._st_out(st)
            if st == 200:
                if id_match(d, "address", ca, _h) != "same":
                    return None, "err"
                cs, slug = coll_shape(d, "collection", OS_SLUG_RE)
                if cs == "err":
                    return None, "err"
            else:
                slug = ""
            with self.lock:
                ent = self.fp.setdefault("map", {}).setdefault(key, {})
                ent["os"] = slug
                ent["at"] = now
                if slug:
                    ent.pop("okf", None)
                    ent.pop("retry", None)
                else:
                    ent.update({"okf": _kfp(k), "retry": now + NEG_TTL})
        if not slug:
            return None, "none"
        return self._fp_os_slug(slug, key)

    def _os_last(self, key, slug):
        now = self.now()
        with self.lock:
            prev = (self.fp.get("fp") or {}).get(key) if key else None
        if ser_parse(key) and isinstance(prev, dict) and prev.get("ser") != key:
            prev = None
        pl = prev.get("last") if (isinstance(prev, dict) and isinstance(prev.get("last"), dict) and prev.get("id") == slug) else None
        if pl and 0 <= now - float(pl.get("chk") or 0) < LAST_SALE_EVERY:
            return dict(pl), "ok"
        hk = {"x-api-key": self._os_key(), "accept": "application/json"}
        st, d = self._call("opensea", f"{OS_HOST}/api/v2/events/collection/{slug}?event_type=sale&limit=1", headers=hk)
        la = parse_os_last_sale(d, slug) if st == 200 else None
        if la is not None:
            return dict(la, chk=now), "ok"
        return (dict(pl) if pl else None), (self._st_out(st) if st != 200 else "err")

    def _fp_os_slug(self, slug, key=None):
        if not self._os_key() or not OS_SLUG_RE.match(str(slug or "")):
            return None, "err"
        hk = {"x-api-key": self._os_key(), "accept": "application/json"}
        st, d = self._call("opensea", f"{OS_HOST}/api/v2/collections/{slug}/stats", headers=hk)
        if st != 200:
            return None, self._st_out(st)
        rec = parse_os_stats(d, slug)
        if rec and not rec.get("sym"):
            return None, "err"
        busy = rec and any((_num(rec.get(f)) or 0) > 0 for f in ("vol24", "sales24", "vol7", "sales7", "sales30"))
        if rec and busy:
            return rec, "ok"
        if not isinstance(d, dict) or not isinstance(d.get("total"), dict) or (not rec and not floor_shape(d, "floor_price", parent="total")):
            return None, "err"
        la, last_out = self._os_last(key, slug)
        if rec:
            if la:
                rec["last"] = la
            return rec, "ok"
        if last_out != "ok":
            return None, last_out
        now = self.now()
        age = (now - float(la["at"])) if (la and la.get("at")) else None
        if age is not None and age < 0:
            return None, "err"
        if age is not None and age <= THIN_MAX_DAYS * 86400 and not la.get("px"):
            return None, "err"
        if la and la.get("at") and la.get("px") and 0 <= age <= THIN_MAX_DAYS * 86400:
            iv = {str(x.get("interval")): x for x in (d.get("intervals") or []) if isinstance(x, dict)}
            return {"src": "os", "basis": "last", "native": float(la["px"]), "sym": "ETH", "usd": None, "vol24": None, "vol7": None,
                    "sales24": None, "sales7": _num((iv.get("seven_day") or {}).get("sales")), "sales30": _num((iv.get("thirty_day") or {}).get("sales")),
                    "vol30": None, "chg24": None, "chg7": None, "listed": None, "id": slug, "name": None, "last": la,
                    "url": "https://opensea.io/collection/" + urllib.parse.quote(slug, safe="")}, "ok"
        return None, "none"

    def _hist_put(self, key, rec):
        px = self._native_usd(rec)
        usd = rec["native"] * px if px else _num(rec.get("usd"))
        d = today_iso(self.now())
        h = self.fp.setdefault("hist", {}).setdefault(key, [])
        row = [d, rec["native"], usd, _num(rec.get("vol24")) or _num(rec.get("vol7")) or 0.0]
        if rec.get("basis") == "last":
            la = rec.get("last") if isinstance(rec.get("last"), dict) else {}
            row.append({"basis": "last", "at": self.now(), "last": {"at": la.get("at"), "px": la.get("px"), "sym": la.get("sym")},
                        "sales7": rec.get("sales7"), "sales30": rec.get("sales30")})
        if h and h[-1][0] == d:
            h[-1] = row
        else:
            h.append(row)
        del h[:-MAX_HIST]

    def _native_usd(self, rec):
        sym = str((rec or {}).get("sym") or "").upper()
        if not sym:
            return None
        try:
            p = self.px_fn(sym)
        except Exception:
            p = None
        return float(p) if _fin(p) and p > 0 else None

    def _neg_eff(self, key) -> bool:
        ent = (self.fp.get("neg") or {}).get(key)
        if not isinstance(ent, dict) or float(ent.get("until") or 0) <= self.now():
            return False
        return not (ser_parse(key) and ent.get("src") != "os")

    def _os_path(self, key, c, rec) -> bool:
        if not self._os_key():
            return False
        if rec and rec.get("src") not in (None, "os"):
            return False
        ch = (c or {}).get("chain")
        return bool(ser_parse(key)) or ch == "os" or (ch in OS_CHAIN and bool(ADDR_RE.match(str((c or {}).get("ca") or ""))))

    def due_fp(self, prefs=None) -> list:
        prefs = prefs if prefs is not None else self._prefs_or_empty()
        off9 = _off_chains(self._cfg())
        now = self.now()
        hidden, promoted = set(prefs.get("hidden") or []), set(prefs.get("promoted") or [])
        trusted = set(prefs.get("notspam") or [])
        watch = {w["key"]: w for w in prefs.get("watch") or [] if isinstance(w, dict) and w.get("key")}
        out, seen = [], set()
        ishid = self._hid_fn(prefs)
        with self.lock:
            chk = self.fp.get("chk") or {}
            fpm = self.fp.get("fp") or {}
            acqm = self.hold.get("acq") or {}
            retry = self.fp.get("retry") if isinstance(self.fp.get("retry"), dict) else {}
            os_rest = bool((self.fp.get("hosts") or {}).get((urllib.parse.urlsplit(OS_HOST).hostname or "").lower()))
            for raw, c in list(self.hold["cols"].items()) + [(k, w) for k, w in watch.items() if k not in self.hold["cols"]]:
                key = self.canon(raw)
                if off9 and ((c.get("chain") if isinstance(c, dict) else None) or str(key).split(":", 1)[0]) in off9:
                    self.urgent.discard(key)
                    self.urgent.discard(raw)
                    continue
                if key in seen:
                    continue
                seen.add(key)
                if key != raw and raw in chk and key not in chk:
                    chk = {**chk, key: chk[raw]}
                if ishid(key):
                    self.urgent.discard(key)
                    self.urgent.discard(raw)
                    continue
                if c.get("lp") and key not in promoted and key not in watch:
                    continue
                if ab_parent_key(key) or col_ab_parent(c):
                    self.urgent.discard(key)
                    self.urgent.discard(raw)
                    continue
                rec = fpm.get(key)
                if ser_parse(key) and isinstance(rec, dict) and rec.get("ser") != key:
                    rec = None
                tracked = key in promoted or key in watch or (bool(rec) and classify(c, rec, acqm.get(raw), trust=key in trusted, now=now)[0] == "auto")
                if not tracked and key not in trusted and strong_spam(c) and not rec:
                    continue
                unconf = key in retry or raw in retry
                if not tracked and key in chk and not rec and not unconf and \
                        classify(c, None, acqm.get(raw), trust=key in trusted, now=now)[0] == "spam":
                    continue
                if (self._neg_eff(key) or self._neg_eff(raw)) and key not in self.urgent:
                    continue
                if self._os_path(key, c, rec):
                    every = OS_TRACK_EVERY if tracked else OS_CAND_EVERY
                else:
                    every = FP_EVERY if tracked else CAND_FP_EVERY
                if unconf:
                    every = min(every, ERR_RETRY)
                last = float(chk.get(key) or 0)
                if key in self.urgent or now - last >= every:
                    first_ser = bool(ser_parse(key)) and not rec and not last and not os_rest
                    out.append((0 if key in self.urgent else (1 if tracked or first_ser else 2), last, raw, c, key))
        out.sort(key=lambda x: (x[0], x[1]))
        return [(r, c) for _p, _l, r, c, _k in out]

    def refresh_fp(self) -> dict:
        try:
            self._os_sync_key()
        except Exception as e:
            _warn("NFT 오픈시 키 확인 실패: %s", type(e).__name__)
        n = {"ok": 0, "none": 0, "err": 0, "budget": 0}
        for key, c in self.due_fp():
            ck = self.canon(key)
            if self._hid_now(key):
                self.urgent.discard(key)
                self.urgent.discard(ck)
                continue
            with self._item(key):
                out = self.fetch_fp(key, c)
            n[out] = n.get(out, 0) + 1
            self.urgent.discard(key)
            self.urgent.discard(ck)
            self.urgent.discard(self.canon(key))
            if out == "budget":
                continue
        self.save()
        return n

    def _hid_now(self, key) -> bool:
        f = self._hid_fn(self._prefs_or_empty())
        return f(key) or f(self.canon(key))

    @contextlib.contextmanager
    def _item(self, key):
        tl = self._tlocal()
        old = (getattr(tl, "key", None), getattr(tl, "hid", False))
        tl.key, tl.hid = key, False
        try:
            yield
        finally:
            tl.key, tl.hid = old

    def _tlocal(self):
        tl = self.__dict__.get("_tl")
        if tl is None:
            tl = self.__dict__.setdefault("_tl", threading.local())
        return tl

    def _item_key(self):
        return getattr(self._tlocal(), "key", None)

    def _item_hid(self) -> bool:
        tl = self._tlocal()
        k = getattr(tl, "key", None)
        if not k:
            return False
        if getattr(tl, "hid", False):
            return True
        if self._hid_now(k):
            tl.hid = True
            return True
        return False

    def _hid_seen(self) -> bool:
        tl = self._tlocal()
        return bool(getattr(tl, "key", None)) and bool(getattr(tl, "hid", False))

    def _prefs_or_empty(self):
        try:
            return self.prefs()
        except StoreError:
            return empty_prefs()

    def save(self):
        with self.lock:
            atomic_write(self.hold_path, _jsafe(self.hold))
            atomic_write(self.fp_path, _jsafe(self.fp))

    def _ab_backup(self) -> bool:
        ok = True
        for path in (self.hold_path, self.fp_path, self.prefs_path):
            bak = path + BAK_SUFFIX
            if os.path.exists(bak) or not os.path.exists(path):
                continue
            try:
                with open(path, "rb") as f:
                    raw = f.read()
                d = os.path.dirname(bak)
                tmp = os.path.join(d, ".nft_bak_%s_%s.tmp" % (os.getpid(), secrets.token_hex(4)))
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    with os.fdopen(fd, "wb") as f:
                        f.write(raw)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp, bak)
                except BaseException:
                    with contextlib.suppress(OSError):
                        os.unlink(tmp)
                    raise
            except OSError as e:
                _warn("NFT 시리즈 이관 전 사본 실패(%s) — 이관 미룸", type(e).__name__)
                ok = False
        return ok

    def _ab_migrate(self) -> int:
        now = self.now()
        pkeys = _pref_keys(self._prefs_or_empty())
        with self.lock:
            need = [pk for pk, p in self.hold["pairs"].items()
                    if isinstance(p, dict) and not p.get("rs")
                    and any(ab_parent_key(k) and not (a or {}).get("unsplit") for k, a in (p.get("items") or {}).items())]
            keys = set(self.hold["cols"]) | {k for p in self.hold["pairs"].values() if isinstance(p, dict) for k in (p.get("items") or {})}
            keys |= set(k for k in (self.hold.get("acq") or {}) if isinstance(k, str))
            keys |= pkeys
            for fld in ("fp", "hist", "map", "neg", "chk", "retry"):
                v9 = self.fp.get(fld)
                keys |= set(k for k in (v9 if isinstance(v9, dict) else {}) if isinstance(k, str))
            parents = set()
            for k in keys:
                sp = ser_parse(k)
                if sp:
                    parents.add(f"{sp[0]}:{sp[1]}")
                elif ab_parent_key(k):
                    parents.add(k)
            negm = self.fp.get("neg") or {}
            unsafe = sorted(k for k in parents if k in (self.fp.get("fp") or {}) or k in (self.fp.get("hist") or {})
                            or not (isinstance(negm.get(k), dict) and negm[k].get("src") == "ab" and float(negm[k].get("until") or 0) >= AB_BLOCK_UNTIL))
        if (need or unsafe) and not self._ab_backup():
            return 0
        with self.lock:
            for k in unsafe:
                (self.fp.get("fp") or {}).pop(k, None)
                (self.fp.get("hist") or {}).pop(k, None)
                self.fp.setdefault("neg", {})[k] = {"until": AB_BLOCK_UNTIL, "src": "ab"}
            for pk in need:
                p = self.hold["pairs"].get(pk)
                if isinstance(p, dict):
                    p["rs"] = 1
            pend = sum(1 for p in self.hold["pairs"].values() if isinstance(p, dict) and p.get("rs"))
            mig = self.hold.get("abmig") if isinstance(self.hold.get("abmig"), dict) else {}
            if mig.get("v") != AB_MIG_V:
                mig = {"v": AB_MIG_V, "at": now}
            mig["pending"] = pend
            if pend:
                mig.pop("done", None)
            elif not mig.get("done"):
                mig["done"] = now
            changed = bool(need or unsafe) or self.hold.get("abmig") != mig
            self.hold["abmig"] = mig
        if changed:
            self.save()
        return len(need)

    def _ab_kids(self) -> dict:
        out = {}
        with self.lock:
            for p in self.hold["pairs"].values():
                for k in ((p or {}).get("items") or {}):
                    sp = ser_parse(k)
                    if sp:
                        out.setdefault(f"{sp[0]}:{sp[1]}", set()).add(k)
        return out

    def _ab_prefs_sync(self) -> bool:
        kids = self._ab_kids()
        if not kids:
            return False
        with self.prefs_lock:
            try:
                p = load_prefs(self.prefs_path)
            except StoreError:
                return False
            led = p.get("abinh") if isinstance(p.get("abinh"), dict) else {}
            changed = full = False
            wkeys = [w.get("key") for w in p.get("watch") or [] if isinstance(w, dict)]
            for lname, src in (("hidden", p["hidden"]), ("promoted", p["promoted"]), ("notspam", p["notspam"]), ("promoted", wkeys)):
                lk = lname if src is not wkeys else "watch"
                book = led.get(lk) if isinstance(led.get(lk), dict) else {}
                for par in [k for k in list(src) if ab_parent_key(k)]:
                    done = set(x for x in (book.get(par) or []) if isinstance(x, str))
                    for kid in sorted(kids.get(par, ())):
                        if kid in done:
                            continue
                        dst = p[lname]
                        if kid not in dst and not (lname == "promoted" and kid in p["hidden"]):
                            if len(dst) >= MAX_PREF_KEYS:
                                full = True
                                continue
                            dst.append(kid)
                            if lname == "hidden":
                                p["promoted"] = [x for x in p["promoted"] if x != kid]
                        done.add(kid)
                        changed = True
                    book[par] = sorted(done)
                if book:
                    led[lk] = book
            if full:
                _warn("NFT 설정 목록 상한(%s) — 일부 시리즈에 계약 설정을 아직 못 이음(숨김은 계속 효력)", MAX_PREF_KEYS)
            if not changed:
                return False
            p["abinh"] = led
            p["updated"] = int(self.now())
            p["v"] = SCHEMA
            atomic_write(self.prefs_path, _jsafe(p))
        return True

    @staticmethod
    def _hid_fn(prefs):
        hidden = set((prefs or {}).get("hidden") or [])
        ab = (prefs or {}).get("abinh")
        book = ab.get("hidden") if isinstance(ab, dict) and isinstance(ab.get("hidden"), dict) else {}

        def f(key):
            if key in hidden:
                return True
            sp = ser_parse(key)
            if not sp:
                return False
            par = f"{sp[0]}:{sp[1]}"
            return par in hidden and key not in set(x for x in (book.get(par) or []) if isinstance(x, str))
        return f

    def _os_key(self) -> str:
        try:
            return str(self.env_fn("TJ_OPENSEA_KEY") or "").strip()
        except Exception:
            return ""

    def _os_sync_key(self) -> int:
        k = self._os_key()
        kf = _kfp(k) if k else ""
        with self.lock:
            st = self.fp.get("oskey") if isinstance(self.fp.get("oskey"), dict) else {}
            if st.get("fp") == kf:
                return 0
            self.fp["oskey"] = {"fp": kf, "at": self.now()}
            n = 0
            if kf:
                mp, neg, chk = self.fp.setdefault("map", {}), self.fp.setdefault("neg", {}), self.fp.setdefault("chk", {})
                for key in list(set(neg) | set(mp)):
                    m = mp.get(key) if isinstance(mp.get(key), dict) else {}
                    ok_map = bool(m.get("os"))
                    os_ok = (bool(ser_parse(key)) or (key.startswith("os:") and bool(OS_SLUG_RE.match(key[3:])))
                             or (":" in key and key.split(":", 1)[0] in OS_CHAIN and ADDR_RE.match(key.split(":", 1)[1] or "")))
                    if not os_ok or ok_map or ab_parent_key(key):
                        continue
                    hit = False
                    if "os" in m:
                        mp[key] = {k9: v9 for k9, v9 in m.items() if k9 not in ("os", "okf", "retry")}
                        if not mp[key]:
                            mp.pop(key, None)
                        hit = True
                    if isinstance(neg.get(key), dict) and neg[key].get("src") in ("cg", "os"):
                        neg.pop(key, None)
                        hit = True
                    if hit:
                        chk.pop(key, None)
                        n += 1
        self.save()
        return n

    def run_once(self, fp_only: bool = False) -> dict:
        out = {"scan": 0}
        if not self.enabled():
            return out
        with self.run_lock:
            try:
                out["abmig"] = self._ab_migrate()
            except Exception as e:
                _warn("NFT 시리즈 이관 표식 실패: %s", type(e).__name__)
            if not fp_only:
                out["scan"] = self.scan()
                if out["scan"]:
                    self._ab_migrate()
            try:
                out["abprefs"] = self._ab_prefs_sync()
            except Exception as e:
                _warn("NFT 시리즈 설정 잇기 실패: %s", type(e).__name__)
            out["fp"] = self.refresh_fp()
            if fp_only:
                return out
            out["acq"] = self.acquire_lookups()
            if out["acq"]:
                self.save()
            try:
                out["alert"] = self.maybe_alert()
            except Exception as e:
                _warn("NFT 코인게코 지연 알림 판정 실패: %s", type(e).__name__)
        return out

    def _loop_wait(self) -> float:
        if self.urgent:
            return 30.0
        wait = float(OS_TRACK_EVERY if self._os_key() else FP_EVERY)
        if self._retry_live():
            wait = min(wait, float(ERR_RETRY))
        return wait

    def _retry_live(self) -> bool:
        prefs = self._prefs_or_empty()
        ishid = self._hid_fn(prefs)
        watch = {w["key"] for w in prefs.get("watch") or [] if isinstance(w, dict) and isinstance(w.get("key"), str)}
        with self.lock:
            rt = self.fp.get("retry") if isinstance(self.fp.get("retry"), dict) else {}
            if not rt:
                return False
            cols = self.hold.get("cols") or {}
            for k in list(rt):
                if not isinstance(k, str) or ab_parent_key(k):
                    continue
                ck = self.canon(k)
                if (k in cols or ck in cols or k in watch or ck in watch) and not (ishid(k) or ishid(ck)):
                    return True
        return False

    def loop(self):
        self.sleep(FIRST_DELAY)
        full_at = 0.0
        while True:
            try:
                self.cg_info_tick()
            except Exception as e:
                _warn("코인게코 프로 한도(/key) 확인 실패: %s", type(e).__name__)
            try:
                full = self.now() - full_at >= FP_EVERY - 60 or bool(self.urgent)
                self.run_once(fp_only=not full)
                if full:
                    full_at = self.now()
            except Exception as e:
                _warn("NFT 바퀴 실패: %s", type(e).__name__)
            self.wake.wait(self._loop_wait())
            self.wake.clear()

    def _off_at(self, cfg, now) -> dict:
        off = _off_chains(cfg)
        if not off:
            return {}
        try:
            raw = common.read_json(common.CONFIG_PATH, {}) or {}
        except (Exception, SystemExit):
            raw = {}
        rch = raw.get("chains") if isinstance(raw, dict) and isinstance(raw.get("chains"), dict) else {}
        out = {}
        for ch in off:
            mk = (rch.get(ch) or {}).get("_chainoff") if isinstance(rch.get(ch), dict) else None
            at = _num(mk.get("at")) if isinstance(mk, dict) else None
            if not (at and 0 < at <= now):
                with self.lock:
                    ts = [_num(p.get("at")) for pk, p in (self.hold.get("pairs") or {}).items()
                          if str(pk).split(":", 1)[0] == ch and isinstance(p, dict)]
                ts = [t for t in ts if t and 0 < t <= now]
                at = max(ts) if ts else None
            if at:
                out[ch] = float(at)
        return out

    def view(self, cfg=None) -> dict:
        cfg = cfg if cfg is not None else self._cfg()
        try:
            prefs = self.prefs()
            perr = None
        except StoreError as e:
            prefs, perr = empty_prefs(), common.safe_err(e)
        evm, sol = registered(cfg)
        labels = {**evm, **sol}
        rate = self.rate_fn() or 0.0
        rate = float(rate) if _fin(rate) and rate > 0 else 0.0
        now = self.now()
        off_at9 = self._off_at(cfg, now)
        td = today_iso(now)
        hidden, promoted = set(prefs.get("hidden") or []), set(prefs.get("promoted") or [])
        trusted = set(prefs.get("notspam") or [])
        watch = {w["key"]: w for w in prefs.get("watch") or [] if isinstance(w, dict) and w.get("key")}
        with self.lock:
            agg, members = {}, {}
            for pk, p in self.hold["pairs"].items():
                addr = pk.split(":", 1)[1]
                for raw, a in (p.get("items") or {}).items():
                    key = self.canon(raw)
                    members.setdefault(key, set()).add(raw)
                    g = agg.setdefault(key, {"n": 0, "w": {}, "partial": False})
                    g["n"] += int(a.get("n") or 0)
                    g["w"][addr] = g["w"].get(addr, 0) + int(a.get("n") or 0)
                    g["partial"] = g["partial"] or bool(a.get("partial"))
            cols = {}
            for key, mem in members.items():
                ms = sorted(mem)
                c0 = dict(self.hold["cols"].get(ms[0]) or {})
                if key != ms[0] or len(ms) > 1:
                    c0["name"] = re.sub(r"\s*#\d+\s*$", "", str(c0.get("name") or "")) or key.split("/", 1)[-1]
                    c0["ca"] = key.split("/", 1)[-1] if key.startswith("sol:me/") else c0.get("ca")
                    c0["lp"] = any((self.hold["cols"].get(m) or {}).get("lp") for m in ms)
                cols[key] = c0
            for raw, c9 in self.hold["cols"].items():
                cols.setdefault(self.canon(raw), dict(c9))
            fpm = {k: dict(v) for k, v in (self.fp.get("fp") or {}).items()}
            hist = {k: [list(r) for r in v[-8:]] for k, v in (self.fp.get("hist") or {}).items()}
            acq = {}
            rank = {"bought": 0, "mint_paid": 1, "mint_free": 2, "claim": 3, "internal": 4, "airdrop_mass": 5, "received": 6, "unknown": 7}
            for raw, a9 in (self.hold.get("acq") or {}).items():
                k9 = self.canon(raw)
                if k9 not in acq or rank.get(a9.get("kind"), 9) < rank.get(acq[k9].get("kind"), 9):
                    acq[k9] = a9
            negs = {k for k in (self.fp.get("neg") or {}) if self._neg_eff(k)}
            scan = dict(self.hold.get("scan") or {})
            abmig = dict(self.hold.get("abmig") or {}) if isinstance(self.hold.get("abmig"), dict) else {}
            hosts = {h: v for h, v in (self.fp.get("hosts") or {}).items() if float(v.get("until") or 0) > now}
        tracked, cands, spam, hid, wl = [], [], [], [], []
        ishid = self._hid_fn(prefs)
        lp_n = lp_items = 0
        tot = {"usd": 0.0, "krw": 0.0, "n": 0, "items": 0, "pending": 0, "partial": 0, "dday_usd": 0.0, "dday_krw": 0.0,
               "old_usd": 0.0, "old_krw": 0.0, "old_n": 0, "split": 0}
        for key in sorted(set(agg) | set(watch)):
            g = agg.get(key) or {"n": 0, "w": {}, "partial": False}
            c = dict(cols.get(key) or {}, partial=bool(g.get("partial")))
            w9 = watch.get(key)
            if not cols.get(key) and w9:
                c = {"chain": w9.get("chain"), "ca": w9.get("ca") or w9.get("me") or w9.get("os"), "name": w9.get("label") or "",
                     "sym": "", "std": ""}
                if w9.get("proj") is not None:
                    c.update({"pca": w9.get("pca"), "proj": w9.get("proj"), "sample": w9.get("sample"), "plat": AB_NAME, "rep": "ok",
                              "name": w9.get("label") or f"{AB_NAME} #{w9.get('proj')}"})
            if c.get("lp") and key not in promoted:
                lp_n += 1
                lp_items += g["n"]
                continue
            rec = fpm.get(key)
            split = ab_parent_key(key) or col_ab_parent(c)
            if split or (ser_parse(key) and isinstance(rec, dict) and rec.get("ser") != key):
                rec = None
            hk = [r for r in hist.get(key, []) if _hist_row_ok(r, c, acq.get(key), key in trusted)]
            ev_now9 = off_at9.get(c.get("chain") or str(key).split(":", 1)[0], now) if off_at9 else now
            ev_td9 = today_iso(ev_now9)
            hrows = [r for r in hk if r and (datetime.strptime(ev_td9, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d") <= r[0] <= ev_td9]
            hall = [] if (split or (ser_parse(key) and rec is None)) else hk
            cls, why = classify(c, rec, acq.get(key), hrows if hall else [], trust=key in trusted, now=ev_now9)
            prc = price_rec(c, rec, acq.get(key), key in trusted, ev_now9)
            row = self._row(key, c, g, prc, hall if prc is not None else [], acq.get(key), labels, rate, now, td)
            if g.get("partial"):
                row["value"], row["dday"], row["partial"] = None, None, True
            if split:
                row["value"], row["dday"], row["ab_split"] = None, None, True
            row.update({"cls": cls, "reason": why, "reason_ko": REASON_KO.get(why, why), "promoted": key in promoted, "notspam": key in trusted,
                        "hidden": ishid(key), "watch": key in watch, "neg": key in negs})
            if w9:
                row["watch_label"] = w9.get("label") or ""
            if ishid(key):
                hid.append(row)
                continue
            if g["n"] <= 0:
                if w9:
                    wl.append(row)
                continue
            if cls == "auto" or key in promoted or w9:
                tracked.append(row)
                tot["n"] += 1
                tot["items"] += g["n"]
                v = row.get("value")
                if v and v.get("usd") is not None:
                    tot["usd"] += v["usd"]
                    tot["krw"] += v.get("krw") or 0.0
                    if why == "thin_old" and key not in promoted and not w9:
                        tot["old_usd"] += v["usd"]
                        tot["old_krw"] += v.get("krw") or 0.0
                        tot["old_n"] += 1
                elif row.get("partial"):
                    tot["partial"] = tot.get("partial", 0) + 1
                elif row.get("ab_split"):
                    tot["split"] += 1
                else:
                    tot["pending"] += 1
                dd = row.get("dday")
                if dd and dd.get("usd") is not None:
                    tot["dday_usd"] += dd["usd"]
                    tot["dday_krw"] += dd.get("krw") or 0.0
                if w9:
                    wl.append(row)
            elif cls == "candidate":
                cands.append(row)
            else:
                spam.append({k: row.get(k) for k in ("key", "chain", "ca", "name", "sym", "std", "count", "reason", "reason_ko", "acq", "holders")})
        inc = prefs.get("include_in_total") is True
        tot["incl_usd"] = (tot["usd"] - tot["old_usd"]) if inc else 0.0
        tot["incl_krw"] = (tot["krw"] - tot["old_krw"]) if inc else 0.0
        if not rate:
            tot["krw"] = tot["incl_krw"] = tot["dday_krw"] = tot["old_krw"] = None
        tracked.sort(key=lambda r: -((r.get("value") or {}).get("usd") or 0))
        cands.sort(key=lambda r: (r["reason"] == "checking", -((r.get("value") or {}).get("usd") or 0), r.get("name") or ""))
        osk = bool(self.env_fn("TJ_OPENSEA_KEY"))
        cgk = self._cg_key()
        with self.lock:
            cg_bad = self._key_bad(cgk)
        cg_rec = None
        if cgk:
            try:
                cg_rec = self.cg_store.load(cgk)
            except Exception:
                cg_rec = None
        try:
            ntc = self.notice(prefs)
        except Exception as e:
            _warn("NFT 안내 판정 실패: %s", type(e).__name__)
            ntc = None
        return _jsafe({
            "ok": True, "v": SCHEMA, "at": int(now), "enabled": self.enabled(), "prefs_error": perr,
            "include_in_total": inc, "rate": rate or None, "totals": tot,
            "tracked": tracked, "candidates": cands, "spam": {"n": len(spam), "items": spam}, "hidden": hid, "watch": wl,
            "lp_excluded": lp_n, "lp_items": lp_items,
            "watch_chains": sorted(set(CG_PLATFORM) | (set(OS_CHAIN) if osk else set())) + ["sol"],
            "scan": {"at": scan.get("at"), "next": (float(scan.get("at") or 0) + SCAN_EVERY) if scan.get("at") else None,
                     "chains": scan.get("chains") or {},
                     "unsupported": [{"chain": c9, "why": v9.get("why"), "until": v9.get("until")} for c9, v9 in sorted((scan.get("unsupported") or {}).items())]},
            "notice": ntc,
            "sources": {"coingecko": {"key": bool(cgk), "key_bad": cg_bad, "blocked_until": (hosts.get("api.coingecko.com") or {}).get("until"),
                                      "key_blocked_until": (hosts.get(CG_PRO_HOST if (cg_rec or {}).get("plan") == "pro" else CG_KEY_HOST) or {}).get("until"),
                                      "plan": (cg_rec or {}).get("plan") if cgk else None,
                                      "plan_text": cgplan.plan_text(cg_rec, now, self._cg_share(), self.budget.month_count("coingecko_key", now)) if cgk else None,
                                      "share": self._cg_share() if (cg_rec or {}).get("plan") == "pro" else None},
                        "magiceden": {"key": False, "blocked_until": (hosts.get("api-mainnet.magiceden.dev") or {}).get("until")},
                        "opensea": {"key": osk, "verified": True, "every": OS_TRACK_EVERY, "cand_every": OS_CAND_EVERY},
                        "tensor": {"key": bool(self.env_fn("TJ_TENSOR_KEY")), "impl": False}},
            "budget": self.budget.snap(),
            "reasons": REASON_KO, "acq_kinds": ACQ_KO,
            "abmig": {"pending": int(abmig.get("pending") or 0), "done": abmig.get("done")} if abmig else None,
        })

    def _row(self, key, c, g, rec, hrows, acq, labels, rate, now, td):
        chain = c.get("chain") or key.split(":", 1)[0]
        count = g["n"]
        px = self._native_usd(rec) if rec else None
        val = value_of(rec, count, px, rate)
        fp_out = None
        if rec:
            fp_out = {k: rec.get(k) for k in ("native", "sym", "src", "vol24", "vol7", "sales24", "chg24", "chg7", "listed", "url", "at", "err",
                                              "sales7", "sales30", "basis")}
            fp_out["usd"] = rec["native"] * px if px else _num(rec.get("usd"))
            fp_out["src_ko"] = SRC_KO.get(rec.get("src"), rec.get("src"))
            fp_out["stale"] = bool(rec.get("err")) or now - float(rec.get("at") or 0) > STALE_SEC
        prev = None
        for r in reversed(hrows or []):
            if r and r[0] < td and _num(r[2]):
                prev = r
                break
        dday = None
        if prev and fp_out and fp_out.get("usd") and count > 0:
            d_usd = count * (fp_out["usd"] - float(prev[2]))
            dday = {"usd": d_usd, "krw": d_usd * rate if rate else None, "pct": (fp_out["usd"] / float(prev[2]) - 1) * 100,
                    "native_pct": ((rec["native"] / float(prev[1]) - 1) * 100) if _num(prev[1]) else None, "since": prev[0]}
        ser = []
        for r in (hrows or [])[-7:]:
            if r and _num(r[2]) is not None and count > 0:
                ser.append([r[0], count * float(r[2])])
        if val and val.get("usd") is not None and count > 0:
            if ser and ser[-1][0] == td:
                ser[-1] = [td, val["usd"]]
            else:
                ser.append([td, val["usd"]])
        a = None
        if acq:
            a = {"kind": acq.get("kind"), "kind_ko": ACQ_KO.get(acq.get("kind"), acq.get("kind")), "paid": acq.get("paid"), "sym": acq.get("sym")}
        ca = str(c.get("ca") or "")
        links = {}
        sp = ser_parse(key)
        if sp and chain in EXPLORER:
            smp = c.get("sample")
            links["explorer"] = EXPLORER[chain] + sp[1] + (("?a=" + str(smp)) if (smp is not None and tid_in(smp, sp[2])) else "")
        elif chain in EXPLORER and (ADDR_RE.match(ca) or SOL_RE.match(ca)):
            links["explorer"] = EXPLORER[chain] + ca
        if rec and rec.get("url"):
            links["market"] = rec["url"]
        series = None
        if sp:
            series = {"plat": AB_NAME, "ver": ab_ver(sp[0], sp[1]), "proj": sp[2]}
        elif ab_parent_key(key) or col_ab_parent(c):
            series = {"plat": AB_NAME, "ver": ab_ver(chain, ca), "proj": None, "split": True}
        if fp_out is not None and isinstance(rec.get("last"), dict):
            la = rec["last"]
            fp_out["last"] = {"at": la.get("at"), "px": la.get("px"), "sym": la.get("sym")}
        return {"key": key, "chain": chain, "ca": ca, "name": _txt(c.get("name") or c.get("mname"), 120) or short(ca),
                "sym": _txt(c.get("sym"), 40), "std": c.get("std") or "", "count": count,
                "wallets": [{"label": labels.get(w) or "", "addr": short(w), "n": n} for w, n in sorted(g["w"].items(), key=lambda x: -x[1])],
                "acq": a, "fp": fp_out, "value": val, "dday": dday, "series7": ser, "holders": c.get("holders"), "supply": c.get("supply"),
                "img": c.get("img"), "links": links, "compressed": bool(c.get("compressed")), "first": c.get("first"),
                "series": series, "trade": last_trade(rec, now) if rec else None}

    def apply_prefs(self, body: dict):
        if not isinstance(body, dict):
            return None, (400, "JSON 객체가 필요해요")
        op = str(body.get("op") or "")
        with self.prefs_lock:
            try:
                p = load_prefs(self.prefs_path)
            except StoreError as e:
                return None, (503, common.safe_err(e))
            with self.lock:
                known = set(self.hold["cols"]) | {self.canon(k) for k in self.hold["cols"]} | \
                    {w.get("key") for w in p["watch"] if isinstance(w, dict)}
            key = str(body.get("key") or "")
            if op in ("promote", "unpromote", "hide", "unhide", "watch_remove", "notspam", "spam"):
                if not KEY_RE.match(key):
                    return None, (400, "key 형식이 맞지 않아요")
            if op == "promote":
                if key not in known:
                    return None, (404, "모르는 컬렉션이에요")
                if key not in p["promoted"]:
                    if len(p["promoted"]) >= MAX_PREF_KEYS:
                        return None, (400, "추적 목록이 너무 길어요")
                    p["promoted"].append(key)
                p["hidden"] = [k for k in p["hidden"] if k != key]
                self.urgent.add(key)
            elif op == "unpromote":
                p["promoted"] = [k for k in p["promoted"] if k != key]
            elif op == "hide":
                if key not in known:
                    return None, (404, "모르는 컬렉션이에요")
                if key not in p["hidden"]:
                    if len(p["hidden"]) >= MAX_PREF_KEYS:
                        return None, (400, "숨김 목록이 너무 길어요")
                    p["hidden"].append(key)
                p["promoted"] = [k for k in p["promoted"] if k != key]
            elif op == "unhide":
                p["hidden"] = [k for k in p["hidden"] if k != key]
            elif op == "notspam":
                if key not in known:
                    return None, (404, "모르는 컬렉션이에요")
                if key not in p["notspam"]:
                    if len(p["notspam"]) >= MAX_PREF_KEYS:
                        return None, (400, "정상 목록이 너무 길어요")
                    p["notspam"].append(key)
                p["hidden"] = [k for k in p["hidden"] if k != key]
                self.urgent.add(key)
                with self.lock:
                    (self.fp.get("neg") or {}).pop(key, None)
            elif op == "spam":
                p["notspam"] = [k for k in p["notspam"] if k != key]
            elif op == "watch_add":
                w, err = parse_watch(body)
                if err:
                    return None, (400, err)
                if w["chain"] == "os" and not self.env_fn("TJ_OPENSEA_KEY"):
                    return None, (400, "오픈시 컬렉션 링크는 오픈시 키가 있어야 해요 — 체인과 컨트랙트 주소로 넣어 주세요")
                if any(isinstance(x, dict) and x.get("key") == w["key"] for x in p["watch"]):
                    return None, (409, "이미 관심 목록에 있어요")
                if len(p["watch"]) >= MAX_WATCH:
                    return None, (400, f"관심 목록은 {MAX_WATCH}개까지예요")
                lab = CTRL_RE.sub("", str(body.get("label") or "")).strip()[:LABEL_MAX]
                w.update({"label": lab, "added": int(self.now())})
                p["watch"].append(w)
                p["hidden"] = [k for k in p["hidden"] if k != w["key"]]
                self.urgent.add(w["key"])
                with self.lock:
                    (self.fp.get("neg") or {}).pop(w["key"], None)
            elif op == "watch_remove":
                if not any(isinstance(x, dict) and x.get("key") == key for x in p["watch"]):
                    return None, (404, "관심 목록에 없어요")
                p["watch"] = [x for x in p["watch"] if not (isinstance(x, dict) and x.get("key") == key)]
            elif op == "include":
                if not isinstance(body.get("on"), bool):
                    return None, (400, "on(true/false)이 필요해요")
                p["include_in_total"] = body["on"]
            else:
                return None, (400, "op 는 promote·unpromote·hide·unhide·notspam·spam·watch_add·watch_remove·include 중 하나예요")
            uk = key if op in ("unhide", "promote", "notspam") else (w["key"] if op == "watch_add" else None)
            sp9 = ser_parse(uk) if uk else None
            if sp9 and f"{sp9[0]}:{sp9[1]}" in p["hidden"]:
                ab = p.get("abinh") if isinstance(p.get("abinh"), dict) else {}
                hb = ab.get("hidden") if isinstance(ab.get("hidden"), dict) else {}
                par9 = f"{sp9[0]}:{sp9[1]}"
                lst9 = [x for x in (hb.get(par9) or []) if isinstance(x, str)]
                if uk not in lst9:
                    hb[par9] = sorted(lst9 + [uk])
                ab["hidden"] = hb
                p["abinh"] = ab
            p["updated"] = int(self.now())
            p["v"] = SCHEMA
            atomic_write(self.prefs_path, _jsafe(p))
        if self.urgent:
            self.wake.set()
        return self.view(), None


def parse_sol_acq(tx, owner: str, mine: set):
    if not isinstance(tx, dict):
        return None
    msg = ((tx.get("transaction") or {}).get("message") or {}) if isinstance(tx.get("transaction"), dict) else {}
    keys = msg.get("accountKeys") if isinstance(msg.get("accountKeys"), list) else []
    meta = tx.get("meta") if isinstance(tx.get("meta"), dict) else None
    if any(not isinstance(k, dict) or not isinstance(k.get("pubkey"), str) or not k["pubkey"] or not isinstance(k.get("signer"), bool) for k in keys):
        return None
    pk = [(k["pubkey"], k["signer"]) for k in keys]
    signers = {a for a, s in pk if s}
    if not signers or meta is None:
        return None
    if owner in signers:
        try:
            i = [a for a, _s in pk].index(owner)
            pre, post = meta["preBalances"][i], meta["postBalances"][i]
            fee = meta.get("fee") or 0
            spent = (pre - post - (fee if i == 0 else 0)) / 1e9
        except (KeyError, IndexError, ValueError, TypeError):
            return None
        if spent > 0.01:
            return {"kind": "bought", "paid": round(spent, 6), "sym": "SOL"}
        return {"kind": "claim"}
    if signers & set(mine):
        return {"kind": "internal"}
    recv = {b.get("owner") for b in (meta.get("postTokenBalances") or []) if isinstance(b, dict) and b.get("owner")}
    if len(recv) >= MASS_N:
        return {"kind": "airdrop_mass", "n": len(recv)}
    return {"kind": "received", "n": len(recv)}


def _rr(items, keyf):
    groups, order = {}, []
    for x in items:
        k = keyf(x)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(x)
    out, i = [], 0
    while len(out) < len(items):
        for k in order:
            if i < len(groups[k]):
                out.append(groups[k][i])
        i += 1
    return out


def _kfp(k) -> str:
    return hashlib.sha256(str(k or "").encode()).hexdigest()[:8]


def _env(k):
    try:
        import settings_store
        return settings_store.env_value(k)
    except Exception:
        return ""


def _warn(fmt, *a):
    try:
        log.warning(fmt, *a)
    except Exception:
        pass
