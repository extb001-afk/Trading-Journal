#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import inspect
import json
import os
import time

CH = "zerog"
W = ["0x" + f"{0xc0 + i:02x}" * 20 for i in range(2)]
CFG = {"backfill_months": 0, "chains": {CH: {"discovery": "rpc", "chain_id": 16661, "rpcs": ["http://127.0.0.1:9/rpc"], "getlogs_span": 10_000_000,
                                             "conf_depth": 10, "blocks_per_day": 43200, "poll_sec": 60, "cycle_budget_sec": 15}},
       "wallets": [{"type": "evm", "chain": CH, "address": w, "label": "w"} for w in W]}
with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump(CFG, f)
import common
import bf_engine
import evm_watch

bf_engine.configure(CFG)
CPATH = os.path.join(common.STATE_DIR, f"cursor_evm_{CH}.json")
C0, TGT = 51_240_000, 51_888_500
LEAVES = [51_888_466, 51_888_472, 51_888_474, 51_888_479, 51_888_481]


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


HNEW = "0x" + "9e" * 32


def run(extra_cursor=None, cycles=90, fail_pick=None, deposit=False):
    cur = {"_rpc_v": 1, "_start": C0}
    cur.update({w: C0 for w in W})
    cur.update(extra_cursor or {})
    common.atomic_write_json(CPATH, cur)
    common.atomic_write_json(os.path.join(common.STATE_DIR, f"emitted_evm_{CH}.json"), [])
    ft = FakeTime()
    real = evm_watch.time
    evm_watch.time = ft
    try:
        w = evm_watch.RpcChainWatcher(CFG, CH, list(W), Wr())
        w.multicall = None
        w.trace_rpcs = ["http://127.0.0.1:9/trace"]
        w._scan_logs = lambda ws, c, target, dl: (({HNEW: TGT - 5} if deposit else {}), int(target), None)
        w._details = lambda hs, deadline=None, trace=True, **k: {h: {"tx": {"hash": h, "block_number": TGT - 5, "from": "0x" + "ab" * 20, "to": W[1],
                                                                             "status": "ok"}, "token_transfers": [], "internal": []} for h in hs}
        w._states = lambda *a, **k: None
        sig = inspect.signature(w._leaf_retry).parameters
        st = {"cyc": 0, "fails": []}

        def native(wa, c, last, pool, dl, nk="_ns", head=None):
            if wa != W[0]:
                return {"ns": [int(last), 0, "0"]}
            bad = fail_pick(st["cyc"]) if fail_pick else flaky(st["cyc"])
            kw = {"c": c, "nk": nk} if "c" in sig else {}
            for y in LEAVES:
                if y == bad:
                    st["fails"].append(y)
                    w._leaf_retry(wa, y, False, **kw)
                    continue
                w._leaf_retry(wa, y, True, **kw)
            return {"ns": [int(last), 0, "0"]}
        w._native = native
        adv_at = None
        for i in range(cycles):
            st["cyc"] = i
            try:
                got = w._advance(list(W), C0, TGT, TGT + 10, ft.t + 15)
            except RuntimeError:
                got = C0
                w.cursor = common.read_json(CPATH, {})
            if got > C0:
                adv_at = i
                break
            ft.t += 60.0
        return w, adv_at, st
    finally:
        evm_watch.time = real


def flaky(i, p=0.75, seed=7):
    import random
    r = random.Random(seed * 100_003 + i)
    for y in LEAVES:
        if r.random() < p:
            return y
    return None


w, adv_at, st = run()
T.chk(adv_at is not None and adv_at <= 40, "F1 실패 잎이 사이클마다 바뀌어도 ≈30분 안에 커서 전진(종전: 90분 넘게 정지 — 잎마다 계수 다시 시작)",
      {"advanced_cycle": adv_at, "fails": st["fails"][:12]})
T.chk(adv_at is not None and adv_at >= 29, "F2 한도(30분) 전엔 종전대로 커서 유지 — 너무 일찍 넘기지 않음", adv_at)
d = common.read_json(CPATH, {})
T.chk(adv_at is not None and all(int(d.get(x) or 0) == TGT for x in W), "F2 전진 = 두 지갑 커서 TGT", {x[:6]: d.get(x) for x in W})
ll = d.get("_leaf_later") or {}
T.chk(ll and all(isinstance(v, dict) and v.get("w") == W[0] and int(v.get("blk") or 0) in LEAVES for v in ll.values()),
      "F2 넘긴 잎 = '나중에 다시'(_leaf_later) 블록별(블록 trace 로 계속 재시도)", sorted(int(v.get("blk") or 0) for v in ll.values()))
T.chk(not (d.get("_leaf_fail") or {}), "F2 전진 뒤 그 구간 계수 지움(_leaf_fail 비움)", d.get("_leaf_fail"))

