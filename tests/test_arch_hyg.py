#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _arch_ratchet as R  # noqa: E402
import _harness as T  # noqa: E402

import ast  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
from collections import Counter  # noqa: E402

import _arch_hyg as H  # noqa: E402
import _arch_hyg_src as HS  # noqa: E402
import _arch_hyg_tools as HT  # noqa: E402
from _arch_hyg_patch import SrcIndex  # noqa: E402

chk = T.chk
t0 = time.time()
S = R.SPECS
D = R._doc

b_max = D({"a.js": {"lines": 700, "bytes": 60000}, "gone.js": {"lines": 900, "bytes": 1}})
c_max = D({"a.js": {"lines": 701, "bytes": 59000}, "new.js": {"lines": 650, "bytes": 1}})
bad, stale = R.compare(S["js_size"], c_max, b_max)
chk(len(bad) == 2 and "lines 700→701" in bad[0] and "new.js: 새 위반" in bad[1], "[R] max: 늘어남·새 위반 = 실패", bad)
chk(any("bytes 60000→59000" in x for x in stale) and any("gone.js" in x for x in stale), "[R] max: 줄어듦·사라짐 = 안내", stale)
tb = R.tighten(S["js_size"], c_max, b_max)
chk(tb["items"] == {"a.js": {"lines": 700, "bytes": 59000}}, "[R] 조이기 = 좋아진 값만(늘어난 lines 그대로 · 새 위반 안 받음 · 사라진 것 뺌)", tb["items"])

b_bag = D({"render": [{"file": "a.js", "lines": 120}]})
moved = D({"render": [{"file": "b.js", "lines": 110, "start": 5}]})
bad, stale = R.compare(S["js_funcs"], moved, b_bag)
chk(not bad and len(stale) == 1, "[R] bag: 다른 파일로 옮긴 같은 이름 함수(짧아짐) = 위반 아님 · 안내만", (bad, stale))
two = D({"render": [{"file": "a.js", "lines": 120, "start": 1}, {"file": "b.js", "lines": 90, "start": 9}]})
bad, _ = R.compare(S["js_funcs"], two, b_bag)
chk(len(bad) == 1 and "b.js:9 render 90줄: 새 위반" in bad[0], "[R] bag: 같은 이름의 둘째 80줄 넘는 함수 = 새 위반(파일:줄 표시)", bad)

b_set = D({"dated": {"tools/a_1010.py": "이름 고정 — 부르는 곳 1: src/x.py"}})
bad, _ = R.compare(S["hyg_tools"], D({"dated": {"tools/a_1010.py": None, "tools/b_1011.sh": None}}), b_set)
chk(len(bad) == 1 and "b_1011" in bad[0], "[R] set: 목록에 새 항목 = 실패", bad)

b_min = D({"t1.py": {"n": 5}, "t2.py": {"n": 3}}, total=8)
bad, stale = R.compare(S["hyg_checks"], D({"t1.py": {"n": 5}, "t3.py": {"n": 4}}, total=9), b_min)
chk(not bad and any("t2.py" in x for x in stale), "[R] min: 지운 시험(t2)의 검사가 다른 시험에 있음(총합 유지) = 통과", (bad, stale))
bad, _ = R.compare(S["hyg_checks"], D({"t1.py": {"n": 4}, "t2.py": {"n": 3}}, total=7), b_min)
chk(len(bad) == 2 and "5→4" in bad[0] and "총합 8→7" in bad[1], "[R] min: 있는 시험의 검사 수 줄어듦 + 총합 줄어듦 = 실패(시험 약화)", bad)
bad, _ = R.compare(S["hyg_checks"], D({"t1.py": {"n": 0}, "t2.py": {"n": 8}}, total=8), b_min)
chk(len(bad) == 1 and "t1.py: 검사 수 5→0" in bad[0], "[R] min: 남아 있는 시험의 검사를 다 지우고(0) 다른 시험에서 총합을 채워도 실패", bad)
tm = R.tighten(S["hyg_checks"], D({"t1.py": {"n": 6}, "t3.py": {"n": 4}}, total=10), b_min)
chk(tm["items"] == {"t1.py": {"n": 6}, "t3.py": {"n": 4}} and tm["total"] == 10, "[R] min 조이기 = 바닥 올림 · 새 시험 바닥 추가 · 지운 시험 뺌", tm)

