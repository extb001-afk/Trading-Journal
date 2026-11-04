#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import time  # noqa: E402

W = "0x" + "ab" * 20
NOW = int(time.time())
DAY = 86400
RATE = 1400.0
shutil.copytree(os.path.join(T.ROOT, "seed"), os.path.join(T.TMP, "seed"), dirs_exist_ok=True)
json.dump({"wallets": [{"type": "evm", "chain": "base", "address": W, "label": "w"}], "backfill_months": 3, "chains": {}},
          open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
import paths  # noqa: E402

assert T.TMP in paths.STATE_DIR
import db as dbm  # noqa: E402

con = dbm.open_db(os.path.join(paths.STATE_DIR, "ledger.db"))
ST = {"aid": 0, "pid": 0}
DEC = {}


def asset(addr, sym):
    ST["aid"] += 1
    a = ST["aid"]
    con.execute("INSERT INTO asset_groups (group_id, name, norm_decimals) VALUES (?,?,18)", (a, f"{sym}#{a}"))
    con.execute("INSERT INTO assets (asset_id, kind, chain, address, symbol, decimals, confirmed, hidden, group_id) VALUES (?,'exchange_currency',NULL,?,?,8,1,0,?)",
                (a, addr, sym, a))
    DEC[a] = 8
    return a


def leg(ns, sid, seq, ts, a, qty, lk, ev, cost=None):
    ST["pid"] += 1
    con.execute("INSERT INTO postings (posting_id, source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd,"
                " cost_krw, leg_kind, event, classifier_ver) VALUES (?,'exchange',?,?,?,?,?,'exchange:binance',?,?,NULL,?,?,5)",
                (ST["pid"], ns, sid, seq, ts, a, str(int(round(qty * 10 ** DEC[a]))), None if cost is None else repr(float(cost)), lk, ev))


bu = asset("binance:USDT", "USDT")
bd = asset("binance:DSTX", "DSTX")
bg = asset("binance:BIGX", "BIGX")
bn = asset("binance:NOCX", "NOCX")
leg("binance:deposit", "d-1", 0, NOW - 30 * DAY, bu, 2000, "move_in", "EXF_DEPOSIT")
leg("binance:trade", "binance:DSTXUSDT:1", 0, NOW - 20 * DAY, bu, -14, "disp", "EXF_BUY", 14)
leg("binance:trade", "binance:DSTXUSDT:1", 1, NOW - 20 * DAY, bd, 70, "acq", "EXF_BUY", 14)
leg("binance:trade", "binance:BIGXUSDT:2", 0, NOW - 19 * DAY, bu, -900, "disp", "EXF_BUY", 900)
leg("binance:trade", "binance:BIGXUSDT:2", 1, NOW - 19 * DAY, bg, 300, "acq", "EXF_BUY", 900)
leg("binance:deposit", "d-2", 0, NOW - 18 * DAY, bn, 5000, "move_in", "EXF_DEPOSIT")
pos = {}
for a, loc, qb in con.execute("SELECT asset_id, location, qty_base FROM postings"):
    pos[(a, loc)] = pos.get((a, loc), 0) + int(qb)
for (a, loc), qb in pos.items():
    con.execute("INSERT OR REPLACE INTO positions (group_id, location, qty_norm, qty_unknown_norm, cost_alloc_usd) VALUES (?,?,?, '0', '0')",
                (a, loc, format(qb / 10 ** DEC[a], ".12f")))
con.commit()
con.close()
ACC = [{"currency": "KRW", "balance": "1.5", "locked": "0", "avg_buy_price": "0", "unit_currency": "KRW"},
       {"currency": "OLDP", "balance": "10000", "locked": "0", "avg_buy_price": "15", "unit_currency": "KRW"},
       {"currency": "NOAV", "balance": "60", "locked": "40", "avg_buy_price": "0", "unit_currency": "KRW"},
       {"currency": "BTCQ", "balance": "50", "locked": "0", "avg_buy_price": "0.0002", "unit_currency": "BTC"},
       {"currency": "DEADX", "balance": "86000", "locked": "0", "avg_buy_price": "2340", "unit_currency": "KRW"},
       {"currency": "FALLX", "balance": "10000", "locked": "0", "avg_buy_price": "1400", "unit_currency": "KRW"}]
json.dump({"ts": NOW, "accounts": ACC}, open(paths.state("upbit_balances.json"), "w"))

import health  # noqa: E402
import web  # noqa: E402
from view_pending import upbit_avg_usd  # noqa: E402

b = web.StateBuilder()
sp = b.spot
sp.rate, sp.rate_ts = RATE, time.time()
sp._ex_done = {"upbit", "binance", "bybit", "okx", "gate", "kucoin", "bithumb"}
for k, v in {"binance:OLDP": 0.08, "bybit:OLDP": 0.08, "binance:NOAV": 10.0, "okx:BTCQ": 15.0, "binance:FALLX": 0.06}.items():
    sp.ex_usd[k], sp.ex_ts[k] = v, NOW
sp.upbit_krw, sp.upbit_alt = set(), {}
sp.ex_dead_syms = {"binance": {"DSTX", "BIGX", "NOCX"}}
b.px.d["neg_ts"]["_fx"] = time.time()
st = T.safe(b.build)
f = (st or {}).get("fields") or {} if isinstance(st, dict) else {}
T.chk(bool(f), "빌드 성공", st if isinstance(st, dict) and st.get("_exc") else "fields 없음")
WD = json.load(open(paths.state("web_diag.json"), encoding="utf-8")) if os.path.exists(paths.state("web_diag.json")) else {}
rows = {c["key"]: c for c in f.get("coins") or []}
UPH = {x.get("sym"): x for x in WD.get("unpriced_held") or []}
EDH = {x.get("sym"): x for x in WD.get("ex_dead_held") or []}
HS = health.settings({"health": {"units": ["tj-web"]}})


def judge(wd):
    obs = {"now": NOW, "pm2": {"tj-web": {"status": "online", "restarts": 0, "pid": 1}}, "bal_mem": {}, "prev_inc": {}, "sources": [],
           "webdiag": dict({"ts": NOW, "unpriced_held": [], "ex_dead_held": [], "proof_div": []}, **wd)}
    return next((c for c in health.evaluate(obs, HS) if c["id"] == "price:unpriced"), {})


print("[A] 24h 거래 0 페어 보유 = 같은 무게 문턱")
d0, g0, n0 = EDH.get("DSTX") or {}, EDH.get("BIGX") or {}, EDH.get("NOCX") or {}
T.chk(abs(float(d0.get("cost") or 0) - 14) <= 0.01 and abs(float(g0.get("cost") or 0) - 900) <= 0.01 and not float(n0.get("cost") or 0),
      "A0 재료(ex_dead_held)에 원가(평단 × 수량) — DSTX $14 · BIGX $900 · NOCX 0(원가 모름)", EDH)
T.chk(set(EDH) == {"DSTX", "BIGX", "NOCX"}, "A0b 거래 0 페어 보유 목록 자체는 전부(먼지·무게 모름 포함 · 판정만 문턱)", sorted(EDH))
ca = judge({"ex_dead_held": [d0]})
T.chk(ca.get("level") == "ok", "A1 먼지($14) 거래 0 페어 = 주의 없음(고치기 전 = 건수만으로 주의)", (ca.get("level"), ca.get("title")))
cb = judge({"ex_dead_held": [g0]})
T.chk(cb.get("level") == "warn" and "BIGX" in str(cb.get("detail")) and "$900" in str(cb.get("detail")),
      "A2 원가 큰($900) 거래 0 페어 = 주의 · 상세에 무게", (cb.get("level"), cb.get("detail")))
cc = judge({"ex_dead_held": [n0]})
T.chk(cc.get("level") == "ok", "A3 무게 모름(원가·참고가 없음) = 주의 없음", (cc.get("level"), cc.get("detail")))
cr = judge({"ex_dead_held": [{"ex": "binance", "sym": "REFX", "qty": 1000.0, "cost": 0.0, "ref": 0.6}]})
T.chk(cr.get("level") == "warn", "A4 원가 모름 · 참고 단가 × 수량 $600 = 주의(참고가 = 단가)", (cr.get("level"), cr.get("detail")))
call = judge({"ex_dead_held": [d0, g0, n0]})
T.chk(call.get("title") == "시세 없는 실보유 1건" and list((call.get("ack") or {}).values()) == [900.0],
      "A5 셋 중 BIGX 만 건수·닫기 재료(금액 = 무게)", (call.get("title"), call.get("ack")))

print("[B] 업비트 단독 잔고 = 참고가 무게 · 업비트 평단 원가는 상한만")
po, pn, pq = UPH.get("OLDP") or {}, UPH.get("NOAV") or {}, UPH.get("BTCQ") or {}
T.chk(not float(po.get("cost") or 0) and abs(float(po.get("ref") or 0) - 15 * 10000 / RATE) <= 0.01,
      "B0 OLDP 재료: 참고가 $800 > 업비트 평단 원가(15원 × 10,000 ÷ 1,400 ≈ $107.14) → 무게 = 원가 상한 $107.14 · cost 칸 0", po)
T.chk(not float(pn.get("cost") or 0) and abs(float(pn.get("ref") or 0) - 1000) <= 0.01 and not float(pq.get("cost") or 0),
      "B0b 평단 0(NOAV)·원화 마켓 아님(BTCQ) = 원가 0 · 참고가 종전", (pn, pq))
ro = rows.get("ub:OLDP") or {}
T.chk(ro and not ro.get("price") and not ro.get("avg") and ro.get("pxRef"), "B0c 보유 행 = 평가 0 · 화면 평단 0 · 참고가 표시 그대로", ro)
T.chk((f.get("unpricedSyms") or [])[:5] == ["NOAV", "BIGX", "BTCQ", "FALLX", "OLDP"],
      "B0d 화면 '시세 없음' 순서 = 무게 순(OLDP = 상한 $107 자리 · 의도한 표시 순서 변화)", f.get("unpricedSyms"))
c1 = judge({"unpriced_held": [po]})
T.chk(c1.get("level") == "ok", "B1 동명 딴 코인 꼴(참고가 $800 > 업비트 평단 원가 $107) = 상한 $107 → 주의 없음(고치기 전 = 주의)",
      (c1.get("level"), c1.get("detail")))
c2 = judge({"unpriced_held": [pn]})
T.chk(c2.get("level") == "warn" and "NOAV" in str(c2.get("detail")), "B2 원가 모름 = 참고가($1,000) 무게 그대로 → 주의(종전)", c2.get("detail"))
c3 = judge({"unpriced_held": [{"sym": "WALX", "where": "지갑", "qty": 10.0, "cost": 600.0, "ref": 0.0, "ent": "base:0x" + "0c" * 20}]})
c4 = judge({"unpriced_held": [{"sym": "WALY", "where": "지갑", "qty": 10.0, "cost": 50.0, "ref": 5000.0, "ent": "base:0x" + "0d" * 20}]})
T.chk(c3.get("level") == "warn" and c4.get("level") == "ok", "B3 지갑 토큰 행도 같은 규칙(원가 $600 = 주의 · 원가 $50 + 참고가 $5,000 = 원가 우선 · 주의 없음)",
      (c3.get("level"), c4.get("level")))
ck = judge({"unpriced_held": [pn, po]})
T.chk(list((ck.get("ack") or {}).values()) == [1000.0], "B4 닫기 재료 = 주의 항목만 · 금액 = 무게", ck.get("ack"))
pd, pf = UPH.get("DEADX") or {}, UPH.get("FALLX") or {}
T.chk(judge({"unpriced_held": [pd]}).get("level") == "ok" and not float(pd.get("ref") or 0),
      "B6 상폐 코인 꼴(업비트 평단 원가 ≈$14만 · 다른 거래소 시세 없음) = 주의 없음(옛 원가로 울리지 않음 · 종전과 같음)", pd)
T.chk(abs(float(pf.get("ref") or 0) - 600) <= 0.01 and judge({"unpriced_held": [pf]}).get("level") == "warn",
      "B7 떨어진 코인 꼴(참고가 $600 < 원가 $10,000) = 지금 가치 $600 무게 → 주의", pf)
c0 = judge({})
T.chk(c0.get("level") == "ok" and "원가(모르면 참고가) $500" in str(c0.get("detail")), "B5 없음 문구 = 무게 규칙", c0.get("detail"))

print("[U] upbit_avg_usd")
u = upbit_avg_usd(ACC + [{"currency": "bad", "avg_buy_price": "x", "unit_currency": "KRW"}, "junk", {"currency": "NEG", "avg_buy_price": "-5", "unit_currency": "KRW"}], RATE)
T.chk(set(u) == {"OLDP", "DEADX", "FALLX"} and abs(u["OLDP"] - 15 / RATE) < 1e-12, "U1 원화 마켓 양수 평단만(0·숫자 아님·음수·BTC 마켓·이상한 줄 = 빠짐)", u)
T.chk(upbit_avg_usd(ACC, None) == {} and upbit_avg_usd(ACC, 0) == {} and upbit_avg_usd(None, RATE) == {} and upbit_avg_usd(ACC, "x") == {},
      "U2 환율 없음·0·이상 / 계좌 없음 = 빈 표(무게는 참고가로)")
T.finish()
