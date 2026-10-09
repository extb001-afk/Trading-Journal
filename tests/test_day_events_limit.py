#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import os

os.environ["TJ_HEALTH"] = "0"
import web


def ck(name, cond, extra=None):
    T.chk(bool(cond), name, extra)


DAYS = ["2026-01-01", "2026-01-02", "2026-01-03"]
PER = 2500
ix = {}
for di, d in enumerate(DAYS):
    rows = []
    for i in range(PER):
        rows.append((1767225600 + di * 86400 + i, "pos", {"k": "매수", "t": d[5:] + " 00:00", "sym": "SYN", "q": 1}, ("p1", "SYN", "eth")))
    rows.append((1767225600 + di * 86400 + PER, "hidden", {"k": "전송", "hideKind": "dust"}, None))
    ix[d] = rows
sb = web.StateBuilder.__new__(web.StateBuilder)
sb._day_idx = {"ix": ix, "rbd": {}, "fut": {}, "builtAt": "합성", "stab": {}, "krw": {}}
sb.snapshot = lambda *a, **k: None
sb.kick_refresh = lambda *a, **k: None
web.BUILDER = sb


class FakeH:
    _DAY_RE = web.Handler._DAY_RE
    _max_age = staticmethod(web.Handler._max_age)

    def __init__(self):
        self.sent = None

    def _send(self, code, body, *a, **k):
        self.sent = (code, body)


def call(q):
    h = FakeH()
    web.Handler._send_day_events(h, q)
    return h.sent


TOTAL = PER * len(DAYS)
dflt = getattr(web.StateBuilder, "DAY_EV_LIMIT_DEFAULT", None)
ck("(전제) 기본 limit = 5000(화면 피드 한 페이지와 같은 크기)", dflt == 5000, dflt)
c, b = call("")
ck("W10 조건 없음 = 최신순 기본 페이지(종전 = 전 기간 전부)", c == 200 and len(b.get("events") or []) == (dflt or 5000) and b.get("more") is True
   and b.get("n") == TOTAL and b.get("limit") == (dflt or 5000) and b.get("offset") == 0, (c, len(b.get("events") or []), b.get("n"), b.get("more")))
ck("W10 조건 없음 = 가장 최신부터", c == 200 and (b.get("events") or [{}])[0].get("iso") == DAYS[-1])
c, b = call("offset=5000")
ck("W10 조건 없음 + offset = 다음 페이지(나머지 · more 끝)", c == 200 and len(b.get("events") or []) == TOTAL - 5000 and b.get("more") is False,
   (c, len(b.get("events") or []), b.get("more")))
c, b = call("date=" + DAYS[1])
ck("W10 그날(date=) = 종전처럼 그날 전부(페이지 아님 — 화면 그날 목록·AI 리뷰)", c == 200 and len(b["events"]) == PER and "more" not in b and len(b["hidden"]) == 1,
   (c, len(b.get("events") or []), b.get("more")))
c, b = call("from=%s&to=%s" % (DAYS[0], DAYS[-1]))
ck("W10 기간(from·to) = 종전처럼 기간 전부(화면 좁은 기간·AI 리뷰 범위 조회)", c == 200 and len(b["events"]) == TOTAL and "more" not in b, (c, len(b.get("events") or [])))
c, b = call("from=%s" % DAYS[1])
ck("W10 from 만 = 조건 있음 → 종전처럼 전부", c == 200 and len(b["events"]) == PER * 2 and "more" not in b, (c, len(b.get("events") or [])))
c, b = call("limit=100&offset=0")
ck("W10 limit 직접(화면 넓은 기간 피드) = 그대로", c == 200 and len(b["events"]) == 100 and b.get("more") is True, (c, len(b.get("events") or [])))
c, b = call("date=2026-13-01")
ck("W10 형식 오류 = 400 그대로", c == 400, c)

T.finish()
