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


P_OLD, P_DAY = 0.05, 0.0885
T0 = E(9, 1, 0, 0, 0)
TB, TM, TS = E(10, 9, 10, 0, 0), E(10, 9, 10, 30, 0), E(10, 9, 11, 0, 0)
LEGS = [(TB, "b1", [(2, 1000, 88.5, "acq", "SWAP", "wallet:sol:A"), (1, -88.5, None, "disp", "SWAP", "wallet:sol:A")]),
        (TM, "m1", [(2, -1000, None, "move_out", "TRANSFER_OUT_EX", "wallet:sol:A"), (3, 1000, None, "move_in", "EXF_DEPOSIT", "exchange:bybit")]),
        (TS, "s1", [(3, -1500, 132.75, "disp", "EXF_SELL", "exchange:bybit"), (1, 132.75, 132.75, "acq", "EXF_SELL", "exchange:bybit")])]


def g(gid, sym, stable, tl):
    return {"gid": gid, "sym": sym, "is_stable": stable, "qty_timeline": [(int(t), Decimal(str(q))) for t, q in tl]}


tl = {1: [(T0, 1000)], 2: [(T0, 10)], 3: [(T0, 500)]}
for t9, _s9, legs9 in LEGS:
    for gid9, q9, _c9, _k9, _e9, _l9 in legs9:
        tl[gid9].append((t9, q9))
G = {1: g(1, "USDC", True, tl[1]), 2: g(2, "TKJ", False, tl[2]), 3: g(3, "TKJ", False, tl[3])}
G[3]["flows"] = [{"rbd": {iso(10, 9): Decimal("0")}}]
HOLD = {gid9: sum((Decimal(str(q9)) for _t, q9 in v9), Decimal(0)) for gid9, v9 in tl.items()}
DEC = {1: 6, 2: 18, 3: 18}
conn = sqlite3.connect(":memory:")
conn.execute("CREATE TABLE assets (asset_id INTEGER PRIMARY KEY, kind TEXT, chain TEXT, address TEXT, symbol TEXT, decimals INTEGER, group_id INTEGER)")
conn.execute("CREATE TABLE postings (posting_id INTEGER PRIMARY KEY, source_kind TEXT, source_ns TEXT, source_id TEXT, leg_seq INTEGER, event_ts INTEGER,"
             " asset_id INTEGER, location TEXT, qty_base TEXT, cost_usd TEXT, cost_krw TEXT, leg_kind TEXT, event TEXT)")
for aid9, sym9 in ((1, "USDC"), (2, "TKJ"), (3, "TKJ")):
    conn.execute("INSERT INTO assets VALUES (?, 'token', 'sol', ?, ?, ?, ?)", (aid9, "A%040d" % aid9, sym9, DEC[aid9], aid9))
pid9 = 0
for t9, s9, legs9 in LEGS:
    for seq9, (gid9, q9, c9, k9, e9, l9) in enumerate(legs9):
        pid9 += 1
        conn.execute("INSERT INTO postings VALUES (?, 'exchange', 'bybit:x', ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
                     (pid9, s9, seq9, int(t9), gid9, l9, str(int(Decimal(str(q9)) * 10 ** DEC[gid9])), None if c9 is None else str(c9), k9, e9))