txt = R.dump(S["js_size"], b_max)
lines = txt.split("\n")
round_trip = R.parse(S["js_size"], txt)["items"] == b_max["items"]
chk(lines[0].startswith('{"_doc": ') and lines[1].startswith('{"key": "a.js"') and txt.endswith("\n") and round_trip,
    "[R] JSON Lines: 첫 줄 설명 · 위반 한 줄씩 정렬 · 왕복 같음", lines[:3])
try:
    R.parse(S["js_size"], txt + "<<<<<<< HEAD\n")
    perr = None
except ValueError as e:
    perr = str(e)
chk(perr is not None and "병합 충돌" in perr, "[R] 깨진 줄(병합 충돌 표식) = 읽기 실패(줄 번호)", perr)
raised = D({"a.js": {"lines": 750, "bytes": 60000}})
chk(R.increases(S["js_size"], raised, b_max) and not R.increases(S["js_size"], tb, b_max),
    "[R] 변조 검사: 기준선 값을 올리면 실패 · 내리기만 하면 통과", R.increases(S["js_size"], raised, b_max))
chk(R.increases(S["hyg_checks"], D({"t1.py": {"n": 2}}, total=8), b_min) and
    R.increases(S["hyg_tests"], D(exempt={"test_lint.py": "정적 분석"}), D()),
    "[R] 변조 검사: 하한 내리기 · 예외(exempt) 추가 = 실패")
dropped = D({"t1.py": {"n": 5}}, total=8)
inc_kept = R.increases(S["hyg_checks"], dropped, b_min, present={"t1.py", "t2.py"})
chk(inc_kept and not R.increases(S["hyg_checks"], dropped, b_min, present={"t1.py"}),
    "[R] 변조 검사: 아직 있는 시험(t2)의 바닥 줄을 지우면 실패 · 지운 시험의 바닥 줄을 지우는 건 통과")

gw, gbad = R.parse_growth('{"_doc": "x"}\n{"spec": "hyg_tests", "key": "t9.py", "f": "patch_attr", "to": 3, "why": "종단 시험", "commit": "c1"}\n')
b_ht = D({"t1.py": {"patch_attr": 1}})
eb, allow = R.grown(S["hyg_tests"], b_ht, gw)
bad_ok = R.compare(S["hyg_tests"], D({"t1.py": {"patch_attr": 1}, "t9.py": {"patch_attr": 3}}), eb)[0]
bad_over = R.compare(S["hyg_tests"], D({"t9.py": {"patch_attr": 4}}), eb)[0]
bad_other = R.compare(S["hyg_tests"], D({"t9.py": {"patch_attr": 2, "patch_call": 1}}), eb)[0]
chk(not gbad and not bad_ok and len(bad_over) == 1 and len(bad_other) == 1 and "patch_call" in bad_other[0] and allow and b_ht["items"] == {"t1.py": {"patch_attr": 1}},
    "[R] 성장 사유 표: 지금 값 ≤ to = 허용(기준선 무변 · 안내) · to 넘음·다른 칸 = 실패", (bad_ok, bad_over, bad_other, allow))
bad_rows = ['{"spec": "hyg_tests", "key": "t9.py", "f": "patch_attr", "to": 3, "why": "", "commit": "c1"}',
            '{"spec": "hyg_checks", "key": "t9.py", "f": "n", "to": 3, "why": "w", "commit": "c1"}',
            '{"spec": "hyg_tests", "key": "t9.py", "f": "nope", "to": 3, "why": "w", "commit": "c1"}',
            '{"spec": "hyg_tests", "key": "t9.py", "f": "patch_attr", "to": true, "why": "w", "commit": "c1"}']
got_rows = [R.parse_growth(x + '\n{"spec": "hyg_tests", "key": "t8.py", "f": "patch_attr", "to": 1, "why": "w", "commit": "c"}') for x in bad_rows]
chk(all(rows == [] and len(bd) == 1 for rows, bd in got_rows), "[R] 성장 사유 표: 빈 사유·하한 지표·모르는 칸·bool 상한 = 틀린 줄 → 표 전체 안 씀", got_rows)

src9 = os.path.join(T.TMP, "src9")
os.makedirs(src9, exist_ok=True)
for fn, body in (("fake_a.py", "from fake_b import helper\nLIMIT = 3\n"), ("fake_b.py", "def helper():\n    return 1\n")):
    with open(os.path.join(src9, fn), "w", encoding="utf-8") as f:
        f.write(body)
