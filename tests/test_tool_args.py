#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import os
import subprocess

chk = T.chk
FAKE = os.path.join(T.TMP, "pm2")


def pm2(online):
    with open(FAKE, "w") as fh:
        fh.write("#!/bin/sh\necho '" + ('[{"name": "tj-core", "pm2_env": {"status": "online"}}]' if online else "[]") + "'\n")
    os.chmod(FAKE, 0o755)


def tool(name, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_") or k.startswith("TJ_TEST_")}
    env.update(TJ_BASE=T.TMP, PM2_BIN=FAKE, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, os.path.join(T.ROOT, "tools", name)] + list(args), env=env, capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


pm2(False)
st0 = sorted(os.listdir(os.path.join(T.TMP, "state")))
for name in ("exf_fut_place.py", "latefix_move.py"):
    rc, out = tool(name, "-h")
    chk(rc == 0 and "usage:" in out and "Traceback" not in out, f"A1 {name} -h = 사용법만(원장 없이 · 오류 없음)", out[-300:])
    rc, out = tool(name, "--apply", "--help")
    chk(rc == 0 and "usage:" in out and "Traceback" not in out, f"A2 {name} --apply --help = 사용법만(적용 안 함)", out[-300:])
    rc, out = tool(name, "--bogus")
    chk(rc == 2 and "usage:" in out, f"A3 {name} 모르는 옵션 = 거부(rc 2)", out[-200:])
    rc, out = tool(name, "--undo")
    chk(rc == 2 and "Traceback" not in out and "usage:" in out, f"A4 {name} --undo 경로 없음 = 사용법 오류(종전 IndexError)", out[-200:])
rc, out = tool("exf_fut_place.py", "--expect", "x.json")
chk(rc == 2 and "--apply" in out, "A5 exf_fut_place.py --expect 는 --apply 와 같이만", out[-200:])
for name in ("exf_fut_place.py", "latefix_move.py"):
    rc, out = tool(name, "--apply")
    chk(rc == 1 and "원장 없음" in out, f"A8 {name} 원장 없는 곳에 --apply = 거부(빈 원장을 만들지 않음)", out[-200:])
import sqlite3
sqlite3.connect(os.path.join(T.TMP, "state", "ledger.db")).close()
st0 = sorted(os.listdir(os.path.join(T.TMP, "state")))
pm2(True)
for name in ("exf_fut_place.py", "latefix_move.py"):
    rc, out = tool(name, "--apply")
    chk(rc == 1 and "거부" in out and "tj-core" in out, f"A6 {name} --apply · pm2 에 tj-core 가 떠 있음 = 거부(rc 1)", out[-300:])
chk(sorted(os.listdir(os.path.join(T.TMP, "state"))) == st0, "A7 state 무변(원장·되돌리기 파일 안 생김)", sorted(os.listdir(os.path.join(T.TMP, "state"))))
T.finish()
