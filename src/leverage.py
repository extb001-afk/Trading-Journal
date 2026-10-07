from __future__ import annotations

import math
import os
import time

import common

NAME = "leverage.json"
V = 1
NOPERM_COOL_SEC = 3600
DENY_COOL_SEC = 6 * 3600
CACHE_TTL = 24 * 3600
CACHE_KEEP = 7 * 24 * 3600
STALE_DROP = 3 * 24 * 3600
EPS = 1e-12

EX_KO = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX", "kucoin": "쿠코인", "gate": "게이트"}
PROD_KO = {"margin_cross": "교차마진", "margin_isolated": "격리마진", "loan": "담보대출",
           "futures_linear": "선물(USDT·USDC)", "futures_inverse": "선물(코인 정산)", "unified": "통합계정"}
EXCHANGES = ("binance", "bybit", "okx", "kucoin", "gate")
NEED = {"binance": ("TJ_BINANCE_KEY", "TJ_BINANCE_SECRET"), "bybit": ("TJ_BYBIT_KEY", "TJ_BYBIT_SECRET"),
        "okx": ("TJ_OKX_KEY", "TJ_OKX_SECRET", "TJ_OKX_PASSPHRASE"),
        "kucoin": ("TJ_KUCOIN_KEY", "TJ_KUCOIN_SECRET", "TJ_KUCOIN_PASSPHRASE"), "gate": ("TJ_GATE_KEY", "TJ_GATE_SECRET")}

DOC = {
    ("binance", "margin_cross"): "https://developers.binance.com/docs/margin_trading/account/Query-Cross-Margin-Account-Details",
    ("binance", "margin_isolated"): "https://developers.binance.com/docs/margin_trading/account/Query-Isolated-Margin-Account-Info",
    ("binance", "loan"): "https://developers.binance.com/docs/crypto_loan/flexible-rate/user-information/Get-Flexible-Loan-Ongoing-Orders",
    ("binance", "futures_linear"): "https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Position-Information-V2",
    ("binance", "futures_inverse"): "https://developers.binance.com/docs/derivatives/coin-margined-futures/trade/rest-api/Position-Information",
    ("binance", "unified"): "https://developers.binance.com/docs/derivatives/portfolio-margin/account/Account-Information",
    ("bybit", "unified"): "https://bybit-exchange.github.io/docs/v5/account/wallet-balance",
    ("bybit", "loan"): "https://bybit-exchange.github.io/docs/v5/new-crypto-loan/crypto-loan-position",
    ("bybit", "futures_linear"): "https://bybit-exchange.github.io/docs/v5/position",
    ("bybit", "futures_inverse"): "https://bybit-exchange.github.io/docs/v5/position",
    ("okx", "unified"): "https://www.okx.com/docs-v5/en/#trading-account-rest-api-get-balance",
    ("okx", "margin_cross"): "https://www.okx.com/docs-v5/en/#trading-account-rest-api-get-positions",
    ("okx", "margin_isolated"): "https://www.okx.com/docs-v5/en/#trading-account-rest-api-get-positions",
    ("okx", "loan"): "https://www.okx.com/docs-v5/en/#financial-product-flexible-loan-get-loan-info",
    ("okx", "futures_linear"): "https://www.okx.com/docs-v5/en/#trading-account-rest-api-get-positions",
    ("okx", "futures_inverse"): "https://www.okx.com/docs-v5/en/#trading-account-rest-api-get-positions",
    ("kucoin", "margin_cross"): "https://www.kucoin.com/docs-new/rest/account-info/account-funding/get-account-cross-margin",
    ("kucoin", "margin_isolated"): "https://www.kucoin.com/docs-new/rest/account-info/account-funding/get-account-isolated-margin",
    ("kucoin", "loan"): "https://www.kucoin.com/docs-new/rest/vip-lending/get-account-detail",
    ("kucoin", "futures_linear"): "https://www.kucoin.com/docs-new/rest/futures-trading/positions/get-position-list",
    ("kucoin", "futures_inverse"): "https://www.kucoin.com/docs-new/rest/futures-trading/positions/get-position-list",
    ("gate", "margin_isolated"): "https://www.gate.com/docs/developers/apiv4/#margin-account-list",
    ("gate", "margin_cross"): "https://www.gate.com/docs/developers/apiv4/#retrieve-cross-margin-account",
    ("gate", "unified"): "https://www.gate.com/docs/developers/apiv4/#get-unified-account-information",
    ("gate", "loan"): "https://www.gate.com/docs/developers/apiv4/#list-orders",
    ("gate", "futures_linear"): "https://www.gate.com/docs/developers/apiv4/#list-all-positions-of-a-user",
    ("gate", "futures_inverse"): "https://www.gate.com/docs/developers/apiv4/#list-all-positions-of-a-user",
}
DOC_BN_FUT_MR = "doc:https://www.binance.com/en/support/faq/binance-futures-liquidation-protocols-360033525271"
DOC_LIQ_PX = "doc:청산가 도달 = 강제 청산(정의)"
DOC_OKX_MGN = "doc:https://www.okx.com/docs-v5/en/#trading-account-rest-api-get-balance (mgnRatio ≤ 1.0 = 청산 경계)"
DOC_OKX_POS_MGN = "doc:https://www.okx.com/en-gb/help/iv-isolated-margin-mode (포지션 mgnRatio ≤ 100% = 청산)"
DOC_KC_FUT_RR = "doc:https://www.kucoin.com/docs-new/rest/account-info/account-funding/get-account-futures (riskRatio ≥ 100% = 청산)"

TJ_CALL_X = 0.8
TJ_DEFAULT = "tj:default-0.8"
JUDGE_METRICS = ("ltv", "margin_level", "mgn_ratio", "mm_rate", "debt_ratio", "risk_rate")
DOC_BN_FUT_CALL = DOC_BN_FUT_MR + " (100% = 청산 · '80% 아래 유지 권장')"
DOC_OKX_WARN = ("doc:https://www.okx.com/en-ae/help/what-is-the-leverage-gradient-maintenance-margin-system "
                "(증거금 비율 ≤ 300% 경고·포지션 축소 권고 · ≤ 100% 강제 청산)")
DOC_GATE_MULTI = ("doc:https://www.gate.com/help/unified-account/risk_control_mechanism/33015/multi-currency-margin-mode-risk-control-mechanism "
                  "(MMR ≤ 110% 부채 자동 상환 · ≤ 100% 청산)")
DOC_GATE_PM = ("doc:https://www.gate.com/help/unified-account/risk_control_mechanism/36096 "
               "(포트폴리오 마진: MMR = 증거금 잔고÷유지증거금 · ≤ 100% 청산 · 자동 상환 기준 없음)")
DOC_GATE_CROSS_EST = DOC_GATE_MULTI + " — 교차마진 계정에 통합계정 기준을 추정 적용(교차 응답 칸 이름·공식이 통합계정과 같음)"
DOC_BYBIT_LOAN = ("doc:https://www.bybit.com/en/help-center/article/Loan-to-Value-Ratio-and-Liquidation-Crypto-Loans "
                  "(통합 담보대출: 마진콜 85% · 지연 청산 93% · 청산 95% — 10-06 코덱스 108·공식 도움말 검색 결과 기준)")
BYBIT_LOAN_CALL, BYBIT_LOAN_LIQ = 0.85, 0.95
GATE_MULTI_CALL = 1.1
OKX_WARN_CALL = 3.0

DENY_SIGS = ('"code":-2015', '"code":-1002', "USER_NOT_FOUND", "HTTP 401", "HTTP 403", "HTTPError 401", "HTTPError 403",
             "retCode=10005", "retCode=10003", "retCode=10010", "okx 50120", "okx 50030", "okx 50125", "okx 50119",
             "okx 58350", "400007", "Access Denied", "FORBIDDEN", "Forbidden")
NOT_OPENED_SIGS = ('"code":-3003', '"code":-11001', "enable the margin trading", "open margin trade", "130201", "130306",
                   "130323", "has not opened", '"code":-21001', "USER_IS_NOT_UNIACCOUNT")
RATE_SIGS = ("HTTP 429", "HTTP 418", "retCode=10006", "okx 50011", "429000", "Too Many", "too frequent")


def num(x):
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, str):
        x = x.strip()
        if not x:
            return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def pos(x):
    v = num(x)
    return v if v is not None and v > EPS else None


class Unknown(ValueError):
    pass


def req_num(row, field, what):
    v = num(row.get(field)) if isinstance(row, dict) else None
    if v is None:
        raise Unknown(f"{what}: {field} 누락·숫자 형식 오류")
    return v


def opt_num(row, field, what):
    if not isinstance(row, dict) or field not in row:
        raise Unknown(f"{what}: {field} 칸 없음")
    v = row.get(field)
    if v is None:
        raise Unknown(f"{what}: {field} null(해당 없음 아님 — 모름)")
    if isinstance(v, str) and not v.strip():
        return None
    n = num(v)
    if n is None:
        raise Unknown(f"{what}: {field} 숫자 형식 오류")
    return n


def req_rows(obj, field, what, nonempty=False):
    rows = obj.get(field) if isinstance(obj, dict) else None
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise Unknown(f"{what}: {field} 목록 누락·행 형식 오류")
    if nonempty and not rows:
        raise Unknown(f"{what}: {field} 빈 목록(문서상 항상 1줄 이상)")
    return rows


def req_list(rows, what):
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise Unknown(f"{what}: 목록 형식 오류")
    return rows


def req_dict(obj, field, what):
    v = obj.get(field) if isinstance(obj, dict) else None
    if not isinstance(v, dict):
        raise Unknown(f"{what}: {field} 누락·형식 오류")
    return v


def req_ccy(v, what):
    c = str(v or "").strip().upper() if isinstance(v, str) else ""
    if not c:
        raise Unknown(f"{what}: 통화 이름 누락")
    return c


