#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import calendar
import inspect
import json
import os
from datetime import datetime, timedelta, timezone

json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(os.environ["TJ_BASE"], "config.json"), "w"))
import candles
import histcurve as H

chk = T.chk
KST = timezone(timedelta(hours=9))
DAY = 86400


def U(y, m, d, h=0):
    return calendar.timegm((y, m, d, h, 0, 0))


def near(a, b, tol=1e-9):
    return a is not None and b is not None and abs(a - b) <= tol * max(1.0, abs(b))


T15 = H.day_end("2026-09-10")
chk(T15 == U(2026, 9, 10, 15), "P 그날 마감 = 그날 UTC 15:00", T15)

c80 = [U(2026, 9, 10), 100.0, 100.0, 80.0, 80.0, 1.0]
c25 = [U(2026, 9, 10), 100.0, 100.0, 25.0, 25.0, 1.0]
prev = [U(2026, 9, 9), 99.0, 101.0, 98.0, 100.0, 1.0]
chk(near(H.px_at([prev, c80], T15), 100.0), "P K9 시가 100 → 23시 UTC 급락 종가 80 = 100(종전 보간 87.5)", H.px_at([prev, c80], T15))
chk(near(H.px_at([prev, c25], T15), 100.0), "P K9 시가 100 → 23시 UTC 급락 종가 25 = 100(종전 종가 25)", H.px_at([prev, c25], T15))
chk(near(H.px_at([c80], T15), 100.0), "P K9 앞 봉 없는 봉 하나 · 시가 100 → 종가 80 = 시가 100", H.px_at([c80], T15))
chk(H.px_at([c25], T15) is None, "P K9 앞 봉 없는 봉(그 마켓 첫 봉 = 상장 첫날)인데 시가가 종가의 3배 밖 = 값 없음(첫 체결 튐인지 모름 · 종가는 미래)",
    H.px_at([c25], T15))
lst = [U(2026, 8, 21), 37.0, 40.0, 0.04, 0.044, 1.0]
chk(H.px_at([lst], H.day_end("2026-08-21")) is None, "P K9 상장 첫 봉의 튄 시가 = 값 없음(그 시각 가격 모름 — 종가는 미래)", H.px_at([lst], H.day_end("2026-08-21")))
nxt = [U(2026, 8, 22), 0.044, 0.05, 0.04, 0.045, 1.0]
chk(near(H.px_at([lst, nxt], H.day_end("2026-08-22")), 0.044), "P K9 상장 다음 날 = 그날 시가(정상)", H.px_at([lst, nxt], H.day_end("2026-08-22")))
chk(near(H.px_at([prev], T15), 100.0) and H.px_at([prev], H.day_end("2026-09-14")) is None, "P 그 시각이 든 봉 없음 = 3일 안 직전 종가 · 그 밖 None(종전)",
    (H.px_at([prev], T15), H.px_at([prev], H.day_end("2026-09-14"))))
chk(H.px_at([c80], U(2026, 9, 9, 23)) is None, "P 첫 봉 앞 = None(종전)", None)
h14 = [U(2026, 9, 10, 14), 101.0, 101.0, 100.0, 100.0, 1.0]
h15 = [U(2026, 9, 10, 15), 100.0, 100.0, 20.0, 20.0, 1.0]
chk(near(H.px_at([h14, h15], T15, step=3600), 100.0), "P K9 1시간봉 = 15:00 봉 시가(그 시각 가격 · 종전 = 급락 봉 종가 20)",
    H.px_at([h14, h15], T15, step=3600))
chk(near(H.px_at([h14, h15], T15 + 1800, step=3600), 100.0), "P 1시간봉 · 봉 중간 시각 = 그 봉 시가(종전 = 그 봉 종가 20)", H.px_at([h14, h15], T15 + 1800, step=3600))
pts = [[U(2026, 9, 10), 100.0, 100.0, 100.0, 100.0, 0], [U(2026, 9, 11), 80.0, 80.0, 80.0, 80.0, 0]]
chk(near(H.px_at(pts, T15, pts=True), 100.0), "P K9 점 = 그 시각 이하 마지막 점(뒤 점과 보간 안 함 · 종전 87.5)", H.px_at(pts, T15, pts=True))
chk(H.px_at(pts[:1], H.day_end("2026-09-13"), pts=True) is None, "P 점 2일 넘게 빔 = None(종전)", None)

