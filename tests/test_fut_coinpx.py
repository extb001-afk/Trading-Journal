#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import copy
import json
import os
import threading
import time
import types

json.dump({"chains": {}, "wallets": []}, open(os.path.join(T.TMP, "config.json"), "w"))
import common
import acct_norm
import fut_rcpt
import web

chk = T.chk
NOW = int(time.time())


def mn(ts_s):
    return ts_s // 60 * 60 * 1000


S1 = NOW - 10 * 86400 - 3 * 3600
S2 = NOW - 8 * 86400 - 5 * 3600
S3 = NOW - 20 * 86400 - 1 * 3600
S4 = NOW - 30 * 86400 - 2 * 3600
T1, T2, T3, T4 = S1 * 1000 + 7, S2 * 1000 + 12, S3 * 1000 + 3, S4 * 1000 + 5

FB = [{"t": T1, "symbol": "AAAUSDT", "kind": "REALIZED", "amount": 5.0, "uid": "b1", "asset": "USDT"},
      {"t": T1 + 1, "symbol": "AAAUSDT", "kind": "FEE", "amount": -0.02, "uid": "b2", "asset": "BNB"},
      {"t": T1 + 2, "symbol": "AAAUSDT", "kind": "FUNDING", "amount": -0.25, "uid": "b3"},
      {"t": T3, "symbol": "AAAUSDT", "kind": "FEE", "amount": -0.02, "uid": "b4", "asset": "BNB"},
      {"t": T4, "symbol": "AAAUSDT", "kind": "FEE", "amount": -0.02, "uid": "b5", "asset": "BNB"}]
FO = [{"t": T2, "symbol": "BTC-USD-SWAP", "kind": "REALIZED", "amount": 0.01, "uid": "ok:x1:p", "asset": "BTC"},
      {"t": T2, "symbol": "BTC-USD-SWAP", "kind": "FEE", "amount": -0.0001, "uid": "ok:x1:f", "asset": "BTC"}]
common.atomic_write_json(os.path.join(common.STATE_DIR, "futures_binance.json"), {"ts": NOW, "events": FB, "positions": []})
common.atomic_write_json(os.path.join(common.STATE_DIR, "futures_okx.json"), {"ts": NOW, "events": FO, "positions": []})
CORE = os.path.join(common.STATE_DIR, "px_cache_core.json")
common.atomic_write_json(CORE, {"candle": {f"BTC:{mn(S2)}": 61000.0}, "fx": {}})
PX = types.SimpleNamespace(lock=threading.Lock(), d={"fx": {}, "candle": {
    f"BNB:{mn(S1)}": 500.0,
    f"BNB:{mn(S3) - 2 * 3600 * 1000}": 450.0,
    f"BNB:{mn(S3) + 10 * 60 * 1000}": 470.0,
}})
SP = {"BNB": 600.0, "BTC": 90000.0}
wb = web.StateBuilder.__new__(web.StateBuilder)
wb.cfg = {}
wb.px = PX
wb.spot = types.SimpleNamespace(rate=1380.0, fx_basis=1380.0, price=lambda s9: SP.get(str(s9).upper()))
web.BUILDER = wb


def kday(ts_s):
    return acct_norm.iso_day(ts_s)


def fxb_now():
    fx9, c9 = web._px_tables(PX)
    return acct_norm.FxBook(fx9, CORE, 1380.0, web_candle=c9)


def view(fxb=True):
    return T.safe(web.StateBuilder._futures_view, wb, fxb_now() if fxb else None)


def rcpt(iso):
    return T.safe(fut_rcpt.assemble, iso, copy.deepcopy(getattr(wb, "_fut_ev", None)), {}, dict(web.StateBuilder.FUT_EXN, **web.PERP_NAMES),
                  web._fut_by_date_ex, int(time.time() * 1000))


def api():
    d9 = T.safe(web.futures_api_payload)
    return {ex: {e["uid"]: e for e in (d9.get(ex) or {}).get("events") or ()} for ex in ("binance", "okx")} if "_exc" not in d9 else d9


print("[F] 빌드 — 정산 시각 시세")
v1 = view()
r1 = {d: rcpt(d) for d in (kday(S1), kday(S2))}
a1 = api()
rb1 = v1.get("realizedByDate") or {}
chk(abs(rb1.get(kday(S1), 0) - (5.0 - 0.02 * 500 - 0.25)) < 1e-6,
    "F1 바이낸스 BNB 수수료 −0.02 = 정산 그 분 봉 $500 × 수량 = −$10(지금 시세 $600 아님) · USDT 정산·옛 이벤트 그대로", (rb1.get(kday(S1)), v1.get("_exc")))
