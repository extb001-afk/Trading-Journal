#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _cassette as C  # noqa: E402

C.freeze()
import time  # noqa: E402

RATE = 1400.0
STEP = {"bybit": [], "gate": [], "okx": [], "kucoin": [], "turnover": True, "gate_fail": False, "krw": []}


def _bybit():
    rows = [dict({"symbol": s + "USDT", "lastPrice": str(p), "volume24h": "1000"}, **({"turnover24h": str(q)} if STEP["turnover"] else {}))
            for s, p, q in STEP["bybit"]]
    return {"retCode": 0, "retMsg": "OK", "result": {"category": "spot", "list": rows + [
        {"symbol": "BTCUSDT", "lastPrice": "100000", "volume24h": "1", "turnover24h": "100000"}]}}


def respond(rq):
    if rq.host == "api.bybit.com" and rq.path == "/v5/market/tickers":
        return _bybit()
    if rq.host == "api.gateio.ws" and rq.path == "/api/v4/spot/tickers":
        if STEP["gate_fail"]:
            return C.Reply({"label": "SERVER_ERROR"}, status=500)
        return [{"currency_pair": s + "_USDT", "last": str(p), "quote_volume": str(q)} for s, p, q in STEP["gate"]] + [
            {"currency_pair": "BTC_USDT", "last": "100000", "quote_volume": "100000"}]
    if rq.host == "www.okx.com" and rq.path == "/api/v5/market/tickers":
        return {"code": "0", "data": [{"instId": s + "-USDT", "last": str(p), "vol24h": "1", "volCcy24h": str(q)} for s, p, q in STEP["okx"]]
                + [{"instId": "BTC-USDT", "last": "100000", "vol24h": "1", "volCcy24h": "100000"}]}
    if rq.host == "api.kucoin.com" and rq.path == "/api/v1/market/allTickers":
        return {"code": "200000", "data": {"ticker": [{"symbol": s + "-USDT", "last": str(p), "vol": "1", "volValue": str(q)} for s, p, q in STEP["kucoin"]]
                                           + [{"symbol": "BTC-USDT", "last": "100000", "vol": "1", "volValue": "1"}]}}
    if rq.host == "api.binance.com" and rq.path == "/api/v3/ticker/24hr":
        return [{"symbol": "AAAUSDT", "count": 5, "closeTime": int(C.NOW * 1000), "quoteVolume": "77.5"},
                {"symbol": "BTCUSDT", "count": 9, "closeTime": int(C.NOW * 1000), "quoteVolume": "1000000"}]
    if rq.host == "api.binance.com" and rq.path == "/api/v3/ticker/price":
        return [{"symbol": "BTCUSDT", "price": "100000"}]
    if rq.host == "api.upbit.com" and rq.path == "/v1/orderbook":
        return [{"market": "KRW-USDT", "orderbook_units": [{"ask_price": RATE, "bid_price": RATE - 1}]}]
    if rq.host == "open.er-api.com":
        return {"result": "success", "rates": {"KRW": 1390.0}}
    if rq.host == "api.upbit.com" and rq.path == "/v1/market/all":
        return [{"market": "KRW-BTC"}, {"market": "USDT-MPLX"}, {"market": "BTC-MPLX"}] + [{"market": "KRW-" + s} for s in STEP["krw"]]
    if rq.host == "api.upbit.com" and rq.path == "/v1/ticker":
        px = {"KRW-MPLX": 154.0, "KRW-BTC": 140_000_000.0}
        return [{"market": m, "trade_price": px[m], "timestamp": int(C.NOW * 1000)} for m in rq.query["markets"].split(",") if m in px]
    raise AssertionError("모르는 요청 " + rq.url)


import health  # noqa: E402
import pricing  # noqa: E402
import px_alt  # noqa: E402
import view_spot  # noqa: E402

cas = C.Cassette("pxalt", responder=respond)


def books(bybit=(), gate=(), okx=(), kucoin=(), turnover=True, gate_fail=False):
    STEP.update(bybit=list(bybit), gate=list(gate), okx=list(okx), kucoin=list(kucoin), turnover=turnover, gate_fail=gate_fail)


