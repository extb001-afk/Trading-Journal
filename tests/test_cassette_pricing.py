#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _cassette as C  # noqa: E402

C.freeze()
import json  # noqa: E402
import os  # noqa: E402

T1 = (int(C.NOW) // 60) * 60 - 2 * 3600
T0 = T1 - 3600
PX_MS = (T0 + 600) * 1000


def bybit_rows(sym, a_ms, n):
    out = []
    for i in range(n):
        ms = a_ms + i * 60_000
        o = 2.0 + (i % 7) * 0.01 if sym == "TSTAUSDT" else 0.5
        out.append([str(ms), "%.4f" % o, "%.4f" % (o + 0.02), "%.4f" % (o - 0.02), "%.4f" % (o + 0.005), "1200.5", "2400.9"])
    return list(reversed(out))


def respond(rq):
    q = rq.query
    if rq.host == "api.binance.com" and rq.path == "/api/v3/klines":
        if q.get("symbol") == "TSTAUSDT":
            return C.Reply({"code": -1121, "msg": "Invalid symbol."}, status=400)
        return []
    if rq.host == "api.bybit.com" and rq.path == "/v5/market/kline":
        a, b = int(q["start"]), int(q["end"])
        n = min(int(q.get("limit") or 1), (b - a) // 60_000 + 1)
        return {"retCode": 0, "retMsg": "OK", "result": {"category": "spot", "symbol": q["symbol"], "list": bybit_rows(q["symbol"], a, n)}}
    if rq.host == "api.upbit.com" and rq.path == "/v1/ticker":
        px = {"KRW-TSTA": 2730.0, "KRW-ETH": 3550000.0}
        return [{"market": m, "trade_price": px[m], "timestamp": int(C.NOW * 1000)} for m in q["markets"].split(",") if m in px]
    raise AssertionError("모르는 요청 " + rq.url)


import paths  # noqa: E402
import candles  # noqa: E402
import pricing  # noqa: E402

cas = C.Cassette("pricing", responder=respond)


def scenario():
    plan = candles.plan_chain({"venue": "binance", "base": "TSTA", "quote": "USDT"}, "TSTA", "USD")
    ch = candles.best_chart(plan, "1m", T0, T1, "USD", now=C.NOW, ref_px=2.03)
    pc = pricing.PxCache(os.path.join(paths.STATE_DIR, "px_cache_test.json"))
    px = pc.candle_usd("TSTB", PX_MS)
    pc.flush()
    spot = pricing.upbit_spot_krw(["TSTA", "ETH"])
    return {"chart": ch, "candle_usd": px, "spot": spot, "calls": candles.CALLS}


if cas.ready(T):
    out, why = cas.run(scenario)
    T.chk(why is None and out and out["chart"]["ok"] and (out["chart"]["src"] or {}).get("venue") == "bybit" and len(out["chart"]["candles"]) == 60,
          "[1] 바이낸스 없는 심볼 → 바이비트 1분봉 60개", [why, out and {k: out["chart"][k] for k in ("ok", "src", "tried", "calls")}])
    T.chk(out and out["candle_usd"] == 0.5, "[2] 원가 1분봉 = 바이낸스 빈 응답 → 바이비트 시가", out and out["candle_usd"])
    T.chk(out and out["spot"] == {"TSTA": 2730.0, "ETH": 3550000.0}, "[3] 현재가(업비트 원화)", out and out["spot"])
    cas.golden(T, {"out": out, "state": C.snap_tree(paths.STATE_DIR)})
    cas.check(T)
T.finish()
