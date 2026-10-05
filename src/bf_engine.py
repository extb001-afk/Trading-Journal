"""Backfill engine for historical wallet activity."""
from __future__ import annotations

import fcntl
import json
import os
import random
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import common

UA = "tj-bot/0.1 (personal trade journal)"


def _url_host(url) -> str:
    try:
        return urllib.parse.urlsplit(str(url)).hostname or "(주소 숨김)"
    except ValueError:
        return "(주소 숨김)"


class NetError(RuntimeError):

    def __init__(self, msg: str, kind: str, code=None, retry_after=None, cap=None, host=None):
        super().__init__(common.redact_secret_text(msg))
        self.kind = kind
        self.code = code
        self.retry_after = retry_after
        self.cap = cap
        self.host = host


class CircuitOpen(NetError):
    def __init__(self, host: str, until: float):
        super().__init__(f"circuit open {host} ({max(0.0, until - time.time()):.0f}s)", "circuit", host=host)
        self.until = until


def retry_after_sec(v):
    if not v:
        return None
    try:
        return max(0.0, float(v))
    except (TypeError, ValueError):
        pass
    try:
        from email.utils import parsedate_to_datetime
        return max(0.0, parsedate_to_datetime(v).timestamp() - time.time())
    except Exception:
        return None


_RANGE_CAP_RE = re.compile(r"(?:maximum block range|block range (?:is )?(?:too large|limit)|range)\D{0,20}(\d{2,7})",
                           re.I)


def classify_rpc_error(err) -> NetError:
    if isinstance(err, dict):
        code, msg = err.get("code"), str(err.get("message") or err)
    else:
        code, msg = None, str(err)
    low = msg.lower()
    text = f"rpc-error {code}: {msg[:160]}"
    if "header not found" in low or "missing trie node" in low or "pruned" in low \
            or "history has been pruned" in low or "block not found" in low \
            or ("historical state" in low and "not available" in low) \
            or "historical version not found" in low or "failed to load state at height" in low:
        return NetError(text, "pruned", code=code)
    if "context deadline exceeded" in low or "execution timeout" in low or "query timeout" in low \
            or "query timed out" in low:
        return NetError(text, "timeout", code=code)
    if "logs matched by query exceeds limit" in low or "query returned more than" in low:
        e9 = NetError(text, "range", code=code)
        e9.results = True
        return e9
    if "rate limit" in low or code in (-32016, -32029, -32007, -32008, 429) or "too many requests" in low \
            or "max usage" in low or "exceeded the quota" in low \
            or "request limit reached" in low or "calls per second" in low or "/second request limit" in low:
        persec = ("second" in low or code == -32007) and not ("max usage" in low or "quota" in low)
        permin = ("minute" in low or code == -32008) and not ("max usage" in low or "quota" in low)
        e9 = NetError(text, "quota" if ("max usage" in low or "quota" in low) else "http429", code=code,
                      retry_after=(1.0 + random.random() * 0.5) if persec else ((20.0 + random.random() * 10) if permin else None))
        e9.persec = persec
        return e9
    m = _RANGE_CAP_RE.search(msg)
    ms = re.search(r"block span \d+ .{0,60}?exceeds? the limit (\d{2,7})", low)
    if ms:
        return NetError(text, "range", code=code, cap=int(ms.group(1)))
    if "exceed maximum block range" in low or "block range" in low or "range too large" in low \
            or "too many results" in low or "query returned more than" in low or "response size" in low \
            or "limit exceeded" in low or code in (-32005, -32602) and ("range" in low or "limit" in low) \
            or "is limited to a" in low or "max allowed range" in low or "blocks distance" in low or "range is too large" in low \
            or "ranges over" in low:
        cap = int(m.group(1)) if (m and "maximum block range" in low) else None
        return NetError(text, "range", code=code, cap=cap)
    return NetError(text, "rpc", code=code)


def classify_exc(e: BaseException, host: str = None) -> NetError:
    if isinstance(e, NetError):
        return e
    if isinstance(e, urllib.error.HTTPError):
        code = e.code
        body = ""
        try:
            body = (e.read() or b"")[:300].decode("utf-8", "replace")
        except Exception:
            pass
        ra = retry_after_sec(e.headers.get("Retry-After") if e.headers else None)
        msg = f"HTTP Error {code}: {e.reason}" + (f" ({body.strip()[:120]})" if body.strip() else "")
        if code == 429:
            kind = "quota" if ("max usage" in body.lower() or "quota" in body.lower()) else "http429"
            return NetError(msg, kind, code=code, retry_after=ra, host=host)
        if 500 <= code < 600:
            return NetError(msg, "http5xx", code=code, retry_after=ra, host=host)
        if code == 400 and body:
            e9 = classify_rpc_error(body)
            if e9.kind in ("range", "pruned", "timeout"):
                e9.host = host
                return e9
        e4 = NetError(msg, "http4xx", code=code, host=host)
        e4.body = common.redact_secret_text(body, generic=False) if body else ""
        return e4
    s = str(e)
    if isinstance(e, (socket.timeout, TimeoutError)) or "timed out" in s:
        return NetError(f"timeout: {s[:120]}", "timeout", host=host)
    if "nodename nor servname" in s or "Name or service not known" in s or "Temporary failure in name" in s:
        return NetError(f"dns: {s[:120]}", "dns", host=host)
    if isinstance(e, (ConnectionError, urllib.error.URLError, OSError)):
        return NetError(f"conn: {s[:160]}", "conn", host=host)
    if isinstance(e, (ValueError, json.JSONDecodeError)):
        return NetError(f"payload: {s[:160]}", "payload", host=host)
    return NetError(f"{type(e).__name__}: {s[:160]}", "other", host=host)


DEFAULT_POLICY = {"rate": 4.0, "burst": 4, "conc": 4, "reserve": 0}
HOST_POLICIES = {
    "rpc1.monad.xyz": {"rate": 2.0, "burst": 2, "conc": 1},
    "rpc2.monad.xyz": {"rate": 2.0, "burst": 2, "conc": 1},
    "rpc.plasma.to": {"rate": 2.0, "burst": 2, "conc": 1},
    "xlayerrpc.okx.com": {"rate": 2.0, "burst": 2, "conc": 1},
    "rpc.xlayer.tech": {"rate": 2.0, "burst": 2, "conc": 1},
    "public-en.node.kaia.io": {"rate": 2.0, "burst": 2, "conc": 1},
    "api.avax.network": {"rate": 2.0, "burst": 2, "conc": 1},
    "rpc.frax.com": {"rate": 2.0, "burst": 2, "conc": 1},
    "rpc.gobob.xyz": {"rate": 2.0, "burst": 2, "conc": 1},
    "www.storyscan.io": {"rate": 1.0, "burst": 5, "conc": 2, "reserve": 30, "reset_unit": "ms"},
    "explorer.somnia.network": {"rate": 1.0, "burst": 5, "conc": 2, "reserve": 30, "reset_unit": "ms"},
    "api.etherscan.io": {"rate": 2.0, "burst": 1, "conc": 2},
    "base.blockscout.com": {"rate": 1.0, "burst": 5, "conc": 2, "reserve": 30, "reset_unit": "ms", "breaker_fails": 8},
    "optimism.blockscout.com": {"rate": 1.0, "burst": 5, "conc": 2, "reserve": 30, "reset_unit": "ms"},
    "explorer.optimism.io": {"rate": 1.0, "burst": 5, "conc": 2, "reserve": 30, "reset_unit": "ms"},
    "*.blockscout.com": {"rate": 1.0, "burst": 5, "conc": 2, "reserve": 30, "reset_unit": "ms"},
    "mainnet.helius-rpc.com": {"rate": 4.0, "burst": 4, "conc": 2},
    "api.mainnet-beta.solana.com": {"rate": 3.0, "burst": 3, "conc": 2},
    "solana-rpc.publicnode.com": {"rate": 3.0, "burst": 3, "conc": 2},
    "bsc-mainnet.nodereal.io": {"rate": 8.0, "burst": 8, "conc": 4},
    "bsc.rpc.blxrbdn.com": {"rate": 2.0, "burst": 2, "conc": 2},
    "rpc-bsc.48.club": {"rate": 2.0, "burst": 2, "conc": 2},
    "*.bnbchain.org": {"rate": 4.0, "burst": 4, "conc": 3},
    "bsc.rpc.sentio.xyz": {"rate": 1.0, "burst": 2, "conc": 1},
    "rpc.mainnet.chain.robinhood.com": {"rate": 2.0, "burst": 2, "conc": 1},
    "robinhood.drpc.org": {"rate": 2.0, "burst": 2, "conc": 1},
    "rpc.mainnet.arc.io": {"rate": 2.0, "burst": 2, "conc": 1},
    "rpc.quicknode.mainnet.arc.io": {"rate": 2.0, "burst": 2, "conc": 1},
    "rpc.blast.io": {"rate": 2.0, "burst": 2, "conc": 1, "call_rate": 8.0, "call_burst": 8},
}

