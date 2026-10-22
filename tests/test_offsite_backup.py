#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import gzip  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402
import tarfile  # noqa: E402
import time  # noqa: E402

os.environ["TJ_HEALTH"] = "0"
sys.path.insert(0, os.path.join(T.ROOT, "tools"))
import paths, statefile  # noqa: E402
import db as dbm  # noqa: E402
import ledger_backup as lb  # noqa: E402
import offsite_backup as OB  # noqa: E402

S = paths.STATE_DIR
REMOTE = os.path.join(T.TMP, "remote_box", "tj_offsite")
KEY = os.path.join(T.TMP, "fake_key")
open(KEY, "w").write("x")


def ck(name, cond, extra=None):
    T.chk(bool(cond), name, extra)


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


c = dbm.open_db(paths.DB_PATH)
for i in range(200):
    c.execute("INSERT INTO raw_txs VALUES('eth', ?, ?, NULL, ?, '{}', '[]', ?)", (f"0x{i:04x}", i, 1_700_000_000 + i, 1_700_000_000 + i))
c.commit()
c.close()
for n, obj in (("other_assets.json", {"v": 1, "items": [{"name": "합성 자산"}]}), ("settings.json", {"telegram": {"bot_name": "x"}}),
               ("nft_prefs.json", {"hide": []}), ("day_memos.json", {"v": 1, "memos": {}}), ("ui_prefs.json", {"a": 1})):
    statefile.atomic_write_json(os.path.join(S, n), obj)
with open(os.path.join(S, ".env.bak"), "w") as f:
    f.write("SECRET=1")
lb.MIN_FREE = 0
os.makedirs(paths.state("backups"), exist_ok=True)
TMP5 = ["ledger_19990101.db.tmp", "ledger_19990101.db.tmp-journal", "ledger_19990102.db.tmp-wal"]
for n5 in TMP5 + ["ledger_19990101.db.tmp.keep"]:
    open(os.path.join(paths.state("backups"), n5), "w").write("x")
st = lb.run_once(log=None)
ck("[5] 지난날 임시 사본 찌꺼기(.db.tmp · -journal · -wal)도 지움 · 이름 규칙 밖은 둠",
   not (set(TMP5) & set(os.listdir(paths.state("backups")))) and os.path.exists(os.path.join(paths.state("backups"), "ledger_19990101.db.tmp.keep")))
os.remove(os.path.join(paths.state("backups"), "ledger_19990101.db.tmp.keep"))
SP5 = os.path.join(T.TMP, "sparse5.db")
with open(SP5, "wb") as f:
    f.truncate(1 << 43)
open(os.path.join(paths.state("backups"), TMP5[0]), "w").write("x")
st5 = lb.run_once(db_path=SP5, log=None)
ck("[5] 디스크 부족 건너뜀 판에도 지난날 임시 사본 찌꺼기 먼저 지움", st5.get("skip") == "disk" and not os.path.exists(os.path.join(paths.state("backups"), TMP5[0])), st5)
os.remove(SP5)
ck("[5] 정기 백업 성공", st.get("last_ok") and not st.get("err"), st)
fdir = [n for n in os.listdir(paths.state("backups")) if n.startswith("files_")][0]
got5 = set(os.listdir(os.path.join(paths.state("backups"), fdir)))
ck("[5] 원장 밖 사본에 기타 자산·설정·NFT 설정·메모", {"other_assets.json", "settings.json", "nft_prefs.json", "day_memos.json"} <= got5, sorted(got5))
ck("[5] .env 류는 안 넣음", not any(n.startswith(".env") for n in got5), sorted(got5))
open(os.path.join(paths.state("backups"), fdir, ".env.leak"), "w").write("SECRET=1")
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
with open(paths.CONFIG_PATH, "w", encoding="utf-8") as f:
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
    os.utime(os.path.join(paths.state("backups"), sorted(n for n in os.listdir(paths.state("backups")) if n.startswith("ledger_"))[-1]), None)
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
ck("[2] 전송 실패 반복 = 이 컴퓨터 묶음 keep_local 개만", len(OB.local_stamps()) == 1, OB.local_stamps())
ck("[2] O: 실패 문구 = 도구가 만든 한국어 그대로(원시 오류 이름 'RuntimeError:' 없음)", OB.read_status().get("err") == "시험: 보내기 실패", OB.read_status().get("err"))
ck("[2] O: 디스크 가득 = 쉬운 말", "디스크가 가득" in OB.err_text(OSError(28, "No space left on device")))

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
ck("[4] 받은 원장 열림", sqlite3.connect(paths.sqlite_ro_uri(p4, immutable=True), uri=True).execute("SELECT count(*) FROM raw_txs").fetchone()[0] == 200)

KEEP9 = ["keep_me.txt", "tjoff_notes.txt", "tjoff_20261001_0000.db.gz.bak", ".tjoff_debug", ".tjoff_20261001_0000.db.gz.toolong9"]
for n9 in ["tjoff_19990101_0000.db.gz", ".tjoff_19990101_0000.db.gz.Ab12Cd", "tjoff_19990101_0000.files.tar.gz"] + KEEP9:
    open(os.path.join(REMOTE, ".incoming", n9), "w").write("x")
