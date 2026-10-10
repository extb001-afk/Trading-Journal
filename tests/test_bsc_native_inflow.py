#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _bscchain as B

import json
import os
import sqlite3
import time

bw = B.bsc_watch
CH = B.CH
common = B.common
E18 = 10 ** 18
clk = [time.time()]
bw._now = lambda: clk[0]
REQ = os.path.join(common.STATE_DIR, getattr(bw, "DISC_REQ_NAME", "disc_open_request.json"))
BALW = os.path.join(common.STATE_DIR, "bsc_balw.json")


def tick(sec, blocks):
    clk[0] += sec
    CH.head += blocks


def setup_db():
    con = sqlite3.connect(common.DB_PATH)
    con.execute("CREATE TABLE IF NOT EXISTS raw_ex (exchange TEXT NOT NULL, kind TEXT NOT NULL, uuid TEXT NOT NULL, revision INTEGER NOT NULL,"
                " payload TEXT NOT NULL, observed_at INTEGER NOT NULL, PRIMARY KEY (exchange, kind, uuid, revision))")
    con.execute("CREATE TABLE IF NOT EXISTS raw_txs (chain TEXT, txhash TEXT, block INTEGER, snapshot TEXT)")
    con.commit()
    con.close()


def gates_reset():
    for g9 in list(getattr(B.bf_engine, "_GATES", {}).values()):
        g9.open_until = g9.pause_until = 0


def fresh(arch=True, n_old_send=True):
    CH.tx.clear()
    CH.mode, CH.old_below, CH.arch_fail = None, None, None
    CH.head = B.H0 + 300_000
    CH.bal0 = {B.W1: 10 * E18, B.W2: 10 * E18}
    CH.prune = 128
    if n_old_send:
        CH.native(CH.head - 5_000, B.W1, B.OTHER, 10 ** 15)
    B.reset_state()
    gates_reset()
    setup_db()
    common.atomic_write_json(B.CPATH, {"from_block": CH.head - 30, "head": CH.head - 10, "_cov": B.WIN_BLK, "_bf_start": B.WIN_BLK,
                                       "_wallets": sorted([B.W1, B.W2])})
    wr = B.Wr()
    w = B.mk(B.cfg(archive_rpcs=[B.ARCH]) if arch else B.cfg(), wr=wr)
    CH.arch_calls.clear()
    return w, wr


def run(w, n, sec=90, blocks=200):
    for _ in range(n):
        tick(sec, blocks)
        B.cycle(w)


def until(w, wr, h, n=8):
    for k in range(n):
        tick(90, 200)
        B.cycle(w)
        if h in B.emitted(wr):
            return k + 1
    return None


def recs(wr, h):
    return [r for r in wr.recs if r["txhash"] == h]


def reqs():
    d = common.read_json(REQ, {}) if os.path.exists(REQ) else {}
    return list(d.get("items") or []) if isinstance(d, dict) else []


def balw_st():
    return common.read_json(BALW, {}) if os.path.exists(BALW) else {}


def jobs_left():
    return sum(len((v or {}).get("jobs") or []) for v in (balw_st().get("w") or {}).values())


w, wr = fresh()
run(w, 3)
dep = CH.native(CH.head + 5, B.OTHER, B.W1, 5 * E18)
got = until(w, wr, dep)
T.chk(got is not None and got <= 4, "N1 로그 없는 직접 BNB 입금 = 몇 주기 안에 방출(이후 지출 없이)", {"cycle": got, "jobs": jobs_left()})
r1 = recs(wr, dep)
T.chk(len(r1) == 1 and r1[0].get("via") == "balw" and r1[0]["snapshot"]["tx"]["value"] == str(5 * E18) and r1[0]["snapshot"]["tx"]["to"] == B.W1,
      "N1 방출 모양 = 실제 거래 스냅샷(via balw · 받는 주소·수량 그대로)", [(r.get("via"), r["snapshot"]["tx"].get("value")) for r in r1])
ac = dict(CH.arch_calls)
T.chk(sum(ac.values()) <= 40 and not reqs() and jobs_left() == 0, "N1 아카이브 호출 = 입금 한 건 수십 콜 이하 · 기초 잔고 요청 없음 · 남은 작업 0",
      {"arch": ac, "req": len(reqs()), "jobs": jobs_left()})
run(w, 3)
T.chk(len(recs(wr, dep)) == 1, "N1 뒤 주기 — 같은 입금 다시 방출 0")

