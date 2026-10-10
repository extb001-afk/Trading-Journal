#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import time
from decimal import Decimal

import common

CFG = os.path.join(os.environ["TJ_BASE"], "config.json")
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(CFG, "w"))
import db as dbm
import netpace
import web

try:
    import ubfill
except ImportError:
    ubfill = None

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
PX = {"ETH": 1000.0, "XRP": 1.0, "BTC": 50000.0, "SOL": 100.0, "USDT": 1.0}
WAL = "0x" + "c3" * 20
web.pricing.PxCache.candle_usd = lambda self, sym, ms: PX.get(str(sym).upper())


def reset_ledger(holds, wallet_eth=None, booked=()):
    for sfx in ("", "-wal", "-shm"):
        if os.path.exists(common.DB_PATH + sfx):
            os.remove(common.DB_PATH + sfx)
    for fn in ("daily_cache.json", "daily_px.json"):
        if os.path.exists(os.path.join(S, fn)):
            os.remove(os.path.join(S, fn))
    c = dbm.open_db(common.DB_PATH)
    gid, aid = {}, {}
    syms = set(holds) | ({"ETH"} if (wallet_eth or booked) else set())
    for sym in sorted(syms):
        c.execute("INSERT INTO asset_groups (name) VALUES (?)", (sym,))
        gid[sym] = c.execute("SELECT group_id FROM asset_groups WHERE name=?", (sym,)).fetchone()[0]
        c.execute("INSERT INTO assets (kind, chain, address, symbol, decimals, confirmed, group_id) VALUES ('exchange_currency',NULL,?,?,8,1,?)",
                  (f"upbit:{sym}", sym, gid[sym]))
        aid[sym] = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    pos = {}
    for sym, q in sorted(holds.items()):
        c.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind,"
                  " event, classifier_ver) VALUES ('exchange','upbit:trade',?,0,?,?,'exchange:upbit',?,?,NULL,'acq','EXF_BUY',4)",
                  (f"init{sym}", NOW - 20 * DAY, aid[sym], str(int(Decimal(str(q)) * 10 ** 8)), repr(float(q) * PX[sym])))
        pos[(gid[sym], "exchange:upbit")] = Decimal(str(q))
    if wallet_eth:
        c.execute("INSERT INTO assets (kind, chain, address, symbol, decimals, confirmed, group_id) VALUES ('native','eth',NULL,'ETH',18,1,?)", (gid["ETH"],))
        an = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind,"
                  " event, classifier_ver) VALUES ('chain','eth','0xw1',0,?,?,?,?,?,NULL,'acq','SWAP',4)",
                  (NOW - 19 * DAY, an, f"wallet:eth:{WAL}", str(int(Decimal(str(wallet_eth)) * 10 ** 18)), repr(float(wallet_eth) * 1000)))
        pos[(gid["ETH"], f"wallet:eth:{WAL}")] = Decimal(str(wallet_eth))
    for uu, st, vol, funds in booked:
        c.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('upbit','order',?,1,?,?)",
                  (uu, json.dumps({"uuid": uu, "market": "KRW-ETH", "side": "bid", "state": st, "ord_type": "limit", "price": "1400000",
                                   "volume": "100", "executed_volume": str(vol), "executed_funds": str(funds), "paid_fee": "0",
                                   "created_at": ""}), NOW - 60))
        c.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind,"
                  " event, classifier_ver) VALUES ('exchange','upbit:fill',?,0,?,?,'exchange:upbit',?,?,NULL,'acq','EXF_BUY',4)",
                  (uu, NOW - 3600, aid["ETH"], str(int(Decimal(str(vol)) * 10 ** 8)), repr(funds / FX)))
        pos[(gid["ETH"], "exchange:upbit")] = pos.get((gid["ETH"], "exchange:upbit"), Decimal(0)) + Decimal(str(vol))
    for (g9, loc9), q9 in pos.items():
        c.execute("INSERT INTO positions (group_id, location, qty_norm) VALUES (?,?,?)", (g9, loc9, str(q9)))
    c.commit()
    c.close()
    return gid


def snap(accounts, orders=(), age=0, oo=True):
    d = {"ts": int(time.time()) - age,
         "accounts": [{"currency": k, "balance": str(v[0]), "locked": str(v[1])} for k, v in accounts.items()]}
    if oo:
        d["open_orders"] = list(orders)
    common.atomic_write_json(UP, d)


def order(uu, market, side, vol, exe, funds, fee="0"):
    return {"uuid": uu, "market": market, "side": side, "state": "wait", "ord_type": "limit", "volume": str(vol),
            "remaining_volume": str(Decimal(str(vol)) - Decimal(str(exe))), "executed_volume": str(exe),
            "executed_funds": str(funds), "paid_fee": str(fee), "created_at": ""}


