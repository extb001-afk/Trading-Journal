#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import threading
import time

CH = "zerog"
W0 = "0x" + "e0" * 20
POLL = 60
URL = "http://127.0.0.1:9/rpc"
URL2 = "http://127.0.0.1:9/rpc2"
KEYU = "https://rpc.ankr.com/zerog/TESTKEY"
CFG = {"backfill_months": 0, "chains": {CH: {"discovery": "rpc", "chain_id": 16661, "rpcs": [URL], "getlogs_span": 10_000_000,
                                             "conf_depth": 10, "blocks_per_day": 43200, "poll_sec": POLL, "cycle_budget_sec": 240}},
       "wallets": [{"type": "evm", "chain": CH, "address": W0, "label": "w"}]}
with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump(CFG, f)
import common
import bf_engine
import evm_watch

bf_engine.configure(CFG)
R = evm_watch.RpcChainWatcher
CPATH = os.path.join(common.STATE_DIR, f"cursor_evm_{CH}.json")
EPATH = os.path.join(common.STATE_DIR, f"emitted_evm_{CH}.json")
HEAD = 60_000_000
SAFE = HEAD - 10
C0 = SAFE - 200
RT = "0x" + "55" * 20
XS = "0x" + "77" * 20
E18 = 10 ** 18
FEE = 21000
BAL0 = 5 * E18
LB = [C0 + 5 * (i + 1) for i in range(20)]
LH = ["0x" + f"{0xa000 + i:064x}" for i in range(20)]
HoldError = getattr(evm_watch, "HoldError", RuntimeError)
StateUnavailable = evm_watch.StateUnavailable


class FakeTime:
    def __init__(self):
        self.t = 1_800_000_000.0

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += float(s)

    def __getattr__(self, k):
        return getattr(time, k)


FT = FakeTime()
real_time = evm_watch.time
real_rpc, real_batch = bf_engine.rpc_call, bf_engine.rpc_batch
evm_watch.time = FT
MODE = {"detail": "408", "nodes408": set()}
CALLS = []


def nonce_at(b):
    return sum(1 for x in LB if x <= b)


def blk_full(b):
    return {"number": hex(b), "timestamp": hex(1_700_000_000 + b), "hash": "0x" + f"{b:064x}",
            "transactions": [{"hash": LH[i], "from": W0, "to": RT, "nonce": hex(i)} for i, x in enumerate(LB) if x == b]}


def tx_of(h):
    i = LH.index(h)
    return {"hash": h, "from": W0, "to": RT, "nonce": hex(i), "value": "0x0", "input": "0x12345678" + "00" * 32, "type": "0x2",
            "gasPrice": "0x1", "blockNumber": hex(LB[i])}


def rc_of(h):
    i = LH.index(h)
    return {"transactionHash": h, "blockNumber": hex(LB[i]), "blockHash": "0x" + f"{LB[i]:064x}", "gasUsed": hex(FEE), "effectiveGasPrice": "0x1",
            "status": "0x1", "logs": [], "from": W0, "to": RT}


def e408():
    return bf_engine.NetError('HTTP Error 408: Request Timeout ({"message":"Request timeout on the free tier"})', "http4xx", code=408)


def one(url, m, p, timeout):
    if m == "eth_getBlockByNumber":
        b = int(p[0], 16)
        return blk_full(b) if p[1] else {"number": p[0], "timestamp": hex(1_700_000_000 + b), "transactions": []}
    if m in ("eth_getTransactionByHash", "eth_getTransactionReceipt"):
        if MODE["detail"] == "408" or url in MODE["nodes408"]:
            raise e408()
        return tx_of(p[0]) if m == "eth_getTransactionByHash" else rc_of(p[0])
    if m == "eth_call":
        return "0x" + "00" * 31 + "12"
    raise bf_engine.NetError("예상 못 한 호출 " + m, "rpc")


def slow_for(url, methods):
    if any(m in ("eth_getTransactionByHash", "eth_getTransactionReceipt") for m in methods) and (MODE["detail"] == "408" or url in MODE["nodes408"]):
        return 20.0
    return 0.1


