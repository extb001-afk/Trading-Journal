#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import time
from datetime import datetime as _dt, timedelta as _td
from decimal import Decimal

import common

CFG = os.path.join(os.environ["TJ_BASE"], "config.json")
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(CFG, "w"))
import db as dbm
import histcurve
import netpace
import web
import xparts

chk = T.chk
for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker"):
    if hasattr(web.StateBuilder, _m):
        setattr(web.StateBuilder, _m, lambda self: None)
netpace.wait = lambda url, now=None, sleep=None: None
web.pricing._gj = lambda url, timeout=10.0: None
S = common.STATE_DIR
FX = 1400.0
DAY = 86400
NOW = int(time.time())
UP = os.path.join(S, "upbit_balances.json")
PX = {"ETH": 1000.0, "XRP": 1.0, "SOL": 100.0, "USDT": 1.0}
WAL = "0x" + "c3" * 20
KRW1 = 1000 * FX
web.pricing.PxCache.candle_usd = lambda self, sym, ms: PX.get(str(sym).upper())
YD = _dt.now(web.KST) - _td(days=1)
YISO, YKEY = YD.strftime("%Y-%m-%d"), YD.strftime("%m-%d")
YEND = YD.replace(hour=23, minute=59, second=59, microsecond=0).timestamp()

json.dump({"usd": PX, "usd_ts": {k: NOW for k in PX}, "rate": FX, "updated": NOW, "dex_usd": {}, "dex_ts": {}, "dex_res": {}, "dex_res_ts": {},
           "fx_basis": FX, "ex_usd": {}, "ex_ts": {}}, open(web.SPOT_PATH, "w"))
common.atomic_write_json(web.PREFS_PATH, {"plans": {}, "ignored": []})
open(os.path.join(S, "backfill_done"), "w").write("1")


def _wipe():
    for sfx in ("", "-wal", "-shm"):
        if os.path.exists(common.DB_PATH + sfx):
            os.remove(common.DB_PATH + sfx)
    for fn in ("daily_cache.json", "daily_px.json"):
        if os.path.exists(os.path.join(S, fn)):
            os.remove(os.path.join(S, fn))


def _grp(c, sym):
    r = c.execute("SELECT group_id FROM asset_groups WHERE name=?", (sym,)).fetchone()
    if r:
        return r[0]
    c.execute("INSERT INTO asset_groups (name) VALUES (?)", (sym,))
    return c.execute("SELECT group_id FROM asset_groups WHERE name=?", (sym,)).fetchone()[0]


def _ex_asset(c, sym):
    r = c.execute("SELECT asset_id FROM assets WHERE address=?", (f"upbit:{sym}",)).fetchone()
    if r:
        return r[0]
    c.execute("INSERT INTO assets (kind, chain, address, symbol, decimals, confirmed, group_id) VALUES ('exchange_currency',NULL,?,?,8,1,?)",
              (f"upbit:{sym}", sym, _grp(c, sym)))
    return c.execute("SELECT last_insert_rowid()").fetchone()[0]


def _post(c, sid, ts, aid, loc, qty, dec, cost_usd, kind):
    c.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind,"
              " event, classifier_ver) VALUES (?,?,?,0,?,?,?,?,?,NULL,?,?,4)",
              ("exchange" if loc.startswith("exchange:") else "chain", "upbit:trade" if loc.startswith("exchange:") else "eth", sid, int(ts), aid, loc,
               str(int(Decimal(str(qty)) * 10 ** dec)), repr(float(cost_usd)), "acq" if qty > 0 else "disp", ("EXF_BUY" if qty > 0 else "EXF_SELL")
               if loc.startswith("exchange:") else "SWAP"))


def _pos_add(c, gid, loc, dq):
    r = c.execute("SELECT qty_norm FROM positions WHERE group_id=? AND location=?", (gid, loc)).fetchone()
    if r:
        c.execute("UPDATE positions SET qty_norm=? WHERE group_id=? AND location=?", (str(Decimal(r[0]) + Decimal(str(dq))), gid, loc))
    else:
        c.execute("INSERT INTO positions (group_id, location, qty_norm) VALUES (?,?,?)", (gid, loc, str(Decimal(str(dq)))))


def ledger(upbit=None, upbit_closed=None, wallet_eth=None):
    _wipe()
    c = dbm.open_db(common.DB_PATH)
    gid = {}
    for sym, q in sorted((upbit or {}).items()):
        aid = _ex_asset(c, sym)
        gid[sym] = _grp(c, sym)
        _post(c, f"init{sym}", NOW - 20 * DAY, aid, "exchange:upbit", q, 8, q * PX[sym], "acq")
        _pos_add(c, gid[sym], "exchange:upbit", q)
    for sym, q in sorted((upbit_closed or {}).items()):
        aid = _ex_asset(c, sym)
        gid[sym] = _grp(c, sym)
        _post(c, f"old{sym}", NOW - 20 * DAY, aid, "exchange:upbit", q, 8, q * PX[sym], "acq")
        _post(c, f"oldx{sym}", NOW - 10 * DAY, aid, "exchange:upbit", -q, 8, 0, "disp")
        _pos_add(c, gid[sym], "exchange:upbit", 0)
    if wallet_eth:
        gid["ETH"] = _grp(c, "ETH")
        c.execute("INSERT INTO assets (kind, chain, address, symbol, decimals, confirmed, group_id) VALUES ('native','eth',NULL,'ETH',18,1,?)", (gid["ETH"],))
        an = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        _post(c, "0xw1", NOW - 19 * DAY, an, f"wallet:eth:{WAL}", wallet_eth, 18, wallet_eth * 1000, "acq")
        _pos_add(c, gid["ETH"], f"wallet:eth:{WAL}", wallet_eth)
    c.commit()
    c.close()
    return gid


