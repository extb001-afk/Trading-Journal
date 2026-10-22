#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _cassette as C  # noqa: E402

CLK = C.freeze(now=1_800_000_000.0)
import json  # noqa: E402
import os  # noqa: E402

import paths  # noqa: E402
import view_spot  # noqa: E402

chk = T.chk
CA = "0x" + "1a" * 20
K = "base:" + CA
RESP = {}


def respond(rq):
    if rq.host == "api.geckoterminal.com":
        return {"data": {"attributes": {"token_prices": RESP.get("px", {}), "total_reserve_in_usd": RESP.get("res", {})}}}
    if rq.host == "api.dexscreener.com":
        return RESP["ds"]
    if rq.host == "api.upbit.com" and rq.path == "/v1/orderbook":
        return [{"market": "KRW-USDT", "orderbook_units": [{"ask_price": 1400.0, "bid_price": 1399.0}]}]
    raise AssertionError("모르는 요청 " + rq.url)


CDIR = os.path.join(T.TMP, "cas_jump")
os.makedirs(CDIR, exist_ok=True)
cas = C.Cassette("jump", responder=respond, dirpath=CDIR, record=True)


def run(fn, *a):
    _r, miss = cas.run(fn, *a)
    chk(miss is None, "카세트 전송 이상 없음", miss)


def gt(sp, at, px, res="same"):
    CLK.now = at
    RESP["px"] = {CA: px}
    RESP["res"] = {} if res is None else {CA: "79610.8" if res == "same" else res}
    sp._gt_next_at = 0
    sp._gt_backoff_until = 0
    run(sp._gt_round, CLK.t())


JF = paths.state("dex_jump.json")


def mk():
    if os.path.exists(JF):
        os.remove(JF)
    sp = view_spot.Spot()
    sp.token_pairs = {("base", CA)}
    sp.dex_usd, sp.dex_ts, sp.dex_res, sp.dex_res_ts, sp.dex_src = {}, {}, {}, {}, {}
    sp._res_gecko_ts, sp._gt_polled = {}, {}
    sp.guarded, sp._guard_logged, sp.dex_alt = {}, {}, {}
    return sp


def ok_px(sp):
    return (sp.jump.ok.get(K) or [None])[0]


T0 = CLK.t()
sp = mk()
gt(sp, T0, "0.1507")
chk(sp.dex_price("base", CA) == 0.1507 and ok_px(sp) == 0.1507, "준비: 정상 값 $0.1507 = 확인된 값", (sp.dex_usd, sp.jump.ok))
gt(sp, T0 + 600, "16.15")
v = sp.dex_price("base", CA)
chk(v == 0.0 and sp.guarded.get(K, "").startswith("시세 급변"),
    "J1 (P1) 게코 $16.15 + 유동성 $79k(전 풀 합) = 0 · 가드 '시세 급변'(종전 = 16.15 그대로 · 207개 ≈ ₩450만)", (v, sp.guarded.get(K)))
chk(ok_px(sp) == 0.1507 and (sp.jump.wait.get(K) or [None])[0] == 16.15, "J1 확인된 값 그대로 · 급변 시작 기록", (sp.jump.ok.get(K), sp.jump.wait.get(K)))
gt(sp, T0 + 1200, "0.1508")
v = sp.dex_price("base", CA)
chk(v == 0.1508 and K not in sp.guarded and K not in sp.jump.wait, "J3 정상 값이 다시 오면 그 값 · 가드 풀림 · 급변 기록 지움", (v, sp.guarded.get(K), sp.jump.wait.get(K)))

sp = mk()
gt(sp, T0 + 3000, "0.1507")
gt(sp, T0 + 3600, "16.15", res=None)
v = sp.dex_price("base", CA)
chk(sp.dex_usd.get(K) == 16.15 and sp.dex_reserve("base", CA) == 79610.8, "J2 준비: 가격만 옴 · 직전 유동성 $79k 남음", (sp.dex_usd.get(K), sp.dex_reserve("base", CA)))
chk(v == 0.0 and sp.guarded.get(K, "").startswith("시세 급변"), "J2 (P2) 유동성 칸 없이 가격 $16.15 = 0(종전 = 직전 유동성으로 통과)", (v, sp.guarded.get(K)))

sp = mk()
gt(sp, T0 + 4000, "0.15")
gt(sp, T0 + 4100, "0.74")
chk(sp.dex_price("base", CA) == 0.74 and ok_px(sp) == 0.74 and not sp.guarded, "J4 5배 바로 안 위로(0.15 → 0.74 = 4.93배) = 그대로", (sp.jump.ok.get(K), sp.guarded))
gt(sp, T0 + 4200, "0.15")
chk(sp.dex_price("base", CA) == 0.15 and ok_px(sp) == 0.15 and not sp.guarded, "J4 5배 바로 안 아래로(0.74 → 0.15 = 4.93배) = 그대로", (sp.jump.ok.get(K), sp.guarded))
gt(sp, T0 + 4300, "0.76")
chk(sp.dex_price("base", CA) == 0.0 and sp.guarded.get(K, "").startswith("시세 급변") and ok_px(sp) == 0.15,
    "J4b 5배 바로 밖 위로(0.15 → 0.76 = 5.07배) = 0", sp.guarded.get(K))
