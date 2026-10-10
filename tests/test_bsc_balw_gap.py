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
E17 = 10 ** 17
clk = [time.time()]
bw._now = lambda: clk[0]
REQ = os.path.join(common.STATE_DIR, getattr(bw, "DISC_REQ_NAME", "disc_open_request.json"))
BALW = os.path.join(common.STATE_DIR, "bsc_balw.json")
GAP_SEC, GAP_BLK = 2700, 6000


def tick(sec, blocks):
    clk[0] += sec
    CH.head += blocks


def setup_db():
    con = sqlite3.connect(common.DB_PATH)
    con.execute("CREATE TABLE IF NOT EXISTS raw_ex (exchange TEXT NOT NULL, kind TEXT NOT NULL, uuid TEXT NOT NULL, revision INTEGER NOT NULL,"
                " payload TEXT NOT NULL, observed_at INTEGER NOT NULL, PRIMARY KEY (exchange, kind, uuid, revision))")
    con.execute("CREATE TABLE IF NOT EXISTS raw_txs (chain TEXT, txhash TEXT, block INTEGER, snapshot TEXT, PRIMARY KEY (chain, txhash))")
    con.commit()
    con.close()


def gates_reset():
    for g9 in list(getattr(B.bf_engine, "_GATES", {}).values()):
        g9.open_until = g9.pause_until = 0


def fresh(arch=True, wallets=None, c=None):
    ws = wallets or [B.W1, B.W2]
    CH.tx.clear()
    CH.mode, CH.old_below, CH.arch_fail, CH.hang = None, None, None, None
    CH.head = B.H0 + 300_000
    CH.bal0 = {w9: 10 * E18 for w9 in ws}
    CH.prune = 128
    CH.native(CH.head - 5_000, B.W1, B.OTHER, 10 ** 15)
    B.reset_state()
    gates_reset()
    setup_db()
    common.atomic_write_json(B.CPATH, {"from_block": CH.head - 30, "head": CH.head - 10, "_cov": B.WIN_BLK, "_bf_start": B.WIN_BLK,
                                       "_wallets": sorted(ws)})
    wr = B.Wr()
    w = bw.BscWatcher(c or (B.cfg(archive_rpcs=[B.ARCH]) if arch else B.cfg()), list(ws), wr)
    CH.arch_calls.clear()
    return w, wr


def mk(wr, arch=True, wallets=None, c=None):
    return bw.BscWatcher(c or (B.cfg(archive_rpcs=[B.ARCH]) if arch else B.cfg()), list(wallets or [B.W1, B.W2]), wr)


def run(w, n, sec=90, blocks=200, gr=False):
    for _ in range(n):
        tick(sec, blocks)
        B.cycle(w)
        if gr:
            gates_reset()


def recs(wr, h):
    return [r for r in wr.recs if r["txhash"] == h]


def reqs():
    d = common.read_json(REQ, {}) if os.path.exists(REQ) else {}
    return list(d.get("items") or []) if isinstance(d, dict) else []


def balw_st():
    return common.read_json(BALW, {}) if os.path.exists(BALW) else {}


def wst(w9=None):
    return ((balw_st().get("w") or {}).get(w9 or B.W1)) or {}


def jobs_left():
    return sum(len((v or {}).get("jobs") or []) for v in (balw_st().get("w") or {}).values())


def bd_attr(wr):
    return [(r["txhash"][-6:], i.get("value")) for r in wr.recs for i in (r["snapshot"].get("internal") or []) if i.get("attr") == "balance_delta"]


def ingest(wr):
    con = sqlite3.connect(common.DB_PATH)
    for r in wr.recs:
        sn = r.get("snapshot") or {}
        b9 = (sn.get("tx") or {}).get("block_number")
        con.execute("INSERT OR REPLACE INTO raw_txs (chain, txhash, block, snapshot) VALUES ('bsc', ?, ?, ?)", (r["txhash"].lower(), b9, json.dumps(sn)))
    con.commit()
    con.close()


def chk_one(wr, h, blk, val, tag):
    r = recs(wr, h)
    tx = r[0]["snapshot"]["tx"] if r else {}
    T.chk(len(r) == 1 and r[0].get("via") == "balw" and tx.get("block_number") == blk and tx.get("timestamp") == CH.ts(blk)
          and tx.get("value") == str(val) and str(tx.get("to")).lower() == B.W1,
          f"{tag} 공백 안 직접 입금 = 원래 블록·시각의 실제 거래 정확히 1건(via balw)",
          {"n": len(r), "via": [x.get("via") for x in r], "blk": (tx.get("block_number"), blk), "jobs": jobs_left(), "req": reqs(), "w": wst()})


w, wr = fresh()
run(w, 3)
cp0 = wst().get("cp")
T.chk(isinstance(cp0, list) and len(cp0) == 3, "G1 전제: 정상 주기 세 번 뒤 체크포인트 저장", cp0)
nb1 = CH.head + 5
dep1 = CH.native(nb1, B.OTHER, B.W1, E17)
tick(GAP_SEC, GAP_BLK)
w = mk(wr)
run(w, 10)
chk_one(wr, dep1, nb1, E17, "G1")
T.chk(not reqs() and jobs_left() == 0 and not bd_attr(wr) and not (wst().get("ux") or []),
      "G1 기초 잔고 요청 0 · 거짓 귀속 0 · 남은 작업·미해결 0", {"req": reqs(), "bd": bd_attr(wr), "w": wst()})
run(w, 3)
T.chk(len(recs(wr, dep1)) == 1, "G1 뒤 주기 — 같은 입금 다시 방출 0")

w, wr = fresh()
run(w, 3)
nb2 = CH.head + 5
dep2 = CH.native(nb2, B.OTHER, B.W1, E17)
tick(GAP_SEC, GAP_BLK)
run(w, 10)
chk_one(wr, dep2, nb2, E17, "G2a 재시작 없음 ·")
T.chk(not reqs() and jobs_left() == 0 and not bd_attr(wr), "G2a 요청·작업·거짓 귀속 0")

w, wr = fresh()
run(w, 3)
nb2b = CH.head + 5
dep2b = CH.native(nb2b, B.OTHER, B.W1, E17)
at0 = int(balw_st().get("at") or 0)
def _down():
    raise RuntimeError("synthetic upstream outage")


w.head = _down
for _ in range(10):
    tick(270, 600)
    B.cycle(w)
