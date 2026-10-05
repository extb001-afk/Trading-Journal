"""Health checks and status panel data."""
from __future__ import annotations

import collections
import glob
import json
import logging
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import time
from datetime import datetime, timedelta, timezone

import common

log = logging.getLogger("tj-alert")
KST = timezone(timedelta(hours=9))
EVAL_PATH = os.path.join(common.STATE_DIR, "health_eval.json")
STATUS_PATH = os.path.join(common.STATE_DIR, "health_status.json")
HB_DIR = os.path.join(common.STATE_DIR, "health")
UNITS = ["tj-evm", "tj-sol", "tj-bsc", "tj-core", "tj-web", "tj-alert", "tj-review", "tj-ex", "tj-exf"]
OPTIONAL_UNITS = []
LEVELS = {"ok": 0, "warn": 1, "crit": 2}
BUCKET = 300

DEFAULTS = {
    "enabled": True,
    "interval_sec": 60,
    "units": UNITS,
    "ignore_units": [],
    "optional_units": OPTIONAL_UNITS,
    "tunnel_ready_url": "http://127.0.0.1:20241/ready",
    "rss_warn_mb": {"tj-web": 2200, "*": 600},
    "checks_off": [],
    "telegram_min_level": "crit",
    "remind_hours": 6,
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
    },
}

CHAIN_NAME = {"eth": "Ethereum", "base": "Base", "arbitrum": "Arbitrum", "optimism": "Optimism",
              "polygon": "Polygon", "scroll": "Scroll", "zksync": "zkSync", "gnosis": "Gnosis",
              "robinhood": "Robinhood", "arc": "Arc", "bsc": "BSC", "sol": "Solana"}
common.fill_chain_table(CHAIN_NAME)
EX_NAME = {"upbit": "업비트", "binance": "바이낸스", "bybit": "바이빗", "okx": "OKX", "kucoin": "쿠코인",
           "gate": "게이트", "bithumb": "빗썸", "hyperliquid": "Hyperliquid"}


def loc_ko(loc) -> str:
    p = str(loc or "").split(":")
    if len(p) >= 3 and p[0] == "wallet":
        w = p[2]
        ws = f"{w[:6]}…{w[-4:]}" if len(w) > 12 else w
        return f"{CHAIN_NAME.get(p[1], p[1])} 지갑 {ws}" + (" 스테이킹" if len(p) >= 4 and p[3] == "stake" else "")
    if len(p) >= 2 and p[0] == "exchange":
        return EX_NAME.get(p[1], p[1]) + (f" {p[2]}" if len(p) >= 3 and p[2] else "")
    return str(loc or "")

LINE_RX = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)[,.]\d+ (DEBUG|INFO|WARNING|ERROR|CRITICAL) (?:\[[^\]]*\] )?(.*)")
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


def settings(cfg: dict) -> dict:
    out = json.loads(json.dumps(DEFAULTS))
    user = (cfg or {}).get("health") or {}
    for k, v in user.items():
        if k == "t" and isinstance(v, dict):
            out["t"].update(v)
        elif k in out:
            out[k] = v
    ut9 = user.get("t") if isinstance(user.get("t"), dict) else {}
    ep9, up9 = common.exf_poll_sec(cfg), common.upbit_poll_sec(cfg)
    for k9, v9 in (("exchange_warn", int(4.5 * ep9)), ("exchange_crit", 9 * ep9), ("upbit_warn", 4 * up9), ("upbit_crit", 12 * up9)):
        if k9 not in ut9 and v9 > float(out["t"][k9]):
            out["t"][k9] = v9
    if os.environ.get("TJ_HEALTH") == "0":
        out["enabled"] = False
    out["bf_stall_sec"] = float(((cfg or {}).get("backfill") or {}).get("stall_sec") or 3600)
    return out


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


def _unreadable_rules(rel: str):
    m = re.fullmatch(r"cursor_(?:evm|rpc)_([A-Za-z0-9_.-]+)\.json", rel)
    if m:
        return [r"sync:chain:" + re.escape(m.group(1))], {m.group(1)}
    m = re.fullmatch(r"cursor_(bsc|sol)\.json", rel)
    if m:
        return [r"sync:chain:" + m.group(1)], {m.group(1)}
    m = re.fullmatch(r"health/([A-Za-z0-9_.-]+)\.json", rel)
    if m:
        u = m.group(1)
        un = u if u.startswith("tj-") else "tj-" + u
        rules = [re.escape("hb:" + un), r"sync:hb:" + re.escape(u) + r":.+"]
        if u == "evm":
            return rules + [r"sync:chain:(?!(?:bsc|sol)$).+", r"gaps:evm:.+"], {"*evm"}
        if u in _NON_EVM:
            return rules + [r"sync:chain:" + u] + ([r"quota:helius"] if u == "sol" else []), {u}
        return rules, set()
    m = re.fullmatch(r"exf_balances_([A-Za-z0-9_.-]+)\.json", rel)
    if m:
        return [r"exbal:stale", r"debt:margin"], set()
    table = {
        "onchain_check.json": [r"balcheck:(?:mismatch|stale)"],
        "exf_state.json": [r"sync:ex:(?!upbit$).+"],
        "exf_active.json": [r"sync:ex:(?!upbit$).+"],
        "upbit_balances.json": [r"sync:ex:upbit", r"upbit:pending"],
        "upbit_sync.json": [r"sync:ex:upbit", r"upbit:pending"],
        "spot.json": [r"sync:price:.+"],
        "web_diag.json": [r"sync:price:dex", r"goplus:queue", r"ledger:neg", r"price:proof", r"price:unpriced", r"web:build", r"rabby:gap"],
        "daily_cache.json": [r"daily:close"],
        "reviews_llm.json": [r"review:daily"],
        "chain_sweep.json": [r"chainsweep:(?:untracked|stale)"],
        "chain_activity.json": [r"chainsweep:untracked"],
        "backups/backup_status.json": [r"backup:age"],
        "backfill_status.json": [r"bfstall:.+"],
        "ext_rebuild_status.json": [r"rebuild:ext"],
        "tg_cursor.json": [r"tg:dmlag"],
        "ledger.db": [r"inbox:.+"],
    }
    return list(table.get(rel, [])), set()


def collect_unreadable(st: dict, now: float) -> dict:
    base = os.path.realpath(common.STATE_DIR)
    cur = {}
    for p9, err9 in list(_READ_FAIL.items()):
        rp9 = os.path.realpath(p9)
        rel = os.path.relpath(rp9, base) if rp9.startswith(base + os.sep) else os.path.basename(p9)
        cur[rel] = err9
    mem = st.setdefault("unreadable", {}) if isinstance(st, dict) else {}
    for rel in [r9 for r9 in mem if r9 not in cur]:
        mem.pop(rel, None)
    for rel in cur:
        mem.setdefault(rel, now)
    rules, fch = set(), set()
    for rel in cur:
        r9, c9 = _unreadable_rules(rel)
        rules.update(r9)
        fch.update(c9)
    return {"files": cur, "since": {r9: float(mem.get(r9) or now) for r9 in cur}, "rules": sorted(rules), "fail_chains": sorted(fch)}


def _held_by(cid: str, rules) -> bool:
    return any(re.fullmatch(rx, cid) for rx in rules or ())


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


