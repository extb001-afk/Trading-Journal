#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os

os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
import common
import leverage as L
import lev_view as V

assert T.TMP in common.STATE_DIR
NOW = 1_800_000_000
SECRET = "SECRETLIKE-0000"


def check(name, ok, detail=""):
    T.chk(bool(ok), name, None if ok else str(detail)[:600])


class R:
    def __init__(self, t):
        self.t = t

    def __call__(self, path, params=None):
        v = self.t.get(path.split("?")[0])
        if isinstance(v, Exception):
            raise v
        return json.loads(json.dumps(v(params) if callable(v) else v))


def collect(ex, g, prev=None):
    if prev is not None:
        common.atomic_write_json(L.path(), prev)
    elif os.path.exists(L.path()):
        os.remove(L.path())
    doc = L.collect({k: "x" for k in L.NEED[ex]}, {ex: g}, now=NOW, cycle_sec=600, fresh_sec=1800)
    L.write(doc)
    return doc


P = lambda ex, p, st="ok", meas=NOW - 60: {"ex": ex, "product": p, "status": st, "status_eff": st, "measured_at": meas}

print("[n0] 공식 상태는 맨 끝")
lev0 = {"v": 1, "ts": NOW, "products": [P("binance", "margin_isolated")], "items": [
    {"id": "binance:margin_isolated:pair:SOLUSDT", "ex": "binance", "product": "margin_isolated", "scope": "pair", "key": "SOLUSDT", "measured_at": NOW - 60, "fresh": True,
     "metrics": {"margin_level": {"v": 1.6, "unit": "x", "risk": "down", "thr_src": "unknown"}, "liq_dist": {"v": 0.08, "unit": "frac", "risk": "down", "liq": 0.0, "thr_src": "doc:x"}},
     "debt": [{"ccy": "USDT", "total": 10.0}], "official_state": {"v": "MARGIN_CALL", "level": 1, "src": "x"}}]}
d0 = V.build(lev0, {}, {"USDT": 1.0}.get, 10.0, None, NOW)
check("격리 페어: 공식 MARGIN_CALL(주의) + 거리 8%(위험) = 위험", d0["rows"][0]["state"] == "danger", d0["rows"][0]["state"])
lev0b = {"v": 1, "ts": NOW, "products": [P("bybit", "futures_linear")], "items": [
    {"id": "bybit:futures_linear:position:ETHUSDT:LONG:", "ex": "bybit", "product": "futures_linear", "scope": "position", "key": "ETHUSDT:LONG", "measured_at": NOW - 60, "fresh": True,
     "metrics": {}, "official_state": {"v": "X1", "level": 1, "src": "x"},
     "position": {"symbol": "ETHUSDT", "side": "LONG", "qty": 1, "qty_unit": "coin", "entry": 100, "mark": 100, "liq": 95, "leverage": 5, "margin_mode": "isolated", "upnl": 0, "settle": "USDT"}}]}
d0b = V.build(lev0b, {}, {"USDT": 1.0}.get, 10.0, None, NOW)
check("선물: 공식 level 1 + 거리 5%(위험) = 위험", [r for r in d0b["rows"] if r["kind"] == "fut"][0]["state"] == "danger")

print("[n1] 더 새 선물 파일 지갑(교차)으로 교차 포지션 판정")
pos = {"symbol": "BTCUSDT", "side": "LONG", "qty": 1, "qty_unit": "coin", "entry": 100, "mark": 100, "liq": 60, "leverage": 5, "margin_mode": "cross", "upnl": 0, "settle": "USDT"}
lev1 = {"v": 1, "ts": NOW - 900, "products": [P("binance", "futures_linear", "error", NOW - 900)], "items": [
    {"id": "binance:futures_linear:position:BTCUSDT:LONG:", "ex": "binance", "product": "futures_linear", "scope": "position", "key": "BTCUSDT:LONG",
     "measured_at": NOW - 900, "fresh": False, "metrics": {}, "position": pos}]}
fb = {"ts": NOW - 20, "wallet": {"maint_margin": 950.0, "margin_balance": 1000.0, "mm_scope": "cross"},
      "positions": [{"symbol": "BTCUSDT", "side": "LONG", "qty": 1, "entry": 100, "mark": 100, "upnl": 0, "leverage": "5", "liq": 60}]}
