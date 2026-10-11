#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import time
from datetime import datetime as _dt, timedelta as _td, timezone as _tz
from decimal import Decimal

KST = _tz(_td(hours=9))
_REAL = time.time
D_DATE = (_dt.fromtimestamp(_REAL(), KST) - _td(days=3)).replace(hour=0, minute=0, second=0, microsecond=0)
CLK = [D_DATE.timestamp() + 12 * 3600]
time.time = lambda: CLK[0]


class _FDT(_dt):
    @classmethod
    def now(cls, tz=None):
        return _dt.fromtimestamp(CLK[0], tz)


import common

CFG = os.path.join(os.environ["TJ_BASE"], "config.json")
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(CFG, "w"))
import core
import db as dbm
import histcurve
import netpace
import web
import xparts

web.datetime = _FDT
histcurve.datetime = _FDT
core.dm = lambda *a, **k: None
chk = T.chk
for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker"):
    if hasattr(web.StateBuilder, _m):
        setattr(web.StateBuilder, _m, lambda self: None)
netpace.wait = lambda url, now=None, sleep=None: None
web.pricing._gj = lambda url, timeout=10.0: None
S = common.STATE_DIR
FX = 1400.0
DAY = 86400
UP = os.path.join(S, "upbit_balances.json")
PX = {"ETH": 1000.0, "XRP": 1.0, "USDT": 1.0}
KRW1 = 1000 * FX
web.pricing.PxCache.candle_usd = lambda self, sym, ms: PX.get(str(sym).upper())
D0 = int(D_DATE.timestamp())
DISO, DM1, DM2 = (D_DATE.strftime("%Y-%m-%d"), (D_DATE - _td(days=1)).strftime("%Y-%m-%d"), (D_DATE - _td(days=2)).strftime("%Y-%m-%d"))
DEND = D0 + DAY - 1


def at(day_off, h, mi=0, s=0):
    return D0 + day_off * DAY + h * 3600 + mi * 60 + s


def clock(ts):
    CLK[0] = float(ts)


def kiso(ts):
    return _dt.fromtimestamp(ts, KST).isoformat()


open(os.path.join(S, "backfill_done"), "w").write("1")


def _spot():
    json.dump({"usd": PX, "usd_ts": {k: int(CLK[0]) for k in PX}, "rate": FX, "updated": int(CLK[0]), "dex_usd": {}, "dex_ts": {}, "dex_res": {},
               "dex_res_ts": {}, "fx_basis": FX, "ex_usd": {}, "ex_ts": {}}, open(web.SPOT_PATH, "w"))


common.atomic_write_json(web.PREFS_PATH, {"plans": {}, "ignored": []})


def _wipe():
    for sfx in ("", "-wal", "-shm"):
        if os.path.exists(common.DB_PATH + sfx):
            os.remove(common.DB_PATH + sfx)
    for fn in ("daily_cache.json", "daily_px.json", common.HIST_DIRTY):
        if os.path.exists(os.path.join(S, fn)):
            os.remove(os.path.join(S, fn))


def _post(c, sid, ts, aid, qty, cost_usd):
    c.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind,"
              " event, classifier_ver) VALUES ('exchange','upbit:order',?,0,?,?,'exchange:upbit',?,?,NULL,?,?,4)",
              (sid, int(ts), aid, str(int(Decimal(str(qty)) * 10 ** 8)), repr(float(cost_usd)), "acq" if qty > 0 else "disp",
               "EX_BUY" if qty > 0 else "EX_SELL"))


def ledger(eth=100, closed=False):
    _wipe()
    clock(at(-20, 9))
    dbm.open_db(common.DB_PATH).close()
    C = core.Core(common.load_config())
    C.px.fx_at = lambda ms: FX
    C.conn.execute("BEGIN")
    aid = C._upbit_asset("ETH")
    _post(C.conn, "initETH", at(-20, 9), aid, eth, eth * PX["ETH"])
    C._bump_position(aid, eth * 10 ** 8, "exchange:upbit")
    if closed:
        _post(C.conn, "initETHx", at(-10, 9), aid, -eth, 0)
        C._bump_position(aid, -eth * 10 ** 8, "exchange:upbit")
    C.conn.commit()
    C._hist_late_fence()
    return C


def snap(ts, accounts, orders=()):
    common.atomic_write_json(UP, {"ts": int(ts), "open_orders": list(orders),
                                  "accounts": [{"currency": k, "balance": str(v[0]), "locked": str(v[1])} for k, v in accounts.items()]})