def build(today, live_b=True, unv=False, dpx_b=False, live_b_px=P_DAY):
    for p9 in (paths.state("daily_cache.json"), paths.state("daily_px.json")):
        if os.path.exists(p9):
            os.remove(p9)
    b = unit_builder()
    for m9, r9 in ((9, range(11, 31)), (10, range(1, 11))):
        for d9 in r9:
            if (m9, d9) >= (today.month, today.day):
                continue
            gd9 = (2, 3) if (m9, d9) < (10, 9) or dpx_b else (2,)
            px9 = {str(x): (P_DAY if (m9, d9) >= (10, 9) else P_OLD) for x in gd9}
            b.daily_px[iso(m9, d9)] = {"p": px9, "k": {k9: "live" for k9 in px9},
                                       "xv": {"v": xparts.GEN, "p": {"ku": [0.0, "snap"], "kb": [0.0, "snap"], "ub": [{}, "snap"], "rest": [0.0, "snap"]},
                                              "fx": FX, "how": "live"}}
    now9 = today.timestamp() + 12 * 3600
    live9 = {2: P_DAY, 3: live_b_px} if live_b else {2: P_DAY}
    ser9 = b._daily_series(G, today, {}, live9, ca_gids={2, 3}, ex_gids=set(), skip_gids=set(), pending_gids=set(),
                           hold_qty=HOLD, extra=copy.deepcopy(mkx(now9)), extra_ok=True, now_ts=now9)
    fl9 = b._daily_flows(conn, ser9, G, today, live9, frozenset(), FX)
    for r9 in ser9:
        if r9["date"] in fl9:
            r9["flow"] = fl9[r9["date"]][0]
    real9 = {"rbd": {}, "lpf": {}, "stk": {}, "unv": {iso(10, 9): {3: (0.5, 0.0)}} if unv else {}}
    att9 = b._daily_attrib(conn, ser9, G, today, live9, frozenset(), mkx(now9), real=real9)
    return att9.get("10-09") or {}, fl9.get("10-09")


print("[1] 오늘 + 원가 미확인 매도")
a1, f1 = build(D(10, 9), unv=True)
chk(a1.get("rest") is not None and abs(a1["rest"]) < 0.02, "나머지 ≈ 0(종전 −$38.5 = 옮긴 1,000 × (0.05 − 0.0885))", a1)
chk(abs(a1.get("gx", 0) - 19.25) < 0.02 and f1 is not None and abs(f1[0]) < 0.02, "gx = B 전일 보유 500 × (0.0885 − 0.05) = +$19.25 · 입출금 0(내 위치 이동)", (a1.get("gx"), f1))
chk(abs(a1.get("un", 0) - round(0.0 - 0.5 * 0.0885, 2)) < 0.006, "un = 정산 − 수량 × 붙인 레그 가격(T 와 같은 가격)", a1.get("un"))
print("[2] 오늘 · 원가 미확인 없음")
a2, _f2 = build(D(10, 9), unv=False)
chk(a2.get("rest") is not None and abs(a2["rest"]) < 0.02 and abs(a2.get("gx", 0) - 19.25) < 0.02, "종전과 같음(나머지 ≈ 0)", a2)
print("[3] 지난날(내일 기준) — 입출금이 B 레그를 그날가 묶음 가격으로(내부 이동 상계 · 가짜 순유입 0) · 분해가 같은 가격으로 붙임(나머지 ≈ 0)")
for unv3 in (False, True):
    for dpx3 in (False, True):
        a3, f3 = build(D(10, 10), unv=unv3, dpx_b=dpx3)
        if unv3 and dpx3:
            chk(f3 is not None and abs(f3[0]) < 0.02 and abs(a3.get("rest", 0) + 38.5) < 0.02, "지난날 원가 미확인 · 그날 고정가에 B 있음 = 종전 그대로(입출금 0 · 나머지 −38.5)", (a3.get("rest"), f3))
            continue
        chk(a3.get("rest") is not None and abs(a3["rest"]) < 0.02 and abs(a3.get("gx", 0) - 19.25) < 0.02 and f3 is not None and abs(f3[0]) < 0.02,
            "지난날 원가 미확인 %s · 그날 고정가에 B %s: 입출금 0 · 나머지 ≈ 0 · gx = 전일 보유 500 × 0.0385" % ("있음" if unv3 else "없음", "있음" if dpx3 else "없음"),
            (a3.get("rest"), a3.get("gx"), f3))
print("[4] 단위 — day_excl")
chk(view_attur.day_excl("2026-10-09", {"2026-10-09": {3: Decimal(200)}}, {"2026-10-09": {4: Decimal(1)}}, {"2026-10-09": {6: Decimal(1)}},
                        {"unv": {"2026-10-09": {5: (1.0, 2.0)}}}, live=True) == {3, 4, 6}
    and view_attur.day_excl("2026-10-09", {}, {}, {}, {"unv": {"2026-10-09": {5: (1.0, 2.0)}}}) == {5},
    "오늘(live) = 원가 미확인만 후보로 남김 · 지난날 = 종전(원가 미확인도 뺌)", None)
