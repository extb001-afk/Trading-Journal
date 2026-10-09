#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import copy
import inspect
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import common

json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(os.environ["TJ_BASE"], "config.json"), "w"))
import histcurve
import web

chk = T.chk


def xkw(b):
    return {"xkit": copy.deepcopy(b.__dict__.get("_x_kit"))} if "xkit" in inspect.signature(histcurve.make_kit).parameters else {}
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


def mkx(now_ts, ku=0.0, kb=0.0, ub=None, rest=0.0, tl_ku=(), tl_kb=(), first=None, base_ku_ts=None, ub_tl=None, ku_now=None):
    ub = ub or {}
    uu = sum(a[1] for a in ub.values())
    return {"ub": uu, "fiat": (ku + kb) / FX, "lp": rest, "ubs": copy.deepcopy(ub), "ub_tl": ub_tl or {},
            "krw_up": ku, "krw_other": kb, "rate": FX, "krw_up_tl": None,
            "xsrc": {"now": {"ts": now_ts, "ku": ku if ku_now is None else ku_now, "kb": kb, "ub": copy.deepcopy(ub), "rest": rest},
                     "base": {"ku": [ku, base_ku_ts or now_ts], "kb": [kb, now_ts]},
                     "tl": {"ku": list(tl_ku) if tl_ku is not None else None, "kb": list(tl_kb) if tl_kb is not None else None},
                     "first": first or {}}}


def run(b, G, hold, today, now_ts, extra, live_px=None, ca=()):
    return b._daily_series(G, today, {}, live_px or {}, ca_gids=set(ca), ex_gids=set(), skip_gids=set(), pending_gids=set(),
                           hold_qty=hold, extra=copy.deepcopy(extra), extra_ok=True, now_ts=now_ts)


def xvo(b, k):
    e = b.daily_px.get(k) if isinstance(b.daily_px.get(k), dict) else {}
    return e.get("xv") if isinstance(e.get("xv"), dict) else {"p": {}}


def val_of(series, m, d):
    k = "%02d-%02d" % (m, d)
    return next((r["val"] for r in series if r["date"] == k), None)


def inval():
    if os.path.exists(web.DAILY_PATH):
        os.remove(web.DAILY_PATH)


def hist_run(b, G, hold, today, series, extra, tmp, now_ts, pre=None):
    pth, pxp = os.path.join(S, tmp + ".json"), os.path.join(S, tmp + "_px.json")
    if pre is not None:
        common.atomic_write_json(pth, pre)
    H = histcurve.HistCurve(path=pth, px_path=pxp)
    kit = histcurve.make_kit(today.strftime("%Y-%m-%d"), G, hold, set(), set(), {}, set(), {}, {}, {}, [], copy.deepcopy(extra), series, b.daily, **xkw(b))
    lo9 = min(histcurve.FIRST_DAY, kit.get("first") or histcurve.FIRST_DAY)
    days = histcurve.days_between(lo9, today.strftime("%Y-%m-%d"))
    H.px["fx"] = {"lo": lo9, "hi": today.strftime("%Y-%m-%d"), "st": "ok", "p": {d9: FX for d9 in days}}
    H.run_once(kit, cap=0, now=now_ts)
    code, body = H.view(None)
    return H, {r[0]: r for r in body["days"]}


