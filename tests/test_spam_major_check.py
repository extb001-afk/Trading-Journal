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
DAY = 86400
NOW = int(time.time())
shutil.copytree(os.path.join(T.ROOT, "seed"), os.path.join(T.TMP, "seed"), dirs_exist_ok=True)
json.dump({"wallets": [{"type": "evm", "chain": "base", "address": W, "label": "w"}, {"type": "evm", "chain": "arbitrum", "address": W, "label": "w"}],
           "backfill_months": 3, "chains": {}}, open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
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


def asset(chain, addr, sym, gname=None, d=18):
    ST["aid"] += 1
    a = ST["aid"]
    nm = gname or f"{sym}#{a}"
    con.execute("INSERT INTO asset_groups (group_id, name, norm_decimals) VALUES (?,?,18)", (100 + a, nm))
    con.execute("INSERT INTO assets (asset_id, kind, chain, address, symbol, decimals, confirmed, hidden, group_id) VALUES (?,?,?,?,?,?,1,0,?)",
                (a, "token", chain, addr, sym, d, 100 + a))
    DEC[a], GID[a] = d, 100 + a
    return a


def leg(kind, chain, sid, ts, a, qty, lk, ev, cost=None):
    ST["pid"] += 1
    con.execute("INSERT INTO postings (posting_id, source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd,"
                " cost_krw, leg_kind, event, classifier_ver) VALUES (?,?,?,?,0,?,?,?,?,?,NULL,?,?,5)",
                (ST["pid"], kind, chain, sid, ts, a, f"wallet:{chain}:{W}", str(int(round(qty * 10 ** DEC[a]))),
                 None if cost is None else repr(float(cost)), lk, ev))


def opening(chain, a, qty):
    leg("opening", chain, f"recon:{chain}:{a}", NOW - 30 * DAY, a, qty, "opening", "OPENING")


CA = {k: "0x" + v * 20 for k, v in (("weth", "c1"), ("wbtc", "c2"), ("usdt", "c3"), ("usdc", "c4"), ("imp", "c5"), ("bsc", "c6"),
                                     ("wbtc_u", "c7"))}
ub = asset("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", "USDC", 6)
leg("chain_tx", "base", h("fund"), NOW - 60 * DAY, ub, 1000, "acq", "PROGRAM_IN", 1000)
a_weth = asset("base", CA["weth"], "WETH")
opening("base", a_weth, 2)
a_wbtc = asset("base", CA["wbtc"], "WBTC", d=8)
opening("base", a_wbtc, 1.5)
a_usdt = asset("arbitrum", CA["usdt"], "USDT", d=6)
opening("arbitrum", a_usdt, 1_000_000)
a_usdc = asset("base", CA["usdc"], "USDC", d=6)
leg("chain_tx", "base", h("air"), NOW - 20 * DAY, a_usdc, 50_000, "acq", "TRANSFER_IN")
con.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES ('base',?,'TRANSFER_IN','{}',5)", (h("air"),))
a_imp = asset("base", CA["imp"], "ꓴSDT", d=6)
opening("base", a_imp, 100)
a_bsc = asset("base", CA["bsc"], "⁠BSC-USD", d=6)
opening("base", a_bsc, 500)
a_user = asset("arbitrum", CA["wbtc_u"], "WBTC", d=8)
opening("arbitrum", a_user, 0.5)
a_thin = asset("arbitrum", "0x" + "c8" * 20, "WETH")
opening("arbitrum", a_thin, 3)
CA7 = {"ust": "0x" + "a7" * 20, "air": "0x" + "a8" * 20, "gps": "0x" + "a9" * 20}
a_ust = asset("base", CA7["ust"], "USDT", d=6)
opening("base", a_ust, 1000)
a_air = asset("base", CA7["air"], "WBTC", d=8)
leg("chain_tx", "base", h("air7"), NOW - 10 * DAY, a_air, 0.25, "acq", "TRANSFER_IN")
a_gps = asset("base", CA7["gps"], "USDC", d=6)
leg("chain_tx", "base", h("gps7"), NOW - 9 * DAY, a_gps, 7000, "acq", "TRANSFER_IN")
pos = {}
for a, loc, qb in con.execute("SELECT asset_id, location, qty_base FROM postings"):
    pos[(GID[a], loc)] = pos.get((GID[a], loc), 0) + int(qb) / 10 ** DEC[a]
for (g, loc), q in pos.items():
    con.execute("INSERT OR REPLACE INTO positions (group_id, location, qty_norm, qty_unknown_norm, cost_alloc_usd) VALUES (?,?,?, '0', '0')",
                (g, loc, format(q, ".12f")))
con.commit()
con.close()
json.dump({"_note": "사용자 정품 목록", "arbitrum": {CA["wbtc_u"].upper().replace("0X", "0x"): "WBTC"},
           "base": {CA7["ust"]: "USDT", CA7["air"]: "WBTC", CA7["gps"]: "USDC"}},
          open(os.path.join(common.STATE_DIR, "genuine_tokens.json"), "w"))
json.dump({f"base:{CA7['gps']}": {"risk": {"strong": True, "label": "허니팟"}}}, open(os.path.join(common.STATE_DIR, "goplus_cache.json"), "w"))

import pricing
import spamguard
import web

pricing._gj = lambda url, *a, **k: (_ for _ in ()).throw(OSError("시험: 시세 받기 없음"))
web.Spot.dex_pending = lambda self, c, ca: False
web.Spot.ex_pending = lambda self, ex: False
b = web.StateBuilder()
web.BUILDER = b
now = time.time()
k_weth = f"base:{CA['weth']}"
b.spot.dex_usd[k_weth], b.spot.dex_ts[k_weth], b.spot.dex_res[k_weth], b.spot.dex_res_ts[k_weth] = 2000.0, now, 5_000_000.0, now
b.spot.usd["BTC"], b.spot.usd_ts["BTC"] = 60000.0, now
k_thin = "arbitrum:0x" + "c8" * 20
b.spot.dex_usd[k_thin], b.spot.dex_ts[k_thin], b.spot.dex_res[k_thin], b.spot.dex_res_ts[k_thin] = 2000.0, now, 500.0, now
st = T.safe(b.build)
f = (st or {}).get("fields") or {} if isinstance(st, dict) else {}
check("빌드 성공", bool(f), st if isinstance(st, dict) and st.get("_exc") else "fields 없음")
coins = {int(str(c["key"])[1:]): c for c in (f.get("coins") or []) if str(c.get("key", "")).startswith("g")}
quar = set(getattr(b, "_risk_quarantined", None) or ())
unv = set(getattr(b, "_risk_unverified", None) or ())
pend = f.get("pendings") or []
risk_keys = {p.get("key") for p in pend if str(p.get("key") or "").startswith("risk:")}

cw = coins.get(GID[a_weth]) or {}
check("S1 정품 목록 밖 'WETH' + 유동성 있는 DEX 시세 = 보유 목록에 평가($4,000) · 격리 아님 · 배지 없음",
      abs(float(cw.get("qty") or 0) * float(cw.get("price") or 0) - 4000) < 0.01 and GID[a_weth] not in quar and not cw.get("unv"),
      (cw, GID[a_weth] in quar))
for a9, nm9, q9 in ((a_wbtc, "WBTC", 1.5), (a_usdt, "USDT", 1_000_000), (a_usdc, "USDC", 50_000), (a_thin, "WETH", 3)):
    c9 = coins.get(GID[a9]) or {}
    check(f"S2 정품 목록 밖 '{nm9}'(시세 없음) = 보유 행 있음 · 평가 0 · 확인 필요 배지({nm9}) · 컨트랙트 칸",
          abs(float(c9.get("qty") or 0) - q9) < 1e-6 and float(c9.get("price") or 0) == 0 and c9.get("unv") == nm9 and c9.get("ca") == ({"WBTC": CA["wbtc"], "USDT": CA["usdt"], "USDC": CA["usdc"]}.get(nm9) or "0x" + "c8" * 20), c9)
    check(f"S2 '{nm9}' 스팸 검토 줄 없음(숨김 목록 아님)", f"risk:g{GID[a9]}" not in risk_keys, sorted(risk_keys))
tot = sum(float(c.get("qty") or 0) * float(c.get("price") or 0) for c in coins.values()) + \
    sum(float(s.get("qty") or 0) * float(s.get("price") or 0) for s in (f.get("stables") or []))
TOT = 35000 + 1000 + 15000
check("S3 총자산 = USDC 1,000 + WETH 4,000 + 등록 WBTC 30,000 + S7 등록 USDT 1,000 · 등록 WBTC 15,000 = $51,000(확인 필요 USDT 100만·USDC 5만·WBTC 1.5·얇은 풀 WETH 3 · 스캠 확증 USDC 제외)",
      abs(tot - TOT) < 0.01, tot)
hero = web._hero_summary(st) if hasattr(web, "_hero_summary") else None
check("S3 첫 화면 총자산(hero)도 같은 값", hero is None or abs(float(hero.get("total") or 0) - TOT) < 0.01, hero)
check("S3 확인 필요 = 격리 집합(기록·곡선·알림 밖)", {GID[a_wbtc], GID[a_usdt], GID[a_usdc], GID[a_thin]} <= quar and {GID[a_wbtc], GID[a_usdt], GID[a_usdc], GID[a_thin]} <= unv,
      (sorted(quar), sorted(unv)))
ups = [str(x) for x in (f.get("unpricedSyms") or [])]
check("S3 '시세 없음' 목록에 확인 필요 토큰 없음(따로 셈)", not any(s in ("WBTC", "USDT", "USDC") for s in ups), ups)
ds = [d for d in (f.get("dailySeries") or []) if isinstance(d, dict)]
check("S3 오늘 일별 값 = 확인 필요 제외", bool(ds) and abs(float(ds[-1].get("val") or 0) - TOT) < 1, ds[-1:] if ds else None)
c7 = coins.get(GID[a_ust]) or {}
check("S7 등록 'USDT'(DEX 시세 없음) = 액면 $1 · 보유 행 · 격리 아님 · '직접 등록' 표식",
      abs(float(c7.get("qty") or 0) * float(c7.get("price") or 0) - 1000) < 0.01 and GID[a_ust] not in quar and c7.get("genU") == 1, (c7, GID[a_ust] in quar))
c7a = coins.get(GID[a_air]) or {}
check("S7 남이 보낸 'WBTC' 등록 = 에어드랍 격리 안 함 · BTC 시세 $15,000 · '직접 등록' 표식(풀기 버튼 재료 ck·ca)",
      abs(float(c7a.get("qty") or 0) * float(c7a.get("price") or 0) - 15000) < 0.01 and GID[a_air] not in quar and c7a.get("genU") == 1
      and c7a.get("ca") == CA7["air"], (c7a, GID[a_air] in quar, (getattr(b, "_risk_reasons", {}) or {}).get(GID[a_air])))
check("S7 등록했어도 고플러스 스캠 확증 = 격리 유지(보유 행 없음)", GID[a_gps] in quar and GID[a_gps] not in coins,
      (GID[a_gps] in quar, coins.get(GID[a_gps]), (getattr(b, "_risk_reasons", {}) or {}).get(GID[a_gps])))
check("S7 등록 안 한 같은 모양 'USDT' = 종전대로 확인 필요(평가 0)", float((coins.get(GID[a_usdt]) or {}).get("price") or 0) == 0 and GID[a_usdt] in unv)
my = {W.lower()}
c2 = __import__("sqlite3").connect(os.path.join(common.STATE_DIR, "ledger.db"))
check("S3 알림 판정: 확인 필요 'USDC' 유입 = 알림 안 보냄(가짜 USDC 사유)", "가짜 USDC" in str(spamguard.tx_scam_reason(c2, "base", h("air"), my)),
      spamguard.tx_scam_reason(c2, "base", h("air"), my))
c2.close()
for a9, nm9 in ((a_imp, "ꓴSDT"), (a_bsc, "숨은 글자 BSC-USD")):
    check(f"S4 {nm9} = 숨김(사칭) · 보유 행 없음 · 확인 필요 아님", GID[a9] in quar and GID[a9] not in unv and GID[a9] not in coins,
          (GID[a9] in quar, GID[a9] in unv, coins.get(GID[a9])))
cu = coins.get(GID[a_user]) or {}
check("S5 사용자 정품 목록 'WBTC' = BTC 시세로 평가($30,000) · 격리 아님 · '직접 등록' 표식",
      abs(float(cu.get("qty") or 0) * float(cu.get("price") or 0) - 30000) < 0.01 and GID[a_user] not in quar and cu.get("genU") == 1, cu)
check("S5 사용자 목록 CA 대소문자 무관(EVM)", spamguard.is_genuine("arbitrum", CA["wbtc_u"]) and spamguard.fake_major("WBTC", [("arbitrum", CA["wbtc_u"])]) is None)
if hasattr(spamguard, "set_user_genuine"):
    IR = web.StateBuilder._impostor_reason
    FK = [("base", "0x" + "d9" * 20)]
    g1 = {"sym": "WBTC", "wd_seen": True}
    check("S6 거래소 출금 도착(wd_seen) = 정품 취급(사유 없음 · 확인 필요 아님)", IR(g1, True, FK) is None and not g1.get("risk_unv"), g1)
    g2 = {"sym": "WBTC"}
    check("S6 유동성 없음 = 확인 필요(숨김 사유 아님)", IR(g2, True, FK, liquid=lambda: False) is None and g2.get("risk_unv") == "WBTC", g2)
    g3 = {"sym": "WBTC"}
    check("S6 유동성 있음(호출자 판정) = 정품 취급", IR(g3, True, FK, liquid=True) is None and not g3.get("risk_unv"), g3)
    g4 = {"sym": "WBTC", "spoof_n": 2}
    check("S6 확인 필요라도 가짜 전송 로그 = 숨김", "가짜 전송" in str(IR(g4, True, FK)), IR(g4, True, FK))
    sp9 = b.spot
    kk = "base:" + "0x" + "e9" * 20
    sp9.dex_usd[kk], sp9.dex_ts[kk], sp9.dex_res[kk], sp9.dex_res_ts[kk] = 1.0, now, 500.0, now
    check("S6 풀 $500(기준 미만) DEX 시세 = 유동성 없음", not (sp9.dex_reserve("base", "0x" + "e9" * 20) or 0) >= sp9.min_reserve_usd)
    up = getattr(b, "_unv_pairs", {}) or {}
    check("S6 등록 대상 표(_unv_pairs) = 지금 확인 필요인 컨트랙트", up.get(("base", CA["wbtc"])) == "WBTC" and ("arbitrum", CA["wbtc_u"]) not in up, up)
    ch9 = spamguard.set_user_genuine("base", CA["wbtc"].upper().replace("0X", "0x"), "WBTC", True)
    check("S6 등록(대문자 CA) → 정품 · 두 번째 등록 = 바뀜 없음", ch9 and spamguard.is_genuine("base", CA["wbtc"])
          and spamguard.set_user_genuine("base", CA["wbtc"], "WBTC", True) is False)
    check("S6 풀기 → 다시 정품 아님", spamguard.set_user_genuine("base", CA["wbtc"], "", False) and not spamguard.is_genuine("base", CA["wbtc"]))
    open(spamguard.user_path(), "w").write("{깨진")
    spamguard._user_refresh(force=True)
    check("S6 깨진 목록 파일 = 빈 목록(죽지 않음 · 내장 목록은 그대로)", not spamguard.is_genuine("arbitrum", CA["wbtc_u"])
          and spamguard.is_genuine("eth", "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"))
    try:
        spamguard.set_user_genuine("base", CA["wbtc"], "WBTC", True)
        check("S6 깨진 파일에 등록 = 거절(덮어쓰지 않음)", False, "예외 없음")
    except ValueError:
        check("S6 깨진 파일에 등록 = 거절(덮어쓰지 않음)", open(spamguard.user_path()).read() == "{깨진")
else:
    check("S6 사용자 정품 목록 API(spamguard.set_user_genuine) 있음", False, "없음")
import sqlite3
c8 = sqlite3.connect(os.path.join(common.STATE_DIR, "ledger.db"))
OTHER = "0x" + "ee" * 20


def tx8(tag, a, qty, lk, ev, frm):
    ST["pid"] += 1
    t9 = h(tag)
    c8.execute("INSERT INTO postings (posting_id, source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd,"
               " cost_krw, leg_kind, event, classifier_ver) VALUES (?,'chain_tx','base',?,0,?,?,?,?,NULL,NULL,?,?,5)",
               (ST["pid"], t9, NOW - 3600, a, f"wallet:base:{W}", str(int(round(qty * 10 ** DEC[a]))), lk, ev))
    c8.execute("INSERT INTO raw_txs (chain, txhash, block, ts, snapshot, wallets, ingested_at) VALUES ('base',?,1,?,?,'[]',0)",
               (t9, NOW - 3600, json.dumps({"tx": {"from": {"hash": frm}, "fee": {"value": "21000"}, "raw_input": "0xa9059cbb00"}})))
    return t9


t_out_liq = tx8("s8-out-weth", a_weth, -0.5, "move_out", "TRANSFER_OUT", W)
t_out_unv = tx8("s8-out-wbtc", a_wbtc, -0.1, "move_out", "TRANSFER_OUT", W)
t_in_liq = tx8("s8-in-weth", a_weth, 0.2, "acq", "TRANSFER_IN", OTHER)
t_in_unv = tx8("s8-in-wbtc", a_wbtc, 0.3, "acq", "TRANSFER_IN", OTHER)
c8.commit()
sp8 = os.path.join(common.STATE_DIR, "spot.json")
json.dump({"dex_usd": {k_weth: 2000.0}, "dex_ts": {k_weth: time.time()}, "dex_res": {k_weth: 5_000_000.0}, "dex_res_ts": {k_weth: time.time()}}, open(sp8, "w"))
r8 = {k: spamguard.tx_scam_reason(c8, "base", t9, my) for k, t9 in (("out_liq", t_out_liq), ("out_unv", t_out_unv), ("in_liq", t_in_liq), ("in_unv", t_in_unv))}
check("S8 내가 서명해 보낸 목록 밖 WETH(유동성 있음) = 알림 지우지 않음", r8["out_liq"] is None, r8)
check("S8 내가 서명해 보낸 확인 필요 WBTC = 알림 지우지 않음(내 행동)", r8["out_unv"] is None, r8)
check("S8 남이 보낸 유동성 있는 WETH(web 정품 취급과 같은 판정) = 알림", r8["in_liq"] is None, r8)
check("S8 남이 보낸 시세 없는 WBTC = 종전대로 거름(가짜 WBTC)", "가짜 WBTC" in str(r8["in_unv"]), r8)
json.dump({"dex_usd": {k_weth: 2000.0}, "dex_ts": {k_weth: time.time()}, "dex_res": {k_weth: 500.0}, "dex_res_ts": {k_weth: time.time()}}, open(sp8, "w"))
check("S8 풀 $500(기준 미만) = 유동성 아님 → 남이 보낸 WETH 거름", "가짜 WETH" in str(spamguard.tx_scam_reason(c8, "base", t_in_liq, my)))
open(sp8, "w").write("{깨진")
check("S8 spot.json 깨짐 = 판정 불가(알림 그대로)", spamguard.tx_scam_reason(c8, "base", t_in_liq, my) is None)
os.remove(sp8)
check("S8 spot.json 없음 = 유동성 증명 없음(시세 없는 것처럼 거름)", "가짜 WETH" in str(spamguard.tx_scam_reason(c8, "base", t_in_liq, my)))
c8.close()
T.finish()
