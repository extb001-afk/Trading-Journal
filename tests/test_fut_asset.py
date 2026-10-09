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
import core
import ex_foreign

core.dm = lambda *a, **k: None
core.Core.EXF_REVERT_LOG = os.path.join(common.STATE_DIR, "exf_recon_revert.jsonl")
chk = T.chk
E8 = 10 ** 8
NOW = int(time.time())

print("[A] 수집기가 정산 자산을 남김")


def _bn(url, headers=None, *a, **k):
    if "/fapi/v2/account" in url:
        return {"totalWalletBalance": "0", "availableBalance": "0", "totalInitialMargin": "0", "positions": []}
    if "/fapi/v2/positionRisk" in url:
        return []
    if "/fapi/v1/income" in url:
        return [{"tranId": "1", "incomeType": "REALIZED_PNL", "time": (NOW - 600) * 1000, "income": "50", "symbol": "AAAUSDT", "asset": "USDT"},
                {"tranId": "2", "incomeType": "COMMISSION", "time": (NOW - 600) * 1000 + 5, "income": "-0.02", "symbol": "AAAUSDT", "asset": "BNB"},
                {"tranId": "3", "incomeType": "FUNDING_FEE", "time": (NOW - 500) * 1000, "income": "-0.1", "symbol": "AAAUSDT"}]
    return []


_bn._tj_test_mock = True
ex_foreign._http_json_err = _bn
ex_foreign._gov_prepare = lambda *a, **k: None
ex_foreign._px_safe = lambda *a, **k: None
ex_foreign.PACE = 0
common.atomic_write_json(os.path.join(common.STATE_DIR, "futures_binance.json"), {"ts": 0, "events": [], "cursor": {"income": (NOW - 3600) * 1000}})
ex_foreign._fut_binance({"TJ_BINANCE_KEY": "k", "TJ_BINANCE_SECRET": "s"})
fb = json.load(open(os.path.join(common.STATE_DIR, "futures_binance.json")))
am = {e["uid"].split(":")[1]: e.get("asset") for e in fb["events"]}
chk(am == {"1": "USDT", "2": "BNB", "3": None}, "A1 바이낸스 income asset → 이벤트 asset(USDT·BNB) · 응답에 없으면 칸 없음", am)


def _okx(env, path, params=None):
    if path == "/api/v5/account/positions":
        return []
    if path == "/api/v5/account/bills":
        return [{"billId": "b1", "ts": str((NOW - 400) * 1000), "pnl": "0.01", "fee": "-0.0001", "type": "2", "instId": "BTC-USD-SWAP", "ccy": "BTC"},
                {"billId": "b2", "ts": str((NOW - 300) * 1000), "pnl": "3", "fee": "-0.5", "type": "2", "instId": "AAA-USDT-SWAP", "ccy": "USDT"}]
    return []


ex_foreign._okx_get = _okx
try:
    ex_foreign.bf_engine.SINCE.target = lambda ex: None
except AttributeError:
    pass
common.atomic_write_json(os.path.join(common.STATE_DIR, "futures_okx.json"), {"ts": 0, "events": [], "cursor": {"bills": (NOW - 3600) * 1000}})
ex_foreign._fut_okx({"TJ_OKX_KEY": "k", "TJ_OKX_SECRET": "s", "TJ_OKX_PASSPHRASE": "p"})
fo = json.load(open(os.path.join(common.STATE_DIR, "futures_okx.json")))
ao = sorted((e["uid"], e.get("asset")) for e in fo["events"])
chk(ao == [("ok:b1:f", "BTC"), ("ok:b1:p", "BTC"), ("ok:b2:f", "USDT"), ("ok:b2:p", "USDT")], "A2 OKX bills ccy → 이벤트 asset(코인 마진 BTC · USDT)", ao)

print("[L] 원장 — 정산 자산 그대로")
C = core.Core(common.load_config())
C._quote_usd = lambda q, ts: Decimal(1)
C.EXF_INIT_PHASE = 5
SEQ = {"t": NOW - 1700}


def tick(d=10):
    SEQ["t"] += d
    return SEQ["t"]


def post(ex, t, sym, qty, sid):
    aid = C._exf_asset(ex, sym)
    qb = int(Decimal(str(qty)) * E8)
    C.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base,"
                   " cost_usd, cost_krw, leg_kind, event, classifier_ver) VALUES ('exchange',?,?,0,?,?,?,?,NULL,NULL,'move_in','EXF_DEPOSIT',?)",
                   (f"{ex}:deposit", sid, int(t), aid, f"exchange:{ex}", str(qb), core.CLASSIFIER_VER))
    C._bump_position(aid, qb, f"exchange:{ex}")
    C.conn.commit()


def futfile(ex, events):
    common.atomic_write_json(os.path.join(common.STATE_DIR, f"futures_{ex}.json"), {
        "ts": int(time.time()),
        "events": [dict({"t": int(t) * 1000 + 123, "symbol": s, "kind": k, "amount": a, "uid": f"u{i}"}, **({"asset": asx} if asx else {}))
                   for i, (t, s, k, a, asx) in enumerate(events)]})
    C.__dict__.pop("_exf_fut_cache", None)


