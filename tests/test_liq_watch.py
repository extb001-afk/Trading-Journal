#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as H

import copy
import json
import os
import time
import urllib.parse

for k in ("TJ_TG_TOKEN", "TJ_TG_CHAT"):
    os.environ.pop(k, None)
S = os.path.join(H.TMP, "state")
CFG = os.path.join(H.TMP, "config.json")
import common
import alert_prefs as AP


def check(name, ok, detail=""):
    H.chk(bool(ok), name, None if ok else str(detail)[:600])


try:
    import liq_watch as LW
except ImportError as e:
    check("G0 청산 빠른 감시 모듈(liq_watch) 있음", False, e)
    H.finish()
import alert_watch as AW


def wcfg(d):
    common.atomic_write_json(CFG, d)
    time.sleep(0.01)


def wprefs(doc):
    common.atomic_write_json(os.path.join(S, "ui_prefs.json"), {AP.PREF_KEY: doc})
    time.sleep(0.01)


wcfg({})
wprefs(AP.preset_doc("rec"))


class World:
    def __init__(self):
        self.pos = {"binance": [], "bybit": [], "okx": []}
        self.mark = {}
        self.hl = {}
        self.err = {}
        self.okx_loans = []
        self.bn_loans = []
        self.bn_coll = {}
        self.bn_margin = None
        self.bn_coeff = {"normalBar": "1.5", "marginCallBar": "1.3", "forceLiquidationBar": "1.1"}
        self.bn_iso = []
        self.spot = {}
        self.hdr = {}
        self.calls = []


W = World()
T = [1_800_000_000.0]


def router(method, url, headers=None, body=None, timeout=6.0):
    u = urllib.parse.urlsplit(url)
    host, path, qs = u.hostname, u.path, dict(urllib.parse.parse_qsl(u.query))
    W.calls.append((T[0], method, host, path, qs))
    for frag, exc in W.err.items():
        if frag in path or frag == host:
            raise exc() if callable(exc) else exc
    hd = {}
    if host in W.hdr:
        hd["x-mbx-used-weight-1m"] = str(W.hdr[host])
    if host == "fapi.binance.com":
        if path == "/fapi/v3/positionRisk":
            return 200, hd, [{"symbol": p["sym"], "positionSide": "BOTH", "positionAmt": str(p["amt"]), "entryPrice": "1",
                              "markPrice": str(W.mark.get(("binance", p["sym"]), 0)), "liquidationPrice": str(p["liq"])} for p in W.pos["binance"]]
        if path == "/fapi/v1/premiumIndex":
            s = qs.get("symbol")
            return 200, hd, {"symbol": s, "markPrice": str(W.mark.get(("binance", s), 0))}
    if host == "api.bybit.com":
        if path == "/v5/position/list":
            return 200, hd, {"retCode": 0, "result": {"list": [{"symbol": p["sym"], "side": "Buy" if p["amt"] > 0 else "Sell", "size": str(abs(p["amt"])),
                                                              "markPrice": str(W.mark.get(("bybit", p["sym"]), 0)), "liqPrice": str(p["liq"]), "leverage": "5"}
                                                             for p in W.pos["bybit"]], "nextPageCursor": ""}}
        if path == "/v5/market/tickers":
            s = qs.get("symbol")
            if qs.get("category") == "spot":
                return 200, hd, {"retCode": 0, "result": {"list": [{"symbol": s, "lastPrice": str(W.spot.get(("bybit", s[:-4]), 0))}]}}
            return 200, hd, {"retCode": 0, "result": {"list": [{"symbol": s, "markPrice": str(W.mark.get(("bybit", s), 0))}]}}
    if host == "www.okx.com":
        if path == "/api/v5/account/positions":
            return 200, hd, {"code": "0", "data": [{"instId": p["sym"], "instType": "SWAP", "posSide": "net", "pos": str(p["amt"]),
                                                     "markPx": str(W.mark.get(("okx", p["sym"]), 0)), "liqPx": str(p["liq"]), "lever": "3"}
                                                    for p in W.pos["okx"]]}
        if path == "/api/v5/public/mark-price":
            s = qs.get("instId")
            return 200, hd, {"code": "0", "data": [{"instId": s, "markPx": str(W.mark.get(("okx", s), 0))}]}
        if path == "/api/v5/finance/flexible-loan/loan-info":
            rows = copy.deepcopy(W.okx_loans)
            for r in rows:
                ref = r.pop("_ref", None)
                if ref:
                    r["curLTV"] = str(ref[0] * ref[1] / W.spot[("okx", ref[2])])
            return 200, hd, {"code": "0", "data": rows}
        if path == "/api/v5/market/ticker":
            s = qs.get("instId", "").split("-")[0]
            if ("okx", s) not in W.spot:
                return 200, hd, {"code": "51001", "msg": "Instrument ID does not exist", "data": []}
            return 200, hd, {"code": "0", "data": [{"instId": qs.get("instId"), "last": str(W.spot[("okx", s)])}]}
    if host == "api.hyperliquid.xyz" and path == "/info":
        b = body or {}
        aps = [{"position": {"coin": c, "szi": str(szi), "positionValue": str(abs(szi) * mk), "liquidationPx": str(lq), "leverage": {"value": 3}}}
               for c, szi, mk, lq in W.hl.get(b.get("user"), [])]
        return 200, hd, {"assetPositions": aps, "marginSummary": {"accountValue": "1"}}
    if host == "api.binance.com":
        if path == "/sapi/v1/margin/account":
            if not W.bn_margin:
                return 200, hd, {"marginLevel": "999", "userAssets": []}
            m = copy.deepcopy(W.bn_margin)
            px = lambda a: 1.0 if a == "USDT" else W.spot[("binance", a)]
            av = sum((float(x["free"]) + float(x["locked"])) * px(x["asset"]) for x in m["userAssets"])
            lv = sum((float(x["borrowed"]) + float(x["interest"])) * px(x["asset"]) for x in m["userAssets"])
            m["marginLevel"] = str(av / lv if lv else 999)
            return 200, hd, m
        if path == "/sapi/v1/margin/tradeCoeff":
            return 200, hd, dict(W.bn_coeff)
        if path == "/sapi/v1/margin/isolated/account":
            return 200, hd, {"assets": copy.deepcopy(W.bn_iso)}
        if path == "/sapi/v2/loan/flexible/ongoing/orders":
            rows = copy.deepcopy(W.bn_loans)
            for r in rows:
                r["currentLTV"] = str(float(r["totalDebt"]) / (float(r["collateralAmount"]) * W.spot[("binance", r["collateralCoin"])]))
            return 200, hd, {"rows": rows, "total": len(rows)}
        if path == "/sapi/v2/loan/flexible/collateral/data":
            c = qs.get("collateralCoin")
            return 200, hd, {"rows": [dict(W.bn_coll[c], collateralCoin=c)] if c in W.bn_coll else [], "total": 1}
        if path == "/api/v3/ticker/price":
            want = json.loads(qs["symbols"]) if "symbols" in qs else None
            rows = [{"symbol": s + "USDT", "price": str(p)} for (ex, s), p in W.spot.items() if ex == "binance"]
            if want is not None:
                if any(w[:-4] not in {s for (ex, s) in W.spot if ex == "binance"} for w in want):
                    raise LW.HttpErr(400, '{"code":-1121,"msg":"Invalid symbol."}')
                rows = [r for r in rows if r["symbol"] in want]
            return 200, hd, rows
    raise LW.HttpErr(404, "not found")


LW.HTTP = router
ENV = {"TJ_TG_TOKEN": "000:fake", "TJ_TG_CHAT": "1", "TJ_BINANCE_KEY": "k" * 16, "TJ_BINANCE_SECRET": "s" * 16}
RL = {}


def mk(env=None):
    return LW.Watcher(env_fn=lambda: (env if env is not None else ENV), rl_map=RL, clock=lambda: T[0], sync=True)


def run(w, sec, step=0.5):
    out = []
    end = T[0] + sec
    while T[0] < end - 1e-9:
        T[0] += step
        out += w.step(T[0])
    return out


def calls(host=None, path=None, since=None):
    return [c for c in W.calls if (host is None or c[2] == host) and (path is None or c[3] == path) and (since is None or c[0] > since)]


def qlines():
    p = os.path.join(S, AP.FAST_QUEUE)
    if not os.path.exists(p):
        return []
    return [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]