def alt(syms):
    sp = view_spot.Spot()
    sp.rate = RATE
    pricing.EX_QVOL.clear()
    out = sp._upbit_alt_global(list(syms), {"BTC": 100000.0}, time.time())
    return sp, out


def scenario():
    o = {}
    books(bybit=[("MPLX", 0.0576, 116000)], gate=[("MPLX", 0.106, 1100000)])
    sp, out = alt(["MPLX"])
    o["v2"] = (out.get("MPLX"), sp.upbit_alt_src.get("MPLX"), sp.alt_spread.get("MPLX"))
    books(bybit=[("MPLX", 0.0576, 116000)], gate=[("MPLX", 0.106, 1100000)], turnover=False)
    sp, out = alt(["MPLX"])
    o["v3"] = (out.get("MPLX"), (sp.alt_spread.get("MPLX") or {}).get("used"))
    books(bybit=[("MPLX", 0.0576, 116000)], gate=[("MPLX", 0.106, 1100000)], gate_fail=True)
    sp, out = alt(["MPLX", "ZZZ"])
    o["v4"] = (out.get("MPLX"), sorted(sp.upbit_alt_miss))
    books(bybit=[("MPLX", 0.0576, 116000)], gate=[("MPLX", 0.106, 1100000)])
    o["v8"] = []
    for krw9 in ([], ["MPLX"]):
        STEP["krw"] = krw9
        sp = view_spot.Spot()
        sp.usd, sp.usd_ts, sp.ex_usd, sp.ex_ts, sp.ex_want, sp._mk_at = {}, {}, {}, {}, set(), 0
        sp.want(["MPLX"])
        sp.tick()
        o["v8"].append((sp.ex_usd.get("upbit:MPLX"), sorted(getattr(sp, "alt_spread", None) or {}), dict(getattr(sp, "upbit_alt_src", None) or {})))
    STEP["krw"] = []
    sp = view_spot.Spot()
    sp.usd, sp.usd_ts, sp.ex_usd, sp.ex_ts, sp.ex_want, sp._mk_at = {}, {}, {}, {}, set(), 0
    sp.want(["MPLX"])
    sp.tick()
    coins9, gid9 = [{"key": "g7", "qty": 10000.0, "price": 0.106}], {7: "upbit"}
    pre9 = px_alt.held_spread(sp.alt_spread, coins9, gid9, {7: {"sym": "MPLX"}}, set(sp.upbit_alt) - set(sp.upbit_krw))
    STEP["krw"] = ["MPLX"]
    sp._mk_at = 0
    sp.tick()
    post9 = px_alt.held_spread(sp.alt_spread, coins9, gid9, {7: {"sym": "MPLX"}}, set(sp.upbit_alt) - set(sp.upbit_krw))
    o["v8b"] = ([x9["sym"] for x9 in pre9], [x9["sym"] for x9 in post9], sp.ex_usd.get("upbit:MPLX"))
    books(bybit=[("AAA", 1.0, 11)], gate=[("AAA", 1.0, 22)], okx=[("AAA", 1.0, 33)], kucoin=[("AAA", 1.0, 44)])
    pricing.EX_QVOL.clear()
    for ex9 in ("bybit", "gate", "okx", "kucoin"):
        pricing.ex_spot_usd(ex9)
    pricing._BN_DEAD["at"] = 0.0
    pricing.binance_dead_syms(now=time.time())
    now9 = time.time()
    o["v9"] = ([px_alt.vol_of(e9, "AAA", now9) for e9 in ("bybit", "gate", "okx", "kucoin", "binance")],
               px_alt.vol_of("gate", "AAA", now9 + px_alt.QVOL_MAX_AGE + 5))
    return o