SAMPLE = '''
import os
import re
import _harness as T
import fake_a
import fake_b
def late_helper():
    return "late" in LATE_SRC


LATE_SRC = T.core_src()
src = T.web_src()
app = open(os.path.join(T.ROOT, "web", "v2", "app.js")).read()
out = open(os.path.join(T.TMP, "out.txt")).read()
T.chk("def foo" in src, "S1 원문 검사")
T.chk("bar(" not in app, "S2 부정 검사(bb612)")
T.chk("ok" in out, "S3 출력 파일 검사는 셈 밖")
body = src[src.index("def foo"):]
T.chk(re.search(r"x\\\\d", body) is not None, "S4 정규식(fix1012 판)")
src = "다시 대입"
T.chk("다시" in src, "S5 다시 대입하면 원문 아님")
fake_a.helper = lambda: 2
fake_b.helper = lambda: 3
fake_a.LIMIT = 9
T.patch_moved("helper", fake_b.helper)
setattr(fake_a, "helper", None)


def check(name, cond):
    T.chk(cond, name)


check("S6 감싸개 이름 s22", True)
assert 1 + 1 == 2
'''
a0 = H.analyze_test(SAMPLE, "test_sample.py", SrcIndex(src9))
got0 = {k: a0[k] for k in ("str_checks", "str_neg", "patch_attr", "patch_call", "patch_foreign", "round_labels", "checks", "labels")}
want0 = {"str_checks": 5, "str_neg": 1, "patch_attr": 3, "patch_call": 2, "patch_foreign": 2, "round_labels": 3, "checks": 8, "labels": 6}
chk(got0 == want0, "[0] 합성 시험: 소스 검사 5(부정 1 · 아래에서 대입한 원문을 읽는 위 도우미 포함 · 출력 파일·다시 대입은 셈 밖) · "
    "속성 대입 3 · 도구 패치 2 · 정의 모듈 밖 2 · "
    "회차 라벨 3 · 검사 수 8(chk 6 + 감싸개 1 + assert 1) · 정적 라벨 6(감싸개 안 chk(cond, name) 은 변수라 못 봄)", (got0, a0["foreign"]))
chk([f for _ln, f in a0["foreign"]] == ["fake_a.helper→fake_b", "fake_a.helper→fake_b"], "[0] 정의 모듈 밖 = 'mod.name→정의모듈'(정의 모듈 패치·상수는 셈 밖)",
    a0["foreign"])
a1 = H.analyze_test('from _ingest import check\nimport _gate as G\ncheck("R1 회차 bb612", True)\nG.check("R2 동작", 1 == 1)\n',
                    "test_helper.py", None, {"_ingest": {"check": (0, "name")}, "_gate": {"check": (0, "name")}})
chk((a1["checks"], a1["labels"], a1["round_labels"]) == (2, 2, 1), "[0] 공용 도우미 감싸개(from _ingest import check · G.check) = 검사·라벨로 셈",
    (a1["checks"], a1["labels"], a1["round_labels"]))
a3 = H.analyze_test('import _gate as G\nimport ledger_restore as LR\ndef check(value):\n    return value\n'
                    'def restorable(path):\n    return bool(LR.check(path))\nG.check("R3 동작", restorable("p"))\nobj.check("x")\n',
                    "test_helper2.py", None, {"_gate": {"check": (0, "name")}})
chk((a3["checks"], a3["labels"]) == (1, 1), "[0] 도우미 감싸개는 부르는 꼴 전체 이름으로(G.check = 셈 · 같은 이름 지역 def 가 가리지 않음 · "
    "obj.check·LR.check = 안 셈 → 그걸 부르는 함수도 감싸개 아님)", (a3["checks"], a3["labels"]))
a2 = H.analyze_test('import _harness as T\ntry:\n    s = T.web_src()\nexcept OSError:\n    s = ""\nfor _ in range(2):\n    s = "아님"\n'
                    'T.chk("x" not in s, "S1")\n', "test_try.py")
chk((a2["str_checks"], a2["str_neg"]) == (1, 1), "[0] try/except·반복문 뒤 = 가지 합치기(예외 대체값·0번 도는 반복이 원문 표시를 지우지 않음)",
    (a2["str_checks"], a2["str_neg"]))
