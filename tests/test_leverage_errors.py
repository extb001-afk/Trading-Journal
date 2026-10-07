#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import copy
import json
import os

os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
import common
import leverage as L
import perp_dex as PD

assert T.TMP in common.STATE_DIR
NOW = 1_800_000_000


def check(name, ok, detail=""):
    T.chk(bool(ok), name, None if ok else str(detail)[:400])


class Router:
    def __init__(self, table):
        self.t, self.calls = dict(table), []

    def __call__(self, path, params=None):
        self.calls.append(path)
        k = path.split("?", 1)[0]
        v = self.t.get(path, self.t.get(k, KeyError(f"no route {path}")))
        if isinstance(v, Exception):
            raise v
        return copy.deepcopy(v(params) if callable(v) else v)


ENV = {"TJ_BINANCE_KEY": "k", "TJ_BINANCE_SECRET": "s", "TJ_BYBIT_KEY": "k", "TJ_BYBIT_SECRET": "s",
       "TJ_OKX_KEY": "k", "TJ_OKX_SECRET": "s", "TJ_OKX_PASSPHRASE": "p", "TJ_KUCOIN_KEY": "k", "TJ_KUCOIN_SECRET": "s",
       "TJ_KUCOIN_PASSPHRASE": "p", "TJ_GATE_KEY": "k", "TJ_GATE_SECRET": "s"}


def prod(doc, ex, product):
    r = [p for p in doc["products"] if p["ex"] == ex and p["product"] == product]
    return r[0] if r else None


def items_of(doc, ex, product):
    return [i for i in doc["items"] if i["ex"] == ex and i["product"] == product]


def bn_tab():
    return {"/sapi/v1/margin/account": {"marginLevel": "2.5", "totalLiabilityOfBtc": "0.4", "userAssets": [
                {"asset": "USDT", "borrowed": "100", "interest": "0.5", "free": "0", "locked": "0"},
                {"asset": "BTC", "borrowed": "0", "interest": "0", "free": "0.01", "locked": "0"}]},
            "/sapi/v1/margin/tradeCoeff": {"normalBar": "1.5", "marginCallBar": "1.3", "forceLiquidationBar": "1.1"},
            "/sapi/v1/margin/crossMarginData": [{"coin": "USDT", "dailyInterest": "0.0002"}],
            "/sapi/v1/margin/isolated/account": {"assets": [{"symbol": "ETHUSDT", "marginLevel": "1.4", "marginLevelStatus": "NORMAL",
                                                             "indexPrice": "100", "liquidatePrice": "80",
                                                             "baseAsset": {"asset": "ETH", "borrowed": "0", "interest": "0", "totalAsset": "2"},
                                                             "quoteAsset": {"asset": "USDT", "borrowed": "50", "interest": "0.1", "totalAsset": "0"}}]},
            "/sapi/v2/loan/flexible/ongoing/orders": {"total": 1, "rows": [{"loanCoin": "USDT", "totalDebt": "1000", "collateralCoin": "ETH",
                                                                            "collateralAmount": "1", "currentLTV": "0.5"}]},
            "/sapi/v2/loan/flexible/collateral/data": {"rows": [{"collateralCoin": "ETH", "marginCallLTV": "0.75", "liquidationLTV": "0.83"}]},
            "/sapi/v2/loan/flexible/loanable/data": {"rows": [{"loanCoin": "USDT", "flexibleInterestRate": "0.000005"}]},
            "/fapi/v2/account": {"totalMarginBalance": "1000", "totalMaintMargin": "50", "totalCrossWalletBalance": "900", "totalCrossUnPnl": "100",
                                 "positions": [{"symbol": "BTCUSDT", "isolated": False, "maintMargin": "40"}]},
            "/fapi/v2/positionRisk": [{"symbol": "BTCUSDT", "positionAmt": "0.01", "entryPrice": "50000", "markPrice": "50000",
                                       "liquidationPrice": "40000", "leverage": "5", "marginType": "cross", "positionSide": "BOTH"},
                                      {"symbol": "XRPUSDT", "positionAmt": "0", "markPrice": "1"}],
            "/dapi/v1/positionRisk": [{"symbol": "BTCUSD_PERP", "positionAmt": "3", "entryPrice": "50000", "markPrice": "50000",
                                       "liquidationPrice": "30000", "leverage": "3", "marginType": "isolated", "positionSide": "BOTH"}]}


def bb_tab():
    pos = {"USDT": [{"symbol": "BTCUSDT", "side": "Sell", "size": "0.1", "avgPrice": "50000", "markPrice": "50000", "liqPrice": "60000",
                     "leverage": "10", "positionIdx": 0, "positionStatus": "Normal"}], "USDC": [], None: [
                    {"symbol": "BTCUSD", "side": "Buy", "size": "100", "avgPrice": "50000", "markPrice": "50000", "liqPrice": "30000",
                     "leverage": "3", "positionIdx": 0, "positionStatus": "Normal"}]}
    return {"/v5/account/wallet-balance": {"list": [{"accountMMRate": "0.25", "accountIMRate": "0.4", "totalMaintenanceMargin": "10",
                                                      "coin": [{"coin": "USDT", "borrowAmount": "100", "accruedInterest": "1"}]}]},
            "/v5/account/info": {"marginMode": "REGULAR_MARGIN"},
            "/v5/account/collateral-info": {"list": [{"currency": "USDT", "hourlyBorrowRate": "0.00001"}]},
            "/v5/crypto-loan-common/position": {"ltv": "0.6", "borrowList": [{"loanCurrency": "USDT", "fixedTotalDebt": "0", "flexibleTotalDebt": "500"}],
                                                "collateralList": [{"currency": "BTC", "amount": "0.02"}], "supplyList": []},
            "/v5/crypto-loan-flexible/ongoing-coin": {"list": []},
            "/v5/position/list": lambda q: {"list": pos[q.get("settleCoin")] if q.get("category") == "linear" else pos[None], "nextPageCursor": ""}}


