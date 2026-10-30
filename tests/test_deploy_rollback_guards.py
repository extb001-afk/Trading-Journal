#!/usr/bin/env python3
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

TOOLS = os.path.join(T.ROOT, "tools")
RB = os.path.join(TOOLS, "rollback_hotfix_20260928t.sh")
DEP = os.path.join(TOOLS, "deploy_hotfix_20260928t.sh")
LIB = os.path.join(TOOLS, "deploy_lib.sh")
if not (os.path.isfile(RB) and os.path.isfile(DEP) and os.path.isfile(LIB)):
    print("SKIP tools/ 배포·롤백 셸 없음(공개판)")
    T.finish()
BASH = "/bin/bash" if os.path.exists("/bin/bash") else shutil.which("bash")
PY = sys.executable
ALL9 = "tj-web tj-exf tj-ex tj-sol tj-bsc tj-evm tj-review tj-alert tj-core".split()
PM2 = os.path.join(T.TMP, "fakepm2.py")
with open(PM2, "w") as f:
    f.write('''#!%s
import json, os, sys
p = os.environ["FAKEPM2_STATE"]
d = json.load(open(p))
a = sys.argv[1:]
open(p + ".calls", "a").write(" ".join(a) + "\\n")
if a[:1] == ["jlist"]:
    print(json.dumps([{"name": n, "pid": 1, "pm2_env": {"status": s, "restart_time": 0}} for n, s in d.items()]))
    sys.exit(0)
if a[:1] in (["start"], ["stop"]):
    for u in a[1:]:
        if u not in d:
            sys.exit(1)
        d[u] = "online" if a[0] == "start" else "stopped"
    json.dump(d, open(p, "w"))
sys.exit(0)
''' % PY)
os.chmod(PM2, os.stat(PM2).st_mode | stat.S_IXUSR)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def sha_file(fpath):
    with open(fpath, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def mkdb(p, mark):
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE m(k TEXT PRIMARY KEY, v TEXT)")
    c.execute("INSERT INTO m VALUES('mark', ?)", (mark,))
    c.commit()
    c.close()


def mark(p):
    return sqlite3.connect("file:" + p + "?mode=ro", uri=True).execute("SELECT v FROM m").fetchone()[0]


def w(p, s):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(s)


N = [0]


def case(live_a="X = 'new'\n", manifest=True, tools=None, after_tools=None, ledger_files=False):
    N[0] += 1
    r = os.path.join(T.TMP, "c%02d" % N[0])
    live, home = os.path.join(r, "live"), os.path.join(r, "home")
    ts = "20261021_1200%02d_%d" % (N[0], 100 + N[0])
    bk = os.path.join(home, "tj_hotfixt_backup_" + ts)
    w(os.path.join(live, "src", "a.py"), live_a)
    w(os.path.join(live, "web", "v2", "app.js"), "var x = 1;\n")
    w(os.path.join(live, "config.json"), json.dumps({"web": {"port": 9916}, "v": "after"}))
    os.makedirs(os.path.join(live, "state"))
    mkdb(os.path.join(live, "state", "ledger.db"), "AFTER")
    for t9 in ("rollback_hotfix_20260928t.sh", "deploy_lib.sh", "deploy_hotfix_20260928t.sh"):
        os.makedirs(os.path.join(live, "tools"), exist_ok=True)
        shutil.copy2(os.path.join(TOOLS, t9), os.path.join(live, "tools", t9))
    w(os.path.join(bk, "code", "src", "a.py"), "X = 'old'\n")
    w(os.path.join(bk, "files.txt"), "src/a.py\ntools/rollback_hotfix_20260928t.sh\n")
    w(os.path.join(bk, "units.txt"), "tj-web tj-core\n")
    w(os.path.join(bk, "state", "config.json"), json.dumps({"web": {"port": 9916}, "v": "before"}))
    shutil.copy2(LIB, os.path.join(bk, "deploy_lib.sh"))
    if manifest:
        w(os.path.join(bk, "installed.sha256"), "%s  src/a.py\n%s  tools/rollback_hotfix_20260928t.sh\n"
          % (sha(b"X = 'new'\n"), sha_file(os.path.join(live, "tools", "rollback_hotfix_20260928t.sh"))))
    if tools is not None:
        w(os.path.join(bk, "tools.txt"), tools + "\n")
    if after_tools is not None:
        w(os.path.join(bk, "state", "config.after_tools.json"), json.dumps({"web": {"port": 9916}, "v": after_tools}))
    if ledger_files:
        sf = os.path.join(bk, "state_full")
        os.makedirs(sf)
        mkdb(os.path.join(sf, "ledger.db"), "SNAP")
        w(os.path.join(bk, "state_full.meta.json"), json.dumps({"v": 1, "consistent": True}))
        for f9 in ("other_assets.json", "day_memos.json", "ui_prefs.json", "settings.json", "genuine_tokens.json", "outflow_decisions.json",
                   "att_frozen.json"):
            w(os.path.join(live, "state", f9), '{"v": "after"}')
            w(os.path.join(sf, f9), '{"v": "before"}')
        w(os.path.join(sf, "cursor_evm_eth.json"), '{"v": "before"}')
        w(os.path.join(live, "state", "cursor_evm_eth.json"), '{"v": "after"}')
    json.dump({u: "online" for u in ALL9}, open(os.path.join(r, "pm2.json"), "w"))
    return r, live, bk, ts


def rb(r, live, ts, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_")}
    env.update(HOME=os.path.join(r, "home"), TJ_LIVE_DIR=live, PM2_BIN=PM2, FAKEPM2_STATE=os.path.join(r, "pm2.json"), PYTHON=PY,
               DEPLOY_NOTIFY_STUB=os.path.join(r, "notify.txt"), RB_ONLINE_WAIT="2", HOTFIX_CORE_WAIT="0", RB_SWAP_PROBE_WAIT="2",
               DEPLOY_BARRIER_WAIT="5", TJ_ROLLBACK_RUNNING="1")
    proc = subprocess.run([BASH, os.path.join(live, "tools", "rollback_hotfix_20260928t.sh"), ts] + list(args), capture_output=True, text=True, env=env, timeout=300)
    return proc.returncode, proc.stdout + proc.stderr


def calls(r):
    cf = os.path.join(r, "pm2.json.calls")
    return [x for x in (open(cf).read().splitlines() if os.path.exists(cf) else []) if x.startswith(("stop", "start"))]


def rd(fpath):
    with open(fpath) as fh:
        return fh.read()


r, live, bk, ts = case()
rc, out = rb(r, live, ts)
T.chk(rc == 0 and rd(os.path.join(live, "src", "a.py")) == "X = 'old'\n" and "해시 기록이 없음" not in out, "D01 라이브 = 설치 판 → 롤백 진행(코드 = 배포 전)", out[-600:])
r, live, bk, ts = case(live_a="X = 'old'\n")
rc, out = rb(r, live, ts)
T.chk(rc == 0, "D01 라이브 = 백업 판(부분 롤백 뒤 재실행) = 진행", out[-600:])
r, live, bk, ts = case(live_a="X = 'later'\n")
rc, out = rb(r, live, ts)
T.chk(rc != 0 and not calls(r) and rd(os.path.join(live, "src", "a.py")) == "X = 'later'\n" and "섞인 트리" in out and "src/a.py" in out
      and not os.path.exists(os.path.join(live, ".deploy_lock")), "D01 라이브 = 다른 판 → 거부 · pm2 정지 0 · 파일 무변 · 잠금 풀림", (rc, calls(r), out[-800:]))
rc, out = rb(r, live, ts, "--force")
T.chk(rc == 0 and rd(os.path.join(live, "src", "a.py")) == "X = 'old'\n" and "--force: 섞임 감수" in out, "D01 --force = 감수하고 진행", out[-600:])
r, live, bk, ts = case(manifest=False)
rc, out = rb(r, live, ts)
T.chk(rc == 0 and "설치 해시 기록이 없음" in out, "D01 옛 백업(해시 기록 없음) = 경고 뒤 진행", out[-600:])
for body, why in (("", "빈 기록"), ("%s  tools/rollback_hotfix_20260928t.sh\n" % ("0" * 64), "src/a.py 줄 빠진 기록")):
    r, live, bk, ts = case()
    w(os.path.join(bk, "installed.sha256"), body)
    rc, out = rb(r, live, ts)
    T.chk(rc != 0 and not calls(r) and "설치 해시 기록에 없음" in out, "D01 해시 기록이 있는데 " + why + " = 판단 불가 → 거부(pm2 정지 0)", (rc, out[-500:]))

for tools, after, want, why in (("pin", None, "after", "도구가 config 안 고침 = 그대로"), ("none", None, "after", "도구 없음 = 그대로"),
                                ("pin,x27", None, "before", "x27(도구 직후 판 기록 없음) = 배포 전으로"),
                                ("allchains", "after", "before", "allchains · 지금 = 도구 직후 판 = 배포 전으로"),
                                ("allchains", "tool", "after", "allchains · 도구 뒤 또 바뀜 = 그대로")):
    r, live, bk, ts = case(tools=tools, after_tools=after)
    rc, out = rb(r, live, ts)
    T.chk(rc == 0 and json.load(open(os.path.join(live, "config.json")))["v"] == want, "D02 " + why, out[-500:])
r, live, bk, ts = case()
rc, out = rb(r, live, ts)
T.chk(rc == 0 and json.load(open(os.path.join(live, "config.json")))["v"] == "before", "D02 옛 백업(tools.txt 없음) = 종전대로 배포 전으로", out[-400:])

r, live, bk, ts = case(ledger_files=True)
rc, out = rb(r, live, ts, "--ledger")
st = os.path.join(live, "state")
own = [json.load(open(os.path.join(st, f9)))["v"] for f9 in ("other_assets.json", "day_memos.json", "ui_prefs.json", "settings.json",
                                                              "genuine_tokens.json", "outflow_decisions.json", "att_frozen.json")]
T.chk(rc == 0 and mark(os.path.join(st, "ledger.db")) == "SNAP" and set(own) == {"after"}, "D03 --ledger: 원장 = 스냅숏 · 오너 입력 6파일 + 분해 동결 기록 = 지금 판", (own, out[-800:]))
lst = os.path.join(live, "state.failed_hotfixt_" + ts, "reverted_state.txt")
got = rd(lst).split() if os.path.exists(lst) else []
T.chk("ledger.db" in got and "cursor_evm_eth.json" in got and "day_memos.json" not in got and "att_frozen.json" not in got and "되돌리는 state 최상위 항목" in out,
      "D03 되돌린 최상위 항목 목록(원장·커서 · 유지 대상 없음)", (got, out[-400:]))

G = os.path.join(T.TMP, "stage")
os.makedirs(G)


def git(*a, cwd=G):
    return subprocess.run(["git", "-C", cwd] + list(a), capture_output=True, text=True, check=True).stdout.strip()


git("init", "-q")
git("config", "user.email", "t@t")
git("config", "user.name", "t")
for d9 in ("src", "web", "seed"):
    shutil.copytree(os.path.join(T.ROOT, d9), os.path.join(G, d9), ignore=shutil.ignore_patterns("__pycache__"))
for f9 in ("config.example.json", "VERSION"):
    shutil.copy2(os.path.join(T.ROOT, f9), os.path.join(G, f9))
os.makedirs(os.path.join(G, "tools"))
for t9 in ("rollback_hotfix_20260928t.sh", "deploy_lib.sh", "deploy_hotfix_20260928t.sh"):
    shutil.copy2(os.path.join(TOOLS, t9), os.path.join(G, "tools", t9))
w(os.path.join(G, "src", "_wip_s20a.py"), "X = 1\n")
git("add", "-A")
git("commit", "-qm", "c1")
C1 = git("rev-parse", "HEAD")
w(os.path.join(G, "seed", "s20_bad.json"), '{"labels": {"0xabc": "Bridge",},\n "on": true}\n')
git("add", "-A")
git("commit", "-qm", "c2")
C2 = git("rev-parse", "HEAD")
git("checkout", "-q", "-b", "c3", C1)
git("mv", "src/_wip_s20a.py", "src/_wip_s20b.py")
with open(os.path.join(G, "src", "web.py"), "a") as f:
    f.write("\n# s20 c3\n")
git("add", "-A")
git("commit", "-qm", "c3")
C3 = git("rev-parse", "HEAD")
PL = os.path.join(T.TMP, "plan_live")
os.makedirs(PL)
subprocess.run("git -C '%s' archive %s src web seed config.example.json VERSION | tar -x -C '%s'" % (G, C1, PL), shell=True, check=True)
os.makedirs(os.path.join(PL, "state"))
mkdb(os.path.join(PL, "state", "ledger.db"), "L")
w(os.path.join(PL, "config.json"), json.dumps({"web": {"port": 9917}}))
if not os.path.exists(os.path.join(PL, "seed", "debt_first_seen_t.json")):
    w(os.path.join(PL, "seed", "debt_first_seen_t.json"), "{}")
PR = os.path.join(T.TMP, "plan_r")
os.makedirs(os.path.join(PR, "home"))
json.dump({u: "online" for u in ALL9}, open(os.path.join(PR, "pm2.json"), "w"))


def plan(prev, commit, allow="", **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_")}
    env.update(HOME=os.path.join(PR, "home"), TJ_LIVE_DIR=PL, TJ_STAGE_DIR=G, PM2_BIN=PM2, FAKEPM2_STATE=os.path.join(PR, "pm2.json"),
               HOTFIX_COMMIT=commit, HOTFIXT_PREV=prev, TJ_WEB_PORT="9917", HOTFIXT_ALLOW_DELETE=allow, PYTHON=PY)
    env.update(extra)
    proc = subprocess.run([BASH, os.path.join(G, "tools", "deploy_hotfix_20260928t.sh"), "plan", "--tools", "none"], capture_output=True, text=True, env=env, timeout=300)
    return proc.returncode, proc.stdout + proc.stderr


rc, out = plan(C1, C2)
T.chk(rc != 0 and "JSON 오류 seed/s20_bad.json" in out and not calls(PR), "D04 끝 쉼표 JSON = 사전검사 'JSON 오류' 거부 · pm2 정지 0", out[-600:])
rc, out = plan(C1, C3)
T.chk(rc != 0 and "삭제된 런타임 파일 src/_wip_s20a.py" in out, "D05 이름 바꾼 파일 = 옛 이름이 삭제로 잡힘(허용 목록 없으면 거부)", out[-600:])
rc, out = plan(C1, C3, allow="src/_wip_s20a.py")
T.chk(rc == 0 and "삭제 1개" in out and "src/_wip_s20b.py src/web.py" in out, "D05 허용하면 plan 통과 · 삭제 1개 · 새 이름 설치 목록", out[-600:])

SLOWBIN = os.path.join(T.TMP, "slowgit")
os.makedirs(SLOWBIN)
w(os.path.join(SLOWBIN, "git"), """#!%s
import os, signal, subprocess, sys, time
signal.signal(signal.SIGPIPE, signal.SIG_DFL)
REAL = %r
a = sys.argv[1:]
if "archive" in a and "-o" not in a:
    r = subprocess.run([REAL] + a, stdout=subprocess.PIPE)
    if r.returncode:
        sys.exit(r.returncode)
    b = r.stdout
    i = len(b)
    while i > 0 and b[i - 512:i] == bytes(512):
        i -= 512
    o = sys.stdout.buffer
    o.write(b[:i + 1024])
    o.flush()
    time.sleep(0.3)
    o.write(b[i + 1024:])
    o.flush()
    sys.exit(0)
os.execv(REAL, [REAL] + a)
""" % (PY, shutil.which("git")))
os.chmod(os.path.join(SLOWBIN, "git"), 0o755)
SLOWPATH = SLOWBIN + os.pathsep + os.environ.get("PATH", "")
rc, out = plan(C1, C2, PATH=SLOWPATH)
T.chk(rc != 0 and "JSON 오류 seed/s20_bad.json" in out and "rc=141" not in out and not calls(PR),
      "D06 늦은 패딩 git 대역 + D04 = 그대로 'JSON 오류' 거부(rc 141 아님)", out[-600:])
rc, out = plan(C1, C3, allow="src/_wip_s20a.py", PATH=SLOWPATH)
T.chk(rc == 0 and "목록 파일 일부 없음" not in out and "삭제 1개" in out, "D06 늦은 패딩 git 대역 + D05 허용 = plan 통과('목록 파일 일부 없음' 오판 없음)", out[-600:])

def body_of(fpath, tag="PYMARKS"):
    t = rd(fpath)
    i = t.index("<<'%s'\n" % tag) + len("<<'%s'\n" % tag)
    return t[i:t.index("\n%s\n" % tag, i)]


T.chk(body_of(LIB) == body_of(RB) and "exf_rawskip:" in body_of(LIB), "M0 롤백 사본 PYMARKS = deploy_lib 23 몸통 글자 그대로")
RCK = os.path.join(TOOLS, "rollback_check.py")
if os.path.isfile(RCK):
    import ast  # noqa: E402
    _rt = rd(RCK)
    _fn = [n for n in ast.parse(_rt).body if isinstance(n, ast.FunctionDef) and n.name == "rawskip_readers"]
    T.chk(len(_fn) == 1 and ("\n" + ast.get_source_segment(_rt, _fn[0]) + "\n") in body_of(LIB), "M0 PYMARKS 의 rawskip_readers = tools/rollback_check.py 글자 그대로")
_RD = '        return not self.conn.execute("SELECT 1 FROM meta WHERE k=?", (f"exf_rawskip:{ex}:%s:{uid}",)).fetchone()\n'
KNOWS = ("class M:\n    def _post_exf_deposit_in(self, ex, uid):\n" + _RD % "deposit"
         + "    def _post_exf_withdraw(self, ex, uid):\n" + _RD % "withdraw")
NOT_KNOWS = "def _post(self, k):\n    return False\n"
CMT_ONLY = NOT_KNOWS + '# exf_rawskip:{ex}:withdraw:{uid} 를 읽던 자리\n"exf_rawskip:"\n'
DEP_ONLY = KNOWS.replace('f"exf_rawskip:{ex}:withdraw:{uid}"', 'f"exf_unread:{ex}:withdraw:{uid}"')
WD_ONLY = KNOWS.replace('f"exf_rawskip:{ex}:deposit:{uid}"', 'f"exf_unread:{ex}:deposit:{uid}"')


def add_marks(dbp, n=2, kind="withdraw"):
    c = sqlite3.connect(dbp)
    c.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
    for i in range(n):
        c.execute("INSERT INTO meta VALUES(?, '1')", ("exf_rawskip:okx:%s:okx:m%d" % (kind, i),))
    c.execute("INSERT OR IGNORE INTO meta VALUES('exf_rawskiq', 'x')")
    c.commit()
    c.close()


def mcase(bk_core, marks=2, ledger_files=False, dep_marks=0):
    r, live, bk, ts = case(ledger_files=ledger_files)
    w(os.path.join(live, "src", "core_exf.py"), KNOWS)
    w(os.path.join(bk, "code", "src", "core_exf.py"), bk_core)
    w(os.path.join(bk, "files.txt"), "src/a.py\nsrc/core_exf.py\ntools/rollback_hotfix_20260928t.sh\n")
    w(os.path.join(bk, "installed.sha256"), "%s  src/a.py\n%s  src/core_exf.py\n%s  tools/rollback_hotfix_20260928t.sh\n"
      % (sha(b"X = 'new'\n"), sha(KNOWS.encode()), sha_file(os.path.join(live, "tools", "rollback_hotfix_20260928t.sh"))))
    if marks:
        add_marks(os.path.join(live, "state", "ledger.db"), marks)
    if dep_marks:
        add_marks(os.path.join(live, "state", "ledger.db"), dep_marks, kind="deposit")
    return r, live, bk, ts


r, live, bk, ts = mcase(NOT_KNOWS)
rc, out = rb(r, live, ts)
T.chk(rc != 0 and not calls(r) and rd(os.path.join(live, "src", "core_exf.py")) == KNOWS and rd(os.path.join(live, "src", "a.py")) == "X = 'new'\n"
      and "exf_rawskip" in out and "2개" in out and "--ledger" in out and "ledger_rowfix.py --undo" in out and not os.path.exists(os.path.join(live, ".deploy_lock")),
      "M1 표식 있는 원장 + 표식 모르는 core 로 코드 전용 롤백 = 유닛 정지 전 거부(pm2 0 · 파일 무변 · 길 안내 · 잠금 풀림)", (rc, calls(r), out[-700:]))
r, live, bk, ts = mcase(KNOWS.replace("_post", "_post2"))
rc, out = rb(r, live, ts)
T.chk(rc == 0 and rd(os.path.join(live, "src", "core_exf.py")) == KNOWS.replace("_post", "_post2") and "exf_rawskip" not in out,
      "M2 표식 아는 판으로의 코드 전용 롤백(087d6b48 꼴) = 통과", out[-500:])
r, live, bk, ts = mcase(NOT_KNOWS, marks=0)
rc, out = rb(r, live, ts)
T.chk(rc == 0 and rd(os.path.join(live, "src", "core_exf.py")) == NOT_KNOWS, "M3 표식 없는 원장 = 옛 판 코드 전용 롤백 통과(과잉 거부 없음)", out[-500:])
r, live, bk, ts = mcase(NOT_KNOWS)
rc, out = rb(r, live, ts, "--force-code-only")
T.chk(rc == 0 and rd(os.path.join(live, "src", "core_exf.py")) == NOT_KNOWS and "--force-code-only" in out and "ledger_rowfix.py --undo" in out,
      "M4 --force-code-only = 경고 뒤 진행", out[-500:])
r, live, bk, ts = mcase(NOT_KNOWS, ledger_files=True)
rc, out = rb(r, live, ts, "--ledger")
T.chk(rc == 0 and mark(os.path.join(live, "state", "ledger.db")) == "SNAP" and rd(os.path.join(live, "src", "core_exf.py")) == NOT_KNOWS,
      "M5 --ledger = 원장째 배포 정지 시점(표식 없음)으로 진행", out[-500:])
for bk_core, dm, want, why in ((CMT_ONLY, 0, 1, "주석·홀로 선 글자열만"), (DEP_ONLY, 0, 1, "입금 reader 만 + 출금 표식"),
                               (WD_ONLY, 0, 0, "출금 reader 만 + 출금 표식만"), (WD_ONLY, 1, 1, "출금 reader 만 + 입금·출금 표식")):
    T.chk("exf_rawskip:" in bk_core, "M7 (대조) %s = 옛 검사('exf_rawskip:' 글자 있음)는 통과시켰을 꼴" % why)
    r, live, bk, ts = mcase(bk_core, dep_marks=dm)
    rc, out = rb(r, live, ts)
    if want:
        T.chk(rc != 0 and not calls(r) and rd(os.path.join(live, "src", "core_exf.py")) == KNOWS and "롤백 거부" in out and "exf_rawskip" in out,
              "M7 %s = 코드 전용 롤백 거부(pm2 0 · 파일 무변)" % why, (rc, calls(r), out[-600:]))
    else:
        T.chk(rc == 0 and rd(os.path.join(live, "src", "core_exf.py")) == bk_core and "롤백 거부" not in out, "M7 %s = 통과" % why, out[-500:])


def rvcase(bk_rev, changed=True, led="2"):
    r, live, bk, ts = mcase(KNOWS, marks=0)
    w(os.path.join(live, "src", "db.py"), "DATA_REV = 2\n")
    w(os.path.join(bk, "code", "src", "db.py"), "DATA_REV = %d\n" % bk_rev)
    if changed:
        w(os.path.join(bk, "files.txt"), rd(os.path.join(bk, "files.txt")) + "src/db.py\n")
        w(os.path.join(bk, "installed.sha256"), rd(os.path.join(bk, "installed.sha256")) + "%s  src/db.py\n" % sha(b"DATA_REV = 2\n"))
    c9 = sqlite3.connect(os.path.join(live, "state", "ledger.db"))
    c9.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
    c9.execute("INSERT INTO meta VALUES('data_rev', ?)", (led,))
    c9.commit()
    c9.close()
    return r, live, bk, ts


r, live, bk, ts = rvcase(1)
rc, out = rb(r, live, ts)
T.chk(rc != 0 and not calls(r) and rd(os.path.join(live, "src", "db.py")) == "DATA_REV = 2\n" and "data_rev" in out and "--undo-autofix" in out,
      "M8 원장 data_rev 2 + 되돌린 뒤 db.py DATA_REV 1 = 코드 전용 롤백 거부(유닛 정지 전 · 파일 무변 · 길 안내)", (rc, calls(r), out[-600:]))
r, live, bk, ts = rvcase(1)
rc, out = rb(r, live, ts, "--force-code-only")
T.chk(rc != 0 and not calls(r) and "data_rev" in out and "--force-code-only 로도" in out, "M8 data_rev 불일치 = --force-code-only 로도 거부", (rc, out[-400:]))
r, live, bk, ts = rvcase(2)
rc, out = rb(r, live, ts)
T.chk(rc == 0 and "data_rev" not in out, "M8 되돌린 뒤 db.py 도 DATA_REV 2 = 통과(과잉 거부 없음)", out[-400:])
r, live, bk, ts = rvcase(2, led="3")
rc, out = rb(r, live, ts)
T.chk(rc != 0 and not calls(r) and "data_rev" in out and "--upbit-split-down --apply --backup-now" in out and "--undo-autofix" not in out,
      "M8 원장 data_rev 3(업비트 분할 체결) + 되돌린 뒤 DATA_REV 2 = 거부 · 안내 = 분할 내리기 한 줄(자동 처리 되돌리기 없음)", (rc, out[-600:]))
r, live, bk, ts = rvcase(1, led="3")
rc, out = rb(r, live, ts)
T.chk(rc != 0 and "--upbit-split-down" in out and "--undo-autofix" in out and out.index("--upbit-split-down") < out.index("--undo-autofix"),
      "M8 원장 data_rev 3 + 되돌린 뒤 DATA_REV 1 = 거부 · 안내 = 분할 내리기 → 자동 처리 되돌리기 차례", out[-600:])
add_marks(os.path.join(PL, "state", "ledger.db"))
git("checkout", "-q", "-b", "m6a", C1)
with open(os.path.join(G, "src", "core_exf.py")) as f:
    ce = f.read()
T.chk("exf_rawskip:" in ce, "M6 (전제) 이 트리 core_exf.py 는 표식을 읽음")
with open(os.path.join(G, "src", "core_exf.py"), "w") as f:
    f.write(ce.replace("exf_rawskip:", "exf_unread:"))
git("add", "-A")
git("commit", "-qm", "m6a")
C4 = git("rev-parse", "HEAD")
rc, out = plan(C1, C4, HOTFIXT_FUTPLACE_AUTO="1")
T.chk(rc != 0 and "배포 거부" in out and "exf_rawskip" in out and not calls(PR), "M6 배포 plan: 깔 core 가 표식을 모름 = 거부 · pm2 정지 0", out[-600:])
git("checkout", "-q", "-b", "m6c", C1)
with open(os.path.join(G, "src", "core_exf.py"), "w") as f:
    f.write(ce.replace('f"exf_rawskip:{ex}:withdraw:{uid}"', 'f"exf_unread:{ex}:withdraw:{uid}"'))
git("add", "-A")
git("commit", "-qm", "m6c")
C6 = git("rev-parse", "HEAD")
T.chk(ce.count('f"exf_rawskip:{ex}:withdraw:{uid}"') == 1, "M6 (전제) 이 트리 core_exf.py 출금 reader 열쇠 1곳")
rc, out = plan(C1, C6, HOTFIXT_FUTPLACE_AUTO="1")
T.chk(rc != 0 and "배포 거부" in out and "출금" in out and not calls(PR), "M6 배포 plan: 출금 reader 만 뺀 판(입금 reader·주석은 남음) = 거부", out[-600:])
git("checkout", "-q", "-b", "m6b", C1)
with open(os.path.join(G, "src", "web.py"), "a") as f:
    f.write("\n# m6b\n")
git("add", "-A")
git("commit", "-qm", "m6b")
C5 = git("rev-parse", "HEAD")
rc, out = plan(C1, C5)
T.chk(rc == 0 and "배포 거부" not in out, "M6 배포 plan: 표식 아는 판(core 무변) = 통과", out[-600:])
T.finish()