def oo(uu, side, vol, exe, funds, fee=0, created=None):
    return {"uuid": uu, "market": "KRW-ETH", "side": side, "state": "wait", "ord_type": "limit", "price": "1400000", "volume": str(vol),
            "remaining_volume": str(Decimal(str(vol)) - Decimal(str(exe))), "executed_volume": str(exe), "executed_funds": str(funds),
            "paid_fee": str(fee), "created_at": kiso(created or at(0, 14))}


def fin(uu, side, vol, state, trades, fee=0, created=None):
    exe = sum(Decimal(str(q)) for _t, q, _k in trades)
    funds = sum(Decimal(str(k)) for _t, _q, k in trades)
    return {"uuid": uu, "market": "KRW-ETH", "side": side, "state": state, "ord_type": "limit", "price": "1400000", "volume": str(vol),
            "remaining_volume": str(Decimal(str(vol)) - exe) if state == "done" else "0", "executed_volume": str(exe),
            "executed_funds": str(funds), "paid_fee": str(fee), "created_at": kiso(created or at(0, 14)), "trades_count": len(trades),
            "trades": [{"uuid": f"{uu}-t{i}", "market": "KRW-ETH", "side": side, "price": "1400000", "volume": str(q), "funds": str(k),
                        "created_at": kiso(t)} for i, (t, q, k) in enumerate(trades)]}


def consume(C, orders):
    C.conn.execute("BEGIN")
    C._consume_fills({"orders": list(orders)})
    C.conn.commit()
    return C._hist_late_scan(now=CLK[0])


def new_builder():
    b = web.StateBuilder()
    b.skip_gen_check = True
    return b


def build_on(b, ts):
    clock(ts)
    _spot()
    for k, v in PX.items():
        b.spot.ex_usd[f"upbit:{k}"] = v
        b.spot.ex_ts[f"upbit:{k}"] = int(ts)
        b.spot.usd[k] = v
        b.spot.usd_ts[k] = int(ts)
    b.spot.rate = FX
    b.spot.rate_ts = int(ts)
    histcurve.HIST.kit = None
    conn = dbm.open_db(common.DB_PATH, readonly=True)
    try:
        return b._build(conn)["fields"]
    finally:
        conn.close()


def total(f):
    return (sum(float(c9["qty"]) * float(c9.get("price") or 0) for c9 in f.get("coins") or [])
            + sum(float(s9["qty"]) * float(s9.get("price") or 0) for s9 in f.get("stables") or [])
            + sum(float(x9["krw"]) for x9 in f.get("fiats") or []) / FX)


def day_val(f, iso):
    k = iso[5:]
    return next((float(d9["val"]) for d9 in f.get("dailySeries") or [] if d9.get("date") == k), None)


def today_val(f):
    d9 = f.get("dailySeries") or []
    return float(d9[-1]["val"]) if d9 else None


def bad_ku(b):
    return (((b.__dict__.get("_x_kit") or {}).get("src") or {}).get("bad") or {}).get("ku")


def kit_day(iso):
    kit = histcurve.HIST.kit or {}
    row = next((r9 for r9 in kit.get("daily") or () if r9[0] == iso), None)
    return float(row[1]) if row else None


def near(a, b, tol=0.02):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


def view(b, f, tag):
    return (tag, day_val(f, DISO), day_val(f, DM1), (b.daily.get(DISO) or {}).get("val"), (b.daily.get(DM1) or {}).get("val"),
            kit_day(DISO), kit_day(DM1), today_val(f), round(total(f), 2), bad_ku(b))


def all_ok(rows, want_d, want_m1, want_now):
    for r9 in rows:
        _t, vd, vm1, sd, sm1, kd, km1, tv, tt, bd = r9
        if not (near(vd, want_d) and near(vm1, want_m1) and near(tv, want_now) and near(tt, want_now) and not bd):
            return False
        if sd is not None and not near(sd, want_d):
            return False
        if sm1 is not None and not near(sm1, want_m1):
            return False
        if kd is not None and not near(kd, want_d):
            return False
        if km1 is not None and not near(km1, want_m1):
            return False
    return True


