#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _cassette as C  # noqa: E402

C.freeze()
import json  # noqa: E402
import time  # noqa: E402

RATE = 1400.0
STEP = {"bithumb": None, "okx": None}


def _row(krw, vol="12.5"):
    return {"closing_price": str(krw), "units_traded_24H": vol}


def _bth(rows):
    d = dict(rows)
    d["date"] = "1760000000000"
    return {"status": "0000", "data": d}


def _okx(rows):
    return {"code": "0", "data": [{"instId": f"{s}-USDT", "last": str(p), "vol24h": "100"} for s, p in rows.items()]}


def respond(rq):
    if rq.host == "api.upbit.com" and rq.path == "/v1/orderbook":
        return [{"market": "KRW-USDT", "orderbook_units": [{"ask_price": RATE, "bid_price": RATE - 1}]}]
    if rq.host == "api.upbit.com" and rq.path == "/v1/market/all":
        return [{"market": "KRW-BTC"}]
    if rq.host == "open.er-api.com":
        return {"result": "success", "rates": {"KRW": 1390.0}}
    if rq.host == "api.bithumb.com" and rq.path == "/public/ticker/ALL_KRW":
        return STEP["bithumb"]
    if rq.host == "www.okx.com" and rq.path == "/api/v5/market/tickers":
        return STEP["okx"]
    raise AssertionError("모르는 요청 " + rq.url)


import paths  # noqa: E402
import view_spot  # noqa: E402

cas = C.Cassette("bthgap", responder=respond)


def tick(sp, bth=None, okx=None):
    STEP["bithumb"], STEP["okx"] = bth, okx
    sp._ex_at = {}
    sp.tick()
    return sp


def fresh(*exs):
    sp = view_spot.Spot()
    sp.ex_usd, sp.ex_ts, sp.ex_want, sp._ex_done = {}, {}, set(exs), set()
    return sp


class _RaceTs(dict):

    def __init__(self, sp, key, *a):
        super().__init__(*a)
        self.sp, self.key, self.fired = sp, key, False

    def get(self, k, d=None):
        v = super().get(k, d)
        if k == self.key and not self.fired:
            self.fired = True
            self.sp._gap_keys = frozenset()
            self[k] = int(time.time())
        return v


def race(sp):
    sp.ex_ts = _RaceTs(sp, "bithumb:AAA", sp.ex_ts)
    try:
        return (sp.ex_price("bithumb", "AAA"), sp.ex_ts.fired)
    finally:
        sp.ex_ts = dict(sp.ex_ts)


