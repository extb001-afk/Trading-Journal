#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os

import common
import ex_foreign as X
import health

chk = T.chk


def decide(ex, a, b, now):
    f = getattr(X, "_snap_promote_ok", None)
    if f is not None:
        return f(ex, a, b, now)
    ok9, why9 = X._snap_agree(a, b)
    return ok9, why9


def snap(bal, fut=None):
    d = {"ts": 0, "balances": dict(bal)}
    if fut is not None:
        d["fut_part"] = dict(fut)
    return d


T0 = 1_800_000_000
usdt = 10000.0
prev = snap({"USDT": usdt, "BTC": 0.1})
prom, forced = 0, 0
for i in range(20):
    usdt *= 1.0003
    cur = snap({"USDT": usdt, "BTC": 0.1})
    ok, why = decide("bybit", prev, cur, T0 + 600 * (i + 1))
    prom += 1 if ok else 0
    forced += 1 if ok == "forced" else 0
    prev = cur
chk(prom >= 1 and forced >= 1, "S1 USDT 0.03%씩 20주기 → 일치 확인 없이 반영 1번 이상(종전 0 — 총자산이 굳음)", (prom, forced))
sm = common.read_json(os.path.join(common.STATE_DIR, "exf_snap_miss.json"), {}) if os.path.exists(os.path.join(common.STATE_DIR, "exf_snap_miss.json")) else {}
it = (sm.get("ex") or {}).get("bybit") or {}
chk(it.get("n") == 20 and it.get("forced") and "USDT" in str(it.get("why")), "S1 상태 파일 = 연속 20주기 · 마지막 강제 반영 시각 · 통화 USDT", sm)
hc = {c["cid"]: c for c in getattr(health, "collect_snap_miss", lambda now: [])(T0 + 600 * 20 + 60)}
c9 = hc.get("snapmiss:bybit") or {}
chk(c9.get("level") == "warn" and c9.get("title") == "잔고 표본 계속 다름: 바이빗 USDT" and c9.get("notify") is False and c9.get("unit") == "tj-exf",
    "S1 상태 패널 '잔고 표본 계속 다름: 바이빗 USDT'(주의 · 알림 없음)", c9)

fut = 2000.0
prev = snap({"USDT": 12000.0, "BNB": 1.0}, {"USDT": fut, "BNB": 0.5})
prom = 0
for i in range(6):
    fut -= 1.2
    cur = snap({"USDT": 10000.0 + fut, "BNB": 1.0}, {"USDT": fut, "BNB": 0.5})
    ok, why = decide("binance", prev, cur, T0 + 600 * (i + 1))
    prom += 1 if ok is True else 0
    prev = cur
chk(prom == 6, "S2 바이낸스 선물 지갑 몫만 움직임 = 매 주기 반영(선물 몫은 비교에서 뺌 — core 가 정산 시각에 기장)", prom)

a = snap({"USDT": 1200.0}, {"USDT": 200.0})
b = snap({"USDT": 1100.0}, {"USDT": 200.0})
c = snap({"USDT": 1100.0}, {"USDT": 200.0})
ok1, why1 = decide("binance", a, b, T0 + 9000)
ok2, why2 = decide("binance", b, c, T0 + 9600)
chk(ok1 is False and "USDT" in why1 and ok2 is True, "S3 소스 사이 이동이 한 표본에 두 번 잡힘(현물 쪽 차이) = 그 표본 반영 안 함 · 다음 일치 표본 반영", (ok1, why1, ok2))

p0 = snap({"USDT": 5000.0})
ok, why = decide("bybit", p0, snap({"USDT": 5000.0}), T0 + 20000)
sm = common.read_json(os.path.join(common.STATE_DIR, "exf_snap_miss.json"), {}) if os.path.exists(os.path.join(common.STATE_DIR, "exf_snap_miss.json")) else {}
hc = {c["cid"]: c for c in getattr(health, "collect_snap_miss", lambda now: [])(T0 + 20060)}
chk(ok is True and "bybit" not in (sm.get("ex") or {}) and (hc.get("snapmiss:bybit") or {}).get("level") == "ok", "S4 다시 일치 = 상태 항목 정상(닫힘)", (sm, hc.get("snapmiss:bybit")))
for i in range(3):
    decide("okx", snap({"USDT": 100.0 + i}), snap({"USDT": 101.0 + i}), T0 + 30000 + i)
st9 = getattr(X, "_SNAP_MISS_ST", None)
if isinstance(st9, dict):
    st9.clear()
res = [decide("okx", snap({"USDT": 200.0 + i}), snap({"USDT": 201.0 + i}), T0 + 31000 + i)[0] for i in range(3)]
chk(res == [False, False, "forced"], "S4 재시작해도 연속 횟수 이어짐(3 + 3 = 6번째에 반영)", res)

out = X._Bal()
X._sub_bal("binance", "futures", lambda o: X._add_to(o, "USDT", 123.0), out)
chk(getattr(out, "by_src", {}).get("futures") == {"USDT": 123.0}, "S5 잔고 수집 = 소스별 몫(선물 지갑) 기록", getattr(out, "by_src", None))
T.finish()
