#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from decimal import Decimal  # noqa: E402

W = "0x" + "ab" * 20
W2 = "0x" + "ac" * 20
S_WL = "0x" + "d1" * 20
S_OTH = "0x" + "e2" * 20
DAY = 86400
KST = timezone(timedelta(hours=9))
NOW = int(datetime.now(KST).replace(hour=12, minute=0, second=0, microsecond=0).timestamp())
D0, D1, D2 = NOW - 20 * DAY, NOW - 10 * DAY, NOW - 5 * DAY
TS = int(time.time())
shutil.copytree(os.path.join(T.ROOT, "seed"), os.path.join(T.TMP, "seed"), dirs_exist_ok=True)
import _nonevm as NE  # noqa: E402

import address_codec  # noqa: E402
MYT_KEY = "41" + "b2" * 20
S_TRON_KEY = "41" + "c3" * 20
WS = "HarvMyWa11et1111111111111111111111111111111"
S_SOL = "HarvWhiteListSo1ana22222222222222222222222"
BTC_MY = NE.BTC_ADDR
BTC_WL = "bc1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3qccfmv3"
json.dump({"wallets": [{"type": "evm", "chain": "base", "address": W, "label": "본지갑"}, {"type": "evm", "chain": "base", "address": W2, "label": "둘째"},
                       {"type": "evm", "chain": "arbitrum", "address": W, "label": "본지갑"}, {"type": "sol", "chain": "sol", "address": WS, "label": "솔지갑"},
                       {"type": "tron", "chain": "tron", "address": address_codec.tron_display(MYT_KEY), "label": "트론지갑"}],
           "chain_wallets": [{"chain": "btc", "network": "mainnet", "mode": "address", "address": BTC_MY, "label": "비트지갑"}],
           "backfill_months": 3, "chains": {}}, open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
import paths  # noqa: E402

assert T.TMP in paths.STATE_DIR
import chain_registry  # noqa: E402
import db as dbm  # noqa: E402

BTC_KEY = chain_registry.owner_key("btc", BTC_MY)
WLIST = [S_WL, S_SOL, address_codec.tron_display(S_TRON_KEY), BTC_WL]


def check(name, ok, detail=""):
    T.chk(bool(ok), name, None if ok else detail)


def h(tag):
    return "0x" + hashlib.sha256(tag.encode()).hexdigest()


def iso(ts):
    return datetime.fromtimestamp(ts, KST).strftime("%Y-%m-%d")


con = dbm.open_db(os.path.join(paths.STATE_DIR, "ledger.db"))
ST = {"aid": 0, "pid": 0}
DEC, GID, CA = {}, {}, {}
WL, W2L, WAL, BNL, UPL = f"wallet:base:{W}", f"wallet:base:{W2}", f"wallet:arbitrum:{W}", "exchange:binance", "exchange:upbit"


def asset(chain, addr, sym, gname=None, d=18, kind="token"):
    ST["aid"] += 1
    a = ST["aid"]
    nm = gname or f"{sym}#{a}"
    row = con.execute("SELECT group_id FROM asset_groups WHERE name=?", (nm,)).fetchone()
    if row is None:
        con.execute("INSERT INTO asset_groups (group_id, name, norm_decimals) VALUES (?,?,18)", (100 + a, nm))
    g = row[0] if row is not None else 100 + a
    con.execute("INSERT INTO assets (asset_id, kind, chain, address, symbol, decimals, confirmed, hidden, group_id) VALUES (?,?,?,?,?,?,1,0,?)",
                (a, kind, chain, addr, sym, d, g))
    DEC[a], GID[a] = d, g
    if addr and kind == "token":
        CA[a] = addr
    return a


def leg(kind, ns, tx, seq, ts, a, loc, qty, lk, ev, cost=None):
    ST["pid"] += 1
    con.execute("INSERT INTO postings (posting_id, source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd,"
                " cost_krw, leg_kind, event, classifier_ver) VALUES (?,?,?,?,?,?,?,?,?,?,NULL,?,?,5)",
                (ST["pid"], kind, ns, tx, seq, ts, a, loc, str(int(round(qty * 10 ** DEC[a]))), None if cost is None else repr(float(cost)), lk, ev))


def ctx(tag, ts, legs, ev, signer=None, tx=None, transfers=None, chain="base"):
    t9 = tx or h(tag)
    for i, (a, q, lk, c, loc) in enumerate(legs):
        leg("chain_tx", chain, t9, i, ts, a, loc, q, lk, ev, c)
    con.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES (?,?,?,'{}',5)", (chain, t9, ev))
    if signer:
        snap = {"tx": {"hash": t9, "from": signer, "to": "0x" + "77" * 20, "value": "0", "fee": {"value": "21000"}, "status": "ok", "raw_input": "0xabcdef12"},
                "token_transfers": [{"from": {"hash": f9}, "to": {"hash": t9t}, "token": {"address": ca9, "type": "ERC-20"}, "total": {"value": str(int(v9 * 10 ** 18))}}
                                    for f9, t9t, ca9, v9 in (transfers or [])], "internal": []}
        con.execute("INSERT INTO raw_txs (chain, txhash, block, ts, snapshot, wallets, ingested_at) VALUES (?,?,?,?,?,'[]',0)", (chain, t9, 1, ts, json.dumps(snap)))
    return t9


def raw(ex, kind, uid, payload, t):
    con.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES (?,?,?,1,?,?)", (ex, kind, uid, json.dumps(dict(payload, uuid=uid)), t))


def ex_in(ex, uid, a, qty, txid, t, upbit=False, link_asset=None):
    sym = con.execute("SELECT symbol FROM assets WHERE asset_id=?", (a,)).fetchone()[0]
    raw(ex, "deposit", uid, {"currency": sym, "amount": str(qty), "txid": txid, "state": "ACCEPTED", "type": "deposit"}, t)
    if upbit:
        con.execute("INSERT INTO transfers (state, asset_id, qty_base, src, dst, chain_txhash, ex_uuid, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                    ("credited", link_asset, str(int(qty * 10 ** DEC[link_asset])), WL, "exchange:upbit", txid, uid, NOW))
    leg("exchange", f"{ex}:deposit", uid, 0, t, a, UPL if upbit else BNL, qty, "move_in", "EX_DEPOSIT" if upbit else "EXF_DEPOSIT")


eth = asset("base", None, "ETH", "ETH", 18, "native")
weth = asset("base", "0x4200000000000000000000000000000000000006", "WETH", "ETH")
usdc = asset("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", "USDC", 6)
usdc_a = asset("arbitrum", "0xaf88d065e77c8cc2239327c5edb3a432268e5831", "USDC", "USDC", 6)
busdt = asset(None, "binance:USDT", "USDT", "USDT", 8, "exchange_currency")
bbtc = asset(None, "binance:BTC", "BTC", "BTC", 8, "exchange_currency")
good = asset("base", "0x" + "11" * 20, "GOOD")
ctx("good-claim", D1, [(good, 1000, "acq", None, WL), (eth, -0.001, "gas", 2.0, WL)], "PROGRAM_IN", signer=W)
ctx("good-sell", D2, [(good, -400, "disp", 800, WL), (usdc, 800, "acq", 800, WL)], "SWAP", signer=W)
ctx("good-sell2", D2 + 600, [(good, -100, "disp", 200, WL), (usdc, 200, "acq", 200, WL)], "SWAP", signer=W)
mix = asset("base", "0x" + "22" * 20, "MIX")
ctx("mix-buy", D0, [(usdc, -500, "disp", 500, WL), (mix, 1000, "acq", 500, WL)], "SWAP", signer=W)
ctx("mix-claim", D1, [(mix, 1000, "acq", None, WL)], "PROGRAM_IN", signer=W)
ctx("mix-sell", D2, [(mix, -1000, "disp", 2000, WL), (usdc, 2000, "acq", 2000, WL)], "SWAP", signer=W)
h2p = asset("base", "0x" + "23" * 20, "H2P")
ctx("h2p-claim", D1, [(h2p, 10, "acq", None, WL)], "PROGRAM_IN", signer=W)
ctx("h2p-push", D1 + 600, [(h2p, 1000, "acq", None, WL)], "TRANSFER_IN", signer=S_OTH, transfers=[(S_OTH, W, CA[h2p], 1000)])
ctx("h2p-sell", D2, [(h2p, -505, "disp", 505, WL), (usdc, 505, "acq", 505, WL)], "SWAP", signer=W)
mv = asset("base", "0x" + "33" * 20, "MV")
bmv = asset(None, "binance:MV", "MV", None, 8, "exchange_currency")
ctx("mv-claim", D1, [(mv, 1000, "acq", None, WL)], "PROGRAM_IN", signer=W)
TK = ctx("mv-out", D1 + 3600, [(mv, -1000, "move_out", None, WL)], "TRANSFER_OUT_EX", signer=W)
ex_in("binance", "MV-D", bmv, 1000, TK, D1 + 4200)
leg("exchange", "binance:trade", "binance:MVUSDT:1", 0, D2, bmv, BNL, -1000, "disp", "EXF_SELL", 3000)
leg("exchange", "binance:trade", "binance:MVUSDT:1", 1, D2, busdt, BNL, 3000, "acq", "EXF_SELL", 3000)
leg("exchange", "binance:trade", "binance:MVUSDT:1", 2, D2, busdt, BNL, -3.0, "gas", "EXF_FEE")
mu = asset("base", "0x" + "34" * 20, "MU")
umu = asset(None, "upbit:MU", "MU", None, 8, "exchange_currency")
ctx("mu-claim", D1, [(mu, 1000, "acq", None, WL)], "PROGRAM_IN", signer=W)
TU = ctx("mu-out", D1 + 3600, [(mu, -1000, "move_out", None, WL)], "TRANSFER_OUT_EX", signer=W)
ex_in("upbit", "MU-D", umu, 1000, TU, D1 + 4200, upbit=True, link_asset=mu)
leg("exchange", "upbit:order", "MU-S", 0, D2, umu, UPL, -1000, "disp", "EX_SELL", 2997)
mv3, bmv3, mv3a = asset("base", "0x" + "35" * 20, "MV3"), asset(None, "binance:MV3", "MV3", None, 8, "exchange_currency"), asset("arbitrum", "0x" + "36" * 20, "MV3")
ctx("mv3-claim", D1, [(mv3, 1000, "acq", None, WL)], "PROGRAM_IN", signer=W)
T3 = ctx("mv3-out", D1 + 3600, [(mv3, -1000, "move_out", None, WL)], "TRANSFER_OUT_EX", signer=W)
ex_in("binance", "MV3-D", bmv3, 1000, T3, D1 + 4200)
T3W = h("mv3-arrive")
leg("exchange", "binance:withdraw", "MV3-W", 0, D1 + 2 * DAY, bmv3, BNL, -1000, "move_out", "EXF_WITHDRAW")
raw("binance", "withdraw", "MV3-W", {"currency": "MV3", "amount": "1000", "fee": "0", "state": "DONE", "txid": T3W}, D1 + 2 * DAY)
ctx("mv3-arrive", D1 + 2 * DAY + 600, [(mv3a, 1000, "acq", None, WAL)], "TRANSFER_IN", tx=T3W, chain="arbitrum")
ctx("mv3-sell", D2, [(mv3a, -1000, "disp", 1000, WAL), (usdc_a, 1000, "acq", 1000, WAL)], "SWAP", signer=W, chain="arbitrum")
mixf, bmixf, umixf = asset("base", "0x" + "37" * 20, "MIXF"), asset(None, "binance:MIXF", "MIXF", None, 8, "exchange_currency"), asset(None, "upbit:MIXF", "MIXF", None, 8, "exchange_currency")
ctx("mixf-claim", D1, [(mixf, 100, "acq", None, WL)], "PROGRAM_IN", signer=W)
TF1 = ctx("mixf-out1", D1 + 600, [(mixf, -100, "move_out", None, WL)], "TRANSFER_OUT_EX", signer=W)
ctx("mixf-buy", D1 + 1200, [(usdc, -100, "disp", 100, WL), (mixf, 100, "acq", 100, WL)], "SWAP", signer=W)
TF2 = ctx("mixf-out2", D1 + 1800, [(mixf, -100, "move_out", None, WL)], "TRANSFER_OUT_EX", signer=W)
ex_in("binance", "MIXF-D1", bmixf, 100, TF1, D1 + 3000)
ex_in("upbit", "MIXF-D2", umixf, 100, TF2, D1 + 3600, upbit=True, link_asset=mixf)
leg("exchange", "binance:trade", "binance:MIXFUSDT:1", 0, D2, bmixf, BNL, -100, "disp", "EXF_SELL", 1000)
leg("exchange", "binance:trade", "binance:MIXFUSDT:1", 1, D2, busdt, BNL, 1000, "acq", "EXF_SELL", 1000)
leg("exchange", "upbit:order", "MIXF-S", 0, D2, umixf, UPL, -100, "disp", "EX_SELL", 100)
feec, bfeec = asset("base", "0x" + "38" * 20, "FEEC"), asset(None, "binance:FEEC", "FEEC", None, 8, "exchange_currency")
ctx("feec-claim", D1, [(feec, 100, "acq", None, WL)], "PROGRAM_IN", signer=W)
TC = ctx("feec-out", D1 + 600, [(feec, -100, "move_out", None, WL)], "TRANSFER_OUT_EX", signer=W)
ex_in("binance", "FEEC-D", bfeec, 100, TC, D1 + 3000)
leg("exchange", "binance:trade", "binance:BTCUSDT:7", 0, D1 + DAY, busdt, BNL, -3000, "disp", "EXF_BUY", 3000)
leg("exchange", "binance:trade", "binance:BTCUSDT:7", 1, D1 + DAY, bbtc, BNL, 0.05, "acq", "EXF_BUY", 3000)
leg("exchange", "binance:trade", "binance:BTCUSDT:7", 2, D1 + DAY, bfeec, BNL, -100, "gas", "EXF_FEE")
leg("exchange", "binance:trade", "binance:FEECUSDT:8", 0, D1 + 2 * DAY, busdt, BNL, -100, "disp", "EXF_BUY", 100)
leg("exchange", "binance:trade", "binance:FEECUSDT:8", 1, D1 + 2 * DAY, bfeec, BNL, 100, "acq", "EXF_BUY", 100)
leg("exchange", "binance:trade", "binance:FEECUSDT:9", 0, D2, bfeec, BNL, -100, "disp", "EXF_SELL", 1000)
leg("exchange", "binance:trade", "binance:FEECUSDT:9", 1, D2, busdt, BNL, 1000, "acq", "EXF_SELL", 1000)
cc, bcc = asset("base", "0x" + "39" * 20, "CC"), asset(None, "binance:CC", "CC", None, 8, "exchange_currency")
ctx("cc-claim", D1, [(cc, 1000, "acq", None, WL)], "PROGRAM_IN", signer=W)
TCC = ctx("cc-out", D1 + 600, [(cc, -1000, "move_out", None, WL)], "TRANSFER_OUT_EX", signer=W)
ex_in("binance", "CC-D", bcc, 1000, TCC, D1 + 3000)
leg("exchange", "binance:trade", "binance:CCBTC:1", 0, D2, bcc, BNL, -1000, "disp", "EXF_SELL", 3000)
leg("exchange", "binance:trade", "binance:CCBTC:1", 1, D2, bbtc, BNL, 0.05, "acq", "EXF_SELL", 3000)
leg("exchange", "binance:trade", "binance:CCBTC:1", 2, D2, busdt, BNL, -3.0, "gas", "EXF_FEE")
imp1 = asset("base", "0x" + "41" * 20, "USD​T")
imp2 = asset("base", "0x" + "42" * 20, "USDТ")
unv = asset("base", "0x" + "43" * 20, "USDT")
gp = asset("base", "0x" + "44" * 20, "HPOT")
dust = asset("base", "0x" + "45" * 20, "DUST")
dust2 = asset("base", "0x" + "46" * 20, "DUST2")
for a9, q9, tag9 in ((imp1, 500, "imp1"), (imp2, 500, "imp2"), (unv, 500, "unv"), (gp, 1000, "gp"), (dust, 0.001, "dust"), (dust2, 0.002, "dust2")):
    ctx(tag9 + "-push", D1, [(a9, q9, "acq", None, WL)], "PROGRAM_IN", signer=S_OTH, transfers=[(S_OTH, W, CA[a9], q9)])
for a9, q9, tag9 in ((gp, 100, "gp"), (dust, 0.0005, "dust"), (dust2, 0.001, "dust2")):
    ctx(tag9 + "-self", D1 + 7200, [(a9, -q9, "move_out", None, WL), (a9, q9, "move_in", None, W2L)], "TRANSFER_SELF", signer=W)
susp = asset("base", "0x" + "51" * 20, "SUSP")
ctx("susp-push", D1, [(susp, 500, "acq", None, WL)], "PROGRAM_IN", signer=S_OTH, transfers=[(S_OTH, W, CA[susp], 500)])
pushok = asset("base", "0x" + "52" * 20, "PUSHOK")
ctx("pushok-push", D1, [(pushok, 5000, "acq", None, WL)], "TRANSFER_IN", signer=S_OTH, transfers=[(S_OTH, W, CA[pushok], 5000)])
ctx("pushok-self", D1 + 7200, [(pushok, -100, "move_out", None, WL), (pushok, 100, "move_in", None, W2L)], "TRANSFER_SELF", signer=W)
ctx("eth-refund", D1, [(eth, 0.5, "acq", None, WL)], "PROGRAM_IN", signer=W)
ctx("weth-claim", D1, [(weth, 1, "acq", None, WL)], "PROGRAM_IN", signer=W)
ctx("eth-pay", D2, [(eth, -0.1, "disp", 300, WL), (usdc, 300, "acq", 300, WL)], "SWAP", signer=W)
rcp, xrcp = asset("base", "0x" + "61" * 20, "RCP"), asset("base", "0x" + "62" * 20, "xRCP")
ctx("rcp-buy", D0, [(usdc, -1000, "disp", 1000, WL), (rcp, 1000, "acq", 1000, WL)], "SWAP", signer=W)
ctx("rcp-bridge", D1, [(xrcp, 1000, "move_in", None, WL), (rcp, -1000, "move_out", None, WL)], "BRIDGE", signer=W)
wlt = asset("base", "0x" + "71" * 20, "WLT")
ctx("wlt-push", D1, [(wlt, 700, "acq", None, WL)], "TRANSFER_IN", signer=S_WL, transfers=[(S_WL, W, CA[wlt], 700)])
tfw = asset("base", "0x" + "72" * 20, "TFW")
ctx("tfw-pull", D1, [(tfw, 300, "acq", None, WL)], "PROGRAM_IN", signer=W, transfers=[(S_WL, W, CA[tfw], 300)])
ovt = asset("base", "0x" + "73" * 20, "OVT")
ctx("ovt-claim", D1, [(ovt, 100, "acq", None, WL)], "PROGRAM_IN", signer=W)
rt = asset("base", "0x" + "81" * 20, "RT")
X_OUT = "0x" + "f9" * 20
ctx("rt-claim", D1, [(rt, 1000, "acq", None, WL)], "PROGRAM_IN", signer=W)
ctx("rt-out", D1 + 3600, [(rt, -600, "move_out", None, WL), (rt, 600, "move_in", None, f"out:base:{X_OUT}")], "TRANSFER_OUT", signer=W)
ctx("rt-back", D2, [(rt, 600, "acq", None, WL)], "PROGRAM_IN")
rts = asset("base", "0x" + "89" * 20, "RTS")
ctx("rts-claim", D1, [(rts, 1000, "acq", None, WL)], "PROGRAM_IN", signer=W)
ctx("rts-out", D1 + 3600, [(rts, -600, "move_out", None, WL), (rts, 600, "move_in", None, f"out:base:{X_OUT}")], "TRANSFER_OUT", signer=W)
ctx("rts-back", D2, [(rts, 600, "acq", None, WL)], "PROGRAM_IN", signer=W)
bro, broa = asset("base", "0x" + "8a" * 20, "BRO"), asset("arbitrum", "0x" + "8b" * 20, "BRO")
ctx("bro-claim", D1, [(bro, 1000, "acq", None, WL)], "PROGRAM_IN", signer=W)
ctx("bro-bridge", D1 + DAY, [(bro, -1000, "move_out", None, WL)], "BRIDGE", signer=W)
ctx("bro-arrive", D1 + DAY + 30000, [(broa, 1000, "acq", None, WAL)], "TRANSFER_IN", signer=W, chain="arbitrum")
brm, brma = asset("base", "0x" + "8c" * 20, "BRM"), asset("arbitrum", "0x" + "8d" * 20, "BRM")
ctx("brm-claim", D1, [(brm, 1000, "acq", None, WL)], "PROGRAM_IN", signer=W)
ctx("brm-bridge", D1 + DAY, [(brm, -1000, "move_out", None, WL)], "BRIDGE", signer=W)
ctx("brm-arrive", D1 + DAY + 600, [(brma, 1000, "acq", None, WAL)], "TRANSFER_IN", signer=W, chain="arbitrum")
ctx("brm-claim2", D2, [(brma, 100, "acq", None, WAL)], "PROGRAM_IN", signer=W, chain="arbitrum")
gasx = asset("base", "0x" + "8e" * 20, "GASX")
ctx("gasx-claim", D1 + 100, [(gasx, 100, "acq", None, WL), (eth, 0.01, "acq", None, WL), (eth, -0.001, "gas", 2.0, WL)], "PROGRAM_IN", signer=W)
buyr = asset("base", "0x" + "8f" * 20, "BUYR")
ctx("buyr-buy", D1, [(usdc, -100, "disp", 100, WL), (buyr, 100, "acq", 100, WL)], "SWAP", signer=W)
ctx("buyr-out", D1 + 3600, [(buyr, -100, "move_out", None, WL), (buyr, 100, "move_in", None, f"out:base:{X_OUT}")], "TRANSFER_OUT", signer=W)
ctx("buyr-back", D2, [(buyr, 100, "acq", None, WL)], "PROGRAM_IN", signer=W)
selfc = asset("base", "0x" + "91" * 20, "SELFC")
ctx("selfc-claim", D1, [(selfc, 100, "acq", None, WL)], "PROGRAM_IN", signer=W)
ctx("selfc-self", D1 + 3600, [(selfc, -50, "move_out", None, WL), (selfc, 50, "move_in", None, W2L)], "TRANSFER_SELF", signer=W)
ctx("selfc-claim2", D2, [(selfc, 100, "acq", None, WL)], "PROGRAM_IN", signer=W)
sbr, sbra = asset("base", "0x" + "92" * 20, "SBR"), asset("arbitrum", "0x" + "93" * 20, "SBR")
ctx("sbr-claim", D1, [(sbr, 1000, "acq", None, WL)], "PROGRAM_IN", signer=W)
ctx("sbr-arrive", D1 + DAY + 30000, [(sbra, 1000, "acq", None, WAL)], "TRANSFER_IN", signer=W, chain="arbitrum")
xca = asset("arbitrum", "0x" + "94" * 20, "XCA")
XCA_TX = h("xca-arrive")
ctx("xca-arrive", D1, [(xca, 1000, "acq", None, WAL)], "TRANSFER_IN", signer=W, tx=XCA_TX, chain="arbitrum")
ext, bext = asset("base", "0x" + "82" * 20, "EXT"), asset(None, "binance:EXT", "EXT", None, 8, "exchange_currency")
ctx("ext-claim", D1, [(ext, 100, "acq", None, WL)], "PROGRAM_IN", signer=W)
ctx("ext-out", D1 + 600, [(ext, -100, "move_out", None, WL), (ext, 100, "move_in", None, f"out:base:{X_OUT}")], "TRANSFER_OUT", signer=W)
ctx("ext-buy", D1 + 1200, [(usdc, -100, "disp", 100, WL), (ext, 100, "acq", 100, WL)], "SWAP", signer=W)
TE = ctx("ext-out2", D1 + 1800, [(ext, -100, "move_out", None, WL)], "TRANSFER_OUT_EX", signer=W)
ex_in("binance", "EXT-D", bext, 100, TE, D1 + 3000)
leg("exchange", "binance:trade", "binance:EXTUSDT:1", 0, D2, bext, BNL, -100, "disp", "EXF_SELL", 1000)
leg("exchange", "binance:trade", "binance:EXTUSDT:1", 1, D2, busdt, BNL, 1000, "acq", "EXF_SELL", 1000)
ret = asset("base", "0x" + "83" * 20, "RET")
X_RET = "0x" + "f8" * 20
ctx("ret-claim", D1, [(ret, 100, "acq", None, WL)], "PROGRAM_IN", signer=W)
ctx("ret-out", D1 + 600, [(ret, -100, "move_out", None, WL), (ret, 100, "move_in", None, f"out:base:{X_RET}")], "TRANSFER_OUT", signer=W)
ctx("ret-back1", D1 + DAY, [(ret, 40, "acq", None, WL)], "PROGRAM_IN", signer=X_RET, transfers=[(X_RET, W, CA[ret], 40)])
ctx("ret-back2", D1 + 2 * DAY, [(ret, 60, "acq", None, WL)], "PROGRAM_IN", signer=X_RET, transfers=[(X_RET, W, CA[ret], 60)])
ctx("ret-sell", D2, [(ret, -100, "disp", 1000, WL), (usdc, 1000, "acq", 1000, WL)], "SWAP", signer=W)
wf, bwf, wfa = asset("base", "0x" + "84" * 20, "WF"), asset(None, "binance:WF", "WF", None, 8, "exchange_currency"), asset("arbitrum", "0x" + "85" * 20, "WF")
ctx("wf-claim", D1, [(wf, 100, "acq", None, WL)], "PROGRAM_IN", signer=W)
ctx("wf-buy", D1 + 600, [(usdc, -100, "disp", 100, WL), (wf, 100, "acq", 100, WL)], "SWAP", signer=W)
TWF = ctx("wf-out", D1 + 1200, [(wf, -200, "move_out", None, WL)], "TRANSFER_OUT_EX", signer=W)
ex_in("binance", "WF-D", bwf, 200, TWF, D1 + 3000)
TWA = h("wf-arrive")
leg("exchange", "binance:withdraw", "WF-W", 0, D1 + 2 * DAY, bwf, BNL, -200, "move_out", "EXF_WITHDRAW")
raw("binance", "withdraw", "WF-W", {"currency": "WF", "amount": "198", "fee": "2", "state": "DONE", "txid": TWA}, D1 + 2 * DAY)
ctx("wf-arrive", D1 + 2 * DAY + 600, [(wfa, 198, "acq", None, WAL)], "TRANSFER_IN", tx=TWA, chain="arbitrum")
ctx("wf-sell", D2, [(wfa, -198, "disp", 198, WAL), (usdc_a, 198, "acq", 198, WAL)], "SWAP", signer=W, chain="arbitrum")
ret2 = asset("base", "0x" + "86" * 20, "RET2")
X_RET2 = "0x" + "f7" * 20
ctx("ret2-claim", D1, [(ret2, 100, "acq", None, WL)], "PROGRAM_IN", signer=W)
ctx("ret2-out1", D1 + 600, [(ret2, -40, "move_out", None, WL), (ret2, 40, "move_in", None, f"out:base:{X_RET2}")], "TRANSFER_OUT", signer=W)
ctx("ret2-out2", D1 + 1200, [(ret2, -60, "move_out", None, WL), (ret2, 60, "move_in", None, f"out:base:{X_RET2}")], "TRANSFER_OUT", signer=W)
ctx("ret2-back", D1 + DAY, [(ret2, 100, "acq", None, WL)], "PROGRAM_IN", signer=X_RET2, transfers=[(X_RET2, W, CA[ret2], 100)])
ctx("ret2-sell", D2, [(ret2, -100, "disp", 1000, WL), (usdc, 1000, "acq", 1000, WL)], "SWAP", signer=W)
solt = asset("sol", "HarvSoLMintToken333333333333333333333333333", "SOLT", None, 9)
TSOL = "5SoLtxSignature" + "a" * 50
leg("chain_tx", "sol", TSOL, 0, D1, solt, f"wallet:sol:{WS}", 100, "acq", "TRANSFER_IN")
con.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES (?,?,?,'{}',5)", ("sol", TSOL, "TRANSFER_IN"))
con.execute("INSERT INTO raw_txs (chain, txhash, block, ts, snapshot, wallets, ingested_at) VALUES (?,?,?,?,?,'[]',0)",
            ("sol", TSOL, 1, D1, json.dumps({"kind": "sol_tx", "fee_payer": S_SOL, "fee_payer_mine": False, "counterparties": [S_SOL], "deltas": [{"delta": 100}]})))
tront = asset("tron", NE.TOK["tron"], "TRONT", None, 6)
TTRON = "tron-tx-" + "d" * 56
leg("chain_tx", "tron", TTRON, 0, D1, tront, f"wallet:tron:{MYT_KEY}", 100, "acq", "TRANSFER_IN")
con.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES (?,?,?,'{}',5)", ("tron", TTRON, "TRANSFER_IN"))
TA = ("token", NE.TOK["tron"], "TRONT", 6)
con.execute("INSERT INTO raw_txs (chain, txhash, block, ts, snapshot, wallets, ingested_at) VALUES (?,?,?,?,?,?,0)",
            ("tron", TTRON, 100, D1, json.dumps(NE.rec("tron", TTRON, D1, deltas=[(MYT_KEY, TA, 100 * 10 ** 6)], owners=[MYT_KEY],
                                                       moves=[(TA, S_TRON_KEY, MYT_KEY, 100 * 10 ** 6)])), json.dumps([MYT_KEY])))
btcw = asset("btc", None, "BTC", None, 8, "native")
TBTC = "e5" * 32
leg("chain_tx", "btc", TBTC, 0, D1, btcw, f"wallet:btc:{BTC_KEY}", 1.0, "acq", "TRANSFER_IN")
con.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES (?,?,?,'{}',5)", ("btc", TBTC, "TRANSFER_IN"))
con.execute("INSERT INTO raw_txs (chain, txhash, block, ts, snapshot, wallets, ingested_at) VALUES (?,?,?,?,?,?,0)",
            ("btc", TBTC, 100, D1, json.dumps(NE.rec("btc", TBTC, D1, deltas=[(BTC_KEY, "native", 10 ** 8)], owners=[BTC_KEY],
                                                     moves=[("native", BTC_WL, BTC_KEY, 10 ** 8)])), json.dumps([BTC_KEY])))
hvo, bhvo, hvoa = asset("base", "0x" + "87" * 20, "HVO"), asset(None, "binance:HVO", "HVO", None, 8, "exchange_currency"), asset("arbitrum", "0x" + "88" * 20, "HVO")
ctx("hvo-claim", D1, [(hvo, 150, "acq", None, WL)], "PROGRAM_IN", signer=W)
THV = ctx("hvo-out", D1 + 600, [(hvo, -50, "move_out", None, WL)], "TRANSFER_OUT_EX", signer=W)
ex_in("binance", "HVO-D", bhvo, 50, THV, D1 + 3000)
THA = h("hvo-arrive")
leg("exchange", "binance:withdraw", "HVO-W", 0, D1 + 2 * DAY, bhvo, BNL, -50, "move_out", "EXF_WITHDRAW")
raw("binance", "withdraw", "HVO-W", {"currency": "HVO", "amount": "50", "fee": "0", "state": "DONE", "txid": THA}, D1 + 2 * DAY)
ctx("hvo-arrive", D1 + 2 * DAY + 600, [(hvoa, 50, "acq", None, WAL)], "TRANSFER_IN", tx=THA, chain="arbitrum")
pos = {}
for a, loc, qb in con.execute("SELECT asset_id, location, qty_base FROM postings WHERE location NOT LIKE 'out:%'"):
    pos[(GID[a], loc)] = pos.get((GID[a], loc), 0) + int(qb) / 10 ** DEC[a]
for (g, loc), q in pos.items():
    con.execute("INSERT OR REPLACE INTO positions (group_id, location, qty_norm, qty_unknown_norm, cost_alloc_usd) VALUES (?,?,?, '0', '0')",
                (g, loc, format(q, ".12f")))
con.commit()
con.close()

LIQ = {good: 2.0, mix: 2.0, h2p: 1.0, mv: 3.0, mu: 3.0, mv3: 1.0, mixf: 10.0, feec: 10.0, cc: 3.0, gp: 0.5, dust: 1.0, dust2: 1.0, pushok: 0.5, ext: 10.0, ret: 10.0,
       wf: 1.0, ret2: 10.0, hvo: 1.0, rts: 1.0, bro: 1.0, brm: 1.0, gasx: 0.1, buyr: 1.0, selfc: 1.0, sbr: 1.0}
LIQ_A = {mv3a: 1.0, wfa: 1.0, hvoa: 10.0, broa: 1.0, brma: 1.0, sbra: 1.0, xca: 1.0}
px = {"ETH": 3000.0, "USDT": 1.0, "USDC": 1.0, "BTC": 60000.0, "MV": 3.0, "MU": 3.0, "MV3": 1.0, "MIXF": 10.0, "FEEC": 10.0, "CC": 3.0}
dex_keys = {**{f"base:{CA[a]}": v for a, v in LIQ.items()}, **{f"arbitrum:{CA[a]}": v for a, v in LIQ_A.items()}}
json.dump({"usd": px, "usd_ts": {k: TS for k in px}, "rate": 1400.0, "updated": TS,
           "dex_usd": dex_keys, "dex_ts": {k: TS for k in dex_keys}, "dex_res": {k: 50000.0 for k in dex_keys}, "dex_res_ts": {k: TS for k in dex_keys},
           "fx_basis": 1400.0, "ex_usd": {f"binance:{k}": v for k, v in px.items() if k != "MU"} | {"upbit:MU": 3.0, "upbit:MIXF": 10.0},
           "ex_ts": {f"binance:{k}": TS for k in px} | {"upbit:MU": TS, "upbit:MIXF": TS}},
          open(paths.state("spot.json"), "w"))
DC = {good: 1.5, mix: 1.0, h2p: 1.0, mv: 2.0, mu: 2.0, mv3: 1.0, mixf: 10.0, feec: 10.0, cc: 2.0, dust: 1.0, gp: 0.5, pushok: 0.5, ext: 10.0, ret: 10.0, wf: 1.0, ret2: 10.0, rts: 1.0, bro: 1.0, brm: 1.0, gasx: 0.1, buyr: 1.0, selfc: 1.0, sbr: 1.0}
json.dump({"_v": 1, "fx": None, "calls": [],
           "s": {f"ca:base:{CA[a]}": {"st": "ok", "lo": iso(D0), "hi": iso(NOW), "p": {iso(D1): v}, "src": ["test"], "at": TS} for a, v in DC.items()}},
          open(paths.state("daily_close_px.json"), "w"))
json.dump({f"base:{CA[gp]}": {"ts": TS, "risk": {"strong": True, "label": "스캠 확증 is_honeypot"}},
           f"arbitrum:{CA[hvoa]}": {"ts": TS, "risk": {"strong": True, "label": "스캠 확증 is_honeypot"}}}, open(paths.state("goplus_cache.json"), "w"))

json.dump({"v": 1, "arr": {f"arbitrum|{XCA_TX}": {"proto": "wormhole", "status": "nolink"}}}, open(os.path.join(paths.STATE_DIR, "xchain_cache.json"), "w"))
with open(paths.state("pending_dm.jsonl"), "w", encoding="utf-8") as f9:
    f9.write(json.dumps({"kind": "TRANSFER_OUT", "event_ts": D1 + DAY, "payload": {"deltas": {str(sbr): str(-1000 * 10 ** 18)}, "to": "0x" + "f6" * 20}}) + "\n")
import statefile  # noqa: E402
import web  # noqa: E402
import accounting_harvest  # noqa: E402

G1 = {"gid": 1, "sym": "AAA", "qty_known": Decimal(0), "qty_unknown": Decimal(100), "is_stable": False, "is_fiat": False}
G2 = {"gid": 2, "sym": "BBB", "qty_known": Decimal(0), "qty_unknown": Decimal(0), "is_stable": False, "is_fiat": False}
hvu = accounting_harvest.HarvestBook({}, None, fs_on=True)


class _Row(dict):
    def __getitem__(self, k):
        return dict.get(self, k)


hvu.recv(G1, _Row(event="PROGRAM_IN", leg_kind="acq", kind="token", location="wallet:base:x", source_ns="base", source_id="0xaa"), Decimal(100), D1, True, None)
hvu.move_out(G1, Decimal(100))
ent_u = {"sym": "AAA", "qty": Decimal(50), "known": Decimal(0), "unknown": Decimal(50), "left": Decimal(50), "gid": 1, "_cv": {"ratio": 0.5}}
hvu.attach(ent_u)
hvu.move_in(G2, ent_u, Decimal(1), Decimal("0.5"))
check("H8 교차 자산 전환(out_move 순서 · _cv 뒤 관찰) = 도착 단위 풀(50)에 환산 한 번 → 받는 그룹 50(origin 보존 · 추정)", hvu.groups[2]["free"] == {(1, "claim"): Decimal(50)} and not hvu.groups[1]["free"] and hvu.ledgers[(1, "claim")]["est"], (hvu.groups, hvu.ledgers))
G2["qty_unknown"] = Decimal(50)
hvu.sell(G2, Decimal(50), Decimal(1000), "2026-10-01")
check("H8 BBB 50 전량 $1,000 매도 = AAA 줄 판 금액 $1,000", hvu.ledgers[(1, "claim")]["usd"] == Decimal(1000) and hvu.ledgers[(1, "claim")]["sold"] == Decimal(50), hvu.ledgers[(1, "claim")])
G3 = {"gid": 3, "sym": "CCC", "qty_known": Decimal(0), "qty_unknown": Decimal(100), "is_stable": False, "is_fiat": False}
hvu.recv(G3, _Row(event="PROGRAM_IN", leg_kind="acq", kind="token", location="wallet:base:x", source_ns="base", source_id="0xcc"), Decimal(100), D1, True, None)
hvu.move_out(G3, Decimal(100))
G3["qty_unknown"] = Decimal(0)
G3["qty_known"] = Decimal(100)
hvu.move_out(G3, Decimal(100))
ent_z = {"gid": 3, "qty": Decimal(100), "known": Decimal(100), "unknown": Decimal(0)}
hvu.attach(ent_z)
G4 = {"gid": 4, "sym": "CCC", "qty_known": Decimal(0), "qty_unknown": Decimal(0), "is_stable": False, "is_fiat": False}
hvu.move_in(G4, ent_z, Decimal(1))
check("H8 무상 0 인 이동 항목 = '0' 등록 → 도착이 외부 송금 대기 줄을 못 가져감(받는 그룹 무상 0)", not (hvu.groups.get(4) or {}).get("free") and hvu.pending.get(3), (hvu.groups.get(4), hvu.pending.get(3)))
ret_e = {"qty": Decimal(100), "left": Decimal(100), "known": Decimal(0), "unknown": Decimal(100)}
G3["qty_known"] = Decimal(0)
hvu.move_in(G3, ret_e, Decimal("0.4"))
hvu.move_in(G3, ret_e, Decimal("0.6"))
check("H8 외부 송금 100 을 40 · 60 으로 나눠 돌려받음 = 잔량 유실 없이 100 복귀", hvu.groups[3]["free"] == {(3, "claim"): Decimal(100)}, hvu.groups[3]["free"])
G5 = {"gid": 5, "sym": "DDD", "qty_known": Decimal(0), "qty_unknown": Decimal(200), "is_stable": False, "is_fiat": False}
hvu.recv(G5, _Row(event="PROGRAM_IN", leg_kind="acq", kind="token", location="wallet:base:x", source_ns="base", source_id="0xdd"), Decimal(200), D1, True, None)
hvu.move_out(G5, Decimal(100))
G5["qty_unknown"] = Decimal(100)
ret5 = {"qty": Decimal(100), "left": Decimal(100), "known": Decimal(0), "unknown": Decimal(100)}
hvu.move_in(G5, ret5, Decimal("0.5"))
G5["qty_unknown"] = Decimal(150)
hvu.move_out(G5, Decimal(50))
G5["qty_unknown"] = Decimal(100)
ret5.update(qty=Decimal(100), left=Decimal(100), unknown=Decimal(100))
hvu.move_in(G5, ret5, Decimal(1))
check("H8 무상 200 → 100 송신 → 50 반환 → 50 추가 송신 → 100 반환 = 200 복원(기존 반환 항목에 새 출발 합산 · 추정)",
      hvu.groups[5]["free"] == {(5, "claim"): Decimal(200)} and hvu.ledgers[(5, "claim")]["est"], (hvu.groups[5], hvu.by_ent.get(id(ret5))))
G6 = {"gid": 6, "sym": "EEE", "qty_known": Decimal(100), "qty_unknown": Decimal(0), "is_stable": False, "is_fiat": False}
hvu.move_out(G6, Decimal(100))
G6["qty_known"] = Decimal(0)
hvu.recv(G6, _Row(event="PROGRAM_IN", leg_kind="acq", kind="token", location="wallet:base:x", source_ns="base", source_id="0xee"), Decimal(100), D1, True, None)
G6["qty_unknown"] = Decimal(100)
hvu.move_out(G6, Decimal(100))
G6["qty_unknown"] = Decimal(0)
ret6 = {"qty": Decimal(200), "left": Decimal(200), "known": Decimal(100), "unknown": Decimal(100)}
hvu.move_in(G6, ret6, Decimal("0.5"))
check("H8 매수 100 + 무상 100 을 같은 곳에 보내고 100 돌려받음 = 무상 몫 50 만 복원(무상 0 송신도 분모 보존 · 혼합 = 추정)",
      hvu.groups[6]["free"] == {(6, "claim"): Decimal(50)} and hvu.ledgers[(6, "claim")]["est"], (hvu.groups[6], hvu.by_ent.get(id(ret6))))


def build(prefs):
    statefile.atomic_write_json(paths.state("ui_prefs.json"), dict({"plans": {}, "ignored": []}, **prefs))
    b = web.StateBuilder()
    b.skip_gen_check = True
    sp = b.spot
    sp._ex_done = {"upbit", "binance", "bybit", "okx", "gate", "kucoin", "bithumb"}
    sp._gt_done = set(getattr(sp, "_gt_done", set()) or set()) | {("base", CA[a]) for a in LIQ} | {("arbitrum", CA[a]) for a in LIQ_A}
    b.px.candle_usd = lambda sym, ms: None
    b.px.d.setdefault("neg_ts", {})["_fx"] = time.time()
    conn = dbm.open_db(paths.DB_PATH, readonly=True)
    try:
        f = b._build(conn)["fields"]
    finally:
        conn.close()
    return b, f


OV = {f"g{GID[ovt]}": {"mode": "unit", "unit": 1.0}}
b, f = build({"src_whitelist": WLIST, "cost_overrides": OV})
check("빌드 성공", bool(f), "fields 없음")
idx = b._day_idx or {}
hv = idx.get("harvest") or {}
rows_all = hv.get("rows") or []
if os.environ.get("TJ_TEST_VERBOSE"):
    for r in rows_all:
        print("  ", r["cls"], r["sym"], r["kind"], "n", r["n"], "recv", r["recv"], "recvUsd", r["recvUsd"], r["pxSrc"], "sold", r["sold"], r["soldUsd"], "left", r["left"], r["leftUsd"],
              "gas", r["gas"], "est", r["est"], "conv", r["conv"], "reason", r["reason"][:40])
by = {r["sym"]: r for r in rows_all if r["kind"] != "push"}
byp = {r["sym"]: r for r in rows_all if r["kind"] == "push"}
syms = {r["sym"] for r in rows_all}
bykey = {r["key"]: r for r in rows_all}
api = accounting_harvest.api(idx, "")
ok = {r["sym"]: r for r in api.get("rows") or []}
fold = {k: {r["sym"]: r for r in v} for k, v in (api.get("fold") or {}).items()}
quar = set(getattr(b, "_risk_quarantined", None) or ())

g1 = ok.get("GOOD")
check("H1 클레임 1,000 = 정상 줄 · 종류 클레임 · 1건", g1 and g1["kind"] == "claim" and g1["n"] == 1 and abs(g1["recv"] - 1000) < 1e-6, g1)
check("H1 400 + 100 매도 $1,000 = 판 금액 $1,000 · 2건 · 남음 500 · 추정 아님", g1 and abs(g1["sold"] - 500) < 1e-6 and abs(g1["soldUsd"] - 1000) < 0.01 and g1["soldN"] == 2 and abs(g1["left"] - 500) < 1e-6 and not g1["est"], g1)
check("H1 지금 가치 = 500 × DEX $2 = $1,000 · 클레임 가스 $2 1건", g1 and abs(g1["leftUsd"] - 1000) < 0.01 and abs(g1["gas"] - 2.0) < 0.01 and g1["gasN"] == 1, g1)
check("H1 최초 인식 가치 $1.5 × 1,000 = $1,500 · 출처 close · 단가 재료 pxQty 1,000", g1 and abs(g1["recvUsd"] - 1500) < 0.01 and g1["pxSrc"] == "close" and g1["pxN"] == 1 and abs(g1["pxQty"] - 1000) < 1e-6, g1)
g2 = ok.get("MIX")
check("H2 실매수 + 클레임 섞임 = 판 몫 500 · 판 금액 $1,000 · 남음 500 · '추정'", g2 and abs(g2["sold"] - 500) < 1e-6 and abs(g2["soldUsd"] - 1000) < 0.01 and abs(g2["left"] - 500) < 1e-6 and g2["est"], g2)
g2p, g2pp = ok.get("H2P"), (fold.get("push") or {}).get("H2P")
check("H2 클레임 10 + 남이 보낸 1,000(같은 그룹) → 505 매도 = 정상 줄은 클레임 몫만(받음 10 · 판 5 · $5 · 남음 5 · 가치 $5 · 추정 아님)",
      g2p and g2p["kind"] == "claim" and g2p["n"] == 1 and abs(g2p["recv"] - 10) < 1e-6 and abs(g2p["sold"] - 5) < 1e-6 and abs(g2p["soldUsd"] - 5) < 0.01
      and abs(g2p["left"] - 5) < 1e-6 and abs(g2p["leftUsd"] - 5) < 0.01 and not g2p["est"], g2p)
check("H2 남이 보낸 1,000 몫은 수령 행 단위로 '받음 — 출처 확인' 접힘(받음 1,000 · 판 500 · $500 · 남음 500 · 가치 0 · 같은 그룹 키 · 다른 줄 키)",
      g2pp and g2pp["kind"] == "push" and abs(g2pp["recv"] - 1000) < 1e-6 and abs(g2pp["sold"] - 500) < 1e-6 and abs(g2pp["soldUsd"] - 500) < 0.01
      and abs(g2pp["left"] - 500) < 1e-6 and g2pp["leftUsd"] == 0 and g2pp["gkey"] == g2p["gkey"] and g2pp["key"] != g2p["key"], g2pp)
g3 = ok.get("MV")
check("H3 지갑 수령 → 바이낸스 입금 → 매도 = 판 금액 $2,997(순수령 · 수수료 $3 차감) · 남음 0", g3 and abs(g3["soldUsd"] - 2997) < 0.01 and abs(g3["sold"] - 1000) < 1e-6 and abs(g3["left"]) < 1e-6, g3)
g3u = ok.get("MU")
check("H3' 업비트(정산액이 이미 순액) = 같은 판 금액 $2,997", g3u and abs(g3u["soldUsd"] - 2997) < 0.01 and abs(g3u["left"]) < 1e-6, g3u)
check("H3 받은 누계는 이동으로 안 는다(MV 1,000 · 1건)", g3 and abs(g3["recv"] - 1000) < 1e-6 and g3["n"] == 1, g3)
g33 = ok.get("MV3")
check("H3'' 지갑 → 바이낸스 → 출금 → 아비트럼 지갑 → 매도(세 그룹 연쇄) = 최초 수령 줄에 판 금액 $1,000 · 남음 0", g33 and abs(g33["soldUsd"] - 1000) < 0.01 and abs(g33["sold"] - 1000) < 1e-6 and abs(g33["left"]) < 1e-6 and g33["n"] == 1, g33)
g34 = ok.get("MIXF")
check("H3''' 무상 100(바이낸스) · 실매수 100(업비트) 따로 보낸 두 송금 = 안 섞임 → 판 금액 $1,000(바이낸스 몫만) · 판 100", g34 and abs(g34["soldUsd"] - 1000) < 0.01 and abs(g34["sold"] - 100) < 1e-6, g34)
g35 = ok.get("FEEC")
check("H3'''' 수수료 자산으로 전부 소진된 무상 몫 = 뒤 실매수 매도에 안 붙음(판 금액 $0 · 판 0)", g35 and abs(g35["soldUsd"]) < 0.01 and abs(g35["sold"]) < 1e-6 and abs(g35["left"]) < 1e-6, g35)
g36 = ok.get("CC")
check("H3''''' 코인↔코인 교환 매도도 수수료 차감 = $2,997", g36 and abs(g36["soldUsd"] - 2997) < 0.01, g36)
g37 = ok.get("EXT")
check("H3 무상 100 외부 송금 뒤 실매수 100 을 거래소로 → 매도 $1,000 = 수확 $0(무상 0 송금이 외부 송금 몫을 못 가져감) · 받음 100", g37 and abs(g37["soldUsd"]) < 0.01 and abs(g37["sold"]) < 1e-6 and abs(g37["recv"] - 100) < 1e-6, g37)
g38 = ok.get("RET")
check("H3 외부 주소로 보낸 100 을 40·60 으로 돌려받고(돌아온 코인 승계) 전량 매도 = 수확 $1,000 · 받음 100(되돌림은 새 수령 아님)", g38 and abs(g38["soldUsd"] - 1000) < 0.01 and abs(g38["sold"] - 100) < 1e-6 and abs(g38["recv"] - 100) < 1e-6 and g38["n"] == 1, g38)
g39 = ok.get("WF")
check("H3 무상 100 + 매수 100 → 출금 수수료 2 → 198 매도 $198 = 수확 $99(수수료로 소진된 무상 몫은 안 넘어감 · 추정)", g39 and abs(g39["soldUsd"] - 99) < 0.01 and abs(g39["sold"] - 99) < 1e-6 and g39["est"], g39)
g40 = ok.get("RET2")
check("H3 같은 주소로 40·60 두 번 보내고 100 을 한 번에 돌려받음(반환 풀 합침) = 수확 $1,000 · 받음 100", g40 and abs(g40["soldUsd"] - 1000) < 0.01 and abs(g40["sold"] - 100) < 1e-6 and abs(g40["recv"] - 100) < 1e-6 and g40["n"] == 1, g40)
g41 = ok.get("HVO")
check("H3 목적지(아비트럼) 허니팟 확증 = 그 몫(50) 가치 0 · 남은 가치 = base 100 × $1 = $100 · 격리 보관 수량 표식 50", g41 and abs(g41["leftUsd"] - 100) < 0.01 and abs(g41["left"] - 150) < 1e-6 and abs(g41["leftHid"] - 50) < 1e-6 and g41["cls"] == "ok", g41)
check("H5 솔라나 화이트리스트 지갑(대소문자 구분) → 내 솔라나 지갑 100 = 받음 0(보드 밖)", "SOLT" not in syms, by.get("SOLT"))
check("H5 Tron 화이트리스트 지갑(base58) → 내 Tron 지갑 TRC-20 100(이동 증거 hex 키) = 받음 0(보드 밖)", "TRONT" not in syms, by.get("TRONT"))
check("H5 BTC 화이트리스트 주소(주소 그대로) → 내 BTC 지갑 1 BTC(이동 증거 from = 실제 주소 · 원장 키 = 지갑 id) = 받음 0(보드 밖)", "BTC" not in syms, [r for r in rows_all if r["sym"] == "BTC"])
sc = fold.get("scam") or {}
check("H4 사칭(보이지 않는 글자) = 격리 접힘 · 사유 '사칭'", "USD​T" in sc and "사칭" in sc["USD​T"]["reason"], sc.get("USD​T"))
check("H4 유사 글자(키릴 Т) = 격리 접힘 · 사유 '사칭'", "USDТ" in sc and "사칭" in sc["USDТ"]["reason"], sc.get("USDТ"))
check("H4 확인 필요(글자 그대로 USDT · 정품 CA 아님) = 격리 접힘 · 사유 '확인 필요'", "USDT" in sc and sc["USDT"]["reason"].startswith("확인 필요"), sc.get("USDT"))
check("H4 고플러스 확증 × 자기전송 = 보유표는 안 숨기지만(격리 집합 밖) 보드는 격리 · 사유 '고플러스'", "HPOT" in sc and "고플러스" in sc["HPOT"]["reason"] and GID[gp] not in quar, (sc.get("HPOT"), GID[gp] in quar))
check("H4 주소 오염 초소액(단가 있음 · $0.001) = 격리 · 가치 0", "DUST" in sc and "주소 오염" in sc["DUST"]["reason"] and sc["DUST"]["leftUsd"] == 0, sc.get("DUST"))
check("H4 주소 오염 초소액(최초 인식 단가 없음 → 지금 시세 $0.002) = 격리", "DUST2" in sc and "주소 오염" in sc["DUST2"]["reason"] and sc["DUST2"]["pxN"] == 0, sc.get("DUST2"))
check("H4 격리 여섯은 정상 줄에 없다", not any(s in ok for s in ("USD​T", "USDТ", "USDT", "HPOT", "DUST", "DUST2")), sorted(ok))
su = fold.get("suspect") or {}
check("H5 남이 보낸 시세 없는 토큰 = 의심 접힘 · 가치 0 · 정상 줄 아님", "SUSP" in su and su["SUSP"]["leftUsd"] == 0 and "SUSP" not in ok, su.get("SUSP"))
pu = fold.get("push") or {}
check("H5 남이 보낸 유동성 토큰(자기전송 허용) = '받음 확인' 접힘 · 정상 줄 아님 · 가치 0", "PUSHOK" in pu and "PUSHOK" not in ok and pu["PUSHOK"]["leftUsd"] == 0 and "원가 지정" in pu["PUSHOK"]["reason"], pu.get("PUSHOK"))
na = fold.get("native") or {}
check("H5 네이티브 그룹(ETH 환불 0.5 + WETH 1건) = 네이티브 접힘 · 정상 줄 아님 · 판 0(스왑 지불 밖)", "ETH" in na and na["ETH"]["n"] == 3 and "ETH" not in ok and na["ETH"]["soldN"] == 0 and na["ETH"]["soldUsd"] == 0, na.get("ETH"))
check("H5 브릿지 양수 레그(TRANSFER_IN 재작성)는 보드 밖", "xRCP" not in syms and "RCP" not in syms, sorted(syms))
check("H5 화이트리스트 발신 = 남이 서명(WLT) · 내가 서명한 인출(TFW) 둘 다 보드 밖", "WLT" not in syms and "TFW" not in syms, [s for s in ("WLT", "TFW") if s in syms])
check("H5 사용자 원가 지정 유입(OVT) = 무상 아님 → 보드 밖", "OVT" not in syms, by.get("OVT"))
ok_gids = {int(r["gkey"][1:]) for r in api.get("rows") or []}
check("H6 보유표에서 숨긴(격리) 그룹 ∩ 보드 정상 줄 = 0", not (ok_gids & quar), sorted(ok_gids & quar))
check("H6 격리 집합의 수확 그룹은 모두 접힘(의심·격리)", all(int(r["gkey"][1:]) not in quar or r["cls"] in ("scam", "suspect") for r in rows_all), [(r["sym"], r["cls"]) for r in rows_all if int(r["gkey"][1:]) in quar])
tot = api.get("tot") or {}
EXP_SOLD = 1000 + 1000 + 5 + 2997 + 2997 + 1000 + 1000 + 0 + 2997 + 0 + 1000 + 99 + 1000
EXP_LEFT = 1000 + 1000 + 5 + 100 + 400 + 1000 + 100 + 10 + 200 + 1000
check("H6 합계(정상 줄만): 판 금액 = Σ 13줄 · 판 건수 12(GOOD 2) · 받음 건수 22 · 남은 가치 Σ · 가스 $4 2건(GOOD·GASX) · 접힘 판 금액 = H2P 받음 몫 $500 1건 · 정상 21종",
      abs(tot.get("soldUsd", 0) - EXP_SOLD) < 0.05 and tot.get("soldN") == 12 and tot.get("recvN") == 22 and abs(tot.get("leftUsd", 0) - EXP_LEFT) < 0.05
      and abs(tot.get("gasUsd", 0) - 4) < 0.01 and tot.get("gasN") == 2
      and abs(tot.get("soldHidUsd", 0) - 500) < 0.01 and tot.get("soldHidN") == 1 and tot.get("est") is True and api["n"]["ok"] == 21, (tot, api["n"]))
p2 = accounting_harvest.api(idx, f"since={iso(D2)}")
pk = {r["sym"]: r for r in p2.get("rows") or []}
check("H7 since = 매도 날 → GOOD 받음 0 · 판 금액 $1,000 · 같은 날 2건 · 남음 그대로", "GOOD" in pk and pk["GOOD"]["n"] == 0 and abs(pk["GOOD"]["recv"]) < 1e-9 and abs(pk["GOOD"]["soldUsd"] - 1000) < 0.01 and pk["GOOD"]["soldN"] == 2 and abs(pk["GOOD"]["left"] - 500) < 1e-6, pk.get("GOOD"))
check("H7 since = 매도 날 → 가격 확인 수량·건수도 기간 안 것만(GOOD pxQty 0 · pxN 0) · since = 수령 날 → 1,000 · 1", pk["GOOD"]["pxQty"] == 0 and pk["GOOD"]["pxN"] == 0
      and abs({r["sym"]: r for r in accounting_harvest.api(idx, f"since={iso(D1)}").get("rows") or []}["GOOD"]["pxQty"] - 1000) < 1e-6, pk.get("GOOD"))
p3 = accounting_harvest.api(idx, f"since={iso(D2 + DAY)}")
check("H7 전부 뒤 = 빈 표 · 합계 0", not p3.get("rows") and all(not v for v in (p3.get("fold") or {}).values()) and p3["tot"]["soldUsd"] == 0, p3.get("n"))
check("H7 응답에 '_' 내부 칸 없음 · builtAt 있음 · ref.gasOn", api.get("builtAt") and not any(k.startswith("_") for r in (api.get("rows") or []) for k in r) and api["ref"]["gasOn"] is True, api.get("ref"))
tax = [r for r in (idx.get("tax") or []) if not r.get("fut") and r.get("tk") != "inc" and str(r.get("ex") or "") not in ("기타 비용(가스)", "스테이킹 보상")]
rz = sum(float(v or 0) for v in (f.get("realizedByDate") or {}).values())
tz = sum(float(r.get("_disp", r.get("disp")) or 0) - float(r.get("_acq", r.get("acq")) or 0) - float(r.get("fee") or 0) for r in tax)
check("H8 실현 합(realizedByDate) ≈ 명세 Σ(양도 − 취득 − 수수료) − 가스 비용 $4(GOOD·GASX 클레임 가스 — 보드가 실현을 안 바꿈)", abs(rz - (tz - 4.0)) < 0.05, (round(rz, 2), round(tz, 2)))
check("H8 응답(fields)에 harvest 키 없음(가벼운 상태 무변) · 빌드 색인에만", "harvest" not in f and isinstance(hv.get("rows"), list), sorted(k for k in f if "harv" in k))
r9 = by.get("RT")
check("H9 켬: 외부로 보냈다 들어온 600 = 돌아온 코인 보류(받음 1,000 · 반환 판정 없음 0)", r9 and abs(r9["recv"] - 1000) < 1e-6 and r9["retUnk"] == 0, r9)
b2, f2 = build({"src_whitelist": WLIST, "cost_overrides": OV, "first_seen_px": False, "risk_overrides": {f"g{GID[pushok]}": "visible"}})
hv2 = (b2._day_idx or {}).get("harvest") or {}
by2 = {r["sym"]: r for r in hv2.get("rows") or [] if r["kind"] != "push"}
byp2 = {r["sym"]: r for r in hv2.get("rows") or [] if r["kind"] == "push"}
r92, r92p = by2.get("RT"), byp2.get("RT")
check("H9 끔: 같은 600 이 새 수령으로 — 클레임 줄 1,000 그대로 + 받음 줄 600(남이 보냄 · '반환 판정 없음' 1 · 추정) · ref.fsOn False",
      r92 and abs(r92["recv"] - 1000) < 1e-6 and r92["retUnk"] == 0 and r92p and abs(r92p["recv"] - 600) < 1e-6 and r92p["retUnk"] == 1 and r92p["est"]
      and r92p["cls"] != "ok" and hv2["ref"]["fsOn"] is False, (r92, r92p, hv2.get("ref")))
bykey2 = {r["key"]: r for r in hv2.get("rows") or []}
rs, rsp = bykey.get(f"g{GID[rts]}"), bykey.get(f"g{GID[rts]}p")
check("H9 켬: 내가 서명해 돌려받은 600 = 돌아온 코인 보류(정상 줄 받음 1,000 그대로 · 받음 줄 없음 · 남음은 보유 1,000 안)", rs and rs["cls"] == "ok" and abs(rs["recv"] - 1000) < 1e-6 and 0 < rs["left"] <= 1000 and rsp is None, (rs, rsp))
rs2, rsp2 = bykey2.get(f"g{GID[rts]}"), bykey2.get(f"g{GID[rts]}p")
check("H9 끔: 내가 서명해 돌려받은 600 = 반환 판정 없음 → 정상 줄 1,000 그대로(retUnk 0) + 받음 접힘 줄 600(retUnk 1 · 추정 · 사유 '돌아온') — 정상 합계에 안 들어감",
      rs2 and rs2["cls"] == "ok" and abs(rs2["recv"] - 1000) < 1e-6 and rs2["retUnk"] == 0 and rsp2 and rsp2["cls"] == "push" and abs(rsp2["recv"] - 600) < 1e-6
      and rsp2["retUnk"] == 1 and rsp2["est"] and "돌아온" in rsp2["reason"], (rs2, rsp2))
bo, boa, boap = bykey.get(f"g{GID[bro]}"), bykey.get(f"g{GID[broa]}"), bykey.get(f"g{GID[broa]}p")
check("H11 브릿지 출발 1,000 이 짝을 못 찾은 채 30,000초 뒤 서명 수령 = 도착 줄은 받음 접힘(brUnk 1 · brhist 1 · 가치 0 · 사유 '브릿지') · 클레임 줄 없음 · 출발 줄 정상(받음 1,000 · 남음 0)",
      boap and boap["cls"] == "push" and boap["brUnk"] == 1 and boap["brhist"] == 1 and abs(boap["recv"] - 1000) < 1e-6 and boap["leftUsd"] == 0 and "브릿지" in boap["reason"]
      and boa is None and bo and bo["cls"] == "ok" and abs(bo["recv"] - 1000) < 1e-6 and abs(bo["left"]) < 1e-6, (bo, boa, boap))
bm, bma, bmap = bykey.get(f"g{GID[brm]}"), bykey.get(f"g{GID[brma]}"), bykey.get(f"g{GID[brma]}p")
check("H11 브릿지 짝이 맞은 뒤(미짝 출발 없음) 같은 심볼 서명 클레임 100 = 정상(brhist 1 · brUnk 0) · 출발 줄 정상(남음 1,000 은 아비트럼에) · 받음 줄 없음",
      bma and bma["cls"] == "ok" and bma["brUnk"] == 0 and bma["brhist"] == 1 and abs(bma["recv"] - 100) < 1e-6 and abs(bma["left"] - 100) < 1e-6
      and bm and bm["cls"] == "ok" and abs(bm["left"] - 1000) < 1e-6 and bmap is None, (bm, bma, bmap))
sb_, sba, sbap = bykey.get(f"g{GID[sbr]}"), bykey.get(f"g{GID[sbra]}"), bykey.get(f"g{GID[sbra]}p")
check("H11 posting 없는 출발(pending_dm TRANSFER_OUT · to_dest 관찰)만 있는 심볼의 30,000초 뒤 서명 수령 = 짝 확인 불가 → 받음 접힘(brUnk 1 · brhist 1 · 가치 0) · 클레임 줄 없음 · 출발 쪽 클레임 정상",
      sbap and sbap["cls"] == "push" and sbap["brUnk"] == 1 and sbap["brhist"] == 1 and abs(sbap["recv"] - 1000) < 1e-6 and sbap["leftUsd"] == 0 and sba is None
      and sb_ and sb_["cls"] == "ok" and abs(sb_["recv"] - 1000) < 1e-6, (sb_, sba, sbap))
br_, brp = bykey.get(f"g{GID[buyr]}"), bykey.get(f"g{GID[buyr]}p")
check("H11 켬: 매수 100 외부 출발 뒤 서명 회수 = 돌아온 코인 보류(수확 줄 없음)", br_ is None and brp is None, (br_, brp))
br2, brp2 = bykey2.get(f"g{GID[buyr]}"), bykey2.get(f"g{GID[buyr]}p")
check("H11 끔: 매수 100(무상 0) 외부 출발 뒤 서명 회수 100 = 외부 출발 이력만으로 받음 접힘(retUnk 1 · 추정 · 클레임 줄 없음 · 정상 합계 밖)",
      br2 is None and brp2 and brp2["cls"] == "push" and brp2["retUnk"] == 1 and brp2["est"] and abs(brp2["recv"] - 100) < 1e-6, (br2, brp2))
sc_, sc2 = bykey.get(f"g{GID[selfc]}"), bykey2.get(f"g{GID[selfc]}")
check("H11 자기전송(내 지갑 간 50)은 외부 출발이 아님 — 켬·끔 모두 두 클레임 정상 200(retUnk 0 · 받음 줄 없음)",
      sc_ and sc2 and sc_["cls"] == "ok" and sc2["cls"] == "ok" and abs(sc_["recv"] - 200) < 1e-6 and abs(sc2["recv"] - 200) < 1e-6 and sc2["retUnk"] == 0
      and f"g{GID[selfc]}p" not in bykey2 and f"g{GID[selfc]}p" not in bykey, (sc_, sc2))
xa, xap = bykey.get(f"g{GID[xca]}"), bykey.get(f"g{GID[xca]}p")
check("H11 xchain 캐시가 브릿지 도착이라 확인한 서명 수령(출발은 원장 밖 · 출발 이력 없음) = 받음 접힘(xcArr 1 · brUnk 1 · brhist 1 · 가치 0 · 사유 '브릿지 도착') · 클레임 줄 없음",
      xap and xap["cls"] == "push" and xap["xcArr"] == 1 and xap["brUnk"] == 1 and xap["brhist"] == 1 and abs(xap["recv"] - 1000) < 1e-6 and xap["leftUsd"] == 0
      and "브릿지 도착" in xap["reason"] and xa is None, (xa, xap))
gx = bykey.get(f"g{GID[gasx]}")
check("H11 ETH 환급(네이티브 줄이 먼저 생김) + 토큰 클레임 같은 tx 가스 $2 = 클레임 줄에 귀속(GASX gas $2 1건 · 네이티브 ETH 줄 gas 0)",
      gx and gx["cls"] == "ok" and abs(gx["gas"] - 2) < 0.01 and gx["gasN"] == 1 and na.get("ETH") and na["ETH"]["gas"] == 0 and na["ETH"]["gasN"] == 0, (gx, na.get("ETH")))
check("H9 끔: 최초 인식 가치 없음(최초 인식 시가 쉼 → '—')", by2.get("GOOD") and by2["GOOD"]["pxN"] == 0 and by2["GOOD"]["recvUsd"] == 0, by2.get("GOOD"))
check("H9 사용자 '정상으로'(visible) = 받음 확인 줄이 정상 줄로", byp2.get("PUSHOK") and byp2["PUSHOK"]["cls"] == "ok" and byp2["PUSHOK"]["leftUsd"] > 0, byp2.get("PUSHOK"))
os.environ["TJ_HARVEST_OFF"] = "1"
try:
    b3, f3 = build({"src_whitelist": WLIST, "cost_overrides": OV})
finally:
    os.environ.pop("TJ_HARVEST_OFF", None)
b4, f4 = build({"src_whitelist": WLIST, "cost_overrides": OV})
VOLATILE = {"builtAt", "buildMs", "build_ms", "ph", "phases", "lastScan", "now", "serverNow", "ts", "elapsed"}
DIAG_VOLATILE = {"dex_age", "workers", "build_ms", "ph"}
ROW_VOLATILE = {"pxAge"}
dump = lambda v: json.dumps(v, sort_keys=True, ensure_ascii=False, default=str)   # noqa: E731


def _strip_rows(v):
    if isinstance(v, list) and all(isinstance(x, dict) for x in v):
        return [{s: w for s, w in x.items() if s not in ROW_VOLATILE} for x in v]
    return v


def _cmp_fields(fa, fb):
    out = []
    for k9 in sorted(set(fa) | set(fb)):
        if k9 in VOLATILE:
            continue
        a9, b9 = _strip_rows(fa.get(k9)), _strip_rows(fb.get(k9))
        if k9 == "_diag" and isinstance(a9, dict) and isinstance(b9, dict):
            a9 = {s: v for s, v in a9.items() if s not in DIAG_VOLATILE}
            b9 = {s: v for s, v in b9.items() if s not in DIAG_VOLATILE}
        if dump(a9) != dump(b9):
            out.append(k9)
            if os.environ.get("TJ_TEST_VERBOSE"):
                if isinstance(a9, dict) and isinstance(b9, dict):
                    print("  diff", k9, sorted(s for s in set(a9) | set(b9) if dump(a9.get(s)) != dump(b9.get(s)))[:20])
                elif isinstance(a9, list) and isinstance(b9, list) and all(isinstance(x, dict) for x in a9 + b9):
                    ka, kb = {str(x.get("key")): x for x in a9}, {str(x.get("key")): x for x in b9}
                    for s in sorted(set(ka) | set(kb)):
                        if dump(ka.get(s)) != dump(kb.get(s)):
                            print("  diff", k9, s, dump(ka.get(s))[:260], "|", dump(kb.get(s))[:260])
                else:
                    print("  diff", k9, dump(a9)[:300], "|", dump(b9)[:300])
    return out


diff_keys = _cmp_fields(f3, f4)
check("H10 훅 끔 ↔ 켬 빌드(같은 원장·설정·저장본) = 응답(fields) 전부 같음(시각·나이 칸 빼고) — 원가·수량·실현·명세·총자산·보유표 무변", not diff_keys, diff_keys[:12])
tax3, tax4 = (b3._day_idx or {}).get("tax") or [], (b4._day_idx or {}).get("tax") or []
check("H10 훅 끔 ↔ 켬 = 세금 명세 행 전부 같음 · 켬 보드는 다시 찼음", dump(tax3) == dump(tax4) and len(tax3) > 0 and len(((b4._day_idx or {}).get("harvest") or {}).get("rows") or []) == len(rows_all), (len(tax3), len(tax4)))
hv3 = (b3._day_idx or {}).get("harvest") or {}
check("H10 훅 끔 = 수확 보드 빈 표(훅 무동작 확인)", not hv3.get("rows"), len(hv3.get("rows") or []))
T.finish()
