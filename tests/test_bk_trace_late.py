#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import copy
import json
import os
import time

CH = "zerog"
W = ["0x" + f"{0xb0 + i:02x}" * 20 for i in range(3)]
OTHER = "0x" + "cc" * 20
CFG = {"backfill_months": 0, "chains": {CH: {"discovery": "rpc", "chain_id": 16661, "rpcs": ["http://127.0.0.1:9/rpc"], "getlogs_span": 10_000,
                                             "conf_depth": 10, "blocks_per_day": 1440, "poll_sec": 60, "cycle_budget_sec": 15}},
       "wallets": [{"type": "evm", "chain": CH, "address": w, "label": "w"} for w in W]}
with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump(CFG, f)
import common
import bf_engine
import evm_watch

bf_engine.configure(CFG)
CPATH = os.path.join(common.STATE_DIR, f"cursor_evm_{CH}.json")


def hx(n):
    return "0x" + f"{n:064x}"


class Wr:
    def __init__(self):
        self.recs = []

    def append(self, rec):
        self.recs.append(copy.deepcopy(rec))


def job(frm, done, to, why="internal"):
    return {"from": frm, "done": done, "to": to, "why": why}


def snap_of(h, blk, frm=None):
    return {"tx": {"hash": h, "block_number": int(blk), "from": frm or W[0], "to": OTHER, "status": "ok", "raw_input": "0x12345678"},
            "token_transfers": [], "internal": []}


def make(cursor, span=16_000, bk_span=200_000, live=900_000):
    bf_engine._PROGRESS.clear()
    cur = {"_rpc_v": 1, "_start": 0, "_handover": {}}
    cur.update({w: live for w in W})
    cur.update(cursor)
    cur.setdefault("_bkspan", span)
    common.atomic_write_json(CPATH, cur)
    common.atomic_write_json(os.path.join(common.STATE_DIR, f"emitted_evm_{CH}.json"), [])
    wr = Wr()
    w = evm_watch.RpcChainWatcher(CFG, CH, list(W), wr)
    w.bk_span = bk_span
    w.multicall = None
    w.trace_rpcs = ["http://127.0.0.1:9/trace"]
    w.trace_mode = "all"
    st = {"scans": [], "details": [], "native": [], "traces": [], "blocks": {}, "trace_fn": None, "native_fn": None}

    def scan(ws, c, target, deadline):
        st["scans"].append((int(c), int(target)))
        f9 = {h: b for h, b in st["blocks"].items() if int(c) < b <= int(target)}
        return f9, int(target), None
    w._scan_logs = scan
    w._states = lambda *a, **k: None

    def native(wa, c, last, pool, dl, nk=None, **k):
        st["native"].append((wa, int(c), int(last)))
        if st["native_fn"]:
            st["native_fn"](wa, c, last)
        return {"ns": [int(last), 0, "0"]}
    w._native = native
    w._batch = lambda calls: (_ for _ in ()).throw(RuntimeError("시험: 배치 없음"))

    def synth(h):
        st["details"].append(h)
        return snap_of(h, st["blocks"].get(h, 1))
    w._rpc_synth_detail = synth
    w._rpc_call = lambda m, p: {"nonce": "0x1", "from": W[0], "to": OTHER} if m == "eth_getTransactionByHash" else None

    def trace(h, snap):
        st["traces"].append(h)
        rows = st["trace_fn"](h) if st["trace_fn"] else []
        snap["internal"] = rows
        snap["internal_note"] = "trace"
        w._trace_fail.pop(h, None)
    w._trace_internal = trace
    return w, wr, st


def disk():
    return common.read_json(CPATH, {})


def restore_like_cycle(w):
    cur9 = common.read_json(w.cursor_path, {})
    for k9 in [k for k in w.cursor if k.startswith("_bk:") or k in ("_bkns", "_bkscan", "_hq", "_bkspan")]:
        if k9 in cur9:
            w.cursor[k9] = cur9[k9]
        else:
            w.cursor.pop(k9, None)


