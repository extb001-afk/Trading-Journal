from __future__ import annotations
import base64
import hashlib
import hmac
import json
import re
import time
import urllib.request
from exf_net import DAY
from exf_net import DENY_COOL_SEC
from exf_net import PACE
from exf_net import RateLimited
from exf_net import SignatureExpired
from exf_net import _Bal
from exf_net import _add_to
from exf_net import _balance_rows
from exf_net import _clock_retry
from exf_net import _cv_fill
from exf_net import _debt_add
from exf_net import _err_body
from exf_net import _gov_prepare
from exf_net import _loan_amt
from exf_net import _recon_hold_clear
from exf_net import _srv_ms
from exf_net import _sub_bal
from exf_net import _xm
from exf_net import http_json
from exf_net import norm_fill
from exf_net import norm_row
import logging

log = logging.getLogger('tj-exf')

def fetch_kucoin(env, t0: int, t1: int):
    key, sec, pph = env["TJ_KUCOIN_KEY"], env["TJ_KUCOIN_SECRET"], env["TJ_KUCOIN_PASSPHRASE"]
    out_w, out_d = [], []

    @_clock_retry
    def call(path_with_qs):
        _gov_prepare("api.kucoin.com", path_with_qs.split("?", 1)[0])
        ts = str(_srv_ms("api.kucoin.com"))
        sig = base64.b64encode(hmac.new(sec.encode(), (ts + "GET" + path_with_qs).encode(),
                                        hashlib.sha256).digest()).decode()
        pph_sig = base64.b64encode(hmac.new(sec.encode(), pph.encode(),
                                            hashlib.sha256).digest()).decode()
        d = http_json("https://api.kucoin.com" + path_with_qs,
                      {"KC-API-KEY": key, "KC-API-SIGN": sig, "KC-API-TIMESTAMP": ts,
                       "KC-API-PASSPHRASE": pph_sig, "KC-API-KEY-VERSION": "2"})
        if d.get("code") != "200000":
            raise RuntimeError(f"kucoin {d.get('code')} {_xm(d.get('msg'))}")
        return d.get("data") or {}

    s = t0
    while s < t1:
        e = min(s + 7 * DAY, t1)
        for path, bucket in (("/api/v1/withdrawals", "w"), ("/api/v1/deposits", "d")):
            page = 1
            while True:
                qs = urllib.parse.urlencode({"startAt": s * 1000, "endAt": e * 1000,
                                             "pageSize": 50, "currentPage": page})
                data = call(f"{path}?{qs}")
                items = data.get("items") or []
                for row in items:
                    txid = str(row.get("walletTxId") or "").split("@")[0]
                    if bucket == "w":
                        st9 = str(row.get("status", "")).upper()
                        st = "DONE" if st9 == "SUCCESS" else ("FAILED" if st9 == "FAILURE" else "PENDING")
                        out_w.append(norm_row("kucoin", row.get("id"), row.get("currency"),
                                              row.get("amount"), row.get("fee"), txid, st,
                                              row.get("createdAt"), row.get("updatedAt"),
                                              row.get("address"), row.get("memo"), row.get("chain")))
                    else:
                        st9 = str(row.get("status", "")).upper()
                        st = "ACCEPTED" if st9 == "SUCCESS" else ("FAILED" if st9 == "FAILURE" else "PENDING")
                        nid = f"{row.get('currency')}:{txid}:{row.get('createdAt')}"
                        out_d.append(norm_row("kucoin", nid, row.get("currency"),
                                              row.get("amount"), 0, txid, st,
                                              row.get("createdAt"), row.get("updatedAt"), network=row.get("chain")))
                time.sleep(PACE)
                if page >= int(data.get("totalPage") or 1):
                    break
                page += 1
        s = e
    return out_w, out_d