w, adv_same, st2 = run(fail_pick=lambda i: LEAVES[2])
T.chk(adv_same is not None and 29 <= adv_same <= 40, "F2 같은 잎만 계속 실패 = 종전과 같은 한도(≈30분)", adv_same)

old = {f"{W[0][:12]}:{y}": [2, 1_800_000_000 - 100] for y in LEAVES[:2]}
old[f"{W[1][:12]}:123"] = [1, 1_800_000_000 - 90_000]
w, adv3, st3 = run(extra_cursor={"_leaf_fail": dict(old)})
d3 = common.read_json(CPATH, {})
T.chk(adv3 is not None and adv3 <= 40, "F3 옛 키(지갑:블록)가 있어도 기동·전진 정상", adv3)
T.chk(not any(k in (d3.get("_leaf_fail") or {}) for k in old), "F3 옛 키는 성공 잎·24시간 정리로 사라짐", d3.get("_leaf_fail"))

OVF = os.path.join(common.STATE_DIR, f"leaf_later_overflow_{CH}.jsonl")
full = {f"{W[1][:12]}:{100 + i}": {"w": W[1], "blk": 100 + i, "at": 1_799_000_000 + i, "n": 1, "next": 1_900_000_000} for i in range(evm_watch.RpcChainWatcher.LEAF_LATER_MAX)}
if os.path.exists(OVF):
    os.remove(OVF)
w, adv4, st4 = run(extra_cursor={"_leaf_later": dict(full)}, cycles=45, deposit=True)
d4 = common.read_json(CPATH, {})
ll4 = d4.get("_leaf_later") or {}
T.chk(all(k in ll4 for k in full), "F4 큐가 꽉 차도 기존 '나중에 다시' 잎을 잘라 버리지 않음(종전: 오래된 것부터 무음 삭제 → internal 입금 영구 누락)",
      {"kept": sum(1 for k in full if k in ll4), "of": len(full)})
T.chk(adv4 is not None and adv4 <= 40 and all(int(d4.get(x) or 0) == TGT for x in W),
      "F4 포화여도 커서 전진(≈30분 한도 그대로) — 옛 잎 실패가 라이브 꼬리를 붙잡지 않음(bk471 판: 무기한 유지)", {"adv": adv4})
T.chk(HNEW in [r.get("txhash") for r in w.writer.recs], "F4 그 걸음의 최신 입금 tx 방출(포화가 최신 방출을 막지 않음)", len(w.writer.recs))
ov4 = []
if os.path.exists(OVF):
    with open(OVF, encoding="utf-8") as f9:
        ov4 = [json.loads(x) for x in f9 if x.strip()]
gave4 = sorted({int(r["blk"]) for r in (d4.get("_native_notes") or []) if r.get("kind") == "leaf_giveup"})
T.chk(gave4 and sorted({int(e["blk"]) for e in ov4}) == gave4 and int(d4.get("_leaf_overflow") or 0) == len(ov4),
      "F4 큐에 못 넣은 잎 = 넘침 파일(state/leaf_later_overflow_<체인>.jsonl)로 — 넘긴 잎 전부 · 수 기록(무음 삭제 0)",
      {"gave": gave4, "ovf": sorted({int(e["blk"]) for e in ov4}), "n": d4.get("_leaf_overflow")})
lk = f"{W[0][:12]}:{LEAVES[0]}"
w4 = evm_watch.RpcChainWatcher(CFG, CH, list(W), Wr())
w4.cursor["_leaf_later"] = dict(full)
w4.cursor["_leaf_later"].pop(next(iter(full)))
w4.cursor["_leaf_later"][lk] = {"w": W[0], "blk": LEAVES[0], "at": 1_799_000_000, "n": 3, "next": 1_900_000_123}
w4.cursor["_leaf_fail"] = {"@_ns:5": [99, int(time.time()) - 3600]}
r4 = T.safe(w4._leaf_retry, W[0], LEAVES[0], False, c=5, nk="_ns") if "c" in inspect.signature(w4._leaf_retry).parameters else {"_exc": "c 없음"}
T.chk(r4 is False and w4.cursor["_leaf_later"][lk]["n"] == 3 and w4.cursor["_leaf_later"][lk]["next"] == 1_900_000_123,
      "F4 이미 큐에 있는 잎 = 백오프(n·next) 보존 · 포화여도 넘김(새 자리 안 씀)", {"r": r4, "e": w4.cursor["_leaf_later"].get(lk)})


w5 = evm_watch.RpcChainWatcher(CFG, CH, list(W), Wr())
w5.cursor["_leaf_later"] = {"x": {"w": W[0], "blk": 5, "at": 1, "n": 0, "next": 0}}
w5.cursor.update({x: C0 for x in W})
calls5 = []
w5._head = lambda: TGT + 10
w5._init = lambda safe: None
w5._leaf_later_step = lambda head: calls5.append(head) or 0


