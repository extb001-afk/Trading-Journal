#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import os
import time
from datetime import datetime, timedelta, timezone

import candles
import histcurve as H

chk = T.chk
KST = timezone(timedelta(hours=9))
NOW = time.time()
iso = lambda d: (datetime.fromtimestamp(NOW, KST) - timedelta(days=d)).strftime("%Y-%m-%d")
OLD1, OLD2, RECENT, OLD3 = iso(200), iso(150), iso(10), iso(250)
CALLS = []
FAIL = set()


def fake_entry(k, lo, hi, now, need=None, fx_get=None, prev=None, xref=None, blocked=None):
    b = candles._TL.bud
    if b is None or candles._bud_left(b) <= 0:
        return {"st": "wait", "lo": lo, "hi": hi, "p": {}, "why": "budget", "at": int(now)}
    candles._bud_take(b)
    CALLS.append((k, lo, hi))
    if k in FAIL:
        return {"st": "err", "n": 1, "lo": lo, "hi": hi, "p": {}, "why": "net", "at": int(now)}
    if k.startswith("ex:upbit:") and not (fx_get and all(fx_get(d) for d in need or ())):
        return {"st": "err", "n": 1, "lo": lo, "hi": hi, "p": {}, "why": "fx", "at": int(now)}
    return {"st": "ok", "lo": lo, "hi": hi, "p": {d: 2.5 for d in (need or ())}, "src": ["coingecko:x"], "at": int(now)}


def fake_fx(lo, hi, now, prev=None):
    b = candles._TL.bud
    candles._bud_take(b)
    CALLS.append(("fx", lo, hi))
    return {"st": "ok", "lo": lo, "hi": hi, "p": {d: 1400.0 for d in H.days_between(lo, hi)}, "src": "upbit:KRW-USDT", "at": int(now)}


REAL_FE = H.fetch_entry
H.fetch_entry = fake_entry
H.fetch_fx_entry = fake_fx
H.off_chains_now = lambda: set()


class FakeHist:
    def __init__(self):
        self.px = {"specs": {}, "fx": None}
        self.pending = False


def mk(day_calls=600):
    fh = FakeHist()
    dc = H.DayClose(path=os.path.join(T.TMP, "dc_%d.json" % len(CALLS)), hist=fh, run_calls=60, day_calls=day_calls)
    return dc, fh


dc, fh = mk()
p, st = dc.lookup("ca:eth:0xaa", OLD1, NOW, 0.0, old=True)
chk(p is None and "ca:eth:0xaa" in dc.want_old and "ca:eth:0xaa" not in dc.want, "O1 옛날 날 + old = 옛날 요청(want_old) · 30일 곡선 요청 아님", [st, dc.want_old, dc.want])
dc.lookup("ca:eth:0xbb", OLD1, NOW, 0.0, ask=False, old=True)
chk("ca:eth:0xbb" not in dc.want_old and "ca:eth:0xbb" not in dc.want, "O1 ask=False(원장 시작일 밖) = 요청 없음", [dc.want_old, dc.want])
dc.lookup("ca:eth:0xcc", RECENT, NOW, 0.0, old=True)
chk("ca:eth:0xcc" in dc.want and "ca:eth:0xcc" not in dc.want_old, "O1 최근 날 = 종전 요청(want)", [dc.want])

dc, fh = mk()
for i in range(3):
    dc.lookup(f"ca:eth:0x0{i}", RECENT, NOW, 100.0)
dc.lookup("ca:eth:0xaa", OLD1, NOW, 0.0, old=True)
del CALLS[:]
rep = dc._run(3, NOW)
chk(len(CALLS) == 3 and all(k.startswith("ca:eth:0x0") for k, _a, _b in CALLS) and "ca:eth:0xaa" in dc.want_old,
    "O2 실행 예산 3 = 30일 곡선 요청 3개 먼저 · 옛날 요청은 다음에(남는 몫 없음)", [CALLS, rep])

