"""Solana wallet watcher."""
from __future__ import annotations

from collections import deque
import contextlib
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
if __name__ == "__main__":
    common.cpu_reserve_apply()
import addr_tier
import lpsol
import bf_engine
import tsfix
from inbox import SegmentWriter

log = common.setup_logging("tj-sol")

TOKEN_PROGRAMS = (
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
)
PLAIN_PROGRAMS = set(TOKEN_PROGRAMS) | {
    "11111111111111111111111111111111",
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
    "ComputeBudget111111111111111111111111111111",
    "Memo1UhkJRfHyvLMcVucJwxXeuD728EqVDDwQDxFMNo",
    "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",
}
SIG_PAGE = 1000
TX_BATCH_SLEEP = 0.12
RATE_LIMIT_MAX = 5
BUDGET_WARN_PER_HOUR = 20000
ADDR_PACE_SEC = 0.25
ADDR_PACE_MAX = 2.0
ATA_EVERY_CYCLES = 5
RL_WAIT_MAX = 30.0
PRIMARY_TRIP_STREAK = 3
HL_COST = {"getProgramAccounts": 10, "getAsset": 10, "getAssetBatch": 10, "getAssetsByOwner": 10, "searchAssets": 10}
PRIMARY_QUOTA_OPEN = 1800.0
PRIMARY_RL_OPEN = 60.0
PARSE_BATCH = 1
SIG_SPOOL_PAGES = 30

HEAD_RPC_DEFAULT = "https://solana-rpc.publicnode.com"
ARCHIVE_RPC_DEFAULT = "https://api.mainnet-beta.solana.com"
HEAD_KEEP_HOURS = 18.0
HEAD_MARGIN_HOURS = 6.0
HEAD_TIMEOUT_SEC = 8.0
HEAD_GAP_SEC = 0.1
HEAD_HEALTH_SEC = 1800
HEAD_HEALTH_PCT = 90.0
HEAD_HEALTH_MIN_N = 20
HEAD_TRIP_STREAK = 3
HEAD_TRIP_BASE = 60.0
HEAD_TRIP_MAX = 1800.0
HEAD_LAG_MAX_SLOTS = 150
HEAD_AUDIT_PER_CYCLE = 3
HEAD_AUDIT_PAGES = 5
HEAD_AUDIT_TRIP_SEC = 6 * 3600.0
ARCHIVE_PER10S = 32
ARCHIVE_METHOD_PER10S = 8
HEAD_METHODS = frozenset({"getSignaturesForAddress", "getTransaction", "getSlot", "getEpochInfo", "getAccountInfo", "getBalance",
                          "getMultipleAccounts", "minimumLedgerSlot", "getFirstAvailableBlock"})

STAKE_PROGRAM = "Stake11111111111111111111111111111111111111"
JITO_TIP_DIST = "4R3gSG8BpU4t19KYj8CfnbtRpnT8gtk4dvTHxVRwc2r7"
STAKE_WITHDRAWER_OFFSET = 44
STAKE_EVERY_SEC = 3600
STAKE_RWD_POLL_SEC = 600
STAKE_RWD_MARGIN_SLOTS = 9000
STAKE_RWD_EPOCHS_PER_CYCLE = 8
SLOTS_PER_EPOCH = 432000
SLOT_SEC_EST = 0.4
U64_MAX = 18446744073709551615


class RateLimited(RuntimeError):

    def __init__(self, msg: str, retry_after=None, quota: bool = False):
        super().__init__(msg)
        self.retry_after = retry_after
        self.quota = quota


def _host(u) -> str:
    return bf_engine._host_norm(u) if u else ""


class _PnSkip(RuntimeError):
    pass


def _retry_after_sec(v):
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


