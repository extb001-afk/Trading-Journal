#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import common
import histcurve
import wow
import wow2

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


TODAY = "2026-09-30"
CA_N, CA_Q = "0x" + "d5" * 20, "0x" + "e6" * 20
json.dump({"_v": 1, "specs": {"ca:eth:" + CA_N: {"p": {d: 100.0 for d in days("2026-09-01", TODAY)}},
                              "ca:eth:" + CA_Q: {"p": {d: 100.0 for d in days("2026-09-01", TODAY)}}}},
          open(os.path.join(common.STATE_DIR, "curve_hist_px.json"), "w"))
histcurve.HIST.kit = {"groups": {31: {"sym": "PEPX", "ca": [("eth", CA_N)]},
                                 32: {"sym": "PEPX", "ca": [("eth", CA_Q)], "skip": True}}}
SELL = lambda a, **kw: dict({"k": "온체인 매도", "a": a, "sym": "PEPX"}, **kw)
D1 = "2026-09-05"
TAX = [{"sold": D1, "sym": "PEPX", "qty": 1, "acq": 50, "disp": 100},
       {"sold": D1, "sym": "PEPX", "qty": 100, "acq": 1, "disp": 100}]
NORMAL = (ts(D1, "10:00"), "pos", SELL("$100.00", _cmp={"q": 1.0, "unk": 0.0}), ("g31f1", "PEPX", "eth"))
HID = (ts(D1, "10:05"), "hidden", SELL("$100.00", _cmp={"q": 100.0, "unk": 0.0}, _gid=32, hide="격리(스팸) 자산", hideKind="scam"), None)
POS = [{"key": "g31f1", "sym": "PEPX", "_ots": ts("2026-09-01", "09:00"), "realizedByDay": {D1: 50.0}},
       {"key": "s32", "sym": "PEPX", "kind": "quarantined", "_ots": ts("2026-09-01", "09:00"), "realizedByDay": {D1: 99.0}}]
n_b = [100]


def bench(tax, rows, pos=()):
    n_b[0] += 1
    return wow.bench({"builtAt": n_b[0], "tax": tax, "ix": {D1: list(rows)}, "pos": list(pos)}, TODAY, since="2026-09-01")


b = bench(TAX, [NORMAL, HID], POS)
r1 = [(r["q"], r["usd"], r["diff"], r["st"]) for r in b["rows"]]
chk(r1 == [(1.0, 100.0, 0.0, "ok")] and abs(b["hold"].get(TODAY, 0)) < 1e-6 and b["holdCov"] == 1.0,
    "Q1 정상 + 격리 같은 날 같은 이름 = 정상 몫만(1개 $100 · 차이 0 — 종전 101개 +$9,900)", (r1, b["hold"].get(TODAY), b["holdCov"]))
b2 = bench(TAX[1:], [HID], POS)
chk(b2["rows"] == [] and b2["holdCov"] is None and not b2["hold"] and b2["nSell"] == 0, "Q2 격리만 판 날 = 대상 아님(행·신뢰도 분모 없음)", (b2["rows"], b2["holdCov"]))
b3 = bench([{"sold": D1, "sym": "PEPX", "qty": 60, "acq": 50, "disp": 100}], [NORMAL])
chk([r["st"] for r in b3["rows"]] == ["nogrp"] and not b3["hold"], "Q3 가격 키 하나 · 판 수량(1)이 명세(60)와 안 맞음 = 묶음 모름(여러 가격 키와 같은 검증)", b3["rows"])
b3b = bench(TAX[:1], [NORMAL])
chk([(r["q"], r["st"]) for r in b3b["rows"]] == [(1.0, "ok")], "Q3 가격 키 하나 · 수량 맞음 = 종전 그대로(시세 붙음)", b3b["rows"])
b3c = bench([{"sold": D1, "sym": "PEPX", "qty": 1, "acq": 0.001, "disp": 0.004}], [(NORMAL[0], "pos", SELL("$0.00", _cmp={"q": 1.0, "unk": 0.0}), NORMAL[3])])
chk([(r["q"], r["st"]) for r in b3c["rows"]] == [(1.0, "ok")], "Q3 가격 키 하나 · 기록 금액 '$0.00'(소액) = 나눌 것 없음 → 종전 그대로(소액)", b3c["rows"])
HID_NQ = (HID[0], "hidden", SELL("$100.00", _gid=32, hideKind="scam"), None)
b4 = bench(TAX, [NORMAL, HID_NQ], POS)
chk([r["st"] for r in b4["rows"]] == ["nogrp"] and not b4["hold"], "Q4 격리 매도 판 수량 모름 = 정상 몫을 못 정함 → 묶음 모름(정상 시세 안 붙음)", b4["rows"])
NORMAL_NQ = (NORMAL[0], "pos", SELL("$100.00"), NORMAL[3])
b4b = bench(TAX, [NORMAL_NQ, HID], POS)
chk([r["st"] for r in b4b["rows"]] == ["nogrp"], "Q4 정상 매도 판 수량 모름 + 격리 몫 있음 = 묶음 모름", b4b["rows"])
for lab, meta in (("카드 키 s32(kind quarantined)", ("s32", "PEPX", "eth")), ("장기 곡선 skip 그룹 g32", ("g32f1", "PEPX", "eth"))):
    q5 = (HID[0], "pos", SELL("$100.00", _cmp={"q": 100.0, "unk": 0.0}), meta)
    b5 = bench(TAX, [NORMAL, q5], POS)
    r5 = [(r["q"], r["usd"], r["diff"]) for r in b5["rows"]]
    chk(r5 == [(1.0, 100.0, 0.0)], "Q5 " + lab + " 매도 = 격리 몫(정상 시세 안 붙음)", r5)
    b5o = bench(TAX[1:], [q5], POS)
    chk(b5o["rows"] == [], "Q5 " + lab + " 만 판 날 = 대상 아님", b5o["rows"])

