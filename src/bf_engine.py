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
HTTP_MAX_BYTES = 32 * 1024 * 1024
HTTP_ERR_MAX_BYTES = 64 * 1024


def _url_host(url) -> str:
    try:
        return urllib.parse.urlsplit(str(url)).hostname or "(주소 숨김)"
    except ValueError:
        return "(주소 숨김)"


class NetError(RuntimeError):

    def __init__(self, msg: str, kind: str, code=None, retry_after=None, cap=None, host=None, earliest=None):
        super().__init__(common.redact_secret_text(msg))
        self.kind = kind
        self.code = code
        self.retry_after = retry_after
        self.cap = cap
        self.host = host
        self.earliest = earliest
        self.latest = None


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


_NUM = r"(0x[0-9a-f]+|\d+)"
_RETENTION_RES = (
    re.compile(r"not contained in the inclusion range\s*\[\s*" + _NUM + r"(?:\s*,\s*" + _NUM + r")?", re.I),
    re.compile(r"lowest height is\s*" + _NUM, re.I),
    re.compile(r"(?:earliest|oldest|first) (?:available|retained|indexed)(?: (?:block|height))?(?: number)?\s*(?:is|:|=)?\s*" + _NUM, re.I),
)


def _num(v):
    if v is None:
        return None
    try:
        n = int(v, 16) if v.lower().startswith("0x") else int(v)
    except ValueError:
        return None
    return n if n > 0 else None


def retention_bounds(msg) -> tuple:
    s = str(msg or "")
    for rx in _RETENTION_RES:
        m = rx.search(s)
        if m:
            lo = _num(m.group(1))
            hi = _num(m.group(2)) if m.re.groups >= 2 else None
            if lo is not None and (hi is None or hi >= lo):
                return lo, hi
    return None, None


def classify_rpc_error(err) -> NetError:
    if isinstance(err, dict):
        code, msg = err.get("code"), str(err.get("message") or err)
        d9 = err.get("data")
        if isinstance(d9, str) and d9.strip() and d9 not in msg:
            msg = f"{msg} — {d9}"
    else:
        code, msg = None, str(err)
    low = msg.lower()
    text = f"rpc-error {code}: {msg[:160]}"
    e9, h9 = retention_bounds(msg)
    if e9 is not None:
        r9 = NetError(text, "pruned", code=code, earliest=e9)
        r9.latest = h9
        return r9
    if "header not found" in low or "missing trie node" in low or "pruned" in low \
            or "history has been pruned" in low or "block not found" in low \
            or ("historical state" in low and ("not available" in low or "unavailable" in low)) \
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
    mc9 = re.search(r"(?:limited to a|up to a|maximum)\s+(\d{1,7})\s+(?:block\s+)?(?:range|blocks)\b", low)
    if mc9 and int(mc9.group(1)) > 0:
        return NetError(text, "range", code=code, cap=int(mc9.group(1)))
    mc8 = (re.search(r"spans \d+ blocks.{0,80}?but only (\d{1,7}) are allowed", low) or re.search(r"\brange \d+ exceeds limit of (\d{1,7})", low)
           or re.search(r"max block range (\d{1,7})", low) or re.search(r"block range greater than (\d{1,7}) max", low)
           or re.search(r"blocks distance:?\s*(\d{1,7})", low))
    if mc8 and int(mc8.group(1)) > 0:
        return NetError(text, "range", code=code, cap=int(mc8.group(1)))
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


RPC_NEAR_HEAD = 256
_FAIL_TRANSIENT = ("quota", "budget", "circuit", "http429", "http5xx", "timeout", "conn", "dns", "payload")
_FAIL_TRANSIENT_MSG = ("timeout", "timed out", "deadline exceeded", "execution aborted", "context canceled", "canceled due to", "request was canceled",
                       "too many requests", "rate limit", "ratelimit", "request limit reached", "compute units per second", "request rate exceeded",
                       "daily request count exceeded", "busy", "try again", "temporarily", "temporary", "service unavailable", "resource unavailable",
                       "overloaded", "over capacity", "internal error", "internal server error", "bad gateway", "gateway timeout", "upstream",
                       "not synced", "syncing")
_FAIL_EXEC = ("execution reverted", "reverted", "revert", "vm execution error", "out of gas", "invalid opcode", "bad instruction", "badinstruction",
              "invalid jump", "stack underflow", "stack limit reached", "stack overflow", "stackunderflow", "stackoverflow", "write protection",
              "gas uint64 overflow", "return data out of bounds", "gas required exceeds allowance")
_FAIL_PERM_MSG = ("required historical state unavailable", "method not found", "does not exist/is not available", "not whitelisted",
                  "not supported", "unsupported", "method not available")
_FAIL_AMBIG = ("header not found", "block not found", "unknown block")
_ERRDICT_RE = re.compile(r"\{['\"]code['\"]:\s*(-?\d+),\s*['\"]message['\"]:\s*['\"]([^'\"]*)")


def _fail_neterr(x):
    if isinstance(x, NetError):
        return x
    net9 = getattr(x, "net", None)
    if isinstance(net9, NetError):
        return net9
    if isinstance(x, urllib.error.HTTPError):
        return classify_exc(x)
    if isinstance(x, dict):
        return classify_rpc_error(x)
    if isinstance(x, (OSError, TimeoutError)):
        return NetError(f"conn: {str(x)[:160]}", "conn")
    if isinstance(x, ValueError):
        return NetError(f"payload: {str(x)[:160]}", "payload")
    s9 = str(x)
    m9 = _ERRDICT_RE.search(s9)
    if m9:
        return classify_rpc_error({"code": int(m9.group(1)), "message": m9.group(2)})
    return classify_rpc_error(s9)


def _fail_class_one(x, block, head) -> str:
    if isinstance(x, str):
        return "permanent"
    if isinstance(x, (TypeError, KeyError, AttributeError, IndexError)):
        return "permanent"
    n9 = _fail_neterr(x)
    k9, msg9, code9 = n9.kind, str(n9).lower(), getattr(n9, "code", None)
    if k9 in _FAIL_TRANSIENT:
        return "transient"
    if k9 == "http4xx":
        return "transient" if code9 in (408, 425) else "permanent"
    if k9 == "null":
        return "permanent"
    if any(p in msg9 for p in _FAIL_PERM_MSG) and not any(p in msg9 for p in ("timeout", "timed out", "rate limit", "too many")):
        return "permanent"
    if k9 == "pruned":
        if any(p in msg9 for p in _FAIL_AMBIG):
            h9 = None
            try:
                h9 = head() if callable(head) else head
            except Exception:
                h9 = None
            if block is None or h9 is None:
                return "transient"
            return "transient" if int(h9) - int(block) <= RPC_NEAR_HEAD else "permanent"
        return "permanent"
    if k9 == "range":
        return "permanent" if any(w in msg9 for w in ("range", "block", "result", "logs", "response size", "distance")) else "transient"
    if any(p in msg9 for p in _FAIL_TRANSIENT_MSG):
        return "transient"
    if code9 == 3 or any(p in msg9 for p in _FAIL_EXEC):
        return "exec"
    return "transient"


def rpc_fail_class(e, block: int = None, head=None) -> str:
    items = list(getattr(e, "errs", None) or [e])
    got = {_fail_class_one(x, block, head) for x in items}
    for c9 in ("transient", "exec", "permanent"):
        if c9 in got:
            return c9
    return "permanent"


def classify_exc(e: BaseException, host: str = None, body_bytes: bytes = None) -> NetError:
    if isinstance(e, NetError):
        return e
    if isinstance(e, urllib.error.HTTPError):
        code = e.code
        body = ""
        try:
            body = ((body_bytes if body_bytes is not None else e.read(HTTP_ERR_MAX_BYTES)) or b"")[:300].decode("utf-8", "replace")
        except Exception:
            pass
        ra = retry_after_sec(e.headers.get("Retry-After") if e.headers else None)
        msg = f"HTTP Error {code}: {e.reason}" + (f" ({body.strip()[:120]})" if body.strip() else "")
        if code == 429:
            kind = "quota" if ("max usage" in body.lower() or "quota" in body.lower()) else "http429"
            return NetError(msg, kind, code=code, retry_after=ra, host=host)
        if 500 <= code < 600:
            return NetError(msg, "http5xx", code=code, retry_after=ra, host=host)
        if code in (400, 413) and body:
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
    "rpc1.monad.xyz": {"rate": 2.0, "burst": 2, "conc": 1, "call_rate": 5.0, "call_burst": 6},
    "rpc2.monad.xyz": {"rate": 2.0, "burst": 2, "conc": 1, "call_rate": 15.0, "call_burst": 10},
    "rpc.monad.xyz": {"rate": 4.0, "burst": 4, "conc": 2, "call_rate": 8.0, "call_burst": 10},
    "rpc.plasma.to": {"rate": 2.0, "burst": 2, "conc": 1},
    "xlayerrpc.okx.com": {"rate": 2.0, "burst": 2, "conc": 1, "call_rate": 15.0, "call_burst": 15},
    "rpc.xlayer.tech": {"rate": 2.0, "burst": 2, "conc": 1, "call_rate": 15.0, "call_burst": 15},
    "rpc.stable.xyz": {"rate": 4.0, "burst": 4, "conc": 2, "call_rate": 40.0, "call_burst": 40},
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
    "bsc-mainnet.nodereal.io": {"rate": 2.0, "burst": 1, "conc": 2, "call_rate": 1.4, "call_burst": 1,
                                "share": "node_nodereal", "share_rate": 1.4, "share_burst": 1, "share_xproc": True},
    "rpc.ankr.com": {"rate": 6.0, "burst": 6, "conc": 3, "call_rate": 12.0, "call_burst": 12,
                     "share": "node_ankr", "share_rate": 12.0, "share_burst": 12, "share_xproc": True},
    "*.quiknode.pro": {"rate": 5.0, "burst": 5, "conc": 3, "call_rate": 10.0, "call_burst": 10,
                       "share": "node_quicknode", "share_rate": 10.0, "share_burst": 10, "share_xproc": True},
    "*.g.alchemy.com": {"rate": 2.0, "burst": 2, "conc": 2, "call_rate": 2.0, "call_burst": 2,
                        "share": "node_alchemy", "share_rate": 2.0, "share_burst": 2, "share_xproc": True},
    "rpc.ankr.com#adv": {"rate": 0.6, "burst": 2, "conc": 1, "call_rate": 0.6, "call_burst": 2,
                         "share": "node_ankr_adv", "share_rate": 0.6, "share_burst": 2, "share_xproc": True},
    "bsc.rpc.blxrbdn.com": {"rate": 2.0, "burst": 2, "conc": 2},
    "rpc-bsc.48.club": {"rate": 2.0, "burst": 2, "conc": 2},
    "*.bnbchain.org": {"rate": 4.0, "burst": 4, "conc": 3},
    "bsc.rpc.sentio.xyz": {"rate": 1.0, "burst": 2, "conc": 1},
    "rpc.mainnet.chain.robinhood.com": {"rate": 2.0, "burst": 2, "conc": 1},
    "robinhood.drpc.org": {"rate": 2.0, "burst": 2, "conc": 1, "call_rate": 6.0, "call_burst": 3,
                           "share": "drpc", "share_rate": 25.0, "share_burst": 50},
    "mainnet.base.org": {"rate": 1.0, "burst": 1, "conc": 1, "call_rate": 5.0, "call_burst": 10},
    "gateway.tenderly.co": {"rate": 2.0, "burst": 2, "conc": 1, "call_rate": 5.0, "call_burst": 10},
    "base.drpc.org": {"rate": 2.0, "burst": 2, "conc": 1, "call_rate": 6.0, "call_burst": 3, "share": "drpc", "share_rate": 25.0, "share_burst": 50},
    "rpc.mainnet.arc.io": {"rate": 2.0, "burst": 2, "conc": 1},
    "rpc.quicknode.mainnet.arc.io": {"rate": 2.0, "burst": 2, "conc": 1},
    "rpc.blast.io": {"rate": 2.0, "burst": 2, "conc": 1, "call_rate": 7.0, "call_burst": 8},
    "*.drpc.org": {"rate": 2.0, "burst": 2, "conc": 1, "call_rate": 6.0, "call_burst": 3, "share": "drpc", "share_rate": 25.0, "share_burst": 50},
    "rpc.mevblocker.io": {"rate": 2.0, "burst": 2, "conc": 1, "call_rate": 10.0, "call_burst": 10},
    "arb1.arbitrum.io": {"rate": 3.0, "burst": 3, "conc": 2, "call_rate": 10.0, "call_burst": 10},
    "mainnet.optimism.io": {"rate": 3.0, "burst": 3, "conc": 2, "call_rate": 10.0, "call_burst": 10},
    "rpc.scroll.io": {"rate": 2.0, "burst": 2, "conc": 1, "call_rate": 10.0, "call_burst": 10},
    "mainnet.era.zksync.io": {"rate": 3.0, "burst": 3, "conc": 2, "call_rate": 3.0, "call_burst": 4},
    "rpc.gnosischain.com": {"rate": 2.0, "burst": 2, "conc": 1, "call_rate": 10.0, "call_burst": 10},
    "rpc.gnosis.gateway.fm": {"rate": 2.0, "burst": 2, "conc": 1, "call_rate": 10.0, "call_burst": 10},
    "mainnet.megaeth.com": {"rate": 3.0, "burst": 3, "conc": 2, "call_rate": 12.0, "call_burst": 12},
    "mainnet.storyrpc.io": {"rate": 2.0, "burst": 2, "conc": 1, "call_rate": 10.0, "call_burst": 10},
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