def ok_tab():
    return {"/api/v5/account/balance": [{"mgnRatio": "3.5", "mmr": "10", "details": [{"ccy": "USDT", "liab": "100", "interest": "0.2"}]}],
            "/api/v5/account/config": [{"acctLv": "3"}], "/api/v5/account/interest-rate": [{"ccy": "USDT", "interestRate": "0.00001"}],
            "/api/v5/finance/flexible-loan/loan-info": [{"ordId": "1", "curLTV": "0.5", "marginCallLTV": "0.8", "liqLTV": "0.9",
                                                         "loanData": [{"ccy": "USDT", "amt": "1000"}], "collateralData": [{"ccy": "OKB", "amt": "10"}]}],
            "/api/v5/finance/flexible-loan/interest-accrued": [], "/api/v5/finance/flexible-loan/loan-history": [],
            "/api/v5/account/positions": [
                {"instType": "SWAP", "instId": "BTC-USDT-SWAP", "pos": "2", "posSide": "net", "avgPx": "100", "markPx": "100", "liqPx": "50", "mgnMode": "cross"},
                {"instType": "SWAP", "instId": "BTC-USD-SWAP", "pos": "-1", "posSide": "net", "avgPx": "100", "markPx": "100", "liqPx": "150", "mgnMode": "isolated"},
                {"instType": "MARGIN", "instId": "ETH-USDT", "pos": "1", "posCcy": "ETH", "avgPx": "100", "markPx": "100", "liqPx": "70",
                 "mgnMode": "isolated", "liab": "60", "liabCcy": "USDT"},
                {"instType": "MARGIN", "instId": "SOL-USDT", "pos": "1", "posCcy": "SOL", "avgPx": "100", "markPx": "100", "liqPx": "70",
                 "mgnMode": "cross", "liab": "60", "liabCcy": "USDT"},
                {"instType": "OPTION", "instId": "BTC-USD-261231-100000-C", "pos": "1"}]}


def kc_tabs():
    get = {"/api/v3/margin/accounts": {"debtRatio": "0.5", "status": "EFFECTIVE",
                                       "accounts": [{"currency": "USDT", "total": "200", "liability": "100.2", "liabilityPrincipal": "100", "liabilityInterest": "0.2"}]},
           "/api/v3/margin/borrowRate": {"items": []},
           "/api/v3/isolated/accounts": {"assets": [{"symbol": "ETH-USDT", "debtRatio": "0.3", "status": "EFFECTIVE",
                                                     "baseAsset": {"currency": "ETH", "total": "1", "liability": "0"},
                                                     "quoteAsset": {"currency": "USDT", "total": "0", "liability": "30"}}]}}
    pub = {"/api/v1/margin/config": {"warningDebtRatio": "0.95", "liqDebtRatio": "0.97"}, "/api/v1/isolated/symbols": [{"symbol": "ETH-USDT", "flDebtRatio": "0.97"}]}
    fut = {"/api/v1/positions": [{"symbol": "XBTUSDTM", "isOpen": True, "currentQty": 3, "avgEntryPrice": 100, "markPrice": 100,
                                  "liquidationPrice": 80, "marginMode": "ISOLATED", "realLeverage": 5, "settleCurrency": "USDT"},
                                 {"symbol": "XBTUSDM", "isOpen": True, "currentQty": -2, "avgEntryPrice": 100, "markPrice": 100,
                                  "liquidationPrice": 125, "marginMode": "ISOLATED", "realLeverage": 4, "settleCurrency": "XBT"}]}
    return get, pub, fut


def gt_tab():
    return {"/api/v4/margin/accounts": [{"currency_pair": "ETH_USDT", "base": {"currency": "ETH", "available": "1", "locked": "0", "borrowed": "0", "interest": "0"},
                                         "quote": {"currency": "USDT", "available": "0", "locked": "0", "borrowed": "30", "interest": "0.1"}}],
            "/api/v4/margin/cross/accounts": {"risk": "1.8", "balances": {"USDT": {"borrowed": "10", "interest": "0.01", "total_liab": "10.01"}}},
            "/api/v4/unified/accounts": {"mode": "multi_currency", "unified_account_total_liab": "20", "balances": {"USDT": {"borrowed": "20", "total_liab": "20"}}},
            "/api/v4/loan/multi_collateral/orders": lambda q: ([{"order_id": 7, "current_ltv": "0.4",
                                                                 "borrow_currencies": [{"currency": "USDT", "left_repay_principal": "100", "left_repay_interest": "1"}],
                                                                 "collateral_currencies": [{"currency": "BTC", "left_collateral": "0.01"}]}]
                                                               if q.get("order_type") == "current" else []),
            "/api/v4/loan/multi_collateral/ltv": {"alert_ltv": "0.8", "liquidate_ltv": "0.9"},
            "/api/v4/futures/usdt/positions": [{"contract": "BTC_USDT", "size": 2, "entry_price": "100", "mark_price": "100", "liq_price": "50", "leverage": "5"}],
            "/api/v4/futures/btc/positions": [{"contract": "BTC_USD", "size": -1, "entry_price": "100", "mark_price": "100", "liq_price": "150", "leverage": "5"}]}


