#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import contextlib  # noqa: E402
import io  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402

chk = T.chk
PK = os.path.join(T.ROOT, "tools", "package")
if not os.path.isfile(os.path.join(PK, "sync_public.py")):
    public_layout = os.path.realpath(T.HERE) == os.path.realpath(os.path.join(T.ROOT, "tests"))
    chk(public_layout, "공개판 배치 — 비공개 도구(tools/package/sync_public.py) 없음 · 건너뜀" if public_layout
        else "저장소 배치인데 tools/package/sync_public.py 없음(건너뛰지 않고 실패)")
    T.finish()
if not shutil.which("git"):
    chk(True, "git 없음 · 건너뜀")
    T.finish()
sys.path.insert(0, PK)
import sync_public as SP  # noqa: E402

ROOT = os.path.realpath(T.ROOT)
BASE = os.path.realpath(T.TMP)
OUT = os.path.join(BASE, "stage")
p = SP.B.plan(ROOT)
SP.B.copy_tree(ROOT, OUT, p["files"])
PUB = os.path.join(BASE, "pubrepo")
os.makedirs(PUB)
GIT = ["git", "-C", PUB, "-c", "user.name=t", "-c", "user.email=t@t.invalid", "-c", "commit.gpgsign=false"]
subprocess.run(GIT + ["init", "-q"], check=True)
with open(os.path.join(PUB, "old_only.txt"), "w") as f:
    f.write("옛 파일\n")
shutil.copyfile(os.path.join(OUT, "LICENSE"), os.path.join(PUB, "LICENSE"))
os.chmod(os.path.join(PUB, "LICENSE"), 0o644)
subprocess.run(GIT + ["add", "-A"], check=True)
subprocess.run(GIT + ["commit", "-q", "-m", "init"], check=True)


