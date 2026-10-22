#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import errno  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import signal  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

import fsio  # noqa: E402

D = os.path.join(T.TMP, "fsio")
os.makedirs(D, exist_ok=True)
OBJ = {"한글": "값", "n": [1, 2.5, None, True], "s": "a\"b\\c", "u": " "}


def mode_of(p):
    return stat.S_IMODE(os.stat(p).st_mode)


def leftovers(d=D):
    return sorted(n for n in os.listdir(d) if n.startswith(fsio.TMP_PREFIX) or n.endswith(fsio.TMP_SUFFIX))


def spy_replace():
    seen, real = [], os.replace

    def rep(a, b, *x, **k):
        seen.append(os.fspath(a))
        return real(a, b, *x, **k)
    os.replace = rep
    return seen, (lambda: setattr(os, "replace", real))


def fork_run(fn):
    pid = os.fork()
    if pid == 0:
        code = 1
        try:
            code = 0 if fn() else 1
        except BaseException:   # noqa: BLE001
            code = 3
        os._exit(code)
    return pid


p = os.path.join(D, "a.json")
seen, undo = spy_replace()
fsio.atomic_write_json(p, OBJ, ensure_ascii=False, separators=(",", ":"))
undo()
T.chk(open(p, "rb").read() == json.dumps(OBJ, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), "A1 json 바이트 = json.dumps 와 같음")
tmpn = os.path.basename(seen[0]) if seen else ""
T.chk(tmpn.startswith(fsio.TMP_PREFIX + "a.json.") and tmpn.endswith(fsio.TMP_SUFFIX) and os.path.dirname(seen[0]) == D,
      "A2 임시 이름 = 같은 폴더 '.tmp_<대상>.<무작위>.tmp'", tmpn)
T.chk(leftovers() == [], "A3 정상 끝 = 임시 파일 안 남음", leftovers())
fsio.atomic_write_json(p, {"x": 1}, indent=2, newline=True, sort_keys=True)
T.chk(open(p, encoding="utf-8").read() == json.dumps({"x": 1}, indent=2, sort_keys=True) + "\n", "A4 indent·sort_keys·끝 줄바꿈 그대로")
fsio.atomic_write_text(os.path.join(D, "t.txt"), "가\n나")
fsio.atomic_write_bytes(os.path.join(D, "b.bin"), b"\x00\xff")
T.chk(open(os.path.join(D, "t.txt"), "rb").read() == "가\n나".encode() and open(os.path.join(D, "b.bin"), "rb").read() == b"\x00\xff",
      "A5 글(UTF-8·줄바꿈 변환 없음)·바이트 그대로")
long9 = os.path.join(D, "x" * 120 + ".json")
seen, undo = spy_replace()
fsio.atomic_write_json(long9, {})
undo()
T.chk(len(os.path.basename(seen[0])) <= 80 and os.path.exists(long9), "A6 긴 이름 = 임시 이름은 대상 이름 앞 40자만", os.path.basename(seen[0]))
dl = os.path.join(T.ROOT, "tools", "deploy_lib.sh")
if os.path.isfile(dl):
    head9, tail9 = open(dl, encoding="utf-8").read().split("EXC_TOP = re.compile(", 1)
    code9 = head9.rsplit("<<'PY'\n", 1)[1] + "EXC_TOP = re.compile(" + tail9.split("\nPY\n", 1)[0]
    ss9 = os.path.join(T.TMP, "snap_src")
    os.makedirs(os.path.join(ss9, "sub"))
    for n9 in (tmpn, os.path.join("sub", tmpn), ".tmp_abcd1234", "keep.json", "keep.json.lock"):
        open(os.path.join(ss9, n9), "w").close()
    par9 = os.path.join(T.TMP, "snap_par")
    os.makedirs(par9)
    r9 = subprocess.run([sys.executable, "-", ss9, os.path.join(par9, "snap"), par9, "snap", "", "", "", str(10 ** 8)],
                        input=code9, capture_output=True, text=True)
    got9 = sorted(os.path.relpath(os.path.join(dp, f), os.path.join(par9, "snap")) for dp, _d, fs in os.walk(os.path.join(par9, "snap")) for f in fs)
    T.chk(r9.returncode == 0 and got9 == ["keep.json", "keep.json.lock"], "A7 배포 필수만 스냅숏(원문 실행) = fsio·옛 임시 파일 안 베낌 · 잠금 파일은 베낌",
          (r9.returncode, got9, r9.stderr[-300:]))