T.chk(int(balw_st().get("at") or 0) == at0, "G2b 전제: 장애 동안 잔고 감시가 한 번도 못 돎(지난 확인 45분 전)", (balw_st().get("at"), at0))
del w.head
gates_reset()
run(w, 10, gr=True)
chk_one(wr, dep2b, nb2b, E17, "G2b 상류 장애 뒤 ·")
T.chk(not reqs() and jobs_left() == 0 and not bd_attr(wr), "G2b 요청·작업·거짓 귀속 0")

w, wr = fresh()
run(w, 3)
nb3 = CH.head + 5
dep3 = CH.native(nb3, B.OTHER, B.W1, E17)
out3 = CH.native(CH.head + 900, B.W1, B.OTHER, 5 * E17)
tick(GAP_SEC, GAP_BLK)
w = mk(wr)
run(w, 10)
chk_one(wr, dep3, nb3, E17, "G3a 출금 섞인 공백 ·")
T.chk(len(recs(wr, out3)) == 1 and recs(wr, out3)[0].get("via") == "nonce" and not bd_attr(wr) and not reqs() and jobs_left() == 0,
      "G3a 출금 = nonce 회수 한 번 · 잔고 감시 다시 방출 0 · 거짓 귀속·기초 잔고 요청 0", {"out": [r.get("via") for r in recs(wr, out3)], "bd": bd_attr(wr), "req": reqs()})

w, wr = fresh()
run(w, 3)
cp3 = list(wst().get("cp") or [])
nb3b = CH.head + 5
dep3b = CH.native(nb3b, B.OTHER, B.W1, E17)
out3b = CH.native(CH.head + 900, B.W1, B.OTHER, 5 * E17)
old = mk(wr)
old._balw_pass = lambda head, S: 0
old._balw_note = lambda rec: None
run(old, 30)
ingest(wr)
n3b = len(wr.recs)
T.chk(len(recs(wr, out3b)) == 1 and dep3b not in B.emitted(wr), "G3b 전제: 옛 코드가 출금만 방출(입금은 못 봄)", B.emitted(wr)[-3:])
w = mk(wr)
run(w, 10)
chk_one(wr, dep3b, nb3b, E17, "G3b 되돌림 뒤 ·")
T.chk(len(recs(wr, out3b)) == 1 and not bd_attr(wr) and not reqs() and jobs_left() == 0 and not (wst().get("ux") or []),
      "G3b 옛 코드 출금 다시 방출 0 · 거짓 귀속·기초 잔고 요청 0 · 미해결 0", {"new": [(r["txhash"][-6:], r.get("via")) for r in wr.recs[n3b:]], "req": reqs(), "w": wst()})

w, wr = fresh()
run(w, 3)
cp4 = list(wst().get("cp") or [])
nb4 = CH.head + 5
dep4 = CH.native(nb4, B.OTHER, B.W1, E17)
out4 = CH.native(CH.head + 900, B.W1, B.OTHER, 5 * E17)
old = mk(wr)
old._balw_pass = lambda head, S: 0
old._balw_note = lambda rec: None
run(old, 30)
ingest(wr)
raw0 = bw.BscWatcher._balw_raw_deltas
bw.BscWatcher._balw_raw_deltas = lambda self, *a, **k: None
w = mk(wr)
run(w, 5)
ux4 = wst().get("ux") or []
T.chk(dep4 not in B.emitted(wr) and not reqs() and jobs_left() == 0 and len(ux4) == 1 and int(ux4[0].get("a") or 0) == int(cp4[0]),
      "G4a 원장 읽기 실패 동안 = 공백 구간(옛 체크포인트부터)을 미해결로 보존 · 방출·요청·작업 0(성공 처리 안 함)", {"ux": ux4, "cp0": cp4, "req": reqs()})
w = mk(wr)
bw.BscWatcher._balw_raw_deltas = raw0
run(w, 6)
chk_one(wr, dep4, nb4, E17, "G4a 회복 뒤 ·")
T.chk(len(recs(wr, out4)) == 1 and not bd_attr(wr) and not reqs() and jobs_left() == 0 and not (wst().get("ux") or []),
      "G4a 회복 뒤 출금 다시 방출 0 · 거짓 귀속·요청 0 · 미해결 0", {"req": reqs(), "w": wst()})

w, wr = fresh()
run(w, 3)
cp4b = list(wst().get("cp") or [])
nb4b = CH.head + 5
dep4b = CH.native(nb4b, B.OTHER, B.W1, E17)
tick(GAP_SEC, GAP_BLK)
cap0 = bw.BALW_DAY_CAP
bw.BALW_DAY_CAP = 0
w = mk(wr)
run(w, 4)
jb4 = (wst().get("jobs") or [{}])[0]
T.chk(dep4b not in B.emitted(wr) and not reqs() and jobs_left() == 1 and int(jb4.get("a") or 0) == int(cp4b[0]),
      "G4b 예산 소진 동안 = 공백 구간 작업 보존(옛 체크포인트부터) · 방출·요청 0", {"w": wst(), "req": reqs()})
bw.BALW_DAY_CAP = cap0
w = mk(wr)
run(w, 6)
chk_one(wr, dep4b, nb4b, E17, "G4b 회복 뒤 ·")
T.chk(not reqs() and jobs_left() == 0, "G4b 요청·남은 작업 0")

w, wr = fresh(arch=False)
run(w, 3)
nb5 = CH.head + 5
dep5 = CH.native(nb5, B.OTHER, B.W1, E17)
tick(GAP_SEC, GAP_BLK)
w = mk(wr, arch=False)
run(w, 10)
q5 = reqs()
rq5 = (balw_st().get("reqs") or [])
T.chk(dep5 not in B.emitted(wr) and len(q5) == 1 and q5[0]["block"] >= nb5 and int(q5[0]["diff_raw"]) == E17
      and q5[0]["chain_bal_raw"] == str(CH.balance(B.W1, q5[0]["block"])) and q5[0]["sources"] == ["bsc_balance_watch"]
      and rq5 and "아카이브 없음" in str(rq5[-1][3]),
      "G5 아카이브 없음 · 공백 구간 = 구간 끝 블록 잔고로 기초 잔고 요청 한 번(원가 미상 · 사유 기록) · 거짓 방출 0",
      {"q": q5, "reqs": rq5, "dep_blk": nb5})
