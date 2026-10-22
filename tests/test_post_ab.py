#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402

chk = T.chk
TOOLS = os.path.join(T.ROOT, "tools", "refactor")
if not (os.path.isfile(os.path.join(TOOLS, "post_ab.py")) and os.path.isfile(os.path.join(TOOLS, "post_ab_drive.py"))):
    _pub = os.path.realpath(T.HERE) == os.path.realpath(os.path.join(T.ROOT, "tests"))
    chk(_pub, "공개판 배치 — 비공개 도구(tools/refactor/post_ab.py · post_ab_drive.py) 없음 · 건너뜀" if _pub else "저장소 배치인데 비공개 도구 없음(건너뛰지 않고 실패)")
    T.finish()
sys.path.insert(0, TOOLS)
import post_ab as P  # noqa: E402

RT, DEC, BAD = P.check_discovery(T.ROOT)
locked = sorted(r for r, v in RT.items() if v["locked"])
inline = sorted(r for r, v in RT.items() if v["inline"])
chk(not BAD and len(RT) == 37 and set(RT) == DEC, "P1 본문 경로 발견 37 = 선언(POST − setup − 로그인)", BAD)
chk(len(locked) == 22 and len(RT) - len(locked) == 15, "P1 잠금 안 22 · 잠금 밖 15", locked)
chk(len(inline) == 33 and not any(r.startswith("/api/ops/") for r in inline)
    and all(os.path.basename(f) == "http_post_prefs.py" for r in inline for f, _lo, _hi in RT[r]["ranges"]),
    "P1 덮음 대상 33(표의 처리 함수 = http_post_prefs · 접두어 4 는 호출)", inline)
chk(sorted(r for r in RT if r.startswith("/api/ops/")) == ["/api/ops/decimals_resolve", "/api/ops/poison_replay", "/api/ops/rebuild_approve",
                                                            "/api/ops/rebuild_cancel"], "P1 /api/ops/ 동작 4 = 처리 함수의 act 비교에서")

CHAIN = '''
class H:
    def do_POST(self):
        path = self.path
        try:
            if path == "/api/a":
                return self._a(body)
            if path.startswith("/api/op/"):
                return self._op(path, body)
            lk().acquire()
            if path == "/api/b":
                x = 1
                return self._send(200, {})
            elif path in ("/api/c", "/api/d"):
                if x:
                    y = 2
            else:
                self._send(404, {})
        finally:
            pass

    def _op(self, path, body):
        act = path[len("/api/op/"):]
        if act == "go":
            pass
        elif act == "stop":
            pass
'''
TABLE = '''
OPS_PREFIX = "/api/op/"


def post_routes():
    NOLOCK = {"/api/a": h_a}
    LOCKED = {"/api/b": h_b, "/api/c": h_c}
    return NOLOCK, LOCKED


def h_a(h, path, body):
    return h._a(body)


def h_b(h, path, body, prefs):
    x = 1
    return h._send(200, {})


def h_c(h, path, body, prefs):
    if body:
        y = 2


def _op(h, path, body):
    act = path[len(OPS_PREFIX):]
    if act == "go":
        pass
'''


def mk_tree(name, files):
    d = os.path.join(T.TMP, name)
    os.makedirs(os.path.join(d, "src"), exist_ok=True)
    for fn, txt in files.items():
        with open(os.path.join(d, "src", fn), "w", encoding="utf-8") as f:
            f.write(txt)
    return d


c1 = P.discover(mk_tree("syn_chain", {"route.py": CHAIN, "other.py": "def f():\n    return 1\n"}))
chk(sorted(c1) == ["/api/a", "/api/b", "/api/c", "/api/d", "/api/op/go", "/api/op/stop"], "P2 사슬 꼴 경로(정확 · 튜플 · elif · 접두어 + act)", sorted(c1))
chk([c1[r]["locked"] for r in ("/api/a", "/api/op/go", "/api/b", "/api/c")] == [False, False, True, True], "P2 잠금 잡는 문장 뒤 = 잠금 안",
    {r: v["locked"] for r, v in c1.items()})
