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

W = "0x" + "cd" * 20
WL = f"wallet:base:{W}"
WA = f"wallet:arbitrum:{W}"
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


def ctx(chain, loc, tag, ts, legs, ev):
    tx = h(tag)
    for i, (a, q, lk, c) in enumerate(legs):
        leg("chain_tx", chain, tx, i, ts, a, loc, q, lk, ev, c)
    con.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES (?,?,?,'{}',5)", (chain, tx, ev))
    return tx


usdc = asset("token", "base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6, "USDC")
ctx("base", WL, "fund", NOW - 200 * DAY, [(usdc, 100000, "acq", 100000)], "PROGRAM_IN")
D1 = NOW - 150 * DAY
e1 = asset("native", "arbitrum", None, "ETH", 18)
leg("chain_tx", "base", h("g1-buy"), 0, D1 - DAY, usdc, WL, -1000, "disp", "SWAP", 1000)
leg("chain_tx", "arbitrum", h("g1-buy"), 1, D1 - DAY, e1, WA, 1.0, "acq", "SWAP", 1000)
leg("chain_tx", "arbitrum", h("g1-gas"), 0, D1, e1, WA, -0.1, "gas", "NOOP", 300)
leg("chain_tx", "arbitrum", h("g1-sell"), 0, D1 + DAY, e1, WA, -0.9, "disp", "SWAP", 2700)
leg("chain_tx", "arbitrum", h("g1-sell"), 1, D1 + DAY, usdc, WL, 2700, "acq", "SWAP", 2700)
D2 = NOW - 140 * DAY
e2 = asset("native", "base", None, "ETH", 18)
ctx("base", WL, "g2-buy", D2 - DAY, [(usdc, -1000, "disp", 1000), (e2, 1.0, "acq", 1000)], "SWAP")
ctx("base", WL, "g2-sell", D2, [(e2, -0.99, "disp", 2970), (usdc, 2970, "acq", 2970), (e2, -0.01, "gas", 35)], "SWAP")
D3 = NOW - 130 * DAY
ue = asset("exchange_currency", None, "upbit:eth", "ETH", 8)
e3 = asset("native", "optimism", None, "ETH", 18)
WO = f"wallet:optimism:{W}"
leg("exchange", "upbit:order", "o-3", 0, D3 - DAY, ue, "exchange:upbit", 1.0, "acq", "EX_BUY", 3000)
leg("exchange", "upbit:withdraw", "w-3", 0, D3, ue, "exchange:upbit", -1.0, "move_out", "EX_WITHDRAW")
TX3 = h("g3-arrive")
con.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('upbit','withdraw','w-3',1,?,?)",
            (json.dumps({"uuid": "w-3", "txid": TX3, "currency": "ETH", "amount": "0.99", "fee": "0.01", "state": "DONE",
                         "created_at": "2026-01-01T00:00:00+09:00"}), D3))
leg("chain_tx", "optimism", TX3, 0, D3 + 300, e3, WO, 0.99, "acq", "TRANSFER_IN")
con.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES ('optimism',?,'TRANSFER_IN','{}',5)", (TX3,))
ctx("optimism", WO, "g3-sell", D3 + DAY, [(e3, -0.99, "disp", 2970), (usdc, 2970, "acq", 2970)], "SWAP")
D4 = NOW - 120 * DAY
BL = "exchange:binance"
bu = asset("exchange_currency", None, "binance:usdt", "USDT", 8)
bb = asset("exchange_currency", None, "binance:bnb", "BNB", 8)
leg("exchange", "binance:deposit", "d-4", 0, D4 - 3 * DAY, bu, BL, 2000, "move_in", "EXF_DEPOSIT")
leg("exchange", "binance:trade", "binance:BNBUSDT:4", 0, D4 - 2 * DAY, bu, BL, -300, "disp", "EXF_BUY", 300)
leg("exchange", "binance:trade", "binance:BNBUSDT:4", 1, D4 - 2 * DAY, bb, BL, 1.0, "acq", "EXF_BUY", 300)
leg("exchange", "binance:withdraw", "w-4", 0, D4, bb, BL, -0.01, "gas", "EXF_WD_FEE")
D5 = NOW - 110 * DAY
ue5 = asset("exchange_currency", None, "upbit:xeth", "XETH", 8)
e5 = asset("native", "scroll", None, "XETH", 18)
WS = f"wallet:scroll:{W}"
leg("exchange", "upbit:order", "o-5", 0, D5 - DAY, ue5, "exchange:upbit", 1.0, "acq", "EX_BUY", 3000)
con.execute("UPDATE postings SET cost_krw='4350000' WHERE posting_id=?", (ST["pid"],))
leg("exchange", "upbit:withdraw", "w-5", 0, D5, ue5, "exchange:upbit", -1.0, "move_out", "EX_WITHDRAW")
TX5 = h("g5-arrive")
con.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('upbit','withdraw','w-5',1,?,?)",
            (json.dumps({"uuid": "w-5", "txid": TX5, "currency": "XETH", "amount": "0.99", "fee": "0.01", "state": "DONE",
                         "created_at": "2026-01-01T00:00:00+09:00"}), D5))
