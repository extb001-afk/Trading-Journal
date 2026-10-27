from __future__ import annotations
import json
import os
import re
import time
from collections.abc import Callable
from datetime import datetime
import paths  # noqa: F401

from timeutil import KST


UNITS = ["tj-evm", "tj-sol", "tj-bsc", "tj-core", "tj-web", "tj-alert", "tj-review", "tj-ex", "tj-exf"]


OPTIONAL_UNITS = ["tj-review"]


BUCKET = 300


DEFAULTS = {
    "enabled": True,
    "interval_sec": 60,
    "units": UNITS,
    "ignore_units": [],
    "optional_units": OPTIONAL_UNITS,
    "tunnel": {},
    "heartbeat_url": "",
    "heartbeat_sec": 300,
    "rss_warn_mb": {"tj-web": 2200, "*": 600},
    "checks_off": [],
    "telegram_min_level": "crit",
    "remind_hours": 0,
    "remind_once_sec": 3600,
    "flap_hold_sec": 900,
    "tg_min_age_sec": 180,
    "digest_hour": 9,
    "hourly_cap": 12,
    "group_min": 4,
    "persist_sec": 600,
    "resolve_sec": 300,
    "wake_gap_sec": 300,
    "pm2_bin": None,
    "log_dir": None,
    "benign_patterns": [],
    "t": {
        "chain_warn": 900, "chain_crit": 2700,
        "new_chain_crit": 21600,
        "exchange_warn": 2700, "exchange_crit": 5400,
        "upbit_warn": 600, "upbit_crit": 1800,
        "price_warn": 300, "price_crit": 600,
        "ex_price_warn": 1800, "ex_price_crit": 3600,
        "dex_price_warn": 1200, "dex_price_crit": 2400,
        "stake_warn": 1800, "stake_crit": 172800,
        "hb_warn": 600, "hb_crit": 1800,
        "proc_persist": 300,
        "restart_warn_n": 2, "restart_warn_win": 3600,
        "restart_crit_n": 3, "restart_crit_win": 900,
        "err_warn_buckets": 4, "err_warn_win": 1800,
        "err_crit_buckets": 10, "err_crit_win": 3600,
        "net_warn_run": 2, "net_crit_run": 6,
        "daily_warn_min": 10, "daily_crit_min": 60,
        "daily_est_warn_usd": 100,
        "daily_est_warn_min_usd": 1000,
        "daily_est_warn_pct": 0.5,
        "neg_hold_warn_usd": 50, "neg_hold_persist": 7200,
        "proof_div_min_usd": 500,
        "review_min": 30,
        "inbox_warn": 900, "inbox_crit": 1800,
        "inbox_big": 64 * 1024 * 1024,
        "disk_warn_gb": 10, "disk_crit_gb": 3,
        "web_persist": 180,
        "tailnet_persist": 600,
        "tg_fail_n": 3, "tg_fail_sec": 600,
        "tunnel_persist": 300,
        "rss_persist": 600,
        "rss_win": 1800,
        "debt_keep_sec": 7200,
        "intent_win": 900,
        "dm_lag_sec": 3600,
        "balcheck_stale_x": 3,
        "upbit_pending_warn": 1800, "upbit_pending_crit": 7200,
        "unreadable_warn_sec": 3600,
        "partial_tg_sec": 86400,
        "vanish_sec": 3600,
        "quota_persist": 21600, "disc_persist": 86400,
        "recon_hold_warn": 21600, "recon_hold_fresh": 7200,
    },
}


CHAIN_NAME = {"eth": "Ethereum", "base": "Base", "arbitrum": "Arbitrum", "optimism": "Optimism",
              "polygon": "Polygon", "scroll": "Scroll", "zksync": "zkSync", "gnosis": "Gnosis",
              "robinhood": "Robinhood", "arc": "Arc", "bsc": "BSC", "sol": "Solana"}


EX_NAME = {"upbit": "업비트", "binance": "바이낸스", "bybit": "바이빗", "okx": "OKX", "kucoin": "쿠코인",
           "gate": "게이트", "bithumb": "빗썸", "hyperliquid": "Hyperliquid"}


LINE_RX = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)[,.]\d+ (DEBUG|INFO|WARNING|ERROR|CRITICAL) (?:\[[^\]]*\] )?(.*)")