def getters(ex, over=None):
    over = over or {}
    if ex == "binance":
        t = bn_tab()
        t.update(over)
        r = Router(t)
        return {"sapi": r, "fapi": r, "dapi": r}
    if ex == "bybit":
        t = bb_tab()
        t.update(over)
        return {"get": Router(t)}
    if ex == "okx":
        t = ok_tab()
        t.update(over)
        return {"get": Router(t)}
    if ex == "kucoin":
        get, pub, fut = kc_tabs()
        for k, v in over.items():
            (fut if k == "/api/v1/positions" else pub if k in pub else get)[k] = v
        return {"get": Router(get), "pub": Router(pub), "fut": Router(fut)}
    t = gt_tab()
    t.update(over)
    return {"get": Router(t)}


def run(ex, over=None, prev=None, now=NOW):
    e9 = {k: v for k, v in ENV.items() if k in L.NEED[ex]}
    if prev is not None:
        common.atomic_write_json(L.path(), prev)
    elif os.path.exists(L.path()):
        os.remove(L.path())
    return L.collect(e9, {ex: getters(ex, over)}, now=now, cycle_sec=600, fresh_sec=1800)


def mut(base, fn):
    d = copy.deepcopy(base)
    fn(d)
    return d


print("[L0] 정상 합성 응답 — 상품마다 ok · 위험 줄 있음")
GOOD = {}
WANT_ITEMS = {"binance": ("margin_cross", "margin_isolated", "loan", "futures_linear", "futures_inverse"),
              "bybit": ("unified", "loan", "futures_linear", "futures_inverse"),
              "okx": ("unified", "loan", "futures_linear", "futures_inverse", "margin_isolated", "margin_cross"),
              "kucoin": ("margin_cross", "margin_isolated", "futures_linear", "futures_inverse"),
              "gate": ("margin_isolated", "margin_cross", "unified", "loan", "futures_linear", "futures_inverse")}
for ex, prods in WANT_ITEMS.items():
    d = run(ex)
    GOOD[ex] = d
    bad = [p for p in prods if prod(d, ex, p)["status"] != "ok" or not items_of(d, ex, p)]
    check(f"{ex}: 정상 판 상품 {len(prods)}개 ok + 줄", not bad, [(p, prod(d, ex, p), len(items_of(d, ex, p))) for p in bad])

