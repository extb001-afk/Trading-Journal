#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import time

import common
import bf_engine as B
import nodekeys as NK


def check(n, c, d=""):
    T.chk(bool(c), n, None if c else str(d)[:900])


DAY = int(time.time() // 86400)
NOON = DAY * 86400 + 43200
X = float(getattr(NK, "BURST_X", 3))
SPEC = {"hosts": ["*.flex-test.invalid"], "unit": "cu", "month": 38750, "pct": 80.0, "cu": 10, "cu_heavy": 10, "cu_methods": {}, "burst": X}
HOST = "rpc.flex-test.invalid"
N = 1000
CAP = 31000


def ldir(name):
    return os.path.join(common.quota_dir(), f"rpc_day_{name}")


def fresh(name, days: dict = None, since: int = None, files: dict = None, spec=None):
    d = ldir(name)
    os.makedirs(d, exist_ok=True)
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))
    if days is not None or since is not None:
        h = {str(DAY - k): {f"seed.{k}.aa": [int(v[0]), int(v[1])]} for k, v in (days or {}).items()}
        common.atomic_write_json(os.path.join(d, "head_days.hist"), {"days": h, "since": DAY - 40 if since is None else since})
    for f, body in (files or {}).items():
        common.atomic_write_json(os.path.join(d, f), body)
    with B._RPC_DAY_LOCK:
        B._RPC_DAY.pop(name, None)
    B.rpc_day_configure({"rpc_day_limits": {name: dict(spec or SPEC)}})
    with B._GATES_LOCK:
        B._GATES.clear()
    return B._RPC_DAY[name]


def take(name, units, burst=False):
    try:
        with B.ledger_burst(bool(burst)):
            B.rpc_day_take(name, HOST, units)
        return "ok"
    except B.NetError as e:
        return "quota_burst_only" if getattr(e, "burst_only", False) else e.kind


def ledger_sum(name):
    n = nh = 0
    for f in os.listdir(ldir(name)):
        if f.endswith(".json"):
            j = json.load(open(os.path.join(ldir(name), f)))
            if j.get("day") == DAY:
                n += int(j.get("n") or 0)
                nh += int(j.get("nh") or 0)
    return n, nh


fresh("node_x1", days={})
L = B.rpc_day_limits("node_x1", now=NOON)
check("X1 지난 기록 0 · 실시간 0 = 하루 백필 상한 = 평소 하루 몫 × 10(열흘치 · 종전 × 3)", X == 10 and L.get("burst") == 10 * N, (X, L))

fresh("node_x2", days={})
r = [take("node_x2", 100, burst=True) for _ in range(30)]
check("X2a 백필 3,000(하루 몫의 3배) 보냄", r == ["ok"] * 30, r)
r2 = [take("node_x2", 100) for _ in range(5)]
check("X2b 그 뒤 실시간(평소) 호출 = 계속 됨(종전 = 오늘 전체 ≥ 하루 몫이라 거절)", r2 == ["ok"] * 5, r2)
check("X2c 게이트 안 닫힘", not B.gate(HOST).is_open())
n2, nh2 = ledger_sum("node_x2")
check("X3 장부: 전체 3,500 · 실시간 칸(nh) = 실시간 500 만(백필은 안 셈 — 종전 = 3,500 전부)", n2 == 3500 and nh2 == 500, (n2, nh2))

fresh("node_x4a", days={k: (100, 100) for k in range(1, 8)})
La = B.rpc_day_limits("node_x4a", now=NOON)
fresh("node_x4b", days={k: (700, 700) for k in range(1, 8)})
Lb = B.rpc_day_limits("node_x4b", now=NOON)
check("X4a 실시간 100/일 = 열흘치 그대로(10,000)", La.get("burst") == 10 * N and La.get("rt") == 100, La)
check("X4b 실시간 700/일(× 1.5 = 하루 몫) = 백필 500 으로 물러남(앞으로 30일 실시간 몫을 남김)", Lb.get("burst") == 500 and Lb.get("rtm") == N, Lb)

