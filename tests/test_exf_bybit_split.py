#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import time
from decimal import Decimal

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import common

assert T.TMP in common.STATE_DIR
import ex_foreign as EF

chk = T.chk
NOW = int(time.time())
DAY = 86400
ENV = {"TJ_BYBIT_KEY": "k", "TJ_BYBIT_SECRET": "s"}
UNI_ROWS = [{"symbol": "BTCUSDE", "baseCoin": "BTC", "quoteCoin": "USDE", "status": "Trading"},
            {"symbol": "ETHEUR", "baseCoin": "ETH", "quoteCoin": "EUR", "status": "Trading"},
            {"symbol": "SOLMNT", "baseCoin": "SOL", "quoteCoin": "MNT", "status": "Trading"},
            {"symbol": "ARBUSDT", "baseCoin": "ARB", "quoteCoin": "USDT", "status": "Trading"}]
S = {"uni_ok": True, "uni": list(UNI_ROWS), "rows": [], "calls": []}


def ex_row(i, sym, side="buy", px="100", qty="2", fee="0.01", fee_ccy=None):
    r = {"symbol": sym, "execId": f"e{i}", "execTime": str((NOW - 3600 + i) * 1000), "side": "Buy" if side == "buy" else "Sell",
         "execPrice": px, "execQty": qty, "execFee": fee}
    if fee_ccy is not None:
        r["feeCurrency"] = fee_ccy
    return r


def fake_http(url, headers=None, data=None, method=None, timeout=20):
    S["calls"].append(url)
    if "/v5/market/instruments-info" in url:
        if not S["uni_ok"]:
            raise OSError("합성: 목록 장애")
        return {"retCode": 0, "result": {"category": "spot", "list": [dict(x) for x in S["uni"]], "nextPageCursor": ""}}
    if "/v5/execution/list" in url:
        return {"retCode": 0, "result": {"list": [dict(x) for x in S["rows"]], "nextPageCursor": ""}}
    raise AssertionError("예상 밖 URL " + url[:80])


EF.http_json = fake_http
EF._gov_prepare = lambda *a, **k: None
EF.PACE = 0
UNI_P = os.path.join(common.STATE_DIR, "exf_bybit_symbols.json")


def n_uni():
    return sum(1 for u in S["calls"] if "instruments-info" in u)


def reset_uni(drop_file=True):
    u9 = getattr(EF, "_BB_UNI", None)
    if isinstance(u9, dict):
        u9.update(ts=0.0, fail=0.0, sym=None, path=None)
    if drop_file and os.path.exists(UNI_P):
        os.remove(UNI_P)


def run(st):
    st.pop("recon_hold", None)
    return EF.fills_bybit(ENV, st, NOW - 3 * DAY, NOW)


def bq(fills):
    return {f["id"]: (f["base"], f["quote"], f["fee_ccy"], f.get("late")) for f in fills}


S["rows"] = [ex_row(1, "BTCUSDE", qty="0.5", px="60000", fee="0.0005", fee_ccy="BTC"), ex_row(2, "ETHEUR", side="sell"), ex_row(3, "SOLMNT")]
st = {}
f1 = run(st)
got = bq(f1)
chk(got.get("bybit:e1", (None,))[:2] == ("BTC", "USDE"), "S1 BTCUSDE → (BTC, USDE)", got)
chk(got.get("bybit:e2", (None,))[:2] == ("ETH", "EUR"), "S1 ETHEUR → (ETH, EUR)", got)
chk(got.get("bybit:e3", (None,))[:3] == ("SOL", "MNT", "MNT"), "S1 SOLMNT → (SOL, MNT) · 수수료 통화 없으면 대금 통화", got)
chk(not any(v[0] in ("BTCUSDE", "ETHEUR", "SOLMNT") for v in got.values()), "S1 심볼 전체를 코인으로 적은 체결 없음", got)
chk(not st.get("bb_hold") and not st.get("recon_hold"), "S1 다 분해되면 보류·잔고 승격 보류 없음", st)

