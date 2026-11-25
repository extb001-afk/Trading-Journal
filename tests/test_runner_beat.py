#!/usr/bin/env python3
# 유닛 러너 하트비트(runner_<unit>.json) 쓰기 간격 — 같은 내용은 BEAT_SEC 마다만 · 상태가 바뀌면 바로 · 실패 뒤 다시 · env 값 검증
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import importlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402

import paths  # noqa: E402
import statefile  # noqa: E402
import unit_runner as U  # noqa: E402

P = paths.state("runner_tbeat.json")
CLOCK = [1000.0]
WRITES = []
_real_aw = statefile.atomic_write_json


def _aw(path, obj, **kw):
    if os.path.basename(path) == "runner_tbeat.json":
        WRITES.append(dict(obj))
    return _real_aw(path, obj, **kw)


statefile.atomic_write_json = _aw
_real_mono = U.time.monotonic
U.time.monotonic = lambda: CLOCK[0]   # time 모듈 공용 — 아래 B 시험 끝에 되돌림
U._mem_view = lambda: None


def beat(**kw):
    n0 = len(WRITES)
    U._beat("tbeat", **kw)
    return len(WRITES) > n0


def at(sec):
    CLOCK[0] = 1000.0 + sec


T.chk(U.BEAT_SEC == U.BEAT_DEFAULT == 60.0 and U.BEAT_MAX == 90.0, "B0 기본 간격 60초 · 상한 90초", (U.BEAT_SEC, U.BEAT_MAX))
run = dict(state="running", why="", fp="f1", child=11)
at(0)
T.chk(beat(**run), "B1 첫 기록은 바로 씀")
seen = []
for s in (15, 30, 45, 59.9):
    at(s)
    seen.append(beat(**run))
T.chk(seen == [False] * 4, "B2 같은 내용 60초 안(15·30·45·59.9초) = 안 씀", seen)
at(60)
T.chk(beat(**run), "B3 같은 내용 60초 = 씀")
at(61)
T.chk(beat(state="restarting", why="설정 변경 감지 — 새 설정으로 재시작", fp="f1"), "B4 상태 바뀜(running → restarting) = 바로 씀")
at(62)
T.chk(beat(state="running", why="", fp="f1", child=12), "B5 자식 pid 바뀜 = 바로 씀")
at(63)
T.chk(beat(state="running", why="", fp="f2", child=12), "B6 설정 지문 바뀜 = 바로 씀")
with open(P, encoding="utf-8") as f:
    rec = json.load(f)
T.chk(rec.get("fp") == "f2" and rec.get("child") == 12 and rec.get("unit") == "tbeat" and isinstance(rec.get("ts"), int),
      "B7 파일 = 마지막 기록 그대로(fp·child·unit·ts 벽시계 정수)", rec)

statefile.atomic_write_json = lambda *a, **k: (_ for _ in ()).throw(OSError("시험: 쓰기 실패"))
at(200)
U._beat("tbeat", state="running", why="", fp="f2", child=12)
statefile.atomic_write_json = _aw
at(201)
T.chk(beat(state="running", why="", fp="f2", child=12), "B8 쓰기 실패 뒤 다음 호출 = 다시 씀(실패를 '썼음'으로 두지 않음)")

wall = U.time.time
U.time.time = lambda: wall() - 3600   # 벽시계를 한 시간 뒤로 — 간격 비교는 단조 시계라 영향 없어야 함
at(262)
T.chk(beat(state="running", why="", fp="f2", child=12), "B9 벽시계가 뒤로 가도 단조 시계로 60초 지나면 씀")
U.time.time = wall
U.time.monotonic = _real_mono


def reload_with(env):
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        m = importlib.reload(U)
        return m.CHECK_SEC, m.SETTLE_SEC, m.BEAT_SEC
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


bad = {v: reload_with({"TJ_RUNNER_BEAT_SEC": v}) for v in ("", "abc", "0", "-5", "nan", "inf")}
T.chk(all(r[2] == 60.0 for r in bad.values()), "E1 TJ_RUNNER_BEAT_SEC 빈 값·글자·0·음수·nan·inf = 경고 뒤 기본 60초(임포트 실패 없음)", bad)
T.chk(reload_with({"TJ_RUNNER_BEAT_SEC": "1e9"})[2] == 90.0 and reload_with({"TJ_RUNNER_BEAT_SEC": "30"})[2] == 30.0,
      "E2 큰 값 = 상한 90초 · 정상 값 30 = 그대로")
T.chk(reload_with({"TJ_RUNNER_CHECK_SEC": "60"})[2] == 60.0, "E3 점검 간격을 바꿔도 하트비트 기본 60초(점검 간격 × 4 아님)")
r4 = reload_with({"TJ_RUNNER_CHECK_SEC": "", "TJ_RUNNER_SETTLE_SEC": "x"})
T.chk(r4[:2] == (15.0, 10.0), "E4 TJ_RUNNER_CHECK_SEC·SETTLE_SEC 잘못된 값 = 기본 15·10초", r4)
src = open(U.__file__, encoding="utf-8").read()
i9 = src.index('if reason.startswith("설정"):')
T.chk('_beat(unit, state="restarting"' in src[i9:i9 + 400] and src.index("_beat(unit, state=\"restarting\"", i9) < src.index("_stop_child(p)", i9),
      "E5 설정 변경 재시작 = 자식 끊기 전에 restarting 하트비트(메모리 경로와 같음)")
T.finish()