class _SharedBucket:

    def __init__(self, name: str, rate, burst):
        self.name = name
        self.rate = _pol_num(rate, 0.0, float, 0.0, 10000.0)
        self.burst = _pol_num(burst, self.rate, float, 1.0, 10000.0) if self.rate else 0.0
        self.tokens = self.burst
        self.t_last = time.monotonic()
        self.lock = threading.Lock()

    def _refill(self):
        now_m = time.monotonic()
        self.tokens = min(self.burst, self.tokens + (now_m - self.t_last) * self.rate)
        self.t_last = now_m

    def peek(self, cost: int = 1) -> float:
        if not self.rate:
            return 0.0
        with self.lock:
            self._refill()
            need = min(float(cost), self.burst)
            return 0.0 if self.tokens >= need else (need - self.tokens) / self.rate

    def try_take(self, cost: int = 1) -> float:
        if not self.rate:
            return 0.0
        with self.lock:
            self._refill()
            need = min(float(cost), self.burst)
            if self.tokens < need:
                return (need - self.tokens) / self.rate
            self.tokens -= float(max(1, cost))
            return 0.0


class _XprocSharedBucket(_SharedBucket):

    def _io(self, cost: int, take: bool) -> float:
        with self.lock:
            try:
                d = os.path.join(common.quota_dir(), "rpc_gap")
                os.makedirs(d, exist_ok=True)
                fd = os.open(os.path.join(d, re.sub(r"[^a-z0-9_]", "_", self.name)[:40] + ".bucket"), os.O_RDWR | os.O_CREAT, 0o600)
            except OSError as e:
                raise NetError(f"budget: {self.name} 공유 버킷 파일 열기 실패 — 보내지 않음({type(e).__name__})", "budget", host=self.name)
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return 0.02
                except OSError as e:
                    raise NetError(f"budget: {self.name} 공유 버킷 잠금 실패 — 보내지 않음({type(e).__name__})", "budget", host=self.name)
                try:
                    now = time.monotonic()
                    raw = os.pread(fd, 256, 0)
                    try:
                        st = json.loads(raw.decode("ascii"))
                        at, tok = float(st["at"]), float(st["tokens"])
                        if not (0.0 <= at <= now + 1.0 and -100000.0 <= tok <= self.burst):
                            raise ValueError("bucket")
                    except (ValueError, TypeError, KeyError, UnicodeDecodeError):
                        at, tok = now, (0.0 if raw else self.burst)
                    tok = min(self.burst, tok + max(0.0, now - at) * self.rate)
                    need = min(float(cost), self.burst)
                    w = 0.0 if tok >= need else (need - tok) / self.rate
                    if take:
                        if w <= 0:
                            tok -= float(max(1, cost))
                        b = json.dumps({"at": now, "tokens": tok}).encode("ascii")
                        os.ftruncate(fd, 0)
                        if os.pwrite(fd, b, 0) != len(b):
                            raise OSError("short write")
                    self.tokens, self.t_last = tok, now
                    return w
                except OSError as e:
                    raise NetError(f"budget: {self.name} 공유 버킷 읽기·기록 실패 — 보내지 않음({type(e).__name__})", "budget", host=self.name)
                finally:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_UN)
                    except OSError:
                        pass
            finally:
                os.close(fd)

    def peek(self, cost: int = 1) -> float:
        if not self.rate:
            return 0.0
        try:
            return self._io(cost, False)
        except NetError:
            return 1.0

    def try_take(self, cost: int = 1) -> float:
        if not self.rate:
            return 0.0
        return self._io(cost, True)


_SHARES = {}
_SHARES_LOCK = threading.Lock()


def _share_bucket(name: str, rate, burst, xproc: bool = False):
    with _SHARES_LOCK:
        b = _SHARES.get(name)
        if b is None:
            b = _SHARES[name] = (_XprocSharedBucket if xproc else _SharedBucket)(name, rate, burst)
        return b


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
        sh9 = str(pol.get("share") or "").strip().lower()
        self.share = _share_bucket(sh9, pol.get("share_rate"), pol.get("share_burst"), bool(pol.get("share_xproc"))) if sh9 else None

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
        cap = int(default)
        if self.call_rate:
            cap = max(1, min(cap, int(self.call_burst)))
        if self.share is not None and self.share.rate:
            cap = max(1, min(cap, int(self.share.burst)))
        return cap

    def acquire(self, prio: str = "fg", deadline: float = None, cost: int = 1):
        if deadline is None and isinstance(self.share, _XprocSharedBucket):
            deadline = time.time() + HG_LOCK_WAIT
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
                    if w <= 0 and self.share is not None:
                        w = self.share.try_take(cost)
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

    def resting(self) -> bool:
        now = time.time()
        return self.open_until > now or self.pause_until > now


_GATES = {}
_GATES_LOCK = threading.Lock()
_POLICY_OVERRIDES = {}


ES_DAILY_BUDGET = 80000
ESB_FLUSH_EVERY = 20
_ESB = {"day": None, "n": 0, "nh": 0, "flushed": 0, "others": 0, "others_h": 0, "others_at": 0.0, "yday_h": None, "fq": 0.0, "others_fq": 0}
_ESB_LOCK = threading.Lock()


def _esb_dir() -> str:
    return os.path.join(common.quota_dir(), "es_budget")


_ESB_INST = os.urandom(4).hex()

ESB_HIST = "head_days.hist"
ESB_HIST_KEEP_DAYS = 3


def _esb_rec_head(j: dict) -> int:
    try:
        return int((j.get("nh") if "nh" in j else j.get("n")) or 0)
    except (TypeError, ValueError):
        return 0


def _esb_rec_fq(j: dict) -> int:
    try:
        return int(j.get("fq") or 0)
    except (TypeError, ValueError):
        return 0


def _esb_hist_read(d: str) -> dict:
    try:
        with open(os.path.join(d, ESB_HIST), "r", encoding="utf-8") as f:
            j = json.load(f)
        return j if isinstance(j, dict) and isinstance(j.get("days"), dict) else {"days": {}}
    except (OSError, ValueError):
        return {"days": {}}


def _esb_hist_merge(d: str, add: dict, today: int) -> bool:
    try:
        with open(os.path.join(d, "hist.lock"), "a+b") as lk:
            fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
            try:
                return _esb_hist_merge_locked(d, add, today)
            finally:
                fcntl.flock(lk.fileno(), fcntl.LOCK_UN)
    except OSError:
        return False


def _hist_load(d: str):
    p9 = os.path.join(d, ESB_HIST)
    try:
        with open(p9, "r", encoding="utf-8") as f:
            j = json.load(f)
    except FileNotFoundError:
        return {"days": {}}, "missing"
    except (OSError, ValueError):
        return {"days": {}}, "bad"
    if not isinstance(j, dict) or not isinstance(j.get("days"), dict):
        return {"days": {}}, "bad"
    return j, "ok"


def _hist_keep_bad(d: str):
    try:
        os.replace(os.path.join(d, ESB_HIST), os.path.join(d, f"{ESB_HIST}.bad.{int(time.time())}"))
    except OSError:
        pass


def _esb_hist_merge_locked(d: str, add: dict, today: int, keep: int = None) -> bool:
    try:
        if keep is not None:
            h, st9 = _hist_load(d)
            if st9 == "bad":
                _hist_keep_bad(d)
        else:
            h = _esb_hist_read(d)
        days = h["days"]
        if keep is not None and int(keep) >= RPC_DAY_WINDOW:
            k9 = h.get("k31")
            if isinstance(k9, int) and not isinstance(k9, bool):
                later9 = [int(k) for k in days if str(k).lstrip("-").isdigit() and int(k) > k9]
                if later9:
                    s9 = h.get("since") if isinstance(h.get("since"), int) and not isinstance(h.get("since"), bool) else None
                    h["since"] = max(s9 if s9 is not None else -10 ** 9, max(later9) + 1)
            h["k31"] = int(today)
        for day, recs in add.items():
            cur = days.get(str(int(day)))
            if not isinstance(cur, dict):
                cur = days[str(int(day))] = {}
            for stem, (nh, n) in recs.items():
                try:
                    o0, o1 = int(cur[stem][0] or 0), int(cur[stem][1] or 0)
                except (KeyError, IndexError, TypeError, ValueError):
                    o0 = o1 = 0
                cur[stem] = [max(o0, int(nh)), max(o1, int(n))]
        for k in [k for k in days if not str(k).lstrip("-").isdigit() or int(k) < today - (ESB_HIST_KEEP_DAYS if keep is None else int(keep))]:
            days.pop(k, None)
        common.atomic_write_json(os.path.join(d, ESB_HIST), dict(h, days=days) if keep is not None else {"days": days})
        return True
    except (OSError, TypeError, ValueError):
        return False


def es_head_on(d: str, day: int):
    recs = _esb_hist_read(d)["days"].get(str(int(day)))
    if not isinstance(recs, dict) or not recs:
        return None
    tot = 0
    for v in recs.values():
        if isinstance(v, list) and v and isinstance(v[0], int):
            tot += v[0]
    return tot


def _esb_roll(day: int):
    prev, proc = _ESB["day"], _ESB.get("last_proc")
    if prev is not None and proc and (_ESB["n"] or _ESB["nh"]):
        _esb_hist_merge(_esb_dir(), {prev: {f"{proc}.{os.getpid()}.{_ESB_INST}": [_ESB["nh"], _ESB["n"]]}}, day)
    _ESB.update(day=day, n=0, nh=0, flushed=0, others=0, others_h=0, others_at=0.0, yday_h=None, others_fq=0)