w = mk(dict(ENV, TJ_TG_TOKEN=""))
run(w, 10)
check("G1 텔레그램 미연결 → 외부 조회 0", not W.calls and w.gate == (False, "텔레그램 미연결"), (len(W.calls), w.gate))
wcfg({"alerts": {"liq_fast": False}})
w = mk()
run(w, 10)
check("G2 config alerts.liq_fast=false → 외부 조회 0", not W.calls, len(W.calls))
wcfg({})
d0 = AP.preset_doc("rec")
d0["cats"]["liq"] = "off"
wprefs(d0)
run(w, 10)
check("G3 설정 '청산 근접' 끔 → 외부 조회 0", not W.calls, len(W.calls))
wprefs(AP.preset_doc("rec"))
run(w, 1)
check("G4 다시 켜면 다음 판에 바로 시작(계정 조회)", len(calls("fapi.binance.com", "/fapi/v3/positionRisk")) == 1, len(W.calls))

t0 = T[0]
run(w, 60)
pr = calls("fapi.binance.com", "/fapi/v3/positionRisk", t0)
mk_ = calls("fapi.binance.com", "/fapi/v1/premiumIndex", t0)
check("D1 포지션 없음 = 계정 조회 5초마다(60초 12번) · 마크가격 0", len(pr) == 12 and not mk_, (len(pr), len(mk_)))
W.pos["binance"] = [{"sym": "BTCUSDT", "amt": 1.0, "liq": 50000.0}]
W.mark[("binance", "BTCUSDT")] = 65000.0
t_open = T[0] + 0.2
lines = run(w, 6)
s9 = w.v.get("binance") or {}
seen_at = s9.get("pos_ts")
check("D2 새 포지션 0→1 발견 ≤5초(계정 조회)", s9.get("pos") and seen_at is not None and seen_at - t_open <= 5.0, (seen_at and seen_at - t_open))
t1 = T[0]
run(w, 60)
mk_ = calls("fapi.binance.com", "/fapi/v1/premiumIndex", t1)
pr = calls("fapi.binance.com", "/fapi/v3/positionRisk", t1)
check("D3 열린 포지션(거리 23% > 기준×2) = 마크가격 5초(60초 12번) · 포지션 30초(2번)", len(mk_) == 12 and len(pr) == 2, (len(mk_), len(pr)))
W.mark[("binance", "BTCUSDT")] = 58000.0
t2 = T[0]
run(w, 30)
mk_ = calls("fapi.binance.com", "/fapi/v1/premiumIndex", t2)
check("D4 기준×2 안(13.8%) = 마크가격 2초(30초 ≈15번)", 14 <= len(mk_) <= 16, len(mk_))

nq0 = len(qlines())
tA = T[0]
W.mark[("binance", "BTCUSDT")] = 54500.0
pr0 = len(calls("fapi.binance.com", "/fapi/v3/positionRisk"))
got = run(w, 4)
liq1 = [x for x in got if x["kind"] == "LIQ_NEAR"]
t_alert = liq1[0]["ts"] if liq1 else None
check("A1 기준 진입(8.3% ≤ 10%) → 2초 안 🔴 1통(소리) · 문장 = 무슨 일/할 일/숫자",
      len(liq1) == 1 and t_alert - tA <= 2.5 and liq1[0]["text"].startswith("🔴 BTCUSDT 롱 선물 청산가까지 8.3% 남았어요\n증거금을"),
      [(x["ts"] - tA, x["text"][:40]) for x in got])
check("A1 긴급 줄 = alerts_fast.jsonl(긴급 종류 · 청산 근접 카테고리) 1줄", len(qlines()) == nq0 + 1 and qlines()[-1]["kind"] in AP.FAST_KINDS
      and AP.cat_of(qlines()[-1]["kind"]) == "liq", qlines()[-1:])
check("A2 기준 진입 → 포지션(청산가) 즉시 1회", len(calls("fapi.binance.com", "/fapi/v3/positionRisk")) - pr0 >= 1)
got = run(w, 20)
check("A3 같은 위험 그대로 = 다시 0통", not got, got)
W.mark[("binance", "BTCUSDT")] = 52000.0
got = run(w, 4)
check("A4 거리 절반 이하(3.8%) → 1번 더(🔴)", len(got) == 1 and "더 가까워졌어요" in got[0]["text"], [x["text"][:40] for x in got])
W.mark[("binance", "BTCUSDT")] = 50500.0
got = run(w, 10)
check("A5 그 뒤 더 가까워져도 0통('1번 더'까지만)", not got, [x["text"][:40] for x in got])
W.mark[("binance", "BTCUSDT")] = 64000.0
got = run(w, 4)
check("A6 기준의 1.5배 밖(21.9%) → ✅ 1통(무음 · 할 일 없음)", len(got) == 1 and got[0]["text"].startswith("✅ BTCUSDT 롱 청산 위험에서 벗어났어요") and got[0].get("resolved"),
      [x["text"][:40] for x in got])
pr0 = len(calls("fapi.binance.com", "/fapi/v3/positionRisk"))
W.mark[("binance", "BTCUSDT")] = 66000.0
run(w, 6)
check("A7 시세 크게 움직임(≥2%) → 포지션 즉시 1회(30초 기다리지 않음)", len(calls("fapi.binance.com", "/fapi/v3/positionRisk")) - pr0 >= 1)

W.mark[("binance", "BTCUSDT")] = 54500.0
got = run(w, 6)
check("E0 (준비) 다시 기준 진입 → 🔴 1통", len(got) == 1 and got[0]["text"].startswith("🔴"), [x["text"][:30] for x in got])
W.err["/fapi/v3/positionRisk"] = LW.HttpErr(401, '{"code":-2015,"msg":"Invalid API-key, IP, or permissions for action."}')
W.pos["binance"] = []
got = run(w, 40)
s9 = w.v["binance"]
check("E1 권한 오류 = 포지션 없음 아님 — 들고 감시 · 닫힘/해소 ✅ 없음", s9.get("pos") and s9.get("ekind") == "perm" and not got, (s9.get("ekind"), [x["text"][:30] for x in got]))
j9 = w.jobs["acct:binance"]
e1t = [c[0] for c in calls("fapi.binance.com", "/fapi/v3/positionRisk", T[0] - 40)]
check("E2 권한 오류 = 6시간 쉼(첫 401 뒤 계정 조회 0)", j9["until"] - T[0] > 5 * 3600 and len(e1t) == 1, (j9["until"] - T[0], len(e1t)))
W.mark[("binance", "BTCUSDT")] = 70000.0
got = run(w, 10)
check("E3 포지션이 낡은 동안(90초 넘음)엔 시세가 멀어져도 해소 ✅ 안 함", not got, [x["text"][:30] for x in got])
del W.err["/fapi/v3/positionRisk"]
ENV["TJ_BINANCE_KEY"] = "n" * 16
run(w, 2)
check("E4 키가 바뀌면 권한 쉼을 풀고 바로 다시 조회", len(calls("fapi.binance.com", "/fapi/v3/positionRisk", T[0] - 2)) >= 1)
W.pos["binance"] = [{"sym": "BTCUSDT", "amt": 1.0, "liq": 50000.0}]
W.mark[("binance", "BTCUSDT")] = 54500.0
run(w, 6)
W.err["/fapi/v3/positionRisk"] = lambda: TimeoutError("timed out")
W.pos["binance"] = []
got = run(w, 40)
s9 = w.v["binance"]
check("E5 타임아웃 = 포지션 없음 아님(들고 감시 · ✅ 없음 · 짧게 다시)", s9.get("pos") and s9.get("ekind") == "net" and not [x for x in got if x["text"].startswith("✅")],
      (s9.get("ekind"), [x["text"][:30] for x in got]))
W.err["/fapi/v1/premiumIndex"] = lambda: TimeoutError("timed out")
W.err.pop("/fapi/v3/positionRisk")
W.pos["binance"] = [{"sym": "BTCUSDT", "amt": 1.0, "liq": 50000.0}]
run(w, 35)
W.mark[("binance", "BTCUSDT")] = 80000.0
got = run(w, 8)
check("E6 마크가격이 낡으면(15초 넘음) 해소 판정 안 함", not [x for x in got if x["text"].startswith("✅")], [x["text"][:30] for x in got])
del W.err["/fapi/v1/premiumIndex"]
got = run(w, 12)
check("E7 마크가격 다시 신선 → ✅ 1통", len([x for x in got if x["text"].startswith("✅")]) == 1, [x["text"][:30] for x in got])

W.mark[("binance", "BTCUSDT")] = 54500.0
got = run(w, 4)
W.pos["binance"] = []
got = run(w, 35)
cl = [x for x in got if "포지션이 닫혀" in x["text"]]
check("C1 새로 읽은 목록에 없음 = 닫힘 → ✅ 1통 · 그 뒤 마크가격 조회 0", len(cl) == 1 and cl[0]["text"].startswith("✅")
      and not calls("fapi.binance.com", "/fapi/v1/premiumIndex", cl[0]["ts"]), [x["text"][:30] for x in got])