chk(abs(rb1.get(kday(S2), 0) - (0.01 - 0.0001) * 61000) < 1e-6 and any(abs(r["pnl"] - 610.0) < 1e-6 for r in v1.get("realizedRows") or ()),
    "F2 OKX 코인 마진 BTC 0.01 = 원장 캐시 그 분 봉 $61,000 → $610(수수료 −$6.1) — 종전 $0.01 로 읽던 것(NB4)도 아님", (rb1.get(kday(S2)), v1.get("realizedRows")))
chk(abs(rb1.get(kday(S3), 0) + 0.02 * 450) < 1e-6, "F3 그 분 봉 없음 = 직전 가장 가까운 과거 봉($450 · 2시간 전) — 10분 뒤 미래 봉($470)이 아니라", rb1.get(kday(S3)))
chk(abs(rb1.get(kday(S4), 0) + 0.02 * 600) < 1e-6 and v1.get("coinEst") == 1,
    "F4 캐시에 아무것도 없음 = 지금 시세($600) + 추정 1건(coinEst)", (rb1.get(kday(S4)), v1.get("coinEst")))

print("[F·R·A] 시세가 바뀌어도 지난 정산 달러는 그대로")
SP.update({"BNB": 900.0, "BTC": 120000.0})
v2 = view()
r2 = {d: rcpt(d) for d in (kday(S1), kday(S2))}
a2 = api()
rb2 = v2.get("realizedByDate") or {}
fixed = [kday(S1), kday(S2), kday(S3)]
chk(all(rb1.get(d) == rb2.get(d) for d in fixed) and all((v1.get("realizedKrwByDate") or {}).get(d) == (v2.get("realizedKrwByDate") or {}).get(d) for d in fixed),
    "F5 일별 선물 손익(USD·원화) — 시세 $600→$900 · $90k→$120k 에도 그대로(종전: 같이 움직임)",
    ({d: (rb1.get(d), rb2.get(d)) for d in fixed}))
ex1 = {(x["date"] if isinstance(x, dict) and "date" in x else k): x for k, x in (v1.get("realizedByDateEx") or {}).items()}
ex2 = {(x["date"] if isinstance(x, dict) and "date" in x else k): x for k, x in (v2.get("realizedByDateEx") or {}).items()}
chk(all(ex1.get(d) == ex2.get(d) for d in fixed) and v1.get("realizedSummary") == v2.get("realizedSummary")
    and v1.get("realizedRows") == v2.get("realizedRows"),
    "F6 거래소별 그날 줄·월별 명세(realizedSummary)·최근 정산 목록 — 시세 바뀌어도 그대로", ({d: (ex1.get(d), ex2.get(d)) for d in fixed}))
chk((v1.get("pnlBreak") or {}).get("fee") != (v2.get("pnlBreak") or {}).get("fee")
    and abs(((v2.get("pnlBreak") or {}).get("fee") or 0) - ((v1.get("pnlBreak") or {}).get("fee") or 0) + 0.02 * 300) < 0.011
    and abs(rb2.get(kday(S4), 0) + 0.02 * 900) < 1e-6 and v2.get("coinEst") == 1,
    "F7 움직이는 건 '추정'(시세 기록 없음) 1건뿐 — 누적 수수료 차이 = 그 1건의 시세 차($300 × 0.02)", (v1.get("pnlBreak"), v2.get("pnlBreak")))
chk(all("_exc" not in r1[d] and "_exc" not in r2[d] and r1[d].get("total") == r2[d].get("total") for d in r1)
    and abs((r1[kday(S2)].get("total") or {}).get("usd", 0) - 603.9) < 1e-6,
    "F8 선물 영수증(그날 합·실현·수수료·원화) — 시세 바뀌어도 그대로 · BTC 코인 마진 그날 $603.90", ({d: (r1[d].get("total"), r2[d].get("total")) for d in r1}))
chk(r1[kday(S1)].get("coinEst", 0) == 0 and rcpt(kday(S4)).get("coinEst") == 1,
    "F9 영수증 '추정' 건수 — 정산 시각 시세 있는 날 0 · 지금 시세로 추정한 날 1", (r1[kday(S1)].get("coinEst"), rcpt(kday(S4)).get("coinEst")))
