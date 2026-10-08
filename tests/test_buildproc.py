#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import signal
import subprocess
import time

import buildproc as bp
import common


def ck(name, cond, extra=None):
    T.chk(bool(cond), name, extra)


ST1 = "Name:\tpython3\nState:\tS (sleeping)\nThreads:\t1\nvoluntary_ctxt_switches:\t40\nnonvoluntary_ctxt_switches:\t2\n"
ST2 = ST1.replace("Threads:\t1", "Threads:\t2")
STR = ST1.replace("State:\tS (sleeping)", "State:\tR (running)")
UNTIMED = "202 0x7f00aa001234 0x80 0x2 0x0 0x0 0x0 0x7ffd00001000 0x7f00aa000100"
TIMED = "202 0x7f00aa001234 0x189 0x0 0x7ffd00002000 0x0 0xffffffff 0x7ffd00001000 0x7f00aa000100"

o = bp.lock_obs(ST1, "futex_wait_queue\n", UNTIMED, futex_nr=202)
ck("스레드 하나 · 잠듦 · futex · 시간 제한 없음 = 교착 후보 · untimed True · 문맥 전환 합 42", o == {"cand": True, "untimed": True, "csw": 42}, o)
o = bp.lock_obs(ST1, "futex_wait_queue", TIMED, futex_nr=202)
ck("시간 제한 있는 futex 대기(Event.wait(6)) = untimed False", o["cand"] and o["untimed"] is False, o)
ck("ARM(98번)도 같은 판정", bp.lock_obs(ST1, "futex_wait_queue", "98" + UNTIMED[3:], futex_nr=98)["untimed"] is True)
ck("스레드 둘 = 후보 아님(다른 스레드가 풀 수 있음)", bp.lock_obs(ST2, "futex_wait_queue", UNTIMED, futex_nr=202)["cand"] is False)
ck("실행 중(R) = 후보 아님", bp.lock_obs(STR, "futex_wait_queue", UNTIMED, futex_nr=202)["cand"] is False)
ck("잠(nanosleep) = 후보 아님", bp.lock_obs(ST1, "hrtimer_nanosleep", "35 0x0", futex_nr=202)["cand"] is False)
ck("syscall 글 없음(권한) = 대기 종류 모름(None)", bp.lock_obs(ST1, "futex_wait_queue", None, futex_nr=202)["untimed"] is None)
ck("'running'·다른 시스템 콜 = 모름(None)", bp.lock_obs(ST1, "futex_wait_queue", "running", futex_nr=202)["untimed"] is None
   and bp.lock_obs(ST1, "futex_wait_queue", "7 0x1 0x2 0x3 0x4 0x5 0x6", futex_nr=202)["untimed"] is None)
nr0 = bp._FUTEX_NR
bp._FUTEX_NR = None
ck("모르는 CPU(번호표 없음) = 모름(None)", bp.lock_obs(ST1, "futex_wait_queue", UNTIMED)["untimed"] is None)
bp._FUTEX_NR = nr0
ck("깨진 글 = 후보 아님(예외 없음)", bp.lock_obs("garbage", "", "zz")["cand"] is False)


def walk(seq, dt=0.25):
    prev, t = None, 1000.0
    for obs, n in seq:
        for _ in range(n):
            t += dt
            prev, dl = bp.lock_step(prev, obs, t)
            if dl:
                return round(t - 1000.0, 2)
    return None


U = {"cand": True, "untimed": True, "csw": 42}
TM = {"cand": True, "untimed": False, "csw": 42}
UNK = {"cand": True, "untimed": None, "csw": 42}
t_u = walk([(U, 40)])
ck(f"시간 제한 없는 대기 = DEADLOCK_S({bp.DEADLOCK_S:g}초) 무렵 교착", t_u is not None and bp.DEADLOCK_S <= t_u <= bp.DEADLOCK_S + 0.5, t_u)
ck("시간 제한 있는 대기 = 60초 쉬어도 교착 아님(종전 = 3초에 오판 → 3번 죽이고 웹 안 빌드)", walk([(TM, 240)]) is None)
t_k = walk([(UNK, 200)])
ck(f"대기 종류 모름 + 문맥 전환 그대로 = DEADLOCK_UNK_S({bp.DEADLOCK_UNK_S:g}초)에 교착 · DEADLOCK_S 엔 아님",
   t_k is not None and bp.DEADLOCK_UNK_S <= t_k <= bp.DEADLOCK_UNK_S + 0.5, t_k)
