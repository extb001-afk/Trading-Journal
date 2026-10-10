#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import time

CH = "zerog"
N = 5
W = ["0x" + f"{0xe0 + i:02x}" * 20 for i in range(N)]
POLL = 60
URL = "http://127.0.0.1:9/rpc"
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
HEAD = 60_000_000
SAFE = HEAD - 10
B0 = 40_000_000
E18 = 10 ** 18
HNEW = "0x" + "9f" * 32
XSRC = "0x" + "77" * 20
HoldError = getattr(evm_watch, "HoldError", RuntimeError)
OVR = getattr(R, "BK_NATIVE_OVERRUN_SEC", 120)


class FakeTime:
    def __init__(self):
        self.t = 1_800_000_000.0

    def time(self):
        return self.t

    def __getattr__(self, k):
        return getattr(time, k)


class Wr:
    def __init__(self):
        self.recs = []

    def append(self, rec):
        self.recs.append(rec)


class Rig:

    def __init__(self, ws, ys, span=8000, st_sec=0.5, tr=None, tr_fail=False, live_dep=False, extra=None):
        self.ft = FakeTime()
        evm_watch.time = self.ft
        self.ws, self.ys, self.span = list(ws), dict(ys), span
        self.st_sec, self.tr, self.tr_fail, self.live_dep = st_sec, (tr or {}), tr_fail, live_dep
        self.calls = {"states": 0, "trace": 0}
        self.durs = []
        lc = SAFE - 50 if live_dep else SAFE
        cur = {"_rpc_v": 1, "_start": 0, "_handover": {"from": "fresh", "at": 1}, "_bkspan": span, "_ns": {}, "_bkns": {}}
        for w in self.ws:
            cur[w] = lc
            cur["_ns"][w] = [lc, 0, str(E18 if self.ys.get(w, 10 ** 12) <= lc else 0), 0, "0"]
            cur["_bk:" + w] = {"from": B0, "to": B0 + span, "done": B0, "why": "new"}
            cur["_bkns"][w] = [B0, 0, "0", 0, "0"]
        cur.update(extra or {})
        common.atomic_write_json(CPATH, cur)
        common.atomic_write_json(EPATH, [])
        w = self.w = R(CFG, CH, list(self.ws), Wr())
        w.multicall = None
        w.trace_rpcs = ["http://127.0.0.1:9/trace"]
        w._head = lambda: HEAD
        w._init = lambda safe: None
        w._head_peek = lambda *a, **k: None
        w._health_cycle = lambda *a, **k: None
        w._scan_logs = self._scan
        w._details = self._details
        w._states = self._states
        w._scan_blocks = lambda lo, hi, ww, dl, **k: ({}, True)
        w._leaf_trace = self._leaf

        def tb(y):
            raise RuntimeError("Request timeout on the free tier")
        w._trace_block = tb

    def _scan(self, ws, c, target, dl):
        if self.live_dep and int(c) < SAFE - 10 <= int(target):
            return {HNEW: SAFE - 10}, int(target), None
        return {}, int(target), None

    def _details(self, hs, deadline=None, trace=True, **k):
        return {h: {"tx": {"hash": h, "block_number": SAFE - 10, "from": XSRC, "to": self.ws[0], "status": "ok", "value": "0"},
                    "token_transfers": [{"from": XSRC, "to": self.ws[0], "value": "5"}], "internal": []} for h in hs}

    def _states(self, pairs, strict=False):
        m = self.w.__dict__.setdefault("_st_memo", {})
        need = [p for p in dict.fromkeys(pairs) if p not in m]
        if need:
            self.calls["states"] += 1
            self.ft.t += self.st_sec
            for (a, b) in need:
                m[(a, b)] = (0, E18 if b >= self.ys.get(a, 10 ** 12) else 0)
        return {p: m[p] for p in pairs}

    def _leaf(self, ww, y, pool, got):
        self.calls["trace"] += 1
        self.ft.t += float(self.tr.get(ww, 0.0))
        return None, bool(self.tr_fail)

    def cycles(self, n):
        for i in range(n):
            t0 = self.ft.t
            T.safe(self.w.cycle)
            self.durs.append(self.ft.t - t0)
            if not self.w._bk_jobs():
                return i + 1
            self.ft.t = max(self.ft.t, t0 + POLL)
        return None

    def disk(self):
        return common.read_json(CPATH, {})