print("[L1] 수량·목록·부채 칸 누락/형식 오류 = 그 상품 error(ok '없음' 아님) · 직전 줄 stale(측정 시각 그대로)")
B, BB, O, (KG, KP, KF), G = bn_tab(), bb_tab(), ok_tab(), kc_tabs(), gt_tab()
P = "/sapi/v1/margin/account"
CASES = [
    ("바이낸스 교차 userAssets 행 형식(문자열)", "binance", "margin_cross", {P: mut(B[P], lambda d: d["userAssets"].insert(0, "x"))}),
    ("바이낸스 교차 borrowed 누락", "binance", "margin_cross", {P: mut(B[P], lambda d: d["userAssets"][0].pop("borrowed"))}),
    ("바이낸스 교차 borrowed 숫자 아님", "binance", "margin_cross", {P: mut(B[P], lambda d: d["userAssets"][0].update(borrowed="abc"))}),
    ("바이낸스 교차 interest 누락", "binance", "margin_cross", {P: mut(B[P], lambda d: d["userAssets"][0].pop("interest"))}),
    ("바이낸스 교차 asset 빈 값", "binance", "margin_cross", {P: mut(B[P], lambda d: d["userAssets"][0].update(asset=""))}),
    ("바이낸스 격리 quoteAsset 누락", "binance", "margin_isolated",
     {"/sapi/v1/margin/isolated/account": mut(B["/sapi/v1/margin/isolated/account"], lambda d: d["assets"][0].pop("quoteAsset"))}),
    ("바이낸스 격리 borrowed 숫자 아님", "binance", "margin_isolated",
     {"/sapi/v1/margin/isolated/account": mut(B["/sapi/v1/margin/isolated/account"], lambda d: d["assets"][0]["quoteAsset"].update(borrowed=None))}),
    ("바이낸스 격리 assets 행 형식", "binance", "margin_isolated",
     {"/sapi/v1/margin/isolated/account": mut(B["/sapi/v1/margin/isolated/account"], lambda d: d["assets"].append(7))}),
    ("바이낸스 대출 rows 행 형식", "binance", "loan",
     {"/sapi/v2/loan/flexible/ongoing/orders": mut(B["/sapi/v2/loan/flexible/ongoing/orders"], lambda d: d["rows"].insert(0, None))}),
    ("바이낸스 대출 totalDebt 누락", "binance", "loan",
     {"/sapi/v2/loan/flexible/ongoing/orders": mut(B["/sapi/v2/loan/flexible/ongoing/orders"], lambda d: d["rows"][0].pop("totalDebt"))}),
    ("바이낸스 대출 collateralAmount 누락", "binance", "loan",
     {"/sapi/v2/loan/flexible/ongoing/orders": mut(B["/sapi/v2/loan/flexible/ongoing/orders"], lambda d: d["rows"][0].pop("collateralAmount"))}),
    ("바이낸스 USDⓈ-M positionAmt 누락", "binance", "futures_linear", {"/fapi/v2/positionRisk": mut(B["/fapi/v2/positionRisk"], lambda d: d[0].pop("positionAmt"))}),
    ("바이낸스 USDⓈ-M positionAmt 숫자 아님", "binance", "futures_linear", {"/fapi/v2/positionRisk": mut(B["/fapi/v2/positionRisk"], lambda d: d[0].update(positionAmt="?"))}),
    ("바이낸스 USDⓈ-M 행 형식", "binance", "futures_linear", {"/fapi/v2/positionRisk": mut(B["/fapi/v2/positionRisk"], lambda d: d.insert(0, []))}),
    ("바이낸스 USDⓈ-M symbol 빈 값", "binance", "futures_linear", {"/fapi/v2/positionRisk": mut(B["/fapi/v2/positionRisk"], lambda d: d[0].update(symbol=""))}),
    ("바이낸스 COIN-M positionAmt 누락", "binance", "futures_inverse", {"/dapi/v1/positionRisk": mut(B["/dapi/v1/positionRisk"], lambda d: d[0].pop("positionAmt"))}),
    ("바이빗 통합 list 빈 목록", "bybit", "unified", {"/v5/account/wallet-balance": {"list": []}}),
    ("바이빗 통합 coin 칸 누락", "bybit", "unified", {"/v5/account/wallet-balance": mut(BB["/v5/account/wallet-balance"], lambda d: d["list"][0].pop("coin"))}),
    ("바이빗 통합 coin 행 형식", "bybit", "unified", {"/v5/account/wallet-balance": mut(BB["/v5/account/wallet-balance"], lambda d: d["list"][0]["coin"].append("x"))}),
    ("바이빗 통합 borrowAmount 누락", "bybit", "unified",
     {"/v5/account/wallet-balance": mut(BB["/v5/account/wallet-balance"], lambda d: d["list"][0]["coin"][0].pop("borrowAmount"))}),
    ("바이빗 통합 totalMaintenanceMargin 칸 누락", "bybit", "unified",
     {"/v5/account/wallet-balance": mut(BB["/v5/account/wallet-balance"], lambda d: (d["list"][0].pop("totalMaintenanceMargin"), d["list"][0].update(coin=[])))}),
    ("바이빗 대출 부채 칸 둘 다 누락", "bybit", "loan",
     {"/v5/crypto-loan-common/position": mut(BB["/v5/crypto-loan-common/position"], lambda d: (d["borrowList"][0].pop("fixedTotalDebt"), d["borrowList"][0].pop("flexibleTotalDebt")))}),
    ("바이빗 대출 borrowList 행 형식", "bybit", "loan",
     {"/v5/crypto-loan-common/position": mut(BB["/v5/crypto-loan-common/position"], lambda d: d["borrowList"].append(1))}),
    ("바이빗 대출 담보 amount 누락", "bybit", "loan",
     {"/v5/crypto-loan-common/position": mut(BB["/v5/crypto-loan-common/position"], lambda d: (d["collateralList"][0].pop("amount"), d.update(borrowList=[])))}),
    ("바이빗 선형 size 누락", "bybit", "futures_linear",
     {"/v5/position/list": lambda q: {"list": [{"symbol": "BTCUSDT", "side": "Sell"}] if q.get("settleCoin") == "USDT" else [], "nextPageCursor": ""}}),
    ("바이빗 인버스 행 형식", "bybit", "futures_inverse",
     {"/v5/position/list": lambda q: {"list": ["x"] if q.get("category") == "inverse" else [], "nextPageCursor": ""}}),
    ("OKX 계정 data 빈 목록", "okx", "unified", {"/api/v5/account/balance": []}),
    ("OKX 계정 details 칸 누락", "okx", "unified", {"/api/v5/account/balance": mut(O["/api/v5/account/balance"], lambda d: d[0].pop("details"))}),
    ("OKX 계정 liab 칸 누락", "okx", "unified", {"/api/v5/account/balance": mut(O["/api/v5/account/balance"], lambda d: d[0]["details"][0].pop("liab"))}),
    ("OKX 계정 liab 숫자 아님", "okx", "unified", {"/api/v5/account/balance": mut(O["/api/v5/account/balance"], lambda d: d[0]["details"][0].update(liab="x"))}),
    ("OKX 대출 loanData 칸 누락", "okx", "loan",
     {"/api/v5/finance/flexible-loan/loan-info": mut(O["/api/v5/finance/flexible-loan/loan-info"], lambda d: d[0].pop("loanData"))}),
    ("OKX 대출 amt 누락", "okx", "loan",
     {"/api/v5/finance/flexible-loan/loan-info": mut(O["/api/v5/finance/flexible-loan/loan-info"], lambda d: d[0]["loanData"][0].pop("amt"))}),
    ("OKX 대출 담보 amt 숫자 아님", "okx", "loan",
     {"/api/v5/finance/flexible-loan/loan-info": mut(O["/api/v5/finance/flexible-loan/loan-info"], lambda d: d[0]["collateralData"][0].update(amt=""))}),
    ("OKX 대출 행 형식", "okx", "loan", {"/api/v5/finance/flexible-loan/loan-info": ["x"]}),
    ("OKX 포지션 pos 누락(선형)", "okx", "futures_linear", {"/api/v5/account/positions": mut(O["/api/v5/account/positions"], lambda d: d[0].pop("pos"))}),
    ("OKX 포지션 pos 누락(격리 마진)", "okx", "margin_isolated", {"/api/v5/account/positions": mut(O["/api/v5/account/positions"], lambda d: d[2].pop("pos"))}),
    ("OKX 포지션 모르는 instType", "okx", "futures_inverse", {"/api/v5/account/positions": mut(O["/api/v5/account/positions"], lambda d: d.append({"instType": "WEIRD", "instId": "A-B", "pos": "1"}))}),
    ("OKX 포지션 행 형식", "okx", "margin_cross", {"/api/v5/account/positions": mut(O["/api/v5/account/positions"], lambda d: d.append(None))}),
    ("쿠코인 교차 liability 누락", "kucoin", "margin_cross",
     {"/api/v3/margin/accounts": mut(KG["/api/v3/margin/accounts"], lambda d: d["accounts"][0].pop("liability"))}),
    ("쿠코인 교차 accounts 행 형식", "kucoin", "margin_cross",
     {"/api/v3/margin/accounts": mut(KG["/api/v3/margin/accounts"], lambda d: d["accounts"].insert(0, "x"))}),
    ("쿠코인 격리 quoteAsset 누락", "kucoin", "margin_isolated",
     {"/api/v3/isolated/accounts": mut(KG["/api/v3/isolated/accounts"], lambda d: d["assets"][0].pop("quoteAsset"))}),
    ("쿠코인 격리 liability 숫자 아님", "kucoin", "margin_isolated",
     {"/api/v3/isolated/accounts": mut(KG["/api/v3/isolated/accounts"], lambda d: d["assets"][0]["quoteAsset"].update(liability="?"))}),
    ("쿠코인 선물 currentQty 누락(선형)", "kucoin", "futures_linear", {"/api/v1/positions": mut(KF["/api/v1/positions"], lambda d: d[0].pop("currentQty"))}),
    ("쿠코인 선물 settleCurrency 누락(선형이 인버스로 새지 않게)", "kucoin", "futures_linear",
     {"/api/v1/positions": mut(KF["/api/v1/positions"], lambda d: d[0].pop("settleCurrency"))}),
    ("쿠코인 선물 행 형식(인버스)", "kucoin", "futures_inverse", {"/api/v1/positions": mut(KF["/api/v1/positions"], lambda d: d.append("x"))}),
    ("게이트 격리 quote 누락", "gate", "margin_isolated", {"/api/v4/margin/accounts": mut(G["/api/v4/margin/accounts"], lambda d: d[0].pop("quote"))}),
    ("게이트 격리 borrowed 누락", "gate", "margin_isolated", {"/api/v4/margin/accounts": mut(G["/api/v4/margin/accounts"], lambda d: d[0]["quote"].pop("borrowed"))}),
    ("게이트 격리 행 형식", "gate", "margin_isolated", {"/api/v4/margin/accounts": mut(G["/api/v4/margin/accounts"], lambda d: d.append(3))}),
    ("게이트 교차 통화 행 형식", "gate", "margin_cross",
     {"/api/v4/margin/cross/accounts": mut(G["/api/v4/margin/cross/accounts"], lambda d: d["balances"].update(BTC="x"))}),
    ("게이트 교차 borrowed·total_liab 둘 다 누락", "gate", "margin_cross",
     {"/api/v4/margin/cross/accounts": mut(G["/api/v4/margin/cross/accounts"], lambda d: (d["balances"]["USDT"].pop("borrowed"), d["balances"]["USDT"].pop("total_liab")))}),
    ("게이트 통합 unified_account_total_liab 누락", "gate", "unified",
     {"/api/v4/unified/accounts": mut(G["/api/v4/unified/accounts"], lambda d: d.pop("unified_account_total_liab"))}),
    ("게이트 통합 통화 행 형식", "gate", "unified", {"/api/v4/unified/accounts": mut(G["/api/v4/unified/accounts"], lambda d: d["balances"].update(BTC=1))}),
    ("게이트 대출 borrow_currencies 누락", "gate", "loan",
     {"/api/v4/loan/multi_collateral/orders": lambda q: [{"order_id": 7, "current_ltv": "0.4", "collateral_currencies": []}] if q.get("order_type") == "current" else []}),
    ("게이트 대출 left_repay_principal 누락", "gate", "loan",
     {"/api/v4/loan/multi_collateral/orders": lambda q: [{"order_id": 7, "current_ltv": "0.4", "borrow_currencies": [{"currency": "USDT", "left_repay_interest": "1"}],
                                                          "collateral_currencies": []}] if q.get("order_type") == "current" else []}),
    ("게이트 대출 left_collateral 누락", "gate", "loan",
     {"/api/v4/loan/multi_collateral/orders": lambda q: [{"order_id": 7, "current_ltv": "0.4", "borrow_currencies": [{"currency": "USDT", "left_repay_principal": "1"}],
                                                          "collateral_currencies": [{"currency": "BTC"}]}] if q.get("order_type") == "current" else []}),
    ("게이트 대출 행 형식", "gate", "loan", {"/api/v4/loan/multi_collateral/orders": lambda q: ["x"] if q.get("order_type") == "current" else []}),
    ("게이트 USDT 선물 size 누락", "gate", "futures_linear", {"/api/v4/futures/usdt/positions": [{"contract": "BTC_USDT", "mark_price": "100"}]}),
    ("게이트 BTC 선물 행 형식", "gate", "futures_inverse", {"/api/v4/futures/btc/positions": ["x"]}),
]
for name, ex, product, over in CASES:
    d = run(ex, over, prev=GOOD[ex], now=NOW + 600)
    p = prod(d, ex, product)
    its = items_of(d, ex, product)
    prev_n = len(items_of(GOOD[ex], ex, product))
    ok9 = (p["status"] == "error" and p["measured_at"] == NOW and len(its) == prev_n
           and all(i["stale"] is True and i["measured_at"] == NOW for i in its))
    check(f"{name} → error · 직전 {prev_n}줄 stale", ok9, (p["status"], p.get("note"), p.get("err"), len(its), [i.get("stale") for i in its]))

