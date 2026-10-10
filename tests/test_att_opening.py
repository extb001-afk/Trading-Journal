#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import copy
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import common

json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(os.environ["TJ_BASE"], "config.json"), "w"))
import web
import xparts

chk = T.chk
S = common.STATE_DIR
open(os.path.join(S, "backfill_done"), "w").write("1")
KST = timezone(timedelta(hours=9))
FX = 1400.0


def E(m, d, h=23, mi=59, s=59):
    return datetime(2026, m, d, h, mi, s, tzinfo=KST).timestamp()


def D(m, d):
    return datetime(2026, m, d, tzinfo=KST)


def iso(m, d):
    return "2026-%02d-%02d" % (m, d)


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


def mkx(now_ts):
    return {"ub": 0.0, "fiat": 0.0, "lp": 0.0, "ubs": {}, "ub_tl": {}, "krw_up": 0.0, "krw_other": 0.0, "rate": FX, "krw_up_tl": None,
            "xsrc": {"now": {"ts": now_ts, "ku": 0.0, "kb": 0.0, "ub": {}, "rest": 0.0},
                     "base": {"ku": [0.0, now_ts], "kb": [0.0, now_ts]}, "tl": {"ku": [], "kb": []}, "first": {}}}


def close(a, b9, tol=0.01):
    return a is not None and b9 is not None and abs(float(a) - float(b9)) < tol


for p9 in (web.DAILY_PATH, web.DAILY_PX_PATH):
    if os.path.exists(p9):
        os.remove(p9)
NOW = E(10, 10, 12, 0, 0)
T_TKN, T_QQ, T_ST, T0 = E(10, 8, 21, 0, 0), E(10, 9, 3, 0, 0), E(10, 6, 10, 0, 0), E(8, 1, 0, 0, 0)


def g(gid, sym, stable, tl, op):
    return {"gid": gid, "sym": sym, "is_stable": stable, "qty_timeline": [(int(t), Decimal(str(q))) for t, q in tl],
            "open_tl": [(int(t), Decimal(str(q))) for t, q in op]}


G = {1: g(1, "USDC", True, [(E(9, 1), 100000), (T_ST, 5000)], [(T_ST, 5000)]),
     2: g(2, "TKN", False, [(T_TKN, 1000)], [(T_TKN, 1000)]),
     3: g(3, "QQQ", False, [(T_QQ, 500)], [(T_QQ, 500)]),
     4: g(4, "ABC", False, [(E(7, 1), 100), (T0, -50)], [(T0, -50)])}
HOLD = {1: Decimal(105000), 2: Decimal(1000), 3: Decimal(500), 4: Decimal(50)}
PX = {"2": 2.0, "3": 1.0, "4": 3.0}
b = unit_builder()
for m9, r9 in ((9, range(11, 31)), (10, range(1, 10))):
    for d9 in r9:
        b.daily_px[iso(m9, d9)] = {"p": dict(PX), "k": {k9: "live" for k9 in PX},
                                   "xv": {"v": xparts.GEN, "p": {"ku": [0.0, "snap"], "kb": [0.0, "snap"], "ub": [{}, "snap"], "rest": [0.0, "snap"]},
                                          "fx": FX, "how": "live"}}
ser = b._daily_series(G, D(10, 10), {}, {2: 2.0, 3: 1.0, 4: 3.0}, ca_gids={2, 3, 4}, ex_gids=set(), skip_gids=set(), pending_gids=set(),
                      hold_qty=HOLD, extra=copy.deepcopy(mkx(NOW)), extra_ok=True, now_ts=NOW)
vals = {r["date"]: r["val"] for r in ser}
chk(close(vals.get("10-05"), 100150) and close(vals.get("10-06"), 105150) and close(vals.get("10-08"), 107150) and close(vals.get("10-09"), 107650),
    "곡선(전제): 기초 잔고 줄 날부터 수량이 늘어남(되감기 = 그 줄 시각)", {k9: vals.get(k9) for k9 in ("10-05", "10-06", "10-08", "10-09")})
