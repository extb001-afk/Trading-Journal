#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import copy  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from decimal import Decimal  # noqa: E402

import paths  # noqa: E402

json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(os.environ["TJ_BASE"], "config.json"), "w"))
import view_attur  # noqa: E402
import web  # noqa: E402
import xparts  # noqa: E402

chk = T.chk
open(os.path.join(paths.STATE_DIR, "backfill_done"), "w").write("1")
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


T0 = E(9, 1, 0, 0, 0)
TM, TS = E(10, 9, 10, 0, 0), E(10, 9, 11, 0, 0)
LEGS = [(TM, "m1", [(3, -300, None, "move_out", "TRANSFER_SELF", "exchange:bybit"), (2, 300, None, "move_in", "TRANSFER_SELF", "wallet:eth:0xa")]),
        (TS, "s1", [(3, -200, 17, "disp", "EXF_SELL", "exchange:bybit"), (1, 17, 17, "acq", "EXF_SELL", "exchange:bybit")])]


def g(gid, sym, stable, tl):
    return {"gid": gid, "sym": sym, "is_stable": stable, "qty_timeline": [(int(t), Decimal(str(q))) for t, q in tl]}


tl = {1: [(T0, 1000)], 2: [(T0, 1000)], 3: [(T0, 500)]}
for t9, _s9, legs9 in LEGS:
    for gid9, q9, _c9, _k9, _e9, _l9 in legs9:
        tl[gid9].append((t9, q9))
G = {1: g(1, "USDC", True, tl[1]), 2: g(2, "MPLX", False, tl[2]), 3: g(3, "MPLX", False, tl[3])}
G[3]["flows"] = [{"rbd": {iso(10, 9): Decimal("7")}}]
HOLD = {gid9: sum((Decimal(str(q9)) for _t, q9 in v9), Decimal(0)) for gid9, v9 in tl.items()}
DEC = {1: 6, 2: 18, 3: 18}
conn = sqlite3.connect(":memory:")
conn.execute("CREATE TABLE assets (asset_id INTEGER PRIMARY KEY, kind TEXT, chain TEXT, address TEXT, symbol TEXT, decimals INTEGER, group_id INTEGER)")
conn.execute("CREATE TABLE postings (posting_id INTEGER PRIMARY KEY, source_kind TEXT, source_ns TEXT, source_id TEXT, leg_seq INTEGER, event_ts INTEGER,"
             " asset_id INTEGER, location TEXT, qty_base TEXT, cost_usd TEXT, cost_krw TEXT, leg_kind TEXT, event TEXT)")
for aid9, sym9 in ((1, "USDC"), (2, "MPLX"), (3, "MPLX")):
    conn.execute("INSERT INTO assets VALUES (?, 'token', 'eth', ?, ?, ?, ?)", (aid9, "0x%040d" % aid9, sym9, DEC[aid9], aid9))
pid9 = 0
for t9, s9, legs9 in LEGS:
    for seq9, (gid9, q9, c9, k9, e9, l9) in enumerate(legs9):
        pid9 += 1
        conn.execute("INSERT INTO postings VALUES (?, 'exchange', 'bybit:x', ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
                     (pid9, s9, seq9, int(t9), gid9, l9, str(q9 * 10 ** DEC[gid9]), None if c9 is None else str(c9), k9, e9))
REAL = {"rbd": {iso(10, 9): 7.0}, "lpf": {}, "stk": {}, "unv": {}}
P_OLD, P_DAY = 0.05, 0.0885