BARS = {}
SEEN = []


def fake_cex(venue, base, quote, iv, t0, t1, now=None):
    SEEN.append((venue, base, quote, iv))
    rows = [r for r in BARS.get((venue, base, quote), []) if t0 <= r[0] < t1]
    return candles.Result(candles=rows or None, why=None if rows else "no_data")


H.candles.fetch_cex = fake_cex


def flat(y, m, d, v):
    return [U(y, m, d), v, v, v, v, 1.0]


BARS[("gate", "ABC", "USDT")] = [flat(2026, 9, d, 1.0) for d in range(1, 10)] + [
    [U(2026, 9, 10), 1.0, 1.0, 0.8, 0.8, 1.0],
    [U(2026, 9, 11), 0.8, 0.8, 0.4, 0.4, 1.0],
    flat(2026, 9, 12, 0.4)]
NOW = U(2026, 9, 13, 12)
old_910 = 1.0 + (0.8 - 1.0) * 15 / 24
prev_e = {"st": "ok", "n": 0, "lo": "2026-09-05", "hi": "2026-09-10", "src": ["gate:ABC_USDT"], "at": int(U(2026, 9, 11, 12)),
          "p": {"2026-09-%02d" % d: 1.0 for d in range(5, 10)}}
prev_e["p"]["2026-09-10"] = old_910
e1 = H.fetch_entry("ex:gate:ABC", "2026-09-05", "2026-09-11", NOW, need={"2026-09-11"}, prev=json.loads(json.dumps(prev_e)))
chk(near(e1["p"].get("2026-09-10"), old_910) and not e1.get("_chg"), "Q K9 받아 둔 9/10(종전 규칙 0.875) = 같은 봉으로 다시 받아도 그대로 · 변경 기록 없음",
    (e1["p"].get("2026-09-10"), e1.get("_chg")))
chk(near(e1["p"].get("2026-09-11"), 0.8), "Q K9 새 날(9/11) = 새 규칙(그 봉 시가 0.8 · 종전 보간 0.55)", e1["p"].get("2026-09-11"))
prev_b = json.loads(json.dumps(prev_e))
prev_b["p"]["2026-09-10"] = 0.9
e2 = H.fetch_entry("ex:gate:ABC", "2026-09-05", "2026-09-11", NOW, need={"2026-09-11"}, prev=prev_b)
chk(near(e2["p"].get("2026-09-10"), 1.0) and "2026-09-10" in (e2.get("_chg") or ()), "Q 봉이 바뀐 날 = 새 규칙으로 정정 · 변경 기록", (e2["p"].get("2026-09-10"), e2.get("_chg")))
e3 = H.fetch_entry("ex:gate:ABC", "2026-09-05", "2026-09-11", NOW)
chk(near(e3["p"].get("2026-09-10"), 1.0) and near(e3["p"].get("2026-09-11"), 0.8), "Q 처음 받는 날 = 새 규칙", (e3["p"].get("2026-09-10"), e3["p"].get("2026-09-11")))
BARS[("upbit", "USDT", "KRW")] = [flat(2026, 9, d, 1400.0) for d in range(1, 10)] + [[U(2026, 9, 10), 1400.0, 1400.0, 1300.0, 1300.0, 1.0],
                                                                                    [U(2026, 9, 11), 1300.0, 1300.0, 1200.0, 1200.0, 1.0]]
fx_old = round(1400.0 + (1300.0 - 1400.0) * 15 / 24, 4)
fx1 = H.fetch_fx_entry("2026-09-05", "2026-09-11", NOW, prev={"st": "ok", "lo": "2026-09-05", "hi": "2026-09-10", "p": {"2026-09-10": fx_old}})
chk(near(fx1["p"].get("2026-09-10"), fx_old) and near(fx1["p"].get("2026-09-11"), 1300.0), "Q K9 환율 = 받아 둔 날 그대로 · 새 날 새 규칙(그 봉 시가)",
    (fx1["p"].get("2026-09-10"), fx1["p"].get("2026-09-11")))

KW = set(inspect.signature(H.make_kit).parameters)


def kit_of(G, hold, floor=None, xkit=None, today="2026-10-09"):
    kw = {"first_floor": floor} if "first_floor" in KW else {}
    return H.make_kit(today, G, hold, set(), set(), {}, set(), {}, {}, {}, [], {}, [], {}, xkit=xkit, **kw)