rc = OB.run(now=NOW + 40 * 86400, force=True, log=lambda *a: None)
inc9 = sorted(os.listdir(os.path.join(REMOTE, ".incoming")))
ck("[3] 새 전송 전에 지난 묶음 찌꺼기 정리 · 이름 규칙 밖 파일은 둠", rc == 0 and inc9 == sorted(KEEP9), inc9)

os.remove(OB.STATUS)
CFG_OB = {"backup": {"offsite": {"enabled": True, "mode": "outbox", "keep_local": 2, "every_h": 24, "warn_h": 36}}}
rc = OB.run(cfg=CFG_OB, now=NOW + 50 * 86400, force=True, log=lambda *a: None)
st9 = OB.read_status()
ck("[2] outbox 묶음 생성 = last_built 만 · last_ok 없음", rc == 0 and st9.get("last_built") and not st9.get("last_ok"), st9)
ck("[2] outbox 생성 간격도 last_built 기준(24시간 안 다시 안 만듦)", OB.run(cfg=CFG_OB, now=NOW + 50 * 86400 + 3600, log=lambda *a: None) == 0
   and OB.read_status().get("last_built") == st9.get("last_built"))
man9 = json.load(open(os.path.join(OB.OUT_DIR, f"{st9['last_stamp']}.manifest.json"), encoding="utf-8"))
ck("[2] confirm sha256 틀림 = 거부 · last_ok 그대로 없음", OB.confirm(st9["last_stamp"], "0" * 64, log=lambda *a: None) != 0 and not OB.read_status().get("last_ok"))
ck("[2] confirm sha256 맞음 = last_ok = 그 묶음을 만든 시각(지금 아님)", OB.confirm(st9["last_stamp"], man9["db"]["sha256"], log=lambda *a: None) == 0
   and OB.read_status().get("last_ok") == int(man9["created"]) and OB.read_status().get("confirmed_stamp") == st9["last_stamp"], OB.read_status())
before9 = dict(OB.read_status())
time.sleep(1.1)
ck("[2] 같은 묶음 다시 confirm = 상태 그대로(멱등 — 새 묶음이 멈추면 경보가 나야 함)", OB.confirm(st9["last_stamp"], man9["db"]["sha256"], log=lambda *a: None) == 0
   and OB.read_status() == before9, (before9, OB.read_status()))
ck("[2] 없는 묶음 confirm = 거부", OB.confirm("tjoff_19990101_0000", man9["db"]["sha256"], log=lambda *a: None) != 0)

import health as H  # noqa: E402
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
b = ev(backup={"created": HN - 10 * 86400, "last_ok": HN - 25 * 3600, "skip": "disk", "skip_at": HN - 60, "free": 1 << 30, "need": 6 << 30})["backup:age"]
ck("[6] W2 디스크 부족 건너뜀 · 마지막 백업 25시간 = 주황(오늘 몇 번 더 시도)", b["level"] == "warn" and b["notify"] is False, b)
b = ev(backup={"created": HN - 10 * 86400, "last_ok": HN - 31 * 3600, "skip": "disk", "skip_at": HN - 60, "free": 1 << 30, "need": 6 << 30})["backup:age"]
ck("[6] W2 디스크 부족 건너뜀 · 마지막 백업 31시간 = 빨강 · 텔레그램 · '디스크 부족'", b["level"] == "crit" and b["notify"] is True and "디스크 부족" in b["title"], b)
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
ck("[6] 한 번도 성공 못 하고 4일(켠 때·첫 시도부터 셈) = 빨강·알림", o["offsite:age"]["level"] == "crit" and o["offsite:age"]["notify"] is True,
   o["offsite:age"])
o = ev(offsite={"enabled": True, "warn_h": 36, "since": HN - 4 * 86400, "status": None})
ck("[6] 켰는데 크론이 한 번도 안 돎 4일 = 빨강·알림", o["offsite:age"]["level"] == "crit" and o["offsite:age"]["notify"] is True, o["offsite:age"])
o = ev(offsite={"enabled": True, "warn_h": 36, "since": HN - 4 * 86400, "status": {"first_try": HN - 4 * 86400, "last_built": HN - 3600,
                                                                                    "dest": "outbox(받는 쪽 확인 대기)"}})
ck("[6] outbox 매일 만들기만 하고 받는 쪽 확인 4일 없음 = 빨강·알림", o["offsite:age"]["level"] == "crit" and o["offsite:age"]["notify"] is True,
   o["offsite:age"])
