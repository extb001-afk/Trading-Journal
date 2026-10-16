from __future__ import annotations
import bisect
import re
import time
import common
import bf_engine

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


BALW_REQ_WAIT = 6 * 3600


BALW_JOB_DONE_MAX = 200


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


_NONCE_STOP_KINDS = ("http429", "quota", "circuit")


_NONCE_NEXT_KINDS = ("pruned", "null", "http5xx", "http4xx", "timeout", "conn", "dns", "payload")


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