d1 = V.build(lev1, {"binance": fb}, {"USDT": 1.0}.get, 10.0, None, NOW)
r1 = [r for r in d1["rows"] if r["kind"] == "fut"][0]
check("파일 지갑 교차 95% = 위험(거리 40% 안전이어도)", r1["state"] == "danger" and r1["fresh"], (r1["state"], r1["fresh"]))
fb_old = dict(fb, wallet={"maint_margin": 950.0, "margin_balance": 1000.0})
d1b = V.build(lev1, {"binance": fb_old}, {"USDT": 1.0}.get, 10.0, None, NOW)
check("표식(mm_scope) 없는 옛 파일 지갑 = 판정에 안 씀(혼합 합계일 수 있음)", [r for r in d1b["rows"] if r["kind"] == "fut"][0]["state"] == "unknown")
fb_stale = dict(fb, ts=NOW - 4000)
d1c = V.build(lev1, {"binance": fb_stale}, {"USDT": 1.0}.get, 10.0, None, NOW)
check("낡은 파일 = 확인 못 함(지갑 값도 안 씀)", [r for r in d1c["rows"] if r["kind"] == "fut"][0]["state"] == "unknown")

print("[m2] 게이트 통합계정 부채 행")
G = {"/api/v4/margin/accounts": [], "/api/v4/margin/cross/accounts": {"balances": {"USDT": {"borrowed": "5", "total_liab": "5.2"}}},
     "/api/v4/unified/accounts": {"mode": "multi_currency", "unified_account_total_liab": "100", "total_maintenance_margin_rate": "3",
                                  "balances": {"USDT": {"total_liab": "100", "borrowed": "99"}, "BTC": {"total_liab": "0"}}},
     "/api/v4/loan/multi_collateral/orders": [], "/api/v4/futures/usdt/positions": [], "/api/v4/futures/btc/positions": []}
dg = collect("gate", {"get": R(G)})
ui = [i for i in dg["items"] if i["product"] == "unified"]
check("통합계정 부채 = USDT 100(통화별 total_liab)", ui and ui[0].get("debt") == [{"ccy": "USDT", "principal": 99.0, "interest": None, "total": 100.0, "rate": None, "rate_period": None}], ui and ui[0].get("debt"))
vg = V.build(L.read_state(now=NOW), {}, {"USDT": 1.0}.get, 10.0, None, NOW)
check("빌린 돈 합에 들어감(통합 100 + 교차 5.2)", abs((vg["debtUsd"] or 0) - 105.2) < 1e-9, vg["debtUsd"])
cr = [i for i in dg["items"] if i["product"] == "margin_cross"]
check("[형제] 게이트 교차 합계 = total_liab 5.2(interest 칸 없음)", cr and cr[0]["debt"][0]["total"] == 5.2, cr and cr[0].get("debt"))
G["/api/v4/unified/accounts"] = {"mode": "multi_currency", "unified_account_total_liab": "100", "balances": {}}
dg2 = collect("gate", {"get": R(G)})
pu = [p for p in dg2["products"] if p["ex"] == "gate" and p["product"] == "unified"][0]
check("부채 합계만 있고 통화별 없음 = 오류(없음 아님)", pu["status"] == "error", pu)

print("[s0] 캐시 = 쓰는 칸만")
okx = R({"/api/v5/account/balance": [{"details": [{"ccy": "USDT", "liab": "10", "interest": "0.1"}], "mgnRatio": "5", "mmr": "1"}],
         "/api/v5/account/config": [{"acctLv": "3", "ip": SECRET, "uid": SECRET, "mainUid": SECRET, "label": SECRET, "perm": "read_only"}],
         "/api/v5/account/interest-rate": [{"ccy": "USDT", "interestRate": "0.00001", "extra": SECRET}],
         "/api/v5/finance/flexible-loan/loan-info": [{"ordId": "5", "curLTV": "0.5", "marginCallLTV": "0.88", "liqLTV": "0.98", "loanData": [{"ccy": "USDT", "amt": "100"}],
                                                       "collateralData": [{"ccy": "OKB", "amt": "4"}]}],
         "/api/v5/finance/flexible-loan/loan-history": [],
         "/api/v5/finance/flexible-loan/interest-accrued": [{"ccy": "USDT", "interest": "1", "interestRate": "0.05", "refId": SECRET, "ts": "1"}],
         "/api/v5/account/positions": []})
