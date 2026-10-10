#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import time

CH = "zerog"
NEW = "0x" + "e1" * 20
OLD = ["0x" + f"{0xa0 + i:02x}" * 20 for i in range(5)]
ALL = OLD + [NEW]
CFG = {"backfill_months": 0, "chains": {CH: {"discovery": "rpc", "chain_id": 16661, "rpcs": ["http://127.0.0.1:9/rpc"], "getlogs_span": 10_000,
                                             "conf_depth": 10, "blocks_per_day": 1440, "poll_sec": 60, "cycle_budget_sec": 15}},
       "wallets": [{"type": "evm", "chain": CH, "address": w, "label": "w"} for w in ALL]}
with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump(CFG, f)
import common
import bf_engine
import evm_watch

bf_engine.configure(CFG)
CPATH = os.path.join(common.STATE_DIR, f"cursor_evm_{CH}.json")
SPATH = os.path.join(common.STATE_DIR, bf_engine.STATUS_FILE)


class Wr:
    def append(self, rec):
        pass


def job(frm, done, to, why="internal"):
    return {"from": frm, "done": done, "to": to, "why": why}


def make(cursor, span=2000, bk_span=2000):
    bf_engine._PROGRESS.clear()
    cur = {"_rpc_v": 1, "_start": 0}
    cur.update({w: 900_000 for w in ALL})
    cur.update(cursor)
    cur.setdefault("_bkspan", span)
    common.atomic_write_json(CPATH, cur)
    w = evm_watch.RpcChainWatcher(CFG, CH, list(ALL), Wr())
    w.bk_span = bk_span
    w.multicall = None
    calls = []

    def scan(ws, c, target, deadline):
        calls.append((tuple(sorted(ws)), int(c), int(target)))
        return {}, int(target), None
    w._scan_logs = scan
    w._states = lambda *a, **k: None
    w._native = lambda wa, c, last, pool, dl, nk=None, **k: {"ns": [int(last), 0, "0"]}
    return w, calls


def segs(w, calls):
    return [(c, t) for _ws, c, t in calls]


def overlap(iv):
    pts = sorted([(c, 1) for c, t in iv] + [(t, -1) for c, t in iv], key=lambda x: (x[0], x[1]))
    n, prev, cov = 0, None, 0
    for x, d in pts:
        if prev is not None and cov >= 2:
            n += x - prev
        cov += d
        prev = x
    return n


def run(w):
    return T.safe(w._bk_step, 10 ** 7, time.time() + 60)


cur = {"_bk:" + a: job(0, 5000, 20_000) for a in OLD}
cur["_bk:" + NEW] = job(0, 0, 20_000, "new")
w, calls = make(cur)
r = run(w)
iv = segs(w, calls)
T.chk(not isinstance(r, dict) and not w._bk_jobs(), "M1 뒤 차선 전부 완주(일 0)", {"r": r, "left": w._bk_jobs()})
T.chk(overlap(iv) == 0, "M1 같은 블록을 두 번 훑지 않음(종전: 두 묶음이 번갈아 앞서며 남은 구간을 두 번)", {"overlap": overlap(iv), "calls": calls[:12]})
T.chk(sum(t - c for c, t in iv) == 20_000, "M1 훑은 블록 합 = 차선 길이 20,000(종전 ≈35,000)", sum(t - c for c, t in iv))
T.chk(any(c == 4000 and t == 5000 and ws == (NEW,) for ws, c, t in calls), "M1 새 지갑 마지막 혼자 걸음이 묶음 진행점 5,000 에서 멈춤", calls[:4])
T.chk(any(ws == tuple(sorted(ALL)) and c == 5000 for ws, c, t in calls), "M1 진행점 5,000 부터 6지갑 한 묶음(getLogs 한 번에)", calls[:6])
T.chk(all(len(ws) == 6 for ws, c, t in calls if c >= 5000), "M1 합친 뒤엔 끝까지 한 묶음", [x for x in calls if x[1] >= 5000][:4])

cur = {"_bk:" + a: job(0, 6000, 12_000) for a in OLD}
cur["_bk:" + NEW] = job(0, 0, 15_000, "new")
w, calls = make(cur)
r = run(w)
iv = segs(w, calls)
T.chk(not w._bk_jobs() and overlap(iv) == 0 and sum(t - c for c, t in iv) == 15_000,
      "M2 끝이 다른 묶음 — 완주 · 겹침 0 · 합 15,000", {"left": w._bk_jobs(), "overlap": overlap(iv), "calls": calls})
T.chk([ws for ws, c, t in calls if c >= 12_000] and all(ws == (NEW,) for ws, c, t in calls if c >= 12_000),
      "M2 먼저 끝난 지갑은 빠지고 새 지갑 혼자 12,000 → 15,000", calls[-3:])