json.dump({"usd": PX, "usd_ts": {k: NOW for k in PX}, "rate": FX, "updated": NOW, "dex_usd": {}, "dex_ts": {}, "dex_res": {}, "dex_res_ts": {},
           "fx_basis": FX, "ex_usd": {}, "ex_ts": {}}, open(web.SPOT_PATH, "w"))
common.atomic_write_json(web.PREFS_PATH, {"plans": {}, "ignored": []})
open(os.path.join(S, "backfill_done"), "w").write("1")


def build(px=None):
    b = web.StateBuilder()
    b.skip_gen_check = True
    t = int(time.time())
    for k, v in (px or PX).items():
        if v:
            b.spot.ex_usd[f"upbit:{k}"] = v
            b.spot.ex_ts[f"upbit:{k}"] = t
        else:
            b.spot.ex_usd.pop(f"upbit:{k}", None)
            b.spot.usd.pop(k, None)
    conn = dbm.open_db(common.DB_PATH, readonly=True)
    try:
        f = b._build(conn)["fields"]
    finally:
        conn.close()
    return b, f


def total(f):
    return (sum(float(c9["qty"]) * float(c9.get("price") or 0) for c9 in f.get("coins") or [])
            + sum(float(s9["qty"]) * float(s9.get("price") or 0) for s9 in f.get("stables") or [])
            + sum(float(x9["krw"]) for x9 in f.get("fiats") or []) / FX)


def rows(f, sym):
    return [c9 for c9 in (f.get("coins") or []) + (f.get("stables") or []) if c9.get("sym") == sym]


def today_val(f):
    d9 = f.get("dailySeries") or []
    return float(d9[-1]["val"]) if d9 else None


def near(a, b, tol=0.01):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


KRW1 = 1000 * FX

G = reset_ledger({"ETH": 100})
snap({"KRW": (0, 50 * KRW1), "ETH": (150, 0)}, [order("u1", "KRW-ETH", "bid", 100, 50, 50 * KRW1)])
b, f = build()
e = rows(f, "ETH")
chk(len(e) == 1 and near(e[0]["qty"], 150), "S1 부분 매수: 그 줄 수량 = 원장 100 + 미기장 체결 50 = 150(실잔고와 같음)", [(r.get("key"), r.get("qty")) for r in e])
chk(near(total(f), 200000), "S1 부분 매수: 총자산 $200,000 보존(종전 $150,000 = 체결 금액만큼 과소)", total(f))
lc = [l9 for l9 in (e[0].get("locs") if e else []) if l9.get("w") == "업비트"]
chk(len(lc) == 1 and near(lc[0]["qty"], 150) and "미체결 주문 체결분" in lc[0].get("sub", ""), "S1 위치 = 업비트 150 · '미체결 주문 체결분 포함' 문구", lc)
chk(near(today_val(f), 200000), "S1 오늘 일별 값 = 화면 총자산(같은 정의)", today_val(f))
lv = (b.daily.get("_live") or {}).get("g") or {}
chk(near(lv.get(str(G["ETH"])), 150000), "S1 마감 스냅숏(_live) 그룹 값 = 150 × $1,000(자정에 이 값으로 동결)", lv)
chk((b.__dict__.get("_ub_fill_info") or {}).get("why") == "ok" and (b.__dict__.get("_ub_fill_info") or {}).get("n") == 1,
    "S1 보정 정보(why ok · 주문 1)", b.__dict__.get("_ub_fill_info"))

reset_ledger({"ETH": 100})
snap({"KRW": (150 * KRW1, 0), "ETH": (0, 50)}, [order("u2", "KRW-ETH", "ask", 100, 50, 50 * KRW1)])
b, f = build()
e = rows(f, "ETH")
chk(len(e) == 1 and near(e[0]["qty"], 50), "S2 부분 매도: 수량 = 100 − 50 = 50", [(r.get("key"), r.get("qty")) for r in e])
chk(near(total(f), 200000), "S2 부분 매도: 총자산 $200,000 보존(종전 $250,000 = 과대)", total(f))
chk(near(today_val(f), 200000), "S2 오늘 일별 값 = 화면 총자산", today_val(f))

reset_ledger({"XRP": 10})
snap({"KRW": (0, 50 * KRW1), "ETH": (50, 0)}, [order("u3", "KRW-ETH", "bid", 100, 50, 50 * KRW1)])
b, f = build()
e = rows(f, "ETH")
chk(len(e) == 1 and str(e[0].get("key")) == "ub:ETH" and near(e[0]["qty"], 50), "S3 최초 매수(원장에 없음) = 실시간 잔고 행 하나(50)만 · 중복 없음", [(r.get("key"), r.get("qty")) for r in e])
chk(near(total(f), 50000 + 50000 + 10), "S3 총자산 = 실잔고(ETH 50 + 원화 $50,000 + XRP $10)", total(f))
snap({"KRW": (0, 100 * KRW1)}, [order("u3b", "KRW-ETH", "bid", 100, 0, 0)])
b, f = build()
chk(not rows(f, "ETH") and near(total(f), 100000 + 10), "S3b 체결 0(잠금만) = 총자산 그대로 · ETH 줄 없음", (total(f), rows(f, "ETH")))
reset_ledger({"ETH": 100})
snap({"KRW": (0, 100 * KRW1), "ETH": (100, 0)}, [order("u3c", "KRW-ETH", "bid", 100, 0, 0)])
b, f = build()
e = rows(f, "ETH")
chk(len(e) == 1 and near(e[0]["qty"], 100) and near(total(f), 200000), "S3b 원장 보유 + 체결 0 주문 = 수량 그대로 · 총자산 그대로", (total(f), [(r.get("key"), r.get("qty")) for r in e]))

