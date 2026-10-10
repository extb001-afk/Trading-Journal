#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import copy
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import common
import xparts

json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(os.environ["TJ_BASE"], "config.json"), "w"))
import db as dbm
import netpace
import web

chk = T.chk
for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker"):
    if hasattr(web.StateBuilder, _m):
        setattr(web.StateBuilder, _m, lambda self: None)
netpace.wait = lambda url, now=None, sleep=None: None
S = common.STATE_DIR
FX = 1400.0


def xv_sum(xv):
    p = xv["p"]
    k = sum(p[k][0] for k in ("ku", "kb") if k in p)
    return k / xv["fx"] + (p["rest"][0] if "rest" in p else 0.0) + sum((xv.get("ubv") or {}).values())


NOW = int(time.time())
c = dbm.open_db(common.DB_PATH)
c.execute("INSERT INTO asset_groups (name) VALUES ('USDT')")
gid_u = c.execute("SELECT group_id FROM asset_groups WHERE name='USDT'").fetchone()[0]
c.execute("INSERT INTO assets (kind, chain, address, symbol, decimals, confirmed, group_id) VALUES ('exchange_currency',NULL,'bithumb:USDT','USDT',8,1,?)", (gid_u,))
aid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
c.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event,"
          " classifier_ver) VALUES ('exchange','bithumb:trade','A1',0,?,?,'exchange:bithumb',?,'100',NULL,'acq','EXF_BUY',4)",
          (NOW - 10 * 86400, aid, str(100 * 10 ** 8)))
c.commit()
c.close()
PX = {"USDT": 1.0}
json.dump({"usd": PX, "usd_ts": {k: NOW for k in PX}, "rate": FX, "updated": NOW, "dex_usd": {}, "dex_ts": {}, "dex_res": {}, "dex_res_ts": {},
           "fx_basis": FX, "ex_usd": {}, "ex_ts": {}}, open(web.SPOT_PATH, "w"))
web.pricing.PxCache.candle_usd = lambda self, sym, ms: PX.get(str(sym).upper())
web.pricing._gj = lambda url, timeout=10.0: None
common.atomic_write_json(web.PREFS_PATH, {"plans": {}, "ignored": []})
open(os.path.join(S, "backfill_done"), "w").write("1")
UP = os.path.join(S, "upbit_balances.json")
BT = os.path.join(S, "exf_balances_bithumb.json")
OK = os.path.join(S, "exf_balances_okx.json")


def files(up_age=0, bt=1_400_000, bt_age=0, okx=None):
    t = int(time.time())
    common.atomic_write_json(UP, {"ts": t - up_age, "accounts": [{"currency": "KRW", "balance": "2800000", "locked": "0"},
                                                                 {"currency": "QQQ", "balance": "100", "locked": "0"}]})
    if bt is None:
        if os.path.exists(BT):
            os.remove(BT)
    else:
        common.atomic_write_json(BT, {"ts": t - bt_age, "balances": {"KRW": bt}})
    if okx is None:
        if os.path.exists(OK):
            os.remove(OK)
    else:
        common.atomic_write_json(OK, {"ts": t, "balances": {"KRW": okx}})
    return t


def build(no_rate=False):
    b = web.StateBuilder()
    b.skip_gen_check = True
    if no_rate:
        b.spot.rate = None
    t = int(time.time())
    b.spot.ex_usd["upbit:QQQ"] = 2.0
    b.spot.ex_ts["upbit:QQQ"] = t
    conn = dbm.open_db(common.DB_PATH, readonly=True)
    try:
        f = b._build(conn)["fields"]
    finally:
        conn.close()
    lv = b.daily.get("_live") or {}
    return f, lv, lv.get("xv") or {}


