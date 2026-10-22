#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _cassette as C  # noqa: E402

CLK = C.freeze(now=1_800_000_000.0)
import os  # noqa: E402
import socket  # noqa: E402
import urllib.error  # noqa: E402

import hl_spot  # noqa: E402
import paths  # noqa: E402
import pricing  # noqa: E402
import statefile  # noqa: E402
import view_spot  # noqa: E402

chk = T.chk
SYMS = ["AAA", "BTC"] + [f"F{i:03d}" for i in range(118)]
NET = {"down": set(), "calls": {}, "krw": 1500.0}
COST_TO = 80.0
SAME_PX = {sym: 10.0 for sym, _cid in hl_spot.SAME_COIN.values() if sym not in hl_spot.STABLE_FACE}
ZK = "ZZT@151"


def _hl_info(t):
    if t == "spotMeta":
        return {"tokens": [{"name": "USDC", "index": 0, "tokenId": "0x" + "00" * 16}, {"name": "HYPE", "index": 150, "tokenId": "0x" + "11" * 16},
                           {"name": "ZZT", "index": 151, "tokenId": "0x" + "22" * 16}],
                "universe": [{"name": "HYPE/USDC", "index": 107, "tokens": [150, 0]}, {"name": "@108", "index": 108, "tokens": [151, 0]}]}
    if t == "allMids":
        return {"HYPE/USDC": "40.3", "@107": "40.3", "@108": "2.5"}
    return {}


def respond(rq):
    h, p = rq.host, rq.path
    NET["calls"][h] = NET["calls"].get(h, 0) + 1
    if h in NET["down"]:
        CLK.now += COST_TO
        return C.Reply(exc="timeout")
    CLK.now += 1.0 if h == "api.hyperliquid.xyz" else 0.3
    if h == "api.upbit.com":
        if p == "/v1/orderbook":
            return [{"market": "KRW-USDT", "orderbook_units": [{"ask_price": 1400.0, "bid_price": 1399.0}]}]
        if p == "/v1/market/all":
            return [{"market": f"KRW-{s}"} for s in SYMS]
        if p == "/v1/ticker":
            return [{"market": m, "trade_price": NET["krw"]} for m in rq.query["markets"].split(",")]
    if h == "open.er-api.com":
        return {"result": "success", "rates": {"KRW": 1390.0}}
    if h == "api.binance.com" and p == "/api/v3/ticker/price":
        return [{"symbol": k + "USDT", "price": str(v)} for k, v in dict(SAME_PX, BTC=100000.0, HYPE=40.5, AAA=1.2).items()]
    if h == "api.binance.com" and p == "/api/v3/ticker/24hr":
        return [{"symbol": "BTCUSDT", "count": 10, "closeTime": int(CLK.t() * 1000)}]
    if h == "api.bithumb.com":
        return {"status": "0000", "data": {"AAA": {"closing_price": "2800", "units_traded_24H": "5"}, "date": "1"}}
    if h == "api.bybit.com":
        return {"retCode": 0, "result": {"list": [{"symbol": k + "USDT", "lastPrice": str(v), "volume24h": "9"}
                                                  for k, v in dict(SAME_PX, HYPE=40.1).items()]}}
    if h == "api.hyperliquid.xyz":
        return _hl_info((rq.json() or {}).get("type"))
    raise AssertionError("모르는 요청 " + rq.url)


CDIR = os.path.join(T.TMP, "cas_wtick")
os.makedirs(CDIR, exist_ok=True)
cas = C.Cassette("wtick", responder=respond, dirpath=CDIR, record=True)


def fresh(exs=("upbit", "bithumb", "hyperliquid"), known_list=True):
    hl_spot._META.clear()
    sp = view_spot.Spot()
    sp.ex_usd, sp.ex_ts, sp.ex_want, sp._ex_done = {}, {}, set(exs), set()
    sp.usd, sp.usd_ts = {}, {}
    sp.upbit_krw = set(SYMS) if known_list else set()
    sp.upbit_alt = {}
    sp.rate, sp.rate_ts = 1400.0, CLK.t() - 60
    sp._mk_at = 0
    sp._gt_round = lambda now: None
    sp._ds_round = lambda now: None
    sp._okx_creds = lambda: None
    sp.want(SYMS)
    return sp


def tick(sp, c=cas):
    NET["calls"] = {}
    sp._ex_at = {}
    t0 = CLK.t()
    _r, miss = c.run(sp.tick)
    chk(miss is None, "카세트 전송 이상 없음", miss)
    return CLK.t() - t0, dict(NET["calls"])