reset_ledger({"ETH": 100})
seq = []
for exe in (10, 30, 50, 50):
    snap({"KRW": (0, (100 - exe) * KRW1), "ETH": (100 + exe, 0)}, [order("u4", "KRW-ETH", "bid", 100, exe, exe * KRW1)])
    b, f = build()
    e = rows(f, "ETH")
    seq.append((exe, round(float(e[0]["qty"]), 8) if e else None, round(total(f), 2)))
chk([s9[1] for s9 in seq] == [110.0, 130.0, 150.0, 150.0], "S4 누적 체결 10 → 30 → 50 → 같은 스냅숏 다시 = 110 · 130 · 150 · 150(한 번씩만 · 재조회 동일)", seq)
chk(all(near(s9[2], 200000) for s9 in seq), "S4 매 단계 총자산 $200,000", seq)

tot5 = []
reset_ledger({"ETH": 100})
snap({"KRW": (0, 50 * KRW1), "ETH": (150, 0)}, [order("u5", "KRW-ETH", "bid", 100, 50, 50 * KRW1)])
b, f = build()
tot5.append(("열린 50", round(total(f), 2), round(float(rows(f, "ETH")[0]["qty"]), 8)))
reset_ledger({"ETH": 100}, booked=[("u5", "done", 100, 100 * KRW1)])
b, f = build()
e = rows(f, "ETH")
tot5.append(("기장 먼저 · 옛 스냅숏", round(total(f), 2), round(float(e[0]["qty"]), 8) if e else None))
chk(e and near(e[0]["qty"], 150), "S5 원장이 먼저 종결 기장(200) · 스냅숏은 열린 주문 50 = 원장을 그 스냅숏 시점(150)으로 — 이중 계상 없음(종전 200 · 단순 가산 250)",
    [(r.get("key"), r.get("qty")) for r in e])
snap({"KRW": (0, 0), "ETH": (200, 0)}, [])
b, f = build()
e = rows(f, "ETH")
tot5.append(("새 스냅숏(목록에서 사라짐)", round(total(f), 2), round(float(e[0]["qty"]), 8) if e else None))
chk(e and near(e[0]["qty"], 200) and "미체결" not in json.dumps(e[0].get("locs"), ensure_ascii=False), "S5 다음 스냅숏(주문 없음) = 원장 200 그대로 · 보정 문구 없음", e)
chk(all(near(t9[1], 200000) for t9 in tot5), "S5 전환 내내 총자산 $200,000(불연속 없음)", tot5)
reset_ledger({"ETH": 100}, booked=[("u5c", "cancel", 50, 50 * KRW1)])
snap({"KRW": (0, 50 * KRW1), "ETH": (150, 0)}, [order("u5c", "KRW-ETH", "bid", 100, 50, 50 * KRW1)])
b, f = build()
e = rows(f, "ETH")
chk(e and near(e[0]["qty"], 150) and near(total(f), 200000), "S5 취소(부분 50) 기장 · 스냅숏은 아직 열린 주문 50 = 보정 0 · 150 · $200,000", (total(f), [(r.get("key"), r.get("qty")) for r in e]))

reset_ledger({"ETH": 100, "XRP": 1000, "BTC": 1, "SOL": 10})
o6 = [order("u6a", "KRW-ETH", "bid", 50, 10, 10 * KRW1, fee="7000"),
      order("u6b", "KRW-ETH", "bid", 50, 20, 20 * KRW1, fee="14000"),
      order("u6c", "BTC-XRP", "ask", 500, 100, "0.002", fee="0.000001"),
      order("u6d", "USDT-SOL", "bid", 5, 2, "200", fee="0.1")]
krw6 = 100 * KRW1 - 30 * KRW1 - 21000
real6 = {"ETH": 130, "XRP": 900, "BTC": Decimal("1") + Decimal("0.002") - Decimal("0.000001"), "SOL": 12, "USDT": Decimal("300") - Decimal("200.1")}
snap({"KRW": (krw6 - 40 * KRW1, 40 * KRW1), "ETH": (130, 0), "XRP": (500, 400), "BTC": (str(real6["BTC"]), 0), "SOL": (12, 0),
      "USDT": (str(real6["USDT"] - Decimal("300.3")), "300.3")}, o6)