class Rpc:
    def __init__(self, cfg: dict):
        key = os.environ.get("TJ_HELIUS_KEY", "")
        if not key:
            key = common.read_env_file().get("TJ_HELIUS_KEY", "")
        sol = cfg.get("sol", {})
        if sol.get("rpc") == "helius":
            if not key:
                raise SystemExit("TJ_HELIUS_KEY 없음 (.env) — fail-closed")
            self.url = f"https://mainnet.helius-rpc.com/?api-key={key}"
        else:
            self.url = sol.get("rpc") or sol.get("rpc_fallback")
        self.fallback = sol.get("rpc_fallback")
        self.fallbacks = []
        for u in [self.fallback] + list(sol.get("rpc_fallbacks") or []):
            if u and u != self.url and u not in self.fallbacks:
                self.fallbacks.append(u)
        self.calls = deque()
        self.rl_streak = 0
        self.rl_seen = 0
        self.rl_last = False
        self.last_src = None
        self.last_url = None
        self.primary_open_until = 0.0
        self.primary_open_n = 0
        self.quota_open = float(sol.get("quota_open_sec", PRIMARY_QUOTA_OPEN))
        self.metered = bf_engine.is_helius_rpc(sol)
        self.proc = "tj-sol"
        self._kind = threading.local()
        def _f(k, d, lo, hi):
            try:
                v = sol.get(k)
                x = float(d if v is None else v)
            except (TypeError, ValueError):
                x = float(d)
            return min(hi, max(lo, x)) if x == x else float(d)
        hu = sol.get("head_rpc", HEAD_RPC_DEFAULT)
        self.head_url = str(hu).strip() if (self.metered and isinstance(hu, str) and hu.strip().startswith("http")) else None
        if self.head_url and _host(self.head_url) == _host(self.url):
            self.head_url = None
        au = sol.get("archive_rpc", ARCHIVE_RPC_DEFAULT)
        self.archive_url = str(au).strip() if (self.metered and isinstance(au, str) and au.strip().startswith("http")) else None
        if self.archive_url and _host(self.archive_url) in (_host(self.url), _host(self.head_url)):
            self.archive_url = None
        bf_engine.sol_meter_configure(cfg)
        self.head_window = 3600.0 * (_f("head_rpc_keep_hours", HEAD_KEEP_HOURS, 1, 240) - _f("head_rpc_margin_hours", HEAD_MARGIN_HOURS, 0, 240))
        self.head_timeout = _f("head_rpc_timeout_sec", HEAD_TIMEOUT_SEC, 1, 60)
        self.head_gap = _f("head_rpc_gap_ms", HEAD_GAP_SEC * 1000, 0, 10000) / 1000.0
        self.head_health_sec = 60.0 * _f("head_rpc_health_min", HEAD_HEALTH_SEC / 60, 1, 1440)
        self.head_health_pct = _f("head_rpc_health_pct", HEAD_HEALTH_PCT, 1, 100)
        self.head_health_n = int(_f("head_rpc_health_n", HEAD_HEALTH_MIN_N, 1, 10000))
        self.head_lag_max = int(_f("head_rpc_lag_slots", HEAD_LAG_MAX_SLOTS, 10, 100000))
        self.head_audit_n = int(_f("head_rpc_audit_per_cycle", HEAD_AUDIT_PER_CYCLE, 0, 50))
        self.archive_gap = 10.0 / _f("archive_rpc_per10s", ARCHIVE_PER10S, 1, 1000)
        self.archive_method_gap = 10.0 / _f("archive_rpc_method_per10s", ARCHIVE_METHOD_PER10S, 1, 1000)
        self._hint = threading.local()
        self._fill = threading.local()
        self._pn_hist = deque()
        self._pn_streak = 0
        self._pn_open_until = 0.0
        self._pn_open_n = 0
        self._pn_why = ""
        self._pn_gen = 0
        self.pn_n = {"ok": 0, "fail": 0, "audit_ok": 0, "audit_miss": 0}
        self.pn_lag = None
        self.hl_closed_until = 0.0
        self._ar_pause_until = 0.0
        self._pn_nf = {}

    @contextlib.contextmanager
    def hint(self, **kw):
        prev = getattr(self._hint, "v", None)
        self._hint.v = dict(prev or {}, **kw)
        try:
            yield
        finally:
            self._hint.v = prev

    @contextlib.contextmanager
    def fill_scope(self):
        prev = getattr(self._fill, "via", None)
        try:
            yield
        finally:
            self._fill.via = prev

    def set_fill_via(self, via):
        self._fill.via = via

    def hl_closed(self) -> bool:
        return float(getattr(self, "hl_closed_until", 0) or 0) > time.time()

    def hl_close_until(self, ts: float):
        self.hl_closed_until = float(ts)

    def hl_open(self):
        self.hl_closed_until = 0.0

    def can_continue_capped(self) -> bool:
        return bool(self.metered and (self.head_url or self.archive_url))

    def pn_open(self) -> bool:
        return float(getattr(self, "_pn_open_until", 0) or 0) > time.time()

    def _pn_note(self, ok: bool, why: str = "", trip: bool = False):
        now = time.time()
        self._pn_hist.append((now, bool(ok)))
        while self._pn_hist and self._pn_hist[0][0] < now - self.head_health_sec:
            self._pn_hist.popleft()
        if ok:
            self.pn_n["ok"] += 1
            self._pn_streak = 0
            self._pn_open_n = 0
            return
        self.pn_n["fail"] += 1
        self._pn_streak += 1
        self._pn_why = common.redact_urls(str(why))[:160]
        if trip or self._pn_streak >= HEAD_TRIP_STREAK:
            self.pn_fault(why, min(HEAD_TRIP_BASE * (2 ** self._pn_open_n), HEAD_TRIP_MAX))
            self._pn_open_n += 1

    def pn_fault(self, why: str, dur: float):
        self._pn_open_until = max(self._pn_open_until, time.time() + float(dur))
        self._pn_gen = int(getattr(self, "_pn_gen", 0) or 0) + 1
        self._pn_streak = 0
        self._pn_why = common.redact_urls(str(why))[:160]
        log.warning("공개 노드(publicnode) %.0f분 쉼 — 새 거래 확인은 헬리우스로: %s", dur / 60, self._pn_why)

    def pn_state(self) -> dict:
        now = time.time()
        while self._pn_hist and self._pn_hist[0][0] < now - self.head_health_sec:
            self._pn_hist.popleft()
        n = len(self._pn_hist)
        okn = sum(1 for _t, o in self._pn_hist if o)
        rate = (okn / n) if n else None
        opn = self.pn_open()
        healthy = bool(self.head_url) and not opn and n >= self.head_health_n and rate is not None and rate * 100.0 >= self.head_health_pct
        return {"on": bool(self.head_url), "healthy": healthy, "rate": rate, "n": n, "open_until": self._pn_open_until if opn else None,
                "why": self._pn_why or None, "host": common.redact_urls(self.head_url) if self.head_url else None, "lag": self.pn_lag}

    def pn_ok(self) -> bool:
        if not getattr(self, "head_url", None) or float(getattr(self, "head_window", 0) or 0) <= 0 or self.pn_open():
            return False
        self.pn_state()
        t9 = float(getattr(self, "_pn_open_until", 0) or 0)
        h9 = [o for t, o in self._pn_hist if t >= t9]
        n9 = len(h9)
        return not (n9 >= self.head_health_n and sum(1 for o in h9 if o) * 100.0 < self.head_health_pct * n9)

    def fill_route(self):
        if not self.metered:
            return "helius"
        if not self.hl_closed() and not self.primary_open() and bf_engine.HELIUS.room("fill", proc=self.proc) > 0:
            return "helius"
        if self.archive_url and time.time() >= self._ar_pause_until:
            return "archive"
        return None

    def _pn_usable(self, method: str, params, hint: dict) -> bool:
        if not self.head_url or self.pn_open() or method not in HEAD_METHODS:
            return False
        if method == "getSignaturesForAddress":
            opt = params[1] if isinstance(params, (list, tuple)) and len(params) > 1 and isinstance(params[1], dict) else {}
            if not hint.get("pn"):
                return False
            if opt.get("before") and not opt.get("until"):
                return False
            return True
        if method == "getTransaction":
            return bool(hint.get("pn_tx"))
        return True

    def _routes(self, method: str, params) -> list:
        hint = getattr(getattr(self, "_hint", None), "v", None) or {}
        hl_ok = not self.primary_open() and not self.hl_closed()
        prim = [(self.url, "primary")] if hl_ok else []
        if hint.get("only") == "primary":
            return prim
        if not getattr(self, "metered", False):
            return prim + [(u, "fallback") for u in self.fallbacks]
        hh, ah, ph = _host(self.head_url), _host(self.archive_url), _host(self.url)
        fbs, seen9 = [], {ph}
        for u in list(self.fallbacks) + ([self.archive_url] if self.archive_url else []):
            h9 = _host(u)
            if u and h9 not in seen9:
                seen9.add(h9)
                fbs.append((u, "fallback"))
        if ah and time.time() < self._ar_pause_until:
            fbs = [x for x in fbs if _host(x[0]) != ah]
        if self.kind() == "fill":
            fbs = [x for x in fbs if _host(x[0]) != hh]
            if getattr(self._fill, "via", None) == "archive":
                if method == "getAsset":
                    return prim
                return [x for x in fbs if _host(x[0]) == ah][:1]
            return prim + fbs
        if method in ("getSignaturesForAddress", "getTokenAccountsByOwner"):
            fbs = [x for x in fbs if _host(x[0]) != hh]
        if self._pn_usable(method, params, hint):
            return [(self.head_url, "head")] + prim + [x for x in fbs if _host(x[0]) != hh]
        return prim + fbs

    def _pn_sigs(self, url: str, params, timeout, hint: dict):
        a = params[0]
        opt = dict(params[1]) if len(params) > 1 and isinstance(params[1], dict) else {}
        until, us = opt.get("until"), hint.get("slot")
        slot_ok = isinstance(us, int) and not isinstance(us, bool)
        if not (until and slot_ok and self._pn_nf.get(a) == until):
            try:
                return self._call(url, "getSignaturesForAddress", [a, opt] if len(params) > 1 else params, timeout)
            except RuntimeError as e:
                s9 = str(e)
                if not until or not ("-32020" in s9 or "not found" in s9.lower()):
                    raise
                if not slot_ok:
                    raise _PnSkip(f"커서를 못 찾음(-32020) · 커서 슬롯 모름 — 헬리우스로") from e
                if len(self._pn_nf) > 5000:
                    self._pn_nf.clear()
                self._pn_nf[a] = until
        opt.pop("until", None)
        rows = self._call(url, "getSignaturesForAddress", [a, opt], timeout)
        if not isinstance(rows, list):
            return rows
        return [x for x in rows if not isinstance(x, dict) or not isinstance(x.get("slot"), int)
                or x["slot"] > us or (x["slot"] == us and x.get("signature") != until)]

    def _head_check(self, method: str, r, hint: dict):
        if method == "getSignaturesForAddress":
            if not isinstance(r, list):
                return "서명 목록 형식"
            us9 = hint.get("slot")
            last = None
            for x in r:
                if not isinstance(x, dict) or not isinstance(x.get("signature"), str) or not isinstance(x.get("slot"), int) or isinstance(x.get("slot"), bool):
                    return "서명 항목 형식"
                if last is not None and x["slot"] > last:
                    return "서명 순서(최신→과거 아님)"
                last = x["slot"]
                if isinstance(us9, int) and not isinstance(us9, bool) and x["slot"] < us9:
                    return f"커서 슬롯 {us9} 보다 옛 서명(커서를 못 찾음 = 색인 구멍)"
            return None
        if method in ("getSlot", "minimumLedgerSlot", "getFirstAvailableBlock"):
            return None if isinstance(r, int) and not isinstance(r, bool) else "슬롯 형식"
        return None

    def kind(self) -> str:
        return getattr(getattr(self, "_kind", None), "v", "head")

    @contextlib.contextmanager
    def as_kind(self, k: str):
        prev = self.kind()
        self._kind.v = k
        try:
            yield
        finally:
            self._kind.v = prev

    def _trip_primary(self, e: "RateLimited"):
        dur = self.quota_open if e.quota else min(PRIMARY_RL_OPEN * (2 ** self.primary_open_n), self.quota_open)
        self.primary_open_until = time.time() + dur
        self.primary_open_n += 1
        log.warning("주 RPC %s — %.0f분간 폴백 RPC 직행 (%s)", "쿼터 소진(max usage)" if e.quota else
                    f"연속 429 {self.rl_streak}회", dur / 60, str(e)[:80])

    def primary_open(self) -> bool:
        return self.primary_open_until > time.time()

    def _rl_wait(self, e: "RateLimited") -> float:
        ra = e.retry_after
        if ra is None:
            ra = min(2.0 ** self.rl_streak, RL_WAIT_MAX)
        return min(max(ra, 0.5), RL_WAIT_MAX)

    def call(self, method: str, params, timeout=25):
        self.rl_last = False
        self.last_src = None
        self.last_url = None
        r = self._call_any(method, params, timeout)
        return r

    def day_capped(self) -> bool:
        return bool(self.metered) and bf_engine.HELIUS.day_capped()

    def fill_ok(self) -> bool:
        return self.fill_route() is not None

    def fill_room(self) -> int:
        if not self.metered:
            return 1 << 30
        return bf_engine.HELIUS.room("fill", proc=self.proc)

    def _call_any(self, method: str, params, timeout=25):
        hint = getattr(getattr(self, "_hint", None), "v", None) or {}
        routes = self._routes(method, params)
        e_head = e_prim = e_fb = None
        tried_fb = False
        if not any(r9 == "primary" for _u9, r9 in routes):
            if self.primary_open():
                e_prim = RuntimeError(f"주 RPC 차단 중(쿼터/429) — {self.primary_open_until - time.time():.0f}s 남음")
            elif self.hl_closed():
                e_prim = RuntimeError(f"헬리우스 하루 예산 소진 — {time.strftime('%H:%M', time.localtime(self.hl_closed_until))} 까지 공개 노드로")
        for url, role in routes:
            if role == "head":
                try:
                    if method == "getSignaturesForAddress":
                        r = self._pn_sigs(url, params, min(timeout, self.head_timeout), hint)
                    else:
                        r = self._call(url, method, params, min(timeout, self.head_timeout))
                    bad = self._head_check(method, r, hint)
                    if bad:
                        raise RuntimeError(f"공개 노드 응답 이상 — {bad}")
                    self._pn_note(True)
                    self.last_src, self.last_url = "head", url
                    return r
                except RateLimited as e:
                    self._pn_note(False, f"429 ({method})", trip=True)
                    e_head = e
                except _PnSkip as e:
                    e_head = e
                except Exception as e:
                    if "-32015" not in str(e):
                        self._pn_note(False, f"{method}: {e}")
                    e_head = e
                continue
            if role == "primary":
                try:
                    r = self._call(url, method, params, timeout)
                    self.last_src, self.last_url = "primary", url
                    return r
                except RateLimited as e:
                    self.rl_streak += 1
                    if e.quota or self.rl_streak >= PRIMARY_TRIP_STREAK:
                        self._trip_primary(e)
                        e_prim = e
                    else:
                        time.sleep(self._rl_wait(e))
                        try:
                            r = self._call(url, method, params, timeout)
                            self.last_src, self.last_url = "primary", url
                            return r
                        except RateLimited as e2:
                            self.rl_streak += 1
                            if e2.quota or self.rl_streak >= PRIMARY_TRIP_STREAK:
                                self._trip_primary(e2)
                            e_prim = e2
                        except Exception as e2:
                            e_prim = e2
                except Exception as e:
                    e_prim = e
                continue
            if method == "getAsset":
                break
            tried_fb = True
            try:
                r = self._call(url, method, params, timeout)
                self.last_src, self.last_url = "fallback", url
                return r
            except RateLimited as e:
                if getattr(self, "archive_url", None) and _host(url) == _host(self.archive_url):
                    self._ar_pause_until = time.time() + min(max(float(e.retry_after or 0), 30.0), 600.0)
                e_fb = e
            except Exception as e:
                e_fb = e
        if tried_fb and e_fb is not None:
            raise e_fb
        raise e_prim or e_head or e_fb or RuntimeError(f"rpc {method}: 쓸 수 있는 RPC 없음")

    def _call(self, url: str, method: str, params, timeout=25):
        if url == self.url and self.metered:
            c9 = HL_COST.get(method, 1)
            if self.kind() == "fill" and getattr(getattr(self, "_fill", None), "via", None) == "archive":
                if not bf_engine.HELIUS.take(self.proc, c9, kind="fill"):
                    raise RuntimeError(f"rpc {method}: 헬리우스 옛 기록 몫 없음(아카이브로 받는 중 — 메타는 몫이 나면)")
            else:
                bf_engine.HELIUS.add(self.proc, c9, kind=self.kind())
        now = time.monotonic()
        self.calls.append(now)
        hour_ago = now - 3600
        while self.calls and self.calls[0] <= hour_ago:
            self.calls.popleft()
        n_hour = len(self.calls)
        if n_hour == BUDGET_WARN_PER_HOUR:
            log.error("★RPC 예산 경보: 최근 1시간 %d콜 — 한도 소진 위험", n_hour)
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "tj-bot/0.1"})
        try:
            with bf_engine.sol_open(req, timeout, method, sol=True) as r:
                d = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                self.rl_seen += 1
                self.rl_last = True
                try:
                    body = (e.read() or b"")[:200].decode("utf-8", "replace").lower()
                except Exception:
                    body = ""
                raise RateLimited(f"HTTP Error 429: Too Many Requests ({method})",
                                  _retry_after_sec(e.headers.get("Retry-After") if e.headers else None),
                                  quota=("max usage" in body or "quota" in body or "credits" in body)) from e
            raise
        if url == self.url:
            self.rl_streak = 0
        if "error" in d:
            raise RuntimeError(f"rpc {method}: {common.redact_secret_text(str(d['error']))}")
        if d.get("result") is None:
            raise RuntimeError(f"rpc {method}: result null")
        if method == "getTransaction":
            _check_tx_result(d["result"])
        return d.get("result")

    def batch(self, method: str, params_list: list, timeout=30) -> list:
        body = json.dumps([{"jsonrpc": "2.0", "id": i, "method": method, "params": p}
                           for i, p in enumerate(params_list)]).encode()
        urls = [u for u, _r in self._routes(method, params_list[0] if params_list else [])] if hasattr(self, "_hint") else \
            (([] if self.primary_open() else [self.url]) + list(self.fallbacks))
        last = None
        for url in urls:
            if True:
                out = []
                for p9 in params_list:
                    try:
                        out.append(self._call(url, method, p9, timeout))
                    except Exception as e9:
                        out.append(e9)
                return out
            if url == self.url and self.metered:
                bf_engine.HELIUS.add(self.proc, len(params_list) * HL_COST.get(method, 1), kind=self.kind())
            now = time.monotonic()
            self.calls.append(now)
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json",
                                                                   "User-Agent": "tj-bot/0.1"})
            try:
                with bf_engine.sol_open(req, timeout) as r:
                    d = json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                if e.code == 429 and url == self.url:
                    try:
                        b9 = (e.read() or b"")[:200].decode("utf-8", "replace").lower()
                    except Exception:
                        b9 = ""
                    self.rl_seen += 1
                    self._trip_primary(RateLimited("HTTP Error 429 (batch)", quota="max usage" in b9 or "quota" in b9))
                last = e
                continue
            except Exception as e:
                last = e
                continue
            if not isinstance(d, list):
                last = RuntimeError(f"batch 응답 형식 오류: {str(d)[:100]}")
                continue
            out = [RuntimeError("batch 항목 누락") for _ in params_list]
            for it in d:
                try:
                    i = int(it.get("id"))
                except (TypeError, ValueError, AttributeError):
                    continue
                if not 0 <= i < len(params_list):
                    continue
                if it.get("error"):
                    out[i] = RuntimeError(f"rpc {method}: {common.redact_secret_text(str(it['error']))}")
                elif it.get("result") is None:
                    out[i] = RuntimeError(f"rpc {method}: result null")
                else:
                    try:
                        if method == "getTransaction":
                            _check_tx_result(it["result"])
                        out[i] = it["result"]
                    except Exception as e9:
                        out[i] = e9
            return out
        raise last if last else RuntimeError("batch: RPC 없음")


def _check_tx_result(result):
    tx9 = result if isinstance(result, dict) else {}
    meta9 = tx9.get("meta")
    keys9 = ((tx9.get("transaction") or {}).get("message") or {}).get("accountKeys")
    if (not isinstance(meta9, dict) or meta9.get("fee") is None or "err" not in meta9
            or not isinstance(keys9, list) or not keys9
            or any(not isinstance(meta9.get(k), list) or len(meta9[k]) != len(keys9)
                   for k in ("preBalances", "postBalances"))):
        raise RuntimeError("rpc getTransaction: 실행 메타/잔고 불완전 — 부분 결과 거부")


_STAKE_IX_KEYS = {
    "initialize": (("stakeAccount",), ("authorized.withdrawer",)),
    "initializeChecked": (("stakeAccount",), ("withdrawer",)),
    "split": (("stakeAccount", "newSplitAccount"), ("stakeAuthority",)),
    "merge": (("destination", "source"), ("stakeAuthority",)),
    "withdraw": (("stakeAccount",), ("withdrawAuthority",)),
    "delegate": (("stakeAccount",), ("stakeAuthority",)),
    "deactivate": (("stakeAccount",), ("stakeAuthority",)),
    "moveStake": (("source", "destination"), ("stakeAuthority",)),
    "moveLamports": (("source", "destination"), ("stakeAuthority",)),
}


def _stake_ix_accounts(instructions: list, owners) -> list:
    out = []
    for ins in instructions or []:
        if ins.get("programId") != STAKE_PROGRAM and ins.get("program") != "stake":
            continue
        p = ins.get("parsed")
        if not isinstance(p, dict):
            continue
        spec = _STAKE_IX_KEYS.get(p.get("type"))
        info = p.get("info") or {}
        if not spec or not isinstance(info, dict):
            continue
        w = None
        for f in spec[1]:
            v = info
            for part in f.split("."):
                v = v.get(part) if isinstance(v, dict) else None
            if isinstance(v, str) and v in owners:
                w = v
                break
        if not w:
            continue
        for f in spec[0]:
            a = info.get(f)
            if isinstance(a, str) and a and a not in owners:
                out.append((a, w))
    return out


def _token_owner_hints(instructions: list, mine=()) -> dict:
    out = {}
    mine = set(mine or ())
    for ins in instructions or []:
        p = ins.get("parsed") if isinstance(ins, dict) else None
        if not isinstance(p, dict) or not isinstance(p.get("info"), dict):
            continue
        info, t, prog = p["info"], str(p.get("type") or ""), str(ins.get("program") or "")
        if prog == "spl-associated-token-account" and t in ("create", "createIdempotent"):
            a, o = info.get("account"), info.get("wallet")
        elif prog in ("spl-token", "spl-token-2022") and t in ("initializeAccount", "initializeAccount2", "initializeAccount3", "closeAccount"):
            a, o = info.get("account"), info.get("owner")
        elif prog in ("spl-token", "spl-token-2022") and t in ("transfer", "transferChecked", "burn", "burnChecked") and info.get("authority") in mine:
            a, o = info.get("source") or info.get("account"), info.get("authority")
        else:
            continue
        if isinstance(a, str) and isinstance(o, str) and a and o:
            out.setdefault(a, o)
    return out


