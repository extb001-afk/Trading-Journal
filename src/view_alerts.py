from __future__ import annotations
import os
import threading
import common

ALERTS_PATH = os.path.join(common.STATE_DIR, "alerts_web.jsonl")


ALERTS_LOCK = threading.Lock()


def _append_alert(obj):
    with ALERTS_LOCK:
        common.append_durable_jsonl(ALERTS_PATH, obj)
