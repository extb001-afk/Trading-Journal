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
json.dump({"wallets": [{"type": "evm", "chain": "base", "address": W, "label": "w"}], "backfill_months": 3, "chains": {}},
          open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
import common

assert T.TMP in common.STATE_DIR
import db as dbm
import spamguard


def check(name, ok, detail=""):
    T.chk(bool(ok), name, None if ok else str(detail)[:900])


def h(tag):
    return "0x" + hashlib.sha256(tag.encode()).hexdigest()


ZW = "\u17b5"
IMP_T = "ꓴ" + ZW + "Տ" + "Ꭰ" + ZW + "Ⲧ"
IMP_C = "ꓴ" + ZW + "Տ" + "Ꭰ" + ZW + "Ꮳ"

for s9, want in ((IMP_T, "USDT"), (IMP_C, "USDC"), (IMP_T.replace(ZW, ""), "USDT"), (IMP_C.replace(ZW, ""), "USDC"),
                 ("ꓴՏᎠⲧ", "USDT"),
                 ("ᴜꜱᴅᴛ", "USDT"),
                 ("ᑌSᗪT", "USDT"),
                 ("ΕⲦⲎ", "ETH"),
                 ("ႽOL", "SOL"),
                 ("WᏏTC", "WBTC"),
                 ("ⲢᎩUSD", "PYUSD")):
    check(f"U1 흉내 '{s9.encode('unicode_escape').decode()}' = {want} 사칭", spamguard.impostor_of(s9) == want, spamguard.impostor_of(s9))
for s9 in ("USDT", "USDC", "ETH", "USD₮", "USDC/WETH", "Meteora DLMM #AbCd…WxYz", "中文名字", "测试代币", "삼성", "ᏣᎳᎩ",
           "Ⲁⲁⲧ", "ZORB", "PEPE", "Ꮳ", "Ͼ"):
    check(f"U2 '{s9.encode('unicode_escape').decode()}' 사칭 아님", spamguard.impostor_of(s9) is None, spamguard.impostor_of(s9))
check("U2 순수 체로키 낱말·순수 한자 = 혼용 문자 아님", spamguard.odd_symbol("ᏣᎳᎩ") is None and spamguard.odd_symbol("中文名字") is None)
check("U2 라틴 + 콥트 섞인 이름 = 혼용 문자(종전 키릴 섞임과 같은 규칙)", spamguard.odd_symbol("PEPⲦ") is not None)
check("U2 접기 표 = 한 글자 → 라틴 대문자 하나(길이 어긋난 칸 없음)", all(len(v) == 1 and v.isascii() and v.isupper() for v in spamguard._CONF.values()),
      {k: v for k, v in spamguard._CONF.items() if not (len(v) == 1 and v.isascii() and v.isupper())})

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


def leg(sid, ts, a, loc, qty, lk, ev, cost=None):
    ST["pid"] += 1
    con.execute("INSERT INTO postings (posting_id, source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd,"
                " cost_krw, leg_kind, event, classifier_ver) VALUES (?,?,?,?,?,?,?,?,?,?,NULL,?,?,5)",
                (ST["pid"], "chain_tx", "base", sid, ST["pid"], ts, a, loc, str(int(round(qty * 10 ** DEC[a]))),
                 None if cost is None else repr(float(cost)), lk, ev))


def snap(txh, ts, frm, synth):
    tx = {"from": {"hash": frm}, "fee": {"value": "0" if synth else "21000"}, "raw_input": "0x01" if synth else "0xa9059cbb00"}
    con.execute("INSERT OR IGNORE INTO raw_txs (chain, txhash, block, ts, snapshot, wallets, ingested_at) VALUES ('base',?,1,?,?,'[]',0)",
                (txh, ts, json.dumps({"tx": tx})))


def send(tag, ts, a, qty, dest, synth):
    t9 = h(tag)
    leg(t9, ts, a, f"wallet:base:{W}", -qty, "move_out", "TRANSFER_OUT")
    leg(t9, ts, a, f"out:base:{dest}", qty, "move_in", "TRANSFER_OUT")
    con.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES ('base',?,'TRANSFER_OUT','{}',5)", (t9,))
    snap(t9, ts, W, synth)
    return t9


USDC_CA = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
ub = asset("base", USDC_CA, "USDC", "USDC", 6)
leg(h("fund"), NOW - 60 * DAY, ub, f"wallet:base:{W}", 5000, "acq", "PROGRAM_IN", 5000)
a_real = asset("base", "0x" + "c9" * 20, "REALT")
leg(h("buy"), NOW - 40 * DAY, a_real, f"wallet:base:{W}", 100, "acq", "PROGRAM_IN", 250)
DEST = {k: "0x" + v * 20 for k, v in (("t", "d1"), ("c", "d2"), ("plain", "d3"), ("usdc", "d4"), ("real", "d5"), ("keep", "d6"),
                                        ("keepimp", "d7"))}
a_t = asset("base", "0x" + "e1" * 20, IMP_T, d=6)
a_c = asset("base", "0x" + "e2" * 20, IMP_C, d=6)
a_pl = asset("base", "0x" + "e3" * 20, "ZQXFAKE", d=6)
T_IMP_T = send("imp-t", NOW - 3 * DAY, a_t, 12345, DEST["t"], True)
T_IMP_C = send("imp-c", NOW - 4 * DAY, a_c, 6789, DEST["c"], True)
T_PLAIN = send("plain", NOW - 5 * DAY, a_pl, 500, DEST["plain"], True)
T_USDC = send("usdc", NOW - 2 * DAY, ub, 300, DEST["usdc"], False)
T_REAL = send("real", NOW - 2 * DAY + 60, a_real, 10, DEST["real"], False)
a_keep = asset("base", "0x" + "e4" * 20, "ZQXKEEP", d=6)
a_keepimp = asset("base", "0x" + "e5" * 20, "U5D\u0422", d=6)
T_KEEP = send("keep", NOW - 6 * DAY, a_keep, 70, DEST["keep"], True)
T_KEEPIMP = send("keepimp", NOW - 7 * DAY, a_keepimp, 80, DEST["keepimp"], True)
pos = {}
for a, loc, qb in con.execute("SELECT asset_id, location, qty_base FROM postings"):
    pos[(GID[a], loc)] = pos.get((GID[a], loc), 0) + int(qb) / 10 ** DEC[a]
for (g, loc), q in pos.items():
    con.execute("INSERT OR REPLACE INTO positions (group_id, location, qty_norm, qty_unknown_norm, cost_alloc_usd) VALUES (?,?,?, '0', '0')",
                (g, loc, format(q, ".12f")))
con.commit()
con.close()

json.dump({"risk_overrides": {f"g{GID[a_keep]}": "visible", f"g{GID[a_keepimp]}": "visible"}},
          open(os.path.join(common.STATE_DIR, "ui_prefs.json"), "w"))
import pricing
import web

pricing._gj = lambda url, *a, **k: (_ for _ in ()).throw(OSError("시험: 시세 받기 없음"))
web.Spot.dex_pending = lambda self, c, ca: False
web.Spot.ex_pending = lambda self, ex: False

EHR = web.StateBuilder._event_hide_reason
r3 = EHR({"_gid": 7, "sym": "USDT", "symRaw": "USD\u200bT"}, {7: {"sym": "USD\u200bT"}}, set(), {7})
check("U3 화면 이름 'USDT'(보이지 않는 글자 뗀 것)라도 원문 'USD\\u200bT' = 사칭 숨김", "USDT" in str(r3 or ""), r3)
r3b = EHR({"_gid": 8, "sym": "USDT"}, {8: {"sym": "USDT"}}, set(), {8})
check("U3 글자 그대로의 'USDT'(원문 없음) = 이 판정으로 숨기지 않음(정품 여부는 CA 판정)", r3b is None, r3b)

b = web.StateBuilder()
web.BUILDER = b
st = T.safe(b.build)
f = (st or {}).get("fields") or {} if isinstance(st, dict) else {}
check("빌드 성공", bool(f), st if isinstance(st, dict) and st.get("_exc") else "fields 없음")
SH = {T_IMP_T: "USDT 흉내", T_IMP_C: "USDC 흉내", T_PLAIN: "평범한 이름 사칭·스팸 로그"}


def short(t9):
    return t9[:6] + "…" + t9[-4:]


vis = [e for e in (f.get("extraEvents") or []) if e.get("k") == "외부 전송"]
hid = [e for e in (f.get("extraEventsHidden") or []) if e.get("k") == "외부 전송"]
for t9, nm9 in SH.items():
    v9 = [e for e in vis if e.get("tx") == short(t9)]
    h9 = [e for e in hid if e.get("tx") == short(t9)]
    tag9 = "B1" if t9 != T_PLAIN else "B2"
    check(f"{tag9} {nm9} '외부 전송' = 기록(extraEvents)에 없음", not v9, v9)
    check(f"{tag9} {nm9} = 숨김 목록(extraEventsHidden · 종류 scam)", len(h9) == 1 and h9[0].get("hideKind") == "scam" and h9[0].get("hide"), h9)
pl9 = [e for e in hid if e.get("tx") == short(T_PLAIN)]
check("B2 평범한 이름 줄의 분류 = 사칭·스팸 로그(spam)", bool(pl9) and (pl9[0].get("of") or {}).get("c") == "spam", pl9)
tot9 = f.get("extraEventsTotal") or {}
check("B1·B2 숨김 수(hiddenScam) ≥ 3", int(tot9.get("hiddenScam") or 0) >= 3, tot9)
de = b.day_events("2000-01-01", "2100-12-31") or {}
dv = {e.get("tx") for e in de.get("events") or [] if e.get("k") == "외부 전송"}
dh = {e.get("tx") for e in de.get("hidden") or [] if e.get("k") == "외부 전송"}
check("B1·B2 날짜 색인(/api/day_events) = 세 줄 모두 숨김(events 에 없음 · hidden 에 있음)",
      not ({short(t) for t in SH} & dv) and {short(t) for t in SH} <= dh, (sorted(dv), sorted(dh)))
acts = f.get("dayActs") or {}
d_plain = time.strftime("%Y-%m-%d", time.gmtime(NOW - 5 * DAY + 9 * 3600))
check("B2 그날 기록 수(dayActs) = 숨김(h)으로 셈", (acts.get(d_plain) or {}).get("h", 0) >= 1 and (acts.get(d_plain) or {}).get("n", 0) == 0,
      acts.get(d_plain))
u9 = [e for e in vis if e.get("tx") == short(T_USDC)]
check("B3 정품 USDC 외부 전송 = 기록에 그대로(확인 필요 라벨)", len(u9) == 1 and (u9[0].get("of") or {}).get("c") == "pending", u9)
check("B3 정품 USDC 줄 = 날짜 색인 events 에 있음", short(T_USDC) in dv, sorted(dv))
real9 = [e for p in (f.get("positions") or []) for e in (p.get("events") or []) if e.get("tx") == short(T_REAL)]
check("B3 산 코인(REALT) 외부 전송 = 카드 기록에 그대로(확인 필요)", len(real9) == 1 and (real9[0].get("of") or {}).get("c") == "pending", real9)
check("B3 산 코인 줄 = 날짜 색인 events 에 있음", short(T_REAL) in dv, sorted(dv))
of_rows = {r.get("address"): r.get("status") for r in (f.get("outflows") or [])}
check("B3 보낸 내역 상태: 진짜 송금 = 확인 필요 · 가짜 = 사칭·스팸 로그(종전 그대로)",
      of_rows.get(DEST["usdc"]) == "pending" and of_rows.get(DEST["real"]) == "pending" and of_rows.get(DEST["plain"]) == "spam", of_rows)
for t9, nm9, tag9 in ((T_KEEP, "평범한 이름(보낸 내역 사칭·스팸 로그)", "B4"), (T_KEEPIMP, "사칭 심볼 'U5DТ'", "B5")):
    v9 = [e for e in vis if e.get("tx") == short(t9)]
    h9 = [e for e in hid if e.get("tx") == short(t9)]
    check(f"{tag9} 정상으로 복원한 {nm9} '외부 전송' = 기록에 그대로(숨김 목록 아님)", len(v9) == 1 and not h9, (v9, h9))
    check(f"{tag9} 정상으로 복원한 {nm9} = 날짜 색인 events 에 있음", short(t9) in dv and short(t9) not in dh, (sorted(dv), sorted(dh)))
check("B4 복원해도 보낸 내역 행 상태는 종전 그대로(spam — 이번 변경 범위 밖)", of_rows.get(DEST["keep"]) == "spam", of_rows)
T.finish()