t1 = files()
f, lv, xv = build()
p = xv.get("p") or {}
chk(p.get("ku") == [2800000.0, "snap"] and p.get("kb") == [1400000.0, "snap"], "A1 ku·kb = 원 단위 그대로(달러로 안 바꿈) · 출처 snap", xv)
chk(p.get("ub") == [{"QQQ": 100.0}, "snap"] and xv.get("ubv") == {"QQQ": 200.0}, "A1 ub = {심볼: 수량} · 그때 업비트가 평가 ubv(달러) 따로", xv)
chk(p.get("rest") == [0.0, "snap"] and xv.get("fx") == FX and xv.get("v") == web.XV_V, "A1 rest = 달러 · 환율 fx 따로 · 세대 v", xv)
chk(abs(xv["rt"].get("upbit", 0) - t1) <= 2 and abs(xv["rt"].get("bithumb", 0) - t1) <= 2, "A1 거래소별 잔고 시각 rt(업비트·빗썸)", xv.get("rt"))
chk(abs(xv_sum(xv) - lv["x"]) < 0.01 and abs(lv["x"] - (2000 + 1000 + 200)) < 0.01 and "dx" not in xv, "A1 구성요소 합 = x($3,200) · dx 없음", (lv.get("x"), xv))
fiat = {x9["ex"]: x9["krw"] for x9 in f.get("fiats") or []}
chk(fiat == {"업비트": 2800000.0, "빗썸": 1400000.0}, "A1 화면 예수금 그대로", fiat)

t2 = files(bt_age=4000)
f, lv, xv = build()
p = xv.get("p") or {}
chk(p.get("kb") == [1400000.0, "carry"] and abs(xv["rt"].get("bithumb", 0) - (t2 - 4000)) <= 2, "A2 빗썸 잔고 낡음 = kb 출처 carry(마지막 값) · rt = 그 잔고 시각", xv)
chk(abs(xv_sum(xv) - lv["x"]) < 0.01 and abs(lv["x"] - 3200) < 0.01, "A2 합 = x(낡은 빗썸도 x 엔 그대로 듦)", (lv.get("x"), xv))

t3 = files(up_age=700)
f, lv, xv = build()
p = xv.get("p") or {}
chk(p.get("ku") == [2800000.0, "carry"] and "ub" not in p and "ubv" not in xv, "A3 업비트 스냅숏 낡음(700초) = ku 마지막 값 carry · ub 키 없음(0 으로 굳지 않게)", xv)
chk(abs(xv["rt"].get("upbit", 0) - (t3 - 700)) <= 2, "A3 rt 에 낡은 업비트 스냅숏 시각은 남김", xv.get("rt"))
chk(abs(xv_sum(xv) - lv["x"]) < 0.01 and abs(lv["x"] - 3000) < 0.01, "A3 합 = x(낡은 업비트 원화 ₩280만도 x 엔 그대로 · 미매칭 코인만 빠짐)", (lv.get("x"), xv))
fu = [x9 for x9 in f.get("fiats") or [] if x9["ex"] == "업비트"]
chk(len(fu) == 1 and fu[0]["krw"] == 2800000.0 and fu[0].get("stale") is True and 690 <= fu[0].get("age", 0) <= 720 and "업비트 잔고" in fu[0]["note"],
    "A3 화면 업비트 원화 = 마지막 값 + stale·age·'업비트 잔고 N분 전'(다른 거래소 원화와 같은 모양)", fu)
t3b = files(up_age=90000)
f, lv, xv = build()
p = xv.get("p") or {}
chk("ku" not in p and "ub" not in p and abs(lv["x"] - 1000) < 0.01 and not [x9 for x9 in f.get("fiats") or [] if x9["ex"] == "업비트"],
    "A3b 하루 넘게 낡은 업비트 스냅숏 = 끊긴 것으로 보고 원화 뺌(ku 키 없음 · x 빗썸만)", (lv.get("x"), xv, f.get("fiats")))

files(bt=None)
f, lv, xv = build()
p = xv.get("p") or {}
chk("kb" not in p and "bithumb" not in xv.get("rt", {}), "A4 빗썸 잔고 파일 없음 = kb·rt 없음", xv)
files(bt=0)
f, lv, xv = build()
p = xv.get("p") or {}
chk(p.get("kb") == [0.0, "snap"] and "bithumb" in xv.get("rt", {}), "A5 빗썸 실제 0원 = kb [0, snap] + rt (A4 와 구분)", xv)
chk(abs(xv_sum(xv) - lv["x"]) < 0.01, "A5 합 = x", (lv.get("x"), xv))