sp = fresh()
OLD_TS = int(CLK.t()) - 600
sp.ex_usd["upbit:AAA"], sp.ex_ts["upbit:AAA"] = 0.9, OLD_TS
rate_ts0 = sp.rate_ts
NET["down"] = {"api.upbit.com"}
sec, calls = tick(sp)
chk(calls.get("api.upbit.com") == 1, "W1 업비트 시간 초과 = 그 바퀴 업비트 1콜(환율만 · 마켓 목록·원화 배치 3개 안 부름 — 종전 5콜)", calls)
chk(sec <= 90, "W1 한 바퀴 ≤ 90초(시간 초과 1번 + 정상 · 종전 ≈ 400초)", sec)
sj = statefile.read_json(paths.state("spot.json"), {})
chk((sj.get("tick") or {}).get("sec", 999) <= 90, "W1 spot.json 한 바퀴 소요 = 위와 같음", sj.get("tick"))
now1 = int(sp.updated)
chk(sp.ex_usd.get("bithumb:AAA") == 2.0 and sp.ex_ts.get("bithumb:AAA") == now1 and "bithumb" in sp._ex_done,
    "W2 빗썸 = 이번 바퀴 값(마지막 환율 1400 환산) · 조회 완료", (sp.ex_usd.get("bithumb:AAA"), sp.ex_ts.get("bithumb:AAA"), now1))
chk(sp.price("BTC") == 100000.0, "W2 글로벌(바이낸스) = 이번 바퀴 값", sp.price("BTC"))
chk(sp.ex_usd.get("hyperliquid:" + ZK) == 2.5 and sp.ex_usd.get("hyperliquid:HYPE") == 40.5 and "hyperliquid" in sp._ex_done,
    "W3 Hyperliquid 성공(앞 단계 80초 뒤에도 — 마감 = 자기 단계 시작 + 30초) · HYPE = 바이낸스 같은 코인 시세",
    {k: v for k, v in sp.ex_usd.items() if k.startswith("hyperliquid:")})
chk(sp.ex_usd.get("upbit:AAA") == 0.9 and sp.ex_ts.get("upbit:AAA") == OLD_TS, "W4 업비트 = 마지막 값·받은 시각 그대로",
    (sp.ex_usd.get("upbit:AAA"), sp.ex_ts.get("upbit:AAA")))
chk(sp.rate == 1400.0 and sp.rate_ts == rate_ts0 and sp._mk_at == 0, "W4 환율 마지막 값·시각 그대로 · 마켓 목록 다음 바퀴 다시(_mk_at 그대로)",
    (sp.rate, sp.rate_ts, sp._mk_at))
chk(sp._tick_to == {"upbit"}, "W4 이번 바퀴 시간 초과 거래소 = 업비트만", sorted(sp._tick_to))
sp0 = fresh(known_list=False)
sec0, calls0 = tick(sp0)
chk(calls0.get("api.upbit.com") == 1 and "upbit" not in sp0._ex_done and not sp0.upbit_krw,
    "W4 목록 없던 설치본 + 업비트 시간 초과 = 업비트 '조회 완료' 아님(목록 못 받음 — 종전 실패와 같음)", (calls0, sorted(sp0._ex_done)))

sec, calls = tick(sp)
chk(calls.get("api.upbit.com") == 1 and sp.ex_usd.get("hyperliquid:" + ZK) == 2.5, "W5 다음 바퀴 = 업비트 다시 1콜(영구 건너뜀 아님)", calls)
NET["down"] = set()
NET["krw"] = 1540.0
sec, calls = tick(sp)
chk(calls.get("api.upbit.com") == 5, "W6 회복 = 업비트 5콜(환율·마켓 목록·원화 배치 3개)", calls)
chk(abs(sp.ex_usd.get("upbit:AAA", 0) - 1.1) < 1e-9 and sp.ex_ts.get("upbit:AAA") == int(sp.updated) and sp._mk_at > 0 and not sp._tick_to,
    "W6 업비트 새 값·새 시각 · 마켓 목록 갱신 · 시간 초과 표 비움", (sp.ex_usd.get("upbit:AAA"), sp._mk_at, sorted(sp._tick_to)))

