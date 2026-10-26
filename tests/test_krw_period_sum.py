#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _costsim as S  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402
import types  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import acct_norm  # noqa: E402
import attfreeze  # noqa: E402
import demo_data  # noqa: E402
import histmark  # noqa: E402
import paths  # noqa: E402
import review_daily  # noqa: E402
import statefile  # noqa: E402
import view_tax  # noqa: E402
import web  # noqa: E402

chk = T.chk
DAY = 86400
KST9 = acct_norm.KST if hasattr(acct_norm, "KST") else __import__("datetime").timezone(timedelta(hours=9))
RATE = 1000.0
PNL = "1.0004"


def noon(days_ago):
    d = datetime.fromtimestamp(S.NOW, KST9) - timedelta(days=days_ago)
    return int(d.replace(hour=12, minute=0, second=0, microsecond=0).timestamp())


def run_spot():
    S.reset(px={"USDT": 1., "USDC": 1., "ETH": 2000.})
    S.FX[0] = RATE
    S.FXF[0] = None
    t0 = noon(12)
    S.ex("binance", deposits=[S.norm_row("binance", "kd0", "USDT", "100000", 0, "kdn0", "ACCEPTED", t0, t0)])
    fl = []
    for i, ago in enumerate((10, 9, 8)):
        tb = noon(ago)
        fl.append(S.norm_fill("binance", f"ETHUSDT:b{i}", tb * 1000, "ETH", "USDT", "buy", "2000", "1", "0", "USDT"))
        fl.append(S.norm_fill("binance", f"ETHUSDT:s{i}", (tb + 3600) * 1000, "ETH", "USDT", "sell", "2001.0004", "1", "0", "USDT"))
    S.fills("binance", fl)
    return S.build()


r1 = T.safe(run_spot)
f1, _G1, rr1 = r1 if isinstance(r1, tuple) else (None, None, None)
chk(f1 is not None and rr1 is not None, "K1 합성 빌드(3일 × 매수·매도 · 환율 1000 고정)", r1 if not isinstance(r1, tuple) else None)
if f1 is not None and rr1 is not None:
    out_k = f1.get("realizedKrwByDate") or {}
    raw_k = rr1.books.realized_krw_by_date
    days = sorted(k for k, v in raw_k.items() if abs(float(v)) > 1)
    chk(len(days) == 3 and all(abs(float(raw_k[d]) - 1000.4) < 1e-6 for d in days), "K1 장부 날짜별 원화 실현 = 1000.4원 × 3일(합성 재료 확인)",
        {d: raw_k[d] for d in days})
    chk(all(out_k.get(d) == round(float(raw_k[d]), 2) for d in days) and all(abs(out_k[d] - 1000.4) < 1e-9 for d in days),
        "K1 화면 맵 = 장부 값 소수 둘째 자리(정수로 자르지 않음)", {d: out_k.get(d) for d in days})
    rows = f1.get("_taxRowsAll") or []
    stmt = sum(float(r[8]) for r in f1.get("taxSummary") or [])
    per = sum(float(v) for v in out_k.values())
    chk(round(per) == round(stmt) == 3001, "K1 기간 합(맵 더한 뒤 원 단위) = 명세 원화 실현 합(원) = 3001 — 종전 정수 맵 합 3000", {"per": per, "stmt": stmt})
    g_new, _tol = view_tax.krw_sum_gap(rows, out_k)
    g_old, _tol2 = view_tax.krw_sum_gap(rows, {k: round(float(v)) for k, v in raw_k.items()})
    chk(abs(g_new) < 0.01 < abs(g_old), "K1 감시 차(명세 − 화면 맵) = 소수 맵 0.01원 미만 < 정수 맵(1.2원)", {"new": g_new, "old": g_old})

FUT_T = [noon(ago) * 1000 + 7 for ago in (6, 5, 4)]
statefile.atomic_write_json(os.path.join(paths.STATE_DIR, "futures_binance.json"), {"ts": S.NOW, "positions": [], "events": [
    {"t": t, "symbol": "KRWTSTUSDT", "kind": "REALIZED", "amount": float(PNL), "uid": f"kf{i}", "asset": "USDT"} for i, t in enumerate(FUT_T)]})
