#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import sqlite3
from datetime import datetime, timedelta

import histcurve
import wow2

chk = T.chk
NOW = datetime.now(wow2.KST)
TS = lambda n, h=12: int((NOW - timedelta(days=n)).replace(hour=h, minute=0, second=0, microsecond=0).timestamp())
D = lambda n: (NOW - timedelta(days=n)).strftime("%Y-%m-%d")
W1 = "0x" + "c4" * 20
DB = os.path.join(T.TMP, "ledger_wdfee.db")
c = sqlite3.connect(DB)
c.executescript("""
CREATE TABLE asset_groups (group_id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, norm_decimals INTEGER NOT NULL DEFAULT 18);
CREATE TABLE assets (asset_id INTEGER PRIMARY KEY, kind TEXT, chain TEXT, address TEXT, symbol TEXT, decimals INTEGER, confirmed INTEGER DEFAULT 0, hidden INTEGER DEFAULT 0, group_id INTEGER);
CREATE TABLE postings (posting_id INTEGER PRIMARY KEY AUTOINCREMENT, source_kind TEXT, source_ns TEXT, source_id TEXT, leg_seq INTEGER, event_ts INTEGER NOT NULL,
  asset_id INTEGER NOT NULL, location TEXT NOT NULL, qty_base TEXT NOT NULL, cost_usd TEXT, cost_krw TEXT, leg_kind TEXT NOT NULL, event TEXT NOT NULL, classifier_ver INTEGER);
CREATE TABLE raw_ex (exchange TEXT NOT NULL, kind TEXT NOT NULL, uuid TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL, observed_at INTEGER NOT NULL,
  PRIMARY KEY (exchange, kind, uuid, revision));
""")
c.executemany("INSERT INTO asset_groups(group_id, name) VALUES (?, ?)", [(1, "USDC#11"), (2, "USDC"), (3, "USDC#12"), (4, "USDC#13")])
c.executemany("INSERT INTO assets(asset_id, kind, chain, symbol, decimals, group_id) VALUES (?,?,?,?,?,?)", [
    (10, "exchange_currency", None, "USDC", 8, 1), (20, "token", "eth", "USDC", 6, 2), (30, "exchange_currency", None, "USDC", 8, 3),
    (40, "exchange_currency", None, "USDC", 8, 4)])
P = []


def post(ts, aid, loc, qty, dec, leg, ev, tx):
    P.append((ts, aid, loc, str(int(round(qty * 10 ** dec))), leg, ev, tx))


def raw(ex, uid, payload, t):
    c.execute("INSERT INTO raw_ex VALUES (?, 'withdraw', ?, 1, ?, ?)", (ex, uid, json.dumps(dict(payload, uuid=uid)), t))


post(TS(9, 9), 10, "exchange:upbit", 1000, 8, "acq", "EX_BUY", "ub1")
post(TS(8, 10), 10, "exchange:upbit", -1000, 8, "move_out", "EX_WITHDRAW", "uw1")
raw("upbit", "uw1", {"currency": "USDC", "amount": "995", "fee": "5", "state": "DONE", "txid": "0xa1"}, TS(8, 10))
post(TS(8, 11), 20, f"wallet:eth:{W1}", 995, 6, "acq", "TRANSFER_IN", "0xa1")
post(TS(7, 9), 30, "exchange:gate", 500, 8, "move_in", "EXF_DEPOSIT", "gd1")
post(TS(6, 10), 30, "exchange:gate", -500, 8, "move_out", "EXF_WITHDRAW", "gw1")
raw("gate", "gw1", {"currency": "USDC", "amount": "500", "fee": "2", "state": "DONE", "txid": "0xb1"}, TS(6, 10))
post(TS(5, 9), 40, "exchange:binance", 301, 8, "move_in", "EXF_DEPOSIT", "bd1")
post(TS(4, 10), 40, "exchange:binance", -300, 8, "move_out", "EXF_WITHDRAW", "bw1")
post(TS(4, 10), 40, "exchange:binance", -1, 8, "gas", "EXF_WD_FEE", "bw1")
raw("binance", "bw1", {"currency": "USDC", "amount": "300", "fee": "1", "state": "DONE", "txid": "0xc1"}, TS(4, 10))
post(TS(4, 11), 20, f"wallet:eth:{W1}", 300, 6, "acq", "TRANSFER_IN", "0xc1")
c.executemany("INSERT INTO postings(event_ts, asset_id, location, qty_base, leg_kind, event, source_id, source_kind, source_ns, leg_seq, classifier_ver)"
              " VALUES (?,?,?,?,?,?,?, 'x', 'x', 0, 1)", P)
c.commit()
c.close()