def debt_req(ccy, principal=None, interest=None, total=None, rate=None, rate_period=None, what=""):
    c = req_ccy(ccy, what)
    if total is None and principal is None:
        raise Unknown(f"{what}: {c} 부채 수량 모름")
    if any(x is not None and x < -EPS for x in (principal, interest, total)):
        raise Unknown(f"{what}: {c} 부채 수량 음수")
    return debt_row(c, principal, interest, total, rate, rate_period)


def coll_req(ccy, qty, what):
    c = req_ccy(ccy, what)
    if qty is None or qty < -EPS:
        raise Unknown(f"{what}: {c} 담보 수량 모름")
    return coll_row(c, qty)


def metric(v, unit, risk, *, warn=None, call=None, liq=None, thr_src="unknown", thr_at=None, src="", inf=False, liq_src=None):
    m = {"v": v, "unit": unit, "risk": risk, "warn": warn, "call": call, "liq": liq, "thr_src": thr_src}
    if thr_at:
        m["thr_at"] = int(thr_at)
    if src:
        m["src"] = src
    if liq_src and liq_src != thr_src:
        m["liq_src"] = liq_src
    if inf:
        m["v"], m["inf"] = None, True
    return m


def call_ok(m, c) -> bool:
    c, lq = num(c), num((m or {}).get("liq"))
    if c is None or c <= 0:
        return False
    if lq is None or lq <= 0:
        return True
    return c < lq if (m or {}).get("risk") != "down" else c > lq


def fill_call(m):
    if not isinstance(m, dict) or str(m.get("thr_src") or "unknown") == "unknown":
        return m
    if m.get("call") is not None and call_ok(m, m.get("call")):
        return m
    lq = num(m.get("liq"))
    if lq is None or lq <= 0:
        return m
    c = lq * TJ_CALL_X if m.get("risk") != "down" else lq / TJ_CALL_X
    if m.get("thr_src") != TJ_DEFAULT:
        m["liq_src"] = m.get("liq_src") or m.get("thr_src")
    m["call"], m["thr_src"] = round(c, 6), TJ_DEFAULT
    return m


def no_null(row, fields, what):
    for f9 in fields:
        if isinstance(row, dict) and f9 in row and row[f9] is None:
            raise Unknown(f"{what}: {f9} null(모름)")


def liq_dist(mark, liq, side):
    mark, liq = num(mark), num(liq)
    if not mark or mark <= 0 or not liq or liq <= 0 or side not in ("LONG", "SHORT"):
        return None
    return max(0.0, ((mark - liq) if side == "LONG" else (liq - mark)) / mark)


def debt_row(ccy, principal=None, interest=None, total=None, rate=None, rate_period=None):
    ccy = str(ccy or "").strip().upper()
    p, i, t = num(principal), num(interest), num(total)
    if t is None:
        t = (p or 0.0) + (i or 0.0) if (p is not None or i is not None) else None
    if not ccy or t is None or t <= EPS:
        return None
    return {"ccy": ccy, "principal": p, "interest": i, "total": t, "rate": num(rate), "rate_period": rate_period}


def coll_row(ccy, qty):
    ccy, q = str(ccy or "").strip().upper(), num(qty)
    return {"ccy": ccy, "qty": q} if ccy and q is not None and q > EPS else None


STATE_LEVEL = {"EXCESSIVE": 0, "NORMAL": 0, "MARGIN_CALL": 1, "PRE_LIQUIDATION": 2, "FORCE_LIQUIDATION": 3,
               "EFFECTIVE": 0, "BORROW": 0, "REPAY": 0, "LIQUIDATION": 3, "BANKRUPTCY": 3,
               "Normal": 0, "Liq": 3, "Adl": 3}


def official(v, src):
    if v in (None, ""):
        return None
    return {"v": str(v), "level": STATE_LEVEL.get(str(v)), "src": src}


def item(ex, product, scope, key, label, now, metrics=None, debt=None, collateral=None, position=None, raw=None, note=None,
         state=None):
    it = {"id": f"{ex}:{product}:{scope}:{key}", "ex": ex, "product": product, "scope": scope, "key": str(key),
          "label": label, "measured_at": int(now), "stale": False,
          "metrics": {k: v for k, v in (metrics or {}).items() if v and (v.get("v") is not None or v.get("inf"))}}
    for k9, m9 in it["metrics"].items():
        if k9 in JUDGE_METRICS:
            fill_call(m9)
    d = [x for x in (debt or []) if x]
    c = [x for x in (collateral or []) if x]
    if d:
        it["debt"] = d
    if c:
        it["collateral"] = c
    if position:
        it["position"] = position
    if raw:
        it["raw"] = {k: v for k, v in raw.items() if v not in (None, "")}
    if note:
        it["note"] = note
    if state:
        it["official_state"] = state
    return it


def classify(e) -> tuple:
    msg = common.safe_err(repr(e))[:200]
    if type(e).__name__ == "RateLimited" or any(s in msg for s in RATE_SIGS):
        return "rate_limited", msg
    if any(s in msg for s in NOT_OPENED_SIGS):
        return "not_opened", msg
    if any(s in msg for s in DENY_SIGS):
        return "no_permission", msg
    return "error", msg


def _side(v):
    s = str(v or "").strip().upper()
    return {"BUY": "LONG", "SELL": "SHORT", "LONG": "LONG", "SHORT": "SHORT"}.get(s)


def pos_item(ex, product, now, symbol, side, qty, qty_unit, entry, mark, liq, leverage, mode, upnl, settle,
             im=None, mm=None, raw=None, note=None, acct="", state=None):
    if not str(symbol or "").strip() or side not in ("LONG", "SHORT"):
        raise Unknown(f"{ex} {product} 포지션 심볼·방향 누락")
    lq = num(liq)
    lq = lq if lq and lq > 0 else None
    d = liq_dist(mark, lq, side)
    m = {}
    if d is not None:
        m["liq_dist"] = metric(round(d, 6), "frac", "down", liq=0.0, thr_src=DOC_LIQ_PX, src="mark·liq")
    p = {"symbol": str(symbol or ""), "side": side, "qty": abs(num(qty) or 0.0), "qty_unit": qty_unit,
         "entry": num(entry), "mark": num(mark), "liq": lq, "leverage": num(leverage),
         "margin_mode": mode if mode in ("cross", "isolated") else None, "upnl": num(upnl), "settle": settle,
         "im": num(im), "mm": num(mm)}
    key = f"{symbol}:{side}" + (f":{acct}" if acct else "")
    side_ko = {"LONG": "롱", "SHORT": "숏"}.get(side, "")
    return item(ex, product, "position", key, f"{symbol} {side_ko}".strip(), now, metrics=m, position=p, raw=raw, note=note, state=state)


def bybit_loan_thr(cfg):
    al = cfg.get("alerts") if isinstance(cfg, dict) else None
    lt = al.get("loan_ltv") if isinstance(al, dict) else None
    b = lt.get("bybit") if isinstance(lt, dict) else None
    if isinstance(b, dict):
        c, lq = num(b.get("call")), num(b.get("liq"))
        if c is not None and 0 < c < 1 and (lq is None or c < lq <= 1.5):
            return c, lq, "config:alerts.loan_ltv.bybit"
    return BYBIT_LOAN_CALL, BYBIT_LOAN_LIQ, DOC_BYBIT_LOAN


CACHE_FIELDS = {
    "binance:tradeCoeff": ("normalBar", "marginCallBar", "forceLiquidationBar"),
    "binance:crossMarginData:": ("coin", "dailyInterest", "yearlyInterest"),
    "binance:loanCollateral": {"rows": ("collateralCoin", "initialLTV", "marginCallLTV", "liquidationLTV")},
    "binance:loanable": {"rows": ("loanCoin", "flexibleInterestRate")},
    "bybit:account-info": ("marginMode", "unifiedMarginStatus"),
    "bybit:collateral-info:": {"list": ("currency", "hourlyBorrowRate")},
    "okx:account-config": ("acctLv",),
    "okx:interest-rate:": ("ccy", "interestRate"),
    "okx:loan-interest-accrued": ("ccy", "interest", "interestRate", "ts"),
    "kucoin:margin-config": ("warningDebtRatio", "liqDebtRatio", "maxLeverage"),
    "kucoin:borrowRate:": {"items": ("currency", "hourlyBorrowRate", "annualizedBorrowRate")},
    "kucoin:isolated-symbols": ("symbol", "flDebtRatio"),
    "gate:multi-ltv": ("init_ltv", "alert_ltv", "liquidate_ltv"),
}


def _proj_spec(key):
    for k9, sp in CACHE_FIELDS.items():
        if key == k9 or (k9.endswith(":") and key.startswith(k9)):
            return sp
    return None


def _proj(v, spec):
    if isinstance(spec, tuple):
        if isinstance(v, dict):
            return {k: v[k] for k in spec if k in v}
        if isinstance(v, list):
            return [{k: x[k] for k in spec if k in x} for x in v if isinstance(x, dict)]
        return None
    if isinstance(spec, dict) and isinstance(v, dict):
        return {c: _proj(v.get(c), sub) for c, sub in spec.items() if c in v}
    return None


def cache_proj(key, v):
    sp = _proj_spec(key)
    return None if sp is None or v is None else _proj(v, sp)


