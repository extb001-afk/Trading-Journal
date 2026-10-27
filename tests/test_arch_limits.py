#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402

import _arch_py_defs as D  # noqa: E402
import _arch_py_ratchet as R  # noqa: E402

chk = T.chk


def doc_of(rows):
    return json.dumps({"_doc": "x", "why": R.LIMITS_WHY, "limits": rows}, ensure_ascii=False)


GOOD = [{"k": "func.lines", "m": "tkj", "q": "A.f", "to": 120, "at": "2026-10"},
        {"k": "file.bytes", "m": "tkj", "q": "<file>", "to": 70000, "at": "2026-10"}]
rows, bad = R.parse_limits(doc_of(GOOD))
chk(rows == GOOD and not bad, "[1] 맞는 꼴 = 줄 그대로", bad)
BADS = [dict(GOOD[0], k="nope"), dict(GOOD[0], k="ledger.write"), dict(GOOD[0], to=-1), dict(GOOD[0], to=True),
        dict(GOOD[0], to=1.5), dict(GOOD[0], at="2026-13"), dict(GOOD[0], at="10-2026"), dict(GOOD[0], m=""),
        dict(GOOD[0], why="손으로 적은 사유 칸은 모르는 칸")]
got = [R.parse_limits(doc_of(GOOD + [b])) for b in BADS]
chk(all(r == [] and len(b) == 1 for r, b in got), "[1] 틀린 줄 하나 = 표 전체 안 씀 + 틀린 곳 1(%d가지)" % len(BADS),
    [b for _r, b in got])
r2, b2 = R.parse_limits(doc_of(GOOD + [dict(GOOD[0], to=99)]))
chk(r2 == [] and any("겹침" in x for x in b2), "[1] 같은 (k, m, q) 두 줄 = 겹침", b2)
for text in ("[]", '{"limits": {}}', "{", '{"limits": [NaN]}'):
    r3, b3 = R.parse_limits(text)
    chk(r3 == [] and b3, "[1] 표 모양 아님 %r = 안 씀" % text[:20], b3)

BASE = [{"k": "func.lines", "m": "tkj", "q": "A.f", "f": "A.f", "h": "aaaaaaaaaaaa", "v": 100}]
RULES = {"limits": {"func.lines": 80}}


def unit(v):
    return {"k": "func.lines", "m": "tkj", "q": "A.f", "f": "A.f", "h": "bbbbbbbbbbbb", "v": v, "t": "f", "at": "src/tkj.py:1"}


allow = R.limit_rows(GOOD)
vd = R.compare("func.lines", [unit(120)], BASE, RULES, allow)
chk(vd.ok and len(vd.grown) == 1 and vd.grown[0][1]["v"] == 100 and "기준선 동결" in vd.grown[0][2]["why"],
    "[2] 지금 120 ≤ 상한 120 = 허용(기준선 100 그대로 · 허용 줄 사유 = 'YYYY-MM 기준선 동결')")
vd = R.compare("func.lines", [unit(121)], BASE, RULES, allow)
chk(not vd.ok and len(vd.grew) == 1, "[2] 지금 121 > 상한 120 = 커짐 실패")
vd = R.compare("func.lines", [unit(121)], BASE, RULES, allow + [{"k": "func.lines", "m": "tkj", "q": "A.f", "to": 125,
                                                                   "why": "합성 성장 사유 — 도우미 추가로 늘어남", "commit": "t"}])
chk(vd.ok and vd.grown, "[2] 상한 표보다 크지만 성장 사유 줄이 허용 = 통과(둘을 같이 봄)")
chk(all(R.why_ok(g["why"]) for g in R.limit_rows(GOOD)), "[2] 상한 표 줄을 바꾼 성장 줄 꼴도 why 규칙 통과")

grown = {("func.lines", "tkj", "A.f"): 110, ("class.lines", "tkj", "A"): 450}
f1 = R.fold_limits(grown, [], "2026-10")
f2 = R.fold_limits(grown, f1, "2026-11")
chk(f1 == f2 and [e["to"] for e in f1] == [450, 110] and all(e["at"] == "2026-10" for e in f2),
    "[3] to = 지금 값 · 정렬 · 다음 달에 다시 접어도 같음(옛 at 유지)")
f3 = R.fold_limits({**grown, ("func.lines", "tkj", "A.f"): 115}, f1, "2026-11")
chk([(e["to"], e["at"]) for e in f3] == [(450, "2026-10"), (115, "2026-11")], "[3] 성장 줄로 올라간 단위 = 새 at")
f4 = R.fold_limits({("class.lines", "tkj", "A"): 440}, f1, "2026-11")
chk([(e["k"], e["to"], e["at"]) for e in f4] == [("class.lines", 440, "2026-10")], "[3] 허용이 필요 없는 단위 빠짐 · 줄어든 값 = 옛 at")

