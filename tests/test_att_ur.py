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


for p9 in (paths.state("daily_cache.json"), paths.state("daily_px.json")):
    if os.path.exists(p9):
        os.remove(p9)
NOW = E(10, 10, 12, 0, 0)
T0 = E(9, 1, 0, 0, 0)
TB1, TS1, TB2, TS2, TB3, TF = (E(10, 9, h, 0, 0) for h in (10, 12, 13, 14, 15, 16))
TRADES = [(TB1, "b1", [(1, -18000, 18000, "disp"), (2, 200000, 18000, "acq")]),
          (TS1, "s1", [(2, -610000, 61000, "disp"), (1, 61000, 61000, "acq")]),
          (TB2, "b2", [(1, -2000, 2000, "disp"), (3, 1000, 2000, "acq")]),
          (TS2, "s2", [(3, -400, 1000, "disp"), (1, 1000, 1000, "acq")]),
          (TB3, "b3", [(1, -500, 500, "disp"), (4, 100, 500, "acq")])]
FEE = (TF, "f1", [(1, -1, None, "fee")])


def g(gid, sym, stable, tl):
    return {"gid": gid, "sym": sym, "is_stable": stable, "qty_timeline": [(int(t), Decimal(str(q))) for t, q in tl]}


tl = {1: [(T0, 1000000)], 2: [(T0, 410000)], 3: [], 4: []}
for t9, _s9, legs9 in TRADES + [FEE]:
    for gid9, q9, _c9, _k9 in legs9:
        tl[gid9].append((t9, q9))
G = {1: g(1, "USDC", True, tl[1]), 2: g(2, "MPLX", False, tl[2]), 3: g(3, "TKN", False, tl[3]), 4: g(4, "QQQ", False, tl[4])}
G[2]["flows"] = [{"rbd": {iso(10, 9): Decimal("34800")}}]
G[3]["flows"] = [{"rbd": {iso(10, 9): Decimal("200")}}]
HOLD = {gid9: sum((Decimal(str(q9)) for _t, q9 in v9), Decimal(0)) for gid9, v9 in tl.items()}
PX_OLD, PX_DAY = {"2": 0.09, "3": 2.5, "4": 6.0}, {"2": 0.1, "3": 2.5, "4": 6.0}
b = unit_builder()
for m9, r9 in ((9, range(11, 31)), (10, range(1, 10))):
    for d9 in r9:
        px9 = PX_DAY if (m9, d9) == (10, 9) else PX_OLD
        b.daily_px[iso(m9, d9)] = {"p": dict(px9), "k": {k9: "live" for k9 in px9},
                                   "xv": {"v": xparts.GEN, "p": {"ku": [0.0, "snap"], "kb": [0.0, "snap"], "ub": [{}, "snap"], "rest": [0.0, "snap"]},
                                          "fx": FX, "how": "live"}}
LIVE = {2: 0.1, 3: 2.5, 4: 6.0}
ser = b._daily_series(G, D(10, 10), {}, LIVE, ca_gids={2, 3, 4}, ex_gids=set(), skip_gids=set(), pending_gids=set(),
                      hold_qty=HOLD, extra=copy.deepcopy(mkx(NOW)), extra_ok=True, now_ts=NOW)
conn = sqlite3.connect(":memory:")
conn.execute("CREATE TABLE assets (asset_id INTEGER PRIMARY KEY, kind TEXT, chain TEXT, address TEXT, symbol TEXT, decimals INTEGER, group_id INTEGER)")
conn.execute("CREATE TABLE postings (posting_id INTEGER PRIMARY KEY, source_kind TEXT, source_ns TEXT, source_id TEXT, leg_seq INTEGER, event_ts INTEGER,"
             " asset_id INTEGER, location TEXT, qty_base TEXT, cost_usd TEXT, cost_krw TEXT, leg_kind TEXT, event TEXT)")
DEC = {1: 6, 2: 18, 3: 18, 4: 18}
for aid9, sym9 in ((1, "USDC"), (2, "MPLX"), (3, "TKN"), (4, "QQQ")):
    conn.execute("INSERT INTO assets VALUES (?, 'token', 'eth', ?, ?, ?, ?)", (aid9, "0x%040d" % aid9, sym9, DEC[aid9], aid9))
