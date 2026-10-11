#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _ingest
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
OTHER2 = "0x" + "b3" * 20
EOA9 = "0x" + "b4" * 20


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


def fresh():
    CH.tx.clear()
    CH.code.clear()
    CH.mode, CH.old_below, CH.arch_fail, CH.hang = None, None, None, None
    CH.head = B.H0 + 300_000
    CH.bal0 = {B.W1: 10 * E18, B.W2: 10 * E18}
    CH.prune = 128
    CH.native(CH.head - 5_000, B.W1, B.OTHER, 10 ** 15)
    B.reset_state()
    gates_reset()
    setup_db()
    common.atomic_write_json(B.CPATH, {"from_block": CH.head - 30, "head": CH.head - 10, "_cov": B.WIN_BLK, "_bf_start": B.WIN_BLK,
                                       "_wallets": sorted([B.W1, B.W2])})
    wr = B.Wr()
    wr_cur[0] = wr
    w = bw.BscWatcher(B.cfg(archive_rpcs=[B.ARCH]), [B.W1, B.W2], wr)
    CH.arch_calls.clear()
    return w, wr


wr_cur = [None]


def ingest(wr):
    con = sqlite3.connect(common.DB_PATH)
    for r in wr.recs:
        sn = r.get("snapshot") or {}
        con.execute("INSERT OR REPLACE INTO raw_txs (chain, txhash, block, snapshot) VALUES ('bsc', ?, ?, ?)",
                    (r["txhash"].lower(), (sn.get("tx") or {}).get("block_number"), json.dumps(sn)))
    con.commit()
    con.close()


def run(w, n, sec=90, blocks=200, eat=True):
    for _ in range(n):
        tick(sec, blocks)
        B.cycle(w)
        if eat:
            ingest(wr_cur[0])


def recs(wr, h):
    return [r for r in wr.recs if r["txhash"] == h]


def reqs():
    d = common.read_json(REQ, {}) if os.path.exists(REQ) else {}
    return list(d.get("items") or []) if isinstance(d, dict) else []


def balw_st():
    return common.read_json(BALW, {}) if os.path.exists(BALW) else {}


def jobs_left():
    return sum(len((v or {}).get("jobs") or []) for v in (balw_st().get("w") or {}).values())


def bd_legs(wr):
    return [(r["txhash"][-6:], i.get("from"), i.get("to"), i.get("value")) for r in wr.recs
            for i in (r["snapshot"].get("internal") or []) if i.get("attr") == "balance_delta"]


def last_snap(wr):
    out = {}
    for r in wr.recs:
        out[r["txhash"]] = r["snapshot"]
    return out


def explained(wr, w9, blk):
    em = 0
    for sn in last_snap(wr).values():
        if (sn.get("tx") or {}).get("block_number") == blk and bw._touches(sn, w9):
            em += int(bw._native_delta(sn, w9)[0])
    rq = sum(int(q["diff_raw"]) for q in reqs() if q["wallet"] == w9 and q["block"] == blk)
    return em, rq


def chain_d(w9, blk):
    return CH.balance(w9, blk) - CH.balance(w9, blk - 1)


def same_block(direct_v, int_v, mention=False, eat=True):
    w, wr = fresh()
    run(w, 3)
    nb = CH.head + 5
    d = CH.native(nb, B.OTHER, B.W1, direct_v)
    s = CH.internal(nb, OTHER2, B.ROUTER, B.W1, int_v, mention=mention)
    run(w, 8, eat=eat)
    return w, wr, nb, d, s


w, wr, nb, d1, s1 = same_block(E18, 2 * E17)
em, rq = explained(wr, B.W1, nb)
T.chk(len(recs(wr, d1)) == 1 and recs(wr, d1)[0].get("via") == "balw" and recs(wr, d1)[0]["snapshot"]["tx"]["value"] == str(E18),
      "A1 직접 입금 1 BNB = 실제 거래 정확히 1건(via balw)", [(r.get("via"), r["snapshot"]["tx"].get("value")) for r in recs(wr, d1)])
