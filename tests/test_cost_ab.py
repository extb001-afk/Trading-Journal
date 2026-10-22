#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

chk = T.chk
TOOLS = os.path.join(T.ROOT, "tools", "refactor")
if not os.path.isfile(os.path.join(TOOLS, "cost_ab.py")):
    chk(True, "공개판 배치 — 비공개 도구(tools/refactor/cost_ab.py) 없음 · 건너뜀")
    T.finish()
sys.path.insert(0, TOOLS)
import cost_ab as A  # noqa: E402

tab = A.load_table()
now_list = A.list_tests(T.HERE)
chk(tab["tests"] == now_list, "A1 표 = 지금 합성 빌드 시험 목록(%d) — 시험이 생기거나 빠지면 표를 같이 고칠 것" % len(now_list),
    {"표에만": sorted(set(tab["tests"]) - set(now_list)), "목록에만": sorted(set(now_list) - set(tab["tests"]))})
chk(set(tab.get("excluded", {})) <= set(tab["tests"]) and all(isinstance(v, str) and v for v in tab.get("excluded", {}).values()),
    "A1 excluded ⊂ tests · 이유 글", tab.get("excluded"))

tmp = tempfile.mkdtemp(prefix="tj_costab_")
try:
    cases = {"test_a.py": ("import web\nb = web.StateBuilder()\n", True), "test_b.py": ("x = obj._build_replay\n", True),
             "test_c.py": ("b._build(conn)\n", True), "test_d.py": ("s = 'StateBuilder._build_replay ._build('\n", False),
             "test_e.py": ("def _build():\n    pass\n_build()\n", False), "helper.py": ("import web\nweb.StateBuilder()\n", False)}
    td = os.path.join(tmp, "t2")
    os.makedirs(td)
    for n, (body, _w) in cases.items():
        with open(os.path.join(td, n), "w", encoding="utf-8") as f:
            f.write(body)
    chk(A.list_tests(td) == ["test_a.py", "test_b.py", "test_c.py"], "A2 목록 규칙(AST · 문자열·함수 이름 _build·test_ 아닌 파일 제외)", A.list_tests(td))

    def side(d, root, tests):
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "_run.json"), "w", encoding="utf-8") as f:
            json.dump({"root": root, "now": 1.0, "tests": {t: {"rc": v.get("_run_rc", 0), "s": 0} for t, v in tests.items()}}, f)
        for t, v in tests.items():
            if v.get("_nofile"):
                continue
            with open(os.path.join(d, t + ".json"), "w", encoding="utf-8") as f:
                json.dump({k: x for k, x in v.items() if not k.startswith("_")}, f)

    def fp(boundary="b1", realized="0", trail=None):
        return {"boundary": {"G": {"d": boundary}}, "opaque": [], "fails": [],
                "cost": {"version": 1, "groups": [[1, "A", "1", "2", "0", realized, "2", 0, "x", 0, "y"]], "books": {},
                         "trail": trail or [[10, 1, "h"]], "trail_calls": 1, "opaque": []}}

    def rec(root, calls=1, fps=None, files=None, rc=0, **kw):
        r = {"calls": calls, "rc": rc, "fails": [], "fps": fps if fps is not None else [fp()], "hashseed": "0",
             "files": files if files is not None else {"view_b_replay": root + "/src/view_b_replay.py", "accounting_cp": root + "/src/accounting_cp.py"}}
        r.update(kw)
        return r

    def cmp(ta, tb, ra="/ra", rb="/rb"):
        n = str(len(os.listdir(tmp)))
        da, db = os.path.join(tmp, "a" + n), os.path.join(tmp, "b" + n)
        side(da, ra, ta)
        side(db, rb, tb)
        return A.compare(da, db)

    h, d, s = cmp({"test_x.py": rec("/ra")}, {"test_x.py": rec("/rb")})
    chk(not h and not d and s == 1, "A3 같은 지문(뿌리만 다름) = 같음", (h, d))
    h, d, s = cmp({"test_x.py": rec("/ra", calls=0)}, {"test_x.py": rec("/rb", calls=0)})
    chk(h and "호출 0" in h[0], "A3 감싼 _build_replay 호출 0 = 머리 실패", h)
    h, d, s = cmp({"test_x.py": rec("/ra", files={"view_b_replay": "/elsewhere/src/view_b_replay.py"})}, {"test_x.py": rec("/rb")})
    chk(h and "뿌리 밖" in h[0], "A3 뿌리 밖에서 실린 파일 = 머리 실패", h)
    h, d, s = cmp({"test_x.py": rec("/ra", files={"accounting_cp": "/ra/src/accounting_cp.py"})}, {"test_x.py": rec("/rb")})
    chk(h and "view_b_replay 안 실림" in h[0], "A3 view_b_replay 안 실림 = 머리 실패", h)
    h, d, s = cmp({"test_x.py": rec("/ra", calls=2, fps=[fp(), fp()])}, {"test_x.py": rec("/rb")})
    chk(h and "호출 수" in h[0], "A3 호출 수 다름 = 머리 실패", h)
    h, d, s = cmp({"test_x.py": rec("/ra", hashseed="ignored")}, {"test_x.py": rec("/rb")})
    chk(h and "해시 시드" in h[0], "A3 해시 시드 고정 안 됨(-I 로 PYTHONHASHSEED 무시) = 머리 실패", h)
    h, d, s = cmp({"test_x.py": dict(rec("/ra"), _run_rc="timeout")}, {"test_x.py": rec("/rb")})
    chk(h and "시간 상한" in h[0], "A3 시간 상한 = 머리 실패", h)
    h, d, s = cmp({"test_x.py": rec("/ra")}, {"test_x.py": rec("/rb", fps=[fp(boundary="b2")])})
    chk(not h and d and "경계 1곳: G" in d[0], "A3 경계 지문 차이", d)
    h, d, s = cmp({"test_x.py": rec("/ra")}, {"test_x.py": rec("/rb", fps=[fp(realized="1", trail=[[10, 1, "h2"]])])})
    chk(not h and d and "그룹 1(A)" in d[0] and "처음 갈린 행 #0" in d[0], "A3 원가 지문 차이(그룹·행 위치)", d)
    h, d, s = cmp({"test_x.py": rec("/ra")}, {"test_x.py": dict(rec("/rb", rc=1), _run_rc=1)})
    chk(not h and d and "rc 0 → 1" in d[0], "A3 시험 rc 차이", d)
    h, d, s = cmp({"test_x.py": rec("/ra")}, {"test_x.py": dict(rec("/rb"), _run_rc=-9)})
    chk(h and "실행 rc -9" in h[0], "A3 지문 파일 rc ≠ 실제 종료 코드(옛 지문 재사용·비정상 종료) = 머리 실패", h)
    bad9 = {"boundary": None, "cost": None, "opaque": [], "fails": ["boundary 지문 예외"]}
    h, d, s = cmp({"test_x.py": rec("/ra", fps=[bad9])}, {"test_x.py": rec("/rb", fps=[bad9])})
    chk(h and "수집 실패" in h[0], "A3 양쪽 같은 지문 수집 실패 = 같음 아님(머리 실패)", h)
    h, d, s = cmp({"test_x.py": rec("/ra", fails=["지문 예외 X"])}, {"test_x.py": rec("/rb", fails=["지문 예외 X"])})
    chk(h and "수집 실패" in h[0], "A3 양쪽 같은 기록 실패(fails) = 머리 실패", h)
    h, d, s = cmp({"test_x.py": rec("/ra", test_exc="IndexError: x")}, {"test_x.py": rec("/rb", test_exc="IndexError: x")})
    chk(not h and not d, "A3 시험 자체 예외가 양쪽 같으면 지문 비교는 그대로(수집 실패 아님)", (h, d))
    h, d, s = cmp({"test_x.py": rec("/ra", test_exc="IndexError: x")}, {"test_x.py": rec("/rb")})
    chk(not h and d and "시험 예외" in d[0], "A3 시험 자체 예외 한쪽만 = 차이", d)

    g = os.path.join(tmp, "g")
    os.makedirs(os.path.join(g, "src"))
    with open(os.path.join(g, "src", "m.py"), "w", encoding="utf-8") as f:
        f.write("x = 1\n")
    env9 = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    for c in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "b"]):
        subprocess.run(["git", "-C", g] + c, check=True, env=env9)
    with open(os.path.join(g, "src", "m.py"), "w", encoding="utf-8") as f:
        f.write("x = 2\n")
    dest = os.path.join(tmp, "arch")
    A.archive(g, "HEAD", dest)
    with open(os.path.join(dest, "src", "m.py"), encoding="utf-8") as f:
        chk(f.read() == "x = 1\n", "A4 archive = rev 의 트리(작업 트리 변경 아님)")
    try:
        A.archive(g, "HEAD", dest)
        chk(False, "A4 비어 있지 않은 폴더 거부")
    except SystemExit:
        chk(True, "A4 비어 있지 않은 폴더 거부")

    one = "test_calc_fee_cost.py"
    if one in tab["tests"] and one not in tab.get("excluded", {}):
        cp9 = os.path.join(tmp, "root")
        os.makedirs(cp9)
        for n in ("src", "seed", "web"):
            if os.path.isdir(os.path.join(T.ROOT, n)):
                shutil.copytree(os.path.join(T.ROOT, n), os.path.join(cp9, n), ignore=shutil.ignore_patterns("__pycache__"))
        for n in ("VERSION",):
            if os.path.isfile(os.path.join(T.ROOT, n)):
                shutil.copy2(os.path.join(T.ROOT, n), os.path.join(cp9, n))
        outs = {}
        with contextlib.redirect_stdout(io.StringIO()):
            for tag, root in (("w1", T.ROOT), ("w2", T.ROOT), ("c1", cp9)):
                outs[tag] = os.path.join(tmp, "run_" + tag)
                A.run(root, T.HERE, outs[tag], [one], 1, 240, A.NOW_DEFAULT)
        try:
            A.run(T.ROOT, T.HERE, outs["w1"], [one], 1, 240, A.NOW_DEFAULT)
            chk(False, "A5 지난 판 지문이 있는 --out 재사용 거부")
        except SystemExit:
            chk(True, "A5 지난 판 지문이 있는 --out 재사용 거부")
        h, d, s = A.compare(outs["w1"], outs["w2"])
        chk(not h and not d and s == 1, "A5 같은 뿌리 두 번 = 차이 0", (h, d))
        h, d, s = A.compare(outs["w1"], outs["c1"])
        chk(not h and not d and s == 1, "A5 뿌리 사본을 작업 자리에 = 차이 0", (h, d))
        with open(os.path.join(outs["c1"], one + ".json"), encoding="utf-8") as f:
            files9 = json.load(f)["files"]
        chk(files9 and all(p.startswith(os.path.realpath(cp9) + os.sep) for p in files9.values()), "A5 실린 파일 = 고른 뿌리(사본) 밑", files9)
        p9 = os.path.join(cp9, "src", "accounting_fee.py")
        with open(p9, encoding="utf-8") as f:
            s9 = f.read()
        old9 = 'g9["realized"] += '
        if s9.count(old9) == 1:
            with open(p9, "w", encoding="utf-8") as f:
                f.write(s9.replace(old9, 'g9["realized"] += Decimal("1e-20") + '))
            with contextlib.redirect_stdout(io.StringIO()):
                outs["m1"] = os.path.join(tmp, "run_m1")
                A.run(cp9, T.HERE, outs["m1"], [one], 1, 240, A.NOW_DEFAULT)
            h, d, s = A.compare(outs["w1"], outs["m1"])
            chk(not h and d, "A5 사본 원가 한 줄 바꿈(fee_gain 실현) = 차이(도구가 고른 뿌리를 씀)", (h, d))
        else:
            chk(True, "A5 바꿀 줄(fee_gain realized) 꼴이 달라 변이 시험 건너뜀")
    else:
        chk(True, "A5 %s 가 표에 없거나 제외 — 한 판 시험 건너뜀" % one)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
T.finish()
