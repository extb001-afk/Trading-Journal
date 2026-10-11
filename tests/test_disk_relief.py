#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _gate as _x
from _gate import check, done
import collections
import json
import os
import shutil
import subprocess
import sqlite3
import time
import common
import core
import ledger_backup as LB

assert _x.TMP in common.STATE_DIR
core.dm = lambda *a, **k: None
c = core.Core(common.load_config())
S = common.STATE_DIR
BASE = os.path.dirname(S)
HOME = os.path.join(_x.TMP, "home_rb")
os.makedirs(HOME, exist_ok=True)
c.cfg.setdefault("backfill", {})["rebuild_dir"] = HOME
LIVE = common.DB_PATH
MB = 1 << 20
GB = 1 << 30
OLD = time.time() - 5 * 86400

Usage = collections.namedtuple("Usage", "total used free")
_real_du = shutil.disk_usage
DISK = {"cap": None, "home_free": None}


def used_now():
    seen, tot = set(), 0
    for dp, dn, fns in os.walk(_x.TMP):
        for fn in fns:
            try:
                st = os.lstat(os.path.join(dp, fn))
            except OSError:
                continue
            if (st.st_dev, st.st_ino) in seen:
                continue
            seen.add((st.st_dev, st.st_ino))
            tot += st.st_size
    return tot


def fake_du(path):
    if DISK["cap"] is None:
        return _real_du(path)
    if DISK["home_free"] is not None and os.path.realpath(str(path)).startswith(os.path.realpath(HOME)):
        return Usage(10 * GB, 0, DISK["home_free"])
    u = used_now()
    return Usage(DISK["cap"], u, max(0, DISK["cap"] - u))


shutil.disk_usage = fake_du


def need_same_fs():
    size = os.path.getsize(LIVE) + (os.path.getsize(LIVE + "-wal") if os.path.exists(LIVE + "-wal") else 0)
    return 3 * size + size + (2 << 30)


def set_free(free_bytes):
    DISK["cap"] = used_now() + free_bytes


def big(path, size):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.truncate(size)


def clear():
    DISK["cap"] = None
    DISK["home_free"] = None
    for n in os.listdir(S):
        if n.startswith("ledger.db.") or n == "ext_rebuild_status.json":
            os.remove(os.path.join(S, n))
    shutil.rmtree(os.path.join(S, "backups"), ignore_errors=True)
    for n in os.listdir(BASE):
        if n.startswith("state.failed_hotfixt_") or n == "elsewhere":
            p = os.path.join(BASE, n)
            os.remove(p) if os.path.islink(p) else shutil.rmtree(p)
    shutil.rmtree(HOME, ignore_errors=True)
    os.makedirs(HOME, exist_ok=True)
    c._ext_relief = None


PRE = [LIVE + ".pre_extrebuild_2026100%d_000000" % i for i in (1, 2, 3)]
DAY = [os.path.join(S, "backups", "ledger_2026100%d.db" % i) for i in (1, 2, 3)]
F_OLD = os.path.join(BASE, "state.failed_hotfixt_20261001_000000_11")
F_NEW = os.path.join(BASE, "state.failed_hotfixt_%s_22" % time.strftime("%Y%m%d_%H%M%S"))
F_HALF = os.path.join(BASE, "state.failed_hotfixt_20261002_000000_33")
F_DONE = os.path.join(BASE, "state.failed_hotfixt_20261003_000000_44")


NEWTS = time.strftime("%Y%m%d_%H%M%S", time.localtime(time.time() - 120))


def setup(failed=True, leftovers=False):
    clear()
    for p in PRE:
        big(p, 512 * MB)
        big(p + "-wal", 4 * MB)
    big(PRE[0] + "-shm", 32 * 1024)
    for p in DAY:
        big(p, 512 * MB)
    open(os.path.join(S, "backups", "prefs_20261003.json"), "w").write("{}")
    if failed:
        big(os.path.join(F_OLD, "config.json.after"), 300 * MB)
        big(os.path.join(F_NEW, "config.json.after"), 300 * MB)
        big(os.path.join(F_HALF, "state", "ledger.db"), 300 * MB)
        big(os.path.join(F_DONE, "state", "ledger.db"), 300 * MB)
        open(os.path.join(F_DONE, "LEDGER_SWAPPED"), "w").write("ts=1\n")
        for p in (F_OLD, F_HALF, F_DONE):
            os.utime(p, (OLD, OLD))
    if leftovers:
        sh_old = os.path.join(HOME, "tj_shadow_extrebuild_20261001_000000")
        big(os.path.join(sh_old, "ledger.db"), 400 * MB)
        os.utime(sh_old, (OLD, OLD))
        big(os.path.join(HOME, "tj_shadow_extrebuild_%s" % NEWTS, "ledger.db"), 100 * MB)
        open(os.path.join(HOME, "tj_shadow_extrebuild_20261001_000000.report.json"), "w").write("{}")
        big(LIVE + ".extnew_20261001_000000", 400 * MB)
        os.utime(LIVE + ".extnew_20261001_000000", (OLD, OLD))
        big(LIVE + ".extnew_%s" % NEWTS, 100 * MB)


