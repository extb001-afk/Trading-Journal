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
import settings_store as ss


def check(n, c, d=""):
    T.chk(bool(c), n, None if c else str(d)[:900])


DAY = int(time.time() // 86400)
TODAY_S = time.strftime("%Y-%m-%d", time.gmtime(DAY * 86400))
SPEC = {"hosts": ["*.bfix.invalid"], "unit": "cu", "month": 3100, "pct": 80.0, "cu": 20, "cu_heavy": 20, "cu_methods": {}, "burst": 3.0}


def ldir(name):
    return os.path.join(common.quota_dir(), f"rpc_day_{name}")


def fresh_dir(name, files: dict = None):
    d = ldir(name)
    os.makedirs(d, exist_ok=True)
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))
    for f, body in (files or {}).items():
        with open(os.path.join(d, f), "w", encoding="utf-8") as fh:
            fh.write(body if isinstance(body, str) else json.dumps(body))
    return d


def conf(name, spec=SPEC):
    with B._RPC_DAY_LOCK:
        B._RPC_DAY.pop(name, None)
    B.rpc_day_configure({"rpc_day_limits": {name: dict(spec)}})
    return B._RPC_DAY[name]


fresh_dir("node_f1", {"reserve.lock": "", f"old.1.aa.json": {"day": DAY, "n": 0, "nh": 0, "proc": "old", "pid": 1, "inst": "aa", "at": 0, "closed": True}})
conf("node_f1")
L = B.rpc_day_limits("node_f1")
check("F1a 업그레이드 직후(지난날 기록 없음) = 지난 30일을 평소 몫으로 봄 → 버스트 없음(평소 80)",
      L.get("prev") == 30 * 80 and L.get("normal") == 80 and L.get("burst") == 80, L)
hf = os.path.join(ldir("node_f1"), "head_days.hist")
since = (json.load(open(hf)) if os.path.exists(hf) else {}).get("since")
check("F1b 첫 설정 때 '기록 시작 날(since)' = 오늘", since == DAY, since)
fresh_dir("node_f1b", {"head_days.hist": {"days": {str(DAY - 3): {"x.1.aa": [100, 100]}}, "since": DAY - 5}})
conf("node_f1b")
L = B.rpc_day_limits("node_f1b")
check("F1c 기록 시작(5일 전) 뒤 기록 없는 날 = 0 · 그 전 25일 = 평소 몫 · 기록된 날 = 그 값 → 100 + 25 × 80 = 2,100",
      L.get("prev") == 100 + 25 * 80, L)
sp = dict(SPEC, fresh_since=DAY)
fresh_dir("node_f1d", {"reserve.lock": ""})
conf("node_f1d", sp)
L = B.rpc_day_limits("node_f1d")
check("F1d fresh_since(오늘 새로 받은 키) = 그 전 기록 없는 날 0 → 바로 버스트 240", L.get("prev") == 0 and L.get("burst") == 240, L)

pl = NK.plans({"node_plans": {"ankr": {"plan": "free", "share": 10, "month": None, "fresh_since": TODAY_S},
                              "alchemy": {"plan": "free", "fresh_since": "2026-13-45"},
                              "nodereal": {"plan": "paid", "share": 25, "fresh_since": TODAY_S}}})
check("F1e plans: fresh_since 형식 검사(YYYY-MM-DD · 이상한 날짜 = 없음)", pl["ankr"].get("fresh_since") == TODAY_S and "fresh_since" not in pl["alchemy"], pl)
sa = NK.budget_spec("ankr", pl["ankr"])
sn = NK.budget_spec("nodereal", pl["nodereal"])
check("F1f budget_spec: 무료 = fresh_since(UTC 날 번호) · 유료 = 버스트·fresh 없음", sa.get("fresh_since") == DAY and "fresh_since" not in sn and "burst" not in sn, (sa, sn))
check("F1g plans 기본값엔 fresh_since 칸 없음(종전 모양 그대로)", NK.plans({})["ankr"] == {"plan": "free", "share": 10, "month": None}, NK.plans({})["ankr"])

import onboarding

r = onboarding._dispatch("keys/nodeplan", {"provider": "ankr", "plan": "free", "share": 10, "month": None, "fresh": True})
check("F1h '새로 받은 키' 켜기 = fresh_since 오늘", r.get("ok") and NK.plans()["ankr"].get("fresh_since") == TODAY_S and r["nodes"]["ankr"].get("freshSince") == TODAY_S, (r.get("ok"), NK.plans()["ankr"]))
r = onboarding._dispatch("keys/nodeplan", {"provider": "ankr", "plan": "paid", "share": 25, "month": None})
check("F1i 요금제를 바꿔도 fresh_since 유지", r.get("ok") and NK.plans()["ankr"].get("fresh_since") == TODAY_S, NK.plans()["ankr"])
r = onboarding._dispatch("keys/nodeplan", {"provider": "ankr", "plan": "free", "share": 10, "month": None, "fresh": False})
check("F1j 끄기 = fresh_since 지움", r.get("ok") and "fresh_since" not in NK.plans()["ankr"], NK.plans()["ankr"])
r = onboarding._dispatch("keys/nodeplan", {"provider": "ankr", "plan": "free", "share": 10, "month": None, "fresh": "yes"})
check("F1k fresh 값 이상 = 거부", r.get("ok") is False, r)