conn = sqlite3.connect(":memory:")
conn.execute("CREATE TABLE assets (asset_id INTEGER PRIMARY KEY, kind TEXT, chain TEXT, address TEXT, symbol TEXT, decimals INTEGER, group_id INTEGER)")
conn.execute("CREATE TABLE postings (posting_id INTEGER PRIMARY KEY, source_kind TEXT, source_ns TEXT, source_id TEXT, leg_seq INTEGER, event_ts INTEGER,"
             " asset_id INTEGER, location TEXT, qty_base TEXT, cost_usd TEXT, cost_krw TEXT, leg_kind TEXT, event TEXT)")
for aid9, sym9, dec9 in ((1, "USDC", 6), (2, "TKN", 18), (3, "QQQ", 18), (4, "ABC", 18)):
    conn.execute("INSERT INTO assets VALUES (?, 'token', 'eth', ?, ?, ?, ?)", (aid9, "0x%040d" % aid9, sym9, dec9, aid9))
for i9, (aid9, t9, q9, dec9) in enumerate(((1, T_ST, 5000, 6), (2, T_TKN, 1000, 18), (3, T_QQ, 500, 18), (4, E(10, 7, 9, 0, 0), -50, 18))):
    conn.execute("INSERT INTO postings VALUES (?, 'opening', 'eth:disc', ?, 0, ?, ?, 'wallet:eth:0xa', ?, NULL, NULL, 'opening', 'OPENING')",
                 (i9 + 1, "disc:%d" % i9, int(t9), aid9, str(q9 * 10 ** dec9)))
att = b._daily_attrib(conn, ser, G, D(10, 10), {2: 2.0, 3: 1.0, 4: 3.0}, frozenset(), mkx(NOW), real={"rbd": {}, "lpf": {}, "stk": {}, "unv": {}})
a6, a8, a9, a7 = (att.get(k9) or {} for k9 in ("10-06", "10-08", "10-09", "10-07"))
chk(close(a8.get("op"), 2000) and abs(a8.get("rest", 9e9)) < 0.02 and not a8.get("unp"),
    "A 처음 생긴 그룹 TKN 1,000 × $2 = 기초 잔고 정정 +$2,000 · 나머지 ≈ 0 · '가격 한쪽 없는 코인' 아님(수정 전 나머지 +$2,000 · unp 1종)",
    {k9: a8.get(k9) for k9 in ("op", "rest", "unp", "ev")})
chk(close(a9.get("op"), 500) and abs(a9.get("rest", 9e9)) < 0.02 and not a9.get("unp"), "A 다음 날 QQQ 500 × $1 = +$500 · 나머지 ≈ 0",
    {k9: a9.get(k9) for k9 in ("op", "rest", "unp")})
chk(close(a6.get("op"), 5000) and abs(a6.get("rest", 9e9)) < 0.02, "B 있던 스테이블 그룹 +5,000 = 기초 잔고 정정 +$5,000 · 나머지 ≈ 0(수정 전 +$5,000)",
    {k9: a6.get(k9) for k9 in ("op", "rest", "unp")})
chk(not a7.get("op") and abs(a7.get("rest", 9e9)) < 0.02, "C 창 시작으로 당긴 음수 기초 잔고(원장 시각 10/7) = 그날 정정 아님(곡선 무변) · 나머지 0",
    {k9: a7.get(k9) for k9 in ("op", "rest")})
chk(all(abs(a9x.get("rest", 0)) < 0.02 for a9x in att.values()), "모든 날 나머지 ≈ 0(합성 — 시세 변화 없음)", {k9: a9x.get("rest") for k9, a9x in att.items() if abs(a9x.get("rest", 0)) >= 0.02})
conn.close()
T.finish()
