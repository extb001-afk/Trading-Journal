from __future__ import annotations

import time
from datetime import timedelta, timezone

__all__ = ["KST", "KST_OFFSET_S", "kst_day", "kst_hm", "kst_day0", "iso_epoch"]

KST_OFFSET_S = 9 * 3600
KST = timezone(timedelta(hours=9))


def kst_day(ts: float | int | str, back_days: int = 0) -> str:
    t = float(ts) + KST_OFFSET_S
    if back_days:
        t = t - back_days * 86400
    return time.strftime("%Y-%m-%d", time.gmtime(t))


def kst_hm(ts: float | int | str) -> str:
    return time.strftime("%H:%M", time.gmtime(float(ts) + KST_OFFSET_S))


def kst_day0(ts) -> int:
    from datetime import datetime as _dt
    d = _dt.fromtimestamp(int(float(ts)), KST)
    return int(d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())


def iso_epoch(s):
    if s is None or s == "":
        return None
    try:
        import datetime as _dt
        t = str(s).strip()
        if t.endswith(("Z", "z")):
            t = t[:-1] + "+00:00"
        d = _dt.datetime.fromisoformat(t)
        if d.tzinfo is None:
            d = d.replace(tzinfo=_dt.timezone.utc)
        return int(d.timestamp())
    except (ValueError, TypeError):
        return None
