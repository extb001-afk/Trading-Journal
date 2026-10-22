#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import time  # noqa: E402

W = "0x" + "ab" * 20
WL = f"wallet:base:{W}"
UL = "exchange:upbit"
NOW = int(time.time())
T0 = NOW - 10 * 86400
shutil.copytree(os.path.join(T.ROOT, "seed"), os.path.join(T.TMP, "seed"), dirs_exist_ok=True)
json.dump({"wallets": [{"type": "evm", "chain": "base", "address": W, "label": "w"}], "backfill_months": 3, "chains": {}},
          open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
import paths  # noqa: E402

assert T.TMP in paths.STATE_DIR
import db as dbm  # noqa: E402

CA = {"QQQ": "0x" + format(0x51, "040x")}
con = dbm.open_db(os.path.join(paths.STATE_DIR, "ledger.db"))
ST = {"aid": 0, "pid": 0}
DEC = {}
XG = {}


def h(tag):
    return "0x" + hashlib.sha256(tag.encode()).hexdigest()


def asset(kind, chain, addr, sym, d):
    ST["aid"] += 1
    a = ST["aid"]
    con.execute("INSERT INTO asset_groups (group_id, name, norm_decimals) VALUES (?,?,18)", (a, f"{sym}#{a}"))
    con.execute("INSERT INTO assets (asset_id, kind, chain, address, symbol, decimals, confirmed, hidden, group_id) VALUES (?,?,?,?,?,?,1,0,?)",
                (a, kind, chain, addr, sym, d, a))
    DEC[a] = d
    return a


def leg(kind, ns, sid, seq, ts, a, loc, qty, lk, ev):
    ST["pid"] += 1
    con.execute("INSERT INTO postings (posting_id, source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd,"
                " cost_krw, leg_kind, event, classifier_ver) VALUES (?,?,?,?,?,?,?,?,?,NULL,NULL,?,?,5)",
                (ST["pid"], kind, ns, sid, seq, ts, a, loc, str(int(round(qty * 10 ** DEC[a]))), lk, ev))


def cls(txh, ev, det="{}"):
    con.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES ('base',?,?,?,5)", (txh, ev, det))


def raw(ex, kind, uuid, payload, ts):
    con.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES (?,?,?,1,?,?)",
                (ex, kind, uuid, json.dumps(payload), ts))


def up_group(sym):
    if sym not in XG:
        XG[sym] = asset("exchange_currency", None, f"upbit:{sym.lower()}", sym, 8)
    return XG[sym]


