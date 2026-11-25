import os
import threading
import time

import paths, statefile

# 읽는 쪽 판정 120초(runner_fp.runner_status)·180초(chk_base.RUNNER_STALE_SEC) 대비 여유 2배 — 30초에서 늘림(state/ 폴더 쓰기 줄이기)
BEAT_SEC = 60
_started = set()
_lock = threading.Lock()


def path(unit: str) -> str:
    return paths.state(f"runner_{unit}.json")


def beat_once(unit: str, now: float = None) -> None:
    try:
        statefile.atomic_write_json(path(unit), {"unit": unit, "pid": os.getpid(), "ts": int(time.time() if now is None else now),
                                              "state": "running", "why": "", "direct": True}, durable=False)
    except Exception:   # noqa: BLE001 [optional]
        pass


def start(unit: str, every: float = BEAT_SEC) -> None:
    with _lock:
        if unit in _started:
            return
        _started.add(unit)
    beat_once(unit)

    def _run():
        while True:
            time.sleep(every)
            beat_once(unit)
    threading.Thread(target=_run, name=f"tj-beat-{unit}", daemon=True).start()
