#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import http.client  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import stat  # noqa: E402
import threading  # noqa: E402
from datetime import datetime  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

with open(os.path.join(T.ROOT, "config.example.json"), encoding="utf-8") as f:
    CFG = json.load(f)
CFG["wallets"], CFG["exchange_addresses"] = [], []
CFG["web"] = {"port": 8023, "bind": "loopback"}
CFG.setdefault("balance_check", {})["enabled"] = False
with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump(CFG, f, ensure_ascii=False)

import paths, statefile  # noqa: E402
import login_auth as LA  # noqa: E402
import login_limits as LL  # noqa: E402
import onboarding  # noqa: E402
import review_daily as rd  # noqa: E402
import review_progress as rprog  # noqa: E402
import settings_store as ss  # noqa: E402
import web  # noqa: E402

chk = T.chk
assert T.TMP in paths.STATE_DIR
REQ = paths.state("review_fill_request.json")
PREFS = {}


class FB:
    lock = threading.Lock()
    cache = None

    def __init__(self, ws="2026-05-15"):
        self.ws, self.mp = ws, 0

    def prefs(self):
        return dict(PREFS)

    def _backfill_since_view(self):
        if self.ws is None:
            raise RuntimeError("창 시작 못 읽음")
        return {"windowStart": self.ws}

    def mpatch(self, kinds):
        self.mp += 1
        return True


def rm(p):
    try:
        os.remove(p)
    except FileNotFoundError:
        pass


print("[W] POST /api/review/fill")
LA.init(CFG)
LL.LIM = LL.Limiter()
LA.set_password("Synthetic-Horse-7731", iters=200_000)
web.BUILDER = FB()
SRV = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
PORT = SRV.server_address[1]
threading.Thread(target=SRV.serve_forever, daemon=True, name="t-revfill").start()
ORIGIN, HOST = f"http://127.0.0.1:{PORT}", f"127.0.0.1:{PORT}"


def post(body=None, csrf=True, origin=True):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=60)
    h = {"Host": HOST, "Content-Type": "application/json"}
    if origin:
        h["Origin"] = ORIGIN
    if csrf:
        h["X-TJ-CSRF"] = ss.csrf_token()
    c.request("POST", "/api/review/fill", body=json.dumps(body or {}).encode(), headers=h)
    r = c.getresponse()
    raw = r.read()
    c.close()
    try:
        return r.status, json.loads(raw.decode() or "null")
    except ValueError:
        return r.status, None


s0, _ = post()
chk(s0 == 401 and not os.path.exists(REQ), "W1 로그인 켜짐 · 세션 없음 = 401 · 요청 파일 없음", s0)
LA.S = LA.Settings({"enabled": False})
onboarding.DEMO = True
s1, _ = post()
onboarding.DEMO = False
chk(s1 == 403 and not os.path.exists(REQ), "W2 데모 = 403 · 파일 없음", s1)
s2, _ = post(csrf=False)
s3, _ = post(origin=False)
chk(s2 == 403 and s3 == 403 and not os.path.exists(REQ), "W3 CSRF 없음·출처 없음 = 403 · 파일 없음", (s2, s3))
PREFS["review_pause"] = {"on": True, "at": 1}
s4, j4 = post()
PREFS.pop("review_pause")
chk(s4 == 409 and not os.path.exists(REQ) and "멈춤" in str((j4 or {}).get("error")), "W4 자동 생성 멈춤 중 = 409 · 파일 없음", (s4, j4))
statefile.atomic_write_json(paths.state("review_catchup_manual.lock"), {"pid": os.getpid(), "ts": int(rd.time.time())})
s5, j5 = post()
rm(paths.state("review_catchup_manual.lock"))
chk(s5 == 409 and not os.path.exists(REQ), "W5 수동 실행(잠금 살아 있음) 중 = 409 · 파일 없음", (s5, j5))
s6, j6 = post()
mode6 = stat.S_IMODE(os.stat(REQ).st_mode) if os.path.exists(REQ) else None
d6 = json.load(open(REQ, encoding="utf-8")) if os.path.exists(REQ) else {}
chk(s6 == 200 and (j6 or {}).get("ok") and mode6 == 0o600, "W6 통과 = 200 · 요청 파일 0600", (s6, j6, oct(mode6 or 0)))
chk(d6.get("since") == "2026-05-15" and d6.get("weekly") is True and d6.get("by") == "web" and isinstance(d6.get("at"), int)
    and set(d6) == {"since", "weekly", "at", "by"}, "W7 내용 = {since = 원장 창 시작, weekly, at, by}", d6)
