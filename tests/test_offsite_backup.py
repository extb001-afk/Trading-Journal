#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
import time

os.environ["TJ_HEALTH"] = "0"
sys.path.insert(0, os.path.join(T.ROOT, "tools"))
import common
import db as dbm
import ledger_backup as lb
import offsite_backup as OB

S = common.STATE_DIR
REMOTE = os.path.join(T.TMP, "remote_box", "tj_offsite")
KEY = os.path.join(T.TMP, "fake_key")
open(KEY, "w").write("x")


def ck(name, cond, extra=None):
    T.chk(bool(cond), name, extra)


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


c = dbm.open_db(common.DB_PATH)
for i in range(200):
    c.execute("INSERT INTO raw_txs VALUES('eth', ?, ?, NULL, ?, '{}', '[]', ?)", (f"0x{i:04x}", i, 1_700_000_000 + i, 1_700_000_000 + i))
c.commit()
c.close()
for n, obj in (("other_assets.json", {"v": 1, "items": [{"name": "합성 자산"}]}), ("settings.json", {"telegram": {"bot_name": "x"}}),
               ("nft_prefs.json", {"hide": []}), ("day_memos.json", {"v": 1, "memos": {}}), ("ui_prefs.json", {"a": 1})):
    common.atomic_write_json(os.path.join(S, n), obj)
with open(os.path.join(S, ".env.bak"), "w") as f:
    f.write("SECRET=1")
lb.MIN_FREE = 0
st = lb.run_once(log=None)
ck("[5] 정기 백업 성공", st.get("last_ok") and not st.get("err"), st)
fdir = [n for n in os.listdir(lb.BACKUP_DIR) if n.startswith("files_")][0]
got5 = set(os.listdir(os.path.join(lb.BACKUP_DIR, fdir)))
ck("[5] 원장 밖 사본에 기타 자산·설정·NFT 설정·메모", {"other_assets.json", "settings.json", "nft_prefs.json", "day_memos.json"} <= got5, sorted(got5))
ck("[5] .env 류는 안 넣음", not any(n.startswith(".env") for n in got5), sorted(got5))
open(os.path.join(lb.BACKUP_DIR, fdir, ".env.leak"), "w").write("SECRET=1")
lb.MIN_FREE = 512 * 1024 ** 2
real_du = shutil.disk_usage
shutil.disk_usage = lambda p: type("U", (), {"free": 600 * 1024 ** 2, "total": 0, "used": 0})()
try:
    st2 = lb.run_once(log=None, now=time.time() + 86400)
finally:
    shutil.disk_usage = real_du
ck("[5] 작은 원장 + 여유 600MB = 건너뛰지 않음(종전 10GB 고정 기준이면 건너뜀)", st2.get("skip") is None, st2)

os.makedirs(os.path.dirname(REMOTE), exist_ok=True)
SENT = []


def fake_remote(cfg, script, timeout=120):
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError(f"원격 명령 실패 rc={r.returncode}: {r.stderr.strip()[-200:]}")
    return r.stdout


def fake_send(cfg, files, timeout=0):
    for f in files:
        SENT.append(os.path.basename(f))
        shutil.copyfile(f, os.path.join(REMOTE, ".incoming", os.path.basename(f)))


def fake_recv(cfg, name, dst, timeout=0):
    src = os.path.join(REMOTE, name)
    if not os.path.exists(src):
        raise RuntimeError("없음")
    shutil.copyfile(src, dst)


OB.remote, OB.send, OB.recv = fake_remote, fake_send, fake_recv
CFG = {"backup": {"offsite": {"enabled": True, "mode": "push", "host": "backup.invalid", "user": "backup", "port": 22, "key": KEY,
                              "path": REMOTE, "keep": 2, "keep_local": 1, "bwlimit_kbps": 1024, "every_h": 24, "warn_h": 36}}}
