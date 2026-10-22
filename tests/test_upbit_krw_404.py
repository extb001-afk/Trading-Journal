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
SECOND = SYMS[50:]
NET = {"mode": "ok", "pre": {"QQQ"}, "log": [], "fail_at": None}


class Holder:

    def __init__(self, s):
        self.spot = s


def px_of(m):
    return 1000.0 + sum(ord(c) for c in m)


def respond(rq):
    h, p = rq.host, rq.path
    if h == "api.upbit.com":
        if p == "/v1/orderbook":
            return [{"market": "KRW-USDT", "orderbook_units": [{"ask_price": 1400.0, "bid_price": 1399.0}]}]
        if p == "/v1/market/all":
            return [{"market": f"KRW-{s}"} for s in SYMS]
        if p == "/v1/ticker":
            mk = rq.query["markets"].split(",")
            NET["log"].append((CLK.t(), len(mk)))
            n = len(NET["log"])
            if NET["mode"] == "timeout" or (NET["fail_at"] == n and NET["mode"] == "late_timeout"):
                CLK.now += 80.0
                return C.Reply(exc="timeout")
            if NET["mode"] == "5xx" or (NET["fail_at"] == n and NET["mode"] == "late_5xx") or (NET["mode"] == "mix5xx" and n <= 8):
                return C.Reply({"error": {"name": "server"}}, status=503)
            if NET["mode"] == "all404" or any(m[4:] in NET["pre"] for m in mk):
                return C.Reply({"error": {"name": "404", "message": "Code not found"}}, status=404)
            return [{"market": m, "trade_price": px_of(m[4:])} for m in mk]
    if h == "open.er-api.com":
        return {"result": "success", "rates": {"KRW": 1390.0}}
    if h == "api.binance.com" and p == "/api/v3/ticker/price":
        return [{"symbol": "BTCUSDT", "price": "100000.0"}]
    if h == "api.binance.com" and p == "/api/v3/ticker/24hr":
        return [{"symbol": "BTCUSDT", "count": 10, "closeTime": int(CLK.t() * 1000)}]
    raise AssertionError("모르는 요청 " + rq.url)


CDIR = os.path.join(T.TMP, "cas_k404")
os.makedirs(CDIR, exist_ok=True)
cas = C.Cassette("k404", responder=respond, dirpath=CDIR, record=True)


def krw(syms, mode="ok", pre=("QQQ",), seen=None, fail_at=None):
    NET.update(mode=mode, pre=set(pre), log=[], fail_at=fail_at)
    got, dead = set(), set()
    kw = {"dead": dead, "answered": got}
    if seen is not None:
        kw["seen"] = set(seen)
    try:
        r, miss = cas.run(pricing.upbit_spot_krw, syms, **kw)
    except TypeError as e:
        chk(False, "upbit_spot_krw(seen=…) 부를 수 있음", repr(e))
        r, miss = cas.run(pricing.upbit_spot_krw, syms, dead=dead, answered=got)
    chk(miss is None, "카세트 전송 이상 없음", miss)
    return r, got, dead, len(NET["log"])


def want(syms, pre):
    return {s: px_of(s) for s in syms if s not in pre}