ACC0 = {"KRW": (100 * KRW1, 0), "ETH": (100, 0)}
ACC_MID = {"KRW": (50 * KRW1, 50 * KRW1), "ETH": (50, 50)}
ORD_MID = [oo("b1", "bid", 100, 50, 50 * KRW1), oo("s1", "ask", 100, 50, 50 * KRW1)]
FIN_B = fin("b1", "bid", 100, "done", [(at(0, 15), 50, 50 * KRW1), (at(1, 7, 59, 30), 50, 50 * KRW1)])
FIN_S = fin("s1", "ask", 100, "cancel", [(at(0, 15, 30), 50, 50 * KRW1)])
ACC_END = {"KRW": (50 * KRW1, 0), "ETH": (150, 0)}


def p1_prefix(C, b, mid_build=True, prior=True, acc=None, orders=None, age=10, before_close=None):
    acc = ACC_MID if acc is None else acc
    orders = ORD_MID if orders is None else orders
    for off in ((-2, -1) if prior else ()):
        snap(at(off, 23, 59, 10), ACC0)
        build_on(b, at(off, 23, 59, 20))
    snap(at(0, 12), ACC0)
    build_on(b, at(0, 12, 0, 10))
    if before_close:
        before_close()
    snap(at(0, 23, 59, 20) - age, acc, orders)
    f = build_on(b, at(0, 23, 59, 20))
    lv = b.daily.get("_live") or {}
    r0 = (lv.get("date"), lv.get("defer"), round(float(lv.get("val") or 0), 2), (lv.get("xv") or {}).get("ufk"), round(total(f), 2),
          (lv.get("xv") or {}).get("ufz"))
    if mid_build:
        snap(at(1, 0, 0, 20), acc, orders)
        build_on(b, at(1, 0, 0, 30))
        snap(at(1, 7, 0), acc, orders)
        build_on(b, at(1, 7, 0, 10))
    return r0


def rebuild_views(b, t0):
    rows = []
    f = build_on(b, t0)
    rows.append(view(b, f, "같은 빌더"))
    f = build_on(b, t0 + 60)
    rows.append(view(b, f, "반복 빌드"))
    b2 = new_builder()
    f = build_on(b2, t0 + 120)
    rows.append(view(b2, f, "새 빌더(재시작)"))
    dc = json.load(open(web.DAILY_PATH))
    for k9 in (DISO, DM1):
        dc.pop(k9, None)
    json.dump(dc, open(web.DAILY_PATH, "w"))
    b3 = new_builder()
    f = build_on(b3, t0 + 180)
    rows.append(view(b3, f, "일별 동결 삭제 뒤"))
    return rows, b3


for mid, prior in ((True, False), (False, False), (True, True), (False, True)):
    tag = ("①자정 뒤 동결 뒤 기장" if mid else "②기장 전 빌드 없음(거절된 마감)") + (" · D−1 마감 관측 있음" if prior else " · D−1 관측 없음")
    C = ledger()
    b = new_builder()
    r0 = p1_prefix(C, b, mid_build=mid, prior=prior)
    chk(r0[0] == DISO and r0[1] is False and near(r0[2], 200000) and near(r0[4], 200000),
        f"P1{tag} 준비: D 23:59:20 빌드 = 정상 마감 후보(defer 아님) · $200,000", r0)
    clock(at(1, 8, 0, 30))
    iso = consume(C, [FIN_B, FIN_S])
    legs = [(r9[0], r9[1], int(r9[2]) // 10 ** 8) for r9 in C.conn.execute(
        "SELECT source_id, CASE WHEN event_ts < ? THEN 'D' ELSE 'D+1' END, qty_base FROM postings WHERE source_ns='upbit:order'"
        " AND source_id NOT LIKE 'init%' ORDER BY source_id",
        (D0 + DAY,)).fetchall()]
    chk(legs == [("b1", "D+1", 100), ("s1", "D", -50)] and iso == DISO, f"P1{tag} core 기장: 매수 +100 = D+1 · 매도 −50 = D · 늦은 행 표식 D", (legs, iso))
    snap(at(1, 8, 59, 50), ACC_END)
    rows = []
    f = build_on(b, at(1, 9))
    rows.append(view(b, f, "같은 빌더"))
    f = build_on(b, at(1, 9, 1))
    rows.append(view(b, f, "반복 빌드"))
    b2 = new_builder()
    f = build_on(b2, at(1, 9, 2))
    rows.append(view(b2, f, "새 빌더(재시작)"))
    dc = json.load(open(web.DAILY_PATH))
    for k9 in (DISO, DM1):
        dc.pop(k9, None)
    json.dump(dc, open(web.DAILY_PATH, "w"))
    b3 = new_builder()
    f = build_on(b3, at(1, 9, 3))
    rows.append(view(b3, f, "일별 동결 삭제 뒤"))
    clock(at(2, 0, 0, 40))
    snap(at(2, 0, 0, 30), ACC_END)
    f = build_on(b3, at(2, 0, 0, 40))
    rows.append(view(b3, f, "다음 날 자정 뒤"))
    chk(all_ok(rows, 200000, 200000, 200000),
        f"P1{tag} 다시 계산: D·D−1·지금 모두 $200,000(화면·저장·장기 곡선 재료 · 원화 불신 없음 · 반복·재시작·캐시 삭제 같음) — 종전 D·D−1 $150,000", rows)
    C.conn.close()