def fail408(h):
    raise RuntimeError("HTTP Error 408: Request Timeout (Request timeout on the free plan)")


w, wr, st = make({"_bk:" + a: job(0, 5000, 100_000) for a in W}, span=16_000)


def bisect_out(wa, c, last):
    raise RuntimeError("이분 탐색 예산 소진")


st["native_fn"] = bisect_out
r = T.safe(w._bk_step, 10 ** 7, time.time() + 60)
T.chk(isinstance(r, dict) and "이분 탐색 예산 소진" in r.get("_exc", ""), "B1 일반 예외는 그대로 올라감(cycle 이 되돌리기·경고)", r)
T.chk(disk().get("_bkspan") == 8000, "B1 디스크 _bkspan 16,000 → 8,000(종전: 16,000 그대로 — 같은 큰 걸음 되풀이)", disk().get("_bkspan"))
restore_like_cycle(w)
T.chk(w.cursor.get("_bkspan") == 8000, "B1 cycle 식 되돌리기 뒤 메모리 구간도 8,000", w.cursor.get("_bkspan"))
T.chk(all(int(j["done"]) == 5000 for j in w._bk_jobs().values()), "B1 진행점은 그대로(5,000)", {k[:6]: v["done"] for k, v in w._bk_jobs().items()})
T.chk(isinstance(disk().get("_bkscan"), dict) and disk()["_bkscan"].get("to") == 21_000, "B1 getLogs 체크포인트(5,001~21,000)는 디스크에 남음(다음 걸음이 이어 씀)",
      disk().get("_bkscan"))
w, wr, st = make({"_bk:" + a: job(0, 5000, 100_000) for a in W}, span=2000)
st["native_fn"] = bisect_out
T.safe(w._bk_step, 10 ** 7, time.time() + 60)
T.chk(disk().get("_bkspan") == 2000, "B1 하한 2,000 아래로는 안 줄임", disk().get("_bkspan"))

HA, HB = hx(0xA1), hx(0xB2)
ck = {"frm": 5001, "to": 37_000, "ws": sorted(W), "found": {HA: 6000, HB: 30_000}}
w, wr, st = make({**{"_bk:" + a: job(0, 5000, 100_000) for a in W}, "_bkscan": ck}, span=16_000)
st["blocks"] = {HA: 6000, HB: 30_000}
seen = []
real_adv = w._advance


def adv_spy(ws, c, target, head, deadline, bk=False):
    n0 = len(st["details"])
    got = real_adv(ws, c, target, head, deadline, bk=bk)
    seen.append((int(c), int(target), int(got), list(st["details"][n0:])))
    return got


w._advance = adv_spy
r = T.safe(w._bk_step, 10 ** 7, time.time() + 60)
T.chk(seen and seen[0][:3] == (5000, 21_000, 21_000), "B2 첫 걸음 = 줄인 목표 21,000 까지만(종전: 체크포인트 끝 37,000 까지)", seen[:2])
T.chk(seen and seen[0][3] == [HA], "B2 첫 걸음 상세 = 목표 안 tx 만(HA) — 목표 밖 HB 는 다음 걸음", seen[:2])
T.chk(len(seen) > 1 and seen[1][0] == 21_000 and seen[1][2] == 37_000 and seen[1][3] == [HB], "B2 다음 걸음 = 남긴 체크포인트(21,001~37,000) 그대로 → HB", seen[:3])
T.chk(st["scans"] and min(c for c, _t in st["scans"]) >= 37_000, "B2 체크포인트 구간(5,001~37,000)은 getLogs 다시 안 부름", st["scans"][:3])
T.chk(not w._bk_jobs() and not isinstance(r, dict), "B2 완주", {"r": r, "left": len(w._bk_jobs())})
T.chk(sorted(x["txhash"] for x in wr.recs) == sorted([HA, HB]), "B2 두 tx 모두 한 번씩 방출(빠짐·중복 없음)", [x["txhash"][-4:] for x in wr.recs])