CAP = 2 + getattr(pricing, "UPBIT_404_CALLS", 16)
r, got, dead, n = krw(SYMS, "ok", seen=[s for s in SYMS if s != "QQQ"])
chk(r == want(SYMS, {"QQQ"}), "B1 개시 전 마켓이 든 배치의 정상 코인 6개 = 시세 있음(고치기 전 = 없음)", sorted(set(want(SYMS, {"QQQ"})) - set(r)))
chk("QQQ" not in r and set(SYMS) <= got and not dead, "B1 개시 전 = 시세 없음 · 404 배치 심볼 전부 답함(종전 규칙)", (sorted(set(SYMS) - got), sorted(dead)))
chk(n == 4, "B1 호출 = 배치 2 + 받은 적 있는 것만 1 + 개시 전 홀로 1", (n, NET["log"]))
r, got, dead, n = krw(SYMS, "ok", seen=())
chk(r == want(SYMS, {"QQQ"}), "B2 seen 비었음 = 반 나눔으로 정상 코인 전부 시세", sorted(set(want(SYMS, {"QQQ"})) - set(r)))
chk(n <= CAP and set(SYMS) <= got, "B2 호출 상한 안 · 답함 전부", (n, CAP))
r, got, dead, n = krw(SYMS, "ok", seen=[s for s in SYMS if s not in ("QQQ", "F050", "F053")])
chk(r == want(SYMS, {"QQQ"}), "B2 받은 적 없는 정상 2 + 개시 전 1 = 정상 전부 시세", sorted(set(want(SYMS, {"QQQ"})) - set(r)))
chk(n <= CAP, "B2 호출 상한 안", n)
r, got, dead, n = krw(SYMS, "ok")
chk(r == want(SYMS, {"QQQ"}) and n <= CAP, "B2 seen 없음(None) = 반 나눔만으로도 정상 전부", (sorted(set(want(SYMS, {"QQQ"})) - set(r)), n))
r, got, dead, n = krw(SYMS, "ok", pre=("QQQ", "F051"), seen=[s for s in SYMS if s not in ("QQQ", "F051")])
chk(r == want(SYMS, {"QQQ", "F051"}) and n <= CAP, "B3 개시 전 2 = 나머지 정상 전부 시세 · 상한 안", (sorted(set(want(SYMS, {"QQQ", "F051"})) - set(r)), n))
W50 = want(SYMS[:50], {"F003", "F040"})
r, got, dead, n = krw(SYMS[:50], "ok", pre=("F003", "F040"), seen=())
chk(n <= CAP and set(r) <= set(W50) and all(r[s] == W50[s] for s in r), "B3 50개 배치 · 개시 전 2 · seen 없음(새 설치 꼴) = 상한 안 · 받은 값 맞음", (n, CAP))
rounds, seen9 = [n], set(r)
while len(rounds) < 6 and set(r) != set(W50):
    r, got, dead, n = krw(SYMS[:50], "ok", pre=("F003", "F040"), seen=seen9)
    seen9 |= set(r)
    rounds.append(n)
chk(r == W50 and max(rounds) <= CAP and len(rounds) <= 4, "B3 받은 코인이 seen 이 되며 몇 바퀴 안에 정상 48 전부 시세 · 바퀴마다 상한 안", (sorted(set(W50) - set(r)), rounds))
r, got, dead, n = krw(SYMS[:50], "ok", pre=("F003", "F040"), seen=seen9)
chk(r == W50 and n == 1 + 1 + 3, "B3 수렴 뒤 = 배치 1 + 받은 것 1 + 개시 전 둘 나눔 3", (n, [k for _t, k in NET["log"]]))
seen9 = [s for s in SYMS[:50] if s != "F030"]
r, got, dead, n = krw(SYMS[:50], "ok", pre=("F020",), seen=seen9)
chk(r == want(SYMS[:50], {"F020"}) and n <= 1 + 14, "B3 개시 전이 seen 쪽 · 정상 하나가 seen 밖 = 한 바퀴에 정상 49 전부 시세(≤ 1 + 14)", (sorted(set(want(SYMS[:50], {"F020"})) - set(r)), n))
r, got, dead, n = krw(SYMS[:50], "ok", pre=("F049",), seen=SYMS)
chk(r == want(SYMS[:50], {"F049"}) and n <= 1 + 14, "B3 50개 전부 seen · 개시 전 끝자리 = 한 바퀴에 정상 49 전부(≤ 1 + 14)", (sorted(set(want(SYMS[:50], {"F049"})) - set(r)), n))
bad = []
for k, pre9 in enumerate(SYMS[:50]):
    other = SYMS[(k + 17) % 50]
    for seen9 in (SYMS, [s for s in SYMS if s != pre9], [s for s in SYMS if s != other]):
        r, got, dead, n = krw(SYMS[:50], "ok", pre=(pre9,), seen=seen9)
        if r != want(SYMS[:50], {pre9}) or n > 1 + 14:
            bad.append((pre9, len(seen9), n, sorted(set(want(SYMS[:50], {pre9})) - set(r))[:3]))
chk(not bad, "B3 개시 전 1개 · 50자리 × seen 3꼴 = 한 바퀴에 정상 49 전부 시세 · 호출 ≤ 1 + 14", bad[:5])
r, got, dead, n = krw(SYMS, "all404", seen=SYMS)
chk(r == {} and n <= CAP and set(SYMS) <= got, "B4 늘 404 = 끝남 · 다시 부르는 수 상한(배치 2 + 상한)", (n, CAP))
big = [f"Z{i:03d}" for i in range(500)]
r, got, dead, n = krw(big, "all404", seen=())
chk(r == {} and n <= 10 + getattr(pricing, "UPBIT_404_CALLS", 16), "B4 500심볼 늘 404 = 배치 10 + 상한(한 번 부르기 전체 합)", n)
ts = [t for t, _k in NET["log"]]
chk(all(sum(1 for u in ts if t <= u < t + 1.0) < 10 for t in ts), "B9 상한을 다 쓴 뒤 남은 원래 배치(늘 404)도 1초 창 10회 미만",
    max(sum(1 for u in ts if t <= u < t + 1.0) for t in ts))