wb = web.StateBuilder.__new__(web.StateBuilder)
wb.cfg = {}
wb.px = types.SimpleNamespace(lock=threading.Lock(), d={"fx": {}, "candle": {}})
wb.spot = types.SimpleNamespace(rate=RATE, fx_basis=RATE, price=lambda s9: None)
v2 = T.safe(web.StateBuilder._futures_view, wb, None)
fk = (v2 or {}).get("realizedKrwByDate") or {}
fdays = sorted({acct_norm.iso_day(t // 1000) for t in FUT_T})
chk(len(fdays) == 3 and all(abs(float(fk.get(d, 0)) - 1000.4) < 1e-9 for d in fdays), "K2 선물 맵 = 정산 시각 원화 소수 둘째 자리(1000.4원 × 3일)",
    {"fk": fk, "exc": (v2 or {}).get("_exc")})
chk(round(sum(float(fk[d]) for d in fdays if d in fk)) == 3001, "K2 선물 기간 합(원) = 이벤트 원화 합 3001 — 종전 정수 맵 3000", fk)
ex2 = (v2 or {}).get("realizedByDateEx") or {}
chk(all(isinstance(x.get("krw"), int) and x["krw"] == 1000 for d in fdays for x in ex2.get(d) or ()), "K2 거래소별 그날 줄 원화 = 정수 그대로(표시 줄 · 바뀌지 않음)", ex2)

d3 = sorted(fdays)[0]
f3 = {"realizedByDate": {d3: 1.0}, "realizedKrwByDate": {d3: 1000.4}, "futures": {"realizedByDate": {d3: 1.0}, "realizedKrwByDate": {d3: 1000.4}}}
chk(review_daily._krw_total(f3, d3, 1.0, 1.0) == 2001, "K3 일일 리뷰 제목 원화 = 현물 + 선물 맵 합(2000.8) → 원 단위 2001(종전 정수 맵 2000)",
    review_daily._krw_total(f3, d3, 1.0, 1.0))
seg = review_daily.week_segment(d3)
wdays = [d for d in review_daily.segment_days(seg)][:3]
f3w = {"realizedByDate": {d: 1.0 for d in wdays}, "realizedKrwByDate": {d: 1000.4 for d in wdays}, "futures": {}, "positions": [], "dailySeries": [],
       "lps": [], "lpsClosed": [], "lpsPending": []}
st3 = {"fields": f3w, "todayIso": wdays[-1], "todayKey": wdays[-1][5:]}
w3 = T.safe(review_daily.gather_week, st3, wdays[0])
want3 = round(1000.4 * len(wdays))
chk(isinstance(w3, dict) and w3.get("realized_total_krw") == want3,
    f"K3 주간 원화 합 = 날 값(반올림 전) 합을 원 단위로({want3}원 · 종전 날마다 정수 합 {1000 * len(wdays)})",
    {"got": (w3 or {}).get("realized_total_krw") if isinstance(w3, dict) else None, "exc": w3 if not isinstance(w3, dict) else None})

TODAY = datetime.fromtimestamp(S.NOW, KST9).strftime("%Y-%m-%d")


def iso_ago(n):
    return (datetime.strptime(TODAY, "%Y-%m-%d") - timedelta(days=n)).strftime("%Y-%m-%d")


OLD = iso_ago(40)
p4 = paths.state(attfreeze.FILE)
statefile.atomic_write_json(p4, {"_v": 1, "dm": [], "d": {OLD: {"r": {"date": OLD[5:], "val": 100.0, "att": {}}, "p": {"date": iso_ago(41)[5:], "val": 90.0},
                                                                "rzd": {"s": 1.0, "sk": 1000, "f": 1.0, "fk": 1000}, "at": S.NOW - 40 * DAY, "h": "x"}}})
statefile.atomic_write_json(paths.state(histmark.HIST_DIRTY), {"marks": []})
rows4 = []
for n in range(29, -1, -1):
    iso = iso_ago(n)
    rows4.append({"date": iso[5:], "val": 100.0 + n, "valKrw": None, "att": {"rz": 1.0} if n else None})
fields4 = {"dailySeries": rows4, "realizedByDate": {iso_ago(n): 1.0 for n in range(1, 30)},
           "realizedKrwByDate": {iso_ago(n): 1000.4 for n in range(1, 30)},
           "futures": {"realizedByDate": {iso_ago(n): 1.0 for n in range(1, 30)}, "realizedKrwByDate": {iso_ago(n): 1000.4 for n in range(1, 30)}}}
own4 = types.SimpleNamespace()
attfreeze.hook(own4, fields4, TODAY, S.NOW)
s4 = statefile.read_json(p4, {}) or {}
d4 = s4.get("d") or {}
win4 = [iso_ago(n) for n in range(1, 29)]
chk(all((d4.get(i) or {}).get("rzd", {}).get("sk") == 1000.4 for i in win4), "K4 창 안 지난날 = 새 빌드 실현(소수) 그대로 기록", {i: (d4.get(i) or {}).get("rzd") for i in win4[:2]})
old4 = d4.get(OLD) or {}
chk(old4.get("rzd") == {"s": 1.0, "sk": 1000, "f": 1.0, "fk": 1000} and not old4.get("st") and old4.get("h") == "x",
    "K4 창 밖 정수 동결 실현 = 그대로(다시 안 씀) · '정정 전 값' 표식 없음", old4)
chk(not any((v or {}).get("st") for v in d4.values()), "K4 정수 동결 + 소수 새 값 섞여도 어느 날에도 's' 없음", [k for k, v in d4.items() if (v or {}).get("st")])
statefile.atomic_write_json(paths.state(histmark.HIST_DIRTY), {"marks": [[1, iso_ago(45), S.NOW - 60]]})
attfreeze.hook(own4, fields4, TODAY, S.NOW + 5)
old4b = (statefile.read_json(p4, {}) or {}).get("d", {}).get(OLD) or {}
chk(old4b.get("st") == "s" and old4b.get("rzd", {}).get("sk") == 1000, "K4 (반대) 정정 표식이 들어오면 창 밖 기록에 's'(값은 그대로 · 표식만이 판정 기준)", old4b)

fdk = T.safe(demo_data.fut_state)
if not isinstance(fdk, dict) or "_exc" in fdk:
    fdk = None
src9 = json.dumps(fdk) if fdk else ""
chk(fdk is not None and isinstance(fdk.get("realizedKrwByDate"), dict) and fdk["realizedKrwByDate"]
    and all(v == round(v, 2) for v in fdk["realizedKrwByDate"].values()) and any(v != round(v) for v in fdk["realizedKrwByDate"].values()),
    "K5 데모 선물 원화 맵 = 소수 둘째 자리(정수 아님 · 공개 스크린샷도 같은 꼴)", {"fn": bool(fdk), "n": len(src9)})
T.finish()