T.chk(not [x for x in bd_legs(wr) if str(x[1]).lower() == str(x[2]).lower()], "A1 W1→W1 가짜 귀속 leg 0(순증 0 이 되는 귀속 없음)", bd_legs(wr))
T.chk(not [x for x in bd_legs(wr) if x[0] == d1[-6:]], "A1 남는 0.2 를 방금 회수한 직접 입금 tx 에 붙이지 않음", bd_legs(wr))
T.chk(em + rq == chain_d(B.W1, nb) == 12 * E17 and rq == 2 * E17,
      "A1 블록 증가 1.2 = 방출 1 + 그 블록 기초 잔고 요청 0.2(관측 복구 — 버리고 완료하지 않음)", {"emitted": em, "req": rq, "chain": chain_d(B.W1, nb),
                                                                                 "reqs": reqs(), "jobs": jobs_left()})
q1 = [q for q in reqs() if q["block"] == nb]
T.chk(len(q1) == 1 and q1[0]["ca"] is None and q1[0]["chain_bal_raw"] == str(CH.balance(B.W1, nb)) and q1[0]["sources"] == ["bsc_balance_watch"]
      and s1 not in B.emitted(wr) and jobs_left() == 0,
      "A1 요청 = 네이티브 · 그 블록 잔고 · 출처 '잔고 감시'(실제 거래처럼 표시 안 함) · 단서 없는 tx 방출 0 · 남은 작업 0", {"q": q1, "jobs": jobs_left()})
A1_STATE = (list(wr.recs), reqs(), nb, d1, CH.balance(B.W1, nb - 1), CH.balance(B.W1, nb), CH.ts(nb))

n8, q8 = len(wr.recs), len(reqs())
w8 = bw.BscWatcher(B.cfg(archive_rpcs=[B.ARCH]), [B.W1, B.W2], wr)
run(w8, 6)
T.chk(len(wr.recs) == n8 and len(reqs()) == q8 and len(recs(wr, d1)) == 1, "A8 재시작 뒤 여러 주기 — 방출·요청 다시 0(직접 입금 중복 0)",
      {"recs": (n8, len(wr.recs)), "req": (q8, len(reqs()))})

w, wr, nb, d2, s2 = same_block(33 * 10 ** 15, 39 * 10 ** 15)
em, rq = explained(wr, B.W1, nb)
T.chk(len(recs(wr, d2)) == 1 and em + rq == chain_d(B.W1, nb) == 72 * 10 ** 15 and rq == 39 * 10 ** 15
      and not [x for x in bd_legs(wr) if str(x[1]).lower() == str(x[2]).lower()],
      "A2 원장 순증(방출 0.033 + 요청 0.039) = 체인 순증 0.072 · 0.039 소실 0 · 가짜 W→W 0", {"emitted": em, "req": rq, "bd": bd_legs(wr)})

w, wr, nb, d3, s3 = same_block(E18, 2 * E17, mention=True)
bd3 = [x for x in bd_legs(wr) if x[0] == s3[-6:]]
em, rq = explained(wr, B.W1, nb)
T.chk(len(recs(wr, d3)) == 1 and len(bd3) == 1 and bd3[0][1] == B.ROUTER and bd3[0][3] == str(2 * E17) and not reqs()
      and em == chain_d(B.W1, nb),
      "A3 로그 단서가 있으면 internal 은 그 tx 에 귀속(보낸 쪽 = 컨트랙트 0.2) · 직접 입금 1건 · 요청 0", {"bd": bd_legs(wr), "req": reqs(), "em": em})