hst = {}
ob1 = H._offsite_obs({"backup": {"offsite": {"enabled": True}}}, hst, HN - 100)
ob2 = H._offsite_obs({"backup": {"offsite": {"enabled": True}}}, hst, HN)
ck("[6] 켠 시각 기억(상태 패널 기억 · 다음 판에도 같은 값)", ob1["since"] == HN - 100 and ob2["since"] == HN - 100, (ob1, ob2))
H._offsite_obs({"backup": {"offsite": {"enabled": False}}}, hst, HN)
ck("[6] 끄면 기억 지움", "offsite_since" not in hst, hst)
os.rename(paths.DB_PATH, paths.DB_PATH + ".moved")
m = ev(runner={"core": {"state": "waiting", "why": "원장 파일 없음 — 백업에서 되돌리기 필요", "evidence": ["원장 백업 2개"], "ts": int(HN)}})
ck("[6] 원장 없음 대기 = 빨강 · 복구 명령", m.get("ledger:missing", {}).get("level") == "crit" and "ledger_restore" in m["ledger:missing"]["action"], m.get("ledger:missing"))
os.rename(paths.DB_PATH + ".moved", paths.DB_PATH)
m = ev(runner={"core": {"state": "waiting", "why": "원장 파일 없음 — 백업에서 되돌리기 필요", "ts": int(HN)}})
ck("[6] 원장이 다시 생기면 점검 없음", "ledger:missing" not in m)
import contextlib  # noqa: E402
import io  # noqa: E402
c7 = OB.conf({"backup": {"offsite": {"enabled": True, "host": "box.invalid", "user": "bk", "port": 2222, "path": "/srv/x", "key": KEY}}})
sc7 = OB.scp_cmd(c7)
ck("[7] scp 도 ConnectTimeout·끊김 감지·호스트 키 규칙(ssh 와 같게)", "ConnectTimeout=20" in sc7 and "ServerAliveInterval=30" in sc7
   and "StrictHostKeyChecking=accept-new" in sc7 and sc7[sc7.index("-P") + 1] == "2222", sc7)
ck("[7] 지문 칸 없음 = ssh·scp 둘 다 accept-new(종전)", OB.ssh_cmd(c7).count("StrictHostKeyChecking=accept-new") == 1 and c7["host_key_fpr"] == [])
BLOB7 = "AAAAC3NzaC1lZDI1NTE5AAAAI" + "A" * 43
c7f = OB.conf({"backup": {"offsite": dict(c7, host_key_fpr=OB.seal.key_fpr(BLOB7) + "=")}})
with open(OB.KNOWN_HOSTS, "w") as f:
    f.write("[box.invalid]:2222 ssh-ed25519 %s\n" % BLOB7)
s7f, sc7f = OB.ssh_cmd(c7f), OB.scp_cmd(c7f)
ck("[7] 지문 칸 있음 = ssh·scp 둘 다 StrictHostKeyChecking=yes + 전용 known_hosts(accept-new 없음)",
   all("StrictHostKeyChecking=yes" in a and "UserKnownHostsFile=" + OB.KNOWN_HOSTS in a and "GlobalKnownHostsFile=/dev/null" in a
       and not any("accept-new" in x for x in a) for a in (s7f, sc7f)) and OB.problems(c7f) == [], [s7f, sc7f])
ck("[7] 지문 칸 꼴 아님 = 설정 문제(보내지 않음)", any("host_key_fpr" in x for x in OB.problems(dict(c7f, host_key_fpr=["MD5:aa"]))))
os.remove(OB.KNOWN_HOSTS)
real_which, real_remote, real_conf = OB.shutil.which, OB.remote, OB.conf


def run_test(which_has, remote_out, cmd=("test",)):
    OB.shutil.which = lambda n: ("/usr/bin/" + n) if n in which_has else None
    OB.remote = (lambda c, script, timeout=120: remote_out) if not isinstance(remote_out, Exception) else \
        (lambda c, script, timeout=120: (_ for _ in ()).throw(remote_out))
    OB.conf = lambda cfg=None: c7
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = OB.main(list(cmd))
    except Exception as e:   # noqa: BLE001
        rc = "Traceback " + repr(e)
    finally:
        OB.shutil.which, OB.remote, OB.conf = real_which, real_remote, real_conf
    return rc, out.getvalue(), err.getvalue()


r7 = run_test({"ssh"}, "/dev/x 100 1 99 1% /srv\n/usr/bin/sha256sum\nTJ_RSYNC_OK\n")
ck("[7] 이 컴퓨터에 rsync·scp 가 없으면 test = 실패(종전 '연결 정상')", r7[0] == 1 and "보낼 도구 없음" in r7[1], r7)
r7 = run_test({"ssh", "rsync"}, "/dev/x 100 1 99 1% /srv\n/usr/bin/sha256sum\nTJ_RSYNC_NO\n")
ck("[7] 이 컴퓨터는 rsync 인데 원격에 rsync 없음 = 실패 안내", r7[0] == 1 and "원격에 rsync" in r7[1], r7)
r7 = run_test({"ssh", "scp"}, "/dev/x 100 1 99 1% /srv\n/usr/bin/sha256sum\nTJ_RSYNC_NO\n")
ck("[7] scp 만 있으면 정상(원격 rsync 불필요) · 어떤 도구로 보내는지 표시", r7[0] == 0 and "scp" in r7[1] and "연결 정상" in r7[1], r7)
r7 = run_test({"ssh", "rsync"}, RuntimeError("원격 명령 실패 rc=255: Connection timed out"))
ck("[7] 연결 실패 = 한 줄 안내(traceback 없음)", r7[0] == 1 and "연결 실패" in r7[1], r7)
DOWN = RuntimeError("원격 명령 실패 rc=255: ssh: connect to host backup.invalid port 22: Connection refused")
r8 = run_test({"ssh", "rsync"}, DOWN, ("list-remote",))
ck("[8] list-remote 연결 실패 = 묶음 목록(stdout) 비움 · 한 줄 안내는 stderr · rc 1(Traceback 없음)",
   r8[0] == 1 and r8[1] == "" and "연결 실패" in r8[2] and "Connection refused" in r8[2], r8)