pid9 = 0
for t9, s9, legs9 in TRADES + [FEE]:
    for seq9, (gid9, q9, c9, k9) in enumerate(legs9):
        pid9 += 1
        conn.execute("INSERT INTO postings VALUES (?, 'chain', 'evm:eth', ?, ?, ?, ?, 'wallet:eth:0xa', ?, ?, NULL, ?, 'SWAP')",
                     (pid9, s9, seq9, int(t9), gid9, str(q9 * 10 ** DEC[gid9]), None if c9 is None else str(c9), k9))
REAL = {"rbd": {iso(10, 9): 35000.0}, "lpf": {}, "stk": {}, "unv": {}}


def run(real=REAL):
    att = b._daily_attrib(conn, ser, G, D(10, 10), LIVE, frozenset(), mkx(NOW), real=real)
    return att, copy.deepcopy(b._att_det_new)


att, det = run()
a9, d9 = att.get("10-09") or {}, (det or {}).get(iso(10, 9)) or {}
u9 = d9.get("ur") or {}
rows9 = {r[0]: r for r in u9.get("rows") or ()}
print("[1] 줄 합 = 분해 ur")
tot9 = sum(r[6] for r in u9.get("rows") or ()) + u9.get("fee", 0) + u9.get("lp", 0) + u9.get("gx", 0) + u9.get("etc", 0)
chk(a9.get("ur") is not None and abs(tot9 - a9["ur"]) < 0.006, "코인 줄 합 + 수수료·가스 + LP + 묶음 차 + 그 밖 = att.ur(센트)", {"ur": a9.get("ur"), "합": tot9, "ur 상세": u9})
chk(abs(a9.get("ur", 0) - (-28301.0)) < 0.01, "합성 ur = 전 레그 × 레그 가격 − 실현 = −$28,301(다 판 MPLX = 그날 평가 없음 → 전일 마감가 0.09 · 수수료 $1)", a9.get("ur"))
chk(abs(u9.get("etc", 9)) < 0.006 and abs(u9.get("fee", 0) + 1) < 0.006 and not u9.get("lp"), "그 밖 = 0 · 수수료·가스 레그 = −$1 · LP 0", u9)
print("[2] 코인 줄")
m9 = rows9.get("MPLX") or [None] * 9
chk(m9[1:9] == [61000.0, 18000.0, 34800.0, -28700.0, 0.0, -28700.0, 18000.0, 0.0],
    "MPLX = 판 돈 $61,000 · 산 돈 $18,000 · 실현 $34,800 · 기존 보유 평가 이동 −$28,700(410,000 × 전일가 0.09 − 원가 8,200) · 그날 산 것 0 · 원가 중 그날 산 몫 $18,000", m9)
k9 = rows9.get("TKN") or [None] * 9
chk(k9[1:9] == [1000.0, 2000.0, 200.0, 0.0, 300.0, 300.0, 800.0, 0.0], "TKN = 600 남김 · 그날 산 코인 평가 변화 +$300(600 × 2.5 − 2,000 × 0.6) · 기존 보유 0", k9)
q9 = rows9.get("QQQ") or [None] * 9
chk(q9[1:9] == [0.0, 500.0, 0.0, 0.0, 100.0, 100.0, 0.0, 0.0], "QQQ 사기만 = 그날 산 코인 평가 변화 +$100(100 × 6 − 500)", q9)
chk("USDC" not in rows9 and u9.get("n") == 3 and [r[0] for r in u9["rows"]] == ["MPLX", "TKN", "QQQ"], "스테이블 줄 없음(정산 쪽은 코인 줄로) · 큰 순", u9.get("rows"))
print("[3] 분해 값·다른 상세 무변")
V2 = {"mk", "top", "etc", "kx", "tr", "fee", "lp", "xo", "rs", "v", "ev", "xm", "ur", "rz", "lpf", "stk", "un", "gx", "rest", "topx", "unp", "op", "fb", "fpx", "np",
      "xr", "xca", "rbv", "dbi"}
