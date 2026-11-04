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


def asset(addr, sym):
    ST["aid"] += 1
    a = ST["aid"]
    con.execute("INSERT INTO asset_groups (group_id, name, norm_decimals) VALUES (?,?,18)", (a, f"{sym}#{a}"))
    con.execute("INSERT INTO assets (asset_id, kind, chain, address, symbol, decimals, confirmed, hidden, group_id) VALUES (?,'exchange_currency',NULL,?,?,8,1,0,?)",
                (a, addr, sym, a))
    return a


def leg(ex, sid, a, qty):
    ST["pid"] += 1
    con.execute("INSERT INTO postings (posting_id, source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd,"
                " cost_krw, leg_kind, event, classifier_ver) VALUES (?,'exchange',?,?,0,?,?,?,?,NULL,NULL,'move_in','EXF_DEPOSIT',5)",
                (ST["pid"], f"{ex}:deposit", sid, NOW - 10 * DAY, a, f"exchange:{ex}", str(int(round(qty * 1e8)))))


bp = asset("bithumb:P", "P")
gp = asset("gate:P", "P")
bg = asset("bithumb:GHST", "GHST")
leg("bithumb", "d-1", bp, 42974)
leg("gate", "d-2", gp, 1000)
leg("bithumb", "d-3", bg, 500)
pos = {}
for a, loc, qb in con.execute("SELECT asset_id, location, qty_base FROM postings"):
    pos[(a, loc)] = pos.get((a, loc), 0) + int(qb)
for (a, loc), qb in pos.items():
    con.execute("INSERT OR REPLACE INTO positions (group_id, location, qty_norm, qty_unknown_norm, cost_alloc_usd) VALUES (?,?,?, '0', '0')",
                (a, loc, format(qb / 1e8, ".12f")))
con.commit()
con.close()

import expoint  # noqa: E402
import web  # noqa: E402

b = web.StateBuilder()
sp = b.spot
sp.rate, sp.rate_ts = RATE, time.time()
sp._ex_done = {"upbit", "binance", "bybit", "okx", "gate", "kucoin", "bithumb"}
for k, v in {"gate:P": 0.014, "binance:BTC": 70000.0}.items():
    sp.ex_usd[k], sp.ex_ts[k] = v, NOW
sp.upbit_krw, sp.upbit_alt = set(), {}
b.px.d["neg_ts"]["_fx"] = time.time()
st = T.safe(b.build)
f = (st or {}).get("fields") or {} if isinstance(st, dict) else {}
T.chk(bool(f), "빌드 성공", st if isinstance(st, dict) and st.get("_exc") else "fields 없음")
WD = json.load(open(paths.state("web_diag.json"), encoding="utf-8")) if os.path.exists(paths.state("web_diag.json")) else {}
rows = {c["key"]: c for c in f.get("coins") or []}
UPH = {(x.get("sym"), x.get("where")) for x in WD.get("unpriced_held") or []}

print("[P] 빗썸 포인트 = 원화 액면")
rp, rg, rh = rows.get(f"g{bp}") or {}, rows.get(f"g{gp}") or {}, rows.get(f"g{bg}") or {}
T.chk(abs(float(rp.get("price") or 0) - 1 / RATE) < 1e-12 and abs(float(rp.get("qty") or 0) - 42974) < 1e-6,
      "P1 빗썸 P 행 = 1원 ÷ 환율 1,400 · 수량 42,974(평가 ≈ $30.70 · 고치기 전 = 0)", rp)
T.chk(str(rp.get("pxSrc") or "").startswith("cex:"), "P1b 출처 = 그 거래소(cex:빗썸)", rp.get("pxSrc"))
T.chk(abs(float(rg.get("price") or 0) - 0.014) < 1e-12, "P2 게이트 동명 코인 'P' = 게이트 자체 시세 $0.014(포인트 액면 안 섞임)", rg)
T.chk(not rh.get("price") and ("GHST" in (f.get("unpricedSyms") or [])), "P3 빗썸 시세 없는 다른 코인 = 종전 그대로 시세 없음", (rh, f.get("unpricedSyms")))
T.chk("P" not in (f.get("unpricedSyms") or []) and not any(s == "P" for s, _w in UPH),
      "P4 '시세 없음' 목록·헬스 재료(unpriced_held)에 P 없음", (f.get("unpricedSyms"), sorted(UPH)))
T.chk(sp.ex_price("bithumb", "P") is None, "P5 ex_price(빗썸 P) = 없음 — 참고가·거래 시작 전 평가 재료엔 안 섞음(expoint.own_px 만)")
T.chk(expoint.own_px(sp, "gate", "P") == 0.014 and expoint.own_px(sp, "bithumb", "GHST") is None, "P6 own_px = 포인트 밖은 ex_price 그대로")
rate0 = sp.rate
sp.rate = 0
T.chk(expoint.own_px(sp, "bithumb", "P") is None, "P7 환율 없음 = 시세 없음(가짜 값 안 만듦)")
sp.rate = rate0
T.finish()