else:
    print("(공개 배치 — tools/deploy_lib.sh 없음: A7 건너뜀)")
import buildproc  # noqa: E402
sw = os.path.join(T.TMP, "sweep")
os.makedirs(os.path.join(sw, "sub"), exist_ok=True)
olds = [os.path.join(sw, tmpn), os.path.join(sw, "sub", tmpn), os.path.join(sw, ".tmp_abcd1234")]
for f9 in olds + [os.path.join(sw, "keep.json"), os.path.join(sw, "keep.json.lock")]:
    open(f9, "w").close()
    os.utime(f9, (time.time() - 7200, time.time() - 7200))
n9 = buildproc.sweep_tmp(min_age=3600, root=sw)
T.chk(n9 == 3 and not any(os.path.exists(f9) for f9 in olds) and os.path.exists(os.path.join(sw, "keep.json"))
      and os.path.exists(os.path.join(sw, "keep.json.lock")), "A8 sweep_tmp = fsio·옛 mkstemp 임시 찌꺼기만 치움(잠금 파일·본 파일 그대로)", n9)
import view_builder  # noqa: E402
rx9 = view_builder.StateBuilder._SIG_SKIP_RX
T.chk(all(rx9.search(n) for n in (tmpn, ".tmp_abcd1234", "x.json.lock", "config.json.lock")) and not rx9.search("x.json"),
      "A9 웹 입력 서명 = fsio 임시·옛 '.tmp_XXXX'·잠금 파일 뺌 · 본 파일은 셈")

p = os.path.join(D, "crash.json")
fsio.atomic_write_json(p, {"v": "old"})
old_b = open(p, "rb").read()
try:
    fsio.atomic_write_json(p, {"v": object()})
    r9 = "no error"
except TypeError:
    r9 = "TypeError"
T.chk(r9 == "TypeError" and open(p, "rb").read() == old_b and leftovers() == [], "B1 쓰기 중 예외(직렬화) = 옛 내용 · 임시 없음", (r9, leftovers()))
real_rep = os.replace


def bad_replace(a, b, *x, **k):
    raise OSError(errno.EIO, "시험: 교체 실패")


os.replace = bad_replace
try:
    fsio.atomic_write_json(p, {"v": "new"})
    r9 = "no error"
except OSError:
    r9 = "OSError"
finally:
    os.replace = real_rep
T.chk(r9 == "OSError" and open(p, "rb").read() == old_b and leftovers() == [], "B2 os.replace 실패 = 옛 내용 · 임시 없음", (r9, leftovers()))
real_fsync = os.fsync
os.fsync = lambda fd: (_ for _ in ()).throw(OSError(errno.ENOSPC, "시험: 디스크 가득"))
try:
    fsio.atomic_write_json(p, {"v": "new"})
    r9 = "no error"
except OSError as e:
    r9 = e.errno
finally:
    os.fsync = real_fsync
T.chk(r9 == errno.ENOSPC and open(p, "rb").read() == old_b and leftovers() == [], "B3 fsync 실패(ENOSPC) = 옛 내용 · 임시 없음", (r9, leftovers()))
try:
    with fsio.atomic_open(p) as f:
        f.write('{"v": "half')
        raise KeyboardInterrupt
except KeyboardInterrupt:
    pass
T.chk(open(p, "rb").read() == old_b and leftovers() == [], "B4 블록 안 중단(BaseException) = 옛 내용 · 임시 없음")


def killed_mid_write():
    with fsio.atomic_open(p) as f:
        f.write('{"v": "never-published"')
        f.flush()
        os.kill(os.getpid(), signal.SIGKILL)
    return True