def head():
    return subprocess.run(["git", "-C", PUB, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def status():
    return subprocess.run(["git", "-C", PUB, "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True).stdout


def _files_of(d):
    got = []
    for dp, dns, fns in os.walk(d):
        dns[:] = [x for x in dns if x != ".git"]
        got += [os.path.relpath(os.path.join(dp, f), d).replace(os.sep, "/") for f in fns]
    return sorted(got)


NOSTRIP = {}


LINT_OK = "digest {d}\nAll checks passed!\nSuccess: no issues found in 13 source files\n"
LINT_F = os.path.join(BASE, "lint.txt")


def run(*a, scan=None, smap=NOSTRIP, lint=LINT_OK):
    a = list(a)
    if lint is not None:
        with open(LINT_F, "w", encoding="utf-8") as f:
            f.write(lint.format(d=SP.lint_digest(a[0]) if os.path.isdir(a[0]) else ""))
        a += ["--lint", LINT_F]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = SP.main(a, scan=scan, smap=smap)
    return rc, buf.getvalue()


def ok_scan(_args):
    return 0


H0 = head()
keep_env = {k: os.environ.pop(k) for k in list(os.environ) if k.startswith("TJ_PUB_")}
rc, out = run(OUT, PUB, "--apply")
chk(rc == 2 and "필수" in out and status() == "" and head() == H0, "[1] 개인정보 스캔 준비물 없음 = rc 2 · 공개 저장소 무변", out[-300:])
rc, out = run(OUT, PUB, "--apply", scan=ok_scan, smap=None)
chk(rc == 2 and "strip 규칙(TJ_PUB_RULES) 필수" in out and status() == "" and head() == H0, "[1] strip 규칙 없음 = rc 2 · 공개 저장소 무변", out[-300:])
BADSTRIP = {"src/version.py": b'"""synthetic."""\nzz_synth = 1\n'}
shutil.copyfile(os.path.join(OUT, "src", "version.py"), os.path.join(BASE, "version_keep"))
with open(os.path.join(OUT, "src", "version.py"), "wb") as f:
    f.write(BADSTRIP["src/version.py"])
rc, out = run(OUT, PUB, "--apply", scan=ok_scan, smap=BADSTRIP)
chk(rc == 1 and "strip 증명 실패 src/version.py" in out and "원본과 바이트 다름" not in out and status() == "" and head() == H0,
    "[1] strip 결과가 코드를 바꿈(바이트는 맞음) = 증명 실패 rc 1 · 무변", out[-300:])
shutil.copyfile(os.path.join(BASE, "version_keep"), os.path.join(OUT, "src", "version.py"))
os.chmod(os.path.join(OUT, "src", "version.py"), 0o644)
with open(os.path.join(OUT, "VERSION"), "ab") as f:
    f.write(b"x")
rc, out = run(OUT, PUB, "--apply", scan=ok_scan)
chk(rc == 1 and "원본과 바이트 다름: VERSION" in out and status() == "", "[1] 산출물이 이 트리 빌드와 다름 = rc 1 · 무변", out[-300:])
shutil.copyfile(os.path.join(ROOT, "VERSION"), os.path.join(OUT, "VERSION"))
os.chmod(os.path.join(OUT, "VERSION"), 0o644)
rc, out = run(OUT, PUB, "--apply", scan=ok_scan, lint=None)
chk(rc == 2 and "린트 결과 파일(--lint" in out and status() == "" and head() == H0, "[1b] --lint 안 줌 = rc 2 · 무변", out[-200:])
rc, out = run(OUT, PUB, "--apply", "--lint", os.path.join(BASE, "no_such_lint.txt"), scan=ok_scan, lint=None)
chk(rc == 2 and "no_such_lint.txt" in out and status() == "", "[1b] 린트 결과 파일 없음 = rc 2 · 무변", out[-200:])
for nm1b, txt1b, want1b in (
        ("ruff 오류", "digest {d}\nsrc/x.py:1:1: F841 Local variable `a` is assigned to but never used\nFound 1 error.\nSuccess: no issues found in 13 source files\n",
         ("ruff 통과 줄", "린트 오류 줄: Found 1 error.")),
        ("mypy 통과 줄 없음", "digest {d}\nAll checks passed!\nsrc/x.py:3: error: bad\nFound 1 error in 1 file (checked 13 source files)\n", ("mypy 통과 줄", "린트 오류 줄")),
        ("지문 다름(옛 결과)", "digest " + "0" * 64 + "\nAll checks passed!\nSuccess: no issues found in 13 source files\n", ("지문이 이 산출물과 다름",)),
        ("지문 줄 없음", "All checks passed!\nSuccess: no issues found in 13 source files\n", ("digest 줄 없음",)),
        ("지문 두 번(이어 붙인 결과)", "digest {d}\ndigest {d}\nAll checks passed!\nSuccess: no issues found in 13 source files\n", ("지문이 이 산출물과 다름",))):
    rc, out = run(OUT, PUB, "--apply", scan=ok_scan, lint=txt1b)
    chk(rc == 1 and all(w in out for w in want1b) and status() == "" and head() == H0, "[1b] 린트 %s = rc 1 · 무변" % nm1b, out[-300:])
D1b = SP.lint_digest(OUT)
with open(os.path.join(OUT, "src", "version.py"), "ab") as f:
    f.write(b"\n")
chk(SP.lint_digest(OUT) != D1b, "[1b] 산출물 .py 한 바이트 바뀜 = 지문 바뀜(고친 뒤 옛 결과 거부)")
shutil.copyfile(os.path.join(ROOT, "src", "version.py"), os.path.join(OUT, "src", "version.py"))
os.chmod(os.path.join(OUT, "src", "version.py"), 0o644)
chk(SP.lint_digest(OUT) == D1b, "[1b] 되돌리면 같은 지문")
PP1b = os.path.join(OUT, "pyproject.toml")
with open(PP1b, "rb") as f:
    pp0 = f.read()
with open(PP1b, "ab") as f:
    f.write(b"\n")
chk(SP.lint_digest(OUT) != D1b, "[1b] 린트 설정(pyproject.toml)만 바뀌어도 지문 바뀜(설정 바꾼 뒤 옛 결과 거부)")
with open(PP1b, "wb") as f:
    f.write(pp0)
AP1b = os.path.join(BASE, "--apply")
with open(AP1b, "w", encoding="utf-8") as f:
    f.write(LINT_OK.format(d=D1b))
cwd1b = os.getcwd()
os.chdir(BASE)
try:
    rc, out = run(OUT, PUB, "--lint", "--apply", scan=ok_scan, lint=None)
finally:
    os.chdir(cwd1b)
chk("(계획 — 쓰기 0)" in out and status() == "" and head() == H0, "[1b] --lint 값 '--apply'(파일 이름) = 적용 아님 · 계획만 · 무변", (rc, out[-300:]))
os.unlink(AP1b)
if shutil.which("sha256sum") and shutil.which("find") and shutil.which("xargs"):
    sh1b = subprocess.run(["bash", "-c", "{ find src tools tests -name '*.py' -type f -print0; printf 'pyproject.toml\\0'; } | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | cut -c1-64"],
                          cwd=OUT, capture_output=True, text=True)
    chk(sh1b.returncode == 0 and sh1b.stdout.strip() == D1b, "[1b] 지문 = 도구 docstring 셸 한 줄과 같은 값", (sh1b.stdout.strip(), D1b, sh1b.stderr[-200:]))
else:
    print("SKIP [1b] sha256sum 없음 — 셸 한 줄 대조 건너뜀")
NOTGIT = os.path.join(BASE, "notgit")
os.makedirs(NOTGIT)
rc, out = run(OUT, NOTGIT, "--apply", scan=ok_scan)
chk(rc == 2 and "git 작업 폴더" in out and os.listdir(NOTGIT) == [], "[1] 공개 저장소가 git 아님 = rc 2", out[-200:])
rc, out = run(OUT, ROOT, scan=ok_scan)
chk(rc == 2, "[1] 공개 저장소가 이 트리 = rc 2", out[-200:])
LIC = os.path.join(PUB, "LICENSE")
with open(LIC, "rb") as f:
    lic0 = f.read()
with open(LIC, "ab") as f:
    f.write(b"synthetic staged secret\n")
subprocess.run(GIT + ["add", "LICENSE"], check=True)
with open(LIC, "wb") as f:
    f.write(lic0)
rc, out = run(OUT, PUB, "--apply", scan=ok_scan)
chk(rc == 2 and "커밋 안 한 변경" in out, "[1] 공개 저장소 인덱스에 검사 안 한 바이트 = rc 2(깨끗한 상태에서만)", out[-200:])
subprocess.run(GIT + ["reset", "-q", "--", "LICENSE"], check=True)
chk(status() == "", "[1] (시험 준비) 인덱스 되돌림")
OUTSIDE = os.path.join(BASE, "outside_config.json")
with open(OUTSIDE, "w") as f:
    f.write("{}\n")
os.symlink(OUTSIDE, os.path.join(PUB, "README.md"))
subprocess.run(GIT + ["add", "README.md"], check=True)
subprocess.run(GIT + ["commit", "-q", "-m", "link"], check=True)
H1 = head()
rc, out = run(OUT, PUB, "--apply", scan=ok_scan)
with open(OUTSIDE) as f:
    chk(rc == 1 and "심볼릭 링크 자리: README.md" in out and f.read() == "{}\n" and status() == "", "[1] 쓸 자리가 저장소 밖 링크 = rc 1 · 바깥 파일·저장소 무변", out[-300:])
subprocess.run(GIT + ["rm", "-q", "README.md"], check=True)
subprocess.run(GIT + ["commit", "-q", "-m", "unlink"], check=True)
H0 = head()
os.link(OUTSIDE, os.path.join(PUB, "VERSION.tj_sync_tmp"))
os.symlink(OUTSIDE, os.path.join(PUB, "README.md.tj_sync_tmp"))

for rel12, how12 in (("VERSION", "미추적"), ("src/version.py", "무시")):
    os.makedirs(os.path.dirname(os.path.join(PUB, rel12)), exist_ok=True)
    with open(os.path.join(PUB, rel12), "w") as f:
        f.write("synthetic developer work\n")
    if how12 == "무시":
        with open(os.path.join(PUB, ".git", "info", "exclude"), "a") as f:
            f.write("/src/version.py\n")
    for args12 in ((), ("--apply",)):
        rc, out = run(OUT, PUB, *args12, scan=ok_scan)
        with open(os.path.join(PUB, rel12)) as f:
            chk(rc == 1 and rel12 in out and f.read() == "synthetic developer work\n" and status() == "" and head() == H0,
                f"[1] 복사 자리에 {how12} 파일 {rel12} {' '.join(args12) or '(계획)'} = rc 1 · 그 파일·저장소 무변", out[-300:])
    os.remove(os.path.join(PUB, rel12))
shutil.rmtree(os.path.join(PUB, "src"), ignore_errors=True)
with open(os.path.join(PUB, ".git", "info", "exclude"), "w") as f:
    f.write("")

rc, out = run(OUT, PUB, scan=ok_scan)
n = len(p["files"]) + 1
chk(rc == 0 and f"새로·바뀐 {n - 1} · 같음 1 · 지울 추적 파일 1" in out and "old_only.txt" in out and status() == "",
    "[2] 계획 = 셈만(LICENSE 같음 · 옛 파일 지울 것) · 쓰기 0", out[-300:])

rc, out = run(OUT, PUB, "--apply", scan=ok_scan)
cached = subprocess.run(["git", "-C", PUB, "diff", "--cached", "--name-status"], capture_output=True, text=True).stdout.splitlines()
chk(rc == 0 and head() == H0 and len([c for c in cached if c.startswith("A")]) == n - 1 and "D\told_only.txt" in cached,
    "[3] 적용 = 복사·git add · 옛 추적 파일 git rm · 커밋 0", (rc, len(cached), out[-200:]))
chk(os.stat(os.path.join(PUB, "tools", "setup.sh")).st_mode & 0o111 and not os.stat(os.path.join(PUB, "README.md")).st_mode & 0o111,
    "[3] 실행 비트 = 산출물 그대로")
chk("인덱스 = 산출물" in out, "[3] 적용 뒤 인덱스 = 산출물(경로·바이트) 재확인", out[-200:])
with open(OUTSIDE) as f:
    chk(f.read() == "{}\n" and not any(x.startswith(".tj_sync_") for x in os.listdir(PUB)), "[3] 미리 둔 임시 자리 링크를 안 따라감 · 바깥 파일 무변 · 남은 임시 파일 0")
rc, out = run(OUT, PUB, scan=ok_scan)
chk(rc == 2 and "커밋 안 한 변경" in out, "[3] 커밋 전 다시 돌리면 거부(사람이 커밋한 뒤에만)", out[-200:])
subprocess.run(GIT + ["commit", "-q", "-m", "sync"], check=True)
rc, out = run(OUT, PUB, scan=ok_scan)
chk(rc == 0 and f"새로·바뀐 0 · 같음 {n} · 지울 추적 파일 0" in out, "[3] 커밋 뒤 다시 계획 = 바꿀 것 0", out[-200:])

PUB2 = os.path.join(BASE, "pubrepo_nofm")
os.makedirs(os.path.join(PUB2, "tools"))
GIT2 = ["git", "-C", PUB2, "-c", "user.name=t", "-c", "user.email=t@t.invalid", "-c", "commit.gpgsign=false"]
subprocess.run(GIT2 + ["init", "-q"], check=True)
subprocess.run(GIT2 + ["config", "core.filemode", "false"], check=True)
EXE = sorted(f for f in _files_of(OUT) if os.stat(os.path.join(OUT, f)).st_mode & 0o111)
chk(EXE and "tools/setup.sh" in EXE, "[4] (전제) 산출물에 실행 파일 있음(tools/setup.sh)", EXE)
shutil.copyfile(os.path.join(OUT, "tools", "setup.sh"), os.path.join(PUB2, "tools", "setup.sh"))
os.chmod(os.path.join(PUB2, "tools", "setup.sh"), 0o755)
shutil.copyfile(os.path.join(OUT, "README.md"), os.path.join(PUB2, "README.md"))
os.chmod(os.path.join(PUB2, "README.md"), 0o644)
subprocess.run(GIT2 + ["add", "-A"], check=True)
subprocess.run(GIT2 + ["update-index", "--chmod=-x", "tools/setup.sh"], check=True)
subprocess.run(GIT2 + ["update-index", "--chmod=+x", "README.md"], check=True)
subprocess.run(GIT2 + ["commit", "-q", "-m", "init"], check=True)


def stage_modes(repo):
    got = {}
    for ent in subprocess.run(["git", "-C", repo, "ls-files", "-s", "-z"], capture_output=True, text=True, check=True).stdout.split("\0"):
        if ent:
            meta, path = ent.split("\t", 1)
            got[path] = meta.split()[0]
    return got


m0 = stage_modes(PUB2)
chk(m0 == {"tools/setup.sh": "100644", "README.md": "100755"}, "[4] (전제) 인덱스 모드 = 산출물과 반대(바이트는 같음)", m0)
with open(os.path.join(PUB2, ".git", "info", "exclude"), "w") as f:
    f.write("")
rc, out = run(OUT, PUB2, scan=ok_scan)
chk(rc == 0 and f"새로·바뀐 {n} · 같음 0 · 지울 추적 파일 0" in out, "[4] 계획: 인덱스 모드만 다른 파일도 '같음' 아님(바꿀 것에 셈)", out[-300:])
rc, out = run(OUT, PUB2, "--apply", scan=ok_scan)
m1 = stage_modes(PUB2)
want = {f: ("100755" if f in EXE else "100644") for f in _files_of(OUT)}
chk(rc == 0 and m1 == want, "[4] 적용 뒤 인덱스 모드 = 산출물 실행 비트(새 파일 · 불가→가능 · 가능→불가 · filemode=false)",
    (rc, {k: v for k, v in m1.items() if want.get(k) != v}, out[-300:]))
chk("실행 모드" in out, "[4] 성공 문구 = 경로·바이트·실행 모드까지 확인했다고 말함", out[-200:])
subprocess.run(GIT2 + ["commit", "-q", "-m", "sync"], check=True)
CL = os.path.join(BASE, "pub_clone")
subprocess.run(["git", "clone", "-q", "--no-hardlinks", PUB2, CL], check=True, capture_output=True)
bad_cl = [f for f in _files_of(OUT) if bool(os.stat(os.path.join(CL, f)).st_mode & 0o111) != (f in EXE)]
chk(not bad_cl, "[4] 새 clone 실행 비트 = 산출물(tools/setup.sh 실행 가능 · README.md 아님)", bad_cl[:10])
rc, out = run(OUT, PUB2, scan=ok_scan)
chk(rc == 0 and f"새로·바뀐 0 · 같음 {n} · 지울 추적 파일 0" in out, "[4] 커밋 뒤 다시 계획 = 바꿀 것 0", out[-200:])
subprocess.run(GIT2 + ["update-index", "--chmod=-x", "tools/setup.sh"], check=True)
chk("tools/setup.sh" in SP._index_matches(PUB2, OUT, _files_of(OUT)), "[4] 인덱스 모드 어긋남 = 재확인이 잡음(바이트 같아도)")
subprocess.run(GIT2 + ["update-index", "--chmod=+x", "tools/setup.sh"], check=True)
os.environ.update(keep_env)
shutil.rmtree(OUT, ignore_errors=True)
shutil.rmtree(PUB, ignore_errors=True)
shutil.rmtree(PUB2, ignore_errors=True)
shutil.rmtree(CL, ignore_errors=True)
T.finish()