w, wr, st = make({**{"_bk:" + a: job(0, 5000, 100_000) for a in W}, "_bkscan": dict(ck)}, span=16_000)
st["blocks"] = {HA: 6000, HB: 30_000}
calls3 = {"n": 0}


def once(wa, c, last):
    if calls3["n"] == 0:
        calls3["n"] += 1
        raise RuntimeError("이분 탐색 예산 소진")


st["native_fn"] = once
seen = []
real_adv = w._advance
w._advance = adv_spy
r1 = T.safe(w._bk_step, 10 ** 7, time.time() + 60)
restore_like_cycle(w)
T.chk(isinstance(r1, dict) and disk().get("_bkspan") == 8000, "B3 첫 사이클 = 실패 · 디스크 구간 8,000", {"r": r1, "span": disk().get("_bkspan")})
n1 = len(seen)
r2 = T.safe(w._bk_step, 10 ** 7, time.time() + 60)
T.chk(len(seen) > n1 and seen[n1][:3] == (5000, 13_000, 13_000) and HB not in seen[n1][3],
      "B3 다음 사이클 첫 걸음 = 5,000 → 13,000(줄인 구간 · 체크포인트 재사용 · HB 는 다음)(종전: 37,000 전체 다시)", seen[n1:n1 + 2])
T.chk(any(c == 5000 and last == 13_000 for _w, c, last in st["native"]),
      "B3 정합(이분 탐색 자리)도 5,000 → 13,000 만", [x[1:] for x in st["native"]][:6])
T.chk(not w._bk_jobs() and sorted(x["txhash"] for x in wr.recs) == sorted([HA, HB]), "B3 이어서 완주 · 두 tx 한 번씩",
      {"left": len(w._bk_jobs()), "recs": [x["txhash"][-4:] for x in wr.recs]})

LATE = W[2]
cur4 = {"_bk:" + a: job(0, 9000, 50_000) for a in W[:2]}
cur4["_bk:" + LATE] = job(0, 5000, 50_000, "new")
cur4["_bkscan"] = {"frm": 5001, "to": 20_000, "ws": [LATE], "found": {}}
w, wr, st = make(cur4, span=16_000)
seen = []
real_adv = w._advance
w._advance = adv_spy
T.safe(w._bk_step, 10 ** 7, time.time() + 60)
T.chk(seen and seen[0][:3] == (5000, 9000, 9000), "B4 늦은 지갑의 체크포인트(~20,000)를 다음 묶음 진행점 9,000 에서 끊음 → 거기서 합침(종전: 20,000 까지 지나침)", seen[:2])
T.chk(len(seen) > 1 and seen[1][0] == 9000, "B4 9,000 부터 세 지갑 한 묶음", seen[:3])

H1 = hx(0xC1)
w, wr, st = make({"_bk:" + a: job(0, 5000, 21_000) for a in W}, span=16_000)
st["blocks"] = {H1: 6000}
st["trace_fn"] = fail408
t0 = int(time.time())
r = T.safe(w._bk_step, 10 ** 7, time.time() + 60)
T.chk(r == (16_000, False), "T1 trace 408 이어도 뒤 차선 걸음 전진(5,000 → 21,000 · 정지 아님)(종전: (0, 정지) — 사이클마다 멈춤)", r)
T.chk([x["txhash"] for x in wr.recs] == [H1] and not wr.recs[0]["snapshot"].get("internal"), "T1 그 tx 는 internal 없이 방출(종전 3회 실패 뒤와 같은 모양)",
      [x["txhash"][-4:] for x in wr.recs])
tl = (disk().get("_trace_later") or {}).get(H1)
T.chk(isinstance(tl, dict) and tl.get("n") == 0 and tl.get("blk") == 6000 and t0 + 100 <= int(tl.get("next") or 0) <= t0 + 200,
      "T1 '나중에 다시' 표식이 디스크 커서에(_trace_later · 블록 · 2분 뒤 재시도)", tl)
