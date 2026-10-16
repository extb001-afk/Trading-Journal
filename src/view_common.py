from __future__ import annotations
import os
from datetime import timedelta
from datetime import timezone
from decimal import Decimal
import common
import re
import sale_match
import rabby
import chain_registry
import time
import calcguard

KST = timezone(timedelta(hours=9))

DAYCLOSE_ON = os.environ.get("TJ_DAYCLOSE", "1") != "0"

DC_LATE_S = 2 * 86400

DC_RETRY_S = 86400

DC_SMALL_USD = 1.0

STABLE_GROUPS = {"USDT", "USDC", "DAI", "BUSD", "USDG", "USDE", "CUSD", "USD1", "NUSD", "USDM"}

EX_STABLE_SYMS = frozenset(("USDT", "USDC", "FDUSD", "BUSD", "DAI", "TUSD", "USD", "USDG", "USDE", "USD1",
                            "RLUSD", "PYUSD", "USDP", "USDS"))


def _hl_cash_syms() -> frozenset:
    out = {"USDC"}
    try:
        d9 = common.read_json(os.path.join(common.STATE_DIR, "hl_cash_syms.json"), {}) or {}
        out |= {str(x).upper() for x in (d9.get("syms") or []) if isinstance(x, str)}
    except (Exception, SystemExit) as _cg9:
        calcguard.swallowed("view_common:_hl_cash_syms", _cg9)
        pass
    return frozenset(out)


def _ex_stable_sym(sym) -> bool:
    s9 = str(sym or "").upper()
    return "@" not in s9 and s9 in EX_STABLE_SYMS

EPS = Decimal("0.000000001")


def _f(x: Decimal | float | None, nd=6):
    if x is None:
        return None
    return round(float(x), nd)


def _px_tables(px):
    d9 = getattr(px, "d", None)
    if not isinstance(d9, dict):
        return {}, None
    lk9 = getattr(px, "lock", None)
    if lk9 is None:
        return dict(d9.get("fx") or {}), (dict(d9["candle"]) if d9.get("candle") is not None else None)
    with lk9:
        return dict(d9.get("fx") or {}), (dict(d9["candle"]) if d9.get("candle") is not None else None)


DAILY_PATH = os.path.join(common.STATE_DIR, "daily_cache.json")
DAILY_V = 4
DAILY_PX_PATH = os.path.join(common.STATE_DIR, "daily_px.json")
DAILY_PX_SEED = os.path.join(common.STATE_DIR, "daily_px_seed.json")
DAILY_PX_KEEP = 45


_GSYM_MEMO = {}
PREFS_PATH = os.path.join(common.STATE_DIR, "ui_prefs.json")
DAILY_LIVE_WIN = 900
DAILY_LQ_V = 1
HL_SETTLE_S = 300
HL_MAXWAIT_S = 3600
DM_PATH = os.path.join(common.STATE_DIR, "pending_dm.jsonl")
CHAIN_NAME = {"eth": "Ethereum", "base": "Base", "arbitrum": "Arbitrum", "optimism": "Optimism",
              "polygon": "Polygon", "scroll": "Scroll", "zksync": "zkSync", "gnosis": "Gnosis", "robinhood": "Robinhood",
              "arc": "Arc", "bsc": "BSC", "sol": "Solana"}
common.fill_chain_table(CHAIN_NAME)
CHAIN_NAME.update({k: s.name for k, s in chain_registry.SPECS.items() if k not in CHAIN_NAME})
OF_BASIS_KO = {"txid": "txid 일치", "amount_time": "수량·시간 일치", "address": "입금주소 일치", "bridge": "브릿지 도착", "sale": "토큰 세일 입찰",
               "hop_split": "경유 주소 분할 입금", "roundtrip": "프로그램 예치 왕복"}
TRANSIT_NET_H = {"TRX": 2, "TRC20": 2, "TRON": 2, "SOL": 2, "SPL": 2, "BSC": 2, "BEP20": 2, "BNB": 2, "ARBITRUM": 2, "ARB": 2,
                 "OPTIMISM": 2, "OP": 2, "BASE": 2, "POLYGON": 2, "MATIC": 2, "POL": 2, "ZKSYNC": 2, "SCROLL": 2, "LINEA": 2,
                 "AVAXC": 2, "AVAX": 2, "KAIA": 2, "KLAY": 2, "APT": 2, "SUI": 2, "TON": 2, "XRP": 2, "XLM": 2, "ATOM": 2,
                 "ETH": 3, "ERC20": 3, "BTC": 6, "LTC": 6, "BCH": 6, "DOGE": 6}
TRANSIT_DEFAULT_H = 6
TRANSIT_OWN_H = 48
TRANSIT_COVER_MARGIN_S = 3600
TRANSIT_COVER_MAX_H = 168
LP_POS_PATH = os.path.join(common.STATE_DIR, "lp_positions.json")
RABBY_PATH = os.path.join(common.STATE_DIR, rabby.STATE_NAME)
RABBY_DAILY_PATH = os.path.join(common.STATE_DIR, rabby.DAILY_NAME)
LP_OPEN_SEC = 300
SALE_PATH = os.path.join(common.STATE_DIR, sale_match.CACHE_NAME)
SALE_SEC = 300
LP_CLOSED_SEC = 6 * 3600
LP_NEW_POLL_SEC = 20
SUB_TAG_RE = re.compile(r"s[1-9]")
SUB_SID_RE = re.compile(r"^[a-z]+:(s[1-9]):")


DISC_OPEN_KO = "발견 시점 기초 잔고 — 원가 미상, 발견 시각 시세로 추정"
DISC_OPEN_KO_UNK = "발견 시점 기초 잔고 · 등록 대사가 놓친 옛 보유분(원가 미상 — 발견 시각 시세로 추정)"
WEB_DIAG_PATH = os.path.join(common.STATE_DIR, "web_diag.json")
EX_CANDLE_SYMS = frozenset(("OKB",))
GOPLUS_PATH = os.path.join(common.STATE_DIR, "goplus_cache.json")
GOPLUS_STATUS = {"lastOk": 0, "lastErr": 0, "err": "", "limitedUntil": 0, "pendingNew": 0, "pendingExpired": 0, "deferred": 0}
GOPLUS_T0 = time.time()
LP_CONV_MIN_USD = Decimal(1)
OF_NATIVE_SYMS = frozenset(("ETH", "SOL", "BNB", "POL", "MATIC", "AVAX", "XDAI"))
TRANSIT_ASK_DAYS = 30


BUILD_HIST_N = 60
BUILD_EX_N = 10
EXT_RB_STATUS_PATH = os.path.join(common.STATE_DIR, "ext_rebuild_status.json")
