import os
import threading
import time

import paths, statefile

BEAT_SEC = 30
_started = set()
_lock = threading.Lock()


def path(unit: str) -> str:
    return paths.state(f"runner_{unit}.json")


def beat_once(unit: str, now: float = None) -> None:
    try:
        statefile.atomic_write_json(path(unit), {"unit": unit, "pid": os.getpid(), "ts": int(time.time() if now is None else now),
                                              "state": "running", "why": "", "direct": True})
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