v0 = view(fxb=False)
chk(v0.get("realizedByDate") == rb2 and v0.get("realizedRows") == v2.get("realizedRows"),
    "F10 FxBook 없이 부른 경우(옛 호출부·시험) = 같은 캐시로 같은 값", (v0.get("realizedByDate"), rb2, v0.get("_exc")))

chk("_exc" not in a1 and abs(a1["binance"]["b2"]["amount"] + 10.0) < 1e-9 and abs(a1["okx"]["ok:x1:p"]["amount"] - 610.0) < 1e-9
    and a1["binance"]["b2"]["amt_native"] == -0.02 and not a1["binance"]["b2"].get("px_est"),
    "A1 /api/futures(선물 서랍 거래소별 원본) = 빌드와 같은 정산 시각 값(BNB −$10 · BTC $610 · 원래 수량 amt_native)", a1 if "_exc" in a1 else {k: a1[k] for k in a1})
chk("_exc" not in a2 and all(a1[ex][u]["amount"] == a2[ex][u]["amount"] for ex, u in (("binance", "b2"), ("binance", "b4"), ("okx", "ok:x1:p"), ("okx", "ok:x1:f")))
    and a2["binance"]["b5"].get("px_est") is True and abs(a2["binance"]["b5"]["amount"] + 18.0) < 1e-9,
    "A2 /api/futures — 시세 바뀌어도 정산 시각 값 그대로 · 시세 기록 없는 1건만 지금 시세 + px_est", a2 if "_exc" in a2 else {k: a2[k] for k in a2})

print("[N] NB4·스테이블·옛 이벤트 회귀")
e1 = web.fut_ev_usd({"amount": 0.01, "asset": "BTC", "kind": "REALIZED"}, {"BTC": 60000.0}.get)
e2 = web.fut_ev_usd({"amount": -0.5, "asset": "USDT", "kind": "FEE"}, None)
e3 = web.fut_ev_usd({"amount": -0.5, "kind": "FEE"}, None)
e4 = web.fut_ev_usd({"amount": -0.02, "asset": "XYZ", "kind": "FEE"}, lambda s9: (None, False))
e5 = web.fut_ev_usd({"amount": -0.02, "asset": "BNB", "kind": "FEE"}, lambda s9: (700.0, True))
chk(abs(e1["amount"] - 600.0) < 1e-9 and e2["amount"] == -0.5 and e3["amount"] == -0.5 and e4 is None
    and abs(e5["amount"] + 14.0) < 1e-9 and e5.get("px_est") is True and "px_est" not in e1,
    "N1 숫자 시세(종전 호출 모양) = 그대로 · 스테이블·자산 없는 옛 이벤트 = 그대로 · 시세 모름 = 뺌 · (시세, 추정) 모양 = px_est", (e1, e2, e3, e4, e5))
print("[C] 그날 마감가 저장본(캐시만 · 요청 기록 없음)")
import histcurve
S5 = NOW - 40 * 86400 - 4 * 3600
PX.d["candle"][f"BNB:{mn(S5) - 3 * 86400 * 1000}"] = 410.0
seen = []
_lk = histcurve.DAYCLOSE.lookup


def _dc(spec, iso, now=None, w=0.0, ask=True, old=False):
    seen.append((spec, iso, ask, old))
    return (420.0, "ok") if (spec, iso) == ("sym:BNB", kday(S5)) else (None, "pending")


histcurve.DAYCLOSE.lookup = _dc
try:
    pc = web.fut_px_at(fxb_now(), lambda s9: 999.0)
    c5, c4, c1 = pc("BNB", S5 * 1000 + 9), pc("BNB", T4), pc("BNB", T1)
finally:
    histcurve.DAYCLOSE.lookup = _lk
chk(c5 == (420.0, False) and c4 == (999.0, True) and c1 == (500.0, False)
    and all(a is False for _s, _i, a, _o in seen) and ("sym:BNB", kday(S5), False, False) in seen and not any(i == kday(S1) for _s, i, _a, _o in seen),
    "C1 그 분·1일 안 과거 봉 없음 = 그날 마감가($420 · 3일 전 봉 $410 보다 먼저) · 요청 기록 없음(ask=False) · 그 분 봉 있으면 마감가를 보지 않음",
    (c5, c4, c1, seen))
pf = web.fut_px_at(fxb_now(), lambda s9: None)
chk(pf("BNB", T4) == (None, False) and pf("BNB", 0) == (None, False),
    "N2 캐시도 지금 시세도 없음 = (None, 추정 아님) → 그 이벤트는 뺌(수량을 달러로 읽지 않음 — NB4)", (pf("BNB", T4), pf("BNB", 0)))
T.finish()
