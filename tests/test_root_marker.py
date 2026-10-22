#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402

chk = T.chk
PY = sys.executable
OLD = "common" + ".py"
ENV = {k: v for k, v in os.environ.items() if not k.startswith("TJ_")}
ENV.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
TOOLS = os.path.join(T.ROOT, "tools", "refactor")


def run(args, cwd=None, env=None):
    p = subprocess.run(args, cwd=cwd or T.TMP, env=env or ENV, capture_output=True, text=True, encoding="utf-8", timeout=120)
    return p.returncode, p.stdout + p.stderr


def make_tree(name, repo, version=True):
    base = os.path.join(T.TMP, name)
    tests = os.path.join(base, "public", "tests") if repo else os.path.join(base, "tests")
    os.makedirs(os.path.join(tests, "arch_baseline"))
    os.makedirs(os.path.join(base, "src"))
    if version:
        shutil.copy(os.path.join(T.SRC, "version.py"), os.path.join(base, "src", "version.py"))
    with open(os.path.join(base, "src", "tiny.py"), "w", encoding="utf-8") as f:
        f.write('"""작은 모듈 — 지도 견본."""\n__all__ = ["one"]\n\n\ndef one():\n    """하나."""\n    return 1\n')
    for fn in ("_harness.py", "run_all.py", "_arch_ratchet.py", "_arch_codemap.py"):
        shutil.copy(os.path.join(T.HERE, fn), os.path.join(tests, fn))
    with open(os.path.join(tests, "arch_baseline", "layers.json"), "w", encoding="utf-8") as f:
        json.dump({"layers": ["기반"], "modules": {"tiny": "기반", "version": "기반"}}, f)
    with open(os.path.join(tests, "test_probe.py"), "w", encoding="utf-8") as f:
        f.write("import _harness as T\nprint('ROOT=' + T.ROOT)\nT.chk(True, 'probe')\nT.finish()\n")
    return os.path.realpath(base), tests


for label, repo in (("저장소 배치", True), ("공개판 배치", False)):
    base, tests = make_tree("t_repo" if repo else "t_pub", repo)
    chk(not os.path.exists(os.path.join(base, "src", OLD)), "[1] %s 임시 트리에 옛 표식 파일 없음(전제)" % label)
    rc, out = run([PY, os.path.join(tests, "run_all.py"), "probe", "-v"])
    chk(rc == 0 and "시험 파일 1개" in out and "전부 통과" in out, "[1] %s run_all 이 첫 시험을 돌림(rc 0)" % label, out[-400:])
    rc, out = run([PY, os.path.join(tests, "test_probe.py")])
    chk(rc == 0 and ("ROOT=" + base) in out, "[1] %s _harness 뿌리 = 그 임시 트리(src/version.py 로 찾음)" % label, out[-300:])
nb, nt = make_tree("t_none", True, version=False)
rc, out = run([PY, os.path.join(nt, "run_all.py")])
chk(rc == 1 and "version.py" in out, "[1] 뿌리 표식이 없으면 run_all 이 멈추고 version.py 를 찾으라고 안내", out[-300:])

