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
    def fx_at(self, ms):
        return FX

    def candle_usd(self, sym, ms):
        return None

    def flush(self):
        pass


def unit_builder():
    b = object.__new__(web.StateBuilder)
    b.daily = {"_v": web.DAILY_V, "_risk_rev": ""}
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


def mkx(now_ts):
    return {"ub": 0.0, "fiat": 0.0, "lp": 0.0, "ubs": {}, "ub_tl": {}, "krw_up": 0.0, "krw_other": 0.0, "rate": FX, "krw_up_tl": None,
            "xsrc": {"now": {"ts": now_ts, "ku": 0.0, "kb": 0.0, "ub": {}, "rest": 0.0},
                     "base": {"ku": [0.0, now_ts], "kb": [0.0, now_ts]}, "tl": {"ku": [], "kb": []}, "first": {}}}


def close(a, b9, tol=0.01):
    return a is not None and b9 is not None and abs(float(a) - float(b9)) < tol


NOW = E(10, 10, 12, 0, 0)
dfp = getattr(histcurve, "disc_fp", lambda G9: "")
T0 = E(8, 1, 0, 0, 0)
TDISC = E(10, 8, 21, 0, 0)
PX = {"2": 2.0}


def mkG(disc=True, q=1000):
    g2 = {"gid": 2, "sym": "TKN", "is_stable": False, "qty_timeline": [(int(T0), Decimal(q))] if disc else [(int(TDISC), Decimal(q))]}
    if disc:
        g2["disc_tl"] = [(int(TDISC), Decimal(q))]
    return {1: {"gid": 1, "sym": "USDC", "is_stable": True, "qty_timeline": [(int(E(7, 1)), Decimal(100000))]}, 2: g2}


HOLD = {1: Decimal(100000), 2: Decimal(1000)}


def pin_all(b):
    for m9, r9 in ((9, range(11, 31)), (10, range(1, 10))):
        for d9 in r9:
            b.daily_px[iso(m9, d9)] = {"p": dict(PX), "k": {"2": "live"},
                                       "xv": {"v": xparts.GEN, "p": {"ku": [0.0, "snap"], "kb": [0.0, "snap"], "ub": [{}, "snap"], "rest": [0.0, "snap"]},
                                              "fx": FX, "how": "live"}}


def run(b, G, now_ts=NOW, hold=None):
    return b._daily_series(G, D(10, 10), {}, {2: 2.0}, ca_gids={2}, ex_gids=set(), skip_gids=set(), pending_gids=set(),
                           hold_qty=dict(hold or HOLD), extra=copy.deepcopy(mkx(now_ts)), extra_ok=True, now_ts=now_ts)


def vals(ser):
    return {r["date"]: r["val"] for r in ser}


def old_entry(val, src="calc", snap=None):
    e = {"val": float(val), "usdt": FX, "kimp": None, "g": {"1": 100000.0}, "x": 0.0, "src": src, "st": "1", "xraw": 0.0}
    if snap:
        e["snap"] = int(snap)
    return e


reset_files()
b = unit_builder()
pin_all(b)
for d9 in range(1, 9):
    b.daily[iso(10, d9)] = old_entry(100000)
b.daily[iso(10, 5)] = old_entry(100000, src="live", snap=E(10, 5, 23, 55, 0))
json.dump(b.daily, open(web.DAILY_PATH, "w"))
G1 = mkG()
FP = dfp(G1)
s1 = vals(run(b, G1))
chk(FP and all(close(s1.get("10-%02d" % d9), 102000) for d9 in range(1, 9)), "J1 발견 전 날(10/1~10/8 — 계산·실시간 마감) = 다시 계산 100,000 + 1,000 × $2(원래 있던 보유)",
    {"10-%02d" % d9: s1.get("10-%02d" % d9) for d9 in range(1, 9)})
chk(all((b.daily.get(iso(10, d9)) or {}).get("dq") == FP for d9 in range(1, 10)), "J1 동결 항목 지문 dq = 지금 지문", {d9: (b.daily.get(iso(10, d9)) or {}).get("dq") for d9 in range(1, 10)})
chk(close(s1.get("09-20"), 102000) and close(s1.get("10-10"), 102000), "J1 창 앞쪽 날·오늘도 같은 정의(계단 없음)", (s1.get("09-20"), s1.get("10-10")))
b.daily[iso(10, 3)]["val"] = 102001.0
json.dump(b.daily, open(web.DAILY_PATH, "w"))
s1b = vals(run(b, G1, NOW + 60))
chk(close(s1b.get("10-03"), 102001), "J1 두 번째 빌드 = 다시 계산 없음(1회)", s1b.get("10-03"))
reset_files()
b = unit_builder()
pin_all(b)
for d9 in range(1, 9):
    b.daily[iso(10, d9)] = old_entry(100000)