r8 = run_test({"ssh", "rsync"}, "", ("list-remote",))
ck("[8] list-remote 원격 빈 폴더 = 묶음 목록(stdout) 비움 · 안내는 stderr · rc 0", r8[0] == 0 and r8[1] == "" and "묶음이 없어요" in r8[2], r8)
r8 = run_test({"ssh", "rsync"}, "x\n%s.manifest.json\n" % stamp, ("list-remote",))
ck("[8] list-remote 묶음 있음 = 묶음 이름 한 줄씩(종전 그대로)", r8[0] == 0 and r8[1] == stamp + "\n" and r8[2] == "", r8)
r8 = run_test({"ssh", "rsync"}, DOWN, ("fetch",))
ck("[8] fetch 연결 실패 = 한 줄 안내 · rc 1(Traceback 없음)", r8[0] == 1 and "실패" in r8[1] and "Connection refused" in r8[1], r8)
r8 = run_test({"ssh", "rsync"}, "", ("fetch",))
ck("[8] fetch 원격에 묶음 없음 = 한 줄 안내 · rc 1(Traceback 없음)", r8[0] == 1 and "원격에 묶음이 없어요" in r8[1], r8)
Q = lambda *a: None   # noqa: E731
T9 = float(int(NOW + 60 * 86400) // 60 * 60)
m9 = OB.build(now=T9, log=Q)
s9 = m9["stamp"]
mb9 = open(os.path.join(OB.OUT_DIR, s9 + ".manifest.json"), "rb").read()
gz9 = sha(os.path.join(OB.OUT_DIR, s9 + ".db.gz"))
c9 = dbm.open_db(paths.DB_PATH)
c9.execute("INSERT INTO raw_txs VALUES('eth', '0xf11', 999, NULL, 1700000999, '{}', '[]', 1700000999)")
c9.commit()
c9.close()
try:
    OB.build(now=T9 + 5, log=Q)
    e9 = None
except RuntimeError as e:
    e9 = str(e)
ck("[9] F11 같은 분 두 번째 묶음 = 거부(1분 뒤) · 앞 묶음 manifest·압축본 그대로 · 그대로 열림",
   e9 and "같은 분" in e9 and open(os.path.join(OB.OUT_DIR, s9 + ".manifest.json"), "rb").read() == mb9
   and sha(os.path.join(OB.OUT_DIR, s9 + ".db.gz")) == gz9
   and os.path.isfile(OB.seal.open_bundle(OB.OUT_DIR, s9, os.path.join(T.TMP, "open9"), OB.seal.load_key(OB.AUTH_KEY), log=Q)), e9)
ck("[9] F11 다음 분은 그대로 만듦", OB.build(now=T9 + 60, log=Q)["stamp"] != s9)
REF9 = {"stamp": "tjoff_20990101_0000", "auth": {"kid": "aaaaaaaa"}, "db": {"raw_size": 1000, "data_until": 1_800_000_000}}
OK9 = {"stamp": "tjoff_20990102_0000", "auth": {"kid": "aaaaaaaa"}, "db": {"raw_size": 1100, "data_until": 1_800_050_000}}
ck("[9] A7-01 후퇴 판정: 정상(같은 열쇠·커짐) = 없음 · 서명 없는 옛 원격 묶음(auth 칸 없음) = 크기·시각만 · auth 칸 꼴 아님 = 비교 불가", OB.regress_reasons(REF9, OK9) == []
   and OB.regress_reasons({k: v for k, v in REF9.items() if k != "auth"}, dict(OK9, auth={"kid": "bbbbbbbb"})) == []
   and OB.regress_reasons(dict(REF9, auth=None), OK9) != [])
ck("[9] A7-01 후퇴 판정: 원격 마지막 manifest 못 읽음 · 자료 시각이 숫자 아님(무한·글자) = 비교 불가 이유(예외 없음)",
   OB.regress_reasons(None, OK9) != [] and OB.regress_reasons(dict(REF9, db={"raw_size": 1000, "data_until": float("inf")}), OK9) != []
   and OB.regress_reasons(dict(REF9, db={"raw_size": 1000, "data_until": "x"}), OK9) != []
   and OB.regress_reasons(dict(REF9, db={"raw_size": 1000, "data_until": 1e300}), OK9) != []
   and OB.regress_reasons({}, OK9) != [] and OB.regress_reasons(dict(REF9, db={"raw_size": 10 ** 400, "data_until": None}), OK9) != []
   and OB.regress_reasons(dict(REF9, db={"raw_size": "x", "data_until": None}), OK9) != []
   and OB.regress_reasons(dict(REF9, db={"raw_size": 1000}), dict(OK9, db={"raw_size": 1100, "data_until": None})) != []
   and OB.regress_reasons(dict(REF9, db={"raw_size": 1000, "data_until": None}), dict(OK9, db={"raw_size": 1100, "data_until": None})) == [])
ck("[9] A7-01 후퇴 판정: 다른 열쇠 · 크기 절반 밑 · 자료 시각 하루 넘게 이름 · 자료 시각 없음",
   len(OB.regress_reasons(REF9, dict(OK9, auth={"kid": "bbbbbbbb"}))) == 1
   and "크기" in " ".join(OB.regress_reasons(REF9, dict(OK9, db={"raw_size": 400, "data_until": 1_800_050_000})))
   and "시각" in " ".join(OB.regress_reasons(REF9, dict(OK9, db={"raw_size": 1100, "data_until": 1_800_000_000 - 90000})))
   and "시각" in " ".join(OB.regress_reasons(REF9, dict(OK9, db={"raw_size": 1100, "data_until": None}))))
ck("[9] A7-01 기준 run(같은 원장·같은 열쇠) = 보냄", OB.run(cfg=CFG, now=T9 + 3600, force=True, log=Q) == 0, OB.read_status().get("err"))
R9 = sorted(os.listdir(REMOTE))
K9 = open(OB.AUTH_KEY, "rb").read()
st9a = OB.remote_stamps(OB.conf(CFG))
try:
    OB.check_remote(OB.conf(CFG), {"stamp": st9a[-1], "auth": {"kid": OB.seal.kid(K9)}, "db": {}}, log=Q)
    e9 = None
except RuntimeError as e:
    e9 = str(e)
ck("[9] A7-01 원격에 같은 이름 묶음 = 거부", e9 and "같은 이름" in e9, e9)
os.rename(paths.DB_PATH, paths.DB_PATH + ".keep9")
dbm.open_db(paths.DB_PATH).close()
os.remove(OB.STATUS)
os.remove(OB.AUTH_KEY)
rc = OB.run(cfg=CFG, now=T9 + 7200, force=True, log=Q)
e9 = str(OB.read_status().get("err"))
ck("[9] A7-01 새 서버 첫 run(빈 원장·새 열쇠) = 실패 · 이유(열쇠·자료 시각) · 원격 무변(회전 0) · 이번 묶음 지움",
   rc == 1 and "열쇠가 다름" in e9 and "후퇴" in e9 and sorted(os.listdir(REMOTE)) == R9
   and not any(n.startswith(OB.stamp_of(T9 + 7200)) for n in os.listdir(OB.OUT_DIR)), (rc, e9))
ck("[9] A7-03 보내기 전 멈춰도 상태에 이번 열쇠 kid(첫 run 실패 뒤 열쇠를 잃어도 새로 안 만들게)", OB.read_status().get("kid") == OB.seal.kid(open(OB.AUTH_KEY, "rb").read()))
rc = OB.run(cfg=CFG, now=T9 + 10800, force=True, log=Q, allow_regress=True)
for k9 in (4, 5):
    rc = rc or OB.run(cfg=CFG, now=T9 + k9 * 3600, force=True, log=Q)
st9b = OB.remote_stamps(OB.conf(CFG))
new9 = [x for x in st9b if x not in st9a]
ck("[9] A7-01 --allow-regress 뒤 = 보냄 · 원격 회전은 새 열쇠 묶음만(keep 2) · 옛 열쇠 묶음은 전부 남음",
   rc == 0 and set(st9a) <= set(st9b) and len(new9) == 2, (rc, st9a, st9b, OB.read_status().get("err")))
os.remove(paths.DB_PATH)
os.rename(paths.DB_PATH + ".keep9", paths.DB_PATH)
n9 = len(OB.local_stamps()) + 1
r9 = run_test({"ssh", "rsync"}, DOWN, ("run", "--force"))
ck("[9] A7-01 원격에 못 닿음 = 실패 · 이 컴퓨터 묶음 keep_local(1)개로 회전", r9[0] == 1 and n9 >= 2 and len(OB.local_stamps()) == 1
   and "Connection refused" in str(OB.read_status().get("err")), (r9, n9, OB.local_stamps()))
lm9 = os.path.join(REMOTE, OB.remote_stamps(OB.conf(CFG))[-1] + ".manifest.json")
keep9m = open(lm9, "rb").read()
for bad9 in (b"\xff\xfe{\"v\": 1}", b"[" * 100000 + b"]" * 100000):
    open(lm9, "wb").write(bad9)
    loc9 = OB.local_stamps()
    rc = OB.run(cfg=CFG, now=T9 + 5 * 3600 + 60 * (len(bad9) % 50 + 1), force=True, log=Q)
    ck("[9] A7-01 원격 manifest 깨짐(%s) = 멈춤 · 이유 '못 읽음' · 지난 로컬 묶음 그대로" % ("글자" if len(bad9) < 50 else "중첩"),
       rc == 1 and "못 읽음" in str(OB.read_status().get("err")) and OB.local_stamps() == loc9, (rc, OB.read_status().get("err"), loc9, OB.local_stamps()))
open(lm9, "wb").write(keep9m)
mj9 = json.loads(keep9m)
for nm9, bad9 in (("구분자 흉내", keep9m.rstrip() + b"\n==TJMAN x.manifest.json\n{}"), ("auth 칸 kid 꼴 아님", json.dumps(dict(mj9, auth={"kid": 12345678})).encode()),
                  ("auth 빈 칸", json.dumps(dict(mj9, auth={})).encode())):
    open(lm9, "wb").write(bad9)
    loc9 = OB.local_stamps()
    rc = OB.run(cfg=CFG, now=T9 + 5 * 3600 + 60 * (len(nm9) + 7), force=True, log=Q)
    ck(f"[9] A7-01 원격 manifest {nm9} = 비교 불가로 멈춤 · 지난 로컬 묶음 그대로", rc == 1 and "불가" in str(OB.read_status().get("err"))
       and OB.local_stamps() == loc9, (rc, OB.read_status().get("err")))
open(lm9, "wb").write(keep9m)
ck("[9] A7-01 kid 꼴: 숫자·대문자·길이 다름 = 없음 취급(회전 대상 아님)", OB._kid_of({"auth": {"kid": 12345678}}) == "" and OB._kid_of({"auth": {"kid": "ABCDEF12"}}) == ""
   and OB._kid_of({"auth": {"kid": "abcdef12"}}) == "abcdef12")
os.chmod(REMOTE, 0o300)
loc9 = OB.local_stamps()
rc = OB.run(cfg=CFG, now=T9 + 5 * 3600 + 60 * 40, force=True, log=Q)
os.chmod(REMOTE, 0o700)
ck("[9] A7-01 원격 목록 권한 실패 = 멈춤 · 지난 로컬 묶음 그대로 · 원격 무변", rc == 1 and "목록을 못 읽음" in str(OB.read_status().get("err"))
   and OB.local_stamps() == loc9, (rc, OB.read_status().get("err")))
os.chmod(os.path.dirname(REMOTE), 0o600)
rc = OB.run(cfg=CFG, now=T9 + 5 * 3600 + 60 * 41, force=True, log=Q)
os.chmod(os.path.dirname(REMOTE), 0o700)
ck("[9] A7-01 원격 위 폴더 탐색 불가 = 멈춤 · 지난 로컬 묶음 그대로", rc == 1 and "목록을 못 읽음" in str(OB.read_status().get("err"))
   and OB.local_stamps() == loc9, (rc, OB.read_status().get("err")))
K9b = open(OB.AUTH_KEY, "rb").read()
ck("[9] A7-03 상태에 지금 열쇠 kid", OB.read_status().get("kid") == OB.seal.kid(K9b), OB.read_status())
os.remove(OB.AUTH_KEY)
rc = OB.run(cfg=CFG, now=T9 + 6 * 3600, force=True, log=Q)
ck("[9] A7-03 지난 묶음 있음 + 열쇠 없음 = 실패 · 새 열쇠 안 만듦", rc == 1 and "열쇠 파일이 없음" in str(OB.read_status().get("err"))
   and not os.path.lexists(OB.AUTH_KEY), OB.read_status().get("err"))
with open(OB.AUTH_KEY, "wb") as f:
    f.write(K9)
os.chmod(OB.AUTH_KEY, 0o600)
rc = OB.run(cfg=CFG, now=T9 + 7 * 3600 - 60, force=True, log=Q)
st9c = OB.read_status()
ck("[9] A7-03 열쇠 바뀜으로 보내기가 멈춰도 '열쇠 바뀜' 기록", rc == 1 and st9c.get("kid_changed_at") and st9c.get("kid") == OB.seal.kid(K9), st9c)
rc = OB.run(cfg=CFG, now=T9 + 7 * 3600, force=True, log=Q, allow_regress=True)
st9c = OB.read_status()
ck("[9] A7-03 열쇠 바뀐 뒤 run = 상태에 새 kid · 옛 kid · 바뀐 시각", rc == 0 and st9c.get("kid") == OB.seal.kid(K9)
   and st9c.get("kid_prev") == OB.seal.kid(K9b) and st9c.get("kid_changed_at"), st9c)
o = ev(offsite={"enabled": True, "warn_h": 36, "status": st9c}).get("offsite:kid") or {}
ck("[9] A7-03 상태 패널 '열쇠 바뀜' = 주황 · 텔레그램 1회(tg_force) · 두 kid", o.get("level") == "warn" and o.get("tg_force") is True
   and OB.seal.kid(K9) in o.get("detail", "") and OB.seal.kid(K9b) in o.get("detail", ""), o)
buf9 = io.StringIO()
with contextlib.redirect_stdout(buf9):
    rc = OB.main(["auth-key", "--export", os.path.join(T.TMP, "key_copy9")])
ck("[9] A7-03 auth-key --export(새 열쇠 사본 보관) = 경고 풀림", rc == 0 and "kid_changed_at" not in OB.read_status()
   and "offsite:kid" not in ev(offsite={"enabled": True, "warn_h": 36, "status": OB.read_status()}), (rc, buf9.getvalue()))
o = {c9["id"]: c9 for c9 in H.evaluate({"now": HN, "pm2": {u: {"status": "online", "restarts": 0, "pid": 1} for u in UNITS}, "bal_mem": {}, "prev_inc": {},
                                         "sources": [], "offsite": {"enabled": True, "warn_h": 36, "status": OB.read_status()}}, HS, {"offsite:kid"})}
ck("[9] A7-03 열린 '열쇠 바뀜' 사건 = 풀리면 정상(ok) 판정으로 닫힘", (o.get("offsite:kid") or {}).get("level") == "ok", o.get("offsite:kid"))
for kc9 in ("broken", 1e300, float("inf"), float("nan"), 10 ** 400, None, [], ""):
    o = ev(offsite={"enabled": True, "warn_h": 36, "status": {"kid": "aaaaaaaa", "kid_changed_at": kc9}})
    ck(f"[9] A7-03 kid_changed_at {kc9!r:.12} = 판정 계속(예외 없음 · 주황 유지)", (o.get("offsite:kid") or {}).get("level") == "warn", o.get("offsite:kid"))
for bad9 in (None, {}, []):
    o = {c9["id"]: c9 for c9 in H.evaluate({"now": HN, "pm2": {u: {"status": "online", "restarts": 0, "pid": 1} for u in UNITS}, "bal_mem": {}, "prev_inc": {},
                                             "sources": [], "offsite": {"enabled": True, "warn_h": 36, "status": bad9}}, HS, {"offsite:kid"})}
    ck(f"[9] A7-03 열린 '열쇠 바뀜' + 상태 {bad9!r} = 판단 보류(level None · 거짓 복구 없음)", "offsite:kid" in o and o["offsite:kid"]["level"] is None, o.get("offsite:kid"))
import re  # noqa: E402
import chk_collect  # noqa: E402
ck("[9] A7-03 상태 파일 못 읽음 = offsite:kid 도 판정 보류 대상(거짓 복구 안 함)",
   any(re.fullmatch(r9, "offsite:kid") for r9 in chk_collect._unreadable_rules("backups/offsite_status.json")[0]))
K9c = bytes(range(32))
with open(OB.AUTH_KEY, "wb") as f:
    f.write(K9c)
with contextlib.redirect_stdout(io.StringIO()):
    OB.main(["auth-key", "--export", os.path.join(T.TMP, "key_copy9c")])
st9e = OB.read_status()
with open(OB.AUTH_KEY, "wb") as f:
    f.write(K9)
st9n = OB.read_status()
st9n["kid_changed_at"] = None
st9n["kid"] = OB.seal.kid(K9c)
OB.write_status(st9n)
with open(OB.AUTH_KEY, "wb") as f:
    f.write(K9c)
with contextlib.redirect_stdout(io.StringIO()):
    OB.main(["auth-key", "--export", os.path.join(T.TMP, "key_copy9n")])
with open(OB.AUTH_KEY, "wb") as f:
    f.write(K9)
ck("[9] A7-03 kid_changed_at=null 이어도 --export 로 칸 지움", "kid_changed_at" not in OB.read_status(), OB.read_status())
ck("[9] A7-03 run 전 --export = 상태 kid 가 내보낸 열쇠", st9e.get("kid") == OB.seal.kid(K9c) and "kid_changed_at" not in st9e, st9e)
st9e["kid"] = OB.seal.kid(K9)
OB.write_status(st9e)
st9e.pop("kid", None)
OB.write_status(st9e)
with open(OB.AUTH_KEY, "wb") as f:
    f.write(K9c)
OB.run(cfg=CFG, now=T9 + 7 * 3600 + 600, force=True, log=Q, allow_regress=True)
st9f = OB.read_status()
with open(OB.AUTH_KEY, "wb") as f:
    f.write(K9)
ck("[9] A7-03 옛 상태(kid 없음)에서 열쇠 바뀜 = 지난 로컬 manifest kid 기준으로 '바뀜' 기록", st9f.get("kid_prev") == OB.seal.kid(K9)
   and st9f.get("kid") == OB.seal.kid(K9c) and st9f.get("kid_changed_at"), st9f)
OB.run(cfg=CFG, now=T9 + 7 * 3600 + 1200, force=True, log=Q, allow_regress=True)
st9f = OB.read_status()
st9f.pop("kid_changed_at", None)
st9f.pop("kid_prev", None)
OB.write_status(st9f)
CUR9 = OB.stamp_of(T9 + 8 * 3600)
ORPH9 = ["tjoff_19990101_0000.db.gz", "tjoff_19990101_0001.files.tar.gz", "tjoff_19990101_0002.snap.db-journal", "tjoff_19990101_0003.snap.db-wal"]
KEEP9b = ["tjoff_notes.txt", "tjoff_19990101_0004.db.gz.bak", CUR9 + ".db.gz"]
for n9 in ORPH9 + KEEP9b:
    open(os.path.join(OB.OUT_DIR, n9), "w").write("x")
have9 = OB.local_stamps()
os.rename(OB.AUTH_KEY, OB.AUTH_KEY + ".keep9")
rc = OB.run(cfg=CFG, now=T9 + 8 * 3600, force=True, log=Q)
os.rename(OB.AUTH_KEY + ".keep9", OB.AUTH_KEY)
left9 = set(os.listdir(OB.OUT_DIR))
ck("[9] A7-04 실패 처리 = manifest 없는 지난 꼬리 지움 · 이번 묶음 꼬리 · 규칙 밖 · manifest 있는 묶음은 둠",
   rc == 1 and not (set(ORPH9) & left9) and set(KEEP9b) <= left9 and OB.local_stamps() == have9, sorted(left9))
for n9 in ORPH9:
    open(os.path.join(OB.OUT_DIR, n9), "w").write("x")
OB.prune_local(30)
left9 = set(os.listdir(OB.OUT_DIR))
ck("[9] A7-04 회전(prune_local) = manifest 없는 꼬리 지움(지금 묶음 지정 없으면 이번 분 것도)",
   not (set(ORPH9) & left9) and CUR9 + ".db.gz" not in left9 and {"tjoff_notes.txt", "tjoff_19990101_0004.db.gz.bak"} <= left9
   and OB.local_stamps() == have9, sorted(left9))
BK9 = paths.state("backups")
MV9 = os.path.join(T.TMP, "moved9")
os.makedirs(MV9)
for n9 in os.listdir(BK9):
    if n9.startswith(("files_", "prefs_")):
        os.rename(os.path.join(BK9, n9), os.path.join(MV9, n9))
st9d = OB.remote_stamps(OB.conf(CFG))[-1]
with tarfile.open(os.path.join(REMOTE, st9d + ".files.tar.gz")) as tf:
    want9 = sorted(x.name for x in tf if x.isfile())
day9 = next(x for x in want9 if x.startswith("files_"))[6:14]


def cli9(argv):
    b9 = io.StringIO()
    with contextlib.redirect_stdout(b9):
        r9 = OB.main(argv)
    return r9, b9.getvalue()


rc, out9 = cli9(["fetch"])
got9 = sorted(os.path.join(dp, f).replace(BK9 + os.sep, "") for dp, _d, fs in os.walk(BK9) for f in fs
              if os.path.relpath(dp, BK9).split(os.sep)[0].startswith("files_") or f.startswith("prefs_"))
ck("[9] A7-02 fetch = 원장 밖 사본을 state/backups/files_<날>/ · prefs_<날>.json 으로(묶음 그대로 · 0600 · .env 류 없음)",
   rc == 0 and got9 == want9 and any(x.startswith("prefs_") for x in got9) and not any(".env" in x for x in got9)
   and all(os.stat(os.path.join(BK9, x)).st_mode & 0o077 == 0 for x in got9), (rc, got9, want9, out9[-300:]))
ck("[9] A7-02 복구 순서 안내 = 원장 restore → files <날> → config 지갑 → 마지막에 tj-core",
   out9.index("ledger_restore.py restore") < out9.index("ledger_restore.py files " + day9) < out9.index("config_subset.json") < out9.index("pm2 start tj-core"),
   out9[-600:])
MK9 = os.path.join(BK9, "files_" + day9, "settings.json")
open(MK9, "w").write('{"mine": 1}')
rc, out9 = cli9(["fetch"])
ck("[9] A7-02 이미 있는 원장 밖 사본 = 덮지 않음(그대로 둠 안내 · 복구 순서의 날짜는 그대로)", rc == 0 and open(MK9).read() == '{"mine": 1}' and "그대로 둠" in out9
   and "ledger_restore.py files " + day9 in out9, out9[-300:])
os.remove(os.path.join(BK9, "files_" + day9, "other_assets.json"))
rc, out9 = cli9(["fetch"])
ck("[9] A7-02 중단된 풀기 다시 = 빠진 파일만 채움 · 있던 파일은 그대로", rc == 0 and os.path.isfile(os.path.join(BK9, "files_" + day9, "other_assets.json"))
   and open(MK9).read() == '{"mine": 1}', out9[-300:])
shutil.rmtree(os.path.join(BK9, "files_" + day9))
rc, out9 = cli9(["open", REMOTE, st9d])
ck("[9] A7-02 open(받는 쪽 로컬 묶음)도 원장 밖 사본을 풂", rc == 0 and os.path.isfile(MK9) and open(MK9).read() != '{"mine": 1}', out9[-300:])
EV9 = os.path.join(T.TMP, "evil9")
os.makedirs(EV9)
SE9 = "tjoff_20990101_0000"
with tarfile.open(os.path.join(EV9, SE9 + ".files.tar.gz"), "w:gz") as tf:
    for nm9, kind9 in (("files_20990101/a.json", "f"), ("../evil.json", "f"), ("files_20990101/../../x.json", "f"), ("files_20990101/ln", "l"),
                       ("files_20990101/sub/deep.json", "f"), ("files_20990101/.hidden", "f"), ("other.json", "f")):
        ti = tarfile.TarInfo(nm9)
        if kind9 == "l":
            ti.type, ti.linkname = tarfile.SYMTYPE, "/etc/passwd"
            tf.addfile(ti)
        else:
            ti.size = 2
            tf.addfile(ti, io.BytesIO(b"{}"))
mf9 = {"v": 1, "stamp": SE9, "db": {"name": SE9 + ".db.gz", "sha256": "0" * 64},
       "files": {"name": SE9 + ".files.tar.gz", "sha256": sha(os.path.join(EV9, SE9 + ".files.tar.gz"))}}
statefile.atomic_write_json(os.path.join(EV9, SE9 + ".manifest.json"), OB.seal.seal(mf9, K9))
DST9 = os.path.join(T.TMP, "evil9_dst")
put9 = OB.unpack_files(EV9, SE9, K9, dst_dir=DST9, log=Q)
ck("[9] A7-02 꼴 아닌 이름·링크·깊은 자리·숨김 = 건너뜀 · 바깥에 안 씀", put9 == ["files_20990101"]
   and os.listdir(os.path.join(DST9, "files_20990101")) == ["a.json"] and sorted(os.listdir(DST9)) == ["files_20990101"]
   and not os.path.exists(os.path.join(T.TMP, "evil.json")) and not os.path.exists(os.path.join(T.TMP, "x.json")), (put9, os.listdir(DST9)))
T.finish()
