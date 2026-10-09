#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import random
import shutil
import subprocess
import time

import common
import db as dbm
import health
import ledger_backup as lb
import unit_runner as U

S = common.STATE_DIR
LIVE = common.DB_PATH


def ck(name, cond, extra=None):
    T.chk(bool(cond), name, extra)


def make_ledger(path, rows=1500):
    for sfx in ("", "-wal", "-shm"):
        if os.path.exists(path + sfx):
            os.remove(path + sfx)
    c = dbm.open_db(path)
    rnd = random.Random(7)
    for i in range(rows):
        c.execute("INSERT INTO raw_txs (chain, txhash, block, blockhash, ts, snapshot, wallets, ingested_at) VALUES (?,?,?,?,?,?,?,?)",
                  ("eth", "0x%064x" % i, i, None, None, json.dumps({"x": "%030x" % rnd.getrandbits(120) * 40}), "[]", 1700000000 + i))
    c.commit()
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.close()


def smash(path, off, n):
    with open(path, "r+b") as f:
        f.seek(off)
        f.write(random.Random(off).randbytes(n) if hasattr(random.Random, "randbytes") else os.urandom(n))


make_ledger(LIVE)
ok1 = lb.ledger_check_light(LIVE)
ck("[1] 멀쩡한 원장 = 가벼운 검사 통과", ok1[0] and not ok1[1], ok1)
ck("[1] 멀쩡한 원장 = 깊은 검사 통과", lb.ledger_check_deep(LIVE) == (True, ""))
GOOD = os.path.join(T.TMP, "good.db")
shutil.copyfile(LIVE, GOOD)
smash(LIVE, 0, 100)
r1 = lb.ledger_check_light(LIVE)
ck("[1] 머리 100바이트 덮어쓰기 = 손상(머리가 SQLite 원장이 아님)", r1[0] is False and "머리" in r1[1], r1)
shutil.copyfile(GOOD, LIVE)
with open(LIVE, "r+b") as f:
    f.truncate(os.path.getsize(LIVE) - 1000)
r1 = lb.ledger_check_light(LIVE)
ck("[1] 끝이 잘림 = 손상(페이지 배수 아님)", r1[0] is False and "배수" in r1[1], r1)
shutil.copyfile(GOOD, LIVE)
t0 = time.time()
for _ in range(20):
    lb.ledger_check_light(LIVE)
ck("[1] 가벼운 검사 = 빠름(20번 < 1초)", time.time() - t0 < 1.0, round(time.time() - t0, 3))
ck("[1] 잠김·권한 같은 '검사 못 함'은 손상으로 보지 않음(없는 파일)", lb.ledger_check_light(os.path.join(T.TMP, "nope.db"))[0] is True)


class Stop(Exception):
    pass


class FakeProc:
    def __init__(self, rc):
        self.returncode = rc
        self.pid = 4242

    def poll(self):
        return self.returncode

    def send_signal(self, _s):
        pass

    def kill(self):
        pass

    def wait(self, *a):
        return self.returncode


def drive(child_rc=None, sleeps=3):
    got = {"popen": 0, "beats": []}
    n = {"s": 0}

    def fake_popen(argv, env=None, **k):
        got["popen"] += 1
        if child_rc is None:
            raise Stop()
        return FakeProc(child_rc)

    def fake_sleep(_s):
        n["s"] += 1
        if n["s"] >= sleeps:
            raise Stop()

    real = (U.subprocess.Popen, U._sleep, U._beat, U._evaluate)
    U.subprocess.Popen, U._sleep = fake_popen, fake_sleep
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
    return got["popen"], (got["beats"] or [{}])[-1]


smash(LIVE, 0, 100)
n2, b2 = drive(child_rc=1)
ck("[2] 머리가 깨진 원장 = core 를 띄우지 않음", n2 == 0, n2)
ck("[2] 하트비트 = 대기 · '원장 손상 — …' · 검사 사유", b2.get("state") == "waiting" and str(b2.get("why")).startswith("원장 손상")
   and "ledger_restore" in str(b2.get("why")) and b2.get("evidence"), b2)