T.chk(len(st["traces"]) == 1, "T1 같은 사이클에 trace 를 되풀이하지 않음(1회)", len(st["traces"]))

H2, H3 = hx(0xD2), hx(0xE3)
w, wr, st = make({}, span=16_000)
st["blocks"] = {H2: 100, H3: 101}
st["trace_fn"] = fail408
w.cursor.pop("_handover", None)
res = [T.safe(w._details, [H2]).get(H2) for _ in range(w.TRACE_RETRY)]
T.chk(all(isinstance(x, Exception) for x in res[:-1]) and isinstance(res[-1], dict),
      f"T2 라이브 = {w.TRACE_RETRY - 1}회까지 재시도(예외) · {w.TRACE_RETRY}회째 확정(종전 그대로)", [type(x).__name__ for x in res])
w._emit(H2, res[-1], 200)
T.chk(isinstance((w.cursor.get("_trace_later") or {}).get(H2), dict), "T2 확정 방출 = '나중에 다시' 표식(종전: 영구 internal 없이 확정 · 표식 없음)",
      w.cursor.get("_trace_later"))
w.cursor["_hq"] = {H3: 0}
res3 = [T.safe(w._details, [H3]).get(H3) for _ in range(w.TRACE_RETRY)]
w._emit(H3, res3[-1], 200)
T.chk(H3 not in (w.cursor.get("_trace_later") or {}) and H3 in w.cursor["_hq"], "T2 인계 큐(_hq) tx 는 표식 안 함(_hq_step 이 다시 trace)",
      {"tl": list(w.cursor.get("_trace_later") or {}), "hq": list(w.cursor["_hq"])})
ok_snap = snap_of(H2, 100)
ok_snap["internal"], ok_snap["internal_note"] = [{"from": OTHER, "to": W[0], "value": "5", "success": True}], "trace"
w._emit(H2, ok_snap, 201)
T.chk(H2 not in (w.cursor.get("_trace_later") or {}), "T2 trace 를 끝낸 방출(다른 길 — 잎 trace 등)은 표식 지움", w.cursor.get("_trace_later"))

now = int(time.time())
HA3, HB3, HC3, HD3, HE3, HF3, HG3 = (hx(0x300 + i) for i in range(7))
tl3 = {HF3: {"at": now - 60, "n": 0, "next": 0, "blk": 10, "sent": False},
       HA3: {"at": now - 60, "n": 0, "next": 1, "blk": 11},
       HB3: {"at": now - 60, "n": 0, "next": 2, "blk": 12},
       HC3: {"at": now - 60, "n": 2, "next": 3, "blk": 13},
       HD3: {"at": now - 60, "n": 0, "next": 4, "blk": 14},
       HE3: {"at": now - 60, "n": 0, "next": now + 9999, "blk": 15},
       HG3: {"at": now - 31 * 86400, "n": 40, "next": 0, "blk": 16}}
w, wr, st = make({"_trace_later": tl3}, span=16_000)
w.emitted.update([HA3, HB3, HC3, HD3, HE3, HG3])
st["blocks"] = {HA3: 11, HB3: 12, HC3: 13, HD3: 14}


def tr3(h):
    if h == HA3:
        return [{"from": OTHER, "to": W[0], "value": "7", "success": True}]
    if h == HB3:
        return []
    if h == HC3:
        raise RuntimeError("HTTP Error 429: Too Many Requests")
    if h == HD3:
        raise RuntimeError("-32601 the method debug_traceTransaction does not exist/is not available")
    raise AssertionError("시험: 부르면 안 되는 tx " + h)


