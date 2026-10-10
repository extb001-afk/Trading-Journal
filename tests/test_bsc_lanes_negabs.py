#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _ingest
from _ingest import W, Reader

import json
import os
import threading
import time

CFG = json.load(open(os.path.join(T.TMP, "config.json"), encoding="utf-8"))
CFG["wallets"].append({"type": "bsc_rpc", "chain": "bsc", "address": W})
CFG["bsc"] = {"detail_rpcs": ["https://bscrpc.invalid"], "logs_rpcs": []}
CFG.setdefault("native_symbol", {})["bsc"] = "BNB"
json.dump(CFG, open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8"))

import common
import core
import discopen

chk = T.chk
core.dm = lambda *a, **k: None
E18 = 10 ** 18
DAY = 86400
NOW = int(time.time())
X = "0x" + "b7" * 20
TKB, TKC, TKD, TKE = ("0x" + c * 20 for c in ("c1", "c2", "c3", "c4"))
T0 = NOW - 20 * DAY
CPATH = os.path.join(common.STATE_DIR, "cursor_bsc.json")


def h(n):
    return "0x" + ("%064x" % n)


def snap(hx, ts, blk, frm, to, toks=(), fee=0):
    return {"tx": {"hash": hx, "from": frm, "to": to, "value": "0", "fee": {"value": str(fee)}, "status": "ok", "raw_input": "0xa9059cbb",
                   "timestamp": ts, "block_number": blk, "block_hash": "0x" + "d" * 64},
            "token_transfers": [{"from": f, "to": t, "token": {"address": ca, "symbol": sym, "decimals": 18, "type": "ERC-20"},
                                 "total": {"value": str(v)}} for f, t, ca, sym, v in toks],
            "internal": []}


def feed(c, hx, s):
    c._drain_stream("bsc", Reader([{"v": 1, "kind": "evm_tx", "chain": "bsc", "txhash": hx, "wallets": [W], "snapshot": s, "ts": 1}]), 0, 0)
    c.conn.commit()


def aid_of(c, ca):
    r = c.conn.execute("SELECT asset_id FROM assets WHERE chain='bsc' AND address=?", (ca,)).fetchone()
    return r[0] if r else None


def total(c, ca):
    a = aid_of(c, ca)
    return sum(int(r[0]) for r in c.conn.execute("SELECT qty_base FROM postings WHERE location=? AND asset_id=?", (f"wallet:bsc:{W}", a))) if a else 0


def anchors(c, ca):
    a = aid_of(c, ca)
    return [tuple(r) for r in c.conn.execute("SELECT source_id, qty_base FROM postings WHERE source_kind='opening' AND source_id LIKE 'recon:bsc:%:disc:%'"
                                             " AND asset_id=?", (a,))] if a else []


def cand(c, ca):
    return discopen._jload(discopen._meta(c.conn, discopen.cand_key("bsc", W, aid_of(c, ca))), None) or {}


def rearm(c, ca):
    d = cand(c, ca)
    d["next"] = 0
    c._negabs_runner()._put(discopen.cand_key("bsc", W, aid_of(c, ca)), d)
    c.conn.commit()


CALLS = []
FAKE = {}
GATE = {}


def fake_fetch(urls, w, ca, blk, tries=2):
    CALLS.append((ca, int(blk)))
    ev = GATE.get(ca)
    if ev is not None:
        ev.wait(10)
    v = FAKE.get((ca, int(blk)))
    if isinstance(v, BaseException):
        raise v
    if v is None:
        raise RuntimeError("rpc eth_call: 시험 목 없음")
    return v


discopen.fetch_at = fake_fetch


def pump(c, n=60):
    for _ in range(n):
        r = c._negabs_runner()
        r.last = 0.0
        c.negabs_pass()
        if not r.jobs:
            return
        time.sleep(0.02)


def cursor(fb, live=None, synced=True):
    cur = {"from_block": fb, "head": 3000, "_cov": 100, "_bf_start": 100, "_wallets": [W]}
    if synced:
        cur["_synced_at"] = NOW + 3600
    if live:
        cur["_live"] = live
    common.atomic_write_json(CPATH, cur)


c = core.Core(common.load_config())
c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('recon_done_bsc', ?)", (str(T0),))
c.conn.execute("INSERT OR REPLACE INTO raw_observations (obs_id, kind, venue, payload, observed_at) VALUES (?,?,?,?,?)",
               ("recon:bsc", "opening_balance", "bsc", json.dumps({W: {"native:None": 0}}), T0))
c.conn.commit()
chk("bsc" in c._negabs_runner()._chains(), "전제: BSC 지갑 = 발견 시점 처리 대상 체인")

print("[D1] 차선 중 — 빈 구간 입금이 아직 안 옴")
LIVE = {"done": 2980, "holes": [[1500, 2400]], "why": "lag", "start": 1500, "fb": 1500}
cursor(1500, LIVE)
T1 = T0 + 5 * DAY
FAKE[(TKB, 2499)] = (10 * E18, T1 - 12)
feed(c, h(11), snap(h(11), T1, 2500, W, TKB, toks=[(W, X, TKB, "TKB", 10 * E18)], fee=10 ** 15))
chk(total(c, TKB) == -10 * E18 and cand(c, TKB).get("st") == "new", "D1 전제: 라이브 유출 먼저 → 원장 −10 · 후보", cand(c, TKB))
pump(c)
chk(not anchors(c, TKB), "D1 차선 중 = 발견 시점 앵커 안 씀(빈 구간 입금을 옛 보유로 흡수하지 않음)", anchors(c, TKB))
chk(cand(c, TKB).get("st") in ("wait", "retry") and "차선" in str(cand(c, TKB).get("why")), "D1 후보 = 대기 · 사유 '차선'", cand(c, TKB))
feed(c, h(10), snap(h(10), T1 - 3600, 2000, X, W, toks=[(X, W, TKB, "TKB", 10 * E18)]))
chk(total(c, TKB) == 0, "D1 옆 차선 입금 뒤 원장 0 = 실잔고 0(이중 계상 없음)", total(c, TKB))
cursor(2990)
rearm(c, TKB)
pump(c)
chk(not anchors(c, TKB) and cand(c, TKB).get("st") in ("gone", "wait", "retry", "new", None), "D1 차선 끝 뒤에도 앵커 없음(음수 아님)", cand(c, TKB))

print("[D2] 차선 끝 — 진짜 옛 보유 누락은 종전대로")
T2 = T1 + DAY
FAKE[(TKC, 2599)] = (5 * E18, T2 - 12)
feed(c, h(21), snap(h(21), T2, 2600, W, TKC, toks=[(W, X, TKC, "TKC", 5 * E18)], fee=10 ** 15))
pump(c)
an2 = anchors(c, TKC)
chk(len(an2) == 1 and int(an2[0][1]) == 5 * E18 and total(c, TKC) == 0, "D2 차선 없음 · from_block ≥ 그 블록 = 앵커 +5(종전과 같음)", (an2, total(c, TKC)))

print("[D3] 조회 시작 뒤 차선이 열림")
T3 = T2 + DAY
FAKE[(TKD, 2699)] = (7 * E18, T3 - 12)
GATE[TKD] = threading.Event()
feed(c, h(31), snap(h(31), T3, 2700, W, TKD, toks=[(W, X, TKD, "TKD", 7 * E18)], fee=10 ** 15))
r = c._negabs_runner()
r.last = 0.0
c.negabs_pass()
chk(any(j["ch"] == "bsc" for j in r.jobs.values()), "D3 전제: 조회 진행 중", list(r.jobs))
cursor(2600, {"done": 2980, "holes": [[2600, 2650]], "why": "lag", "start": 2600, "fb": 2600})
GATE[TKD].set()
time.sleep(0.1)
pump(c)
chk(not anchors(c, TKD) and "차선" in str(cand(c, TKD).get("why")), "D3 수확 때 차선 확인 → 앵커 안 씀 · 다시 대기", cand(c, TKD))
cursor(2990)
rearm(c, TKD)
pump(c)
chk(len(anchors(c, TKD)) == 1 and total(c, TKD) == 0, "D3 차선 끝 → 다시 조회해 앵커 +7", (anchors(c, TKD), cand(c, TKD)))

print("[D4] 빈틈없이 받은 끝(from_block)이 그 블록 앞")
T4 = T3 + DAY
FAKE[(TKE, 2799)] = (3 * E18, T4 - 12)
cursor(2700)
feed(c, h(41), snap(h(41), T4, 2800, W, TKE, toks=[(W, X, TKE, "TKE", 3 * E18)], fee=10 ** 15))
pump(c)
chk(not anchors(c, TKE) and cand(c, TKE).get("st") in ("wait", "retry"), "D4 from_block(2700) < 그 블록(2800) = 대기", cand(c, TKE))
cursor(2990)
rearm(c, TKE)
pump(c)
chk(len(anchors(c, TKE)) == 1, "D4 따라잡은 뒤 = 앵커", anchors(c, TKE))

print("[D5] 차선 중 · 빈 구간이 전부 그 블록 뒤")
TKF = "0x" + "c5" * 20
T5 = T4 + DAY
FAKE[(TKF, 2749)] = (7 * E18, T5 - 12)
cursor(2990, {"done": 3500, "holes": [[2990, 3200]], "why": "lag", "start": 2990, "fb": 2990}, synced=False)
feed(c, h(51), snap(h(51), T5, 2750, W, TKF, toks=[(W, X, TKF, "TKF", 7 * E18)], fee=10 ** 15))
pump(c)
an5 = anchors(c, TKF)
chk(len(an5) == 1 and int(an5[0][1]) == 7 * E18 and total(c, TKF) == 0, "D5 그 블록 아래는 다 받음(from_block 2990 ≥ 2749) = 앵커 +7(차선 중이어도 보류 안 함)",
    (an5, cand(c, TKF)))

LV = {"done": 3500, "holes": [[2749, 3200]], "why": "lag", "start": 2749, "fb": 2749}
cursor(2749, LV)
r5a = c._negabs_runner()._lane_hold("bsc", 2749)
cursor(2748, dict(LV, holes=[[2748, 3200]], fb=2748))
r5b = c._negabs_runner()._lane_hold("bsc", 2749)
chk(r5a is None and r5b and "차선" in r5b and c._negabs_runner()._lane_hold("base", 1) is None,
    "D5 경계 — from_block = 읽는 블록이면 통과 · 한 블록 모자라면 대기(사유 '차선') · BSC 밖 체인은 이 판정 없음", (r5a, r5b))

T.finish()