def book(uu, side, vol, funds, created_ts, fill_ts=None, fee=0):
    c = dbm.open_db(common.DB_PATH)
    pl = {"uuid": uu, "market": "KRW-ETH", "side": side, "state": "done", "ord_type": "limit", "price": "1400000", "volume": str(vol),
          "executed_volume": str(vol), "executed_funds": str(funds), "paid_fee": str(fee),
          "created_at": _dt.fromtimestamp(created_ts, web.KST).isoformat()}
    if fill_ts:
        pl["trades"] = [{"created_at": _dt.fromtimestamp(fill_ts, web.KST).isoformat(), "volume": str(vol), "funds": str(funds)}]
    c.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('upbit','order',?,1,?,?)",
              (uu, json.dumps(pl), int(fill_ts or created_ts)))
    aid = _ex_asset(c, "ETH")
    sg = 1 if side == "bid" else -1
    _post(c, uu, int(fill_ts or created_ts), aid, "exchange:upbit", sg * vol, 8, (funds + fee * sg) / FX, "acq" if sg > 0 else "disp")
    _pos_add(c, _grp(c, "ETH"), "exchange:upbit", sg * vol)
    c.commit()
    c.close()


def snap(accounts, orders=(), age=0):
    common.atomic_write_json(UP, {"ts": int(time.time()) - age, "open_orders": list(orders),
                                  "accounts": [{"currency": k, "balance": str(v[0]), "locked": str(v[1])} for k, v in accounts.items()]})


def order(uu, side, vol, exe, funds, fee="0"):
    return {"uuid": uu, "market": "KRW-ETH", "side": side, "state": "wait", "ord_type": "limit", "volume": str(vol),
            "remaining_volume": str(Decimal(str(vol)) - Decimal(str(exe))), "executed_volume": str(exe),
            "executed_funds": str(funds), "paid_fee": str(fee), "created_at": _dt.fromtimestamp(NOW - 50, web.KST).isoformat()}


def new_builder():
    b = web.StateBuilder()
    b.skip_gen_check = True
    return b


def build_on(b):
    t = int(time.time())
    for k, v in PX.items():
        b.spot.ex_usd[f"upbit:{k}"] = v
        b.spot.ex_ts[f"upbit:{k}"] = t
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


def today_val(f):
    d9 = f.get("dailySeries") or []
    return float(d9[-1]["val"]) if d9 else None


def day_val(f, key=YKEY):
    return next((float(d9["val"]) for d9 in f.get("dailySeries") or [] if d9.get("date") == key), None)


def bad_ku(b):
    return (((b.__dict__.get("_x_kit") or {}).get("src") or {}).get("bad") or {}).get("ku")


def eth_rows(f):
    return [(c9.get("key"), round(float(c9["qty"]), 8)) for c9 in (f.get("coins") or []) if c9.get("sym") == "ETH"]


def near(a, b, tol=0.02):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


def kit_checks(tag, b, f, want_y, want_ku_y, ub_y_syms, old_x=None):
    kit = histcurve.HIST.kit or {}
    row = next((r9 for r9 in kit.get("daily") or () if r9[0] == YISO), None)
    chk(row is not None and near(row[1], want_y), f"{tag} 장기 곡선 재료 30일 행 어제 = ${want_y:,.0f}", row)
    src = histcurve.HistCurve._x_src(kit)
    p = xparts.resolve(YEND, src, pinned=(((kit.get("xk") or {}).get("days") or {}).get(YISO) or {}).get("p"))
    ku = (p.get("ku") or [None])[0]
    ubs = sorted(xparts.ub_norm((p.get("ub") or [{}])[0]))
    chk(near(ku, want_ku_y, 1) and ubs == sorted(ub_y_syms), f"{tag} 장기 곡선 원장 밖 규칙: 어제 원화 ₩{want_ku_y:,.0f} · 업비트 미매칭 {sorted(ub_y_syms)}",
        (ku, ubs, p.get("ub")))
    if old_x is not None:
        iso_o = (YD - _td(days=40)).strftime("%Y-%m-%d")
        xr = histcurve.HIST._x_rec(kit, iso_o, lambda gid: 0.0)
        chk(near(xr.get("x"), old_x, 1), f"{tag} 장기 곡선 창 밖 옛날(40일 전) 원장 밖 금액 = ${old_x:,.0f}(현금 체결 전 · 실시간 행 체결분 이월 없음)", xr)


def a_snap(exe, age):
    if exe == 0:
        snap({"KRW": (100 * KRW1, 0), "XRP": (10, 0)}, [], age=age)
    else:
        snap({"KRW": (0, (100 - exe) * KRW1), "XRP": (10, 0), "ETH": (exe, 0)}, [order("a1", "bid", 100, exe, exe * KRW1)], age=age)


ledger(upbit={"XRP": 10})
b = new_builder()
a_snap(0, 60)
f = build_on(b)
seq = [("S0", day_val(f), round(today_val(f) or 0, 2), round(total(f), 2), bad_ku(b), eth_rows(f))]
chk(near(day_val(f), 100010) and near(today_val(f), 100010), "A 준비: 어제·오늘 $100,010(XRP 10 + 원화 $100,000)", seq[0])
for nm, exe, age in (("S1", 50, 40), ("S1'", 50, 30), ("S2", 80, 20)):
    a_snap(exe, age)
    f = build_on(b)
    seq.append((nm, day_val(f), round(today_val(f) or 0, 2), round(total(f), 2), bad_ku(b), eth_rows(f)))
    if nm == "S1":
        inf = dict(b.__dict__.get("_ub_fill_info") or {})
        chk(near(inf.get("krw_tl"), -50 * KRW1, 1), "A S1 체결 원화 몫 = −₩70,000,000(코인 보정과 따로 · 종전 0)", inf)
        kit_checks("A S1", b, f, 100010, 100 * KRW1, [])
book("a1", "bid", 100, 100 * KRW1, NOW - 50, fill_ts=time.time() - 15)
snap({"KRW": (0, 0), "XRP": (10, 0), "ETH": (100, 0)}, [], age=10)
f = build_on(b)
seq.append(("S3", day_val(f), round(today_val(f) or 0, 2), round(total(f), 2), bad_ku(b), eth_rows(f)))
chk(all(near(v9, 100010) and near(t9, 100010) and near(tt9, 100010) and not bd9 and len(r9) <= 1 for _n9, v9, t9, tt9, bd9, r9 in seq),
    "A 첫 부분 매수 같은 빌더 S0→S1→S1 반복→S2(80)→S3(종결 기장) = 어제 늘 $100,010 · 오늘 $100,010 · ETH 한 줄 · 원화 불신 없음(종전 S1 부터 어제 $50,010)",
    seq)