n_h = [200]


def habits(tax, rows, pos):
    n_h[0] += 1
    wow._CACHE.pop("habits", None)
    return wow.habits({"builtAt": n_h[0], "tax": tax, "ix": {D1: list(rows)}, "pos": list(pos)}, TODAY)


h = habits(TAX, [NORMAL, HID], POS)
hb = [(x["k"], x["n"], x["cost"], x["pnl"]) for x in h["hold"] if x["n"]]
cell = h["grid"][datetime.strptime(D1, "%Y-%m-%d").weekday()][5]
chk(hb == [] and h["excl"].get("mix") == 1, "Q6 섞인 날(격리 몫 있음) = 보유 기간 칸에서 뺌(격리 원가·손익 안 섞임) · 뺀 수 excl.mix", (hb, h["excl"]))
chk(h["n"] == 1 and cell[:2] == [1, 1] and abs(cell[2] - 50) < 1e-6 and h["excl"].get("quar") == 1, "Q6 습관 칸 = 정상 카드 실현만(격리 카드 실현 99 제외)", (h["n"], cell, h["excl"]))
chk(h["next"] == [0, 1] and h["nextAvg"] == 0.0, "Q6 판 다음 날 = 정상 몫 판 값(100) 기준 · 시세 100 → 변화 0%(종전 판 값 1.98 → 500% 넘어 버려짐)", (h["next"], h["nextAvg"]))
h0 = habits(TAX[:1], [NORMAL], POS[:1])
chk([(x["k"], x["n"]) for x in h0["hold"] if x["n"]] == [("1주 안", 1)] and not h0["excl"].get("mix"), "Q6 격리 몫 없는 날 = 보유 기간 칸 종전 그대로", h0["hold"])
hm = habits(TAX[:1], [NORMAL, HID_NQ], POS)
chk([(x["k"], x["n"], x["cost"]) for x in hm["hold"] if x["n"]] == [("1주 안", 1, 50.0)] and not hm["excl"].get("mix"),
    "Q6 격리 매도 판 수량 모름 · 명세 수량 = 정상 몫 판 수량(1) = 격리 몫 0 확인 → 보유 기간 칸에 듦(원가 50)", (hm["hold"], hm["excl"]))
bm = bench(TAX[:1], [NORMAL, HID_NQ], POS)
chk([(r["q"], r["st"]) for r in bm["rows"]] == [(1.0, "ok")], "Q4 격리 판 수량 모름 · 명세 = 정상 몫만 확인 → 정상 시세(종전 결과와 같음)", bm["rows"])
hm2 = habits(TAX, [NORMAL, HID_NQ], POS)
chk([x for x in hm2["hold"] if x["n"]] == [] and hm2["excl"].get("mix") == 1, "Q6 격리 판 수량 모름 · 명세(101) ≠ 정상 몫(1) → 뺌", (hm2["hold"], hm2["excl"]))
hm3 = habits(TAX, [NORMAL_NQ, HID_NQ], POS)
chk([x for x in hm3["hold"] if x["n"]] == [] and hm3["excl"].get("mix") == 1, "Q6 정상·격리 둘 다 판 수량 모름 → 못 가름 = 뺌", (hm3["hold"], hm3["excl"]))
hq = habits(TAX[1:], [HID], POS[1:])
chk([x for x in hq["hold"] if x["n"]] == [] and hq["next"] == [0, 0] and hq["n"] == 0, "Q6 격리만 판 날 = 습관 어디에도 없음", (hq["hold"], hq["next"]))

