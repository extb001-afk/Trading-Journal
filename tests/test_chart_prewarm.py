#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import urllib.parse  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

os.environ["TJ_HEALTH"] = "0"
import paths  # noqa: E402
import bf_engine  # noqa: E402
import candles  # noqa: E402
import sellchart  # noqa: E402
import review_daily as rd  # noqa: E402

chk = T.chk
KST = timezone(timedelta(hours=9))
TODAY = "2026-10-12"
T9 = datetime.strptime(TODAY, "%Y-%m-%d")


def ago(n):
    return (T9 - timedelta(days=n)).strftime("%Y-%m-%d")


class FakeWeb:

    def __init__(self, items, resp=None, default_calls=2):
        self.items, self.resp, self.default_calls = items, dict(resp or {}), default_calls
        self.paths, self.lists = [], 0

    def __call__(self, path):
        u = urllib.parse.urlsplit(path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        if u.path == "/api/receipt_list":
            self.lists += 1
            return {"ok": True, "items": [dict(x) for x in self.items]}
        if u.path != "/api/receipt_chart":
            raise AssertionError("모르는 경로 " + path)
        self.paths.append(path)
        side = q.get("side", "sell")
        key = f"{q['date']}|{q['sym']}|{side}"
        r = self.resp.get(key)
        if callable(r):
            r = r(path)
        if isinstance(r, list):
            r = r.pop(0) if r else None
        if isinstance(r, Exception):
            raise r
        if r is None:
            r = {"ok": True, "date": q["date"], "sym": q["sym"], "chart": {"ok": True, "tried": []}, "calls": self.default_calls}
            if side == "buy":
                r["side"] = "buy"
                r["segs"] = [{"ok": True, "tried": []}]
        return r

    def keys(self):
        out = []
        for p9 in self.paths:
            q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(p9).query).items()}
            out.append(f"{q['date']}|{q['sym']}|{q.get('side', 'sell')}")
        return out


SLEPT = []


def fsleep(s):
    SLEPT.append(s)


def reset_pw():
    for p9 in (paths.state("candles", "prewarm.json"), paths.state("candles", "dex_later.json")):
        try:
            os.remove(p9)
        except OSError:
            pass
    sellchart._DL["items"] = None


def run(n, web, dex_cap=30, today=TODAY, stop=None):
    return rd.prewarm_charts({"review": {"chart_prewarm_per_day": n}}, get=web, sleep=fsleep, today_iso=today,
                             stop_check=stop or (lambda: None), dex_cap=dex_cap)


reset_pw()
w = FakeWeb([{"date": ago(5), "sym": "AAA", "vk": ["cex"]}])
chk(run(0, w) is None and w.lists == 0 and not w.paths, "A1 기본 0(꺼짐) = 영수증 목록·차트 조회 0", (w.lists, w.paths))
chk(rd.prewarm_per_day({}) == 0 and rd.prewarm_per_day({"review": {}}) == 0 and rd.prewarm_per_day({"review": {"chart_prewarm_per_day": "x"}}) == 0
    and rd.prewarm_per_day({"review": {"chart_prewarm_per_day": 99999}}) == rd.PREWARM_MAX,
    "A1 설정 없음·이상 = 0 · 상한 PREWARM_MAX")
chk(rd._prewarm_start({}) is None and rd._PW_THREAD[0] is None, "A1 꺼짐 = 미리 받기 스레드도 안 띄움")
chk(not os.path.exists(paths.state("candles", "prewarm.json")), "A1 꺼짐 = 기록 파일도 안 씀")

reset_pw()
items = [{"date": ago(300 + i), "sym": f"C{i}", "vk": ["cex"]} for i in range(10)]
w = FakeWeb(items)
c = run(3, w)
chk(len(w.paths) == 3 and c["counted"] == 3 and c["stopped"] == "하루 상한", "A2 하루 상한 N=3 = 차트 요청 3번에서 멈춤", (w.paths, c))
chk(all("bg=1" in p9 and "inp=" not in p9 for p9 in w.paths), "A2 요청 = bg=1 · inp 없음(평가 입력·모델 호출 0)", w.paths)
st = json.load(open(paths.state("candles", "prewarm.json"), encoding="utf-8"))
chk(st.get("day") == TODAY and st.get("n") == 3 and len(st.get("done") or {}) == 3, "A2 하루 진행·다 받음 기록 = state/candles/prewarm.json", st)
chk(os.path.isfile(os.path.join(paths.STATE_DIR, "candles", "prewarm.json")), "A2 기록 위치 = state/candles(tj-web 빌드 입력 서명 밖 · reset_pw 로 지운 뒤 실행이 만든 파일)")
w2 = FakeWeb(items)
c2 = run(3, w2)
chk(not w2.paths and c2["stopped"] == "하루 상한", "A3 재시작 뒤에도 그날 상한 유지(기록 파일)", (w2.paths, c2))
w3 = FakeWeb(items)
c3 = run(3, w3, today="2026-10-13")
k3 = w3.keys()
chk(len(w3.paths) == 3 and c3["counted"] == 3, "A3 날 바뀜 = 하루 수만 0 — 다시 3번", (k3, c3))
chk(not (set(k3) & set(w.keys())), "A4 다 받은 것(어제) 다시 안 부름", (k3, w.keys()))