real_time = evm_watch.time
try:
    ys1 = {w: B0 + 100 + 350 * i for i, w in enumerate(W)}
    rg = Rig(W, ys1, span=8000, st_sec=0.5, tr={w: 40.0 for w in W})
    fin1 = rg.cycles(8)
    T.chk(fin1 is not None and fin1 <= 3, "B1 지갑 5개 · 잎 trace 느림 — 3사이클 안에 전 지갑 뒤 차선 완주(종전: 매 사이클 같은 지갑 '이분 탐색 예산 소진' — 영구 정지)",
          {"done_cycle": fin1, "jobs_left": len(rg.w._bk_jobs()), "durs": [round(x, 1) for x in rg.durs], "calls": rg.calls})
    bound1 = (POLL - 5) + 60 + 40 + 20
    T.chk(rg.durs and max(rg.durs) <= bound1, f"B1 사이클 길이 ≤ 주기 + 60초 + 진행 중 잎 1개(≈{bound1}초 — 지갑 수와 무관 · 종전 마감 +120초에 잎 trace 무제한)",
          [round(x, 1) for x in rg.durs])
    T.chk(int(rg.disk().get("_bkspan") or 0) == 8000 or not rg.disk().get("_bkspan"), "B1 진행 있는 예산 소진 = 걸음(_bkspan) 반감 없음",
          rg.disk().get("_bkspan"))
    notes1 = [r.get("kind") for r in (rg.disk().get("_native_notes") or [])]
    T.chk(fin1 is not None and notes1.count("unexplained") + notes1.count("leaf_deferred") >= N,
          "B1 잎마다 결론(잎 trace 결과 없음 = unexplained · 마감 넘긴 잎 = leaf_deferred → '나중에 다시') — 빠진 지갑 없음", notes1)

    ys2 = {W[0]: B0 + 700, W[1]: B0 + 1500}
    rg2 = Rig(W[:2], ys2, span=8000, st_sec=15.0, tr={})
    fin2 = rg2.cycles(10)
    T.chk(fin2 is not None and fin2 <= 6, "B2 상태 조회 느림(이분 탐색 1개 > 한 사이클) — 메모가 이어져 6사이클 안 완주(종전: 매번 처음부터 — 영구 정지)",
          {"done_cycle": fin2, "durs": [round(x, 1) for x in rg2.durs], "states": rg2.calls["states"]})
    T.chk(fin2 is not None and rg2.calls["states"] <= 2 * 14 + 4, "B2 상태 배치 = 지갑당 이분 탐색 한 번 몫(+ 선조회) — 같은 블록 다시 안 받음",
          rg2.calls)
    T.chk(int(rg2.disk().get("_bkspan") or 8000) == 8000, "B2 진행 있는 예산 소진 = 걸음 반감 없음", rg2.disk().get("_bkspan"))

    rg3 = Rig(W, ys1, span=8000, st_sec=0.5, tr={w: 40.0 for w in W}, live_dep=True)
    t03 = rg3.ft.t
    T.safe(rg3.w.cycle)
    d3 = rg3.disk()
    T.chk(HNEW in [r.get("txhash") for r in rg3.w.writer.recs], "B3 옛 구간이 '예산 소진'으로 못 끝나는 사이클에도 최신 입금 방출(그 사이클)",
          len(rg3.w.writer.recs))
    T.chk(all(int(d3.get(w) or 0) == SAFE for w in W), "B3 라이브 커서 = safe(최신 꼬리 먼저)", {w[:6]: d3.get(w) for w in W})
    T.chk(rg3.ft.t - t03 <= bound1, "B3 그 사이클 길이도 상한 안", round(rg3.ft.t - t03, 1))

    rg4 = Rig(W[:1], {W[0]: B0 + 700}, span=8000, st_sec=0.5, tr={W[0]: 5.0}, tr_fail=True)
    fin4 = rg4.cycles(4)
    d4 = rg4.disk()
    ll4 = d4.get("_leaf_later") or {}
    T.chk(fin4 == 1, "B4 뒤 차선 잎 trace 실패 = 그 사이클에 전진(종전: 10회·30분 보류 — 걸음마다 새로 시작)", {"done_cycle": fin4, "jobs": list(rg4.w._bk_jobs())})
    T.chk(any(int((v or {}).get("blk") or 0) == B0 + 700 for v in ll4.values()), "B4 그 잎 = '나중에 다시'(_leaf_later — 블록 trace 로 계속 재시도)",
          sorted(ll4))
    T.chk(int(d4.get("_bkspan") or 8000) >= 8000, "B4 걸음(_bkspan) 반감 없음(빠른 걸음이면 늘 수는 있음)", d4.get("_bkspan"))

    def live_case(err_fn, lv=5000):
        rg5 = Rig(W[:1], {}, span=8000, extra={W[0]: SAFE - 3000, "_lvspan": lv, "_ns": {W[0]: [SAFE - 3000, 0, "0", 0, "0"]}})
        for k9 in [k for k in rg5.w.cursor if k.startswith("_bk:")]:
            rg5.w.cursor.pop(k9)
        common.atomic_write_json(CPATH, rg5.w.cursor)

        def adv(ws, c, target, head, deadline, bk=False):
            err_fn(rg5.w, c)
        rg5.w._advance = adv
        T.safe(rg5.w.cycle)
        return int(rg5.disk().get("_lvspan") or 0)

    def hold(w, c):
        w._state_lag_hold("_ns", SAFE - 5, HEAD, SAFE, c)

    def r429(w, c):
        raise bf_engine.NetError("HTTP Error 429: Too Many Requests", "http429")

    def other(w, c):
        raise RuntimeError("잎 블록 123 스캔 미완 — 다음 사이클 재시도")
    v_hold, v_429, v_oth = live_case(hold), live_case(r429), live_case(other)
    T.chk(v_hold == 5000, "B5 라이브 꼬리 상태 뒤처짐 보류(HoldError) = 라이브 걸음(_lvspan) 그대로(종전: 모든 실패 반감)", v_hold)
    T.chk(v_429 == 5000, "B5 노드 한도(429) = 라이브 걸음 그대로(걸음이 작아지면 블록당 호출은 오히려 늚)", v_429)
    T.chk(v_oth == 2500, "B5 그 밖 실패 = 종전대로 반감", v_oth)

    def bk_case(exc):
        rg6 = Rig(W[:1], {}, span=8000)

        def adv(ws, c, target, head, deadline, bk=False):
            if bk:
                raise exc
            return c
        rg6.w._advance = adv
        T.safe(rg6.w.cycle)
        return int(rg6.disk().get("_bkspan") or 0)
    b429 = bk_case(bf_engine.NetError("HTTP Error 429", "http429"))
    bhold = bk_case(HoldError("잎 블록 1 trace·상세 일시 실패 1회 — 커서 유지(다음 사이클)"))
    both = bk_case(RuntimeError("nonce 틈 tx 상세 실패 — 다음 사이클 재시도"))
    T.chk(b429 == 8000 and bhold == 8000, "B5 뒤 차선 429·보류 = _bkspan 그대로", {"429": b429, "hold": bhold})
    T.chk(both == 4000, "B5 뒤 차선 그 밖 실패 = 종전대로 반감", both)

    GONE = bf_engine.classify_rpc_error({"code": -32000, "message": "required historical state unavailable (reexec stopped at block 123)"})
    T.chk(GONE.kind == "pruned", "B6 오류 분류: 'required historical state unavailable' = 상태 없음(pruned · 종전 'rpc' 일시 오류)", GONE.kind)
    tg = getattr(R, "_trace_gone", None)
    E401 = bf_engine.NetError("HTTP Error 401: Unauthorized", "http4xx", code=401)
    E403 = bf_engine.NetError("HTTP Error 403: Forbidden", "http4xx", code=403)
    ENULL = RuntimeError("trace 응답 형식 오류")
    E429 = bf_engine.NetError("HTTP Error 429: Too Many Requests", "http429")
    T.chk(tg is not None and tg(GONE) and tg(RuntimeError("rpc-error -32601: the method debug_traceBlockByNumber does not exist")),
          "B6 trace 불가 판정 = 과거 상태 없음 · 메서드 미지원", None if tg is None else [tg(GONE)])
    T.chk(tg is not None and not any(tg(e) for e in (E401, E403, ENULL, E429)), "B6 401·403·결과 없음·429 = 일시(영구로 치지 않음 — 늦은 채움 유지)",
          None if tg is None else [tg(e) for e in (E401, E403, ENULL, E429)])
    rg7 = Rig(W[:1], {})
    w7 = rg7.w
    y7 = 1234
    snapA = {"tx": {"hash": "0x" + "aa" * 32, "block_number": y7, "from": XSRC, "to": "0x" + "55" * 20, "status": "ok", "value": "0"},
             "token_transfers": [], "internal": []}
    lt = R._leaf_trace.__get__(w7)

    def trace_raise(e):
        def f(*a, **k):
            raise e
        return f
    w7._trace_internal = trace_raise(GONE)
    w7._trace_block = trace_raise(GONE)
    r_g = T.safe(lt, W[0], y7, [json.loads(json.dumps(snapA))], {})
    w7._trace_internal = trace_raise(E403)
    w7._trace_block = trace_raise(E403)
    r_t = T.safe(lt, W[0], y7, [json.loads(json.dumps(snapA))], {})
    T.chk(isinstance(r_g, tuple) and r_g[1] is False, "B6 잎 trace '과거 상태 없음' = 일시 실패 아님(호출측이 잔고 차이 귀속 — 보류·반감 없음)", r_g)
    T.chk(isinstance(r_t, tuple) and r_t[1] is True, "B6 잎 trace 403 = 일시 실패(종전대로 재시도·나중에 다시)", r_t)
    w7._batch = lambda calls: []
    w7._rpc_synth_detail = lambda h: {"tx": {"hash": h, "block_number": y7, "from": W[0], "to": "0x" + "55" * 20, "status": "ok", "value": "0",
                                              "raw_input": "0xa9059cbb" + "00" * 8}, "token_transfers": [], "internal": []}
    w7._rpc_call = lambda m, p: {"nonce": "0x1", "from": W[0], "to": "0x" + "55" * 20}
    w7._trace_want = lambda h, s: True
    w7._fill_symbols = lambda snaps: None
    dt = R._details.__get__(w7)
    w7._trace_internal = trace_raise(GONE)
    hG = "0x" + "c1" * 32
    o_g = T.safe(dt, [hG])
    w7._trace_internal = trace_raise(E403)
    hT = "0x" + "c2" * 32
    o_t = T.safe(dt, [hT])
    T.chk(isinstance(o_g, dict) and isinstance(o_g.get(hG), dict) and hG not in (w7.__dict__.get("_trace_late") or set()),
          "B6 상세 trace '과거 상태 없음' = internal 없이 확정 · 늦은 채움 표식 없음(종전: 3사이클 재시도 → 늦은 채움 30일)",
          {"o": str(o_g)[:120], "late": hG in (w7.__dict__.get("_trace_late") or set())})
    T.chk(isinstance(o_t, dict) and isinstance(o_t.get(hT), Exception), "B6 상세 trace 403 = 종전대로 재시도(라이브 · 1회차)", str(o_t)[:120])
    now7 = int(rg7.ft.t)
    w7.cursor["_leaf_later"] = {"g": {"w": W[0], "blk": 11, "at": now7 - 60, "n": 0, "next": 0}}
    w7._trace_block = trace_raise(GONE)
    T.safe(w7._leaf_later_step, HEAD)
    T.chk("g" not in (w7.cursor.get("_leaf_later") or {}), "B6 '나중에 다시' 잎 — 과거 상태 없음 = 뺌(기록 leaf_later_unsupported)", w7.cursor.get("_leaf_later"))
    w7.cursor["_leaf_later"] = {"t": {"w": W[0], "blk": 12, "at": now7 - 60, "n": 0, "next": 0}}
    w7._trace_block = trace_raise(E403)
    T.safe(w7._leaf_later_step, HEAD)
    T.chk("t" in (w7.cursor.get("_leaf_later") or {}), "B6 '나중에 다시' 잎 — 403 = 남김(백오프)", w7.cursor.get("_leaf_later"))
    hx = "0x" + "d1" * 32
    w7.cursor["_trace_later"] = {hx: {"at": now7 - 60, "n": 0, "next": 0, "blk": 5, "sent": True}}
    w7._trace_internal = trace_raise(GONE)
    T.safe(w7._trace_later_step, HEAD)
    T.chk(hx not in (w7.cursor.get("_trace_later") or {}), "B6 늦은 채움 — 과거 상태 없음 = 뺌(기록)", w7.cursor.get("_trace_later"))

    rg8 = Rig(W[:1], {})
    w8 = rg8.w
    w8.bpd = 340_000
    ov_def = w8._es_late_overlap({"etherscan_chainid": 42161})
    ov_cfg = w8._es_late_overlap({"etherscan_chainid": 42161, "trace_rpcs": ["https://archive-trace.example/rpc"]})
    T.chk(ov_def <= 340_000 * 3600 // 86400 + 1, "B7 아카이브 trace 노드(설정 trace_rpcs) 없음 = 이더스캔 인계 겹침 ≈1시간(종전 6시간 = 85,000블록)", ov_def)
    T.chk(ov_cfg == 85_000, "B7 설정 trace_rpcs 있음 = 종전 6시간 그대로", ov_cfg)
    T.chk(w8._es_late_overlap({}) == 0, "B7 이더스캔 체인 아님 = 0(종전)", w8._es_late_overlap({}))

    seen8 = []

    class FakeScanner:
        def __init__(self, eps, topic, pads, **kw):
            seen8.append(dict(kw.get("caps") or {}))
            self.caps = dict(kw.get("caps") or {})
            self.metrics, self.last_stop, self.retention_floor = {}, None, None

        def scan(self, a, b, deadline=None, **k):
            return {}, b
    rg9 = Rig(W[:1], {})
    w9 = rg9.w
    real_ls = bf_engine.LogScanner
    bf_engine.LogScanner = FakeScanner
    try:
        sl = R._scan_logs.__get__(w9)
        w9._log_caps[URL] = 50
        T.safe(sl, W[:1], 100, 200, rg9.ft.t + 30)
        rg9.ft.t += 1801
        T.safe(sl, W[:1], 200, 300, rg9.ft.t + 30)
    finally:
        bf_engine.LogScanner = real_ls
    T.chk(len(seen8) == 2 and seen8[0].get(URL) == 50, "B8 줄여 배운 상한은 그 사이엔 이어 씀", seen8)
    T.chk(len(seen8) == 2 and seen8[1].get(URL) == 5000, "B8 30분 지나면 정적 표 값(설정 상한 5000)으로 복구(종전: 재시작 전까지 50)", seen8)

    rg10 = Rig(W[:1], {})
    w10 = rg10.w
    now10 = int(rg10.ft.t)
    w10.cursor["_leaf_later"] = {"old": {"w": W[0], "blk": 21, "at": now10 - 31 * 86400, "n": 7, "next": now10 + 999_999},
                                 "new": {"w": W[0], "blk": 22, "at": now10 - 2 * 86400, "n": 3, "next": now10 + 999_999}}
    T.safe(w10._leaf_later_step, HEAD)
    ll10 = w10.cursor.get("_leaf_later") or {}
    T.chk("old" not in ll10 and "new" in ll10, "B9 30일 넘은 잎 = 뺌 · 그 안 = 그대로(종전: 만료 없음)", sorted(ll10))
    T.chk(any(r.get("kind") == "leaf_later_giveup" and int(r.get("blk") or 0) == 21 for r in (w10.cursor.get("_native_notes") or [])),
          "B9 뺀 잎 = 기록(leaf_later_giveup)", [r.get("kind") for r in (w10.cursor.get("_native_notes") or [])])
    T.chk(int((common.read_json(CPATH, {}).get("_leaf_later") or {}).get("old", {}).get("n") or -1) == -1, "B9 디스크에도 반영", None)

    rg11 = Rig(W[:1], {})
    w11 = rg11.w
    trim = getattr(w11, "_st_memo_trim", None)
    w11._st_safe = 1000
    w11._st_memo = {(W[0], 900): (1, 2), (W[0], 1000): (1, 3), (W[0], 1001): (1, 4)}
    T.safe(trim) if trim else None
    T.chk(trim is not None and set(w11._st_memo) == {(W[0], 900), (W[0], 1000)}, "B10 사이클 시작 = 지난 safe 이하 상태만 유지(헤드 근처 값 버림 · 종전: 전부 비움)",
          sorted(str(k[1]) for k in w11._st_memo))
    w12 = R(CFG, CH, list(W[:1]), Wr())
    w12.state_rpcs = [URL]
    w12._st_memo = {(W[0], 10 + i): (0, i) for i in range(R.__dict__.get("ST_MEMO_MAX", 20000))}
    real_rb = bf_engine.rpc_batch
    bf_engine.rpc_batch = lambda url, calls, **k: ["0x1" for _ in calls]
    try:
        T.safe(R._states.__get__(w12), [(W[0], 999_999)])
    finally:
        bf_engine.rpc_batch = real_rb
    T.chk((W[0], 999_999) in w12._st_memo and (W[0], 10 + 19_999) in w12._st_memo and (W[0], 10) not in w12._st_memo
          and len(w12._st_memo) >= 10_000, "B10 상한 넘음 = 오래 넣은 것부터 덜어 냄(최근 것·새 값 유지 · 종전: 통째 비움)", len(w12._st_memo))

    GEN = 1_700_000_000
    S0 = 50_000_000
    common.atomic_write_json(os.path.join(common.STATE_DIR, "backfill_request.json"), {"since": "2026-01-01"})
    cur11 = {"_rpc_v": 1, "_start": S0, "_ns": {}}
    for w in W[:2]:
        cur11[w] = SAFE
        cur11["_ns"][w] = [SAFE, 0, "0", 0, "0"]
    common.atomic_write_json(CPATH, cur11)
    ft11 = FakeTime()
    evm_watch.time = ft11
    w13 = R(CFG, CH, list(W[:2]), Wr())
    w13._block_ts = lambda b: int(GEN + int(b) * 2)
    w13._states = lambda pairs, strict=False: {p: (0, 0) for p in pairs}
    s9 = bf_engine.SINCE.target(CH)
    T.chk(bool(s9) and w13._window_start(SAFE) < S0, "B11 준비: 확장 목표가 지금 창 시작보다 이름", {"s9": s9, "ws": w13._window_start(SAFE)})
    T.safe(w13._since_reinit, SAFE)
    d13 = common.read_json(CPATH, {})
    T.chk(all(int(d13.get(w) or 0) == SAFE for w in W[:2]) and not isinstance(d13.get("_since_ext"), dict),
          "B11 단일 차선 설치의 과거 창 확장 = 최신 커서를 되감지 않음(종전: 전 지갑 커서를 새 시작으로 — 옛 구간 다 훑을 때까지 최신 멈춤)",
          {"curs": [d13.get(w) for w in W[:2]], "since_ext": d13.get("_since_ext")})
    T.chk(all(isinstance(d13.get("_bk:" + w), dict) and d13["_bk:" + w].get("why") == "extend" and int(d13["_bk:" + w]["to"]) == S0 for w in W[:2])
          and isinstance(d13.get("_handover"), dict) and d13["_handover"].get("from") == "extend" and w13.bk_mode,
          "B11 앞 구간 = 뒤 차선 작업(why=extend · 끝 = 옛 창 시작) · 차선 모드 전환(_handover from=extend)",
          {k: v for k, v in d13.items() if k.startswith("_bk") or k == "_handover"})
    os.remove(os.path.join(common.STATE_DIR, "backfill_request.json"))

    rg14 = Rig(W[:1], {}, span=8000)
    w14 = rg14.w
    w14.cursor["_bk:" + W[0]] = {"from": B0, "to": B0 + 10_000_000, "done": B0, "why": "new"}
    common.atomic_write_json(CPATH, w14.cursor)
    mode = {"fail": True}

    def adv14(ws, c, target, head, deadline, bk=False):
        if not bk:
            return c
        if mode["fail"]:
            raise RuntimeError("잎 블록 1 스캔 미완 — 다음 사이클 재시도")
        job = w14.cursor["_bk:" + ws[0]]
        job["done"] = int(target)
        rg14.ft.t += 1.0
        return int(target)
    w14._advance = adv14
    T.safe(w14.cycle)
    sp1 = int(common.read_json(CPATH, {}).get("_bkspan") or 0)
    mode["fail"] = False
    rg14.ft.t += POLL
    T.safe(w14.cycle)
    sp2 = int(common.read_json(CPATH, {}).get("_bkspan") or 0)
    rg14.ft.t += 700
    T.safe(w14.cycle)
    sp3 = int(common.read_json(CPATH, {}).get("_bkspan") or 0)
    T.chk(sp1 == 4000 and sp2 == 4000, "B12 줄인 뒤 10분 안 빠른 걸음 = 그대로(종전: 바로 두 배 → 다음 바쁜 구간에서 또 소진)", {"cut": sp1, "next": sp2})
    T.chk(sp3 > 4000, "B12 유예(10분) 지나면 다시 늘림", sp3)

    rg15 = Rig(W[:1], {}, span=8000)
    w15 = rg15.w
    H1, H2 = "0x" + "e1" * 32, "0x" + "e2" * 32
    w15._scan_logs = lambda ws, c, target, dl: (({H1: B0 + 10, H2: B0 + 20} if int(c) < B0 + 10 <= int(target) else {}), int(target), None)
    st15 = {"n": 0}

    def det15(hs, deadline=None, trace=True, **k):
        st15["n"] += 1
        out = {}
        for h in hs:
            if st15["n"] == 1 and h == H2:
                out[h] = RuntimeError("상세 예산 소진 — 다음 사이클")
                continue
            out[h] = {"tx": {"hash": h, "block_number": B0 + 10, "from": XSRC, "to": W[0], "status": "ok", "value": "0"},
                      "token_transfers": [{"from": XSRC, "to": W[0], "value": "5"}], "internal": []}
        return out
    w15._details = det15
    T.safe(w15.cycle)
    sp15 = int(common.read_json(CPATH, {}).get("_bkspan") or 0)
    T.chk(sp15 == 8000, "B13 상세 일부를 새로 받은 무전진(나머지 예산 소진 — 받은 상세는 메모로 이어 씀) = 걸음 유지(종전: 반감)", sp15)
    rg15.ft.t += POLL
    T.safe(w15.cycle)
    T.chk(not w15._bk_jobs() and {H1, H2} <= {r.get("txhash") for r in w15.writer.recs}, "B13 다음 사이클 = 남은 상세만 받아 완주 · 두 tx 방출",
          {"jobs": list(w15._bk_jobs()), "recs": len(w15.writer.recs), "det_calls": st15["n"]})

    rg16 = Rig(W[:1], {})
    w16 = rg16.w
    w16._late_ctx = True
    r16 = T.safe(w16._leaf_retry, W[0], 777, False, c=700, nk="_ns")
    T.chk(isinstance(r16, dict) and "HoldError" in str(r16.get("_exc")), "B14 차선 모드 라이브 따라잡기 = 종전 체인 단위 보류(120초) 유지 · 보류는 HoldError(걸음 안 줄임)", r16)
    r16b = T.safe(w16._leaf_retry, W[0], 778, False, c=900, nk="_bkns")
    T.chk(r16b is False and any(int((v or {}).get("blk") or 0) == 778 for v in (w16.cursor.get("_leaf_later") or {}).values()),
          "B14 뒤 차선 = 첫 실패에 바로 '나중에 다시'(종전: 10회·30분 보류 예외)", r16b)
    cur17 = {"_rpc_v": 1, "_start": 0, W[0]: SAFE - 9000, "_ns": {W[0]: [SAFE - 9000, 0, "0", 0, "0"]}}
    common.atomic_write_json(CPATH, cur17)
    w17 = R(CFG, CH, list(W[:1]), Wr())
    w17._late_ctx = True
    r17 = T.safe(w17._leaf_retry, W[0], 779, False, c=SAFE - 9000, nk="_ns")
    T.chk(r17 is False and any(int((v or {}).get("blk") or 0) == 779 for v in (w17.cursor.get("_leaf_later") or {}).values()),
          "B14 단일 차선 따라잡는 걸음 = 첫 실패에 바로 '나중에 다시'(종전: 걸음마다 30분 — 최신 꼬리까지 멈춤)", r17)
    w17._late_ctx = False
    r17b = T.safe(w17._leaf_retry, W[0], 780, False, c=SAFE - 100, nk="_ns")
    T.chk(isinstance(r17b, dict) and "HoldError" in str(r17b.get("_exc")), "B14 단일 차선 헤드 꼬리 걸음 = 종전대로 보류(재시도) · HoldError", r17b)

    rg18 = Rig(W[:1], {})
    w18 = rg18.w
    now18 = int(rg18.ft.t)
    w18.cursor["_leaf_later"] = {f"k{i}": {"w": W[0], "blk": 30 + i, "at": now18 - 60, "n": 0, "next": 0} for i in range(3)}

    def tb18(y):
        rg18.ft.t += 40.0
        raise RuntimeError("Request timeout on the free tier")
    w18._trace_block = tb18
    t18 = rg18.ft.t
    T.safe(w18._leaf_later_step, HEAD)
    tried18 = sum(1 for v in (w18.cursor.get("_leaf_later") or {}).values() if int(v.get("n") or 0) >= 1)
    T.chk(tried18 == 1 and rg18.ft.t - t18 <= 45, "B15 '나중에 다시' 재시도 = 1건 뒤 30초 넘으면 다음 사이클로(라이브 차선 앞을 오래 붙잡지 않음 · 종전: 3건 연속)",
          {"tried": tried18, "sec": rg18.ft.t - t18})

    TA, TB = "http://127.0.0.1:9/trA", "http://127.0.0.1:9/trB"
    ERR_G = {"code": -32000, "message": "required historical state unavailable (reexec stopped at block 9)"}
    plan = {}

    def fake_rpc(url, method, params, **k):
        e = plan.get((url, method))
        if e == "gone":
            raise bf_engine.classify_rpc_error(ERR_G)
        if e == "429":
            raise bf_engine.NetError("HTTP Error 429: Too Many Requests", "http429")
        if e == "timeout":
            raise bf_engine.NetError("timed out", "timeout")
        if e == "null":
            return None
        raise bf_engine.NetError("예상 못 한 호출", "rpc")

    def setplan(a_kind, b_kind):
        plan.clear()
        for m in ("debug_traceTransaction", "trace_transaction", "debug_traceBlockByNumber"):
            plan[(TA, m)] = a_kind
            plan[(TB, m)] = b_kind
    rg19 = Rig(W[:1], {})
    w19 = rg19.w
    w19.trace_rpcs = [TA, TB]
    for k9 in ("_trace_internal", "_trace_block", "_leaf_trace", "_details"):
        w19.__dict__.pop(k9, None)
    w19._rpc_call = lambda m, p: {"transactions": []}
    real_rpc = bf_engine.rpc_call
    bf_engine.rpc_call = fake_rpc
    try:
        now19 = int(rg19.ft.t)

        def tl_left(a_kind, b_kind):
            setplan(a_kind, b_kind)
            hx9 = "0x" + "f1" * 32
            w19.cursor["_trace_later"] = {hx9: {"at": now19 - 60, "n": 0, "next": 0, "blk": 5, "sent": True}}
            T.safe(w19._trace_later_step, HEAD)
            return hx9 in (w19.cursor.get("_trace_later") or {})

        def ll_left(a_kind, b_kind):
            setplan(a_kind, b_kind)
            w19.cursor["_leaf_later"] = {"q": {"w": W[0], "blk": 40, "at": now19 - 60, "n": 0, "next": 0}}
            T.safe(w19._leaf_later_step, HEAD)
            return "q" in (w19.cursor.get("_leaf_later") or {})

        def hq_left(a_kind, b_kind):
            setplan(a_kind, b_kind)
            hq9 = "0x" + "f3" * 32
            w19.cursor["_hq"] = {hq9: 0}
            w19._details = lambda hs, deadline=None, trace=True, **k: {h: {"tx": {"hash": h, "block_number": 7, "from": XSRC, "to": W[0], "status": "ok", "value": "0"},
                                                                           "token_transfers": [], "internal": []} for h in hs}
            T.safe(w19._hq_step, HEAD, rg19.ft.t + 300)
            w19.__dict__.pop("_details", None)
            return hq9 in (w19.cursor.get("_hq") or {})
        mixed = [("429", "gone"), ("timeout", "gone"), ("gone", "429"), ("null", "gone")]
        T.chk(all(tl_left(a9, b9) for a9, b9 in mixed), "B16 tx 경로(늦은 채움 _trace_later): 노드 A 일시(429·시간 초과·결과 없음) + B '과거 상태 없음' = 일시 → 큐 유지(수정 전: 마지막 B 오류만 보고 삭제)",
              [tl_left(a9, b9) for a9, b9 in mixed])
        T.chk(all(ll_left(a9, b9) for a9, b9 in mixed), "B16 잎 경로(_leaf_later — 블록 trace): A 일시 + B 과거 상태 없음 = 큐 유지", [ll_left(a9, b9) for a9, b9 in mixed])
        T.chk(all(hq_left(a9, b9) for a9, b9 in mixed), "B16 인계 큐(_hq): A 일시 + B 과거 상태 없음 = 큐 유지", [hq_left(a9, b9) for a9, b9 in mixed])
        T.chk(not tl_left("gone", "gone") and not ll_left("gone", "gone") and not hq_left("gone", "gone"),
              "B16 모든 노드가 '과거 상태 없음'(parity 포함) = 영구 → 큐에서 뺌(기록)", [tl_left("gone", "gone"), ll_left("gone", "gone"), hq_left("gone", "gone")])
        w19._batch = lambda calls: []
        w19._rpc_synth_detail = lambda h: {"tx": {"hash": h, "block_number": 7, "from": W[0], "to": "0x" + "55" * 20, "status": "ok", "value": "0",
                                                   "raw_input": "0x12345678" + "00" * 8}, "token_transfers": [], "internal": []}
        w19._trace_want = lambda h, s: True
        w19._fill_symbols = lambda snaps: None
        setplan("429", "gone")
        hd1 = "0x" + "f4" * 32
        od1 = T.safe(w19._details, [hd1])
        setplan("gone", "gone")
        hd2 = "0x" + "f5" * 32
        od2 = T.safe(w19._details, [hd2])
        T.chk(isinstance(od1, dict) and isinstance(od1.get(hd1), Exception), "B16 상세: A 429 + B 과거 상태 없음 = 일시(재시도 — 수정 전: 늦은 채움 없이 internal 없이 확정)", str(od1)[:140])
        T.chk(isinstance(od2, dict) and isinstance(od2.get(hd2), dict), "B16 상세: 모든 노드 과거 상태 없음 = internal 없이 확정", str(od2)[:140])
        snapL = {"tx": {"hash": "0x" + "f6" * 32, "block_number": 41, "from": XSRC, "to": "0x" + "55" * 20, "status": "ok", "value": "0"}, "token_transfers": [], "internal": []}
        setplan("timeout", "gone")
        rL = T.safe(w19._leaf_trace, W[0], 41, [json.loads(json.dumps(snapL))], {})
        T.chk(isinstance(rL, tuple) and rL[1] is True, "B16 잎 trace: A 시간 초과 + B 과거 상태 없음 = 일시 실패(잔고 귀속 안 함 · 나중에 다시)", rL)
        setplan("gone", "gone")
        w19._order = lambda urls: [u for u in urls if u != TA] or list(urls)
        cut9 = ll_left("gone", "gone")
        w19.__dict__.pop("_order", None)
        T.chk(cut9, "B16 서킷으로 건너뛴 trace 노드가 있으면 '미확인'(일시) — 물어본 노드가 전부 과거 상태 없음이어도 큐 유지", cut9)
    finally:
        bf_engine.rpc_call = real_rpc

    rg20 = Rig(W[:1], {}, live_dep=True)
    w20 = rg20.w
    for k9 in [k for k in w20.cursor if k.startswith("_bk:")]:
        w20.cursor.pop(k9)
    w20.cursor["_hq"] = {"0x" + f"{0xa0 + i:02x}" * 32: 0 for i in range(20)}
    common.atomic_write_json(CPATH, w20.cursor)
    n20 = {"trace": 0}

    def slow_trace(h, snap):
        n20["trace"] += 1
        rg20.ft.t += 60.0
        raise bf_engine.NetError("HTTP Error 408: Request Timeout", "http4xx", code=408)
    w20._trace_internal = slow_trace
    t20 = rg20.ft.t
    T.safe(w20.cycle)
    dur20 = rg20.ft.t - t20
    T.chk(dur20 <= (POLL - 5) + 60 + 5 and n20["trace"] <= 2, "B17 인계 큐 trace 가 느려도 사이클 = 마감 + 진행 중 1건 안에 반환(종전: 20건 × 60초 — 다음 최신 확인 20분 밀림)",
          {"sec": dur20, "traced": n20["trace"]})
    T.chk(HNEW in [r.get("txhash") for r in w20.writer.recs] and len(w20.cursor.get("_hq") or {}) == 20,
          "B17 그 사이클 최신 입금 방출 · 못 한 인계 큐 항목은 그대로 남음(다음 사이클)", {"hq": len(w20.cursor.get("_hq") or {})})
    rg21 = Rig(W[:1], {})
    w21 = rg21.w
    now21 = int(rg21.ft.t)
    w21.cursor["_trace_later"] = {"0x" + f"{0xb0 + i:02x}" * 32: {"at": now21 - 60, "n": 0, "next": 0, "blk": 9, "sent": True} for i in range(3)}
    n21 = {"trace": 0}

    def slow_trace21(h, snap):
        n21["trace"] += 1
        rg21.ft.t += 60.0
        raise bf_engine.NetError("HTTP Error 408: Request Timeout", "http4xx", code=408)
    w21._trace_internal = slow_trace21
    t21 = rg21.ft.t
    T.safe(w21._trace_later_step, HEAD)
    T.chk(n21["trace"] == 1 and rg21.ft.t - t21 <= 65, "B17 늦은 채움 trace = 1건 뒤 시간 상한(30초) 넘으면 다음 사이클로(종전: 시간 검사 없이 3건)",
          {"traced": n21["trace"], "sec": rg21.ft.t - t21})

    def hq_rig(slow_first=0.0, det_sec=0.0, n=5):
        rg = Rig(W[:1], {})
        w = rg.w
        for k9 in [k for k in w.cursor if k.startswith("_bk:")]:
            w.cursor.pop(k9)
        hs = ["0x" + f"{0xc0 + i:02x}" * 32 for i in range(n)]
        w.cursor["_hq"] = {h: 0 for h in hs}
        common.atomic_write_json(CPATH, w.cursor)
        st = {"trace": [], "det": 0}

        def det(hl, deadline=None, trace=True, **k):
            st["det"] += 1
            rg.ft.t += det_sec
            return {h: {"tx": {"hash": h, "block_number": 9, "from": XSRC, "to": W[0], "status": "ok", "value": "0"}, "token_transfers": [], "internal": []}
                    for h in hl}

        def tr(h, snap):
            st["trace"].append(h)
            if h == hs[0] and slow_first:
                rg.ft.t += slow_first
                raise bf_engine.NetError("HTTP Error 408: Request Timeout", "http4xx", code=408)
            rg.ft.t += 1.0
            snap["internal"] = [{"from": XSRC, "to": W[0], "value": "7", "success": True}]
            snap["internal_note"] = "trace"
        w._details = det
        w._trace_internal = tr
        return rg, w, hs, st

    rgA, wA, hsA, stA = hq_rig(slow_first=60.0)
    for _ in range(4):
        T.safe(wA._hq_step, HEAD, rgA.ft.t + 40.0)
        rgA.ft.t += POLL
    leftA = sorted(wA.cursor.get("_hq") or {})
    T.chk(leftA == [hsA[0]] and {r.get("txhash") for r in wA.writer.recs} >= set(hsA[1:]),
          "B18 맨 앞 항목이 매번 60초 뒤 408 이어도 몇 사이클 안에 뒤 항목 전부 처리(재개 위치 — 종전 bb612 판: 같은 앞 항목만 되풀이 · 뒤 항목 영구 정체)",
          {"left": len(leftA), "emitted": len(wA.writer.recs), "traced": len(stA["trace"])})
    rgB, wB, hsB, stB = hq_rig(det_sec=12.0)
    prog = []
    for _ in range(6):
        b0 = len(wB.cursor.get("_hq") or {})
        T.safe(wB._hq_step, HEAD, rgB.ft.t + 10.0)
        prog.append(b0 - len(wB.cursor.get("_hq") or {}))
        rgB.ft.t += POLL
    T.chk(all(x >= 1 for x in prog[:5]) and not (wB.cursor.get("_hq") or {}),
          "B18 상세 조회가 예산(10초)을 넘겨도 매 사이클 trace ≥1건 진전 → 큐가 빔(종전 bb612 판: 상세 뒤 마감 검사로 trace 0건 · 매번 같은 상세 반복)",
          {"progress": prog, "left": len(wB.cursor.get("_hq") or {}), "det_calls": stB["det"]})

    rg22 = Rig(W[:1], {})
    w22 = rg22.w
    w22.trace_rpcs = ["http://127.0.0.1:9/trA", "http://127.0.0.1:9/trB"]
    for k9 in ("_details", "_trace_internal"):
        w22.__dict__.pop(k9, None)
    w22._batch = lambda calls: []
    w22._rpc_synth_detail = lambda h: {"tx": {"hash": h, "block_number": 7, "from": W[0], "to": "0x" + "55" * 20, "status": "ok", "value": "0",
                                               "raw_input": "0x12345678" + "00" * 32}, "token_transfers": [], "internal": []}
    w22._rpc_call = lambda m, p: {"nonce": "0x1", "from": W[0], "to": "0x" + "55" * 20}
    w22._fill_symbols = lambda snaps: None
    n22 = {"trace": 0}

    def slow408(url, method, params, **k):
        n22["trace"] += 1
        rg22.ft.t += 5.0
        raise bf_engine.NetError("HTTP Error 408: Request Timeout", "http4xx", code=408)
    hs22 = ["0x" + f"{0xd0 + i:02x}" * 32 for i in range(20)]
    real_rpc22 = bf_engine.rpc_call
    bf_engine.rpc_call = slow408
    try:
        t22 = rg22.ft.t
        o22 = T.safe(w22._details, list(hs22), late=True)
        dt22, tr22 = rg22.ft.t - t22, n22["trace"]
        late22 = set(w22.__dict__.get("_trace_late") or ())
        T.chk(isinstance(o22, dict) and all(isinstance(o22.get(h), dict) for h in hs22) and set(hs22) <= late22,
              "B19 늦은 채움 문맥: 20건 전부 internal 없이 확정 · 전부 '나중에 다시'(늦은 채움) 표식", {"late": len(set(hs22) & late22)})
        T.chk(dt22 <= 25 and tr22 <= 4, "B19 첫 tx trace 가 408 로 막히면 남은 tx 는 trace 를 걸지 않음 — 상세 1회 ≈ 1건 몫(종전: tx 마다 노드 2 × callTracer·parity = 20건 × 20초 → 라이브 걸음 7분 고정)",
              {"sec": dt22, "trace_calls": tr22})
        n22["trace"] = 0
        w22.__dict__.pop("_trace_late", None)
        w22._trace_fail = {}
        w22._trace_nf, w22._trace_sick_until = 0, 0.0
        o22b = T.safe(w22._details, list(hs22[:3]), late=False)
        T.chk(isinstance(o22b, dict) and all(isinstance(o22b.get(h), Exception) for h in hs22[:2]) and n22["trace"] == 8,
              "B19 헤드 꼬리 걸음(늦은 채움 문맥 아님) = 앞 tx 들은 종전대로 trace 재시도(TRACE_RETRY · 노드 2 × callTracer·parity)", {"trace_calls": n22["trace"]})
        T.chk(isinstance(o22b, dict) and isinstance(o22b.get(hs22[2]), dict) and hs22[2] in (w22.__dict__.get("_trace_late") or {}),
              "B19 헤드 꼬리 걸음도 한 상세 호출 안 연속 2번 실패 뒤 남은 tx 는 trace 를 걸지 않고 늦은 채움 표식(baser1011 — 문서2 1-2 ①)",
              {"t3": type(o22b.get(hs22[2])).__name__ if isinstance(o22b, dict) else o22b})
    finally:
        bf_engine.rpc_call = real_rpc22

    def catchup(n_own, live0, cycles):
        rg = Rig(W[:1], {}, extra={W[0]: live0, "_ns": {W[0]: [live0, 0, "0", 0, "0"]}})
        w = rg.w
        for k9 in [k for k in w.cursor if k.startswith("_bk:")]:
            w.cursor.pop(k9)
        common.atomic_write_json(CPATH, w.cursor)
        w.trace_rpcs = ["http://127.0.0.1:9/trA", "http://127.0.0.1:9/trB"]
        span = SAFE - live0
        txs = {}
        for i in range(n_own):
            h = "0x" + f"{0x1000 + i:064x}"
            txs[h] = {"tx": {"hash": h, "block_number": live0 + 1 + (span * i) // max(1, n_own), "from": W[0], "to": "0x" + "55" * 20, "status": "ok",
                             "value": "0", "raw_input": "0x12345678" + "00" * 32, "fee": {"value": "0"}}, "token_transfers": [], "internal": []}
        blk = sorted((v["tx"]["block_number"], h) for h, v in txs.items())
        for k9 in ("_details", "_trace_internal"):
            w.__dict__.pop(k9, None)
        w._scan_logs = lambda ws, c, target, dl: ({h: b9 for b9, h in blk if int(c) < b9 <= int(target)}, int(target), None)
        w._batch = lambda cl: []
        w._rpc_synth_detail = lambda h: json.loads(json.dumps(txs[h]))
        w._rpc_call = lambda m, p: {"nonce": "0x0", "from": W[0], "to": "0x" + "55" * 20}
        w._fill_symbols = lambda snaps: None

        def st(pairs, strict=False):
            m = w.__dict__.setdefault("_st_memo", {})
            for (a9, b9) in pairs:
                m.setdefault((a9, b9), (sum(1 for bb, _h in blk if bb <= b9), 0))
            return {p: m[p] for p in pairs}
        w._states = st

        def slow(url, method, params, **k):
            rg.ft.t += 5.0
            raise bf_engine.NetError("HTTP Error 408: Request Timeout", "http4xx", code=408)
        real9 = bf_engine.rpc_call
        bf_engine.rpc_call = slow
        try:
            t0 = rg.ft.t
            for i in range(cycles):
                tc = rg.ft.t
                T.safe(w.cycle)
                if int(common.read_json(CPATH, {}).get(W[0]) or 0) >= SAFE:
                    return i + 1, rg.ft.t - t0, len(w.writer.recs)
                rg.ft.t = max(rg.ft.t, tc + POLL)
            return None, rg.ft.t - t0, len(w.writer.recs)
        finally:
            bf_engine.rpc_call = real9
    c20, s20, e20 = catchup(300, SAFE - 86_400, 4)
    T.chk(c20 == 1 and s20 <= 300 and e20 == 300, "B20 최근 창 86,400블록 · 내 컨트랙트 호출 300건 · trace 노드 408 — 첫 사이클(≤300초)에 헤드 도달 · 300건 방출(종전 14차 판도 같은 입력이면 5,000블록/≈400초 고정 — 몇 시간)",
          {"cycle": c20, "sec": s20, "emitted": e20})
    c20b, s20b, e20b = catchup(1, SAFE - 100, 1)
    T.chk(c20b is None and e20b == 0, "B20 평시 꼬리(헤드 근처 100블록 걸음) = 종전대로 trace 재시도(그 사이클 커서 유지 · 늦은 채움 아님)", {"cycle": c20b, "emitted": e20b})

    rg23 = Rig(W[:1], {}, extra={W[0]: SAFE - 5000, "_ns": {W[0]: [SAFE - 5000, 0, "0", 0, "0"]}})
    w23 = rg23.w
    for k9 in [k for k in w23.cursor if k.startswith("_bk:")]:
        w23.cursor.pop(k9)
    common.atomic_write_json(CPATH, w23.cursor)
    w23.trace_rpcs = ["http://127.0.0.1:9/trA", "http://127.0.0.1:9/trB"]
    tx23 = {}
    for i in range(10):
        h = "0x" + f"{0x2000 + i:064x}"
        tx23[h] = {"tx": {"hash": h, "block_number": SAFE - 4000 + i * 100, "from": W[0], "to": "0x" + "55" * 20, "status": "ok", "value": "0",
                          "raw_input": "0x12345678" + "00" * 32, "fee": {"value": "0"}}, "token_transfers": [], "internal": []}
    for k9 in ("_details", "_trace_internal"):
        w23.__dict__.pop(k9, None)
    w23._batch = lambda cl: []
    w23._rpc_synth_detail = lambda h: json.loads(json.dumps(tx23[h]))
    w23._rpc_call = lambda m, p: {"nonce": "0x0", "from": W[0], "to": "0x" + "55" * 20}
    w23._fill_symbols = lambda snaps: None
    blk23 = sorted((v["tx"]["block_number"], h) for h, v in tx23.items())
    w23._scan_logs = lambda ws, c, target, dl: ({h: b9 for b9, h in blk23 if int(c) < b9 <= int(target)}, int(target), None)
    w23._states = lambda pairs, strict=False: {p: (sum(1 for bb, _h in blk23 if bb <= p[1]), 0) for p in pairs}

    def slow23(url, method, params, **k):
        rg23.ft.t += 5.0
        raise bf_engine.NetError("HTTP Error 408: Request Timeout", "http4xx", code=408)
    real23 = bf_engine.rpc_call
    bf_engine.rpc_call = slow23
    try:
        w23._late_ctx = True
        T.safe(w23._advance, [W[0]], SAFE - 5000, SAFE, HEAD, rg23.ft.t + 200)
        w23._late_ctx = False
    finally:
        bf_engine.rpc_call = real23
    d23 = common.read_json(CPATH, {})
    tl23 = d23.get("_trace_later") or {}
    T.chk(set(tx23) <= set(tl23) and all(int(tl23[h].get("n") or 0) == 0 and tl23[h].get("sent") for h in tx23),
          "B21 따라잡는 걸음에서 trace 를 건너뛴 tx 도 전부 늦은 채움 큐에 n=0 · 방출 표식으로 등록(trace=False 함정 없음 · 디스크)", {"in_queue": len(set(tx23) & set(tl23))})
    T.chk(len(getattr(w23, "_trace_fail", {}) or {}) == 1, "B21 시도 안 한 tx 는 실패 횟수(_trace_fail)를 안 올림(실제로 부른 첫 tx 1건만)", len(getattr(w23, "_trace_fail", {}) or {}))
    T.chk(getattr(R, "TRACE_LATER_MAX", 0) == 2000, "B21 커서 안 늦은 채움 큐 상한 = 2,000(옛 판 상한 그대로 — 롤백 호환 · 넘는 건 넘침 파일 · 코덱스 ba705 #3)", getattr(R, "TRACE_LATER_MAX", 0))
    rg24 = Rig(W[:1], {})
    w24 = rg24.w
    w24.TRACE_LATER_MAX = 5
    now24 = int(rg24.ft.t)
    w24.cursor["_trace_later"] = {f"0xa{i}": {"at": now24 - 1000 + i, "n": (3 if i < 2 else 0), "next": now24 + 999, "blk": 1, "sent": True} for i in range(5)}
    w24.__dict__["_trace_late"] = {}
    for j in range(3):
        hj = f"0xb{j}"
        w24.__dict__["_trace_late"][hj] = 1
        w24._trace_later_mark(hj, {"tx": {"hash": hj, "block_number": 2}, "internal": []})
    tl24 = w24.cursor.get("_trace_later") or {}
    ovf24 = os.path.join(common.STATE_DIR, f"trace_later_overflow_{CH}.jsonl")
    rows24 = [json.loads(x) for x in open(ovf24, encoding="utf-8")] if os.path.exists(ovf24) else []
    T.chk(all(f"0xa{i}" in tl24 for i in range(5)) and not any(f"0xb{j}" in tl24 for j in range(3)) and sorted(r["h"] for r in rows24) == ["0xb0", "0xb1", "0xb2"]
          and all(r.get("sent") for r in rows24),
          "B21 큐 넘침 = 아무것도 버리지 않음 — 큐 항목 그대로 · 새 항목은 넘침 파일(내구 append · 방출 사실 보존)(baser1011 문서2 B3 · 코덱스 bb620 HIGH)", {"q": sorted(tl24), "file": rows24})
    T.chk(int(w24.cursor.get("_trace_later_overflow") or 0) == 3 and not w24.cursor.get("_trace_later_dropped"),
          "B21 넘침 대기 수 커서 기록(_trace_later_overflow — 헬스 사실) · 버린 수 0", {"ovf": w24.cursor.get("_trace_later_overflow"), "drop": w24.cursor.get("_trace_later_dropped")})
    for i in range(5):
        w24.cursor["_trace_later"].pop(f"0xa{i}")
    T.safe(w24._trace_overflow_refill)
    tl24b = w24.cursor.get("_trace_later") or {}
    T.chk(sorted(tl24b) == ["0xb0", "0xb1", "0xb2"] and all(tl24b[h].get("sent") and int(tl24b[h].get("n") or 0) == 0 for h in tl24b)
          and not os.path.exists(ovf24) and not w24.cursor.get("_trace_later_overflow") and sorted((common.read_json(CPATH, {}).get("_trace_later") or {})) == ["0xb0", "0xb1", "0xb2"],
          "B21 자리가 나면 넘침 파일에서 되살림(방출 사실·시도 0 그대로 · 커서 먼저 내구화 뒤 파일 지움)", {"q": tl24b, "file": os.path.exists(ovf24)})
    import health
    ht24 = getattr(health, "trace_later_drop_text", None)
    T.chk(ht24 is not None and ht24({}) is None and "3" in (ht24({"_trace_later_overflow": 3}) or "") and "경고" not in (ht24({"_trace_later_overflow": 3}) or "")
          and "경고" in (ht24({"_trace_later_dropped": 2}) or ""),
          "B21 헬스: 넘침 대기 = 사실 한 줄(경고 아님) · 예전 판이 버린 수가 남아 있으면 경고", [ht24({"_trace_later_overflow": 3}), ht24({"_trace_later_dropped": 2})] if ht24 else None)
    rg25 = Rig(W[:1], {})
    w25 = rg25.w
    now25 = int(rg25.ft.t)
    w25.cursor["_trace_later"] = {"0xold0": {"at": now25 - 31 * 86400, "n": 0, "next": now25 + 999, "blk": 1, "sent": True},
                                  "0xold6": {"at": now25 - 31 * 86400, "n": 6, "next": now25 + 999, "blk": 1, "sent": True}}
    T.safe(w25._trace_later_step, HEAD)
    tl25 = w25.cursor.get("_trace_later") or {}
    T.chk("0xold0" in tl25 and "0xold6" not in tl25, "B21 만료(30일) = 5회 이상 시도한 것만 뺌 · 미시도는 남김(종전: 시도 수 무관)", sorted(tl25))
    rg26 = Rig(W[:1], {})
    w26 = rg26.w
    w26.trace_rpcs = ["http://127.0.0.1:9/trA"]
    for k9 in ("_details", "_trace_internal"):
        w26.__dict__.pop(k9, None)
    w26._batch = lambda cl: []
    h26 = "0x" + "e9" * 32
    w26._rpc_synth_detail = lambda h: {"tx": {"hash": h, "block_number": 7, "from": W[0], "to": "0x" + "55" * 20, "status": "ok", "value": "0",
                                               "raw_input": "0x12345678" + "00" * 32}, "token_transfers": [], "internal": []}
    w26._rpc_call = lambda m, p: {"nonce": "0x0", "from": W[0], "to": "0x" + "55" * 20}
    w26._fill_symbols = lambda snaps: None
    w26.__dict__["_trace_late"] = {f"0xp{i}": 1 for i in range(20_001)}
    real26 = bf_engine.rpc_call
    bf_engine.rpc_call = slow23
    try:
        T.safe(w26._details, [h26], late=True)
    finally:
        bf_engine.rpc_call = real26
    lt26 = w26.__dict__.get("_trace_late") or {}
    T.chk(h26 in lt26 and "0xp20000" in lt26 and "0xp0" not in lt26 and 10_000 <= len(lt26) <= 20_000,
          "B21 늦은 채움 표식 2만 넘음 = 오래된 것부터 덜어 냄(방출 전 표식을 통째 지우지 않음 · 종전: clear)", len(lt26))
    rg27 = Rig(W[:1], {})
    w27 = rg27.w
    for k9 in [k for k in w27.cursor if k.startswith("_bk:")]:
        w27.cursor.pop(k9)
    now27 = int(rg27.ft.t)
    w27.cursor["_trace_later"] = {"0x" + f"{0x3000 + i:064x}": {"at": now27 - 60, "n": 0, "next": 0, "blk": 9, "sent": True} for i in range(25)}
    common.atomic_write_json(CPATH, w27.cursor)
    w27._trace_internal = lambda h, snap: rg27.ft.t.__class__
    T.safe(w27.cycle)
    left27 = len(common.read_json(CPATH, {}).get("_trace_later") or {})
    T.chk(left27 == 5, "B21 라이브가 꼬리에 붙은 사이클 = 늦은 채움 재시도 20건(30초 안 · 종전 3건)", {"left": left27})
finally:
    evm_watch.time = real_time

T.finish()
sys.exit(1 if T.FAILS else 0)