r, got, dead, n = krw(SYMS, "ok", pre=(), seen=SYMS)
chk(r == want(SYMS, ()) and n == 2, "B5 정상(200) = 배치 2 호출 그대로 · 값 그대로", n)
r, got, dead, n = krw(SYMS, "ok", pre=())
chk(r == want(SYMS, ()) and n == 2, "B5 정상(200) · seen 없음 = 배치 2 그대로", n)
r, got, dead, n = krw(SYMS, "5xx", seen=SYMS)
chk(r == {} and n == 2 and not got, "B6 5xx = 배치마다 1번(다시 안 부름) · 답함 아님", (n, sorted(got)))
r, got, dead, n = krw(SYMS, "late_5xx", seen=(), fail_at=3)
chk(n == 3 and "upbit" not in dead, "B7 다시 부르다 5xx = 그 뒤 다시 안 부름", (n, NET["log"]))
chk(set(SYMS[:50]) <= set(r), "B7 첫 배치 값 그대로", sorted(set(SYMS[:50]) - set(r)))
r, got, dead, n = krw(SYMS, "timeout", seen=SYMS)
chk(r == {} and n == 1 and dead == {"upbit"}, "B8 시간 초과 = 1번에 멈춤(종전)", (n, sorted(dead)))
r, got, dead, n = krw(SYMS, "late_timeout", seen=(), fail_at=3)
chk(n == 3 and dead == {"upbit"}, "B8 다시 부르다 시간 초과 = 이번 바퀴 멈춤", (n, sorted(dead)))
r, got, dead, n = krw(SYMS[:50], "ok", pre=("F003", "F040"), seen=())
ts = [t for t, _k in NET["log"]]
gaps = [b - a for a, b in zip(ts, ts[1:])]
chk(n > 2 and gaps and min(gaps) >= 0.12 - 1e-5, "B9 다시 부를 때마다 직전 호출과 0.12초 이상", gaps)
chk(all(sum(1 for u in ts if t <= u < t + 1.0) < 10 for t in ts), "B9 어느 1초 창이든 10회 미만", ts)


mix = [f"M{i:03d}" for i in range(450)]
r, got, dead, n = krw(mix, "mix5xx", pre=("M400",), seen=())
ts = [t for t, _k in NET["log"]]
chk(r == want(mix[400:], {"M400"}) and all(sum(1 for u in ts if t <= u < t + 1.0) < 10 for t in ts),
    "B9 빠른 5xx 원래 배치 8개 뒤 404 다시 부르기 = 1초 창 10회 미만 · 마지막 배치 정상 49 시세",
    (max(sum(1 for u in ts if t <= u < t + 1.0) for t in ts), sorted(set(want(mix[400:], {"M400"})) - set(r))[:3]))


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
for s in SYMS:
    if s != "QQQ":
        sp.ex_usd[f"upbit:{s}"], sp.ex_ts[f"upbit:{s}"] = 1.0, OLD
NET.update(mode="ok", pre={"QQQ"}, log=[], fail_at=None)
_r, miss = cas.run(sp.tick)
chk(miss is None, "카세트 전송 이상 없음(tick)", miss)
now9 = int(sp.updated)
chk(all(sp.ex_ts.get(f"upbit:{s}") == now9 and abs(sp.ex_usd[f"upbit:{s}"] - px_of(s) / 1400.0) < 1e-9 for s in SECOND if s != "QQQ"),
    "B10 개시 전 마켓과 같은 배치 정상 코인 = 이번 바퀴 값·시각(고치기 전 = 2시간 전 값 그대로)",
    [(s, sp.ex_ts.get(f"upbit:{s}")) for s in SECOND])
chk("upbit:QQQ" not in sp.ex_ts and set(SYMS) <= sp.upbit_answered, "B10 개시 전 = 시세 없음 · 답함")
hb = Holder(sp)
chk(view_b_cards._pre_listed("QQQ", sb=hb) and not any(view_b_cards._pre_listed(s, sb=hb) for s in SECOND if s != "QQQ"),
    "B10 거래 시작 전 판정 = 개시 전 코인만", [(s, view_b_cards._pre_listed(s, sb=hb)) for s in SECOND])
chk(len(NET["log"]) == 4, "B10 tick 티커 호출 = 배치 2 + 다시 2", NET["log"])
T.finish()
