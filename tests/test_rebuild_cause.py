#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _gate as _x
from _gate import check, done
import collections
import errno
import json
import os
import shutil
import sqlite3
import subprocess
import time
import types
import common
import core

assert _x.TMP in common.STATE_DIR
core.dm = lambda *a, **k: None
c = core.Core(common.load_config())
HOME = os.path.join(_x.TMP, "home_rc")
os.makedirs(HOME, exist_ok=True)
c.cfg.setdefault("backfill", {})["rebuild_dir"] = HOME
GB = 1 << 30
Usage = collections.namedtuple("Usage", "total used free")
_real_du = shutil.disk_usage
DISK = {"free": 500 * GB}
shutil.disk_usage = lambda p: Usage(1000 * GB, 0, DISK["free"])


class _R:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def meta(k):
    return c._meta_get(k)


def status():
    try:
        return json.load(open(os.path.join(common.STATE_DIR, "ext_rebuild_status.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def reset():
    c.conn.execute("DELETE FROM meta WHERE k LIKE 'ext_rebuild_%' OR k IN ('ext_rebuilt_at', 'rebuild_not_before')")
    c.conn.commit()


def run(results, **over):
    seq = list(results)
    real = subprocess.run

    def fake(args, *a, **k):
        r = seq.pop(0) if seq else _R(0)
        if callable(r) and not isinstance(r, _R):
            r = r(args)
        if isinstance(r, BaseException):
            raise r
        return r
    subprocess.run = fake
    for k9, v9 in over.items():
        setattr(c, k9, v9)
    try:
        c._ext_rebuild({"base": 1}, [])
    finally:
        subprocess.run = real
        for k9 in over:
            delattr(c, k9)
    return meta("ext_rebuild_fail_code"), meta("ext_rebuild_fail_stage"), str(meta("ext_rebuild_last_error") or "")


def marker_db(args):
    sh = args[args.index("--shadow-dir") + 1]
    os.makedirs(sh, exist_ok=True)
    cx = sqlite3.connect(os.path.join(sh, "ledger.db"))
    cx.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    cx.execute("INSERT INTO meta VALUES ('rebuild_incomplete', '1')")
    cx.commit()
    cx.close()
    return _R(0)


K = {}
reset()
DISK["free"] = 1 << 20
K["disk_pre"] = run([])
st_disk = status()
DISK["free"] = 500 * GB
K["rc2"] = run([_R(2, "", "★[6b] 업비트 재대사 미완★")])
K["rc4"] = run([_R(4, "", "★G_obs_replay 실패★")])
K["rc1_full"] = run([_R(1, "", "sqlite3.OperationalError: database or disk is full")])
K["rc1"] = run([_R(1, "", "Traceback ... KeyError: 'x'")])
K["timeout"] = run([subprocess.TimeoutExpired(["rebuild2"], 1)])
K["gates"] = run([_R(0), _R(1, "G_b 실패")])
K["pos"] = run([_R(0), _R(0)], _ext_position_gate=lambda *a, **k: ["합성칸"])
K["pnl"] = run([_R(0), _R(0)], _ext_position_gate=lambda *a, **k: [],
               _ext_pnl_gate=lambda *a, **k: {"ok": False, "approved": False, "reason": "합성 손익 차이"})
K["marker"] = run([marker_db, _R(0)], _ext_position_gate=lambda *a, **k: [],
                  _ext_pnl_gate=lambda *a, **k: {"ok": True, "approved": False, "reason": ""})


def enospc(*a, **k):
    raise OSError(errno.ENOSPC, "No space left on device")


K["enospc"] = run([], _ext_touched=enospc)
check("[K] 디스크 사전 검사 = resource_disk · precheck", K["disk_pre"][:2] == ("resource_disk", "precheck") and K["disk_pre"][2].startswith("디스크 부족"), K["disk_pre"])
check("[K] 상태 파일 fail_code·fail_label·fail_stage · 디스크별 여유/필요(disk.rows)",
      st_disk.get("fail_code") == "resource_disk" and st_disk.get("fail_label") == "디스크 공간" and st_disk.get("fail_stage") == "precheck"
      and isinstance((st_disk.get("disk") or {}).get("rows"), list) and (st_disk["disk"]["rows"][0].get("need_gb") or 0) >= 2, st_disk)
check("[K] rebuild2 rc 2(업비트 재대사 미완) = transient_rpc · rc 4(관측 재현 악화) = integrity",
      K["rc2"][:2] == ("transient_rpc", "run") and K["rc4"][:2] == ("integrity", "run"), (K["rc2"], K["rc4"]))
check("[K] rebuild2 도중 디스크 가득 = resource_disk · run(짧은 재시도 대상 아님) · 그 밖 rc 1 = error",
      K["rc1_full"][:2] == ("resource_disk", "run") and K["rc1"][:2] == ("error", "run"), (K["rc1_full"], K["rc1"]))
check("[K] 시간 초과 = timeout · 게이트 b·c = integrity · 새 원장 마커 = integrity",
      K["timeout"][0] == "timeout" and K["gates"][0] == "integrity" and K["marker"][0] == "integrity", (K["timeout"], K["gates"], K["marker"]))
check("[K] 포지션 게이트 = position_gate · 손익 게이트 = pnl_approval", K["pos"][0] == "position_gate" and K["pnl"][0] == "pnl_approval",
      (K["pos"], K["pnl"]))
check("[K] 도중 ENOSPC 예외 = resource_disk · run", K["enospc"][:2] == ("resource_disk", "run"), K["enospc"])
reset()
c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_prewindow:base', '1')")
c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_rebuild_started_at', ?)", (str(int(time.time()) - 50),))
c.conn.commit()
c._ext_items = lambda now: ([], [], [])
c._last_ext_check = 0
c.ext_rebuild_pass(set(c.EXT_STREAMS))
check("[K] 도중 중단(시작 표식 남음) = interrupted", meta("ext_rebuild_fail_code") == "interrupted", meta("ext_rebuild_fail_code"))
src = open(os.path.join(_x.TREE, "src", "core.py"), encoding="utf-8").read()
i9 = src.find("c2.execute(\"DELETE FROM meta WHERE k LIKE 'ext_prewindow:%'")
check("[K] 성공 교체 = 실패 횟수·원인 코드·단계도 지움(정적)", i9 > 0 and "'ext_rebuild_fail_code', 'ext_rebuild_fail_stage'" in src[i9:i9 + 600], i9)
check("[K] 실패 기록이 원인 코드를 받음 — _ext_rebuild 의 fail(...) 호출 전부 코드 지정(정적)",
      all(("fail(" + q) not in src for q in ('"rebuild2 시간 초과")', '"게이트 b·c: " + g.stdout.strip()[-300:])', '"shadow WAL 미체크포인트")',
                                              '"새 원장 무결성/마커")', '"복사본 무결성")')), "")

calls = []
real_rebuild = c._ext_rebuild


def two_fails(results_fn):
    reset()
    for _ in range(2):
        results_fn()
    return int(meta("ext_rebuild_fails") or 0)


def pass_now(ago, born_ago=5000, shift_code=True):
    c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_prewindow:base', '1')")
    c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_rebuild_fail_at', ?)", (str(int(time.time() - ago)),))
    if shift_code:
        c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_rebuild_fail_code_at', ?)", (str(int(time.time() - ago)),))
    c.conn.commit()
    c._last_ext_check = 0
    c._ext_born = time.time() - born_ago
    c._ext_rebuild = lambda need, ex_done: calls.append(1)
    n0 = len(calls)
    try:
        c.ext_rebuild_pass(set(c.EXT_STREAMS))
    finally:
        del c._ext_rebuild
    return len(calls) > n0


def disk_fail():
    DISK["free"] = 1 << 20
    run([])


nf = two_fails(disk_fail)
wait = min(c.EXT_RETRY_MAX, 6 * 3600 * 2 ** (nf - 1))
w_short = pass_now(400)
DISK["free"] = 500 * GB
w_early = pass_now(120)
w_ok = pass_now(400)
w_born = pass_now(400, born_ago=60)
check("[W] 디스크 실패 2회 = 백오프 12시간(종전 규칙 그대로)", nf == 2 and wait == 12 * 3600 and meta("ext_rebuild_fail_code") == "resource_disk", (nf, wait))
check("[W] 공간이 그대로면 재구축 안 함", w_short is False, w_short)
check("[W] ★공간이 생기면 12시간을 기다리지 않고 다시(실패 5분 뒤부터)★ — 실패 2분 뒤·core 기동 직후는 아직",
      w_ok is True and w_early is False and w_born is False, (w_ok, w_early, w_born))
other = {}
for nm9, fn9 in (("pnl_approval", lambda: run([_R(0), _R(0)], _ext_position_gate=lambda *a, **k: [],
                                                  _ext_pnl_gate=lambda *a, **k: {"ok": False, "approved": False, "reason": "합성"})),
                 ("integrity", lambda: run([_R(0), _R(1, "G_b 실패")])),
                 ("position_gate", lambda: run([_R(0), _R(0)], _ext_position_gate=lambda *a, **k: ["합성칸"])),
                 ("transient_rpc", lambda: run([_R(2, "", "업비트 재대사 미완")])),
                 ("resource_disk/run", lambda: run([_R(1, "", "OSError: [Errno 28] No space left on device")]))):
    DISK["free"] = 500 * GB
    two_fails(fn9)
    other[nm9] = (meta("ext_rebuild_fail_code"), pass_now(400), pass_now(3 * 3600))
check("[W] 손익 승인·무결성·포지션 게이트·일시 오류·도중 디스크 가득 = 공간이 넉넉해도 종전 백오프(6분·3시간 뒤 모두 안 함 — 우회 없음)",
      all(v[1] is False and v[2] is False for v in other.values()) and other["pnl_approval"][0] == "pnl_approval"
      and other["resource_disk/run"][0] == "resource_disk", other)

DISK["free"] = 500 * GB
reset()
disk_fail()
DISK["free"] = 500 * GB
ok_l0 = pass_now(400)
c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_rebuild_fail_at', ?)", (str(int(time.time()) - 350),))
c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_rebuild_fails', '2')")
c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_rebuild_last_error', '손익 게이트: 합성(이전 코드)')")
c.conn.commit()
ok_l1 = pass_now(350, shift_code=False)
c._ext_status()
st_l = status()
fake0 = types.SimpleNamespace(cfg=c.cfg, BF_REQ_PATH=os.path.join(common.STATE_DIR, "backfill_request.json"))
import web

v_l = web.StateBuilder._backfill_since_view(fake0, c.conn)
check("[L] 새 코드의 디스크 실패 = 짧은 재시도 됨(대조)", ok_l0 is True, ok_l0)
check("[L] 이전 코드가 그 뒤 실패를 기록 = 남은 resource_disk 코드 무효 → 공간이 있어도 짧은 재시도 없음 · 상태·화면 원인 없음",
      ok_l1 is False and st_l.get("fail_code") is None and v_l.get("rebuildFailCode") is None and v_l.get("rebuildDiskRetry") is False,
      (ok_l1, st_l.get("fail_code"), v_l.get("rebuildFailCode")))
DISK["free"] = 1 << 20
run([])
check("[L] 다시 새 코드가 실패를 기록하면 원인 코드 정상", c._ext_fail_code() == ("resource_disk", "precheck"), c._ext_fail_code())

os.environ["TJ_HEALTH"] = "0"
import health as H

NOW = time.time()
UNITS = ["tj-core", "tj-web", "tj-alert"]
HS = H.settings({"health": {"units": UNITS}})


def hev(xr):
    obs = {"now": NOW, "pm2": {u: {"status": "online", "restarts": 0, "pid": 1} for u in UNITS}, "bal_mem": {}, "prev_inc": {}, "sources": [],
           "extrb": xr}
    return {x["id"]: x for x in H.evaluate(obs, HS)}.get("rebuild:ext") or {}


g_disk = hev({"fails": 2, "fail_at": NOW - 60, "last_error": "디스크 부족(자동 정리 뒤에도): 여유 6GB / 필요 ≈16GB (재구축 작업 폴더 디스크 · 원장 5000MB)",
              "fail_code": "resource_disk", "fail_label": "디스크 공간", "fail_stage": "precheck",
              "disk": {"rows": [{"what": "work", "label": "재구축 작업 폴더 디스크", "free_gb": 6.0, "need_gb": 16.6},
                                {"what": "ledger", "label": "원장 디스크", "free_gb": 30.0, "need_gb": 7.3}]}})
g_pnl = hev({"fails": 2, "fail_at": NOW - 60, "last_error": "손익 게이트: 합성", "fail_code": "pnl_approval", "fail_label": "손익 승인 대기",
             "fail_stage": "run"})
g_old = hev({"fails": 2, "fail_at": NOW - 60, "last_error": "rebuild2 rc=1: x"})
check("[G] 헬스: 디스크 = 제목에 '디스크 공간' · 상세에 디스크별 여유/필요 · '5분 안에 자동으로 다시' · 할 일 = 디스크 여유 확보",
      g_disk.get("level") == "warn" and g_disk.get("title") == "과거 데이터 재계산 실패 2회 · 디스크 공간"
      and "재구축 작업 폴더 디스크 여유 6.0GB / 필요 ≈16.6GB" in str(g_disk.get("detail")) and "5분 안에" in str(g_disk.get("detail"))
      and "디스크 여유 확보" in str(g_disk.get("action")), g_disk)
check("[G] 헬스: 손익 승인 = 원인 이름 · 승인 안내 · 백오프 문구(디스크 문구 없음)",
      g_pnl.get("title") == "과거 데이터 재계산 실패 2회 · 손익 승인 대기" and "재계산 승인" in str(g_pnl.get("action"))
      and "5분 안에" not in str(g_pnl.get("detail")) and "백오프 뒤 재시도" in str(g_pnl.get("detail")), g_pnl)
check("[G] 헬스: 옛 상태 파일(원인 코드 없음) = 종전 제목·문구", g_old.get("title") == "과거 데이터 재계산 실패 2회"
      and str(g_old.get("detail")).startswith("마지막 오류: rebuild2 rc=1: x"), g_old)

reset()
DISK["free"] = 1 << 20
run([])
fake = types.SimpleNamespace(cfg=c.cfg, BF_REQ_PATH=os.path.join(common.STATE_DIR, "backfill_request.json"))
v1 = web.StateBuilder._backfill_since_view(fake, c.conn)
reset()
v2 = web.StateBuilder._backfill_since_view(fake, c.conn)
check("[G] 설정 › 과거 데이터: rebuildFailCode·rebuildFailLabel·rebuildDiskRetry(디스크 사전 검사) · 실패 없으면 비움",
      v1.get("rebuildFailCode") == "resource_disk" and v1.get("rebuildFailLabel") == "디스크 공간" and v1.get("rebuildDiskRetry") is True
      and v2.get("rebuildFailCode") is None and v2.get("rebuildDiskRetry") is False, (v1.get("rebuildFailCode"), v1.get("rebuildDiskRetry"), v2.get("rebuildFailCode")))
js = open(os.path.join(_x.TREE, "web", "v2", "app.js"), encoding="utf-8").read()
check("[G] 화면 문구: 원인 이름 · 디스크면 '여유가 생기면 바로 다시'(정적)", "bs.rebuildFailLabel" in js and "bs.rebuildDiskRetry" in js, "")
shutil.disk_usage = _real_du
shutil.rmtree(HOME, ignore_errors=True)
done()
