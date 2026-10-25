#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from decimal import Decimal  # noqa: E402
from types import SimpleNamespace  # noqa: E402

json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(os.environ["TJ_BASE"], "config.json"), "w"))
import attfreeze  # noqa: E402
import db as dbm  # noqa: E402
import histcurve  # noqa: E402
import paths  # noqa: E402
import web  # noqa: E402

chk = T.chk
KST = timezone(timedelta(hours=9))
TOL = 0.011
CONN = dbm.open_db(paths.DB_PATH)
CONN.commit()
chk(histcurve.HIST.flow_fn is web._hist_flows, "등록된 HIST.flow_fn = web._hist_flows(실제 함수)")
SEQ = [0]


def put_move(ex, ts, amount):
    SEQ[0] += 1
    when = datetime.fromtimestamp(ts, KST).isoformat()
    kind = "deposit" if amount > 0 else "withdraw"
    pl = {"currency": "KRW", "state": "ACCEPTED" if amount > 0 else "DONE", "amount": str(abs(amount)), "fee": "0",
          "created_at": when, "done_at": when, "txid": "t%d" % SEQ[0]}
    CONN.execute("INSERT INTO raw_ex(exchange, kind, uuid, revision, payload, observed_at) VALUES (?,?,?,?,?,?)",
                 (ex, kind, "u%d" % SEQ[0], 1, json.dumps(pl), int(ts)))
    CONN.commit()


def clear_moves():
    CONN.execute("DELETE FROM raw_ex")
    CONN.commit()


def setup(ex, pd, d, opening, amount, prevfx, closefx, fx_tx, rate_now=None):
    clear_moves()
    y, m, dd = (int(v) for v in d.split("-"))
    ts = int(datetime(y, m, dd, 12, tzinfo=KST).timestamp())
    put_move(ex, ts, amount)
    ending = opening + amount
    part = "ku" if ex == "upbit" else "kb"
    b = object.__new__(web.StateBuilder)
    b.daily = {}
    b.spot = SimpleNamespace(rate=closefx, fx_basis=closefx)
    b.px = SimpleNamespace(fx_at=fx_tx)
    tl = [(ts, Decimal(amount))] if ex == "upbit" else []
    b._upbit_krw_tl = (None, tl, [])
    b.daily_px = {pd: {"p": {}, "x": round(opening / prevfx, 2), "xv": {"v": 2, "p": {part: [opening, "snap"]}, "fx": prevfx}},
                  d: {"p": {}, "x": round(ending / closefx, 2), "xv": {"v": 2, "p": {part: [ending, "snap"]}, "fx": closefx}}}
    extra = {"krw_up": ending if ex == "upbit" else 0.0, "krw_other": ending if ex == "bithumb" else 0.0, "krw_up_tl": tl, "rate": rate_now or closefx}
    real = {"rbd": {}, "lpf": {}, "stk": {}, "unv": {}}
    fk = {"today": "2026-10-23", "G": {}, "skip": frozenset(), "offc": frozenset(), "rate": closefx, "transit": [], "wdt": {}}
    kit = {"groups": {}, "transit": [], "xk": {"sym_tl": {}}, "fk": fk}
    ctx = ({}, datetime(2026, 10, 23, 12, tzinfo=KST), {}, frozenset(), extra, real, None)
    return b, kit, ctx, extra, real


def normal_window(b, kit, extra, real, pd, d, closefx):
    src, rs = attfreeze._bf_rows([pd, d], {}, set(), kit, b.daily_px, histcurve.HIST.flow_fn)
    y, m, dd = (int(v) for v in d.split("-"))
    now = datetime(y, m, dd, 12, tzinfo=KST) + timedelta(days=1)
    rows = [dict(rs[x], date=x[5:]) for x in (pd, d)]
    nf = b._daily_flows(CONN, rows, {}, now, {}, rate_now=closefx)
    for r in rows:
        r["flow"] = (nf.get(r["date"]) or (0.0, []))[0]
    b._daily_att_src = src
    att = b._daily_attrib(CONN, rows, {}, now, {}, extra=extra, real=real)[d[5:]]
    return rows[-1], att