ATA_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
_ATA_MEMO = {}


def ata_address(owner: str, mint: str, token_program: str):
    k = (owner, mint, token_program)
    if k in _ATA_MEMO:
        return _ATA_MEMO[k]
    try:
        o9, m9, p9 = lpsol.b58decode(owner), lpsol.b58decode(mint), lpsol.b58decode(token_program)
        a = lpsol.find_pda([o9, p9, m9], ATA_PROGRAM)[0] if len(o9) == 32 and len(m9) == 32 and len(p9) == 32 else None
    except (KeyError, ValueError, TypeError):
        a = None
    if len(_ATA_MEMO) > 50_000:
        _ATA_MEMO.clear()
    _ATA_MEMO[k] = a
    return a


def ata_owner_of(acct: str, mint, owners, program=None):
    if not isinstance(acct, str) or not isinstance(mint, str) or not acct or not mint:
        return None
    progs = (program,) if program in TOKEN_PROGRAMS else TOKEN_PROGRAMS
    for o in sorted(owners or ()):
        for p9 in progs:
            if ata_address(o, mint, p9) == acct:
                return o
    return None


def stake_state(act, deact, epoch) -> str:
    try:
        act, deact, epoch = int(act), int(deact), int(epoch)
    except (TypeError, ValueError):
        return "undelegated"
    if deact != U64_MAX and deact < epoch:
        return "inactive"
    if deact != U64_MAX:
        return "deactivating"
    return "activating" if act >= epoch else "active"


