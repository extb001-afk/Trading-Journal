#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import common

json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(os.environ["TJ_BASE"], "config.json"), "w"))
import acct_norm
import db as dbm
import histcurve
import netpace
import web
FS_EX = getattr(web, "FS_EX", " · 최초 인식 시가")

chk = T.chk
for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker"):
    if hasattr(web.StateBuilder, _m):
        setattr(web.StateBuilder, _m, lambda self: None)
netpace.wait = lambda url, now=None, sleep=None: None
KST = timezone(timedelta(hours=9))
NOW = int(time.time())
DAY = 86400
W = int((datetime.fromtimestamp(NOW, KST).replace(hour=9, minute=0, second=0, microsecond=0) - timedelta(days=140)).timestamp())

c = dbm.open_db(common.DB_PATH)
A, G = {}, {}
for sym in ("LLL", "MMM", "NNN", "OOO", "PPP", "QQQ", "RRR", "SSS", "USDT"):
    c.execute("INSERT INTO asset_groups (name) VALUES (?)", (sym,))
    G[sym] = c.execute("SELECT group_id FROM asset_groups WHERE name=?", (sym,)).fetchone()[0]
    for ex in ("bybit", "binance"):
        c.execute("INSERT INTO assets (kind, chain, address, symbol, decimals, confirmed, group_id) VALUES ('exchange_currency',NULL,?,?,8,1,?)",
                  (f"{ex}:{sym}", sym, G[sym]))
        A[(ex, sym)] = c.execute("SELECT last_insert_rowid()").fetchone()[0]


def post(ex, kind, sid, t, sym, qty, usd, lk, evk, leg=0):
    c.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event,"
              " classifier_ver) VALUES ('exchange',?,?,?,?,?,?,?,?,NULL,?,?,4)",
              (f"{ex}:{kind}", sid, leg, int(t), A[(ex, sym)], f"exchange:{ex}", str(int(Decimal(str(qty)) * 10 ** 8)),
               None if usd is None else repr(float(usd)), lk, evk))


def move(t, sym, qty, src, dst, tag):
    tx = f"0x{tag}"
    post(src, "withdraw", f"w{tag}", t, sym, -qty, None, "move_out", "EXF_WITHDRAW")
    post(dst, "deposit", f"d{tag}", t + 600, sym, qty, None, "move_in", "EXF_DEPOSIT")
    for ex, kind, uid, st in ((src, "withdraw", f"w{tag}", "DONE"), (dst, "deposit", f"d{tag}", "ACCEPTED")):
        c.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES (?,?,?,1,?,?)",
                  (ex, kind, uid, json.dumps({"uuid": f"{ex}:{uid}", "currency": sym, "amount": str(qty), "fee": "0", "txid": tx, "state": st,
                                              "created_at": "", "done_at": ""}), int(t)))


def trade(ex, sid, t, sym, qty, usd):
    post(ex, "trade", sid, t, sym, qty, usd, "acq" if qty > 0 else "disp", "EXF_BUY" if qty > 0 else "EXF_SELL")