json.dump(b.daily, open(web.DAILY_PATH, "w"))
G0 = mkG(disc=False)
s0 = vals(run(b, G0, hold={1: Decimal(100000), 2: Decimal(1000)}))
chk(dfp(G0) == "" and close(s0.get("10-05"), 100000) and (b.daily.get(iso(10, 5)) or {}).get("dq") == "",
    "J1 disc 없는 설치본 = 옛 계산 그대로(발견 시각 제자리) · 표식 dq ''", (s0.get("10-05"), b.daily.get(iso(10, 5))))

reset_files()
b = unit_builder()
pin_all(b)
sn9 = {"date": iso(10, 9), "ts": E(10, 9, 23, 58, 0), "val": 100000.0, "usdt": FX, "kimp": None, "g": {"1": 100000.0}, "x": 0.0, "defer": False,
       "p": {}, "xv": {"v": 1, "p": {"kb": [0.0, "snap"], "rest": [0.0, "snap"]}, "fx": FX, "ts": int(E(10, 9, 23, 58, 0))}}
b.daily["_live_ok"] = dict(sn9)
b.daily["_live"] = dict(sn9)
s2 = vals(run(b, mkG()))
chk(close(s2.get("10-09"), 102000) and (b.daily.get(iso(10, 9)) or {}).get("dq") == FP,
    "J2 발견 전 지문의 어제 마감 스냅숏 = 재료로 안 씀 → 계산 102,000(종전이면 100,000 으로 굳음)", (s2.get("10-09"), b.daily.get(iso(10, 9))))
sn9b = dict(sn9, dq=FP, val=102000.0, g={"1": 100000.0, "2": 2000.0}, p={"2": 2.0})
reset_files()
b = unit_builder()
pin_all(b)
b.daily["_live_ok"] = dict(sn9b)
b.daily["_live"] = dict(sn9b)
run(b, mkG())
chk((b.daily.get(iso(10, 9)) or {}).get("src") == "live" and (b.daily.get(iso(10, 9)) or {}).get("dq") == FP,
    "J2 지금 지문의 스냅숏 = 종전대로 마감 재료(실시간 마감 live)", b.daily.get(iso(10, 9)))

reset_files()
b = unit_builder()
pin_all(b)
run(b, mkG())
for d9 in (3, 4):
    b.daily[iso(10, d9)] = old_entry(100000)
json.dump(b.daily, open(web.DAILY_PATH, "w"))
s3 = vals(run(b, mkG(), NOW + 60))
chk(close(s3.get("10-03"), 102000) and close(s3.get("10-04"), 102000), "J3 롤백 뒤 옛 코드가 다시 굳힌 날 = 새 코드 첫 빌드에 다시 102,000", (s3.get("10-03"), s3.get("10-04")))
G3 = mkG(q=1500)
s3b = vals(run(b, G3, NOW + 120, hold={1: Decimal(100000), 2: Decimal(1500)}))
chk(close(s3b.get("10-03"), 103000) and (b.daily.get(iso(10, 3)) or {}).get("dq") == dfp(G3), "J3 새 지문 = 다시 계산 103,000", s3b.get("10-03"))

before4 = {k9: v9 for k9, v9 in s3b.items() if k9 != "10-10"}
os.remove(web.DAILY_PATH)
s4 = vals(run(b, G3, NOW + 180, hold={1: Decimal(100000), 2: Decimal(1500)}))
chk(all(close(s4.get(k9), v9) for k9, v9 in before4.items()), "J4 캐시 삭제 뒤 처음부터 = 같은 지난날 값", {k9: (v9, s4.get(k9)) for k9, v9 in list(before4.items())[-4:]})

reset_files()
b = unit_builder()
pin_all(b)
G5 = {1: {"gid": 1, "sym": "USDC", "is_stable": True, "qty_timeline": [(int(E(7, 1)), Decimal(100000))]},
      2: {"gid": 2, "sym": "USDT", "is_stable": True, "qty_timeline": [(int(T0), Decimal(5000))], "disc_tl": [(int(TDISC), Decimal(5000))]}}
H5 = {1: Decimal(100000), 2: Decimal(5000)}
s5 = run(b, G5, hold=H5)
pth9, pxp9 = os.path.join(S, "chJ.json"), os.path.join(S, "chJ_px.json")


def hrow(v, kind="hc"):
    return [float(v), None, 0, kind, 0]


xp0 = {"ku": [0.0, "snap"], "kb": [0.0, "snap"], "ub": [{}, "snap"], "rest": [0.0, "snap"]}
pre9 = {"_v": histcurve.HIST_V, "d": {iso(8, 20): hrow(100000), iso(8, 21): hrow(100000), iso(8, 22): hrow(100000, "dc")},
        "s": {iso(8, 20): [100000.0, 0.0, 0.0, 0, 0.0], iso(8, 21): [100000.0, 0.0, 0.0, 0, 0.0]},
        "x": {k9: {"p": xp0, "fx": FX, "cut": 0.0, "x": 0.0, "xc": 0.0, "uat": histcurve.day_end(k9) - 1} for k9 in (iso(8, 20), iso(8, 21))},
        "meta": {"pending": False, "flow_pending": False}}
