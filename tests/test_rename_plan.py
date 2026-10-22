#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

chk = T.chk
TOOLS = os.path.join(T.ROOT, "tools", "refactor")
if not os.path.isfile(os.path.join(TOOLS, "test_rename.py")):
    _pub = os.path.realpath(T.HERE) == os.path.realpath(os.path.join(T.ROOT, "tests"))
    chk(_pub, "공개판 배치 — 비공개 도구(tools/refactor/test_rename.py) 없음 · 건너뜀" if _pub else "저장소 배치인데 비공개 도구 없음(건너뛰지 않고 실패)")
    T.finish()
sys.path.insert(0, TOOLS)
import test_rename as TR  # noqa: E402
import _arch_hyg as H  # noqa: E402

OLD_A, OLD_B = "test_foo" + "1012.py", "test_foo" + "1012b.py"
FILES = {
    "public/tests/" + OLD_A: '"""foo."""\n# python3 tests/' + OLD_A + '\n',
    "public/tests/" + OLD_B: '"""foo b."""\n# 앞 판 = ' + OLD_A[:-3] + '\n',
    "public/tests/test_plain.py": '"""plain."""\n',
    "public/tests/test_other.py": '"""other."""\nNAMES = ["' + OLD_B + '"]\n',
    "public/tests/arch_baseline/hyg_names.jsonl": '{"_doc": "x"}\n{"set": "round_named_tests", "key": "' + OLD_A + '"}\n'
                                                  '{"set": "round_named_tests", "key": "' + OLD_B + '"}\n',
    "public/tests/arch_baseline/hyg_checks.jsonl": '{"key": "' + OLD_A + '", "n": 3}\n{"key": "' + OLD_B + '", "n": 2}\n',
    "tools/refactor/cost_ab_tests.json": '{"tests": ["' + OLD_B + '"]}\n',
    "dev/old/CHANGES_x.diff": "+ " + OLD_A + "\n+ " + OLD_A + "\n",
}
GOOD = {OLD_A: ("test_foo_first.py", "첫 판"), OLD_B: ("test_foo_second.py", "둘째 판")}

