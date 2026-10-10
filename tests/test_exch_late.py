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


def close(a, b9, tol=0.01):
    return a is not None and b9 is not None and abs(float(a) - float(b9)) < tol


XQ = getattr(web, "_xq_sets", None)
MARK = E(9, 5, 12, 0, 0)
TREC = E(10, 8, 15, 0, 0)
T0 = E(5, 13, 0, 0, 0)
NOW = E(10, 10, 12, 0, 0)

if XQ:
    a0 = XQ([("recon_done_upbit", str(int(NOW))), ("recon_done_exf_binance", str(int(NOW))), ("recon_done_exf_okx", str(int(NOW))), ("other", "1")],
            {"upbit": int(TREC), "binance": int(E(8, 29)), "okx": int(E(10, 1)), "gate": int(E(8, 1))}, MARK)
    chk(a0 == ("binance,okx,upbit", "binance"), "X0 지금 = 대사 마친 거래소 · 기준 = 원본 첫 수집이 표식 전(바이낸스 8/29) — 업비트(10/8)·OKX(10/1)는 표식 뒤 · 대사 표식 시각(재구축 뒤 다시 씀)은 안 봄", a0)
    chk(XQ([("recon_done_exf_bybit", "5")], {}, MARK) == ("bybit", "bybit") and XQ([("recon_done_upbit", "1")], {"upbit": int(TREC)}, 0) == ("upbit", "upbit"),
        "X0 처음 본 때 모름·표식 없음 = 기준에 넣음(값 안 바꾸는 쪽)", None)
else:
    chk(False, "X0 web._xq_sets 있음", None)


def mkx(now_ts, krw=1.4e6, ub=None, dep=None):
    ub = ub or {}
    uu = sum(a9[1] for a9 in ub.values())
    return {"ub": uu, "fiat": krw / FX, "lp": 0.0, "ubs": copy.deepcopy(ub), "ub_tl": {}, "krw_up": krw, "krw_other": 0.0, "rate": FX, "krw_up_tl": None,
            "xsrc": {"now": {"ts": now_ts, "ku": krw, "kb": 0.0, "ub": copy.deepcopy(ub), "rest": 0.0},
                     "base": {"ku": [krw, now_ts], "kb": [0.0, now_ts]}, "tl": {"ku": [(int(dep or E(9, 1, 10, 0, 0)), krw)], "kb": []}, "first": {}}}


G = {1: {"gid": 1, "sym": "USDC", "is_stable": True, "qty_timeline": [(int(E(7, 1)), Decimal(100000))]},
     4: {"gid": 4, "sym": "USDT", "is_stable": True, "qty_timeline": [(int(T0), Decimal(1500)), (int(E(10, 3, 12, 0, 0)), Decimal(500))]}}
HOLD = {1: Decimal(100000), 4: Decimal(2000)}


def pin_old(b, m, d):
    b.daily_px[iso(m, d)] = {"p": {}, "k": {}, "xv": {"v": xparts.GEN, "p": {"ku": [0.0, "carry"], "kb": [0.0, "snap"], "ub": [{}, "carry"], "rest": [0.0, "snap"]},
                                                     "fx": FX, "how": "calc"}}


def old_entry(val=100000.0, src="calc"):
    return {"val": float(val), "usdt": FX, "kimp": None, "g": {"1": 100000.0}, "x": 0.0, "src": src, "st": "1,4", "xraw": 0.0, "lq": 1, "dq": ""}


def run(b, xq="upbit", xqb="", now_ts=NOW, hold=None, x=None):
    kw = {"xq": xq, "xq_base": xqb} if XQ else {}
    return {r["date"]: r["val"] for r in b._daily_series(G, D(10, 10), {}, {}, ca_gids=set(), ex_gids=set(), skip_gids=set(), pending_gids=set(),
                                                           hold_qty=dict(hold or HOLD), extra=copy.deepcopy(x or mkx(now_ts)), extra_ok=True, now_ts=now_ts, **kw)}