common.atomic_write_json(pth9, pre9)
HJ = histcurve.HistCurve(path=pth9, px_path=pxp9)


def kit_of(G9, H9, ser9):
    return histcurve.make_kit("2026-10-10", G9, H9, set(), set(), {}, set(), {}, {}, {}, [], mkx(NOW), ser9, b.daily,
                              xkit=copy.deepcopy(b.__dict__.get("_x_kit")))


kJ = kit_of(G5, H5, s5)
daysJ = histcurve.days_between("2026-07-01", "2026-10-10")
HJ.px["fx"] = {"lo": "2026-07-01", "hi": "2026-10-10", "st": "ok", "p": {d9: FX for d9 in daysJ}}
HJ.run_once(kJ, cap=0, now=NOW)
dJ = HJ.st.get("d") or {}
cJ = (HJ.st.get("s") or {}).get(iso(8, 20)) or []
chk(close((dJ.get(iso(8, 20)) or [None])[0], 105000) and cJ[6:7] == [kJ.get("dq")] and kJ.get("dq"),
    "J5 장기 곡선 hc 행(8/20 — 옛 되감기 100,000) = 1회 다시 계산 105,000 · 행 지문(cov 7번째 칸)", (dJ.get(iso(8, 20)), cJ))
chk(close((dJ.get(iso(8, 22)) or [None])[0], 105000) and (dJ.get(iso(8, 22)) or [None] * 4)[3] in ("hc", "hp"),
    "J5 창 밖 dc 행(동결 항목 없음 · 옛 값 100,000) = hc 로 다시 105,000", dJ.get(iso(8, 22)))
dJ[iso(8, 20)] = [105001.0] + list(dJ[iso(8, 20)][1:])
HJ.st["d"] = dJ
HJ.run_once(kJ, cap=0, now=NOW + 60)
chk(close(((HJ.st.get("d") or {}).get(iso(8, 20)) or [None])[0], 105001), "J5 두 번째 실행 = 다시 계산 없음(1회)", (HJ.st.get("d") or {}).get(iso(8, 20)))
st9 = HJ.st
st9["d"] = dict(st9["d"], **{iso(8, 20): hrow(100000)})
st9["s"] = dict(st9["s"], **{iso(8, 20): [100000.0, 0.0, 0.0, 0, 0.0]})
common.atomic_write_json(pth9, st9)
HJ2 = histcurve.HistCurve(path=pth9, px_path=pxp9)
HJ2.px["fx"] = HJ.px["fx"]
HJ2.run_once(kJ, cap=0, now=NOW + 120)
chk(close(((HJ2.st.get("d") or {}).get(iso(8, 20)) or [None])[0], 105000), "J5 롤백 뒤 옛 코드가 다시 굳힌 hc 행 = 새 코드 첫 실행에 다시 105,000",
    (HJ2.st.get("d") or {}).get(iso(8, 20)))
G5b = copy.deepcopy(G5)
G5b[2]["qty_timeline"] = [(int(T0), Decimal(7000))]
G5b[2]["disc_tl"] = [(int(TDISC), Decimal(5000)), (int(E(10, 9, 9, 0, 0)), Decimal(2000))]
H5b = {1: Decimal(100000), 2: Decimal(7000)}
b2 = unit_builder()
pin_all(b2)
s5b = b2._daily_series(G5b, D(10, 10), {}, {}, ca_gids=set(), ex_gids=set(), skip_gids=set(), pending_gids=set(), hold_qty=dict(H5b),
                       extra=copy.deepcopy(mkx(NOW)), extra_ok=True, now_ts=NOW)
kJb = histcurve.make_kit("2026-10-10", G5b, H5b, set(), set(), {}, set(), {}, {}, {}, [], mkx(NOW), s5b, b2.daily, xkit=copy.deepcopy(b2.__dict__.get("_x_kit")))
HJ2.run_once(kJb, cap=0, now=NOW + 180)
chk(close(((HJ2.st.get("d") or {}).get(iso(8, 20)) or [None])[0], 107000) and close(((HJ2.st.get("d") or {}).get(iso(8, 21)) or [None])[0], 107000),
    "J5 새 발견(지문 바뀜) = hc 행 다시 107,000", ((HJ2.st.get("d") or {}).get(iso(8, 20)), (HJ2.st.get("d") or {}).get(iso(8, 21))))