fresh("node_x5", days={})
L0 = B.rpc_day_limits("node_x5", now=NOON)
common.atomic_write_json(os.path.join(ldir("node_x5"), "rt.1.cc.json"), {"day": DAY, "n": 300, "nh": 300, "proc": "rt", "pid": 1, "inst": "cc", "at": 0})
L1 = B.rpc_day_limits("node_x5", now=NOON)
check("X5 오늘 실시간 0 → 300(정오 · 하루 600 꼴) = 백필 상한 10,000 → 3,550(바로 물러남)", L0.get("burst") == 10 * N and L1.get("burst") == 3550, (L0, L1))

fresh("node_x6", days={k: (700, 700) for k in range(1, 8)})
got6 = []
for _i in range(400):
    v = take("node_x6", 10, burst=True)
    got6.append(v)
    if v != "ok":
        break
check("X6a 백필 상한에서 거절 = 백필 몫만(burst_only)", got6[-1] == "quota_burst_only", got6[-3:])
check("X6b 게이트 안 닫힘", not B.gate(HOST).is_open())
check("X6c 같은 노드 실시간 호출 = 계속", take("node_x6", 10) == "ok")

SPEC7 = dict(SPEC, fresh_since=DAY)
ent7 = fresh("node_x7", spec=SPEC7)
m7 = ent7["meter"]
lims7 = getattr(B, "_rpc_day_lims")


def take7(units, burst, t):
    def lim(now9):
        try:
            L9 = lims7(ent7, now9, live=True)
        except TypeError:
            L9 = lims7(ent7, now9)
        return L9["burst"] if burst else L9["normal"]
    return m7.take("sim", units, kind="fill" if burst else "must", now=t, limit=lim)


tot7, rt_ref7, bf7 = {}, 0, {}
for dd in range(70):
    base = (DAY + dd) * 86400
    for hh in range(24):
        t = base + hh * 3600 + 60
        if hh % 2 == 0:
            if take7(25, False, t):
                tot7[dd] = tot7.get(dd, 0) + 25
            else:
                rt_ref7 += 1
        for _k in range(40):
            if not take7(100, True, t + 1 + _k):
                break
            tot7[dd] = tot7.get(dd, 0) + 100
            bf7[dd] = bf7.get(dd, 0) + 100
roll = [sum(tot7.get(k, 0) for k in range(s9, s9 + 31)) for s9 in range(0, 70 - 30)]
check("X7a 어느 연속 31일 합도 월 상한(31,000) 이하", max(roll) <= CAP, (max(roll), roll[:5]))
check("X7b 실시간 거절 0(백필이 실시간을 굶기지 않음)", rt_ref7 == 0, rt_ref7)
print("X7 숫자: 날짜별 백필", [bf7.get(k, 0) for k in range(5)], "· 31일 합(첫 창)", roll[0], "· 최대 창", max(roll))
check("X7c 첫날 백필 ≤ 열흘치(10,000) · 첫 31일에 상한의 90% 넘게 씀(몰아 쓰기)", bf7.get(0, 0) <= 10 * N and roll[0] >= 0.9 * CAP, (bf7.get(0), roll[0]))

fresh("node_x8")
L8 = B.rpc_day_limits("node_x8", now=NOON)
check("X8 새 설치(칩 안 켬) = qn2: 기록 없는 지난날 = 0 → 첫날부터 버스트(하루 몫 < 백필 ≤ 열흘치) · 실시간 몫 = 하루 몫",
      N < L8.get("burst", 0) <= 10 * N and L8.get("normal") == N, L8)

PAID = dict(SPEC)
PAID.pop("burst")
fresh("node_x9", days={}, spec=PAID)
L9 = B.rpc_day_limits("node_x9", now=NOON)
check("X9 유료(버스트 없음) = 평소 몫 그대로", L9.get("normal") == N and L9.get("burst") == N, L9)

KEY, PUB = "https://key10.flex-test.invalid/x", "https://pub10.flex-test.invalid/x"
HEAD = 3_000_000
hits = {"key_old": 0, "key_new": 0, "pub": 0}
real_rc = B.rpc_call


