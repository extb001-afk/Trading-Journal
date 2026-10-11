#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import time

CH = "zerog"
W0 = "0x" + "e0" * 20
POLL = 60
URL = "http://127.0.0.1:9/rpc"
TA, TB = "http://127.0.0.1:9/trA", "http://127.0.0.1:9/trB"
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
TOVF = os.path.join(common.STATE_DIR, f"trace_later_overflow_{CH}.jsonl")
HEAD = 60_000_000
X = "0x" + "77" * 20
RT = "0x" + "55" * 20
E18 = 10 ** 18


class FakeTime:
    def __init__(self):
        self.t = 1_800_000_000.0
        self.jit = 0.0

    def time(self):
        self.t += self.jit
        return self.t

    def sleep(self, s):
        self.t += float(s)

    def __getattr__(self, k):
        return getattr(time, k)


FT = FakeTime()
real_time = evm_watch.time
evm_watch.time = FT
real_rpc = bf_engine.rpc_call
LOG = []
PLAN = {}


def e408():
    return bf_engine.NetError('HTTP Error 408: Request Timeout ({"message":"Request timeout on the free tier"})', "http4xx", code=408)


def slow408(sec):
    def f(params, timeout):
        FT.t += min(float(sec), float(timeout))
        if float(timeout) < float(sec):
            raise bf_engine.NetError("timeout: The read operation timed out", "timeout")
        raise e408()
    return f


def hang():
    def f(params, timeout):
        FT.t += float(timeout)
        raise bf_engine.NetError("timeout: The read operation timed out", "timeout")
    return f


def ok_rows(rows=(), sec=0.5):
    def f(params, timeout, _m=None):
        if float(timeout) < float(sec):
            FT.t += float(timeout)
            raise bf_engine.NetError("timeout: The read operation timed out", "timeout")
        FT.t += float(sec)
        return rows
    return f


def gone(msg):
    def f(params, timeout):
        FT.t += 0.1
        raise bf_engine.classify_rpc_error({"code": -32000, "message": msg})
    return f


def r429():
    def f(params, timeout):
        FT.t += 0.2
        raise bf_engine.NetError("HTTP Error 429: Too Many Requests", "http429", code=429)
    return f


def frame(rows):
    return {"type": "CALL", "from": W0, "to": RT, "value": "0x0",
            "calls": [{"type": "CALL", "from": f9, "to": t9, "value": hex(v9)} for (f9, t9, v9) in rows]}


def parity(rows):
    return [{"type": "call", "traceAddress": [], "action": {"from": W0, "to": RT, "value": "0x0", "callType": "call"}}] + [
        {"type": "call", "traceAddress": [i], "action": {"from": f9, "to": t9, "value": hex(v9), "callType": "call"}} for i, (f9, t9, v9) in enumerate(rows)]


def fake_rpc(url, method, params, timeout=25.0, **k):
    LOG.append((url, method, float(timeout)))
    fn = PLAN.get((url, method))
    if fn is None:
        raise bf_engine.NetError("예상 못 한 호출 " + method, "rpc")
    r = fn(params, timeout)
    if method == "debug_traceTransaction" and isinstance(r, (list, tuple)):
        return frame(r)
    if method == "trace_transaction" and isinstance(r, (list, tuple)):
        return parity(r)
    return r


bf_engine.rpc_call = fake_rpc


class Wr:
    def __init__(self):
        self.recs = []

    def append(self, rec):
        self.recs.append(rec)


def hx(i):
    return "0x" + f"{i:064x}"


def own_tx(h, blk=7):
    return {"tx": {"hash": h, "block_number": blk, "from": W0, "to": RT, "status": "ok", "value": "0", "raw_input": "0x12345678" + "00" * 32,
                   "fee": {"value": "0"}}, "token_transfers": [], "internal": []}


def mk(trace=(TA, TB), tl=None):
    cur = {"_rpc_v": 1, "_start": 0}
    if tl:
        cur["_trace_later"] = tl
    common.atomic_write_json(CPATH, cur)
    common.atomic_write_json(EPATH, sorted(tl or {}))
    if os.path.exists(TOVF):
        os.remove(TOVF)
    w = R(CFG, CH, [W0], Wr())
    w.multicall = None
    w.trace_rpcs = list(trace)
    w._head = lambda: HEAD
    w._init = lambda safe: None
    w._health_cycle = lambda *a, **k: None
    w._order = lambda urls: list(urls)
    w._batch = lambda calls, urls=None: [None for _ in calls]
    w._rpc_synth_detail = lambda h: own_tx(h)
    w._rpc_call = lambda m, p: {"nonce": "0x0", "from": W0, "to": RT}
    w._fill_symbols = lambda snaps: None
    return w


def queue(hs, n=0):
    now = int(FT.t)
    return {h: {"at": now, "n": n, "next": now, "blk": 7, "sent": True} for h in hs}


