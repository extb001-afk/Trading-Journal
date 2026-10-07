import copy
import datetime
import hashlib
import json
import logging
import os
import threading
import time

import common

log = logging.getLogger("tj-tsfix")

POISON_FILE = "poison.jsonl"
DONE_FILE = "poison_replayed.json"
TSFIX_PERIOD = 600
TSFIX_MAX = 20
TSFIX_FAIL_BACKOFF = 3600
HOLD_MAX = 20
BTS_CACHE_MAX = 2000

_lock = threading.Lock()
_last_run = {}
_scan_cache = {}


def ts_valid(v) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return v > 0
    if isinstance(v, str):
        try:
            return datetime.datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp() > 0
        except ValueError:
            return False
    return False


def sol_ts_valid(v) -> bool:
    if isinstance(v, bool):
        return False
    try:
        return int(v or 0) > 0
    except (TypeError, ValueError):
        return False


def block_ts(wt, blk, fn=None) -> int:
    blk = int(blk)
    if blk <= 0:
        raise RuntimeError("블록 번호 없음")
    c = getattr(wt, "_tsfix_bts", None)
    if c is None:
        c = {}
        try:
            wt._tsfix_bts = c
        except AttributeError:
            pass
    if blk in c:
        return c[blk]
    v = int((fn or wt._block_ts)(blk))
    if v <= 0:
        raise RuntimeError(f"블록 {blk} 시각 0")
    if len(c) >= BTS_CACHE_MAX:
        c.clear()
    c[blk] = v
    return v


class TsHold:

    def __init__(self, limit: int = HOLD_MAX):
        self.limit = int(limit)
        self.n = {}

    def hold(self, h: str) -> bool:
        k = str(h or "").lower()
        self.n[k] = self.n.get(k, 0) + 1
        if len(self.n) > 5000:
            self.n = {k: self.n[k]}
        return self.n[k] <= self.limit

    def clear(self, h: str):
        self.n.pop(str(h or "").lower(), None)


