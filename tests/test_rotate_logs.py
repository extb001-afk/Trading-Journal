#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import os
import shutil
import subprocess
import time

ROT = os.path.join(T.ROOT, "tools", "rotate_logs.sh")
SETUP = next((p for p in (os.path.join(T.ROOT, "tools", "setup.sh"), os.path.join(T.ROOT, "public", "tools", "setup.sh")) if os.path.isfile(p)), None)


def ck(name, cond, extra=None):
    T.chk(bool(cond), name, extra)


st = open(SETUP, encoding="utf-8").read() if SETUP else ""
ck("[1] setup.sh pm2 없는 로그 예시 = 덧붙이기(>> … 2>&1)", ">> ~/tj-logs/tj-web.log 2>&1" in st and "'... > ~/tj-logs" not in st, SETUP)
ck("[1] setup.sh pm2 없는 목록에 감시 유닛(alert_bot) · 멈추는 법", "src/alert_bot.py" in st and "Ctrl+C" in st)
bash = shutil.which("bash")
if bash:
    h = subprocess.run([bash, ROT, "-h"], capture_output=True, text=True, timeout=30).stdout
    ck("[1] rotate_logs.sh -h = '덧붙이기(>>)로 열어야'", "덧붙이기" in h and ">>" in h, h[-400:])
    D = os.path.join(T.TMP, "tj-logs")
    os.makedirs(D)
    WR = r'''
import os, sys, time
p, mode = sys.argv[1], sys.argv[2]
fd = os.open(p, os.O_WRONLY | os.O_CREAT | (os.O_APPEND if mode == "append" else os.O_TRUNC), 0o600)
os.write(fd, b"x" * (11 * 1024 * 1024))   # 상한(10MB)을 넘긴 상태에서 시작
open(p + ".ready", "w").close()
t0 = time.time()
while time.time() - t0 < 12:
    os.write(fd, b"line\n" * 20)
    time.sleep(0.05)
'''

    def run_case(mode):
        f = os.path.join(D, f"tj-{mode}.log")
        pr = subprocess.Popen([sys.executable, "-c", WR, f, mode])
        try:
            for _ in range(200):
                if os.path.exists(f + ".ready"):
                    break
                time.sleep(0.05)
            r = subprocess.run([bash, ROT, "--max-mb", "10", "--keep-mb", "1", D], capture_output=True, text=True, timeout=60)
            time.sleep(5)
            return os.path.getsize(f), r.stdout
        finally:
            pr.kill()
            pr.wait()
            for x in (f, f + ".1", f + ".ready"):
                if os.path.exists(x):
                    os.remove(x)
    sz, out = run_case("append")
    ck("[2] 덧붙이기(>>)로 쓰는 프로세스 → 회전 5초 뒤 크기 < 상한(10MB)", sz < 10 * 1024 * 1024 and "잘랐음" in out, (sz, out))
    sz, out = run_case("trunc")
    ck("[3] '>' 로 연 프로세스 → 자른 뒤에도 크기 그대로(그래서 안내는 >>)", sz >= 10 * 1024 * 1024, (sz, out))
else:
    print("bash 없음 — [1] rotate -h · [2] · [3] 건너뜀")
T.finish()