def run(label, ex, pd, d, opening, amount, prevfx, closefx, txfx, *, fx_known=True, normal=True, rate_now=None):
    fx_tx = (lambda ms, _f=txfx: _f) if fx_known else (lambda ms: None)
    b, kit, ctx, extra, real = setup(ex, pd, d, opening, amount, prevfx, closefx, fx_tx, rate_now)
    ending = opening + amount
    fxu = txfx if fx_known else closefx
    exp = {"val": ending / closefx, "flow": amount / fxu,
           "kx": opening * (1 / closefx - 1 / prevfx) + amount * (1 / closefx - 1 / fxu), "rest": 0.0}
    rec = attfreeze.bf_records(b, CONN, ctx, (kit, b.daily_px, histcurve.HIST.flow_fn), [d], 1)
    chk("_att_fx_at" not in b.__dict__, label + ": 복원 뒤 빌더에 환율 함수 안 남음(30일 빌드 분해 무접촉)")
    rr = (rec.get(d) or {}).get("r") or {}
    aa = rr.get("att") or {}
    got = {"val": rr.get("val"), "flow": rr.get("flow"), "kx": aa.get("kx"), "rest": aa.get("rest")}
    ok = all(got[k] is not None and abs(float(got[k]) - exp[k]) < TOL for k in exp)
    chk(ok and rec[d].get("st") == "b", label + ": 복원 = 독립 기대값(입출금·환율·나머지·마감 각각)", {"got": got, "exp": exp})
    if normal:
        nr, na = normal_window(b, kit, extra, real, pd, d, closefx)
        ng = {"val": nr["val"], "flow": nr["flow"], "kx": na["kx"], "rest": na["rest"]}
        chk(all(abs(float(ng[k]) - exp[k]) < TOL for k in exp), label + ": 30일 창 계산 = 독립 기대값(대조군)", {"normal": ng, "exp": exp})
        same = all(abs(float(aa.get(k) or 0) - float(na.get(k) or 0)) < TOL for k in ("mk", "kx", "ev", "rest", "rs", "xo"))
        chk(same and abs(float(rr["flow"]) - float(nr["flow"])) < TOL, label + ": 복원 = 30일 창 항목별 같음(mk·kx·ev·rest·rs·xo·flow)",
            {"bf": aa, "normal": na})
    return rr


PD, D = "2026-09-19", "2026-09-20"
for ex in ("upbit", "bithumb"):
    for amount in (1300000, -1300000):
        for txfx, closefx in ((1300.0, 1400.0), (1400.0, 1300.0), (1300.0, 1300.0)):
            run(f"X1 {ex} {amount:+d} 환율 {txfx:g}→{closefx:g}", ex, PD, D, max(0, -amount), amount, txfx, closefx, txfx)

for ex in ("upbit", "bithumb"):
    run(f"X2 {ex} 전일 보유 2,600,000(전일 환율 1350) + 입금 1,300,000(1300 → 마감 1400)", ex, PD, D, 2600000, 1300000, 1350.0, 1400.0, 1300.0)
    run(f"X2 {ex} 전일 보유 2,600,000 − 출금 1,300,000(1420 → 마감 1380)", ex, PD, D, 2600000, -1300000, 1350.0, 1380.0, 1420.0)
run("X2 upbit 금액 1,000배 입금", "upbit", PD, D, 0, 1300000000, 1300.0, 1400.0, 1300.0)
run("X2 bithumb 금액 1,000배 출금", "bithumb", PD, D, 1300000000, -1300000000, 1400.0, 1300.0, 1400.0)
run("X2 upbit 연말 넘김(전일 = 지난해 마지막 날)", "upbit", "2027-12-31", "2028-01-01", 0, 1300000, 1300.0, 1400.0, 1300.0)
run("X2 bithumb 윤일(2월 29일)", "bithumb", "2028-02-28", "2028-02-29", 0, 1300000, 1300.0, 1400.0, 1300.0)

for ex in ("upbit", "bithumb"):
    run(f"X3 {ex} 그 시각 환율 없음 = 마감 환율(지금 환율 1500 아님 · 나머지 0)", ex, PD, D, 1000000, 1300000, 1350.0, 1400.0, None, fx_known=False, normal=False,
        rate_now=1500.0)

b, kit, ctx, extra, real = setup("upbit", PD, D, 0, 1300000, 1300.0, 1400.0, lambda ms: 1300.0)
open(os.path.join(paths.STATE_DIR, "backfill_done"), "w").write("1")
OLD_B = {"r": {"date": "09-20", "val": 928.57, "flow": 928.57, "att": {"v": 2, "kx": -71.43, "rest": 71.43}}, "p": {"date": "09-19", "val": 0.0},
         "det": {}, "st": "b", "at": 5, "h": "old"}
