from __future__ import annotations
import os
import time
import urllib.request
import ex_sign, paths, statefile
from exf_net import BN_UNI_RETRY
from exf_net import BN_UNI_TTL
from exf_net import DAY
from exf_net import PACE
from exf_net import PX_CALLS_MAX
from exf_net import RateLimited
from exf_net import _Bal
from exf_net import _PartialConvertRows
from exf_net import _acct
from exf_net import _balance_rows
from exf_net import _clock_retry
from exf_net import _cv_fill
from exf_net import _debt_add
from exf_net import _earn_amount
from exf_net import _fut_opt
from exf_net import _fut_path
from exf_net import _fut_req
from exf_net import _fut_write
from exf_net import _gov_prepare
from exf_net import _int_or
from exf_net import _loan_add
from exf_net import _loan_amt
from exf_net import _px_safe
from exf_net import _recon_hold
from exf_net import _recon_hold_clear
from exf_net import _srv_ms
from exf_net import _sub_bal
from exf_net import _xm
from exf_net import fut_first_t0
from exf_net import fut_rcpt
from exf_net import http_json
from exf_net import norm_fill
from exf_net import norm_row
from exf_net import split_pair
import logging

log = logging.getLogger('tj-exf')

_BB_WD_FAIL = {"cancelbyuser": "CANCELLED", "reject": "REJECTED", "fail": "FAILED"}


def fetch_bybit(env, t0: int, t1: int):
    key, sec = env["TJ_BYBIT_KEY"], env["TJ_BYBIT_SECRET"]
    out_w, out_d = [], []

    @_clock_retry
    def call(path, params):
        _gov_prepare("api.bybit.com", path)
        qs = urllib.parse.urlencode(params)
        ts = str(_srv_ms("api.bybit.com"))
        recv = "10000"
        sig = ex_sign.bybit_sign(sec, ts, key, recv, qs)
        d = http_json(f"https://api.bybit.com{path}?{qs}",
                      {"X-BAPI-API-KEY": key, "X-BAPI-TIMESTAMP": ts,
                       "X-BAPI-RECV-WINDOW": recv, "X-BAPI-SIGN": sig})
        if d.get("retCode") != 0:
            raise RuntimeError(f"bybit {d.get('retCode')} {_xm(d.get('retMsg'))}")
        return d.get("result") or {}

    s = t0
    while s < t1:
        e = min(s + 29 * DAY, t1)
        srcs = [("/v5/asset/withdraw/query-record", "w"), ("/v5/asset/deposit/query-record", "d")]
        if _acct():
            srcs = srcs[1:]
        for path, bucket in srcs:
            cursor = ""
            seen_cursors = set()
            while True:
                p = {"startTime": s * 1000, "endTime": e * 1000, "limit": 50}
                if bucket == "w":
                    p["withdrawType"] = 2
                if cursor:
                    p["cursor"] = cursor
                res = call(path, p)
                rows = res.get("rows") or []
                for row in rows:
                    if bucket == "w":
                        st9 = str(row.get("status", "")).lower()
                        st = "DONE" if st9 == "success" else _BB_WD_FAIL.get(st9, "PENDING")
                        int9 = str(row.get("withdrawType")) == "1"
                        net9 = row.get("chain") or ("BYBIT_INTERNAL" if int9 else None)
                        r9 = norm_row("bybit", row.get("withdrawId"), row.get("coin"),
                                      row.get("amount"), row.get("withdrawFee"),
                                      row.get("txID"), st,
                                      row.get("createTime"), row.get("updateTime"),
                                      row.get("toAddress"), row.get("tag"), net9)
                        if int9:
                            r9["late"] = 1
                        out_w.append(r9)
                    else:
                        st = "ACCEPTED" if _int_or(row.get("status"), 0) == 3 else \
                            ("FAILED" if _int_or(row.get("status"), 0) == 4 else "PENDING")
                        nid = row.get("id") or f"{row.get('coin')}:{row.get('txID')}"
                        out_d.append(norm_row("bybit", nid, row.get("coin"), row.get("amount"),
                                              0, row.get("txID"), st,
                                              row.get("successAt"), row.get("successAt"),
                                              network=row.get("chain")))
                cursor = res.get("nextPageCursor") or ""
                if cursor and cursor in seen_cursors:
                    raise RuntimeError("bybit 입출금 페이지 커서 순환 — 다음 주기 재시도")
                seen_cursors.add(cursor)
                time.sleep(PACE)
                if not cursor or not rows:
                    break
        s = e
    return out_w, out_d


def _bybit_internal_rows(env, t0: int, t1: int) -> list:
    out = []
    s = int(t0)
    while s < t1:
        e = min(s + 29 * DAY, int(t1))
        cursor, seen_c = "", set()
        while True:
            p = {"startTime": s * 1000, "endTime": e * 1000, "limit": 50}
            if cursor:
                p["cursor"] = cursor
            res = _bybit_get(env, "/v5/asset/deposit/query-internal-record", p)
            rows = res.get("rows")
            if not isinstance(rows, list):
                raise RuntimeError("bybit internal-record rows 누락/형식 오류")
            for row in rows:
                if not isinstance(row, dict) or not row.get("id"):
                    continue
                sti = _int_or(row.get("status"), 0)
                st = "ACCEPTED" if sti == 2 else ("FAILED" if sti == 3 else "PENDING")
                out.append(norm_row("bybit", f"int:{row.get('id')}", row.get("coin"), row.get("amount"),
                                    0, row.get("txID"), st, row.get("createdTime"), row.get("createdTime"),
                                    network="BYBIT_INTERNAL"))
            cursor = str(res.get("nextPageCursor") or "")
            time.sleep(PACE)
            if not cursor or not rows:
                break
            if cursor in seen_c:
                raise RuntimeError("bybit internal-record 커서 순환")
            seen_c.add(cursor)
        s = e
    return out