gt(sp, T0 + 4400, "0.0295")
chk(sp.dex_price("base", CA) == 0.0 and sp.guarded.get(K, "").startswith("시세 급변"), "J4b 5배 바로 밖 아래로(0.15 → 0.0295 = 5.08배) = 0", sp.guarded.get(K))
gt(sp, T0 + 4500, "0.0301")
chk(sp.dex_price("base", CA) == 0.0301 and ok_px(sp) == 0.0301 and K not in sp.guarded and K not in sp.jump.wait,
    "J4b 다시 5배 바로 안(0.15 → 0.0301 = 4.98배) = 그대로 · 가드 풀림", (sp.jump.ok.get(K), sp.guarded.get(K)))

sp = mk()
T5 = T0 + 6000
gt(sp, T5, "0.15")
seen = []
for dt in (600, 1800, 3000, 600 + 3600):
    gt(sp, T5 + dt, "1.0")
    seen.append(sp.dex_price("base", CA))
chk(seen == [0.0, 0.0, 0.0, 1.0] and ok_px(sp) == 1.0 and K not in sp.guarded and K not in sp.jump.wait,
    "J5 0.15 → 1.0 이 1시간 넘게 이어짐 = 그 전 0 · 그 뒤 인정(확인된 값 1.0 · 가드 풀림)", (seen, sp.jump.ok.get(K), sp.guarded.get(K)))

sp = mk()
T5b = T5 + 5000
gt(sp, T5b, "0.1507")
for dt in (600, 1800, 3000):
    gt(sp, T5b + dt, "0.01")
gt(sp, T5b + 4200, "16.15")
v = sp.dex_price("base", CA)
chk(v == 0.0 and ok_px(sp) == 0.1507 and (sp.jump.wait.get(K) or [None, None]) == [16.15, float(T5b + 4200)],
    "J5b 급락 대기 1시간 뒤 처음 온 $16.15 = 0 · 확인된 값 그대로 · 급변 다시 셈", (v, sp.jump.ok.get(K), sp.jump.wait.get(K)))
gt(sp, T5b + 4800, "1.30")
chk(sp.dex_price("base", CA) == 0.0 and (sp.jump.wait.get(K) or [None])[0] == 1.30, "J5b 다른 얇은 풀 값($1.30 · 급변 값과 12배) = 또 새 급변", sp.jump.wait.get(K))

T6 = T5b + 10000
sp = mk()
gt(sp, T6, "16.15")
chk(sp.dex_price("base", CA) == 16.15 and not sp.guarded, "J6 확인된 값 없음(처음 받는 값) = 종전 그대로(유동성 가드만)", sp.guarded)

sp = mk()
gt(sp, T6 + 100, "0.1507")
gt(sp, T6 + 700, "16.15", res="165.92")
v = sp.dex_price("base", CA)
chk(v == 0.0 and sp.guarded.get(K, "").startswith("풀 유동성") and ok_px(sp) == 0.1507 and K not in sp.jump.wait,
    "J7 얇은 풀 응답(유동성 $165.92) = 종전 '풀 유동성' 가드 · 확인된 값·급변 기록 안 건드림", (v, sp.guarded.get(K), sp.jump.ok.get(K), sp.jump.wait.get(K)))

sp = mk()
T7 = T6 + 1000
gt(sp, T7, "0.1507")
gt(sp, T7 + 600, "16.15")
gt(sp, T7 + 1200, "0.1507", res="165")
chk(K not in sp.jump.wait, "J7b 유동성 미달 응답 = 급변 대기 끊김", sp.jump.wait.get(K))
gt(sp, T7 + 12000, "16.15")
chk(sp.dex_price("base", CA) == 0.0 and ok_px(sp) == 0.1507 and (sp.jump.wait.get(K) or [None, None])[1] == float(T7 + 12000),
    "J7b 3시간 뒤 같은 급변 = 0 · 대기 새로 셈(바로 인정 아님)", (sp.jump.ok.get(K), sp.jump.wait.get(K)))

sp = mk()
T7c = T7 + 13000
gt(sp, T7c, "0.1507")
gt(sp, T7c + 600, "16.15")
CLK.now = T7c + 1200
RESP["px"], RESP["res"] = {}, {CA: "165"}
sp._gt_next_at = sp._gt_backoff_until = 0
run(sp._gt_round, CLK.t())
chk(sp.dex_res.get(K) == 165.0 and K not in sp.jump.wait, "J7c 가격 빠지고 유동성 $165 만 온 응답 = 급변 대기 끊김", sp.jump.wait.get(K))
gt(sp, T7c + 12000, "16.15")
chk(sp.dex_price("base", CA) == 0.0 and ok_px(sp) == 0.1507, "J7c 3시간 뒤 같은 급변 = 0(바로 인정 아님)", (sp.jump.ok.get(K), sp.jump.wait.get(K)))