ROOTD = tempfile.mkdtemp(prefix="tj_rename_plan_", dir=T.TMP)
OUTD = tempfile.mkdtemp(prefix="tj_rename_out_", dir=T.TMP)
try:
    for rel, text in FILES.items():
        path = os.path.join(ROOTD, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    gate = os.path.join(OUTD, "gate_x.sh")
    with open(gate, "w", encoding="utf-8") as f:
        f.write("echo one\npython3 tests/" + OLD_B + "\n")

    d = TR.plan(ROOTD, [OUTD], GOOD)
    rows = {r["old"]: r for r in d["rows"]}
    chk(d["ok"] and not d["errors"], "[1] 바른 표 = ok", d["errors"])
    a, b = rows[OLD_A]["refs"], rows[OLD_B]["refs"]
    chk(len(a["baseline"]) == 2 and len(b["baseline"]) == 2, "[1] 기준선 줄 = hyg_names·hyg_checks 각 1(이름마다)", [a["baseline"], b["baseline"]])
    chk({h["file"] for h in rows[OLD_A]["hyg_rows"]} == {"hyg_names.jsonl", "hyg_checks.jsonl"}
        and any(h["row"].get("n") == 3 for h in rows[OLD_A]["hyg_rows"]), "[1] 기준선 줄 내용(n 값) 그대로 담음", rows[OLD_A]["hyg_rows"])
    chk(b["cost_ab"] and not a["cost_ab"], "[1] cost_ab_tests.json 은 그 이름만", [a["cost_ab"], b["cost_ab"]])
    chk(len(a["self"]) == 1 and a["tests"] == ["public/tests/%s:2" % OLD_B],
        "[1] self = 자기 파일 · tests = 다른 시험의 이름 글자(…b 의 머리 글은 a 를 가리킴)", a)
    chk(b["tests"] == ["public/tests/test_other.py:2"], "[1] 앞부분이 같은 이름(a)은 b 참조로 안 잡힘", b["tests"])
    chk(a["history"] == 2 and b["history"] == 0, "[1] dev 이력 = 수만(바꾸지 않음)", [a["history"], b["history"]])

    chk(rows[OLD_B]["outside_report_only"] == ["gate_x.sh:2"] and rows[OLD_A]["outside_report_only"] == [],
        "[2] 저장소 밖 = 파일 이름:줄 만", rows[OLD_B]["outside_report_only"])
    chk(OUTD not in json.dumps(d, ensure_ascii=False), "[2] 결과에 저장소 밖 경로 글 없음", None)

    def errs(table):
        return TR.plan(ROOTD, [], table)["errors"]
    e = errs({OLD_A: ("test_bar" + "1013.py", "x"), OLD_B: GOOD[OLD_B]})
    chk(any("회차 이름" in x for x in e), "[3] 새 이름도 회차 이름 = 거부", e)
    e = errs({OLD_A: ("test_plain.py", "x"), OLD_B: GOOD[OLD_B]})
    chk(any("이미 있는" in x for x in e), "[3] 이미 있는 파일 = 거부", e)
    e = errs({OLD_A: ("test_same.py", "x"), OLD_B: ("test_same.py", "y")})
    chk(any("겹침" in x for x in e), "[3] 새 이름끼리 겹침 = 거부", e)
    e = errs({OLD_A: ("Test_Up.py", "x"), OLD_B: GOOD[OLD_B]})
    chk(any("꼴" in x for x in e), "[3] 꼴 틀림 = 거부", e)
    e = errs({OLD_A: GOOD[OLD_A]})
    chk(any("표 열쇠" in x for x in e), "[3] 표에 없는 회차 이름 = 거부", e)
    with open(os.path.join(ROOTD, "public/tests/arch_baseline/hyg_names.jsonl"), "w", encoding="utf-8") as f:
        f.write('{"set": "round_named_tests", "key": "' + OLD_A + '"}\n')
    e = errs(GOOD)
    chk(any("기준선" in x for x in e), "[3] 지금 회차 이름 ≠ 기준선 = 거부", e)
    chk(TR.main([]) == 2 and TR.main(["plan", "--bad"]) == 2, "[3] 모르는 명령·인자 = rc 2", None)
    with open(os.path.join(ROOTD, "public/tests/arch_baseline/hyg_names.jsonl"), "w", encoding="utf-8") as f:
        f.write(FILES["public/tests/arch_baseline/hyg_names.jsonl"])
    hc = os.path.join(ROOTD, "public/tests/arch_baseline/hyg_checks.jsonl")
    with open(hc, "a", encoding="utf-8") as f:
        f.write('{"key": "test_foo_first.py", "n": 1}\n')
    e = errs(GOOD)
    chk(any("기준선 열쇠에 이미" in x for x in e), "[3] 새 이름이 기준선 열쇠에 이미 있음 = 거부(값 덮임 방지)", e)
    with open(hc, "w", encoding="utf-8") as f:
        f.write(FILES["public/tests/arch_baseline/hyg_checks.jsonl"])
    ext = os.path.join(OUTD, "outside_ref.md")
    with open(ext, "w", encoding="utf-8") as f:
        f.write("see " + OLD_B + "\n")
    os.symlink(ext, os.path.join(ROOTD, "docs_link.md"))
    e = errs(GOOD)
    chk(any("심볼릭 링크" in x and "docs_link.md" in x for x in e), "[3] 참조 파일이 저장소 밖을 가리키는 링크 = 거부(apply 가 밖을 안 씀)", e)
    rc9, _l9 = TR.apply(ROOTD, GOOD)
    chk(rc9 == 1 and open(ext, encoding="utf-8").read() == "see " + OLD_B + "\n" and os.path.isfile(os.path.join(ROOTD, "public/tests", OLD_A)),
        "[3] 링크 있는 트리 apply = rc 1 · 링크 대상·시험 파일 그대로", _l9)
    os.remove(os.path.join(ROOTD, "docs_link.md"))
    hl = os.path.join(ROOTD, "docs_hard.md")
    os.link(ext, hl)
    e = errs(GOOD)
    chk(any("하드 링크" in x and "docs_hard.md" in x for x in e), "[3] 참조 파일이 저장소 밖 파일과 하드 링크 = 거부", e)
    os.remove(hl)

    news = [v[0] for v in TR.RENAMES.values()]
    chk(len(TR.RENAMES) == 25 and len(set(news)) == 25, "[4] 표 25 · 새 이름 겹침 0", len(set(news)))
    chk(not [n for n in news if H.round_named(n)] and all(n.startswith("test_") and n.endswith(".py") for n in news),
        "[4] 새 이름 = 회차 이름 아님 · test_*.py 꼴", [n for n in news if H.round_named(n)])
    chk(all(H.round_named(o) for o in TR.RENAMES), "[4] 옛 이름 = 모두 회차 이름", None)
    rn = os.path.join(T.HERE, "arch_baseline", "hyg_rename.json")
    done4 = [o for o, (n, _w) in TR.RENAMES.items() if not os.path.isfile(os.path.join(T.HERE, o)) and os.path.isfile(os.path.join(T.HERE, n))]
    if done4:
        tab = json.load(open(rn, encoding="utf-8")).get("renames") if os.path.isfile(rn) else None
        miss = sorted(o for o in done4 if not isinstance(tab, dict) or tab.get(o) != TR.RENAMES[o][0])
        chk(isinstance(tab, dict) and not miss, "[4] 바꾼 이름 %d 마다 승계 표 줄 있음(hyg_rename.json 있음 · ⊇ 바꾼 RENAMES)" % len(done4), miss)

    ROOT2 = tempfile.mkdtemp(prefix="tj_rename_apply_", dir=T.TMP)
    for rel, text in FILES.items():
        path = os.path.join(ROOT2, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    git = shutil.which("git")
    if not git:
        print("SKIP [5] git 없음")
    else:
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
        for args in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"]):
            subprocess.run([git, "-C", ROOT2] + args, check=True, capture_output=True, env=env, timeout=60)
        bad = {OLD_A: ("test_plain.py", "x"), OLD_B: GOOD[OLD_B]}
        rc, _l = TR.apply(ROOT2, bad)
        chk(rc == 1 and os.path.isfile(os.path.join(ROOT2, "public/tests", OLD_A)) and os.path.isfile(os.path.join(ROOT2, "public/tests", OLD_B)),
            "[5] plan 오류 = rc 1 · 아무것도 안 바꿈", _l)
        os.environ["GIT_DIR"] = os.path.join(OUTD, "not_a_repo")
        try:
            rc, lines = TR.apply(ROOT2, GOOD)
        finally:
            os.environ.pop("GIT_DIR", None)
        rd = lambda rel: open(os.path.join(ROOT2, rel), encoding="utf-8").read()  # noqa: E731
        chk(rc == 0 and not os.path.exists(os.path.join(ROOT2, "public/tests", OLD_A))
            and os.path.isfile(os.path.join(ROOT2, "public/tests/test_foo_first.py")), "[5] apply = git mv", lines)
        chk('"key": "test_foo_first.py", "n": 3' in rd("public/tests/arch_baseline/hyg_checks.jsonl")
            and OLD_A not in rd("public/tests/arch_baseline/hyg_checks.jsonl"), "[5] hyg_checks 열쇠 = 새 이름 · 값 그대로", rd("public/tests/arch_baseline/hyg_checks.jsonl"))
        chk("round_named_tests" not in rd("public/tests/arch_baseline/hyg_names.jsonl"), "[5] hyg_names 줄 지움", None)
        tab = json.loads(rd("public/tests/arch_baseline/hyg_rename.json"))["renames"]
        chk(tab == {OLD_A: "test_foo_first.py", OLD_B: "test_foo_second.py"}, "[5] 승계 표 = 옛 → 새 2줄", tab)
        chk(json.loads(rd("tools/refactor/cost_ab_tests.json"))["tests"] == ["test_foo_second.py"], "[5] cost_ab 목록 새 이름", None)
        chk("test_foo_second.py" in rd("public/tests/test_other.py") and "tests/test_foo_first.py" in rd("public/tests/test_foo_first.py")
            and "test_foo_first\n" in rd("public/tests/test_foo_second.py"), "[5] 참조 글자(다른 시험 · 자기 쓰는 법 줄 · …b 의 머리 글)", None)
        chk(rd("dev/old/CHANGES_x.diff").count(OLD_A) == 2, "[5] 이력(dev) 그대로", None)
        rc2, l2 = TR.apply(ROOT2, GOOD)
        d2 = TR.plan(ROOT2, [], GOOD)
        chk(rc2 == 0 and l2 == ["할 일 0(전부 바꿈)"] and d2["ok"] and d2["summary"]["done"] == 2, "[5] 다시 apply = 할 일 0 · 뒤 plan ok", (l2, d2["errors"]))
    shutil.rmtree(ROOT2, ignore_errors=True)
finally:
    shutil.rmtree(ROOTD, ignore_errors=True)
    shutil.rmtree(OUTD, ignore_errors=True)
T.finish()
