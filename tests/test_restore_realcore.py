#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _ingest
from _ingest import check, W

import json
import os
import sqlite3
import time as _rt

import common
sys.path.insert(0, os.path.join(T.ROOT, "tools"))
cfg9 = json.load(open(common.CONFIG_PATH, encoding="utf-8"))
cfg9["chains"]["arbitrum"] = {"blockscout": "https://bs3.invalid", "conf_depth": 12, "blocks_per_day": 345600, "rpcs": ["https://rpc3.invalid"]}
cfg9["wallets"].append({"type": "evm", "chain": "arbitrum", "address": W})
json.dump(cfg9, open(common.CONFIG_PATH, "w", encoding="utf-8"))

import core
import inbox
import ledger_backup as lb
import ledger_restore as LR
core.dm = lambda *a, **k: None


class _Clock:
    t = None

    def __getattr__(self, k):
        return getattr(_rt, k)

    def time(self):
        return self.t if self.t is not None else _rt.time()


CLK = _Clock()
core.time = CLK
S = common.STATE_DIR
NOW = int(_rt.time())
T_BK = NOW - 3 * 86400
B, R, TK = "0x" + "b2" * 20, "0x" + "c3" * 20, "0x" + "a" * 40


def rec(i, blk, ts):
    h = "0x%064x" % (0xA000 + i)
    tx = {"hash": h, "from": B, "to": R, "value": "0", "fee": {"value": "0"}, "status": "ok", "raw_input": "0x01",
          "timestamp": ts, "block_number": blk, "block_hash": "0x" + "d" * 64}
    snap = {"tx": tx, "internal": [],
            "token_transfers": [{"from": B, "to": W, "token": {"address": TK, "symbol": "T", "decimals": 6, "type": "ERC-20"},
                                 "total": {"value": "1000000"}}]}
    return h, {"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": h, "wallets": [W], "snapshot": snap, "ts": ts}


wr = inbox.SegmentWriter(os.path.join(common.INBOX_DIR, "evm"))
c = core.Core(common.load_config())
c.conn.commit()
hashes = []


def ingest(i, blk, at):
    h, r9 = rec(i, blk, at - 600)
    wr.append(r9)
    hashes.append(h)
    row = c.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream='evm'").fetchone()
    CLK.t = at
    try:
        c._drain_stream("evm", c.reader, *(tuple(row) if row else (1, 0)))
    finally:
        CLK.t = None


ingest(1, 1000, T_BK - 30 * 3600)
ingest(2, 1100, T_BK - 14 * 3600)
ingest(3, 1200, T_BK - 2 * 3600)
ingest(4, 1250, T_BK)
c.conn.commit()
st9 = lb.run_once(db_path=common.DB_PATH, now=T_BK)
BK = st9.get("last_path")
check("(전제) 정기 백업 생성(ledger_backup.run_once — 실제 경로)", BK and os.path.exists(BK), st9)
ingest(5, 1300, T_BK + 86400)
ingest(6, 1400, NOW - 3600)
c.conn.close()
wr.close()

b9 = sqlite3.connect(common.sqlite_ro_uri(BK, immutable=True), uri=True)
eth9 = b9.execute("SELECT count(*), sum(ts IS NULL), max(block) FROM raw_txs WHERE chain='eth'").fetchone()
ing9 = b9.execute("SELECT max(ingested_at) FROM raw_txs").fetchone()[0]
b9.close()
check("[1] 실제 Core 가 기장한 eth 줄 = ts 비어 있음(4줄 모두 NULL)", eth9 == (4, 4, 1250), eth9)
check("[1] 백업 데이터 시각 = 마지막으로 들어온 시각", ing9 == T_BK, (ing9, T_BK))

ibd = os.path.join(common.INBOX_DIR, "evm")
for n in os.listdir(ibd):
    if n.endswith(".jsonl"):
        os.remove(os.path.join(ibd, n))
with open(os.path.join(ibd, f"{9:09d}.jsonl"), "w", encoding="utf-8") as f:
    f.write(json.dumps({"kind": "x"}) + "\n")

OLD_ARB = 9_000_000


def wj(name, obj):
    common.atomic_write_json(os.path.join(S, name), obj)


wj("cursor_evm_eth.json", {"_rpc_v": 3, "_start": 900, W: 5000, "_ns": {W: {"n": 1}}, "_cov:" + W: 900, "_synced_at": NOW})
wj("cursor_rpc_eth.json", {"from_block": 5000, "rpc_synced_at": NOW})
wj("cursor_evm_base.json", {W: 900000, "_cov:" + W: 100, "_synced_at": NOW})
wj("cursor_evm_arbitrum.json", {"_rpc_v": 3, W: OLD_ARB, "_cov:" + W: 100, "_synced_at": NOW})
wj("cursor_rpc_arbitrum.json", {"from_block": OLD_ARB})
wj("emitted_evm_eth.json", [h.lower() for h in hashes])

