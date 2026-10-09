#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import sqlite3

os.environ["TJ_HEALTH"] = "0"
with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump({}, f)
import common

assert T.TMP in common.STATE_DIR
import ex_foreign as EF


def check(name, ok, detail=""):
    T.chk(bool(ok), name, None if ok else str(detail)[:500])


ROWS = [
    {"instId": "BTC-USDT-SWAP", "instType": "SWAP", "posSide": "net", "pos": "3", "avgPx": "59000", "markPx": "60000", "upl": "30",
     "lever": "5", "liqPx": "50000", "notionalUsd": "1800"},
    {"instId": "ETH-USDT-SWAP", "instType": "SWAP", "posSide": "short", "pos": "2", "avgPx": "2600", "markPx": "2500", "upl": "20",
     "lever": "3", "liqPx": "3000", "notionalUsd": ""},
    {"instId": "ZZ-USDT-SWAP", "instType": "SWAP", "posSide": "long", "pos": "7", "avgPx": "1", "markPx": "2", "upl": "0", "lever": "2", "liqPx": "1"},
]
CT = {"ETH-USDT-SWAP": 0.1}


def fake_okx_get(env, path, params=None):
    if path == "/api/v5/account/positions":
        return [dict(r) for r in ROWS]
    return []


class _FakeRcpt:
    @staticmethod
    def load(ex):
        return {"ct": dict(CT)} if ex == "okx" else {}


_saved = (EF._okx_get, EF.fut_rcpt, getattr(EF, "PACE", 0))
EF._okx_get = fake_okx_get
EF.fut_rcpt = _FakeRcpt
EF.PACE = 0
poss = None
try:
    EF._fut_okx({"TJ_OKX_KEY": "k", "TJ_OKX_SECRET": "s", "TJ_OKX_PASSPHRASE": "p"})
except Exception as e:
    print("참고: _fut_okx 뒤쪽 예외", type(e).__name__, str(e)[:120])
try:
    d = common.read_json(os.path.join(common.STATE_DIR, "futures_okx.json"), {})
    poss = {p["symbol"]: p for p in d.get("positions") or []}
except Exception as e:
    poss = {"_err": str(e)}
EF._okx_get, EF.fut_rcpt, EF.PACE = _saved
check("N0 수집기(_fut_okx)가 저장한 선물 파일의 포지션 3개", isinstance(poss, dict) and set(poss) == {"BTC-USDT-SWAP", "ETH-USDT-SWAP", "ZZ-USDT-SWAP"}, poss)
_on = getattr(EF, "_okx_notional", lambda p, pos, g: None)
if not poss or "BTC-USDT-SWAP" not in poss:
    poss = {r["instId"]: {"notional": _on(r, float(r["pos"]), CT.get)} for r in ROWS}
check("N1 OKX notionalUsd = 명목가($1,800 — 계약 3개 × 마크 $60,000 = $180,000 이 아님)", abs((poss["BTC-USDT-SWAP"].get("notional") or 0) - 1800) < 1e-6, poss)
check("N2 notionalUsd 없음 → 계약 크기 0.1 × 2계약 × 마크 2,500 = $500", abs((poss["ETH-USDT-SWAP"].get("notional") or 0) - 500) < 1e-6, poss)
check("N2 notionalUsd·계약 크기 둘 다 없음 → 명목 없음(None)", poss["ZZ-USDT-SWAP"].get("notional") is None, poss)
check("N2 순수 함수 — 음수 notionalUsd 는 절댓값 · 0·문자·비유한 = 계약 크기 경로",
      _on({"notionalUsd": "-120"}, 1, lambda i: None) == 120 and _on({"notionalUsd": "0", "markPx": "10", "instId": "A"}, 2, lambda i: 0.5) == 10
      and _on({"notionalUsd": "inf", "markPx": "x", "instId": "A"}, 2, lambda i: 0.5) is None and hasattr(EF, "_okx_notional"))

import web

