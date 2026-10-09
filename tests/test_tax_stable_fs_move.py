#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import hashlib
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

FS_EX = getattr(web, "FS_EX", " · 최초 인식 시가")
chk = T.chk
for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker"):
    if hasattr(web.StateBuilder, _m):
        setattr(web.StateBuilder, _m, lambda self: None)
netpace.wait = lambda url, now=None, sleep=None: None
KST = timezone(timedelta(hours=9))
NOW = int(time.time())
D0 = int((datetime.fromtimestamp(NOW, KST).replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=40)).timestamp())
DAY = 86400
TDEP = D0 + DAY
TXM = "0x" + hashlib.sha256(b"m1-move").hexdigest()

c = dbm.open_db(common.DB_PATH)
A = {}
for i, (ex, sym) in enumerate((("upbit", "USDT"), ("binance", "USDT"), ("upbit", "USDC"))):
    c.execute("INSERT INTO asset_groups (name) VALUES (?)", (f"{sym}#{901 + i}",))
    gid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.execute("INSERT INTO assets (kind, chain, address, symbol, decimals, confirmed, group_id) VALUES ('exchange_currency',NULL,?,?,8,1,?)",
              (f"{ex}:{sym.lower()}", sym, gid))
    A[(ex, sym)] = c.execute("SELECT last_insert_rowid()").fetchone()[0]


def post(ns, sid, t, ex, sym, qty, usd, krw, lk, evk, leg=0):
    c.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event,"
              " classifier_ver) VALUES ('exchange',?,?,?,?,?,?,?,?,?,?,?,4)",
              (ns, sid, leg, t, A[(ex, sym)], "exchange:" + ex, str(int(Decimal(str(qty)) * 10 ** 8)), None if usd is None else repr(float(usd)),
               None if krw is None else str(krw), lk, evk))


def raw(ex, kind, uuid, payload, t):
    c.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES (?,?,?,1,?,?)", (ex, kind, uuid, json.dumps(payload), t))


post("upbit:order", "M1B", D0, "upbit", "USDT", 10000, 10000, 13_000_000, "acq", "EX_BUY")
post("binance:deposit", "M1D", TDEP, "binance", "USDT", 10000, 10000, None, "move_in", "EXF_DEPOSIT")
post("binance:withdraw", "M1W", D0 + 2 * DAY, "binance", "USDT", -10000, None, None, "move_out", "EXF_WITHDRAW")
raw("binance", "withdraw", "M1W", {"txid": TXM, "state": "DONE", "currency": "USDT", "amount": "10000", "fee": "0"}, D0 + 2 * DAY)
post("upbit:deposit", "M1U", D0 + 2 * DAY + 600, "upbit", "USDT", 10000, 10000, None, "move_in", "EX_DEPOSIT")
raw("upbit", "deposit", "M1U", {"txid": TXM, "state": "ACCEPTED", "currency": "USDT", "amount": "10000",
                                "created_at": datetime.fromtimestamp(D0 + 2 * DAY + 600, KST).isoformat()}, D0 + 2 * DAY + 600)
post("upbit:order", "M1S", D0 + 3 * DAY, "upbit", "USDT", -15000, 15000, 21_750_000, "disp", "EX_SELL")
post("upbit:order", "M3S", D0 + 4 * DAY, "upbit", "USDT", -5000, 5000, 7_250_000, "disp", "EX_SELL")
post("upbit:order", "M2B", D0, "upbit", "USDC", 10000, 10000, 13_000_000, "acq", "EX_BUY")
post("upbit:deposit", "M2D", TDEP, "upbit", "USDC", 10000, 10000, None, "move_in", "EX_DEPOSIT")
post("upbit:order", "M2S", D0 + 3 * DAY, "upbit", "USDC", -15000, 15000, 21_750_000, "disp", "EX_SELL")
c.commit()
c.close()
px = {"USDT": 1.0, "USDC": 1.0}
json.dump({"usd": px, "usd_ts": {k: NOW for k in px}, "rate": 1400.0, "updated": NOW, "dex_usd": {}, "dex_ts": {}, "dex_res": {}, "dex_res_ts": {},
           "fx_basis": 1400.0, "ex_usd": {f"{e}:{k}": v for k, v in px.items() for e in ("upbit", "binance")},
           "ex_ts": {f"{e}:{k}": NOW for k in px for e in ("upbit", "binance")}}, open(web.SPOT_PATH, "w"))
web.pricing.PxCache.candle_usd = lambda self, sym, ms: px.get(str(sym).upper())
web.pricing._gj = lambda url, timeout=10.0: None


def build(prefs):
    common.atomic_write_json(web.PREFS_PATH, dict({"plans": {}, "ignored": []}, **prefs))
    b = web.StateBuilder()
    b.skip_gen_check = True
    b.px.d.setdefault("fx", {})[str((TDEP * 1000 // 60_000) * 60_000)] = 1380.0
    conn = dbm.open_db(common.DB_PATH, readonly=True)
    try:
        f = b._build(conn)["fields"]
    finally:
        conn.close()
    return f, (b._day_idx or {}).get("tax") or []


def row(rows, sym, qty):
    r9 = [r for r in rows if r.get("sym") == sym and abs(float(r.get("_qty") or r.get("qty") or 0) - qty) < 1e-6]
    return r9[0] if len(r9) == 1 else None


def sfx(r):
    return None if r is None or r.get("_sfx") is None else round(float(r["_sfx"]))


f0, rows0 = build({"first_seen_px": False})
r0 = row(rows0, "USDT", 15000)
chk(r0 is not None and sfx(r0) == 1_125_000 and not str(r0.get("ex") or "").endswith(FS_EX),
    "M1 끔 = 산 몫 7,500 × ₩150 = +₩1,125,000 · 추정 표기 없음(종전 그대로)", r0)
f1, rows1 = build({})
r1 = row(rows1, "USDT", 15000)
chk(r1 is not None and sfx(r1) == 1_650_000, "M1 켬 = 이동평균 ₩1,340 → 15,000 × ₩110 = +₩1,650,000(액면 몫 유입 시각 환율 · 이중 계상 없음)", r1)
chk(r1 is not None and str(r1.get("ex") or "").endswith(FS_EX), "M1 켬 = 이동을 거쳐도 명세 줄 이름 끝 ' · 최초 인식 시가'", r1)
q1 = row(rows1, "USDC", 15000)
chk(q1 is not None and sfx(q1) == 1_650_000 and str(q1.get("ex") or "").endswith(FS_EX), "M2 대조: 업비트 직접 액면 입금 = 같은 +₩1,650,000 · 같은 표기", q1)
r3 = row(rows1, "USDT", 5000)
chk(r3 is not None and sfx(r3) == 550_000 and str(r3.get("ex") or "").endswith(FS_EX), "M3 남은 5천 = 남은 추정 몫 표기 · +₩550,000(₩1,340 기준)", r3)
r30 = row(rows0, "USDT", 5000)
chk(r30 is not None and sfx(r30) == 375_000 and not str(r30.get("ex") or "").endswith(FS_EX), "M3 끔 = 산 몫 2,500 × ₩150 = +₩375,000", r30)
d3 = datetime.fromtimestamp(D0 + 3 * DAY, KST).strftime("%Y-%m-%d")
k1, k0 = (f1.get("realizedKrwByDate") or {}).get(d3), (f0.get("realizedKrwByDate") or {}).get(d3)
chk(k1 is not None and k0 is not None and round(float(k1)) == round(float(k0)), "헤더·달력 원화 실현은 켬·끔 같음(스테이블 환차는 명세만)", [k1, k0])
T.finish()
