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
CHK = os.path.join(common.STATE_DIR, "onchain_check.json")
W3 = "0x" + "a3" * 20
W4 = "0x" + "a4" * 20


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


def cfg_for(ws):
    c = B.cfg(archive_rpcs=[B.ARCH])
    c["wallets"] = [{"type": "bsc_rpc", "address": a} for a in ws]
    return c


def fresh(wallets=None, keep_tx=False):
    ws = wallets or [B.W1, B.W2]
    if not keep_tx:
        CH.tx.clear()
    CH.code.clear()
    CH.mode, CH.old_below, CH.arch_fail, CH.hang = None, None, None, None
    CH.bad_rc = set()
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
    w = bw.BscWatcher(cfg_for(ws), list(ws), wr)
    CH.arch_calls.clear()
    return w, wr


def mk(wr, wallets=None):
    ws = wallets or [B.W1, B.W2]
    return bw.BscWatcher(cfg_for(ws), list(ws), wr)


def ingest(wr):
    con = sqlite3.connect(common.DB_PATH)
    for r in wr.recs:
        sn = r.get("snapshot") or {}
        con.execute("INSERT OR REPLACE INTO raw_txs (chain, txhash, block, snapshot) VALUES ('bsc', ?, ?, ?)",
                    (r["txhash"].lower(), (sn.get("tx") or {}).get("block_number"), json.dumps(sn)))
    con.commit()
    con.close()


def cyc(w):
    B.cycle(w)
    ingest(w.writer.inner if hasattr(w.writer, "inner") else w.writer)


def run(w, n, sec=90, blocks=200):
    for _ in range(n):
        tick(sec, blocks)
        cyc(w)


def recs(wr, h):
    return [r for r in wr.recs if r["txhash"] == h]


def reqs():
    d = common.read_json(REQ, {}) if os.path.exists(REQ) else {}
    return list(d.get("items") or []) if isinstance(d, dict) else []


def balw_st():
    return common.read_json(BALW, {}) if os.path.exists(BALW) else {}


def wst(w9):
    return ((balw_st().get("w") or {}).get(w9)) or {}


def jobs_left():
    return sum(len((v or {}).get("jobs") or []) for v in (balw_st().get("w") or {}).values())


def mismatch(rows):
    common.atomic_write_json(CHK, {"mismatches": [{"key": f"bsc:{w9}:native", "chain": "bsc", "wallet": w9, "ca": None, "sym": "BNB",
                                                   "ledger": 1.0, "onchain": 1.0 + g9, "confirmed": True} for w9, g9 in rows]})