chk(all(set(a) <= V2 for a in att.values()) and abs(a9.get("rz", 0) - 35000) < 0.01 and abs(a9.get("tr", 0) - 6699.0) < 0.01,
    "분해 값(att) = 종전 키만 · 실현 $35,000 · 매매 $6,699(상세는 att 를 바꾸지 않음 — 새 값은 줄 상세 'ur' 에만)", a9)
OLD = {"mk", "mkN", "more", "xm", "kx", "unp", "un", "op", "fb", "fl", "rbNew", "pv"}
chk(all(set(dv) - OLD == {"ur"} for k, dv in det.items() if k == iso(10, 9)) and all(set(dv) <= OLD | {"ur"} for dv in det.values()),
    "줄 상세 = 종전 키 + 새 키 'ur' 만", {k: sorted(dv) for k, dv in det.items()})
print("[4] 상한 · v1 날")
G[4]["flows"] = []
cls9 = type("C", (), {"ATT_TRADE_EV": web.StateBuilder.ATT_TRADE_EV, "ATT_DET_CAP": 1})
ub9 = view_attur.UrBuild(conn.execute("SELECT p.event_ts, p.qty_base, a.decimals, a.group_id, p.event, p.leg_kind, p.location, p.leg_seq, p.source_ns,"
                                      " p.source_id, p.cost_usd FROM postings p JOIN assets a ON a.asset_id = p.asset_id").fetchall(),
                         G, frozenset(), cls9.ATT_TRADE_EV, 1)
dd9 = {}
view_attur.attach(dd9, ub9, iso(10, 9), {"ur": a9["ur"], "gx": a9.get("gx", 0)}, {1: [0, Decimal(-1), 0, 0]}, {2: 0.1, 3: 2.5, 4: 6.0}, REAL)
mo9 = (dd9.get("more") or {}).get("ur")
chk(len(dd9["ur"]["rows"]) == 1 and mo9 == [2, 400.0] and dd9["ur"]["n"] == 3
    and abs(sum(r[6] for r in dd9["ur"]["rows"]) + mo9[1] + dd9["ur"]["fee"] + dd9["ur"]["etc"] + dd9["ur"]["gx"] - a9["ur"]) < 0.006,
    "상한 1 = 큰 줄 1 + more['ur'] = [2, $400] · 합 보존", dd9)
print("[5] 심볼 단위 나눔 — 산 그룹 → 판 그룹 이동(같은 심볼)")
GZ = {7: {"gid": 7, "sym": "ZZZ", "is_stable": False}, 8: {"gid": 8, "sym": "ZZZ", "is_stable": False,
      "flows": [{"rbd": {iso(10, 9): Decimal("4100")}}]}}
RZ = [(int(TB1), 100 * 10 ** 18, 18, 7, "SWAP", "acq", "wallet:eth:0xa", 0, "evm:eth", "z1", "500"),
      (int(TS1), -1100 * 10 ** 18, 18, 8, "EXF_SELL", "disp", "exchange:bybit", 0, "bybit:x", "z2", "6600")]
ubz = view_attur.UrBuild(RZ, GZ, frozenset(), web.StateBuilder.ATT_TRADE_EV, 100)
dz = {}
view_attur.attach(dz, ubz, iso(10, 9), {"ur": -4000.0, "gx": 0.0}, {}, {7: 6.0, 8: 6.0}, {"unv": {}})
chk((dz.get("ur") or {}).get("rows") == [["ZZZ", 6600.0, 500.0, 4100.0, -4000.0, 0.0, -4000.0, 500.0, 0.0]] and dz["ur"]["etc"] == 0.0,
    "심볼 순매도 = 그날 산 코인 평가 변화 0 · 기존 보유 평가 이동 −$4,000(그룹별이면 +$100 / −$4,100 로 갈려 서로 지움) · 합 = ur", dz)
att1, det1 = run(real=None)
chk(all("ur" not in (dv or {}) for dv in (det1 or {}).values()), "실현 재료 없는 빌드(v1) = 'ur' 없음", None)
conn.close()
T.finish()
