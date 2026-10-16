from __future__ import annotations
import base64
import hashlib
import hmac
import time
import urllib.request
import common
import bf_engine
import calendar
from exf_net import DAY
from exf_net import PACE
from exf_net import PX_CALLS_MAX
from exf_net import _Bal
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
from exf_net import _loan_add
from exf_net import _loan_amt
from exf_net import _px_safe
from exf_net import _srv_ms
from exf_net import _sub_bal
from exf_net import _xm
from exf_net import fut_rcpt
from exf_net import http_json
from exf_net import norm_fill
from exf_net import norm_row
import logging

log = logging.getLogger('tj-exf')

def _okx_ts(ms: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ms // 1000)) + f".{ms % 1000:03d}Z"


_OKX_WD_FAIL = {"-2": "CANCELLED", "-1": "FAILED"}


def fetch_okx(env, t0: int, t1: int):
    key, sec, pph = env["TJ_OKX_KEY"], env["TJ_OKX_SECRET"], env["TJ_OKX_PASSPHRASE"]
    out_w, out_d = [], []

    @_clock_retry
    def call(path, params):
        _gov_prepare("www.okx.com", path)
        qs = urllib.parse.urlencode(params)
        full = path + ("?" + qs if qs else "")
        ts = _okx_ts(_srv_ms("www.okx.com"))
        sig = base64.b64encode(hmac.new(sec.encode(), (ts + "GET" + full).encode(),
                                        hashlib.sha256).digest()).decode()
        d = http_json("https://www.okx.com" + full,
                      {"OK-ACCESS-KEY": key, "OK-ACCESS-SIGN": sig,
                       "OK-ACCESS-TIMESTAMP": ts, "OK-ACCESS-PASSPHRASE": pph})
        if d.get("code") != "0":
            raise RuntimeError(f"okx {d.get('code')} {_xm(d.get('msg'))}")
        return d.get("data") or []

    for path, bucket in (("/api/v5/asset/withdrawal-history", "w"),
                         ("/api/v5/asset/deposit-history", "d")):
        after = ""
        got = set()
        while True:
            p = {"limit": 100}
            if after:
                p["after"] = after
            rows = call(path, p)
            if not rows:
                break
            n_new = 0
            for row in rows:
                ts_ms = int(row.get("ts") or 0)
                if bucket == "w":
                    st = "DONE" if str(row.get("state")) == "2" else _OKX_WD_FAIL.get(str(row.get("state")), "PENDING")
                    r9 = norm_row("okx", row.get("wdId"), row.get("ccy"),
                                  row.get("amt"), row.get("fee"), row.get("txId"),
                                  st, ts_ms, ts_ms, row.get("to"),
                                  row.get("tag") or row.get("memo") or row.get("pmtId"), row.get("chain"))
                else:
                    st = "ACCEPTED" if str(row.get("state")) == "2" else "PENDING"
                    nid = row.get("depId") or f"{row.get('ccy')}:{row.get('txId')}"
                    r9 = norm_row("okx", nid, row.get("ccy"), row.get("amt"),
                                  0, row.get("txId"), st, ts_ms, ts_ms, network=row.get("chain"))
                if r9["uuid"] in got:
                    continue
                got.add(r9["uuid"])
                n_new += 1
                (out_w if bucket == "w" else out_d).append(r9)
            oldest = min(int(r.get("ts") or 0) for r in rows)
            time.sleep(PACE)
            if oldest // 1000 <= t0 or len(rows) < 100:
                break
            if after and n_new == 0:
                raise RuntimeError("okx 입출금 페이지 시각 미전진 — 다음 주기 재시도")
            after = str(oldest + 1)
    return out_w, out_d


def fills_okx(env, st, t0: int, t1: int):
    key, sec, pph = env["TJ_OKX_KEY"], env["TJ_OKX_SECRET"], env["TJ_OKX_PASSPHRASE"]

    @_clock_retry
    def call(params):
        _gov_prepare("www.okx.com", "/api/v5/trade/fills-history")
        qs = urllib.parse.urlencode(params)
        full = "/api/v5/trade/fills-history" + ("?" + qs if qs else "")
        ts = _okx_ts(_srv_ms("www.okx.com"))
        sig = base64.b64encode(hmac.new(sec.encode(), (ts + "GET" + full).encode(),
                                        hashlib.sha256).digest()).decode()
        d = http_json("https://www.okx.com" + full,
                      {"OK-ACCESS-KEY": key, "OK-ACCESS-SIGN": sig,
                       "OK-ACCESS-TIMESTAMP": ts, "OK-ACCESS-PASSPHRASE": pph})
        if d.get("code") != "0":
            raise RuntimeError(f"okx {d.get('code')} {_xm(d.get('msg'))}")
        return d.get("data") or []

    fills = []
    after = ""
    seen_pages = set()
    while True:
        p = {"instType": "SPOT", "limit": 100}
        if after:
            p["after"] = after
        rows = call(p)
        if not rows:
            break
        for r in rows:
            if int(r.get("ts") or 0) < t0 * 1000:
                continue
            inst = str(r.get("instId") or "")
            b, _, q = inst.partition("-")
            try:
                fee_ok = -float(r.get("fee") or 0)
            except (TypeError, ValueError):
                fee_ok = 0
            fills.append(norm_fill("okx", r.get("billId"), r.get("ts"), b, q,
                                   str(r.get("side", "")).lower(), r.get("fillPx"),
                                   r.get("fillSz"), fee_ok, r.get("feeCcy")))
        oldest = min(int(r.get("ts") or 0) for r in rows)
        time.sleep(PACE)
        if oldest // 1000 <= t0 or len(rows) < 100:
            break
        nxt = rows[-1].get("billId") or str(oldest)
        if nxt in seen_pages:
            raise RuntimeError("okx 체결 페이지 커서 순환 — 다음 주기 재시도")
        seen_pages.add(nxt)
        after = nxt
    return fills


def convert_okx(env, t0: int, t1: int):
    out, got = [], set()
    after = ""
    for _pg in range(200):
        p = {"limit": 100}
        if after:
            p["after"] = after
        rows = _okx_get(env, "/api/v5/asset/convert/history", p)
        if not isinstance(rows, list):
            raise RuntimeError("okx convert data 형식 오류")
        if not rows:
            break
        n_new = 0
        for r in rows:
            if not isinstance(r, dict):
                continue
            tid = str(r.get("tradeId") or r.get("clTReqId") or "")
            if not tid or tid in got:
                continue
            got.add(tid)
            n_new += 1
            if str(r.get("state") or "").lower() not in ("fullyfilled", "filled", "success"):
                continue
            if int(float(r.get("ts") or 0)) < t0 * 1000:
                continue
            side = str(r.get("side") or "").lower()
            if side not in ("buy", "sell"):
                raise RuntimeError("okx convert side 누락/형식 오류")
            if side == "buy":
                f9 = _cv_fill("okx", tid, r.get("ts"), r.get("quoteCcy"), r.get("fillQuoteSz"), r.get("baseCcy"), r.get("fillBaseSz"))
            else:
                f9 = _cv_fill("okx", tid, r.get("ts"), r.get("baseCcy"), r.get("fillBaseSz"), r.get("quoteCcy"), r.get("fillQuoteSz"))
            if f9 is None:
                raise RuntimeError("okx convert 체결 필드 누락/형식 오류")
            out.append(f9)
        oldest = min(int(float(r.get("ts") or 0)) for r in rows if isinstance(r, dict)) if rows else 0
        time.sleep(PACE)
        if oldest // 1000 <= t0 or len(rows) < 100:
            break
        if after and n_new == 0:
            raise RuntimeError("okx convert 페이지 시각 미전진")
        after = str(oldest + 1)
    else:
        raise RuntimeError("okx convert 200페이지 초과")
    return out


@_clock_retry
def _okx_get(env, path, params=None):
    _gov_prepare("www.okx.com", path)
    key, sec, pph = env["TJ_OKX_KEY"], env["TJ_OKX_SECRET"], env["TJ_OKX_PASSPHRASE"]
    qs = urllib.parse.urlencode(params or {})
    full = path + ("?" + qs if qs else "")
    ts = _okx_ts(_srv_ms("www.okx.com"))
    sig = base64.b64encode(hmac.new(sec.encode(), (ts + "GET" + full).encode(),
                                    hashlib.sha256).digest()).decode()
    d = http_json("https://www.okx.com" + full,
                  {"OK-ACCESS-KEY": key, "OK-ACCESS-SIGN": sig,
                   "OK-ACCESS-TIMESTAMP": ts, "OK-ACCESS-PASSPHRASE": pph})
    if d.get("code") != "0":
        raise RuntimeError(f"okx {d.get('code')} {_xm(d.get('msg'))}")
    if path in ("/api/v5/account/balance", "/api/v5/asset/balances", "/api/v5/finance/savings/balance",
                "/api/v5/finance/staking-defi/orders-active", "/api/v5/finance/flexible-loan/loan-info",
                "/api/v5/account/positions",
                "/api/v5/account/bills", "/api/v5/account/bills-archive"):
        return _balance_rows(d.get("data"))
    return d.get("data") or []


def _bal_okx(env):
    out = _Bal()
    for row in _okx_get(env, "/api/v5/account/balance"):
        for c in _balance_rows(row.get("details")):
            v = float(c.get("cashBal") or c.get("availBal") or 0)
            if v > 0:
                out[str(c["ccy"]).upper()] = out.get(str(c["ccy"]).upper(), 0) + v
            elif v < 0:
                _debt_add(out, "okx", "trading", c.get("ccy"), v)
    time.sleep(PACE)
    for c in _okx_get(env, "/api/v5/asset/balances"):
        v = float(c.get("bal") or 0)
        if v > 0:
            out[str(c["ccy"]).upper()] = out.get(str(c["ccy"]).upper(), 0) + v

    def _savings(o):
        rows = _okx_get(env, "/api/v5/finance/savings/balance")
        if not isinstance(rows, list):
            raise RuntimeError("okx savings data 형식 오류")
        for r2 in rows:
            _earn_amount(o, r2, "ccy", "amt")

    def _staking(o):
        after9, seen9 = "", set()
        for _p in range(20):
            p9 = {"limit": 100}
            if after9:
                p9["after"] = after9
            rows = _okx_get(env, "/api/v5/finance/staking-defi/orders-active", p9)
            if not isinstance(rows, list):
                raise RuntimeError("okx staking data 형식 오류")
            for r2 in rows:
                if not isinstance(r2, dict):
                    raise RuntimeError("okx staking 행 형식 오류")
                for inv in _balance_rows(r2.get("investData")):
                    _earn_amount(o, inv, "ccy", "amt")
            if len(rows) < 100:
                return
            nxt = str(rows[-1].get("ordId") or "")
            if not nxt or nxt in seen9:
                raise RuntimeError("okx staking 페이지 미전진")
            seen9.add(nxt)
            after9 = nxt
            time.sleep(PACE)
        raise RuntimeError("okx staking 20페이지 초과 — 부분 잔고 폐기")

    def _loan(o):
        rows = _okx_get(env, "/api/v5/finance/flexible-loan/loan-info")
        recs = []
        for r in rows:
            if not isinstance(r, dict):
                raise RuntimeError("okx loan-info 행 형식 오류")
            coll, debt = {}, {}
            for c in _balance_rows(r.get("collateralData")):
                k9, v9 = _loan_amt(c, "ccy", "amt", "okx 대출 담보")
                coll[k9] = coll.get(k9, 0) + v9
            for c in _balance_rows(r.get("loanData")):
                k9, v9 = _loan_amt(c, "ccy", "amt", "okx 대출 차입")
                debt[k9] = debt.get(k9, 0) + v9
            if any(v > 0 for v in coll.values()) or any(v > 0 for v in debt.values()):
                recs.append((r, coll, debt))
        if not recs:
            return
        since, evs, prin, prin_bad = None, [], {}, False
        if any(v > 0 for _, _, d9 in recs for v in d9.values()):
            time.sleep(PACE)
            hist = _okx_get(env, "/api/v5/finance/flexible-loan/loan-history", {"limit": "100"})
            if not isinstance(hist, list):
                raise RuntimeError("okx loan-history data 형식 오류")
            for h9 in hist:
                if not isinstance(h9, dict):
                    raise RuntimeError("okx loan-history 행 형식 오류")
                try:
                    t9 = int(int(h9.get("ts")) / 1000)
                except (TypeError, ValueError):
                    raise RuntimeError("okx loan-history ts 형식 오류") from None
                typ9 = str(h9.get("type") or "")
                if typ9 in ("borrowed", "collateral_locked"):
                    since = t9 if since is None else min(since, t9)
                if typ9 in ("borrowed", "repaid"):
                    try:
                        c9 = str(h9.get("ccy") or "").upper()
                        prin[c9] = prin.get(c9, 0.0) + (abs(float(h9.get("amt"))) * (1 if typ9 == "borrowed" else -1))
                    except (TypeError, ValueError):
                        prin_bad = True
                if len(evs) < 20:
                    try:
                        a9 = float(h9.get("amt"))
                    except (TypeError, ValueError):
                        a9 = None
                    evs.append({"ts": t9, "type": typ9, "ccy": str(h9.get("ccy") or "").upper(), "amt": a9})
        for r, coll, debt in recs:
            ex9 = {}
            for k9, f9 in (("curLTV", "ltv"), ("liqLTV", "liqLtv"), ("marginCallLTV", "callLtv")):
                try:
                    ex9[f9] = float(r.get(k9))
                except (TypeError, ValueError):
                    pass
            try:
                ex9["liqPx"] = float((r.get("riskWarningData") or {}).get("liqPx"))
                ex9["liqPair"] = str((r.get("riskWarningData") or {}).get("instId") or "")
            except (TypeError, ValueError, AttributeError):
                pass
            if evs:
                ex9["events"] = evs
            if prin and not prin_bad and len(hist) < 100:
                ex9["principal"] = {k9: v9 for k9, v9 in prin.items() if v9 > 0}
            _loan_add(o, "okx", "loan", "flexible-loan", "OKX 담보대출", coll, debt, since=since, extra=ex9)

    okx_deny = ("okx 50120", "okx 50030", "okx 50125", "okx 50119", "okx 58350")
    for src, fn in (("savings", _savings), ("staking", _staking), ("loan", _loan)):
        time.sleep(PACE)
        _sub_bal("okx", src, fn, out, extra_deny=okx_deny, lenient=True)
    return out


def _okx_notional(p, pos, ct_get):
    nu = _fut_opt(p.get("notionalUsd"))
    if nu:
        return abs(nu)
    cv, mk = _fut_opt(ct_get(p.get("instId"))), _fut_opt(p.get("markPx"))
    return abs(pos) * cv * mk if (cv and mk and cv > 0 and mk > 0) else None


def _fut_okx(env):
    poss = []
    ct9 = []

    def ct_get(iid):
        if not ct9:
            try:
                ct9.append((fut_rcpt.load("okx").get("ct") or {}) if fut_rcpt else {})
            except Exception:
                ct9.append({})
        return ct9[0].get(iid)
    for p in _okx_get(env, "/api/v5/account/positions"):
        if not isinstance(p, dict):
            raise RuntimeError("okx position 행 형식 오류 — 스냅숏 보류")
        pos = _fut_req(p.get("pos"), "수량(pos)")
        if pos == 0:
            continue
        if p.get("posSide") not in ("long", "short", "net"):
            raise RuntimeError("okx position 방향(posSide) 모름 — 스냅숏 보류")
        poss.append({"symbol": p.get("instId"), "notional": _okx_notional(p, pos, ct_get),
                     "side": (str(p.get("posSide")).upper() if p.get("posSide") in ("long", "short")
                              else ("LONG" if pos > 0 else "SHORT")),
                     "qty": abs(pos), "entry": float(p.get("avgPx") or 0),
                     "mark": float(p.get("markPx") or 0),
                     "upnl": _fut_opt(p.get("upl")), "leverage": p.get("lever"),
                     "liq": float(p.get("liqPx") or 0),
                     "settle": (str(p.get("ccy") or "").strip().upper() or None), "inst_type": p.get("instType") or None})
    st = common.read_json(_fut_path("okx"), {})
    ev = list(st.get("events") or [])
    seen = {r.get("uid") for r in ev}
    time.sleep(PACE)
    def bills(path="/api/v5/account/bills", extra=None):
        params = {"instType": "SWAP", "limit": "100"}
        params.update(extra or {})
        cursors = set()
        while True:
            rows = _okx_get(env, path, params)
            yield from rows
            if len(rows) < 100:
                break
            cursor = rows[-1].get("billId")
            if not cursor or cursor in cursors:
                raise RuntimeError("okx 선물 페이지 커서 미전진")
            cursors.add(cursor)
            params["after"] = cursor
            time.sleep(PACE)

    now_ms = int(time.time() * 1000)
    c0 = (st.get("cursor") or {}).get("bills")
    if isinstance(c0, (int, float)) and c0 > 0:
        begin = int(c0) - DAY * 1000
    else:
        ok_t = [int(r.get("t") or 0) for r in ev if str(r.get("uid") or "").startswith("ok:")]
        begin = (max(ok_t) - DAY * 1000) if ok_t else None
    srcs = [bills()]
    if begin is not None and begin < now_ms - 6 * DAY * 1000:
        lo9 = now_ms - 89 * DAY * 1000
        if begin < lo9:
            log.warning("okx 선물 정산 공백이 3개월 초과(%s~) — %s 이전은 API 로 조회 불가",
                        time.strftime("%Y-%m-%d", time.gmtime(begin / 1000)), time.strftime("%Y-%m-%d", time.gmtime(lo9 / 1000)))
            begin = lo9
        srcs.append(bills("/api/v5/account/bills-archive", {"begin": str(begin), "end": str(now_ms - 6 * DAY * 1000)}))
    hist_lo = (st.get("cursor") or {}).get("hist_lo")
    tg9 = bf_engine.SINCE.target("okx")
    if tg9:
        g9 = time.gmtime(now_ms / 1000)
        y9, m9 = g9.tm_year, g9.tm_mon - 3
        if m9 <= 0:
            y9, m9 = y9 - 1, m9 + 12
        floor9 = (calendar.timegm((y9, m9, 1, 0, 0, 0)) + 3600) * 1000
        want9 = max(int(tg9) * 1000, floor9)
        if not (isinstance(hist_lo, (int, float)) and hist_lo <= want9):
            ok_t9 = [int(r.get("t") or 0) for r in ev if str(r.get("uid") or "").startswith("ok:")]
            end9 = min((min(ok_t9) + DAY * 1000) if ok_t9 else now_ms, now_ms - 6 * DAY * 1000)
            try:
                hist9 = list(bills("/api/v5/account/bills-archive", {"begin": str(want9), "end": str(end9)})) if want9 < end9 else []
                srcs.append(hist9)
                hist_lo = want9
                log.info("okx 선물 과거 정산 채움 %s~%s · %d건", time.strftime("%Y-%m-%d", time.gmtime(want9 / 1000)),
                         time.strftime("%Y-%m-%d", time.gmtime(end9 / 1000)), len(hist9))
            except Exception as e:
                log.warning("okx 선물 과거 정산 채움 실패(다음 주기 재시도): %s", str(e)[:160])
    import itertools as _it
    pxraw = []
    for b in _it.chain(*srcs):
        pxraw.append(b)
        bid = b.get("billId")
        t9 = int(b.get("ts") or 0)
        base_uid = f"ok:{bid}"
        pnl = float(b.get("pnl") or 0)
        fee = float(b.get("fee") or 0)
        kind9 = "FUNDING" if str(b.get("type")) == "8" else "REALIZED"
        ccy9 = {"asset": str(b.get("ccy")).strip().upper()} if str(b.get("ccy") or "").strip() else {}
        if pnl != 0 and base_uid + ":p" not in seen:
            seen.add(base_uid + ":p")
            ev.append(dict({"t": t9, "symbol": b.get("instId") or "", "kind": kind9,
                            "amount": pnl, "uid": base_uid + ":p"}, **ccy9))
        if fee != 0 and base_uid + ":f" not in seen:
            seen.add(base_uid + ":f")
            ev.append(dict({"t": t9, "symbol": b.get("instId") or "", "kind": "FEE",
                            "amount": fee, "uid": base_uid + ":f"}, **ccy9))
    _fut_write("okx", {"balance": None, "note": "트레이딩 계정에 포함 — 잔고는 현물 집계에"},
               poss, ev, dict({"bills": now_ms}, **({"hist_lo": hist_lo} if hist_lo else {})))
    _px_safe("okx", lambda: _px_okx(bills, pxraw, now_ms))


PX_OKX_CT_MAX = 5


PX_OKX_BF_V = getattr(fut_rcpt, "OKX_BF_V", 2)


def _px_okx(bills, raw, now_ms):
    st = fut_rcpt.load("okx")
    cur, ct = dict(st.get("cursor") or {}), dict(st.get("ct") or {})
    rows = fut_rcpt.rows_okx(raw)
    try:
        if not cur.get("bf_done") or cur.get("bf_v") != PX_OKX_BF_V:
            job = cur.get("bf_job") if isinstance(cur.get("bf_job"), dict) else {}
            b9, e9, a9 = fut_rcpt.num(job.get("b")), fut_rcpt.num(job.get("e")), job.get("after")
            if job.get("v") != PX_OKX_BF_V or b9 is None or e9 is None or not 0 < b9 < e9:
                b9, e9, a9 = now_ms - 89 * DAY * 1000, now_ms - 6 * DAY * 1000, None
            a9 = fut_rcpt.safe(a9, 40) if isinstance(a9, str) else ""
            ex9 = dict({"begin": str(int(b9)), "end": str(int(e9))}, **({"after": a9} if a9 else {}))
            got, last9, done9 = [], a9, False
            try:
                for b in bills("/api/v5/account/bills-archive", ex9):
                    got.append(b)
                    if isinstance(b, dict) and b.get("billId"):
                        last9 = fut_rcpt.safe(b.get("billId"), 40) or last9
                    if len(got) >= PX_CALLS_MAX * 100:
                        break
                else:
                    done9 = True
            finally:
                rows += fut_rcpt.rows_okx(got)
                if done9:
                    cur["bf_done"], cur["bf_v"] = True, PX_OKX_BF_V
                    cur.pop("bf_job", None)
                    log.info("okx 선물 가격 과거 채움 끝(bills %d건)", len(got))
                else:
                    cur["bf_job"] = {"v": PX_OKX_BF_V, "b": int(b9), "e": int(e9), "after": last9}
                    log.info("okx 선물 가격 과거 채움 이어서(이번 bills %d건 · 다음 주기)", len(got))
        miss = {k: v for k, v in (cur.get("ct_miss") or {}).items() if isinstance(v, (int, float)) and v > now_ms - DAY * 1000}
        need = sorted({r["symbol"] for r in rows + list(st.get("rows") or []) if isinstance(r, dict) and r.get("qty_ct") and r.get("symbol") not in ct and r.get("symbol") not in miss})
        for iid in need[:PX_OKX_CT_MAX]:
            time.sleep(PACE)
            miss[iid] = now_ms
            d9 = http_json("https://www.okx.com/api/v5/public/instruments?" + urllib.parse.urlencode({"instType": "SWAP", "instId": iid}))
            if isinstance(d9, dict) and str(d9.get("code")) == "0":
                ct.update(fut_rcpt.okx_ct(d9.get("data")))
            if iid in ct:
                miss.pop(iid, None)
        cur["ct_miss"] = miss
    finally:
        fut_rcpt.update("okx", rows, now_ms, cursor=cur, ct=ct)


def _okx_fills_floor(now: int) -> int:
    t = time.gmtime(now)
    y, m = t.tm_year, t.tm_mon - 3
    while m <= 0:
        y, m = y - 1, m + 12
    import calendar
    return int(calendar.timegm((y, m, 1, 0, 0, 0)))