reset_files()
NOW = E(10, 9, 12, 0, 0)
X1 = mkx(NOW, kb=0.0, rest=10000.0, tl_kb=[(E(3, 1) - 3600, 14e6), (E(10, 1) - 3600, -14e6)], first={"rest": E(1, 1) - 86400})
b = unit_builder()
s1 = run(b, {}, {}, D(10, 9), NOW, X1)
chk(abs((val_of(s1, 9, 28) or 0) - 20000) < 0.01 and abs(val_of(s1, 10, 5) - 10000) < 0.01, "B cs313/n 30일: 9/28 = LP + 빗썸 · 10/5 = LP 만", (val_of(s1, 9, 28), val_of(s1, 10, 5)))
px1 = copy.deepcopy(b.daily_px)
s1b = run(b, {}, {}, D(10, 9), NOW + 60, X1)
chk(b.daily_px == px1 and s1b[:-1] == s1[:-1], "A 빌드 두 번 = daily_px · 지난날 값 동일", None)
inval()
s1c = run(b, {}, {}, D(10, 9), NOW + 120, X1)
chk(b.daily_px == px1 and [r["val"] for r in s1c[:-1]] == [r["val"] for r in s1[:-1]], "A 캐시 삭제(무효화) 뒤 = 같은 값 · 같은 daily_px", None)
X1L = mkx(NOW, kb=0.0, rest=12000.0, tl_kb=X1["xsrc"]["tl"]["kb"], first={"rest": E(1, 1) - 86400})
s1d = run(b, {}, {}, D(10, 9), NOW + 180, X1L)
chk([r["val"] for r in s1d[:-1]] == [r["val"] for r in s1[:-1]] and abs(s1d[-1]["val"] - 12000) < 0.01, "A 지금 LP 를 바꿔도 지난날 불변(오늘만 바뀜)", None)
inval()
s1e = run(b, {}, {}, D(10, 9), NOW + 240, X1L)
chk([r["val"] for r in s1e[:-1]] == [r["val"] for r in s1[:-1]], "A LP 바뀐 뒤 무효화해도 지난날 불변(고정 구성요소)", None)
H1, v1 = hist_run(b, {}, {}, D(10, 9), s1, X1, "ch1", NOW)
chk(abs(v1[iso(2, 1)][1] - 10000) < 0.01 and abs(v1[iso(5, 1)][1] - 20000) < 0.01, "B cs313/n 장기: 2/1 = LP 만 · 5/1 = LP + 빗썸(입금 전 LP 안 지워짐)",
    (v1[iso(2, 1)][1], v1[iso(5, 1)][1]))
chk(abs(v1[iso(1, 1)][1] - 10000) < 0.01 and abs(v1[iso(9, 9)][1] - 20000) < 0.01, "B 장기 1/1(LP 시작 뒤) · 9/9", (v1[iso(1, 1)][1], v1[iso(9, 9)][1]))
chk(abs(v1[iso(9, 9)][1] - val_of(s1, 9, 10)) < 0.01, "G 경계 9/9(장기) = 9/10(30일) — 같은 규칙(입출금 없음 = 같은 값)", (v1[iso(9, 9)][1], val_of(s1, 9, 10)))
X1t = copy.deepcopy(X1)
X1t["xsrc"]["tl"]["kb"] = sorted(X1t["xsrc"]["tl"]["kb"] + [(E(4, 1) - 3600, -7e6), (E(4, 2) - 3600, 7e6)])
kit_t = histcurve.make_kit("2026-10-09", {}, {}, set(), set(), {}, set(), {}, {}, {}, [], X1t, s1, b.daily, **xkw(b))
if "xk" in kit_t:
    kit_t["xk"]["src"]["tl"]["kb"] = X1t["xsrc"]["tl"]["kb"]
H1.run_once(kit_t, cap=0, now=NOW + 300)
c9, b9 = H1.view(None)
v1t = {r[0]: r for r in b9["days"]}
chk(abs(v1t[iso(4, 1)][1] - 15000) < 0.01 and abs(v1t[iso(5, 1)][1] - 20000) < 0.01 and (H1.st["s"].get(iso(4, 1)) or [None])[0] == 0.0,
    "B cs313/s 늦게 채워진 이력 = 그날 x 만 정정(4/1 $15,000) · 가격 부분 그대로 · 세대 올림 없음", (v1t[iso(4, 1)][1], H1.st["s"][iso(4, 1)]))

reset_files()
NOW = E(9, 30, 12, 0, 0)
G2 = {1: {"gid": 1, "sym": "USDT", "is_stable": True, "qty_timeline": [(E(1, 5), Decimal(2500))]}}
H2 = {1: Decimal(2500)}
b = unit_builder()
b.daily_px[iso(9, 20)] = {"p": {}, "k": {}, "x": 100.0, "xk": "live"}
b.daily[iso(9, 20)] = {"val": 2600.0, "usdt": FX, "g": {"1": 2500.0}, "x": 100.0, "src": "calc", "st": ""}
X2 = mkx(NOW, kb=0.0, rest=1500.0, tl_kb=[])
s2 = run(b, G2, H2, D(9, 30), NOW, X2)
chk(abs(val_of(s2, 9, 20) - 2600) < 0.01 and xvo(b, iso(9, 20))["p"].get("rest") == [100.0, "snap"], "C cs317/n 실제 마감 x(재구축 보존) = 빗썸 0·빈 이력·지금 LP 1,500 에도 그대로",
    (val_of(s2, 9, 20), xvo(b, iso(9, 20))))