dc, fh = mk()
for i in range(60):
    dc.lookup(f"ca:eth:0xd{i:02d}", OLD1, NOW, 0.0, old=True)
del CALLS[:]
rep = dc._run(60, NOW)
chk(len(CALLS) == H.DC_OLD_RUN_CALLS and len(dc.want_old) == 60 - H.DC_OLD_RUN_CALLS, f"O3 남는 몫 = 옛날 요청 {H.DC_OLD_RUN_CALLS}개까지(실행 상한)", [len(CALLS), len(dc.want_old), rep])
fh.pending = True
del CALLS[:]
dc._run(60, NOW)
chk(len(CALLS) == H.DC_OLD_BUSY_CALLS, f"O3 장기 곡선 받는 중 = 옛날 요청 {H.DC_OLD_BUSY_CALLS}개만", len(CALLS))

dc, fh = mk()
dc.lookup("ca:eth:0xaa", OLD1, NOW, 0.0, old=True)
dc.lookup("ca:eth:0xaa", OLD2, NOW, 0.0, old=True)
dc._run(60, NOW)
p1, s1 = dc.lookup("ca:eth:0xaa", OLD1, NOW, 0.0, old=True)
chk(p1 == 2.5 and s1 == "ok" and "ca:eth:0xaa" in (dc.st.get("o") or {}) and not dc.want_old, "O4 받은 값 = 저장본 o · 조회 2.5 · 요청 지움", [p1, s1, dc.want_old])
dc2 = H.DayClose(path=dc.path, hist=fh)
p2, _s2 = dc2.lookup("ca:eth:0xaa", OLD2, NOW, 0.0, old=True)
chk(p2 == 2.5 and not dc2.want_old, "O4 다시 띄워도 저장본에서(보관 하한으로 안 버림)", p2)

del CALLS[:]
dc.want_old["ca:eth:0xaa"] = {"days": {OLD1}, "w": 0.0, "t0": NOW}
dc._run(60, NOW)
chk(not CALLS, "O5 이미 덮은 날 = 다시 안 받음(호출 0)", CALLS)
dc, fh = mk()
FAIL.add("ca:eth:0xee")
dc.lookup("ca:eth:0xee", OLD1, NOW, 0.0, old=True)
dc._run(60, NOW)
chk("ca:eth:0xee" in dc.want_old, "O5 일시 실패 = 요청 남김", dc.want_old)
FAIL.discard("ca:eth:0xee")
dc._run(60, NOW)
p5, _ = dc.lookup("ca:eth:0xee", OLD1, NOW, 0.0, old=True)
chk(p5 == 2.5 and not dc.want_old, "O5 다음 실행에 이어 받음", [p5, dc.want_old])
dc, fh = mk(day_calls=600)
dc.st["calls"] = [(int(NOW) - 60, 600)]
dc.lookup("ca:eth:0xff", OLD1, NOW, 0.0, old=True)
del CALLS[:]
dc._run(60, NOW)
chk(not CALLS and "ca:eth:0xff" in dc.want_old, "O5 하루 상한(30일 곡선과 합산 600) 다 쓰면 옛날 요청도 안 받음", CALLS)