reset_pw()
items = [{"date": ago(10), "sym": "NEWCEX", "vk": ["cex"]},
         {"date": ago(500), "sym": "OLDCEX", "vk": ["cex"]},
         {"date": ago(100), "sym": "DEX100", "vk": ["dex"]},
         {"date": ago(170), "sym": "DEX170", "vk": ["dex"]},
         {"date": ago(30), "sym": "GATE30", "vk": ["gate"]},
         {"date": ago(400), "sym": "DEX400", "vk": ["dex"]},
         {"date": ago(200), "sym": "DEX200", "vk": ["dex"]},
         {"date": ago(50), "sym": "MIX", "vk": ["cex", "dex"]}]
sellchart.dex_later_mark(ago(20), "LATER", "buy", "deferred")
order = rd.prewarm_order(items, sellchart.dex_later_read(), TODAY)
seq = [f"{o[1]}:{o[2]}" for o in order]
want = ["GATE30:sell", "GATE30:buy", "DEX170:sell", "DEX170:buy", "DEX100:sell", "DEX100:buy", "MIX:sell", "MIX:buy", "LATER:buy",
        "DEX200:sell", "DEX200:buy", "OLDCEX:sell", "OLDCEX:buy", "NEWCEX:sell", "NEWCEX:buy"]
chk(seq == want, "A4 차례 = 게이트 34일 → DEX 179일 임박 순 → 코인게코 364일 → 기한 없는 거래소 오래된 것부터 · '나중에 채움' 포함", seq)
chk(not any(s.startswith("DEX400") for s in seq), "A4 기한 지난 DEX(400일 — GeckoTerminal·코인게코 둘 다 밖) 건너뜀", seq)
chk(rd.ret_left(["dex"], 10) == 169 and rd.ret_left(["dex"], 200) == 164 and rd.ret_left(["dex"], 400) == "expired" and rd.ret_left(["cex"], 900) is None
    and rd.ret_left(["gate"], 40) is None and rd.ret_left([], 5) is None, "A4 보존 기한 계산(DEX 179/364 · 게이트 34 · 거래소 없음)")
w = FakeWeb(items)
c = run(50, w)
chk(w.keys()[:4] == [f"{ago(30)}|GATE30|sell", f"{ago(30)}|GATE30|buy", f"{ago(170)}|DEX170|sell", f"{ago(170)}|DEX170|buy"],
    "A4 실제 요청도 그 차례", w.keys()[:6])
chk(f"{ago(20)}|LATER|buy" in w.keys(), "A4 '나중에 채움' 목록 영수증도 받음", w.keys())

reset_pw()
items = [{"date": ago(300 + i), "sym": f"Z{i}", "vk": ["cex"]} for i in range(6)]
w = FakeWeb(items, default_calls=0)
c = run(2, w)
chk(c["counted"] == 0 and len(w.paths) == 4 and c["stopped"] == "회차 상한" and c["done"] == 4,
    "A5 이미 캐시(외부 호출 0) = 하루 상한에 안 셈(다 받음 기록 · 한 회차 요청은 2N 까지)", c)
w2 = FakeWeb(items, default_calls=0)
run(2, w2)
chk(not (set(w2.keys()) & set(w.keys())), "A5 다음 회차 = 다 받은 것 건너뛰고 나머지", (w.keys(), w2.keys()))

reset_pw()
items = [{"date": ago(300 + i), "sym": f"B{i}", "vk": ["cex"]} for i in range(4)]
busy = {"ok": True, "status": "busy", "retryAfter": 3}
prep = {"ok": True, "status": "preparing", "retryAfter": 3}
w = FakeWeb(items, resp={f"{ago(303)}|B3|sell": [busy], f"{ago(303)}|B3|buy": [prep, prep, None]})
SLEPT.clear()
c = run(20, w)
chk(c["busy"] == 1 and f"{ago(303)}|B3|sell" not in json.load(open(paths.state("candles", "prewarm.json"), encoding="utf-8"))["done"]
    and rd.PREWARM_BUSY_WAIT_S in SLEPT, "A6 202 busy = 그 건 양보(다 받음 아님 · 잠시 쉼) 뒤 다음 차례", (c, SLEPT[:5]))