class Run:

    def __init__(self, prev: dict | None, now: int, cycle_sec: int = 600, fresh_sec: int = 1800, pace=None, cfg=None):
        self.prev = prev if isinstance(prev, dict) else {}
        self.cfg = cfg if isinstance(cfg, dict) else {}
        self.now = int(now)
        self.cycle_sec, self.fresh_sec = int(cycle_sec), int(fresh_sec)
        self.pace = pace or (lambda: None)
        self.products, self.items = [], []
        pp = self.prev.get("products") if isinstance(self.prev.get("products"), list) else []
        self._pprod = {(p.get("ex"), p.get("product")): p for p in pp if isinstance(p, dict)}
        pi = self.prev.get("items") if isinstance(self.prev.get("items"), list) else []
        self._pitems = {}
        for it in pi:
            if isinstance(it, dict):
                self._pitems.setdefault((it.get("ex"), it.get("product")), []).append(it)
        pc = self.prev.get("_cache")
        self.cache = dict(pc) if isinstance(pc, dict) else {}

    def cached(self, key: str, fn, ttl: int = CACHE_TTL):
        c = self.cache.get(key)
        at = int(c.get("at") or 0) if isinstance(c, dict) else 0
        if isinstance(c, dict) and self.now - at < ttl:
            return c.get("d"), at
        try:
            self.pace()
            d = cache_proj(key, fn())
            self.cache[key] = {"at": self.now, "d": d}
            return d, self.now
        except Exception as e:
            if isinstance(c, dict) and self.now - at < CACHE_KEEP:
                return c.get("d"), at
            self.cache[key] = {"at": 0, "fail_at": self.now, "d": None, "err": classify(e)[1][:120]}
            return None, None

    def _carry(self, ex, product):
        out = []
        for it in self._pitems.get((ex, product), []):
            try:
                age = self.now - int(it.get("measured_at") or 0)
            except (TypeError, ValueError):
                continue
            if age <= STALE_DROP:
                out.append(dict(it, stale=True))
        return out

    def _row(self, ex, product, status, endpoints=(), note=None, err=None, n=0, measured_at=None, retry_at=None):
        row = {"ex": ex, "product": product, "status": status, "checked_at": self.now, "measured_at": measured_at,
               "retry_at": retry_at, "n": n, "err": err, "endpoints": list(endpoints), "doc": DOC.get((ex, product), "")}
        if note:
            row["note"] = note
        self.products.append(row)
        return row

    def skip(self, ex, product, status, note, endpoints=()):
        return self._row(ex, product, status, endpoints, note=note)

    def run(self, ex, product, fn, endpoints=(), note_ok=None):
        pp = self._pprod.get((ex, product)) or {}
        ra = pp.get("retry_at")
        if (isinstance(ra, (int, float)) and self.now < ra <= self.now + DENY_COOL_SEC + 60
                and pp.get("status") in ("no_permission", "not_opened", "rate_limited")):
            carry = [] if pp.get("status") == "not_opened" else self._carry(ex, product)
            self.items.extend(carry)
            row = self._row(ex, product, pp.get("status"), endpoints, note=pp.get("note"), err=pp.get("err"),
                            n=len(carry), measured_at=pp.get("measured_at"), retry_at=int(ra))
            row["checked_at"] = pp.get("checked_at")
            return row
        try:
            r = fn()
            note = note_ok
            if isinstance(r, tuple):
                r, note = r
            its = [x for x in (r or []) if x]
            self.items.extend(its)
            return self._row(ex, product, "ok", endpoints, note=note, n=len(its), measured_at=self.now)
        except Exception as e:
            st, msg = classify(e)
            retry = None
            if st == "no_permission":
                retry = self.now + NOPERM_COOL_SEC
            elif st == "not_opened":
                retry = self.now + DENY_COOL_SEC
            elif st == "rate_limited":
                retry = self.now + max(600, self.cycle_sec)
            carry = [] if st == "not_opened" else self._carry(ex, product)
            self.items.extend(carry)
            note = {"no_permission": "키 권한 부족 또는 IP 불일치 — 1시간마다 다시 확인",
                    "not_opened": "상품 미개설 — 차입·포지션 없음(6시간마다 다시 확인)",
                    "rate_limited": "API 한도 백오프 중 — 다음 주기 재시도",
                    "error": "조회 실패 — 다음 주기 재시도(직전 값은 '낡음' 표시)"}.get(st)
            return self._row(ex, product, st, endpoints, note=note, err=msg, n=len(carry),
                             measured_at=pp.get("measured_at"), retry_at=retry)

    def result(self, extra: dict | None = None) -> dict:
        for k in list(self.cache):
            c = self.cache[k]
            if isinstance(c, dict):
                if _proj_spec(k) is None:
                    del self.cache[k]
                    continue
                self.cache[k] = dict(c, d=cache_proj(k, c.get("d")))
        for k in [k for k, c in self.cache.items()
                  if not isinstance(c, dict) or self.now - max(int(c.get("at") or 0), int(c.get("fail_at") or 0)) > CACHE_KEEP]:
            del self.cache[k]
        out = {"v": V, "ts": self.now, "cycle_sec": self.cycle_sec, "fresh_sec": self.fresh_sec,
               "products": self.products, "items": self.items, "_cache": self.cache}
        if extra:
            out.update(extra)
        return out


def _cross_syms(items):
    return {str((it.get("position") or {}).get("symbol") or "") for it in items
            if it.get("scope") == "position" and (it.get("position") or {}).get("margin_mode") != "isolated"}