class SolWatcher:
    def __init__(self, cfg: dict, wallets: list, writer: SegmentWriter):
        self.cfg = cfg
        self.rpc = Rpc(cfg)
        self.owners = wallets
        months = 0 if cfg.get("backfill_full_history") else float(cfg.get("backfill_months") or 0)
        self.cutoff_ts = int(time.time() - months * 30 * 86400) if months > 0 else 0
        self.writer = writer
        self.cursor_path = os.path.join(common.STATE_DIR, "cursor_sol.json")
        self.cursor = common.read_json(self.cursor_path, {})
        self.meta_path = os.path.join(common.STATE_DIR, "sol_mint_meta.json")
        self.mint_meta = common.read_json(self.meta_path, {})
        self.emitted_path = os.path.join(common.STATE_DIR, "emitted_sol.json")
        self.emitted = set(common.read_json(self.emitted_path, []))
        self.ata_owner = {}
        for k9 in [k9 for k9 in self.cursor if k9.startswith("_fb_wait:")]:
            if self.cursor[k9] in self.owners:
                self.ata_owner[k9[9:]] = self.cursor[k9]
            else:
                self.cursor.pop(k9, None)
        sol9 = cfg.get("sol") or {}
        self.ata_every = max(1, int(sol9.get("ata_every_cycles", ATA_EVERY_CYCLES)))
        self.addr_pace = float(sol9.get("addr_pace_sec", ADDR_PACE_SEC))
        self._n_cycle = 0
        self.parse_batch = max(1, int(sol9.get("parse_batch", PARSE_BATCH)))
        self.batch_sleep = float(sol9.get("batch_sleep_sec", 1.0))
        self.batch_sleep_min = self.batch_sleep
        self.sig_spool_pages = max(1, int(sol9.get("sig_spool_pages", SIG_SPOOL_PAGES)))
        self.progress = bf_engine.progress("sol")
        self._rl_log_at = time.time()
        self._rl_log_base = 0
        self.stake_on = bool(sol9.get("stake", True))
        self.stake_every = float(sol9.get("stake_every_sec", STAKE_EVERY_SEC))
        self.stake_path = os.path.join(common.STATE_DIR, "sol_stake.json")
        self.stake_snap = common.read_json(self.stake_path, {}) or {}
        self._stake_disc_at = 0.0
        self._stake_rwd_at = 0.0
        self._epoch = None
        self._stake_err = None
        self._bt_cache = {}
        self._fb_est = {}
        self._fb_waiting = set()
        self._vat = {}
        self._vat_load()
        self._audit_i = 0
        self._retiring = set()
        self._tier = addr_tier.sol_book(self, cfg)

    def _vat_load(self):
        now9 = time.time()
        for k9 in [k9 for k9 in self.cursor if isinstance(k9, str) and k9.startswith("_vat:")]:
            a9, v9 = k9[5:], self.cursor.get(k9)
            if a9 not in self.cursor:
                self.cursor.pop(k9, None)
                continue
            t9 = v9.get("t") if isinstance(v9, dict) else None
            if isinstance(t9, (int, float)) and not isinstance(t9, bool) and t9 == t9 and v9.get("c") == (self.cursor.get(a9) or ""):
                self._vat[a9] = float(min(t9, now9))

    def _vat_save(self, a: str):
        t9 = self._vat.get(a)
        if t9 is None:
            self.cursor.pop("_vat:" + a, None)
            return
        self.cursor["_vat:" + a] = {"t": int(t9), "c": self.cursor.get(a) or ""}

    def stake_reg(self) -> dict:
        return {k[5:]: v for k, v in self.cursor.items() if k.startswith("_stk:") and isinstance(v, dict)}

    def _stake_t0(self) -> int:
        vals = [v for v in (self.cutoff_ts, bf_engine.SINCE.target("sol")) if v]
        return int(min(vals)) if vals else 0

    def list_atas(self, owner: str) -> list:
        out = []
        for prog in TOKEN_PROGRAMS:
            res = self.rpc.call("getTokenAccountsByOwner",
                                [owner, {"programId": prog}, {"encoding": "jsonParsed"}])
            time.sleep(TX_BATCH_SLEEP)
            if res is None:
                raise RuntimeError(f"ATA 열거 응답 None ({owner[:8]}/{prog[:8]})")
            for it in (res or {}).get("value", []):
                pk = it.get("pubkey")
                if pk:
                    out.append(pk)
                    self.ata_owner[pk] = owner
        return out

    class SpoolPending(RuntimeError):
        pass

    class FillPaced(SpoolPending):
        pass

    def _spool_path(self, addr: str, tag: str = "") -> str:
        return os.path.join(common.STATE_DIR, f"solspool{tag}_{addr}.jsonl")

    def _sigs_spooled(self, addr: str, ck: dict, first_rows: list = None, cutoff: int = None, tag: str = "", gate=None):
        path = self._spool_path(addr, tag)
        cutoff = self.cutoff_ts if cutoff is None else cutoff
        if os.path.exists(path) and os.path.getsize(path) > int(ck.get("off", 0)):
            with open(path, "r+b") as f:
                f.truncate(int(ck.get("off", 0)))
        pages = 0

        def _append(rows):
            with open(path, "ab") as f:
                f.write(b"".join((json.dumps({"signature": r["signature"], "slot": r.get("slot"),
                                              "blockTime": r.get("blockTime")}) + "\n").encode() for r in rows))
                f.flush()
                os.fsync(f.fileno())
                ck["off"] = f.tell()
            ck["n"] = int(ck.get("n", 0)) + len(rows)
            ck["before"] = rows[-1]["signature"] if rows else ck.get("before")

        if first_rows is not None:
            _append(first_rows)
            common.atomic_write_json(self.cursor_path, self.cursor)
        while not ck.get("done") and pages < self.sig_spool_pages:
            if gate is not None and not gate():
                common.atomic_write_json(self.cursor_path, self.cursor)
                raise self.FillPaced(f"{addr[:8]} 서명 {ck['n']}건 — 오늘 옛 기록 몫을 다 써서 멈춤(몫이 나면 이어서)")
            opt = {"limit": SIG_PAGE, "commitment": "finalized"}
            if ck.get("before"):
                opt["before"] = ck["before"]
            res = self.rpc.call("getSignaturesForAddress", [addr, opt])
            if res is None:
                raise RuntimeError(f"getSignaturesForAddress None ({addr[:8]})")
            rows = res
            short = len(rows) < SIG_PAGE
            cut_stop = False
            if cutoff:
                kept = [r for r in rows
                        if not isinstance(r.get("blockTime"), int) or r["blockTime"] >= cutoff]
                cut_stop = len(kept) < len(rows)
                rows = kept
            if rows:
                _append(rows)
            if cut_stop or (short and self._end_ok(res)):
                ck["done"] = True
            elif short:
                common.atomic_write_json(self.cursor_path, self.cursor)
                raise self.SpoolPending(f"{addr[:8]} 서명 {ck['n']}건 — 폴백 RPC 의 짧은 페이지(이력 끝 미확인) · 주 RPC 로 끝 확인 대기")
            common.atomic_write_json(self.cursor_path, self.cursor)
            pages += 1
            self.progress.update(f"sol:{addr[:8]}", phase="sigs", unit="sigs", done=int(ck["n"]),
                                 note="서명 수집 중(총량 미상)")
            time.sleep(TX_BATCH_SLEEP)
        if not ck.get("done"):
            raise self.SpoolPending(f"{addr[:8]} 서명 {ck['n']}건 수집 — 다음 사이클 계속")
        if int(ck.get("off", 0)) == 0:
            return []
        out = []
        with open(path, "rb") as f:
            for line in f.read(int(ck["off"])).splitlines():
                if line.strip():
                    out.append(json.loads(line.decode()))
        return out

    def _end_ok(self, rows=None) -> bool:
        return getattr(self.rpc, "last_src", "primary") != "fallback"

    FB_MIN_SLOT_TTL = 600

    def _fb_min_slot(self, url):
        if not url:
            return None
        memo = self.__dict__.setdefault("_fb_min_memo", {})
        ent = memo.get(url)
        if ent and time.time() - ent[1] < self.FB_MIN_SLOT_TTL:
            return ent[0]
        fn = getattr(self.rpc, "_call", None)
        try:
            v = fn(url, "minimumLedgerSlot", []) if fn else None
            v = int(v) if isinstance(v, int) and not isinstance(v, bool) else None
        except Exception:
            v = None
        memo[url] = (v, time.time())
        return v

    def _cursor_set(self, addr: str, rows: list):
        self.cursor[addr] = rows[0]["signature"]
        sl = rows[0].get("slot")
        if isinstance(sl, int) and not isinstance(sl, bool):
            self.cursor["_slot:" + addr] = sl

    def new_sigs(self, addr: str, cutoff: int = None, gate=None, _bridge=None):
        cut = self.cutoff_ts if cutoff is None else cutoff
        until = self.cursor.get(addr) if _bridge is None else _bridge[0]
        ck = self.cursor.get("_sigbf:" + addr)
        if _bridge is None and not until and isinstance(ck, dict):
            rows9 = self._sigs_spooled(addr, ck, cutoff=cut, gate=gate)
            if not rows9:
                return rows9
            br9 = (rows9[0]["signature"], rows9[0].get("slot"))
            h9 = getattr(self.rpc, "hint", None)
            w9 = float(getattr(self.rpc, "head_window", 0) or 0) if getattr(self.rpc, "head_url", None) else 0.0
            t09 = ck.get("t0")
            pn9 = (w9 > 0 and isinstance(br9[1], int) and not isinstance(br9[1], bool) and isinstance(t09, (int, float))
                   and time.time() - (float(t09) - 60) <= w9)
            with (h9(pn=pn9, slot=br9[1]) if callable(h9) else contextlib.nullcontext()):
                newer9 = self.new_sigs(addr, cutoff=cut, gate=gate, _bridge=br9)
            return newer9 + rows9
        sigs = []
        before = None
        pages = 0
        while pages < 200:
            if _bridge is not None and gate is not None and not gate():
                raise self.FillPaced(f"{addr[:8]} 스풀 뒤 새 서명 — 오늘 옛 기록 몫을 다 써서 멈춤(몫이 나면 이어서)")
            opt = {"limit": SIG_PAGE, "commitment": "finalized"}
            if until:
                opt["until"] = until
            if before:
                opt["before"] = before
            t_call9 = time.time()
            res = self.rpc.call("getSignaturesForAddress", [addr, opt])
            if res is None:
                raise RuntimeError(f"getSignaturesForAddress None ({addr[:8]})")
            if getattr(self.rpc, "last_src", None) == "head":
                self._pnv_mark(addr, until or "", (_bridge[1] if _bridge is not None else self.cursor.get("_slot:" + addr)), t_call9)
            rows = res
            if cut:
                kept = [r for r in rows
                        if not isinstance(r.get("blockTime"), int) or r["blockTime"] >= cut]
                sigs.extend(kept)
                if len(kept) < len(rows):
                    break
            else:
                sigs.extend(rows)
            if len(rows) < SIG_PAGE:
                if not until and not self._end_ok(rows):
                    raise RuntimeError(f"{addr[:8]} 신규 주소 서명 — 폴백 RPC 의 짧은 페이지(이력 끝 미확인) · 주 RPC 로 다시")
                if until and not self._end_ok(rows):
                    us9 = self.cursor.get("_slot:" + addr) if _bridge is None else _bridge[1]
                    ms9 = self._fb_min_slot(getattr(self.rpc, "last_url", None))
                    if not (isinstance(us9, int) and isinstance(ms9, int) and ms9 <= us9):
                        raise RuntimeError(f"{addr[:8]} 서명 — 폴백 RPC 의 짧은 페이지(커서까지 이력 보유 미확인 · 노드 최저 슬롯 {ms9} · 커서 슬롯 {us9})"
                                           " · 주 RPC 로 다시")
                break
            if not until and pages == 0:
                ck = self.cursor["_sigbf:" + addr] = {"n": 0, "off": 0, "before": None, "done": False,
                                                      "t0": int(time.time())}
                log.info("%s 대형 신규 주소 — 재개형 서명 수집(스풀) 시작", addr[:8])
                return self._sigs_spooled(addr, ck, first_rows=sigs, cutoff=cut, gate=gate)
            before = rows[-1]["signature"]
            pages += 1
            time.sleep(TX_BATCH_SLEEP)
        else:
            raise RuntimeError(f"getSignaturesForAddress {pages}페이지 상한 도달 ({addr[:8]}) — 부분 결과 거부")
        return sigs

    def _pnv_mark(self, addr: str, sig: str, slot, t: float):
        k = "_pnv:" + addr
        e = self.cursor.get(k)
        if not isinstance(e, dict):
            self.cursor[k] = {"sig": sig or "", "slot": slot if isinstance(slot, int) and not isinstance(slot, bool) else None,
                              "pn": float(t), "since": float(t)}
        else:
            e["pn"] = max(float(e.get("pn") or 0), float(t))

    def mint_info(self, mint: str, fallback_dec) -> tuple:
        if mint in self.mint_meta:
            m = self.mint_meta[mint]
            return m[0], m[1]
        sym, dec = None, fallback_dec
        ok = True
        try:
            res = self.rpc.call("getAsset", {"id": mint})
            sym = (((res or {}).get("content") or {}).get("metadata") or {}).get("symbol")
            ti = (res or {}).get("token_info") or {}
            if isinstance(ti.get("decimals"), int):
                dec = ti["decimals"]
            if isinstance(ti.get("symbol"), str) and not sym:
                sym = ti["symbol"]
        except Exception:
            ok = False
        if isinstance(sym, str):
            sym = sym.strip()[:16] or None
        if ok:
            self.mint_meta[mint] = [sym, dec]
        return sym, dec

    TX_OPTS = {"encoding": "jsonParsed", "commitment": "finalized", "maxSupportedTransactionVersion": 1}

    def parse_tx(self, sig: str):
        tx = self.rpc.call("getTransaction", [sig, dict(self.TX_OPTS)])
        return self._parse_result(sig, tx)

    def parse_txs(self, sigs: list) -> dict:
        out = {}
        if self.parse_batch > 1 and len(sigs) > 1:
            try:
                res = self.rpc.batch("getTransaction", [[s9, dict(self.TX_OPTS)] for s9 in sigs])
                n_rl = 0
                for s9, r9 in zip(sigs, res):
                    if not isinstance(r9, Exception):
                        try:
                            out[s9] = self._parse_result(s9, r9)
                        except Exception as e:
                            out[s9] = e
                    elif "429" in str(r9) or "too many" in str(r9).lower():
                        n_rl += 1
                if n_rl:
                    self.batch_sleep = min(30.0, max(self.batch_sleep * 2, float(len(sigs))))
                    time.sleep(self.batch_sleep)
                else:
                    self.batch_sleep = max(self.batch_sleep_min, self.batch_sleep * 0.8)
            except Exception as e:
                log.info("getTransaction 배치 실패 → 단건: %s", str(e)[:100])
        for s9 in sigs:
            if s9 not in out or isinstance(out[s9], Exception):
                try:
                    out[s9] = self.parse_tx(s9)
                except Exception as e:
                    out[s9] = e
                time.sleep(TX_BATCH_SLEEP)
        return out

    def _parse_result(self, sig: str, tx):
        if not tx:
            return None
        meta = tx.get("meta") or {}
        msg = (tx.get("transaction") or {}).get("message") or {}
        keys = [k.get("pubkey") if isinstance(k, dict) else k for k in msg.get("accountKeys", [])]
        if getattr(self, "_tier", None) is not None:
            sg9 = self.__dict__.setdefault("_tier_signers", {})
            if len(sg9) > 5000:
                sg9.clear()
            sg9[sig] = [k.get("pubkey") for k in msg.get("accountKeys", []) if isinstance(k, dict) and k.get("signer")]
        mine = set(self.owners)
        stake_of = {s: (v.get("w") or "") for s, v in self.stake_reg().items() if v.get("w")} if self.stake_on else {}
        all_ins = list(msg.get("instructions") or [])
        for inn in (meta.get("innerInstructions") or []):
            all_ins.extend(inn.get("instructions") or [])
        stake_new = {}
        if self.stake_on:
            for s9, w9 in _stake_ix_accounts(all_ins, mine):
                if s9 not in stake_of and s9 not in mine:
                    stake_of[s9] = w9
                    stake_new[s9] = w9
        err = meta.get("err") is not None
        fee = int(meta.get("fee") or 0)
        fee_payer = keys[0] if keys else None
        fee_payer_mine = fee_payer in mine

        deltas = []
        counterparties = set()
        pre = meta.get("preBalances") or []
        post = meta.get("postBalances") or []
        stake_pre = {}
        for i, k in enumerate(keys):
            if i >= len(pre) or i >= len(post):
                break
            d = int(post[i]) - int(pre[i])
            if k in mine:
                adj = d + fee if (k == fee_payer and fee_payer_mine) else d
                if adj:
                    deltas.append({"asset": "native", "symbol": "SOL", "decimals": 9,
                                   "delta": str(adj), "owner": k})
            elif k in stake_of:
                stake_pre[k] = int(pre[i])
                if d:
                    deltas.append({"asset": "native", "symbol": "SOL", "decimals": 9,
                                   "delta": str(d), "owner": f"{stake_of[k]}:stake:{k}"})
            elif abs(d) > 1_000_000:
                counterparties.add(k)
        pre_tb, post_tb = list(meta.get("preTokenBalances") or []), list(meta.get("postTokenBalances") or [])
        idx_owner = {r9.get("accountIndex"): r9.get("owner") for r9 in pre_tb + post_tb
                     if isinstance(r9, dict) and r9.get("owner") and isinstance(r9.get("accountIndex"), int)}
        hint9 = None

        def owner_of(row):
            nonlocal hint9
            o9 = row.get("owner")
            ix9 = row.get("accountIndex")
            if o9 or not isinstance(ix9, int):
                return o9
            if ix9 in idx_owner:
                return idx_owner[ix9]
            acct9 = keys[ix9] if 0 <= ix9 < len(keys) else None
            if not acct9:
                return f"?{ix9}"
            if hint9 is None:
                hint9 = _token_owner_hints(all_ins, mine)
            return ((getattr(self, "ata_owner", None) or {}).get(acct9) or hint9.get(acct9)
                    or ata_owner_of(acct9, row.get("mint"), mine, row.get("programId")) or f"?{ix9}")
        tb = {}
        for row in pre_tb:
            key = (owner_of(row), row.get("mint"))
            ent = tb.setdefault(key, [0, 0, (row.get("uiTokenAmount") or {}).get("decimals")])
            ent[0] += int((row.get("uiTokenAmount") or {}).get("amount") or 0)
        for row in post_tb:
            key = (owner_of(row), row.get("mint"))
            ent = tb.setdefault(key, [0, 0, (row.get("uiTokenAmount") or {}).get("decimals")])
            ent[1] += int((row.get("uiTokenAmount") or {}).get("amount") or 0)
        unres9 = [{"acct": keys[int(o9[1:])] if int(o9[1:]) < len(keys) else None, "mint": m9, "delta": str(b1 - b0)}
                  for (o9, m9), (b0, b1, _d9) in tb.items() if isinstance(o9, str) and o9.startswith("?") and m9 and b1 != b0]
        hold9o = self.__dict__.setdefault("_own_hold", tsfix.TsHold())
        if unres9:
            old9 = not any(isinstance(r9, dict) and r9.get("owner") for r9 in pre_tb + post_tb)
            if not old9 and hold9o.hold(sig):
                raise RuntimeError(f"tx {sig[:12]} 토큰 잔고 {len(unres9)}줄 소유자 모름 — 보류(커서 유지 · 다음 사이클 다시)")
            now9 = time.time()
            if now9 - float(self.__dict__.get("_own_warn_at", 0) or 0) >= 600:
                self._own_warn_at = now9
                log.error("★tx %s 토큰 잔고 %d줄 소유자를 못 찾음(%s) — 그 줄 빼고 내보냄 · 목록 state/sol_owner_unknown.jsonl(내 계정이면 입출금이 빠짐)★",
                          sig[:12], len(unres9), "owner 칸 없는 옛 응답" if old9 else f"{hold9o.limit}회 연속")
            try:
                common.append_durable_jsonl(os.path.join(common.STATE_DIR, "sol_owner_unknown.jsonl"),
                                            {"ts": int(now9), "sig": sig, "old": old9, "rows": unres9})
            except OSError as e9:
                log.warning("sol_owner_unknown.jsonl 기록 실패: %s", e9)
        else:
            hold9o.clear(sig)
        for (owner, mint), (b0, b1, dec) in tb.items():
            d = b1 - b0
            if not d or not owner or not mint or str(owner).startswith("?"):
                continue
            if owner in mine:
                sym, dec2 = self.mint_info(mint, dec if isinstance(dec, int) else 0)
                deltas.append({"asset": mint, "symbol": sym,
                               "decimals": dec2 if isinstance(dec2, int) else 0,
                               "delta": str(d), "owner": owner})
            else:
                counterparties.add(owner)
        progs = set()
        for ins in (msg.get("instructions") or []):
            pid = ins.get("programId")
            if pid:
                progs.add(pid)
        has_program = any(p not in PLAIN_PROGRAMS for p in progs)
        bt9 = tx.get("blockTime")
        if not (isinstance(bt9, int) and not isinstance(bt9, bool) and bt9 > 0):
            hold9 = getattr(self, "_ts_hold", None)
            if hold9 is None:
                hold9 = self._ts_hold = tsfix.TsHold()
            try:
                bt9 = tsfix.block_ts(self, tx.get("slot") or 0, fn=self._block_time)
                hold9.clear(sig)
            except Exception as e:
                if hold9.hold(sig):
                    raise RuntimeError(f"tx {sig[:12]} 시각 없음 · 슬롯 시각 조회 실패 — 보류: {str(e)[:80]}") from e
                log.error("★tx %s 시각 없음 %d회 연속 — 내보냄(core 격리 → 슬롯 시각 구하는 대로 자동 재방출)★", sig[:12], hold9.limit)
                bt9 = tx.get("blockTime")
        out = {
            "v": 1, "kind": "sol_tx", "chain": "sol", "txhash": sig,
            "slot": tx.get("slot"), "ts": bt9,
            "fee_lamports": fee, "fee_payer_mine": fee_payer_mine,
            "fee_payer": fee_payer,
            "wallets": self.owners,
            "deltas": deltas, "counterparties": sorted(counterparties),
            "has_program": has_program, "err": err,
        }
        if stake_pre:
            out["stake_pre"] = stake_pre
        if stake_new:
            out["stake_new"] = stake_new
        if (not err and deltas and JITO_TIP_DIST in {i9.get("programId") for i9 in all_ins}
                and all(":stake:" in (d9.get("owner") or "") and int(d9["delta"]) > 0 for d9 in deltas)):
            out["stake_reward"] = {"kind": "mev"}
        lp9 = lpsol.extract(tx, mine)
        if lp9:
            out["lp"] = lp9
        return out

    def _stake_hl_ok(self, need: int, what: str) -> bool:
        if not _hl_paced(self.rpc):
            return True
        room9 = bf_engine.HELIUS.room("head", proc=self.rpc.proc)
        if room9 >= need:
            return True
        self._stake_paced_at = time.time()
        if time.time() - float(getattr(self, "_stake_paced_log", 0) or 0) >= 1800:
            self._stake_paced_log = time.time()
            log.info("스테이킹 %s — 헬리우스 실시간 몫 대기(필요 %d · 지금 여유 %d) · 다음 주기에(실패 아님)", what, need, room9)
        return False

    def _stake_discover(self, force: bool = False) -> bool:
        if not self.stake_on:
            return False
        now = time.time()
        if not force and self._stake_disc_at and now - self._stake_disc_at < self.stake_every:
            return True
        if not force and now < getattr(self, "_stake_retry_at", 0):
            return False
        if not self._stake_hl_ok(int(HL_COST.get("getProgramAccounts", 10)) * len(self.owners), "계정 발견"):
            return False
        try:
            ei = self.rpc.call("getEpochInfo", [{"commitment": "finalized"}])
            self._epoch = {"epoch": int(ei["epoch"]), "slotIndex": int(ei["slotIndex"]),
                           "absoluteSlot": int(ei["absoluteSlot"]), "ts": int(now)}
            found = {}
            for w in self.owners:
                res = self.rpc.call("getProgramAccounts", [STAKE_PROGRAM, {
                    "encoding": "jsonParsed", "commitment": "finalized",
                    "filters": [{"memcmp": {"offset": STAKE_WITHDRAWER_OFFSET, "bytes": w}}]}])
                time.sleep(TX_BATCH_SLEEP)
                for it in res or []:
                    pk = it.get("pubkey")
                    acc = it.get("account") or {}
                    info = (((acc.get("data") or {}).get("parsed") or {}).get("info") or {})
                    auth = ((info.get("meta") or {}).get("authorized") or {})
                    if not pk or auth.get("withdrawer") != w:
                        continue
                    dl = ((info.get("stake") or {}).get("delegation") or {})
                    found[pk] = {"w": w, "lamports": int(acc.get("lamports") or 0),
                                 "stake": int(dl.get("stake") or 0), "voter": dl.get("voter"),
                                 "act": dl.get("activationEpoch"), "deact": dl.get("deactivationEpoch"),
                                 "rent": int((info.get("meta") or {}).get("rentExemptReserve") or 0),
                                 "staker": auth.get("staker"),
                                 "state": stake_state(dl.get("activationEpoch"), dl.get("deactivationEpoch"),
                                                      self._epoch["epoch"])}
        except Exception as e:
            self._stake_err = common.safe_err(e)[:160]
            self._stake_retry_at = now + 300
            log.info("스테이크 계정 발견 실패(5분 뒤 재시도): %s", e)
            return False
        t0 = self._stake_t0()
        for s, v in found.items():
            k = "_stk:" + s
            ent = self.cursor.get(k)
            if not isinstance(ent, dict):
                self.cursor[k] = {"w": v["w"], "t0": t0, "rwd_next": None, "first": None, "open": False}
                log.info("★스테이크 계정 발견 %s (지갑 %s, %.4f SOL, 검증인 %s) — 창 %s 부터 추적★", s[:8], v["w"][:8],
                         v["lamports"] / 1e9, (v["voter"] or "?")[:8], time.strftime("%Y-%m-%d", time.gmtime(t0)))
            elif ent.pop("gone", None) is not None:
                pass
        for s, ent in self.stake_reg().items():
            if s not in found and not ent.get("gone"):
                ent["gone"] = int(now)
        prev = self.stake_snap.get("accounts") or {}
        for s, ent in self.stake_reg().items():
            if s not in found and s in prev:
                found[s] = dict(prev[s], lamports=0, stake=0, state="closed", w=ent.get("w"))
        for s, v in found.items():
            v["ledger_ready"] = bool((self.cursor.get("_stk:" + s) or {}).get("open"))
        self.stake_snap = {"ts": int(now), "epoch": self._epoch, "accounts": found}
        common.atomic_write_json(self.stake_path, self.stake_snap)
        common.atomic_write_json(self.cursor_path, self.cursor)
        self._stake_disc_at = now
        self._stake_err = None
        return True

    def _block_time(self, slot: int) -> int:
        if slot in self._bt_cache:
            return self._bt_cache[slot]
        bt = int(self.rpc.call("getBlockTime", [int(slot)]))
        if len(self._bt_cache) > 512:
            self._bt_cache.clear()
        self._bt_cache[slot] = bt
        return bt

    def _stake_note_first(self, s: str, slot, pre) -> None:
        ent = self.cursor.get("_stk:" + s)
        if not isinstance(ent, dict) or (ent.get("open") and not ent.get("reopen_pending")) or slot is None or pre is None:
            return
        f = ent.get("first")
        if not f or int(slot) < int(f[0]):
            ent["first"] = [int(slot), int(pre)]

    def _stake_rewards(self) -> bool:
        reg = self.stake_reg()
        if not self.stake_on or not reg:
            return True
        now = time.time()
        if not self._epoch or now - self._epoch["ts"] >= STAKE_RWD_POLL_SEC:
            ei = self.rpc.call("getEpochInfo", [{"commitment": "finalized"}])
            self._epoch = {"epoch": int(ei["epoch"]), "slotIndex": int(ei["slotIndex"]),
                           "absoluteSlot": int(ei["absoluteSlot"]), "ts": int(now)}
        cur = self._epoch["epoch"]
        last = cur - 1 if self._epoch["slotIndex"] >= STAKE_RWD_MARGIN_SLOTS else cur - 2
        acc = (self.stake_snap.get("accounts") or {})
        for s, ent in reg.items():
            if ent.get("rwd_next") is None:
                t0 = int(ent.get("t0") or 0)
                act = (acc.get(s) or {}).get("act")
                try:
                    act = int(act)
                except (TypeError, ValueError):
                    act = None
                if t0:
                    lag = int((now - t0) / (SLOTS_PER_EPOCH * SLOT_SEC_EST)) + 3
                    e0 = max(cur - lag, act if act is not None else 0)
                else:
                    e0 = act if act is not None else cur - 1
                ent["rwd_next"] = int(e0)
        n = 0
        while n < STAKE_RWD_EPOCHS_PER_CYCLE:
            todo = {s: e for s, e in ((s, int(v.get("rwd_next"))) for s, v in reg.items()
                                      if not (v.get("gone") and v.get("open") and not v.get("reopen_pending"))) if e <= last}
            if not todo:
                break
            e = min(todo.values())
            addrs = sorted(s for s, e9 in todo.items() if e9 == e)
            if not self._stake_hl_ok(1 + len(addrs), "보상 조회"):
                break
            res = self.rpc.call("getInflationReward", [addrs, {"epoch": e, "commitment": "finalized"}])
            if not isinstance(res, list) or len(res) != len(addrs):
                raise RuntimeError(f"getInflationReward 응답 형식 오류(epoch {e})")
            for s, r in zip(addrs, res):
                ent = reg[s]
                if r and int(r.get("amount") or 0) > 0:
                    slot9 = int(r["effectiveSlot"])
                    bt = self._block_time(slot9)
                    if bt >= int(ent.get("t0") or 0):
                        txh = f"stakerwd:{s}:{e}"
                        if txh not in self.emitted:
                            amt = int(r["amount"])
                            self.writer.append({
                                "v": 1, "kind": "sol_tx", "chain": "sol", "txhash": txh, "slot": slot9, "ts": bt,
                                "fee_lamports": 0, "fee_payer_mine": False, "fee_payer": None, "wallets": self.owners,
                                "deltas": [{"asset": "native", "symbol": "SOL", "decimals": 9, "delta": str(amt),
                                            "owner": f"{ent['w']}:stake:{s}"}],
                                "counterparties": [], "has_program": True, "err": False,
                                "stake_reward": {"kind": "epoch", "epoch": e, "commission": r.get("commission"),
                                                 "post_balance": int(r.get("postBalance") or 0),
                                                 "voter": (acc.get(s) or {}).get("voter")}})
                            self.emitted.add(txh)
                        self._stake_note_first(s, slot9, int(r.get("postBalance") or 0) - int(r["amount"]))
                ent["rwd_next"] = e + 1
            n += 1
            common.write_json_if_changed(self.emitted_path, sorted(self.emitted))
            common.atomic_write_json(self.cursor_path, self.cursor)
            time.sleep(TX_BATCH_SLEEP)
        return all(int(v.get("rwd_next")) > last for v in reg.values()
                   if not (v.get("gone") and v.get("open") and not v.get("reopen_pending")))

    def _stake_note_tx(self, rec: dict) -> None:
        for s9, w9 in (rec.get("stake_new") or {}).items():
            if not isinstance(self.cursor.get("_stk:" + s9), dict):
                self.cursor["_stk:" + s9] = {"w": w9, "t0": self._stake_t0(), "rwd_next": None, "first": None, "open": False}
                log.info("★스테이크 계정 발견(tx) %s (지갑 %s)★", s9[:8], w9[:8])
        for s9, pre9 in (rec.get("stake_pre") or {}).items():
            self._stake_note_first(s9, rec.get("slot"), pre9)

    def _stake_open(self, caught_up: bool) -> None:
        if not caught_up:
            return
        acc = self.stake_snap.get("accounts") or {}
        for s, ent in self.stake_reg().items():
            if ent.get("open") or s not in self.cursor:
                continue
            f = ent.get("first")
            if f:
                lam = int(f[1])
            elif s in acc and acc[s].get("state") != "closed":
                lam = int(acc[s].get("lamports") or 0)
            else:
                continue
            txh = f"stakeopen:{s}"
            if lam > 0 and txh not in self.emitted:
                self.writer.append({
                    "v": 1, "kind": "sol_tx", "chain": "sol", "txhash": txh, "slot": None,
                    "ts": int(ent.get("t0") or 0) or int(time.time()),
                    "fee_lamports": 0, "fee_payer_mine": False, "fee_payer": None, "wallets": self.owners,
                    "deltas": [{"asset": "native", "symbol": "SOL", "decimals": 9, "delta": str(lam),
                                "owner": f"{ent['w']}:stake:{s}"}],
                    "counterparties": [], "has_program": True, "err": False,
                    "stake_open": {"acct": s, "wallet": ent["w"], "lamports": lam,
                                   "first_slot": f[0] if f else None}})
                self.emitted.add(txh)
                log.info("★스테이크 기초잔고 %s %.6f SOL (창 %s)★", s[:8], lam / 1e9,
                         time.strftime("%Y-%m-%d", time.gmtime(int(ent.get("t0") or 0))))
            ent["open"] = True
            if s in acc:
                acc[s]["ledger_ready"] = True
        common.write_json_if_changed(self.emitted_path, sorted(self.emitted))
        common.atomic_write_json(self.cursor_path, self.cursor)
        if self.stake_snap:
            common.atomic_write_json(self.stake_path, self.stake_snap)

    def _stake_sigs_between(self, s: str, lo: int, hi: int):
        out, before = [], None
        for _p in range(50):
            opt = {"limit": 1000, "commitment": "finalized"}
            if before:
                opt["before"] = before
            res = self.rpc.call("getSignaturesForAddress", [s, opt])
            if not isinstance(res, list):
                raise RuntimeError(f"getSignaturesForAddress 형식 오류({s[:8]})")
            stop = False
            for r in res:
                bt = r.get("blockTime")
                if bt is None:
                    raise RuntimeError(f"서명 blockTime 없음({s[:8]})")
                if int(bt) < lo:
                    stop = True
                    break
                if int(bt) < hi and not r.get("err"):
                    out.append(r["signature"])
            if stop:
                return list(reversed(out))
            if len(res) < 1000:
                if not self._end_ok(res):
                    raise RuntimeError(f"스테이크 {s[:8]} 서명 — 폴백 RPC 의 짧은 페이지(이력 끝 미확인) · 다음 주기")
                return list(reversed(out))
            before = res[-1]["signature"]
        raise RuntimeError(f"스테이크 서명 50쪽 상한({s[:8]})")

    def _stake_reopen(self, caught_up=None) -> None:
        tgt = bf_engine.SINCE.target("sol")
        if not tgt:
            return
        tgt = int(tgt)
        changed = False
        acc = self.stake_snap.get("accounts") or {}
        for s, ent in self.stake_reg().items():
            if caught_up is None:
                if not ent.get("open") or ent.get("reopen_pending") or int(ent.get("t0") or 0) <= tgt + 60:
                    continue
                if not self._stake_hl_ok(1, "기초잔고 재산정"):
                    break
                old_t0 = int(ent.get("t0") or 0)
                first = ent.get("first") if isinstance(ent.get("first"), list) else None
                n_emit = 0
                for sig in self._stake_sigs_between(s, tgt, old_t0):
                    rec = self.parse_tx(sig)
                    if not isinstance(rec, dict):
                        raise RuntimeError(f"스테이크 tx 파싱 실패 {sig[:10]}")
                    pre9 = (rec.get("stake_pre") or {}).get(s)
                    if pre9 is not None and rec.get("slot") is not None and (not first or int(rec["slot"]) < int(first[0])):
                        first = [int(rec["slot"]), int(pre9)]
                    if sig not in self.emitted:
                        self.writer.append(rec)
                        self.emitted.add(sig)
                        n_emit += 1
                    time.sleep(TX_BATCH_SLEEP)
                ent.update(t0=tgt, rwd_next=None, first=first, reopen_pending=True, reopen_from=old_t0)
                changed = True
                log.warning("★스테이크 기초잔고 재산정 시작 %s: 창 %s → %s · 옛 구간 tx 방출 %d(보상 따라잡은 뒤 기초잔고 확정)★", s[:8],
                            time.strftime("%Y-%m-%d", time.gmtime(old_t0)), time.strftime("%Y-%m-%d", time.gmtime(tgt)), n_emit)
                continue
            if not caught_up or not ent.get("reopen_pending"):
                continue
            first = ent.get("first")
            if first:
                lam = int(first[1])
            elif s in acc and acc[s].get("state") != "closed":
                lam = int(acc[s].get("lamports") or 0)
            else:
                continue
            new_t0 = int(ent["t0"])
            txh = f"stakeopen:{s}:{new_t0}"
            if txh not in self.emitted:
                self.writer.append({
                    "v": 1, "kind": "sol_tx", "chain": "sol", "txhash": txh, "slot": None, "ts": new_t0,
                    "fee_lamports": 0, "fee_payer_mine": False, "fee_payer": None, "wallets": self.owners,
                    "deltas": ([{"asset": "native", "symbol": "SOL", "decimals": 9, "delta": str(lam),
                                 "owner": f"{ent['w']}:stake:{s}"}] if lam > 0 else []),
                    "counterparties": [], "has_program": True, "err": False,
                    "stake_open": {"acct": s, "wallet": ent["w"], "lamports": lam, "first_slot": first[0] if first else None,
                                   "reopen": True, "t0": new_t0, "prev_t0": int(ent.get("reopen_from") or 0)}})
                self.emitted.add(txh)
            log.warning("★스테이크 기초잔고 재산정 %s: 창 %s → %s · %.6f SOL(과거 창 확장)★", s[:8],
                        time.strftime("%Y-%m-%d", time.gmtime(int(ent.get("reopen_from") or 0))),
                        time.strftime("%Y-%m-%d", time.gmtime(new_t0)), lam / 1e9)
            ent.pop("reopen_pending", None)
            ent.pop("reopen_from", None)
            changed = True
        if changed:
            common.write_json_if_changed(self.emitted_path, sorted(self.emitted))
            common.atomic_write_json(self.cursor_path, self.cursor)

    def _stake_cycle(self) -> None:
        if not self.stake_on:
            return
        hb = bf_engine.health("sol")
        try:
            self._stake_reopen()
            caught = self._stake_rewards()
            self._stake_reopen(caught_up=caught)
            self._stake_open(caught)
            self._stake_err = None if self._stake_disc_at else self._stake_err
        except Exception as e:
            caught = False
            self._stake_err = common.safe_err(e)[:160]
            log.info("스테이킹 보상 단계 실패(다음 주기): %s", e)
        reg = self.stake_reg()
        now = time.time()
        disc_age = now - self._stake_disc_at if self._stake_disc_at else None
        facts = dict(accounts=len([1 for v in reg.values() if not v.get("gone")]),
                     discovered_at=int(self._stake_disc_at) or None, snapshot_ts=self.stake_snap.get("ts"),
                     epoch=(self._epoch or {}).get("epoch"),
                     rewards_next_epoch=min((int(v["rwd_next"]) for v in reg.values() if v.get("rwd_next") is not None),
                                            default=None),
                     rewards_caught_up=bool(caught), opened=sum(1 for v in reg.values() if v.get("open")),
                     staked_sol=round(sum(int(v.get("lamports") or 0) for v in (self.stake_snap.get("accounts") or {}).values()) / 1e9, 6))
        pz9 = float(getattr(self, "_stake_paced_at", 0) or 0)
        if pz9 and now - pz9 <= 600:
            facts["paced_at"] = int(pz9)
        if not self._stake_err and pz9 and now - pz9 <= 600:
            hb.ok("sol_stake", "stake", **facts)
        elif self._stake_err or disc_age is None or disc_age > 3 * self.stake_every:
            hb.fail("sol_stake", RuntimeError(self._stake_err or "스테이크 계정 발견 스냅샷 오래됨"), "stake", **facts)
        else:
            hb.ok("sol_stake", "stake", **facts)
        hb.flush()

    def _rl_summary(self):
        now = time.time()
        if now - self._rl_log_at >= 3600:
            n = self.rpc.rl_seen - self._rl_log_base
            log.info("헬리우스/폴백 429 응답: 최근 %.0f분 %d회 (재시도 흡수 포함, 주소 간격 %.2fs, ATA %d사이클마다)",
                     (now - self._rl_log_at) / 60, n, self.addr_pace, self.ata_every)
            self._rl_log_at = now
            self._rl_log_base = self.rpc.rl_seen

    def full_due(self, now: float = None) -> bool:
        now = time.time() if now is None else now
        tb0 = getattr(self, "_tier", None)
        pf9 = (tb0.eff_poll / tb0.base_poll) if tb0 is not None and tb0.base_poll else 1.0
        if pf9 > 1.0:
            return self._n_cycle == 0 or now - float(getattr(self, "_full_at", 0) or 0) >= tb0.eff_poll * self.ata_every * 0.98
        return self._n_cycle % self.ata_every == 0

    def hl_full_est(self) -> int:
        return 2 * len(self.owners) + int(getattr(self.rpc, "head_audit_n", 0) or 0) + 1

    def _fb_paced(self) -> bool:
        m9 = bf_engine.HELIUS
        return bool(getattr(self.rpc, "metered", False)) and callable(getattr(self.rpc, "fill_room", None)) \
            and getattr(m9, "fill_first", False) and m9.burst < 1.0

    def _fb_fits(self, est: int, left: int) -> bool:
        m9 = bf_engine.HELIUS
        fresh, keep = m9.fill_cap_fresh(), m9.keep_credits()
        if est <= left:
            return True
        if est <= fresh - keep:
            return False
        return left >= min(est, fresh) - keep

    def _fb_hold(self, a: str, est):
        self._fb_wait_note(a)
        self._fb_waiting.add(a)
        self.progress.update(f"sol:{a[:8]}", phase="wait", unit="tx", done=0, total=est if est else None, eta_sec=0, rate=0,
                             paced_at=int(time.time()), note="오늘 옛 기록 몫을 다 써서 차례 대기 — UTC 0시(한국 오전 9시)에 이어 받아요")

    def _fb_wait_note(self, a: str):
        o9 = self.ata_owner.get(a)
        if o9 and a not in self.owners and self.cursor.get("_fb_wait:" + a) != o9:
            self.cursor["_fb_wait:" + a] = o9
            common.atomic_write_json(self.cursor_path, self.cursor)

    def cycle(self):
        full = self.full_due() and not self.__dict__.pop("_own_only", False)
        if full:
            self._full_at = time.time()
            self._pn_lag_check()
        self._n_cycle += 1
        self._rl_summary()
        if full and self.cursor.pop("_synced_at", None) is not None:
            common.atomic_write_json(self.cursor_path, self.cursor)
        if full or not self._stake_disc_at:
            self._stake_discover()
        newp = {o for o in self.owners if o not in self.cursor}
        newp |= {k[7:] for k in self.cursor if k.startswith("_persp:")}
        for o in newp:
            self.cursor["_persp:" + o] = 1
        stake_reg = self.stake_reg()
        tb = getattr(self, "_tier", None)
        own_set = full_set = set(self.owners)
        if tb is not None:
            addr_tier.sol_activity(self, tb)
            addr_tier.sol_period_tick(self, tb)
            due9, _rest9 = tb.due_list(self.owners)
            full_set = set(due9)
            if full:
                full_set |= {o for o in self.owners if tb.tier(o)[1] <= 0}
            now_set = full_set if full else {o for o in due9 if tb.tier(o)[1] <= 0 or isinstance((tb.pairs.get(o) or {}).get("wake"), dict)}
            own_set = now_set | set(tb.activity_targets())
        addrs = []
        for o in self.owners:
            if o not in own_set:
                continue
            addrs.append(o)
            if full and o in full_set:
                try:
                    addrs.extend(self.list_atas(o))
                except Exception:
                    self._n_cycle = 0
                    raise
                time.sleep(TX_BATCH_SLEEP)
        if full:
            for s9, v9 in stake_reg.items():
                if not v9.get("gone"):
                    addrs.append(s9)
        active_addrs = set(addrs)
        if full:
            addrs.extend(k9[9:] for k9, o9 in list(self.cursor.items())
                         if k9.startswith("_fb_wait:") and o9 in full_set and k9[9:] not in active_addrs and k9[9:] not in self.cursor)
        repersp_addrs = {a for a in addrs if a not in self.cursor and
                         (a in newp or self.ata_owner.get(a) in newp or a in stake_reg)}
        if full:
            addrs.extend(a for a in self.cursor
                         if not a.startswith("_") and a not in active_addrs
                         and not (tb is not None and (a in self.owners or self.ata_owner.get(a) in set(self.owners) - full_set)))
        addr_sigs = {}
        all_new = {}
        fail_list = []
        rl_hits = 0
        rl_sleep = 1.0
        pace = self.addr_pace
        failed_addr = False
        fb_set = {a for a in dict.fromkeys(addrs) if a not in self.cursor and a not in stake_reg
                  and (a in newp or self.ata_owner.get(a) in newp)}
        fb_pace = bool(fb_set) and self._fb_paced()
        fb_resv = 0
        held = []
        hint9 = getattr(self.rpc, "hint", None)
        win9 = float(getattr(self.rpc, "head_window", 0) or 0) if getattr(self.rpc, "head_url", None) else 0.0
        hl_shut9 = callable(getattr(self.rpc, "hl_closed", None)) and self.rpc.hl_closed()
        t_list = {}
        self._retiring = {a for a in dict.fromkeys(addrs) if a not in active_addrs}
        gate9 = _pn_ok(self.rpc) and _hl_paced(self.rpc)
        defer9 = set()
        for a in dict.fromkeys(addrs):
            if rl_hits >= RATE_LIMIT_MAX:
                log.warning("429 %d회 — 이번 사이클 나머지 주소 건너뜀(커서 유지)", rl_hits)
                failed_addr = True
                break
            fb9 = a in fb_set
            if fb9 and fb_pace:
                left9 = self.rpc.fill_room() - fb_resv
                est9 = self._fb_est.get(a)
                if left9 <= 0 or (est9 and not self._fb_fits(est9, left9)):
                    self._fb_hold(a, est9)
                    held.append(a)
                    failed_addr = True
                    continue
            retire9 = a not in active_addrs
            if retire9 and hl_shut9:
                held.append(a)
                continue
            now9 = time.time()
            pn9 = (win9 > 0 and not fb9 and not retire9 and a in self.cursor and now9 - float(self._vat.get(a, -1e18)) <= win9)
            if gate9 and not pn9 and not fb9 and bf_engine.HELIUS.room("head", proc=self.rpc.proc) < 1:
                defer9.add(a)
                held.append(a)
                failed_addr = True
                continue
            if pn9 and self.cursor.get(a) and not isinstance(self.cursor.get("_slot:" + a), int):
                self._cursor_slot_fill(a)
            hk9 = {"pn": pn9, "slot": self.cursor.get("_slot:" + a)} if not retire9 else {"only": "primary"}
            t_list[a] = now9
            try:
                kw9 = {"gate": (lambda: self.rpc.fill_room() > 0)} if fb9 and fb_pace else {}
                with (self.rpc.as_kind("fill" if fb9 else "head") if callable(getattr(self.rpc, "as_kind", None)) else contextlib.nullcontext()), \
                        (hint9(**hk9) if callable(hint9) else contextlib.nullcontext()):
                    rows = self.new_sigs(a, cutoff=(int(stake_reg[a].get("t0") or 0) if a in stake_reg else None), **kw9)
            except self.FillPaced as e:
                log.info("%s", e)
                self._fb_hold(a, None)
                held.append(a)
                failed_addr = True
                continue
            except self.SpoolPending as e:
                log.info("%s", e)
                self._fb_wait_note(a)
                failed_addr = True
                continue
            except Exception as e:
                log.debug("%s 서명 조회 실패 — 이 주소 커서 유지: %s", a[:8], e)
                fail_list.append((a[:8], common.safe_err(e)[:120]))
                failed_addr = True
                if "429" in str(e):
                    rl_hits += 1
                    time.sleep(rl_sleep)
                    rl_sleep = min(rl_sleep * 2, 8.0)
                continue
            finally:
                if self.rpc.rl_last:
                    pace = min(max(pace, 0.05) * 2, ADDR_PACE_MAX)
                time.sleep(pace)
            if fb9 and fb_pace:
                left9 = self.rpc.fill_room() - fb_resv
                if not self._fb_fits(len(rows), left9):
                    log.info("%s 첫 백필 서명 %d건 — 오늘 남은 옛 기록 몫 %d 보다 커서 다음 차례(UTC 0시에 몰아서)", a[:8], len(rows), max(0, left9))
                    self._fb_est[a] = len(rows)
                    self._fb_hold(a, len(rows))
                    held.append(a)
                    failed_addr = True
                    continue
                fb_resv += len(rows)
                self._fb_est.pop(a, None)
                if a in self._fb_waiting:
                    self.progress.update(f"sol:{a[:8]}", phase="parse", unit="tx", done=0, total=len(rows), note="옛 기록 받는 중")
            miss9 = self.cursor.get("_pnmiss:" + a)
            if isinstance(miss9, list) and miss9:
                seen9 = {r["signature"] for r in rows}
                rows = list(rows) + [dict(r, _miss=True) for r in miss9
                                     if isinstance(r, dict) and isinstance(r.get("signature"), str) and r["signature"] not in seen9]
            addr_sigs[a] = rows
            for r in rows:
                all_new.setdefault(r["signature"], a)
        if defer9 and time.time() - float(getattr(self, "_defer_log", 0) or 0) >= 1800:
            self._defer_log = time.time()
            log.info("헬리우스 새 거래 확인 몫 대기 — publicnode 창 밖 주소 %d개(오래 쉰 계단·받침 복구 등)는 다음 주기에(창 안 주소는 그대로 확인)", len(defer9))
        ordered = []
        seen = set()
        for a, rows in addr_sigs.items():
            for r in reversed(rows):
                s = r["signature"]
                if s not in seen:
                    seen.add(s)
                    ordered.append(r)
        ordered.sort(key=lambda r: r.get("slot") or 0)
        re_sigs = {r["signature"] for a in repersp_addrs for r in addr_sigs.get(a, ()) if r["signature"] in self.emitted}
        cut_all = min([self.cutoff_ts] + [int(v.get("t0") or 0) for v in stake_reg.values()]) if self.cutoff_ts else 0
        done_ok = True
        todo = [r["signature"] for r in ordered if (r["signature"] not in self.emitted or r["signature"] in re_sigs) and not (
            cut_all and isinstance(r.get("blockTime"), int) and r["blockTime"] < cut_all)]
        head_sigs9 = {r["signature"] for a9, rows9 in addr_sigs.items() if a9 not in fb_set for r in rows9}
        bt_of = {r["signature"]: r.get("blockTime") for r in ordered}
        fb_sigs9 = {r["signature"] for a9, rows9 in addr_sigs.items() if a9 in fb_set for r in rows9} - head_sigs9
        pre = {}
        pos = 0
        n_done = 0
        big = len(todo) > 50
        for r in ordered:
            sig = r["signature"]
            if sig in self.emitted and sig not in re_sigs:
                continue
            bt = r.get("blockTime")
            if cut_all and isinstance(bt, int) and bt < cut_all:
                continue
            if sig not in pre:
                while pos < len(todo) and todo[pos] != sig:
                    pos += 1
                chunk = todo[pos:pos + self.parse_batch]
                pos += len(chunk)
                k9 = "fill" if chunk and all(s9 in fb_sigs9 for s9 in chunk) else "head"
                tnow9 = time.time()
                ptx9 = (k9 == "head" and win9 > 0 and bool(chunk)
                        and all(isinstance(bt_of.get(s9), int) and tnow9 - bt_of[s9] <= win9 for s9 in chunk))
                with (self.rpc.as_kind(k9) if callable(getattr(self.rpc, "as_kind", None)) else contextlib.nullcontext()), \
                        (hint9(pn_tx=ptx9) if callable(hint9) else contextlib.nullcontext()):
                    pre = self.parse_txs(chunk) if chunk else {}
                time.sleep(TX_BATCH_SLEEP if len(chunk) <= 1 else self.batch_sleep)
            rec = pre.pop(sig, None)
            if isinstance(rec, Exception):
                log.warning("tx %s 파싱 실패 — 커서 미전진, 다음 사이클: %s", sig[:12], rec)
                done_ok = False
                break
            if rec is None:
                log.warning("tx %s 응답 None — 커서 보류, 다음 사이클 재조회", sig[:12])
                done_ok = False
                break
            if sig in re_sigs:
                rec["repersp"] = True
            try:
                self.writer.append(rec)
                self.emitted.add(sig)
                self._stake_note_tx(rec)
                if tb is not None:
                    for o9 in {rec.get("fee_payer")} | set(self.__dict__.get("_tier_signers", {}).pop(sig, None) or []):
                        tb.note_sent(o9, rec.get("ts"))
            except Exception as e:
                log.error("inbox append 실패 — 커서 미전진: %s", e)
                done_ok = False
                break
            n_done += 1
            if big and n_done % 50 == 0:
                self.progress.update("sol", phase="parse", unit="tx", done=n_done, total=len(todo))
                common.write_json_if_changed(self.emitted_path, sorted(self.emitted))
        if big:
            self.progress.update("sol", phase="parse" if not done_ok else "live", unit="tx", done=n_done,
                                 total=len(todo), flush=True)
        if done_ok:
            for a, rows in addr_sigs.items():
                wait9 = self.cursor.pop("_fb_wait:" + a, None)
                if self.cursor.pop("_sigbf:" + a, None) is not None:
                    try:
                        os.remove(self._spool_path(a))
                    except OSError:
                        pass
                    self.progress.finish(f"sol:{a[:8]}", note=f"서명 {len(rows)}건 처리")
                    self._fb_waiting.discard(a)
                elif a in self._fb_waiting:
                    self._fb_waiting.discard(a)
                    self.progress.finish(f"sol:{a[:8]}", note=f"서명 {len(rows)}건 처리")
                self.cursor.pop("_pnmiss:" + a, None)
                rows = [r for r in rows if not r.get("_miss")]
                if a not in active_addrs and not isinstance(self.cursor.get("_pnv:" + a), dict):
                    self.cursor.pop(a, None)
                    self.cursor.pop("_slot:" + a, None)
                    self._vat.pop(a, None)
                    self.cursor.pop("_vat:" + a, None)
                    if wait9:
                        self.ata_owner.pop(a, None)
                    continue
                if a in t_list:
                    self._vat[a] = t_list[a]
                if not self.cursor.get(a) and "_cov_ts:" + a not in self.cursor:
                    self.cursor["_cov_ts:" + a] = int(self.cutoff_ts or 0)
                    if rows:
                        self.cursor["_cov_sig:" + a] = rows[-1]["signature"]
                if rows:
                    self._cursor_set(a, rows)
                else:
                    self.cursor.setdefault(a, "")
                if a in t_list:
                    self._vat_save(a)
            if full and len(addr_sigs) == len(dict.fromkeys(addrs)):
                self.cursor["_synced_at"] = int(time.time())
        if not full and (failed_addr or not done_ok):
            self.cursor.pop("_synced_at", None)
        if tb is not None:
            unq9 = set(dict.fromkeys(addrs)) - set(addr_sigs) - defer9
            failed_own = {o for o in own_set if o in unq9 or any(self.ata_owner.get(a) == o for a in unq9)}
            defer_own9 = {o for o in own_set if o in defer9 or any(self.ata_owner.get(a) == o for a in defer9)} - failed_own
            if not done_ok:
                failed_own |= set(own_set)
            scope_full9 = {o for o in own_set if full and o in full_set}
            ok9 = set(own_set) - failed_own - defer_own9
            fail_full9 = set(getattr(self, "_tier_fail_full", set())) & set(getattr(self, "_tier_fail", set()))
            self._tier_fail = (getattr(self, "_tier_fail", set()) - (ok9 & scope_full9) - (ok9 - fail_full9)) | failed_own
            self._tier_fail_full = (fail_full9 - (ok9 & scope_full9)) | (failed_own & scope_full9)
            now9 = int(time.time())
            for o in own_set - failed_own:
                if o not in addr_sigs or o in defer_own9:
                    continue
                if full and o in full_set:
                    tb.note_full(o, now9)
                    tb.note_baseline(o, 0, 0, now9)
                    tb.pairs[o]["atas"] = sorted(a for a, o9 in self.ata_owner.items() if o9 == o)
                else:
                    tb.pairs[o]["actAt"] = now9
            tb.save()
        if full and done_ok:
            for o in newp:
                if o in self.cursor and all(a9 in self.cursor for a9, o9 in self.ata_owner.items() if o9 == o):
                    self.cursor.pop("_persp:" + o, None)
        common.write_json_if_changed(self.meta_path, self.mint_meta)
        common.write_json_if_changed(self.emitted_path, sorted(self.emitted))
        common.atomic_write_json(self.cursor_path, self.cursor)
        if full and done_ok:
            self._pn_audit()
        self._health_cycle(full, addrs, addr_sigs, fail_list, done_ok, held)
        self._stake_cycle()
        if full and done_ok and not fail_list:
            try:
                self._extend([a for a in dict.fromkeys(addrs) if a in active_addrs and a not in stake_reg])
            except Exception as e:
                log.info("과거 창 확장 예외(다음 전체 사이클): %s", e)

    EXT_BUDGET = 300

    def _extend(self, addrs: list):
        target = bf_engine.SINCE.target("sol")
        if not target:
            return
        pend = []
        for a in addrs:
            cov9 = self.cursor.get("_cov_ts:" + a)
            if self._first_synced(a) and (not isinstance(cov9, int) or cov9 > int(target)):
                pend.append(a)
        if not pend:
            return
        if callable(getattr(self.rpc, "fill_ok", None)) and not self.rpc.fill_ok():
            for a in pend:
                self.progress.update(f"sol:{a[:8]}:extend", phase="extend", unit="tx", paced_at=int(time.time()))
            return
        with (self.rpc.as_kind("fill") if callable(getattr(self.rpc, "as_kind", None)) else contextlib.nullcontext()), \
                (self.rpc.fill_scope() if callable(getattr(self.rpc, "fill_scope", None)) else contextlib.nullcontext()):
            self._extend_addrs(pend, target)

    def _first_synced(self, a: str) -> bool:
        return a in self.cursor or ("_cov_ts:" + a) in self.cursor

    def _ext_more(self, a: str) -> bool:
        fr9 = getattr(self.rpc, "fill_route", None)
        if callable(fr9):
            via9 = fr9()
            if via9 is not None:
                if callable(getattr(self.rpc, "set_fill_via", None)):
                    self.rpc.set_fill_via(via9)
                return True
        elif not callable(getattr(self.rpc, "fill_room", None)) or self.rpc.fill_room() > 0:
            return True
        self.progress.update(f"sol:{a[:8]}:extend", phase="extend", unit="tx", paced_at=int(time.time()))
        return False

    def _extend_addrs(self, addrs: list, target):
        deadline = time.time() + self.EXT_BUDGET
        for a in addrs:
            if time.time() > deadline:
                break
            if not self._first_synced(a):
                continue
            cov = self.cursor.get("_cov_ts:" + a)
            if not isinstance(cov, int):
                cov = int(time.time())
            if cov <= target:
                continue
            ck = self.cursor.get("_sigx:" + a)
            if not isinstance(ck, dict) or ck.get("target") != target:
                ck = self.cursor["_sigx:" + a] = {"target": int(target), "n": 0, "off": 0,
                                                  "before": self.cursor.get("_cov_sig:" + a) or None, "done": False}
                try:
                    os.remove(self._spool_path(a, "x"))
                except OSError:
                    pass
            if not self._ext_more(a):
                break
            via9 = getattr(getattr(self.rpc, "_fill", None), "via", None)
            wait9 = self.__dict__.setdefault("_ext_hl_wait", set())
            if via9 == "archive" and a in wait9:
                continue
            if via9 != "archive":
                wait9.discard(a)
            try:
                sigs = self._sigs_spooled(a, ck, cutoff=int(target), tag="x", gate=lambda a=a: self._ext_more(a))
            except self.SpoolPending as e:
                log.info("확장 %s", e)
                if (not isinstance(e, self.FillPaced) and getattr(getattr(self.rpc, "_fill", None), "via", None) == "archive"
                        and getattr(self.rpc, "last_src", None) == "fallback"):
                    wait9.add(a)
                continue
            todo = [r["signature"] for r in reversed(sigs) if r["signature"] not in self.emitted]
            n_ok = 0
            for i in range(0, len(todo), max(1, self.parse_batch)):
                if time.time() > deadline or not self._ext_more(a):
                    break
                chunk = todo[i:i + max(1, self.parse_batch)]
                res = self.parse_txs(chunk) if len(chunk) > 1 else {chunk[0]: self.parse_tx(chunk[0])}
                bad = False
                for sg in chunk:
                    rec = res.get(sg)
                    if not isinstance(rec, dict):
                        bad = True
                        break
                    self.writer.append(rec)
                    self.emitted.add(sg)
                    n_ok += 1
                time.sleep(TX_BATCH_SLEEP if len(chunk) <= 1 else self.batch_sleep)
                if bad:
                    break
            common.write_json_if_changed(self.emitted_path, sorted(self.emitted))
            left = [sg for sg in todo if sg not in self.emitted]
            self.progress.update(f"sol:{a[:8]}:extend", phase="extend", unit="tx", done=len(todo) - len(left),
                                 total=len(todo), target=time.strftime("%Y-%m-%d", time.gmtime(target)))
            if not left:
                self.cursor["_cov_ts:" + a] = int(target)
                if sigs:
                    self.cursor["_cov_sig:" + a] = sigs[-1]["signature"]
                self.cursor.pop("_sigx:" + a, None)
                try:
                    os.remove(self._spool_path(a, "x"))
                except OSError:
                    pass
                self.progress.finish(f"sol:{a[:8]}:extend", note=f"{len(todo)}건")
            common.atomic_write_json(self.cursor_path, self.cursor)

    def _cursor_slot_fill(self, a: str):
        rpc, sig = self.rpc, self.cursor.get(a)
        tried9 = self.__dict__.setdefault("_slot_try", {})
        if time.time() - tried9.get(a, 0) < 3600:
            return False
        tried9[a] = time.time()
        for u in (getattr(rpc, "archive_url", None), None if (rpc.primary_open() or rpc.hl_closed()) else rpc.url):
            if not u:
                continue
            try:
                with rpc.as_kind("head"):
                    r = rpc._call(u, "getSignatureStatuses", [[sig], {"searchTransactionHistory": True}])
                v = ((r or {}).get("value") or [None])[0] if isinstance(r, dict) else None
                sl = (v or {}).get("slot")
                if isinstance(sl, int) and not isinstance(sl, bool) and sl > 0:
                    self.cursor["_slot:" + a] = sl
                    return True
            except Exception:
                continue
        return False

    def _pn_lag_check(self):
        rpc = self.rpc
        hu = getattr(rpc, "head_url", None)
        if not hu or not callable(getattr(rpc, "pn_open", None)) or rpc.pn_open():
            return
        ref = rpc.url if not (rpc.primary_open() or rpc.hl_closed()) else getattr(rpc, "archive_url", None)
        if not ref:
            return
        try:
            pn = rpc._call(hu, "getSlot", [{"commitment": "finalized"}], timeout=rpc.head_timeout)
            if not isinstance(pn, int) or isinstance(pn, bool):
                raise RuntimeError("getSlot 형식")
        except Exception as e:
            rpc._pn_note(False, f"getSlot: {e}")
            return
        try:
            with rpc.as_kind("head"):
                rs = int(rpc._call(ref, "getSlot", [{"commitment": "finalized"}]))
        except Exception:
            return
        rpc.pn_lag = rs - int(pn)
        if rpc.pn_lag > rpc.head_lag_max:
            rpc.pn_fault(f"최신 슬롯이 {rpc.pn_lag}슬롯 뒤(기준 {common.redact_urls(ref)})", HEAD_TRIP_BASE * 5)
        else:
            rpc._pn_note(True)

    PN_SEEN_LAG = 120

    def _pn_audit(self):
        rpc = self.rpc
        n_aud = int(getattr(rpc, "head_audit_n", 0) or 0)
        if n_aud <= 0 or not callable(getattr(rpc, "hint", None)):
            return
        if rpc.primary_open() or rpc.hl_closed():
            return
        ents = {k[5:]: v for k, v in self.cursor.items() if k.startswith("_pnv:") and isinstance(v, dict)}
        cands = [x for x in ents if x in self.cursor and not self.cursor.get("_pnmiss:" + x)]
        if not cands:
            return
        first = sorted(x for x in cands if x in self._retiring)
        rest = sorted(x for x in cands if x not in self._retiring)
        picked = first[:n_aud]
        k_rest = min(len(rest), n_aud - len(picked))
        picked += [rest[(self._audit_i + k) % len(rest)] for k in range(k_rest)]
        self._audit_i += k_rest
        stake9 = self.stake_reg()
        fault = 0
        for a in picked:
            e = ents[a]
            cut = int(stake9[a].get("t0") or 0) if a in stake9 else int(self.cutoff_ts or 0)
            chk = e.get("chk") if isinstance(e.get("chk"), dict) else None
            if chk is None:
                ts9 = self.cursor.get("_slot:" + a)
                chk = {"at": time.time(), "top": self.cursor.get(a) or "", "tslot": ts9 if isinstance(ts9, int) and not isinstance(ts9, bool) else None,
                       "pn": float(e.get("pn") or 0), "before": None}
            anc = e.get("sig") or ""
            miss = list(self.cursor.get("_pnmiss:" + a) or [])
            have = {m.get("signature") for m in miss if isinstance(m, dict)}
            reached, pages, bad = False, 0, 0
            try:
                while pages < HEAD_AUDIT_PAGES:
                    opt = {"limit": SIG_PAGE, "commitment": "finalized"}
                    if anc:
                        opt["until"] = anc
                    if chk.get("before"):
                        opt["before"] = chk["before"]
                    with rpc.as_kind("head"), rpc.hint(only="primary"):
                        res = rpc.call("getSignaturesForAddress", [a, opt])
                    if not isinstance(res, list):
                        raise RuntimeError("형식")
                    pages += 1
                    past_cut = False
                    for r in res:
                        if not isinstance(r, dict) or not isinstance(r.get("signature"), str):
                            continue
                        s9, sl9, bt9 = r["signature"], r.get("slot"), r.get("blockTime")
                        if cut and isinstance(bt9, int) and bt9 < cut:
                            past_cut = True
                            continue
                        if s9 in self.emitted or s9 in have:
                            continue
                        due9 = ((chk["tslot"] is not None and isinstance(sl9, int) and sl9 <= chk["tslot"]) or s9 == chk["top"]
                                or (isinstance(bt9, int) and chk["pn"] > 0 and bt9 <= chk["pn"] - self.PN_SEEN_LAG))
                        if due9:
                            miss.append({"signature": s9, "slot": sl9, "blockTime": bt9})
                            have.add(s9)
                            bad += 1
                    if res:
                        chk["before"] = res[-1]["signature"]
                    if len(res) < SIG_PAGE or past_cut:
                        reached = True
                        break
            except Exception as e9:
                log.debug("publicnode 대조 %s 실패(다음 차례에 이어서): %s", a[:8], e9)
            if miss:
                self.cursor["_pnmiss:" + a] = miss
            if bad:
                fault += bad
                rpc.pn_n["audit_miss"] += 1
                log.error("★publicnode 대조: %s 받았어야 할 서명 %d건을 못 받았음(공개 노드 목록 누락) — 다음 사이클에 헬리우스로 받음★", a[:8], bad)
            if reached:
                rpc.pn_n["audit_ok"] += 1
                if chk["top"]:
                    e["sig"], e["slot"] = chk["top"], chk["tslot"]
                e.pop("chk", None)
                if float(e.get("pn") or 0) < float(chk["at"]) and not miss:
                    self.cursor.pop("_pnv:" + a, None)
            else:
                e["chk"] = chk
        common.atomic_write_json(self.cursor_path, self.cursor)
        if fault:
            rpc.pn_fault(f"대조 누락 {fault}건", HEAD_AUDIT_TRIP_SEC)

    def _health_cycle(self, full, addrs, addr_sigs, fail_list, done_ok, held=()):
        hb = bf_engine.health("sol")
        n_addr = len(dict.fromkeys(addrs)) - len(set(held))
        ok = done_ok and not fail_list and len(addr_sigs) == n_addr
        self._fail_cycles = 0 if ok else getattr(self, "_fail_cycles", 0) + 1
        if fail_list:
            lv = bf_engine.LogDebounce.level(self._fail_cycles) or "debug"
            getattr(log, lv)("서명 조회 실패 %d/%d 주소 (연속 %d사이클, 커서 유지·다음 주기 재시도) — 예: %s", len(fail_list),
                             n_addr, self._fail_cycles, "; ".join(f"{a}: {e}" for a, e in fail_list[:2]))
        slot = None
        if full:
            try:
                slot = int(self.rpc.call("getSlot", [{"commitment": "finalized"}]))
            except Exception:
                slot = None
        newest = max((r[0].get("blockTime") or 0 for r in addr_sigs.values() if r), default=0) or None
        facts = dict(addresses=n_addr, addresses_failed=len(fail_list), full_cycle=full,
                     head=slot if slot is not None else hb.src.get("sol", {}).get("head"),
                     newest_sig_block_time=newest, synced_at=self.cursor.get("_synced_at"),
                     primary=("open" if self.rpc.primary_open() else "ok"),
                     primary_open_until=int(self.rpc.primary_open_until) if self.rpc.primary_open() else None,
                     current_source=common.redact_urls(self.rpc.fallbacks[0] if (self.rpc.primary_open() and self.rpc.fallbacks)
                                                       else self.rpc.url),
                     rl_429_total=self.rpc.rl_seen, consecutive_failed_cycles=self._fail_cycles,
                     spooling=[k[7:15] for k in self.cursor if k.startswith("_sigbf:")],
                     helius_used=bf_engine.HELIUS.used()[0] if getattr(self.rpc, "metered", False) else None,
                     helius_budget=bf_engine.HELIUS.budget if getattr(self.rpc, "metered", False) else None,
                     helius_daycap_until=None,
                     fill_wait=len(set(held)))
        if callable(getattr(self.rpc, "pn_state", None)):
            pn9 = self.rpc.pn_state()
            facts.update(head_rpc=pn9["host"], head_rpc_on=pn9["on"], head_rpc_ok=pn9["healthy"],
                         head_rpc_rate=(round(pn9["rate"], 4) if pn9["rate"] is not None else None), head_rpc_n=pn9["n"],
                         head_rpc_open_until=int(pn9["open_until"]) if pn9["open_until"] else None, head_rpc_why=pn9["why"], head_rpc_lag=pn9["lag"],
                         head_rpc_audit=dict(self.rpc.pn_n),
                         archive_rpc=common.redact_urls(self.rpc.archive_url) if getattr(self.rpc, "archive_url", None) else None,
                         helius_closed_until=int(self.rpc.hl_closed_until) if self.rpc.hl_closed() else None,
                         pn_unverified=sum(1 for k9 in self.cursor if k9.startswith("_pnv:")),
                         helius_head_min=round(float(getattr(bf_engine.HELIUS, "head_min", 0.1)), 4) if getattr(self.rpc, "metered", False) else None)
            if self.rpc.hl_closed() and pn9["on"]:
                facts["current_source"] = pn9["host"]
            if self.rpc.hl_closed():
                facts["helius_daycap_until"] = int(self.rpc.hl_closed_until)
                facts["helius_continue"] = bool(self.rpc.can_continue_capped())
        if ok:
            hb.ok("sol", "sol_rpc", **facts)
        else:
            hb.fail("sol", RuntimeError("; ".join(f"{a}: {e}" for a, e in fail_list[:3]) or
                                        ("tx 파싱/방출 실패" if not done_ok else "부분 조회")), "sol_rpc", **facts)
        hb.flush()


