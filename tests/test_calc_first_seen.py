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
R = NOW - 12 * DAY

c = dbm.open_db(common.DB_PATH)
A, G = {}, {}
for sym in ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "BTC", "USDT", "RRR"):
    c.execute("INSERT INTO asset_groups (name) VALUES (?)", (sym,))
    G[sym] = c.execute("SELECT group_id FROM asset_groups WHERE name=?", (sym,)).fetchone()[0]
    c.execute("INSERT INTO assets (kind, chain, address, symbol, decimals, confirmed, group_id) VALUES ('exchange_currency',NULL,?,?,8,1,?)",
              ("upbit:" + sym, sym, G[sym]))
    A[sym] = c.execute("SELECT last_insert_rowid()").fetchone()[0]
for sym in ("GGG", "USDC", "HHH"):
    c.execute("INSERT INTO asset_groups (name) VALUES (?)", (sym,))
    G[sym] = c.execute("SELECT group_id FROM asset_groups WHERE name=?", (sym,)).fetchone()[0]
for key, sym, gid in (("bn:GGG", "GGG", G["GGG"]), ("bn:USDC", "USDC", G["USDC"]), ("bn:HHH", "HHH", G["HHH"])):
    c.execute("INSERT INTO assets (kind, chain, address, symbol, decimals, confirmed, group_id) VALUES ('exchange_currency',NULL,?,?,8,1,?)",
              ("binance:" + sym, sym, gid))
    A[key] = c.execute("SELECT last_insert_rowid()").fetchone()[0]


def post(ns, sid, t, sym, qty, usd, krw, lk, evk, leg=0, loc="exchange:upbit"):
    c.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event,"
              " classifier_ver) VALUES ('exchange',?,?,?,?,?,?,?,?,?,?,?,4)",
              (ns, sid, leg, t, A[sym], loc, str(int(Decimal(str(qty)) * 10 ** 8)), None if usd is None else repr(float(usd)),
               None if krw is None else str(krw), lk, evk))


def sell(sid, t, sym, qty, usd):
    post("upbit:order", sid, t, sym, -Decimal(str(qty)), usd, int(usd * 1400), "disp", "EX_SELL")


post("upbit:recon", "recon:AAA", W, "AAA", 100, None, None, "opening", "EX_ADJUST")
sell("F1S", W + 10 * DAY, "AAA", 100, 500)
post("upbit:deposit", "F2D", W + 2 * DAY, "BBB", 10, None, None, "move_in", "EX_DEPOSIT")
sell("F2S", W + 6 * DAY, "BBB", 11, 88)
post("upbit:deposit", "F4D", W + 1 * DAY, "CCC", 5, None, None, "move_in", "EX_DEPOSIT")
sell("F4S", W + 6 * DAY, "CCC", 5, 40)
post("upbit:deposit", "F5D", W + 1 * DAY, "DDD", 10, None, None, "move_in", "EX_DEPOSIT")
sell("F5S", W + 3 * DAY, "DDD", 10, 50)
post("upbit:order", "F10B", W + 1 * DAY, "EEE", 10, 10, 14000, "acq", "EX_BUY")
post("upbit:deposit", "F10D", W + 1 * DAY + 600, "EEE", 10, None, None, "move_in", "EX_DEPOSIT")
sell("F10S", W + 4 * DAY, "EEE", 20, 80)
post("upbit:deposit", "F6D", W + 1 * DAY, "FFF", 10, None, None, "move_in", "EX_DEPOSIT")
sell("F6S", W + 1 * DAY + 7200, "FFF", 10, 30)
T7 = W + 1 * DAY + 3600
post("upbit:deposit", "F7D", T7, "BTC", "0.1", None, None, "move_in", "EX_DEPOSIT")
sell("F7S", W + 9 * DAY, "BTC", "0.1", 7000)
T8 = W + 1 * DAY + 1800
post("upbit:deposit", "F8D", T8, "USDT", 1000, 1000, None, "move_in", "EX_DEPOSIT")
post("upbit:order", "F8S", W + 8 * DAY, "USDT", -1000, 1000, 1_450_000, "disp", "EX_SELL")
post("upbit:deposit", "F11D", R, "RRR", 3, None, None, "move_in", "EX_DEPOSIT")
post("binance:deposit", "F12D", W + 1 * DAY, "bn:GGG", 10, None, None, "move_in", "EXF_DEPOSIT", loc="exchange:binance")
post("binance:trade", "F12T", W + 3 * DAY, "bn:GGG", -10, 100, None, "disp", "EXF_SELL", loc="exchange:binance")
post("binance:trade", "F12T", W + 3 * DAY, "bn:USDC", 100, 100, None, "acq", "EXF_BUY", leg=1, loc="exchange:binance")
post("binance:trade", "F12T", W + 3 * DAY, "bn:USDC", -1, None, None, "gas", "EXF_FEE", leg=2, loc="exchange:binance")
post("binance:deposit", "F13D", NOW - 170 * DAY, "bn:HHH", 1, None, None, "move_in", "EXF_DEPOSIT", loc="exchange:binance")
post("upbit:deposit", "F3D", W + 5 * DAY, "BBB", 1, None, None, "move_in", "EX_DEPOSIT")
c.commit()
c.close()

