#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import os
import time

import common
import health
import ledger_backup as lb
import unit_beat

S = common.STATE_DIR
NOW = time.time()


def ck(name, cond, extra=None):
    T.chk(bool(cond), name, extra)


def wj(name, obj):
    common.atomic_write_json(os.path.join(S, name), obj)


def rm(name):
    try:
        os.remove(os.path.join(S, name))
    except FileNotFoundError:
        pass


WAIT_MISSING = {"unit": "core", "pid": 1, "ts": int(NOW) - 10, "state": "waiting", "since": int(NOW) - 900,
                "why": "원장 파일 없음 — 백업에서 되돌리기 필요(python3 tools/ledger_restore.py list)", "evidence": ["원장 백업 2개(state/backups)"]}

rm("health_status.json")
rm("runner_alert.json")
wj("runner_core.json", WAIT_MISSING)
v = health.web_view(NOW)
ck("[1] tj-alert 없음 + 원장 없음 대기 = 빨강", v["overall"] == "crit", v.get("overall"))
ck("[1] 열린 문제 맨 앞 = '원장 파일 없음 — 복구 필요'(복구 명령 · 시작 시각)", v["open"] and v["open"][0]["id"] == "ledger:missing"
   and "ledger_restore" in v["open"][0]["action"] and v["open"][0]["since"] == int(NOW) - 900, v.get("open"))
ck("[1] 배너 재료 ledgerWait", (v.get("ledgerWait") or {}).get("kind") == "missing", v.get("ledgerWait"))
ck("[1] 감시 유닛 꺼짐 표시(monitorOff · 켜는 명령)", v.get("monitorOff") is True and "pm2 start tj-alert" in v.get("note", ""), v.get("note"))
c = health.compact(v)
ck("[1] 앱 상태 요약에도 ledger·monitorOff", (c.get("ledger") or {}).get("id") == "ledger:missing" and c.get("monitorOff") is True and c["crit"] == 1, c)
rm("runner_core.json")
v0 = health.web_view(NOW)
ck("[1] 원장 문제 없음 + tj-alert 없음 = 회색(unknown) · monitorOff 만", v0["overall"] == "unknown" and v0.get("monitorOff") is True and "ledgerWait" not in v0, v0)

unit_beat.beat_once("alert", now=NOW - 5)
v2 = health.web_view(NOW)
ck("[2] 감시 유닛 살아 있음 + 첫 점검 전 = monitorOff 아님 · '첫 점검 전'", not v2.get("monitorOff") and "첫 점검 전" in v2.get("note", ""), v2.get("note"))
rm("runner_alert.json")
os.environ["TJ_DEMO"] = "1"
try:
    v3 = health.web_view(NOW)
finally:
    del os.environ["TJ_DEMO"]
ck("[2] 데모 = monitorOff 아님(배너 없음)", not v3.get("monitorOff"), v3)

wj("health_status.json", {"v": 1, "updatedAt": NOW - 30, "interval": 60, "overall": "crit",
                          "open": [{"id": "ledger:missing", "check": "ledger:missing", "unit": "tj-core", "title": "원장 파일 없음 — 복구 필요", "level": "crit"}],
                          "resolved": [], "watching": [], "units": []})
wj("runner_core.json", WAIT_MISSING)
v4 = health.web_view(NOW)
ck("[3] 판정에 이미 같은 문제 = 중복 없음(1건) · ledgerWait 는 붙음", sum(1 for x in v4["open"] if x.get("id") == "ledger:missing") == 1 and v4.get("ledgerWait"), v4["open"])
rm("runner_core.json")
wj("health_status.json", {"v": 1, "updatedAt": NOW - 30, "interval": 60, "overall": "ok", "open": [], "resolved": [], "watching": [], "units": []})
c5 = health.compact(health.web_view(NOW))
ck("[3] 원장 대기 없음 = 앱 상태 요약 키 종전 그대로(5개)", sorted(c5) == ["crit", "overall", "stale", "updatedAt", "warn"], c5)

wj("runner_core.json", {"unit": "core", "pid": 1, "ts": int(NOW) - 5, "state": "waiting", "why": lb.CORRUPT_WHY, "evidence": ["빠른 검사(quick_check) 실패: x"]})
open(common.DB_PATH, "wb").close()
v6 = health.web_view(NOW)
ck("[4] 원장 손상 대기 = 열린 문제 맨 앞 '원장 손상 — 복구 필요' · 배너 재료", v6["open"][0]["id"] == "ledger:corrupt" and (v6.get("ledgerWait") or {}).get("kind") == "corrupt"
   and v6["overall"] == "crit", (v6["open"][:1], v6.get("ledgerWait")))
T.finish()