chk(c1["/api/a"]["method"] == "_a" and not c1["/api/a"]["inline"] and c1["/api/b"]["inline"] and len(c1["/api/c"]["stmts"]) == 2,
    "P2 한 줄 호출 = 호출 · 그 밖 = 옮길 몸통(중첩 문장 셈)", {r: (v["method"], v["inline"], len(v["stmts"])) for r, v in c1.items()})
t1 = P.discover(mk_tree("syn_table", {"route.py": "class H:\n    def do_POST(self):\n        fn = post_routes()\n", "prefs_mod.py": TABLE}))
chk(sorted(t1) == ["/api/a", "/api/b", "/api/c", "/api/op/go"], "P2 표 꼴 경로(post_routes · *PREFIX)", sorted(t1))
chk(not t1["/api/a"]["locked"] and t1["/api/b"]["locked"] and t1["/api/c"]["stmts"] and t1["/api/b"]["ranges"][0][0].endswith("prefs_mod.py"),
    "P2 표 꼴 잠금 구분 · 진입 범위 = 처리 함수", {r: (v["locked"], v["ranges"]) for r, v in t1.items()})

try:
    P.discover(mk_tree("syn_table_dup", {"route.py": "class H:\n    def do_POST(self):\n        fn = post_routes()\n", "prefs_mod.py": TABLE,
                                         "other_mod.py": "def h_b(h, path, body, prefs):\n    return None\n"}))
    amb = False
except SystemExit:
    amb = True
chk(amb, "P2 표 꼴 처리 함수 이름 정의가 여럿 = 거부(엉뚱한 함수로 진입 세기 금지)")

REC = {"status": 200, "body": {"ok": True}, "events": [["prefs", "acquire"], ["enter"], ["send", 200], ["prefs", "release"]],
       "state": [["ui_prefs.json", "ab"]], "entered": True}


def res_of(**over):
    r = dict(REC, **over)
    return {"cases": {"/api/b#normal": r}, "lines": [], "net_tries": []}


A = res_of()
chk(P.compare(A, res_of()) == [], "P3 같은 기록 = 차이 0")
for k, v in (("status", 409), ("body", {"ok": False}), ("events", [["enter"], ["prefs", "acquire"], ["send", 200], ["prefs", "release"]]),
             ("state", []), ("entered", False), ("headers", [["content-type", "text/plain"]]), ("done", False)):
    d = P.compare(A, res_of(**{k: v}))
    chk(len(d) == 1 and d[0][1] == k, "P3 칸 차이 잡음: " + k, d)
chk(P.compare(A, {"cases": {}, "lines": []})[0][1] == "요청 없음", "P3 한쪽에 없는 요청 = 차이")
syn = P.discover(mk_tree("syn_chain2", {"route.py": CHAIN}))
reqs = [{"id": "/api/b#normal", "path": "/api/b", "route": "/api/b"}]
bad, cover = P.preconditions({"/api/b": syn["/api/b"]}, reqs, res_of(), {"unreachable": []})
chk(any("덮음 모자람" in x for x in bad) and cover["/api/b"]["stmts"] == 2, "P3 실행 안 된 몸통 문장 = 덮음 모자람", bad)
b_lines = [[os.path.realpath(f), ln] for f, ln in syn["/api/b"]["stmts"]]
bad2, _ = P.preconditions({"/api/b": syn["/api/b"]}, reqs, dict(res_of(), lines=b_lines), {"unreachable": []})
chk(bad2 == [], "P3 진입 · 덮음 100% · 바깥 연결 0 = 통과", bad2)
bad3, _ = P.preconditions({"/api/b": syn["/api/b"]}, reqs, dict(res_of(entered=False), lines=b_lines[:1], net_tries=["x.example"]),
                          {"unreachable": [{"route": "/api/b", "text": "return self._send(200, {})", "why": "합성"},
                                           {"route": "/api/b", "text": "없는 글", "why": "합성"}]})
