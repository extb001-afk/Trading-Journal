import json
import os
import threading
import time
import re
import urllib.request
import common
import bf_engine
import logging

log = logging.getLogger('tj-evm')

_HTTP5XX_RE = re.compile(r"HTTP(?: Error)? ?5\d\d\b")


class BsDetailCap(RuntimeError):
    pass


def _is_http_5xx(e) -> bool:
    cur, hops = e, 0
    while cur is not None and hops < 4:
        code = getattr(cur, "code", None)
        if isinstance(cur, urllib.error.HTTPError) and isinstance(code, int) and 500 <= code < 600:
            return True
        if _HTTP5XX_RE.search(str(cur) or ""):
            return True
        cur = cur.__cause__ or cur.__context__
        hops += 1
    return False


class _ScanLog:
    WIN = 600

    def __init__(self, base):
        self.base = base
        self.seen = {}

    def info(self, msg, *args, **kw):
        if isinstance(msg, str) and msg.endswith("— 재배치") and len(args) >= 5:
            err = str(args[4])
            kind = "429" if ("429" in err or "Too Many" in err) else err[:40]
            key = (str(args[0]), str(args[1]), kind)
            now = time.time()
            ent = self.seen.get(key)
            if ent and now - ent[0] < self.WIN:
                ent[1] += 1
                return
            n = ent[1] if ent else 0
            self.seen[key] = [now, 0]
            if n:
                msg = msg + " (지난 %d분 같은 줄 %d회 더)"
                args = tuple(args) + (max(1, int((now - ent[0]) / 60)), n)
        return self.base.info(msg, *args, **kw)

    def __getattr__(self, name):
        return getattr(self.base, name)


_SCAN_LOG = _ScanLog(log)


UA = "tj-bot/0.1 (personal trade journal)"


HTTP_TIMEOUT = 40


HTTP_RETRIES = 2


DISCOVERY_PAGES_MAX = 40


BACKFILL_PAGES_MAX = 400


def _dm(kind: str, text: str):
    try:
        fd = os.open(os.path.join(common.STATE_DIR, "pending_dm.jsonl"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": int(time.time()), "kind": kind, "text": text, "payload": None},
                               ensure_ascii=False) + "\n")
    except Exception as e:
        log.warning("DM 큐 기록 실패: %s", e)


_TRACE_END = object()


TRACE_DEPTH_MAX = 1024


TRACE_FAIL_NODES_MAX = 200_000


def trace_fail_index(res) -> dict:
    root = {}
    n = 0
    for t in res:
        if isinstance(t, dict) and t.get("error"):
            path = t.get("traceAddress") or []
            if len(path) > TRACE_DEPTH_MAX:
                raise ValueError("traceAddress 깊이 상한 초과")
            node = root
            for x in path:
                nxt = node.get(x)
                if nxt is None:
                    n += 1
                    if n > TRACE_FAIL_NODES_MAX:
                        raise ValueError("실패 경로 노드 상한 초과")
                    nxt = node[x] = {}
                node = nxt
            node[_TRACE_END] = True
    return root


def trace_path_failed(index: dict, ta) -> bool:
    node = index
    if _TRACE_END in node:
        return True
    for x in ta:
        node = node.get(x)
        if node is None:
            return False
        if _TRACE_END in node:
            return True
    return False


ES_DAILY_MARGIN = 300


ES_DAILY_FAR = 20 * 3600


ES_DAILY_PROBE = 3600


ES_DAILY_DM_GAP = 12 * 3600


_ES_DAILY = {"until": 0.0, "dm_at": 0.0}


_ES_DAILY_LOCK = threading.Lock()


def es_is_daily_limit(text) -> bool:
    low = str(text or "").lower()
    return "day/limit" in low or ("daily" in low and "limit" in low)


def es_daily_left(now: float = None) -> float:
    now = time.time() if now is None else now
    with _ES_DAILY_LOCK:
        return max(0.0, _ES_DAILY["until"] - now)