leg("chain_tx", "scroll", TX5, 0, D5 + 300, e5, WS, 0.99, "acq", "TRANSFER_IN")
con.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES ('scroll',?,'TRANSFER_IN','{}',5)", (TX5,))
pos = {}
for a, loc, qb in con.execute("SELECT asset_id, location, qty_base FROM postings"):
    pos[(a, loc)] = pos.get((a, loc), 0) + int(qb)
for (a, loc), qb in pos.items():
    con.execute("INSERT OR REPLACE INTO positions (group_id, location, qty_norm, qty_unknown_norm, cost_alloc_usd) VALUES (?,?,?, '0', '0')",
                (a, loc, format(qb / 10 ** DEC[a], ".12f")))
con.commit()
con.close()

import acct_norm
import pricing
import web

pricing._gj = lambda url, *a, **k: (_ for _ in ()).throw(OSError("시험: 시세 받기 없음"))
PX = {"ETH": 3500.0, "BNB": 600.0, "XETH": 3500.0}
acct_norm.FxBook.candle = lambda self, sym, ts: PX.get(str(sym or "").upper())
web.Spot.dex_pending = lambda self, c, ca: False
web.Spot.ex_pending = lambda self, ex: False


def build(gas_on):
    common.atomic_write_json(web.PREFS_PATH, {"gas_in_cost": gas_on, "first_seen_px": False})
    b = web.StateBuilder()
    web.BUILDER = b
    st = T.safe(b.build)
    f = (st or {}).get("fields") or {} if isinstance(st, dict) else {}
    check(f"빌드 성공(가스 {'켬' if gas_on else '끔'})", bool(f), st if isinstance(st, dict) and st.get("_exc") else "fields 없음")
    return f


def day_sum(f, lo, hi):
    rbd = {k: float(v) for k, v in (f.get("realizedByDate") or {}).items()}
    return round(sum(v for k, v in rbd.items() if iso(lo) <= k <= iso(hi)), 2)


def fee_rows(f, day):
    return [r for r in f.get("_taxRowsAll") or [] if r.get("ex") == "수수료로 쓴 코인(처분)" and r.get("sold") == day]


def gas_row(f, label):
    return [g for g in f.get("gasByChain") or f.get("gas") or [] if g.get("chain") == label]


def invariants(f, tag):
    rbd = {k: float(v) for k, v in (f.get("realizedByDate") or {}).items()}
    tot = round(sum(rbd.values()), 2)
    pos9 = f.get("_positionsAll") or f.get("positions") or []
    cards = round(sum(float(p.get("realized") or 0) + float(p.get("realizedFb") or 0) for p in pos9), 2)
    check(f"{tag} 불변: 헤더 실현 합 = 카드 실현 합", abs(tot - cards) <= 0.05, (tot, cards))
    tn = round(sum(float(r.get("_disp", r.get("disp")) or 0) - float(r.get("_acq", r.get("acq")) or 0) - float(r.get("_fee", r.get("fee")) or 0)
                   for r in f.get("_taxRowsAll") or []), 2)
    check(f"{tag} 불변: 세금 명세 Σ(양도 − 취득 − 수수료) = 헤더 실현 합", abs(tot - tn) <= 0.05, (tot, tn))
    return tot


fon = build(True)
foff = build(False)
check("켬 G1 NOOP 가스: 실현 = $1,700", abs(day_sum(fon, D1 - DAY, D1 + DAY) - 1700) <= 0.05, day_sum(fon, D1 - DAY, D1 + DAY))
check("켬 G2 스왑 가스: 실현 = $1,970", abs(day_sum(fon, D2 - DAY, D2) - 1970) <= 0.05, day_sum(fon, D2 - DAY, D2))
check("켬 G3 업비트 출금 수수료: 실현 = −$30", abs(day_sum(fon, D3 - DAY, D3 + DAY) + 30) <= 0.05, day_sum(fon, D3 - DAY, D3 + DAY))
check("켬 G4 해외 출금 수수료: 실현 = −$3", abs(day_sum(fon, D4 - 3 * DAY, D4) + 3) <= 0.05, day_sum(fon, D4 - 3 * DAY, D4))
ton = invariants(fon, "켬")
g5 = fee_rows(fon, iso(D5))
rk5 = (fon.get("realizedKrwByDate") or {}).get(iso(D5))
check("켬 G5(NA8 ①) 환율 기록 없는 출금 수수료 행 = 원화 취득가액 따로 없음 · 원화 손익 = $5 × 같은 환율 = 머리 원화(가짜 환차 없음)",
      len(g5) == 1 and g5[0].get("rateSrc") in ("spot", "default") and g5[0].get("_akr") is None
      and rk5 is not None and abs((float(g5[0]["_disp"]) - float(g5[0]["_acq"])) * float(g5[0]["rate"]) - (5 * float(g5[0]["rate"]))) < 1
      and abs(float(rk5) - (5 - 35) * float(g5[0]["rate"])) < 2, [g5, rk5])
