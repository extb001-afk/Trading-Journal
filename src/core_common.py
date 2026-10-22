import json
import os
import time
import paths
import logging

log = logging.getLogger('tj-core')


class MissingTs(ValueError):
    pass


CLASSIFIER_VER = 5


DM_RECENT_SEC = 6 * 3600


PRICE_BATCH = 40


PRICE_IDLE_SEC = 20


PRICE_BACKOFF_MIN = 22


PRICE_BACKOFF_MAX = 86400


PRICE_BULK_BATCH = 400


PRICE_BULK_BUDGET = 12.0


PRICE_PREFETCH_CALLS = 40


KRW_FILL_SEC = 60


KRW_FILL_CALLS = 60


def dm(kind: str, text: str, payload=None, event_ts=None):
    if event_ts is not None and time.time() - event_ts > DM_RECENT_SEC:
        log.info("DM스킵(과거분)[%s] %s", kind, text)
        return
    fd = os.open(paths.state("pending_dm.jsonl"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        if os.fstat(fd).st_mode & 0o077:
            os.fchmod(fd, 0o600)
    except OSError:
        pass
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": int(time.time()), "kind": kind, "text": text,
                            "payload": payload}, ensure_ascii=False) + "\n")
    log.info("DM대기[%s] %s", kind, text)
