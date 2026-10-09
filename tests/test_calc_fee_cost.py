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
WL = f"wallet:base:{W}"
DAY = 86400
NOW = int(time.time())
KST = timezone(timedelta(hours=9))
shutil.copytree(os.path.join(T.ROOT, "seed"), os.path.join(T.TMP, "seed"), dirs_exist_ok=True)
json.dump({"wallets": [{"type": "evm", "chain": "base", "address": W, "label": "w"}], "backfill_months": 3, "chains": {}},
          open(os.path.join(T.TMP, "config.json"), "w"))
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
DEC = {}


def asset(kind, chain, addr, sym, d, gname=None):
    ST["aid"] += 1
    a = ST["aid"]
    con.execute("INSERT INTO asset_groups (group_id, name, norm_decimals) VALUES (?,?,18)", (a, gname or f"{sym}#{a}"))
    con.execute("INSERT INTO assets (asset_id, kind, chain, address, symbol, decimals, confirmed, hidden, group_id) VALUES (?,?,?,?,?,?,1,0,?)",
                (a, kind, chain, addr, sym, d, a))
    DEC[a] = d
    return a


def leg(kind, ns, sid, seq, ts, a, loc, qty, lk, ev, cost=None):
    ST["pid"] += 1
    con.execute("INSERT INTO postings (posting_id, source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd,"
                " cost_krw, leg_kind, event, classifier_ver) VALUES (?,?,?,?,?,?,?,?,?,?,NULL,?,?,5)",
                (ST["pid"], kind, ns, sid, seq, ts, a, loc, str(int(round(qty * 10 ** DEC[a]))), None if cost is None else repr(float(cost)), lk, ev))


def ctx(tag, ts, legs, ev):
    tx = h(tag)
    for i, (a, q, lk, c) in enumerate(legs):
        leg("chain_tx", "base", tx, i, ts, a, WL, q, lk, ev, c)
    con.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES ('base',?,?,'{}',5)", (tx, ev))
    return tx


usdc = asset("token", "base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6, "USDC")
ctx("fund", NOW - 200 * DAY, [(usdc, 100000, "acq", 100000)], "PROGRAM_IN")
D1 = NOW - 150 * DAY
ue = asset("exchange_currency", None, "upbit:eth", "ETH", 8)
e1 = asset("native", "base", None, "ETH", 18)
leg("exchange", "upbit:order", "o-1", 0, D1 - DAY, ue, "exchange:upbit", 1.0, "acq", "EX_BUY", 3000)
leg("exchange", "upbit:withdraw", "w-1", 0, D1, ue, "exchange:upbit", -1.0, "move_out", "EX_WITHDRAW")
TX1 = h("f1-arrive")
con.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('upbit','withdraw','w-1',1,?,?)",
            (json.dumps({"uuid": "w-1", "txid": TX1, "currency": "ETH", "amount": "0.99", "fee": "0.01", "state": "DONE",
                         "created_at": "2026-01-01T00:00:00+09:00"}), D1))