def ts_kst(iso, h=10):
    return int(datetime.strptime(iso, "%Y-%m-%d").replace(hour=h, tzinfo=KST).timestamp())


G1 = {1: {"sym": "AAA", "qty_timeline": [(ts_kst("2025-06-15"), 5.0)]}, 2: {"sym": "BBB", "qty_timeline": [(ts_kst("2025-09-01"), 1.0)]}}
k1 = kit_of(G1, {1: 5.0, 2: 1.0})
chk(k1["first"] == "2025-06-15", "S NK3 첫 기록 2025-06-15 → 곡선 첫날 2025-06-15(종전 2026-01-01 고정)", k1["first"])
k2 = kit_of(G1, {1: 5.0, 2: 1.0}, floor=ts_kst("2026-01-01", 0))
chk(k2["first"] == "2026-01-01", "S NK3 고정 창 시작(backfill_since 2026-01-01) 앞으로는 안 감", k2["first"])
G3 = {1: {"sym": "AAA", "qty_timeline": [(ts_kst("2026-03-10"), 5.0)]}}
chk(kit_of(G3, {1: 5.0}, floor=ts_kst("2026-01-01", 0))["first"] == "2026-03-10", "S NK3 첫 기록이 창 시작보다 늦으면 첫 기록 날", None)
xk = {"src": {"now": {"ts": NOW}, "tl": {"ku": [(ts_kst("2025-04-02"), 1e6)], "kb": None}, "first": {"rest": ts_kst("2025-05-01")}}, "obs": {}, "days": {}}
chk(kit_of(G1, {1: 5.0, 2: 1.0}, xkit=xk)["first"] == "2025-04-02", "S NK3 원화 이력 첫 기록(2025-04-02)도 첫 기록", None)
chk(kit_of({}, {})["first"] == H.FIRST_DAY, "S 기록 없음 = 종전 첫날", None)
pth = os.path.join(T.TMP, "state", "s_hist.json")
HC = H.HistCurve(path=pth, px_path=os.path.join(T.TMP, "state", "s_hist_px.json"))
ds = H.days_between("2025-06-15", "2026-10-08")
HC.px["fx"] = {"lo": "2025-06-15", "hi": "2026-10-08", "st": "ok", "p": {d9: 1400.0 for d9 in ds}}
GS = {1: {"sym": "USDT", "is_stable": True, "qty_timeline": [(ts_kst("2025-06-15"), 100.0)]}}
HC.run_once(kit_of(GS, {1: 100.0}), cap=0, now=NOW)
code9, body9 = HC.view(None)
chk(body9["days"] and body9["days"][0][0] == "2025-06-15" and abs(body9["days"][0][1] - 100.0) < 0.01 and body9.get("first") == "2025-06-15",
    "S NK3 장기 곡선 '전체' = 첫 기록 날(2025-06-15)부터", (body9["days"][:1], body9.get("first")))

pth2 = os.path.join(T.TMP, "state", "s_hist2.json")
H.common.atomic_write_json(pth2, {"_v": H.HIST_V, "d": {"2026-01-01": [5.0, None, 0, "hc", 0], "2026-03-09": [5.0, None, 0, "hc", 0]},
                                  "s": {}, "meta": {"first": "2026-01-01", "pending": False, "flow_pending": False}})
HC2 = H.HistCurve(path=pth2, px_path=os.path.join(T.TMP, "state", "s_hist2_px.json"))
ds2 = H.days_between("2026-01-01", "2026-10-08")
HC2.px["fx"] = {"lo": "2026-01-01", "hi": "2026-10-08", "st": "ok", "p": {d9: 1400.0 for d9 in ds2}}
GL = {1: {"sym": "USDT", "is_stable": True, "qty_timeline": [(ts_kst("2026-03-10"), 100.0)]}}
HC2.run_once(kit_of(GL, {1: 100.0}, floor=ts_kst("2026-01-01", 0)), cap=0, now=NOW)
c2, b2 = HC2.view(None)
chk(b2.get("first") == "2026-03-10" and b2["days"] and b2["days"][0][0] == "2026-03-10" and "2026-01-01" in HC2.st["d"],
    "S NK3 cv402 저장본에 첫날 앞 행이 있어도 응답 = 첫 기록 날(03-10)부터 · 저장본 행은 그대로", (b2.get("first"), b2["days"][:1], sorted(HC2.st["d"])[:1]))

T.finish()