def _esb_sync(proc: str, now: float):
    d = _esb_dir()
    try:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "hist.lock"), "a+b") as lk:
            fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
            try:
                _esb_sync_locked(d, proc, now)
            finally:
                fcntl.flock(lk.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    _ESB["others_at"] = now


def _esb_sync_locked(d: str, proc: str, now: float):
    me = f"{proc}.{os.getpid()}.{_ESB_INST}.json"
    try:
        rec9 = {"day": _ESB["day"], "n": _ESB["n"], "nh": _ESB["nh"], "fq": int(_ESB["fq"]), "proc": proc, "pid": os.getpid(), "inst": _ESB_INST, "at": int(now)}
        if _ESB.get("closed"):
            rec9["closed"] = True
        common.atomic_write_json(os.path.join(d, me), rec9)
        _ESB["flushed"] = _ESB["n"]
        tot = toth = fq9 = 0
        old9 = {}
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
                toth += _esb_rec_head(j)
                fq9 = max(fq9, _esb_rec_fq(j))
                if not j.get("closed"):
                    tot += ESB_FLUSH_EVERY
            elif isinstance(j.get("day"), int) and j["day"] < _ESB["day"]:
                old9[f] = j
        if old9:
            add9 = {}
            for f, j in old9.items():
                add9.setdefault(j["day"], {})[f[:-5]] = [_esb_rec_head(j), int(j.get("n") or 0)]
            if _esb_hist_merge_locked(d, add9, _ESB["day"]):
                for f in old9:
                    try:
                        os.remove(os.path.join(d, f))
                    except OSError:
                        pass
        _ESB["others"] = tot
        _ESB["others_h"] = toth
        _ESB["others_fq"] = fq9
        _ESB["yday_h"] = es_head_on(d, _ESB["day"] - 1)
    except OSError:
        pass


ES_PACE_BURST_FRAC = 0.04
ES_FILL_KEEP_FRAC = 0.02
ES_FILL_KEEP_MIN = 0.01
ES_HEAD_MULT = 1.25
ES_HEAD_MIN_FRAC = 0.10
ES_HEAD_MAX_FRAC = 0.70
ES_HEAD_EARLY = 0.10
ES_FILL_HEAD_MIN_FRAC = 0.03
ES_FILL_ACTIVE_SEC = 3600
ES_KINDS = ("head", "fill", "aux")
_ESB_WHY = threading.local()


def es_head_share(head_used: float, yday_head, now: float, budget: float = None, fill_active: bool = False, floor: float = None,
                  base: float = None) -> int:
    b = float(ES_DAILY_BUDGET if budget is None else budget)
    bb = b if base is None else float(base)
    fl = _es_floor(fill_active, floor)
    e = (now % 86400) / 86400.0
    m = max(float(yday_head or 0), float(head_used or 0) / max(e, ES_HEAD_EARLY))
    return int(min(b * ES_HEAD_MAX_FRAC, max(bb * fl, m * ES_HEAD_MULT)))


def _es_floor(fill_active: bool, floor: float = None) -> float:
    if floor is not None:
        return float(floor)
    return ES_FILL_HEAD_MIN_FRAC if fill_active else ES_HEAD_MIN_FRAC


def es_fill_active(fq: float, now: float) -> bool:
    try:
        return float(fq or 0) > 0 and now - float(fq) <= ES_FILL_ACTIVE_SEC
    except (TypeError, ValueError):
        return False


def es_rooms(used: float, head_used: float, yday_head, now: float, budget: float = None, burst: float = None, keep: float = None,
             fill_active: bool = False, floor: float = None, base: float = None) -> dict:
    b = float(ES_DAILY_BUDGET if budget is None else budget)
    bb = b if base is None else float(base)
    fl = _es_floor(fill_active, floor)
    bu = float(ES_PACE_BURST_FRAC if burst is None else burst)
    kp = float(ES_FILL_KEEP_FRAC if keep is None else keep)
    if bu >= 1.0:
        left = int(b - used)
        return {"head": left, "fill": left, "rt": None, "fillFirst": False, "off": True}
    e = (now % 86400) / 86400.0
    r = es_head_share(head_used, yday_head, now, b, fill_active, fl, base=bb)
    spent9 = max(0.0, float(used) - float(head_used or 0)) + min(float(head_used or 0), r * e)
    affordable = (b - spent9 - bb * max(kp, ES_FILL_KEEP_MIN)) / max(1.0 - e, 1e-9)
    r = min(r, max(int(bb * fl), int(affordable)))
    resv = r * (1.0 - e)
    head = b - used - resv
    fill = head - bb * max(kp, ES_FILL_KEEP_MIN)
    return {"head": int(head), "fill": int(fill), "rt": r, "fillFirst": bool(fill_active), "off": False}


def es_pace_room(kind: str = "head", now: float = None) -> int:
    now = time.time() if now is None else now
    day = int(now // 86400)
    with _ESB_LOCK:
        if kind == "fill":
            _ESB["fq"] = now
        if _ESB["day"] == day:
            used, hu, yd, fq = _ESB["n"] + _ESB["others"], _ESB["nh"] + _ESB["others_h"], _ESB["yday_h"], max(_ESB["fq"], _ESB["others_fq"])
        else:
            used, hu, yd, fq = 0, 0, None, _ESB["fq"]
    return es_rooms(used, hu, yd, now, fill_active=es_fill_active(fq, now))["fill" if kind in ("fill", "aux") else "head"]


def es_ledger_read(now: float = None, d: str = None) -> dict:
    now = time.time() if now is None else now
    day = int(now // 86400)
    d = d or _esb_dir()
    n = nh = fq = 0
    hm9 = None
    try:
        for f in os.listdir(d):
            if f.endswith(".json"):
                try:
                    j = common.read_json(os.path.join(d, f), {})
                except (Exception, SystemExit):
                    continue
                if isinstance(j, dict) and j.get("day") == day:
                    n += int(j.get("n") or 0)
                    nh += _esb_rec_head(j)
                    fq = max(fq, _esb_rec_fq(j))
                    hm9 = _hm_pick(hm9, j, now)
    except (OSError, TypeError, ValueError):
        pass
    return {"n": n, "nh": nh, "fq": fq, "ydayHead": es_head_on(d, day - 1), "hm": hm9[1] if hm9 else None}


def es_ledger_rooms(now: float = None, budget: float = None, burst: float = None, keep: float = None) -> dict:
    now = time.time() if now is None else now
    L = es_ledger_read(now)
    r = es_rooms(L["n"], L["nh"], L["ydayHead"], now, budget, burst, keep, fill_active=es_fill_active(L["fq"], now))
    return dict(L, **r)


def es_budget_why() -> str:
    return getattr(_ESB_WHY, "v", "")


def es_budget_take(proc: str, now: float = None, kind: str = "head") -> bool:
    now = time.time() if now is None else now
    day = int(now // 86400)
    _ESB_WHY.v = ""
    k = kind if kind in ES_KINDS else "head"
    with _ESB_LOCK:
        if _ESB["day"] != day:
            _esb_roll(day)
        if now - _ESB["others_at"] > 30 or _ESB["n"] - _ESB["flushed"] >= ESB_FLUSH_EVERY:
            _esb_sync(proc, now)
        used = _ESB["n"] + _ESB["others"]
        if used >= ES_DAILY_BUDGET:
            if _ESB["n"] != _ESB["flushed"]:
                _esb_sync(proc, now)
            _ESB_WHY.v = "day"
            return False
        if k == "fill":
            _ESB["fq"] = now
        fa = es_fill_active(max(_ESB["fq"], _ESB["others_fq"]), now)
        if es_rooms(used, _ESB["nh"] + _ESB["others_h"], _ESB["yday_h"], now, fill_active=fa)["fill" if k == "aux" else k] <= 0:
            _ESB_WHY.v = "pace"
            _ESB["paced"] = int(_ESB.get("paced") or 0) + 1
            return False
        _ESB["n"] += 1
        if k == "head":
            _ESB["nh"] += 1
        _ESB["last_proc"] = proc
        return True


def es_budget_flush(closed: bool = False):
    if not _ESB_LOCK.acquire(timeout=1.0):
        return
    try:
        if _ESB["day"] is None:
            return
        proc = _ESB.get("last_proc")
        if not proc:
            return
        _ESB["closed"] = bool(closed)
        _esb_sync(proc, time.time())
    finally:
        _ESB_LOCK.release()


def _esb_atexit():
    try:
        es_budget_flush(closed=True)
    except Exception:
        pass


__import__("atexit").register(_esb_atexit)


def es_budget_install_sigterm():
    import signal

    def _h(signum, _frame):
        _esb_atexit()
        _hl_atexit()
        _rpc_day_atexit()
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)
    try:
        signal.signal(signal.SIGTERM, _h)
    except (ValueError, OSError):
        pass


HL_KINDS = ("head", "fill", "aux", "must")
HL_FLUSH_EVERY = 20
HM_FRESH_SEC = 900


def _hm_pick(cur, j: dict, now: float):
    try:
        hm, at = j.get("hm"), float(j.get("at") or 0)
    except (TypeError, ValueError):
        return cur
    if isinstance(hm, bool) or not isinstance(hm, (int, float)) or not 0.0 < float(hm) <= 1.0 or j.get("closed") or now - at > HM_FRESH_SEC:
        return cur
    if cur is None or at > cur[0]:
        return (at, float(hm))
    return cur


class DayMeter:

    def __init__(self, sub: str, budget: int, burst: float = 0.04, keep: float = 0.02, fill_first: bool = False, head_min: float = None):
        self.sub, self.budget, self.burst, self.keep = sub, int(budget), float(burst), float(keep)
        self.fill_first = bool(fill_first)
        self.head_min = ES_HEAD_MIN_FRAC if head_min is None else float(head_min)
        self.st = {"day": None, "n": 0, "nh": 0, "fq": 0.0, "flushed": 0, "others": 0, "others_h": 0, "others_fq": 0,
                   "others_at": 0.0, "yday_h": None, "paced": 0}
        self.lock = threading.Lock()
        self.inst = os.urandom(4).hex()
        self.why = threading.local()
        self.proc = None
        self._hist_pend = {}
        self.hm_pub = False
        self.hist_keep = 0
        self.month_cap = None
        self.flex_x = 0.0
        self.fresh_svc = None

    def _hkeep(self):
        return max(int(self.hist_keep or 0), ESB_HIST_KEEP_DAYS)

    def _dir(self) -> str:
        return os.path.join(common.quota_dir(), self.sub)

    def keep_credits(self) -> int:
        return int(self.budget * max(self.keep, ES_FILL_KEEP_MIN))

    def fill_cap_fresh(self) -> int:
        return int(self.budget - int(self.budget * self.head_min) - self.keep_credits())

    def _sync(self, now: float) -> bool:
        d = self._dir()
        ok = True
        me = f"{self.proc}.{os.getpid()}.{self.inst}.json"
        try:
            os.makedirs(d, exist_ok=True)
            if (self.fill_first or self.hist_keep) and self._hist_pend and isinstance(self.st["day"], int):
                if _esb_hist_merge_locked(d, {dy: {me[:-5]: v} for dy, v in self._hist_pend.items()}, self.st["day"], keep=self._hkeep()):
                    self._hist_pend.clear()
            rec9 = {"day": self.st["day"], "n": self.st["n"], "nh": self.st["nh"], "fq": int(self.st["fq"] or 0),
                    "proc": self.proc, "pid": os.getpid(), "inst": self.inst, "at": int(now)}
            if self.hm_pub:
                rec9["hm"] = round(float(self.head_min), 5)
            if self.st.get("closed"):
                rec9["closed"] = True
            common.atomic_write_json(os.path.join(d, me), rec9)
            self.st["flushed"] = self.st["n"]
            tot = toth = fq9 = 0
            hm9 = None
            old9 = {}
            for f in os.listdir(d):
                if not f.endswith(".json") or f == me:
                    continue
                try:
                    j = common.read_json(os.path.join(d, f), None)
                except (Exception, SystemExit):
                    j = None
                if not isinstance(j, dict):
                    ok = False
                    continue
                if j.get("day") == self.st["day"]:
                    tot += int(j.get("n") or 0)
                    toth += _esb_rec_head(j)
                    fq9 = max(fq9, _esb_rec_fq(j))
                    hm9 = _hm_pick(hm9, j, now)
                    if not j.get("closed"):
                        tot += HL_FLUSH_EVERY
                elif isinstance(j.get("day"), int) and j["day"] < self.st["day"]:
                    old9[f] = j
            if old9:
                done9 = True
                if self.fill_first or self.hist_keep:
                    add9 = {}
                    for f, j in old9.items():
                        add9.setdefault(j["day"], {})[f[:-5]] = [_esb_rec_head(j), int(j.get("n") or 0)]
                    done9 = _esb_hist_merge_locked(d, add9, self.st["day"], keep=self._hkeep())
                if done9:
                    for f in old9:
                        try:
                            os.remove(os.path.join(d, f))
                        except OSError:
                            pass
            self.st["others"] = tot
            self.st["others_h"] = toth
            self.st["others_fq"] = fq9
            self.st["others_hm"] = hm9
            if self.fill_first:
                self.st["yday_h"] = es_head_on(d, self.st["day"] - 1)
        except (OSError, TypeError, ValueError):
            return False
        self.st["others_at"] = now
        return ok

    def _locked_sync(self, now: float) -> bool:
        try:
            os.makedirs(self._dir(), exist_ok=True)
            with open(os.path.join(self._dir(), "reserve.lock"), "a+b") as lk:
                fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
                try:
                    return self._sync(now)
                finally:
                    fcntl.flock(lk.fileno(), fcntl.LOCK_UN)
        except OSError:
            return False

    def window_on(self) -> bool:
        return bool(self.fill_first and self.month_cap and float(self.flex_x or 0) >= 1.0)

    _flex_on = window_on

    def eff_budget(self, now: float):
        if not self._flex_on():
            return None
        fd9 = None
        if self.fresh_svc:
            try:
                import nodekeys
                fd9 = nodekeys.fresh_day(str(self.fresh_svc))
            except Exception:
                fd9 = None
        used, head = self.st["n"] + self.st["others"], self.st["nh"] + self.st["others_h"]
        try:
            F = month_flex(self._dir(), now, self.budget, int(self.month_cap), head, fd9)
        except (OSError, TypeError, ValueError):
            F = None
        if F is None:
            return None
        if float(self.flex_x) <= 1.0:
            d9 = max(0, int(min(self.budget, F["room"])))
            return (d9, d9)
        bh = max(0, int(min(F["room"], used - head + self.budget)))
        bf = max(0, int(min(self.budget * float(self.flex_x), F["ahead"])))
        return (bh, bf)

    def take_hard(self, proc: str, n: int = 1, kind: str = "head", now: float = None) -> bool:
        k = kind if kind in HL_KINDS else "head"
        ix = 1 if k in ("fill", "aux") else 0

        def lim(now9):
            eb9 = self.eff_budget(now9)
            return self.budget if eb9 is None else eb9[ix]
        return self.take(proc, n, kind=k, now=now, limit=lim)

    def _room(self, kind: str, used: int, now: float, budget=None) -> int:
        if budget is not None and self.fill_first:
            b9 = budget[1] if kind in ("fill", "aux") else budget[0]
            if kind == "must":
                return int(b9 - used)
            r = es_rooms(used, self.st["nh"] + self.st["others_h"], self.st["yday_h"], now, budget=b9, burst=self.burst, keep=self.keep,
                         fill_active=es_fill_active(max(float(self.st["fq"] or 0), float(self.st["others_fq"] or 0)), now), floor=self.floor_now(now),
                         base=self.budget)
            return int(r["fill" if kind in ("fill", "aux") else "head"])
        if not self.fill_first:
            if self.burst >= 1.0:
                return int(self.budget - used)
            line = self.budget * ((now % 86400) / 86400.0)
            if kind in ("fill", "aux"):
                lim = line - self.budget * self.keep
            elif kind == "must":
                lim = self.budget
            else:
                lim = line + self.budget * self.burst
            return int(min(lim, self.budget) - used)
        if kind == "must":
            return int(self.budget - used)
        r = es_rooms(used, self.st["nh"] + self.st["others_h"], self.st["yday_h"], now, budget=self.budget, burst=self.burst, keep=self.keep,
                     fill_active=es_fill_active(max(float(self.st["fq"] or 0), float(self.st["others_fq"] or 0)), now), floor=self.floor_now(now))
        return int(r["fill" if kind in ("fill", "aux") else "head"])

    def floor_now(self, now: float = None) -> float:
        if self.hm_pub:
            return float(self.head_min)
        hm9 = self.st.get("others_hm")
        now = time.time() if now is None else now
        if hm9 and now - float(hm9[0]) <= HM_FRESH_SEC:
            return float(hm9[1])
        return float(self.head_min)

    def _roll(self, now: float):
        day = int(now // 86400)
        if self.st["day"] != day:
            prev = self.st["day"]
            if (self.fill_first or self.hist_keep) and prev is not None and self.proc and (self.st["n"] or self.st["nh"]):
                self._hist_pend[prev] = [int(self.st["nh"]), int(self.st["n"])]
            self.st.update(day=day, n=0, nh=0, flushed=0, others=0, others_h=0, others_fq=0, others_hm=None, others_at=0.0, yday_h=None, paced=0)

    def room(self, kind: str = "head", now: float = None, proc: str = None) -> int:
        now = time.time() if now is None else now
        with self.lock:
            if proc:
                self.proc = proc
            self._roll(now)
            if self.fill_first and kind == "fill":
                self.st["fq"] = now
            if self.proc and now - self.st["others_at"] > 30:
                self._locked_sync(now)
            return self._room(kind if kind in HL_KINDS else "head", self.st["n"] + self.st["others"], now, budget=self.eff_budget(now))

    def take(self, proc: str, n: int = 1, kind: str = "head", now: float = None, limit: int = None) -> bool:
        now = time.time() if now is None else now
        self.why.v = ""
        k = kind if kind in HL_KINDS else "head"
        with self.lock:
            self.proc = proc
            self._roll(now)
            try:
                os.makedirs(self._dir(), exist_ok=True)
                lk = open(os.path.join(self._dir(), "reserve.lock"), "a+b")
            except OSError:
                self.why.v = "io"
                return False
            try:
                fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
                if not self._sync(now):
                    self.why.v = "io"
                    return False
                used = self.st["n"] + self.st["others"]
                lim9 = limit(now) if callable(limit) else limit
                eb9 = self.eff_budget(now) if lim9 is None else None
                db9 = self.budget if eb9 is None else eb9[1 if k in ("fill", "aux") else 0]
                if used + n > (db9 if lim9 is None else max(0, int(lim9))):
                    self.why.v = "day"
                    return False
                if self.fill_first and k == "fill":
                    self.st["fq"] = now
                if limit is None and self._room(k, used, now, budget=eb9) < n:
                    self.why.v = "pace"
                    self.st["paced"] += 1
                    return False
                h9 = n if k in ("head", "must") else 0
                self.st["n"] += n
                self.st["nh"] += h9
                if not self._sync(now):
                    self.st["n"] -= n
                    self.st["nh"] -= h9
                    self.why.v = "io"
                    return False
                return True
            except OSError:
                self.why.v = "io"
                return False
            finally:
                try:
                    fcntl.flock(lk.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
                lk.close()

    def add(self, proc: str, n: int = 1, now: float = None, kind: str = "head"):
        now = time.time() if now is None else now
        k = kind if kind in HL_KINDS else "head"
        with self.lock:
            self.proc = proc
            self._roll(now)
            self.st["n"] += int(n)
            if k in ("head", "must"):
                self.st["nh"] += int(n)
            elif k == "fill" and self.fill_first:
                self.st["fq"] = now
            self._locked_sync(now)

    def day_capped(self, now: float = None) -> bool:
        now = time.time() if now is None else now
        with self.lock:
            self._roll(now)
            ok = self._locked_sync(now)
            eb9 = self.eff_budget(now)
            return (not ok) or self.st["n"] + self.st["others"] >= (self.budget if eb9 is None else max(eb9))

    def last_why(self) -> str:
        return getattr(self.why, "v", "")

    def used(self, now: float = None) -> tuple:
        now = time.time() if now is None else now
        with self.lock:
            self._roll(now)
            return self.st["n"] + self.st["others"], self.budget

    def flush(self, closed: bool = False):
        if not self.lock.acquire(timeout=1.0):
            return
        try:
            if self.st["day"] is None or not self.proc:
                return
            self.st["closed"] = bool(closed)
            self._locked_sync(time.time())
        finally:
            self.lock.release()


def ledger_rooms(sub: str, budget: float, burst: float = None, keep: float = None, now: float = None, floor: float = None, flex: dict = None) -> dict:
    now = time.time() if now is None else now
    d9 = os.path.join(common.quota_dir(), sub)
    L = es_ledger_read(now, d=d9)
    fl = L["hm"] if L.get("hm") is not None else floor
    eb9 = None
    if isinstance(flex, dict) and flex.get("cap") and float(flex.get("x") or 0) >= 1.0:
        try:
            m9 = DayMeter(sub, int(budget), fill_first=True)
            m9.month_cap, m9.flex_x, m9.fresh_svc = int(flex["cap"]), float(flex["x"]), "helius" if sub == "helius_budget" else None
            m9.st.update(day=int(now // 86400), n=int(L["n"]), nh=int(L["nh"]))
            eb9 = m9.eff_budget(now)
        except Exception:
            eb9 = None
    fa9 = es_fill_active(L["fq"], now)
    if eb9 is None:
        r = es_rooms(L["n"], L["nh"], L["ydayHead"], now, budget, burst, keep, fill_active=fa9, floor=fl)
        return dict(L, **r, floorUsed=fl, dayCap=int(budget))
    r = es_rooms(L["n"], L["nh"], L["ydayHead"], now, eb9[0], burst, keep, fill_active=fa9, floor=fl, base=budget)
    rf = es_rooms(L["n"], L["nh"], L["ydayHead"], now, eb9[1], burst, keep, fill_active=fa9, floor=fl, base=budget)
    return dict(L, **dict(r, fill=rf["fill"]), floorUsed=fl, dayCap=int(max(eb9)), fillCap=int(eb9[1]))


HELIUS_MONTHLY_DEFAULT = 1_000_000


def helius_day_budget(cfg: dict) -> int:
    try:
        m = float(((cfg or {}).get("sol") or {}).get("helius_monthly_credits") or HELIUS_MONTHLY_DEFAULT)
    except (TypeError, ValueError):
        m = float(HELIUS_MONTHLY_DEFAULT)
    try:
        pct = min(100.0, max(1.0, float(((cfg or {}).get("addr_tier") or {}).get("budget_pct") or 80)))
    except (TypeError, ValueError):
        pct = 80.0
    return max(100, int(m * pct / 100.0 / 31.0))


HELIUS = DayMeter("helius_budget", helius_day_budget({}), fill_first=True)


HELIUS_HEAD_MIN_PCT = 10.0


def helius_head_min(cfg: dict) -> float:
    try:
        v = ((cfg or {}).get("sol") or {}).get("helius_head_min_pct")
        pct = float(HELIUS_HEAD_MIN_PCT if v is None else v)
    except (TypeError, ValueError):
        pct = HELIUS_HEAD_MIN_PCT
    return min(70.0, max(1.0, pct)) / 100.0


HELIUS_HEAD_MIN_PN_PCT = 3.0


def helius_head_min_pn(cfg: dict, head_used: float, yday_head, now: float, budget: float) -> float:
    hi = helius_head_min(cfg)
    try:
        v = ((cfg or {}).get("sol") or {}).get("helius_head_min_pct_pn")
        lo = float(HELIUS_HEAD_MIN_PN_PCT if v is None else v) / 100.0
    except (TypeError, ValueError):
        lo = HELIUS_HEAD_MIN_PN_PCT / 100.0
    lo = min(hi, max(0.01, lo))
    e = (now % 86400) / 86400.0
    m = max(float(yday_head or 0), float(head_used or 0) / max(e, ES_HEAD_EARLY))
    return min(hi, max(lo, m * ES_HEAD_MULT / max(1.0, float(budget))))


HG_LOCK_WAIT = 30.0
_HG_LOCAL = threading.Lock()


def host_gap_wait(host: str, method: str = None, gap: float = 0.0, method_gap: float = 0.0, deadline: float = None):
    gap, method_gap = max(0.0, float(gap or 0)), max(0.0, float(method_gap or 0))
    if gap <= 0 and method_gap <= 0:
        return
    key = re.sub(r"[^A-Za-z0-9_.-]", "_", str(host or "x"))[:80] or "x"
    with _HG_LOCAL:
        try:
            d = os.path.join(common.quota_dir(), "rpc_gap")
            os.makedirs(d, exist_ok=True)
            fd = os.open(os.path.join(d, key + ".slot"), os.O_RDWR | os.O_CREAT, 0o600)
        except OSError as e:
            raise NetError(f"budget: {key} 공유 간격 파일 열기 실패 — 보내지 않음({type(e).__name__})", "budget", host=key)
        try:
            t_lock = time.time()
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.time() - t_lock > HG_LOCK_WAIT or (deadline is not None and time.time() >= deadline):
                        raise NetError(f"budget: {key} 공유 간격 잠금 대기 초과", "budget", host=key)
                    time.sleep(0.02)
                except OSError as e:
                    raise NetError(f"budget: {key} 공유 간격 잠금 실패 — 보내지 않음({type(e).__name__})", "budget", host=key)
            try:
                now = time.time()
                try:
                    st = json.loads(os.pread(fd, 8192, 0).decode("utf-8", "replace") or "{}")
                    st = st if isinstance(st, dict) else {"*": now}
                except ValueError:
                    st = {"*": now, str(method or "*")[:64]: now}

                def _t(k):
                    try:
                        v = float(st.get(k) or 0)
                    except (TypeError, ValueError):
                        v = now
                    return now if v > now + 5 else v

                wait = max(_t("*") + gap, (_t(method) + method_gap) if method else 0.0) - now
                if wait > 0:
                    if deadline is not None and now + wait > deadline:
                        raise NetError(f"budget: {key} 공유 간격 대기가 마감을 넘음", "budget", host=key)
                    time.sleep(wait)
                t9 = time.time()
                st = {k: v for k, v in st.items() if isinstance(v, (int, float)) and t9 - float(v) < 3600}
                st["*"] = t9
                if method:
                    st[str(method)[:64]] = t9
                b = json.dumps(st).encode()
                os.ftruncate(fd, 0)
                os.pwrite(fd, b, 0)
            except OSError as e:
                raise NetError(f"budget: {key} 공유 간격 읽기·기록 실패 — 보내지 않음({type(e).__name__})", "budget", host=key)
            finally:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            os.close(fd)


SOL_HELIUS_RPS = 8.0
SOL_HELIUS_DAS_GAP = 1.0
SOL_HELIUS_GPA_GAP = 0.25
SOL_HELIUS_DAS = frozenset({"das", "getAsset", "getAssetBatch", "getAssetsByOwner", "getAssetsByGroup", "getAssetsByCreator", "getAssetsByAuthority",
                            "searchAssets", "getAssetProof", "getAssetProofBatch", "getSignaturesForAsset", "getTokenAccounts", "getNftEditions"})
SOL_ARCHIVE_HOSTS = ("api.mainnet-beta.solana.com", "api.mainnet.solana.com")
_SOL_METER = {"helius": 1.0 / SOL_HELIUS_RPS, "head": ("solana-rpc.publicnode.com", 0.1), "archive": (set(SOL_ARCHIVE_HOSTS), 10.0 / 32, 10.0 / 8),
              "other": (set(), 0.125)}


def _host_norm(url) -> str:
    try:
        return (urllib.parse.urlsplit(str(url or "").strip()).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def sol_meter_configure(cfg: dict):
    sol = (cfg or {}).get("sol") or {}

    def f(k, d, lo, hi):
        try:
            v = sol.get(k)
            x = float(d if v is None else v)
        except (TypeError, ValueError):
            x = float(d)
        return min(hi, max(lo, x)) if x == x else float(d)
    hu = sol.get("head_rpc", "https://solana-rpc.publicnode.com")
    head_h = _host_norm(hu) if isinstance(hu, str) and hu.strip() else ""
    au = sol.get("archive_rpc", "https://api.mainnet-beta.solana.com")
    arch = set(SOL_ARCHIVE_HOSTS)
    if isinstance(au, str) and au.strip():
        arch.add(_host_norm(au))
    arch.discard("")
    other = {_host_norm(u) for u in [sol.get("rpc_fallback")] + list(sol.get("rpc_fallbacks") or []) + list(((cfg or {}).get("balance_check") or {}).get("sol_rpcs") or [])
             if isinstance(u, str) and u.strip()}
    other -= arch | {head_h, ""}
    other = {h for h in other if not (h == "helius-rpc.com" or h.endswith(".helius-rpc.com"))}
    _SOL_METER_SET[0] = True
    _SOL_METER.update(helius=1.0 / f("helius_rps", SOL_HELIUS_RPS, 0.5, 1000),
                      head=(head_h or "solana-rpc.publicnode.com", f("head_rpc_gap_ms", 100, 0, 10000) / 1000.0),
                      archive=(arch, 10.0 / f("archive_rpc_per10s", 32, 1, 1000), 10.0 / f("archive_rpc_method_per10s", 8, 1, 1000)),
                      other=(other, f("rpc_other_gap_ms", 125, 0, 10000) / 1000.0))


def sol_meter_class(url):
    h = _host_norm(url)
    if not h:
        return None
    if h == "helius-rpc.com" or h.endswith(".helius-rpc.com"):
        return h, "helius", _SOL_METER["helius"], 0.0
    hits = []
    if h in _SOL_METER["archive"][0]:
        hits.append(("archive", _SOL_METER["archive"][1], _SOL_METER["archive"][2]))
    if h == _SOL_METER["head"][0]:
        hits.append(("head", _SOL_METER["head"][1], 0.0))
    if h in _SOL_METER["other"][0]:
        hits.append(("other", _SOL_METER["other"][1], 0.0))
    if not hits:
        return None
    return h, "+".join(x[0] for x in hits), max(x[1] for x in hits), max(x[2] for x in hits)


_SOL_METER_SET = [False]


def _sol_meter_ensure():
    if not _SOL_METER_SET[0]:
        _SOL_METER_SET[0] = True
        try:
            sol_meter_configure(common.load_config())
        except (Exception, SystemExit):
            pass


def rpc_gap(url, method: str = None, deadline: float = None, sol: bool = False):
    _sol_meter_ensure()
    c = sol_meter_class(url)
    if c is None and sol:
        h9 = _host_norm(url)
        c = (h9, "other", _SOL_METER["other"][1], 0.0) if h9 else None
    if c is None:
        return
    h, _cls, gap, mgap = c
    mkey = (str(method) if method else None) if mgap > 0 else None
    if _cls == "helius" and method:
        if str(method) in SOL_HELIUS_DAS:
            mkey, mgap = "_helius_das", max(mgap, SOL_HELIUS_DAS_GAP)
        elif str(method) == "getProgramAccounts":
            mkey, mgap = "getProgramAccounts", max(mgap, SOL_HELIUS_GPA_GAP)
    host_gap_wait(h, mkey, gap * 1.002, mgap * 1.002, deadline)


def _rpc_methods_of(data) -> list:
    try:
        d = json.loads(data.decode("utf-8") if isinstance(data, (bytes, bytearray)) else data) if isinstance(data, (bytes, bytearray, str)) else data
    except (ValueError, UnicodeDecodeError):
        return [None]
    if isinstance(d, dict):
        return [d.get("method")]
    if isinstance(d, list) and d:
        return [x.get("method") if isinstance(x, dict) else None for x in d]
    return [None]


def sol_open(req, timeout, method: str = None, deadline: float = None, sol: bool = False):
    url = req.full_url if hasattr(req, "full_url") else str(req)
    _sol_meter_ensure()
    if sol or sol_meter_class(url) is not None:
        for m9 in ([method] if method else _rpc_methods_of(getattr(req, "data", None))):
            rpc_gap(url, m9, deadline, sol=sol)
    return urllib.request.urlopen(req, timeout=timeout)


def is_helius_rpc(sol_cfg: dict) -> bool:
    v = str((sol_cfg or {}).get("rpc") or "")
    if v == "helius":
        return True
    h = (urllib.parse.urlsplit(v).hostname or "").lower() if "://" in v else ""
    return h == "helius-rpc.com" or h.endswith(".helius-rpc.com")


def helius_configure(cfg: dict):
    es9 = (cfg or {}).get("etherscan") or {}
    try:
        burst = max(0.0, float(es9.get("pace_burst_pct", 4))) / 100.0
        keep = min(50.0, max(0.0, float(es9.get("fill_keep_pct", 2)))) / 100.0
    except (TypeError, ValueError):
        burst, keep = 0.04, 0.02
    fx9 = helius_flex(cfg)
    with HELIUS.lock:
        HELIUS.budget = helius_day_budget(cfg)
        HELIUS.burst, HELIUS.keep = burst, keep
        HELIUS.head_min = helius_head_min(cfg)
        HELIUS.month_cap = fx9["cap"] if fx9 else None
        HELIUS.flex_x = fx9["x"] if fx9 else 0.0
        HELIUS.fresh_svc = "helius" if fx9 else None
        HELIUS.hist_keep = RPC_DAY_WINDOW if fx9 else 0
    if fx9:
        _hist_since_ensure(HELIUS._dir(), int(time.time() // 86400))


def helius_flex(cfg: dict):
    sol9 = (cfg or {}).get("sol") or {}
    on9 = sol9.get("helius_burst") is not False
    try:
        m = float(sol9.get("helius_monthly_credits") or HELIUS_MONTHLY_DEFAULT)
        pct = min(100.0, max(1.0, float(((cfg or {}).get("addr_tier") or {}).get("budget_pct") or 80)))
    except (TypeError, ValueError):
        return None
    x = 1.0
    if on9 and m <= HELIUS_MONTHLY_DEFAULT:
        try:
            import nodekeys
            x = max(1.0, float(nodekeys.BURST_X))
        except Exception:
            x = 1.0
    return {"cap": int(m * pct / 100.0), "x": x}


def _hl_atexit():
    try:
        HELIUS.flush(closed=True)
    except Exception:
        pass


__import__("atexit").register(_hl_atexit)


RPC_DAY_MONTH_DAYS = 31.0
RPC_DAY_DEFAULT = {
    "drpc": {"hosts": ["*.drpc.org"], "unit": "cu", "month": 210_000_000, "cu": 20, "cu_heavy": 300},
    "tenderly": {"hosts": ["gateway.tenderly.co"], "unit": "bytes", "day": 1_000_000_000, "max_resp": 2_000_000},
}
RPC_DAY_MAX_RESP = 2_000_000
_RPC_DAY = {}
_RPC_DAY_LOCK = threading.Lock()
_RPC_DAY_PROC = os.path.splitext(os.path.basename((__import__("sys").argv or ["py"])[0] or "py"))[0] or "py"


def _rpc_day_pct(cfg: dict) -> float:
    try:
        v = (cfg or {}).get("rpc_day_pct")
        if v is None:
            v = ((cfg or {}).get("addr_tier") or {}).get("budget_pct") or 80
        return min(100.0, max(1.0, float(v)))
    except (TypeError, ValueError):
        return 80.0


def rpc_day_configure(cfg: dict):
    over = (cfg or {}).get("rpc_day_limits") if isinstance((cfg or {}).get("rpc_day_limits"), dict) else {}
    pct = _rpc_day_pct(cfg)
    with _RPC_DAY_LOCK:
        old = dict(_RPC_DAY)
        _RPC_DAY.clear()
        for name in list(dict.fromkeys(list(RPC_DAY_DEFAULT) + list(over))):
            ov = over.get(name)
            if ov is False:
                continue
            spec = dict(RPC_DAY_DEFAULT.get(name) or {}, **(ov if isinstance(ov, dict) else {}))
            if not spec.get("hosts") or spec.get("unit") not in ("cu", "bytes", "calls"):
                continue
            try:
                per_day = float(spec["day"]) if spec.get("day") else float(spec["month"]) / RPC_DAY_MONTH_DAYS
                pct_e = min(100.0, max(1.0, float(spec["pct"]))) if spec.get("pct") is not None else pct
            except (KeyError, TypeError, ValueError):
                continue
            budget = max(1, int(per_day * pct_e / 100.0))
            prev = old.get(name)
            if prev is not None and prev["spec"].get("unit") == spec.get("unit"):
                m9 = prev["meter"]
                with m9.lock:
                    m9.budget = budget
            else:
                m9 = DayMeter(f"rpc_day_{name}", budget, burst=1.0, keep=0.0)
            m9.proc = m9.proc or _RPC_DAY_PROC
            m9.hist_keep = RPC_DAY_WINDOW if _win_spec(spec) else 0
            if m9.hist_keep:
                _hist_since_ensure(m9._dir(), int(time.time() // 86400))
            _RPC_DAY[name] = {"spec": spec, "meter": m9, "pct": pct_e, "refused": prev.get("refused", 0) if prev else 0}


def _rpc_day_of(host: str):
    h = (host or "").lower()
    with _RPC_DAY_LOCK:
        for name, ent in _RPC_DAY.items():
            for p in ent["spec"].get("hosts") or ():
                p = str(p).lower()
                if h == p or (p.startswith("*.") and (h.endswith(p[1:]) or h == p[2:])):
                    return name
    return None


def rpc_day_unit(name: str):
    with _RPC_DAY_LOCK:
        ent = _RPC_DAY.get(name)
        return ent["spec"].get("unit") if ent else None


def _rpc_day_units(name: str, methods=None, cost: int = 1) -> int:
    with _RPC_DAY_LOCK:
        ent = _RPC_DAY.get(name)
        spec = ent["spec"] if ent else {}
        bud = ent["meter"].budget if ent else 1
    u = spec.get("unit")
    if u == "bytes":
        try:
            mx = int(spec.get("max_resp") or RPC_DAY_MAX_RESP)
        except (TypeError, ValueError):
            mx = RPC_DAY_MAX_RESP
        return max(1, min(mx, bud))
    if u == "calls":
        return max(1, int(cost))
    cu, heavy = int(spec.get("cu") or 20), int(spec.get("cu_heavy") or spec.get("cu") or 20)
    cm = spec.get("cu_methods") if isinstance(spec.get("cu_methods"), dict) else {}
    cp = spec.get("cu_prefix") if isinstance(spec.get("cu_prefix"), dict) else {}
    ms = list(methods or [])
    if not ms:
        return max(cu, max((int(v) for v in cm.values()), default=cu)) * max(1, int(cost))

    def one(m):
        m = str(m)
        if cm.get(m):
            return int(cm[m])
        for pre, v in cp.items():
            if m.startswith(str(pre)):
                return int(v)
        return heavy if m.startswith(("debug_", "trace_")) else cu
    return sum(one(m) for m in ms)


RPC_DAY_WINDOW = 31
RPC_RT_MARGIN = 1.5
RPC_RT_FLOOR = 0.05
RPC_RT_LOOKBACK = 7
_BURST_TL = threading.local()


def _hist_since_ensure(d: str, today: int):
    try:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "reserve.lock"), "a+b") as lk:
            fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
            try:
                h, st9 = _hist_load(d)
                if st9 == "ok" and isinstance(h.get("since"), int) and not isinstance(h.get("since"), bool):
                    return
                if st9 == "bad":
                    _hist_keep_bad(d)
                    h = {"days": {}}
                common.atomic_write_json(os.path.join(d, ESB_HIST), dict(h, since=int(today)))
            finally:
                fcntl.flock(lk.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def _win_spec(spec) -> bool:
    sp = spec or {}
    return bool(_burst_x(sp)) or bool(sp.get("window") and sp.get("month") and not sp.get("day"))


def _burst_x(spec) -> float:
    try:
        x = float((spec or {}).get("burst") or 0)
    except (TypeError, ValueError):
        return 0.0
    return x if x > 1.0 and (spec or {}).get("month") and not (spec or {}).get("day") else 0.0


class ledger_burst:

    def __init__(self, on: bool = True):
        self.on = bool(on)

    def __enter__(self):
        self.prev = getattr(_BURST_TL, "on", False)
        _BURST_TL.on = self.on
        return self

    def __exit__(self, *a):
        _BURST_TL.on = self.prev
        return False


def burst_on() -> bool:
    return bool(getattr(_BURST_TL, "on", False))


def _rpc_day_prev_used(d: str, today: int, n_day: int = 0, fresh_day: int = None, rt_out: dict = None, day_out: dict = None):
    lo = today - (RPC_DAY_WINDOW - 1)
    per = {}
    perh = {}
    h9, st9 = _hist_load(d)
    if st9 == "bad":
        return None
    since = h9.get("since") if isinstance(h9.get("since"), int) and not isinstance(h9.get("since"), bool) else None
    for k, recs in (h9.get("days") or {}).items():
        try:
            day = int(k)
        except (TypeError, ValueError):
            continue
        if lo <= day < today and isinstance(recs, dict):
            for stem, v in recs.items():
                try:
                    n9 = int(v[1])
                except (IndexError, TypeError, ValueError):
                    continue
                per[(day, stem)] = max(per.get((day, stem), 0), n9)
                try:
                    perh[(day, stem)] = max(perh.get((day, stem), 0), min(n9, int(v[0])))
                except (IndexError, TypeError, ValueError):
                    perh[(day, stem)] = max(perh.get((day, stem), 0), n9)
    try:
        names = os.listdir(d)
    except OSError:
        names = []
    for f in names:
        if not f.endswith(".json"):
            continue
        try:
            j = common.read_json(os.path.join(d, f), None)
            day = j.get("day") if isinstance(j, dict) else None
            if isinstance(day, int) and lo <= day < today:
                per[(day, f[:-5])] = max(per.get((day, f[:-5]), 0), int(j.get("n") or 0))
                perh[(day, f[:-5])] = max(perh.get((day, f[:-5]), 0), min(int(j.get("n") or 0), _esb_rec_head(j)))
        except (Exception, SystemExit):
            continue
    if rt_out is not None:
        for (day, _s), v in perh.items():
            rt_out[day] = rt_out.get(day, 0) + max(0, v)
    seen = {day for day, _s in per}
    unk = [day for day in range(lo, today) if day not in seen and not (since is not None and day >= since)
           and not (fresh_day is not None and day < fresh_day)]
    if day_out is not None:
        for (day, _s), v in per.items():
            day_out[day] = day_out.get(day, 0) + max(0, v)
        for day in unk:
            day_out[day] = max(0, int(n_day))
    return sum(max(0, v) for v in per.values()) + len(unk) * max(0, int(n_day))


def rpc_day_limits(name: str, now: float = None) -> dict:
    now = time.time() if now is None else now
    with _RPC_DAY_LOCK:
        ent = _RPC_DAY.get(name)
    if ent is None:
        return {}
    return _rpc_day_lims(ent, now)


def month_flex(d: str, now: float, base: int, cap: int, head: int, fresh_day: int = None):
    today = int(now // 86400)
    rtd, dd = {}, {}
    prev = _rpc_day_prev_used(d, today, base, fresh_day, rt_out=rtd, day_out=dd)
    if prev is None:
        return None
    e = (now % 86400) / 86400.0
    rt_hist = max((v for dy, v in rtd.items() if dy >= today - RPC_RT_LOOKBACK), default=0)
    rt = max(float(rt_hist), float(max(0, int(head or 0))) / max(e, ES_HEAD_EARLY))
    rtm = min(float(base), max(rt * RPC_RT_MARGIN, float(base) * RPC_RT_FLOOR))
    lo = today - (RPC_DAY_WINDOW - 1)
    tail = float(sum(dd.get(dy, 0) for dy in range(lo, today)))
    ahead = float(cap) - tail
    for j in range(1, RPC_DAY_WINDOW):
        tail -= dd.get(lo + j - 1, 0)
        ahead = min(ahead, float(cap) - tail - j * rtm)
    return {"prev": int(prev), "room": int(cap) - int(prev), "ahead": int(ahead), "rt": int(rt), "rtm": int(rtm), "left": rtm * (1.0 - e)}


def _rpc_day_today(m9, now: float, live: bool) -> tuple:
    if live and m9.st.get("day") == int(now // 86400):
        return int(m9.st["n"] + m9.st["others"]), int(m9.st["nh"] + m9.st["others_h"])
    L = es_ledger_read(now, d=m9._dir())
    return int(L["n"]), int(L["nh"])


def _rpc_day_lims(ent: dict, now: float, live: bool = False) -> dict:
    m9 = ent["meter"]
    n_day = int(m9.budget)
    x = _burst_x(ent["spec"])
    if not x and not _win_spec(ent["spec"]):
        return {"normal": n_day, "burst": n_day, "cap": None, "prev": None, "x": 1.0}
    fd9 = ent["spec"].get("fresh_since")
    fd9 = int(fd9) if isinstance(fd9, int) and not isinstance(fd9, bool) else None
    if ent["spec"].get("svc"):
        try:
            import nodekeys
            fd9 = nodekeys.fresh_day(str(ent["spec"]["svc"]))
        except Exception:
            pass
    try:
        cap = int(float(ent["spec"]["month"]) * float(ent.get("pct") or 80.0) / 100.0)
    except (KeyError, TypeError, ValueError):
        return {"normal": n_day, "burst": n_day, "cap": None, "prev": None, "x": 1.0}
    used, head = _rpc_day_today(m9, now, live)
    if not x:
        F = month_flex(m9._dir(), now, n_day, cap, head, fd9)
        if F is None:
            return {"normal": n_day, "burst": n_day, "cap": cap, "prev": None, "x": 1.0, "bad": True}
        d9 = max(0, int(min(n_day, F["room"])))
        return {"normal": d9, "burst": d9, "cap": cap, "prev": F["prev"], "x": 1.0, "room": F["room"], "rt": F["rt"], "rtm": F["rtm"], "used": used, "head": head}
    return node_day_lims(m9._dir(), now, n_day, x, cap, used, head, fd9)


def node_day_lims(d: str, now: float, n_day: int, x: float, cap: int, used: int, head: int, fresh_day: int = None) -> dict:
    F = month_flex(d, now, n_day, cap, head, fresh_day)
    if F is None:
        return {"normal": n_day, "burst": n_day, "cap": cap, "prev": None, "x": x, "bad": True}
    room, rtm, left = F["room"], F["rtm"], F["left"]
    normal = max(0, min(room, used - head + n_day))
    burst = max(0, int(min(n_day * x, F["ahead"] - left)))
    return {"normal": int(normal), "burst": burst, "cap": cap, "prev": F["prev"], "x": x, "room": room, "ahead": F["ahead"],
            "rt": F["rt"], "rtm": int(rtm), "used": used, "head": head}


def rpc_day_take(name: str, host: str, units: int):
    with _RPC_DAY_LOCK:
        ent = _RPC_DAY.get(name)
    if ent is None:
        return None
    now = time.time()
    m9 = ent["meter"]
    bu9 = burst_on()
    hold9 = {}

    def lim_fn(now9):
        hold9["L"] = _rpc_day_lims(ent, now9, live=True)
        return hold9["L"]["burst"] if bu9 else hold9["L"]["normal"]
    bx9 = bool(_burst_x(ent["spec"]))
    wn9 = bx9 or _win_spec(ent["spec"])
    if m9.take(m9.proc or _RPC_DAY_PROC, max(1, int(units)), kind="fill" if (bx9 and bu9) else "must", now=now, limit=lim_fn if wn9 else None):
        return int(now // 86400)
    lims = hold9.get("L")
    lim9 = None if lims is None else (lims["burst"] if bu9 else lims["normal"])
    if m9.last_why() == "io":
        _stat(host, "quota_io")
        e9 = NetError(f"budget: {name} 하루 장부 기록 실패 — 합계를 모르면 승인 안 함(이번 요청 보류 · 다른 노드로)", "budget", host=host)
        e9.local = True
        raise e9
    used, bud = m9.used(now=now)
    if lim9 is not None:
        bud = lim9
    if lims is not None and not bu9 and used + max(1, int(units)) <= lims["burst"]:
        e8 = NetError(f"quota: {name} 오늘(UTC) 평소 몫 다 씀 {used}/{bud}{ent['spec'].get('unit')} — 따라잡기(백필) 호출만 더 받음(다른 노드로)",
                      "quota", host=host)
        e8.local = True
        e8.normal_only = True
        with _RPC_DAY_LOCK:
            ent["refused"] = int(ent.get("refused") or 0) + 1
        _stat(host, "quota_local")
        raise e8
    if lims is not None and bu9 and used + max(1, int(units)) <= lims["normal"]:
        e7 = NetError(f"quota: {name} 오늘(UTC) 백필 몫 다 씀 {used}/{bud}{ent['spec'].get('unit')} — 실시간 몫은 남겨 둠(백필은 다른 노드·다음 주기)",
                      "quota", host=host)
        e7.local = True
        e7.burst_only = True
        with _RPC_DAY_LOCK:
            ent["refused"] = int(ent.get("refused") or 0) + 1
        _stat(host, "quota_local")
        raise e7
    err = NetError(f"quota: {name} 오늘(UTC) 몫(공표 한도 {ent.get('pct', 80):g}% 규칙) 다 씀 "
                   f"{used}/{bud}{ent['spec'].get('unit')} — UTC 자정까지 이 노드 쉼(다른 노드로)", "quota", host=host)
    err.local = True
    with _RPC_DAY_LOCK:
        ent["refused"] = int(ent.get("refused") or 0) + 1
    nxt = (int(now) // 86400 + 1) * 86400 + 60
    gate(host).failure(err, quota_open=max(60.0, nxt - now) / 1.1)
    _stat(host, "quota_local")
    raise err


def rpc_day_settle(name: str, actual: int, reserved: int, day):
    delta = int(actual) - int(reserved)
    if not delta or day is None:
        return
    with _RPC_DAY_LOCK:
        ent = _RPC_DAY.get(name)
    if ent is None:
        return
    now = time.time()
    if int(now // 86400) != int(day):
        return
    try:
        ent["meter"].add(ent["meter"].proc or _RPC_DAY_PROC, delta, now=now)
    except Exception:
        pass


def rpc_day_status() -> dict:
    out = {}
    with _RPC_DAY_LOCK:
        ents = dict(_RPC_DAY)
    for name, ent in ents.items():
        try:
            used, bud = ent["meter"].used()
        except Exception:
            used, bud = 0, ent["meter"].budget
        out[name] = {"used": int(used), "budget": int(bud), "unit": ent["spec"].get("unit"), "refused": int(ent.get("refused") or 0)}
        if _burst_x(ent["spec"]):
            try:
                l9 = rpc_day_limits(name)
                out[name].update(normal=l9.get("normal"), burst=l9.get("burst"), cap=l9.get("cap"), prev=l9.get("prev"),
                                  rt=l9.get("rt"), rtm=l9.get("rtm"), room=l9.get("room"))
            except Exception:
                pass
    return out


def _rpc_day_atexit():
    with _RPC_DAY_LOCK:
        ents = list(_RPC_DAY.values())
    for ent in ents:
        try:
            ent["meter"].flush(closed=True)
        except Exception:
            pass


__import__("atexit").register(_rpc_day_atexit)
rpc_day_configure({})


ES_DISPATCH_GAP = 0.51
ES_DISPATCH_FALLBACK = 1.25
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


_CONFIGURED = [False]
_CFG_ENSURE_LOCK = threading.Lock()


def configure(cfg: dict):
    global QUOTA_OPEN, ES_DAILY_BUDGET, ES_PACE_BURST_FRAC, ES_FILL_KEEP_FRAC
    _CONFIGURED[0] = True
    try:
        ES_DAILY_BUDGET = int(((cfg or {}).get("etherscan") or {}).get("daily_budget") or 80000)
    except (TypeError, ValueError):
        ES_DAILY_BUDGET = 80000
    es9 = (cfg or {}).get("etherscan") or {}
    try:
        ES_PACE_BURST_FRAC = max(0.0, float(es9.get("pace_burst_pct", 4))) / 100.0
        ES_FILL_KEEP_FRAC = min(50.0, max(0.0, float(es9.get("fill_keep_pct", 2)))) / 100.0
    except (TypeError, ValueError):
        ES_PACE_BURST_FRAC, ES_FILL_KEEP_FRAC = 0.04, 0.02
    helius_configure(cfg)
    rpc_day_configure(cfg)
    sol_meter_configure(cfg)
    bf = (cfg or {}).get("backfill") or {}
    _POLICY_OVERRIDES.clear()
    for h, p in (bf.get("hosts") or {}).items():
        if isinstance(p, dict):
            _POLICY_OVERRIDES[str(h).lower()] = p
    if bf.get("quota_open_sec"):
        QUOTA_OPEN = float(bf["quota_open_sec"])
    with _GATES_LOCK:
        _GATES.clear()
    with _SHARES_LOCK:
        _SHARES.clear()


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
        return max(0.0, g._wait_needed(prio, 1), g.share.peek(1) if g.share is not None else 0.0)


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
    return sol_open(req, timeout)


ANKR_ADV_GATE = "rpc.ankr.com#adv"


def _ankr_adv(url: str, rpc_methods, cost: int):
    try:
        path = urllib.parse.urlsplit(url).path or ""
    except ValueError:
        return None, rpc_methods
    if not path.startswith("/multichain"):
        return None, rpc_methods
    return ANKR_ADV_GATE, (rpc_methods if rpc_methods else ["ankr_"] * max(1, int(cost or 1)))


def http_request(url: str, *, data: bytes = None, headers: dict = None, timeout: float = 25.0,
                 retries: int = 3, retry_5xx: bool = True, prio: str = "fg", deadline: float = None,
                 ua: str = UA, max_inline_wait: float = 20.0, breaker_5xx: bool = True, cost: int = 1,
                 sem_timeout: float = None, gate_host: str = None, rpc_methods=None):
    host = (urllib.parse.urlsplit(url).hostname or "?").lower()
    if gate_host is None and host == "rpc.ankr.com":
        gate_host, rpc_methods = _ankr_adv(url, rpc_methods, cost)
    g = gate(gate_host or host)
    last = None
    hard = sem_timeout is not None
    rd9 = _rpc_day_of(host) if _RPC_DAY else None
    rdu9 = _rpc_day_units(rd9, rpc_methods, cost) if rd9 else 0
    rdb9 = bool(rd9) and rpc_day_unit(rd9) == "bytes"

    def _left():
        return None if deadline is None else deadline - time.time()
    for i in range(max(1, retries)):
        if hard and _left() is not None and _left() <= 0:
            raise NetError(f"budget: {host} 요청 마감 지남", "budget", host=host)
        rdd9 = rpc_day_take(rd9, host, rdu9) if rd9 else None
        rds9 = False

        def _unsent(rdd9=rdd9):
            if hard and rd9 and rdd9 is not None:
                rpc_day_settle(rd9, 0, rdu9, rdd9)
        if not hard:
            g.sem.acquire()
        else:
            l9 = _left()
            st9 = float(sem_timeout) if l9 is None else min(float(sem_timeout), l9)
            if st9 <= 0 or not g.sem.acquire(timeout=st9):
                _unsent()
                raise NetError(f"budget: {host} 동시 요청 대기 {max(0.0, st9):.1f}s 초과", "budget", host=host)
        try:
            g.acquire(prio=prio, deadline=deadline, cost=cost)
        except BaseException:
            g.sem.release()
            _unsent()
            raise
        try:
            to9 = timeout
            if hard and _left() is not None:
                l9 = _left()
                if l9 <= 0:
                    _unsent()
                    rds9 = True
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
                g.observe(getattr(r, "headers", None))
                n9 = (min(rdu9, HTTP_MAX_BYTES) if rdb9 else HTTP_MAX_BYTES) + 1
                ln9 = getattr(r, "length", None)
                if isinstance(ln9, int) and not isinstance(ln9, bool) and ln9 >= 0:
                    n9 = min(n9, ln9 + 1)
                raw = r.read(n9)
            if rdb9:
                rpc_day_settle(rd9, len(raw), rdu9, rdd9)
                rds9 = True
                if len(raw) > rdu9:
                    e9 = NetError(f"payload: {host} 응답이 하루 장부 예약 상한 {rdu9:,}바이트를 넘음 — 받은 만큼 셈 · 구간·배치를 줄여 다시", "range", host=host)
                    e9.results = True
                    raise e9
            if len(raw) > HTTP_MAX_BYTES:
                e9 = NetError(f"payload: {host} response size over {HTTP_MAX_BYTES:,} bytes — 구간·배치를 줄여 다시", "range", host=host)
                e9.results = True
                raise e9
            try:
                d = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as e:
                raise NetError(f"payload: JSON 파싱 불가 ({str(e)[:60]})", "payload", host=host)
            g.success()
            return d, None
        except CircuitOpen:
            raise
        except Exception as e:
            bb9 = None
            if rdb9 and rdd9 is not None and not rds9 and isinstance(e, urllib.error.HTTPError):
                try:
                    bb9 = e.read(min(rdu9, HTTP_ERR_MAX_BYTES) + 1) or b""
                except Exception:
                    bb9 = None
                if bb9 is not None and len(bb9) > HTTP_ERR_MAX_BYTES:
                    bb9 = bb9[:HTTP_ERR_MAX_BYTES]
                elif bb9 is not None:
                    rpc_day_settle(rd9, len(bb9), rdu9, rdd9)
            err = classify_exc(e, host, body_bytes=bb9)
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


class RpcTransportError(ConnectionError):

    def __init__(self, err):
        super().__init__(str(err))
        self.net = err
        for k9 in ("kind", "code", "retry_after", "host"):
            setattr(self, k9, getattr(err, k9, None))
        self.local = bool(getattr(err, "local", False))


def _rpc_cfg_ensure():
    if _CONFIGURED[0]:
        return
    with _CFG_ENSURE_LOCK:
        if _CONFIGURED[0]:
            return
        try:
            configure(common.load_config())
        except (Exception, SystemExit):
            _CONFIGURED[0] = True


def rpc_post(url: str, body, *, timeout: float = 25.0, ua: str = None, retries: int = 1, prio: str = "fg", deadline: float = None,
             burst: bool = None):
    items = body if isinstance(body, list) else [body]
    methods = [str(it.get("method") or "") for it in items if isinstance(it, dict)]
    _rpc_cfg_ensure()
    try:
        with ledger_burst(burst_on() if burst is None else bool(burst)):
            return http_json(url, data=json.dumps(body).encode(), timeout=timeout, retries=retries, prio=prio, deadline=deadline,
                             ua=ua or UA, cost=max(1, len(items)), rpc_methods=methods or None, breaker_5xx=False)
    except NetError as e:
        raise RpcTransportError(e) from e


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
             prio: str = "fg", deadline: float = None, allow_null: bool = False, sem_timeout: float = None):
    _rpc_cfg_ensure()
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    host = (urllib.parse.urlsplit(url).hostname or "?").lower()
    for i9 in range(RATE_RETRIES + 1):
        d = http_json(url, data=body, timeout=timeout, retries=retries, prio=prio, deadline=deadline, rpc_methods=(method,), sem_timeout=sem_timeout)
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
              deadline: float = None, sem_timeout: float = None) -> list:
    if not calls:
        return []
    _rpc_cfg_ensure()
    host = (urllib.parse.urlsplit(url).hostname or "?").lower()
    out = _rpc_batch_once(url, calls, timeout, retries, prio, deadline, host, sem_timeout)
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
        again = _rpc_batch_once(url, [calls[k] for k in idx], timeout, retries, prio, deadline, host, sem_timeout)
        for k, r in zip(idx, again):
            out[k] = r
    return out


def _rpc_batch_once(url, calls, timeout, retries, prio, deadline, host, sem_timeout=None) -> list:
    body = json.dumps([{"jsonrpc": "2.0", "id": i, "method": m, "params": p}
                       for i, (m, p) in enumerate(calls)]).encode()
    for i9 in range(RATE_RETRIES + 1):
        try:
            d = http_json(url, data=body, timeout=timeout, retries=retries, prio=prio, deadline=deadline, cost=len(calls),
                          rpc_methods=[m for m, _p in calls], sem_timeout=sem_timeout)
        except NetError as err9:
            if err9.kind != "range" or not getattr(err9, "results", False) or len(calls) < 2:
                raise
            mid9 = len(calls) // 2
            return (_rpc_batch_once(url, calls[:mid9], timeout, retries, prio, deadline, host, sem_timeout)
                    + _rpc_batch_once(url, calls[mid9:], timeout, retries, prio, deadline, host, sem_timeout))
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
                 head_guard: bool = True, head_refresh_sec: float = 15.0, soft: dict = None, burst: bool = None):
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
        self.retention_floor = None
        self.retention_hint = {}
        self.sleep = float(sleep)
        self.timeout = float(timeout)
        self.per_ep_workers = max(1, int(per_ep_workers))
        self.prio = prio
        self.burst = burst
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
        self.soft = soft if isinstance(soft, dict) else None

    SOFT_SLOW_N = 8

    def _soft_fail(self, url, n: int):
        if self.soft is None:
            return
        s = self.soft.get(url) if isinstance(self.soft.get(url), dict) else {}
        best = int(s.get("best") or 0)
        self.soft[url] = {"cap": max(1, min(n - 1, max(n // 2, best if best < n else 0))), "fail": int(n), "ok": 0, "best": 0}

    def _soft_ok(self, url, n: int):
        s = self.soft.get(url) if self.soft is not None else None
        if not isinstance(s, dict):
            return
        s["best"] = max(int(s.get("best") or 0), int(n))
        if s.get("fail") and n > int(s["fail"]):
            s["fail"] = None
        if n < int(s["cap"]):
            return
        s["ok"] = int(s.get("ok") or 0) + 1
        if not s.get("fail") or int(s["cap"]) * 2 < int(s["fail"]):
            s["cap"], s["ok"] = int(s["cap"]) * 2, 0
        elif s["ok"] >= self.SOFT_SLOW_N:
            s["cap"], s["ok"] = int(s["cap"]) + max(1, int(s["cap"]) // 8), 0
        if int(s["cap"]) >= min(self.span, int(self.caps.get(url) or self.span)):
            self.soft.pop(url, None)

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
        c = min(self.span, int(self.caps.get(url) or self.span))
        s = self.soft.get(url) if self.soft is not None else None
        return min(c, max(1, int(s["cap"]))) if isinstance(s, dict) and s.get("cap") else c

    def _retention_all(self, eps):
        eps = list(eps)
        if not eps or any(u not in self.retention_hint for u in eps):
            return None
        return min(int(self.retention_hint[u]) for u in eps)

    def _burst_for(self, to: int) -> bool:
        if self.burst is not None:
            return bool(self.burst)
        hs = [h for h in (self.ep_head or {}).values() if isinstance(h, int)]
        with _EP_HEADS_LOCK:
            hs += [g[0] for u, g in _EP_HEADS.items() if (u in self.eps or u in self.fallback) and g and isinstance(g[0], int)]
        return bool(hs) and int(to) < max(hs) - RPC_NEAR_HEAD

    def _chunk_burst(self, url, chunk) -> bool:
        return self._burst_for(min(int(chunk[1]), int(chunk[0]) + self._cap(url) - 1))

    def _query(self, url, frm, to, pos):
        tp = [self.positions.get(pos, self.topic0), None, None] + [None] * max(0, pos - 2)
        tp[pos] = self.pads
        while tp and tp[-1] is None:
            tp.pop()
        with ledger_burst(self._burst_for(to)):
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

        normal_off = set()
        burst_off = set()

        def usable(url, chunk):
            if url in untrusted and chunk[0] <= old_below:
                return False
            if url in normal_off and not self._chunk_burst(url, chunk):
                return False
            if url in burst_off and self._chunk_burst(url, chunk):
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
                            if normal_off and any(u in normal_off for u in all_eps) and not self._burst_for(pending[0][1]):
                                st["stop"] = f"구간 {pending[0][0]}-{pending[0][1]}: 노드 키 오늘 평소 몫 다 씀 — 다음 사이클(공개 노드가 되면 그쪽으로)"
                            elif burst_off and any(u in burst_off for u in all_eps) and self._burst_for(pending[0][1]):
                                st["stop"] = f"구간 {pending[0][0]}-{pending[0][1]}: 노드 키 오늘 백필 몫 다 씀(실시간 몫은 남겨 둠) — 다음 사이클"
                            elif any(u in self.lag_head and pending[0][0] > self.lag_head[u][0] for u in all_eps):
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
                        self._soft_ok(url, b - a + 1)
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
                                if getattr(err, "results", False) and self.soft is not None:
                                    self._soft_fail(url, b - a + 1)
                                    requeue([[a, b]])
                                else:
                                    requeue([[a, mid], [mid + 1, b]])
                            else:
                                st["stop"] = common.redact_secret_text(f"{_url_host(url)} 최소 구간({self.min_span})도 거부: {err}")
                        elif err.kind == "timeout" and (b - a + 1) > self.min_span:
                            mid = (a + b) // 2
                            self.metrics["halved"] += 1
                            requeue([[a, mid], [mid + 1, b]])
                        elif err.kind == "pruned" and isinstance(getattr(err, "earliest", None), int):
                            n9, h9 = int(err.earliest), getattr(err, "latest", None)
                            h9 = int(h9) if isinstance(h9, int) and not isinstance(h9, bool) else None
                            parts9 = []
                            if a < n9:
                                pb9 = n9 - 1
                                self.pruned_below[url] = max(self.pruned_below.get(url, -1), pb9)
                                self.retention_hint[url] = max(self.retention_hint.get(url, 0), n9)
                                self.metrics["pruned"] += 1
                                parts9.append([a, min(b, pb9)])
                            lo9 = max(a, n9)
                            if h9 is not None and b > h9 and lo9 <= b:
                                self.lag_head[url] = (h9, time.time())
                                self.metrics["lag_clip"] += 1
                                if lo9 <= h9:
                                    parts9.append([lo9, h9])
                                parts9.append([max(lo9, h9 + 1), b])
                            elif lo9 <= b and a < n9:
                                parts9.append([lo9, b])
                            requeue(parts9 or [[a, b]])
                            if not parts9:
                                self.metrics["retention_odd"] = self.metrics.get("retention_odd", 0) + 1
                            fl9 = self._retention_all(all_eps)
                            if fl9 is not None and st["last"] + 1 < fl9 and st["stop"] is None:
                                st["stop"] = (f"구간 {st['last'] + 1}-{fl9 - 1}: 노드 보관 범위 밖(첫 보관 블록 {fl9}) — "
                                              "이 노드들에선 영영 못 받음")
                        elif err.kind == "pruned":
                            self.pruned_below[url] = max(self.pruned_below.get(url, -1), b)
                            self.metrics["pruned"] += 1
                            requeue([[a, b]])
                        elif err.kind == "quota" and getattr(err, "normal_only", False):
                            normal_off.add(url)
                            requeue([[a, b]])
                        elif err.kind == "quota" and getattr(err, "burst_only", False):
                            burst_off.add(url)
                            requeue([[a, b]])
                        else:
                            requeue([[a, b]])
                        cv.notify_all()
                    if self.log and err.kind not in ("range",):
                        self.log.info("%s %s %d-%d %s — 재배치", self.name,
                                      urllib.parse.urlsplit(url).hostname, a, b, str(err)[:120])
                    if err.kind not in ("range", "pruned", "timeout") or (err.kind == "pruned" and isinstance(getattr(err, "earliest", None), int)
                                                                          and not (a < err.earliest or (isinstance(getattr(err, "latest", None), int)
                                                                                                        and b > err.latest))):
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
            self.retention_floor = None
            fl9 = self._retention_all(all_eps)
            if st["last"] < frm and fl9 is not None and fl9 > frm:
                self.retention_floor = fl9
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

    BASE_KEYS = ("kind", "ok", "last_cycle_ts", "last_success_ts", "consecutive_failures", "last_error")

    def reset_facts(self, key: str):
        with self.lock:
            s = self.src.get(key)
            if isinstance(s, dict):
                for k in [k for k in s if k not in self.BASE_KEYS]:
                    del s[k]

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


BSC_BACKFILL_DAYS_DEFAULT = 120


def bsc_backfill_days(cfg: dict) -> int:
    cfg = cfg if isinstance(cfg, dict) else {}
    bc = cfg.get("bsc") if isinstance(cfg.get("bsc"), dict) else {}
    v = bc.get("backfill_days")
    if v is not None and not isinstance(v, bool):
        try:
            return max(1, int(v))
        except (TypeError, ValueError, OverflowError):
            pass
    if not cfg.get("backfill_full_history"):
        try:
            m = float(cfg.get("backfill_months") or 0)
        except (TypeError, ValueError):
            m = 0.0
        if 0 < m < 1200:
            return max(1, int(round(m * 30)))
    return BSC_BACKFILL_DAYS_DEFAULT