def poison_id(entry: dict) -> str:
    return hashlib.sha256(json.dumps(entry.get("rec"), ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:16]


def rec_missing_ts(rec) -> bool:
    if not isinstance(rec, dict):
        return False
    if rec.get("kind") == "evm_tx":
        tx = ((rec.get("snapshot") or {}).get("tx") or {}) if isinstance(rec.get("snapshot"), dict) else {}
        return isinstance(tx, dict) and not ts_valid(tx.get("timestamp"))
    if rec.get("kind") == "sol_tx":
        return not rec.get("stake_open") and not sol_ts_valid(rec.get("ts"))
    return False


def rec_block(rec) -> int:
    try:
        if rec.get("kind") == "evm_tx":
            tx = (rec.get("snapshot") or {}).get("tx") or {}
            return int(tx.get("block_number") or tx.get("block") or rec.get("block") or 0)
        if rec.get("kind") == "sol_tx":
            return int(rec.get("slot") or 0)
    except (TypeError, ValueError, AttributeError):
        return 0
    return 0


def rec_chain(rec) -> str:
    return "sol" if rec.get("kind") == "sol_tx" else str(rec.get("chain") or "")


def _scan(state_dir: str = None):
    p = os.path.join(state_dir or common.STATE_DIR, POISON_FILE)
    try:
        st = os.stat(p)
    except FileNotFoundError:
        return [], 0
    key = (st.st_size, st.st_mtime_ns)
    with _lock:
        hit = _scan_cache.get(p)
        if hit and hit[0] == key:
            return hit[1], hit[2]
    out = []
    bad = 0
    try:
        with open(p, encoding="utf-8") as f:
            for ln in f:
                if not ln.strip():
                    continue
                try:
                    e = json.loads(ln)
                except ValueError:
                    bad += 1
                    continue
                if isinstance(e, dict):
                    out.append((poison_id(e), e))
                else:
                    bad += 1
    except FileNotFoundError:
        return [], 0
    with _lock:
        _scan_cache[p] = (key, out, bad)
    return out, bad


def scan(state_dir: str = None) -> list:
    return _scan(state_dir)[0]


def fix_path(chain: str) -> str:
    return os.path.join(common.STATE_DIR, f"poison_tsfix_{chain}.json")


def _rj(path: str, default):
    try:
        return common.read_json(path, default)
    except SystemExit as ex:
        raise RuntimeError(common.safe_err(str(ex))[:200]) from None


def _done_ok(state_dir: str = None) -> set:
    d = _rj(os.path.join(state_dir or common.STATE_DIR, DONE_FILE), {}) or {}
    return {k for k, v in d.items() if isinstance(v, dict) and v.get("ok")} if isinstance(d, dict) else set()


def repair(chain: str, lookup, writer, now: float = None, force: bool = False) -> int:
    now = time.time() if now is None else now
    try:
        if not os.path.exists(os.path.join(common.STATE_DIR, POISON_FILE)):
            return 0
        with _lock:
            if not force and now - _last_run.get(chain, 0) < TSFIX_PERIOD:
                return 0
            _last_run[chain] = now
        ents = [(pid, e) for pid, e in scan() if isinstance(e.get("rec"), dict) and rec_chain(e["rec"]) == chain
                and rec_missing_ts(e["rec"])]
        if not ents:
            return 0
        okset = _done_ok()
        fp = fix_path(chain)
        try:
            doc = _rj(fp, {}) or {}
        except RuntimeError as ex:
            log.warning("%s 시각 보강 진행 파일 손상 — 새로 시작: %s", chain, str(ex)[:120])
            doc = {}
        if not isinstance(doc, dict):
            doc = {}
        groups = {}
        for i9, (pid, e) in enumerate(ents):
            r9 = e["rec"]
            h9 = str(r9.get("txhash") or "")
            key9 = (r9.get("kind"), h9.lower() if r9.get("kind") == "evm_tx" else h9) if h9 else ("", pid)
            groups.setdefault(key9, {"i": i9, "items": []})["items"].append((pid, e))
        ready = []
        for key9, g in groups.items():
            pend = [(pid, e) for pid, e in g["items"]
                    if pid not in okset and not (isinstance(doc.get(pid), dict) and doc[pid].get("sent"))]
            if not pend:
                continue
            blk = next((b9 for b9 in (rec_block(e["rec"]) for _p, e in g["items"]) if b9 > 0), 0)
            th = str(pend[0][1]["rec"].get("txhash") or "").lower()
            if blk <= 0:
                for pid, _e in pend:
                    if not (isinstance(doc.get(pid), dict) and doc[pid].get("no_block")):
                        doc[pid] = {"no_block": True, "at": int(now), "txhash": th[:90]}
                continue
            hd = doc.get(pend[0][0]) if isinstance(doc.get(pend[0][0]), dict) else {}
            if hd.get("fail_at") and now - float(hd["fail_at"]) < TSFIX_FAIL_BACKOFF:
                continue
            ready.append((int(hd.get("n") or 0), g["i"], key9, pend, blk, th))
        ready.sort(key=lambda x: (x[0], x[1]))
        n = 0
        tries = 0
        stop = False
        for nfail, _i9, _k9, pend, blk, th in ready:
            if stop or tries >= TSFIX_MAX:
                break
            tries += 1
            try:
                ts = int(lookup(blk))
                if ts <= 0:
                    raise RuntimeError("블록 시각 0")
            except Exception as ex:
                for pid, _e in pend:
                    doc[pid] = {"fail_at": int(now), "err": common.safe_err(ex)[:160], "n": nfail + 1}
                log.warning("%s 격리된 시각 없는 tx %s — 블록 %s 시각 조회 실패(나중에 다시): %s", chain, th[:14], blk, str(ex)[:100])
                continue
            for pid, e in pend:
                rec2 = copy.deepcopy(e["rec"])
                if rec2.get("kind") == "evm_tx":
                    rec2["snapshot"]["tx"]["timestamp"] = ts
                else:
                    rec2["ts"] = ts
                rec2["ts_fix"] = {"poison_ids": [pid], "src": "block_ts", "block": blk, "at": int(now)}
                try:
                    writer.append(rec2)
                except Exception as ex:
                    log.error("%s 격리 tx %s 시각 보강 재방출 — inbox 쓰기 실패(다음 점검): %s", chain, th[:14], ex)
                    stop = True
                    break
                doc[pid] = {"sent": int(now), "ts": ts, "block": blk, "txhash": th[:90]}
                n += 1
            if not stop:
                log.warning("★%s 격리된 시각 없는 tx %s — 블록 %d 시각(%s)으로 보강해 다시 보냄(격리본 %d건)★", chain, th[:14], blk,
                            time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts)) + "Z", len(pend))
        live = {pid for pid, _e in ents}
        doc = {p9: v for p9, v in doc.items() if p9 in live}
        common.atomic_write_json(fp, doc)
        return n
    except (Exception, SystemExit) as ex:
        log.warning("%s 격리 시각 보강 점검 실패(다음 주기): %s", chain, common.safe_err(str(ex))[:160])
        return 0


def status(state_dir: str = None) -> dict:
    sd = state_dir or common.STATE_DIR
    if not os.path.exists(os.path.join(sd, POISON_FILE)):
        return None
    ents, bad = _scan(sd)
    okset = _done_ok(sd)
    fixdoc = {}
    try:
        for fn in os.listdir(sd):
            if fn.startswith("poison_tsfix_") and fn.endswith(".json"):
                try:
                    v = _rj(os.path.join(sd, fn), {}) or {}
                except RuntimeError:
                    v = {}
                if isinstance(v, dict):
                    fixdoc.update(v)
    except OSError:
        pass
    out = {"total": int(bad), "missing_ts": 0, "sent": 0, "no_block": 0, "corrupt": int(bad), "other": 0, "oldest": None}
    seen = set()
    for pid, e in ents:
        if pid in okset or pid in seen:
            continue
        seen.add(pid)
        out["total"] += 1
        try:
            t9 = int(e.get("ts") or 0)
        except (TypeError, ValueError):
            t9 = 0
        if t9 and (out["oldest"] is None or t9 < out["oldest"]):
            out["oldest"] = t9
        rec = e.get("rec")
        if not isinstance(rec, dict) or rec.get("kind") == "_corrupt" or e.get("err") == "_corrupt_inbox_line":
            out["corrupt"] += 1
        elif rec_missing_ts(rec):
            out["missing_ts"] += 1
            f9 = fixdoc.get(pid) if isinstance(fixdoc.get(pid), dict) else {}
            if f9.get("sent"):
                out["sent"] += 1
            elif f9.get("no_block") or rec_block(rec) <= 0:
                out["no_block"] += 1
        else:
            out["other"] += 1
    return out
