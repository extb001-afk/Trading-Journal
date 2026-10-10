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
OPTIONAL_UNITS = ["tj-review"]
_UNIT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
LEVELS = {"ok": 0, "warn": 1, "crit": 2}
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
    tn = out.get("tunnel") if isinstance(out.get("tunnel"), dict) else {}
    unit = str(tn.get("unit") or "").strip()
    url = str(tn.get("ready_url") or "").strip()
    if unit and _UNIT_RE.fullmatch(unit) and url.startswith(("http://127.0.0.1", "http://localhost")):
        out["tunnel"] = {"unit": unit, "ready_url": url}
        if unit not in out["units"]:
            out["units"] = list(out["units"]) + [unit]
        if unit not in (out.get("optional_units") or []):
            out["optional_units"] = list(out.get("optional_units") or []) + [unit]
    else:
        out["tunnel"] = {}
    out["bf_stall_sec"] = float(((cfg or {}).get("backfill") or {}).get("stall_sec") or 3600)
    hb = out.get("heartbeat_url")
    out["heartbeat_url"] = hb.strip() if isinstance(hb, str) and re.fullmatch(r"https?://[^\s]{4,500}", hb.strip()) else ""
    try:
        out["heartbeat_sec"] = max(60, int(float(out.get("heartbeat_sec") or 300)))
    except (TypeError, ValueError):
        out["heartbeat_sec"] = 300
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
        "onchain_check.json": [r"balcheck:(?:mismatch|stale|disc)"],
        "exf_state.json": [r"sync:ex:(?!upbit$).+"],
        "exf_active.json": [r"sync:ex:(?!upbit$).+"],
        "upbit_balances.json": [r"sync:ex:upbit", r"upbit:pending"],
        "upbit_sync.json": [r"sync:ex:upbit", r"upbit:pending"],
        "spot.json": [r"sync:price:.+"],
        "web_diag.json": [r"sync:price:dex", r"goplus:queue", r"ledger:neg", r"price:proof", r"price:unpriced", r"web:build", r"web:buildmode", r"rabby:gap"],
        "daily_cache.json": [r"daily:close"],
        "reviews_llm.json": [r"review:daily"],
        "chain_sweep.json": [r"chainsweep:(?:untracked|stale)"],
        "chain_activity.json": [r"chainsweep:untracked"],
        "backups/backup_status.json": [r"backup:age"],
        "backups/offsite_status.json": [r"offsite:age"],
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


BUILD_EX_WHY = {"rebuild": "원장 재구축 중", "swap": "원장 교체 직후"}


def build_ex_text(ex, now: float) -> str:
    if not isinstance(ex, list):
        return ""
    xs = [x for x in ex if isinstance(x, dict) and isinstance(x.get("ms"), (int, float)) and isinstance(x.get("at"), (int, float))
          and now - float(x["at"]) < 86400]
    if not xs:
        return ""
    w9 = {str(x.get("why") or "") for x in xs}
    lab = "원장 재구축 중·교체 직후" if {"rebuild", "swap"} <= w9 else BUILD_EX_WHY.get(next(iter(w9)), "원장 재구축 중") if len(w9) == 1 else "원장 재구축 중"
    return (f" · {lab} 빌드 {len(xs)}회(최대 {max(float(x['ms']) for x in xs) / 1000:.1f}초 · 마지막 {fmt_ts(max(float(x['at']) for x in xs))})는 표본 제외")


def build_mode_view(bp, now: float):
    if not isinstance(bp, dict):
        return None
    try:
        nf, ni, fails = int(bp.get("fork") or 0), int(bp.get("inproc") or 0), int(bp.get("fails") or 0)
        paused = int(bp.get("paused") or 0)
        fmax = int(bp.get("fail_max") or 3)
    except (TypeError, ValueError):
        return None
    il = bp.get("inproc_last") if isinstance(bp.get("inproc_last"), dict) else None
    last_in = ""
    if il and isinstance(il.get("at"), (int, float)):
        last_in = f" · 마지막 웹 안 빌드 {fmt_ts(il['at'])}({fmt_ago(now - float(il['at']))} 전) — {str(il.get('why') or '?')[:120]}"
    if not bp.get("on"):
        return {"title": "빌드 방식: 웹 안", "chip": "빌드 웹 안", "level": "ok", "fork": False,
                "detail": f"화면 계산을 웹 프로세스 안에서 — {str(bp.get('why') or '별도 프로세스 안 씀')[:120]}"}
    core9 = bp.get("core")
    where = f"코어 {core9}번 전용 · 코어 {bp.get('cores')}개" if core9 is not None else f"코어 {bp.get('cores')}개"
    cnt = f"이번 가동 별도 {nf}회 · 웹 안 {ni}회"
    if paused > 0:
        return {"title": "빌드 방식: 웹 안(별도 프로세스 쉼)", "chip": f"빌드 웹 안 · 쉼 {fmt_ago(paused)}", "level": "warn", "fork": False,
                "detail": f"별도 프로세스 연속 실패 {fmax}번 — {fmt_ago(paused)} 뒤 다시 별도 프로세스로({where}) · {cnt}"
                          + (f" · 직전 실패: {str(bp.get('last_err'))[:120]}" if bp.get("last_err") else "") + last_in}
    return {"title": "빌드 방식: 별도 프로세스", "chip": "빌드 별도 프로세스", "level": "ok", "fork": True,
            "detail": f"화면 계산 = 별도 프로세스({where}) · {cnt}" + (f" · 연속 실패 {fails}/{fmax}" if fails else "") + last_in}


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
        line = PM2_TS_RX.sub("", line.rstrip("\n"), count=1)
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


_CHALLENGE_RX = re.compile(r"just a moment|cf-mitigated|cf-chl|challenge-platform|attention required", re.I)


def is_challenge(msg) -> bool:
    return bool(msg) and bool(_CHALLENGE_RX.search(str(msg)))