def b_snap(exe, age, fee_b=0, fee_s=0):
    if exe == 0:
        snap({"KRW": (100 * KRW1, 0), "ETH": (100, 0)}, [], age=age)
        return
    krw = 100 * KRW1 - exe * KRW1 - fee_b + exe * 1.2 * KRW1 - fee_s
    snap({"KRW": (krw - (100 - exe) * KRW1, (100 - exe) * KRW1), "ETH": (exe, 100 - exe)},
         [order("b1", "bid", 100, exe, exe * KRW1, fee_b), order("s1", "ask", 100, exe, exe * 1.2 * KRW1, fee_s)], age=age)


ledger(upbit={"ETH": 100})
b = new_builder()
b_snap(0, 60)
f = build_on(b)
seq = [("S0", day_val(f), round(today_val(f) or 0, 2), round(total(f), 2), bad_ku(b), 200000)]
for nm, exe, age, want in (("S1", 50, 40, 210000), ("S1'", 50, 30, 210000), ("S2", 80, 20, 216000)):
    b_snap(exe, age)
    f = build_on(b)
    seq.append((nm, day_val(f), round(today_val(f) or 0, 2), round(total(f), 2), bad_ku(b), want))
    if nm == "S1":
        inf = dict(b.__dict__.get("_ub_fill_info") or {})
        chk(near(inf.get("krw_tl"), 10 * KRW1, 1), "B S1 순수량 0 의 원화 몫 = +₩14,000,000(종전 0 — dq = 0 이면 건너뜀)", inf)
        kit_checks("B S1", b, f, 200000, 100 * KRW1, [])
book("b1", "bid", 100, 100 * KRW1, NOW - 50, fill_ts=time.time() - 15)
book("s1", "ask", 100, 120 * KRW1, NOW - 50, fill_ts=time.time() - 14)
snap({"KRW": (120 * KRW1, 0), "ETH": (100, 0)}, [], age=10)
f = build_on(b)
seq.append(("S3", day_val(f), round(today_val(f) or 0, 2), round(total(f), 2), bad_ku(b), 220000))
chk(all(near(v9, 200000) and near(t9, w9) and near(tt9, w9) and not bd9 for _n9, v9, t9, tt9, bd9, w9 in seq),
    "B 순수량 0 같은 빌더 S0→S1→반복→S2(80)→S3(종결) = 어제 늘 $200,000 · 오늘 $210,000→$216,000→$220,000 · 원화 불신 없음(종전 어제 $210,000)", seq)

ledger(upbit={"ETH": 100})
b_snap(50, 30, fee_b=25 * FX, fee_s=30 * FX)
b = new_builder()
f = build_on(b)
chk(near(day_val(f), 200000) and near(today_val(f), 209945) and near(total(f), 209945),
    "B2 수수료 포함 순수량 0(첫 빌드) = 어제 $200,000 · 오늘 $209,945(원화 순증 $10,000 − 수수료 $55 그대로)", (day_val(f), today_val(f), total(f)))
kit_checks("B2", b, f, 200000, 100 * KRW1, [], old_x=100000)

for cold in (False, True):
    ledger(upbit_closed={"ETH": 100})
    b = new_builder()
    f0 = None
    if not cold:
        snap({"KRW": (100 * KRW1, 0)}, [], age=60)
        f0 = build_on(b)
    snap({"KRW": (0, 50 * KRW1), "ETH": (50, 0)}, [order("c1", "bid", 100, 50, 50 * KRW1)], age=30)
    f = build_on(b)
    chk((cold or near(day_val(f0), 100000)) and near(day_val(f), 100000) and near(today_val(f), 100000) and near(total(f), 100000) and not bad_ku(b),
        f"C 업비트 보유 0(원장 그룹 있음) → 재매수 부분 체결{' · 관측 없음(첫 빌드)' if cold else ''} = 어제 $100,000 · 오늘 $100,000"
        f"(종전 어제 {'$100,000 — 원화 $50,000 + 실시간 행 ETH 50 이월이 우연히 맞음' if cold else '$50,000'})",
        (day_val(f0) if f0 else None, day_val(f), today_val(f), total(f), bad_ku(b), eth_rows(f)))

for cold in (False, True):
    ledger(wallet_eth=5)
    b = new_builder()
    f0 = None
    if not cold:
        snap({"KRW": (100 * KRW1, 0)}, [], age=60)
        f0 = build_on(b)
    snap({"KRW": (0, 50 * KRW1), "ETH": (50, 0)}, [order("d1", "bid", 100, 50, 50 * KRW1)], age=30)
    f = build_on(b)
    wl = [l9 for c9 in (f.get("coins") or []) if c9.get("sym") == "ETH" for l9 in (c9.get("locs") or []) if l9.get("w") != "업비트"]
    chk((cold or near(day_val(f0), 105000)) and near(day_val(f), 105000) and near(today_val(f), 105000) and near(total(f), 105000)
        and len(wl) == 1 and near(wl[0].get("qty"), 5),
        f"D 지갑에만 ETH 5 → 업비트 첫 부분 매수{' · 관측 없음(첫 빌드)' if cold else ''} = 어제 $105,000 · 오늘 $105,000 · 지갑 위치 5 그대로"
        f"{'' if cold else '(종전 어제 $55,000)'}",
        (day_val(f0) if f0 else None, day_val(f), today_val(f), total(f), eth_rows(f), wl))