s2b = run(b, G2, H2, D(9, 30), NOW + 60, X2)
inval()
s2c = run(b, G2, H2, D(9, 30), NOW + 120, X2)
chk(abs(val_of(s2b, 9, 20) - 2600) < 0.01 and abs(val_of(s2c, 9, 20) - 2600) < 0.01, "C cs317/s 다음 빌드·무효화 재계산 = 같은 값(2,600)", (val_of(s2b, 9, 20), val_of(s2c, 9, 20)))
reset_files()
b = unit_builder()
X3 = mkx(NOW, kb=14e6, rest=10000.0, tl_kb=[])
s3 = run(b, {}, {}, D(9, 30), NOW, X3)
X3b = mkx(NOW, kb=14e6, rest=12000.0, tl_kb=[])
s3b = run(b, {}, {}, D(9, 30), NOW + 60, X3b)
inval()
s3c = run(b, {}, {}, D(9, 30), NOW + 120, X3b)
chk(abs(val_of(s3, 9, 29) - 20000) < 0.01 and abs(val_of(s3b, 9, 29) - 20000) < 0.01 and abs(val_of(s3c, 9, 29) - 20000) < 0.01,
    "C cs317/n 계산 동결 = LP 가 바뀌어도 $20,000 · 무효화 뒤에도", (val_of(s3, 9, 29), val_of(s3b, 9, 29), val_of(s3c, 9, 29)))

reset_files()
b = unit_builder()
G4 = {1: {"gid": 1, "sym": "USDT", "is_stable": True, "qty_timeline": [(E(1, 5), Decimal(100))]}}
H4 = {1: Decimal(100)}
X4 = mkx(NOW, kb=14e6, ub={"QQQ": [1000.0, 2000.0]}, tl_kb=[])
s4 = run(b, G4, H4, D(9, 30), NOW, X4)
chk(abs(val_of(s4, 9, 25) - 12100) < 0.01 and (xvo(b, iso(9, 25))["p"].get("ub") or [None])[0] == {"QQQ": 1000.0}, "D cs321/n 매칭 전 $12,100 · 미매칭 분해 ub 고정", val_of(s4, 9, 25))
G4b = {**G4, 2: {"gid": 2, "sym": "QQQ", "is_stable": False, "qty_timeline": [(E(9, 1), Decimal(1000))]}}
H4b = {**H4, 2: Decimal(1000)}
X4b = mkx(NOW, kb=14e6, ub={}, tl_kb=[], ub_tl={2: [(int(E(9, 1)), Decimal(1000))]})
s4b = run(b, G4b, H4b, D(9, 30), NOW + 60, X4b, live_px={2: 2.0}, ca=(2,))
inval()
s4c = run(b, G4b, H4b, D(9, 30), NOW + 120, X4b, live_px={2: 2.0}, ca=(2,))
chk(abs(val_of(s4b, 9, 25) - 12100) < 0.01 and abs(val_of(s4c, 9, 25) - 12100) < 0.01, "D cs321/n 원장이 QQQ 를 세게 돼도(소급·무효화 재계산) $12,100 — 이중 계상 없음",
    (val_of(s4b, 9, 25), val_of(s4c, 9, 25)))
reset_files()
b = unit_builder()
X5 = mkx(NOW, ub={"ABC": [10.0, 100.0]}, tl_kb=[])
s5 = run(b, G4, H4, D(9, 30), NOW, X5)
G5 = {**G4, 3: {"gid": 3, "sym": "ABC", "is_stable": False, "qty_timeline": [(E(9, 1), Decimal(10))]}}
H5 = {**H4, 3: Decimal(10)}
inval()
s5b = run(b, G5, H5, D(9, 30), NOW + 60, mkx(NOW, tl_kb=[], ub_tl={3: [(int(E(9, 1)), Decimal(10))]}), live_px={3: 10.0}, ca=(3,))
chk(abs(val_of(s5, 9, 25) - 200) < 0.01 and abs(val_of(s5b, 9, 25) - 200) < 0.01, "D cs321/s 빼기 0 이던 날의 미매칭 분해 유지 → 원장 편입 뒤 무효화 = $200 그대로",
    (val_of(s5, 9, 25), val_of(s5b, 9, 25)))

