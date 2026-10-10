#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import copy
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import common

json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(os.environ["TJ_BASE"], "config.json"), "w"))
import histcurve
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
    fx_none = False

    def fx_at(self, ms):
        return None if self.fx_none else FX

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


def reset_files():
    for p9 in (web.DAILY_PATH, web.DAILY_PX_PATH):
        if os.path.exists(p9):
            os.remove(p9)


def mkx(now_ts, rest=0.0):
    return {"ub": 0.0, "fiat": 0.0, "lp": rest, "ubs": {}, "ub_tl": {}, "krw_up": 0.0, "krw_other": 0.0, "rate": FX, "krw_up_tl": None,
            "xsrc": {"now": {"ts": now_ts, "ku": 0.0, "kb": 0.0, "ub": {}, "rest": rest},
                     "base": {"ku": [0.0, now_ts], "kb": [0.0, now_ts]}, "tl": {"ku": [], "kb": []}, "first": {}}}


def pin_x(b, m, d, rest, kind="snap", ts=None, px=None):
    xv = {"v": xparts.GEN, "p": {"ku": [0.0, "snap"], "kb": [0.0, "snap"], "ub": [{}, "snap"], "rest": [float(rest), kind]}, "fx": FX, "how": "live"}
    if ts is not None:
        xv["ts"] = int(ts)
    b.daily_px[iso(m, d)] = {"p": dict(px or {}), "k": {k9: "live" for k9 in (px or {})}, "xv": xv}


def run(b, G, hold, today, now_ts, extra, live_px=None, ca=()):
    return b._daily_series(G, today, {}, live_px or {}, ca_gids=set(ca), ex_gids=set(), skip_gids=set(), pending_gids=set(),
                           hold_qty=hold, extra=copy.deepcopy(extra), extra_ok=True, now_ts=now_ts)


def val_of(series, m, d):
    k = "%02d-%02d" % (m, d)
    return next((r["val"] for r in series if r["date"] == k), None)


def close(a, b9, tol=0.01):
    return a is not None and b9 is not None and abs(float(a) - float(b9)) < tol


def usdc(qty_tl, lp_tl, gid=1):
    g9 = {"gid": gid, "sym": "USDC", "is_stable": True, "qty_timeline": [(int(t), Decimal(str(q))) for t, q in qty_tl]}
    g9["lp_tl"] = [(int(t), Decimal(str(q))) for t, q in lp_tl]
    return g9


reset_files()
NOW = E(10, 10, 12, 0, 0)
TDEP, TREM = E(10, 7, 15, 0, 0), E(10, 9, 10, 0, 0)
GA = {1: usdc([(E(9, 1), 100000)], [(TDEP, 30000), (TREM, -30000)])}
HA = {1: Decimal(100000)}


def pin_a(b, kind="snap", rm_ts=None):
    for d9 in range(11, 31):
        pin_x(b, 9, d9, 0.0)
    for d9 in range(1, 10):
        lp9 = d9 in (7, 8)
        pin_x(b, 10, d9, (15.0 if kind == "carry" else 30015.0) if lp9 else 0.0, kind=kind if lp9 else "snap", ts=E(10, d9, 23, 58, 0))


b = unit_builder()
pin_a(b)
sA = run(b, GA, HA, D(10, 10), NOW, mkx(NOW, 0.0))
chk(close(val_of(sA, 10, 6), 100000), "A 예치 전날 = 지갑 $100,000", val_of(sA, 10, 6))
chk(close(val_of(sA, 10, 7), 100015) and close(val_of(sA, 10, 8), 100015),
    "A LP 열린 날(관측) = 지갑 몫 70,000 + LP 평가 30,015 = $100,015(수정 전 $130,015 = 원금 이중)", (val_of(sA, 10, 7), val_of(sA, 10, 8)))