chk(w.keys().count(f"{ago(303)}|B3|buy") == 3 and c["done"] == 7, "A6 202 준비 중 = retryAfter 뒤 같은 건 다시(끝나면 다 받음)", (w.keys(), c))
reset_pw()
w = FakeWeb(items, resp={f"{ago(300 + i)}|B{i}|{s}": [busy] for i in range(4) for s in ("sell", "buy")})
c = run(20, w)
chk(c["busy"] == rd.PREWARM_BUSY_MAX and c["stopped"] == "화면 차트 수집 중(양보)", "A6 연속 busy = 이번 회차 끝(화면이 쓰는 중)", c)

reset_pw()
items = [{"date": ago(100), "sym": "D1", "vk": ["dex"]}, {"date": ago(110), "sym": "D2", "vk": ["dex"]},
         {"date": ago(300), "sym": "C1", "vk": ["cex"]}]
w = FakeWeb(items, resp={f"{ago(110)}|D2|sell": {"ok": True, "dexLater": "deferred", "chart": {"ok": True, "tried": []}, "calls": 1},
                         f"{ago(110)}|D2|buy": {"ok": True, "side": "buy", "dexLater": "bg_stop", "chart": {"ok": True}, "segs": [], "calls": 1}})
c = run(20, w)
st = json.load(open(paths.state("candles", "prewarm.json"), encoding="utf-8"))
chk(f"{ago(110)}|D2|sell" not in st["done"] and c["later"] >= 1, "A7 dexLater(대체 봉) = 다 받음 아님(다음에 다시)", (st["done"], c))
chk(st.get("dex_stop") == TODAY and not any("D1" in k for k in w.keys()) and c["skipped_dex"] == 2 and any("C1" in k for k in w.keys()),
    "A7 DEX 429(bg_stop) = 그날 DEX 영수증만 건너뜀 · 거래소 봉은 계속", (w.keys(), c, st.get("dex_stop")))
reset_pw()
w = FakeWeb(items)
c = run(20, w, dex_cap=1)
chk(c["dex"] == 1 and c["skipped_dex"] == 3 and sum(1 for k in w.keys() if "|C1|" in k) == 2, "A7 DEX 하루 몫(키 종류별 자동 상한) = 넘으면 DEX 만 건너뜀", (w.keys(), c))
chk(rd.prewarm_dex_cap() == (rd.PREWARM_DEX_BASE, "none"), "A7 무키 = DEX 몫 기본(무키 GeckoTerminal 분당 1회)", rd.prewarm_dex_cap())
reset_pw()
w = FakeWeb(items, resp={f"{ago(300)}|C1|sell": {"ok": True, "chart": {"ok": False, "tried": [{"why": "net"}]}, "calls": 1},
                         f"{ago(300)}|C1|buy": {"ok": True, "side": "buy", "chart": {"ok": False}, "segs": [{"ok": False, "tried": [{"why": "no_market"}]}],
                                                "calls": 1}})
c = run(20, w)
st = json.load(open(paths.state("candles", "prewarm.json"), encoding="utf-8"))
chk(f"{ago(300)}|C1|sell" not in st["done"] and st["done"].get(f"{ago(300)}|C1|buy", {}).get("r") == "none",
    "A7 일시 실패(net) = 다음에 다시 · 영영 없음(no_market) = 다 받음(그릴 것 없음)", st["done"])

reset_pw()
items = [{"date": ago(300 + i), "sym": f"E{i}", "vk": ["cex"]} for i in range(5)]
w = FakeWeb(items, resp={f"{ago(300 + i)}|E{i}|{s}": OSError("tj-web 꺼짐") for i in range(5) for s in ("sell", "buy")})
c = run(20, w)
chk(c["err"] == rd.PREWARM_ERR_MAX and c["stopped"].startswith("조회 실패"), "A8 차트 조회 실패 연속 = 이번 회차 끝(예외 안 남)", c)
w = FakeWeb(items)
c = run(20, w, stop=lambda: "자동 생성 멈춤(설정)")
chk(c == {"stopped": "자동 생성 멈춤(설정)"} and not w.paths and w.lists == 0, "A8 멈춤(review_paused·수동 보충) = 아무것도 안 부름", (c, w.paths))
_orig = rd.prewarm_charts
rd.prewarm_charts = lambda cfg: (_ for _ in ()).throw(RuntimeError("boom"))
r8 = T.safe(rd._prewarm_safe, {"review": {"chart_prewarm_per_day": 5}})
rd.prewarm_charts = _orig
chk(r8 is None, "A8 미리 받기 예외 = _prewarm_safe 가 삼킴(데몬 안 죽음)", r8)
calls8 = []
rd.prewarm_charts = lambda cfg: calls8.append(1)
t8 = rd._prewarm_start({"review": {"chart_prewarm_per_day": 5}})
t8.join(5)
rd.prewarm_charts = _orig
chk(t8 is not None and calls8 == [1] and t8.daemon, "A8 켜짐 = 배경 스레드 하나(데몬 스레드)", (t8, calls8))
src_rd = open(os.path.join(T.SRC, "review_daily.py"), encoding="utf-8").read()
import re  # noqa: E402
ev9 = [m9.start() for m9 in re.finditer(r"^[ \t]+_receipt_evals_safe\(cfg\)", src_rd, re.M)]
pw9 = [m9.start() for m9 in re.finditer(r"^[ \t]+_prewarm_start\(cfg\)", src_rd, re.M)]
chk(len(pw9) == 2 and len(ev9) == 2 and ev9[0] < pw9[0] < ev9[1] < pw9[1],
    "A8 호출 위치 = 기동·일간 회차의 영수증 평가 뒤", (ev9, pw9))