files(okx=70_000)
f, lv, xv = build()
p = xv.get("p") or {}
chk(p.get("rest") == [50.0, "snap"] and "okx" in xv.get("rt", {}), "A6 그 밖 거래소 원화 = rest 달러(₩70,000 ÷ 1,400)", xv)
chk(abs(xv_sum(xv) - lv["x"]) < 0.01 and abs(lv["x"] - 3250) < 0.01, "A6 합 = x", (lv.get("x"), xv))

files()
f, lv, xv = build(no_rate=True)
p = xv.get("p") or {}
chk(xv.get("fxd") == 1 and xv.get("fx") == 1384 and p.get("ku") == [2800000.0, "snap"] and abs(xv_sum(xv) - lv["x"]) < 0.01,
    "A7 환율 미조회 = 원화는 원 그대로 · fx = x 계산에 쓴 기본값 + fxd 표식 · 합 = x", (lv.get("x"), xv))

KST = timezone(timedelta(hours=9))
D27 = datetime(2026, 9, 27, tzinfo=KST)
D28 = datetime(2026, 9, 28, tzinfo=KST)
T_CLOSE = D27.replace(hour=23, minute=55).timestamp()
T_NOON = D27.replace(hour=18).timestamp()
T_NEXT = D28.replace(minute=5).timestamp()


class FakeSpot:
    rate = FX
    fx_basis = FX

    def price(self, sym):
        return None


class FakePx:
    def fx_at(self, ms):
        return FX

    def candle_usd(self, sym, ms):
        return None

    def flush(self):
        pass


def unit_builder():
    b = object.__new__(web.StateBuilder)
    b.daily = {"_v": web.DAILY_V}
    b.daily_px = {"_v": 1}
    b._daily_seed = {}
    b._upbit_krw_tl = None
    b.spot = FakeSpot()
    b.px = FakePx()
    return b


T0 = (D27 - timedelta(days=60)).timestamp()
G = {10: {"gid": 10, "sym": "TOK", "is_stable": False, "qty_timeline": [(T0, Decimal(100))]}}
HOLD = {10: Decimal(100)}
XV = {"v": web.XV_V, "p": {"ku": [2800000.0, "snap"], "kb": [1400000.0, "snap"], "ub": [{"QQQ": 100.0}, "snap"], "rest": [500.0, "snap"]},
      "fx": FX, "rt": {"upbit": 1, "bithumb": 1}, "ubv": {"QQQ": 200.0}}
X = {"ub": 200.0, "fiat": 3000.0, "lp": 500.0, "ubs": {"QQQ": [100.0, 200.0]}, "ub_tl": {},
     "krw_up": 2800000.0, "krw_other": 1400000.0, "rate": FX, "krw_up_tl": None, "xv": XV}
X_TOTAL = 3700.0


def reset_files():
    for p9 in (web.DAILY_PATH, web.DAILY_PX_PATH):
        if os.path.exists(p9):
            os.remove(p9)


def run(b, today, now_ts, extra, pend=(), lg=None):
    return b._daily_series(G, today, {}, {10: 2.0}, ca_gids={10}, ex_gids=set(), skip_gids=set(), pending_gids=set(pend),
                           hold_qty=HOLD, extra=copy.deepcopy(extra), extra_ok=True, now_ts=now_ts, led_gen=lg)


def strip(o):
    if isinstance(o, dict):
        return {k: strip(v) for k, v in o.items() if k not in ("xv", "_reset_at")}
    if isinstance(o, (list, tuple)):
        return [strip(v) for v in o]
    return o


def scenario(extra, steps):
    reset_files()
    b = unit_builder()
    out = []
    for today, now_ts, pend, inval, *lg in steps:
        if inval and os.path.exists(web.DAILY_PATH):
            os.remove(web.DAILY_PATH)
        d = run(b, today, now_ts, extra, pend, lg[0] if lg else None)
        out.append((copy.deepcopy(d), copy.deepcopy(b.daily), copy.deepcopy(b.daily_px)))
    return out