ISO = acct_norm.iso_day
DC = {("ex:upbit:AAA", ISO(W)): 2.0, ("ex:upbit:AAA", ISO(W + 2 * DAY)): 3.0, ("ex:upbit:AAA", ISO(NOW)): 9.9,
      ("ex:upbit:BBB", ISO(W + 2 * DAY)): 5.0, ("ex:upbit:BBB", ISO(W + 5 * DAY)): 6.0, ("ex:upbit:BBB", ISO(W + 6 * DAY)): 7.0,
      ("ex:upbit:DDD", ISO(W + DAY)): 4.0, ("ex:upbit:EEE", ISO(W + DAY)): 3.0, ("ex:upbit:FFF", ISO(W + DAY)): 2.0,
      ("sym:BTC", ISO(T7)): 60000.0, ("ex:binance:GGG", ISO(W + DAY)): 5.0}
CALLS = []


def fake_lookup(spec, iso, now=None, w=0.0, ask=True, old=False):
    CALLS.append((spec, iso, ask, old))
    v = DC.get((spec, iso))
    return (v, "ok") if v else (None, "pending")


fake_lookup._tj_test_mock = True
histcurve.DAYCLOSE.lookup = fake_lookup
px = {"AAA": 9.9, "BBB": 9.9, "CCC": 9.9, "DDD": 9.9, "EEE": 9.9, "FFF": 9.9, "BTC": 70000.0, "USDT": 1.0, "RRR": 1.0}
json.dump({"usd": px, "usd_ts": {k: NOW for k in px}, "rate": 1400.0, "updated": NOW, "dex_usd": {}, "dex_ts": {}, "dex_res": {}, "dex_res_ts": {},
           "fx_basis": 1400.0, "ex_usd": {f"upbit:{k}": v for k, v in px.items()}, "ex_ts": {f"upbit:{k}": NOW for k in px}}, open(web.SPOT_PATH, "w"))
web.pricing.PxCache.candle_usd = lambda self, sym, ms: None
web.pricing._gj = lambda url, timeout=10.0: None