print("[L2] 정상 0 · 해당 없음('') · 빈 목록 = ok")
ZERO = [
    ("바이낸스 USDⓈ-M 수량 '0' 만 = ok n=0", "binance", "futures_linear",
     {"/fapi/v2/positionRisk": [{"symbol": "XRPUSDT", "positionAmt": "0"}], "/fapi/v2/account": {"totalMarginBalance": "0", "totalMaintMargin": "0"}}),
    ("바이낸스 교차 부채 0 = ok '차입 없음 확인'", "binance", "margin_cross",
     {P: {"marginLevel": "999", "userAssets": [{"asset": "BTC", "borrowed": "0", "interest": "0", "free": "1", "locked": "0"}]}}),
    ("바이낸스 대출 빈 rows = ok", "binance", "loan", {"/sapi/v2/loan/flexible/ongoing/orders": {"total": 0, "rows": []}}),
    ("바이빗 통합 mm '' · 부채 0(격리 모드 해당 없음) = ok n=0", "bybit", "unified",
     {"/v5/account/wallet-balance": {"list": [{"accountMMRate": "", "accountIMRate": "", "totalMaintenanceMargin": "",
                                               "coin": [{"coin": "USDT", "borrowAmount": "0", "accruedInterest": ""}]}]}}),
    ("바이빗 대출 빈 목록 = ok", "bybit", "loan", {"/v5/crypto-loan-common/position": {"ltv": "0", "borrowList": [], "collateralList": [], "supplyList": []}}),
    ("바이빗 선형 size '0' = ok", "bybit", "futures_linear",
     {"/v5/position/list": lambda q: {"list": [{"symbol": "BTCUSDT", "side": "", "size": "0"}], "nextPageCursor": ""}}),
    ("OKX 선물 모드 liab·interest '' = ok '차입 없음'", "okx", "unified",
     {"/api/v5/account/balance": [{"mgnRatio": "", "mmr": "", "details": [{"ccy": "USDT", "liab": "", "interest": "", "crossLiab": ""}]}],
      "/api/v5/account/config": [{"acctLv": "2"}]}),
    ("OKX 포지션 빈 목록 = ok", "okx", "futures_linear", {"/api/v5/account/positions": []}),
    ("OKX 옵션만 = 범위 밖 ok n=0", "okx", "futures_inverse", {"/api/v5/account/positions": [{"instType": "OPTION", "instId": "BTC-USD-261231-1-C", "pos": "1"}]}),
    ("쿠코인 선물 수량 0 = ok", "kucoin", "futures_linear", {"/api/v1/positions": [{"symbol": "XBTUSDTM", "isOpen": False, "currentQty": 0}]}),
    ("게이트 통합 classic = ok", "gate", "unified", {"/api/v4/unified/accounts": {"mode": "classic"}}),
    ("게이트 통합 부채 0 = ok", "gate", "unified", {"/api/v4/unified/accounts": {"mode": "multi_currency", "unified_account_total_liab": "0", "balances": {}}}),
    ("게이트 교차 total_liab 만(interest 칸 없음 — 실측 모양) = ok", "gate", "margin_cross",
     {"/api/v4/margin/cross/accounts": {"balances": {"USDT": {"borrowed": "10", "total_liab": "10"}}}}),
    ("게이트 선물 size 0 = ok", "gate", "futures_linear", {"/api/v4/futures/usdt/positions": [{"contract": "BTC_USDT", "size": 0}]}),
]
for name, ex, product, over in ZERO:
    d = run(ex, over, prev=GOOD[ex], now=NOW + 600)
    p = prod(d, ex, product)
    its = items_of(d, ex, product)
    want_items = name.startswith("게이트 교차 total_liab")
    ok9 = p["status"] == "ok" and p["measured_at"] == NOW + 600 and all(not i["stale"] for i in its) and (bool(its) if want_items else True)
    check(name, ok9, (p["status"], p.get("err"), len(its)))
