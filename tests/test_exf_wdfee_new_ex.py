#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import time
from decimal import Decimal

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import common
import core
import db as dbm

assert T.TMP in common.STATE_DIR
core.dm = lambda *a, **k: None
chk = T.chk
NOW = int(time.time())
T_OLD = NOW - 20 * 86400
E8 = 10 ** 8
EXT = "0x" + "e7" * 20


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(t))


def mk_core():
    c9 = core.Core(common.load_config())
    c9._quote_usd = lambda q, ts: Decimal(1) if str(q).upper() in ("USDT", "USDC") else None
    c9.px.fx_at = lambda ms: 1380.0
    return c9


def wd(ex, uid, cur, amt, fee, t, fee_ccy=None):
    d = {"uuid": uid, "currency": cur, "amount": str(amt), "fee": str(fee), "txid": "0x" + uid.encode().hex().ljust(64, "0")[:64],
         "state": "DONE", "address": EXT, "created_at": iso(t), "done_at": iso(t + 60)}
    if fee_ccy:
        d["fee_ccy"] = fee_ccy
    return d


def legs(c9, ex, uid):
    return [(r[0], r[1], r[2]) for r in c9.conn.execute(
        "SELECT p.event, a.symbol, p.qty_base FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.source_ns=? AND p.source_id=?"
        " ORDER BY p.leg_seq", (f"{ex}:withdraw", uid))]