def day_gap(n_dep, cycles):
    w, wr = fresh()
    run(w, 3)
    cp = CH.head
    deps = [CH.native(cp + 100 + k * (190_000 // n_dep), B.OTHER, B.W1, (k + 1) * 10 ** 15) for k in range(n_dep)]
    tick(86400, 192_000)
    w = mk(wr)
    got = None
    for k in range(cycles):
        tick(90, 200)
        cyc(w)
        if got is None and all(h in B.emitted(wr) for h in deps):
            got = k + 1
    return w, wr, deps, got


w, wr, deps, got = day_gap(15, 40)
ok = [h for h in deps if len(recs(wr, h)) == 1 and recs(wr, h)[0].get("via") == "balw"]
q = [x for x in reqs() if x["wallet"] == B.W1]
T.chk(len(ok) == 15 and not q and jobs_left() == 0,
      "S2a 하루 공백 입금 15건 = 15건 모두 원래 블록의 실제 거래 · 기초 잔고 요청 0(종전 = 160콜에서 끊겨 일부만)",
      {"real": len(ok), "cycle": got, "req": [(x["block"], x["diff_raw"]) for x in q], "jobs": jobs_left()})

w, wr, deps, got = day_gap(40, 90)
ok = [h for h in deps if len(recs(wr, h)) == 1 and recs(wr, h)[0].get("via") == "balw"]
q = [x for x in reqs() if x["wallet"] == B.W1]
T.chk(len(ok) == 40 and not q and jobs_left() == 0, "S2b 하루 공백 입금 40건 = 40건 모두 실제 거래 · 요청 0",
      {"real": len(ok), "cycle": got, "req": len(q), "jobs": jobs_left()})

w, wr = fresh()
run(w, 3)
cp = CH.head
bad = CH.native(cp + 5_000, B.OTHER, B.W1, 3 * E17)
CH.bad_rc = {bad}
tick(86400, 192_000)
w = mk(wr)
run(w, 70)
q = [x for x in reqs() if x["wallet"] == B.W1]
T.chk(bad not in B.emitted(wr) and len(q) == 1 and int(q[0]["diff_raw"]) >= 3 * E17 and jobs_left() == 0,
      "S2c 진행 없는 작업 = 호출 상한(160)에서 마감 · 기초 잔고 요청 1건(금액 보존) · 작업이 끝없이 남지 않음", {"req": q, "jobs": jobs_left(), "w": wst(B.W1)})
CH.bad_rc = set()


def f1(cycles=50, restart_at=None):
    ws = [B.W1, B.W2, W3, W4]
    CH.tx.clear()
    old = CH.native(B.H0 + 300_000 - 400_000, B.OTHER, W4, 9 * E18)
    w, wr = fresh(wallets=ws, keep_tx=True)
    run(w, 3)
    mismatch([(W4, 9.0)])
    live, got, made = [], None, None
    for k in range(cycles):
        for w9 in (B.W1, B.W2, W3):
            live.append(CH.native(CH.head + 5, B.OTHER, w9, E17))
        tick(90, 200)
        if restart_at is not None and k == restart_at:
            w = mk(wr, ws)
        cyc(w)
        if made is None and any(j.get("k") == "hist" for j in wst(W4).get("jobs") or []):
            made = k + 1
        if got is None and old in B.emitted(wr):
            got = k + 1
    return w, wr, old, live, got, made


w, wr, old, live, got, made = f1()
print(f"[F1] 과거 복구 작업 생성 = {made}주기 · 9 BNB 회수 = {got}주기 · 남은 작업 {jobs_left()} · 요청 {len(reqs())}"
      f" · 최신 입금 {len(live)}건 중 실제 거래 {sum(1 for h in live if h in B.emitted(wr))}건")
T.chk(got is not None and len(recs(wr, old)) == 1 and recs(wr, old)[0].get("via") == "balw",
      "F1 지속 유입(3지갑 × 90초) 하에서도 과거 9 BNB 가 50주기 안에 실제 거래로 회수(종전 = 75분 동안 과거 복구 작업 자체를 못 만듦)",
      {"cycle": got, "job_made": made, "w4": {k9: v9 for k9, v9 in wst(W4).items() if k9 != "cp"}, "jobs": jobs_left()})
cur = B.cur()
T.chk(int(cur.get("from_block") or 0) >= CH.head - 400, "F1 최신 커서는 계속 전진(헤드 근처)", {"from": cur.get("from_block"), "head": CH.head})
T.chk(sum(1 for h in live if h in B.emitted(wr)) >= len(live) // 3,
      "F1 최신 입금도 계속 실제 거래로(넘친 몫은 작업 상한에서 정직한 마감)", {"live": len(live), "emitted": sum(1 for h in live if h in B.emitted(wr)), "req": len(reqs())})
run(w, 60)


def conserved(w9, b0):
    em = 0
    seen = {}
    for r in wr.recs:
        seen[r["txhash"]] = r["snapshot"]
    for sn in seen.values():
        if bw._touches(sn, w9) and int((sn.get("tx") or {}).get("block_number") or 0) > b0:
            em += int(bw._native_delta(sn, w9)[0])
    rq = sum(int(x["diff_raw"]) for x in reqs() if x["wallet"] == w9)
    return em + rq, CH.balance(w9, CH.head) - CH.balance(w9, b0)


b0 = B.H0 + 300_000 + 3 * 200
cs = {w9[:6]: conserved(w9, b0) for w9 in (B.W1, B.W2, W3)}
T.chk(jobs_left() == 0 and all(a == b for a, b in cs.values()),
      "F1 유입이 멈춘 뒤 작업 0 · 지갑마다 (실제 거래 + 기초 잔고 요청) = 체인 증가(넘침 마감에서도 금액 유실 0)", {"cons": cs, "jobs": jobs_left()})

def f4(busy_others, cycles=50):
    ws = [B.W1, B.W2, W3, W4]
    CH.tx.clear()
    old = CH.native(B.H0 + 300_000 - 400_000, B.OTHER, W4, 9 * E18)
    w, wr = fresh(wallets=ws, keep_tx=True)
    run(w, 3)
    mismatch([(W4, 9.0)])
    live, got, made = [], None, None
    for k in range(cycles):
        for w9 in ((B.W1, B.W2, W3, W4) if busy_others else (W4,)):
            live.append((w9, CH.native(CH.head + 5, B.OTHER, w9, E17)))
        tick(90, 200)
        cyc(w)
        if made is None and any(j.get("k") == "hist" for j in wst(W4).get("jobs") or []):
            made = k + 1
        if got is None and old in B.emitted(wr):
            got = k + 1
    return w, wr, old, live, got, made


for busy in (False, True):
    w, wr, old, live, got, made = f4(busy)
    lw4 = [h for w9, h in live if w9 == W4]
    ws4 = (B.W1, B.W2, W3, W4) if busy else (W4,)
    per = {w9[:6]: sum(1 for w8, h in live if w8 == w9 and h in B.emitted(wr)) for w9 in ws4}
    print(f"[F4{'b' if busy else 'a'}] 과거 복구 작업 생성 = {made}주기 · 9 BNB 회수 = {got}주기 · 지갑별 최신 입금 실제 거래 {per}(지갑당 {len(lw4)}건)")
    T.chk(got is not None and len(recs(wr, old)) == 1 and recs(wr, old)[0].get("via") == "balw",
          f"F4{'b 4지갑 모두' if busy else 'a W4 만'} 지속 유입 — 과거 누락 지갑 자신에게 최신 입금이 계속 와도 9 BNB 가 50주기 안에 실제 거래로 회수",
          {"cycle": got, "job_made": made, "w4": {k9: v9 for k9, v9 in wst(W4).items() if k9 not in ("cp",)}})
    T.chk(int(B.cur().get("from_block") or 0) >= CH.head - 400 and sum(1 for h in lw4[:-3] if h in B.emitted(wr)) >= len(lw4[:-3]) // (4 if busy else 1),
          f"F4{'b' if busy else 'a'} 최신 커서 전진 · W4 최신 입금도 계속 실제 거래로({'과부하 — 4건 중 1건 이상' if busy else '전부'})",
          {"from": B.cur().get("from_block"), "head": CH.head, "per": per})
    run(w, 60)
    b0 = B.H0 + 300_000 + 3 * 200
    cs = {}
    for w9 in ((B.W1, B.W2, W3, W4) if busy else (W4,)):
        seen = {}
        for r in wr.recs:
            seen[r["txhash"]] = r["snapshot"]
        em = sum(int(bw._native_delta(sn, w9)[0]) for sn in seen.values()
                 if bw._touches(sn, w9) and int((sn.get("tx") or {}).get("block_number") or 0) > b0)
        rq = sum(int(x["diff_raw"]) for x in reqs() if x["wallet"] == w9 and int(x["block"]) > b0)
        cs[w9[:6]] = (em + rq, CH.balance(w9, CH.head) - CH.balance(w9, b0))
    T.chk(jobs_left() == 0 and all(a == b for a, b in cs.values()) and len(recs(wr, old)) == 1,
          f"F4{'b' if busy else 'a'} 유입이 멈춘 뒤 작업 0 · 체크포인트 뒤 (실제 거래 + 요청) = 체인 증가 · 과거 입금 중복 0", {"cons": cs, "jobs": jobs_left()})

CH.tx.clear()
old2 = CH.native(B.H0 + 300_000 - 400_000, B.OTHER, B.W2, 2 * E18)
w, wr = fresh(keep_tx=True)
run(w, 3)
mismatch([(B.W2, 2.0)])
st2 = w._balw_load()
h0 = st2["w"][B.W2].get("hist_at")
cnt2 = {"n": bw.BALW_CALL_CAP, "emit": 0, "jobs": 0, "halt": None, "head": CH.head, "t_end": time.time() + 10}
try:
    w._balw_hist(st2, [B.W1, B.W2], cnt2)
    stop2 = None
except bw._BalwStop as e:
    stop2 = str(e)
ws2 = st2["w"][B.W2]
T.chk(stop2 is not None and ws2.get("hist_at") == h0 and isinstance(ws2.get("hist_wait"), int) and not ws2.get("jobs"),
      "F2 실행 몫이 없어 못 돈 초기화 = hist_at 그대로(다음 실행 바로 차례) · 대기 시작 표시(hist_wait)",
      {"stop": stop2, "hist_at": (h0, ws2.get("hist_at")), "wait": ws2.get("hist_wait")})
cnt2 = {"n": 0, "emit": 0, "jobs": 0, "halt": None, "head": CH.head, "t_end": time.time() + 10}
w._balw_hist(st2, [B.W1, B.W2], cnt2)
T.chk(any(j.get("k") == "hist" for j in ws2.get("jobs") or []) and ws2.get("hist_at") == int(clk[0]) and "hist_wait" not in ws2,
      "F2 몫이 생기면 바로 초기화(작업 생성) · hist_at = 지금 · 대기 표시 지움", {"w": {k9: v9 for k9, v9 in ws2.items() if k9 not in ("cp", "jobs")}})
st2["w"][B.W2]["hist_wait"] = int(clk[0])
common.atomic_write_json(CHK, {"mismatches": []})
w._balw_hist_cands(st2, [B.W1, B.W2], clk[0])
T.chk("hist_wait" not in st2["w"][B.W2], "F2 대조 부족이 풀리면 대기 표시도 지움", {k9: v9 for k9, v9 in st2["w"][B.W2].items() if k9 not in ("cp", "jobs")})
w._balw_st = None
w, wr = fresh(keep_tx=True)
run(w, 3)
mismatch([(B.W2, 2.0)])
st2 = w._balw_load()
ans2 = CH.answer
CH.answer = lambda url, m, p: ({"_err": {"code": -32603, "message": "internal error (synthetic)"}}
                               if url == B.ARCH and m == "eth_getBalance" and p[1] not in ("latest", "pending") else ans2(url, m, p))
cnt2 = {"n": 0, "emit": 0, "jobs": 0, "halt": None, "head": CH.head, "t_end": time.time() + 10}
try:
    w._balw_hist(st2, [B.W1, B.W2], cnt2)
except Exception:
    pass
CH.answer = ans2
ws2 = st2["w"][B.W2]
T.chk(ws2.get("hist_at") == int(clk[0] - bw.BALW_HIST_GAP + bw.BALW_HIST_RETRY) and not ws2.get("jobs"),
      "F2 실제 조회 실패(아카이브 오류) = 짧게 뒤 다시(BALW_HIST_RETRY)", {"hist_at": ws2.get("hist_at"), "now": clk[0]})

ws3 = [B.W1, B.W2, W3, W4]
CH.tx.clear()
olds = {w9: CH.native(B.H0 + 300_000 - 400_000 + k, B.OTHER, w9, (k + 1) * E18) for k, w9 in enumerate((B.W2, W3, W4))}
w, wr = fresh(wallets=ws3, keep_tx=True)
run(w, 3)
st3 = w._balw_load()
st3["w"][W4]["hist_at"] = int(clk[0]) - 5 * 86400
st3["w"][W3]["hist_at"] = int(clk[0]) - 3 * 86400
st3["w"][B.W2]["hist_at"] = int(clk[0]) - 2 * 86400
w._balw_save()
mismatch([(B.W2, 1.0), (W3, 2.0), (W4, 3.0)])
order = []
for k in range(3):
    if k == 1:
        w = mk(wr, ws3)
    before = {w9 for w9 in (B.W2, W3, W4) if any(j.get("k") == "hist" for j in wst(w9).get("jobs") or []) or w9 in order}
    run(w, 1)
    new = [w9 for w9 in (B.W2, W3, W4) if w9 not in before and (any(j.get("k") == "hist" for j in wst(w9).get("jobs") or [])
                                                                  or olds[w9] in B.emitted(wr))]
    order.append(new[0] if len(new) == 1 else tuple(new))
T.chk(order == [W4, W3, B.W2], "F3 실행당 초기화 1건 · 가장 오래 기다린 지갑부터(W4 → W3 → W2) · 재시작 뒤에도 차례 유지",
      [o[:6] if isinstance(o, str) else o for o in order])
run(w, 40)
T.chk(all(len(recs(wr, h)) == 1 for h in olds.values()) and not reqs() and jobs_left() == 0, "F3 세 지갑 지난 누락 모두 실제 거래 한 번씩 · 요청 0",
      {w9[:6]: len(recs(wr, h)) for w9, h in olds.items()})

T.finish()
