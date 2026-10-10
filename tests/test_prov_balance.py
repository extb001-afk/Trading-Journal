#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import hashlib
import json
import os
import shutil
import time

W = "0x" + "ab" * 20
W2 = "0x" + "cd" * 20
DAY = 86400
NOW = int(time.time())
AT = NOW - 60
shutil.copytree(os.path.join(T.ROOT, "seed"), os.path.join(T.TMP, "seed"), dirs_exist_ok=True)
CFG = {"wallets": [{"type": "evm", "chain": "eth", "address": W, "label": "w"}], "backfill_months": 3,
       "chains": {"eth": {"blockscout": "https://bs.invalid", "conf_depth": 12, "blocks_per_day": 7200, "rpcs": ["https://rpc.invalid"]}},
       "native_symbol": {"eth": "ETH"}}
json.dump(CFG, open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
import common

assert T.TMP in common.STATE_DIR
import db as dbm


def check(name, ok, detail=""):
    T.chk(bool(ok), name, None if ok else str(detail)[:900])


def h(tag):
    return "0x" + hashlib.sha256(tag.encode()).hexdigest()


con = dbm.open_db(os.path.join(common.STATE_DIR, "ledger.db"))
ST = {"aid": 0, "pid": 0}
DEC, GID = {}, {}


def asset(addr, sym, d=18, gname=None, kind="token"):
    ST["aid"] += 1
    a = ST["aid"]
    con.execute("INSERT INTO asset_groups (group_id, name, norm_decimals) VALUES (?,?,18)", (100 + a, gname or f"{sym}#{a}"))
    con.execute("INSERT INTO assets (asset_id, kind, chain, address, symbol, decimals, confirmed, hidden, group_id) VALUES (?,?,?,?,?,?,1,0,?)",
                (a, kind, "eth", addr, sym, d, 100 + a))
    DEC[a], GID[a] = d, 100 + a
    return a


TXEV = []


def leg(kind, sid, ts, a, qty, lk, ev, cost=None, seq=0, w=W):
    ST["pid"] += 1
    con.execute("INSERT INTO postings (posting_id, source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd,"
                " cost_krw, leg_kind, event, classifier_ver) VALUES (?,?,?,?,?,?,?,?,?,?,NULL,?,?,5)",
                (ST["pid"], kind, "eth", sid, seq, ts, a, f"wallet:eth:{w}", str(int(round(qty * 10 ** DEC[a]))),
                 None if cost is None else repr(float(cost)), lk, ev))
    TXEV.append((sid, ev))


def ca(x):
    return "0x" + x * 20


CA = {"known": ca("e1"), "new": ca("e2"), "spam": ca("e3"), "nocg": ca("e4"), "air": ca("e5"), "fake": ca("e6"), "neg": ca("e7"),
      "drop": ca("d1"), "zero": ca("d2"), "outq": ca("d3"), "late": ca("d4"), "new2": ca("c1"), "thin": ca("c2"), "cgonly": ca("c3"),
      "anewx": ca("c4"), "blk": ca("b1"), "blk2": ca("b2"), "amb": ca("b3"), "thn2": ca("b4")}
WBTC = "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"
BTS = NOW - 200
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
a_known = asset(CA["known"], "KNOWN")
leg("chain_tx", h("buy"), NOW - 5 * DAY, a_known, 10, "acq", "SWAP", 20)
a_usdc = asset(USDC, "USDC", 6, gname="USDC")
leg("chain_tx", h("dep"), NOW - 6 * DAY, a_usdc, 100, "acq", "TRANSFER_IN", 100)
a_air = asset(CA["air"], "AIRDR")
leg("chain_tx", h("air"), NOW - 4 * DAY, a_air, 1000, "acq", "PROGRAM_IN")
a_neg = asset(CA["neg"], "NEGT")
leg("chain_tx", h("negout"), NOW - 3 * DAY, a_neg, -50, "move_out", "TRANSFER_OUT")
a_drop = asset(CA["drop"], "DROP")
leg("chain_tx", h("drop"), NOW - 5 * DAY, a_drop, 100, "acq", "SWAP", 100)
a_zero = asset(CA["zero"], "ZEROT")
leg("chain_tx", h("zero"), NOW - 5 * DAY, a_zero, 7, "acq", "SWAP", 7)
a_outq = asset(CA["outq"], "OUTQ")
leg("chain_tx", h("outq"), NOW - 5 * DAY, a_outq, 5, "acq", "SWAP", 5)
a_late = asset(CA["late"], "LATE")
leg("chain_tx", h("late"), NOW - 10, a_late, 3, "acq", "SWAP", 3)
a_blk = asset(CA["blk"], "BLK")
leg("chain_tx", h("blk"), NOW - 400, a_blk, 5, "acq", "SWAP", 5)
a_blk2 = asset(CA["blk2"], "BLKB")
leg("chain_tx", h("blk2"), NOW - 30, a_blk2, 4, "acq", "SWAP", 4)
a_amb = asset(CA["amb"], "AMBT")
leg("chain_tx", h("amb"), BTS + 5, a_amb, 6, "acq", "SWAP", 6)
for hx9, ev9 in TXEV:
    con.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES ('eth',?,?,'{}',5)", (hx9, ev9))
for hx9, bk9 in ((h("blk"), 125), (h("blk2"), 120)):
    con.execute("INSERT INTO raw_txs (chain, txhash, block, blockhash, ts, snapshot, wallets, ingested_at) VALUES ('eth',?,?,NULL,NULL,'{}','[]',0)", (hx9, bk9))
pos = {}
for a, loc, qb in con.execute("SELECT asset_id, location, qty_base FROM postings"):
    pos[(GID[a], loc)] = pos.get((GID[a], loc), 0) + int(qb) / 10 ** DEC[a]
for (g, loc), q in pos.items():
    con.execute("INSERT OR REPLACE INTO positions (group_id, location, qty_norm, qty_unknown_norm, cost_alloc_usd) VALUES (?,?,?, '0', '0')",
                (g, loc, format(q, ".12f")))
con.commit()
N_POST = con.execute("SELECT count(*) FROM postings").fetchone()[0]
con.close()
E18 = 10 ** 18
TOK = {CA["known"]: [str(25 * E18), "KNOWN", 18], USDC: [str(300 * 10 ** 6), "USDC", 6], CA["new"]: [str(40 * E18), "NEWT", 18],
       CA["spam"]: [str(9 * E18), "Visit claim-reward.com", 18], CA["nocg"]: [str(7 * E18), "NOCGT", 18],
       CA["air"]: [str(1500 * E18), "AIRDR", 18], CA["fake"]: [str(5 * E18), "WETH", 18], CA["neg"]: [str(30 * E18), "NEGT", 18],
       CA["drop"]: [str(10 * E18), "DROP", 18], CA["outq"]: ["0", "OUTQ", 18], CA["late"]: [str(4 * E18), "LATE", 18],
       CA["new2"]: [str(40 * E18), "NEWB", 18], CA["thin"]: [str(1_000_000 * E18), "THIN", 18], CA["cgonly"]: [str(100 * E18), "CGO", 18],
       CA["anewx"]: [str(100 * E18), "ANEWX", 18], USDT: [str(500 * 10 ** 6), "USDT", 6],
       CA["blk"]: [str(2 * E18), "BLK", 18], CA["blk2"]: [str(9 * E18), "BLKB", 18], CA["amb"]: [str(1 * E18), "AMBT", 18],
       CA["thn2"]: [str(15_000 * E18), "THN2", 18], WBTC: [str(50_000_000), "WBTC", 8]}
Q = sorted(c for c in TOK if c != CA["outq"]) + [CA["zero"]]
TOK.pop(CA["outq"])
PROV = {"eth": {"mode": "chain", "at": AT, "t1": AT, "block": 123, "bts": BTS, "req": [W, W2], "wallets": {
    W: {"native": str(2 * E18), "tok": TOK, "q": sorted(Q)},
    W2: {"tok": {CA["thn2"]: [str(15_000 * E18), "THN2", 18]}, "q": [CA["thn2"]]}}}}
json.dump({"v": 1, "e": {f"eth:{CA['nocg']}": [AT, None], f"eth:{CA['new']}": [AT, 1.5], f"eth:{CA['new2']}": [AT, 3.0],
                         f"eth:{CA['cgonly']}": [AT, 0.5], f"eth:{CA['anewx']}": [AT, 1.0], f"eth:{WBTC}": [AT, 60000.0]}},
          open(os.path.join(common.STATE_DIR, "cg_ca.json"), "w"))

import pricing
import cgca
import web

cgca.reset_for_tests()
pricing._gj = lambda url, *a, **k: (_ for _ in ()).throw(OSError("시험: 시세 받기 없음"))
web.Spot.dex_pending = lambda self, c, ca: False
web.Spot.ex_pending = lambda self, ex: False
PX = {CA["known"]: 2.0, CA["new"]: 1.5, CA["spam"]: 1.0, CA["nocg"]: 3.0, CA["air"]: 0.01, CA["fake"]: 2500.0, CA["neg"]: 1.0,
      CA["drop"]: 1.0, CA["zero"]: 1.0, CA["outq"]: 1.0, CA["late"]: 1.0, CA["new2"]: 3.0, CA["thin"]: 1.0, CA["anewx"]: 1.0, USDT: 1.01,
      CA["blk"]: 1.0, CA["blk2"]: 1.0, CA["amb"]: 1.0, CA["thn2"]: 1.0}
RES = {CA["thin"]: 20_000.0, CA["thn2"]: 20_000.0}
RB = {"wallets": {W: {"fetchedAt": NOW - 60, "total": 50000, "tokens": [
    {"id": CA["new"], "chain": "eth", "sym": "NEWT", "amt": 40, "px": 1.5, "v": True},
    {"id": ca("e8"), "chain": "eth", "sym": "RBONLY", "amt": 10, "px": 2.0, "v": True}],
    "protocols": [{"chain": "eth", "proto": "lend", "pname": "Lend", "items": [
        {"name": "Lending", "pool": ca("f1"), "ctrl": ca("f2"), "idx": "", "assets": [{"sym": "NEWX", "amt": 100, "px": 1.0, "v": True}]}]}]}}}
json.dump(RB, open(os.path.join(common.STATE_DIR, "rabby_portfolio.json"), "w"))
json.dump({"fallback_avg": True}, open(os.path.join(common.STATE_DIR, "ui_prefs.json"), "w"))


def builder():
    b = web.StateBuilder()
    web.BUILDER = b
    now = time.time()
    for ca9, px9 in PX.items():
        kk = f"eth:{ca9}"
        b.spot.dex_usd[kk], b.spot.dex_ts[kk], b.spot.dex_res[kk], b.spot.dex_res_ts[kk] = px9, now, RES.get(ca9, 5_000_000.0), now
    b.spot.usd["ETH"], b.spot.usd_ts["ETH"] = 2500.0, now
    return b


def total_of(f):
    return sum(float(c.get("qty") or 0) * float(c.get("price") or 0) for c in (f.get("coins") or [])) + \
        sum(float(s.get("qty") or 0) * float(s.get("price") or 0) for s in (f.get("stables") or []))


def build():
    b = builder()
    st = T.safe(b.build)
    return b, ((st or {}).get("fields") or {}) if isinstance(st, dict) else {}


b0, f0 = build()
check("빌드(종전) 성공", bool(f0))
T0 = total_of(f0)
c0 = {str(c["key"]): c for c in (f0.get("coins") or [])}
json.dump(PROV, open(os.path.join(common.STATE_DIR, "prov_bal.json"), "w"))
b1, f1 = build()
check("빌드(지금 잔고 있음) 성공", bool(f1))
coins = {str(c["key"]): c for c in (f1.get("coins") or [])}
stab = {str(s["key"]): s for s in (f1.get("stables") or [])}


def q_of(k, src=None):
    r = (src or coins).get(k) or stab.get(k) or {}
    return float(r.get("qty") or 0)


ck = coins.get(f"g{GID[a_known]}") or {}
check("P2 원장이 아는 토큰 = 그 행에 차이만(원장 10 · 지금 25 → 25 · pvQty 15)", abs(q_of(f"g{GID[a_known]}") - 25) < 1e-9 and abs(float(ck.get("pvQty") or 0) - 15) < 1e-9, ck)
check("P16 평균가 대체(켬) = 지금 잔고 몫도 종전 계산(원가 미확인 15 × 평단 $2 = $30)", abs(float(ck.get("fbQty") or 0) - 15) < 1e-9 and abs(float(ck.get("fbCost") or 0) - 30) < 0.01, ck)
check("P1 스테이블 그룹 = 액면으로(100 → 300)", abs(q_of(f"g{GID[a_usdc]}") - 300) < 1e-6, stab.get(f"g{GID[a_usdc]}"))
cn = coins.get("pv:eth:native") or {}
check("P1 네이티브(원장에 없음) = 새 행 2 ETH × $2,500", abs(float(cn.get("qty") or 0) * float(cn.get("price") or 0) - 5000) < 0.01 and cn.get("sym") == "ETH", cn)
check("P14 네이티브 = 시세 조회 등록(ETH)", "ETH" in b1.spot.syms, sorted(b1.spot.syms)[:20])
cw = coins.get(f"pv:eth:{CA['new2']}") or {}
check("P1 원장이 모르는 토큰(코인게코 있음 · DEX) = 새 행 40 × $3", abs(float(cw.get("qty") or 0) * float(cw.get("price") or 0) - 120) < 0.01, cw)
skipped = (f1.get("prov") or {}).get("skipped") or {}
check("P3 스팸 이름 · 코인게코 없음 · 가짜 대표 심볼 = 안 더함 · 격리 그룹 = 보유 밖",
      not any(k for k in coins if CA["spam"] in k or CA["nocg"] in k or CA["fake"] in k) and q_of(f"g{GID[a_air]}") == 0
      and {"스팸 이름", "코인게코 시세 없음", "가짜 대표 심볼"} <= set(skipped), (sorted(coins), skipped))
check("P10 원장 위치 음수 −50 · 지금 30 → 보유 30(80 아님)", abs(q_of(f"g{GID[a_neg]}") - 30) < 1e-9, coins.get(f"g{GID[a_neg]}"))
check("P11 원장 100 > 지금 10 → 보유 10(원장 몫 그대로 두지 않음)", abs(q_of(f"g{GID[a_drop]}") - 10) < 1e-9, coins.get(f"g{GID[a_drop]}"))
check("P11 조회 범위 안 · 안 나옴 = 0(원장 7 → 0)", q_of(f"g{GID[a_zero]}") == 0, coins.get(f"g{GID[a_zero]}"))
check("P11 조회 범위 밖 = 원장 그대로(5)", abs(q_of(f"g{GID[a_outq]}") - 5) < 1e-9, coins.get(f"g{GID[a_outq]}"))
check("P11 조회 뒤 원장에 들어온 입금은 그대로 더함(지금 4 + 뒤 입금 3 = 7)", abs(q_of(f"g{GID[a_late]}") - 7) < 1e-9, coins.get(f"g{GID[a_late]}"))
su = stab.get(f"pv:eth:{USDT}") or {}
check("P12 원장 밖 검증 스테이블 = 액면 $1 · 스테이블 목록(500 → $500 · DEX 1.01 아님)", su and float(su.get("price") or 0) == 1.0 and abs(float(su.get("qty") or 0) - 500) < 1e-6
      and f"pv:eth:{USDT}" not in coins, (su, sorted(stab)))
check("P13 유동성 가드(100만 × $1 > 풀 $2만) = 0", q_of(f"pv:eth:{CA['thin']}") == 0 or float((coins.get(f"pv:eth:{CA['thin']}") or {}).get("price") or 0) == 0,
      coins.get(f"pv:eth:{CA['thin']}"))
cg9 = coins.get(f"pv:eth:{CA['cgonly']}") or {}
check("P14 코인게코 시세 평가(100 × $0.5) · 1시간마다 다시 받게 등록", abs(float(cg9.get("qty") or 0) * float(cg9.get("price") or 0) - 50) < 0.01
      and ("eth", CA["cgonly"]) in set((b1.__dict__.get("_cgca_want") or ({}, set()))[1]), (cg9, (b1.__dict__.get("_cgca_want") or ({}, set()))[1]))
rbk = [str(c9["key"]) for c9 in (f1.get("coins") or []) if str(c9.get("key", "")).startswith("rb:")]
rbk0 = [str(c9["key"]) for c9 in (f0.get("coins") or []) if str(c9.get("key", "")).startswith("rb:")]
check("P9 Rabby 겹침 = Rabby 숫자 그대로(NEWT 는 Rabby 행만 · 지금 잔고 행 없음 · RBONLY 그대로)",
      "rb:NEWT" in rbk and f"pv:eth:{CA['new']}" not in coins and "rb:RBONLY" in rbk and skipped.get("Rabby 기준 행으로 표시") == 1, (rbk, sorted(coins), skipped))
check("P15 Rabby 프로토콜 포지션(NEWX $100) ↔ 지금 잔고 영수 토큰(ANEWX $100) = 한 번만", "rb:NEWX" in rbk0 and "rb:NEWX" not in rbk
      and abs(q_of(f"pv:eth:{CA['anewx']}") - 100) < 1e-9, (rbk0, rbk))
check("P17 블록 뒤 레그(시각은 앞) = 안 뺌(지금 2 + 원장 5 = 7)", abs(q_of(f"g{GID[a_blk]}") - 7) < 1e-9, coins.get(f"g{GID[a_blk]}"))
check("P17 블록 앞 레그(시각은 뒤) = 뺌(지금 9 = 9 · 13 아님)", abs(q_of(f"g{GID[a_blk2]}") - 9) < 1e-9, coins.get(f"g{GID[a_blk2]}"))
check("P17 블록 모르는 경계 근처 레그 = 그 칸 보류(원장 6 그대로)", abs(q_of(f"g{GID[a_amb]}") - 6) < 1e-9, coins.get(f"g{GID[a_amb]}"))
t2 = coins.get(f"pv:eth:{CA['thn2']}") or {}
check("P18 유동성 가드 = 전 지갑 합계(15,000 × 2 × $1 > 풀 $2만 → 0)", float(t2.get("qty") or 0) * float(t2.get("price") or 0) == 0, t2)
wb9 = coins.get(f"pv:eth:{WBTC}") or {}
cw9 = b1.__dict__.get("_cgca_want") or ({}, set())
check("P18 원장 밖 정품(WBTC · DEX·거래소 시세 없음) = 코인게코 시세 · 재조회 확인 대상(want)·시세 대상 둘 다",
      abs(float(wb9.get("qty") or 0) * float(wb9.get("price") or 0) - 30000) < 0.01 and ("eth", WBTC) in cw9[0] and ("eth", WBTC) in set(cw9[1]), (wb9, cw9))
PV = 15 * 2 + 200 + 30 - 90 - 7 + 4 + 5000 + 120 + 50 + 500 + 100 + 2 + 5 + 30000
T1 = total_of(f1)
check("P1 총자산 = 종전 + 지금 잔고 몫 − Rabby 프로토콜 중복(NEWX $100)", abs(T1 - T0 - (PV - 100)) < 0.05, (T0, T1, T1 - T0, PV - 100))
check("P1 지금 잔고 몫 집계 = 원장 그룹 차이 + 새 행", abs(float((f1.get("prov") or {}).get("usd") or 0) - PV) < 0.05, f1.get("prov"))
d0 = {d["date"]: d for d in (f0.get("dailySeries") or []) if isinstance(d, dict)}
d1 = {d["date"]: d for d in (f1.get("dailySeries") or []) if isinstance(d, dict)}
last0, last1 = (f0.get("dailySeries") or [{}])[-1], (f1.get("dailySeries") or [{}])[-1]
check("P4 오늘 일별 값 = 화면 총자산 · 지금 잔고 몫 = pv · 순유입 칸(종전 순유입 + pv)", abs(float(last1.get("val") or 0) - (float(last0.get("val") or 0) + T1 - T0)) < 1
      and abs(float(last1.get("pv") or 0) - PV) < 0.05
      and abs((float(last1.get("flow") or 0) - float(last1.get("rbNew") or 0)) - (float(last0.get("flow") or 0) - float(last0.get("rbNew") or 0)) - PV) < 0.05,
      (last0, last1, T0, T1))
prev_same = all(abs(float(d1[k].get("val") or 0) - float(d0[k].get("val") or 0)) < 1e-6 for k in d0 if k in d1 and k != last1.get("date"))
check("P4 지난날 값 무변(첫 대사 전 몫은 곡선 되감기에 안 넣음)", prev_same and len(d1) >= 2)
att1 = last1.get("att") if isinstance(last1.get("att"), dict) else {}
check("P4 분해 '원장 밖 잔고' 이름표에 지금 잔고 몫을 또 넣지 않음", abs(float(att1.get("xr") or 0)) < PV / 2, att1)
note = str((f1.get("prov") or {}).get("note") or "")
check("P7 안내 = 원가·손익·지난날 곡선은 옛 기록을 다 받으면 정확하게", "정확하게 맞춰져요" in note and "원가·손익·지난날 곡선" in note and "Ethereum" in note, note)
loc_pv = [l9 for l9 in (ck.get("locs") or []) if l9.get("pv")]
check("P1 보관처 줄 = '지금 잔고(옛 기록 받는 중)' 표시", loc_pv and "지금 잔고(옛 기록 받는 중)" in str(loc_pv[0].get("sub")), ck.get("locs"))
import sqlite3
c9 = sqlite3.connect(os.path.join(common.STATE_DIR, "ledger.db"))
check("P8 장부 무변(빌드가 원장에 안 씀)", c9.execute("SELECT count(*) FROM postings").fetchone()[0] == N_POST)
c9.execute("INSERT INTO meta (k, v) VALUES ('recon_done_eth', ?)", (str(NOW),))
c9.commit()
c9.close()
b2, f2 = build()
f0n = {k: (v.get("qty"), v.get("price")) for k, v in c0.items()}
f2n = {str(k["key"]): (k.get("qty"), k.get("price")) for k in (f2.get("coins") or [])}
check("P5 대사 끝 = 지금 잔고 몫 0(원장 숫자만 · 보유 행 종전과 같음)", abs(total_of(f2) - T0) < 0.05 and not f2.get("prov") and f2n == f0n, (total_of(f2), T0, f2.get("prov")))
PROVW = {"eth": {"mode": "wallet", "at": AT, "wallets": {W2: {"native": str(E18)}}}}
json.dump(PROVW, open(os.path.join(common.STATE_DIR, "prov_bal.json"), "w"))
b3, f3 = build()
check("P6 방식 'wallet' 칸(대사 끝난 체인의 새 지갑) = 안 씀(라이브 영향 0)", abs(total_of(f3) - T0) < 0.05 and not f3.get("prov"), (total_of(f3), T0))

import core
core.dm = lambda *a, **k: None
os.remove(os.path.join(common.STATE_DIR, "prov_bal.json"))
c = core.Core(common.load_config())
c.conn.execute("DELETE FROM meta WHERE k IN ('recon_done_eth')")
c.conn.commit()
c.my_wallets.setdefault("eth", set()).add(W2)
check("K1 첫 대사 전 대상 = (eth, chain, [W, W2])", c._prov_targets() == [("eth", "evm", "chain", sorted([W, W2]))], c._prov_targets())
calls = []
BAL = {"per_wallet": {W: {("native", None): 3 * E18, ("token", CA["new"]): 0, ("token", CA["known"]): 25 * E18}},
       "_meta": {CA["known"]: ("KNOWN", 18)}, "_block": 999, "_source": "rpc", "_queried": {W: [CA["known"], CA["new"], CA["zero"]]},
       "_unobs": {W: [CA["thin"]]}, "_hold": {W2: ["x"]}}


def fake_plan(chain, kind, ws, mode=None, latest=False):
    calls.append((chain, kind, list(ws), mode, latest))
    return lambda: BAL


def drain():
    for _ in range(100):
        if all(j["ev"].is_set() for j in c._prov_jobs.values()):
            return
        time.sleep(0.02)


c._recon_fetch_plan = fake_plan
c.prov_pass()
drain()
c._prov_last = 0
c.prov_pass()
pf = json.load(open(os.path.join(common.STATE_DIR, "prov_bal.json")))
we = (pf.get("eth") or {}).get("wallets", {}).get(W) or {}
check("K1 prov_pass = 지금 블록 조회(latest) · 파일 = 네이티브·토큰(0 잔고 포함) · 조회 범위·관측 불가 · 보류 지갑 뺌",
      calls and calls[0][4] is True and pf.get("eth", {}).get("mode") == "chain" and we.get("native") == str(3 * E18)
      and we.get("tok", {}).get(CA["known"]) == [str(25 * E18), "KNOWN", 18] and we.get("tok", {}).get(CA["new"]) == ["0", None, None]
      and we.get("q") == sorted([CA["known"], CA["new"], CA["zero"]]) and we.get("unobs") == [CA["thin"]]
      and set(pf["eth"]["wallets"]) == {W} and pf["eth"].get("req") == sorted([W, W2]), (calls, pf))
n_calls = len(calls)
for _ in range(3):
    c._prov_last = 0
    c.prov_pass()
    drain()
check("K1 (코덱스 pr513) 보류 지갑이 있어도 1시간 안 다시 안 물음", len(calls) == n_calls, (n_calls, len(calls)))
check("K1 장부 무변(prov_pass 가 원장에 안 씀)", c.conn.execute("SELECT count(*) FROM postings").fetchone()[0] == N_POST)
c.conn.execute("INSERT INTO meta (k, v) VALUES ('recon_done_eth', '1')")
c.conn.commit()
c._prov_last = 0
c.prov_pass()
check("K1 대사 끝 = 그 체인 칸 지움", "eth" not in json.load(open(os.path.join(common.STATE_DIR, "prov_bal.json"))))
W3 = "0x" + "ef" * 20
c.my_wallets.setdefault("eth", set()).add(W3)
check("K1 대사 뒤 새 지갑 = 대상 아님(라이브 영향 0 — 지갑별 대사가 채움)", c._prov_targets() == [], c._prov_targets())
BSCB = {"per_wallet": {W: {("native", None): 5, ("token", CA["known"]): 7}}, "_meta": {}, "_zero": {W: [CA["zero"]]}}
pk_b = core.Core._prov_pack(BSCB, "chain", 100, req=[W], t1=130, kind="bsc")
pk_s = core.Core._prov_pack({"per_wallet": {W: {("native", None): 5, ("token", "Mint1111"): 7}}}, "chain", 100, kind="sol")
pk_r = core.Core._prov_pack(dict(BAL, _block_ts=1234), "chain", 100, t1=150, kind="evm")
check("K1 (코덱스 pr517) BSC = 물은 토큰(양수·0)만 조회 범위 · SOL = 전부(범위 없음) · RPC = 블록·블록 시각 · 요청·받은 시각",
      pk_b["wallets"][W].get("q") == sorted([CA["known"], CA["zero"]]) and "q" not in pk_s["wallets"][W]
      and pk_r.get("block") == 999 and pk_r.get("bts") == 1234 and pk_r.get("at") == 100 and pk_r.get("t1") == 150
      and "block" not in pk_b and pk_b.get("t1") == 130, (pk_b, pk_s, pk_r))
c.recon_months = 0
c._prov_last = 0
c.prov_pass()
check("K1 전체 이력 모드(대사 안 함) = 임시 표시 안 함(파일 지움)", not os.path.exists(os.path.join(common.STATE_DIR, "prov_bal.json")))

import provbal
import depaddr
import xfer_match
from decimal import Decimal as D

USDC_BASE = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
check("P19 준비: Base USDC 가 검증 스테이블 표에 있음", pricing.STABLE_CAS.get("base", {}).get(USDC_BASE) == "USDC")
GX, GC = 900, 7


def pit(chain, w, gid, qty, addr=USDC_BASE, kind="token", sym="USDC", seen=2000):
    return {"chain": chain, "wallet": w, "loc": f"wallet:{chain}:{w}", "kind": kind, "addr": addr if kind == "token" else None, "aid": 1, "gid": gid,
            "sym": sym, "dec": 6, "bal": D(qty), "led": D(0), "qty": D(qty), "at": seen, "seen": seen}


def pend(net, addr, qty, state="pending", cls="wallet", sym="USDC", gid=GX, start=1000):
    return {"state": state, "cls": cls, "net": net, "sym": sym, "addr": addr, "gid": gid, "qty": D(qty), "ts": start - 5, "start": start}


def net(its, pends):
    return provbal.net_pending(its, pends, chain_of=depaddr.chain_of, norm=xfer_match.norm_addr)


WU = W.upper().replace("0X", "0x")
its0 = [pit("base", W, GC, "8800")]
r19 = net(its0, [pend("BASE", WU, "8800")])
check("P19 거래소 그룹(900) ≠ 체인 USDC 그룹(7)이어도 통화(검증 스테이블 USDC)로 맞춰 임시 몫 0(이중 계상 없음 — 종전: 17,600) · 주소 대소문자 무관", r19 == [], r19)
check("P19 호출측 목록 불변(사본으로 고침)", its0[0]["qty"] == D("8800"), its0)
r19u = net([pit("base", W, None, "8800")], [pend("BASE", W, "8800")])
check("P19 원장이 모르는 자산(그룹 없음 — 새 설치 첫 수집 전)도 통화로 맞춤", r19u == [], r19u)
r19n = net([pit("base", W, 3, "2", kind="native", sym="ETH")], [pend("BASE", W, "2", sym="ETH", gid=901)])
check("P19 네이티브 = 심볼(ETH)로 맞춤", r19n == [], r19n)
r19t = net([pit("base", W, GC, "8800", seen=900)], [pend("BASE", W, "8800", start=1000)])
check("P19 (tl526 보안) 잔고 관측이 출금 시작 전 = 그 잔고엔 출금이 없음 → 안 뺌", len(r19t) == 1 and r19t[0]["qty"] == D("8800"), r19t)
r19s = net([pit("base", W, 55, "8800", addr="0x" + "99" * 20)], [pend("BASE", W, "8800")])
check("P19 심볼만 USDC 인 비정품 토큰(사칭 가능) = 통화로 안 맞춤(그룹도 다름 → 안 뺌)", len(r19s) == 1 and r19s[0]["qty"] == D("8800"), r19s)
r19g = net([pit("base", W, 55, "300", addr="0x" + "99" * 20, sym="FOO")], [pend("BASE", W, "300", sym="FOO", gid=55)])
check("P19 일반 토큰 = 같은 그룹일 때만 뺌", r19g == [], r19g)
r19b = net([pit("base", W, GC, "100")], [pend("BASE", W, "8800")])
check("P19 초과(100)보다 많이 안 뺌 → 0", r19b == [], r19b)
r19c = net([pit("base", W, GC, "9000")], [pend("BASE", W, "8800")])
check("P19 초과 9,000 − 전송 중 8,800 = 200(옛 보유 몫은 그대로) · 뺀 몫 표시(transit)",
      len(r19c) == 1 and r19c[0]["qty"] == D("200") and r19c[0].get("transit") == D("8800"), r19c)
r19d = net([pit("arbitrum", W, GC, "8800", addr="0xaf88d065e77c8cc2239327c5edb3a432268e5831"), pit("base", W2, GC, "30"), pit("base", W, GC, "-5")],
           [pend("BASE", W, "8800")])
check("P19 다른 체인·다른 지갑·음수(원장 > 잔고) = 그대로",
      [(x["chain"], x["wallet"], x["qty"]) for x in r19d] == [("arbitrum", W, D("8800")), ("base", W2, D("30")), ("base", W, D("-5"))], r19d)
r19e = net([pit("base", W, GC, "8800")], [pend("", W, "8800")])
check("P19 네트워크 모름(chain_of None) = 그 지갑의 어느 체인이든", r19e == [], r19e)
r19f = net([pit("base", W, GC, "8800")], [pend("BASE", W, "8800", state="arrived"), pend("BASE", W, "8800", state="out"),
                                           pend("BASE", W, "8800", cls="exchange"), pend("BASE", W, "8800", cls="wallet_untracked")])
check("P19 도착 확인·유출·거래소행·추적 안 하는 지갑 = 안 뺌(그 전송 중은 화면이 따로 안 셈)", len(r19f) == 1 and r19f[0]["qty"] == D("8800"), r19f)
r19m = net([pit("base", W, GC, "5000")], [pend("BASE", W, "3000"), pend("BASE", W, "3000")])
check("P19 출금 둘(3,000+3,000) · 초과 5,000 = 0(한 출금이 두 번 쓰이지 않고 초과 한도)", r19m == [], r19m)
r19h = net([pit("base", W, GC, "8800")], [dict(pend("BASE", W, "0"), qty="abc"), pend("BASE", W, "-1"), dict(pend("BASE", W, "0"), qty="NaN"),
                                           {"state": "pending"}, None])
check("P19 이상한 항목(수량 글자·음수·NaN·필드 없음·None) = 무시", len(r19h) == 1 and r19h[0]["qty"] == D("8800"), r19h)
NSYM = {"base": "ETH", "sol": "SOL", "bsc": "BNB"}
itq = provbal.items({"base": {"mode": "chain", "at": 2000, "bts": 2000, "wallets": {W: {"native": "2000000000000000000"}}}},
                    done_chain=lambda c: False, asset_of=lambda c, k, a: None, ledger=lambda loc, ent: ({}, set()), ainfo=lambda a: None)
check("P19 (tl528) 준비: 원장에 네이티브 자산이 아직 없음 = 임시 항목 심볼 '?' · 그룹 없음", itq and itq[0]["sym"] == "?" and itq[0]["gid"] is None, itq)
r19q = provbal.net_pending(itq, [pend("BASE", W, "2", sym="ETH", gid=901)], chain_of=depaddr.chain_of, norm=xfer_match.norm_addr,
                           native_sym=lambda c: NSYM.get(c))
check("P19 (tl528) 원장에 없는 네이티브도 설정 심볼(ETH)로 출금 2 ETH 와 상계 → 0(종전: '?' 라 4 ETH)", r19q == [], r19q)
r19q2 = provbal.net_pending(itq, [pend("BASE", W, "2", sym="ETH", gid=901)], chain_of=depaddr.chain_of, norm=xfer_match.norm_addr)
check("P19 (tl528) 설정 심볼 없이 '?' 면 통화 모름 = 안 뺌(오탐 없음)", len(r19q2) == 1, r19q2)
r19q3 = provbal.net_pending([pit("bsc", W, None, "1", kind="native", sym="?")], [pend("BSC", W, "1", sym="ETH", gid=902)],
                            chain_of=depaddr.chain_of, norm=xfer_match.norm_addr, native_sym=lambda c: NSYM.get(c))
check("P19 (tl528) 다른 네이티브(BSC = BNB ≠ ETH 출금) = 안 뺌", len(r19q3) == 1, r19q3)
it19 = provbal.items({"base": {"mode": "chain", "at": 100, "t1": 130, "bts": 120, "wallets": {W: {"native": "1000000000000000000"}}}},
                     done_chain=lambda c: False, asset_of=lambda c, k, a: (1, 3, "ETH", 18), ledger=lambda loc, ent: ({}, set()), ainfo=lambda a: None)
check("P19 임시 항목에 잔고가 가리키는 시각(seen = 블록 시각 우선)", it19 and it19[0].get("seen") == 120, it19)
T.finish()
