#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402

import _arch_hyg_rename as RN  # noqa: E402
import _arch_ratchet as R  # noqa: E402

TESTS = R.SPECS["hyg_tests"]
CHECKS = R.SPECS["hyg_checks"]
TABLE = {"test_old_a.py": "test_new_a.py"}


def tdoc(items, total=None):
    return R._doc({k: dict(v) for k, v in items.items()}, total)


def judge(spec, cur, base, table=TABLE):
    return R.compare(spec, cur, RN.renamed(spec, base, set(cur["items"]), table))


print("[1] 상한(hyg_tests)")
base = tdoc({"test_old_a.py": {"patch_attr": 16, "round_labels": 2}, "test_keep.py": {"patch_attr": 1}})
cur_same = tdoc({"test_new_a.py": {"patch_attr": 16, "round_labels": 2}, "test_keep.py": {"patch_attr": 1}})
bad, stale = judge(TESTS, cur_same, base)
T.chk(not bad, "이름만 바꿈(값 같음) = 새 위반 0", bad)
cur_less = tdoc({"test_new_a.py": {"patch_attr": 3}, "test_keep.py": {"patch_attr": 1}})
bad, stale = judge(TESTS, cur_less, base)
T.chk(not bad and any("test_new_a.py" in x for x in stale), "새 이름 값이 줄어듦 = 통과 + 조이기 안내", (bad, stale))
cur_more = tdoc({"test_new_a.py": {"patch_attr": 17, "round_labels": 2}, "test_keep.py": {"patch_attr": 1}})
bad, _s = judge(TESTS, cur_more, base)
T.chk(any("test_new_a.py" in x and "늘어남" in x for x in bad), "새 이름 값이 옛 상한보다 큼 = 실패", bad)
cur_both = tdoc({"test_old_a.py": {"patch_attr": 16, "round_labels": 2}, "test_new_a.py": {"patch_attr": 1}, "test_keep.py": {"patch_attr": 1}})
bad, _s = judge(TESTS, cur_both, base)
T.chk(any("test_new_a.py" in x and "새 위반" in x for x in bad), "옛 파일이 남아 있음 = 승계 없음(새 이름 = 새 위반)", bad)
cur_other = tdoc({"test_new_b.py": {"patch_attr": 16}, "test_keep.py": {"patch_attr": 1}})
bad, _s = judge(TESTS, cur_other, base)
T.chk(any("test_new_b.py" in x for x in bad), "표에 없는 새 이름 = 새 위반(표 밖 승계 0)", bad)
work = tdoc({"test_new_a.py": {"patch_attr": 16, "round_labels": 2}, "test_keep.py": {"patch_attr": 1}})
ref_ok = R.increases(TESTS, work, RN.renamed(TESTS, base, set(work["items"]), TABLE), set(cur_same["items"]))
T.chk(ref_ok == [], "변조 검사: 작업 기준선 새 열쇠 = 기준 커밋 옛 열쇠 값 → 통과", ref_ok)
work_up = tdoc({"test_new_a.py": {"patch_attr": 20, "round_labels": 2}, "test_keep.py": {"patch_attr": 1}})
ref_bad = R.increases(TESTS, work_up, RN.renamed(TESTS, base, set(work_up["items"]), TABLE), set(cur_same["items"]))
T.chk(any("test_new_a.py" in x for x in ref_bad), "변조 검사: 새 열쇠 상한을 옛 값보다 올림 = 실패", ref_bad)
work_dup = tdoc({"test_old_a.py": {"patch_attr": 16, "round_labels": 2}, "test_new_a.py": {"patch_attr": 16},
                 "test_keep.py": {"patch_attr": 1}})
ref_dup = R.increases(TESTS, work_dup, RN.renamed(TESTS, base, set(work_dup["items"]), TABLE), set(cur_same["items"]))
T.chk(any("test_new_a.py" in x for x in ref_dup), "변조 검사: 옛 열쇠를 남긴 채 새 열쇠를 더함 = 실패(값 복제 금지)", ref_dup)
low = R.tighten(TESTS, cur_less, RN.renamed(TESTS, base, set(cur_less["items"]), TABLE))
T.chk(low["items"].get("test_new_a.py") == {f: (3 if f == "patch_attr" else 0) for f in TESTS.fields} and "test_old_a.py" not in low["items"],
      "조이기(--update-lower 꼴): 옛 열쇠 지움 · 새 열쇠 = min(옛 상한, 지금 값)", low["items"])

print("[2] 바닥(hyg_checks)")
cbase = tdoc({"test_old_a.py": {"n": 12}, "test_keep.py": {"n": 5}}, total=17)
bad, _s = judge(CHECKS, tdoc({"test_new_a.py": {"n": 12}, "test_keep.py": {"n": 5}}, total=17), cbase)
T.chk(not bad, "검사 수 같은 이름 바꿈 = 통과", bad)
bad, _s = judge(CHECKS, tdoc({"test_new_a.py": {"n": 11}, "test_keep.py": {"n": 6}}, total=17), cbase)
T.chk(any("test_new_a.py" in x and "줄어듦" in x for x in bad), "새 이름 검사 수 < 옛 바닥 = 실패(총합이 같아도)", bad)

cur_c = tdoc({"test_new_a.py": {"n": 11}, "test_keep.py": {"n": 6}}, total=17)
work_c = tdoc({"test_keep.py": {"n": 5}}, total=17)
def ref_judge(spec, work, ref, cur):
    return R.increases(spec, work, RN.renamed(spec, ref, set(work["items"]) | set(cur["items"]), TABLE, set(cur["items"])), set(cur["items"]))


