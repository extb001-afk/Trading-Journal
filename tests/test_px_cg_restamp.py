#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _cassette as C  # noqa: E402

C.freeze()
import json  # noqa: E402
import os  # noqa: E402

ST = {"cg": 0}


def respond(rq):
    if rq.host == "api.coingecko.com" and rq.path == "/api/v3/simple/price":
        ST["cg"] += 1
        if ST["cg"] >= 2:
            return C.Reply({"status": {"error_code": 429, "error_message": "rate limited"}}, status=429, headers={"Retry-After": "120"})
        return {"humacoin": {"usd": 0.05}}
    if rq.host == "api.bybit.com" and rq.path == "/v5/market/tickers":
        return {"retCode": 0, "retMsg": "OK", "result": {"category": "spot", "list": [
            {"symbol": "BTCUSDT", "lastPrice": "60000", "volume24h": "1", "turnover24h": "60000"}]}}
    if rq.host == "api.gateio.ws" and rq.path == "/api/v4/spot/tickers":
        return [{"currency_pair": "BTC_USDT", "last": "60000", "quote_volume": "60000"}]
    if rq.host == "www.okx.com" and rq.path == "/api/v5/market/tickers":
        return {"code": "0", "data": [{"instId": "BTC-USDT", "last": "60000", "vol24h": "1", "volCcy24h": "60000"}]}
    if rq.host == "api.kucoin.com" and rq.path == "/api/v1/market/allTickers":
        return {"code": "200000", "data": {"ticker": [{"symbol": "BTC-USDT", "last": "60000", "vol": "1", "volValue": "60000"}]}}
    raise AssertionError("모르는 요청 " + rq.url)


import candles  # noqa: E402
import view_spot  # noqa: E402

chk = T.chk
os.makedirs(candles.CACHE_DIR, exist_ok=True)
with open(os.path.join(candles.CACHE_DIR, "cgx_upbit.json"), "w") as f:
    json.dump({"done": True, "at": int(C.NOW), "map": {"HUMA": ["humacoin"]}}, f)
cas = C.Cassette("pxcgat", responder=respond)
T0 = C.NOW


def scenario():
    o = {}
    sp = view_spot.Spot()
    sp.rate = 1400.0
    at0 = {}
    out = sp._upbit_alt_global(["HUMA"], {"BTC": 60000.0}, T0, at=at0)
    o["r2a"] = [(out.get("HUMA") or (None,))[0], at0.get("HUMA")]
    at1 = {}
    out = sp._upbit_alt_global(["HUMA"], {"BTC": 60000.0}, T0 + 3500, at=at1)
    o["r2b"] = [(out.get("HUMA") or (None,))[0], at1.get("HUMA")]
    sp2 = view_spot.Spot()
    sp2.rate = 1400.0
    at2 = {}
    out = sp2._upbit_alt_global(["HUMB"], {"HUMB": 2.0, "BTC": 60000.0}, T0 + 3500, at=at2)
    o["r4"] = [(out.get("HUMB") or (None,))[0], sorted(at2)]
    at3 = {}
    o["r1"] = [candles.cg_simple_usd(["humacoin"], now=T0 + 3500, at=at3), at3]
    return o


if cas.ready(T):
    out, why = cas.run(scenario)
    chk(why is None and out, "카세트 시나리오 끝까지", why)
    out = out or {}
    chk(out.get("r2a") == [0.05, T0], "R2 처음 = 코인게코 값 · 받은 시각 t0", out.get("r2a"))
    chk(out.get("r2b") == [0.05, T0], "R2 58분 뒤 429 = 옛 값 · 받은 시각 = t0(지금 아님)", out.get("r2b"))
    chk(out.get("r4") == [2.0, []], "R4 반대: 바이낸스 값 = 받은 시각 표 없음(지금)", out.get("r4"))
    chk(out.get("r1") == [{"humacoin": 0.05}, {"humacoin": T0}], "R1 cg_simple_usd at = 받은 시각", out.get("r1"))
    cas.golden(T, {"out": out})
    cas.check(T)
T.finish()
