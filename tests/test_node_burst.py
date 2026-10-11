#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import threading
import time

import common
import bf_engine as B
import nodekeys as NK


def check(n, c, d=""):
    T.chk(bool(c), n, None if c else str(d)[:900])


sf = NK.budget_spec("ankr", {"plan": "free", "share": 10, "month": None})
sp = NK.budget_spec("ankr", {"plan": "paid", "share": 25, "month": 100_000_000})
sq = NK.budget_spec("quicknode", NK.plans({})["quicknode"])
sa = NK.budget_spec("alchemy", NK.plans({})["alchemy"])
check("B1a 무료 = 버스트 배수 10(열흘치 · 상수 하나 — nodekeys.BURST_X)", getattr(NK, "BURST_X", None) == 10 and sf.get("burst") == 10 and sa.get("burst") == 10, (sf, sa))
check("B1b 유료 = 버스트 없음(남의 키 보호) · QuickNode 기본 = 무료 플랜이라 버스트(qn1011)", "burst" not in sp and sq.get("burst") == float(NK.BURST_X), (sp, sq))

SPEC = {"hosts": ["*.burst-test.invalid"], "unit": "cu", "month": 3100, "pct": 80.0, "cu": 20, "cu_heavy": 20, "cu_methods": {}, "burst": 10.0}
NAME = "node_bt"
HOST = "rpc.burst-test.invalid"
DAY = int(time.time() // 86400)
NOON = DAY * 86400 + 43200


def conf(spec=SPEC, name=NAME):
    B.rpc_day_configure({"rpc_day_limits": {name: dict(spec)}})
    return B._RPC_DAY[name]


def ldir(name=NAME):
    return os.path.join(common.quota_dir(), f"rpc_day_{name}")


def seed(days: dict, name=NAME, raw: dict = None):
    d = ldir(name)
    os.makedirs(d, exist_ok=True)
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))
    h = {str(DAY - k): {f"seed.{k}.aa": (list(v) if isinstance(v, tuple) else [v, v])} for k, v in days.items()}
    common.atomic_write_json(os.path.join(d, "head_days.hist"), {"days": h, "since": DAY - 40})
    for k, v in (raw or {}).items():
        common.atomic_write_json(os.path.join(d, f"old.{k}.bb.json"), {"day": DAY - k, "n": v, "nh": v, "proc": "old", "pid": 1, "inst": "bb", "at": 0, "closed": True})


def take(units, burst=False, host=HOST):
    try:
        if burst:
            with B.ledger_burst():
                B.rpc_day_take(NAME, host, units)
        else:
            B.rpc_day_take(NAME, host, units)
        return "ok"
    except B.NetError as e:
        return "quota_burst_only" if getattr(e, "burst_only", False) else e.kind


lim_f = getattr(B, "rpc_day_limits", None)
check("B0 bf_engine.rpc_day_limits · ledger_burst 있음", callable(lim_f) and callable(getattr(B, "ledger_burst", None)))
if not (callable(lim_f) and callable(getattr(B, "ledger_burst", None))):
    T.finish()

seed({})
conf()
L = lim_f(NAME, now=NOON)
check("B2a 기록 없음 = 평소 80 · 버스트 800(평소 × 10) · 상한 2,480", L.get("normal") == 80 and L.get("burst") == 800 and L.get("cap") == 2480 and L.get("prev") == 0, L)
r2 = [take(20, burst=True) for _ in range(41)]
check("B2b 따라잡기 호출 = 800 까지(20 × 40) · 41번째 = 백필 몫만 거절", r2 == ["ok"] * 40 + ["quota_burst_only"], r2)
check("B2c 백필 몫만 다 쓴 거절 = 게이트 안 닫음(실시간 몫 남음)", not B.gate(HOST).is_open())
r = [take(20) for _ in range(5)]
check("B2d 그 뒤 평소(실시간) 호출 = 80 까지(20 × 4 — 백필 800 에 안 막힘) · 5번째 거절", r == ["ok"] * 4 + ["quota"], r)
check("B2e 실시간·백필 몫 둘 다 없으면 게이트 닫힘(UTC 자정까지)", B.gate(HOST).is_open())
st = B.rpc_day_status().get(NAME) or {}
check("B2f 장부 = 880 · 화면 상태에 평소(전체 기준 880)·실시간 실측", st.get("used") == 880 and st.get("normal") == 880 and st.get("rt") is not None, st)
with B._GATES_LOCK:
    B._GATES.clear()