def run_later(w, cycles, stop_empty=True):
    nmax = 0
    for i in range(cycles):
        t0 = FT.t
        T.safe(w._trace_later_step, HEAD)
        tl = w.cursor.get("_trace_later") or {}
        nmax = max([nmax] + [int((e or {}).get("n") or 0) for e in tl.values()])
        if stop_empty and not tl:
            return i + 1, nmax
        FT.t = max(FT.t, t0 + POLL)
    return None, nmax


try:
    PLAN.clear()
    PLAN.update({(TA, "debug_traceTransaction"): slow408(30), (TA, "trace_transaction"): slow408(30),
                 (TB, "debug_traceTransaction"): ok_rows([]), (TB, "trace_transaction"): ok_rows([])})
    hs1 = [hx(0x100 + i) for i in range(7)]
    w1 = mk(tl=queue(hs1))
    LOG.clear()
    fin1, _n1 = run_later(w1, 40)
    nb1 = sum(1 for u, _m, _t in LOG if u == TB)
    na1 = sum(1 for u, _m, _t in LOG if u == TA)
    T.chk(fin1 is not None and fin1 <= 10, "N1 trace 노드 [A 30초 408, B 정상] · 늦은 채움 7건 → 10사이클 안에 큐 빔(종전: 40사이클에도 7건 그대로)",
          {"empty_cycle": fin1, "left": len(w1.cursor.get("_trace_later") or {})})
    T.chk(nb1 >= 7, "N1 둘째 노드 B 를 실제로 씀(종전: B 호출 0회 — 첫 항목 몫 30초를 A 가 다 씀)", {"B": nb1, "A": na1})
    T.chk(na1 <= 4, "N1 느린 A 는 300초 동안 뒤로(사이클마다 다시 30초 408 을 기다리지 않음)", {"A": na1})
    order1 = getattr(w1, "_trace_order", None)
    T.chk(callable(order1), "N1 _trace_order 있음(느렸던 노드 = TRACE_SICK_SEC 동안 맨 뒤)", None)

    PLAN.clear()
    PLAN.update({(TA, "debug_traceTransaction"): ok_rows([], sec=12.0), (TA, "trace_transaction"): ok_rows([], sec=12.0)})
    hs2 = [hx(0x200 + i) for i in range(30)]
    w2 = mk(trace=(TA,), tl=queue(hs2))
    LOG.clear()
    fin2, nmax2 = run_later(w2, 30)
    T.chk(nmax2 == 0, "N2 trace 12초 정상 노드 — 남은 몫(6초)에서 끊긴 건 실패로 안 셈(거짓 실패 0 · 종전 사이클마다 1건 n+1 → 백오프 4분~6시간)",
          {"max_n": nmax2, "left": len(w2.cursor.get("_trace_later") or {})})
    T.chk(fin2 is not None and fin2 <= 16, "N2 30건 전부 회수(사이클당 2건 — 셋째는 다음 사이클)", {"empty_cycle": fin2})
    cut2 = [t for _u, m, t in LOG if m == "debug_traceTransaction" and t < 12.0]
    T.chk(all(t < 29.0 for t in cut2), "N2 끊긴 호출은 전부 실제로 깎인 몫(상한 30초보다 1초 이상 짧음)", cut2[:5])
    T.chk(not (w2.__dict__.get("_trace_sick_until") or 0) or not w2._trace_sick(), "N2 아픈 노드 안 열림(거짓 실패가 연속 실패 계수에 안 듦)",
          w2.__dict__.get("_trace_nf"))

    PLAN.clear()
    PLAN.update({(TA, "debug_traceTransaction"): hang(), (TA, "trace_transaction"): hang(),
                 (TB, "debug_traceTransaction"): ok_rows([]), (TB, "trace_transaction"): ok_rows([])})
    hs3 = [hx(0x300 + i) for i in range(3)]
    w3 = mk(tl=queue(hs3))
    LOG.clear()
    FT.jit = 1e-4
    try:
        fin3, _n3 = run_later(w3, 8)
    finally:
        FT.jit = 0.0
    nb3 = sum(1 for u, _m, _t in LOG if u == TB)
    na3 = sum(1 for u, _m, _t in LOG if u == TA)
    T.chk(fin3 is not None and fin3 <= 6 and nb3 >= 3 and na3 == 1,
          "N3 첫 1건 몫(상한 30초 − 마이크로초)에서 매달린 노드 A 의 시간 초과 = 노드 탓 → A 뒤로(그 뒤 A 0회) · B 로 전부 회수(첫 항목은 백오프 뒤) — 깎음 판정 = 상한보다 1초 이상 짧을 때만",
          {"empty_cycle": fin3, "B": nb3, "A": na3, "first_timeouts": [round(t, 4) for u, m, t in LOG if u == TA][:3]})

    tg = R._trace_gone
    MTN = bf_engine.classify_rpc_error({"code": -32000, "message": "missing trie node 7c3f (path )"})
    HP = bf_engine.classify_rpc_error({"code": -32000, "message": "history has been pruned"})
    HV = bf_engine.classify_rpc_error({"code": -32000, "message": "historical version not found: 5: invalid height"})
    FL = bf_engine.classify_rpc_error({"code": -32000, "message": "failed to load state at height 123"})
    HNF = bf_engine.classify_rpc_error({"code": -32000, "message": "header not found"})
    BNF = bf_engine.classify_rpc_error({"code": -32000, "message": "block not found"})
    T.chk(all(getattr(e, "kind", None) == "pruned" for e in (MTN, HP, HV, FL, HNF, BNF)), "N4 (전제) 여섯 문구 모두 bf_engine 분류 = pruned",
          [getattr(e, "kind", None) for e in (MTN, HP, HV, FL, HNF, BNF)])
    T.chk(tg(MTN) and tg(HP) and tg(HV) and tg(FL), "N4 'missing trie node'·'history has been pruned'·'historical version not found'·'failed to load state at height' = 영영 못 줌",
          [tg(e) for e in (MTN, HP, HV, FL)])
    T.chk(not tg(HNF) and not tg(BNF), "N4 모호한 'header not found'·'block not found'(뒤처진 노드) = 재시도", [tg(HNF), tg(BNF)])
    T.chk(not tg(bf_engine.NetError("rpc-error -32000: missing trie node", "rpc")), "N4 문구가 같아도 분류가 pruned 가 아니면 영구 아님(종전 규약)", None)
    PLAN.clear()
    PLAN.update({(TA, "debug_traceTransaction"): gone("missing trie node 7c3f (path )"), (TA, "trace_transaction"): gone("missing trie node 7c3f (path )")})
    h4 = hx(0x400)
    w4 = mk(trace=(TA,), tl=queue([h4]))
    T.safe(w4._trace_later_step, HEAD)
    notes4 = [r.get("kind") for r in (w4.cursor.get("_native_notes") or [])]
    T.chk(h4 not in (w4.cursor.get("_trace_later") or {}) and "trace_later_unsupported" in notes4,
          "N4 비아카이브 trace 노드의 옛 tx('missing trie node') = 늦은 채움 큐에서 뺌(기록 남김 · 종전: 30일·5회 자리 차지)", notes4)
    T.chk(not w4._trace_sick() and int(w4.__dict__.get("_trace_nf") or 0) == 0, "N4 아픈 노드 계수 안 오름(옛 tx 마다 서킷이 다시 열리던 것)",
          w4.__dict__.get("_trace_nf"))
    PLAN.clear()
    PLAN.update({(TA, "debug_traceTransaction"): gone("missing trie node 7c3f (path )"), (TA, "trace_transaction"): gone("missing trie node 7c3f (path )"),
                 (TB, "debug_traceTransaction"): r429(), (TB, "trace_transaction"): r429()})
    w4b = mk(tl=queue([h4]))
    T.safe(w4b._trace_later_step, HEAD)
    T.chk(h4 in (w4b.cursor.get("_trace_later") or {}), "N4 다른 노드가 일시 오류(429)면 항목 남김(노드 하나의 '없음'이 지우지 않음 — _trace_err)",
          sorted(w4b.cursor.get("_trace_later") or {}))
    PLAN.clear()
    PLAN.update({(TA, "debug_traceTransaction"): gone("header not found"), (TA, "trace_transaction"): gone("header not found")})
    w4c = mk(trace=(TA,), tl=queue([h4]))
    T.safe(w4c._trace_later_step, HEAD)
    T.chk(int(((w4c.cursor.get("_trace_later") or {}).get(h4) or {}).get("n") or 0) == 1, "N4 'header not found' = 일시 실패(재시도 · n+1)",
          (w4c.cursor.get("_trace_later") or {}).get(h4))

    def deep(depth, leaf_to=W0, v=E18):
        root = {"type": "CALL", "from": W0, "to": RT, "value": "0x0", "calls": []}
        cur = root
        for i in range(depth):
            ch = {"type": "CALL", "from": RT, "to": X, "value": "0x0", "calls": []}
            cur["calls"].append(ch)
            cur = ch
        cur["calls"].append({"type": "CALL", "from": X, "to": leaf_to, "value": hex(v)})
        return root
    D5 = deep(1500)
    PLAN.clear()
    PLAN.update({(TA, "debug_traceTransaction"): (lambda p, t: (FT.__setattr__("t", FT.t + 0.5), D5)[1])})
    w5 = mk(trace=(TA,))
    snap5 = {}
    r5 = T.safe(w5._trace_internal, hx(0x500), snap5)
    T.chk(not (isinstance(r5, dict) and "_exc" in r5) and snap5.get("internal") == [{"from": X, "to": W0, "value": str(E18), "success": True}],
          "N5 깊이 1,500 callTracer 프레임 — RecursionError 없이 맨 안쪽 internal 입금 회수(종전: 재귀 깊이 초과 = trace 실패)",
          {"r": r5 if isinstance(r5, dict) else None, "internal": snap5.get("internal")})
    PLAN.clear()
    PLAN.update({(TA, "debug_traceBlockByNumber"): (lambda p, t: (FT.__setattr__("t", FT.t + 0.5), [{"txHash": hx(0x501), "result": D5}])[1])})
    w5b = mk(trace=(TA,))
    r5b = T.safe(w5b._trace_block, 123)
    T.chk(isinstance(r5b, tuple) and (r5b[0] or {}).get(hx(0x501)) == [{"from": X, "to": W0, "value": str(E18), "success": True}],
          "N5 블록 trace 도 깊은 프레임 회수", r5b if not isinstance(r5b, tuple) else {k[-4:]: v for k, v in r5b[0].items()})
    TREE = {"type": "CALL", "from": W0, "to": RT, "value": "0x0", "calls": [
        {"type": "CALL", "from": RT, "to": W0, "value": "0x1", "error": "reverted", "calls": [
            {"type": "CALL", "from": X, "to": W0, "value": "0x2"},
            {"type": "DELEGATECALL", "from": X, "to": W0, "value": "0x9"},
            {"type": "CALL", "from": W0, "to": X, "value": "0x3", "calls": [{"type": "CREATE", "from": X, "to": W0, "value": "0x4"}]}]},
        {"type": "CALL", "from": RT, "to": W0, "value": "0x5", "calls": [{"type": "SELFDESTRUCT", "from": X, "to": W0, "value": "0x6"}]},
        {"type": "STATICCALL", "from": RT, "to": X, "value": "0x0", "calls": [{"type": "CALL", "from": X, "to": W0, "value": "0x7"}]}]}

    def ref_walk(fr, failed, out):
        for ch in fr.get("calls") or []:
            bad = failed or bool(ch.get("error"))
            v = int(ch.get("value") or "0x0", 16)
            f9, t9 = (ch.get("from") or "").lower(), (ch.get("to") or "").lower()
            if v and str(ch.get("type") or "").upper() in R._VALUE_OPS and (f9 == W0 or t9 == W0):
                out.append({"from": f9, "to": t9, "value": str(v), "success": not bad})
            ref_walk(ch, bad, out)
    exp5 = []
    ref_walk(TREE, False, exp5)
    PLAN.clear()
    PLAN.update({(TA, "debug_traceTransaction"): (lambda p, t: (FT.__setattr__("t", FT.t + 0.5), TREE)[1])})
    w5c = mk(trace=(TA,))
    snap5c = {}
    T.safe(w5c._trace_internal, hx(0x502), snap5c)
    T.chk(snap5c.get("internal") == exp5 and [r["value"] for r in exp5] == ["1", "2", "3", "4", "5", "6", "7"]
          and [r["success"] for r in exp5] == [False, False, False, False, True, True, True],
          "N5 행 순서·성공 표시 = 종전 재귀(전위 · 되돌린 프레임 하위 전부 False · DELEGATECALL 제외)", snap5c.get("internal"))

    w6 = mk(trace=(TA,))
    h61, h62, h63 = hx(0x601), hx(0x602), hx(0x603)
    with open(TOVF, "w", encoding="utf-8") as f:
        f.write(json.dumps({"h": h61, "at": 100, "n": 1, "blk": 5, "sent": True}) + "\n")
        f.write(json.dumps({"h": h62, "at": "abc", "n": 2, "blk": 6, "sent": True}) + "\n")
        f.write("{not json\n")
        f.write(json.dumps({"h": h63, "at": 300, "n": 0, "blk": 7, "sent": False}) + "\n")
    rd6 = T.safe(w6._trace_overflow_read)
    rows6 = {r["h"]: r for r in rd6} if isinstance(rd6, list) else {}
    T.chk(set(rows6) == {h61, h62, h63}, "N6 숫자 칸이 깨진 줄 뒤의 줄도 읽음(종전: 깨진 줄에서 멈춰 그 뒤 유실 — 다음 되살림이 그 줄들 없이 파일을 다시 씀)",
          sorted(k[-4:] for k in rows6))
    T.chk(rows6.get(h62, {}).get("n") == 2 and rows6.get(h62, {}).get("blk") == 6 and rows6.get(h61, {}).get("at") == 100,
          "N6 깨진 줄도 해시·나머지 칸은 살림(깨진 칸만 기본값)", rows6.get(h62))
finally:
    evm_watch.time = real_time
    bf_engine.rpc_call = real_rpc

T.finish()
