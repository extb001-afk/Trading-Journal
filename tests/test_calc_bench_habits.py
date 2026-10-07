#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
from datetime import datetime, timedelta, timezone

import common
import histcurve
import wow

chk = T.chk

KST = timezone(timedelta(hours=9))


def ts(iso, hm="12:00"):
    return int(datetime.strptime(iso + " " + hm, "%Y-%m-%d %H:%M").replace(tzinfo=KST).timestamp())


def days(a, b):
    x, out = datetime.strptime(a, "%Y-%m-%d"), []
    while x <= datetime.strptime(b, "%Y-%m-%d"):
        out.append(x.strftime("%Y-%m-%d"))
        x += timedelta(days=1)
    return out


CA_A = "0x" + "a1" * 20
TODAY = "2026-09-30"
st = common.STATE_DIR
px = {"sym:PEPE": {"p": {d: 100.0 for d in days("2026-09-01", TODAY)}},
      "ca:eth:" + CA_A: {"p": {d: 2.0 for d in days("2026-09-01", TODAY)}},
      "sym:GAP": {"p": dict({d: 10.0 for d in days("2026-09-01", "2026-09-10")}, **{d: 20.0 for d in days("2026-09-25", TODAY)})},
      "sym:DEAD": {"p": {d: 5.0 for d in days("2026-09-01", "2026-09-15")}},
      "sym:ETH": {"p": {d: 3000.0 for d in days("2026-08-01", TODAY)}}}
json.dump({"_v": 1, "specs": px}, open(os.path.join(st, "curve_hist_px.json"), "w"))
histcurve.HIST.kit = {"groups": {
    11: {"sym": "PEPE", "ca": [("eth", CA_A)]},
    12: {"sym": "GAP", "maj": True},
    13: {"sym": "DEAD", "maj": True},
    14: {"sym": "ETH", "maj": True},
    15: {"sym": "USDT", "st": True},
}}
tax = [
    {"sold": "2026-09-05", "sym": "PEPE", "qty": 10, "acq": 10, "disp": 15},
    {"sold": "2026-09-05", "sym": "GAP", "qty": 1, "acq": 8, "disp": 10},
    {"sold": "2026-09-05", "sym": "DEAD", "qty": 2, "acq": 6, "disp": 10},
    {"sold": "2025-08-20", "sym": "ETH", "qty": 1, "acq": 1000, "disp": 2000},
]
ev = lambda sym, a: {"k": "거래소 매도", "a": a, "sym": sym}
ix = {"2026-09-05": [(ts("2026-09-05", "10:00"), "pos", ev("PEPE", "$15.00"), ("g11f1", "PEPE", "eth")),
                     (ts("2026-09-05", "10:05"), "pos", ev("GAP", "$10.00"), ("g12", "GAP", "")),
                     (ts("2026-09-05", "10:10"), "pos", ev("DEAD", "$10.00"), ("g13", "DEAD", ""))],
      "2025-08-20": [(ts("2025-08-20", "09:00"), "pos", ev("ETH", "$2,000.00"), ("g14", "ETH", ""))]}
idx = {"builtAt": 1, "tax": tax, "ix": ix, "pos": []}

b = wow.bench(idx, TODAY, since="2026-09-01")
H = b["hold"]
chk(abs(H.get(TODAY, 0) - (5 + (20 - 10))) < 1e-6, "B3 시세 = 자산 묶음 기준(ca:eth) — 같은 티커 다른 토큰 시세 안 붙음 · B2 끊긴 DEAD 는 선에서 빠짐", H.get(TODAY))
gap_vals = [H.get(d, 0) for d in days("2026-09-12", "2026-09-24")]
chk(all(abs(v - 5) < 1e-6 for v in gap_vals), "B2 중간 공백 = 직전 시세 유지(값 일정 · 0 으로 안 떨어짐)", gap_vals[:3])
dead_rows = [r for r in b["rows"] if r["sym"] == "DEAD"]
chk(dead_rows and dead_rows[0]["st"] == "nopx" and dead_rows[0]["lastPx"] == "2026-09-15" and dead_rows[0]["now"] is None,
    "B2 오늘 시세 없는 묶음 = 건별 표 '시세 없음'(마지막 시세 날)", dead_rows)
