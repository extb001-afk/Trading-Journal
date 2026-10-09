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
import db as dbm
import netpace
import web

chk = T.chk
for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker"):
    if hasattr(web.StateBuilder, _m):
        setattr(web.StateBuilder, _m, lambda self: None)
netpace.wait = lambda url, now=None, sleep=None: None
KST = timezone(timedelta(hours=9))
NOW = int(time.time())
D0 = int((datetime.fromtimestamp(NOW, KST).replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=40)).timestamp())
DAY = 86400
FEE = Decimal("0.0005")

c = dbm.open_db(common.DB_PATH)
A = {}
for ex, sym in (("upbit", "USDT"), ("bithumb", "USDT"), ("bithumb", "KRW"), ("bithumb", "BTC")):
    if not c.execute("SELECT 1 FROM asset_groups WHERE name=?", (sym,)).fetchone():
        c.execute("INSERT INTO asset_groups (name) VALUES (?)", (sym,))
    gid = c.execute("SELECT group_id FROM asset_groups WHERE name=?", (sym,)).fetchone()[0]
    c.execute("INSERT INTO assets (kind, chain, address, symbol, decimals, confirmed, group_id) VALUES ('exchange_currency',NULL,?,?,8,1,?)", (ex + ":" + sym, sym, gid))
    A[(ex, sym)] = c.execute("SELECT last_insert_rowid()").fetchone()[0]


def post(ns, sid, leg, t, ex, sym, qty, usd, krw, lk, evk):
    c.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event,"
              " classifier_ver) VALUES ('exchange',?,?,?,?,?,?,?,?,?,?,?,4)",
              (ns, sid, leg, t, A[(ex, sym)], "exchange:" + ex, str(int(Decimal(str(qty)) * 10 ** 8)), repr(float(usd)), None if krw is None else str(krw), lk, evk))


b1, s1 = Decimal(13_000_000) * (1 + FEE), Decimal(14_500_000) * (1 - FEE)
post("upbit:order", "S1B", 0, D0, "upbit", "USDT", "10000", float(b1) / 1300, b1, "acq", "EX_BUY")
post("upbit:order", "S1S", 0, D0 + 10 * DAY, "upbit", "USDT", "-10000", float(s1) / 1450, s1, "disp", "EX_SELL")
b2, s2 = Decimal(1_450_000) * (1 + FEE), Decimal(1_300_000) * (1 - FEE)
post("upbit:order", "S2B", 0, D0 + 11 * DAY, "upbit", "USDT", "1000", float(b2) / 1450, b2, "acq", "EX_BUY")
post("upbit:order", "S2S", 0, D0 + 12 * DAY, "upbit", "USDT", "-1000", float(s2) / 1300, s2, "disp", "EX_SELL")
post("bithumb:trade", "S3A", 0, D0 + 14 * DAY, "bithumb", "USDT", "2000", 2000, 2_600_000, "acq", "EXF_BUY")
post("bithumb:trade", "S3A", 1, D0 + 14 * DAY, "bithumb", "KRW", "-2600000", 2000, 2_600_000, "disp", "EXF_SELL")
post("bithumb:trade", "S3B", 0, D0 + 15 * DAY, "bithumb", "BTC", "0.02", 2000, 2_800_000, "acq", "EXF_BUY")
post("bithumb:trade", "S3B", 1, D0 + 15 * DAY, "bithumb", "USDT", "-2000", 2000, 2_800_000, "disp", "EXF_SELL")
post("bithumb:trade", "S3C", 0, D0 + 16 * DAY, "bithumb", "BTC", "-0.02", 2300, 3_220_000, "disp", "EXF_SELL")
post("bithumb:trade", "S3C", 1, D0 + 16 * DAY, "bithumb", "KRW", "3220000", 2300, 3_220_000, "acq", "EXF_BUY")
post("upbit:deposit", "S5D", 0, D0 + 20 * DAY, "upbit", "USDT", "9000", 9000, None, "move_in", "EX_DEPOSIT")
post("upbit:order", "S5B", 0, D0 + 20 * DAY + 600, "upbit", "USDT", "1000", 1000, 1_300_000, "acq", "EX_BUY")
post("upbit:order", "S5S", 0, D0 + 21 * DAY, "upbit", "USDT", "-10000", 10000, 15_000_000, "disp", "EX_SELL")
c.commit()
c.close()
px = {"USDT": 1.0, "BTC": 115000.0, "KRW": 1 / 1400.0}
json.dump({"usd": px, "usd_ts": {k: NOW for k in px}, "rate": 1400.0, "updated": NOW, "dex_usd": {}, "dex_ts": {}, "dex_res": {}, "dex_res_ts": {},
           "fx_basis": 1400.0, "ex_usd": {f"{e}:{k}": v for k, v in px.items() for e in ("upbit", "bithumb")},
           "ex_ts": {f"{e}:{k}": NOW for k in px for e in ("upbit", "bithumb")}}, open(web.SPOT_PATH, "w"))