def setup(b):
    for m9, r9 in ((9, range(11, 31)), (10, range(1, 8))):
        for d9 in r9:
            pin_old(b, m9, d9)
            b.daily[iso(m9, d9)] = old_entry()
    b.daily[iso(10, 6)]["src"] = "live"
    json.dump(b.daily, open(web.DAILY_PATH, "w"))


reset_files()
b = unit_builder()
setup(b)
v1 = run(b)
chk(all(close(v1.get("10-%02d" % d9), 103000) for d9 in (4, 5, 6, 7)) and close(v1.get("10-02"), 102500) and close(v1.get("10-10"), 103000),
    "X1 지난날(10/2 = USDT 1,500 + 원화 $1,000 · 10/4~10/7 계산·실시간 마감 = USDT 2,000 + 원화) = 거래소 보유 포함 · 오늘과 계단 없음(수정 전 지난날 100,000 → 오늘 +$3,000)",
    {k9: v1.get(k9) for k9 in ("10-02", "10-04", "10-06", "10-07", "10-08", "10-10")})
chk(close(v1.get("09-11"), 102500), "X1 창 앞쪽 날(9/11)도 = 창 시작 앵커 USDT 1,500 + 원화 이력 ₩1.4M(9/1 입금)", v1.get("09-11"))
chk(all((b.daily.get(iso(10, d9)) or {}).get("xq") == "upbit" for d9 in range(1, 10)), "X1 동결 항목 거래소 지문 xq = upbit",
    {d9: (b.daily.get(iso(10, d9)) or {}).get("xq") for d9 in range(1, 10)})
chk(((b.daily_px.get(iso(10, 5)) or {}).get("xv") or {}).get("p", {}).get("ku") == [1.4e6, "tl"], "X1 키 없을 때 정한 업비트 원화 이월 0 → 원화 이력으로 다시(tl)",
    ((b.daily_px.get(iso(10, 5)) or {}).get("xv") or {}).get("p"))
b.daily[iso(10, 5)]["val"] = 103001.0
json.dump(b.daily, open(web.DAILY_PATH, "w"))
v2 = run(b, now_ts=NOW + 60)
chk(close(v2.get("10-05"), 103001), "X2 두 번째 빌드 = 다시 계산 없음(1회)", v2.get("10-05"))
b.daily[iso(10, 5)] = old_entry()
pin_old(b, 10, 5)
json.dump(b.daily, open(web.DAILY_PATH, "w"))
v2b = run(b, now_ts=NOW + 120)
chk(close(v2b.get("10-05"), 103000), "X2 롤백 뒤 옛 코드가 다시 굳힌 날 = 새 코드 첫 빌드에 다시 103,000", v2b.get("10-05"))
reset_files()
b = unit_builder()
setup(b)
v2c = run(b, xq="upbit", xqb="upbit")
chk(close(v2c.get("10-05"), 100000) and (b.daily.get(iso(10, 5)) or {}).get("xq") == "upbit",
    "X2 표식 전부터 있던 거래소(기준 포함 — 라이브) = 옛 값 그대로 · 표식만", (v2c.get("10-05"), b.daily.get(iso(10, 5))))
reset_files()
b = unit_builder()
setup(b)
sn9 = {"date": iso(10, 9), "ts": E(10, 9, 23, 58, 0), "val": 100000.0, "usdt": FX, "kimp": None, "g": {"1": 100000.0}, "x": 0.0, "defer": False, "p": {}, "dq": "",
       "xv": {"v": 1, "p": {"kb": [0.0, "snap"], "rest": [0.0, "snap"]}, "fx": FX, "ts": int(E(10, 9, 23, 58, 0))}}
b.daily["_live_ok"] = dict(sn9)
b.daily["_live"] = dict(sn9)
v3 = run(b)
chk(close(v3.get("10-09"), 103000), "X3 업비트 대사 전 어제 마감 스냅숏(지문 없음) = 재료로 안 씀 → 103,000(종전이면 100,000 으로 굳음)", (v3.get("10-09"), b.daily.get(iso(10, 9))))

reset_files()
b = unit_builder()
for m9, r9 in ((9, range(11, 31)), (10, range(1, 8))):
    for d9 in r9:
        pin_old(b, m9, d9)