BB_INT_DENY = ("retCode=10005", "retCode=10003", "retCode=10004", "retCode=10010")


BB_UNI_NAME = "exf_bybit_symbols.json"


BB_UNI_URL = "https://api.bybit.com/v5/market/instruments-info"


BB_HOLD_MAX = 2000


_BB_UNI = {"ts": 0.0, "fail": 0.0, "sym": None, "path": None}


def _bb_universe(now: float, need: bool = False):
    u = _BB_UNI
    p = paths.state(BB_UNI_NAME)
    if u.get("path") != p:
        u.update(ts=0.0, fail=0.0, sym=None, path=p)
        try:
            d = statefile.read_json(p, {}) if os.path.exists(p) else {}
        except SystemExit:
            d = {}
        sy = d.get("symbols") if isinstance(d, dict) else None
        if isinstance(sy, dict) and sy:
            u["sym"] = {str(k): (str(v[0]), str(v[1])) for k, v in sy.items() if isinstance(v, list) and len(v) >= 2 and v[0] and v[1]}
            try:
                u["ts"] = float(d.get("ts") or 0)
            except (TypeError, ValueError):
                u["ts"] = 0.0
    due = now - u["ts"] >= BN_UNI_TTL or (need and now - u["ts"] >= BN_UNI_RETRY)
    if due and now - u["fail"] >= BN_UNI_RETRY:
        try:
            sym, cur, seen9 = {}, "", set()
            for _pg in range(10):
                q9 = {"category": "spot", "limit": 1000}
                if cur:
                    q9["cursor"] = cur
                d = http_json(BB_UNI_URL + "?" + urllib.parse.urlencode(q9), timeout=30)
                if not isinstance(d, dict) or d.get("retCode") != 0 or not isinstance((d.get("result") or {}).get("list"), list):
                    raise RuntimeError(f"instruments-info 형식 오류 {_xm((d or {}).get('retCode') if isinstance(d, dict) else type(d).__name__)}")
                for r in d["result"]["list"]:
                    if not isinstance(r, dict):
                        continue
                    s9 = str(r.get("symbol") or "").upper()
                    b9, q9b = str(r.get("baseCoin") or "").upper(), str(r.get("quoteCoin") or "").upper()
                    if s9 and b9 and q9b and b9 != q9b:
                        sym[s9] = (b9, q9b)
                cur = str(d["result"].get("nextPageCursor") or "")
                if not cur or cur in seen9:
                    break
                seen9.add(cur)
            if not sym:
                raise RuntimeError("instruments-info 종목 0")
            u["sym"], u["ts"] = dict(u["sym"] or {}, **sym), float(now)
            statefile.atomic_write_json(p, {"ts": int(now), "symbols": {k: list(v) for k, v in u["sym"].items()}})
            log.info("bybit 종목 목록 갱신: %d개(이번 응답 %d)", len(u["sym"]), len(sym))
        except Exception as e:   # noqa: BLE001 [fallback]
            u["fail"] = float(now)
            log.warning("bybit instruments-info 갱신 실패(%s · 1시간 뒤 재시도): %s",
                        "직전 목록 사용" if u["sym"] else "종전 주요 쿼트로", _xm(repr(e))[:140])
    return u["sym"]


def _bb_split(sym: str, uni):
    s = str(sym or "").upper()
    if uni and s in uni:
        return uni[s]
    b, q = split_pair(s)
    return (b, q) if (b and q) else (None, None)


def _bb_fill(r, b, q):
    return norm_fill("bybit", r.get("execId"), r.get("execTime"), b, q, str(r.get("side", "")).lower(),
                     r.get("execPrice"), r.get("execQty"), r.get("execFee"), r.get("feeCurrency") or q)


def _bb_hold_keep(st: dict, cp: dict) -> bool:
    h9 = cp.get("bb_hold") if isinstance(cp, dict) else None
    if not isinstance(h9, dict) or not h9:
        return False
    dst = (st.setdefault("fills", {})).setdefault("bb_hold", {})
    add = {k: v for k, v in h9.items() if k not in dst}
    dst.update(add)
    return bool(add)