seed({k: 80 for k in range(1, 26)})
conf()
L = lim_f(NAME, now=NOON)
check("B3 옛 판 기록 = 실시간으로 봄(하루 몫 다 씀 · 보수) → 백필 = 오늘 남은 실시간 몫 뒤 40(정오) · 평소 80", L.get("prev") == 2000 and L.get("normal") == 80
      and L.get("burst") == 40 and L.get("rtm") == 80, L)
seed({1: (0, 1500), 2: (0, 500)})
conf()
L = lim_f(NAME, now=NOON)
check("B4 앞날 실시간 몫 남김: 28일 뒤 창에 2,000 이 남음 → 2,480 − 2,000 − 28 × 4 − 오늘 남은 2 = 366(× 10 보다 작게)", L.get("burst") == 366 and L.get("normal") == 80, L)
seed({1: (0, 2450)})
conf()
L = lim_f(NAME, now=NOON)
check("B5a 월 상한 거의 다 씀(2,450 — 앞으로 29일 창에 남음) = 평소 몫도 30 으로(연속 31일 합 ≤ 상한) · 백필 0(앞날 실시간 몫 먼저)",
      L.get("normal") == 30 and L.get("burst") == 0, L)
seed({1: (0, 2600)})
conf()
L = lim_f(NAME, now=NOON)
check("B5b 상한 넘음 = 0(오늘은 쉼)", L.get("normal") == 0 and L.get("burst") == 0, L)
check("B5c 상한 넘은 날의 평소 호출 = 거절 + 게이트 닫힘", take(20) == "quota" and B.gate(HOST).is_open())
with B._GATES_LOCK:
    B._GATES.clear()

seed({31: 999, 30: 7, 1: 5}, raw={2: 11, 0: 13})
d6 = ldir()
h6 = json.load(open(os.path.join(d6, "head_days.hist")))
h6["days"][str(DAY - 2)] = {"old.2.bb": [11, 11]}
common.atomic_write_json(os.path.join(d6, "head_days.hist"), h6)
conf()
L = lim_f(NAME)
check("B6 창 = 지난 30일(31일 전 999 · 오늘 파일 13 안 셈) · 안 합친 지난날 파일 셈 · 같은 생애 중복 없음 = 7 + 11 + 5 = 23", L.get("prev") == 23, L)

seed({})
NM7 = "node_bt7"
os.makedirs(ldir(NM7), exist_ok=True)
common.atomic_write_json(os.path.join(ldir(NM7), "head_days.hist"), {"days": {}, "since": DAY - 40})
B.rpc_day_configure({"rpc_day_limits": {NM7: dict(SPEC)}})
m7 = B._RPC_DAY[NM7]["meter"]
t0 = (DAY - 3) * 86400 + 100
check("B7a 장부 시험 준비(지난날 예약)", m7.take("t7", 40, kind="must", now=t0) and m7.take("t7", 15, kind="must", now=t0 + 10))
m7.take("t7", 5, kind="must", now=t0 + 86400)
hp = os.path.join(ldir(NM7), "head_days.hist")
hd = (json.load(open(hp)) if os.path.exists(hp) else {}).get("days", {})
check("B7b 지난날 합 55 가 날짜별 기록에", sum(v[1] for v in (hd.get(str(DAY - 3)) or {}).values()) == 55, hd)
B.rpc_day_configure({"rpc_day_limits": {NM7: dict(SPEC)}})
check("B7c 다시 읽어도 같은 판정(파일만 보고 셈)", lim_f(NM7, now=(DAY - 1) * 86400 + 50).get("prev") == 60, lim_f(NM7, now=(DAY - 1) * 86400 + 50))
m7.take("t7", 1, kind="must", now=(DAY + 40) * 86400)
hd = (json.load(open(hp)) if os.path.exists(hp) else {}).get("days", {})
check("B7d 31일 넘은 기록은 지움(보관 31일)", str(DAY - 3) not in hd and str(DAY - 2) not in hd, list(hd))

seed({})
PAID = dict(SPEC)
PAID.pop("burst")
conf(PAID)
L = lim_f(NAME)
check("B8a 유료(버스트 없음) = 평소 몫 그대로(창 판정 없음 — 종전)", L.get("normal") == 80 and L.get("burst") == 80, L)
r8 = [take(20, burst=True) for _ in range(5)]
check("B8b 유료 + 따라잡기 = 80 까지만", r8 == ["ok"] * 4 + ["quota"], r8)
with B._GATES_LOCK:
    B._GATES.clear()