loop = []
for i in range(12):
    loop.append(({"cand": True, "untimed": None, "csw": 42 + 2 * i}, 24))
ck("대기 종류 모름 + 6초마다 깨어남(문맥 전환 늘어남) = 72초 동안 교착 아님", walk(loop) is None)
ck("시간 제한 없는 대기라도 문맥 전환이 늘면 창을 다시(깨어났다 다시 잠든 것)",
   walk([({"cand": True, "untimed": True, "csw": 42 + i}, 1) for i in range(40)]) is None)
ck("못 읽음(None)·후보 아님 = 초기화", bp.lock_step((1.0, 3), None, 99.0) == (None, False)
   and bp.lock_step((1.0, 3), {"cand": False, "untimed": True, "csw": 3}, 99.0) == (None, False))
ck("SQLite 뮤텍스 교착 감지 시간 그대로(DEADLOCK_S 3초 · FORK_TRIES 3)", bp.DEADLOCK_S == 3.0 and bp.FORK_TRIES == 3 and bp.DEADLOCK_UNK_S < bp.STALL_S)

ck("종료 상태 글: 코드·신호·모름", bp._status_text(9 << 8) == "종료 코드 9" and bp._status_text(int(signal.SIGKILL)) == "신호 9(SIGKILL)"
   and bp._status_text(None) == "상태 모름", [bp._status_text(9 << 8), bp._status_text(int(signal.SIGKILL))])
sd = os.path.join(T.TMP, "sw")
os.makedirs(os.path.join(sd, "sub"))
now = time.time()
for name, age in ((".tmp_old", 7200), (".tmp_new", 5), ("keep.json", 7200), ("sub/.tmp_old2", 7200)):
    p = os.path.join(sd, name)
    open(p, "w").write("x")
    os.utime(p, (now - age, now - age))
n = bp.sweep_tmp(min_age=3600, root=sd, now=now)
left = sorted(os.path.relpath(os.path.join(dp, f), sd) for dp, _d, fs in os.walk(sd) for f in fs)
ck("임시 파일 정리: 1시간 넘은 .tmp_* 만(하위 한 단계 포함) · 새 것·다른 파일 그대로", n == 2 and left == [".tmp_new", "keep.json"], left)
p = os.path.join(sd, ".tmp_mid")
open(p, "w").write("x")
os.utime(p, (now - 100, now - 100))
ck("since(fork 시각) 전 파일은 강제 종료 정리 대상 아님", bp.sweep_tmp(min_age=30, since=now - 50, root=sd, now=now) == 0 and os.path.exists(p))
ck("since 뒤·min_age 넘은 것만 정리", bp.sweep_tmp(min_age=30, since=now - 200, root=sd, now=now) == 1 and not os.path.exists(p))