reset_files()
b = unit_builder()
b.daily_px[iso(9, 20)] = {"p": {}, "k": {}, "x": 10000.0, "xk": "calc", "xbt": 1}
b.daily[iso(9, 20)] = {"val": 10000.0, "usdt": FX, "g": {}, "x": 10000.0, "src": "calc", "st": "", "xbt": 1}
X6 = mkx(NOW, kb=7e6, rest=5000.0, tl_kb=[])
s6 = run(b, {}, {}, D(9, 30), NOW, X6)
v6 = val_of(s6, 9, 20)
chk(abs(v6 - 10000) < 0.01 and xvo(b, iso(9, 20)).get("how") == "mig:calc", "E cs321/n 옛 calc(표식 있음) = 한 번 규칙대로 다시(오너 결정)", (v6, xvo(b, iso(9, 20))))
X6b = mkx(NOW, ku=1.4e6, kb=7e6, rest=5000.0, tl_kb=[], tl_ku=None)
s6b = run(b, {}, {}, D(9, 30), NOW + 60, X6b)
inval()
s6c = run(b, {}, {}, D(9, 30), NOW + 120, X6b)
chk(abs(val_of(s6b, 9, 20) - v6) < 0.01 and abs(val_of(s6c, 9, 20) - v6) < 0.01, "E cs321/n 그 뒤 업비트 원화 이월분이 생겨도 지난날 그대로 · 무효화 뒤에도",
    (val_of(s6b, 9, 20), val_of(s6c, 9, 20)))
x7 = copy.deepcopy(b.daily_px)
s6d = run(b, {}, {}, D(9, 30), NOW + 180, X6b)
chk(b.daily_px == x7, "A 이관 두 번(다음 빌드) = 같은 daily_px", None)
reset_files()
b = unit_builder()
for d9 in range(1, 30):
    b.daily_px[iso(9, d9)] = {"p": {}, "k": {}, "x": 20000.0, "xk": "live"}
    b.daily[iso(9, d9)] = {"val": 20000.0, "usdt": FX, "g": {}, "x": 20000.0, "src": "live", "st": ""}
X8 = mkx(NOW, ku=28e6, kb=14e6, tl_ku=[], tl_kb=[])
s8 = run(b, {}, {}, D(9, 30), NOW, X8)
chk(abs(val_of(s8, 9, 10) - 30000) < 0.01 and xvo(b, iso(9, 10))["p"].get("kb") == [14e6, "tl"], "E cs321/n 빗썸 안 담은 옛 마감 + 빗썸 이력값(출처 tl) = $30,000",
    (val_of(s8, 9, 10), xvo(b, iso(9, 10))))
H8, v8 = hist_run(b, {}, {}, D(9, 30), s8, X8, "ch8", NOW)
chk(abs(v8[iso(8, 31)][1] - 30000) < 0.01 and abs(v8[iso(8, 31)][1] - val_of(s8, 9, 1)) < 0.01, "E 장기 곡선 경계 전날(8/31) = $30,000 = 9/1(경계 차 0)",
    (v8[iso(8, 31)][1], val_of(s8, 9, 1)))

reset_files()
b = unit_builder()
X9 = mkx(NOW, kb=0.0, rest=1000.0, tl_kb=[(E(6, 1), 7e6), (E(9, 15), -7e6)], first={"rest": E(1, 1)})
s9 = run(b, {}, {}, D(9, 30), NOW, X9)
pre = {"_v": histcurve.HIST_V, "d": {iso(7, 1): [999.0 + 50000.0, None, 1, "hc", 50000.0]}, "s": {iso(7, 1): [999.0, 0.0, 50000.0, 0]},
       "meta": {"pending": False, "flow_pending": False}}
H9, v9 = hist_run(b, {}, {}, D(9, 30), s9, X9, "ch9", NOW, pre=pre)
chk(abs(v9[iso(7, 1)][1] - (999.0 + 1000.0 + 5000.0)) < 0.01 and (H9.st["s"].get(iso(7, 1)) or [None])[0] == 999.0 and len(H9.st["s"].get(iso(7, 1)) or ()) == 5,
    "F cs321/n·s 옛 행 = 가격 부분(999) 그대로 · x 만 규칙으로(LP 1,000 + 빗썸 ₩7M) · 세대 올림 없음", (v9[iso(7, 1)], H9.st["s"].get(iso(7, 1))))
H9.run_once(histcurve.make_kit("2026-09-30", {}, {}, set(), set(), {}, set(), {}, {}, {}, [], copy.deepcopy(X9), s9, b.daily, **xkw(b)), cap=0, now=NOW + 60)
chk(abs(H9.view(None)[1]["days"][[r[0] for r in H9.view(None)[1]["days"]].index(iso(7, 1))][1] - 6999.0) < 0.01, "F 다시 실행 = 같은 값(멱등)", None)