b, f = build()
got6 = {s9: round(sum(float(r9["qty"]) for r9 in rows(f, s9)), 8) for s9 in real6}
chk(got6 == {"ETH": 130.0, "XRP": 900.0, "BTC": 1.001999, "SOL": 12.0, "USDT": 99.9}, "S6 같은 코인 2건 합(+30) · BTC 마켓 매도 = XRP −100 · BTC +(0.002 − 수수료 0.000001) · "
    "USDT 마켓 = SOL +2 · USDT 는 실시간 잔고 행 그대로", got6)
want6 = sum(float(real6[s9]) * PX[s9] for s9 in real6) + krw6 / FX
chk(near(total(f), want6), "S6 총자산 = 실잔고 합(수수료 = 쿼트 통화)", (total(f), want6))
us6 = rows(f, "USDT")
chk(len(us6) == 1 and str(us6[0].get("key")) == "ub:USDT", "S6 실시간 잔고 행(쿼트 USDT)에 보정이 번지지 않음", us6)

reset_ledger({"ETH": 100}, wallet_eth=5)
snap({"KRW": (0, 50 * KRW1), "ETH": (150, 0)}, [order("u7", "KRW-ETH", "bid", 100, 50, 50 * KRW1)])
b, f = build()
e = rows(f, "ETH")
lw = {(l9.get("w"), round(float(l9["qty"]), 8)) for l9 in (e[0].get("locs") if e else [])}
chk(e and near(e[0]["qty"], 155) and any(q9 == 5.0 for _w, q9 in lw) and ("업비트", 150.0) in lw, "S7 지갑 5 그대로 · 업비트 위치만 150", lw)
chk(near(total(f), 205000), "S7 총자산 = 업비트 150 + 지갑 5 + 원화 $50,000", total(f))
reset_ledger({"XRP": 10}, wallet_eth=5)
snap({"KRW": (0, 50 * KRW1), "ETH": (50, 0)}, [order("u7b", "KRW-ETH", "bid", 100, 50, 50 * KRW1)])
b, f = build()
gq = [round(float(r9["qty"]), 8) for r9 in rows(f, "ETH") if str(r9.get("key", "")).startswith("g")]
uq = [round(float(r9["qty"]), 8) for r9 in rows(f, "ETH") if str(r9.get("key", "")).startswith("ub:")]
chk(gq == [5.0] and uq == [50.0] and near(total(f), 5000 + 50000 + 50000 + 10), "S7b 업비트 원장 위치 없음 = 지갑 줄(5)에 안 번짐 · 실시간 행 50", (gq, uq, total(f)))

reset_ledger({"ETH": 100})
snap({"KRW": (0, 50 * KRW1), "ETH": (150, 0)}, [order("u8", "KRW-ETH", "bid", 100, 50, 50 * KRW1)], age=700)
b, f = build()
fu = [x9 for x9 in f.get("fiats") or [] if x9["ex"] == "업비트"]
e = rows(f, "ETH")
chk(len(fu) == 1 and fu[0].get("stale") is True and "업비트 잔고" in fu[0]["note"] and near(fu[0]["krw"], 50 * KRW1),
    "S8 신선도(600초) 넘은 스냅숏 = 원화 마지막 값 유지 + 낡음 표시(종전: 통째로 빠짐)", fu)
chk(e and near(e[0]["qty"], 100) and (b.__dict__.get("_ub_fill_info") or {}).get("why") == "stale",
    "S8 낡은 스냅숏으로는 체결분 보정 안 함(코덱스 ub601 HIGH2 — 마감 후보에 낡은 보정이 굳지 않게 · 업비트 실시간 코인 행과 같은 신선도 규칙)",
    (b.__dict__.get("_ub_fill_info"), [(r.get("key"), r.get("qty")) for r in e]))
xv8 = ((b.daily.get("_live") or {}).get("xv") or {}).get("p") or {}
chk((xv8.get("ku") or [None, None])[1] == "carry", "S8 마감 구성요소 업비트 원화 출처 = carry(낡은 마지막 값 — 확정 관측으로 안 굳음)", xv8)
chk(f.get("upbitConnected") is False, "S8 연결 표시 = 신선도 기준(낡으면 연결됨 아님)", f.get("upbitConnected"))
snap({"KRW": (0, 50 * KRW1), "ETH": (150, 0)}, [order("u8", "KRW-ETH", "bid", 100, 50, 50 * KRW1)], age=90000)
b, f = build()
e = rows(f, "ETH")
chk(not [x9 for x9 in f.get("fiats") or [] if x9["ex"] == "업비트"] and e and near(e[0]["qty"], 100),
    "S8 하루 넘게 낡음 = 원화도 보정도 없음(끊긴 것 — 원장 100만)", (f.get("fiats"), [(r.get("key"), r.get("qty")) for r in e]))
