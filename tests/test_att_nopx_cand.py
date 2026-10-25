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


P_OLD, P_DAY = 0.18, 0.2
T0 = E(9, 1, 0, 0, 0)
TB, TM, TS = E(10, 9, 10, 0, 0), E(10, 9, 10, 30, 0), E(10, 9, 11, 0, 0)


def g(gid, sym, stable, tl):
    return {"gid": gid, "sym": sym, "is_stable": stable, "qty_timeline": [(int(t), Decimal(str(q))) for t, q in tl]}


DEC = {1: 6, 2: 18, 3: 18}


def make(ext):
    legs = [(TB, "b1", [(2, 1000, 200, "acq", "SWAP", "wallet:sol:A"), (1, -200, None, "disp", "SWAP", "wallet:sol:A")])]
    if ext:
        legs.append((TM, "m1", [(3, 1000, None, "acq", "TRANSFER_IN", "exchange:bybit")]))
    else:
        legs.append((TM, "m1", [(2, -1000, None, "move_out", "TRANSFER_OUT_EX", "wallet:sol:A"), (3, 1000, None, "move_in", "EXF_DEPOSIT", "exchange:bybit")]))
    legs.append((TS, "s1", [(3, -1000, 199, "disp", "EXF_SELL", "exchange:bybit"), (1, 199, 199, "acq", "EXF_SELL", "exchange:bybit")]))
    tl = {1: [(T0, 1000)], 2: [(T0, 10)], 3: []}
    for t9, _s9, l9 in legs:
        for gid9, q9, _c9, _k9, _e9, _l9 in l9:
            tl[gid9].append((t9, q9))
    G = {1: g(1, "USDC", True, tl[1]), 2: g(2, "TKJ", False, tl[2]), 3: g(3, "TKJ", False, tl[3])}
    hold = {gid9: sum((Decimal(str(q9)) for _t, q9 in v9), Decimal(0)) for gid9, v9 in tl.items()}
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE assets (asset_id INTEGER PRIMARY KEY, kind TEXT, chain TEXT, address TEXT, symbol TEXT, decimals INTEGER, group_id INTEGER)")
    conn.execute("CREATE TABLE postings (posting_id INTEGER PRIMARY KEY, source_kind TEXT, source_ns TEXT, source_id TEXT, leg_seq INTEGER, event_ts INTEGER,"
                 " asset_id INTEGER, location TEXT, qty_base TEXT, cost_usd TEXT, cost_krw TEXT, leg_kind TEXT, event TEXT)")
    for aid9, sym9 in ((1, "USDC"), (2, "TKJ"), (3, "TKJ")):
        conn.execute("INSERT INTO assets VALUES (?, 'token', 'sol', ?, ?, ?, ?)", (aid9, "A%040d" % aid9, sym9, DEC[aid9], aid9))
    pid9 = 0
    for t9, s9, l9 in legs:
        for seq9, (gid9, q9, c9, k9, e9, lo9) in enumerate(l9):
            pid9 += 1
            conn.execute("INSERT INTO postings VALUES (?, 'exchange', 'bybit:x', ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
                         (pid9, s9, seq9, int(t9), gid9, lo9, str(int(Decimal(str(q9)) * 10 ** DEC[gid9])), None if c9 is None else str(c9), k9, e9))
    return G, hold, conn


def build(live_b, ext=False):
    G, hold, conn = make(ext)
    for p9 in (paths.state("daily_cache.json"), paths.state("daily_px.json")):
        if os.path.exists(p9):
            os.remove(p9)
    b = unit_builder()
    today = D(10, 10)
    for m9, r9 in ((9, range(11, 31)), (10, range(1, 10))):
        for d9 in r9:
            px9 = {"2": P_DAY if (m9, d9) >= (10, 9) else P_OLD}
            b.daily_px[iso(m9, d9)] = {"p": px9, "k": {k9: "live" for k9 in px9},
                                       "xv": {"v": xparts.GEN, "p": {"ku": [0.0, "snap"], "kb": [0.0, "snap"], "ub": [{}, "snap"], "rest": [0.0, "snap"]},
                                              "fx": FX, "how": "live"}}
    now9 = today.timestamp() + 12 * 3600
    live9 = {2: P_DAY} if live_b is None else {2: P_DAY, 3: live_b}
    ser9 = b._daily_series(G, today, {}, live9, ca_gids={2, 3}, ex_gids=set(), skip_gids=set(), pending_gids=set(),
                           hold_qty=hold, extra=copy.deepcopy(mkx(now9)), extra_ok=True, now_ts=now9)
    fl9 = b._daily_flows(conn, ser9, G, today, live9, frozenset(), FX)
    for r9 in ser9:
        if r9["date"] in fl9:
            r9["flow"] = fl9[r9["date"]][0]
    att9 = b._daily_attrib(conn, ser9, G, today, live9, frozenset(), mkx(now9), real={"rbd": {}, "lpf": {}, "stk": {}, "unv": {}})
    conn.close()
    return att9.get("10-09") or {}, fl9.get("10-09")


print("[1] 지난날 · B 지금 시세가 그날가의 몇 배든 나머지 ≈ 0")
for k1 in (0.49, 0.52, 2.5, None):
    a1, f1 = build(None if k1 is None else P_DAY * k1)
    chk(a1.get("rest") is not None and abs(a1["rest"]) < 0.02 and not a1.get("np") and f1 is not None and abs(f1[0]) < 0.02,
        "B 지금 시세 %s배: 나머지 ≈ 0 · 레그 가격 있음 · 입출금 0" % k1, (a1.get("rest"), a1.get("np"), a1.get("tr"), f1))
print("[2] 반례 — 같은 심볼 다른 토큰(외부 유입 · 짝 없음) = 입출금 레그 버림 → 지금 시세 판정 종전(A 가격 강제 안 함)")
a2, f2 = build(0.001, ext=True)
a3, _f3 = build(P_DAY * 0.9, ext=True)
chk(a2.get("np") == 1 and not a3.get("np"), "지금 시세 0.001(묶음 밖) = 레그 가격 없음(np 1 · 종전) · 0.9배 = 종전처럼 묶음가", (a2.get("np"), a3.get("np"), f2))
print("[3] 단위 — nopx_flow_px")
Z = [Decimal(0)] * 3
L3 = {3: [Decimal(-100)] + Z, 4: [Decimal(-1)] + Z, 2: [Decimal(5)] + Z, 5: [Decimal(-1000)] + Z, 6: [Decimal(-10)] + Z}
M3 = {3: {"EXF_DEPOSIT": Decimal(100)}, 4: {"EXF_DEPOSIT": Decimal(1)}, 5: {"EXF_DEPOSIT": Decimal(100)}, 6: {"EXF_DEPOSIT": Decimal(10)}}
F3 = {("d", 3): 0.2, ("d", 2): 0.2, ("e", 4): 0.3, ("d", 5): 0.2, ("d", 6): 0.2}
chk(view_attur.nopx_flow_px(L3, M3, {6}, {2: 0.2}, F3, "d") == {3: 0.2},
    "그날 순수량 0 · 자기 가격 없는 · 그날 입출금 가격 있는 그룹만(2 자기 가격 · 4 다른 날 · 5 전일 미평가 재고 900 판 꼴 · 6 기초 잔고/선물 = 종전)", None)
T.finish()
