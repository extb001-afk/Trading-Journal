"""Progress tracking for trade reviews."""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
import threading
import time
import common
from datetime import datetime, timedelta

DURATIONS_KEEP = 30
DEFAULT_ITEM_S = 90.0
FILL_ORDERS = ("recent", "oldest")
FILL_PARALLEL = (1, 3)
DEFAULT_FILL = {"order": "recent", "parallel": 1}
_TLOCK = threading.Lock()


def fill_eff(v) -> dict:
    v = v if isinstance(v, dict) else {}
    o = v.get("order") if v.get("order") in FILL_ORDERS else DEFAULT_FILL["order"]
    p = v.get("parallel")
    p = p if (isinstance(p, int) and not isinstance(p, bool) and p in FILL_PARALLEL) else DEFAULT_FILL["parallel"]
    return {"order": o, "parallel": p}


def order_keys(keys, order: str) -> list:
    return sorted(keys, reverse=(order == "recent"))


def eta_secs(remaining: int, parallel: int, avg_llm=None, pace_s: float = 20.0, done: int = 0, elapsed=None) -> float:
    if remaining <= 0:
        return 0.0
    if done >= 3 and elapsed and elapsed > 0:
        per = elapsed / done
    else:
        per = ((avg_llm if avg_llm and avg_llm > 0 else DEFAULT_ITEM_S) + max(0.0, pace_s)) / max(1, int(parallel or 1))
    return remaining * per


def avg_llm(d, n: int = 10):
    xs = [float(x.get("s") or 0) for x in (d or {}).get("durations") or [] if isinstance(x, dict) and x.get("s")][-n:]
    return round(sum(xs) / len(xs), 1) if xs else None


