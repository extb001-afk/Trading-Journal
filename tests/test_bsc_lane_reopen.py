#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _ingest
from _ingest import W, Reader

import json
import os
import time

CFG = json.load(open(os.path.join(T.TMP, "config.json"), encoding="utf-8"))
CFG["wallets"].append({"type": "bsc_rpc", "chain": "bsc", "address": W})
CFG["bsc"] = {"detail_rpcs": ["https://bscrpc.invalid"], "logs_rpcs": []}
CFG.setdefault("native_symbol", {})["bsc"] = "BNB"
json.dump(CFG, open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8"))

import common
import core
import discopen
import bsc_watch

chk = T.chk
core.dm = lambda *a, **k: None
E18 = 10 ** 18
NOW = int(time.time())
T0 = NOW - 20 * 86400
X = "0x" + "b7" * 20
TKR = "0x" + "c9" * 20
CPATH = os.path.join(common.STATE_DIR, "cursor_bsc.json")
FAKE = {}


def fake_fetch(urls, w, ca, blk, tries=2):
    v = FAKE.get((ca, int(blk)))
    if isinstance(v, BaseException):
        raise v
    if v is None:
        raise RuntimeError("rpc eth_call: 시험 목 없음")
    return v


discopen.fetch_at = fake_fetch


def h(n):
    return "0x" + ("%064x" % n)


def lane_watcher(cur):
    common.atomic_write_json(CPATH, cur)
    bw = object.__new__(bsc_watch.BscWatcher)
    bw.cursor_path = CPATH
    bw.cursor = common.read_json(CPATH, {})
    bw.lanes_cfg = None
    return bw


bw = lane_watcher({"from_block": 1500, "head": 3000, "_live": {"done": 2980, "holes": [[1500, 2400]], "fb": 1500}})
r1 = bw._lane_norm()
chk(r1 is True and "_lanes_seen" not in common.read_json(CPATH, {}), "R1 차선 중 = 차선 모드 그대로 · 표식 없음", common.read_json(CPATH, {}))
bw = lane_watcher({"from_block": 2980, "head": 3000, "_live": {"done": 2980, "holes": [[2980, 2980]], "fb": 2980}})
r1b = bw._lane_norm()
cur1 = common.read_json(CPATH, {})
chk(r1b is False and "_live" not in cur1 and type(cur1.get("_lanes_seen")) is int,
    "R1 ★옆 차선 끝(빈 구간 다 받음) = 한 차선으로 합치며 _lanes_seen 표식 남김★", cur1)

c = core.Core(common.load_config())
c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('recon_done_bsc', ?)", (str(T0),))
c.conn.execute("INSERT OR REPLACE INTO raw_observations (obs_id, kind, venue, payload, observed_at) VALUES (?,?,?,?,?)",
               ("recon:bsc", "opening_balance", "bsc", json.dumps({W: {"native:None": 0}}), T0))
c.conn.commit()
T1 = T0 + 5 * 86400
snap = {"tx": {"hash": h(1), "from": W, "to": TKR, "value": "0", "fee": {"value": str(10 ** 15)}, "status": "ok", "raw_input": "0xa9059cbb",
               "timestamp": T1, "block_number": 2000, "block_hash": "0x" + "d" * 64},
        "token_transfers": [{"from": W, "to": X, "token": {"address": TKR, "symbol": "TKR", "decimals": 18, "type": "ERC-20"}, "total": {"value": str(5 * E18)}}],
        "internal": []}
common.atomic_write_json(CPATH, {"from_block": 2980, "head": 3000, "_synced_at": NOW + 3600, "_live": {"done": 2980, "holes": [[1500, 2400]], "fb": 1500}})
c._drain_stream("bsc", Reader([{"v": 1, "kind": "evm_tx", "chain": "bsc", "txhash": h(1), "wallets": [W], "snapshot": snap, "ts": 1}]), 0, 0)
c.conn.commit()
aid = c.conn.execute("SELECT asset_id FROM assets WHERE chain='bsc' AND address=?", (TKR,)).fetchone()[0]
k = discopen.cand_key("bsc", W, aid)
r = c._negabs_runner()
r._put(k, {"st": "fail", "n": discopen.MAX_TRIES, "why": discopen.LANE_FAIL_WHY, "tx": h(1), "at": NOW, "next": 0})
c.conn.commit()
FAKE[(TKR, 1999)] = (12 * E18, T1 - 3)


def pump(n=40):
    for _ in range(n):
        rr = c._negabs_runner()
        rr.last = 0.0
        c.negabs_pass()
        if not rr.jobs:
            return
        time.sleep(0.02)


def cand():
    return discopen._jload(discopen._meta(c.conn, k), None) or {}


def anchors():
    return [tuple(x) for x in c.conn.execute("SELECT source_id, qty_base FROM postings WHERE source_kind='opening' AND source_id LIKE 'recon:bsc:%:disc:%'"
                                             " AND asset_id=?", (aid,))]


pump()
chk(cand().get("st") == "fail" and not anchors(), "R2 차선 중(_live) = 굳은 칸 그대로(다시 안 엶)", cand())
bw = lane_watcher(dict(common.read_json(CPATH, {}), from_block=2980, _live={"done": 2980, "holes": [[2980, 2980]], "fb": 2980}))
bw._lane_norm()
pump()
pump()
chk(cand().get("reopened") and len(anchors()) == 1 and int(anchors()[0][1]) == 12 * E18,
    "R2 ★옆 차선이 끝나면(_lanes_seen) 차선 때문에 굳은 칸을 1회 다시 열어 앵커(직전 블록 실잔고 12)★", (cand(), anchors()))

for fb9, live9, up9 in ((1500, {"done": 2980, "holes": [[1500, 2400]], "fb": 1500}, 1999), (2500, {"done": 2980, "holes": [[2500, 2900]], "fb": 2500}, 1999),
                        (1000, None, 1999), (3000, None, 1999)):
    cur9 = {"from_block": fb9}
    if live9:
        cur9["_live"] = live9
    common.atomic_write_json(CPATH, cur9)
    a9, b9 = r._lane_hold("bsc", up9), discopen.lane_hold("bsc", W, up9)
    chk(bool(a9) == bool(b9) and a9 == b9, f"R3 판정 함수 하나 — from_block {fb9}{' · 차선' if live9 else ''} · 블록 {up9}: Runner._lane_hold = lane_hold", (a9, b9))
chk(r._lane_hold("bsc", 1999) is None and discopen.lane_hold("bsc", W, 1999) is None, "R3 빈틈없이 받은 끝 ≥ 그 블록 = 대기 아님")
T.finish()
