#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _ingest
from _ingest import check, W, Writer, Reader

import json
import os

import common
import core
assert T.TMP in common.STATE_DIR
core.dm = lambda *a, **k: None
B, R = "0x" + "b2" * 20, "0x" + "c3" * 20
TKA, TKB = "0x" + "a" * 40, "0x" + "b" * 40
TS = 1790000500


def leg(shape, ca, v):
    if shape == "full":
        return {"from": {"hash": B}, "to": {"hash": W}, "token": {"address_hash": ca, "symbol": "T", "decimals": "6", "type": "ERC-20"},
                "total": {"value": str(v), "decimals": "6"}, "log_index": 3 if ca == TKA else 4, "block_number": 500}
    if shape == "bs_list":
        return {"from": {"hash": B}, "to": {"hash": W}, "token": {"address_hash": ca, "symbol": "T", "decimals": "6", "type": "ERC-20"},
                "total": {"value": str(v), "decimals": "6"}, "log_index": 3 if ca == TKA else 4, "block_number": 500, "transaction_hash": "x"}
    return {"from": B, "to": W, "token": {"address": ca, "symbol": "T", "decimals": 6, "type": "ERC-20"}, "total": {"value": str(v)}}


def snap(shape, h, legs, ts=TS):
    tx = {"hash": h, "from": ({"hash": B} if shape == "full" else B), "to": ({"hash": R} if shape == "full" else R), "value": "0",
          "fee": {"value": "0"}, "status": "ok", "raw_input": "0x01", "timestamp": ts, "block_number": 500, "block_hash": "0x" + "d" * 64}
    out = {"tx": tx, "token_transfers": [leg(shape, ca, v) for ca, v in legs], "internal": []}
    if shape == "rpc":
        tx["synth"] = "rpc"
    if shape == "bs_list":
        tx["synth"] = "bs_list"
        out["src"] = "bs_list"
    return out


def toks(c, h):
    return sorted((str(r[0]).lower(), int(r[1])) for r in c.conn.execute(
        "SELECT a.address, p.qty_base FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.source_id=? AND a.kind='token'"
        " AND p.location LIKE 'wallet:eth:%'", (h,)).fetchall())


c = core.Core(common.load_config())
c.conn.commit()
CASES = [
    ("es", [(TKB, 2)], "es", [(TKA, 1)], [(TKA, 1), (TKB, 2)]),
    ("rpc", [(TKB, 2)], "rpc", [(TKA, 1)], [(TKA, 1), (TKB, 2)]),
    ("bs_list", [(TKB, 2)], "bs_list", [(TKA, 1)], [(TKA, 1), (TKB, 2)]),
    ("rpc", [(TKB, 2)], "es", [(TKA, 1)], [(TKA, 1), (TKB, 2)]),
    ("es", [(TKB, 2)], "rpc", [(TKA, 1)], [(TKA, 1), (TKB, 2)]),
    ("bs_list", [(TKB, 2)], "es", [(TKA, 1)], [(TKA, 1), (TKB, 2)]),
    ("es", [(TKB, 2)], "full", [(TKA, 1), (TKB, 2)], [(TKA, 1), (TKB, 2)]),
    ("rpc", [(TKB, 2)], "full", [(TKA, 1), (TKB, 2)], [(TKA, 1), (TKB, 2)]),
    ("full", [(TKA, 1), (TKB, 2)], "es", [(TKA, 1)], [(TKA, 1), (TKB, 2)]),
]
for i, (so, sl, nw, nl, want) in enumerate(CASES):
    h = "0x" + ("%064x" % (0xE100 + i))
    c._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": h, "wallets": [W], "snapshot": snap(so, h, sl), "ts": 1}]), 0, 0)
    fix = {"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": h, "wallets": [W], "snapshot": snap(nw, h, nl), "ts": 2,
           "ts_fix": {"poison_ids": ["p%015d" % i], "src": "block_ts", "block": 500}}
    c._drain_stream("evm", Reader([fix]), 0, 0)
    got = toks(c, h)
    c._drain_stream("evm", Reader([fix]), 0, 0)
    again = toks(c, h)
    check(f"[C] 저장 {so} × 보강 {nw} = {'합집합' if so != 'full' and nw != 'full' else ('승격' if nw == 'full' else '그대로')} · 두 번 = 무변",
          got == want and again == want, (got, again))
