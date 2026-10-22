from __future__ import annotations

import threading
import time

__all__ = ["FAIL_MAX", "FAIL_WINDOW", "LOCK_BASE", "LOCK_CAP", "LOCK_DECAY", "GLOBAL_FAILS", "GLOBAL_WINDOW", "RL_MAX_KEYS",
           "Limiter", "LIM", "HASH_SEM", "HASH_SEM_DEV", "mins"]

FAIL_MAX, FAIL_WINDOW = 5, 600
LOCK_BASE, LOCK_CAP = 900, 86400
LOCK_DECAY = 86400
GLOBAL_FAILS, GLOBAL_WINDOW = 50, 600
RL_MAX_KEYS = 10000

_now = time.time
HASH_SEM = threading.BoundedSemaphore(1)
HASH_SEM_DEV = threading.BoundedSemaphore(1)


class Limiter:
    def __init__(self):
        self.ip = {}
        self.glob = []
        self.lock = threading.Lock()
        self.gen = False

    def reset(self):
        with self.lock:
            self.ip.clear()
            self.glob = []

    def _st(self, b, now):
        st = self.ip.get(b)
        if st is None:
            st = self.ip[b] = {"f": [], "until": 0.0, "n": 0, "last": now}
        if st["n"] and now - st["last"] > LOCK_DECAY and st["until"] <= now:
            st["n"] = 0
        st["f"] = [t for t in st["f"] if now - t < FAIL_WINDOW]
        return st

    def wait(self, b, direct) -> int:
        now = _now()
        with self.lock:
            st = self.ip.get(b)
            if st and st["until"] > now:
                return max(1, int(st["until"] - now + 0.999))
            if not direct:
                self.glob = [t for t in self.glob if now - t < GLOBAL_WINDOW]
                if len(self.glob) >= GLOBAL_FAILS:
                    return max(1, int(self.glob[0] + GLOBAL_WINDOW - now + 0.999))
        return 0

    def fail(self, b: str, glob: bool = True) -> int:
        now = _now()
        with self.lock:
            st = self._st(b, now)
            st["f"].append(now)
            st["last"] = now
            if glob:
                self.glob.append(now)
            if len(self.glob) > GLOBAL_FAILS * 4:
                self.glob = [t for t in self.glob if now - t < GLOBAL_WINDOW]
            if len(st["f"]) >= FAIL_MAX:
                st["n"] += 1
                dur = min(LOCK_CAP, LOCK_BASE * (2 ** (st["n"] - 1)))
                st["until"] = now + dur
                st["f"] = []
                self._prune(now)
                return int(dur)
            self._prune(now)
            return 0

    def left(self, b) -> int:
        now = _now()
        with self.lock:
            st = self.ip.get(b)
            return FAIL_MAX - len([t for t in (st or {}).get("f", []) if now - t < FAIL_WINDOW])

    def ok(self, b):
        with self.lock:
            st = self.ip.get(b)
            if st:
                st["f"] = []
                st["n"] = 0

    def _prune(self, now):
        if len(self.ip) <= RL_MAX_KEYS:
            return
        for k in [k for k, v in self.ip.items() if v["until"] <= now and now - v["last"] > LOCK_DECAY]:
            self.ip.pop(k, None)
        if len(self.ip) > RL_MAX_KEYS:
            for k, _v in sorted(self.ip.items(), key=lambda kv: kv[1]["last"])[:len(self.ip) - int(RL_MAX_KEYS * 0.9)]:
                self.ip.pop(k, None)


LIM = Limiter()


def mins(sec: float) -> str:
    m = max(1, int((sec + 59) // 60))
    return f"{m // 60}시간 {m % 60}분" if m >= 120 else f"{m}분"