chk(any("진입 없음" in x for x in bad3) and not any("덮음 모자람" in x for x in bad3) and any("목록에서 지우라" in x for x in bad3)
    and any("바깥 연결" in x for x in bad3), "P3 진입 없음 · unreachable 인정 · 낡은 unreachable · 바깥 연결 = 실패", bad3)
chk(P.preconditions({}, [], {"cases": {}, "lines": []}, {"unreachable": []})[0] == ["기록이 빔"], "P3 기록이 빔 = 실패")
flat = {"cases": {"/api/b#normal": REC, "/api/b#empty": REC}, "lines": b_lines}
chk(any("정상 본문과 빈 본문" in x for x in P.preconditions({"/api/b": syn["/api/b"]}, reqs, flat, {"unreachable": []})[0])
    and not any("정상 본문과 빈 본문" in x for x in P.preconditions({"/api/b": syn["/api/b"]}, reqs, flat,
                                                                     {"unreachable": [], "body_insensitive": {"/api/b": "합성"}})[0]),
    "P3 정상 본문 = 빈 본문 기록 = 실패(본문 전달 못 봄) · body_insensitive 이유 = 허용")
bad4, _ = P.preconditions({"/api/b": syn["/api/b"]}, reqs, dict(res_of(done=False), lines=b_lines), {"unreachable": []})
chk(any("30초 안에 안 끝난" in x for x in bad4), "P3 처리 스레드가 안 끝난 요청 = 실패", bad4)
try:
    P.build_requests({"/api/b": syn["/api/b"]}, {"routes": {}, "cases": [{"path": "/api/b", "id": "x"}, {"path": "/api/b", "id": "x"}],
                                                  "unreachable": []})
    dup = False
except SystemExit:
    dup = True
chk(dup, "P3 요청 id 겹침 = 거부")

SCR = os.path.join(T.TMP, "scr")
os.makedirs(SCR, exist_ok=True)
OUT = os.path.join(SCR, "full.json")
p4 = subprocess.run([sys.executable, "-I", os.path.join(TOOLS, "post_ab.py"), "run", "--base", T.ROOT, "--work", T.ROOT, "--scratch", SCR,
                     "--out", OUT, "--keep"], capture_output=True, text=True, timeout=600)
chk(p4.returncode == 0 and "결과: 통과" in p4.stdout, "P4 같은 트리 run = 통과(두 번 차이 0 · 진입 37/37 · 덮음 100%)", (p4.stdout + p4.stderr)[-1500:])
with open(OUT, encoding="utf-8") as f:
    S4 = json.load(f)
BR = S4["base_record"]["cases"]
chk(S4["routes"] == 37 and S4["pre"] == [] and all(m == 0 for _n, m in S4["cover_base"].values()) and len(S4["cover_base"]) == 33,
    "P4 경로 37 · 선행 조건 0 · 처리 함수 33 전부 덮음", {k: S4[k] for k in ("routes", "pre")})
ev = BR["plan#full"]["events"]
e2 = [e[:2] for e in ev]
chk(e2[0] == ["b.mats_wait", "/api/plan"] and e2[1] == ["prefs", "acquire"] and e2.index(["enter"]) > 1 and e2[-1] == ["prefs", "release"]
    and ["cache", None] in e2,
    "P4 잠금 차례 기록(준비 검사 → 잠금 → 진입 → 캐시 무효화 → 보냄 → 풂)", ev)
chk(BR["/api/zz_post_ab_unknown#normal"]["status"] == 404 and BR["/api/zz_post_ab_unknown#normal"]["events"][1][:2] == ["prefs", "acquire"],
    "P4 모르는 경로 = 잠금 잡은 뒤 404", BR["/api/zz_post_ab_unknown#normal"])
chk(BR["reval#pause_auto_ctype"]["status"] == 409 and BR["reval#nopause_auto_ctype"]["status"] == 415, "P4 멈춤 409 가 415 보다 먼저")
chk(BR["/api/plan#raise_in_lock"]["status"] == 500 and BR["/api/plan#raise_in_lock"]["events"][-1][:2] == ["prefs", "release"],
    "P4 처리 중 예외 = 500 + 잠금 풂", BR["/api/plan#raise_in_lock"])