def build(today, gids_day=(2, 3)):
    for p9 in (paths.state("daily_cache.json"), paths.state("daily_px.json")):
        if os.path.exists(p9):
            os.remove(p9)
    b = unit_builder()
    for m9, r9 in ((9, range(11, 31)), (10, range(1, 11))):
        for d9 in r9:
            if (m9, d9) >= (today.month, today.day):
                continue
            px9 = {str(x): (P_DAY if (m9, d9) >= (10, 9) else P_OLD) for x in gids_day}
            b.daily_px[iso(m9, d9)] = {"p": px9, "k": {k9: "live" for k9 in px9},
                                       "xv": {"v": xparts.GEN, "p": {"ku": [0.0, "snap"], "kb": [0.0, "snap"], "ub": [{}, "snap"], "rest": [0.0, "snap"]},
                                              "fx": FX, "how": "live"}}
    now9 = today.timestamp() + 12 * 3600
    live9 = {x: P_DAY for x in gids_day}
    ser9 = b._daily_series(G, today, {}, live9, ca_gids=set(gids_day), ex_gids=set(), skip_gids=set(), pending_gids=set(),
                           hold_qty=HOLD, extra=copy.deepcopy(mkx(now9)), extra_ok=True, now_ts=now9)
    att9 = b._daily_attrib(conn, ser9, G, today, live9, frozenset(), mkx(now9), real=REAL)
    return att9.get("10-09") or {}, {r["date"]: r["val"] for r in ser9}


print("[1] 지난날(10-10 기준 10-09)")
a1, v1 = build(D(10, 10))
chk(a1.get("rest") is not None and abs(a1["rest"]) < 0.02, "나머지 ≈ 0(종전 +$11.55 = 옮긴 300 × 0.0385)", a1)
chk(abs(a1.get("gx", 0) - 19.25) < 0.02, "묶음 차 gx = B 전일 보유 500 × (0.0885 − 0.05) = +$19.25", a1.get("gx"))
chk(abs(a1.get("rz", 0) - 7) < 0.01 and abs(a1.get("ur", 0) - (a1.get("tr", 0) + a1.get("gx", 0) - 7)) < 0.02, "실현 $7 · ur = T + gx − 실현", a1)
print("[2] 오늘(10-09 = 오늘 · 화면 시세)")
a2, v2 = build(D(10, 9))
chk(a2.get("rest") is not None and abs(a2["rest"]) < 0.02, "오늘도 나머지 ≈ 0", a2)
print("[3] 단위 — 붙일 묶음 없음 = 종전 · 지난날 외부 유출 수량 뺌")
own9 = {3: 0.05}
chk(view_attur.prev_only(own9, {}, {"3": 0.05}, lambda g0: True, G, {}, frozenset()) == set(), "같은 심볼 그날가 그룹이 없으면 전일가 그룹도 종전 묶음", None)
chk(view_attur.prev_only({2: 0.0885, 3: 0.05}, {}, {"2": 0.0885, "3": 0.05}, lambda g0: g0 == 3, G, {}, frozenset()) == set(),
    "같은 심볼 다른 그룹도 그날가가 없으면(전일가뿐 · 무이동) 종전 묶음 — 그날가 근거 = pdx 만", None)
own9 = {2: 0.0885, 3: 0.05}
IE9 = frozenset(("TRANSFER_SELF",))
chk(view_attur.prev_only(own9, {"2": 0.0885}, {"2": 0.05, "3": 0.05}, lambda g0: g0 == 3, G, {3: {"TRANSFER_OUT": Decimal(-500)}}, IE9) == set(),
    "외부 레그(내 위치 이동 아님)가 있는 마감 0 그룹 = 후보 아님(입출금 줄이 그 기준가로 이미 매김 — 종전 그대로)", None)