st["trace_fn"] = tr3
step = getattr(w, "_trace_later_step", None)
n = T.safe(step, 300) if step else {"_exc": "_trace_later_step 없음"}
d3 = disk().get("_trace_later") or {}
T.chk(n == 1 and [x["txhash"] for x in wr.recs] == [HA3], "T3 회복한 tx = internal 붙여 다시 방출 1건", {"n": n, "recs": [x["txhash"][-4:] for x in wr.recs]})
T.chk(wr.recs and wr.recs[0]["snapshot"].get("internal_note") == "trace" and wr.recs[0]["snapshot"]["internal"][0]["value"] == "7"
      and wr.recs[0].get("repair") == "int_fill", "T3 다시 방출 = trace internal · int_fill 표식(차선 모드 — core 가 internal 만 합침)",
      wr.recs[0] if wr.recs else None)
T.chk(HA3 not in d3 and HB3 not in d3, "T3 회복·internal 없음 = 표식 뺌(디스크)", sorted(k[-4:] for k in d3))
T.chk(st["details"] == [HA3], "T3 상세는 internal 이 나온 tx 만 받음(실패·없음 = 상세 콜 0)", [h[-4:] for h in st["details"]])
T.chk(d3.get(HC3, {}).get("n") == 3 and int(d3[HC3]["next"]) >= now + 120 * 8 and "429" in str(d3[HC3].get("err")),
      "T3 일시 실패 = 남겨 두고 간격 배(3회째 · 16분↑)", d3.get(HC3))
T.chk(d3.get(HD3, {}).get("n") == 0 and HD3 not in st["traces"], "T3 사이클당 상한 3건 — 4번째(HD3)는 다음 번", {"d": d3.get(HD3), "traces": [h[-4:] for h in st["traces"]]})
T.chk(HF3 in d3 and HF3 not in st["traces"] and HE3 in d3 and HE3 not in st["traces"], "T3 방출 사실 없는 tx(sent False · emitted 없음) · 아직 아닌 tx 는 건드리지 않음", sorted(k[-4:] for k in d3))
T.chk(HG3 not in d3 and any(r.get("kind") == "trace_later_giveup" for r in w.cursor.get("_native_notes") or []), "T3 30일 넘음 = 기록 남기고 뺌",
      [r.get("kind") for r in w.cursor.get("_native_notes") or []])
w.cursor["_trace_later"][HD3]["next"] = 0
T.safe(w._trace_later_step, 301)
d3 = disk().get("_trace_later") or {}
T.chk(HD3 not in d3 and any(r.get("kind") == "trace_later_unsupported" for r in w.cursor.get("_native_notes") or []),
      "T3 노드가 메서드를 아예 안 줌(-32601) = 기록 남기고 뺌", sorted(k[-4:] for k in d3))
w.trace_rpcs = []
T.chk(T.safe(w._trace_later_step, 302) == 0, "T3 trace 노드 없음 = 0(콜 없음)")

HT4 = hx(0x401)
w, wr, st = make({**{"_bk:" + a: job(0, 5000, 100_000) for a in W}, "_trace_later": {HT4: {"at": now - 60, "n": 0, "next": 0, "blk": 900}}},
                 span=16_000, live=900_000)
w.emitted.add(HT4)
st["blocks"] = {HT4: 900}
st["trace_fn"] = lambda h: [{"from": OTHER, "to": W[1], "value": "3", "success": True}] if h == HT4 else []
st["native_fn"] = bisect_out
w._head = lambda: 900_010
w._init = lambda safe: None
hc = []
w._health_cycle = lambda *a, **k: hc.append((a, k))
r4 = T.safe(w.cycle)
T.chk(not isinstance(r4, dict), "T4 cycle 예외 없이 끝(뒤 차선 실패는 경고만)", r4)
T.chk([x["txhash"] for x in wr.recs] == [HT4] and HT4 not in (disk().get("_trace_later") or {}), "T4 cycle 이 늦은 채움을 돌림(다시 방출 · 표식 뺌)",
      {"recs": [x["txhash"][-4:] for x in wr.recs], "tl": disk().get("_trace_later")})
T.chk(w.cursor.get("_bkspan") == 8000 and disk().get("_bkspan") == 8000, "T4 뒤 차선 일반 실패 → 되돌린 뒤 구간 8,000(메모리·디스크)(종전: 16,000)",
      {"mem": w.cursor.get("_bkspan"), "disk": disk().get("_bkspan")})