W.pos["binance"] = [{"sym": "ETHUSDT", "amt": -2.0, "liq": 3300.0}]
W.mark[("binance", "ETHUSDT")] = 3050.0
got = run(w, 8)
check("R0 (준비) 숏 기준 진입 1통", len(got) == 1 and "ETHUSDT 숏" in got[0]["text"], [x["text"][:30] for x in got])
w.save(T[0], force=True)
w2 = mk()
got = run(w2, 12)
check("R1 재시작(기억 파일) → 같은 단계 다시 0통", not got, [x["text"][:30] for x in got])
os.remove(os.path.join(S, LW.STATE_NAME))
w3 = mk()
got = run(w3, 12)
check("R2 기억 파일이 없어도(저장 전 죽음) 긴급 줄 기록으로 맞춰 다시 0통", not got, [x["text"][:30] for x in got])
W.mark[("binance", "ETHUSDT")] = 3200.0
got = run(w3, 4)
check("R3 되살린 기억으로 '1번 더' 규칙 이어감", len(got) == 1 and "더 가까워졌어요" in got[0]["text"], [x["text"][:30] for x in got])
w = w3
W.pos["binance"] = []
run(w, 40)

W.pos["binance"] = [{"sym": f"S{i}USDT", "amt": 1.0, "liq": 90.0} for i in range(8)]
for i in range(8):
    W.mark[("binance", f"S{i}USDT")] = 99.0