def late_xrp(C, ts, q=1000):
    C.conn.execute("BEGIN")
    aid = C._upbit_asset("XRP")
    _post(C.conn, f"latexrp{int(ts)}", ts, aid, q, q * PX["XRP"])
    C._bump_position(aid, q * 10 ** 8, "exchange:upbit")
    C.conn.commit()
    return C._hist_late_scan(now=CLK[0])


def scen(tag, acc, orders, steps, want, prior=False, mid=True, age=10, pre=None):
    C = ledger()
    b = new_builder()
    r0 = p1_prefix(C, b, mid_build=mid, prior=prior, acc=acc, orders=orders, age=age)
    if pre:
        pre(b)
    rows = []
    last = None
    for st in steps:
        clock(st[0])
        if st[1] == "consume":
            consume(C, st[2])
        elif st[1] == "late":
            late_xrp(C, st[2])
        elif st[1] == "snap":
            snap(st[0], st[2], st[3])
            last = st
        elif st[1] == "build":
            f = build_on(b, st[0])
            rows.append(view(b, f, f"{tag} {_dt.fromtimestamp(st[0], KST).strftime('%H:%M')} 빌드") + (st[2],))
    if last is not None:
        snap(CLK[0] + 590, last[2], last[3])
    rr, b3 = rebuild_views(b, CLK[0] + 600)
    rows += [r9 + (want,) for r9 in rr]
    C.conn.close()
    return rows, r0, b3


def rows_ok(rows):
    for r9 in rows:
        w9 = r9[-1]
        if w9 is None:
            continue
        if not all_ok([r9[:-1]], *w9):
            return False
    return True


ORD_U = [oo("u1b", "bid", 100, 50, 50 * KRW1, created=at(0, 22)), oo("u1s", "ask", 100, 50, 50 * KRW1, created=at(0, 22))]
rows, r0, _b = scen("U1a", ACC_MID, ORD_U, [
    (at(1, 9), "consume", [fin("u1b", "bid", 100, "cancel", [(at(0, 23), 50, 50 * KRW1)], created=at(0, 22))]),
    (at(1, 9, 59, 50), "snap", {"KRW": (100 * KRW1, 0), "ETH": (50, 50)}, [ORD_U[1]]),
    (at(1, 10), "build", (200000, 200000, 200000)),
    (at(1, 11, 0, 30), "consume", [fin("u1s", "ask", 100, "done", [(at(0, 23), 50, 50 * KRW1), (at(1, 11), 50, 50 * KRW1)], created=at(0, 22))]),
    (at(1, 11, 29, 50), "snap", {"KRW": (150 * KRW1, 0), "ETH": (50, 0)}, []),
    (at(1, 11, 30), "build", (200000, 200000, 200000))], (200000, 200000, 200000))
chk(rows_ok(rows) and r0[5] == {"ETH": {"u1b": -70000000.0, "u1s": 70000000.0}},
    "U1a 매수·매도 50 씩(D 23:00) → 매수 잔량 취소(어제 23:00 기장 +50) · 매도 열림 → 어제 $200,000(종전 $250,000) · 매도 오늘 기장 뒤에도 $200,000 · "
    "마감 관측에 순수량 0 묶음 주문별 원화(ufz)", (r0, rows))