r9 = rd.eval_one({}, ago(3), "X", "sell", get=lambda p: {"ok": True, "dexLater": "deferred", "evalFp": "f", "evalInput": {"a": 1}},
                 sleep=fsleep, runner=lambda *a: (_ for _ in ()).throw(AssertionError("모델 호출")))
chk(r9 == "nochart", "A9 dexLater 차트 = 평가 건너뜀(DEX 봉 채운 뒤에 — 모델 두 번 안 부름)", r9)

NOW = int(time.time())
GT_CALLS, BN_CALLS = [], []
MODE = {"gt": "ok", "bn": "ok"}


def gt_rows(b, n, s=300):
    return {"data": {"attributes": {"ohlcv_list": [[b - (i + 1) * s, 1.0, 1.1, 0.9, 1.05, 100.0] for i in range(n)]}}}


def fake_get(url, headers=None, timeout=20.0, deadline=None, inline_wait=10.0, gate_host=None, single=False):
    host = urllib.parse.urlsplit(url).hostname
    nc9 = getattr(candles._TL, "ncalls", None)
    if nc9 is not None:
        nc9[0] += 1
    if host == "api.geckoterminal.com":
        GT_CALLS.append((url, single))
        if MODE["gt"] == "429":
            raise bf_engine.NetError("http 429 Too Many Requests", "http429", code=429, host=host)
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        return gt_rows(int(q["before_timestamp"]), int(q["limit"]))
    if host == "api.binance.com":
        BN_CALLS.append(url)
        if MODE["bn"] == "none":
            raise bf_engine.NetError("http 400 Invalid symbol -1121", "http4xx", code=400, host=host)
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        a = int(q["startTime"]) // 1000
        return [[(a + i * 300) * 1000, "1.0", "1.1", "0.9", "1.05", "10"] for i in range(20)]
    if host == "api.bybit.com":
        return {"retCode": 10001, "retMsg": "symbol invalid"}
    raise AssertionError("모르는 호스트 " + str(host))


candles._get = fake_get
T0 = (NOW - 3 * 86400) // 300 * 300
T1 = T0 + 6 * 3600
DEX = {"venue": "dex", "chain": "base", "token": "0x" + "ab" * 20, "pool": "0x" + "cd" * 20}
plan = candles.plan_chain(DEX, "ABC", "USD")
g9 = bf_engine.gate("api.geckoterminal.com")
g9.pause_until = time.time() + 120

with candles.chart_mode("fg"):
    r = candles.fetch_gt("base", DEX["pool"], DEX["token"], "5m", T0, T1)
chk(r.why == "deferred" and r.calls == 0 and not GT_CALLS and r.note == candles.DEFER_NOTE, "B1 화면 + 게이트 막힘 = DEX 봉 미룸(호출 0)", (r, GT_CALLS))
with candles.chart_mode("fg"):
    res = candles.best_chart(plan, "5m", T0, T1, "USD", ref_px=1.0)
chk(res["ok"] and res["src"]["venue"] == "binance" and res.get("dexLater") == "deferred" and res["tried"][0]["why"] == "deferred"
    and res["src"]["fallback"] and not GT_CALLS, "B1 미룬 DEX → 같은 해상도 CEX 봉(바이낸스)으로 그림 · dexLater='deferred'", res.get("tried"))
cp_dex = candles._cpath("dex", "base", DEX["pool"].lower(), DEX["token"].lower(), "5m", T0, T1)
chk(not os.path.exists(cp_dex), "B1 대체 봉은 DEX 디스크 캐시를 만들지 않음(나중에 DEX 봉을 받는다)", cp_dex)
MODE["bn"] = "none"
n_bn = len(BN_CALLS)
plan2 = candles.plan_chain(DEX, "XYZ", "USD")
with candles.chart_mode("fg"):
    res2 = candles.best_chart(plan2, "5m", T0, T1, "USD", ref_px=1.0)
chk(res2["ok"] and res2["src"]["venue"] == "dex" and res2.get("dexLater") is None and len(GT_CALLS) >= 1,
    "B2 CEX 봉도 없음(DEX 전용 코인) = 종전 그대로 DEX 봉을 받음(2차)", (res2.get("tried"), res2.get("src"), len(BN_CALLS) - n_bn))