def fake_rc(url, method, params, **kw):
    if method == "eth_blockNumber":
        return hex(HEAD)
    if url == KEY:
        if B.burst_on():
            hits["key_old"] += 1
            e = B.NetError("quota: 백필 몫 다 씀(시험)", "quota", host="key10.flex-test.invalid")
            e.local = True
            e.burst_only = True
            raise e
        hits["key_new"] += 1
        return []
    hits["pub"] += 1
    time.sleep(0.05)
    return []


B.rpc_call = fake_rc
try:
    s10 = B.LogScanner([KEY, PUB], "0x" + "dd" * 32, ["0x" + "00" * 12 + "ab" * 20], span=1000, positions={1: "0x" + "dd" * 32})
    s10.ep_head = {KEY: HEAD, PUB: HEAD}
    f10, last10 = s10.scan(1_000_000, 1_019_999, deadline=time.time() + 60)
    check("X10a 옛 구간: 키 노드는 백필 몫 거절 1번 뒤 빠지고 공개 노드가 전부 · 스캔 완료", hits["key_old"] == 1 and last10 == 1_019_999 and hits["pub"] >= 19,
          (hits, last10))
    check("X10b 게이트 안 닫힘", not B.gate(KEY).is_open())
    hits.update(key_old=0, key_new=0, pub=0)
    s11 = B.LogScanner([KEY, PUB], "0x" + "dd" * 32, ["0x" + "00" * 12 + "ab" * 20], span=10, positions={1: "0x" + "dd" * 32})
    s11.ep_head = {KEY: HEAD, PUB: HEAD}
    f11, last11 = s11.scan(HEAD - 99, HEAD, deadline=time.time() + 60)
    check("X10c 헤드 근처(실시간) 청크 = 그 키 노드도 계속 씀", last11 == HEAD and hits["key_new"] >= 1, (hits, last11))
finally:
    B.rpc_call = real_rc
with B._GATES_LOCK:
    B._GATES.clear()

r_hi = B.es_rooms(10000, 7500, 15000, NOON, budget=80000, fill_active=True)
check("X11a 옛 기록 채우는 중 · 실시간 실측 1.5만/일 = 실시간 몫 18,750(× 1.25 — 종전 8,000 고정이라 실시간이 굶음)", r_hi.get("rt") == 18750, r_hi)
r_lo = B.es_rooms(10000, 500, 1000, NOON, budget=80000, fill_active=True)
check("X11b 실시간 적음(1천/일) = 실시간 몫 2,400(하한 3%) · 오늘 남은 옛 기록 몫 = 80,000 − 10,000 − 1,200 − 1,600 = 67,200(종전 64,400)",
      r_lo.get("rt") == 2400 and r_lo.get("fill") == 67200, r_lo)
r_up = B.es_rooms(10000, 4000, 1000, NOON, budget=80000, fill_active=True)
check("X11c 오늘 실시간이 늘면(정오 4천 = 하루 8천) 실시간 몫 1만 · 옛 기록 몫이 바로 줄어듦", r_up.get("rt") == 10000 and r_up.get("fill") < r_lo.get("fill"),
      (r_up, r_lo))

D11 = (DAY + 3) * 86400
ref11 = got11 = fill11 = 0
for hh in range(24):
    t = D11 + hh * 3600 + 30
    for _i in range(625):
        if B.es_budget_take("x11", now=t + _i * 5, kind="head"):
            got11 += 1
        else:
            ref11 += 1
    for _k in range(6000):
        if not B.es_budget_take("x11", now=t + 3200, kind="fill"):
            break
        fill11 += 1
check("X11d 하루 모의: 실시간 1.5만 중 거절 ≤ 2%(종전 = 실시간 몫 10% 고정이라 1,907건 13% 거절) · 옛 기록 ≥ 5만 · 합계 ≤ 8만",
      ref11 <= 300 and fill11 >= 50000 and got11 + fill11 <= 80000, (got11, ref11, fill11))
print("X11d 숫자(실시간 받음·거절·옛 기록):", got11, ref11, fill11)