reset_files()
b = unit_builder()
pin_all(b)
run(b, mkG())
G_rm = {1: mkG()[1], 2: {"gid": 2, "sym": "TKN", "is_stable": False, "qty_timeline": [(int(E(10, 9, 12, 0, 0)), Decimal(1000))]}}
sK1 = vals(run(b, G_rm, NOW + 60))
chk(close(sK1.get("10-05"), 100000) and (b.daily.get(iso(10, 5)) or {}).get("dq", "x") == "", "K1 30일: 마지막 disc 앵커 제거(지문 '') = 다시 계산 100,000(소급분 빠짐 · 수정 전 102,000 유지)",
    (sK1.get("10-05"), b.daily.get(iso(10, 5))))
reset_files()
b = unit_builder()
pin_all(b)
G6 = {1: {"gid": 1, "sym": "USDC", "is_stable": True, "qty_timeline": [(int(E(7, 1)), Decimal(100000))]},
      2: {"gid": 2, "sym": "USDT", "is_stable": True, "qty_timeline": [(int(T0), Decimal(5000))], "disc_tl": [(int(TDISC), Decimal(5000))]},
      3: {"gid": 3, "sym": "DAI", "is_stable": True, "qty_timeline": [(int(E(7, 1)), Decimal(300))]}}
H6 = {1: Decimal(100000), 2: Decimal(5000), 3: Decimal(300)}
s6 = run(b, G6, hold=H6)
pthK, pxpK = os.path.join(S, "chK.json"), os.path.join(S, "chK_px.json")
preK = {"_v": histcurve.HIST_V, "d": {iso(8, 20): hrow(1), iso(8, 22): hrow(1, "dc")}, "s": {iso(8, 20): [1.0, 0.0, 0.0, 0, 0.0]},
        "x": {iso(8, 20): {"p": xp0, "fx": FX, "cut": 0.0, "x": 0.0, "xc": 0.0, "uat": histcurve.day_end(iso(8, 20)) - 1}},
        "meta": {"pending": False, "flow_pending": False}}
common.atomic_write_json(pthK, preK)
HK = histcurve.HistCurve(path=pthK, px_path=pxpK)
HK.px["fx"] = {"lo": "2026-07-01", "hi": "2026-10-10", "st": "ok", "p": {d9: FX for d9 in daysJ}}


def kitK(G9, H9, skip=()):
    return histcurve.make_kit("2026-10-10", G9, H9, set(skip), set(), {}, set(), {}, {}, {}, [], mkx(NOW), s6, b.daily,
                              xkit=copy.deepcopy(b.__dict__.get("_x_kit")))


def hv(H9, k9):
    return ((H9.st.get("d") or {}).get(k9) or [None])[0]


HK.run_once(kitK(G6, H6), cap=0, now=NOW)
chk(close(hv(HK, iso(8, 20)), 105300) and close(hv(HK, iso(8, 22)), 105300), "K 전제: 장기 곡선 8/20(hc)·8/22(창 밖 dc → hc) = 105,300(소급 포함)", (hv(HK, iso(8, 20)), hv(HK, iso(8, 22))))
G6r = copy.deepcopy(G6)
G6r[2] = {"gid": 2, "sym": "USDT", "is_stable": True, "qty_timeline": [(int(E(10, 9, 12, 0, 0)), Decimal(5000))]}
HK.run_once(kitK(G6r, H6), cap=0, now=NOW + 60)
chk(close(hv(HK, iso(8, 20)), 100300) and close(hv(HK, iso(8, 22)), 100300),
    "K2 장기 곡선: 마지막 disc 앵커 제거(지문 '') = hc 행 다시 100,300(소급분 빠짐 · 수정 전 105,300 유지)", (hv(HK, iso(8, 20)), hv(HK, iso(8, 22))))
HK.run_once(kitK(G6, H6), cap=0, now=NOW + 120)
HK.run_once(kitK(G6, H6, skip={2}), cap=0, now=NOW + 180)
chk(close(hv(HK, iso(8, 20)), 100300), "K3 장기 곡선: disc 그룹이 격리로 바뀜 = hc 행 다시 100,300(격리 몫 빠짐 · 수정 전 105,300 유지)", hv(HK, iso(8, 20)))
HK.run_once(kitK(G6, H6, skip={2, 3}), cap=0, now=NOW + 240)
chk(close(hv(HK, iso(8, 20)), 100000), "K4 (RECORD) 장기 곡선: 다른 그룹(DAI 300) 격리 전환 = 그 그룹이 있던 hc 행 다시 100,000", hv(HK, iso(8, 20)))
HK.run_once(kitK(G6, H6, skip={2}), cap=0, now=NOW + 300)
chk(close(hv(HK, iso(8, 20)), 100300), "K4 격리 해제 = 다시 100,300", hv(HK, iso(8, 20)))

reset_files()
T.finish()