BREAKER_FAILS = 4
BREAKER_BASE = 15.0
BREAKER_MAX = 600.0
OPEN_WAIT = 30.0
QUOTA_OPEN = 1800.0


def _pol_num(v, default, typ, lo, hi):
    try:
        x = float(v)
    except (TypeError, ValueError, OverflowError):
        return default
    if x != x or x in (float("inf"), float("-inf")):
        return default
    return typ(min(hi, max(lo, x)))


class HostGate:
    def __init__(self, host: str, pol: dict):
        self.host = host
        self.rate = float(pol.get("rate", DEFAULT_POLICY["rate"]))
        self.burst = float(pol.get("burst", DEFAULT_POLICY["burst"]))
        self.reserve = int(pol.get("reserve", 0))
        self.sem = threading.BoundedSemaphore(max(1, int(pol.get("conc", DEFAULT_POLICY["conc"]))))
        self.lock = threading.Lock()
        self.tokens = self.burst
        self.t_last = time.monotonic()
        self.q_remaining = None
        self.q_reset_at = 0.0
        self.fail_streak = 0
        self.open_until = 0.0
        self.open_count = 0
        self.pause_until = 0.0
        self.open_wait = _pol_num(pol.get("open_wait"), OPEN_WAIT, float, 0.0, 120.0)
        self.breaker_fails = _pol_num(pol.get("breaker_fails"), BREAKER_FAILS, int, 1, 100)
        self.reset_unit = str(pol.get("reset_unit") or "auto").lower()
        self.q_limit = None
        self.ms_seen = False
        self.call_rate = _pol_num(pol.get("call_rate"), 0.0, float, 0.0, 10000.0)
        self.call_burst = _pol_num(pol.get("call_burst"), self.call_rate, float, 1.0, 10000.0) if self.call_rate else 0.0
        self.c_tokens = self.call_burst
        self.c_last = time.monotonic()

    def _wait_needed(self, prio: str, cost: int = 1) -> float:
        now_m = time.monotonic()
        self.tokens = min(self.burst, self.tokens + (now_m - self.t_last) * self.rate)
        self.t_last = now_m
        w = 0.0
        if self.tokens < 1.0:
            w = (1.0 - self.tokens) / max(self.rate, 1e-6)
        if self.call_rate:
            self.c_tokens = min(self.call_burst, self.c_tokens + (now_m - self.c_last) * self.call_rate)
            self.c_last = now_m
            need = min(float(cost), self.call_burst)
            if self.c_tokens < need:
                w = max(w, (need - self.c_tokens) / self.call_rate)
        now = time.time()
        if self.pause_until > now:
            w = max(w, self.pause_until - now)
        if self.q_remaining is not None and self.q_reset_at > now:
            floor = self.reserve if prio == "bg" else 0
            if floor and self.q_limit:
                floor = min(floor, max(1, int(self.q_limit) // 3))
            if self.q_remaining <= floor:
                w = max(w, self.q_reset_at - now + 0.5)
        return w

    def batch_cap(self, default: int = 40) -> int:
        return max(1, min(int(default), int(self.call_burst))) if self.call_rate else int(default)

    def acquire(self, prio: str = "fg", deadline: float = None, cost: int = 1):
        while True:
            with self.lock:
                now = time.time()
                if self.open_until > now:
                    left = self.open_until - now
                    if left > self.open_wait or self.open_count > 1 or (deadline is not None and now + left > deadline):
                        raise CircuitOpen(self.host, self.open_until)
                    w = left + 0.05
                else:
                    w = self._wait_needed(prio, cost)
                if w <= 0:
                    self.tokens -= 1.0
                    if self.call_rate:
                        self.c_tokens -= float(max(1, cost))
                    if self.q_remaining is not None:
                        self.q_remaining -= 1
                    return
            if deadline is not None and time.time() + w > deadline:
                raise NetError(f"budget: {self.host} 대기 {w:.0f}s > 남은 예산", "budget", host=self.host)
            time.sleep(min(w, 30.0))

    def observe(self, headers):
        if not headers:
            return
        try:
            rem = headers.get("x-ratelimit-remaining") or headers.get("X-RateLimit-Remaining")
            rst = headers.get("x-ratelimit-reset") or headers.get("X-RateLimit-Reset")
            if rem is None:
                return
            rem = int(float(rem))
            lim = headers.get("x-ratelimit-limit") or headers.get("X-RateLimit-Limit")
            try:
                lim = int(float(lim)) if lim is not None else None
            except (TypeError, ValueError):
                lim = None
            reset_s = None
            if rst is not None:
                reset_s = self._reset_seconds(float(rst), lim)
            with self.lock:
                self.q_remaining = rem
                if lim and lim > 0:
                    self.q_limit = lim
                if reset_s is not None:
                    self.q_reset_at = time.time() + max(0.0, reset_s)
        except (TypeError, ValueError):
            pass

    RESET_S_MAX_AMBIG = 60.0

    def _reset_seconds(self, v: float, lim=None) -> float:
        if v > 1e12:
            return v / 1000.0 - time.time()
        if v > 1e9:
            return v - time.time()
        if v > 1000:
            self.ms_seen = True
            return v / 1000.0
        unit = self.reset_unit
        if unit == "s":
            return v
        if unit == "ms" or self.ms_seen or (lim is not None and 0 < lim <= 60) or v > self.RESET_S_MAX_AMBIG:
            return v / 1000.0
        return v

    def success(self):
        with self.lock:
            self.fail_streak = 0
            self.open_count = 0

    def failure(self, err: NetError, quota_open: float = None, count_5xx: bool = True):
        if quota_open is None:
            quota_open = QUOTA_OPEN
        with self.lock:
            now = time.time()
            if err.kind == "quota":
                self.open_until = now + quota_open * (1.0 + random.random() * 0.1)
                self.open_count += 1
                return
            if err.kind == "http429":
                ra = err.retry_after if err.retry_after is not None else 10.0 * (1 + random.random())
                self.pause_until = max(self.pause_until, now + min(ra, 120.0))
            if err.kind == "http5xx" and not count_5xx:
                return
            if err.kind in ("http429", "http5xx", "timeout", "dns", "conn"):
                self.fail_streak += 1
                if self.fail_streak >= self.breaker_fails:
                    wait = min(BREAKER_BASE * (2 ** self.open_count), BREAKER_MAX) * (1.0 + random.random() * 0.5)
                    self.open_until = now + wait
                    self.open_count += 1
                    self.fail_streak = 0

    def is_open(self) -> bool:
        return self.open_until > time.time()


_GATES = {}
_GATES_LOCK = threading.Lock()
_POLICY_OVERRIDES = {}


ES_DAILY_BUDGET = 80000
ESB_FLUSH_EVERY = 20
_ESB = {"day": None, "n": 0, "flushed": 0, "others": 0, "others_at": 0.0}
_ESB_LOCK = threading.Lock()


def _esb_dir() -> str:
    return os.path.join(common.quota_dir(), "es_budget")


def _esb_sync(proc: str, now: float):
    d = _esb_dir()
    me = f"{proc}.{os.getpid()}.json"
    try:
        os.makedirs(d, exist_ok=True)
        common.atomic_write_json(os.path.join(d, me), {"day": _ESB["day"], "n": _ESB["n"], "proc": proc, "pid": os.getpid(), "at": int(now)})
        _ESB["flushed"] = _ESB["n"]
        tot = 0
        for f in os.listdir(d):
            if not f.endswith(".json") or f == me:
                continue
            try:
                j = common.read_json(os.path.join(d, f), {})
            except (Exception, SystemExit):
                continue
            if not isinstance(j, dict):
                continue
            if j.get("day") == _ESB["day"]:
                tot += int(j.get("n") or 0)
            elif isinstance(j.get("day"), int) and j["day"] < _ESB["day"]:
                try:
                    os.remove(os.path.join(d, f))
                except OSError:
                    pass
        _ESB["others"] = tot
    except OSError:
        pass
    _ESB["others_at"] = now


def es_budget_take(proc: str, now: float = None) -> bool:
    now = time.time() if now is None else now
    day = int(now // 86400)
    with _ESB_LOCK:
        if _ESB["day"] != day:
            _ESB.update(day=day, n=0, flushed=0, others=0, others_at=0.0)
        if now - _ESB["others_at"] > 30 or _ESB["n"] - _ESB["flushed"] >= ESB_FLUSH_EVERY:
            _esb_sync(proc, now)
        if _ESB["n"] + _ESB["others"] >= ES_DAILY_BUDGET:
            if _ESB["n"] != _ESB["flushed"]:
                _esb_sync(proc, now)
            return False
        _ESB["n"] += 1
        return True


ES_DISPATCH_GAP = 0.5
ES_DISPATCH_FALLBACK = 1.0
_es_log = __import__("logging").getLogger("tj-bf")
ES_DISPATCH_LOCK_WAIT = 30.0
_ES_DISPATCH_LOCAL = threading.Lock()
_ES_DISPATCH_WARNED = [False]


def es_dispatch_wait(deadline: float = None):
    with _ES_DISPATCH_LOCAL:
        try:
            d = _esb_dir()
            os.makedirs(d, exist_ok=True)
            fd = os.open(os.path.join(d, "dispatch.slot"), os.O_RDWR | os.O_CREAT, 0o600)
        except OSError as e:
            if not _ES_DISPATCH_WARNED[0]:
                _ES_DISPATCH_WARNED[0] = True
                _es_log.warning("이더스캔 공유 간격 파일 사용 불가 — 보수 간격 %.1f초로 대기: %s", ES_DISPATCH_FALLBACK, str(e)[:120])
            _es_fallback_sleep(deadline)
            return
        try:
            t_lock = time.time()
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.time() - t_lock > ES_DISPATCH_LOCK_WAIT or (deadline is not None and time.time() >= deadline):
                        raise NetError("budget: 이더스캔 공유 간격 잠금 대기 초과", "budget", host="api.etherscan.io")
                    time.sleep(0.02)
                except OSError as e:
                    if not _ES_DISPATCH_WARNED[0]:
                        _ES_DISPATCH_WARNED[0] = True
                        _es_log.warning("이더스캔 공유 간격 잠금 실패 — 보수 간격 %.1f초: %s", ES_DISPATCH_FALLBACK, str(e)[:120])
                    _es_fallback_sleep(deadline)
                    return
            try:
                raw = os.pread(fd, 64, 0).decode("ascii", "replace").strip()
                try:
                    last = float(raw) if raw else 0.0
                except ValueError:
                    last = time.time()
                now = time.time()
                if last > now + 5:
                    last = now
                wait = last + ES_DISPATCH_GAP - now
                if wait > 0:
                    if deadline is not None and now + wait > deadline:
                        raise NetError("budget: 이더스캔 공유 간격 대기가 마감을 넘음", "budget", host="api.etherscan.io")
                    time.sleep(wait)
                b = ("%.6f" % time.time()).encode()
                os.ftruncate(fd, 0)
                os.pwrite(fd, b, 0)
            except OSError as e:
                if not _ES_DISPATCH_WARNED[0]:
                    _ES_DISPATCH_WARNED[0] = True
                    _es_log.warning("이더스캔 공유 간격 기록 실패 — 보수 간격 %.1f초: %s", ES_DISPATCH_FALLBACK, str(e)[:120])
                _es_fallback_sleep(deadline)
            finally:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            os.close(fd)


def _es_fallback_sleep(deadline):
    if deadline is not None and time.time() + ES_DISPATCH_FALLBACK > deadline:
        raise NetError("budget: 이더스캔 보수 간격 대기가 마감을 넘음", "budget", host="api.etherscan.io")
    time.sleep(ES_DISPATCH_FALLBACK)


def es_budget_used() -> tuple:
    with _ESB_LOCK:
        return _ESB["n"] + _ESB["others"], ES_DAILY_BUDGET


def configure(cfg: dict):
    global QUOTA_OPEN, ES_DAILY_BUDGET
    try:
        ES_DAILY_BUDGET = int(((cfg or {}).get("etherscan") or {}).get("daily_budget") or 80000)
    except (TypeError, ValueError):
        ES_DAILY_BUDGET = 80000
    bf = (cfg or {}).get("backfill") or {}
    for h, p in (bf.get("hosts") or {}).items():
        if isinstance(p, dict):
            _POLICY_OVERRIDES[str(h).lower()] = p
    if bf.get("quota_open_sec"):
        QUOTA_OPEN = float(bf["quota_open_sec"])
    with _GATES_LOCK:
        _GATES.clear()


def _policy_for(host: str) -> dict:
    h = host.lower()

    def pick(table):
        if h in table:
            return table[h]
        for k, v in table.items():
            if k.startswith("*.") and h.endswith(k[1:]):
                return v
        return {}
    out = dict(DEFAULT_POLICY)
    out.update(pick(HOST_POLICIES))
    out.update(pick(_POLICY_OVERRIDES))
    return out


def gate_wait(url_or_host: str, prio: str = "bg") -> float:
    host = urllib.parse.urlsplit(url_or_host).hostname if "://" in url_or_host else url_or_host
    with _GATES_LOCK:
        g = _GATES.get((host or "?").lower())
    if g is None:
        return 0.0
    with g.lock:
        now = time.time()
        if g.open_until > now:
            return g.open_until - now
        return max(0.0, g._wait_needed(prio, 1))


def gate(url_or_host: str) -> HostGate:
    host = urllib.parse.urlsplit(url_or_host).hostname if "://" in url_or_host else url_or_host
    host = (host or "?").lower()
    with _GATES_LOCK:
        g = _GATES.get(host)
        if g is None:
            g = _GATES[host] = HostGate(host, _policy_for(host))
        return g


def set_call_rate(url_or_host: str, rps) -> float:
    try:
        r = float(rps)
    except (TypeError, ValueError):
        return 0.0
    if not (r > 0) or r != r or r == float("inf"):
        return 0.0
    g = gate(url_or_host)
    with g.lock:
        if g.call_rate:
            return g.call_rate
        g.call_rate = min(10000.0, r)
        g.call_burst = max(1.0, g.call_rate)
        g.c_tokens = g.call_burst
        g.c_last = time.monotonic()
        return g.call_rate


_STATS = {}
_STATS_LOCK = threading.Lock()


def _stat(host: str, kind: str, n: int = 1):
    with _STATS_LOCK:
        d = _STATS.setdefault(host, {})
        d[kind] = d.get(kind, 0) + n


def stats_snapshot() -> dict:
    with _STATS_LOCK:
        return {h: dict(v) for h, v in _STATS.items()}


def _backoff(i: int, base: float = 1.0, cap: float = 20.0) -> float:
    return random.uniform(0, min(cap, base * (2 ** i)))


RETRYABLE = ("http429", "http5xx", "timeout", "conn", "dns", "payload")


def _open(req, timeout):
    return urllib.request.urlopen(req, timeout=timeout)


def http_request(url: str, *, data: bytes = None, headers: dict = None, timeout: float = 25.0,
                 retries: int = 3, retry_5xx: bool = True, prio: str = "fg", deadline: float = None,
                 ua: str = UA, max_inline_wait: float = 20.0, breaker_5xx: bool = True, cost: int = 1,
                 sem_timeout: float = None, gate_host: str = None):
    host = (urllib.parse.urlsplit(url).hostname or "?").lower()
    g = gate(gate_host or host)
    last = None
    hard = sem_timeout is not None

    def _left():
        return None if deadline is None else deadline - time.time()
    for i in range(max(1, retries)):
        if hard and _left() is not None and _left() <= 0:
            raise NetError(f"budget: {host} 요청 마감 지남", "budget", host=host)
        g.acquire(prio=prio, deadline=deadline, cost=cost)
        if not hard:
            g.sem.acquire()
        else:
            l9 = _left()
            st9 = float(sem_timeout) if l9 is None else min(float(sem_timeout), l9)
            if st9 <= 0 or not g.sem.acquire(timeout=st9):
                raise NetError(f"budget: {host} 동시 요청 대기 {max(0.0, st9):.1f}s 초과", "budget", host=host)
        try:
            to9 = timeout
            if hard and _left() is not None:
                l9 = _left()
                if l9 <= 0:
                    raise NetError(f"budget: {host} 요청 마감 지남", "budget", host=host)
                to9 = min(float(timeout), l9)
            h = {"User-Agent": common.ua_for(url, ua), "Accept": "application/json"}
            if data is not None:
                h["Content-Type"] = "application/json"
            h.update(headers or {})
            req = urllib.request.Request(url, data=data, headers=h)
            if host == "api.etherscan.io":
                es_dispatch_wait(deadline)
            _stat(host, "calls")
            with _open(req, to9) as r:
                g.observe(r.headers)
                raw = r.read()
            try:
                d = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as e:
                raise NetError(f"payload: JSON 파싱 불가 ({str(e)[:60]})", "payload", host=host)
            g.success()
            return d, None
        except CircuitOpen:
            raise
        except Exception as e:
            err = classify_exc(e, host)
            if isinstance(e, urllib.error.HTTPError):
                g.observe(e.headers)
            _stat(host, err.kind)
            g.failure(err, count_5xx=breaker_5xx)
            last = err
            if err.kind not in RETRYABLE or (err.kind == "http5xx" and not retry_5xx) or err.kind == "quota":
                raise err
            if i + 1 >= retries:
                break
            wait = err.retry_after if (err.kind == "http429" and err.retry_after is not None) else _backoff(i)
            if wait > max_inline_wait or (deadline is not None and time.time() + wait > deadline):
                raise err
            time.sleep(wait)
        finally:
            g.sem.release()
    raise last if last else NetError("요청 실패", "other", host=host)


def http_json(url: str, **kw):
    return http_request(url, **kw)[0]


RATE_RETRIES = 4


def _persec(err) -> bool:
    return isinstance(err, NetError) and err.kind == "http429" and bool(getattr(err, "persec", False))


def _rate_wait(err, i: int, deadline) -> float:
    w = err.retry_after if getattr(err, "retry_after", None) is not None else min(8.0, 1.0 * (2 ** i))
    w = float(w) * (1 + i * 0.5)
    if deadline is not None and time.time() + w > deadline:
        return None
    return w


def rpc_call(url: str, method: str, params, *, timeout: float = 25.0, retries: int = 2,
             prio: str = "fg", deadline: float = None, allow_null: bool = False):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    host = (urllib.parse.urlsplit(url).hostname or "?").lower()
    for i9 in range(RATE_RETRIES + 1):
        d = http_json(url, data=body, timeout=timeout, retries=retries, prio=prio, deadline=deadline)
        if not isinstance(d, dict):
            raise NetError(f"rpc {method}: 응답 형식 오류 ({type(d).__name__})", "payload", host=host)
        if not d.get("error"):
            break
        err = classify_rpc_error(d["error"])
        err.host = host
        _stat(host, "rpc_" + err.kind)
        if err.kind in ("http429", "quota"):
            gate(host).failure(err)
        w9 = _rate_wait(err, i9, deadline) if (_persec(err) and i9 < RATE_RETRIES) else None
        if w9 is None:
            raise err
        time.sleep(w9)
    if d.get("result") is None and not allow_null:
        raise NetError(f"rpc {method}: result null", "null", host=host)
    return d.get("result")


def rpc_batch(url: str, calls: list, *, timeout: float = 30.0, retries: int = 2, prio: str = "fg",
              deadline: float = None) -> list:
    if not calls:
        return []
    host = (urllib.parse.urlsplit(url).hostname or "?").lower()
    out = _rpc_batch_once(url, calls, timeout, retries, prio, deadline, host)
    for i9 in range(RATE_RETRIES):
        idx = [k for k, r in enumerate(out) if isinstance(r, NetError) and _persec(r)]
        if not idx:
            break
        gate(host).failure(out[idx[0]])
        _stat(host, "rpc_http429", len(idx))
        w9 = _rate_wait(out[idx[0]], i9, deadline)
        if w9 is None:
            break
        time.sleep(w9)
        again = _rpc_batch_once(url, [calls[k] for k in idx], timeout, retries, prio, deadline, host)
        for k, r in zip(idx, again):
            out[k] = r
    return out


def _rpc_batch_once(url, calls, timeout, retries, prio, deadline, host) -> list:
    body = json.dumps([{"jsonrpc": "2.0", "id": i, "method": m, "params": p}
                       for i, (m, p) in enumerate(calls)]).encode()
    for i9 in range(RATE_RETRIES + 1):
        d = http_json(url, data=body, timeout=timeout, retries=retries, prio=prio, deadline=deadline, cost=len(calls))
        if isinstance(d, dict) and d.get("error"):
            err = classify_rpc_error(d["error"])
            err.host = host
            w9 = _rate_wait(err, i9, deadline) if (_persec(err) and i9 < RATE_RETRIES) else None
            if w9 is None:
                raise err
            gate(host).failure(err)
            time.sleep(w9)
            continue
        break
    if not isinstance(d, list):
        raise NetError(f"rpc batch: 응답 형식 오류 ({type(d).__name__})", "payload", host=host)
    out = [NetError("rpc batch: 응답 누락", "null", host=host) for _ in calls]
    for it in d:
        if not isinstance(it, dict):
            continue
        try:
            i = int(it.get("id"))
        except (TypeError, ValueError):
            continue
        if not (0 <= i < len(calls)):
            continue
        if it.get("error"):
            e = classify_rpc_error(it["error"])
            e.host = host
            out[i] = e
        elif it.get("result") is None:
            out[i] = NetError(f"rpc {calls[i][0]}: result null", "null", host=host)
        else:
            out[i] = it["result"]
    return out


DEC_CONFIRM_N = 3
DEC_CONFIRM_SEC = 600


class TokenNoDecimals(RuntimeError):
    pass


def decimals_from_result(r):
    if not isinstance(r, str) or not r.lower().startswith("0x"):
        return None, f"형식 오류({type(r).__name__})"
    h = r[2:]
    if not h:
        return None, "빈 반환(0x)"
    try:
        dec = int(h, 16)
    except ValueError:
        return None, "hex 아님"
    if not (0 <= dec <= 77):
        return None, f"uint8 범위 밖({str(dec)[:20]})"
    return dec, None


def revert_like(e) -> bool:
    m = str(e).lower()
    return "revert" in m or "invalid opcode" in m or "bad instruction" in m or "invalid jump" in m


class NoDecRegistry:

    SKIP_LOG = "token_leg_skips.jsonl"

    def __init__(self, chain: str, log=None):
        self.chain = chain
        self.path = os.path.join(common.STATE_DIR, f"token_nodec_{chain}.json")
        self.d = common.read_json(self.path, {}) or {}
        self.log = log
        self._lock = threading.Lock()

    def perm(self, ca: str) -> bool:
        e = self.d.get(str(ca).lower())
        return bool(isinstance(e, dict) and e.get("perm"))

    def bad(self, ca: str, why: str, now: float = None) -> bool:
        ca, now = str(ca).lower(), int(now or time.time())
        with self._lock:
            e = self.d.setdefault(ca, {"n": 0, "first": now, "perm": False})
            e["n"] = int(e.get("n") or 0) + 1
            e["last"], e["why"] = now, str(why)[:120]
            newly = (not e.get("perm") and e["n"] >= DEC_CONFIRM_N and now - int(e.get("first") or now) >= DEC_CONFIRM_SEC)
            if newly:
                e["perm"] = now
            try:
                common.atomic_write_json(self.path, self.d)
            except OSError:
                pass
        if newly and self.log:
            self.log.warning("★%s 토큰 %s decimals() 영구 불능 확정(%s · %d회 · %.0f분) — 이 토큰 레그는 기장하지 않음(tx 나머지는 확정, "
                             "기록 state/%s)★", self.chain, ca[:10], e["why"], e["n"], (now - int(e["first"])) / 60, self.SKIP_LOG)
        return bool(e.get("perm"))

    def ok(self, ca: str):
        ca = str(ca).lower()
        e = self.d.get(ca)
        if isinstance(e, dict) and not e.get("perm"):
            with self._lock:
                self.d.pop(ca, None)
                try:
                    common.atomic_write_json(self.path, self.d)
                except OSError:
                    pass

    def skip(self, txhash: str, ca: str, frm: str, to: str, value) -> None:
        ca, h = str(ca).lower(), str(txhash).lower()
        with self._lock:
            e = self.d.setdefault(ca, {"n": 0, "first": int(time.time()), "perm": int(time.time())})
            sk = e.setdefault("skips", [])
            if h in sk:
                return
            sk.append(h)
            del sk[:-200]
            try:
                common.atomic_write_json(self.path, self.d)
            except OSError:
                pass
        try:
            common.append_durable_jsonl(os.path.join(common.STATE_DIR, self.SKIP_LOG),
                                        {"ts": int(time.time()), "chain": self.chain, "txhash": h, "token": ca,
                                         "from": str(frm or "").lower(), "to": str(to or "").lower(), "value": str(value),
                                         "why": (self.d.get(ca) or {}).get("why")})
        except OSError:
            pass
        if self.log:
            self.log.info("%s tx %s 토큰 %s 레그 건너뜀(decimals 영구 불능 — state/%s)", self.chain, h[:12], ca[:10], self.SKIP_LOG)


DETAIL_FAIL_MAX = 200
DETAIL_FAIL_SEC = 6 * 3600
QUAR_RETRY_SEC = 86400
QUAR_RETRY_PER_CYCLE = 5
_DET_MSG = ("gasused 미확보", "형식 오류", "형식 이상", "malformed", "invalid hex", "decode")


def detail_err_deterministic(e) -> bool:
    if isinstance(e, TokenNoDecimals):
        return True
    if isinstance(e, json.JSONDecodeError):
        return False
    if isinstance(e, NetError):
        return e.kind == "rpc" and revert_like(e)
    if isinstance(e, (KeyError, TypeError, IndexError, AttributeError, ValueError)):
        return True
    if revert_like(e):
        return True
    m = str(e).lower()
    return any(k in m for k in _DET_MSG)


def quarantine_map(cursor: dict) -> dict:
    q = cursor.get("_quarantine")
    if isinstance(q, list):
        now = int(time.time())
        q = {str(h): {"at": now, "next": now + QUAR_RETRY_SEC, "n": 0} for h in q}
        cursor["_quarantine"] = q
    elif not isinstance(q, dict):
        q = cursor["_quarantine"] = {}
    return q


def detail_fail_note(cursor: dict, bad: list, dets: dict, chain: str, src: str, log=None, seen: set = None, blocks: dict = None) -> list:
    now = int(time.time())
    fm = cursor.setdefault("_detail_fail", {})
    q = quarantine_map(cursor)
    left = []
    for h in bad:
        e = dets.get(h)
        if h in q:
            continue
        if "예산 소진" in str(e) or not detail_err_deterministic(e):
            left.append(h)
            continue
        n9, t9 = (fm.get(h) or [0, now])[:2]
        if seen is None or h not in seen:
            n9 += 1
            if seen is not None:
                seen.add(h)
        fm[h] = [n9, t9]
        if n9 >= DETAIL_FAIL_MAX and now - int(t9) >= DETAIL_FAIL_SEC:
            err9 = common.safe_err(e)[:200]
            common.append_durable_jsonl(os.path.join(common.STATE_DIR, "pending_poison.jsonl"),
                                        {"ts": now, "chain": chain, "txhash": h, "src": src, "n": n9, "err": err9})
            q[h] = {"at": now, "next": now + QUAR_RETRY_SEC, "n": 0, "err": err9[:120]}
            if blocks and blocks.get(h) is not None:
                try:
                    q[h]["blk"] = int(blocks[h])
                except (TypeError, ValueError):
                    pass
            fm.pop(h, None)
            if log:
                log.error("★%s 상세 %s 결정적 실패 %d회·%.0f시간 — 격리(pending_poison.jsonl · 하루마다 재시도) 후 커서 전진: %s★",
                          chain, h[:12], n9, (now - int(t9)) / 3600, err9[:120])
        else:
            left.append(h)
    return left


def detail_fail_clear(cursor: dict, ok_hashes):
    fm = cursor.get("_detail_fail")
    if isinstance(fm, dict) and fm:
        for h in ok_hashes:
            fm.pop(h, None)


def quarantine_due(cursor: dict, now: float = None, limit: int = QUAR_RETRY_PER_CYCLE) -> list:
    now = now or time.time()
    q = quarantine_map(cursor)
    return sorted((h for h, v in q.items() if float((v or {}).get("next") or 0) <= now), key=lambda h: q[h].get("next") or 0)[:limit]


def quarantine_result(cursor: dict, h: str, ok: bool, chain: str, src: str, log=None, err=None):
    q = quarantine_map(cursor)
    now = int(time.time())
    if ok:
        e9 = q.pop(h, None) or {}
        if e9.get("blk") is not None:
            rel = cursor.setdefault("_q_released", {})
            rel[h] = int(e9["blk"])
            for k9 in list(rel)[:-500]:
                rel.pop(k9, None)
        common.append_durable_jsonl(os.path.join(common.STATE_DIR, "pending_poison.jsonl"),
                                    {"ts": now, "chain": chain, "txhash": h, "src": src, "released": True})
        if log:
            log.warning("★%s 격리 tx %s 재시도 성공 — 방출·격리 해제★", chain, h[:12])
    elif h in q:
        q[h]["next"] = now + QUAR_RETRY_SEC
        q[h]["n"] = int(q[h].get("n") or 0) + 1
        if err is not None:
            q[h]["err"] = common.safe_err(err)[:120]


_NODEC = {}
_NODEC_LOCK = threading.Lock()


def nodec_registry(chain: str, log=None) -> "NoDecRegistry":
    with _NODEC_LOCK:
        r = _NODEC.get(chain)
        if r is None or r.path != os.path.join(common.STATE_DIR, f"token_nodec_{chain}.json"):
            r = _NODEC[chain] = NoDecRegistry(chain, log)
        return r


def block_at_ts(get_ts, target_ts: int, lo: int, hi: int, max_calls: int = 40) -> int:
    lo, hi = int(lo), int(hi)
    if hi <= lo:
        return lo
    t_lo, t_hi = get_ts(lo), get_ts(hi)
    calls = 2
    if t_lo >= target_ts:
        return lo
    if t_hi < target_ts:
        return hi
    use_bisect = False
    while hi - lo > 1 and calls < max_calls:
        width = hi - lo
        if use_bisect or t_hi <= t_lo:
            g = (lo + hi) // 2
            t = get_ts(g)
            calls += 1
            if t < target_ts:
                lo, t_lo = g, t
            else:
                hi, t_hi = g, t
            use_bisect = False
            continue
        g = lo + int((target_ts - t_lo) * width / float(t_hi - t_lo))
        g = min(max(g, lo + 1), hi - 1)
        m = max(1, width // 64)
        t = get_ts(g)
        calls += 1
        if t < target_ts:
            lo, t_lo = g, t
            g2 = min(g + m, hi - 1)
        else:
            hi, t_hi = g, t
            g2 = max(g - m, lo + 1)
        if lo < g2 < hi:
            t2 = get_ts(g2)
            calls += 1
            if t2 < target_ts:
                lo, t_lo = g2, t2
            else:
                hi, t_hi = g2, t2
        use_bisect = (hi - lo) > width * 0.25
    if hi - lo > 1:
        return lo
    return lo


BSC_CANARY = {"from": 62_500_000, "to": 62_500_999, "expect": 1069,
              "topics": ["0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef", None,
                         "0x0000000000000000000000008894e0a0c962cb723c1976a4421c95949be2d4e3"]}
CANARY_TTL = 1800.0
_CANARY = {}
_CANARY_LOCK = threading.Lock()


def canary_check(url: str, canary: dict, *, timeout: float = 25.0, prio: str = "bg", now: float = None):
    now = time.time() if now is None else now
    with _CANARY_LOCK:
        c = _CANARY.get(url)
        if c and now - c[1] < CANARY_TTL:
            return c[0], c[2]
    total, span, a, res, why = 0, canary["to"] - canary["from"] + 1, canary["from"], None, ""
    try:
        while a <= canary["to"]:
            b = min(canary["to"], a + span - 1)
            try:
                rows = rpc_call(url, "eth_getLogs", [{"fromBlock": hex(a), "toBlock": hex(b), "topics": canary["topics"]}],
                                timeout=timeout, retries=1, prio=prio, allow_null=True)
            except NetError as e:
                if e.kind == "range" and span > 50:
                    span = max(50, min(span // 2, int(e.cap or span // 2)))
                    continue
                raise
            if not isinstance(rows, list):
                raise NetError("canary result null", "null")
            total += len(rows)
            a = b + 1
        res = total == int(canary["expect"])
        why = f"{total}/{canary['expect']}건"
    except Exception as e:
        res, why = None, f"오류 {common.safe_err(e)[:80]}"
    with _CANARY_LOCK:
        _CANARY[url] = (res, now, why)
    return res, why


SILENT_ROW_CAPS = frozenset((1000, 2000, 5000, 10000, 20000, 50000))


_EP_HEADS = {}
_EP_HEADS_LOCK = threading.Lock()
_EP_HEAD_OFF = {}
EP_HEAD_OFF_SEC = 600


class LogScanner:

    def __init__(self, endpoints: list, topic0: str, pads: list, *, span: int = 5000, min_span: int = 50,
                 caps: dict = None, fallback: dict = None, sleep: float = 0.0, timeout: float = 25.0,
                 per_ep_workers: int = 1, prio: str = "fg", log=None, name: str = "logs",
                 canary: dict = None, recent_blocks: int = 200_000, positions: dict = None,
                 head_guard: bool = True, head_refresh_sec: float = 15.0):
        self.positions = dict(positions) if positions else {1: topic0, 2: topic0}
        self.canary = canary
        self.recent_blocks = int(recent_blocks)
        self.canary_view = {}
        self.eps = [str(u) for u in endpoints]
        self.fallback = {str(u): int(c) for u, c in (fallback or {}).items() if int(c) > 0}
        self.topic0 = topic0
        self.pads = list(pads)
        self.span = max(1, int(span))
        self.min_span = max(1, int(min_span))
        self.caps = {u: int(c) for u, c in (caps or {}).items()}
        for u, c in self.fallback.items():
            self.caps.setdefault(u, c)
        self.pruned_below = {}
        self.sleep = float(sleep)
        self.timeout = float(timeout)
        self.per_ep_workers = max(1, int(per_ep_workers))
        self.prio = prio
        self.log = log
        self.name = name
        self.metrics = {"calls": 0, "range_split": 0, "halved": 0, "pruned": 0, "errors": 0, "head_calls": 0, "lag_clip": 0}
        self.head_guard = bool(head_guard)
        self.head_refresh_sec = float(head_refresh_sec)
        self.ep_head = {}
        self._head_at = {}
        self.lag_head = {}
        self.head_fail = {}
        self.head_off = set()

    def _known_head(self, url, need: int, refresh: bool = True):
        h = self.ep_head.get(url)
        if h is None:
            with _EP_HEADS_LOCK:
                g = _EP_HEADS.get(url)
            h = g[0] if g else None
        if h is not None and h >= need:
            return h
        if not refresh or (h is not None and time.time() - self._head_at.get(url, 0) < self.head_refresh_sec):
            return h if h is not None else -1
        self._head_at[url] = time.time()
        self.metrics["head_calls"] += 1
        r = rpc_call(url, "eth_blockNumber", [], timeout=min(10.0, self.timeout), retries=1, prio=self.prio)
        try:
            h2 = int(r, 16)
        except (TypeError, ValueError):
            raise NetError(f"eth_blockNumber 형식 오류: {str(r)[:40]}", "payload", host=_url_host(url))
        self.ep_head[url] = h2
        with _EP_HEADS_LOCK:
            _EP_HEADS[url] = (h2, time.time())
        return h2

    def _cap(self, url):
        return min(self.span, int(self.caps.get(url) or self.span))

    def _query(self, url, frm, to, pos):
        tp = [self.positions.get(pos, self.topic0), None, None] + [None] * max(0, pos - 2)
        tp[pos] = self.pads
        while tp and tp[-1] is None:
            tp.pop()
        res = rpc_call(url, "eth_getLogs", [{"fromBlock": hex(frm), "toBlock": hex(to), "topics": tp}],
                       timeout=self.timeout, retries=1, prio=self.prio, allow_null=True)
        if not isinstance(res, list):
            raise NetError(f"getLogs 비정상 result: {type(res).__name__}", "null",
                           host=urllib.parse.urlsplit(url).hostname)
        if len(res) in SILENT_ROW_CAPS:
            e9 = NetError(f"getLogs {len(res)}행 = 알려진 결과 상한 — 잘림 의심({frm}-{to})", "range",
                          host=urllib.parse.urlsplit(url).hostname)
            e9.results = True
            raise e9
        return res

    def scan(self, frm: int, to: int, deadline: float = None, on_advance=None):
        frm, to = int(frm), int(to)
        if to < frm:
            return {}, frm - 1
        lock = threading.Lock()
        cv = threading.Condition(lock)
        pending = []
        s = frm
        while s <= to:
            e = min(s + self.span - 1, to)
            pending.append([s, e])
            s = e + 1
        done = {}
        inflight = set()
        st = {"last": frm - 1, "stop": None, "found": {}}
        primaries = list(self.eps)
        all_eps = primaries + [u for u in self.fallback if u not in primaries]

        def advance_locked():
            moved = False
            while True:
                nxt = st["last"] + 1
                if nxt in done:
                    end, f = done.pop(nxt)
                    st["found"].update(f)
                    st["last"] = end
                    moved = True
                else:
                    break
            if moved and on_advance:
                try:
                    on_advance(st["last"], dict(st["found"]))
                except Exception:
                    pass

        old_below = to - self.recent_blocks
        untrusted = set()
        if self.canary and frm <= old_below:
            verdict = {u: canary_check(u, self.canary, timeout=self.timeout, prio=self.prio)
                       for u in list(dict.fromkeys(list(self.eps) + list(self.fallback)))}
            self.canary_view = {urllib.parse.urlsplit(u).netloc: (v[0], v[1]) for u, v in verdict.items()}
            anyok = any(v[0] is True for v in verdict.values())
            untrusted = {u for u, v in verdict.items() if v[0] is False or (anyok and v[0] is None)}
            if self.log and (untrusted or not anyok):
                self.log.warning("%s 옛 구간 카나리: %s%s", self.name,
                                 ", ".join(f"{h} {'통과' if r is True else '불통과' if r is False else '판정불가'}({w})"
                                           for h, (r, w) in self.canary_view.items()),
                                 "" if anyok else " — 통과 노드 없음(판정 불가 노드로 계속)")

        def usable(url, chunk):
            if url in untrusted and chunk[0] <= old_below:
                return False
            lh = self.lag_head.get(url)
            if lh is not None and chunk[0] > lh[0] and time.time() - lh[1] < max(1.0, self.head_refresh_sec):
                return False
            pb = self.pruned_below.get(url)
            return pb is None or chunk[0] > pb

        def pick(url):
            is_fb = url not in primaries
            for i, ch in enumerate(pending):
                if not usable(url, ch):
                    continue
                if is_fb:
                    if any(usable(p, ch) and not gate(p).is_open() for p in primaries):
                        continue
                cap = self._cap(url)
                if ch[1] - ch[0] + 1 > cap:
                    head = [ch[0], ch[0] + cap - 1]
                    ch[0] = head[1] + 1
                    return head
                return pending.pop(i)
            return None

        def requeue(chunks):
            pending.extend(chunks)
            pending.sort(key=lambda c: c[0])

        def worker(url):
            while True:
                with cv:
                    while True:
                        if st["stop"] is not None:
                            return
                        if deadline is not None and time.time() >= deadline:
                            return
                        if not pending and not inflight:
                            return
                        if gate(url).is_open():
                            ch = None
                        else:
                            ch = pick(url)
                        if ch is not None:
                            inflight.add(tuple(ch))
                            break
                        if pending and not inflight and all(
                                not usable(u, pending[0]) for u in all_eps):
                            if any(u in self.lag_head and pending[0][0] > self.lag_head[u][0] for u in all_eps):
                                st["stop"] = (f"구간 {pending[0][0]}-{pending[0][1]}: 로그 노드 헤드 미도달"
                                              f"(최고 {max(v[0] for v in self.lag_head.values())}) — 다음 사이클")
                            else:
                                st["stop"] = f"구간 {pending[0][0]}-{pending[0][1]} 를 줄 노드 없음(가지치기 — 아카이브 노드 필요)"
                            cv.notify_all()
                            return
                        cv.wait(timeout=1.0)
                a, b = ch
                try:
                    hh = None
                    if self.head_guard and url not in self.head_off and _EP_HEAD_OFF.get(url, 0) <= time.time():
                        try:
                            hh = self._known_head(url, b)
                            self.head_fail[url] = 0
                        except Exception as e9:
                            self.head_fail[url] = self.head_fail.get(url, 0) + 1
                            if self.head_fail[url] < 3:
                                raise
                            self.head_off.add(url)
                            _EP_HEAD_OFF[url] = time.time() + EP_HEAD_OFF_SEC
                            if self.log:
                                self.log.warning("%s %s 헤드 조회 %d연속 실패 — 이번 스캔은 헤드 가드 없이(종전 동작): %s", self.name,
                                                 _url_host(url), self.head_fail[url], str(e9)[:100])
                        if hh is not None and hh < b:
                            with cv:
                                inflight.discard((a, b))
                                if hh >= a:
                                    requeue([[hh + 1, b]])
                                    b = hh
                                    inflight.add((a, b))
                                    self.metrics["lag_clip"] += 1
                                else:
                                    requeue([[a, b]])
                                self.lag_head[url] = (hh, time.time())
                                cv.notify_all()
                            if hh < a:
                                if self.log:
                                    self.log.info("%s %s 헤드 %d < 청크 시작 %d — 그 노드엔 아직 없는 블록(다른 노드·다음 사이클)", self.name,
                                                  _url_host(url), hh, a)
                                continue
                    f = {}
                    for pos in sorted(self.positions):
                        self.metrics["calls"] += 1
                        rows = self._query(url, a, b, pos)
                        for lg in rows:
                            h = (lg.get("transactionHash") or "").lower()
                            if not h:
                                continue
                            try:
                                blk = int(lg.get("blockNumber"), 16)
                            except (TypeError, ValueError):
                                blk = b
                            f[h] = blk
                        if self.sleep:
                            time.sleep(self.sleep)
                    with cv:
                        inflight.discard((a, b))
                        done[a] = (b, f)
                        advance_locked()
                        cv.notify_all()
                except Exception as e:
                    err = classify_exc(e) if not isinstance(e, NetError) else e
                    with cv:
                        inflight.discard((a, b))
                        self.metrics["errors"] += 1
                        if err.kind == "range":
                            if err.cap and err.cap < (b - a + 1):
                                self.caps[url] = err.cap
                                self.metrics["range_split"] += 1
                                requeue([[a, b]])
                            elif (b - a + 1) > (1 if getattr(err, "results", False) else self.min_span):
                                mid = (a + b) // 2
                                if not getattr(err, "results", False):
                                    self.caps[url] = max(self.min_span, (b - a + 1) // 2)
                                self.metrics["halved"] += 1
                                requeue([[a, mid], [mid + 1, b]])
                            else:
                                st["stop"] = common.redact_secret_text(f"{_url_host(url)} 최소 구간({self.min_span})도 거부: {err}")
                        elif err.kind == "timeout" and (b - a + 1) > self.min_span:
                            mid = (a + b) // 2
                            self.metrics["halved"] += 1
                            requeue([[a, mid], [mid + 1, b]])
                        elif err.kind == "pruned":
                            self.pruned_below[url] = max(self.pruned_below.get(url, -1), b)
                            self.metrics["pruned"] += 1
                            requeue([[a, b]])
                        else:
                            requeue([[a, b]])
                        cv.notify_all()
                    if self.log and err.kind not in ("range",):
                        self.log.info("%s %s %d-%d %s — 재배치", self.name,
                                      urllib.parse.urlsplit(url).hostname, a, b, str(err)[:120])
                    if err.kind not in ("range", "pruned", "timeout"):
                        time.sleep(min(5.0, 0.5 + random.random()))

        threads = []
        for u in all_eps:
            for _k in range(self.per_ep_workers):
                t = threading.Thread(target=worker, args=(u,), daemon=True, name=f"scan-{u[-12:]}")
                threads.append(t)
                t.start()
        for t in threads:
            t.join()
        with cv:
            advance_locked()
            found = {h: b for h, b in st["found"].items() if b <= st["last"]}
            if st["stop"] and self.log:
                self.log.warning("%s 스캔 중단: %s (연속 완료 %d)", self.name, st["stop"], st["last"])
            self.last_stop = st["stop"]
            return found, st["last"]


STATUS_FILE = "backfill_status.json"


class Progress:

    def __init__(self, unit: str, min_interval: float = 5.0):
        self.unit = unit
        self.path = os.path.join(common.STATE_DIR, STATUS_FILE)
        self.min_interval = min_interval
        self.items = {}
        self._hist = {}
        self._last_flush = 0.0
        self.lock = threading.Lock()

    def update(self, key: str, *, done=None, total=None, phase=None, unit=None, errors=None,
               note=None, flush: bool = False, **extra):
        now = time.time()
        with self.lock:
            it = self.items.setdefault(key, {"started": int(now)})
            prev_phase, prev_done = it.get("phase"), it.get("done")
            if done is not None:
                it["done"] = done
                h = self._hist.setdefault(key, [])
                h.append((now, float(done)))
                del h[:-20]
                if len(h) >= 2 and h[-1][0] - h[0][0] > 0:
                    rate = (h[-1][1] - h[0][1]) / (h[-1][0] - h[0][0])
                    it["rate"] = round(rate, 4)
                    tot = total if total is not None else it.get("total")
                    if tot is not None and rate > 0:
                        it["eta_sec"] = int(max(0.0, (float(tot) - float(done)) / rate))
                    elif rate <= 0:
                        it.pop("eta_sec", None)
            if total is not None:
                it["total"] = total
            if phase is not None:
                if it.get("phase") != phase:
                    flush = True
                it["phase"] = phase
            if unit is not None:
                it["unit"] = unit
            if errors:
                e = it.setdefault("errors", {})
                for k, v in errors.items():
                    e[k] = e.get(k, 0) + int(v)
            if note is not None:
                it["note"] = common.redact_urls(common.redact_secret_text(str(note), generic=False))[:200]
            it.update(extra)
            it["updated"] = int(now)
            if "moved_at" not in it or (done is not None and done != prev_done) or (phase is not None and phase != prev_phase):
                it["moved_at"] = int(now)
            if it.get("phase") == "done":
                if prev_phase != "done" or "done_at" not in it:
                    it["done_at"] = int(now)
            else:
                it.pop("done_at", None)
        if flush or now - self._last_flush >= self.min_interval:
            self.flush()

    def finish(self, key: str, note: str = None):
        self.update(key, phase="done", note=note, flush=True, eta_sec=0)

    def drop(self, key: str):
        with self.lock:
            self.items.pop(key, None)
        self.flush()

    def flush(self):
        self._last_flush = time.time()
        with self.lock:
            mine = json.loads(json.dumps(self.items))
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path + ".lock", "a+") as lk:
                fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
                try:
                    try:
                        with open(self.path, "r", encoding="utf-8") as f:
                            cur = json.load(f)
                        if not isinstance(cur, dict):
                            cur = {}
                    except (FileNotFoundError, ValueError):
                        cur = {}
                    cur[self.unit] = mine
                    cur, _n9 = common.scrub_secrets(cur, ("note",))
                    cur["_updated"] = int(time.time())
                    common.atomic_write_json(self.path, cur)
                finally:
                    fcntl.flock(lk.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass


def scrub_status_file() -> int:
    path = os.path.join(common.STATE_DIR, STATUS_FILE)
    try:
        with open(path + ".lock", "a+") as lk:
            fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
            try:
                return common.scrub_secret_file(path, ("note",))
            finally:
                fcntl.flock(lk.fileno(), fcntl.LOCK_UN)
    except OSError:
        return 0


def read_status() -> dict:
    try:
        with open(os.path.join(common.STATE_DIR, STATUS_FILE), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def fmt_eta(sec) -> str:
    if sec is None:
        return "?"
    sec = int(sec)
    if sec < 90:
        return f"{sec}s"
    if sec < 5400:
        return f"{sec // 60}m"
    return f"{sec / 3600:.1f}h"


_PROGRESS = {}
_PROGRESS_LOCK = threading.Lock()


def progress(unit: str) -> Progress:
    with _PROGRESS_LOCK:
        p = _PROGRESS.get(unit)
        if p is None:
            p = _PROGRESS[unit] = Progress(unit)
        return p


HEALTH_DIR = "health"
HEALTH_SCHEMA = 1


class Health:

    def __init__(self, unit: str):
        self.unit = unit
        self.path = os.path.join(common.STATE_DIR, HEALTH_DIR, f"{unit}.json")
        self.lock = threading.Lock()
        self.src = {}
        self.started = int(time.time())

    def _s(self, key: str, kind: str = None) -> dict:
        s = self.src.setdefault(key, {"kind": kind, "ok": None, "last_cycle_ts": None, "last_success_ts": None,
                                      "consecutive_failures": 0, "last_error": None})
        if kind:
            s["kind"] = kind
        return s

    def facts(self, key: str, kind: str = None, **kv):
        with self.lock:
            s = self._s(key, kind)
            for k, v in kv.items():
                if isinstance(v, str):
                    v = common.redact_secret_text(v, generic=False)
                s[k] = v
            if s.get("head_ts"):
                try:
                    s["head_age_sec"] = int(time.time() - float(s["head_ts"]))
                except (TypeError, ValueError):
                    pass

    def ok(self, key: str, kind: str = None, **kv):
        with self.lock:
            s = self._s(key, kind)
            now = int(time.time())
            s.update(ok=True, last_cycle_ts=now, last_success_ts=now, consecutive_failures=0)
        self.facts(key, kind, **kv)

    def fail(self, key: str, err, kind: str = None, **kv) -> int:
        with self.lock:
            s = self._s(key, kind)
            now = int(time.time())
            s["ok"] = False
            s["last_cycle_ts"] = now
            s["consecutive_failures"] = int(s.get("consecutive_failures") or 0) + 1
            ek = getattr(err, "kind", None) or type(err).__name__
            s["last_error"] = {"ts": now, "kind": ek, "msg": common.redact_secret_text(str(err))[:300]}
            n = s["consecutive_failures"]
        self.facts(key, kind, **kv)
        return n

    def flush(self):
        with self.lock:
            src = json.loads(json.dumps(self.src, default=str))
        net = {}
        now = time.time()
        for h, st in stats_snapshot().items():
            g = _GATES.get(h)
            net[h] = dict(st, circuit_open_sec=max(0, int(g.open_until - now)) if g else 0)
        doc = {"schema": HEALTH_SCHEMA, "unit": self.unit, "ts": int(now), "pid": os.getpid(),
               "started": self.started, "ok": all(v.get("ok") is not False for v in src.values()) if src else None,
               "sources": src, "net": net}
        try:
            common.atomic_write_json(self.path, doc)
        except Exception:
            pass


_HEALTH = {}


def health(unit: str) -> Health:
    with _PROGRESS_LOCK:
        h = _HEALTH.get(unit)
        if h is None:
            h = _HEALTH[unit] = Health(unit)
        return h


class LogDebounce:

    @staticmethod
    def level(n: int):
        if n in (10, 100) or (n > 100 and n % 500 == 0):
            return "error"
        if n == 3 or (n > 3 and n % 20 == 0):
            return "warning"
        if n <= 2:
            return "info"
        return None


def wallet_since_map(cfg: dict, chain: str) -> dict:
    out = {}
    for w in (cfg or {}).get("wallets") or []:
        if not isinstance(w, dict) or w.get("chain") != chain or w.get("type") == "sol":
            continue
        t = parse_date_ts(w.get("backfill_since"))
        a = str(w.get("address") or "").lower()
        if t and a:
            out[a] = min(t, out.get(a, t))
    return out


def parse_date_ts(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return int(v)
    try:
        import datetime as _dt
        return int(_dt.datetime.strptime(str(v)[:10], "%Y-%m-%d").replace(tzinfo=_dt.timezone.utc).timestamp())
    except ValueError:
        return None


class _SinceSource:
    def __init__(self):
        self.lock = threading.Lock()
        self.cache = {}

    def _load(self, path):
        try:
            mt = os.path.getmtime(path)
        except OSError:
            return {}
        with self.lock:
            c = self.cache.get(path)
            if c and c[0] == mt:
                return c[1]
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        with self.lock:
            self.cache[path] = (mt, d if isinstance(d, dict) else {})
        return self.cache[path][1]

    def _section(self, cfg: dict, section: str):
        if not section:
            return {}
        if section in ("bsc", "sol"):
            return cfg.get(section) or {}
        if section in ((cfg.get("chains") or {})):
            return cfg["chains"][section] or {}
        return ((cfg.get("exchanges") or {}).get(section)) or {}

    def target(self, section: str = None):
        cfg = self._load(common.CONFIG_PATH)
        req = self._load(os.path.join(common.STATE_DIR, "backfill_request.json"))
        vals = [parse_date_ts(cfg.get("backfill_since")), parse_date_ts(self._section(cfg, section).get("backfill_since")),
                parse_date_ts(req.get("since")), parse_date_ts((req.get("per") or {}).get(section) if section else None)]
        vals = [v for v in vals if v]
        return min(vals) if vals else None

    def covered_hint(self, section: str = None):
        cfg = self._load(common.CONFIG_PATH)
        v = parse_date_ts(self._section(cfg, section).get("covered_since")) or parse_date_ts(cfg.get("backfill_covered_since"))
        return v


SINCE = _SinceSource()


def effective_backfill_t0(cfg: dict, now: float = None) -> int:
    now = time.time() if now is None else now
    months = float(cfg.get("backfill_months") or 0)
    t = now - months * 30 * 86400 if months > 0 else 0
    s = SINCE.target(None)
    return int(min(t, s) if s else t)
