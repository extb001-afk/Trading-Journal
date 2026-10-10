#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _ingest
from _ingest import W, Reader

import json
import os
import time

import common
import core
import discopen

chk = T.chk
core.dm = lambda *a, **k: None
E18 = 10 ** 18
DAY = 86400
NOW = int(time.time())
X = "0x" + "b7" * 20
TKA, TKB, TKC, TKD = ("0x" + c * 20 for c in ("a1", "a2", "a3", "a4"))
T0 = NOW - 20 * DAY
CP = os.path.join(common.STATE_DIR, "cursor_evm_eth.json")


def h(n):
    return "0x" + ("%064x" % n)


def snap(hx, ts, blk, frm, to, toks=(), fee=10 ** 15):
    return {"tx": {"hash": hx, "from": frm, "to": to, "value": "0", "fee": {"value": str(fee)}, "status": "ok", "raw_input": "0xa9059cbb",
                   "timestamp": ts, "block_number": blk, "block_hash": "0x" + "d" * 64},
            "token_transfers": [{"from": f, "to": t, "token": {"address": ca, "symbol": sym, "decimals": 18, "type": "ERC-20"},
                                 "total": {"value": str(v)}} for f, t, ca, sym, v in toks],
            "internal": []}


def feed(c, hx, s):
    c._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": hx, "wallets": [W], "snapshot": s, "ts": 1}]), 0, 0)
    c.conn.commit()


def aid_of(c, ca):
    r = c.conn.execute("SELECT asset_id FROM assets WHERE chain='eth' AND address=?", (ca,)).fetchone()
    return r[0] if r else None


def anchors(c, ca):
    a = aid_of(c, ca)
    return [tuple(r) for r in c.conn.execute("SELECT source_id, qty_base FROM postings WHERE source_kind='opening' AND source_id LIKE 'recon:%:disc:%'"
                                             " AND asset_id=?", (a,))]


def cand(c, ca):
    return discopen._jload(discopen._meta(c.conn, discopen.cand_key("eth", W, aid_of(c, ca))), None) or {}


CALLS = []
FAKE = {}
HOOK = {}


def fake_fetch(urls, w, ca, blk, tries=2):
    CALLS.append((ca, int(blk)))
    if HOOK.get("during"):
        HOOK.pop("during")()
    v = FAKE.get((ca, int(blk)))
    if isinstance(v, BaseException):
        raise v
    if v is None:
        raise RuntimeError("시험 목 없음")
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


def lanes_cursor(live, job=None, synced=True):
    cur = {"_rpc_v": 1, "_start": 100, W: int(live), "_ns": {W: [int(live), 0, "0", 0, "0"]},
           "_handover": {"from": "fresh", "at": NOW, "live": int(live), "start": 100}}
    if job:
        cur["_bk:" + W] = job
    if synced:
        cur["_synced_at"] = NOW + 3600
    common.atomic_write_json(CP, cur)


def unhold(c, ca):
    d9 = cand(c, ca)
    d9["next"] = 0
    c._negabs_runner()._put(discopen.cand_key("eth", W, aid_of(c, ca)), d9)
    c.conn.commit()


c = core.Core(common.load_config())
c.conn.execute("INSERT INTO meta (k, v) VALUES (?, ?)", (f"wrecon_done:eth:{W}", str(T0)))
c.conn.execute("INSERT INTO raw_observations (obs_id, kind, venue, payload, observed_at) VALUES (?,?,?,?,?)",
               (f"recon:eth:{W}", "opening_balance", "eth", json.dumps({W: {"native:None": 0}, "_source": "rpc", "_block": 900, "_q": []}), T0))
c.conn.commit()

T1 = T0 + 5 * DAY
lanes_cursor(5000, {"from": 100, "to": 4000, "done": 1500, "why": "internal"})
FAKE[(TKA, 1999)] = (1000 * E18, T1 - 12)
feed(c, h(11), snap(h(11), T1, 2000, W, TKA, toks=[(W, X, TKA, "TKA", 600 * E18)]))
pump(c)
chk(not anchors(c, TKA) and (TKA, 1999) not in CALLS and cand(c, TKA).get("st") == "wait" and "뒤 차선" in cand(c, TKA).get("why", ""),
    "H1 ★그 지갑 뒤 차선이 나간 거래 블록 아래를 덜 받음(done 1500 < 1999) = 대기 · 조회 0 · 앵커 0★(수정 전 = 대사 완료만 보고 흡수)",
    {"cand": cand(c, TKA), "calls": CALLS, "anchors": anchors(c, TKA)})
lanes_cursor(5000, None)
unhold(c, TKA)
pump(c)
chk(len(anchors(c, TKA)) == 1 and int(anchors(c, TKA)[0][1]) == 1000 * E18, "H2 뒤 차선이 지나가면 = 조회 → 앵커 +1,000(종전 그대로)", anchors(c, TKA))