w, wr = fresh()
run(w, 3)
nb = CH.head + 5
pay4 = CH.internal(nb, B.W1, B.ROUTER, B.W1, 2 * E18)
d4 = CH.native(nb, B.OTHER, B.W1, E18)
run(w, 8)
bd4 = [x for x in bd_legs(wr) if x[0] == pay4[-6:]]
em, rq = explained(wr, B.W1, nb)
T.chk(len(recs(wr, d4)) == 1 and len(bd4) == 1 and bd4[0][1] == B.ROUTER and bd4[0][3] == str(2 * E18)
      and not [x for x in bd_legs(wr) if x[0] == d4[-6:]] and not reqs() and em == chain_d(B.W1, nb),
      "A4 환급은 내 컨트랙트 호출 tx 에 귀속 · 직접 입금은 후보 아님 · 요청 0 · 순증 일치", {"bd": bd_legs(wr), "req": reqs(), "em": em, "chain": chain_d(B.W1, nb)})

w, wr = fresh()
run(w, 3)
nb = CH.head + 5
mv5 = CH.native(nb, B.W2, B.W1, E18)
s5 = CH.internal(nb, OTHER2, B.ROUTER, B.W1, 3 * E17)
run(w, 8)
em1, rq1 = explained(wr, B.W1, nb)
em2, rq2 = explained(wr, B.W2, nb)
T.chk(not bd_legs(wr) and em1 + rq1 == chain_d(B.W1, nb) and rq1 == 3 * E17 and em2 == chain_d(B.W2, nb) and rq2 == 0,
      "A5 내 지갑끼리 tx 에 귀속 안 함(W1→W1 0 · W2 차감 0) · 0.3 = 요청 · 두 지갑 순증 일치",
      {"bd": bd_legs(wr), "w1": (em1, rq1, chain_d(B.W1, nb)), "w2": (em2, rq2, chain_d(B.W2, nb))})

w, wr = fresh()
run(w, 3)
nb = CH.head + 5
snd6 = CH.native(nb, B.W1, EOA9, E17)
s6 = CH.internal(nb, OTHER2, B.ROUTER, B.W1, 4 * E17)
run(w, 8)
em, rq = explained(wr, B.W1, nb)
T.chk(not [x for x in bd_legs(wr) if x[0] == snd6[-6:]] and rq == 4 * E17 and em + rq == chain_d(B.W1, nb),
      "A6 코드를 안 도는 송금(받는 쪽 EOA)에 internal 붙이지 않음 · 0.4 = 요청 · 순증 일치", {"bd": bd_legs(wr), "em": em, "rq": rq, "chain": chain_d(B.W1, nb)})

w, wr = fresh()
run(w, 3)
nb = CH.head + 5
s7 = CH.internal(nb, OTHER2, B.ROUTER, B.W1, 5 * E17, mention=True)
fd0 = bw.BscWatcher.fetch_details


def fd7(self, hashes, deadline=None):
    out = fd0(self, hashes, deadline=deadline)
    sn = out.get(s7)
    if isinstance(sn, dict):
        out[s7] = dict(sn, tx=dict(sn["tx"], to=B.W1))
    return out


bw.BscWatcher.fetch_details = fd7
run(w, 8)
bw.BscWatcher.fetch_details = fd0
em, rq = explained(wr, B.W1, nb)
T.chk(not [x for x in bd_legs(wr) if str(x[1]).lower() == str(x[2]).lower()] and em + rq == chain_d(B.W1, nb) and rq == 5 * E17,
      "A7 귀속해도 순증이 안 바뀌는 경우 = 귀속 안 하고 잔여 0.5 를 요청(완료로 덮지 않음)", {"bd": bd_legs(wr), "em": em, "rq": rq})

w, wr, nb, d9, s9 = same_block(E17, 5 * 10 ** 13)
em, rq = explained(wr, B.W1, nb)
T.chk(len(recs(wr, d9)) == 1 and rq == 5 * 10 ** 13 and em + rq == chain_d(B.W1, nb),
      "A9 0.00005 BNB internal(대조 문턱 아래)도 요청으로 남음 · 직접 입금 1건", {"em": em, "rq": rq, "reqs": reqs()})