sp = mk()
T7d = T7c + 13000
gt(sp, T7d, "0.1507")
gt(sp, T7d + 600, "16.15")
gt(sp, T7d + 3500, "16.15")
gt(sp, T7d + 3590, "0.1507", res="165")
chk(K not in view_spot.Spot().jump.wait, "J7d 유동성 미달로 끊긴 대기가 90초 뒤 재시작해도 파일에 안 남음", json.load(open(JF)).get("wait"))
sp2 = view_spot.Spot()
sp2.token_pairs = {("base", CA)}
sp2.dex_usd, sp2.dex_ts, sp2.dex_res, sp2.dex_res_ts, sp2.dex_src = {}, {}, {}, {}, {}
sp2._res_gecko_ts, sp2._gt_polled = {}, {}
sp2.guarded, sp2._guard_logged, sp2.dex_alt = {}, {}, {}
gt(sp2, T7d + 3700, "16.15")
chk(sp2.dex_price("base", CA) == 0.0 and (sp2.jump.ok.get(K) or [None])[0] == 0.1507, "J7d 재시작 뒤 같은 급변 = 0(옛 대기 시간으로 바로 인정 아님)",
    (sp2.jump.ok.get(K), sp2.jump.wait.get(K)))

sp = mk()
T8 = T7d + 20000
gt(sp, T8, "0.1507")
sp.token_prio = {("base", CA): 100.0}
sp._ds_polled = {}
sp._ds_backoff_until = 0
RESP["ds"] = [{"chainId": "base", "baseToken": {"address": CA, "symbol": "RVX"}, "quoteToken": {"address": "0x" + "cc" * 20},
               "priceUsd": "16.15", "liquidity": {"usd": 80000}}]
CLK.now = T8 + 1800
run(sp._ds_round, CLK.t())
v = sp.dex_price("base", CA)
chk(sp.dex_src.get(K) == "dexscreener" and v == 0.0 and sp.guarded.get(K, "").startswith("시세 급변"),
    "J8 덱스스크리너 폴백 $16.15(유동성 $80k) = 같은 규칙으로 0", (sp.dex_src.get(K), v, sp.guarded.get(K)))

sp2 = view_spot.Spot()
chk(sp2.jump.ok.get(K) == [0.1507, float(T8)] and sp2.jump.wait.get(K) == [16.15, float(T8 + 1800)],
    "J9 dex_jump.json 저장 → 새 Spot(재시작)이 확인된 값·급변 대기 복원", (sp2.jump.ok.get(K), sp2.jump.wait.get(K)))
sp2.dex_usd, sp2.dex_ts, sp2.dex_src = dict(sp.dex_usd), dict(sp.dex_ts), dict(sp.dex_src)
sp2.dex_res, sp2.dex_res_ts = dict(sp.dex_res), dict(sp.dex_res_ts)
sp2.guarded, sp2._guard_logged = {}, {}
v = sp2.dex_price("base", CA)
chk(v == 0.0 and sp2.guarded.get(K, "").startswith("시세 급변"), "J9 재시작 뒤 첫 평가도 급변 가드(기준 기억)", (v, sp2.guarded.get(K)))
d9 = json.load(open(JF))
d9["ok"].update({"base:0xbad": ["x", 1], "base:0xbad2": [1.0], "base:0xbad3": [True, 1], "base:0xbad4": [float("nan"), 1]})
json.dump(d9, open(JF, "w"))
chk(set(view_spot.Spot().jump.ok) == {K}, "J9 손상·옛 모양 칸 버림", None)
T9 = T8 + 1900
CLK.now = T9
sp._fx_at = sp._mk_at = sp._ds_at = T9
sp._gt_backoff_until = T9 + 600
run(sp.tick)
keys9 = set(json.load(open(paths.state("spot.json"))))
chk(not keys9 & {"ok", "wait", "dex_ok", "dex_jump"} and {"dex_usd", "dex_res", "guarded"} <= keys9, "J9 spot.json 모양 무변(급변 상태는 따로)", sorted(keys9))
os.remove(paths.state("spot.json"))

sp = mk()
T10 = T9 + 1000
sp.jump.ok = {K: [0.15, T10 - 7 * 3600]}
gt(sp, T10, "16.15")
chk(sp.dex_price("base", CA) == 16.15 and ok_px(sp) == 16.15, "J10 확인된 값이 6시간 넘게 묵음 = 기준 없음(종전 그대로)", sp.jump.ok.get(K))

sp = mk()
T11 = T10 + 1000
gt(sp, T11, "0.15")
CLK.now = T11 + 600
sp.dex_res_ts[K] = sp._res_gecko_ts[K] = int(T11 - 7 * 3600)
sp.dex_usd[K], sp.dex_ts[K], sp.dex_src[K] = 1.0, int(CLK.t()), "gecko"
sp._alt_note(K, "okx", 1.02, CLK.t())
v = sp.dex_price("base", CA)
chk(sp.dex_reserve("base", CA) is None and v == 1.0 and not str(sp.guarded.get(K, "")).startswith("시세 급변"),
    "J11 유동성 모름 + OKX 교차확인 통과(K7) = 종전 그대로 1.0(확인된 값 0.15 와 5배 넘어도 급변 가드 안 함)", (v, sp.guarded.get(K)))

T.finish()