ORD_U2 = [oo("u2b", "bid", 100, 50, 50 * KRW1, created=at(0, 22)), oo("u2s", "ask", 100, 50, 60 * KRW1, created=at(0, 22))]
rows, r0, _b = scen("U1b", {"KRW": (60 * KRW1, 50 * KRW1), "ETH": (50, 50)}, ORD_U2, [
    (at(1, 9), "consume", [fin("u2s", "ask", 100, "cancel", [(at(0, 23), 50, 60 * KRW1)], created=at(0, 22))]),
    (at(1, 9, 59, 50), "snap", {"KRW": (60 * KRW1, 50 * KRW1), "ETH": (100, 0)}, [ORD_U2[0]]),
    (at(1, 10), "build", (210000, 200000, 210000))], (210000, 200000, 210000))
chk(rows_ok(rows) and near(r0[2], 210000), "U1b 반대(매도 60 체결액 · 매도 잔량 취소 어제 기장 · 매수 열림) → 어제 $210,000(종전 $160,000)", (r0, rows))

F = FX
ORD_F = [oo("fb", "bid", 100, 50, 50 * KRW1, fee=25 * F), oo("fs", "ask", 100, 50, 50 * KRW1, fee=30 * F)]
rows, r0, _b = scen("X1", {"KRW": (50 * KRW1 - 55 * F, 50 * KRW1), "ETH": (50, 50)}, ORD_F, [
    (at(1, 8, 0, 30), "consume", [fin("fb", "bid", 100, "done", [(at(0, 15), 50, 50 * KRW1), (at(1, 7, 59, 30), 50, 50 * KRW1)], fee=50 * F),
                                  fin("fs", "ask", 100, "cancel", [(at(0, 15, 30), 50, 50 * KRW1)], fee=30 * F)]),
    (at(1, 8, 59, 50), "snap", {"KRW": (50 * KRW1 - 80 * F, 0), "ETH": (150, 0)}, [])], (199970, 200000, 199920))
chk(rows_ok(rows) and near(r0[2], 199945), "X1 수수료 포함 = D 마감 $199,945 → 다시 계산 D $199,970(매수 몫·수수료는 다음 날) · D−1 $200,000 · 지금 $199,920", (r0, rows))
rows, r0, _b = scen("X2", ACC_MID, ORD_MID, [
    (at(1, 8, 0, 30), "consume", [fin("b1", "bid", 100, "cancel", [(at(0, 15), 50, 50 * KRW1)]),
                                  fin("s1", "ask", 100, "done", [(at(0, 15, 30), 50, 50 * KRW1), (at(1, 7, 59, 30), 50, 50 * KRW1)])]),
    (at(1, 8, 59, 50), "snap", {"KRW": (150 * KRW1, 0), "ETH": (50, 0)}, [])], (200000, 200000, 200000))
chk(rows_ok(rows), "X2 반대 방향(매수 D · 매도 D+1 기장) = D·D−1·지금 $200,000", rows)
rows, r0, _b = scen("X3", ACC_MID, ORD_MID, [
    (at(1, 8, 0, 30), "consume", [FIN_B, fin("s1", "ask", 100, "done", [(at(0, 15, 30), 50, 50 * KRW1), (at(1, 7, 59, 40), 50, 50 * KRW1)])]),
    (at(1, 8, 59, 50), "snap", {"KRW": (100 * KRW1, 0), "ETH": (100, 0)}, [])], (200000, 200000, 200000))
chk(rows_ok(rows), "X3 둘 다 D+1 기장 = $200,000(맞출 것 없음)", rows)
rows, r0, _b = scen("X4", ACC_MID, ORD_MID, [
    (at(0, 23, 59, 45), "consume", [fin("b1", "bid", 100, "cancel", [(at(0, 15), 50, 50 * KRW1)]), FIN_S]),
    (at(1, 0, 0, 20), "snap", {"KRW": (100 * KRW1, 0), "ETH": (100, 0)}, []),
    (at(1, 0, 0, 30), "build", (200000, 200000, 200000))], (200000, 200000, 200000), mid=False)
chk(rows_ok(rows), "X4 둘 다 D 기장(자정 전 취소 — 마감 스냅숏 거절) = $200,000", rows)
rows, r0, _b = scen("X5", ACC_MID, ORD_MID, [
    (at(1, 6, 0, 30), "consume", [FIN_S]),
    (at(1, 6, 59, 50), "snap", {"KRW": (50 * KRW1, 50 * KRW1), "ETH": (100, 0)}, [ORD_MID[0]]),
    (at(1, 7, 0), "build", (200000, 200000, 200000)),
    (at(1, 8, 0, 30), "consume", [FIN_B]),
    (at(1, 8, 59, 50), "snap", ACC_END, []),
    (at(1, 9), "build", (200000, 200000, 200000)),
    (at(1, 9, 10), "consume", [FIN_B, FIN_S]),
    (at(1, 9, 20), "build", (200000, 200000, 200000))], (200000, 200000, 200000), mid=False)
