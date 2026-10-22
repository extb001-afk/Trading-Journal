#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _cassette as C  # noqa: E402

C.freeze()
import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

H = 3600_000
DAY = 86400
MS = (int(C.NOW) // 60) * 60_000 - 3 * H
D0 = (int(C.NOW) // DAY - 40) * DAY
FLAT_BASE = MS - 3 * 86400_000


def _bn_row(ms, o, v, q):
    return [ms, o, o, o, o, v, ms + 59_999, q, 0 if v == "0" else 3]


def respond(rq):
    q = rq.query
    if rq.host == "api.binance.com" and rq.path == "/api/v3/klines":
        sym, st = q.get("symbol"), int(q["startTime"])
        if sym == "ZDEADUSDT":
            return [_bn_row(st, "1.5", "0.00000000", "0.00000000")]
        if sym == "ZLIVEUSDT":
            return [_bn_row(st, "1.5", "3.0", "4.5")]
        if sym == "ZNOQUSDT":
            return [[st, "1.5", "1.5", "1.5", "1.5", "0"]]
        if sym == "ZMIXUSDT":
            return [_bn_row(st, "1.0", "0", "0"), _bn_row(st + 60_000, "1.1", "4", "4.4")]
        return C.Reply({"code": -1121, "msg": "Invalid symbol."}, status=400)
    if rq.host == "api.bybit.com" and rq.path == "/v5/market/kline":
        sym, st = q.get("symbol"), int(q["start"])
        if q.get("interval") == "D":
            n = (int(q["end"]) + 1 - st) // (DAY * 1000)
            return {"retCode": 0, "retMsg": "OK", "result": {"list": [
                [str(st + i * DAY * 1000), "2", "2", "2", "2", "0" if i >= 2 else "5", "0" if i >= 2 else "10"] for i in reversed(range(n))]}}
        row = {"ZDEADUSDT": [str(st), "0.3171", "0.3171", "0.3171", "0.3171", "0", "0"],
               "ZIPUSDT": [str(st), "0.3171", "0.3171", "0.3171", "0.3171", "0", "0"],
               "ZLIVEUSDT": [str(st), "2.5", "2.6", "2.4", "2.55", "10", "25"],
               "ZFLUSDT": [str(st), "0.29", "0.3", "0.28", "0.29", "100", "29"]}.get(sym)
        return {"retCode": 0, "retMsg": "OK", "result": {"list": [row] if row else []}}
    if rq.host == "api.upbit.com" and rq.path == "/v1/candles/minutes/1":
        return C.Reply({"error": {"name": "404", "message": "Code not found"}}, status=404)
    raise AssertionError("모르는 요청 " + rq.url)


import acct_norm  # noqa: E402
import candles  # noqa: E402
import paths  # noqa: E402
import pricing  # noqa: E402
import view_common  # noqa: E402

chk = T.chk
cas = C.Cassette("pxzero", responder=respond)


def flat_file(name):
    cache = {}
    for i in range(8):
        cache[f"ZFL:{FLAT_BASE + i * 9 * H}"] = 0.3171
    cache[f"ZFL:{MS - 120_000}"] = 0.3171
    for i in range(8):
        cache[f"LV:{FLAT_BASE + i * 9 * H}"] = 2.0 + i * 0.01
    for i in range(3):
        cache[f"TH:{MS - 10 * H + i * 3 * H}"] = 0.05
    for i in range(3):
        cache[f"KA:{FLAT_BASE + i * 24 * H}"] = 0.0297
    for i in range(5):
        cache[f"USDG:{FLAT_BASE + i * 15 * H}"] = 1.0007
    p = os.path.join(paths.STATE_DIR, name)
    with open(p, "w") as f:
        json.dump({"candle": cache, "cven": {k: "bybit" for k in cache if k.startswith("ZFL:")}}, f)
    return p


def scenario():
    o = {"z1": [pricing._c_bybit("ZDEAD", MS), pricing._c_bybit("ZLIVE", MS)],
         "z2": [pricing._c_binance("ZDEAD", MS), pricing._c_binance("ZLIVE", MS), pricing._c_binance("ZNOQ", MS)]}
    pc = pricing.PxCache(os.path.join(paths.STATE_DIR, "px_z4.json"))
    o["z4"] = [pc.candle_usd("ZIP", MS), sorted(k for k in pc.d["candle"] if k.startswith("ZIP:"))]
    p5 = pricing.PxCache(os.path.join(paths.STATE_DIR, "px_z5.json"))
    p5.prefetch_candles([("ZMIX", MS), ("ZMIX", MS + 60_000)], pace=0)
    o["z5"] = [list(kv) for kv in sorted(p5.d["candle"].items())]
    r = candles.fetch_cex("bybit", "ZZ", "USDT", "1d", D0, D0 + 5 * DAY)
    r2 = candles.fetch_cex("bybit", "ZZ", "USDT", "1d", D0, D0 + 5 * DAY)
    o["z6"] = [[c[0] for c in (r.candles or [])], r2.cached, [c[0] for c in (r2.candles or [])]]
    p9 = pricing.PxCache(flat_file("px_z9.json"))
    k9 = FLAT_BASE + 9 * H
    o["z9"] = [p9.candle_usd("ZFL", k9), p9.candle_usd("ZFL", k9), p9.candle_venue("ZFL", k9)]
    return o


if cas.ready(T):
    out, why = cas.run(scenario)
    chk(why is None and out, "카세트 시나리오 끝까지", why)
    out = out or {}
    chk(out.get("z1") == [None, 2.5], "Z1 바이빗 거래 0 봉 = None · 거래 있는 봉 = 시가", out.get("z1"))
    chk(out.get("z2") == [None, 1.5, 1.5], "Z2 바이낸스 거래 0 = None · 거래 있음 = 시가 · 대금 필드 없음(모름) = 시가", out.get("z2"))
    chk(out.get("z4") == [None, []], "Z4 candle_usd 거래 0 봉뿐 = 값 없음 · 캐시에 안 씀", out.get("z4"))
    chk(out.get("z5") == [[f"ZMIX:{MS + 60_000}", 1.1]], "Z5 선조회 = 거래 0 분은 비워 둠 · 거래 있는 분만", out.get("z5"))
    chk(out.get("z6") == [[D0, D0 + DAY], True, [D0, D0 + DAY]], "Z6 일봉 거래 0 봉 버림 · 다시 = 디스크 캐시 같은 값", out.get("z6"))
    chk(out.get("z9") == [0.29, 0.29, "bybit"], "Z9 평평 표시 키를 새로 받으면(거래 있는 봉) 그 값 · 다음 = 캐시 적중", out.get("z9"))
    cas.golden(T, {"out": out})
    cas.check(T)

cp = candles._cpath("bybit", "YYUSDT", "1d", D0, D0 + 5 * DAY)
os.makedirs(os.path.dirname(cp), exist_ok=True)
with open(cp, "w") as f:
    json.dump({"key": ["bybit", "YYUSDT", "1d", D0, D0 + 5 * DAY], "candles": [[D0 + i * DAY, 3.0, 3.0, 3.0, 3.0, 0.0 if i else 7.0] for i in range(5)],
               "why": None, "note": None, "at": int(time.time()), "complete": candles.CACHE_V}, f)
r3 = candles.fetch_cex("bybit", "YY", "USDT", "1d", D0, D0 + 5 * DAY)
chk(r3.cached and [c[0] for c in (r3.candles or [])] == [D0], "Z6 저장된 일봉 캐시의 거래 0 봉도 읽을 때 버림", (r3.cached, r3.candles))
h0 = D0
ch = candles._cpath("bybit", "HHUSDT", "1h", h0, h0 + 3 * 3600)
with open(ch, "w") as f:
    json.dump({"key": ["bybit", "HHUSDT", "1h", h0, h0 + 3 * 3600], "candles": [[h0 + i * 3600, 2.0, 2.0, 2.0, 2.0, 0.0] for i in range(3)],
               "why": None, "note": None, "at": int(time.time()), "complete": candles.CACHE_V}, f)
r4 = candles.fetch_cex("bybit", "HH", "USDT", "1h", h0, h0 + 3 * 3600)
chk(r4.cached and len(r4.candles or []) == 3, "Z6 반대: 1시간봉 캐시(차트) = 그대로(일봉만 거름)", (r4.cached, len(r4.candles or [])))

cb_body = {"candles": [{"start": str(D0 + i * DAY), "low": "0.04", "high": "0.05", "open": "0.045", "close": "0.045",
                        "volume": "0" if i == 1 else "12.5"} for i in reversed(range(3))]}
z12 = candles._day_live(candles.norm(candles.parse_coinbase(cb_body), D0, D0 + 3 * DAY), "1d")
chk([c[0] for c in z12] == [D0, D0 + 2 * DAY], "Z12 코인베이스 일봉 응답의 거래 0 봉 = 버림(거래 있는 날만)", z12)
cc = candles._cpath("coinbase", "CB-USD", "1d", D0, D0 + 3 * DAY)
os.makedirs(os.path.dirname(cc), exist_ok=True)
with open(cc, "w") as f:
    json.dump({"key": ["coinbase", "CB-USD", "1d", D0, D0 + 3 * DAY], "candles": [[D0 + i * DAY, 0.045, 0.05, 0.04, 0.045, 0.0 if i == 1 else 12.5] for i in range(3)],
               "why": None, "note": None, "at": int(time.time()), "complete": candles.CACHE_V}, f)
r12 = candles.fetch_cex("coinbase", "CB", "USD", "1d", D0, D0 + 3 * DAY)
chk(r12.cached and [c[0] for c in (r12.candles or [])] == [D0, D0 + 2 * DAY], "Z12 코인베이스 저장된 일봉 캐시의 거래 0 봉도 읽을 때 버림", (r12.cached, r12.candles))

p7 = flat_file("px_z7.json")
px7 = pricing.PxCache(p7)
k_old = f"ZFL:{FLAT_BASE}"
px7.nb_begin()
chk(px7.candle_usd("ZFL", FLAT_BASE) is None, "Z7 평평 캐시 값 = 읽을 때 없음(candle_usd)")
chk(not px7.candle_recent("ZFL", MS), "Z7 candle_recent 직전 10분 캐시 평평 값도 안 씀")
chk(px7.candle_usd("LV", FLAT_BASE + 9 * H) == 2.01, "Z8 값이 바뀌는 심볼 = 그대로")
chk(px7.candle_usd("TH", MS - 10 * H) == 0.05, "Z8 24시간 안의 같은 값 = 그대로")
chk(px7.candle_usd("KA", FLAT_BASE + 24 * H) == 0.0297, "Z8 같은 값 3점(5점 미만 · 이틀) = 그대로")
chk(px7.candle_usd("USDG", FLAT_BASE) == 1.0007, "Z8 달러 고정 근처 평평 = 그대로")
miss7 = px7.nb_end()
chk(("c", "ZFL", FLAT_BASE) in miss7, "Z7 평평 키 = 다시 받을 대기열에", sorted(miss7))
px7._dirty = 99
px7.flush()
chk(json.load(open(p7))["candle"].get(k_old) == 0.3171, "Z7 캐시 파일 값은 안 고침(읽는 쪽에서만)")
fxb = acct_norm.FxBook({}, p7, 1400.0, web_candle=None)
chk(fxb.candle("ZFL", (FLAT_BASE + 18 * H) // 1000) is None, "Z10 FxBook 도 평평 묶음은 안 씀")
chk(fxb.candle("LV", (FLAT_BASE + 9 * H) // 1000) == 2.01, "Z10 반대: 살아 있는 심볼 = 그대로")
fx10, wc10 = view_common._px_tables(px7)
chk(wc10.get(k_old, 1) is None and wc10.get(f"LV:{FLAT_BASE}") == 2.0, "Z10 웹 캐시 사본(_px_tables → FxBook) = 평평 값 None · 다른 값 그대로")
core10 = os.path.join(paths.STATE_DIR, "px_core10.json")
with open(core10, "w") as f:
    json.dump({"candle": {f"ZFL:{FLAT_BASE + 18 * H}": 0.3171}}, f)
with open(core10, "w") as f:
    json.dump({"candle": {f"ZFL:{FLAT_BASE + 18 * H}": 0.3171, f"ZFL:{FLAT_BASE + 27 * H + 60_000}": 0.3171}}, f)
fxb2 = acct_norm.FxBook(fx10, core10, 1400.0, web_candle=wc10)
chk(fxb2.candle("ZFL", (FLAT_BASE + 18 * H) // 1000) is None, "Z10 웹에서 거른 평평 값 = 원장 캐시 같은 분 값으로 되살아나지 않음")
chk(fxb2.candle("ZFL", (FLAT_BASE + 27 * H) // 1000) is None, "Z10 거른 분 = 원장 캐시 1분 옆 값으로도 대신 안 함")
import view_misc  # noqa: E402
chk(view_misc._fx_candle_near(fxb2, "ZFL", (FLAT_BASE + 27 * H) // 1000) is None, "Z10 수수료 ±1시간 도우미도 거른 분 = 없음")
chk(fxb2.candle("LV", (FLAT_BASE + 9 * H + 60_000) // 1000) == 2.01, "Z10 반대: 살아 있는 심볼 인접 봉 대체 = 그대로")
fxq = pricing.FxWarmQueue(px7)
chk(fxq._missing([("c", "ZFL", FLAT_BASE), ("c", "LV", FLAT_BASE)]) == [("c", "ZFL", FLAT_BASE)], "Z11 배경 환율·1분봉 큐: 평평 키 = 아직 없음(다시 받음) · 살아 있는 값 = 있음")
import flow_trace  # noqa: E402
sc = flow_trace.Scanner({"chains": {}}, {"_memo": {"pxday": {f"ZFL:{FLAT_BASE // 86400_000}": 0.3171}}}, px=px7, budget=0)
chk(sc._px_at("ZFL", FLAT_BASE // 1000) == (None, False) and sc._px_at("LV", FLAT_BASE // 1000) == (2.0, False),
    "Z11 돈 흐름 추적 캐시 읽기도 평평 값 = 없음 · 살아 있는 값 = 그대로")
chk(sc._px_at("ZFL", (FLAT_BASE + 60_000) // 1000) == (None, False), "Z11 같은 날 캐시 없는 분도 옛 평평 하루 메모 안 씀")
sc.c["_memo"]["pxday"][f"LV:{(FLAT_BASE + 60_000) // 86400_000}"] = 2.0
chk(sc._px_at("LV", (FLAT_BASE + 60_000) // 1000) == (2.0, True), "Z11 반대: 평평 없는 심볼 = 하루 메모 그대로(근사)")
T.finish()