def es_reset_text(now: float = None) -> str:
    now = time.time() if now is None else now
    return time.strftime("%H:%M", time.localtime((int(now) // 86400 + 1) * 86400 + 300))


PACE_GRACE_SEC = 7200


def pace_alive(src: dict, now: float):
    if (src or {}).get("ok") is False:
        return None
    try:
        pa = float((src or {}).get("paced_at") or 0)
        ls = float((src or {}).get("last_success_ts") or 0)
    except (TypeError, ValueError):
        return None
    if pa <= 0 or now - pa > 600:
        return None
    if ls <= 0 or now - ls > PACE_GRACE_SEC:
        return None
    return pa


def fill_paced(sub: str, budget: float, keep: float = 0.02, now: float = None) -> bool:
    now = time.time() if now is None else now
    day = int(now // 86400)
    n = 0
    try:
        d = os.path.join(common.quota_dir(), sub)
        for f in os.listdir(d):
            if f.endswith(".json"):
                j = _read(os.path.join(d, f), None)
                if isinstance(j, dict) and j.get("day") == day:
                    n += int(j.get("n") or 0)
    except (OSError, TypeError, ValueError):
        return False
    return n >= budget * ((now % 86400) / 86400.0) - budget * keep


def fill_slow(obs: dict, bu: str, key: str, it: dict = None, now: float = None) -> bool:
    if not (obs.get("fill_paced") or {}).get(bu):
        return False
    now = time.time() if now is None else now
    try:
        pa9 = float((it or {}).get("paced_at") or 0)
    except (TypeError, ValueError):
        pa9 = 0.0
    if pa9 <= 0 or now - pa9 > 3600:
        return False
    ps9 = (((obs.get("hb") or {}).get(bu) or {}).get("sources") or {}).get(str(key).split(":")[0]) or {}
    if bu == "sol" and ps9.get("primary") == "open":
        return False
    return (bu == "evm" and ps9.get("kind") == "etherscan") or (bu == "sol" and bool(ps9.get("helius_budget")))


def _fill_paced_map(cfg: dict, now: float) -> dict:
    try:
        import bf_engine
        es9 = (cfg or {}).get("etherscan") or {}
        if float(es9.get("pace_burst_pct", 4)) >= 100:
            return {"evm": False, "sol": False}
        keep = min(50.0, max(0.0, float(es9.get("fill_keep_pct", 2)))) / 100.0
        es = float(es9.get("daily_budget") or 80000)
        burst = max(0.0, float(es9.get("pace_burst_pct", 4))) / 100.0
        return {"evm": bf_engine.es_ledger_rooms(now, es, burst, keep)["fill"] <= 0,
                "sol": bf_engine.ledger_rooms("helius_budget", bf_engine.helius_day_budget(cfg), burst, keep, now, floor=bf_engine.helius_head_min(cfg), flex=bf_engine.helius_flex(cfg))["fill"] <= 0}
    except Exception:
        return {}


PACE_NOTE_FILL = "하루 한도 안에서 천천히 확인 중 — 새 거래 확인 몫을 먼저 떼어 두고 옛 기록은 남는 몫으로 뒤에서 채워요(새 거래 확인이 그 몫보다 많으면 남은 시간에 고르게 나눠 확인)"
PACE_NOTE_HEAD = "하루 한도 안에서 천천히 확인 중 — 새 거래 확인이 하루 몫보다 많아 남은 시간에 고르게 나눠 확인해요(평소보다 늦을 수 있어요)"


def _pace_note(cfg: dict, now: float, unit: str) -> str:
    ff = None
    try:
        import bf_engine
        es9 = (cfg or {}).get("etherscan") or {}
        keep = min(50.0, max(0.0, float(es9.get("fill_keep_pct", 2)))) / 100.0
        burst = max(0.0, float(es9.get("pace_burst_pct", 4))) / 100.0
        if unit == "sol":
            ff = bf_engine.ledger_rooms("helius_budget", bf_engine.helius_day_budget(cfg), burst, keep, now, floor=bf_engine.helius_head_min(cfg), flex=bf_engine.helius_flex(cfg)).get("fillFirst")
        else:
            ff = bf_engine.es_ledger_rooms(now, float(es9.get("daily_budget") or 80000), burst, keep).get("fillFirst")
    except Exception:
        ff = None
    return PACE_NOTE_HEAD if ff is False else PACE_NOTE_FILL


def human_err(msg, label: str = "") -> str:
    if not msg:
        return msg
    m = common.redact_secret_text(str(msg))
    if is_challenge(m):
        return "외부 탐색기가 사람 확인 화면으로 막는 중(HTTP 403 · 우리 쪽 문제 아님)"
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


def leaf_overflow_text(cur: dict, warn: int = 100_000):
    try:
        n = int((cur or {}).get("_leaf_overflow") or 0)
    except (TypeError, ValueError, AttributeError):
        return None
    if n <= 0:
        return None
    t = f"내부 입금 확인 대기 잎 블록 {n:,}개(큐 넘침 — 노드 trace 회복 뒤 자동)"
    return ("넘침 경고: " + t + " · 추적(trace) 노드 확인 필요") if n >= warn else t


def trace_later_drop_text(cur: dict, warn: int = 100_000):
    try:
        n = int((cur or {}).get("_trace_later_dropped") or 0)
        o = int((cur or {}).get("_trace_later_overflow") or 0)
    except (TypeError, ValueError, AttributeError):
        return None
    out = []
    if o > 0:
        t = f"내부 이동 확인 대기 거래 {o:,}건(늦은 채움 큐 넘침 — 노드 trace 회복 뒤 자동)"
        out.append(("넘침 경고: " + t + " · 추적(trace) 노드 확인 필요") if o >= warn else t)
    if n > 0:
        out.append(f"넘침 경고: 늦은 채움(내부 이동 trace) 큐에서 {n:,}건을 뺐어요 — 그 거래의 내부 이동은 미확인 · 추적(trace) 노드 확인 필요")
    return " · ".join(out) or None


def uncollected_text(rt):
    if not isinstance(rt, dict):
        return None

    def _d(t):
        return datetime.fromtimestamp(float(t), KST).strftime("%Y-%m-%d") \
            if isinstance(t, (int, float)) and not isinstance(t, bool) and t > 0 else None
    try:
        a, b = int(rt.get("from") or 0), int(rt.get("to") or 0)
    except (TypeError, ValueError):
        return None
    if b <= 0:
        return None
    da, db = _d(rt.get("from_ts")), _d(rt.get("floor_ts"))
    per = f"({da or '?'}~{db}" + " 전)" if db else (f"({da}부터)" if da else "")
    return (f"옛 구간 미수집: 블록 {a:,}~{b:,}{per} — 로그 노드가 보관하지 않아 못 받음 · "
            "그 앞 보유는 기초 잔고(원가 미확인)로 맞춤")


def collect_sources(cfg: dict, st: dict, now: float) -> list:
    S = common.STATE_DIR
    out = []
    chains = (cfg.get("chains") or {}) if cfg else {}
    hb = read_heartbeats(cfg)
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

    rpcfb9 = _read(os.path.join(S, "rpc_fallback.json"), {}) or {}
    rpcfb9 = rpcfb9 if isinstance(rpcfb9, dict) else {}
    pn9 = None
    evm_ch9 = {w.get("chain") for w in ((cfg or {}).get("wallets") or []) if isinstance(w, dict) and w.get("type", "evm") == "evm"}
    for c in sorted(chains):
        if not isinstance(chains[c], dict):
            continue
        if c not in evm_ch9:
            used_hb.update({("evm", c), ("evm", f"{c}:rpclog")})
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
        pa9 = pace_alive(hb_src.get(("evm", c)), now)
        if pa9:
            cands.append(pa9)
            if pn9 is None:
                pn9 = _pace_note(cfg, now, "evm")
            hex_ = " · ".join(x for x in (hex_, pn9) if x)
        esu9 = (hb_src.get(("evm", c)) or {}).get("es_daily_until")
        if isinstance(esu9, (int, float)) and not isinstance(esu9, bool) and esu9 > now:
            hex_ = " · ".join(x for x in (hex_, f"이더스캔 하루 한도 쉼 — {time.strftime('%H:%M', time.localtime(float(esu9)))} 저절로 복귀") if x)
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
        gs9 = [g for g in ((d or {}).get("_retention_gaps") or []) if isinstance(g, dict)] if isinstance(d, dict) else []
        rt9 = uncollected_text({"from": min(int(g.get("from") or 0) for g in gs9), "to": max(int(g.get("to") or 0) for g in gs9),
                                "from_ts": min(gs9, key=lambda g: int(g.get("from") or 0)).get("from_ts"),
                                "floor_ts": max(gs9, key=lambda g: int(g.get("to") or 0)).get("floor_ts")}) if gs9 \
            else uncollected_text((hb_src.get(("evm", c)) or {}).get("retention"))
        if rt9:
            hex_ = " · ".join(x for x in (hex_, rt9) if x)
        lo9 = leaf_overflow_text(d) if isinstance(d, dict) else None
        if lo9:
            hex_ = " · ".join(x for x in (hex_, lo9) if x)
        td9 = trace_later_drop_text(d) if isinstance(d, dict) else None
        if td9:
            hex_ = " · ".join(x for x in (hex_, td9) if x)
        bk9h = (hb_src.get(("evm", c)) or {}).get("rpc_bk")
        if isinstance(bk9h, dict):
            t9 = []
            if bk9h.get("new"):
                t9.append(f"새 지갑 {int(bk9h['new'])}개 과거 기록 수집 중")
            if bk9h.get("internal"):
                t9.append(f"지갑 {int(bk9h['internal'])}개 내부 이동(internal) RPC 로 다시 채우는 중")
            if bk9h.get("extend"):
                t9.append(f"지갑 {int(bk9h['extend'])}개 과거 창 확장 중")
            if t9:
                hex_ = " · ".join(x for x in (hex_, " · ".join(t9) + f"(옛 구간 {float(bk9h.get('pct') or 0):.0f}%)") if x)
        hbs9 = hb_src.get(("evm", c)) or {}
        fb9h = hbs9.get("rpc_fb")
        if "rpc_fb" not in hbs9:
            r9 = rpcfb9.get(c) if isinstance(rpcfb9.get(c), dict) else {}
            fb9h = r9 if r9.get("active") and r9.get("text") else None
        if not (isinstance(fb9h, dict) and fb9h.get("text")):
            fb9h = None
        if fb9h:
            hex_ = " · ".join(x for x in (hex_, str(fb9h["text"])[:200]) if x)
        else:
            lim9h = (hb_src.get(("evm", c)) or {}).get("rpc_limited")
            if isinstance(lim9h, str) and lim9h:
                hex_ = " · ".join(x for x in (hex_, f"제한된 백업({lim9h[:80]})") if x)
            try:
                import inflow_probe
                if1 = inflow_probe.health_text(hbs9.get("inflow"), now)
                if if1:
                    hex_ = " · ".join(x for x in (hex_, if1) if x)
            except Exception:
                pass
        out.append(_source(st, now, f"chain:{c}", "tj-evm", _cname(c), "chain",
                           max(cands) if cands else None, human_err(herr, _cname(c)), hex_))
        out[-1]["err_raw"] = common.redact_urls(common.redact_secret_text(herr, generic=False)) if herr else None
        if rt9:
            out[-1]["uncollected"] = True
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
        if not cfail9:
            for k9, v9 in dd9.items():
                w9 = str(k9)[4:].lower() if str(k9).startswith("_bk:") else ""
                if w9 in wl9 and isinstance(v9, dict) and v9.get("why") == "new":
                    done9, to9 = v9.get("done"), v9.get("to")
                    if type(done9) is int and type(to9) is int and done9 < to9:
                        bw9.add(w9)
        if chains[c].get("rpc_log_discovery") and common.chain_discovery(c, chains[c]) != "rpc" and isinstance(dr, dict):
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
    if (os.path.exists(os.path.join(S, "cursor_sol.json")) or ("sol", "sol") in hb_src) and not runner_waiting("sol", SOL_WAIT_WHY, now):
        d = _read(os.path.join(S, "cursor_sol.json"), {}) or {}
        hts, herr, hex_ = hbinfo("sol", "sol")
        cands = [float(x) for x in (d.get("_synced_at"), hts) if x]
        pa9 = pace_alive(hb_src.get(("sol", "sol")), now)
        if pa9:
            cands.append(pa9)
            hex_ = " · ".join(x for x in (hex_, _pace_note(cfg, now, "sol")) if x)
        hcu9 = (hb_src.get(("sol", "sol")) or {}).get("helius_daycap_until")
        if isinstance(hcu9, (int, float)) and not isinstance(hcu9, bool) and hcu9 > now:
            hex_ = " · ".join(x for x in (hex_, f"헬리우스 하루 한도 쉼 — {time.strftime('%H:%M', time.localtime(float(hcu9)))} 저절로 복귀") if x)
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
    if os.path.exists(ub) and upbit_connected():
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
        has9 = any(isinstance(sp.get(k9), dict) and sp.get(k9) for k9 in ("usd", "ex_usd", "dex_usd"))
        wt9 = sp.get("want") if isinstance(sp.get("want"), dict) else None
        try:
            need9 = wt9 is None or bool(wt9.get("ex")) or int(wt9.get("dex") or 0) > 0
        except (TypeError, ValueError):
            need9 = True
        if not has9 and need9:
            ex9 = " · ".join(x for x in (ex9, "받은 시세 없음(바퀴는 돎)") if x)
        out.append(_source(st, now, "price:spot", "tj-web", "시세 갱신", "price", sp.get("updated") if (has9 or not need9) else None, None, ex9))
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


def upbit_connected() -> bool:
    try:
        import settings_store
        env9 = {}
        try:
            with open(settings_store.ENV_PATH, "r", encoding="utf-8-sig") as f9:
                for line9 in f9:
                    kv9 = common.parse_env_line(line9)
                    if kv9 and kv9[0]:
                        env9[kv9[0]] = kv9[1]
        except FileNotFoundError:
            env9 = {}
        return bool((os.environ.get("UPBIT_ACCESS") or env9.get("UPBIT_ACCESS")) and (os.environ.get("UPBIT_SECRET") or env9.get("UPBIT_SECRET")))
    except Exception:
        return True


SOL_WAIT_WHY = ("Helius 키 없음", "Solana 지갑 없음")


def runner_waiting(unit: str, whys: tuple, now: float = None) -> bool:
    rb = _read(os.path.join(common.STATE_DIR, f"runner_{unit}.json"), None)
    if not isinstance(rb, dict) or rb.get("state") != "waiting" or rb.get("by") == "reload":
        return False
    try:
        age = (time.time() if now is None else float(now)) - float(rb.get("ts"))
    except (TypeError, ValueError):
        return False
    return -60 <= age < 120 and any(str(rb.get("why") or "").startswith(w) for w in whys)


def read_heartbeats(cfg: dict = None) -> dict:
    out = {}
    off = set((cfg or {}).get("_disabled_chains") or ())
    evm_wait = False
    if cfg is not None and not any(isinstance(w, dict) and w.get("type", "evm") == "evm" for w in cfg.get("wallets") or []):
        rb = _read(os.path.join(common.STATE_DIR, "runner_evm.json"), None)
        evm_wait = (isinstance(rb, dict) and rb.get("state") == "waiting" and rb.get("why") == "EVM 지갑 없음"
                    and isinstance(rb.get("ts"), (int, float)) and 0 <= time.time() - float(rb["ts"]) < 120)
    for p in glob.glob(os.path.join(HB_DIR, "*.json")):
        d = _read(p, None)
        if isinstance(d, dict) and d.get("ts") and d.get("schema") == 1 and isinstance(d.get("sources"), dict):
            unit = str(d.get("unit") or os.path.basename(p)[:-5])
            if unit == "evm" and evm_wait:
                continue
            if unit == "sol" and runner_waiting("sol", SOL_WAIT_WHY):
                continue
            if unit == "evm" and off:
                d = dict(d, sources={k: v for k, v in d["sources"].items() if str(k).split(":", 1)[0] not in off})
            out[unit] = d
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
              "ledger": m.get("ledger"), "onchain": m.get("onchain"),

              "carriedN": int(m.get("carriedN") or 0), "seenAt": m.get("seenAt"),
              "firstSeen": m.get("firstSeen")} for m in conf]
    fixed = [m for m in mm if m.get("ledgerFixed")]
    return {"checkedAt": d.get("checkedAt"), "confirmed": len(conf), "watch": len(mm) - len(conf) - len(fixed),
            "resolving": len(fixed),
            "errors": len(d.get("errors") or []), "top": top, "items": items,
            "unchecked": d.get("unchecked"), "capped": bool(d.get("capped")), "pairs": d.get("pairs"),
            "disc": d.get("disc") if isinstance(d.get("disc"), dict) else None}


BAL_READY_SEC = 86400
BAL_BUSY_MAX = 3 * 86400


def collect_bal_busy(now: float, extrb=None, bf=None) -> dict:
    out = {"global": [], "chains": {}, "wallets": {}}

    def addc(ch, why):
        lst = out["chains"].setdefault(str(ch), [])
        if why not in lst:
            lst.append(why)
    try:
        conn = sqlite3.connect(common.sqlite_ro_uri(common.DB_PATH), uri=True, timeout=2)
        try:
            rows = conn.execute("SELECT k, v FROM meta WHERE k LIKE 'ext_prewindow:%'").fetchall()
        finally:
            conn.close()
        for k, v in rows:
            try:
                if int(v) <= 0:
                    continue
            except (TypeError, ValueError):
                continue
            ch = str(k)[len("ext_prewindow:"):]
            if re.fullmatch(r"[a-z0-9]{2,20}", ch):
                addc(ch, "옛 기록을 반영하는 재계산 대기")
            else:
                if "재계산 대기" not in out["global"]:
                    out["global"].append("재계산 대기")
    except sqlite3.Error:
        out["unknown"] = True
    if isinstance(extrb, dict) and extrb.get("running"):
        out["global"].append("재계산 중")
    for unit, items in ((bf or {}).items() if isinstance(bf, dict) else ()):
        if not isinstance(items, dict) or str(unit).startswith("_"):
            continue
        for key, it in items.items():
            if not isinstance(it, dict) or not (str(key).endswith(":extend") or it.get("phase") == "extend") or it.get("phase") == "done":
                continue
            try:
                if now - float(it.get("updated") or 0) > 7 * 86400:
                    continue
            except (TypeError, ValueError):
                continue
            ch = {"bsc": "bsc", "sol": "sol", "ex": "upbit"}.get(unit) or (str(key).split(":", 1)[0] if unit == "evm" else None)
            if ch:
                addc(ch, "과거 기록 범위를 넓히는 중")
    cb = _read(os.path.join(common.STATE_DIR, "cursor_bsc.json"), None)
    nw = cb.get("_neww") if isinstance(cb, dict) else None
    if isinstance(nw, dict):
        for w in nw.get("wallets") or []:
            out["wallets"].setdefault(f"bsc|{str(w).lower()}", []).append("새 지갑 과거 기록 수집 중")
    bn = _read(os.path.join(common.STATE_DIR, "bsc_nonce.json"), None)
    for w, ws in ((bn.get("w") or {}).items() if isinstance(bn, dict) and isinstance(bn.get("w"), dict) else ()):
        try:
            miss = int((ws or {}).get("missing") or 0)
        except (TypeError, ValueError):
            continue
        if miss > 0:
            out["wallets"].setdefault(f"bsc|{str(w).lower()}", []).append(f"로그 없는 송금 {miss}건 회수 중")
    return out


def bal_busy_reasons(it: dict, bb: dict, sync_bad: dict) -> list:
    ch = str(it.get("chain") or "")
    w = str(it.get("wallet") or "")
    w = w if ch == "sol" else w.lower()
    out = []
    for x in list((bb or {}).get("global") or []) + list(((bb or {}).get("chains") or {}).get(ch) or []) \
            + list(((bb or {}).get("wallets") or {}).get(f"{ch}|{w}") or []):
        if x not in out:
            out.append(x)
    if ch in (sync_bad or {}):
        out.append(sync_bad[ch])
    if it.get("carried"):
        out.append("이번 판에 다시 대조하지 못함(다음 판에 이어서)")
    return out


BAL_RB_WHY = ("옛 기록을 반영하는 재계산 대기", "재계산 대기", "재계산 중")


def bal_rb_wait(why) -> bool:
    return any(w in BAL_RB_WHY for w in (why or ()))


def _fmt_left(sec) -> str:
    sec = max(0, int(sec))
    if sec < 3600:
        return f"{max(1, sec // 60)}분"
    if sec < 86400:
        h, m = divmod(sec // 60, 60)
        return f"{h}시간" + (f" {m}분" if m and h < 10 else "")
    d, h = divmod(sec // 3600, 24)
    return f"{d}일" + (f" {h}시간" if h else "")


def _bf_ext_pending(bf) -> list:
    def path9(key):
        ch9, _, rest9 = str(key).partition(":")
        return (ch9.lower(), rest9 if rest9 in ("extend", "job", "rpc") else None)
    out = []
    for unit, items in ((bf or {}).items() if isinstance(bf, dict) else ()):
        if not isinstance(items, dict) or str(unit).startswith("_"):
            continue
        last = {}
        for key, it in items.items():
            ch9, p9 = path9(key)
            if p9 and isinstance(it, dict):
                try:
                    u9 = float(it.get("updated") or 0)
                except (TypeError, ValueError):
                    u9 = 0.0
                last[(ch9, p9)] = max(last.get((ch9, p9), 0.0), u9)
        for key, it in items.items():
            if not isinstance(it, dict) or not (str(key).endswith(":extend") or it.get("phase") == "extend") or it.get("phase") == "done":
                continue
            ch9, p9 = path9(key)
            if p9 and max(last.get((ch9, q9), -1.0) for q9 in ("extend", "job", "rpc")) > last.get((ch9, p9), 0.0):
                continue
            out.append((unit, key, it))
    return out


def bf_ext_phrase(bf, now: float) -> str:
    acc = {}
    for unit, key, it in _bf_ext_pending(bf):
        try:
            if now - float(it.get("updated") or 0) >= 3 * 3600:
                continue
            dn, tt, eta = float(it.get("done") or 0), float(it.get("total") or 0), float(it.get("eta_sec") or 0)
        except (TypeError, ValueError):
            continue
        ch = {"bsc": "bsc", "sol": "sol", "ex": "upbit"}.get(unit) or str(key).split(":", 1)[0]
        a = acc.setdefault(ch, [0.0, 0.0, 0.0])
        a[0] += max(0.0, dn)
        a[1] += max(0.0, tt)
        a[2] = max(a[2], eta)
    out = []
    for ch, (dn, tt, eta) in sorted(acc.items(), key=lambda kv: (-kv[1][2], kv[0])):
        bits = ([f"지금 {min(99, int(dn * 100 / tt))}%"] if tt > 0 else []) + ([f"약 {_fmt_left(eta)} 남음"] if eta > 0 else [])
        out.append(f"{CHAIN_NAME.get(ch) or EX_NAME.get(ch) or ch} 과거 기록 넓히기" + (f"({' · '.join(bits)})" if bits else ""))
    return " · ".join(out[:2]) + (f" 외 {len(out) - 2}개" if len(out) > 2 else "")


BAL_RB_LIVE_SEC = 6 * 3600


def bf_ext_live(obs: dict, now: float, stall_sec: float = 3600) -> bool:
    for unit, key, it in _bf_ext_pending((obs or {}).get("bf")):
        try:
            upd = float(it.get("updated") or 0)
            moved = float(it.get("moved_at") or it.get("started") or upd or 0)
        except (TypeError, ValueError):
            continue
        if now - upd < BAL_RB_LIVE_SEC and (now - moved <= float(stall_sec or 3600) or fill_slow(obs, unit, key, it, now)):
            return True
    return False


BF_EXT_ORPHAN_SEC = 24 * 3600


def bf_ext_open(obs: dict, chain=None) -> bool:
    pre = (str(chain).lower() + ":") if chain else ""
    now = float((obs or {}).get("now") or time.time())
    for _u, key, it in _bf_ext_pending((obs or {}).get("bf")):
        if pre and not str(key).lower().startswith(pre):
            continue
        try:
            if now - float(it.get("updated") or 0) >= BF_EXT_ORPHAN_SEC:
                continue
        except (TypeError, ValueError):
            continue
        return True
    return False


def rb_wait_sentence(bf, now: float) -> str:
    ph = bf_ext_phrase(bf, now)
    return (f"{ph}가 끝나면 원장 자동 재계산으로 사라져요 — 기다리면 됨" if ph
            else "원장 자동 재계산이 끝나면 사라져요 — 기다리면 됨")


def _fq(x) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "?"
    s9 = f"{v:,.2f}" if abs(v) >= 1000 else f"{v:,.6g}"
    return s9.replace("-", "−")


def bal_guess(it: dict) -> str:
    try:
        lq, oq = float(it.get("ledger")), float(it.get("onchain"))
    except (TypeError, ValueError):
        return ""
    if abs(lq) < 1e-12 and oq > 0:
        return "장부에 이 코인이 아예 없어요 — 들어온 기록을 못 받은 듯해요"
    if abs(oq) < 1e-12 and lq > 0:
        return "실제로는 다 빠져나갔어요 — 장부에 없는 출금이 있는 듯해요"
    if oq > lq:
        return "실제가 더 많아요 — 장부에 없는 입금(로그 없는 입금·내부 이동 등)이 있는 듯해요"
    if lq > oq:
        return "장부가 더 많아요 — 장부에 없는 출금·수수료(로그 없는 송금 등)가 있는 듯해요"
    return ""


def bal_line(it: dict) -> str:
    ch = it.get("chain")
    d9 = f"(차이 ${abs(float(it.get('diffUsd') or 0)):,.0f})"
    qty9 = it.get("ledger") is not None and it.get("onchain") is not None
    if ch == "upbit":
        return f"업비트 {it.get('sym')} — " + (f"장부 {_fq(it.get('ledger'))} · 업비트 잔고 {_fq(it.get('onchain'))} {d9}" if qty9 else d9)
    return (f"{CHAIN_NAME.get(ch, ch)} 지갑 {_short_addr(it.get('wallet'))} 의 {it.get('sym')} — "
            + (f"장부 {_fq(it.get('ledger'))} · 실제 {_fq(it.get('onchain'))} {d9}" if qty9 else d9))


def bal_text(items: list, more: bool = False) -> str:
    items = sorted(items or [], key=lambda x: -abs(float(x.get("diffUsd") or 0)))
    n = len(items)
    lines = [f"🔴 잔고가 장부와 하루 넘게 다른 곳이 {n}곳 더 생겼어요" if more else f"🔴 잔고가 장부와 하루 넘게 달라요 · {n}곳"]
    stuck = sorted({w9 for x in items for w9 in (x.get("stuck") or [])})
    if stuck:
        lines.append("할 일: 기다리기 — " + " · ".join(stuck[:3]) + "이(가) 3일 넘게 안 끝났어요. 상태 패널에서 진행을 확인하세요.")
        rbw9 = next((str(x["rbw"]) for x in items if x.get("rbw")), "")
        if rbw9:
            lines.append(f"  {rbw9}")
    else:
        lines.append("할 일: 앱 › 잔고 맞추기에서 이 지갑·코인을 열어 빠진 입출금이 있는지 보세요(장부는 자동으로 고치지 않아요) — 수집·재계산은 다 끝났어요.")
    for it in items[:5]:
        lines.append(bal_line(it))
        g9 = bal_guess(it)
        if g9:
            lines.append(f"  짐작: {g9}")
    if n > 5:
        lines.append(f"… 외 {n - 5}곳(앱 › 잔고 맞추기)")
    return "\n".join(lines)


def _short_addr(a: str) -> str:
    a = str(a or "")
    return a[:6] + "…" + a[-4:] if len(a) > 14 else a


REST_LATE_MARGIN = 900
REST_LATE_MAX = 13 * 3600


def tier_rest_map() -> dict:
    out = {}
    for f in glob.glob(os.path.join(common.STATE_DIR, "addr_tier_*.json")):
        if os.path.basename(f) == "addr_tier_req.json":
            continue
        d = _read(f, None)
        if not isinstance(d, dict) or not isinstance(d.get("pairs"), dict) or not d.get("scope"):
            continue
        sc = str(d["scope"])
        for w, p in d["pairs"].items():
            if isinstance(p, dict) and (int(p.get("tier") or 0) > 0 or p.get("rest") is True) and not p.get("hold"):
                out.setdefault(sc, {})[w if sc == "sol" else str(w).lower()] = int(p.get("full") or 0)
    return out


def rest_late(it: dict, rest: dict, now: float = None) -> bool:
    now = time.time() if now is None else now
    ch = it.get("chain")
    w = it.get("wallet") or ""
    w = w if ch == "sol" else str(w).lower()
    full = (rest.get(ch) or {}).get(w)
    if full is None:
        return False
    try:
        fs = float(it["firstSeen"])
    except (KeyError, TypeError, ValueError):
        return False
    return full < fs + REST_LATE_MARGIN and 0 <= now - fs < REST_LATE_MAX


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
    try:
        rest9 = tier_rest_map()
    except Exception:
        rest9 = {}
    for it in bc.get("items") or []:
        ch, w = it.get("chain"), str(it.get("wallet") or "").lower()
        if rest9 and rest_late(it, rest9):
            late9.append(it)
        elif ch in pw and w and any(p9 and w.startswith(p9) for p9 in pw[ch]):
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


def collect_poison():
    try:
        import tsfix
        return tsfix.status()
    except (Exception, SystemExit) as e:
        log.warning("격리 기록 집계 실패: %s", e)
        return {"error": common.safe_err(e)[:160]}


def _sweep_scope():
    try:
        import copy
        import chainsweep as _cs9
        cf9 = _read(common.CONFIG_PATH, None)
        if not isinstance(cf9, dict) or not isinstance(cf9.get("wallets"), list):
            return set(), {}
        cf9 = copy.deepcopy(cf9)
        cf9.setdefault("chains", {})
        off9 = {}
        for n, cc in (cf9.get("chains") or {}).items():
            if isinstance(cc, dict) and not common.chain_enabled(n, cc):
                co9 = cc.get("_chainoff") if isinstance(cc.get("_chainoff"), dict) else {}
                try:
                    off9[n] = float(co9["at"]) if co9.get("auto") is True and co9.get("at") else None
                except (TypeError, ValueError):
                    off9[n] = None
        common.apply_activity_gate(cf9)
        return {pr for pr in _cs9.wallets(cf9)[2] if pr[0] not in off9}, off9
    except (Exception, SystemExit):
        return set(), {}


def collect_chainsweep():
    d = _read(os.path.join(common.STATE_DIR, "chain_sweep.json"), None)
    if not isinstance(d, dict):
        return None
    fs = [f for f in (d.get("findings") or []) if isinstance(f, dict)]
    joined9, off9 = _sweep_scope()
    fs = [f for f in fs if (str(f.get("chain") or ""), str(f.get("wallet") or "").lower()) not in joined9]
    n_off = 0
    if off9:
        act9 = _activity_pairs()
        keep9 = []
        for f in fs:
            c9 = str(f.get("chain") or "")
            if c9 in off9:
                at9 = off9[c9]
                a9 = (act9.get(f"{c9}:{str(f.get('wallet') or '').lower()}") or {}).get("activatedAt")
                try:
                    new9 = at9 is not None and a9 is not None and float(a9) > at9
                except (TypeError, ValueError):
                    new9 = False
                if not new9:
                    n_off += 1
                    continue
            keep9.append(f)
        fs = keep9
    try:
        import chainsweep as _cs9
        sp9 = _read(common.BACKFILL_SPEED_PATH, None) or {}
        cf9 = _read(common.CONFIG_PATH, None) or {}
        auto9 = bool(((cf9.get("chain_sweep") or {}) if isinstance(cf9, dict) else {}).get("auto_enable") is True)
        fs = [_cs9.refresh_reason(f, (sp9.get("chains") or {}) if isinstance(sp9, dict) else {}, auto9) for f in fs]
    except Exception:
        pass
    return {"checkedAt": d.get("checkedAt"), "findings": fs, "off": n_off,
            "auto": len(d.get("autoEnabled") or []), "errors": len(d.get("errors") or []), "chains": len(d.get("chains") or {})}


def _offsite_obs(cfg, st: dict = None, now: float = None) -> dict:
    o = ((cfg or {}).get("backup") or {}).get("offsite") if isinstance((cfg or {}).get("backup"), dict) else None
    if not (isinstance(o, dict) and o.get("enabled") is True):
        if isinstance(st, dict):
            st.pop("offsite_since", None)
        return None
    since = None
    if isinstance(st, dict):
        since = st.setdefault("offsite_since", float(time.time() if now is None else now))
    return {"enabled": True, "warn_h": o.get("warn_h") if isinstance(o.get("warn_h"), (int, float)) and not isinstance(o.get("warn_h"), bool) else 36,
            "since": since, "status": _read(os.path.join(common.STATE_DIR, "backups", "offsite_status.json"), None)}


def collect_inbox(st: dict, now: float):
    mem = st.setdefault("inbox", {})
    try:
        conn = sqlite3.connect(common.sqlite_ro_uri(common.DB_PATH), uri=True, timeout=2)
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


FUT_WAIT_WARN_S = 3600
FUT_WAIT_FRESH_S = 2400
FUT_FB_SHOW_S = 86400
FUT_PLACE_FRESH_S = 7200


def collect_fut_wait(now: float, path: str = None) -> list:
    d = _read(path or os.path.join(common.STATE_DIR, "exf_fut_wait.json"), None)
    if not isinstance(d, dict):
        return []
    out = []
    try:
        fresh = now - float(d.get("ts") or 0) <= FUT_WAIT_FRESH_S
    except (TypeError, ValueError):
        fresh = False
    names = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX"}
    act = "tj-exf 로그의 '선물 스냅샷' 실패(권한·IP·시간 오차) 확인 — 선물 정산 수집이 되살아나면 대사가 저절로 이어져요"
    base = {"unit": "tj-core", "action": act, "persist": 0, "resolve": 0, "notify": False, "remind": False, "kind": "futwait"}
    w = d.get("wait") if isinstance(d.get("wait"), dict) else {}
    warn_w = {}
    for ex, it in sorted(w.items()):
        if not fresh or not isinstance(it, dict) or it.get("fallback"):
            continue
        try:
            age = now - float(it.get("since") or now)
        except (TypeError, ValueError):
            continue
        if age >= FUT_WAIT_WARN_S:
            warn_w[str(ex)] = age
    fb_live = {}
    for ex, it in sorted(w.items()):
        if fresh and isinstance(it, dict) and it.get("fallback"):
            try:
                fb_live[str(ex)] = float(it.get("since") or now)
            except (TypeError, ValueError):
                continue
    fb_at = {}
    for x in [x for x in (d.get("fb") or []) if isinstance(x, dict)]:
        ex = str(x.get("ex") or "")
        try:
            at = float(x.get("at") or 0)
        except (TypeError, ValueError):
            continue
        if ex and now - at <= FUT_FB_SHOW_S:
            fb_at[ex] = max(fb_at.get(ex, 0.0), at)
    for ex in sorted(set(names) | set(w) | {str(x.get("ex") or "") for x in (d.get("fb") or []) if isinstance(x, dict)} - {""}):
        nm = names.get(ex, ex)
        if ex in warn_w:
            out.append(dict(base, cid=f"futwait:{ex}", title=f"선물 정산 기다리며 {nm} 대사 미룸 {fmt_ago(warn_w[ex])}", level="warn",
                            detail="선물 정산 파일이 잔고 시각을 아직 못 덮어 그 거래소 잔고 대사를 미루는 중 — 3시간 넘으면 종전 규칙으로 대사"
                                   "(그 사이 선물 정산은 지난날로 들어갈 수 있음)"))
        else:
            out.append(dict(base, cid=f"futwait:{ex}", title=f"{nm} 선물 정산 대기 없음", level="ok", detail="잔고 대사 정상 진행"))
        if ex in fb_live:
            out.append(dict(base, cid=f"futwait:fb:{ex}", title=f"{nm} 선물 정산 못 받아 종전 규칙으로 대사 중 ({fmt_ago(now - fb_live[ex])}째)", level="warn",
                            detail="선물 정산 파일이 3시간 넘게 잔고를 못 덮어 종전 규칙으로 대사하는 중 — 그 사이 선물 정산은 정산 시각이 아니라 "
                                   "지난날로 들어갈 수 있어요(원장 합·보유는 맞음 · 이중 계상 없음) · 선물 수집이 되살아나면 저절로 풀려요"))
        elif ex in fb_at:
            out.append(dict(base, cid=f"futwait:fb:{ex}", title=f"{nm} 선물 정산 못 받아 종전 규칙으로 대사 ({fmt_ago(now - fb_at[ex])} 전)", level="warn",
                            detail="선물 정산 파일이 3시간 넘게 잔고를 못 덮어 종전 규칙으로 대사 — 그 사이 선물 정산은 정산 시각이 아니라 "
                                   "지난날로 들어갔을 수 있어요(원장 합·보유는 맞음 · 이중 계상 없음)"))
        else:
            out.append(dict(base, cid=f"futwait:fb:{ex}", title=f"{nm} 선물 정산 종전 규칙 전환 없음(최근 하루)", level="ok", detail="정상"))
    try:
        pfresh = now - float(d.get("ts") or 0) <= FUT_PLACE_FRESH_S
    except (TypeError, ValueError):
        pfresh = False
    pl = d.get("place") if isinstance(d.get("place"), dict) else {}
    pbase = dict(base, kind="futplace", action="상세 사유는 tj-core 로그 '선물 정산 재배치' · 미리보기 python3 tools/exf_fut_place.py — 선물 정산 수집이 되살아나거나"
                                                " 원장 백업이 생기면 다음 대사에 저절로 옮겨요(그 전 정산은 옛 배치 그대로 · 합은 맞음)")
    for ex in sorted(set(names) | {str(k) for k in pl}):
        nm = names.get(ex, ex)
        it = pl.get(ex) if pfresh and isinstance(pl.get(ex), dict) else None
        if it:
            out.append(dict(pbase, cid=f"futplace:{ex}", title=f"선물 재배치 대기: {nm} — {str(it.get('why') or '사유 모름')[:120]}", level="warn",
                            detail="지난 대사가 지난날로 보낸 선물 정산을 정산 시각으로 다시 놓는 1회 작업을 이 거래소만 미뤘어요(다른 거래소는 옮김)"))
        else:
            out.append(dict(pbase, cid=f"futplace:{ex}", title=f"{nm} 선물 재배치 대기 없음", level="ok", detail="정상"))
    return out


SNAP_MISS_SHOW_S = 7200


def collect_snap_miss(now: float, path: str = None) -> list:
    d = _read(path or os.path.join(common.STATE_DIR, "exf_snap_miss.json"), None)
    if not isinstance(d, dict) or not isinstance(d.get("ex"), dict):
        return []
    names = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX", "kucoin": "쿠코인", "gate": "게이트", "bithumb": "빗썸", "hyperliquid": "하이퍼리퀴드"}
    base = {"unit": "tj-exf", "persist": 0, "resolve": 0, "notify": False, "remind": False, "kind": "snapmiss",
            "action": "보통 선물·봇 거래가 잦아 10분마다 잔고가 움직이는 계정 — 할 일 없음(총자산이 최대 1시간 늦게 따라와요). 거래가 없는데 이어지면 tj-exf 로그 '잔고 표본 불일치' 확인"}
    out = []
    for ex in sorted({str(k) for k in d["ex"]} | {str(x) for x in (d.get("seen") if isinstance(d.get("seen"), list) else [])}):
        it = d["ex"].get(ex)
        nm = names.get(ex, ex)
        try:
            live = isinstance(it, dict) and it.get("forced") and now - float(it.get("at") or 0) <= SNAP_MISS_SHOW_S
        except (TypeError, ValueError):
            live = False
        if live:
            out.append(dict(base, cid=f"snapmiss:{ex}", title=f"잔고 표본 계속 다름: {nm} {str(it.get('why') or '').split(' ')[0]}", level="warn",
                            detail=f"10분마다 받는 잔고 표본이 {int(it.get('n') or 0)}주기째 서로 달라({str(it.get('why') or '')[:60]}) 일치 확인 없이"
                                   f" 약 1시간마다 반영 중 — 마지막 반영 {fmt_ts(float(it['forced']))}"))
        else:
            out.append(dict(base, cid=f"snapmiss:{ex}", title=f"{nm} 잔고 표본 일치", level="ok", detail="정상"))
    return out


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
    for fn in ("pending_dm.jsonl", "alerts_web.jsonl", "alerts_fast.jsonl"):
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
    tn = h.get("tunnel") if isinstance(h.get("tunnel"), dict) else {}
    unit = tn.get("unit") or ""
    if not unit or (pm2 is not None and unit not in pm2):
        return None
    url = tn.get("ready_url") or ""
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


def collect_keys(cfg: dict, now: float = None) -> dict:
    try:
        import settings_store
        return {"evm": settings_store.needs_etherscan(cfg or {}), "etherscan": bool(settings_store.env_value("TJ_ETHERSCAN_KEY")),
                "alchemyNeed": settings_store.needs_alchemy(cfg or {}), "alchemy": bool(settings_store.env_value("TJ_ALCHEMY_KEY")),
                "ankrNeed": settings_store.needs_ankr(cfg or {}), "ankr": bool(settings_store.env_value("TJ_ANKR_KEY")),
                "heliusNeed": settings_store.needs_helius(cfg or {}), "helius": bool(settings_store.env_value("TJ_HELIUS_KEY"))}
    except Exception:
        return {}


def awake_age(now: float, base, sleeps) -> float:
    if base is None:
        return None
    age = now - base
    for a, b in sleeps or ():
        lo, hi = max(a, base), min(b, now)
        if hi > lo:
            age -= hi - lo
    return max(0.0, age)


def _liq_blind_checks(add, st9: dict, now: float) -> None:
    for sec9 in ("venues", "risk"):
        for k9, v9 in ((st9.get(sec9) if isinstance(st9.get(sec9), dict) else {}) or {}).items():
            if not isinstance(v9, dict) or "bl" not in v9:
                continue
            try:
                bl9 = int(v9.get("bl") or 0)
                since9 = float(v9.get("since") or 0) or None
            except (TypeError, ValueError):
                continue
            where9 = str(v9.get("where") or k9)[:60]
            lvl9 = "crit" if bl9 >= 2 else "warn" if bl9 == 1 else "ok"
            if lvl9 == "ok":
                add(f"liq:see:{k9}", "tj-exf", f"청산 감시 · {where9}", "ok", "정상", "", persist=0, resolve=60, notify=False, remind=False, kind="liqblind")
                continue
            if v9.get("read"):
                last9 = f"마지막 정상 {fmt_ts(since9)}({fmt_ago(now - since9)} 전)" if since9 else "마지막 정상 —"
            elif v9.get("prev_read"):
                last9 = f"마지막 정상 {fmt_ts(v9['prev_read'])}(재시작 전) · 재시작 뒤 한 번도 못 읽음"
            else:
                last9 = "감시 시작 뒤 한 번도 못 읽음"
            why9 = {"perm": "API 키 권한 오류", "net": "연결 실패·시간 초과", "rl": "거래소 호출 한도"}.get(v9.get("kind"), "")
            if v9.get("ok") is not False:
                why9 = "조회 대기(호출 한도·쉼)"
            det9 = (f"{last9} · 마지막으로 본 위험도: {str(v9.get('worst') or '—')[:120]}"
                    + (f" · 원인: {why9}" if why9 else "") + (f"({str(v9.get('err'))[:80]})" if v9.get("err") else ""))
            if bl9 == 1:
                title9, det9 = f"청산 감시가 {where9} 못 봄", det9 + " · 열린 포지션·대출은 없어요 — 새로 열면 발견이 늦어요"
            else:
                title9 = f"청산 감시가 {where9} 못 봄" + (" — 마지막에 위험 구간" if bl9 >= 3 else "")
            add(f"liq:see:{k9}", "tj-exf", title9, lvl9, det9,
                "거래소(앱·웹)에서 포지션·대출을 직접 확인 · 권한 오류면 API 키·IP 허용 목록 확인(설정 › 거래소 키) — 텔레그램은 청산 감시가 직접 보내요",
                since=since9, persist=0, resolve=60, notify=False, remind=False, kind="liqblind")


RUNNER_KEYS = ("web", "core", "evm", "sol", "bsc", "ex", "exf", "alert")
RUNNER_STALE_SEC = 180
PM2LESS_NO_OK_SEC = 600
PM2LESS_ALL_SEC = 300


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except (PermissionError, OSError, TypeError, ValueError):
        return True


def runner_alive(rec, now: float):
    if not isinstance(rec, dict) or rec.get("by") == "reload":
        return None
    try:
        age = now - float(rec.get("ts"))
    except (TypeError, ValueError):
        return None
    pid = rec.get("pid")
    alive_pid = _pid_alive(pid) if pid else True
    if age > RUNNER_STALE_SEC:
        return False, f"마지막 기록 {fmt_ago(age)} 전" + (" · 프로세스는 있음(멈춤)" if pid and alive_pid else " · 프로세스 없음")
    if not alive_pid:
        return False, f"기록 {fmt_ago(age)} 전 · 그 프로세스(pid {pid})가 없음"
    why = str(rec.get("why") or "")
    return True, ("대기: " + why[:80] if rec.get("state") == "waiting" and why else "실행 중") + f" · 기록 {fmt_ago(max(0.0, age))} 전 (pm2 없음 — 러너 기록)"


def ledger_wait_item(rc, now: float, db_path: str = None):
    if not isinstance(rc, dict) or rc.get("state") != "waiting" or rc.get("by") == "reload":
        return None
    try:
        if not now - float(rc.get("ts")) < 600:
            return None
    except (TypeError, ValueError):
        return None
    why = str(rc.get("why") or "")
    dbp = db_path or common.DB_PATH
    ev = " · ".join(str(x) for x in (rc.get("evidence") or [])[:4])
    try:
        since = int(float(rc.get("since") or rc.get("ts")))
    except (TypeError, ValueError):
        since = None
    if why.startswith("원장 파일 없음") and not os.path.exists(dbp):
        return {"id": "ledger:missing", "kind": "missing", "title": "원장 파일 없음 — 복구 필요", "since": since,
                "detail": "예전 원장 흔적: " + ev + " — 빈 원장을 만들지 않고 기다리는 중(수집은 인박스에 쌓임)",
                "action": "python3 tools/ledger_restore.py list → restore <번호>(미리보기) → --apply · 정말 새로 시작이면 tools/ledger_restore.py new --apply"}
    if why.startswith("원장이 이 코드보다 새") and os.path.exists(dbp):
        return {"id": "ledger:newer", "kind": "newer", "title": "원장이 코드보다 새 판 — 코드 업데이트 필요", "since": since,
                "detail": why[:300] + " — core 를 띄우지 않고 기다리는 중(수집은 인박스에 쌓임)",
                "action": "README '업데이트' 절대로 코드를 최신으로(git pull → bash tools/setup.sh → 재시작) · 옛 코드를 써야 하면 python3 tools/ledger_restore.py list"}
    if why.startswith("원장 손상") and os.path.exists(dbp):
        return {"id": "ledger:corrupt", "kind": "corrupt", "title": "원장 손상 — 복구 필요", "since": since,
                "detail": "검사 결과: " + (ev or "?") + " — 원장을 열지 않고 기다리는 중(수집은 인박스에 쌓임 · 되돌리면 지금 원장은 보존본으로 남음)",
                "action": "python3 tools/ledger_restore.py list → restore <번호>(미리보기) → 유닛 정지 → --apply → pm2 start tj-core"}
    return None


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
            ra = runner_alive((obs.get("runner") or {}).get(u[3:] if u.startswith("tj-") else u), now)
            if ra is None:
                if u in (h.get("optional_units") or ()):
                    continue
                add(f"proc:{u}", u, "프로세스 상태", None, "pm2 확인 불가 · 러너 기록 없음")
                continue
            if ra[0]:
                add(f"proc:{u}", u, "프로세스 상태", "ok", ra[1], persist=t["proc_persist"], resolve=60, kind="proc")
            else:
                down_units.add(u)
                src9 = {"tj-ex": "upbit_link.py", "tj-exf": "ex_foreign.py", "tj-alert": "alert_bot.py"}.get(u)
                add(f"proc:{u}", u, "프로세스 중지", "crit", ra[1] + " (pm2 없음 — 러너 기록)",
                    f"그 유닛을 다시 켜세요: python3 src/{src9 or 'unit_runner.py ' + u[3:]} — 켠 터미널의 마지막 출력에서 원인 확인",
                    persist=t["proc_persist"], resolve=60, kind="proc")
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
            "이 컴퓨터의 인터넷 연결(와이파이·VPN) 확인 — 복구되면 수집기는 자동으로 따라잡습니다",
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
        if pm2 is None and lvl == "ok" and not s["last_success"] and s["kind"] in ("chain", "upbit") and age is not None and age >= PM2LESS_NO_OK_SEC:
            add(cid, s["unit"], f"{s['label']} 시작 뒤 성공 없음", "warn",
                f"관측 {fmt_ago(real)}째 성공 기록 없음" + (f" · 최근 오류: {str(s['err'])[:120]}" if s.get("err") else ""),
                ACTIONS[s["kind"]].format(unit=s["unit"]) + " (pm2 없이 돌리면 그 유닛을 켠 터미널의 출력)", since=s["first_seen"], persist=120, kind=s["kind"])
            checks[-1].update(age=real, age_eff=age, label=s["label"])
            continue
        partial_ok = lvl == "ok" and s.get("partial")
        if partial_ok:
            lvl = "warn"
            ttl = f"{s['label']} 부분 동기화"
        elif lvl == "ok":
            ttl = f"{s['label']} 동기화" if s["kind"] in ("chain", "upbit", "exchange") else s["label"]
            if s.get("uncollected"):
                ttl += " · 옛 구간 미수집"
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
    if pm2 is None:
        fast9 = [s for s in (obs.get("sources") or []) if s.get("kind") in ("chain", "upbit") and not s.get("new_chain")]
        if fast9 and all(now - float(s.get("first_seen") or now) >= PM2LESS_ALL_SEC for s in fast9):
            stale9 = [s for s in fast9 if not s.get("last_success") or now - float(s["last_success"]) >= PM2LESS_ALL_SEC]
            bad9 = len(stale9) == len(fast9)
            add("collect:all", "system", "모든 수집기 5분째 성공 없음" if bad9 else "수집기 성공", "warn" if bad9 else "ok",
                (f"{len(fast9)}곳(" + ", ".join(str(s.get('label')) for s in fast9[:6]) + (" …" if len(fast9) > 6 else "") + ") 모두 5분 넘게 성공 없음")
                if bad9 else f"{len(fast9) - len(stale9)}/{len(fast9)}곳 5분 안 성공",
                "인터넷 연결·키를 확인하고, pm2 없이 돌리면 각 수집기를 켠 터미널의 출력을 보세요" if bad9 else "",
                persist=0, resolve=120, kind="chain")
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
        try:
            cap9 = float(ssrc.get("helius_daycap_until") or 0)
        except (TypeError, ValueError):
            cap9 = 0.0
        ours9 = cap9 > now
        cont9 = ours9 and bool(ssrc.get("helius_continue"))
        quota = ours9 or (ssrc.get("primary") == "open" and (le.get("kind") == "quota" or "max usage" in str(le.get("msg") or "").lower()
                                                            or int(ssrc.get("rl_429_total") or 0) > 0))
        via = ssrc.get("current_source") or "공개 RPC"
        hh9 = time.strftime('%H:%M', time.localtime(cap9)) if cap9 else ""
        add("quota:helius", "tj-sol", ("Helius 하루 예산 소진 · 공개 노드로 계속" if cont9 else "Helius 하루 예산 소진 · 수집 쉼" if ours9
                                       else "Helius 한도 소진 · 공개 RPC 사용 중") if quota else "Helius",
            "warn" if quota else "ok",
            (f"우리 하루 예산(Helius 월 크레딧의 80% ÷ 30)을 다 써서 {hh9} 까지 새 거래 확인은 공개 노드({ssrc.get('head_rpc') or 'publicnode'})로, 옛 기록은 아카이브 공개 노드로 이어 받아요"
             " — 처음 넣은 지갑의 첫 백필·닫힌 토큰 계정 정리는 그때까지 미뤄요" if cont9 else
             f"우리 하루 예산(Helius 월 크레딧의 80% ÷ 30)을 다 써서 {hh9} 까지 솔라나 수집을 쉬어요(기록은 그대로 · 풀리면 이어 받음)"
             if ours9 else f"주 RPC(Helius) 크레딧 소진 — 30분마다 재확인, 지금은 {via} 로 동기화 중" if quota else "주 RPC 정상"),
            (f"{hh9}에 Helius 가 저절로 다시 쓰여요 — 그때 미룬 일을 이어 받아요(더 넉넉히 쓰려면 Helius 플랜을 올리고 설정의 월 크레딧을 바꾸세요)" if cont9 else
             f"{hh9}에 수집이 저절로 다시 시작돼요 — 쉬는 동안 빠진 기록은 그때 이어 받아요(더 자주 받으려면 Helius 플랜을 올리고 설정의 월 크레딧을 바꾸세요)"
             if ours9 else "Helius 플랜·키를 바꾸거나(설정 › 연결 · 키) 그대로 두면 공개 RPC 로 계속 동기화합니다(속도만 느림)"),
            persist=0, resolve=600, notify=False, remind=False, kind="quota")
        chip("Helius 한도" if quota else None)
        if ssrc.get("head_rpc_on"):
            ou9 = ssrc.get("head_rpc_open_until")
            rate9 = ssrc.get("head_rpc_rate")
            n9 = int(ssrc.get("head_rpc_n") or 0)
            open9 = isinstance(ou9, (int, float)) and not isinstance(ou9, bool) and ou9 > now
            low9 = isinstance(rate9, (int, float)) and n9 >= 20 and rate9 < 0.9
            sick9 = open9 or low9
            host9 = ssrc.get("head_rpc") or "publicnode"
            why9 = str(ssrc.get("head_rpc_why") or "")[:120]
            add("rpc:sol_head", "tj-sol", "Solana 공개 노드 응답 이상 · 헬리우스로 대신 확인" if sick9 else "Solana 새 거래 확인 노드",
                "warn" if sick9 else "ok",
                (f"새 거래 확인용 공개 노드({host9})가 " + (f"{time.strftime('%H:%M', time.localtime(float(ou9)))}까지 쉬는 중" if open9 else
                                                       f"최근 응답 {round(float(rate9) * 100)}%({n9}회)") + (f" — {why9}" if why9 else "") +
                 " · 그동안 헬리우스로 확인해서 헬리우스 하루 몫을 더 써요(옛 기록이 늦어질 수 있음)") if sick9 else
                f"새 거래 확인 = 공개 노드({host9}) 먼저 · 백업 헬리우스" + (f" · 최근 응답 {round(float(rate9) * 100)}%" if isinstance(rate9, (int, float)) else ""),
                "저절로 다시 써요(연속 실패 = 1분부터 길게 쉼 · 대조에서 누락이 보이면 6시간) — 오래 이어지면 설정 sol.head_rpc 로 다른 노드를 지정하거나 \"\"(끔)로 헬리우스만 쓰세요",
                persist=900, resolve=600, notify=False, remind=False, kind="quota")
    kk = obs.get("keys") or {}
    if kk.get("evm") and "tj-evm" in units and "etherscan" in kk:
        have = bool(kk.get("etherscan"))
        add("key:etherscan", "tj-evm", "이더스캔 키" if have else "이더스캔 키가 필요해요(무료)", "ok" if have else "warn",
            "저장됨" if have else ("EVM 지갑이 있는데 이더스캔 키가 없어요 — 지금은 공개 탐색기·RPC 로만 받아 느리거나, 막힌 체인(Arbitrum·Polygon 등)은 "
                                  "늦게 기록될 수 있어요(기록이 사라지지는 않아요)"),
            "etherscan.io/myapikey 에서 무료 키를 받아 설정 › 연결 · 키 › Etherscan 에 넣으세요",
            persist=0, resolve=60, notify=False, remind=False, kind="key")
    if kk.get("alchemyNeed") and "alchemy" in kk and ("tj-evm" in units or "tj-bsc" in units):
        have = bool(kk.get("alchemy"))
        add("key:alchemy", "tj-evm" if "tj-evm" in units else "tj-bsc", "Alchemy 키" if have else "Alchemy 키가 필요해요(무료)", "ok" if have else "warn",
            "저장됨 — 지갑 토큰·잔고 찾기에 써요(감시·옛 기록은 무료 노드)" if have else
            ("EVM 지갑이 있는데 Alchemy 키가 없어요 — 지갑이 주고받은 토큰 전부와 지금 잔고를 한 번에 찾지 못해, 옛 보유 토큰 찾기가 약해져요"
             "(탐색기 한 곳만 — 그 탐색기가 막힌 체인은 오래 들고만 있던 토큰을 놓칠 수 있어요). 거래 수집·감시는 그대로 돌아요"),
            "dashboard.alchemy.com/signup 에서 무료 키를 받아 설정 › 연결 · 키 › Alchemy 에 넣으세요(재시작 없이 바로 써요)",
            persist=0, resolve=60, notify=False, remind=False, kind="key")
    if kk.get("ankrNeed") and "ankr" in kk and ("tj-evm" in units or "tj-bsc" in units):
        have = bool(kk.get("ankr"))
        add("key:ankr", "tj-evm" if "tj-evm" in units else "tj-bsc", "Ankr 키" if have else "Ankr 키가 필요해요(무료)", "ok" if have else "warn",
            "저장됨 — 쉬는 지갑에 들어온 토큰을 10분마다 확인하고, BSC·Base 옛 기록을 빨리 받아요(무료 한도의 80% 아래)" if have else
            ("EVM 지갑이 있는데 Ankr 키가 없어요 — 오래 안 쓴 지갑에 들어온 토큰을 무료 공개 노드로만 확인해 늦거나 빠질 수 있고(1시간 확인이 받쳐 줘요), "
             "BSC·Base 옛 기록도 공개 노드로 천천히 받아요. 거래 수집·감시는 그대로 돌아요"),
            "ankr.com/rpc 에서 무료 키(Freemium)를 받아 설정 › 연결 · 키 › Ankr 에 넣으세요",
            persist=0, resolve=60, notify=False, remind=False, kind="key")
    if kk.get("heliusNeed") and "helius" in kk and "tj-sol" in units:
        have = bool(kk.get("helius"))
        add("key:helius", "tj-sol", "Helius 키" if have else "Helius 키가 필요해요(무료)", "ok" if have else "warn",
            "저장됨 — Solana 지갑 기록을 받아요" if have else
            ("Solana 지갑이 있는데 Helius 키가 없어요 — Solana 기록 수집은 키를 넣을 때까지 기다려요(이미 받은 기록은 그대로 · "
             "넣으면 최근 거래부터 바로 받고 빠진 구간도 이어 받아요)"),
            "dashboard.helius.dev 에서 무료 키를 받아 설정 › 연결 · 키 › Helius 에 넣으세요(넣으면 약 30초 안에 Solana 수집이 저절로 시작돼요)",
            persist=0, resolve=60, notify=False, remind=False, kind="key")
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
            slow9 = stalled and fill_slow(obs, bu, key, it, now)
            if slow9:
                stalled = False
            un = bf_units.get(bu, f"tj-{bu}")
            add(f"bfstall:{bu}:{key}", un if un in units else "system", "과거 데이터 가져오기 멈춤" if stalled else "과거 데이터 가져오기",
                "warn" if stalled else "ok",
                (f"{key} — {fmt_ago(now - moved)} 동안 진행 없음" + (f" · {str(it.get('note'))[:120]}" if it.get("note") else "")
                 if stalled else (f"{key} 오늘 옛 기록 몫을 다 써서 남는 몫으로 이어 받는 중(UTC 0시에 다시 몰아서) · 새 거래 확인은 먼저 떼어 둔 몫으로 지금 주기대로"
                                  if bu in ("evm", "sol") else f"{key} 하루 한도 안에서 남는 몫으로 천천히 채우는 중(새 거래 확인 먼저)") if slow9 else f"{key} {it.get('phase')}"),
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
    pg = obs.get("pnlgate")
    if isinstance(pg, dict) and "tj-core" in units:
        rb9 = float((xr or {}).get("rebuilt_at") or 0) if isinstance(xr, dict) else 0.0
        if not pg.get("ok") and not pg.get("approved") and float(pg.get("ts") or 0) > rb9:
            act9 = ("상태 › 정리 요청 › '재계산 승인'에서 바뀐 달·포지션을 확인하고 승인(또는 python3 tools/rebuild_approve.py --yes)"
                    if pg.get("report_sha") else "보고서가 없어 승인할 수 없어요 — 다음 자동 재계산 결과로 다시 판단")
            add("rebuild:pnl", "tj-core", "재계산이 과거 손익을 바꿔 보류", "warn",
                (str(pg.get("reason") or "") + (" · " + str(pg.get("approve_note")) if pg.get("approve_note") else ""))[:300],
                act9, persist=0, resolve=600, remind=False, kind="rebuild")
        elif float(pg.get("ts") or 0) > now - 86400:
            add("rebuild:pnl", "tj-core", "재계산 손익 게이트", "ok",
                ("승인으로 통과 · " + str(pg.get("reason") or "")[:200]) if pg.get("approved") else "과거 손익 차이 임계 이내",
                persist=0, resolve=600, notify=False, remind=False, kind="rebuild")
    if "tj-core" in units:
        for c9 in collect_fut_wait(now):
            add(**c9)
    if "tj-exf" in units:
        for c9 in collect_snap_miss(now):
            add(**c9)
    di = obs.get("decis")
    if isinstance(di, dict) and isinstance(di.get("items"), dict) and "tj-core" in units:
        its = [x for x in di["items"].values() if isinstance(x, dict)]
        cf = [x for x in its if x.get("kind") == "conflict"]
        pd = [x for x in its if x.get("kind") in ("pending", "resolve")]
        if cf or pd:
            det = " · ".join(f"{x.get('symbol') or '?'}({x.get('chain')}) 저장 {x.get('stored')} → 관측 {x.get('seen')}" for x in (cf or pd)[:4])
            add("ledger:decimals", "tj-core", f"토큰 자리수 다름 {len(cf)}개" if cf else f"토큰 자리수 채움 대기 {len(pd)}개",
                "warn" if cf else "ok", det[:300],
                ("다른 값은 덮지 않았어요 — 상태 › 정리 요청 › '자리수 다름'에서 확인하고 관측값으로 다시 기장 요청(또는 python3 tools/fill_decimals.py)"
                 if cf else "다음 자동 재구축에서 채워져요(수량 표시가 맞춰짐 · 손익이 바뀌면 재계산 승인 필요)"),
                persist=0, resolve=600, remind=False, kind="ledger")
    po = obs.get("poison")
    if "tj-core" in units and ((isinstance(po, dict) and int(po.get("total") or 0) > 0) or "ledger:poison" in open_ids):
        n9 = int((po or {}).get("total") or 0) if isinstance(po, dict) else 0
        parts = []
        if isinstance(po, dict) and po.get("missing_ts"):
            parts.append(f"시각 없음 {po['missing_ts']}건" + (f"(블록 시각으로 보강해 다시 보냄 {po['sent']}건 — 처리 대기)" if po.get("sent") else "")
                         + (f" · 블록 번호 없어 자동 보강 불가 {po['no_block']}건" if po.get("no_block") else ""))
        if isinstance(po, dict) and po.get("other"):
            parts.append(f"처리 오류 {po['other']}건")
        if isinstance(po, dict) and po.get("corrupt"):
            parts.append(f"손상된 줄 {po['corrupt']}건")
        if isinstance(po, dict) and po.get("oldest"):
            parts.append("가장 오래된 것 " + fmt_ts(po["oldest"]))
        add("ledger:poison", "tj-core", f"격리된 거래 기록 {n9}건" if n9 else "격리된 거래 기록",
            None if (isinstance(po, dict) and po.get("error")) else ("warn" if n9 else "ok"),
            ("집계 실패: " + str(po["error"])) if (isinstance(po, dict) and po.get("error")) else (" · ".join(parts) if n9 else "모두 처리됨"),
            "시각 없는 건은 수집기가 블록 시각을 구하는 대로 자동으로 다시 보내요 · 목록: python3 tools/replay_poison.py — 원인을 고친 뒤 --apply --all 로 다시 처리",
            persist=0, resolve=600, notify=False, remind=False, kind="ledger")
    tn = obs.get("tunnel")
    tu = ((h.get("tunnel") or {}) if isinstance(h.get("tunnel"), dict) else {}).get("unit")
    if tn is not None and tu and tu in units:
        bad = not tn.get("ok") or int(tn.get("n") or 0) < 1
        add("tunnel:ready", tu, "터널 연결 끊김" if bad else "터널", "crit" if bad else "ok",
            (f"연결 {int(tn.get('n') or 0)}개" + (f" · {tn['err']}" if tn.get("err") else "")) if bad else f"연결 {int(tn.get('n') or 0)}개",
            f"pm2 logs {tu} --lines 50 — 반복되면 pm2 restart {tu} (로컬 대시보드는 영향 없음)",
            persist=t.get("tunnel_persist", 300), kind="tunnel")
        chip("터널" + (" 끊김" if bad else ""))
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
                                       ("web:build", "tj-web", "web"), ("web:buildmode", "tj-web", "web"), ("rabby:gap", "tj-web", "rabby")):
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
            pd9 = ng.get("pend") if isinstance(ng.get("pend"), dict) else {}
            try:
                p_n9, p_usd9 = int(pd9.get("n") or 0), float(pd9.get("usd") or 0)
            except (TypeError, ValueError):
                p_n9, p_usd9 = 0, 0.0
            all_pd9 = bad and p_n9 > 0 and p_n9 >= n_neg9
            top = " · ".join(f"{x.get('sym')} {loc_ko(x.get('loc'))} ${abs(float(x.get('usd') or 0)):,.0f}"
                             + ("(재계산 대기)" if x.get("pend") and not all_pd9 else "") for x in top9[:3])
            ph9 = bf_ext_phrase(obs.get("bf"), now) if bad and p_n9 > 0 else ""
            first9 = False
            if all_pd9:
                det9 = (f"{n_neg9}곳(거래소 차입 몫 제외 — 총자산에서 차감됨) · {top} — 재계산 대기: 과거 기록을 늦게 받은 옛 거래가 이미 맞춰 둔 기초잔고와 겹친 일시 음수"
                        " (그동안 같은 거래의 다른 쪽 — 내 다른 지갑 — 이 그만큼 많게 보일 수 있음) · "
                        + (f"{ph9}가 끝나면 원장 자동 재계산이 다시 맞춤 — 기다리면 됨" if ph9 else "과거 기록 범위 넓히기가 끝나면 원장 자동 재계산이 다시 맞춤"))
                act9 = ((f"기다리면 됨 — {ph9}가 끝나면 원장 자동 재계산이 다시 맞춤 · " if ph9 else "")
                        + "과거 기록 넓히기·재계산이 끝날 때까지 기다린 뒤에도 남으면 빠진 입금·지갑 등록을 점검 — 진행은 설정 › 과거 데이터 더 가져오기")
            elif not os.path.exists(os.path.join(common.STATE_DIR, "backfill_done")):
                first9 = True
                det9 = (f"{n_neg9}곳(거래소 차입 몫 제외 — 총자산에서 차감됨) · {top} — 첫 백필 중: 기초잔고 대사(창 이전 보유 맞추기) 전이라 판 코인이 음수로 보일 수 있음"
                        " · 체인·거래소별 첫 수집이 끝나 대사가 되면 자동으로 맞춰짐")
                act9 = "기다리면 됨 — 진행은 화면 위 상태 칩 '과거 N%' · 대사가 끝난 뒤에도 남으면 빠진 입금·지갑 등록·거래소 이력 기간을 점검"
            else:
                det9 = (f"{n_neg9}곳(거래소 차입 몫 제외 — 총자산에서 차감됨) · {top} — 보유량은 0 으로 보이지만 원장 결손(누락 입금·원가 이관) 신호"
                        + (f" · 그중 {p_n9}곳 ${abs(p_usd9):,.0f} 은 재계산 대기(늦게 받은 옛 거래 — "
                           + (f"{ph9}가 끝나면 " if ph9 else "") + "자동 재계산이 다시 맞춤)" if p_n9 > 0 else ""))
                act9 = "대시보드 보유 목록의 음수 위치 확인 — 빠진 입금·지갑 등록·거래소 이력 기간을 점검"
            add("ledger:neg", "tj-core", (f"원장 음수 보유 ${abs(nusd):,.0f}" + (" · 재계산 대기" if all_pd9 else " · 첫 백필 중" if first9 else "")) if bad else "원장 음수 보유",
                "warn" if bad else "ok",
                det9 if bad else "없음(거래소 차입 몫은 총자산에서 차감됨)",
                act9,
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
    bpm9 = build_mode_view(wd.get("build_proc") if isinstance(wd, dict) and now - float(wd.get("ts") or 0) < 1800 else None, now)
    if isinstance(bd, dict) and "tj-web" in units and int(bd.get("n") or 0) >= 5:
        p95 = float(bd.get("p95") or 0) / 1000
        thr_u9 = t.get("build_p95_warn_s")
        fork9 = bool(bpm9 and bpm9.get("fork"))
        if thr_u9:
            thr9, thr_lab9 = float(thr_u9), "설정"
        else:
            thr9, thr_lab9 = (60.0, "별도 프로세스") if fork9 else (10.0, "웹 안")
        slow = p95 > thr9
        add("web:build", "tj-web", f"웹 빌드 느림 p95 {p95:.1f}초" if slow else "웹 빌드", "warn" if slow else "ok",
            f"최근 {int(bd.get('n') or 0)}회 · 중앙 {float(bd.get('p50') or 0) / 1000:.1f}초 · p95 {p95:.1f}초 · 마지막 {float(bd.get('last_ms') or 0) / 1000:.1f}초"
            + f" · 문턱 {thr9:g}초({thr_lab9})"
            + (f" · 재시작 직후 첫 빌드 {float(bd['cold_ms']) / 1000:.1f}초는 표본 제외" if isinstance(bd.get("cold_ms"), (int, float)) else "")
            + build_ex_text(wd.get("build_ex"), now)
            + (f" · {bpm9['chip']}" if bpm9 else ""),
            "보유·기록 규모 증가 또는 원장 잠금(백업·재구축) 확인 — 웹 서버(tj-web) 로그의 '빌드 N초' 줄",
            persist=900, resolve=600, notify=False, remind=False, kind="web")
    if bpm9 and "tj-web" in units:
        add("web:buildmode", "tj-web", bpm9["title"], bpm9["level"], bpm9["detail"],
            "웹 서버(tj-web) 로그의 '빌드 자식 실패' 줄 — 쉼이 끝나면 저절로 별도 프로세스로 돌아감(재시작해도 바로 돌아감)" if bpm9["level"] == "warn" else "",
            persist=600, resolve=300, notify=False, remind=False, kind="web")
        chip(bpm9["chip"])
    for u9 in ("web", "core", "evm", "sol", "bsc"):
        rb9 = (obs.get("runner") or {}).get(u9)
        mem9 = rb9.get("mem") if isinstance(rb9, dict) and isinstance(rb9.get("mem"), dict) else None
        if mem9 is None or f"tj-{u9}" not in units or not (isinstance(rb9.get("ts"), (int, float)) and now - float(rb9["ts"]) < 1800):
            continue
        rs9 = [x for x in (mem9.get("restarts") or []) if isinstance(x, (int, float)) and 0 <= now - float(x) < 86400]
        cap9, cur9 = mem9.get("max_mb"), mem9.get("rss_mb")
        last9 = mem9.get("last") if isinstance(mem9.get("last"), dict) else {}
        cur_t9 = (f"지금 {int(cur9):,}MB" if isinstance(cur9, (int, float)) else "지금 값 모름") + (f" · 상한 {int(cap9):,}MB" if cap9 else " · 상한 꺼짐")
        if not rs9 and not cap9:
            continue
        if rs9:
            lt9 = datetime.fromtimestamp(float(last9.get("ts") or rs9[-1]), KST).strftime("%m-%d %H:%M")
            det9 = (f"최근 24시간 {len(rs9)}번 · 마지막 {lt9}(RSS {int(last9.get('rss_mb') or 0):,}MB > 상한 {int(last9.get('max_mb') or 0):,}MB) · " + cur_t9)
        else:
            det9 = cur_t9
        add(f"runner:mem:{u9}", f"tj-{u9}", f"메모리 상한 넘어 다시 시작 {len(rs9)}번(24시간)" if rs9 else "메모리 상한", "warn" if rs9 else "ok", det9,
            f"tj-{u9} 메모리가 상한을 넘어 정상 종료 뒤 다시 시작했어요(데이터 손실 없음) — 자주 반복되면 로그의 '메모리 상한' 줄과 보유·기록 규모 확인 ·"
            f" 상한은 환경변수 TJ_RUNNER_MAX_MB_{u9.upper()} 또는 config.json runner.max_mb.{u9}(0 = 끔)" if rs9 else "",
            persist=0, resolve=3600, notify=False, remind=False, kind="web")
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
        crit9 = age is not None and age > float(t.get("backup_crit_h") or 72) * 3600
        skip = bk.get("skip") == "disk" and now - float(bk.get("skip_at") or 0) < 86400
        if skip and age is not None and age > float(t.get("backup_disk_crit_h") or 30) * 3600:
            crit9 = True
        bad = old or skip
        if bk.get("last_ok"):
            det = f"마지막 원장 백업 {fmt_ago(age)} 전({fmt_ts(bk['last_ok'])}, {float(bk.get('size') or 0) / 1024 ** 3:.2f}GB)"
        else:
            det = f"아직 백업 없음(매일 04:30 KST 이후 — 기준 {fmt_ts(ref)})"
        if skip:
            det += (f" · 디스크 여유 부족으로 건너뜀(여유 {float(bk.get('free') or 0) / 1024 ** 3:.1f}GB < 필요 "
                    f"{float(bk.get('need') or 10 * 1024 ** 3) / 1024 ** 3:.1f}GB)")
        elif bk.get("err") and bad:
            det += f" · 최근 실패: {str(bk['err'])[:100]}"
        add("backup:age", "tj-core", ("원장 백업 못 함(디스크 부족) — 마지막 " + fmt_ago(age) + " 전" if (crit9 and skip) else
                                      f"원장 백업 {int(age // 86400)}일째 없음" if crit9 else "원장 백업 건너뜀(디스크 부족)" if skip
                                      else f"원장 백업 {fmt_ago(age)} 없음") if bad else "원장 백업",
            "crit" if crit9 else "warn" if bad else "ok", det,
            "디스크 여유 확보(옛 백업 정리) 뒤 tj-core 로그의 '원장 정기 백업' 줄 확인",
            persist=0, resolve=600, notify=crit9, remind=crit9, kind="backup")
    ob = obs.get("offsite")
    if isinstance(ob, dict) and ob.get("enabled"):
        os9 = ob.get("status") if isinstance(ob.get("status"), dict) else {}
        lok9 = float(os9.get("last_ok") or 0)
        age9 = now - lok9 if lok9 else None
        ref0 = min([float(x) for x in (ob.get("since"), os9.get("first_try")) if isinstance(x, (int, float)) and x > 0] or [0.0])
        age0 = now - ref0 if (not lok9 and ref0) else None
        warn_h9 = float(ob.get("warn_h") or 36)
        crit_o9 = (age9 is not None and age9 > max(72.0, warn_h9) * 3600) or (age0 is not None and age0 > max(72.0, warn_h9) * 3600)
        err9 = os9.get("err") if os9.get("err") and float(os9.get("err_at") or os9.get("last_try") or 0) >= lok9 else None
        bad9 = age9 is None or age9 > warn_h9 * 3600 or bool(err9)
        det9 = (f"마지막 성공 {fmt_ago(age9)} 전({fmt_ts(lok9)} · {os9.get('last_stamp') or ''} · 압축 {float(os9.get('size') or 0) / 1024 ** 3:.2f}GB"
                f" → {os9.get('dest') or '?'})" if lok9 else "아직 성공 없음")
        if err9:
            det9 += f" · 최근 실패: {str(err9)[:120]}"
        if age0 is not None:
            det9 += f" · 켠 뒤 {fmt_ago(age0)} 동안 성공 없음"
        add("offsite:age", "tj-core", (f"서버 밖 백업 {int((age9 if age9 is not None else age0) // 86400)}일째 없음" if crit_o9 else "서버 밖 백업 실패" if err9
                                      else "서버 밖 백업 아직 없음" if age9 is None else f"서버 밖 백업 {fmt_ago(age9)} 없음") if bad9 else "서버 밖 백업",
            "crit" if crit_o9 else "warn" if bad9 else "ok", det9,
            "python3 tools/offsite_backup.py status · test(연결 확인) · run --force — 원격 키·폴더·여유 공간 확인",
            persist=0, resolve=600, notify=crit_o9, remind=crit_o9, kind="backup")
    lw9 = ledger_wait_item((obs.get("runner") or {}).get("core"), now)
    if lw9:
        add(lw9["id"], "tj-core", lw9["title"], "crit", lw9["detail"], lw9["action"], since=lw9.get("since"), persist=0, resolve=60, kind="backup")
    lw = obs.get("liqw")
    if isinstance(lw, dict) and isinstance(lw.get("status"), dict) and "tj-exf" in units and "tj-exf" not in down_units \
            and "tj-exf" not in (obs.get("intent_active") or ()):
        if lw["status"].get("on"):
            age9 = eff_age("liq:watch", float(lw.get("ts") or 0) or None)
            if age9 is not None:
                lvl9 = "crit" if age9 >= 600 else "warn" if age9 >= 120 else "ok"
                add("liq:watch", "tj-exf", "청산 빠른 감시 멈춤" if lvl9 != "ok" else "청산 빠른 감시", lvl9,
                    f"마지막 판 {fmt_ago(age9)} 전 — 그동안 선물 청산·대출·마진 위험 알림이 안 나가요" if lvl9 != "ok" else "정상(몇 초마다)",
                    "pm2 restart tj-exf — 반복되면 pm2 logs tj-exf 에서 '청산' 줄 확인", persist=0, resolve=120, kind="hb")
                if lvl9 == "ok":
                    _liq_blind_checks(add, lw["status"], now)
        else:
            add("liq:watch", "tj-exf", "청산 빠른 감시", "ok", f"꺼짐 — {str(lw['status'].get('why') or '')[:80]}", persist=0, resolve=60,
                notify=False, remind=False, kind="hb")
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
        due9, busy9 = [], []
        rb_all9, rb_n9, rbs9, rbo9 = False, 0, "", []
        mem9 = obs.get("bal_mem") if isinstance(obs.get("bal_mem"), dict) else {}
        if bc.get("items") is not None and not held_all9:
            sync_bad9 = {}
            for c9 in checks:
                cid9 = str(c9.get("id") or "")
                if cid9.startswith("sync:chain:") and c9.get("level") in ("warn", "crit"):
                    sync_bad9[cid9[len("sync:chain:"):]] = f"{c9.get('label') or cid9[11:]} 수집이 지금 정상이 아님"
                elif cid9 in ("sync:ex:upbit", "upbit:pending") and c9.get("level") not in ("ok", "off"):
                    sync_bad9["upbit"] = "업비트 수집이 지금 정상이 아님"
            bb9 = obs.get("balbusy") if isinstance(obs.get("balbusy"), dict) else {}
            live9 = set()
            unk9 = bool(bb9.get("unknown"))
            hk9 = {str(x.get("key")) for x in hred9}
            for it in ([] if unk9 else now9):
                k9 = str(it.get("key") or "")
                if k9 in hk9:
                    live9.add(k9)
                    try:
                        if k9 in mem9 and now - float(mem9[k9]) >= BAL_READY_SEC:
                            due9.append(dict(it, stuck=[]))
                    except (TypeError, ValueError):
                        pass
                    continue
                why9 = bal_busy_reasons(it, bb9, sync_bad9)
                try:
                    old9 = now - float(it.get("firstSeen") or now) >= BAL_BUSY_MAX
                except (TypeError, ValueError):
                    old9 = False
                if old9 and bal_rb_wait(why9) and bf_ext_open(obs, it.get("chain")):
                    old9 = False
                if why9 and not old9:
                    busy9.append((it, why9))
                    mem9.pop(k9, None)
                    continue
                live9.add(k9)
                try:
                    rs9 = float(mem9.get(k9) or now)
                except (TypeError, ValueError):
                    rs9 = now
                mem9[k9] = rs9 if rs9 <= now else now
                if why9 and bal_rb_wait(why9):
                    rbo9.append(it)
                if now - mem9[k9] >= BAL_READY_SEC:
                    due9.append(dict(it, stuck=why9 if why9 else [],
                                     rbw=rb_wait_sentence(obs.get("bf"), now) if bal_rb_wait(why9) else None))
            for k9 in ([] if unk9 else [k for k in mem9 if k not in live9 and k not in {str(x.get("key")) for x in hred9}]):
                del mem9[k9]
            if busy9:
                det += (" / " if det else "") + "진행 중이라 알림 보류: " + " · ".join(
                    f"{CHAIN_NAME.get(it.get('chain'), it.get('chain'))} {_short_addr(it.get('wallet'))} {it.get('sym')}({why9[0]})" for it, why9 in busy9[:4]) \
                    + (f" 외 {len(busy9) - 4}건" if len(busy9) > 4 else "")
            wait9 = [it for it in now9 if str(it.get("key")) in live9 and not any(str(it.get("key")) == str(d.get("key")) for d in due9)
                     and not any(it is x for x in rbo9)]
            if wait9:
                det += (" / " if det else "") + f"진행 중인 일 없음 · 24시간 지켜보는 중 {len(wait9)}건"
            rbh9 = [it for it, why9 in busy9 if bal_rb_wait(why9)]
            if (rbh9 or rbo9) and now9:
                rbs9 = rb_wait_sentence(obs.get("bf"), now)
                if len(rbh9) == len(now9):
                    lvl, crit9, rb_all9 = "warn", False, True
                    ttl = f"원장·온체인 잔고 불일치 {len(now9)}건 · 재계산 대기" + (f" · 외부 지연 대기 {len(late9)}건" if late9 else "")
                    det = rbs9 + " / " + ("재계산 대기: " + det[len("확인 필요: "):] if det.startswith("확인 필요: ") else det)
                else:
                    rb_n9 = len(rbh9) + len(rbo9)
                    det += (f" / 그중 {rb_n9}건은 재계산 대기 — {rbs9}"
                            + (f" ({len(rbo9)}건은 처음 본 지 3일 넘어 24시간 지켜보는 중)" if rbo9 else ""))
        add("balcheck:mismatch", "tj-web", ttl, lvl, det,
            (rbs9 + " · 재계산이 끝난 뒤에도 남으면 미매칭 › 잔고 대사에서 확인") if rb_all9
            else ("대시보드 미매칭 › 잔고 대사에서 확인 (원장은 자동 보정하지 않음)"
                  + (f" · 그중 재계산 대기 {rb_n9}건은 기다리면 됨(원장 자동 재계산이 고침)" if rb_n9 else "")) if lvl == "crit"
            else "외부 탐색기(블록스카웃)가 복구되면 다음 대조에서 저절로 맞춰져요 — 복구 뒤에도 남으면 미매칭 › 잔고 대사에서 확인",
            persist=0, notify=crit9 and bool(due9), remind=False, kind="balcheck")
        checks[-1]["bal_v"] = 2
        if crit9 and bc.get("items") is not None:
            checks[-1]["crit_keys"] = sorted({str(x.get("key")) for x in now9 if x.get("key")})
            checks[-1]["keys"] = sorted({str(x.get("key")) for x in due9 if x.get("key")})
            checks[-1]["tg_items"] = [{k: x.get(k) for k in ("key", "chain", "wallet", "sym", "ledger", "onchain", "diffUsd", "stuck", "rbw")} for x in due9]
        if held_all9:
            checks[-1]["level"] = None
        chip(f"잔고 재계산 대기 {len(now9)}" if rb_all9 else
             ("잔고 지연 대기 " if lvl == "warn" else "잔고 불일치 ") + str(bc["confirmed"] if lvl != "crit" or bc.get("items") is None else len(now9))
             if bc["confirmed"] else "잔고 대조 일치")
        iv = 3600
        age = eff_age("balcheck:stale", float(bc.get("checkedAt") or 0) or None)
        if age is not None:
            lvl = "warn" if age >= t["balcheck_stale_x"] * iv else "ok"
            add("balcheck:stale", "tj-web", "잔고 대조 멈춤" if lvl != "ok" else "잔고 대조 주기", lvl,
                f"마지막 대조 {fmt_ago(now - float(bc['checkedAt']))} 전", "pm2 logs tj-web 에서 '온체인 잔고 대조' 확인",
                persist=0, kind="balcheck")
        ds9 = bc.get("disc")
        if isinstance(ds9, dict):
            fp9, no9 = int(ds9.get("failPairs") or 0), list(ds9.get("noOld") or [])
            hd9 = int(ds9.get("hold") or 0)
            lvl9 = "warn" if fp9 or hd9 else "ok"
            det9 = (f"찾은 쌍 {int(ds9.get('done') or 0)}/{int(ds9.get('pairs') or 0)}"
                    + (f" · 발견 실패 {fp9}쌍(" + ", ".join(f"{k} {v}" for k, v in sorted((ds9.get('failBy') or {}).items())) + ")" if fp9 else "")
                    + (f" · 스팸 의심으로 기초 잔고에 안 넣은 토큰 {int(ds9.get('skip') or 0)}" if ds9.get("skip") else "")
                    + (f" · 판정 대기 토큰 {hd9}(시세 판정 출처 장애 — 다음 대조에 다시)" if hd9 else "")
                    + (" · 이 체인은 옛 보유 확인 불가: " + ", ".join(no9) if no9 else ""))
            add("balcheck:disc", "tj-web", f"토큰 발견 실패 {fp9}쌍" if fp9 else (f"토큰 판정 대기 {hd9}" if hd9 else "토큰 발견"), lvl9, det9,
                "발견 실패는 다음 대조(1시간)에 다시 · 한도면 다음 날(UTC) · '옛 보유 확인 불가' 체인은 설정 › 노드 키에 Alchemy·Ankr 무료 키를 넣으면 풀려요",
                persist=0, notify=False, remind=False, kind="balcheck")
    cs = obs.get("chainsweep")
    if cs is not None:
        import chainsweep as _cs9
        fs = cs.get("findings") or []
        lvl = "warn" if fs else "ok"
        usd9 = sum(float(f.get("usd") or 0) for f in fs)
        add("chainsweep:untracked", "tj-web",
            (f"미추적 체인에 잔고/활동 {len(fs)}건" + (f" (≈${usd9:,.0f})" if usd9 else "")) if fs else "미추적 체인 점검",
            lvl, (" / ".join(_cs9.finding_text(f) for f in fs[:6]) + (f" 외 {len(fs) - 6}건" if len(fs) > 6 else "")
                  if fs else f"체인 {cs.get('chains')}개 점검 — 발견 없음" + (f" · 활동 게이트 자동 추적 {cs['auto']}쌍" if cs.get("auto") else "")
                  + (f" · 조회 실패 {cs['errors']}개 체인" if cs.get("errors") else ""))
            + (f" · 끈 체인 {cs['off']}건(설정에서 끈 체인 — 알림 없음)" if cs.get("off") else ""),
            "필요한 체인이면 설정 › 지갑 추가에서 같은 주소에 그 체인을 골라 등록하세요(자동 켜기 chain_sweep.auto_enable 을 켠 설치는 속도 측정 뒤 저절로 켜져요) · "
            "필요 없는 체인·지갑이면 무시 목록(설정 파일 chain_sweep.ignore)에 넣어 경고에서 뺄 수 있어요",
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
    rl = obs.get("reload")
    if isinstance(rl, dict) and rl.get("level") in ("warn", "ok"):
        try:
            rl_fresh = now - float(rl.get("ts") or 0) < 6 * 3600
        except (TypeError, ValueError):
            rl_fresh = False
        lvl = "warn" if rl.get("level") == "warn" and rl_fresh else "ok"
        add("reload:wallet", "system", "지갑 등록 뒤 자동 재시작 실패" if lvl != "ok" else "지갑 등록 자동 재시작", lvl,
            f"연속 {int(rl.get('fails') or 0)}회 실패" + (f" · {rl.get('error')}" if rl.get("error") and lvl != "ok" else ""),
            "pm2 logs tj-reload --lines 50 — 새 지갑은 수동 재시작(pm2 restart tj-evm tj-sol tj-bsc tj-core tj-web)으로도 반영돼요",
            kind="reload")
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
    grp9 = {}
    for c in checks:
        if alert_cat(c) == "stall" and not c.get("new_chain"):
            grp9.setdefault(c["unit"], []).append(c)

    def _all_down(cs9):
        lv9 = [c["level"] for c in cs9]
        if any(x not in ("crit", None) for x in lv9):
            return "ok"
        return "crit" if all(x == "crit" for x in lv9) else None

    def _add_all(cid9, unit9, cs9, ttl9):
        lv9 = _all_down(cs9)
        if lv9 == "ok" and cid9 not in open_ids:
            return
        cs9 = sorted(cs9, key=lambda c: -float(c.get("age") or 0))
        names9 = ", ".join(f"{c.get('label') or c['title']}({fmt_ago(c['age'])})" if c.get("age") is not None else str(c.get("label") or c["title"])
                           for c in cs9[:6]) + (f" 외 {len(cs9) - 6}개" if len(cs9) > 6 else "")
        sn9 = [float(c["since"]) for c in cs9 if isinstance(c.get("since"), (int, float)) and not isinstance(c.get("since"), bool)]
        add(cid9, unit9, ttl9 if lv9 != "ok" else f"체인 {len(cs9)}개 수집", lv9,
            (f"체인 하나씩이 아니라 {len(cs9)}개가 한꺼번에 멈췄어요 — {names9}" if lv9 != "ok" else f"체인 {len(cs9)}개 중 수집되는 곳이 있어요"),
            ("pm2 logs " + unit9 + " --lines 100 — 수집기 자체·공용 키(이더스캔 등)·인터넷 연결 확인" if unit9 != "system"
             else "인터넷 연결·공용 키 확인 — 수집기마다 pm2 logs 로 멈춘 지점 확인"),
            since=(max(sn9) if sn9 and lv9 != "ok" else None), persist=120, kind="chainall")
        checks[-1]["units"] = sorted({c["unit"] for c in cs9})

    for u9 in sorted(u for u, cs9 in grp9.items() if len(cs9) >= 2):
        _add_all(f"chainall:{u9}", u9, grp9[u9], f"체인 {len(grp9[u9])}개 수집이 모두 멈춤")
    if len(grp9) >= 2:
        al9 = [c for cs9 in grp9.values() for c in cs9]
        _add_all("chainall:*", "system", al9, f"모든 체인 수집이 멈춤 · 체인 {len(al9)}개")
    dep = {"tj-web": ("price", "ex_price", "dex_price", "daily", "balcheck", "rabby"), }
    sync_bad_units = {c["unit"] for c in checks if c["id"].startswith(("sync:", "hb:")) and c["level"] in ("warn", "crit")}
    upend9 = any(c["id"] == "upbit:pending" and c["level"] in ("warn", "crit") for c in checks)
    ublock9 = any(s9.get("key") == "ex:upbit" and s9.get("pending_block") for s9 in obs.get("sources") or [])
    hb_bad9 = {c["unit"] for c in checks if c["id"].startswith("hb:") and c["level"] in ("warn", "crit")}
    allc9 = any(c["id"] == "chainall:*" and c["level"] == "crit" for c in checks)
    for c in checks:
        if c["level"] not in ("warn", "crit"):
            continue
        k = c.get("kind")
        if c["unit"] in down_units and not c["id"].startswith(("proc:", "restart:")):
            c["suppressed"] = f"{c['unit']} 중지"
        elif "tj-web" in down_units and k in dep["tj-web"]:
            c["suppressed"] = "tj-web 중지"
        elif net_bad and k in ("chain", "exchange", "upbit", "price", "ex_price", "dex_price", "stake", "errors", "tg", "tunnel", "chainall"):
            c["suppressed"] = "네트워크 끊김"
        elif k == "chainall" and set(c.get("units") or ()) & (down_units | hb_bad9):
            c["suppressed"] = "프로세스·수집 루프 점검이 담당"
        elif k == "chainall" and c["id"] != "chainall:*" and allc9:
            c["suppressed"] = "모든 체인 멈춤이 담당"
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
        hv9 = (st.get("res_hold") or {}).get(cid) if i is None and lvl in ("warn", "crit") else None
        if isinstance(hv9, dict) and isinstance(hv9.get("i"), dict):
            i = hv9["i"]
            del st["res_hold"][cid]
            i.pop("resolved", None)
            i.pop("resolved_detail", None)
            st["history"] = [x for x in (st.get("history") or []) if not (isinstance(x, dict) and x.get("id") == i.get("id"))]
            i.update(title=c["title"], detail=c["detail"], action=c["action"], level=want or lvl, notify=c["notify"], remind=c["remind"],
                     kind=c.get("kind") or i.get("kind"), flaps=int(i.get("flaps") or 0) + 1)
            inc[cid] = i
            if want == "crit" and i.get("peak") != "crit":
                i["peak"] = "crit"
                events.append(("escalate", i))
        elif i is None and want:
            i = inc[cid] = {"id": f"{cid}@{int(now)}", "check": cid, "unit": c["unit"], "title": c["title"],
                            "detail": c["detail"], "action": c["action"], "level": want, "peak": want,
                            "opened": now, "since": c.get("since") or r["bad_since"], "notify": c["notify"],
                            "remind": c["remind"], "msg_id": None, "announced": None, "last_notified": None, "kind": c.get("kind")}
            for k9 in ("keys", "tg_force", "crit_keys", "tg_items", "bal_v"):
                if c.get(k9):
                    i[k9] = c[k9]
            events.append(("open", i))
        elif i is not None:
            if c.get("kind") == "balcheck" and lvl in ("ok", "off"):
                i["notify"] = False
                for k9 in ("keys", "tg_items"):
                    i.pop(k9, None)
            if lvl in ("warn", "crit") and c.get("kind") == "balcheck" and c.get("bal_v") and not i.get("bal_v"):
                for k9 in ("announced", "queued", "soft_told", "keys_told", "dedup", "muted", "last_notified", "reminded"):
                    i.pop(k9, None)
                i["msg_id"] = None
            if lvl in ("warn", "crit"):
                i.update(title=c["title"], detail=c["detail"], action=c["action"], level=lvl)
                i.update(notify=c["notify"], remind=c["remind"], kind=c.get("kind") or i.get("kind"))
                for k9 in ("keys", "tg_force", "crit_keys", "tg_items", "bal_v"):
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


UNIT_KO = {"tj-evm": "이더리움 계열 수집", "tj-sol": "솔라나 수집", "tj-bsc": "BSC 수집", "tj-ex": "업비트 수집", "tj-exf": "해외 거래소 수집",
           "tj-core": "장부 계산", "tj-web": "화면 서버", "tj-alert": "알림", "tj-review": "AI 복기"}
_ACT_ROUTINE = "대부분 저절로 풀려요 — 한 시간 넘게 이어지면 한 번 더 알려 드릴게요(원인과 조치는 상태 패널에)."
_AUTO_KINDS = frozenset({"chain", "exchange", "upbit", "price", "ex_price", "dex_price", "net", "stake", "tunnel"})
_ACT_MANUAL = "저절로 안 풀릴 수 있어요 — 상태 패널에서 원인과 조치를 확인하세요."
_ACT_DISK = "저절로 풀리지 않아요 — 디스크 공간을 비워 주세요(오래된 백업·로그 정리). 남은 공간은 상태 패널에 있어요."
_ACT_SOFT = "따로 할 일은 없어요 — 진행은 상태 패널에서 볼 수 있어요."
_ACT_LATE = "한 시간 넘게 이어지고 있어요 — 상태 패널에서 원인과 조치를 확인하세요."
_KIND_BY_PREFIX = (("disk:", "disk"), ("net:", "net"), ("proc:", "proc"), ("restart:", "restart"), ("inbox:", "inbox"), ("hb:", "hb"),
                   ("sync:chain:", "chain"), ("sync:ex:upbit", "upbit"), ("sync:ex:", "exchange"), ("price:", "price"), ("stake:", "stake"),
                   ("tunnel", "tunnel"))


def _kind_of(i) -> str:
    k = str((i or {}).get("kind") or "")
    if k:
        return k
    c = str((i or {}).get("check") or "")
    return next((v for p, v in _KIND_BY_PREFIX if c.startswith(p)), "")


STALL_GATE_KIND = "CHAIN_STALL"
BAL_GATE_KIND = "BAL_LONG"
_GATE_OF = {"stall": STALL_GATE_KIND, "bal": BAL_GATE_KIND}
STALL_CHECK_KINDS = frozenset({"chain"})


def alert_cat(i) -> str:
    if not isinstance(i, dict):
        return "health"
    c = str(i.get("check") or i.get("id") or "")
    if c.split("@", 1)[0] == "balcheck:mismatch":
        return "bal"
    return "stall" if c.startswith("sync:") and _kind_of(i) in STALL_CHECK_KINDS else "health"


def _stall_on(now: float = None) -> bool:
    try:
        import alert_prefs as _ap9
        return bool(_ap9.effective(_ap9.load(), "stall", now))
    except Exception:
        return False


def _by_cat(lst) -> list:
    return [x for x in ([i for i in lst if alert_cat(i) == c9] for c9 in ("health", "bal", "stall")) if x]


def _noun_of(lst) -> str:
    c9 = {alert_cat(i) for i in lst or ()}
    return "체인 수집 지연" if c9 == {"stall"} else "잔고 불일치" if c9 == {"bal"} else "봇 문제"


def _soft(i) -> bool:
    return bool(i.get("tg_force")) and LEVELS.get(i.get("peak"), 0) < LEVELS["crit"]


def _txt_group(lst, now) -> str:
    acts9 = {_act(i) for i in lst}
    lines = [f"{'📋' if all(_soft(i) for i in lst) else '🔴'} {_noun_of(lst)} {len(lst)}건이 한꺼번에 생겼어요",
             acts9.pop() if len(acts9) == 1 else _ACT_MANUAL]
    return "\n".join(lines + [f"- {i['title']} · {_u(i)} ({fmt_ago(now - i['since'])}째)" for i in lst[:12]])


def _txt_remind(lst, now) -> str:
    if len(lst) == 1:
        return msg_remind(lst[0], now)
    return "\n".join([f"🔴 아직 안 풀린 {_noun_of(lst)} {len(lst)}건", _ACT_LATE] + [f"- {i['title']} ({fmt_ago(now - i['since'])}째)" for i in lst[:12]])


def _txt_resolve(lst, now) -> str:
    if len(lst) == 1:
        return msg_resolve(lst[0], now)
    return "\n".join([f"✅ {_noun_of(lst)} {len(lst)}건이 풀렸어요", "할 일은 없어요."]
                     + [f"- {i['title']} ({fmt_ago(i['resolved'] - i['since'])})" for i in lst[:12]])


def _act(i) -> str:
    if bool(i.get("tg_force")) and LEVELS.get(i.get("peak"), 0) < LEVELS["crit"]:
        return _ACT_SOFT
    k = _kind_of(i)
    if k == "disk":
        return _ACT_DISK
    return _ACT_ROUTINE if k in _AUTO_KINDS else _ACT_MANUAL


def _u(i) -> str:
    u = str(i.get("unit") or "")
    return UNIT_KO.get(u) or ("원격 접속" if u.endswith("-tunnel") else u)


_PLAIN = (("외부 탐색기(블록스카웃)", "외부 탐색기"), ("대시보드 미매칭 › 잔고 대사", "앱 › 잔고 맞추기"), ("미매칭 › 잔고 대사", "앱 › 잔고 맞추기"), ("잔고 대사", "잔고 맞추기"),
          ("원가 미상", "원가 모름"), ("원가 미확인", "원가 모름"), ("블록스카웃", "외부 탐색기"), ("blockscout", "외부 탐색기"),
          ("백필", "과거 기록 가져오기"), ("미매칭", "짝 못 찾은 거래"), ("대사", "잔고 맞추기"), ("커서·하트비트", "진행 기록"),
          ("커서", "진행 위치"), ("폴백", "대체 경로"), ("REDERIVE", "다시 계산"), ("rederive", "다시 계산"), ("자동 보정하지", "자동으로 고치지"), ("보정하지", "고치지"),
          ("보정했", "고쳤"), ("보정", "고침"), ("미정산", "확정 전"), ("정산", "마감"))
_PLAIN_SKIP = re.compile(
    r"https?://[^\s)\]]+"
    r"|`[^`\n]*`"
    r"|\b0x[0-9a-fA-F]+"
    r"|(?:[A-Za-z0-9_.~-]+/)+[A-Za-z0-9_.~-]*"
    r"|[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+(?::\d{1,5})?"
    r"|[A-Za-z0-9]*_[A-Za-z0-9_]+")


def _plain_seg(s: str) -> str:
    for a, b in _PLAIN:
        s = s.replace(a, b)
    return s


def plain_text(s) -> str:
    s = str(s or "")
    out, pos = [], 0
    for m in _PLAIN_SKIP.finditer(s):
        out.append(_plain_seg(s[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(_plain_seg(s[pos:]))
    return "".join(out)


def ext_cause(i) -> str:
    if _kind_of(i) != "chain":
        return ""
    det = str(i.get("detail") or "")
    es = "이더스캔 하루 한도" in det or "day/limit" in det.lower()
    hl = "헬리우스 하루 한도" in det
    ch = "사람 확인" in det or is_challenge(det)
    if not (es or ch or hl):
        return ""
    m9 = re.search(r"이더스캔 하루 한도 쉼 — (\d{2}:\d{2})", det)
    h9 = re.search(r"헬리우스 하루 한도 쉼 — (\d{2}:\d{2})", det)
    parts = []
    if es:
        parts.append(f"이더스캔 무료 하루 한도에 닿아 쉬는 중이에요({m9.group(1) if m9 else es_reset_text()}에 저절로 풀려요)")
    if hl:
        parts.append(f"헬리우스 하루 예산(무료 한도의 80%)에 닿아 쉬는 중이에요({h9.group(1) if h9 else '자정 무렵'}에 저절로 풀려요)")
    if ch:
        parts.append("외부 탐색기가 사람 확인 화면으로 막고 있어요(우리 쪽 문제 아님 — 저쪽이 풀면 저절로 다시 받아요)")
    return " · ".join(parts) + " — 기록은 그대로고, 풀리면 따라잡아요."


def msg_open(i, now) -> str:
    icon = "🔴" if i["peak"] == "crit" else "📋"
    det = str(i.get("detail") or "").replace("\n", " ")
    if i.get("check") == "balcheck:mismatch":
        if i.get("tg_items"):
            return bal_text(i["tg_items"])
        n9 = len(i.get("keys") or ()) or 1
        return (f"🔴 잔고가 기록과 다른 곳이 {n9}곳 있어요\n앱 › 잔고 맞추기에서 어느 지갑·코인인지 확인하세요(기록은 자동으로 고치지 않아요).\n"
                f"{fmt_ago(now - i['since'])}째 · {det[:140]}")
    return (f"{icon} {i['title']} · {_u(i)}\n{ext_cause(i) or _act(i)}\n"
            f"{fmt_ago(now - i['since'])}째 · {det[:140]}")


def msg_remind(i, now) -> str:
    return f"🔴 아직 안 풀렸어요 · {i['title']} ({fmt_ago(now - i['since'])}째)\n{_ACT_DISK if _kind_of(i) == 'disk' else _ACT_LATE}"


def msg_resolve(i, now) -> str:
    return f"✅ 풀렸어요 · {i['title']}\n할 일은 없어요.\n{fmt_ago(i['resolved'] - i['since'])} 동안 이어졌어요 · {_u(i)}"


def msg_flap(i, now) -> str:
    return (f"✅ 잠깐 멈췄다 풀렸어요 · {i['title']}\n할 일은 없어요.\n"
            f"{fmt_ts(i['since'])}~{fmt_ts(i['resolved'])} ({fmt_ago(i['resolved'] - i['since'])}) · {_u(i)}")


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
    _normalize_legacy_safe(st, now, h)
    r = _plan_raw(st, events, now, h, tg_configured)
    for o in st.get("outbox") or []:
        if isinstance(o, dict) and isinstance(o.get("text"), str):
            o["text"] = plain_text(common.redact_secret_text(o["text"], generic=False))
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

    tg_min = float(h.get("tg_min_age_sec") or 0)

    def eligible(i):
        if tg_min and now - float(i.get("since") or now) < tg_min:
            return False
        return i.get("notify", True) and (LEVELS.get(i.get("peak"), 0) >= minl or bool(i.get("tg_force")))

    def soft(i):
        return bool(i.get("tg_force")) and LEVELS.get(i.get("peak"), 0) < LEVELS["crit"]

    nb_cache = []

    def not_before():
        if not nb_cache:
            nb_cache.append(_quiet_until(now))
        return nb_cache[0]

    def put(item, soft_only, src=None):
        if src:
            _gk(item, src)
        if soft_only:
            nb9 = not_before()
            if nb9:
                item["not_before"] = nb9
        ob.append(item)

    recent_dm = _bal_dm_recent(st, now)

    def _gk(item, src):
        return _tag(item, src)

    bi9 = inc.get("balcheck:mismatch")
    if isinstance(bi9, dict):
        for o in [o for o in ob if isinstance(o, dict) and o.get("cat") == "bal" and o.get("kind") in ("open", "group", "remind")
                  and bi9.get("id") in (o.get("incs") or [])]:
            ob.remove(o)
            if o["kind"] in ("open", "group") and not bi9.get("announced"):
                for k9 in ("queued", "soft_told", "keys_told"):
                    bi9.pop(k9, None)
            elif o.get("keys"):
                bi9["keys_told"] = sorted(set(bi9.get("keys_told") or ()) - set(o["keys"]))

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
            if i.get("announced") and float(h.get("flap_hold_sec") or 0) > 0:
                st.setdefault("res_hold", {})[i["check"]] = {"i": i, "at": now}
            elif i.get("announced"):
                resolved.append(i)
            elif pend:
                for o in pend:
                    o["incs"].remove(i["id"])
                    if o["kind"] == "open" or not o["incs"]:
                        ob.remove(o)
                put({"kind": "flap", "text": msg_flap(i, now), "reply": None, "incs": [i["id"]], "created": now}, soft(i), [i])
    rh9 = st.get("res_hold") if isinstance(st.get("res_hold"), dict) else {}
    for cid9 in list(rh9):
        hv9 = rh9[cid9]
        if not isinstance(hv9, dict) or not isinstance(hv9.get("i"), dict):
            del rh9[cid9]
            continue
        r9 = (st.get("checks") or {}).get(cid9)
        if not (isinstance(r9, dict) and r9.get("last") == now and r9.get("lvl") in ("ok", "off")):
            hv9.setdefault("miss", now)
            hv9["at"] = now
            if now - float(hv9.get("miss") or now) >= float((h.get("t") or {}).get("vanish_sec", 3600)):
                del rh9[cid9]
            continue
        hv9.pop("miss", None)
        if now - float(hv9.get("at") or 0) >= float(h.get("flap_hold_sec") or 0):
            resolved.append(hv9["i"])
            del rh9[cid9]
    for rs9 in _by_cat(resolved):
        put({"kind": "resolve", "text": _txt_resolve(rs9, now), "reply": rs9[0].get("msg_id"),
             "incs": [i["id"] for i in rs9], "created": now}, all(soft(i) for i in rs9), rs9)
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
    for op9 in _by_cat(opens):
        if len(op9) >= h["group_min"]:
            put({"kind": "group", "text": _txt_group(op9, now), "reply": None, "incs": [i["id"] for i in op9],
                 "created": now}, all(soft(i) for i in op9), op9)
            for i in op9:
                i["queued"] = True
                if soft(i):
                    i["soft_told"] = True
        else:
            for i in op9:
                put({"kind": "open", "text": msg_open(i, now), "reply": None, "incs": [i["id"]], "created": now}, soft(i), [i])
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
            nit9 = [x for x in (i.get("tg_items") or []) if str(x.get("key")) in new9]
            ob.append({"kind": "remind", "text": (bal_text(nit9, more=True) if nit9 else
                                                  f"🔴 잔고가 기록과 다른 곳이 {len(new9)}곳 더 늘었어요\n앱에서 어느 지갑·코인인지 확인하세요.\n{str(i['detail'])[:140]}"),
                       "reply": i.get("msg_id"), "incs": [i["id"]], "created": now, "keys": sorted(new9)})
            _gk(ob[-1], [i])
            upd9 |= new9
        if upd9 != told9:
            i["keys_told"] = sorted(upd9)
    rh = 0.0 if float(h.get("remind_once_sec") or 0) > 0 else float(h.get("remind_hours") or 0) * 3600
    cand = [i for i in inc.values() if rh > 0 and i.get("announced") and i.get("remind", True) and eligible(i)
            and i.get("level") == "crit" and not any(o["kind"] == "remind" and i["id"] in o["incs"] for o in ob)]
    age = lambda i: now - float(i.get("last_notified") or i["announced"])
    if any(age(i) >= rh for i in cand):
        due = sorted([i for i in cand if age(i) >= rh / 2], key=lambda i: i["opened"])
        for i in due:
            if i.get("keys"):
                i["keys_told"] = sorted(set(i.get("keys_told") or ()) | set(i["keys"]))
        for dd9 in _by_cat(due):
            ob.append({"kind": "remind", "text": _txt_remind(dd9, now), "reply": dd9[0].get("msg_id"),
                       "incs": [i["id"] for i in dd9], "created": now})
            _gk(ob[-1], dd9)
    ro9 = float(h.get("remind_once_sec") or 0)
    if ro9 > 0:
        c1 = [i for i in inc.values() if i.get("announced") and not i.get("reminded") and i.get("remind", True) and eligible(i)
              and i.get("level") == "crit" and now - float(i["announced"]) >= ro9
              and not any(o["kind"] in ("open", "group", "remind") and i["id"] in o["incs"] for o in ob)]
        if c1:
            c1.sort(key=lambda i: i["opened"])
            for i in c1:
                i["reminded"] = now
                if i.get("keys"):
                    i["keys_told"] = sorted(set(i.get("keys_told") or ()) | set(i["keys"]))
            for cc9 in _by_cat(c1):
                ob.append({"kind": "remind", "once": True, "text": _txt_remind(cc9, now), "reply": cc9[0].get("msg_id"),
                           "incs": [i["id"] for i in cc9], "created": now})
                _gk(ob[-1], cc9)
    today = nk.strftime("%Y-%m-%d")
    if nk.hour >= int(h["digest_hour"]) and st.get("digest_date") != today:
        st["digest_date"] = today
        sk9 = _stall_on(now)
        opn = sorted((i for i in inc.values() if not str(i.get("id") or "").startswith(("quota:", "bfstall:", "gaps:"))
                      and (sk9 or alert_cat(i) != "stall") and alert_cat(i) != "bal"),
                     key=lambda x: (-LEVELS.get(x["level"], 0), x["opened"]))
        if opn:
            crit = [i for i in opn if i["level"] == "crit"]
            warn = [i for i in opn if i["level"] != "crit"]
            head = f"📋 {nk.strftime('%H:%M')} 상태 · 아직 안 풀린 문제 {len(opn)}건"
            body = "; ".join(f"{i['unit']} {i['title']}({fmt_ago(now - i['since'])})" for i in (crit or warn)[:6])
            tail = f" · 주의 {len(warn)}건은 대시보드" if crit and warn else ""
            ob.append({"kind": "digest", "text": f"{head}: {body}{tail}", "reply": None, "incs": [], "created": now})


_ONCE_PREFIX = ("🔴 아직 안 풀렸어요", "🔴 아직 안 풀린 봇 문제")


CAT_V = 2


def _tag(item: dict, src) -> dict:
    c9 = {alert_cat(x) for x in src or ()}
    item["cat"] = c9.pop() if len(c9) == 1 else "health"
    item["cat_v"] = CAT_V
    if item["cat"] in _GATE_OF:
        item["gk"] = _GATE_OF[item["cat"]]
    else:
        item.pop("gk", None)
    return item


_LEGACY_KINDS = ("open", "group", "remind", "resolve", "flap")


def _normalize_legacy(ob: list, by_id: dict, now: float, h: dict) -> int:
    n9 = 0
    for o in list(ob):
        if not isinstance(o, dict) or _cur_tag(o) or o.get("kind") not in _LEGACY_KINDS or not o.get("incs"):
            continue
        src9 = [by_id.get(x) for x in o["incs"]]
        if o.get("keys") and all(isinstance(x, dict) and alert_cat(x) == "bal" for x in src9):
            ob.remove(o)
            for x in src9:
                if x.get("keys_told"):
                    x["keys_told"] = sorted(set(x["keys_told"]) - set(o.get("keys") or ()))
            n9 += 1
            continue
        if not all(isinstance(x, dict) for x in src9) or o.get("keys"):
            _tag(o, src9 if all(isinstance(x, dict) for x in src9) else [])
            continue
        try:
            new9 = _rebuild_legacy(o, src9, now, h)
        except Exception as e:
            log.warning("옛 알림 대기열 항목 다시 만들기 실패(그대로 둠): %s", e)
            _tag(o, src9 if len(_by_cat(src9)) < 2 else [])
            continue
        at9 = ob.index(o)
        ob[at9:at9 + 1] = new9
        n9 += 1
    if n9:
        log.info("배포 전 알림 대기열 %d건을 사건 단위(봇 정지·체인 수집 지연)로 다시 만듦", n9)
    return n9


def _rebuild_legacy(o: dict, src9: list, now: float, h: dict) -> list:
    once9 = bool(o["once"]) if "once" in o else str(o.get("text") or "").startswith(_ONCE_PREFIX)
    new9 = []
    for part in _by_cat(src9):
        if alert_cat(part[0]) == "bal" and o["kind"] in ("open", "group", "remind"):
            if o["kind"] in ("open", "group"):
                for x in part:
                    if not x.get("announced"):
                        x.pop("queued", None)
                        x.pop("soft_told", None)
            continue
        if o["kind"] in ("open", "flap"):
            batches = [[i] for i in part]
        elif o["kind"] == "group" and len(part) < int(h.get("group_min") or 4):
            batches = [[i] for i in part]
        else:
            batches = [part]
        for b in batches:
            it = {k: v for k, v in o.items() if k not in ("text", "incs", "reply", "keys", "once", "gk", "cat", "cat_v")}
            it["incs"] = [i["id"] for i in b]
            if o["kind"] in ("open", "group") and len(b) == 1:
                it.update(kind="open", text=msg_open(b[0], now), reply=None)
            elif o["kind"] == "group":
                it.update(text=_txt_group(b, now), reply=None)
            elif o["kind"] == "remind":
                it.update(text=_txt_remind(b, now), reply=b[0].get("msg_id"), once=once9)
            else:
                r9 = [dict(i, resolved=i.get("resolved") or now) for i in b]
                it.update(text=(msg_flap(r9[0], now) if o["kind"] == "flap" else _txt_resolve(r9, now)), reply=(None if o["kind"] == "flap" else b[0].get("msg_id")))
            it["text"] = plain_text(common.redact_secret_text(it["text"], generic=False))
            new9.append(_tag(it, b))
    return new9


def _cur_tag(o: dict) -> bool:
    return "cat" in o and o.get("cat_v") == CAT_V


def _normalize_legacy_safe(st: dict, now: float, h: dict) -> int:
    try:
        ob = st.setdefault("outbox", [])
        if not any(isinstance(o, dict) and not _cur_tag(o) and o.get("incs") for o in ob):
            return 0
        by_id = {i["id"]: i for i in list((st.get("incidents") or {}).values()) + list(st.get("history") or []) if isinstance(i, dict) and i.get("id")}
        for hv9 in (st.get("res_hold") or {}).values():
            if isinstance(hv9, dict) and isinstance(hv9.get("i"), dict) and hv9["i"].get("id"):
                by_id.setdefault(hv9["i"]["id"], hv9["i"])
        return _normalize_legacy(ob, by_id, now, h)
    except Exception as e:
        log.warning("옛 알림 대기열 다시 만들기 실패(그대로 둠): %s", e)
        return 0


def deliver(st: dict, send_fn, now: float, h: dict, gate=None) -> int:
    ob = st.setdefault("outbox", [])
    sent_t = [x for x in st.get("sent_times", []) if now - x < 3600]
    n = 0
    by_id = {i["id"]: i for i in list(st.get("incidents", {}).values()) + list(st.get("history", []))}
    live_ids = {i["id"] for i in st.get("incidents", {}).values()}
    _normalize_legacy_safe(st, now, h)
    for o in list(ob):
        if now - o["created"] > 86400:
            ob.remove(o)
            if o.get("kind") in ("open", "group"):
                for iid in o.get("incs") or []:
                    i = by_id.get(iid)
                    if i is not None and iid in live_ids and not i.get("announced"):
                        i.pop("queued", None)
                        i.pop("soft_told", None)
            elif o.get("kind") == "remind":
                once9 = bool(o["once"]) if "once" in o else str(o.get("text") or "").startswith(("🔴 아직 안 풀렸어요", "🔴 아직 안 풀린 봇 문제"))
                keys9 = set(o.get("keys") or ())
                ids9 = set(o.get("incs") or [])
                held9 = [v9["i"] for v9 in (st.get("res_hold") or {}).values() if isinstance(v9, dict) and isinstance(v9.get("i"), dict)]
                for i in list(st.get("incidents", {}).values()) + list(st.get("history", [])) + held9:
                    if isinstance(i, dict) and i.get("id") in ids9:
                        if once9:
                            i.pop("reminded", None)
                        if keys9 and i.get("keys_told"):
                            i["keys_told"] = sorted(set(i["keys_told"]) - keys9)
            log.warning("헬스 알림 %s 이 24시간 넘게 발송되지 못해 버림(사건 %d건 — 열린 사건은 다시 대기열에)", o.get("kind"), len(o.get("incs") or []))
            continue
        if o.get("not_before"):
            try:
                if now < float(o["not_before"]):
                    continue
            except (TypeError, ValueError):
                pass
        gk9 = o.get("gk")
        if gate is not None:
            try:
                go = bool(gate(gk9 or o["kind"], o["text"]))
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
                        if gk9:
                            i["muted"] = True
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
            i.pop("muted", None)
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


def _inc_view(i, now, stall_on=True):
    tg9 = bool(i.get("notify", True)) and not i.get("muted") and (stall_on or alert_cat(i) != "stall" or bool(i.get("announced")))
    out = {"id": i["id"], "check": i["check"], "unit": i["unit"], "title": i["title"], "detail": i["detail"],
           "action": i["action"], "level": i.get("level"), "peak": i.get("peak"), "since": i.get("since"),
           "opened": i.get("opened"), "resolved": i.get("resolved"), "notified": bool(i.get("announced")) and not i.get("muted"),
           "telegram": tg9}
    kn = known_note(i.get("check"), i.get("level"), i.get("detail"), i.get("opened") or i.get("since"), now) if not i.get("resolved") else None
    if kn:
        out["known"] = kn
    return out


def build_status(st: dict, obs: dict, checks: list, now: float, h: dict) -> dict:
    inc = st.get("incidents", {})
    sk9 = _stall_on(now) if any(alert_cat(i) == "stall" for i in list(inc.values()) + list(st.get("history") or [])) else True
    open_v = sorted((_inc_view(i, now, sk9) for i in inc.values()),
                    key=lambda x: (-LEVELS.get(x["level"], 0), -(x["opened"] or 0)))
    hist = [_inc_view(i, now, sk9) for i in reversed(st.get("history", [])) if not i.get("quiet")][:20]
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
        off9 = os.environ.get("TJ_DEMO") != "1" and not (runner_alive(_read(os.path.join(common.STATE_DIR, "runner_alert.json"), None), now) or (False,))[0]
        d = {"v": 1, "overall": "unknown", "updatedAt": None, "open": [], "resolved": [], "watching": [], "units": [],
             "note": ("감시 유닛(tj-alert)이 꺼져 있어요 — 원장·백업·수집 문제를 화면·텔레그램으로 알려 주지 못해요(켜기: pm2 start tj-alert · pm2 없이: python3 src/alert_bot.py)"
                      if off9 else "아직 상태 점검 결과가 없어요 — 감시 프로그램(tj-alert)이 첫 점검 전이에요")}
        if off9:
            d["monitorOff"] = True
        return _with_ledger_wait(d, now)
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
    return _with_ledger_wait(d, now)


def _with_ledger_wait(d: dict, now: float) -> dict:
    try:
        lw = ledger_wait_item(_read(os.path.join(common.STATE_DIR, "runner_core.json"), None), now)
    except Exception:
        lw = None
    if not lw:
        return d
    d = dict(d)
    d["ledgerWait"] = {k: lw[k] for k in ("id", "kind", "title", "detail", "action", "since")}
    if not any(isinstance(x, dict) and lw["id"] in (x.get("id"), x.get("check")) for x in d.get("open") or []):
        d["open"] = [{"id": lw["id"], "check": lw["id"], "unit": "tj-core", "title": lw["title"], "detail": lw["detail"], "action": lw["action"],
                      "level": "crit", "peak": "crit", "since": lw["since"], "opened": lw["since"], "notified": False, "telegram": False}] + list(d.get("open") or [])
    d["overall"] = "crit"
    return d


def compact(view: dict) -> dict:
    op = view.get("open") or []
    out = {"overall": view.get("overall"), "crit": sum(1 for x in op if x.get("level") == "crit"),
           "warn": sum(1 for x in op if x.get("level") != "crit"), "updatedAt": view.get("updatedAt"),
           "stale": bool(view.get("stale"))}
    if view.get("ledgerWait"):
        out["ledger"] = view["ledgerWait"]
    if view.get("monitorOff"):
        out["monitorOff"] = True
    return out


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
        self.hb_last = 0.0
        self.hb_busy = False

    def heartbeat(self, h: dict, now: float, opener=None) -> bool:
        url = h.get("heartbeat_url") or ""
        if not url or self.hb_busy or now - self.hb_last < float(h.get("heartbeat_sec") or 300):
            return False
        self.hb_last, self.hb_busy = now, True

        def _go():
            try:
                import urllib.request
                req = urllib.request.Request(url, headers={"User-Agent": "tj-bot-health/1"})
                with (opener.open if opener else urllib.request.urlopen)(req, timeout=10) as r:
                    r.read(256)
            except Exception as e:
                log.debug("헬스 하트비트 실패(%s)", type(e).__name__)
            finally:
                self.hb_busy = False
        import threading
        threading.Thread(target=_go, name="tj-health-hb", daemon=True).start()
        return True

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
                "keys": collect_keys(cfg, now),
                "restarts": {u: m.get("ev", []) for u, m in rmem.items()},
                "intent_active": intent_active,
                "logs": {u: self.logs.summary(u, now, h["t"]) for u in h["units"]},
                "sources": collect_sources(cfg, st, now),
                "bf": _read(os.path.join(common.STATE_DIR, "backfill_status.json"), {}) or {},
                "fill_paced": _fill_paced_map(cfg, now),
                "extrb": _read(os.path.join(common.STATE_DIR, "ext_rebuild_status.json"), None),
                "decis": _read(os.path.join(common.STATE_DIR, "asset_decimals_issues.json"), None),
                "poison": collect_poison(),
                "pnlgate": _read(os.path.join(common.STATE_DIR, "rebuild_pnl_gate.json"), None),
                "liqw": _read(os.path.join(common.STATE_DIR, "liq_watch.json"), None),
                "hb": read_heartbeats(cfg),
                "daily": daily, "review": review,
                "webdiag": _read(os.path.join(common.STATE_DIR, "web_diag.json"), None),
                "backup": _read(os.path.join(common.STATE_DIR, "backups", "backup_status.json"), None),
                "offsite": _offsite_obs(cfg, st, now),
                "rss": rss_track(st, pm2, now, float((h.get("t") or {}).get("rss_win") or 1800)),
                "balcheck": collect_balcheck(),
                "chainsweep": collect_chainsweep(),
                "inbox": pr["inbox"]() if "inbox" in pr else collect_inbox(st, now),
                "disk": pr["disk"]() if "disk" in pr else collect_disk(),
                "reload": _read(os.path.join(common.STATE_DIR, "health_reload.json"), None),
                "runner": {u9: _read(os.path.join(common.STATE_DIR, f"runner_{u9}.json"), None) for u9 in RUNNER_KEYS},
                "web": pr["web"]() if "web" in pr else collect_web(cfg, st, now),
                "tg": dict(TG_STATS, configured=bool(tg_configured)),
                "dm": collect_dm(st, now, bool(tg_configured))}
        obs["balbusy"] = collect_bal_busy(now, obs.get("extrb"), obs.get("bf"))
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
        obs["bal_mem"] = st.setdefault("bal_ready", {})
        obs["prev_inc"] = {k: {"level": (v or {}).get("level"), "keys": list((v or {}).get("crit_keys") or (v or {}).get("keys") or [])}
                           for k, v in (st.get("incidents") or {}).items()}
        open9 = {k: (v or {}).get("unit") for k, v in (st.get("incidents") or {}).items()}
        for cid9, hv9 in (st.get("res_hold") or {}).items():
            if isinstance(hv9, dict) and isinstance(hv9.get("i"), dict):
                open9.setdefault(cid9, hv9["i"].get("unit"))
        checks = evaluate(obs, h, open_ids=open9)
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
        self.heartbeat(h, now)
        return status