def es_daily_trip(text: str, now: float = None) -> float:
    now = time.time() if now is None else now
    nxt = (int(now) // 86400 + 1) * 86400 + ES_DAILY_MARGIN
    until = float(nxt) if nxt - now <= ES_DAILY_FAR else now + ES_DAILY_PROBE
    with _ES_DAILY_LOCK:
        if _ES_DAILY["until"] > now:
            return _ES_DAILY["until"]
        _ES_DAILY["until"] = until
        send_dm = now - _ES_DAILY.get("dm_at", 0.0) > ES_DAILY_DM_GAP
        if send_dm:
            _ES_DAILY["dm_at"] = now
    kst = time.strftime("%m-%d %H:%M", time.localtime(until))
    log.error("★이더스캔 하루 한도 소진 — %s 까지 이더스캔 0콜(해당 체인 blockscout 임시 폴백 · 블록스카웃이 막힌 체인은 RPC 전용), 그 뒤 자동 재시도★ (%s)",
              kst, str(text)[:100])
    if send_dm:
        _dm("ES_DAILY_LIMIT", f"이더스캔 무료 키 하루 한도 소진 — {kst} 까지 blockscout(막힌 체인은 공개 RPC)로 수집, 그 뒤 자동 복귀(재시작 불필요)")
    return until


def _revoke_stamp_disk(cursor_path: str, tok: bool = True):
    try:
        cur9 = common.read_json(cursor_path, {})
        a9 = cur9.pop("_synced_at", None) is not None
        b9 = tok and cur9.pop("_synced_tok_at", None) is not None
        if a9 or b9:
            common.atomic_write_json(cursor_path, cur9)
    except Exception as e:
        log.warning("도장 철회 실패(무시): %s", e)


def http_json(url: str, prio: str = "fg", deadline: float = None, retries: int = None, breaker_5xx: bool = True):
    return bf_engine.http_json(url, timeout=HTTP_TIMEOUT, retries=HTTP_RETRIES if retries is None else retries,
                               prio=prio, deadline=deadline, ua=UA, breaker_5xx=breaker_5xx)


def leaf_overflow_path(chain: str) -> str:
    return os.path.join(common.STATE_DIR, f"leaf_later_overflow_{chain}.jsonl")


def leaf_overflow_read(path: str) -> list:
    out, seen = [], set()
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                try:
                    e = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(e, dict) and isinstance(e.get("w"), str) and type(e.get("blk")) is int and e["blk"] > 0:
                    k9 = str(e.get("k") or f"{e['w'][:12]}:{e['blk']}")
                    if k9 not in seen:
                        seen.add(k9)
                        out.append(dict(e, k=k9))
    except OSError:
        pass
    return out


def rpc_handback(wt, target: str):
    cur = wt.cursor
    ts9 = time.strftime("%Y%m%d_%H%M%S")
    common.atomic_write_json(wt.cursor_path + f".rpc_handback_{ts9}", cur)
    jobs = {k[4:]: v for k, v in cur.items() if k.startswith("_bk:") and isinstance(v, dict)}
    new = {k: v for k, v in cur.items() if k.startswith("_cov:") or (not k.startswith("_") and isinstance(v, int)
                                                                    and not isinstance(v, bool))}
    rs, drop = [], []
    for w, j in jobs.items():
        try:
            d9, t9 = int(j.get("done") or 0), int(j.get("to") or 0)
        except (TypeError, ValueError):
            continue
        if d9 >= t9:
            continue
        if j.get("why") == "new" or (target == "etherscan" and j.get("why") == "internal"):
            new.pop(w, None)
            drop.append(w)
        elif j.get("why") == "extend":
            new["_cov:" + w] = t9
        else:
            rs.append({"wallet": w, "from_block": d9, "to_block": t9, "kind": "readd", "since": None, "job": None,
                       "npp": None, "done": False, "pages": 0})
    ll9 = {k: v for k, v in (cur.get("_leaf_later") or {}).items()
           if isinstance(v, dict) and isinstance(v.get("w"), str) and type(v.get("blk")) is int and v["blk"] > 0}
    ovp9 = leaf_overflow_path(wt.chain)
    for r9 in leaf_overflow_read(ovp9):
        ll9.setdefault(r9["k"], {"w": r9["w"], "blk": int(r9["blk"]), "at": int(r9.get("at") or 0), "n": 0, "next": 0})
    for e9 in ll9.values():
        w9, y9 = e9["w"].lower(), int(e9["blk"])
        if target == "etherscan":
            new.pop(w9, None)
            if w9 not in drop:
                drop.append(w9)
        else:
            rs.append({"wallet": w9, "from_block": y9 - 1, "to_block": y9, "kind": "leaf", "since": None, "job": None,
                       "npp": None, "done": False, "pages": 0})
    if ll9:
        new["_leaf_later_left"] = ll9
    if rs:
        new["_ext_internal_pending"] = {"v": 1, "ranges": rs, "hashes": [], "emit_i": 0, "created": int(time.time())}
    qd = cur.get("_quarantine") if isinstance(cur.get("_quarantine"), dict) else {}
    if qd and target == "etherscan":
        new["_quarantine_left"] = qd
    elif qd:
        pp = os.path.join(common.STATE_DIR, f"pending_detail_{wt.chain}.json")
        pend9 = common.read_json(pp, {}) or {}
        for h in qd:
            pend9.setdefault(str(h).lower(), 0)
        common.atomic_write_json(pp, pend9)
    hq = dict(cur["_hq"]) if isinstance(cur.get("_hq"), dict) else {}
    tl9 = cur.get("_trace_later") if isinstance(cur.get("_trace_later"), dict) else {}
    n_tl9 = 0
    keep9 = {}
    for h9, e9 in tl9.items():
        if isinstance(h9, str) and h9.startswith("0x") and isinstance(e9, dict):
            hq.setdefault(h9.lower(), 0)
            keep9[h9.lower()] = dict(e9)
            n_tl9 += 1
    try:
        with open(os.path.join(common.STATE_DIR, f"trace_later_overflow_{wt.chain}.jsonl"), encoding="utf-8") as f9:
            for ln9 in f9:
                try:
                    r9 = json.loads(ln9)
                except ValueError:
                    continue
                h9 = str((r9 or {}).get("h") or "").lower() if isinstance(r9, dict) else ""
                if h9.startswith("0x") and h9 not in keep9:
                    hq.setdefault(h9, 0)
                    keep9[h9] = {"at": int(r9.get("at") or 0), "n": int(r9.get("n") or 0), "next": 0, "blk": int(r9.get("blk") or 0), "sent": True}
                    n_tl9 += 1
    except (OSError, TypeError, ValueError):
        pass
    if keep9:
        tp9 = os.path.join(common.STATE_DIR, f"trace_later_left_{wt.chain}.json")
        old9 = common.read_json(tp9, {})
        old9 = old9 if isinstance(old9, dict) else {}
        old9.update(keep9)
        common.atomic_write_json(tp9, old9)
    if hq and target == "etherscan":
        hp = os.path.join(common.STATE_DIR, f"hq_left_{wt.chain}.json")
        old9 = common.read_json(hp, {}) or {}
        for h in hq:
            old9.setdefault(str(h).lower(), 0)
        common.atomic_write_json(hp, old9)
    elif hq:
        ep = os.path.join(common.STATE_DIR, f"enrich_{wt.chain}.json")
        enr = common.read_json(ep, {}) or {}
        for h in hq:
            enr.setdefault(str(h).lower(), 0)
        common.atomic_write_json(ep, enr)
    new["_handback"] = {"at": int(time.time()), "from": "rpc", "first_backfill": len(drop), "internal_ranges": len(rs), "enrich": len(hq),
                        "leaf_later": len(ll9), "trace_later": n_tl9,
                        "backup": os.path.basename(wt.cursor_path + f".rpc_handback_{ts9}")}
    wt.cursor = new
    common.atomic_write_json(wt.cursor_path, new)
    if os.path.exists(ovp9):
        try:
            os.remove(ovp9)
        except OSError:
            pass
    log.warning("★%s RPC 전용 → " + ("이더스캔" if target == "etherscan" else "블록스카웃") + " 되돌림: 지갑 커서 %d개 이어받음 · 첫 백필로 되돌린 지갑 %d · internal 재훑기 구간 %d · enrich %d건 (원본 .rpc_handback_%s)★",
                wt.chain, sum(1 for k in new if not k.startswith("_")), len(drop), len(rs), len(hq), ts9)


class EtherscanKeyError(RuntimeError):
    pass


class EtherscanPaced(RuntimeError):
    pass


class EtherscanDailyLimit(EtherscanKeyError):
    pass


_ES_Q = {}


_ES_Q_LOCK = threading.Lock()


ES_Q_TTL = 900


_ES_WMEM = {}


ES_FAIL_ISOLATE_SEC = 1800


class StateUnavailable(RuntimeError):
    pass


class HoldError(RuntimeError):
    pass


class BisectBudget(RuntimeError):
    pass


class TraceDeferred(bf_engine.NetError):

    def __init__(self, msg: str = "budget: trace 마감 — 시도 안 함(다음 차례)"):
        super().__init__(msg, "budget")


class TraceStaged(RuntimeError):

    def __init__(self):
        super().__init__("trace 단계 기록: callTracer·parity 모든 노드 실제 실패(지난 차례)")


class _TraceBudget:

    def __init__(self, w, dl):
        self.w, self.dl = w, dl

    def __enter__(self):
        self.old = self.w.__dict__.get("_tdl")
        dl = self.dl if self.old is None or self.dl is None else min(float(self.old), float(self.dl))
        self.w._tdl = self.old if dl is None else dl
        return self

    def __exit__(self, *a):
        if self.old is None:
            self.w.__dict__.pop("_tdl", None)
        else:
            self.w._tdl = self.old
        return False


_WALK_END = object()


def _int_or(v, dflt: int) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError, OverflowError):
        return dflt


