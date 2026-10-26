from __future__ import annotations
from collections import deque
import contextlib
import json
import os
import threading
import time
import urllib.request
import envfile, logs, net_http
import bf_engine
import logging

log = logging.getLogger('tj-sol')

TX_BATCH_SLEEP = 0.12


BUDGET_WARN_PER_HOUR = 20000


RL_WAIT_MAX = 30.0


PRIMARY_TRIP_STREAK = 3


HL_COST = {"getProgramAccounts": 10, "getAsset": 10, "getAssetBatch": 10, "getAssetsByOwner": 10, "searchAssets": 10}


PRIMARY_QUOTA_OPEN = 1800.0


PRIMARY_RL_OPEN = 60.0


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


ARCHIVE_PER10S = 32


ARCHIVE_METHOD_PER10S = 8


HEAD_METHODS = frozenset({"getSignaturesForAddress", "getTransaction", "getSlot", "getEpochInfo", "getAccountInfo", "getBalance",
                          "getMultipleAccounts", "minimumLedgerSlot", "getFirstAvailableBlock"})


STAKE_PROGRAM = "Stake11111111111111111111111111111111111111"


STAKE_WITHDRAWER_OFFSET = 44


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
    except Exception:  # noqa: BLE001 [fallback]
        return None


class Rpc:
    def __init__(self, cfg: dict):
        key = os.environ.get("TJ_HELIUS_KEY", "")
        if not key:
            key = envfile.read_env_file().get("TJ_HELIUS_KEY", "")
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
        self._pn_why = logs.redact_urls(str(why))[:160]
        if trip or self._pn_streak >= HEAD_TRIP_STREAK:
            self.pn_fault(why, min(HEAD_TRIP_BASE * (2 ** self._pn_open_n), HEAD_TRIP_MAX))
            self._pn_open_n += 1

    def pn_fault(self, why: str, dur: float):
        self._pn_open_until = max(self._pn_open_until, time.time() + float(dur))
        self._pn_gen = int(getattr(self, "_pn_gen", 0) or 0) + 1
        self._pn_streak = 0
        self._pn_why = logs.redact_urls(str(why))[:160]
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
                "why": self._pn_why or None, "host": logs.redact_urls(self.head_url) if self.head_url else None, "lag": self.pn_lag}

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
                    raise _PnSkip("커서를 못 찾음(-32020) · 커서 슬롯 모름 — 헬리우스로") from e
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
                except Exception as e:   # noqa: BLE001 [fallback]
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
                        except Exception as e2:  # noqa: BLE001 [fallback]
                            e_prim = e2
                except Exception as e:  # noqa: BLE001 [fallback]
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
            except Exception as e:  # noqa: BLE001 [fallback]
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
            elif bf_engine.HELIUS.window_on():
                if not bf_engine.HELIUS.take_hard(self.proc, c9, kind=self.kind()):
                    raise RuntimeError(f"rpc {method}: 헬리우스 월 창 몫 없음({bf_engine.HELIUS.last_why()}) — 다른 노드로")
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
        req = net_http.request(url, data=body,
                               headers={"Content-Type": "application/json",
                                        "User-Agent": "tj-bot/0.1"})
        try:
            with bf_engine.sol_open(req, timeout, method, sol=True) as r:
                d = json.loads(net_http.read_capped(r).decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                self.rl_seen += 1
                self.rl_last = True
                try:
                    body = (e.read(net_http.HTTP_ERR_BODY_MAX) or b"")[:200].decode("utf-8", "replace").lower()
                except Exception:  # noqa: BLE001 [fallback]
                    body = ""
                raise RateLimited(f"HTTP Error 429: Too Many Requests ({method})",
                                  _retry_after_sec(e.headers.get("Retry-After") if e.headers else None),
                                  quota=("max usage" in body or "quota" in body or "credits" in body)) from e
            raise
        if url == self.url:
            self.rl_streak = 0
        if "error" in d:
            raise RuntimeError(f"rpc {method}: {logs.redact_secret_text(str(d['error']))}")
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
                    except Exception as e9:   # noqa: BLE001 [isolate]
                        out.append(e9)
                return out
            if url == self.url and self.metered:
                bf_engine.HELIUS.add(self.proc, len(params_list) * HL_COST.get(method, 1), kind=self.kind())
            now = time.monotonic()
            self.calls.append(now)
            req = net_http.request(url, data=body, headers={"Content-Type": "application/json",
                                                             "User-Agent": "tj-bot/0.1"})
            try:
                with bf_engine.sol_open(req, timeout) as r:
                    d = json.loads(net_http.read_capped(r).decode())
            except urllib.error.HTTPError as e:
                if e.code == 429 and url == self.url:
                    try:
                        b9 = (e.read(net_http.HTTP_ERR_BODY_MAX) or b"")[:200].decode("utf-8", "replace").lower()
                    except Exception:  # noqa: BLE001 [fallback]
                        b9 = ""
                    self.rl_seen += 1
                    self._trip_primary(RateLimited("HTTP Error 429 (batch)", quota="max usage" in b9 or "quota" in b9))
                last = e
                continue
            except Exception as e:  # noqa: BLE001 [isolate]
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
                    out[i] = RuntimeError(f"rpc {method}: {logs.redact_secret_text(str(it['error']))}")
                elif it.get("result") is None:
                    out[i] = RuntimeError(f"rpc {method}: result null")
                else:
                    try:
                        if method == "getTransaction":
                            _check_tx_result(it["result"])
                        out[i] = it["result"]
                    except Exception as e9:  # noqa: BLE001 [fallback]
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


def _hl_paced(rpc) -> bool:
    m9 = bf_engine.HELIUS
    return bool(getattr(rpc, "metered", False)) and not (callable(getattr(rpc, "hl_closed", None)) and rpc.hl_closed()) \
        and bool(getattr(m9, "fill_first", False)) and float(getattr(m9, "burst", 1.0)) < 1.0