for label, repo, want in (("저장소 배치", True, "True"), ("공개판 배치", False, "False")):
    base, tests = make_tree("r_repo" if repo else "r_pub", repo)
    rc, out = run([PY, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import _arch_ratchet as R; print(R.repo_layout())", tests])
    chk(rc == 0 and out.strip().endswith(want), "[2] %s _arch_ratchet.repo_layout() = %s" % (label, want), out[-300:])
    rc, out = run([PY, os.path.join(tests, "_arch_codemap.py")])
    if repo:
        chk(rc == 0 and "`tiny`" in out and "`version`" in out, "[2] 저장소 배치 _arch_codemap = 지도 만듦(옛 표식 없이)", out[-300:])
    else:
        chk(rc == 1 and "공개판 배치" in out, "[2] 공개판 배치 _arch_codemap = 정당하게 건너뜀(종료 1 · 안내)", out[-300:])

if not os.path.isfile(os.path.join(TOOLS, "gate.sh")):
    chk(True, "[3] 공개판 — 비공개 도구(tools/refactor) 없음 · 건너뜀")
    T.finish()
base, tests = make_tree("g_repo", True)
nb, _nt = make_tree("g_none", True, version=False)
rc, out = run(["bash", os.path.join(TOOLS, "gate.sh"), base, "probe", "--nogolden"])
chk(rc == 2 and "트리에 도구 없음" in out, "[3] gate.sh 머리 = version.py 로 트리를 알아보고 다음 준비물(도구)에서 멈춤", out[-300:])
rc, out = run(["bash", os.path.join(TOOLS, "gate.sh"), nb, "probe", "--nogolden"])
chk(rc == 2 and "코드 트리가 아님" in out, "[3] gate.sh 머리 = version.py 없는 트리 거부", out[-300:])
env = dict(ENV)
rc, out = run(["bash", os.path.join(TOOLS, "pub_dryrun.sh"), base, "probe"], env=env)
chk(rc == 2 and "공개 빌드 도구 없음" in out, "[3] pub_dryrun.sh 머리 = version.py 로 트리를 알아보고 빌드 도구 확인에서 멈춤", out[-300:])
rc, out = run(["bash", os.path.join(TOOLS, "pub_dryrun.sh"), nb, "probe"], env=env)
chk(rc == 2 and "코드 트리가 아님" in out, "[3] pub_dryrun.sh 머리 = version.py 없는 트리 거부", out[-300:])
stage, _st = make_tree("g_stage", False)
rc, out = run([PY, "-I", os.path.join(TOOLS, "pub_checklist.py"), base, stage])
chk(rc in (0, 1) and "공개판 점검 목록" in out, "[3] pub_checklist = 트리·stage 를 version.py 로 알아봄(점검 목록 출력)", out[-300:])
rc, out = run([PY, "-I", os.path.join(TOOLS, "pub_checklist.py"), nb, stage])
chk(rc == 2 and "version.py" in out, "[3] pub_checklist = 표식 없는 트리 거부", out[-300:])
sys.path.insert(0, TOOLS)
import root_marker as RM  # noqa: E402
shapes = ['if Path(root, "src", "%s").is_file():' % OLD, 'os.path.isfile(os.path.join(f(a), "src", "%s"))' % OLD,
          '[ -f "$T/src/%s" ] || die' % OLD, '(root / "src" / "%s").exists()' % OLD, 'test -e src/%s' % OLD]
got = [RM.classify("public/tests/_harness.py", x) for x in shapes]
chk(got == ["marker"] * len(shapes) and RM.classify("public/tests/test_x.py", 'derive(PART, "src/%s")' % OLD) == "sample",
    "[3] 전수 분류: 있는지 보는 꼴(os.path·pathlib·셸 [ -f ]·test -e) = 뿌리 표식 · 견본 경로 = 견본", got)
import tempfile  # noqa: E402
with tempfile.TemporaryDirectory() as td:
    for rel, data in ((".github/workflows/tests.yml", b'[ -f src/%s ]\n'), ("public/ci/tests.yaml", b'test -e src/%s\n'),
                      ("tools/runme", b'if [ -f src/%s ]; then :; fi\n'), ("web/x.png", b'\0[ -f src/%s ]'),
                      (".git/hooks/pre", b'[ -f src/%s ]\n')):
        os.makedirs(os.path.join(td, os.path.dirname(rel)), exist_ok=True)
        with open(os.path.join(td, rel), "wb") as f:
            f.write(data.replace(b"%s", OLD.encode()))
    got = sorted((h["path"], h["kind"]) for h in RM.scan(td))
chk(got == [(".github/workflows/tests.yml", "marker"), ("public/ci/tests.yaml", "marker"), ("tools/runme", "marker")],
    "[3] 전수 분류 대상: 숨김 폴더(.github) · .yaml · 확장자 없는 글 파일 포함 · 바이너리·.git 제외", got)
rc, out = run([PY, "-I", os.path.join(TOOLS, "root_marker.py"), T.ROOT, "--json"])
got = json.loads(out) if rc in (0, 1) and out.strip().startswith("{") else {"counts": {"error": out[-300:]}}
cnt = got["counts"]
chk(rc == 0 and not cnt.get("marker") and not cnt.get("other"), "[3] 저장소 전수 분류: 옛 파일을 뿌리 표식으로 쓰는 곳 0 · 미분류 0", cnt)
print("  분류: " + " · ".join("%s %s" % kv for kv in sorted(cnt.items())))
T.finish()