leg("chain_tx", "base", TX1, 0, D1 + 300, e1, WL, 0.99, "acq", "TRANSFER_IN")
con.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES ('base',?,'TRANSFER_IN','{}',5)", (TX1,))
ctx("f1-sell", D1 + DAY, [(e1, -0.99, "disp", 2970), (usdc, 2970, "acq", 2970)], "SWAP")
D2 = NOW - 140 * DAY
e2 = asset("native", "arbitrum", None, "ETH", 18)
leg("chain_tx", "base", h("f2-buy"), 0, D2 - DAY, usdc, WL, -1000, "disp", "SWAP", 1000)
leg("chain_tx", "arbitrum", h("f2-buy"), 1, D2 - DAY, e2, "wallet:arbitrum:" + W, 1.0, "acq", "SWAP", 1000)
leg("chain_tx", "arbitrum", h("f2-gas"), 0, D2, e2, "wallet:arbitrum:" + W, -0.1, "gas", "NOOP", 300)
leg("chain_tx", "arbitrum", h("f2-sell"), 0, D2 + DAY, e2, "wallet:arbitrum:" + W, -0.9, "disp", "SWAP", 2700)
leg("chain_tx", "arbitrum", h("f2-sell"), 1, D2 + DAY, usdc, WL, 2700, "acq", "SWAP", 2700)
D3 = NOW - 130 * DAY
BL = "exchange:binance"
bu = asset("exchange_currency", None, "binance:USDT", "USDT", 8)
bb = asset("exchange_currency", None, "binance:BNB", "BNB", 8)
bx = asset("exchange_currency", None, "binance:XXX", "XXX", 8)
leg("exchange", "binance:deposit", "d-1", 0, D3 - 3 * DAY, bu, BL, 2000, "move_in", "EXF_DEPOSIT")
leg("exchange", "binance:trade", "binance:BNBUSDT:1", 0, D3 - 2 * DAY, bu, BL, -300, "disp", "EXF_BUY", 300)
leg("exchange", "binance:trade", "binance:BNBUSDT:1", 1, D3 - 2 * DAY, bb, BL, 1.0, "acq", "EXF_BUY", 300)
leg("exchange", "binance:trade", "binance:XXXUSDT:2", 0, D3 - DAY, bu, BL, -1000, "disp", "EXF_BUY", 1000)
leg("exchange", "binance:trade", "binance:XXXUSDT:2", 1, D3 - DAY, bx, BL, 100, "acq", "EXF_BUY", 1000)
leg("exchange", "binance:trade", "binance:XXXUSDT:3", 0, D3, bx, BL, -100, "disp", "EXF_SELL", 1500)
leg("exchange", "binance:trade", "binance:XXXUSDT:3", 1, D3, bu, BL, 1500, "acq", "EXF_SELL", 1500)
leg("exchange", "binance:trade", "binance:XXXUSDT:3", 2, D3, bb, BL, -0.01, "gas", "EXF_FEE")
D4 = NOW - 120 * DAY
aa = asset("token", "base", "0x" + "aa" * 20, "AAA", 18)
bbt = asset("token", "base", "0x" + "bb" * 20, "BBB", 18)
ctx("f4-buy", D4 - DAY, [(usdc, -3000, "disp", 3000), (aa, 1000, "acq", 3000)], "SWAP")
ctx("f4-x", D4, [(aa, -1000, "disp", None), (bbt, 500, "acq", None)], "SWAP")
ctx("f4-sell", D4 + DAY, [(bbt, -500, "disp", 6000), (usdc, 6000, "acq", 6000)], "SWAP")
D5 = NOW - 100 * DAY
tk = asset("token", "base", "0x" + "11" * 20, "TKN", 18)
ctx("f5-air", D5 - 5 * DAY, [(tk, 1000, "acq", None)], "PROGRAM_IN")
ctx("f5-sell", D5, [(tk, -1000, "disp", 1000), (usdc, 1000, "acq", 1000)], "SWAP")
ctx("f5-buy", D5 + 69 * DAY, [(usdc, -1000, "disp", 1000), (tk, 100, "acq", 1000)], "SWAP")
D6 = NOW - 90 * DAY
tb = asset("token", "base", "0x" + "12" * 20, "TKB", 18)
zz = asset("token", "base", "0x" + "13" * 20, "ZZZ", 18)
ctx("f6-buy", D6 - DAY, [(usdc, -100, "disp", 100), (tb, 100, "acq", 100)], "SWAP")
ctx("f6-br", D6, [(tb, -100, "move_out", None), (zz, 5, "move_in", None)], "BRIDGE")
pos = {}
for a, loc, qb in con.execute("SELECT asset_id, location, qty_base FROM postings"):
    pos[(a, loc)] = pos.get((a, loc), 0) + int(qb)
for (a, loc), qb in pos.items():
    con.execute("INSERT OR REPLACE INTO positions (group_id, location, qty_norm, qty_unknown_norm, cost_alloc_usd) VALUES (?,?,?, '0', '0')",
                (a, loc, format(qb / 10 ** DEC[a], ".12f")))
con.commit()
con.close()
json.dump({"fallback_avg": True}, open(os.path.join(common.STATE_DIR, "ui_prefs.json"), "w"))

import acct_norm
import pricing
import web

PRICE_TRIES = []


def _no_price(url, *a, **k):
    PRICE_TRIES.append(str(url)[:80])
    raise OSError("시험: 시세 받기 없음")