print("[5] 오늘 + 원가 미확인 · 입출금 가격과 다른 묶음 = 종전")
a5, f5 = build(D(10, 9), unv=True, live_b_px=P_OLD)
chk(a5.get("rest") is not None and abs(a5["rest"]) < 0.02 and abs(a5.get("gx", 0)) < 0.005 and f5 is not None and abs(f5[0] + 38.5) < 0.02,
    "B 화면 시세 0.05(입출금 = 따로 묶음)면 붙이지 않음 — 나머지 ≈ 0 · gx 0", (a5, f5))
print("[6] 단위 — unv_live_keep: 일반 후보와 같은 전일가 묶음 = 종전(둘 다 안 붙음) · unv 만의 묶음 = 입출금 가격과 같을 때만 · unv 없음 = 종전")
G6 = {i6: {"sym": "TKJ"} for i6 in (2, 3, 4, 5)}
OWN6, PD6 = {2: P_DAY, 3: P_OLD, 4: P_OLD, 5: P_OLD}, {"2": P_DAY}
BANDS6 = {"TKJ": [(P_OLD, [3, 4]), (P_DAY, [2])]}
LIVE6 = {2: P_DAY, 3: P_DAY, 4: P_DAY, 5: P_DAY}


def keep6(prev6, bands6, unv6, fpx6):
    return view_attur.unv_live_keep(lambda q6: view_attur.prev_band_px(q6, OWN6, bands6, LIVE6, G6, (0.5, 2.0), PD6), prev6, unv6, fpx6, "2026-10-09", bands6)


for fp6 in (P_OLD, P_DAY):
    p6 = {3, 4}
    o6 = keep6(p6, BANDS6, {3: (0.5, 0.0)}, {("2026-10-09", 3): fp6, ("2026-10-09", 4): fp6})
    chk(o6 == {} and p6 == set(), "혼합 전일가 묶음(입출금 가격 %s) = 둘 다 종전" % fp6, (o6, p6))
B7 = {"TKJ": [(P_OLD, [3, 5]), (P_DAY, [2])]}
p7 = {3, 5}
o7 = keep6(p7, B7, {3: (0.5, 0.0), 5: (0.1, 0.0)}, {("2026-10-09", 3): P_DAY, ("2026-10-09", 5): P_DAY})
p8 = {3, 5}
o8 = keep6(p8, B7, {3: (0.5, 0.0), 5: (0.1, 0.0)}, {("2026-10-09", 3): P_DAY, ("2026-10-09", 5): P_OLD})
chk(o7 == {3: P_DAY, 5: P_DAY} and p7 == {3, 5} and o8 == {} and p8 == set(),
    "unv 만의 묶음 = 전부 입출금 가격과 같으면 붙음 · 하나라도 다르면 전부 종전", (o7, o8))
p9 = {4}
o9 = keep6(p9, {"TKJ": [(P_OLD, [4]), (P_DAY, [2])]}, {}, {})
chk(o9 == {4: P_DAY} and p9 == {4}, "unv 없음 = prev_band_px 그대로(종전)", (o9, p9))
for px10 in (0.2, 0.0):
    p10 = {3, 5}
    o10 = view_attur.unv_live_keep(lambda q10: view_attur.prev_band_px(q10, OWN6, B7, {**LIVE6, 5: px10}, G6, (0.5, 2.0), PD6),
                                   p10, {3: (0.5, 0.0), 5: (0.1, 0.0)}, {("2026-10-09", 3): P_DAY, ("2026-10-09", 5): P_DAY}, "2026-10-09", B7)
    chk(o10 == {} and p10 == set(), "unv 후보 일부만 붙으면 전부 종전(다른 후보 화면 시세 %s)" % px10, (o10, p10))