plan0, mem0 = bp.plan, bp._mem_avail_mb
st0 = dict(bp._ST)
try:
    bp.plan = lambda: {"on": False, "core": None, "cores": 8, "why": "리눅스 아님 — 웹 안에서 빌드(코어 지정 기능 없음)"}
    ck("계획 꺼짐(맥·코어 1개·TJ_BUILD_PROC=off) = 웹 안 · '돌아간' 기록 없음", bp.usable() is False and (bp.note_inproc() or bp._ST.get("inproc_last") is None))
    bp.plan = lambda: {"on": True, "core": 5, "cores": 6, "why": "합성"}
    bp._mem_avail_mb = lambda: 500
    ck("램 여유 부족 = 웹 안 · 이유 기록", bp.usable() is False and "램 여유 500MB" in str(bp._ST.get("why_in")))
    bp.note_inproc()
    ck("계획은 별도 프로세스인데 웹 안으로 = 그때·이유 남김(상태 패널)", "램 여유" in str((bp._ST.get("inproc_last") or {}).get("why")))
    bp._mem_avail_mb = lambda: 8000
    bp._ST.update(fails=0, pause_until=0.0)
    ck("램 충분 · 쉼 아님 = 별도 프로세스", bp.usable() is True)
    for _ in range(bp.FAIL_MAX):
        bp._fail("합성 실패")
    ck(f"연속 실패 {bp.FAIL_MAX}번 = {bp.FAIL_PAUSE_S // 60}분 쉼(웹 안) · 직전 실패 이유", bp.usable() is False and bp._ST["pause_until"] > time.time()
       and "합성 실패" in str(bp._ST.get("why_in")), bp._ST)
    s9 = bp.status()
    ck("진단 칸(상태 패널): 쉼 남은 초 · fail_max · pause_min", s9["paused"] > 0 and s9["fail_max"] == bp.FAIL_MAX and s9["pause_min"] == bp.FAIL_PAUSE_S // 60)
finally:
    bp.plan, bp._mem_avail_mb = plan0, mem0
    bp._ST.clear()
    bp._ST.update(st0)
ck("dict 키 단위 차이(바뀐·새 · 지운 키)", bp._keyed_diff({"a": 1, "b": 2}, {"a": 1, "b": 3, "c": 4}) == ({"b": 3, "c": 4}, [])
   and bp._keyed_diff({"a": 1}, {}) == ({}, ["a"]) and bp._keyed_diff(None, {}) is None)


class Fn:
    def __init__(self, f):
        self.f, self.restype = f, None

    def __call__(self, *a):
        return self.f(*a)


class Lib:
    def __init__(self, cfg_rcs, used=0, ver=None, has_used=True):
        rcs = list(cfg_rcs)
        self.sqlite3_config = Fn(lambda *a: rcs.pop(0) if len(rcs) > 1 else rcs[0])
        self.sqlite3_shutdown = Fn(lambda: 0)
        if has_used:
            self.sqlite3_memory_used = Fn(lambda: used)
        import sqlite3 as _s
        v = (ver or _s.sqlite_version).encode()
        self.sqlite3_libversion = Fn(lambda: v)


import sqlite3
ck("같은 라이브러리(파이썬 연결 뒤 다시 설정 = MISUSE 21 · 통계 0 · 버전 같음) = 끔(확인)", common._memstatus_apply(Lib([0, 21])) is True
   and "확인" in common.SQLITE_MEMSTAT_WHY[0])
ck("다른 사본(파이썬 연결이 그 사본을 초기화하지 않음 = 다시 설정 0) = 못 끔 · 사유", common._memstatus_apply(Lib([0, 0])) is False
   and "다른 SQLite" in common.SQLITE_MEMSTAT_WHY[0], common.SQLITE_MEMSTAT_WHY[0])
ck("통계가 여전히 셈(memory_used > 0) = 못 끔", common._memstatus_apply(Lib([0, 21], used=4096)) is False and "여전히" in common.SQLITE_MEMSTAT_WHY[0])
ck("버전 다름 = 못 끔", common._memstatus_apply(Lib([0, 21], ver="3.0.0")) is False and "버전" in common.SQLITE_MEMSTAT_WHY[0])
ck("이미 초기화(MISUSE) + 파이썬 sqlite3 이미 있음 = 못 끔(되돌리지 않음)", common._memstatus_apply(Lib([21])) is False and "거부" in common.SQLITE_MEMSTAT_WHY[0])
ck("확인 도구가 없음 = '확인 불가'(끔이라고 적지 않음)", common._memstatus_apply(Lib([0, 21], has_used=False)) == "unverified"
   and "확인 불가" in common.SQLITE_MEMSTAT_WHY[0])
if not sys.platform.startswith("linux"):
    ck("리눅스 아님 = 해당 없음(None — 자식 빌드를 안 씀)", common.sqlite_memstatus_off() is None)
code = ("import json,sys;sys.path.insert(0,sys.argv[1]);import common;lib,src=common._sqlite_lib();r=common._memstatus_apply(lib);"
        "print(json.dumps([r,src,common.SQLITE_MEMSTAT_WHY[0]]))")
pr = subprocess.run([sys.executable, "-c", code, T.SRC], capture_output=True, text=True, timeout=60,
                    env={k: v for k, v in os.environ.items() if not k.startswith("TJ_")} | {"TJ_BASE": T.TMP})
try:
    r9, src9, why9 = json.loads(pr.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    r9, src9, why9 = "err", "", pr.stderr[-300:]
ck(f"이 파이썬의 실제 SQLite: 세 갈래 중 하나 + 사유(지금 = {r9} · {src9} · {why9})", r9 in (True, False, "unverified") and why9, pr.stderr[-300:])
T.finish()