def fills_bybit(env, st, t0: int, t1: int):
    key, sec = env["TJ_BYBIT_KEY"], env["TJ_BYBIT_SECRET"]

    @_clock_retry
    def call(params):
        _gov_prepare("api.bybit.com", "/v5/execution/list")
        qs = urllib.parse.urlencode(params)
        ts = str(_srv_ms("api.bybit.com"))
        recv = "10000"
        sig = ex_sign.bybit_sign(sec, ts, key, recv, qs)
        d = http_json(f"https://api.bybit.com/v5/execution/list?{qs}",
                      {"X-BAPI-API-KEY": key, "X-BAPI-TIMESTAMP": ts,
                       "X-BAPI-RECV-WINDOW": recv, "X-BAPI-SIGN": sig})
        if d.get("retCode") != 0:
            raise RuntimeError(f"bybit {d.get('retCode')} {_xm(d.get('retMsg'))}")
        return d.get("result") or {}

    fills = []
    now9 = int(time.time())
    uni = [_bb_universe(now9), False]

    def split9(sym):
        b9, q9 = _bb_split(sym, uni[0])
        if not q9 and not uni[1]:
            uni[1] = True
            uni[0] = _bb_universe(now9, need=True)
            b9, q9 = _bb_split(sym, uni[0])
        return b9, q9
    hold = st.get("bb_hold") if isinstance(st.get("bb_hold"), dict) else {}
    st["bb_hold"] = hold
    out9 = set()
    for k9 in sorted(hold, key=lambda k: str((hold[k] or {}).get("execTime") or "")):
        r9 = hold[k9] if isinstance(hold[k9], dict) else {}
        b9, q9 = split9(r9.get("symbol"))
        if q9:
            f9 = _bb_fill(r9, b9, q9)
            f9["late"] = 1
            fills.append(f9)
            out9.add(k9)
    for k9 in out9:
        hold.pop(k9, None)
    if out9:
        log.info("bybit 보류 체결 %d건 방출(종목 목록으로 대금 통화 확인)", len(out9))
    s = t0
    while s < t1:
        e = min(s + 6 * DAY, t1)
        cursor = ""
        seen_cursors = set()
        while True:
            p = {"category": "spot", "startTime": s * 1000, "endTime": e * 1000, "limit": 100}
            if cursor:
                p["cursor"] = cursor
            res = call(p)
            rows = res.get("list") or []
            for r in rows:
                k9 = str(r.get("execId") or "")
                if k9 in out9:
                    continue
                b, q = split9(r.get("symbol"))
                if not q:
                    if k9 and k9 not in hold and str(r.get("symbol") or "").strip():
                        hold[k9] = {kk: r.get(kk) for kk in ("symbol", "execId", "execTime", "side", "execPrice", "execQty", "execFee", "feeCurrency")}
                        hold[k9]["held_at"] = now9
                        log.warning("bybit 체결 보류 — 종목 목록에 없는 심볼 %s(대금 통화 모름): %s", _xm(r.get("symbol"))[:24], k9[:24])
                    continue
                fills.append(_bb_fill(r, b, q))
            cursor = res.get("nextPageCursor") or ""
            if cursor and cursor in seen_cursors:
                raise RuntimeError("bybit 체결 페이지 커서 순환 — 다음 주기 재시도")
            seen_cursors.add(cursor)
            time.sleep(PACE)
            if not cursor or not rows:
                break
        s = e
    if len(hold) > BB_HOLD_MAX:
        for k9 in sorted(hold, key=lambda k: int((hold[k] or {}).get("held_at") or 0))[:len(hold) - BB_HOLD_MAX]:
            hold.pop(k9, None)
        log.warning("bybit 보류 체결 상한 %d 초과 — 가장 오래된 것부터 버림", BB_HOLD_MAX)
    if hold:
        _recon_hold(st, "bb_split", now9, f"바이비트 대금 통화 모르는 체결 {len(hold)}건 보류")
    else:
        st.pop("bb_hold", None)
        _recon_hold_clear(st, "bb_split")
    return fills


def convert_bybit(env, t0: int, t1: int):
    out, got, errs = [], set(), []
    invalid = set()
    try:
        for idx in range(1, 101):
            res = _bybit_get(env, "/v5/asset/exchange/query-convert-history", {"index": idx, "limit": 100})
            rows = res.get("list")
            if not isinstance(rows, list):
                raise RuntimeError("bybit convert list 형식 오류")
            ts9 = []
            for r in rows:
                if not isinstance(r, dict):
                    continue
                tid = str(r.get("exchangeTxId") or "")
                try:
                    ts9.append(int(float(r.get("createdAt") or 0)))
                except (TypeError, ValueError):
                    pass
                if not tid or tid in got or str(r.get("exchangeStatus") or "").lower() != "success":
                    continue
                if int(float(r.get("createdAt") or 0)) < t0 * 1000:
                    continue
                f9 = _cv_fill("bybit", tid, r.get("createdAt"), r.get("fromCoin"), r.get("fromAmount"),
                              r.get("toCoin"), r.get("toAmount"))
                if f9:
                    got.add(tid)
                    out.append(f9)
                else:
                    invalid.add(tid)
            time.sleep(PACE)
            if len(rows) < 100:
                break
            if len(ts9) >= 2 and ts9[0] >= ts9[-1] and ts9[-1] < t0 * 1000:
                break
    except Exception as e:  # noqa: BLE001 [isolate]
        errs.append(_xm(repr(e))[:160])
    try:
        cursor, seen_c = "", set()
        for _pg in range(100):
            p = {"limit": 50}
            if cursor:
                p["cursor"] = cursor
            res = _bybit_get(env, "/v5/asset/exchange/order-record", p)
            rows = res.get("orderBody")
            if not isinstance(rows, list):
                raise RuntimeError("bybit order-record orderBody 형식 오류")
            old9 = False
            for r in rows:
                if not isinstance(r, dict):
                    continue
                tid = str(r.get("exchangeTxId") or "")
                try:
                    tsr = int(float(r.get("createdTime") or 0))
                except (TypeError, ValueError):
                    continue
                tsr_ms = tsr * 1000 if tsr < 10 ** 12 else tsr
                if tsr_ms < t0 * 1000:
                    old9 = True
                    continue
                if not tid or tid in got:
                    continue
                f9 = _cv_fill("bybit", tid, tsr_ms, r.get("fromCoin"), r.get("fromAmount"), r.get("toCoin"), r.get("toAmount"))
                if f9:
                    got.add(tid)
                    out.append(f9)
                else:
                    invalid.add(tid)
            time.sleep(PACE)
            cursor = str(res.get("nextPageCursor") or "")
            if not rows or not cursor or old9:
                break
            if cursor in seen_c:
                raise RuntimeError("bybit order-record 커서 순환")
            seen_c.add(cursor)
    except Exception as e:  # noqa: BLE001 [isolate]
        errs.append(_xm(repr(e))[:160])
    if len(errs) == 2:
        raise RuntimeError("bybit 전환 두 경로 모두 실패: " + " | ".join(errs))
    if invalid - got:
        raise RuntimeError("bybit convert 체결 필드 누락/형식 오류")
    if errs:
        log.warning("bybit 전환 내역 한 경로 실패(다른 경로 결과만 반영): %s", errs[0])
        return _PartialConvertRows(out, errs[0])
    return out


