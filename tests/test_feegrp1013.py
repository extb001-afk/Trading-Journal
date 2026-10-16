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
D3 = int(datetime.fromtimestamp(NOW - 30 * DAY, KST).replace(hour=12, minute=0, second=0, microsecond=0).timestamp())
BL = "exchange:binance"
bu = asset("exchange_currency", None, "binance:USDT", "USDT", 8)
bb = asset("exchange_currency", None, "binance:BNB", "BNB", 8)
bx = asset("exchange_currency", None, "binance:XXX", "XXX", 8)
leg("exchange", "binance:deposit", "d-1", 0, D3 - 3 * DAY, bu, BL, 5000, "move_in", "EXF_DEPOSIT")
leg("exchange", "binance:trade", "binance:BNBUSDT:1", 0, D3 - 2 * DAY, bu, BL, -300, "disp", "EXF_BUY", 300)
leg("exchange", "binance:trade", "binance:BNBUSDT:1", 1, D3 - 2 * DAY, bb, BL, 1.0, "acq", "EXF_BUY", 300)
leg("exchange", "binance:trade", "binance:XXXUSDT:2", 0, D3 - DAY, bu, BL, -1000, "disp", "EXF_BUY", 1000)
leg("exchange", "binance:trade", "binance:XXXUSDT:2", 1, D3 - DAY, bx, BL, 100, "acq", "EXF_BUY", 1000)
for i9 in range(3):
    leg("exchange", "binance:trade", f"binance:XXXUSDT:{3 + i9}", 0, D3 + i9 * 60, bx, BL, -10, "disp", "EXF_SELL", 150)
    leg("exchange", "binance:trade", f"binance:XXXUSDT:{3 + i9}", 1, D3 + i9 * 60, bu, BL, 150, "acq", "EXF_SELL", 150)
    leg("exchange", "binance:trade", f"binance:XXXUSDT:{3 + i9}", 2, D3 + i9 * 60, bb, BL, -0.01 * (i9 + 1), "gas", "EXF_FEE")
leg("exchange", "binance:trade", "binance:XXXUSDT:9", 0, D3 + DAY, bx, BL, -10, "disp", "EXF_SELL", 150)
leg("exchange", "binance:trade", "binance:XXXUSDT:9", 1, D3 + DAY, bu, BL, 150, "acq", "EXF_SELL", 150)
leg("exchange", "binance:trade", "binance:XXXUSDT:9", 2, D3 + DAY, bb, BL, -0.02, "gas", "EXF_FEE")
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


def _no_price(url, *a, **k):
    raise OSError("시험: 시세 받기 없음")


pricing._gj = _no_price
PX = {"BNB": 600.0}
RT = {}


def _rate_src(self, ts, row=None):
    r9 = 1300.0 + (int(ts) % 1000) / 10.0
    RT[int(ts)] = r9
    return r9, "minute"


acct_norm.FxBook.candle = lambda self, sym, ts: PX.get(str(sym or "").upper())
acct_norm.FxBook.rate_src = _rate_src
acct_norm.FxBook.rate_at = lambda self, ts, row=None: _rate_src(self, ts, row)[0]
web.Spot.dex_pending = lambda self, c, ca: False
web.Spot.ex_pending = lambda self, ex: False
b = web.StateBuilder()
web.BUILDER = b
st = T.safe(b.build)
f = (st or {}).get("fields") or {} if isinstance(st, dict) else {}
check("빌드 성공", bool(f), st if isinstance(st, dict) and st.get("_exc") else "fields 없음")
FEE = "수수료로 쓴 코인(처분)"
d0, d1 = iso(D3), iso(D3 + DAY)
raw = [r for r in f.get("_taxRowsAll") or [] if r.get("ex") == FEE and r.get("sym") == "BNB"]
check("G4 빌드 내부 BNB 수수료 처분 = 4건 그대로(같은 날 3 · 다음 날 1)", sorted(r["sold"] for r in raw) == [d0, d0, d0, d1], [(r["sold"], r["qty"]) for r in raw])
r0 = [r for r in raw if r["sold"] == d0]
out = [r for r in f.get("taxRows") or [] if r.get("ex") == FEE and r.get("sym") == "BNB"]
m0 = [r for r in out if r["sold"] == d0]
check("G1 응답 taxRows = 2줄(같은 날 3건 → 1줄 n=3 · 다음 날 1줄 그대로)", len(out) == 2 and len(m0) == 1 and m0[0].get("n") == 3
      and not [r for r in out if r["sold"] == d1][0].get("n"), out)