inc = ref_judge(CHECKS, work_c, cbase, cur_c)
T.chk(any("test_new_a.py" in x for x in inc), "변조 검사: 작업 기준선에서 새 이름 바닥 줄을 지움(지금 값엔 있음) = 실패(옛 바닥이 따라옴)", inc)
work_s = tdoc({"test_old_a.py": {"n": 12}, "test_new_a.py": {"n": 11}, "test_keep.py": {"n": 6}}, total=17)
inc = ref_judge(CHECKS, work_s, cbase, cur_c)
T.chk(any("test_new_a.py" in x and "줄어듦" in x for x in inc), "변조 검사: 작업 기준선에 옛 이름 줄을 남기고 새 이름 바닥을 낮춤 = 실패(옛 파일 없음 → 옛 바닥이 새 이름으로)", inc)
T.chk(ref_judge(CHECKS, tdoc({"test_new_a.py": {"n": 12}, "test_keep.py": {"n": 5}}, total=17), cbase,
                tdoc({"test_new_a.py": {"n": 12}, "test_keep.py": {"n": 5}}, total=17)) == [], "변조 검사: 바르게 바꾼 작업 기준선 = 통과", None)

print("[3] 표 오류 · 다른 지표")
for name, table in (("사슬", {"test_a.py": "test_b.py", "test_b.py": "test_c.py"}),
                    ("새 이름 겹침", {"test_a.py": "test_c.py", "test_b.py": "test_c.py"}),
                    ("같은 이름", {"test_a.py": "test_a.py"}), ("꼴 아님", {"test_a.py": "helper_a.py"})):
    err = RN._rename_errors(table)
    T.chk(bool(err), f"표 오류({name}) = 오류 줄", err)
T.chk(RN._rename_errors(TABLE) == [] and RN._rename_errors([]) != [], "정상 표 = 오류 0 · dict 아님 = 오류", RN._rename_errors([]))
REF_FILES = {"test_old_a.py", "test_keep.py"}
T.chk(RN.rename_ref_errors(TABLE, {}, REF_FILES) == [] and RN.rename_ref_errors(dict(TABLE, **{"test_b.py": "test_c.py"}), TABLE, REF_FILES) == [],
      "기준 커밋 대조: 이름 바꾸기 · 줄 더함 = 오류 0", None)
e = RN.rename_ref_errors({}, TABLE, REF_FILES)
T.chk(any("지우거나" in x for x in e), "기준 커밋 대조: 기준 커밋 표 줄을 지움 = 오류", e)
e = RN.rename_ref_errors({"test_old_a.py": "test_other.py"}, TABLE, REF_FILES)
T.chk(any("바꿈" in x for x in e), "기준 커밋 대조: 기준 커밋 표 줄의 새 이름을 바꿈 = 오류", e)
e = RN.rename_ref_errors({"test_old_a.py": "test_keep.py"}, {}, REF_FILES)
T.chk(any("이미 있는 파일" in x for x in e), "기준 커밋 대조: 새 이름이 기준 커밋에 있던 다른 파일 = 오류(상한 빌리기 금지)", e)
REF = R.Ref("0" * 40, os.devnull, "합성 기준", False)


def fake_git(ls=None, lsr="", show=""):
    def g(_top, *args):
        if args[0] == "show":
            return show
        return lsr if args[-1].endswith(RN.RENAME_FILE) else ls
    return g


T.chk(R.rename_ref_check(REF, fake_git(ls=None)) != [], "기준 커밋 대조: 파일 목록 git 실패 = 오류(빈 목록으로 통과 안 함)", None)
T.chk(R.rename_ref_check(REF, fake_git(ls="public/tests/test_keep.py", lsr=None)) != [], "기준 커밋 대조: 표 조회 git 실패 = 오류", None)
T.chk(R.rename_ref_check(REF, fake_git(ls="public/tests/test_keep.py", lsr="x", show=None)) != [], "기준 커밋 대조: 표 읽기 git 실패 = 오류", None)
T.chk(R.rename_ref_check(REF, fake_git(ls="public/tests/test_keep.py", lsr="x", show='{"renames": []}')) != [],
      "기준 커밋 대조: 기준 커밋 표 꼴 틀림 = 오류", None)
T.chk(R.rename_ref_check(REF, fake_git(ls="", lsr="")) != [], "기준 커밋 대조: 파일 목록 빔 = 오류", None)
esc = R.SPECS["js_esc"]
ebase = R._doc({"test_old_a.py": {"n": 1}})
T.chk(RN.renamed(esc, ebase, {"test_new_a.py"}, TABLE) is ebase, "그 밖 지표(js_esc)는 승계 안 함", esc.name)

print("[4] 저장소 표")
if R.repo_layout():
    tab = RN.renames()
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    T.chk(all(not os.path.exists(os.path.join(tests_dir, o)) for o in tab), "표 옛 이름 = 지금 없는 파일", sorted(tab))
    T.chk(all(os.path.isfile(os.path.join(tests_dir, n)) for n in tab.values()), "표 새 이름 = 있는 파일", sorted(tab.values()))
    path = os.path.join(RN.BASE_DIR, RN.RENAME_FILE)
    raw = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
    T.chk(not raw or isinstance(json.loads(raw).get("renames"), dict), "표 파일 꼴 = {'renames': {옛: 새}}", raw[:80])
else:
    print("  (공개판 배치 — 기준선 없음 · 건너뜀)")

T.finish()