@_clock_retry
def _bybit_get(env, path, params):
    _gov_prepare("api.bybit.com", path)
    key, sec = env["TJ_BYBIT_KEY"], env["TJ_BYBIT_SECRET"]
    qs = urllib.parse.urlencode(params or {})
    ts = str(_srv_ms("api.bybit.com"))
    sig = ex_sign.bybit_sign(sec, ts, key, "10000", qs)
    d = http_json(f"https://api.bybit.com{path}" + (f"?{qs}" if qs else ""),
                  {"X-BAPI-API-KEY": key, "X-BAPI-TIMESTAMP": ts,
                   "X-BAPI-RECV-WINDOW": "10000", "X-BAPI-SIGN": sig})
    if not isinstance(d, dict) or d.get("retCode") != 0:
        rc = d.get("retCode") if isinstance(d, dict) else None
        raise RuntimeError(f"bybit {path} retCode={rc} {_xm((d or {}).get('retMsg')) if isinstance(d, dict) else _xm(str(d)[:80])}")
    return d.get("result") or {}


def _bal_bybit(env):
    _gov_prepare("api.bybit.com", "/v5/account/wallet-balance")
    key, sec = env["TJ_BYBIT_KEY"], env["TJ_BYBIT_SECRET"]
    q = "accountType=UNIFIED"
    ts = str(_srv_ms("api.bybit.com"))
    sig = ex_sign.bybit_sign(sec, ts, key, "10000", q)
    d = http_json(f"https://api.bybit.com/v5/account/wallet-balance?{q}",
                  {"X-BAPI-API-KEY": key, "X-BAPI-TIMESTAMP": ts,
                   "X-BAPI-RECV-WINDOW": "10000", "X-BAPI-SIGN": sig})
    if d.get("retCode") != 0:
        raise RuntimeError(f"bybit {_xm(d.get('retMsg'))}")
    out = _Bal()
    for acct in _balance_rows((d.get("result") or {}).get("list")):
        for c in _balance_rows(acct.get("coin")):
            v = float(c.get("walletBalance") or 0) - float(c.get("spotBorrow") or 0)
            if v < 0:
                _debt_add(out, "bybit", "UNIFIED", c.get("coin"), v)
            if v > 0:
                out[str(c["coin"]).upper()] = out.get(str(c["coin"]).upper(), 0) + v
    time.sleep(PACE)
    _gov_prepare("api.bybit.com", "/v5/asset/transfer/query-account-coins-balance")
    q2 = "accountType=FUND"
    ts2 = str(_srv_ms("api.bybit.com"))
    sig2 = ex_sign.bybit_sign(sec, ts2, key, "10000", q2)
    d2 = http_json(f"https://api.bybit.com/v5/asset/transfer/query-account-coins-balance?{q2}",
                   {"X-BAPI-API-KEY": key, "X-BAPI-TIMESTAMP": ts2,
                    "X-BAPI-RECV-WINDOW": "10000", "X-BAPI-SIGN": sig2})
    if d2.get("retCode") != 0:
        raise RuntimeError(f"bybit FUND {_xm(d2.get('retMsg'))}")
    for c in _balance_rows((d2.get("result") or {}).get("balance")):
        v = float(c.get("walletBalance") or 0)
        if v > 0:
            out[str(c["coin"]).upper()] = out.get(str(c["coin"]).upper(), 0) + v

    def _earn(o):
        for cat in ("FlexibleSaving", "OnChain"):
            res = _bybit_get(env, "/v5/earn/position", {"category": cat})
            rows = res.get("list")
            if not isinstance(rows, list):
                raise RuntimeError(f"bybit earn {cat} list 누락")
            for r2 in rows:
                _earn_amount(o, r2, "coin", "amount")
            time.sleep(PACE)

    def _loan(o):
        res = _bybit_get(env, "/v5/crypto-loan-common/position", {})
        if not isinstance(res, dict):
            raise RuntimeError("bybit crypto-loan position 형식 오류")
        coll, debt = {}, {}
        for key9 in ("collateralList", "supplyList"):
            rows = res.get(key9)
            if not isinstance(rows, list):
                raise RuntimeError(f"bybit crypto-loan {key9} 누락")
            for r2 in rows:
                k9, v9 = _loan_amt(r2, "currency", "amount", f"bybit 대출 {key9}")
                coll[k9] = coll.get(k9, 0) + v9
        rows = res.get("borrowList")
        if not isinstance(rows, list):
            raise RuntimeError("bybit crypto-loan borrowList 누락")
        for r2 in rows:
            if not isinstance(r2, dict) or not isinstance(r2.get("loanCurrency"), str) or not r2["loanCurrency"].strip():
                raise RuntimeError("bybit 대출 차입 행 형식 오류(loanCurrency)")
            parts9 = [r2.get(f9) for f9 in ("fixedTotalDebt", "flexibleTotalDebt") if r2.get(f9) not in (None, "")]
            if not parts9:
                raise RuntimeError("bybit 대출 차입 수량 필드 누락(fixedTotalDebt/flexibleTotalDebt)")
            v9 = sum(float(x) for x in parts9)
            if not 0 <= v9 < float("inf"):
                raise RuntimeError("bybit 대출 차입 수량 형식 오류")
            debt[r2["loanCurrency"].strip().upper()] = debt.get(r2["loanCurrency"].strip().upper(), 0) + v9
        try:
            td9 = float(res.get("totalDebt") or 0)
        except (TypeError, ValueError):
            td9 = 0.0
        if td9 > 0 and not any(v > 0 for v in debt.values()):
            raise RuntimeError("bybit crypto-loan totalDebt>0 인데 차입 행 없음 — 형식 변경 의심")
        ex9 = {}
        try:
            ex9["ltv"] = float(res.get("ltv"))
        except (TypeError, ValueError):
            pass
        _loan_add(o, "bybit", "loan", "crypto-loan", "바이빗 담보대출", coll, debt, extra=ex9)

    time.sleep(PACE)
    _sub_bal("bybit", "earn", _earn, out, extra_deny=("retCode=10005", "retCode=10003", "retCode=10004"), lenient=True)
    time.sleep(PACE)
    _sub_bal("bybit", "loan", _loan, out, extra_deny=("retCode=10005", "retCode=10003", "retCode=10004"), lenient=True)
    return out