def scenario():
    o = {}
    sp = fresh("bithumb")
    cap = view_spot.GAP_CARRY_SEC["bithumb"]
    o["cap"] = cap
    tick(sp, _bth({"AAA": _row(1400), "BBB": _row(2800)}))
    o["b1"] = (sp.ex_usd.get("bithumb:AAA"), sp.ex_usd.get("bithumb:BBB"), sp.ex_ts.get("bithumb:BBB") == int(time.time()), sp.ex_pending("bithumb"))
    ts = sp.ex_ts["bithumb:BBB"] = int(time.time()) - 600
    tick(sp, _bth({"AAA": _row(1540)}))
    o["b2"] = (sp.ex_usd.get("bithumb:AAA"), sp.ex_usd.get("bithumb:BBB"), sp.ex_ts.get("bithumb:BBB") == ts,
               sp.ex_price("bithumb", "BBB"), round(sp.ex_age("bithumb", "BBB") or 0))
    ts = sp.ex_ts["bithumb:BBB"] = int(time.time()) - 2 * 3600
    tick(sp, _bth({"AAA": _row(1540)}))
    o["b3"] = (sp.ex_usd.get("bithumb:BBB"), sp.ex_ts.get("bithumb:BBB") == ts, sp.ex_price("bithumb", "BBB"), "bithumb:BBB" in sp._gap_keys)
    o["b5"] = []
    for name, wire in (("HTTP 500", C.Reply({"status": "5000"}, status=500)), ("status 오류", {"status": "5600", "message": "점검"}),
                       ("빈 data", {"status": "0000", "data": {}})):
        sp.ex_ts["bithumb:BBB"] = int(time.time()) - cap - 60
        snap = (dict(sp.ex_usd), dict(sp.ex_ts))
        tick(sp, wire)
        o["b5"].append((name, (sp.ex_usd, sp.ex_ts) == snap))
    sp2 = fresh("bithumb")
    tick(sp2, {"status": "5600"})
    o["b5_first"] = (sp2.ex_pending("bithumb"), dict(sp2.ex_usd))
    tick(sp, _bth({"AAA": _row(1540)}))
    o["b4"] = ("bithumb:BBB" in sp.ex_usd, "bithumb:BBB" in sp.ex_ts, "bithumb:BBB" in sp._gap_keys)
    tick(sp, _bth({"AAA": _row(1540), "BBB": _row(4200)}))
    o["b6"] = (sp.ex_usd.get("bithumb:BBB"), sp.ex_ts.get("bithumb:BBB") == int(time.time()))
    sp.ex_ts["bithumb:BBB"] = int(time.time()) - 60
    tick(sp, _bth({"AAA": _row(1540), "BBB": _row(4200, vol="0")}))
    o["b7"] = ("bithumb:BBB" in sp.ex_usd, "BBB" in sp.ex_dead_syms.get("bithumb", ()))
    sp3 = fresh("okx")
    tick(sp3, okx=_okx({"AAA": 1.0, "BBB": 2.0}))
    sp3.ex_ts["okx:BBB"] = int(time.time()) - 60
    tick(sp3, okx=_okx({"AAA": 1.0}))
    o["b8_okx"] = sorted(sp3.ex_usd)
    sp4 = fresh("bithumb")
    tick(sp4, _bth({"AAA": _row(1400), "BBB": _row(2800), "CCC": _row(1400)}))
    for k in list(sp4.ex_ts):
        sp4.ex_ts[k] = int(time.time()) - cap - 60
    tick(sp4, _bth({"AAA": _row(1400)}))
    o["b8_cut"] = sorted(sp4.ex_usd)
    sp5 = fresh("bithumb")
    tick(sp5, _bth({"AAA": _row(1400), "BBB": _row(2800), "CCC": _row(1400)}))
    tick(sp5, _bth({"AAA": _row(1400), "BBB": _row(2800)}))
    tick(sp5, _bth({"AAA": _row(1400), "BBB": _row(2800, vol="0")}))
    o["b10"] = sorted(sp5.ex_usd)
    sp6 = fresh("bithumb")
    tick(sp6, _bth({s9: _row(1400) for s9 in ("AAA", "BBB", "CCC", "DDD", "EEE")}))
    tick(sp6, _bth({"AAA": _row(1400), "BBB": _row(2800, vol="0")}))
    o["b10_cut"] = sorted(sp6.ex_usd)
    sp7 = fresh("bithumb")
    tick(sp7, _bth({"AAA": _row(1400), "BBB": _row(2800)}))
    sp7.ex_ts["bithumb:AAA"] = int(time.time()) - 2 * 3600
    tick(sp7, {"status": "5600"})
    o["b11"] = (sp7.ex_usd.get("bithumb:AAA"), sp7.ex_price("bithumb", "AAA"), "bithumb:AAA" in sp7._gap_keys)
    tick(sp7, _bth({"AAA": _row(1400)}))
    sp7.ex_ts["bithumb:BBB"] = int(time.time()) - 2 * 3600
    tick(sp7, {"status": "5600"})
    o["b12"] = (sp7.ex_price("bithumb", "BBB"), "bithumb:BBB" in sp7._gap_keys)
    sp8 = view_spot.Spot()
    sp8.ex_want = {"bithumb"}
    o["b14"] = [sp8.ex_usd.get("bithumb:BBB"), sp8.ex_price("bithumb", "BBB")]
    tick(sp8, _bth({"AAA": _row(1400)}))
    o["b14"] += [sp8.ex_price("bithumb", "BBB"), sp8.ex_ts.get("bithumb:BBB") == sp7.ex_ts.get("bithumb:BBB")]
    tick(sp7, _bth({"AAA": _row(1400), "BBB": _row(4200)}))
    hit9 = "bithumb:BBB" in sp7._gap_keys
    sp7.ex_ts["bithumb:BBB"] = int(time.time()) - 2 * 3600
    o["b13"] = (hit9, sp7.ex_price("bithumb", "BBB"))
    sp9 = fresh("bithumb")
    tick(sp9, _bth({s9: _row(1400) for s9 in ("AAA", "BBB", "CCC", "DDD", "EEE")}))
    for k in list(sp9.ex_ts):
        sp9.ex_ts[k] = int(time.time()) - 2 * 3600
    tick(sp9, _bth({"AAA": _row(1400)}))
    o["b15"] = (sorted(sp9._gap_keys), sp9.ex_usd.get("bithumb:BBB"), sp9.ex_price("bithumb", "BBB"))
    sp10 = fresh("bithumb")
    tick(sp10, _bth({"AAA": _row(1400), "BBB": _row(2800)}))
    tick(sp10, _bth({"AAA": _row(1400)}))
    sp10.ex_ts["bithumb:BBB"] = int(time.time()) - 2 * 3600
    tick(sp10, _bth({"BBB": _row(2800, vol="0")}))
    o["b16"] = (sorted(sp10.ex_usd), sorted(sp10._gap_keys), sp10.ex_price("bithumb", "BBB"))
    sp10.ex_ts["bithumb:AAA"] = int(time.time()) - 2 * 3600
    sp10._gap_keys = frozenset({"bithumb:AAA"})
    o["b17"] = sp10.ex_price("bithumb", "AAA") if isinstance(sp10.ex_ts, dict) else None
    o["b17_race"] = race(sp10)
    ts = sp.ex_ts["bithumb:AAA"] = int(time.time()) - 300
    tick(sp, _bth({"BBB": _row(4200), "CCC": _row(1400)}))
    d9 = json.load(open(paths.state("spot.json"), encoding="utf-8"))
    o["b9"] = (d9["ex_usd"].get("bithumb:AAA"), d9["ex_ts"].get("bithumb:AAA") == ts, sorted(d9))
    return o