AL1, AL2 = "TESTal_first00000000000000001", "TESTal_second0000000000000002"
fresh_dir("node_alchemy")
r = onboarding._dispatch("keys/save", {"group": "alchemy", "values": {"TJ_ALCHEMY_KEY": AL1}})
check("F1l 첫 키 저장 = 자동 표시 없음(오늘 쓴 기존 키·옛 표시 승계 오인 방지)", r.get("ok") and "fresh_since" not in NK.plans()["alchemy"], NK.plans()["alchemy"])
onboarding._dispatch("keys/nodeplan", {"provider": "alchemy", "plan": "free", "share": 10, "month": None, "fresh": True})
r = onboarding._dispatch("keys/save", {"group": "alchemy", "values": {"TJ_ALCHEMY_KEY": AL1}})
check("F1m 같은 키 다시 저장 = 표시 유지", r.get("ok") and NK.plans()["alchemy"].get("fresh_since") == TODAY_S, NK.plans()["alchemy"])
r = onboarding._dispatch("keys/save", {"group": "alchemy", "values": {"TJ_ALCHEMY_KEY": AL2}})
check("F1n 다른 키로 바꿔 저장 = 표시 지움(새 키도 같은 계정 한도일 수 있음 — 다시 켜려면 칩)", r.get("ok") and "fresh_since" not in NK.plans()["alchemy"], NK.plans()["alchemy"])
onboarding._dispatch("keys/nodeplan", {"provider": "ankr", "plan": "free", "share": 10, "month": None, "fresh": True})
onboarding._dispatch("keys/save", {"group": "ankr", "values": {"TJ_ANKR_KEY": "TESTak_first0000000000001"}})
check("F1p Ankr: 키가 없던 서비스에 새 키 저장(빈 값 → 키) = 바뀐 것 → 표시 지움", "fresh_since" not in NK.plans()["ankr"], NK.plans()["ankr"])
check("F1q 자동 표시 기능 없음(nodekeys.auto_fresh_ok 삭제)", not hasattr(NK, "auto_fresh_ok"))
with open(os.path.join(T.ROOT, "web", "v2", "setup.js"), encoding="utf-8") as f:
    check("F1o 설정 화면 '새로 받은 키' 선택", "새로 받은 키" in f.read())

fresh_dir("node_f2", {"head_days.hist": {"days": {}, "since": DAY - 40}})
ent = conf("node_f2")
check("F2a 기록 비었음 = 버스트 240", B.rpc_day_limits("node_f2").get("burst") == 240)
common.atomic_write_json(os.path.join(ldir("node_f2"), "head_days.hist"), {"days": {str(DAY - 1): {"other.9.zz": [2000, 2000]}}, "since": DAY - 40})
check("F2b 다른 프로세스가 방금 합친 기록 = 바로 반영(캐시 없음) → 버스트 없음", B.rpc_day_limits("node_f2").get("burst") == 80, B.rpc_day_limits("node_f2"))
order = []
m2 = ent["meter"]
sync0 = m2._sync


def spy_sync(now):
    order.append("sync")
    return sync0(now)


prev0 = B._rpc_day_prev_used


def spy_prev(*a, **k):
    order.append("prev")
    return prev0(*a, **k)


m2._sync = spy_sync
B._rpc_day_prev_used = spy_prev
try:
    with B.ledger_burst():
        B.rpc_day_take("node_f2", "x.bfix.invalid", 20)
finally:
    m2._sync = sync0
    B._rpc_day_prev_used = prev0
check("F2c 상한 계산 = 예약 잠금 안 지난날 동기화(sync) 뒤", order[:2] == ["sync", "prev"], order)
fresh_dir("node_f2b", {"head_days.hist": {"days": {}, "since": DAY - 40},
                       "gone.1.aa.json": {"day": DAY - 1, "n": 2000, "nh": 2000, "proc": "gone", "pid": 1, "inst": "aa", "at": 0, "closed": True}})
conf("node_f2b")
r2 = []
with B.ledger_burst():
    for _i in range(5):
        try:
            B.rpc_day_take("node_f2b", "y.bfix.invalid", 20)
            r2.append("ok")
        except B.NetError as e:
            r2.append(e.kind)