v5 = run(b)
chk(close(v5.get("10-05"), 103000) and ((b.daily_px.get(iso(10, 5)) or {}).get("xv") or {}).get("xq") == "upbit",
    "X5 캐시 삭제 뒤 다시 계산 = 업비트 원화 이월 0 고정 풀려 원화 이력 포함 103,000 · 구성요소 지문 xq(수정 전 102,000 — 원화 빠짐)",
    (v5.get("10-05"), ((b.daily_px.get(iso(10, 5)) or {}).get("xv") or {}).get("p")))
reset_files()
b = unit_builder()
for m9, r9 in ((9, range(11, 31)), (10, range(1, 8))):
    for d9 in r9:
        pin_old(b, m9, d9)
v5c = run(b, xq="upbit", xqb="upbit")
chk(close(v5c.get("10-05"), 102000) and ((b.daily_px.get(iso(10, 5)) or {}).get("xv") or {}).get("p", {}).get("ku") == [0.0, "carry"],
    "X5 기준에 든 거래소(표식 전부터 — 라이브) = 고정 구성요소 그대로(이월 0 유지 · 값 무변)", (v5c.get("10-05"), ((b.daily_px.get(iso(10, 5)) or {}).get("xv") or {}).get("p")))

reset_files()
b = unit_builder()
setup(b)
v6a = run(b, x=mkx(NOW, ub={"QQQ": [10.0, 100.0]}))
v6b = run(b, now_ts=NOW + 60, x=mkx(NOW + 60, ub={"QQQ": [10.0, 200.0]}))
v6c = run(b, now_ts=NOW + 120, x=mkx(NOW + 120, ub={"QQQ": [10.0, 300.0]}))
chk(close(v6a.get("10-05"), 103100) and close(v6b.get("10-05"), 103100) and close(v6c.get("10-05"), 103100)
    and ((b.daily_px.get(iso(10, 5)) or {}).get("xv") or {}).get("xq") == "upbit",
    "X6 fc505: 지난날(10/5) = 처음 다시 정한 미매칭 이월 $100 그대로 — 다음 빌드들(지금 $200·$300)에도 무변 · 구성요소 지문 유지(수정 전 빌드마다 지금 값으로)",
    (v6a.get("10-05"), v6b.get("10-05"), v6c.get("10-05"), ((b.daily_px.get(iso(10, 5)) or {}).get("xv") or {}).get("xq")))

reset_files()
b = unit_builder()
setup(b)
ser4 = b._daily_series(G, D(10, 10), {}, {}, ca_gids=set(), ex_gids=set(), skip_gids=set(), pending_gids=set(), hold_qty=dict(HOLD),
                       extra=copy.deepcopy(mkx(NOW)), extra_ok=True, now_ts=NOW, **({"xq": "upbit", "xq_base": ""} if XQ else {}))
pth9, pxp9 = os.path.join(S, "chX.json"), os.path.join(S, "chX_px.json")
xp0 = {"ku": [0.0, "carry"], "kb": [0.0, "snap"], "ub": [{}, "carry"], "rest": [0.0, "snap"]}


def hrow(v, kind="hc"):
    return [float(v), None, 0, kind, 0]


pre9 = {"_v": histcurve.HIST_V, "d": {iso(8, 20): hrow(100000), iso(8, 21): hrow(103000), iso(8, 22): hrow(100000, "dc")},
        "s": {iso(8, 20): [100000.0, 0.0, 0.0, 0, 0.0], iso(8, 21): [102000.0, 0.0, 0.0, 0, 0.0, 1, "", "upbit"]},
        "x": {k9: {"p": xp0, "fx": FX, "cut": 0.0, "x": 0.0, "xc": 0.0, "uat": histcurve.day_end(k9) - 1} for k9 in (iso(8, 20), iso(8, 21))},
        "meta": {"pending": False, "flow_pending": False}}
