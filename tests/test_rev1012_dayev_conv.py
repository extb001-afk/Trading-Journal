#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import os
import random
import re

os.environ["TJ_HEALTH"] = "0"
import web

SB = web.StateBuilder
chk = T.chk


def mk(ix, stab, krw):
    sb = SB.__new__(SB)
    sb._day_idx = {"ix": ix, "rbd": {}, "fut": {}, "builtAt": 1, "stab": stab, "krw": krw}
    return sb


D = "2026-01-02"
ts0 = 1767312000
sb = mk({D: [(ts0 + i, "pos", {"k": "매수", "t": "01-02 00:00", "sym": "SYN", "q": 1}, ("p1", "SYN", "eth")) for i in range(3)]},
        {D: [(ts0 + 10, {"k": "매도", "_conv": "스테이블 교환", "t": "01-02 00:00", "d": "USDT→USDC", "a": "$1,000"}, ("s1", "USDT", "eth"))]},
        {D: [(ts0 + 20, {"t": "01-02 00:00", "sym": "KRW", "k": "전송", "d": "업비트 입금 ← 은행 (원화 입금)", "q": "5,000,000", "a": "₩5,000,000",
                         "tx": "—", "src": "ex:upbit"})]})
full = sb.day_events("2000-01-01", "2099-12-31")
page = sb.day_events("2000-01-01", "2099-12-31", limit=5000, offset=0)
chk(len(page.get("conv") or []) == 1 and len(page.get("krw") or []) == 1 and page["conv"] == full["conv"] and page["krw"] == full["krw"],
    "P1 페이지 응답에 conv 1 · krw 1(비페이지와 같음)", {k: len(page.get(k) or []) for k in ("conv", "krw")})

random.seed(1012)
bad = []
for trial in range(300):
    ix, stab, krw = {}, {}, {}
    base = 1767225600
    for di in range(random.randint(1, 6)):
        d = "2026-01-%02d" % (di + 1)

        def ts(di=di):
            return base + di * 86400 + random.randint(0, 40)
        ix[d] = [(ts(), "pos", {"k": "매수", "id": (di, i)}, ("p", "S", "eth")) for i in range(random.randint(0, 9))] + \
                [(ts(), "hidden", {"k": "전송", "id": ("h", di, i)}, None) for i in range(random.randint(0, 2))]
        stab[d] = [(ts(), {"k": "매도", "_conv": "스테이블 교환", "id": ("c", di, i)}, ("s", "USDT", "eth")) for i in range(random.randint(0, 3))]
        krw[d] = [(ts(), {"k": "전송", "id": ("k", di, i)}) for i in range(random.randint(0, 3))]
    sb = mk(ix, stab, krw)
    full = sb.day_events("2000-01-01", "2099-12-31")
    want_c = sorted(str(o["id"]) for o in full["conv"])
    want_k = sorted(str(o["id"]) for o in full["krw"])
    for lim in (1, 2, 3, 7, 100):
        off, ev, cv, kw, guard = 0, [], [], [], 0
        while guard < 200:
            guard += 1
            pg = sb.day_events("2000-01-01", "2099-12-31", limit=lim, offset=off)
            ev += pg["events"]
            cv += pg.get("conv") or []
            kw += pg.get("krw") or []
            off += len(pg["events"])
            if not pg["more"]:
                break
        if [e["id"] for e in ev] != [e["id"] for e in full["events"]]:
            bad.append(("events", trial, lim))
        if sorted(str(o["id"]) for o in cv) != want_c:
            bad.append(("conv", trial, lim))
        if sorted(str(o["id"]) for o in kw) != want_k:
            bad.append(("krw", trial, lim))
chk(not bad, "P2 무작위 300 × limit 5종: 페이지 합집합 = 비페이지 · 중복 0", bad[:8])

src = T.app_js()
m = re.search(r"async function fetchDayEvents\(q\) \{(.*?)\n  \}\n", src, re.S)
body = m.group(1) if m else ""
chk("arr(j.conv).concat(arr(j.krw))" in body and "arr(j.events).concat(cv)" in body, "P3 화면이 응답의 conv·krw 를 목록에 합침", bool(m))
chk("nextOffset: num(j.offset) + arr(j.events).length" in body, "P3 다음 offset = 기록(events) 수만(conv·krw 는 세지 않음)")

T.finish()