def recon(ex, bal, sources=("futures",)):
    bts = tick()
    st = common.read_json(os.path.join(common.STATE_DIR, "exf_state.json"), {})
    st.setdefault(ex, {"seen": {}, "backfilled_until": NOW, "fills": {"backfilled_until": NOW}})
    common.atomic_write_json(os.path.join(common.STATE_DIR, "exf_state.json"), st)
    common.atomic_write_json(os.path.join(common.STATE_DIR, f"exf_balances_{ex}.json"), {"ts": bts, "balances": bal, "sources": list(sources)})
    C._drain_at = bts + 5
    C._last_exfrecon = 0
    C.exf_recon_pass({"ex"})
    return bts


def rows(ex, sym, ns):
    return sorted((int(r[0]), Decimal(int(r[1])) / E8) for r in C.conn.execute(
        "SELECT p.event_ts, p.qty_base FROM postings p JOIN assets a USING(asset_id) WHERE p.source_ns=? AND p.event='EXF_ADJUST'"
        " AND upper(a.symbol)=? AND p.location=?", (f"{ex}:{ns}", sym, f"exchange:{ex}")).fetchall())


def total(ex, sym):
    v = C.conn.execute("SELECT SUM(CAST(p.qty_base AS INTEGER)) FROM postings p JOIN assets a USING(asset_id) WHERE p.location=? AND upper(a.symbol)=?",
                       (f"exchange:{ex}", sym)).fetchone()[0]
    return Decimal(int(v or 0)) / E8


futfile("binance", [])
t0 = tick(0) - 3000
post("binance", t0, "USDT", 1000, "d1")
post("binance", t0, "BNB", 1, "d2")
recon("binance", {"USDT": 1000, "BNB": 1})
tf = tick(5)
futfile("binance", [(tf, "AAAUSDT", "REALIZED", 50.0, "USDT"), (tf + 1, "AAAUSDT", "FEE", -0.02, "BNB")])
b2 = recon("binance", {"USDT": 1050, "BNB": 0.98})
fu, fbn = rows("binance", "USDT", "futpnl"), rows("binance", "BNB", "futpnl")
ru, rb = rows("binance", "USDT", "recon"), rows("binance", "BNB", "recon")
chk(fu == [(tf, Decimal(50))] and not [x for x in ru if x[0] == b2], "L1 USDT 선물 줄 = 정확히 +50 · USDT 대사 줄 없음(종전: +49.98 + 대사 +0.02)", (fu, ru))
chk(fbn == [(tf + 1, Decimal("-0.02"))] and not [x for x in rb if x[0] == b2] and total("binance", "BNB") == Decimal("0.98"),
    "L2 BNB 수수료 −0.02 = BNB 선물 줄 한 번(정산 시각) · BNB 대사 줄 없음 · 원장 BNB = 실잔고", (fbn, rb, total("binance", "BNB")))
chk(total("binance", "USDT") == Decimal(1050), "L3 원장 USDT = 실잔고(종전: 1,049.98 — USDT 대사 +0.02 가 소액 보류로 남음)", total("binance", "USDT"))
tf2 = tick(5)
futfile("binance", [(tf, "AAAUSDT", "REALIZED", 50.0, "USDT"), (tf + 1, "AAAUSDT", "FEE", -0.02, "BNB"), (tf2, "AAAUSDT", "FUNDING", -0.5, None),
                    (tf2 + 1, "AAAUSD_PERP", "REALIZED", 0.01, "AAA")])
recon("binance", {"USDT": 1049.5, "BNB": 0.98, "AAA": 0.01})
chk((tf2, Decimal("-0.5")) in rows("binance", "USDT", "futpnl") and not rows("binance", "AAA", "futpnl"),
    "L4 자산 없는 옛 이벤트 = 계약 통화(USDT) · 코인 정산 계약(AAAUSD_PERP · AAA) = 종전처럼 선물 줄 없음(대사가 흡수)", (rows("binance", "USDT", "futpnl"), rows("binance", "AAA", "futpnl")))

print("[D] 화면 — 표시용 달러")
import web
px = {"BNB": 600.0, "BTC": 60000.0}
e1 = web.fut_ev_usd({"amount": -0.02, "asset": "BNB", "kind": "FEE"}, px.get)
e2 = web.fut_ev_usd({"amount": 0.01, "asset": "BTC", "kind": "REALIZED"}, px.get)
e3 = web.fut_ev_usd({"amount": -0.5, "asset": "USDT", "kind": "FEE"}, px.get)
e4 = web.fut_ev_usd({"amount": -0.5, "kind": "FEE"}, px.get)
e5 = web.fut_ev_usd({"amount": -0.02, "asset": "XYZ", "kind": "FEE"}, px.get)
chk(abs(e1["amount"] + 12.0) < 1e-9 and e1["amt_native"] == -0.02 and abs(e2["amount"] - 600.0) < 1e-9 and e3["amount"] == -0.5 and e4["amount"] == -0.5
    and e5 is None, "D1 BNB −0.02 → −$12(원래 수량 amt_native) · BTC 0.01 → $600(종전 $0.01) · USDT·옛 이벤트 그대로 · 시세 모름 = 뺌", (e1, e2, e3, e4, e5))
T.finish()
