#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import hashlib
import json
import os
import sqlite3
import subprocess
import time

import common
import db as dbm
import health
import unit_runner as U
import version

sys.path.insert(0, os.path.join(T.ROOT, "tools"))
import ledger_restore as LR

LIVE = common.DB_PATH


def ck(name, cond, extra=None):
    T.chk(bool(cond), name, extra)


def mk(path, data_rev=None, extra_meta=()):
    for sfx in ("", "-wal", "-shm"):
        if os.path.exists(path + sfx):
            os.remove(path + sfx)
    c = dbm.open_db(path)
    for k, v in extra_meta:
        c.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (k, v))
    if data_rev is not None:
        c.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('data_rev', ?)", (str(data_rev),))
    c.commit()
    c.execute("PRAGMA journal_mode=DELETE")
    c.close()


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


mk(LIVE, None, (("exf_fut_place_v", "2:1791500000"), ("exf_fut_from_binance", "1791400000")))
c = dbm.open_db(LIVE)
ck("[1] data_rev 없는 원장(선물 이관 표식만 있음) = 열림 · 개정 0 · 거부 사유 없음", dbm.ledger_data_rev(c) == 0 and dbm.data_rev_refusal(c) is None)
c.close()
mk(LIVE, dbm.DATA_REV)
c = dbm.open_db(LIVE)
ck("[1] 원장 개정 = 코드 개정 = 열림", dbm.data_rev_refusal(c) is None)
c.close()

mk(LIVE, dbm.DATA_REV + 1)
h0 = sha(LIVE)
try:
    dbm.open_db(LIVE)
    r2 = "열림"
except SystemExit as e:
    r2 = str(e)
ck("[2] 원장 개정 = 코드 + 1 → 쓰기 연결 거부(업데이트·백업 안내)", "새 데이터 변환" in r2 and "ledger_restore" in r2 and "업데이트" in r2, r2)
ck("[2] 거부해도 원장 바이트 그대로", sha(LIVE) == h0)
ro = dbm.open_db(LIVE, readonly=True)
ck("[2] 읽기 전용 연결(화면·도구 읽기)은 그대로 열림", ro.execute("SELECT v FROM meta WHERE k='data_rev'").fetchone()[0] == str(dbm.DATA_REV + 1))
ro.close()
base = os.path.join(T.TMP, "inst")
os.makedirs(os.path.join(base, "state"))
json.dump({"chains": {}, "wallets": []}, open(os.path.join(base, "config.json"), "w"))
mk(os.path.join(base, "state", "ledger.db"), dbm.DATA_REV + 1)
env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_")}
env.update(TJ_BASE=base, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8", HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9")
p = subprocess.run([sys.executable, os.path.join(T.SRC, "core.py")], env=env, capture_output=True, text=True, timeout=120)
o = p.stdout + p.stderr
ck("[2] core.py = 0 아닌 종료 · '원장이 이 코드보다 새 데이터 변환' 안내 · 트레이스백 없음", p.returncode != 0 and "새 데이터 변환" in o and "Traceback" not in o,
   (p.returncode, o[-400:]))

mk(LIVE, None)
c = dbm.open_db(LIVE)
ck("[3] bump 0 → 1", dbm.bump_data_rev(c, 1) == 1 and dbm.ledger_data_rev(c) == 1)
c.commit()
ck("[3] 같은 번호 다시 = 그대로(멱등)", dbm.bump_data_rev(c, 1) == 1)
try:
    dbm.bump_data_rev(c, dbm.DATA_REV + 1)
    r3 = "통과"
except ValueError as e:
    r3 = str(e)
ck("[3] 코드가 모르는 번호로 올리기 = 거부(DATA_REV 먼저)", "DATA_REV" in r3, r3)
c.execute("UPDATE meta SET v='x' WHERE k='data_rev'")
ck("[3] 해석 못 하는 값 = 거부 사유(판단 불가)", "읽을 수 없어요" in (dbm.data_rev_refusal(c) or ""))
c.rollback()
c.close()

mk(LIVE, dbm.DATA_REV + 1)


class Stop(Exception):
    pass


got = {"popen": 0, "beats": []}
real = (U.subprocess.Popen, U._sleep, U._beat, U._evaluate)
U.subprocess.Popen = lambda *a, **k: (got.__setitem__("popen", got["popen"] + 1), (_ for _ in ()).throw(Stop()))[1]
U._sleep = lambda s: (_ for _ in ()).throw(Stop())
U._beat = lambda unit, **kw: got["beats"].append(kw)
U._evaluate = lambda unit: (True, "", "fp")
U._stop["sig"] = None
sys.argv = ["unit_runner.py", "core"]
try:
    U.main()
except Stop:
    pass
finally:
    U.subprocess.Popen, U._sleep, U._beat, U._evaluate = real
b4 = (got["beats"] or [{}])[-1]
ck("[4] 유닛 러너 = core 를 띄우지 않고 대기(why '원장이 이 코드보다 새 …')", got["popen"] == 0 and b4.get("state") == "waiting"
   and str(b4.get("why")).startswith("원장이 이 코드보다 새"), (got["popen"], b4))
it = health.ledger_wait_item(dict(b4, ts=time.time()), time.time())
ck("[4] 상태 패널·웹 배너 = '원장이 코드보다 새 판 — 코드 업데이트 필요'", it and it["id"] == "ledger:newer" and "업데이트" in it["action"], it)
bk = os.path.join(T.TMP, "bk_newer.db")
mk(bk, dbm.DATA_REV + 1)
ck4 = LR.check(bk)
ck("[4] 복구 도구 check = 코드보다 새 개정 백업 거부(코드 먼저 최신으로)", ck4["ok"] is False and any("데이터 개정" in w for w in ck4["why"]), ck4["why"])
mk(bk, None)
ck("[4] 개정 없는 백업 = 통과(종전 백업)", LR.check(bk)["ok"] is True, LR.check(bk)["why"])

ck("[5] VERSION 파일 = 버전 문자열", version.app_version() not in ("", None) and (
   version.app_version() == open(version.VERSION_FILE, encoding="utf-8").readline().strip() if os.path.exists(version.VERSION_FILE) else version.app_version() == "알 수 없음"),
   version.app_version())
saved = version.VERSION_FILE
try:
    version.VERSION_FILE = os.path.join(T.TMP, "VERSION_missing")
    version._cache.update(mt=None, v=None)
    ck("[5] VERSION 없음 = '알 수 없음'", version.app_version() == "알 수 없음")
    version.VERSION_FILE = os.path.join(T.TMP, "VERSION_bad")
    open(version.VERSION_FILE, "w").write("<script>\n")
    ck("[5] 이상한 VERSION = '알 수 없음'(화면에 그대로 안 냄)", version.app_version() == "알 수 없음")
finally:
    version.VERSION_FILE = saved
    version._cache.update(mt=None, v=None)
T.finish()