def twin_same(name, a, b):
    ok = all(strip(x) == strip(y) for x, y in zip(a, b)) and len(a) == len(b)
    bad = next(((i, strip(x), strip(y)) for i, (x, y) in enumerate(zip(a, b)) if strip(x) != strip(y)), None)
    chk(ok, name + " — 쌍둥이(구성요소 재료 없음 = 종전)와 시리즈·daily_cache·daily_px 동일", bad)


X_NO = {k: v for k, v in X.items() if k != "xv"}
STEPS = [(D27, T_CLOSE, (), False), (D28, T_NEXT, (), False), (D28, T_NEXT + 60, (), False), (D28, T_NEXT + 120, (), True)]
sa = scenario(X, STEPS)
f27 = (common.read_json(web.DAILY_PX_PATH, {}) or {}).get("2026-09-27") or {}
sb = scenario(X_NO, STEPS)
d0, c0, p0 = sa[0]
lxv = (c0.get("_live") or {}).get("xv") or {}
chk(lxv.get("p") == XV["p"] and lxv.get("ts") == int(T_CLOSE) and abs(xv_sum(lxv) - c0["_live"]["x"]) < 0.01 and "dx" not in lxv,
    "B1 오늘 스냅숏 _live.xv = 구성요소 · 스냅숏 시각 · 합 = x", (c0.get("_live") or {}))
d1, c1, p1 = sa[1]
e27 = p1.get("2026-09-27") or {}
chk(e27.get("xv", {}).get("p") == XV["p"] and e27["xv"].get("fx") == FX and e27["xv"].get("ubv") == {"QQQ": 200.0}
    and e27["xv"].get("v") == xparts.GEN and e27["xv"].get("ts") == int(T_CLOSE) and "part" not in e27["xv"] and "dx" not in e27["xv"]
    and e27["xv"].get("how") == "snap" and e27["xv"].get("ob") == {"ku": [1.0, 2800000.0], "kb": [1.0, 1400000.0]},
    "B2 다음 날 동결 → daily_px[그날].xv(세대 GEN · 원 단위 ku·kb · ub 수량 · rest 달러 · fx · ubv · 스냅숏 시각 · 잔고 관측 ob)", e27)
chk(e27.get("x") == X_TOTAL and e27.get("xk") == "live" and e27.get("xu") == {"QQQ": [100.0, 200.0]} and c1["2026-09-27"].get("src") == "live",
    "B2 기존 x·xk·xu 무변(실시간 마감)", (e27, c1.get("2026-09-27")))
calc9 = {k: v for k, v in p1.items() if k != "2026-09-27" and isinstance(v, dict) and "xv" in v}
chk(calc9 and all(v["xv"].get("v") == xparts.GEN and v["xv"].get("how") == "calc" and abs(xv_sum(v["xv"]) - v["x"]) < 0.01 for v in calc9.values()),
    "B2 스냅숏 없는 날(계산 동결)도 xv(규칙 · 합 = 고정 x)", {k: v.get("xv") for k, v in list(calc9.items())[:2]})
twin_same("B2·B3·B4", sa, sb)
chk(sa[2][2].get("2026-09-27") == e27, "B3 다시 빌드 = 같은 daily_px 항목(멱등)", sa[2][2].get("2026-09-27"))
chk(sa[3][2].get("2026-09-27", {}).get("xv") == e27["xv"] and sa[3][1]["2026-09-27"].get("src") == "live" and f27.get("xv") == e27["xv"],
    "B4 동결 무효화(daily_cache 삭제) 뒤 다시 동결 = 같은 xv · 파일에도", sa[3][2].get("2026-09-27"))

ST5 = [(D27, T_CLOSE, (10,), False), (D28, T_NEXT, (), False), (D28, T_NEXT + 60, (), False)]
s5a, s5b = scenario(X, ST5), scenario(X_NO, ST5)
e5 = s5a[1][2].get("2026-09-27") or {}
chk(s5a[0][1]["_live"].get("defer") is True and s5a[1][1]["2026-09-27"].get("src") == "partial" and e5.get("xv", {}).get("part") == 1
    and e5["xv"].get("p") == XV["p"] and e5.get("x") == X_TOTAL, "B5 부분 동결 = xv + part 표식 · 고정 x 그대로", (e5, s5a[1][1].get("2026-09-27")))
