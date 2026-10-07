#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import os
import sqlite3
import subprocess

import core

P = os.path.join(T.TMP, "ledger.db")


def ck(name, cond):
    T.chk(bool(cond), name)


code = r'''
import sqlite3, sys, os
p = sys.argv[1]
c = sqlite3.connect(p); c.execute("PRAGMA journal_mode=WAL"); c.execute("CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT)")
c.execute("INSERT INTO meta VALUES('rebuild_incomplete','1'),('x','1')"); c.commit()
ro = sqlite3.connect("file:%s?mode=ro" % p, uri=True); ro.execute("SELECT count(*) FROM meta").fetchone()
f = sqlite3.connect(p); f.execute("DELETE FROM meta WHERE k='rebuild_incomplete'"); f.commit(); f.close()
os._exit(0)
'''
subprocess.run([sys.executable, "-c", code, P], check=True)
w = P + "-wal"
ck("재현: 다른 연결이 열린 채 끝나면 WAL 이 남는다(수정 전 = 'shadow WAL 미체크포인트' 실패)", os.path.exists(w) and os.path.getsize(w) > 0)
ok = core.Core._ext_wal_settle(P)
ck("정리 반환 True", ok is True)
ck("정리 뒤 WAL 비었음(검사 통과)", not (os.path.exists(w) and os.path.getsize(w) > 0))
c = sqlite3.connect("file:%s?mode=ro" % P, uri=True)
ck("마지막 커밋 보존(마커 지워짐)", c.execute("SELECT count(*) FROM meta WHERE k='rebuild_incomplete'").fetchone()[0] == 0)
ck("다른 행 보존", c.execute("SELECT v FROM meta WHERE k='x'").fetchone()[0] == "1")
ck("저널 모드 WAL 유지(성공하던 재구축과 같은 원장 머리)", c.execute("PRAGMA journal_mode").fetchone()[0] == "wal")
ck("무결성", c.execute("PRAGMA integrity_check").fetchone()[0] == "ok")
c.close()
P2 = os.path.join(T.TMP, "plain.db"); c2 = sqlite3.connect(P2); c2.execute("CREATE TABLE t(a)"); c2.commit(); c2.close()
ck("WAL 없으면 True·파일 무변", core.Core._ext_wal_settle(P2) is True and not os.path.exists(P2 + "-wal"))
P3 = os.path.join(T.TMP, "busy.db")
holder = subprocess.Popen([sys.executable, "-c", r'''
import sqlite3, sys, time
p = sys.argv[1]
c = sqlite3.connect(p, isolation_level=None); c.execute("PRAGMA journal_mode=WAL"); c.execute("CREATE TABLE t(a)")
for i in range(50): c.execute("INSERT INTO t VALUES(?)", (i,))
r = sqlite3.connect(p, isolation_level=None); r.execute("BEGIN"); r.execute("SELECT count(*) FROM t").fetchone()
c.execute("INSERT INTO t VALUES(99)")
print("ready", flush=True); time.sleep(30)
''', P3], stdout=subprocess.PIPE, text=True)
holder.stdout.readline()
try:
    r3 = core.Core._ext_wal_settle(P3)
    ck("읽기 스냅샷이 쥐고 있어 다 못 합치면 False(검사가 실패로 처리)", r3 is False)
finally:
    holder.kill(); holder.wait()
T.finish()