reset_files()
b = unit_builder()
b.daily_px[iso(9, 25)] = {"p": {}, "k": {}, "x": 5000.0 / 1.0, "xk": "live",
                          "xv": {"v": 1, "p": {"kb": [7e6, "snap"], "rest": [0.0, "snap"]}, "fx": FX, "rt": {"bithumb": int(E(9, 25) - 300)}, "ts": int(E(9, 25) - 300)}}
b.daily[iso(9, 25)] = {"val": 5000.0, "usdt": FX, "g": {}, "x": 5000.0, "src": "live", "st": ""}
X10 = mkx(NOW, kb=14e6, tl_kb=[(E(9, 1), 14e6)])
s10 = run(b, {}, {}, D(9, 30), NOW, X10)
chk(abs(val_of(s10, 9, 20) - 5000) < 0.01 and (xvo(b, iso(9, 20))["p"].get("kb") or [None, None])[1] == "carry", "G 자가 점검: 관측 ↔ 이력 어긋남 → 그 전 날 빗썸 = 가까운 관측 이월(₩7M)",
    (val_of(s10, 9, 20), xvo(b, iso(9, 20))))
chk(abs(val_of(s10, 9, 27) - 10000) < 0.01, "G 자가 점검: 어긋난 관측 뒤 날 = 이력 되감기(₩14M)", val_of(s10, 9, 27))
reset_files()
b = unit_builder()
b._daily_seed = {iso(9, 18): {"x": 3000.0, "g": {}}}
s11 = run(b, {}, {}, D(9, 30), NOW, mkx(NOW, kb=0.0, rest=50.0, tl_kb=[]))
chk(abs(val_of(s11, 9, 18) - 3000) < 0.01 and xvo(b, iso(9, 18)).get("how") == "seed", "G 시드(옛 마감 백업) = 합계 보존 쪼개기", (val_of(s11, 9, 18), xvo(b, iso(9, 18))))
reset_files()
b = unit_builder()
b.px.fx_none = True
s12 = run(b, {}, {}, D(9, 30), NOW, mkx(NOW, kb=2.8e6, tl_kb=[]))
e12 = xvo(b, iso(9, 20))
chk(abs(val_of(s12, 9, 20) - 2000) < 0.01 and e12["p"].get("kb") == [2.8e6, "tl"] and e12.get("fx") == FX, "G 환율 없는 날 = 원화는 원 단위 그대로 + 쓴 환율(대체값) 기록", e12)
reset_files()
b = unit_builder()
X13 = mkx(NOW, ku=4.2e6, tl_ku=[(E(9, 22), 2.8e6)], base_ku_ts=E(9, 28, 12), ku_now=None)
s13 = run(b, {}, {}, D(9, 30), NOW, X13)
chk(abs(val_of(s13, 9, 20) - 1000) < 0.01 and abs(val_of(s13, 9, 25) - 3000) < 0.01, "G 업비트 낡음 = 그 잔고 시각 기준 되감기(9/20 ₩1.4M · 9/25 ₩4.2M)",
    (val_of(s13, 9, 20), val_of(s13, 9, 25)))

for defer9, lab9 in ((False, "마감 스냅숏(_live_ok)"), (True, "유예 스냅숏(부분 동결)")):
    reset_files()
    b = unit_builder()
    NOWh = E(10, 9, 12, 0, 0)
    sn9 = {"date": iso(10, 8), "ts": E(10, 8, 23, 58, 0), "val": 500.0, "usdt": FX, "kimp": None, "g": {}, "x": 500.0, "defer": defer9, "p": {},
           "xv": {"v": 1, "p": {"kb": [0.0, "snap"], "rest": [500.0, "snap"]}, "fx": FX, "ts": int(E(10, 8, 23, 58, 0))}}
    b.daily["_live"] = copy.deepcopy(sn9)
    if not defer9:
        b.daily["_live_ok"] = copy.deepcopy(sn9)
    Xh1 = mkx(NOWh, rest=500.0, ub={"QQQ": [1000.0, 2000.0]}, tl_kb=[])
    sh1 = run(b, {}, {}, D(10, 9), NOWh, Xh1)
    v1h = val_of(sh1, 10, 8)
    Xh2 = mkx(NOWh, rest=500.0, ub={"QQQ": [1000.0, 3000.0]}, tl_kb=[])
    inval()
    b.daily["_live"] = copy.deepcopy(sn9)
    if not defer9:
        b.daily["_live_ok"] = copy.deepcopy(sn9)
    sh2 = run(b, {}, {}, D(10, 9), NOWh + 600, Xh2)
    chk(v1h is not None and abs(v1h - 2500) < 0.01 and abs((val_of(sh2, 10, 8) or 0) - v1h) < 0.01,
        "H cv333 " + lab9 + " 재동결 = 처음 채운 이월(QQQ $2,000) 그대로 — 지금 평가($3,000)로 다시 매기지 않음", (v1h, val_of(sh2, 10, 8), xvo(b, iso(10, 8))))

