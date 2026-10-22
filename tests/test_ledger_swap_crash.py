#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import config, histmark, paths, statefile  # noqa: E402
import ledger_backup as lb  # noqa: E402

chk = T.chk


def mkdb(path, rows, tag):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE IF NOT EXISTS t(a)")
    c.executemany("INSERT INTO t VALUES (?)", [(f"{tag}{i}",) for i in range(rows)])
    c.commit()
    c.close()


def count(path, immutable=False):
    c = sqlite3.connect(paths.sqlite_ro_uri(path, immutable=immutable), uri=True) if immutable else sqlite3.connect(path)
    try:
        return c.execute("SELECT count(*) FROM t").fetchone()[0]
    finally:
        c.close()


def wal_only_rows(path, n):
    subprocess.run([sys.executable, "-c", r'''
import os, sqlite3, sys
c = sqlite3.connect(sys.argv[1]); c.execute("PRAGMA journal_mode=WAL"); c.execute("CREATE TABLE t(a)"); c.commit()
c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
for i in range(int(sys.argv[2])): c.execute("INSERT INTO t VALUES (?)", (i,))
c.commit()
os._exit(0)
''', path, str(n)], check=True)


CRASH_SWAP = r'''
import os, sys
sys.path.insert(0, sys.argv[1])
import ledger_backup as lb
live, new, keep = sys.argv[2:5]
real = os.replace
def rep(a, b):
    if os.path.abspath(b) == os.path.abspath(live):
        os._exit(9)
    return real(a, b)
os.replace = rep
lb.swap_in(live, new, keep)
print("NO_CRASH")
'''

d = os.path.join(T.TMP, "w")
os.makedirs(d)
live, new, keep = os.path.join(d, "ledger.db"), os.path.join(d, "ledger.db.new"), os.path.join(d, "ledger.db.pre_x")
wal_only_rows(live, 5)
chk(os.path.getsize(live + "-wal") > 0 and count(live, immutable=True) == 0, "W0 (전제) 커밋 5행이 WAL 에만(본문 파일만 읽으면 0행)")
mkdb(new, 9, "n")
r = subprocess.run([sys.executable, "-c", CRASH_SWAP, T.SRC, live, new, keep], capture_output=True, text=True, timeout=60)
chk(r.returncode == 9 and "NO_CRASH" not in r.stdout, "W1 (전제) 교체 직전 강제 종료(-wal 은 이미 보존본 짝으로 옮긴 뒤)", (r.returncode, r.stdout[-200:], r.stderr[-300:]))
chk(count(live) == 5 and count(live, immutable=True) == 5, "W2 ★옛 원장 = 커밋 5행 그대로(본문 파일만 읽어도 5행 — 교체 전에 WAL 을 본문에 합침)★",
    (count(live), count(live, immutable=True)))
chk(os.path.exists(keep) and os.path.samefile(keep, live) and os.path.exists(new), "W3 교체 안 됨 = live 는 옛 원장 · 보존본 링크·새 원장 파일 남음(다시 하면 됨)")
os.remove(keep)
for sfx in ("-wal", "-shm"):
    if os.path.exists(keep + sfx):
        os.remove(keep + sfx)
res = lb.swap_in(live, new, keep)
chk(count(live) == 9 and count(keep) == 5, "W4 다시 교체 = 새 원장 · 보존본 = 옛 원장 5행", (count(live), count(keep)))

d = os.path.join(T.TMP, "b")
os.makedirs(d)
live, new, keep = os.path.join(d, "ledger.db"), os.path.join(d, "ledger.db.new"), os.path.join(d, "ledger.db.pre_b")
w = sqlite3.connect(live)
w.execute("PRAGMA journal_mode=WAL")
w.execute("CREATE TABLE t(a)")
w.commit()
w.execute("PRAGMA wal_checkpoint(TRUNCATE)")
w.execute("INSERT INTO t VALUES (1)")
w.commit()
rd = sqlite3.connect(live)
rd.execute("BEGIN")
rd.execute("SELECT count(*) FROM t").fetchone()
w.execute("INSERT INTO t VALUES (2)")
w.commit()
w.close()
mkdb(new, 3, "n")
try:
    lb.swap_in(live, new, keep, wal_timeout=0.3)
    b9 = "swapped"
except lb.SwapRefused as e:
    b9 = str(e)
chk("WAL" in b9 and not os.path.exists(keep) and os.path.exists(new) and os.path.getsize(live + "-wal") > 0,
    "B1 옛 시점을 쥔 연결 = SwapRefused(교체 안 함 · 보존본 안 만듦 · -wal 그대로)", b9)