BB_TLOG_TYPES = frozenset(("TRADE", "SETTLEMENT", "DELIVERY", "LIQUIDATION", "ADL"))


BB_TLOG_CALLS_MAX = 40


BB_TLOG_OVERLAP_MS = 3600 * 1000


BB_TLOG_LAG_MS = 120 * 1000


BB_TLOG_QUIET_MS = 300 * 1000


BB_TLOG_OFF_MS = 6 * 3600 * 1000


def _bb_num(v):
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return 0.0
    return _fut_opt(v)


def _bb_tlog_events(rows, tl_from, seen, ev):
    n9 = bad9 = 0
    for r in rows:
        if str(r.get("type") or "") not in BB_TLOG_TYPES or str(r.get("category") or "linear") != "linear":
            continue
        rid, t9 = str(r.get("id") or "").strip(), _fut_opt(r.get("transactionTime"))
        cf9, fd9, fe9 = _bb_num(r.get("cashFlow")), _bb_num(r.get("funding")), _bb_num(r.get("fee"))
        if not rid or t9 is None or t9 <= 0 or None in (cf9, fd9, fe9):
            bad9 += 1
            continue
        if int(t9) < tl_from:
            continue
        base9 = {"t": int(t9), "symbol": r.get("symbol") or ""}
        if str(r.get("currency") or "").strip():
            base9["asset"] = str(r.get("currency")).strip().upper()
        for suf9, kind9, amt9 in ((":p", "REALIZED", cf9), (":f", "FEE", -fe9), (":n", "FUNDING", fd9)):
            uid9 = f"bbt:{rid}{suf9}"
            if amt9 == 0 or uid9 in seen:
                continue
            seen.add(uid9)
            e9 = dict(base9, kind=kind9, amount=amt9, uid=uid9)
            if kind9 == "REALIZED":
                if str(r.get("orderId") or "").strip():
                    e9["oid"] = str(r.get("orderId")).strip()
                if str(r.get("type")) == "LIQUIDATION":
                    e9["liq"] = True
            ev.append(e9)
            n9 += 1
    if bad9:
        log.warning("bybit 거래 내역 형식 이상 %d줄 — 그 줄만 뺌(대사 나머지가 흡수)", bad9)
    return n9


def _bb_tlog_window(bcall, cur, s, e, out, budget):
    p9 = cur.get("tlog_pg")
    cursor = ""
    if isinstance(p9, dict):
        ps9, pe9, pc9 = _fut_opt(p9.get("s")), _fut_opt(p9.get("e")), p9.get("cursor")
        if ps9 == s and pe9 is not None and s < pe9 <= s + 7 * DAY * 1000 and isinstance(pc9, str) and pc9:
            e, cursor = int(pe9), pc9
        else:
            cur.pop("tlog_pg", None)
    seen9 = {cursor} if cursor else set()
    while True:
        if budget[0] >= BB_TLOG_CALLS_MAX:
            return None
        q9 = {"accountType": "UNIFIED", "category": "linear", "limit": 50, "startTime": s, "endTime": e}
        if cursor:
            q9["cursor"] = cursor
        time.sleep(PACE)
        budget[0] += 1
        try:
            res9 = bcall("/v5/account/transaction-log", q9)
            rows9 = res9.get("list") if isinstance(res9, dict) else None
            if not isinstance(rows9, list) or any(not isinstance(x9, dict) for x9 in rows9):
                raise RuntimeError("bybit transaction-log 목록 결손·형식 오류")
        except Exception:
            if cursor:
                cur.pop("tlog_pg", None)
            raise
        out.extend(rows9)
        nxt9 = res9.get("nextPageCursor") or ""
        if not nxt9 or not rows9:
            cur.pop("tlog_pg", None)
            return e
        if nxt9 in seen9:
            cur.pop("tlog_pg", None)
            raise RuntimeError("bybit transaction-log 페이지 커서 미전진")
        seen9.add(nxt9)
        cursor = nxt9
        cur["tlog_pg"] = {"s": s, "e": e, "cursor": cursor}