run(w, 3)
T.chk(len(reqs()) == 1 and jobs_left() == 0 and not (wst().get("ux") or []), "G5 같은 요청 반복 0 · 남은 작업·미해결 0", {"q": reqs(), "w": wst()})

w, wr = fresh()
run(w, 3)
tick(GAP_SEC, GAP_BLK)
w = mk(wr)
run(w, 4)
T.chk(not [r for r in wr.recs if r.get("via") == "balw"] and not reqs() and jobs_left() == 0 and not (wst().get("ux") or []),
      "G6 공백 동안 아무 일 없음 = 방출·요청·작업·미해결 0", {"w": wst(), "req": reqs()})
w, wr = fresh()
run(w, 3)
dep6 = CH.native(CH.head + 5, B.OTHER, B.W1, E17)
tick(GAP_SEC, GAP_BLK)
bw.BscWatcher._balw_raw_deltas = lambda self, *a, **k: None
w = mk(wr)
run(w, 3)
nb6 = CH.head + 5
new6 = CH.native(nb6, B.OTHER, B.W1, 3 * E17)
run(w, 4)
T.chk(len(recs(wr, new6)) == 1 and recs(wr, new6)[0].get("via") == "balw" and dep6 not in B.emitted(wr) and len(wst().get("ux") or []) == 1,
      "G6 공백 구간이 미해결로 막힌 동안에도 그 뒤 새 입금은 바로 방출(최신 먼저 · 공백 구간은 보존)",
      {"new": len(recs(wr, new6)), "old": dep6 in B.emitted(wr), "w": wst()})
bw.BscWatcher._balw_raw_deltas = raw0
run(w, 6)
T.chk(len(recs(wr, dep6)) == 1 and len(recs(wr, new6)) == 1 and not reqs() and jobs_left() == 0 and not (wst().get("ux") or []),
      "G6 회복 뒤 공백 안 입금도 한 번 · 새 입금 다시 방출 0", {"old": len(recs(wr, dep6)), "w": wst()})

w, wr = fresh()
run(w, 3)
nb7 = CH.head + 5
dep7 = CH.native(nb7, B.OTHER, B.W1, E17)
out7 = CH.native(CH.head + 900, B.W1, B.OTHER, 5 * E17)
tick(3 * 3600, 24_000)
w = mk(wr)
np0 = bw.BscWatcher._nonce_pass
bw.BscWatcher._nonce_pass = lambda self, *a, **k: 0
run(w, 3)
T.chk(dep7 not in B.emitted(wr) and out7 not in B.emitted(wr) and not reqs(), "G7 nonce 회수 전 = 공백 구간 보류(출금 미방출 · 입금 아직)",
      {"w": wst(), "req": reqs()})
bw.BscWatcher._nonce_pass = np0
run(w, 8)
chk_one(wr, dep7, nb7, E17, "G7 nonce 회수 뒤 ·")
T.chk(len(recs(wr, out7)) == 1 and not reqs() and not bd_attr(wr) and jobs_left() == 0, "G7 출금 한 번 · 요청·거짓 귀속 0")

w, wr = fresh()
run(w, 3)
nb9g = CH.head + 5
dep9g = CH.native(nb9g, B.OTHER, B.W1, E17)
ans9 = CH.answer
CH.answer = lambda url, m, p: None if (m == "eth_getBalance" and url == B.DET and str(p[0]).lower() == B.W1) else ans9(url, m, p)
cp9 = list(wst().get("cp") or [])
run(w, 3)
T.chk(list(wst().get("cp") or []) == cp9 and dep9g not in B.emitted(wr), "G9 잔고 null 동안 = 체크포인트 그대로(방출 아직)", {"cp": wst().get("cp"), "cp0": cp9})
CH.answer = ans9
run(w, 4)
chk_one(wr, dep9g, nb9g, E17, "G9 잔고 읽기 회복 뒤 ·")

WS10 = [B.W1, B.W2] + ["0x" + format(0xf800 + k, "040x") for k in range(6)]
w, wr = fresh(wallets=WS10)
run(w, 3)
tick(GAP_SEC, GAP_BLK)
w = mk(wr, wallets=WS10)
rd10 = bw.BscWatcher._balw_raw_deltas
c10 = sqlite3.connect
inside, reads10, calls10 = [False], [0], [0]


def cc10(*a, **k):
    if inside[0]:
        reads10[0] += 1
    return c10(*a, **k)


def rdw10(self, *a, **k):
    calls10[0] += 1
    inside[0] = True
    try:
        return rd10(self, *a, **k)
    finally:
        inside[0] = False


sqlite3.connect = cc10
bw.BscWatcher._balw_raw_deltas = rdw10
run(w, 1)
sqlite3.connect = c10
bw.BscWatcher._balw_raw_deltas = rd10
n10 = sum(1 for a9 in WS10 if ((balw_st().get("w") or {}).get(a9) or {}).get("ux"))
T.chk(calls10[0] >= len(WS10) and reads10[0] == 1 and n10 == 0, "G10 공백 뒤 지갑 8개 평가 = 원장 읽기 1번(실행당 캐시) · 미해결 0",
      {"calls": calls10[0], "reads": reads10[0], "ux": n10})

w, wr = fresh()
run(w, 3)
nb8 = CH.head + 5
dep8 = CH.native(nb8, B.OTHER, B.W1, E17)
out8 = CH.native(CH.head + 900, B.W1, B.OTHER, 5 * E17)
tick(3 * 3600, 24_000)
ls0 = bw.BscWatcher._lane_scan


def ls_block(self, a, b, key, *args, **kw):
    if key == "_scan":
        raise RuntimeError("synthetic side-lane outage")
    return ls0(self, a, b, key, *args, **kw)


bw.BscWatcher._lane_scan = ls_block
w = mk(wr)
run(w, 3)
T.chk(isinstance(B.cur().get("_live"), dict) and dep8 not in B.emitted(wr) and len(wst().get("ux") or []) == 1 and not reqs() and not bd_attr(wr),
      "G8 옆 차선이 공백 구간을 아직 못 훑음 = 공백 구간 보류(미해결 1 · 방출·요청·거짓 귀속 0)", {"live": B.cur().get("_live"), "w": wst()})