a4 = H.analyze_test('import _harness as T\ns = ""\ntry:\n    s = T.web_src()\n    may_raise()\n    s = ""\nexcept ValueError:\n'
                    '    T.chk("removed" not in s, "S1")\n', "test_try2.py")
chk((a4["str_checks"], a4["str_neg"]) == (1, 1), "[0] except 입구 = try 몸통 안 모든 문장 뒤 상태 합(중간에 예외가 나면 원문)", (a4["str_checks"], a4["str_neg"]))
sc9 = lambda s: HS.source_checks(ast.parse("import _harness as T\nimport re\n" + s))[0]  # noqa: E731
edge = {"반복 뒷바퀴": 'src = ""\nfor i in range(2):\n    if i:\n        T.chk("x" not in src, "a")\n    src = T.web_src()\n',
        "튜플 대입 순서": 'src = T.web_src()\nsrc, body = "", src\nT.chk("x" not in body, "a")\n',
        "정규식 키워드 인자": 'src = T.web_src()\nT.chk(re.search(pattern="r", string=src) is None, "a")\n',
        "break 뒤 else": 's = T.web_src()\nfor _ in range(1):\n    break\nelse:\n    s = ""\nT.chk("x" not in s, "g")\n',
        "finally 중간 상태": 's = ""\ntry:\n    s = T.web_src()\n    may_raise()\n    s = ""\nfinally:\n    T.chk("x" not in s, "g")\n'}
edge.update({"while 조건 뒷바퀴": 's = ""\nwhile "x" not in s:\n    s = T.web_src()\n',
             "긴 대입 사슬": 'a = b = c = d = e = f = ""\nfor _ in range(9):\n    T.chk("x" in a, "q")\n    a = b\n    b = c\n    c = d\n'
                         '    d = e\n    e = f\n    f = T.web_src()\n',
             "하네스 읽기 도우미": 'def raw():\n    return T.web_src()\ns = raw()\nT.chk("x" not in s, "a")\n'})
got9 = {k: len(sc9(v)) for k, v in edge.items()}
chk(all(v == 1 for v in got9.values()), "[0] 오염 추적 가장자리(반복·while 조건 뒷바퀴·긴 사슬·튜플 대입 순서·키워드 인자·break/else·finally·"
    "하네스 읽기 도우미) = 원문 검사로 셈", got9)
fin_out = sc9('try:\n    s = T.web_src()\nfinally:\n    s = "ok"\nT.chk("ok" in s, "r")\n')
chk(fin_out == [], "[0] finally 에서 다시 대입한 값 = 원문 아님(출력 검사는 셈 밖)", fin_out)
hp = {"_gate": {"check": (0, "name")}, "_ingest": {"check": (0, "name")}}
scope = {"클래스 메서드 같은 이름": ('from _ingest import check\nclass D:\n    def check(self, v):\n        return v\ncheck("동작", True)\n', 1),
         "안쪽 def 같은 이름": ('from _ingest import check\ndef h():\n    def check(v):\n        return v\n'
                             '    return check(1)\ncheck("동작", True)\n', 1),
         "인자로 가린 별칭": ('import _gate as G\ndef probe(G):\n    G.check("검사", False)\n', 0),
         "컴프리헨션 변수는 안 가림": ('from _ingest import check\ndef run(cs):\n    xs = [check for check in cs]\n    check("동작", True)\n', 1),
         "모듈 별칭 다시 대입": ('import _gate as G\nG = make()\nG.check("x", True)\n', 0)}
got10 = {k: H.analyze_test(v[0], "t.py", None, hp)["checks"] for k, v in scope.items()}
chk(got10 == {k: v[1] for k, v in scope.items()}, "[0] 도우미 이름 해석은 범위대로(메서드·안쪽 def 는 모듈 이름을 안 가림 · 함수 인자로 가린 별칭은 안 셈)", got10)
rm = H.round_markers("코덱스 bb612 · fix1010 · 10-09 · s24a · 16차 · pg19 — 안 셈: sha256 · erc20 · 1차 · S8 · P1b · b1 · 2026 · 1,000")
chk(rm == ["코덱스", "bb612", "1010", "10-09", "s24a", "16차", "pg19"], "[0] 회차 표식 = 날짜·리뷰 번호·세션·수정 회차·리뷰 낱말(절 번호·기술 낱말·숫자 뺌)", rm)
names = {n: H.round_named(n) for n in ("test_exbal1012.py", "test_s22_perm.py", "test_exf_x12.py", "test_p2b_silent.py",
                                        "test_btc_bt939.py", "test_s23rev1012.py", "test_fix_1017.py", "test_tier1h.py",
                                        "test_upbit_fill_dq0.py", "test_health_pm2less.py", "test_base64_codec.py")}