HT5 = hx(0x501)
NEWW = "0x" + "e7" * 20
common.atomic_write_json(CPATH, {"_rpc_v": 1, "_start": 0, **{a: 900_000 for a in W},
                                 "_trace_later": {HT5: {"at": now - 60, "n": 0, "next": 0, "blk": 800, "sent": True}}})
common.atomic_write_json(os.path.join(common.STATE_DIR, f"emitted_evm_{CH}.json"), [HT5])
wr5 = Wr()
w5 = evm_watch.RpcChainWatcher(CFG, CH, list(W) + [NEWW], wr5)
T.chk(not w5.emitted and common.read_json(os.path.join(common.STATE_DIR, f"emitted_evm_{CH}.json"), None) == [], "T5 준비: 새 지갑 합류 = emitted 초기화(종전 규약)")
w5.trace_rpcs = ["http://127.0.0.1:9/trace"]
w5._batch = lambda calls: (_ for _ in ()).throw(RuntimeError("시험: 배치 없음"))
w5._rpc_synth_detail = lambda h: snap_of(h, 800)
w5._rpc_call = lambda m, p: {"nonce": "0x1", "from": W[0], "to": OTHER} if m == "eth_getTransactionByHash" else None


def tr5(h, snap):
    snap["internal"] = [{"from": OTHER, "to": W[0], "value": "11", "success": True}]
    snap["internal_note"] = "trace"


w5._trace_internal = tr5
n5 = T.safe(w5._trace_later_step, 500)
T.chk(n5 == 1 and [x["txhash"] for x in wr5.recs] == [HT5] and HT5 not in (common.read_json(CPATH, {}).get("_trace_later") or {}),
      "T5 emitted 가 비어도 표식의 '방출됨' 사실로 늦은 채움 진행(종전: emitted 에 없어 30일 뒤 표식만 삭제)", {"n": n5, "recs": [x["txhash"][-4:] for x in wr5.recs]})
w6, wr6, st6 = make({}, span=16_000)
st6["trace_fn"] = fail408
H6 = hx(0x601)
st6["blocks"] = {H6: 50}
w6.cursor.pop("_handover", None)
for _ in range(w6.TRACE_RETRY):
    s6 = T.safe(w6._details, [H6]).get(H6)
w6._emit(H6, s6, 60)
T.chk((w6.cursor.get("_trace_later") or {}).get(H6, {}).get("sent") is True, "T5 표식에 방출 사실(sent) 기록", (w6.cursor.get("_trace_later") or {}).get(H6))

HQ6, TL6 = hx(0x611), hx(0x612)
EP = os.path.join(common.STATE_DIR, f"enrich_{CH}.json")
HP = os.path.join(common.STATE_DIR, f"hq_left_{CH}.json")
for tgt in ("blockscout", "etherscan"):
    for p9 in (EP, HP):
        if os.path.exists(p9):
            os.remove(p9)
    w7, wr7, st7 = make({"_hq": {HQ6: 0}, "_trace_later": {TL6: {"at": now - 60, "n": 1, "next": now + 99, "blk": 70, "sent": True}}}, span=16_000)
    r7 = T.safe(evm_watch.rpc_handback, w7, tgt)
    got7 = common.read_json(EP if tgt == "blockscout" else HP, {}) or {}
    T.chk(not isinstance(r7, dict) and HQ6 in got7 and TL6 in got7,
          f"T6 {tgt} 되돌림 = 인계 큐(_hq) + 늦은 채움(_trace_later) 둘 다 " + ("enrich 로" if tgt == "blockscout" else "hq_left 보관(다시 RPC = _hq 로 되살림)")
          + "(종전: _trace_later 버림)", {"r": r7, "got": sorted(k[-4:] for k in got7)})
    T.chk(int((common.read_json(CPATH, {}).get("_handback") or {}).get("trace_later") or 0) == 1, f"T6 {tgt} 되돌림 기록에 늦은 채움 수",
          common.read_json(CPATH, {}).get("_handback"))