d = run("okx", {"/api/v5/account/balance": [{"mgnRatio": "", "mmr": "", "details": [{"ccy": "USDT", "liab": "", "interest": ""}]}],
                "/api/v5/account/config": [{"acctLv": "2"}]})
check("OKX 선물 모드 liab '' → 줄 0 · n=0", prod(d, "okx", "unified")["n"] == 0 and not items_of(d, "okx", "unified"))

print("[P] 퍼프 덱스 6곳 — 목록·행·수량 누락 = 주소 실패(직전 포지션·마지막 성공 시각 유지)")
PD.SLEEP = lambda s: None
for k in PD.DEXES:
    PD.DEXES[k]["pace"] = 0.0
import hl_spot as _HL
_HL.GOV = _HL.Gov(cap=10 ** 9, pace=0)
import re

EVM = "0x" + "12" * 20
SOL = "So11111111111111111111111111111111111111112"
DYDX = "dydx1ttp44s66cddvxkkrttp44s66cddvxkkrxefmdc"
T0 = 1700000000000
OLD_TS = NOW - 600


class PRouter:
    def __init__(self, rules):
        self.rules = [(re.compile(rx), fn) for rx, fn in rules]

    def __call__(self, url, body=None):
        key = url + ("  " + json.dumps(body, sort_keys=True) if body is not None else "")
        for rx, fn in self.rules:
            if rx.search(key):
                r = fn(url, body)
                if isinstance(r, Exception):
                    raise r
                return copy.deepcopy(r)
        raise PD.PerpHTTPError(404, "no route")