def _bb_tlog_pass(bcall, cur0, ev, seen, now_ms):
    cur = {k: cur0[k] for k in ("tlog_from", "tlog", "tlog_pg", "tlog_off", "tlog_err") if k in cur0}
    tl_from = cur.get("tlog_from")
    raw9 = []
    if not (isinstance(tl_from, int) and not isinstance(tl_from, bool) and tl_from > 0):
        cur.pop("tlog_from", None)
        if now_ms < (_fut_opt(cur.get("tlog_off")) or 0):
            return cur, None, raw9
        try:
            _bb_tlog_window(bcall, {}, now_ms - 3 * BB_TLOG_QUIET_MS, now_ms, raw9, [0])
            tm9 = [int(_fut_opt(r.get("transactionTime")) or 0) for r in raw9 if str(r.get("type") or "") in BB_TLOG_TYPES]
            open9 = False
            if not any(t9 >= now_ms - BB_TLOG_QUIET_MS for t9 in tm9):
                for sc9 in ("USDT", "USDC"):
                    pos9 = bcall("/v5/position/list", {"category": "linear", "settleCoin": sc9, "limit": 200})
                    pp9 = pos9.get("list") if isinstance(pos9, dict) else None
                    if not isinstance(pp9, list) or any(not isinstance(p9, dict) for p9 in pp9):
                        raise RuntimeError("bybit 전환 포지션 목록 결손·형식 오류")
                    if pos9.get("nextPageCursor") or any(_fut_req(p9.get("size"), "수량(size)") != 0 for p9 in pp9):
                        open9 = True
                        break
        except RateLimited:
            return cur, None, []
        except Exception as e9:   # noqa: BLE001 [fallback]
            cur["tlog_off"] = now_ms + BB_TLOG_OFF_MS
            log.warning("bybit 거래 내역(transaction-log) 조회 실패 — 선물 수수료·펀딩은 종전처럼 청산 시각(6시간 뒤 다시): %s", _xm(repr(e9))[:160])
            return cur, None, []
        cur.pop("tlog_off", None)
        if any(t9 >= now_ms - BB_TLOG_QUIET_MS for t9 in tm9):
            log.info("bybit 거래 내역 전환 미룸 — 최근 5분 선물 체결·정산 있음(다음 주기)")
            return cur, None, []
        if open9:
            log.info("bybit 거래 내역 전환 미룸 — 미청산 linear 포지션 있음(다음 주기)")
            return cur, None, []
        cur["tlog_from"] = cur["tlog"] = now_ms
        log.info("★bybit 선물 수수료·펀딩 = 낸 시각(transaction-log) 전환 — %s 부터(그 앞은 종전 closed-pnl)★",
                 time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_ms / 1000)))
        return cur, (now_ms - BB_TLOG_LAG_MS) // 1000, []
    c9 = _fut_opt(cur.get("tlog"))
    done9 = int(c9) if c9 is not None and tl_from <= c9 <= now_ms else tl_from
    s9 = max(tl_from, done9 - BB_TLOG_OVERLAP_MS)
    budget = [0]
    try:
        while s9 < now_ms:
            got9 = []
            try:
                e9 = _bb_tlog_window(bcall, cur, s9, min(s9 + 7 * DAY * 1000 - 1000, now_ms), got9, budget)
            finally:
                raw9.extend(got9)
                _bb_tlog_events(got9, tl_from, seen, ev)
            if e9 is None:
                log.info("bybit 거래 내역 따라잡는 중(주기 상한 %d쪽) — 덮은 시각 %s", BB_TLOG_CALLS_MAX,
                         time.strftime("%m-%d %H:%M", time.localtime(done9 / 1000)))
                break
            done9 = max(done9, e9)
            s9 = e9
        cur.pop("tlog_err", None)
    except Exception as e9:   # noqa: BLE001 [fallback]
        if now_ms - (_fut_opt(cur.get("tlog_err")) or 0) >= 3600 * 1000:
            cur["tlog_err"] = now_ms
            log.warning("bybit 거래 내역(transaction-log) 수집 실패 — 선물 정산 %s 까지만(다음 주기 다시): %s",
                        time.strftime("%m-%d %H:%M", time.localtime(done9 / 1000)), _xm(repr(e9))[:160])
    cur["tlog"] = done9
    return cur, (min(done9, now_ms) - BB_TLOG_LAG_MS) // 1000, raw9