if cas.ready(T):
    o, why = cas.run(scenario)
    T.chk(why is None and o, "카세트 시나리오 끝까지", why)
    o = o or {}
    v2 = o.get("v2") or (None, None, None)
    T.chk(v2[0] and v2[0][0] == 0.106 and v2[0][1].startswith("gate MPLXUSDT · 24h 거래대금 최대 $1,100,000"), "V2 거래대금 최대 거래소(게이트) 값", v2[0])
    T.chk(str(v2[1] or "").startswith("게이트 · 업비트 비원화"), "V2 화면 출처 = 게이트", v2[1])
    sd = v2[2] or {}
    T.chk(sd.get("x") == 1.84 and sd.get("used") == "gate" and sd.get("px") == 0.106
          and [(r["ex"], r["px"], r["qv"]) for r in sd.get("rows", [])] == [("bybit", 0.0576, 116000.0), ("gate", 0.106, 1100000.0)],
          "V2 괴리 재료(1.84배 · 거래소별 가격·거래대금 · 쓴 가격)", sd)
    v3 = o.get("v3") or (None, None)
    T.chk(v3[0] and v3[0][0] == 0.0576 and v3[0][1].startswith("bybit ") and v3[1] == "bybit", "V3 거래대금 모름 = 옛 순서(바이빗) · 괴리 재료 남음", v3)
    v4 = o.get("v4") or (None, None)
    T.chk(v4[0] and v4[0][0] == 0.0576 and v4[1] == ["ZZZ"], "V4 게이트 조회 실패 = 옛 순서(바이빗) · 다른 코인 '시세 없음' 판정 그대로", v4)
    v8 = o.get("v8") or [(None,), (None,)]
    T.chk(v8[0][0] == 0.106 and v8[0][1] == ["MPLX"] and str(v8[0][2].get("MPLX", "")).startswith("게이트"), "V8 개시 전 = 대체 경로(게이트 값 · 괴리 재료)", v8[0])
    T.chk(v8[1][0] == 0.11 and v8[1][1] == [] and v8[1][2] == {}, "V8 개시 뒤 = 대체 경로 안 탐 · 업비트 원화 값(154 ÷ 1400)", v8[1])
    T.chk(o.get("v8b") == (["MPLX"], [], 0.11), "V8b 같은 Spot 개시 전 → 뒤 = 묵은 괴리 재료 안 실음 · 원화 값", o.get("v8b"))
    v9 = o.get("v9") or ([], 0)
    T.chk(v9[0] == [11.0, 22.0, 33.0, 44.0, 77.5], "V9 거래소별 24h USDT 거래대금 기록(바이낸스 = 24hr MINI)", v9[0])
    T.chk(v9[1] is None, "V9 묵은 거래대금 = 모름", v9[1])
    cas.golden(T, {"out": o})
    cas.check(T)

NOW = 1_800_000_000.0


def pick(bk, qv, ident=None, failed=None):
    pricing.EX_QVOL.clear()
    pricing.EX_QVOL.update({e9: (NOW, d9) for e9, d9 in qv.items()})
    book9, fl9 = (lambda ex: bk.get(ex, {"BTC": 1.0})), (failed or (lambda ex: False))
    return px_alt.pick(["MPLX"], book9, NOW, (ident, None, fl9), pricing.pick_global_usd(["MPLX"], book9, ident=ident, failed=fl9))


out, spr = pick({"binance": {"MPLX": 2.0}}, {"binance": {"MPLX": 5.0}})
T.chk(out == {"MPLX": (2.0, "binance MPLXUSDT")} and spr == {}, "V1 후보 한 곳 = 종전 그대로", (out, spr))
out, spr = pick({"bybit": {"MPLX": 0.10}, "gate": {"MPLX": 0.12}}, {"bybit": {"MPLX": 500.0}, "gate": {"MPLX": 500.0}})
T.chk(out["MPLX"][0] == 0.10 and out["MPLX"][1].startswith("bybit MPLXUSDT · 24h 거래대금 최대 $500") and spr == {}, "V5 거래대금 같음 = 앞 순서 · 1.2배 = 괴리 없음", (out, spr))
out, spr = pick({"gate": {"MPLX": 3.1}, "kucoin": {"MPLX": 3.0}}, {"gate": {"MPLX": 9e6}, "kucoin": {"MPLX": 1.0}})
T.chk(out == {} and spr == {}, "V6 옛 규칙이 거래소를 못 고름(코인게코 몫) = 손대지 않음", (out, spr))
out, spr = pick({"bybit": {"MPLX": 0.0576}, "gate": {"MPLX": 0.106}}, {"bybit": {"MPLX": 1.16e5}, "gate": {"MPLX": 1.1e6}},
                ident=lambda s, ex: (False, "다른 코인") if ex == "gate" else (None, ""))