w, wr = fresh()
run(w, 3)
n0 = len(wr.recs)
mv = CH.native(CH.head + 5, B.W2, B.W1, 2 * E18)
got = until(w, wr, mv)
run(w, 3)
T.chk(got is not None and len(recs(wr, mv)) == 1 and recs(wr, mv)[0].get("via") == "nonce",
      "N2 내 다른 지갑 → 지갑 순수 BNB = 보낸 쪽 nonce 회수가 한 번 방출", [(r.get("via")) for r in recs(wr, mv)])
T.chk(not [r for r in wr.recs[n0:] if r.get("via") == "balw"] and not reqs() and jobs_left() == 0,
      "N2 받는 쪽 잔고 감시 = 설명됨(작업·잔고 감시 방출·기초 잔고 요청 0)", {"balw": [r["txhash"][-6:] for r in wr.recs[n0:] if r.get("via") == "balw"],
                                                                 "req": reqs(), "jobs": jobs_left()})

w, wr = fresh()
run(w, 3)
dep = CH.native(CH.head + 5, B.HOT, B.W1, 3 * E18)
spend = CH.native(CH.head + 60, B.W1, B.OTHER, 1 * E18)
run(w, 6)
T.chk(len(recs(wr, dep)) == 1 and recs(wr, dep)[0].get("via") == "balw" and len(recs(wr, spend)) == 1 and recs(wr, spend)[0].get("via") == "nonce",
      "N3 입금(잔고 감시)·지출(nonce) 둘 다 한 번씩", {"dep": [r.get("via") for r in recs(wr, dep)], "spend": [r.get("via") for r in recs(wr, spend)]})
w2 = B.mk(B.cfg(archive_rpcs=[B.ARCH]), wr=wr)
run(w2, 4)
dep2 = CH.native(CH.head + 5, B.OTHER, B.W1, 7 * 10 ** 17)
run(w2, 5)
T.chk(len(recs(wr, dep)) == 1 and len(recs(wr, spend)) == 1 and len(recs(wr, dep2)) == 1 and not reqs(),
      "N4 재시작 뒤 — 옛 입금·지출 다시 방출 0 · 새 입금은 한 번", {"dep": len(recs(wr, dep)), "spend": len(recs(wr, spend)), "dep2": len(recs(wr, dep2))})

w, wr = fresh()
run(w, 3)
pay = CH.internal(CH.head + 5, B.W1, B.ROUTER, B.W1, 2 * E18)
run(w, 6)
r5 = recs(wr, pay)
bd5 = [i for r in r5 for i in (r["snapshot"].get("internal") or []) if i.get("attr") == "balance_delta" and i.get("to") == B.W1]
T.chk(any(r.get("via") == "nonce" for r in r5) and any(r.get("via") == "balw" for r in r5) and len(bd5) == 1 and bd5[0]["value"] == str(2 * E18),
      "N5 내 tx 의 컨트랙트 internal 환급 = 그 tx 에 잔고 차이 귀속(attr=balance_delta · 2 BNB) 다시 방출",
      {"via": [r.get("via") for r in r5], "bd": bd5})
T.chk(not reqs() and jobs_left() == 0, "N5 기초 잔고 요청·남은 작업 0")

w, wr = fresh()
run(w, 3)
br = CH.internal(CH.head + 5, B.OTHER, B.ROUTER, B.W1, 3 * E18, mention=True)
run(w, 6)
r6 = recs(wr, br)
bd6 = [i for r in r6 for i in (r["snapshot"].get("internal") or []) if i.get("attr") == "balance_delta" and i.get("to") == B.W1]
T.chk(len(r6) == 1 and r6[0].get("via") == "balw" and len(bd6) == 1 and bd6[0]["value"] == str(3 * E18) and bd6[0]["from"] == B.ROUTER,
      "N6 남의 tx internal + 나를 언급한 로그 = 그 tx 에 귀속(보낸 쪽 = 컨트랙트) 한 번 방출", {"recs": [(r.get("via")) for r in r6], "bd": bd6})
T.chk(not reqs(), "N6 기초 잔고 요청 0")

w, wr = fresh()
run(w, 3)
nb = CH.head + 5
silent = CH.internal(nb, B.OTHER, B.ROUTER, B.W1, 4 * E18)
run(w, 6)
q7 = reqs()
T.chk(len(q7) == 1 and q7[0]["block"] == nb and q7[0]["chain_bal_raw"] == str(CH.balance(B.W1, nb)) and q7[0]["ca"] is None
      and q7[0]["spam"] is False and int(q7[0]["diff_raw"]) == 4 * E18 and q7[0]["block_ts"] == CH.ts(nb),
      "N7 단서 없는 internal = 그 블록 · 그 블록 잔고로 원가 미상 기초 잔고 요청(core discopen ③ 규약)", q7)