chk(BR["combo#fallback_send_fail"]["status"] is None and ["log", "DEBUG", "%s %s 상대가 끊음: %s"] in BR["combo#fallback_send_fail"]["events"],
    "P4 연결 끊김 = _gone_or_500 의 '상대가 끊음'", BR["combo#fallback_send_fail"])
chk(BR["/api/plan#mats_wait"]["status"] == 503 and not BR["/api/plan#mats_wait"]["entered"], "P4 계산 재료 준비 전 = 503 · 진입 안 함")
chk(all(BR[r + "#big"]["status"] == 413 for r in RT), "P4 1MiB+1 = 413(37 경로)")

p4b = subprocess.run([sys.executable, "-I", os.path.join(TOOLS, "post_ab.py"), "run", "--base", T.ROOT, "--work", T.ROOT, "--scratch", SCR,
                      "--routes", "/api/fallback_avg"], capture_output=True, text=True, timeout=600)
chk(p4b.returncode == 2 and "부분 확인" in p4b.stdout, "P4 --routes(일부 경로) = rc 2(게이트 통과 아님)", (p4b.returncode, p4b.stdout[-300:]))

BASE = os.path.join(T.TMP, "mut_base")
shutil.copytree(os.path.join(T.ROOT, "src"), os.path.join(BASE, "src"), ignore=shutil.ignore_patterns("__pycache__"))
shutil.copy(os.path.join(T.ROOT, "config.example.json"), BASE)
os.makedirs(os.path.join(BASE, "public", "tests", "arch_baseline"))
shutil.copy(os.path.join(T.ROOT, "public", "tests", "arch_baseline", "sec_routes.jsonl"), os.path.join(BASE, "public", "tests", "arch_baseline"))
DOC = P.load_cases(P.CASES_DEFAULT)
ONLY = {"/api/plan", "/api/fallback_avg", "/api/receipt_eval", "/api/dust_threshold", "/api/review_len", "/api/cost_override", "/api/alert_test"}
RB = P.discover(BASE)
REQS = P.build_requests(RB, DOC, ONLY)
B0 = P.drive(BASE, REQS, RB, SCR)
FB = '    prefs["fallback_avg"] = body["on"]\n'
RL = '    prefs["review_len"] = dict(rl, **{kind: length})\n'
RLW = '    statefile.atomic_write_json(paths.state("ui_prefs.json"), prefs)\n'
MUT = {
    "status": ('return h._send(400, {"error": "key 필요"})', 'return h._send(422, {"error": "key 필요"})'),
    "lock404": ("            web_ctx.prefs_lock().acquire()\n",
                "            if path.startswith(\"/api/zz\"):\n                return self._send(404, {\"error\": \"not found\"})\n"
                "            web_ctx.prefs_lock().acquire()\n"),
    "order415": ('    if body.get("auto") is True and review_pause_eff(',
                 '    if not h._write_guard():\n        return\n    if body.get("auto") is True and review_pause_eff('),
    "nocache": (FB + RLW + '    with web_ctx.builder().lock:\n        web_ctx.builder().cache = None\n', FB + RLW),
    "value": ('prefs["dust_usd"] = max(0.0, min(v, 1e6))', 'prefs["dust_usd"] = max(0.0, min(v, 1e7))'),
    "dropkey": (FB, FB + '    prefs.pop("risk_overrides", None)\n'),
    "const": (FB, '    prefs["fallback_avg"] = True\n'),
    "net": (FB, FB + '    try:\n        __import__("urllib.request").request.urlopen("http://example.invalid/x", timeout=1)\n'
                '    except Exception:\n        pass\n'),
    "thread": (FB, FB + '    tm = __import__("threading").Timer(120, lambda: None)\n    tm.daemon = True\n    tm.start()\n'),
    "mpatch_order": (RL + RLW + '    if not web_ctx.bcall("mpatch", {"review"}):',
                     RL + '    mp = web_ctx.bcall("mpatch", {"review"})\n' + RLW + '    if not mp:'),
    "nonblock": ("            web_ctx.prefs_lock().acquire()\n", "            web_ctx.prefs_lock().acquire(False)\n"),
    "nogate": ("            if onboarding.handle_post(self, path):", "            if False and onboarding.handle_post(self, path):"),
    "query": ('    def do_POST(self):\n        path = self.path.split("?", 1)[0]\n', '    def do_POST(self):\n        path = self.path\n'),
    "importwrite": ("\nclass ", '\nopen(__import__("paths").state("zz_import.json"), "w").write("{}")\n\n\nclass '),
    "udp": (FB, FB + '    try:\n        __import__("socket").socket(2, 2).sendto(b"x", ("192.0.2.1", 9))\n'
                '    except Exception:\n        pass\n'),
    "ossystem": (FB, FB + '    try:\n        __import__("os").system("true")\n    except Exception:\n        pass\n'),
    "mats_path": ("            if not web_ctx.mats_ready(path):   # 저장 검증",
                  '            if not web_ctx.mats_ready(path.replace("/api/", "/", 1)):   # 저장 검증'),
    "mats_first": ("        locked = False\n        try:\n",
                   "        locked = False\n        try:\n            if not web_ctx.mats_ready(path):\n"
                   "                return self._send(503, {\"ok\": False, \"error\": \"x\"})\n"),
    "battr_pop": ('last = last.get("fields") if', 'last = last.pop("fields") if'),
    "write_in_lock": (FB + RLW + '    with web_ctx.builder().lock:\n',
                      FB + '    with web_ctx.builder().lock:\n        statefile.atomic_write_json(paths.state("ui_prefs.json"), prefs)\n'),
    "reentrant": (FB, FB + "    with web_ctx.prefs_lock():\n        pass\n"),
    "lock_alias": ("PREFS_LOCK = threading.Lock()   #", "PREFS_LOCK = threading.Lock()\nPREFS_LOCK_SAVED = PREFS_LOCK   #"),
    "slash": ('    def do_POST(self):\n        path = self.path.split("?", 1)[0]\n',
              '    def do_POST(self):\n        path = self.path.split("?", 1)[0].rstrip("/") or "/"\n'),
    "argdrop": ("return h._alert_test_post(body)", "return h._alert_test_post({})"),
    "outside404": ("            web_ctx.prefs_lock().acquire()\n",
                   "            if not path.startswith(\"/api/\"):\n                return self._send(404, {\"error\": \"not found\"})\n"
                   "            web_ctx.prefs_lock().acquire()\n"),
    "table_unlocked": ('        "/api/fallback_avg": http_post_prefs.post_fallback_avg,\n', ''),
}
MUT_FILE = {"lock_alias": "web.py"}
MUT_FILE.update({k: "http_post_prefs.py" for k in ("status", "order415", "nocache", "value", "dropkey", "const", "net", "thread", "mpatch_order",
                                                   "udp", "ossystem", "battr_pop", "write_in_lock", "reentrant", "argdrop")})