def _fut_bybit(env):
    key, sec = env["TJ_BYBIT_KEY"], env["TJ_BYBIT_SECRET"]

    @_clock_retry
    def bcall(path, q):
        _gov_prepare("api.bybit.com", path)
        qs = urllib.parse.urlencode(q)
        ts = str(_srv_ms("api.bybit.com"))
        sig = ex_sign.bybit_sign(sec, ts, key, "10000", qs)
        d = http_json(f"https://api.bybit.com{path}?{qs}",
                      {"X-BAPI-API-KEY": key, "X-BAPI-TIMESTAMP": ts,
                       "X-BAPI-RECV-WINDOW": "10000", "X-BAPI-SIGN": sig})
        if d.get("retCode") != 0:
            if str(d.get("retCode")) == "10006":
                raise RateLimited(f"bybit 10006 {_xm(d.get('retMsg'))}", 429)
            raise RuntimeError(f"bybit {d.get('retCode')} {_xm(d.get('retMsg'))}")
        return d.get("result") or {}

    def bpages(path, params):
        params = dict(params)
        cursors = set()
        while True:
            result = bcall(path, params)
            rows = result.get("list")
            if not isinstance(rows, list) or any(not isinstance(r9, dict) for r9 in rows):
                raise RuntimeError(f"bybit {path} 목록 결손·형식 오류 — 스냅숏 보류")
            yield from rows
            cursor = result.get("nextPageCursor") or ""
            if not cursor:
                break
            if not rows or cursor in cursors:
                raise RuntimeError("bybit 선물 페이지 커서 미전진")
            cursors.add(cursor)
            params["cursor"] = cursor
            time.sleep(PACE)

    def bpage(path, params):
        result = bcall(path, params)
        rows = result.get("list")
        if not isinstance(rows, list) or any(not isinstance(r9, dict) for r9 in rows):
            raise RuntimeError(f"bybit {path} 목록 결손·형식 오류 — 가격 보강 보류")
        cur9 = result.get("nextPageCursor")
        return rows, (cur9 if isinstance(cur9, str) else "")

    st = statefile.read_json(_fut_path("bybit"), {})
    poss = []
    for p in bpages("/v5/position/list", {"category": "linear", "settleCoin": "USDT"}):
        if not isinstance(p, dict):
            raise RuntimeError("bybit position 행 형식 오류 — 스냅숏 보류")
        sz = _fut_req(p.get("size"), "수량(size)")
        if sz == 0:
            continue
        if p.get("side") not in ("Buy", "Sell"):
            raise RuntimeError("bybit position 방향(side) 모름 — 스냅숏 보류")
        poss.append({"symbol": p.get("symbol"),
                     "side": "LONG" if p.get("side") == "Buy" else "SHORT",
                     "qty": sz, "entry": float(p.get("avgPrice") or 0),
                     "mark": float(p.get("markPrice") or 0),
                     "upnl": _fut_opt(p.get("unrealisedPnl")),
                     "leverage": p.get("leverage"),
                     "liq": float(p.get("liqPrice") or 0)})
    ev = list(st.get("events") or [])
    seen = {r.get("uid") for r in ev}
    now_ms = int(time.time() * 1000)
    tlc9, tlcov9, tlraw9 = _bb_tlog_pass(bcall, dict(st.get("cursor") or {}), ev, seen, now_ms)
    tl9 = tlc9.get("tlog_from") if isinstance(tlc9.get("tlog_from"), int) else None

    def _cp_take(c):
        uid = f"bb:{c.get('orderId')}:{c.get('updatedTime')}"
        if uid in seen:
            return
        seen.add(uid)
        t9 = int(c.get("updatedTime") or 0)
        if tl9 is not None and t9 >= tl9:
            ev.append({"t": t9, "symbol": c.get("symbol") or "", "kind": "CLOSEDPNL", "amount": 0.0,
                       "net": _fut_opt(c.get("closedPnl")), "uid": uid})
            return
        ev.append({"t": t9, "symbol": c.get("symbol") or "", "kind": "REALIZED", "amount": float(c.get("closedPnl") or 0), "uid": uid})
    c0 = (st.get("cursor") or {}).get("closed_pnl")
    if isinstance(c0, (int, float)) and c0 > 0:
        s_ms = int(c0) - DAY * 1000
    else:
        bb_t = [int(r.get("t") or 0) for r in ev if str(r.get("uid") or "").startswith("bb:")]
        s_ms = (max(bb_t) - DAY * 1000) if bb_t else now_ms
    s_ms = max(now_ms - 729 * DAY * 1000, min(s_ms, now_ms - 7 * DAY * 1000))
    pxraw = []
    while s_ms < now_ms:
        e_ms = min(s_ms + 7 * DAY * 1000 - 1000, now_ms)
        time.sleep(PACE)
        for c in bpages("/v5/position/closed-pnl", {"category": "linear", "limit": 100,
                                                     "startTime": s_ms, "endTime": e_ms}):
            pxraw.append(c)
            _cp_take(c)
        s_ms = e_ms
    hist_lo = (st.get("cursor") or {}).get("hist_lo")
    tg9 = fut_first_t0("bybit", now_ms / 1000)
    if tg9 is not None:
        want9 = max(int(tg9) * 1000, now_ms - 729 * DAY * 1000)
        if not (isinstance(hist_lo, (int, float)) and hist_lo <= want9):
            bb_t9 = [int(r.get("t") or 0) for r in ev if str(r.get("uid") or "").startswith("bb:")]
            end9 = min((min(bb_t9) + DAY * 1000) if bb_t9 else now_ms, now_ms)
            try:
                add9, h9 = [], want9
                while h9 < end9:
                    e9 = min(h9 + 7 * DAY * 1000 - 1000, end9)
                    time.sleep(PACE)
                    add9.extend(bpages("/v5/position/closed-pnl", {"category": "linear", "limit": 100, "startTime": h9, "endTime": e9}))
                    h9 = e9
                pxraw.extend(add9)
                for c in add9:
                    _cp_take(c)
                hist_lo = want9
                log.info("bybit 선물 과거 청산손익 채움 %s~ · %d건", time.strftime("%Y-%m-%d", time.gmtime(want9 / 1000)), len(add9))
            except Exception as e:   # noqa: BLE001 [optional]
                log.warning("bybit 선물 과거 청산손익 채움 실패(다음 주기 재시도): %s", str(e)[:160])
    _fut_write("bybit", {"balance": None, "note": "통합계좌에 포함 — 잔고는 현물 집계에"},
               poss, ev, dict({"closed_pnl": now_ms}, **({"hist_lo": hist_lo} if hist_lo else {}), **tlc9),
               covered_through=tlcov9)
    _px_safe("bybit", lambda: _px_bybit(bpage, pxraw, ev, now_ms, tl=(tl9, tlraw9)))


PX_BB_EX_OFF_MS = 6 * 3600 * 1000


