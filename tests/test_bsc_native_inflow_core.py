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
DAY = 86400
NOW = int(time.time())
X = "0x" + "b7" * 20
CTR = "0x" + "c9" * 20
TKB = "0x" + "c1" * 20
T0 = NOW - 20 * DAY
CPATH = os.path.join(common.STATE_DIR, "cursor_bsc.json")


def h(n):
    return "0x" + ("%064x" % n)


def snap(hx, ts, blk, frm, to, value=0, toks=(), fee=0, internal=()):
    s = {"tx": {"hash": hx, "from": frm, "to": to, "value": str(value), "fee": {"value": str(fee)}, "status": "ok",
                "raw_input": "0xa9059cbb" if toks else "0x", "timestamp": ts, "block_number": blk, "block_hash": "0x" + "d" * 64},
         "token_transfers": [{"from": f, "to": t, "token": {"address": ca, "symbol": sym, "decimals": 18, "type": "ERC-20"},
                              "total": {"value": str(v)}} for f, t, ca, sym, v in toks],
         "internal": [dict(r) for r in internal]}
    if internal:
        s["internal_note"] = "balance_delta"
    return s


def feed(c, hx, s, via="balw"):
    c._drain_stream("bsc", Reader([{"v": 1, "kind": "evm_tx", "chain": "bsc", "txhash": hx, "wallets": [W], "snapshot": s, "ts": 1, "via": via}]), 0, 0)
    c.conn.commit()


def bnb(c):
    r = c.conn.execute("SELECT asset_id FROM assets WHERE kind='native' AND chain='bsc'").fetchone()
    return sum(int(x[0]) for x in c.conn.execute("SELECT qty_base FROM postings WHERE location=? AND asset_id=?", (f"wallet:bsc:{W}", r[0]))) if r else 0


def pump(c, n=30):
    for _ in range(n):
        r = c._negabs_runner()
        r.last = 0.0
        c.negabs_pass()
        if not r.jobs:
            return
        time.sleep(0.02)


common.atomic_write_json(CPATH, {"from_block": 2990, "head": 3000, "_cov": 100, "_bf_start": 100, "_wallets": [W], "_synced_at": NOW + 3600})
c = core.Core(common.load_config())
c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('recon_done_bsc', ?)", (str(T0),))
c.conn.execute("INSERT OR REPLACE INTO raw_observations (obs_id, kind, venue, payload, observed_at) VALUES (?,?,?,?,?)",
               ("recon:bsc", "opening_balance", "bsc", json.dumps({W: {"native:None": 0}}), T0))
c.conn.commit()

print("[K1] 직접 입금")
T1 = T0 + 2 * DAY
feed(c, h(1), snap(h(1), T1, 2000, X, W, value=5 * E18))
chk(bnb(c) == 5 * E18, "K1 잔고 감시가 찾은 직접 입금 = BNB +5", bnb(c))
feed(c, h(1), snap(h(1), T1, 2000, X, W, value=5 * E18))
chk(bnb(c) == 5 * E18, "K1 같은 레코드 다시 = 무변", bnb(c))

print("[K2] 내 토큰 받기 tx 에 internal 귀속")
T2 = T1 + DAY
base2 = snap(h(2), T2, 2100, X, CTR, toks=[(CTR, W, TKB, "TKB", 9 * E18)])
feed(c, h(2), base2, via=None)
chk(bnb(c) == 5 * E18, "K2 전제: 토큰 받기 = BNB 무변", bnb(c))
bd2 = {"from": CTR, "to": W, "value": str(2 * E18), "success": True, "attr": "balance_delta"}
feed(c, h(2), dict(base2, internal=[bd2], internal_note="balance_delta"))
chk(bnb(c) == 7 * E18, "K2 귀속 행 다시 방출 = BNB +2 한 번", bnb(c))
feed(c, h(2), dict(base2, internal=[bd2], internal_note="balance_delta"))
feed(c, h(2), base2, via=None)
chk(bnb(c) == 7 * E18, "K2 같은 귀속 다시 · 귀속 없는 원본 다시 = 무변(합집합 — 귀속이 사라지거나 두 번 실리지 않음)", bnb(c))