T3 = T1 + DAY
lanes_cursor(2500, None)
FAKE[(TKB, 2999)] = (50 * E18, T3 - 12)
n3 = len(CALLS)
feed(c, h(31), snap(h(31), T3, 3000, W, TKB, toks=[(W, X, TKB, "TKB", 20 * E18)]))
pump(c)
chk(not anchors(c, TKB) and len(CALLS) == n3 and "라이브 차선" in cand(c, TKB).get("why", ""),
    "H3 라이브 커서(2,500)가 그 블록(2,999) 앞 = 대기 · 조회 0", {"cand": cand(c, TKB), "calls": CALLS[n3:]})
lanes_cursor(5000, None)
unhold(c, TKB)
pump(c)
chk(len(anchors(c, TKB)) == 1, "H3 라이브 차선이 지나가면 = 앵커", anchors(c, TKB))

T4 = T3 + DAY
lanes_cursor(5000, None)
FAKE[(TKC, 3099)] = (70 * E18, T4 - 12)
HOOK["during"] = lambda: lanes_cursor(5000, {"from": 100, "to": 4000, "done": 200, "why": "new"})
feed(c, h(41), snap(h(41), T4, 3100, W, TKC, toks=[(W, X, TKC, "TKC", 10 * E18)]))
pump(c)
chk((TKC, 3099) in CALLS and not anchors(c, TKC) and cand(c, TKC).get("st") == "retry" and "뒤 차선" in cand(c, TKC).get("why", ""),
    "H4 조회를 시작한 뒤 차선이 열림 = 반영 직전에 다시 보고 대기(앵커 0)", {"cand": cand(c, TKC), "anchors": anchors(c, TKC)})
lanes_cursor(5000, None)
unhold(c, TKC)
pump(c)
chk(len(anchors(c, TKC)) == 1, "H4 차선이 끝나면 = 앵커", anchors(c, TKC))

T5 = T4 + DAY
feed(c, h(51), snap(h(51), T5, 3500, X, W, toks=[(X, W, TKD, "TKD", 5 * E18)]))
lanes_cursor(5000, {"from": 100, "to": 4500, "done": 3000, "why": "internal"})
it = {"chain": "eth", "wallet": W, "ca": TKD, "symbol": "TKD", "decimals": 18, "block": 3600, "block_ts": T5 + 60, "chain_bal_raw": str(9 * E18),
      "diff_raw": str(4 * E18), "spam": False, "sources": ["synthetic"]}
r5 = c._negabs_runner()
st5, why5, _s = r5._recheck_one(dict(it), {})
chk(st5 == "wait" and "뒤 차선" in why5 and not anchors(c, TKD),
    "H5 ★재점검 적용 — 동기화 도장이 있어도 그 지갑 뒤 차선이 그 블록 아래를 덜 받음(done 3000 < 3600) = 대기★(수정 전 = 적용)", (st5, why5))
lanes_cursor(5000, None)
st5b, why5b, sid5 = r5._recheck_one(dict(it), {})
chk(st5b == "done" and len(anchors(c, TKD)) == 1 and int(anchors(c, TKD)[0][1]) == 4 * E18, "H5 뒤 차선이 지나가면 = 적용(+4)", (st5b, why5b, anchors(c, TKD)))

T7 = T5 + DAY
TKE = "0x" + "a5" * 20
lanes_cursor(5000, {"from": 100, "to": 4800, "done": 2500, "why": "extend"})
FAKE[(TKE, 1999)] = RuntimeError("rpc eth_call: {'code': -32000, 'message': 'missing trie node abc'}")
FAKE[(TKE, 5000)] = (130 * E18, T7 + 3600)
feed(c, h(71), snap(h(71), T7, 2000, W, TKE, toks=[(W, X, TKE, "TKE", 20 * E18)]))
pump(c)
chk(not anchors(c, TKE) and (TKE, 5000) not in CALLS,
    "H7 ★대체(커서 블록 5,000 잔고)는 그 아래 뒤 차선 미완(done 2,500)이면 안 함 — 앵커 0★(수정 전 = 직전 블록 1,999 만 보고 대체 → 미수집 입금 흡수)",
    {"cand": cand(c, TKE), "anchors": anchors(c, TKE), "calls": [x for x in CALLS if x[0] == TKE]})
lanes_cursor(5000, None)
unhold(c, TKE)
pump(c)
chk(len(anchors(c, TKE)) == 1 and (TKE, 5000) in CALLS, "H7 뒤 차선이 지나가면 = 대체 → 앵커(종전 규칙)", anchors(c, TKE))