nb8b = CH.head + 5
new8 = CH.native(nb8b, B.OTHER, B.W1, 3 * E17)
run(w, 3)
T.chk(len(recs(wr, new8)) == 1 and recs(wr, new8)[0].get("via") == "balw" and dep8 not in B.emitted(wr) and len(wst().get("ux") or []) == 1,
      "G8 차선 중 새 입금은 바로(최신 먼저) · 공백 구간은 옆 차선 끝까지 보류", {"new": len(recs(wr, new8)), "w": wst()})
bw.BscWatcher._lane_scan = ls0
run(w, 10)
chk_one(wr, dep8, nb8, E17, "G8 옆 차선 끝난 뒤 ·")
T.chk(len(recs(wr, out8)) == 1 and len(recs(wr, new8)) == 1 and not reqs() and not bd_attr(wr) and jobs_left() == 0 and not (wst().get("ux") or []),
      "G8 출금·새 입금 한 번씩 · 요청·거짓 귀속·남은 작업·미해결 0", {"out": len(recs(wr, out8)), "req": reqs(), "w": wst()})

w, wr = fresh()
CH.tx.clear()
old_h1 = CH.native(CH.head - 400_000, B.OTHER, B.W1, 9 * E18)
run(w, 2)
common.atomic_write_json(os.path.join(common.STATE_DIR, "onchain_check.json"),
                         {"mismatches": [{"key": f"bsc:{B.W1}:native", "chain": "bsc", "wallet": B.W1, "ca": None, "sym": "BNB",
                                          "ledger": 1.0, "onchain": 10.0, "confirmed": True}]})
bw.BscWatcher._balw_raw_deltas = lambda self, *a, **k: None
run(w, 2)
T.chk(old_h1 not in B.emitted(wr) and jobs_left() == 0, "H1 전제: 원장 읽기 실패 동안 지난 누락 탐색 못 함")
bw.BscWatcher._balw_raw_deltas = raw0
got_h1 = None
for k in range(12):
    tick(90, 200)
    B.cycle(w)
    if old_h1 in B.emitted(wr):
        got_h1 = k + 1
        break
T.chk(got_h1 is not None and len(recs(wr, old_h1)) == 1 and recs(wr, old_h1)[0].get("via") == "balw",
      "H1 원장 회복 뒤 몇 분 안에 다시 탐색 → 놓친 입금 방출(종전 = '탐색함'으로 기록돼 하루 뒤)", {"cycle": got_h1, "hist_at": wst().get("hist_at"), "now": clk[0]})

RX = os.path.join(common.STATE_DIR, getattr(bw, "BALW_RX_NAME", "bsc_balw_recheck.json"))
for arch_r in (True, False):
    w, wr = fresh(arch=arch_r)
    run(w, 3)
    nbr = CH.head + 5
    depr = CH.native(nbr, B.OTHER, B.W1, E17)
    tick(GAP_SEC, GAP_BLK)
    w = mk(wr, arch=arch_r)
    ua0 = getattr(bw.BscWatcher, "_balw_ux_add", None)
    if ua0 is not None:
        bw.BscWatcher._balw_ux_add = lambda self, *a, **k: None
    run(w, 1)
    if ua0 is not None:
        bw.BscWatcher._balw_ux_add = ua0
    run(w, 3)
    T.chk(depr not in B.emitted(wr) and not reqs(), f"R1 전제(아카이브 {arch_r}): 옛 코드가 덮어쓴 체크포인트 = 그 사이 입금 안 보임")
    common.atomic_write_json(RX, {"hours": 2})
    run(w, 6)
    if arch_r:
        chk_one(wr, depr, nbr, E17, "R1 요청 파일(최근 2시간 다시 점검) →")
        T.chk(not os.path.exists(RX) and not reqs() and jobs_left() == 0 and not bd_attr(wr) and not wst().get("rx"),
              "R1 요청 파일 정리 · 요청·작업·거짓 귀속 0", {"rx": os.path.exists(RX), "req": reqs(), "w": wst()})
        run(w, 3)
        T.chk(len(recs(wr, depr)) == 1, "R1 같은 입금 다시 방출 0")
    else:
        T.chk(depr not in B.emitted(wr) and not reqs() and not os.path.exists(RX) and not wst().get("rx") and jobs_left() == 0,
              "R1 아카이브 없음 = 다시 점검 못 함(경고) · 거짓 방출·요청 0 · 요청 정리", {"req": reqs(), "w": wst()})

w, wr = fresh()
run(w, 3)
nk1 = CH.head + 5
dk1 = CH.native(nk1, B.OTHER, B.W1, E17)
ok1 = CH.native(CH.head + 900, B.W1, B.OTHER, 5 * E17)
old = mk(wr)
old._balw_pass = lambda head, S: 0
old._balw_note = lambda rec: None
run(old, 30)
w = mk(wr)
run(w, 10, sec=900, blocks=2000)
ux_k1 = wst().get("ux") or []
T.chk(dk1 not in B.emitted(wr) and len(ux_k1) == 1 and not reqs(), "K1 출금 기장 전 = 공백 구간 보존(2시간 넘어도 음수 잔여로 버리지 않음)", {"ux": ux_k1, "req": reqs()})
ingest(wr)
run(w, 6)
chk_one(wr, dk1, nk1, E17, "K1 출금 기장 뒤 ·")
T.chk(len(recs(wr, ok1)) == 1 and not reqs() and not bd_attr(wr) and not (wst().get("ux") or []), "K1 출금 다시 방출 0 · 요청·거짓 귀속·미해결 0", {"w": wst(), "req": reqs()})

w, wr = fresh()
run(w, 3)
s_k = balw_st()
cpk = (s_k["w"][B.W1])["cp"]
segs = [{"a": cpk[0] - 3000 + 100 * i, "ba": str(cpk[1]), "na": 1, "z": cpk[0] - 3000 + 100 * i + 50, "bz": str(cpk[1]), "nz": 2,
         "t0": int(clk[0]), "why": "시험"} for i in range(int(bw.BALW_JOBS_MAX) + 1)]
s_k["w"][B.W1]["ux"] = segs
common.atomic_write_json(BALW, s_k)
w._balw_st = None
run(w, 1)
uxk = wst().get("ux") or []
qk = reqs()
T.chk(len(uxk) == int(bw.BALW_JOBS_MAX) and len(qk) == 1 and qk[0]["block"] == segs[0]["z"] and uxk[0]["a"] == segs[1]["a"],
      "K1b 미해결 21개 = 가장 오래된 1개만 구간 끝 기초 잔고 요청으로 마감 · 20개 보존(종전 = 그대로 평가해 조용히 버림)", {"ux": len(uxk), "q": qk})