p = LR.plan(BK, now=NOW)
check("[2] 기준 시각 = 백업 데이터 시각 · 인박스 앞부분 지워짐 = evm 되감기", p["T"] == T_BK and "evm" in p["rewind"], (p["T"], p["rewind"]))
rec9 = LR.apply(p, proc_check=False, log=lambda *a: None)


def rj(name):
    with open(os.path.join(S, name), encoding="utf-8") as f:
        return json.load(f)


ce = rj("cursor_evm_eth.json")
check("[2] RPC 트랙 eth 지갑 커서 ≤ 여유 이전에 들어온 마지막 블록(1100) — ts 없는 실제 원장에서도", isinstance(ce.get(W), int) and ce[W] <= 1100, ce.get(W))
check("[2] RPC 트랙 상태 기준점(_ns) 지움(아카이브 없이 못 맞춤 — 첫 구간 정합만 건너뜀)", W not in (ce.get("_ns") or {}), ce.get("_ns"))
cr = rj("cursor_rpc_eth.json")
check("[2] 이중화 트랙 cursor_rpc_eth from_block ≤ 1100", cr.get("from_block", 10 ** 9) <= 1100, cr)
check("[2] 방출 기록 = 백업에 있는 4건만(백업 뒤 2건은 다시 보냄)", rj("emitted_evm_eth.json") == [h.lower() for h in hashes[:4]], rj("emitted_evm_eth.json"))

cut = p["cut"]
need_back = int((NOW - cut) * 345600 / 86400)
ca = rj("cursor_evm_arbitrum.json")
check("[3] 기준 없는 RPC 트랙 체인 = 시간으로 되감음(≥ (지금 − 기준 시각)/블록 시간) · 창 하한 위",
      isinstance(ca.get(W), int) and 100 <= ca[W] <= OLD_ARB - need_back, (ca.get(W), OLD_ARB - need_back))
cra = rj("cursor_rpc_arbitrum.json")
check("[3] 기준 없는 이중화 트랙 from_block 도 시간으로 되감음", cra.get("from_block", 10 ** 12) <= OLD_ARB - need_back, cra)
notes = rec9.get("notes") or []
check("[3] 시간으로 되감은 것은 ★ 안내(근사임을 알림)", any(n.startswith("★") and "cursor_evm_arbitrum" in n for n in notes)
      and any(n.startswith("★") and "cursor_rpc_arbitrum" in n for n in notes), notes)
cb = rj("cursor_evm_base.json")
check("[3] 기준 없는 탐색기 트랙 = 창 처음(_cov)부터 다시 훑음", cb.get(W) == 100, cb)
check("[4] 커서 파일마다 안내 한 줄 이상(조용한 분기 없음)",
      all(any(n9 in x for x in notes) for n9 in ("cursor_evm_eth", "cursor_rpc_eth", "cursor_evm_base", "cursor_evm_arbitrum", "cursor_rpc_arbitrum")), notes)
check("[4] 저장소에 없는 도구(backfill_gap.py)를 안내하지 않음", not any("backfill_gap" in x for x in notes)
      and "backfill_gap" not in (LR.__doc__ or "") + LR.EPILOG, [x for x in notes if "backfill_gap" in x])

pend6 = rj("pending_detail_eth.json") if os.path.exists(os.path.join(S, "pending_detail_eth.json")) else {}
check("[6] RPC 트랙 = 백업 뒤 방출한 2건이 해시 재수집 큐에", sorted(pend6) == sorted(h.lower() for h in hashes[4:]), pend6)
check("[6] 탐색기 트랙(base)은 창 처음부터 다시 훑으므로 큐 없음", not os.path.exists(os.path.join(S, "pending_detail_base.json")))
import evm_watch
rw = evm_watch.RpcChainWatcher.__new__(evm_watch.RpcChainWatcher)
rw.chain, rw.cursor, rw.lanes_cfg = "eth", {}, None
rw.emitted = set(rj("emitted_evm_eth.json"))
rw.emitted_path = os.path.join(S, "emitted_evm_eth.json")
rw.cursor_path = os.path.join(S, "cursor_evm_eth.json")
LOGLESS = {"tx": {"hash": hashes[5], "from": W, "to": R, "value": "5000000000000000", "fee": {"value": "0"}, "status": "ok", "raw_input": "0x",
                  "timestamp": NOW - 4000, "block_number": 1400, "block_hash": "0x" + "d" * 64}, "token_transfers": [], "internal": []}
