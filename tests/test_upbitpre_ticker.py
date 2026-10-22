#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _cassette as C  # noqa: E402

CLK = C.freeze(now=1_800_000_000.0)
import os  # noqa: E402

import pricing  # noqa: E402
import view_b_cards  # noqa: E402
import view_spot  # noqa: E402

chk = T.chk
SYMS = ["BTC"] + [f"F{i:03d}" for i in range(55)] + ["QQQ"]
NET = {"mode": "ok", "calls": 0, "pre": {"QQQ"}}


class Holder:

    def __init__(self, s):
        self.spot = s


def respond(rq):
    CLK.now += 0.3
    h, p = rq.host, rq.path
    if h == "api.upbit.com":
        if p == "/v1/orderbook":
            return [{"market": "KRW-USDT", "orderbook_units": [{"ask_price": 1400.0, "bid_price": 1399.0}]}]
        if p == "/v1/market/all":
            return [{"market": f"KRW-{s}"} for s in SYMS]
        if p == "/v1/ticker":
            NET["calls"] += 1
            if NET.get("watch") is not None:
                NET["mid"].append(view_b_cards._pre_listed("F000", sb=Holder(NET["watch"])))
            mk = rq.query["markets"].split(",")
            if NET["mode"] == "timeout":
                CLK.now += 80.0
                return C.Reply(exc="timeout")
            if NET["mode"] == "5xx":
                return C.Reply({"error": {"name": "server"}}, status=503)
            if any(m[4:] in NET["pre"] for m in mk) and NET["mode"] != "omit":
                return C.Reply({"error": {"name": "404", "message": "Code not found"}}, status=404)
            return [{"market": m, "trade_price": 1540.0} for m in mk if m[4:] not in NET["pre"]]
    if h == "open.er-api.com":
        return {"result": "success", "rates": {"KRW": 1390.0}}
    if h == "api.binance.com" and p == "/api/v3/ticker/price":
        return [{"symbol": "BTCUSDT", "price": "100000.0"}]
    if h == "api.binance.com" and p == "/api/v3/ticker/24hr":
        return [{"symbol": "BTCUSDT", "count": 10, "closeTime": int(CLK.t() * 1000)}]
    raise AssertionError("모르는 요청 " + rq.url)


CDIR = os.path.join(T.TMP, "cas_upre")
os.makedirs(CDIR, exist_ok=True)
cas = C.Cassette("upre", responder=respond, dirpath=CDIR, record=True)


def krw(syms, mode, answered=True):
    NET["mode"], NET["calls"] = mode, 0
    got, dead = set(), set()
    if answered:
        r, miss = cas.run(pricing.upbit_spot_krw, syms, dead=dead, answered=got)
    else:
        r, miss = cas.run(pricing.upbit_spot_krw, syms, dead=dead)
    chk(miss is None, "카세트 전송 이상 없음", miss)
    return r, got, dead


r, got, _d = krw(["AAA", "QQQ"], "404")
chk(r == {"AAA": 1540.0} and got == {"AAA", "QQQ"}, "A1 개시 전 마켓이 든 배치 404 = 개시 전만 시세 없음(나눠 다시 — test_upbit_krw_404) · 그 배치 심볼 전부 답함", (r, sorted(got)))
r, got, _d = krw(["AAA", "QQQ"], "omit")
chk(r == {"AAA": 1540.0} and got == {"AAA", "QQQ"}, "A2 정상 응답에서 빠진 심볼도 답함 · 값은 있는 것만", (r, sorted(got)))
r, got, _d = krw(["AAA", "QQQ"], "5xx")
chk(r == {} and not got, "A3 5xx = 답함 아님(조회 실패)", (r, sorted(got)))
r, got, dead = krw(["AAA", "QQQ"], "timeout")
chk(r == {} and not got and dead == {"upbit"}, "A4 시간 초과 = 답함 아님 · 이번 바퀴 업비트 시간 초과", (r, sorted(got), sorted(dead)))
r, _g, _d = krw(["AAA", "BBB"], "ok", answered=False)
chk(r == {"AAA": 1540.0, "BBB": 1540.0}, "A5 answered 없음 = 종전 값", r)


def fresh():
    sp = view_spot.Spot()
    sp.ex_usd, sp.ex_ts, sp.ex_want, sp._ex_done = {}, {}, {"upbit"}, set()
    sp.usd, sp.usd_ts = {}, {}
    sp.upbit_krw, sp.upbit_alt = set(SYMS), {}
    sp.rate, sp.rate_ts = 1400.0, CLK.t() - 60
    sp._mk_at = CLK.t()
    sp._gt_round = lambda now: None
    sp._ds_round = lambda now: None
    sp._okx_creds = lambda: None
    sp.want(SYMS)
    return sp


sp = fresh()
OLD = int(CLK.t()) - 7200
sp.ex_usd["upbit:F054"], sp.ex_ts["upbit:F054"] = 1.0, OLD
NET["mode"], NET["watch"], NET["mid"] = "404", sp, []
_r, miss = cas.run(sp.tick)
NET["watch"] = None
chk(len(NET["mid"]) >= 2 and not any(NET["mid"]), "A6 배치 사이(첫 배치 정상 응답 · 가격 저장 전) = 첫 배치 코인이 거래 시작 전으로 안 보임", NET["mid"])
chk(miss is None, "카세트 전송 이상 없음(tick)", miss)
first = SYMS[:50]
chk(all(sp.ex_ts.get(f"upbit:{s}") == int(sp.updated) for s in first) and abs(sp.ex_usd.get("upbit:F000", 0) - 1.1) < 1e-9,
    "A6 개시 전 마켓 없는 첫 배치 = 이번 바퀴 값", (sp.ex_usd.get("upbit:F000"), sp.ex_ts.get("upbit:F000"), int(sp.updated)))
chk(set(SYMS) <= sp.upbit_answered, "A6 두 배치 심볼 전부 답함(둘째 = 404)", sorted(set(SYMS) - set(sp.upbit_answered)))
chk(abs(sp.ex_usd.get("upbit:F054", 0) - 1.1) < 1e-9 and sp.ex_ts.get("upbit:F054") == int(sp.updated) and "upbit:QQQ" not in sp.ex_ts,
    "A6 404 배치 = 받은 적 있는 코인은 나눠 다시 받은 이번 바퀴 값·시각(test_upbit_krw_404) · 개시 전 마켓 시세 없음", (sp.ex_usd.get("upbit:F054"), sp.ex_ts.get("upbit:F054")))


hb = Holder(sp)
chk(view_b_cards._pre_listed("QQQ", sb=hb) and not view_b_cards._pre_listed("F054", sb=hb) and not view_b_cards._pre_listed("F000", sb=hb),
    "A7 거래 시작 전 = 목록에 있음 · 답함 · 업비트 시세 받은 적 없음만(받은 적 있는 F054·이번에 받은 F000 = 아님)",
    [(s, view_b_cards._pre_listed(s, sb=hb)) for s in ("QQQ", "F054", "F000")])
sp2 = fresh()
chk(not view_b_cards._pre_listed("QQQ", sb=Holder(sp2)), "A7 답하기 전(새 Spot · 재시작 직후) = 아님(미조회 대기)", sorted(sp2.__dict__.get("upbit_answered") or ()))
sp.upbit_krw = set(SYMS) - {"QQQ"}
chk(not view_b_cards._pre_listed("QQQ", sb=hb), "A7 목록 밖 = _pre_listed 아님(목록에 없음 규칙이 따로 맡음)")
T.finish()