pricing._gj = _no_price

PX = {"ETH": 3500.0, "BNB": 600.0}
acct_norm.FxBook.candle = lambda self, sym, ts: PX.get(str(sym or "").upper())
web.Spot.dex_pending = lambda self, c, ca: False
web.Spot.ex_pending = lambda self, ex: False
b = web.StateBuilder()
web.BUILDER = b
st = T.safe(b.build)
f = (st or {}).get("fields") or {} if isinstance(st, dict) else {}
check("빌드 성공", bool(f), st if isinstance(st, dict) and st.get("_exc") else "fields 없음")
rbd = {k: float(v) for k, v in (f.get("realizedByDate") or {}).items()}
pos = f.get("_positionsAll") or f.get("positions") or []
pend = f.get("pendings") or []
tax = f.get("_taxRowsAll") or []


def day_sum(lo, hi):
    return round(sum(v for k, v in rbd.items() if iso(lo) <= k <= iso(hi)), 2)


check("F1 거래소 출금 수수료: 출금~매도 실현 = −$30(수수료 0.01 개의 원가)", abs(day_sum(D1 - DAY, D1 + DAY) + 30) <= 0.05, rbd)
fd = [r for r in tax if r.get("ex") == "수수료로 쓴 코인(처분)" and r.get("sold") == iso(D1)]
check("F1 세금 명세 '수수료로 쓴 코인(처분)' = 취득 $30 · 양도 $35(시가)", len(fd) == 1 and abs(float(fd[0]["_acq"]) - 30) <= 0.01
      and abs(float(fd[0]["_disp"]) - 35) <= 0.01, fd)
ge = (f.get("gasExpenseByDate") or {}).get(iso(D1)) or [0, 0, {}]
check("F1 가스 비용 칸 = 출금 수수료 시가 $35", abs(float(ge[0]) - 35) <= 0.05, ge)
check("F2 가스: 매수~매도 실현 = $1,700(가스 비용 −$300 · 처분 손익 +$200 · 매도 +$1,800)", abs(day_sum(D2 - DAY, D2 + DAY) - 1700) <= 0.05, rbd)
check("F3 체결 수수료 코인: 실현 = $497", abs(day_sum(D3 - 3 * DAY, D3) - 497) <= 0.05, rbd)
check("F4 양쪽 시세 없는 스왑: B 매도 실현 = +$3,000", abs(day_sum(D4 - DAY, D4 + DAY) - 3000) <= 0.05, rbd)
check("F4 대금 미상 매도·원가미상 매도 검토 없음(AAA·BBB)",
      not [p for p in pend if p.get("sym") in ("AAA", "BBB") and str(p.get("key")).startswith(("noproc:", "unv:"))], pend)
check("F5 평균가 대체: 매수 없는 사이클의 원가 미상 매도는 새 사이클 평단으로 실현 안 함(그날 0)", abs(rbd.get(iso(D5), 0.0)) <= 0.05, rbd)
pz = [p for p in pos if p.get("sym") == "ZZZ"]
check("F6 브릿지 tx 에서 받은 ZZZ 5 개(낸 것 TKB 하나 · 받은 것 하나 = 예치 증서) = TKB 원가 $100 승계 카드(원가 미상 0)",
      any(abs(float(p.get("bought") or 0) - 5) <= 1e-6 and abs(float(p.get("cost") or 0) - 100) <= 0.01 and not float(p.get("unknownQty") or 0) for p in pz), pz)
tot = round(sum(rbd.values()), 2)
cards = round(sum(float(p.get("realized") or 0) + float(p.get("realizedFb") or 0) for p in pos), 2)
check("불변: 헤더 실현 합 = 카드 실현 합", abs(tot - cards) <= 0.05, (tot, cards))
tn = round(sum(float(r.get("_disp", r.get("disp")) or 0) - float(r.get("_acq", r.get("acq")) or 0) - float(r.get("_fee", r.get("fee")) or 0) for r in tax), 2)
check("불변: 세금 명세 Σ(양도 − 취득 − 수수료) = 헤더 실현 합", abs(tot - tn) <= 0.05, (tot, tn))
T.finish()