got6 = []
rw._details = lambda hs, deadline=None, trace=True: {h: (LOGLESS if h == hashes[5].lower() else rec(5, 1300, T_BK + 86400)[1]["snapshot"]) for h in hs}
rw._emit = lambda h, s9, head: (got6.append((h, s9["tx"]["value"])), rw.emitted.add(h))
evm_watch.RpcChainWatcher._legacy_queues(rw)
check("[6] 수집기(RpcChainWatcher._legacy_queues)가 큐의 해시를 다시 받아 보냄 — 로그 없는 네이티브 송금 포함 · 큐 비움",
      sorted(h for h, _v in got6) == sorted(h.lower() for h in hashes[4:]) and ("%s" % hashes[5].lower(), "5000000000000000") in got6
      and rj("pending_detail_eth.json") == {}, (got6, rj("pending_detail_eth.json")))
evm_watch.RpcChainWatcher._legacy_queues(rw)
check("[6] 두 번째 사이클 = 다시 안 보냄(방출 기록)", len(got6) == 2, got6)

import json as _js
S7 = os.path.join(T.TMP, "st7")
os.makedirs(S7)
CTR = "0x" + "c7" * 20
H_INT = hashes[4].lower()
cur7 = {"_rpc_v": 3, "_start": 900, W: 5000, "_ns": {W: [5000, 1, "0", 0, "0"]}, "_handover": {"from": "explorer", "at": NOW - 86400}}
_js.dump(cur7, open(os.path.join(S7, "cursor_evm_eth.json"), "w"))
_js.dump([h.lower() for h in hashes], open(os.path.join(S7, "emitted_evm_eth.json"), "w"))
B7 = {"tx": {"eth": {h.lower() for h in hashes[:4]}}, "anchor": {"eth": 1100}, "wallets": {"eth": {W.lower()}}, "sol_anchor": {}, "ex": {}, "bsc_max": None}
n7 = []
f7 = LR.plan_evm(S7, B7, n7, cut=T_BK - 12 * 3600, now=NOW, cfg={"chains": {"eth": {"blocks_per_day": 7200}}})
for k9, v9 in f7.items():
    _js.dump(v9, open(os.path.join(S if k9.startswith("pending_detail_") else S7, k9), "w"))
rw7 = evm_watch.RpcChainWatcher.__new__(evm_watch.RpcChainWatcher)
rw7.chain, rw7.wallets, rw7.lanes_cfg, rw7.trace_mode = "eth", [W.lower()], None, None
rw7.cursor = _js.load(open(os.path.join(S7, "cursor_evm_eth.json")))
rw7.cursor_path, rw7.emitted_path = os.path.join(S7, "cursor_evm_eth.json"), os.path.join(S7, "emitted_evm_eth.json")
rw7.emitted = set(_js.load(open(rw7.emitted_path)))
rw7.detail_batch, rw7.trace_rpcs, rw7._trace_fail, rw7._txmeta, rw7.rpc_meta = 10, ["https://trace.invalid"], {}, {}, {}
rw7._batch = lambda calls: [None] * len(calls)
rw7._rpc_call = lambda m, p: {"nonce": "0x5", "from": B, "to": CTR}
rw7._nodec_reg = lambda: type("N", (), {"perm": staticmethod(lambda ca: False)})()
rw7._fill_symbols = lambda snaps: None


def synth7(h):
    return {"tx": {"hash": h, "from": B, "to": CTR, "value": "0", "fee": {"value": "0"}, "status": "ok", "raw_input": "0x12345678",
                   "timestamp": NOW - 5000, "block_number": 1300, "block_hash": "0x" + "d" * 64}, "token_transfers": [], "internal": []}


def trace7(h, snap):
    snap["internal"] = [{"from": CTR, "to": W.lower(), "value": "3000000000000000000", "success": True}] if h == H_INT else []
    snap["internal_note"] = "trace"


rw7._rpc_synth_detail, rw7._trace_internal = synth7, trace7
em7 = {}


def emit7(h, snap, head):
    em7[h] = list(snap.get("internal") or [])
    rw7.emitted.add(h)
    if isinstance(rw7.cursor.get("_hq"), dict) and snap.get("internal_note") == "trace":
        rw7.cursor["_hq"].pop(h, None)