chk(close(val_of(sA, 10, 9), 100000) and close(val_of(sA, 10, 10), 100000), "A 회수 날·오늘 = $100,000", (val_of(sA, 10, 9), val_of(sA, 10, 10)))
c9 = b.daily.get(iso(10, 8)) or {}
chk(close(c9.get("val"), 100015) and close((c9.get("g") or {}).get("1"), 70000), "A 동결 항목 = 그룹 평가 70,000(지갑) · val 100,015", c9)
reset_files()
b = unit_builder()
pin_a(b, kind="carry")
sA2 = run(b, GA, HA, D(10, 10), NOW, mkx(NOW, 0.0))
chk(close(val_of(sA2, 10, 8), 100015), "A2 이월 날(rest carry — LP 평가 없음) = 지갑에 원금 그대로 100,000 + 15(종전과 같음 · 원금 사라지지 않음)", val_of(sA2, 10, 8))
reset_files()
b = unit_builder()
GA3 = {1: usdc([(E(9, 1), 100000)], [(TDEP, 30000), (E(10, 8, 23, 59, 30), -30000)])}
pin_a(b)
sA3 = run(b, GA3, HA, D(10, 10), NOW, mkx(NOW, 0.0))
chk(close(val_of(sA3, 10, 8), 100015), "A3 관측(23:58) 뒤 같은 날 회수 = 관측 시각 기준 지갑 몫 70,000 + 평가 30,015", val_of(sA3, 10, 8))

reset_files()
TDB = E(10, 4, 16, 0, 0)
GB = {1: usdc([(E(9, 1), 100000)], [(TDB, 30000)])}
HB = {1: Decimal(70000)}
b = unit_builder()
for d9 in range(1, 10):
    pin_x(b, 10, d9, 30015.0 if d9 >= 4 else 0.0)
sB = run(b, GB, HB, D(10, 10), NOW, mkx(NOW, 30025.0))
chk(close(val_of(sB, 10, 3), 100000), "B 예치 전 날 = 지갑 $100,000(수정 전 $70,000 — 지금 LP 원금만큼 모자람)", val_of(sB, 10, 3))
chk(close(val_of(sB, 10, 5), 100015) and close(val_of(sB, 10, 10), 100025), "B 예치 뒤 날 = 70,000 + 30,015 · 오늘 = 70,000 + 30,025", (val_of(sB, 10, 5), val_of(sB, 10, 10)))

reset_files()
T1, T2, T3 = E(10, 2, 12, 0, 0), E(10, 5, 12, 0, 0), E(10, 7, 12, 0, 0)
GC = {1: usdc([(E(9, 1), 50000), (T2, -1000)], [(T1, 10000), (T2, -4000), (T2, -1000), (T3, 3000)]),
      2: {"gid": 2, "sym": "ETH", "is_stable": False, "qty_timeline": [(int(E(9, 1)), Decimal(10)), (int(T2), Decimal("0.5"))],
          "lp_tl": [(int(T1), Decimal(5)), (int(T2), Decimal(-2))]}}
HC = {1: Decimal(41000), 2: Decimal("7.5")}
PXE = {"2": 2000.0}
b = unit_builder()
for d9 in range(11, 31):
    pin_x(b, 9, d9, 0.0, px=PXE)
for d9 in range(1, 10):
    r9 = 0.0 if d9 < 2 else 20050.0 if d9 < 5 else 11030.0 if d9 < 7 else 14035.0
    pin_x(b, 10, d9, r9, px=PXE)
sC = run(b, GC, HC, D(10, 10), NOW, mkx(NOW, 14040.0), live_px={2: 2000.0}, ca=(2,))
exp9 = {(10, 1): 70000, (10, 3): 50000 + 20050, (10, 5): 59000 + 11030, (10, 6): 59000 + 11030, (10, 8): 56000 + 14035, (10, 10): 56000 + 14040}
got9 = {k9: val_of(sC, *k9) for k9 in exp9}
chk(all(close(got9[k9], v9) for k9, v9 in exp9.items()), "C 여러 LP·부분 회수·풀 안 전환·ETH = 날마다 지갑 수량 × 가격 + 그날 LP 평가(수정 전 예치 전 날 $56,000)",
    {"%02d-%02d" % k9: (got9[k9], v9) for k9, v9 in exp9.items()})