chk(s5a[2][2].get("2026-09-27") == e5, "B5 다시 빌드 = 같은 값(멱등)", s5a[2][2].get("2026-09-27"))
twin_same("B5", s5a, s5b)

ST6 = [(D27, T_NOON, (), False), (D28, T_NEXT, (), False)]
s6a, s6b = scenario(X, ST6), scenario(X_NO, ST6)
e6 = s6a[1][2].get("2026-09-27") or {}
chk("xv" in (s6a[0][1].get("_live") or {}) and e6.get("xv", {}).get("how") == "day" and all(v[1] == "carry" for v in e6["xv"]["p"].values())
    and e6.get("x") == X_TOTAL and s6a[1][1]["2026-09-27"].get("src") == "calc",
    "B6 창 밖 스냅숏 = 그 관측을 이월 출처로(전부 carry) · 그날 x 무변", e6)
twin_same("B6", s6a, s6b)

LOGS = []


class _H(logging.Handler):
    def emit(self, r):
        LOGS.append(r.getMessage())


web.log.addHandler(_H())
X7 = copy.deepcopy(X)
X7["xv"]["p"]["ku"] = [2100000.0, "snap"]
s7 = scenario(X7, STEPS[:2])
e7 = s7[1][2].get("2026-09-27") or {}
chk(s7[0][1]["_live"]["xv"].get("dx") == 500.0 and e7.get("x") == X_TOTAL and abs(xv_sum(e7.get("xv") or {"p": {}, "fx": FX}) - X_TOTAL) < 0.01
    and e7["xv"].get("v") == xparts.GEN,
    "B7 합 ≠ x = 관측 기록에 dx · 동결 = 그 x 를 합계 보존으로 쪼갬(x 그대로)", (s7[0][1]["_live"].get("xv"), e7))
chk(any("구성요소 합이 x 와 다름" in m and "2026-09-27" in m for m in LOGS), "B7 경고 로그", LOGS[-5:])
twin_same("B7", s7, sb[:2])

X8 = {"ub": 0.0, "fiat": 1000.0, "lp": 500.0, "ubs": {}, "ub_tl": {}, "krw_up": 0.0, "krw_other": 1400000.0, "rate": FX, "krw_up_tl": None,
      "xv": {"v": web.XV_V, "p": {"kb": [1400000.0, "snap"], "rest": [500.0, "snap"]}, "fx": FX, "rt": {"upbit": 1, "bithumb": 1}}}
s8 = scenario(X8, STEPS[:2])
e8 = s8[1][2].get("2026-09-27") or {}
p8 = e8.get("xv", {}).get("p") or {}
chk(p8.get("kb") == [1400000.0, "snap"] and p8.get("rest") == [500.0, "snap"] and p8.get("ku", [None, None])[1] == "carry" and p8.get("ub", [None, None])[1] == "carry"
    and e8.get("x") == 1500.0, "B8 못 읽은 구성요소(ku·ub) = 동결 때 규칙으로 채움(관측 snap 그대로 · 이 시험은 이월 0) · x 무변", e8)

ST9 = [(D27, T_CLOSE, (), False, 100), (D28, T_NEXT, (), False, 200)]
s9a, s9b = scenario(X, ST9), scenario(X_NO, ST9)
e9 = s9a[1][2].get("2026-09-27") or {}
chk(s9a[1][1]["2026-09-27"].get("why") == "led" and e9.get("x") == X_TOTAL and e9.get("xv", {}).get("p") == XV["p"] and "part" not in e9["xv"],
    "B9 원장 세대가 바뀐 마감 창 스냅숏 = 고정 x 와 같은 스냅숏의 xv", (e9, s9a[1][1].get("2026-09-27")))
twin_same("B9", s9a, s9b)

reset_files()
T.finish()