do = collect("okx", {"get": okx})
raw = open(L.path()).read()
check("OKX 설정·이자율·이자 기록의 원문 칸(ip·uid·label·refId 등) 미저장", SECRET not in raw, [k for k in json.loads(raw)["_cache"]])
check("쓰는 칸은 남음(acctLv · 이자율)", json.loads(raw)["_cache"]["okx:account-config"]["d"] == [{"acctLv": "3"}])
legacy = dict(do, _cache=dict(do["_cache"], **{"okx:account-config": {"at": NOW, "d": [{"acctLv": "3", "ip": SECRET}]}, "who:knows": {"at": NOW, "d": SECRET}}))
collect("okx", {"get": okx}, prev=legacy)
raw2 = open(L.path()).read()
check("옛 파일 캐시(원문 칸·모르는 키)도 다음 기록 때 거름", SECRET not in raw2, raw2[:200])
bn = R({"/sapi/v1/margin/account": {"marginLevel": "3", "totalLiabilityOfBtc": "0.1", "userAssets": [{"asset": "USDT", "borrowed": "10", "interest": "0", "free": "0", "locked": "0"}]},
        "/sapi/v1/margin/tradeCoeff": {"normalBar": "1.5", "marginCallBar": "1.3", "forceLiquidationBar": "1.1", "x": SECRET},
        "/sapi/v1/margin/crossMarginData": [{"coin": "USDT", "dailyInterest": "0.0002", "vipLevel": SECRET}],
        "/sapi/v1/margin/isolated/account": {"assets": []},
        "/sapi/v2/loan/flexible/ongoing/orders": {"rows": [{"loanCoin": "USDT", "totalDebt": "10", "collateralCoin": "ETH", "collateralAmount": "1", "currentLTV": "0.5"}]},
        "/sapi/v2/loan/flexible/collateral/data": {"rows": [{"collateralCoin": "ETH", "marginCallLTV": "0.75", "liquidationLTV": "0.83", "maxLimit": SECRET}], "total": 1},
        "/sapi/v2/loan/flexible/loanable/data": {"rows": [{"loanCoin": "USDT", "flexibleInterestRate": "0.000005", "flexibleMaxLimit": SECRET}]},
        "/fapi/v2/account": {}, "/fapi/v2/positionRisk": [], "/dapi/v1/positionRisk": []})
collect("binance", {"sapi": bn, "fapi": bn, "dapi": bn})
check("바이낸스 캐시 원문 칸 미저장", SECRET not in open(L.path()).read())
by = R({"/v5/account/wallet-balance": {"list": [{"accountMMRate": "0.1", "totalMaintenanceMargin": "1", "coin": [{"coin": "USDT", "borrowAmount": "5", "accruedInterest": "0"}]}]},
        "/v5/account/info": {"marginMode": "REGULAR_MARGIN", "smpGroup": SECRET},
        "/v5/account/collateral-info": {"list": [{"currency": "USDT", "hourlyBorrowRate": "0.00001", "borrowUsageRate": SECRET}]},
        "/v5/crypto-loan-common/position": {"borrowList": [], "collateralList": []}, "/v5/position/list": {"list": [], "nextPageCursor": ""}})
collect("bybit", {"get": by})
check("바이빗 캐시 원문 칸 미저장", SECRET not in open(L.path()).read())
kc = R({"/api/v3/margin/accounts": {"debtRatio": "0.5", "accounts": [{"currency": "USDT", "total": "10", "liability": "5", "liabilityPrincipal": "5", "liabilityInterest": "0"}]},
        "/api/v3/margin/borrowRate": {"items": [{"currency": "USDT", "hourlyBorrowRate": "0.000001", "vipLevel": SECRET}]},
        "/api/v3/isolated/accounts": {"assets": [{"symbol": "BTC-USDT", "debtRatio": "0.4", "baseAsset": {"currency": "BTC", "liability": "0"},
                                                  "quoteAsset": {"currency": "USDT", "liability": "1", "liabilityPrincipal": "1", "liabilityInterest": "0"}}]}})
kcp = R({"/api/v1/margin/config": {"warningDebtRatio": "0.95", "liqDebtRatio": "0.97", "currencyList": [SECRET]},
         "/api/v1/isolated/symbols": [{"symbol": "BTC-USDT", "flDebtRatio": "0.97", "baseCurrency": SECRET}]})
collect("kucoin", {"get": kc, "fut": R({"/api/v1/positions": []}), "pub": kcp})
check("쿠코인 캐시 원문 칸 미저장", SECRET not in open(L.path()).read())
check("모든 캐시 진입점이 칸 목록에 있음(코드 속 run.cached 키 = CACHE_FIELDS)", all(L._proj_spec(k) is not None for k in (
    "binance:tradeCoeff", "binance:crossMarginData:USDT", "binance:loanCollateral", "binance:loanable", "bybit:account-info", "bybit:collateral-info:USDT",
    "okx:account-config", "okx:interest-rate:USDT", "okx:loan-interest-accrued", "kucoin:margin-config", "kucoin:borrowRate:USDT", "kucoin:isolated-symbols", "gate:multi-ltv")))
import re
keys_in_code = set(re.findall(r'run\.cached\(f?"([a-z]+:[A-Za-z-]+:?)', open(os.path.join(T.SRC, "leverage.py"), encoding="utf-8").read()))
check("코드의 캐시 키 앞부분이 전부 칸 목록에 있음(새 캐시 추가 때 빠뜨림 방지)", all(L._proj_spec(k + ("X" if k.endswith(":") else "")) is not None for k in keys_in_code), sorted(keys_in_code))

T.finish()