def adv_boom(*a, **k):
    raise RuntimeError("나중에 다시 잎 블록 큐 포화 — 커서 유지")


w5._advance = adv_boom
w5._health_cycle = lambda *a, **k: None
r5 = T.safe(w5.cycle)
T.chk(isinstance(r5, dict) and calls5 == [TGT + 10], "F5 전진이 예외로 끝나는 사이클에도 '나중에 다시' 회수가 먼저 돈다(종전: 전진 뒤에만 — 포화면 영영 안 비움)",
      {"r": r5, "calls": calls5})

w6 = evm_watch.RpcChainWatcher(CFG, CH, list(W), Wr())
w6.trace_rpcs = ["http://127.0.0.1:9/trace"]
q6 = {f"{W[1][:12]}:{100 + i}": {"w": W[1], "blk": 100 + i, "at": 1, "n": 1, "next": 2_000_000_000} for i in range(450)}
w6.cursor["_leaf_later"] = dict(q6)
ovl6 = [{"k": f"{W[0][:12]}:{7000 + i}", "w": W[0], "blk": 7000 + i, "at": 5} for i in range(20)] + [{"k": f"{W[1][:12]}:100", "w": W[1], "blk": 100, "at": 5}]
with open(OVF, "w", encoding="utf-8") as f9:
    f9.write("".join(json.dumps(x) + "\n" for x in ovl6))
w6.cursor["_leaf_overflow"] = len(ovl6)
traced6 = []


def tb6(y):
    traced6.append(int(y))
    return {}, []


w6._trace_block = tb6
n6 = T.safe(w6._leaf_later_step, 10 ** 8)
ll6 = w6.cursor.get("_leaf_later") or {}
left6 = open(OVF, encoding="utf-8").read().strip() if os.path.exists(OVF) else ""
T.chk(not isinstance(n6, dict) and all(f"{W[0][:12]}:{7000 + i}" in ll6 or (7000 + i) in traced6 for i in range(20)) and not left6
      and not w6.cursor.get("_leaf_overflow"), "F6 자리가 나면 넘침 파일에서 큐로 다시 채움(중복 1건 제외) · 파일 비움 · 수 0",
      {"n": n6, "q": len(ll6), "left": left6[:80], "cnt": w6.cursor.get("_leaf_overflow")})
T.chk(traced6 and all(y >= 7000 for y in traced6), "F6 다시 채운 잎도 같은 백오프 재시도 대상(바로 처리 시작)", traced6)
T.chk(all(k in ll6 for k in q6), "F6 기존 큐 항목 그대로", sum(1 for k in q6 if k in ll6))

w7 = evm_watch.RpcChainWatcher(CFG, CH, list(W), Wr())
w7.cursor["_leaf_later"] = {f"{W[1][:12]}:100": {"w": W[1], "blk": 100, "at": 1, "n": 1, "next": 2}}
with open(OVF, "w", encoding="utf-8") as f9:
    f9.write(json.dumps({"k": f"{W[0][:12]}:7777", "w": W[0], "blk": 7777, "at": 5}) + "\n")
w7.cursor["_leaf_overflow"] = 1
r7 = T.safe(evm_watch.rpc_handback, w7, "blockscout")
d7 = common.read_json(CPATH, {})
left7 = d7.get("_leaf_later_left") or {}
T.chk(not isinstance(r7, dict) and any(int(v.get("blk") or 0) == 7777 for v in left7.values())
      and any(r.get("kind") == "leaf" and r.get("to_block") == 7777 for r in ((d7.get("_ext_internal_pending") or {}).get("ranges") or []))
      and not (open(OVF, encoding="utf-8").read().strip() if os.path.exists(OVF) else ""),
      "F7 되돌림 = 넘침 잎도 블록스카웃 재훑기·보관(_leaf_later_left)으로 · 넘침 파일 비움", {"r": r7, "left": sorted(left7)})

CB = "zbs"
CFG["chains"][CB] = {"discovery": "explorer", "chain_id": 16662, "rpcs": ["http://127.0.0.1:9/rpc"], "blockscout": "http://127.0.0.1:9/bs",
                     "etherscan_chainid": 16662, "conf_depth": 10, "blocks_per_day": 43200, "poll_sec": 60, "cycle_budget_sec": 15}