w, wr = fresh()
run(w, 3)
nb = CH.head + 5
c1 = CH.internal(nb, B.W1, B.ROUTER, B.OTHER, 10 ** 15)
c2 = CH.internal(nb, B.W1, B.TK, B.OTHER, 10 ** 15)
s10 = CH.internal(nb, OTHER2, B.USD, B.W1, 6 * E17)
run(w, 8)
em, rq = explained(wr, B.W1, nb)
T.chk(not bd_legs(wr) and rq == 6 * E17 and em + rq == chain_d(B.W1, nb),
      "A10 후보가 여럿(내 컨트랙트 호출 2건) = 특정 tx 에 붙이지 않고 0.6 요청 · 순증 일치", {"bd": bd_legs(wr), "em": em, "rq": rq, "chain": chain_d(B.W1, nb)})

w, wr = fresh()
run(w, 3)
nb = CH.head + 5
pay11 = CH.internal(nb, B.W1, B.ROUTER, B.W1, 2 * E18)
ans11 = CH.answer
CH.answer = lambda url, m, p: ({"_err": {"code": -32603, "message": "internal error (synthetic)"}} if m == "eth_getCode" and str(p[0]).lower() == B.ROUTER
                               else ans11(url, m, p))
run(w, 4)
q11 = reqs()
T.chk(not bd_legs(wr) and not q11 and jobs_left() == 1, "A11 코드 확인 실패 동안 = 작업 유지(요청·귀속 0)", {"req": q11, "jobs": jobs_left(), "bd": bd_legs(wr)})
CH.answer = ans11
run(w, 4)
bd11 = [x for x in bd_legs(wr) if x[0] == pay11[-6:]]
T.chk(len(bd11) == 1 and bd11[0][3] == str(2 * E18) and not reqs() and jobs_left() == 0, "A11 회복 뒤 환급 귀속 1 · 요청 0", {"bd": bd_legs(wr), "req": reqs()})

w, wr, nb, d12, s12 = same_block(E18, 2 * E17, eat=False)
pq12 = balw_st().get("rqp") or []
T.chk(not reqs() and len(pq12) == 1 and pq12[0]["aft"] == [d12] and pq12[0]["it"]["block"] == nb and pq12[0]["it"]["diff_raw"] == str(2 * E17),
      "A12 core 가 직접 입금을 원장에 넣기 전 = 요청 파일에 안 씀(상태에 보류 · 기다리는 거래 = 그 직접 입금)", {"req": reqs(), "rqp": pq12})
ingest(wr)
run(w, 1, eat=False)
q12 = reqs()
T.chk(len(q12) == 1 and q12[0]["block"] == nb and q12[0]["diff_raw"] == str(2 * E17) and not balw_st().get("rqp"),
      "A12 직접 입금이 원장에 들어간 다음 주기 = 요청 0.2 씀 · 보류 비움", {"req": q12, "rqp": balw_st().get("rqp")})
