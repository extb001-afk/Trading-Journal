from __future__ import annotations
import threading
import sellchart

_OPS_RL = __import__("collections").deque()


_OPS_RL_LOCK = threading.Lock()


class MemoHourly(Exception):
    pass


_ALERT_TEST_LOCK = threading.Lock()


_ALERT_TEST_T = []


ALERT_TEST_HOURLY = 6


def _eval_budget_msg(cap, side, side_ko) -> str:
    fn = getattr(sellchart, "budget_msg", None)
    if callable(fn):
        try:
            return str(fn(cap, side))
        except Exception:
            pass
    return f"오늘 AI {side_ko} 평가 한도({cap}회)를 다 썼어요"