for cold in (False, True):
    ledger(upbit={"XRP": 10})
    b = new_builder()
    f0 = None
    if not cold:
        snap({"KRW": (0, 0), "XRP": (10, 0), "SOL": (1000, 0)}, [], age=60)
        f0 = build_on(b)
    snap({"KRW": (500 * 100 * FX, 0), "XRP": (10, 0), "SOL": (0, 500)},
         [dict(order("f1", "ask", 1000, 500, 500 * 100 * FX), market="KRW-SOL")], age=30)
    f = build_on(b)
    sol = [(c9.get("key"), c9.get("qty")) for c9 in (f.get("coins") or []) if c9.get("sym") == "SOL"]
    chk((cold or near(day_val(f0), 100010)) and near(day_val(f), 100010) and near(today_val(f), 100010) and near(total(f), 100010) and not bad_ku(b),
        f"F 실시간 행 SOL 1,000 중 500 매도{' · 관측 없음(첫 빌드)' if cold else ''} = 어제 $100,010(SOL 체결 전 1,000 · 원화 체결 전 0) · 오늘 $100,010"
        f"{'(종전도 $100,010 — 원화 체결 뒤 + 실시간 행 500 이월이 우연히 맞음)' if cold else '(종전 어제 $150,010 — 원화만 체결 뒤)'}",
        (day_val(f0) if f0 else None, day_val(f), today_val(f), total(f), bad_ku(b), sol))
ledger(upbit={"ETH": 100})
snap({"KRW": (0, 0), "ETH": (150, 0), "USDT": (0, 50000)}, [dict(order("g1", "bid", 100, 50, 50000), market="USDT-ETH")], age=30)
b = new_builder()
f = build_on(b)
chk(near(day_val(f), 200000) and near(today_val(f), 200000) and near(total(f), 200000),
    "G USDT 마켓 부분 매수(쿼트 USDT = 실시간 행 · 관측 없음 첫 빌드) = 어제 $200,000(ETH 원장 100 + USDT 체결 전 100,000) · 오늘 $200,000(종전 어제 $150,000)",
    (day_val(f), today_val(f), total(f)))
kit_checks("G", b, f, 200000, 0, ["USDT"])

import ubfill
D9 = Decimal
if not (hasattr(ubfill, "cash_krw") and hasattr(xparts, "ub_pre_fill")):
    chk(False, "U ubfill.cash_krw · xparts.ub_pre_fill 없음(수정 전 코드)")
else:
    m = ubfill.deltas([order("u1", "bid", 10, 5, 5 * KRW1), order("u2", "ask", 10, 5, 6 * KRW1, fee="1000")], {}, 1000)
    chk(m["ETH"]["dq"] == 0 and m["ETH"]["krw"] == D9(str(KRW1)) - 1000 and ubfill.cash_krw(m) == D9(str(KRW1)) - 1000,
        "U 같은 코인 매수 5 · 매도 5(다른 체결액·수수료) = 수량 0 · 원화 몫 +₩1,399,000 그대로(cash_krw)", m)
    bk = {"u3": dict(ubfill.order_fill(order("u3", "bid", 10, 5, 5 * KRW1)), ts=1100)}
    m = ubfill.deltas([order("u3", "bid", 10, 5, 5 * KRW1)], bk, 1000)
    chk(m.get("ETH", {}).get("dq") == 0 and m["ETH"]["krw"] == -5 * D9(str(KRW1)),
        "U 기장 체결량 = 스냅숏 체결량이지만 기장 시각이 스냅숏 뒤 = 수량 0 칸 · 원화 몫 −₩7,000,000(그 잔고 기준 되감기에 아직 없음 — 종전 칸 없음)", m)
    chk(ubfill.cash_krw(None) == 0 and ubfill.cash_krw({}) == 0, "U cash_krw 목록 불신·빈 결과 = 0")
    ub9 = {"ETH": [50.0, 50000.0], "SOL": [500.0, 50000.0]}
    chk(xparts.ub_pre_fill(ub9, [1000, {"ETH": 50.0, "SOL": -500.0, "BTC": 1.0}], 999, 1000) == {"SOL": [1000.0, 100000.0]},
        "U ub_pre_fill: 스냅숏 전 날 = 늘어난 몫 빼기(0 = 없음) · 줄어든 몫 관측 단가로 되돌림 · 관측에 없는 심볼 그대로",
        xparts.ub_pre_fill(ub9, [1000, {"ETH": 50.0, "SOL": -500.0}], 999, 1000))
    chk(xparts.ub_pre_fill(ub9, [1000, {"ETH": 50.0}], 1000, 1000) == ub9 and xparts.ub_pre_fill(ub9, [1000, {"ETH": 50.0}], 999, 999) == ub9
        and xparts.ub_pre_fill(ub9, None, 999, 1000) == ub9 and xparts.ub_pre_fill(ub9, [None, {"ETH": 1}], 0, 1000) == ub9,
        "U ub_pre_fill: 스냅숏 시각 이후 날 · 스냅숏 전 관측 · 재료 없음·형식 이상 = 그대로")
    chk(xparts.ub_pre_fill({"ETH": [80.0, 80000.0]}, [1000, {"ETH": 50.0}], 999, 1000) == {"ETH": [30.0, 30000.0]}, "U ub_pre_fill: 일부만(80 중 50) = 30 · 평가 비례")

for tag, setup, s0, s1, want_y, want_t in (
        ("A", lambda: ledger(upbit={"XRP": 10}), lambda: a_snap(0, 60), lambda: a_snap(50, 30), 100010, 100010),
        ("B", lambda: ledger(upbit={"ETH": 100}), lambda: b_snap(0, 60), lambda: b_snap(50, 30), 200000, 210000)):
    res = {}
    setup()
    s0()
    build_on(new_builder())
    s1()
    b = new_builder()
    f = build_on(b)
    res["새 빌더"] = (day_val(f), today_val(f), bad_ku(b))
    os.remove(os.path.join(S, "daily_cache.json"))
    b = new_builder()
    f = build_on(b)
    res["캐시 삭제"] = (day_val(f), today_val(f), bad_ku(b))
    c9 = dbm.open_db(common.DB_PATH)
    common.hist_late_put(c9, YEND - 3600)
    c9.commit()
    c9.close()
    f = build_on(b)
    res["늦은 행 표식"] = (day_val(f), today_val(f), bad_ku(b))
    setup()
    s1()
    b = new_builder()
    f = build_on(b)
    res["관측 없음(첫 빌드)"] = (day_val(f), today_val(f), bad_ku(b))
    kit_checks(f"E {tag} 관측 없음", b, f, want_y, 100 * KRW1, [], old_x=100000)
    for k9, (y9, t9, bd9) in res.items():
        chk(near(y9, want_y) and near(t9, want_t) and not bd9, f"E {tag} {k9} = 어제 ${want_y:,.0f} · 오늘 ${want_t:,.0f} · 원화 불신 없음", (y9, t9, bd9))