web.pricing.PxCache.candle_usd = lambda self, sym, ms: px.get(str(sym).upper())
web.pricing._gj = lambda url, timeout=10.0: None
common.atomic_write_json(web.PREFS_PATH, {"plans": {}, "ignored": []})
b = web.StateBuilder()
b.skip_gen_check = True
conn = dbm.open_db(common.DB_PATH, readonly=True)
try:
    f = b._build(conn)["fields"]
finally:
    conn.close()
rows = (b._day_idx or {}).get("tax") or []


def krw_pnl(r):
    rt = float(r["rate"])
    ak = r.get("_akr", r.get("akr"))
    return float(r["_disp"]) * rt - (float(ak) if ak is not None else float(r["_acq"]) * rt) - float(r.get("_fee", r.get("fee")) or 0) * rt


usl = sorted([r for r in rows if r.get("sym") == "USDT"], key=lambda r: str(r["sold"]))
us = {}
for r in usl:
    us.setdefault(round(float(r["qty"])), r)
chk(10000 in us and abs(krw_pnl(us[10000]) - 1_486_250) < 2, "S1 ₩1,300 매수 → ₩1,450 매도 = 명세 원화 +₩1,486,250", us.get(10000))
chk(1000 in us and abs(krw_pnl(us[1000]) + 151_375) < 2, "S2 ₩1,450 매수 → ₩1,300 매도 = 명세 원화 −₩151,375", us.get(1000))
chk(2000 in us and abs(krw_pnl(us[2000]) - 200_000) < 2, "S3 코인 매수 대금 USDT 2,000(1,300 → 1,400) = 원화 환차 +₩200,000", us.get(2000))
bt = [r for r in rows if r.get("sym") == "BTC"]
chk(len(bt) == 1 and abs(float(bt[0].get("akr") or 0) - 2_800_000) < 2 and abs(krw_pnl(bt[0]) - 420_000) < 2,
    "S3 산 코인 원화 취득가 = 그때 USDT 원화 시가 ₩2,800,000(BTC 손익 +₩420,000 — USDT 환차와 겹치지 않음)", bt)
chk(all(r.get("tk") == "st" for r in usl) and not [r for r in rows if r.get("sym") != "USDT" and r.get("tk")], "S4 스테이블 처분 행만 tk = st", rows)
ym = str(us[10000]["sold"])[:7] if 10000 in us else None
sf = f.get("taxStableFx") or {}
tot = [sum(v[i] for v in sf.values()) for i in range(5)] if sf else []
chk(len(tot) == 5 and tot[0] == 4 and tot[1] == 4 and tot[3] == 3 and abs(tot[2] - (1_500_750 + 200_000 - 150_075 + 200_000)) <= 3,
    "S4 taxStableFx = 4행 · 원화 매도 3행 · 원화 환차 합(₩1,500,750 + ₩200,000 − ₩150,075 + ₩200,000)", sf)
rk = f.get("realizedKrwByDate") or {}
d1 = str(us[10000]["sold"]) if 10000 in us else ""
chk(d1 in rk and abs(rk[d1] + 14_500) < 2, "S4 헤더·달력 원화 실현은 그대로(매도 시각 환율 −₩14,500 — 명세만 취득 시점 원화)", rk.get(d1))
summ = [x for x in f.get("taxSummary") or [] if x[1] == "USDT"]
chk(summ and all(len(x) == 16 and x[15] == "st" for x in summ) and abs(sum(x[13] for x in summ) - sum(krw_pnl(r) for r in usl)) < 3,
    "S4 요약 15열 = st · 13열(명세 원화 손익) 합 = 행 합", summ)
chk(not [r for r in f.get("taxRows") or [] if any(k.startswith("_") for k in r)], "S4 응답 명세 행에 '_' 내부 칸 없음")
chk(10000 in us and abs(float(us[10000].get("akr") or 0) - 13_006_500) < 2, "S1 행 = 첫 1만 개(원화 매수 ₩13,006,500)", us.get(10000))
s5 = [r for r in usl if round(float(r["qty"])) == 10000 and r is not us.get(10000)]
chk(len(s5) == 1 and abs(float(s5[0].get("akr") or 0) - 14_800_000) < 2 and abs(krw_pnl(s5[0]) - 200_000) < 2,
    "S5 액면 9,000 + 원화 매수 1,000 → 전량 ₩1,500 = 원화 취득 ₩14,800,000 · +₩200,000(새 매수 환율을 액면 몫에 덮지 않음)", s5)
T.finish()