T.chk(silent not in B.emitted(wr) and jobs_left() == 0, "N7 가짜 거래 방출 없음 · 남은 작업 0")
run(w, 3)
T.chk(len(reqs()) == 1, "N7 같은 블록 요청 반복 0")

w, wr = fresh(arch=False)
run(w, 3)
s0 = (balw_st().get("w") or {}).get(B.W1, {}).get("cp", [0])[0]
dep = CH.native(s0 + 3, B.OTHER, B.W1, 6 * E18)
run(w, 4)
r8 = recs(wr, dep)
T.chk(len(r8) == 1 and r8[0].get("via") == "balw" and not reqs(),
      "N8 아카이브 없음 · 상태 보관 밖 직접 입금 = 공개 노드 블록 본문으로 찾아 실제 거래로 한 번(기초 잔고 요청 없음 — 대사 전 새 설치도 바로 보임)",
      {"recs": [r.get("via") for r in r8], "q": reqs(), "dep_blk": s0 + 3})
T.chk(jobs_left() == 0 and not CH.arch_calls, "N8 남은 작업 0 · 아카이브 호출 0")
run(w, 3)
s1 = (balw_st().get("w") or {}).get(B.W1, {}).get("cp", [0])[0]
nb8 = s1 + 3
sil8 = CH.internal(nb8, B.OTHER, B.ROUTER, B.W1, 2 * E18)
run(w, 4)
q8 = reqs()
T.chk(sil8 not in B.emitted(wr) and len(q8) == 1 and nb8 <= q8[0]["block"] and q8[0]["chain_bal_raw"] == str(CH.balance(B.W1, q8[0]["block"]))
      and int(q8[0]["diff_raw"]) == 2 * E18 and q8[0]["sources"] == ["bsc_balance_watch"],
      "N8b 아카이브 없음 · 단서 없는 internal = 훑은 구간 끝 블록 잔고로 기초 잔고 요청(새 입금 표식)", {"q": q8, "blk": nb8})
T.chk(jobs_left() == 0, "N8b 남은 작업 0")

w, wr = fresh()
run(w, 3)
CH.arch_fail = "429"
dep = CH.native(CH.head + 5, B.OTHER, B.W1, 5 * E18)
CH.native(CH.head + 6, B.OTHER, B.OTHER, 1)
run(w, 2)
tok = CH.transfer(CH.head + 5, B.USD, B.OTHER, B.W1, 123 * E18)
got9 = until(w, wr, tok, n=2)
T.chk(got9 == 1, "N9 아카이브 429 로 탐색이 쉬는 중에도 새 토큰 입금 = 다음 주기 방출(최신 먼저)", {"cycle": got9, "st": (balw_st().get("bo_until"), jobs_left())})
T.chk(dep not in B.emitted(wr) and float(balw_st().get("bo_until") or 0) > clk[0] - 1000, "N9 429 = 탐색 쉼(입금은 아직)")
CH.arch_fail = None
gates_reset()
got9b = None
for k in range(10):
    tick(400, 200)
    B.cycle(w)
    gates_reset()
    if dep in B.emitted(wr):
        got9b = k + 1
        break
T.chk(got9b is not None and len(recs(wr, dep)) == 1, "N9 쉼이 끝나면 입금 회수(한 번)", {"cycle": got9b})

w, wr = fresh()
run(w, 3)
ghost = CH.native(CH.head + 5, B.W1, B.OTHER, 5 * 10 ** 17)
tick(0, 30)
snap = w.fetch_details([ghost])[ghost]
wr.recs.append({"txhash": ghost, "snapshot": snap, "via": "old"})
w.emitted.add(ghost)
st10 = balw_st()
st10["at"] = int(clk[0] - 3 * 3600)
common.atomic_write_json(BALW, st10)
w._balw_st = None
w2 = B.mk(B.cfg(archive_rpcs=[B.ARCH]), wr=wr)
w2.emitted.add(ghost)
n10 = len(wr.recs)
run(w2, 5)
T.chk(not [r for r in wr.recs[n10:] if r.get("via") == "balw"] and not reqs() and jobs_left() == 0,
      "N10 되돌림 뒤(지난 확인 오래됨) = 체크포인트 다시 · 가짜 작업·방출·요청 0", {"new": [(r["txhash"][-6:], r.get("via")) for r in wr.recs[n10:]], "req": reqs()})