def dpx_load():
    return json.load(open(os.path.join(S, "daily_px.json")))


def dpx_save(d):
    json.dump(d, open(os.path.join(S, "daily_px.json"), "w"))


def y_ub():
    xv9 = (dpx_load().get(YISO) or {}).get("xv") or {}
    return [(xv9.get("p") or {}).get("ub"), (xv9.get("p") or {}).get("ku"), xv9.get("ubv")]


def pin_old(ku_krw, ub_q, ub_usd):
    d9 = dpx_load()
    n9 = 0
    for k9, e9 in d9.items():
        xv9 = e9.get("xv") if isinstance(e9, dict) and len(str(k9)) == 10 else None
        if isinstance(xv9, dict) and isinstance(xv9.get("p"), dict):
            xv9["p"]["ku"] = [ku_krw, "tl"]
            xv9["p"]["ub"] = [{s9: q9 for s9, q9 in ub_q.items()}, "carry"]
            xv9["ubv"] = dict(ub_usd)
            n9 += 1
    dpx_save(d9)
    return n9


ledger(upbit={"XRP": 10})
a_snap(50, 30)
build_on(new_builder())
n_pin = pin_old(50 * KRW1, {"ETH": 50.0}, {"ETH": 50000.0})
b = new_builder()
f = build_on(b)
up = [("이어받은 첫 빌드", day_val(f), today_val(f), (b.daily.get(YISO) or {}).get("val"), y_ub())]
kit_checks("UP1", b, f, 100010, 100 * KRW1, [])
f = build_on(b)
up.append(("다음 빌드", day_val(f), today_val(f), (b.daily.get(YISO) or {}).get("val"), y_ub()))
book("a1", "bid", 100, 100 * KRW1, NOW - 50, fill_ts=time.time() - 15)
snap({"KRW": (0, 0), "XRP": (10, 0), "ETH": (100, 0)}, [], age=10)
f = build_on(b)
up.append(("종결 기장 뒤", day_val(f), today_val(f), (b.daily.get(YISO) or {}).get("val"), y_ub()))
chk(n_pin >= 1 and all(near(v9, 100010) and near(t9, 100010) and near(fz9, 100010) and u9[0] == [{}, "carry"] for _n9, v9, t9, fz9, u9 in up),
    "UP1 수정 전 코드가 체결 뒤로 고정한 지난날(원화 tl 체결 뒤 · ETH 50 이월)을 같은 스냅숏으로 이어받음 = 어제 $100,010 · 동결 값 $100,010 · 고정 이월 ETH 50 → 없음"
    "(체결 전 · 저장) · 다음 빌드·종결 기장 뒤 그대로(종전 어제 $150,010 — 체결 전 원화 + ETH 50)", (n_pin, up))

ledger(upbit={"XRP": 10})
snap({"KRW": (100 * KRW1, 0), "XRP": (10, 0), "ETH": (30, 0)}, [], age=30)
build_on(new_builder())
pin_old(123 * KRW1, {"ETH": 30.0}, {"ETH": 30000.0})
b = new_builder()
f = build_on(b)
u2 = y_ub()
chk(u2[0] == [{"ETH": 30.0}, "carry"] and u2[2] == {"ETH": 30000.0} and near(day_val(f), 130010),
    "UP2 체결 없는 평상시 = 고정 이월 ETH 30 그대로(원화 고정값이 달라 다시 되감겨도 · 미기장 체결 없음 = 손 안 댐) · 어제 $130,010", (u2, day_val(f)))

for tag9, pin_q, want_y in (("체결 전 보유 ETH 30", 30.0, 130010), ("범위 밖 ETH 200", 200.0, 300010)):
    ledger(upbit={"XRP": 10})
    snap({"KRW": (0, 50 * KRW1), "XRP": (10, 0), "ETH": (80, 0)}, [order("up3", "bid", 100, 50, 50 * KRW1)], age=30)
    build_on(new_builder())
    pin_old(50 * KRW1, {"ETH": pin_q}, {"ETH": pin_q * 1000})
    b = new_builder()
    f = build_on(b)
    u3 = y_ub()
    chk(u3[0] == [{"ETH": pin_q}, "carry"] and near(day_val(f), want_y),
        f"UP3 체결 중 업그레이드 · {tag9} 고정 이월 = 그대로(체결 전(30)~체결 뒤(80) 사이가 아니거나 이미 체결 전 값) · 어제 ${want_y:,.0f}", (u3, day_val(f)))