NOW = datetime.now(wow2.KST)
TS = lambda n, hh=12: int((NOW - timedelta(days=n)).replace(hour=hh, minute=0, second=0, microsecond=0).timestamp())
DD = lambda n: (NOW - timedelta(days=n)).strftime("%Y-%m-%d")
W1 = "0x" + "f7" * 20
DB = os.path.join(T.TMP, "ledger.db")
c = sqlite3.connect(DB)
c.executescript("""
CREATE TABLE asset_groups (group_id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, norm_decimals INTEGER NOT NULL DEFAULT 18);
CREATE TABLE assets (asset_id INTEGER PRIMARY KEY, kind TEXT, chain TEXT, address TEXT, symbol TEXT, decimals INTEGER, confirmed INTEGER DEFAULT 0, hidden INTEGER DEFAULT 0, group_id INTEGER);
CREATE TABLE postings (posting_id INTEGER PRIMARY KEY AUTOINCREMENT, source_kind TEXT, source_ns TEXT, source_id TEXT, leg_seq INTEGER, event_ts INTEGER NOT NULL,
  asset_id INTEGER NOT NULL, location TEXT NOT NULL, qty_base TEXT NOT NULL, cost_usd TEXT, cost_krw TEXT, leg_kind TEXT NOT NULL, event TEXT NOT NULL, classifier_ver INTEGER);
""")
c.executemany("INSERT INTO asset_groups(group_id, name) VALUES (?, ?)", [(41, "PEPX#41"), (42, "PEPX"), (43, "PEPX#43")])
c.executemany("INSERT INTO assets(asset_id, kind, chain, symbol, decimals, group_id) VALUES (?,?,?,?,?,?)", [
    (410, "exchange_currency", None, "PEPX", 8, 41), (420, "token", "eth", "PEPX", 18, 42), (430, "token", "base", "PEPX", 18, 43)])
P = []


def post(t, aid, loc, qty, dec, leg, ev, tx):
    P.append((t, aid, loc, str(int(round(qty * 10 ** dec))), leg, ev, tx))


post(TS(5, 9), 410, "exchange:upbit", 100, 8, "acq", "EX_BUY", "u1")
post(TS(4, 10), 410, "exchange:upbit", -100, 8, "move_out", "EX_WITHDRAW", "u2")
post(TS(4, 10) + 60, 430, f"wallet:base:{W1}", 100, 18, "acq", "TRANSFER_IN", "0xspoof")
post(TS(4, 10) + 600, 420, f"wallet:eth:{W1}", 100, 18, "acq", "TRANSFER_IN", "0xreal")
c.executemany("INSERT INTO postings(event_ts, asset_id, location, qty_base, leg_kind, event, source_id, source_kind, source_ns, leg_seq, classifier_ver)"
              " VALUES (?,?,?,?,?,?,?, 'x', 'x', 0, 1)", P)
c.commit()
c.close()


class PxHist:
    kit = {"groups": {"41": {"sym": "PEPX", "lp": 2.0}, "42": {"sym": "PEPX", "lp": 2.0}, "43": {"sym": "PEPX", "lp": 2.0, "skip": True}}}
    px = {"specs": {}}
    st = {}

    def _clean(self, sp, specs):
        return sp


_orig = (histcurve.spec_of, histcurve.pmap_of)
histcurve.spec_of = lambda g: "sym:" + g["sym"]
histcurve.pmap_of = lambda sp, upto: {DD(n): 2.0 for n in range(0, 40)}
try:
    conn = wow2._ro(DB)
    wow2._MEMO.clear()
    FF = {"rate": 1380, "coins": [{"sym": "PEPX", "price": 2.0, "locs": [{"w": "메인 지갑", "ch": "Ethereum", "qty": 100}]}]}
    fl = wow2.flows(FF, conn=conn, chain_names={"eth": "Ethereum", "base": "Base"}, hist=PxHist())
    L = {(l["s"], l["t"], l["kind"]): l["usd"] for l in fl["links"]}
    chk(abs(L.get(("ex:upbit", "ch:eth", "route"), 0) - 200) < 0.01 and ("ex:upbit", "ch:base", "route") not in L,
        "Q7 거래소 출금 짝 = 진짜 도착(이더리움) — 같은 이름 격리 수령(Base)과 짝짓지 않음", {k: v for k, v in L.items() if k[2] == "route"})
    chk(not any(k[2] == "coin_in" for k in L), "Q7 진짜 도착이 '코인으로 받음'으로 두 번 세지지 않음", {k: v for k, v in L.items() if k[2] == "coin_in"})
    D8 = DD(3)
    daily = {"_risk_rev": "43", D8: {"g": {"42": 100.0, "43": 50.0}, "val": 100.0, "x": 0.0}}
    dpx = {D8: {"p": {"42": 1.0, "43": 1.0}}}
    t = wow2.tm(D8, hist=PxHist(), daily=daily, dpx=dpx, fields={}, conn=conn, chain_names={}, now_px={"42": 2.0, "43": 2.0})
    it = [(i["sym"], i["usd"], i["nowUsd"]) for i in t.get("items") or []]
    chk(it == [("PEPX", 100.0, 200.0)] and t.get("etcUsd") == 0.0 and t.get("x") == 0.0 and t.get("total") == 100.0 and t.get("nowTotal") == 200.0,
        "Q8 격리 그룹 몫 = 정상 줄과 안 합침 · 그 밖·원장 밖에도 없음(그날 합계 val 이 이미 뺀 값 — qdaily1006)", (it, t.get("etcUsd"), t.get("x"), t.get("total"), t.get("nowTotal")))
finally:
    histcurve.spec_of, histcurve.pmap_of = _orig
T.finish()