T1 = W + 10 * DAY
move(T1, "LLL", 100, "bybit", "binance", "a1")
trade("binance", "s1", W + 11 * DAY, "LLL", -100, 400)
trade("binance", "b1", W + 20 * DAY, "LLL", 102, 204)
move(W + 20 * DAY + 3600, "LLL", 102, "binance", "bybit", "a2")
post("bybit", "recon", "recon:LLL", W + 25 * DAY, "LLL", -2, None, "opening", "EXF_ADJUST")
move(W + 30 * DAY, "MMM", 50, "bybit", "binance", "m1")
trade("binance", "s2", W + 31 * DAY, "MMM", -50, 150)
trade("binance", "b3", W + 35 * DAY + 120, "NNN", 10, 10)
move(W + 35 * DAY, "NNN", 10, "binance", "bybit", "n1")
trade("bybit", "s3", W + 36 * DAY, "NNN", -10, 30)
trade("binance", "b4", W + 1 * DAY, "OOO", 20, 20)
T4 = W + 40 * DAY
move(T4, "OOO", 30, "bybit", "binance", "o1")
trade("binance", "s4", W + 41 * DAY, "OOO", -30, 180)
trade("binance", "b5", W + 45 * DAY, "OOO", 30, 120)
move(W + 45 * DAY + 3600, "OOO", 30, "binance", "bybit", "o2")
trade("binance", "s5", W + 50 * DAY, "OOO", -20, 60)
move(W + 60 * DAY, "PPP", 40, "bybit", "binance", "p1")
trade("binance", "s6", W + 61 * DAY, "PPP", -40, 100)
trade("binance", "b6", W + 70 * DAY, "PPP", 40, 80)
move(W + 70 * DAY + 3600, "PPP", 40, "binance", "bybit", "p2")
post("bybit", "deposit", "q0", W + 74 * DAY, "USDT", 300, 300, "move_in", "EXF_DEPOSIT")
move(W + 75 * DAY, "QQQ", 100, "bybit", "binance", "q1")
trade("binance", "s7", W + 76 * DAY, "QQQ", -100, 400)
TQ = W + 85 * DAY
post("bybit", "trade", "q2", TQ, "USDT", -200, 200, "disp", "EXF_SELL", leg=0)
post("bybit", "trade", "q2", TQ, "QQQ", 100, 200, "acq", "EXF_BUY", leg=1)
post("bybit", "trade", "q2", TQ, "USDT", "-0.2", None, "gas", "EXF_FEE", leg=2)
move(W + 90 * DAY, "RRR", 100, "bybit", "binance", "r1")
trade("binance", "s8", W + 91 * DAY, "RRR", -100, 400)
post("binance", "deposit", "r2", W + 95 * DAY, "RRR", 10, None, "move_in", "EXF_DEPOSIT")
trade("binance", "b8", W + 95 * DAY + 600, "RRR", 90, 180)
TR = W + 100 * DAY
move(TR, "RRR", 100, "binance", "bybit", "r3")
move(W + 102 * DAY, "SSS", 50, "bybit", "binance", "x1")
trade("binance", "s9", W + 103 * DAY, "SSS", -50, 150)
trade("binance", "b9", W + 110 * DAY, "SSS", 50, 100)
move(W + 110 * DAY + 3600, "SSS", 50, "binance", "bybit", "x2")
c.commit()
c.close()

ISO = acct_norm.iso_day
DC = {}
for ex in ("bybit", "binance"):
    DC[(f"ex:{ex}:LLL", ISO(T1))] = 3.0
    DC[(f"ex:{ex}:MMM", ISO(W + 30 * DAY))] = 2.5
    DC[(f"ex:{ex}:NNN", ISO(W + 35 * DAY))] = 1.0
    DC[(f"ex:{ex}:OOO", ISO(T4))] = 5.0
    DC[(f"ex:{ex}:QQQ", ISO(W + 75 * DAY))] = 3.0
    DC[(f"ex:{ex}:RRR", ISO(W + 90 * DAY))] = 3.0
    DC[(f"ex:{ex}:RRR", ISO(W + 95 * DAY))] = 1.0
    DC[(f"ex:{ex}:SSS", ISO(W + 102 * DAY))] = 2.0


def fake_lookup(spec, iso, now=None, w=0.0, ask=True, old=False):
    v = DC.get((spec, iso))
    return (v, "ok") if v else (None, "pending")


fake_lookup._tj_test_mock = True
histcurve.DAYCLOSE.lookup = fake_lookup
px = {"LLL": 2.5, "MMM": 2.5, "NNN": 2.5, "OOO": 2.5}
json.dump({"usd": px, "usd_ts": {k: NOW for k in px}, "rate": 1400.0, "updated": NOW, "dex_usd": {}, "dex_ts": {}, "dex_res": {}, "dex_res_ts": {},
           "fx_basis": 1400.0, "ex_usd": {f"{e}:{k}": v for k, v in px.items() for e in ("bybit", "binance")},
           "ex_ts": {f"{e}:{k}": NOW for k in px for e in ("bybit", "binance")}}, open(web.SPOT_PATH, "w"))
web.pricing.PxCache.candle_usd = lambda self, sym, ms: None
web.pricing._gj = lambda url, timeout=10.0: None