snap({"KRW": (0, 50 * KRW1), "ETH": (150, 0)}, oo=False)
b, f = build()
e = rows(f, "ETH")
chk(e and near(e[0]["qty"], 100) and (b.__dict__.get("_ub_fill_info") or {}).get("why") == "no_open_orders",
    "S8 open_orders 없는 스냅숏(조회 중 체결로 생략) = 보정 없음(종전 · 다음 스냅숏에서)", (b.__dict__.get("_ub_fill_info"), [(r.get("key"), r.get("qty")) for r in e]))

reset_ledger({"ETH": 100})
snap({"KRW": (0, 50 * KRW1), "ETH": (150, 0)}, [order("u9", "KRW-ETH", "bid", 100, 50, int(50 * 1200 * FX))])
b, f = build()
e = rows(f, "ETH")
chk(e and near(e[0]["qty"], 150) and near(e[0]["kqty"], 150) and near(e[0]["avg"], (100000 + 60000) / 150, 0.001),
    "S9 체결 금액 근거 = 늘어난 50 만 그 원가($60,000) · 평단 = 가중 $1,066.67 · 원가 근거 수량 150", (e[0].get("qty"), e[0].get("kqty"), e[0].get("avg")) if e else None)
reset_ledger({"XRP": 1000, "BTC": 1})
snap({"KRW": (0, 0), "XRP": (1100, 0), "BTC": ("0.998", "0.001")}, [order("u9b", "BTC-XRP", "bid", 200, 100, "0.002")])
b, f = build(px=dict(PX, BTC=0))
e = rows(f, "XRP")
chk(e and near(e[0]["qty"], 1100) and near(e[0]["kqty"], 1000) and near(e[0]["avg"], 1.0, 1e-9),
    "S9 쿼트 시세 없음 = 늘어난 100 은 원가 미상(평단 $1 그대로 · 근거 수량 1000 — 기존 평단을 덮어씌우지 않음)", (e[0].get("qty"), e[0].get("kqty"), e[0].get("avg")) if e else None)
bq = rows(f, "BTC")
chk(bq and near(bq[0]["qty"], 0.998), "S9 BTC 마켓 매수 = 쿼트 BTC 원장 −0.002(1 → 0.998 · 실잔고와 같음)", [(r.get("key"), r.get("qty")) for r in bq])

reset_ledger({"ETH": 100})
c0 = dbm.open_db(common.DB_PATH, readonly=True)
before = (c0.execute("SELECT COUNT(*), COALESCE(SUM(CAST(qty_base AS INTEGER)), 0) FROM postings").fetchone()[:],
          c0.execute("SELECT group_id, location, qty_norm FROM positions ORDER BY 1, 2").fetchall())
c0.close()
snap({"KRW": (0, 50 * KRW1), "ETH": (150, 0)}, [order("u10", "KRW-ETH", "bid", 100, 50, 50 * KRW1)])
build()
c0 = dbm.open_db(common.DB_PATH, readonly=True)
after = (c0.execute("SELECT COUNT(*), COALESCE(SUM(CAST(qty_base AS INTEGER)), 0) FROM postings").fetchone()[:],
         c0.execute("SELECT group_id, location, qty_norm FROM positions ORDER BY 1, 2").fetchall())
c0.close()
chk([tuple(x) for x in before[1]] == [tuple(x) for x in after[1]] and tuple(before[0]) == tuple(after[0]), "S10 원장(postings)·위치 표(positions) 무변 — 화면 계산만", (before, after))

json.dump({"chains": {}, "wallets": [], "backfill_months": 5, "upbit": {"poll_sec": 300}}, open(CFG, "w"))
common.CFG_CACHE = None if hasattr(common, "CFG_CACHE") else None
snap({"KRW": (0, 50 * KRW1), "ETH": (150, 0)}, [order("u11", "KRW-ETH", "bid", 100, 50, 50 * KRW1)], age=700)
b, f = build()
if common.upbit_fresh_sec(b.cfg) == 1200:
    fu = [x9 for x9 in f.get("fiats") or [] if x9["ex"] == "업비트"]
    chk(len(fu) == 1 and not fu[0].get("stale") and f.get("upbitConnected") is True and near(total(f), 200000),
        "S11 주기 300초(신선도 1,200초) · 700초 스냅숏 = 원화 신선(낡음 표시 없음 · 연결됨 — 종전 600초 하드코딩은 낡음)", (fu, f.get("upbitConnected")))
else:
    chk(False, "S11 설정 주기 300초가 빌더 설정에 안 실림(시험 준비 문제)", common.upbit_fresh_sec(b.cfg))
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(CFG, "w"))

if ubfill is None:
    chk(False, "U ubfill 모듈 없음(수정 전 코드)")
