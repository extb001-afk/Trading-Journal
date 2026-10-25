#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import copy  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from decimal import Decimal as D  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import _costsim as S  # noqa: E402
import attfreeze  # noqa: E402
import db  # noqa: E402
import histcurve  # noqa: E402
import paths  # noqa: E402
import statefile  # noqa: E402
import web  # noqa: E402
import xparts  # noqa: E402

chk = T.chk
KST = timezone(timedelta(hours=9))
TOL = 0.011
KEYS = ("mk", "tr", "fee", "rs", "kx", "xo", "lp", "ev")


def ep(day, h=0):
    return int(datetime.fromisoformat(day).replace(tzinfo=KST, hour=h).timestamp())


DAY = "2026-09-20"
T0 = ep(DAY, 10)
OLD = ep("2026-08-01")


def fixture(k, ext=0):
    c = S.reset(px={"TKJ": .2, "USDC": 1., "USDT": 1.})
    S.PXF[0] = lambda sym, at: (.18 if at < T0 else .2) if sym == "TKJ" else None
    ch = S.Ch(c)
    a = ch.tok("base", "0x" + "11" * 20, "TKJ", 18)
    u = ch.tok("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6)
    ch.tx("base", "seed", OLD, [(u, 1000 * k, "acq", 1000 * k), (a, (10 + ext) * k, "acq", 1.8 * k + ext * k * .18)], "PROGRAM_IN")
    ch.tx("base", "buy", T0, [(a, 1000 * k, "acq", 200 * k), (u, -200 * k, "disp", 200 * k)], "SWAP")
    tx = ch.tx("base", "xfer", T0 + 1800, [(a, -1000 * k, "move_out", None)], "TRANSFER_OUT_EX")
    if ext:
        ch.tx("base", "send", T0 + 600, [(a, -ext * k, "move_out", None), (a, ext * k, "move_in", None, "out:base:0x" + "9b" * 20)], "TRANSFER_OUT")
    S.ex("bybit", deposits=[S.norm_row("bybit", "received", "TKJ", str(1000 * k), 0, tx, "ACCEPTED", T0 + 1800, T0 + 1800)])
    S.fills("bybit", [S.norm_fill("bybit", "sale", (T0 + 3600) * 1000, "TKJ", "USDT", "sell", ".199", str(1000 * k), "0", "")])
    f, G, _rr = S.build()
    conn = db.open_db(paths.DB_PATH)
    assets = [dict(r) for r in conn.execute("SELECT * FROM assets")]
    ga = next(r["group_id"] for r in assets if r["asset_id"] == a)
    gb = next(r["group_id"] for r in assets if r["symbol"] == "TKJ" and r["asset_id"] != a)
    hold = {gid: sum((D(str(q)) for _, q in g.get("qty_timeline") or ()), D(0)) for gid, g in G.items()}
    return conn, f, G, ga, gb, hold


def extra(at):
    return {"ub": 0., "fiat": 0., "lp": 0., "ubs": {}, "ub_tl": {}, "krw_up": 0., "krw_other": 0., "rate": 1400., "krw_up_tl": None,
            "xsrc": {"now": {"ts": at, "ku": 0., "kb": 0., "ub": {}, "rest": 0.}, "base": {"ku": [0., at], "kb": [0., at]}, "tl": {"ku": [], "kb": []}, "first": {}}}


def builder(ga):
    b = object.__new__(web.StateBuilder)
    b.daily, b.daily_px, b._daily_seed, b._upbit_krw_tl = {"_v": web.DAILY_V}, {"_v": 1}, {}, None
    b.spot = SimpleNamespace(rate=1400., fx_basis=1400., price=lambda x: None)
    b.px = SimpleNamespace(fx_at=lambda ms: 1400., candle_usd=lambda sym, ms: None, flush=lambda: None)
    today = datetime(2026, 9, 21, tzinfo=KST)
    for i in range(45):
        day = (today - timedelta(days=i + 1)).strftime("%Y-%m-%d")
        ps = {str(ga): .2 if day >= DAY else .18}
        b.daily_px[day] = {"p": ps, "k": {k: "live" for k in ps}, "x": 0.,
                           "xv": {"v": xparts.GEN, "p": {"ku": [0., "snap"], "kb": [0., "snap"], "ub": [{}, "snap"], "rest": [0., "snap"]}, "fx": 1400., "how": "live"}}
    return b


def clear_state():
    for p in ("daily_cache.json", "daily_px.json", attfreeze.FILE):
        if os.path.exists(paths.state(p)):
            os.remove(paths.state(p))


def run(fx, live_b, mode, pre=None):
    conn, f, G, ga, gb, hold = fx
    clear_state()
    b = builder(ga)
    live = {ga: .2, **({gb: live_b} if live_b is not None else {})}
    real = {"rbd": {DAY: sum(float(v) for k, v in (f.get("realizedByDate") or {}).items() if k in (DAY, DAY[5:]))}, "lpf": {}, "stk": {}, "unv": {}}
    if mode == "daily":
        today = datetime(2026, 9, 21, tzinfo=KST)
        x = extra(today.timestamp() + 12 * 3600)
        ser = b._daily_series(G, today, {}, live, ca_gids={ga}, ex_gids={gb}, skip_gids=set(), pending_gids=set(), hold_qty=hold,
                              extra=copy.deepcopy(x), extra_ok=True, now_ts=x["xsrc"]["now"]["ts"])
        fl = b._daily_flows(conn, ser, G, today, live, frozenset(), 1400.)
        for r in ser:
            if r["date"] in fl:
                r["flow"] = fl[r["date"]][0]
        att = b._daily_attrib(conn, ser, G, today, live, frozenset(), x, real=real)[DAY[5:]]
        return next(r for r in ser if r["date"] == DAY[5:]), att, None
    today = datetime(2026, 10, 25, 12, tzinfo=KST)
    x = extra(today.timestamp())
    fk = {"today": today.strftime("%Y-%m-%d"), "G": G, "skip": frozenset(), "offc": frozenset(), "rate": 1400., "transit": [], "wdt": {}}
    kit = histcurve.make_kit(today.strftime("%Y-%m-%d"), G, hold, frozenset(), {ga}, {gb: "bybit"}, set(), {}, live, {}, [], x, [], {}, flow_kit=fk)
    ctx = (G, today, live, frozenset(), x, real, None)
    if mode == "bf":
        rec = attfreeze.bf_records(b, conn, ctx, (kit, attfreeze._bf_px(b.daily_px), histcurve.HIST.flow_fn), [DAY], int(today.timestamp()))[DAY]
        return rec["r"], rec["r"]["att"], None
    statefile.atomic_write_json(paths.state(attfreeze.FILE), pre or {"_v": 1, "d": {}, "dm": [], "bf": {"v": attfreeze.BF_V - 1}})
    with open(paths.state("backfill_done"), "w") as fh:
        fh.write("1")
    rep = [attfreeze.backfill(b, conn, lambda: kit, ctx, now=int(today.timestamp()))]
    nctx = (G, today, {ga: .2, gb: .104}, frozenset(), x, real, None)
    rep.append(attfreeze.backfill(b, conn, lambda: kit, nctx, now=int(today.timestamp()) + 1000))
    fresh = builder(ga)
    rep.append(attfreeze.backfill(fresh, conn, lambda: kit, nctx, now=int(today.timestamp()) + 2000))
    disk = statefile.read_json(paths.state(attfreeze.FILE), {})
    served = attfreeze.serve({}, {}, DAY, DAY, int(today.timestamp()))[DAY]
    return dict(disk["d"][DAY]["r"], _st=disk["d"][DAY].get("st"), _bf=disk.get("bf")), served["r"]["att"], rep


def same(a, b):
    return all(abs(float(a.get(k) or 0) - float(b.get(k) or 0)) <= TOL for k in KEYS)


def pick(a):
    return {k: a.get(k) for k in KEYS if a.get(k)}


for k in (1, 1000):
    fx = fixture(k)
    for live_b in (.098, .104, .5, None):
        r0, a0, _ = run(fx, live_b, "daily")
        chk(abs(r0["flow"]) < TOL and abs(a0["rs"]) < TOL * k and not a0.get("np"), f"P1 ×{k} 30일 창 · 지금 {live_b}: 순유입 0 · 나머지 0", pick(a0))
        r1, a1, _ = run(fx, live_b, "bf")
        chk(abs(r1["flow"]) < TOL and abs(a1["rs"]) < TOL * k and not a1.get("np") and same(a1, a0),
            f"P1 ×{k} 복원 계산 · 지금 {live_b}: 순유입 0 · 나머지 0 · np 없음 · 30일 분해와 같음", (pick(a1), pick(a0)))
        if k == 1:
            r2, a2, rep = run(fx, live_b, "persist")
            chk(r2["_st"] == "b" and r2["_bf"]["v"] == attfreeze.BF_V and abs(a2["rs"]) < TOL and same(a2, a0) and rep[1]["n"] == 0 and rep[2]["n"] == 0,
                f"P1 복원 저장 · 지금 {live_b} → 다음 빌드 시세 바뀜·재시작 = 안 다시 함 · serve 분해 = 30일과 같음", (pick(a2), rep))
    fx[0].close()

fx = fixture(1)
bad = {"r": {"date": DAY[5:], "val": 1001.0, "flow": 0.0, "att": {"mk": 0.2, "tr": 199.0, "rs": -200.0, "np": 1}}, "p": {"date": "09-19", "val": 1001.8},
       "det": {}, "st": "b", "at": 1, "h": "x"}
kept = {"r": {"date": "09-18", "val": 1.0, "att": {"rs": 5.0}}, "p": {}, "det": {}, "st": "s", "at": 1, "h": "y"}
r3, a3, rep3 = run(fx, .5, "persist", pre={"_v": 1, "d": {DAY: bad, "2026-09-18": kept}, "dm": [], "bf": {"v": attfreeze.BF_V - 1, "at": 1}})
disk3 = statefile.read_json(paths.state(attfreeze.FILE), {})
chk(attfreeze.BF_V >= 4 and rep3[0].get("re", 0) >= 1 and abs(a3["rs"]) < TOL and abs(float(a3.get("tr") or 0) + 1.0) < TOL and not a3.get("np")
    and disk3["d"]["2026-09-18"] == kept and disk3["bf"]["v"] == attfreeze.BF_V,
    "P3 옛 세대 'b'(매매 199 · 나머지 −200) = 다시 계산(매매 −1 · 나머지 0) · 's' 기록 그대로 · 세대 봉인", (pick(a3), rep3[0]))
fx[0].close()

fx = fixture(1, ext=500)
r0, a0, _ = run(fx, .5, "daily")
r1, a1, _ = run(fx, .5, "bf")
chk(r0["flow"] < -50 and abs(r1["flow"] - r0["flow"]) < TOL and same(a1, a0) and abs(a1["rs"]) < TOL,
    "P4 같은 날 남의 주소로 보낸 TKJ = 복원 순유출 = 30일 순유출(숨기지 않음) · 분해 같음", (r0["flow"], r1["flow"], pick(a1), pick(a0)))
conn, f, G, ga, gb, hold = fx
tabs = {d: {"p": dict(v.get("p") or {})} for d, v in builder(ga).daily_px.items() if d != "_v"}
fk = {"today": "2026-10-25", "G": G, "skip": frozenset(), "offc": frozenset(), "rate": 1400., "transit": [], "wdt": {}}
plain = histcurve.HIST.flow_fn(fk, [DAY], tabs, lambda iso: 1400.)
box = {"src": {}}
withatt = histcurve.HIST.flow_fn(fk, [DAY], tabs, lambda iso: 1400., att=box)
chk(plain == withatt and "px" in box and (DAY, gb) in box["px"], "P4 장기 곡선 flow_fn(att 없음) 값 = att 준 호출 값 · 받는 곳에 그날 레그 가격", (plain, sorted(box.get("px") or {})[:4]))
conn.close()
T.finish()