chk(all(abs(H.get(d, 0) - H.get("2026-09-06", 0)) < 1e-6 for d in days("2026-09-06", "2026-09-10")), "B2 끊긴 묶음은 선 전체에서 빠짐(끊긴 날 전후 계단 없음)")
chk(abs(b["holdCov"] - 25 / 35) < 1e-4, "B4 신뢰도 holdCov = 시세 찾은 대금 비율", b["holdCov"])
chk(b["pxAt"] == TODAY and b["basis"] == "group", "B4 시세 기준 날(pxAt)·기준(group)", (b["pxAt"], b["basis"]))
pr = [r for r in b["rows"] if r["sym"] == "PEPE"][0]
chk(abs(pr["sp"] - 1.5) < 1e-9 and abs(pr["now"] - 2.0) < 1e-9 and abs(pr["diff"] - 5) < 1e-9 and pr["st"] == "ok", "B4 건별 표: 판 가격·지금 가격·차이", pr)
b_all = wow.bench(idx, TODAY, since="2025-08-01")
b_400 = wow.bench(idx, TODAY)
chk(any(r["sym"] == "ETH" for r in b_all["rows"]) and not any(r["sym"] == "ETH" for r in b_400["rows"]) and b_all["since"] == "2025-08-01",
    "B1 차트 기간(since) 안 매도만 — 기간을 주면 그 앞은 처음부터 없음", (b_all["since"], b_400["since"]))
d1 = wow.bench(idx, "2026-09-24", since="2026-09-01")["hold"]
d2 = wow.bench(idx, "2026-09-25", since="2026-09-01")["hold"]
chk(abs(d1.get("2026-09-20", 0) - d2.get("2026-09-20", 0)) < 1e-6, "B1 하루 지나도(같은 since) 지난날 값이 바뀌지 않음(선이 하루 만에 내려앉지 않음)", (d1.get("2026-09-20"), d2.get("2026-09-20")))

CA_B, CA_C = "0x" + "b3" * 20, "0x" + "c4" * 20
px2 = dict(px)
px2["ca:eth:" + CA_B] = {"p": {d: 1.0 for d in days("2026-09-01", TODAY)}}
px2["ca:base:" + CA_C] = {"p": {d: 100.0 for d in days("2026-09-01", TODAY)}}
json.dump({"_v": 1, "specs": px2}, open(os.path.join(st, "curve_hist_px.json"), "w"))
histcurve.HIST.kit["groups"].update({21: {"sym": "DUP", "ca": [("eth", CA_B)]}, 22: {"sym": "DUP", "ca": [("base", CA_C)]}})
tax_d = [{"sold": "2026-09-06", "sym": "DUP", "qty": 101, "acq": 150, "disp": 200}]
ix_d = {"2026-09-06": [(ts("2026-09-06", "10:00"), "pos", dict(ev("DUP", "$100.00"), _cmp={"q": 100.0}), ("g21", "DUP", "eth")),
                       (ts("2026-09-06", "11:00"), "pos", dict(ev("DUP", "$100.00"), _cmp={"q": 1.0}), ("g22", "DUP", "base"))]}
bd = wow.bench({"builtAt": 21, "tax": tax_d, "ix": ix_d, "pos": []}, TODAY, since="2026-09-01")
rd = sorted((r["q"], r["diff"]) for r in bd["rows"])
chk(rd == [(1.0, 0.0), (100.0, 0.0)] and abs(bd["hold"].get(TODAY, 0)) < 1e-6, "경계1 가격 키 둘 = 그룹별 판 수량(_cmp.q)으로 나눔 · 차이 0(종전 +4,900.5)", (rd, bd["hold"].get(TODAY)))
ix_d2 = {"2026-09-06": [(ts("2026-09-06", "10:00"), "pos", ev("DUP", "$100.00"), ("g21", "DUP", "eth")),
                        (ts("2026-09-06", "11:00"), "pos", ev("DUP", "$100.00"), ("g22", "DUP", "base"))]}
bd2 = wow.bench({"builtAt": 22, "tax": tax_d, "ix": ix_d2, "pos": []}, TODAY, since="2026-09-01")
chk([r["st"] for r in bd2["rows"]] == ["nogrp"] and not bd2["hold"], "경계1 그룹별 수량을 모르면 나누지 않고 '묶음 모름'(선에서 빠짐)", bd2["rows"])
tax_k = [{"sold": "2026-09-06", "sym": "DUP", "qty": 100, "acq": 150, "disp": 100}]
ix_k = {"2026-09-06": [(ts("2026-09-06", "10:00"), "pos", dict(ev("DUP", "$100.00"), _cmp={"q": 100.0, "unk": 0.0}), ("g21", "DUP", "eth")),
                       (ts("2026-09-06", "11:00"), "pos", dict(ev("DUP", "$100.00"), _cmp={"q": 1.0, "unk": 1.0}), ("g22", "DUP", "base"))]}