with open(common.CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump(CFG, f)
ck("[2] 설정 검사 통과", OB.problems(OB.conf()) == [], OB.problems(OB.conf()))
ck("[2] 설정 빠짐 = 문제 목록", OB.problems(OB.conf({"backup": {"offsite": {"enabled": True}}})) != [])

NOW = time.time()
rc = OB.run(now=NOW, log=lambda *a: None)
stt = OB.read_status()
ck("[2] 보내기 성공 · 상태 last_ok", rc == 0 and stt.get("last_ok") and not stt.get("err"), stt)
names = sorted(n for n in os.listdir(REMOTE) if not n.startswith("."))
stamp = stt.get("last_stamp")
ck("[2] 원격 = 원장 압축본 · 원장 밖 사본 · manifest", names == sorted([f"{stamp}.db.gz", f"{stamp}.files.tar.gz", f"{stamp}.manifest.json"]), names)
ck("[2] manifest 를 마지막에 보냄", SENT[-1].endswith(".manifest.json"), SENT)
ck("[2] 받는 중 폴더 비움", os.listdir(os.path.join(REMOTE, ".incoming")) == [])
man = json.load(open(os.path.join(REMOTE, f"{stamp}.manifest.json"), encoding="utf-8"))
ck("[1] manifest sha256 = 원격 파일", man["db"]["sha256"] == sha(os.path.join(REMOTE, f"{stamp}.db.gz")))
ck("[1] 오늘 정기 백업을 재사용(같은 디스크에 새 스냅숏 안 뜸) · 검사 ok · 세대", man["source"].startswith("ledger_") and man["db"]["quick_check"] == "ok"
   and str(man["db"]["schema_version"]) == str(dbm.SCHEMA_VERSION), man)
raw = gzip.open(os.path.join(REMOTE, f"{stamp}.db.gz")).read()
ck("[1] 압축 풀면 원장 스냅숏(같은 sha256)", hashlib.sha256(raw).hexdigest() == man["db"]["raw_sha256"])
with tarfile.open(os.path.join(REMOTE, f"{stamp}.files.tar.gz")) as tf:
    tn = tf.getnames()
ck("[1] 원장 밖 사본 묶음에 기타 자산 · .env 류 없음", any(n.endswith("other_assets.json") for n in tn) and not any(".env" in n for n in tn), tn)
ck("[2] 이 컴퓨터 묶음 = 1개(keep_local)", len(OB.local_stamps()) == 1)
ck("[2] 간격(24시간) 전엔 안 함", OB.run(now=NOW + 3600, log=lambda *a: None) == 0 and OB.read_status().get("last_stamp") == stamp)

for k in (1, 2):
    os.utime(os.path.join(lb.BACKUP_DIR, sorted(n for n in os.listdir(lb.BACKUP_DIR) if n.startswith("ledger_"))[-1]), None)
    rc = OB.run(now=NOW + k * 86400 + 60, force=True, log=lambda *a: None)
stamps = OB.remote_stamps(OB.conf())
ck("[2] 원격 보관 수 = 2(오래된 것 지움)", rc == 0 and len(stamps) == 2 and stamp not in stamps, stamps)

def bad_send(cfg, files, timeout=0):
    for f in files:
        dst = os.path.join(REMOTE, ".incoming", os.path.basename(f))
        shutil.copyfile(f, dst)
        if f.endswith(".db.gz"):
            with open(dst, "r+b") as fh:
                fh.seek(10)
                fh.write(b"\x00\x01\x02")


OB.send = bad_send
before3 = sorted(os.listdir(REMOTE))
rc = OB.run(now=NOW + 5 * 86400, force=True, log=lambda *a: None)
st3 = OB.read_status()
ck("[3] 깨진 전송 = 실패 · 상태에 이유", rc == 1 and "sha256" in str(st3.get("err")), st3)
inc3 = os.listdir(os.path.join(REMOTE, ".incoming"))
ck("[3] 깨진 원장 압축본 지움 · 제자리엔 새 묶음 없음", not any(n.endswith(".db.gz") for n in inc3) and sorted(os.listdir(REMOTE)) == before3,
   (inc3, sorted(os.listdir(REMOTE))))
ck("[2] 실패 뒤 3시간은 쉼(강제 아니면)", OB.run(now=NOW + 5 * 86400 + 600, log=lambda *a: None) == 0 and OB.read_status().get("err_at") == st3.get("err_at"))
OB.send = fake_send

def fail_send(cfg, files, timeout=0):
    raise RuntimeError("시험: 보내기 실패")


OB.send = fail_send
for k in (10, 11, 12):
    OB.run(now=NOW + k * 86400, force=True, log=lambda *a: None)
OB.send = fake_send
ck("[2] 전송 실패 반복 = 이 컴퓨터 묶음 keep_local 개만(wl314 ④)", len(OB.local_stamps()) == 1, OB.local_stamps())

for bad9 in ("/srv/$(id)", "/srv/a b", "/srv/`id`", "/srv/;rm", "/srv/../etc", "relative/path"):
    ck(f"[1] 경로 거부: {bad9!r}", OB.problems(OB.conf({"backup": {"offsite": dict(CFG["backup"]["offsite"], path=bad9)}})) != [])
ck("[1] 경로 허용: ~/tj_offsite · /srv/tj-off_2.x", OB.problems(OB.conf({"backup": {"offsite": dict(CFG["backup"]["offsite"], path="~/tj_offsite")}})) == []
   and OB.problems(OB.conf({"backup": {"offsite": dict(CFG["backup"]["offsite"], path="/srv/tj-off_2.x")}})) == [])
ck("[1] 사용자 거부: 'a;b'", OB.problems(OB.conf({"backup": {"offsite": dict(CFG["backup"]["offsite"], user="a;b")}})) != [])
ck("[1] 호스트 거부: 'h$(id)'", OB.problems(OB.conf({"backup": {"offsite": dict(CFG["backup"]["offsite"], host="h$(id)")}})) != [])
ck("[1] rsync 3.1 = -s(인자 보호) · 3.2.4+ 기본 보호 · openrsync = 없음(허용 문자로 막음)",
   OB.rsync_protect_args("rsync  version 3.1.3  protocol version 31") == ["-s"]
   and OB.rsync_protect_args("rsync  version 3.2.7  protocol version 31") == []
   and OB.rsync_protect_args("openrsync: protocol version 29") == [], (OB.rsync_protect_args("rsync  version 3.1.3  protocol version 31"),))
ck("[1] 실행 때도 설정 검사(잘못된 경로 = 보내지 않음)", OB.run(cfg={"backup": {"offsite": dict(CFG["backup"]["offsite"], path="/srv/$(id)")}},
                                                   force=True, log=lambda *a: None) == 2)

p4 = OB.fetch(OB.conf(), None, log=lambda *a: None)
m4 = json.load(open(os.path.join(REMOTE, f"{OB.remote_stamps(OB.conf())[-1]}.manifest.json"), encoding="utf-8"))
ck("[4] 받은 원장 = 원본 바이트(sha256)", sha(p4) == m4["db"]["raw_sha256"])
ck("[4] 받은 원장 열림", sqlite3.connect(common.sqlite_ro_uri(p4, immutable=True), uri=True).execute("SELECT count(*) FROM raw_txs").fetchone()[0] == 200)

KEEP9 = ["keep_me.txt", "tjoff_notes.txt", "tjoff_20261001_0000.db.gz.bak", ".tjoff_debug", ".tjoff_20261001_0000.db.gz.toolong9"]
for n9 in ["tjoff_19990101_0000.db.gz", ".tjoff_19990101_0000.db.gz.Ab12Cd", "tjoff_19990101_0000.files.tar.gz"] + KEEP9:
    open(os.path.join(REMOTE, ".incoming", n9), "w").write("x")
rc = OB.run(now=NOW + 40 * 86400, force=True, log=lambda *a: None)
inc9 = sorted(os.listdir(os.path.join(REMOTE, ".incoming")))
ck("[3] 새 전송 전에 지난 묶음 찌꺼기 정리(wl316 ③) · 이름 규칙 밖 파일은 둠(wl318 ②)", rc == 0 and inc9 == sorted(KEEP9), inc9)

os.remove(OB.STATUS)
CFG_OB = {"backup": {"offsite": {"enabled": True, "mode": "outbox", "keep_local": 2, "every_h": 24, "warn_h": 36}}}
rc = OB.run(cfg=CFG_OB, now=NOW + 50 * 86400, force=True, log=lambda *a: None)
st9 = OB.read_status()
ck("[2] outbox 묶음 생성 = last_built 만 · last_ok 없음(wl316 ②)", rc == 0 and st9.get("last_built") and not st9.get("last_ok"), st9)
ck("[2] outbox 생성 간격도 last_built 기준(24시간 안 다시 안 만듦)", OB.run(cfg=CFG_OB, now=NOW + 50 * 86400 + 3600, log=lambda *a: None) == 0
   and OB.read_status().get("last_built") == st9.get("last_built"))
man9 = json.load(open(os.path.join(OB.OUT_DIR, f"{st9['last_stamp']}.manifest.json"), encoding="utf-8"))
ck("[2] confirm sha256 틀림 = 거부 · last_ok 그대로 없음", OB.confirm(st9["last_stamp"], "0" * 64, log=lambda *a: None) != 0 and not OB.read_status().get("last_ok"))
ck("[2] confirm sha256 맞음 = last_ok = 그 묶음을 만든 시각(지금 아님 — wl318 ①)", OB.confirm(st9["last_stamp"], man9["db"]["sha256"], log=lambda *a: None) == 0
   and OB.read_status().get("last_ok") == int(man9["created"]) and OB.read_status().get("confirmed_stamp") == st9["last_stamp"], OB.read_status())
before9 = dict(OB.read_status())
time.sleep(1.1)
ck("[2] 같은 묶음 다시 confirm = 상태 그대로(멱등 — 새 묶음이 멈추면 경보가 나야 함)", OB.confirm(st9["last_stamp"], man9["db"]["sha256"], log=lambda *a: None) == 0
   and OB.read_status() == before9, (before9, OB.read_status()))
ck("[2] 없는 묶음 confirm = 거부", OB.confirm("tjoff_19990101_0000", man9["db"]["sha256"], log=lambda *a: None) != 0)

import health as H
UNITS = ["tj-core", "tj-web"]
HS = H.settings({"health": {"units": UNITS}})
HN = 1_800_000_000.0


def ev(**extra):
    obs = {"now": HN, "pm2": {u: {"status": "online", "restarts": 0, "pid": 1} for u in UNITS}, "bal_mem": {}, "prev_inc": {}, "sources": []}
    obs.update(extra)
    return {c9["id"]: c9 for c9 in H.evaluate(obs, HS)}


b = ev(backup={"created": HN - 10 * 86400, "last_ok": HN - 40 * 3600, "size": 1})["backup:age"]
ck("[6] 원장 백업 40시간 = 주황 · 알림 없음(종전)", b["level"] == "warn" and b["notify"] is False, b)
b = ev(backup={"created": HN - 10 * 86400, "last_ok": HN - 4 * 86400, "size": 1})["backup:age"]
ck("[6] 원장 백업 4일 = 빨강 · 텔레그램 · '4일째'", b["level"] == "crit" and b["notify"] is True and "4일째" in b["title"], b)
b = ev(backup={"created": HN - 10 * 86400, "last_ok": HN - 3600, "skip": "disk", "skip_at": HN - 60, "free": 1 << 30, "need": 6 << 30})["backup:age"]
ck("[6] 디스크 부족 문구 = 실제 필요량", "필요 6.0GB" in b["detail"], b)
cks = ev(backup=None)
ck("[6] 서버 밖 백업 꺼짐 = 점검 없음", "offsite:age" not in cks)
o = ev(offsite={"enabled": True, "warn_h": 36, "status": {"last_ok": HN - 3600, "last_stamp": "tjoff_x", "size": 1 << 30, "dest": "backup.invalid:/srv"}})
ck("[6] 서버 밖 백업 1시간 전 = 초록", o["offsite:age"]["level"] == "ok", o["offsite:age"])
o = ev(offsite={"enabled": True, "warn_h": 36, "status": {"last_ok": HN - 40 * 3600}})
ck("[6] 서버 밖 백업 40시간 = 주황 · 알림 없음", o["offsite:age"]["level"] == "warn" and o["offsite:age"]["notify"] is False, o["offsite:age"])
o = ev(offsite={"enabled": True, "warn_h": 36, "status": {"last_ok": HN - 4 * 86400, "err": "RuntimeError: 원격 명령 실패", "err_at": HN - 600}})
ck("[6] 서버 밖 백업 4일 + 실패 = 빨강 · 알림 · 실패 이유", o["offsite:age"]["level"] == "crit" and o["offsite:age"]["notify"] is True
   and "원격 명령 실패" in o["offsite:age"]["detail"], o["offsite:age"])
o = ev(offsite={"enabled": True, "warn_h": 36, "status": None})
ck("[6] 켰는데 아직 성공 없음 = 주황", o["offsite:age"]["level"] == "warn", o["offsite:age"])
o = ev(offsite={"enabled": True, "warn_h": 36, "since": HN - 4 * 86400, "status": {"first_try": HN - 4 * 86400, "last_try": HN - 600,
                                                                                    "err": "RuntimeError: 원격 명령 실패", "err_at": HN - 600}})
ck("[6] 한 번도 성공 못 하고 4일(켠 때·첫 시도부터 셈) = 빨강·알림(wl314 ③)", o["offsite:age"]["level"] == "crit" and o["offsite:age"]["notify"] is True,
   o["offsite:age"])
o = ev(offsite={"enabled": True, "warn_h": 36, "since": HN - 4 * 86400, "status": None})
ck("[6] 켰는데 크론이 한 번도 안 돎 4일 = 빨강·알림", o["offsite:age"]["level"] == "crit" and o["offsite:age"]["notify"] is True, o["offsite:age"])
o = ev(offsite={"enabled": True, "warn_h": 36, "since": HN - 4 * 86400, "status": {"first_try": HN - 4 * 86400, "last_built": HN - 3600,
                                                                                    "dest": "outbox(받는 쪽 확인 대기)"}})
ck("[6] outbox 매일 만들기만 하고 받는 쪽 확인 4일 없음 = 빨강·알림(wl316 ②)", o["offsite:age"]["level"] == "crit" and o["offsite:age"]["notify"] is True,
   o["offsite:age"])
hst = {}
ob1 = H._offsite_obs({"backup": {"offsite": {"enabled": True}}}, hst, HN - 100)
ob2 = H._offsite_obs({"backup": {"offsite": {"enabled": True}}}, hst, HN)
ck("[6] 켠 시각 기억(상태 패널 기억 · 다음 판에도 같은 값)", ob1["since"] == HN - 100 and ob2["since"] == HN - 100, (ob1, ob2))
H._offsite_obs({"backup": {"offsite": {"enabled": False}}}, hst, HN)
ck("[6] 끄면 기억 지움", "offsite_since" not in hst, hst)
os.rename(common.DB_PATH, common.DB_PATH + ".moved")
m = ev(runner={"core": {"state": "waiting", "why": "원장 파일 없음 — 백업에서 되돌리기 필요", "evidence": ["원장 백업 2개"], "ts": int(HN)}})
ck("[6] 원장 없음 대기 = 빨강 · 복구 명령", m.get("ledger:missing", {}).get("level") == "crit" and "ledger_restore" in m["ledger:missing"]["action"], m.get("ledger:missing"))
os.rename(common.DB_PATH + ".moved", common.DB_PATH)
m = ev(runner={"core": {"state": "waiting", "why": "원장 파일 없음 — 백업에서 되돌리기 필요", "ts": int(HN)}})
ck("[6] 원장이 다시 생기면 점검 없음", "ledger:missing" not in m)
T.finish()