pid9 = fork_run(killed_mid_write)
_, st9 = os.waitpid(pid9, 0)
left9 = leftovers()
T.chk(os.WIFSIGNALED(st9) and open(p, "rb").read() == old_b and len(left9) == 1, "B5 교체 전 kill -9 = 옛 내용 그대로(찌꺼기 임시 1개)", (st9, left9))
n9 = buildproc.sweep_tmp(min_age=0, root=D, now=time.time() + 1)
T.chk(n9 >= 1 and leftovers() == [], "B6 강제 종료 찌꺼기 = sweep_tmp 가 치움", (n9, leftovers()))

old_um = os.umask(0o077)
try:
    fsio.atomic_write_text(os.path.join(D, "m644"), "x", mode=0o644)
    fsio.atomic_write_text(os.path.join(D, "mnone"), "x", mode=None)
finally:
    os.umask(old_um)
T.chk(mode_of(os.path.join(D, "m644")) == 0o644 and mode_of(os.path.join(D, "mnone")) == 0o600, "C1 숫자 = 그대로(umask 무관) · None = umask 기본(077 → 600)")
os.umask(0o022)
try:
    fsio.atomic_write_text(os.path.join(D, "mnone2"), "x", mode=None)
    fsio.atomic_write_text(os.path.join(D, "mdef"), "x")
finally:
    os.umask(old_um)
T.chk(mode_of(os.path.join(D, "mnone2")) == 0o644 and mode_of(os.path.join(D, "mdef")) == 0o600, "C2 None = open('w') 와 같음(022 → 644) · 기본 = 0600")
os.chmod(os.path.join(D, "m644"), 0o640)
fsio.atomic_write_text(os.path.join(D, "m644"), "y", mode=fsio.KEEP)
fsio.atomic_write_text(os.path.join(D, "mkeep_new"), "y", mode=fsio.KEEP)
T.chk(mode_of(os.path.join(D, "m644")) == 0o640 and mode_of(os.path.join(D, "mkeep_new")) == 0o600, "C3 KEEP = 지금 권한 유지 · 새 파일 0600")
with fsio.locked(os.path.join(D, "lk.json")):
    pass
T.chk(mode_of(os.path.join(D, "lk.json.lock")) == 0o600 and os.path.getsize(os.path.join(D, "lk.json.lock")) == 0,
      "C4 잠금 파일 = '<대상>.lock' 0600 · 내용 안 씀")

real_fsync = os.fsync


def fsync_dir_fails(fd):
    if stat.S_ISDIR(os.fstat(fd).st_mode):
        raise OSError(errno.EIO, "시험: 폴더 fsync 실패")
    return real_fsync(fd)


os.fsync = fsync_dir_fails
p = os.path.join(D, "dsync.json")
try:
    fsio.atomic_write_json(p, {"v": 2})
    r9 = "no error"
except fsio.DirSyncError as e:
    r9 = ("DirSyncError", isinstance(e, OSError), e.errno)
finally:
    os.fsync = real_fsync
T.chk(r9 == ("DirSyncError", True, errno.EIO) and json.load(open(p)) == {"v": 2} and leftovers() == [],
      "D1 교체 뒤 폴더 fsync 실패 = DirSyncError(OSError) · 대상 = 새 내용 · 임시 없음", r9)
os.fsync = fsync_dir_fails
try:
    fsio.atomic_write_json(p, {"v": 3}, dir_fsync=False)
    r9 = "ok"
except OSError as e:
    r9 = repr(e)
finally:
    os.fsync = real_fsync
T.chk(r9 == "ok" and json.load(open(p)) == {"v": 3}, "D2 dir_fsync=False = 폴더 fsync 안 함", r9)
try:
    fsio.atomic_write_json(os.path.join(D, "없음", "x.json"), {}, makedirs=False)
    r9 = "made"
except FileNotFoundError:
    r9 = "FileNotFoundError"
T.chk(r9 == "FileNotFoundError" and not os.path.exists(os.path.join(D, "없음")), "D3 makedirs=False = 폴더 없으면 실패(종전 캐시 쓰기와 같음)", r9)
fsio.atomic_write_json(os.path.join(D, "새폴더", "x.json"), {})
T.chk(os.path.exists(os.path.join(D, "새폴더", "x.json")), "D4 makedirs 기본 = 폴더 만듦(종전 common·settings_store 와 같음)")