hfx = getattr(B, "helius_flex", None)
check("X12a helius_flex: 무료 = 월 상한 80만 · 배수 10 · 유료(월 500만) = 400만 · 배수 1 · 끔(helius_burst false) = 배수 1(창은 셈 — 코덱스 bu465)",
      callable(hfx) and hfx({}) == {"cap": 800000, "x": 10.0} and hfx({"sol": {"helius_monthly_credits": 5_000_000}}) == {"cap": 4000000, "x": 1.0}
      and hfx({"sol": {"helius_burst": False}}) == {"cap": 800000, "x": 1.0}, hfx({}) if callable(hfx) else None)
d12 = os.path.join(common.quota_dir(), "hl_flex_t")
os.makedirs(d12, exist_ok=True)
common.atomic_write_json(os.path.join(d12, "head_days.hist"), {"days": {}, "since": DAY - 40})
m12 = B.DayMeter("hl_flex_t", N, fill_first=True)
if hasattr(m12, "month_cap"):
    m12.month_cap, m12.flex_x, m12.hist_keep = CAP, X, 31
t12 = DAY * 86400 + 3600
n12 = 0
for _i in range(200):
    if not m12.take("sol", 50, kind="fill", now=t12 + _i):
        break
    n12 += 50
check("X12b 헬리우스 무료 = 옛 기록이 하루 예산(1,000)을 넘어 몰아 씀(월 창 · 열흘치 안)", N < n12 <= 10 * N, n12)
check("X12c 옛 기록을 몰아 쓴 뒤에도 실시간 몫 남음(head 판정 > 0)", m12.room("head", now=t12 + 300) > 0, m12.room("head", now=t12 + 300))
try:
    lr = B.ledger_rooms("hl_flex_t", N, 0.04, 0.02, t12 + 300, floor=0.1, flex={"cap": CAP, "x": X})
except TypeError as e:
    lr = {"err": str(e)}
check("X12d 화면 판정(ledger_rooms flex) = 수집기와 같은 하루 상한(평소 예산보다 큼)", lr.get("dayCap", 0) > N and lr.get("fillCap") == m12.eff_budget(t12 + 300)[1]
      if hasattr(m12, "eff_budget") else False, lr)

d14 = os.path.join(common.quota_dir(), "hl_rb_t")
os.makedirs(d14, exist_ok=True)
common.atomic_write_json(os.path.join(d14, "head_days.hist"), {"days": {str(DAY - 2): {"old.1.aa": [10, 10]}, str(DAY - 1): {"old.1.aa": [10, 10]}},
                                                               "since": DAY - 40, "k31": DAY - 10})
ok14 = B._esb_hist_merge_locked(d14, {DAY - 1: {"new.2.bb": [5, 5]}}, DAY, keep=31)
h14 = json.load(open(os.path.join(d14, "head_days.hist")))
p14 = B._rpc_day_prev_used(d14, DAY, N)
check("X14 롤백 판이 합친 날(k31 뒤 기록) → 기록 시작 날을 그 뒤로 · qn2: 기록 없는 날 = 0(롤백으로 지워졌을 수 있는 날도 — 드문 엣지 감수) → 25",
      ok14 and h14.get("since") == DAY and h14.get("k31") == DAY and p14 == 25, (h14, p14))
common.atomic_write_json(os.path.join(d14, "head_days.hist"), {"days": {str(DAY - 2): {"x.1.aa": [10, 10]}}, "since": DAY - 40, "k31": DAY - 1})
B._esb_hist_merge_locked(d14, {DAY - 1: {"x.1.aa": [5, 5]}}, DAY, keep=31)
h14b = json.load(open(os.path.join(d14, "head_days.hist")))
check("X14b 평소(31일 판만 합침) = 기록 시작 날 그대로", h14b.get("since") == DAY - 40 and h14b.get("k31") == DAY, h14b)

st = NK.status(env={}, settings={})["ankr"]
check("X13a 설정 상태: 배수 10 · 실시간 하루 실측(rtDay)·오늘 백필 상한(burstCap) 칸", st.get("burstX") == 10 and "rtDay" in st and "burstCap" in st, st)
with open(os.path.join(T.ROOT, "web", "v2", "setup.js"), encoding="utf-8") as f:
    js = f.read()
check("X13b 설정 화면 문구 = 열흘치 · 실시간 실측만 남김 · 오늘 백필 상한", "열흘치" in js and "실시간 실측" in js and "burstCap" in js)

T.finish()