def seed(dex, addr):
    pos = {"symbol": "ETH-USD", "side": "LONG", "qty": 1.0, "entry": 100.0, "mark": 100.0, "upnl": 0.0, "leverage": 5.0, "liq": 50.0, "acct": addr}
    common.atomic_write_json(PD.fut_path(dex), {"v": PD.FILE_VER, "ts": OLD_TS, "dex": dex, "wallet": {}, "positions": [pos], "events": [],
                                                 "cursor": {}, "accts": {addr: {"label": "a", "ts": OLD_TS}}})


EMPTY_HIST = [(r"userFillsByTime|userFunding", lambda u, b: []), (r"/fills\?|/fundingPayments|/perpetualPositions|/historicalPnl|/transfers", lambda u, b: {"fills": [], "fundingPayments": [], "positions": [], "historicalPnl": [], "transfers": []}),
              (r"/trades\?", lambda u, b: {"trades": [], "dataList": [], "count": 0, "data": [], "has_more": False}),
              (r"tradeActions", lambda u, b: {"data": {"tradeActions": []}}), (r"/markets$", lambda u, b: {"markets": []}),
              (r"/tokens$", lambda u, b: {"tokens": []}), (r"/prices/tickers", lambda u, b: []),
              (r"/info/prices", lambda u, b: {"data": []}), (r"/account\?account", lambda u, b: {"data": {"account_equity": "1"}}),
              (r"/trades/history|/funding/history", lambda u, b: {"data": [], "has_more": False})]
HL_CH = {"assetPositions": [{"type": "oneWay", "position": {"coin": "ETH", "szi": "1", "entryPx": "100", "positionValue": "100", "liquidationPx": "50"}}],
         "marginSummary": {"accountValue": "10"}}
PCASES = [
    ("hyperliquid", EVM, "HL 응답 None", [(r"clearinghouseState", lambda u, b: None)]),
    ("hyperliquid", EVM, "HL assetPositions 칸 누락", [(r"clearinghouseState", lambda u, b: {"marginSummary": {"accountValue": "1"}})]),
    ("hyperliquid", EVM, "HL szi 누락", [(r"clearinghouseState", lambda u, b: mut(HL_CH, lambda d: d["assetPositions"][0]["position"].pop("szi")))]),
    ("hyperliquid", EVM, "HL position 칸 누락", [(r"clearinghouseState", lambda u, b: {"assetPositions": [{"type": "oneWay"}]})]),
    ("dydx", DYDX, "dYdX subaccounts 칸 누락", [(r"/addresses/", lambda u, b: {})]),
    ("dydx", DYDX, "dYdX size 누락", [(r"/addresses/", lambda u, b: {"subaccounts": [{"subaccountNumber": 0, "equity": "1",
                                                                                    "openPerpetualPositions": {"ETH-USD": {"market": "ETH-USD", "entryPrice": "100"}}}]})]),
    ("dydx", DYDX, "dYdX openPerpetualPositions 형식", [(r"/addresses/", lambda u, b: {"subaccounts": [{"subaccountNumber": 0, "openPerpetualPositions": []}]})]),
    ("lighter", EVM, "Lighter accounts 칸 누락", [(r"/account\?by=l1_address", lambda u, b: {"code": 200})]),
    ("lighter", EVM, "Lighter positions 칸 누락", [(r"/account\?by=l1_address", lambda u, b: {"accounts": [{"index": 1, "total_asset_value": "1"}]})]),
    ("lighter", EVM, "Lighter position 누락", [(r"/account\?by=l1_address", lambda u, b: {"accounts": [{"index": 1, "positions": [{"market_id": 0, "symbol": "ETH", "sign": 1}]}]})]),
    ("lighter", EVM, "Lighter sign 형식", [(r"/account\?by=l1_address", lambda u, b: {"accounts": [{"index": 1, "positions": [{"market_id": 0, "symbol": "ETH", "position": "1", "sign": "x"}]}]})]),
    ("gmx", EVM, "GMX GraphQL errors(data null)", [(r"positions\(", lambda u, b: {"errors": [{"message": "boom"}], "data": None})]),
    ("gmx", EVM, "GMX 마켓 모름(decimals 모름 — 조용히 빼지 않음)", [(r"positions\(", lambda u, b: {"data": {"positions": [{"market": "0xab", "isLong": True,
                                                                                                             "sizeInTokens": "1", "sizeInUsd": "1", "entryPrice": "1"}]}})]),
    ("jupiter", SOL, "Jupiter dataList 칸 누락", [(r"/positions\?walletAddress", lambda u, b: {"count": 0})]),
    ("jupiter", SOL, "Jupiter size 누락", [(r"/positions\?walletAddress", lambda u, b: {"dataList": [{"side": "long", "entryPrice": "100"}]})]),
    ("jupiter", SOL, "Jupiter entryPrice 누락", [(r"/positions\?walletAddress", lambda u, b: {"dataList": [{"side": "long", "size": "100"}]})]),
    ("pacifica", SOL, "Pacifica data 칸 누락", [(r"/positions\?account", lambda u, b: {"success": True})]),
    ("pacifica", SOL, "Pacifica success false", [(r"/positions\?account", lambda u, b: {"success": False, "data": [], "error": "x"})]),
    ("pacifica", SOL, "Pacifica amount 누락", [(r"/positions\?account", lambda u, b: {"success": True, "data": [{"symbol": "ETH", "side": "bid"}]})]),
    ("pacifica", SOL, "Pacifica side 형식", [(r"/positions\?account", lambda u, b: {"success": True, "data": [{"symbol": "ETH", "side": "?", "amount": "1"}]})]),
]
for dex, addr, name, rules in PCASES:
    seed(dex, addr)
    PD.HTTP = PRouter(rules + EMPTY_HIST)
    try:
        out, _ = PD.snapshot_dex(dex, [{"address": addr, "label": "a"}], T0, NOW)
    except Exception as e:
        out = common.read_json(PD.fut_path(dex), {})
        _ = e
    m = (out.get("accts") or {}).get(addr) or {}
    ok9 = bool(m.get("err")) and m.get("ts") == OLD_TS and len(out.get("positions") or []) == 1 and out["positions"][0]["qty"] == 1.0 and out.get("ts") == OLD_TS
    check(f"{dex}: {name} → 주소 err · ts 유지 · 직전 포지션 유지", ok9, (m, out.get("positions"), out.get("ts")))