else:
    D = Decimal
    chk(ubfill.deltas([{"uuid": "x", "market": "KRWETH", "side": "bid", "executed_volume": "1"}], {}) is None, "U 마켓 형식 오류 = 목록 전체 불신(None — 종전 동작)")
    chk(ubfill.deltas([order("x", "KRW-ETH", "bid", 10, "-1", 0)], {}) is None, "U 음수 체결량 = None")
    chk(ubfill.deltas([order("x", "KRW-ETH", "bid", 10, 5, 7000000)], {"x": False}) == {}, "U 기장본 해석 불가 = 보정 안 함(이미 기장된 몫 재가산 금지)")
    m = ubfill.deltas([order("a", "KRW-ETH", "bid", 10, 5, 7000000), order("b", "KRW-ETH", "ask", 10, 3, 4200000)], {})
    chk(m["ETH"]["dq"] == D(2) and m["ETH"]["k"] == D(2) and m["ETH"]["c"]["KRW"] == D(7000000) * D(2) / D(5) and "KRW" not in m,
        "U 같은 심볼 매수 5 · 매도 3 = 순 +2 · 원가 근거 수량 2(원가도 같은 비율) · KRW 는 안 돌려줌", m)
    m = ubfill.deltas([order("c", "BTC-XRP", "ask", 10, 4, "0.0004", fee="0.000001")], {})
    chk(m["XRP"]["dq"] == D(-4) and m["BTC"]["dq"] == D("0.000399") and m["BTC"]["c"] == {"BTC": D("0.000399")},
        "U BTC 마켓 매도 = 기준 −4 · 쿼트 +(금액 − 수수료) · 받은 쿼트의 원가 근거 = 그 수량(그 통화 시세로)", m)
    bk = {"d": {"uuid": "d", "quote": "KRW", "base": "ETH", "side": "bid", "vol": D(8), "funds": D(11200000), "fee": D(0)}}
    m = ubfill.deltas([order("d", "KRW-ETH", "bid", 10, 5, 7000000)], bk)
    chk(m["ETH"]["dq"] == D(-3) and m["ETH"]["k"] == 0, "U 기장(8)이 스냅숏(5)보다 앞섬 = −3(원장을 스냅숏 시점으로) · 원가 근거 없음", m)
    try:
        m = ubfill.deltas([order("f", "KRW-ETH", "bid", 10, 5, 7000000, fee="3500")], {}, 1000)
        chk(m["ETH"]["krw"] == D(-7003500), "U 원화 마켓 매수 원화 몫 = −(금액 + 수수료) · 기장 없음", m)
        bk = {"g": dict(ubfill.order_fill(order("g", "KRW-ETH", "bid", 10, 8, 11200000)), ts=900)}
        m = ubfill.deltas([order("g", "KRW-ETH", "bid", 10, 5, 7000000)], bk, 1000)
        chk(m["ETH"]["dq"] == D(-3) and m["ETH"]["krw"] == D(4200000), "U 기장본 이력 시각(900) ≤ 스냅숏(1000) = 원화 몫에서 기장분 뺌(−7,000,000 + 11,200,000)", m)
        bk["g"]["ts"] = 1100
        m = ubfill.deltas([order("g", "KRW-ETH", "bid", 10, 5, 7000000)], bk, 1000)
        chk(m["ETH"]["krw"] == D(-7000000), "U 기장본 이력 시각이 스냅숏 뒤 = 그 잔고 기준 되감기에 안 듦 → 빼지 않음", m)
        m = ubfill.deltas([order("h", "BTC-XRP", "ask", 10, 4, "0.0004")], {}, 1000)
        chk(m["XRP"]["krw"] == 0 and m["BTC"]["krw"] == 0, "U 원화 아닌 마켓 = 원화 몫 0", m)
    except (TypeError, KeyError) as e9:
        chk(False, "U 원화 몫 계산 없음(수정 전 코드)", repr(e9))
    o_nf = dict(order("e", "KRW-ETH", "bid", 10, 2, 0), price="1400000")
    o_nf.pop("executed_funds")
    m = ubfill.deltas([o_nf], {})
    chk(m["ETH"]["dq"] == D(2) and m["ETH"]["c"]["KRW"] == D(2800000), "U 체결 금액 칸 없음 = 지정가 × 체결량(core 와 같은 대체)", m)

from datetime import datetime as _dt, timedelta as _td
import histcurve
YD = _dt.now(web.KST) - _td(days=1)
YISO, YKEY = YD.strftime("%Y-%m-%d"), YD.strftime("%m-%d")


def day_val(f, key):
    return next((float(d9["val"]) for d9 in f.get("dailySeries") or [] if d9.get("date") == key), None)


G = reset_ledger({"ETH": 100})
snap({"KRW": (100 * KRW1, 0), "ETH": (100, 0)}, [])
b, f = build()
dpx = json.load(open(os.path.join(S, "daily_px.json")))
ok_seed = YISO in dpx and isinstance((dpx[YISO].get("xv") or {}).get("p"), dict)
chk(ok_seed and near(day_val(f, YKEY), 200000), "H1 준비: 어제 = ETH 100 + 원화 $100,000 = $200,000 · 그날 고정 구성요소 있음", (day_val(f, YKEY), ok_seed))
if ok_seed:
    dpx[YISO]["xv"]["p"]["ku"] = [100 * KRW1, "snap"]
    json.dump(dpx, open(os.path.join(S, "daily_px.json"), "w"))