cur = {"_bk:" + a: job(0, 5000, 20_000) for a in OLD}
cur["_bk:" + NEW] = job(0, 4000, 20_000, "new")
cur["_bkscan"] = {"frm": 4001, "to": 6000, "ws": [NEW], "found": {}}
cur["_bkns"] = {NEW: [4000, 0, "0"]}
w, calls = make(cur)
r = run(w)
iv = [(4000, 6000)] + segs(w, calls)
T.chk(not isinstance(r, dict) and not w._bk_jobs(), "M3 옛 커서 파일로 기동 → 예외 없이 완주", {"r": r, "left": w._bk_jobs()})
T.chk(calls and calls[0] == (tuple(sorted(OLD)), 5000, 6000), "M3 체크포인트로 지나친 뒤 뒤처진 묶음이 6,000 에서 멈춤", calls[:3])
T.chk(overlap(iv) <= 2000 and all(len(ws) == 6 for ws, c, t in calls[1:]),
      "M3 겹침 ≤ 체크포인트 한 구간 · 그 뒤 한 묶음", {"overlap": overlap(iv), "calls": calls[:4]})

cur = {"_bk:" + a: job(0, 5000, 20_000) for a in ALL}
w, calls = make(cur, span=16_000, bk_span=200_000)
w._scan_logs = lambda ws, c, target, dl: ({}, int(c), None)
r = run(w)
T.chk(r == (0, True) and w.cursor.get("_bkspan") == 8000 and all(int(j["done"]) == 5000 for j in w._bk_jobs().values()),
      "M4 전진 없음 = (0, 정지) · 구간 16,000 → 8,000 저장 · 진행점 그대로(종전)", {"r": r, "span": w.cursor.get("_bkspan")})
cur = {"_bk:" + a: job(0, 1000, 60_000) for a in OLD}
cur["_bk:" + NEW] = job(0, 0, 60_000, "new")
w, calls = make(cur, span=16_000, bk_span=200_000)
r = run(w)
sz = [t - c for ws, c, t in calls]
T.chk(sz[:3] == [1000, 16_000, 32_000], "M4 합치려고 끊은 걸음(1,000) 뒤 구간 16,000 그대로 · 보통 걸음 뒤엔 2배(종전)", sz)

jobs = {a: job(0, 5000, 20_000) for a in OLD}
jobs[NEW] = job(0, 1000, 21_000, "new")
lane = T.safe(evm_watch.RpcChainWatcher._bk_lane, jobs)
T.chk(lane == (1000, 21_000), "M5 차선 블록 = (전진 1,000 · 전체 21,000) — 지갑별 합(21,000+5×20,000)이 아님", lane)
old_left = sum(j["to"] - j["done"] for j in jobs.values())
T.chk(isinstance(lane, tuple) and (lane[1] - lane[0]) / 100 == 200 and old_left / 100 == 950, "M5 남은 시간 200초(종전 식 950초 — 지갑 수만큼 부풂)",
      {"lane": lane, "old_left": old_left})
T.chk(T.safe(evm_watch.RpcChainWatcher._bk_lane, {NEW: job(0, 0, 0)}) == (0, 1), "M5 빈 구간 = (0, 1)(나눗셈 0 없음)")
lane2 = T.safe(evm_watch.RpcChainWatcher._bk_lane, {OLD[0]: job(100, 50, 200), OLD[1]: job(300, 400, 500)})
T.chk(lane2 == (100, 300), "M5 진행점이 시작보다 앞(깨진 값) = 시작으로 · 떨어진 구간은 따로 셈(전체 100+200 · 남은 100+100)", lane2)
w, calls = make({**{"_bk:" + a: job(0, 5000, 20_000) for a in OLD}, "_bk:" + NEW: job(0, 1000, 21_000, "new")})
it = (common.read_json(SPATH, {}).get("evm") or {}).get(f"{CH}:rpc") or {}
T.chk(it.get("phase") == "extend" and it.get("done") == 1000 and it.get("total") == 21_000, "M5 재기동 표시 = 같은 차선 블록(1,000 / 21,000)", it)

class FakeTime:
    def __init__(self):
        self.t = 1_000_000.0

    def time(self):
        return self.t

    def __getattr__(self, k):
        return getattr(time, k)


