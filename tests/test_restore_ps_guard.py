#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402

import paths  # noqa: E402
import db as dbm  # noqa: E402

chk = T.chk
S = paths.STATE_DIR
os.makedirs(S, exist_ok=True)
with open(paths.CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump({"chains": {}, "wallets": []}, f)
os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
TOOLS = os.path.join(T.ROOT, "tools")
SHIM = os.path.join(T.TMP, "shim")
os.makedirs(SHIM, exist_ok=True)
PROBE = ("import sys; sys.path.insert(0, sys.argv[1]); import ledger_restore as LR; r = LR.running_units(); "
         "print('NONE' if r is None else 'LIST %d' % len(r))")


def fake_ps(body):
    with open(os.path.join(SHIM, "ps"), "w") as f:
        f.write("#!/bin/sh\n" + body)
    os.chmod(os.path.join(SHIM, "ps"), 0o755)


def env(shim):
    e9 = {k: v for k, v in os.environ.items() if not k.startswith("TJ_") or k.startswith("TJ_TEST_")}
    e9["TJ_BASE"] = T.TMP
    if shim:
        e9["PATH"] = SHIM + os.pathsep + os.environ.get("PATH", "")
    return e9


def units(body):
    if body is not None:
        fake_ps(body)
    r9 = subprocess.run([sys.executable, "-c", PROBE, TOOLS], capture_output=True, text=True, timeout=60, env=env(body is not None))
    return (r9.stdout.strip().splitlines() or ["?"])[-1]


modes = {"종료값 1 · 빈 출력": "echo 'synthetic ps failed' >&2\nexit 1\n", "종료값 0 · 빈 출력": "exit 0\n",
         "종료값 0 · 해석 불가 출력": "echo 'garbage line'\necho 'more'\nexit 0\n", "종료값 2 · 정상 꼴 출력": "echo \"$PPID python3\"\nexit 2\n"}
got = {k: units(v) for k, v in modes.items()}
chk(all(v == "NONE" for v in got.values()), "P1 ps 비정상 종료·빈 출력·해석 불가 = 확인 불가(None — 빈 목록 아님)", got)
chk(units("echo \"$PPID python3 tkj.py\"\nexit 0\n") == "LIST 0", "P1 정상 꼴(자기 자신이 보이는 출력 · 유닛 없음) = 빈 목록(대조)")
chk(units(None).startswith("LIST"), "P1 진짜 ps = 목록(대조)", units(None))

live = paths.DB_PATH
c = dbm.open_db(live)
c.execute("INSERT OR REPLACE INTO meta(k, v) VALUES('tkj_tag', 'backup')")
c.commit()
BK = os.path.join(S, "bk_ps.db")
b9 = sqlite3.connect(BK)
c.backup(b9)
b9.execute("PRAGMA journal_mode=DELETE").fetchone()
b9.close()
c.execute("UPDATE meta SET v='live' WHERE k='tkj_tag'")
c.commit()
c.close()


def tag():
    with sqlite3.connect(live) as c9:
        return c9.execute("SELECT v FROM meta WHERE k='tkj_tag'").fetchone()[0]


fake_ps("exit 1\n")
r = subprocess.run([sys.executable, os.path.join(TOOLS, "ledger_restore.py"), "restore", BK, "--apply"], capture_output=True, text=True, timeout=120, env=env(True))
chk(r.returncode != 0 and "ps" in (r.stderr + r.stdout) and tag() == "live", "P2 restore --apply + ps 실패(종료값 1 · 빈 출력) = 거부 · 원장 그대로",
    (r.returncode, r.stdout[-300:], r.stderr[-300:]))
r = subprocess.run([sys.executable, os.path.join(TOOLS, "ledger_restore.py"), "restore", BK, "--apply", "--no-proc-check"], capture_output=True, text=True,
                   timeout=120, env=env(True))
chk(r.returncode == 0 and tag() == "backup", "P2 명시 우회(--no-proc-check · 정지를 직접 확인) = 적용(자동 판정과 구분)", (r.returncode, r.stderr[-300:]))
chk(not T.NET_TRIES, "바깥 연결 0", T.NET_TRIES)
T.finish()
