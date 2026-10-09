#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import hashlib
import json
import os
import shutil
import time
from datetime import datetime, timedelta, timezone

W = "0x" + "cd" * 20
DAY = 86400
NOW = int(time.time())
KST = timezone(timedelta(hours=9))
shutil.copytree(os.path.join(T.ROOT, "seed"), os.path.join(T.TMP, "seed"), dirs_exist_ok=True)
json.dump({"wallets": [{"type": "evm", "chain": "base", "address": W, "label": "w"}, {"type": "evm", "chain": "arbitrum", "address": W, "label": "w"}],
           "backfill_months": 3, "chains": {}}, open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
os.environ["TJ_REPLAY_DEBUG"] = "1"
import common

assert T.TMP in common.STATE_DIR
import db as dbm


def check(name, ok, detail=""):
    T.chk(bool(ok), name, None if ok else detail)


def h(tag):
    return "0x" + hashlib.sha256(tag.encode()).hexdigest()


def iso(ts):
    return datetime.fromtimestamp(ts, KST).strftime("%Y-%m-%d")


con = dbm.open_db(os.path.join(common.STATE_DIR, "ledger.db"))
ST = {"aid": 0, "pid": 0}
DEC, GID = {}, {}


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
    return a


def leg(chain, tx, seq, ts, a, qty, lk, ev, cost=None):
    ST["pid"] += 1
    con.execute("INSERT INTO postings (posting_id, source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd,"
                " cost_krw, leg_kind, event, classifier_ver) VALUES (?,'chain_tx',?,?,?,?,?,?,?,?,NULL,?,?,5)",
                (ST["pid"], chain, tx, seq, ts, a, f"wallet:{chain}:{W}", str(int(round(qty * 10 ** DEC[a]))), None if cost is None else repr(float(cost)),
                 lk, ev))


def ctx(chain, tag, ts, legs, ev):
    t9 = h(tag)
    for i, (a, q, lk, c) in enumerate(legs):
        leg(chain, t9, i, ts, a, q, lk, ev, c)
    con.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES (?,?,?,'{}',5)", (chain, t9, ev))
    return t9


ub = asset("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", "USDC", 6)
ua = asset("arbitrum", "0xaf88d065e77c8cc2239327c5edb3a432268e5831", "USDC", "USDC", 6)
ctx("base", "fund", NOW - 200 * DAY, [(ub, 100000, "acq", 100000)], "PROGRAM_IN")
ctx("arbitrum", "funda", NOW - 200 * DAY, [(ua, 100000, "acq", 100000)], "PROGRAM_IN")
EXP = {}
D = NOW - 150 * DAY
a1, c1, b1 = asset("base", "0x" + "11" * 20, "NIA"), asset("base", "0x" + "12" * 20, "NIC"), asset("base", "0x" + "13" * 20, "NIB")
ctx("base", "n1-ba", D - 7200, [(ub, -3000, "disp", 3000), (a1, 1000, "acq", 3000)], "SWAP")
ctx("base", "n1-bc", D - 3600, [(ub, -1000, "disp", 1000), (c1, 500, "acq", 1000)], "SWAP")
ctx("base", "n1-x", D, [(a1, -1000, "disp", None), (c1, -500, "disp", None), (b1, 200, "acq", None)], "SWAP")
ctx("base", "n1-sb", D + DAY, [(b1, -200, "disp", 6000), (ub, 6000, "acq", 6000)], "SWAP")
N1 = D + DAY
D = NOW - 140 * DAY
a2, b2, c2 = asset("base", "0x" + "21" * 20, "NOA"), asset("base", "0x" + "22" * 20, "NOB"), asset("base", "0x" + "23" * 20, "NOC")
ctx("base", "n2-ba", D - 3600, [(ub, -3000, "disp", 3000), (a2, 1000, "acq", 3000)], "SWAP")
ctx("base", "n2-x", D, [(a2, -1000, "disp", None), (b2, 100, "acq", None), (c2, 300, "acq", None)], "SWAP")
ctx("base", "n2-sb", D + DAY, [(b2, -100, "disp", 3500), (ub, 3500, "acq", 3500)], "SWAP")
ctx("base", "n2-sc", D + DAY + 60, [(c2, -300, "disp", 3500), (ub, 3500, "acq", 3500)], "SWAP")
N2 = D + DAY
D = NOW - 130 * DAY
eb = asset("base", None, "ETH", None, 18, "native")
a3, b3 = asset("base", "0x" + "31" * 20, "NDA"), asset("base", "0x" + "32" * 20, "NDB")
ctx("base", "n3-ba", D - 3600, [(ub, -3000, "disp", 3000), (a3, 1000, "acq", 3000)], "SWAP")
ctx("base", "n3-x", D, [(a3, -1000, "disp", None), (b3, 100, "acq", None), (eb, 0.001, "acq", None)], "SWAP")
ctx("base", "n3-sb", D + DAY, [(b3, -100, "disp", 6000), (ub, 6000, "acq", 6000)], "SWAP")
N3, N3X = D + DAY, D
D = NOW - 120 * DAY
a4, b4 = asset("base", "0x" + "41" * 20, "NSA"), asset("base", "0x" + "42" * 20, "NSB")
ctx("base", "n4-ba", D - 3600, [(ub, -3000, "disp", 3000), (a4, 1000, "acq", 3000)], "SWAP")
ctx("base", "n4-x", D, [(a4, -1000, "disp", None), (b4, 100, "acq", None), (ub, 10, "acq", None)], "SWAP")
ctx("base", "n4-sb", D + DAY, [(b4, -100, "disp", 6000), (ub, 6000, "acq", 6000)], "SWAP")
N4 = D + DAY
D = NOW - 115 * DAY
a4b, b4b = asset("base", "0x" + "43" * 20, "NUA"), asset("base", "0x" + "44" * 20, "NUB")
ctx("base", "n4b-in", D - 7200, [(a4b, 500, "acq", None)], "TRANSFER_IN")
ctx("base", "n4b-ba", D - 3600, [(ub, -1500, "disp", 1500), (a4b, 500, "acq", 1500)], "SWAP")
ctx("base", "n4b-x", D, [(a4b, -1000, "disp", None), (b4b, 100, "acq", None), (ub, 10, "acq", None)], "SWAP")
ctx("base", "n4b-sb", D + DAY, [(b4b, -100, "disp", 6000), (ub, 6000, "acq", 6000)], "SWAP")
N4B = D + DAY
D = NOW - 110 * DAY
ea = asset("arbitrum", None, "ETH", None, 18, "native")
a5, b5 = asset("arbitrum", "0x" + "51" * 20, "NCA"), asset("arbitrum", "0x" + "52" * 20, "NCB")
ctx("arbitrum", "n5-ba", D - 3600, [(ua, -100, "disp", 100), (a5, 1000, "acq", 100)], "SWAP")
ctx("arbitrum", "n5-x", D, [(a5, -1000, "disp", None), (b5, 100, "acq", None), (ea, 0.1, "acq", None)], "SWAP")
ctx("arbitrum", "n5-sb", D + DAY, [(b5, -100, "disp", 500), (ua, 500, "acq", 500)], "SWAP")
N5 = D + DAY
D = NOW - 105 * DAY
ep = asset("base", None, "ETH", None, 18, "native")
ska, gvb = asset("base", "0x" + "91" * 20, "SKA"), asset("base", "0x" + "92" * 20, "GVB")
ctx("base", "p1-buy", D - 3600, [(ub, -2000, "disp", 2000), (ep, 1, "acq", 2000)], "SWAP")
ctx("base", "p1-x", D, [(ep, -1, "disp", 2500), (ska, 1, "acq", None), (gvb, 1, "acq", None)], "SWAP")
ctx("base", "p1-s", D + DAY, [(ska, -1, "disp", 2000), (ub, 2000, "acq", 2000)], "SWAP")
P1, P1S = D, D + DAY
D = NOW - 102 * DAY
px2, py2 = asset("base", "0x" + "93" * 20, "PXA"), asset("base", "0x" + "94" * 20, "PYA")
ctx("base", "p2-bx", D - 7200, [(ub, -1000, "disp", 1000), (px2, 100, "acq", 1000)], "SWAP")
ctx("base", "p2-by", D - 3600, [(ub, -500, "disp", 500), (py2, 100, "acq", 500)], "SWAP")
ctx("base", "p2-x", D, [(px2, -100, "disp", None), (py2, -100, "disp", None), (ub, 1800, "acq", 1800)], "SWAP")
P2 = D
ZV = ["base:0x" + "a7" * 20, "base:0x" + "a8" * 20, "base:0x" + "a9" * 20, "base:0x" + "aa" * 20]
os.makedirs(os.path.join(common.STATE_DIR, "seed_local"), exist_ok=True)
json.dump({"tokens": ZV}, open(os.path.join(common.STATE_DIR, "seed_local", "zero_value_companions.json"), "w"))
D = NOW - 98 * DAY
ez = asset("base", None, "ETH", None, 18, "native")
skz, gvz = asset("base", "0x" + "96" * 20, "SKZ"), asset("base", "0x" + "a7" * 20, "GVZ")
ctx("base", "z1-buy", D - 3600, [(ub, -2000, "disp", 2000), (ez, 1, "acq", 2000)], "SWAP")
ctx("base", "z1-x", D, [(ez, -1, "disp", 2500), (skz, 1, "acq", None), (gvz, 1, "acq", None)], "SWAP")
ctx("base", "z1-s", D + DAY, [(skz, -1, "disp", 2600), (ub, 2600, "acq", 2600)], "SWAP")
Z1, Z1S = D, D + DAY
D = NOW - 97 * DAY
az2, bz2, cz2 = asset("base", "0x" + "97" * 20, "ZTA"), asset("base", "0x" + "98" * 20, "ZTB"), asset("base", "0x" + "a8" * 20, "GVY")
ctx("base", "z2-ba", D - 3600, [(ub, -3000, "disp", 3000), (az2, 1000, "acq", 3000)], "SWAP")
ctx("base", "z2-x", D, [(az2, -1000, "disp", None), (bz2, 100, "acq", None), (cz2, 1000, "acq", None)], "SWAP")
ctx("base", "z2-sb", D + DAY, [(bz2, -100, "disp", 3500), (ub, 3500, "acq", 3500)], "SWAP")
Z2 = D + DAY
D = NOW - 96 * DAY
rz3, xz3, gz3 = asset("base", "0x" + "99" * 20, "RCX"), asset("base", "0x" + "9a" * 20, "xRCX"), asset("base", "0x" + "a9" * 20, "GVX")
ctx("base", "z3-buy", D - 3600, [(ub, -1000, "disp", 1000), (rz3, 1000, "acq", 1000)], "SWAP")
ctx("base", "z3-dep", D, [(gz3, 1000, "move_in", None), (rz3, -1000, "move_out", None), (xz3, 1000, "move_in", None)], "BRIDGE")
ctx("base", "z3-sell", D + DAY, [(xz3, -1000, "disp", 1500), (ub, 1500, "acq", 1500)], "SWAP")
Z3 = D + DAY
D = NOW - 87 * DAY
eg = asset("base", None, "ETH", None, 18, "native")
gvg, skg = asset("base", "0x" + "aa" * 20, "GVG"), asset("base", "0x" + "9b" * 20, "SKG")
ctx("base", "g1-buy", D - 3600, [(ub, -2008, "disp", 2008), (eg, 1.004, "acq", 2008)], "SWAP")
ctx("base", "g1-x", D, [(gvg, 1, "acq", None), (skg, 1, "acq", None), (eg, -1, "disp", 2500), (eg, -0.004, "gas", 10)], "SWAP")
ctx("base", "g1-s", D + DAY, [(skg, -1, "disp", 2600), (ub, 2600, "acq", 2600)], "SWAP")
G1, G1S = D, D + DAY
D = NOW - 93 * DAY
ev1 = asset("base", None, "ETH", None, 18, "native")
bv1, fb1 = asset("base", "0x" + "9c" * 20, "BVA"), asset("base", "0x" + "9d" * 20, "BTC")
ctx("base", "v1-buy", D - 3600, [(ub, -2000, "disp", 2000), (ev1, 1, "acq", 2000)], "SWAP")
ctx("base", "v1-x", D, [(ev1, -1, "disp", 2000), (bv1, 1, "acq", None), (fb1, 1, "acq", None)], "SWAP")
ctx("base", "v1-s", D + DAY, [(bv1, -1, "disp", 2500), (ub, 2500, "acq", 2500)], "SWAP")
V1 = D + DAY
D = NOW - 92 * DAY
av2, bv2, fb2 = asset("base", "0x" + "9e" * 20, "AVB"), asset("base", "0x" + "9f" * 20, "BVB"), asset("base", "0x" + "8e" * 20, "BTC")
ctx("base", "v2-ba", D - 3600, [(ub, -3000, "disp", 3000), (av2, 1000, "acq", 3000)], "SWAP")
ctx("base", "v2-x", D, [(av2, -1000, "disp", None), (bv2, 100, "acq", None), (fb2, 1, "acq", None)], "SWAP")
ctx("base", "v2-s", D + DAY, [(bv2, -100, "disp", 3500), (ub, 3500, "acq", 3500)], "SWAP")
V2 = D + DAY
D = NOW - 85 * DAY
av3 = asset("base", "0x" + "8f" * 20, "AVC")
wv3 = asset("base", "0x4200000000000000000000000000000000000006", "WETH")
bv3 = asset("base", "0x0555e30da8f98308edb960aa94c0db47230d2b9c", "WBTC", None, 8)
ctx("base", "v3-ba", D - 3600, [(ub, -2000, "disp", 2000), (av3, 1000, "acq", 2000)], "SWAP")
ctx("base", "v3-x", D, [(av3, -1000, "disp", None), (wv3, 0.25, "acq", None), (bv3, 0.025, "acq", None)], "SWAP")
D = NOW - 100 * DAY
r1, x1 = asset("base", "0x" + "61" * 20, "RCQ"), asset("base", "0x" + "62" * 20, "xRCQ")
ctx("base", "r1-buy", D - 3600, [(ub, -1000, "disp", 1000), (r1, 1000, "acq", 1000)], "SWAP")
ctx("base", "r1-dep", D, [(r1, -1000, "move_out", None), (x1, 990, "move_in", None)], "BRIDGE")
ctx("base", "r1-sell", D + DAY, [(x1, -990, "disp", 1500), (ub, 1500, "acq", 1500)], "SWAP")
R1 = D + DAY
D = NOW - 95 * DAY
r2, x2, en2 = asset("base", "0x" + "63" * 20, "RCZ"), asset("base", "0x" + "64" * 20, "xRCZ"), asset("base", None, "ETH", None, 18, "native")
ctx("base", "r2-buy", D - 3600, [(ub, -1000, "disp", 1000), (r2, 1000, "acq", 1000)], "SWAP")
ctx("base", "r2-dep", D, [(en2, 0.0001, "move_in", None), (r2, -1000, "move_out", None), (x2, 1000, "move_in", None)], "BRIDGE")
ctx("base", "r2-sell", D + DAY, [(x2, -1000, "disp", 1500), (ub, 1500, "acq", 1500)], "SWAP")
R2 = D + DAY
F = {}
for tag, arr, d0 in (("F1", 999, NOW - 90 * DAY), ("F2", 950, NOW - 80 * DAY)):
    fb9 = asset("base", "0x" + ("71" if tag == "F1" else "81") * 20, "FB" + tag[1])
    fa9 = asset("arbitrum", "0x" + ("72" if tag == "F1" else "82") * 20, "FB" + tag[1])
    ctx("base", f"{tag}-buy", d0 - 3600, [(ub, -1000, "disp", 1000), (fb9, 1000, "acq", 1000)], "SWAP")
    ctx("base", f"{tag}-br", d0, [(fb9, -1000, "move_out", None)], "BRIDGE")
    ctx("arbitrum", f"{tag}-arr", d0 + 600, [(fa9, arr, "acq", None)], "TRANSFER_IN")
    ctx("arbitrum", f"{tag}-sell", d0 + DAY, [(fa9, -arr, "disp", 1500), (ua, 1500, "acq", 1500)], "SWAP")
    F[tag] = (d0, d0 + DAY, 1000 - arr)
pos = {}
for a, loc, qb in con.execute("SELECT asset_id, location, qty_base FROM postings"):
    pos[(GID[a], loc)] = pos.get((GID[a], loc), 0) + int(qb) / 10 ** DEC[a]
for (g, loc), q in pos.items():
    con.execute("INSERT OR REPLACE INTO positions (group_id, location, qty_norm, qty_unknown_norm, cost_alloc_usd) VALUES (?,?,?, '0', '0')",
                (g, loc, format(q, ".12f")))
con.commit()
con.close()

import acct_norm
import pricing
import web


def _no_price(url, *a, **k):
    raise OSError("시험: 시세 받기 없음")


pricing._gj = _no_price
PX = {"ETH": 2000.0, "BTC": 60000.0, "WETH": 2000.0, "WBTC": 60000.0}
acct_norm.FxBook.candle = lambda self, sym, ts: PX.get(str(sym or "").upper())
web._fx_candle_near = lambda fxb, sym, ts, within_s=3600: PX.get(str(sym or "").upper())
web.Spot.dex_pending = lambda self, c, ca: False
web.Spot.ex_pending = lambda self, ex: False
web.Spot.price = lambda self, sym, *a, **k: None


def build(gas_on):
    common.atomic_write_json(web.PREFS_PATH, {"gas_in_cost": gas_on})
    b = web.StateBuilder()
    web.BUILDER = b
    st = T.safe(b.build)
    f = (st or {}).get("fields") or {} if isinstance(st, dict) else {}
    check(f"빌드 성공(가스 비용 {'켬' if gas_on else '끔'})", bool(f), st if isinstance(st, dict) and st.get("_exc") else "fields 없음")
    return f


def rbd_of(f):
    return {k: float(v) for k, v in (f.get("realizedByDate") or {}).items()}


def day(f, ts):
    return round(rbd_of(f).get(iso(ts), 0.0), 2)


def span(f, lo, hi):
    return round(sum(v for k, v in rbd_of(f).items() if iso(lo) <= k <= iso(hi)), 2)


def cards_of(f):
    return f.get("_positionsAll") or f.get("positions") or []


def pend_of(f, sym, pre=("unv:", "unkh:", "noproc:", "unvlost:")):
    return [p for p in (f.get("pendings") or []) if p.get("sym") == sym and str(p.get("key") or "").startswith(pre)]


def evs(f, sym):
    return [str(e.get("d")) for p in cards_of(f) if p.get("sym") == sym for e in (p.get("events") or [])]


def card(f, gid):
    return [p for p in cards_of(f) if p.get("_gid") == gid]


def invariants(f, tag):
    tot = round(sum(rbd_of(f).values()), 2)
    cs = round(sum(float(p.get("realized") or 0) + float(p.get("realizedFb") or 0) for p in cards_of(f)), 2)
    check(f"{tag} 불변: 헤더 실현 합 = 카드 실현 합", abs(tot - cs) <= 0.05, (tot, cs))
    tn = round(sum(float(r.get("_disp", r.get("disp")) or 0) - float(r.get("_acq", r.get("acq")) or 0) - float(r.get("_fee", r.get("fee")) or 0)
                   for r in f.get("_taxRowsAll") or []), 2)
    check(f"{tag} 불변: 세금 명세 Σ(양도 − 취득 − 수수료) = 헤더 실현 합", abs(tot - tn) <= 0.05, (tot, tn))
    return tot


fon = build(True)
foff = build(False)
check("N1 two_in A + C → B · B 매도 = +$2,000 · 검토 없음", abs(day(fon, N1) - 2000) <= 0.05 and not pend_of(fon, "NIB"), (day(fon, N1), pend_of(fon, "NIB")))
check("N2 two_out A → B + C · 합 +$4,000 · 받은 쪽 '추정'", abs(day(fon, N2) - 4000) <= 0.05 and any("추정" in d for d in evs(fon, "NOB") + evs(fon, "NOC")),
      (day(fon, N2), evs(fon, "NOB")))
check("N3 네이티브 잔돈(0.001 ETH · $2,000) = 시가 $2 만 · B 원가 $2,998 → B 매도 +$3,002", abs(day(fon, N3) - 3002) <= 0.05, (day(fon, N3), evs(fon, "NDB")))
e3 = [p for p in cards_of(fon) if p.get("_gid") == GID[eb] or (p.get("sym") == "ETH" and "Base" in json.dumps(p.get("chains") or p.get("chain") or "", ensure_ascii=False))]
e3c = [round(float(p.get("cost") or p.get("costUsd") or 0), 2) for p in card(fon, GID[eb])]
check("N3 잔돈 ETH 카드 원가 = $2(종전 균등 = $1,500)", e3c and abs(sum(e3c) - 2) <= 0.05, (e3c, [(p.get("sym"), p.get("cost"), p.get("qty")) for p in e3]))
check("N3 받은 시세 없는 코인이 하나뿐 = '추정' 아님", not any("추정" in d for d in evs(fon, "NDB")), evs(fon, "NDB"))
check("N4 스테이블 잔돈 USDC 10 = 액면 $10 · B 원가 $2,990 → B 매도 +$3,010", abs(day(fon, N4) - 3010) <= 0.05, (day(fon, N4), evs(fon, "NSB")))
check("N4b 절반 원가 미상 처분 + 스테이블 잔돈 → B 원가 확인 50개 = $1,490 → 매도 확인분 +$1,510", abs(day(fon, N4B) - 1510) <= 0.05, (day(fon, N4B), evs(fon, "NUB")))
check("N4b 스테이블 잔돈 = 원가 미상 수량 없음(검토 줄 없음)", not pend_of(fon, "USDC", ("unv:", "unkh:", "noproc:", "unvlost:", "fs", "un")),
      [p for p in (fon.get("pendings") or []) if p.get("sym") == "USDC"])
e5c = [round(float(p.get("cost") or 0), 2) for p in card(fon, GID[ea])]
check("N5 시세 있는 쪽 시가($200) > 넘긴 원가($100) → ETH 원가 $100 · B 원가 0 → B 매도 +$500", abs(day(fon, N5) - 500) <= 0.05 and e5c and abs(sum(e5c) - 100) <= 0.05,
      (day(fon, N5), e5c))
check("P1 한쪽만 시가: ETH 처분 +$500(그날) · 받은 두 코인 원가 = $2,500 균등 추정 → SKA 매도 $2,000 = +$750",
      abs(day(fon, P1) - 500) <= 0.05 and abs(day(fon, P1S) - 750) <= 0.05, (day(fon, P1), day(fon, P1S), evs(fon, "SKA")))
gvc = [round(float(p.get("cost") or 0), 2) for p in card(fon, GID[gvb])]
check("P1 GVB 원가 $1,250 · 원가 미상 0 · '추정' 표시", gvc and abs(sum(gvc) - 1250) <= 0.05
      and not any(float(p.get("unknownQty") or 0) > 1e-9 for p in card(fon, GID[gvb])) and any("추정" in d for d in evs(fon, "GVB")),
      (gvc, [(p.get("unknownQty"), p.get("events")) for p in card(fon, GID[gvb])]))
check("P2 거울: 낸 쪽 둘 다 시세 없음 · 받은 USDC 1,800 → 정산액 균등 추정 = 실현 −$100 + $400 = +$300 · 대금 미상 검토 없음",
      abs(day(fon, P2) - 300) <= 0.05 and not [p for p in (fon.get("pendings") or []) if str(p.get("key") or "").startswith("noproc:")]
      and any("추정" in d for d in evs(fon, "PXA")), (day(fon, P2), [p for p in (fon.get("pendings") or []) if str(p.get("key") or "").startswith("noproc:")], evs(fon, "PXA")))
zl = common.seed_json("zero_value_companions.json", {}, base_dir=common.BASE_DIR) or {}
check("Z 목록 = 공개 seed(govBNB) + 이 설치 덧붙임 합집합", "bsc:0x0000000000000000000000000000000000002005" in (zl.get("tokens") or [])
      and all(z in (zl.get("tokens") or []) for z in ZV), zl)


def zcard(gid):
    c9 = card(fon, gid)
    return [(round(float(p.get("cost") or 0), 2), float(p.get("unknownQty") or 0)) for p in c9]


check("Z1 한쪽만 시가 + 동반 토큰 → 증서 SKZ 원가 $2,500 전부 → $2,600 매도 = +$100 · '추정' 아님",
      abs(day(fon, Z1) - 500) <= 0.05 and abs(day(fon, Z1S) - 100) <= 0.05 and not any("추정" in d for d in evs(fon, "SKZ")),
      (day(fon, Z1), day(fon, Z1S), evs(fon, "SKZ")))
check("Z1 동반 GVZ = 원가 0 확인(원가 미상 0)", zcard(GID[gvz]) and all(abs(c) <= 0.005 and u <= 1e-9 for c, u in zcard(GID[gvz])), (zcard(GID[gvz]), evs(fon, "GVZ")))
check("Z2 양쪽 시세 없음 + 동반 토큰 → B 원가 $3,000 전부 → $3,500 매도 = +$500 · 동반 GVY 원가 0 확인",
      abs(day(fon, Z2) - 500) <= 0.05 and zcard(GID[cz2]) and all(abs(c) <= 0.005 and u <= 1e-9 for c, u in zcard(GID[cz2])),
      (day(fon, Z2), evs(fon, "ZTB"), zcard(GID[cz2])))
check("Z3 브릿지 예치 증서 + 동반 토큰 → 증서 매도 +$500 · 검토 없음 · 동반 GVX 원가 0 확인",
      abs(day(fon, Z3) - 500) <= 0.05 and not pend_of(fon, "xRCX") and zcard(GID[gz3]) and all(abs(c) <= 0.005 and u <= 1e-9 for c, u in zcard(GID[gz3])),
      (day(fon, Z3), pend_of(fon, "xRCX"), zcard(GID[gz3]), evs(fon, "GVX")))
check("G1 동반 토큰 먼저 + 스왑 가스 $10 → 증서 SKG 원가 $2,510 → $2,600 매도 = +$90 · 스왑 날 +$502(ETH 처분 +$500 · 가스 코인 처분 손익 +$2 — L4 규약)",
      abs(day(fon, G1) - 502) <= 0.05 and abs(day(fon, G1S) - 90) <= 0.05, (day(fon, G1), day(fon, G1S), evs(fon, "SKG")))
check("G1 동반 GVG 원가 0 그대로(가스 안 붙음)", zcard(GID[gvg]) and all(abs(c) <= 0.005 and u <= 1e-9 for c, u in zcard(GID[gvg])), (zcard(GID[gvg]), evs(fon, "GVG")))
check("V1 한쪽만 시가 + 가짜 'BTC' 계약 → 분봉 안 씀 = 균등 추정 $1,000 → B $2,500 매도 = +$1,500",
      abs(day(fon, V1) - 1500) <= 0.05 and any("추정" in d for d in evs(fon, "BVA")), (day(fon, V1), evs(fon, "BVA")))
check("V2 양쪽 시세 없음 + 가짜 'BTC' 계약 → 균등 추정 $1,500 → B $3,500 매도 = +$2,000",
      abs(day(fon, V2) - 2000) <= 0.05 and any("추정" in d for d in evs(fon, "BVB")), (day(fon, V2), evs(fon, "BVB")))
v3c = ([round(float(p.get("cost") or 0), 2) for p in card(fon, GID[wv3])], [round(float(p.get("cost") or 0), 2) for p in card(fon, GID[bv3])])
check("V3 받은 쪽 전부 정품 CA + 분봉 → 시세 비례 WETH 원가 $500 · WBTC $1,500 · '추정' 아님",
      v3c[0] and v3c[1] and abs(sum(v3c[0]) - 500) <= 0.05 and abs(sum(v3c[1]) - 1500) <= 0.05 and not any("추정" in d for d in evs(fon, "WETH") + evs(fon, "WBTC")),
      (v3c, evs(fon, "WETH")))
check("R1 증서(수량 990) 매도 +$500 · 검토 없음", abs(day(fon, R1) - 500) <= 0.05 and not pend_of(fon, "xRCQ"), (day(fon, R1), pend_of(fon, "xRCQ")))
check("R2 증서 + 네이티브 잔돈 같이 받음 → 증서가 원가 승계 → 매도 +$500 · 검토 없음", abs(day(fon, R2) - 500) <= 0.05 and not pend_of(fon, "xRCZ"),
      (day(fon, R2), pend_of(fon, "xRCZ"), evs(fon, "xRCZ")))
for tag, (d0, d1, fq) in F.items():
    check(f"{tag} 켬: 브릿지 날 −${fq} + 매도 +${500 + fq} = 합 +$500", abs(day(fon, d0) + fq) <= 0.05 and abs(day(fon, d1) - (500 + fq)) <= 0.05
          and abs(span(fon, d0, d1) - 500) <= 0.05, (day(fon, d0), day(fon, d1)))
    check(f"{tag} 끔: 실현 합 +${500 + fq}(수수료 처분 손익 0 · 비용은 탭)", abs(span(foff, d0, d1) - (500 + fq)) <= 0.05, (day(foff, d0), day(foff, d1)))
    check(f"{tag} 검토 없음(도착이 원가 승계)", not pend_of(fon, "FB" + tag[1]), pend_of(fon, "FB" + tag[1]))
gbc = [g for g in (foff.get("gasByChain") or []) if g.get("chain") == "Base"]
check("끔: 가스·수수료 탭 Base 줄 브릿지 수수료 = $1 + $50", gbc and abs(sum(float(g.get("br") or 0) for g in gbc) - 51) <= 0.05, gbc)
ton = invariants(fon, "켬")
invariants(foff, "끔")
exp = 2000 + 4000 + 3002 + 3010 + 1510 + 500 + (500 + 750) + 300 + (500 + 100) + 500 + 500 + (502 + 90) + 1500 + 2000 + 500 + 500 + 500 + 500
check(f"켬 전체 실현 합 = 시나리오 합 ${exp:,}(스테이블·잔돈 원가 부풀림 없음)", abs(ton - exp) <= 0.05, (ton, rbd_of(fon)))
T.finish()
