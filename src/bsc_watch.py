"""BNB Smart Chain wallet watcher."""
from __future__ import annotations

import bisect
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
if __name__ == "__main__":
    common.cpu_reserve_apply()
import bf_engine
from inbox import SegmentWriter

log = common.setup_logging("tj-bsc")

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
DEPOSIT_TOPIC = "0xe1fffcc4923d04b559f4d29a8bfc6cda04eb5b0d3c460751c2402c5c5cc9109c"
WITHDRAWAL_TOPIC = "0x7fcf532c15f0a6db0bd6d0e038bea71d30d808c7d98cb3bf7268a95bf5081b65"
ZERO_ADDR = "0x0000000000000000000000000000000000000000"
BLOCKS_PER_DAY = 28800
CALL_SLEEP = 0.25


_now = time.time
NONCE_EVERY = 3600
NONCE_BACKLOG_EVERY = 170
NONCE_HEAD_EVERY = 45
NONCE_RECENT_SEC = 7200
NONCE_OLD_BURST = 300
NONCE_MAX_FIND = 20
NONCE_CALL_CAP = 30
NONCE_PUB_CAP = 400
NONCE_TOP_BATCH = 16
NONCE_ARCH_GAP = 0.5
NONCE_BO_BASE = 300
NONCE_BO_MAX = 3600
NONCE_NARROW = 4096
NONCE_HINT_NEAR = 300
NONCE_HINT_FAR = 3000
NONCE_HINT_KEEP = 7 * 86400
XIN_EVERY = 3600
XIN_MAX_NEW = 10
XIN_NF_MAX = 6
BALW_EVERY = 60
BALW_EVERY_ARCH = 900
BALW_DUST = 10 ** 13
BALW_CALL_CAP = 24
BALW_DAY_CAP = 3000
BALW_TIME_CAP = 20.0
BALW_JOB_CALLS = 160
BALW_JOB_KEEP = 7 * 86400
BALW_JOBS_MAX = 20
BALW_STALE = 1800
BALW_NOSTATE_N = 3
BALW_HIST_RETRY = 600
BALW_BACK_MIN = 6
BALW_RX_MAX_H = 24 * 400
BALW_NONCE_STUCK = 2 * 3600
BALW_HIST_DAYS = 30
BALW_HIST_GAP = 86400
BALW_BO_BASE = 300
BALW_BO_MAX = 3600
BALW_PUB_NEAR = 80
BALW_PUB_SCAN = 256
BALW_SCAN_BATCH = 4
BALW_SCAN_RUN = 64
DISC_REQ_NAME = "disc_open_request.json"
BALW_RX_NAME = "bsc_balw_recheck.json"
LANE_SPLIT_SEC = 2 * 3600
LIVE_SEED_SEC = 3600
BSC_BLOCK_SEC = 0.45
_XIN_TXID = re.compile(r"^0x[0-9a-f]{64}$")
_XIN_NET = re.compile(r"BSC|BEP-?20|SMART|^BNB$", re.I)
_XIN_NF = re.compile(r"^(?:미확정 tx: .*|(?:rpc )?eth_getTransaction(?:ByHash|Receipt): result null)$")


def _xin_not_found(err) -> bool:
    return bool(_XIN_NF.match(str(err)))


def _touches(snap: dict, w: str) -> bool:
    tx = snap.get("tx") or {}
    if w in (str(tx.get("from") or "").lower(), str(tx.get("to") or "").lower()):
        return True
    for key in ("token_transfers", "internal"):
        for r in snap.get(key) or []:
            if isinstance(r, dict) and w in (str(r.get("from") or "").lower(), str(r.get("to") or "").lower()):
                return True
    return False


def _native_delta(snap: dict, w: str):
    tx = snap.get("tx") or {}
    ok = tx.get("status") == "ok"
    try:
        val = int(str(tx.get("value") or "0"))
        fee = int(str((tx.get("fee") or {}).get("value") or "0"))
    except (TypeError, ValueError):
        return None
    sent = str(tx.get("from") or "").lower() == w
    d = 0
    if sent:
        d -= fee + (val if ok else 0)
    if ok and str(tx.get("to") or "").lower() == w:
        d += val
    if ok:
        for r in snap.get("internal") or []:
            if not isinstance(r, dict) or r.get("success") is False or r.get("error"):
                continue
            try:
                v = int(str(r.get("value") or "0"))
            except (TypeError, ValueError):
                continue
            if str(r.get("to") or "").lower() == w:
                d += v
            if str(r.get("from") or "").lower() == w:
                d -= v
    return d, sent


class _SentTap:

    def __init__(self, inner, owner):
        self.inner = inner
        self._owner = owner

    def append(self, rec):
        r = self.inner.append(rec)
        try:
            self._owner._nonce_note(rec)
        except Exception as e:
            log.debug("nonce 색인 기록 실패: %s", e)
        try:
            self._owner._balw_note(rec)
        except Exception as e:
            log.debug("잔고 감시 색인 기록 실패: %s", e)
        return r

    def __getattr__(self, k):
        return getattr(self.inner, k)


_NONCE_STOP_KINDS = ("http429", "quota", "circuit")
_NONCE_NEXT_KINDS = ("pruned", "null", "http5xx", "http4xx", "timeout", "conn", "dns", "payload")
_ARCHIVE_HOST_HINTS = ("nodereal", "ankr.com", "quiknode.pro")


def _archive_like(url) -> bool:
    try:
        host = (urllib.parse.urlsplit(str(url)).hostname or "").lower()
    except ValueError:
        return False
    return any(k in host for k in _ARCHIVE_HOST_HINTS)


class _PubDown(RuntimeError):
    pass


class _NonceBudget(RuntimeError):
    pass


class _BalwStop(RuntimeError):
    pass


class _BalwNoArch(RuntimeError):
    pass


class _BalwNoState(_BalwNoArch):
    pass


def _balw_nostate(e) -> bool:
    if isinstance(e, bf_engine.NetError):
        return e.kind in ("pruned", "null")
    return isinstance(e, RuntimeError) and "result null" in str(e)


def _nonce_why(e) -> str:
    parts = [str(x) for x in (getattr(e, "host", None), getattr(e, "kind", None)) if x]
    msg = common.safe_err(e)[:160]
    return (" · ".join(parts) + " — " + msg) if parts else msg


class _NView:

    def __init__(self, w: str, ws: dict, lo_blk: int):
        self.w, self.ws, self.lo_blk = w, ws, int(lo_blk)
        self.skip = False
        self.smp = {}
        ns = ws.get("ns")
        for k, v in (ns.items() if isinstance(ns, dict) else ()):
            try:
                b, n = int(k), int(v)
            except (TypeError, ValueError):
                continue
            if b >= self.lo_blk and n >= 0:
                self.smp[b] = n
        lo = ws.get("lo")
        self.lo_n = None
        if isinstance(lo, list) and len(lo) == 2 and lo[0] == self.lo_blk and isinstance(lo[1], int) and not isinstance(lo[1], bool):
            self.lo_n = lo[1]
            self.smp[self.lo_blk] = lo[1]
        t = ws.get("top")
        self.top = t if (isinstance(t, int) and t > self.lo_blk and t in self.smp) else None
        ta = ws.get("top_at")
        self.top_at = float(ta) if isinstance(ta, (int, float)) and not isinstance(ta, bool) and self.top is not None else 0.0
        self.reindex()

    def ready(self) -> bool:
        return self.lo_n is not None and self.top is not None

    def set_lo(self, n: int):
        self.lo_n = int(n)
        self.ws["lo"] = [self.lo_blk, self.lo_n]
        self.smp[self.lo_blk] = self.lo_n

    def reindex(self):
        hs = self.ws.get("hashes") or {}
        top = self.top if self.top is not None else (1 << 62)
        self.blocks = sorted(b for b in hs.values() if isinstance(b, int) and self.lo_blk < b <= top)
        ex = self.ws.get("nonce_extra") or {}
        self.ex = sorted((int(k), int(n)) for k, n in (ex.items() if isinstance(ex, dict) else ())
                         if str(k).isdigit() and self.lo_blk < int(k) and str(n).lstrip("-").isdigit())

    def known_le(self, b: int) -> int:
        return bisect.bisect_right(self.blocks, b) + sum(n for k, n in self.ex if k <= b)

    def D(self, b: int) -> int:
        return self.smp[b] - self.lo_n - self.known_le(b)

    def missing(self) -> int:
        return self.D(self.top)

    def intervals(self) -> tuple:
        pts = sorted(b for b in self.smp if self.lo_blk <= b <= self.top)
        out, bad, prev = [], False, None
        for b in pts:
            d = self.D(b)
            if prev is not None:
                if self.smp[b] < self.smp[prev[0]] or d < prev[1]:
                    bad = True
                elif d > prev[1]:
                    out.append((prev[0], b, d - prev[1]))
            prev = (b, d)
        return out, bad

    def open_at(self, p: int) -> bool:
        a = max((b for b in self.smp if b < p), default=None)
        z = min((b for b in self.smp if b > p and b <= self.top), default=None)
        return a is not None and z is not None and self.D(z) - self.D(a) > 0

    def reset(self):
        self.smp = {b: n for b, n in self.smp.items() if b in (self.lo_blk, self.top)}

    def prune(self):
        ivs, bad = self.intervals()
        keep = {self.lo_blk, self.top}
        if not bad:
            for a, z, _d in ivs:
                keep.update((a, z))
        self.smp = {b: n for b, n in self.smp.items() if b in keep}

    def save(self):
        self.ws["ns"] = {str(b): n for b, n in sorted(self.smp.items())}
        if self.top is not None:
            self.ws["top"] = self.top
            self.ws["top_at"] = int(self.top_at)


def _pad_topic(addr: str) -> str:
    return "0x" + addr.lower().replace("0x", "").rjust(64, "0")


class Rpc:
    def __init__(self, urls: list, rotate_each: bool = False):
        self.urls = urls
        self.i = 0
        self.rotate_each = rotate_each

    def call(self, method: str, params, timeout=25):
        last = None
        if self.rotate_each:
            self.i = (self.i + 1) % len(self.urls)
        order = [(self.i + k) % len(self.urls) for k in range(len(self.urls))]
        ready = [j for j in order if not bf_engine.gate(self.urls[j]).is_open()]
        for j in (ready or order):
            kw9 = self._dl_kw()
            self.i = j
            url = self.urls[j]
            try:
                d = {"result": bf_engine.rpc_call(url, method, params, timeout=timeout, retries=1, allow_null=True, **kw9)}
                if method == "eth_getLogs" and not isinstance(d.get("result"), list):
                    raise RuntimeError(f"getLogs 비정상 result: {type(d.get('result')).__name__}")
                if d.get("result") is None:
                    raise RuntimeError(f"{method}: result null")
                return d.get("result")
            except _BalwStop:
                raise
            except Exception as e:
                last = e
                self.i = (j + 1) % len(self.urls)
                time.sleep(0.2)
        raise last

    def _dl_kw(self) -> dict:
        dl = self.__dict__.get("_dl")
        if dl is None:
            return {}
        left = float(dl) - time.time()
        if left <= 0:
            raise _BalwStop("잔고 감시 시간 상한(노드 호출 전)")
        return {"deadline": float(dl), "sem_timeout": left}


    def batch(self, calls: list, timeout=30):
        last = None
        for _attempt in range(len(self.urls)):
            url = self.urls[self.i]
            try:
                res = []
                cap = bf_engine.gate(url).batch_cap(max(1, len(calls)))
                for i9 in range(0, len(calls), cap):
                    res += bf_engine.rpc_batch(url, calls[i9:i9 + cap], timeout=timeout, retries=1, **self._dl_kw())
                if res and all(isinstance(r, Exception) for r in res):
                    raise res[0]
                return res
            except _BalwStop:
                raise
            except Exception as e:
                last = e
                self.i = (self.i + 1) % len(self.urls)
        raise last if last else RuntimeError("batch: 노드 없음")


def _valid_meta(m) -> dict:
    out = {}
    bad = []
    for ca, v in (m.items() if isinstance(m, dict) else ()):
        d = v[1] if isinstance(v, list) and len(v) >= 2 else None
        if isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= 77:
            out[str(ca).lower()] = [v[0], d]
        else:
            bad.append(str(ca)[:10])
    if bad:
        log.warning("BSC 토큰 메타 캐시 이상 자리수 %d개 버림(다시 조회): %s", len(bad), ", ".join(bad[:5]))
    return out


def _dec_string(hexdata: str) -> str | None:
    try:
        h = hexdata[2:] if hexdata.startswith("0x") else hexdata
        if not h:
            return None
        b = bytes.fromhex(h)
        if len(b) == 32:
            return b.rstrip(b"\x00").decode("utf-8", "ignore") or None
        if len(b) >= 64:
            ln = int.from_bytes(b[32:64], "big")
            return b[64:64 + ln].decode("utf-8", "ignore") or None
    except Exception:
        pass
    return None