T.chk(out["MPLX"][0] == 0.0576 and spr == {}, "V7 매핑으로 다른 코인인 거래소 = 후보 아님", (out, spr))
out, spr = pick({"binance": {"MPLX": 1.0}, "bybit": {}, "gate": {"MPLX": 1.2}}, {"binance": {"MPLX": 10.0}, "gate": {"MPLX": 1.2e4}})
T.chk(out["MPLX"] == (1.0, "binance MPLXUSDT"), "V12 빈 책(실패를 빈 값으로 캐시) = 비교 불완전 → 옛 결과", (out, spr))

SPR = {"MPLX": {"sym": "MPLX", "x": 1.84, "used": "gate", "px": 0.106,
                "rows": [{"ex": "bybit", "px": 0.0576, "qv": 116000.0}, {"ex": "gate", "px": 0.106, "qv": 1100000.0}]}}
coins = [{"key": "g7", "qty": 10000.0, "price": 0.106}, {"key": "g8", "qty": 5.0, "price": 0.106}, {"key": "x1", "qty": 1.0, "price": 1.0}]
held = px_alt.held_spread(SPR, coins, {7: "upbit", 8: "bybit"}, {7: {"sym": "MPLX"}, 8: {"sym": "MPLX"}})
T.chk(len(held) == 1 and held[0]["usd"] == 1060.0 and "바이빗 $0.0576(거래대금 $116,000)" in held[0]["text"]
      and "게이트 $0.106(거래대금 $1,100,000)" in held[0]["text"] and "쓴 가격 게이트 $0.106" in held[0]["text"],
      "V10 업비트 보유만 · 보유 $ · 문구(거래소별 가격·거래대금·쓴 가격)", held)
T.chk(px_alt.held_spread(SPR, coins, {7: "upbit"}, {7: {"sym": "MPLX"}}, set()) == [], "V10 지금 대체 경로 아닌 코인(원화 마켓) = 재료 뺌")
UNITS = ["tj-core", "tj-web", "tj-exf", "tj-sol"]
HS = health.settings({"health": {"units": UNITS}})


def proof(**kw):
    wd9 = {"ts": time.time(), "unpriced_held": [], "ex_dead_held": [], "proof_div": []}
    wd9.update(kw)
    ob9 = {"now": time.time(), "pm2": {u: {"status": "online", "restarts": 0, "pid": 1} for u in UNITS}, "bal_mem": {}, "prev_inc": {}, "sources": [],
           "webdiag": wd9}
    return next((c for c in health.evaluate(ob9, HS) if c["id"] == "price:proof"), {})


c = proof(alt_spread=held)
T.chk(c.get("level") == "warn" and c.get("title") == "거래소 간 시세 괴리 1건" and "MPLX 거래소 간 1.84배" in c.get("detail", "")
      and "24h 거래대금 최대" in c.get("action", "") and "DEX 와 20%" not in c.get("action", ""), "V10 헬스 price:proof 주황 1건", c)
c0 = proof()
T.chk(c0.get("level") == "ok" and c0.get("title") == "거래소 시세·DEX 교차검증" and c0.get("detail") == "보유 $500 이상 괴리 없음"
      and c0.get("action", "").startswith("입출금으로 증명한 거래소 시세가 DEX 와 20%"), "V10 재료 없음 = 종전 문구", c0)
T.chk(proof(alt_spread=[dict(held[0], usd=100.0)]).get("level") == "ok", "V10 보유 $500 미만 = 주황 아님")

ex_usd, ex_ts = {"upbit:MPLX": 0.106, "upbit:OLD": 1.0}, {"upbit:MPLX": NOW, "upbit:OLD": NOW}
keep = view_spot._px1004_spot_filter(ex_usd, ex_ts, {"upbit_krw": ["BTC"], "ex_alt_src": {"MPLX": "gate", "OLD": "upbit-usdt"}})
T.chk(keep == {"MPLX": "gate"} and "upbit:MPLX" in ex_usd and "upbit:OLD" not in ex_usd, "V11 저장 출처 gate = 유지 · 모르는 출처 = 버림", (keep, ex_usd))

T.finish()
