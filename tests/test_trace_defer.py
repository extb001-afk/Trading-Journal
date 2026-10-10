#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import time

CH = "zerog"
W = ["0x" + f"{0xe0 + i:02x}" * 20 for i in range(2)]
W0 = W[0]
POLL = 60
URL = "http://127.0.0.1:9/rpc"
TA, TB = "http://127.0.0.1:9/trA", "http://127.0.0.1:9/trB"
CFG = {"backfill_months": 0, "chains": {CH: {"discovery": "rpc", "chain_id": 16661, "rpcs": [URL], "getlogs_span": 10_000_000,
                                             "conf_depth": 10, "blocks_per_day": 43200, "poll_sec": POLL, "cycle_budget_sec": 240,
                                             "rpc_log_span_caps": {URL: 5000}}},
       "wallets": [{"type": "evm", "chain": CH, "address": w, "label": "w"} for w in W]}
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
LOVF = os.path.join(common.STATE_DIR, f"leaf_later_overflow_{CH}.jsonl")
HEAD = 60_000_000
SAFE = HEAD - 10
E18 = 10 ** 18
X = "0x" + "77" * 20
RT = "0x" + "55" * 20
HoldError = getattr(evm_watch, "HoldError", RuntimeError)
TraceDeferred = getattr(evm_watch, "TraceDeferred", None)


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
evm_watch.time = FT
real_rpc, real_batch = bf_engine.rpc_call, bf_engine.rpc_batch
LOG = []
PLAN = {}
DEFAULT = ["408", 5.0]


class Crash(BaseException):
    pass


def fake_rpc(url, method, params, timeout=25.0, **k):
    LOG.append((url, method, dict(k, timeout=timeout)))
    p = PLAN.get((url, method)) or PLAN.get(method) or DEFAULT
    kind = p[0]
    if kind == "408":
        FT.t += min(float(p[1]), float(timeout))
        raise bf_engine.NetError('HTTP Error 408: Request Timeout ({"message":"Request timeout on the free tier"})', "http4xx", code=408)
    if kind == "429":
        FT.t += 0.2
        raise bf_engine.NetError("HTTP Error 429: Too Many Requests", "http429", code=429)
    if kind == "unsup":
        FT.t += 0.1
        raise bf_engine.NetError(f"rpc: the method {method} does not exist/is not available (-32601)", "rpc")
    if kind == "gone":
        FT.t += 0.1
        raise bf_engine.NetError("rpc: required historical state unavailable (reexec=0)", "rpc")
    if kind == "budget":
        FT.t += 0.05
        raise bf_engine.NetError("budget: 127.0.0.1 동시 요청 대기 0.0s 초과", "budget")
    if kind == "local":
        FT.t += 0.01
        e9 = bf_engine.NetError("quota: drpc 오늘(UTC) 몫 다 씀 — 다른 노드로", "quota")
        e9.local = True
        raise e9
    if kind == "bad":
        FT.t += 0.1
        return {"weird": 1} if method != "trace_transaction" else "nope"
    if kind == "ok":
        FT.t += 0.5
        h = str(params[0]).lower() if params else ""
        rows = p[1](h) if callable(p[1]) else p[1]
        if method == "debug_traceTransaction":
            return {"type": "CALL", "from": W0, "to": RT, "value": "0x0", "calls": [{"type": "CALL", "from": f9, "to": t9, "value": hex(v9)} for (f9, t9, v9) in rows]}
        if method == "trace_transaction":
            return [{"type": "call", "traceAddress": [], "action": {"from": W0, "to": RT, "value": "0x0", "callType": "call"}}] + [
                {"type": "call", "traceAddress": [i], "action": {"from": f9, "to": t9, "value": hex(v9), "callType": "call"}} for i, (f9, t9, v9) in enumerate(rows)]
        if method == "debug_traceBlockByNumber":
            return [{"txHash": hh, "result": {"type": "CALL", "from": X, "to": RT, "value": "0x0",
                                              "calls": [{"type": "CALL", "from": f9, "to": t9, "value": hex(v9)} for (f9, t9, v9) in rr]}}
                    for hh, rr in (p[2] if len(p) > 2 else {}).items()]
    raise bf_engine.NetError("예상 못 한 호출 " + method, "rpc")


bf_engine.rpc_call = fake_rpc


class Wr:
    def __init__(self):
        self.recs = []
        self.at = {}

    def append(self, rec):
        self.recs.append(rec)
        self.at.setdefault(rec.get("txhash"), FT.t)


def own_tx(h, blk, frm=W0, to=RT, value="0", inp="0x12345678"):
    return {"tx": {"hash": h, "block_number": blk, "from": frm, "to": to, "status": "ok", "value": value, "raw_input": inp + "00" * 32,
                   "fee": {"value": "0"}}, "token_transfers": [], "internal": []}


def hx(i):
    return "0x" + f"{i:064x}"


def mk(cur=None, wallets=None, txs=None, trace=(TA, TB)):
    common.atomic_write_json(CPATH, cur if cur is not None else {"_rpc_v": 1, "_start": 0})
    common.atomic_write_json(EPATH, [])
    for p9 in (TOVF, LOVF):
        if os.path.exists(p9):
            os.remove(p9)
    w = R(CFG, CH, list(wallets or [W0]), Wr())
    w.multicall = None
    w.trace_rpcs = list(trace)
    w._head = lambda: HEAD
    w._init = lambda safe: None
    w._health_cycle = lambda *a, **k: None
    w._batch = lambda calls: [None for _ in calls]
    tx9 = txs if txs is not None else {}
    w._rpc_synth_detail = lambda h: json.loads(json.dumps(tx9[h] if h in tx9 else own_tx(h, 7)))
    w._rpc_call = lambda m, p: {"nonce": "0x0", "from": W0, "to": RT}
    w._fill_symbols = lambda snaps: None
    return w


def disk():
    return common.read_json(CPATH, {})


def n_trace():
    return sum(1 for u, m, _k in LOG if m in ("debug_traceTransaction", "trace_transaction", "debug_traceBlockByNumber"))


class _NoBudget:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def tb(w, dl):
    f = getattr(w, "_trace_budget", None)
    return f(dl) if callable(f) else _NoBudget()


def sick(w):
    f = getattr(w, "_trace_sick", None)
    return bool(f()) if callable(f) else False


def live_cur(c, extra=None):
    cur = {"_rpc_v": 1, "_start": 0, "_handover": {"from": "fresh", "at": 1}, "_ns": {W0: [c, 0, "0", 0, "0"]}, "_bkns": {}, W0: c}
    cur.update(extra or {})
    return cur