chk(web.BUILDER.mp == 1, "W8 화면 칸 갱신(mpatch review) 1번 — '요청함' 표시", web.BUILDER.mp)
d6b = dict(d6, at=1)
statefile.atomic_write_json(REQ, d6b)
s7, j7 = post()
chk(s7 == 200 and json.load(open(REQ, encoding="utf-8")) == d6b and "이미" in str((j7 or {}).get("msg")),
    "W9 이미 요청돼 있으면 덮지 않음(200 · '이미 요청')", (s7, j7))
chk(web.review_fill_req_view() == {"at": 1, "since": "2026-05-15"}, "W10 화면용 요청 보기 {at, since}", web.review_fill_req_view())
rm(REQ)
web.BUILDER = FB(ws=None)
s8, _ = post()
d8 = json.load(open(REQ, encoding="utf-8")) if os.path.exists(REQ) else {}
chk(s8 == 200 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d8.get("since"))) is not None, "W11 창 시작 못 읽음 = 설정 개월 수로(형식 맞음)", d8)
rm(REQ)
SRV.shutdown()
SRV.server_close()
statefile.atomic_write_json(REQ, {"since": "invalid", "at": 12})
req12 = web.review_fill_req_view() == {"since": "invalid", "at": 12}
rd.fill_request_check(CFG)
req12 = req12 and not os.path.exists(REQ) and os.path.exists(REQ + ".bad") and web.review_fill_req_view() is None
rm(REQ + ".bad")
with rd._ManualLock():
    lock12 = web.review_manual_busy() and rd._manual_lock_live()
chk(req12 and lock12 and not web.review_manual_busy() and not rd._manual_lock_live(), "W12 웹·데몬 같은 요청·잠금 파일(요청 보기·소비 · 잠금 바쁨)",
    (req12, lock12))
WSRC = T.web_src()
fb_src = WSRC[WSRC.index("def _review_fill_post"):WSRC.index("def _health_ack_post")]
chk("subprocess" not in fb_src and "claude" not in fb_src.lower().replace("claude 사용량", "") and "review_daily" not in fb_src,
    "W13 웹은 모델·프로세스를 부르지 않음(요청 파일만)")

print("[D] tj-review — 요청 처리")
CALLS = []
SEEN = {}


def f_catch(cfg, since_iso=None, dry=False, before=None):
    CALLS.append(("daily", since_iso))
    SEEN["before"] = before
    SEEN["lock"] = rd._manual_lock_live()
    SEEN["btn"] = rd._FILL_BTN[0]


def f_week(cfg, since_iso, dry=False, before=None):
    CALLS.append(("weekly", since_iso))
    return []


rd.catch_up, rd.weekly_since = f_catch, f_week


def fc(cfg=None):
    r = rd.fill_request_check(cfg or {})
    t9 = (getattr(rd, "_FILL_THREAD", None) or [None])[0]
    if t9 is not None:
        t9.join(10)
    return r


def put_req(obj):
    statefile.atomic_write_json(REQ, obj)


def pause(on):
    statefile.atomic_write_json(paths.state("ui_prefs.json"), {"review_pause": {"on": on, "at": 1}} if on else {})


chk(fc() is False and CALLS == [], "D1 요청 없음 = 아무것도 안 함")
put_req({"since": "2026-05-15", "weekly": True, "at": 1, "by": "web"})
r2 = fc()
chk(r2 is True and CALLS == [("daily", "2026-05-15"), ("weekly", "2026-05-15")] and not os.path.exists(REQ),
    "D2 요청 = 일간 → 주간(같은 since · 수동 경로) · 요청 지움", CALLS)
chk(SEEN.get("lock") is True and SEEN.get("btn") is True and not rd._manual_lock_live() and rd._FILL_BTN[0] is False,
    "D3 실행 중 수동 잠금 살아 있음(자동 보충 건너뜀) · 끝나면 잠금·표시 풀림", SEEN)
r3 = fc()
chk(r3 is False and len(CALLS) == 2, "D4 1번만 처리(다시 확인해도 안 돎)", CALLS)
CALLS.clear()
statefile.atomic_write_json(paths.state("review_catchup_manual.lock"), {"pid": os.getpid(), "ts": int(rd.time.time())})
put_req({"since": "2026-05-15", "weekly": True, "at": 1, "by": "web"})
r5 = fc()
rm(paths.state("review_catchup_manual.lock"))
chk(r5 is False and CALLS == [] and not os.path.exists(REQ), "D5 수동 잠금 중 = 무시(요청 지움 · 실행 0)", CALLS)
pause(True)
put_req({"since": "2026-05-15", "weekly": True, "at": 1, "by": "web"})
r6 = fc()
chk(r6 is False and CALLS == [] and os.path.exists(REQ), "D6 멈춤 중 = 실행 안 함(요청은 남김 — 풀면 이어서)", CALLS)
pause(False)
r6b = fc()
chk(r6b is True and len(CALLS) == 2 and not os.path.exists(REQ), "D6b 멈춤 풀면 다음 확인 때 실행", CALLS)
CALLS.clear()
with open(REQ, "w", encoding="utf-8") as f:
    f.write("{since: 깨짐")