HT7, HQ7 = hx(0x701), hx(0x702)
for tgt in ("etherscan", "blockscout"):
    for p9 in (EP, HP, os.path.join(common.STATE_DIR, f"trace_later_left_{CH}.json")):
        if os.path.exists(p9):
            os.remove(p9)
    w8, wr8, st8 = make({"_trace_later": {HT7: {"at": now - 60, "n": 2, "next": now + 500, "blk": 70, "sent": True}}}, span=16_000)
    T.safe(evm_watch.rpc_handback, w8, tgt)
    w9 = evm_watch.RpcChainWatcher(CFG, CH, list(W), Wr())
    w9.handover = "rescan"
    w9.lanes_cfg = False
    w9._window_start = lambda safe: 1000
    w9._states = lambda *a, **k: {}
    w9.trace_rpcs = ["http://127.0.0.1:9/trace"]
    r9 = T.safe(w9._init, 900_000)
    tl9 = (common.read_json(CPATH, {}).get("_trace_later") or {}).get(HT7)
    T.chk(not isinstance(r9, dict) and isinstance(tl9, dict) and tl9.get("n") == 2 and tl9.get("sent") is True,
          f"T7 {tgt} 되돌림 → rescan 으로 RPC 복귀 = 늦은 채움 표식 되살림(백오프 그대로)(종전: 보관분 유실)", {"r": r9, "tl": tl9})
    T.chk(not (common.read_json(os.path.join(common.STATE_DIR, f"trace_later_left_{CH}.json"), {}) or {})
          and HT7 not in (common.read_json(HP, {}) or {}), f"T7 {tgt} 되살린 뒤 보관 파일·hq_left 에서 그 해시 정리(두 번 일 안 함)",
          {"left": common.read_json(os.path.join(common.STATE_DIR, f"trace_later_left_{CH}.json"), {}), "hq_left": common.read_json(HP, {})})
w10, _wr10, _st10 = make({"_hq": {HQ7: 0}}, span=16_000)
common.atomic_write_json(os.path.join(common.STATE_DIR, f"trace_later_left_{CH}.json"),
                         {HQ7: {"at": now - 60, "n": 0, "next": 0, "blk": 71, "sent": True}, HT7: {"at": now - 60, "n": 0, "next": 0, "blk": 72, "sent": True}})
T.safe(w10._legacy_queues)
d10 = common.read_json(CPATH, {})
T.chk(HQ7 not in (d10.get("_trace_later") or {}) and HT7 in (d10.get("_trace_later") or {}) and HQ7 in (d10.get("_hq") or {}),
      "T7 인계 큐(_hq)에 이미 있는 해시는 _hq_step 몫 — 늦은 채움엔 나머지만", {"tl": sorted(k[-4:] for k in d10.get("_trace_later") or {})})

H8a, H8b = hx(0x801), hx(0x802)
w, wr, st = make({}, span=16_000)
st["blocks"] = {H8a: 100, H8b: 101}
st["trace_fn"] = fail408
w._late_ctx = True
r8a = T.safe(w._details, [H8a]).get(H8a)
T.chk(isinstance(r8a, dict) and H8a in w.__dict__.get("_trace_late", set()), "T8 문맥 켬 = late 인자 없이도 trace 첫 실패에 확정 + 늦은 채움 표식(종전: 예외 · 재시도)",
      type(r8a).__name__)
w._late_ctx = False
r8b = T.safe(w._details, [H8b]).get(H8b)
T.chk(isinstance(r8b, Exception) and "재시도" in str(r8b), "T8 문맥 끔 = 종전대로 TRACE_RETRY 재시도(예외)", r8b)

seen9 = []


def spy9(wo):
    def adv(ws, c, target, head, deadline, bk=False):
        seen9.append((bool(bk), int(c), int(target), bool(wo.__dict__.get("_late_ctx"))))
        return int(target)
    return adv


