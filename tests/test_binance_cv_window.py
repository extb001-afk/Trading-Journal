#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import urllib.parse  # noqa: E402

json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import exf_binance as B  # noqa: E402

chk = T.chk
DAY = 86400
T.patch_moved("PACE", 0, ("exf_",))
T.patch_moved("_gov_prepare", lambda *_a, **_k: None, ("exf_",))
T.patch_moved("_srv_ms", lambda *_a, **_k: 1700000000000, ("exf_",))
ENV = {"TJ_BINANCE_KEY": "k", "TJ_BINANCE_SECRET": "s"}
T0 = 1690000000
T1 = T0 + 100 * DAY
CV, DUST, CALLS = [], [], []


def http(url, headers=None, **_k):
    u = urllib.parse.urlparse(url)
    q = dict(urllib.parse.parse_qsl(u.query))
    a, b = int(q["startTime"]), int(q["endTime"])
    CALLS.append((u.path, a, b))
    if u.path.endswith("convert/tradeFlow"):
        rows = [r for r in CV if a <= r["createTime"] <= b]
        return {"list": rows, "moreData": False}
    if u.path.endswith("asset/dribblet"):
        g = [r for r in DUST if a <= r["operateTime"] <= b]
        return {"total": len(g), "userAssetDribblets": g}
    raise AssertionError(u.path)


T.patch_moved("http_json", http, ("exf_",))


def cv(oid, ms):
    return {"orderId": oid, "orderStatus": "SUCCESS", "fromAsset": "USDT", "fromAmount": "10", "toAsset": "ETH", "toAmount": "0.01",
            "createTime": ms}


def dust(tid, ms):
    return {"operateTime": ms, "transId": tid, "userAssetDribbletDetails": [
        {"transId": tid, "fromAsset": "XYZ", "amount": "1", "transferedAmount": "0.001", "operateTime": ms, "targetAsset": "BNB"}]}


def windows(path):
    return [(a, b) for p, a, b in CALLS if p.endswith(path)]


def contiguous(ws):
    return all(ws[i + 1][0] == ws[i][1] + 1 for i in range(len(ws) - 1))


print("[1] convert 조각 경계")
E1 = T0 + 30 * DAY - 1
CV[:] = [cv(1, E1 * 1000 + 500), cv(2, T0 * 1000), cv(3, (E1 + 1) * 1000), cv(4, T1 * 1000 + 10)]
CALLS.clear()
out = B.convert_binance(ENV, T0, T1)
ids = sorted(f["id"] for f in out)
chk(any(f["id"].endswith(":1") for f in out), "[1] 조각 끝 초 안(e*1000+500) 전환 받음", ids)
ws = windows("tradeFlow")
chk(all(b - a < 30 * DAY * 1000 for a, b in ws), "[1] 조각 = 30일 미만", ws)
chk(contiguous(ws) and ws[-1][1] == T1 * 1000, "[1] 이어지는 조각 사이 빈 ms 0 · 마지막 끝 = t1", ws)
chk(len(out) == 3 and len(set(ids)) == 3, "[3] convert: 시작 ms·다음 조각 시작 ms 1번씩 · t1 뒤 제외", ids)

print("[2] Dust 조각 경계")
E2 = T0 + 90 * DAY - 1
DUST[:] = [dust(11, E2 * 1000 + 700), dust(12, T0 * 1000), dust(13, (E2 + 1) * 1000)]
CALLS.clear()
out = B.convert_binance_dust(ENV, T0, T1)
ids = sorted(f["id"] for f in out)
chk(any(":11:" in f["id"] for f in out), "[2] 조각 끝 초 안(e*1000+700) 소액 전환 받음", ids)
ws = windows("dribblet")
chk(all(b - a < 90 * DAY * 1000 for a, b in ws) and contiguous(ws) and ws[-1][1] == T1 * 1000, "[2] 조각 90일 미만 · 빈 ms 0 · 마지막 끝 = t1", ws)
chk(len(out) == 3 and len(set(ids)) == 3, "[3] Dust: 각 1번씩", ids)

T.finish()