if cas.ready(T):
    o, why = cas.run(scenario)
    T.chk(why is None and o, "카세트 시나리오 끝까지", why)
    o = o or {}
    T.chk(o.get("cap") == 6 * 3600, "상한 = 6시간(상수 하나)", o.get("cap"))
    T.chk(o.get("b1") == (1.0, 2.0, True, False), "B1 1회 A·B = 둘 다 시세 · 받은 시각 = 그 tick · 조회 완료", o.get("b1"))
    T.chk(o.get("b2") == (1.1, 2.0, True, 2.0, 600), "B2 A 만 = B 직전 값 · 받은 시각 그대로 · ex_price = 값 · 나이 = 원래 시각 기준", o.get("b2"))
    T.chk(o.get("b3") == (2.0, True, 2.0, True), "B3 이어 쓰는 중 1~6시간 = 남김(시각 그대로) · ex_price = 값(상한 GAP_CARRY_SEC) · 표시 있음", o.get("b3"))
    T.chk(o.get("b5") and all(x[1] for x in o["b5"]), "B5 응답 실패(HTTP 500 · status 오류 · 빈 data) = 아무것도 안 바뀜(종전)", o.get("b5"))
    T.chk(o.get("b5_first") == (True, {}), "B5 처음부터 실패 = 조회 완료 아님(동결 유예 종전)", o.get("b5_first"))
    T.chk(o.get("b4") == (False, False, False), "B4 상한 넘은 직전 값 = 지움 · 표시 해제", o.get("b4"))
    T.chk(o.get("b11") == (1.0, None, False), "B11 조회 실패로 묵은 값(이어 쓰는 중 아님) 1시간 넘음 = ex_price None(종전)", o.get("b11"))
    T.chk(o.get("b12") == (2.0, True), "B12 이어 쓰는 중에 조회 실패 = 표시 유지 · 상한 안 = 값", o.get("b12"))
    T.chk(o.get("b13") == (False, None), "B13 다시 오면 표시 해제 · 그 뒤 1시간 넘은 값 = None(종전)", o.get("b13"))
    T.chk(o.get("b14") == [2.0, None, 2.0, True], "B14 재시작 = 표시 없음(1시간 규칙) → 다음 정상 응답에 빠지면 다시 표시 · 시각 그대로", o.get("b14"))
    T.chk(o.get("b15") == ([], 1.0, None), "B15 잘린 응답에서 처음 빠진 키 = 표시 안 함(남되 1시간 규칙)", o.get("b15"))
    T.chk(o.get("b6") == (3.0, True), "B6 돌아온 B = 새 값 · 새 시각", o.get("b6"))
    T.chk(o.get("b7") == (False, True), "B7 24h 거래 0 = 상한 안이어도 바로 지움(종전)", o.get("b7"))
    T.chk(o.get("b8_okx") == ["okx:AAA"], "B8 OKX 빠진 코인 = 바로 지움(종전)", o.get("b8_okx"))
    T.chk(o.get("b8_cut") == ["bithumb:AAA", "bithumb:BBB", "bithumb:CCC"], "B8 잘린 응답(절반 미만) = 상한 넘어도 안 지움(종전)", o.get("b8_cut"))
    T.chk(o.get("b10") == ["bithumb:AAA", "bithumb:CCC"], "B10 이어 쓴 키(C)가 절반 규칙을 막아도 24h 거래 0(B) = 지움 · C = 이어 씀", o.get("b10"))
    T.chk(o.get("b10_cut") == ["bithumb:AAA", "bithumb:CCC", "bithumb:DDD", "bithumb:EEE"], "B10 잘린 응답 = 빠진 키 안 지움(종전) · 응답에 있는 24h 거래 0 = 지움",
          o.get("b10_cut"))
    T.chk(o.get("b16") == (["bithumb:AAA"], [], None), "B16 24h 거래 0 페어만 온 응답 = 이어 쓰던 그 페어 지움 · 표시 해제", o.get("b16"))
    T.chk(o.get("b17") == 1.0 and list(o.get("b17_race") or ()) == [1.0, True], "B17 시각 읽는 사이 tick 이 표시를 풀어도 = 값(상한을 먼저 읽음)",
          (o.get("b17"), o.get("b17_race")))
    b9 = o.get("b9") or (None, None, [])
    T.chk(b9[:2] == (1.1, True), "B9 spot.json = 이어 쓴 값 · 받은 시각 그대로", b9[:2])
    T.chk("ex_usd" in b9[2] and "ex_ts" in b9[2] and not [k for k in b9[2] if "gap" in k], "B9 spot.json 키 무변(새 필드 없음)", b9[2])
    cas.golden(T, {"out": o, "state": C.snap_tree(paths.STATE_DIR)})
    cas.check(T)