gC = (b.daily.get(iso(10, 3)) or {}).get("g") or {}
chk(close(gC.get("1"), 40000) and close(gC.get("2"), 10000), "C 10/3 동결 그룹 평가 = USDC 40,000 · ETH 5 × 2,000", gC)

kitC = histcurve.make_kit("2026-10-10", GC, HC, set(), {2}, {}, set(), {}, {2: 2000.0}, {}, [], mkx(NOW, 14040.0), sC, b.daily,
                          xkit=copy.deepcopy(b.__dict__.get("_x_kit")))
days9 = ["2026-10-01", "2026-10-03", "2026-10-05", "2026-10-08"]
qC = histcurve.rewind(kitC, days9)
expq9 = {"2026-10-01": (50000, 10), "2026-10-03": (40000, 5), "2026-10-05": (44000, 7.5), "2026-10-08": (41000, 7.5)}
chk(all(close((qC.get(1) or {}).get(d9), expq9[d9][0]) and close((qC.get(2) or {}).get(d9), expq9[d9][1]) for d9 in days9),
    "D 장기 곡선 rewind = 30일 곡선과 같은 지갑 수량(관측 날 LP 보정)", {d9: ((qC.get(1) or {}).get(d9), (qC.get(2) or {}).get(d9)) for d9 in days9})
xkC = copy.deepcopy(b.__dict__.get("_x_kit"))
for d9 in list((xkC or {}).get("days") or {}):
    xkC["days"][d9]["p"]["rest"][1] = "carry"
kitC2 = histcurve.make_kit("2026-10-10", GC, HC, set(), {2}, {}, set(), {}, {2: 2000.0}, {}, [], mkx(NOW, 14040.0), sC, b.daily, xkit=xkC)
qC2 = histcurve.rewind(kitC2, ["2026-10-01"])
chk(close((qC2.get(1) or {}).get("2026-10-01"), 42000) and close((qC2.get(2) or {}).get("2026-10-01"), 7), "D 이월 날 = 종전 되감기 그대로(보정 없음)",
    ((qC2.get(1) or {}).get("2026-10-01"), (qC2.get(2) or {}).get("2026-10-01")))

LQ = getattr(web, "DAILY_LQ_V", 1)


def old_frozen(b, m, d, val, src="calc", usdt=FX, g=None, x=0.0):
    b.daily[iso(m, d)] = {"val": float(val), "usdt": usdt, "kimp": None, "g": {"1": float(g if g is not None else val)}, "x": float(x), "src": src, "st": "1",
                          "xraw": float(x)}


def setup_e(b, usdt=FX):
    b.daily["_risk_rev"] = ""
    pin_a(b)
    for d9 in range(1, 7):
        old_frozen(b, 10, d9, 100000)
    for d9 in (7, 8):
        old_frozen(b, 10, d9, 130015, usdt=usdt, g=100000, x=30015)
    b.daily[iso(10, 5)]["src"] = "live"
    b.daily[iso(10, 5)]["val"] = 99999.0
    b.daily[iso(10, 5)]["g"] = {"1": 99999.0}
    json.dump(b.daily, open(web.DAILY_PATH, "w"))


reset_files()
b = unit_builder()
setup_e(b)
sE = run(b, GA, HA, D(10, 10), NOW, mkx(NOW, 0.0))
cE = b.daily.get(iso(10, 8)) or {}
chk(close(val_of(sE, 10, 7), 100015) and close(val_of(sE, 10, 8), 100015) and cE.get("lq") == LQ,
    "E 옛 계산으로 굳은 LP 날($130,015) = 첫 빌드에 다시 계산 $100,015 · 표식 lq", (val_of(sE, 10, 7), val_of(sE, 10, 8), cE))
chk(close(val_of(sE, 10, 5), 99999) and "lq" not in (b.daily.get(iso(10, 5)) or {}), "E 실시간 마감(live) 날 = 값 그대로 · 표식 없음", b.daily.get(iso(10, 5)))
chk(close(val_of(sE, 10, 6), 100000) and (b.daily.get(iso(10, 6)) or {}).get("lq") == LQ, "E 보정 0 인 옛 계산 날 = 값 그대로 · 확인 표식만(다음에 다시 안 봄)",
    b.daily.get(iso(10, 6)))