ledger(upbit={"XRP": 10})
a_snap(50, 30)
build_on(new_builder())
book("a1", "bid", 100, 100 * KRW1, NOW - 50, fill_ts=time.time() - 15)
snap({"KRW": (0, 0), "XRP": (10, 0), "ETH": (100, 0)}, [], age=10)
pin_old(77 * KRW1, {"ETH": 40.0}, {"ETH": 40000.0})
b = new_builder()
build_on(b)
u4 = y_ub()
chk(u4[0] == [{"ETH": 40.0}, "carry"] and u4[2] == {"ETH": 40000.0}, "UP4 기장 완료 뒤(미기장 체결 없음) = 고정 이월 그대로(손 안 댐)", u4)
if hasattr(xparts, "_ub_pin_fill"):
    src9 = {"now": {"ts": 2000.0, "ku": 0.0, "ub": {"ETH": [50.0, 50000.0]}, "ubf": [1000, {"ETH": 50.0}]}, "base": {"ku": [0.0, 1000.0]},
            "tl": {"ku": [(1000, -70000000.0)]}, "first": {}}
    pin9 = {"ku": [0.0, "tl"], "ub": [{"ETH": [50.0, 50000.0]}, "carry"]}
    chk(xparts.resolve(500, src9, pin9)["ub"] == [{}, "carry"], "U ub701: 고정 이월(체결 뒤 50) + 원화가 이번에 체결 전으로 = 그 심볼 체결 전(0)")
    chk(xparts.resolve(500, src9, dict(pin9, ku=[70000000.0, "tl"]))["ub"] == [{"ETH": [50.0, 50000.0]}, "carry"],
        "U ub701: 고정 원화와 이번 되감기 값이 같음(새 코드가 이미 맞춘 날) = 그대로")
    chk(xparts.resolve(500, src9, dict(pin9, ku=[0.0, "snap"]))["ub"] == [{"ETH": [50.0, 50000.0]}, "carry"], "U ub701: 원화가 그날 관측(snap) = 그대로")
    chk(xparts.resolve(1500, src9, pin9)["ub"] == [{"ETH": [50.0, 50000.0]}, "carry"], "U ub701: 스냅숏 시각 뒤 날 = 그대로")
    chk(xparts.resolve(500, dict(src9, now=dict(src9["now"], ubf=None)), pin9)["ub"] == [{"ETH": [50.0, 50000.0]}, "carry"], "U ub701: 미기장 체결 없음 = 그대로")
    chk(xparts.resolve(500, src9, dict(pin9, ub=[{"ETH": [50.0, 50000.0]}, "snap"]))["ub"] == [{"ETH": [50.0, 50000.0]}, "snap"], "U ub701: 관측(snap) ub = 그대로")
    src7 = {"now": {"ts": 200000.0, "ub": {"ETH": [80.0, 80000.0]}, "ubf": [199970, {"ETH": 50.0}]}, "base": {"ku": [70000000.0, 199970.0]},
            "tl": {"ku": [(199970, -70000000.0)]}, "obs": {"old": {"end": 13600.0, "ub": {"ETH": [10.0, 10000.0]}}}, "first": {}}
    r7 = xparts.resolve(100000, src7, {"ku": [70000000.0, "tl"], "ub": [{"ETH": [30.0, 30000.0]}, "carry"]})
    chk(r7["ub"] == [{"ETH": [30.0, 30000.0]}, "carry"] and r7["ku"] == [140000000.0, "tl"],
        "U ub707: 옛 관측(ETH 10)이 있어도 체결 전 수량(30)으로 고정된 이월은 그대로($130,000 유지 · 종전 10 으로 덮어 $110,000)", r7)
    r7 = xparts.resolve(100000, src7, {"ku": [70000000.0, "tl"], "ub": [{"ETH": [80.0, 80000.0]}, "carry"]})
    chk(r7["ub"] == [{"ETH": [30.0, 30000.0]}, "carry"],
        "U ub707: 체결 뒤 수량(80)으로 고정된 이월 = 고정 수량 − 체결 몫(30 · 평가 단가 유지) — 옛 관측(10)을 쓰지 않음", r7)
    r7 = xparts.resolve(100000, src7, {"ku": [70000000.0, "tl"], "ub": [{"ETH": [60.0, 60000.0]}, "carry"]})
    chk(r7["ub"] == [{"ETH": [60.0, 60000.0]}, "carry"], "U ub707: 체결 전·뒤 어느 쪽도 아닌 고정 이월(60) = 그대로", r7)
    src8 = dict(src7, now=dict(src7["now"], ub={"SOL": [500.0, 50000.0]}, ubf=[199970, {"SOL": -500.0}]), tl={"ku": [(199970, 70000000.0)]})
    r8 = xparts.resolve(100000, src8, {"ku": [70000000.0, "tl"], "ub": [{"SOL": [500.0, 50000.0]}, "carry"]})
    chk(r8["ub"] == [{"SOL": [1000.0, 100000.0]}, "carry"], "U ub707: 매도 — 체결 뒤(500)로 고정된 이월 = 500 − (−500) = 1,000", r8)
else:
    chk(False, "U ub701: xparts._ub_pin_fill 없음(수정 전 코드)")

def move_live_to_yesterday(b9, sec_before_end):
    lv9 = dict(b9.daily.get("_live") or {})
    t9 = YEND + 1 - sec_before_end
    lv9["date"], lv9["ts"] = YISO, t9
    if isinstance(lv9.get("xv"), dict):
        lv9["xv"] = dict(lv9["xv"], ts=int(t9), rt=dict(lv9["xv"].get("rt") or {}, upbit=int(t9)))
    dc9 = json.load(open(os.path.join(S, "daily_cache.json")))
    dc9.pop(YISO, None)
    dc9["_live"] = dc9["_live_ok"] = lv9
    json.dump(dc9, open(os.path.join(S, "daily_cache.json"), "w"))
    d9 = dpx_load()
    d9.pop(YISO, None)
    dpx_save(d9)
    return lv9


def late_xrp(ts9, q9=1000):
    c9 = dbm.open_db(common.DB_PATH)
    _post(c9, "latexrp", ts9, _ex_asset(c9, "XRP"), "exchange:upbit", q9, 8, q9 * PX["XRP"], "acq")
    _pos_add(c9, _grp(c9, "XRP"), "exchange:upbit", q9)
    c9.commit()
    c9.close()


IT_ACC = {"KRW": (0, 50 * KRW1), "ETH": (150, 0)}
ledger(upbit={"ETH": 100})
snap(IT_ACC, [order("it1", "bid", 100, 50, 50 * KRW1)], age=40)
b = new_builder()
build_on(b)
lv1 = move_live_to_yesterday(b, 40)
late_xrp(YEND - 19)
snap(IT_ACC, [order("it1", "bid", 100, 50, 50 * KRW1)], age=20)
b = new_builder()
f = build_on(b)
it1 = (day_val(f), (b.daily.get(YISO) or {}).get("val"), (b.daily.get(YISO) or {}).get("src"), today_val(f))
kit_checks("IT1", b, f, 201000, 100 * KRW1, [])
chk(near(it1[0], 201000) and near(it1[1], 201000) and it1[2] == "calc" and near(it1[3], 201000) and (lv1.get("xv") or {}).get("ufc"),
    "IT1 거절된 마감 스냅숏(체결 뒤 원화 $50,000 관측) + 코인 되감기(새 스냅숏 시각) = 어제 $201,000 · 동결 $201,000(종전 $151,000 — 다음 날 가짜 +$50,000) · 오늘 $201,000",
    (it1, (lv1.get("xv") or {}).get("ufc")))
