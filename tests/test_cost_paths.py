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

W = "0x" + "cd" * 20
WL = f"wallet:base:{W}"
UL = "exchange:upbit"
DAY = 86400
NOW = int(time.time())
KST = timezone(timedelta(hours=9))
shutil.copytree(os.path.join(T.ROOT, "seed"), os.path.join(T.TMP, "seed"), dirs_exist_ok=True)
json.dump({"wallets": [{"type": "evm", "chain": "base", "address": W, "label": "w"}], "backfill_months": 3, "chains": {}},
          open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
os.environ["TJ_REPLAY_DEBUG"] = "1"
import paths  # noqa: E402

assert T.TMP in paths.STATE_DIR
import db as dbm  # noqa: E402


def check(name, ok, detail=""):
    T.chk(bool(ok), name, None if ok else detail)


def h(tag):
    return "0x" + hashlib.sha256(tag.encode()).hexdigest()


def iso(ts):
    return datetime.fromtimestamp(ts, KST).strftime("%Y-%m-%d")


def iso_z(ts):
    return datetime.fromtimestamp(ts, KST).isoformat()


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


def ctx(tag, ts, legs, ev):
    tx = h(tag)
    for i, (a, q, lk, c) in enumerate(legs):
        leg("chain_tx", "base", tx, i, ts, a, WL, q, lk, ev, c)
    con.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES ('base',?,?,'{}',5)", (tx, ev))
    return tx


def raw(kind, uid, payload, ts):
    con.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('upbit',?,?,1,?,?)",
                (kind, uid, json.dumps(payload), ts))