w, wr = fresh()
run(w, 3)
nk2 = CH.head + 5
dk2 = CH.native(nk2, B.OTHER, B.W1, E17)
tick(GAP_SEC, GAP_BLK)
ans_k2 = CH.answer
lim_k2 = [CH.head - 1000]
CH.answer = lambda url, m, p: ({"_err": {"code": -32603, "message": "internal error (synthetic)"}}
                               if (url == B.ARCH and m == "eth_getBalance" and p[1] not in ("latest", "pending") and int(p[1], 16) < lim_k2[0])
                               else ans_k2(url, m, p))
w = mk(wr)
run(w, 2)
T.chk(dk2 not in B.emitted(wr) and jobs_left() >= 1, "K2 전제: 공백 작업이 옛 블록 조회 실패로 멈춤", {"jobs": jobs_left()})
nk2b = CH.head + 5
nw2 = CH.native(nk2b, B.OTHER, B.W1, 3 * E17)
got_k2 = None
for k in range(4):
    tick(90, 200)
    B.cycle(w)
    if nw2 in B.emitted(wr):
        got_k2 = k + 1
        break
T.chk(got_k2 is not None and recs(wr, nw2)[0].get("via") == "balw" and dk2 not in B.emitted(wr),
      "K2 막힌 공백 작업이 있어도 새 입금 작업이 먼저(몇 주기 안 방출)", {"cycle": got_k2, "jobs": [(j.get("a"), j.get("back")) for j in wst().get("jobs") or []]})
CH.answer = ans_k2
run(w, 8)
T.chk(len(recs(wr, dk2)) == 1 and len(recs(wr, nw2)) == 1 and not reqs() and jobs_left() == 0, "K2 회복 뒤 공백 입금도 1 · 새 입금 다시 방출 0", {"w": wst(), "req": reqs()})

w, wr = fresh()
run(w, 3)
nk3 = CH.head + 5
dk3 = CH.native(nk3, B.OTHER, B.W1, E17)
tick(GAP_SEC, GAP_BLK)
ans_k3 = CH.answer
alt = [0]


def ans_alt(url, m, p):
    if url == B.ARCH and m == "eth_getBalance" and p[1] not in ("latest", "pending") and int(p[1], 16) < CH.head - 300:
        alt[0] += 1
        if alt[0] % 2 == 1:
            return {"_err": {"code": -32000, "message": "missing trie node (synthetic)"}}
    return ans_k3(url, m, p)


CH.answer = ans_alt
w = mk(wr)
run(w, 30)
CH.answer = ans_k3
T.chk(len(recs(wr, dk3)) == 1 and recs(wr, dk3)[0].get("via") == "balw" and not reqs(),
      "K3 실패·성공이 번갈아 = 연속 아님 — 실제 거래로 회수(종전 = 세 번째 실패에 기초 잔고 요청으로 마감)", {"n": len(recs(wr, dk3)), "req": reqs(), "alt": alt[0]})

WS_K4 = [B.W1, B.W2] + ["0x" + format(0xf900 + k, "040x") for k in range(6)]
c_k4 = B.cfg(detail_rpcs=[B.ARCH], archive_rpcs=[B.ARCH])
c_k4["wallets"] = [{"type": "bsc_rpc", "address": a} for a in WS_K4]
w, wr = fresh(wallets=WS_K4, c=c_k4)
run(w, 5, sec=900, blocks=2000)
nk4 = CH.head + 5
many_k4 = [CH.native(nk4, B.OTHER, B.W1, (k + 1) * 10 ** 16) for k in range(4)]
for _ in range(16):
    tick(900, 2000)
    B.cycle(w)
T.chk(all(len(recs(wr, h)) == 1 and recs(wr, h)[0].get("via") == "balw" for h in many_k4) and not reqs(),
      "K4 아카이브 전용 · 한 블록 직접 입금 4건 = 남은 몫만큼 나눠 모두 실제 거래로(종전 = 묶음 12콜 예약에 매번 멈춤)",
      {"emitted": sum(1 for h in many_k4 if h in B.emitted(wr)), "req": reqs(), "last": balw_st().get("last")})

for raw_k5 in ('{"hours": 1e309}', '{"hours": true}', '{"since": 1e20}', '{"hours": -3}'):
    w, wr = fresh()
    run(w, 3)
    with open(RX, "w", encoding="utf-8") as f:
        f.write(raw_k5)
    nk5 = CH.head + 5
    dk5 = CH.native(nk5, B.OTHER, B.W1, E17)
    run(w, 4)
    bad5 = [f9 for f9 in os.listdir(common.STATE_DIR) if f9.startswith(os.path.basename(RX) + ".bad")]
    T.chk(not os.path.exists(RX) and bad5 and not wst().get("rx") and len(recs(wr, dk5)) == 1,
          f"K5 요청 {raw_k5} = .bad 로 옮김 · 다시 점검 안 함 · 잔고 감시 계속(새 입금 1)", {"rx": os.path.exists(RX), "bad": bad5, "n": len(recs(wr, dk5))})

WS_M1 = [B.W1, B.W2] + ["0x" + format(0xfa00 + k, "040x") for k in range(6)]
c_m1 = B.cfg(detail_rpcs=[B.ARCH], archive_rpcs=[B.ARCH])
c_m1["wallets"] = [{"type": "bsc_rpc", "address": a} for a in WS_M1]
w, wr = fresh(wallets=WS_M1, c=c_m1)
run(w, 5, sec=900, blocks=2000)
d_m1 = []
for k in range(20):
    d_m1.append(CH.native(CH.head + 5, B.OTHER, B.W1, (k + 1) * 10 ** 15))
    tick(900, 2000)
    B.cycle(w)
first3 = [len(recs(wr, h)) for h in d_m1[:3]]
q_m1 = [q for q in reqs() if q["wallet"] == B.W1]
T.chk(first3 == [1, 1, 1] and all(recs(wr, h)[0].get("via") == "balw" for h in d_m1[:3]) and not q_m1,
      "M1 매 실행 새 입금이 와도 먼저 온 입금(이어 가는 작업)이 실제 거래로 회수됨(종전 = 새 창이 늘 먼저 → 옛 작업 굶음)",
      {"first3": first3, "emitted": sum(1 for h in d_m1 if h in B.emitted(wr)), "jobs": jobs_left(), "q": q_m1})