def binance(run: Run, g: dict, now: int):
    ex = "binance"

    def coeff():
        d, at = run.cached("binance:tradeCoeff", lambda: g["sapi"]("/sapi/v1/margin/tradeCoeff", {}))
        return (d if isinstance(d, dict) else {}), at

    def cross():
        d = g["sapi"]("/sapi/v1/margin/account", {})
        if not isinstance(d, dict) or not isinstance(d.get("userAssets"), list):
            raise RuntimeError("binance margin account 응답 형식 오류(userAssets)")
        debt, coll = [], []
        W = "binance margin account"
        for a in req_rows(d, "userAssets", W):
            debt.append(debt_req(a.get("asset"), req_num(a, "borrowed", W), req_num(a, "interest", W), what=W))
            coll.append(coll_row(a.get("asset"), (num(a.get("free")) or 0.0) + (num(a.get("locked")) or 0.0)))
        debt = [x for x in debt if x]
        if not debt:
            return [], "차입 없음 확인"
        c, cat = coeff()
        rates = {}
        for r9 in debt:
            rd, _ = run.cached(f"binance:crossMarginData:{r9['ccy']}",
                               lambda c9=r9["ccy"]: g["sapi"]("/sapi/v1/margin/crossMarginData", {"coin": c9}))
            row = (rd[0] if isinstance(rd, list) and rd else rd) if rd else None
            if isinstance(row, dict) and num(row.get("dailyInterest")) is not None:
                r9["rate"], r9["rate_period"] = num(row.get("dailyInterest")), "day"
            rates[r9["ccy"]] = r9.get("rate")
        ml = num(d.get("marginLevel"))
        liab = num(d.get("totalLiabilityOfBtc"))
        m = {"margin_level": metric(ml, "x", "down", warn=num(c.get("normalBar")), call=num(c.get("marginCallBar")),
                                    liq=num(c.get("forceLiquidationBar")),
                                    thr_src="api:GET /sapi/v1/margin/tradeCoeff" if c else "unknown", thr_at=cat,
                                    src="marginLevel@GET /sapi/v1/margin/account", inf=bool(liab is not None and liab <= EPS))}
        raw = {"accountType": d.get("accountType"), "totalAssetOfBtc": num(d.get("totalAssetOfBtc")),
               "totalLiabilityOfBtc": liab, "collateralMarginLevel": num(d.get("collateralMarginLevel")),
               "tradeEnabled": d.get("tradeEnabled")}
        return [item(ex, "margin_cross", "account", "-", "바이낸스 교차마진", now, m, debt, coll, raw=raw)]

    def isolated():
        d = g["sapi"]("/sapi/v1/margin/isolated/account", {})
        if not isinstance(d, dict) or not isinstance(d.get("assets"), list):
            raise RuntimeError("binance isolated account 응답 형식 오류(assets)")
        out = []
        W = "binance isolated account"
        for p in req_rows(d, "assets", W):
            debt, coll = [], []
            for side in ("baseAsset", "quoteAsset"):
                a = req_dict(p, side, W)
                debt.append(debt_req(a.get("asset"), req_num(a, "borrowed", W), req_num(a, "interest", W), what=W))
                coll.append(coll_row(a.get("asset"), a.get("totalAsset")))
            debt = [x for x in debt if x]
            if not debt:
                continue
            sym = str(p.get("symbol") or "")
            m = {"margin_level": metric(num(p.get("marginLevel")), "x", "down", thr_src="unknown",
                                        src="marginLevel@GET /sapi/v1/margin/isolated/account")}
            bd9 = {x["ccy"] for x in debt}
            bc9, qc9 = str((p.get("baseAsset") or {}).get("asset") or "").upper(), str((p.get("quoteAsset") or {}).get("asset") or "").upper()
            pside9 = "SHORT" if bd9 == {bc9} else "LONG" if bd9 == {qc9} else None
            dd = liq_dist(p.get("indexPrice"), p.get("liquidatePrice"), pside9)
            if dd is not None:
                m["liq_dist"] = metric(round(dd, 6), "frac", "down", liq=0.0, thr_src=DOC_LIQ_PX, src="indexPrice·liquidatePrice")
            raw = {"marginLevelStatus": p.get("marginLevelStatus"), "liquidatePrice": num(p.get("liquidatePrice")),
                   "indexPrice": num(p.get("indexPrice")), "marginRatio": num(p.get("marginRatio")),
                   "liquidateRate": num(p.get("liquidateRate"))}
            out.append(item(ex, "margin_isolated", "pair", sym, f"바이낸스 격리마진 {sym}", now, m, debt, coll, raw=raw,
                            note="격리 청산 기준은 레버리지 구간별 — 거래소 상태(marginLevelStatus)·청산가로 판단",
                            state=official(p.get("marginLevelStatus"), "marginLevelStatus@GET /sapi/v1/margin/isolated/account")))
        return out, (None if out else "차입 없음 확인")

    def loan():
        rows, page = [], 1
        while page <= 20:
            d = g["sapi"]("/sapi/v2/loan/flexible/ongoing/orders", {"current": page, "limit": 100})
            if not isinstance(d, dict) or not isinstance(d.get("rows"), list):
                raise RuntimeError("binance flexible loan 응답 형식 오류(rows)")
            rows.extend(req_rows(d, "rows", "binance flexible loan"))
            if len(d["rows"]) < 100:
                break
            page += 1
            run.pace()
        else:
            raise RuntimeError("binance flexible loan 20페이지 초과")
        if not rows:
            return [], "대출 없음 확인"
        cd, cat = run.cached("binance:loanCollateral", lambda: g["sapi"]("/sapi/v2/loan/flexible/collateral/data", {}))
        ld, _ = run.cached("binance:loanable", lambda: g["sapi"]("/sapi/v2/loan/flexible/loanable/data", {}))
        cmap = {str(r.get("collateralCoin") or "").upper(): r for r in ((cd or {}).get("rows") or []) if isinstance(r, dict)} \
            if isinstance(cd, dict) else {}
        lmap = {str(r.get("loanCoin") or "").upper(): r for r in ((ld or {}).get("rows") or []) if isinstance(r, dict)} \
            if isinstance(ld, dict) else {}
        out = []
        for i, r in enumerate(rows):
            cc, lc = str(r.get("collateralCoin") or "").upper(), str(r.get("loanCoin") or "").upper()
            th = cmap.get(cc) or {}
            m = {"ltv": metric(num(r.get("currentLTV")), "frac", "up", call=num(th.get("marginCallLTV")),
                               liq=num(th.get("liquidationLTV")),
                               thr_src="api:GET /sapi/v2/loan/flexible/collateral/data" if th else "unknown", thr_at=cat if th else None,
                               src="currentLTV@GET /sapi/v2/loan/flexible/ongoing/orders")}
            rate = num((lmap.get(lc) or {}).get("flexibleInterestRate"))
            W = "binance flexible loan"
            dr = debt_req(r.get("loanCoin"), total=req_num(r, "totalDebt", W), rate=rate, rate_period=None, what=W)
            out.append(item(ex, "loan", "loan", f"{lc}-{cc}", f"바이낸스 담보대출 {lc}←{cc}", now, m, [dr],
                            [coll_req(r.get("collateralCoin"), req_num(r, "collateralAmount", W), W)],
                            raw={"initialLTV": num(th.get("initialLTV"))},
                            note="부채 = 원금+이자 합(거래소가 따로 안 줌) · 이자율 단위 문서 미기재"))
        return out

    def fut_linear():
        acct = g["fapi"]("/fapi/v2/account", {})
        run.pace()
        rows = g["fapi"]("/fapi/v2/positionRisk", {})
        if not isinstance(acct, dict) or not isinstance(rows, list):
            raise RuntimeError("binance 선물 응답 형식 오류")
        out = []
        for p in req_list(rows, "binance positionRisk"):
            amt = req_num(p, "positionAmt", "binance positionRisk")
            if abs(amt) <= EPS:
                continue
            side = "LONG" if amt > 0 else "SHORT"
            mode = str(p.get("marginType") or "").lower() or None
            out.append(pos_item(ex, "futures_linear", now, p.get("symbol"), side, amt, "coin", p.get("entryPrice"),
                                p.get("markPrice"), p.get("liquidationPrice"), p.get("leverage"), mode,
                                p.get("unRealizedProfit"), "USDT",
                                raw={"positionSide": p.get("positionSide"), "isolatedMargin": num(p.get("isolatedMargin")),
                                     "notional": num(p.get("notional"))},
                                acct=("" if str(p.get("positionSide") or "BOTH") == "BOTH" else str(p.get("positionSide")))))
        mb, mt = num(acct.get("totalMarginBalance")), num(acct.get("totalMaintMargin"))
        cross_mm = cmb = None
        if out or (mt and mt > EPS):
            W = "binance USDⓈ-M account"
            vals, seen_cross = [], set()
            for a in req_rows(acct, "positions", W):
                if not isinstance(a.get("isolated"), bool):
                    raise Unknown(f"{W}: positions.isolated 형식 오류")
                if a["isolated"]:
                    continue
                v9 = req_num(a, "maintMargin", W)
                if v9 < 0:
                    raise Unknown(f"{W}: 교차 maintMargin 음수")
                seen_cross.add(str(a.get("symbol") or ""))
                vals.append(v9)
            if not _cross_syms(out) <= seen_cross:
                raise Unknown(f"{W}: 교차 포지션의 계정 줄 없음")
            cross_mm = sum(vals)
            cmb = req_num(acct, "totalCrossWalletBalance", W) + req_num(acct, "totalCrossUnPnl", W)
            m = {}
            mr9 = (None if cross_mm is None else 0.0 if cross_mm <= EPS else None if cmb is None
                   else round(cross_mm / cmb, 6) if cmb > EPS else 10.0)
            if mr9 is not None:
                m["mm_rate"] = metric(mr9, "frac", "up", call=0.8, liq=1.0, thr_src=DOC_BN_FUT_CALL,
                                      src="교차 maintMargin 합÷(totalCrossWalletBalance+totalCrossUnPnl)@GET /fapi/v2/account")
            out.insert(0, item(ex, "futures_linear", "account", "-", "바이낸스 USDⓈ-M 선물 계정", now, m,
                               raw={"totalMarginBalance": mb, "totalMaintMargin": mt, "crossMaintMargin": cross_mm, "crossMarginBalance": cmb,
                                    "totalInitialMargin": num(acct.get("totalInitialMargin"))}))
        return out, (None if out else "포지션 없음 확인")

    def fut_inverse():
        rows = g["dapi"]("/dapi/v1/positionRisk", {})
        if not isinstance(rows, list):
            raise RuntimeError("binance COIN-M 응답 형식 오류")
        out = []
        for p in req_list(rows, "binance COIN-M positionRisk"):
            amt = req_num(p, "positionAmt", "binance COIN-M positionRisk")
            if abs(amt) <= EPS:
                continue
            side = "LONG" if amt > 0 else "SHORT"
            sym = str(p.get("symbol") or "")
            out.append(pos_item(ex, "futures_inverse", now, sym, side, amt, "contract", p.get("entryPrice"), p.get("markPrice"),
                                p.get("liquidationPrice"), p.get("leverage"), str(p.get("marginType") or "").lower() or None,
                                p.get("unRealizedProfit"), sym.split("USD")[0] if "USD" in sym else None,
                                raw={"positionSide": p.get("positionSide"), "isolatedMargin": num(p.get("isolatedMargin"))},
                                acct=("" if str(p.get("positionSide") or "BOTH") == "BOTH" else str(p.get("positionSide")))))
        cross9 = _cross_syms(out)
        if cross9:
            run.pace()
            out = coinm_account(g["dapi"]("/dapi/v1/account", {}), now, cross9) + out
        return out, (None if out else "포지션 없음 확인")

    def coinm_account(acct, now9, cross9=frozenset()):
        W = "binance COIN-M account"
        if not isinstance(acct, dict):
            raise Unknown(f"{W}: 응답 형식 오류")
        bal = {}
        for a in req_rows(acct, "assets", W):
            bal[req_ccy(a.get("asset"), W)] = req_num(a, "crossWalletBalance", W) + req_num(a, "crossUnPnl", W)
        cmm, seen9 = {}, set()
        for p in req_rows(acct, "positions", W):
            if not isinstance(p.get("isolated"), bool):
                raise Unknown(f"{W}: positions.isolated 형식 오류")
            mm9 = req_num(p, "maintMargin", W)
            if mm9 < 0:
                raise Unknown(f"{W}: maintMargin 음수")
            sym9 = str(p.get("symbol") or "")
            if p["isolated"] or (mm9 <= EPS and sym9 not in cross9):
                continue
            seen9.add(sym9)
            base9 = sym9.split("USD")[0].upper() if "USD" in sym9 else ""
            if not base9:
                raise Unknown(f"{W}: 증거금 코인 모름({sym9[:20]})")
            cmm[base9] = cmm.get(base9, 0.0) + mm9
        if not set(cross9) <= seen9:
            raise Unknown(f"{W}: 교차 포지션의 계정 줄 없음")
        items = []
        for c9, mm9 in sorted(cmm.items()):
            if c9 not in bal:
                raise Unknown(f"{W}: {c9} 증거금 잔고 줄 없음")
            b9 = bal[c9]
            v9 = 0.0 if mm9 <= EPS else round(mm9 / b9, 6) if b9 > EPS else 10.0
            items.append(item(ex, "futures_inverse", "account", c9, f"바이낸스 COIN-M 선물 계정 {c9}", now9,
                              {"mm_rate": metric(v9, "frac", "up", call=0.8, liq=1.0, thr_src=DOC_BN_FUT_CALL,
                                                 src="교차 maintMargin 합÷(crossWalletBalance+crossUnPnl)@GET /dapi/v1/account")},
                              raw={"crossMaintMargin": round(mm9, 8), "crossMarginBalance": round(b9, 8)},
                              note="증거금 코인별 교차 유지증거금률(교차 포지션의 청산 기준)"))
        return items

    run.run(ex, "margin_cross", cross, ["GET /sapi/v1/margin/account", "GET /sapi/v1/margin/tradeCoeff (하루 1번)",
                                        "GET /sapi/v1/margin/crossMarginData (차입 통화만 · 하루 1번)"])
    run.pace()
    run.run(ex, "margin_isolated", isolated, ["GET /sapi/v1/margin/isolated/account"])
    run.pace()
    run.run(ex, "loan", loan, ["GET /sapi/v2/loan/flexible/ongoing/orders", "GET /sapi/v2/loan/flexible/collateral/data (대출 있을 때 · 하루 1번)",
                               "GET /sapi/v2/loan/flexible/loanable/data (대출 있을 때 · 하루 1번)"])
    run.pace()
    fl = run.run(ex, "futures_linear", fut_linear, ["GET /fapi/v2/account", "GET /fapi/v2/positionRisk"])
    run.pace()
    run.run(ex, "futures_inverse", fut_inverse, ["GET /dapi/v1/positionRisk", "GET /dapi/v1/account (교차 포지션 있을 때)"])
    if fl.get("status") == "ok":
        run.skip(ex, "unified", "unsupported", "포트폴리오 마진 계정 아님(일반 선물 API 정상 응답 — PM 이면 /fapi 불가)")
    else:
        run.skip(ex, "unified", "not_collected", "포트폴리오 마진 여부 미확인(선물 조회 실패) — PM 계정이면 /papi/v1/account 수집 필요")