pv9 = view_attur.prev_only(own9, {"2": 0.0885}, {"2": 0.05, "3": 0.05}, lambda g0: g0 == 3, G, {3: {"TRANSFER_SELF": Decimal(-300)}}, IE9)
chk(pv9 == {3} and view_attur.by_symbol(own9, G, pv9) == {"MPLX": [2]}, "마감 0 그룹만 묶음 판정에서 뺌", pv9)
pa9, pb9, pc9 = set(pv9), set(pv9), set(pv9)
PD9 = {"2": 0.0885}
bp9 = view_attur.prev_band_px(pa9, own9, {"MPLX": [(0.05, [3]), (0.0885, [2])]}, None, G, (0.5, 2.0), PD9)
bq9 = view_attur.prev_band_px(pb9, {2: 0.0885, 3: 0.03}, {"MPLX": [(0.03, [3]), (0.0885, [2])]}, None, G, (0.5, 2.0), PD9)
bm9 = view_attur.prev_band_px(pc9, {2: 0.055, 3: 0.05}, {"MPLX": [(0.05, [2, 3])]}, None, G, (0.5, 2.0), {"2": 0.055})
pd9 = set(pv9)
G[4] = {"gid": 4, "sym": "MPLX", "is_stable": False}
bn9 = view_attur.prev_band_px(pd9, {2: 0.0885, 3: 0.05, 4: 0.04}, {"MPLX": [(0.04, [4]), (0.05, [3]), (0.0885, [2])]}, None, G, (0.5, 2.0), PD9)
pz9 = set(pv9)
bz9 = view_attur.prev_band_px(pz9, own9, {"MPLX": [(0.05, [3]), (0.0885, [2])]}, {2: 0.0885}, G, (0.5, 2.0), PD9)
del G[4]
chk(bp9 == {3: 0.0885} and pa9 == {3} and bq9 == {} and pb9 == set() and bm9 == {} and pc9 == set() and bn9 == {3: 0.0885} and bz9 == {} and pz9 == set(),
    "따로 갈라진 묶음만 붙임(0.5~2배 안 = 그날가(pdx) 그룹 든 묶음가 — 전일가뿐인 무이동 묶음 0.04 는 목적지 아님 · 오늘 화면 시세 없음 = 안 붙임) · 밖 = 종전 · 이미 그날가 그룹과 같은 묶음 = 종전(다른 그룹 기준가 무변) · 후보 = 붙인 것만 남음", (bp9, bq9, bm9))
mv9 = {3: {"TRANSFER_OUT": Decimal(-100), "TRANSFER_SELF": Decimal(-300), "EXF_SELL": Decimal(-100)}}
ie9 = frozenset(("TRANSFER_SELF",))
chk(abs(view_attur.prev_out(3, 25.0, 0.05, pv9, False, mv9, ie9) - (-15.0)) < 1e-9 and view_attur.prev_out(3, 25.0, 0.05, pv9, True, mv9, ie9) == -25.0
    and view_attur.prev_out(2, 50.0, 0.05, pv9, False, mv9, ie9) == -50.0,
    "지난날 = 내 위치 이동 아닌 유출 200 뺀 300 × 0.05 · 오늘·다른 그룹 = 종전 −전일 평가", None)
mi9 = {3: {"TRANSFER_IN": Decimal(200), "TRANSFER_OUT": Decimal(-500)}}
mo9 = {3: {"TRANSFER_OUT": Decimal(-700)}}
chk(abs(view_attur.prev_out(3, 25.0, 0.05, pv9, False, mi9, ie9) - (-10.0)) < 1e-9 and abs(view_attur.prev_out(3, 25.0, 0.05, pv9, False, mo9, ie9) - 10.0) < 1e-9,
    "외부 순이동 = 부호 있는 합(유입도 셈 · 자르지 않음): 500 − 300 = 200 × 0.05 · 500 − 700 = −200 → +$10(그날 산 몫)", None)
chk(view_attur.day_excl("2026-10-09", {"2026-10-09": {3: Decimal(200)}}, {"2026-10-09": {4: Decimal(1)}}, {}, {"unv": {"2026-10-09": {5: (1.0, 2.0)}}})
    == {3, 4, 5} and view_attur.day_excl("2026-10-08", {"2026-10-09": {3: 1}}, {}, {}, None) == set(),
    "그날 기초 잔고 정정·선물 반영·이자·원가 미확인 그룹 = 후보 아님(op·fb·dbi·un 금액이 레그 가격을 읽음 — 종전 그대로)", None)
conn.close()
T.finish()