ce = os.path.join(D, "token")
T.chk(fsio.create_exclusive(ce, b"first\n") is True and fsio.create_exclusive(ce, b"second\n") is False and open(ce, "rb").read() == b"first\n"
      and mode_of(ce) == 0o600 and leftovers() == [], "E1 없을 때만 만듦 · 있으면 손대지 않고 False · 0600 · 임시 없음")
race = os.path.join(D, "race_token")
go = os.path.join(D, "race_go")
pids = []
for i in range(6):
    def creator(i=i):
        while not os.path.exists(go):
            time.sleep(0.001)
        return fsio.create_exclusive(race, (("W%d" % i) * 4000).encode())
    pids.append(fork_run(creator))
open(go, "w").close()
partial, codes = 0, {}
t_end = time.time() + 10
while time.time() < t_end and len(codes) < len(pids):
    try:
        b9 = open(race, "rb").read()
        if len(b9) != 8000:
            partial += 1
    except FileNotFoundError:
        pass
    for x in pids:
        if x not in codes:
            r9 = os.waitpid(x, os.WNOHANG)
            if r9 != (0, 0):
                codes[x] = r9[1]
for x in pids:
    if x not in codes:
        codes[x] = os.waitpid(x, 0)[1]
b9 = open(race, "rb").read()
wins = sum(1 for v in codes.values() if v == 0)
T.chk(partial == 0 and len(b9) == 8000 and len(set(b9.decode()[i:i + 2] for i in range(0, 8000, 2))) == 1 and wins == 1 and leftovers() == [],
      "E2 동시 6개 = 한 쪽만 True · 그 내용만 · 반쯤 쓴 파일 한 번도 안 보임 · 임시 없음", (partial, len(b9), sorted(codes.values())))
real_link = os.link
os.link = lambda a, b: (_ for _ in ()).throw(OSError(errno.EPERM, "시험: 하드 링크 안 됨"))
try:
    r1 = fsio.create_exclusive(os.path.join(D, "nolink"), b"x")
    r2 = fsio.create_exclusive(os.path.join(D, "nolink"), b"y")
finally:
    os.link = real_link
T.chk(r1 is True and r2 is False and open(os.path.join(D, "nolink"), "rb").read() == b"x" and leftovers() == [],
      "E3 하드 링크 못 거는 파일 시스템 = O_EXCL 직접(종전 방식) · 결과 같음")
dirsync = []
real_fsync = os.fsync


def fsync_spy(fd):
    if stat.S_ISDIR(os.fstat(fd).st_mode):
        dirsync.append(fd)
        if fail_dir[0]:
            raise OSError(errno.EIO, "시험: 폴더 fsync 실패")
    return real_fsync(fd)


fail_dir = [False]
os.link = lambda a, b: (_ for _ in ()).throw(OSError(errno.EPERM, "시험: 하드 링크 안 됨"))
os.fsync = fsync_spy
try:
    r3 = fsio.create_exclusive(os.path.join(D, "nolink2"), b"z")
    n3 = len(dirsync)
    fail_dir[0] = True
    try:
        fsio.create_exclusive(os.path.join(D, "nolink3"), b"w")
        r4 = "no error"
    except fsio.DirSyncError:
        r4 = "DirSyncError"
finally:
    os.link, os.fsync = real_link, real_fsync
T.chk(r3 is True and n3 == 1 and r4 == "DirSyncError" and open(os.path.join(D, "nolink3"), "rb").read() == b"w",
      "E4 물러선 길(O_EXCL 직접)도 dir_fsync 계약 그대로(폴더 fsync · 실패 = DirSyncError)", (r3, n3, r4))