def fake_batch(url, calls, timeout=30.0, retries=2, prio="fg", deadline=None, sem_timeout=None):
    CALLS.append(("batch", url, sorted({m for m, _p in calls}), {"timeout": timeout, "deadline": deadline, "sem_timeout": sem_timeout}))
    d9 = slow_for(url, [m for m, _p in calls])
    FT.t += min(d9, float(timeout))
    if float(timeout) < d9:
        raise bf_engine.NetError("timeout: The read operation timed out", "timeout")
    if d9 >= 20.0:
        raise e408()
    return [one(url, m, p, timeout) for m, p in calls]


def fake_call(url, method, params, timeout=25.0, retries=2, prio="fg", deadline=None, allow_null=False, sem_timeout=None):
    CALLS.append(("call", url, [method], {"timeout": timeout, "deadline": deadline, "sem_timeout": sem_timeout}))
    d9 = slow_for(url, [method])
    FT.t += min(d9, float(timeout))
    if float(timeout) < d9:
        raise bf_engine.NetError("timeout: The read operation timed out", "timeout")
    return one(url, method, params, timeout)


bf_engine.rpc_batch = fake_batch
bf_engine.rpc_call = fake_call


class Wr:
    def __init__(self):
        self.recs = []

    def append(self, rec):
        self.recs.append(rec)


def states_fake(w, slow=0.0):
    def st(pairs, strict=False):
        m = w.__dict__.setdefault("_st_memo", {})
        for (a, b) in dict.fromkeys(pairs):
            if (a, b) not in m:
                FT.t += slow
                n9 = nonce_at(b)
                m[(a, b)] = (n9, BAL0 - FEE * n9)
        return {p: m[p] for p in pairs}
    return st


def mk(cur=None, rpcs=(URL,), fake_states=True):
    common.atomic_write_json(CPATH, cur if cur is not None else {"_rpc_v": 1, "_start": 0, W0: C0, "_ns": {W0: [C0, 0, str(BAL0), 0, "0"]}})
    common.atomic_write_json(EPATH, [])
    w = R(CFG, CH, [W0], Wr())
    w.multicall = None
    w.trace_rpcs = []
    w.cfg_rpcs = list(rpcs)
    w.state_rpcs = list(rpcs)
    w._head = lambda: HEAD
    w._init = lambda safe: None
    w._health_cycle = lambda *a, **k: None
    w._head_peek = lambda *a, **k: None
    w._order = lambda urls: list(urls)
    if fake_states:
        w._states = states_fake(w)
    return w


def n_calls(kind=None):
    return sum(1 for c in CALLS if kind is None or c[0] == kind)


def disk():
    return common.read_json(CPATH, {})