NOW9 = 1_800_000_000
CAP9 = view_spot.GAP_CARRY_SEC["bithumb"]
OLD9 = ["bithumb:X", "bithumb:Y", "bithumb:Z", "bithumb:W", "bithumb:V"]
TS9 = {"bithumb:X": NOW9 - 60, "bithumb:Y": "abc", "bithumb:Z": NOW9 + CAP9 + 10, "bithumb:V": NOW9 - 60}
T.chk(view_spot._gap_drop("bithumb", OLD9, TS9, {"V"}, NOW9, True) == ["bithumb:Y", "bithumb:Z", "bithumb:W", "bithumb:V"],
      "단위: 시각 없음·이상·24h 거래 0 = 지움 · 상한 안 = 남김", view_spot._gap_drop("bithumb", OLD9, TS9, {"V"}, NOW9, True))
T.chk(view_spot._gap_drop("bithumb", OLD9, TS9, {"V"}, NOW9, False) == ["bithumb:V"], "단위: 잘린 응답 = 24h 거래 0 만 지움")
T.chk(view_spot._gap_drop("gate", ["gate:X"], {"gate:X": NOW9}, {"X"}, NOW9, True) == ["gate:X"]
      and view_spot._gap_drop("gate", ["gate:X"], {"gate:X": NOW9}, {"X"}, NOW9, False) == [], "단위: 다른 거래소 = 전부 지움 · 잘린 응답 = 안 지움(종전)")

T.finish()