import rabby
note9 = {"first": "2026-09-01", "d": {"2026-09-01": 10000.0, "2026-09-05": 12000.0}}
dv9 = rabby.day_values(note9, ["2026-08-31", "2026-09-01", "2026-09-03", "2026-09-06"], "2026-10-09", 15000.0)
rows9 = [{"date": "08-31", "val": 1.0}, {"date": "09-01", "val": 1.0}, {"date": "09-03", "val": 1.0}, {"date": "09-06", "val": 1.0}]
rabby.daily_overlay(rows9, note9, "2026-10-09", 15000.0)
chk(dv9 == {"2026-09-01": 10000.0, "2026-09-03": 10000.0, "2026-09-06": 12000.0}
    and [r9.get("rb") for r9 in rows9] == [None, 10000.0, 10000.0, 12000.0], "I day_values = daily_overlay 와 같은 규칙(첫날 전 없음 · 기록 없는 날 이월)", (dv9, rows9))
if "rb_days" in inspect.signature(histcurve.make_kit).parameters:
    dc9 = {"2026-08-25": {"val": 100000.0, "usdt": FX, "xraw": 500.0, "x": 500.0, "g": {}, "src": "live"}}
    xk9 = {"src": {"now": {"ts": NOW, "ku": 0.0, "kb": 0.0, "ub": {}, "rest": 0.0}}, "obs": {}, "days": {"2026-08-25": {"p": {"rest": [500.0, "snap"]}, "fx": FX}}}
    kit9 = histcurve.make_kit("2026-10-09", {}, {}, set(), set(), {}, set(), {}, {}, {}, [], {}, [{"date": "09-10", "val": 1.0}], dc9, xkit=xk9,
                              rb_days={"2026-08-25": 10000.0})
    dcv9 = (kit9.get("dcv") or {}).get("2026-08-25")
else:
    dcv9 = None
chk(dcv9 is not None and abs(dcv9[0] - 110000.0) < 0.01 and dcv9[1] == round(110000.0 * FX), "I cv334 창 밖 dc 행 값 = 동결 항목(봇 $100,000) + 그날 Rabby $10,000", dcv9)

reset_files()
b = unit_builder()
NOWj = E(10, 9, 12, 0, 0)
b.daily_px[iso(10, 5)] = {"p": {}, "k": {}, "x": 500.0, "xk": "calc",
                          "xv": {"v": 1, "p": {"kb": [0.0, "snap"], "rest": [500.0, "snap"]}, "fx": FX, "ts": int(E(10, 5) - 300)}}
b.daily[iso(10, 5)] = {"val": 500.0, "usdt": FX, "g": {}, "x": 500.0, "src": "partial", "st": ""}
json.dump(b.daily, open(web.DAILY_PATH, "w"))
sj = run(b, {}, {}, D(10, 9), NOWj, mkx(NOWj, rest=500.0, ub={"QQQ": [1000.0, 2000.0]}, tl_kb=[]))
cj = b.daily.get(iso(10, 5)) or {}
chk(cj.get("src") == "partial" and abs((val_of(sj, 10, 5) or 0) - 2500) < 0.01 and (cj.get("xu") or {}).get("QQQ") == [1000.0, 2000.0],
    "J cv336 이관으로 채운 미매칭 코인(QQQ $2,000) = 동결 val 2,500 + 동결 항목 xu 에 기록", (val_of(sj, 10, 5), cj))

def obs_day(b, m, d, rest):
    import xparts
    b.daily_px[iso(m, d)] = {"p": {}, "k": {}, "xv": {"v": xparts.GEN, "p": {"ku": [0.0, "snap"], "kb": [0.0, "snap"], "ub": [{}, "snap"],
                                                                         "rest": [rest, "snap"]}, "fx": FX, "how": "obs"}}