try:
    MODE.update(detail="408", nodes408=set())
    w1 = mk()
    CALLS.clear()
    t01 = FT.t
    r1 = T.safe(w1._native, W0, C0, SAFE, [], FT.t + 60, "_ns", HEAD)
    el1 = FT.t - t01
    T.chk(isinstance(r1, dict) and "_exc" in r1, "P1 잎 상세가 안 오면 정합 실패(예외 — 호출측 커서 유지 · 다음 사이클)", r1)
    T.chk(el1 <= 61.0, "P1 잎 20개 × 상세 408(20초) — _native 마감 60초 안에 끝남(종전 440초: 배치 2번 + 단건 대체 20번 뒤 첫 잎 실패)",
          {"sec": round(el1, 1), "rpc": n_calls()})
    T.chk(n_calls() <= 5, "P1 RPC ≤ 5(블록 묶음 1 + 선조회 배치 1 + 첫 잎 배치·단건) — 종전 23(잎마다 단건 대체)",
          [(c[0], c[2]) for c in CALLS])
    T.chk(not (w1.cursor.get("_detail_fail") or {}), "P1 마감·408 은 상세 실패 계수(격리 200사이클)에 안 듦", w1.cursor.get("_detail_fail"))

    w2 = mk(rpcs=(URL, URL2))
    CALLS.clear()
    t02 = FT.t
    r2 = T.safe(w2._native, W0, C0, SAFE, [], FT.t + 60, "_ns", HEAD)
    el2 = FT.t - t02
    T.chk(isinstance(r2, dict) and "_exc" in r2 and el2 <= 61.0, "P2 노드 2개 모두 408 — 노드 전환 전에도 남은 시간 검사(마감 안 · 종전 = 노드 수 × 단건 대체)",
          {"sec": round(el2, 1), "rpc": n_calls()})
    det2 = [c for c in CALLS if "eth_getTransactionReceipt" in c[2] or "eth_getTransactionByHash" in c[2]]
    T.chk(det2 and all(c[3]["sem_timeout"] is not None and c[3]["deadline"] is not None and float(c[3]["timeout"]) <= 60.0 for c in det2),
          "P2 상세 RPC 마다 deadline · sem_timeout(세마포어 대기 상한) · 남은 시간으로 깎은 timeout 전달(종전 = 마감 없음 · 30/25초 고정)",
          [(c[0], round(float(c[3]["timeout"]), 1), c[3]["sem_timeout"] is not None) for c in det2])
    MODE.update(detail="ok")
    w2b = mk()
    w2b._batch = lambda calls, urls=None: [bf_engine.NetError("partial", "rpc") if m == "eth_getTransactionReceipt" else one(URL, m, p, 30) for m, p in calls]
    MODE.update(detail="408")
    CALLS.clear()
    t02b = FT.t
    o2b = T.safe(w2b._details, LH[:10], deadline=FT.t + 30, trace=False)
    el2b = FT.t - t02b
    bud2b = [h for h, v in (o2b or {}).items() if "예산 소진" in str(v)] if isinstance(o2b, dict) and "_exc" not in o2b else []
    T.chk(el2b <= 31.0 and len(bud2b) >= 8, "P2 청크 안 단건 대체도 마감 검사 — 마감 뒤 남은 tx = '상세 예산 소진'(미시도) · 청크를 끝까지 재시도하지 않음(종전 10 × 20초)",
          {"sec": round(el2b, 1), "budget": len(bud2b), "calls": n_calls()})

    MODE.update(detail="408", nodes408=set())
    w3 = mk()
    w3._scan_logs = lambda ws, c, target, dl: ({}, int(target), None)
    CALLS.clear()
    t03 = FT.t
    r3 = T.safe(w3.cycle)
    el3 = FT.t - t03
    d3 = disk()
    T.chk(el3 <= 75.0, "P3 실제 cycle — 사이클 길이 ≤ 75초(종전 440초 · 최신 갱신 지연)", {"sec": round(el3, 1), "rpc": n_calls(), "r": r3})
    T.chk(int(d3.get(W0) or 0) == C0 and isinstance(d3.get("_scan"), dict), "P3 확인 못 한 구간 = 라이브 커서 유지 · 스캔 체크포인트 남음(다음 사이클 이어서)",
          {"cursor": d3.get(W0), "scan": bool(d3.get("_scan"))})
    MODE.update(detail="ok")
    w3b = mk(cur=d3)
    w3b._scan_logs = lambda ws, c, target, dl: ({}, int(target), None)
    T.safe(w3b.cycle)
    T.safe(w3b.cycle)
    em3 = [r.get("txhash") for r in w3b.writer.recs]
    T.chk(sorted(set(em3)) == sorted(LH) and len(em3) == len(LH), "P3 회복 뒤 잎 tx 20건 정확히 한 번 방출(다음 사이클 중복 0)",
          {"emitted": len(em3), "unique": len(set(em3))})
    T.chk(int(disk().get(W0) or 0) == SAFE, "P3 회복 뒤 라이브 커서 safe 도달", disk().get(W0))

    bf_engine.rpc_batch, bf_engine.rpc_call = real_batch, real_rpc
    evm_watch.time = real_time
    try:
        w4 = mk()
        g4 = bf_engine.gate(URL)
        held = []
        while g4.sem.acquire(blocking=False):
            held.append(1)
        t04 = time.time()
        res4 = {}

        def run4():
            with w4._rpc_budget(time.time() + 1.5):
                try:
                    res4["out"] = w4._batch([("eth_getTransactionByHash", [LH[0]])])
                except Exception as e:
                    res4["err"] = e
        th = threading.Thread(target=run4, daemon=True)
        th.start()
        th.join(10.0)
        el4 = time.time() - t04
        for _ in held:
            g4.sem.release()
        T.chk(not th.is_alive() and el4 <= 3.0 and "budget" in str(res4.get("err") or "").lower(),
              "P4 호스트 세마포어를 다른 요청이 쥐고 있어도 마감(1.5초) 안에 '예산 소진'으로 끝남(sem_timeout = 남은 시간 · 종전: 무기한 대기)",
              {"sec": round(el4, 2), "alive": th.is_alive(), "err": str(res4.get("err"))[:80]})
    finally:
        evm_watch.time = FT
        bf_engine.rpc_batch, bf_engine.rpc_call = fake_batch, fake_call

    SMODE = {"key": "local", "pub_old": "pruned"}
    OLD = SAFE - 500_000

    def fb5(url, calls, timeout=30.0, retries=2, prio="fg", deadline=None, sem_timeout=None):
        FT.t += 0.1
        if url == KEYU:
            if SMODE["key"] == "local":
                e9 = bf_engine.NetError("quota: Ankr 오늘(UTC) 몫(80%) 다 씀 — 다른 노드로", "quota")
                e9.local = True
                raise e9
            if SMODE["key"] == "circuit":
                raise bf_engine.NetError("circuit open rpc.ankr.com (60s)", "circuit")
        out = []
        for m, p in calls:
            b = int(p[1], 16)
            if url != KEYU and HEAD - b > 6000:
                out.append(bf_engine.classify_rpc_error({"code": -32000, "message": "missing trie node abc (path )"}))
            elif url != KEYU and SMODE["pub_old"] == "lag" and HEAD - b <= 64:
                out.append(bf_engine.classify_rpc_error({"code": -32000, "message": "header not found"}))
            else:
                out.append(hex(0) if m == "eth_getTransactionCount" else hex(BAL0))
        return out
    bf_engine.rpc_batch = fb5
    try:
        def st5(rpcs, blk, mode_key="local", pub="pruned", order=None, ctx=True):
            SMODE.update(key=mode_key, pub_old=pub)
            w = mk(rpcs=rpcs, fake_states=False)
            w._st_safe = SAFE
            w._log_head = HEAD
            w._e4_ctx = ctx
            if order is not None:
                w._order = order
            try:
                return w._states([(W0, blk)])
            except Exception as e:
                return e
        a5 = st5((KEYU, URL), OLD)
        T.chk(isinstance(a5, HoldError) and not isinstance(a5, StateUnavailable),
              "P5 키 노드 하루 몫 거절 + 공개 노드 '상태 없음'(옛 블록) = 보류(HoldError · 커서 유지 — 종전 StateUnavailable = 이분 탐색 없이 누적 전진)",
              type(a5).__name__)
        b5 = st5((KEYU, URL), OLD, mode_key="circuit")
        T.chk(isinstance(b5, HoldError), "P5 키 노드 서킷(호출 중 거절)도 보류", type(b5).__name__)
        c5 = st5((KEYU, URL), OLD, mode_key="ok", order=lambda urls: [u for u in urls if u != KEYU])
        T.chk(isinstance(c5, HoldError), "P5 키 노드가 서킷으로 순서에서 빠짐(미확인)도 보류", type(c5).__name__)
        d5 = st5((KEYU, URL), OLD, mode_key="ok")
        T.chk(isinstance(d5, dict) and d5.get((W0, OLD)) == (0, BAL0), "P5 키 노드 정상 = 옛 상태 받음(종전)", d5 if isinstance(d5, dict) else type(d5).__name__)
        e5 = st5((URL,), OLD)
        T.chk(isinstance(e5, StateUnavailable), "P5 키 없는 설치(공개 노드만) = 종전 StateUnavailable(비아카이브 — 누적)", type(e5).__name__)
        f5 = st5((KEYU, URL), HEAD - 5, pub="lag")
        T.chk(isinstance(f5, StateUnavailable), "P5 헤드 근처(라이브 꼬리) = 종전 StateUnavailable(뒤처진 노드 보류 규칙 _state_lag_hold 가 다룸)", type(f5).__name__)
        h5 = st5((KEYU, URL), OLD, ctx=False)
        T.chk(isinstance(h5, StateUnavailable) and not isinstance(h5, HoldError),
              "P5 (코덱스 ev905) 뒤 차선 걸음 밖(초기화·인계·새 지갑 합류·창 확장 준비·엿보기·라이브 차선) = 종전 StateUnavailable(호출측이 흡수 — 최신 수집 안 멈춤)",
              type(h5).__name__)
        g5 = st5((KEYU, URL), SAFE)
        T.chk(isinstance(g5, dict) and g5.get((W0, SAFE)) == (0, BAL0), "P5 키 노드가 쉬어도 최신 블록 상태는 공개 노드가 줌", type(g5).__name__ if not isinstance(g5, dict) else g5)

        SMODE.update(key="local", pub_old="pruned")
        HNEW = "0x" + "9f" * 32
        cur5 = {"_rpc_v": 1, "_start": 0, "_handover": {"from": "fresh", "at": 1}, W0: SAFE - 50, "_ns": {W0: [SAFE - 50, 0, str(BAL0), 0, "0"]},
                "_bk:" + W0: {"from": OLD, "to": OLD + 8000, "done": OLD, "why": "new"}, "_bkns": {W0: [OLD, 0, str(BAL0), 0, "0"]}, "_bkspan": 8000}
        w5 = mk(cur=cur5, rpcs=(KEYU, URL), fake_states=False)

        def scan5(ws, c, target, dl):
            if int(c) < SAFE - 10 <= int(target):
                return {HNEW: SAFE - 10}, int(target), None
            return {}, int(target), None
        w5._scan_logs = scan5
        w5._details = lambda hs, deadline=None, trace=True, **k: {h: {"tx": {"hash": h, "block_number": SAFE - 10, "from": XS, "to": W0, "status": "ok", "value": "0",
                                                                               "fee": {"value": "0"}},
                                                                        "token_transfers": [{"from": XS, "to": W0, "value": "5", "token": {"address": RT, "decimals": 6}}],
                                                                        "internal": []} for h in hs}
        T.safe(w5.cycle)
        d5c = disk()
        T.chk(HNEW in [r.get("txhash") for r in w5.writer.recs] and int(d5c.get(W0) or 0) == SAFE,
              "P5 키 노드가 쉬는 사이클에도 최신 꼬리 입금 방출 · 라이브 커서 safe(최신 우선 불변식)", {"recs": len(w5.writer.recs), "cursor": d5c.get(W0)})
        j5 = d5c.get("_bk:" + W0) or {}
        T.chk(int(j5.get("done") or 0) == OLD and ((d5c.get("_bkns") or {}).get(W0) or [0])[0] == OLD,
              "P5 옛 구간(뒤 차선)은 보류 — 진행점·기준점 그대로(종전: 이분 탐색 없이 누적 전진 → 그 구간 로그 없는 internal 입금 영영 정합 안 됨)",
              {"done": j5.get("done"), "bkns": (d5c.get("_bkns") or {}).get(W0)})
        def mk7(cur, wallets=(W0,), window=None):
            common.atomic_write_json(CPATH, cur)
            common.atomic_write_json(EPATH, [])
            w = R(CFG, CH, list(wallets), Wr())
            w.multicall = None
            w.trace_rpcs = []
            w.cfg_rpcs = [URL]
            w.state_rpcs = [KEYU, URL]
            w._head = lambda: (setattr(w, "_log_head", HEAD), HEAD)[1]
            w._health_cycle = lambda *a, **k: None
            w._head_peek = lambda *a, **k: None
            w._order = lambda urls: list(urls)
            w._scan_logs = scan5
            w._details = w5._details
            if window is not None:
                w._window_start = lambda safe: int(window)
            return w

        def emitted7(w):
            return [r.get("txhash") for r in w.writer.recs]
        SMODE.update(key="local", pub_old="pruned")
        WS7 = SAFE - 200_000
        w7 = mk7({}, window=WS7)
        r7 = T.safe(w7.cycle)
        d7 = disk()
        j7 = d7.get("_bk:" + W0) or {}
        T.chk(HNEW in emitted7(w7) and int(d7.get(W0) or 0) == SAFE,
              "P7a 새 설치 첫 초기화 · 키 노드 하루 몫 거절 + 공개 노드 옛 상태 pruned → 그 사이클에 최신 입금 방출 · 라이브 커서 safe(종전 판: HoldError 가 초기화에서 올라가 사이클 통째 실패)",
              {"r": r7 if isinstance(r7, dict) else None, "emitted": len(emitted7(w7)), "cursor": d7.get(W0)})
        T.chk(j7 and int(j7.get("done") or 0) == int(j7.get("from") or -1) == WS7 and not (d7.get("_bkns") or {}).get(W0),
              "P7a 옛 구간(뒤 차선)은 시작 기준점을 다시 묻다가 쉬는 중이라 보류 — 진행점 그대로(기준점 없이 첫 구간을 흡수하지 않음)", {"job": j7, "bkns": d7.get("_bkns")})
        SMODE.update(key="ok")
        w7b = mk7(d7, window=WS7)
        T.safe(w7b.cycle)
        d7b = disk()
        nb7 = [r for r in (d7b.get("_native_notes") or []) if r.get("kind") == "baseline" and WS7 < int(r.get("blk") or 0) <= int(j7.get("to") or 0)]
        T.chk(not d7b.get("_bk:" + W0) and not nb7,
              "P7a 키 노드 회복 → 뒤 차선 시작 기준점을 받아 첫 구간부터 정합하며 완주(첫 확인 지점 '기준점 흡수' 없음)", {"job": d7b.get("_bk:" + W0), "baseline_notes": nb7})
        SMODE.update(key="local")
        s_tgt = getattr(bf_engine.SINCE, "target")
        bf_engine.SINCE.target = lambda section=None: 1_600_000_000
        try:
            cur7 = {"_rpc_v": R.VERSION, "_start": WS7, "_handover": {"from": "fresh", "at": 1}, W0: SAFE - 50,
                    "_ns": {W0: [SAFE - 50, 0, str(BAL0), 0, "0"]}, "_bkns": {}}
            w7c = mk7(cur7, window=WS7 - 100_000)
            r7c = T.safe(w7c.cycle)
        finally:
            bf_engine.SINCE.target = s_tgt
        d7c = disk()
        T.chk(HNEW in emitted7(w7c) and int(d7c.get(W0) or 0) == SAFE,
              "P7b 과거 창 확장 준비 중 키 노드 쉬는 중 → 최신 입금 방출 · 라이브 커서 safe(종전 판: _since_reinit_bk 의 기준점 조회에서 HoldError → 사이클 통째 실패)",
              {"r": r7c if isinstance(r7c, dict) else None, "emitted": len(emitted7(w7c)), "cursor": d7c.get(W0)})
        T.chk(isinstance(d7c.get("_since_skip"), dict) and not d7c.get("_bk:" + W0) and int(d7c.get("_start") or 0) == WS7,
              "P7b 확장은 보류 표식(_since_skip — 6시간마다 다시) · 창 시작·뒤 차선 그대로(종전 규약)", {"skip": d7c.get("_since_skip"), "start": d7c.get("_start")})
        W1 = "0x" + "e1" * 20
        cur7d = {"_rpc_v": R.VERSION, "_start": WS7, "_handover": {"from": "fresh", "at": 1}, W0: SAFE - 50,
                 "_ns": {W0: [SAFE - 50, 0, str(BAL0), 0, "0"]}, "_bkns": {}, "_since_seen": 0}
        w7d = mk7(cur7d, wallets=(W0, W1))
        r7d = T.safe(w7d.cycle)
        d7d = disk()
        j7d = d7d.get("_bk:" + W1) or {}
        T.chk(HNEW in emitted7(w7d) and int(d7d.get(W0) or 0) == SAFE and int(d7d.get(W1) or 0) == SAFE,
              "P7c 새 지갑 합류 중 키 노드 쉬는 중 → 최신 입금 방출 · 두 지갑 라이브 커서 safe(종전 판: 합류 기준점 조회에서 HoldError → 사이클 통째 실패)",
              {"r": r7d if isinstance(r7d, dict) else None, "emitted": len(emitted7(w7d)), "w0": d7d.get(W0), "w1": d7d.get(W1)})
        T.chk(j7d and int(j7d.get("done") or 0) == int(j7d.get("from") or -1) == WS7, "P7c 합류 지갑의 옛 구간(뒤 차선)은 보류(진행점 그대로)", j7d)
    finally:
        bf_engine.rpc_batch = fake_batch

    KEY6 = f"{CH}:rpc"
    prog = bf_engine.progress("evm")
    prog.items.pop(KEY6, None)
    cur6 = {"_rpc_v": 1, "_start": 0, "_handover": {"from": "explorer", "at": 1}, W0: SAFE, "_ns": {W0: [SAFE, 0, str(BAL0), 0, "0"]},
            "_hq": {"0x" + "ab" * 32: 0, "0x" + "cd" * 32: 0}}
    w6 = mk(cur=cur6)
    it6 = dict(prog.items.get(KEY6) or {})
    T.chk(it6.get("phase") != "extend", "P6 뒤 차선 일 없이 인계 큐만 남은 재기동 = 'extend' 표식 안 만듦(종전 done 0/total 1 'extend' → core 재구축이 재기동마다 1시간 대기)",
          {k: it6.get(k) for k in ("phase", "done", "total", "note")})
    w6._hq_step = lambda head, deadline: 0
    w6._scan_logs = lambda ws, c, target, dl: ({}, int(target), None)
    T.safe(w6.cycle)
    it6b = dict(prog.items.get(KEY6) or {})
    T.chk(it6b.get("phase") == "live", "P6 사이클 끝도 인계 큐만이면 'live'(헬스 rpc_bk 에는 큐 수 그대로)", {k: it6b.get(k) for k in ("phase", "done", "total", "note")})
    prog.items.pop(KEY6, None)
    cur6b = dict(cur6, **{"_bk:" + W0: {"from": SAFE - 9000, "to": SAFE - 1000, "done": SAFE - 5000, "why": "extend"}, "_bkns": {}})
    mk(cur=cur6b)
    it6c = dict(prog.items.get(KEY6) or {})
    T.chk(it6c.get("phase") == "extend" and str(it6c.get("note") or "").startswith("재기동"),
          "P6 뒤 차선 일이 남은 재기동 = 종전대로 기동 즉시 'extend'(perf1008c — 첫 사이클 전 재구축 끼어들기 방지)", {k: it6c.get(k) for k in ("phase", "note")})
    cur6c = dict(cur6)
    cur6c.pop("_hq")
    w6c = mk(cur=cur6c)
    w6c._scan_logs = lambda ws, c, target, dl: ({}, int(target), None)
    T.safe(w6c.cycle)
    it6d = dict(prog.items.get(KEY6) or {})
    T.chk(it6d.get("phase") == "live" and not str(it6d.get("note") or "").startswith("재기동"),
          "P6 뒤 차선이 끝나 'live' 가 되면 '재기동 — 뒤 차선 이어서' 메모를 지움(종전: live 인데 메모가 남아 헬스 상세에 보임)", {k: it6d.get(k) for k in ("phase", "note")})
finally:
    evm_watch.time = real_time
    bf_engine.rpc_call, bf_engine.rpc_batch = real_rpc, real_batch

T.finish()