if os.geteuid() != 0:
    ro9 = os.path.join(D, "ro_dir")
    os.makedirs(ro9)
    os.chmod(ro9, 0o500)
    try:
        fsio.create_exclusive(os.path.join(ro9, "x"), b"x")
        r5 = "made"
    except fsio.CreateError as e:
        r5 = ("CreateError", isinstance(e, OSError), e.errno)
    finally:
        os.chmod(ro9, 0o700)
    T.chk(r5 == ("CreateError", True, errno.EACCES) and os.listdir(ro9) == [], "E5 새 이름을 못 만듦(쓰기 못 하는 폴더) = CreateError(OSError) · 아무것도 안 남음", r5)
os.fsync = lambda fd: (_ for _ in ()).throw(OSError(errno.ENOSPC, "시험: 디스크 가득"))
try:
    fsio.create_exclusive(os.path.join(D, "wfail"), b"x")
    r6 = "made"
except fsio.CreateError:
    r6 = "CreateError"
except OSError as e:
    r6 = e.errno
finally:
    os.fsync = real_fsync
T.chk(r6 == errno.ENOSPC and not os.path.exists(os.path.join(D, "wfail")) and leftovers() == [],
      "E6 쓰는 중 실패 = CreateError 아닌 OSError 그대로 · 대상·임시 없음", r6)

real_fchmod = os.fchmod
os.fchmod = lambda fd, m: (_ for _ in ()).throw(OSError(errno.EIO, "시험: 권한 맞추기 실패"))
try:
    fsio.create_exclusive(os.path.join(D, "chmodfail"), b"x")
    r7 = "made"
except fsio.CreateError:
    r7 = "CreateError"
except OSError as e:
    r7 = e.errno
finally:
    os.fchmod = real_fchmod
T.chk(r7 == errno.EIO and not os.path.exists(os.path.join(D, "chmodfail")) and leftovers() == [],
      "E7 이름은 만든 뒤 권한 맞추기 실패 = CreateError 아닌 OSError(못 만듦으로 삼키지 않게) · 대상·임시 없음", r7)

q = os.path.join(D, "nest.json")
try:
    with fsio.locked(q):
        with fsio.locked(q):
            pass
    r9 = "no error"
except RuntimeError as e:
    r9 = "RuntimeError" if "중첩" in str(e) else repr(e)
T.chk(r9 == "RuntimeError", "F1 같은 스레드 중첩 = RuntimeError(교착 대신)", r9)
cnt = os.path.join(D, "count.json")


def incr(cur):
    d = dict(cur or {"n": 0})
    n0 = d["n"]
    time.sleep(0.0005)
    d["n"] = n0 + 1
    return d


ths = [threading.Thread(target=lambda: [fsio.locked_update_json(cnt, incr) for _ in range(25)]) for _ in range(8)]
[t.start() for t in ths]
[t.join() for t in ths]
T.chk(json.load(open(cnt))["n"] == 200, "F2 스레드 8 × 25 읽고-바꾸고-쓰기 = 잃어버린 갱신 0", json.load(open(cnt)))
os.unlink(cnt)
pids = [fork_run(lambda: [fsio.locked_update_json(cnt, incr) for _ in range(30)] and True) for _ in range(6)]
st = [os.waitpid(x, 0)[1] for x in pids]
T.chk(all(s == 0 for s in st) and json.load(open(cnt))["n"] == 180, "F3 프로세스 6 × 30 = 잃어버린 갱신 0", (st, json.load(open(cnt))))
T.chk(fsio.locked_update_json(cnt, lambda c: fsio.UNCHANGED) is fsio.UNCHANGED and json.load(open(cnt))["n"] == 180
      and fsio.locked_update_json(cnt, lambda c: fsio.DELETE) is fsio.DELETE and not os.path.exists(cnt), "F4 UNCHANGED = 안 씀 · DELETE = 지움")
try:
    fsio.locked_update_json(cnt, lambda c: None)
    r9 = "no error"
except TypeError:
    r9 = "TypeError"
T.chk(r9 == "TypeError", "F5 fn 이 None = TypeError(지우기·그대로는 표식으로만)")
open(os.path.join(D, "bad.json"), "w").write("{깨짐")
try:
    fsio.locked_update_json(os.path.join(D, "bad.json"), lambda c: {"x": 1})
    r9 = "overwrote"