def bybit(run: Run, g: dict, now: int):
    ex = "bybit"

    def unified():
        res = g["get"]("/v5/account/wallet-balance", {"accountType": "UNIFIED"})
        W = "bybit wallet-balance"
        lst = req_rows(res, "list", W, nonempty=True)
        info, iat = run.cached("bybit:account-info", lambda: g["get"]("/v5/account/info", {}))
        mode = (info or {}).get("marginMode") if isinstance(info, dict) else None
        out = []
        for a in lst:
            debt = []
            for c in req_rows(a, "coin", W):
                debt.append(debt_req(c.get("coin"), req_num(c, "borrowAmount", W), opt_num(c, "accruedInterest", W), what=W))
            debt = [x for x in debt if x]
            mm = opt_num(a, "totalMaintenanceMargin", W)
            if not debt and not (mm and mm > EPS):
                continue
            for r9 in debt:
                rd, _ = run.cached(f"bybit:collateral-info:{r9['ccy']}",
                                   lambda c9=r9["ccy"]: g["get"]("/v5/account/collateral-info", {"currency": c9}))
                rr = ((rd or {}).get("list") or [None])[0] if isinstance(rd, dict) else None
                if isinstance(rr, dict) and num(rr.get("hourlyBorrowRate")) is not None:
                    r9["rate"], r9["rate_period"] = num(rr.get("hourlyBorrowRate")), "hour"
            m = {"mm_rate": metric(num(a.get("accountMMRate")), "frac", "up", liq=1.0,
                                   thr_src="doc:https://www.bybit.com/en/help-center/article/Glossary-Unified-Trading-Account (유지증거금률 100% = 청산)",
                                   src="accountMMRate@GET /v5/account/wallet-balance"),
                 "im_rate": metric(num(a.get("accountIMRate")), "frac", "up", thr_src="unknown",
                                   src="accountIMRate@GET /v5/account/wallet-balance")}
            raw = {"marginMode": mode, "totalEquity": num(a.get("totalEquity")), "totalMarginBalance": num(a.get("totalMarginBalance")),
                   "totalMaintenanceMargin": mm, "totalInitialMargin": num(a.get("totalInitialMargin"))}
            out.append(item(ex, "unified", "account", "UNIFIED", "바이빗 통합계정", now, m, debt, raw=raw,
                            note="차입 = borrowAmount(현물+파생 부채) · 이자 = accruedInterest"))
        return out, (None if out else "차입·증거금 사용 없음 확인")

    def loan():
        res = g["get"]("/v5/crypto-loan-common/position", {})
        if not isinstance(res, dict):
            raise RuntimeError("bybit crypto-loan position 형식 오류")
        W = "bybit crypto-loan position"
        bl, cl = req_rows(res, "borrowList", W), req_rows(res, "collateralList", W)
        debt = []
        flex = False
        fixed_ccys = set()
        for r in bl:
            fx, fl = (opt_num(r, f9, W) if f9 in r else None for f9 in ("fixedTotalDebt", "flexibleTotalDebt"))
            if fx is None and fl is None:
                raise Unknown(f"{W}: fixedTotalDebt·flexibleTotalDebt 둘 다 없음")
            if fl and fl > EPS:
                flex = True
            has_fx = bool(fx and fx > EPS)
            if has_fx:
                fixed_ccys.add(str(r.get("loanCurrency") or "").strip().upper())
            rt9 = None if has_fx else num(r.get("flexibleHourlyInterestRate"))
            debt.append(debt_req(r.get("loanCurrency"), total=(fx or 0.0) + (fl or 0.0), rate=rt9, rate_period="hour" if rt9 is not None else None, what=W))
        debt = [x for x in debt if x]
        coll = [coll_req(r.get("currency"), req_num(r, "amount", W), W) for r in cl]
        coll = [x for x in coll if x]
        if not debt and not coll:
            return [], "대출 없음 확인"
        if flex:
            try:
                run.pace()
                fr = g["get"]("/v5/crypto-loan-flexible/ongoing-coin", {})
                fl9 = fr.get("list") if isinstance(fr, dict) else None
                split = {}
                for r in (fl9 or []):
                    if not isinstance(r, dict):
                        continue
                    c9 = str(r.get("loanCurrency") or "").upper()
                    if num(r.get("unpaidAmount")) is not None and c9 not in fixed_ccys:
                        a9 = split.setdefault(c9, [0.0, 0.0])
                        a9[0] += num(r.get("unpaidAmount"))
                        a9[1] += num(r.get("unpaidInterest")) or 0.0
                for d9 in debt:
                    pi9 = split.get(d9["ccy"])
                    if pi9 and abs(pi9[0] + pi9[1] - d9["total"]) <= max(1e-6, 1e-3 * d9["total"]):
                        d9["principal"], d9["interest"] = pi9[0], pi9[1]
            except Exception:
                pass
        call9, liq9, src9 = bybit_loan_thr(run.cfg)
        m = {"ltv": metric(num(res.get("ltv")), "frac", "up", call=call9, liq=liq9, thr_src=src9,
                           src="ltv@GET /v5/crypto-loan-common/position")}
        raw = {"totalDebtUSD": num(res.get("totalDebt")), "totalCollateralUSD": num(res.get("totalCollateral"))}
        return [item(ex, "loan", "loan", "-", "바이빗 담보대출", now, m, debt, coll, raw=raw,
                     note=("마진콜·청산 LTV = 내 설정(alerts.loan_ltv.bybit)" if src9.startswith("config:")
                           else "마진콜·청산 LTV 는 API 에 없음 — 공식 도움말 수치(85% · 95%)"))]

    def positions(category, settle):
        out, params, seen = [], {"category": category, "limit": 200}, set()
        if settle:
            params["settleCoin"] = settle
        while True:
            res = g["get"]("/v5/position/list", params)
            rows = req_rows(res, "list", "bybit position list")
            out.extend(rows)
            cur = res.get("nextPageCursor") or ""
            if not cur or not rows:
                break
            if cur in seen:
                raise RuntimeError("bybit position 페이지 커서 미전진")
            seen.add(cur)
            params = dict(params, cursor=cur)
            run.pace()
        return out

    def to_items(rows, product, unit, settle):
        out = []
        for p in rows:
            sz = req_num(p, "size", "bybit position list")
            if abs(sz) <= EPS:
                continue
            side = _side(p.get("side"))
            ps = p.get("positionIdx")
            out.append(pos_item(ex, product, now, p.get("symbol"), side, sz, unit, p.get("avgPrice"), p.get("markPrice"),
                                p.get("liqPrice"), p.get("leverage"), None, p.get("unrealisedPnl"), settle or p.get("symbol", "")[:3],
                                im=p.get("positionIM"), mm=p.get("positionMM"),
                                raw={"positionStatus": p.get("positionStatus"), "adlRankIndicator": num(p.get("adlRankIndicator")),
                                     "autoAddMargin": p.get("autoAddMargin")},
                                note="교차 증거금의 청산가는 거래소 추정치(계정 단위 위험 = 통합계정 유지증거금률)",
                                acct=str(ps) if ps not in (None, 0, "0") else "",
                                state=official(p.get("positionStatus"), "positionStatus@GET /v5/position/list")))
        return out

    def fut_linear():
        rows = positions("linear", "USDT")
        run.pace()
        rows_c = positions("linear", "USDC")
        out = to_items(rows, "futures_linear", "coin", "USDT") + to_items(rows_c, "futures_linear", "coin", "USDC")
        return out, (None if out else "포지션 없음 확인")

    def fut_inverse():
        out = to_items(positions("inverse", None), "futures_inverse", "usd", None)
        return out, (None if out else "포지션 없음 확인")

    run.run(ex, "unified", unified, ["GET /v5/account/wallet-balance?accountType=UNIFIED", "GET /v5/account/info (하루 1번)",
                                     "GET /v5/account/collateral-info (차입 통화만 · 하루 1번)"])
    run.pace()
    run.run(ex, "loan", loan, ["GET /v5/crypto-loan-common/position", "GET /v5/crypto-loan-flexible/ongoing-coin (변동 대출 있을 때)"])
    run.pace()
    run.run(ex, "futures_linear", fut_linear, ["GET /v5/position/list?category=linear&settleCoin=USDT", "… settleCoin=USDC"])
    run.pace()
    run.run(ex, "futures_inverse", fut_inverse, ["GET /v5/position/list?category=inverse"])
    run.skip(ex, "margin_cross", "unsupported", "통합계정(UTA)에 포함 — 현물 차입·이자는 '통합계정' 줄")