hb = json.load(open(os.path.join(ldir("node_f2b"), "head_days.hist")))
check("F2d 안 합친 지난날 파일(2,000)을 합친 뒤에도 같은 판정 — 따라잡기여도 평소 80 까지", r2 == ["ok"] * 4 + ["quota"]
      and str(DAY - 1) in hb["days"] and not os.path.exists(os.path.join(ldir("node_f2b"), "gone.1.aa.json")), (r2, hb))
with B._GATES_LOCK:
    B._GATES.clear()

sc = B.LogScanner(["https://k3.bfix.invalid/x"], "0x" + "dd" * 32, ["0x" + "00" * 12 + "ab" * 20])
sc.ep_head = {}
with B._EP_HEADS_LOCK:
    B._EP_HEADS["https://k3.bfix.invalid/x"] = (1_000_000, time.time())
check("F3 이번 스캔엔 헤드를 안 물었어도 프로세스 캐시 헤드로 옛 구간 = 따라잡기", sc._burst_for(500_000) is True and sc._burst_for(999_900) is False,
      (sc._burst_for(500_000), sc._burst_for(999_900)))

sc3 = B.LogScanner(["https://k3b.bfix.invalid/x"], "0x" + "dd" * 32, ["0x" + "00" * 12 + "ab" * 20], span=5000,
                   caps={"https://k3b.bfix.invalid/x": 100})
sc3.ep_head = {"https://k3b.bfix.invalid/x": 1_000_000}
ch3 = [995_001, 1_000_000]
cb = getattr(sc3, "_chunk_burst", None)
check("F3b 대기 청크 끝(헤드)이 아니라 이 노드가 떼어 갈 앞부분 끝으로 따라잡기 판정",
      callable(cb) and cb("https://k3b.bfix.invalid/x", ch3) is True and sc3._burst_for(ch3[1]) is False
      and cb("https://k3b.bfix.invalid/x", [999_901, 1_000_000]) is False)

KEY, PUB = "https://key4.bfix.invalid/x", "https://pub4.bfix.invalid/x"
HEAD = 2_000_000
hits = {"key_norm": 0, "key_burst": 0, "pub": 0}
real_rc = B.rpc_call


def fake_rc(url, method, params, **kw):
    if method == "eth_blockNumber":
        return hex(HEAD)
    if url == KEY:
        if B.burst_on():
            hits["key_burst"] += 1
            return []
        hits["key_norm"] += 1
        e = B.NetError("quota: 평소 몫 다 씀(시험)", "quota", host="key4.bfix.invalid")
        e.local = True
        e.normal_only = True
        raise e
    hits["pub"] += 1
    time.sleep(0.15)
    return []


B.rpc_call = fake_rc
try:
    s4 = B.LogScanner([KEY, PUB], "0x" + "dd" * 32, ["0x" + "00" * 12 + "ab" * 20], span=10, positions={1: "0x" + "dd" * 32})
    f4, last4 = s4.scan(HEAD - 249, HEAD, deadline=time.time() + 60)
    check("F4a 헤드 근처(평소) 청크 25개: 키 노드는 평소 몫 거절 1번 뒤 빠지고 공개 노드가 전부 · 스캔 완료",
          hits["key_norm"] == 1 and last4 == HEAD and hits["pub"] >= 25, (hits, last4))
    check("F4b 게이트는 안 닫힘(같은 노드의 백필은 계속)", not B.gate(KEY).is_open())
    hits.update(key_norm=0, key_burst=0, pub=0)
    s5 = B.LogScanner([KEY], "0x" + "dd" * 32, ["0x" + "00" * 12 + "ab" * 20], span=1000, positions={1: "0x" + "dd" * 32})
    f5, last5 = s5.scan(100_000, 104_999, deadline=time.time() + 60)
    check("F4c 옛 구간(따라잡기) 청크 = 같은 노드로 계속", last5 == 104_999 and hits["key_burst"] == 5 and hits["key_norm"] == 0, (hits, last5))
finally:
    B.rpc_call = real_rc
with B._GATES_LOCK:
    B._GATES.clear()

fresh_dir("node_f5", {"head_days.hist": "{깨진 json"})
ent5 = conf("node_f5")
L5 = B.rpc_day_limits("node_f5")
check("F5a 날짜별 기록 손상 = 버스트 끔 · 평소 몫(보수)", L5.get("burst") == 80 and L5.get("normal") == 80, L5)
bad = [f for f in os.listdir(ldir("node_f5")) if f.startswith("head_days.hist.bad")]
check("F5b 손상 파일 보존(이름 바꿔 둠) · 새 기록 = 기록 시작 오늘", len(bad) == 1 and open(os.path.join(ldir("node_f5"), bad[0])).read() == "{깨진 json"
      and json.load(open(os.path.join(ldir("node_f5"), "head_days.hist"))).get("since") == DAY, (bad, os.listdir(ldir("node_f5"))))

T.finish()