chk(rows_ok(rows), "X5 도착 순서 분리(매도 먼저 · 매수 열린 채 빌드 · 매수 나중) · X6 같은 종결 주문 다시 수신 = 늘 $200,000", rows)
C = ledger()
b = new_builder()
r0 = p1_prefix(C, b, mid_build=False, acc={"KRW": (50 * KRW1, 50 * KRW1), "ETH": (100, 0)}, orders=ORD_MID,
               before_close=lambda: (clock(at(0, 23, 59, 5)), consume(C, [FIN_S])))
lv7 = (b.daily.get("_live") or {}).get("xv") or {}
clock(at(1, 8, 0, 30))
consume(C, [FIN_B])
snap(at(1, 8, 59, 50), ACC_END)
rows, _b = rebuild_views(b, at(1, 9))
C.conn.close()
chk(all_ok(rows, 200000, 200000, 200000) and not lv7.get("ufz") and list((lv7.get("ufc") or {})) == ["b1"],
    "X7 일부 이미 기장(경합) = 묶음 표식 없음 · 매수만 주문별 몫 → D·D−1·지금 $200,000", (lv7.get("ufz"), lv7.get("ufc"), rows))
ORD_X8 = [oo("x8b", "bid", 100, 50, 50 * KRW1), oo("x8s", "ask", 100, 50, 60 * KRW1)]
ACC_X8 = {"KRW": (60 * KRW1, 50 * KRW1), "ETH": (50, 50)}
rows, r0, _b = scen("X8", ACC_X8, ORD_X8, [
    (at(1, 8, 0, 30), "late", at(0, 23)),
    (at(1, 8, 59, 50), "snap", ACC_X8, ORD_X8),
    (at(1, 9), "build", (211000, 200000, 211000))], (211000, 200000, 211000))
chk(rows_ok(rows) and near(r0[2], 210000), "X8 순현금 ≠ 0 · 둘 다 아직 열림 + 무관한 늦은 행 = D $211,000(관측 원화 그대로)", (r0, rows))
rows, r0, _b = scen("X8b", ACC_X8, ORD_X8, [
    (at(1, 8, 0, 30), "consume", [fin("x8s", "ask", 100, "cancel", [(at(0, 15, 30), 50, 60 * KRW1)]),
                                  fin("x8b", "bid", 100, "done", [(at(0, 15), 50, 50 * KRW1), (at(1, 7, 59, 30), 50, 50 * KRW1)])]),
    (at(1, 8, 59, 50), "snap", {"KRW": (60 * KRW1, 0), "ETH": (150, 0)}, [])], (210000, 200000, 210000))
chk(rows_ok(rows), "X8b 순현금 ≠ 0 · 매도 D · 매수 D+1 기장 = D $210,000 · D−1 $200,000 · 지금 $210,000", rows)
C = ledger()
b = new_builder()
r0 = p1_prefix(C, b, mid_build=False, acc={"KRW": (0, 100 * KRW1), "ETH": (0, 100)},
               orders=[oo("n1", "bid", 100, 0, 0), oo("n2", "ask", 100, 0, 0)])
C.conn.close()
chk(not r0[3] and not r0[5] and near(r0[2], 200000), "X9 체결 없는 열린 주문만 = 원화 관측 보호 표식(ufk)·묶음(ufz) 없음 · $200,000", r0)
C = ledger(closed=True)
b = new_builder()
r0 = p1_prefix(C, b, mid_build=True)
clock(at(1, 8, 0, 30))
consume(C, [FIN_B, FIN_S])
snap(at(1, 8, 59, 50), ACC_END)
rows, _b = rebuild_views(b, at(1, 9))
C.conn.close()
chk(r0[3] == 1 and not r0[5] and near(r0[2], 200000) and all(near(r9[1], 200000) and near(r9[2], 200000) and not r9[9] for r9 in rows),
    "X10 원장 보유 0(실시간 잔고 행 코인) 순수량 0 체결 = ufz 없음 · ufk 있음 · 마감 $200,000 → 기장 뒤 D·D−1 $200,000 · 원화 불신 없음", (r0, rows))