r7 = fc()
chk(r7 is False and CALLS == [] and not os.path.exists(REQ) and os.path.exists(REQ + ".bad"), "D7 깨진 요청 = 무시(.bad 로 옮김)", CALLS)
rm(REQ + ".bad")
for bad in ({"since": "2026-13-01"}, {"since": 20260515}, ["2026-05-15"], {}):
    put_req(bad)
    r8 = fc()
    chk(r8 is False and CALLS == [] and not os.path.exists(REQ) and os.path.exists(REQ + ".bad"), f"D8 형식 오류 {bad!r} = 무시(.bad)", CALLS)
    rm(REQ + ".bad")
put_req({"since": "2026-05-15", "weekly": True})
pause(False)


def f_catch_pause(cfg, since_iso=None, dry=False, before=None):
    CALLS.append(("daily", since_iso))
    pause(True)


rd.catch_up = f_catch_pause
r9 = fc()
pause(False)
chk(r9 is True and CALLS == [("daily", "2026-05-15")], "D9 일간 도중 멈춤 켜면 주간은 시작 안 함", CALLS)
CALLS.clear()


def f_boom(cfg, since_iso=None, dry=False, before=None):
    raise RuntimeError("합성 오류")


rd.catch_up = f_boom
put_req({"since": "2026-05-15", "weekly": True})
r10 = T.safe(fc)
chk(r10 is True and not rd._manual_lock_live() and rd._FILL_BTN[0] is False, "D10 실행 오류 = 데몬 안 멈춤 · 잠금·표시 풀림", r10)
rd.catch_up = f_catch

print("[D] _nap — 잠자는 동안 1분마다 확인")


class FakeTime:
    def __init__(self, t0=1000.0):
        self.t, self.sl = float(t0), []

    def time(self):
        return self.t

    def sleep(self, s):
        self.sl.append(s)
        self.t += s


ft, n_chk = FakeTime(), []
rt, rfc = rd.time, rd.fill_request_check
rd.time, rd.fill_request_check = ft, (lambda cfg: n_chk.append(1))
try:
    rd._nap(150, {})
finally:
    rd.time, rd.fill_request_check = rt, rfc
chk(ft.sl == [60, 60, 30] and len(n_chk) == 3 and ft.t == 1150.0, "D11 150초 = 60·60·30 쪼개 자며 3번 확인 · 깨는 시각 같음", ft.sl)

print("[R] 시간 걸리는 채우기 — 예약 루프는 기다리지 않음 · 하나만 · 시작일 고정")
GATE = threading.Event()
RC = []


def f_slow(cfg, since_iso=None, dry=False, before=None):
    RC.append((since_iso, before, rd._manual_lock_live()))
    GATE.wait(20)


rd.catch_up = f_slow
CALLS.clear()
put_req({"since": "2026-05-15", "weekly": True, "at": 1, "by": "web"})
T0R = float(int(rd.time.time()))
ft2 = FakeTime(T0R)
rt2 = rd.time
rd.time = ft2
nap_t = threading.Thread(target=rd._nap, args=(150, {}), daemon=True)
try:
    nap_t.start()
    nap_t.join(3)
    nap_late = nap_t.is_alive()
finally:
    rd.time = rt2
chk(not nap_late and ft2.t == T0R + 150, "R1 23:50 대기 중 요청 = 예약 루프는 제시각(_nap 이 채우기를 기다리지 않음 → run_today 안 밀림)",
    {"nap 아직 안 끝남": nap_late, "깬 시각(+초)": ft2.t - T0R})
for _ in range(50):
    if RC:
        break
    threading.Event().wait(0.05)
t_fill = (getattr(rd, "_FILL_THREAD", None) or [None])[0]
chk(len(RC) == 1 and RC[0][2] is True and t_fill is not None and t_fill.is_alive(), "R2 채우기 = 배경 스레드 하나(수동 잠금 안에서 도는 중)", RC)
put_req({"since": "2026-05-15", "weekly": True, "at": 2, "by": "web"})
r_dup = rd.fill_request_check({})
chk(r_dup is False and len(RC) == 1 and not os.path.exists(REQ), "R3 이미 돌고 있으면 새 요청 무시(지움 · 두 번째 실행 없음)", RC)
chk(rd._manual_lock_live(), "R4 도는 동안 수동 잠금 = 자동 보충(catch_up·weekly_refresh)은 종전대로 건너뜀")
today9 = datetime.now(rd.KST).strftime("%Y-%m-%d")
chk(RC and RC[0][1] == today9, "R5 채우기 날짜 기준 = 시작한 날로 고정(before — 자정 넘겨도 오늘·어제 예약분과 안 겹침)", (RC, today9))
GATE.set()
if t_fill is not None:
    t_fill.join(10)