pos9 = [{"ex": "okx", "symbol": "BTC-USDT-SWAP", "side": "LONG", "qty": 3, "mark": 60000.0, "notional": 1800.0},
        {"ex": "binance", "symbol": "ETHUSDT", "side": "SHORT", "qty": 2, "mark": 2500.0},
        {"ex": "okx", "symbol": "ZZ-USDT-SWAP", "side": "LONG", "qty": 7, "mark": 2.0, "notional": None},
        {"ex": "okx", "symbol": "BAD", "side": "LONG", "qty": 1, "mark": 3.0, "notional": "nan"}]
_fn = getattr(web, "_fut_notional", lambda p: float(p.get("qty") or 0) * float(p.get("mark") or 0))
vals = [_fn(p) for p in pos9]
check("N3 포지션 명목가 = 수집기 명목가 우선($1,800) · 바이낸스 = 수량 × 마크가($5,000) · OKX 명목가 모름(없음·비유한) = None(종전 계약 수 × 마크가 $14 · $3)",
      vals == [1800.0, 5000.0, None, None], vals)
_sum = getattr(web, "_fut_notional_sum", None)
check("N3 선물 요약 규모 = 하나라도 모르면 None(화면 '—') · 다 알면 합($6,800)",
      callable(_sum) and _sum(pos9) is None and _sum(pos9[:2]) == 6800.0 and _sum([]) == 0, None)
_js = open(os.path.join(T.ROOT, "web", "v2", "app.js"), encoding="utf-8").read()
check("N3 화면: 규모·롱/숏 칸이 None 이면 '—'(0 이 아님)", "fut.notional == null ? '—'" in _js and "f.notional != null" in _js
      and "f.longNotional == null ? '—'" in _js and "f.shortNotional == null ? '—'" in _js)

con = sqlite3.connect(common.DB_PATH)
con.executescript("""
CREATE TABLE IF NOT EXISTS asset_groups (group_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, norm_decimals INTEGER NOT NULL DEFAULT 18);
CREATE TABLE IF NOT EXISTS assets (asset_id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, chain TEXT, address TEXT, symbol TEXT, decimals INTEGER,
  confirmed INTEGER NOT NULL DEFAULT 0, hidden INTEGER NOT NULL DEFAULT 0, group_id INTEGER, UNIQUE (kind, chain, address));
""")
con.execute("INSERT INTO asset_groups (group_id, name) VALUES (501, 'BTC#501'), (502, 'BTC#502'), (503, 'BTC#503'), (7, 'ETH#7')")
con.execute("INSERT INTO assets (asset_id, kind, chain, address, symbol, hidden, group_id) VALUES (7, 'exchange_currency', NULL, 'a', 'BTC', 0, 501)")
con.execute("INSERT INTO assets (asset_id, kind, chain, address, symbol, hidden, group_id) VALUES (8, 'exchange_currency', NULL, 'b', 'btc', 0, 502)")
con.execute("INSERT INTO assets (asset_id, kind, chain, address, symbol, hidden, group_id) VALUES (9, 'token', 'eth', '0xspam', 'BTC', 1, 503)")
con.execute("INSERT INTO assets (asset_id, kind, chain, address, symbol, hidden, group_id) VALUES (501, 'exchange_currency', NULL, 'c', 'ETH', 0, 7)")
con.commit()
con.close()
common.atomic_write_json(web.DAILY_PX_PATH, {"_v": 1,
                                             "2026-09-01": {"p": {"501": 60000.0, "502": 60100.0, "503": 99999999.0, "7": 2500.0}},
                                             "2026-09-02": {"p": {"502": 61000.0}},
                                             "2026-09-03": {"p": {"7": 2500.0, "8": 61000.0}}})
ids = web._bench_btc_ids()
b = web.bench_series()
check("B1 BTC 일별 가격 찾기 = 그룹 id(501·502) — 자산 id(7·8)·숨긴 'BTC' 그룹(503)·다른 코인 그룹 아님", ids == {"501", "502"}, ids)
check("B1 비교선 일별 몫 = 그날 BTC 그룹 값 중앙값 · ETH 그룹 값(자산 id 7 과 같은 숫자 키)이 섞이지 않음 · 그룹 없는 날 = 없음",
      b.get("px") == {"2026-09-01": 60100.0, "2026-09-02": 61000.0} and (b.get("src") or {}).get("daily") == 2, b)
T.finish()