tB = T[0]
run(w, 60)
fw = sum(1 if c[3] == "/fapi/v1/premiumIndex" else 5 for c in calls("fapi.binance.com", since=tB))
check("B1 바이낸스 선물 무게(이 스레드) ≤ 360/분(IP 2,400 의 15%)", fw <= 360, fw)
W.hdr["fapi.binance.com"] = 2000
run(w, 3)
W.hdr.pop("fapi.binance.com")
n_after = len(calls("fapi.binance.com", since=T[0]))
tH = T[0]
nxt_min = (int(tH // 60) + 1) * 60
run(w, max(0.5, nxt_min - tH - 1.5))
check("B2 바이낸스 IP 사용량 헤더 ≥80% → 그 분 끝까지 선물 조회 0", not calls("fapi.binance.com", since=tH), len(calls("fapi.binance.com", since=tH)))
run(w, 5)
check("B2 다음 분엔 다시", len(calls("fapi.binance.com", since=nxt_min)) >= 1)
RL["fapi.binance.com"] = T[0] + 30
tR = T[0]
run(w, 20)
check("B3 tj-exf 와 공유하는 429 백오프 지도에 걸린 호스트 = 조회 0", not calls("fapi.binance.com", since=tR))
W.err["fapi.binance.com"] = LW.HttpErr(429, "", {"retry-after": "40"})
RL.pop("fapi.binance.com")
run(w, 2)
W.err.pop("fapi.binance.com")
check("B4 429 → 공유 지도에 Retry-After 기록(이력 수집도 같이 쉼)", RL.get("fapi.binance.com", 0) - T[0] > 30, RL)
RL.pop("fapi.binance.com")
W.pos["binance"] = []
run(w, 40)

ADDR = "0x" + "ab" * 20
wcfg({"perp_wallets": [{"dex": "hyperliquid", "address": ADDR, "label": "t"}]})
import perp_dex
ADDR = perp_dex.configured(common.read_json(CFG, {}))["hyperliquid"][0]["address"]
tH = T[0]
run(w, 30)
hc = [c for c in calls("api.hyperliquid.xyz", since=tH)]
check("H1 포지션 없는 주소 = 5초(30초 6번) · 무게 2", 5 <= len(hc) <= 7, len(hc))
W.hl[ADDR] = [("ETH", 1.0, 2500.0, 2300.0)]
got = run(w, 8)
check("H2 주소 포지션 발견 + 기준 진입 → 🔴 1통", len(got) == 1 and got[0]["text"].startswith("🔴 ETH 롱"), [x["text"][:30] for x in got])
tH = T[0]
run(w, 20)
hc = calls("api.hyperliquid.xyz", since=tH)
check("H3 가까운 주소 = 2초(20초 ≈10번)", 9 <= len(hc) <= 11, len(hc))
W.hl[ADDR] = []
got = run(w, 6)
check("H4 닫힘 → ✅ 1통", len([x for x in got if "포지션이 닫혀" in x["text"]]) == 1, [x["text"][:30] for x in got])
wcfg({})

ENV.update({"TJ_OKX_KEY": "o" * 16, "TJ_OKX_SECRET": "p" * 16, "TJ_OKX_PASSPHRASE": "q" * 8})
W.okx_loans = [{"ordId": "1", "collateralData": [{"ccy": "ETH", "amt": "10"}], "loanData": [{"ccy": "USDT", "amt": "10000"}],
                "curLTV": "0.5", "marginCallLTV": "0.8", "liqLTV": "0.9", "riskWarningData": {"instId": "ETH-USDT", "liqPx": "1111"},
                "_ref": (0.5, 2000.0, "ETH")}]
W.spot[("okx", "ETH")] = 2000.0
tL = T[0]
got = run(w, 70)
li = calls("www.okx.com", "/api/v5/finance/flexible-loan/loan-info", tL)
tk = calls("www.okx.com", "/api/v5/market/ticker", tL)
check("L1 대출 정보 60초(70초 2번) · 담보 시세 5초(LTV 50% — 2초 아님)", len(li) == 2 and 13 <= len(tk) <= 17 and not got, (len(li), len(tk), [x["text"][:30] for x in got]))
W.spot[("okx", "ETH")] = 1380.0
li0 = len(calls("www.okx.com", "/api/v5/finance/flexible-loan/loan-info"))
got = run(w, 3)
check("L2 담보 시세로 추정한 LTV 가 마진콜의 90% → 3초 안 🔴 1통 + '청산까지 ETH 가치가 N% 더 떨어지면'",
      len(got) == 1 and got[0]["kind"] == "LOAN_RISK" and "마진콜 문턱의 90%" in got[0]["text"] and "ETH 가치가" in got[0]["text"]
      and "시세로 추정" in got[0]["text"], [x["text"] for x in got])
check("L2 단계가 오르면 대출 정보 즉시 확인 1회", len(calls("www.okx.com", "/api/v5/finance/flexible-loan/loan-info")) - li0 >= 1)
tk0 = len(calls("www.okx.com", "/api/v5/market/ticker"))
run(w, 10)
check("L3 마진콜의 80% 위 = 담보 시세 2초(10초 ≈5번)", 4 <= len(calls("www.okx.com", "/api/v5/market/ticker")) - tk0 <= 6, len(calls("www.okx.com", "/api/v5/market/ticker")) - tk0)
W.spot[("okx", "ETH")] = 1240.0
got = run(w, 3)
check("L4 마진콜 도달 → 🔴 긴급 1통", len(got) == 1 and "마진콜에 닿았어요(긴급)" in got[0]["text"], [x["text"][:60] for x in got])
W.spot[("okx", "ETH")] = 1150.0
got = run(w, 3)
check("L5 청산 직전(마진콜과 청산의 가운데) → 🔴 1통 · 그 뒤 같은 단계 0", len(got) == 1 and "청산 직전" in got[0]["text"] and not run(w, 10), [x["text"][:60] for x in got])
W.err["/api/v5/market/ticker"] = lambda: TimeoutError("timed out")
W.spot[("okx", "ETH")] = 3000.0
got = run(w, 8)
check("L6 담보 시세 조회 실패 중 = 낡은 추정으로 해소 안 함", not [x for x in got if x["text"].startswith("✅")], [x["text"][:40] for x in got])
del W.err["/api/v5/market/ticker"]
got = run(w, 30)
check("L6 신선한 시세로 1단계 문턱의 95% 아래여도 60초 이어져야 ✅(깜빡임 거름) — 30초엔 아직 0", not got, [x["text"][:40] for x in got])
got = run(w, 130)
rs = [x for x in got if x["text"].startswith("✅")]
check("L6 60초 넘게 이어짐 → ✅ 1통(무음)", len(rs) == 1 and rs[0]["kind"] == "LOAN_RISK", [x["text"][:40] for x in got])
W.okx_loans = []
got = run(w, 70)
check("L7 대출이 없어짐(갚음) → 기억만 정리(이미 ✅ 뒤라 알림 0)", not got and not w.st["risk"], (w.st["risk"], [x["text"][:30] for x in got]))
W.bn_loans = [{"loanCoin": "USDT", "totalDebt": "5000", "collateralCoin": "BNB", "collateralAmount": "20"}]
W.bn_coll = {"BNB": {"initialLTV": "0.65", "marginCallLTV": "0.75", "liquidationLTV": "0.83"}}
W.spot[("binance", "BNB")] = 400.0
tBL = T[0]
got = run(w, 65)
cd = calls("api.binance.com", "/sapi/v2/loan/flexible/collateral/data", tBL)
check("L8 바이낸스 Flexible — 임계 = 담보 코인 자료(collateral/data · 6시간 보관) · LTV 62.5% = 알림 0", len(cd) == 1 and not got
      and (w.risk.get("bn_loan") or {}).get("recs"), (len(cd), [x["text"][:30] for x in got]))
W.spot[("binance", "BNB")] = 368.0
got = run(w, 6)
check("L9 바이낸스 Flexible 90% 문턱 → 🔴 1통", len(got) == 1 and "바이낸스 담보대출" in got[0]["text"], [x["text"][:60] for x in got])
W.bn_loans = []
got = run(w, 65)
check("L10 대출 정리 → ✅ '빚이 없어져 감시를 끝내요' 1통", len(got) == 1 and got[0]["text"].startswith("✅") and "빚이 없어져" in got[0]["text"], [x["text"][:40] for x in got])

W.bn_margin = {"accountType": "MARGIN_1", "marginLevel": "1.6", "totalLiabilityOfBtc": "0.1", "userAssets": [
    {"asset": "BTC", "free": "1", "locked": "0", "borrowed": "0", "interest": "0", "netAsset": "1"},
    {"asset": "USDT", "free": "0", "locked": "0", "borrowed": "37500", "interest": "0", "netAsset": "-37500"}]}
W.spot[("binance", "BTC")] = 60000.0
got = run(w, 65)
check("M1 교차 마진 1.6(마진콜 1.3 · 청산 1.1) = 알림 0 · 기록 있음(lev id binance:margin_cross:account:-)",
      not got and "binance:margin_cross:account:-" in ((w.risk.get("bn_margin") or {}).get("recs") or {}), [x["text"][:30] for x in got])
W.spot[("binance", "BTC")] = 52000.0
got = run(w, 6)
check("M2 마진 레벨 하락(추정 1.39) → 🔴 1통(마진 레벨이 마진콜 문턱의 90%)", len(got) == 1 and got[0]["kind"] == "MARGIN_RISK" and "마진 레벨이" in got[0]["text"]
      and "마진콜 1.30" in got[0]["text"], [x["text"] for x in got])
W.bn_iso = [{"symbol": "ETHUSDT", "marginLevel": "1.15", "marginLevelStatus": "MARGIN_CALL", "liquidatePrice": "1900", "indexPrice": "2000",
             "baseAsset": {"asset": "ETH", "borrowed": "0", "interest": "0"}, "quoteAsset": {"asset": "USDT", "borrowed": "1000", "interest": "1"}}]
got = run(w, 65)
iso = [x for x in got if "격리" in x["text"]]
check("M3 격리 마진 상태 MARGIN_CALL → 🔴 1통(청산가까지 5.0%)", len(iso) == 1 and "5.0%" in iso[0]["text"], [x["text"][:60] for x in got])
W.bn_iso[0]["marginLevelStatus"] = "NORMAL"
got = run(w, 125)
check("M4 격리 마진 NORMAL(60초 이어짐) → ✅ 1통", len([x for x in got if x["text"].startswith("✅") and "격리" in x["text"]]) == 1, [x["text"][:40] for x in got])
W.bn_margin = None
W.bn_iso = []
run(w, 65)

_CH = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _bech(hrp, data):
    def pm(vals):
        g, c = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3], 1
        for v in vals:
            b = c >> 25
            c = ((c & 0x1ffffff) << 5) ^ v
            for i in range(5):
                c ^= g[i] if ((b >> i) & 1) else 0
        return c
    hx = [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]
    m = pm(hx + data + [0] * 6) ^ 1
    return hrp + "1" + "".join(_CH[d] for d in data + [(m >> 5 * (5 - i)) & 31 for i in range(6)])


DY = _bech("dydx", [(i * 7) % 32 for i in range(32)])
try:
    DYN = perp_dex.validate_address("dydx", DY)[0]
except ValueError:
    DYN = None
if DYN:
    wcfg({"perp_wallets": [{"dex": "dydx", "address": DYN, "label": "d"}]})
    common.atomic_write_json(os.path.join(S, "futures_dydx.json"), {"ts": int(T[0]), "positions": [
        {"symbol": "BTC-USD", "side": "LONG", "qty": 1, "mark": 60000.0, "liq": 55000.0, "acct": DYN}], "accts": {DYN: {"ts": int(T[0])}}})
    got = run(w, 2)
    check("S1 10분 수집 파일(dYdX) 포지션 8.3% → 🔴 1통", len(got) == 1 and "BTC-USD 롱" in got[0]["text"], [x["text"][:40] for x in got])
    common.atomic_write_json(os.path.join(S, "futures_dydx.json"), {"ts": int(T[0]), "positions": [], "accts": {DYN: {"ts": int(T[0])}}})
    got = run(w, 2)
    k9 = next((k for k in w.st["fut"] if k.startswith("dydx:BTC-USD")), None)
    a9 = (w.st["fut"].get(k9) or {}).get("absent")
    (w.st["fut"].get(k9) or {})["absent"] = int(T[0]) - getattr(LW, "FILE_FORGET", 86400) - 1
    got += run(w, 1)
    check("S2 신선한 파일(주소 ts 기억 뒤·90초 안)에 없음 = 닫힘 ✅ 1통 · 기억 지움(그 뒤 조용)",
          len(got) == 1 and got[0]["text"].startswith("✅") and "닫혀" in got[0]["text"] and k9 is None, ([x["text"][:40] for x in got], a9, k9))
else:
    check("S0 합성 dYdX 시험 주소가 주소 검증을 통과해야 S 절을 돌림(못 돌리면 실패 — 건너뜀 = 통과 아님)", False, DY)
wcfg({})

LEVP = os.path.join(S, "leverage.json")


def wlev(items, products, ts=None):
    common.atomic_write_json(LEVP, {"v": 1, "ts": int(ts or T[0]), "cycle_sec": 600, "fresh_sec": 1320, "products": products, "items": items})
    time.sleep(0.01)


def gate_loan(ltv, at=None):
    return {"id": "gate:loan:loan:m:1", "ex": "gate", "product": "loan", "scope": "loan", "key": "m:1", "label": "게이트 다중 담보대출",
            "measured_at": int(at or T[0]), "stale": False,
            "metrics": {"ltv": {"v": ltv, "unit": "frac", "risk": "up", "warn": None, "call": 0.8, "liq": 0.9, "thr_src": "doc:시험(합성)", "src": "t"}},
            "debt": [{"ccy": "USDT", "total": 1.0}], "collateral": [{"ccy": "ETH", "qty": 1.0}]}


PR = [{"ex": "gate", "product": "loan", "status": "ok", "checked_at": int(T[0]), "measured_at": int(T[0])},
      {"ex": "kucoin", "product": "futures_linear", "status": "ok", "checked_at": int(T[0]), "measured_at": int(T[0])}]
wlev([gate_loan(0.75)], PR)
got = run(w, 2)
check("V1 lev 파일 게이트 담보대출 LTV 75%(마진콜 80%의 90% 넘음) → 🔴 1통(대출 종류 · lev id 기억)", len(got) == 1 and got[0]["kind"] == "LOAN_RISK"
      and "게이트 다중 담보대출" in got[0]["text"] and "gate:loan:loan:m:1" in w.st["risk"], [x["text"][:50] for x in got])
wlev([gate_loan(0.5, at=T[0] - 2000)], [dict(PR[0], measured_at=int(T[0]) - 2000), PR[1]], ts=T[0] - 2000)
got = run(w, 70)
check("V2 lev 값이 낡으면(fresh_sec 넘음) 낮아져도 ✅ 안 함", not got, [x["text"][:40] for x in got])
wlev([gate_loan(0.5)], [dict(p, measured_at=int(T[0])) for p in PR])
got = run(w, 65)
check("V3 lev 안정 값 한 장(스냅숏 하나)을 65초 다시 읽어도 ✅ 없음(측정 15초 상한 — 105b)", not got, [x["text"][:40] for x in got])
run(w, 535)
wlev([gate_loan(0.5)], [dict(p, measured_at=int(T[0])) for p in PR])
got = run(w, 2)
check("V3 다음 10분 측정도 안정(두 측정 사이 ≤ lev 신선 한도) → ✅ 1통", len(got) == 1 and got[0]["text"].startswith("✅ 게이트 다중 담보대출"), [x["text"][:40] for x in got])
wlev([gate_loan(0.75)], [dict(p, measured_at=int(T[0])) for p in PR])
run(w, 2)
wlev([], [dict(p, measured_at=int(T[0])) for p in PR])
got = run(w, 2)
a9 = (w.st["risk"].get("gate:loan:loan:m:1") or {}).get("absent")
(w.st["risk"].get("gate:loan:loan:m:1") or {})["absent"] = int(T[0]) - getattr(LW, "FILE_FORGET", 86400) - 1
got += run(w, 1)
check("V4 lev 신선 'ok' 목록(기억 뒤 측정)에서 대출이 없어짐 = '빚이 없어져' ✅ 1통(의도 변경 — lev r106 엄격화로 ok = 목록 전체 확인)",
      len(got) == 1 and "빚이 없어져" in got[0]["text"] and "gate:loan:loan:m:1" not in w.st["risk"], ([x["text"][:40] for x in got], a9))
kpos = {"id": "kucoin:futures_linear:position:XBTUSDTM:LONG", "ex": "kucoin", "product": "futures_linear", "scope": "position", "key": "XBTUSDTM:LONG",
        "label": "XBTUSDTM 롱", "measured_at": int(T[0]), "stale": False, "metrics": {},
        "position": {"symbol": "XBTUSDTM", "side": "LONG", "qty": 1, "qty_unit": "contract", "mark": 100.0, "liq": 92.0, "leverage": 5}}
wlev([kpos], [dict(p, measured_at=int(T[0])) for p in PR])
got = run(w, 2)
check("V5 lev 파일 쿠코인 선물 포지션(빠른 감시 밖) 8% → 🔴 1통(선물)", len(got) == 1 and got[0]["kind"] == "LIQ_NEAR" and "XBTUSDTM 롱" in got[0]["text"],
      [x["text"][:40] for x in got])
wlev([], [dict(p, measured_at=int(T[0])) for p in PR])
got = run(w, 2)
k9 = "kucoin:XBTUSDTM:LONG:lev"
a9 = (w.st["fut"].get(k9) or {}).get("absent")
(w.st["fut"].get(k9) or {})["absent"] = int(T[0]) - getattr(LW, "FILE_FORGET", 86400) - 1
got += run(w, 1)
check("V6 lev 신선 'ok' 목록에서 포지션이 없어짐 = 닫힘 ✅ 1통(의도 변경)", len(got) == 1 and "닫혀" in got[0]["text"] and k9 not in w.st["fut"],
      ([x["text"][:40] for x in got], a9))
wlev([gate_loan(0.85)], [dict(PR[0], status="no_permission", measured_at=None), PR[1]])
got = run(w, 2)
check("V7 lev 상품 상태가 ok 아님(권한 없음) = 판정 안 함", not got, [x["text"][:40] for x in got])
bnl = {"id": "binance:loan:loan:USDT-BNB", "ex": "binance", "product": "loan", "scope": "loan", "key": "USDT-BNB", "label": "바이낸스 담보대출 USDT←BNB",
       "measured_at": int(T[0]), "stale": False, "metrics": {"ltv": {"v": 0.79, "unit": "frac", "risk": "up", "call": 0.75, "liq": 0.83, "thr_src": "api"}}}
W.bn_loans = []
wlev([bnl], [{"ex": "binance", "product": "loan", "status": "ok", "measured_at": int(T[0])}])
got = run(w, 65)
check("V8 빠른 조회가 그 출처(바이낸스 대출)를 정상으로 읽는 중 = lev 파일의 같은 상품은 안 씀(대출 없음이 정본)", not got, [x["text"][:40] for x in got])
os.remove(LEVP)
run(w, 2)

fu = {"binance": {"ts": T[0] - 30, "positions": [{"symbol": "XRPUSDT", "side": "LONG", "qty": 1, "mark": 2.0, "liq": 1.84}]}}
web_lines = AW.prod_liq({"futures": fu, "cur": "USD"}, AP.preset_doc("rec"), {}, T[0], None, True)
W.pos["binance"] = [{"sym": "XRPUSDT", "amt": 1.0, "liq": 1.84}]
W.mark[("binance", "XRPUSDT")] = 2.0
got = run(w, 8)
both = [x for x in web_lines if x.get("kind") == "LIQ_NEAR"] + [x for x in got if x["kind"] == "LIQ_NEAR"]
check("W1 같은 순간 웹 1분 감시 + 빠른 감시 → 청산 줄 1통(웹은 판정 안 함)", len(both) == 1 and not web_lines, (len(web_lines), [x["text"][:30] for x in got]))
W.pos["binance"] = []
run(w, 40)

mine = [it for src in ("okx_loan", "bn_loan", "bn_margin") for it in (((w.risk.get(src) or {}).get("recs")) or {}).values()]
W.okx_loans = [{"ordId": "y", "collateralData": [{"ccy": "ETH", "amt": "10"}], "loanData": [{"ccy": "USDT", "amt": "10000"}],
                "marginCallLTV": "0.8", "liqLTV": "0.9", "riskWarningData": {}, "_ref": (0.5, 2000.0, "ETH")}]
W.spot[("okx", "ETH")] = 2000.0
W.bn_margin = {"marginLevel": "2", "userAssets": [{"asset": "BTC", "free": "1", "locked": "0", "borrowed": "0", "interest": "0"},
                                                 {"asset": "USDT", "free": "0", "locked": "0", "borrowed": "1000", "interest": "1"}]}
W.bn_iso = [{"symbol": "ETHUSDT", "marginLevel": "3", "marginLevelStatus": "NORMAL", "liquidatePrice": "1", "indexPrice": "2",
             "baseAsset": {"asset": "ETH", "borrowed": "0", "interest": "0"}, "quoteAsset": {"asset": "USDT", "borrowed": "10", "interest": "0"}}]
run(w, 65)
mine = [it for src in ("okx_loan", "bn_margin") for it in (((w.risk.get(src) or {}).get("recs")) or {}).values()]
W.okx_loans, W.bn_margin, W.bn_iso = [], None, []
run(w, 65)

_H0 = LW.HTTP


def with_http(over):
    def h(method, url, headers=None, body=None, timeout=6.0):
        path = urllib.parse.urlsplit(url).path
        for frag, resp in over.items():
            if frag in path:
                W.calls.append((T[0], method, urllib.parse.urlsplit(url).hostname, path, {}))
                if isinstance(resp, Exception):
                    raise resp
                return 200, {}, (resp() if callable(resp) else resp)
        return router(method, url, headers, body, timeout)
    LW.HTTP = h


def okx_loan_row(ltv_ref=0.5):
    return {"ordId": "q", "collateralData": [{"ccy": "ETH", "amt": "10"}], "loanData": [{"ccy": "USDT", "amt": "10000"}],
            "marginCallLTV": "0.8", "liqLTV": "0.9", "riskWarningData": {}, "_ref": (ltv_ref, 2000.0, "ETH")}


try:
    q1 = (LW.fut_dist(90, 75, "LONG"), LW.fut_dist(110, 125, "SHORT"), LW.fut_dist(90, 100, "LONG"), LW.fut_dist(110, 100, "SHORT"))
except TypeError as e:
    q1 = (str(e),)
check("Q1 fut_dist 방향 — 롱 마크 ≤ 청산가 = 0 · 숏 마크 ≥ 청산가 = 0 · 정상 거리 그대로",
      len(q1) == 4 and q1[0] == 0 and q1[1] == 0 and abs(q1[2] - 10) < 1e-9 and abs(q1[3] - 10) < 1e-9, q1)
W.pos["binance"] = [{"sym": "QQUSDT", "amt": 1.0, "liq": 90.0}]
W.mark[("binance", "QQUSDT")] = 99.0
got = run(w, 8)
W.mark[("binance", "QQUSDT")] = 75.0
got2 = run(w, 40)
check("Q1 롱 청산가를 지나친 신선한 가격 → ✅ 없음 · '청산가에 닿았거나 지났어요' 1통", len(got) == 1 and not [x for x in got2 if x["text"].startswith("✅")]
      and len([x for x in got2 if "청산가에 닿았거나 지났어요" in x["text"]]) == 1, ([x["text"][:30] for x in got], [x["text"][:30] for x in got2]))
W.pos["binance"] = []
run(w, 40)

W.pos["binance"] = [{"sym": "QBUSDT", "amt": 1.0, "liq": 50000.0}]
W.mark[("binance", "QBUSDT")] = 54500.0
got = run(w, 8)
with_http({"/fapi/v3/positionRisk": [{"symbol": "QBUSDT", "positionAmt": "bad", "liquidationPrice": "50000"}]})
got2 = run(w, 40)
s9 = w.v["binance"]
check("Q2 positionAmt 숫자 오류 응답 = 조회 실패(포지션 들고 감시 · 닫힘 ✅ 없음)", len(got) == 1 and not [x for x in got2 if "닫혀" in x["text"]]
      and s9.get("ok") is False and s9.get("pos"), ([x["text"][:30] for x in got2], s9.get("ok"), s9.get("err")))
with_http({"/fapi/v3/positionRisk": [{"symbol": "QBUSDT", "liquidationPrice": "50000"}]})
got2 = run(w, 40)
check("Q2 positionAmt 누락 응답 = 조회 실패(닫힘 없음)", not [x for x in got2 if "닫혀" in x["text"]] and w.v["binance"].get("ok") is False,
      [x["text"][:30] for x in got2])
LW.HTTP = _H0
W.pos["binance"] = []
run(w, 40)
W.okx_loans = [okx_loan_row()]
W.spot[("okx", "ETH")] = 2000.0
run(w, 65)
W.spot[("okx", "ETH")] = 1380.0
got = run(w, 6)
bad_loan = [{"ordId": "q", "collateralData": [{"ccy": "ETH", "amt": "10"}], "curLTV": "0.7", "marginCallLTV": "0.8", "liqLTV": "0.9"}]
with_http({"/api/v5/finance/flexible-loan/loan-info": {"code": "0", "data": bad_loan}})
got2 = run(w, 130)
check("Q2 OKX loanData 누락 = 조회 실패('빚이 없어져' ✅ 없음 · 기억 유지)", len(got) == 1 and not [x for x in got2 if "빚이 없어져" in x["text"]]
      and "okx:loan:loan:q" in w.st["risk"] and (w.risk.get("okx_loan") or {}).get("ok") is False, ([x["text"][:30] for x in got2], w.risk.get("okx_loan", {}).get("err")))
with_http({"/api/v5/finance/flexible-loan/loan-info": {"code": "0", "data": [dict(okx_loan_row(), loanData=[{"ccy": "USDT", "amt": "x"}])]}})
got2 = run(w, 65)
check("Q2 OKX 부채 수량 숫자 오류 = 조회 실패(✅ 없음)", not [x for x in got2 if x["text"].startswith("✅")], [x["text"][:30] for x in got2])
LW.HTTP = _H0
W.okx_loans = []
W.spot[("okx", "ETH")] = 2000.0
run(w, 70)
W.bn_margin = {"marginLevel": "1.6", "userAssets": [{"asset": "BTC", "free": "1", "locked": "0", "borrowed": "0", "interest": "0"},
                                                   {"asset": "USDT", "free": "0", "locked": "0", "borrowed": "37500", "interest": "0"}]}
W.spot[("binance", "BTC")] = 52000.0
got = run(w, 65)
with_http({"/sapi/v1/margin/account": {}})
got2 = run(w, 130)
with_http({"/sapi/v1/margin/account": {"marginLevel": "0", "userAssets": W.bn_margin["userAssets"]}})
got3 = run(w, 130)
check("Q2 바이낸스 margin/account 빈 응답·마진 레벨 0(부채 남음) = '빚이 없어져' 없음(기억 유지)",
      len([x for x in got if x["kind"] == "MARGIN_RISK"]) == 1 and not [x for x in got2 + got3 if "빚이 없어져" in x["text"]]
      and "binance:margin_cross:account:-" in w.st["risk"], ([x["text"][:30] for x in got], [x["text"][:30] for x in got2 + got3]))
LW.HTTP = _H0
W.bn_margin = None
run(w, 130)

W.pos["binance"] = [{"sym": "QLUSDT", "amt": 1.0, "liq": 92.0}]
W.mark[("binance", "QLUSDT")] = 100.0
got = run(w, 8)
lpos = {"id": "binance:futures_linear:position:QLUSDT:LONG", "ex": "binance", "product": "futures_linear", "scope": "position", "key": "QLUSDT:LONG",
        "label": "QLUSDT 롱", "measured_at": int(T[0]), "stale": False, "metrics": {},
        "position": {"symbol": "QLUSDT", "side": "LONG", "qty": 1, "mark": 100.0, "liq": 92.0, "settle": "USDT"}}
wlev([lpos], [{"ex": "binance", "product": "futures_linear", "status": "ok", "measured_at": int(T[0])}])
w.save(T[0], force=True)
wq = mk()
got2 = run(wq, 3)
W.err["/fapi/v3/positionRisk"] = lambda: TimeoutError("timed out")
got2 += run(wq, 40)
del W.err["/fapi/v3/positionRisk"]
got2 += run(wq, 40)
check("Q3 재시작 첫 판·조회 실패·복구 중 lev 파일의 같은 선물 = 다시 🔴 없음 · 거짓 '닫혀' 없음", len(got) == 1 and not got2,
      ([x["text"][:30] for x in got], [x["text"][:40] for x in got2]))
w = wq
os.remove(LEVP)
W.pos["binance"] = []
run(w, 40)

itq = {"collateral": [{"ccy": "ETH", "qty": 10.0}], "debt": [{"ccy": "USDT", "total": 10000.0}], "_px0": {}}
itq2 = {"collateral": [{"ccy": "ETH", "qty": 10.0}, {"ccy": "SOL", "qty": 5.0}], "debt": [{"ccy": "USDT", "total": 10000.0}], "_px0": {"ETH": 2000.0}}
e1 = LW.estimate_ratio(itq, {"ETH": (1000.0, T[0])}, T[0], 0.5)
e2 = LW.estimate_ratio(itq2, {"ETH": (1000.0, T[0]), "SOL": (100.0, T[0])}, T[0], 0.5)
check("Q4 조회 때 시세 없는 비스테이블 담보 = (거래소 값, 추정 아님, 신선 아님) · 일부만 있으면 부분합으로 옮기지 않음",
      e1 == (0.5, False, False) and e2 == (0.5, False, False), (e1, e2))

memq = {"okx:loan:loan:z": {"st": 1, "at": 0, "label": "t"}}
rowq = {"key": "okx:loan:loan:z", "kind": "loan", "label": "t", "metric": "ltv", "m": {"unit": "frac", "risk": "up"}, "r": 0.3, "call": 0.8, "liq": 0.9}
o = LW.judge_risk(memq, [dict(rowq, alert_ok=True, resolve_ok=True)], [], 1000)
for t9 in range(1020, 1081, 10):
    o += LW.judge_risk(memq, [dict(rowq, alert_ok=True, resolve_ok=False)], [], t9)
o += LW.judge_risk(memq, [dict(rowq, alert_ok=True, resolve_ok=True)], [], 1081)
check("Q5 신선 0초 → 20~80초 낡음 → 81초 신선 = 아직 ✅ 없음(낡은 구간을 안정으로 세지 않음)", not o and "okx:loan:loan:z" in memq, o)
o = LW.judge_risk(memq, [dict(rowq, alert_ok=True, resolve_ok=True)], [], 1141)
check("Q5 그 뒤 신선한 관찰이 60초 이어짐 → ✅ 1통", len(o) == 1 and o[0][1].startswith("✅"), o)
memq = {"okx:loan:loan:z": {"st": 1, "at": 0, "label": "t"}}
o = LW.judge_risk(memq, [dict(rowq, alert_ok=True, resolve_ok=True)], [], 2000)
o += LW.judge_risk(memq, [dict(rowq, alert_ok=True, resolve_ok=True)], [], 2061)
check("Q5 거래소 값만(60초마다 신선) 두 번 안정 → ✅(시세 조회 실패 중에도 해소 가능 · 간격 ≤75초)", len(o) == 1, o)

w.gate = (False, "시험")
n0 = len(W.calls)
try:
    w.call("binance", "bn_fapi", "bn_fapi", "GET", "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=X")
    r6 = "호출함"
except LW.Wait:
    r6 = "Wait"
check("Q6 스위치 꺼짐 = 일꾼이 이미 돌고 있어도 다음 외부 호출 안 함(Wait)", r6 == "Wait" and len(W.calls) == n0, r6)
run(w, 1)

if DYN:
    wcfg({"perp_wallets": [{"dex": "dydx", "address": DYN, "label": "d"}]})
    def dyf(mark, age, pos=True):
        common.atomic_write_json(os.path.join(S, "futures_dydx.json"), {"ts": int(T[0] - age), "positions": ([
            {"symbol": "QD-USD", "side": "LONG", "qty": 1, "mark": mark, "liq": 55000.0, "acct": DYN}] if pos else []),
            "accts": {DYN: {"ts": int(T[0] - age)}}})
        time.sleep(0.01)
    dyf(60000.0, 0)
    got = run(w, 2)
    dyf(90000.0, 300)
    got2 = run(w, 3)
    dyf(90000.0, 300, pos=False)
    got2 += run(w, 3)
    dyf(90000.0, 0)
    got3 = run(w, 2)
    check("Q7 10분 파일이 5분 낡음 = 해소·닫힘 ✅ 없음 · 새 값(90초 안)이면 ✅", len(got) == 1 and not got2 and len(got3) == 1 and got3[0]["text"].startswith("✅"),
          ([x["text"][:30] for x in got], [x["text"][:30] for x in got2], [x["text"][:30] for x in got3]))
    wcfg({})
    os.remove(os.path.join(S, "futures_dydx.json"))
    run(w, 2)
wlev([gate_loan(0.75)], [dict(p, measured_at=int(T[0])) for p in PR])
got = run(w, 2)
wlev([gate_loan(0.5, at=T[0] - 300)], [dict(PR[0], measured_at=int(T[0]) - 300), PR[1]], ts=T[0] - 300)
got2 = run(w, 130)
wlev([], [dict(PR[0], measured_at=int(T[0]) - 300), PR[1]], ts=T[0] - 300)
got2 += run(w, 5)
check("Q7 lev 대출 값이 5분 낡음(lev 신선 22분 안이어도) = 해소·'빚 없어짐' ✅ 없음", len(got) == 1 and not got2,
      ([x["text"][:30] for x in got], [x["text"][:30] for x in got2]))
wlev([], [dict(p, measured_at=int(T[0])) for p in PR])
got3 = run(w, 2)
check("Q7 lev 새 값(90초 안·기억 뒤)에서 대출 없음 = '빚이 없어져' ✅ 1통(의도 변경 — 낡은 값으로는 위에서 0통)",
      len(got3) == 1 and "빚이 없어져" in got3[0]["text"], [x["text"][:30] for x in got3])
w.st["risk"].pop("gate:loan:loan:m:1", None)
os.remove(LEVP)
run(w, 2)

if DYN:
    wcfg({"perp_wallets": [{"dex": "dydx", "address": DYN, "label": "d"}]})
    common.atomic_write_json(os.path.join(S, "futures_dydx.json"), {"ts": int(T[0]), "positions": [
        {"symbol": "QE-USD", "side": "LONG", "qty": 1, "mark": 60000.0, "liq": 55000.0, "acct": DYN}], "accts": {DYN: {"ts": int(T[0])}}})
    got = run(w, 2)
    common.atomic_write_json(os.path.join(S, "futures_dydx.json"), {"ts": int(T[0]), "accts": {DYN: {"ts": int(T[0])}}})
    got2 = run(w, 3)
    check("Q10 10분 파일 positions 칸 누락(주소 성공 시각은 신선) = 닫힘 ✅ 없음", len(got) == 1 and not got2, ([x["text"][:30] for x in got], [x["text"][:30] for x in got2]))
    common.atomic_write_json(os.path.join(S, "futures_dydx.json"), {"ts": int(T[0]), "positions": [], "accts": {DYN: {"ts": int(T[0])}}})
    run(w, 2)
    wcfg({})
    os.remove(os.path.join(S, "futures_dydx.json"))
wlev([gate_loan(0.75)], [dict(p, measured_at=int(T[0])) for p in PR])
got = run(w, 2)
common.atomic_write_json(LEVP, {"v": 1, "ts": int(T[0]), "fresh_sec": 1320, "products": [dict(p, measured_at=int(T[0])) for p in PR]})
time.sleep(0.01)
got2 = run(w, 3)
check("Q10 lev 파일 items 칸 누락(상품 ok) = '빚 없어짐' ✅ 없음", len(got) == 1 and not got2, ([x["text"][:30] for x in got], [x["text"][:30] for x in got2]))
wlev([], [dict(p, measured_at=int(T[0])) for p in PR])
run(w, 2)
os.remove(LEVP)
run(w, 2)

import perp_dex as PD
import hl_spot as HS
rlq = {}
_pd0, _pdh0, _hs0 = PD._http_default, PD.HTTP, HS.HTTP
hits = []


def _fake_pd(url, body=None, timeout=15):
    hits.append(url)
    raise PD.PerpHTTPError(429, "Too Many Requests", "40")


PD._http_default = _fake_pd
PD.HTTP = _fake_pd
getattr(LW, "_share_hl_rl", lambda *a, **k: None)(rlq, clock=lambda: T[0])
try:
    PD.HTTP("https://api.hyperliquid.xyz/info", {"type": "x"})
except PD.PerpHTTPError:
    pass
rec = rlq.get("api.hyperliquid.xyz", 0) - T[0]
n_h = len(hits)
try:
    HS.HTTP("https://api.hyperliquid.xyz/info", {"type": "x"})
    r8 = "호출함"
except Exception as e:
    r8 = type(e).__name__
check("Q8 기존 수집기 429 → 공유 지도에 기록(빠른 감시도 쉼) · 그 동안 현물 수집기 호출 0(429 로 즉시 실패)", rec > 30 and len(hits) == n_h and r8 == "HLError", (rec, len(hits), r8))
PD._http_default, PD.HTTP, HS.HTTP = _pd0, _pdh0, _hs0

with_http({"/api/v5/market/ticker": {"code": "50011", "msg": "Too Many Requests", "data": []}})
try:
    w.call("okx", "okx_tick", "okx_tick", "GET", "https://www.okx.com/api/v5/market/ticker?instId=ETH-USDT")
except Exception:
    pass
n0 = len(W.calls)
try:
    w.call("okx", "okx_tick", "okx_tick", "GET", "https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT")
    r9 = "호출함"
except LW.Wait:
    r9 = "Wait"
check("Q9 OKX 50011(HTTP 200) → 같은 경로 다음 호출 Wait(30초)", r9 == "Wait" and len(W.calls) == n0, r9)
LW.HTTP = _H0
run(w, 40)

if DYN:
    wcfg({"perp_wallets": [{"dex": "dydx", "address": DYN, "label": "d"}]})
    dyf(60000.0, 0)
    got = run(w, 2)
    dyf(90000.0, 30)
    got2 = run(w, 3)
    dyf(90000.0, 0)
    got3 = run(w, 2)
    check("R1 10분 파일 마크가 30초 낡음 = 해소 ✅ 없음 · 측정 직후(15초 안)면 ✅", len(got) == 1 and not got2 and len(got3) == 1 and got3[0]["text"].startswith("✅"),
          ([x["text"][:30] for x in got], [x["text"][:30] for x in got2], [x["text"][:30] for x in got3]))
    dyf(90000.0, 0, pos=False)
    run(w, 2)
    for k9 in [k for k in w.st["fut"] if k.startswith("dydx:")]:
        w.st["fut"].pop(k9)
    wcfg({})
    os.remove(os.path.join(S, "futures_dydx.json"))
    run(w, 2)
W.bn_iso = [{"symbol": "RIUSDT", "marginLevel": "1.15", "marginLevelStatus": "MARGIN_CALL", "liquidatePrice": "1900", "indexPrice": "2000",
             "baseAsset": {"asset": "RI", "borrowed": "0", "interest": "0"}, "quoteAsset": {"asset": "USDT", "borrowed": "1000", "interest": "1"}}]
got = run(w, 65)
W.bn_iso[0].update(marginLevelStatus="NORMAL", marginLevel="0")
got2 = run(w, 190)
check("R2 부채 남은 격리마진 · 마진 레벨 0(모름) + 상태 NORMAL = ✅ 없음(값 모르면 안정 아님)", len([x for x in got if "RIUSDT" in x["text"]]) == 1 and not got2,
      ([x["text"][:30] for x in got], [x["text"][:30] for x in got2]))
W.bn_iso[0].update(marginLevel="3")
got3 = run(w, 190)
check("R2 마진 레벨을 다시 알고 NORMAL 이 이어지면 ✅ 1통", len([x for x in got3 if x["text"].startswith("✅")]) == 1, [x["text"][:30] for x in got3])
W.bn_iso = []
run(w, 65)
ENV.update({"TJ_BYBIT_KEY": "b" * 16, "TJ_BYBIT_SECRET": "c" * 16})
okx_rows = [{"instId": "RM-USDT", "instType": "MARGIN", "posSide": "net", "pos": "5", "posCcy": "USDT", "markPx": "2", "liqPx": "2.2", "lever": "3"}]
with_http({"/api/v5/account/positions": {"code": "0", "data": okx_rows}})
run(w, 8)
kk = sorted((w.v.get("okx") or {}).get("pos") or {})
check("R3 OKX 현물 마진 net(pos 양수 · posCcy = 호가 통화) = 숏으로 읽음", kk == ["okx:RM-USDT:SHORT:"], kk)
with_http({"/api/v5/account/positions": {"code": "0", "data": [dict(okx_rows[0], posCcy="")]}})
run(w, 40)
check("R3 OKX 현물 마진 net 방향 모름(posCcy 없음) = 조회 실패(마지막 포지션 유지)", (w.v.get("okx") or {}).get("ok") is False
      and sorted((w.v.get("okx") or {}).get("pos") or {}) == ["okx:RM-USDT:SHORT:"], (w.v.get("okx") or {}).get("err"))
with_http({"/v5/position/list": {"retCode": 0, "result": {"list": [{"symbol": "RBUSDT", "size": "1", "side": "", "markPrice": "1", "liqPrice": "0.9"}],
                                                          "nextPageCursor": ""}}})
run(w, 8)
check("R3 바이비트 방향 누락 = 조회 실패(숏으로 읽지 않음)", (w.v.get("bybit") or {}).get("ok") is False, (w.v.get("bybit") or {}).get("err"))
LW.HTTP = _H0
ENV.pop("TJ_BYBIT_KEY")
ENV.pop("TJ_BYBIT_SECRET")
run(w, 40)
for k9 in [k for k in w.st["fut"] if k.startswith(("okx:RM", "bybit:"))]:
    w.st["fut"].pop(k9)
with_http({"/v5/crypto-loan-common/position": {"retCode": 0, "result": {"ltv": "0.5", "collateralList": [], "supplyList": [],
                                                                        "borrowList": [{"loanCurrency": "USDT", "fixedTotalDebt": "0"}]}}})
try:
    w.fetch_risk("bybit_loan", {"TJ_BYBIT_KEY": "b" * 16, "TJ_BYBIT_SECRET": "c" * 16}, {"alerts": {"loan_ltv": {"bybit": {"call": 0.8, "liq": 0.9}}}})
    r4 = "정상(빚 0)"
except ValueError as e:
    r4 = "실패:" + str(e)[:40]
LW.HTTP = _H0
check("R4 바이비트 borrowList 의 flexibleTotalDebt 누락 = 조회 실패('빚 없음' 아님)", r4.startswith("실패"), r4)
if DYN:
    wcfg({"perp_wallets": [{"dex": "dydx", "address": DYN, "label": "d"}]})
    dyf(60000.0, 0)
    got = run(w, 2)
    common.atomic_write_json(os.path.join(S, "futures_dydx.json"), {"ts": int(T[0]), "positions": [
        {"symbol": "QD-USD", "qty": 1, "mark": 60000.0, "liq": 55000.0, "acct": DYN}], "accts": {DYN: {"ts": int(T[0])}}})
    got2 = run(w, 3)
    kq = [k for k in w.st["fut"] if k.startswith("dydx:QD-USD")]
    check("R5 10분 파일 행의 side 누락 = 파일 전체 모름(닫힘·없어진 시각 기록 없음)", len(got) == 1 and not got2 and kq
          and not w.st["fut"][kq[0]].get("absent"), ([x["text"][:30] for x in got2], kq))
    dyf(60000.0, 0, pos=False)
    run(w, 2)
    for k9 in kq:
        w.st["fut"].pop(k9, None)
    wcfg({})
    os.remove(os.path.join(S, "futures_dydx.json"))
    run(w, 2)
kpos = dict(kpos, measured_at=int(T[0]))
wlev([kpos], [dict(p, measured_at=int(T[0])) for p in PR])
got = run(w, 2)
wlev([dict(kpos, position={"symbol": "XBTUSDTM", "qty": 1, "mark": 100.0, "liq": 92.0})], [dict(p, measured_at=int(T[0])) for p in PR])
got2 = run(w, 3)
wlev([{"ex": "kucoin", "scope": "position"}], [dict(p, measured_at=int(T[0])) for p in PR])
got2 += run(w, 3)
check("R5 lev 행의 방향·id 누락 = lev 전체 모름(없어진 시각 기록 없음)", len(got) == 1 and not got2
      and not (w.st["fut"].get("kucoin:XBTUSDTM:LONG:lev") or {}).get("absent"), ([x["text"][:30] for x in got], [x["text"][:30] for x in got2]))
w.st["fut"].pop("kucoin:XBTUSDTM:LONG:lev", None)
W.pos["binance"] = [{"sym": "R6USDT", "amt": 1.0, "liq": 85.0}]
W.mark[("binance", "R6USDT")] = 100.0
run(w, 8)
w.st["fut"]["binance:R6USDT:LONG:lev"] = {"st": 1, "d1": 8.0, "at": int(T[0]), "name": "R6USDT 롱", "ex": "binance",
                                         "levsrc": ["binance", "futures_linear", "USDT"]}
common.append_durable_jsonl(os.path.join(S, AP.FAST_QUEUE), {"ts": int(T[0]), "kind": "LIQ_NEAR", "text": "🔴 R6", "key": "binance:R6USDT:LONG:lev",
                                                            "lw": {"k": "binance:R6USDT:LONG:lev", "g": "fut", "st": 1, "d1": 8.0}})
wlev([], [{"ex": "binance", "product": "futures_linear", "status": "ok", "measured_at": int(T[0])}])
got = run(w, 8)
check("R6 옛 ':lev' 기억(빠른 감시 상품) — lev 목록에 없어도 닫힘 ✅·재알림 없이 빠른 키로", not got and "binance:R6USDT:LONG:" in w.st["fut"]
      and "binance:R6USDT:LONG:lev" not in w.st["fut"], ([x["text"][:30] for x in got], sorted(k for k in w.st["fut"] if "R6" in k)))
w.save(T[0], force=True)
os.remove(os.path.join(S, LW.STATE_NAME))
w6 = mk()
w6.st["moved"] = dict(w.st.get("moved") or {})
w6.st["fut"].clear()
w6._reconcile()
check("R6 재시작 복원(옮긴 관계 기록) = 옛 줄의 ':lev' 키도 빠른 키로 되살림", "binance:R6USDT:LONG:" in w6.st["fut"] and "binance:R6USDT:LONG:lev" not in w6.st["fut"],
      sorted(w6.st["fut"]))
W.pos["binance"] = []
run(w, 40)
w.st["fut"].pop("binance:R6USDT:LONG:", None)
os.remove(LEVP)
run(w, 2)
w.save(T[0], force=True)

stf = common.read_json(os.path.join(S, LW.STATE_NAME), {})
blob = json.dumps(stf) + open(os.path.join(S, AP.FAST_QUEUE), encoding="utf-8").read()
check("Z1 상태 파일(liq_watch.json) = 판 시각·켜짐·곳별 상태(헬스 '청산 빠른 감시 멈춤' 재료) · health/ 하트비트 파일은 안 만듦(되돌림 뒤 거짓 경보 방지)",
      stf.get("status", {}).get("on") is True and abs(stf.get("ts", 0) - T[0]) <= 31 and not os.path.exists(os.path.join(S, "health", "exf.json")), (list(stf), stf.get("ts"), T[0]))
check("Z2 상태·긴급 줄에 키 값 없음", not any(ENV[k] in blob for k in ENV if k.endswith(("KEY", "SECRET", "PASSPHRASE"))))
import health as HH
hset = HH.settings({})
base_obs = {"now": T[0], "pm2": {u: {"status": "online", "restarts": 0, "pid": 1} for u in hset["units"]}}


def hcheck(lw):
    c9 = [c for c in HH.evaluate(dict(base_obs, liqw=lw), hset) if c["id"] == "liq:watch"]
    return c9[0] if c9 else None


c1 = hcheck({"ts": T[0] - 30, "status": {"on": True}})
c2 = hcheck({"ts": T[0] - 300, "status": {"on": True}})
c3 = hcheck({"ts": T[0] - 900, "status": {"on": True}})
c4 = hcheck({"ts": T[0] - 9000, "status": {"on": False, "why": "꺼짐(config alerts.liq_fast)"}})
c5 = hcheck(None)
check("Z3 헬스 '청산 빠른 감시' — 30초 정상 · 5분 주황 · 15분 빨강 · 꺼짐 = 정보(알림 없음) · 상태 파일 없음 = 점검 없음",
      c1 and c1["level"] == "ok" and c2["level"] == "warn" and c3["level"] == "crit" and c4["level"] == "ok" and not c4["notify"] and c5 is None,
      [(c or {}).get("level") for c in (c1, c2, c3, c4, c5)])
check("Z3 외부 호출은 전부 목(실제 네트워크 0)", all(c[2] in ("fapi.binance.com", "api.binance.com", "api.bybit.com", "www.okx.com", "api.hyperliquid.xyz") for c in W.calls))
H.finish()