def okx(run: Run, g: dict, now: int):
    ex = "okx"
    pos_rows = {}

    def unified():
        rows = g["get"]("/api/v5/account/balance", {})
        W = "okx balance"
        if not req_list(rows, W):
            raise Unknown(f"{W}: data 빈 목록(문서상 계정 1줄)")
        cfg, _ = run.cached("okx:account-config", lambda: g["get"]("/api/v5/account/config", {}))
        lv = None
        if isinstance(cfg, list) and cfg and isinstance(cfg[0], dict):
            lv = cfg[0].get("acctLv")
        out = []
        for a in rows:
            debt = []
            for c in req_rows(a, "details", W):
                cm9 = num(c.get("mgnRatio"))
                if cm9 is not None and cm9 > 0:
                    c9 = str(c.get("ccy") or "").upper()
                    out.append(item(ex, "unified", "ccy", c9, f"OKX 교차 증거금 {c9}", now,
                                    {"mgn_ratio": metric(cm9, "x", "down", call=OKX_WARN_CALL, liq=1.0, thr_src=DOC_OKX_WARN, liq_src=DOC_OKX_MGN,
                                                        src="details.mgnRatio@GET /api/v5/account/balance")},
                                    raw={"notionalLever": num(c.get("notionalLever")), "upl": num(c.get("upl"))}))
                lb9 = opt_num(c, "liab", W)
                d9 = debt_req(c.get("ccy"), interest=num(c.get("interest")), total=lb9, what=W) if lb9 is not None else None
                if d9:
                    d9["principal"] = None
                    debt.append(d9)
            no_null(a, ("mgnRatio", "mmr"), W)
            mr = num(a.get("mgnRatio"))
            mmr = num(a.get("mmr"))
            if not debt and not (mr is not None and mmr and mmr > EPS):
                continue
            for r9 in debt:
                rd, _ = run.cached(f"okx:interest-rate:{r9['ccy']}", lambda c9=r9["ccy"]: g["get"]("/api/v5/account/interest-rate", {"ccy": c9}))
                rr = rd[0] if isinstance(rd, list) and rd and isinstance(rd[0], dict) else None
                if rr and num(rr.get("interestRate")) is not None:
                    r9["rate"], r9["rate_period"] = num(rr.get("interestRate")), "hour"
            m = {}
            if mr is not None:
                m["mgn_ratio"] = metric(mr, "x", "down", call=OKX_WARN_CALL, liq=1.0, thr_src=DOC_OKX_WARN, liq_src=DOC_OKX_MGN,
                                        src="mgnRatio@GET /api/v5/account/balance")
            raw = {"acctLv": lv, "totalEq": num(a.get("totalEq")), "adjEq": num(a.get("adjEq")), "imr": num(a.get("imr")), "mmr": mmr}
            out.append(item(ex, "unified", "account", "-", "OKX 트레이딩 계정", now, m, debt, raw=raw,
                            note="부채 = liab(원문) · 이자 = 아직 차감 안 된 누적 이자(interest)"))
        return out, (None if out else ("차입 없음 확인" + (f" · 계정 모드 {lv}" if lv else "")))

    def loan():
        rows = g["get"]("/api/v5/finance/flexible-loan/loan-info", {})
        W = "okx loan-info"
        out = []
        for i, r in enumerate(req_list(rows, W)):
            debt = [debt_req(c.get("ccy"), total=req_num(c, "amt", W), what=W) for c in req_rows(r, "loanData", W)]
            coll = [coll_req(c.get("ccy"), req_num(c, "amt", W), W) for c in req_rows(r, "collateralData", W)]
            debt, coll = [x for x in debt if x], [x for x in coll if x]
            if not debt and not coll:
                continue
            if debt:
                ia, _ = run.cached("okx:loan-interest-accrued", lambda: g["get"]("/api/v5/finance/flexible-loan/interest-accrued", {"limit": "100"}))
                try:
                    run.pace()
                    hist = g["get"]("/api/v5/finance/flexible-loan/loan-history", {"limit": "100"})
                except Exception:
                    hist = None
                rate, isum = {}, {}
                for x in (ia if isinstance(ia, list) else []):
                    if isinstance(x, dict):
                        c9 = str(x.get("ccy") or "").upper()
                        if c9 not in rate and num(x.get("interestRate")) is not None:
                            rate[c9] = num(x.get("interestRate"))
                        isum[c9] = isum.get(c9, 0.0) + (num(x.get("interest")) or 0.0)
                prin, bad = {}, not isinstance(hist, list) or len(hist) >= 100
                for h in (hist if isinstance(hist, list) else []):
                    if not isinstance(h, dict):
                        continue
                    t9 = str(h.get("type") or "")
                    if t9 in ("borrowed", "repaid"):
                        a9 = num(h.get("amt"))
                        if a9 is None:
                            bad = True
                            continue
                        c9 = str(h.get("ccy") or "").upper()
                        prin[c9] = prin.get(c9, 0.0) + (abs(a9) if t9 == "borrowed" else -abs(a9))
                    elif t9.startswith("forced_") or t9 in ("partial_liquidation", "sell_collateral"):
                        bad = True
                for d9 in debt:
                    if d9["ccy"] in rate:
                        d9["rate"], d9["rate_period"] = rate[d9["ccy"]], "year"
                    p9 = prin.get(d9["ccy"])
                    if not bad and p9 is not None and 0 < p9 <= d9["total"] + EPS:
                        d9["principal"], d9["interest"] = p9, max(0.0, d9["total"] - p9)
            rw = r.get("riskWarningData") if isinstance(r.get("riskWarningData"), dict) else {}
            m = {"ltv": metric(num(r.get("curLTV")), "frac", "up", call=num(r.get("marginCallLTV")), liq=num(r.get("liqLTV")),
                               thr_src="api:GET /api/v5/finance/flexible-loan/loan-info",
                               src="curLTV@GET /api/v5/finance/flexible-loan/loan-info")}
            raw = {"liqPx": num(rw.get("liqPx")), "liqPair": rw.get("instId"), "loanNotionalUsd": num(r.get("loanNotionalUsd")),
                   "collateralNotionalUsd": num(r.get("collateralNotionalUsd"))}
            key = str(r.get("ordId") or i)
            out.append(item(ex, "loan", "loan", key, "OKX 담보대출", now, m, debt, coll, raw=raw,
                            note="이자율 = 최근 이자 기록의 연율(APY) · 원금 = 대출 이력(차입−상환) — 이력이 100건 넘거나 청산 정리가 있으면 원금 미표시"))
        return out, (None if out else "대출 없음 확인")

    def load_positions():
        if "rows" not in pos_rows:
            rows = g["get"]("/api/v5/account/positions", {})
            pos_rows["rows"] = req_list(rows, "okx positions")
        return pos_rows["rows"]

    def kind_of(p):
        it = str(p.get("instType") or "").upper()
        iid = str(p.get("instId") or "")
        parts = iid.split("-")
        if not it:
            it = "SWAP" if iid.endswith("-SWAP") else ("MARGIN" if len(parts) == 2 else ("FUTURES" if len(parts) == 3 else ""))
        if it == "MARGIN":
            return "margin_cross" if str(p.get("mgnMode") or "") == "cross" else "margin_isolated"
        if it in ("SWAP", "FUTURES"):
            return "futures_linear" if len(parts) > 1 and parts[1] in ("USDT", "USDC", "USDG") else "futures_inverse"
        if it == "OPTION":
            return None
        raise Unknown(f"okx positions: 모르는 instType {it[:20]!r}")

    def okx_pos(product):
        out = []
        for p in load_positions():
            if kind_of(p) != product:
                continue
            q = req_num(p, "pos", "okx positions")
            if abs(q) <= EPS:
                continue
            ps = str(p.get("posSide") or "")
            bq9 = str(p.get("instId") or "").split("-")
            if product.startswith("margin"):
                pc9 = str(p.get("posCcy") or "")
                side = ("LONG" if pc9 == bq9[0] else "SHORT" if len(bq9) > 1 and pc9 == bq9[1] else None) if pc9 \
                    else (ps.upper() if ps in ("long", "short") else None)
            else:
                side = ps.upper() if ps in ("long", "short") else (("LONG" if q > 0 else "SHORT") if ps == "net" else None)
            if side is None:
                raise Unknown("okx positions: 방향 모름(posSide·posCcy)")
            iid = str(p.get("instId") or "")
            if product.startswith("margin"):
                it = pos_item(ex, product, now, iid, side, q, "coin", p.get("avgPx"), p.get("markPx"), p.get("liqPx"), p.get("lever"),
                              p.get("mgnMode"), p.get("upl"), p.get("ccy"), im=p.get("imr"), mm=p.get("mmr"),
                              raw={"mgnRatio": num(p.get("mgnRatio")), "liabCcy": p.get("liabCcy")})
                _okx_mgn(it, p)
                d9 = debt_row(p.get("liabCcy"), interest=p.get("interest"), total=p.get("liab"))
                if d9:
                    d9["principal"] = None
                    it["debt"] = [d9]
                it["scope"], it["id"] = "pair", it["id"].replace(":position:", ":pair:")
                out.append(it)
            else:
                out.append(_okx_mgn(pos_item(ex, product, now, iid, side, q, "contract", p.get("avgPx"), p.get("markPx"), p.get("liqPx"),
                                             p.get("lever"), p.get("mgnMode"), p.get("upl"), p.get("ccy"), im=p.get("imr"), mm=p.get("mmr"),
                                             raw={"mgnRatio": num(p.get("mgnRatio")), "adl": num(p.get("adl")), "notionalUsd": num(p.get("notionalUsd"))},
                                             acct=(ps if ps in ("long", "short") else "")), p))
        return out, (None if out else "포지션 없음 확인")

    run.run(ex, "unified", unified, ["GET /api/v5/account/balance", "GET /api/v5/account/config (하루 1번)",
                                     "GET /api/v5/account/interest-rate (차입 통화만 · 하루 1번)"])
    run.pace()
    run.run(ex, "loan", loan, ["GET /api/v5/finance/flexible-loan/loan-info",
                               "GET /api/v5/finance/flexible-loan/interest-accrued (대출 있을 때 · 하루 1번)",
                               "GET /api/v5/finance/flexible-loan/loan-history (대출 있을 때 · 하루 1번)"])
    run.pace()
    for prod in ("futures_linear", "futures_inverse", "margin_isolated", "margin_cross"):
        run.run(ex, prod, lambda prod=prod: okx_pos(prod), ["GET /api/v5/account/positions (상품 4줄이 한 번의 조회를 나눠 씀)"])


def _okx_mgn(it, p):
    mr = num(p.get("mgnRatio"))
    if mr is not None and mr > 0:
        it.setdefault("metrics", {})["mgn_ratio"] = metric(mr, "x", "down", call=OKX_WARN_CALL, liq=1.0, thr_src=DOC_OKX_WARN,
                                                          liq_src=DOC_OKX_POS_MGN, src="mgnRatio@GET /api/v5/account/positions")
    return it