NOWk = E(10, 9, 12, 0, 0)
reset_files()
b = unit_builder()
obs_day(b, 9, 9, 7000.0)
Xk1 = mkx(NOWk, rest=7000.0, tl_kb=[], first={"rest": None})
sk1 = run(b, {}, {}, D(10, 9), NOWk, Xk1)
Hk1, vk1 = hist_run(b, {}, {}, D(10, 9), sk1, Xk1, "chk1", NOWk)
chk(iso(8, 10) not in vk1 or abs(vk1[iso(8, 10)][1]) < 0.01, "K NK2① LP 없음 · 현금 관측 9/9 부터 → 60일 전(8/10) = 0(오늘 현금을 지난날로 끌고 가지 않음)",
    vk1.get(iso(8, 10)))
chk(abs((val_of(sk1, 9, 20) or 0) - 7000) < 0.01 and abs(vk1.get(iso(9, 9), [0, 0])[1] - 7000) < 0.01, "K NK2① 관측 뒤 날(9/20) · 관측일(9/9) = 현금 $7,000",
    (val_of(sk1, 9, 20), vk1.get(iso(9, 9))))
chk(abs(float(((b.daily_px.get("_xfirst") or {}).get("rest")) or 0) - E(9, 9)) < 1, "K NK2① 현금 첫 관측 시각 저장(관측 보관 기간 밖으로 밀려나도 늦어지지 않게)",
    b.daily_px.get("_xfirst"))
reset_files()
b = unit_builder()
obs_day(b, 9, 9, 7000.0)
Xk2 = mkx(NOWk, rest=7000.0 + 10000.0, tl_kb=[], first={"rest": E(9, 29) - 3600})
sk2 = run(b, {}, {}, D(10, 9), NOWk, Xk2)
chk(abs((val_of(sk2, 9, 19) or 0) - 7000) < 0.01, "K NK2② LP 9/29 시작 · 현금 9/9 부터 → 9/19 = 현금만($7,000 — 종전 0)", val_of(sk2, 9, 19))
Hk2, vk2 = hist_run(b, {}, {}, D(10, 9), sk2, Xk2, "chk2", NOWk)
chk(iso(9, 1) not in vk2 or abs(vk2[iso(9, 1)][1]) < 0.01, "K NK2② 현금 첫 관측(9/9) 전 날(9/1) = 0", vk2.get(iso(9, 1)))
b.daily_px.pop(iso(9, 9), None)
sk3 = run(b, {}, {}, D(10, 9), NOWk + 60, Xk2)
chk(abs((val_of(sk3, 9, 19) or 0) - 7000) < 0.01, "K NK2③ 관측 기록이 사라져도 저장된 첫 관측 시각으로 9/19 = 현금 그대로", val_of(sk3, 9, 19))
reset_files()
b = unit_builder()
run(b, {}, {}, D(10, 9), NOWk, mkx(NOWk, rest=0.0, tl_kb=[], first={"rest": None}))
dpx_before = json.load(open(web.DAILY_PX_PATH)) if os.path.exists(web.DAILY_PX_PATH) else {}
run(b, {}, {}, D(10, 9), NOWk + 60, mkx(NOWk + 60, rest=7000.0, tl_kb=[], first={"rest": None}))
dpx_disk = json.load(open(web.DAILY_PX_PATH)) if os.path.exists(web.DAILY_PX_PATH) else {}
chk("_xfirst" not in dpx_before and abs(float((dpx_disk.get("_xfirst") or {}).get("rest") or 0) - int(NOWk + 60)) < 1,
    "K NK2⑤ cv402 첫 관측 시각만 바뀐 빌드 = daily_px 파일에도 저장(메모리만 아님)", (dpx_before.get("_xfirst"), dpx_disk.get("_xfirst")))
reset_files()
b = unit_builder()
sk4 = run(b, {}, {}, D(10, 9), NOWk, mkx(NOWk, rest=500.0, tl_kb=[], first={}))
chk(abs((val_of(sk4, 9, 15) or 0) - 500) < 0.01 and "_xfirst" not in b.daily_px, "K NK2④ 첫 활동 시각 모름 = 자르지 않음(종전 이월) · 저장 없음", val_of(sk4, 9, 15))

reset_files()
T.finish()