usdc = asset("token", "base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6, "USDC")
ctx("fund", NOW - 200 * DAY, [(usdc, 100000, "acq", 100000)], "PROGRAM_IN")
D1 = NOW - 150 * DAY
rtk = asset("token", "base", "0x" + "21" * 20, "RTK", 18)
ctx("p1-buy", D1 - DAY, [(usdc, -1000, "disp", 1000), (rtk, 100, "acq", 1000)], "SWAP")
tx1o = ctx("p1-out", D1, [(rtk, -100, "move_out", None)], "TRANSFER_OUT")
leg("chain_tx", "base", tx1o, 1, D1, rtk, "out:base:0x" + "5e" * 20, 100, "move_in", "TRANSFER_OUT")
ctx("p1-in", D1 + 600, [(rtk, 100, "acq", None)], "PROGRAM_IN")
ctx("p1-sell", D1 + DAY, [(rtk, -100, "disp", 1500), (usdc, 1500, "acq", 1500)], "SWAP")
D2 = NOW - 140 * DAY
dta = asset("exchange_currency", None, "upbit:DTK", "DTK", 8)
dtb = asset("exchange_currency", None, "upbit:DTK-B", "DTK", 8)
leg("exchange", "upbit:deposit", "dep-p2", 0, D2 - 2 * DAY, dta, UL, 10, "move_in", "EX_DEPOSIT")
leg("exchange", "upbit:order", "o-p2a", 0, D2 - DAY, dta, UL, 100, "acq", "EX_BUY", 1000)
ctx("p2-pad", D2 - 3 * DAY, [(dtb, 110, "move_in", None)], "LP_REMOVE")
leg("exchange", "upbit:order", "o-p2b", 0, D2, dtb, UL, -110, "disp", "EX_SELL", 2200)
D2B = NOW - 135 * DAY
mta = asset("exchange_currency", None, "upbit:MTK", "MTK", 8)
mtb = asset("exchange_currency", None, "upbit:MTK-B", "MTK", 8)
mtc = asset("exchange_currency", None, "upbit:MTK-C", "MTK", 8)
leg("exchange", "upbit:deposit", "dep-p2b1", 0, D2B - 2 * DAY, mta, UL, 30, "move_in", "EX_DEPOSIT")
leg("exchange", "upbit:deposit", "dep-p2b2", 0, D2B - 2 * DAY + 60, mtb, UL, 30, "move_in", "EX_DEPOSIT")
ctx("p2b-pad", D2B - 3 * DAY, [(mtc, 20, "move_in", None)], "LP_REMOVE")
leg("exchange", "upbit:order", "o-p2b3", 0, D2B, mtc, UL, -20, "disp", "EX_SELL", 400)
D3 = NOW - 130 * DAY
old3 = asset("exchange_currency", None, "upbit:OLD", "OLD", 8)
new3 = asset("exchange_currency", None, "upbit:NEW", "NEW", 8)
leg("exchange", "upbit:order", "o-p3", 0, D3 - DAY, old3, UL, 100, "acq", "EX_BUY", 1000)
leg("exchange", "upbit:withdraw", "wd-p3", 0, D3, old3, UL, -100, "move_out", "EX_WITHDRAW")
raw("withdraw", "wd-p3", {"uuid": "wd-p3", "txid": "swap_p3", "currency": "OLD", "amount": "100", "fee": "0", "state": "DONE",
                          "created_at": iso_z(D3)}, D3)
leg("exchange", "upbit:deposit", "dep-p3", 0, D3 + 60, new3, UL, 50, "move_in", "EX_DEPOSIT")
raw("deposit", "dep-p3", {"uuid": "dep-p3", "txid": "swap_p3", "currency": "NEW", "amount": "50", "state": "ACCEPTED",
                          "created_at": iso_z(D3 + 60), "done_at": iso_z(D3 + 60)}, D3 + 60)
D4 = NOW - 120 * DAY
old4 = asset("exchange_currency", None, "upbit:OLDB", "OLDB", 8)
new4 = asset("exchange_currency", None, "upbit:NEWB", "NEWB", 8)
leg("exchange", "upbit:order", "o-p4", 0, D4 - DAY, old4, UL, 100, "acq", "EX_BUY", 1000)
leg("exchange", "upbit:deposit", "dep-p4", 0, D4, new4, UL, 50, "move_in", "EX_DEPOSIT")
raw("deposit", "dep-p4", {"uuid": "dep-p4", "txid": "swap_p4", "currency": "NEWB", "amount": "50", "state": "ACCEPTED",
                          "created_at": iso_z(D4), "done_at": iso_z(D4)}, D4)
leg("exchange", "upbit:withdraw", "wd-p4", 0, D4 + 60, old4, UL, -100, "move_out", "EX_WITHDRAW")
raw("withdraw", "wd-p4", {"uuid": "wd-p4", "txid": "swap_p4", "currency": "OLDB", "amount": "100", "fee": "0", "state": "DONE",
                          "created_at": iso_z(D4 + 60)}, D4 + 60)
D5 = NOW - 110 * DAY
usdt = asset("token", "base", "0xfde4c96c8593536e31f229ea8f37b2ada2699bb2", "USDT", 6, "USDT")
lpc = asset("token", "base", "0x" + "31" * 20, "LPC", 18)
ctx("p5a", D5, [(usdt, 500, "acq", None), (lpc, 100, "acq", None)], "LP_REMOVE")
D5B = NOW - 100 * DAY
lpx_a = asset("token", "base", "0x" + "32" * 20, "LPX", 18)
lpy_a = asset("token", "base", "0x" + "33" * 20, "LPY", 18)
ctx("p5b-buy", D5B - 2 * DAY, [(usdc, -100, "disp", 100), (lpx_a, 50, "acq", 100)], "SWAP")
ctx("p5b-air", D5B - DAY, [(lpx_a, 50, "acq", None)], "PROGRAM_IN")
ctx("p5b", D5B, [(lpx_a, -100, "disp", None), (lpy_a, 200, "acq", None)], "LP_REMOVE")
pos = {}
for a, loc, qb in con.execute("SELECT asset_id, location, qty_base FROM postings"):
    pos[(a, loc)] = pos.get((a, loc), 0) + int(qb)
for (a, loc), qb in pos.items():
    con.execute("INSERT OR REPLACE INTO positions (group_id, location, qty_norm, qty_unknown_norm, cost_alloc_usd) VALUES (?,?,?, '0', '0')",
                (a, loc, format(qb / 10 ** DEC[a], ".12f")))
con.commit()
con.close()

os.environ["TJ_BUILD_PROC"] = "off"
import pricing  # noqa: E402
import web  # noqa: E402

PRICE_TRIES = []


def _no_price(url, *a, **k):
    PRICE_TRIES.append(str(url)[:80])
    raise OSError("시험: 시세 받기 없음")


pricing._gj = _no_price

CAP = []
b = web.StateBuilder()
_orig_br = b._build_replay


def _cap_br(conn):
    rr = _orig_br(conn)
    CAP.append(rr)
    return rr


b._build_replay = _cap_br
st = T.safe(b.build)
f = (st or {}).get("fields") or {} if isinstance(st, dict) else {}
check("빌드 성공", bool(f), st if isinstance(st, dict) and st.get("_exc") else "fields 없음")
check("리플레이 결과 한 번 잡힘", len(CAP) == 1, len(CAP))
G = CAP[-1].G if CAP else {}
rbd = {k: float(v) for k, v in (f.get("realizedByDate") or {}).items()}
cards = f.get("_positionsAll") or f.get("positions") or []
tax = f.get("_taxRowsAll") or []
D0 = Decimal(0)


def gq(aid):
    g = G.get(aid) or {}
    return (g.get("qty_known", D0), g.get("cost", D0), g.get("qty_unknown", D0), g.get("realized", D0))


def near(x, y, tol="0.000001"):
    return abs(Decimal(x) - Decimal(y)) <= Decimal(tol)


def four(aid, qk, c, qu, rz):
    v = gq(aid)
    return near(v[0], qk) and near(v[1], c, "0.0001") and near(v[2], qu) and near(v[3], rz, "0.0001"), [str(x) for x in v]


def texts(aid):
    g = G.get(aid) or {}
    out = []
    for fl in g.get("flows") or []:
        for e in fl.get("events") or []:
            out.append(" ".join(str(x) for x in (e.get("type"), e.get("desc"), e.get("detail")) if x))
            out.append(json.dumps(e, ensure_ascii=False, default=str))
    for u in g.get("unk_src") or []:
        out.append(json.dumps(u, ensure_ascii=False, default=str))
    return "\n".join(out)


def day_sum(lo, hi):
    return round(sum(v for k, v in rbd.items() if iso(lo) <= k <= iso(hi)), 2)


ok, v = four(rtk, 0, 0, 0, 500)
check("P1 왕복 복귀 뒤 매도: RTK 끝 known 0 · cost 0 · unknown 0 · 실현 +$500(= 1,500 − 복원 원가 1,000)", ok, v)
check("P1 경로 표식: '프로그램 예치 복귀 · 원가 복원'", "프로그램 예치 복귀 · 원가 복원" in texts(rtk), texts(rtk)[:600])
check("P1 그날 실현 = +$500", abs(day_sum(D1, D1 + DAY) - 500) <= 0.05, rbd)
ok, v = four(dtb, 0, 0, 0, 1000)
check("P2 기증 승계 뒤 매도: DTK(나) known 0 · cost 0 · unknown 0(기증 미상분 10 도 같이 처분) · 실현 +$1,000", ok, v)
ok, v = four(dta, 0, 0, 0, 0)
check("P2 기증자 DTK(가) 전량 기증 → 0/0/0 · 실현 0", ok, v)
tl2 = (G.get(dta) or {}).get("qty_timeline") or []
check("P2 기증자 시계열 끝 = −110(기증)", bool(tl2) and near(tl2[-1][1], -110), tl2[-3:])
check("P2 경로 표식: '동일 심볼 원장 정정 · 브릿지 인스턴스에서 원가 이관'", "동일 심볼 원장 정정" in texts(dtb), texts(dtb)[:600])
v = gq(mtc)
check("P2b 기증자 후보 둘 = 기증 없음: MTK(다) known 0 · cost 0 · 실현 0", near(v[0], 0) and near(v[1], 0) and near(v[3], 0), [str(x) for x in v])
check("P2b 후보 둘의 잔고 그대로(가·나 unknown 30 씩)", near(gq(mta)[2], 30) and near(gq(mtb)[2], 30), (gq(mta), gq(mtb)))
check("P2b 경로 표식 없음(기증 안 함)", "동일 심볼 원장 정정" not in texts(mtc), texts(mtc)[:600])
ok, v = four(new3, 50, 1000, 0, 0)
check("P3 전환 출금 먼저: NEW known 50 · cost $1,000 · unknown 0", ok, v)
ok, v = four(old3, 0, 0, 0, 0)
check("P3 OLD 전량 출금 → 0/0/0", ok, v)
check("P3 경로 표식: '업비트 토큰 전환 입금 (OLD → NEW · 구 토큰 원가 승계)'", "업비트 토큰 전환 입금 (OLD → NEW · 구 토큰 원가 승계)" in texts(new3), texts(new3)[:600])
ok, v = four(new4, 50, 1000, 0, 0)
check("P4 전환 입금 먼저 → 출금이 원가 이관: NEWB known 50 · cost $1,000 · unknown 0", ok, v)
ok, v = four(old4, 0, 0, 0, 0)
check("P4 OLDB 전량 출금 → 0/0/0", ok, v)
check("P4 경로 표식: '업비트 토큰 전환 입금 · OLDB → NEWB'", "업비트 토큰 전환 입금 · OLDB → NEWB" in texts(new4), texts(new4)[:600])
ok, v = four(usdt, 500, 500, 0, 0)
check("P5a 예치 기록 없는 LP 회수 스테이블: USDT known 500 · cost $500(액면)", ok, v)
ok, v = four(lpc, 0, 0, 100, 0)
check("P5a 같은 tx 비스테이블 LPC unknown 100 · cost 0", ok, v)
check("P5a 경로 표식: 'LP 회수' · '예치 기록 없음'", "예치 기록 없음" in texts(lpc), texts(lpc)[:600])
ok, v = four(lpy_a, 100, 100, 100, 0)
check("P5b 전환 원금 절반 미상: LPY known 100 · unknown 100 · cost $100", ok, v)
ok, v = four(lpx_a, 0, 0, 0, 0)
check("P5b LPX 전량 전환 → 0/0/0 · 실현 0", ok, v)
check("P5b 경로 표식: 'LP 전환 취득 · 원가미상 원금분'", "원가미상 원금분" in texts(lpy_a), texts(lpy_a)[:600])
tot = round(sum(rbd.values()), 2)
cs = round(sum(float(p.get("realized") or 0) + float(p.get("realizedFb") or 0) for p in cards), 2)
check("불변: 헤더 실현 합 = 카드 실현 합", abs(tot - cs) <= 0.05, (tot, cs))
tn = round(sum(float(r.get("_disp", r.get("disp")) or 0) - float(r.get("_acq", r.get("acq")) or 0) - float(r.get("_fee", r.get("fee")) or 0) for r in tax), 2)
check("불변: 세금 명세 Σ(양도 − 취득 − 수수료) = 헤더 실현 합", abs(tot - tn) <= 0.05, (tot, tn))
T.finish()