tgo = fon.get("taxGas") or {}
check("켬 taxGas.expense = 온체인 가스 비용만 $300 · 출금 수수료 $76 은 wdFee · separate − expense = 0(화면 '시가 미상'에 출금 수수료가 음수로 안 섞임)",
      abs(float(tgo.get("expense") or 0) - 300) <= 0.05 and abs(float(tgo.get("wdFee") or 0) - 76) <= 0.05
      and abs(float(tgo.get("separate") or 0) - float(tgo.get("expense") or 0)) <= 0.05, tgo)
check("켬 가스·수수료 탭에도 출금 수수료 줄(표시는 스위치와 무관 — 켬은 그날 가스 비용으로도 빠짐)",
      gas_row(fon, "업비트 출금 수수료") and gas_row(fon, "바이낸스 출금 수수료"), fon.get("gasByChain"))

check("끔 G1 NOOP 가스: 실현 = $2,000(매도 +$1,800 + 가스 코인 처분 +$200 — 가스 $300 은 따로 → 2,000 − 300 = 1,700)",
      abs(day_sum(foff, D1 - DAY, D1 + DAY) - 2000) <= 0.05, day_sum(foff, D1 - DAY, D1 + DAY))
check("끔 G1 가스 $300 은 가스·수수료 탭에 따로(아비트럼)", any(abs(float(g.get("spot") or 0) - 300) <= 0.05 for g in gas_row(foff, "Arbitrum")),
      foff.get("gasByChain"))
g1r = fee_rows(foff, iso(D1))
check("끔 G1 세금 명세 '수수료로 쓴 코인(처분)' = 취득 $100 · 양도 $300", len(g1r) == 1 and abs(float(g1r[0]["_acq"]) - 100) <= 0.01
      and abs(float(g1r[0]["_disp"]) - 300) <= 0.01, g1r)
check("끔 G2 스왑 가스: 실현 = $2,005(매도 +$1,980 + 가스 코인 처분 +$25 — 가스 $35 따로 → 1,970)",
      abs(day_sum(foff, D2 - DAY, D2) - 2005) <= 0.05, day_sum(foff, D2 - DAY, D2))
check("끔 G3 업비트 출금 수수료: 실현 = +$5(수수료 0.01 개 처분 손익 · 비용 $35 는 따로 → 5 − 35 = −30)",
      abs(day_sum(foff, D3 - DAY, D3 + DAY) - 5) <= 0.05, day_sum(foff, D3 - DAY, D3 + DAY))
check("끔 G3·G5 출금 수수료 $35 × 2 = 가스·수수료 탭 '업비트 출금 수수료' 줄 $70 · 2건(따로 표시)",
      any(abs(float(g.get("spot") or 0) - 70) <= 0.05 and g.get("tx") == 2 for g in gas_row(foff, "업비트 출금 수수료")), foff.get("gasByChain"))
check("끔 G4 해외 출금 수수료: 실현 = +$3 · 비용 $6 은 '바이낸스 출금 수수료' 줄로 따로",
      abs(day_sum(foff, D4 - 3 * DAY, D4) - 3) <= 0.05 and any(abs(float(g.get("spot") or 0) - 6) <= 0.05 for g in gas_row(foff, "바이낸스 출금 수수료")),
      [day_sum(foff, D4 - 3 * DAY, D4), foff.get("gasByChain")])
tg = foff.get("taxGas") or {}
check("끔 taxGas.wdFee = 출금 수수료 합 $76(따로 둔 비용 — 업비트 $35 × 2 + 바이낸스 $6)", tg.get("on") is False and abs(float(tg.get("wdFee") or 0) - 76) <= 0.05, tg)
check("끔 가스 비용 항목(그날 실현에서 뺀 비용) 없음", not foff.get("gasExpenseByDate"), foff.get("gasExpenseByDate"))
toff = invariants(foff, "끔")
sep = 300 + 35 + 35 + 6 + 35
check("끔 실현 − 따로 둔 비용(가스 $335 + 출금 수수료 $76) = 켬 실현", abs((toff - sep) - ton) <= 0.05, (toff, sep, ton))
T.finish()