rows, r0, _b = scen("X11", ACC_MID, ORD_MID, [
    (at(1, 8, 0, 30), "consume", [FIN_B, FIN_S]),
    (at(1, 8, 59, 50), "snap", ACC_END, [])], (200000, 200000, 200000), mid=False, age=700)
chk(rows_ok(rows) and r0[3] == 1 and not r0[1], "X11 낡은 D 스냅숏(순수량 0 체결) = ufk · 유예 아님 → 기장 뒤 D·D−1·지금 $200,000", (r0, rows))


def _defer(b9):
    dc9 = json.load(open(web.DAILY_PATH))
    dc9["_live"] = dict(dc9["_live"], defer=True)
    dc9.pop("_live_ok", None)
    json.dump(dc9, open(web.DAILY_PATH, "w"))
    b9.daily = dc9


rows, r0, b12 = scen("X12", ACC_MID, ORD_MID, [
    (at(1, 0, 0, 20), "snap", ACC_MID, ORD_MID),
    (at(1, 0, 0, 30), "build", (200000, 200000, 200000)),
    (at(1, 8, 0, 30), "consume", [FIN_B, FIN_S]),
    (at(1, 8, 59, 50), "snap", ACC_END, [])], (200000, 200000, 200000), mid=False, pre=_defer)
xv12 = (json.load(open(web.DAILY_PX_PATH)).get(DISO) or {}).get("xv") or {}
chk(rows_ok(rows) and rows[0][3] is not None and xv12.get("ufz") == {"ETH": {"b1": -70000000.0, "s1": 70000000.0}},
    "X12 유예 마감 → 부분 동결(고정값에 ufz 보관) → 기장 뒤 D·D−1·지금 $200,000", (xv12.get("ufz"), rows))


def _strip(b9):
    dc9 = json.load(open(web.DAILY_PATH))
    for k9 in ("_live", "_live_ok"):
        if isinstance((dc9.get(k9) or {}).get("xv"), dict):
            dc9[k9]["xv"]["ufz"] = {"ETH": {"b1": "x", "s1": None}} if k9 == "_live" else None
            if dc9[k9]["xv"]["ufz"] is None:
                dc9[k9]["xv"].pop("ufz")
    json.dump(dc9, open(web.DAILY_PATH, "w"))
    b9.daily = dc9


rows, r0, _b = scen("X13", ACC_MID, ORD_MID, [
    (at(1, 8, 0, 30), "consume", [FIN_B, FIN_S]),
    (at(1, 8, 59, 50), "snap", ACC_END, [])], None, mid=False, pre=_strip)
chk(all(r9[1] is not None and near(r9[7], 200000) for r9 in rows), "X13 손상된 묶음 표식 = 예외 없음 · 지금 $200,000", rows)

S14 = fin("s1", "ask", 100, "done", [(at(0, 15, 30), 50, 50 * KRW1), (at(1, 7, 59, 50), 50, 50 * KRW1)])
S14_bare = {k9: v9 for k9, v9 in S14.items() if k9 not in ("trades", "trades_count")}
C = ledger()
b = new_builder()
p1_prefix(C, b, mid_build=True, prior=True)
clock(at(1, 8, 0, 30))
consume(C, [FIN_B, S14_bare])
snap(at(1, 8, 59, 50), {"KRW": (100 * KRW1, 0), "ETH": (100, 0)})
f = build_on(b, at(1, 9))
x14a = view(b, f, "옛 원본(생성 시각 D) 기장 뒤")
xv14a = (json.load(open(web.DAILY_PX_PATH)).get(DISO) or {}).get("xv") or {}
clock(at(1, 9, 10))
C.conn.execute("BEGIN")
r14 = C._consume_order_trades({"orders": [dict(S14)], "ts": int(CLK[0]), "src": "test"})
C.conn.commit()
C._hist_late_scan(now=CLK[0])
snap(at(1, 9, 19, 50), {"KRW": (100 * KRW1, 0), "ETH": (100, 0)})
rows, _b = rebuild_views(b, at(1, 9, 20))
xv14 = (json.load(open(web.DAILY_PX_PATH)).get(DISO) or {}).get("xv") or {}
C.conn.close()
chk(r14.get("moved") == 1 and xv14a.get("ku0") is not None and all_ok(rows, 200000, 200000, 200000)
    and near(((xv14.get("p") or {}).get("ku") or [0])[0], 100 * KRW1),
    "X14 묶음 켜 맞춘 뒤 다시 기장으로 꺼짐 = 원본 관측 원화로 되돌림 · D·D−1·지금 $200,000(맞춘 값 고정 잔재 없음)",
    (r14, x14a, xv14a.get("ku0"), (xv14a.get("p") or {}).get("ku"), (xv14.get("p") or {}).get("ku"), rows))