def fills_kucoin(env, st, t0: int, t1: int):
    key, sec, pph = env["TJ_KUCOIN_KEY"], env["TJ_KUCOIN_SECRET"], env["TJ_KUCOIN_PASSPHRASE"]

    @_clock_retry
    def call(path_with_qs):
        _gov_prepare("api.kucoin.com", path_with_qs.split("?", 1)[0])
        ts = str(_srv_ms("api.kucoin.com"))
        sig = base64.b64encode(hmac.new(sec.encode(), (ts + "GET" + path_with_qs).encode(),
                                        hashlib.sha256).digest()).decode()
        pph_sig = base64.b64encode(hmac.new(sec.encode(), pph.encode(),
                                            hashlib.sha256).digest()).decode()
        d = http_json("https://api.kucoin.com" + path_with_qs,
                      {"KC-API-KEY": key, "KC-API-SIGN": sig, "KC-API-TIMESTAMP": ts,
                       "KC-API-PASSPHRASE": pph_sig, "KC-API-KEY-VERSION": "2"})
        if d.get("code") != "200000":
            raise RuntimeError(f"kucoin {d.get('code')} {_xm(d.get('msg'))}")
        return d.get("data") or {}

    fills = []
    s = t0
    while s < t1:
        e = min(s + 6 * DAY, t1)
        page = 1
        while True:
            qs = urllib.parse.urlencode({"startAt": s * 1000, "endAt": e * 1000,
                                         "pageSize": 500, "currentPage": page})
            data = call(f"/api/v1/fills?{qs}")
            items = data.get("items") or []
            for r in items:
                b, _, q = str(r.get("symbol") or "").partition("-")
                fills.append(norm_fill("kucoin", f"{r.get('symbol')}:{r.get('tradeId')}",
                                       r.get("createdAt"),
                                       b, q, str(r.get("side", "")).lower(), r.get("price"),
                                       r.get("size"), r.get("fee"), r.get("feeCurrency")))
            time.sleep(PACE)
            if page >= int(data.get("totalPage") or 1):
                break
            page += 1
        s = e
    return fills + _kucoin_hf_pass(call, st, t0, t1, fills)


KC_HF_LEDGER_PAGES = 50


KC_HF_FILL_PAGES = 100


KC_HF_DENY = ("kucoin 400007", "kucoin 400006", "kucoin 400003", "kucoin 404", "HTTPError 404", "HTTP Error 404", "HTTPError 401", "HTTPError 403",
              "HTTP Error 401", "HTTP Error 403")


def _kc_ctx_symbol(r):
    c9 = r.get("context") if isinstance(r, dict) else None
    if isinstance(c9, str):
        try:
            c9 = json.loads(c9)
        except ValueError:
            m9 = re.search(r'"symbol"\s*:\s*"([A-Za-z0-9]+-[A-Za-z0-9]+)"', c9)
            return m9.group(1).upper() if m9 else None
    if isinstance(c9, dict) and "-" in str(c9.get("symbol") or ""):
        return str(c9["symbol"]).upper()
    return None


def _kucoin_hf_window(call, s, e, have_ids):
    syms, last = set(), None
    for _ in range(KC_HF_LEDGER_PAGES):
        q9 = {"bizType": "TRADE_EXCHANGE", "startAt": s * 1000, "endAt": e * 1000, "limit": 200}
        if last:
            q9["lastId"] = last
        rows = call("/api/v1/hf/accounts/ledgers?" + urllib.parse.urlencode(q9))
        if isinstance(rows, dict):
            rows = rows.get("items") if "items" in rows else ([] if not rows else None)
        if not isinstance(rows, list):
            raise RuntimeError("kucoin hf ledgers 응답 형식 오류")
        for r in rows:
            sy = _kc_ctx_symbol(r)
            if sy:
                syms.add(sy)
        if len(rows) < 200:
            break
        last = rows[-1].get("id") if isinstance(rows[-1], dict) else None
        if not last:
            raise RuntimeError("kucoin hf ledgers 다음 쪽 id 없음")
        time.sleep(PACE)
    else:
        raise RuntimeError(f"kucoin hf ledgers {KC_HF_LEDGER_PAGES}쪽 초과")
    out = []
    for sy in sorted(syms):
        last = None
        for _ in range(KC_HF_FILL_PAGES):
            time.sleep(PACE)
            q9 = {"symbol": sy, "startAt": s * 1000, "endAt": e * 1000, "limit": 100}
            if last:
                q9["lastId"] = last
            data = call("/api/v1/hf/fills?" + urllib.parse.urlencode(q9))
            items = data.get("items") if isinstance(data, dict) else None
            if items is None and data in ({}, None):
                items = []
            if not isinstance(items, list):
                raise RuntimeError(f"kucoin hf fills {sy} 응답 형식 오류")
            for r in items:
                b, _, q = str(r.get("symbol") or sy).partition("-")
                f9 = norm_fill("kucoin", f"{r.get('symbol') or sy}:{r.get('tradeId')}", r.get("createdAt"),
                               b, q, str(r.get("side", "")).lower(), r.get("price"), r.get("size"), r.get("fee"), r.get("feeCurrency"))
                if f9["id"] in have_ids:
                    continue
                have_ids.add(f9["id"])
                out.append(f9)
            if len(items) < 100:
                break
            last = data.get("lastId") or (items[-1].get("id") if isinstance(items[-1], dict) else None)
            if not last:
                raise RuntimeError(f"kucoin hf fills {sy} 다음 쪽 id 없음")
        else:
            raise RuntimeError(f"kucoin hf fills {sy} {KC_HF_FILL_PAGES}쪽 초과")
    return out