class BscWatcher:
    def __init__(self, cfg: dict, wallets: list, writer: SegmentWriter):
        bc = cfg["bsc"]
        self.logs_rpc = Rpc(bc["logs_rpcs"], rotate_each=True)
        arch = [str(u) for u in (bc.get("archive_rpcs") or [u for u in bc.get("logs_rpcs") or [] if "nodereal" in str(u)])]
        self.rpc = Rpc(list(bc["detail_rpcs"]) + [u for u in arch if u not in bc["detail_rpcs"]])
        self._arch_urls = list(dict.fromkeys(arch + [str(u) for u in list(bc["detail_rpcs"]) + list(bc.get("logs_rpcs") or []) if _archive_like(u)]))
        self.arch_rpc = Rpc(list(self._arch_urls)) if self._arch_urls else None
        pub9 = [u for u in bc["detail_rpcs"] if u not in self._arch_urls]
        self.nonce_pub_rpc = Rpc(pub9) if pub9 else None
        self.logs_sleep = float(bc.get("logs_sleep_sec", 1.2))
        self.span = int(bc.get("getlogs_span", 5000))
        self.logs_fb = {str(u): int(c) for u, c in (bc.get("logs_rpcs_fallback") or {}).items() if int(c) > 0}
        self.canary = None if bc.get("canary") is False else bf_engine.BSC_CANARY
        self.conf_depth = int(bc.get("conf_depth", 20))
        self.backfill_days = bf_engine.bsc_backfill_days(cfg)
        self.poll_sec = float(bc.get("poll_sec", 60))
        self.lanes_cfg = bc.get("lanes")
        try:
            self.lane_budget = float(bc["lane_budget_sec"]) if bc.get("lane_budget_sec") is not None else None
        except (TypeError, ValueError):
            self.lane_budget = None
        self.wallets = [w.lower() for w in wallets]
        self.wrapped_ca = str((cfg.get("wrapped_native") or {}).get("bsc") or "").lower() or None
        self.discover_wrap = bc.get("discover_wrap") is not False and bool(self.wrapped_ca)
        try:
            self.sell_verify_blocks = max(0, int(bc.get("sell_verify_blocks", self.SELL_WD_RECENT)))
        except (TypeError, ValueError):
            self.sell_verify_blocks = self.SELL_WD_RECENT
        self.wallet_since = bf_engine.wallet_since_map(cfg, "bsc")
        self.topics = [_pad_topic(w) for w in self.wallets]
        self.writer = _SentTap(writer, self)
        self.cursor_path = os.path.join(common.STATE_DIR, "cursor_bsc.json")
        self.cursor = common.read_json(self.cursor_path, {})
        self.meta_path = os.path.join(common.STATE_DIR, "bsc_token_meta.json")
        self.token_meta = _valid_meta(common.read_json(self.meta_path, {}))
        self.nodec = bf_engine.nodec_registry("bsc", log)
        self.emitted_path = os.path.join(common.STATE_DIR, "emitted_bsc.json")
        self.emitted = set(common.read_json(self.emitted_path, []))
        self.block_ts = {}
        self.span_caps = {str(u): int(c) for u, c in (bc.get("getlogs_span_caps") or {}).items()}
        self.scan_workers = int(bc.get("scan_workers", 1))
        self.span_max = int(bc.get("getlogs_span_max", 50000))
        self.detail_batch = max(1, int(bc.get("detail_batch", 8)))
        self.logs_head_guard = bc.get("logs_head_guard") is not False
        self.cycle_budget = float(bc.get("cycle_budget_sec", 600))
        self.progress = bf_engine.progress("bsc")
        self.last_scan_metrics = {}

    def _detail_home(self):
        arch9 = set(getattr(self, "_arch_urls", None) or ())
        rpc9 = getattr(self, "rpc", None)
        urls9 = getattr(rpc9, "urls", None)
        try:
            if arch9 and urls9 and urls9[rpc9.i] in arch9:
                self.rpc.i = next((j for j, u in enumerate(urls9) if u not in arch9), rpc9.i)
        except (IndexError, TypeError, AttributeError):
            pass

    STALE_NODE_BLOCKS = 50

    def head(self) -> int:
        urls = self.rpc.urls
        heads = {}
        first = int(self.rpc.call("eth_blockNumber", []), 16)
        heads[self.rpc.urls[self.rpc.i]] = first
        if len(urls) > 1:
            other = urls[(self.rpc.i + 1) % len(urls)]
            try:
                heads[other] = int(bf_engine.rpc_call(other, "eth_blockNumber", [], timeout=10, retries=1), 16)
            except Exception:
                pass
        top = max(heads.values())
        for u, h9 in heads.items():
            if top - h9 > self.STALE_NODE_BLOCKS:
                g9 = bf_engine.gate(u)
                g9.open_until = max(g9.open_until, time.time() + 60)
                log.info("BSC 노드 %s 헤드 %d 가 %d블록 뒤처짐 — 60초 제외", common.redact_urls(u), h9, top - h9)
        self.node_heads = {common.redact_urls(u): h9 for u, h9 in heads.items()}
        self._log_head = top
        return top

    def token_info(self, ca: str) -> tuple:
        ca = ca.lower()
        if ca in self.token_meta:
            m = self.token_meta[ca]
            return m[0], m[1]
        if self.nodec.perm(ca):
            raise bf_engine.TokenNoDecimals(f"token decimals 영구 불능 {ca[:10]}")
        sym, dec = None, 18
        try:
            r = self.rpc.call("eth_call", [{"to": ca, "data": "0x95d89b41"}, "latest"])
            sym = _dec_string(r or "")
        except Exception:
            sym = None
        time.sleep(CALL_SLEEP)
        try:
            r = self.rpc.call("eth_call", [{"to": ca, "data": "0x313ce567"}, "latest"])
        except Exception as e:
            if bf_engine.revert_like(e) and self.nodec.bad(ca, "revert: " + common.safe_err(e)[:80]):
                raise bf_engine.TokenNoDecimals(f"token decimals 영구 불능 {ca[:10]}: {common.safe_err(e)[:80]}") from e
            raise RuntimeError(f"token decimals 조회 실패 {ca[:10]}: {e}")
        dec, why = bf_engine.decimals_from_result(r)
        if dec is None:
            if self.nodec.bad(ca, why):
                raise bf_engine.TokenNoDecimals(f"token decimals 영구 불능 {ca[:10]}: {why}")
            raise RuntimeError(f"token decimals 조회 실패 {ca[:10]}: decimals {why}")
        self.nodec.ok(ca)
        if isinstance(sym, str):
            sym = sym.strip()[:16] or None
        self.token_meta[ca] = [sym, dec]
        return sym, dec

    def _logs(self, frm: int, to: int, position: int):
        topics = [TRANSFER_TOPIC, None, None]
        topics[1 if position == 0 else 2] = self.topics
        params = [{"fromBlock": hex(frm), "toBlock": hex(to), "topics": topics[:3]}]
        last = None
        for attempt in range(3):
            try:
                res = self.logs_rpc.call("eth_getLogs", params)
                if not isinstance(res, list):
                    raise RuntimeError(f"getLogs 비정상 result: {type(res).__name__}")
                return res
            except Exception as e:
                last = e
                msg = str(e)
                if "429" in msg or "Too Many" in msg:
                    log.info("getLogs 429 — %d초 대기 후 재시도", 30 * (attempt + 1))
                    time.sleep(30 * (attempt + 1))
                    continue
                break
        if self.logs_fb:
            log.warning("getLogs 주 풀 실패(%s) — 비상 폴백 청크 조회 %d-%d", str(last)[:60], frm, to)
            return self._logs_fallback(frm, to, topics[:3])
        raise last if last else RuntimeError("getLogs 429 지속")

    def _logs_fallback(self, frm: int, to: int, topics: list) -> list:
        last = None
        for url, cap in self.logs_fb.items():
            rows, cur, ok = [], frm, True
            one = Rpc([url])
            while cur <= to:
                end = min(cur + cap - 1, to)
                try:
                    chunk = one.call("eth_getLogs", [{"fromBlock": hex(cur), "toBlock": hex(end),
                                                      "topics": topics}])
                    if not isinstance(chunk, list):
                        raise RuntimeError(f"폴백 {common.redact_urls(url)} 청크 {cur}-{end} 비정상 result: {type(chunk).__name__}")
                    rows.extend(chunk)
                except Exception as e:
                    last = e; ok = False
                    log.warning("폴백 %s 청크 %d-%d 실패: %s", common.redact_urls(url), cur, end,
                                common.redact_urls(str(e))[:60])
                    break
                cur = end + 1
                time.sleep(0.3)
            if ok:
                return rows
        raise last if last else RuntimeError("getLogs 폴백 미구성")

    def discover(self, frm: int, to: int, budget_sec: float = 600, on_advance=None, topics=None) -> "tuple | None":
        if to < frm:
            return set(), frm - 1
        eps9, fb9 = list(self.logs_rpc.urls), dict(self.logs_fb or {})
        head9 = self.__dict__.get("_log_head")
        if isinstance(head9, int) and frm >= head9 - bf_engine.RPC_NEAR_HEAD:
            try:
                import nodekeys
                key9 = [u9 for u9 in eps9 if nodekeys.is_key_node(u9)]
            except Exception:
                key9 = []
            if key9 and len(key9) < len(eps9):
                eps9 = [u9 for u9 in eps9 if u9 not in key9]
                for u9 in key9:
                    fb9.setdefault(u9, int(self.span_caps.get(u9) or self.span))
        sc = bf_engine.LogScanner(
            eps9, TRANSFER_TOPIC, list(topics) if topics else self.topics,
            span=max(self.span, self.span_max),
            caps=self.span_caps, fallback=fb9, sleep=self.logs_sleep, timeout=25,
            per_ep_workers=self.scan_workers, log=log, name="bsc getLogs",
            canary=getattr(self, "canary", bf_engine.BSC_CANARY), head_guard=getattr(self, "logs_head_guard", True),
            positions=({1: [TRANSFER_TOPIC, DEPOSIT_TOPIC, WITHDRAWAL_TOPIC], 2: TRANSFER_TOPIC}
                       if getattr(self, "discover_wrap", False) else None))
        found, last_done = sc.scan(frm, to, deadline=time.time() + budget_sec,
                                   on_advance=on_advance)
        self.span_caps.update(sc.caps)
        self.last_scan_metrics = dict(sc.metrics, stop=sc.last_stop)
        if last_done < to:
            log.info("getLogs %d-%d 중 %d 까지 연속 완료 (%s) — 다음 사이클 계속", frm, to, last_done,
                     sc.last_stop or "예산 소진")
        return set(found), last_done

    def _block_time(self, block_hex: str) -> int:
        if block_hex in self.block_ts:
            return self.block_ts[block_hex]
        b = self.rpc.call("eth_getBlockByNumber", [block_hex, False])
        ts = int(b["timestamp"], 16)
        self.block_ts[block_hex] = ts
        if len(self.block_ts) > 5000:
            self.block_ts.clear()
        return ts

    def fetch_detail(self, txhash: str) -> dict:
        r = self.fetch_details([txhash]).get(txhash)
        if isinstance(r, Exception):
            raise r
        if r is None:
            raise RuntimeError(f"미확정 tx: {txhash}")
        return r

    def _fetch_detail_single(self, txhash: str) -> dict:
        tx = self.rpc.call("eth_getTransactionByHash", [txhash])
        time.sleep(CALL_SLEEP)
        rc = self.rpc.call("eth_getTransactionReceipt", [txhash])
        return self._build_snapshot(txhash, tx, rc)

    def _mine_logs(self, rc: dict):
        for lg in rc.get("logs") or []:
            tp = lg.get("topics") or []
            if len(tp) != 3 or tp[0].lower() != TRANSFER_TOPIC:
                continue
            fr9, to9 = ("0x" + tp[1][-40:]).lower(), ("0x" + tp[2][-40:]).lower()
            if fr9 not in self.wallets and to9 not in self.wallets:
                continue
            try:
                val = int(lg.get("data") or "0x0", 16)
            except ValueError:
                continue
            if not val:
                continue
            yield lg, tp, val

    def _wrap_moves(self, rc: dict, tts: list) -> tuple:
        wr = getattr(self, "wrapped_ca", None)
        if not wr:
            return [], []
        cover = {}
        for t in tts:
            if (t.get("token") or {}).get("address") == wr:
                k = (str(t.get("from") or "").lower(), str(t.get("to") or "").lower(), str((t.get("total") or {}).get("value")))
                cover[k] = cover.get(k, 0) + 1
        legs, ints = [], []
        for lg in rc.get("logs") or []:
            tp = lg.get("topics") or []
            if len(tp) != 2 or (lg.get("address") or "").lower() != wr:
                continue
            t0 = (tp[0] or "").lower()
            if t0 not in (DEPOSIT_TOPIC, WITHDRAWAL_TOPIC):
                continue
            who = ("0x" + str(tp[1])[-40:]).lower()
            if who not in self.wallets:
                continue
            try:
                v = int(lg.get("data") or "0x0", 16)
            except ValueError:
                continue
            if not v:
                continue
            fr, to = (ZERO_ADDR, who) if t0 == DEPOSIT_TOPIC else (who, ZERO_ADDR)
            if t0 == WITHDRAWAL_TOPIC:
                ints.append({"from": wr, "to": who, "value": str(v), "success": True})
            k = (fr, to, str(v))
            if cover.get(k):
                cover[k] -= 1
                continue
            sym, dec = self.token_info(wr)
            legs.append({"from": fr, "to": to, "token": {"address": wr, "symbol": sym, "decimals": dec, "type": "ERC-20"},
                         "total": {"value": str(v)}})
        return legs, ints

    SELL_WD_RECENT = 100

    def _sell_unwrap(self, tx: dict, rc: dict, tts: list, ints: list) -> list:
        wr = getattr(self, "wrapped_ca", None)
        f = str(tx.get("from") or "").lower()
        my = set(self.wallets)
        if not wr or f not in my:
            return []
        try:
            if int(tx.get("value") or "0x0", 16):
                return []
        except (TypeError, ValueError):
            return []
        if any(str(t.get("to") or "").lower() in my for t in tts) or any(str(i.get("to") or "").lower() in my for i in ints):
            return []
        if not any(str(t.get("from") or "").lower() == f for t in tts):
            return []
        wd = dep = 0
        src = None
        for lg in rc.get("logs") or []:
            tp = lg.get("topics") or []
            if len(tp) != 2 or (lg.get("address") or "").lower() != wr:
                continue
            t0 = (tp[0] or "").lower()
            who = ("0x" + str(tp[1])[-40:]).lower()
            if who in my or t0 not in (DEPOSIT_TOPIC, WITHDRAWAL_TOPIC):
                continue
            try:
                v = int(lg.get("data") or "0x0", 16)
            except ValueError:
                continue
            if t0 == WITHDRAWAL_TOPIC:
                wd += v
                src = src or who
            else:
                dep += v
        x = wd - dep
        if x <= 0 or not src:
            return []
        amt = self._sell_unwrap_check(f, tx, rc, x)
        if amt <= 0:
            log.info("BSC %s 매도 받은 BNB 추정 %d — 잔고 변화로는 안 받음(받는 사람 다름) · 행 안 만듦", str(tx.get("hash"))[:12], x)
            return []
        return [{"from": src, "to": f, "value": str(amt), "success": True, "attr": "balance_delta"}]

    def _sell_unwrap_check(self, f: str, tx: dict, rc: dict, x: int) -> int:
        pub = getattr(self, "nonce_pub_rpc", None)
        head = getattr(self, "_log_head", None)
        try:
            blk = int(tx["blockNumber"], 16)
            fee = int(rc["gasUsed"], 16) * int(rc.get("effectiveGasPrice") or tx.get("gasPrice") or "0x0", 16)
        except (KeyError, TypeError, ValueError):
            return x
        lim = getattr(self, "sell_verify_blocks", self.SELL_WD_RECENT)
        if pub is None or not isinstance(head, int) or blk < 1 or not lim or head - blk > lim:
            return x
        try:
            res = pub.batch([("eth_getBalance", [f, hex(blk - 1)]), ("eth_getBalance", [f, hex(blk)]),
                             ("eth_getTransactionCount", [f, hex(blk - 1)]), ("eth_getTransactionCount", [f, hex(blk)])], timeout=15)
            b0, b1, n0, n1 = (int(r, 16) for r in res)
        except Exception as e:
            log.info("BSC %s 매도 받은 BNB 잔고 확인 실패(로그 값 사용): %s", str(tx.get("hash"))[:12], common.safe_err(e)[:80])
            return x
        if n1 - n0 != 1:
            return x
        r = b1 - b0 + fee
        if r <= 0:
            return 0
        return min(r, x)

    def _token_info_batch(self, cas):
        cas = sorted(c for c in set(cas) if c not in self.token_meta and not self.nodec.perm(c))
        if not cas:
            return
        calls = []
        for ca in cas:
            calls += [("eth_call", [{"to": ca, "data": "0x95d89b41"}, "latest"]),
                      ("eth_call", [{"to": ca, "data": "0x313ce567"}, "latest"])]
        try:
            res = self.rpc.batch(calls)
        except Exception:
            return
        for j, ca in enumerate(cas):
            sym_r, dec_r = res[2 * j], res[2 * j + 1]
            if isinstance(dec_r, Exception) or not dec_r or dec_r == "0x":
                continue
            dec, _why9 = bf_engine.decimals_from_result(dec_r)
            if dec is None:
                continue
            sym = None if isinstance(sym_r, Exception) else _dec_string(sym_r or "")
            if isinstance(sym, str):
                sym = sym.strip()[:16] or None
            self.token_meta[ca] = [sym, dec]

    def fetch_details(self, hashes, deadline: float = None) -> dict:
        out = {}
        hs = list(dict.fromkeys(h for h in hashes if h))
        B = self.detail_batch
        for i in range(0, len(hs), B):
            chunk = hs[i:i + B]
            if deadline is not None and time.time() > deadline:
                for h in hs[i:]:
                    out[h] = RuntimeError("detail 예산 소진 — 다음 사이클")
                break
            pairs = {}
            try:
                calls = []
                for h in chunk:
                    calls += [("eth_getTransactionByHash", [h]), ("eth_getTransactionReceipt", [h])]
                res = self.rpc.batch(calls)
                for j, h in enumerate(chunk):
                    tx, rc = res[2 * j], res[2 * j + 1]
                    if not isinstance(tx, Exception) and not isinstance(rc, Exception):
                        pairs[h] = (tx, rc)
            except _BalwStop:
                raise
            except Exception as e:
                log.info("상세 배치 실패 → 단건 경로: %s", str(e)[:100])
            try:
                need = sorted({tx["blockNumber"] for tx, rc in pairs.values()
                               if isinstance(tx, dict) and tx.get("blockNumber")
                               and tx["blockNumber"] not in self.block_ts})
                if need:
                    res = self.rpc.batch([("eth_getBlockByNumber", [b9, False]) for b9 in need])
                    for b9, r9 in zip(need, res):
                        if isinstance(r9, dict) and r9.get("timestamp"):
                            self.block_ts[b9] = int(r9["timestamp"], 16)
                cas = {lg.get("address", "").lower() for _tx, rc in pairs.values() if isinstance(rc, dict)
                       for lg, _tp, _v in self._mine_logs(rc)}
                self._token_info_batch(cas)
            except _BalwStop:
                raise
            except Exception as e:
                log.info("블록/메타 배치 실패 → 단건 경로: %s", str(e)[:100])
            for h in chunk:
                try:
                    if h in pairs:
                        out[h] = self._build_snapshot(h, *pairs[h])
                    else:
                        out[h] = self._fetch_detail_single(h)
                except _BalwStop:
                    raise
                except Exception as e:
                    out[h] = e
            time.sleep(CALL_SLEEP)
        return out

    def _build_snapshot(self, txhash: str, tx: dict, rc: dict) -> dict:
        if not tx or not rc or tx.get("blockNumber") is None:
            raise RuntimeError(f"미확정 tx: {txhash}")
        gas_used = int(rc["gasUsed"], 16)
        gas_px = int(rc.get("effectiveGasPrice") or tx.get("gasPrice") or "0x0", 16)
        status = rc.get("status")
        ts = self._block_time(tx["blockNumber"])
        tts = []
        for lg, tp, val in self._mine_logs(rc):
            ca = lg.get("address", "").lower()
            try:
                sym, dec = self.token_info(ca)
            except bf_engine.TokenNoDecimals:
                self.nodec.skip(txhash, ca, "0x" + tp[1][-40:], "0x" + tp[2][-40:], val)
                continue
            tts.append({
                "from": "0x" + tp[1][-40:], "to": "0x" + tp[2][-40:],
                "token": {"address": ca, "symbol": sym, "decimals": dec, "type": "ERC-20"},
                "total": {"value": str(val)},
            })
        wl9, wi9 = self._wrap_moves(rc, tts) if status == "0x1" else ([], [])
        tts.extend(wl9)
        if status == "0x1":
            wi9 = wi9 + self._sell_unwrap(tx, rc, tts, wi9)
        return {
            "tx": {
                "hash": tx["hash"], "from": tx.get("from"), "to": tx.get("to"),
                "value": str(int(tx.get("value") or "0x0", 16)),
                "fee": {"value": str(gas_used * gas_px)},
                "status": "ok" if status == "0x1" else "error",
                "raw_input": tx.get("input") or "0x",
                "timestamp": ts,
                "block_number": int(tx["blockNumber"], 16),
                "block_hash": tx.get("blockHash"),
            },
            "token_transfers": tts,
            "internal": wi9,
        }

    def block_at_ts(self, ts: int, hi: int) -> int:
        return bf_engine.block_at_ts(lambda b: self._block_time(hex(b)), int(ts), 0, int(hi))

    def _health(self, head: int, since: int, ok: bool, err=None, extra=None):
        hb = bf_engine.health("bsc")
        now = time.time()
        prev = getattr(self, "_hb_prev", None)
        if prev and head > prev[0]:
            v = (now - prev[1]) / float(head - prev[0])
            self._hb_bsec = v if getattr(self, "_hb_bsec", None) is None else 0.7 * self._hb_bsec + 0.3 * v
        if not prev or head != prev[0]:
            self._hb_prev = (head, now)
        bsec = getattr(self, "_hb_bsec", None)
        safe = head - self.conf_depth
        sc = self.cursor.get("_scan")
        facts = dict(head=head, cursor=since, lag_blocks=safe - since,
                     lag_sec=int((safe - since) * bsec) if bsec else None,
                     block_sec_est=round(bsec, 3) if bsec else None,
                     head_unchanged_sec=int(now - self._hb_prev[1]) if getattr(self, "_hb_prev", None) else None,
                     node_heads=getattr(self, "node_heads", None),
                     current_source=common.redact_urls(self.rpc.urls[self.rpc.i]),
                     logs_sources=[common.redact_urls(u) for u in self.logs_rpc.urls],
                     scan_pending=len(sc.get("found") or []) if isinstance(sc, dict) else 0,
                     synced_at=self.cursor.get("_synced_at"), scan=self.last_scan_metrics or None,
                     lanes=(extra or {}).get("lanes"),
                     balw=self.__dict__.get("_balw_facts"))
        if ok:
            hb.ok("bsc", "bsc_rpc", **facts)
        else:
            hb.fail("bsc", err or RuntimeError("부분 진행"), "bsc_rpc", **facts)
        hb.flush()

    def _extend(self, head: int):
        target = bf_engine.SINCE.target("bsc")
        if not target:
            return
        ext = self.cursor.get("_ext")
        if not isinstance(ext, dict) or ext.get("target") != target:
            tblk = self.block_at_ts(target, head - self.conf_depth)
            cov = self.cursor.get("_cov")
            if not isinstance(cov, int):
                hint = bf_engine.SINCE.covered_hint("bsc")
                base9 = int(self.cursor.get("_bf_start") or self.cursor.get("from_block") or 0)
                cov = min(self.block_at_ts(hint, head - self.conf_depth), base9) if hint else base9
            if cov <= tblk + 1:
                return
            ext = {"target": int(target), "tblk": int(tblk), "to": int(cov), "done_to": int(tblk), "found": [],
                   "t0": int(time.time())}
            self.cursor["_ext"] = ext
            common.atomic_write_json(self.cursor_path, self.cursor)
            log.info("★BSC 과거 창 확장: 블록 %d → %d (%s~)★", tblk, cov, time.strftime("%Y-%m-%d", time.gmtime(target)))
        t0 = time.time()
        bud = self._side_left()
        if ext["done_to"] < ext["to"]:
            found, last = self.discover(ext["done_to"] + 1, ext["to"], budget_sec=bud)
            if last > ext["done_to"]:
                ext["found"] = sorted(set(ext["found"]) | {h for h in found if h not in self.emitted})
                ext["done_to"] = last
                common.atomic_write_json(self.cursor_path, self.cursor)
        todo = [h for h in ext["found"] if h not in self.emitted]
        dets = self.fetch_details(todo, deadline=t0 + bud) if todo else {}
        order = sorted(todo, key=lambda h: (dets[h]["tx"]["block_number"], h) if isinstance(dets.get(h), dict)
                       else (1 << 62, h))
        n_emit = 0
        for h in order:
            snap = dets.get(h)
            if not isinstance(snap, dict):
                log.info("BSC 확장 상세 %s 보류(다음 사이클): %s", h[:12], str(snap)[:100])
                break
            self.writer.append({"v": 1, "kind": "evm_tx", "chain": "bsc", "txhash": h, "snapshot": snap,
                                "wallets": self.wallets, "observed_head": head, "ts": int(time.time())})
            self.emitted.add(h)
            n_emit += 1
        common.write_json_if_changed(self.meta_path, self.token_meta)
        common.write_json_if_changed(self.emitted_path, sorted(self.emitted))
        ext["found"] = [h for h in ext["found"] if h not in self.emitted]
        span = max(1, ext["to"] - ext["tblk"])
        self.progress.update("bsc:extend", phase="extend", unit="blocks", done=ext["done_to"] - ext["tblk"], total=span,
                             pending_detail=len(ext["found"]), target=time.strftime("%Y-%m-%d", time.gmtime(target)),
                             range=[ext["tblk"], ext["to"]], note=(self.last_scan_metrics or {}).get("stop"))
        if ext["done_to"] >= ext["to"] and not ext["found"]:
            self.cursor["_cov"] = ext["tblk"]
            self.cursor.pop("_ext", None)
            self.progress.finish("bsc:extend", note=f"확장 완료 {span}블록")
            log.info("★BSC 과거 창 확장 완료 — 하한 블록 %d (%.0f분)★", ext["tblk"], (time.time() - ext["t0"]) / 60)
        common.atomic_write_json(self.cursor_path, self.cursor)

    NEWW_KEY = "bsc:newwallet"

    def _seed_wallet_set(self):
        cur = sorted(set(self.wallets))
        known = self.cursor.get("_wallets")
        if not isinstance(known, list):
            self.cursor["_wallets"] = cur
            common.atomic_write_json(self.cursor_path, self.cursor)
            log.info("BSC 추적 지갑 집합 시드: %d개 (재스캔 없음)", len(cur))
            return
        kept = sorted(set(known) & set(cur))
        dirty = kept != sorted(known)
        if dirty:
            self.cursor["_wallets"] = kept
        if set(cur) - set(kept) and not isinstance(self.cursor.get("_neww"), dict) and "_neww_top" not in self.cursor:
            sc = self.cursor.get("_scan")
            fb = int(self.cursor.get("from_block") or 0)
            self.cursor["_neww_top"] = max(fb, int(sc.get("to") or 0)) if isinstance(sc, dict) else fb
            lv9, ls9 = self.cursor.get("_live"), self.cursor.get("_lscan")
            if isinstance(lv9, dict) and fb > 0:
                try:
                    self.cursor["_neww_top"] = max(int(self.cursor["_neww_top"]), int(lv9.get("done") or 0),
                                                   int(ls9.get("to") or 0) if isinstance(ls9, dict) else 0)
                except (TypeError, ValueError):
                    pass
            dirty = True
        if dirty:
            common.atomic_write_json(self.cursor_path, self.cursor)

    def _new_wallet_lo(self, head: int, new=None) -> int:
        cands = [self.block_at_ts(int(time.time()) - self.backfill_days * 86400, head - self.conf_depth)]
        ws9 = [self.wallet_since[w] for w in (new or ()) if (getattr(self, "wallet_since", None) or {}).get(w)]
        if ws9:
            cands.append(self.block_at_ts(min(ws9), head - self.conf_depth))
        for v in (self.cursor.get("_cov"), self.cursor.get("_bf_start")):
            if isinstance(v, int) and v > 0:
                cands.append(v)
        ext = self.cursor.get("_ext")
        if isinstance(ext, dict) and isinstance(ext.get("tblk"), int):
            cands.append(int(ext["tblk"]))
        return max(1, min(cands))

    def _new_wallet_pass(self, head: int):
        known = self.cursor.get("_wallets")
        if not isinstance(known, list):
            return
        cur = set(self.wallets)
        fb = int(self.cursor.get("from_block") or 0)
        sc = self.cursor.get("_scan")
        top = max(fb, int(sc.get("to") or 0)) if isinstance(sc, dict) else fb
        hint = self.cursor.get("_neww_top")
        if isinstance(hint, int) and 0 < hint <= top:
            top = hint
        job = self.cursor.get("_neww")
        if isinstance(job, dict):
            jw = sorted(set(job.get("wallets") or []) & cur)
            extra = sorted(cur - set(known) - set(jw))
            if extra:
                lo2 = min(int(job["lo"]), int(self._new_wallet_lo(head, extra)))
                jw = sorted(set(jw) | set(extra))
                job["lo"] = lo2
                job["done_to"] = lo2 - 1
                job["to"] = max(int(job["to"]), top)
            if not jw:
                self.cursor.pop("_neww", None)
                common.atomic_write_json(self.cursor_path, self.cursor)
                return
            job["wallets"] = jw
        else:
            new = sorted(cur - set(known))
            if not new:
                return
            if fb <= 0 or hint == 0:
                self.cursor.pop("_neww_top", None)
                self.cursor["_wallets"] = sorted(cur)
                common.atomic_write_json(self.cursor_path, self.cursor)
                return
            lo = self._new_wallet_lo(head, new)
            self.cursor.pop("_neww_top", None)
            if lo > top:
                self.cursor["_wallets"] = sorted(set(known) | set(new))
                common.atomic_write_json(self.cursor_path, self.cursor)
                return
            job = {"wallets": new, "lo": int(lo), "to": int(top), "done_to": int(lo) - 1, "found": [],
                   "t0": int(time.time())}
            self.cursor["_neww"] = job
            common.atomic_write_json(self.cursor_path, self.cursor)
            log.info("★BSC 나중 등록 지갑 %d개 이력 백필: 블록 %d → %d (새 지갑 토픽만)★", len(new), lo, top)
        t0 = time.time()
        bud = self._side_left()
        if job["done_to"] < job["to"]:
            found, last = self.discover(job["done_to"] + 1, job["to"], budget_sec=bud,
                                        topics=[_pad_topic(w) for w in job["wallets"]])
            if last > job["done_to"]:
                job["found"] = sorted(set(job["found"]) | set(found))
                job["done_to"] = last
                common.atomic_write_json(self.cursor_path, self.cursor)
        todo = list(job["found"])
        dets = self.fetch_details(todo, deadline=t0 + bud) if todo else {}
        order = sorted(todo, key=lambda h: (dets[h]["tx"]["block_number"], h) if isinstance(dets.get(h), dict)
                       else (1 << 62, h))
        sent = set()
        for h in order:
            snap = dets.get(h)
            if not isinstance(snap, dict):
                log.info("BSC 새 지갑 백필 상세 %s 보류(다음 사이클): %s", h[:12], str(snap)[:100])
                break
            try:
                self.writer.append({"v": 1, "kind": "evm_tx", "chain": "bsc", "txhash": h, "snapshot": snap,
                                    "wallets": self.wallets, "observed_head": head, "ts": int(time.time())})
            except Exception as e:
                log.error("inbox append 실패 — 새 지갑 백필 보류: %s", e)
                break
            self.emitted.add(h)
            sent.add(h)
        common.write_json_if_changed(self.meta_path, self.token_meta)
        common.write_json_if_changed(self.emitted_path, sorted(self.emitted))
        job["found"] = [h for h in job["found"] if h not in sent]
        span = max(1, job["to"] - job["lo"] + 1)
        self.progress.update(self.NEWW_KEY, phase="extend", unit="blocks", done=job["done_to"] - job["lo"] + 1,
                             total=span, pending_detail=len(job["found"]), range=[job["lo"], job["to"]],
                             note=f"새 지갑 {len(job['wallets'])}개")
        if job["done_to"] >= job["to"] and not job["found"]:
            self.cursor["_wallets"] = sorted((set(known) | set(job["wallets"])) & cur)
            self.cursor.pop("_neww", None)
            self.progress.finish(self.NEWW_KEY, note=f"새 지갑 {len(job['wallets'])}개 이력 백필 완료 {span}블록")
            log.info("★BSC 나중 등록 지갑 이력 백필 완료 — %d개, %.0f분★", len(job["wallets"]), (time.time() - job["t0"]) / 60)
        common.atomic_write_json(self.cursor_path, self.cursor)

    def _detail_fail_note(self, bad: list, dets: dict) -> list:
        return bf_engine.detail_fail_note(self.cursor, bad, dets, "bsc", "bsc_detail", log, self.__dict__.setdefault("_df_seen", set()))

    def _detail_fail_clear(self, ok_hashes):
        bf_engine.detail_fail_clear(self.cursor, ok_hashes)

    def _quarantine_retry(self, head: int):
        due = bf_engine.quarantine_due(self.cursor)
        if not due:
            return 0
        dets = self.fetch_details(due)
        n = 0
        for h in due:
            snap = dets.get(h)
            if isinstance(snap, dict):
                if h not in self.emitted:
                    self.writer.append({"v": 1, "kind": "evm_tx", "chain": "bsc", "txhash": h, "snapshot": snap,
                                        "wallets": self.wallets, "observed_head": head, "ts": int(time.time())})
                    self.emitted.add(h)
                    n += 1
                bf_engine.quarantine_result(self.cursor, h, True, "bsc", "bsc_detail", log)
            else:
                bf_engine.quarantine_result(self.cursor, h, False, "bsc", "bsc_detail", log, err=snap)
        common.write_json_if_changed(self.meta_path, self.token_meta)
        common.write_json_if_changed(self.emitted_path, sorted(self.emitted))
        common.atomic_write_json(self.cursor_path, self.cursor)
        return n

    def _nonce_path(self) -> str:
        return os.path.join(common.STATE_DIR, "bsc_nonce.json")

    def _nonce_load(self) -> dict:
        d = getattr(self, "_nonce_st", None)
        if d is None:
            d = common.read_json(self._nonce_path(), {})
            if not isinstance(d, dict) or not isinstance(d.get("w"), dict):
                d = {"w": {}}
            self._nonce_st = d
        return d

    def _nonce_note(self, rec: dict):
        st = self._nonce_load()
        if not st.get("boot"):
            return
        tx = ((rec or {}).get("snapshot") or {}).get("tx") or {}
        fr = str(tx.get("from") or "").lower()
        if fr not in self.wallets:
            return
        try:
            b = int(tx.get("block_number"))
        except (TypeError, ValueError):
            return
        ws = st["w"].setdefault(fr, {})
        hs = ws.setdefault("hashes", {})
        h = str(rec.get("txhash") or tx.get("hash") or "").lower()
        if h and h not in hs:
            hs[h] = b
            ws["blocks"] = sorted(hs.values())
            common.atomic_write_json(self._nonce_path(), st)

    def _nonce_boot(self, st: dict) -> bool:
        if st.get("boot"):
            return True
        if not os.path.exists(common.DB_PATH):
            return False
        import sqlite3
        try:
            con = sqlite3.connect(common.sqlite_ro_uri(common.DB_PATH), uri=True, timeout=10)
            try:
                rows = con.execute("SELECT txhash, block, json_extract(snapshot, '$.tx.from') FROM raw_txs WHERE chain='bsc'").fetchall()
            finally:
                con.close()
        except Exception as e:
            log.info("BSC nonce 색인 부트스트랩 실패(다음 기회): %s", str(e)[:120])
            return False
        mine = set(self.wallets)
        for h, b, fr in rows:
            fr = str(fr or "").lower()
            if fr in mine and b is not None:
                st["w"].setdefault(fr, {}).setdefault("hashes", {})[str(h).lower()] = int(b)
        for w, ws in st["w"].items():
            ws["blocks"] = sorted((ws.get("hashes") or {}).values())
        st["boot"] = int(_now())
        common.atomic_write_json(self._nonce_path(), st)
        log.info("BSC nonce 색인 부트스트랩: 원장 발신 tx %d건", sum(len(ws.get("hashes") or {}) for ws in st["w"].values()))
        return True

    def _nonce_hint(self, w: str, blk) -> bool:
        w = str(w or "").lower()
        if w not in self.wallets:
            return False
        try:
            b = int(blk)
        except (TypeError, ValueError):
            return False
        st = self._nonce_load()
        hl = st["w"].setdefault(w, {}).setdefault("hint", [])
        if any(isinstance(h9, list) and h9 and h9[0] == b for h9 in hl):
            return False
        hl.append([b, int(_now())])
        common.atomic_write_json(self._nonce_path(), st)
        return True

    def _nonce_due(self, st: dict, now: float, lo_blk: int, busy: set, known_set) -> bool:
        for w in self.wallets:
            if w in busy or (isinstance(known_set, list) and w not in known_set):
                continue
            ws = st["w"].get(w) or {}
            kind = ws.get("kind")
            if kind is None:
                return True
            if kind != "eoa":
                continue
            lo = ws.get("lo")
            if not (isinstance(lo, list) and len(lo) == 2 and lo[0] == lo_blk):
                return True
            ta = ws.get("top_at")
            if not isinstance(ws.get("top"), int) or not isinstance(ta, (int, float)) or now - float(ta) >= NONCE_HEAD_EVERY:
                return True
            try:
                if int(ws.get("missing") or 0) > 0:
                    return True
            except (TypeError, ValueError):
                pass
            if ws.get("hint"):
                return True
        return False

    def _nonce_tops(self, batch_fn, ws_list: list, safe: int, put, one, can_one=None) -> None:
        if not ws_list:
            return
        bh = hex(int(safe))

        def put_one(w9):
            if can_one is not None and not can_one():
                return False
            r9 = one(w9, bh)
            if r9 is not None:
                put(w9, int(r9, 16))
            return True
        rest = list(ws_list)
        if batch_fn is not None and len(rest) > 1:
            rest = []
            down = False
            for i in range(0, len(ws_list), NONCE_TOP_BATCH):
                chunk = ws_list[i:i + NONCE_TOP_BATCH]
                res = []
                if not down:
                    try:
                        res = batch_fn([("eth_getTransactionCount", [w9, bh]) for w9 in chunk])
                    except _NonceBudget:
                        raise
                    except _PubDown:
                        down = True
                    except Exception as e:
                        if isinstance(e, bf_engine.NetError) and e.kind in _NONCE_STOP_KINDS:
                            raise
                failed = []
                for j, w9 in enumerate(chunk):
                    r9 = res[j] if isinstance(res, list) and j < len(res) else None
                    if isinstance(r9, bf_engine.NetError) and r9.kind in _NONCE_STOP_KINDS:
                        raise r9
                    try:
                        n9 = int(r9, 16)
                    except (TypeError, ValueError):
                        failed.append(w9)
                        continue
                    put(w9, n9)
                for w9 in failed:
                    if not put_one(w9):
                        return
        for w9 in rest:
            if not put_one(w9):
                return

    def _nonce_pass(self, head: int, lo_blk: int = None) -> int:
        st = self._nonce_load()
        now = _now()
        if float(st.get("bo_until") or 0) > now:
            return 0
        if now - float(st.get("at_w") or 0) < NONCE_HEAD_EVERY:
            return 0
        if lo_blk is None:
            lo_blk = self.cursor.get("_cov") if isinstance(self.cursor.get("_cov"), int) else self.cursor.get("_bf_start")
        if not isinstance(lo_blk, int) or lo_blk <= 0:
            return 0
        safe = int(head) - self.conf_depth
        if safe <= lo_blk:
            return 0
        if not self._nonce_boot(st):
            return 0
        busy = set((self.cursor.get("_neww") or {}).get("wallets") or []) if isinstance(self.cursor.get("_neww"), dict) else set()
        known_set = self.cursor.get("_wallets")
        if not self._nonce_due(st, now, lo_blk, busy, known_set):
            return 0
        st["at_w"] = int(now)
        base_rpc = self.rpc
        base_i = getattr(base_rpc, "i", None)
        arch = getattr(self, "arch_rpc", None) or base_rpc
        own_arch = arch is base_rpc and isinstance(base_rpc, Rpc) and bool(base_rpc.urls)
        if own_arch:
            arch = Rpc(list(base_rpc.urls))
            try:
                arch.i = int(st.get("arch_i") or 0) % len(arch.urls)
            except (TypeError, ValueError):
                arch.i = 0
        pub_rpc = getattr(self, "nonce_pub_rpc", base_rpc)
        cnt = {"arch": 0, "pub": 0, "found": 0, "emit": 0}
        self._nonce_last = cnt
        try:
            tok0 = float(st["old_tok"]) if st.get("old_tok") is not None else float(NONCE_OLD_BURST)
            tat0 = float(st.get("old_tok_at") or now)
        except (TypeError, ValueError):
            tok0, tat0 = float(NONCE_OLD_BURST), now
        old_tok = [min(float(NONCE_OLD_BURST), tok0 + max(0.0, now - tat0) * NONCE_CALL_CAP / float(NONCE_BACKLOG_EVERY))]
        old_a0 = [None]
        nxt = [0.0]
        blk = [False]
        halt = [None]

        def halt_on(e):
            if halt[0] is None and (isinstance(e, _NonceBudget) or (isinstance(e, bf_engine.NetError) and e.kind not in ("null", "rpc", "range"))):
                halt[0] = e

        def charge(n):
            if halt[0] is not None:
                raise halt[0]
            if cnt["arch"] + n > NONCE_CALL_CAP:
                e9 = _NonceBudget("nonce 확인 아카이브 호출 상한")
                halt_on(e9)
                raise e9
            cnt["arch"] += n
            w9 = nxt[0] - time.monotonic()
            if w9 > 0:
                time.sleep(w9)
            nxt[0] = time.monotonic() + NONCE_ARCH_GAP * n

        def pub_charge(n):
            if cnt["pub"] + n > NONCE_PUB_CAP:
                raise _NonceBudget("nonce 확인 공개 노드 호출 상한")
            cnt["pub"] += n

        class _Metered:

            def call(self_, m, p, *a, **kw):
                if not isinstance(arch, Rpc) or not arch.urls:
                    charge(1)
                    try:
                        return arch.call(m, p, *a, **kw)
                    except Exception as e:
                        halt_on(e)
                        raise
                if halt[0] is not None:
                    raise halt[0]
                tries9 = len(arch.urls)
                for k9 in range(tries9):
                    j9 = self_._pick()
                    charge(1)
                    try:
                        return self_._one(j9, m, p, kw.get("timeout", a[0] if a else 25))
                    except Exception as e:
                        if k9 + 1 < tries9 and isinstance(e, bf_engine.NetError) and e.kind in _NONCE_NEXT_KINDS:
                            continue
                        halt_on(e)
                        raise

            def _pick(self_):
                urls9 = arch.urls
                t9 = time.time()
                for k9 in range(len(urls9)):
                    j9 = (arch.i + k9) % len(urls9)
                    g9 = bf_engine.gate(urls9[j9])
                    if not (g9.open_until > t9 or g9.pause_until > t9):
                        return j9
                blk[0] = True
                e9 = _NonceBudget(bf_engine._url_host(urls9[arch.i % len(urls9)]) + " 쉬는 중(429·서킷)")
                halt_on(e9)
                raise e9

            def _one(self_, j9, m, p, timeout):
                urls9 = arch.urls
                u9 = urls9[j9]
                arch.i = j9
                host9 = bf_engine._url_host(u9)
                g9 = bf_engine.gate(u9)
                try:
                    d9 = bf_engine.http_json(u9, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": m, "params": p}).encode(),
                                             timeout=timeout, retries=1)
                    if not isinstance(d9, dict):
                        raise bf_engine.NetError(f"rpc {m}: 응답 형식 오류 ({type(d9).__name__})", "payload", host=host9)
                    if d9.get("error"):
                        e9 = bf_engine.classify_rpc_error(d9["error"])
                        e9.host = host9
                        if e9.kind in ("http429", "quota"):
                            g9.failure(e9)
                        raise e9
                    if d9.get("result") is None:
                        raise bf_engine.NetError(f"rpc {m}: result null", "null", host=host9)
                    return d9["result"]
                except Exception:
                    arch.i = (j9 + 1) % len(urls9)
                    raise

            def batch(self_, items, *a, **kw):
                out = []
                for m, p in items:
                    if halt[0] is not None:
                        out.append(halt[0])
                        continue
                    try:
                        out.append(self_.call(m, p, *a, **kw))
                    except Exception as e:
                        out.append(halt[0] if halt[0] is not None else e)
                return out

            def __getattr__(self_, k):
                return getattr(arch, k)

        pub_real = isinstance(pub_rpc, Rpc) and bool(pub_rpc.urls)

        def pub_req(body, n):
            urls9 = pub_rpc.urls
            last9 = None
            t9 = time.time()
            for k9 in range(len(urls9)):
                j9 = (pub_rpc.i + k9) % len(urls9)
                u9 = urls9[j9]
                g9 = bf_engine.gate(u9)
                if g9.open_until > t9 or g9.pause_until > t9:
                    continue
                if halt[0] is not None:
                    raise halt[0]
                pub_charge(n)
                try:
                    d9 = bf_engine.http_json(u9, data=json.dumps(body).encode(), timeout=25, retries=1, cost=n)
                    pub_rpc.i = j9
                    return d9, bf_engine._url_host(u9), g9
                except Exception as e:
                    if isinstance(e, bf_engine.NetError) and e.kind in _NONCE_STOP_KINDS:
                        halt_on(e)
                        raise
                    last9 = e
            if last9 is None:
                raise _PubDown("공개 노드 전부 쉬는 중(서킷·쉼)")
            raise last9

        def pub_err(d9, host9, g9):
            e9 = bf_engine.classify_rpc_error(d9["error"])
            e9.host = host9
            if e9.kind in ("http429", "quota"):
                g9.failure(e9)
            if e9.kind in _NONCE_STOP_KINDS:
                halt_on(e9)
            return e9

        def pub_single(m, p):
            d9, host9, g9 = pub_req({"jsonrpc": "2.0", "id": 1, "method": m, "params": p}, 1)
            if not isinstance(d9, dict):
                raise bf_engine.NetError(f"rpc {m}: 응답 형식 오류", "payload", host=host9)
            if d9.get("error"):
                raise pub_err(d9, host9, g9)
            if d9.get("result") is None:
                raise bf_engine.NetError(f"rpc {m}: result null", "null", host=host9)
            return d9["result"]

        def pub_batch(items):
            d9, host9, g9 = pub_req([{"jsonrpc": "2.0", "id": i9, "method": m, "params": p} for i9, (m, p) in enumerate(items)], len(items))
            if isinstance(d9, dict) and d9.get("error"):
                raise pub_err(d9, host9, g9)
            if not isinstance(d9, list):
                raise bf_engine.NetError("rpc batch: 응답 형식 오류", "payload", host=host9)
            out = [bf_engine.NetError("rpc batch: 응답 누락", "null", host=host9) for _ in items]
            for it in d9:
                try:
                    i9 = int(it.get("id"))
                except (TypeError, ValueError, AttributeError):
                    continue
                if not 0 <= i9 < len(items):
                    continue
                if it.get("error"):
                    out[i9] = pub_err(it, host9, g9)
                elif it.get("result") is not None:
                    out[i9] = it["result"]
            return out

        def pub_one(m, p, archive_ok=True):
            if pub_rpc is None:
                return self.rpc.call(m, p) if archive_ok else None
            if not pub_real:
                pub_charge(1)
                return pub_rpc.call(m, p)
            try:
                return pub_single(m, p)
            except _NonceBudget:
                raise
            except Exception as e:
                if halt[0] is not None:
                    raise
                if not archive_ok:
                    return None
                log.debug("BSC nonce 확인 — 공개 노드 실패 → 아카이브(계량): %s", _nonce_why(e))
                return self.rpc.call(m, p)

        def arch_blocked():
            urls9 = getattr(arch, "urls", None) or []
            if arch is base_rpc or not urls9:
                return None
            t9 = time.time()
            for u9 in urls9:
                g9 = bf_engine.gate(u9)
                if not (g9.open_until > t9 or g9.pause_until > t9):
                    return None
            return bf_engine._url_host(urls9[0]) + " 쉬는 중(429·서킷)"

        def sample(v, b):
            n9 = int(self.rpc.call("eth_getTransactionCount", [v.w, hex(int(b))]), 16)
            lo9 = max((x for x in v.smp if x < b), default=None)
            hi9 = min((x for x in v.smp if x > b), default=None)
            if (lo9 is not None and n9 < v.smp[lo9]) or (hi9 is not None and n9 > v.smp[hi9]):
                raise RuntimeError(f"블록 {b} nonce {n9} 가 이웃 표본과 순서 어긋남(노드 불일치)")
            v.smp[int(b)] = n9

        def pend_of(v, z):
            pd = v.ws.get("pend")
            return pd if isinstance(pd, dict) and pd.get("z") == z and isinstance(pd.get("h"), list) else None

        def resolve(v, z):
            w = v.w
            ws = v.ws
            hs = ws.setdefault("hashes", {})
            pd = pend_of(v, z)
            if pd is None:
                blk = self.rpc.call("eth_getBlockByNumber", [hex(z), True]) or {}
                txs9 = blk.get("transactions")
                try:
                    num9 = int(str(blk.get("number") or "0x0"), 16)
                except ValueError:
                    num9 = -1
                if num9 != z or not isinstance(txs9, list) or any(not isinstance(t, dict) or not t.get("from") or not t.get("hash") for t in txs9):
                    raise RuntimeError(f"블록 {z} 전체 응답 불완전")
                try:
                    ts9 = int(str(blk.get("timestamp")), 16)
                except (TypeError, ValueError, AttributeError):
                    ts9 = None
                mine = [t for t in txs9 if str(t.get("from") or "").lower() == w]
                diff9 = v.smp[z] - v.smp[z - 1]
                extra9 = diff9 - len(mine)
                if diff9 <= 0:
                    raise RuntimeError(f"블록 {z} nonce 증가 없음 — 표본 불일치")
                if extra9 < 0:
                    raise RuntimeError(f"블록 {z} nonce 증가량({diff9}) < 내 발신 tx {len(mine)}")
                if extra9 > 0:
                    ws.setdefault("nonce_extra", {})[str(z)] = extra9
                    log.info("BSC nonce 확인 %s: 블록 %d nonce +%d 은 발신 tx 아님(7702 위임 등) — 기록하고 다음으로", w[:10], z, extra9)
                pd = {"z": z, "h": [str(t.get("hash") or "").lower() for t in mine], "ts": ts9}
                ws["pend"] = pd
            cnt["found"] += 1
            if isinstance(pd.get("ts"), int):
                self.block_ts[hex(z)] = pd["ts"]
            stop9 = None
            for h in pd["h"]:
                if not h:
                    continue
                if h in hs or h in self.emitted:
                    hs[h] = z
                    continue
                if halt[0] is not None:
                    stop9 = halt[0]
                    break
                if NONCE_CALL_CAP - cnt["arch"] < 2:
                    stop9 = _NonceBudget("nonce 확인 아카이브 호출 상한(발신 하나 몫 부족 — 다음 실행)")
                    halt_on(stop9)
                    break
                snap = self.fetch_details([h]).get(h)
                if not isinstance(snap, dict):
                    if halt[0] is not None:
                        stop9 = halt[0]
                        break
                    raise RuntimeError(f"상세 실패 {h[:12]}: {_nonce_why(snap)}")
                self.writer.append({"v": 1, "kind": "evm_tx", "chain": "bsc", "txhash": h, "snapshot": snap,
                                    "wallets": self.wallets, "observed_head": head, "ts": int(time.time()), "via": "nonce"})
                self.emitted.add(h)
                cnt["emit"] += 1
                log.info("★BSC 로그 없는 발신 tx 회수(nonce) %s 블록 %d★", h[:14], z)
                hs[h] = z
            v.reindex()
            if stop9 is not None:
                raise stop9
            ws.pop("pend", None)
            if any(a9 == z - 1 and z9 == z for a9, z9, _d9 in v.intervals()[0]):
                log.info("BSC nonce 확인 %s: 블록 %d 해결 뒤에도 nonce 증가가 남음 — 표본 초기화", w[:10], z)
                v.reset()
                v.skip = True

        wl = list(self.wallets)
        rr = int(st.get("rr") or 0) % len(wl) if wl else 0
        order = wl[rr:] + wl[:rr]
        views = {}
        err = None
        blocked = False
        last_w = None
        self.rpc = _Metered()
        try:
            why0 = arch_blocked()
            if why0:
                blocked = True
                halt[0] = _NonceBudget(why0)
                log.info("BSC nonce 확인 — 아카이브 %s: 이번엔 헤드 확인만", why0)
            for w in order:
                if w in busy or (isinstance(known_set, list) and w not in known_set):
                    continue
                ws = st["w"].setdefault(w, {})
                if ws.get("kind") is None:
                    code = str(pub_one("eth_getCode", [w, "latest"]) or "0x").lower()
                    ws["kind"] = "eoa" if code in ("0x", "0x0", "") or code.startswith("0xef0100") else "contract"
                if ws["kind"] != "eoa":
                    ws.pop("hint", None)
                    continue
                views[w] = _NView(w, ws, lo_blk)

            def hints(v):
                return [h9 for h9 in (v.ws.get("hint") or []) if isinstance(h9, list) and len(h9) == 2 and isinstance(h9[0], int)]
            def head_due(v):
                return v.top is None or now - v.top_at >= NONCE_HEAD_EVERY or any(h9[0] + NONCE_HINT_FAR > v.top for h9 in hints(v))
            need = []
            for w, v in views.items():
                if head_due(v):
                    if v.top is None or v.top < safe:
                        need.append(w)
                    else:
                        v.top_at = now

            def put_top(w, n9):
                v = views[w]
                if v.top is not None and n9 < v.smp.get(v.top, 0):
                    log.info("BSC nonce 확인 %s: 헤드 nonce %d < 지난 확인 %d — 이번엔 헤드 확인 건너뜀(노드 뒤처짐)", w[:10], n9, v.smp.get(v.top, 0))
                    return
                v.smp[safe] = n9
                v.top = safe
                v.top_at = now
                if n9 == 0 and v.lo_n is None:
                    v.set_lo(0)
                v.reindex()
            bfn = pub_batch if pub_real else (None if pub_rpc is None or not callable(getattr(pub_rpc, "batch", None))
                                              else (lambda it9: (pub_charge(len(it9)), pub_rpc.batch(it9))[1]))
            need.sort(key=lambda w9: (views[w9].top is not None, views[w9].top_at))
            self._nonce_tops(bfn, need, safe, put_top,
                             lambda w9, bh9: pub_one("eth_getTransactionCount", [w9, bh9],
                                                     archive_ok=views[w9].top is None or now - views[w9].top_at >= NONCE_EVERY),
                             can_one=lambda: cnt["arch"] < NONCE_CALL_CAP // 2)
            if halt[0] is not None:
                raise halt[0]
            for w, v in views.items():
                if v.lo_n is None and v.top is not None:
                    v.set_lo(int(self.rpc.call("eth_getTransactionCount", [w, hex(lo_blk)]), 16))
                    v.reindex()
            for w, v in views.items():
                if not v.ready():
                    continue
                _iv, bad = v.intervals()
                if bad:
                    log.info("BSC nonce 확인 %s: 표본·색인이 서로 안 맞음 — 표본 초기화(다시 좁힘)", w[:10])
                    v.reset()
                m9 = v.missing()
                v.ws["missing"] = m9
                if m9 < 0:
                    log.info("BSC nonce 확인 %s: 색인 발신 %d > nonce 차 — 건너뜀(원장·색인 불일치)", w[:10], len(v.blocks))
                    v.skip = True
            act = [w for w in order if w in views and views[w].ready() and not views[w].skip]
            for w in act:
                v = views[w]
                hl = hints(v)
                if not hl:
                    v.ws.pop("hint", None)
                    continue
                keep = []
                for b9, t9 in hl:
                    if now - float(t9) > NONCE_HINT_KEEP or b9 <= lo_blk:
                        continue
                    for p9 in (b9 - 1, b9 + NONCE_HINT_NEAR, b9 + NONCE_HINT_FAR):
                        if lo_blk < p9 < v.top and p9 not in v.smp and v.open_at(p9):
                            sample(v, p9)
                    if b9 + NONCE_HINT_FAR > v.top:
                        keep.append([b9, t9])
                if keep:
                    v.ws["hint"] = keep
                else:
                    v.ws.pop("hint", None)
            rlo = safe - max(1, int(NONCE_RECENT_SEC / self._bsec()))
            old_ok = old_tok[0] >= NONCE_CALL_CAP / 2.0
            pos = 0
            while act and cnt["found"] < NONCE_MAX_FIND:
                ivs = {w9: (views[w9].intervals()[0] if not views[w9].skip else []) for w9 in act}
                live = [w9 for w9 in act if ivs[w9]]
                if not live:
                    break
                rec = {w9: [t9 for t9 in ivs[w9] if t9[1] > rlo] for w9 in live}
                rec = {w9: r9 for w9, r9 in rec.items() if r9}
                if rec:
                    pool9, cand = rec, set(rec)
                elif old_ok:
                    if old_a0[0] is None:
                        old_a0[0] = cnt["arch"]
                    pool9 = ivs
                    cand = {w9 for w9 in live if min(z9 - a9 for a9, z9, _d9 in ivs[w9]) <= NONCE_NARROW} or set(live)
                else:
                    break
                w = next(act[(pos + j) % len(act)] for j in range(len(act)) if act[(pos + j) % len(act)] in cand)
                pos = (act.index(w) + 1) % len(act)
                a9, z9, _d9 = min(pool9[w], key=lambda t9: (t9[1] - t9[0], -t9[0]))
                last_w = w
                v = views[w]
                if z9 - a9 == 1:
                    if NONCE_CALL_CAP - cnt["arch"] < (2 if pend_of(v, z9) else 3):
                        raise _NonceBudget("nonce 확인 아카이브 호출 상한(블록 해결 몫 부족 — 다음 실행)")
                    resolve(v, z9)
                elif w in rec and a9 < rlo < z9 and rlo not in v.smp:
                    sample(v, rlo)
                else:
                    sample(v, (a9 + z9) // 2)
        except _NonceBudget as e:
            log.debug("BSC nonce 확인 — 이번 실행 상한: %s", e)
        except Exception as e:
            err = e
        finally:
            if own_arch:
                st["arch_i"] = arch.i
            self.rpc = base_rpc
            if base_i is not None:
                try:
                    base_rpc.i = base_i
                except AttributeError:
                    pass
        st["old_tok"] = round(old_tok[0] - (cnt["arch"] - old_a0[0] if old_a0[0] is not None else 0), 2)
        st["old_tok_at"] = int(now)
        if blk[0]:
            blocked = True
        if halt[0] is not None:
            err = None if isinstance(halt[0], _NonceBudget) else halt[0]
        left = 0
        n_left = 0
        for v in views.values():
            if v.ready():
                try:
                    if not v.skip:
                        v.prune()
                        v.ws["missing"] = v.missing()
                        if v.ws["missing"] <= 0:
                            v.ws.pop("pend", None)
                except Exception as e:
                    log.debug("BSC nonce 표본 정리 실패 %s: %s", v.w[:10], e)
            v.save()
            m9 = v.ws.get("missing")
            if isinstance(m9, int) and m9 > 0:
                left += m9
                n_left += 1
        for ws in st["w"].values():
            ws["blocks"] = sorted((ws.get("hashes") or {}).values())
        if wl:
            st["rr"] = (wl.index(last_w) + 1) % len(wl) if last_w in wl else (rr + 1) % len(wl)
        if err is None:
            if not blocked:
                st.pop("bo_until", None)
                st["bo_n"] = 0
        else:
            n9 = int(st.get("bo_n") or 0) + 1
            st["bo_n"] = n9
            wait9 = int(min(NONCE_BO_MAX, NONCE_BO_BASE * (2 ** min(n9 - 1, 16))))
            st["bo_until"] = int(_now() + wait9)
            log.info("BSC nonce 확인 중단(%d초 쉼 뒤 다음 기회): %s", wait9, _nonce_why(err))
        common.atomic_write_json(self._nonce_path(), st)
        common.write_json_if_changed(self.meta_path, self.token_meta)
        if cnt["emit"]:
            common.write_json_if_changed(self.emitted_path, sorted(self.emitted))
        if cnt["arch"] or cnt["emit"] or err is not None:
            log.info("BSC nonce 회수: 아카이브 %d콜 · 공개 %d콜 · 찾은 블록 %d · 방출 %d · 남은 누락 %d건(지갑 %d개)",
                     cnt["arch"], cnt["pub"], cnt["found"], cnt["emit"], left, n_left)
        return cnt["emit"]

    XIN_HINT_TRIES = 24

    def _xin_hints(self, memo: dict) -> int:
        need = [h for h, m9 in memo.items() if isinstance(m9, dict) and m9.get("r") == "emit" and not m9.get("hint")
                and isinstance(m9.get("blk"), int)]
        if not need:
            return 0
        tos = {}
        if any(not memo[h].get("to") for h in need) and os.path.exists(common.DB_PATH):
            import sqlite3
            try:
                con = sqlite3.connect(common.sqlite_ro_uri(common.DB_PATH), uri=True, timeout=10)
                try:
                    q9 = [h for h in need if not memo[h].get("to")]
                    rows = []
                    for i9 in range(0, len(q9), 500):
                        c9 = q9[i9:i9 + 500]
                        rows += con.execute("SELECT lower(txhash), lower(json_extract(snapshot, '$.tx.to')) FROM raw_txs WHERE chain='bsc'"
                                            " AND lower(txhash) IN (" + ",".join("?" * len(c9)) + ")", c9).fetchall()
                finally:
                    con.close()
                tos = {str(h9): str(t9 or "") for h9, t9 in rows}
            except Exception as e:
                log.debug("BSC 거래소 출금 힌트 — 원장 읽기 실패(다음 기회): %s", str(e)[:120])
        n = 0
        for h in need:
            m9 = memo[h]
            to9 = str(m9.get("to") or tos.get(h) or "").lower()
            if to9 in self.wallets:
                try:
                    n += 1 if self._nonce_hint(to9, m9["blk"]) else 0
                    m9["hint"] = 1
                except Exception as e:
                    log.debug("BSC nonce 힌트 기록 실패: %s", str(e)[:120])
            else:
                m9["hint_n"] = int(m9.get("hint_n") or 0) + 1
                if m9["hint_n"] >= self.XIN_HINT_TRIES:
                    m9["hint"] = -1
        return n

    def _xin_path(self) -> str:
        return os.path.join(common.STATE_DIR, "bsc_xin.json")

    def _xin_cands(self) -> list:
        if not os.path.exists(common.DB_PATH):
            return []
        import sqlite3
        con = sqlite3.connect(common.sqlite_ro_uri(common.DB_PATH), uri=True, timeout=10)
        try:
            rows = con.execute(
                "SELECT r.payload FROM raw_ex r JOIN (SELECT exchange, uuid, max(revision) AS rv FROM raw_ex WHERE kind='withdraw'"
                " GROUP BY exchange, uuid) x ON x.exchange=r.exchange AND x.uuid=r.uuid AND x.rv=r.revision"
                " WHERE r.kind='withdraw' AND upper(json_extract(r.payload, '$.currency'))='BNB'").fetchall()
        finally:
            con.close()
        mine = set(self.wallets)
        out = {}
        for (pl,) in rows:
            try:
                p = json.loads(pl)
            except (TypeError, ValueError):
                continue
            if not isinstance(p, dict) or str(p.get("state") or "").upper() not in ("DONE", "ACCEPTED"):
                continue
            tx = str(p.get("txid") or "").strip().lower()
            if len(tx) == 64 and not tx.startswith("0x"):
                tx = "0x" + tx
            if not _XIN_TXID.match(tx):
                continue
            net = str(p.get("network") or p.get("net_type") or "").strip()
            if net and not _XIN_NET.search(net):
                continue
            addr = str(p.get("address") or "").strip().lower()
            if addr and addr not in mine:
                continue
            t9 = common.iso_epoch(p.get("done_at")) or common.iso_epoch(p.get("created_at")) or 0
            out[tx] = max(out.get(tx, 0), t9)
        return sorted(out, key=lambda h: (-out[h], h))

    def _xin_pass(self, head: int) -> int:
        try:
            st = common.read_json(self._xin_path(), {})
        except SystemExit as e:
            log.warning("BSC 거래소 출금 txid 진행 파일 손상 — 새로 시작: %s", str(e)[:120])
            st = {}
        if not isinstance(st, dict) or not isinstance(st.get("tx"), dict):
            st = {"tx": {}}
        if _now() - float(st.get("at") or 0) < XIN_EVERY:
            return 0
        st["at"] = int(_now())
        lo_blk = self.cursor.get("_cov") if isinstance(self.cursor.get("_cov"), int) else self.cursor.get("_bf_start")
        safe = int(head) - self.conf_depth
        n_emit = 0
        try:
            cands = self._xin_cands()
        except Exception as e:
            log.info("BSC 거래소 출금 txid 확인 — 원장 읽기 실패(다음 기회): %s", str(e)[:120])
            common.atomic_write_json(self._xin_path(), st)
            return 0
        memo = st["tx"]
        w9 = sorted(set(self.wallets))
        if st.get("wallets") != w9:
            for m9 in memo.values():
                if isinstance(m9, dict) and m9.get("r") == "not_direct":
                    m9["r"] = "retry"
            st["wallets"] = w9
        if isinstance(lo_blk, int):
            for h in cands:
                m9 = memo.get(h) or {}
                if m9.get("r") == "old" and isinstance(m9.get("blk"), int) and m9["blk"] > lo_blk:
                    m9["r"] = "retry"
        todo = [h for h in cands if h not in self.emitted and (memo.get(h) or {}).get("r") in (None, "retry", "ahead", "nf")
                and not ((memo.get(h) or {}).get("r") == "nf" and int((memo.get(h) or {}).get("nf_n") or 0) >= XIN_NF_MAX)]
        todo.sort(key=lambda h: int((memo.get(h) or {}).get("tried_at") or 0))
        n_new = 0
        for h in todo:
            if n_new >= XIN_MAX_NEW:
                break
            m = memo.setdefault(h, {})
            n_new += 1
            m["tried_at"] = int(_now())
            try:
                snap = self.fetch_details([h]).get(h)
            except Exception as e:
                snap = e
            if not isinstance(snap, dict):
                nf = _xin_not_found(snap)
                m.update(r="nf" if nf else "retry", n=int(m.get("n") or 0) + 1,
                         nf_n=(int(m.get("nf_n") or 0) + 1 if m.get("r") == "nf" else 1) if nf else 0, err=common.safe_err(snap)[:120])
                continue
            tx = snap.get("tx") or {}
            try:
                blk = int(tx.get("block_number"))
                val = int(str(tx.get("value") or "0"))
            except (TypeError, ValueError):
                m.update(r="retry", n=int(m.get("n") or 0) + 1)
                continue
            to = str(tx.get("to") or "").lower()
            if to not in self.wallets or val <= 0 or tx.get("status") != "ok":
                m.update(r="not_direct", blk=blk)
                continue
            if isinstance(lo_blk, int) and blk <= lo_blk:
                m.update(r="old", blk=blk)
                continue
            if blk > safe:
                m.update(r="ahead", blk=blk)
                continue
            try:
                self.writer.append({"v": 1, "kind": "evm_tx", "chain": "bsc", "txhash": h, "snapshot": snap, "wallets": self.wallets,
                                    "observed_head": head, "ts": int(time.time()), "via": "exchange_txid"})
            except Exception as e:
                log.error("BSC 거래소 출금 txid 회수 — inbox 쓰기 실패(다음 기회): %s", e)
                break
            self.emitted.add(h)
            m.update(r="emit", blk=blk, to=to)
            n_emit += 1
            log.info("★BSC 받는 쪽 순수 BNB 회수(거래소 출금 txid) %s 블록 %d★", h[:14], blk)
        self._xin_hints(memo)
        st["tx"] = {h: v for h, v in memo.items() if h in set(cands)}
        common.atomic_write_json(self._xin_path(), st)
        if n_emit:
            common.write_json_if_changed(self.meta_path, self.token_meta)
            common.write_json_if_changed(self.emitted_path, sorted(self.emitted))
        return n_emit

    def _balw_path(self) -> str:
        return os.path.join(common.STATE_DIR, "bsc_balw.json")

    def _balw_load(self) -> dict:
        d = self.__dict__.get("_balw_st")
        if d is None:
            try:
                d = common.read_json(self._balw_path(), {})
            except SystemExit as e:
                log.warning("BSC 잔고 감시 진행 파일 손상 — 새로 시작: %s", str(e)[:120])
                d = {}
            if not isinstance(d, dict) or not isinstance(d.get("w"), dict) or not isinstance(d.get("d"), dict):
                d = {"v": 1, "w": {}, "d": {}}
            self._balw_st = d
        return d

    def _balw_save(self):
        common.atomic_write_json(self._balw_path(), self._balw_load())

    @staticmethod
    def _balw_lo(ws) -> "int | None":
        if not isinstance(ws, dict):
            return None
        c = []
        cp = ws.get("cp")
        if isinstance(cp, list) and len(cp) == 3 and isinstance(cp[0], int):
            c.append(cp[0])
        c += [j["a"] for j in ws.get("jobs") or [] if isinstance(j, dict) and isinstance(j.get("a"), int)]
        c += [u["a"] for u in ws.get("ux") or [] if isinstance(u, dict) and isinstance(u.get("a"), int)]
        return min(c) if c else None

    def _balw_put(self, st: dict, w: str, h: str, b: int, snap: dict) -> bool:
        cur = st["d"].setdefault(w, {})
        r = _native_delta(snap, w) if _touches(snap, w) else None
        if r is None:
            return cur.pop(h, None) is not None
        v = [int(b), str(r[0]), 1 if r[1] else 0]
        if cur.get(h) == v:
            return False
        cur[h] = v
        return True

    def _balw_note(self, rec: dict):
        snap = (rec or {}).get("snapshot") or {}
        tx = snap.get("tx") or {}
        try:
            b = int(tx.get("block_number"))
        except (TypeError, ValueError):
            return
        h = str((rec or {}).get("txhash") or tx.get("hash") or "").lower()
        if not h:
            return
        st = self._balw_load()
        ch = False
        for w in self.wallets:
            lo = self._balw_lo(st["w"].get(w))
            if lo is not None and b > lo:
                ch = self._balw_put(st, w, h, b, snap) or ch
        if ch:
            self._balw_save()

    @staticmethod
    def _balw_left(cnt: dict) -> int:
        return int(cnt.get("cap") or BALW_CALL_CAP) - int(cnt["n"])

    @staticmethod
    def _balw_stop_budget(cnt: dict, why: str):
        if cnt.get("cap") is not None:
            cnt["soft"] = True
        raise _BalwStop(why)

    def _balw_charge(self, cnt: dict, n: int):
        st = self._balw_load()
        if time.time() > cnt["t_end"]:
            raise _BalwStop("실행 시간 상한")
        if cnt["n"] + n > BALW_CALL_CAP:
            raise _BalwStop("실행당 호출 상한")
        if cnt["n"] + n > int(cnt.get("cap") or BALW_CALL_CAP):
            self._balw_stop_budget(cnt, "최신 작업 몫 호출 상한")
        if cnt.get("t_soft") and time.time() > float(cnt["t_soft"]):
            self._balw_stop_budget(cnt, "최신 작업 몫 시간")
        day = time.strftime("%Y-%m-%d", time.gmtime(_now()))
        if st.get("day") != day:
            st["day"], st["day_n"] = day, 0
        if int(st.get("day_n") or 0) + n > BALW_DAY_CAP:
            raise _BalwStop("하루 호출 상한")
        cnt["n"] += n
        st["day_n"] = int(st.get("day_n") or 0) + n

    def _balw_call(self, cnt: dict, m: str, p, recent: bool = False):
        self._balw_charge(cnt, 1)
        pub = getattr(self, "nonce_pub_rpc", None)
        arch = getattr(self, "arch_rpc", None)
        last = None
        if pub is not None and (recent or arch is None):
            try:
                return pub.call(m, p, timeout=15)
            except Exception as e:
                last = e
        if arch is None:
            raise _BalwNoArch(f"옛 블록 상태를 줄 아카이브 노드 없음({common.safe_err(last)[:80] if last else '공개 노드 없음'})")
        if float(self._balw_load().get("bo_until") or 0) > _now():
            raise _BalwStop("아카이브 쉬는 중")
        try:
            return arch.call(m, p, timeout=20)
        except _BalwStop:
            raise
        except Exception as e:
            if isinstance(e, bf_engine.NetError) and e.kind in _NONCE_STOP_KINDS:
                cnt["halt"] = e
                raise _BalwStop(_nonce_why(e)) from e
            if _balw_nostate(e):
                if pub is not None and last is None:
                    try:
                        return pub.call(m, p, timeout=15)
                    except _BalwStop:
                        raise
                    except Exception as e2:
                        last = e2
                try:
                    age = int(cnt.get("head") or 0) - int(str(p[-1]), 16)
                except (TypeError, ValueError, IndexError):
                    age = None
                if age is not None and age > BALW_PUB_SCAN:
                    raise _BalwNoState("아카이브가 그 블록 상태를 못 줌(" + _nonce_why(e)[:100] + ")") from e
            raise

    def _balw_read(self, ws_list: list, S: int, cnt: dict) -> dict:
        out = {}
        bh = hex(int(S))
        pub = getattr(self, "nonce_pub_rpc", None)
        nw = (self._nonce_load().get("w") or {})
        known = {}
        for w in ws_list:
            ws9 = nw.get(w) or {}
            try:
                if ws9.get("top") == int(S):
                    known[w] = int((ws9.get("ns") or {})[str(int(S))])
            except (KeyError, TypeError, ValueError):
                pass
        if pub is not None:
            items, slots = [], []
            for w in ws_list:
                slots.append((w, len(items), None if w in known else len(items) + 1))
                items.append(("eth_getBalance", [w, bh]))
                if w not in known:
                    items.append(("eth_getTransactionCount", [w, bh]))
            res = []
            for i in range(0, len(items), NONCE_TOP_BATCH):
                try:
                    res += list(pub.batch(items[i:i + NONCE_TOP_BATCH], timeout=15))
                except _BalwStop:
                    break
                except Exception as e:
                    log.debug("BSC 잔고 감시 — 공개 노드 배치 실패: %s", common.safe_err(e)[:120])
                    res += [None] * len(items[i:i + NONCE_TOP_BATCH])
            for w, jb, jn in slots:
                try:
                    out[w] = (int(res[jb], 16), known[w] if jn is None else int(res[jn], 16))
                except (TypeError, ValueError, IndexError, KeyError):
                    pass
        for w in ws_list:
            if w in out or pub is not None:
                continue
            if cnt["n"] + 2 > max(2, BALW_CALL_CAP // 2):
                break
            try:
                b9 = int(self._balw_call(cnt, "eth_getBalance", [w, bh], recent=True), 16)
                n9 = int(self._balw_call(cnt, "eth_getTransactionCount", [w, bh], recent=True), 16)
                out[w] = (b9, n9)
            except _BalwStop:
                break
            except Exception as e:
                log.debug("BSC 잔고 감시 %s 블록 %d 잔고 못 읽음: %s", w[:10], S, common.safe_err(e)[:120])
        return out

    def _balw_f(self, st: dict, w: str, job: dict, b: int) -> int:
        s = job["s"]
        a = int(job["a"])
        ex, seen = 0, set()
        for h, v in (st["d"].get(w) or {}).items():
            if a < v[0] <= b:
                ex += int(v[1])
                seen.add(h)
        for h, v in (job.get("xd") or {}).items():
            if h not in seen and a < v[0] <= b:
                ex += int(v[1])
        return int(s[str(b)]) - int(s[str(a)]) - ex

    def _balw_emit(self, h: str, snap: dict, head: int, cnt: dict):
        self.writer.append({"v": 1, "kind": "evm_tx", "chain": "bsc", "txhash": h, "snapshot": snap, "wallets": self.wallets,
                            "observed_head": head, "ts": int(time.time()), "via": "balw"})
        self.emitted.add(h)
        cnt["emit"] += 1

    def _balw_disc_req(self, st: dict, w: str, blk: int, bal: int, ts: int, d: int, why: str, old: bool = False) -> bool:
        p = os.path.join(common.STATE_DIR, DISC_REQ_NAME)
        cur = common.read_control_json(p, None)
        items = list(cur.get("items") or []) if isinstance(cur, dict) and isinstance(cur.get("items"), list) else []
        if any(isinstance(x, dict) and x.get("chain") == "bsc" and str(x.get("wallet") or "").lower() == w and x.get("block") == int(blk)
               and x.get("ca") in (None, "", "native") for x in items):
            return False
        items.append({"chain": "bsc", "wallet": w, "ca": None, "block": int(blk), "chain_bal_raw": str(int(bal)), "block_ts": int(ts),
                      "diff_raw": str(max(1, int(d))), "spam": False, "symbol": "BNB", "decimals": 18,
                      "sources": ["bsc_balance_watch_old" if old else "bsc_balance_watch"]})
        common.atomic_write_json(p, {"items": items, "by": "tj-bsc 잔고 감시", "ts": int(time.time())})
        rq = st.setdefault("reqs", [])
        rq.append([w[:10], int(blk), str(int(d)), why, int(_now())])
        del rq[:-20]
        log.warning("★BSC 받는 쪽 BNB %s… 블록 %d +%d wei — 어느 거래인지 못 가림(%s) · 원가 미상 기초 잔고 요청(core 가 그 블록 잔고로 다시 재고 기장)★",
                    w[:10], int(blk), int(d), why)
        return True

    def _balw_resolve(self, st: dict, w: str, job: dict, y: int, d: int, head: int, cnt: dict):
        self._balw_charge(cnt, 1)
        blk = self.rpc.call("eth_getBlockByNumber", [hex(y), True]) or {}
        txs = blk.get("transactions")
        try:
            num9, ts9 = int(str(blk.get("number")), 16), int(str(blk.get("timestamp")), 16)
        except (TypeError, ValueError):
            num9, ts9 = -1, 0
        if num9 != y or not isinstance(txs, list):
            raise RuntimeError(f"블록 {y} 전체 응답 불완전")
        self.block_ts[hex(y)] = ts9
        idx = st["d"].setdefault(w, {})
        direct = []
        for t in txs:
            if not isinstance(t, dict):
                continue
            h = str(t.get("hash") or "").lower()
            if h and h not in idx and h not in (job.get("xd") or {}) and w in (str(t.get("from") or "").lower(), str(t.get("to") or "").lower()):
                direct.append(h)
        if direct:
            k9 = min(5, max(0, self._balw_left(cnt) // 3))
            if k9 <= 0:
                self._balw_stop_budget(cnt, "직접 거래 상세 몫 없음 — 다음 실행")
            more9 = len(direct) > k9
            direct = direct[:k9]
            self._balw_charge(cnt, 3 * len(direct))
            dets = self.fetch_details(direct, deadline=cnt["t_end"])
            if time.time() > cnt["t_end"]:
                raise _BalwStop("직접 거래 상세 마감")
            for h in direct:
                snap = dets.get(h)
                if not isinstance(snap, dict):
                    raise RuntimeError(f"블록 {y} 상세 실패 {h[:12]}: {common.safe_err(snap)[:80]}")
                if h in self.emitted:
                    self._balw_put(st, w, h, y, snap)
                    continue
                self._balw_emit(h, snap, head, cnt)
                log.info("★BSC 받는 쪽 BNB 회수(잔고 감시 · 직접 거래) %s 블록 %d★", h[:14], y)
            common.write_json_if_changed(self.emitted_path, sorted(self.emitted))
            common.write_json_if_changed(self.meta_path, self.token_meta)
            if more9:
                self._balw_stop_budget(cnt, "한 블록 직접 거래 남음 — 다음 실행")
            d = self._balw_f(st, w, job, y) - self._balw_f(st, w, job, y - 1)
            if d < BALW_DUST:
                job.setdefault("done", []).append(y)
                return
        cands = sorted(h for h, v in idx.items() if v[0] == y)
        pick = cands[0] if len(cands) == 1 else None
        if pick is None:
            self._balw_charge(cnt, 1)
            try:
                rcs = self.rpc.call("eth_getBlockReceipts", [hex(y)])
            except Exception as e:
                log.debug("BSC 잔고 감시 블록 %d 영수증 묶음 실패: %s", y, common.safe_err(e)[:80])
                rcs = None
            hits = set()
            pw, wh = _pad_topic(w), w[2:]
            for rc in rcs if isinstance(rcs, list) else []:
                if not isinstance(rc, dict) or rc.get("status") != "0x1":
                    continue
                for lg in rc.get("logs") or []:
                    tps = [str(x).lower() for x in (lg.get("topics") or [])] if isinstance(lg, dict) else []
                    if pw in tps[1:] or (isinstance(lg, dict) and wh in str(lg.get("data") or "").lower()):
                        hits.add(str(rc.get("transactionHash") or "").lower())
                        break
            hits.discard("")
            pool = (set(cands) & hits) if cands else hits
            pick = next(iter(pool)) if len(pool) == 1 else None
        if pick:
            self._balw_charge(cnt, 3)
            snap = self.fetch_details([pick], deadline=cnt["t_end"]).get(pick)
            if time.time() > cnt["t_end"]:
                raise _BalwStop("귀속 상세 마감")
            if not isinstance(snap, dict):
                raise RuntimeError(f"블록 {y} 귀속 상세 실패 {pick[:12]}: {common.safe_err(snap)[:80]}")
            if (snap.get("tx") or {}).get("status") == "ok":
                tx9 = snap["tx"]
                snap = dict(snap, internal=list(snap.get("internal") or []) + [
                    {"from": str(tx9.get("to") or tx9.get("from") or "").lower(), "to": w, "value": str(int(d)), "success": True, "attr": "balance_delta"}],
                    internal_note="balance_delta")
                self._balw_emit(pick, snap, head, cnt)
                common.write_json_if_changed(self.emitted_path, sorted(self.emitted))
                common.write_json_if_changed(self.meta_path, self.token_meta)
                log.info("★BSC 받는 쪽 BNB 회수(잔고 감시 · internal 귀속) %s 블록 %d +%d wei★", pick[:14], y, int(d))
                job.setdefault("done", []).append(y)
                return
        self._balw_disc_req(st, w, y, int(job["s"][str(y)]), ts9, d, "로그 없는 internal · 단서 거래 없음" if not pick else "단서 거래 실패")
        job.setdefault("done", []).append(y)

    def _balw_pubscan(self, st: dict, w: str, job: dict, head: int, cnt: dict):
        x, y, nxt = (int(v9) for v9 in job["scan"])
        pub = getattr(self, "nonce_pub_rpc", None)
        idx = st["d"].setdefault(w, {})
        while nxt <= y:
            self._balw_charge(cnt, 0)
            n9 = min(BALW_SCAN_BATCH, y - nxt + 1)
            if int(cnt.get("scan") or 0) + n9 > int(cnt.get("scan_cap") or BALW_SCAN_RUN):
                self._balw_stop_budget(cnt, "공개 블록 본문 훑기 실행 상한")
            cnt["scan"] = int(cnt.get("scan") or 0) + n9
            res = pub.batch([("eth_getBlockByNumber", [hex(b9), True]) for b9 in range(nxt, nxt + n9)], timeout=20)
            found = []
            for b9, blk in zip(range(nxt, nxt + n9), list(res) + [None] * n9):
                try:
                    ok9 = isinstance(blk, dict) and int(str(blk.get("number")), 16) == b9 and isinstance(blk.get("transactions"), list)
                    ts9 = int(str(blk.get("timestamp")), 16) if ok9 else None
                except (TypeError, ValueError):
                    ok9 = False
                if not ok9:
                    raise RuntimeError(f"공개 블록 {b9} 본문 응답 불완전")
                self.block_ts[hex(b9)] = ts9
                for t in blk["transactions"]:
                    if not isinstance(t, dict) or str(t.get("to") or "").lower() != w:
                        continue
                    h = str(t.get("hash") or "").lower()
                    try:
                        v9 = int(str(t.get("value") or "0x0"), 16)
                    except ValueError:
                        v9 = 0
                    if h and v9 >= BALW_DUST and h not in idx:
                        found.append((b9, h))
            more9 = False
            if found:
                k9 = max(0, self._balw_left(cnt) // 3)
                if k9 <= 0:
                    self._balw_stop_budget(cnt, "공개 블록 본문 훑기 — 실행당 호출 상한")
                more9 = len(found) > k9
                found = found[:k9]
                self._balw_charge(cnt, 3 * len(found))
                dets = self.fetch_details([h for _b9, h in found], deadline=cnt["t_end"])
                if time.time() > cnt["t_end"]:
                    raise _BalwStop("공개 블록 본문 훑기 — 상세 마감")
                for b9, h in found:
                    snap = dets.get(h)
                    if not isinstance(snap, dict):
                        raise RuntimeError(f"공개 블록 {b9} 입금 상세 실패 {h[:12]}: {common.safe_err(snap)[:80]}")
                    if h in self.emitted:
                        self._balw_put(st, w, h, b9, snap)
                        continue
                    self._balw_emit(h, snap, head, cnt)
                    log.info("★BSC 받는 쪽 BNB 회수(잔고 감시 · 공개 블록 본문 — 아카이브 없음) %s 블록 %d★", h[:14], b9)
                common.write_json_if_changed(self.emitted_path, sorted(self.emitted))
                common.write_json_if_changed(self.meta_path, self.token_meta)
            if more9:
                self._balw_stop_budget(cnt, "공개 블록 본문 훑기 — 이 묶음 남은 입금은 다음 실행")
            nxt += n9
            job["scan"][2] = nxt
        rest = self._balw_f(st, w, job, y) - self._balw_f(st, w, job, x)
        if rest >= BALW_DUST:
            ts9 = self.block_ts.get(hex(y))
            if ts9 is None:
                self._balw_charge(cnt, 1)
                ts9 = self._block_time(hex(y))
            self._balw_disc_req(st, w, y, int(job["s"][str(y)]), ts9, rest, "아카이브 없음 · 직접 거래 없음(internal)")
        job.setdefault("sd", []).append([x, y])
        job.pop("scan", None)

    def _balw_close(self, st: dict, w: str, job: dict, why: str, cnt: dict):
        z = int(job["z"])
        try:
            rest = self._balw_f(st, w, job, z) - sum(max(0, self._balw_f(st, w, job, y) - self._balw_f(st, w, job, y - 1))
                                                     for y in job.get("done") or [] if str(y - 1) in job["s"] and str(y) in job["s"])
        except (KeyError, TypeError, ValueError):
            rest = BALW_DUST
        if rest >= BALW_DUST:
            ts9 = self.block_ts.get(hex(z))
            if ts9 is None:
                try:
                    self._balw_charge(cnt, 1)
                    ts9 = self._block_time(hex(z))
                except _BalwStop:
                    raise
                except Exception:
                    return False
            self._balw_disc_req(st, w, z, int(job["s"][str(z)]), ts9, rest, why, old=job.get("k") == "hist")
        return True

    def _balw_hist(self, st: dict, eoas: list, cnt: dict):
        if isinstance(self.cursor.get("_live"), dict):
            return
        try:
            chk = common.read_json(os.path.join(common.STATE_DIR, "onchain_check.json"), {})
        except SystemExit:
            return
        now = _now()
        lo = self.cursor.get("_cov") if isinstance(self.cursor.get("_cov"), int) else self.cursor.get("_bf_start")
        for m in (chk.get("mismatches") or []) if isinstance(chk, dict) else []:
            if not isinstance(m, dict) or m.get("chain") != "bsc" or m.get("ca") or not m.get("confirmed"):
                continue
            w = str(m.get("wallet") or "").lower()
            if w not in eoas:
                continue
            try:
                gap = float(m.get("onchain")) - float(m.get("ledger"))
            except (TypeError, ValueError):
                continue
            ws = st["w"].get(w) or {}
            cp = ws.get("cp")
            if gap <= 0 or not (isinstance(cp, list) and len(cp) == 3) or ws.get("jobs") or now - float(ws.get("hist_at") or 0) < BALW_HIST_GAP:
                continue
            ws["hist_at"] = int(now - BALW_HIST_GAP + BALW_HIST_RETRY)
            z, bz = int(cp[0]), int(cp[1])
            a = max(int(lo) if isinstance(lo, int) and lo > 0 else 1, z - int(BALW_HIST_DAYS * 86400 / self._bsec()))
            if a >= z:
                ws["hist_at"] = int(now)
                continue
            xd = self._balw_raw_deltas(w, a, z, deadline=cnt["t_end"])
            if xd is None:
                continue
            job = {"k": "hist", "a": a, "z": z, "s": {str(z): str(bz)}, "t0": int(now), "n": 0, "done": [], "xd": xd}
            try:
                job["s"][str(a)] = str(int(self._balw_call(cnt, "eth_getBalance", [w, hex(a)]), 16))
            except _BalwNoArch as e:
                if isinstance(e, _BalwNoState):
                    ws["hist_ns"] = int(ws.get("hist_ns") or 0) + 1
                    if ws["hist_ns"] < BALW_NOSTATE_N:
                        continue
                ws.pop("hist_ns", None)
                self._balw_charge(cnt, 1)
                self._balw_disc_req(st, w, z, bz, self._block_time(hex(z)), int(gap * 10 ** 18), "지난 누락 · 아카이브 없음", old=True)
                ws["hist_at"] = int(now)
                continue
            ws.pop("hist_ns", None)
            r = self._balw_f(st, w, job, z)
            log.info("BSC 잔고 감시 %s: 잔고 대조 부족 %.6f BNB — 지난 %d일 창(블록 %d~%d) 설명 안 되는 증가 %d wei", w[:10], gap, BALW_HIST_DAYS, a, z, r)
            if r < BALW_DUST:
                self._balw_charge(cnt, 1)
                ts9 = self._block_time(hex(a))
                self._balw_disc_req(st, w, a, int(job["s"][str(a)]), ts9, int(gap * 10 ** 18), "지난 누락 · 창 이전(또는 원장 쪽)", old=True)
                ws["hist_at"] = int(now)
                continue
            ws.setdefault("jobs", []).append(job)
            ws["hist_at"] = int(now)

    def _balw_raw_deltas(self, w: str, a: int, z: int, deadline: float = None, cache: dict = None):
        if not os.path.exists(common.DB_PATH):
            return {}
        import sqlite3
        rows = cache.get((int(a), int(z))) if cache is not None else None
        if rows is None:
            left = 10.0 if deadline is None else min(10.0, float(deadline) - time.time())
            if left <= 0:
                return None
            try:
                con = sqlite3.connect(common.sqlite_ro_uri(common.DB_PATH), uri=True, timeout=left)
                try:
                    if deadline is not None:
                        con.set_progress_handler(lambda: 1 if time.time() >= deadline else 0, 2000)
                    if cache is not None:
                        rows = [(h9, b9, sn9, str(sn9).lower()) for h9, b9, sn9 in con.execute(
                            "SELECT lower(txhash), block, snapshot FROM raw_txs WHERE chain='bsc' AND block > ? AND block <= ?", (int(a), int(z)))]
                        cache[(int(a), int(z))] = rows
                    else:
                        rows = con.execute("SELECT lower(txhash), block, snapshot FROM raw_txs WHERE chain='bsc' AND block > ? AND block <= ?"
                                           " AND instr(lower(snapshot), ?) > 0", (int(a), int(z), w[2:])).fetchall()
                finally:
                    con.close()
            except Exception as e:
                log.info("BSC 잔고 감시 — 원장 읽기 실패(다음 기회): %s", str(e)[:120])
                return None
        if cache is not None:
            rows = [(h9, b9, sn9) for h9, b9, sn9, low9 in rows if w[2:] in low9]
        out = {}
        for h, b, sn in rows:
            try:
                snap = json.loads(sn)
            except (TypeError, ValueError):
                continue
            if isinstance(snap, dict) and b is not None and _touches(snap, w):
                r = _native_delta(snap, w)
                if r is not None:
                    out[str(h)] = [int(b), str(r[0]), 1 if r[1] else 0]
        return out

    def _balw_win(self, st: dict, w: str, lo: list, hi: list, cnt: dict, raw: bool = False):
        a, ba, na = int(lo[0]), int(lo[1]), int(lo[2])
        z, bz, nz = int(hi[0]), int(hi[1]), int(hi[2])
        idx = {h: v for h, v in (st["d"].get(w) or {}).items() if a < v[0] <= z}
        sent = sum(int(v[2]) for v in idx.values())
        xd = {}
        if raw or nz - na > sent:
            rd = self._balw_raw_deltas(w, a, z, deadline=cnt["t_end"], cache=cnt.setdefault("raw9", {}))
            if rd is None:
                return "noraw", 0, {}
            xd = {h: v for h, v in rd.items() if h not in idx}
            sent += sum(int(v[2]) for v in xd.values() if len(v) > 2)
        r = (bz - ba) - sum(int(v[1]) for v in idx.values()) - sum(int(v[1]) for v in xd.values())
        if nz - na == sent:
            return "ok", r, xd
        return ("miss" if nz - na > sent else "excess"), r, xd

    def _balw_job_add(self, st: dict, w: str, ws: dict, lo: list, hi: list, r: int, xd: dict, now: float, cnt: dict, why: str = "", back: bool = False):
        jobs = ws.setdefault("jobs", [])
        a, z = int(lo[0]), int(hi[0])
        job = {"k": "fwd", "a": a, "z": z, "s": {str(a): str(int(lo[1])), str(z): str(int(hi[1]))}, "t0": int(now), "n": 0, "done": []}
        if xd:
            job["xd"] = xd
        if back:
            job["back"] = True
        jobs.append(job)
        log.info("BSC 잔고 감시 %s: 블록 %d~%d 설명 안 되는 BNB 증가 %d wei — 이분 탐색%s", w[:10], a, z, r, (" · " + why) if why else "")
        try:
            while len(jobs) > BALW_JOBS_MAX:
                v9 = min(jobs, key=lambda j9: (int(j9.get("z") or 0), int(j9.get("a") or 0)))
                if not self._balw_close(st, w, v9, "작업 상한", cnt):
                    break
                jobs.remove(v9)
        except _BalwStop:
            pass

    def _balw_ux_add(self, w: str, ws: dict, lo: list, hi: list, now: float, why: str):
        ux = ws.setdefault("ux", [])
        a, z = int(lo[0]), int(hi[0])
        if ux and isinstance(ux[-1], dict) and ux[-1].get("z") == a:
            ux[-1].update(z=z, bz=str(int(hi[1])), nz=int(hi[2]))
        else:
            ux.append({"a": a, "ba": str(int(lo[1])), "na": int(lo[2]), "z": z, "bz": str(int(hi[1])), "nz": int(hi[2]), "t0": int(now), "why": why})
        log.info("BSC 잔고 감시 %s: 블록 %d~%d 미해결 구간(%s) — 색인·원장으로 다시 설명한 뒤 평가(체크포인트를 버리지 않음)", w[:10], a, z, why)

    def _balw_ux_step(self, st: dict, eoas: list, cnt: dict, now: float, nst: dict):
        lv = self.cursor.get("_live")
        holes = []
        for h9 in (lv.get("holes") or []) if isinstance(lv, dict) else []:
            try:
                holes.append((int(h9[0]), int(h9[1])))
            except (TypeError, ValueError, IndexError):
                pass
        for w in eoas:
            ws = st["w"].get(w)
            ux = ws.get("ux") if isinstance(ws, dict) else None
            if not isinstance(ux, list) or not ux:
                continue
            keep = []
            for k, sg in enumerate(ux):
                try:
                    lo, hi = [int(sg["a"]), int(sg["ba"]), int(sg["na"])], [int(sg["z"]), int(sg["bz"]), int(sg["nz"])]
                except (KeyError, TypeError, ValueError, AttributeError):
                    log.warning("BSC 잔고 감시 %s: 미해결 구간 항목 손상 — 버림: %s", w[:10], str(sg)[:120])
                    continue
                a, z = lo[0], hi[0]
                if time.time() > cnt["t_end"] or any(ha < z and hb > a for ha, hb in holes):
                    keep.append(sg)
                    continue
                v9, r, xd = self._balw_win(st, w, lo, hi, cnt, raw=True)
                if v9 in ("noraw", "miss"):
                    over = len(ux) - k > BALW_JOBS_MAX
                    aged = now - float(sg.get("t0") or now) > BALW_JOB_KEEP and (nst["w"].get(w) or {}).get("missing") == 0
                    if not (over or aged) or not self._balw_ux_close(st, w, hi, r, cnt, "미해결 구간 마감(" + ("상한" if over else "7일") + " · " + v9 + ")"):
                        keep.append(sg)
                    continue
                if v9 == "excess":
                    log.info("BSC 잔고 감시 %s: 미해결 구간 %d~%d 내 발신 과다(색인 불일치) — 구간 끝 기초 잔고 요청으로 마감", w[:10], a, z)
                    if not self._balw_ux_close(st, w, hi, r, cnt, "미해결 구간 · 색인 불일치"):
                        keep.append(sg)
                elif r >= BALW_DUST:
                    self._balw_job_add(st, w, ws, lo, hi, r, xd, now, cnt, "미해결 구간(" + str(sg.get("why") or "") + ")", back=True)
                elif r <= -BALW_DUST:
                    log.info("BSC 잔고 감시 %s: 미해결 구간 %d~%d 설명 안 되는 BNB 감소 %d wei(감수)", w[:10], a, z, -r)
            if keep:
                ws["ux"] = keep
            else:
                ws.pop("ux", None)

    def _balw_ux_close(self, st: dict, w: str, hi: list, r: int, cnt: dict, why: str) -> bool:
        z, bz = int(hi[0]), int(hi[1])
        ts9 = self.block_ts.get(hex(z))
        try:
            if ts9 is None:
                self._balw_charge(cnt, 1)
                ts9 = self._block_time(hex(z))
        except Exception as e:
            log.debug("BSC 잔고 감시 %s: 미해결 구간 끝 블록 시각 실패: %s", w[:10], common.safe_err(e)[:80])
            return False
        log.warning("BSC 잔고 감시 %s: %s — 블록 %d 기초 잔고 요청(잔여 %d wei · core 가 잔고 − 원장으로 다시 잼)", w[:10], why, z, int(r))
        self._balw_disc_req(st, w, z, bz, ts9, max(1, int(r)), why)
        return True

    def _balw_rx(self, st: dict, eoas: list, cnt: dict):
        p = os.path.join(common.STATE_DIR, BALW_RX_NAME)
        req = common.read_control_json(p, None) if os.path.exists(p) else None
        now = _now()
        if req is not None:
            since = None
            if isinstance(req, dict):
                v9 = req.get("since") if req.get("since") is not None else req.get("hours")
                try:
                    f9 = float(v9) if not isinstance(v9, bool) else float("nan")
                except (TypeError, ValueError, OverflowError):
                    f9 = float("nan")
                if req.get("since") is not None and 0 < f9 < now:
                    since = int(f9)
                elif req.get("since") is None and 0 < f9 <= BALW_RX_MAX_H:
                    since = int(now - f9 * 3600)
            if not since:
                bad9 = p + ".bad" if not os.path.exists(p + ".bad") else p + ".bad." + str(int(time.time()))
                try:
                    os.replace(p, bad9)
                except OSError:
                    pass
                log.warning("BSC 잔고 감시 — 지난 공백 다시 점검 요청 형식·범위 오류(%s 로 옮김): %s", os.path.basename(bad9), str(req)[:120])
                req = None
        if req is not None:
            want = {str(x).lower() for x in req["wallets"]} if isinstance(req.get("wallets"), list) else set()
            n9 = 0
            for w in eoas:
                ws = st["w"].get(w)
                if isinstance(ws, dict) and isinstance(ws.get("cp"), list) and (not want or w in want):
                    ws["rx"] = int(since)
                    n9 += 1
            log.warning("★BSC 잔고 감시 — 지난 공백 다시 점검 요청: %s 부터 · 지갑 %d개(원장 + 옛 블록 잔고로 다시 설명)★",
                        time.strftime("%Y-%m-%d %H:%M", time.gmtime(since)) + " UTC", n9)
            cnt["rx_take"] = p
        lo = self.cursor.get("_cov") if isinstance(self.cursor.get("_cov"), int) else self.cursor.get("_bf_start")
        for w in eoas:
            ws = st["w"].get(w)
            if not isinstance(ws, dict) or not ws.get("rx"):
                continue
            cp = ws.get("cp")
            if not (isinstance(cp, list) and len(cp) == 3):
                ws.pop("rx", None)
                continue
            if ws.get("jobs") or ws.get("ux"):
                continue
            z, bz = int(cp[0]), int(cp[1])
            age = max(0.0, float(ws.get("cp_at") or now) - float(ws["rx"]))
            a = max(int(lo) if isinstance(lo, int) and lo > 0 else 1, z - int(age * 1.1 / self._bsec()) - 100)
            if a >= z:
                ws.pop("rx", None)
                continue
            xd = self._balw_raw_deltas(w, a, z, deadline=cnt["t_end"])
            if xd is None:
                return
            job = {"k": "fwd", "a": a, "z": z, "s": {str(z): str(bz)}, "t0": int(now), "n": 0, "done": [], "xd": xd, "back": True}
            try:
                job["s"][str(a)] = str(int(self._balw_call(cnt, "eth_getBalance", [w, hex(a)]), 16))
            except _BalwNoArch as e:
                if isinstance(e, _BalwNoState):
                    ws["rx_ns"] = int(ws.get("rx_ns") or 0) + 1
                    if ws["rx_ns"] < BALW_NOSTATE_N:
                        continue
                log.warning("BSC 잔고 감시 %s: 지난 공백 다시 점검 못 함 — 블록 %d 잔고 모름(%s)", w[:10], a, str(e)[:80])
                ws.pop("rx", None)
                ws.pop("rx_ns", None)
                continue
            ws.pop("rx_ns", None)
            r = self._balw_f(st, w, job, z)
            ws.pop("rx", None)
            if r >= BALW_DUST:
                ws.setdefault("jobs", []).append(job)
                log.info("BSC 잔고 감시 %s: 지난 공백 다시 점검 — 블록 %d~%d 설명 안 되는 BNB 증가 %d wei — 이분 탐색", w[:10], a, z, r)
            else:
                log.info("BSC 잔고 감시 %s: 지난 공백 다시 점검 — 블록 %d~%d 원장으로 다 설명됨", w[:10], a, z)

    @staticmethod
    def _balw_back(job) -> bool:
        return isinstance(job, dict) and (job.get("k") == "hist" or bool(job.get("back")))

    def _balw_jobs(self, st: dict, eoas: list, cnt: dict, head: int, now: float, back: bool):
        skip = cnt.setdefault("skip", {})
        while True:
            cand = [(w9, j9) for w9 in eoas for j9 in ((st["w"].get(w9) or {}).get("jobs") or [])
                    if isinstance(j9, dict) and self._balw_back(j9) == back and id(j9) not in skip]
            if not cand:
                break
            if back:
                w, job = min(cand, key=lambda t9: (float(t9[1].get("lw") or t9[1].get("t0") or 0), int(t9[1].get("t0") or 0)))
            else:
                w, job = max(cand, key=lambda t9: int(t9[1].get("z") or 0))
            jobs = st["w"][w]["jobs"]
            n0 = cnt["n"]
            sc0 = int(cnt.get("scan") or 0)
            x = y = None
            try:
                if now - float(job.get("t0") or now) > BALW_JOB_KEEP or int(job.get("n") or 0) > BALW_JOB_CALLS:
                    if self._balw_close(st, w, job, "탐색 상한(시간·호출)", cnt):
                        jobs.remove(job)
                        continue
                    skip[id(job)] = job
                    continue
                pts = sorted(int(k) for k in job["s"])
                fv = {b: self._balw_f(st, w, job, b) for b in pts}
                done = set(job.get("done") or [])
                sd9 = {tuple(v9) for v9 in job.get("sd") or [] if isinstance(v9, list) and len(v9) == 2}
                ivs = [(x, y) for x, y in zip(pts, pts[1:]) if fv[y] - fv[x] >= BALW_DUST and not (y - x == 1 and y in done)
                       and (x, y) not in sd9]
                if not ivs:
                    jobs.remove(job)
                    cnt["jobs"] += 1
                    continue
                x, y = min(ivs, key=lambda t: (t[1] - t[0], -t[1]))
                if isinstance(job.get("scan"), list):
                    self._balw_pubscan(st, w, job, head, cnt)
                    job.pop("ns", None)
                    continue
                if y - x == 1:
                    self._balw_resolve(st, w, job, y, fv[y] - fv[x], head, cnt)
                else:
                    mid = (x + y) // 2
                    job["s"][str(mid)] = str(int(self._balw_call(cnt, "eth_getBalance", [w, hex(mid)],
                                                                 recent=(head - mid) <= BALW_PUB_NEAR), 16))
                job.pop("ns", None)
            except _BalwNoArch as e:
                if (job.get("k") == "fwd" and x is not None and y is not None and not isinstance(job.get("scan"), list)
                        and y - x <= BALW_PUB_SCAN and getattr(self, "nonce_pub_rpc", None) is not None):
                    job["scan"] = [int(x), int(y), int(x) + 1]
                    continue
                if isinstance(e, _BalwNoState):
                    job["ns"] = int(job.get("ns") or 0) + 1
                    if job["ns"] < BALW_NOSTATE_N:
                        skip[id(job)] = job
                        continue
                if self._balw_close(st, w, job, "아카이브 상태 없음" if isinstance(e, _BalwNoState) else "아카이브 없음", cnt):
                    jobs.remove(job)
                    continue
                skip[id(job)] = job
                continue
            except _BalwStop:
                raise
            except Exception as e:
                skip[id(job)] = job
                cnt.setdefault("err", e)
                log.info("BSC 잔고 감시 %s: 작업 %d~%d 걸음 실패(이 작업만 다음 실행): %s", w[:10], int(job.get("a") or 0), int(job.get("z") or 0),
                         common.safe_err(e)[:120])
                continue
            finally:
                job["n"] = int(job.get("n") or 0) + (cnt["n"] - n0)
                if cnt["n"] > n0 or int(cnt.get("scan") or 0) > sc0:
                    cnt["lwk"] = int(cnt.get("lwk") or 0) + 1
                    job["lw"] = round(float(now) + cnt["lwk"] * 1e-4, 4)
                if not jobs:
                    st["w"][w].pop("jobs", None)

    def _balw_safe(self, head: int, S: int) -> int:
        try:
            return self._balw_pass(head, S)
        except Exception as e:
            log.info("BSC 잔고 감시 실패(다음 기회): %s", common.safe_err(e)[:120])
            return 0

    def _balw_pass(self, head: int, S: int) -> int:
        st = self._balw_load()
        now = _now()
        every = BALW_EVERY if getattr(self, "nonce_pub_rpc", None) is not None else BALW_EVERY_ARCH
        if now - float(st.get("at") or 0) < every:
            return 0
        resting = float(st.get("bo_until") or 0) > now
        prev_at = float(st.get("at") or 0)
        st["at"] = int(now)
        cnt = {"n": 0, "emit": 0, "jobs": 0, "halt": None, "head": int(head),
               "t_end": time.time() + min(BALW_TIME_CAP, max(3.0, self._side_left() / 2.0))}
        nst = self._nonce_load()
        eoas = [w for w in self.wallets if (nst["w"].get(w) or {}).get("kind") == "eoa"]
        stale = prev_at > 0 and now - prev_at > max(BALW_STALE, 2 * every)
        if stale:
            log.info("BSC 잔고 감시 — 지난 확인 뒤 %d분(봇 꺼짐·상류 장애·되돌림 — 그동안 방출이 색인에 없을 수 있음): 체크포인트 유지 · 공백 구간은 원장으로 다시 설명",
                     int((now - prev_at) / 60))
            for ws9 in st["w"].values():
                if isinstance(ws9, dict) and isinstance(ws9.get("cp"), list):
                    ws9["gap"] = int(prev_at)
        for w in list(st["w"]):
            if w not in self.wallets:
                st["w"].pop(w, None)
        for w in list(st["d"]):
            if w not in self.wallets:
                st["d"].pop(w, None)
        err = None
        dl_pools = []
        for pool9 in (getattr(self, "rpc", None), getattr(self, "nonce_pub_rpc", None), getattr(self, "arch_rpc", None)):
            if isinstance(pool9, Rpc) and not any(pool9 is p9 for p9, _o in dl_pools):
                dl_pools.append((pool9, pool9.__dict__.get("_dl")))
                pool9._dl = cnt["t_end"]
        for ws9 in st["w"].values():
            for j9 in (ws9.get("jobs") or []) if isinstance(ws9, dict) else []:
                if isinstance(j9, dict):
                    j9["back"] = True
        try:
            rr0 = int(st.get("read_rr") or 0) % len(eoas) if eoas else 0
            obs = self._balw_read(eoas[rr0:] + eoas[:rr0], S, cnt) if eoas else {}
            st["read_rr"] = (rr0 + max(1, len(obs))) % len(eoas) if eoas and len(obs) < len(eoas) else 0
            for w in eoas:
                o = obs.get(w)
                if o is None:
                    continue
                bal, non = o
                ws = st["w"].setdefault(w, {})
                cp = ws.get("cp")
                ok_cp = isinstance(cp, list) and len(cp) == 3 and all(isinstance(x, (int, str)) for x in cp)
                if not ok_cp or int(cp[0]) > S:
                    ws["cp"], ws["cp_at"] = [int(S), str(bal), int(non)], int(now)
                    ws.pop("gap", None)
                    continue
                B0, b0, n0 = int(cp[0]), int(cp[1]), int(cp[2])
                if B0 == S:
                    continue
                if ws.get("gap"):
                    self._balw_ux_add(w, ws, [B0, b0, n0], [int(S), bal, non], now, "공백")
                    ws.pop("gap", None)
                    ws["cp"], ws["cp_at"] = [int(S), str(bal), int(non)], int(now)
                    continue
                v9, r, xd = self._balw_win(st, w, [B0, b0, n0], [int(S), bal, non], cnt)
                if v9 != "ok":
                    m9 = (nst["w"].get(w) or {}).get("missing")
                    if v9 == "excess":
                        log.info("BSC 잔고 감시 %s: nonce 차 %d < 방출한 내 발신(색인 불일치 · 원장 복원 등) — 체크포인트 다시", w[:10], non - n0)
                        ws["cp"], ws["cp_at"] = [int(S), str(bal), int(non)], int(now)
                    elif now - float(ws.get("cp_at") or now) > BALW_NONCE_STUCK and m9 == 0:
                        self._balw_ux_add(w, ws, [B0, b0, n0], [int(S), bal, non], now, "nonce 정체")
                        ws["cp"], ws["cp_at"] = [int(S), str(bal), int(non)], int(now)
                    continue
                if r >= BALW_DUST:
                    self._balw_job_add(st, w, ws, [B0, b0, n0], [int(S), bal, non], r, xd, now, cnt)
                elif r <= -BALW_DUST:
                    log.info("BSC 잔고 감시 %s: 블록 %d~%d 설명 안 되는 BNB 감소 %d wei(감수 — 귀속 행 과대·위임 코드 등)", w[:10], B0, S, -r)
                ws["cp"], ws["cp_at"] = [int(S), str(bal), int(non)], int(now)
            if not resting:
                back9 = os.path.exists(os.path.join(common.STATE_DIR, BALW_RX_NAME)) or any(
                    (st["w"].get(w9) or {}).get("ux") or (st["w"].get(w9) or {}).get("rx")
                    or any(self._balw_back(j9) for j9 in (st["w"].get(w9) or {}).get("jobs") or []) for w9 in eoas)
                if back9:
                    cnt["cap"] = BALW_CALL_CAP - BALW_BACK_MIN
                    cnt["scan_cap"] = BALW_SCAN_RUN - max(BALW_SCAN_BATCH, BALW_SCAN_RUN // 4)
                    cnt["t_soft"] = time.time() + 0.75 * max(0.0, cnt["t_end"] - time.time())
                try:
                    self._balw_jobs(st, eoas, cnt, head, now, back=False)
                except _BalwStop as e:
                    if cnt["halt"] is not None:
                        raise
                    log.debug("BSC 잔고 감시 — 최신 작업 단계 끝(옛 몫 단계로): %s", e)
                finally:
                    cnt.pop("cap", None)
                    cnt.pop("scan_cap", None)
                    cnt.pop("t_soft", None)
                    cnt.pop("soft", None)
            self._balw_ux_step(st, eoas, cnt, now, nst)
            if resting:
                raise _BalwStop("아카이브 쉬는 중 — 공개 잔고 확인·창 평가만")
            for st9 in (lambda: self._balw_jobs(st, eoas, cnt, head, now, back=True),
                        lambda: self._balw_rx(st, eoas, cnt),
                        lambda: self._balw_hist(st, eoas, cnt)):
                try:
                    st9()
                except _BalwStop as e:
                    if cnt["halt"] is not None:
                        raise
                    log.debug("BSC 잔고 감시 — 옛 몫 단계 멈춤(다음 단계로): %s", e)
                except Exception as e:
                    cnt.setdefault("err", e)
                    log.info("BSC 잔고 감시 — 옛 몫 단계 실패(다음 단계로): %s", common.safe_err(e)[:120])
        except _BalwStop as e:
            log.debug("BSC 잔고 감시 — 이번 실행 멈춤: %s", e)
        except Exception as e:
            err = e
        finally:
            for pool9, old9 in dl_pools:
                if old9 is None:
                    pool9.__dict__.pop("_dl", None)
                else:
                    pool9._dl = old9
        if cnt["halt"] is not None:
            err = cnt["halt"]
        if err is None and cnt.get("err") is not None:
            err = cnt["err"]
        if err is not None:
            n9 = int(st.get("bo_n") or 0) + 1
            st["bo_n"] = n9
            if cnt["halt"] is not None:
                st["bo_until"] = int(_now() + min(BALW_BO_MAX, BALW_BO_BASE * (2 ** min(n9 - 1, 16))))
            log.info("BSC 잔고 감시 실패(다음 기회): %s", _nonce_why(err))
        elif not resting:
            st["bo_n"] = 0
            st.pop("bo_until", None)
        for w in list(st["d"]):
            lo = self._balw_lo(st["w"].get(w))
            st["d"][w] = {h: v for h, v in st["d"][w].items() if lo is not None and v[0] > lo}
        jobs_left = sum(len((st["w"].get(w) or {}).get("jobs") or []) for w in st["w"])
        ux_left = sum(len((st["w"].get(w) or {}).get("ux") or []) for w in st["w"])
        self._balw_facts = {"wallets": len(eoas), "jobs": jobs_left, "calls": cnt["n"], "emit": cnt["emit"],
                            "noarch": getattr(self, "arch_rpc", None) is None, "at": int(now), "ux": ux_left}
        st["last"] = self._balw_facts
        self._balw_save()
        if cnt.get("rx_take"):
            try:
                os.remove(cnt["rx_take"])
            except OSError:
                pass
        if cnt["n"] or cnt["emit"] or jobs_left or ux_left:
            log.info("BSC 잔고 감시: 지갑 %d · 옛 블록 호출 %d · 방출 %d · 끝난 작업 %d · 남은 작업 %d · 미해결 구간 %d", len(eoas), cnt["n"], cnt["emit"],
                     cnt["jobs"], jobs_left, ux_left)
        return cnt["emit"]

    def _report(self, head: int, since: int, phase: str, note: str = None, flush: bool = False):
        start = self.cursor.get("_bf_start")
        if isinstance(start, int) and head > start:
            self.progress.update("bsc", phase=phase, unit="blocks", done=max(0, since - start),
                                 total=max(1, head - self.conf_depth - start), note=note, flush=flush,
                                 lag=max(0, head - self.conf_depth - since), scan=self.last_scan_metrics or None, lanes=None)
        else:
            self.progress.update("bsc", phase=phase, unit="blocks", lag=max(0, head - self.conf_depth - since),
                                 note=note, flush=flush, lanes=None)

    def _bsec(self) -> float:
        v = self.__dict__.get("_hb_bsec")
        try:
            v = float(v) if v else BSC_BLOCK_SEC
        except (TypeError, ValueError):
            v = BSC_BLOCK_SEC
        return min(10.0, max(0.05, v))

    def _seed_blocks(self) -> int:
        return max(100, int(LIVE_SEED_SEC / self._bsec()))

    def _lanes_on(self) -> bool:
        return getattr(self, "lanes_cfg", None) is not False

    def _side_budget(self, tc0: float) -> float:
        v = getattr(self, "lane_budget", None)
        if v is not None:
            return max(0.1, float(v))
        return max(10.0, min(float(getattr(self, "cycle_budget", 600)), float(getattr(self, "poll_sec", 60)) - (time.time() - tc0) - 5.0))

    def _side_left(self) -> float:
        tc0 = self.__dict__.get("_tc0")
        return self._side_budget(tc0) if tc0 else float(getattr(self, "cycle_budget", 600))

    def _set_fb(self, v: int):
        self.cursor["from_block"] = int(v)
        lv = self.cursor.get("_live")
        if isinstance(lv, dict):
            lv["fb"] = int(v)

    def _lane_open(self, safe: int, why: str) -> bool:
        if not self._lanes_on():
            return False
        fb = int(self.cursor.get("from_block") or 0)
        seed = self._seed_blocks()
        l0 = int(safe) - seed
        if fb <= 0 or l0 <= fb + seed:
            return False
        self.cursor["_live"] = {"done": l0, "holes": [[fb, l0]], "why": why, "at": int(time.time()), "start": fb, "fb": fb}
        self.cursor.pop("_lscan", None)
        log.info("★BSC 차선 시작(%s): 라이브 = 블록 %d 부터(확정 헤드 %d) · 옛 기록 = %d → %d 옆 차선(남는 예산)★", why, l0 + 1, safe, fb, l0)
        return True

    def _lane_norm(self) -> bool:
        lv = self.cursor.get("_live")
        if not isinstance(lv, dict):
            if self.cursor.pop("_lscan", None) is not None:
                common.atomic_write_json(self.cursor_path, self.cursor)
            return False
        fb = int(self.cursor.get("from_block") or 0)
        try:
            L = int(lv.get("done"))
            holes = sorted([int(a), int(b)] for a, b in (lv.get("holes") or []))
            fb_mine = int(lv.get("fb", fb))
        except (TypeError, ValueError):
            L, holes, fb_mine = None, [], fb
        if L is None or fb <= 0 or fb < fb_mine or not self._lanes_on():
            log.info("BSC 차선 기록 버림(%s) — from_block %d 부터 한 차선", "차선 끔" if not self._lanes_on() else "커서 되감김·기록 이상", fb)
            self.cursor.pop("_live", None)
            self.cursor["_lanes_seen"] = int(time.time())
            self.cursor.pop("_lscan", None)
            common.atomic_write_json(self.cursor_path, self.cursor)
            return False
        out = []
        for a, b in holes:
            b = min(b, L)
            a = max(a, fb)
            if a < b:
                out.append([a, b])
        if not out or fb >= L:
            self._set_fb(max(fb, L))
            self.cursor.pop("_live", None)
            self.cursor["_lanes_seen"] = int(time.time())
            self.cursor.pop("_lscan", None)
            log.info("★BSC 옆 차선(옛 기록) 끝 — 한 차선으로 합침(from_block %d)★", int(self.cursor["from_block"]))
            common.atomic_write_json(self.cursor_path, self.cursor)
            return False
        if out[0][0] > fb:
            self._set_fb(out[0][0])
        if out != holes or lv.get("fb") != int(self.cursor["from_block"]):
            lv["holes"] = out
            lv["fb"] = int(self.cursor["from_block"])
            common.atomic_write_json(self.cursor_path, self.cursor)
        return True

    def _lane_scan(self, frm: int, to: int, ckey: str, head: int, budget: float, detail_deadline: float) -> tuple:
        sc = self.cursor.get(ckey)
        if isinstance(sc, dict) and int(sc.get("frm", -1)) == frm and int(sc.get("to", 0)) >= frm:
            found, last_done = set(sc.get("found") or []), int(sc["to"])
        else:
            res = self.discover(frm, to, budget_sec=budget)
            if res is None:
                return "none", frm - 1
            found, last_done = res
            if last_done < frm:
                return "none", frm - 1
            self.cursor[ckey] = {"frm": frm, "to": last_done, "found": sorted(h for h in found if h not in self.emitted)}
            common.atomic_write_json(self.cursor_path, self.cursor)
        qset = bf_engine.quarantine_map(self.cursor)
        todo = [h for h in found if h not in self.emitted and h not in qset]
        dets = self.fetch_details(todo, deadline=detail_deadline) if todo else {}
        bad9 = [h for h in todo if not isinstance(dets.get(h), dict)]
        if bad9:
            gone9 = set(bad9) - set(self._detail_fail_note(bad9, dets))
            todo = [h for h in todo if h not in gone9]
        self._detail_fail_clear([h for h in todo if isinstance(dets.get(h), dict)])

        def _blk(h):
            v = dets.get(h)
            return (v["tx"]["block_number"], h) if isinstance(v, dict) else (1 << 62, h)
        ok = True
        for h in sorted(todo, key=_blk):
            snap = dets.get(h)
            if not isinstance(snap, dict):
                log.warning("detail %s 실패 — %s 체크포인트로 다음 사이클 상세만 재시도: %s", h[:12], ckey, str(snap)[:120])
                ok = False
                break
            try:
                self.writer.append({"v": 1, "kind": "evm_tx", "chain": "bsc", "txhash": h, "snapshot": snap, "wallets": self.wallets,
                                    "observed_head": head, "ts": int(time.time())})
                self.emitted.add(h)
            except Exception as e:
                log.error("inbox append 실패 — 커서 미전진: %s", e)
                ok = False
                break
        common.write_json_if_changed(self.meta_path, self.token_meta)
        common.write_json_if_changed(self.emitted_path, sorted(self.emitted))
        if not ok:
            sc9 = self.cursor.get(ckey)
            if isinstance(sc9, dict):
                sc9["found"] = sorted(h for h in found if h not in self.emitted)
                common.atomic_write_json(self.cursor_path, self.cursor)
            return "detail", frm - 1
        self.cursor.pop(ckey, None)
        return ("done" if last_done >= to else "part"), last_done

    def _lanes_cycle(self, head: int, safe: int, tc0: float):
        lv = self.cursor["_live"]
        L = int(lv["done"])
        if (safe - L) * self._bsec() > LANE_SPLIT_SEC:
            nl = int(safe) - self._seed_blocks()
            if nl > L:
                lv["holes"] = list(lv.get("holes") or []) + [[L, nl]]
                lv["done"] = L = nl
                self.cursor.pop("_lscan", None)
                common.atomic_write_json(self.cursor_path, self.cursor)
                log.info("BSC 라이브 차선이 크게 뒤 — 블록 %d 부터 다시(그 앞 %d블록은 옆 차선)", nl + 1, nl - int(lv["holes"][-1][0]))
        live_st, live_err = "done", None
        if L < safe:
            t0 = time.time()
            try:
                live_st, last = self._lane_scan(L + 1, safe, "_lscan", head, self.cycle_budget, t0 + self.cycle_budget + 300)
            except Exception as e:
                live_st, last, live_err = "none", L, e
            if last > L:
                lv["done"] = L = int(last)
                common.atomic_write_json(self.cursor_path, self.cursor)
            if live_st in ("none", "detail") and live_err is None:
                live_err = RuntimeError("라이브 차선 " + ("상세 실패 — 체크포인트로 재시도" if live_st == "detail" else
                                                       "한 청크도 못 나감 — " + str((self.last_scan_metrics or {}).get("stop") or "노드 오류")))
        live_ok = live_st in ("done", "part")
        if live_ok:
            self.cursor["head"] = head
            common.atomic_write_json(self.cursor_path, self.cursor)
        try:
            self._xin_pass(head)
        except Exception as e:
            log.info("BSC 거래소 출금 txid 확인 실패(다음 기회): %s", common.safe_err(e)[:120])
        if live_st == "done" and L >= safe:
            try:
                hl9 = [int(b9) for _a9, b9 in (self.cursor["_live"].get("holes") or [])]
                if hl9:
                    self._nonce_pass(head, lo_blk=max(hl9))
            except Exception as e:
                log.info("BSC nonce 확인(라이브 범위) 실패(다음 기회): %s", common.safe_err(e)[:120])
            try:
                self._balw_pass(head, L)
            except Exception as e:
                log.info("BSC 잔고 감시 실패(다음 기회): %s", common.safe_err(e)[:120])
        live_metrics = dict(self.last_scan_metrics or {})
        bk_st, bk_err, bk_adv = None, None, 0
        if self._lane_norm():
            fb = int(self.cursor["from_block"])
            hole_end = int(self.cursor["_live"]["holes"][0][1])
            bud = self._side_budget(tc0)
            try:
                bk_st, last = self._lane_scan(fb + 1, hole_end, "_scan", head, bud, time.time() + bud + 60)
                if last > fb:
                    bk_adv = int(last) - fb
                    self._set_fb(last)
                    common.atomic_write_json(self.cursor_path, self.cursor)
            except Exception as e:
                bk_st, bk_err = "none", e
                log.warning("BSC 옆 차선 실패(다음 사이클 이어서): %s", common.redact_urls(common.safe_err(e))[:160])
            self._lane_norm()
        lv = self.cursor.get("_live") if isinstance(self.cursor.get("_live"), dict) else None
        lanes = None
        if lv:
            holes = lv.get("holes") or []
            start = int(lv.get("start") or self.cursor.get("_bf_start") or self.cursor.get("from_block") or 0)
            miss = sum(max(0, int(b) - int(a)) for a, b in holes) + max(0, safe - int(lv["done"]))
            total = max(1, safe - start)
            stop = (self.last_scan_metrics or {}).get("stop") if bk_st != "done" else None
            lanes = {"why": lv.get("why"), "back_from": int(self.cursor.get("from_block") or 0), "back_to": int(holes[-1][1]) if holes else None,
                     "holes": len(holes), "live": int(lv["done"]), "advanced": bk_adv,
                     "stalled": bool(bk_st in ("none", "detail") or bk_err is not None),
                     "err": (common.redact_urls(common.safe_err(bk_err))[:160] if bk_err is not None else
                             (str(stop)[:160] if stop and bk_st in ("none", "detail") else None))}
            note = None if not lanes["stalled"] else "옛 기록 차선 멈춤 — " + str(lanes["err"] or "노드 오류")[:120]
            self.progress.update("bsc", phase="scan", unit="blocks", done=max(0, total - miss), total=total, note=note,
                                 lag=max(0, safe - int(lv["done"])), scan=live_metrics or None, lanes=lanes)
        else:
            self._report(head, int(self.cursor.get("from_block") or 0), "live" if live_st == "done" else "scan")
        self._health(head, L, live_ok, None if live_ok else live_err, extra={"lanes": lanes})

    def cycle(self):
        tc0 = self._tc0 = time.time()
        if self.cursor.pop("_synced_at", None) is not None:
            common.atomic_write_json(self.cursor_path, self.cursor)
        self._seed_wallet_set()
        self._df_seen = set()
        self._detail_home()
        head = self.head()
        try:
            self._quarantine_retry(head)
        except Exception as e:
            log.info("BSC 격리 tx 재시도 실패(다음 사이클): %s", str(e)[:120])
        safe = head - self.conf_depth
        since = int(self.cursor.get("from_block", 0))
        if since == 0:
            cutoff = int(time.time()) - self.backfill_days * 86400
            lo = self.block_at_ts(cutoff, safe)
            since = max(1, lo)
            self.cursor["from_block"] = since
            self.cursor["_bf_start"] = since
            self.cursor["_cov"] = since
            self._lane_open(safe, "new")
            common.atomic_write_json(self.cursor_path, self.cursor)
            log.info("백필 시작: 블록 %d → %d (%d일, timestamp 탐색)",
                     since, safe, self.backfill_days)
        lanes9 = self._lane_norm()
        if not lanes9 and self._lanes_on() and (safe - int(self.cursor.get("from_block") or 0)) * self._bsec() > LANE_SPLIT_SEC:
            lanes9 = self._lane_open(safe, "lag")
            if lanes9:
                common.atomic_write_json(self.cursor_path, self.cursor)
        if lanes9:
            self._lanes_cycle(head, safe, tc0)
            return
        since = int(self.cursor.get("from_block", 0))
        if since >= safe:
            self._report(head, since, "live")
            self._health(head, since, True)
            self._extend(head)
            self._new_wallet_pass(head)
            self._nonce_pass(head)
            self._xin_pass(head)
            self._balw_safe(head, since)
            return
        safe0 = safe
        t_cycle = time.time()
        sc = self.cursor.get("_scan")
        if isinstance(sc, dict) and int(sc.get("frm", -1)) == since + 1 and int(sc.get("to", 0)) > since:
            found, last_done = set(sc.get("found") or []), int(sc["to"])
        else:
            def _adv(last, f):
                self._report(head, last, "scan")
            res = self.discover(since + 1, safe, budget_sec=self.cycle_budget, on_advance=_adv)
            if res is None:
                return
            found, last_done = res
            if last_done <= since:
                self._report(head, since, "scan", note="한 청크도 못 나감 — " + str(
                    (self.last_scan_metrics or {}).get("stop") or "노드 오류"), flush=True)
                return
            self.cursor["_scan"] = {"frm": since + 1, "to": last_done,
                                    "found": sorted(h for h in found if h not in self.emitted)}
            common.atomic_write_json(self.cursor_path, self.cursor)
        safe = last_done
        complete = last_done >= safe0
        ok = True
        qset = bf_engine.quarantine_map(self.cursor)
        todo = [h for h in found if h not in self.emitted and h not in qset]
        dets = self.fetch_details(todo, deadline=t_cycle + self.cycle_budget + 300) if todo else {}
        bad9 = [h for h in todo if not isinstance(dets.get(h), dict)]
        if bad9:
            gone9 = set(bad9) - set(self._detail_fail_note(bad9, dets))
            todo = [h for h in todo if h not in gone9]
        self._detail_fail_clear([h for h in todo if isinstance(dets.get(h), dict)])

        def _blk(h):
            v = dets.get(h)
            return (v["tx"]["block_number"], h) if isinstance(v, dict) else (1 << 62, h)
        n_ok = 0
        for h in sorted(todo, key=_blk):
            snap = dets.get(h)
            if isinstance(snap, Exception) or snap is None:
                log.warning("detail %s 실패 — 커서 유지(스캔 체크포인트로 다음 사이클 상세만 재시도): %s", h[:12], snap)
                ok = False
                break
            rec = {"v": 1, "kind": "evm_tx", "chain": "bsc", "txhash": h,
                   "snapshot": snap, "wallets": self.wallets,
                   "observed_head": head, "ts": int(time.time())}
            try:
                self.writer.append(rec)
                self.emitted.add(h)
                n_ok += 1
            except Exception as e:
                log.error("inbox append 실패 — 커서 미전진: %s", e)
                ok = False
                break
        common.write_json_if_changed(self.meta_path, self.token_meta)
        common.write_json_if_changed(self.emitted_path, sorted(self.emitted))
        if ok:
            self.cursor["from_block"] = safe
            self.cursor["head"] = head
            self.cursor.pop("_scan", None)
            if complete:
                self.cursor["_synced_at"] = int(time.time())
            else:
                self.cursor.pop("_synced_at", None)
                log.warning("부분 조회 %d→%d (확정 헤드 %d) — 커서 전진, 도장 보류", since, safe, safe0)
            common.atomic_write_json(self.cursor_path, self.cursor)
            if found:
                log.info("사이클 완료: %d tx (블록 %d→%d, %.0f초)", len(found), since, safe, time.time() - t_cycle)
            self._report(head, safe, "live" if complete else "scan")
            self._health(head, safe, True)
            if complete:
                self._extend(head)
                self._new_wallet_pass(head)
                self._nonce_pass(head)
                self._xin_pass(head)
                self._balw_safe(head, safe)
        else:
            sc9 = self.cursor.get("_scan")
            if isinstance(sc9, dict):
                sc9["found"] = sorted(h for h in found if h not in self.emitted)
                common.atomic_write_json(self.cursor_path, self.cursor)
            self._report(head, since, "detail", note=f"상세 남음 {len(sc9.get('found') or []) if isinstance(sc9, dict) else '?'}건")
            self._health(head, since, False, RuntimeError("상세 실패 — 스캔 체크포인트로 재시도"))


def main():
    common.ensure_dirs()
    cfg = common.load_config()
    bf_engine.configure(cfg)
    wallets = [w["address"] for w in cfg["wallets"] if w.get("type") == "bsc_rpc"]
    if not wallets:
        raise SystemExit("추적할 BSC 지갑이 없음 — config.wallets 확인")
    poll = int(cfg.get("bsc", {}).get("poll_sec", 60))
    writer = SegmentWriter(os.path.join(common.INBOX_DIR, "bsc"))
    w = BscWatcher(cfg, wallets, writer)
    log.info("가동: %d지갑, %d초 주기, 백필 %d일", len(wallets), poll, w.backfill_days)
    while True:
        t0 = time.time()
        try:
            w.cycle()
        except Exception as e:
            n9 = bf_engine.health("bsc").fail("bsc", e, "bsc_rpc")
            bf_engine.health("bsc").flush()
            lv = bf_engine.LogDebounce.level(n9)
            if lv:
                getattr(log, lv)("cycle 실패 %d회 연속(다음 주기 재시도): %s", n9, e)
        time.sleep(max(5.0, poll - (time.time() - t0)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("정지 신호(SIGINT) — 종료")