import random

rng = random.Random(1011)
bad_r, n_r = [], 0
for i_r in range(36):
    ab, as_ = rng.choice((10, 30, 50, 50, 70, 90)), rng.choice((10, 30, 50, 50, 70, 90))
    if rng.random() < 0.5:
        as_ = ab
    fb, fs = rng.choice(("done", "cancel", "open")), rng.choice(("done", "cancel", "open"))
    mid_r, prior_r, late_r = rng.random() < 0.5, rng.random() < 0.5, rng.random() < 0.3
    ub, us = f"rb{i_r}", f"rs{i_r}"
    acc_d = {"KRW": (as_ * KRW1, (100 - ab) * KRW1), "ETH": (ab, 100 - as_)}
    ords_d = [oo(ub, "bid", 100, ab, ab * KRW1), oo(us, "ask", 100, as_, as_ * KRW1)]
    fins, open_now = [], []
    eb, es = ab, as_
    if fb == "done":
        fins.append(fin(ub, "bid", 100, "done", [(at(0, 15), ab, ab * KRW1), (at(1, 7, 59, 30), 100 - ab, (100 - ab) * KRW1)]))
        eb = 100
    elif fb == "cancel":
        fins.append(fin(ub, "bid", 100, "cancel", [(at(0, 15), ab, ab * KRW1)]))
    else:
        open_now.append(ords_d[0])
    if fs == "done":
        fins.append(fin(us, "ask", 100, "done", [(at(0, 15, 30), as_, as_ * KRW1), (at(1, 7, 59, 40), 100 - as_, (100 - as_) * KRW1)]))
        es = 100
    elif fs == "cancel":
        fins.append(fin(us, "ask", 100, "cancel", [(at(0, 15, 30), as_, as_ * KRW1)]))
    else:
        open_now.append(ords_d[1])
    lock_k = (100 - ab) * KRW1 if fb == "open" else 0
    lock_e = (100 - as_) if fs == "open" else 0
    acc_n = {"KRW": (100 * KRW1 - eb * KRW1 + es * KRW1 - lock_k, lock_k), "ETH": (100 + eb - es - lock_e, lock_e)}
    steps = []
    if fins:
        steps.append((at(1, 8, 0, 30), "consume", fins))
    if late_r:
        steps.append((at(1, 8, 0, 40), "late", at(0, 23)))
    steps.append((at(1, 8, 59, 50), "snap", acc_n, open_now))
    w_r = 200000 + (1000 if late_r else 0)
    rows, r0, _b = scen(f"R{i_r}", acc_d, ords_d, steps, (w_r, 200000, w_r), prior=prior_r, mid=mid_r)
    n_r += 1
    if not rows_ok(rows):
        bad_r.append(((ab, as_, fb, fs, mid_r, prior_r, late_r), rows[0][:10]))
chk(not bad_r, f"R 무작위 {n_r}개(체결량·완료/취소/열림·자정 뒤 동결·D−1 관측·무관한 늦은 행) = D·D−1·지금 늘 일치(±체결 금액 없음 · 원화 불신 없음)",
    bad_r[:4])

import ubfill

dz = ubfill.deltas([oo("a", "bid", 100, 50, 50 * KRW1), oo("b", "ask", 100, 50, 50 * KRW1)], {}, at(0, 23))
d0 = ubfill.deltas([oo("a", "bid", 100, 0, 0), oo("b", "ask", 100, 0, 0)], {}, at(0, 23))
chk(ubfill.has_cash_flow(dz) and float(ubfill.cash_krw(dz)) == 0 and not ubfill.has_cash_flow(d0) and not ubfill.has_cash_flow(None)
    and dz["ETH"]["dq"] == 0 and dz["ETH"]["ko"] == {"a": Decimal(-70000000), "b": Decimal(70000000)},
    "U has_cash_flow: 순현금 0 묶음 = 참(주문별 몫 ±₩70,000,000) · 체결 없음·불신 = 거짓", (dz, d0))

T.finish()