try:
    PLAN.clear()
    DEFAULT[:] = ["408", 5.0]
    w1 = mk()
    w1._trace_want = lambda h, s: True
    hs1 = [hx(0x100 + i) for i in range(3)]
    LOG.clear()
    t01 = FT.t
    o1 = T.safe(w1._details, list(hs1), deadline=t01 + 1.0)
    el1, nc1 = FT.t - t01, n_trace()
    T.chk(el1 <= 1.0 + 1e-6 and nc1 <= 2, "D1 tx 3 · 노드 2 · 호출마다 5초 뒤 408 · 바깥 마감 1초 → 마감 안에 끝남(종전 12회 · 가상 60초 — 마감이 trace 에 안 닿음)",
          {"sec": round(el1, 2), "trace_calls": nc1})
    T.chk(LOG and all(k.get("deadline") is not None and float(k.get("timeout") or 99) <= 1.0 + 1e-6 for _u, _m, k in LOG),
          "D1 trace 호출마다 절대 마감·남은 시간 소켓 상한 전달(종전 = 마감 None · 30초)", [(m, k.get("timeout"), k.get("deadline") is not None) for _u, m, k in LOG])
    late1 = w1.__dict__.get("_trace_late") or {}
    T.chk(isinstance(o1, dict) and isinstance(o1.get(hs1[0]), Exception) and all(isinstance(o1.get(h), dict) and h in late1 for h in hs1[1:])
          and set((w1._trace_fail or {})) == {hs1[0]},
          "D1 실제로 부른 첫 tx = 종전 재시도 · 마감 뒤 tx = 시도 없이 늦은 채움 표식(실패 횟수 0 — 미시도와 실패 구분)",
          {"out": {h[-4:]: type(v).__name__ for h, v in (o1 or {}).items()} if isinstance(o1, dict) else o1, "fail": list(w1._trace_fail or {})})

    def d2(plan, order=None, budget=10.0):
        w = mk()
        PLAN.clear()
        PLAN.update(plan)
        if order is not None:
            w._order = order
        LOG.clear()
        t0 = FT.t
        err = None
        snap = {}
        try:
            with tb(w, t0 + budget):
                w._trace_internal(hx(0x200), snap)
        except Exception as e:
            err = e
        return FT.t - t0, err, w
    cases = {
        "느린 408 ×노드 2(8초)": {(TA, "debug_traceTransaction"): ("408", 8.0), (TB, "debug_traceTransaction"): ("408", 8.0),
                               (TA, "trace_transaction"): ("408", 8.0), (TB, "trace_transaction"): ("408", 8.0)},
        "429": {"debug_traceTransaction": ("429",), "trace_transaction": ("429",)},
        "영구 미지원 + 408": {(TA, "debug_traceTransaction"): ("unsup",), (TA, "trace_transaction"): ("unsup",),
                         (TB, "debug_traceTransaction"): ("408", 6.0), (TB, "trace_transaction"): ("408", 6.0)},
        "과거 상태 없음 + 429": {(TA, "debug_traceTransaction"): ("gone",), (TA, "trace_transaction"): ("gone",),
                            (TB, "debug_traceTransaction"): ("429",), (TB, "trace_transaction"): ("429",)},
        "형식 오류": {"debug_traceTransaction": ("bad",), "trace_transaction": ("bad",)},
    }
    res2 = {}
    for nm, pl in cases.items():
        el, err, _w = d2(pl)
        res2[nm] = (round(el, 2), type(err).__name__, bool(err is not None and R._trace_gone(err)))
    T.chk(all(v[0] <= 10.0 + 1e-6 for v in res2.values()), "D2 오류 종류마다 전체 걸린 시간 ≤ 마감(10초 — callTracer·parity·노드 넘김 전부 포함)", res2)
    T.chk(all(v[1] != "NoneType" and not v[2] for v in res2.values()), "D2 일시(408·429·형식·미지원+408·과거 상태 없음+429) = 일시 오류로 올림(큐 유지 — 영구 판정 아님)", res2)
    el2c, err2c, _w2c = d2({(TB, "debug_traceTransaction"): ("gone",), (TB, "trace_transaction"): ("gone",)},
                          order=lambda urls: [u for u in urls if u != TA])
    T.chk(err2c is not None and not R._trace_gone(err2c), "D2 열린 회로(A 미확인) + B 과거 상태 없음 = 일시(미확인 노드가 있으면 영구 아님)", type(err2c).__name__)
    el2g, err2g, _w2g = d2({"debug_traceTransaction": ("gone",), "trace_transaction": ("gone",)})
    T.chk(err2g is not None and R._trace_gone(err2g), "D2 모든 노드·메서드가 과거 상태 없음 = 영구(호출측이 internal 없이 확정)", type(err2g).__name__)
    el2d, err2d, _w2d = d2({(TA, "debug_traceTransaction"): ("408", 30.0)}, budget=3.0)
    T.chk(el2d <= 3.0 + 1e-6 and err2d is not None and not R._trace_gone(err2d) and (TB, "debug_traceTransaction") not in [(u, m) for u, m, _k in LOG],
          "D2 첫 노드가 마감을 다 쓰면 다음 노드·parity 를 시작하지 않음(미확인 = 일시)", {"sec": round(el2d, 2), "calls": [(u[-3:], m) for u, m, _k in LOG]})
    w2e = mk()
    PLAN.clear()
    LOG.clear()
    err2e = None
    try:
        with tb(w2e, FT.t - 1):
            w2e._trace_internal(hx(0x201), {})
    except Exception as e:
        err2e = e
    T.chk(TraceDeferred is not None and isinstance(err2e, TraceDeferred) and not LOG and not R._trace_gone(err2e),
          "D2 마감이 이미 지남 = 호출 0 · '시도 안 함'(TraceDeferred — 일시 · 시도 횟수 안 올림)", {"err": type(err2e).__name__, "calls": len(LOG)})

    PLAN.clear()
    DEFAULT[:] = ["408", 1.0]
    w3 = mk()
    w3._trace_want = lambda h, s: True
    LOG.clear()
    T.safe(w3._details, [hx(0x301)], late=True)
    T.safe(w3._details, [hx(0x302)], late=True)
    c3a = n_trace()
    sick3 = sick(w3)
    LOG.clear()
    o3 = T.safe(w3._details, [hx(0x303), hx(0x304)], late=True)
    w3._peek_ctx = True
    o3p = T.safe(w3._details, [hx(0x305)])
    w3._peek_ctx = False
    c3b = n_trace()
    late3 = w3.__dict__.get("_trace_late") or {}
    T.chk(sick3 and c3b == 0 and all(h in late3 for h in (hx(0x303), hx(0x304), hx(0x305)))
          and isinstance(o3, dict) and isinstance(o3.get(hx(0x303)), dict) and isinstance(o3p, dict) and isinstance(o3p.get(hx(0x305)), dict),
          "D3 연속 2회 실패 → 아픈 노드 · 그동안 따라잡기(늦은 채움 문맥)·엿보기 상세는 trace 0콜 · 바로 늦은 채움 표식(문서2 B2 — 엿보기 tx 마다 동기 trace)",
          {"sick": sick3, "calls_before": c3a, "calls_sick": c3b})
    LOG.clear()
    T.safe(w3._details, [hx(0x306)])
    c3c = [(u[-3:], m) for u, m, _k in LOG]
    T.chk(len(c3c) == 2 and all(m == "debug_traceTransaction" for _u, m in c3c),
          "D3 아픈 동안 꼬리(평시) 상세는 trace 를 시도(회복 확인) · 시간 초과 난 노드에 parity 를 다시 걸지 않음(대기 두 배 방지)", c3c)
    PLAN["debug_traceTransaction"] = ("ok", [])
    LOG.clear()
    T.safe(w3._details, [hx(0x307)])
    sick3b = sick(w3)
    LOG.clear()
    T.safe(w3._details, [hx(0x308)], late=True)
    T.chk(not sick3b and n_trace() == 1, "D3 trace 성공 1번이면 아픈 노드 풀림 → 늦은 채움 문맥도 다시 trace", {"sick": sick3b, "calls": n_trace()})

    PLAN.clear()
    DEFAULT[:] = ["408", 1.0]
    hs3b = [hx(0x3b0 + i) for i in range(5)]
    txs3b = {h: own_tx(h, SAFE - 50 + i) for i, h in enumerate(hs3b)}
    w3b = mk(live_cur(SAFE - 5000), txs=txs3b)
    w3b._scan_logs = lambda ws, c, target, dl: ({h: SAFE - 50 + i for i, h in enumerate(hs3b) if int(c) < SAFE - 50 + i <= int(target)}, int(target), None)
    LOG.clear()
    for _k in range(3):
        w3b._peek_ctx = True
        T.safe(w3b._peek_logs, SAFE - 100, SAFE, FT.t + 30, HEAD)
        w3b._peek_ctx = False
        FT.t += POLL
    tl3b = disk().get("_trace_later") or {}
    T.chk(n_trace() <= 8 and set(hs3b) <= {r.get("txhash") for r in w3b.writer.recs} and set(hs3b) <= set(tl3b),
          "D3b (B2) 엿보기 3사이클 · tx 5건 trace 계속 실패 → trace 호출 ≤ 8(종전 60 — 사이클마다 tx 마다 동기) · 5건 모두 방출 · 늦은 채움 큐(디스크)",
          {"calls": n_trace(), "emitted": len(w3b.writer.recs), "tl": len(set(hs3b) & set(tl3b))})

    PLAN.clear()
    DEFAULT[:] = ["408", 5.0]
    L4 = SAFE - 20_000
    Y4 = L4 + 100

    def st4(w, ys):
        def st(pairs, strict=False):
            m = w.__dict__.setdefault("_st_memo", {})
            for (a, b) in pairs:
                m.setdefault((a, b), (0, E18 if b >= ys.get(a, 10 ** 12) else 0))
            return {p: m[p] for p in pairs}
        return st
    w4 = mk(live_cur(L4))
    w4._states = st4(w4, {W0: Y4})
    w4._scan_logs = lambda ws, c, target, dl: ({}, int(target), None)
    w4._scan_blocks = lambda lo, hi, ww, dl, **k: ({}, True)
    w4._head_peek = lambda *a, **k: None
    w4._trace_sick_until = FT.t + 300
    LOG.clear()
    t04 = FT.t
    T.safe(w4.cycle)
    d4 = disk()
    k4 = f"{W0[:12]}:{Y4}"
    T.chk(n_trace() == 0 and int(d4.get(W0) or 0) == SAFE,
          "D4 따라잡는 라이브 걸음 · 로그 없는 내부 입금 잎 · trace 노드 아픔 → 잎 trace(tx·블록 trace) 동기 호출 0 · 그 사이클에 헤드(종전: tx trace 2 + 블록 trace 1 동기 · 차선 모드는 120초 보류)",
          {"trace_calls": n_trace(), "cursor": d4.get(W0), "sec": round(FT.t - t04, 1)})
    T.chk(k4 in (d4.get("_leaf_later") or {}) and int((d4.get("_leaf_later") or {}).get(k4, {}).get("n", -1)) == 0,
          "D4 건너뛴 잎 = 그 지갑·블록을 '나중에 다시'(_leaf_later · 디스크 · 시도 0)에 — 해시를 모르는 내부 입금도 나중에 블록 trace 로 회수(문서1 7.3 B)",
          d4.get("_leaf_later"))
    w4p = mk(live_cur(L4))
    w4p._states = st4(w4p, {W0: Y4})
    w4p._scan_blocks = lambda lo, hi, ww, dl, **k: ({}, True)
    w4p._trace_sick_until = FT.t + 300
    w4p._peek_fail_ws = set()
    w4p.cursor["_peek_ns"] = {W0: [L4, 0, "0", 0, "0"]}
    LOG.clear()
    r4p = T.safe(w4p._native, W0, L4, L4 + 1000, [], FT.t + 60, nk="_peek_ns", head=HEAD)
    T.chk(n_trace() == 0 and k4 in (w4p.cursor.get("_leaf_later") or {}) and W0 not in (w4p._peek_fail_ws or set()),
          "D4 엿보기도 아픈 노드면 잎 trace 0 · '나중에 다시'에 넣고 그 지갑 엿보기는 끝(같은 잎을 사이클마다 다시 안 함)",
          {"calls": n_trace(), "ll": list(w4p.cursor.get("_leaf_later") or {}), "r": r4p if not isinstance(r4p, dict) or "_exc" in r4p else "ok"})
    w4t = mk(live_cur(SAFE - 50))
    w4t._states = st4(w4t, {W0: SAFE - 20})
    w4t._scan_blocks = lambda lo, hi, ww, dl, **k: ({}, True)
    w4t._bisect = lambda ww, a, b, sa, sb, pool, dl: [(SAFE - 21, SAFE - 20, (0, 0), (0, E18))]
    LOG.clear()
    r4t = T.safe(w4t._native, W0, SAFE - 50, SAFE, [], FT.t - 1, nk="_ns", head=HEAD)
    T.chk(n_trace() == 0 and isinstance(r4t, dict) and "HoldError" in str(r4t.get("_exc")),
          "D4 평시 꼬리가 정합 마감을 넘김 = 잎 trace 안 걸고 종전 보류(커서 유지 · 다음 사이클)", {"calls": n_trace(), "r": r4t})

    w5 = mk()
    H5 = hx(0x501)
    w5._snap_memo = {H5: own_tx(H5, 9)}
    w5._trace_late = {H5: 1}
    for i in range(20_000):
        w5._trace_late[hx(0x10_0000 + i)] = 1
    w5._trace_late_add(hx(0x502))
    T.chk(H5 not in w5._trace_late and H5 not in w5._snap_memo,
          "D5 표식 2만 초과 = 오래된 표식을 덜어 내되 그 tx 상세 메모도 버림(다음 걸음이 다시 상세·trace → 다시 표식·등록 · 종전: 메모에서 internal 없이 방출 · 큐 등록 없음)",
          {"late": H5 in w5._trace_late, "memo": H5 in w5._snap_memo})
    C5 = SAFE - 5000
    txs5 = {H5: own_tx(H5, C5 + 100)}
    w5b = mk(live_cur(C5), txs=txs5)
    w5b._scan_logs = lambda ws, c, target, dl: ({H5: C5 + 100}, int(target), None)
    w5b._states = lambda pairs, strict=False: {p: ((1 if p[1] >= C5 + 100 else 0), 0) for p in pairs}
    w5b._late_ctx = True
    real_native5 = w5b._native
    w5b._native = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("잎 블록 스캔 미완 — 다음 사이클 재시도"))
    T.safe(w5b._advance, [W0], C5, SAFE, HEAD, FT.t + 100)
    in_memo5 = H5 in (w5b.__dict__.get("_snap_memo") or {})
    for i in range(20_001):
        w5b._trace_late_add(hx(0x20_0000 + i))
    w5b._native = real_native5
    T.safe(w5b._advance, [W0], C5, SAFE, HEAD, FT.t + 100)
    w5b._late_ctx = False
    tl5 = disk().get("_trace_later") or {}
    T.chk(in_memo5 and H5 in [r.get("txhash") for r in w5b.writer.recs] and H5 in tl5 and tl5[H5].get("sent") is True,
          "D5 (재현 R3) 걸음 실패 뒤 표식 넘침 → 다음 걸음이 방출한 tx 도 늦은 채움 큐(디스크 · 방출 사실) — 종전: 큐 없음 · internal 영구 누락",
          {"memo": in_memo5, "emitted": len(w5b.writer.recs), "tl": tl5.get(H5)})
    T.chk(not any(h == H5 for h in (w5b.__dict__.get("_trace_late") or {})),
          "D5 걸음 끝 = 그 걸음 tx 의 표식 정리(등록 뒤 지움 — 방출 안 되는 표식이 쌓여 넘침에 닿지 않게)", len(w5b.__dict__.get("_trace_late") or {}))

    C6 = SAFE - 5000
    Y6 = C6 + 300
    H6 = hx(0x601)
    txs6 = {H6: own_tx(H6, Y6, frm=X, to=W0, value=str(E18))}
    w6 = mk(live_cur(C6), txs=txs6)
    w6.emitted.add(H6)
    w6._trace_want = lambda h, s: True
    w6._states = lambda pairs, strict=False: {p: (0, E18 + 7 if p[1] >= Y6 else 0) for p in pairs}
    w6._scan_blocks = lambda lo, hi, ww, dl, **k: ({H6: Y6}, True)
    w6._trace_sick_until = FT.t + 300
    w6._late_ctx = True
    T.safe(w6._native, W0, C6, C6 + 1000, [], FT.t + 100, nk="_ns", head=HEAD)
    w6._late_ctx = False
    tl6 = w6.cursor.get("_trace_later") or {}
    T.chk(H6 in tl6 and tl6[H6].get("sent") is True,
          "D6 (재현 R2) 이미 방출한 tx 를 잎에서 다시 받았는데 trace 가 또 실패·생략 → 늦은 채움 큐(sent=True) — 종전: 방출 루프가 건너뛰어 등록 없음",
          tl6.get(H6))

    C7 = SAFE - 5000
    H7 = hx(0x701)
    txs7 = {H7: own_tx(H7, C7 + 100)}

    def rig7():
        w = mk(live_cur(C7), txs=txs7)
        w._scan_logs = lambda ws, c, target, dl: ({H7: C7 + 100}, int(target), None)
        w._states = lambda pairs, strict=False: {p: ((1 if p[1] >= C7 + 100 else 0), 0) for p in pairs}
        w._head_peek = lambda *a, **k: None
        return w
    PLAN.clear()
    DEFAULT[:] = ["408", 2.0]
    w7 = rig7()

    def boom(rec):
        raise Crash("종료(방출 도중)")
    w7.writer.append = boom
    try:
        w7.cycle()
    except Crash:
        pass
    d7 = disk()
    T.chk(H7 in (d7.get("_trace_later") or {}) and int(d7.get(W0) or 0) == C7 and H7 not in common.read_json(EPATH, []),
          "D7 방출 도중 종료 — 늦은 채움 항목은 방출 전에 이미 디스크(선등록 · 커서 전진 없음)", {"tl": (d7.get("_trace_later") or {}).get(H7), "cur": d7.get(W0)})
    w7b = rig7()
    real_aw = common.atomic_write_json
    st7 = {"e": False}

    def aw(path, obj, *a, **k):
        if path == EPATH:
            st7["e"] = True
        elif path == CPATH and st7["e"]:
            raise Crash("종료(emitted 저장 뒤)")
        return real_aw(path, obj, *a, **k)
    common.atomic_write_json = aw
    try:
        try:
            w7b.cycle()
        except Crash:
            pass
    finally:
        common.atomic_write_json = real_aw
    d7b = disk()
    T.chk(H7 in common.read_json(EPATH, []) and H7 in (d7b.get("_trace_later") or {}),
          "D7 (B6) emitted 저장 뒤 · 커서 저장 전 종료 → 디스크 늦은 채움 큐에 그 tx 가 있음(종전: emitted 라 다시 상세·등록 안 함 = internal 영구 누락)",
          {"tl": (d7b.get("_trace_later") or {}).get(H7)})
    FT.t += 400
    PLAN.clear()
    PLAN["debug_traceTransaction"] = ("ok", [(RT, W0, 7)])
    w7c = R(CFG, CH, [W0], Wr())
    for k9, v9 in (("multicall", None), ("trace_rpcs", [TA, TB])):
        setattr(w7c, k9, v9)
    w7c._head = lambda: HEAD
    w7c._init = lambda safe: None
    w7c._health_cycle = lambda *a, **k: None
    w7c._batch = lambda calls: [None for _ in calls]
    w7c._rpc_synth_detail = lambda h: json.loads(json.dumps(txs7[h]))
    w7c._rpc_call = lambda m, p: {"nonce": "0x0", "from": W0, "to": RT}
    w7c._fill_symbols = lambda snaps: None
    w7c._scan_logs = lambda ws, c, target, dl: ({H7: C7 + 100}, int(target), None)
    w7c._states = lambda pairs, strict=False: {p: ((1 if p[1] >= C7 + 100 else 0), 0) for p in pairs}
    w7c._head_peek = lambda *a, **k: None
    T.safe(w7c.cycle)
    re7 = [r for r in w7c.writer.recs if r.get("txhash") == H7 and (r.get("snapshot") or {}).get("internal")]
    T.chk(re7 and H7 not in (disk().get("_trace_later") or {}),
          "D7 다시 뜬 뒤 노드 회복 → 늦은 채움이 internal 을 채워 재방출 · 큐에서 빠짐", {"reemit": len(re7), "tl": (disk().get("_trace_later") or {}).get(H7)})

    w8 = mk()
    w8.state_rpcs = [URL]
    w8._order = lambda urls: list(urls)
    old8 = (W0, 11)
    w8._st_memo = {old8: (1, 2)}
    for i in range(R.ST_MEMO_MAX):
        w8._st_memo[(W[1], 100 + i)] = (0, 0)

    def fb8(url, calls, **k):
        return ["0x1" for _ in calls]
    bf_engine.rpc_batch = fb8
    try:
        r8 = T.safe(w8._states, [old8, (W0, 99)])
    finally:
        bf_engine.rpc_batch = real_batch
    T.chk(isinstance(r8, dict) and "_exc" not in r8 and r8.get(old8) == (1, 2) and r8.get((W0, 99)) == (1, 1),
          "D8 상태 메모 2만 초과 덜어내기 — 이 호출이 요청한 옛 쌍은 남김(종전: KeyError → 라이브 루프가 못 잡고 사이클 통째 중단)", r8)

    PLAN.clear()
    DEFAULT[:] = ["408", 1.0]
    C9 = SAFE - 10_000
    H9 = hx(0x901)
    txs9 = {H9: own_tx(H9, SAFE - 5)}
    w9 = mk(live_cur(C9), txs=txs9)
    w9._scan_logs = lambda ws, c, target, dl: ({H9: SAFE - 5} if int(c) < SAFE - 5 <= int(target) else {}, int(target), None)
    w9._trace_sick_until = FT.t + 300

    def pn9(*a, **k):
        raise bf_engine.NetError("엿보기 상태 조회 시간 초과", "timeout")
    w9._peek_native = pn9

    def adv9(*a, **k):
        raise RuntimeError("이분 탐색 예산 소진")
    w9._advance = adv9
    T.safe(w9.cycle)
    d9 = disk()
    T.chk(H9 in [r.get("txhash") for r in w9.writer.recs] and H9 in (d9.get("_trace_later") or {}),
          "D9 (B13) 엿보기가 internal 없이 방출(아픈 노드) → 엿보기 중단 + 같은 사이클 라이브 걸음 실패(디스크 커서로 되돌림) → 늦은 채움 항목 디스크에 남음(종전: 메모리 표식 소실)",
          {"emitted": [r.get("txhash")[-4:] for r in w9.writer.recs], "tl": list(d9.get("_trace_later") or {})})
    w9b = mk(live_cur(C9))
    w9b.cursor["_trace_later"] = {H9: {"at": int(FT.t), "n": 0, "next": int(FT.t) + 120, "blk": 1, "sent": True}}
    T.safe(w9b._lv_span_persist, 2500)
    T.chk(H9 in (disk().get("_trace_later") or {}) and H9 in (w9b.cursor.get("_trace_later") or {}) and disk().get("_lvspan") == 2500,
          "D9 라이브 걸음 실패 되돌리기(_lv_span_persist)가 메모리 늦은 채움 항목을 디스크 사본으로 덮어 버리지 않음", disk().get("_trace_later"))

    w10 = mk()
    w10.TRACE_LATER_MAX = 4
    now10 = int(FT.t)
    w10.cursor["_trace_later"] = {hx(0xa00 + i): {"at": now10, "n": 0, "next": now10 + 9999, "blk": 1, "sent": True} for i in range(4)}
    w10._trace_late = {hx(0xa10 + j): 1 for j in range(6)}
    for j in range(6):
        w10._emit(hx(0xa10 + j), own_tx(hx(0xa10 + j), 5), HEAD)
    T.chk(len(w10.cursor["_trace_later"]) == 4 and int(w10.cursor.get("_trace_later_overflow") or 0) == 6 and os.path.exists(TOVF),
          "D10 늦은 채움 큐(상한) 포화 = 새 항목 6건 넘침 파일로(버림 0 · 종전 2,000 넘으면 오래된 것 조용히 버림)",
          {"q": len(w10.cursor["_trace_later"]), "ovf": w10.cursor.get("_trace_later_overflow")})
    w10.TRACE_LATER_MAX = 20
    w10._trace_internal = lambda h, snap: None
    T.safe(w10._trace_later_step, HEAD)
    tl10 = w10.cursor.get("_trace_later") or {}
    T.chk(not os.path.exists(TOVF) and not w10.cursor.get("_trace_later_overflow") and all(hx(0xa10 + j) not in tl10 for j in range(3)),
          "D10 자리가 나면 넘침 파일에서 되살려 바로 처리(먼저 넘친 것부터)", {"left": len(tl10)})
    w10b = mk()
    now10b = int(FT.t)
    w10b.cursor["_trace_later"] = {"0xold0": {"at": now10b - 40 * 86400, "n": 0, "next": 0, "blk": 1, "sent": True},
                                   "0xold6": {"at": now10b - 40 * 86400, "n": 6, "next": now10b + 999, "blk": 1, "sent": True}}

    def tdf(h, snap):
        raise TraceDeferred() if TraceDeferred else RuntimeError("x")
    w10b._trace_internal = tdf
    T.safe(w10b._trace_later_step, HEAD)
    tl10b = w10b.cursor.get("_trace_later") or {}
    T.chk("0xold0" in tl10b and int(tl10b["0xold0"].get("n") or 0) == 0 and "0xold6" not in tl10b,
          "D10 만료 = 실제 5회 이상 시도 ∧ 30일만 · 마감으로 시작 못 한 시도는 횟수 0 그대로(종전: 미시도도 나이만으로 · 미시도에 횟수 증가)", tl10b)
    w10c = mk()
    now10c = int(FT.t)
    w10c.cursor["_trace_later"] = {"0xpre": {"at": now10c - 60, "n": 0, "next": 0, "blk": 1, "sent": False}}
    n10c = {"t": 0}
    w10c._trace_internal = lambda h, snap: n10c.__setitem__("t", n10c["t"] + 1)
    T.safe(w10c._trace_later_step, HEAD)
    a10 = n10c["t"]
    w10c.cursor["_trace_later"]["0xpre"]["at"] = now10c - 4000
    T.safe(w10c._trace_later_step, HEAD)
    T.chk(a10 == 0 and n10c["t"] == 1, "D10 방출 전 선등록 = 방출 확인 전엔 기다리고 1시간 넘으면 그래도 시도(조용히 묵히지 않음)", {"before": a10, "after": n10c["t"]})
    w10d = mk()
    w10d.LEAF_LATER_MAX = 3
    w10d.cursor["_leaf_later"] = {f"k{i}": {"w": W0, "blk": 10 + i, "at": 1, "n": 0, "next": 0} for i in range(3)}
    T.safe(getattr(w10d, "_leaf_defer", lambda *a: None), W0, 777)
    rows10 = evm_watch.leaf_overflow_read(LOVF)
    T.chk(len(w10d.cursor["_leaf_later"]) == 3 and [r["blk"] for r in rows10] == [777] and int(w10d.cursor.get("_leaf_overflow") or 0) == 1,
          "D10 '나중에 다시' 잎 큐(상한) 포화도 같은 정책 — 넘침 파일(버림 0)", {"rows": rows10})

    PLAN.clear()
    DEFAULT[:] = ["408", 20.0]
    C11 = SAFE - 30
    now11 = int(FT.t)
    cur11 = live_cur(C11, {"_leaf_later": {f"{W0[:12]}:{1000 + i}": {"w": W0, "blk": 1000 + i, "at": now11 - 100 + i, "n": 0, "next": 0} for i in range(6)},
                           "_trace_later": {hx(0xb00 + i): {"at": now11 - 100 + i, "n": 0, "next": 0, "blk": 5, "sent": True} for i in range(6)}})
    w11 = mk(cur11)
    w11.emitted.update(cur11["_trace_later"])
    state11 = {"n": 0}

    def scan11(ws, c, target, dl):
        h = hx(0xc00 + state11["n"])
        return {h: int(target)}, int(target), None
    w11._scan_logs = scan11
    w11._rpc_synth_detail = lambda h: {"tx": {"hash": h, "block_number": SAFE, "from": X, "to": "0x" + "d4" * 20, "status": "ok", "value": "0"},
                                       "token_transfers": [{"from": X, "to": W0, "value": "5", "token": {"address": "0x" + "d4" * 20}}], "internal": []}
    w11._states = lambda pairs, strict=False: {p: (0, 0) for p in pairs}
    w11._head_peek = lambda *a, **k: None
    durs11, lag11 = [], []
    for k in range(8):
        state11["n"] = k
        hd = HEAD + k * 100
        w11._head = (lambda v: (lambda: v))(hd)
        t0 = FT.t
        T.safe(w11.cycle)
        durs11.append(FT.t - t0)
        hk = hx(0xc00 + k)
        lag11.append(round(w11.writer.at.get(hk, 1e18) - t0, 1))
        FT.t = max(FT.t, t0 + POLL)
    T.chk(all(x <= 1.0 for x in lag11), "D11 잎·늦은 채움 큐가 20초 408 노드에 막혀도 최신 입금은 사이클 앞부분(라이브 차선 먼저)에 방출(종전: 잎 재시도가 라이브 앞에서 무예산 첫 1건)",
          lag11)
    T.chk(max(durs11) <= 240 + 60 + 30 + 2, "D11 사이클 길이 ≤ 예산 + 잎 몫(60초) + 늦은 채움 몫(30초) — 첫 1건도 상한", [round(x, 1) for x in durs11])
    ll11 = w11.cursor.get("_leaf_later") or {}
    tl11 = w11.cursor.get("_trace_later") or {}
    tried_l = sorted(int(e["blk"]) for e in ll11.values() if int(e.get("n") or 0) >= 1)
    tried_t = sorted(h for h, e in tl11.items() if int(e.get("n") or 0) >= 1)
    T.chk(len(tried_l) >= 6 and len(tried_t) >= 6, "D11 늘 바쁜 라이브 · 아픈 노드에서도 잎·늦은 채움 큐 항목이 매 사이클 최소 1건씩 실제 시도(굶지 않음 · 8사이클에 전부)",
          {"leaf_tried": tried_l, "trace_tried": len(tried_t)})

    PLAN.clear()
    DEFAULT[:] = ["408", 5.0]
    L12 = SAFE - 86_400
    N12 = 300
    txs12 = {hx(0x5000 + i): own_tx(hx(0x5000 + i), L12 + 1 + (86_400 * i) // N12) for i in range(N12)}
    blk12 = sorted((v["tx"]["block_number"], h) for h, v in txs12.items())
    w12 = mk(live_cur(L12), txs=txs12)
    w12._scan_logs = lambda ws, c, target, dl: ({h: b for b, h in blk12 if int(c) < b <= int(target)}, int(target), None)
    w12._states = lambda pairs, strict=False: {p: (sum(1 for bb, _h in blk12 if bb <= p[1]), 0) for p in pairs}
    w12._head_peek = lambda *a, **k: None
    LOG.clear()
    t012 = FT.t
    T.safe(w12.cycle)
    d12 = disk()
    tl12 = d12.get("_trace_later") or {}
    T.chk(int(d12.get(W0) or 0) == SAFE and FT.t - t012 <= 120 and n_trace() <= 8,
          "D12 최근 창 86,400블록 · 내 컨트랙트 호출 300건 · trace 노드 408 ×2 → 첫 사이클 헤드 · trace 시도 ≤ 8(아픈 노드 · 종전 a0e04716 = 20회·100초 · 14차 = 몇 시간)",
          {"cursor": d12.get(W0), "sec": round(FT.t - t012, 1), "trace_calls": n_trace()})
    T.chk(len(tl12) == N12 and all(int(e.get("n") or 0) <= 1 and e.get("sent") is True for e in tl12.values()) and sum(1 for e in tl12.values() if int(e.get("n") or 0) == 0) >= N12 - 2,
          "D12 300건 전부 늦은 채움 큐(디스크 · 방출 사실 · 실제로 부른 1~2건 빼고 시도 0)", {"q": len(tl12)})
    PLAN.clear()
    PLAN["debug_traceTransaction"] = ("ok", [(RT, W0, 9)])
    w12._trace_sick_until = 0.0
    w12._trace_nf = 0
    for _k in range(30):
        FT.t += 7200
        T.safe(w12.cycle)
        if not (disk().get("_trace_later") or {}):
            break
    re12 = {r.get("txhash") for r in w12.writer.recs if (r.get("snapshot") or {}).get("internal") and r.get("repair") == "int_fill"}
    T.chk(not (disk().get("_trace_later") or {}) and len(re12) == N12,
          "D12 노드 회복 뒤 큐가 비며 300건 전부 internal 채워 재방출(int_fill — 빠진 내부 이동 0)", {"left": len(disk().get("_trace_later") or {}), "reemit": len(re12)})

    PLAN.clear()
    PLAN["debug_traceTransaction"] = ("408", 30.0)
    PLAN["trace_transaction"] = ("ok", [(RT, W0, 11)])
    H13 = hx(0xd13)
    w13 = mk(live_cur(SAFE), txs={H13: own_tx(H13, SAFE - 9)})
    w13.emitted.add(H13)
    now13 = int(FT.t)
    w13.cursor["_trace_later"] = {H13: {"at": now13 - 60, "n": 0, "next": 0, "blk": SAFE - 9, "sent": True}}
    w13._trace_sick_until = FT.t + 10_000
    for _k in range(4):
        T.safe(w13._trace_later_step, HEAD)
        if H13 not in (w13.cursor.get("_trace_later") or {}):
            break
        FT.t = max(FT.t, float((w13.cursor["_trace_later"][H13] or {}).get("next") or FT.t)) + 1
    re13 = [r for r in w13.writer.recs if r.get("txhash") == H13 and (r.get("snapshot") or {}).get("internal")]
    T.chk(re13 and H13 not in (w13.cursor.get("_trace_later") or {}),
          "D13 (코덱스 ba705 #1) callTracer 가 30초 예산을 다 쓰고 408 · parity 는 정상 → 다음 재시도는 parity 부터(같은 절대 예산) — internal 회수(종전: 매번 callTracer 가 예산 소진 · 30일·5회 뒤 삭제)",
          {"reemit": len(re13), "q": w13.cursor.get("_trace_later")})

    for kind14 in ("budget", "local"):
        PLAN.clear()
        DEFAULT[:] = [kind14]
        w14 = mk()
        now14 = int(FT.t)
        w14.cursor["_trace_later"] = {hx(0xd14): {"at": now14 - 40 * 86400, "n": 4, "next": 0, "blk": 5, "sent": True}}
        w14._trace_nf = 1
        T.safe(w14._trace_later_step, HEAD)
        e14 = (w14.cursor.get("_trace_later") or {}).get(hx(0xd14)) or {}
        T.chk(int(e14.get("n") or -1) == 4 and int(getattr(w14, "_trace_nf", 0) or 0) == 1 and not sick(w14),
              f"D14 (ba705 #2) trace 노드 '{kind14}' 거절(HTTP 전송 전) = 시도 횟수·아픈 노드 계수 안 올림(종전: n 4→5 · 30일 넘은 항목 삭제 길 · 아픈 노드 진입)",
              {"e": e14, "nf": getattr(w14, "_trace_nf", None)})
        w14b = mk()
        LOG.clear()
        err14 = None
        try:
            with tb(w14b, FT.t + 60):
                w14b._trace_block(123)
        except Exception as e:
            err14 = e
        T.chk(TraceDeferred is not None and isinstance(err14, TraceDeferred) and int(getattr(w14b, "_trace_nf", 0) or 0) == 0,
              f"D14 블록 trace 도 '{kind14}' 거절만이면 '시도 안 함'(TraceDeferred) · 아픈 노드 계수 0", {"err": type(err14).__name__, "nf": getattr(w14b, "_trace_nf", None)})
    DEFAULT[:] = ["408", 5.0]

    T.chk(int(getattr(R, "TRACE_LATER_MAX", 0)) == 2000, "D15 커서 안 늦은 채움 큐 상한 = 2,000(옛 판이 넘는 만큼 오래된 것부터 지우는 상한 — 롤백해도 커서 항목을 안 지움)",
          getattr(R, "TRACE_LATER_MAX", None))
    w15 = mk()
    now15 = int(FT.t)
    w15._trace_late = {}
    for i in range(2100):
        h = hx(0x150000 + i)
        w15._trace_late[h] = 1
        w15._trace_later_mark(h, own_tx(h, 5))
    rows15 = w15._trace_overflow_read() if hasattr(w15, "_trace_overflow_read") else []
    T.chk(len(w15.cursor.get("_trace_later") or {}) == 2000 and len(rows15) == 100 and int(w15.cursor.get("_trace_later_overflow") or 0) == 100,
          "D15 2,100건 = 커서 2,000 + 넘침 파일 100(버림 0)", {"q": len(w15.cursor.get("_trace_later") or {}), "file": len(rows15)})
    w15b = mk()
    w15b.cursor["_trace_later"] = {hx(0x160000 + i): {"at": now15 - 5000 + i, "n": 0, "next": now15 + 9999, "blk": 1, "sent": True} for i in range(2500)}
    T.safe(w15b._trace_later_step, HEAD)
    dq15 = disk().get("_trace_later") or {}
    rows15b = w15b._trace_overflow_read() if hasattr(w15b, "_trace_overflow_read") else []
    T.chk(len(dq15) == 2000 and len(rows15b) == 500 and all(hx(0x160000 + i) in dq15 for i in range(2000)),
          "D15 커서 큐가 2,000 을 넘으면(옛 보관분 되살림 등) 새 것부터 넘침 파일로 내려 디스크 커서 ≤ 2,000(오래된 것이 먼저 시도)", {"disk": len(dq15), "file": len(rows15b)})

    PLAN.clear()
    PLAN["debug_traceTransaction"] = ("408", 5.0)
    PLAN["trace_transaction"] = ("408", 5.0)
    w16 = mk()
    w16._trace_want = lambda h, s: True
    T.safe(w16._details, [hx(0x1601)])
    T.safe(w16._details, [hx(0x1602)])
    s16 = sick(w16)
    ts16 = FT.t
    PLAN["trace_transaction"] = ("ok", [(RT, W0, 3)])
    ok16 = None
    for k in range(12):
        FT.t += 45
        o16 = T.safe(w16._details, [hx(0x1610 + k)])
        if isinstance(o16, dict) and isinstance(o16.get(hx(0x1610 + k)), dict) and o16[hx(0x1610 + k)].get("internal"):
            ok16 = round(FT.t - ts16)
            break
    T.chk(s16 and ok16 is not None and ok16 <= 300 + 90 and not sick(w16),
          "D16 (ba705 #4) 아픈 노드 만료는 처음 진입 때 고정(실패마다 연장 안 함) → 실패가 45초마다 이어져도 5분 뒤 정상 경로가 parity 까지 확인해 회복(종전: 영영 아픔 · parity 만 회복한 노드를 안 봄)",
          {"sick0": s16, "recovered_after_s": ok16, "sick_now": sick(w16)})

    def mixed17(kind):
        PLAN.clear()
        PLAN[(TB, "debug_traceTransaction")] = ("408", 30.0)
        PLAN[(TB, "trace_transaction")] = ("ok", [(RT, W0, 13)])
        if kind == "local":
            PLAN[(TA, "debug_traceTransaction")] = ("local",)
            PLAN[(TA, "trace_transaction")] = ("local",)

        def setup(w):
            if kind == "circuit":
                w._order = lambda urls: [u for u in urls if u != TA]
        return setup
    for kind17 in ("circuit", "local"):
        setup17 = mixed17(kind17)
        H17 = hx(0x1700 + (1 if kind17 == "local" else 0))
        w17 = mk(live_cur(SAFE), txs={H17: own_tx(H17, SAFE - 9)})
        setup17(w17)
        w17.cursor["_hq"] = {H17: 0}
        got17 = None
        for k in range(4):
            T.safe(w17._hq_step, HEAD, FT.t + 10)
            if H17 not in (w17.cursor.get("_hq") or {}):
                got17 = k + 1
                break
            FT.t += POLL
        re17 = [r for r in w17.writer.recs if r.get("txhash") == H17 and (r.get("snapshot") or {}).get("internal")]
        T.chk(got17 is not None and got17 <= 2 and re17,
              f"D17 (ba710) 인계 큐 · 노드 A {kind17}(미전송) + B callTracer 30초 408 · parity 정상 → 다음 사이클 parity 먼저로 회수(종전: A 의 미전송 오류가 대표 오류라 교대 계수가 안 늘어 매번 callTracer 부터 — 영영 못 풂)",
              {"cycle": got17, "reemit": len(re17), "hq": w17.cursor.get("_hq"), "try": w17.__dict__.get("_hq_try")})
        H17b = hx(0x1710 + (1 if kind17 == "local" else 0))
        w17b = mk(live_cur(SAFE), txs={H17b: own_tx(H17b, SAFE - 9)})
        setup17(w17b)
        w17b.emitted.add(H17b)
        w17b.cursor["_trace_later"] = {H17b: {"at": int(FT.t) - 60, "n": 0, "next": 0, "blk": SAFE - 9, "sent": True}}
        for k in range(4):
            T.safe(w17b._trace_later_step, HEAD)
            if H17b not in (w17b.cursor.get("_trace_later") or {}):
                break
            FT.t = max(FT.t, float((w17b.cursor["_trace_later"][H17b] or {}).get("next") or FT.t)) + 1
        re17b = [r for r in w17b.writer.recs if r.get("txhash") == H17b and (r.get("snapshot") or {}).get("internal")]
        T.chk(re17b and H17b not in (w17b.cursor.get("_trace_later") or {}),
              f"D17 늦은 채움도 같은 혼합 오류(A {kind17} + B 408·parity 정상)에서 교대해 회수", {"reemit": len(re17b), "q": w17b.cursor.get("_trace_later")})
    PLAN.clear()
    PLAN[(TA, "debug_traceTransaction")] = ("local",)
    PLAN[(TA, "trace_transaction")] = ("local",)
    PLAN[(TB, "debug_traceTransaction")] = ("408", 2.0)
    PLAN[(TB, "trace_transaction")] = ("408", 2.0)
    w17c = mk()
    err17 = None
    try:
        with tb(w17c, FT.t + 60):
            w17c._trace_internal(hx(0x1720), {})
    except Exception as e:
        err17 = e
    T.chk(err17 is not None and not R._trace_untried(err17) and "408" in str(err17),
          "D17 혼합 오류의 대표 오류 = 실제로 보낸 노드 것(408) — 미전송 거절이 오류 목록 앞에 있어도(오류 순서에 기대지 않음)", {"err": str(err17)[:80]})

    for kind18 in ("mixed", "allbad"):
        PLAN.clear()
        PLAN[(TB, "debug_traceTransaction")] = ("bad",)
        PLAN[(TB, "trace_transaction")] = ("bad",)
        if kind18 == "mixed":
            PLAN[(TA, "debug_traceTransaction")] = ("local",)
            PLAN[(TA, "trace_transaction")] = ("local",)
        else:
            PLAN[(TA, "debug_traceTransaction")] = ("bad",)
            PLAN[(TA, "trace_transaction")] = ("bad",)
        H18 = hx(0x1800 + (1 if kind18 == "allbad" else 0))
        w18 = mk(live_cur(SAFE), txs={H18: own_tx(H18, SAFE - 9)})
        w18.cursor["_hq"] = {H18: 0}
        for k in range(8):
            T.safe(w18._hq_step, HEAD, FT.t + 10)
            FT.t += POLL
        d18 = disk()
        in_hq, tl18 = H18 in (d18.get("_hq") or {}), (d18.get("_trace_later") or {}).get(H18)
        if kind18 == "mixed":
            T.chk(in_hq or (tl18 and tl18.get("sent") is True),
                  "D18 (ba715) 인계 큐 · 노드 A 미전송(하루 장부) + B callTracer·parity 형식 오류 8번 → 항목 남음(혼합 = 결정적 실패로 안 셈 · 종전: 5번 뒤 삭제 — 늦은 채움에도 안 감)",
                  {"hq": d18.get("_hq"), "tl": tl18})
        else:
            T.chk(not in_hq and tl18 and tl18.get("sent") is True and int(tl18.get("n") or 0) == 0,
                  "D18 (ba715) 인계 큐 · 전 노드 형식 오류 5번(결정적) → 지우지 않고 늦은 채움(_trace_later · 방출 사실 · 디스크)으로 넘김(백오프·30일·실제 5회 만료 규칙)",
                  {"hq": d18.get("_hq"), "tl": tl18})
        PLAN.clear()
        PLAN["debug_traceTransaction"] = ("ok", [(RT, W0, 17)])
        FT.t += 4 * 3600
        for k in range(3):
            T.safe(w18._hq_step, HEAD, FT.t + 10)
            T.safe(w18._trace_later_step, HEAD)
            FT.t += 4 * 3600
        re18 = [r for r in w18.writer.recs if r.get("txhash") == H18 and (r.get("snapshot") or {}).get("internal")]
        d18b = disk()
        T.chk(re18 and H18 not in (d18b.get("_hq") or {}) and H18 not in (d18b.get("_trace_later") or {}),
              f"D18 ({kind18}) 노드 회복 뒤 internal 채워 재방출 · 큐에서 빠짐(조용한 유실 0)", {"reemit": len(re18)})

    HP18 = os.path.join(common.STATE_DIR, f"hq_left_{CH}.json")
    EP18 = os.path.join(common.STATE_DIR, f"enrich_{CH}.json")
    for tgt18 in ("etherscan", "blockscout"):
        for p9 in (HP18, EP18, os.path.join(common.STATE_DIR, f"trace_later_left_{CH}.json")):
            if os.path.exists(p9):
                os.remove(p9)
        w18c = mk(live_cur(SAFE))
        HO18 = hx(0x18f0)
        common.append_durable_jsonl(TOVF, {"h": HO18, "at": int(FT.t), "n": 0, "blk": 5, "sent": True})
        r18c = T.safe(evm_watch.rpc_handback, w18c, tgt18)
        got18 = common.read_json(HP18 if tgt18 == "etherscan" else EP18, {}) or {}
        left18 = common.read_json(os.path.join(common.STATE_DIR, f"trace_later_left_{CH}.json"), {}) or {}
        T.chk(not (isinstance(r18c, dict) and "_exc" in r18c) and HO18 in got18 and HO18 in left18,
              f"D18b {tgt18} 되돌림 = 늦은 채움 넘침 파일 tx 도 넘김(종전: 파일에만 남아 탐색기 경로에선 회수 안 됨)", {"r": r18c, "got": HO18 in got18, "left": HO18 in left18})

    def leaf19(prefetch, fail_blocks=False):
        L19 = SAFE - 5000
        own19 = {("0x" + f"{0x19000 + i:064x}"): L19 + 100 + i * 300 for i in range(12)}
        OWN19 = sorted((b, h) for h, b in own19.items())
        reqs = {"n": 0, "items": 0, "blocks": 0}

        def fb(url, calls, **k):
            reqs["n"] += 1
            reqs["items"] += len(calls)
            FT.t += max(1.0, len(calls) / 5.0)
            out = []
            for m, p in calls:
                if m == "eth_getTransactionCount":
                    out.append(hex(sum(1 for bb, _h in OWN19 if bb <= int(p[1], 16))))
                elif m == "eth_getBalance":
                    out.append("0x0")
                elif m == "eth_getBlockByNumber" and p[1]:
                    reqs["blocks"] += 1
                    b = int(p[0], 16)
                    if fail_blocks:
                        out.append(bf_engine.NetError("block fetch failed", "rpc"))
                    else:
                        out.append({"number": p[0], "transactions": [{"hash": h, "from": W0, "to": RT} for bb, h in OWN19 if bb == b]})
                else:
                    out.append(None)
            return out
        w = mk(live_cur(L19), txs={h: own_tx(h, b) for h, b in own19.items()})
        w.state_rpcs = w.cfg_rpcs = [URL]
        w.__dict__.pop("_batch", None)
        w._order = lambda urls: list(urls)
        w._scan_logs = lambda ws, c, target, dl: ({}, int(target), None)
        w._head_peek = lambda *a, **k: None
        w._trace_sick_until = FT.t + 10_000
        if not prefetch:
            w._leaf_prefetch = lambda *a, **k: ({}, {})
        real_b = bf_engine.rpc_batch
        bf_engine.rpc_batch = fb
        try:
            t0 = FT.t
            w._late_ctx = True
            r = T.safe(w._advance, [W0], L19, SAFE, HEAD, FT.t + 600)
            w._late_ctx = False
        finally:
            bf_engine.rpc_batch = real_b
        d = disk()
        return {"r": r, "sec": round(FT.t - t0), "reqs": dict(reqs), "emitted": sorted(x.get("txhash") for x in w.writer.recs),
                "ns": (d.get("_ns") or {}).get(W0), "nonces": (d.get("_nonces") or {}).get(W0), "tl": sorted(d.get("_trace_later") or {})}
    a19, b19 = leaf19(False), leaf19(True)
    T.chk(b19["r"] == SAFE and a19["r"] == SAFE and b19["emitted"] == a19["emitted"] and len(b19["emitted"]) == 12 and b19["ns"] == a19["ns"]
          and b19["nonces"] == a19["nonces"] and b19["tl"] == a19["tl"],
          "D19 잎 12개(로그 없는 내 발신) — 묶음 경로 결과 = 잎마다 경로(방출·기준점·nonce 지도·늦은 채움 큐 같음)",
          {"a": {k: a19[k] for k in ("r", "sec", "reqs")}, "b": {k: b19[k] for k in ("r", "sec", "reqs")}})
    T.chk(b19["reqs"]["n"] <= a19["reqs"]["n"] - 20 and b19["sec"] < a19["sec"],
          "D19 묶음 = 요청 수·걸음 시간 줄어듦(공개 노드 초당 1요청 게이트 — 종전 잎마다 블록·상세 요청 따로)", {"before": a19["reqs"], "after": b19["reqs"],
                                                                                    "sec": [a19["sec"], b19["sec"]]})
    c19 = leaf19(True, fail_blocks=True)
    T.chk(isinstance(c19["r"], dict) and "_exc" in c19["r"] and not c19["emitted"],
          "D19 묶음 블록 조회가 실패하면 잎마다 종전 경로(같은 실패 = 걸음 실패 · 커서 유지 — 조용히 넘어가지 않음)", c19["r"])

    KEYU = "https://rpc.ankr.com/base/TESTKEY"
    PUBU = URL
    seen20 = []
    mode20 = {"key": "ok"}

    def fb20(url, calls, **k):
        seen20.append(url)
        if url == KEYU and mode20["key"] == "local":
            e9 = bf_engine.NetError("quota: Ankr 오늘(UTC) 몫(80%) 다 씀 — 다른 노드로", "quota")
            e9.local = True
            raise e9
        return ["0x1" if m == "eth_getTransactionCount" else "0x0" for m, _p in calls]
    real_b20 = bf_engine.rpc_batch
    bf_engine.rpc_batch = fb20
    try:
        w20 = mk()
        w20.state_rpcs = [PUBU, KEYU]
        w20._order = lambda urls: list(urls)
        seen20.clear()
        w20._st_memo = {}
        T.safe(w20._states, [(W0, 100)])
        first_plain = seen20[:1]
        w20._key_ctx = True
        seen20.clear()
        w20._st_memo = {}
        r20 = T.safe(w20._states, [(W0, 101)])
        first_key = seen20[:1]
        mode20["key"] = "local"
        seen20.clear()
        w20._st_memo = {}
        r20b = T.safe(w20._states, [(W0, 102)])
        mode20["key"] = "ok"
        g20 = bf_engine.gate(KEYU)
        rest0 = g20.resting
        g20.resting = lambda: True
        try:
            seen20.clear()
            w20._st_memo = {}
            T.safe(w20._states, [(W0, 103)])
            first_rest = seen20[:1]
        finally:
            g20.resting = rest0
        w20._key_ctx = False
        w20b = mk()
        w20b.state_rpcs = [PUBU]
        w20b._order = lambda urls: list(urls)
        w20b._key_ctx = True
        seen20.clear()
        T.safe(w20b._states, [(W0, 104)])
        first_nokey = seen20[:1]
        T.chk(first_plain == [PUBU] and first_key == [KEYU] and isinstance(r20, dict) and r20.get((W0, 101)) == (1, 0),
              "D20 따라잡는 라이브 걸음(_key_ctx) = 상태 조회를 키 노드 먼저 · 그 밖 = 종전(공개 먼저 — 최신 조회가 키 몫을 안 먹음)", {"plain": first_plain, "key": first_key})
        T.chk(seen20 is not None and isinstance(r20b, dict) and r20b.get((W0, 102)) == (1, 0) and first_rest == [PUBU] and first_nokey == [PUBU],
              "D20 키 노드 하루 장부 80% 거절 = 같은 호출 안에서 공개 노드로(결과 그대로) · 키 노드 429 쉼 = 공개 먼저 · 키 없는 설치 = 종전", {"refused": r20b, "rest": first_rest, "nokey": first_nokey})
        def cyc20(c0):
            w = mk(live_cur(c0))
            w.state_rpcs = [PUBU, KEYU]
            w._order = lambda urls: list(urls)
            w._scan_logs = lambda ws, c, target, dl: ({}, int(target), None)
            w._head_peek = lambda *a, **k: None
            st0 = w._states
            log20 = []

            def st(pairs, strict=False):
                n0 = len(seen20)
                r = st0(pairs, strict)
                log20.append(seen20[n0] if len(seen20) > n0 else None)
                return r
            w._states = st
            seen20.clear()
            T.safe(w.cycle)
            return [x for x in log20 if x], w
        a20, _wa = cyc20(SAFE - 86_400)
        b20, _wb = cyc20(SAFE - 40)
        T.chk(a20 and a20[0] == KEYU and b20 and all(x == PUBU for x in b20) and not _wa.__dict__.get("_key_ctx"),
              "D20 실제 사이클: 최근 창 따라잡는 걸음 = 상태 키 노드 먼저 · 헤드 근처 평시 꼬리 = 공개 먼저 · 걸음 뒤 문맥 꺼짐", {"catchup": a20[:3], "tail": b20[:3]})
    finally:
        bf_engine.rpc_batch = real_b20
finally:
    evm_watch.time = real_time
    bf_engine.rpc_call, bf_engine.rpc_batch = real_rpc, real_batch

T.finish()
sys.exit(1 if T.FAILS else 0)
