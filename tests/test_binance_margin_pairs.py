#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
import urllib.parse  # noqa: E402

json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import paths  # noqa: E402
import exf_binance as B  # noqa: E402

chk = T.chk
NOW = int(time.time())
T.patch_moved("PACE", 0, ("exf_",))
T.patch_moved("_gov_prepare", lambda *_a, **_k: None, ("exf_",))
T.patch_moved("_srv_ms", lambda *_a, **_k: NOW * 1000, ("exf_",))
ENV = {"TJ_BINANCE_KEY": "k", "TJ_BINANCE_SECRET": "s"}
UNI = {"ETHUSDT": ("ETH", "USDT", "TRADING", 1), "ETHBTC": ("ETH", "BTC", "TRADING", 1), "ETHTRY": ("ETH", "TRY", "TRADING", 1),
       "ETHEUR": ("ETH", "EUR", "TRADING", 0), "BTCUSDT": ("BTC", "USDT", "TRADING", 1)}
MCALLS = []


def http(url, headers=None, **_k):
    u = urllib.parse.urlparse(url)
    q = dict(urllib.parse.parse_qsl(u.query))
    if u.path == "/api/v3/exchangeInfo":
        raise RuntimeError("목록 갱신 안 함(시험)")
    if u.path == "/api/v3/account":
        return {"balances": []}
    if u.path in ("/api/v3/myTrades", "/api/v3/openOrders"):
        return []
    if u.path == "/sapi/v1/margin/account":
        return {"userAssets": [{"asset": "ETH", "free": "1", "locked": "0", "borrowed": "0", "interest": "0", "netAsset": "1"}]}
    if u.path == "/sapi/v1/margin/isolated/account":
        return {"assets": []}
    if u.path == "/sapi/v1/margin/myTrades":
        MCALLS.append((q["symbol"], q["isIsolated"]))
        if q["symbol"] == "ETHTRY" and int(q["fromId"]) == 0:
            return [{"id": 7, "time": (NOW - 3600) * 1000, "isBuyer": True, "price": "100000", "qty": "1", "commission": "0",
                     "commissionAsset": "TRY"}]
        return []
    raise AssertionError(u.path)


T.patch_moved("http_json", http, ("exf_",))


def run(uni):
    B._BN_UNI.update(ts=float(NOW) if uni else 0.0, fail=float(NOW), sym=dict(uni) if uni else None, path=paths.state(B.BN_UNI_NAME))
    MCALLS.clear()
    st = {"backfilled_until": NOW - 600, "bn_sweep_full": NOW, "bn_bal": {}, "bn_acct_at": NOW - 600}
    out = B.fills_binance(ENV, st, NOW - 30 * 86400, NOW)
    return {s for s, iso in MCALLS if iso == "FALSE"}, out


print("[1] 심볼 목록 있음")
syms, out = run(UNI)
chk({"ETHUSDT", "ETHBTC", "ETHTRY"} <= syms, "[1] 교차 마진 조회 = 종전 5종(목록에 있는 것) + 마진 허용 ETHTRY", sorted(syms))
chk("ETHEUR" not in syms and not ({"ETHUSDC", "ETHBNB", "ETHFDUSD"} & syms), "[1] 마진 불가 쿼트 5종 밖·목록에 없는 페어 = 안 봄", sorted(syms))
m9 = [f for f in out if "ETHTRY" in f["id"]]
chk(len(m9) == 1 and m9[0]["id"].startswith("binance:m:") and m9[0].get("quote") == "TRY", "[1] ETHTRY 마진 체결 들어옴(교차 · 쿼트 TRY)", m9)

print("[2] 심볼 목록 없음")
syms, out = run(None)
chk(syms == {"ETHUSDT", "ETHUSDC", "ETHBTC", "ETHBNB", "ETHFDUSD"}, "[2] 목록 없음 = 종전 쿼트 5종 그대로", sorted(syms))

T.finish()