G6[8], G6[9] = {"sym": "XBT"}, {"sym": "XBT"}
OWN6.update({8: 100.0, 9: 101.0})
B11 = {"TKJ": [(P_OLD, [3]), (P_DAY, [2])], "XBT": [(100.0, [8, 9])]}
p11 = {3, 9}
o11 = keep6(p11, B11, {3: (0.5, 0.0), 9: (0.1, 0.0)}, {("2026-10-09", 3): P_DAY})
chk(o11 == {3: P_DAY} and p11 == {3}, "다른 묶음의 unv 후보(섞인 묶음 · 입출금 레그 없음)가 막지 않음 — 묶음 단위 판정", (o11, p11))
print("[7] 단위 — flow_prev_reprice · past_flow_px")
acc7 = {"2026-10-08": {"TKJ": {2: {"a": Decimal(-100)}, 3: {"b": Decimal(100)}, 4: {"c": Decimal(5)}, 6: {"f": Decimal(1)}, 8: {"h": Decimal(1)}},
                       "USDC": {1: {"d": Decimal(1)}, 9: {"e": Decimal(1)}}},
        "2026-10-09": {"TKJ": {2: {"a": Decimal(-1)}, 3: {"b": Decimal(1)}}}}
gpx7 = {("2026-10-08", 2): 0.0885, ("2026-10-08", 3): 0.05, ("2026-10-08", 4): 0.02, ("2026-10-08", 6): 0.09, ("2026-10-08", 8): 0.07,
        ("2026-10-08", 1): 1.0, ("2026-10-08", 9): 1.0, ("2026-10-09", 2): 0.0885, ("2026-10-09", 3): 0.05}
gpxc7, gsrc7 = dict(gpx7), {}
DPX7 = {"2026-10-08": {"p": {"2": 0.0885}}, "2026-10-09": {"p": {"2": 0.0885}}}
SRC7 = {"2026-10-08": ({"2": 1.0, "8": 7.0}, {"2": 0.0885, "8": 0.07}, None), "2026-10-09": ({"2": 1.0}, {"2": 0.0885}, None)}
G7 = {1: {"sym": "USDC", "is_stable": True}, 9: {"sym": "USDC", "is_stable": True}, 2: {"sym": "TKJ"}, 3: {"sym": "TKJ"}, 4: {"sym": "TKJ"},
      6: {"sym": "TKJ"}, 8: {"sym": "TKJ"}}
rep7 = view_attur.flow_prev_reprice(acc7, (gpx7, gpxc7, gsrc7), G7, (DPX7, SRC7), "2026-10-09", (0.5, 2.0), {})
chk(rep7 == {("2026-10-08", 3): 0.0885} and gpx7[("2026-10-08", 3)] == 0.0885 and gpxc7[("2026-10-08", 4)] == 0.02 and gpx7[("2026-10-09", 3)] == 0.05
    and gpx7[("2026-10-08", 6)] == 0.09 and gpx7[("2026-10-08", 8)] == 0.07 and gsrc7 == {("2026-10-08", 3): {}},
    "지난날 마감 0 · 따로 갈라진 그룹만 그날가 묶음 가격(밖 · 이미 같은 묶음 · 마감 평가 있음 · 오늘 · 스테이블 = 그대로)", (rep7, gpx7))
chk(view_attur.flow_prev_reprice(acc7, (dict(gpx7), dict(gpxc7), {}), G7, (DPX7, {}), "2026-10-09", (0.5, 2.0), {}) == {}
    and view_attur.flow_prev_reprice(acc7, (dict(gpx7), dict(gpxc7), {}), G7, (DPX7, SRC7), "2026-10-09", (0.5, 2.0), {("2026-10-08", "TKJ"): {}}) == {},
    "분해 재료 없는 날 · 가격 없는 그룹 짝 맞춤(rel3d) 있는 날·심볼 = 종전", None)