low = R.lower_limits({("func.lines", "tkj", "A.f"): 105, ("class.lines", "tkj", "A"): 460}, f1)
chk([e["to"] for e in low] == [450, 105], "[4] 줄어든 값만 내림(105) · 성장 줄로 더 커진 단위(460)는 표 값 450 그대로")
chk(R.lower_limits({}, f1) == [], "[4] 더는 기준선보다 안 큰 단위 = 빠짐")
chk(R.lower_limits({("class.lines", "tkj", "A"): 440}, f1, {"func.lines"}) == [dict(f1[0], to=440), f1[1]],
    "[4] 실패 중인 지표(상한 넘어 커짐)의 줄 = 그대로(지우지 않음 — 되돌리면 다시 통과)")

P5 = os.path.join(T.TMP, "lim5.json")
R.dump_limits(P5, list(reversed(f1)), "doc")
with open(P5, encoding="utf-8") as f:
    a5 = f.read()
R.dump_limits(P5, R.parse_limits(a5)[0], "doc")
with open(P5, encoding="utf-8") as f:
    b5 = f.read()
chk(a5 == b5 and R.parse_limits(a5) == (f1, []) and a5.count("\n") == len(f1) + 4, "[5] 줄 하나에 단위 하나 · 두 번 써도 바이트 같음")
R.dump_limits(P5, [], "doc")
with open(P5, encoding="utf-8") as f:
    chk(R.parse_limits(f.read()) == ([], []), "[5] 빈 표 = 읽힘(줄 0 · 틀린 곳 0)")

try:
    import _arch_py_checks as PC  # noqa: E402
except SystemExit:
    PC = None
if PC is None:
    chk(True, "[6] 무결성 모듈을 못 실음 — 건너뜀")
else:
    g_row = json.dumps({"k": "func.lines", "m": "tkj", "q": "A.f", "to": 112, "why": "합성 성장 사유 — 단계 함수 추출로 늘어남", "commit": "t"},
                       ensure_ascii=False)
    old6 = doc_of(f1[:1])
    cur6 = doc_of(f1)
    bad6, rev6 = PC.loosened_limits(cur6, old6, [None, "", g_row])
    chk(not bad6 and len(rev6) == 1, "[6] 새 줄 = 성장 줄(to 112 ≥ 110)이 받침 → 검수 줄 · 실패 0", (bad6, rev6))
    bad6, rev6 = PC.loosened_limits(cur6, old6, [None, ""])
    chk(len(bad6) == 1 and not rev6, "[6] 받치는 성장 줄 없는 새 줄 = 실패", bad6)
    bad6, _r = PC.loosened_limits(doc_of([dict(f1[1], to=113)]), None, [g_row])
    chk(len(bad6) == 1, "[6] 성장 줄 허용(112)보다 큰 상한(113) = 실패", bad6)
    bad6, rev6 = PC.loosened_limits(doc_of([dict(f1[0], to=451)]), old6, [g_row])
    chk(len(bad6) == 1, "[6] 기준보다 올린 상한(450 → 451 · 받침 없음) = 실패", bad6)
    bad6, rev6 = PC.loosened_limits(doc_of([dict(f1[0], to=400)]), cur6, [])
    chk(not bad6 and not rev6, "[6] 내림·지움 = 괜찮음(검수 줄도 없음)")
    bad6, _r = PC.loosened_limits('{"limits": 1}', old6, [])
    chk(bad6, "[6] 표 모양 틀림 = 실패", bad6)
    for raw in ('{"k": "func.lines", "m": "tkj", "q": "A.f", "to": 120}',
                '{"k": "func.lines", "m": "tkj", "q": "A.f", "to": 120, "why": "허용 허용 허용 허용 허용 허용 허용 허용", "commit": "t"}'):
        bad6, _r = PC.loosened_limits(cur6, old6, [raw])
        chk(len(bad6) == 1, "[6] 받침 줄이 성장 사유 꼴이 아님(why 없음·빈말) = 받침 아님 → 실패(사유 없는 성장 세탁 막음)", bad6)
    bad6, rev6 = PC.loosened_limits(cur6, old6, [], public=True)
    chk(not bad6 and len(rev6) == 1 and "공개판" in rev6[0], "[6] 공개판 배치 = 받침 없는 새 줄도 검수 줄로만(공개 이력엔 접힌 성장 줄 커밋이 없음)", rev6)

