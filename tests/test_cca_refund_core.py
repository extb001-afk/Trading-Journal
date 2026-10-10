#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _ingest
from _ingest import W, Reader

import json
import os
import time

json.dump({"chains": {"eth": {"blockscout": "https://bs.invalid", "etherscan_chainid": 1, "conf_depth": 12, "blocks_per_day": 7200,
                              "rpcs": ["https://rpc.invalid"]}},
           "wallets": [{"type": "evm", "chain": "eth", "address": W, "label": "w"}],
           "native_symbol": {"eth": "ETH"}, "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
os.environ["TJ_NEGABS"] = "0"
import acct_norm
import common
import core
import db as dbm
import histcurve
import netpace
import pricing
import web

chk = T.chk
core.dm = lambda *a, **k: None
FS_EX = getattr(web, "FS_EX", " · 최초 인식 시가")
for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker"):
    if hasattr(web.StateBuilder, _m):
        setattr(web.StateBuilder, _m, lambda self: None)
netpace.wait = lambda url, now=None, sleep=None: None
E18, E6 = 10 ** 18, 10 ** 6
DAY = 86400
NOW = int(time.time())
D0 = NOW - 40 * DAY
X, ROUTER, AUC, TKN = "0x" + "b7" * 20, "0x" + "c7" * 20, "0x" + "a7" * 20, "0x" + "d7" * 20
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
ISO = acct_norm.iso_day


def h(n):
    return "0x" + ("%064x" % n)


def eth_px(ts):
    return 1000.0 if ts < D0 + 2 * DAY - 3600 else 1200.0


def _candle(self, sym, ms):
    s = str(sym or "").upper()
    return eth_px(int(ms) // 1000) if s in ("ETH", "WETH") else (1.0 if s in ("USDT", "USDC") else None)


def fake_lookup(spec, iso, now=None, w=0.0, ask=True, old=False):
    if "ETH" not in str(spec or "").upper():
        return None, "pending"
    return eth_px(int(time.mktime(time.strptime(iso + " 23:00", "%Y-%m-%d %H:%M")))), "ok"


fake_lookup._tj_test_mock = True
pricing.PxCache.candle_usd = _candle
web.pricing._gj = lambda url, timeout=10.0: None
histcurve.DAYCLOSE.lookup = fake_lookup


def snap(hx, ts, blk, frm, to, value=0, toks=(), internal=(), data="0x12345678"):
    return {"tx": {"hash": hx, "from": frm, "to": to, "value": str(value), "fee": {"value": "0"}, "status": "ok", "raw_input": data,
                   "timestamp": ts, "block_number": blk, "block_hash": "0x" + "d" * 64},
            "token_transfers": [{"from": f, "to": t, "token": {"address": ca, "symbol": sym, "decimals": dec, "type": "ERC-20"},
                                 "total": {"value": str(v), "decimals": str(dec)}} for f, t, ca, sym, dec, v in toks],
            "internal": [{"from": f, "to": t, "value": str(v), "success": True} for f, t, v in internal]}


FUND0, FUND, BID, EXIT, CLAIM, SELL = h(0x10), h(0x11), h(0x12), h(0x13), h(0x14), h(0x15)
FEEDS = [
    (FUND0, snap(FUND0, D0 - DAY, 900, X, W, toks=[(X, W, USDT, "USDT", 6, 30000 * E6)], data="0xa9059cbb")),
    (FUND, snap(FUND, D0, 1000, W, ROUTER, toks=[(W, ROUTER, USDT, "USDT", 6, 10000 * E6)], internal=[(ROUTER, W, 10 * E18)])),
    (BID, snap(BID, D0 + DAY, 1100, W, AUC, value=10 * E18)),
    (EXIT, snap(EXIT, D0 + 2 * DAY, 1200, W, AUC, internal=[(AUC, W, 9 * E18)])),
    (CLAIM, snap(CLAIM, D0 + 3 * DAY, 1300, W, AUC, toks=[(AUC, W, TKN, "TKN", 18, 1000 * E18)])),
    (SELL, snap(SELL, D0 + 10 * DAY, 2000, W, ROUTER, value=9 * E18, toks=[(ROUTER, W, USDT, "USDT", 6, 10800 * E6)])),
]


def feed(c, hx, s):
    c._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": hx, "wallets": [W], "snapshot": s, "ts": 1}]), 0, 0)


def ledger_rows(c):
    return [tuple(r) for r in c.conn.execute("SELECT source_id, leg_seq, event, leg_kind, location, qty_base FROM postings ORDER BY source_id, leg_seq")]


c = core.Core(common.load_config())
for hx, s in FEEDS:
    feed(c, hx, s)
c.conn.commit()
first = ledger_rows(c)
for hx, s in FEEDS:
    feed(c, hx, s)
c.conn.commit()
for _ in range(3):
    c._last_price_pass = 0
    c.price_pass()
c.conn.commit()
rows = ledger_rows(c)
ev = {(r[0], r[3], r[4].split(":")[0] + ":" + r[4].split(":")[-1][:6]): (r[2], int(r[5])) for r in rows}
chk(ev.get((BID, "move_out", "wallet:" + W[:6])) == ("TRANSFER_OUT", -10 * E18) and ev.get((BID, "move_in", "out:" + AUC[:6])) == ("TRANSFER_OUT", 10 * E18),
    "R1 입찰 = TRANSFER_OUT(지갑 −10 ETH · out:경매 +10)", [r for r in rows if r[0] == BID])
chk(ev.get((EXIT, "acq", "wallet:" + W[:6])) == ("PROGRAM_IN", 9 * E18) and ev.get((CLAIM, "acq", "wallet:" + W[:6]), ("", 0))[0] == "PROGRAM_IN",
    "R1 종료 tx 환불 9 ETH = PROGRAM_IN · 토큰 수령 = PROGRAM_IN", [r for r in rows if r[0] in (EXIT, CLAIM)])
chk(rows == first, "R1 같은 스냅숏 두 번(반복 raw 입력) = 원장 무변", [len(first), len(rows)])
costs = {(r[0], r[1]): r[2] for r in c.conn.execute("SELECT source_id, leg_seq, cost_usd FROM postings WHERE event='SWAP'")}
c.conn.close()

json.dump({"owners": {f"eth:{W}": {"t": NOW, "chain": "eth", "owner": W,
                                    "bids": [{"auction": AUC, "id": 1, "amount": str(10 * E18), "bid_tx": BID, "bid_ts": D0 + DAY,
                                              "filled": str(1000 * E18), "refunded": str(9 * E18), "exit_tx": EXIT, "exit_ts": D0 + 2 * DAY,
                                              "claim_tx": CLAIM, "claim_ts": D0 + 3 * DAY}],
                                    "auctions": {AUC: {"ok": True, "why": "seed", "currency": {"addr": "", "sym": "ETH", "dec": 18},
                                                       "token": {"addr": TKN, "sym": "TKN", "dec": 18}}}}}}, open(web.SALE_PATH, "w"))
spot = {"ETH": 2000.0, "USDT": 1.0}
json.dump({"usd": spot, "usd_ts": {k: NOW for k in spot}, "rate": 1300.0, "updated": NOW, "dex_usd": {}, "dex_ts": {}, "dex_res": {}, "dex_res_ts": {},
           "fx_basis": 1300.0, "ex_usd": {}, "ex_ts": {}}, open(web.SPOT_PATH, "w"))


def build(prefs=None):
    common.atomic_write_json(web.PREFS_PATH, dict({"plans": {}, "ignored": []}, **(prefs or {})))
    b = web.StateBuilder()
    b.skip_gen_check = True
    conn = dbm.open_db(common.DB_PATH, readonly=True)
    try:
        f = b._build(conn)["fields"]
    finally:
        conn.close()
    return f, [r for r in ((b._day_idx or {}).get("tax") or []) if r.get("sym") == "ETH"]


def ad(rows9):
    return [(round(float(r.get("_qty", r.get("qty")) or 0), 6), round(float(r.get("_acq", r.get("acq")) or 0), 2),
             round(float(r.get("_disp", r.get("disp")) or 0), 2), str(r.get("ex") or "").endswith(FS_EX)) for r in rows9]


f, er = build()
sl = [(s.get("costUsd"), s.get("refundBackCost")) for s in f.get("saleLinks") or []]
rz = round(float((f.get("realizedByDate") or {}).get(ISO(D0 + 10 * DAY), 0)), 2)
chk(sl and sl[0][0] == 1000.0, "R2 취득 토큰 원가 $1,000(15차 그대로)", [sl, costs])
chk(ad(er) == [(9.0, 9000.0, 10800.0, False)] and rz == 1800.0,
    "R2 환불 ETH 매도 명세 = 수량 9 · 취득 $9,000 · 처분 $10,800 · 실현 $1,800 · 최초 인식 시가 표기 없음(종전 $10,800 · 실현 0 · 추정 표기)", [ad(er), rz, costs])
f2, er2 = build({"first_seen_px": False})
chk(ad(er2) == ad(er) and round(float((f2.get("realizedByDate") or {}).get(ISO(D0 + 10 * DAY), 0)), 2) == 1800.0,
    "R2 최초 인식 시가 끔 = 같은 값(종전: 원가 미확인 · 명세 행 없음)", ad(er2))
f3, er3 = build()
chk(ad(er3) == ad(er) and [(s.get("costUsd"), s.get("refundBackCost")) for s in f3.get("saleLinks") or []] == sl, "R3 다시 빌드 = 같은 값", ad(er3))
T.finish()