chk(os.path.exists(cp_dex) and (candles._cache_get(cp_dex) or {}).get("complete") == candles.CACHE_V, "B2 받은 DEX 봉 = 영구 캐시(완결 표식)")
MODE["bn"] = "ok"
GT_CALLS.clear()
T0b, T1b = T0 - 86400, T1 - 86400
r = candles.fetch_gt("base", DEX["pool"], DEX["token"], "5m", T0b, T1b)
chk(r.ok and len(GT_CALLS) == 1, "B3 방식 없음(종전 호출자 — histcurve 등) = 게이트 막힘이어도 종전처럼 부름", (r, GT_CALLS))
g9.pause_until = 0.0

GT_CALLS.clear()
candles._BG["last"].clear()
candles._BG["stop"].clear()
T0c, T1c = T0 - 2 * 86400, T1 - 2 * 86400
with candles.chart_mode("bg"), candles.hard_deadline(time.time() + 300):
    ra = candles.fetch_gt("base", DEX["pool"], DEX["token"], "5m", T0c, T1c)
chk(ra.ok and len(GT_CALLS) == 1 and GT_CALLS[0][1] is True, "B4 미리 받기 첫 GT 콜 = 바로 · 재시도 없이 한 번(single)", GT_CALLS)
with candles.chart_mode("bg"), candles.hard_deadline(time.time() + 30):
    rb = candles.fetch_gt("base", DEX["pool"], DEX["token"], "5m", T0c - 86400, T1c - 86400)
chk(rb.why == "bg_pace" and rb.calls == 0 and len(GT_CALLS) == 1, "B4 분당 1회 간격 = 마감 안에 못 기다리면 미룸(호출 0)", (rb, GT_CALLS))
candles.BG_PACE_S, old_pace = 0.3, candles.BG_PACE_S
candles._BG["last"]["api.geckoterminal.com"] = time.time()
t9 = time.time()
with candles.chart_mode("bg"), candles.hard_deadline(time.time() + 300):
    rc = candles.fetch_gt("base", DEX["pool"], DEX["token"], "5m", T0c - 86400, T1c - 86400)
chk(rc.ok and len(GT_CALLS) == 2 and time.time() - t9 >= 0.15, "B4 마감 안이면 간격만큼 기다렸다 부름", (rc, time.time() - t9))
time.sleep(0.35)
MODE["gt"] = "429"
with candles.chart_mode("bg"), candles.hard_deadline(time.time() + 300):
    rd9 = candles.fetch_gt("base", DEX["pool"], DEX["token"], "5m", T0c - 3 * 86400, T1c - 3 * 86400)
MODE["gt"] = "ok"
time.sleep(0.35)
n_gt = len(GT_CALLS)
with candles.chart_mode("bg"), candles.hard_deadline(time.time() + 300):
    re9 = candles.fetch_gt("base", DEX["pool"], DEX["token"], "5m", T0c - 4 * 86400, T1c - 4 * 86400)
chk(rd9.why == "bg_stop" and candles.bg_stopped() and re9.why == "bg_stop" and len(GT_CALLS) == n_gt,
    "B5 미리 받기 429 = 그날 GeckoTerminal 멈춤(다음 콜 안 부름)", (rd9, re9))
with candles.chart_mode("fg"):
    rf9 = candles.fetch_gt("base", DEX["pool"], DEX["token"], "5m", T0c - 4 * 86400, T1c - 4 * 86400)
chk(rf9.ok and len(GT_CALLS) == n_gt + 1, "B5 멈춤은 미리 받기만 — 화면 요청은 그대로 부름", rf9)
candles.BG_PACE_S = old_pace
candles._BG["stop"].clear()
candles._BG["last"]["api.geckoterminal.com"] = time.time()
with candles.chart_mode("bg"), candles.hard_deadline(time.time() + 40):
    res5 = candles.best_chart(plan, "5m", T0c - 5 * 86400, T1c - 5 * 86400, "USD", ref_px=1.0)
chk(res5["ok"] and res5.get("dexLater") == "bg_pace" and res5["src"]["venue"] == "binance", "B5 미리 받기 간격 미룸 = 사슬은 이어 감(대체 봉 · 나중에 채움)", res5.get("tried"))

import cgkey  # noqa: E402
import nft  # noqa: E402
_k, _p, _b, _w, _bud = cgkey.key, cgkey.plan_of, candles.cgplan_basis, nft.cg_key_windows, cgkey.budget
REQ = []
_req = cgkey.request
cgkey.request = lambda path, lane, via, allow=True, valid=None: (REQ.append(lane), ("skip", "test"))[1]
cgkey.key = lambda: "k-test"