disk9 = json.load(open(web.DAILY_PATH))
chk((disk9.get(iso(10, 8)) or {}).get("lq") == LQ and close((disk9.get(iso(10, 8)) or {}).get("val"), 100015), "E 파일에도 저장", disk9.get(iso(10, 8)))
b.daily[iso(10, 8)]["val"] = 100016.0
json.dump(b.daily, open(web.DAILY_PATH, "w"))
sE2 = run(b, GA, HA, D(10, 10), NOW + 60, mkx(NOW + 60, 0.0))
chk(close(val_of(sE2, 10, 8), 100016), "E 두 번째 빌드 = 다시 계산 없음(1회)", val_of(sE2, 10, 8))
reset_files()
b = unit_builder()
setup_e(b, usdt=None)
b.px.fx_none = True
run(b, GA, HA, D(10, 10), NOW, mkx(NOW, 0.0))
chk(close((b.daily.get(iso(10, 8)) or {}).get("val"), 130015) and "lq" not in (b.daily.get(iso(10, 8)) or {}), "E 유예(환율 없음) = 옛 항목 그대로 · 표식 없음(다음에 다시)",
    b.daily.get(iso(10, 8)))
b.px.fx_none = False
sE3 = run(b, GA, HA, D(10, 10), NOW + 60, mkx(NOW + 60, 0.0))
chk(close(val_of(sE3, 10, 8), 100015) and (b.daily.get(iso(10, 8)) or {}).get("lq") == LQ, "E 환율 생긴 다음 빌드 = 다시 계산 $100,015", b.daily.get(iso(10, 8)))
b.daily[iso(10, 8)] = {k9: v9 for k9, v9 in b.daily[iso(10, 8)].items() if k9 != "lq"}
b.daily[iso(10, 8)].update(val=130015.0, g={"1": 100000.0})
json.dump(b.daily, open(web.DAILY_PATH, "w"))
sE4 = run(b, GA, HA, D(10, 10), NOW + 120, mkx(NOW + 120, 0.0))
chk(close(val_of(sE4, 10, 8), 100015), "E 롤백 뒤 옛 코드가 다시 굳힌 날 = 새 코드 첫 빌드에 다시 고침", val_of(sE4, 10, 8))
known9 = {"val", "usdt", "kimp", "g", "x", "src", "st", "xraw", "xu", "x0", "xu0", "drd", "wdt", "snap", "pend", "xs", "why", "est", "xc", "lg", "z",
          "src9", "native_c", "px", "lq", "dq"}
extra9 = sorted({k9 for ck9, c9 in b.daily.items() if not ck9.startswith("_") and isinstance(c9, dict) for k9 in c9} - known9)
chk(not extra9 and not [k9 for k9 in b.daily if k9.startswith("_") and k9 not in ("_v", "_risk_rev", "_live", "_live_ok", "_reset_at")],
    "E 롤백 안전: 동결 항목 = 종전 키 + lq·dq(옛 코드는 모르는 키를 무시) · 메타 키 추가 없음", extra9)

import sqlite3
reset_files()
b = unit_builder()
pin_a(b)
sF = run(b, GA, HA, D(10, 10), NOW, mkx(NOW, 0.0))
conn = sqlite3.connect(":memory:")
conn.execute("CREATE TABLE assets (asset_id INTEGER PRIMARY KEY, kind TEXT, chain TEXT, address TEXT, symbol TEXT, decimals INTEGER, group_id INTEGER)")
conn.execute("CREATE TABLE postings (posting_id INTEGER PRIMARY KEY, source_kind TEXT, source_ns TEXT, source_id TEXT, leg_seq INTEGER, event_ts INTEGER,"
             " asset_id INTEGER, location TEXT, qty_base TEXT, cost_usd TEXT, cost_krw TEXT, leg_kind TEXT, event TEXT)")