chk([k for k, v in names.items() if v] == list(names)[:7], "[0] 회차 이름 파일 = 날짜(1017 단독 포함)·세션·리뷰 번호 낱말(tier1h·dq0·pm2less·base64 는 동작 이름)",
    names)
tables = HT.ledger_tables(T.ROOT)
cases = {'c.execute("DELETE FROM postings WHERE x=?")': True, 'c.execute(f"UPDATE {t} SET a=1")': True,
         'print("INSERT INTO notes VALUES (1)")': False, 'c = core.Core(cfg)\nc.conn.commit()': True,
         'c.execute("SELECT 1 FROM postings")': False}
got1 = {k: HT.writes_ledger(k, tables) for k in cases}
chk(got1 == cases, "[0] 원장 쓰는 도구 = 원장 표·{표} 자리 SQL 쓰기 또는 Core()+commit(원장 밖 표·SELECT 는 아님)", got1)
dated = {n: bool(HT.DATED.search(n)) for n in ("deploy_hotfix_20260928t.sh", "negabs_1010.py", "rebuild2.py", "post_checks_r6.sh")}
chk(dated == {"deploy_hotfix_20260928t.sh": True, "negabs_1010.py": True, "rebuild2.py": False, "post_checks_r6.sh": False},
    "[0] 날짜 붙은 도구 = 20YYMMDD·MMDD(숫자 낱말 r6·rebuild2 는 아님)", dated)

layout = R.repo_layout()
old_tests = R.load("hyg_tests") if layout else None
cur, extra = R.current_hyg(T.ROOT, T.HERE, T.README, old_tests["exempt"] if old_tests else None)
if not layout:
    print("[1] 공개판 배치 — 래칫 건너뜀")
else:
    R.check(T, T.ROOT, cur)

th = extra["tests"]
tot = Counter()
for r in th.values():
    for k in ("str_checks", "str_neg", "patch_attr", "patch_call", "patch_foreign", "round_labels", "checks", "labels"):
        tot[k] += r[k]
rn = sorted(cur["hyg_names"]["items"]["round_named_tests"])
print(f"[2] 합계: 소스 문자열 검사 {tot['str_checks']}(부정 {tot['str_neg']}) · 몽키패치 속성 대입 {tot['patch_attr']} + 도구 패치 {tot['patch_call']}"
      f"(정의 모듈 밖 {tot['patch_foreign']}) · 회차 라벨 {tot['round_labels']}/{tot['labels']} · 회차 이름 파일 {len(rn)} · "
      f"검사 수(test_*.py) {cur['hyg_checks']['total']}")
tg = Counter(f for r in th.values() for _ln, f in r.get("foreign", []))
print(f"[2] 정의 모듈 밖 패치 표적 {len(tg)}개: " + " · ".join(f"{k} {v}" for k, v in tg.most_common(8)))
print("[2] README 를 읽는 시험(README 를 docs/ 로 옮길 때 이 문서 계약을 지킬 것): " + ", ".join(sorted(fn for fn, r in th.items() if r["reads_readme"])))
sz = extra["sizes"]
print(f"[2] 문서: README {sz['readme']:,}바이트 · docs .md {sz['docs_md']:,}(CODEMAP 뺌) · docs 그 밖(스크린숏) {sz['docs_img']:,} · "
      f"원장 쓰는 도구 {len(extra['tools']['ledger_writers'])} · 날짜 붙은 도구 {len(extra['tools']['dated'])}")
base_tools = R.load("hyg_tools") if layout else None
if base_tools:
    pinned = sorted({k for s9 in base_tools["items"].values() for k, w in s9.items() if w})
    print(f"[2] 이름 고정 도구 {len(pinned)}개(기준선 why): " + ", ".join(pinned))
print(f"[2] {time.time() - t0:.1f}초")
T.finish()
