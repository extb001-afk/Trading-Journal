#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import hashlib
import json
import os
import shutil
import time
from datetime import datetime, timedelta, timezone

W = "0x" + "ab" * 20
DAY = 86400
NOW = int(time.time())
KST = timezone(timedelta(hours=9))
shutil.copytree(os.path.join(T.ROOT, "seed"), os.path.join(T.TMP, "seed"), dirs_exist_ok=True)
json.dump({"wallets": [{"type": "evm", "chain": "base", "address": W, "label": "w"}, {"type": "evm", "chain": "arbitrum", "address": W, "label": "w"}],
           "backfill_months": 3, "chains": {}}, open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
os.environ["TJ_REPLAY_DEBUG"] = "1"
import common

assert T.TMP in common.STATE_DIR
import db as dbm


def check(name, ok, detail=""):
    T.chk(bool(ok), name, None if ok else detail)


def h(tag):
    return "0x" + hashlib.sha256(tag.encode()).hexdigest()


def iso(ts):
    return datetime.fromtimestamp(ts, KST).strftime("%Y-%m-%d")


con = dbm.open_db(os.path.join(common.STATE_DIR, "ledger.db"))
ST = {"aid": 0, "pid": 0}
DEC, GID = {}, {}


def asset(chain, addr, sym, gname=None, d=18, kind="token"):
    ST["aid"] += 1
    a = ST["aid"]
    nm = gname or f"{sym}#{a}"
    row = con.execute("SELECT group_id FROM asset_groups WHERE name=?", (nm,)).fetchone()
    if row is None:
        con.execute("INSERT INTO asset_groups (group_id, name, norm_decimals) VALUES (?,?,18)", (100 + a, nm))
    g = row[0] if row is not None else 100 + a
    con.execute("INSERT INTO assets (asset_id, kind, chain, address, symbol, decimals, confirmed, hidden, group_id) VALUES (?,?,?,?,?,?,1,0,?)",
                (a, kind, chain, addr, sym, d, g))
    DEC[a], GID[a] = d, g
    return a


def leg(chain, tx, seq, ts, a, qty, lk, ev, cost=None):
    ST["pid"] += 1
    con.execute("INSERT INTO postings (posting_id, source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd,"
                " cost_krw, leg_kind, event, classifier_ver) VALUES (?,'chain_tx',?,?,?,?,?,?,?,?,NULL,?,?,5)",
                (ST["pid"], chain, tx, seq, ts, a, f"wallet:{chain}:{W}", str(int(round(qty * 10 ** DEC[a]))), None if cost is None else repr(float(cost)),
                 lk, ev))


def ctx(chain, tag, ts, legs, ev, tx=None, block=None, snap=None):
    t9 = tx or h(tag)
    for i, (a, q, lk, c) in enumerate(legs):
        leg(chain, t9, i, ts, a, q, lk, ev, c)
    con.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES (?,?,?,'{}',5)", (chain, t9, ev))
    if block is not None:
        con.execute("INSERT INTO raw_txs (chain, txhash, block, ts, snapshot, wallets, ingested_at) VALUES (?,?,?,?,?,'[]',0)",
                    (chain, t9, block, ts, json.dumps(snap or {})))
    return t9


ub = asset("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", "USDC", 6)
ua = asset("arbitrum", "0xaf88d065e77c8cc2239327c5edb3a432268e5831", "USDC", "USDC", 6)
ctx("base", "fund", NOW - 200 * DAY, [(ub, 100000, "acq", 100000)], "PROGRAM_IN")
ctx("arbitrum", "funda", NOW - 200 * DAY, [(ua, 100000, "acq", 100000)], "PROGRAM_IN")
D1 = NOW - 150 * DAY
a1, b1 = asset("base", "0x" + "a1" * 20, "HPA"), asset("base", "0x" + "b1" * 20, "HPB")
ctx("base", "", D1, [(ub, -1000, "disp", 1000), (a1, 1000, "acq", 1000)], "SWAP", tx="0x" + "9" * 64)
ctx("base", "", D1, [(a1, -1000, "disp", 1200), (b1, 500, "acq", 1200)], "SWAP", tx="0x" + "5" * 64)
ctx("base", "", D1, [(b1, -500, "disp", 1500), (ub, 1500, "acq", 1500)], "SWAP", tx="0x" + "1" * 64)
D2 = NOW - 140 * DAY
a2 = asset("base", "0x" + "a2" * 20, "HLD")
ctx("base", "b2-pre", D2 - 3600, [(ub, -1000, "disp", 1000), (a2, 1000, "acq", 1000)], "SWAP")
ctx("base", "", D2, [(a2, -1000, "disp", 3000), (ub, 3000, "acq", 3000)], "SWAP", tx="0x2" + "0" * 63, block=500, snap={"tx": {"position": 3}})
ctx("base", "", D2, [(ub, -2000, "disp", 2000), (a2, 1000, "acq", 2000)], "SWAP", tx="0x1" + "0" * 63, block=500, snap={"tx": {"position": 7}})
D3 = NOW - 130 * DAY
d3b, d3x, d3y = asset("base", "0x" + "d1" * 20, "DCY"), asset("arbitrum", "0x" + "d2" * 20, "DCY"), asset("arbitrum", "0x" + "d3" * 20, "DCY")
ctx("base", "b3-buy", D3 - 3600, [(ub, -1000, "disp", 1000), (d3b, 1000, "acq", 1000)], "SWAP")
ctx("base", "b3-br", D3, [(d3b, -1000, "move_out", None)], "BRIDGE")
ctx("arbitrum", "b3-x", D3 + 60, [(d3x, 995, "acq", None)], "TRANSFER_IN")
ctx("arbitrum", "b3-y", D3 + 900, [(d3y, 999, "acq", None)], "TRANSFER_IN")
ctx("arbitrum", "b3-sell", D3 + DAY, [(d3y, -999, "disp", 1500), (ua, 1500, "acq", 1500)], "SWAP")
D4 = NOW - 120 * DAY
e4b, e4a = asset("base", "0x" + "e1" * 20, "ERL"), asset("arbitrum", "0x" + "e2" * 20, "ERL")
ctx("base", "b4-buy", D4 - 3600, [(ub, -1000, "disp", 1000), (e4b, 1000, "acq", 1000)], "SWAP")
ctx("arbitrum", "b4-arr", D4 - 300, [(e4a, 1000, "acq", None)], "TRANSFER_IN")
ctx("base", "b4-br", D4, [(e4b, -1000, "move_out", None)], "BRIDGE")
ctx("arbitrum", "b4-sell", D4 + DAY, [(e4a, -1000, "disp", 1500), (ua, 1500, "acq", 1500)], "SWAP")
D5 = NOW - 110 * DAY
f5b, f5a = asset("base", "0x" + "f1" * 20, "FEF"), asset("arbitrum", "0x" + "f2" * 20, "FEF")
ctx("base", "b5-buy", D5 - 3600, [(ub, -1000, "disp", 1000), (f5b, 1000, "acq", 1000)], "SWAP")
ctx("base", "b5-br", D5, [(f5b, -1000, "move_out", None)], "BRIDGE")
ctx("arbitrum", "b5-arr", D5 + 600, [(f5a, 950, "acq", None)], "TRANSFER_IN")
ctx("arbitrum", "b5-sell", D5 + DAY, [(f5a, -950, "disp", 1500), (ua, 1500, "acq", 1500)], "SWAP")
D6 = NOW - 100 * DAY
a6, b6, c6 = asset("base", "0x" + "61" * 20, "TSA"), asset("base", "0x" + "62" * 20, "TSB"), asset("base", "0x" + "63" * 20, "TSC")
ctx("base", "b6-buy", D6 - 3600, [(ub, -2000, "disp", 2000), (a6, 1000, "acq", 2000)], "SWAP")
ctx("base", "b6-x", D6, [(a6, -1000, "disp", None), (b6, 100, "acq", None), (c6, 300, "acq", None)], "SWAP")
ctx("base", "b6-sb", D6 + DAY, [(b6, -100, "disp", 3000), (ub, 3000, "acq", 3000)], "SWAP")
ctx("base", "b6-sc", D6 + DAY + 60, [(c6, -300, "disp", 3000), (ub, 3000, "acq", 3000)], "SWAP")
D6b = NOW - 90 * DAY
a7, c7, b7 = asset("base", "0x" + "71" * 20, "TTA"), asset("base", "0x" + "72" * 20, "TTC"), asset("base", "0x" + "73" * 20, "TTB")
ctx("base", "b6b-ba", D6b - 3600, [(ub, -1000, "disp", 1000), (a7, 1000, "acq", 1000)], "SWAP")
ctx("base", "b6b-bc", D6b - 3000, [(ub, -1000, "disp", 1000), (c7, 500, "acq", 1000)], "SWAP")
ctx("base", "b6b-x", D6b, [(a7, -1000, "disp", None), (c7, -500, "disp", None), (b7, 200, "acq", None)], "SWAP")
ctx("base", "b6b-sb", D6b + DAY, [(b7, -200, "disp", 4000), (ub, 4000, "acq", 4000)], "SWAP")
D7 = NOW - 80 * DAY
r7, x7, o7 = asset("base", "0x" + "e5" * 20, "RCP"), asset("base", "0x" + "e6" * 20, "xRCP"), asset("arbitrum", "0x" + "e7" * 20, "RCP")
ctx("base", "b7-buy", D7 - 3600, [(ub, -1000, "disp", 1000), (r7, 1000, "acq", 1000)], "SWAP")
ctx("base", "b7-dep", D7, [(x7, 1000, "move_in", None), (r7, -1000, "move_out", None)], "BRIDGE")
ctx("arbitrum", "b7-other", D7 + 600, [(o7, 1000, "acq", None)], "TRANSFER_IN")
ctx("base", "b7-sell", D7 + DAY, [(x7, -1000, "disp", 1500), (ub, 1500, "acq", 1500)], "SWAP")
pos = {}
for a, loc, qb in con.execute("SELECT asset_id, location, qty_base FROM postings"):
    pos[(GID[a], loc)] = pos.get((GID[a], loc), 0) + int(qb) / 10 ** DEC[a]
for (g, loc), q in pos.items():
    con.execute("INSERT OR REPLACE INTO positions (group_id, location, qty_norm, qty_unknown_norm, cost_alloc_usd) VALUES (?,?,?, '0', '0')",
                (g, loc, format(q, ".12f")))
con.commit()
con.close()

import acct_norm
import pricing
import web

PRICE_TRIES = []


def _no_price(url, *a, **k):
    PRICE_TRIES.append(str(url)[:80])
    raise OSError("시험: 시세 받기 없음")


pricing._gj = _no_price
PX = {"FEF": 1.2}
acct_norm.FxBook.candle = lambda self, sym, ts: PX.get(str(sym or "").upper())
web.Spot.dex_pending = lambda self, c, ca: False
web.Spot.ex_pending = lambda self, ex: False
b = web.StateBuilder()
web.BUILDER = b
st = T.safe(b.build)
f = (st or {}).get("fields") or {} if isinstance(st, dict) else {}
check("빌드 성공", bool(f), st if isinstance(st, dict) and st.get("_exc") else "fields 없음")
rbd = {k: float(v) for k, v in (f.get("realizedByDate") or {}).items()}
cards = f.get("_positionsAll") or f.get("positions") or []
pend = f.get("pendings") or []
tax = f.get("_taxRowsAll") or []


def day(ts):
    return round(rbd.get(iso(ts), 0.0), 2)


def pend_of(sym, pre=("unv:", "unkh:", "noproc:", "unvlost:")):
    return [p for p in pend if p.get("sym") == sym and str(p.get("key") or "").startswith(pre)]


def evs(sym):
    return [str(e.get("d")) for p in cards if p.get("sym") == sym for e in (p.get("events") or [])]


check("B1 같은 초 A 매수 → A→B → B 매도 = +$500(아무도 모자라지 않는 순서)", abs(day(D1) - 500) <= 0.05, rbd)
check("B1 검토 없음", not pend_of("HPA") and not pend_of("HPB"), [p for p in pend if p.get("sym") in ("HPA", "HPB")])
check("B2 같은 블록 tx.position 매도 3 < 매수 7 → 매도 먼저 = +$2,000", abs(day(D2) - 2000) <= 0.05, rbd)
dx = [p for p in cards if p.get("_gid") == GID[d3x] or (p.get("sym") == "DCY" and abs(float(p.get("unknownQty") or 0) - 995) <= 1e-6)]
check("B3 미끼 995(컨트랙트 다름) = 원가 안 가져감(원가 미상 995)", any(abs(float(p.get("unknownQty") or 0) - 995) <= 1e-6 for p in dx), dx)
check("B3 진짜 999 매도 = 원가미상 매도 검토(실현 0) + 검토 출처 '브릿지 도착 후보 여러 개'", abs(day(D3 + DAY)) <= 0.05 and
      any("브릿지 도착 후보 여러 개" in json.dumps(p.get("cands") or [], ensure_ascii=False) for p in pend_of("DCY")), pend_of("DCY"))
check("B4 도착이 출발보다 5분 먼저 찍혀도 원가 승계 → 매도 +$500 · 검토 없음", abs(day(D4 + DAY) - 500) <= 0.05 and not pend_of("ERL"), (rbd, pend_of("ERL")))
check("B5 브릿지 날 −$50(시가 비용 $60 + 처분 손익 $10) · 매도 +$550 · 합 +$500", abs(day(D5) + 50) <= 0.05 and abs(day(D5 + DAY) - 550) <= 0.05, rbd)
ge = (f.get("gasExpenseByDate") or {}).get(iso(D5)) or [0, 0, {}]
check("B5 가스 비용 '브릿지 수수료'(BRIDGE_FEE) 칸 = 수수료 시가 $60", abs(float(ge[0]) - 60) <= 0.05 and "BRIDGE_FEE" in (ge[2] or {}), ge)
check("B6 A → B + C · 합 +$4,000 · 받은 쪽 '추정' 표시", abs(day(D6 + DAY) - 4000) <= 0.05 and any("추정" in d for d in evs("TSB") + evs("TSC")), (rbd, evs("TSB")))
check("B6 A + C → B · +$2,000 · 검토 없음", abs(day(D6b + DAY) - 2000) <= 0.05 and not pend_of("TTB"), (rbd, pend_of("TTB")))
check("B7 증서 매도 +$500 · 검토 없음", abs(day(D7 + DAY) - 500) <= 0.05 and not pend_of("xRCP"), (rbd, pend_of("xRCP")))
check("B7 다른 체인 같은 심볼 유입 = 원가 안 가져감(원가 미상 1,000)",
      any(p.get("sym") == "RCP" and abs(float(p.get("unknownQty") or 0) - 1000) <= 1e-6 for p in cards),
      [(p.get("sym"), p.get("unknownQty"), p.get("cost")) for p in cards if p.get("sym") == "RCP"])
tot = round(sum(rbd.values()), 2)
cs = round(sum(float(p.get("realized") or 0) + float(p.get("realizedFb") or 0) for p in cards), 2)
check("불변: 헤더 실현 합 = 카드 실현 합", abs(tot - cs) <= 0.05, (tot, cs))
tn = round(sum(float(r.get("_disp", r.get("disp")) or 0) - float(r.get("_acq", r.get("acq")) or 0) - float(r.get("_fee", r.get("fee")) or 0) for r in tax), 2)
check("불변: 세금 명세 Σ(양도 − 취득 − 수수료) = 헤더 실현 합", abs(tot - tn) <= 0.05, (tot, tn))
T.finish()