rd.rollback()
rd.close()
lb.swap_in(live, new, keep, wal_timeout=5)
chk(count(live) == 3 and count(keep) == 2 and count(keep, immutable=True) == 2, "B2 그 연결이 끝나면 교체 = 새 원장 · 보존본 = 커밋 2행(본문에 합쳐짐)",
    (count(live), count(keep)))

d = os.path.join(T.TMP, "j")
os.makedirs(d)
live, new, keep = os.path.join(d, "ledger.db"), os.path.join(d, "ledger.db.new"), os.path.join(d, "ledger.db.pre_j")
if hasattr(os, "geteuid") and os.geteuid() == 0:
    chk(True, "J1 건너뜀 — root 는 권한 0 인 파일도 열어 '못 여는 원장'을 만들 수 없음")
else:
    mkdb(live, 2, "o")
    open(live + "-journal", "wb").write(b"journal of a ledger we cannot open " * 40)
    os.chmod(live, 0)
    mkdb(new, 4, "n")
    try:
        lb.swap_in(live, new, keep)
    finally:
        os.chmod(keep if os.path.exists(keep) else live, 0o600)
    chk(count(live) == 4 and not os.path.exists(live + "-journal") and os.path.exists(keep + "-journal"),
        "J1 못 여는 옛 원장 = 교체 · 그 -journal 은 보존본 짝으로(새 원장 옆에 남아 되감기되지 않게)", sorted(os.listdir(d)))
d = os.path.join(T.TMP, "j2")
os.makedirs(d)
live, new, keep = os.path.join(d, "ledger.db"), os.path.join(d, "ledger.db.new"), os.path.join(d, "ledger.db.pre_j2")
subprocess.run([sys.executable, "-c", r'''
import os, sqlite3, sys
c = sqlite3.connect(sys.argv[1], isolation_level=None)
c.execute("PRAGMA journal_mode=DELETE"); c.execute("CREATE TABLE t(a)")
for i in range(3):
    c.execute("INSERT INTO t VALUES (?)", (i,))
c.execute("PRAGMA cache_size=10")
c.execute("PRAGMA cache_spill=1")
c.execute("BEGIN")
for i in range(6000):
    c.execute("INSERT INTO t VALUES (?)", ("x" * 900,))
os._exit(0)
''', live], check=True)
chk(os.path.exists(live + "-journal") and os.path.getsize(live + "-journal") > 0 and os.path.getsize(live) > 1 << 20,
    "J2 (전제) 정상 옛 원장에 핫 저널(쓰기 도중 강제 종료 · 원장 파일은 이미 바뀜 — 열면 되감겨야 할 상태)")
mkdb(new, 6, "n")
lb.swap_in(live, new, keep)
c9 = sqlite3.connect(live)
qc9 = c9.execute("PRAGMA quick_check").fetchone()[0]
c9.close()
chk(qc9 == "ok" and count(live) == 6 and not os.path.exists(live + "-journal") and count(keep) == 3,
    "J3 ★핫 저널 = 교체 전에 옛 원장에서 되감김 → 새 원장 그대로(6행 — R3 전엔 옛 저널이 새 원장에 되감겨 옛 3행이 됨) · 보존본 = 커밋된 3행★",
    (qc9, count(live), count(keep)))

d = os.path.join(T.TMP, "e")
os.makedirs(d)
live, new, keep = os.path.join(d, "ledger.db"), os.path.join(d, "ledger.db.new"), os.path.join(d, "ledger.db.pre_e")
wal_only_rows(live, 4)
mkdb(new, 2, "n")
_real_sqlite = lb.sqlite3


class _IoFailConn:
    def __init__(self, real):
        self.real = real

    def execute(self, sql, *a):
        if "wal_checkpoint" in sql:
            raise _real_sqlite.OperationalError("disk I/O error")
        return self.real.execute(sql, *a)

    def close(self):
        self.real.close()


def _io_fail_connect(*a, **k):
    return _IoFailConn(_real_sqlite.connect(*a, **k))


import db as _dbm  # noqa: E402
_real_db_connect = _dbm.connect
_dbm.connect = _io_fail_connect
try:
    try:
        lb.swap_in(live, new, keep, wal_timeout=0.3)
        e9 = "swapped"
    except lb.SwapRefused as e:
        e9 = str(e)
finally:
    _dbm.connect = _real_db_connect
chk("입출력" in e9 and not os.path.exists(keep) and os.path.exists(new) and count(live) == 4,
    "E1 합치다 실패(디스크·입출력 오류 — 잠김·손상·못 엶이 아님) = SwapRefused(교체 안 함 · 보존본 안 만듦 · 옛 원장 커밋 4행)", e9)
