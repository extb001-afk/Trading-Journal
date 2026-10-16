from __future__ import annotations
import json
import os
import time
import common
import calcguard

try:
    from review_prompt import LEN_KEYS as REVIEW_LEN_KEYS, len_key as review_len_key
except Exception:
    REVIEW_LEN_KEYS, review_len_key = (), None


try:
    import review_progress
except Exception:
    review_progress = None


REVIEW_PROGRESS_PATH = os.path.join(common.STATE_DIR, "review_progress.json")


REVIEW_FILL_REQ_PATH = os.path.join(common.STATE_DIR, "review_fill_request.json")


REVIEW_MANUAL_LOCK = os.path.join(common.STATE_DIR, "review_catchup_manual.lock")


def review_pause_eff(prefs) -> dict:
    v = (prefs or {}).get("review_pause")
    return {"on": bool(isinstance(v, dict) and v.get("on") is True), "at": (v or {}).get("at") if isinstance(v, dict) else None}


def review_fill_req_view():
    try:
        with open(REVIEW_FILL_REQ_PATH, "r", encoding="utf-8") as f9:
            d9 = json.load(f9)
    except (OSError, ValueError):
        return None
    return {"at": d9.get("at"), "since": d9.get("since")} if isinstance(d9, dict) else None


def review_manual_busy() -> bool:
    try:
        with open(REVIEW_MANUAL_LOCK, "r", encoding="utf-8") as f9:
            d9 = json.load(f9)
        pid9, ts9 = int(d9.get("pid") or 0), float(d9.get("ts") or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        return False
    return pid9 > 0 and time.time() - ts9 <= 12 * 3600 and review_progress is not None and review_progress.pid_alive(pid9)


def review_len_eff(prefs) -> dict:
    if not review_len_key:
        return {}
    rl = (prefs or {}).get("review_len")
    rl = rl if isinstance(rl, dict) else {}
    return {k: review_len_key(k, rl.get(k) if isinstance(rl.get(k), str) else None) for k in ("daily", "weekly")}


try:
    from review_prompt import PROMPT_VERSION as REVIEW_PV
except Exception:
    REVIEW_PV = None
try:
    from review_prompt import WEEKLY_PROMPT_VERSION as REVIEW_WPV
except Exception:
    REVIEW_WPV = REVIEW_PV