PX_BB_EX_PAD_MS = 30 * DAY * 1000


def _px_bb_window(bpage, cur, slot, path, s, e, conv, rows, budget):
    p9 = cur.get(slot)
    cursor = ""
    if isinstance(p9, dict):
        ps, pe, pc = fut_rcpt.num(p9.get("s")), fut_rcpt.num(p9.get("e")), p9.get("cursor")
        if ps is not None and pe is not None and 0 < ps <= pe and pe - ps < 7 * DAY * 1000 and isinstance(pc, str) and pc:
            s, e, cursor = int(ps), int(pe), pc
        else:
            cur.pop(slot, None)
    seen = {cursor} if cursor else set()
    while True:
        if budget[0] >= PX_CALLS_MAX:
            return None
        params = {"category": "linear", "limit": 100, "startTime": s, "endTime": e}
        if cursor:
            params["cursor"] = cursor
        time.sleep(PACE)
        budget[0] += 1
        try:
            got, nxt = bpage(path, params)
        except RateLimited:
            raise
        except Exception:
            if cursor:
                cur.pop(slot, None)
            raise
        rows.extend(conv(got))
        if not nxt or not got:
            cur.pop(slot, None)
            return s, e
        if nxt in seen:
            cur.pop(slot, None)
            raise RuntimeError("bybit 선물 페이지 커서 미전진")
        seen.add(nxt)
        cursor = nxt
        cur[slot] = {"s": s, "e": e, "cursor": cursor}


def _px_bybit_exec(bpage, cur, ev, now_ms, budget, rows):
    hi0 = fut_rcpt.num(cur.get("ex_hi"))
    first = hi0 is None
    s = int(hi0) - 3600 * 1000 if hi0 is not None and now_ms - 729 * DAY * 1000 < hi0 <= now_ms else now_ms - 7 * DAY * 1000 + 1000
    while s < now_ms:
        w = _px_bb_window(bpage, cur, "ex_rp", "/v5/execution/list", s, min(s + 7 * DAY * 1000 - 1000, now_ms), fut_rcpt.rows_bybit_exec, rows, budget)
        if w is None:
            return
        if first and not cur.get("ex_done") and fut_rcpt.num(cur.get("ex_lo")) is None:
            cur["ex_lo"] = w[0]
        first = False
        cur["ex_hi"] = w[1]
        s = w[1]
    if not cur.get("ex_done"):
        h9 = fut_rcpt.num(cur.get("ex_lo"))
        if h9 is None:
            return
        bb_t = [int(r.get("t") or 0) for r in ev if str(r.get("uid") or "").startswith(("bb:", "bbt:"))]
        if not bb_t:
            return
        lo = max(now_ms - 729 * DAY * 1000, min(bb_t) - PX_BB_EX_PAD_MS)
        hi = int(h9)
        while hi > lo:
            w = _px_bb_window(bpage, cur, "ex_hp", "/v5/execution/list", max(lo, hi - 7 * DAY * 1000 + 1000), hi, fut_rcpt.rows_bybit_exec, rows, budget)
            if w is None:
                return
            hi = w[0]
            cur["ex_lo"] = hi
        cur["ex_done"] = True
        cur.pop("ex_lo", None)
        log.info("bybit 선물 진입 체결 과거 채움 끝")


def _px_bybit(bpage, raw, ev, now_ms, tl=None):
    tl_from, tlraw = tl if isinstance(tl, tuple) and len(tl) == 2 else (None, ())
    st = fut_rcpt.load("bybit")
    cur = dict(st.get("cursor") or {})
    rows, budget = fut_rcpt.rows_bybit(raw), [0]
    if tl_from is not None:
        rows.extend(fut_rcpt.rows_bybit_tlog(tlraw, cp=raw))
    try:
        if not cur.get("bf_done"):
            bb_t = [int(r.get("t") or 0) for r in ev if str(r.get("uid") or "").startswith("bb:")]
            lo = max(now_ms - 729 * DAY * 1000, (min(bb_t) - DAY * 1000) if bb_t else now_ms)
            hi9 = fut_rcpt.num(cur.get("bf_hi"))
            hi = int(hi9) if hi9 is not None and lo < hi9 <= now_ms else now_ms - 6 * DAY * 1000
            while hi > lo:
                w = _px_bb_window(bpage, cur, "bf_pg", "/v5/position/closed-pnl", max(lo, hi - 7 * DAY * 1000 + 1000), hi, fut_rcpt.rows_bybit, rows, budget)
                if w is None:
                    break
                hi = w[0]
                cur["bf_hi"] = hi
            if hi <= lo:
                cur["bf_done"] = True
                cur.pop("bf_hi", None)
                log.info("bybit 선물 가격 과거 채움 끝(%d콜)", budget[0])
        if now_ms >= (fut_rcpt.num(cur.get("ex_off")) or 0):
            try:
                _px_bybit_exec(bpage, cur, ev, now_ms, budget, rows)
                cur.pop("ex_off", None)
            except RateLimited:
                raise
            except Exception as e9:   # noqa: BLE001 [fallback]
                cur["ex_off"] = now_ms + PX_BB_EX_OFF_MS
                log.warning("bybit 선물 진입 체결 조회 실패(6시간 뒤 다시 · 정산 무관): %s", _xm(repr(e9))[:160])
    finally:
        fut_rcpt.update("bybit", rows, now_ms, cursor=cur,
                        keep=None if tl_from is None else (lambda r9: not (str(r9.get("uid") or "").startswith("bb:") and r9["ts_ms"] >= tl_from)))