MUT_FIX = {"table_unlocked": ('    nolock = {\n', '    nolock = {\n        "/api/fallback_avg": http_post_prefs.post_fallback_avg,\n')}
EXPECT = {"status": ("plan#no_key", "status"), "lock404": ("/api/zz_post_ab_unknown#normal", "events"),
          "order415": ("reval#pause_auto_ctype", "status"), "nocache": ("/api/fallback_avg#normal", "events"), "value": ("dust#clamp", "state"),
          "dropkey": ("/api/fallback_avg#normal", "state"), "const": ("/api/fallback_avg#flip_on", "state"),
          "net": ("/api/fallback_avg#normal", "net"), "thread": ("/api/fallback_avg#normal", "events"),
          "mpatch_order": ("/api/review_len#normal", "events"), "nonblock": ("/api/fallback_avg#normal", "events"),
          "nogate": ("/api/fallback_avg#no_origin", "status"), "query": ("/api/fallback_avg#query", "status"),
          "importwrite": ("__init__", "init_state"), "udp": ("/api/fallback_avg#normal", "net"), "ossystem": ("/api/fallback_avg#normal", "events"),
          "mats_path": ("/api/fallback_avg#normal", "events"), "mats_first": ("/api/fallback_avg#mats+no_origin", "status"),
          "battr_pop": ("cost#breakeven", "battrs_after"), "write_in_lock": ("/api/fallback_avg#normal", "events"),
          "reentrant": ("/api/fallback_avg#normal", "status"), "lock_alias": ("__init__", "init"),
          "slash": ("/api/fallback_avg#slash", "status"), "argdrop": ("/api/alert_test#normal", "status"),
          "outside404": ("/zz_post_ab_outside#normal", "events"), "table_unlocked": ("/api/fallback_avg#normal", "events")}