snap({"KRW": (0, 50 * KRW1), "ETH": (150, 0)}, [order("h1", "KRW-ETH", "bid", 100, 50, 50 * KRW1)])
os.remove(os.path.join(S, "daily_cache.json"))
b, f = build()
chk(near(day_val(f, YKEY), 200000), "H1 무효화 뒤 다시 계산한 어제 = $200,000(오늘 부분 체결 50 이 어제 수량에 안 남음 — 종전 $250,000)", day_val(f, YKEY))
chk(near(total(f), 200000) and near(today_val(f), 200000), "H1 오늘은 그대로 보정(ETH 150 + 원화 $50,000)", (total(f), today_val(f)))
kit = histcurve.HIST.kit or {}
kg = (kit.get("groups") or {}).get(G["ETH"]) or {}
rw = histcurve.rewind(kit, [YISO]) if kg else {}
chk(kg and abs(float(kg.get("hold") or 0) - 150) < 1e-9 and abs(float((rw.get(G["ETH"]) or {}).get(YISO, 0)) - 100) < 1e-9,
    "H1 장기 곡선 재료: 지금 150 · 어제 되감기 = 100(보정분은 그 스냅숏 시각 뒤 증감)", (kg.get("hold"), rw.get(G["ETH"])))

import xparts
for side9, acc9, o9 in (("매수", {"KRW": (0, 50 * KRW1), "ETH": (150, 0)}, order("h1b", "KRW-ETH", "bid", 100, 50, 50 * KRW1)),
                        ("매도", {"KRW": (150 * KRW1, 0), "ETH": (0, 50)}, order("h1c", "KRW-ETH", "ask", 100, 50, 50 * KRW1))):
    G = reset_ledger({"ETH": 100})
    snap({"KRW": (100 * KRW1, 0), "ETH": (100, 0)}, [])
    b, f = build()
    dpx = json.load(open(os.path.join(S, "daily_px.json")))
    ku9 = ((dpx.get(YISO) or {}).get("xv") or {}).get("p", {}).get("ku")
    snap(acc9, [o9])
    os.remove(os.path.join(S, "daily_cache.json"))
    b, f = build()
    chk(ku9 and ku9[1] == "tl" and near(day_val(f, YKEY), 200000) and near(today_val(f), 200000),
        f"H1b 부분 {side9} · 어제 원화 = 이력 되감기(tl) · 무효화 뒤 다시 계산한 어제 = $200,000 · 오늘 $200,000(ub607 전 어제만 체결 금액만큼 틀림)",
        (ku9, day_val(f, YKEY), today_val(f)))
    src9 = ((b.__dict__.get("_x_kit") or {}).get("src") or {})
    k9 = xparts.krw_at((src9.get("base") or {}).get("ku"), (src9.get("tl") or {}).get("ku"), YD.replace(hour=23, minute=59, second=59).timestamp())
    chk(k9 is not None and abs(k9 - 100 * KRW1) < 1, f"H1b 부분 {side9} · 장기 곡선 재료 원화 되감기(어제 마감) = 체결 전 ₩{100 * KRW1:,.0f}", k9)

def build_on(b9):
    t9 = int(time.time())
    for k9, v9 in PX.items():
        b9.spot.ex_usd[f"upbit:{k9}"] = v9
        b9.spot.ex_ts[f"upbit:{k9}"] = t9
    conn9 = dbm.open_db(common.DB_PATH, readonly=True)
    try:
        return b9._build(conn9)["fields"]
    finally:
        conn9.close()


def book_done(uu, side, vol, funds, gid, ts):
    c9 = dbm.open_db(common.DB_PATH)
    c9.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('upbit','order',?,1,?,?)",
               (uu, json.dumps({"uuid": uu, "market": "KRW-ETH", "side": side, "state": "done", "ord_type": "limit", "price": "1400000",
                                "volume": str(vol), "executed_volume": str(vol), "executed_funds": str(funds), "paid_fee": "0",
                                "created_at": _dt.fromtimestamp(ts, web.KST).isoformat()}), int(ts)))
    aid9 = c9.execute("SELECT asset_id FROM assets WHERE address='upbit:ETH'").fetchone()[0]
    sg9 = 1 if side == "bid" else -1
    c9.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind,"
               " event, classifier_ver) VALUES ('exchange','upbit:fill',?,0,?,?,'exchange:upbit',?,?,NULL,?,?,4)",
               (uu, int(ts), aid9, str(sg9 * vol * 10 ** 8), repr(funds / FX), "acq" if sg9 > 0 else "disp", "EXF_BUY" if sg9 > 0 else "EXF_SELL"))
    q9 = Decimal(c9.execute("SELECT qty_norm FROM positions WHERE group_id=? AND location='exchange:upbit'", (gid,)).fetchone()[0]) + sg9 * vol
    c9.execute("UPDATE positions SET qty_norm=? WHERE group_id=? AND location='exchange:upbit'", (str(q9), gid))
    c9.commit()
    c9.close()