def run_fixed(fixed_s, scan_s, cycles=4, n_w=6):
    cur = {"_bk:" + a: job(0, 0, 10 ** 7) for a in ALL[:n_w]}
    w, calls = make(cur, span=2000, bk_span=200_000)
    ft = FakeTime()
    real = evm_watch.time
    evm_watch.time = ft
    try:
        w.multicall = "0x" + "ca" * 20

        def scan(ws, c, target, deadline):
            ft.t += scan_s
            calls.append((tuple(sorted(ws)), int(c), int(target)))
            return {}, int(target), None

        def mc(ws, blk):
            ft.t += fixed_s
            for a in ws:
                w._st_memo[(a, int(blk))] = (0, 0)
            return len(ws)
        w._scan_logs = scan
        w._mc_balances = mc
        for _ in range(cycles):
            ft.t += 25.0
            w._bk_step(10 ** 8, ft.t + 20.0)
    finally:
        evm_watch.time = real
    return [t - c for _ws, c, t in calls], w


sz6, w6 = run_fixed(16.0, 1.0)
T.chk(len(sz6) >= 4 and sz6[0] == 2000 and max(sz6) >= 16_000 and all(b >= a for a, b in zip(sz6, sz6[1:])),
      "M6 큰 묶음 — 상태 선조회 16초(고정) + getLogs 1초 → 구간이 2,000 → 16,000↑ 로 늘어남(종전 = 2,000 고정)", sz6)
T.chk(sum(sz6) >= 8 * 2000 * len(sz6) // 4, "M6 같은 걸음 수(= 같은 고정 비용 횟수)로 훑은 블록 ≥ 종전의 2배", {"blocks": sum(sz6), "steps": len(sz6)})
sz6b, _w = run_fixed(16.0, 12.0)
T.chk(sz6b and all(x == 2000 for x in sz6b), "M6 getLogs·상세(구간 비례)가 예산 1/3 넘으면 종전처럼 안 늘림", sz6b)
sz6c, _w = run_fixed(0.0, 1.0)
T.chk(len(sz6c) >= 3 and sz6c[:3] == [2000, 4000, 8000], "M6 고정 비용 없는 걸음(지갑 1개 꼴) = 종전과 같게 늘림", sz6c[:4])
T.chk(int(w6.cursor.get("_bkspan") or 0) >= max(sz6), "M6 늘린 구간은 _bkspan 에 저장(재기동해도 이어 씀 · 형식 무변)",
      {"bkspan": w6.cursor.get("_bkspan"), "max": max(sz6)})

NODE_CAP = 3000
rng7, rej7 = [], []


def fake_rpc(url, method, params, *a, **k):
    if method == "eth_blockNumber":
        return hex(10 ** 8)
    if method == "eth_getLogs":
        f9, t9 = int(params[0]["fromBlock"], 16), int(params[0]["toBlock"], 16)
        if t9 - f9 + 1 > NODE_CAP:
            rej7.append((f9, t9))
            raise bf_engine.NetError(f"exceed maximum block range: {NODE_CAP}", "range", cap=NODE_CAP, host="127.0.0.1")
        rng7.append((f9, t9))
        return []
    raise bf_engine.NetError("시험: 모르는 메서드 " + method, "rpc")


fake_rpc._tj_test_mock = True
cur = {"_bk:" + a: job(0, 0, 70_000) for a in ALL}
w7, _c7 = make(cur, span=64_000, bk_span=200_000)
del w7._scan_logs
real_rpc = bf_engine.rpc_call
bf_engine.rpc_call = fake_rpc
try:
    r7 = T.safe(w7._bk_step, 10 ** 8, time.time() + 60)
finally:
    bf_engine.rpc_call = real_rpc
T.chk(not isinstance(r7, dict) and not w7._bk_jobs(), "M7 구간 64,000 걸음으로 70,000 블록 완주", {"r": r7, "left": {k[:6]: v.get("done") for k, v in w7._bk_jobs().items()}})
T.chk(rng7 and max(b - a + 1 for a, b in rng7) <= NODE_CAP, "M7 성공한 getLogs 는 전부 노드 상한(3,000) 이하", max((b - a + 1 for a, b in rng7), default=None))
T.chk(len(rej7) == 1, "M7 거부는 첫 1회뿐 — 배운 상한을 다음 청크·다음 걸음이 이어 씀(_log_caps)", {"rej": rej7, "caps": w7.__dict__.get("_log_caps")})
cov7 = sorted(set(rng7))
T.chk(all(rng7.count(x) == 2 for x in cov7), "M7 청크마다 두 위치(보낸 쪽·받는 쪽) 조회", len(rng7))
T.chk(cov7 and cov7[0][0] == 1 and all(b + 1 == a2 for (a, b), (a2, b2) in zip(cov7, cov7[1:])) and cov7[-1][1] == 70_000,
      "M7 빈틈 없이 1 → 70,000", {"n": len(cov7), "first": cov7[:2], "last": cov7[-2:]})

T.finish()
sys.exit(1 if T.FAILS else 0)
