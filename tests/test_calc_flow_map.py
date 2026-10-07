#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import os
import sqlite3
from datetime import datetime, timedelta

import histcurve
import wow2

chk = T.chk
TMP = T.TMP

NOW = datetime.now(wow2.KST)
TS = lambda n, h=12: int((NOW - timedelta(days=n)).replace(hour=h, minute=0, second=0, microsecond=0).timestamp())
D = lambda n: (NOW - timedelta(days=n)).strftime("%Y-%m-%d")
W1 = "0x" + "b2" * 20
DB = os.path.join(TMP, "ledger.db")
c = sqlite3.connect(DB)
c.executescript("""
CREATE TABLE asset_groups (group_id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, norm_decimals INTEGER NOT NULL DEFAULT 18);
CREATE TABLE assets (asset_id INTEGER PRIMARY KEY, kind TEXT, chain TEXT, address TEXT, symbol TEXT, decimals INTEGER, confirmed INTEGER DEFAULT 0, hidden INTEGER DEFAULT 0, group_id INTEGER);
CREATE TABLE postings (posting_id INTEGER PRIMARY KEY AUTOINCREMENT, source_kind TEXT, source_ns TEXT, source_id TEXT, leg_seq INTEGER, event_ts INTEGER NOT NULL,
  asset_id INTEGER NOT NULL, location TEXT NOT NULL, qty_base TEXT NOT NULL, cost_usd TEXT, cost_krw TEXT, leg_kind TEXT NOT NULL, event TEXT NOT NULL, classifier_ver INTEGER);
""")
c.executemany("INSERT INTO asset_groups(group_id, name) VALUES (?, ?)", [(1, "USDC#5"), (2, "USDC"), (3, "USDC#9"), (4, "ARB"), (5, "ARB#3"), (6, "OPX"), (7, "OPX#2")])
c.executemany("INSERT INTO assets(asset_id, kind, chain, symbol, decimals, group_id) VALUES (?,?,?,?,?,?)", [
    (10, "exchange_currency", None, "USDC", 8, 1), (20, "token", "eth", "USDC", 6, 2), (30, "token", "base", "USDC", 6, 3),
    (40, "token", "arbitrum", "ARB", 18, 4), (50, "token", "base", "ARB", 18, 5), (60, "token", "optimism", "OPX", 18, 6), (70, "token", "base", "OPX", 18, 7)])
P = []


def post(ts, aid, loc, qty, dec, leg, ev, tx):
    P.append((ts, aid, loc, str(int(round(qty * 10 ** dec))), leg, ev, tx))


post(TS(10, 9), 10, "exchange:upbit", 1000, 8, "acq", "EX_BUY", "u1")
post(TS(9, 10), 10, "exchange:upbit", -1000, 8, "move_out", "EX_WITHDRAW", "u2")
post(TS(9, 11), 20, f"wallet:eth:{W1}", 1000, 6, "acq", "TRANSFER_IN", "0xin1")
post(TS(8, 10), 20, f"wallet:eth:{W1}", -1000, 6, "move_out", "BRIDGE", "0xbr1")
post(TS(8, 10) + 900, 30, f"wallet:base:{W1}", 990, 6, "acq", "TRANSFER_IN", "0xarr1")
post(TS(6, 10), 40, f"wallet:arbitrum:{W1}", 100, 18, "acq", "TRANSFER_IN", "0xin2")
post(TS(5, 10), 40, f"wallet:arbitrum:{W1}", -100, 18, "move_out", "TRANSFER_OUT", "0xbr2")
post(TS(5, 10) + 1200, 50, f"wallet:base:{W1}", 96, 18, "acq", "PROGRAM_IN", "0xarr2")
post(TS(4, 9), 20, f"wallet:eth:{W1}", 200, 6, "acq", "TRANSFER_IN", "0xin3")
post(TS(3, 10), 20, f"wallet:eth:{W1}", -200, 6, "move_out", "BRIDGE", "0xbr3")
post(TS(4, 9), 40, f"wallet:arbitrum:{W1}", 10, 18, "acq", "TRANSFER_IN", "0xin4")
post(TS(3, 11), 40, f"wallet:arbitrum:{W1}", -10, 18, "move_out", "TRANSFER_OUT", "0xown1")
post(TS(3, 9), 60, f"wallet:optimism:{W1}", 50, 18, "acq", "TRANSFER_IN", "0xin5")
post(TS(2, 23), 60, f"wallet:optimism:{W1}", -50, 18, "move_out", "BRIDGE", "0xbr5")
post(TS(2, 23) + 7200, 70, f"wallet:base:{W1}", 50, 18, "acq", "TRANSFER_IN", "0xarr5")
c.executemany("INSERT INTO postings(event_ts, asset_id, location, qty_base, leg_kind, event, source_id, source_kind, source_ns, leg_seq, classifier_ver)"
              " VALUES (?,?,?,?,?,?,?, 'x', 'x', 0, 1)", P)
c.commit()
c.close()


class PxHist:
    kit = {"groups": {g: {"sym": s, "st": s == "USDC", "lp": 1.0 if s == "USDC" else 0.5} for g, s in (("1", "USDC"), ("2", "USDC"), ("3", "USDC"), ("4", "ARB"), ("5", "ARB"), ("6", "OPX"), ("7", "OPX"))}}
    px = {"specs": {}}

    def _clean(self, sp, specs):
        return sp