def _d(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")


LOANS = [{"exchange": "bybit", "asset": "LLL", "from": _d(W + 5 * DAY), "to": _d(W + 22 * DAY)},
         {"exchange": "bybit", "asset": "MMM", "from": _d(W + 29 * DAY), "to": _d(W + 120 * DAY)},
         {"exchange": "binance", "asset": "NNN", "from": _d(W + 34 * DAY), "to": _d(W + 37 * DAY)},
         {"exchange": "bybit", "asset": "OOO", "from": _d(W + 39 * DAY), "to": _d(W + 47 * DAY)},
         {"exchange": "bybit", "asset": "PPP", "from": _d(W + 59 * DAY), "to": _d(W + 72 * DAY)},
         {"exchange": "bybit", "asset": "QQQ", "from": _d(W + 74 * DAY), "to": _d(W + 86 * DAY)},
         {"exchange": "bybit", "asset": "RRR", "from": _d(W + 89 * DAY), "to": _d(W + 101 * DAY)}]


def build(prefs, loans=LOANS):
    json.dump(dict({"chains": {}, "wallets": [], "backfill_months": 5}, **({"loan_short": loans} if loans is not None else {})),
              open(os.path.join(os.environ["TJ_BASE"], "config.json"), "w"))
    common.atomic_write_json(web.PREFS_PATH, dict({"plans": {}, "ignored": []}, **prefs))
    b = web.StateBuilder()
    b.skip_gen_check = True
    conn = dbm.open_db(common.DB_PATH, readonly=True)
    try:
        f = b._build(conn)["fields"]
    finally:
        conn.close()
    return f, (b._day_idx or {}).get("tax") or []


def rz(f, sym):
    return round(sum(float(p.get("realized") or 0) for p in (f.get("_positionsAll") or f.get("positions") or []) if p.get("sym") == sym), 2)


def unv(f, sym):
    return [p for p in f.get("pendings") or [] if str(p.get("key") or "").startswith("unv:") and str(p.get("sym") or p.get("s") or "") == sym]


def tax(rows, sym):
    return [r for r in rows if r.get("sym") == sym]


f, rows = build({})
l1 = tax(rows, "LLL")
rp = [r for r in l1 if str(r.get("ex") or "").startswith("바이빗 대출 상환")]
sl = [r for r in l1 if not str(r.get("ex") or "").startswith("바이빗 대출 상환")]
chk(rz(f, "LLL") == 200.0, "S1 실현 = 매도 대금 $400 − 되산 원가 $200 = $200(종전 = 0 · 원가 미확인 $400)", [rz(f, "LLL"), l1])
chk(not unv(f, "LLL"), "S1 원가 미확인 검토 행 없음", unv(f, "LLL"))
chk(len(sl) == 1 and abs(float(sl[0]["_acq"]) - 300) < 1e-6 and abs(float(sl[0]["_disp"]) - 400) < 1e-6 and sl[0]["ex"].endswith(FS_EX),
    "S1 매도 행 = 빌린 시각 시가 $3 × 100 = 취득 $300 · 양도 $400 · 추정 표기", sl)
chk(len(rp) == 1 and abs(float(rp[0]["_acq"]) - 200) < 1e-6 and abs(float(rp[0]["_disp"]) - 300) < 1e-6 and rp[0]["ex"].endswith(FS_EX)
    and rp[0]["sold"] == ISO(W + 20 * DAY + 3600 + 600),
    "S1 상환 행(바이빗 입금 날) = 되산 원가 $200 · 빌린 시각 시가 $300 · 추정 표기", rp)
pl = [p for p in (f.get("_positionsAll") or f.get("positions") or []) if p.get("sym") == "LLL" and float(p.get("qty") or 0) > 1e-9]
chk(not pl, "S1 끝 보유 = 원장(0) — 되산 코인이 유령 보유로 남지 않음", pl)
chk(rz(f, "MMM") == 0 and unv(f, "MMM") and not [r for r in tax(rows, "MMM") if "대출" in str(r.get("ex"))],
    "S2 끝까지 안 채워짐 = 종전(원가 미확인 · 대출 행 없음)", [rz(f, "MMM"), unv(f, "MMM"), tax(rows, "MMM")])
chk(not [r for r in tax(rows, "NNN") if "대출" in str(r.get("ex"))], "S3 6시간 안에 채워진 음수 = 대출 아님", tax(rows, "NNN"))
chk(rz(f, "OOO") == 100.0 and not unv(f, "OOO"), "S4 다른 거래소 보유 + 대출: 전부 처분 뒤 실현 합 = 처분 $390(180 + 상환 150 + 60) − 취득 $290(20 + 150 + 120) = $100",
    [rz(f, "OOO"), tax(rows, "OOO"), unv(f, "OOO")])
lost5 = [p for p in f.get("pendings") or [] if str(p.get("key") or "") == f"unvlost:{G['PPP']}"]
p5 = [p for p in (f.get("_positionsAll") or f.get("positions") or []) if p.get("sym") == "PPP" and float(p.get("qty") or 0) > 1e-9]
chk(rz(f, "PPP") == 0 and unv(f, "PPP") and lost5 and abs(float(lost5[0].get("usd") or 0) - 80) < 0.01 and not p5
    and not [r for r in tax(rows, "PPP") if "대출" in str(r.get("ex"))],
    "S5 시세 없는 대출 = 원가 미확인 매도 · 갚은 코인 원가 $80 = '창 밖 처분' 검토 행 · 남는 보유 없음 · 대출 행 없음", [rz(f, "PPP"), lost5, p5])
q6 = tax(rows, "QQQ")
rp6 = [r for r in q6 if "대출 상환" in str(r.get("ex"))]
pq = [p for p in (f.get("_positionsAll") or f.get("positions") or []) if p.get("sym") == "QQQ"]
chk(rz(f, "QQQ") == 199.8 and len(rp6) == 1 and abs(float(rp6[0]["_acq"]) - 200.2) < 1e-6,
    "S6 (ex441 ①) 같은 거래소 매수 상환 + 수수료 0.2 USDT → 상환 취득가 $200.2 · 실현 $199.8(수수료 전 정산이면 $200)", [rz(f, "QQQ"), q6])
ev6 = [e for p in pq for e in (p.get("events") or []) if "대출 상환" in str(e.get("d"))]
hid6 = [e for e in (f.get("extraEventsHidden") or []) if "대출 상환" in str(e.get("d"))]
chk(len(ev6) == 1 and not hid6, "S6 (ex448) 상환 기록 = 카드에 보임(수수료 0.2 USDT 기준 '소액' 숨김 아님)", [ev6, hid6])
chk(pq and all(float(p.get("held") or 0) <= 1e-9 for p in pq) and abs(sum(float(p.get("realized") or 0) for p in pq) - 199.8) < 0.005,
    "S6 카드 = 보유 0 · 실현 $199.8(수수료까지 상환 원가)", [(p.get("held"), p.get("realized"), p.get("status")) for p in pq])
dR = ISO(TR + 600)
fsr = f.get("fsRealByDate") or {}
r7 = [r for r in tax(rows, "RRR") if "대출 상환" in str(r.get("ex"))]
chk(len(r7) == 1 and abs(float(r7[0]["_acq"]) - 190) < 1e-6 and r7[0]["ex"].endswith(FS_EX) and dR in fsr and abs(fsr[dR][0] - 110) < 0.01,
    "S7 (ex441 ②) 갚은 코인 원가 $190(최초 인식 $10 + 매수 $180) · 상환 실현 $110 = 그날 '이 중 추정' $110 한 번(부분 $20·중복 $130 아님)", [r7, fsr.get(dR)])
chk(rz(f, "SSS") == 0 and unv(f, "SSS") and not [r for r in tax(rows, "SSS") if "대출" in str(r.get("ex"))],
    "S8 (ex441 ③) 설정에 없는 자산의 같은 모양 = 대출 아님(종전 원가 미확인)", [rz(f, "SSS"), tax(rows, "SSS")])
fn, rowsn = build({}, loans=None)
chk(not [r for r in rowsn if "대출" in str(r.get("ex"))] and rz(fn, "LLL") == 0 and unv(fn, "LLL"),
    "S8 설정 loan_short 없음 = B′ 꺼짐(전부 종전)", [rz(fn, "LLL"), tax(rowsn, "LLL")])
f0, rows0 = build({"first_seen_px": False})
chk(not [r for r in rows0 if "대출" in str(r.get("ex"))] and rz(f0, "LLL") == 0 and unv(f0, "LLL"),
    "최초 인식 시가 끔 = 종전(대출 정산 없음 · 원가 미확인)", [rz(f0, "LLL"), tax(rows0, "LLL")])

T.finish()
sys.exit(1 if T.FAILS else 0)