def _kc_hf_transient(e, msg: str) -> bool:
    if isinstance(e, urllib.error.HTTPError):
        return int(getattr(e, "code", 0) or 0) >= 500
    if isinstance(e, (urllib.error.URLError, TimeoutError, ConnectionError)) or type(e) is OSError:
        return True
    m9 = re.search(r"kucoin (\d{6})", msg or "")
    if m9:
        return m9.group(1).startswith("5") or m9.group(1) == "429000"
    return "쪽 초과" in (msg or "")


def _kucoin_hf_pass(call, st, t0: int, t1: int, classic: list) -> list:
    now9 = int(time.time())
    regular = t1 >= now9 - 3600
    if float(st.get("kc_hf_off") or 0) > now9:
        return []
    have_ids = {f["id"] for f in classic}
    gap9 = int(st.get("kc_hf_gap") or 0) if regular else 0
    h0 = min(int(t0), gap9) if gap9 else int(t0)
    out = []
    s9 = h0
    try:
        while s9 < t1:
            e9 = min(s9 + 6 * DAY, t1)
            out += _kucoin_hf_window(call, s9, e9, have_ids)
            s9 = e9
    except (RateLimited, SignatureExpired):
        if regular:
            st["kc_hf_gap"] = h0
        raise
    except Exception as e9:
        msg9 = _xm(repr(e9))
        if isinstance(e9, urllib.error.HTTPError):
            msg9 += " " + _xm(_err_body(e9)[:200])
        tr9 = _kc_hf_transient(e9, msg9) and not any(k9 in msg9 for k9 in KC_HF_DENY)
        if not regular:
            if tr9:
                raise RuntimeError(f"kucoin HF 체결(과거 창) 일시 실패 — 이 조각 다음 주기에 다시: {msg9[:160]}") from None
            log.warning("kucoin HF 체결(과거 창) 결정적 오류 — 이 조각의 HF 체결 생략(옛 계정 체결은 정상): %s", msg9[:160])
            return []
        if not tr9:
            st["kc_hf_off"] = now9 + DENY_COOL_SEC
            _recon_hold_clear(st, "kc_hf")
            if gap9:
                st["kc_hf_lost"] = {"from": int(h0), "to": int(t0), "at": now9}
                st.pop("kc_hf_gap", None)
                log.warning("★kucoin HF 밀린 구간 %s~%s 회수 불가(결정적 오류) — 그 구간 HF 체결은 빠질 수 있음(수동 확인)★: %s",
                            time.strftime("%Y-%m-%d", time.localtime(h0)), time.strftime("%Y-%m-%d", time.localtime(t0)), msg9[:160])
            log.warning("kucoin HF 체결 조회 거부·결정적 오류 — %d시간 쉼(옛 계정 체결은 정상): %s", DENY_COOL_SEC // 3600, msg9[:160])
            return []
        st["kc_hf_gap"] = h0
        st["partial"] = (str(st.get("partial")) + " · " if st.get("partial") else "") + "쿠코인 HF 체결 일시 실패(밀린 하한 보존 — 다음 주기 다시)"
        _recon_hold_clear(st, "kc_hf")
        log.warning("kucoin HF 체결 조회 일시 실패(다음 주기에 %s 부터 다시 — 옛 계정 체결은 정상 · 이번 주기 완주·잔고 승격 보류): %s",
                    time.strftime("%m-%d %H:%M", time.localtime(h0)), msg9[:160])
        return []
    if regular:
        _recon_hold_clear(st, "kc_hf")
        st.pop("kc_hf_off", None)
        st.pop("kc_hf_gap", None)
        on9 = int(st.get("kc_hf_on") or 0)
        if not on9:
            on9 = st["kc_hf_on"] = now9
        for f in out:
            if gap9 or f["ts"] < on9 * 1000:
                f["late"] = 1
        if out:
            log.info("kucoin HF 계정 체결 %d건(옛 계정 체결과 겹침 제외%s)", len(out), " · 밀린 구간 회수" if gap9 else "")
    return out


@_clock_retry
def _kucoin_call(env, path_with_qs):
    _gov_prepare("api.kucoin.com", path_with_qs.split("?", 1)[0])
    key, sec, pph = env["TJ_KUCOIN_KEY"], env["TJ_KUCOIN_SECRET"], env["TJ_KUCOIN_PASSPHRASE"]
    ts = str(_srv_ms("api.kucoin.com"))
    sig = base64.b64encode(hmac.new(sec.encode(), (ts + "GET" + path_with_qs).encode(), hashlib.sha256).digest()).decode()
    pph_sig = base64.b64encode(hmac.new(sec.encode(), pph.encode(), hashlib.sha256).digest()).decode()
    d = http_json("https://api.kucoin.com" + path_with_qs,
                  {"KC-API-KEY": key, "KC-API-SIGN": sig, "KC-API-TIMESTAMP": ts,
                   "KC-API-PASSPHRASE": pph_sig, "KC-API-KEY-VERSION": "2"})
    if not isinstance(d, dict) or d.get("code") != "200000":
        raise RuntimeError(f"kucoin {(d or {}).get('code') if isinstance(d, dict) else '?'} "
                           f"{_xm((d or {}).get('msg')) if isinstance(d, dict) else _xm(str(d)[:80])}")
    return d.get("data")


def convert_kucoin(env, t0: int, t1: int):
    out, got = [], set()
    s = int(t0)
    while s < t1:
        e = min(s + 30 * DAY, int(t1))
        page = 1
        while True:
            qs = urllib.parse.urlencode({"startAt": s * 1000, "endAt": e * 1000, "page": page, "pageSize": 50})
            data = _kucoin_call(env, f"/api/v1/convert/order/history?{qs}")
            if not isinstance(data, dict) or not isinstance(data.get("items"), list):
                raise RuntimeError("kucoin convert items 누락/형식 오류")
            for r in data["items"]:
                if not isinstance(r, dict) or str(r.get("status") or "").upper() != "SUCCESS":
                    continue
                f9 = _cv_fill("kucoin", r.get("orderId") or r.get("clientOrderId"), r.get("orderTime") or r.get("createdAt"),
                              r.get("fromCurrency"), r.get("fromCurrencySize"), r.get("toCurrency"), r.get("toCurrencySize"))
                if f9 is None:
                    raise RuntimeError("kucoin convert SUCCESS 필드 누락/형식 오류")
                if f9["id"] in got:
                    continue
                got.add(f9["id"])
                out.append(f9)
            time.sleep(PACE)
            if page >= int(data.get("totalPage") or 1) or not data["items"]:
                break
            page += 1
            if page > 200:
                raise RuntimeError("kucoin convert 200페이지 초과")
        s = e
    return out


@_clock_retry
def _kucoin_get(env, path_with_qs):
    _gov_prepare("api.kucoin.com", path_with_qs.split("?", 1)[0])
    key, sec, pph = env["TJ_KUCOIN_KEY"], env["TJ_KUCOIN_SECRET"], env["TJ_KUCOIN_PASSPHRASE"]
    ts = str(_srv_ms("api.kucoin.com"))
    sig = base64.b64encode(hmac.new(sec.encode(), (ts + "GET" + path_with_qs).encode(),
                                    hashlib.sha256).digest()).decode()
    pph_sig = base64.b64encode(hmac.new(sec.encode(), pph.encode(),
                                        hashlib.sha256).digest()).decode()
    d = http_json("https://api.kucoin.com" + path_with_qs,
                  {"KC-API-KEY": key, "KC-API-SIGN": sig, "KC-API-TIMESTAMP": ts,
                   "KC-API-PASSPHRASE": pph_sig, "KC-API-KEY-VERSION": "2"})
    if d.get("code") != "200000":
        raise RuntimeError(f"kucoin {_xm(d.get('msg'))}")
    return d.get("data")


def _bal_kucoin(env):
    out = _Bal()
    v1_margin = {}
    for a in _balance_rows(_kucoin_get(env, "/api/v1/accounts")):
        v = float(a.get("balance") or 0)
        if v > 0:
            out[str(a["currency"]).upper()] = out.get(str(a["currency"]).upper(), 0) + v
            if str(a.get("type") or "").lower() in ("margin", "margin_v2"):
                _add_to(v1_margin, a["currency"], v)

    def _margin(o):
        d2 = _kucoin_get(env, "/api/v3/margin/accounts?quoteCurrency=USDT")
        if not isinstance(d2, dict):
            raise RuntimeError("kucoin margin 응답 형식 오류")
        for a2 in _balance_rows(d2.get("accounts")):
            k9, t9 = _loan_amt(a2, "currency", "total", "kucoin 마진 자산")
            k9, v9 = _loan_amt(a2, "currency", "liability", "kucoin 마진 부채")
            _add_to(o, k9, t9)
            if v9 > 0:
                _debt_add(o, "kucoin", "margin", k9, -v9)

    time.sleep(PACE)
    _sub_bal("kucoin", "margin", _margin, out, extra_deny=("enable the margin trading",), lenient=True)
    if "margin" in out.sources:
        for k9, v9 in v1_margin.items():
            out[k9] = out.get(k9, 0) - v9
            if out[k9] <= 1e-12:
                del out[k9]
    return out


@_clock_retry
def _kucoin_fut_get(env, path_with_qs):
    _gov_prepare("api-futures.kucoin.com", path_with_qs.split("?", 1)[0])
    key, sec, pph = env["TJ_KUCOIN_KEY"], env["TJ_KUCOIN_SECRET"], env["TJ_KUCOIN_PASSPHRASE"]
    ts = str(_srv_ms("api-futures.kucoin.com"))
    sig = base64.b64encode(hmac.new(sec.encode(), (ts + "GET" + path_with_qs).encode(), hashlib.sha256).digest()).decode()
    pph_sig = base64.b64encode(hmac.new(sec.encode(), pph.encode(), hashlib.sha256).digest()).decode()
    d = http_json("https://api-futures.kucoin.com" + path_with_qs,
                  {"KC-API-KEY": key, "KC-API-SIGN": sig, "KC-API-TIMESTAMP": ts,
                   "KC-API-PASSPHRASE": pph_sig, "KC-API-KEY-VERSION": "2"})
    if not isinstance(d, dict) or d.get("code") != "200000":
        raise RuntimeError(f"kucoin futures {_xm((d or {}).get('code') if isinstance(d, dict) else '')} {_xm((d or {}).get('msg') if isinstance(d, dict) else str(d)[:80])}")
    return d.get("data")


def _kucoin_pub_get(path_with_qs):
    d = http_json("https://api.kucoin.com" + path_with_qs)
    if not isinstance(d, dict) or d.get("code") != "200000":
        raise RuntimeError(f"kucoin public {_xm((d or {}).get('msg') if isinstance(d, dict) else str(d)[:80])}")
    return d.get("data")