def held(c9, ex, sym):
    r = c9.conn.execute("SELECT COALESCE(sum(CAST(p.qty_base AS INTEGER)), 0) FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                        " WHERE p.location=? AND upper(a.symbol)=?", (f"exchange:{ex}", sym)).fetchone()
    return Decimal(r[0]) / E8


c = mk_core()
since0 = c.wd_fee_since
chk(abs(since0 - NOW) < 600, "준비: 기능 시작 시각 = 첫 기동(지금) — 옛 출금은 그 전", since0)
c._consume_ex({"exchange": "binance", "deposits": [{"uuid": "bn:d1", "currency": "USDT", "amount": "3000", "txid": "0x" + "d1" * 32,
                                                     "state": "ACCEPTED", "created_at": iso(T_OLD - 7200), "done_at": iso(T_OLD - 7200)}]})
c._consume_exf_fills({"exchange": "binance", "fills": [{"id": "binance:ETHUSDT:1", "ts": (T_OLD - 3600) * 1000, "base": "ETH", "quote": "USDT",
                                                         "side": "buy", "price": "3000", "qty": "1", "fee": "0", "fee_ccy": "ETH"}]})
c._consume_ex({"exchange": "binance", "withdraws": [wd("binance", "bn:w1", "ETH", "0.99", "0.01", T_OLD)]})
T_OTH = T_OLD + 3 * 86400
c._consume_ex({"exchange": "okx", "withdraws": [wd("okx", "okx:w1", "USDT", "100", "1", T_OTH)]})
c._consume_ex({"exchange": "gate", "withdraws": [wd("gate", "gt:w1", "USDT", "99", "1", T_OTH)]})
c.conn.commit()
lb = legs(c, "binance", "bn:w1")
chk(lb == [("EXF_WITHDRAW", "ETH", str(-99 * E8 // 100)), ("EXF_WD_FEE", "ETH", str(-1 * E8 // 100))],
    "W1 처음 연결한 바이낸스 · 설치 전 출금 = 본액 −0.99 + 수수료 레그 −0.01", lb)
chk(held(c, "binance", "ETH") == 0, "W1 바이낸스 ETH = 0(유령 0.01 ETH 없음)", held(c, "binance", "ETH"))
lo = legs(c, "okx", "okx:w1")
chk([x[0] for x in lo] == ["EXF_WITHDRAW", "EXF_WD_FEE"], "W3 처음 연결한 OKX 도 수수료 레그", lo)
lg = legs(c, "gate", "gt:w1")
chk([x[0] for x in lg] == ["EXF_WITHDRAW"], "W3 게이트(수수료가 수량에 포함) = 레그 없음(이중 차감 금지)", lg)
mv = {r[0]: r[1] for r in c.conn.execute("SELECT k, v FROM meta WHERE k LIKE 'exf_wd_fee_since%'")}
chk(mv.get("exf_wd_fee_since:binance") == "0" and mv.get("exf_wd_fee_since:okx") == "0" and "exf_wd_fee_since:gate" not in mv
    and mv.get("exf_wd_fee_since") == str(since0), "W4 기준 시각 = 원장 meta(바이낸스·OKX 0 · 게이트 없음 · 전역 그대로)", mv)

c.conn.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('bybit','deposit','bb:old',1,'{}',?)", (T_OLD,))
c._consume_ex({"exchange": "bybit", "withdraws": [wd("bybit", "bb:w1", "USDT", "50", "1", T_OTH)]})
c._consume_ex({"exchange": "bybit", "withdraws": [wd("bybit", "bb:w2", "USDT", "50", "1", since0 + 10)]})
c.conn.commit()
chk([x[0] for x in legs(c, "bybit", "bb:w1")] == ["EXF_WITHDRAW"] and [x[0] for x in legs(c, "bybit", "bb:w2")] == ["EXF_WITHDRAW", "EXF_WD_FEE"],
    "W4 이미 연결돼 있던 거래소 = 종전 경계(시작 전 출금 레그 없음 · 시작 뒤 출금 레그)", (legs(c, "bybit", "bb:w1"), legs(c, "bybit", "bb:w2")))
c.conn.close()
c2 = mk_core()
chk(c2._wd_fee_since_of("binance") == 0 and c2._wd_fee_since_of("bybit") == since0 if hasattr(c2, "_wd_fee_since_of") else False,
    "W4 다시 기동해도 같은 기준(바이낸스 0 · 바이비트 전역)", None)
c2.conn.execute("DELETE FROM postings WHERE source_ns='binance:withdraw'")
c2._post_exf_withdraw("binance", "bn:w1", wd("binance", "bn:w1", "ETH", "0.99", "0.01", T_OLD))
chk([x[0] for x in legs(c2, "binance", "bn:w1")] == ["EXF_WITHDRAW", "EXF_WD_FEE"], "W4 재기장(재구축 경로)도 같은 레그", legs(c2, "binance", "bn:w1"))
c2.conn.commit()
c2.conn.close()

import netpace
import web

for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker"):
    if hasattr(web.StateBuilder, _m):
        setattr(web.StateBuilder, _m, lambda self: None)
netpace.wait = lambda url, now=None, sleep=None: None
web.pricing._gj = lambda url, *a, **k: (_ for _ in ()).throw(OSError("시험: 시세 받기 없음"))
web.pricing.PxCache.fx_at = lambda self, ms: 1380.0
_px = {"USDT": 1.0, "ETH": 3000.0}
web.pricing.PxCache.candle_usd = lambda self, sym, ms: _px.get(str(sym).upper())
spot = {"usd": _px, "usd_ts": {k: NOW for k in _px}, "rate": 1380.0, "updated": NOW, "dex_usd": {}, "dex_ts": {}, "dex_res": {}, "dex_res_ts": {},
        "fx_basis": 1380.0, "ex_usd": {"binance:ETH": 3000.0, "binance:USDT": 1.0}, "ex_ts": {"binance:ETH": NOW, "binance:USDT": NOW}}
json.dump(spot, open(web.SPOT_PATH, "w"))
common.atomic_write_json(web.PREFS_PATH, {"plans": {}, "ignored": []})
b = web.StateBuilder()
b.skip_gen_check = True
conn = dbm.open_db(common.DB_PATH, readonly=True)
try:
    f = b._build(conn)["fields"]
finally:
    conn.close()
import acct_norm

dk = acct_norm.iso_day(T_OLD)
rbd = f.get("realizedByDate") or {}
v = [val for k9, val in rbd.items() if k9 in (dk, dk[5:])]
chk(bool(v) and abs(v[0] - (-30.0)) < 1e-6, "W2 바이낸스 설치 전 출금 수수료 = 그날 실현 −$30(0.01 ETH × $3,000 · 종전 $0)", (dk, rbd))
T.finish()