sp = fresh(exs=("binance", "bithumb", "hyperliquid"))
OLD_TS = int(CLK.t()) - 300
sp.ex_usd["binance:BTC"], sp.ex_ts["binance:BTC"] = 99000.0, OLD_TS
NET["down"] = {"api.binance.com"}
sec, calls = tick(sp)
chk(calls.get("api.binance.com") == 1, "W7 바이낸스 시간 초과 = 그 바퀴 1콜(거래소별·Hyperliquid 같은 코인 시세는 안 부름 — 종전 3콜)", calls)
chk("binance" not in sp._ex_done and sp._ex_at.get("binance") and sp.ex_usd.get("binance:BTC") == 99000.0 and sp.ex_ts.get("binance:BTC") == OLD_TS,
    "W7 건너뛴 거래소 = 조회 실패 그대로(완료 표시 없음 · 직전 값·시각 그대로 · 다음 주기 다시)",
    (sorted(sp._ex_done), sp.ex_usd.get("binance:BTC"), sp.ex_ts.get("binance:BTC")))
chk(sp.ex_usd.get("hyperliquid:HYPE") == 40.1 and "바이빗" in (sp.hl_src.get("HYPE") or "") and "hyperliquid" in sp._ex_done and "bithumb" in sp._ex_done,
    "W7 Hyperliquid = 바이빗 같은 코인 시세로 성공 · 빗썸 정상", (sp.ex_usd.get("hyperliquid:HYPE"), sp.hl_src.get("HYPE")))
chk(sec <= 90, "W7 한 바퀴 ≤ 90초", sec)
NET["down"] = set()

cas_r = C.Cassette("wtick_refuse", responder=respond, dirpath=CDIR, record=True, conn_events={"api.upbit.com:443": ["refused"] * 5})
sp = fresh()
sec, calls = tick(sp, cas_r)
n_up = sum(1 for k9, ev, _p in cas_r.conn_log if k9 == "api.upbit.com:443" and ev == "refused")
chk(n_up == 5 and not calls.get("api.upbit.com") and not sp._tick_to, "W8 연결 거부(빠른 실패) = 건너뜀 없음(종전 그대로 5번 시도)",
    (n_up, calls, sorted(sp._tick_to)))

NET["down"] = {"api.upbit.com"}


def krw(dead=None, use=True):
    NET["calls"] = {}
    r, _m = cas.run(pricing.upbit_spot_krw, SYMS, dead=dead) if use else cas.run(pricing.upbit_spot_krw, SYMS)
    return r, NET["calls"].get("api.upbit.com", 0)


r, n = krw(use=False)
chk(r == {} and n == 3, "W9 dead 없음 = 종전(배치마다 시도 · 3콜)", n)
d9 = set()
r, n = krw(d9)
chk(r == {} and n == 1 and d9 == {"upbit"}, "W9 dead 집합 = 첫 시간 초과에서 멈춤 · 'upbit' 넣음", (n, d9))
r, n = krw({"upbit"})
chk(r == {} and n == 0, "W9 이미 시간 초과 = 0콜", n)
NET["down"] = set()

cases = [(urllib.error.URLError(socket.timeout("timed out")), True), (TimeoutError("x"), True), (socket.timeout("timed out"), True),
         (urllib.error.HTTPError("https://x/", 504, "Gateway Time-out", {}, None), False),
         (urllib.error.URLError(ConnectionRefusedError(61, "refused")), False), (urllib.error.URLError(socket.gaierror(8, "nodename")), False),
         (pricing.BulkError("upbit", {"error": 1}), False), (view_spot._TickSkip("upbit 이번 바퀴 시간 초과"), False),
         (pricing.BulkError("bybit", {"retCode": 10000, "retMsg": "request timed out"}), False), (ValueError("timed out"), False)]
got = [pricing.timed_out(e) for e, _ in cases]
chk(got == [w for _, w in cases], "W10 시간 초과만 True(HTTP 오류·거부·DNS·오류 응답(본문에 'timed out' 글자가 있어도)·건너뜀 표식 아님)", got)

t_start = CLK.t()
CLK.now += COST_TO
r, _m = cas.run(T.safe, hl_spot.fetch_book, t_start)
chk(isinstance(r, dict) and "_exc" in r and "Budget" in r["_exc"], "W11 종전(tick 시작 now 로 마감) = 80초 뒤 Budget(라이브 '조회 실패: ' 빈 문구 재현)", r)
r, _m = cas.run(T.safe, hl_spot.fetch_book, t_start, deadline=hl_spot.CLOCK() + 30)
chk(isinstance(r, dict) and r.get(ZK) == 2.5, "W11 고친 방식(단계 시작 + 30초) = 성공", r)

T.finish()