acc8 = {"2026-10-08": {"TKJ": {2: {"a": Decimal(100)}, 3: {"b": Decimal(-2000)}, 4: {"c": Decimal(-1000)}}}}
px8 = {("2026-10-08", 2): 10.0, ("2026-10-08", 3): 5.0, ("2026-10-08", 4): 11.0}
G8 = {2: {"sym": "TKJ"}, 3: {"sym": "TKJ"}, 4: {"sym": "TKJ"}}
D8, S8 = {"2026-10-08": {"p": {"2": 10.0}}}, {"2026-10-08": ({"2": 1.0}, {"2": 10.0}, None)}
chk(view_attur.flow_prev_reprice(acc8, (dict(px8), dict(px8), {}), G8, (D8, S8), "2026-10-09", (0.5, 2.0), {}) == {},
    "목적지 묶음 [10(그날가), 11(전일가 · 이동량 최대)] 의 기준 = 전일가 그룹 → 바꾸지 않음(종전)", None)
px9 = {("2026-10-08", 2): 21.0, ("2026-10-08", 3): 10.0, ("2026-10-08", 4): 11.0}
acc9 = {"2026-10-08": {"TKJ": {2: {"a": Decimal(100)}, 3: {"b": Decimal(-1000)}, 4: {"c": Decimal(-2000)}}}}
D9, S9 = {"2026-10-08": {"p": {"2": 21.0}}}, {"2026-10-08": ({"2": 1.0}, {"2": 21.0}, None)}
chk(view_attur.flow_prev_reprice(acc9, (dict(px9), dict(px9), {}), G8, (D9, S9), "2026-10-09", (0.5, 2.0), {}) == {},
    "전일가 묶음 [10, 11] 중 11 만 0.5~2 안 → 묶음 일부만 옮기지 않음(종전)", None)
pv7 = {3, 5, 6}
fa7 = view_attur.past_flow_px(pv7, {("d", 3): 0.0885, ("e", 5): 0.07, ("d", 11): 0.08}, {("d", 3): 0.09, ("d", 6): 0.05, ("e", 5): 0.07, ("d", 11): 0.08}, "d")
chk(fa7 == {3: 0.09, 11: 0.08} and pv7 == {5, 6}, "입출금이 바꾼 그룹만(분해 자기 가격 없는 11 포함) · 입출금이 최종으로 센 가격으로 붙임 · 묶음 판정 후보에서 뺌 · 다른 날·다른 그룹 무접촉", (fa7, pv7))
G11 = {**G8, 5: {"sym": "TKJ", "is_stable": True}}
acc11 = {"2026-10-08": {"TKJ": {2: {"a": Decimal(1)}, 3: {"b": Decimal(-100)}, 5: {"s": Decimal(10)}}}}
px11 = {("2026-10-08", 2): 10.0, ("2026-10-08", 3): 6.0, ("2026-10-08", 5): 1.0}
chk(view_attur.flow_prev_reprice(acc11, (dict(px11), dict(px11), {}), G11, (D8, S8), "2026-10-09", (0.5, 2.0), {}) == {}, "스테이블 섞인 심볼 = 종전", None)
acc10 = {"2026-10-08": {"TKJ": {2: {"a": Decimal(1)}, 3: {"b": Decimal(-100)}, 4: {"c": Decimal(10)}}}}
px10 = {("2026-10-08", 2): 10.0, ("2026-10-08", 3): 6.0, ("2026-10-08", 4): 25.0}
gp10, gc10 = dict(px10), dict(px10)
gp10[("2026-10-08", 4)] = 7.0
chk(view_attur.flow_prev_reprice(acc10, (gp10, gc10, {}), G8, (D8, S8), "2026-10-09", (0.5, 2.0), {}) == {}
    and view_attur.flow_prev_reprice(acc10, (dict(px10), dict(px10), {}), G8, (D8, S8), "2026-10-09", (0.5, 2.0), {}) == {("2026-10-08", 3): 10.0},
    "표시가(fp) 묶음이 지금 고정가 묶음과 다르면 종전 · 같으면 옮김", None)
conn.close()
T.finish()