for _ in range(30):
    tick(900, 2000)
    B.cycle(w)
T.chk(all(len(recs(wr, h)) == 1 for h in d_m1) and not [q for q in reqs() if q["wallet"] == B.W1] and jobs_left() == 0,
      "M1 입금이 멈춘 뒤 20건 모두 실제 거래 한 번씩 · 기초 잔고 요청 0", {"emitted": sum(1 for h in d_m1 if h in B.emitted(wr)), "jobs": jobs_left()})

w, wr = fresh(arch=False)
run(w, 3)
common.atomic_write_json(os.path.join(common.STATE_DIR, "onchain_check.json"),
                         {"mismatches": [{"key": f"bsc:{B.W2}:native", "chain": "bsc", "wallet": B.W2, "ca": None, "sym": "BNB",
                                          "ledger": 1.0, "onchain": 2.0, "confirmed": True}]})
d_m2 = []
got_m2 = None
for k in range(6):
    d_m2.append(CH.native(CH.head - 17, B.OTHER, B.W1, (k + 1) * 10 ** 16))
    tick(90, 250)
    B.cycle(w)
    if got_m2 is None and [q for q in reqs() if q["wallet"] == B.W2]:
        got_m2 = k + 1
T.chk(got_m2 is not None, "M2 최신 창 본문 훑기가 매 실행 상한에 닿아도 지난 누락 탐색(옛 몫)이 돎(종전 = 실행 전체 멈춤 → 영영 안 돎)",
      {"cycle": got_m2, "req": reqs(), "jobs": jobs_left()})
for _ in range(40):
    tick(90, 10)
    B.cycle(w)
T.chk(all(len(recs(wr, h)) == 1 and recs(wr, h)[0].get("via") == "balw" for h in d_m2) and not [q for q in reqs() if q["wallet"] == B.W1],
      "M2 W1 직접 입금 6건 모두 공개 본문 훑기로 실제 거래 한 번씩(최신·옛 몫 나눠도 누락 0)", {"emitted": sum(1 for h in d_m2 if h in B.emitted(wr)), "jobs": jobs_left()})

w, wr = fresh()
dA_m3 = CH.native(CH.head - 5000, B.OTHER, B.W1, 2 * E18)
dB_m3 = CH.native(CH.head - 100, B.OTHER, B.W1, E17)
run(w, 3)
lim_m3 = CH.head - 1000
mk_job = lambda a9, z9: {"k": "fwd", "a": a9, "z": z9, "s": {str(a9): str(CH.balance(B.W1, a9)), str(z9): str(CH.balance(B.W1, z9))},
                         "t0": int(clk[0]) - 600 + (0 if a9 < lim_m3 else 60), "n": 0, "done": [], "back": True}
s_m3 = balw_st()
s_m3["w"][B.W1]["jobs"] = [mk_job(CH.head - 5600 - 40, CH.head - 5600 + 4000), mk_job(CH.head - 700 - 30, CH.head - 700 + 30)]
common.atomic_write_json(BALW, s_m3)
w._balw_st = None
ans_m3 = CH.answer
CH.answer = lambda url, m, p: ({"_err": {"code": -32603, "message": "internal error (synthetic)"}}
                               if (url == B.ARCH and m == "eth_getBalance" and p[1] not in ("latest", "pending") and int(p[1], 16) < lim_m3)
                               else ans_m3(url, m, p))
run(w, 3)
T.chk(len(recs(wr, dB_m3)) == 1 and recs(wr, dB_m3)[0].get("via") == "balw" and dA_m3 not in B.emitted(wr),
      "M3 앞선 옛 작업이 노드 오류로 실패해도 같은 지갑 다음 옛 작업은 같은 실행에서 진행(종전 = 첫 작업 실패가 실행 전체를 끝내 영영 막음)",
      {"B": len(recs(wr, dB_m3)), "jobs": [(j.get("a"), j.get("ft")) for j in wst().get("jobs") or []]})
CH.answer = ans_m3
run(w, 8)
T.chk(len(recs(wr, dA_m3)) == 1 and len(recs(wr, dB_m3)) == 1 and not reqs() and jobs_left() == 0, "M3 노드 회복 뒤 앞선 작업 입금도 1 · 요청 0", {"w": wst(), "req": reqs()})

def craft_jobs(w9, spans):
    s9 = balw_st()
    s9["w"][w9]["jobs"] = [{"k": "fwd", "a": a9, "z": z9, "s": {str(a9): str(CH.balance(w9, a9)), str(z9): str(CH.balance(w9, z9))},
                            "t0": int(clk[0]) - 600, "n": 0, "done": [], "back": True} for a9, z9 in spans]
    common.atomic_write_json(BALW, s9)


w, wr = fresh()
h_p1 = CH.head
dep_p1 = [CH.native(h_p1 - 8000 + 300 * i, B.OTHER, B.W1, (i + 1) * 10 ** 15) for i in range(20)]
run(w, 3)
spans_p1 = [(h_p1 - 8000 + 300 * i - 100, h_p1 - 8000 + 300 * i + 100) for i in range(20)]
craft_jobs(B.W1, spans_p1)
w._balw_st = None
nb_p1 = CH.head + 5
new_p1 = CH.native(nb_p1, B.OTHER, B.W1, 7 * E17)
run(w, 2)
q_p1 = [q for q in reqs() if q["wallet"] == B.W1]
T.chk(len(recs(wr, new_p1)) == 1 and recs(wr, new_p1)[0].get("via") == "balw" and q_p1 and q_p1[0]["block"] == spans_p1[0][1],
      "P1 작업 21개 = 끝 블록이 가장 이른 작업만 그 끝 블록 기초 잔고로 마감 · 방금 생긴 최신 창은 실제 거래로(종전 = 같은 폭이면 최신 창을 먼저 마감)",
      {"new": len(recs(wr, new_p1)), "q": [(q["block"], q["diff_raw"]) for q in q_p1], "oldest_z": spans_p1[0][1]})