class PxHist:
    kit = {"groups": {g: {"sym": "USDC", "st": True, "lp": 1.0} for g in ("1", "2", "3", "4")}}
    px = {"specs": {}}

    def _clean(self, sp, specs):
        return sp


_orig = (histcurve.spec_of, histcurve.pmap_of)
histcurve.spec_of = lambda g: "stable" if g.get("st") else "sym:" + g["sym"]
histcurve.pmap_of = lambda sp, upto: {D(n): 1.0 for n in range(0, 40)}
FF = {"rate": 1380, "krwFlows": {"rows": [{"dir": "in", "amt": 1_380_000, "ex": "업비트", "st": "done", "t": TS(9, 8)}]},
      "stables": [{"sym": "USDC", "qty": 1295, "price": 1, "locs": [{"w": "메인 지갑", "ch": "Ethereum", "qty": 1295}]}],
      "gasByChain": [{"chain": "업비트 출금 수수료", "spot": 5, "lp": 0, "tx": 1, "kind": "exfee"},
                     {"chain": "게이트 출금 수수료", "spot": 2, "lp": 0, "tx": 1, "kind": "exfee"},
                     {"chain": "바이낸스 출금 수수료", "spot": 1, "lp": 0, "tx": 1, "kind": "exfee"}]}
try:
    conn = wow2._ro(DB)
    wow2._MEMO.clear()
    fl = wow2.flows(FF, conn=conn, chain_names={"eth": "Ethereum"}, hist=PxHist())
    L = {(l["s"], l["t"], l["kind"]): l["usd"] for l in fl["links"]}
    N = {n["id"]: n for n in fl["nodes"]}
    gl = {k: v for k, v in L.items() if k[2] in ("gain", "loss")}
    chk(abs(L.get(("ex:upbit", "ch:eth", "route"), 0) - 995) < 0.01, "W1 업비트 → 이더리움 = 실제로 보낸 995(수수료 5 는 이동액에 안 섞임)", L)
    chk(abs(L.get(("ex:upbit", "now:fee", "fee"), 0) - 5) < 0.01, "W1 업비트 수수료 · 가스 = 5(한 번)", L.get(("ex:upbit", "now:fee", "fee")))
    chk(not [k for k in gl if k[0] in ("ex:upbit", "ch:eth") or k[1] in ("ex:upbit", "ch:eth")],
        "W1 업비트 '늘어난 몫'·이더리움 '줄어든 몫' 가짜 없음", gl)
    chk(abs(L.get(("ex:gate", "now:sent", "sent"), 0) - 498) < 0.01 and abs(L.get(("ex:gate", "now:fee", "fee"), 0) - 2) < 0.01,
        "W2 게이트 밖으로 보냄 = 498 · 수수료 2(수수료가 보냄에 또 안 섞임)", {k: v for k, v in L.items() if "gate" in k[0]})
    chk(not [k for k in gl if "ex:gate" in k], "W2 게이트 '늘어난 몫' 가짜 없음", gl)
    chk(abs(L.get(("ex:binance", "ch:eth", "route"), 0) - 300) < 0.01 and abs(L.get(("ex:binance", "now:fee", "fee"), 0) - 1) < 0.01
        and not [k for k in gl if "ex:binance" in k], "W3 바이낸스(수수료 별도 레그) = 이동 300 · 수수료 1 · 마디 맞음", {k: v for k, v in L.items() if "binance" in k[0]})
    bal = all(abs(sum(l["usd"] for l in fl["links"] if l["t"] == nid) - sum(l["usd"] for l in fl["links"] if l["s"] == nid)) <= 0.01 for nid, n in N.items() if n["col"] in (1, 2))
    src = sum(l["usd"] for l in fl["links"] if N[l["s"]]["col"] == 0)
    dst = sum(l["usd"] for l in fl["links"] if N[l["t"]]["col"] == 3)
    chk(bal and abs(src - dst) < 0.05 and fl["totals"]["gain"] == 0 and fl["totals"]["loss"] == 0 and abs(fl["totals"]["fee"] - 8) < 0.01,
        "불변: 마디 들어온 = 나간 · 왼쪽 합 = 오른쪽 합 · 늘어난·줄어든 몫 0 · 수수료 합 8", (src, dst, fl["totals"]))
    fl0 = wow2.flows(dict(FF, gasByChain=[]), conn=conn, chain_names={"eth": "Ethereum"}, hist=PxHist())
    L0 = {(l["s"], l["t"], l["kind"]): l["usd"] for l in fl0["links"]}
    chk(abs(L0.get(("ex:upbit", "ch:eth", "route"), 0) - 995) < 0.01, "수수료 줄 없는 옛 응답도 이동액 = 보낸 수량(원장 원본 기준)", L0)
finally:
    histcurve.spec_of, histcurve.pmap_of = _orig

T.finish()