w, wr, nb, d12b, s12b = same_block(E18, 2 * E17, eat=False)
run(w, 2, sec=getattr(bw, "BALW_REQ_WAIT", 21600) // 2 + 60, blocks=200, eat=False)
T.chk(len(reqs()) == 1 and reqs()[0]["block"] == nb and not balw_st().get("rqp"), "A12 상한(BALW_REQ_WAIT) 지나면 원장 반영 없이도 씀(무한 보류 없음)",
      {"req": reqs(), "rqp": balw_st().get("rqp")})
w, wr, nb, d12c, s12c = same_block(E18, 2 * E17, eat=False)
w = bw.BscWatcher(B.cfg(archive_rpcs=[B.ARCH]), [B.W1, B.W2], wr)
ingest(wr)
run(w, 2, eat=False)
T.chk(len(reqs()) == 1 and reqs()[0]["block"] == nb and not balw_st().get("rqp"), "A12 재시작 뒤에도 보류한 요청이 이어져 원장 반영 뒤 씀",
      {"req": reqs(), "rqp": balw_st().get("rqp")})

recs1, reqs1, nb1, d1, bal_before, bal_after, ts1 = A1_STATE
OFF = ts1 - (int(time.time()) - 86400)
for p9 in (common.DB_PATH, common.DB_PATH + "-wal", common.DB_PATH + "-shm"):
    if os.path.exists(p9):
        os.remove(p9)
import core
import discopen
cfg_c = json.loads(json.dumps(_ingest.CFG))
cfg_c["wallets"] = [{"type": "bsc_rpc", "chain": "bsc", "address": B.W1}]
cfg_c["bsc"] = {"detail_rpcs": ["https://bscrpc.invalid"], "logs_rpcs": []}
cfg_c.setdefault("native_symbol", {})["bsc"] = "BNB"
json.dump(cfg_c, open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8"))
core.dm = lambda *a, **k: None
T0 = int(time.time()) - 20 * 86400
common.atomic_write_json(B.CPATH, {"from_block": nb1 + 50, "head": nb1 + 70, "_cov": 100, "_bf_start": 100, "_wallets": [B.W1],
                                   "_synced_at": int(time.time()) + 3600})
c = core.Core(common.load_config())
c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('recon_done_bsc', ?)", (str(T0),))
c.conn.execute("INSERT OR REPLACE INTO raw_observations (obs_id, kind, venue, payload, observed_at) VALUES (?,?,?,?,?)",
               ("recon:bsc", "opening_balance", "bsc", json.dumps({B.W1: {"native:None": 0}}), T0))
c.conn.commit()


def bnb(cc):
    r = cc.conn.execute("SELECT asset_id FROM assets WHERE kind='native' AND chain='bsc'").fetchone()
    return sum(int(x[0]) for x in cc.conn.execute("SELECT qty_base FROM postings WHERE location=? AND asset_id=?", (f"wallet:bsc:{B.W1}", r[0]))) if r else 0


def feed(cc, rs):
    out = []
    for r in rs:
        r2 = json.loads(json.dumps(r))
        r2["snapshot"]["tx"]["timestamp"] = int(r2["snapshot"]["tx"]["timestamp"]) - OFF
        r2["wallets"] = [B.W1]
        out.append(r2)
    cc._drain_stream("bsc", _ingest.Reader(out), 0, 0)
    cc.conn.commit()


def pump(cc, n=30):
    for _ in range(n):
        r = cc._negabs_runner()
        r.last = 0.0
        cc.negabs_pass()
        if not r.jobs:
            return
        time.sleep(0.02)


b0 = bnb(c)
feed(c, [r for r in recs1 if (r["snapshot"].get("tx") or {}).get("block_number") == nb1])
items = []
for q in reqs1:
    if q["block"] == nb1:
        q2 = dict(q, block_ts=int(q["block_ts"]) - OFF, chain_bal_raw=str(int(q["chain_bal_raw"]) - bal_before))
        items.append(q2)
common.atomic_write_json(os.path.join(common.STATE_DIR, discopen.RECHK_REQ_NAME), {"items": items, "by": "시험", "ts": int(time.time())})
pump(c)
got = bnb(c)
T.chk(got - b0 == bal_after - bal_before == 12 * E17,
      "C1 진짜 Core: 방출(직접 1) + 기초 잔고 요청(0.2) → W1 BNB 원장 +1.2 = 체인 증가(0.2 버려지지 않음)", {"ledger_d": got - b0, "chain_d": bal_after - bal_before})
feed(c, [r for r in recs1 if (r["snapshot"].get("tx") or {}).get("block_number") == nb1])
common.atomic_write_json(os.path.join(common.STATE_DIR, discopen.RECHK_REQ_NAME), {"items": items, "by": "시험", "ts": int(time.time())})
pump(c)
T.chk(bnb(c) == got, "C1 같은 방출·요청 다시 = 무변(중복 계상 0)", bnb(c) - got)

T.finish()