def raw_put(h):
    t = CH.tx[h]
    s = {"tx": {"hash": h, "from": t["from"], "to": t["to"], "value": str(t["value"]), "fee": {"value": "21000"}, "status": "ok", "block_number": t["blk"]},
         "token_transfers": [{"from": fr, "to": to, "token": {"address": tok}, "total": {"value": str(v)}} for tok, fr, to, v in t["logs"]],
         "internal": []}
    con = sqlite3.connect(common.DB_PATH)
    con.execute("INSERT INTO raw_txs (chain, txhash, block, snapshot) VALUES ('bsc', ?, ?, ?)", (h, t["blk"], json.dumps(s)))
    con.commit()
    con.close()


def mismatch(gap):
    common.atomic_write_json(os.path.join(common.STATE_DIR, "onchain_check.json"),
                             {"mismatches": [{"key": f"bsc:{B.W1}:native", "chain": "bsc", "wallet": B.W1, "ca": None, "sym": "BNB",
                                              "ledger": 1.0, "onchain": 1.0 + gap, "confirmed": True}]})


CH.tx.clear()
CH.head = B.H0 + 300_000
CH.bal0 = {B.W1: 10 * E18, B.W2: 10 * E18}
CH.prune, CH.arch_fail = 128, None
old_send = CH.native(CH.head - 900_000, B.W1, B.OTHER, 10 ** 16)
old_tok = CH.transfer(CH.head - 700_000, B.TK, B.OTHER, B.W1, 5 * E18)
old_dep = CH.native(CH.head - 400_000, B.OTHER, B.W1, 9 * E18)
B.reset_state()
gates_reset()
setup_db()
for h9 in (old_send, old_tok):
    raw_put(h9)
common.atomic_write_json(B.CPATH, {"from_block": CH.head - 30, "head": CH.head - 10, "_cov": B.WIN_BLK, "_bf_start": B.WIN_BLK,
                                   "_wallets": sorted([B.W1, B.W2])})
wr = B.Wr()
w = B.mk(B.cfg(archive_rpcs=[B.ARCH]), wr=wr)
run(w, 2)
mismatch(9.0)
got11 = until(w, wr, old_dep, n=6)
T.chk(got11 is not None and recs(wr, old_dep)[0].get("via") == "balw" and len(recs(wr, old_dep)) == 1,
      "N11 지난 누락(잔고 대조 확정 부족) → 30일 창 이분 탐색 → 놓친 직접 입금 방출(한 번)", {"cycle": got11, "jobs": jobs_left(), "req": reqs()})
T.chk(old_send not in B.emitted(wr) and old_tok not in B.emitted(wr) and not reqs(), "N11 원장에 있던 거래는 다시 안 냄 · 기초 잔고 요청 0")
run(w, 3)
T.chk(len(recs(wr, old_dep)) == 1 and jobs_left() == 0, "N11 하루 1번 — 같은 부족으로 다시 탐색·방출 0")

CH.tx.clear()
CH.head = B.H0 + 300_000
old_send = CH.native(CH.head - 900_000, B.W1, B.OTHER, 10 ** 16)
B.reset_state()
gates_reset()
setup_db()
raw_put(old_send)
common.atomic_write_json(B.CPATH, {"from_block": CH.head - 30, "head": CH.head - 10, "_cov": B.WIN_BLK, "_bf_start": B.WIN_BLK,
                                   "_wallets": sorted([B.W1, B.W2])})
wr = B.Wr()
w = B.mk(B.cfg(archive_rpcs=[B.ARCH]), wr=wr)
run(w, 2)
mismatch(2.5)
run(w, 3)
q12 = reqs()
a12 = q12[0]["block"] if q12 else None
T.chk(len(q12) == 1 and a12 is not None and a12 < CH.head - 5_000_000 and q12[0]["chain_bal_raw"] == str(CH.balance(B.W1, a12))
      and int(q12[0]["diff_raw"]) == int(2.5 * E18),
      "N12 창 안이 다 설명됨 = 창 시작 블록 잔고로 기초 잔고 요청(core 가 그 블록 잔고 − 원장으로 다시 잼)", q12)
T.chk(not [r for r in wr.recs if r.get("via") == "balw"], "N12 방출 0")