if m0:
    m = m0[0]
    sq, sa, sd = (sum(float(r["_" + k]) for r in r0) for k in ("qty", "acq", "disp"))
    check("G1 묶은 줄 수량·취득·양도 = 3건 합(0.06 개 · 취득 $18 · 양도 $36)", abs(m["qty"] - round(sq, 4)) < 1e-9 and abs(m["acq"] - round(sa, 2)) < 1e-9
          and abs(m["disp"] - round(sd, 2)) < 1e-9 and abs(sq - 0.06) < 1e-9 and abs(sa - 18) <= 0.01 and abs(sd - 36) <= 0.01, (m, sq, sa, sd))
    dk = sum(float(r["_disp"]) * float(r["rate"]) for r in r0)
    check("G1 원화 양도(양도 × 환율) = 건별 합(환율이 건마다 달라도)", len({r["rate"] for r in r0}) == 3 and abs(m["disp"] * m["rate"] - dk) <= 1.0, (m, dk, [r["rate"] for r in r0]))
    ak = sum(float(r.get("_akr", r.get("akr"))) if r.get("_akr", r.get("akr")) is not None else float(r["_acq"]) * float(r["rate"]) for r in r0)
    check("G1 원화 취득(akr) = 건별 합", m.get("akr") is not None and abs(float(m["akr"]) - ak) <= 1.0, (m, ak))
    check("G1 응답에 내부 필드 없음", not [k for k in m if k.startswith("_")], m)
summ = [r for r in f.get("taxSummary") or [] if r[1] == "BNB" and r[2] == FEE]
check("G2 요약 건수 = 2(날짜 수) · 취득·양도 = 4건 합", sum(r[3] for r in summ) == 2
      and abs(sum(r[5] for r in summ) - sum(float(r["_acq"]) for r in raw)) <= 0.01
      and abs(sum(r[6] for r in summ) - sum(float(r["_disp"]) for r in raw)) <= 0.01, summ)
check("G2 요약 원화 양도 = 건별 원화 합", abs(sum(r[10] for r in summ) - sum(float(r["_disp"]) * float(r["rate"]) for r in raw)) <= 1.0, summ)
sold = [r for r in f.get("_taxRowsAll") or [] if r.get("sym") == "XXX"]
check("G3 매도 행(XXX)은 건별 그대로 4행", len(sold) == 4 and len([r for r in f.get("taxRows") or [] if r.get("sym") == "XXX"]) == 4, sold)
T.safe(b.snapshot)
ym = d0[:7]
tr = T.safe(b.tax_rows, ym, "BNB")
if isinstance(tr, dict) and tr.get("ok"):
    exp = 2 if d1[:7] == ym else 1
    rr = [r for r in tr["rows"] if r.get("ex") == FEE]
    check(f"G3 /api/tax_rows BNB {ym} = 묶은 줄 {exp} · total {exp}", tr["total"] == exp and len(rr) == exp and any(r.get("n") == 3 for r in rr), tr)
else:
    check("G3 /api/tax_rows 응답", False, tr)
rbd = sum(float(v) for v in (f.get("realizedByDate") or {}).values())
tsum = sum(float(r.get("_disp", 0)) - float(r.get("_acq", 0)) - float(r.get("_fee", 0)) for r in f.get("_taxRowsAll") or [])
check("G4 헤더 실현 = 명세 Σ(양도 − 취득 − 수수료)", abs(rbd - tsum) <= 0.05, (rbd, tsum))

print("[G6] 원화 원가 기록 없는 묶음(공개 코덱스 pubv31)")
g6 = [{"sold": "2026-09-01", "sym": "Q", "ticker": "Q", "ex": FEE, "qty": 1, "acq": 10, "disp": 10, "fee": 0, "rate": 1300.0, "rateSrc": "spot", "_acq": 10.0, "_disp": 10.0, "_qty": 1.0},
      {"sold": "2026-09-01", "sym": "Q", "ticker": "Q", "ex": FEE, "qty": 1, "acq": 10, "disp": 20, "fee": 0, "rate": 1310.0, "rateSrc": "spot", "_acq": 10.0, "_disp": 20.0, "_qty": 1.0}]
mg = web._tax_fee_merge(g6)
sm = web._tax_summary(g6, "2026-10-13")
check("G6 akr 없는 2건 묶음 = 원화 취득 = 건별 취득 × 그 건 환율 합(₩26,100) = 요약 원화 취득", len(mg) == 1 and mg[0].get("akr") == 26100
      and abs(sm[0][12] - 26100) <= 1 and sm[0][3] == 1, (mg, sm))
check("G6 묶은 줄 원화 손익 = 요약 원화 손익", abs((mg[0]["disp"] * mg[0]["rate"] - mg[0]["akr"]) - sm[0][13]) <= 1.0, (mg, sm))
check("G6 스테이블(tk st)·다른 거래처 글자는 묶지 않음", len(web._tax_fee_merge([dict(g6[0], tk="st"), dict(g6[1], tk="st")])) == 2
      and len(web._tax_fee_merge([g6[0], dict(g6[1], ex="바이낸스 대출 상환(빌린 코인 · 빌린 시각 시가로 정산)")])) == 2)

print("[G5] 화면")
app = T.app_js()
check("G5 체결 상세 줄: n > 1 이면 'N건 묶음'", "(num(r.n) > 1 ? ' · ' + nf('ko-KR').format(num(r.n)) + '건 묶음' : '')" in app)
T.finish()
