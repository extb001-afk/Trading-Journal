#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import os

os.environ["TJ_TG_API"] = "http://127.0.0.1:9/never"
import tinychart
import alert_watch
import alert_bot

chk = T.chk

v = [10000.0, 20000.0]
old_day = (v[-1] / v[-2] - 1) * 100
chk(abs(old_day - 100) < 1e-9, "종전 식(입출금 포함) = +100% (재현 — 입금을 수익으로 셈)", old_day)
hd = getattr(tinychart, "headline", None)
chk(hd is not None and abs(hd([[10000.0, None], [20000.0, 10000.0]])["day"]) < 1e-9, "순유입 1만 뺀 하루 수익률 = 0%", hd and hd([[10000.0, None], [20000.0, 10000.0]]))
fr = getattr(tinychart, "flow_ret", None)
chk(fr is not None and fr(100, 150, 40) == 10.0 and fr(0, 5, 0) is None and fr(None, 5) is None, "flow_ret = (끝 − 처음 − 순유입) ÷ 처음 · 0·없음 = None", fr and [fr(100, 150, 40), fr(0, 5, 0)])
if hd:
    h = hd([[100.0, None], [110.0, 0.0], [220.0, 100.0], [231.0, 0.0]])
    chk(abs(h["period"] - 31.0) < 1e-9 and abs(h["day"] - 5.0) < 1e-9 and h["rising"], "기간 % = (231 − 100 − 100) ÷ 100 = +31% · 하루 +5%", h)
    h = hd([[100.0, None], [50.0, None], [60.0, 0.0]])
    chk(h["period"] is None and abs(h["day"] - 20.0) < 1e-9, "중간 날 순유입 모름 = 기간 % 없음(그리지 않음) · 하루는 알면 뺀다", h)
    h = hd([[100.0, None], [300.0, 250.0]])
    chk(h["rising"] is False and h["day"] < 0, "입금으로 늘었지만 실제는 손실 = 내림 색(파랑)", h)
    h = hd([100.0, 200.0, 150.0])
    chk(abs(h["day"] - (-25.0)) < 1e-9 and abs(h["period"] - 50.0) < 1e-9 and h["net"] is False, "옛 재료(숫자만) = 종전 식 그대로", h)
png = tinychart.render([[1.0e9, None], [1.5e9, 4.0e8], [1.52e9, 0.0]], cur="KRW")
chk(png[:8] == b"\x89PNG\r\n\x1a\n" and tinychart.png_size(png) == (720, 300), "쌍 재료 그림 = 정상 PNG 720×300", tinychart.png_size(png))
png2 = tinychart.render([1.0, 2.0, 3.0], flows=[None, 1.0, None])
chk(tinychart.png_size(png2) == (720, 300), "flows 인자 + 순유입 None 날 = 정상 PNG", tinychart.png_size(png2))
png3 = tinychart.render([[1.0, None], ["x", 2.0], [3.0, None]])
chk(tinychart.png_size(png3) == (720, 300), "깨진 값 점은 순유입과 함께 빠짐(정상 PNG)", tinychart.png_size(png3))
out = {"todayIso": "2026-10-06", "todayKey": "10-06", "builtAt": 0, "fields": {"rate": 1400.0, "dailySeries": [
    {"date": "10-04", "val": 10000.0, "valKrw": 13900000, "usdt": 1390, "flow": None},
    {"date": "10-05", "val": 10000.0, "valKrw": 13950000, "usdt": 1395, "flow": 0.0},
    {"date": "10-06", "val": 20000.0, "usdt": 1400, "flow": 10000.0}], "realizedByDate": {}, "futures": {}}}
d = alert_watch.pnl_data(out, "KRW")
cv = (d or {}).get("curve") or []
chk(len(cv) == 3 and all(len(c) == 3 for c in cv), "재료 curve = [MM-DD, 값, 순유입] 세 값", cv)
chk(cv and cv[0][2] is None and cv[1][2] == 0.0 and cv[2][2] == 10000.0 * 1400.0, "원화 순유입: 모름 = None · 오늘 = × 지금 환율", [c[2] for c in cv])
out["fields"]["dailySeries"][1]["flow"] = 100.0
d = alert_watch.pnl_data(out, "KRW")
chk(d["curve"][1][2] == 100.0 * 1395, "원화 순유입: 지난날 = × 그날 USDT 종가(valKrw 와 같은 환율)", d["curve"][1])
du = alert_watch.pnl_data(out, "USD")
chk(du["curve"][2][2] == 10000.0 and du["curve"][2][1] == 20000.0, "달러 모드 = 순유입 그대로", du["curve"][2])
rec = {"v": 2, "preset": "recommended", "cats": {}, "th": {}, "quiet": {"on": False}}
try:
    import alert_prefs as AP
    rec = AP.load() if hasattr(AP, "load") else rec
except Exception:
    pass
from datetime import datetime, timezone, timedelta
D9 = datetime(2026, 10, 6, 9, 30, tzinfo=timezone(timedelta(hours=9))).timestamp()
dg = {"items": [{"cat": "pnl", "kind": "PNL_DAILY", "text": "x", "ts": D9, "d": dict(alert_watch.pnl_data(out, "KRW"), iso="2026-10-06")}], "n": {}}
try:
    txt, curve, cur = alert_bot.compose_digest(dg, rec, D9, None, {})
except Exception as e:
    txt, curve, cur = None, None, repr(e)
chk(isinstance(curve, list) and len(curve) == 3 and all(isinstance(c, list) and len(c) == 2 for c in curve), "요약 그림 재료 = [값, 순유입] 쌍(세 값 재료)", curve)
dg_old = {"items": [{"cat": "pnl", "kind": "PNL_DAILY", "text": "x", "ts": D9, "d": {"iso": "2026-10-06", "cur": "KRW", "realized": 1.0, "delta": 1.0, "sells": 1, "top": [],
                                                                                  "curve": [["10-05", 1.0e9], ["10-06", 1.1e9]]}}], "n": {}}
txt2, curve2, _c = alert_bot.compose_digest(dg_old, rec, D9, None, {})
chk(curve2 == [1.0e9, 1.1e9], "옛 보류 재료(2원소) = 숫자만(종전 그대로)", curve2)
if isinstance(curve, list) and curve:
    chk(tinychart.png_size(tinychart.render(curve, cur=cur)) == (720, 300), "요약 재료 그대로 그림(flush_digest 경로) = 정상 PNG")
hdN = tinychart.headline([[10000.0, None], [20000.0, None]])
chk(hdN["day"] is None and hdN["period"] is None and hdN["rising"] is True, "경계 끝날 순유입 모름 = 하루 %·기간 % 없음(입금을 +100% 로 안 그림)", hdN)
pngN = tinychart.render([[10000.0, None], [15000.0, 0.0], [20000.0, None]])
chk(pngN[:8] == b"\x89PNG\r\n\x1a\n" and len(pngN) > 1000, "경계 하루 % 없는 그림도 PNG 정상", len(pngN))

T.finish()
