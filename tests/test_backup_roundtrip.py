#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import base64  # noqa: E402
import contextlib  # noqa: E402
import gzip  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import sqlite3  # noqa: E402
import tarfile  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

import _gpgkit as G  # noqa: E402

chk = T.chk
TOOLS = os.path.join(T.ROOT, "tools")
sys.path.insert(0, TOOLS)
import paths, statefile  # noqa: E402
import db as dbm  # noqa: E402
import ledger_backup as lb  # noqa: E402
import offsite_backup as OB  # noqa: E402

REMOTE = os.path.join(T.TMP, "remote_box", "tj_offsite")
FAKEBIN = os.path.join(T.TMP, "fakebin")
KEY = os.path.join(T.TMP, "fake_key")
CHILD_ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def rows(p):
    c = sqlite3.connect(paths.sqlite_ro_uri(p, immutable=True), uri=True)
    try:
        return c.execute("SELECT * FROM raw_txs ORDER BY txhash").fetchall()
    finally:
        c.close()


PORT = "2222"
HOSTSPEC = "backup@backup.invalid"
FAKE_SSH = """#!%s
import subprocess, sys
a = sys.argv[1:]
open("@@LOG@@", "a").write("ssh " + " ".join(a) + "\\n")
ok = len(a) >= 2 and a[-2] == "@@HOST@@" and any(a[i:i + 2] == ["-p", "@@PORT@@"] for i in range(len(a))) and \\
    any(a[i:i + 2] == ["-i", "@@KEY@@"] for i in range(len(a)))
if not ok:   # 설정 대상 · 포트 · 열쇠가 다 실려야(빠지면 실제로는 접속 실패)
    sys.stderr.write("가짜 ssh: 대상·포트·열쇠 아님 %%r\\n" %% a)
    sys.exit(255)
sys.exit(subprocess.run(["bash", "-c", sys.argv[-1]]).returncode)
"""
FAKE_RSYNC = """#!%s
import os, re, shutil, sys
a = sys.argv[1:]
open("@@LOG@@", "a").write("rsync " + " ".join(a) + "\\n")
if "--version" in a:
    print("rsync  version 3.2.7  protocol version 31")
    sys.exit(0)
import shlex
pos, skip, mode, eshell = [], False, None, None
for x in a:
    if skip:
        skip, eshell = False, x
    elif x == "-e":
        skip = True
    elif x.startswith("--chmod=F"):
        mode = int(x.split("F", 1)[1], 8)
    elif not x.startswith("-"):
        pos.append(x)
ev = shlex.split(eshell or "")
if not ev or ev[0] != "ssh" or not any(ev[i:i + 2] == ["-p", "@@PORT@@"] for i in range(len(ev))) or \\
        not any(ev[i:i + 2] == ["-i", "@@KEY@@"] for i in range(len(ev))):   # 원격 셸(-e) = 설정 포트·열쇠 실린 ssh 여야
    sys.stderr.write("가짜 rsync: -e 원격 셸 꼴 아님 %%r\\n" %% eshell)
    sys.exit(14)
pre = "@@HOST@@:"
far = [i for i, x in enumerate(pos) if x.startswith(pre)]
# 원격 쪽은 정확히 한쪽(보내기 = 끝 · 받기 = 앞 하나) · 원격 경로는 가짜 원격 폴더 아래만 — 접두어가 빠지면 로컬 복사로 거짓 성공하지 않게
if len(pos) < 2 or len(far) != 1 or far[0] not in (0, len(pos) - 1) or (far[0] == 0 and len(pos) != 2) or \\
        not os.path.abspath(pos[far[0]][len(pre):]).startswith("@@REMOTE@@" + os.sep):
    sys.stderr.write("가짜 rsync: 원격 인자 꼴 아님 %%r\\n" %% pos)
    sys.exit(12)
pos = [x[len(pre):] if x.startswith(pre) else x for x in pos]
dst = pos[-1]
for s in pos[:-1]:
    if not os.path.exists(s):
        sys.stderr.write("rsync: no such file %%s\\n" %% s)
        sys.exit(23)
    d = os.path.join(dst, os.path.basename(s)) if dst.endswith("/") or os.path.isdir(dst) else dst
    shutil.copyfile(s, d)
    if mode is not None:
        os.chmod(d, mode)
"""