LIFT_OLD = ('    """POST /api/fallback_avg — 원가 미상 평균가 대체 켬·끔(ui_prefs fallback_avg)."""\n',
            '    h._send(200, {"ok": True, "on": prefs["fallback_avg"]})\n')


def mutant(name, edit, file=None):
    d = os.path.join(T.TMP, "mut_" + name)
    shutil.copytree(os.path.join(BASE, "src"), os.path.join(d, "src"), copy_function=os.link)
    shutil.copy(os.path.join(BASE, "config.example.json"), d)
    shutil.copytree(os.path.join(BASE, "public"), os.path.join(d, "public"))
    fp = os.path.join(d, "src", file or MUT_FILE.get(name, "http_route.py"))
    with open(fp, encoding="utf-8") as f:
        txt = f.read()
    new = edit(txt)
    os.remove(fp)
    with open(fp, "w", encoding="utf-8") as f:
        f.write(new)
    return d, new != txt


def drive_in(name, d):
    w = os.path.join(SCR, "w_" + name)
    os.makedirs(w, exist_ok=True)
    return P.drive(d, REQS, P.discover(d), w)


def _edit(name, old, new):
    def f(t):
        out = t.replace(old, new, 1)
        if name in MUT_FIX:
            out = out.replace(MUT_FIX[name][0], MUT_FIX[name][1], 1) if out != t else out
        return out
    return f


MADE = {name: mutant(name, _edit(name, old, rep)) for name, (old, rep) in MUT.items()}
with ThreadPoolExecutor(max_workers=6) as ex:
    RES = dict(zip(MADE, ex.map(lambda n: drive_in(n, MADE[n][0]), list(MADE))))
for name in MUT:
    diffs = P.compare(B0, RES[name])
    cid, field = EXPECT[name]
    chk(MADE[name][1] and any(x[0] == cid and x[1] == field for x in diffs), "P5 변이 잡음: " + name, [x[:2] for x in diffs][:8])
chk(P.preconditions({r: v for r, v in RB.items() if r in ONLY}, REQS, RES["udp"], DOC)[0] != [], "P5 바깥 보내기(UDP) = 작업 쪽 선행 조건도 실패")


def lift(txt):
    i = txt.index(LIFT_OLD[0]) + len(LIFT_OLD[0])
    j = txt.index(LIFT_OLD[1], i) + len(LIFT_OLD[1])
    fn = "\n\ndef _lifted_fallback_avg(h, body, prefs):\n" + txt[i:j]
    return txt[:i] + "    return _lifted_fallback_avg(h, body, prefs)\n" + txt[j:] + fn


d5, ch5 = mutant("lift", lift, "http_post_prefs.py")
R5 = P.discover(d5)
diffs5 = P.compare(B0, P.drive(d5, REQS, R5, SCR))
chk(ch5 and not RB["/api/fallback_avg"]["ranges"] == R5["/api/fallback_avg"]["ranges"] and diffs5 == [], "P5 몸통을 모듈 함수로 옮김 = 차이 0",
    [x[:2] for x in diffs5][:8])
T.finish()