_orig = (histcurve.spec_of, histcurve.pmap_of)
histcurve.spec_of = lambda g: "stable" if g.get("st") else "sym:" + g["sym"]
histcurve.pmap_of = lambda sp, upto: ({D(n): (1.0 if n >= 2 else 0.9) for n in range(0, 40)} if sp == "sym:OPX" else {D(n): 0.5 for n in range(0, 40)})
CN = {"eth": "Ethereum", "base": "Base", "arbitrum": "Arbitrum"}
FF = {"rate": 1380, "krwFlows": {"rows": [{"dir": "in", "amt": 1_380_000, "ex": "업비트", "st": "done", "t": TS(10, 8)}]},
      "coins": [{"sym": "ARB", "price": 0.5, "locs": [{"w": "메인 지갑", "ch": "Base", "qty": 96}]}],
      "stables": [{"sym": "USDC", "qty": 1190, "price": 1, "locs": [{"w": "메인 지갑", "ch": "Base", "qty": 990}, {"w": "메인 지갑", "ch": "Ethereum", "qty": 0}]}],
      "outflows": [{"status": "bridge_matched", "usdAtSend": 50, "chains": ["arbitrum"], "txs": [{"ts": TS(5, 10), "tx": "0xBR2", "sym": "ARB", "qty": 100}]},
                   {"status": "own", "usdAtSend": 5, "chains": ["arbitrum"], "txs": [{"ts": TS(3, 11), "tx": "0xown1", "sym": "ARB", "qty": 10}]}]}
try:
    conn = wow2._ro(DB)
    wow2._MEMO.clear()
    fl = wow2.flows(FF, conn=conn, chain_names=CN, hist=PxHist())
    L = {(l["s"], l["t"], l["kind"]): l["usd"] for l in fl["links"]}
    N = {n["id"]: n for n in fl["nodes"]}
    chk(("in:coin", "ch:base", "coin_in") not in L, "F1 브릿지 도착은 '코인으로 받음' 아님(종전 999.5 두 번 셈)", {k: v for k, v in L.items() if k[2] == "coin_in"})
    chk(not any(k[1] == "now:loss" and k[0] == "ch:eth" for k in L), "F1 이더리움 '줄어든 몫' 없음(종전 1000)", {k: v for k, v in L.items() if k[2] == "loss"})
    chk(abs(L.get(("in:bridge", "ch:base", "bridge_in"), 0) - (990 + 48 + 45)) < 0.01 and abs(L.get(("ch:eth", "now:bridge", "bridge_out"), 0) - 990) < 0.01,
        "F1·F2 짝 = 다른 체인에서 옮겨 옴(Base) · 다른 체인으로 옮김(이더리움 · Arbitrum)", {k: v for k, v in L.items() if "bridge" in k[2]})
    chk(abs(L.get(("ch:arbitrum", "now:bridge", "bridge_out"), 0) - 48) < 0.01, "F2 보낸 내역 브릿지 판정 전송(TRANSFER_OUT · 해시 대소문자 무관)도 짝", L.get(("ch:arbitrum", "now:bridge", "bridge_out")))
    fee = next((l for l in fl["links"] if l["s"] == "ch:eth" and l["t"] == "now:fee"), None)
    chk(fee and abs(fee["usd"] - 10) < 0.01 and any(r["sym"] == "브릿지 수수료" for r in fee["rows"]), "F1 출발 − 도착 = 브릿지 수수료(수수료 · 가스 줄)", fee)
    chk(abs(L.get(("ch:eth", "now:unexpl", "unexpl"), 0) - 200) < 0.01 and abs(L.get(("ch:arbitrum", "now:unexpl", "unexpl"), 0) - 5) < 0.01,
        "F3 도착 못 찾은 브릿지·내 다른 지갑 = '설명 안 됨'(손실 아님)", {k: v for k, v in L.items() if k[2] in ("unexpl", "loss")})
    un = next(l for l in fl["links"] if l["kind"] == "unexpl" and l["s"] == "ch:arbitrum")
    chk(un["rows"][0]["note"] == "내 다른 지갑(추적 밖)", "F3 설명 안 됨 세부 = 이유(브릿지 도착 못 찾음 · 내 다른 지갑)", un["rows"])
    chk(N["now:unexpl"]["label"] == "설명 안 됨" and fl["totals"]["unexpl"] == 205.0 and fl["totals"]["bridgeN"] == 3, "F3 합계 unexpl · 브릿지 짝 수", fl["totals"])
    chk(fl["totals"].get("pxDay") == 1.0 and fl["totals"].get("pxNone") == 0, "7장 1 신뢰도: 이동 금액 중 그날 가격 비율(합성 = 전부 그날 가격)", (fl["totals"].get("pxDay"), fl["totals"].get("pxNone")))
    chk(not any(l["s"] == "ch:optimism" and l["t"] == "now:fee" for l in fl["links"]) and abs(L.get(("ch:optimism", "now:bridge", "bridge_out"), 0) - 45) < 0.01,
        "경계2 자정 넘긴 브릿지 시세 하락(50 → 50 · $1 → $0.9)은 수수료 아님(종전 $5 수수료)", {k: v for k, v in L.items() if "optimism" in k[0]})
    bal = all(abs(sum(l["usd"] for l in fl["links"] if l["t"] == nid) - sum(l["usd"] for l in fl["links"] if l["s"] == nid)) <= 1.0 for nid, n in N.items() if n["col"] in (1, 2))
    src = sum(l["usd"] for l in fl["links"] if N[l["s"]]["col"] == 0)
    dst = sum(l["usd"] for l in fl["links"] if N[l["t"]]["col"] == 3)
    chk(bal and abs(src - dst) < 0.05, "F4 마디 들어온 = 나간 · 왼쪽 합 = 오른쪽 합", (src, dst))
finally:
    histcurve.spec_of, histcurve.pmap_of = _orig

T.finish()