chk(t_fill is not None and not t_fill.is_alive() and not rd._manual_lock_live() and rd._FILL_BTN[0] is False and CALLS == [("weekly", "2026-05-15")],
    "R6 끝나면 주간까지 하고 잠금·표시 풀림", CALLS)
rd.catch_up = f_catch
CALLS.clear()
rdmain = open(os.path.join(T.SRC, "review_daily.py"), encoding="utf-8").read()
rt_body = rdmain[rdmain.index("def run_today(cfg):"):rdmain.index("def receipt_items(")]
chk("_manual_lock_live" not in rt_body, "R7 run_today 는 수동 잠금과 무관하게 돈다(채우기 중에도 23:50 일간)")

print("[D] 멈춤 — 전체 채우기만 건마다")
PP = os.path.join(paths.STATE_DIR, "rp_test.json")


def run_items(btn):
    done = []
    run = rprog.Run(PP, "manual-catchup", {"daily": ["2026-05-01", "2026-05-02"]}, "recent", 1, 0)
    rd._FILL_BTN[0] = btn
    try:
        why = rd._run_items(run, [("daily", "2026-05-01", ""), ("daily", "2026-05-02", "")], lambda k, d: done.append(d) or True, 1, pace_s=0)
    finally:
        rd._FILL_BTN[0] = False
        run.close(None)
    return why, done


pause(True)
w1, dn1 = run_items(True)
w2, dn2 = run_items(False)
pause(False)
chk(w1 == "자동 생성 멈춤(설정)" and dn1 == [], "D12 전체 채우기 + 멈춤 = 새 건 안 씀", (w1, dn1))
chk(w2 is None and dn2 == ["2026-05-01", "2026-05-02"], "D13 CLI 수동(--catchup-since) + 멈춤 = 종전대로 씀(무변)", (w2, dn2))

RSRC = open(os.path.join(T.SRC, "review_daily.py"), encoding="utf-8").read()
mn = RSRC[RSRC.index("def main():"):]
chk(rd.CATCHUP_DAYS == 3 and rd.CATCHUP_OLD_MAX == 5 and "target = ref.replace(hour=23, minute=50, second=0, microsecond=0)" in mn
    and "tfix = ref.replace(hour=0, minute=15, second=0, microsecond=0)" in mn, "D14 자동 규칙 무변(최근 3일 · 옛 날 하루 5일 · 23:50 · 00:15)")
chk(re.search(r"with _ManualLock\(\):[^\n]*\n            catch_up\(cfg, sys\.argv\[2\]\)", mn)
    and "with _ManualLock():\n            weekly_since(cfg, sys.argv[2])" in mn, "D15 CLI --catchup-since · --weekly-since 무변")
chk(mn.count("_nap(max(30,") == 2 and "time.sleep(max(30," not in mn, "D16 예약 대기 두 곳 = _nap(같은 시각 · 1분마다 요청 확인)")

print("[U] 화면·README")
AJ = T.app_js()
fa = AJ[AJ.index("revFillAll: () =>"):AJ.index("revFill: async el =>")]
chk('data-a="revFillAll"' in AJ and "'/api/review/fill'" in fa and "confirmAsk(" in fa and "confirm(" not in fa.replace("confirmAsk(", ""),
    "U1 '전체 채우기' 버튼 → 앱 확인창(브라우저 confirm 아님) → POST /api/review/fill")
chk("Claude 사용량을 써요" in fa and "P.avgSec" in fa and "/ par" in fa and "최근 날부터" in fa, "U2 확인창 = 건수 · 순서 · 사용량 · 약 X(평균 × 건수 ÷ 동시 수)")
rp = AJ[AJ.index("function revProgHTML"):AJ.index("const REV_LEN = {")]
chk("수동 실행에서만" not in AJ and "전체 채우기로" in rp and "runs.length ? ''" in rp and "P.fillReq" in rp,
    "U3 문구 '전체 채우기로 써요' · 진행 중이면 버튼 없음 · 요청함 표시")
chk("<select" not in rp and 'class="btn sm" data-a="revFillAll"' in rp, "U4 기존 .btn sm 스타일")
RM = T.doc_text("README.md")
chk("설정 › AI 리뷰 › **전체 채우기**로 한 번에 써요" in RM, "U5 README 한 줄")
T.finish()