SRC7 = '''"""모듈 독스트링."""
import os


def f(a):
    def g():
        """안쪽 함수 독스트링."""
        return 1
    """안쪽 함수 뒤 문자열 — 공개 빌드가 지움."""
    return g()


class C:
    """클래스 독스트링."""
    x = 1
    """클래스 몸통 중간 문자열."""

    def m(self):
        if os.sep:
            "if 안 문자열"
        return 2


"""모듈 중간 문자열."""
'''
import ast  # noqa: E402
chk(D.bare_strings(ast.parse(SRC7)) == [9, 16, 20, 24], "[7] 독스트링 자리 밖 문자열 단독 문장 = 9·16·20·24 줄", D.bare_strings(ast.parse(SRC7)))
chk(D.bare_strings(ast.parse('"""d."""\n\n\ndef f():\n    """d."""\n    return 1\n')) == [], "[7] 독스트링 자리만 = 0")
chk("doc.misplaced" in R.HARD and R.HARD["doc.misplaced"][0] == "contracts", "[7] 굳은 검사 doc.misplaced = contracts 묶음")

DOC_ROOT = os.path.realpath(os.path.join(T.HERE, ".."))
PUBLIC = DOC_ROOT == os.path.realpath(T.ROOT)
LIM = os.path.join(T.HERE, "arch_baseline", R.LIMITS_FILE)
if not os.path.isfile(os.path.join(T.HERE, "arch_baseline", "py_rules.json")) or not os.path.isfile(LIM):
    chk(True, "[8] 규칙 파일·현재 상한 표 없음 — 건너뜀")
    T.finish()
R8 = os.path.join(T.TMP, "r8")
TESTS8 = os.path.join(R8, "tests") if PUBLIC else os.path.join(R8, "public", "tests")
shutil.copytree(T.SRC, os.path.join(R8, "src"), ignore=shutil.ignore_patterns("__pycache__"))
shutil.copytree(T.HERE, TESTS8, ignore=shutil.ignore_patterns("__pycache__", "cassettes", "test_*.py"))
shutil.copy(os.path.join(T.HERE, "test_arch_size.py"), TESTS8)
DOCS8 = os.path.dirname(TESTS8)
for rel in ("README.md", ".env.example"):
    if os.path.isfile(os.path.join(DOC_ROOT, rel)):
        shutil.copy(os.path.join(DOC_ROOT, rel), os.path.join(DOCS8, rel))
if os.path.isdir(os.path.join(DOC_ROOT, "docs")):
    shutil.copytree(os.path.join(DOC_ROOT, "docs"), os.path.join(DOCS8, "docs"), ignore=shutil.ignore_patterns("screenshots", "*.png"))
B8 = os.path.join(TESTS8, "arch_baseline")
ENV = {k: v for k, v in os.environ.items() if not k.startswith(("TJ_", "GIT_"))}


def cli(*a):
    p = subprocess.run([sys.executable, os.path.join(TESTS8, "_arch.py")] + list(a), capture_output=True, text=True,
                       encoding="utf-8", env=ENV, timeout=600, cwd=R8)
    return p.returncode, p.stdout + p.stderr


def read8(name):
    with open(os.path.join(B8, name), encoding="utf-8") as f:
        return f.read()


def write8(name, text):
    with open(os.path.join(B8, name), "w", encoding="utf-8") as f:
        f.write(text)


with open(LIM, encoding="utf-8") as f:
    lim0 = R.parse_limits(f.read())[0]
grow0 = read8(R.GROWTH_FILE)
unfold = [json.dumps({"k": e["k"], "m": e["m"], "q": e["q"], "to": e["to"], "why": "합성 성장 사유 — 접은 표를 되돌린 줄(시험)",
                      "commit": "t"}, ensure_ascii=False) for e in lim0]
write8(R.GROWTH_FILE, grow0 + "".join(x + "\n" for x in unfold))
os.remove(os.path.join(B8, R.LIMITS_FILE))
rc1, out1 = cli("--fold-growth")
a8 = read8(R.LIMITS_FILE)
rc2, out2 = cli("--fold-growth")
b8 = read8(R.LIMITS_FILE)
refold = {(e["k"], e["m"], e["q"]): e["to"] for e in R.parse_limits(a8)[0]}
have = {(e["k"], e["m"], e["q"]): e["to"] for e in lim0}
extra = sorted("%s %s %s %s" % (k + (v,)) for k, v in refold.items() if k not in have or v > have[k]) if not grow0.strip() else []
chk(rc1 == 0 and rc2 == 0, "[8] --fold-growth 두 번 rc 0", (out1[-400:], out2[-400:]))
chk(not extra, "[8] 상한 표 → 성장 줄로 되돌린 뒤 접기 ⊆ 지금 표(새 단위·큰 to 0 · 다시 접은 %d줄 · 지금 %d줄)%s" % (
    len(refold), len(have), "" if not grow0.strip() else " — 지금 성장 사유 표에 줄이 있어 비교 건너뜀"), extra[:10])