class FB:
    used = 100

    def cg_usage(self):
        return {"total": self.used}

    def now(self):
        return time.time()

    def month_count(self, k):
        return 0


cgkey.budget = lambda: FB()
url9 = "https://api.geckoterminal.com/api/v2/networks/base/pools/x/ohlcv/minute?aggregate=5"
with candles.chart_mode("bg"):
    kd = candles._keyed(url9, "past", True, None, time.time() + 30)
chk(kd == ("skip", "bg") and not REQ, "B6 데모 키 + 미리 받기 = 키 장부 안 씀(무키 분당 1회로)", (kd, REQ))
with candles.chart_mode("fg"):
    candles._keyed(url9, "past", True, None, time.time() + 30)
chk(REQ == ["past"], "B6 화면 요청은 종전 그대로 키 먼저", REQ)
cgkey.plan_of = lambda k: ("pro", {"plan": "pro"})
candles.cgplan_basis = lambda rec, b, share: "pro"
nft.cg_key_windows = lambda rec, b=None, share=None: (60, 1000)
FB.used = 100
chk(candles._bg_key_ok(), "B6 프로 + 지난 24시간 100/1000 = 미리 받기도 키(절반 500 아래)")
FB.used = 500
chk(not candles._bg_key_ok(), "B6 프로라도 지난 24시간이 하루 몫 절반에 닿으면 키 안 씀(가격·곡선 몫)")
FB.used = 100
cap9, plan9 = rd.prewarm_dex_cap()
chk(plan9 == "pro" and cap9 == rd.PREWARM_DEX_BASE + (500 - 100) // rd.PREWARM_KEY_CALLS, "B6 프로 = DEX 몫 = 기본 + 남는 키 몫 ÷ 한쪽당 콜", (cap9, plan9))
FB.used = 900
chk(rd.prewarm_dex_cap()[0] == rd.PREWARM_DEX_BASE, "B6 프로 키 몫이 바닥(하루 몫을 거의 다 씀) = 기본 몫만", rd.prewarm_dex_cap())
cgkey.key, cgkey.plan_of, candles.cgplan_basis, nft.cg_key_windows, cgkey.budget, cgkey.request = _k, _p, _b, _w, _bud, _req

with candles.count_calls() as nc:
    with candles.chart_mode("fg"):
        candles.best_chart(plan, "5m", T0 - 9 * 86400, T1 - 9 * 86400, "USD", ref_px=1.0)
chk(nc[0] >= 1, "B7 count_calls = 이 스레드 외부 호출 수", nc)
with candles.count_calls() as nc2:
    candles.best_chart(plan, "5m", T0 - 9 * 86400, T1 - 9 * 86400, "USD", ref_px=1.0)
chk(nc2[0] == 0, "B7 다시 = 디스크 캐시라 호출 0(미리 받기가 상한에 안 셈)", nc2)

import web  # noqa: E402

reset_pw()
o = {"ok": True, "autoEval": True}
web.StateBuilder._dex_later(o, "2026-10-01", "ABC", "sell", "deferred")
it = sellchart.dex_later_read()
chk(o.get("dexLater") == "deferred" and o.get("autoEval") is False and "2026-10-01|ABC|sell" in it, "C1 dexLater = 자동 평가 끔 · '나중에 채움' 목록에 넣음", (o, it))
chk(os.path.isfile(os.path.join(paths.STATE_DIR, "candles", "dex_later.json")), "C1 목록 위치 = state/candles(빌드 서명 밖 · reset_pw 로 지운 뒤 _dex_later 가 만든 파일)")
o1 = {"ok": True, "autoEval": True}
web.StateBuilder._dex_later(o1, "2026-10-01", "ABC", "sell", None, listed=False)
chk("2026-10-01|ABC|sell" in sellchart.dex_later_read() and "dexLater" not in o1,
    "C1 다른 보기(1분봉·판 뒤 6시간·다른 장소 칩)는 목록을 건드리지 않음(기본 보기의 '나중에 채움'을 지우지 않게)")
src_w = T.web_src()
chk('listed=(iv == "5m" and after == "1h" and not venue)' in src_w and 'listed=(iv == "5m" and not venue and not bvenue)' in src_w,
    "C1 목록 = 미리 받기와 같은 기본 보기에서만")
o2 = {"ok": True, "autoEval": True}
web.StateBuilder._dex_later(o2, "2026-10-01", "ABC", "sell", None)
chk("dexLater" not in o2 and o2["autoEval"] is True and not sellchart.dex_later_read(), "C1 DEX 로 그림(사유 없음) = 목록에서 뺌 · 자동 평가 그대로", o2)
mt = os.stat(paths.state("candles", "dex_later.json")).st_mtime_ns
web.StateBuilder._dex_later({}, "2026-10-02", "Q", "buy", None)
chk(os.stat(paths.state("candles", "dex_later.json")).st_mtime_ns == mt, "C1 바뀐 것 없으면 안 씀")
sb = web.StateBuilder.__new__(web.StateBuilder)
chk(not any(n.startswith("chart_dex_later") or n == "prewarm.json" for n in os.listdir(paths.STATE_DIR)), "C1 state 맨 위에 새 파일 없음(재빌드 유발 없음)",
    os.listdir(paths.STATE_DIR))

D2 = "2026-10-01"
ts2 = int(datetime.strptime(D2, "%Y-%m-%d").replace(tzinfo=KST).timestamp()) + 3600
sb._day_idx = {"builtAt": 1, "pos": [{"sym": "AAA", "realizedByDay": {D2: 5.0}}, {"sym": "BBB", "realizedByDay": {D2: -3.0}},
                                     {"sym": "CCC", "realizedByDay": {D2: 1.0}}],
               "ix": {D2: [(ts2, "pos", {"k": "온체인 매도", "d": "Base · 스왑"}, ("g1", "AAA", "Base")),
                           (ts2, "pos", {"k": "거래소 매도", "d": "업비트 · 현물 체결", "src": "ex:upbit"}, ("g2", "BBB", "업비트")),
                           (ts2, "pos", {"k": "거래소 매수", "d": "게이트 · 현물 체결", "src": "ex:gate"}, ("g3", "CCC", "게이트")),
                           (ts2, "pos", {"k": "거래소 매도", "d": "바이낸스 · 현물 체결", "src": "ex:binance"}, ("g3", "CCC", "바이낸스"))]}}
lst = sb.receipt_list(D2, D2)
vk = {x["sym"]: x.get("vk") for x in lst["items"]}
chk(vk == {"AAA": ["dex"], "BBB": ["cex"], "CCC": ["cex", "gate"]}, "C2 영수증 목록 = 장소 종류(vk: dex·cex·gate — 미리 받기 차례용)", vk)

SEEN = []


def fake_rc(iso, sym, iv="5m", after="1h", venue=None, fetch=True, cache_only=False):
    if cache_only:
        return None
    SEEN.append(candles.chart_mode_now())
    nc9 = getattr(candles._TL, "ncalls", None)
    if nc9 is not None:
        nc9[0] += 3
    return {"ok": True, "date": iso, "sym": sym, "chart": {"ok": True}}


sb.receipt_chart = fake_rc
J = web.StateBuilder._CHART_JOBS
J.clear()
J[("x",)] = {"ev": threading.Event(), "done": False, "res": None, "t": time.time()}
r3 = sb.chart_request(D2, "AAA", bg=True)
chk(r3 == (None, "busy") and not SEEN, "C3 bg = 다른 차트 수집이 돌고 있으면 바로 busy(양보)", r3)
J.clear()
r3b = sb.chart_request(D2, "AAA", bg=True, wait=5)
chk(r3b[1] == "ok" and r3b[0].get("calls") == 3 and SEEN == ["bg"], "C3 bg 작업 = chart_mode 'bg' · 응답에 이번 외부 호출 수", (r3b, SEEN))
J.clear()
J[("y",)] = {"ev": threading.Event(), "done": False, "res": None, "t": time.time(), "bg": True}
r3c = sb.chart_request(D2, "BBB", wait=5)
chk(r3c[1] == "ok" and SEEN[-1] == "fg" and "calls" not in r3c[0], "C3 화면 요청 = 미리 받기 작업을 세지 않음(화면 몫 2개 그대로) · 방식 'fg'", (r3c, SEEN))
J.clear()
del sb.receipt_chart

sb.receipt = lambda iso, sym: {"ok": True, "sym": "AAA", "builtAt": 7}
ck = (7, D2, "AAA", "5m", "1h", "", True)
sb._chart_cache = {ck: (time.time(), {"ok": True, "date": D2, "sym": "AAA", "dexLater": "deferred", "chart": {"ok": True}})}
with candles.chart_mode("bg"):
    h_bg = sb.receipt_chart(D2, "AAA", cache_only=True)
with candles.chart_mode("fg"):
    h_fg = sb.receipt_chart(D2, "AAA", cache_only=True)
chk(h_bg is None and isinstance(h_fg, dict) and h_fg.get("dexLater") == "deferred", "C4 응답 캐시의 대체 봉 본문 = 화면은 그대로 · 미리 받기는 다시 받음", (h_bg, h_fg))

js = T.app_js()
chk("' 봉 대신 '" in js and "오늘 몫 소진 — DEX 봉은 나중에 채움" in js and js.count("rcFbTxt(") >= 3 and js.count("rcLaterTxt(") >= 2,
    "C5 화면 = '… 봉 대신 …' + '오늘 몫 소진 — DEX 봉은 나중에 채움'(매도·매수 출처 줄)")
chk("chart_prewarm_per_day" in T.doc_text("README.md"), "C5 README = config 키 설명")

import onboarding  # noqa: E402


class FH:
    _DAY_RE, _IV_OK, _AFTER_OK = web.Handler._DAY_RE, web.Handler._IV_OK, web.Handler._AFTER_OK
    _chart_args = web.Handler._chart_args
    headers = {"Host": "127.0.0.1:8023"}
    client_address = ("127.0.0.1", 1)

    def __init__(self):
        self.out = None

    def _send(self, code, body, *a, **k):
        self.out = (code, body)


def send_chart(builder, q):
    old = web.BUILDER
    web.BUILDER = builder
    try:
        h = FH()
        r = T.safe(web.Handler._send_receipt_chart, h, q)
        return r, h.out
    finally:
        web.BUILDER = old


DB9 = onboarding.DemoBuilder(web)
for q9 in (f"date={D2}&sym=BTC&side=fut", f"date={D2}&sym=BTC", f"date={D2}&sym=BTC&bg=1"):
    r9, o9 = send_chart(DB9, q9)
    chk(not (isinstance(r9, dict) and r9.get("_exc")) and o9 and o9[0] == 200, f"D1(HIGH) 데모 빌더 차트 요청 = 200(bg 인자로 TypeError 500 없음) · {q9}", (r9, o9 and o9[0]))

sbx = web.StateBuilder.__new__(web.StateBuilder)
sbx._day_idx = {"builtAt": 1}
RC9 = {}


def rc9(iso, sym, iv="5m", after="1h", venue=None, fetch=True, cache_only=False):
    if (iso, sym) in RC9:
        return dict(RC9[(iso, sym)])
    if cache_only:
        return None
    time.sleep(0.3)
    nc9 = getattr(candles._TL, "ncalls", None)
    if nc9 is not None:
        nc9[0] += 4
    out = {"ok": True, "date": iso, "sym": sym, "chart": {"ok": True}}
    RC9[(iso, sym)] = out
    return out


sbx.receipt_chart = rc9
J.clear()
p1 = sbx.chart_request(D2, "PP", bg=True, wait=0.01)
for _ in range(100):
    if all(j9["done"] for j9 in J.values()):
        break
    time.sleep(0.05)
p2 = sbx.chart_request(D2, "PP", bg=True, wait=1)
chk(p1 == (None, "preparing") and p2[1] == "ok" and (p2[0] or {}).get("calls") == 4,
    "D2(MEDIUM) 준비 중 → 다시 물음 = 끝난 미리 받기 작업의 외부 호출 수 4(응답 캐시 0 으로 하루 상한 우회 없음)", (p1, p2))
p3 = sbx.chart_request(D2, "PP", bg=True, wait=1)
chk(p3[1] == "ok" and (p3[0] or {}).get("calls") == 0, "D2 그 뒤 같은 요청 = 응답 캐시(호출 0)", p3)
r9b = sbx.chart_request(D2, "PP", wait=1)
chk(r9b[1] == "ok" and "calls" not in (r9b[0] or {}), "D2 화면 요청은 종전 그대로(캐시 · calls 없음)", r9b)
J.clear()


class FT:
    def __init__(self, t):
        self.t = float(t)

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += max(0.0, float(s))


PG = {"n": 0}


def fake_get_pages(url, headers=None, timeout=20.0, deadline=None, inline_wait=10.0, gate_host=None, single=False):
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    PG["n"] += 1
    b = int(q["before_timestamp"])
    return gt_rows(b, 10 if PG["n"] < 3 else int(q["limit"]))


ft = FT(time.time())
ft0 = ft.t
old_time, old_sleep, old_get = candles.time, candles.BG_SLEEP[0], candles._get
candles.time, candles.BG_SLEEP[0], candles._get = ft, ft.sleep, fake_get_pages
candles._BG["last"].clear()
candles._BG["stop"].clear()
candles.BG_PACE_S = 60.0
T0d = (int(ft.t) - 30 * 86400) // 300 * 300
try:
    with candles.chart_mode("bg"), candles.hard_deadline(ft.t + 300):
        r3 = candles.fetch_gt("base", DEX["pool"], DEX["token"], "5m", T0d, T0d + 6 * 3600)
finally:
    candles.time, candles.BG_SLEEP[0], candles._get = old_time, old_sleep, old_get
chk(r3.ok and r3.complete and PG["n"] == 3 and r3.why is None, "D3(MEDIUM) 미리 받기 GT 세 쪽 = 분당 1회 간격으로 하드 마감 안에서 끝까지(완결 · 영구 캐시)",
    (r3, PG["n"]))
chk(120 <= ft.t - ft0 < 300, "D3 쪽 사이 간격 60초씩 지킴(가짜 시계 120초 경과 · 하드 마감 300초 안)", ft.t - ft0)

T.finish()