NETLOG = os.path.join(T.TMP, "fake_net.log")
SCAN_OUT = os.path.join(T.TMP, "fake_keyscan.out")
FAKE_SCAN = """#!%s
import sys
open("@@LOG@@", "a").write("ssh-keyscan " + " ".join(sys.argv[1:]) + "\\n")
sys.stdout.write(open("@@SCAN@@").read())
"""


def fakebin():
    os.makedirs(FAKEBIN, exist_ok=True)
    for name, body in (("ssh", FAKE_SSH), ("rsync", FAKE_RSYNC), ("ssh-keyscan", FAKE_SCAN)):
        p = os.path.join(FAKEBIN, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write((body % sys.executable).replace("@@HOST@@", HOSTSPEC).replace("@@REMOTE@@", os.path.abspath(REMOTE))
                    .replace("@@PORT@@", PORT).replace("@@KEY@@", KEY).replace("@@LOG@@", NETLOG).replace("@@SCAN@@", SCAN_OUT))
        os.chmod(p, 0o755)


def cli(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        rc = OB.main(argv)
    return rc, out.getvalue()


def fake_rsync_rc(args):
    return subprocess.run([os.path.join(FAKEBIN, "rsync")] + args, capture_output=True, timeout=60).returncode


print("[R1] 평문 왕복 — run → 가짜 원격 → fetch → ledger_restore check")
c = dbm.open_db(paths.DB_PATH)
for i in range(120):
    c.execute("INSERT INTO raw_txs VALUES('eth', ?, ?, ?, ?, ?, ?, ?)",
              (f"0x{i:04x}", i, f"0xb{i:063x}", 1_700_000_000 + i, json.dumps({"bal": str(i), "n": i}), json.dumps([f"0x{i:040x}"]),
               1_700_000_000 + i))
c.commit()
c.close()
ORIG = rows(paths.DB_PATH)
for n, obj in (("ui_prefs.json", {"plans": {}}), ("other_assets.json", {"v": 1, "items": [{"name": "합성 자산"}]})):
    statefile.atomic_write_json(os.path.join(paths.STATE_DIR, n), obj)
with open(KEY, "w") as f:
    f.write("x")
os.makedirs(REMOTE, exist_ok=True)
fakebin()
os.environ["PATH"] = FAKEBIN + os.pathsep + os.environ.get("PATH", "")
E_OK = ["-e", "ssh -p %s -i %s" % (PORT, KEY)]
chk(fake_rsync_rc(["-t"] + E_OK + [KEY, REMOTE + "/"]) == 12 and fake_rsync_rc(["-t"] + E_OK + [KEY, "other@backup.invalid:" + REMOTE + "/"]) == 12
    and fake_rsync_rc(["-t"] + E_OK + [KEY, HOSTSPEC + ":/elsewhere/"]) == 12, "R1 가짜 rsync = 대상·접두어·원격 폴더가 다르면 거부(rc 12)")
chk(fake_rsync_rc(["-t", KEY, HOSTSPEC + ":" + REMOTE + "/"]) == 14 and fake_rsync_rc(["-t", "-e", "ssh -i " + KEY, KEY, HOSTSPEC + ":" + REMOTE + "/"]) == 14
    and fake_rsync_rc(["-t", "-e", "ssh -p " + PORT, KEY, HOSTSPEC + ":" + REMOTE + "/"]) == 14, "R1 가짜 rsync = -e 없음·포트·열쇠 빠짐 거부(rc 14)")
chk(subprocess.run([os.path.join(FAKEBIN, "ssh"), "-i", KEY, HOSTSPEC, "true"], capture_output=True, timeout=60).returncode == 255
    and subprocess.run([os.path.join(FAKEBIN, "ssh"), "-p", PORT, "-i", KEY, HOSTSPEC, "true"], capture_output=True, timeout=60).returncode == 0,
    "R1 가짜 ssh = 포트 빠짐 거부 · 대상·포트·열쇠 다 있으면 실행")
CFG = {"backup": {"offsite": {"enabled": True, "mode": "push", "host": "backup.invalid", "user": "backup", "port": int(PORT), "key": KEY,
                              "path": REMOTE, "keep": 2, "keep_local": 1, "bwlimit_kbps": 1024, "every_h": 24, "warn_h": 36}}}
with open(paths.CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump(CFG, f)
rc1, out1 = cli(["run", "--force"])
st1 = OB.read_status()
chk(rc1 == 0 and st1.get("last_ok") and not st1.get("err"), "R1 정기 백업 전 run --force = 보내기 성공(가짜 ssh·rsync)", [rc1, out1[-300:], st1])
sa = st1.get("last_stamp") or ""
got = sorted(n for n in os.listdir(REMOTE) if not n.startswith("."))
chk(got == sorted([sa + ".db.gz", sa + ".manifest.json"]), "R1 정기 백업 전 = 원장 밖 사본 없음 허용(압축본 · manifest 만)", got)
rca, outa = cli(["fetch"])
pa = next((ln.split(":", 1)[1].strip() for ln in outa.splitlines() if ln.startswith("받음:")), "")
chk(rca == 0 and os.path.isfile(pa) and rows(pa) == ORIG, "R1 정기 백업 전 묶음 fetch = 원본 행", [rca, outa[-300:]])
st0 = lb.run_once(log=None)
chk(st0.get("last_ok") and not st0.get("err"), "R1 정기 백업(원장 밖 사본 포함) 성공", st0)
rcb = OB.run(force=True, now=time.time() + 180, log=lambda *a: None)
st1 = OB.read_status()
stamp = st1.get("last_stamp") or ""
chk(rcb == 0 and stamp != sa and not st1.get("err"), "R1 정기 백업 뒤 run = 보내기 성공(새 묶음)", st1)
got = sorted(n for n in os.listdir(REMOTE) if not n.startswith(".") and n.startswith(stamp))
chk(got == sorted([stamp + ".db.gz", stamp + ".files.tar.gz", stamp + ".manifest.json"]), "R1 원격 = 압축본 · 원장 밖 사본 · manifest", got)
with open(os.path.join(REMOTE, stamp + ".manifest.json"), encoding="utf-8") as f:
    MAN = json.load(f)
rc2, out2 = cli(["fetch"])
p2 = next((ln.split(":", 1)[1].strip() for ln in out2.splitlines() if ln.startswith("받음:")), "")
chk(rc2 == 0 and os.path.isfile(p2) and stamp[6:] in p2, "R1 fetch rc 0 · 받은 원장 경로(최신 묶음)", [rc2, out2[-300:]])
ok2 = os.path.isfile(p2)
chk(ok2 and MAN.get("source", "").startswith("ledger_") and sha(p2) == MAN["db"]["raw_sha256"]
    and os.path.getsize(p2) == MAN["db"]["raw_size"], "R1 받은 원장 sha256·크기 = manifest raw(정기 백업 재사용)", MAN["db"])
chk(ok2 and rows(p2) == ORIG and len(ORIG) == 120, "R1 받은 원장 행 = 원본(120)", len(ORIG))
fdir = os.path.dirname(p2) if ok2 else ""
fz = os.path.join(fdir, stamp + ".files.tar.gz")
chk(ok2 and os.path.isfile(fz) and sha(fz) == (MAN.get("files") or {}).get("sha256"), "R1 받은 원장 밖 사본 sha256 = manifest", MAN.get("files"))
TAR_GOT, TAR_WANT = {}, {}
if ok2 and os.path.isfile(fz):
    with tarfile.open(fz) as tf:
        for m in tf.getmembers():
            if m.isfile():
                TAR_GOT[m.name] = hashlib.sha256(tf.extractfile(m).read()).hexdigest()
    for inc in (MAN.get("files") or {}).get("includes") or []:
        top = os.path.join(OB.BK_DIR, inc)
        for fp in ([top] if os.path.isfile(top) else [os.path.join(dp, f) for dp, _d, fs in os.walk(top) for f in fs]):
            TAR_WANT[os.path.relpath(fp, OB.BK_DIR).replace(os.sep, "/")] = sha(fp)
chk(TAR_WANT and TAR_GOT == TAR_WANT and any(k.startswith("prefs_") for k in TAR_GOT)
    and any(k.endswith("other_assets.json") for k in TAR_GOT), "R1 받은 원장 밖 사본 안 파일 = 정기 백업 원본(이름·내용 · prefs·기타 자산 포함)",
    [sorted(TAR_GOT), sorted(TAR_WANT)])
r3 = subprocess.run([sys.executable, os.path.join(TOOLS, "ledger_restore.py"), "check", p2], capture_output=True, text=True,
                    env=CHILD_ENV, timeout=300)
chk(ok2 and r3.returncode == 0, "R1 ledger_restore.py check <받은 원장> rc 0(새 프로세스)", [r3.returncode, (r3.stdout + r3.stderr)[-400:]])
with open(os.path.join(REMOTE, stamp + ".db.gz"), "r+b") as f:
    f.seek(40)
    b = f.read(1)
    f.seek(40)
    f.write(bytes([b[0] ^ 0xFF]))
rc4, out4 = cli(["fetch"])
chk(rc4 == 1 and "sha256" in out4, "R1 원격 압축본 한 바이트 바뀜 = fetch 실패(rc 1 · sha256 불일치)", [rc4, out4[-200:]])

print("[R2] 버리는 gpg 키 — 서버 홈(공개 키만) · 복원 홈(개인 키) · 암호화 왕복 · 정리 뒤 데몬 0")
if not G.gpg_path():
    G.skip_or_fail(T, "R2 gpg 키트")
elif ok2:
    K = G.Kit()
    try:
        fpr = K.make()
        print("  " + str(K.version) + (" · " + K.why if K.why else ""), flush=True)
        chk(len(fpr) == 40 and K.fingerprints(K.restore, secret=True) == [fpr], "R2 복원 홈 = 개인 키 1(지문 40자)", fpr)
        chk(K.fingerprints(K.server, secret=True) == [] and K.fingerprints(K.server) == [fpr], "R2 서버 홈 = 공개 키만(개인 키 0)",
            [K.fingerprints(K.server, secret=True), K.fingerprints(K.server)])
        chk(all(len(os.path.join(h, G.SOCK_NAME)) <= G.SOCK_MAX and (os.stat(h).st_mode & 0o777) == 0o700 for h in K.homes()),
            "R2 홈 = 0700 · 소켓 경로 한도 안", [len(os.path.join(h, G.SOCK_NAME)) for h in K.homes()])
        enc = os.path.join(T.TMP, "ledger.db.gpg")
        dec = os.path.join(T.TMP, "ledger.db.dec")
        K.encrypt(p2, enc)
        with open(enc, "rb") as f:
            head = f.read(16)
        chk(head and head[0] & 0x80 and not head.startswith(b"SQLite format 3") and not head.startswith(b"\x1f\x8b"),
            "R2 암호문 머리 = OpenPGP 패킷(SQLite·gzip 머리 아님)", head.hex())
        chk(K.decrypt(enc, dec, home=K.server) != 0 and not os.path.exists(dec), "R2 서버 홈(개인 키 없음)으로는 복호화 실패")
        K.decrypt(enc, dec)
        chk(sha(dec) == sha(p2) == MAN["db"]["raw_sha256"], "R2 복원 홈 복호화 = 원본 원장 바이트")
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        chk(False, "R2 gpg 키트 오류", "%s: %s" % (type(e).__name__, e))
    finally:
        homes = K.homes()
        root = os.path.dirname(homes[0]) if homes else ""
        K.close()
    chk(G.agents_left(homes) == 0, "R2 정리 뒤 그 홈들의 gpg 데몬 0", homes)
    chk(homes and not os.path.exists(root), "R2 정리 뒤 임시 홈 폴더 없음", root)

print("[R3] gpg 없는 PATH — 스위치 끔 = SKIP · 켬 = FAIL")
EMPTY = os.path.join(T.TMP, "emptybin")
os.makedirs(EMPTY, exist_ok=True)
CHILD = "import sys; sys.path.insert(0, %r); import _harness as T; import _gpgkit as G\n" \
        "if G.gpg_path() is None:\n    G.skip_or_fail(T, 'R3 자식')\nelse:\n    T.chk(False, 'gpg 가 보임')\nT.finish()\n" % T.HERE
for req, want_rc, want in (("", 0, "SKIP gpg 없음"), ("1", 1, "FAIL gpg 없음")):
    env = {k: v for k, v in CHILD_ENV.items() if k != "TJ_TEST_REQUIRE_GPG"}
    env.update(PATH=EMPTY, TJ_TEST_REQUIRE_GPG=req)
    r = subprocess.run([sys.executable, "-c", CHILD], capture_output=True, text=True, env=env, timeout=120)
    chk(r.returncode == want_rc and want in r.stdout, "R3 gpg 없음 · TJ_TEST_REQUIRE_GPG=%s → rc %d · '%s'" % (req or "끔", want_rc, want),
        [r.returncode, (r.stdout + r.stderr)[-300:]])
print("[R4] 송신자 인증 · 로컬 열기(open) · 호스트 키 지문 — 위조·옛 묶음·열쇠 사본·outbox·지문 다름")
S = OB.seal
with open(os.path.join(REMOTE, stamp + ".db.gz"), "r+b") as f:
    f.seek(40)
    b = f.read(1)
    f.seek(40)
    f.write(bytes([b[0] ^ 0xFF]))
SNAP = {n: open(os.path.join(REMOTE, n), "rb").read() for n in os.listdir(REMOTE) if n.startswith(stamp + ".")}
FD = os.path.join(OB.BK_DIR, "offsite_fetch", stamp)
RMAN = os.path.join(REMOTE, stamp + ".manifest.json")
STATE_KEY = S.load_key(OB.AUTH_KEY)


def restore_remote():
    for n, b in SNAP.items():
        with open(os.path.join(REMOTE, n), "wb") as f:
            f.write(b)


def put_man(m):
    with open(RMAN, "w", encoding="utf-8") as f:
        json.dump(m, f)


def left():
    return sorted(n for n in os.listdir(FD) if n.startswith(stamp + ".")) if os.path.isdir(FD) else []


def nets():
    return open(NETLOG).read().splitlines() if os.path.exists(NETLOG) else []


chk(STATE_KEY and MAN.get("auth", {}).get("kid") == S.kid(STATE_KEY) and S.verify(MAN, STATE_KEY) is None,
    "R4 원격 manifest = state 열쇠 HMAC 봉인(kid 같음)", MAN.get("auth"))
rc, out = cli(["fetch"])
chk(rc == 0, "R4 되돌린 묶음 fetch rc 0(기준)", [rc, out[-200:]])
m = json.loads(json.dumps(MAN))
m["created"] += 1
put_man(m)
rc, out = cli(["fetch"])
chk(rc == 3 and "인증 실패" in out and left() == [], "R4 manifest 한 글자 바뀜(sha 그대로) = rc 3 · 받은 것 지움", [rc, out[-200:], left()])
restore_remote()
FAKE_DB = os.path.join(T.TMP, "forged.db")
fc = sqlite3.connect(FAKE_DB)
fc.execute("CREATE TABLE raw_txs(x)")
fc.execute("INSERT INTO raw_txs VALUES('위조')")
fc.commit()
fc.close()
FRAW = open(FAKE_DB, "rb").read()
with open(os.path.join(REMOTE, stamp + ".db.gz"), "wb") as f:
    f.write(gzip.compress(FRAW))
FGZ = open(os.path.join(REMOTE, stamp + ".db.gz"), "rb").read()
forged = json.loads(json.dumps(MAN))
forged["db"].update(sha256=hashlib.sha256(FGZ).hexdigest(), size=len(FGZ), raw_sha256=hashlib.sha256(FRAW).hexdigest(), raw_size=len(FRAW))
for why, fm in (("진짜 auth 베낌", forged), ("auth 없음", {k: v for k, v in forged.items() if k != "auth"}),
                ("다른 열쇠로 봉인", S.seal({k: v for k, v in forged.items() if k != "auth"}, os.urandom(32)))):
    put_man(fm)
    rc, out = cli(["fetch"])
    chk(rc == 3 and "인증 실패" in out and left() == [], "R4 원격이 만든 가짜 묶음(sha 맞춤 · %s) = rc 3 · 받은 것 지움" % why, [rc, out[-160:], left()])
restore_remote()
put_man({k: v for k, v in MAN.items() if k != "auth"})
rc, out = cli(["fetch"])
chk(rc == 3 and "--allow-unsigned" in out, "R4 auth 없는 옛 묶음 = 스위치 없이 rc 3", [rc, out[-200:]])
rc, out = cli(["fetch", "--allow-unsigned"])
chk(rc == 0 and "경고" in out and "서명 없는" in out, "R4 auth 없는 옛 묶음 + --allow-unsigned = rc 0 · 경고 한 줄", [rc, out[-300:]])
restore_remote()
CP = os.path.join(T.TMP, "owner_copy.key")
rc, out = cli(["auth-key", "--export", CP])
chk(rc == 0 and open(CP, "rb").read() == STATE_KEY and (os.stat(CP).st_mode & 0o777) == 0o600 and S.kid(STATE_KEY) in out,
    "R4 auth-key --export = state 열쇠와 같은 바이트 · 0600 · kid", [rc, out])
rc, out = cli(["auth-key", "--export", CP])
chk(rc == 1 and open(CP, "rb").read() == STATE_KEY, "R4 사본 자리에 파일 있음 = rc 1 · 덮지 않음", [rc, out])
os.rename(OB.AUTH_KEY, OB.AUTH_KEY + ".aside")
try:
    rc, out = cli(["fetch"])
    chk(rc == 3 and "열쇠가 없음" in out, "R4 state 열쇠 없음 = rc 3(봉인 묶음을 확인 못 함)", [rc, out[-200:]])
    rc, out = cli(["fetch", "--auth-key", CP])
    chk(rc == 0 and not os.path.exists(OB.AUTH_KEY), "R4 --auth-key <사본> = 다른 컴퓨터처럼 받음 · state 열쇠 안 만듦", [rc, out[-200:]])
finally:
    os.rename(OB.AUTH_KEY + ".aside", OB.AUTH_KEY)
RECV = os.path.join(T.TMP, "receiver")
os.makedirs(RECV)
for n in os.listdir(REMOTE):
    if n.startswith((stamp + ".", sa + ".")):
        shutil.copyfile(os.path.join(REMOTE, n), os.path.join(RECV, n))
with open(paths.CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump({"backup": {"offsite": {"enabled": True, "mode": "outbox"}}}, f)
rc, out = cli(["fetch"])
chk(rc == 2, "R4 outbox 설치 = fetch rc 2(원격 없음 — 종전)", [rc, out[-120:]])
n0 = len(nets())
rc, out = cli(["open", RECV, stamp])
po = next((ln.split(":", 1)[1].strip() for ln in out.splitlines() if ln.startswith("받음:")), "")
chk(rc == 0 and os.path.isfile(po) and sha(po) == MAN["db"]["raw_sha256"] and rows(po) == ORIG and len(nets()) == n0,
    "R4 open(outbox 받는 쪽) = 원본 바이트 · 행 · ssh·rsync 0회", [rc, out[-200:]])
r5 = subprocess.run([sys.executable, os.path.join(TOOLS, "ledger_restore.py"), "check", po], capture_output=True, text=True, env=CHILD_ENV, timeout=300)
chk(r5.returncode == 0, "R4 open 으로 푼 원장 → ledger_restore.py check rc 0", [r5.returncode, (r5.stdout + r5.stderr)[-300:]])
rc, out = cli(["open", RECV, sa])
chk(rc == 0 and "받음:" in out, "R4 원장 밖 사본 없는 묶음도 open rc 0", [rc, out[-200:]])
with open(os.path.join(RECV, stamp + ".files.tar.gz"), "ab") as f:
    f.write(b"!")
rc, out = cli(["open", RECV, stamp])
chk(rc == 1 and "원장 밖 사본 sha256" in out and os.path.exists(os.path.join(RECV, stamp + ".files.tar.gz")),
    "R4 받는 쪽 원장 밖 사본 변조 = rc 1 · 받는 쪽 파일은 안 지움", [rc, out[-200:]])
m = json.loads(json.dumps(MAN))
m["source"] = "x"
with open(os.path.join(RECV, stamp + ".manifest.json"), "w", encoding="utf-8") as f:
    json.dump(m, f)
rc, out = cli(["open", RECV, stamp])
chk(rc == 3 and os.path.exists(os.path.join(RECV, stamp + ".manifest.json")), "R4 받는 쪽 manifest 변조 = open rc 3 · 받는 쪽 파일은 안 지움", [rc, out[-200:]])
rc, out = cli(["open", RECV, "../" + stamp])
chk(rc == 1 and "형식" in out, "R4 open 묶음 이름 꼴 아님 = rc 1", [rc, out[-200:]])
with open(paths.CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump(CFG, f)
with open(OB.AUTH_KEY, "wb") as f:
    f.write(STATE_KEY[:31])
before_l, before_r = sorted(os.listdir(OB.OUT_DIR)), sorted(os.listdir(REMOTE))
rcg = OB.run(force=True, now=time.time() + 400, log=lambda *a: None)
stg = OB.read_status()
chk(rcg == 1 and "열쇠" in str(stg.get("err")) and sorted(os.listdir(OB.OUT_DIR)) == before_l and sorted(os.listdir(REMOTE)) == before_r,
    "R4 열쇠 길이 다름 = run 실패(상태 err) · 이 컴퓨터·원격 새 묶음 0", [rcg, stg.get("err")])
with open(OB.AUTH_KEY, "wb") as f:
    f.write(STATE_KEY)
B1 = base64.b64encode(b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + b"\x01" * 32).decode()
B2 = base64.b64encode(b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + b"\x02" * 32).decode()
CFG_PIN = json.loads(json.dumps(CFG))
CFG_PIN["backup"]["offsite"]["host_key_fpr"] = S.key_fpr(B1)
with open(paths.CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump(CFG_PIN, f)
with open(SCAN_OUT, "w") as f:
    f.write("[backup.invalid]:%s ssh-ed25519 %s\n" % (PORT, B2))
n0 = len([x for x in nets() if not x.startswith("ssh-keyscan")])
res = [cli(["test"]), cli(["list-remote"]), cli(["fetch"])]
rcr = OB.run(force=True, now=time.time() + 500, log=lambda *a: None)
chk([r[0] for r in res] == [1, 1, 1] and rcr == 1 and all("다름" in r[1] for r in res) and "다름" in str(OB.read_status().get("err"))
    and len([x for x in nets() if not x.startswith("ssh-keyscan")]) == n0 and not os.path.exists(OB.KNOWN_HOSTS),
    "R4 지문 칸과 원격 키 다름 = test·list-remote·fetch·run 모두 ssh·rsync 0회로 실패 · known_hosts 안 씀", [r[:1] + (r[1][-90:],) for r in res])
with open(SCAN_OUT, "w") as f:
    f.write("[backup.invalid]:%s ssh-ed25519 %s\n[backup.invalid]:%s ssh-ed25519 %s\n" % (PORT, B2, PORT, B1))
rc, out = cli(["fetch"])
ssh9 = [x for x in nets() if x.startswith(("ssh ", "rsync ")) and x != "rsync --version"][-3:]
chk(rc == 0 and open(OB.KNOWN_HOSTS).read() == "[backup.invalid]:%s ssh-ed25519 %s\n" % (PORT, B1)
    and (os.stat(OB.KNOWN_HOSTS).st_mode & 0o777) == 0o600 and ssh9
    and all("StrictHostKeyChecking=yes" in x and "UserKnownHostsFile=" + OB.KNOWN_HOSTS in x and "accept-new" not in x for x in ssh9),
    "R4 맞는 지문 = 전용 known_hosts(그 키만 · 0600) · ssh·rsync 가 yes + 그 파일로 받음", [rc, out[-160:], ssh9[-1:]])
rcp = OB.run(force=True, now=time.time() + 600, log=lambda *a: None)
stp = OB.read_status()
chk(rcp == 0 and stp.get("hostkey") == "고정" and not stp.get("err"), "R4 지문 고정 run = 보내기 성공 · 상태 hostkey 고정", stp)
T.finish()