sys.path.insert(0, os.path.join(T.ROOT, "tools"))
if os.path.isfile(os.path.join(T.ROOT, "tools", "ledger_restore.py")):
    import ledger_restore as LR  # noqa: E402
    sd = os.path.join(T.TMP, "e2")
    os.makedirs(sd)
    base9 = os.path.basename(paths.DB_PATH)
    old9, new9 = os.path.join(sd, base9 + ".pre_restore_20260101_000000"), os.path.join(sd, base9 + ".pre_restore_20260102_000000")
    mkdb(old9, 1, "o")
    mkdb(new9, 1, "n")
    open(new9 + "-journal", "wb").write(b"journal of the kept ledger")
    os.utime(old9, (1_800_000_000, 1_800_000_000))
    os.utime(new9, (1_800_000_100, 1_800_000_100))
    os.utime(new9 + "-journal", (1_800_000_200, 1_800_000_200))
    gone9 = LR.prune_pre_restore(sd, keep=2, keep_path=new9)
    chk(gone9 == [] and os.path.exists(old9) and os.path.exists(new9 + "-journal"), "E2 보존본 짝 -journal 은 따로 세지 않음(keep 2 = 옛 보존본 그대로)", gone9)
    gone9 = LR.prune_pre_restore(sd, keep=1, keep_path=new9)
    chk(not os.path.exists(old9) and os.path.exists(new9) and os.path.exists(new9 + "-journal"),
        "E2 keep 1 = 방금 보존본과 그 -journal 남김 · 옛 보존본만 지움", (gone9, sorted(os.listdir(sd))))
    names9 = [r["name"] for r in LR.backups(state_dir=sd)]
    chk(not any(n.endswith("-journal") for n in names9), "E2 백업 목록에 -journal 짝을 원장으로 안 올림", names9)
    hot = os.path.join(sd, base9 + ".pre_restore_20260103_000000")
    subprocess.run([sys.executable, "-c", r"""
import os, sqlite3, sys
c = sqlite3.connect(sys.argv[1], isolation_level=None)
c.execute("PRAGMA journal_mode=DELETE"); c.execute("CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT)"); c.execute("CREATE TABLE t(a)")
for ddl in ("CREATE TABLE postings(posting_id INTEGER PRIMARY KEY)", "CREATE TABLE raw_txs(chain TEXT, txhash TEXT, ingested_at INTEGER)",
            "CREATE TABLE raw_ex(exchange TEXT, observed_at INTEGER)", "CREATE TABLE inbox_offsets(stream TEXT PRIMARY KEY, seg INTEGER, off INTEGER)",
            "CREATE TABLE wallets(chain TEXT, address TEXT)"):   # 복원 검사·계획의 필수 표(되감지 않은 저널만 빼면 '되돌릴 수 있는 원장' 모양)
    c.execute(ddl)
c.execute("INSERT INTO meta VALUES ('schema_version', '2')")
for i in range(3):
    c.execute("INSERT INTO t VALUES (?)", (i,))
c.execute("PRAGMA cache_size=10")
c.execute("PRAGMA cache_spill=1")
c.execute("BEGIN")
for i in range(6000):
    c.execute("INSERT INTO t VALUES (?)", ("x" * 900,))
os._exit(0)
""", hot], check=True)
    ck9 = LR.check(hot, full=False)
    chk(not ck9["ok"] and any("열기 실패" in w for w in ck9["why"]),
        "E3 되감지 않은 핫 저널이 붙은 보존본 = 검사 '열기 실패'(immutable 로 저널을 무시하고 되감지 않은 내용을 되돌리지 않음)", ck9["why"])
    rs9 = lb.restore_state(hot, deep=False)
    chk(rs9[0] == "unknown", "E3 자동 공간 확보·재구축 교체의 보존본 검사(restore_state)도 핫 저널 붙은 사본 = '검사 못 함'(확인됨 아님 — 지울 근거로 안 씀)", rs9)
else:
    chk(True, "E2·E3 건너뜀 — tools/ledger_restore.py 없는 배치")