print("[P2] 정상 빈 목록 = 성공(주소 ts 갱신 · 포지션 0)")
PZERO = [
    ("hyperliquid", EVM, "HL 빈 assetPositions", [(r"clearinghouseState", lambda u, b: {"assetPositions": [], "marginSummary": {"accountValue": "0"}})]),
    ("hyperliquid", EVM, "HL szi 0", [(r"clearinghouseState", lambda u, b: mut(HL_CH, lambda d: d["assetPositions"][0]["position"].update(szi="0")))]),
    ("dydx", DYDX, "dYdX 404(입금 전 주소)", [(r"/addresses/", lambda u, b: PD.PerpHTTPError(404, "nf"))]),
    ("dydx", DYDX, "dYdX 열린 포지션 없음", [(r"/addresses/", lambda u, b: {"subaccounts": [{"subaccountNumber": 0, "equity": "1", "openPerpetualPositions": {}}]})]),
    ("lighter", EVM, "Lighter 빈 positions · position 0", [(r"/account\?by=l1_address", lambda u, b: {"accounts": [{"index": 1, "positions": [
        {"market_id": 0, "symbol": "ETH", "position": "0.00", "sign": 0}]}]})]),
    ("gmx", EVM, "GMX 빈 positions", [(r"positions\(", lambda u, b: {"data": {"positions": []}})]),
    ("jupiter", SOL, "Jupiter 빈 dataList", [(r"/positions\?walletAddress", lambda u, b: {"dataList": [], "count": 0})]),
    ("pacifica", SOL, "Pacifica 빈 data", [(r"/positions\?account", lambda u, b: {"success": True, "data": []})]),
]
for dex, addr, name, rules in PZERO:
    seed(dex, addr)
    PD.HTTP = PRouter(rules + EMPTY_HIST)
    try:
        out, _ = PD.snapshot_dex(dex, [{"address": addr, "label": "a"}], T0, NOW)
    except Exception as e:
        out = {"accts": {addr: {"err": repr(e)}}}
    m = (out.get("accts") or {}).get(addr) or {}
    check(f"{dex}: {name} → 성공 · ts 갱신 · 포지션 0", not m.get("err") and m.get("ts") == NOW and out.get("positions") == [], (m, out.get("positions")))

print("[C] 소비 쪽(liq_watch · lev_view) — error 상품 = '모름'")
d_err = run("okx", {"/api/v5/account/positions": mut(O["/api/v5/account/positions"], lambda d: d[0].pop("pos"))}, prev=GOOD["okx"], now=NOW + 600)
import liq_watch as LW
lf = LW.lev_fresh(d_err, NOW + 610)
prod_ok, _ = LW.Watcher._lev_prod(lf)
pos_items = [i for i in lf["items"] if i["ex"] == "okx" and i["product"] == "futures_linear"]
check("liq_watch: 오류 상품은 prod_ok 밖(닫힘·잊기·해소 근거 아님)", ("okx", "futures_linear") not in prod_ok and ("okx", "unified") in prod_ok, sorted(prod_ok))
check("liq_watch: 승계 줄 fresh=False(진입 알림·해소 모두 막힘)", pos_items and all(i["fresh"] is False for i in pos_items), pos_items)
check("liq_watch: _lev_ok 통과(형식 정상 — 파일 전체를 '모름'으로 만들지 않음)", LW._lev_ok(lf))
import lev_view
L.write(d_err)
v = lev_view.build(L.read_state(NOW + 610), {}, lambda s: 1.0, 10.0, None, NOW + 610)
unc = {(u["ex"], u["product"]) for u in v["unconfirmed"]}
check("lev_view: 오류 상품 = '확인 못 한 곳'에 표시", ("okx", "futures_linear") in unc, v["unconfirmed"])

T.finish()