class _R:
    returncode, stdout, stderr = 1, "", "stub rebuild2"


def run_rebuild():
    real = subprocess.run
    subprocess.run = lambda *a, **k: _R()
    try:
        c._ext_rebuild({"base": 1}, [])
    finally:
        subprocess.run = real
    return str(c._meta_get("ext_rebuild_last_error") or "")


def ex(*ps):
    return [os.path.basename(p) for p in ps if os.path.lexists(p)]


def status():
    try:
        return json.load(open(os.path.join(S, "ext_rebuild_status.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def must_keep():
    return all(os.path.exists(p) for p in (LIVE, PRE[2], DAY[2]))


setup()
set_free(need_same_fs() - 700 * MB)
errA = run_rebuild()
stA = status()
check("[A] 디스크 검사 통과(자동 정리 뒤) — 다음 단계(rebuild2)까지 감", errA.startswith("rebuild2 rc="), errA)
check("[A] pre_extrebuild 최신 1개만 · 지운 것의 -wal·-shm 짝도", ex(*PRE) == [os.path.basename(PRE[2])]
      and not os.path.exists(PRE[0] + "-wal") and not os.path.exists(PRE[0] + "-shm") and os.path.exists(PRE[2] + "-wal"), ex(*PRE))
check("[A] 충분해졌으니 일일 백업·롤백 흔적은 그대로", ex(*DAY) == [os.path.basename(p) for p in DAY] and os.path.isdir(F_OLD), ex(*DAY))
rlA = stA.get("relief") or {}
names_A = sorted(r.get("name") for r in rlA.get("removed") or [])
check("[A] ext_rebuild_status.json relief = 지운 목록 · 확보량(≈1032MB)",
      names_A == sorted(os.path.basename(p) for p in PRE[:2]) and abs(int(rlA.get("freed") or 0) - (1024 + 8) * MB - 32 * 1024) <= 64 * 1024, rlA)

setup()
set_free(need_same_fs() - 1600 * MB)
errB = run_rebuild()
check("[B] 디스크 검사 통과", errB.startswith("rebuild2 rc="), errB)
check("[B] 일일 원장 백업도 최신 1개만(prefs 는 무접촉)", ex(*DAY) == [os.path.basename(DAY[2])]
      and os.path.exists(os.path.join(S, "backups", "prefs_20261003.json")), ex(*DAY))
check("[B] (c) 롤백 흔적까지는 안 감", os.path.isdir(F_OLD) and os.path.isdir(F_DONE), "")

setup(leftovers=True)
set_free(need_same_fs() - 20 * GB)
errC = run_rebuild()
check("[C] 그래도 모자라면 실패 · 문구 '자동 정리 뒤에도'", errC.startswith("디스크 부족") and "자동 정리 뒤에도" in errC, errC)
check("[C] 3일 지난 흔적(교체 끝남 포함) 지움", not os.path.exists(F_OLD) and not os.path.exists(F_DONE), ex(F_OLD, F_DONE))
check("[C] 3일 안 된 흔적 · 교체 미완(state 있고 LEDGER_SWAPPED 없음) 흔적은 남김", os.path.isdir(F_NEW) and os.path.isdir(F_HALF), ex(F_NEW, F_HALF))
check("[C] 지금 원장·-wal·최신 pre_extrebuild·최신 일일 백업은 절대 남음", must_keep() and ex(*PRE) == [os.path.basename(PRE[2])]
      and ex(*DAY) == [os.path.basename(DAY[2])], (ex(*PRE), ex(*DAY)))
sh_left = sorted(n for n in os.listdir(HOME) if n.startswith("tj_shadow_extrebuild_"))
check("[C] 죽은 재구축 찌꺼기(12시간 지난 shadow·extnew) 지움 · 새것·보고서는 남김",
      "tj_shadow_extrebuild_20261001_000000" not in sh_left and len(sh_left) == 2 and not os.path.exists(LIVE + ".extnew_20261001_000000")
      and sum(1 for n in os.listdir(S) if ".extnew_" in n) == 1, sh_left)
check("[C] 실패 상태에도 relief 기록", int((status().get("relief") or {}).get("freed") or 0) > 0, status().get("relief"))

setup(failed=False)
os.makedirs(os.path.join(BASE, "elsewhere"))
os.link(PRE[0], os.path.join(BASE, "elsewhere", "same_inode"))
set_free(need_same_fs() - 300 * MB)
errH = run_rebuild()
rlH = status().get("relief") or {}
check("[H] 하드 링크인 옛 보존본은 남김(지워도 공간이 안 생김) · 다른 옛 보존본으로 확보", errH.startswith("rebuild2 rc=")
      and os.path.exists(PRE[0]) and not os.path.exists(PRE[1]), (errH, ex(*PRE)))
check("[H] 확보량에 하드 링크 0(지운 것 = 512MB+4MB)", abs(int(rlH.get("freed") or 0) - 516 * MB) <= 64 * 1024
      and any("링크" in str(s.get("why")) for s in rlH.get("skipped") or []), rlH)

setup()
_dev_real = getattr(LB, "dev_of", None)
LB.dev_of = lambda p: 101 if os.path.realpath(str(p)).startswith(os.path.realpath(HOME)) else 202
set_free(100 * GB)
DISK["home_free"] = 1 * GB
errD = run_rebuild()
check("[D] 다른 디스크의 state 보존본은 안 지움(도움 안 됨) · 실패", errD.startswith("디스크 부족") and ex(*PRE) == [os.path.basename(p) for p in PRE]
      and ex(*DAY) == [os.path.basename(p) for p in DAY], (errD, ex(*PRE)))
if _dev_real is not None:
    LB.dev_of = _dev_real
else:
    del LB.dev_of

calls = []
real_rebuild = c._ext_rebuild
c._ext_rebuild = lambda need, ex_done: calls.append(1)
c._ext_items = lambda now: ([], [], [])


def pass_r(code, stage="precheck", err="디스크 부족: 여유 6GB / 필요 ≈16GB (원장 5109MB)", fail_ago=400, born_ago=5000):
    c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_prewindow:base', '1')")
    c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_rebuild_fail_at', ?)", (str(int(time.time() - fail_ago)),))
    c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_rebuild_fail_code_at', ?)", (str(int(time.time() - fail_ago)),))
    c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_rebuild_fails', '2')")
    c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_rebuild_last_error', ?)", (err,))
    c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_rebuild_fail_code', ?)", (code,))
    c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_rebuild_fail_stage', ?)", (stage,))
    c.conn.execute("DELETE FROM meta WHERE k IN ('ext_rebuild_started_at', 'ext_rebuilt_at', 'rebuild_not_before')")
    c.conn.commit()
    c._last_ext_check = 0
    c._ext_born = time.time() - born_ago
    n0 = len(calls)
    c.ext_rebuild_pass(set(c.EXT_STREAMS))
    return len(calls) > n0


setup(failed=False)
set_free(need_same_fs() - 5 * GB)
r1 = pass_r("resource_disk")
set_free(need_same_fs() + 1 * GB)
r2 = pass_r("resource_disk")
r3 = [pass_r(cd, "run", err="한국어 문구는 판정에 안 씀: 디스크 부족") for cd in ("transient_rpc", "integrity", "position_gate", "pnl_approval", "error")]
r3b = pass_r("resource_disk", "run")
r4 = pass_r("resource_disk", fail_ago=100)
r5 = pass_r("resource_disk", born_ago=60)
setup(failed=False)
set_free(need_same_fs() - 700 * MB)
r6 = pass_r("resource_disk")
check("[R] 디스크 부족 + 지금도 모자람 = 재시도 안 함", r1 is False, r1)
check("[R] 디스크 부족 + 지금 충분 = 백오프 무시하고 바로 재시도", r2 is True, r2)
check("[R] 다른 원인(transient_rpc·integrity·position_gate·pnl_approval·error) = 종전 백오프(문구에 '디스크 부족'이 있어도)", r3 == [False] * 5, r3)
check("[R] resource_disk 라도 재구축 도중(run) = 종전 백오프", r3b is False, r3b)
check("[R] 실패 직후(최소 간격 안) · core 기동 직후(배포 검증 창) = 안 함", r4 is False and r5 is False, (r4, r5))
check("[R] 자동 정리로 충분해지면 재시도(옛 보존본 정리됨)", r6 is True and ex(*PRE) == [os.path.basename(PRE[2])], (r6, ex(*PRE)))
c._ext_rebuild = real_rebuild

def mkdb(path, tag):
    cx = sqlite3.connect(path)
    cx.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    cx.execute("INSERT INTO meta VALUES ('tag', ?)", (tag,))
    cx.commit()
    cx.close()


def tag(path):
    cx = sqlite3.connect(common.sqlite_ro_uri(path, immutable=True), uri=True)
    try:
        return cx.execute("SELECT v FROM meta WHERE k='tag'").fetchone()[0]
    finally:
        cx.close()


def swap_dir(name, live_db=True):
    d9 = os.path.join(_x.TMP, name)
    os.makedirs(d9)
    lv = os.path.join(d9, "ledger.db")
    for tsx in ("20260101_000000", "20260201_000000", "20260301_000000"):
        mkdb(lv + ".pre_extrebuild_" + tsx, "old" + tsx[4:6])
        open(lv + ".pre_extrebuild_" + tsx + "-wal", "w").write("")
    mkdb(lv, "cur") if live_db else open(lv, "w").write("cur — 원장 아님")
    mkdb(lv + ".extnew_X", "new")
    return d9, lv


d, live = swap_dir("swap")
core.Core._ext_swap(live, live + ".extnew_X", "20260401_000000")
left = sorted(f for f in os.listdir(d) if ".pre_extrebuild_" in f)
check("[S] 기본 = 이번 것(직전 원장) 1개만 · 옛 것의 -wal 도", left == ["ledger.db.pre_extrebuild_20260401_000000"], left)
check("[S] 새 원장 자리", tag(live) == "new" and tag(live + ".pre_extrebuild_20260401_000000") == "cur", "")
d2, live2 = swap_dir("swap_fail")
real_swap = LB.swap_in


def boom(*a, **k):
    raise OSError("합성: 교체 실패")


LB.swap_in = boom
try:
    core.Core._ext_swap(live2, live2 + ".extnew_X", "20260401_000000")
    raised = False
except OSError:
    raised = True
finally:
    LB.swap_in = real_swap
left2 = sorted(f for f in os.listdir(d2) if ".pre_extrebuild_" in f and not f.endswith("-wal"))
check("[S] 교체 실패 = 옛 보존본 3개 그대로(-wal 포함) · 원장 그대로", raised and len(left2) == 3 and tag(live2) == "cur"
      and os.path.exists(live2 + ".pre_extrebuild_20260101_000000-wal"), (raised, left2))
d3, live3 = swap_dir("swap_badkept", live_db=False)
core.Core._ext_swap(live3, live3 + ".extnew_X", "20260401_000000")
left3 = sorted(f for f in os.listdir(d3) if ".pre_extrebuild_" in f and not f.endswith("-wal"))
check("[S] 이번 보존본 확인 실패(원장 아님) = 옛 보존본 그대로 + 이번 것", len(left3) == 4 and tag(live3) == "new", left3)


def kc(bcfg, kcfg=None):
    try:
        return tuple(c._ext_keep_cfg(bcfg, kcfg))
    except TypeError as e:
        return repr(e)


ks = {"기본": kc({}), "keep_pre_rebuild=3": kc({}, {"keep_pre_rebuild": 3}), "keep_pre_rebuild=1": kc({}, {"keep_pre_rebuild": 1}),
      "새 키가 옛 키보다 먼저": kc({"rebuild_keep_recent": 4, "rebuild_keep_oldest": True}, {"keep_pre_rebuild": 2}),
      "옛 키 명시 존중": kc({"rebuild_keep_recent": 2, "rebuild_keep_oldest": True}, {}),
      "잘못된 값(0·6·문자·True)": [kc({}, {"keep_pre_rebuild": v}) for v in (0, 6, "2", True)]}
check("[S] 보존 수 설정: 기본 (0, False) · backup.keep_pre_rebuild N = 최근 N−1 + 이번 것 · 옛 키 명시 존중 · 잘못된 값 = 기본",
      ks["기본"] == (0, False) and ks["keep_pre_rebuild=3"] == (2, False) and ks["keep_pre_rebuild=1"] == (0, False)
      and ks["새 키가 옛 키보다 먼저"] == (1, False) and ks["옛 키 명시 존중"] == (2, True)
      and ks["잘못된 값(0·6·문자·True)"] == [(0, False)] * 4, ks)
src = open(os.path.join(_x.TREE, "src", "core.py"), encoding="utf-8").read()
check("[S] 재구축 교체가 backup 설정을 넘김(정적)", 'self._ext_keep_cfg(bcfg, self.cfg.get("backup"))' in src, "")
clear()
done()