bk = wow.bench({"builtAt": 23, "tax": tax_k, "ix": ix_k, "pos": []}, TODAY, since="2026-09-01")
rk = [(r["q"], r["usd"], r["diff"]) for r in bk["rows"]]
chk(rk == [(100.0, 100.0, 0.0)] and abs(bk["hold"].get(TODAY, 0)) < 1e-6, "경계2 명세 = 원가 확인분 → 원가 확인분 비율(100개 $100 → g21) · 차이 0(종전 +$98.02)", (rk, bk["hold"].get(TODAY)))
tax_x = [{"sold": "2026-09-06", "sym": "DUP", "qty": 60, "acq": 90, "disp": 100}]
bx = wow.bench({"builtAt": 24, "tax": tax_x, "ix": ix_d, "pos": []}, TODAY, since="2026-09-01")
chk([r["st"] for r in bx["rows"]] == ["nogrp"], "경계2 명세 수량이 원가 확인분·전체 판 수량 어느 쪽과도 안 맞으면 나누지 않음(묶음 모름)", bx["rows"])

json.dump({"_v": 1, "specs": dict(px2, **{"ex:gate:BLK": {"p": {"2026-09-07": 5.0, "2026-09-08": 777.0, "2026-09-09": 5.0}, "ps": {"2026-09-08": "binance:BLKUSDT"},
                                                          "src": ["gate:BLK_USDT"], "blk": ["binance"]},
                                          "ex:gate:PND": {"p": {"2026-09-07": 3.0, "2026-09-08": 999.0}, "src": ["gate:PND_USDT"], "pend": ["2026-09-08"]}})},
          open(os.path.join(st, "curve_hist_px.json"), "w"))
K = wow.px_by_key()
chk("2026-09-08" not in K.get("ex:gate:BLK", {}) and K["ex:gate:BLK"].get("2026-09-07") == 5.0, "경계3 막힌 거래소(blk) 날 시세 뺌(다른 코인 판정)", K.get("ex:gate:BLK"))
chk("2026-09-08" not in K.get("ex:gate:PND", {}) and K["ex:gate:PND"].get("2026-09-07") == 3.0, "경계3 대기(pend) 날 시세 뺌", K.get("ex:gate:PND"))
json.dump({"_v": 1, "specs": px}, open(os.path.join(st, "curve_hist_px.json"), "w"))

pos = [
    {"key": "g14", "sym": "ETH", "_ots": ts("2026-09-01", "00:30"), "realizedByDay": {"2026-09-02": 500.0}},
    {"key": "s1", "sym": "USDT", "kind": "stable", "_ots": ts("2026-09-01", "09:00"), "realizedByDay": {"2026-09-02": 3.0}},
    {"key": "g99", "sym": "SCAM", "kind": "quarantined", "_ots": ts("2026-09-01", "09:00"), "realizedByDay": {"2026-09-02": 40.0}},
]
tax_h = [{"sold": "2026-09-02", "sym": "ETH", "qty": 1, "acq": 1000, "disp": 1500},
         {"sold": "2026-09-02", "sym": "USDT", "qty": 9000, "acq": 9000, "disp": 9003},
         {"sold": "2026-09-02", "sym": "SCAM", "qty": 1, "acq": 1, "disp": 41}]
ix_h = {"2026-09-02": [(ts("2026-09-02", "22:30"), "pos", ev("ETH", "$1,500.00"), ("g14", "ETH", "")),
                       (ts("2026-09-02", "22:40"), "pos", ev("USDT", "$9,003.00"), ("s1", "USDT", "")),
                       (ts("2026-09-02", "22:50"), "pos", ev("SCAM", "$41.00"), ("g99", "SCAM", ""))]}
idx_h = {"builtAt": 2, "tax": tax_h, "ix": ix_h, "pos": pos}
h = wow.habits(idx_h, TODAY)
cell = h["grid"][datetime.strptime("2026-09-02", "%Y-%m-%d").weekday()][11]
chk(h["n"] == 1 and cell[:2] == [1, 1] and abs(cell[2] - 500) < 1e-6, "H1·H3 칸 = ETH 1건(스테이블·격리 제외) · [건수, 이익, 손익 USD]", (h["n"], cell))
hb = [(x["k"], x["n"], round(x["pnl"] / x["cost"] * 100, 1) if x["cost"] else None) for x in h["hold"] if x["n"]]
chk(hb == [("1주 안", 1, 50.0)], "H1·H2 보유 기간 = 실제 매도 시각(46시간 = '1주 안') · 수익률 +50%(희석 없음)", hb)
chk(h["excl"] == {"stable": 1, "quar": 1}, "H1 뺀 묶음 수(스테이블·격리) 알림", h["excl"])
chk(h["cov"]["pxAt"] == "2026-09-03" and h["cov"]["next"] == 1.0 and h["next"] == [1, 1], "H 판 다음 날 = 자산 묶음 시세 · 신뢰도(가격 확인 비율·시세 날)", (h["cov"], h["next"]))
chk(wow.habits(None)["ok"] is False and wow.bench(None)["hold"] == {}, "색인 없음 = 빌드 전(죽지 않음)")

T.finish()