rw7._emit = emit7
check("[7] (전제) 차선 모드 = 기본 trace '내 지갑이 보낸 것만'(외부 발신 컨트랙트 호출은 trace 안 함)",
      rw7.bk_mode and not evm_watch.RpcChainWatcher._trace_want(rw7, "0x" + "ab" * 32, synth7("0x" + "ab" * 32)))
check("[7] 차선 모드 RPC 트랙 = 복구 해시가 인계 큐(_hq)에도", sorted((rw7.cursor.get("_hq") or {})) == sorted(h.lower() for h in hashes[4:]), rw7.cursor.get("_hq"))
evm_watch.RpcChainWatcher._legacy_queues(rw7)
check("[7] 외부 → 컨트랙트 → 내 지갑 internal ETH 입금 = trace 되어 internal 과 함께 다시 방출(수정 전 internal=[])",
      em7.get(H_INT) and em7[H_INT][0]["to"] == W.lower() and em7[H_INT][0]["value"] == "3000000000000000000", em7)
check("[7] trace 끝낸 방출 = 인계 큐·재시도 큐에서 빠짐", not (rw7.cursor.get("_hq") or {}) and rj("pending_detail_eth.json") == {},
      (rw7.cursor.get("_hq"), rj("pending_detail_eth.json")))
S8 = os.path.join(T.TMP, "st8")
os.makedirs(S8)
_js.dump(cur7, open(os.path.join(S8, "cursor_evm_eth.json"), "w"))
_js.dump([h.lower() for h in hashes], open(os.path.join(S8, "emitted_evm_eth.json"), "w"))
f8 = LR.plan_evm(S8, B7, [], cut=T_BK - 12 * 3600, now=NOW, cfg={"chains": {"eth": {"blocks_per_day": 7200, "rpc_lanes": False}}})
check("[7] 단일 차선(rpc_lanes false — 기본 trace 전부)은 인계 큐를 늘리지 않음(재시도 큐만)", "_hq" not in (f8.get("cursor_evm_eth.json") or {}) or not f8["cursor_evm_eth.json"].get("_hq"),
      (f8.get("cursor_evm_eth.json") or {}).get("_hq"))
n9 = []
f9 = LR.plan_evm(S8, B7, n9, cut=T_BK - 12 * 3600, now=NOW, cfg={"chains": {"eth": {"blocks_per_day": 7200, "rpc_lanes": False, "rpc_trace": "own"}}})
check("[7] op410 단일 차선 + rpc_trace=own = 인계 큐 안 늘림 · ★ 안내(외부발 internal 입금 · rpc_trace 를 지우거나 all 로)",
      not (f9.get("cursor_evm_eth.json") or {}).get("_hq") and any(x.startswith("★cursor_evm_eth") and "rpc_trace" in x and "internal" in x for x in n9), n9)
f10 = LR.plan_evm(S8, B7, [], cut=T_BK - 12 * 3600, now=NOW, cfg={"chains": {"eth": {"blocks_per_day": 7200, "rpc_trace": "own"}}})
check("[7] op410 인계 차선 + rpc_trace=own 명시 = 인계 큐에 등록(_hq_step 이 도는 구성)",
      sorted((f10.get("cursor_evm_eth.json") or {}).get("_hq") or {}) == sorted(h.lower() for h in hashes[4:]), (f10.get("cursor_evm_eth.json") or {}).get("_hq"))

c2 = core.Core(common.load_config())
wr2 = inbox.SegmentWriter(os.path.join(common.INBOX_DIR, "evm"))
for i, blk, at in ((5, 1300, T_BK + 86400), (6, 1400, NOW - 3600), (3, 1200, T_BK - 2 * 3600)):
    wr2.append(rec(i, blk, at - 600)[1])
row = c2.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream='evm'").fetchone()
seg9, off9 = tuple(row) if row else (1, 0)
for _ in range(5):
    seg9, off9, n9 = c2._drain_stream("evm", c2.reader, seg9, off9)
    if not n9:
        break
n_eth = c2.conn.execute("SELECT count(*) FROM raw_txs WHERE chain='eth'").fetchone()[0]
n_leg = c2.conn.execute("SELECT count(*) FROM postings WHERE source_id IN (%s)" % ",".join("?" * 6), [h.lower() for h in hashes]).fetchone()[0]
c2.conn.close()
wr2.close()
check("[5] 복구 뒤 다시 받은 백업 뒤 거래 2건 + 겹친 1건 = eth 원본 6건(중복 없음)", n_eth == 6, n_eth)
check("[5] 기장 레그도 거래마다 한 번(6건 · 겹친 것 두 번 기장 안 됨)", n_leg == 6, n_leg)
T.finish()