def kucoin(run: Run, g: dict, now: int):
    ex = "kucoin"

    def cross():
        d = g["get"]("/api/v3/margin/accounts?quoteCurrency=USDT")
        if not isinstance(d, dict) or not isinstance(d.get("accounts"), list):
            raise RuntimeError("kucoin margin accounts 형식 오류")
        debt, coll = [], []
        W = "kucoin margin accounts"
        for a in req_rows(d, "accounts", W):
            debt.append(debt_req(a.get("currency"), num(a.get("liabilityPrincipal")), num(a.get("liabilityInterest")), req_num(a, "liability", W), what=W))
            coll.append(coll_row(a.get("currency"), a.get("total")))
        debt = [x for x in debt if x]
        if not debt:
            return [], "차입 없음 확인"
        cfg, cat = run.cached("kucoin:margin-config", lambda: g["pub"]("/api/v1/margin/config"))
        cfg = cfg if isinstance(cfg, dict) else {}
        for r9 in debt:
            rd, _ = run.cached(f"kucoin:borrowRate:{r9['ccy']}", lambda c9=r9["ccy"]: g["get"](f"/api/v3/margin/borrowRate?currency={c9}"))
            its = (rd or {}).get("items") if isinstance(rd, dict) else None
            if isinstance(its, list) and its and isinstance(its[0], dict) and num(its[0].get("hourlyBorrowRate")) is not None:
                r9["rate"], r9["rate_period"] = num(its[0].get("hourlyBorrowRate")), "hour"
        wd9, ld9 = num(cfg.get("warningDebtRatio")), num(cfg.get("liqDebtRatio"))
        m = {"debt_ratio": metric(num(d.get("debtRatio")), "frac", "up", warn=wd9, call=wd9 if (wd9 and (ld9 is None or wd9 < ld9)) else None,
                                  liq=ld9, thr_src="api:GET /api/v1/margin/config" if (cfg and (wd9 or ld9)) else "unknown",
                                  thr_at=cat if cfg else None, src="debtRatio@GET /api/v3/margin/accounts")}
        raw = {"status": d.get("status"), "totalAssetUSDT": num(d.get("totalAssetOfQuoteCurrency")),
               "totalLiabilityUSDT": num(d.get("totalLiabilityOfQuoteCurrency"))}
        return [item(ex, "margin_cross", "account", "-", "쿠코인 교차마진", now, m, debt, coll, raw=raw,
                     state=official(d.get("status"), "status@GET /api/v3/margin/accounts"))]

    def isolated():
        d = g["get"]("/api/v3/isolated/accounts?quoteCurrency=USDT")
        if not isinstance(d, dict) or not isinstance(d.get("assets"), list):
            raise RuntimeError("kucoin isolated accounts 형식 오류")
        out = []
        W = "kucoin isolated accounts"
        for p in req_rows(d, "assets", W):
            debt, coll = [], []
            for side in ("baseAsset", "quoteAsset"):
                a = req_dict(p, side, W)
                debt.append(debt_req(a.get("currency"), num(a.get("liabilityPrincipal")), num(a.get("liabilityInterest")), req_num(a, "liability", W), what=W))
                coll.append(coll_row(a.get("currency"), a.get("total")))
            debt = [x for x in debt if x]
            if not debt:
                continue
            sym = str(p.get("symbol") or "")
            sy, sat = run.cached("kucoin:isolated-symbols", lambda: g["pub"]("/api/v1/isolated/symbols"))
            th = next((x for x in (sy or []) if isinstance(x, dict) and x.get("symbol") == sym), {}) if isinstance(sy, list) else {}
            fl9 = num(th.get("flDebtRatio"))
            mc9, _ = run.cached("kucoin:margin-config", lambda: g["pub"]("/api/v1/margin/config")) if fl9 else (None, None)
            wd9 = num((mc9 or {}).get("warningDebtRatio")) if isinstance(mc9, dict) else None
            ok9 = bool(wd9 and fl9 and wd9 < fl9)
            m = {"debt_ratio": metric(num(p.get("debtRatio")), "frac", "up", call=wd9 if ok9 else None, liq=fl9,
                                      thr_src=("api:GET /api/v1/isolated/symbols (flDebtRatio) · GET /api/v1/margin/config (warningDebtRatio)" if ok9
                                               else "api:GET /api/v1/isolated/symbols (flDebtRatio)") if fl9 else "unknown",
                                      thr_at=sat if fl9 else None, src="debtRatio@GET /api/v3/isolated/accounts")}
            out.append(item(ex, "margin_isolated", "pair", sym, f"쿠코인 격리마진 {sym}", now, m, debt, coll, raw={"status": p.get("status")},
                            state=official(p.get("status"), "status@GET /api/v3/isolated/accounts")))
        return out, (None if out else "차입 없음 확인")

    def futures(product):
        rows = fut_rows()
        out = []
        for p in rows:
            q = req_num(p, "currentQty", "kucoin futures positions")
            if abs(q) <= EPS:
                continue
            settle = req_ccy(p.get("settleCurrency"), "kucoin futures positions settleCurrency")
            prod9 = "futures_linear" if settle in ("USDT", "USDC") else "futures_inverse"
            if prod9 != product:
                continue
            mode = str(p.get("marginMode") or ("CROSS" if p.get("crossMode") else "ISOLATED")).lower()
            side = _side(p.get("positionSide")) if str(p.get("positionSide") or "BOTH").upper() != "BOTH" else ("LONG" if q > 0 else "SHORT")
            liq9 = None if mode == "cross" else p.get("liquidationPrice")
            out.append(pos_item(ex, product, now, p.get("symbol"), side, q, "contract", p.get("avgEntryPrice"), p.get("markPrice"),
                                liq9, p.get("realLeverage") if mode == "isolated" else p.get("leverage"), mode, p.get("unrealisedPnl"),
                                settle or None, im=p.get("posInit"), mm=p.get("posMaint"),
                                raw={"maintMarginReq": num(p.get("maintMarginReq")), "delevPercentage": num(p.get("delevPercentage"))},
                                note=("교차 포지션 — 청산은 선물 계정 위험률(riskRatio) 기준" if mode == "cross" else None)))
        return out, (None if out else "포지션 없음 확인")

    cache9 = {}

    def fut_rows():
        if "rows" not in cache9:
            rows = g["fut"]("/api/v1/positions")
            cache9["rows"] = req_list(rows, "kucoin futures positions")
        return cache9["rows"]

    run.run(ex, "margin_cross", cross, ["GET /api/v3/margin/accounts?quoteCurrency=USDT", "GET /api/v1/margin/config (공개 · 하루 1번)",
                                        "GET /api/v3/margin/borrowRate (차입 통화만 · 하루 1번)"])
    run.pace()
    run.run(ex, "margin_isolated", isolated, ["GET /api/v3/isolated/accounts?quoteCurrency=USDT", "GET /api/v1/isolated/symbols (공개 · 하루 1번)"])
    run.pace()
    for prod in ("futures_linear", "futures_inverse"):
        run.run(ex, prod, lambda prod=prod: futures(prod), ["GET api-futures /api/v1/positions (두 줄이 한 번의 조회를 나눠 씀)"])
    run.skip(ex, "loan", "unsupported", "개인용 담보대출(Crypto Loan) 공개 API 없음 — VIP 대출(otc-loan)만 있음")


