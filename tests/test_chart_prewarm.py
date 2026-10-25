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
DEX_CASES = {"get": None}


def gt_rows(b, n, s=300):
    return {"data": {"attributes": {"ohlcv_list": [[b - (i + 1) * s, 1.0, 1.1, 0.9, 1.05, 100.0] for i in range(n)]}}}


def fake_get(url, headers=None, timeout=20.0, deadline=None, inline_wait=10.0, gate_host=None, single=False):
    if DEX_CASES["get"] is not None:
        return DEX_CASES["get"](url, headers=headers, timeout=timeout, deadline=deadline, inline_wait=inline_wait, gate_host=gate_host, single=single)
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

def dex_pool_cases():
    TOK = "0x" + "ab" * 20
    P_NEW = "0x" + "11" * 20
    P_HIT = "0x" + "22" * 20
    P_HIT2 = "0x" + "33" * 20
    P_OTHER = "0x" + "44" * 20
    USDC = "0x" + "55" * 20
    WETH = "0x" + "66" * 20


    def pair(addr, liq, qsym, quote):
        return {"chainId": "base", "dexId": "aerodrome", "pairAddress": addr, "liquidity": {"usd": liq},
                "baseToken": {"address": TOK, "symbol": "TKJ"}, "quoteToken": {"address": quote, "symbol": qsym}}


    ALL = [pair(P_NEW, 1000000.0, "USDC", USDC), pair(P_HIT, 600000.0, "WETH", WETH), pair(P_OTHER, 400000.0, "WETH", WETH),
           pair(P_HIT2, 100000.0, "WETH", WETH)]
    CALLS = []
    GTP = {"mode": "ok", "body": {"data": []}}
    EMPTY = set()
    MODE429 = {"on": False}
    DSERR = {"on": False}
    NOW = int(time.time())
    T0 = (NOW - 100 * 86400) // 300 * 300
    T1 = T0 + 3 * 3600


    def gt_rows(pool, before, limit):
        if pool.lower() == P_NEW or pool.lower() in EMPTY:
            return {"data": {"attributes": {"ohlcv_list": []}}}
        rows = []
        t = (before // 300) * 300
        for _ in range(limit):
            rows.append([t, "1.0", "1.1", "0.9", "1.05", "100"])
            t -= 300
        return {"data": {"attributes": {"ohlcv_list": rows}}}


    def fake_get(url, headers=None, timeout=20.0, deadline=None, inline_wait=10.0, gate_host=None, single=False):
        u = urllib.parse.urlsplit(url)
        CALLS.append(url)
        if u.hostname == "api.dexscreener.com":
            if u.path.startswith("/tokens/v1/"):
                return [ALL[0]]
            if u.path.startswith("/token-pairs/v1/"):
                if DSERR["on"]:
                    import bf_engine
                    raise bf_engine.NetError("timeout", "timeout", host=u.hostname)
                return list(ALL)
            raise AssertionError("모르는 DexScreener 경로 " + u.path)
        if u.hostname == "api.geckoterminal.com":
            if "/tokens/" in u.path:
                if GTP["mode"] == "404":
                    import bf_engine
                    raise bf_engine.NetError("http 404", "http4xx", code=404, host=u.hostname)
                if GTP["mode"] == "429":
                    import bf_engine
                    raise bf_engine.NetError("http 429", "http429", code=429, host=u.hostname)
                return GTP["body"]
            if MODE429["on"]:
                import bf_engine
                raise bf_engine.NetError("http 429 Too Many Requests", "http429", code=429, host=u.hostname)
            pool = u.path.split("/pools/")[1].split("/")[0]
            q = dict(urllib.parse.parse_qsl(u.query))
            return gt_rows(pool, int(q["before_timestamp"]), int(q["limit"]))
        raise AssertionError("모르는 호스트 " + str(u.hostname))


    DEX_CASES["get"] = fake_get


    def reset_pools():
        for p9 in (candles._pools_path(),):
            try:
                os.remove(p9)
            except OSError:
                pass


    reset_pools()
    CALLS.clear()
    best, why, n = candles.find_pool("base", TOK, tx_addrs=[P_HIT.upper().replace("0X", "0x"), P_HIT2, "0x" + "99" * 20])
    chk(why is None and best and best["pool"].lower() == P_HIT and best["matched"] is True,
        "E1 체결 tx 가 건드린 풀을 고름(대표 1페어만 주는 tokens/v1 이 아니라 모든 페어)", (best, why))
    chk(n == 1 and len(CALLS) == 1 and "/token-pairs/v1/base/" in CALLS[0] and "/tokens/v1/" not in CALLS[0],
        "E1 풀 목록 = DexScreener token-pairs/v1 한 콜", CALLS)

    reset_pools()
    with open(candles._pools_path(), "w", encoding="utf-8") as f:
        json.dump({f"base:{TOK}": {"pairs": candles.parse_ds_pairs([ALL[0]], "base"), "until": NOW + 5 * 86400}}, f)
    CALLS.clear()
    best, why, n = candles.find_pool("base", TOK, tx_addrs=[P_HIT])
    chk(n == 1 and best and best["pool"].lower() == P_HIT and best["matched"],
        "E2 옛 풀 캐시(표식 없는 대표 1페어 · 기한 안) = 다시 받아 체결 풀", (best, n, CALLS))
    CALLS.clear()
    best, why, n = candles.find_pool("base", TOK, tx_addrs=[P_HIT])
    chk(n == 0 and not CALLS and best["pool"].lower() == P_HIT, "E2 새 표식 캐시 = 호출 0(7일 캐시 그대로)", (n, CALLS))
    pc = json.load(open(candles._pools_path(), encoding="utf-8"))
    chk(len(pc[f"base:{TOK}"]["pairs"]) == 4, "E2 캐시 = 모든 페어", pc)

    best, why, n = candles.find_pool("base", TOK, tx_addrs=())
    chk(best["pool"].lower() == P_NEW and best["matched"] is False, "E3 tx 주소 없음 = 주요 호가 자산 페어 중 유동성 최대(종전)", best)
    best, why, n = candles.find_pool("base", TOK, tx_addrs=["0x" + "99" * 20])
    chk(best["pool"].lower() == P_NEW and best["matched"] is False, "E3 안 겹침 = 유동성 최대(종전)", best)
    CALLS.clear()
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK, "tx_addrs": ["0x" + "99" * 20]}, "5m", T0, T1, now=NOW)
    gt = [u.split("/pools/")[1].split("/")[0] for u in CALLS if "geckoterminal" in u]
    chk(r.ok and sp["pool"].lower() == P_HIT and gt[:2] == [P_NEW, P_HIT] and r.calls == len(CALLS),
        "E3 첫 후보 풀(유동성 최대) 빈 응답 → 다음 후보 풀에서 봉(한 풀만 믿고 '없음'으로 끝내지 않음) · 호출 수 합산", (r, gt))

    CALLS.clear()
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK, "tx_addrs": [P_HIT2, P_HIT]}, "5m", T0 + 1200, T1 + 1200, now=NOW)
    gt = [u for u in CALLS if "geckoterminal" in u]
    chk(r.ok and len(r.candles) == 36 and sp["pool"].lower() == P_HIT and sp["poolMatched"] is True,
        "E4 체결 풀(둘 다 건드렸으면 유동성 큰 쪽)로 봉 36개", (r, sp.get("pool")))
    chk(gt and all(f"/pools/{P_HIT}/" in u.lower() for u in gt) and "tx_addrs" not in sp, "E4 GeckoTerminal 은 그 풀로 물음 · tx 주소는 밖으로 안 감", gt)

    TODAY = time.strftime("%Y-%m-%d", time.localtime(NOW))
    d_old = time.strftime("%Y-%m-%d", time.localtime(NOW - 30 * 86400))
    items = [{"date": d_old, "sym": s, "vk": ["dex"]} for s in ("AAA", "BBB", "CCC")]
    done = {f"{d_old}|AAA|buy": {"at": NOW - 86400, "r": "none"},
            f"{d_old}|BBB|buy": {"at": NOW - 86400, "r": "ok"},
            f"{d_old}|CCC|buy": {"at": NOW - 60, "r": "none", "pv": rd.PW_DONE_V}}
    keys = [f"{r9[0]}|{r9[1]}|{r9[2]}" for r9 in rd.prewarm_order(items, {}, TODAY, done)]
    chk(f"{d_old}|AAA|buy" in keys, "E5 고침 전 'none' 기록 = 한 번 다시 물음", keys)
    chk(f"{d_old}|BBB|buy" not in keys and f"{d_old}|CCC|buy" not in keys, "E5 'ok' 기록·고친 뒤 'none' 기록 = 그대로 건너뜀", keys)
    chk(f"{d_old}|AAA|sell" in keys, "E5 기록 없는 쪽은 종전 그대로 물음", keys)
    items2 = [{"date": d_old, "sym": "DDD", "vk": ["cex"]}]
    keys2 = [f"{r9[0]}|{r9[1]}|{r9[2]}" for r9 in rd.prewarm_order(items2, {}, TODAY, {f"{d_old}|DDD|buy": {"at": NOW - 86400, "r": "none"}})]
    chk(f"{d_old}|DDD|buy" not in keys2 and f"{d_old}|DDD|sell" in keys2, "E5 거래소만인 영수증의 옛 none 기록 = 그대로 건너뜀(DEX 만 다시)", keys2)


    def set_pairs(lst):
        ALL[:] = lst
        reset_pools()


    def mk(i, liq, created=None):
        p = pair("0x" + ("%02x" % (0x70 + i)) * 20, liq, "WETH", WETH)
        if created is not None:
            p["pairCreatedAt"] = created * 1000
        return p


    set_pairs([mk(1, 9e5, T1 + 86400), mk(2, 8e5, T1 + 3600)])
    CALLS.clear()
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK, "tx_addrs": []}, "5m", T0, T1, now=NOW)
    chk(not r.ok and r.why == "no_data" and r.sure is True and not [u for u in CALLS if "geckoterminal" in u] and "생성" in (r.note or ""),
        "E6 모든 풀이 구간 뒤 생성 = GeckoTerminal 호출 0 · 확실한 없음", (r, r.note, CALLS))
    set_pairs([mk(i, 9e5 - i * 1e4) for i in range(3)])
    EMPTY.update(p["pairAddress"].lower() for p in ALL)
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK}, "5m", T0 + 2400, T1 + 2400, now=NOW)
    chk(not r.ok and r.why == "no_data" and r.sure is True and "3개 모두" in (r.note or ""), "E6 후보 풀 3개 모두 빈 응답 = 확실한 없음", (r, r.note))
    set_pairs([mk(i, 9e5 - i * 1e4) for i in range(6)])
    EMPTY.update(p["pairAddress"].lower() for p in ALL)
    CALLS.clear()
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK}, "5m", T0 + 3600, T1 + 3600, now=NOW)
    n_gt = len([u for u in CALLS if "geckoterminal" in u])
    chk(not r.ok and r.why == "no_data" and r.sure is False and n_gt == candles.POOL_TRY_MAX and "다음에" in (r.note or ""),
        "E6 후보 6개 중 상한(POOL_TRY_MAX)만 봄 = 불확실(임시 없음)", (r, r.note, n_gt))
    CALLS.clear()
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK}, "5m", T0 + 3600, T1 + 3600, now=NOW + 3 * 86400)
    gt9 = [u.split("/pools/")[1].split("/")[0] for u in CALLS if "geckoterminal" in u]
    chk(r.why == "no_data" and r.sure is True and len(gt9) == 2 and set(gt9) == {p["pairAddress"].lower() for p in ALL[4:6]},
        "E6 3일 뒤 다시 물음 = 본 풀(빈 결과 기록)은 호출 없이 넘기고 나머지 2개만 → 다 봄 = 확실한 없음", (r, r.note, gt9))
    set_pairs([mk(i, 9e5 - i * 1e4) for i in range(9)])
    EMPTY.update(p["pairAddress"].lower() for p in ALL[:8])
    EMPTY.discard(ALL[8]["pairAddress"].lower())
    got_at, soft_rec = None, None
    for k in range(rd.PW_SOFT_MAX + 1):
        r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK}, "5m", T0 + 4200, T1 + 4200, now=NOW + k * 7 * 86400)
        if r.ok:
            got_at = (k, sp["pool"].lower())
            break
        soft_rec = rd.pw_done_rec({"ok": True, "chart": {"ok": False, "tried": [{"label": "DEX", "why": r.why, "sure": r.sure}]}}, soft_rec, NOW + k * 7 * 86400)
    chk(got_at == (2, ALL[8]["pairAddress"].lower()) and soft_rec and not soft_rec.get("gaveup"),
        "E6 다시 묻기(7일 간격) 셋째 = 9번째 풀에서 봉 · 그 전에 gaveup 없음(앞 풀 기록 유지)", (got_at, soft_rec))
    chk(candles.DEX_EMPTY_TTL_S >= 2 * rd.PW_SOFT_TTL_S * (rd.PW_SOFT_MAX + 1)
        and candles.POOL_TRY_MAX * (rd.PW_SOFT_MAX + 1) >= 30,
        "E6 상수 관계: 본 풀 기록 기한 ≥ 다시 묻기 전체 × 2 · 다시 묻기 횟수 × 새 풀 상한 ≥ 후보 상한 30",
        (candles.DEX_EMPTY_TTL_S, rd.PW_SOFT_TTL_S, rd.PW_SOFT_MAX, candles.POOL_TRY_MAX))
    plan = [({"venue": "dex", "chain": "base", "token": TOK}, None, "primary")]
    res = candles.best_chart(plan, "5m", T0 + 4800, T1 + 4800, "USD", by_date=False)
    dx = [t9 for t9 in res["tried"] if t9.get("label", "").startswith("DEX")]
    chk(not res["ok"] and dx and dx[0].get("sure") is False, "E6 시도 목록에 DEX 불확실 표시(sure=False — 미리 받기 판정 재료)", res["tried"])
    MODE429["on"] = True
    set_pairs([mk(i, 9e5 - i * 1e4) for i in range(3)])
    CALLS.clear()
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK}, "5m", T0 + 6000, T1 + 6000, now=NOW)
    chk(not r.ok and r.why == "net" and not r.sure and len([u for u in CALLS if "geckoterminal" in u]) == 1,
        "E6 429 = 일시 실패(다음 풀로 넘어가 '없음'으로 굳히지 않음 · 확실 아님)", (r, CALLS))
    MODE429["on"] = False

    resp_soft = {"ok": True, "chart": {"ok": False, "tried": [{"label": "DEX Base", "why": "no_data", "sure": False}]}}
    resp_sure = {"ok": True, "chart": {"ok": False, "tried": [{"label": "DEX Base", "why": "no_data", "sure": True}]}}
    resp_buy_soft = {"ok": True, "chart": {"ok": True, "tried": []}, "segs": [{"ok": False, "tried": [{"label": "DEX Base", "why": "no_data", "sure": False}]}]}
    resp_429 = {"ok": True, "chart": {"ok": False, "tried": [{"label": "DEX Base", "why": "net"}]}}
    r1 = rd.pw_done_rec(resp_soft, None, NOW)
    chk(rd._pw_judge(resp_soft, "sell") == "done" and r1.get("exp") == NOW + rd.PW_SOFT_TTL_S and r1["soft"] == 1 and r1["r"] == "none",
        "E7 불확실한 DEX 없음 = 임시 기록(기한 exp)", r1)
    r2 = rd.pw_done_rec(resp_buy_soft, None, NOW)
    chk(r2.get("exp") and r2["soft"] == 1, "E7 매수 묶음(segs) 안의 불확실 DEX 없음도 임시", r2)
    rs = rd.pw_done_rec(resp_sure, None, NOW)
    chk("exp" not in rs and "gaveup" not in rs and rs["pv"] == rd.PW_DONE_V, "E7 확실한 없음 = 영구 기록(종전)", rs)
    chk(rd._pw_judge(resp_429, "sell") == "retry", "E7 429·망(일시) = retry(다 받음 기록 안 함 — 종전)")
    k9 = f"{d_old}|EEE|sell"
    it9 = [{"date": d_old, "sym": "EEE", "vk": ["dex"]}]
    order_keys = lambda dn, now: [f"{x[0]}|{x[1]}|{x[2]}" for x in rd.prewarm_order(it9, {}, TODAY, dn, now=now)]   # noqa: E731
    chk(k9 not in order_keys({k9: r1}, NOW + 60), "E7 임시 기록 = 기한 전엔 건너뜀", r1)
    chk(k9 in order_keys({k9: r1}, NOW + rd.PW_SOFT_TTL_S + 1), "E7 임시 기록 = 기한 뒤 다시 물음", r1)
    prev = r1
    for _i in range(rd.PW_SOFT_MAX):
        prev = rd.pw_done_rec(resp_soft, prev, NOW)
    chk(prev.get("gaveup") and "exp" not in prev and k9 not in order_keys({k9: prev}, NOW + 10 * rd.PW_SOFT_TTL_S),
        "E7 PW_SOFT_MAX 번 넘게 그대로 = gaveup(더 안 물음 · 상태 패널 주의로 남김)", prev)

    import chk_collect  # noqa: E402
    import health  # noqa: E402
    pwp = paths.state("candles", "prewarm.json")
    try:
        os.remove(pwp)
    except OSError:
        pass
    chk(chk_collect.collect_chart_dex(NOW) is None, "E8 미리 받기 기록 없음(꺼짐) = 관측 없음")
    ADDS = []


    def fadd(cid, unit, title, level, detail="", action="", **kw):
        ADDS.append((cid, level, title, detail))


    health._chart_dex_item(fadd, {"chart_dex": None}, ["tj-review"], set())
    chk(not ADDS, "E8 관측 없음 = 항목 없음", ADDS)
    os.makedirs(os.path.dirname(pwp), exist_ok=True)
    with open(pwp, "w", encoding="utf-8") as f:
        json.dump({"day": TODAY, "done": {"a|X|sell": {"at": NOW, "r": "ok", "pv": 2}, "b|Y|buy": r1, "c|Z|sell": prev}}, f)
    cd = chk_collect.collect_chart_dex(NOW)
    chk(cd == {"soft": 1, "gaveup": 1, "oldest": float(NOW)}, "E8 임시 1 · 멈춤 1 집계", cd)
    health._chart_dex_item(fadd, {"chart_dex": cd}, ["tj-review"], set())
    chk(ADDS and ADDS[-1][0] == "chart:dex" and ADDS[-1][1] == "warn" and "2건" in ADDS[-1][2], "E8 멈춘 것 있음 = 주의", ADDS)
    health._chart_dex_item(fadd, {"chart_dex": {"soft": 2, "gaveup": 0}}, ["tj-review"], set())
    chk(ADDS[-1][1] == "ok", "E8 임시 몇 건(문턱 아래)·멈춤 0 = ok", ADDS[-1])
    health._chart_dex_item(fadd, {"chart_dex": {"soft": health.CHART_DEX_SOFT_WARN, "gaveup": 0}}, ["tj-review"], set())
    chk(ADDS[-1][1] == "warn", "E8 임시가 문턱만큼 쌓임 = 주의", ADDS[-1])
    with open(pwp, "w", encoding="utf-8") as f:
        f.write("{망가짐")
    cd = chk_collect.collect_chart_dex(NOW)
    health._chart_dex_item(fadd, {"chart_dex": cd}, ["tj-review"], set())
    chk(cd.get("error") and ADDS[-1][1] is None, "E8 기록 손상 = 판단 보류", (cd, ADDS[-1]))
    for bad_doc in ([], {"done": []}, {"done": {"k": 1}}, {"done": {"k": {"at": "x", "r": "none", "exp": 5}}},
                    {"done": {"k": {"at": 1, "exp": []}}}, {"done": {"k": {"at": 1, "exp": "NaN"}}}, {"done": {"k": {"at": 1, "gaveup": "yes"}}}):
        with open(pwp, "w", encoding="utf-8") as f:
            json.dump(bad_doc, f)
        cd = chk_collect.collect_chart_dex(NOW)
        chk(isinstance(cd, dict) and cd.get("error"), "E8 구조 손상(%s) = 판단 보류(0건 초록 아님 · 예외 없음)" % json.dumps(bad_doc)[:30], cd)

    P_GT = "0x" + "88" * 20
    set_pairs([])
    GTP.update(mode="ok", body={"data": [{"id": "base_" + P_GT, "attributes": {"address": P_GT, "name": "TKJ / WETH 0.3%", "reserve_in_usd": "5000",
                                                                                "pool_created_at": "2020-01-01T00:00:00Z"},
                                          "relationships": {"dex": {"data": {"id": "uniswap_v3"}}}}]})
    CALLS.clear()
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK, "tx_addrs": [P_GT]}, "5m", T0 + 7200, T1 + 7200, now=NOW)
    chk(r.ok and sp["pool"].lower() == P_GT and sp.get("poolMatched") is True and sp.get("dex") == "uniswap_v3"
        and any("/tokens/" in u and "geckoterminal" in u for u in CALLS), "E9 DexScreener 페어 0 → GeckoTerminal 풀 목록 → 그 풀 봉", (r, sp, CALLS))
    reset_pools()
    GTP.update(mode="429")
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK}, "5m", T0 + 7200, T1 + 7200, now=NOW + 1)
    pc = json.load(open(candles._pools_path(), encoding="utf-8")) if os.path.exists(candles._pools_path()) else {}
    chk(not r.ok and r.why == "net" and f"base:{TOK}" not in pc, "E9 풀 목록 429 = 일시 실패(풀 없음으로 캐시 안 함)", (r, pc))
    GTP.update(mode="404")
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK}, "5m", T0 + 7200, T1 + 7200, now=NOW + 2)
    chk(not r.ok and r.why == "no_market", "E9 둘 다 풀 없음(404) = 풀 없음(6시간 부정 캐시 — 종전)", r)


    MODE429["on"] = False
    GTP.update(mode="ok", body={"data": []})
    set_pairs([pair(P_HIT, 600000.0, "WETH", WETH)])
    EMPTY.clear()
    old0 = (NOW - 200 * 86400) // 300 * 300
    old1 = old0 + 3 * 3600
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK}, "5m", old0, old1, now=NOW - 30 * 86400)
    chk(r.ok and not r.cached, "E10 준비: 그때(구간 170일 전) 받아 둔 DEX 봉(디스크)", r)
    CALLS.clear()
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK, "tx_addrs": [P_HIT]}, "5m", old0, old1, now=NOW)
    chk(r.ok and r.cached and len(r.candles) == 36 and sp.get("pool", "").lower() == P_HIT and not CALLS,
        "E10 200일 지난 영수증 + 받아 둔 봉 = 차트 나옴(외부 호출 0 · 풀 몰라도 색인으로)", (r, sp.get("pool"), CALLS))
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK, "pool": P_HIT}, "5m", old0, old1, now=NOW)
    chk(r.ok and r.cached and not CALLS, "E10 풀 지정(빈 시간 채우기 꼴)도 받아 둔 봉", r)
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK}, "5m", old0 + 7200, old1 + 7200, now=NOW)
    chk(not r.ok and r.why == "too_old" and r.calls == 0 and not CALLS, "E10 받아 둔 봉 없음 = too_old(외부 호출 0 — 종전)", (r, CALLS))
    plan_old = [({"venue": "dex", "chain": "base", "token": TOK}, None, "primary")]
    res = candles.best_chart(plan_old, "5m", old0, old1, "USD")
    chk(res["ok"] and res["src"]["venue"] == "dex" and res["calls"] == 0, "E10 차트 사슬(날짜 맞춤 포함)도 받아 둔 DEX 봉으로 그림", res.get("tried"))
    cg_t0 = (NOW - 400 * 86400) // 3600 * 3600
    cg_t1 = cg_t0 + 6 * 3600
    pts = [[cg_t0 + i * 3600 + 60, 2.0 + i * 0.01, 2.0 + i * 0.01, 2.0 + i * 0.01, 2.0 + i * 0.01, 0.0] for i in range(6)]
    cpk = candles._cpath("cg", "base", TOK, cg_t0 // 86400 * 86400, -(-cg_t1 // 86400) * 86400)
    candles._cache_store(cpk, ["cg", "base", TOK, 0, 0], pts, None, None, True, NOW - 300 * 86400)
    r = candles.fetch_cg_hourly("base", TOK, cg_t0, cg_t1, now=NOW)
    chk(r.ok and len(r.candles) == 6 and r.cached and not CALLS, "E10 코인게코 시세 점도 365일 밖 + 받아 둔 점 = 그대로(호출 0)", r)
    r = candles.fetch_cg_hourly("base", TOK, cg_t0 - 86400 * 3, cg_t1 - 86400 * 3, now=NOW)
    chk(not r.ok and r.why == "too_old" and not CALLS, "E10 코인게코 받아 둔 점 없음 = too_old(종전)", r)
    plan_cg = [({"venue": "dex", "chain": "base", "token": TOK}, None, "primary")]
    res = candles.best_chart(plan_cg, "5m", cg_t0, cg_t1, "USD")
    chk(res["ok"] and res["src"]["venue"] == "coingecko" and res["calls"] == 0 and not CALLS,
        "E10 차트 사슬: DEX 180일 밖·코인게코 365일 밖이어도 받아 둔 코인게코 점으로 그림(사슬에서 빼지 않음)", res.get("tried"))
    candles.neg_put("gt:base:" + P_HIT.lower(), "no_market", ttl=86400, now=NOW)
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK, "pool": P_HIT}, "5m", old0, old1, now=NOW)
    chk(r.ok and r.cached and not CALLS, "E10 풀 없음(404) 기록이 있어도 받아 둔 그 풀 봉은 씀(새 호출만 막음)", r)
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK, "pool": P_HIT}, "5m", T0 + 9000, T1 + 9000, now=NOW)
    chk(not r.ok and r.why == "no_market" and not CALLS, "E10 받아 둔 봉 없는 구간 = 404 기록대로 호출 없이 풀 없음(종전)", r)


    def mk2(i, liq, created=None, q="WETH", qa=WETH):
        p9 = pair("0x" + "c0" * 19 + "%02x" % i, liq, q, qa)
        if created is not None:
            p9["pairCreatedAt"] = created * 1000
        return p9
    MODE429["on"] = False
    GTP.update(mode="ok", body={"data": []})
    EMPTY.clear()
    w0, w1 = T0 + 12000, T1 + 12000
    TXP = ("0x" + "c0" * 19 + "%02x" % 30)
    later = w1 + 86400
    set_pairs([mk2(i, 9e5 - i * 1e4, later) for i in range(30)] + [mk2(30, 1000.0, w0 - 86400)])
    CALLS.clear()
    cands, why, n = candles.pool_candidates("base", TOK, [TXP], now=NOW)
    chk(cands and cands[0]["pool"].lower() == TXP and cands[0]["matched"] is True and len(cands) == getattr(candles, "POOL_CAND_MAX", 30),
        "E11 후보 31개 · 체결 풀이 유동성 31번째 = 상한 자르기 전에 체결 풀을 앞에 보존", (len(cands or []), (cands or [{}])[0].get("pool")))
    chk(all(c9.get("poolsCut") for c9 in cands), "E11 차례 상한에 잘림 = 후보마다 poolsCut(목록 다 안 옴)", None)
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK, "tx_addrs": [TXP]}, "5m", w0, w1, now=NOW)
    chk(r.ok and sp["pool"].lower() == TXP and sp.get("poolMatched") is True, "E11 그 체결 풀 봉으로 차트(종전 = 잘려 나가 '봉 없음' 확실)", (r, sp.get("pool")))
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK}, "5m", w0 + 600, w1 + 600, now=NOW)
    chk(not r.ok and r.why == "no_data" and r.sure is False and "다음에" in (r.note or ""),
        "E11 tx 없음 · 보이는 30개 모두 구간 뒤 생성 · 목록 잘림 = 불확실(임시 없음 — 잘린 31번째가 옛 풀일 수 있음)", (r, r.note))
    set_pairs([mk2(i, 9e5 - i * 1e4, later) for i in range(30)])
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK}, "5m", w0 + 1200, w1 + 1200, now=NOW)
    chk(not r.ok and r.why == "no_data" and r.sure is True, "E11 대조: 목록 30개(다 옴) · 모두 구간 뒤 생성 = 확실한 없음(종전)", (r, r.note))
    set_pairs([mk2(40 + i, 9e5 - i * 1e4) for i in range(3)])
    EMPTY.update(p9["pairAddress"].lower() for p9 in ALL)
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK, "tx_addrs": ["0x" + "9e" * 20]}, "5m", w0 + 1800, w1 + 1800, now=NOW)
    chk(not r.ok and r.why == "no_data" and r.sure is False and "체결 풀" in (r.note or ""),
        "E11 체결 tx 풀을 목록에서 못 찾음 · 후보 3개 모두 빈 응답 = 불확실(영구 none 아님)", (r, r.note))
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK}, "5m", w0 + 1800, w1 + 1800, now=NOW)
    chk(not r.ok and r.sure is True, "E11 대조: tx 없음 · 같은 3개 모두 빈 응답 = 확실(종전)", (r, r.note))
    def gt_body(k):
        return {"data": [{"id": "base_x%d" % i, "attributes": {"address": "0x" + "c1" * 19 + "%02x" % i, "name": "TKJ / WETH",
                                                               "reserve_in_usd": str(9000 - i), "pool_created_at": "2099-01-01T00:00:00Z"}}
                         for i in range(k)]}
    set_pairs([])
    GTP.update(mode="ok", body=gt_body(getattr(candles, "GT_PAGE_ROWS", 20)))
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK}, "5m", w0 + 2400, w1 + 2400, now=NOW)
    pc = json.load(open(candles._pools_path(), encoding="utf-8"))
    chk(not r.ok and r.why == "no_data" and r.sure is False and pc[f"base:{TOK}"].get("cut") is True,
        "E11 GeckoTerminal 첫 쪽 20개 꽉 참(page=1 만) · 모두 구간 뒤 = 불확실 · 캐시에 cut 표식", (r, r.note))
    set_pairs([])
    GTP.update(mode="ok", body=gt_body(3))
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK}, "5m", w0 + 2400, w1 + 2400, now=NOW)
    chk(not r.ok and r.sure is True, "E11 대조: GeckoTerminal 3개(다 옴) · 모두 구간 뒤 = 확실(종전)", (r, r.note))
    GTP.update(mode="ok", body={"data": []})
    set_pairs([mk2(i, 9e5 - i * 1e4) for i in range(31)])
    with open(candles._pools_path(), "w", encoding="utf-8") as f:
        json.dump({f"base:{TOK}": {"pairs": candles.parse_ds_pairs(ALL[:30], "base"), "until": NOW + 5 * 86400, "src": candles.POOL_SRC}}, f)
    CALLS.clear()
    cands, why, n = candles.pool_candidates("base", TOK, [TXP], now=NOW)
    chk(n == 1 and cands[0]["pool"].lower() == TXP and cands[0]["matched"], "E11 옛 30개 캐시(cut 표식 없음) = 다시 받아 체결 풀 찾음", (n, CALLS))
    CALLS.clear()
    cands, why, n = candles.pool_candidates("base", TOK, [TXP], now=NOW)
    chk(n == 0 and not CALLS, "E11 새 캐시(cut 표식 있음) = 호출 0(7일 캐시 그대로)", (n, CALLS))
    set_pairs([])
    GTP.update(mode="ok", body=gt_body(getattr(candles, "GT_PAGE_ROWS", 20)))
    with open(candles._pools_path(), "w", encoding="utf-8") as f:
        json.dump({f"base:{TOK}": {"pairs": candles.parse_gt_pools(gt_body(20)), "until": NOW + 5 * 86400, "src": candles.POOL_SRC}}, f)
    CALLS.clear()
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK}, "5m", w0 + 3000, w1 + 3000, now=NOW)
    chk(CALLS and r.why == "no_data" and r.sure is False, "E11 옛 GeckoTerminal 20개 캐시(cut 표식 없음) = 다시 받음 → 잘림 표식 · 불확실", (len(CALLS), r.sure))
    GTP.update(mode="ok", body={"data": []})
    done_v2 = {f"{d_old}|AAA|buy": {"at": NOW - 86400, "r": "none", "pv": 2}}
    keys_v2 = [f"{r9[0]}|{r9[1]}|{r9[2]}" for r9 in rd.prewarm_order(items, {}, TODAY, done_v2)]
    chk(f"{d_old}|AAA|buy" in keys_v2, "E11 고침 전 판(pv 2)의 DEX none 기록 = 한 번 다시 물음(잘림·체결 풀 미발견으로 굳힌 영구 none 이행)", keys_v2)
    done_ok = {f"{d_old}|AAA|buy": {"at": NOW - 86400, "r": "ok", "pv": 2}, f"{d_old}|BBB|buy": {"at": NOW - 86400, "r": "ok"},
               f"{d_old}|CCC|buy": {"at": NOW - 86400, "r": "ok", "pv": rd.PW_DONE_V}, f"{d_old}|AAA|sell": {"at": NOW - 86400, "r": "ok", "pv": 2}}
    keys_ok = [f"{r9[0]}|{r9[1]}|{r9[2]}" for r9 in rd.prewarm_order(items, {}, TODAY, done_ok)]
    chk(f"{d_old}|AAA|buy" in keys_ok and f"{d_old}|BBB|buy" not in keys_ok and f"{d_old}|CCC|buy" not in keys_ok and f"{d_old}|AAA|sell" not in keys_ok,
        "E11 판 2 DEX 매수 ok(구간 일부가 잘린 목록으로 확실 처리됐을 수 있음) = 한 번 다시 · 판 없는 ok·지금 판 ok·매도 ok = 그대로 건너뜀", keys_ok)
    items_cx = [{"date": d_old, "sym": "FFF", "vk": ["cex"]}]
    done_cx = {f"{d_old}|FFF|buy": {"at": NOW - 86400, "r": "ok", "pv": 2}, f"{d_old}|FFF|sell": {"at": NOW - 86400, "r": "ok", "pv": 2}}
    keys_cx = [f"{r9[0]}|{r9[1]}|{r9[2]}" for r9 in rd.prewarm_order(items_cx, {}, TODAY, done_cx)]
    done_cx3 = {k9: dict(v9, pv=rd.PW_DONE_V) for k9, v9 in done_cx.items()}
    keys_cx3 = [f"{r9[0]}|{r9[1]}|{r9[2]}" for r9 in rd.prewarm_order(items_cx, {}, TODAY, done_cx3)]
    chk(keys_cx == [f"{d_old}|FFF|buy"] and not keys_cx3,
        "E11 매도 당일 거래소(vk cex)여도 판 2 매수 ok = 한 번 다시(지난날 DEX 매수 구간) · 다시 쓴 판 3 기록 = 건너뜀(반복 없음)", (keys_cx, keys_cx3))
    big = [mk2(i % 256, 9e5 - i) for i in range(getattr(candles, "POOL_KEEP_MAX", 200) + 5)]
    for i9, p9 in enumerate(big):
        p9["pairAddress"] = "0x%040x" % (0xc2 << 150 | i9)
    set_pairs(big)
    cands, why, n = candles.pool_candidates("base", TOK, [], now=NOW)
    pc = json.load(open(candles._pools_path(), encoding="utf-8"))
    chk(len(pc[f"base:{TOK}"]["pairs"]) == getattr(candles, "POOL_KEEP_MAX", 200) and pc[f"base:{TOK}"]["cut"] is True and cands[0].get("poolsCut"),
        "E11 풀 목록 캐시 상한(POOL_KEEP_MAX) 넘음 = 잘라 저장 · cut 표식", len(pc[f"base:{TOK}"]["pairs"]))

    kmax = getattr(candles, "POOL_KEEP_MAX", 200)
    w0, w1 = T0 + 15000, T1 + 15000
    later = w1 + 86400

    def tail(n9):
        out9 = [mk2(0, 9e5 - i, later) for i in range(n9)]
        for i9, p9 in enumerate(out9):
            p9["pairAddress"] = "0x%040x" % (0xc3 << 150 | i9)
        return out9
    big = tail(kmax + 3)
    TA, TB = big[kmax]["pairAddress"], big[kmax + 1]["pairAddress"]
    big[kmax]["pairCreatedAt"] = (w0 - 86400) * 1000
    big[kmax + 1]["pairCreatedAt"] = (w0 - 86400) * 1000
    set_pairs(big)
    CALLS.clear()
    cands, why, n = candles.pool_candidates("base", TOK, [TA], now=NOW)
    pc = json.load(open(candles._pools_path(), encoding="utf-8"))
    kept = {p9["pool"] for p9 in pc[f"base:{TOK}"]["pairs"]}
    chk(cands and cands[0]["pool"] == TA and cands[0]["matched"] is True and TA in kept and len(kept) == kmax and pc[f"base:{TOK}"]["cut"] is True,
        "E12 후보 203개 · 체결 풀 = 유동성 201번째 = 캐시 상한(200) 전에 보존(종전 = 잘려 '체결 풀 못 찾음')", (len(cands or []), TA in kept, len(kept)))
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK, "tx_addrs": [TA]}, "5m", w0, w1, now=NOW + 86400)
    chk(r.ok and sp["pool"] == TA and sp.get("poolMatched") is True, "E12 다음 날 다시 물어도(캐시) 그 체결 풀 봉으로 차트", (r.why, sp.get("pool")))
    CALLS.clear()
    cands, why, n = candles.pool_candidates("base", TOK, [TB], now=NOW + 3600)
    chk(n == 0 and not any(c9["matched"] for c9 in cands) and cands[0].get("poolsCut"),
        "E12 다른 체결 풀(잘린 꼬리) · 잘린 캐시가 갓 받은 것(6시간 안) = 다시 안 받음(호출 0 · 잘림 표식 = 확실한 없음 아님)", (n, len(CALLS)))
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK, "tx_addrs": [TB]}, "5m", w0 + 300, w1 + 300, now=NOW + 3600)
    chk(not r.ok and r.sure is False, "E12 그동안 = 임시 없음(sure 아님 · 미리 받기가 기한 두고 다시)", (r.why, r.sure, r.note))
    DSERR["on"] = True
    CALLS.clear()
    cands, why, n = candles.pool_candidates("base", TOK, [TB], now=NOW + candles.NEG_TTL_S + 1)
    chk(cands is None and len(CALLS) == 1, "E12 묵은 잘린 캐시 다시 받기 · 망 오류 = 그 사유(1요청)", (why, len(CALLS)))
    CALLS.clear()
    cands, why, n = candles.pool_candidates("base", TOK, [TB], now=NOW + candles.NEG_TTL_S + 60)
    chk(n == 0 and not CALLS and cands and not any(c9["matched"] for c9 in cands),
        "E12 다시 받기 실패 직후 다시 물음 = 시도 시각부터 6시간 안 다시 안 받음(잘린 캐시 그대로 · 요청 반복 없음)", (n, len(CALLS)))
    DSERR["on"] = False
    CALLS.clear()
    cands, why, n = candles.pool_candidates("base", TOK, [TB], now=NOW + 2 * candles.NEG_TTL_S + 2)
    pc = json.load(open(candles._pools_path(), encoding="utf-8"))
    chk(n == 1 and cands[0]["pool"] == TB and cands[0]["matched"] is True and TB in {p9["pool"] for p9 in pc[f"base:{TOK}"]["pairs"]},
        "E12 잘린 캐시가 6시간 지남 + 체결 풀이 그 안에 없음 = 다시 받아 그 체결 풀 보존(다음 재시도가 같은 상한에 막히지 않음)", (n, len(CALLS)))
    CALLS.clear()
    cands, why, n = candles.pool_candidates("base", TOK, [], now=NOW + 2 * candles.NEG_TTL_S + 3)
    chk(n == 0 and not CALLS, "E12 대조: 체결 tx 없는 물음 = 잘린 캐시 그대로(호출 0)", (n, CALLS))
    set_pairs([mk2(i, 9e5 - i * 1e4, later) for i in range(3)] + [{"chainId": "base", "liquidity": {"usd": 5}}, None])
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK}, "5m", w0 + 600, w1 + 600, now=NOW)
    pc = json.load(open(candles._pools_path(), encoding="utf-8"))
    chk(not r.ok and r.why == "no_data" and r.sure is False and pc[f"base:{TOK}"].get("cut") is True,
        "E12 DexScreener 5행 중 2행 해석 못 함 · 보이는 3개 모두 구간 뒤 = 불확실(잘림 표식)", (r.sure, r.note))
    set_pairs([None, {"chainId": "base", "liquidity": {"usd": 5}}])
    cands, why, n = candles.pool_candidates("base", TOK, [], now=NOW)
    chk(cands is None and why == "bad" and not os.path.exists(candles._pools_path()),
        "E12 DexScreener 행이 전부 해석 못 함 = 형식 이상(why bad · '풀 없음' 캐시 안 함 · 다음에 다시)", (why, n))
    set_pairs([mk2(i, 9e5 - i * 1e4, later) for i in range(3)] + [dict(mk2(9, 5.0, later), chainId="solana")])
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK}, "5m", w0 + 900, w1 + 900, now=NOW)
    chk(not r.ok and r.sure is True, "E12 대조: 다른 체인 행(정상 행 · 뺌)만 섞임 = 확실(종전)", (r.sure, r.note))
    def gt_rows9(k, broken):
        rows9 = [{"id": "base_y%d" % i, "attributes": {"address": "0x" + "c4" * 19 + "%02x" % i, "name": "TKJ / WETH",
                                                     "reserve_in_usd": str(9000 - i), "pool_created_at": "2099-01-01T00:00:00Z"}} for i in range(k)]
        for j in range(broken):
            rows9[-1 - j] = {}
        return {"data": rows9}
    for k9, b9, lb in ((getattr(candles, "GT_PAGE_ROWS", 20), 1, "20행 중 1행 깨짐(19개)"), (5, 1, "5행 중 1행 깨짐")):
        set_pairs([])
        GTP.update(mode="ok", body=gt_rows9(k9, b9))
        r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK}, "5m", w0 + 1200, w1 + 1200, now=NOW)
        chk(not r.ok and r.why == "no_data" and r.sure is False, f"E12 GeckoTerminal {lb} · 모두 구간 뒤 = 불확실(종전 = 확실한 없음)", (r.sure, r.note))
    set_pairs([])
    GTP.update(mode="ok", body=gt_rows9(5, 0))
    r, sp = candles.fetch_spec({"venue": "dex", "chain": "base", "token": TOK}, "5m", w0 + 1200, w1 + 1200, now=NOW)
    chk(not r.ok and r.sure is True, "E12 대조: GeckoTerminal 5행 모두 정상 · 모두 구간 뒤 = 확실(종전)", (r.sure, r.note))
    GTP.update(mode="ok", body={"data": []})
    EMPTY.clear()


dex_pool_cases()
DEX_CASES["get"] = None

T.finish()
