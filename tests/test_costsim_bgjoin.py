#!/usr/bin/env python3
import json
import os
import subprocess
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

chk = T.chk
DELAY = "0.3"
SLOW = r'''
import os, sys, threading, time
sys.dont_write_bytecode = True
import _harness
import db
_o = db.open_db
SEEN = []
def slow_open(path, readonly=False):
    c = _o(path, readonly=readonly)
    if readonly and threading.current_thread().name == "rawfrom-worker":
        SEEN.append(1)
        time.sleep(float(os.environ["BGJ_DELAY"]))   # 느린 기계 흉내: 연 뒤 첫 읽기 전에 쉼(그사이 주 스레드가 reset)
    return c
db.open_db = slow_open
'''
B1 = SLOW + r'''
import json, web
import _costsim as S
_ob = web.StateBuilder._build
def _build_with_from(self, conn, *a, **k):
    out = _ob(self, conn, *a, **k)
    self._rtxc().from_counts(conn)   # 발신자 건수 첫 계산 = 배경 스레드(제품 빌드가 모르는 출금 주소가 있을 때 하는 일)
    return out
web.StateBuilder._build = _build_with_from
S.reset()
S.build()
alive = [t.name for t in threading.enumerate() if t.name == "rawfrom-worker" and t.is_alive()]
print("BGJ1 " + json.dumps({"seen": len(SEEN), "alive": alive}), flush=True)
'''
B2 = SLOW + r'''
import runpy
runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(_harness.__file__)), "test_cost_known_paths.py"), run_name="__main__")
'''
here = os.path.dirname(os.path.abspath(__file__))
env = dict(os.environ, PYTHONPATH=here + os.pathsep + os.environ.get("PYTHONPATH", ""), PYTHONDONTWRITEBYTECODE="1", PYTHONFAULTHANDLER="1", BGJ_DELAY=DELAY)
env.pop("TJ_BASE", None)


def child(code):
    return subprocess.run([sys.executable, "-c", code], cwd=here, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600)


p = child(B1)
got = next((json.loads(s9[5:]) for s9 in p.stdout.splitlines() if s9.startswith("BGJ1 ")), None)
chk(p.returncode == 0 and got is not None and got["seen"] and not got["alive"],
    "B1 build() 가 돌려줄 때 배경 원장 읽기 스레드 끝남(늦춰도) · 대조: 스레드가 실제로 떴음", {"rc": p.returncode, "got": got})
p = child(B2)
summ = [s9 for s9 in p.stdout.splitlines() if s9.startswith(("결과:", "Fatal Python error"))]
chk(p.returncode == 0 and any(s9.startswith("결과:") and " 0 FAIL" in s9 for s9 in summ),
    "B2 배경 읽기를 늦춘 test_cost_known_paths 전체 = 신호 없이 끝남 · FAIL 0(종전 SIGBUS · Core.__init__ → open_db)", {"rc": p.returncode, "summary": summ})
T.finish()
