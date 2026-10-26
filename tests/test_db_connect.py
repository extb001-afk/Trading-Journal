#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402

sys.path.insert(0, T.SRC)
import db  # noqa: E402

chk = T.chk
TMP = os.path.join(T.TMP, "dbc")
os.makedirs(TMP, exist_ok=True)
DBF = os.path.join(TMP, "x #1.db")
c0 = sqlite3.connect(DBF)
c0.execute("CREATE TABLE t (x)")
c0.execute("INSERT INTO t VALUES (1)")
c0.commit()
c0.close()

import threading  # noqa: E402
import time  # noqa: E402
c = db.connect(":memory:", 7, check_same_thread=False, isolation_level=None)
th = []
t9 = threading.Thread(target=lambda: th.append(c.execute("SELECT 1").fetchone()[0]))
t9.start()
t9.join()
r1 = (c.isolation_level, th)
c.close()
chk(r1 == (None, [1]), "C1 db.connect 위치·이름 인자 그대로(isolation_level=None · check_same_thread=False → 다른 스레드에서 씀)", r1)
w9 = sqlite3.connect(DBF, timeout=0)
w9.execute("BEGIN EXCLUSIVE")
try:
    t0 = time.monotonic()
    try:
        c = db.open_ro(DBF, timeout=0.2)
        c.execute("SELECT x FROM t").fetchone()
        locked = False
    except sqlite3.OperationalError as e:
        locked = "locked" in str(e)
    dt = time.monotonic() - t0
    c = db.open_ro(DBF, immutable=True)
    n1 = c.execute("SELECT x FROM t").fetchone()[0]
    c.close()
finally:
    w9.rollback()
    w9.close()
chk(locked and dt < 5 and n1 == 1, "C1 open_ro(timeout=0.2) = 잠금 대기 짧게 실패(%.1f초) · open_ro(immutable=True) = 잠금 없이 읽음(# 든 경로 인용)" % dt,
    (locked, round(dt, 2), n1))

PROBE = os.path.join(TMP, "probe_site.py")
with open(PROBE, "w", encoding="utf-8") as f:
    f.write('''import json, logging, sqlite3, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
msgs = []
class H(logging.Handler):
    def emit(self, r):
        msgs.append(r.getMessage())
logging.getLogger().addHandler(H())
logging.getLogger().setLevel(logging.INFO)
import buildproc, db
buildproc._warn_new_sqlite()
dbf = sys.argv[2]
for i in range(2):
    db.connect(":memory:").close()
db.open_ro(dbf).close()
db.open_db(dbf, readonly=True).close()
sqlite3.connect(":memory:").close()
print("JSON " + json.dumps(msgs, ensure_ascii=False))
''')
env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_") or k.startswith("TJ_TEST_")}
env["TJ_BASE"] = os.path.join(TMP, "base")
os.makedirs(os.path.join(env["TJ_BASE"], "state"), exist_ok=True)
p = subprocess.run([sys.executable, "-B", PROBE, T.SRC, DBF], capture_output=True, text=True, timeout=120, env=env)
js = [x for x in p.stdout.splitlines() if x.startswith("JSON ")]
msgs = json.loads(js[-1][5:]) if js else ["rc=%s %s" % (p.returncode, (p.stdout + p.stderr)[-600:])]
sites = [m.split("(", 1)[1].split(")", 1)[0] for m in msgs if "새 SQLite 연결" in m]
chk(sites == ["probe_site.py:14", "probe_site.py:15", "probe_site.py:16", "probe_site.py:17"],
    "C2 빌드 자식 차단점: db.connect(2번 = 한 줄)·open_ro·open_db(readonly)·직접 연결이 부른 자리(파일:줄)로 기록 · db.py 0", msgs)

bad, from_imp, conn_body = [], [], None
for dp, dn, fn in os.walk(T.SRC):
    dn[:] = [d for d in dn if d != "__pycache__"]
    for nm in fn:
        if not nm.endswith(".py"):
            continue
        fp = os.path.join(dp, nm)
        rel = os.path.relpath(fp, T.SRC)
        tree = ast.parse(open(fp, encoding="utf-8").read())
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "connect" and isinstance(n.func.value, ast.Name) \
                    and n.func.value.id in ("sqlite3", "_s9") and rel not in ("db.py", "runtime.py"):
                bad.append("%s:%d" % (rel, n.lineno))
            if isinstance(n, ast.ImportFrom) and n.module == "sqlite3" and any(a.name in ("connect", "*") for a in n.names):
                from_imp.append("%s:%d" % (rel, n.lineno))
            if rel == "db.py" and isinstance(n, ast.FunctionDef) and n.name == "connect":
                conn_body = ast.dump(n.body[-1])
dbx = [f for f in os.listdir(T.SRC) if f.startswith("db_") and f.endswith(".py")]
chk(not bad and not from_imp and not dbx, "C3 src 의 sqlite3.connect = db.py·runtime.py 만 · from sqlite3 import connect 0 · db_*.py 0", (bad, from_imp, dbx))
want = ast.dump(ast.parse("return sqlite3.connect(*args, **kwargs)").body[0])
chk(conn_body == want, "C3 db.connect 몸통 = return sqlite3.connect(*args, **kwargs)(속성 조회 — 호출 시점)")

c = db.open_ro(DBF)
try:
    c.execute("INSERT INTO t VALUES (2)")
    ro = False
except sqlite3.OperationalError as e:
    ro = "readonly" in str(e)
c.close()
c = db.open_db(DBF, readonly=True)
r4 = (c.row_factory is sqlite3.Row, c.execute("SELECT count(*) FROM t").fetchone()[0])
c.close()
chk(ro and r4 == (True, 1), "C4 open_ro 쓰기 거부(readonly) · open_db(readonly) = open_ro + Row", (ro, r4))
T.finish()