chk(a8 == b8, "[8] 다시 접어도 바이트 같음(멱등)")
chk(read8(R.GROWTH_FILE) == "", "[8] 접은 뒤 성장 사유 표 = 빔")
p8 = subprocess.run([sys.executable, os.path.join(TESTS8, "test_arch_size.py")], capture_output=True, text=True, encoding="utf-8",
                    env=ENV, timeout=600, cwd=R8)
chk(p8.returncode == 0, "[8] 접은 뒤 크기 래칫(test_arch_size) 통과", p8.stdout[-600:])
big = next((e for e in R.parse_limits(a8)[0] if e["k"] in ("func.lines", "file.lines", "file.bytes", "class.lines")), None)
if big is None:
    chk(True, "[8] 접은 표에 크기 줄 없음 — 실패 중 거부 시험 건너뜀")
else:
    write8(R.LIMITS_FILE, a8.replace(json.dumps(big, ensure_ascii=False, separators=(",", ":")),
                                     json.dumps(dict(big, to=big["to"] - 1), ensure_ascii=False, separators=(",", ":"))))
    c8 = read8(R.LIMITS_FILE)
    rc3, out3 = cli("--fold-growth")
    chk(rc3 == 1 and "거부" in out3 and read8(R.LIMITS_FILE) == c8, "[8] 래칫 실패 중(상한 1 줄임) = 접기 거부 · 아무것도 안 씀", out3[-300:])
    rc3b, out3b = cli("--update-lower")
    chk(read8(R.LIMITS_FILE) == c8, "[8] 래칫 실패 중 --update-lower = 그 지표 상한 줄 그대로(지우지 않음)", out3b[-300:])
write8(R.LIMITS_FILE, a8)
if os.path.isfile(os.path.join(B8, R.TARGETS_FILE)):
    os.remove(os.path.join(B8, R.TARGETS_FILE))
rc4, out4 = cli("--tighten-targets")
rc5, out5 = cli("--tighten-targets", "--write", "--rate", "0.05")
rc6, out6 = cli("--tighten-targets", "--rate", "x")
t8 = json.loads(read8(R.TARGETS_FILE))
chk(rc4 == 0 and "목표 표 없음" in out4, "[8] --tighten-targets(목표 표 없음) = 안내만 rc 0", out4[-200:])
chk(rc5 == 0 and "쪼개야 할 파일" in out5 and t8["targets"] and all(t["to"] < t["from"] or t["to"] == 0 or t["from"] <= 80
                                                                    for t in t8["targets"]),
    "[8] --write = 목표 표(지금 값에서 5%% 줄임 · 규칙 한도 밑으론 안 내림) + 쪼개야 할 파일 안내 rc 0(%d단위)" % len(t8["targets"]), out5[-300:])
chk(rc6 == 2, "[8] --rate 숫자 아님 = rc 2")

SW = "\n\ndef _t_sw():\n    try:\n        return 1\n    except Exception as e:\n        calcguard.swallowed('t:sw', e)\n        pass\n"
hs9 = [ast.parse(SW).body[0].body[0].handlers[0], ast.parse(SW.replace("        pass\n", "        return 0\n")).body[0].body[0].handlers[0],
       ast.parse(SW.replace("calcguard.swallowed('t:sw', e)", "calcguard.swallowed('t:sw', e, expected=True)")).body[0].body[0].handlers[0]]
chk([D.swallow_pass(h) for h in hs9] == [True, False, True], "[9] swallow_pass = [swallowed, pass] 몸통만(대체값 반환 = 아님 · expected 인자는 꼴 무관)")
base9 = next((ln for ln in R.parse_lines(read8("py_except.jsonl"), "py_except") if ln["k"] == "except.swallow_pass"), None)
chk(base9 is not None and base9["m"] == "*" and base9["q"] == "*", "[9] 기준선 py_except.jsonl 에 except.swallow_pass 한 줄(저장소 합)", base9)
shutil.copy(os.path.join(T.HERE, "test_arch_except.py"), TESTS8)


def run_exc8():
    p9 = subprocess.run([sys.executable, os.path.join(TESTS8, "test_arch_except.py")], capture_output=True, text=True, encoding="utf-8",
                        env=ENV, timeout=600, cwd=R8)
    return p9.returncode, p9.stdout


rc9a, o9a = run_exc8()
with open(os.path.join(R8, "src", "calcguard.py"), "a", encoding="utf-8") as f9:
    f9.write(SW.replace("calcguard.swallowed", "swallowed"))
rc9b, o9b = run_exc8()
chk(rc9a == 0 and rc9b != 0 and "except.swallow_pass" in o9b and "= %d" % (base9["v"] + 1) in o9b if base9 else False,
    "[9] 지금 = 통과 · 자리 하나 더(%s) = except.swallow_pass 래칫 실패" % ((base9 or {}).get("v", 0) + 1), (rc9a, rc9b, o9b[-500:]))
T.finish()