n0 = n_uni()
chk(n0 == 1 and os.path.exists(UNI_P), "S2 목록 조회 1회 + 캐시 파일(state/exf_bybit_symbols.json)", (n0, os.path.exists(UNI_P)))
run({})
chk(n_uni() == n0, "S2 같은 날 다시 = 목록 조회 0회(하루 캐시)", n_uni())
reset_uni(drop_file=False)
run({})
chk(n_uni() == n0, "S2 재기동해도 캐시 파일로(조회 0회)", n_uni())
S["rows"] = [ex_row(9, "NEWCOINZZZ")]
st9 = {}
run(st9)
chk(n_uni() == n0, "S2 목록에 없는 심볼 — 마지막 갱신 1시간 안 = 다시 안 부름", n_uni())
u9 = getattr(EF, "_BB_UNI", {})
if isinstance(u9, dict) and "ts" in u9:
    u9["ts"] = float(NOW - 2 * 3600)
run(st9)
chk(n_uni() == n0 + 1, "S2 목록에 없는 심볼 — 마지막 갱신 1시간 지남 = 한 번 일찍 갱신(새 상장)", n_uni())

reset_uni()
S["uni_ok"] = False
S["rows"] = [ex_row(11, "BTCUSDE", qty="0.1", px="60000"), ex_row(12, "ARBUSDT", qty="10", px="1")]
st3 = {}
f3 = run(st3)
got3 = bq(f3)
chk("bybit:e11" not in got3 and not any(v[0] == "BTCUSDE" for v in got3.values()),
    "S3 목록 장애 + 종전 쿼트로 못 뗌(BTCUSDE) = 체결 방출 안 함(유령 코인 없음)", got3)
chk(got3.get("bybit:e12", (None,))[:2] == ("ARB", "USDT"), "S3 종전 쿼트(USDT)는 목록 없이도 분해", got3)
chk(set((st3.get("bb_hold") or {})) == {"e11"} and "보류" in str(st3.get("recon_hold") or ""),
    "S3 보류 = 체결 상태 bb_hold · 잔고 승격 보류 표시(recon_hold)", st3)
run(st3)
chk(set((st3.get("bb_hold") or {})) == {"e11"}, "S3 다시 조회돼도 보류 1건 그대로(중복 없음)", st3.get("bb_hold"))

S["uni_ok"] = True
u9 = getattr(EF, "_BB_UNI", {})
if isinstance(u9, dict) and "fail" in u9:
    u9["fail"] = 0.0
f4 = run(st3)
ids4 = [f["id"] for f in f4]
got4 = bq(f4)
chk(got4.get("bybit:e11") == ("BTC", "USDE", "USDE", 1), "S4 목록 복구 → 보류분 (BTC, USDE) · 'late' 표시로 방출", got4)
chk(ids4.count("bybit:e11") == 1, "S4 보류분과 다시 조회된 같은 체결 = 한 번만 방출", ids4)
chk(not st3.get("bb_hold") and not st3.get("recon_hold"), "S4 보류 비움 · 잔고 승격 보류 해제", st3)
f4b = run(st3)
chk(bq(f4b).get("bybit:e11", (0, 0, 0, None))[3] is None, "S4 다음 주기 = 보통 체결(late 아님 — 보류분 재방출 없음)", bq(f4b))

keep = getattr(EF, "_bb_hold_keep", None)
st5 = {"fills": {"bb_hold": {"a": {"execId": "a"}}}}
ok5 = callable(keep) and keep(st5, {"bb_hold": {"a": {"execId": "a"}, "b": {"execId": "b"}}}) and set(st5["fills"]["bb_hold"]) == {"a", "b"}
ok5 = ok5 and callable(keep) and not keep(st5, {"bb_hold": {"a": {}}}) and not keep(st5, {})
chk(ok5, "S5 과거 창 확장이 보류한 체결을 정본 체결 상태에 옮김(새 것만 · 없으면 그대로)", st5)

import core

core.dm = lambda *a, **k: None
c = core.Core(common.load_config())
c._quote_usd = lambda q, ts: Decimal(1)
c.px.fx_at = lambda ms: 1380.0
c._consume_exf_fills({"exchange": "bybit", "fills": [f for f in f1 if f["id"] == "bybit:e1"]})
c.conn.commit()
legs = sorted((r[0], r[1]) for r in c.conn.execute(
    "SELECT a.symbol, p.qty_base FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.source_ns='bybit:trade' AND p.leg_kind!='gas'"))
syms = {r[0] for r in c.conn.execute("SELECT symbol FROM assets")}
chk(legs == [("BTC", str(int(0.5 * 10 ** 8))), ("USDE", str(-30000 * 10 ** 8))] and "BTCUSDE" not in syms,
    "S6 원장 = BTC +0.5 · USDE −30,000 두 다리 · 'BTCUSDE' 자산 없음", (legs, syms))
c.conn.close()
T.finish()