conn.execute("INSERT INTO assets VALUES (1, 'token', 'eth', '0xusdc', 'USDC', 6, 1)")
WL, LPL = "wallet:eth:0xa", "lp:eth:0xmgr:7"
for i9, (t9, q9, ev9, lk9, loc9) in enumerate([(TDEP, -30000, "LP_ADD", "move_out", WL), (TDEP, 30000, "LP_ADD", "move_in", LPL),
                                               (TREM, -30000, "LP_REMOVE", "move_out", LPL), (TREM, 30000, "LP_REMOVE", "move_in", WL)]):
    conn.execute("INSERT INTO postings VALUES (?, 'chain_tx', 'eth', ?, ?, ?, 1, ?, ?, NULL, NULL, ?, ?)",
                 (i9 + 1, "0xtx%d" % (i9 // 2), i9 % 2, int(t9), loc9, str(q9 * 10 ** 6), lk9, ev9))
real9 = {"rbd": {}, "lpf": {}, "stk": {}, "unv": {}}
att9 = b._daily_attrib(conn, sF, GA, D(10, 10), {}, frozenset(), mkx(NOW, 0.0), real=real9)
a7, a9 = att9.get("10-07") or {}, att9.get("10-09") or {}
chk(abs(a7.get("rest", 99999)) < 20 and abs(a9.get("rest", 99999)) < 20, "F 예치 날·회수 날 나머지 ≈ 0(LP 평가 − 원금 = 수수료 몫 ±$15 · 수정 전 ±$30,015)",
    ({k9: a7.get(k9) for k9 in ("rest", "xr", "lp")}, {k9: a9.get(k9) for k9 in ("rest", "xr", "lp")}))
chk(close(a7.get("xr", 0) + 0.0, a7.get("rest", 1e9), 0.02) and close(a9.get("xr", 0) + 0.0, a9.get("rest", 1e9), 0.02),
    "F 이름표 '원장 밖 잔고(LP)' = 나머지 그대로(LP 평가 − 원금 이동) — 이름표 합 ≠ 나머지 아님", (a7.get("xr"), a7.get("rest"), a9.get("xr"), a9.get("rest")))
conn.close()

reset_files()
b = unit_builder()
b.daily["_risk_rev"] = ""
GG = {1: usdc([(E(9, 1), 100000)], [(E(10, 3, 12, 0, 0), 30000), (E(10, 7, 12, 0, 0), -30000)])}
for d9 in range(1, 10):
    pin_x(b, 10, d9, 30015.0 if 3 <= d9 <= 6 else 0.0)
b.daily[iso(10, 1)] = {"val": 70000.0, "usdt": FX, "kimp": None, "g": {"1": 70000.0}, "x": 0.0, "src": "calc", "st": "1", "xraw": 0.0}
b.daily[iso(10, 9)] = {"val": 100000.0, "usdt": FX, "kimp": None, "g": {"1": 100000.0}, "x": 0.0, "src": "calc", "st": "1", "xraw": 0.0}
json.dump(b.daily, open(web.DAILY_PATH, "w"))
sG = run(b, GG, {1: Decimal(100000)}, D(10, 10), NOW, mkx(NOW, 0.0))
chk(close(val_of(sG, 10, 1), 100000) and (b.daily.get(iso(10, 1)) or {}).get("lq") == LQ,
    "G lp489#1 LP 열린 동안 옛 코드가 굳힌 날(10/1 $70,000 · 보정 순합 0) = 다시 계산 $100,000(수정 전 표식만 → $70,000 유지)", (val_of(sG, 10, 1), b.daily.get(iso(10, 1))))
chk(close(val_of(sG, 10, 9), 100000) and (b.daily.get(iso(10, 9)) or {}).get("lq") == LQ, "G 관측 뒤 LP 레그 없는 날(10/9) = 표식만(값 그대로)", b.daily.get(iso(10, 9)))
chk(close(val_of(sG, 10, 4), 100015), "G LP 열린 날(10/4) = 지갑 몫 70,000 + 평가 30,015", val_of(sG, 10, 4))

reset_files()
b = unit_builder()
b.daily["_risk_rev"] = ""
TH1, TH2 = E(9, 4, 12, 0, 0), E(9, 8, 12, 0, 0)
GH = {1: usdc([(E(8, 20), 100000)], [(TH1, 30000), (TH2, -30000)])}
for d9 in range(1, 31):
    pin_x(b, 9, d9, 30015.0 if 4 <= d9 <= 7 else 0.0)
for d9 in range(1, 10):
    pin_x(b, 10, d9, 0.0)
b.daily[iso(9, 5)] = {"val": 130015.0, "usdt": FX, "kimp": None, "g": {"1": 100000.0}, "x": 30015.0, "src": "calc", "st": "1", "xraw": 30015.0}
b.daily[iso(9, 2)] = {"val": 100000.0, "usdt": FX, "kimp": None, "g": {"1": 100000.0}, "x": 0.0, "src": "calc", "st": "1", "xraw": 0.0}
json.dump(b.daily, open(web.DAILY_PATH, "w"))
sH = run(b, GH, {1: Decimal(100000)}, D(10, 10), NOW, mkx(NOW, 0.0))
cH = b.daily.get(iso(9, 5)) or {}
chk(close(cH.get("val"), 100015) and cH.get("lq") == LQ and len(sH) == 30 and sH[0]["date"] == "09-11",
    "H lp489#2 창 밖 옛 계산 동결(9/5 $130,015) = 다시 계산 $100,015 · 표식 lq · 화면 행은 30일 그대로", (cH, len(sH), sH[0]["date"]))
chk(close((b.daily.get(iso(9, 2)) or {}).get("val"), 100000) and (b.daily.get(iso(9, 2)) or {}).get("lq") == LQ, "H 창 밖 보정 없는 날(9/2) = 값 그대로 · 표식만",
    b.daily.get(iso(9, 2)))
kitH = histcurve.make_kit("2026-10-10", GH, {1: Decimal(100000)}, set(), set(), {}, set(), {}, {}, {}, [], mkx(NOW, 0.0), sH, b.daily,
                          xkit=copy.deepcopy(b.__dict__.get("_x_kit")))
chk(close(((kitH.get("dcv") or {}).get(iso(9, 5)) or [None])[0], 100015), "H 장기 곡선 dc 행 재료(dcv) = 고친 값 $100,015", (kitH.get("dcv") or {}).get(iso(9, 5)))
import wow2
tmH = T.safe(wow2.tm, iso(9, 5), hist=None, daily=b.daily, dpx=b.daily_px)
chk(isinstance(tmH, dict) and close(tmH.get("total"), 100015), "H 타임머신(그날 보유 재현 — 동결 항목 우선) 합계 = $100,015",
    {k9: (tmH or {}).get(k9) for k9 in ("ok", "total", "src", "error", "_exc")})

reset_files()
b = unit_builder()
for d9 in range(1, 31):
    pin_x(b, 9, d9, 30015.0 if 4 <= d9 <= 7 else 0.0)
for d9 in range(1, 10):
    pin_x(b, 10, d9, 0.0)
sI = run(b, GH, {1: Decimal(100000)}, D(10, 10), NOW, mkx(NOW, 0.0))
pth9, pxp9 = os.path.join(S, "chI.json"), os.path.join(S, "chI_px.json")
e95 = histcurve.day_end(iso(9, 5)) - 1
xp95 = {"ku": [0.0, "snap"], "kb": [0.0, "snap"], "ub": [{}, "snap"], "rest": [30015.0, "snap"]}
pre9 = {"_v": histcurve.HIST_V, "d": {iso(9, 5): [130015.0, None, 0, "hc", 0], iso(9, 2): [100000.0, None, 0, "hc", 0]},
        "s": {iso(9, 5): [100000.0, 0.0, 0.0, 0, 0.0], iso(9, 2): [100000.0, 0.0, 0.0, 0, 0.0]},
        "x": {iso(9, 5): {"p": xp95, "fx": FX, "cut": 0.0, "x": 30015.0, "xc": 0.0, "uat": e95},
              iso(9, 2): {"p": dict(xp95, rest=[0.0, "snap"]), "fx": FX, "cut": 0.0, "x": 0.0, "xc": 0.0, "uat": histcurve.day_end(iso(9, 2)) - 1}},
        "meta": {"pending": False, "flow_pending": False}}
common.atomic_write_json(pth9, pre9)
HI = histcurve.HistCurve(path=pth9, px_path=pxp9)
kitI = histcurve.make_kit("2026-10-10", GH, {1: Decimal(100000)}, set(), set(), {}, set(), {}, {}, {}, [], mkx(NOW, 0.0), sI, b.daily,
                          xkit=copy.deepcopy(b.__dict__.get("_x_kit")))
daysI = histcurve.days_between("2026-08-01", "2026-10-10")
HI.px["fx"] = {"lo": "2026-08-01", "hi": "2026-10-10", "st": "ok", "p": {d9: FX for d9 in daysI}}
HI.run_once(kitI, cap=0, now=NOW)
dI = HI.st.get("d") or {}
LQH = getattr(histcurve, "LQ_V", 1)


def row_lq(H, k9):
    c9 = (H.st.get("s") or {}).get(k9)
    return isinstance(c9, list) and c9[5:6] == [LQH]


chk(close((dI.get(iso(9, 5)) or [None])[0], 100015) and row_lq(HI, iso(9, 5)),
    "I lp489#2 장기 곡선 hc 행(9/5 $130,015 — 옛 되감기) = 1회 다시 계산 $100,015 · 행 표식(cov 6번째 칸)", (dI.get(iso(9, 5)), (HI.st.get("s") or {}).get(iso(9, 5))))
chk(close((dI.get(iso(9, 2)) or [None])[0], 100000), "I 예치 전 hc 날(9/2 — 관측 뒤 레그가 있어 다시 계산 · 같은 값 $100,000)", dI.get(iso(9, 2)))
dI[iso(9, 5)] = [100016.0] + list(dI[iso(9, 5)][1:])
HI.st["d"] = dI
HI.run_once(kitI, cap=0, now=NOW + 60)
chk(close(((HI.st.get("d") or {}).get(iso(9, 5)) or [None])[0], 100016), "I 두 번째 실행 = 다시 계산 없음(1회)", (HI.st.get("d") or {}).get(iso(9, 5)))
HI.st["x"][iso(9, 5)]["fx"] = FX + 1.0
HI.run_once(kitI, cap=0, now=NOW + 90)
dI = dict(HI.st.get("d") or {})
dI[iso(9, 5)] = [100017.0] + list(dI[iso(9, 5)][1:])
HI.st["d"] = dI
HI.run_once(kitI, cap=0, now=NOW + 100)
chk(row_lq(HI, iso(9, 5)) and close(((HI.st.get("d") or {}).get(iso(9, 5)) or [None])[0], 100017),
    "I lp495 원장 밖 금액만 다시 써도 행 표식 유지 → 다음 실행 다시 계산 없음", ((HI.st.get("s") or {}).get(iso(9, 5)), (HI.st.get("d") or {}).get(iso(9, 5))))
st9 = HI.st
st9["d"] = dict(st9["d"], **{iso(9, 5): [130015.0, None, 0, "hc", 0]})
st9["s"] = dict(st9["s"], **{iso(9, 5): [100000.0, 0.0, 0.0, 0, 0.0]})
st9["meta"] = dict(st9.get("meta") or {}, lq=LQH)
common.atomic_write_json(pth9, st9)
HI2 = histcurve.HistCurve(path=pth9, px_path=pxp9)
HI2.px["fx"] = HI.px["fx"]
HI2.run_once(kitI, cap=0, now=NOW + 120)
chk(close(((HI2.st.get("d") or {}).get(iso(9, 5)) or [None])[0], 100015) and row_lq(HI2, iso(9, 5)),
    "I lp495 롤백 중 옛 코드가 다시 굳힌 hc 행($130,015 · meta lq 남음) = 새 코드 첫 실행에 다시 교정 $100,015", ((HI2.st.get("d") or {}).get(iso(9, 5)), HI2.st.get("meta")))

reset_files()
T.finish()