for side9 in ("bid", "ask"):
    G = reset_ledger({"ETH": 100})
    b = web.StateBuilder()
    b.skip_gen_check = True
    snap({"KRW": (100 * KRW1, 0), "ETH": (100, 0)}, [], age=60)
    f = build_on(b)
    seq9 = [("S0", day_val(f, YKEY), round(total(f), 2), 0)]
    for nm9, exe9, age9 in (("S1", 50, 40), ("S2", 50, 20), ("S3", 80, 10)):
        if side9 == "bid":
            snap({"KRW": (0, (100 - exe9) * KRW1), "ETH": (100 + exe9, 0)}, [order("h3" + side9, "KRW-ETH", "bid", 100, exe9, exe9 * KRW1)], age=age9)
        else:
            snap({"KRW": ((100 + exe9) * KRW1, 0), "ETH": (0, 100 - exe9)}, [order("h3" + side9, "KRW-ETH", "ask", 100, exe9, exe9 * KRW1)], age=age9)
        f = build_on(b)
        seq9.append((nm9, day_val(f, YKEY), round(total(f), 2), (((b.__dict__.get("_x_kit") or {}).get("src") or {}).get("bad") or {}).get("ku")))
    book_done("h3" + side9, side9, 100, 100 * KRW1, G["ETH"], time.time() - 5)
    snap({"KRW": (0, 0) if side9 == "bid" else (200 * KRW1, 0), "ETH": (200, 0) if side9 == "bid" else (0, 0)}, [])
    f = build_on(b)
    seq9.append(("S4", day_val(f, YKEY), round(total(f), 2), (((b.__dict__.get("_x_kit") or {}).get("src") or {}).get("bad") or {}).get("ku")))
    chk(all(near(v9, 200000) and near(t9, 200000) and not bd9 for _n9, v9, t9, bd9 in seq9),
        f"H3 {'매수' if side9 == 'bid' else '매도'} 같은 빌더 연속 수집 S0→S4 = 어제·오늘 늘 $200,000 · 자가 점검 불신 표식 없음(ub611 전 S2 부터 어제 "
        f"{'$150,000' if side9 == 'bid' else '$250,000'})", seq9)

G = reset_ledger({"ETH": 100}, booked=[("h2", "done", 100, 100 * KRW1)])
T_FILL = int(YD.replace(hour=23, minute=57, second=0, microsecond=0).timestamp())
_c = dbm.open_db(common.DB_PATH)
_pl = json.loads(_c.execute("SELECT payload FROM raw_ex WHERE uuid='h2'").fetchone()[0])
_pl["created_at"] = YD.replace(hour=23, minute=57, second=0, microsecond=0).isoformat()
_c.execute("UPDATE raw_ex SET payload=? WHERE uuid='h2'", (json.dumps(_pl),))
_c.execute("UPDATE postings SET event_ts=? WHERE source_id='h2'", (T_FILL,))
_c.commit()
_c.close()
snap({"KRW": (0, 50 * KRW1), "ETH": (150, 0)}, [order("h2", "KRW-ETH", "bid", 100, 50, 50 * KRW1)], age=700)
b, f = build()
lv = dict(b.daily.get("_live") or {})
T_CLOSE = YD.replace(hour=23, minute=55, second=0, microsecond=0).timestamp()
lv["date"], lv["ts"] = YISO, T_CLOSE
if isinstance(lv.get("xv"), dict):
    lv["xv"] = dict(lv["xv"], ts=int(T_CLOSE), rt=dict(lv["xv"].get("rt") or {}, upbit=int(T_CLOSE - 720)))
dc = json.load(open(os.path.join(S, "daily_cache.json")))
dc.pop(YISO, None)
dc["_live"] = dc["_live_ok"] = lv
json.dump(dc, open(os.path.join(S, "daily_cache.json"), "w"))
dpx = json.load(open(os.path.join(S, "daily_px.json")))
dpx.pop(YISO, None)
json.dump(dpx, open(os.path.join(S, "daily_px.json"), "w"))
snap({"KRW": (0, 0), "ETH": (200, 0)}, [])
b, f = build()
chk(near(day_val(f, YKEY), 200000) and (b.daily.get(YISO) or {}).get("src") == "live",
    "H2 낡은 스냅숏 마감 → 다음 날 동결 = $200,000(원장 200 + 그날 마감 원화 0 — 종전 보정 150 이 굳어 $150,000)", (day_val(f, YKEY), (b.daily.get(YISO) or {}).get("src")))

T.finish()
