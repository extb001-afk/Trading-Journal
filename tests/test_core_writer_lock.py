#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import os  # noqa: E402
import subprocess  # noqa: E402

import runtime  # noqa: E402
import core  # noqa: E402

chk = T.chk
db9 = os.path.join(T.TMP, "wl", "ledger.db")
os.makedirs(os.path.dirname(db9), exist_ok=True)
lockp = os.path.join(os.path.dirname(db9), "core_writer.lock")

fd = core.writer_lock(db9)
chk(os.path.exists(lockp) and (os.stat(lockp).st_mode & 0o777) == 0o600, "L1 잠금 파일 위치·권한", oct(os.stat(lockp).st_mode & 0o777) if os.path.exists(lockp) else None)

probe = ("import fcntl,os,sys\nfd=os.open(sys.argv[1],os.O_RDWR)\n"
         "try:\n    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);print('got')\nexcept OSError:\n    print('busy')\n")
r = subprocess.run([sys.executable, "-I", "-c", probe, lockp], capture_output=True, text=True, timeout=20)
chk(r.stdout.strip() == "busy", "L2 잠근 동안 다른 프로세스 = 잠금 못 잡음", r.stdout + r.stderr)

os.close(fd)
core._WRITER_LOCK.clear()
r = subprocess.run([sys.executable, "-I", "-c", probe, lockp], capture_output=True, text=True, timeout=20)
chk(r.stdout.strip() == "got", "L3 쥔 쪽 종료 뒤 = 다음 core 가 잡음", r.stdout + r.stderr)

import ledger_backup  # noqa: E402
ev = ledger_backup.prior_ledger_evidence(state_dir=os.path.dirname(db9), db_path=db9)
chk(not any("core_writer" in e for e in ev), "L4 잠금 파일 ≠ 예전 원장 흔적", ev)

os.environ.pop("TJ_RUNNER_PID", None)
chk(runtime.parent_watch_start() is False, "L5a 러너 밖 = 감시 안 함")
os.environ["TJ_RUNNER_PID"] = str(os.getpid())
chk(runtime.parent_watch_start() is False, "L5b 부모 pid 불일치 = 감시 안 함")
os.environ.pop("TJ_RUNNER_PID", None)

kid = ("import sys,time\nsys.path.insert(0,sys.argv[1])\nimport runtime\n"
       "ok=runtime.parent_watch_start(every=0.2)\nprint('watch',ok,flush=True)\n"
       "try:\n    time.sleep(30)\nexcept KeyboardInterrupt:\n    print('stopped',flush=True)\n")
mid = ("import os,subprocess,sys\nenv=dict(os.environ,TJ_RUNNER_PID=str(os.getpid()))\n"
       "p=subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]],env=env,stdout=open(sys.argv[3],'w'),stderr=subprocess.DEVNULL,stdin=subprocess.DEVNULL)\n"
       "import time\ntime.sleep(1.0)\nprint(p.pid,flush=True)\n")
outp = os.path.join(T.TMP, "wl", "kid.out")
r = subprocess.run([sys.executable, "-c", mid, kid, T.SRC, outp], capture_output=True, text=True, timeout=20,
                   preexec_fn=T.sigint_default)
import time  # noqa: E402
txt = ""
for _ in range(50):
    time.sleep(0.2)
    txt = open(outp).read() if os.path.exists(outp) else ""
    if "stopped" in txt:
        break
chk("watch True" in txt and "stopped" in txt, "L6 부모(러너) 사라짐 → 자식 스스로 종료", txt)

mid2 = mid.replace("import time\ntime.sleep(1.0)\n", "")
kid2 = ("import os,sys,time\nsys.path.insert(0,sys.argv[1])\nimport runtime\n"
        "try:\n    runtime.parent_watch_start(every=0.2)\n    time.sleep(30)\nexcept KeyboardInterrupt:\n"
        "    print('stopped','env' if os.environ.get('TJ_RUNNER_PID') else 'noenv',flush=True)\n")
outp2 = os.path.join(T.TMP, "wl", "kid2.out")
subprocess.run([sys.executable, "-c", mid2, kid2, T.SRC, outp2], capture_output=True, text=True, timeout=20,
               preexec_fn=T.sigint_default)
txt = ""
for _ in range(50):
    time.sleep(0.2)
    txt = open(outp2).read() if os.path.exists(outp2) else ""
    if "stopped" in txt:
        break
chk("stopped" in txt and "noenv" in txt, "L6b 부모 이미 없음 → 종료 · env 손자 미전달", txt)

import unit_runner as UR  # noqa: E402
p = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"])
UR._live["p"] = p
_orig = UR._main
UR._main = lambda: (_ for _ in ()).throw(RuntimeError("러너 예외"))
try:
    UR.main()
except RuntimeError:
    pass
UR._main = _orig
chk(p.poll() is not None, "L7 러너 예외 종료 = 자식 정리", p.poll())

T.finish()