print("[K3] 내 발신 tx 에 환급 귀속")
T3 = T2 + DAY
fee3 = 21000 * 10 ** 9
base3 = snap(h(3), T3, 2200, W, CTR, value=E18 // 2, fee=fee3)
feed(c, h(3), base3, via="nonce")
chk(bnb(c) == 7 * E18 - E18 // 2 - fee3, "K3 전제: 내 발신 = −0.5 − 가스", bnb(c))
bd3 = {"from": CTR, "to": W, "value": str(E18), "success": True, "attr": "balance_delta"}
feed(c, h(3), dict(base3, internal=[bd3], internal_note="balance_delta"))
chk(bnb(c) == 8 * E18 - E18 // 2 - fee3, "K3 환급 귀속 = +1 한 번(발신·가스 그대로)", bnb(c))
feed(c, h(3), dict(base3, internal=[bd3], internal_note="balance_delta"))
chk(bnb(c) == 8 * E18 - E18 // 2 - fee3, "K3 다시 = 무변", bnb(c))

print("[K3b] 남의 tx(중계자 → 컨트랙트 · 내 토큰 없음)의 internal 귀속")
T3b = T3 + 3600
b3b = bnb(c)
s3b = snap(h(5), T3b, 2300, X, CTR, internal=[{"from": CTR, "to": W, "value": str(3 * E18), "success": True, "attr": "balance_delta"}])
feed(c, h(5), s3b)
chk(bnb(c) == b3b + 3 * E18, "K3b 남의 tx 의 컨트랙트 BNB(내 지갑 레그 = internal 하나) = +3", bnb(c) - b3b)
feed(c, h(5), s3b)
chk(bnb(c) == b3b + 3 * E18, "K3b 다시 = 무변", bnb(c) - b3b)

print("[K4] 단서 없는 internal → 기초 잔고 요청")
T4 = T3 + DAY
led4 = bnb(c)
ok4 = bsc_watch.BscWatcher._balw_disc_req(None, {}, W, 2500, led4 + 4 * E18, T4, 4 * E18, "시험")
q4 = (common.read_json(os.path.join(common.STATE_DIR, discopen.RECHK_REQ_NAME), {}) or {}).get("items") or []
chk(ok4 and len(q4) == 1 and q4[0]["ca"] is None and q4[0]["block"] == 2500, "K4 요청 파일 = 네이티브 한 줄(core 재점검 요청 규약)", q4)
chk(not bsc_watch.BscWatcher._balw_disc_req(None, {}, W, 2500, led4 + 4 * E18, T4, 4 * E18, "시험"), "K4 같은 블록 요청 두 번 안 넣음")
pump(c)
sid4 = discopen.sid_of("bsc", W, None, 2500)
an4 = [tuple(r) for r in c.conn.execute("SELECT source_id, event_ts, qty_base FROM postings WHERE source_kind='opening' AND source_id=?", (sid4,))]
res4 = ((common.read_json(os.path.join(common.STATE_DIR, discopen.RES_NAME), {}) or {}).get("recheck") or {})
chk(len(an4) == 1 and an4[0][1] == T4 and int(an4[0][2]) == 4 * E18 and bnb(c) == led4 + 4 * E18,
    "K4 core = 그 블록 시각에 발견 시점 기초 잔고 +4(원가 미상) · 원장 = 그 블록 잔고", (an4, res4, bnb(c) - led4))
bsc_watch.BscWatcher._balw_disc_req(None, {}, W, 2500, led4 + 4 * E18, T4, 4 * E18, "시험")
pump(c)
chk(bnb(c) == led4 + 4 * E18, "K4 같은 요청 다시 = 무변(같은 관측 한 번)", bnb(c) - led4)

T.finish()