class LogWatch:

    KEEP_SEC = 3 * 3600
    FIRST_TAIL = 512 * 1024
    MAX_READ = 4 * 1024 * 1024

    def __init__(self, benign_extra=None, disabled_chains=None):
        pats = list(BENIGN_DEFAULT) + list(benign_extra or [])
        for c in disabled_chains or []:
            pats.append(r"\b" + re.escape(c) + r"\b")
        self.benign = re.compile("|".join(f"(?:{p})" for p in pats), re.I)
        self.files = {}
        self.units = {}

    def _u(self, unit):
        u = self.units.get(unit)
        if u is None:
            u = self.units[unit] = {"last_ts": None, "ev": collections.deque(), "review": None}
        return u

    def classify(self, level: str, msg: str) -> str:
        if DEBT_RX.search(msg):
            return "debt"
        if level in ("ERROR", "CRITICAL"):
            if self.benign.search(msg):
                return "benign"
            if NET_RX.search(msg):
                return "net"
            if TRANSIENT_RX.search(msg):
                return "transient"
            return "error"
        if level == "WARNING":
            if NET_RX.search(msg):
                return "net"
            return "warn"
        return "info"

    def feed(self, unit: str, line: str, ts_hint: float = None, fstate: dict = None):
        u = self._u(unit)
        fs = fstate if fstate is not None else {}
        line = line.rstrip("\n")
        m = LINE_RX.match(line)
        if m:
            self._flush_tb(unit, fs)
            try:
                ts = time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                ts = ts_hint or _now()
            fs["last_ts"] = ts
            level, msg = m.group(2), m.group(3)
            u["last_ts"] = max(u["last_ts"] or 0, ts)
            cls = self.classify(level, msg)
            if cls == "debt":
                m9 = DEBT_RX.search(msg)
                try:
                    u.setdefault("debt", {})[(m9.group(1), m9.group(2), m9.group(3))] = (ts, float(m9.group(4)))
                except (ValueError, AttributeError):
                    pass
            elif cls != "info":
                u["ev"].append((ts, cls, _sig(msg), msg[:300]))
            if unit == "tj-review":
                self._review(u, ts, msg)
            return
        if fs.get("incremental"):
            ts = ts_hint or _now()
        elif fs.get("hint_mtime"):
            ts = fs.get("last_ts")
        else:
            ts = fs.get("last_ts") or ts_hint or _now()
        if line.startswith("Traceback (most recent call last)"):
            self._flush_tb(unit, fs)
            fs["tb"] = {"ts": ts, "lines": []}
            return
        tb = fs.get("tb")
        if tb is not None:
            if line.startswith(" ") or not line.strip():
                tb["lines"].append(line)
                return
            fs["tb"] = None
            exc = line.strip()
            if tb["ts"] is not None and not exc.startswith(QUIET_EXC):
                u["ev"].append((tb["ts"], "crash", _sig(exc), exc[:300]))

    def _flush_tb(self, unit, fs):
        if fs.get("tb") is not None:
            fs["tb"] = None

    @staticmethod
    def _review(u, ts, msg):
        if "리뷰 생성 완료" in msg:
            u["review"] = (ts, "ok", msg)
        elif "claude CLI 없음" in msg:
            u["review"] = (ts, "off", msg)
        elif "리뷰" in msg and ("실패" in msg or "파싱" in msg):
            u["review"] = (ts, "fail", msg)

    def prune(self, now: float):
        cut = now - self.KEEP_SEC
        for u in self.units.values():
            ev = u["ev"]
            while ev and ev[0][0] < cut:
                ev.popleft()
            while len(ev) > 20000:
                ev.popleft()

    def poll(self, unit_files: dict, now: float):
        for unit, paths in unit_files.items():
            for p in paths:
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                fs = self.files.get(p)
                hint = now if fs is not None else st.st_mtime
                seen = fs is not None
                if fs is not None:
                    fs["incremental"] = True
                if fs is None or fs.get("ino") != st.st_ino or st.st_size < fs.get("off", 0):
                    start = max(0, st.st_size - self.FIRST_TAIL) if fs is None else 0
                    fs = self.files[p] = {"ino": st.st_ino, "off": start, "unit": unit, "tb": None,
                                          "last_ts": None, "skip_partial": start > 0, "incremental": seen,
                                          "hint_mtime": not seen}
                if st.st_size <= fs["off"]:
                    continue
                if st.st_size - fs["off"] > self.MAX_READ:
                    fs["off"] = st.st_size - self.MAX_READ
                    fs["skip_partial"] = True
                try:
                    with open(p, "rb") as f:
                        f.seek(fs["off"])
                        data = f.read(st.st_size - fs["off"])
                except OSError:
                    continue
                cut = data.rfind(b"\n")
                if cut < 0:
                    continue
                chunk = data[:cut + 1]
                fs["off"] += cut + 1
                text = chunk.decode("utf-8", "replace")
                lines = text.split("\n")
                if fs.pop("skip_partial", False) and lines:
                    lines = lines[1:]
                for ln in lines:
                    if ln:
                        self.feed(unit, ln, ts_hint=hint, fstate=fs)
        self.prune(now)

    def summary(self, unit: str, now: float, t: dict) -> dict:
        u = self.units.get(unit) or {"last_ts": None, "ev": (), "review": None}
        w60 = now - 3600
        err_b, net_b = set(), set()
        n_err = n_warn = n_tr = n_net = n_crash = 0
        top = collections.Counter()
        sample = {}
        last_crash = None
        for ts, cls, sig, msg in u["ev"]:
            if ts < w60 or ts > now + 5:
                continue
            b = int(ts // BUCKET)
            if cls in ("error", "crash"):
                err_b.add(b)
                n_err += 1
                top[sig] += 1
                sample[sig] = msg
                if cls == "crash":
                    n_crash += 1
                    last_crash = (ts, msg)
            elif cls == "net":
                net_b.add(b)
                n_net += 1
            elif cls == "transient":
                n_tr += 1
            elif cls == "warn":
                n_warn += 1
        return {"last_ts": u["last_ts"], "err_buckets": sorted(err_b), "net_buckets": sorted(net_b),
                "n_err": n_err, "n_warn": n_warn, "n_transient": n_tr, "n_net": n_net, "n_crash": n_crash,
                "top": [(s, c, sample[s]) for s, c in top.most_common(3)], "last_crash": last_crash,
                "review": u.get("review")}


def _pm2_bin(h: dict):
    cands = [h.get("pm2_bin"), shutil.which("pm2"), "/opt/homebrew/bin/pm2", "/usr/local/bin/pm2",
             os.path.expanduser("~/.npm-global/bin/pm2"), os.path.expanduser("~/.local/bin/pm2")]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


def pm2_list(h: dict):
    b = _pm2_bin(h)
    if not b:
        return None
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(b) + os.pathsep + env.get("PATH", "")
    try:
        out = subprocess.run([b, "jlist"], capture_output=True, text=True, timeout=25, env=env)
        i = out.stdout.find("[")
        data = json.loads(out.stdout[i:]) if i >= 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    res = {}
    for p in data:
        e = p.get("pm2_env") or {}
        name = p.get("name") or e.get("name")
        if not name:
            continue
        res[name] = {"status": e.get("status"), "restarts": int(e.get("restart_time") or 0),
                     "pid": p.get("pid"), "uptime": (e.get("pm_uptime") or 0) / 1000.0,
                     "out": e.get("pm_out_log_path"), "err": e.get("pm_err_log_path"),
                     "mem": (p.get("monit") or {}).get("memory")}
    return res


def _mem_ts(st: dict, key: str, cur):
    mem = st.setdefault("mem", {})
    rec = mem.setdefault(key, {"last": None, "first": None})
    if cur:
        rec["last"] = max(float(cur), float(rec["last"] or 0))
    return rec


def _cname(c) -> str:
    if c in CHAIN_NAME:
        return CHAIN_NAME[c]
    try:
        import chainsweep as _cs9
        ent = _cs9.SWEEP_CHAINS.get(c)
        if ent:
            return ent[0]
    except Exception:
        pass
    return str(c)[:1].upper() + str(c)[1:]


def human_err(msg, label: str = "") -> str:
    if not msg:
        return msg
    m = common.redact_secret_text(str(msg))
    if _PERMANENT_RX.search(m):
        return m
    low = m.lower()
    who = f"{label} RPC" if label else "RPC"
    if "-32008" in m or "/minute" in low or "per minute" in low:
        return f"{who} 분당 한도 — 속도 낮춰 재시도 중"
    if "-32007" in m or "request limit reached" in low or "per second" in low or "/second" in low:
        return f"{who} 초당 한도 — 속도 낮춰 재시도 중"
    if "max usage" in low or "quota" in low:
        return f"{who} 사용량 한도 소진 — 한도가 풀리면 이어서"
    if "429" in m or "too many requests" in low or "rate limit" in low:
        return f"{who} 호출 한도 — 잠시 쉬었다 재시도 중"
    if "timed out" in low or "timeout" in low or "deadline exceeded" in low:
        return f"{who} 응답 시간 초과 — 다음 주기 재시도"
    if "circuit open" in low:
        return f"{who} 연속 실패로 잠시 쉬는 중"
    return common.redact_urls(m)


_TRANSIENT_RX = re.compile(r"-32007|-32008|/minute|per minute|-32016|-32029|request limit reached|per second|/second|rate limit|too many requests|\b429\b|max usage|"
                           r"초당 한도|호출 한도|응답 시간 초과|잠시 쉬는 중|circuit open|HTTP Error 5\d\d|http5xx|\b50[0-4]\b|bad gateway|"
                           r"service unavailable|gateway time-?out|timed? ?out|timeout|deadline exceeded|^conn:|^dns:|"
                           r"Connection (?:reset|refused|aborted)|Remote end closed|부분 진행\(예산|이분 탐색 예산 소진|스캔 예산 소진", re.I)
_PERMANENT_RX = re.compile(r"chainid\s*불일치|추적 중지|HTTP(?: Error)?\s*(?!429\b)4\d\d\b|unauthori[sz]ed|forbidden|invalid api key|미구성", re.I)
NEW_CHAIN_CYCLE_STALE = 1800


def _transient_err(err) -> bool:
    if not err:
        return True
    t = str(err)
    return not _PERMANENT_RX.search(t) and bool(_TRANSIENT_RX.search(t))


def _source(st, now, key, unit, label, kind, cur_ts, err=None, extra=None):
    rec = _mem_ts(st, key, cur_ts)
    if rec["first"] is None:
        rec["first"] = now
    return {"key": key, "unit": unit, "label": label, "kind": kind, "last_success": rec["last"],
            "first_seen": rec["first"], "err": err, "extra": extra}


NATIVE_SYM = {"eth": "ETH", "base": "ETH", "arbitrum": "ETH", "optimism": "ETH", "scroll": "ETH", "zksync": "ETH",
              "robinhood": "ETH", "arc": "USDC", "polygon": "POL", "gnosis": "xDAI", "bsc": "BNB"}
common.fill_chain_table(NATIVE_SYM, 1)


def _bs_partial_text(chain: str, bs: dict, bs_ts: float, now: float) -> str:
    lag = bs.get("lag_sec")
    try:
        lag = float(lag) if lag is not None else None
    except (TypeError, ValueError):
        lag = None
    if lag is None and bs_ts:
        lag = now - float(bs_ts)
    if lag and 5400 <= lag < 172800:
        h9, m9 = divmod(int(lag) // 60, 60)
        lag_s = f"{h9}시간" + (f" {m9}분" if m9 else "")
    else:
        lag_s = fmt_ago(lag)
    head = f"블록스카웃 {lag_s} 지연(외부)" if lag else "블록스카웃 응답 대기(외부)"
    late = f"{NATIVE_SYM.get(chain, '네이티브')} 송금·내부 이동"
    try:
        nbf = int(bs.get("wallets_backfilling") or 0)
    except (TypeError, ValueError):
        nbf = 0
    if nbf > 0:
        ids = [str(x)[:6] for x in (bs.get("backfilling_ids") or []) if x][:3]
        late += f"과 새 지갑 {nbf}개" + (f"({', '.join(ids)}{'…' if nbf > len(ids) else ''})" if ids else "") + " 기초잔고"
        late += "는"
    else:
        late += "은"
    tail = (f" · 블록스카웃 마지막 성공 {fmt_ts(bs_ts)}" if bs_ts
            else f" · 블록스카웃 반영 {fmt_ts(now - lag)}까지" if lag else "")
    return f"{head} — 토큰 이동은 실시간, {late} 복구 후 자동 반영{tail}"


INT_STALL_SEC = 3 * 3600
INT_PROGRESS = 0.02


def _int_track(st: dict, chain: str, bs: dict, now: float):
    if not isinstance(st, dict) or not isinstance(bs, dict):
        return None
    mem = st.setdefault("mem", {})
    k = f"intidx:{chain}"
    if bs.get("indexing_state") != "internal":
        if bs.get("ok") and not bs.get("indexing_unknown") and bs.get("indexing_state") is not None:
            mem.pop(k, None)
        return None
    try:
        r = round(float(bs.get("internal_ratio")), 4)
    except (TypeError, ValueError):
        return None
    rec = mem.get(k)
    if not isinstance(rec, dict):
        rec = None
    else:
        try:
            if "base" not in rec:
                rec = {"base": float(rec.get("ratio")), "since": float(rec.get("since") or now),
                       "start": float(rec.get("since") or now)}
            else:
                rec = {"base": float(rec["base"]), "since": float(rec.get("since") or now),
                       "start": float(rec.get("start") or rec.get("since") or now)}
        except (TypeError, ValueError):
            rec = None
    if rec is None:
        rec = {"base": r, "since": now, "start": now}
    elif r >= rec["base"] + INT_PROGRESS - 1e-9:
        rec.update(base=r, since=now)
    elif r < rec["base"] - 0.2:
        rec.update(base=r, since=now)
    mem[k] = rec
    return {"stall": max(0.0, now - rec["since"]), "below_since": min(rec["start"], now)}


def _int_stall(st: dict, chain: str, bs: dict, now: float):
    tr = _int_track(st, chain, bs, now)
    return tr["stall"] if tr else None


def _bs_internal_text(chain: str, bs: dict, stall_sec=None):
    if not bs.get("ok"):
        return None
    intf = bs.get("int_fill") if isinstance(bs.get("int_fill"), dict) else None
    nat = NATIVE_SYM.get(chain, "네이티브")
    if bs.get("indexing_state") == "internal":
        try:
            pct = f"{float(bs.get('internal_ratio')) * 100:.0f}%"
        except (TypeError, ValueError):
            pct = "미완"
        if stall_sec is not None and stall_sec >= INT_STALL_SEC:
            txt = (f"외부 탐색기 색인 {pct}에서 {fmt_ago(stall_sec)}째 정체 — 내부 이동({nat} 전송) 일부 누락 가능"
                   f" · 거래·토큰 목록은 최신, 색인이 다시 움직여 끝나면 자동으로 채움")
        else:
            txt = f"거래·토큰 목록 최신, 내부 이동({nat} 전송 일부)은 외부 탐색기 색인 {pct} 대기 — 끝나면 자동으로 채움"
        if bs.get("indexing_unknown"):
            txt += "(색인 상태 조회 실패 — 마지막 관측 유지)"
    elif intf:
        txt = f"거래·토큰 목록 최신, 내부 이동({nat} 전송 일부)은 탐색기 색인이 끝나 지금 자동으로 채우는 중"
    else:
        return None
    try:
        nbf = int(bs.get("wallets_backfilling") or 0)
    except (TypeError, ValueError):
        nbf = 0
    if nbf > 0:
        ids = [str(x)[:6] for x in (bs.get("backfilling_ids") or []) if x][:3]
        txt += f" · 새 지갑 {nbf}개" + (f"({', '.join(ids)}{'…' if nbf > len(ids) else ''})" if ids else "") + " 과거 기록 수집 중"
    return txt


def collect_sources(cfg: dict, st: dict, now: float) -> list:
    S = common.STATE_DIR
    out = []
    chains = (cfg.get("chains") or {}) if cfg else {}
    hb = read_heartbeats()
    hb_src = {}
    for unit, doc in hb.items():
        for k, s in ((doc.get("sources") or {}).items()):
            hb_src[(unit, k)] = s
    used_hb = set()

    def hbinfo(unit, k):
        s = hb_src.get((unit, k))
        if not s:
            return None, None, None
        used_hb.add((unit, k))
        le = s.get("last_error") or {}
        err = le.get("msg") if s.get("ok") is False else None
        ex = []
        if s.get("current_source"):
            ex.append(str(s["current_source"]))
        if s.get("lag_sec") is not None:
            ex.append(f"지연 {fmt_ago(s['lag_sec'])}")
        elif s.get("lag_blocks") is not None:
            ex.append(f"{s['lag_blocks']}블록 뒤")
        return s.get("last_success_ts"), err, " · ".join(ex) or None

    for c in sorted(chains):
        if not isinstance(chains[c], dict):
            continue
        p = os.path.join(S, f"cursor_evm_{c}.json")
        pr = os.path.join(S, f"cursor_rpc_{c}.json")
        if not chains[c].get("_auto") and not os.path.exists(p) and not os.path.exists(pr) \
                and ("evm", c) not in hb_src and ("evm", f"{c}:rpclog") not in hb_src:
            continue
        cands = []
        d = _read(p, {}) or {}
        if d.get("_synced_at"):
            cands.append(float(d["_synced_at"]))
        dr = _read(pr, {}) if os.path.exists(pr) else {}
        if (dr or {}).get("rpc_synced_at"):
            cands.append(float(dr["rpc_synced_at"]))
        hts, herr, hex_ = hbinfo("evm", c)
        if hts:
            cands.append(float(hts))
        rts, _rerr, _rex = hbinfo("evm", f"{c}:rpclog")
        if rts:
            cands.append(float(rts))
        partial9 = False
        pkind9 = None
        sr9 = hb_src.get(("evm", f"{c}:rpclog")) or {}
        bs9i = hb_src.get(("evm", c)) or {}
        itr9 = _int_track(st, c, bs9i, now) if not herr else None
        int9 = None if herr else _bs_internal_text(c, bs9i, itr9["stall"] if itr9 else None)
        if rts and sr9.get("ok") and now - float(rts) < 1800:
            ex9 = []
            bs_ts9 = max([float(x) for x in (d.get("_synced_at"), hts) if x] or [0])
            if herr or (hts is None and not d.get("_synced_at")) or (bs_ts9 and now - bs_ts9 > 900):
                ex9.append(_bs_partial_text(c, hb_src.get(("evm", c)) or {}, bs_ts9, now))
                partial9, pkind9 = True, "bs_lag"
            elif int9:
                ex9.append(int9)
                partial9, pkind9 = True, "internal"
            else:
                ex9.append("RPC 로그 트랙 실시간")
            nw9 = sr9.get("nw") if isinstance(sr9.get("nw"), dict) else None
            if nw9:
                eta9 = nw9.get("eta")
                ex9.append(f"신규 지갑 백필 {float(nw9.get('pct') or 0):.0f}%" + (f"(남은 {fmt_ago(eta9)})" if eta9 else ""))
            if partial9 or nw9:
                herr, hex_ = None, " · ".join(ex9)
        elif int9:
            partial9, pkind9, hex_ = True, "internal", int9
        out.append(_source(st, now, f"chain:{c}", "tj-evm", _cname(c), "chain",
                           max(cands) if cands else None, human_err(herr, _cname(c)), hex_))
        out[-1]["err_raw"] = common.redact_urls(common.redact_secret_text(herr, generic=False)) if herr else None
        if chains[c].get("_auto") and not cands and not out[-1]["last_success"]:
            acts9 = [float(v.get("activatedAt")) for k9, v in (_activity_pairs() or {}).items()
                     if str(k9).split(":", 1)[0] == c and isinstance(v, dict) and v.get("active") and v.get("activatedAt")]
            out[-1]["new_chain"] = min(acts9) if acts9 else out[-1]["first_seen"]
            lc9 = (hb_src.get(("evm", c)) or {}).get("last_cycle_ts")
            out[-1]["last_cycle"] = float(lc9) if isinstance(lc9, (int, float)) and not isinstance(lc9, bool) else None
            mrec9 = st.setdefault("mem", {}).setdefault(f"chain:{c}", {"last": None, "first": None})
            if out[-1]["last_cycle"] is not None:
                mrec9["cyc"] = max(out[-1]["last_cycle"], float(mrec9.get("cyc") or 0))
            elif mrec9.get("cyc"):
                out[-1]["last_cycle_mem"] = float(mrec9["cyc"])
            sd9 = (hb.get("evm") or {}).get("started")
            if out[-1]["last_cycle"] is None and isinstance(sd9, (int, float)) and not isinstance(sd9, bool) \
                    and float(sd9) > float(out[-1]["new_chain"] or 0) and float(sd9) <= now:
                out[-1]["restart_at"] = float(sd9)
        wl9 = {str(w9.get("address") or "").lower() for w9 in (cfg.get("wallets") or [])
               if isinstance(w9, dict) and w9.get("type", "evm") == "evm" and w9.get("chain") == c
               and str(w9.get("address") or "").lower().startswith("0x") and len(str(w9.get("address") or "")) == 42}
        dd9 = d if isinstance(d, dict) else {}
        cfail9 = p in _READ_FAIL
        bw9 = set() if cfail9 else {w9 for w9 in wl9 if not isinstance(dd9.get(w9), int) or isinstance(dd9.get(w9), bool)}
        job9 = dd9.get("_bfjob")
        if (isinstance(job9, dict) and job9.get("kind") == "extend"
                and isinstance(job9.get("wallets"), list)):
            bw9 |= {str(x).lower() for x in job9["wallets"] if str(x).lower() in wl9}
        if chains[c].get("rpc_log_discovery") and isinstance(dr, dict):
            for k9, v9 in dr.items():
                w9 = str(k9)[4:].lower() if str(k9).startswith("_nw:") else ""
                if w9 in wl9 and isinstance(v9, dict):
                    done9, to9 = v9.get("done"), v9.get("to")
                    if type(done9) is int and type(to9) is int and done9 < to9:
                        bw9.add(w9)
        if bw9:
            out[-1]["backfill_wallets"] = sorted(bw9)
        if partial9:
            out[-1]["partial"] = True
            bs9 = hb_src.get(("evm", c)) or {}
            out[-1]["partial_wallets"] = sorted({str(x).lower() for x in list(bs9.get("backfilling_ids") or []) + list(bs9.get("wallets_failing") or [])
                                                 if x and len(str(x)) >= 6})
            out[-1]["partial_kind"] = pkind9
            intf9 = bs9.get("int_fill") if isinstance(bs9.get("int_fill"), dict) else {}
            if intf9.get("wallets"):
                out[-1]["partial_native_wallets"] = sorted({str(x).lower() for x in intf9["wallets"] if x and len(str(x)) >= 6})
        pm9 = st.setdefault("mem", {}) if isinstance(st, dict) else {}
        if partial9:
            pr9 = pm9.get(f"partial:{c}")
            try:
                ps9 = float(pr9.get("since")) if isinstance(pr9, dict) and pr9.get("since") else None
            except (TypeError, ValueError):
                ps9 = None
            if ps9 is None or ps9 > now:
                ps9 = now
            pm9[f"partial:{c}"] = {"since": ps9}
            if pkind9 == "internal" and itr9:
                ps9 = min(ps9, float(itr9["below_since"]))
            out[-1]["partial_since"] = ps9
        else:
            pm9.pop(f"partial:{c}", None)
    if os.path.exists(os.path.join(S, "cursor_bsc.json")) or ("bsc", "bsc") in hb_src:
        d = _read(os.path.join(S, "cursor_bsc.json"), {}) or {}
        hts, herr, hex_ = hbinfo("bsc", "bsc")
        cands = [float(x) for x in (d.get("_synced_at"), hts) if x]
        out.append(_source(st, now, "chain:bsc", "tj-bsc", "BSC", "chain", max(cands) if cands else None, human_err(herr, "BSC"), hex_))
    if os.path.exists(os.path.join(S, "cursor_sol.json")) or ("sol", "sol") in hb_src:
        d = _read(os.path.join(S, "cursor_sol.json"), {}) or {}
        hts, herr, hex_ = hbinfo("sol", "sol")
        cands = [float(x) for x in (d.get("_synced_at"), hts) if x]
        out.append(_source(st, now, "chain:sol", "tj-sol", "Solana", "chain", max(cands) if cands else None, human_err(herr, "Solana"), hex_))
    for (unit, k), s in hb_src.items():
        if (unit, k) in used_hb or (unit == "evm" and k.endswith(":rpclog")):
            continue
        un = unit if unit.startswith("tj-") else f"tj-{unit}"
        hts, herr, hex_ = hbinfo(unit, k)
        if unit == "sol" and k == "sol_stake":
            n9 = s.get("accounts")
            out.append(_source(st, now, f"hb:{unit}:{k}", un, "Solana 스테이킹", "stake", hts, herr,
                               (f"계정 {n9}개" if n9 is not None else None)))
            continue
        out.append(_source(st, now, f"hb:{unit}:{k}", un, _cname(k), "chain", hts, herr, hex_))
    exf = _read(os.path.join(S, "exf_state.json"), {}) or {}
    act9 = _read(os.path.join(S, "exf_active.json"), None)
    active9 = None
    if isinstance(act9, dict) and isinstance(act9.get("active"), list):
        active9 = {str(x) for x in act9["active"] if isinstance(x, str)}
    for ex, v in sorted(exf.items()):
        if not isinstance(v, dict):
            continue
        if active9 is not None and ex not in active9:
            continue
        dw = v.get("backfilled_until")
        fl = (v.get("fills") or {}).get("backfilled_until")
        vals = [float(x) for x in (dw, fl) if x]
        cur = min(vals) if len(vals) == 2 else None
        which = None
        if len(vals) == 2 and abs(float(dw) - float(fl)) > 1800:
            which = "입출금" if float(dw) < float(fl) else "체결"
        out.append(_source(st, now, f"ex:{ex}", "tj-exf", EX_NAME.get(ex, ex), "exchange", cur,
                           None, f"{which} 수집 지연" if which else None))
    ub = os.path.join(S, "upbit_balances.json")
    if os.path.exists(ub):
        d = _read(ub, {}) or {}
        syp9 = os.path.join(S, "upbit_sync.json")
        sy = _read(syp9, None)
        cur9, err9, ex9 = d.get("ts"), None, None
        if sy is None and syp9 in _READ_FAIL:
            cur9, ex9 = None, "완주 기록(upbit_sync.json) 읽기 실패 — 판단 보류"
        elif isinstance(sy, dict):
            try:
                lok9 = float(sy.get("last_ok") or 0) or None
            except (TypeError, ValueError):
                lok9 = None
            try:
                bts9 = float(d.get("ts") or 0) or None
            except (TypeError, ValueError):
                bts9 = None
            cur9 = min(bts9, lok9) if (bts9 and lok9) else None
            le9 = sy.get("last_err") if isinstance(sy.get("last_err"), dict) else {}
            try:
                if le9.get("msg") and float(le9.get("ts") or 0) > float(lok9 or 0):
                    err9 = human_err(str(le9["msg"])[:200], "업비트")
            except (TypeError, ValueError):
                pass
            bits9 = [f"잔고 스냅샷 {fmt_ago(now - bts9)} 전" if bts9 else "잔고 스냅샷 없음",
                     f"체결·입출금 마지막 완주 {fmt_ago(now - lok9)} 전" if lok9 else "체결·입출금 완주 기록 없음"]
            try:
                if int(sy.get("track_pending") or 0) > 0:
                    bits9.append(f"체결 확정 대기 {int(sy['track_pending'])}건")
            except (TypeError, ValueError):
                pass
            ex9 = " · ".join(bits9)
        out.append(_source(st, now, "ex:upbit", "tj-ex", "업비트", "upbit", cur9, err9, ex9))
        if isinstance(sy, dict):
            try:
                out[-1]["track_pending"] = int(sy.get("track_pending") or 0)
                out[-1]["pending_since"] = float(sy.get("pending_since") or 0) or None
            except (TypeError, ValueError):
                out[-1]["track_pending"], out[-1]["pending_since"] = 0, None
            out[-1]["pending_block"] = bool(err9) and le9.get("kind") == "pending"
    sp = _read(os.path.join(S, "spot.json"), None)
    if isinstance(sp, dict):
        tk9 = sp.get("tick") if isinstance(sp.get("tick"), dict) else {}
        ex9 = (f"마지막 한 바퀴 {float(tk9.get('sec') or 0):.0f}초" + (f"(가장 느린 단계: {tk9['slowest']})" if tk9.get("slowest") else "")
               if tk9.get("sec") and float(tk9["sec"]) > 60 else None)
        out.append(_source(st, now, "price:spot", "tj-web", "시세 갱신", "price", sp.get("updated"), None, ex9))
        usd_ts = [float(v) for v in (sp.get("usd_ts") or {}).values() if isinstance(v, (int, float))]
        if usd_ts:
            out.append(_source(st, now, "price:global", "tj-web", "글로벌 시세", "price", max(usd_ts)))
        want = sp.get("want") if isinstance(sp.get("want"), dict) else None
        dex = [float(v) for v in (sp.get("dex_ts") or {}).values() if isinstance(v, (int, float))]
        if want is not None and int(want.get("dex") or 0) > 0 and dex:
            wd = _read(os.path.join(S, "web_diag.json"), None)
            da = (wd or {}).get("dex_age") if isinstance(wd, dict) else None
            ts_dex, ex_dex = max(dex), None
            if isinstance(da, dict) and now - float(wd.get("ts") or 0) < 600 and da.get("p90w") is not None:
                ts_dex = float(wd["ts"]) - float(da["p90w"])
                ex_dex = f"보유 평가액 90%가 {fmt_ago(float(da['p90w']))} 안 가격 · 가장 낡은 보유 {fmt_ago(da.get('max'))}"
            out.append(_source(st, now, "price:dex", "tj-web", "DEX 가격", "dex_price", ts_dex, None, ex_dex))
        by_ex = {}
        for k, v in (sp.get("ex_ts") or {}).items():
            if isinstance(v, (int, float)) and ":" in k:
                ex = k.split(":", 1)[0]
                by_ex[ex] = max(by_ex.get(ex, 0), float(v))
        for ex in sorted(set((want or {}).get("ex") or [])):
            out.append(_source(st, now, f"price:ex:{ex}", "tj-web", f"{EX_NAME.get(ex, ex)} 시세", "ex_price",
                               by_ex.get(ex)))
    return out


def read_heartbeats() -> dict:
    out = {}
    for p in glob.glob(os.path.join(HB_DIR, "*.json")):
        d = _read(p, None)
        if isinstance(d, dict) and d.get("ts") and d.get("schema") == 1 and isinstance(d.get("sources"), dict):
            out[str(d.get("unit") or os.path.basename(p)[:-5])] = d
    return out


def expected_day(now: float, deadline_min: int):
    nk = datetime.fromtimestamp(now, KST)
    back = 1 if nk.hour * 60 + nk.minute >= deadline_min else 2
    return nk - timedelta(days=back)


def run_since(day, run: int, deadline_min: int) -> float:
    first = day - timedelta(days=max(1, run) - 1) + timedelta(days=1)
    return datetime(first.year, first.month, first.day, deadline_min // 60, deadline_min % 60, tzinfo=KST).timestamp()


def missing_run(keys, day, fmt: str, limit: int = 14) -> int:
    n = 0
    while n < limit and (day - timedelta(days=n)).strftime(fmt) not in keys:
        n += 1
    return n


def collect_daily_review(now: float, logs: LogWatch, h: dict = None) -> tuple:
    S = common.STATE_DIR
    t = (h or DEFAULTS)["t"]
    dc = _read(os.path.join(S, "daily_cache.json"), None)
    daily = None
    if isinstance(dc, dict):
        y = expected_day(now, t["daily_warn_min"])
        run = missing_run(dc, y, "%Y-%m-%d")
        daily = {"date": y.strftime("%Y-%m-%d"), "present": y.strftime("%Y-%m-%d") in dc,
                 "run": run, "since": run_since(y, run, t["daily_warn_min"])}
        ent9 = dc.get(daily["date"]) if daily["present"] else None
        if isinstance(ent9, dict):
            try:
                est9 = float(ent9.get("est") or 0)
                val9 = float(ent9.get("val") or 0)
            except (TypeError, ValueError):
                est9, val9 = 0.0, 0.0
            daily.update(src=ent9.get("src"), est=est9, val=val9, pend=ent9.get("pend"), why=ent9.get("why"),
                         xs=bool(ent9.get("xs")))
        ra = dc.get("_reset_at")
        try:
            ra = float(ra) if ra else None
        except (TypeError, ValueError):
            ra = None
        y_close = datetime(y.year, y.month, y.day, tzinfo=KST).timestamp() + 86400
        if ra and y_close <= ra and now - ra < float(t.get("daily_heal_sec") or 3 * 3600):
            daily["healing"] = ra
    rv = _read(os.path.join(S, "reviews_llm.json"), None)
    rsum = logs.units.get("tj-review", {}).get("review") if logs else None
    y = expected_day(now, t["review_min"])
    rkeys = set()
    for k9 in (rv or {}) if isinstance(rv, dict) else ():
        k9 = str(k9)
        rkeys.add(k9[5:] if len(k9) == 10 and k9[4] == "-" else k9)
    run = missing_run(rkeys, y, "%m-%d")
    review = {"date": y.strftime("%m-%d"), "present": isinstance(rv, dict) and y.strftime("%m-%d") in rkeys,
              "exists": isinstance(rv, dict), "run": run, "since": run_since(y, run, t["review_min"]),
              "outcome": rsum[1] if rsum else None, "outcome_msg": rsum[2] if rsum else None}
    if isinstance(rv, dict):
        nk9 = datetime.fromtimestamp(now, KST)
        for back9 in range(0, 3):
            d9 = nk9 - timedelta(days=back9)
            if d9.date() < y.date():
                break
            ent9 = rv.get(d9.strftime("%Y-%m-%d")) or rv.get(d9.strftime("%m-%d"))
            if isinstance(ent9, dict):
                review["latest"] = d9.strftime("%m-%d")
                review["latestTpl"] = ent9.get("model") == "template"
                break
    return daily, review


def rss_track(st: dict, pm2, now: float, win: float) -> dict:
    rh = st.setdefault("rss_hist", {})
    out = {}
    for u, p in (pm2 or {}).items():
        mem = (p or {}).get("mem")
        if not mem:
            continue
        ent = rh.get(u) if isinstance(rh.get(u), dict) else None
        if ent is None or ent.get("pid") != (p or {}).get("pid"):
            ent = rh[u] = {"pid": (p or {}).get("pid"), "s": []}
        ent["s"] = [x for x in ent["s"] if isinstance(x, list) and len(x) == 2 and now - float(x[0]) <= win][-240:]
        ent["s"].append([round(now, 1), round(float(mem) / 1e6, 1)])
        out[u] = {"min": min(x[1] for x in ent["s"]), "span": now - float(ent["s"][0][0]), "n": len(ent["s"])}
    for u in [u for u in rh if u not in (pm2 or {})]:
        rh.pop(u, None)
    return out


def collect_balcheck():
    p = os.path.join(common.STATE_DIR, "onchain_check.json")
    d = _read(p, None)
    if not isinstance(d, dict):
        return None
    mm = d.get("mismatches") or []
    conf = [m for m in mm if m.get("confirmed", True)]
    top = None
    if conf:
        m = max(conf, key=lambda x: abs(float(x.get("diffUsd") or 0)))
        top = f"{m.get('chain')} {m.get('sym')} 차이 ${abs(float(m.get('diffUsd') or 0)):,.0f}"
    items = [{"key": m.get("key"), "chain": m.get("chain"), "wallet": str(m.get("wallet") or ""), "sym": m.get("sym"), "ca": m.get("ca"),
              "diffUsd": float(m.get("diffUsd") or 0), "carried": bool(m.get("carried")),
              "carriedN": int(m.get("carriedN") or 0), "seenAt": m.get("seenAt")} for m in conf]
    fixed = [m for m in mm if m.get("ledgerFixed")]
    return {"checkedAt": d.get("checkedAt"), "confirmed": len(conf), "watch": len(mm) - len(conf) - len(fixed),
            "resolving": len(fixed),
            "errors": len(d.get("errors") or []), "top": top, "items": items,
            "unchecked": d.get("unchecked"), "capped": bool(d.get("capped")), "pairs": d.get("pairs")}


def _short_addr(a: str) -> str:
    a = str(a or "")
    return a[:6] + "…" + a[-4:] if len(a) > 14 else a


def balcheck_split(bc: dict, sources) -> tuple:
    pw, pnw, bfw = {}, {}, {}
    for s9 in sources or []:
        k9 = str(s9.get("key") or "")
        if k9.startswith("chain:") and s9.get("backfill_wallets"):
            bfw[k9[6:]] = [str(x).lower() for x in s9["backfill_wallets"]]
        if s9.get("partial") and k9.startswith("chain:"):
            pw[k9[6:]] = [str(x).lower() for x in (s9.get("partial_wallets") or [])]
            pnw[k9[6:]] = [str(x).lower() for x in (s9.get("partial_native_wallets") or [])]
    now9, late9 = [], []
    for it in bc.get("items") or []:
        ch, w = it.get("chain"), str(it.get("wallet") or "").lower()
        if ch in pw and w and any(p9 and w.startswith(p9) for p9 in pw[ch]):
            late9.append(it)
        elif ch in bfw and w and any(p9 and w.startswith(p9) for p9 in bfw[ch]):
            late9.append(it)
        elif ch in pnw and w and not it.get("ca") and any(p9 and w.startswith(p9) for p9 in pnw[ch]):
            late9.append(it)
        else:
            now9.append(it)
    return now9, late9


INBOX_NAME = {"evm": "EVM 체인 수집분", "bsc": "BSC 수집분", "sol": "Solana 수집분", "ex": "거래소 수집분"}


def _activity_pairs() -> dict:
    d = _read(os.path.join(common.STATE_DIR, "chain_activity.json"), None)
    p = d.get("pairs") if isinstance(d, dict) else None
    return p if isinstance(p, dict) else {}


def collect_chainsweep():
    d = _read(os.path.join(common.STATE_DIR, "chain_sweep.json"), None)
    if not isinstance(d, dict):
        return None
    fs = [f for f in (d.get("findings") or []) if isinstance(f, dict)]
    act9 = _activity_pairs()
    fs = [f for f in fs if not (act9.get(f"{f.get('chain')}:{str(f.get('wallet') or '').lower()}") or {}).get("active")]
    try:
        import chainsweep as _cs9
        sp9 = _read(common.BACKFILL_SPEED_PATH, None) or {}
        cf9 = _read(common.CONFIG_PATH, None) or {}
        auto9 = bool(((cf9.get("chain_sweep") or {}) if isinstance(cf9, dict) else {}).get("auto_enable") is True)
        fs = [_cs9.refresh_reason(f, (sp9.get("chains") or {}) if isinstance(sp9, dict) else {}, auto9) for f in fs]
    except Exception:
        pass
    return {"checkedAt": d.get("checkedAt"), "findings": fs,
            "auto": len(d.get("autoEnabled") or []), "errors": len(d.get("errors") or []), "chains": len(d.get("chains") or {})}


def collect_inbox(st: dict, now: float):
    mem = st.setdefault("inbox", {})
    try:
        conn = sqlite3.connect(f"file:{common.DB_PATH}?mode=ro", uri=True, timeout=2)
        try:
            rows = conn.execute("SELECT stream, seg, off FROM inbox_offsets").fetchall()
        finally:
            conn.close()
    except sqlite3.Error as e:
        _READ_FAIL[common.DB_PATH] = type(e).__name__
        if not mem:
            return None
        return {s9: {"unknown": True, "err": common.safe_err(e)[:120]} for s9 in sorted(mem)}
    out = {}
    for stream, seg, off in rows:
        d = os.path.join(common.INBOX_DIR, stream)
        try:
            segs = sorted(int(f.split(".")[0]) for f in os.listdir(d) if f.endswith(".jsonl"))
        except OSError:
            continue
        backlog = 0
        for s in segs:
            try:
                sz = os.path.getsize(os.path.join(d, f"{s:09d}.jsonl"))
            except OSError:
                continue
            if s > seg:
                backlog += sz
            elif s == seg:
                backlog += max(0, sz - int(off))
        pos = [int(seg), int(off)]
        m = mem.get(stream) or {}
        if m.get("pos") != pos or backlog == 0:
            m = {"pos": pos, "since": now}
        out[stream] = {"backlog": backlog, "stalled_since": m["since"] if backlog > 0 else None}
        mem[stream] = m
    return out


def _tcp(host, port, timeout=3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


TAILSCALE_BINS = ("tailscale", "/usr/local/bin/tailscale", "/opt/homebrew/bin/tailscale",
                  "/Applications/Tailscale.app/Contents/MacOS/Tailscale")


def _tailnet_ip():
    for b in TAILSCALE_BINS:
        try:
            out = subprocess.run([b, "ip", "-4"], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            continue
        ip = out.stdout.strip().splitlines()[0].strip() if out.stdout.strip() else ""
        return ip if ip.startswith("100.") else ""
    return None


def collect_web(cfg: dict, st: dict, now: float):
    if os.environ.get("TJ_HEALTH_NO_NET") == "1":
        return None
    web = (cfg or {}).get("web") or {}
    port = int(web.get("port", 8023))
    lo = _tcp("127.0.0.1", port)
    mode = web.get("bind", "loopback")
    res = {"lo": lo, "tail_mode": mode == "tailscale", "tail_ip": None, "ext": None}
    if mode == "tailscale":
        cache = st.setdefault("tailcache", {})
        if now - float(cache.get("at") or 0) > 300:
            cache.update(at=now, ip=_tailnet_ip())
        ip = cache.get("ip")
        res["tail_ip"] = ip
        if ip:
            res["ext"] = _tcp(ip, port)
    return res


def collect_disk():
    try:
        du = shutil.disk_usage(common.STATE_DIR)
        return {"free": du.free, "total": du.total}
    except OSError:
        return None


def collect_dm(st: dict, now: float, tg_configured: bool):
    if not tg_configured:
        st.pop("dm", None)
        return None
    cur = _read(os.path.join(common.STATE_DIR, "tg_cursor.json"), {}) or {}
    lag = 0
    for fn in ("pending_dm.jsonl", "alerts_web.jsonl"):
        p = os.path.join(common.STATE_DIR, fn)
        try:
            sz = os.path.getsize(p)
        except OSError:
            continue
        if fn in cur:
            lag += max(0, sz - int(cur.get(fn) or 0))
    m = st.setdefault("dm", {"lag": 0, "since": None, "min": None})
    if lag == 0:
        m.update(lag=0, since=None, min=None)
    elif m.get("since") is None or lag < (m.get("min") or 0):
        m.update(lag=lag, since=now, min=lag)
    else:
        m["lag"] = lag
    return {"lag": lag, "since": m.get("since")}


def collect_tunnel(h: dict, pm2):
    if os.environ.get("TJ_HEALTH_NO_NET") == "1":
        return None
    if pm2 is not None and "tj-tunnel" not in pm2:
        return None
    url = h.get("tunnel_ready_url") or ""
    if not url.startswith("http://127.0.0.1") and not url.startswith("http://localhost"):
        return None
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            d = json.loads(r.read().decode() or "{}")
        return {"ok": True, "n": int(d.get("readyConnections") or 0)}
    except Exception as e:
        n = None
        try:
            n = int(json.loads(e.read().decode()).get("readyConnections") or 0)
        except Exception:
            pass
        return {"ok": False, "n": n or 0, "err": f"{type(e).__name__}: {common.safe_err(e)[:100]}"}


STABLE_USD = {"USDT", "USDC", "FDUSD", "DAI", "USD1", "USDG", "PYUSD", "TUSD", "BUSD"}
def collect_exbal(now: float) -> list:
    out = []
    for p in sorted(glob.glob(os.path.join(common.STATE_DIR, "exf_balances_*.json"))):
        ex = os.path.basename(p)[len("exf_balances_"):-5]
        d = _read(p, None)
        if not isinstance(d, dict):
            continue
        bal = d.get("balances") if isinstance(d.get("balances"), dict) else {}
        try:
            krw = float(bal.get("KRW") or 0)
        except (TypeError, ValueError):
            krw = 0.0
        if not bal:
            continue
        out.append((ex, max(0.0, now - float(d.get("ts") or 0)), krw))
    return out


DEBT_SRC_KO = {"loan": "담보대출", "margin": "마진", "spot": "현물 음수"}


def collect_debt(logs, now: float, h: dict):
    S = common.STATE_DIR
    px = ((_read(os.path.join(S, "spot.json"), {}) or {}).get("usd") or {})
    out, from_file = {}, set()
    for p in glob.glob(os.path.join(S, "exf_balances_*.json")):
        ex = os.path.basename(p)[len("exf_balances_"):-5]
        d = _read(p, None)
        if not isinstance(d, dict):
            continue
        db = d.get("debts") if isinstance(d.get("debts"), dict) else (d.get("debt") if isinstance(d.get("debt"), dict) else None)
        if db is not None:
            from_file.add(ex)
            loan_q = {}
            for ln in (d.get("loans") if isinstance(d.get("loans"), list) else ()):
                for a, q in ((ln.get("debt") or {}).items() if isinstance(ln, dict) and isinstance(ln.get("debt"), dict) else ()):
                    try:
                        loan_q[str(a).upper()] = loan_q.get(str(a).upper(), 0.0) + abs(float(q))
                    except (TypeError, ValueError):
                        continue
            for k, v in db.items():
                items = v.items() if isinstance(v, dict) else [(k, v)]
                src = k if isinstance(v, dict) else "margin"
                for a, q in items:
                    try:
                        q = -abs(float(q))
                    except (TypeError, ValueError):
                        continue
                    lq = min(loan_q.get(str(a).upper(), 0.0), -q) if not isinstance(v, dict) else 0.0
                    if lq > 0:
                        out[(ex, "loan", str(a))] = -lq
                        q += lq
                    if q < -1e-12:
                        out[(ex, src, str(a))] = q
        for a, q in ((d.get("balances") or {}).items() if isinstance(d.get("balances"), dict) else ()):
            if isinstance(q, (int, float)) and q < 0:
                out[(ex, "spot", str(a))] = float(q)
    u = (logs.units.get("tj-exf") or {}) if logs else {}
    for (ex, src, a), (ts, v) in (u.get("debt") or {}).items():
        if ex in from_file or now - ts > float(h["t"].get("debt_keep_sec", 7200)):
            continue
        out.setdefault((ex, src, a), v)
    rows = []
    for (ex, src, a), q in out.items():
        pr = 1.0 if a.upper() in STABLE_USD else px.get(a.upper())
        rows.append((ex, src, a, q, abs(q) * float(pr) if pr else None))
    rows.sort(key=lambda r: -(r[4] or 0))
    return rows


def _intent_entries(doc) -> list:
    out = []
    if not isinstance(doc, dict):
        return out
    try:
        if doc.get("unit") and doc.get("ts"):
            out.append((str(doc["unit"]), float(doc["ts"]), 1, f"{doc['unit']}:{doc['ts']}", None))
        for e in doc.get("entries") or []:
            if isinstance(e, dict) and e.get("unit") and e.get("ts"):
                out.append((str(e["unit"]), float(e["ts"]), max(1, int(e.get("n") or 1)), f"{e['unit']}:{e['ts']}",
                            float(e["win"]) if e.get("win") else None))
    except (TypeError, ValueError):
        pass
    return out


def _kind_t(kind: str, t: dict):
    return {"chain": ("chain_warn", "chain_crit"), "exchange": ("exchange_warn", "exchange_crit"),
            "upbit": ("upbit_warn", "upbit_crit"), "price": ("price_warn", "price_crit"),
            "ex_price": ("ex_price_warn", "ex_price_crit"), "dex_price": ("dex_price_warn", "dex_price_crit"),
            "stake": ("stake_warn", "stake_crit")}.get(kind)


ACTIONS = {
    "chain": "{unit} 로그에서 RPC·익스플로러 오류 확인 (pm2 logs {unit} --lines 80)",
    "exchange": "거래소 API 키 권한·허용 IP 확인 (pm2 logs tj-exf --lines 80)",
    "upbit": "업비트 API 키(조회 권한·허용 IP) 확인 (pm2 logs tj-ex --lines 50)",
    "price": "tj-web 로그 확인 (pm2 logs tj-web --lines 80)",
    "ex_price": "해당 거래소 시세 API 상태 확인 — 1시간 넘으면 그 거래소 잔고가 평가에서 빠집니다",
    "dex_price": "게코터미널 조회 실패 여부 확인 (pm2 logs tj-web) — 30분 넘으면 CA 토큰 평가 제외",
    "stake": "{unit} 로그에서 '스테이크' 줄 확인 (pm2 logs {unit} --lines 80) — 지갑 동기화와 별개, 보상·상태 표기만 늦어짐",
}


def awake_age(now: float, base, sleeps) -> float:
    if base is None:
        return None
    age = now - base
    for a, b in sleeps or ():
        lo, hi = max(a, base), min(b, now)
        if hi > lo:
            age -= hi - lo
    return max(0.0, age)


def evaluate(obs: dict, h: dict, open_ids=()) -> list:
    t = h["t"]
    now = obs["now"]
    sleeps = obs.get("sleeps") or []
    units = [u for u in h["units"] if u not in (h.get("ignore_units") or [])]
    open_units = dict(open_ids) if isinstance(open_ids, dict) else {}
    open_ids = set(open_ids)
    checks = []

    def add(cid, unit, title, level, detail="", action="", since=None, persist=None, resolve=None,
            notify=True, remind=True, kind=None):
        detail = common.redact_secret_text(detail, generic=False) if isinstance(detail, str) else detail
        action = common.redact_secret_text(action, generic=False) if isinstance(action, str) else action
        checks.append({"id": cid, "unit": unit, "title": title, "level": level, "detail": detail, "action": action,
                       "since": since, "persist": h["persist_sec"] if persist is None else persist,
                       "resolve": h["resolve_sec"] if resolve is None else resolve,
                       "notify": notify, "remind": remind, "kind": kind, "suppressed": None})

    def chip(text):
        checks[-1]["chip"] = text

    def eff_age(cid, base_ts):
        return awake_age(now, base_ts, sleeps)

    pm2 = obs.get("pm2")
    down_units = set()
    for u in units:
        if pm2 is None:
            add(f"proc:{u}", u, "프로세스 상태", None, "pm2 확인 불가")
            continue
        p = pm2.get(u)
        stt = (p or {}).get("status") or "없음"
        if p is None and u in (h.get("optional_units") or ()):
            continue
        if p is not None and stt in ("stopped", "errored") and u in (obs.get("intent_active") or ()):
            add(f"proc:{u}", u, "프로세스 상태", "ok", f"pm2 {stt} · 배포 중 의도된 정지", persist=t["proc_persist"], resolve=60, kind="proc")
            continue
        if p is None or stt in ("stopped", "errored"):
            down_units.add(u)
            add(f"proc:{u}", u, "프로세스 중지", "crit", f"pm2 상태: {stt}",
                f"pm2 restart {u} 후 pm2 logs {u} --lines 50 으로 원인 확인",
                persist=t["proc_persist"], resolve=60, kind="proc")
        else:
            add(f"proc:{u}", u, "프로세스 상태", "ok", f"pm2 {stt}", persist=t["proc_persist"], resolve=60, kind="proc")
    for u in units:
        rs = [x for x in (obs.get("restarts") or {}).get(u, []) if now - x <= t["restart_warn_win"]]
        if pm2 is None and not rs:
            continue
        n15 = sum(1 for x in rs if now - x <= t["restart_crit_win"])
        lc = ((obs.get("logs") or {}).get(u) or {}).get("last_crash")
        det = f"최근 1시간 재시작 {len(rs)}회" + (f" · 마지막 오류: {lc[1][:120]}" if lc else "")
        recent = rs and now - max(rs) <= 1800
        lvl = "crit" if n15 >= t["restart_crit_n"] else "warn" if (len(rs) >= t["restart_warn_n"] and recent) else "ok"
        add(f"restart:{u}", u, "재시작 반복" if lvl != "ok" else "재시작", lvl, det,
            f"pm2 logs {u} --err --lines 80 으로 예외 확인", persist=0, kind="restart")
    logs = obs.get("logs") or {}
    net_units = {u for u, s in logs.items() if any(b >= int(now // BUCKET) - 1 for b in s.get("net_buckets", []))}
    allb = set()
    for s in logs.values():
        allb.update(s.get("net_buckets", []))
    run = 0
    b = int(now // BUCKET)
    if b not in allb:
        b -= 1
    while b in allb:
        run += 1
        b -= 1
    net_bad = None
    if logs:
        net_lvl = "ok"
        if len(net_units) >= 2 and run >= t["net_crit_run"]:
            net_lvl = "crit"
        elif len(net_units) >= 2 and run >= t["net_warn_run"]:
            net_lvl = "warn"
        net_bad = net_lvl != "ok"
        add("net:dns", "system", "네트워크 끊김", net_lvl,
            f"{len(net_units)}개 유닛에서 DNS·경로 실패 {run * 5}분째",
            "맥의 인터넷 연결(와이파이·VPN) 확인 — 복구되면 수집기는 자동으로 따라잡습니다",
            persist=0, resolve=h["resolve_sec"], kind="net")
        chip("네트워크" + (" 끊김" if net_lvl != "ok" else ""))
        checks[-1]["run"] = run
    for s in obs.get("sources") or []:
        th = _kind_t(s["kind"], t)
        if not th:
            continue
        cid = f"sync:{s['key']}"
        base = s["last_success"] if s["last_success"] else s["first_seen"]
        age = eff_age(cid, base)
        real = now - base if base else None
        lvl = None
        if age is not None:
            lvl = "crit" if age >= t[th[1]] else "warn" if age >= t[th[0]] else "ok"
        ttl = {"chain": f"{s['label']} 동기화 멈춤", "exchange": f"{s['label']} 이력 수집 멈춤",
               "upbit": "업비트 동기화 멈춤", "price": f"{s['label']} 멈춤", "ex_price": f"{s['label']} 멈춤",
               "dex_price": "DEX 가격 갱신 멈춤", "stake": f"{s['label']} 갱신 멈춤"}[s["kind"]]
        if s.get("new_chain") and not s["last_success"]:
            real = max(0.0, now - float(s["new_chain"]))
            lc9 = s.get("last_cycle")
            on9 = f"새로 켠 체인(활동 감지 자동 추적 · {fmt_ts(s['new_chain'])} 켬)"
            rs9 = s.get("restart_at")
            if lc9 is None and rs9 and _transient_err(s.get("err_raw") if s.get("err_raw") is not None else s.get("err")):
                w9 = max(0.0, now - float(rs9))
                lvl = "crit" if w9 >= NEW_CHAIN_CYCLE_STALE else "warn"
                pm9 = s.get("last_cycle_mem")
                det = (f"수집기(tj-evm) {fmt_ts(rs9)} 재시작 뒤 이 체인의 첫 수집 사이클을 기다리는 중"
                       + (f" · 재시작 전 마지막 사이클 {fmt_ts(pm9)}" if pm9 else "") + f" · {on9}, 아직 첫 동기화 전")
                add(cid, s["unit"], f"{s['label']} 재시작 뒤 첫 사이클 대기 " + (f"{int(w9 // 60)}분" if w9 < 5400 else fmt_ago(w9)), lvl, det, ACTIONS[s["kind"]].format(unit=s["unit"]),
                    since=rs9, persist=120, kind=s["kind"])
                checks[-1].update(age=w9, age_eff=w9, label=s["label"], new_chain=True, restart_wait=True)
                continue
            lcx = lc9 if lc9 is not None else s.get("last_cycle_mem")
            dead9 = now - float(lcx if lcx is not None else s["new_chain"]) >= NEW_CHAIN_CYCLE_STALE and real >= NEW_CHAIN_CYCLE_STALE
            permanent9 = not _transient_err(s.get("err_raw") if s.get("err_raw") is not None else s.get("err")) or dead9
            lvl = "crit" if permanent9 or real >= t.get("new_chain_crit", 21600) else "warn"
            ttl = (f"{s['label']} 첫 사이클 없음" if dead9 and lcx is None else f"{s['label']} 추적 오류" if permanent9
                   else f"{s['label']} 첫 동기화 대기" if lvl == "warn" else f"{s['label']} 첫 동기화 멈춤")
            det = f"{on9} — 아직 첫 동기화 전"
            if dead9:
                det += f" · 수집 사이클 {fmt_ago(now - float(lcx))}째 없음" if lcx is not None else " · 첫 사이클 없음"
            if s.get("err"):
                det += f" · {str(s['err'])[:120]}"
            add(cid, s["unit"], ttl, lvl, det, ACTIONS[s["kind"]].format(unit=s["unit"]),
                since=s["new_chain"], persist=120, kind=s["kind"])
            checks[-1].update(age=real, age_eff=real, label=s["label"], new_chain=True)
            continue
        partial_ok = lvl == "ok" and s.get("partial")
        if partial_ok:
            lvl = "warn"
            ttl = f"{s['label']} 부분 동기화"
        elif lvl == "ok":
            ttl = f"{s['label']} 동기화" if s["kind"] in ("chain", "upbit", "exchange") else s["label"]
        det = (("로그 트랙 마지막 성공 " if s.get("partial") and s.get("partial_kind") != "internal" else "마지막 성공 ")
               + (fmt_ago(real) + " 전" if s["last_success"] else f"기록 없음(관측 {fmt_ago(real)})"))
        if s.get("err"):
            det += f" · 최근 오류: {str(s['err'])[:120]}"
        if s.get("extra"):
            det += f" · {s['extra']}"
        pdur = None
        if partial_ok and s.get("partial_since"):
            pdur = max(0.0, now - float(s["partial_since"]))
            det += f" · 부분 동기화 {fmt_ago(pdur)}째({fmt_ts(s['partial_since'])}부터)"
        add(cid, s["unit"], ttl, lvl, det, ACTIONS[s["kind"]].format(unit=s["unit"]),
            since=(s.get("partial_since") if partial_ok and s.get("partial_since") else s["last_success"]), persist=120, kind=s["kind"])
        checks[-1].update(age=real, age_eff=age, label=s["label"])
        if pdur is not None and pdur >= float(t.get("partial_tg_sec") or 86400):
            checks[-1]["tg_force"] = True
    for s in obs.get("sources") or []:
        if s.get("key") != "ex:upbit" or "track_pending" not in s:
            continue
        n9, ps9 = int(s.get("track_pending") or 0), s.get("pending_since")
        dur9 = max(0.0, now - float(ps9)) if (n9 and ps9) else None
        lv9 = "ok" if dur9 is None else ("crit" if dur9 >= float(t.get("upbit_pending_crit") or 7200)
                                        else "warn" if dur9 >= float(t.get("upbit_pending_warn") or 1800) else "ok")
        add("upbit:pending", "tj-ex", f"업비트 체결 확정 대기 {n9}건 · {fmt_ago(dur9)}째" if lv9 != "ok" else "업비트 체결 확정",
            lv9, (f"종결 확인된 주문 {n9}건의 체결을 단건 조회로 확정하지 못함({fmt_ts(ps9)}부터) — 그 체결은 아직 원장에 없음"
                  if dur9 is not None else "대기 없음"),
            "pm2 logs tj-ex --lines 80 에서 '추적 주문 … 단건 조회 실패' 사유 확인(키 권한·레이트리밋·업비트 점검)",
            since=ps9 if dur9 is not None else None, persist=0, kind="upbit")
    for unit, doc in (obs.get("hb") or {}).items():
        un = unit if unit.startswith("tj-") else f"tj-{unit}"
        if un not in units:
            continue
        age = eff_age(f"hb:{un}", float(doc.get("ts") or 0) or None)
        if age is None:
            continue
        lvl = "crit" if age >= t["hb_crit"] else "warn" if age >= t["hb_warn"] else "ok"
        add(f"hb:{un}", un, "수집 루프 멈춤" if lvl != "ok" else "하트비트", lvl,
            f"하트비트 마지막 갱신 {fmt_ago(now - float(doc.get('ts') or 0))} 전 (프로세스는 떠 있음)",
            f"pm2 restart {un} — 반복되면 pm2 logs {un} 에서 멈춘 지점 확인", persist=120, kind="hb")
        checks[-1].update(age=now - float(doc.get("ts") or 0), label="하트비트")
    sol_doc = (obs.get("hb") or {}).get("sol") or {}
    ssrc = (sol_doc.get("sources") or {}).get("sol") or {}
    if ssrc and "tj-sol" in units:
        le = ssrc.get("last_error") or {}
        quota = ssrc.get("primary") == "open" and (le.get("kind") == "quota" or "max usage" in str(le.get("msg") or "").lower()
                                                  or int(ssrc.get("rl_429_total") or 0) > 0)
        via = ssrc.get("current_source") or "공개 RPC"
        add("quota:helius", "tj-sol", "Helius 한도 소진 · 공개 RPC 사용 중" if quota else "Helius", "warn" if quota else "ok",
            (f"주 RPC(Helius) 크레딧 소진 — 30분마다 재확인, 지금은 {via} 로 동기화 중" if quota else "주 RPC 정상"),
            "Helius 플랜·키를 바꾸거나(설정 › 연결 · 키) 그대로 두면 공개 RPC 로 계속 동기화합니다(속도만 느림)",
            persist=0, resolve=600, notify=False, remind=False, kind="quota")
        chip("Helius 한도" if quota else None)
    bf_units = {"evm": "tj-evm", "bsc": "tj-bsc", "sol": "tj-sol", "exf": "tj-exf", "ex": "tj-ex"}
    for bu, items in (obs.get("bf") or {}).items():
        if not isinstance(items, dict) or bu.startswith("_"):
            continue
        for key, it in items.items():
            if not isinstance(it, dict) or not (key.endswith(":extend") or it.get("phase") == "extend"):
                continue
            upd = float(it.get("updated") or 0)
            if now - upd > 7 * 86400:
                continue
            moved = float(it.get("moved_at") or it.get("started") or upd or now)
            stalled = it.get("phase") != "done" and now - moved > float(h.get("bf_stall_sec") or 3600)
            un = bf_units.get(bu, f"tj-{bu}")
            add(f"bfstall:{bu}:{key}", un if un in units else "system", "과거 데이터 가져오기 멈춤" if stalled else "과거 데이터 가져오기",
                "warn" if stalled else "ok",
                (f"{key} — {fmt_ago(now - moved)} 동안 진행 없음" + (f" · {str(it.get('note'))[:120]}" if it.get("note") else "")
                 if stalled else f"{key} {it.get('phase')}"),
                "해당 유닛 로그 확인(pm2 logs " + un + ") — 거래소 API 한도·권한이면 설정의 날짜를 늦추거나 그대로 두세요(원장 재계산은 막지 않음)",
                persist=0, resolve=600, notify=False, remind=False, kind="bfstall")
    for k9, s9 in (((obs.get("hb") or {}).get("evm") or {}).get("sources") or {}).items():
        gaps = (s9 or {}).get("native_gaps") or []
        if not gaps or "tj-evm" not in units:
            continue
        newest = max(float(g.get("ts") or 0) for g in gaps if isinstance(g, dict)) if any(isinstance(g, dict) for g in gaps) else 0
        nm = CHAIN_NAME.get(k9, k9)
        det = " · ".join(f"{g.get('w')} nonce {g.get('nonce_missing')} · {g.get('native_diff')}" for g in gaps[-3:] if isinstance(g, dict))
        add(f"gaps:evm:{k9}", "tj-evm", f"{nm} 네이티브 잔고 차이 {len(gaps)}건", "warn" if now - newest < 86400 else "ok",
            f"로그 없는 이동(입금 등) — 금액은 정확, 위치 미상. 대사가 원가 미상 기초잔고로 흡수 · {det}"[:300],
            "정보용 — 완전 이력이 필요하면 chains.%s.archive_rpcs 에 아카이브 RPC(유료 키)" % k9,
            persist=0, resolve=600, notify=False, remind=False, kind="gaps")
        chip(f"{nm} 차이 {len(gaps)}")
    xr = obs.get("extrb")
    if isinstance(xr, dict) and "tj-core" in units:
        nf = int(xr.get("fails") or 0)
        add("rebuild:ext", "tj-core", f"과거 데이터 재계산 실패 {nf}회" if nf >= 2 else "과거 데이터 재계산",
            "warn" if nf >= 2 else "ok",
            (f"마지막 오류: {str(xr.get('last_error') or '')[:160]} · 원장은 그대로, 백오프 뒤 재시도" if nf >= 2
             else ("재계산 중" if xr.get("running") and now - float(xr.get("started_at") or 0) < 6000 else "정상")),
            "설정 › '과거 데이터 더 가져오기' 카드의 오류 확인 — 디스크·게이트 사유면 원인 해소 후 기다리면 재시도",
            persist=0, resolve=600, remind=False, kind="rebuild")
    tn = obs.get("tunnel")
    if tn is not None and "tj-tunnel" in units:
        bad = not tn.get("ok") or int(tn.get("n") or 0) < 1
        add("tunnel:ready", "tj-tunnel", "원격 터널 연결 끊김" if bad else "원격 터널", "crit" if bad else "ok",
            (f"연결 {int(tn.get('n') or 0)}개" + (f" · {tn['err']}" if tn.get("err") else "")) if bad else f"연결 {int(tn.get('n') or 0)}개",
            "pm2 logs tj-tunnel --lines 50 — 반복되면 pm2 restart tj-tunnel (로컬 대시보드는 영향 없음)",
            persist=t.get("tunnel_persist", 300), kind="tunnel")
        chip("원격 터널" + (" 끊김" if bad else ""))
    rw = h.get("rss_warn_mb") or {}
    rss_b = obs.get("rss") or {}
    for u in units:
        mem = ((pm2 or {}).get(u) or {}).get("mem")
        lim = (rw.get(u) or rw.get("*")) if isinstance(rw, dict) else None
        if not mem or not lim:
            continue
        mb = float(mem) / 1e6
        b9 = rss_b.get(u) if isinstance(rss_b.get(u), dict) else None
        if b9 is not None:
            base9 = float(b9["min"]) if float(b9.get("span") or 0) >= float(t.get("rss_win", 1800)) * 2 / 3 else None
        else:
            base9 = mb
        hi = base9 is not None and base9 > float(lim)
        if hi or f"mem:{u}" in open_ids:
            add(f"mem:{u}", u, "메모리 사용 높음" if hi else "메모리", "warn" if hi else "ok",
                f"RSS {mb:,.0f}MB" + (f" · 최근 {fmt_ago(t.get('rss_win', 1800))} 최저 {base9:,.0f}MB" if b9 is not None and base9 is not None else "")
                + f" (기준 {float(lim):,.0f}MB)", f"pm2 monit 으로 추이 확인 — 계속 늘면 pm2 restart {u}",
                persist=t.get("rss_persist", 600), notify=False, remind=False, kind="mem")
    dbt = obs.get("debt")
    if dbt is not None and "tj-exf" in units:
        tot = sum(r[4] or 0 for r in dbt)
        det = " · ".join(f"{EX_NAME.get(r[0], r[0])} {DEBT_SRC_KO.get(r[1], r[1])} {r[2]} " + f"{r[3]:,.6g}".replace("-", "−") + (f"(${r[4]:,.0f})" if r[4] else "")
                         for r in dbt[:6]) + (f" 외 {len(dbt) - 6}건" if len(dbt) > 6 else "")
        lbl = "차입 부채" if any(r[1] == "loan" for r in (dbt or ())) else "마진 부채"
        add("debt:margin", "tj-exf", (f"{lbl} ${tot:,.0f}" if tot else lbl) if dbt else "마진 부채", "warn" if dbt else "ok",
            (det + " — 총자산에서 차감 반영") if dbt else "부채 없음",
            "거래소에서 상환하거나, 의도한 차입이면 그대로 두세요 — 총자산에서 이미 빼고 계산해요(대시보드 '차입 부채' 카드) · 담보는 내 자산으로 계산",
            persist=0, resolve=600, notify=False, remind=False, kind="debt")
        chip(f"부채 ${tot:,.0f}" if dbt and tot else ("부채" if dbt else None))
    ebs = obs.get("exbal")
    if ebs is not None and "tj-exf" in units:
        lim9 = float((t or {}).get("exbal_stale_sec", 7200))
        old9 = [(ex9, a9, k9) for ex9, a9, k9 in ebs if a9 > lim9]
        det9 = " · ".join(f"{EX_NAME.get(ex9, ex9)} 잔고 {fmt_ago(a9)} 전" + (f"(원화 ₩{k9:,.0f})" if k9 > 0 else "") for ex9, a9, k9 in old9[:6])
        add("exbal:stale", "tj-exf", "거래소 잔고 오래됨" if old9 else "거래소 잔고", "warn" if old9 else "ok",
            (det9 + " — 총자산엔 마지막 값 사용") if old9 else "잔고 스냅샷 신선",
            "pm2 logs tj-exf 에서 잔고 조회 실패 사유 확인(키 권한·허용 IP·점검) — 총자산은 마지막 잔고로 계속 표시",
            persist=0, resolve=600, notify=False, remind=False, kind="exbal")
    wd = obs.get("webdiag")
    if isinstance(wd, dict) and "tj-web" in units:
        wd_age9 = now - float(wd.get("ts") or 0)
        if 1800 <= wd_age9 < float(t.get("webdiag_hold_sec") or 21600):
            for cid9, unit9, kind9 in (("goplus:queue", "tj-web", "goplus"), ("ledger:neg", "tj-core", "ledger"),
                                       ("price:proof", "tj-web", "price"), ("price:unpriced", "tj-web", "price"),
                                       ("web:build", "tj-web", "web"), ("rabby:gap", "tj-web", "rabby")):
                if cid9 in open_ids:
                    add(cid9, unit9, "판단 보류", None, f"웹 빌드 진단이 {fmt_ago(wd_age9)} 전 것 — 다음 빌드 뒤 다시 판정(그동안 직전 판정 유지)",
                        "", persist=0, resolve=600, notify=False, remind=False, kind=kind9)
    if isinstance(wd, dict) and "tj-web" in units and now - float(wd.get("ts") or 0) < 1800:
        wts = float(wd.get("ts") or now)
        gp = wd.get("goplus") if isinstance(wd.get("goplus"), dict) else {}
        if gp:
            last_ok = float(gp.get("lastOk") or 0)
            ref_ok = max(last_ok, float(gp.get("started") or 0))
            stuck = int(gp.get("pendingNew") or 0) > 0 and wts - ref_ok > 3600
            limited = float(gp.get("limitedUntil") or 0) > wts and wts - ref_ok >= 1800
            bad = stuck or limited
            add("goplus:queue", "tj-web", "고플러스 확증 조회 정체" if bad else "고플러스 확증 조회", "warn" if bad else "ok",
                (f"새 후보 {int(gp.get('pendingNew') or 0)}건 · 만료 재조회 {int(gp.get('pendingExpired') or 0)}건 대기 · 마지막 성공 "
                 + (fmt_ago(wts - last_ok) + " 전" if last_ok else "없음")
                 + (" · 한도(429) 쉼 중" if limited else "") + (f" · 최근 실패: {str(gp.get('err'))[:80]}" if gp.get("err") else ""))
                if bad else f"대기 새 후보 {int(gp.get('pendingNew') or 0)}건",
                "pm2 logs tj-web 에서 '고플러스' 실패 사유 확인 — 새 토큰의 스캠 확증 라벨만 늦어짐(격리는 원장 신호로 계속)",
                persist=0, resolve=600, notify=False, remind=False, kind="goplus")
        ng = wd.get("neg") if isinstance(wd.get("neg"), dict) else None
        if ng is not None:
            nusd = float(ng.get("usd") or 0)
            bad = nusd < -float(t.get("neg_hold_warn_usd") or 50)
            top0 = [x for x in (ng.get("top") or []) if isinstance(x, dict)]
            top9 = [x for x in top0 if abs(float(x.get("usd") or 0)) >= 0.5]
            n_neg9 = max(len(top9), int(ng.get("n") or 0) - (len(top0) - len(top9)))
            top = " · ".join(f"{x.get('sym')} {loc_ko(x.get('loc'))} ${abs(float(x.get('usd') or 0)):,.0f}" for x in top9[:3])
            add("ledger:neg", "tj-core", f"원장 음수 보유 ${abs(nusd):,.0f}" if bad else "원장 음수 보유", "warn" if bad else "ok",
                (f"{n_neg9}곳(마진 차입 제외) · {top} — 보유량은 0 으로 보이지만 원장 결손(누락 입금·원가 이관) 신호") if bad
                else "없음(마진 차입 제외)",
                "대시보드 보유 목록의 음수 위치 확인 — 빠진 입금·지갑 등록·거래소 이력 기간을 점검",
                persist=float(t.get("neg_hold_persist") or 7200), resolve=600, notify=False, remind=False, kind="ledger")
        pdv = [x for x in (wd.get("proof_div") or []) if isinstance(x, dict)
               and float(x.get("usd") or 0) >= float(t.get("proof_div_min_usd") or 500)]
        add("price:proof", "tj-web", f"거래소 시세·DEX 괴리 {len(pdv)}건" if pdv else "거래소 시세·DEX 교차검증", "warn" if pdv else "ok",
            " · ".join(f"{x.get('sym')} {x.get('ex')} ${float(x.get('cex') or 0):,.4g} vs DEX ${float(x.get('dex') or 0):,.4g}"
                       f"({float(x.get('diff') or 0) * 100:+.0f}%, 보유 ${float(x.get('usd') or 0):,.0f})" for x in pdv[:3]) if pdv
            else "보유 $500 이상 괴리 없음",
            "입출금으로 증명한 거래소 시세가 DEX 와 20% 넘게 다름 — 그 거래소 페어가 다른 코인인지·DEX 풀이 이상한지 확인",
            persist=1800, resolve=600, notify=False, remind=False, kind="price")
        uph = [x for x in (wd.get("unpriced_held") or []) if isinstance(x, dict)
               and max(float(x.get("cost") or 0), float(x.get("ref") or 0)) >= float(t.get("unpriced_warn_usd") or 500)]
        edh = [x for x in (wd.get("ex_dead_held") or []) if isinstance(x, dict)]
        bad = bool(uph or edh)
        add("price:unpriced", "tj-web", f"시세 없는 실보유 {len(uph) + len(edh)}건" if bad else "시세 없는 실보유", "warn" if bad else "ok",
            " · ".join([f"{x.get('sym')} {x.get('where') or ''} 원가 ${float(x.get('cost') or 0):,.0f}"
                        + (f"·참고가 ${float(x.get('ref') or 0):,.0f}" if x.get("ref") else "") for x in uph[:3]]
                       + [f"{x.get('sym')} {EX_KO.get(str(x.get('ex') or '').lower(), x.get('ex'))} 거래 0 페어" for x in edh[:3]]) if bad
            else f"원가·참고가 ${float(t.get('unpriced_warn_usd') or 500):,.0f} 이상 없음",
            "평가 0 으로 총자산에 빠져 있는 보유 — 상장폐지·거래정지·마켓 없음 확인(보유 목록 '시세 없음'), 필요하면 가격을 직접 지정(설정 파일의 가격 지정 항목)"
            " · 대시보드 '시세 없음 N개'는 소액·스캠까지 센 전체이고 여기는 그중 원가·참고가가 큰 실보유만",
            persist=3600, resolve=600, notify=False, remind=False, kind="price")
    bd = wd.get("build") if isinstance(wd, dict) and now - float(wd.get("ts") or 0) < 1800 else None
    if isinstance(bd, dict) and "tj-web" in units and int(bd.get("n") or 0) >= 5:
        p95 = float(bd.get("p95") or 0) / 1000
        slow = p95 > float(t.get("build_p95_warn_s") or 10)
        add("web:build", "tj-web", f"웹 빌드 느림 p95 {p95:.1f}초" if slow else "웹 빌드", "warn" if slow else "ok",
            f"최근 {int(bd.get('n') or 0)}회 · 중앙 {float(bd.get('p50') or 0) / 1000:.1f}초 · p95 {p95:.1f}초 · 마지막 {float(bd.get('last_ms') or 0) / 1000:.1f}초"
            + (f" · 재시작 직후 첫 빌드 {float(bd['cold_ms']) / 1000:.1f}초는 표본 제외" if isinstance(bd.get("cold_ms"), (int, float)) else ""),
            "보유·기록 규모 증가 또는 원장 잠금(백업·재구축) 확인 — 웹 서버(tj-web) 로그의 '빌드 N초' 줄",
            persist=900, resolve=600, notify=False, remind=False, kind="web")
    rb = wd.get("rabby") if isinstance(wd, dict) and now - float(wd.get("ts") or 0) < 1800 else None
    if isinstance(rb, dict) and "tj-web" in units:
        long_ = [w for w in (rb.get("wallets") or []) if isinstance(w, dict) and w.get("gapSince")
                 and now - float(w["gapSince"]) >= float(t.get("rabby_gap_sec") or 86400)]
        watch = [w for w in (rb.get("wallets") or []) if isinstance(w, dict) and w.get("gapSince") and w not in long_]

        def _rbw(w):
            miss = ", ".join(f"{x.get('sym')} {x.get('chain')} ${float(x.get('usd') or 0):,.0f}" for x in (w.get("top") or [])[:3])
            return (f"{w.get('label')} 봇 ${float(w.get('bot') or 0):,.0f} · Rabby ${float(w.get('rabby') or 0):,.0f} · 차이 "
                    f"${float(w.get('rabby') or 0) - float(w.get('bot') or 0):,.0f}" + (f" (빠진 것: {miss})" if miss else ""))
        long_.sort(key=lambda w: -(float(w.get("rabby") or 0) - float(w.get("bot") or 0)))
        def _bo(w):
            b9, r9 = float(w.get("bot") or 0), float(w.get("rabby") or 0)
            return b9 - r9 > max(200.0, 0.05 * max(b9, r9, 0.0))
        bover = sorted((w for w in (rb.get("wallets") or []) if isinstance(w, dict) and not w.get("gapSince") and _bo(w)),
                       key=lambda w: -(float(w.get("bot") or 0) - float(w.get("rabby") or 0)))

        def _bow(w):
            age9 = now - float(w.get("fetchedAt") or 0) if w.get("fetchedAt") else None
            return (f"{w.get('label')} 봇 쪽이 ${float(w.get('bot') or 0) - float(w.get('rabby') or 0):,.0f} 많음"
                    + (f"(Rabby 자료 {age9 / 3600:.0f}시간 전" + (" — 대조 자료 낡음)" if age9 > 30 * 3600 else ")") if age9 is not None else ""))
        bo_txt = ("봇 쪽이 많은 지갑 " + " · ".join(_bow(w) for w in bover[:3])) if bover else ""
        add("rabby:gap", "tj-web", f"Rabby 대비 봇이 모르는 보유 {len(long_)}지갑" if long_ else (f"Rabby 대조 · 봇 쪽이 많은 {len(bover)}지갑" if bover else "Rabby 대조"),
            "warn" if long_ else "ok",
            " · ".join(x for x in (" · ".join(_rbw(w) for w in long_[:3]), bo_txt) if x) if long_ else
            " · ".join(x for x in ((f"관찰 중 {len(watch)}지갑(하루 지나면 주황)" if watch else ("" if bover else f"{len(rb.get('wallets') or [])}지갑 차이 없음")), bo_txt) if x),
            "빠진 것은 총자산에 'Rabby 기준'으로 이미 포함 — 봇이 직접 추적하려면 그 체인 지갑 등록·토큰 확인(설정 › Rabby 대조)",
            persist=0, resolve=3600, notify=False, remind=False, kind="rabby")
    bk = obs.get("backup")
    if isinstance(bk, dict) and "tj-core" in units:
        ref = float(bk.get("last_ok") or bk.get("created") or 0)
        age = now - ref if ref else None
        old = age is not None and age > float(t.get("backup_warn_h") or 36) * 3600
        skip = bk.get("skip") == "disk" and now - float(bk.get("skip_at") or 0) < 86400
        bad = old or skip
        if bk.get("last_ok"):
            det = f"마지막 원장 백업 {fmt_ago(age)} 전({fmt_ts(bk['last_ok'])}, {float(bk.get('size') or 0) / 1024 ** 3:.2f}GB)"
        else:
            det = f"아직 백업 없음(매일 04:30 KST 이후 — 기준 {fmt_ts(ref)})"
        if skip:
            det += f" · 디스크 여유 부족으로 건너뜀(여유 {float(bk.get('free') or 0) / 1024 ** 3:.1f}GB < 10GB)"
        elif bk.get("err") and bad:
            det += f" · 최근 실패: {str(bk['err'])[:100]}"
        add("backup:age", "tj-core", ("원장 백업 건너뜀(디스크 부족)" if skip else f"원장 백업 {fmt_ago(age)} 없음") if bad else "원장 백업",
            "warn" if bad else "ok", det,
            "디스크 여유 확보(옛 백업 정리) 뒤 tj-core 로그의 '원장 정기 백업' 줄 확인",
            persist=0, resolve=600, notify=False, remind=False, kind="backup")
    cur_b = int(now // BUCKET)
    for u in units:
        s = logs.get(u)
        if not s:
            continue
        eb = s.get("err_buckets", [])
        w = sum(1 for x in eb if x > cur_b - t["err_warn_win"] // BUCKET)
        c = sum(1 for x in eb if x > cur_b - t["err_crit_win"] // BUCKET)
        recent = any(x >= cur_b - 1 for x in eb)
        lvl = "crit" if (c >= t["err_crit_buckets"] and recent) else "warn" if (w >= t["err_warn_buckets"] and recent) else "ok"
        top = s.get("top") or []
        det = f"최근 60분 오류 {s.get('n_err', 0)}건({c}개 5분 구간)"
        if top:
            det += f" · 대표: {top[0][2][:140]}"
        add(f"errors:{u}", u, "오류 지속" if lvl != "ok" else "오류율", lvl, det,
            f"pm2 logs {u} --lines 100 으로 반복 오류 확인", persist=0, kind="errors")
        checks[-1].update(n30=w, n60=c)
    nk = datetime.fromtimestamp(now, KST)
    mins = nk.hour * 60 + nk.minute
    d = obs.get("daily")
    if d is not None:
        lvl = "ok"
        if not d["present"] and d.get("healing"):
            add("daily:close", "tj-web", "일별 마감 재산출 중", "ok",
                f"{d['date']} 등 지난날 마감값을 다시 계산하는 중(시작 {fmt_ts(d['healing'])}) — 가격 조회 첫 바퀴 뒤 저장",
                "", persist=0, resolve=0, remind=False, kind="daily")
            chip(f"마감 {d['date'][5:]} 재산출 중")
            d = None
        elif not d["present"]:
            late = d.get("run", 1) > 1 or not (t["daily_warn_min"] <= mins < t["daily_crit_min"])
            lvl = "crit" if late else "warn"
    est_note9 = ""
    if d is not None and lvl == "ok" and d.get("present") and d.get("src") not in (None, "live") \
            and float(d.get("est") or 0) >= float(t.get("daily_est_warn_usd") or 100):
        if d.get("pend") is not None:
            why9 = f"실시간 유예: 가격 미조회 {int(d['pend'])}그룹" + (" · 잔고 스냅샷 낡음" if d.get("xs") else "")
        elif d.get("why") == "no_snap":
            why9 = "마감 직전 실시간 기록 없음(웹 중단·재시작)"
        else:
            why9 = "실시간 스냅샷 아님"
        est9 = float(d["est"])
        pct9 = (est9 / float(d["val"]) * 100) if d.get("val") else 0.0
        pct_s9 = f"{pct9:.1f}" if abs(pct9) >= 0.1 else f"{pct9:.2f}"
        big9 = est9 >= max(float(t.get("daily_est_warn_min_usd") or 1000), float(t.get("daily_est_warn_pct") or 0.5) / 100 * abs(float(d.get("val") or 0)))
        if big9:
            add("daily:close", "tj-web", f"마감 근사 ${est9:,.0f}({pct_s9}%)", "warn",
                f"{d['date']} 마감 저장됨 — 근사분 ${est9:,.0f}({pct_s9}%, {why9})은 그날 시세 기록이 없어 처음 계산한 시각의 시세로 고정",
                "마감 전후(23:30~00:20) 배포·재시작을 피하세요 — 게코 첫 바퀴 전 스냅샷은 가격 미조회로 유예됩니다",
                persist=0, resolve=0, notify=False, remind=False, kind="daily")
            chip(f"마감 {d['date'][5:]} 근사")
            d = None
        else:
            est_note9 = f" · 근사분 ${est9:,.0f}({pct_s9}%, {why9}) — 허용 범위"
    if d is not None:
        run = d.get("run", 1)
        add("daily:close", "tj-web", f"일별 마감 누락 ({d['date'][5:]})" if lvl != "ok" else "일별 마감", lvl,
            (f"{d['date']} 마감값이 저장되지 않음" + (f" · {run}일 연속" if run > 1 else "")) if lvl != "ok"
            else f"{d['date']} 마감 저장됨" + est_note9,
            "tj-web 로그에서 마감 유예 사유(가격 조회 전·잔고 스냅샷 낡음) 확인",
            since=d.get("since") if lvl != "ok" else None, persist=0, resolve=0, remind=False, kind="daily")
        chip(f"마감 {d['date'][5:]}" + (" 누락" if lvl != "ok" else ""))
    r = obs.get("review")
    if r is not None and (r.get("exists", True) or r.get("outcome") == "fail"):
        lvl = "ok"
        if r.get("outcome") == "off":
            lvl = "off"
        elif not r["present"]:
            lvl = "crit"
        det = f"{r['date']} 리뷰 " + ("없음" if not r["present"] else "생성됨")
        if lvl == "ok" and r.get("latest") and r["latest"] != r["date"]:
            det = f"{r['latest']} 리뷰 생성됨"
        if lvl == "ok" and r.get("latestTpl"):
            det += " · 체결 없는 날 자동 요약"
        if lvl == "crit" and r.get("run", 1) > 1:
            det += f" · {r['run']}일 연속"
        if lvl == "crit" and r.get("outcome_msg"):
            det += f" · 마지막 기록: {r['outcome_msg'][:120]}"
        add("review:daily", "tj-review", "하루 리뷰 누락" if lvl == "crit" else "하루 리뷰", lvl, det,
            "pm2 logs tj-review — '/api/state 조회 실패' 면 tj-web 접속(루프백) 확인",
            since=r.get("since") if lvl == "crit" else None, persist=0, resolve=0, remind=False, kind="review")
        chip("리뷰 꺼짐(claude CLI 없음)" if lvl == "off" else f"리뷰 {r.get('latest') or r['date'] if lvl == 'ok' else r['date']}" + (" 누락" if lvl == "crit" else ""))
    bc = obs.get("balcheck")
    if bc is not None:
        lvl = "crit" if bc["confirmed"] else "ok"
        ttl = f"원장·온체인 잔고 불일치 {bc['confirmed']}건" if lvl != "ok" else "잔고 대조"
        det = (bc.get("top") or "") + (f" · 관찰 중 {bc['watch']}건" if bc.get("watch") else "")
        held_all9, heldc9 = False, []
        if bc.get("items") is not None:
            fc9 = set(((obs.get("unreadable") or {}).get("fail_chains")) or ())
            prev9 = (obs.get("prev_inc") or {}).get("balcheck:mismatch") or {}
            pkeys9 = set(prev9.get("keys") or ())
            evi9, held9, hred9 = [], [], []
            for it in bc["items"]:
                if fc9 and (it.get("chain") in fc9 or ("*evm" in fc9 and it.get("chain") not in _NON_EVM)):
                    (hred9 if str(it.get("key")) in pkeys9 else held9).append(it)
                else:
                    evi9.append(it)
            heldc9 = sorted({str(it.get("chain")) for it in held9 + hred9})
            now9, late9 = balcheck_split(dict(bc, items=evi9), obs.get("sources"))
            now9 = now9 + hred9
            held_all9 = bool(held9) and not now9 and not late9
            row = lambda it: (f"{CHAIN_NAME.get(it.get('chain'), it.get('chain'))} {_short_addr(it.get('wallet'))} {it.get('sym')} "
                              f"차이 ${abs(float(it.get('diffUsd') or 0)):,.0f}"
                              + ((f" (지난 판 값 · {int(it.get('carriedN') or 1)}판째 이월" + (f" · 실측 {fmt_ago(now - float(it['seenAt']))} 전" if it.get("seenAt") else "")
                                  + ")") if it.get("carried") else ""))
            if now9:
                lvl = "crit"
                ttl = f"원장·온체인 잔고 불일치 {len(now9)}건" + (f" · 외부 지연 대기 {len(late9)}건" if late9 else "")
            elif late9:
                lvl = "warn"
                ttl = f"잔고 불일치 {len(late9)}건 · 외부 지연 대기(복구 후 자동 반영)"
            parts9 = []
            if now9:
                parts9.append("확인 필요: " + " · ".join(row(x) for x in sorted(now9, key=lambda x: -abs(x["diffUsd"]))[:8])
                              + (f" 외 {len(now9) - 8}건" if len(now9) > 8 else ""))
            if late9:
                parts9.append("부분 동기화 지갑(블록스카웃 복구 후 자동 반영): "
                              + " · ".join(row(x) for x in sorted(late9, key=lambda x: -abs(x["diffUsd"]))[:8])
                              + (f" 외 {len(late9) - 8}건" if len(late9) > 8 else ""))
            if bc.get("watch"):
                parts9.append(f"관찰 중 {bc['watch']}건")
            if bc.get("resolving"):
                parts9.append(f"해소 대기 {bc['resolving']}건(원장이 지난 실측 온체인 값과 일치 — 다음 대조에서 확인)")
            if heldc9:
                parts9.append(f"{', '.join(heldc9)} 상태 파일(커서·하트비트) 읽기 실패 — 그 체인 {len(held9) + len(hred9)}건은 판단 보류"
                              + (f"(직전 빨강 {len(hred9)}건 유지)" if hred9 else "") + "(직전 상태 유지)")
            det = " / ".join(parts9) if parts9 else det
            if not now9 and not late9 and not held9:
                lvl = "ok" if not hred9 else lvl
        if bc.get("unchecked"):
            det += (" · " if det else "") + f"이번 판 미대조 {int(bc['unchecked'])}쌍(호출 상한 — 다음 판에 이어서)"
        elif bc.get("capped"):
            det += (" · " if det else "") + "이번 판 호출 상한 도달"
        crit9 = lvl == "crit"
        add("balcheck:mismatch", "tj-web", ttl, lvl, det,
            "대시보드 미매칭 › 잔고 대사에서 확인 (원장은 자동 보정하지 않음)" if lvl == "crit"
            else "외부 탐색기(블록스카웃)가 복구되면 다음 대조에서 저절로 맞춰져요 — 복구 뒤에도 남으면 미매칭 › 잔고 대사에서 확인",
            persist=0, notify=crit9, remind=crit9, kind="balcheck")
        if crit9 and bc.get("items") is not None:
            checks[-1]["keys"] = sorted({str(x.get("key")) for x in now9 if x.get("key")})
        if held_all9:
            checks[-1]["level"] = None
        chip(("잔고 지연 대기 " if lvl == "warn" else "잔고 불일치 ") + str(bc["confirmed"] if lvl != "crit" or bc.get("items") is None else len(now9))
             if bc["confirmed"] else "잔고 대조 일치")
        iv = 3600
        age = eff_age("balcheck:stale", float(bc.get("checkedAt") or 0) or None)
        if age is not None:
            lvl = "warn" if age >= t["balcheck_stale_x"] * iv else "ok"
            add("balcheck:stale", "tj-web", "잔고 대조 멈춤" if lvl != "ok" else "잔고 대조 주기", lvl,
                f"마지막 대조 {fmt_ago(now - float(bc['checkedAt']))} 전", "pm2 logs tj-web 에서 '온체인 잔고 대조' 확인",
                persist=0, kind="balcheck")
    cs = obs.get("chainsweep")
    if cs is not None:
        import chainsweep as _cs9
        fs = cs.get("findings") or []
        lvl = "warn" if fs else "ok"
        usd9 = sum(float(f.get("usd") or 0) for f in fs)
        add("chainsweep:untracked", "tj-web",
            (f"미추적 체인에 잔고/활동 {len(fs)}건" + (f" (≈${usd9:,.0f})" if usd9 else "")) if fs else "미추적 체인 점검",
            lvl, " / ".join(_cs9.finding_text(f) for f in fs[:6]) + (f" 외 {len(fs) - 6}건" if len(fs) > 6 else "")
            if fs else f"체인 {cs.get('chains')}개 점검 — 발견 없음" + (f" · 활동 게이트 자동 추적 {cs['auto']}쌍" if cs.get("auto") else "")
            + (f" · 조회 실패 {cs['errors']}개 체인" if cs.get("errors") else ""),
            "그 체인을 추적에 추가하거나(속도 측정이 끝나면 활동 지갑은 자동으로 켜져요), 필요 없는 체인·지갑이면 무시 목록(설정 파일)에 넣어 경고에서 뺄 수 있어요",
            persist=0, remind=False, kind="chainsweep")
        chip(f"미추적 체인 {len(fs)}건" if fs else "미추적 체인 없음")
        age = eff_age("chainsweep:stale", float(cs.get("checkedAt") or 0) or None)
        if age is not None:
            lvl = "warn" if age >= 3 * 86400 else "ok"
            add("chainsweep:stale", "tj-web", "미추적 체인 점검 멈춤" if lvl != "ok" else "미추적 체인 점검 주기", lvl,
                f"마지막 점검 {fmt_ago(now - float(cs['checkedAt']))} 전", "pm2 logs tj-web 에서 '미추적 체인 점검' 확인",
                persist=0, kind="chainsweep")
    for stream, v in (obs.get("inbox") or {}).items():
        cid = f"inbox:{stream}"
        if v.get("unknown"):
            add(cid, "tj-core", f"원장 처리 · {INBOX_NAME.get(stream, stream)}", None,
                "원장 처리 위치 읽기 실패 — 판단 보류(직전 상태 유지)" + (f": {v['err']}" if v.get("err") else ""),
                "", persist=120, kind="inbox")
            continue
        age = eff_age(cid, v.get("stalled_since"))
        lvl = "ok"
        if age is not None and v["backlog"] > 0:
            lvl = "crit" if age >= t["inbox_crit"] else "warn" if age >= t["inbox_warn"] else "ok"
        if lvl == "ok" and v["backlog"] >= t["inbox_big"]:
            lvl = "warn"
        sn9 = INBOX_NAME.get(stream, stream)
        add(cid, "tj-core", f"원장 처리 멈춤 · {sn9}" if lvl != "ok" else f"원장 처리 · {sn9}", lvl,
            f"처리 대기 {v['backlog'] / 1024:,.0f}KB" + (f" · 위치 {fmt_ago(now - v['stalled_since'])} 째 그대로" if v.get("stalled_since") else ""),
            "pm2 logs tj-core --lines 100 — 멈췄으면 pm2 restart tj-core", persist=120, kind="inbox")
    dk = obs.get("disk")
    if dk:
        gb = dk["free"] / 1e9
        pct = dk["free"] * 100.0 / max(1, dk["total"])
        lvl = "crit" if gb < t["disk_crit_gb"] else "warn" if gb < t["disk_warn_gb"] else "ok"
        add("disk:state", "system", "디스크 여유 부족" if lvl != "ok" else "디스크", lvl,
            f"여유 {gb:,.1f}GB ({pct:.1f}%)", "오래된 백업(ledger.db.bak_*)·로그 정리 — 원장 쓰기가 실패하기 전에",
            kind="disk")
        chip(f"디스크 여유 {gb:,.0f}GB")
    wb = obs.get("web")
    if wb:
        add("web:loopback", "tj-web", "대시보드 응답 없음" if not wb["lo"] else "대시보드 응답",
            "crit" if not wb["lo"] else "ok", "127.0.0.1 포트 연결 " + ("실패" if not wb["lo"] else "정상"),
            "pm2 restart tj-web — 반복되면 pm2 logs tj-web", persist=t["web_persist"], kind="web")
        chip("대시보드 응답" + (" 없음" if not wb["lo"] else ""))
        if wb.get("tail_mode"):
            if wb.get("tail_ip"):
                ok = bool(wb.get("ext"))
                add("net:tailnet", "tj-web", "테일넷 접속 불가" if not ok else "테일넷 접속", "warn" if not ok else "ok",
                    f"{wb['tail_ip']} 에 대시보드가 안 떠 있음" if not ok else f"{wb['tail_ip']} 정상",
                    "tj-web 은 60초마다 재바인딩 — 10분 넘게 지속되면 pm2 restart tj-web",
                    persist=t["tailnet_persist"], kind="web")
                chip("테일넷" + (" 접속 불가" if not ok else ""))
            else:
                add("net:tailnet", "tj-web", "테일넷 꺼짐", "off",
                    "테일스케일 IP 없음 — 외부(휴대폰) 접속 불가, 루프백은 정상" if wb.get("tail_ip") == "" else "테일스케일 없음",
                    kind="web")
                chip("테일넷 꺼짐")
    tg = obs.get("tg") or {}
    if tg.get("configured"):
        fs = tg.get("fail_since")
        bad = tg.get("consec_fail", 0) >= t["tg_fail_n"] and fs and now - fs >= t["tg_fail_sec"]
        add("tg:send", "tj-alert", "텔레그램 발송 실패" if bad else "텔레그램 발송", "crit" if bad else "ok",
            f"연속 실패 {tg.get('consec_fail', 0)}회" + (f" · {tg.get('last_error')}" if tg.get("last_error") else ""),
            "봇 토큰·채팅 ID 확인 (python3 src/alert_bot.py --test)", persist=0, notify=False, kind="tg")
        chip("텔레그램 발송" + (" 실패" if bad else ""))
        dm = obs.get("dm")
        if dm:
            age = eff_age("tg:dmlag", dm.get("since"))
            lvl = "warn" if (dm["lag"] > 0 and age is not None and age >= t["dm_lag_sec"]) else "ok"
            add("tg:dmlag", "tj-alert", "알림 발송 밀림" if lvl != "ok" else "알림 대기열", lvl,
                f"미발송 {dm['lag'] / 1024:,.1f}KB", "시간당 상한·발송 실패 여부 확인 (pm2 logs tj-alert)",
                persist=0, kind="tg")

    unr = obs.get("unreadable")
    if isinstance(unr, dict):
        rl9 = unr.get("rules") or []
        fl9 = unr.get("files") or {}
        if rl9:
            made9 = {c["id"] for c in checks}
            for cid in sorted(open_ids - made9):
                if _held_by(cid, rl9):
                    add(cid, open_units.get(cid) or "system", "판단 보류", None,
                        "상태 파일을 읽지 못해 판단 보류 — 직전 판정 유지(" + ", ".join(sorted(fl9))[:160] + ")", "", persist=0, kind="hold")
            for c in checks:
                if c["level"] is not None and c.get("kind") != "hold" and _held_by(c["id"], rl9):
                    c["level"] = None
                    c["detail"] = "상태 파일 읽기 실패(" + ", ".join(sorted(fl9))[:120] + ") — 판단 보류(직전 상태 유지) · " + str(c.get("detail") or "")
        sn9 = unr.get("since") or {}
        lim9 = float(t.get("unreadable_warn_sec") or 3600)
        old9 = sorted((r9, now - float(sn9.get(r9) or now)) for r9 in fl9 if now - float(sn9.get(r9) or now) >= lim9)
        add("health:input", "tj-alert", f"상태 파일 읽기 실패 {len(old9)}개" if old9 else "상태 파일 읽기",
            "warn" if old9 else "ok",
            (" · ".join(f"{r9}({fl9.get(r9)}, {fmt_ago(a9)}째)" for r9, a9 in old9[:6]) + (f" 외 {len(old9) - 6}개" if len(old9) > 6 else "")
             + " — 그 파일로 하는 점검은 판단 보류(직전 상태 유지)") if old9
            else ("정상" if not fl9 else f"읽기 실패 {len(fl9)}개 관찰 중(1시간 넘으면 주황)"),
            "해당 파일 손상·권한 확인(쓰는 유닛 로그) — 손상이면 그 유닛 재시작으로 다시 써지는지 확인",
            persist=0, kind="input")
    dep = {"tj-web": ("price", "ex_price", "dex_price", "daily", "balcheck", "rabby"), }
    sync_bad_units = {c["unit"] for c in checks if c["id"].startswith(("sync:", "hb:")) and c["level"] in ("warn", "crit")}
    upend9 = any(c["id"] == "upbit:pending" and c["level"] in ("warn", "crit") for c in checks)
    ublock9 = any(s9.get("key") == "ex:upbit" and s9.get("pending_block") for s9 in obs.get("sources") or [])
    for c in checks:
        if c["level"] not in ("warn", "crit"):
            continue
        k = c.get("kind")
        if c["unit"] in down_units and not c["id"].startswith(("proc:", "restart:")):
            c["suppressed"] = f"{c['unit']} 중지"
        elif "tj-web" in down_units and k in dep["tj-web"]:
            c["suppressed"] = "tj-web 중지"
        elif net_bad and k in ("chain", "exchange", "upbit", "price", "ex_price", "dex_price", "stake", "errors", "tg", "tunnel"):
            c["suppressed"] = "네트워크 끊김"
        elif k == "errors" and c["unit"] in sync_bad_units:
            c["suppressed"] = "동기화 체크가 담당"
        elif c["id"] == "sync:ex:upbit" and upend9 and ublock9:
            c["suppressed"] = "체결 확정 대기 점검이 담당"
    off = h.get("checks_off") or []
    return [c for c in checks if not any(c["id"] == o or c["id"].startswith(o) for o in off)]


def step(st: dict, checks: list, now: float, h: dict) -> list:
    cs = st.setdefault("checks", {})
    inc = st.setdefault("incidents", {})
    events = []
    seen = set()
    for c in checks:
        if isinstance(c.get("detail"), str):
            c = dict(c, detail=common.redact_secret_text(c["detail"], generic=False))
        cid = c["id"]
        seen.add(cid)
        r = cs.setdefault(cid, {"nb": 0, "nc": 0, "no": 0, "bad_since": None, "crit_since": None, "ok_since": None})
        lvl = c["level"]
        if c.get("suppressed") and cid not in inc:
            lvl = None
        if lvl in ("ok", "off"):
            r.update(nb=0, nc=0, bad_since=None, crit_since=None, no=r["no"] + 1)
            r["ok_since"] = r["ok_since"] or now
        elif lvl in ("warn", "crit"):
            r["no"], r["ok_since"] = 0, None
            r["nb"] += 1
            r["bad_since"] = r["bad_since"] or now
            if lvl == "crit":
                r["nc"] += 1
                r["crit_since"] = r["crit_since"] or now
            else:
                r["nc"], r["crit_since"] = 0, None
        r["lvl"] = lvl
        r["last"] = now
        i = inc.get(cid)
        want = None
        if lvl == "crit" and r["nc"] >= 2 and now - r["crit_since"] >= c["persist"]:
            want = "crit"
        elif lvl in ("warn", "crit") and r["nb"] >= 2 and now - r["bad_since"] >= c["persist"]:
            want = "warn"
        if i is not None:
            i.pop("unseen_since", None)
        if i is None and want:
            i = inc[cid] = {"id": f"{cid}@{int(now)}", "check": cid, "unit": c["unit"], "title": c["title"],
                            "detail": c["detail"], "action": c["action"], "level": want, "peak": want,
                            "opened": now, "since": c.get("since") or r["bad_since"], "notify": c["notify"],
                            "remind": c["remind"], "msg_id": None, "announced": None, "last_notified": None}
            for k9 in ("keys", "tg_force"):
                if c.get(k9):
                    i[k9] = c[k9]
            events.append(("open", i))
        elif i is not None:
            if lvl in ("warn", "crit"):
                i.update(title=c["title"], detail=c["detail"], action=c["action"], level=lvl)
                i.update(notify=c["notify"], remind=c["remind"])
                for k9 in ("keys", "tg_force"):
                    if c.get(k9):
                        i[k9] = c[k9]
                    else:
                        i.pop(k9, None)
                if want == "crit" and i["peak"] != "crit":
                    i["peak"] = "crit"
                    events.append(("escalate", i))
            if lvl in ("ok", "off") and r["no"] >= 2 and now - r["ok_since"] >= c["resolve"]:
                _bal_dm_forget(st, i)
                i["resolved"] = now
                i["resolved_detail"] = common.redact_secret_text(c["detail"], generic=False) if isinstance(c["detail"], str) else c["detail"]
                events.append(("resolve", i))
                del inc[cid]
                hist = st.setdefault("history", [])
                hist.append(i)
                cut = now - 7 * 86400
                st["history"] = [x for x in hist if x.get("resolved", now) >= cut][-60:]
    grace = float((h.get("t") or {}).get("vanish_sec", 3600)) if isinstance(h, dict) else 3600.0
    for cid in [k for k in inc if k not in seen]:
        i0 = inc[cid]
        try:
            gone = float(i0.get("unseen_since") or now)
        except (TypeError, ValueError):
            gone = now
        i0["unseen_since"] = gone
        if now - gone < grace:
            continue
        i = inc.pop(cid)
        i.pop("unseen_since", None)
        _bal_dm_forget(st, i)
        i["resolved"] = now
        i["resolved_detail"] = "감시 대상에서 빠짐"
        i["quiet"] = True
        st.setdefault("history", []).append(i)
    for cid in [k for k in cs if k not in seen and now - float(cs[k].get("last") or 0) > 86400]:
        del cs[cid]
    return events


def _min_level(h) -> int:
    return LEVELS.get(h.get("telegram_min_level") or "crit", 2)


def msg_open(i, now) -> str:
    icon = "🔴" if i["peak"] == "crit" else "🟠"
    return (f"{icon} {i['unit']} · {i['title']}\n{i['detail']}\n"
            f"시작: {fmt_ts(i['since'])} ({fmt_ago(now - i['since'])} 전)\n조치: {i['action']}")


def msg_remind(i, now) -> str:
    return f"⏰ 계속 발생 중 ({fmt_ago(now - i['since'])}째) · {i['unit']} {i['title']}\n{i['detail']}"


def msg_resolve(i, now) -> str:
    return f"✅ 복구됨 · {i['unit']} {i['title']} (지속 {fmt_ago(i['resolved'] - i['since'])})"


def msg_flap(i, now) -> str:
    return (f"🟡 {i['unit']} · {i['title']} — {fmt_ts(i['since'])}~{fmt_ts(i['resolved'])} "
            f"({fmt_ago(i['resolved'] - i['since'])}) 발생 후 복구됨\n{i['detail']}")


def _quiet_until(now: float):
    try:
        import alert_prefs as _ap9
        return _ap9.quiet_until(_ap9.load(), now)
    except Exception:
        return None


BAL_DM_WIN = 86400
BAL_DM_KEEP = 2 * 86400


def _bal_dm_recent(st: dict, now: float) -> set:
    m = st.get("bal_dm") if isinstance(st, dict) and isinstance(st.get("bal_dm"), dict) else {}
    out = set()
    for k, v in m.items():
        try:
            if now - float(v) < BAL_DM_WIN:
                out.add(str(k))
        except (TypeError, ValueError):
            continue
    return out


def note_bal_dm(st: dict, keys, now: float = None) -> None:
    if not isinstance(st, dict):
        return
    now = now or _now()
    m = st.get("bal_dm") if isinstance(st.get("bal_dm"), dict) else {}
    for k in keys or ():
        if isinstance(k, str) and k:
            m[k] = now
    keep = {}
    for k, v in m.items():
        try:
            if now - float(v) < BAL_DM_KEEP:
                keep[k] = float(v)
        except (TypeError, ValueError):
            continue
    st["bal_dm"] = keep


def _bal_dm_forget(st: dict, i: dict) -> None:
    if not isinstance(i, dict) or i.get("check") != "balcheck:mismatch" or not isinstance(st.get("bal_dm"), dict):
        return
    for k in set(i.get("keys") or ()) | set(i.get("keys_told") or ()):
        st["bal_dm"].pop(k, None)


def bal_covered(st: dict, keys) -> bool:
    ks = {str(k) for k in (keys or ()) if k}
    if not ks or not isinstance(st, dict):
        return False
    i = (st.get("incidents") or {}).get("balcheck:mismatch")
    if not isinstance(i, dict) or not (i.get("announced") or i.get("queued")):
        return False
    return ks <= set(i.get("keys_told") or ())


def plan(st: dict, events: list, now: float, h: dict, tg_configured: bool):
    r = _plan_raw(st, events, now, h, tg_configured)
    for o in st.get("outbox") or []:
        if isinstance(o, dict) and isinstance(o.get("text"), str):
            o["text"] = common.redact_secret_text(o["text"], generic=False)
    return r


def _plan_raw(st: dict, events: list, now: float, h: dict, tg_configured: bool):
    ob = st.setdefault("outbox", [])
    nk = datetime.fromtimestamp(now, KST)
    if not tg_configured:
        if nk.hour >= int(h["digest_hour"]):
            st["digest_date"] = nk.strftime("%Y-%m-%d")
        return
    minl = _min_level(h)
    inc = st.get("incidents", {})

    def eligible(i):
        return i.get("notify", True) and (LEVELS.get(i.get("peak"), 0) >= minl or bool(i.get("tg_force")))

    def soft(i):
        return bool(i.get("tg_force")) and LEVELS.get(i.get("peak"), 0) < LEVELS["crit"]

    nb_cache = []

    def not_before():
        if not nb_cache:
            nb_cache.append(_quiet_until(now))
        return nb_cache[0]

    def put(item, soft_only):
        if soft_only:
            nb9 = not_before()
            if nb9:
                item["not_before"] = nb9
        ob.append(item)

    recent_dm = _bal_dm_recent(st, now)

    opens, resolved = [], []
    for typ, i in events:
        if typ == "escalate" and i.get("soft_told"):
            for o in [o for o in ob if o["kind"] in ("open", "group") and i["id"] in o["incs"]]:
                o["incs"].remove(i["id"])
                if o["kind"] == "open" or not o["incs"]:
                    ob.remove(o)
            i.pop("soft_told", None)
            i.pop("queued", None)
            i["announced"] = None
        if typ in ("open", "escalate") and eligible(i) and not i.get("announced") and not i.get("queued"):
            opens.append(i)
        elif typ == "resolve":
            pend = [o for o in ob if o["kind"] in ("open", "group") and i["id"] in o["incs"]]
            if i.get("announced"):
                resolved.append(i)
            elif pend:
                for o in pend:
                    o["incs"].remove(i["id"])
                    if o["kind"] == "open" or not o["incs"]:
                        ob.remove(o)
                put({"kind": "flap", "text": msg_flap(i, now), "reply": None, "incs": [i["id"]], "created": now}, soft(i))
    if len(resolved) == 1:
        i = resolved[0]
        put({"kind": "resolve", "text": msg_resolve(i, now), "reply": i.get("msg_id"),
             "incs": [i["id"]], "created": now}, soft(i))
    elif resolved:
        lines = [f"✅ 복구됨 {len(resolved)}건"] + [f"- {i['unit']} · {i['title']} (지속 {fmt_ago(i['resolved'] - i['since'])})"
                                                 for i in resolved[:12]]
        put({"kind": "resolve", "text": "\n".join(lines), "reply": resolved[0].get("msg_id"),
             "incs": [i["id"] for i in resolved], "created": now}, all(soft(i) for i in resolved))
    for i in inc.values():
        if eligible(i) and not i.get("announced") and not i.get("queued") and i not in opens:
            opens.append(i)
    for i in list(opens):
        ks9 = set(i.get("keys") or ())
        if i.get("check") == "balcheck:mismatch" and ks9 and ks9 <= recent_dm:
            opens.remove(i)
            i.update(announced=now, last_notified=now, msg_id=None, keys_told=sorted(ks9), dedup="BALANCE_MISMATCH")
    for i in opens:
        if i.get("keys"):
            i["keys_told"] = sorted(set(i.get("keys_told") or ()) | set(i["keys"]))
    if len(opens) >= h["group_min"]:
        lines = [f"🔴 문제 {len(opens)}건 동시 발생"]
        for i in opens[:12]:
            lines.append(f"- {i['unit']} · {i['title']} ({fmt_ago(now - i['since'])})")
        lines.append("조치: 대시보드 설정 › 상태 에서 항목별 안내 확인")
        put({"kind": "group", "text": "\n".join(lines), "reply": None, "incs": [i["id"] for i in opens],
             "created": now}, all(soft(i) for i in opens))
        for i in opens:
            i["queued"] = True
            if soft(i):
                i["soft_told"] = True
    else:
        for i in opens:
            put({"kind": "open", "text": msg_open(i, now), "reply": None, "incs": [i["id"]], "created": now}, soft(i))
            i["queued"] = True
            if soft(i):
                i["soft_told"] = True
    for i in inc.values():
        if i.get("check") != "balcheck:mismatch" or not eligible(i) or not (i.get("announced") or i.get("queued")):
            continue
        told9 = set(i.get("keys_told") or ())
        cur9 = set(i.get("keys") or ())
        new9 = cur9 - told9 - recent_dm
        upd9 = told9 | (cur9 & recent_dm)
        if new9 and not any(i["id"] in o["incs"] and o["kind"] in ("open", "group", "remind") for o in ob):
            ob.append({"kind": "remind", "text": f"🔴 {i['unit']} · {i['title']} — 새로 확정된 불일치 {len(new9)}건\n{i['detail']}",
                       "reply": i.get("msg_id"), "incs": [i["id"]], "created": now})
            upd9 |= new9
        if upd9 != told9:
            i["keys_told"] = sorted(upd9)
    rh = float(h["remind_hours"]) * 3600
    cand = [i for i in inc.values() if i.get("announced") and i.get("remind", True) and eligible(i)
            and i.get("level") == "crit" and not any(o["kind"] == "remind" and i["id"] in o["incs"] for o in ob)]
    age = lambda i: now - float(i.get("last_notified") or i["announced"])
    if any(age(i) >= rh for i in cand):
        due = sorted([i for i in cand if age(i) >= rh / 2], key=lambda i: i["opened"])
        for i in due:
            if i.get("keys"):
                i["keys_told"] = sorted(set(i.get("keys_told") or ()) | set(i["keys"]))
        if len(due) == 1:
            ob.append({"kind": "remind", "text": msg_remind(due[0], now), "reply": due[0].get("msg_id"),
                       "incs": [due[0]["id"]], "created": now})
        else:
            lines = [f"⏰ 계속 발생 중 {len(due)}건"]
            for i in due[:12]:
                lines.append(f"- {i['unit']} · {i['title']} ({fmt_ago(now - i['since'])}째)")
            ob.append({"kind": "remind", "text": "\n".join(lines), "reply": due[0].get("msg_id"),
                       "incs": [i["id"] for i in due], "created": now})
    today = nk.strftime("%Y-%m-%d")
    if nk.hour >= int(h["digest_hour"]) and st.get("digest_date") != today:
        st["digest_date"] = today
        opn = sorted((i for i in inc.values() if not str(i.get("id") or "").startswith(("quota:", "bfstall:", "gaps:"))),
                     key=lambda x: (-LEVELS.get(x["level"], 0), x["opened"]))
        if opn:
            crit = [i for i in opn if i["level"] == "crit"]
            warn = [i for i in opn if i["level"] != "crit"]
            head = f"📋 {nk.strftime('%H:%M')} 상태 · 열린 문제 {len(opn)}건"
            body = "; ".join(f"{i['unit']} {i['title']}({fmt_ago(now - i['since'])})" for i in (crit or warn)[:6])
            tail = f" · 주의 {len(warn)}건은 대시보드" if crit and warn else ""
            ob.append({"kind": "digest", "text": f"{head}: {body}{tail}", "reply": None, "incs": [], "created": now})


def deliver(st: dict, send_fn, now: float, h: dict, gate=None) -> int:
    ob = st.setdefault("outbox", [])
    sent_t = [x for x in st.get("sent_times", []) if now - x < 3600]
    n = 0
    by_id = {i["id"]: i for i in list(st.get("incidents", {}).values()) + list(st.get("history", []))}
    live_ids = {i["id"] for i in st.get("incidents", {}).values()}
    for o in list(ob):
        if now - o["created"] > 86400:
            ob.remove(o)
            if o.get("kind") in ("open", "group"):
                for iid in o.get("incs") or []:
                    i = by_id.get(iid)
                    if i is not None and iid in live_ids and not i.get("announced"):
                        i.pop("queued", None)
                        i.pop("soft_told", None)
            log.warning("헬스 알림 %s 이 24시간 넘게 발송되지 못해 버림(사건 %d건 — 열린 사건은 다시 대기열에)", o.get("kind"), len(o.get("incs") or []))
            continue
        if o.get("not_before"):
            try:
                if now < float(o["not_before"]):
                    continue
            except (TypeError, ValueError):
                pass
        if gate is not None:
            try:
                go = bool(gate(o["kind"], o["text"]))
            except Exception as e:
                log.warning("알림 설정 관문 실패(보냄): %s", e)
                go = True
            if not go:
                ob.remove(o)
                for iid in o["incs"]:
                    i = by_id.get(iid)
                    if not i:
                        continue
                    if o["kind"] in ("open", "group"):
                        i["announced"] = now
                        i["last_notified"] = now
                        i["msg_id"] = None
                    elif o["kind"] == "remind":
                        i["last_notified"] = now
                continue
        if len(sent_t) >= int(h["hourly_cap"]):
            break
        ok, mid, err = send_fn(o["text"], o.get("reply"))
        if not ok:
            break
        sent_t.append(now)
        n += 1
        ob.remove(o)
        for iid in o["incs"]:
            i = by_id.get(iid)
            if not i:
                continue
            if o["kind"] in ("open", "group"):
                i["announced"] = now
                i["last_notified"] = now
                i["msg_id"] = mid
            elif o["kind"] == "remind":
                i["last_notified"] = now
        if o["kind"] in ("open", "group"):
            for o2 in ob:
                if o2["kind"] in ("remind", "resolve") and set(o2["incs"]) & set(o["incs"]):
                    o2["reply"] = mid
    st["sent_times"] = sent_t
    return n


EX_KO = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX", "kucoin": "쿠코인", "gate": "게이트", "bithumb": "빗썸", "upbit": "업비트", "hyperliquid": "Hyperliquid"}
KNOWN_UNPRICED_AGE = 24 * 3600


def known_note(check, level, detail, opened, now):
    if level != "warn":
        return None
    c, d = str(check or ""), str(detail or "")
    if c.startswith("debt:"):
        return "부채 표시 — 총자산에 이미 차감"
    if c.startswith("sync:chain:") and "외부 탐색기 색인" in d and "정체" not in d:
        return "외부 탐색기 색인 진행 중 — 끝나면 자동으로 채움"
    if c == "price:unpriced" and opened and now - float(opened) >= KNOWN_UNPRICED_AGE:
        return "시세 없는 보유 — 총자산에 넣지 않음"
    return None


def _inc_view(i, now):
    out = {"id": i["id"], "check": i["check"], "unit": i["unit"], "title": i["title"], "detail": i["detail"],
           "action": i["action"], "level": i.get("level"), "peak": i.get("peak"), "since": i.get("since"),
           "opened": i.get("opened"), "resolved": i.get("resolved"), "notified": bool(i.get("announced")),
           "telegram": i.get("notify", True)}
    kn = known_note(i.get("check"), i.get("level"), i.get("detail"), i.get("opened") or i.get("since"), now) if not i.get("resolved") else None
    if kn:
        out["known"] = kn
    return out


def build_status(st: dict, obs: dict, checks: list, now: float, h: dict) -> dict:
    inc = st.get("incidents", {})
    open_v = sorted((_inc_view(i, now) for i in inc.values()),
                    key=lambda x: (-LEVELS.get(x["level"], 0), -(x["opened"] or 0)))
    hist = [_inc_view(i, now) for i in reversed(st.get("history", [])) if not i.get("quiet")][:20]
    overall = "crit" if any(x["level"] == "crit" for x in open_v) else "warn" if open_v else "ok"
    watching = [{"id": c["id"], "unit": c["unit"], "title": c["title"], "level": c["level"], "detail": c["detail"],
                 "suppressed": c.get("suppressed")}
                for c in checks if c["level"] in ("warn", "crit") and c["id"] not in inc]
    units = []
    pm2 = obs.get("pm2") or {}
    logs = obs.get("logs") or {}
    by_unit = collections.defaultdict(list)
    for c in checks:
        by_unit[c["unit"]].append(c)
    for u in [x for x in h["units"]] + ["system"]:
        cs = by_unit.get(u, [])
        if u == "system" and not cs:
            continue
        if u in (h.get("optional_units") or ()) and obs.get("pm2") is not None and u not in (obs.get("pm2") or {}) and not cs:
            continue
        p = pm2.get(u) if obs.get("pm2") is not None else None
        lg = logs.get(u) or {}
        lv = max((LEVELS.get((inc.get(c["id"]) or {}).get("level") or "", 0) for c in cs), default=0)
        srcs = [{"id": c["id"], "label": c.get("label") or c["title"], "level": c["level"], "age": c.get("age"),
                 "detail": c["detail"]} for c in cs if c["id"].startswith(("sync:", "inbox:", "hb:"))]
        other = [{"id": c["id"], "title": c["title"], "chip": c.get("chip"), "level": c["level"], "detail": c["detail"]}
                 for c in cs if not c["id"].startswith(("sync:", "inbox:", "hb:", "proc:"))
                 and (c.get("chip") or c["level"] in ("warn", "crit", "off"))]
        units.append({"unit": u, "ignored": u in (h.get("ignore_units") or []),
                      "proc": ({"status": p.get("status"), "restarts": p.get("restarts"),
                                "uptime": p.get("uptime")} if p else ({"status": "없음"} if obs.get("pm2") is not None and u != "system" else None)),
                      "lastLog": lg.get("last_ts"), "errors60": lg.get("n_err"), "warn60": lg.get("n_warn"),
                      "level": {0: "ok", 1: "warn", 2: "crit"}[lv], "sources": srcs, "other": other})
    tg = obs.get("tg") or {}
    return {"v": 1, "updatedAt": now, "interval": h["interval_sec"], "overall": overall,
            "open": open_v, "resolved": hist, "watching": watching, "units": units,
            "wakeAt": obs.get("wake_at"),
            "telegram": {"configured": bool(tg.get("configured")), "lastOk": tg.get("last_ok"),
                         "lastFail": tg.get("last_fail"), "lastError": tg.get("last_error"),
                         "consecFail": tg.get("consec_fail", 0), "minLevel": h.get("telegram_min_level"),
                         "queued": len(st.get("outbox") or [])}}


def web_view(now: float = None) -> dict:
    now = now or _now()
    d = _read(STATUS_PATH, None)
    if isinstance(d, dict):
        d = common.scrub_secrets(d)[0]
    if not isinstance(d, dict):
        return {"v": 1, "overall": "unknown", "updatedAt": None, "open": [], "resolved": [], "watching": [],
                "units": [], "note": "아직 상태 점검 결과가 없어요 — 감시 프로그램(알림·감시)이 첫 점검 전이거나 꺼져 있어요"}
    iv = float(d.get("interval") or 60)
    age = now - float(d.get("updatedAt") or 0)
    if age > max(300, 5 * iv):
        d = dict(d)
        d["stale"] = True
        d["overall"] = "crit"
        d["open"] = [{"id": "monitor", "check": "monitor", "unit": "tj-alert", "title": "상태 감시 멈춤",
                      "detail": f"마지막 점검 {fmt_ago(age)} 전 — 아래 내용은 그 시점 기준",
                      "action": "pm2 restart tj-alert 후 pm2 logs tj-alert 확인", "level": "crit", "peak": "crit",
                      "since": d.get("updatedAt"), "opened": d.get("updatedAt"), "notified": False,
                      "telegram": False}] + list(d.get("open") or [])
    return d


def compact(view: dict) -> dict:
    op = view.get("open") or []
    return {"overall": view.get("overall"), "crit": sum(1 for x in op if x.get("level") == "crit"),
            "warn": sum(1 for x in op if x.get("level") != "crit"), "updatedAt": view.get("updatedAt"),
            "stale": bool(view.get("stale"))}


TG_STATS = {"last_ok": None, "last_fail": None, "fail_since": None, "consec_fail": 0, "last_error": None}


def note_send(ok: bool, err: str = None, now: float = None):
    now = now or _now()
    if ok:
        TG_STATS.update(last_ok=now, consec_fail=0, fail_since=None)
    else:
        TG_STATS["consec_fail"] += 1
        TG_STATS["last_fail"] = now
        TG_STATS["fail_since"] = TG_STATS["fail_since"] or now
        TG_STATS["last_error"] = common.redact_secret_text(err or "")[:160] or None


def note_wake(st: dict, now: float, h: dict):
    last = float(st.get("last_eval") or 0)
    if not last or now - last > h["wake_gap_sec"]:
        st["wake_at"] = now
        if last:
            st["sleeps"] = [x for x in (st.get("sleeps") or []) if now - x[1] < 8 * 86400] + [[last, now]]
        for r in (st.get("checks") or {}).values():
            if r.get("bad_since"):
                r.update(bad_since=now, nb=0)
            if r.get("crit_since"):
                r.update(crit_since=now, nc=0)
    st["last_eval"] = now


class Monitor:

    def __init__(self, cfg: dict = None, probes: dict = None):
        self.cfg = cfg
        self.probes = probes or {}
        self.st = _read(EVAL_PATH, {}) or {}
        self.st, n9 = common.scrub_secrets(self.st)
        if n9:
            try:
                common.atomic_write_json(EVAL_PATH, self.st)
            except OSError:
                pass
        common.scrub_secret_file(STATUS_PATH)
        self.logs = None
        self.last = 0.0
        self.interval = DEFAULTS["interval_sec"]
        self.obs, self.checks = None, None

    def _cfg(self):
        if self.cfg is not None:
            return self.cfg
        try:
            return common.load_config()
        except (Exception, SystemExit):
            return {}

    def due(self, now: float = None) -> bool:
        return (now or _now()) - self.last >= self.interval

    def observe(self, cfg: dict, h: dict, now: float, tg_configured: bool) -> dict:
        st, pr = self.st, self.probes
        _READ_FAIL.clear()
        pm2 = pr["pm2"]() if "pm2" in pr else pm2_list(h)
        if self.logs is None:
            self.logs = LogWatch(h.get("benign_patterns"), (cfg or {}).get("_disabled_chains") or sorted(common.DEFAULT_DISABLED_CHAINS))
        ld = h.get("log_dir") or os.path.join(os.environ.get("PM2_HOME") or os.path.expanduser("~/.pm2"), "logs")
        files = {}
        for u in h["units"]:
            p = (pm2 or {}).get(u) or {}
            files[u] = [x for x in (p.get("out"), p.get("err")) if x] or \
                [os.path.join(ld, f"{u}-out.log"), os.path.join(ld, f"{u}-error.log")]
        self.logs.poll(files, now)
        rmem = st.setdefault("restarts", {})
        intent_path = os.path.join(common.STATE_DIR, "intentional_restart.json")
        intent_doc = _read(intent_path, {}) or {}
        intents = _intent_entries(intent_doc)
        used_now = set()
        win = float(h["t"].get("intent_win", 900))
        intent_active = sorted({iu for (iu, its, _n9, _k9, w9) in intents if -60 <= now - its < (w9 or win)})
        for u, p in ((pm2 or {}).items()):
            if u not in h["units"]:
                continue
            m = rmem.setdefault(u, {"n": p["restarts"], "pid": p.get("pid"), "ev": []})
            k = max(0, p["restarts"] - int(m.get("n") or 0))
            if k == 0 and m.get("pid") and p.get("pid") and m["pid"] != p["pid"] and p.get("status") == "online":
                k = 1
            used = list(m.get("intent_used") or ([f"{u}:{m['intent_ts']}"] if m.get("intent_ts") else []))
            for (iu, its, n9, key9, w9) in intents:
                if not k:
                    break
                if iu != u or key9 in used or not (-60 <= now - its < (w9 or win)):
                    continue
                take = min(k, n9)
                k -= take
                used.append(key9)
                used_now.add(key9)
            m["intent_used"] = used[-10:]
            m.pop("intent_ts", None)
            m["ev"] = [x for x in m.get("ev", []) if now - x < 7200] + [now] * min(k, 20)
            m.update(n=p["restarts"], pid=p.get("pid"))
        if intents:
            done = {e[3] for e in intents if e[3] in used_now or now - e[1] > max(3600, e[4] or 0)}
            used_all = {k9 for m9 in rmem.values() for k9 in (m9.get("intent_used") or [])}
            done |= {e[3] for e in intents if e[3] in used_all}
            if all(e[3] in done for e in intents):
                try:
                    os.remove(intent_path)
                except OSError:
                    pass
            elif done:
                keep = [dict({"unit": e[0], "ts": e[1], "n": e[2]}, **({"win": e[4]} if e[4] else {}))
                        for e in intents if e[3] not in done]
                try:
                    common.atomic_write_json(intent_path, {"entries": keep})
                except OSError:
                    pass
        daily, review = collect_daily_review(now, self.logs, h)
        obs = {"now": now, "pm2": pm2,
                "tunnel": pr["tunnel"]() if "tunnel" in pr else collect_tunnel(h, pm2),
                "debt": collect_debt(self.logs, now, h),
                "exbal": collect_exbal(now),
                "restarts": {u: m.get("ev", []) for u, m in rmem.items()},
                "intent_active": intent_active,
                "logs": {u: self.logs.summary(u, now, h["t"]) for u in h["units"]},
                "sources": collect_sources(cfg, st, now),
                "bf": _read(os.path.join(common.STATE_DIR, "backfill_status.json"), {}) or {},
                "extrb": _read(os.path.join(common.STATE_DIR, "ext_rebuild_status.json"), None),
                "hb": read_heartbeats(),
                "daily": daily, "review": review,
                "webdiag": _read(os.path.join(common.STATE_DIR, "web_diag.json"), None),
                "backup": _read(os.path.join(common.STATE_DIR, "backups", "backup_status.json"), None),
                "rss": rss_track(st, pm2, now, float((h.get("t") or {}).get("rss_win") or 1800)),
                "balcheck": collect_balcheck(),
                "chainsweep": collect_chainsweep(),
                "inbox": pr["inbox"]() if "inbox" in pr else collect_inbox(st, now),
                "disk": pr["disk"]() if "disk" in pr else collect_disk(),
                "web": pr["web"]() if "web" in pr else collect_web(cfg, st, now),
                "tg": dict(TG_STATS, configured=bool(tg_configured)),
                "dm": collect_dm(st, now, bool(tg_configured))}
        obs["unreadable"] = collect_unreadable(st, now)
        return obs

    def tick(self, send_fn=None, tg_configured: bool = False, now: float = None, gate=None) -> dict:
        now = now or _now()
        cfg = self._cfg()
        h = settings(cfg)
        self.last = now
        self.interval = max(15, int(h["interval_sec"]))
        if not h["enabled"]:
            return {}
        st = self.st
        note_wake(st, now, h)
        obs = self.observe(cfg, h, now, tg_configured)
        obs["wake_at"] = st.get("wake_at")
        obs["sleeps"] = st.get("sleeps")
        obs["prev_inc"] = {k: {"level": (v or {}).get("level"), "keys": list((v or {}).get("keys") or [])}
                           for k, v in (st.get("incidents") or {}).items()}
        checks = evaluate(obs, h, open_ids={k: (v or {}).get("unit") for k, v in (st.get("incidents") or {}).items()})
        events = step(st, checks, now, h)
        for typ, i in events:
            (log.info if typ == "resolve" else log.warning)(
                "헬스 %s: %s · %s (%s)", {"open": "발생", "escalate": "악화", "resolve": "복구"}[typ],
                i["unit"], i["title"], i.get("level"))
        plan(st, events, now, h, bool(tg_configured))
        if send_fn is not None and tg_configured:
            deliver(st, send_fn, now, h, gate)
        status = build_status(st, obs, checks, now, h)
        try:
            common.atomic_write_json(EVAL_PATH, st)
            common.atomic_write_json(STATUS_PATH, status)
        except OSError as e:
            log.warning("헬스 상태 저장 실패: %s", e)
        self.obs, self.checks = obs, checks
        return status