c.conn.close()

json.dump({"chains": {}, "wallets": [{"type": "evm", "chain": "bsc", "address": W}], "native_symbol": {"bsc": "BNB"},
           "bsc": {"logs_rpcs": ["https://l.invalid"], "detail_rpcs": ["https://d.invalid"]}}, open(os.path.join(T.TMP, "config.json"), "w"))
import bsc_watch
W2 = "0x" + "e5" * 20
H1, H2 = "0x" + "11" * 32, "0x" + "22" * 32
MODE = {H1: "blocknull", H2: "ok"}


def details(hs, deadline=None):
    out = {}
    for h in hs:
        m = MODE[h]
        if m == "blocknull":
            out[h] = RuntimeError("eth_getBlockByNumber: result null")
        elif m == "txnull":
            out[h] = RuntimeError("eth_getTransactionByHash: result null")
        else:
            out[h] = {"tx": {"hash": h, "from": B, "to": (W if h == H1 else W2), "value": str(10 ** 18), "fee": {"value": "1"}, "status": "ok",
                             "raw_input": "0x", "timestamp": TS, "block_number": 2000, "block_hash": None}, "token_transfers": [], "internal": []}
    return out


def mk(wallets):
    w = bsc_watch.BscWatcher.__new__(bsc_watch.BscWatcher)
    w.wallets = list(wallets)
    w.conf_depth = 20
    w.cursor = {"_cov": 1000, "from_block": 3000}
    w.emitted = set()
    w.emitted_path = os.path.join(common.STATE_DIR, "emitted_bsc.json")
    w.meta_path = os.path.join(common.STATE_DIR, "bsc_token_meta.json")
    w.token_meta = {}
    w.writer = Writer()
    w.fetch_details = details
    w._xin_cands = lambda: [H1, H2]
    return w


now = [1_800_000_000.0]
bsc_watch._now = lambda: now[0]
wb = mk([W])
for _ in range(bsc_watch.XIN_NF_MAX + 3):
    wb._xin_pass(3100)
    now[0] += 3700
st = json.load(open(os.path.join(common.STATE_DIR, "bsc_xin.json")))
check("[X1] 블록 시각 null = nf 아님(retry) · 상한 넘어도 계속 후보", st["tx"][H1]["r"] == "retry", st["tx"][H1])
MODE[H1] = "ok"
wb._xin_pass(3100)
now[0] += 3700
check("[X1] 노드 회복 = 방출", H1 in {r["txhash"] for r in wb.writer.recs})
check("[X2] 전제: 받는 주소가 아직 등록 안 된 지갑 = not_direct", st["tx"][H2]["r"] == "not_direct", st["tx"][H2])
MODE[H2] = "txnull"
st["tx"][H2] = {"r": "retry", "n": 0}
json.dump(st, open(os.path.join(common.STATE_DIR, "bsc_xin.json"), "w"))
for k in range(bsc_watch.XIN_NF_MAX - 1):
    wb._xin_pass(3100)
    now[0] += 3700
MODE[H2] = "blocknull"
wb._xin_pass(3100)
now[0] += 3700
MODE[H2] = "txnull"
wb._xin_pass(3100)
now[0] += 3700
m2 = json.load(open(os.path.join(common.STATE_DIR, "bsc_xin.json")))["tx"][H2]
check("[X1] 연속 부재만 셈(다른 오류 뒤 nf_n=1) · 아직 후보", m2.get("r") == "nf" and m2.get("nf_n") == 1, m2)
MODE[H2] = "ok"
st = json.load(open(os.path.join(common.STATE_DIR, "bsc_xin.json")))
st["tx"][H2] = {"r": "not_direct", "blk": 2000}
json.dump(st, open(os.path.join(common.STATE_DIR, "bsc_xin.json"), "w"))
wb2 = mk([W, W2])
wb2.emitted = {H1}
wb2._xin_pass(3100)
check("[X2] 지갑 새로 등록 = not_direct 다시 조회 → 방출", H2 in {r["txhash"] for r in wb2.writer.recs},
      json.load(open(os.path.join(common.STATE_DIR, "bsc_xin.json")))["tx"].get(H2))
T.finish()