PM2_TS_RX = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:?\d\d)?: ")


BENIGN_DEFAULT = [
    r"429|Too Many Requests|rate.?limit|max usage",
    r"indexing[-_ ]status|색인",
    r"silent-200 실증|저하 방출",
    r"선물 스냅샷",
    r"테일넷 IP 미확보|추가 바인딩",
]


NET_RX = re.compile(r"nodename nor servname|Name or service not known|Temporary failure in name resolution|"
                    r"Network is unreachable|No route to host|getaddrinfo failed", re.I)


TRANSIENT_RX = re.compile(r"timed out|timeout|Connection reset|Remote end closed|Service Unavailable|Bad Gateway|"
                          r"Gateway Time|HTTP Error 50[0234]|HTTPError 50[0234]|Internal Server Error|"
                          r"Connection refused|Connection aborted|SSL|EOF occurred|IncompleteRead|"
                          r"urlopen error", re.I)


SIG_SUB = [(re.compile(r"0x[0-9a-fA-F]{6,}"), "0x…"), (re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{24,}\b"), "…"),
           (re.compile(r"\d+(\.\d+)?"), "N")]


QUIET_EXC = ("KeyboardInterrupt", "SystemExit", "ConnectionResetError", "BrokenPipeError", "ConnectionAbortedError")


DEBT_RX = re.compile(r"★?(\S+) (\S+) 부채 감지: (\S+) (-?[\d.]+(?:[eE][-+]?\d+)?)")


def _now() -> float:
    return time.time()


_READ_FAIL = {}


def _read(path: str, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as e:
        if os.path.lexists(path):
            _READ_FAIL[path] = type(e).__name__
        return default


_NON_EVM = ("bsc", "sol")


def _sig(msg: str) -> str:
    s = msg
    for rx, rep in SIG_SUB:
        s = rx.sub(rep, s)
    return s[:90]


def fmt_ago(sec) -> str:
    if sec is None:
        return "—"
    sec = max(0, int(sec))
    if sec < 90:
        return f"{sec}초"
    if sec < 5400:
        return f"{sec // 60}분"
    if sec < 172800:
        h, m = divmod(sec // 60, 60)
        return f"{h}시간" + (f" {m}분" if m and h < 10 else "")
    return f"{sec // 86400}일"


def fmt_ts(ts) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(float(ts), KST).strftime("%m-%d %H:%M")


_CHALLENGE_RX = re.compile(r"just a moment|cf-mitigated|cf-chl|challenge-platform|attention required", re.I)


PACE_GRACE_SEC = 7200


PACE_NOTE_FILL = "하루 한도 안에서 천천히 확인 중 — 새 거래 확인 몫을 먼저 떼어 두고 옛 기록은 남는 몫으로 뒤에서 채워요(새 거래 확인이 그 몫보다 많으면 남은 시간에 고르게 나눠 확인)"


PACE_NOTE_HEAD = "하루 한도 안에서 천천히 확인 중 — 새 거래 확인이 하루 몫보다 많아 남은 시간에 고르게 나눠 확인해요(평소보다 늦을 수 있어요)"


_TRANSIENT_RX = re.compile(r"-32007|-32008|/minute|per minute|-32016|-32029|request limit reached|per second|/second|rate limit|too many requests|\b429\b|max usage|"
                           r"초당 한도|호출 한도|응답 시간 초과|잠시 쉬는 중|circuit open|HTTP Error 5\d\d|http5xx|\b50[0-4]\b|bad gateway|"
                           r"service unavailable|gateway time-?out|timed? ?out|timeout|deadline exceeded|^conn:|^dns:|"
                           r"Connection (?:reset|refused|aborted)|Remote end closed|부분 진행\(예산|이분 탐색 예산 소진|스캔 예산 소진", re.I)


_PERMANENT_RX = re.compile(r"chainid\s*불일치|추적 중지|HTTP(?: Error)?\s*(?!429\b)4\d\d\b|unauthori[sz]ed|forbidden|invalid api key|미구성", re.I)


NATIVE_SYM = {"eth": "ETH", "base": "ETH", "arbitrum": "ETH", "optimism": "ETH", "scroll": "ETH", "zksync": "ETH",
              "robinhood": "ETH", "arc": "USDC", "polygon": "POL", "gnosis": "xDAI", "bsc": "BNB"}


INT_STALL_SEC = 3 * 3600


INT_PROGRESS = 0.02


SOL_WAIT_WHY = ("Helius 키 없음", "Solana 지갑 없음")


BAL_RB_WHY = ("옛 기록을 반영하는 재계산 대기", "재계산 대기", "재계산 중")


BAL_RB_LIVE_SEC = 6 * 3600


BF_EXT_ORPHAN_SEC = 24 * 3600


REST_LATE_MARGIN = 900


REST_LATE_MAX = 13 * 3600


TAILSCALE_BINS = ("tailscale", "/usr/local/bin/tailscale", "/opt/homebrew/bin/tailscale",
                  "/Applications/Tailscale.app/Contents/MacOS/Tailscale")


FUT_WAIT_WARN_S = 3600


FUT_WAIT_FRESH_S = 2400


FUT_FB_SHOW_S = 86400


FUT_PLACE_FRESH_S = 7200


SNAP_MISS_SHOW_S = 7200


CALC_BUG_SHOW_S = 86400
CALC_OTHER_WARN_N = 100


CALC_UNIT = {"web": "tj-web", "web_build": "tj-web", "core": "tj-core"}


STABLE_USD = {"USDT", "USDC", "FDUSD", "BUSD", "DAI", "TUSD", "USD", "USDG", "USDE", "USD1", "RLUSD", "PYUSD", "USDP", "USDS"}


RUNNER_STALE_SEC = 180


UNIT_KO = {"tj-evm": "이더리움 계열 수집", "tj-sol": "솔라나 수집", "tj-bsc": "BSC 수집", "tj-ex": "업비트 수집", "tj-exf": "해외 거래소 수집",
           "tj-core": "장부 계산", "tj-web": "화면 서버", "tj-alert": "알림", "tj-review": "AI 복기"}


def _u(i) -> str:
    u = str(i.get("unit") or "")
    return UNIT_KO.get(u) or ("원격 접속" if u.endswith("-tunnel") else u)


def decwait_item(add: Callable, chip: Callable, doc: dict | None, units: list, open_ids: tuple, now: float) -> None:
    ren = doc.get("renorm") if isinstance(doc, dict) and isinstance(doc.get("renorm"), dict) else None
    if "tj-core" in units and ren and isinstance(ren.get("n"), int) and ren["n"] > 0 and now - float(ren.get("ts") or 0) < 86400:
        add("ledger:renorm", "tj-core", f"자릿수 채움 재정규화 {ren['n']}개", "ok",
            "자릿수를 늦게 안 토큰의 표시 수량을 원장에서 다시 계산했어요(데이터 개정 아님 · 원장 불변 · 총자산이 바뀌었을 수 있음)", "",
            persist=0, resolve=600, notify=False, remind=False, kind="ledger")
    items = doc.get("items") if isinstance(doc, dict) and isinstance(doc.get("items"), dict) else {}
    if "tj-core" not in units or not (items or "ledger:decimals_wait" in open_ids):
        return
    rows = [x for x in items.values() if isinstance(x, dict)]
    wait = [x for x in rows if not x.get("est")]
    est = [x for x in rows if x.get("est")]
    oldest = min((float(x.get("since") or now) for x in wait), default=now)
    det = " · ".join(f"{x.get('symbol') or '?'}({x.get('chain')})" for x in (wait or est)[:4])
    if est:
        det += f"{' · ' if det else ''}자릿수를 알려 주지 않는 토큰 {len(est)}개 = 18자리로 가정(추정)"
    add("ledger:decimals_wait", "tj-core", f"자릿수 모르는 토큰 {len(wait)}개 — 수량이 틀릴 수 있음" if wait else ("자릿수 추정 토큰" if est else "자릿수 모르는 토큰"),
        "warn" if wait else "ok", (det or "모두 확인됨")[:300],
        "수집기가 자릿수를 알게 되면 바로 잡혀요(수량을 원장에서 다시 계산 · 재구축 불필요) · 목록: python3 tools/fill_decimals.py" if wait else "",
        persist=0, resolve=600, notify=False, remind=False, kind="ledger")
    if wait and now - oldest > 86400:
        chip("24시간 넘음")
