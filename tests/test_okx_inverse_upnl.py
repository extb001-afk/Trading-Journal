#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import time

with open(os.path.join(T.TMP, "config.json"), "w") as f:
    json.dump({"chains": {}, "wallets": []}, f)
import common

chk = T.chk
INV = {"instType": "SWAP", "instId": "BTC-USD-SWAP", "ccy": "BTC", "pos": "200", "posSide": "long", "avgPx": "55000", "markPx": "60000",
       "upl": "0.0333333333", "lever": "5", "liqPx": "40000", "notionalUsd": "20000"}
LIN = {"instType": "SWAP", "instId": "BTC-USDT-SWAP", "ccy": "USDT", "pos": "10", "posSide": "net", "avgPx": "59000", "markPx": "60000",
       "upl": "120", "lever": "10", "liqPx": "50000", "notionalUsd": "6000"}

print("[O1] 수집기")
import ex_foreign as XF
CAP = {}
XF._okx_get = lambda env, path, params=None: [dict(INV), dict(LIN)] if path == "/api/v5/account/positions" else []
XF._fut_write = lambda ex, wallet, poss, ev, cur: CAP.update(poss=poss)
XF._px_safe = lambda ex, fn: None
XF.PACE = 0
try:
    XF.bf_engine.SINCE.target = lambda ex: None
except Exception:
    pass
T.safe(XF._fut_okx, {})
P = {p["symbol"]: p for p in CAP.get("poss") or []}
chk(P.get("BTC-USD-SWAP", {}).get("settle") == "BTC" and P.get("BTC-USDT-SWAP", {}).get("settle") == "USDT"
    and P.get("BTC-USD-SWAP", {}).get("inst_type") == "SWAP" and abs(float(P["BTC-USD-SWAP"]["upnl"]) - 0.0333333333) < 1e-12,
    "O1 수집기: settle(BTC·USDT)·instType 보존 · upl 원래 단위(코인) 그대로", CAP.get("poss"))

print("[O2~O4] web")
import web
now = time.time()


def write_okx(poss):
    common.atomic_write_json(os.path.join(common.STATE_DIR, "futures_okx.json"),
                             {"ts": int(now), "wallet": {"balance": None}, "positions": poss, "events": []})


b = web.StateBuilder()
web.BUILDER = b
write_okx(CAP.get("poss") or [])
b.spot.usd["BTC"], b.spot.usd_ts["BTC"] = 60000.0, now
v = T.safe(b._futures_view) or {}
pv = {p["sym"]: p for p in v.get("positions") or []}
chk(abs((pv.get("BTC-USD-SWAP") or {}).get("upnl", 0) - 2000.0) < 0.01 and abs((pv.get("BTC-USDT-SWAP") or {}).get("upnl", 0) - 120.0) < 0.01
    and abs((v.get("upnl") or 0) - 2120.0) < 0.01 and not v.get("upnlPartial"),
    "O2 역계약 0.0333 BTC × $60,000 = $2,000 · 선형 $120 · 합계 $2,120(종전 $120.03)", (v.get("upnl"), [(k, p.get("upnl")) for k, p in pv.items()]))
b.spot.usd.pop("BTC", None)
b.spot.usd_ts.pop("BTC", None)
v = T.safe(b._futures_view) or {}
pv = {p["sym"]: p for p in v.get("positions") or []}
inv9 = pv.get("BTC-USD-SWAP") or {}
chk(inv9.get("upnl", 0) is None and inv9.get("upnlWhy") and abs((v.get("upnl") or 0) - 120.0) < 0.01 and v.get("upnlPartial") is True,
    "O3 BTC 시세 없음 = 그 포지션 null + 사유 · 합계 = 아는 것만 + 일부 모름(0 아님)", (v.get("upnl"), v.get("upnlPartial"), inv9))
b.spot.usd["BTC"], b.spot.usd_ts["BTC"] = 60000.0, now
b.spot.usd["ETH"], b.spot.usd_ts["ETH"] = 3000.0, now
old = [{"symbol": "BTC-USD-SWAP", "side": "LONG", "qty": 1, "entry": 1, "mark": 60000, "upnl": 0.01, "leverage": "3", "liq": 0, "notional": 100},
       {"symbol": "ETH-USD-261226", "side": "SHORT", "qty": 1, "entry": 1, "mark": 3000, "upnl": -0.5, "leverage": "3", "liq": 0, "notional": 100},
       {"symbol": "BTC-USDT-SWAP", "side": "LONG", "qty": 1, "entry": 1, "mark": 60000, "upnl": 7, "leverage": "3", "liq": 0, "notional": 100},
       {"symbol": "BTC-USDT", "side": "LONG", "qty": 1, "entry": 1, "mark": 60000, "upnl": 3, "leverage": "3", "liq": 0, "notional": 100}]
write_okx(old)
v = T.safe(b._futures_view) or {}
pv = {p["sym"]: p.get("upnl") for p in v.get("positions") or []}
chk(pv == {"BTC-USD-SWAP": 600.0, "ETH-USD-261226": -1500.0, "BTC-USDT-SWAP": 7.0, "BTC-USDT": 3.0} and abs((v.get("upnl") or 0) - (600 - 1500 + 10)) < 0.01,
    "O4 옛 스냅숏: X-USD-SWAP·X-USD-YYMMDD = 코인 정산(× 시세) · USDT 상품 = 그대로", pv)

print("[O5] lev_view")
import lev_view
write_okx(CAP.get("poss") or [])
fut9 = {"okx": common.read_json(os.path.join(common.STATE_DIR, "futures_okx.json"), {})}
rows = []
try:
    out9 = lev_view.build({"items": []}, fut9, lambda s: 60000.0 if str(s).upper() == "BTC" else (1.0 if str(s).upper() in ("USDT", "USDC") else None),
                          10.0, None, now)
    rows = [r for r in out9.get("rows") or [] if isinstance(r, dict)]
except Exception as e:
    rows = [{"err": repr(e)}]
lv = {str(r.get("symbol") or r.get("sym") or r.get("id")): r.get("upnlUsd") for r in rows}
inv_l = [u for k, u in lv.items() if "BTC-USD-SWAP" in k]
chk(inv_l and abs(inv_l[0] - 2000.0) < 0.01, "O5 레버리지 화면 = 같은 포지션 $2,000(settle 칸이 생겨도 이중 환산 없음)", lv)

print("[O6] 화면")
APP = os.path.join(T.ROOT, "web", "v2", "app.js")
src9 = open(APP, encoding="utf-8").read() if os.path.exists(APP) else ""
chk(src9 and "m(num(p.upnl)" not in src9 and "m(num(fut.upnl)" not in src9 and "m(num(f.upnl)" not in src9 and src9.count("upnlH(") >= 5,
    "O6 선물 평가손익 칸 5곳 = null 이면 '—'(사유 툴팁) — 0 으로 그리지 않음", src9.count("upnlH("))
T.finish()