w, wr = fresh()
run(w, 3)
st14 = balw_st()
st14["bo_n"] = 3
common.atomic_write_json(BALW, st14)
w._balw_st = None
CH.arch_fail = "429"
d14a = CH.native(CH.head + 5, B.OTHER, B.W1, 1 * E18)
run(w, 1)
bo14 = float(balw_st().get("bo_until") or 0) - clk[0]
T.chk(bo14 > getattr(bw, "BALW_STALE", 1800), "N14 전제: 아카이브 쉼이 BALW_STALE 보다 김", bo14)
d14b = CH.native(CH.head + 5, B.OTHER, B.W1, 2 * E18)
for _ in range(25):
    tick(90, 200)
    B.cycle(w)
T.chk(float(balw_st().get("bo_until") or 0) > clk[0] and int(balw_st().get("bo_n") or 0) == 4, "N14 쉼 동안 쉼 연장·연속 실패 수 그대로(아카이브 안 부름)",
      (balw_st().get("bo_n"), balw_st().get("bo_until"), clk[0]))
CH.arch_fail = None
gates_reset()
for _ in range(6):
    tick(90, 200)
    B.cycle(w)
    gates_reset()
T.chk(len(recs(wr, d14a)) == 1 and len(recs(wr, d14b)) == 1,
      "N14 쉼 앞·쉼 동안 들어온 입금 둘 다 쉼이 끝난 뒤 회수(체크포인트를 지우지 않음 · 쉼 동안 창 평가는 계속)",
      {"a": len(recs(wr, d14a)), "b": len(recs(wr, d14b)), "jobs": jobs_left(), "req": reqs()})

w, wr = fresh()
run(w, 3)
cap0 = bw.BALW_TIME_CAP
bw.BALW_TIME_CAP = 1.0
CH.hang = {"url": B.DET, "method": "eth_getBalance", "sec": 6}
CH.kw_seen.clear()
tick(90, 200)
t15 = time.time()
B.cycle(w)
dt15 = time.time() - t15
seen15 = [k for k in CH.kw_seen if k[0] == B.DET and "eth_getBalance" in k[1]]
T.chk(dt15 < 3.5, "N15 공개 노드가 멈춰도 잔고 감시는 시간 상한(시험 1초) 안에서 끝남(종전 = 노드 대기 6초 × 묶음)", round(dt15, 2))
T.chk(seen15 and all(k[2] is not None and k[3] is not None for k in seen15), "N15 잔고 감시의 노드 호출 = 마감·세마포어 대기 상한을 받음", seen15[:3])
CH.hang = None
tok15 = CH.transfer(CH.head + 5, B.USD, B.OTHER, B.W1, 9 * E18)
got15 = until(w, wr, tok15, n=2)
pools15 = [getattr(w, k, None) for k in ("rpc", "nonce_pub_rpc", "arch_rpc")]
T.chk(got15 == 1 and all(p9 is None or "_dl" not in p9.__dict__ for p9 in pools15),
      "N15 다음 주기 최신 토큰 입금 방출 · 감시가 끝나면 노드 마감 풀림(최신 수집·nonce 회수는 종전)", {"cycle": got15})
bw.BALW_TIME_CAP = cap0
try:
    r16 = w._balw_raw_deltas(B.W1, 0, 10 ** 9, deadline=time.time() - 1)
    r16b = w._balw_raw_deltas(B.W1, 0, 10 ** 9, deadline=time.time() + 5)
except TypeError as e:
    r16 = r16b = repr(e)
T.chk(r16 is None and isinstance(r16b, dict), "N15b 원장 raw_txs 읽기도 마감(지남 = 안 읽고 다음 기회 · 남음 = 읽음)", (r16, type(r16b).__name__))

w, wr = fresh(arch=False)
run(w, 3)
s16 = (balw_st().get("w") or {}).get(B.W1, {}).get("cp", [0])[0]
many16 = [CH.native(s16 + 3, B.OTHER, B.W1, 10 ** 16) for _ in range(128)]
dust16 = [CH.native(s16 + 4, B.OTHER, B.W1, 10 ** 12) for _ in range(50)]
cs0, cap0 = bw.CALL_SLEEP, bw.BALW_TIME_CAP
bw.CALL_SLEEP, bw.BALW_TIME_CAP = 0.25, 1.0
dts16 = []
for _ in range(3):
    tick(90, 200)
    t16 = time.time()
    B.cycle(w)
    dts16.append(round(time.time() - t16, 2))
