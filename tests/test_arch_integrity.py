#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _arch as A  # noqa: E402

import _arch_py_checks as C  # noqa: E402

import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402

if shutil.which("git") is None:
    A.T.chk(True, "[0] git 없음 — 기준 커밋 합성 건너뜀")
else:
    GENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
                GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)

    def git(repo, *args):
        return subprocess.run(["git", "-C", repo, "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"] + list(args), check=True,
                              env=GENV, capture_output=True, text=True).stdout.strip()

    def repo_with(name, files_per_commit, tag_at=None):
        r = os.path.join(A.T.TMP, name)
        os.makedirs(r)
        git(r, "init", "-q", "-b", "main")
        shas = []
        for i, files in enumerate(files_per_commit):
            for fn, body in files.items():
                with open(os.path.join(r, fn), "w", encoding="utf-8") as f:
                    f.write(body)
            git(r, "add", "-A")
            git(r, "commit", "-q", "-m", "c%d" % i)
            shas.append(git(r, "rev-parse", "HEAD"))
            if tag_at == i:
                git(r, "tag", "v1")
        return r, shas

    r1, s1 = repo_with("pub_tag", [{"VERSION": "1\n"}, {"VERSION": "2\n"}, {"a.txt": "x\n"}], tag_at=0)
    got1 = C.base_commit(r1, True)
    A.T.chk(got1 == (s1[0], "마지막 태그 v1", None), "[0] 공개판 배치 + 태그 = 마지막 태그 커밋(VERSION 을 더 뒤에 바꿔도 태그가 먼저)", got1)
    r2, s2 = repo_with("pub_ver", [{"VERSION": "1\n"}, {"VERSION": "2\n"}, {"a.txt": "x\n"}])
    got2 = C.base_commit(r2, True)
    A.T.chk(got2 == (s2[1], "VERSION 마지막 커밋", None), "[0] 공개판 배치 + 태그 없음 = VERSION 을 마지막으로 바꾼 커밋", got2)
    sh2 = os.path.join(A.T.TMP, "pub_shallow")
    subprocess.run(["git", "clone", "-q", "--depth", "1", "file://" + r2, sh2], check=True, env=GENV, capture_output=True)
    got2s = C.base_commit(sh2, True)
    A.T.chk(got2s[0] is None and "얕은 복제" in got2s[2], "[0] 공개판 배치 + 태그 없는 얕은 복제 = 건너뜀(VERSION 커밋 = 얕은 경계 HEAD 와 자기 비교 금지)", got2s)
    sub = os.path.join(A.T.TMP, "pub_sub")
    os.makedirs(os.path.join(sub, "pkg"))
    git(sub, "init", "-q", "-b", "main")
    for i, body in enumerate(("1\n", "2\n")):
        with open(os.path.join(sub, "pkg", "VERSION"), "w", encoding="utf-8") as f:
            f.write(body)
        git(sub, "add", "-A")
        git(sub, "commit", "-q", "-m", "v%d" % i)
    with open(os.path.join(sub, "b.txt"), "w", encoding="utf-8") as f:
        f.write("x\n")
    git(sub, "add", "-A")
    git(sub, "commit", "-q", "-m", "other")
    got2b = C.base_commit(os.path.join(sub, "pkg"), True)
    A.T.chk(got2b[0] == git(sub, "rev-parse", "HEAD~1") and got2b[1] == "VERSION 마지막 커밋", "[0] 공개판 배치가 저장소 하위 폴더 = 그 폴더의 VERSION 커밋", got2b)
    r3, _s3 = repo_with("pub_none", [{"a.txt": "x\n"}])
    got3 = C.base_commit(r3, True)
    A.T.chk(got3[0] is None and "태그도 VERSION 커밋도 없음" in got3[2], "[0] 공개판 배치 + 태그·VERSION 커밋 없음 = 건너뜀(이유)", got3)
    nogit = os.path.join(A.T.TMP, "pub_nogit")
    os.makedirs(nogit)
    got4 = C.base_commit(nogit, True)
    A.T.chk(got4[0] is None and "깃 없는 사본" in got4[2], "[0] 공개판 배치 + git 작업 트리 아님 = 건너뜀(이유)", got4)
    got5 = C.base_commit(r1, False)
    A.T.chk(got5[0] is None and "기준 브랜치 'refactor'" in got5[2], "[0] 저장소 배치 = refactor merge-base 그대로(태그가 있어도 안 씀 · 없으면 건너뜀)", got5)
    git(r1, "branch", "refactor", s1[1])
    got6 = C.base_commit(r1, False)
    A.T.chk(got6 == (s1[1], "refactor", None), "[0] 저장소 배치 + refactor 있음 = merge-base", got6)
    got7 = (C.base_commit(r1, True, "skip"), C.base_commit(r1, True, s1[2]))
    A.T.chk(got7[0][0] is None and got7[1][0] == s1[2], "[0] TJ_TEST_ARCH_BASE_REF = 두 배치 모두 우선(skip = 건너뜀)", got7)

old9 = '{"_doc": "x", "kind": "set", "spec": "hyg_srctext"}\n{"set": "src_readers", "key": "test_a.py"}\n{"set": "src_readers", "key": "test_b.py"}\n'
add9 = old9 + '{"set": "src_readers", "key": "test_new.py"}\n'
drop9 = '{"_doc": "x", "kind": "set", "spec": "hyg_srctext"}\n{"set": "src_readers", "key": "test_a.py"}\n'
lc = (C.loosened_cls("hyg_srctext.jsonl", add9, old9), C.loosened_cls("hyg_srctext.jsonl", drop9, old9),
      C.loosened_cls("hyg_untested.jsonl", '{"set": "modules", "key": "m1"}\n{"set": "modules", "key": "m2"}\n', '{"set": "modules", "key": "m1"}\n'))
A.T.chk(len(lc[0]) == 1 and "test_new.py" in lc[0][0] and lc[1] == [] and len(lc[2]) == 1 and "m2" in lc[2][0] and C._ours("hyg_srctext.jsonl"),
        "[0] 시험 분류 기준선: 목록에 새 항목 = 느슨해짐(공개판 배치도 기준 커밋과 견줌) · 줄인 것 = 통과", lc)

C.run_integrity()
A.T.finish()