WS_P2 = [B.W1, B.W2] + ["0x" + format(0xfb00 + k, "040x") for k in range(6)]
c_p2 = B.cfg(detail_rpcs=[B.ARCH], archive_rpcs=[B.ARCH])
c_p2["wallets"] = [{"type": "bsc_rpc", "address": a} for a in WS_P2]
w, wr = fresh(wallets=WS_P2, c=c_p2)
h_p2 = CH.head
depA_p2 = CH.native(h_p2 - 6000, B.OTHER, B.W1, 3 * E17)
run(w, 5, sec=900, blocks=2000)
craft_jobs(B.W1, [(h_p2 - 6000 - 8, h_p2 - 6000 + 8)])
w._balw_st = None
lim_p2 = h_p2 - 3000
ans_p2 = CH.answer
CH.answer = lambda url, m, p: ({"_err": {"code": -32603, "message": "internal error (synthetic)"}}
                               if (url == B.ARCH and m == "eth_getBalance" and p[1] not in ("latest", "pending") and int(p[1], 16) < lim_p2)
                               else ans_p2(url, m, p))
got_p2 = None
new_p2 = []
for k in range(20):
    if k == 4:
        CH.answer = ans_p2
    new_p2.append(CH.native(CH.head + 5, B.OTHER, B.W1, (k + 1) * 10 ** 15))
    tick(900, 2000)
    B.cycle(w)
    if got_p2 is None and depA_p2 in B.emitted(wr):
        got_p2 = k + 1
CH.answer = ans_p2
T.chk(got_p2 is not None and recs(wr, depA_p2)[0].get("via") == "balw",
      "P2 실패하던 이어 가는 작업도 회복 뒤 새 입금이 계속 와도 차례를 받아 실제 거래로(종전 = 한 번 실패 표식이 정상 작업 뒤로 영영 밀림)",
      {"cycle": got_p2, "jobs": jobs_left(), "emitted_new": sum(1 for h in new_p2 if h in B.emitted(wr))})
for _ in range(40):
    tick(900, 2000)
    B.cycle(w)
T.chk(all(len(recs(wr, h)) == 1 for h in new_p2 + [depA_p2]) and not [q for q in reqs() if q["wallet"] == B.W1],
      "P2 입금이 멈춘 뒤 모두 실제 거래 한 번씩 · 기초 잔고 요청 0", {"emitted": sum(1 for h in new_p2 if h in B.emitted(wr)), "jobs": jobs_left()})

w, wr = fresh()
h_p3 = CH.head
depA_p3 = [CH.native(h_p3 - 30000 + 3000 * i, B.OTHER, B.W1, (i + 1) * 10 ** 15) for i in range(8)]
depB_p3 = CH.native(h_p3 - 4000, B.OTHER, B.W2, 4 * E17)
run(w, 3)
craft_jobs(B.W1, [(h_p3 - 30000 + 3000 * i - 1000, h_p3 - 30000 + 3000 * i + 1000) for i in range(8)])
craft_jobs(B.W2, [(h_p3 - 4000 - 8, h_p3 - 4000 + 8)])
w._balw_st = None
got_p3 = None
for k in range(6):
    tick(90, 200)
    B.cycle(w)
    if got_p3 is None and depB_p3 in B.emitted(wr):
        got_p3 = k + 1
T.chk(got_p3 is not None and got_p3 <= 2 and recs(wr, depB_p3)[0].get("via") == "balw",
      "P3 지갑 A 작업 8개가 이어지는 동안에도 지갑 B 작업이 2실행 안에 실제 거래로(마지막으로 일한 시각 순 · 지갑 순번 없음)",
      {"cycle": got_p3, "A_emitted": sum(1 for h in depA_p3 if h in B.emitted(wr))})
run(w, 10)
T.chk(all(len(recs(wr, h)) == 1 for h in depA_p3 + [depB_p3]) and not reqs() and jobs_left() == 0, "P3 A 8건·B 1건 모두 한 번씩 · 요청·남은 작업 0",
      {"A": sum(1 for h in depA_p3 if h in B.emitted(wr)), "jobs": jobs_left(), "req": reqs()})

WS_Q1 = [B.W1, B.W2] + ["0x" + format(0xfc00 + k, "040x") for k in range(6)]
c_q1 = B.cfg(detail_rpcs=[B.ARCH], archive_rpcs=[B.ARCH])
c_q1["wallets"] = [{"type": "bsc_rpc", "address": a} for a in WS_Q1]
w, wr = fresh(wallets=WS_Q1, c=c_q1)
h_q1 = CH.head
depA_q1 = CH.native(h_q1 - 6000, B.OTHER, B.W1, 3 * E17)
run(w, 5, sec=900, blocks=2000)
craft_jobs(B.W1, [(h_q1 - 6000 - 32, h_q1 - 6000 + 32)])
s_q1 = balw_st()
s_q1["w"][B.W1]["jobs"][0]["lw"] = clk[0] - 100
common.atomic_write_json(BALW, s_q1)
w._balw_st = None
got_q1 = None
for k in range(12):
    for a9 in WS_Q1[2:]:
        CH.native(CH.head + 5, B.OTHER, a9, (k + 1) * 10 ** 15)
    tick(900, 2000)
    B.cycle(w)
    if got_q1 is None and depA_q1 in B.emitted(wr):
        got_q1 = k + 1
T.chk(got_q1 is not None and recs(wr, depA_q1)[0].get("via") == "balw",
      "Q1 6지갑 매 실행 새 입금에도 일하던 작업이 차례를 받아 실제 거래로(종전 = 새 작업 lw 0 이 늘 앞서 굶음)", {"cycle": got_q1, "jobs": jobs_left()})

c_q2 = B.cfg(detail_rpcs=[B.ARCH], archive_rpcs=[B.ARCH])
w, wr = fresh(c=c_q2)
h_q2 = CH.head
depB_q2 = CH.native(h_q2 - 2000, B.OTHER, B.W2, 4 * E17)
for i in range(20):
    CH.native(h_q2 - 9000 + 300 * i, B.OTHER, B.W1, (i + 1) * 10 ** 15)
run(w, 5, sec=900, blocks=2000)
craft_jobs(B.W1, [(h_q2 - 9000 + 300 * i - 100, h_q2 - 9000 + 300 * i + 100) for i in range(20)])
craft_jobs(B.W2, [(h_q2 - 2000 - 8, h_q2 - 2000 + 8)])
s_q2 = balw_st()
for i, j9 in enumerate(s_q2["w"][B.W1]["jobs"]):
    j9["lw"] = clk[0] - 1000 + i