book("it1", "bid", 100, 100 * KRW1, NOW - 50, fill_ts=time.time() - 15)
snap({"KRW": (0, 0), "ETH": (200, 0), "XRP": (1000, 0)}, [], age=10)
f = build_on(b)
chk(near(day_val(f), 201000) and near(today_val(f), 201000), "IT1 그 뒤 종결 기장(오늘) = 어제 $201,000 그대로 · 오늘 $201,000", (day_val(f), today_val(f)))

ledger(upbit={"ETH": 100})
snap(IT_ACC, [order("it2", "bid", 100, 50, 50 * KRW1)], age=40)
b = new_builder()
build_on(b)
move_live_to_yesterday(b, 40)
snap(IT_ACC, [order("it2", "bid", 100, 50, 50 * KRW1)], age=20)
b = new_builder()
f = build_on(b)
it2 = [("받아들인 마감", day_val(f), (b.daily.get(YISO) or {}).get("src"))]
dc = json.load(open(os.path.join(S, "daily_cache.json")))
for k9 in [k9 for k9 in dc if not str(k9).startswith("_live")]:
    dc.pop(k9)
dc.pop("_live_ok", None)
json.dump(dc, open(os.path.join(S, "daily_cache.json"), "w"))
b = new_builder()
f = build_on(b)
it2.append(("무효화 뒤 다시", day_val(f), (b.daily.get(YISO) or {}).get("src")))
f = build_on(b)
it2.append(("다음 빌드", day_val(f), (b.daily.get(YISO) or {}).get("src")))
chk(all(near(v9, 200000) for _n9, v9, _s9 in it2), "IT2 받아들여 동결된 체결 뒤 마감 → 무효화 뒤 고정 구성요소로 다시 계산 = 어제 $200,000 그대로(종전 $150,000)", it2)

def book_cancel(uu, vol, exe, funds, created_ts, fill_ts):
    c9 = dbm.open_db(common.DB_PATH)
    pl9 = {"uuid": uu, "market": "KRW-ETH", "side": "bid", "state": "cancel", "ord_type": "limit", "price": "1400000", "volume": str(vol),
           "executed_volume": str(exe), "executed_funds": str(funds), "paid_fee": "0", "created_at": _dt.fromtimestamp(created_ts, web.KST).isoformat(),
           "trades": [{"created_at": _dt.fromtimestamp(fill_ts, web.KST).isoformat(), "volume": str(exe), "funds": str(funds)}]}
    c9.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('upbit','order',?,1,?,?)", (uu, json.dumps(pl9), int(time.time())))
    _post(c9, uu, int(fill_ts), _ex_asset(c9, "ETH"), "exchange:upbit", exe, 8, funds / FX, "acq")
    _pos_add(c9, _grp(c9, "ETH"), "exchange:upbit", exe)
    c9.commit()
    c9.close()


def drop_day_cache(ck9):
    dc9 = json.load(open(os.path.join(S, "daily_cache.json")))
    dc9.pop(ck9, None)
    json.dump(dc9, open(os.path.join(S, "daily_cache.json"), "w"))


ledger(upbit={"ETH": 100})
snap(IT_ACC, [order("it4", "bid", 100, 50, 50 * KRW1)], age=40)
b = new_builder()
build_on(b)
move_live_to_yesterday(b, 40)
late_xrp(YEND - 19)
snap(IT_ACC, [order("it4", "bid", 100, 50, 50 * KRW1)], age=20)
b = new_builder()
f = build_on(b)
it4 = [("첫 재계산", day_val(f), ((dpx_load().get(YISO) or {}).get("xv") or {}).get("ufc"))]
book_cancel("it4", 100, 50, 50 * KRW1, NOW - 50, YEND - 6 * 3600)
snap({"KRW": (50 * KRW1, 0), "ETH": (150, 0), "XRP": (1000, 0)}, [], age=10)
drop_day_cache(YISO)
b = new_builder()
f = build_on(b)
it4.append(("취소 기장(어제 18:00) 뒤 다시", day_val(f), ((dpx_load().get(YISO) or {}).get("xv") or {}).get("ufc")))
drop_day_cache(YISO)
b = new_builder()
f = build_on(b)
it4.append(("한 번 더", day_val(f), None))
chk(all(near(v9, 201000) for _n9, v9, _u9 in it4) and near(today_val(f), 201000),
    "IT4 거절된 마감 첫 재계산 $201,000 → 다음 날 잔여 취소(부분 체결이 어제 18:00 으로 기장) → 다시 계산 = $201,000 · 반복해도 같음(종전 $251,000)", (it4, today_val(f)))

ledger(upbit={"ETH": 100})
snap(IT_ACC, [order("it5", "bid", 100, 50, 50 * KRW1)], age=40)
b = new_builder()
build_on(b)
move_live_to_yesterday(b, 40)
late_xrp(YEND - 19)
_real_time = time.time
time.time = lambda: YEND + 31.0
try:
    snap(IT_ACC, [order("it5", "bid", 100, 50, 50 * KRW1)], age=40)
    b = new_builder()
    f = build_on(b)
    it5 = [("00:00:31 첫 재계산(맞춤 0)", day_val(f), ((dpx_load().get(YISO) or {}).get("xv") or {}).get("ufc"))]
finally:
    time.time = _real_time
snap(IT_ACC, [order("it5", "bid", 100, 50, 50 * KRW1)], age=20)
drop_day_cache(YISO)
b = new_builder()
f = build_on(b)
it5.append(("오늘 잔고로 갱신 뒤 다시", day_val(f), ((dpx_load().get(YISO) or {}).get("xv") or {}).get("ufc")))
chk(all(near(v9, 201000) for _n9, v9, _u9 in it5), "IT5 첫 재계산 맞춤 0(그 잔고 스냅숏이 그날 마감 전) → 오늘 잔고로 갱신 → 다시 계산 = $201,000(종전 $151,000)", it5)