def read(path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path, d):
    dn = os.path.dirname(path)
    os.makedirs(dn, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dn, prefix=".tmp_rp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def update(path, fn):
    try:
        with _TLOCK, open(path + ".lock", "a") as lk:
            fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
            try:
                d = read(path)
                fn(d)
                d["v"] = 1
                d["updated_at"] = int(time.time())
                _write(path, d)
                return True
            finally:
                fcntl.flock(lk.fileno(), fcntl.LOCK_UN)
    except Exception:
        return False


def pid_alive(pid) -> bool:
    try:
        pid = int(pid or 0)
        if pid <= 0:
            return False
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (OSError, ValueError, TypeError):
        return False


class Run:

    def __init__(self, path, mode: str, queue: dict, order: str = "recent", parallel: int = 1, pace_s: float = 20.0, clock=time.time):
        self.path, self.mode, self.order, self.parallel, self.pace_s, self.clock = path, mode, order, max(1, int(parallel or 1)), pace_s, clock
        self.t0 = clock()
        self.id = f"{os.getpid()}-{mode}-{int(self.t0 * 1000)}"
        self.done = self.llm = self.tpl = self.regen = self.fail = 0
        self.q = {k: list(v) for k, v in (queue or {}).items() if v}
        self.cur = {}
        self.last_error = None
        self._lock = threading.Lock()
        self._put()

    def remaining(self) -> int:
        return sum(len(v) for v in self.q.values()) + len(self.cur)

    def _entry(self, d) -> dict:
        now = self.clock()
        eta = eta_secs(self.remaining(), self.parallel, avg_llm(d), self.pace_s, self.done, now - self.t0)
        return {"mode": self.mode, "pid": os.getpid(), "started_at": int(self.t0), "updated_at": int(now), "order": self.order,
                "parallel": self.parallel, "queue": {k: list(v) for k, v in self.q.items()},
                "current": sorted(self.cur.values(), key=lambda x: x["started_at"]), "done": self.done, "llm": self.llm, "tpl": self.tpl,
                "regen": self.regen, "fail": self.fail, "last_error": self.last_error, "eta_at": int(now + eta) if self.remaining() else None}

    def _put(self, extra=None):
        def fn(d):
            if extra:
                extra(d)
            d.setdefault("runs", {})[self.id] = self._entry(d)
        update(self.path, fn)

    def start(self, kind: str, key: str, label: str = ""):
        with self._lock:
            if key in self.q.get(kind, []):
                self.q[kind].remove(key)
            self.cur[(kind, key)] = {"kind": kind, "key": key, "label": label or key, "started_at": int(self.clock())}
            self._put()

    def end(self, kind: str, key: str, ok: bool, llm: bool = False, secs: float = 0.0, regen: bool = False, err=None, skipped: bool = False):
        with self._lock:
            self.cur.pop((kind, key), None)
            if skipped:
                pass
            elif ok:
                self.done += 1
                if llm:
                    self.llm += 1
                else:
                    self.tpl += 1
                if regen:
                    self.regen += 1
            else:
                self.fail += 1
                self.last_error = (common.safe_err(err) if err else f"{key} 생성 실패")[:200]

            def add(d):
                if ok and llm and secs > 0 and not skipped:
                    xs = [x for x in d.get("durations") or [] if isinstance(x, dict)]
                    xs.append({"k": kind, "s": round(float(secs), 1), "at": int(self.clock()), "regen": bool(regen)})
                    d["durations"] = xs[-DURATIONS_KEEP:]
            self._put(add)

    def drop_queue(self):
        with self._lock:
            self.q = {}

    def close(self, stopped=None):
        now = self.clock()

        def fn(d):
            (d.get("runs") or {}).pop(self.id, None)
            if self.done or self.fail:
                d["last"] = {"mode": self.mode, "started_at": int(self.t0), "ended_at": int(now), "done": self.done, "llm": self.llm,
                             "tpl": self.tpl, "regen": self.regen, "fail": self.fail, "secs": int(now - self.t0), "stopped": stopped,
                             "last_error": self.last_error, "parallel": self.parallel, "order": self.order}
        update(self.path, fn)


def week_segment(day_iso: str):
    d = datetime.strptime(day_iso, "%Y-%m-%d")
    mon = d - timedelta(days=d.weekday())
    sun = mon + timedelta(days=6)
    m1 = d.replace(day=1)
    mend = (m1 + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    lo, hi = max(mon, m1), min(sun, mend)
    iy, iw, _ = mon.isocalendar()
    wk = f"{iy}-W{iw:02d}"
    key = wk if (lo == mon and hi == sun) else wk + ("a" if lo == mon else "b")
    return key, lo.strftime("%Y-%m-%d"), hi.strftime("%Y-%m-%d")


def backlog(rdays, daily_rv: dict, weekly_rv: dict, today_iso: str, queued=None, catchup_days: int = 3, old_max: int = 5,
            weekly_auto_days: int = 35, weekly_max: int = 2) -> dict:
    queued = queued or {}
    qd, qw = set(queued.get("daily") or ()), set(queued.get("weekly") or ())
    lo = (datetime.strptime(today_iso, "%Y-%m-%d") - timedelta(days=catchup_days)).strftime("%Y-%m-%d")
    d_auto = d_man = 0
    old_data = 0
    for d in rdays:
        if d >= today_iso or d in qd:
            continue
        rv = daily_rv.get(d)
        pend = rv is None or bool(rv.get("stale"))
        if not pend:
            continue
        if d >= lo:
            d_auto += 1
        elif rv is not None and "리뷰 방식 변경" not in str(rv.get("staleWhy") or ""):
            old_data += 1
        else:
            d_man += 1
    d_recent = d_auto
    d_auto += old_data
    segs = {}
    for d in rdays:
        if d < today_iso:
            s = week_segment(d)
            if s[2] < today_iso:
                segs[s[0]] = s
    w_auto = w_man = 0
    wlo = (datetime.strptime(today_iso, "%Y-%m-%d") - timedelta(days=weekly_auto_days)).strftime("%Y-%m-%d")
    y = (datetime.strptime(today_iso, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    ls = week_segment(y)
    if ls[2] >= today_iso:
        ls = week_segment((datetime.strptime(ls[1], "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d"))
    latest = ls[0]
    for k, s in segs.items():
        if k in qw:
            continue
        rv = weekly_rv.get(k)
        pend = rv is None or bool(rv.get("stale"))
        if not pend:
            continue
        pv_changed = rv is not None and "리뷰 방식 변경" in str(rv.get("staleWhy") or "")
        if k == latest or (s[2] >= wlo and not pv_changed and not (rv is None and weekly_rv.get(k[:8]) and k[8:] in ("a", "b"))):
            w_auto += 1
        else:
            w_man += 1
    return {"daily": {"auto": d_auto, "manual": d_man, "recent": d_recent, "old": old_data, "oldMax": old_max},
            "weekly": {"auto": w_auto, "manual": w_man, "perRun": weekly_max}}


def view(path, daily_rv=None, weekly_rv=None, rdays=None, today_iso=None, fill=None, now=None) -> dict:
    d = read(path)
    now = now or time.time()
    runs = []
    qd, qw = set(), set()
    for rid, r in sorted((d.get("runs") or {}).items(), key=lambda kv: (kv[1] or {}).get("started_at") or 0):
        if not isinstance(r, dict) or not pid_alive(r.get("pid")):
            continue
        q = r.get("queue") or {}
        cur = [c for c in r.get("current") or [] if isinstance(c, dict)]
        qd |= set(q.get("daily") or ()) | {c["key"] for c in cur if c.get("kind") == "daily"}
        qw |= set(q.get("weekly") or ()) | {c["key"] for c in cur if c.get("kind") == "weekly"}
        runs.append({"mode": r.get("mode"), "startedAt": r.get("started_at"), "updatedAt": r.get("updated_at"),
                     "order": r.get("order"), "parallel": r.get("parallel") or 1,
                     "current": [{"kind": c.get("kind"), "key": c.get("key"), "label": c.get("label"), "startedAt": c.get("started_at")} for c in cur],
                     "q": {"daily": len(q.get("daily") or []), "weekly": len(q.get("weekly") or [])},
                     "done": r.get("done") or 0, "llm": r.get("llm") or 0, "tpl": r.get("tpl") or 0, "regen": r.get("regen") or 0,
                     "fail": r.get("fail") or 0, "lastError": r.get("last_error"), "etaAt": r.get("eta_at")})
    out = {"runs": runs, "avgSec": avg_llm(d), "nAvg": len([x for x in d.get("durations") or [] if isinstance(x, dict)][-10:]),
           "regenRate": None, "last": d.get("last") if isinstance(d.get("last"), dict) else None, "fill": fill_eff(fill)}
    xs = [x for x in d.get("durations") or [] if isinstance(x, dict)][-DURATIONS_KEEP:]
    if xs:
        out["regenRate"] = round(sum(1 for x in xs if x.get("regen")) / len(xs), 2)
    if rdays is not None and today_iso:
        out["backlog"] = backlog(rdays, daily_rv or {}, weekly_rv or {}, today_iso, {"daily": qd, "weekly": qw})
    return out