s_q2["w"][B.W2]["jobs"][0]["lw"] = clk[0] - 500
common.atomic_write_json(BALW, s_q2)
w._balw_st = None
lim_q2 = h_q2 - 5000
ans_q2 = CH.answer
CH.answer = lambda url, m, p: ({"_err": {"code": -32603, "message": "internal error (synthetic)"}}
                               if (url == B.ARCH and m == "eth_getBalance" and p[1] not in ("latest", "pending") and int(p[1], 16) < lim_q2)
                               else ans_q2(url, m, p))
got_q2, nB_q2 = None, []
sl_q2 = time.sleep
time.sleep = lambda s9: None
for k in range(10):
    tick(900, 2000)
    B.cycle(w)
    jb2 = (wst(B.W2).get("jobs") or [{}])[0]
    nB_q2.append(int(jb2.get("n") or 0) if jb2 else -1)
    if got_q2 is None and depB_q2 in B.emitted(wr):
        got_q2 = k + 1
CH.answer = ans_q2
time.sleep = sl_q2
T.chk(got_q2 is not None and nB_q2[1] > 0 and recs(wr, depB_q2)[0].get("via") == "balw",
      "Q2 A 작업 20개 실패가 남은 호출을 다 써도 B 는 0콜 중단으로 차례를 잃지 않음 — 2실행째부터 매 실행 호출(작업 21개가 걸음씩 나눠 씀) → 실제 거래로(종전 = 매 실행 맨 뒤 → 영영 0콜)",
      {"cycle": got_q2, "B_calls_by_run": nB_q2, "jobs": jobs_left()})

WS7 = [B.W1, B.W2] + ["0x" + format(0xf700 + k, "040x") for k in range(12)]
c7 = B.cfg(detail_rpcs=[B.ARCH], archive_rpcs=[B.ARCH])
c7["wallets"] = [{"type": "bsc_rpc", "address": a} for a in WS7]
w, wr = fresh(wallets=WS7, c=c7)
T.chk(getattr(w, "nonce_pub_rpc", "x") is None, "B7 전제: 공개 노드 없음(상세 노드가 전부 아카이브)")
run(w, 5, sec=900, blocks=2000)
ncp7 = sum(1 for a in WS7 if isinstance(((balw_st().get("w") or {}).get(a) or {}).get("cp"), list))
T.chk(ncp7 == len(WS7), "B7 지갑 14개 — 몇 실행 안에 모두 체크포인트(종전 = 13번째 지갑에서 매번 멈춰 0개)", {"cp": ncp7, "last": balw_st().get("last")})
nb7b = CH.head + 5
dep7b = CH.native(nb7b, B.OTHER, B.W1, 2 * E18)
got7 = None
for k in range(10):
    tick(900, 2000)
    B.cycle(w)
    if dep7b in B.emitted(wr):
        got7 = k + 1
        break
T.chk(got7 is not None and len(recs(wr, dep7b)) == 1 and recs(wr, dep7b)[0].get("via") == "balw" and not reqs(),
      "B7 아카이브 전용 · 지갑 14개 — 직접 입금 회수(작업 몫 보장)", {"cycle": got7, "last": balw_st().get("last"), "req": reqs()})

ans0 = CH.answer


def pruned_arch(kind):
    def ans(url, m, p):
        if url == B.ARCH and m == "eth_getBalance" and p[1] not in ("latest", "pending") and int(p[1], 16) < CH.head - 128:
            with CH.lock:
                CH.calls[m] = CH.calls.get(m, 0) + 1
            return {"_err": {"code": -32000, "message": "missing trie node (synthetic)"}} if kind == "pruned" else None
        return ans0(url, m, p)
    return ans


for kind8 in ("pruned", "null"):
    CH.answer = pruned_arch(kind8)
    w, wr = fresh()
    run(w, 3)
    s8 = wst().get("cp", [0])[0]
    nb8 = s8 + 3
    dep8 = CH.native(nb8, B.OTHER, B.W1, 2 * E18)
    got8 = None
    for k in range(12):
        tick(90, 200)
        B.cycle(w)
        if dep8 in B.emitted(wr):
            got8 = k + 1
            break
    T.chk(got8 is not None and len(recs(wr, dep8)) == 1 and recs(wr, dep8)[0].get("via") == "balw" and not reqs(),
          f"B8 아카이브가 옛 상태 못 줌({kind8}) — 공개 노드·블록 본문 훑기로 직접 입금 회수(종전 = 작업 열린 채 실패만)",
          {"cycle": got8, "jobs": jobs_left(), "req": reqs(), "bo": balw_st().get("bo_n")})
    CH.answer = ans0

CH.answer = pruned_arch("pruned")
w, wr = fresh()
CH.native(CH.head - 400_000, B.OTHER, B.W1, 9 * E18)
run(w, 2)
common.atomic_write_json(os.path.join(common.STATE_DIR, "onchain_check.json"),
                         {"mismatches": [{"key": f"bsc:{B.W1}:native", "chain": "bsc", "wallet": B.W1, "ca": None, "sym": "BNB",
                                          "ledger": 1.0, "onchain": 10.0, "confirmed": True}]})
run(w, 2, sec=700)
q_h2a = len(reqs())
run(w, 3, sec=700)
q_h2 = reqs()
T.chk(q_h2a == 0 and len(q_h2) == 1 and q_h2[0]["sources"] == ["bsc_balance_watch_old"] and not [r for r in wr.recs if r.get("via") == "balw"],
      "H2 아카이브 상태 없음 — 두 번까지는 다음 기회 · 세 번째에 창 끝 기초 잔고 요청(옛 몫 표식) · 거짓 방출 0", {"first": q_h2a, "q": q_h2})
CH.answer = ans0

w, wr = fresh()
run(w, 3)
nb9 = CH.head - 20 + 9
many9 = [CH.native(nb9, B.OTHER, B.W1, (k + 1) * 10 ** 16) for k in range(7)]
run(w, 6, blocks=10)
T.chk(all(len(recs(wr, h)) == 1 and recs(wr, h)[0].get("via") == "balw" for h in many9) and not reqs() and jobs_left() == 0,
      "B9 한 블록 직접 입금 7건 = 7건 모두 실제 거래로 한 번씩(종전 = 5건 · 나머지 원가 미상 기초 잔고)",
      {"emitted": sum(1 for h in many9 if h in B.emitted(wr)), "req": reqs()})

bw._now = time.time
T.finish()