CPB = os.path.join(common.STATE_DIR, f"cursor_evm_{CB}.json")
OVB = os.path.join(common.STATE_DIR, f"leaf_later_overflow_{CB}.jsonl")
HTL9 = "0x" + "7a" * 32
for tgt9 in ("blockscout", "etherscan"):
    for p9 in (OVB, os.path.join(common.STATE_DIR, f"enrich_{CB}.json"), os.path.join(common.STATE_DIR, f"hq_left_{CB}.json"),
               os.path.join(common.STATE_DIR, f"trace_later_left_{CB}.json")):
        if os.path.exists(p9):
            os.remove(p9)
    common.atomic_write_json(CPB, {"_rpc_v": 1, "_start": 1000, W[0]: 900_000, W[1]: 900_000,
                                   "_leaf_later": {f"{W[0][:12]}:6000": {"w": W[0], "blk": 6000, "at": 1, "n": 1, "next": 2}},
                                   "_trace_later": {HTL9: {"at": 1, "n": 1, "next": 2, "blk": 6100, "sent": True}}, "_leaf_overflow": 1})
    common.atomic_write_json(os.path.join(common.STATE_DIR, f"emitted_evm_{CB}.json"), [])
    common.append_durable_jsonl(OVB, {"k": f"{W[1][:12]}:7777", "w": W[1], "blk": 7777, "at": 5})
    wt9 = evm_watch.RpcChainWatcher(CFG, CB, list(W), Wr())
    wt9.fb_info = {"src": tgt9, "why": "시험"}
    if tgt9 == "blockscout":
        mk9 = lambda c9, ch9, ad9: evm_watch.ChainWatcher(c9, ch9, ad9, Wr())
    else:
        mk9 = lambda c9, ch9, ad9: evm_watch.EtherscanWatcher(c9, ch9, ad9, Wr(), 16662, "TESTKEY0123")
    nw9 = T.safe(evm_watch.rpcfb_try_return, CFG, wt9, mk9, "TESTKEY0123")
    d9 = common.read_json(CPB, {})
    left9 = d9.get("_leaf_later_left") or {}
    rng9 = (d9.get("_ext_internal_pending") or {}).get("ranges") or []
    T.chk(not isinstance(nw9, dict) and type(nw9).__name__ == ("ChainWatcher" if tgt9 == "blockscout" else "EtherscanWatcher"),
          f"F9 {tgt9}: 실제 복귀 경로(rpcfb_try_return → 탐색기 생성자) 로 돌아감", {"nw": nw9 if isinstance(nw9, dict) else type(nw9).__name__})
    T.chk(any(int(v.get("blk") or 0) == 7777 for v in left9.values()) and any(int(v.get("blk") or 0) == 6000 for v in left9.values())
          and not os.path.exists(OVB),
          f"F9 {tgt9}: 넘침 잎(7777)·큐 잎(6000) 둘 다 _leaf_later_left 로 · 넘침 파일 비움(종전: 넘침 건너뜀 — 탐색기 생성자엔 넘침 읽기 없음)",
          {"left": sorted(int(v.get("blk") or 0) for v in left9.values()), "ovf": os.path.exists(OVB)})
    if tgt9 == "blockscout":
        T.chk(any(r.get("kind") == "leaf" and r.get("to_block") == 7777 for r in rng9), "F9 blockscout: 넘침 잎 = 그 지갑 internal 재훑기 구간(leaf)",
              [(r.get("kind"), r.get("to_block")) for r in rng9])
        T.chk(HTL9 in (common.read_json(os.path.join(common.STATE_DIR, f"enrich_{CB}.json"), {}) or {}), "F9 blockscout: 늦은 채움(_trace_later) = enrich 로(같은 경로)")
    else:
        T.chk(W[1] not in d9 and W[0] not in d9, "F9 etherscan: 넘침 잎 지갑도 첫 백필(커서 지움 — 목록 3종이 internal 까지 완전)", sorted(k[:6] for k in d9 if not k.startswith("_")))
        T.chk(HTL9 in (common.read_json(os.path.join(common.STATE_DIR, f"hq_left_{CB}.json"), {}) or {}), "F9 etherscan: 늦은 채움(_trace_later) = hq_left 보관(같은 경로)")
    T.chk(HTL9 in (common.read_json(os.path.join(common.STATE_DIR, f"trace_later_left_{CB}.json"), {}) or {}),
          f"F9 {tgt9}: 늦은 채움 원본 표식 보관(trace_later_left — 다시 RPC 면 되살림)")

import health

tx8 = getattr(health, "leaf_overflow_text", None)
T.chk(tx8 is not None and tx8({}) is None and "3" in (tx8({"_leaf_overflow": 3}) or "")
      and "경고" in (tx8({"_leaf_overflow": evm_watch.RpcChainWatcher.LEAF_OVERFLOW_WARN}) or ""),
      "F8 헬스: 넘침 대기 n블록 사실 한 줄 · 큰 상한 넘으면 경고 문구", [tx8({"_leaf_overflow": 3}) if tx8 else None])

T.finish()
sys.exit(1 if T.FAILS else 0)