w, wr, st = make({}, span=16_000, live=1000)
w.cursor["_lvspan"] = 3000
w._head = lambda: 10_010
w._init = lambda safe: None
w._head_peek = lambda *a, **k: None
w._health_cycle = lambda *a, **k: None
w._advance = spy9(w)
r9 = T.safe(w.cycle)
lv9 = [x for x in seen9 if not x[0]]
T.chk(not isinstance(r9, dict) and len(lv9) >= 2 and all(x[3] for x in lv9[:-1]) and lv9[-1][3] is False and lv9[-1][2] == max(x[2] for x in lv9),
      "T9 라이브 따라잡는 걸음 = 문맥 켬 · 헤드에 닿는 마지막 걸음 = 끔(평시 꼬리는 종전 재시도)", {"r": r9, "steps": lv9})
T.chk(not w.__dict__.get("_late_ctx"), "T9 사이클 뒤 문맥 끔(다른 상세 호출에 새지 않음)", w.__dict__.get("_late_ctx"))
seen9.clear()
w, wr, st = make({"_bk:" + a: job(0, 5000, 100_000) for a in W}, span=16_000, live=900_000)
w._head = lambda: 900_010
w._init = lambda safe: None
w._head_peek = lambda *a, **k: None
w._health_cycle = lambda *a, **k: None
w._advance = spy9(w)
T.safe(w.cycle)
bk9 = [x for x in seen9 if x[0]]
T.chk(bk9 and all(x[3] for x in bk9) and not w.__dict__.get("_late_ctx"), "T9 뒤 차선 걸음 = 문맥 켬(잎 정합 상세도 늦은 채움) · 끝나면 끔", bk9[:3])


def boom9(ws, c, target, head, deadline, bk=False):
    raise RuntimeError("이분 탐색 예산 소진")


w, wr, st = make({}, span=16_000, live=1000)
w.cursor["_lvspan"] = 3000
w._head = lambda: 10_010
w._init = lambda safe: None
w._head_peek = lambda *a, **k: None
w._health_cycle = lambda *a, **k: None
w._advance = boom9
T.safe(w.cycle)
T.chk(not w.__dict__.get("_late_ctx"), "T9 걸음 예외여도 문맥 끔(finally)", w.__dict__.get("_late_ctx"))

H10 = hx(0xA10)
w, wr, st = make({}, span=16_000, live=1000)
w.cursor["_lvspan"] = 3000
st["blocks"] = {H10: 2000}
st["trace_fn"] = lambda h: (_ for _ in ()).throw(RuntimeError("HTTP Error 429: Too Many Requests (You reached Public endpoint limit)"))
w._head = lambda: 10_010
w._init = lambda safe: None
w._head_peek = lambda *a, **k: None
w._health_cycle = lambda *a, **k: None
r10 = T.safe(w.cycle)
cur10 = [int(w.cursor[a]) for a in W]
T.chk(not isinstance(r10, dict) and min(cur10) >= 10_000 - 1, "T10 따라잡는 걸음 tx 의 trace 429 = 걸음 안 멈춤 → 첫 사이클에 라이브 커서 헤드(safe)까지(종전: 1,000 그대로 · 걸음 반감)",
      {"r": r10, "cur": cur10, "lv": w.cursor.get("_lvspan")})
T.chk([x["txhash"] for x in wr.recs] == [H10] and isinstance((w.cursor.get("_trace_later") or {}).get(H10), dict),
      "T10 그 tx = internal 없이 방출 + '나중에 다시' 표식(백오프 trace → 나오면 재방출)", {"recs": [x["txhash"][-4:] for x in wr.recs], "tl": list(w.cursor.get("_trace_later") or {})})
T.chk(int(w.cursor.get("_lvspan") or 3000) >= 3000, "T10 걸음 반감 없음", w.cursor.get("_lvspan"))

T.finish()
sys.exit(1 if T.FAILS else 0)
