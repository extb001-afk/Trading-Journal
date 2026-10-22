#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import fcntl  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

chk = T.chk
OFF = os.path.join(T.ROOT, "tools", "offsite_backup.py")
LIB = os.path.join(T.ROOT, "tools", "deploy_lib.sh")
TREE = os.path.join(T.TMP, "tree")
BASE = os.path.join(T.TMP, "base")
LOCKF = os.path.join(TREE, ".deploy.lock")
STAMP, SHA = "tjoff_20261001_0000", "ab" * 32
STATUS = os.path.join(BASE, "state", "backups", "offsite_status.json")
ENV0 = {k: v for k, v in os.environ.items() if not k.startswith("TJ_") or k.startswith("TJ_TEST_")}
ENV0["TJ_BASE"] = BASE


def status():
    try:
        with open(STATUS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


class Hold:
    def __init__(self, path, kind=fcntl.LOCK_EX):
        self.fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(self.fd, kind)

    def release(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def off(*args, wait=None, timeout=120):
    e = dict(ENV0)
    if wait is not None:
        e["TJ_DEPLOY_BARRIER_WAIT"] = str(wait)
    t0 = time.time()
    p = subprocess.run([sys.executable, os.path.join(TREE, "tools", "offsite_backup.py")] + list(args), capture_output=True, text=True,
                       timeout=timeout, env=e)
    return p.returncode, p.stdout + p.stderr, time.time() - t0


if not os.path.isfile(OFF):
    print("SKIP tools/offsite_backup.py 없음 — O 절 건너뜀")
else:
    os.makedirs(os.path.join(TREE, "tools"), exist_ok=True)
    shutil.copy2(OFF, os.path.join(TREE, "tools", "offsite_backup.py"))
    if os.path.isfile(os.path.join(T.ROOT, "tools", "offsite_seal.py")):
        shutil.copy2(os.path.join(T.ROOT, "tools", "offsite_seal.py"), os.path.join(TREE, "tools", "offsite_seal.py"))
    os.symlink(T.SRC, os.path.join(TREE, "src"))
    od = os.path.join(BASE, "state", "backups", "offsite")
    os.makedirs(od, exist_ok=True)
    with open(os.path.join(od, STAMP + ".manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"stamp": STAMP, "created": 1759276800, "db": {"sha256": SHA, "size": 10, "raw_size": 20}}, f)

    h = Hold(LOCKF)
    e1 = dict(ENV0)
    p = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import offsite_backup as O; print('ok', O.EX_TEMPFAIL)",
                        os.path.join(TREE, "tools")], capture_output=True, text=True, timeout=60, env=e1)
    chk(p.returncode == 0 and "ok 75" in p.stdout, "O1 모듈로 import = 잠금 안 잡음(배포 중에도 바로)", (p.returncode, p.stdout[-300:], p.stderr[-300:]))
    rc, out, dt = off("--help", wait=30)
    chk(rc == 0 and dt < 20, "O1 도움말 = 잠금 안 잡음", (rc, round(dt, 1)))

    rc, out, dt = off("run", wait=30)
    chk(rc == 0 and "배포 중" in out and "건너뜀" in out and dt < 20 and status() is None,
        "O2 배포 중 run = 건너뜀 rc 0 · 기다리지 않음 · 상태 파일 무변", (rc, out[-300:], round(dt, 1), status()))

    rc, out, dt = off("confirm", STAMP, SHA, wait=2)
    chk(rc == 75 and dt >= 2 and status() is None, "O3 배포 중 confirm = 대기 상한(2초) 뒤 rc 75 · 확인 상태 무변", (rc, out[-300:], round(dt, 1), status()))

    e4 = dict(ENV0, TJ_DEPLOY_BARRIER_WAIT="60")
    pr = subprocess.Popen([sys.executable, os.path.join(TREE, "tools", "offsite_backup.py"), "confirm", STAMP, SHA], stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, env=e4)
    time.sleep(2)
    waiting = pr.poll() is None
    h.release()
    try:
        out4, _ = pr.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        pr.kill()
        out4, _ = pr.communicate()
    st = status() or {}
    chk(waiting and pr.returncode == 0 and "확인됨" in out4 and st.get("confirmed_stamp") == STAMP and st.get("last_ok") == 1759276800,
        "O4 confirm 이 기다리다 배포가 끝나면 이어서 처리 rc 0 · 확인 상태 기록", (waiting, pr.returncode, out4[-300:], st))
    rc, out, dt = off("confirm", STAMP, SHA, wait=5)
    st2 = status() or {}
    chk(rc == 0 and "확인됨" in out and st2.get("confirmed_stamp") == STAMP and st2.get("last_ok") == 1759276800,
        "O4 같은 묶음 다시 confirm = rc 0(멱등) · 상태 그대로", (rc, out[-200:], st2))
    rc, out, dt = off("run", wait=5)
    chk(rc == 0 and "배포 중" not in out, "O4 장벽이 풀린 뒤 run = 종전 처리(이 설정 = 꺼짐 · 할 일 없음)", (rc, out[-200:]))

    if os.geteuid() == 0:
        print("SKIP 루트로 실행 — 권한 오류를 못 만듦(O5 건너뜀)")
    else:
        os.remove(LOCKF)
        os.chmod(TREE, 0o555)
        try:
            rc1, out1, _ = off("run", wait=2)
            rc2, out2, _ = off("confirm", STAMP, SHA, wait=2)
        finally:
            os.chmod(TREE, 0o755)
        chk(rc1 == 75 and rc2 == 75 and "못 엶" in out1 and "못 엶" in out2, "O5 잠금 파일을 못 엶(권한) = run·confirm 모두 rc 75(아무것도 안 함)",
            (rc1, out1[-200:], rc2, out2[-200:]))

if not os.path.isfile(LIB):
    print("SKIP tools/deploy_lib.sh 없음(공개판) — D1 건너뜀")
else:
    LIVE = os.path.join(T.TMP, "live")
    os.makedirs(LIVE, exist_ok=True)
    PROBE = ("import fcntl, os, sys\nfd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)\n"
             "try:\n    fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB); print('free')\nexcept OSError:\n    print('held')\n")
    SCRIPT = r'''
set -u
. "$1"
PY=$2; LIVE=$3; PROBE=$4
deploy_barrier_acquire "$LIVE" 1; echo "a1=$? held=$DEPLOY_BARRIER_HELD"
{ true >&9; } 2>/dev/null && echo "fd9_after_fail=open" || echo "fd9_after_fail=closed"
echo go > "$LIVE/.go"
i=0; while [ -e "$LIVE/.holder" ] && [ $i -lt 100 ]; do sleep 0.1; i=$((i + 1)); done
deploy_barrier_acquire "$LIVE" 10; echo "a2=$? held=$DEPLOY_BARRIER_HELD"
echo "probe_held=$("$PY" -c "$PROBE" "$LIVE/.deploy.lock")"
deploy_barrier_release; echo "rel=$? held=$DEPLOY_BARRIER_HELD"
echo "probe_after=$("$PY" -c "$PROBE" "$LIVE/.deploy.lock")"
deploy_barrier_acquire "$LIVE" x 2>&1; echo "a3=$?"
'''
    hold = Hold(os.path.join(LIVE, ".deploy.lock"), fcntl.LOCK_SH)
    open(os.path.join(LIVE, ".holder"), "w").close()
    pb = subprocess.Popen(["/bin/bash", "-c", SCRIPT, "_", LIB, sys.executable, LIVE, PROBE], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          env=dict(ENV0, PYTHON=sys.executable))
    t_end = time.time() + 30
    while not os.path.exists(os.path.join(LIVE, ".go")) and time.time() < t_end and pb.poll() is None:
        time.sleep(0.1)
    hold.release()
    os.remove(os.path.join(LIVE, ".holder"))
    try:
        outb, _ = pb.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        pb.kill()
        outb, _ = pb.communicate()
    outb = outb.decode("utf-8", "replace")
    kv = dict(x.split("=", 1) for x in outb.splitlines() if "=" in x and " " not in x.split("=", 1)[0])
    chk(kv.get("a1") == "1 held=0" and "못 잡음" in outb and kv.get("fd9_after_fail") == "closed",
        "D1 공유 잠금(백업 도는 중) = 대기 상한 뒤 rc 1 · fd 9 닫음(라이브 무변)", outb[-600:])
    chk(kv.get("a2") == "0 held=1" and kv.get("probe_held") == "held", "D1 풀린 뒤 잡음 · 도우미가 끝나도 셸이 fd 9 를 쥔 동안 공유 잠금 막힘", outb[-600:])
    chk(kv.get("rel") == "0 held=0" and kv.get("probe_after") == "free", "D1 deploy_barrier_release 뒤 풀림", outb[-600:])
    chk(kv.get("a3") == "1" and "0 이상 정수" in outb, "D1 대기 상한이 숫자 아님 = 거부", outb[-600:])
T.finish()