KEEP_S = {"r": {"date": "09-18", "val": 1.0, "att": {"v": 2, "rest": 9.0}}, "p": {"date": "09-17", "val": 1.0}, "det": {}, "st": "s", "st0": "b", "sx": "2026-09-01",
          "at": 4, "h": "s"}
KEEP_W = {"r": {"date": "09-17", "val": 1.0, "att": {"v": 2, "rest": 7.0}}, "p": {"date": "09-16", "val": 1.0}, "det": {}, "at": 3, "h": "w"}
b.daily_px["2026-09-18"] = dict(b.daily_px[PD])
b.daily_px["2026-09-17"] = dict(b.daily_px[PD])
store = {"_v": attfreeze.V, "d": {D: OLD_B, "2026-09-18": KEEP_S, "2026-09-17": KEEP_W}, "dm": [], "bf": {"v": 1, "at": 5, "n": 1, "want": 1}}
P = paths.state(attfreeze.FILE)
json.dump(store, open(P, "w"))
rep = attfreeze.backfill(b, CONN, lambda: kit, ctx, now=1_900_000_000)
disk = json.load(open(P))
nb = disk["d"][D]
chk(attfreeze.BF_V >= 2 and disk["bf"]["v"] == attfreeze.BF_V and nb["st"] == "b" and abs(nb["r"]["flow"] - 1000.0) < TOL
    and abs(nb["r"]["att"]["kx"] + 71.43) < TOL and abs(nb["r"]["att"]["rest"]) < TOL and nb["at"] == 1_900_000_000,
    "X4 옛 세대 'b' 기록 = 다시 계산(입출금 1000 · 환율 −71.43 · 나머지 0)", (rep, disk.get("bf"), nb.get("r")))
chk(disk["d"]["2026-09-18"] == KEEP_S and disk["d"]["2026-09-17"] == KEEP_W,
    "X4 's'(정정 전 값 · 옛 'b' 였어도)·창 밖 정상 동결(st 없음) = 그대로", (disk["d"]["2026-09-18"], disk["d"]["2026-09-17"]))
chk(rep.get("re") == 1 and disk["bf"].get("re") == 1, "X4 보고 = 다시 계산 1일(re)", (rep, disk["bf"]))
m0 = os.path.getmtime(P)
b2 = object.__new__(web.StateBuilder)
b2.daily_px = b.daily_px
rep2 = attfreeze.backfill(b2, CONN, lambda: kit, ctx, now=1_900_000_100)
chk(rep2["n"] == 0 and os.path.getmtime(P) == m0 and json.load(open(P))["d"][D] == nb, "X4 새 세대 표식 뒤 = 다시 안 함(파일 무변)", rep2)
store2 = json.load(open(P))
store2["d"]["2026-08-01"] = dict(OLD_B, r=dict(OLD_B["r"], date="08-01"))
store2["bf"] = {"v": 1}
json.dump(store2, open(P, "w"))
b3 = object.__new__(web.StateBuilder)
b3.__dict__.update(b.__dict__)
b3.__dict__.pop("_att_frz_bf", None)
attfreeze.backfill(b3, CONN, lambda: kit, ctx, now=1_900_000_200)
d3 = json.load(open(P))
chk(d3["d"]["2026-08-01"] == store2["d"]["2026-08-01"] and d3["bf"]["v"] == attfreeze.BF_V, "X4 재료 없는 옛 'b' 날 = 그대로(지우지 않음)", d3["bf"])

clear_moves()
put_move("upbit", int(datetime(2026, 9, 20, 12, tzinfo=KST).timestamp()), 1400000)
fk = {"today": "2026-10-23", "G": {}, "skip": frozenset(), "offc": frozenset(), "rate": 1400.0, "transit": [], "wdt": {}}
hf = histcurve.HIST.flow_fn(fk, [D], {D: {"p": {}}}, lambda iso: 1400.0)
chk(abs(hf[D][0] - 1000.0) < TOL, "X5 장기 곡선 호출(4인자) = 그날 마감 환율 그대로(1,400,000 / 1400 = 1000)", hf)

CONN.close()
T.finish()