sys.path.insert(0, os.path.join(T.ROOT, "tools"))
if os.path.isfile(os.path.join(T.ROOT, "tools", "ledger_restore.py")):
    import core  # noqa: E402
    import ledger_restore as LR  # noqa: E402
    S = paths.STATE_DIR
    LIVE = paths.DB_PATH
    BK = os.path.join(S, "backups", "ledger_20261001.db")
    RESTORE = r'''
import os, sys, time
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2])
import paths, ledger_backup as lb, ledger_restore as LR
mode, bk = sys.argv[3], sys.argv[4]
live = paths.DB_PATH
real_replace, real_swap = os.replace, lb.swap_in
if mode == "before":
    lb.swap_in = lambda *a, **k: os._exit(9)
elif mode == "mid":
    def rep(a, b):
        if os.path.abspath(b) == os.path.abspath(live):
            os._exit(9)
        return real_replace(a, b)
    os.replace = rep
elif mode == "after":
    def sw(*a, **k):
        real_swap(*a, **k)
        os._exit(9)
    lb.swap_in = sw
LR.apply(LR.plan(bk, now=int(time.time())), proc_check=False, log=lambda *a: None)
print("NO_CRASH")
'''

    def setup():
        for n in os.listdir(S):
            p9 = os.path.join(S, n)
            if n.startswith(("ledger.db", "restore", "daily_cache", histmark.HIST_DIRTY)) and os.path.isfile(p9):
                os.remove(p9)
            elif n.startswith("restore_") and os.path.isdir(p9):
                import shutil
                shutil.rmtree(p9)
        core.Core(config.load_config()).conn.close()
        os.makedirs(os.path.dirname(BK), exist_ok=True)
        LR.copy_ledger(LIVE, BK)
        subprocess.run([sys.executable, "-c", "import os,sqlite3,sys\nc=sqlite3.connect(sys.argv[1])\n"
                        "c.execute(\"INSERT INTO meta (k, v) VALUES ('crash_tag', 'wal')\")\nc.commit()\nos._exit(0)\n", LIVE], check=True)
        statefile.atomic_write_json(os.path.join(S, "daily_cache.json"), {"x": 1})

    def tag(path, immutable=False):
        c = sqlite3.connect(paths.sqlite_ro_uri(path, immutable=immutable or not os.path.exists(path + "-wal")), uri=True)
        try:
            r9 = c.execute("SELECT v FROM meta WHERE k='crash_tag'").fetchone()
            return r9[0] if r9 else None
        finally:
            c.close()

    def run(mode):
        return subprocess.run([sys.executable, "-c", RESTORE, T.SRC, os.path.join(T.ROOT, "tools"), mode, BK],
                              capture_output=True, text=True, timeout=120)

    setup()
    chk(tag(LIVE) == "wal" and tag(LIVE, immutable=True) is None and tag(BK) is None, "R0 (전제) 지금 원장 = WAL 에만 커밋 1건 · 백업 = 그 전")
    r = run("before")
    chk(r.returncode == 9 and tag(LIVE) == "wal" and os.path.exists(os.path.join(S, "restore.lock")),
        "R1 교체 직전 강제 종료 = 옛 원장 그대로(WAL 커밋 포함) · restore.lock 남음(다음 실행이 알림)", (r.returncode, r.stderr[-300:]))
    setup()
    r = run("mid")
    chk(r.returncode == 9 and tag(LIVE) == "wal" and tag(LIVE, immutable=True) == "wal" and os.path.exists(os.path.join(S, "restore.lock")),
        "R2 ★교체 도중(-wal 옮긴 뒤) 강제 종료 = 옛 원장 그대로 · 커밋은 본문에(WAL 없이도)★", (r.returncode, tag(LIVE), r.stderr[-300:]))
    os.remove(os.path.join(S, "restore.lock"))
    rec = LR.apply(LR.plan(BK, now=int(time.time())), proc_check=False, log=lambda *a: None)
    chk(tag(LIVE) is None and rec["kept"] and tag(rec["kept"]) == "wal", "R3 restore.lock 지우고 다시 = 끝까지(원장 = 백업 · 보존본 = 커밋 포함 옛 원장)")
    setup()
    r = run("after")
    chk(r.returncode == 9 and tag(LIVE) is None and not os.path.exists(os.path.join(S, "daily_cache.json")),
        "R4 교체 직후 강제 종료 = 새 원장 · 옛 원장으로 만든 곡선 캐시는 이미 무효화(교체 전에 지움 — R3)", (r.returncode, r.stderr[-300:]))
    pre9 = [f for f in os.listdir(S) if f.startswith("ledger.db.pre_restore_") and not f.endswith(("-wal", "-shm", "-journal"))]
    chk(len(pre9) == 1 and tag(os.path.join(S, pre9[0])) == "wal", "R4 옛 원장 보존본 = 커밋 포함(교체 전 합침)", pre9)
else:
    chk(True, "R 건너뜀 — tools/ledger_restore.py 없는 배치")

T.finish()