class _Resp:
    status = 200
    headers = {}

    def __init__(self, b):
        self.b = b

    def read(self, n=-1):
        return self.b

    def getheader(self, k, d=None):
        return d

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


SENT = []


def _fake_open(req, timeout):
    SENT.append(req.full_url)
    return _Resp(b'{"jsonrpc": "2.0", "id": 1, "result": "0x1"}')


seed({})
B._rpc_cfg_ensure()
with B._RPC_DAY_LOCK:
    B._RPC_DAY.pop(NAME, None)
conf()
open_real = B._open
B._open = _fake_open
try:
    URL = f"https://{HOST}/v1/TESTkey0000000001"
    body = {"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": []}
    n9 = 0
    for _i in range(8):
        B.rpc_post(URL, body, burst=True)
        n9 += 1
    check("B9b rpc_post(burst=True) = 160 보냄(평소 몫 80 을 넘어)", n9 == 8 and len(SENT) == 8, (n9, len(SENT)))
    ok9 = 0
    for _i in range(4):
        B.rpc_post(URL, body)
        ok9 += 1
    e9 = None
    try:
        B.rpc_post(URL, body)
    except Exception as e:
        e9 = getattr(e, "net", e)
    check("B9a 그 뒤 평소 rpc_post = 실시간 80 까지(4콜 — 백필에 안 막힘) · 5번째 quota", ok9 == 4 and getattr(e9, "kind", "") == "quota" and len(SENT) == 12,
          (ok9, repr(e9)[:160]))
    seen = {}

    def other():
        seen["t"] = B.burst_on()
    with B.ledger_burst():
        th = threading.Thread(target=other)
        th.start()
        th.join()
        seen["main"] = B.burst_on()
    check("B9c ledger_burst = 그 스레드만(다른 스레드 · 끝난 뒤 = 평소)", seen == {"t": False, "main": True} and B.burst_on() is False, seen)
finally:
    B._open = open_real
with B._GATES_LOCK:
    B._GATES.clear()

calls = []
real_rc = B.rpc_call


def fake_rc(url, method, params, **kw):
    calls.append(B.burst_on())
    return []


B.rpc_call = fake_rc
try:
    sc = B.LogScanner(["https://k.burst-test.invalid/x"], "0x" + "dd" * 32, ["0x" + "00" * 12 + "ab" * 20])
    sc.ep_head = {"https://k.burst-test.invalid/x": 1_000_000}
    sc._query("https://k.burst-test.invalid/x", 100_000, 102_999, 1)
    sc._query("https://k.burst-test.invalid/x", 999_900, 1_000_000, 1)
    sc.ep_head = {}
    sc._query("https://k.burst-test.invalid/x", 100_000, 102_999, 1)
    sc2 = B.LogScanner(["https://k.burst-test.invalid/x"], "0x" + "dd" * 32, ["0x" + "00" * 12 + "ab" * 20], burst=False)
    sc2.ep_head = {"https://k.burst-test.invalid/x": 1_000_000}
    sc2._query("https://k.burst-test.invalid/x", 100_000, 102_999, 1)
    check("B10 LogScanner 옛 구간 = 버스트 · 헤드 근처 = 평소 · 헤드 모름 = 평소 · burst=False = 평소", calls == [True, False, False, False], calls)
finally:
    B.rpc_call = real_rc

d11 = os.path.join(common.quota_dir(), "rpc_day_node_alchemy")
os.makedirs(d11, exist_ok=True)
for f in os.listdir(d11):
    os.remove(os.path.join(d11, f))
per = NK.status(env={}, settings={})["alchemy"]["perDay"]
common.atomic_write_json(os.path.join(d11, "x.1.cc.json"), {"day": DAY, "n": per + 1, "nh": per + 1})
st11 = NK.status(env={}, settings={})["alchemy"]
check("B11a 오늘 쓴 양 > 평소 몫 = bursting", st11.get("bursting") is True and st11.get("usedToday") == per + 1, st11)
common.atomic_write_json(os.path.join(d11, "x.1.cc.json"), {"day": DAY, "n": 5, "nh": 5})
check("B11b 평소 = bursting 아님", NK.status(env={}, settings={})["alchemy"].get("bursting") is False)
with open(os.path.join(T.ROOT, "web", "v2", "setup.js"), encoding="utf-8") as f:
    check("B11c 설정 화면 '버스트 중' 표시", "버스트 중" in f.read())

T.finish()
