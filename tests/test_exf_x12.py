#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import base64
import io
import json
import os
import time
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone

json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import common
import ex_foreign as XF
import upbit_link as UL

chk = T.chk
XF.PACE = 0
UL.time.sleep = lambda *_a, **_k: None
HAS = hasattr(XF, "_CLOCK_ON")
KST = timezone(timedelta(hours=9))
NOW = int(time.time())

print("[C] 서버 시각 보정")
SKEW = [30000]
TIME_BAD = [False]
CALLS = []


class _Resp:
    def __init__(self, body, hdrs=None):
        self._b = json.dumps(body).encode()
        self.headers = hdrs or {}
        self.status = 200

    def read(self, n=-1):
        b, self._b = (self._b, b"") if n is None or n < 0 else (self._b[:n], self._b[n:])
        return b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _err(url, code, body):
    return urllib.error.HTTPError(url, code, "x", {}, io.BytesIO(json.dumps(body).encode()))


def _srv():
    return time.time() * 1000 + SKEW[0]


def _jwt_ts(auth):
    p = auth.split(" ", 1)[1].split(".")[1]
    return int(json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))["timestamp"])


def _ts_of(u, h):
    host = u.hostname
    if host.endswith("binance.com"):
        return int(urllib.parse.parse_qs(u.query)["timestamp"][0])
    if host == "api.bybit.com":
        return int(h["x-bapi-timestamp"])
    if host == "www.okx.com":
        return int(datetime.strptime(h["ok-access-timestamp"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp() * 1000) \
            + int(h["ok-access-timestamp"][20:23])
    if host == "api.kucoin.com":
        return int(h["kc-api-timestamp"])
    if host == "api.gateio.ws":
        return int(h["timestamp"]) * 1000
    if host == "api.bithumb.com":
        return _jwt_ts(h["authorization"])
    raise AssertionError(host)


TIME_PATHS = {"/api/v3/time", "/v5/market/time", "/api/v5/public/time", "/api/v1/timestamp", "/api/v4/spot/time", "/v1/ticker"}


def fake_urlopen(req, timeout=None):
    url = req.full_url
    u = urllib.parse.urlsplit(url)
    h = {k.lower(): v for k, v in req.header_items()}
    if u.path in TIME_PATHS:
        CALLS.append(("time", u.hostname))
        s = int(time.time() * 1000) if TIME_BAD[0] else int(_srv())
        body = {"/api/v3/time": {"serverTime": s}, "/v5/market/time": {"retCode": 0, "result": {"timeSecond": str(s // 1000)}, "time": s},
                "/api/v5/public/time": {"code": "0", "data": [{"ts": str(s)}]}, "/api/v1/timestamp": {"code": "200000", "data": s},
                "/api/v4/spot/time": {"server_time": s}, "/v1/ticker": [{"market": "KRW-BTC"}]}[u.path]
        hd = {"Date": time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(s / 1000.0))}
        return _Resp(body, hd)
    ts = _ts_of(u, h)
    ok = abs(ts - _srv()) <= 5000
    CALLS.append(("sign", u.hostname, ok))
    host = u.hostname
    if FORCE_ERR[0]:
        raise _err(url, 400, {"code": -2015, "msg": "Invalid API-key, IP, or permissions for action."})
    if ok:
        return _Resp({"retCode": 0, "result": {"ok": 1}} if host == "api.bybit.com" else
                     {"code": "0", "data": [{"ok": 1}]} if host == "www.okx.com" else
                     {"code": "200000", "data": {"ok": 1}} if host == "api.kucoin.com" else
                     [{"ok": 1}] if host == "api.bithumb.com" else {"ok": 1})
    if host.endswith("binance.com"):
        raise _err(url, 400, {"code": -1021, "msg": "Timestamp for this request is outside of the recvWindow."})
    if host == "api.bybit.com":
        return _Resp({"retCode": 10002, "retMsg": "invalid request, please check your server timestamp or recv_window param", "result": {}})
    if host == "www.okx.com":
        raise _err(url, 401, {"msg": "Timestamp request expired", "code": "50102"})
    if host == "api.kucoin.com":
        raise _err(url, 400, {"code": "400002", "msg": "Invalid KC-API-TIMESTAMP"})
    if host == "api.gateio.ws":
        raise _err(url, 403, {"label": "REQUEST_EXPIRED", "message": "gap between request Timestamp and server time exceeds 60"})
    raise _err(url, 401, {"error": {"name": "jwt_verification", "message": "x"}})


FORCE_ERR = [False]
fake_urlopen._tj_test_mock = True
XF.urllib.request.urlopen = fake_urlopen
ENV = {"TJ_BINANCE_KEY": "k", "TJ_BINANCE_SECRET": "s", "TJ_BYBIT_KEY": "k", "TJ_BYBIT_SECRET": "s", "TJ_OKX_KEY": "k", "TJ_OKX_SECRET": "s",
       "TJ_OKX_PASSPHRASE": "p", "TJ_KUCOIN_KEY": "k", "TJ_KUCOIN_SECRET": "s", "TJ_KUCOIN_PASSPHRASE": "p", "TJ_GATE_KEY": "k", "TJ_GATE_SECRET": "s",
       "TJ_BITHUMB_KEY": "k", "TJ_BITHUMB_SECRET": "s"}
SIGNED = {"binance": lambda: XF._binance_signed(ENV, "/api/v3/account"),
          "bybit": lambda: XF._bybit_get(ENV, "/v5/account/info", {}),
          "okx": lambda: XF._okx_get(ENV, "/api/v5/account/config"),
          "kucoin": lambda: XF._kucoin_get(ENV, "/api/v1/accounts"),
          "gate": lambda: XF._gate_get(ENV, "/api/v4/spot/accounts")}


def _reset(on=True, at=None, off=0):
    CALLS.clear()
    if HAS:
        XF._CLOCK.clear()
        XF._CLOCK_ON[0] = on
        for ex in ("binance", "bybit", "okx", "kucoin", "gate", "bithumb"):
            XF._CLOCK[ex] = {"off": off, "at": time.time() if at is None else at, "rtt": 0}


def _run(fn):
    try:
        return fn(), None
    except Exception as e:
        return None, e


for ex, fn in SIGNED.items():
    _reset()
    r, e = _run(fn)
    seq = [c[0] if c[0] == "time" else ("ok" if c[2] else "bad") for c in CALLS]
    off = (getattr(XF, "_CLOCK", {}).get(ex) or {}).get("off")
    chk(e is None and seq == ["bad", "time", "ok"] and off is not None and abs(off - 30000) < 1500,
        f"C1 {ex}: 시계 30초 늦음 + 시각 오류 → 서버 시각 1번 재고 다시 1번 → 성공", (seq, off, repr(e)[:120]))

_reset()
_run(SIGNED["binance"])
p9 = os.path.join(common.STATE_DIR, "exf_clock.json")
doc = json.load(open(p9)) if os.path.exists(p9) else {}
chk(abs(int(((doc.get("ex") or {}).get("binance") or {}).get("off") or 0) - 30000) < 1500, "C2 잰 차이 = state/exf_clock.json", doc)
if HAS:
    XF._CLOCK.clear()
    XF._CLOCK_ON[0] = False
n9 = XF._clock_restore() if HAS else 0
chk(HAS and XF._CLOCK_ON[0] and abs(int(XF._CLOCK.get("binance", {}).get("off") or 0) - 30000) < 1500 and n9 >= 1,
    "C3 기동 복원(_clock_restore) = 파일 값 · 보정 켬", (n9, getattr(XF, "_CLOCK", None)))

_reset(at=time.time() - 3700)
r, e = _run(SIGNED["binance"])
seq = [c[0] if c[0] == "time" else ("ok" if c[2] else "bad") for c in CALLS]
chk(e is None and seq == ["time", "ok"], "C4 1시간 지남 = 서명 전에 먼저 잼(실패 0)", (seq, repr(e)[:80]))

_reset(at=time.time() - 3700)
_run(SIGNED["kucoin"])
CALLS.clear()
_run(SIGNED["kucoin"])
chk([c[0] for c in CALLS] == ["sign"], "C5 잰 뒤 1시간 안 = 다시 안 잼", CALLS)

_reset()
FORCE_ERR[0] = True
r, e = _run(SIGNED["binance"])
FORCE_ERR[0] = False
chk(e is not None and [c[0] for c in CALLS] == ["sign"], "C6 시각 오류 아님(-2015 권한) = 안 재고 다시 안 부름(오류 그대로)", (CALLS, repr(e)[:80]))

_reset()
TIME_BAD[0] = True
r, e = _run(SIGNED["okx"])
n_time1 = sum(1 for c in CALLS if c[0] == "time")
r2, e2 = _run(SIGNED["okx"])
TIME_BAD[0] = False
n_time2 = sum(1 for c in CALLS if c[0] == "time")
chk(e is not None and e2 is not None and n_time1 == 1 and n_time2 == 1 and sum(1 for c in CALLS if c[0] == "sign") == 3,
    "C7 다시 재도 틀림 = 한 번만 다시(무한 반복 없음) · 60초 안 두 번째 오류는 다시 안 잼", (CALLS, repr(e)[:60]))

_reset(on=False)
r, e = _run(SIGNED["gate"])
chk(e is not None and not any(c[0] == "time" for c in CALLS), "C8 보정 꺼짐(시험·도구 import) = 시각 조회 0 · 종전 동작", CALLS)

_reset(at=time.time() - 3700)
r, e = _run(lambda: XF._bithumb_get(ENV, "/v1/accounts"))
signs = [c for c in CALLS if c[0] == "sign"]
chk(e is None and [c[0] for c in CALLS] == ["time", "sign"] and signs and signs[0][2], "C9 빗썸 = 공개 응답 Date 머리로 차이 · 서명 시각 보정(초 단위 오차 안)",
    (CALLS, repr(e)[:80]))

print("[I] 바이낸스 선물 정산 같은 1ms 에 1,500건")
_reset(on=False)
T0 = (NOW - 3000) * 1000
INC = [{"tranId": str(i), "incomeType": "FUNDING_FEE", "time": T0, "income": "-0.001", "symbol": "AAAUSDT", "asset": "USDT"} for i in range(1, 1501)]
INC += [{"tranId": str(2000 + i), "incomeType": "REALIZED_PNL", "time": T0 + 5, "income": "1", "symbol": "AAAUSDT", "asset": "USDT"} for i in range(3)]
INC_Q = []


def _bn(url, headers=None, *a, **k):
    u = urllib.parse.urlsplit(url)
    q = {k9: v9[0] for k9, v9 in urllib.parse.parse_qs(u.query).items()}
    if u.path == "/fapi/v2/account":
        return {"totalWalletBalance": "0", "availableBalance": "0", "totalInitialMargin": "0", "positions": []}
    if u.path == "/fapi/v2/positionRisk":
        return []
    if u.path == "/fapi/v1/income":
        INC_Q.append(q)
        s9, lim = int(q["startTime"]), int(q.get("limit") or 100)
        rows = [r for r in INC if r["time"] >= s9 and ("endTime" not in q or r["time"] <= int(q["endTime"]))]
        pg = int(q.get("page") or 1)
        return rows[(pg - 1) * lim:pg * lim]
    return []


_bn._tj_test_mock = True
XF._http_json_err = _bn
XF._gov_prepare = lambda *a, **k: None
XF._px_safe = lambda *a, **k: None
common.atomic_write_json(os.path.join(common.STATE_DIR, "futures_binance.json"), {"ts": 0, "events": [], "cursor": {"income": T0}})
r, e = _run(lambda: XF._fut_binance({"TJ_BINANCE_KEY": "k", "TJ_BINANCE_SECRET": "s"}))
fb = common.read_json(os.path.join(common.STATE_DIR, "futures_binance.json"), {})
uids = [x["uid"] for x in fb.get("events") or []]
chk(e is None and len(uids) == 1503 and len(set(uids)) == 1503 and int((fb.get("cursor") or {}).get("income") or 0) == T0 + 5,
    "I1 같은 ms 1,500건 + 다음 ms 3건 = 1,503건 · 중복 0 · 커서 전진", (len(uids), fb.get("cursor"), repr(e)[:120]))
chk(any(q.get("endTime") == str(T0) and q.get("page") == "2" for q in INC_Q), "I2 그 1ms 만 page 로 넘김(startTime=endTime)", INC_Q[:4])

print("[K] 쿠코인 옛 계정 + HF 계정 체결")
TA = (NOW - 3600) * 1000
CL = [{"symbol": "BTC-USDT", "tradeId": "1", "orderId": "o1", "side": "buy", "price": "60000", "size": "0.01", "fee": "0.6", "feeCurrency": "USDT", "createdAt": TA}]
HF = {"ETH-USDT": [{"id": 5000 - i, "symbol": "ETH-USDT", "tradeId": str(100 + i), "orderId": f"h{i}", "side": "sell", "price": "3000", "size": "0.1",
                    "fee": "0.3", "feeCurrency": "USDT", "createdAt": TA - i * 1000} for i in range(105)],
      "BTC-USDT": [dict(CL[0], id=900), dict(CL[0], id=899, tradeId="1b")]}
LED = [{"id": "9", "currency": "ETH", "bizType": "TRADE_EXCHANGE", "context": json.dumps({"symbol": "ETH-USDT", "orderId": "h1", "tradeId": "101"})},
       {"id": "8", "currency": "USDT", "bizType": "TRADE_EXCHANGE", "context": {"symbol": "BTC-USDT", "orderId": "o1", "tradeId": "1"}}]
KQ = []
KMODE = ["ok"]


def _kc(url, headers=None, *a, **k):
    u = urllib.parse.urlsplit(url)
    q = {k9: v9[0] for k9, v9 in urllib.parse.parse_qs(u.query).items()}
    KQ.append((u.path, q))
    if u.path == "/api/v1/fills":
        return {"code": "200000", "data": {"items": CL, "totalPage": 1}}
    if u.path == "/api/v1/hf/accounts/ledgers":
        if KMODE[0] == "fail":
            return {"code": "500000", "msg": "internal"}
        if KMODE[0] == "deny":
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b"{}"))
        if KMODE[0] == "bad":
            return {"code": "400100", "msg": "parameter error"}
        return {"code": "200000", "data": LED}
    if u.path == "/api/v1/hf/fills":
        rows = sorted(HF.get(q["symbol"], []), key=lambda r: -r["id"])
        rows = [r for r in rows if int(q["startAt"]) <= int(r["createdAt"]) <= int(q["endAt"])]
        if q.get("lastId"):
            rows = [r for r in rows if r["id"] < int(q["lastId"])]
        page = rows[:int(q.get("limit") or 100)]
        return {"code": "200000", "data": {"items": page, "lastId": page[-1]["id"] if page else None}}
    return {"code": "200000", "data": {}}


_kc._tj_test_mock = True
XF.http_json = _kc
st = {}
r, e = _run(lambda: XF.fills_kucoin(ENV, st, NOW - 3 * 86400, NOW))
r = r or []
ids = [f["id"] for f in r]
chk(e is None and len(r) == 107 and len(set(ids)) == 107 and sum(1 for i in ids if i.startswith("kucoin:ETH-USDT:")) == 105
    and "kucoin:BTC-USDT:1b" in ids, "K1 옛 1건 + HF ETH 105건(lastId 2쪽) · BTC 같은 tradeId 는 하나로 · 다른 tradeId(같은 ms·같은 값)는 따로 = 107건",
    (len(r), repr(e)[:120]))
hf9 = [f for f in r if f["id"].startswith("kucoin:ETH-USDT:")]
chk(all(f.get("late") for f in hf9) and not any(f.get("late") for f in r if f["id"] == "kucoin:BTC-USDT:1") and st.get("kc_hf_on"),
    "K2 HF 를 처음 켠 주기 = 그 전 HF 체결 '늦게 발견'(대사 흡수분 되돌림) · 옛 체결은 그대로", st)
st2 = {"kc_hf_on": NOW - 30 * 86400}
r2, _ = _run(lambda: XF.fills_kucoin(ENV, st2, NOW - 3 * 86400, NOW))
chk(r2 and not any(f.get("late") for f in r2), "K3 켠 뒤 체결 = 늦게 발견 아님")
KMODE[0] = "fail"
st3 = {}
r3, e3 = _run(lambda: XF.fills_kucoin(ENV, st3, NOW - 3 * 86400, NOW))
chk(e3 is None and [f["id"] for f in (r3 or [])] == ["kucoin:BTC-USDT:1"] and "HF" in str(st3.get("partial") or st3.get("recon_hold") or "")
    and int(st3.get("kc_hf_gap") or 0) == NOW - 3 * 86400, "K4 HF 일시 실패 = 옛 체결은 그대로 · 이번 주기 완주·잔고 승격 보류 · 못 받은 하한 기억(kc_hf_gap)", (r3, st3))
KMODE[0] = "deny"
st4 = {}
r4, e4 = _run(lambda: XF.fills_kucoin(ENV, st4, NOW - 3 * 86400, NOW))
KQ.clear()
r5, _ = _run(lambda: XF.fills_kucoin(ENV, st4, NOW - 3 * 86400, NOW))
chk(e4 is None and len(r4 or []) == 1 and float(st4.get("kc_hf_off") or 0) > NOW and not st4.get("recon_hold")
    and not any(p.startswith("/api/v1/hf/") for p, _q in KQ), "K5 HF 거부(404) = 6시간 쉼(옛 체결 그대로 · 보류 없음 · 쉬는 동안 HF 조회 0)", (st4, KQ))
KMODE[0] = "fail"
st6 = {"kc_hf_on": NOW - 30 * 86400}
_run(lambda: XF.fills_kucoin(ENV, st6, NOW - 6 * 86400, NOW))
KMODE[0] = "ok"
KQ.clear()
r6, e6 = _run(lambda: XF.fills_kucoin(ENV, st6, NOW - 3 * 86400, NOW))
led9 = [q9 for p9, q9 in KQ if p9 == "/api/v1/hf/accounts/ledgers"]
hf6 = [f for f in (r6 or []) if f["id"].startswith("kucoin:ETH-USDT:")]
chk(e6 is None and led9 and led9[0].get("startAt") == str((NOW - 6 * 86400) * 1000) and len(hf6) == 105 and all(f.get("late") for f in hf6)
    and not st6.get("kc_hf_gap"), "K6 일시 실패 뒤 다음 주기 = 못 받은 하한(6일 전)부터 다시 · 회수분 전부 late · 기억 지움",
    (led9[:1], len(hf6), st6))
KMODE[0] = "fail"
r7, e7 = _run(lambda: XF.fills_kucoin(ENV, {}, NOW - 40 * 86400, NOW - 20 * 86400))
KMODE[0] = "bad"
r8, e8 = _run(lambda: XF.fills_kucoin(ENV, {}, NOW - 40 * 86400, NOW - 20 * 86400))
st9 = {}
r9b, e9b = _run(lambda: XF.fills_kucoin(ENV, st9, NOW - 3 * 86400, NOW))
KMODE[0] = "ok"
chk(e7 is not None and e8 is None and r8 is not None and float(st9.get("kc_hf_off") or 0) > NOW and not st9.get("kc_hf_gap"),
    "K7 과거 창: HF 일시 실패 = 예외(그 조각 다음 주기에 다시 — 확장 하한 안 내려감) · 결정적 오류 = 그 조각 HF 만 생략 · 정규 창 결정적 오류 = 6시간 쉼",
    (repr(e7)[:80], repr(e8)[:80], st9))

OLD = (NOW - 100 * 86400) * 1000
HF["ETH-USDT"].append({"id": 1, "symbol": "ETH-USDT", "tradeId": "old1", "orderId": "ho", "side": "buy", "price": "2000", "size": "1",
                       "fee": "1", "feeCurrency": "USDT", "createdAt": OLD})
KMODE[0] = "fail"
st8 = {"kc_hf_on": NOW - 200 * 86400}
_run(lambda: XF.fills_kucoin(ENV, st8, NOW - 150 * 86400, NOW))
p8 = st8.get("partial")
KMODE[0] = "ok"
r8b, e8b = _run(lambda: XF.fills_kucoin(ENV, st8, NOW - 3 * 86400, NOW))
got8 = [f for f in (r8b or []) if f["id"] == "kucoin:ETH-USDT:old1"]
chk(p8 and e8b is None and got8 and got8[0].get("late") and not st8.get("kc_hf_gap"),
    "K8 첫 5개월 수집 HF 1회 실패(완주 보류) → 다음 주기 성공 = 100일 전 HF 체결까지 회수(late) · 하한 기억 지움", (p8, len(r8b or []), st8))
HF["ETH-USDT"].pop()
st9b = {"kc_hf_on": NOW - 200 * 86400, "kc_hf_gap": NOW - 150 * 86400}
KMODE[0] = "bad"
_run(lambda: XF.fills_kucoin(ENV, st9b, NOW - 3 * 86400, NOW))
KMODE[0] = "ok"
lost9 = st9b.get("kc_hf_lost") or {}
chk(int(lost9.get("from") or 0) == NOW - 150 * 86400 and not st9b.get("kc_hf_gap") and float(st9b.get("kc_hf_off") or 0) > NOW,
    "K9 밀린 구간 회수 중 결정적 오류 = 조용히 안 지움(kc_hf_lost 기록·경고) · 6시간 쉼", st9b)

print("[B] 빗썸 과거 창 체결 시각")


def kiso(ts):
    return datetime.fromtimestamp(ts, KST).strftime("%Y-%m-%dT%H:%M:%S+09:00")


A9, B9 = NOW - 40 * 86400, NOW - 10 * 86400
CR = NOW - 30 * 86400
BROWS = [{"uuid": "bl", "side": "bid", "ord_type": "limit", "price": "100", "state": "done", "market": "KRW-AAA", "created_at": kiso(CR),
          "volume": "2", "executed_volume": "2", "executed_funds": "200", "paid_fee": "0.1"},
         {"uuid": "bm", "side": "ask", "ord_type": "market", "state": "done", "market": "KRW-AAA", "created_at": kiso(CR + 60),
          "volume": "1", "executed_volume": "1", "executed_funds": "100", "paid_fee": "0.05"},
         {"uuid": "bn", "side": "bid", "ord_type": "limit", "price": "100", "state": "done", "market": "KRW-AAA", "created_at": kiso(CR + 120),
          "volume": "1", "executed_volume": "1", "executed_funds": "100", "paid_fee": "0.05"}]
LAST = CR + 3 * 86400 + 777
BQ = []


def _bt(path, params):
    BQ.append((path, dict(params)))
    if path == "/v1/orders":
        return list(BROWS) if params.get("state") == "done" and int(params.get("page") or 1) == 1 else []
    if path == "/v1/order":
        if params["uuid"] == "bn":
            raise urllib.error.HTTPError("x", 404, "nf", {}, io.BytesIO(b"{}"))
        return dict(BROWS[0], trades=[{"created_at": kiso(CR + 3600), "volume": "1", "funds": "100"},
                                      {"created_at": kiso(LAST), "volume": "1", "funds": "100"}])
    raise AssertionError(path)


XF._BITHUMB_ASC_CACHE.clear()
EMIT = []
r, e = _run(lambda: XF._bithumb_ext_fills(_bt, {}, {}, A9, B9, time.time() + 60, EMIT.extend, lambda: None))
bts = {f["id"]: f["ts"] for f in EMIT}
n_one = sum(1 for p, _q in BQ if p == "/v1/order")
chk(e is None and bts.get("bithumb:bl") == LAST * 1000, "B1 지정가 = 단건 조회 마지막 체결 시각(생성 3일 뒤)", (bts, repr(e)[:120]))
chk(bts.get("bithumb:bm") == (CR + 60) * 1000 and bts.get("bithumb:bn") == (CR + 120) * 1000 and n_one == 2,
    "B2 시장가 = 조회 0·생성 시각 · 404 = 생성 시각 · 단건 조회 = 지정가 2건만", (bts, n_one))

XF._BITHUMB_ASC_CACHE.clear()
BQ.clear()
EMIT2, EXT2 = [], {}
_tt = XF.time.time
_left = [1]


def _bt_budget(path, params):
    r9 = _bt(path, params)
    if path == "/v1/order":
        _left[0] -= 1
    return r9


XF.time.time = lambda: _tt() + (0 if _left[0] > 0 else 10 ** 6)
fin1, e1 = _run(lambda: XF._bithumb_ext_fills(_bt_budget, {}, EXT2, A9, B9, _tt() + 60, EMIT2.extend, lambda: None))
XF.time.time = _tt
n1 = sum(1 for p, _q in BQ if p == "/v1/order")
fin2, e2 = _run(lambda: XF._bithumb_ext_fills(_bt, {}, EXT2, A9, B9, _tt() + 60, EMIT2.extend, lambda: None))
n2 = sum(1 for p, _q in BQ if p == "/v1/order")
b2 = {f["id"]: f["ts"] for f in EMIT2}
chk(fin1 is False and e1 is None and n1 == 1 and fin2 is True and n2 == 2 and b2.get("bithumb:bl") == LAST * 1000 and len(EMIT2) == 3,
    "B3 단건 조회 중 시간 예산 소진 = 그 쪽 방출 보류(커서 그대로) · 다음 주기 = 받은 결과 재사용(같은 주문 다시 안 물음)", (fin1, fin2, n1, n2, b2, repr(e1)[:80]))

XF._BITHUMB_ASC_CACHE.clear()
CLK = [time.time()]
XF.time.time = lambda: CLK[0]
ROWS4 = [{"uuid": f"r{i:03d}", "side": "bid", "ord_type": "limit", "price": "100", "state": "done", "market": "KRW-AAA",
          "created_at": kiso(CR + i * 60), "volume": "1", "executed_volume": "1", "executed_funds": "100", "paid_fee": "0.05"} for i in range(250)]
N4 = [0]


def _bt4(path, params):
    if path == "/v1/orders":
        if params.get("state") != "done":
            return []
        p9 = int(params.get("page") or 1)
        return ROWS4[(p9 - 1) * 100:p9 * 100]
    if path == "/v1/order":
        N4[0] += 1
        CLK[0] += 1.5
        r9 = next(r for r in ROWS4 if r["uuid"] == params["uuid"])
        return dict(r9, trades=[{"created_at": kiso(CR + 9 * 86400), "volume": "1", "funds": "100"}])
    raise AssertionError(path)


EXT4, EM4, fin4, cyc4 = {}, [], False, 0
while not fin4 and cyc4 < 8:
    cyc4 += 1
    fin4, e4b = _run(lambda: XF._bithumb_ext_fills(_bt4, {}, EXT4, A9, B9, CLK[0] + 240, EM4.extend, lambda: None))
    fin4 = bool(fin4)
XF.time.time = _tt
ok4 = {f["id"] for f in EM4 if f["ts"] == (CR + 9 * 86400) * 1000}
chk(fin4 and cyc4 <= 3 and len(ok4) == 250 and N4[0] == 250, "B4 재개 = 받은 단건 결과 재사용 → 몇 주기 안에 끝(같은 쪽 반복 없음 · 단건 조회 = 지정가 수만큼)",
    (fin4, cyc4, len(ok4), N4[0], (EXT4.get("bt_scan") or {}).get("st")))

print("[U] 업비트 과거 창 지정가 → ex_order_trades")


def uo(u, ot, created, vol="2", funds="2000", n=2):
    return {"uuid": u, "side": "bid", "ord_type": ot, "price": "1000", "state": "done", "market": "KRW-AAA", "created_at": kiso(created),
            "volume": vol, "remaining_volume": "0", "paid_fee": "1", "executed_volume": vol, "executed_funds": funds, "trades_count": n}


UC = NOW - 60 * 86400
SWEEP = [uo("ua", "limit", UC), uo("ub", "price", UC + 10), uo("uc", "limit", UC + 20)]
UL._sweep = lambda up, a, b, seen: (list(SWEEP), True, b)
try:
    UL.bf_engine.progress = lambda *_a, **_k: type("P", (), {"update": lambda *a, **k: None})()
except AttributeError:
    pass
nst = {"ext_from": NOW - 30 * 86400, "ext_target": NOW - 90 * 86400, "ext_start": NOW - 30 * 86400}
out = UL.extend_orders(None, 1, NOW - 90 * 86400, nst, set())
q9 = sorted((nst.get("tfill") or {}).keys())
chk(len(out) == 3 and q9 == ["ua", "uc"], "U1 과거 창 방출 3건 중 지정가 2건만 대기열(시장가 제외)", q9)


class _Up:
    def __init__(self):
        self.n = 0
        self._backoff_err = None

    def get(self, path, query=None):
        assert path == "/v1/order"
        self.n += 1
        u = query["uuid"]
        if u == "ua":
            return dict(SWEEP[0], trades=[{"uuid": "t1", "market": "KRW-AAA", "side": "bid", "price": "1000", "volume": "1", "funds": "1000",
                                           "created_at": kiso(UC + 86400)},
                                          {"uuid": "t2", "market": "KRW-AAA", "side": "bid", "price": "1000", "volume": "1", "funds": "1000",
                                           "created_at": kiso(UC + 5 * 86400)}])
        return dict(SWEEP[2], trades=[{"uuid": "t3", "market": "KRW-AAA", "side": "bid", "price": "1000", "volume": "1", "funds": "1000",
                                       "created_at": kiso(UC + 30)}])


class _W:
    def __init__(self):
        self.recs = []

    def append(self, rec):
        self.recs.append(rec)


up, wr = _Up(), _W()
n_sent = UL._tfill_pass(up, wr, nst) if hasattr(UL, "_tfill_pass") else 0
rec = wr.recs[0] if wr.recs else {}
chk(n_sent == 1 and rec.get("kind") == "ex_order_trades" and [o["uuid"] for o in rec.get("orders") or []] == ["ua"]
    and len(rec["orders"][0].get("trades") or []) == 2, "U2 단건 조회 → 검사 통과 1건 'ex_order_trades'(체결 목록 2줄)", wr.recs)
import acct_norm
m9, why9 = acct_norm.trades_fill_merge(SWEEP[0], rec["orders"][0]) if rec else (None, "없음")
chk(m9 is not None and acct_norm.fill_ts(m9) == UC + 5 * 86400, "U3 core 와 같은 검사 통과 · 기장 시각 = 마지막 체결(생성 5일 뒤)", why9)
tq = nst.get("tfill") or {}
chk(sorted(tq) == ["ua"] and tq["ua"].get("sent") and up.n == 2, "U4 검사 실패(수량 합 다름)는 뺌 · 보낸 것은 원장 반영 확인 전까지 남김(sent) · 조회 2회", tq)
DONE = {"ua": False}
UL._tfill_done = lambda us: {u: DONE.get(u, False) for u in us}
up2, wr2 = _Up(), _W()
UL._tfill_pass(up2, wr2, nst)
chk(up2.n == 0 and not wr2.recs and "ua" in (nst.get("tfill") or {}), "U5 보낸 지 10분 안 · 원장 미반영 = 기다림(조회 0)")
nst["tfill"]["ua"]["sent"] = int(time.time()) - 700
up3, wr3 = _Up(), _W()
UL._tfill_pass(up3, wr3, nst)
chk(up3.n == 1 and len(wr3.recs) == 1 and int(nst["tfill"]["ua"].get("ns") or 0) == 1 and nst["tfill"]["ua"].get("sent"),
    "U6 10분 지나도 원장 미반영(core 되돌림) = 다시 받아 다시 보냄(ns 1)", nst.get("tfill"))
DONE["ua"] = True
up4, wr4 = _Up(), _W()
UL._tfill_pass(up4, wr4, nst)
chk(up4.n == 0 and not nst.get("tfill"), "U7 원장에 체결 목록 붙음 = 대기열에서 뺌 · 조회 0", nst.get("tfill"))

chk(not T.NET_TRIES, "바깥 연결 시도 0", T.NET_TRIES)
T.finish()