def deposit(t, sym, q, tag, ts):
    tx = h("dep-" + tag)
    leg("chain_tx", "base", tx, 0, ts, t, WL, -q, "move_out", "TRANSFER_OUT_EX")
    cls(tx, "TRANSFER_OUT_EX", json.dumps({"ex": "0x" + "cd" * 20}))
    uu = "u-" + tag
    con.execute("INSERT INTO transfers (state, asset_id, qty_base, src, dst, chain_txhash, ex_uuid, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                ("credited", t, str(int(q * 10 ** 6)), WL, "exchange:" + "0x" + "cd" * 20, tx, uu, NOW))
    leg("exchange", "upbit:deposit", uu, 0, ts + 600, up_group(sym), UL, q, "move_in", "EX_DEPOSIT")
    raw("upbit", "deposit", uu, {"txid": tx, "currency": sym, "state": "ACCEPTED", "amount": str(q)}, ts + 600)


def internal(sym, q):
    uu = "u-" + sym
    leg("exchange", "upbit:deposit", uu, 0, NOW - 7200, up_group(sym), UL, q, "move_in", "EX_DEPOSIT")
    raw("upbit", "deposit", uu, {"txid": "airdrop-" + sym, "currency": sym, "state": "ACCEPTED", "amount": str(q)}, NOW - 7200)


tq = asset("token", "base", CA["QQQ"], "QQQ", 6)
txw = h("gate-wd-QQQ")
leg("chain_tx", "base", txw, 0, T0, tq, WL, 39501, "move_in", "TRANSFER_IN")
cls(txw, "TRANSFER_IN")
raw("gate", "withdraw", "g-QQQ", {"txid": txw, "currency": "QQQ", "state": "DONE", "amount": "39501"}, T0)
deposit(tq, "QQQ", 30, "QQQ-test", NOW - 3600)
deposit(tq, "QQQ", 39471, "QQQ-main", NOW - 1500)
for s9 in ("KKK", "RRR", "FFF", "SSS", "GGG"):
    internal(s9, 1000)
pos = {}
for a, loc, qb in con.execute("SELECT asset_id, location, qty_base FROM postings"):
    pos[(a, loc)] = pos.get((a, loc), 0) + int(qb)
for (a, loc), qb in pos.items():
    con.execute("INSERT OR REPLACE INTO positions (group_id, location, qty_norm, qty_unknown_norm, cost_alloc_usd) VALUES (?,?,?, '0', '0')",
                (a, loc, format(qb / 10 ** DEC[a], ".12f")))
con.commit()
con.close()

import web  # noqa: E402

b = web.StateBuilder()
sp = b.spot
sp.rate, sp.rate_ts = 1400.0, time.time()
sp._ex_done = {"upbit", "binance", "bybit", "okx", "gate", "kucoin", "bithumb"}
sp._gt_done = {("base", CA["QQQ"])}
KQ = "base:" + CA["QQQ"]
sp.dex_usd[KQ], sp.dex_ts[KQ], sp.dex_res[KQ], sp.dex_res_ts[KQ], sp.dex_src[KQ] = 0.41, NOW, 12000.0, NOW, "gecko"
EX = {"gate:QQQ": 0.40, "okx:QQQ": 0.4043, "kucoin:QQQ": 0.405,
      "gate:KKK": 1.0, "kucoin:KKK": 1.0, "gate:RRR": 3.0, "kucoin:RRR": 3.0, "upbit:FFF": 5.0, "bybit:SSS": 2.0,
      "gate:GGG": 0.50, "kucoin:GGG": 0.52}
for k, v in EX.items():
    sp.ex_usd[k], sp.ex_ts[k] = v, NOW
sp.ex_usd["upbit:RRR"], sp.ex_ts["upbit:RRR"] = 3.1, NOW - 7200
LISTED = {"BTC", "KKK", "RRR", "FFF", "SSS"}


def build(listed, answered):
    sp.upbit_krw = set(listed)
    sp.upbit_alt = {}
    sp.upbit_answered = set(answered)
    b.cache = None
    b.px.d["neg_ts"]["_fx"] = time.time()
    st = T.safe(b.build)
    f = (st or {}).get("fields") or {} if isinstance(st, dict) else {}
    T.chk(bool(f), "빌드 성공", st if isinstance(st, dict) and st.get("_exc") else "fields 없음")
    rows = {c["key"]: c for c in f.get("coins") or []}
    return {s: rows.get(f"g{g}") or {} for s, g in XG.items()}, dict(b.__dict__.get("_px_pre_gids") or {})


def pv(r):
    return (float(r.get("price") or 0), r.get("pxSrc"), r.get("pxPre"), r.get("pxPreN"), bool(r.get("pxRef")))


def same_rest(r):
    return (pv(r["KKK"])[:4] == (0.0, None, None, None) and pv(r["RRR"])[:4] == (0.0, None, None, None)
            and pv(r["FFF"])[:4] == (5.0, "cex:업비트", None, None) and pv(r["SSS"])[:4] == (0.0, None, None, None)
            and pv(r["GGG"])[:4] == (0.5, "cex:게이트", 1, 2))


r0, pre0 = build(LISTED, LISTED - {"KKK"})
q0 = r0["QQQ"]
T.chk(abs(float(q0.get("qty") or 0) - 39501) < 1e-6 and pv(q0)[:4] == (0.4, "cex:게이트", 1, None),
      "L0 목록에 없음 = 거래 시작 전 평가 게이트 $0.40 · 수량 39,501(보유 평가 > 풀 유동성이어도)", pv(q0) + (q0.get("qty"),))
T.chk(XG["QQQ"] in pre0, "L0 거래 시작 전 평가 목록(지난날 소급 제외)에 QQQ", sorted(pre0))
T.chk(same_rest(r0), "L0 다른 행 = 종전 규칙", {s: pv(r) for s, r in r0.items()})

r1, pre1 = build(LISTED | {"QQQ"}, (LISTED | {"QQQ"}) - {"KKK"})
q1 = r1["QQQ"]
T.chk(pv(q1)[:4] == (0.4, "cex:게이트", 1, None) and not q1.get("pxRef"),
      "L1 목록에 있음 · 업비트가 답함 · 시세 받은 적 없음 = 거래 시작 전 평가 게이트 $0.40(참고가 아님)", pv(q1))
T.chk(XG["QQQ"] in pre1, "L1 거래 시작 전 평가 목록에 QQQ", sorted(pre1))
T.chk(same_rest(r1), "L1 다른 행 = 종전 규칙(업비트 시세 받은 적 있는 RRR 만료 = 0 그대로 · 아직 안 물어본 KKK = 대기 0)",
      {s: pv(r) for s, r in r1.items()})

r2, pre2 = build(LISTED | {"QQQ"}, set())
q2 = r2["QQQ"]
T.chk(pv(q2)[:4] == (0.0, None, None, None) and XG["QQQ"] not in pre2, "L2 목록에 있음 · 아직 답하기 전(재시작 직후) = 0 · 미조회 대기 그대로", pv(q2))

sp.ex_usd["upbit:QQQ"], sp.ex_ts["upbit:QQQ"] = 0.3676, NOW
r3, pre3 = build(LISTED | {"QQQ"}, LISTED | {"QQQ"})
q3 = r3["QQQ"]
T.chk(pv(q3)[:4] == (0.3676, "cex:업비트", None, None) and XG["QQQ"] not in pre3, "L3 거래 시작 = 업비트 원화 시세 $0.3676 · 표식 없음", pv(q3))
T.finish()