except ValueError:
    r9 = "ValueError"
T.chk(r9 == "ValueError" and open(os.path.join(D, "bad.json")).read() == "{깨짐", "F6 기본 읽기 = 깨진 JSON 은 덮지 않고 ValueError")
rl = fsio.FileRLock(lambda: os.path.join(D, "rl.lock"))
with rl:
    with rl:
        inner = rl._depth
T.chk(inner == 2 and rl._depth == 0 and rl._fd is None, "F7 FileRLock = 같은 스레드 재진입(깊이만) · 다 풀면 flock 도 풂")
rcnt = os.path.join(D, "rcount.json")


def rl_incr():
    for _ in range(30):
        with rl:
            with rl:
                d = json.load(open(rcnt)) if os.path.exists(rcnt) else {"n": 0}
                time.sleep(0.0005)
                fsio.atomic_write_json(rcnt, {"n": d["n"] + 1})
    return True


pids = [fork_run(rl_incr) for _ in range(4)]
ths = [threading.Thread(target=rl_incr) for _ in range(2)]
[t.start() for t in ths]
[t.join() for t in ths]
st = [os.waitpid(x, 0)[1] for x in pids]
T.chk(all(s == 0 for s in st) and json.load(open(rcnt))["n"] == 180, "F8 FileRLock = 프로세스 4 + 스레드 2 × 30 잃어버린 갱신 0", (st, json.load(open(rcnt))))
try:
    rl.release()
    r9 = "no error"
except RuntimeError:
    r9 = "RuntimeError"
T.chk(r9 == "RuntimeError", "F9 잡지 않고 풀기 = RuntimeError")
if os.geteuid() != 0:
    lk0 = os.path.join(D, "root_owned.json")
    open(lk0 + ".lock", "w").close()
    os.chmod(lk0 + ".lock", 0)
    try:
        with fsio.locked(lk0):
            pass
        r9 = "opened"
    except PermissionError as e:
        r9 = "PermissionError" if "잠금 파일을 열 수 없음" in str(e) and lk0 + ".lock" in str(e) else repr(e)
    os.chmod(lk0 + ".lock", 0o600)
    T.chk(r9 == "PermissionError", "F10 못 여는 잠금 파일(남이 만든 0600 등) = 안내 문구가 붙은 PermissionError", r9)
fk = os.path.join(D, "fork.json")
held, release = threading.Event(), threading.Event()


def holder():
    with fsio.locked(fk):
        with rl:
            held.set()
            release.wait(5)


th = threading.Thread(target=holder)
th.start()
held.wait(5)


def child_lock():
    signal.alarm(8)
    with fsio.locked(fk):
        with rl:
            return True


cp = fork_run(child_lock)
time.sleep(0.3)
waited = os.waitpid(cp, os.WNOHANG) == (0, 0)
release.set()
th.join()
st9 = os.waitpid(cp, 0)[1]
T.chk(waited and st9 == 0, "F11 fork 뒤 자식 = 프로세스 안 잠금 표 새로(교착 없음) · 파일 잠금은 부모가 풀 때까지 기다림", (waited, st9))

rq = os.path.join(D, "req.json")
fsio.atomic_write_json(rq, {"ids": ["a"]})
c9 = fsio.claim(rq)
fsio.atomic_write_json(rq, {"ids": ["b"]})
T.chk(c9 == rq + fsio.CLAIM_INFIX + str(os.getpid()) and json.load(open(c9)) == {"ids": ["a"]} and json.load(open(rq)) == {"ids": ["b"]},
      "G1 claim = '<요청>.claim.<pid>' 로 가져감 · 그 뒤 새 요청은 새 파일로 남음")
os.unlink(c9)
os.unlink(rq)
T.chk(fsio.claim(rq) is None, "G2 요청 없음 = None")
T.chk(not [n for n in dir(fsio) if n in ("time", "dm", "_now", "http_json", "PACE")], "G3 시험 patch_moved 흔한 이름이 fsio 전역에 없음(가짜가 섞이지 않게)")
T.finish()