shutil.copyfile(GOOD, LIVE)
mid = (os.path.getsize(LIVE) // 2) // 4096 * 4096
smash(LIVE, mid, 60 * 1024)
ck("[2] (전제) 중간 60KB 덮어쓰기 = quick_check 실패", lb.ledger_check_deep(LIVE)[0] is False, lb.ledger_check_deep(LIVE))
n2, b2 = drive(child_rc=1)
ck("[2] 작은 원장 중간 손상 = 시작 전 quick_check 로 잡아 띄우지 않고 대기", n2 == 0 and str(b2.get("why")).startswith("원장 손상"), (n2, b2))

saved_max, saved_light = lb.DEEP_PRESTART_MAX, lb.ledger_check_light
lb.DEEP_PRESTART_MAX = 0
lb.ledger_check_light = lambda p: (True, "")
try:
    n3, b3 = drive(child_rc=1, sleeps=4)
finally:
    lb.DEEP_PRESTART_MAX, lb.ledger_check_light = saved_max, saved_light
ck("[3] 큰 원장: 한 번 띄움 → 빨리 죽음 → quick_check 로 손상 확인 → 다시 안 띄움(재시작 반복 없음)", n3 == 1, n3)
ck("[3] … 그 뒤 대기 하트비트 '원장 손상'", b3.get("state") == "waiting" and str(b3.get("why")).startswith("원장 손상"), b3)
lb.DEEP_PRESTART_MAX = 0
try:
    shutil.copyfile(GOOD, LIVE)
    n3, b3 = drive(child_rc=1, sleeps=3)
finally:
    lb.DEEP_PRESTART_MAX = saved_max
ck("[3] 멀쩡한 원장인데 빨리 죽음(다른 원인) = 검사 통과 → 보통 재시작(대기 아님)", n3 >= 2 and b3.get("state") == "restarting", (n3, b3))

smash(LIVE, 0, 100)
got4 = {"n": 0}
real_check = U.ledger_backup.ledger_check_light


def swap_after_first(p):
    got4["n"] += 1
    r = real_check(p)
    if got4["n"] == 1:
        os.replace(GOOD + ".copy", LIVE)
    return r


shutil.copyfile(GOOD, GOOD + ".copy")
U.ledger_backup.ledger_check_light = swap_after_first
try:
    n4, b4 = drive(child_rc=None, sleeps=5)
finally:
    U.ledger_backup.ledger_check_light = real_check
ck("[4] 대기 중 원장 파일이 바뀌면(복구) 다시 검사해 띄움", n4 == 1, (n4, b4, got4))
shutil.copyfile(GOOD, LIVE)
n4, b4 = drive(child_rc=None)
ck("[4] 멀쩡한 원장 = 바로 띄움", n4 == 1, n4)

base5 = os.path.join(T.TMP, "inst5")
os.makedirs(os.path.join(base5, "state"))
with open(os.path.join(base5, "config.json"), "w", encoding="utf-8") as f:
    json.dump({"chains": {}, "wallets": []}, f)
shutil.copyfile(GOOD, os.path.join(base5, "state", "ledger.db"))
smash(os.path.join(base5, "state", "ledger.db"), 0, 100)
env5 = {k: v for k, v in os.environ.items() if not k.startswith("TJ_")}
env5.update(TJ_BASE=base5, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8", HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9")
p5 = subprocess.run([sys.executable, os.path.join(T.SRC, "core.py")], env=env5, capture_output=True, text=True, timeout=120)
o5 = p5.stdout + p5.stderr
ck("[5] core.py 직접 실행 + 머리 깨진 원장 = 종료 코드 3 · 복구 안내 · 트레이스백 없음",
   p5.returncode == 3 and "원장 손상" in o5 and "ledger_restore" in o5 and "Traceback" not in o5, (p5.returncode, o5[-600:]))

NOW = time.time()
it6 = health.ledger_wait_item({"state": "waiting", "why": lb.CORRUPT_WHY, "ts": NOW - 20, "evidence": ["빠른 검사(quick_check) 실패: x"]}, NOW, db_path=GOOD)
ck("[6] 원장 손상 대기 = '원장 손상 — 복구 필요' 항목(복구 명령)", it6 and it6["id"] == "ledger:corrupt" and "ledger_restore" in it6["action"], it6)
ck("[6] 10분 넘게 갱신 없는 러너 기록 = 항목 없음(러너가 꺼짐 — 다른 점검 몫)",
   health.ledger_wait_item({"state": "waiting", "why": lb.CORRUPT_WHY, "ts": NOW - 900}, NOW, db_path=GOOD) is None)
ck("[6] 지갑 등록 감시기(by=reload) 기록은 무시", health.ledger_wait_item({"state": "waiting", "why": lb.CORRUPT_WHY, "ts": NOW, "by": "reload"}, NOW, db_path=GOOD) is None)
h6 = health.settings({})
ch6 = {c["id"]: c for c in health.evaluate({"now": NOW, "pm2": {}, "runner": {"core": {"state": "waiting", "why": lb.CORRUPT_WHY, "ts": NOW, "evidence": ["x"]}}}, h6)}
ck("[6] 상태 판정(tj-alert) = ledger:corrupt 빨강", ch6.get("ledger:corrupt", {}).get("level") == "crit", ch6.get("ledger:corrupt"))
T.finish()
