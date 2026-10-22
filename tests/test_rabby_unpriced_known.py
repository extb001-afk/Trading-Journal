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
W2 = "0x" + "cd" * 20
NOW = int(time.time())
shutil.copytree(os.path.join(T.ROOT, "seed"), os.path.join(T.TMP, "seed"), dirs_exist_ok=True)
CFG = {"wallets": [{"type": "evm", "chain": "eth", "address": W, "label": "w"}, {"type": "evm", "chain": "eth", "address": W2, "label": "w2"}], "backfill_months": 3,
       "chains": {"eth": {"blockscout": "https://bs.invalid", "conf_depth": 12, "blocks_per_day": 7200, "rpcs": ["https://rpc.invalid"]}},
       "native_symbol": {"eth": "ETH"}}
json.dump(CFG, open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
import paths  # noqa: E402

assert T.TMP in paths.STATE_DIR
import db as dbm  # noqa: E402
from view_pending import merge_scoped, unpriced_pairs  # noqa: E402
import rabby  # noqa: E402


def check(name, ok, detail=""):
    T.chk(bool(ok), name, None if ok else str(detail)[:900])


def ca(x):
    return "0x" + x * 20


P = {1: [("eth", "0xAA" + "a" * 38), ("bsc", "0x" + "b" * 40)], 2: [("eth", ca("c2"))], 3: [("eth", ca("c3"))], 4: [("eth", ca("c4"))],
     5: [("eth", ca("c5"))], 6: [("eth", ca("c6"))], 7: [("eth", ca("c7"))]}
ROWS = [{"key": "g1", "qty": 2.0, "price": 0}, {"key": "g2", "qty": 2.0, "price": 1.5}, {"key": "g3", "qty": 0, "price": 0},
        {"key": "g4", "qty": 2.0, "price": 0, "guard": 1}, {"key": "g5", "qty": 2.0, "price": 0, "unv": "X"},
        {"key": "g6", "qty": 2.0, "price": None}, {"key": "g7", "qty": 2.0, "price": 0},
        {"key": "rb:STK", "qty": 2.0, "price": 0}, {"key": "ub:ABC", "qty": 2.0, "price": 0}]
WA, WB = "0x" + "a1" * 20, "0x" + "b1" * 20


def lc(ch, w, q):
    return {"location": f"wallet:{ch}:{w}", "qty_norm": str(q)}


LOCS = {g: [lc("eth", WA, 1)] for g in range(2, 8)}
LOCS[1] = [lc("eth", WA, 1), lc("bsc", WB.upper().replace("0X", "0x"), 2), lc("eth", WB, 0), {"location": "exchange:upbit", "qty_norm": "5"}]
u1 = unpriced_pairs(ROWS, P, LOCS, {"tokens": [f"eth:{ca('c6').upper().replace('0X', '0x')}"]}, {7})
check("U1a 시세 없음 행 CA 중 그 지갑·체인에 양수 보유만(WA = eth 쌍 · WB = bsc 쌍 · 수량 0·거래소 위치 = 없음) · 시세 있음·수량 0·가드·확인 필요·"
      "수동 고정(keep)·rb:/ub: 키 = 없음 · 동반 토큰(대소문자 무관) = 없음",
      u1 == {WA: {("eth", "0xaa" + "a" * 38)}, WB: {("bsc", "0x" + "b" * 40)}}, u1)
u1b = unpriced_pairs(ROWS, P, LOCS, None)
check("U1b 동반 토큰 목록·keep 없음 = 시세 없음 행 전부(가격 None 포함)",
      u1b == {WA: {("eth", "0xaa" + "a" * 38), ("eth", ca("c6")), ("eth", ca("c7"))}, WB: {("bsc", "0x" + "b" * 40)}}, u1b)
u1c = [unpriced_pairs(ROWS, P, LOCS, z, {7}) for z in ({"tokens": "eth:x"}, ["eth:" + ca("c6")], {"tokens": [1, None]}, {})]
check("U1c 목록 모양 이상 = 동반 토큰 없음으로(예외 없음)", all(x == {WA: u1b[WA] - {("eth", ca("c7"))}, WB: u1b[WB]} for x in u1c), u1c)

X1, X2, X3 = ca("f1"), ca("f2"), ca("f3")


def pos(pool, sym, usd):
    return {"chain": "eth", "proto": "p" + sym, "pname": "P" + sym, "items": [
        {"name": "Staked", "pool": pool, "ctrl": pool, "idx": "", "assets": [{"sym": sym, "amt": 1, "px": usd, "v": True}],
         "debts": [{"sym": "DBT", "amt": 1, "px": 1.0}]}]}


SM = {"wallets": {a: {"fetchedAt": 1000 + i, "total": 9.0, "tokens": [], "protocols": [pos(X1, "S1" + str(i), 10.0 + i), pos(X2, "S2" + str(i), 20.0 + i),
                                                                                   pos(X3, "S3" + str(i), 30.0 + i)]}
                  for i, a in enumerate((WB, WA, W2))}}
KW = dict(resolve=lambda r: "eth", wallet_chains_set={(a, "eth") for a in (WA, WB, W2)}, known_pairs={("eth", X1), ("eth", X2)}, now=5000.0,
          only_addrs={WA, WB, W2})
m0 = rabby.merge(SM, **KW)
check("M1a 빼기 없음 = rabby.merge 한 번과 같은 값", merge_scoped(rabby.merge, {}, SM, **KW) == m0, None)
m1 = merge_scoped(rabby.merge, {WA: {("eth", X1)}, W2: {("eth", X1), ("eth", X2)}}, SM, **KW)
ref = {a: rabby.merge(SM, **dict(KW, known_pairs=KW["known_pairs"] - ex, only_addrs={a})) for a, ex in
       ((WA, {("eth", X1)}), (WB, set()), (W2, {("eth", X1), ("eth", X2)}))}
check("M1b 지갑마다 다른 빼기 = 그 지갑에서만 빠짐(WA: S1 더함 · W2: S1·S2 더함 · WB 종전)",
      sorted(x["sym"] for x in m1["items"]) == ["S11", "S12", "S22", "S30", "S31", "S32"] and
      all(m1["wallets"][a] == ref[a]["wallets"][a] for a in ref), sorted(x["sym"] for x in m1["items"]))
check("M1c 합친 모양·차례 = 한 번에 부른 꼴(items·debts 지갑 주소 차례 · wallets 정렬 · onlyUsd·debtUsd·at)",
      list(m1) == list(m0) and [x["addr"] for x in m1["items"]] == sorted(x["addr"] for x in m1["items"]) and list(m1["wallets"]) == sorted(m1["wallets"])
      and m1["debts"] == m0["debts"] and m1["onlyUsd"] == round(sum(x["usd"] for x in m1["items"]), 2) and m1["at"] == m0["at"],
      (list(m1), [x["addr"][:4] for x in m1["items"]]))

con = dbm.open_db(os.path.join(paths.STATE_DIR, "ledger.db"))
CRD, GOV, KNOWN = ca("e1"), ca("e2"), ca("e3")
GID = {}


def asset(aid, addr, sym):
    con.execute("INSERT INTO asset_groups (group_id, name, norm_decimals) VALUES (?,?,18)", (100 + aid, sym))
    con.execute("INSERT INTO assets (asset_id, kind, chain, address, symbol, decimals, confirmed, hidden, group_id) VALUES (?,?,?,?,?,?,1,0,?)",
                (aid, "token", "eth", addr, sym, 18, 100 + aid))
    GID[sym] = 100 + aid


def h(tag):
    return "0x" + hashlib.sha256(tag.encode()).hexdigest()


for i, (addr, sym) in enumerate(((CRD, "CRD"), (GOV, "GOVX"), (KNOWN, "KNWN")), 1):
    asset(i, addr, sym)
    con.execute("INSERT INTO postings (posting_id, source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd,"
                " cost_krw, leg_kind, event, classifier_ver) VALUES (?,?,?,?,0,?,?,?,?,?,NULL,'acq','SWAP',5)",
                (i, "chain_tx", "eth", h(sym), NOW - 5 * 86400, i, f"wallet:eth:{W}", str(2 * 10 ** 18), "10.0"))
    con.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES ('eth',?,'SWAP','{}',5)", (h(sym),))
    con.execute("INSERT OR REPLACE INTO positions (group_id, location, qty_norm, qty_unknown_norm, cost_alloc_usd) VALUES (?,?,'2', '0', '0')",
                (100 + i, f"wallet:eth:{W}"))
con.commit()


def ledger_fp():
    return (con.execute("SELECT count(*), group_concat(qty_base) FROM postings").fetchone(),
            con.execute("SELECT group_concat(group_id || location || qty_norm) FROM positions").fetchone())


FP0 = ledger_fp()


def item(pool, sym, amt, px):
    return {"name": "Staked", "pool": pool, "ctrl": pool, "idx": "staked", "assets": [{"sym": sym, "amt": amt, "px": px, "v": True}]}


RB = {"wallets": {W2: {"fetchedAt": NOW - 60, "total": 1500.0, "tokens": [], "chains": [{"id": "eth", "cid": 1, "usd": 1500.0}],
                       "protocols": [{"chain": "eth", "proto": "stk", "pname": "Staking", "items": [item(CRD, "STW", 1, 700.0)]}]},
                  W: {"fetchedAt": NOW - 60, "total": 2 * 1.0 + 1400.0 + 1400.0, "tokens": [], "chains": [{"id": "eth", "cid": 1, "usd": 2802.0}],
                      "protocols": [{"chain": "eth", "proto": "stk", "pname": "Staking", "items": [item(CRD, "STK", 2, 700.0)]},
                                    {"chain": "eth", "proto": "gov", "pname": "Gov", "items": [item(GOV, "STG", 2, 700.0)]}]}}}
json.dump(RB, open(os.path.join(paths.STATE_DIR, "rabby_portfolio.json"), "w"))
os.makedirs(os.path.join(paths.STATE_DIR, "seed_local"), exist_ok=True)
json.dump({"tokens": [f"eth:{GOV}"]}, open(os.path.join(paths.STATE_DIR, "seed_local", "zero_value_companions.json"), "w"))

import web  # noqa: E402


def build(px):
    b = web.StateBuilder()
    t = time.time()
    b.spot.rate, b.spot.rate_ts = 1400.0, t
    b.px.d.setdefault("neg_ts", {})["_fx"] = int(t)
    b.spot._ex_done = {"upbit", "binance", "bybit", "okx", "gate", "kucoin", "bithumb"}
    b.spot._gt_done = {("eth", c9) for c9 in (CRD, GOV, KNOWN)}
    for ca9, px9 in px.items():
        kk = f"eth:{ca9}"
        b.spot.dex_usd[kk], b.spot.dex_ts[kk], b.spot.dex_res[kk], b.spot.dex_res_ts[kk] = px9, t, 5_000_000.0, t
    b.spot.usd["ETH"], b.spot.usd_ts["ETH"] = 2500.0, t
    st = T.safe(b.build)
    return ((st or {}).get("fields") or {}) if isinstance(st, dict) else {}


def total_of(f):
    return sum(float(c.get("qty") or 0) * float(c.get("price") or 0) for c in (f.get("coins") or []) + (f.get("stables") or []))


def rows(f):
    return {str(c["key"]): c for c in (f.get("coins") or [])}


def recon(f):
    return next((r for r in ((f.get("rabby") or {}).get("wallets") or []) if r.get("addr") == W), {})


f1 = build({KNOWN: 1.0})
r1 = rows(f1)
check("B1 빌드 성공", bool(f1), f1)
stk = r1.get("rb:STK") or {}
check("B1a 시세 없는 증서(CRD 평가 0)의 같은 CA Rabby 포지션 = 'Rabby 기준' 행 rb:STK(2 × $700)",
      abs(float(stk.get("qty") or 0) - 2) < 1e-9 and abs(float(stk.get("price") or 0) - 700) < 1e-6 and not float(r1.get(f"g{GID['CRD']}", {}).get("price") or 0),
      (stk, r1.get(f"g{GID['CRD']}")))
check("B1b 총자산 = 봇(KNWN $2) + Rabby 기준 $1,400", abs(total_of(f1) - 1402.0) < 0.01, total_of(f1))
rc1 = recon(f1)
check("B1c 대조 — Rabby 기준으로 더한 몫(only) = $1,400 · 남은 차이(rest) = 동반 토큰 포지션 $1,400 만",
      abs(float(rc1.get("only") or 0) - 1400) < 0.01 and abs(float(rc1.get("rest") or 0) - 1400) < 0.01, rc1)
check("B2 동반 토큰(경제 가치 없음 목록 · seed_local) GOVX 의 같은 CA 포지션 = 종전대로 안 더함(rb:STG 없음)", "rb:STG" not in r1, sorted(r1))

check("B5 증서가 없는 지갑 W2 의 같은 CA 포지션(낡은 스냅샷) = 종전대로 안 더함(rb:STW 없음 · W2 only 0)",
      "rb:STW" not in r1 and not float(next((r for r in ((f1.get("rabby") or {}).get("wallets") or []) if r.get("addr") == W2), {}).get("only") or 0),
      sorted(r1))

f3 = build({KNOWN: 1.0, CRD: 690.0})
r3 = rows(f3)
check("B3a 증서에 시세가 생기면 = Rabby 행 없음(봇 숫자) · 증서 봇 행 = 2 × $690",
      "rb:STK" not in r3 and abs(float(r3.get(f"g{GID['CRD']}", {}).get("price") or 0) - 690) < 1e-6, (sorted(r3), r3.get(f"g{GID['CRD']}")))
check("B3b 총자산 = 봇 값만(KNWN $2 + CRD $1,380 · 이중 계산 0)", abs(total_of(f3) - 1382.0) < 0.01, total_of(f3))
check("B3c 대조 only = 0", abs(float(recon(f3).get("only") or 0)) < 0.01, recon(f3))

CFG["price_overrides"] = {f"eth:{CRD}": 0}
json.dump(CFG, open(os.path.join(T.TMP, "config.json"), "w"))
f6 = build({KNOWN: 1.0, CRD: 690.0})
check("B6 수동 가격 고정 0(평가 불가 스위치) = 종전대로 안 더함(rb:STK 없음 · CRD 평가 0 · 총자산 = KNWN $2)",
      "rb:STK" not in rows(f6) and abs(total_of(f6) - 2.0) < 0.01, (sorted(rows(f6)), total_of(f6)))

check("B4 원장 무변(빌드 전후 postings·positions 같음)", ledger_fp() == FP0, (ledger_fp(), FP0))
con.close()
T.finish()