def gate(run: Run, g: dict, now: int):
    ex = "gate"

    def isolated():
        rows = g["get"]("/api/v4/margin/accounts", {})
        W = "gate margin accounts"
        out = []
        for p in req_list(rows, W):
            debt, coll = [], []
            for side in ("base", "quote"):
                a = req_dict(p, side, W)
                debt.append(debt_req(a.get("currency"), req_num(a, "borrowed", W), num(a.get("interest")), what=W))
                coll.append(coll_row(a.get("currency"), (num(a.get("available")) or 0.0) + (num(a.get("locked")) or 0.0)))
            debt = [x for x in debt if x]
            if not debt:
                continue
            pair = str(p.get("currency_pair") or "")
            m = {}
            if num(p.get("risk")) is not None:
                m["risk_rate"] = metric(num(p.get("risk")), "x", "down", thr_src="unknown", src="risk@GET /api/v4/margin/accounts")
            out.append(item(ex, "margin_isolated", "pair", pair, f"게이트 격리마진 {pair}", now, m, debt, coll,
                            raw={"mmr": num(p.get("mmr")), "account_type": p.get("account_type"), "leverage": num(p.get("leverage"))},
                            note="현행 문서의 위험 지표 = mmr(유지증거금률 — 방향·청산 기준 문서 미기재) — 원문만 표시"))
        return out, (None if out else "차입 없음 확인")

    def cross():
        d = g["get"]("/api/v4/margin/cross/accounts", {})
        bals = d.get("balances") if isinstance(d, dict) else None
        if not isinstance(bals, dict):
            raise RuntimeError("gate cross balances 형식 오류")
        debt = []
        W = "gate cross accounts"
        for ccy, b in bals.items():
            if not isinstance(b, dict):
                raise Unknown(f"{W}: balances 행 형식 오류")
            bw9, tl9 = num(b.get("borrowed")), num(b.get("total_liab"))
            if bw9 is None and tl9 is None:
                raise Unknown(f"{W}: {str(ccy)[:12]} borrowed·total_liab 둘 다 없음")
            r9 = debt_req(ccy, bw9, num(b.get("interest")), tl9, what=W)
            if r9 and r9["total"] > 1e-6:
                debt.append(r9)
        if not debt:
            return [], "차입 없음 확인"
        m = {"risk_rate": metric(num(d.get("risk")), "x", "down", liq=1.1,
                                 thr_src="doc:https://github.com/gateio/gateapi-python (CrossMarginAccount.risk — 110% 미만 청산)",
                                 src="risk@GET /api/v4/margin/cross/accounts")}
        mmr = num(d.get("total_maintenance_margin_rate"))
        if mmr is not None and mmr > 0:
            est9 = num(d.get("risk")) is None
            m["mgn_ratio"] = metric(mmr, "x", "down", call=GATE_MULTI_CALL if est9 else None, liq=1.0 if est9 else None,
                                    thr_src=DOC_GATE_CROSS_EST if est9 else "unknown",
                                    src="total_maintenance_margin_rate@GET /api/v4/margin/cross/accounts")
        raw = {"total_maintenance_margin_rate": mmr, "total_initial_margin_rate": num(d.get("total_initial_margin_rate")),
               "total_margin_balance": num(d.get("total_margin_balance")), "total_maintenance_margin": num(d.get("total_maintenance_margin"))}
        return [item(ex, "margin_cross", "account", "-", "게이트 교차마진", now, m, debt, raw=raw)]

    def unified():
        d = g["get"]("/api/v4/unified/accounts", {})
        if not isinstance(d, dict):
            raise RuntimeError("gate unified 형식 오류")
        if str(d.get("mode") or "") == "classic":
            return [], "클래식 계정(통합계정 미사용) 확인"
        liab = req_num(d, "unified_account_total_liab", "gate unified")
        mm = num(d.get("total_maintenance_margin_rate"))
        if not (liab and liab > EPS):
            mt9 = num(d.get("total_maintenance_margin"))
            if mt9 is not None and mt9 < 0:
                raise Unknown("gate unified: total_maintenance_margin 음수")
            if not (mm is not None and mm > 0 and (mt9 is None or mt9 > EPS)):
                return [], "통합계정 부채 없음 확인"
        m = {}
        if mm is not None and mm > 0:
            md9 = str(d.get("mode") or "")
            if md9 == "multi_currency":
                m["mgn_ratio"] = metric(mm, "x", "down", call=GATE_MULTI_CALL, liq=1.0, thr_src=DOC_GATE_MULTI,
                                        src="total_maintenance_margin_rate@GET /api/v4/unified/accounts")
            elif md9 == "portfolio":
                m["mgn_ratio"] = metric(mm, "x", "down", liq=1.0, thr_src=DOC_GATE_PM, src="total_maintenance_margin_rate@GET /api/v4/unified/accounts")
            else:
                m["mgn_ratio"] = metric(mm, "x", "down", thr_src="unknown", src="total_maintenance_margin_rate@GET /api/v4/unified/accounts")
        debt = []
        bals9 = d.get("balances")
        for ccy, b in (bals9.items() if isinstance(bals9, dict) else ()):
            if not isinstance(b, dict):
                raise Unknown("gate unified: balances 행 형식 오류")
            r9 = debt_row(ccy, b.get("borrowed"), b.get("interest"), b.get("total_liab"))
            if r9:
                debt.append(r9)
        if liab > EPS and not debt:
            raise RuntimeError("gate unified 부채 합계는 있는데 통화별 total_liab 없음 — 형식 변경 의심")
        return [item(ex, "unified", "account", "-", "게이트 통합계정", now, m, debt,
                     raw={"unified_account_total_liab": liab, "unified_account_total_equity": num(d.get("unified_account_total_equity")),
                          "mode": d.get("mode")})]

    def loan():
        out = []
        rows = []
        for ot9 in ("current", "fixed"):
            for pg9 in range(1, 21):
                b9 = req_list(g["get"]("/api/v4/loan/multi_collateral/orders", {"order_type": ot9, "page": pg9, "limit": 100}),
                              "gate multi-collateral loan")
                rows.extend(b9)
                if len(b9) < 100:
                    break
                run.pace()
            else:
                raise RuntimeError("gate multi-collateral loan 20쪽 초과 — 부분 목록 폐기")
            run.pace()
        mth = None
        W = "gate multi-collateral loan"
        for r in rows:
            debt = [debt_req(b.get("currency"), req_num(b, "left_repay_principal", W), num(b.get("left_repay_interest")), what=W)
                    for b in req_rows(r, "borrow_currencies", W)]
            debt = [x for x in debt if x]
            if not debt:
                continue
            coll = [coll_req(c.get("currency"), req_num(c, "left_collateral", W), W) for c in req_rows(r, "collateral_currencies", W)]
            if mth is None:
                mth, mat = run.cached("gate:multi-ltv", lambda: g["get"]("/api/v4/loan/multi_collateral/ltv", {}))
                mth = mth if isinstance(mth, dict) else {}
            al9, lq9 = num(mth.get("alert_ltv")), num(mth.get("liquidate_ltv"))
            m = {"ltv": metric(num(r.get("current_ltv")), "frac", "up", warn=al9, call=al9 if (al9 and (lq9 is None or al9 < lq9)) else None, liq=lq9,
                               thr_src="api:GET /api/v4/loan/multi_collateral/ltv" if mth else "unknown", thr_at=mat if mth else None,
                               src="current_ltv@GET /api/v4/loan/multi_collateral/orders")}
            out.append(item(ex, "loan", "loan", f"m:{r.get('order_id')}", "게이트 다중 담보대출", now, m, debt, coll,
                            raw={"order_type": r.get("order_type"), "fixed_rate": num(r.get("fixed_rate"))}))
        return out, (None if out else "대출 없음 확인")

    def futures(settle, product):
        rows = g["get"](f"/api/v4/futures/{settle}/positions", {"holding": "true"})
        out = []
        for p in req_list(rows, "gate futures positions"):
            sz = req_num(p, "size", "gate futures positions")
            if abs(sz) <= EPS:
                continue
            lev = num(p.get("leverage"))
            pm9 = str(p.get("pos_margin_mode") or "").lower()
            mode = pm9 if pm9 in ("cross", "isolated") else ("cross" if lev == 0 else "isolated")
            if num(p.get("lever")) is not None:
                lev = num(p.get("lever"))
            out.append(pos_item(ex, product, now, p.get("contract"), "LONG" if sz > 0 else "SHORT", sz, "contract", p.get("entry_price"),
                                p.get("mark_price"), p.get("liq_price"), lev if lev else p.get("cross_leverage_limit"),
                                mode, p.get("unrealised_pnl"), settle.upper(), im=p.get("initial_margin"), mm=p.get("maintenance_margin"),
                                raw={"maintenance_rate": num(p.get("maintenance_rate")), "margin": num(p.get("margin")),
                                     "adl_ranking": num(p.get("adl_ranking")), "mode": p.get("mode")}))
        return out, (None if out else "포지션 없음 확인")

    run.run(ex, "margin_isolated", isolated, ["GET /api/v4/margin/accounts"])
    run.pace()
    run.run(ex, "margin_cross", cross, ["GET /api/v4/margin/cross/accounts"])
    run.pace()
    row = run.run(ex, "unified", unified, ["GET /api/v4/unified/accounts"])
    if row.get("status") == "no_permission":
        row["note"] = "클래식 계정(통합계정 미사용)이거나 키 권한 없음 — 1시간마다 다시 확인"
    run.pace()
    run.run(ex, "loan", loan, ["GET /api/v4/loan/multi_collateral/orders", "GET /api/v4/loan/multi_collateral/ltv (대출 있을 때 · 하루 1번)"],
            note_ok=None)
    run.pace()
    run.run(ex, "futures_linear", lambda: futures("usdt", "futures_linear"), ["GET /api/v4/futures/usdt/positions"])
    run.pace()
    run.run(ex, "futures_inverse", lambda: futures("btc", "futures_inverse"), ["GET /api/v4/futures/btc/positions"])


COLLECTORS = {"binance": binance, "bybit": bybit, "okx": okx, "kucoin": kucoin, "gate": gate}
ALL_PRODUCTS = {
    "binance": ("margin_cross", "margin_isolated", "loan", "futures_linear", "futures_inverse", "unified"),
    "bybit": ("unified", "loan", "futures_linear", "futures_inverse", "margin_cross"),
    "okx": ("unified", "loan", "futures_linear", "futures_inverse", "margin_isolated", "margin_cross"),
    "kucoin": ("margin_cross", "margin_isolated", "futures_linear", "futures_inverse", "loan"),
    "gate": ("margin_isolated", "margin_cross", "unified", "loan", "futures_linear", "futures_inverse"),
}


def path() -> str:
    return os.path.join(common.STATE_DIR, NAME)


def load_prev() -> dict:
    try:
        d = common.read_json(path(), {})
    except (SystemExit, Exception):
        return {}
    return d if isinstance(d, dict) and d.get("v") == V else {}


def collect(env: dict, getters: dict, now: int = None, cycle_sec: int = 600, fresh_sec: int = 1800, pace=None, log=None, cfg=None) -> dict:
    now = int(now or time.time())
    run = Run(load_prev(), now, cycle_sec, fresh_sec, pace, cfg)
    for ex in EXCHANGES:
        if not all(env.get(k) for k in NEED[ex]) or ex not in getters:
            for prod in ALL_PRODUCTS[ex]:
                run.skip(ex, prod, "no_key", "API 키 없음 — 호출 안 함")
            continue
        n0 = len(run.products)
        try:
            COLLECTORS[ex](run, getters[ex], now)
        except Exception as e:
            st, msg = classify(e)
            done = {p["product"] for p in run.products[n0:]}
            for prod in ALL_PRODUCTS[ex]:
                if prod not in done:
                    run._row(ex, prod, "error", note="수집기 오류 — 다음 주기 재시도", err=msg)
            if log:
                log.warning("레버리지 %s 수집기 오류: %s", ex, msg[:160])
    return run.result()


def write(doc: dict) -> None:
    common.atomic_write_json(path(), doc)


def read_state(now: float = None, p: str = None) -> dict:
    now = float(now if now is not None else time.time())
    try:
        d = common.read_json(p or path(), None)
    except (SystemExit, Exception):
        d = None
    if not isinstance(d, dict) or d.get("v") != V:
        return {"v": V, "missing": True, "products": [], "items": []}
    fs = int(d.get("fresh_sec") or 1800)
    for pr in d.get("products") or []:
        if isinstance(pr, dict):
            ma = pr.get("measured_at")
            st = pr.get("status")
            pr["status_eff"] = "stale" if st == "ok" and (not isinstance(ma, (int, float)) or now - ma > fs) else st
    for it in d.get("items") or []:
        if isinstance(it, dict):
            ma = it.get("measured_at")
            it["fresh"] = bool(not it.get("stale") and isinstance(ma, (int, float)) and now - ma <= fs)
    d.pop("_cache", None)
    return d
