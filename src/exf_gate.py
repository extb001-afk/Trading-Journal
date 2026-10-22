from __future__ import annotations
import hashlib
import time
import urllib.request
import ex_sign
from exf_net import DAY
from exf_net import PACE
from exf_net import _Bal
from exf_net import _DEP_DENIED
from exf_net import _add_to
from exf_net import _ak
from exf_net import _balance_rows
from exf_net import _clock_retry
from exf_net import _cv_fill
from exf_net import _debt_add
from exf_net import _gov_prepare
from exf_net import _srv_ms
from exf_net import _sub_bal
from exf_net import http_json
from exf_net import norm_fill
from exf_net import norm_row
import logging

log = logging.getLogger('tj-exf')

_GATE_FAIL = {"CANCEL": "CANCELLED", "FAIL": "FAILED", "INVALID": "FAILED"}


def fetch_gate(env, t0: int, t1: int, dep_t0: int = None):
    key, sec = env["TJ_GATE_KEY"], env["TJ_GATE_SECRET"]
    out_w, out_d = [], []
    _DEP_DENIED.discard(_ak("gate"))

    @_clock_retry
    def call(path, params):
        _gov_prepare("api.gateio.ws", path)
        qs = urllib.parse.urlencode(params)
        ts = str(_srv_ms("api.gateio.ws") // 1000)
        body_hash = hashlib.sha512(b"").hexdigest()
        sig = ex_sign.gate_sign(sec, "GET", path, qs, body_hash, ts)
        return http_json(f"https://api.gateio.ws{path}?{qs}",
                         {"KEY": key, "Timestamp": ts, "SIGN": sig})

    dep_denied = False
    d0 = t0 if dep_t0 is None else min(int(dep_t0), int(t0))
    s = d0
    while s < t1:
        e = min(s + 29 * DAY, t1)
        for path, bucket in (("/api/v4/wallet/withdrawals", "w"),
                             ("/api/v4/wallet/deposits", "d")):
            if bucket == "d" and dep_denied:
                continue
            if bucket == "w" and e <= t0:
                continue
            try:
                _gate_range(call, path, bucket, max(s, t0) if bucket == "w" else s, e, out_w, out_d)
            except urllib.error.HTTPError as ge:
                if bucket == "d" and ge.code == 403:
                    dep_denied = True
                    _DEP_DENIED.add(_ak("gate"))
                    log.warning("gate 입금 조회 권한 없음 — 출금만 수집 (Wallet 읽기 켜면 완성 · 입금은 그때 이 구간부터 다시)")
                    continue
                raise
        s = e
    if dep_t0 is not None and int(dep_t0) < int(t0) and not dep_denied:
        for r in out_d:
            r["late"] = 1
    return out_w, out_d


def _gate_range(call, path, bucket, s, e, out_w, out_d):
    offset = 0
    while True:
        rows = call(path, {"from": s, "to": e, "limit": 500, "offset": offset}) or []
        for row in rows:
            if bucket == "w":
                st = "DONE" if str(row.get("status", "")).upper() in ("DONE", "SUCCESS") \
                    else _GATE_FAIL.get(str(row.get("status", "")).upper(), "PENDING")
                out_w.append(norm_row("gate", row.get("id"), row.get("currency"),
                                      row.get("amount"), row.get("fee"), row.get("txid"),
                                      st, row.get("timestamp"), row.get("timestamp"),
                                      row.get("address"), row.get("memo"), row.get("chain")))
            else:
                st = "ACCEPTED" if str(row.get("status", "")).upper() in ("DONE", "SUCCESS") \
                    else _GATE_FAIL.get(str(row.get("status", "")).upper(), "PENDING")
                out_d.append(norm_row("gate", row.get("id"), row.get("currency"),
                                      row.get("amount"), 0, row.get("txid"), st,
                                      row.get("timestamp"), row.get("timestamp"), network=row.get("chain")))
        time.sleep(PACE)
        if len(rows) < 500:
            break
        offset += 500


def fills_gate(env, st, t0: int, t1: int):
    key, sec = env["TJ_GATE_KEY"], env["TJ_GATE_SECRET"]

    @_clock_retry
    def call(params):
        _gov_prepare("api.gateio.ws", "/api/v4/spot/my_trades")
        qs = urllib.parse.urlencode(params)
        ts = str(_srv_ms("api.gateio.ws") // 1000)
        body_hash = hashlib.sha512(b"").hexdigest()
        path = "/api/v4/spot/my_trades"
        sig = ex_sign.gate_sign(sec, "GET", path, qs, body_hash, ts)
        return http_json(f"https://api.gateio.ws{path}?{qs}",
                         {"KEY": key, "Timestamp": ts, "SIGN": sig})

    fills = []
    s = t0
    while s < t1:
        e = min(s + 29 * DAY, t1)
        page = 1
        while True:
            rows = call({"from": s, "to": e, "limit": 1000, "page": page}) or []
            for r in rows:
                b, _, q = str(r.get("currency_pair") or "").partition("_")
                fills.append(norm_fill("gate", f"{r.get('currency_pair')}:{r.get('id')}",
                                       r.get("create_time_ms"),
                                       b, q, str(r.get("side", "")).lower(), r.get("price"),
                                       r.get("amount"), r.get("fee"), r.get("fee_currency")))
            time.sleep(PACE)
            if len(rows) < 1000:
                break
            page += 1
        s = e
    return fills


def convert_gate(env, t0: int, t1: int):
    out, got = [], set()
    for page in range(1, 51):
        rows = _gate_get(env, "/api/v4/flash_swap/orders", {"status": 1, "limit": 100, "page": page})
        if not isinstance(rows, list):
            raise RuntimeError("gate flash_swap 응답 형식 오류")
        old9 = False
        for r in rows:
            if not isinstance(r, dict):
                continue
            try:
                ts9 = int(float(r.get("create_time") or 0))
            except (TypeError, ValueError):
                raise RuntimeError("gate flash_swap create_time 형식 오류") from None
            ts_ms = ts9 * 1000 if ts9 < 10 ** 12 else ts9
            if ts_ms < t0 * 1000:
                old9 = True
                continue
            if str(r.get("status")) not in ("1", "success", "SUCCESS"):
                continue
            tid = str(r.get("id") or "")
            if not tid or tid in got:
                continue
            f9 = _cv_fill("gate", tid, ts_ms, r.get("sell_currency"), r.get("sell_amount"), r.get("buy_currency"), r.get("buy_amount"))
            if f9 is None:
                raise RuntimeError("gate flash_swap 필드 누락/형식 오류")
            got.add(tid)
            out.append(f9)
        time.sleep(PACE)
        if old9 or len(rows) < 100:
            return out
    raise RuntimeError("gate flash_swap 50페이지 초과")


@_clock_retry
def _gate_get(env, path, params=None):
    _gov_prepare("api.gateio.ws", path)
    key, sec = env["TJ_GATE_KEY"], env["TJ_GATE_SECRET"]
    qs = urllib.parse.urlencode(params or {})
    ts = str(_srv_ms("api.gateio.ws") // 1000)
    bh = hashlib.sha512(b"").hexdigest()
    sig = ex_sign.gate_sign(sec, "GET", path, qs, bh, ts)
    return http_json(f"https://api.gateio.ws{path}" + (f"?{qs}" if qs else ""),
                     {"KEY": key, "Timestamp": ts, "SIGN": sig})


def _bal_gate(env):
    out = _Bal()
    for a in _balance_rows(_gate_get(env, "/api/v4/spot/accounts")):
        _add_to(out, a["currency"], float(a.get("available") or 0) + float(a.get("locked") or 0))

    def _gmargin(o):
        for pair in _balance_rows(_gate_get(env, "/api/v4/margin/accounts")):
            for side in ("base", "quote"):
                a2 = pair.get(side) or {}
                v = (float(a2.get("available") or 0) + float(a2.get("locked") or 0)
                     - float(a2.get("borrowed") or 0))
                if v < 0:
                    _debt_add(o, "gate", "margin", a2.get("currency"), v)
                else:
                    _add_to(o, a2.get("currency"), v)

    time.sleep(PACE)
    _sub_bal("gate", "margin", _gmargin, out)
    spot9 = dict(out)

    def _gcross(o):
        d2 = _gate_get(env, "/api/v4/margin/cross/accounts")
        bals = d2.get("balances") if isinstance(d2, dict) else None
        if not isinstance(bals, dict):
            raise RuntimeError("gate cross balances 누락/형식 오류")
        for ccy, b2 in bals.items():
            if not isinstance(b2, dict):
                raise RuntimeError("gate cross 행 형식 오류")
            held = float(b2.get("available") or 0) + float(b2.get("freeze") or 0)
            if held > 1e-8 and spot9.get(str(ccy).upper(), 0) < held * 0.5:
                raise RuntimeError(f"gate 교차 잔고 {ccy} 가 스팟에 없음 — 클래식 교차마진(별도 계정) 추정, 미지원")
            liab = float(b2.get("total_liab") or 0)
            if liab > 1e-6:
                _debt_add(o, "gate", "cross", ccy, -liab)

    time.sleep(PACE)
    _sub_bal("gate", "cross", _gcross, out, lenient=True)
    return out