def build(prefs):
    common.atomic_write_json(web.PREFS_PATH, dict({"plans": {}, "ignored": []}, **prefs))
    del CALLS[:]
    b = web.StateBuilder()
    b.skip_gen_check = True
    m7 = (T7 * 1000 // 60_000) * 60_000
    b.px.d.setdefault("candle", {})[f"BTC:{m7}"] = 50000.0
    b.px.d.setdefault("fx", {})[str((T8 * 1000 // 60_000) * 60_000)] = 1300.0
    conn = dbm.open_db(common.DB_PATH, readonly=True)
    try:
        f = b._build(conn)["fields"]
    finally:
        conn.close()
    return f, (b._day_idx or {}).get("tax") or []


def by_sym(rows, sym):
    return [r for r in rows if r.get("sym") == sym]


def rz(f, sym):
    return round(sum(float(p.get("realized") or 0) for p in f.get("positions") or [] if p.get("sym") == sym), 2)


def unv_syms(f):
    return {str(p.get("sym") or p.get("s") or "") for p in f.get("pendings") or [] if str(p.get("key") or "").startswith("unv:")}


tod = int(time.time())
f, rows = build({"cost_overrides": {f"g{G['DDD']}": {"mode": "unit", "unit": 1.0}},
                 "cost_breakeven": {f"g{G['FFF']}": {"until": W + 1 * DAY + 7200 + 60, "qty": "10"}}})
fs = f.get("firstSeen") or {}
chk(fs.get("on") is True and fs.get("eff") is True, "기본 = 켬(설정 없음)", fs)
a = by_sym(rows, "AAA")
chk(len(a) == 1 and abs(float(a[0]["_acq"]) - 200) < 1e-6 and a[0]["ex"] == "업비트" + FS_EX,
    "F1 창 시작 기초 잔고 100 AAA → 창 시작 날 가격 $2(오늘 $9.9·3일째 $3 아님) · 명세 '최초 인식 시가'", a)
chk(rz(f, "AAA") == 300.0, "F1 실현 = $500 − $200 = $300", rz(f, "AAA"))
fsr = f.get("fsRealByDate") or {}
d1 = ISO(W + 10 * DAY)
chk(d1 in fsr and abs(fsr[d1][0] - 300) < 0.01 and abs(fsr[d1][1] - 300 * 1400) < 2, "F1 머리 '이 중 추정' = 그날 +$300 · 원화 = 매도 시각 환율", fsr.get(d1))
pa = [p for p in f.get("positions") or [] if p.get("sym") == "AAA"]
chk(pa and (pa[0].get("fsEst") or {}).get("cost") == 200 and (pa[0].get("fsEst") or {}).get("real") == 300, "F1 카드 fsEst = 추정 원가 $200 · 그 실현 $300", pa[:1])
bb = by_sym(rows, "BBB")
chk(len(bb) == 1 and abs(float(bb[0]["_acq"]) - 56) < 1e-6, "F2·F3 BBB 원가 = 3일째 10개 × $5 + 5일째(나중에 수집) 1개 × $6 = $56(매도일·오늘 가격 아님)", bb)
chk(rz(f, "BBB") == 32.0, "F2·F3 실현 = $88 − $56 = $32", rz(f, "BBB"))
chk(not by_sym(rows, "CCC") and rz(f, "CCC") == 0 and "CCC" in unv_syms(f), "F4 그날 시가 없음 → 원가 미확인 그대로(실현 0 · 검토 행)", sorted(unv_syms(f)))
chk(fs.get("miss", 0) >= 1, "F4 firstSeen.miss ≥ 1", fs)
dd = by_sym(rows, "DDD")
chk(len(dd) == 1 and abs(float(dd[0]["_acq"]) - 10) < 1e-6 and not dd[0]["ex"].endswith(FS_EX) and rz(f, "DDD") == 40.0,
    "F5 원가 지정 개당 $1 이 먼저(최초 인식 시가 $4 아님) · 추정 표기 없음 · 실현 $40", dd)
ff = by_sym(rows, "FFF")
chk(rz(f, "FFF") == 0 and all("매수가=매도가" in r["ex"] for r in ff) and ff, "F6 손익 0 처리가 먼저(실현 0 · 매수가=매도가 행)", ff)
bt = by_sym(rows, "BTC")
chk(len(bt) == 1 and abs(float(bt[0]["_acq"]) - 5000) < 1e-6 and rz(f, "BTC") == 2000.0,
    "F7 대표 코인 = 그 분 캐시 시세 $50,000(그날 마감가 $60,000 보다 먼저) → 원가 $5,000 · 실현 $2,000", bt)
us = by_sym(rows, "USDT")
chk(len(us) == 1 and abs(float(us[0].get("_akr") or 0) - 1_300_000) < 2 and us[0]["ex"].endswith(FS_EX) and us[0].get("tk") == "st",
    "F8 스테이블 액면 입금 → 명세 원화 취득 = 입금 그 분 환율 ₩1,300 × 1,000 · 추정 표기", us)
chk(rz(f, "USDT") == 0, "F8 스테이블 USD 실현은 그대로 0(원화 명세만)", rz(f, "USDT"))
calls = {(s9, i9): a9 for s9, i9, a9, _o9 in CALLS}
wo = histcurve.DAYCLOSE.want_old
chk(calls.get(("ex:upbit:RRR", ISO(R))) is True and calls.get(("ex:upbit:CCC", ISO(W + DAY))) is False
    and ISO(W + DAY) in (wo.get("ex:upbit:CCC") or {}).get("days", ()),
    "F11 최근 날 = 30일 곡선 요청 · 옛날 날(원장 창 안) = 빌드 끝 옛날 요청(ask_old — 남는 몫에서 받음)", [sorted((k, v) for k, v in calls.items() if "CCC" in k[0] or "RRR" in k[0]), wo.get("ex:upbit:CCC")])
chk(calls.get(("ex:binance:HHH", ISO(NOW - 170 * DAY))) is False and "ex:binance:HHH" not in wo, "F13 원장 창 시작 밖 날 = 요청 안 남김", [(k, v) for k, v in calls.items() if "HHH" in k[0]])
chk(abs(sum(v[0] for v in fsr.values()) - float(fs.get("real") or 0)) < 0.05, "머리 날짜별 합 = firstSeen.real", [fsr, fs.get("real")])
gg = by_sym(rows, "GGG")
d12 = ISO(W + 3 * DAY)
chk(len(gg) == 1 and abs(float(gg[0].get("_fee", gg[0].get("fee")) or 0) - 1) < 1e-6 and rz(f, "GGG") == 49.0 and abs(fsr.get(d12, [0])[0] - 49) < 0.01,
    "F12(fs322 ①) 체결 수수료 1 USDT 뒤 실제 실현 $49 = 머리 '이 중 추정' $49(수수료 전 $50 아님)", [gg, rz(f, "GGG"), fsr.get(d12)])
pg = [p for p in f.get("positions") or [] if p.get("sym") == "GGG"]
chk(pg and (pg[0].get("fsEst") or {}).get("real") == 49.0, "F12 카드 fsEst.real = $49(수수료 뒤)", pg[:1])
chk(not [r for r in f.get("taxRows") or [] if any(k.startswith("_") for k in r)], "응답 명세 행에 '_' 내부 칸 없음")
chk(int(time.time()) - tod < 600, "빌드 시간 정상")

f0, rows0 = build({"first_seen_px": False})
fs0 = f0.get("firstSeen") or {}
chk(fs0.get("on") is False and fs0.get("n") == 0 and not f0.get("fsRealByDate"), "F9 끔 = 매긴 유입 0 · 머리 '이 중 추정' 없음", fs0)
chk(rz(f0, "AAA") == 0 and rz(f0, "BBB") == 0 and {"AAA", "BBB"} <= unv_syms(f0), "F9 끔 = AAA·BBB 원가 미확인(실현 0 · 검토 행)", sorted(unv_syms(f0)))
chk(not [r for r in rows0 if str(r.get("ex") or "").endswith(FS_EX)], "F9 끔 = 명세 추정 표기 0")
u0 = by_sym(rows0, "USDT")
chk(len(u0) == 1 and u0[0].get("_akr") is None and u0[0].get("_sfx") is None, "F9 끔 = 스테이블 원화 원가 기록 없음 → 처분 시각 환율(환차 0 — 종전)", u0)
chk(not [p for p in f0.get("positions") or [] if p.get("fsEst")], "F9 끔 = 카드 fsEst 없음")

f2, rows2 = build({"fallback_avg": True})
fs2 = f2.get("firstSeen") or {}
chk(fs2.get("on") is True and fs2.get("eff") is False and fs2.get("n") == 0, "F10 평균가 대체 켬 = 최초 인식 시가 쉼(eff false · 매긴 유입 0)", fs2)
rfb = round(sum(float(p.get("realizedFb") or 0) for p in f2.get("positions") or [] if p.get("sym") == "EEE"), 2)
chk(rz(f2, "EEE") == 30.0 and rfb == 30.0, "F10 EEE = 매수분 실현 $30 + 평균가 대체 실현(평균가 $1 × 10개 몫) $30", [rz(f2, "EEE"), rfb])
chk(not [r for r in rows2 if str(r.get("ex") or "").endswith(FS_EX) and r.get("tk") != "st"], "F10 평균가 대체 켬 = 코인 명세 추정(최초 인식 시가) 표기 0")
chk(rz(f, "EEE") == 40.0, "F10 (켬·평균가 대체 끔) EEE = 최초 인식 시가 $3 → 원가 $40 · 실현 $40", rz(f, "EEE"))
u2 = by_sym(rows2, "USDT")
chk(len(u2) == 1 and abs(float(u2[0].get("_akr") or 0) - 1_300_000) < 2, "F10 스테이블 원화 원가(평균가 대체와 무관)는 그대로 켬", u2)
T.finish()