class _RpcBudget:

    def __init__(self, w, dl):
        self.w, self.dl = w, dl

    def __enter__(self):
        self.old = self.w.__dict__.get("_rdl")
        dl = self.dl if self.old is None or self.dl is None else min(float(self.old), float(self.dl))
        self.w._rdl = self.old if dl is None else dl
        return self

    def __exit__(self, *a):
        if self.old is None:
            self.w.__dict__.pop("_rdl", None)
        else:
            self.w._rdl = self.old
        return False


class ChainDisabled(Exception):
    pass


RETENTION_CONFIRM_N = 3


RETENTION_CONFIRM_SEC = 1800


RETENTION_MIN_AGE_SEC = 2 * 86400


EXPLORER_FROZEN_SEC = 3 * 3600


EXPLORER_FROZEN_GAP = 2000


def retention_summary(cur: dict):
    g = [x for x in ((cur or {}).get("_retention_gaps") or []) if isinstance(x, dict)]
    if not g:
        return None
    a = min(g, key=lambda x: int(x.get("from") or 0))
    b = max(g, key=lambda x: int(x.get("to") or 0))
    return {"from": int(a.get("from") or 0), "to": int(b.get("to") or 0), "from_ts": a.get("from_ts"), "floor_ts": b.get("floor_ts"),
            "n": len(g)}


_TDLY = "https://gateway.tenderly.co/public/"