ledger(upbit={"ETH": 100})
snap(IT_ACC, [order("it6", "bid", 100, 50, 50 * KRW1)], age=40)
b = new_builder()
build_on(b)
lv6 = move_live_to_yesterday(b, 40)
dc = json.load(open(os.path.join(S, "daily_cache.json")))
dc["_live"] = dict(dc["_live"], defer=True)
dc.pop("_live_ok", None)
json.dump(dc, open(os.path.join(S, "daily_cache.json"), "w"))
snap(IT_ACC, [order("it6", "bid", 100, 50, 50 * KRW1)], age=20)
b = new_builder()
f = build_on(b)
xv6 = (dpx_load().get(YISO) or {}).get("xv") or {}
it6 = [("부분 동결", day_val(f), (b.daily.get(YISO) or {}).get("src"), (xv6.get("p") or {}).get("ku"), xv6.get("ku0"), bool(xv6.get("ufc")))]
dc = json.load(open(os.path.join(S, "daily_cache.json")))
dc.pop(YISO, None)
dc["_live_ok"] = dict(lv6, defer=False)
json.dump(dc, open(os.path.join(S, "daily_cache.json"), "w"))
b = new_builder()
f = build_on(b)
xv6 = (dpx_load().get(YISO) or {}).get("xv") or {}
it6.append(("받아들인 마감으로 다시", day_val(f), (b.daily.get(YISO) or {}).get("src"), (xv6.get("p") or {}).get("ku"), xv6.get("ku0"), bool(xv6.get("ufc"))))
chk(near(it6[0][1], 200000) and it6[0][2] == "partial" and near(it6[0][4], 50 * KRW1) and it6[0][5] and near((it6[0][3] or [0])[0], 100 * KRW1)
    and near(it6[1][1], 200000) and it6[1][2] == "live" and near((it6[1][3] or [0])[0], 50 * KRW1),
    "IT6 유예 스냅숏 부분 동결 = $200,000(원화 체결 전 · 고정값에 원본 관측 ₩70,000,000·주문별 몫 보관) → 같은 날 받아들인 마감으로 다시 동결 = 원본 관측 원화 $200,000", it6)

ledger(upbit={"ETH": 100})
snap({"KRW": (100 * KRW1, 0), "ETH": (100, 0)}, [], age=40)
b = new_builder()
build_on(b)
lv3 = move_live_to_yesterday(b, 40)
late_xrp(YEND - 19)
snap({"KRW": (100 * KRW1, 0), "ETH": (100, 0)}, [], age=20)
b = new_builder()
f = build_on(b)
chk(near(day_val(f), 201000) and not (lv3.get("xv") or {}).get("ufc"), "IT3 미기장 체결 없는 거절 = 어제 $201,000(종전 그대로 · 관측에 체결 원화 몫 없음)", (day_val(f), (lv3.get("xv") or {}).get("ufc")))

ledger(upbit={"ETH": 100})
b = new_builder()
snap({"KRW": (0, 50 * KRW1), "ETH": (150, 0)}, [order("s8", "bid", 100, 50, 50 * KRW1)], age=700)
f = build_on(b)
lv = b.daily.get("_live") or {}
chk(lv.get("defer") is True and (b.__dict__.get("_ub_fill_info") or {}).get("why") == "stale",
    "S8 낡은 스냅숏(700초) + 미기장 체결 = 그 빌드 마감 스냅숏(_live) 유예 — 마감 재료로 안 씀(체결 전 코인 + 체결 뒤 원화로 굳지 않게)",
    (lv.get("defer"), b.__dict__.get("_ub_fill_info")))
ledger(upbit={"ETH": 100})
b = new_builder()
seq = []
for nm, acc, oo, age in (("S0", {"KRW": (100 * KRW1, 0), "ETH": (100, 0)}, [], 1500),
                         ("낡음", {"KRW": (0, 50 * KRW1), "ETH": (150, 0)}, [order("s8b", "bid", 100, 50, 50 * KRW1)], 700),
                         ("신선", {"KRW": (0, 50 * KRW1), "ETH": (150, 0)}, [order("s8b", "bid", 100, 50, 50 * KRW1)], 30)):
    snap(acc, oo, age=age)
    f = build_on(b)
    seq.append((nm, day_val(f), today_val(f), bad_ku(b), (b.daily.get("_live") or {}).get("xv", {}).get("ufk")))
chk(all(near(v9, 200000) and not bd9 for _n9, v9, _t9, bd9, _u9 in seq) and near(seq[-1][2], 200000) and seq[1][4] == 1,
    "S8 같은 빌더 체결 전(낡음 · 25분) → 낡은 스냅숏 + 체결(12분 · 원화 관측에 ufk · 곡선 원화 되감기에 체결 원화 몫) → 신선 = 어제 늘 $200,000 · "
    "원화 불신 없음(종전 낡은 동안 어제 $150,000 · 신선 빌드에서 낡은 관측과 충돌 → 지난날 이월) — 낡은 동안 오늘 $150,000 은 감수(마감 유예)", seq)
ledger(upbit={"ETH": 100})
snap({"KRW": (100 * KRW1, 0), "ETH": (100, 0)}, [], age=700)
b = new_builder()
f = build_on(b)
chk(not (b.daily.get("_live") or {}).get("defer"), "S8 낡은 스냅숏이라도 미기장 체결이 없으면 유예 안 함(종전)", (b.daily.get("_live") or {}).get("defer"))
snap({"KRW": (0, 50 * KRW1), "ETH": (150, 0)}, [order("s8", "bid", 100, 50, 50 * KRW1)], age=30)
b = new_builder()
f = build_on(b)
chk(not (b.daily.get("_live") or {}).get("defer"), "S8 신선한 스냅숏 + 미기장 체결 = 유예 안 함(같은 스냅숏 보정 — 15차 그대로)", (b.daily.get("_live") or {}).get("defer"))

T.finish()