def _hl_paced(rpc) -> bool:
    m9 = bf_engine.HELIUS
    return bool(getattr(rpc, "metered", False)) and not (callable(getattr(rpc, "hl_closed", None)) and rpc.hl_closed()) \
        and bool(getattr(m9, "fill_first", False)) and float(getattr(m9, "burst", 1.0)) < 1.0


def _pn_ok(rpc) -> bool:
    try:
        return bool(callable(getattr(rpc, "pn_ok", None)) and rpc.pn_ok())
    except Exception:
        return False


def rest_if_capped(w) -> bool:
    if not w.rpc.day_capped():
        if callable(getattr(w.rpc, "hl_open", None)) and getattr(w.rpc, "hl_closed_until", 0):
            w.rpc.hl_open()
        return True
    until9 = (int(time.time()) // 86400 + 1) * 86400 + 60
    cont9 = callable(getattr(w.rpc, "can_continue_capped", None)) and w.rpc.can_continue_capped()
    hb9 = bf_engine.health("sol")
    hb9.facts("sol", helius_daycap_until=until9, helius_used=bf_engine.HELIUS.used()[0], helius_budget=bf_engine.HELIUS.budget,
              helius_continue=bool(cont9))
    hb9.flush()
    if cont9:
        w.rpc.hl_close_until(until9)
        if time.time() - getattr(w, "_cap_log", 0) >= 1800:
            w._cap_log = time.time()
            log.warning("헬리우스 하루 예산 %d 크레딧 소진 — %s 까지 헬리우스 없이 이어 감(새 거래 확인 = 공개 노드 · 옛 기록 = 아카이브 공개 노드)",
                        bf_engine.HELIUS.budget, time.strftime("%H:%M", time.localtime(until9)))
        return True
    if time.time() - getattr(w, "_cap_log", 0) >= 1800:
        w._cap_log = time.time()
        log.warning("헬리우스 하루 예산 %d 크레딧 소진 — %s 까지 솔라나 수집 쉼(기록은 그대로, 풀리면 커서부터 이어 받음)", bf_engine.HELIUS.budget,
                    time.strftime("%H:%M", time.localtime(until9)))
    return False


def rest_if_paced(w) -> bool:
    if not getattr(w.rpc, "metered", False):
        return True
    if callable(getattr(w.rpc, "hl_closed", None)) and w.rpc.hl_closed():
        return True
    m9 = bf_engine.HELIUS
    if not getattr(m9, "fill_first", False) or m9.burst >= 1.0:
        return True
    full9 = w.full_due()
    pn9 = _pn_ok(w.rpc)
    costs9 = getattr(w, "_hl_cost", None) or {}

    def _need(k):
        if pn9:
            if k == "own":
                return 0
            c = costs9.get(k + "_pn")
            c = w.hl_full_est() if c is None else int(c)
            return 0 if c <= 0 else max(1, min(c, m9.keep_credits()))
        c = costs9.get(k)
        c = 1 if c is None else int(c)
        if c <= 0:
            return 1
        return max(1, min(c, m9.keep_credits()))
    need = _need("full" if full9 else "own")
    room = m9.room("head", proc=w.rpc.proc)
    if need <= 0 or room >= need:
        return True
    if full9 and _need("own") <= 0:
        w._own_only = True
        return True
    now9 = int(time.time())
    hb9 = bf_engine.health("sol")
    hb9.facts("sol", paced_at=now9, helius_used=m9.used()[0], helius_budget=m9.budget)
    hb9.flush()
    if time.time() - getattr(w, "_paced_log", 0) >= 1800:
        w._paced_log = time.time()
        log.info("헬리우스 새 거래 확인 몫 대기(옛 기록 먼저 채우는 중이면 하루 예산 %.0f%% 안에서) — %s 사이클 %d 크레딧 · 지금 여유 %d(기록은 그대로, 다음 주기에 이어 받음)",
                 float(getattr(m9, "head_min", 0.1)) * 100, "전체" if full9 else "소유자", need, room)
    return False


def _floor_tick(w):
    rpc = w.rpc
    m9 = bf_engine.HELIUS
    if not getattr(rpc, "metered", False) or not getattr(m9, "fill_first", False) or not getattr(rpc, "head_url", None):
        return
    cfg9 = getattr(w, "cfg", None) or {}
    hi9 = bf_engine.helius_head_min(cfg9)
    now9 = time.time()
    if rpc.pn_state()["healthy"]:
        with m9.lock:
            hu9 = int(m9.st.get("nh") or 0) + int(m9.st.get("others_h") or 0)
            yd9 = m9.st.get("yday_h")
        hm9 = bf_engine.helius_head_min_pn(cfg9, hu9, yd9, now9, m9.budget)
    else:
        hm9 = hi9
    with m9.lock:
        m9.hm_pub = True
        m9.head_min = hm9


def run_cycle(w) -> bool:
    if not rest_if_capped(w):
        return False
    try:
        _floor_tick(w)
    except Exception as e:
        log.debug("실시간 하한 조정 실패: %s", e)
    try:
        paced_ok = rest_if_paced(w)
    except Exception as e:
        log.warning("헬리우스 새 거래 확인 몫 판정 실패(이번 사이클은 그대로 돌림): %s", str(e)[:160])
        paced_ok = True
    if not paced_ok:
        return False
    full9 = w.full_due() and not getattr(w, "_own_only", False)
    m9 = bf_engine.HELIUS
    d0, h0 = m9.st.get("day"), int(m9.st.get("nh") or 0)
    pn0 = _pn_ok(w.rpc)
    g0 = int(getattr(w.rpc, "_pn_gen", 0) or 0)
    try:
        w.cycle()
        tsfix.repair("sol", lambda s9: tsfix.block_ts(w, s9, fn=w._block_time), w.writer)
    except Exception as e:
        n9 = bf_engine.health("sol").fail("sol", e, "sol_rpc")
        bf_engine.health("sol").flush()
        lv = bf_engine.LogDebounce.level(n9)
        if lv:
            getattr(log, lv)("cycle 실패 %d회 연속(다음 주기 재시도): %s", n9, e)
    finally:
        if getattr(w.rpc, "metered", False) and m9.st.get("day") == d0 and d0 is not None:
            pn1 = _pn_ok(w.rpc)
            if pn1 == pn0 and int(getattr(w.rpc, "_pn_gen", 0) or 0) == g0:
                w.__dict__.setdefault("_hl_cost", {})[("full" if full9 else "own") + ("_pn" if pn0 else "")] = max(0, int(m9.st.get("nh") or 0) - h0)
    return True


def main():
    common.ensure_dirs()
    cfg = common.load_config()
    bf_engine.configure(cfg)
    addr_tier.ACTIVE_PROC = True
    bf_engine.es_budget_install_sigterm()
    wallets = [w["address"] for w in cfg["wallets"] if w.get("type") == "sol"]
    if not wallets:
        raise SystemExit("추적할 SOL 지갑이 없음 — config.wallets 확인")
    poll = int(cfg.get("sol", {}).get("poll_sec", 60))
    writer = SegmentWriter(os.path.join(common.INBOX_DIR, "sol"))
    w = SolWatcher(cfg, wallets, writer)
    log.info("가동: %d지갑, %d초 주기", len(wallets), poll)
    while True:
        t0 = time.time()
        run_cycle(w)
        time.sleep(max(5.0, poll - (time.time() - t0)))


if __name__ == "__main__":
    main()