dc, fh = mk()
dc.lookup("ex:upbit:ZZZ", OLD1, NOW, 0.0, old=True)
del CALLS[:]
dc._run(60, NOW)
p6, _ = dc.lookup("ex:upbit:ZZZ", OLD1, NOW, 0.0, old=True)
chk(CALLS and CALLS[0][0] == "fx" and p6 == 2.5 and isinstance(dc.st.get("fxo"), dict), "O6 업비트 보유 코인 = 그날 환율(fxo) 먼저 받고 → 시세", [CALLS, p6])
dc.lookup("ca:eth:0x11", OLD1, NOW, 0.0, old=True)
dc.lookup("ca:eth:0x11", OLD2, NOW, 0.0, old=True)
os9 = dc.old_status()
chk(os9["specs"] == 1 and os9["days"] == 2 and os9["done"] >= 1, "O6 진행 상태 = 남은 코인 1 · 날 2 · 받아 둔 출처 ≥ 1", os9)
dc.kick(NOW + 10_000)
chk(dc.ev.is_set(), "O6 옛날 요청만 있어도 배경 작업을 깨운다")
import buildproc
DCg = H.DAYCLOSE
DCg.want_old.clear()
hs = buildproc._hist_begin()
DCg.ask_old("ca:eth:0x77", {OLD1, OLD2}, 12.0, NOW)
res = buildproc._hist_end(hs)
DCg.want_old.clear()
buildproc._apply_hist(res)
chk(set((DCg.want_old.get("ca:eth:0x77") or {}).get("days") or ()) == {OLD1, OLD2} and float(DCg.want_old["ca:eth:0x77"].get("w") or 0) == 12.0,
    "O7 자식 빌드의 옛날 요청(날짜·중요도 w) → 부모 DayClose(want_old) 로 전달", [res.get("want_old_add"), DCg.want_old])

dc, fh = mk()
dc.lookup("ex:upbit:ZZZ", OLD1, NOW, 0.0, old=True)
dc._run(60, NOW)
dc.lookup("ex:upbit:YYY", OLD3, NOW, 0.0, old=True)
del CALLS[:]
dc._run(60, NOW)
p8, _ = dc.lookup("ex:upbit:YYY", OLD3, NOW, 0.0, old=True)
chk(any(k == "fx" for k, _a, _b in CALLS) and p8 == 2.5 and (dc.st.get("fxo") or {}).get("lo", "9999") <= OLD3 and (dc.st.get("fxo") or {}).get("hi", "") >= OLD1,
    "O8(fs323 ①) fxo 범위 밖 날 → 환율 범위 넓혀 다시 받고(전 범위 유지) 시세까지", [CALLS, p8, {k: (dc.st.get("fxo") or {}).get(k) for k in ("lo", "hi")}])

import hl_spot
HLN = []


def fake_hl(key, t0, t1, now=None, budget=30.0):
    HLN.append(key)
    return candles.Result(candles=[[int(t0) + i * 86400, 1.0, 1.0, 1.0, 3.0, 1.0] for i in range(int((t1 - t0) // 86400) + 2)], calls=1)


hl_spot.daily_candles = fake_hl
HLC = getattr(H, "HL_CALLS_PER_FETCH", 2)
H.fetch_entry = REAL_FE
dc, fh = mk()
for i in range(30):
    dc.lookup(f"ex:hyperliquid:H{i:02d}", OLD1, NOW, 0.0, old=True)
n0 = candles.CALLS["n"]
rep9 = dc._run(60, NOW)
H.fetch_entry = fake_entry
chk(len(HLN) == H.DC_OLD_RUN_CALLS // HLC and candles.CALLS["n"] - n0 == len(HLN) * HLC and rep9["calls"] == len(HLN) * HLC,
    f"O9(fs323 ②) HL 일봉 = 한 번에 {HLC}씩 같은 예산·장부 → 실행 상한 {H.DC_OLD_RUN_CALLS} 안({H.DC_OLD_RUN_CALLS // HLC}개)", [len(HLN), candles.CALLS["n"] - n0, rep9])

dc, fh = mk()
dc.lookup("ca:eth:0x99", OLD1, NOW, 0.0, old=True)
fh.px["specs"]["ca:eth:0x99"] = {"st": "ok", "lo": OLD1, "hi": OLD1, "p": {OLD1: 4.0}, "src": ["coingecko:x"], "at": int(NOW)}
del CALLS[:]
dc._run(60, NOW)
chk(not [c for c in CALLS if c[0] == "ca:eth:0x99"] and "ca:eth:0x99" not in dc.want_old, "O10(fs323 ③) 장기 곡선이 이미 받은 날 = 호출 없이 요청 지움", [CALLS, dc.want_old])
T.finish()
