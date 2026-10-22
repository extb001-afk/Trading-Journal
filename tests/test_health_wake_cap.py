#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import time  # noqa: E402

import health  # noqa: E402

H = health.settings({})
NOW = time.time()
PM2 = {u: {"status": "online", "restarts": 0, "pid": 1} for u in H["units"]}


def levels(gap, susp_prev, susp_cur, mins=(1, 14, 44, 89)):
    t0 = NOW - gap - 120
    st = {"last_eval": t0 + 60}
    if susp_prev is not None:
        st["susp"] = susp_prev
    health.note_wake(st, NOW, H, clock=lambda: susp_cur or None)
    src = [{"kind": "exchange", "key": "ex:bybit", "label": "바이빗", "unit": "tj-exf", "last_success": t0, "first_seen": t0 - 86400},
           {"kind": "chain", "key": "chain:eth", "label": "Ethereum", "unit": "tj-evm", "last_success": t0, "first_seen": t0 - 86400}]
    out = {}
    for m in mins:
        now = NOW + m * 60
        by = {c["id"]: c for c in health.evaluate({"now": now, "pm2": PM2, "sources": src, "sleeps": st.get("sleeps")}, H, ())}
        out[m] = (by["sync:ex:bybit"]["level"], by["sync:chain:eth"]["level"])
    return out, st


BAD = ("warn", "crit")
o, st = levels(10 * 3600, [29000000, 1000.0], [29000000, 1000.0])
T.chk(all(a in BAD and b in BAD for a, b in o.values()), "W1 감시만 10시간 꺼짐(안 잠) = 재기동 직후부터 멈춤 경보", o)
T.chk(sum(b - a for a, b in st["sleeps"]) <= health.WAKE_CAP_SEC + 1, "W1 잠 구간 = 상한 30분까지만", st["sleeps"])
o, st = levels(10 * 3600, None, False)
T.chk(all(a in BAD and b in BAD for a, b in o.values()), "W2 시계 못 잼(직전 기록 없음) = 상한까지만 → 멈춤 경보", o)

o, st = levels(22 * 60, [29000000, 1000.0], [29000000, 1000.0], mins=(1,))
T.chk(o[1] == ("ok", "ok"), "W3 배포 정지 22분 = 통째 뺌(초록 · 종전)", o)
o, st = levels(8 * 3600, [29000000, 1000.0], [29000000, 1000.0 + 8 * 3600 - 60], mins=(1,))
T.chk(o[1] == ("ok", "ok"), "W3 기기가 실제로 8시간 잠듦 = 통째 뺌(초록 · 종전)", o)
o, st = levels(8 * 3600, [29000000, 1000.0], [29000480, 0.0], mins=(1,))
T.chk(o[1] == ("ok", "ok"), "W3 재부팅(부팅 시각 바뀜) = 통째 뺌(초록 · 종전)", o)

st = {"last_eval": NOW - 7200, "susp": [29000000, 1000.0]}
health.note_wake(st, NOW, H, clock=lambda: [29000000, 1300.0])
age = health.awake_age(NOW, NOW - 1200, st.get("sleeps"))
T.chk(abs(age - 900) < 2, "W5 짧은 실제 잠(5분) = 5분만 뺌 · 틈 안에서 성공한 수집의 나이 그대로(15분)", (age, st.get("sleeps")))
c = health._suspend_clock()
T.chk(c is None or (isinstance(c, list) and len(c) == 2 and c[1] >= 0), "W4 _suspend_clock 꼴", c)
st = {"last_eval": NOW - 30}
health.note_wake(st, NOW, H)
T.chk(c is None or (isinstance(st.get("susp"), list) and len(st["susp"]) == 2), "W4 판정마다 시계 기록(st.susp)", st.get("susp"))
T.finish()
