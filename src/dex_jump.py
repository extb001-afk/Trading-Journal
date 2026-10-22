from __future__ import annotations

import math
import os

import statefile

JUMP_X = 5.0
CONFIRM_SEC = 3600
BASIS_SEC = 6 * 3600
SAVE_EVERY = 300


def _pair(v: object) -> bool:
    return (isinstance(v, (list, tuple)) and len(v) == 2
            and all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in v))


def ratio(a: float, b: float) -> float:
    return max(a, b) / min(a, b)


class Guard:

    def __init__(self, path: str):
        d = statefile.read_json(path, {}) if os.path.exists(path) else {}
        d = d if isinstance(d, dict) else {}
        self.path = path
        self.ok = {k: [float(v[0]), float(v[1])] for k, v in (d.get("ok") or {}).items() if _pair(v)}
        self.wait = {k: [float(v[0]), float(v[1])] for k, v in (d.get("wait") or {}).items() if _pair(v)}
        self.saved_at = 0.0

    def note(self, key: str, px: object, res: float | None, min_res: float, now: float) -> None:
        before = self.wait.get(key)
        if res is None or res < min_res:
            self.wait.pop(key, None)
        elif isinstance(px, (int, float)) and px > 0:
            ok = self.ok.get(key)
            wait = self.wait.get(key)
            if not ok or ok[0] <= 0 or now - ok[1] > BASIS_SEC or ratio(px, ok[0]) <= JUMP_X:
                self.ok[key] = [float(px), float(now)]
                self.wait.pop(key, None)
            elif not wait or ratio(px, wait[0]) > JUMP_X:
                self.wait[key] = [float(px), float(now)]
            elif now - wait[1] >= CONFIRM_SEC:
                self.ok[key] = [float(px), float(now)]
                self.wait.pop(key, None)
        if self.wait.get(key) != before or now - self.saved_at >= SAVE_EVERY:
            self.save(now)

    def held(self, key: str, px: object, px_ts: float) -> str | None:
        ok = self.ok.get(key)
        if not (isinstance(px, (int, float)) and px > 0 and ok and ok[0] > 0 and px_ts - ok[1] <= BASIS_SEC):
            return None
        x = ratio(px, ok[0])
        if x <= JUMP_X:
            return None
        return f"시세 급변 — 가격 ${px:,.6g} · 확인된 값 ${ok[0]:,.6g}({x:,.1f}배) · {CONFIRM_SEC // 60}분 이어지면 인정"

    def save(self, now: float) -> None:
        self.saved_at = now
        statefile.write_json_if_changed(self.path, {
            "ok": self.ok, "wait": {k: v for k, v in self.wait.items() if now - v[1] <= BASIS_SEC}})
