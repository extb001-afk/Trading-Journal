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
from types import SimpleNamespace  # noqa: E402

W = "0x" + "ab" * 20
WL = f"wallet:base:{W}"
WA = f"wallet:arbitrum:{W}"
DAY = 86400
NOW = int(time.time())
KST = timezone(timedelta(hours=9))
shutil.copytree(os.path.join(T.ROOT, "seed"), os.path.join(T.TMP, "seed"), dirs_exist_ok=True)
json.dump({"wallets": [{"type": "evm", "chain": "base", "address": W, "label": "w"}], "backfill_months": 3, "chains": {}},
          open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
import paths, statefile  # noqa: E402

assert T.TMP in paths.STATE_DIR
import accounting_books  # noqa: E402
import accounting_fee  # noqa: E402
import db as dbm  # noqa: E402
import view_misc  # noqa: E402

chk = T.chk


def h(tag):
    return "0x" + hashlib.sha256(tag.encode()).hexdigest()


def iso(ts):
    return datetime.fromtimestamp(ts, KST).strftime("%Y-%m-%d")


print("[1] FeeBook.fee_day_add · gas_rows_by_date")
books = accounting_books.Books()
px = SimpleNamespace(sb=None, books=books, cb=None, ctx=SimpleNamespace(fxb=SimpleNamespace(rate_at=lambda ts: 1400.0)))
fbx = accounting_fee.FeeBook(px, kst_fmt=lambda ts, fmt: datetime.fromtimestamp(ts, KST).strftime(fmt))
T0 = int(datetime(2026, 3, 10, 12, tzinfo=KST).timestamp())
fbx.fee_day_add(Decimal("1.5"), T0, ("c", "base"), 1)
fbx.fee_day_add(Decimal("0"), T0 + 60, ("c", "base"), 1)
fbx.fee_day_add(Decimal("2"), T0 + 120, ("c", "base"), 0, True)
fbx.fee_day_add(Decimal("0.25"), T0 + 180, ("x", "binance"), 1)
fbx.fee_day_add(Decimal("3"), T0 + 240, ("w", "upbit"), 1)
fbx.fee_day_add(Decimal("4"), T0 + DAY, ("c", "arbitrum"), 1)
fbx.fee_day_add(Decimal("7"), T0 + DAY + 60)
d0, d1 = "2026-03-10", "2026-03-11"
g = books.gas_by_date
chk(set(g) == {d0, d1} and g[d0][("c", "base")] == {"usd": Decimal("3.5"), "tx": 2, "br": Decimal("2")}
    and g[d0][("x", "binance")] == {"usd": Decimal("0.25"), "tx": 1} and g[d0][("w", "upbit")] == {"usd": Decimal("3"), "tx": 1}
    and g[d1] == {("c", "arbitrum"): {"usd": Decimal("4"), "tx": 1}}, "F1 날짜 → 줄 키 → {usd, tx[, br]} (usd 0 가스 건수 · 브릿지 건수 0 + br)", g)
chk(books.fee_day[d0][0] == Decimal("6.75") and books.fee_day[d1][0] == Decimal("11") and abs(books.fee_day[d0][1] - 6.75 * 1400) < 1e-6,
    "F2 그날 합(fee_day)은 종전 그대로(usd > 0 만 · 줄 키 없는 호출도 더함)", books.fee_day)
rows = view_misc.gas_rows_by_date(g, {"base": "Base", "arbitrum": "Arbitrum"}, lambda e: e + " 체결 수수료", lambda e: e + " 출금 수수료")
chk(list(rows) == [d0, d1] and rows[d0] == [{"chain": "Base", "spot": 3.5, "tx": 2, "br": 2.0},
                                              {"chain": "binance 체결 수수료", "spot": 0.25, "tx": 1, "kind": "exfee", "ex": "binance"},
                                              {"chain": "upbit 출금 수수료", "spot": 3.0, "tx": 1, "kind": "exfee", "ex": "upbit"}]
    and rows[d1] == [{"chain": "Arbitrum", "spot": 4.0, "tx": 1}], "F3 응답 줄 = 월 버킷 줄 꼴(chain·spot·tx·br·kind·ex) · 차례 체인 → 체결 → 출금", rows)
chk(view_misc.gas_rows_by_date({}, {}, str, str) == {} and view_misc.gas_rows_by_date(None, {}, str, str) == {}, "F3 재료 없음 = 빈 dict")
books4 = accounting_books.Books()
fbx4 = accounting_fee.FeeBook(SimpleNamespace(sb=None, books=books4, cb=None, ctx=px.ctx), kst_fmt=fbx.kst_fmt)
for i in range(30):
    fbx4.fee_day_add(Decimal("0.004"), T0 + i * DAY, ("c", "base"), 1)
rows4 = view_misc.gas_rows_by_date(books4.gas_by_date, {"base": "Base"}, str, str)
chk(len(rows4) == 30 and all(r[0]["spot"] == 0.004 for r in rows4.values()) and abs(sum(r[0]["spot"] for r in rows4.values()) - 0.12) < 1e-9,
    "F4 매일 $0.004 × 30 = 날짜 합 $0.12 = 월 합(날짜 줄 2자리 반올림이면 0 — 정밀도 보존 · 표시에서만 반올림)", [sum(r[0]["spot"] for r in rows4.values())])

print("[2] 합성 원장 빌드")
con = dbm.open_db(os.path.join(paths.STATE_DIR, "ledger.db"))
ST = {"aid": 0, "pid": 0}
DEC = {}


def asset(kind, chain, addr, sym, d, gname=None):
    ST["aid"] += 1
    a = ST["aid"]
    con.execute("INSERT INTO asset_groups (group_id, name, norm_decimals) VALUES (?,?,18)", (a, gname or f"{sym}#{a}"))
    con.execute("INSERT INTO assets (asset_id, kind, chain, address, symbol, decimals, confirmed, hidden, group_id) VALUES (?,?,?,?,?,?,1,0,?)",
                (a, kind, chain, addr, sym, d, a))
    DEC[a] = d
    return a


def leg(kind, ns, sid, seq, ts, a, loc, qty, lk, ev, cost=None):
    ST["pid"] += 1
    con.execute("INSERT INTO postings (posting_id, source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd,"
                " cost_krw, leg_kind, event, classifier_ver) VALUES (?,?,?,?,?,?,?,?,?,?,NULL,?,?,5)",
                (ST["pid"], kind, ns, sid, seq, ts, a, loc, str(int(round(qty * 10 ** DEC[a]))), None if cost is None else repr(float(cost)), lk, ev))


def ctx(chain, loc, tag, ts, legs, ev):
    tx = h(tag)
    for i, (a, q, lk, c) in enumerate(legs):
        leg("chain_tx", chain, tx, i, ts, a, loc, q, lk, ev, c)
    con.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES (?,?,?,'{}',5)", (chain, tx, ev))
    return tx


usdc = asset("token", "base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6, "USDC")
ctx("base", WL, "fund", NOW - 200 * DAY, [(usdc, 100000, "acq", 100000)], "PROGRAM_IN")
e1 = asset("native", "arbitrum", None, "ETH", 18)
e2 = asset("native", "base", None, "ETH", 18)
D1, D2 = NOW - 150 * DAY, NOW - 140 * DAY
leg("chain_tx", "base", h("g1-buy"), 0, D1 - DAY, usdc, WL, -1000, "disp", "SWAP", 1000)
leg("chain_tx", "arbitrum", h("g1-buy"), 1, D1 - DAY, e1, WA, 1.0, "acq", "SWAP", 1000)
leg("chain_tx", "arbitrum", h("g1-gas"), 0, D1, e1, WA, -0.1, "gas", "NOOP", 300)
leg("chain_tx", "arbitrum", h("g1-gas2"), 0, D1 + 3600, e1, WA, -0.05, "gas", "NOOP", 150)
leg("chain_tx", "arbitrum", h("g1-gas3"), 0, D1 + 5 * DAY, e1, WA, -0.02, "gas", "NOOP", 60)
leg("chain_tx", "arbitrum", h("g1-sell"), 0, D1 + 6 * DAY, e1, WA, -0.8, "disp", "SWAP", 2400)
leg("chain_tx", "arbitrum", h("g1-sell"), 1, D1 + 6 * DAY, usdc, WL, 2400, "acq", "SWAP", 2400)
ctx("base", WL, "g2-buy", D2 - DAY, [(usdc, -1000, "disp", 1000), (e2, 1.0, "acq", 1000)], "SWAP")
ctx("base", WL, "g2-sell", D2, [(e2, -0.99, "disp", 2970), (usdc, 2970, "acq", 2970), (e2, -0.01, "gas", 35)], "SWAP")
D3 = NOW - 130 * DAY
ue = asset("exchange_currency", None, "upbit:eth", "ETH", 8)
e3 = asset("native", "optimism", None, "ETH", 18)
WO = f"wallet:optimism:{W}"
leg("exchange", "upbit:order", "o-3", 0, D3 - DAY, ue, "exchange:upbit", 1.0, "acq", "EX_BUY", 3000)
leg("exchange", "upbit:withdraw", "w-3", 0, D3, ue, "exchange:upbit", -1.0, "move_out", "EX_WITHDRAW")
TX3 = h("g3-arrive")
con.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('upbit','withdraw','w-3',1,?,?)",
            (json.dumps({"uuid": "w-3", "txid": TX3, "currency": "ETH", "amount": "0.99", "fee": "0.01", "state": "DONE",
                         "created_at": "2026-01-01T00:00:00+09:00"}), D3))
leg("chain_tx", "optimism", TX3, 0, D3 + 300, e3, WO, 0.99, "acq", "TRANSFER_IN")
con.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES ('optimism',?,'TRANSFER_IN','{}',5)", (TX3,))
D4 = NOW - 120 * DAY
BL = "exchange:binance"
bu = asset("exchange_currency", None, "binance:usdt", "USDT", 8)
bb = asset("exchange_currency", None, "binance:bnb", "BNB", 8)
leg("exchange", "binance:deposit", "d-4", 0, D4 - 3 * DAY, bu, BL, 2000, "move_in", "EXF_DEPOSIT")
leg("exchange", "binance:trade", "binance:BNBUSDT:4", 0, D4 - 2 * DAY, bu, BL, -300, "disp", "EXF_BUY", 300)
leg("exchange", "binance:trade", "binance:BNBUSDT:4", 1, D4 - 2 * DAY, bb, BL, 1.0, "acq", "EXF_BUY", 300)
leg("exchange", "binance:withdraw", "w-4", 0, D4, bb, BL, -0.01, "gas", "EXF_WD_FEE")
pos = {}
for a, loc, qb in con.execute("SELECT asset_id, location, qty_base FROM postings"):
    pos[(a, loc)] = pos.get((a, loc), 0) + int(qb)
for (a, loc), qb in pos.items():
    con.execute("INSERT OR REPLACE INTO positions (group_id, location, qty_norm, qty_unknown_norm, cost_alloc_usd) VALUES (?,?,?, '0', '0')",
                (a, loc, format(qb / 10 ** DEC[a], ".12f")))
con.commit()
con.close()

import pricing  # noqa: E402
import web  # noqa: E402

pricing._gj = lambda url, *a, **k: (_ for _ in ()).throw(OSError("시험: 시세 받기 없음"))


def build(gas_on):
    statefile.atomic_write_json(paths.state("ui_prefs.json"), {"gas_in_cost": gas_on, "first_seen_px": False})
    b = web.StateBuilder()
    st = T.safe(b.build)
    f = (st or {}).get("fields") or {} if isinstance(st, dict) else {}
    chk(bool(f), f"빌드 성공(가스 {'켬' if gas_on else '끔'})", st if isinstance(st, dict) and st.get("_exc") else "fields 없음")
    return f


def rkey(r):
    return (r.get("chain"), r.get("kind") or "", r.get("ex") or "")


for gas_on in (True, False):
    f = build(gas_on)
    tag = "켬" if gas_on else "끔"
    bd, bm, fa = f.get("gasByDate"), f.get("gasByMonth") or {}, f.get("feeAllByDate") or {}
    chk(isinstance(bd, dict) and bd and all(len(k) == 10 and k[4] == "-" for k in bd) and list(bd) == sorted(bd), f"{tag} gasByDate 있음 · ISO 날짜 키 · 오름차순", list(bd or {})[:5])
    bad = []
    for ym, mrows in bm.items():
        acc = {}
        for d, drows in bd.items():
            if d[:7] != ym:
                continue
            for r in drows:
                e = acc.setdefault(rkey(r), [0.0, 0, 0.0])
                e[0] += float(r.get("spot") or 0)
                e[1] += int(r.get("tx") or 0)
                e[2] += float(r.get("br") or 0)
        for r in mrows:
            e = acc.get(rkey(r))
            if e is None or abs(e[0] - float(r.get("spot") or 0)) > 0.006 or e[1] != int(r.get("tx") or 0) or abs(e[2] - float(r.get("br") or 0)) > 0.006:
                bad.append((ym, r, e))
        if set(acc) != {rkey(r) for r in mrows}:
            bad.append((ym, "줄 집합 다름", sorted(acc), sorted(rkey(r) for r in mrows)))
    chk(not bad and len(bm) >= 2, f"{tag} 달마다 날짜 합 = gasByMonth 줄(금액 ±반올림 0.005·건수·브릿지 몫 · 줄 집합 같음 · {len(bm)}달)", bad[:3])
    bad2 = [(d, sum(float(r.get("spot") or 0) for r in rows), fa.get(d)) for d, rows in bd.items()
            if abs(sum(float(r.get("spot") or 0) for r in rows) - float((fa.get(d) or [0])[0])) > 0.006]
    chk(not bad2 and set(fa) <= set(bd), f"{tag} 날짜마다 줄 합 = feeAllByDate 그날 합 · feeAllByDate 날짜 ⊆ gasByDate 날짜", bad2[:3])
    d1, d1b = iso(D1), iso(D1 + 5 * DAY)
    arb = [r for r in bd.get(d1, []) if r.get("chain") == "Arbitrum"]
    chk(len(arb) == 1 and abs(arb[0]["spot"] - 450) <= 0.01 and arb[0]["tx"] == 2 and "kind" not in arb[0], f"{tag} 같은 날 가스 두 건 = 한 줄 $450 · 2건(아비트럼)", bd.get(d1))
    chk(any(r.get("chain") == "Arbitrum" and abs(r["spot"] - 60) <= 0.01 and r["tx"] == 1 for r in bd.get(d1b, [])), f"{tag} 닷새 뒤 $60 는 그날 줄로 따로(월 버킷은 합쳐 $510 · 3건)", bd.get(d1b))
    arb_m = [r for r in bm.get(d1[:7], []) if r.get("chain") == "Arbitrum"]
    chk(arb_m and abs(arb_m[0]["spot"] - 510) <= 0.01 and arb_m[0]["tx"] == 3, f"{tag} gasByMonth 아비트럼 = $510 · 3건(종전 그대로)", arb_m)
    wd3 = [r for r in bd.get(iso(D3), []) if r.get("kind") == "exfee" and r.get("ex") == "upbit"]
    wd4 = [r for r in bd.get(iso(D4), []) if r.get("kind") == "exfee" and r.get("ex") == "binance"]
    chk(len(wd3) == 1 and abs(wd3[0]["spot"] - 30) <= 0.01 and wd3[0]["tx"] == 1 and "출금 수수료" in wd3[0]["chain"]
        and len(wd4) == 1 and abs(wd4[0]["spot"] - 3) <= 0.01 and wd4[0]["tx"] == 1, f"{tag} 거래소 출금 수수료 줄 = kind exfee + ex 키 + 출금 수수료 이름(업비트 $30 · 바이낸스 $3)", (wd3, wd4))
    base_d2 = [r for r in bd.get(iso(D2), []) if r.get("chain") == "Base"]
    chk(len(base_d2) == 1 and abs(base_d2[0]["spot"] - 35) <= 0.01, f"{tag} 스왑 가스도 그날 줄(베이스 $35 · 켬·끔 무관)", bd.get(iso(D2)))
    chk(sum(float(r.get("spot") or 0) for g in f.get("gasByChain") or [] for r in [g]) > 0 and f.get("gasByChain") and f.get("gasByMonth"),
        f"{tag} 종전 칸(gasByChain·gasByMonth) 그대로 있음")
T.finish()