T8 = T7 + DAY
TKF = "0x" + "a6" * 20
lanes_cursor(5000, {"from": 100, "to": 4800, "done": 2500, "why": "internal"})
FAKE[(TKF, 2199)] = RuntimeError("rpc eth_call: {'code': -32000, 'message': 'missing trie node abc'}")
FAKE[(TKF, 5000)] = (60 * E18, T8 + 3600)
feed(c, h(81), snap(h(81), T8, 2200, W, TKF, toks=[(W, X, TKF, "TKF", 10 * E18)]))
for _ in range(discopen.MAX_TRIES + 4):
    pump(c)
    unhold(c, TKF)
d8 = cand(c, TKF)
chk(d8.get("st") != "fail" and int(d8.get("n") or 0) == 0 and "뒤 차선" in str(d8.get("why") or "") and not anchors(c, TKF),
    f"H8 ★차선이 {discopen.MAX_TRIES + 4}번 백오프 동안 이어져도 = 차선 대기(n 0 · 'fail' 안 됨)★(수정 전 = 조회 실패로 세어 {discopen.MAX_TRIES}번 뒤 영구 'fail')", d8)
lanes_cursor(5000, None)
unhold(c, TKF)
pump(c)
chk(len(anchors(c, TKF)) == 1 and int(anchors(c, TKF)[0][1]) == 70 * E18, "H8 차선이 끝나면 = 대체(커서 블록 잔고 60 − 그 뒤 원장 −10) → 앵커 70", (cand(c, TKF), anchors(c, TKF)))
TKG = "0x" + "a7" * 20
T9 = T8 + DAY
FAKE[(TKG, 2299)] = RuntimeError("rpc eth_call: {'code': -32000, 'message': 'missing trie node abc'}")
FAKE[(TKG, 5000)] = (15 * E18, T9 + 3600)
lanes_cursor(5000, {"from": 100, "to": 4800, "done": 2500, "why": "internal"})
feed(c, h(91), snap(h(91), T9, 2300, W, TKG, toks=[(W, X, TKG, "TKG", 5 * E18)]))
kg = discopen.cand_key("eth", W, aid_of(c, TKG))
c._negabs_runner()._put(kg, {"st": "fail", "n": discopen.MAX_TRIES, "why": discopen.LANE_FAIL_WHY, "tx": h(91), "at": NOW, "next": 0})
c.conn.commit()
pump(c)
chk(cand(c, TKG).get("st") == "fail" and not anchors(c, TKG), "H8 (옛 'fail' 칸) 차선이 아직이면 그대로", cand(c, TKG))
lanes_cursor(5000, None)
pump(c)
pump(c)
chk(len(anchors(c, TKG)) == 1 and cand(c, TKG).get("reopened"), "H8 ★옛 코드가 차선 때문에 'fail' 로 굳힌 칸 = 차선이 끝나면 1회 다시 열어 앵커★", (cand(c, TKG), anchors(c, TKG)))

common.atomic_write_json(CP, {W: 5000, "_synced_at": NOW + 3600})
chk(discopen.lane_hold("eth", W, 4000) is None, "H6 탐색기 커서(블록스카웃·이더스캔 모양) = 종전 판정(대기 아님)")
lanes_cursor(5000, {"from": 100, "to": 4000, "done": 4000, "why": "internal"})
chk(discopen.lane_hold("eth", W, 3999) is None, "H6 뒤 차선 일이 이미 그 블록을 지남(done = to) = 대기 아님")
lanes_cursor(5000, {"from": 3000, "to": 4000, "done": 3000, "why": "new"})
chk(discopen.lane_hold("eth", W, 2999) is None and discopen.lane_hold("eth", W, 3500),
    "H6 뒤 차선 구간이 그 블록 뒤에서 시작(멈춘 차선 전환 — 그 아래는 이미 받음) = 대기 아님 · 구간 안 = 대기")
common.atomic_write_json(os.path.join(common.STATE_DIR, "cursor_bsc.json"), {"from_block": 6000, "_live": {"done": 9000, "holes": [[6000, 7000]], "fb": 6000}})
chk(discopen.lane_hold("bsc", W, 6500) and discopen.lane_hold("bsc", W, 8000),
    "H6 BSC 옆 차선 빈 구간(6,000→7,000)이 그 블록 아래에서 시작 = 대기")
chk(discopen.lane_hold("bsc", W, 5000) is None, "H6 ★BSC 빈 구간이 그 블록 '뒤'에만 있음 = 대기 아님(진짜 옛 보유 앵커를 영구 보류하지 않음 · 코덱스 bs487 규칙)★")
chk(discopen.lane_hold("bsc", W, 9500), "H6 BSC 라이브 차선 끝(9,000)이 그 블록 앞 = 대기")
common.atomic_write_json(os.path.join(common.STATE_DIR, "cursor_bsc.json"), {"from_block": 9000})
chk(discopen.lane_hold("bsc", W, 9500) and discopen.lane_hold("bsc", W, 8000) is None, "H6 BSC 빈틈없이 받은 끝 앞 = 대기 · 지나감 = 대기 아님")
T.finish()
