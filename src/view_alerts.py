from __future__ import annotations
import threading
import paths, statefile


ALERTS_LOCK = threading.Lock()


def _append_alert(obj):
    with ALERTS_LOCK:
        statefile.append_durable_jsonl(paths.state("alerts_web.jsonl"), obj)