n16a = len([h for h in many16 if h in B.emitted(wr)])
T.chk(max(dts16) < 2.0 and 0 < n16a < 128, "N16 직접 입금 128건 — 한 주기 잔고 감시 ≤ 마감(시험 1초 + 여유) · 실행당 일부만(종전 = 128건 상세 한 번에 · 8건마다 0.25초)",
      {"dt": dts16, "emitted": n16a})
bw.CALL_SLEEP = 0
for _ in range(30):
    tick(90, 200)
    B.cycle(w)
    if not jobs_left():
        break
bw.CALL_SLEEP, bw.BALW_TIME_CAP = cs0, cap0
e16 = B.emitted(wr)
q16 = reqs()
ne16 = sum(1 for h in many16 if h in e16)
T.chk(all(e16.count(h) <= 1 for h in many16) and ne16 >= 40 and not any(h in e16 for h in dust16) and len(q16) == 1 and jobs_left() == 0
      and int(q16[0]["diff_raw"]) == (128 - ne16) * 10 ** 16 + 50 * 10 ** 12,
      "N16 여러 실행에 걸쳐 실제 거래로 방출(중복 0) · 작업 호출 상한(160)에 닿으면 남은 입금 + 먼지 합은 구간 끝 기초 잔고 요청 한 번(금액 합 정확) · 먼지는 상세 안 받음",
      {"emitted": ne16, "dust": sum(1 for h in dust16 if h in e16), "q": q16, "jobs": jobs_left()})

import balcheck
import db as dbm

DBP = os.path.join(T.TMP, "bc13.db")
os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
conn = dbm.open_db(DBP)
conn.execute("INSERT INTO asset_groups (name) VALUES ('BNB')")
gid = conn.execute("SELECT group_id FROM asset_groups WHERE name='BNB'").fetchone()[0]
conn.execute("INSERT INTO assets (kind, chain, address, symbol, decimals, group_id) VALUES ('native', 'bsc', NULL, 'BNB', 18, ?)", (gid,))
aid = conn.execute("SELECT asset_id FROM assets WHERE kind='native' AND chain='bsc'").fetchone()[0]
conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, leg_kind, event, classifier_ver)"
             " VALUES ('chain_tx', 'bsc', '0xsyn', 0, 1, ?, ?, ?, 'in', 'RECEIVE', 1)", (aid, f"wallet:bsc:{B.W2}", str(10 ** 17)))
conn.commit()
BAL13 = {B.W1: 3 * E18, B.W2: 10 ** 17}


def fake_rpc(url, method, params, timeout=15.0, gap=True):
    if method == "eth_getBalance":
        return hex(BAL13.get(str(params[0]).lower(), 0))
    if method == "eth_call":
        return "0x" + "0" * 64
    raise RuntimeError("시험 목 없음 " + method)


balcheck.recon._rpc = fake_rpc
balcheck.time.sleep = lambda s: None
cfg13 = {"wallets": [{"type": "bsc_rpc", "address": B.W1}, {"type": "bsc_rpc", "address": B.W2}], "bsc": {"detail_rpcs": [B.DET]},
         "native_symbol": {"bsc": "BNB"}, "backfill_months": 0, "balance_check": {"disc": False, "sol": False, "upbit": False, "pace_sec": 0}}
conn.row_factory = sqlite3.Row
s13 = balcheck.run_once(cfg13, conn, {gid: 600.0}, set(), {})
m13 = [m for m in s13.get("mismatches") or [] if m.get("wallet") == B.W1 and m.get("ca") is None]
T.chk(len(m13) == 1 and abs(m13[0]["onchain"] - 3.0) < 1e-9 and m13[0]["ledger"] == 0.0 and m13[0]["diffUsd"] == 1800.0,
      "N13 원장에 BNB 행 없는 지갑 = 같은 체인 네이티브 시세(다른 지갑 행)로 대조 → 불일치로 드러남(종전 = 건너뜀)", s13.get("mismatches"))
conn.execute("DELETE FROM postings")
conn.execute("DELETE FROM assets")
conn.commit()
s13b = balcheck.run_once(cfg13, conn, {gid: 600.0}, set(), {})
T.chk(any(m.get("wallet") == B.W1 and m.get("ca") is None for m in s13b.get("mismatches") or []),
      "N13 네이티브 자산 행이 아예 없어도 같은 이름 그룹(거래소 BNB 등) 시세로 대조", s13b.get("mismatches"))
conn.close()

bw._now = time.time
T.finish()