common.atomic_write_json(pth9, pre9)
HX = histcurve.HistCurve(path=pth9, px_path=pxp9)
kw9 = {"xq": "upbit", "xq_base": ""} if "xq" in histcurve.make_kit.__code__.co_varnames else {}
kitX = histcurve.make_kit("2026-10-10", G, HOLD, set(), set(), {}, set(), {}, {}, {}, [], mkx(NOW), ser4, b.daily, xkit=copy.deepcopy(b.__dict__.get("_x_kit")), **kw9)
daysX = histcurve.days_between("2026-05-01", "2026-10-10")
HX.px["fx"] = {"lo": "2026-05-01", "hi": "2026-10-10", "st": "ok", "p": {d9: FX for d9 in daysX}}
HX.run_once(kitX, cap=0, now=NOW)
dX = HX.st.get("d") or {}
chk(close((dX.get(iso(8, 20)) or [None])[0], 101500) and (HX.st.get("s") or {}).get(iso(8, 20), [])[7:8] == ["upbit"],
    "X4 장기 곡선 hc 행(8/20 — 업비트 없이 100,000) = 1회 다시 계산 101,500(창 시작 앵커 USDT 1,500 · 원화는 9/1 입금 전이라 0 — 이력 되감기) · 행 지문", (dX.get(iso(8, 20)), (HX.st.get("s") or {}).get(iso(8, 20))))
chk(close((dX.get(iso(8, 22)) or [None])[0], 101500), "X4 창 밖 dc 행(동결 항목 없음) = hc 로 다시 101,500", dX.get(iso(8, 22)))
chk(close((dX.get(iso(8, 21)) or [None])[0], 103000), "X4 지문 있는 행(8/21 · xq upbit) = 그대로", dX.get(iso(8, 21)))
dX[iso(8, 20)] = [101501.0] + list(dX[iso(8, 20)][1:])
HX.st["d"] = dX
HX.run_once(kitX, cap=0, now=NOW + 60)
chk(close(((HX.st.get("d") or {}).get(iso(8, 20)) or [None])[0], 101501), "X4 두 번째 실행 = 다시 계산 없음(1회)", (HX.st.get("d") or {}).get(iso(8, 20)))
reset_files()
b = unit_builder()
setup(b)
X7 = mkx(NOW, dep=E(7, 1, 10, 0, 0))
ser7 = b._daily_series(G, D(10, 10), {}, {}, ca_gids=set(), ex_gids=set(), skip_gids=set(), pending_gids=set(), hold_qty=dict(HOLD),
                       extra=copy.deepcopy(X7), extra_ok=True, now_ts=NOW, **({"xq": "upbit", "xq_base": ""} if XQ else {}))
pth7, pxp7 = os.path.join(S, "chX7.json"), os.path.join(S, "chX7_px.json")
common.atomic_write_json(pth7, {"_v": histcurve.HIST_V, "d": {iso(8, 20): hrow(100000)}, "s": {iso(8, 20): [100000.0, 0.0, 0.0, 0, 0.0]},
                                "x": {iso(8, 20): {"p": xp0, "fx": FX, "cut": 0.0, "x": 0.0, "xc": 0.0, "uat": histcurve.day_end(iso(8, 20)) - 1}},
                                "meta": {"pending": False, "flow_pending": False}})
H7 = histcurve.HistCurve(path=pth7, px_path=pxp7)
H7.px["fx"] = HX.px["fx"]
kit7 = histcurve.make_kit("2026-10-10", G, HOLD, set(), set(), {}, set(), {}, {}, {}, [], X7, ser7, b.daily, xkit=copy.deepcopy(b.__dict__.get("_x_kit")), **kw9)
H7.run_once(kit7, cap=0, now=NOW)
chk(close(((H7.st.get("d") or {}).get(iso(8, 20)) or [None])[0], 102500),
    "X7 fc505: 장기 곡선 8/20(보관 45일 밖 · 키 없을 때 원화 이월 0 고정) = 다시 계산에서 원화 이력 ₩1.4M(7/1 입금) 포함 102,500(수정 전 101,500)",
    ((H7.st.get("d") or {}).get(iso(8, 20)), ((H7.st.get("x") or {}).get(iso(8, 20)) or {}).get("p")))

reset_files()
T.finish()
