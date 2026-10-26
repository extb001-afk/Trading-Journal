#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _arch_py_ratchet as PR  # noqa: E402

import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402

chk = T.chk
TOOL = os.path.join(T.ROOT, "tools", "refactor", "codemod_mod.py")
if not os.path.isfile(TOOL):
    print("SKIP tools/refactor/codemod_mod.py 없음(공개판 — 리팩터 도구는 운영 저장소에만)")
    T.finish()
sys.path.insert(0, os.path.dirname(TOOL))
import codemod_mod as C  # noqa: E402

TAB = {"STATE_DIR": "paths", "DB_PATH": "paths", "read_json": "statefile", "safe_err": "logs",
       "seed_merge": "seeds", "seed_canon": "seeds", "auth_urlopen": "net_http"}

SRC1 = b'''"""doc."""
import json
import common  # noqa: keep

X = common.STATE_DIR + "x"   # note
common.DB_PATH = "a"
del common.DB_PATH


def f(a):
    return common.read_json(a), common.other, json.dumps(1)


class K:
    y = common.STATE_DIR

    def m(self):
        return [common.read_json(x) for x in ()], (lambda: common.STATE_DIR)
'''
r = C.rewrite("src/x.py", SRC1, TAB)
new = r.new.decode()
chk("import common, paths, statefile  # noqa: keep" in new.split("\n"), "[1] 모드 A import 줄 = common 맨 앞 + 정의 모듈 정렬(줄 끝 주석 그대로)", new)
chk('X = paths.STATE_DIR + "x"   # note' in new and 'paths.DB_PATH = "a"' in new and "del paths.DB_PATH" in new,
    "[1] 읽기·대입·삭제 = 정의 모듈로(대리 모듈이 넘기는 꼴 · 주석 그대로)", new)
chk("statefile.read_json(a), common.other" in new and "y = paths.STATE_DIR" in new and "[statefile.read_json(x) for x in ()]" in new
    and "lambda: paths.STATE_DIR" in new, "[1] 함수·클래스 몸통·내포·람다 안도 바꿈 · 표에 없는 이름은 common 그대로", new)
chk(r.counts == {"attr": 7, "bare": 0, "import": 1, "left": 1} and not r.refused and r.new.count(b"\n") == SRC1.count(b"\n"),
    "[1] 센 수(속성 7 · import 1 · 남김 1 · 거부 0) · 줄 수 그대로", r.counts)
r = C.rewrite("src/c4.py", b"import common\nX = f\"{common.STATE_DIR}!\"\n", TAB)
chk(r.new == b"import common, paths\nX = f\"{paths.STATE_DIR}!\"\n", "[1] 식 하나인 f-string = 바꿈(글자 대조 통과)", r.new)
SRC2 = b"\"\"\"doc.\"\"\"\nimport os\nimport fsio  # x\n\nSEP = '/'\n\n\ndef read_env():\n    return STATE_DIR + SEP + str(DB_PATH), read_json(1)\n"
r = C.rewrite("src/common.py", SRC2, TAB, bare=True)
chk(r.new == b"\"\"\"doc.\"\"\"\nimport os\nimport fsio  # x\nimport paths, statefile\n\nSEP = '/'\n\n\ndef read_env():\n"
    b"    return paths.STATE_DIR + SEP + str(paths.DB_PATH), statefile.read_json(1)\n" and r.added == ["paths", "statefile"],
    "[1] 모드 B = 맨 이름 → 정의 모듈.이름 · 맨 위 import 묶음 바로 뒤에 한 줄", r.new)
SRC2b = b"import os\nimport paths\n\n\ndef read_env():\n    return STATE_DIR, paths.other, read_json(1)\n"
r = C.rewrite("src/common.py", SRC2b, TAB, bare=True)
chk(r.new == b"import os\nimport paths\nimport statefile\n\n\ndef read_env():\n    return paths.STATE_DIR, paths.other, statefile.read_json(1)\n"
    and r.added == ["statefile"], "[1] 모드 B: 맨 위 묶음에 이미 있는 `import paths` 는 그대로 씀(없는 statefile 만 한 줄)", r.new)

REF = [("함수 안 import common", b"def f():\n    import common\n    return common.STATE_DIR\n"),
       ("조건부 import common", b"if X:\n    import common\nY = common.STATE_DIR\n"),
       ("try 안 import common", b"try:\n    import common\nexcept ImportError:\n    common = None\nY = common.STATE_DIR\n"),
       ("별칭 import common as cm", b"import common as cm\nY = cm.STATE_DIR\nZ = common.STATE_DIR\n"),
       ("여러 이름 import json, common", b"import json, common\nY = common.STATE_DIR\n"),
       ("import common 두 번", b"import common\nimport common\nY = common.STATE_DIR\n"),
       ("모듈과 함수 둘 다 import common", b"import common\n\n\ndef f():\n    import common\n    return common.STATE_DIR\n"),
       ("from common import", b"import common\nfrom common import read_json\nY = common.STATE_DIR, read_json\n"),
       ("import common.sub", b"import common\nimport common.sub\nY = common.STATE_DIR\n"),
       ("common 대입", b"import common\ncommon = common\nY = common.STATE_DIR\n"),
       ("함수 안 global common", b"import common\n\n\ndef f():\n    global common\n    common = None\n\n\nY = common.STATE_DIR\n"),
       ("인자 이름 common", b"import common\n\n\ndef f(common):\n    return common.STATE_DIR\n"),
       ("for 대상 common", b"import common\nfor common in ():\n    pass\nY = common.STATE_DIR\n"),
       ("except as common", b"import common\ntry:\n    pass\nexcept E as common:\n    pass\nY = common.STATE_DIR\n"),
       ("클래스 이름 common", b"import common\nY = common.STATE_DIR\n\n\nclass common:\n    pass\n"),
       ("from F import common", b"import common\nfrom pkg import common\nY = common.STATE_DIR\n"),
       ("nonlocal common", b"import common\n\n\ndef o():\n    common = 1\n\n    def i():\n        nonlocal common\n        return common.STATE_DIR\n    return i\n"),
       ("정의 모듈 import 가 이미 있음(맨 위 묶음 밖 · 두 번)", b"import paths\nX = 1\nimport common\nimport paths\nY = common.STATE_DIR\n"),
       ("정의 모듈 이름이 인자", b"import common\n\n\ndef g(paths):\n    return common.STATE_DIR\n"),
       ("정의 모듈 이름이 지역 변수", b"import common\n\n\ndef g():\n    paths = 1\n    return common.STATE_DIR, paths\n"),
       ("from 정의 모듈 import", b"import common\nfrom paths import other\nY = common.STATE_DIR\n"),
       ("정의 모듈 이름을 맨 이름으로 읽음(내장·바깥 주입)", b"import common\nY = common.STATE_DIR, paths\n"),
       ("함수 안 import 정의 모듈", b"import common\n\n\ndef h():\n    import paths\n    return paths.x\nY = common.STATE_DIR\n"),
       ("from X import *", b"import common\nfrom overlay import *\nY = common.STATE_DIR\n"),
       ("globals()", b"import common\nglobals()['common'] = None\nY = common.STATE_DIR\n"),
       ("exec", b"import common\nexec('common = 1')\nY = common.STATE_DIR\n"),
       ("인자 없는 locals()", b"import common\n\n\ndef f():\n    return locals(), common.STATE_DIR\n"),
       ("주석(annotation) 안", b"import common\n\n\ndef f(a: common.STATE_DIR = None):\n    return a\n"),
       ("변수 주석 안", b"import common\nY: common.DB_PATH = common.STATE_DIR\n"),
       ("CRLF 글", b"import common\r\nY = common.STATE_DIR\r\n"),
       ("별칭으로 가져온 globals", b"from builtins import globals as ns\nimport common\nseen = 'paths' in ns()\nY = common.STATE_DIR\n"),
       ("속성으로 부른 builtins.globals()", b"import builtins\nimport common\nbuiltins.globals()['common'] = 1\nY = common.STATE_DIR\n"),
       ("인자 없는 dir()", b"import common\nNAMES = dir()\nY = common.STATE_DIR\n"),
       ("인수 펼친 vars(*())", b"import common\nV = vars(*())\nY = common.STATE_DIR\n"),
       ("sys.modules", b"import sys\nimport common\nsetattr(sys.modules[__name__], 'common', 1)\nY = common.STATE_DIR\n"),
       ("metaclass __prepare__ 가 이름 공간을 채우는 클래스 몸통", b"import common\n\n\nclass Meta(type):\n    @classmethod\n"
        b"    def __prepare__(mcls, name, bases):\n        return {'paths': 1}\n\n\nclass K(metaclass=Meta):\n    value = common.STATE_DIR\n"),
       ("기반 클래스가 있는 클래스 몸통(물려받은 metaclass)", b"import common\n\n\nclass K(Base):\n    value = common.STATE_DIR\n"),
       ("기반 클래스 몸통의 내포 첫 iter", b"import common\n\n\nclass K(Base):\n    v = [x for x in common.STATE_DIR]\n")]
for label, src9 in REF:
    r = C.rewrite("src/q.py", src9, TAB)
    chk(r.new == src9 and r.refused and not r.edits, "[2] 파일째 거부: " + label, r.refused)
src9 = b"import common\nX = f\"{common.STATE_DIR}/{common.STATE_DIR}\"\n"
r = C.rewrite("src/q.py", src9, TAB)
if sys.version_info >= (3, 12):
    chk(r.new == b"import common, paths\nX = f\"{paths.STATE_DIR}/{paths.STATE_DIR}\"\n" and not r.refused
        and C.prove("src/q.py", src9, r.new, TAB)["ok"], "[2] 같은 식 두 번 든 f-string = 3.12↑ 자리 정확 → 바꿈(증명 통과)", (r.new, r.refused))
else:
    chk(r.new == src9 and r.refused and not r.edits, "[2] 파일째 거부: 같은 식 두 번 든 f-string(3.12 전 — 자리 추정 불확실)", r.refused)
REFB = [("지역 같은 철자", b"import os\n\n\ndef f():\n    return STATE_DIR\n\n\ndef g():\n    STATE_DIR = 1\n    return STATE_DIR\n"),
        ("global 대입", b"import os\n\n\ndef f():\n    global STATE_DIR\n    STATE_DIR = 2\n"),
        ("맨 위 import 묶음 없음", b"\"\"\"doc.\"\"\"\nX = 1\n\n\ndef f():\n    return STATE_DIR\n"),
        ("맨 위 묶음 끝 줄에 다른 글", b"import os; X = 1\n\n\ndef f():\n    return STATE_DIR\n"),
        ("별칭 import paths as p", b"import os\nimport paths as p\n\n\ndef f():\n    return STATE_DIR, p\n"),
        ("함수 안 import paths", b"import os\n\n\ndef f():\n    import paths\n    return STATE_DIR, paths\n"),
        ("import paths 가 맨 위 묶음 밖", b"import os\nX = 1\nimport paths\n\n\ndef f():\n    return STATE_DIR\n"),
        ("주석 안 맨 이름", b"import os\n\n\ndef f(a: STATE_DIR):\n    return a\n"),
        ("내장 이름(open)", b"import os\n\n\ndef f():\n    return open\n")]
TAB = dict(TAB, open="paths")
for label, src9 in REFB:
    r = C.rewrite("src/common.py", src9, TAB, bare=True)
    chk(r.new == src9 and r.refused and not r.edits, "[2] 모드 B 파일째 거부: " + label, r.refused)
TAB.pop("open")

r = C.rewrite("src/k2.py", b"import common\n\n\nclass K(Base):\n    def m(self):\n        return common.STATE_DIR\n    v = [common.DB_PATH for x in ()]\n", TAB)
chk(not r.refused and b"return paths.STATE_DIR" in r.new and b"[paths.DB_PATH for x in ()]" in r.new,
    "[2] 기반 클래스의 메서드 몸통 · 내포 안쪽(첫 iter 밖) = 클래스 이름 공간을 안 보니 바꿈", (r.refused, r.new))
r = C.rewrite("src/common.py", b"import os\n\n\nclass K(Base):\n    v = STATE_DIR\n", TAB, bare=True)
chk(r.refused and not r.edits, "[2] 모드 B: 기반 클래스 몸통의 맨 이름 = 거부(__prepare__)", r.refused)

bad_tab = 0
for raw in ({"__paths": ["STATE_DIR"]}, {"paths": ["__value"]}, {"__class__": ["X"]}):
    tp = os.path.join(T.TMP, "badtab.json")
    with open(tp, "w", encoding="utf-8") as f:
        json.dump(raw, f)
    try:
        C.load_table(tp)
    except ValueError:
        bad_tab += 1
chk(bad_tab == 3, "[2] 표: 밑줄 둘로 시작하는 정의 모듈·이름(클래스 안 맹글링 · __class__ 셀) = 표 오류", bad_tab)

r = C.rewrite("src/sm.py", b"import sys\nimport common\nok = 'sqlite3' not in sys.modules\nY = common.STATE_DIR\n", TAB)
chk(not r.refused and b"paths.STATE_DIR" in r.new, "[2] `x not in sys.modules` 소속 검사만은 이름 공간 접근으로 안 봄(바꿈)", r.refused)
PX = b"import sys\nimport paths\n\n\nclass _P(type(sys)):\n    pass\n\n\nsys.modules[__name__].__class__ = _P\n\n\ndef load():\n    return CONFIG_PATH\n"
r = C.rewrite("src/common.py", PX, dict(TAB, CONFIG_PATH="paths"), bare=True)
chk(not r.refused and b"return paths.CONFIG_PATH" in r.new and C.prove("src/common.py", PX, r.new, dict(TAB, CONFIG_PATH="paths"), bare=True)["ok"],
    "[2] 모드 B: 대리 모듈 설치 한 줄(sys.modules[__name__].__class__ = …)이 있는 4-1 꼴 = 바꿈 · 증명 통과", r.refused)
r = C.rewrite("src/common.py", PX.replace(b".__class__ = _P", b".paths = None"), dict(TAB, CONFIG_PATH="paths"), bare=True)
chk(r.refused, "[2] 모드 B: sys.modules[__name__] 의 다른 속성 쓰기 = 거부", r.refused)

r = C.rewrite("src/r.py", b"import common\nX = getattr(common, 'Y'), common.STATE_DIR\n", TAB)
chk(r.new == b"import common, paths\nX = getattr(common, 'Y'), paths.STATE_DIR\n", "[3] 모듈 객체 직접 사용 = common 이 남으니 그대로 바꿈", r.new)
r = C.rewrite("src/r2.py", b"import common  # side effect\n", TAB)
chk(r.new == b"import common  # side effect\n" and any("참조 없는" in n for _w, n in r.notes), "[3] 표 이름 참조 없는 import common = 그대로 · 보고", r.notes)

r = C.rewrite("src/x.py", SRC1, TAB)
p = C.prove("src/x.py", SRC1, r.new, TAB)
chk(p["ok"] and p["recomputed"] == p["delta"] == len(r.new) - len(SRC1) and p["mods"] == ["paths", "statefile"], "[4] 도구 결과 = 증명 통과 · 바이트 차 = 실제", p)
chk(C._expected_dump(SRC1, TAB, False, r.mods) == C.ast.dump(C.ast.parse(r.new), include_attributes=False),
    "[4] 손으로 적용한 AST(따로 만든 변환) = 도구 결과 AST")
chk(C._expected_dump(SRC1, TAB, False, ["paths"]) != C.ast.dump(C.ast.parse(r.new), include_attributes=False),
    "[4] 손으로 적용한 AST 가 import 모듈 하나만 달라도 다름(대조가 살아 있음)")
for label, n9 in (("주석 한 글자", r.new.replace(b"# note", b"# nose")), ("다른 정의 모듈", r.new.replace(b"paths.DB_PATH", b"statefile.DB_PATH")),
                  ("표 밖 이름 바꿈", r.new.replace(b"common.other", b"common.other2")),
                  ("import 순서", r.new.replace(b"import common, paths, statefile", b"import common, statefile, paths")),
                  ("common 지움", r.new.replace(b"import common, paths, statefile", b"import paths, statefile")),
                  ("common 을 뒤로", r.new.replace(b"import common, paths, statefile", b"import paths, statefile, common")),
                  ("한 자리만 안 바꿈", r.new.replace(b"y = paths.STATE_DIR", b"y = common.STATE_DIR"))):
    chk(not C.prove("src/x.py", SRC1, n9, TAB)["ok"], "[4] 손으로 만든 틀린 결과 = 실패: " + label)
bad = [("참조 없는 import common 을 정의 모듈 import 로 바꿈", b"import common\n", b"import logs\n"),
       ("정의 모듈을 조건부 import 로만 묶음", b"import common\nif False:\n    import paths\nX = common.STATE_DIR\n",
        b"import common\nif False:\n    import paths\nX = paths.STATE_DIR\n"),
       ("지연 import 를 모듈 맨 위로", b"import json\n\n\ndef f():\n    import common\n    return common.STATE_DIR\n",
        b"import json\nimport paths\n\ndef f():\n    import json\n    return paths.STATE_DIR\n"),
       ("함수 안 import 를 같은 자리에서 바꿈(지원 밖)", b"def f():\n    import common\n    return common.STATE_DIR\n",
        b"def f():\n    import common, paths\n    return paths.STATE_DIR\n"),
       ("from common 나눔(지원 밖)", b"from common import read_json, STATE_DIR\nr = STATE_DIR\n",
        b"from paths import STATE_DIR\nfrom statefile import read_json\nr = STATE_DIR\n"),
       ("common 없던 정의 모듈 import 를 바꿈", b"import paths\n", b"import statefile\n"),
       ("있던 정의 모듈 import 순서", b"import paths, logs\n", b"import logs, paths\n"),
       ("from 정의 모듈을 from common 으로 되돌림", b"from paths import STATE_DIR\n", b"from common import STATE_DIR\n"),
       ("정의 모듈 참조를 common 으로 되돌림", b"import common, paths\nout = paths.STATE_DIR\n", b"import common, paths\nout = common.STATE_DIR\n"),
       ("맨 이름 역방향(모드 A 표에서)", b"import common, paths\nout = paths.STATE_DIR\n", b"import common, paths\nout = STATE_DIR\n"),
       ("import * 가 있는 파일", b"import common\nfrom overlay import *\nx = common.STATE_DIR\n", b"import common, paths\nfrom overlay import *\nx = paths.STATE_DIR\n"),
       ("기본 인자에서 늦은 import 를 먼저 읽음", b"import os\nimport common\n\n\ndef f(a=common.STATE_DIR):\n    return a\n",
        b"import os\nimport common\n\n\ndef f(a=paths.STATE_DIR):\n    return a\nimport paths\n")]
for label, o9, n9 in bad:
    chk(not C.prove("src/b9.py", o9, n9, TAB)["ok"], "[4] 손으로 만든 틀린 결과 = 실패: " + label)
r = C.rewrite("src/common.py", SRC2, TAB, bare=True)
chk(C.prove("src/common.py", SRC2, r.new, TAB, bare=True)["ok"], "[4] 모드 B 결과 = 증명 통과")
chk(not C.prove("src/common.py", b"import os\nimport paths\nX = paths.STATE_DIR\n", b"import os\nimport paths\nX = STATE_DIR\n", TAB, bare=True)["ok"],
    "[4] 모드 B 역방향(정의 모듈.이름 → 맨 이름) = 실패")
r = C.rewrite("src/common.py", SRC2b, TAB, bare=True)
chk(C.prove("src/common.py", SRC2b, r.new, TAB, bare=True)["ok"] and not C.prove("src/common.py", SRC2b, r.new.replace(b"import statefile\n", b""), TAB, bare=True)["ok"],
    "[4] 모드 B(있던 import 그대로) = 통과 · 새 줄을 빼면 실패")

R5 = os.path.join(T.TMP, "r5")
B5 = os.path.join(R5, "public", "tests", "arch_baseline")
os.makedirs(B5)
with open(os.path.join(B5, "py_size.jsonl"), "w", encoding="utf-8") as f:
    f.write('{"k":"_keys","m":"*","q":"*","v":["file.bytes"]}\n{"k":"file.bytes","m":"big","q":"<file>","v":70000}\n'
            '{"k":"file.bytes","m":"huge","q":"<file>","v":80000}\n')
with open(os.path.join(B5, "py_rules.json"), "w", encoding="utf-8") as f:
    json.dump({"limits": {"file.bytes": 65536}}, f)
with open(os.path.join(B5, "py_growth.jsonl"), "w", encoding="utf-8") as f:
    f.write(json.dumps({"k": "file.bytes", "m": "big", "q": "<file>", "to": 70001, "why": C.MARK_WHY, "commit": "old"}) + "\n")
    f.write(json.dumps({"k": "file.bytes", "m": "huge", "q": "<file>", "to": 80003, "why": C.MARK_WHY, "commit": "old"}) + "\n")
    f.write(json.dumps({"k": "func.lines", "m": "big", "q": "f", "to": 90, "why": "다른 사유", "commit": "x"}) + "\n")


def res(path, old, new):
    x = C.Result(path)
    x.old, x.new = old, new
    return x


rows, block = C.growth_plan(R5, [res("src/big.py", b"a" * 69990, b"a" * 70010), res("src/small.py", b"a" * 65000, b"a" * 65600),
                                 res("src/mid.py", b"a" * 50000, b"a" * 50100), res("tools/t.py", b"a", b"aa")])
chk(rows == [{"k": "file.bytes", "m": "big", "q": "<file>", "to": 70010}], "[5] 기준선(70,000)보다 커지는 src 파일 = 정확한 to 의 성장 줄 하나", rows)
chk(len(block) == 1 and "src/small.py" in block[0], "[5] 기준선 밖인데 하드 한도(64KiB)를 넘게 됨 = 막힘(성장 사유 표로 못 받음)", block)
txt = C.growth_text(R5, rows, "w 시험", changed={"big", "huge"})
got = [json.loads(x) for x in txt.split("\n") if x.strip()]
chk([g["k"] for g in got] == ["func.lines", "file.bytes"] and got[1]["to"] == 70010 and got[1]["commit"] == "w 시험" and got[1]["why"] == C.WRITE_WHY
    and C.MARK_WHY in C.WRITE_WHY and PR.why_ok(C.WRITE_WHY) and not any(g.get("m") == "huge" for g in got),
    "[5] 바뀐 모듈의 옛 코드모드 줄 = 새 값으로(big · 사유 = 표지 + 설명 · 래칫 사유 규칙 통과) · 기준선 이하가 되면 지움(huge) · 다른 사유 줄 그대로", got)
txt2 = C.growth_text(R5, [], "w", changed={"big"})
chk('"m": "huge"' in txt2 and '"m": "big", "q": "<file>"' not in txt2, "[5] 이번 범위 밖 모듈(huge)의 코드모드 줄은 그대로 물려받음", txt2)
with open(os.path.join(B5, "py_growth.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps({"k": "file.bytes", "m": "big", "q": "<file>", "to": 99999, "why": C.MARK_WHY, "commit": "dup"}) + "\n")
try:
    C.growth_text(R5, rows, "w")
    dup_ok = False
except ValueError:
    dup_ok = True
chk(dup_ok, "[5] 같은 단위 코드모드 줄 둘 = 쓰기 전에 멈춤(ValueError)")
W5 = os.path.join(T.TMP, "w5")
os.makedirs(W5)
fa, fb, fl, out_t = (os.path.join(W5, n) for n in ("a.py", "b.py", "link.py", "outside.txt"))
for pth, body in ((fa, b"A0"), (fb, b"B0"), (out_t, b"KEEP")):
    with open(pth, "wb") as f:
        f.write(body)
os.symlink(out_t, fl)
calls = []


def flaky(src, dst):
    calls.append(dst)
    if len(calls) == 2:
        raise OSError("가짜 교체 오류")
    return os.replace(src, dst)


ok5 = C._write_all([(fa, b"A1"), (fb, b"B1")], replace=flaky)
left = sorted(n for n in os.listdir(W5) if n.startswith(".codemod_"))
chk(not ok5 and open(fa, "rb").read() == b"A0" and open(fb, "rb").read() == b"B0" and not left,
    "[5] 교체 도중 오류 = 이미 바꾼 파일을 원래 글로 되돌림 · 임시 파일 0", (ok5, open(fa, "rb").read(), left))
chk(not C._write_all([(fa, b"A2"), (fl, b"X")]) and open(out_t, "rb").read() == b"KEEP" and open(fa, "rb").read() == b"A0",
    "[5] 대상이 심볼릭 링크 = 아무것도 안 씀(링크 너머 파일 그대로)")
chk(not C._write_all([(fa, b"A3"), (fa, b"A4")]) and open(fa, "rb").read() == b"A0", "[5] 같은 대상 두 번 = 아무것도 안 씀")
chk(C._write_all([(fa, b"A5"), (fb, b"B5")]) and open(fa, "rb").read() == b"A5" and open(fb, "rb").read() == b"B5"
    and not [n for n in os.listdir(W5) if n.startswith(".codemod_")], "[5] 정상 = 모두 씀 · 임시 파일 0")

MI = os.path.join(W5, "mi.py")
with open(MI, "w", encoding="utf-8") as f:
    f.write("import os\nA = 1\nif os:\n    B = 2\n[(C := 3) for _ in (0,)]\nfor D in ():\n    pass\n\n\ndef E():\n    F = 1\n"
            "from .x import y\n")
mi = C._mod_info(MI)
MI2 = os.path.join(W5, "mi2.py")
with open(MI2, "w", encoding="utf-8") as f:
    f.write("from importlib import import_module as load\nX = load('h')\n")
MI3 = os.path.join(W5, "mi3.py")
with open(MI3, "w", encoding="utf-8") as f:
    f.write("import builtins\nexec(\"STATE_DIR = 1\")\nY = builtins.__import__('h')\n")
mi2, mi3 = C._mod_info(MI2), C._mod_info(MI3)
chk(mi2["opaque"] and mi3["opaque"] and "*" in mi3["any"],
    "[5] 전제용 사실: 별칭 import_module · 속성 __import__ · exec = 의존 불투명(P3) · exec·globals 류 = 모든 이름을 묶는다고 봄(P2)", (mi2, mi3))
chk(mi["sure"] >= {"os", "A", "E"} and not mi["sure"] & {"B", "C", "D", "F"} and mi["any"] >= {"A", "B", "C", "D", "F"} and mi["opaque"],
    "[5] 전제용 사실: sure = 최상위 무조건 결합만 · any = 조건부·내포 walrus·for 대상·지역까지(match 캡처도 bindings 가 셈 · 3.9 파싱 불가라 시험 없음) · 상대 import = 의존 불투명", mi)
OUTD = os.path.join(T.TMP, "outside5")
os.makedirs(OUTD)
with open(os.path.join(OUTD, "x.py"), "wb") as f:
    f.write(b"OUT")
os.symlink(OUTD, os.path.join(W5, "linkdir"))
chk(not C._write_all([(os.path.join(W5, "linkdir", "x.py"), b"NEW")], root=W5) and open(os.path.join(OUTD, "x.py"), "rb").read() == b"OUT",
    "[5] 부모 폴더 링크로 트리 밖 파일 = 아무것도 안 씀")
os.link(fa, os.path.join(W5, "hard.py"))
chk(not C._write_all([(fa, b"H1"), (os.path.join(W5, "hard.py"), b"H2")], root=W5) and open(fa, "rb").read() == b"A5",
    "[5] 같은 파일의 다른 이름(하드 링크 · 같은 inode) 두 번 = 아무것도 안 씀")
calls2 = []


def flaky2(src, dst):
    calls2.append(dst)
    if len(calls2) >= 2:
        raise OSError("가짜 교체·되돌리기 오류")
    return os.replace(src, dst)


ok6 = C._write_all([(fa, b"A6"), (fb, b"B6")], root=W5, replace=flaky2)
chk(not ok6 and open(fb, "rb").read() == b"B5" and not [n for n in os.listdir(W5) if n.startswith(".codemod_")],
    "[5] 되돌리기까지 실패해도 임시 파일 0(되돌리지 못한 파일은 목록으로 알림)", os.listdir(W5))

GIT = shutil.which("git")
R6 = os.path.join(T.TMP, "r6")
ENV = {k: v for k, v in os.environ.items() if not k.startswith(("TJ_", "GIT_"))}
ENV.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x.invalid", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@x.invalid")


def sh(*a):
    p = subprocess.run(list(a), capture_output=True, text=True, encoding="utf-8", env=ENV, timeout=120)
    return p.returncode, p.stdout + p.stderr


def put(rel, text):
    path = os.path.join(R6, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def tool(*a):
    return sh(sys.executable, "-I", TOOL, *a)


if not GIT:
    chk(True, "[6] git 없음 — 명령 줄 시험 건너뜀")
else:
    shutil.copytree(R5 + "/public", R6 + "/public")
    put("public/tests/arch_baseline/py_growth.jsonl", "")
    put("src/paths.py", '"""가짜 정의 모듈."""\nSTATE_DIR = "/tmp/x.invalid"\nCONFIG_PATH = "c.invalid"\n')
    put("src/statefile.py", '"""가짜."""\n\n\ndef read_json(p):\n    return p\n')
    put("src/common.py", '"""대리 자리(옮긴 이름 없음)."""\nimport os\n\n\ndef load_config():\n    return CONFIG_PATH, os.sep\n')
    put("src/big.py", "import common\n\n\ndef f():\n    return common.STATE_DIR\n" + "#" * 70000 + "\n")
    put("tools/u.py", "import common\nprint(common.read_json, common.other)\n")
    put("tools/go_20260101.sh", "python3 - <<'PY'\nimport common\nPY\n")
    put("tools/live.sh", "python3 -c 'from common import x'\n")
    tab = os.path.join(T.TMP, "tab.json")
    with open(tab, "w", encoding="utf-8") as f:
        json.dump({"paths": ["STATE_DIR", "CONFIG_PATH"], "statefile": ["read_json"]}, f)
    gp = os.path.join(R6, "public", "tests", "arch_baseline", "py_growth.jsonl")
    sh(GIT, "-C", R6, "init", "-q")
    sh(GIT, "-C", R6, "add", "-A")
    rc0, out0 = sh(GIT, "-C", R6, "commit", "-qm", "base")
    rc, out = tool("apply", "--table", tab, "--root", R6, "--growth-commit", "시험 표시", os.path.join(R6, "src/big.py"), os.path.join(R6, "tools/u.py"))
    gl = open(gp, encoding="utf-8").read()
    big = open(os.path.join(R6, "src", "big.py"), encoding="utf-8").read()
    chk(rc0 == 0 and rc == 0 and "import common, paths\n" in big and "paths.STATE_DIR" in big and '"to": %d' % len(big.encode()) in gl and "시험 표시" in gl,
        "[6] apply = 파일 바꿈 + 성장 줄(to = 새 바이트 · commit 표시)", (rc, out[-400:], gl))
    rc, out = tool("prove", "--table", tab, "--root", R6, "--base", "HEAD")
    chk(rc == 0 and "증명 2파일 · 실패 0" in out, "[6] prove --base HEAD = 바뀐 2파일 통과", out[-400:])
    with open(gp, "w", encoding="utf-8") as f:
        f.write(gl.replace('"to": %d' % len(big.encode()), '"to": %d' % (len(big.encode()) + 1)))
    rc, out = tool("prove", "--table", tab, "--root", R6, "--base", "HEAD")
    chk(rc == 1 and "코드모드 성장 줄 ('file.bytes', 'big', '<file>') 의 to(" in out, "[6] 성장 줄 to 가 새 바이트와 다르면 prove 실패", out[-400:])
    with open(gp, "w", encoding="utf-8") as f:
        f.write(gl + json.dumps({"k": "func.lines", "m": "x", "q": "f", "to": 99, "why": "다른 사유", "commit": "y"}) + "\n")
    rc, out = tool("prove", "--table", tab, "--root", R6, "--base", "HEAD")
    chk(rc == 1 and "다른 사유 줄이 바뀜" in out, "[6] 성장 사유 표의 다른 사유 줄을 더하거나 바꾸면 prove 실패", out[-300:])
    with open(gp, "w", encoding="utf-8") as f:
        f.write(gl.replace('"k": "file.bytes"', '"k": "func.lines"'))
    rc, out = tool("prove", "--table", tab, "--root", R6, "--base", "HEAD")
    chk(rc == 1 and "단위가 틀린" in out and "성장 줄 없음" in out, "[6] 코드모드 성장 줄의 지표(k)가 틀리면 prove 실패", out[-300:])
    row = [x for x in gl.split("\n") if x.strip()][0]
    with open(gp, "w", encoding="utf-8") as f:
        f.write(row.replace('"to": %d' % len(big.encode()), '"to": 999999') + "\n" + gl)
    rc, out = tool("prove", "--table", tab, "--root", R6, "--base", "HEAD")
    chk(rc == 1 and "중복" in out, "[6] 같은 단위 코드모드 성장 줄 둘(큰 상한을 숨김) = prove 실패", out[-300:])
    with open(gp, "w", encoding="utf-8") as f:
        f.write(gl)
    put("src/json.py", "X = 1\n")
    rc, out = tool("prove", "--table", tab, "--root", R6, "--base", "HEAD")
    chk(rc == 1 and "src/json.py — 코드모드는 파일을 만들거나 지우지 않음(새 파일)" in out, "[6] 기준에 없던 새 .py 파일 = prove 실패", out[-300:])
    os.remove(os.path.join(R6, "src", "json.py"))
    put("tools/note.txt", "x\n")
    sh(GIT, "-C", R6, "add", "tools/note.txt")
    rc, out = tool("prove", "--table", tab, "--root", R6, "--base", "HEAD")
    chk(rc == 1 and "증명 밖 변경 A tools/note.txt" in out, "[6] 코드모드 범위 밖 파일 변경 = prove 실패(치환·성장 줄만 허용)", out[-300:])
    os.remove(os.path.join(R6, "tools", "note.txt"))
    sh(GIT, "-C", R6, "rm", "-q", "--cached", "tools/note.txt")
    rc, out = tool("prove", "--table", tab, "--root", R6, "--base", "no_such_ref")
    chk(rc == 2 and "기준 커밋을 못 찾음" in out, "[6] 없는 기준 커밋 = 증명하지 않고 종료 2", out[-300:])
    rc, out = tool("plan", "--table", tab, "--root", R6, "../outside.py")
    chk(rc == 2 and "트리 밖" in out, "[6] 트리 밖 파일 인자 = 종료 2", out[-200:])
    sh(GIT, "-C", R6, "add", "-A")
    sh(GIT, "-C", R6, "commit", "-qm", "stage1")
    put("tools/w.py", "import common\nX = common.STATE_DIR\n")
    with open(os.path.join(R6, "src", "common.py"), "a", encoding="utf-8") as f:
        f.write("STATE_DIR = 'own'\n")
    sh(GIT, "-C", R6, "add", "-A")
    sh(GIT, "-C", R6, "commit", "-qm", "p2")
    rc, out = tool("apply", "--table", tab, "--root", R6, "--growth-commit", "x", os.path.join(R6, "tools/w.py"))
    chk(rc == 1 and "P2" in out and "아무것도 쓰지 않음" in out and "common.STATE_DIR" in open(os.path.join(R6, "tools", "w.py"), encoding="utf-8").read(),
        "[6] 전제 P2(common 이 아직 그 이름을 묶음 — 대리 전) = apply 안 씀", out[-300:])
    put("tools/w.py", "import common, paths\nX = paths.STATE_DIR\n")
    rc, out = tool("prove", "--table", tab, "--root", R6, "--base", "HEAD", os.path.join(R6, "tools/w.py"))
    chk(rc == 1 and "전제 P2" in out, "[6] 전제 P2 위반 커밋 = prove 실패", out[-300:])
    sh(GIT, "-C", R6, "checkout", "-q", "HEAD~1", "--", "src/common.py")
    with open(os.path.join(R6, "src", "common.py"), "a", encoding="utf-8") as f:
        f.write("[(STATE_DIR := 'own') for _ in (0,)]\n")
    put("tools/w.py", "import common\nX = common.STATE_DIR\n")
    rc, out = tool("plan", "--table", tab, "--root", R6, os.path.join(R6, "tools/w.py"))
    chk(rc == 1 and "P2" in out, "[6] 전제 P2: common 의 내포 walrus 모듈 결합도 '아직 묶음'으로 봄", out[-300:])
    sh(GIT, "-C", R6, "checkout", "-q", "HEAD~1", "--", "src/common.py")
    put("tools/w.py", "import common\nX = common.STATE_DIR\n")
    rc, out = tool("apply", "--table", tab, "--root", R6, "--growth-commit", "x", os.path.join(R6, "tools/w.py"))
    chk(rc == 0, "[6] 전제를 채우면(common 이 그 이름을 안 묶음) apply 됨", out[-300:])
    tab_bad = os.path.join(T.TMP, "tab_bad.json")
    with open(tab_bad, "w", encoding="utf-8") as f:
        json.dump({"paths": ["read_json"]}, f)
    put("tools/v.py", "import common\nX = common.read_json\n")
    rc, out = tool("plan", "--table", tab_bad, "--root", R6, os.path.join(R6, "tools/v.py"))
    chk(rc == 1 and "P1 src/paths.py 최상위 무조건 문장이 read_json 를 묶지 않음" in out, "[6] 전제 P1(표가 틀림) = plan 실패로 보고", out[-300:])
    os.remove(os.path.join(R6, "tools", "v.py"))
    sh(GIT, "-C", R6, "add", "-A")
    sh(GIT, "-C", R6, "commit", "-qm", "w")
    rc, out = tool("apply", "--table", tab, "--root", R6, "--bare", os.path.join(R6, "src", "common.py"), "--growth-commit", "b", os.path.join(R6, "src/common.py"))
    cm = open(os.path.join(R6, "src", "common.py"), encoding="utf-8").read()
    rc2, out2 = tool("prove", "--table", tab, "--root", R6, "--bare", os.path.join(R6, "src", "common.py"), "--base", "HEAD")
    chk(rc == 0 and "import os\nimport paths\n" in cm and "return paths.CONFIG_PATH, os.sep" in cm and rc2 == 0 and "증명 1파일 · 실패 0" in out2,
        "[6] 모드 B apply → prove 통과(맨 이름 → paths.CONFIG_PATH · import 한 줄)", (out[-200:], out2[-300:]))
    sh(GIT, "-C", R6, "checkout", "-q", "--", "src/common.py")
    with open(os.path.join(R6, "src", "paths.py"), "a", encoding="utf-8") as f:
        f.write("import common\n")
    rc, out = tool("apply", "--table", tab, "--root", R6, "--bare", os.path.join(R6, "src", "common.py"), "--growth-commit", "b", os.path.join(R6, "src/common.py"))
    chk(rc == 1 and "P3" in out and "paths" not in open(os.path.join(R6, "src", "common.py"), encoding="utf-8").read(),
        "[6] 전제 P3(정의 모듈이 바뀌는 모듈을 import — 순환) = apply 안 씀", out[-300:])
    sh(GIT, "-C", R6, "checkout", "-q", "--", "src/paths.py")
    with open(os.path.join(R6, "src", "paths.py"), "a", encoding="utf-8") as f:
        f.write("import helper9\n")
    put("src/helper9.py", "from common import load_config\n")
    rc, out = tool("plan", "--table", tab, "--root", R6, "--bare", os.path.join(R6, "src", "common.py"), os.path.join(R6, "src/common.py"))
    chk(rc == 1 and "P3" in out and "common 에 닿음" in out, "[6] 전제 P3: 간접 순환(paths → helper9 → common) = 위반", out[-300:])
    put("src/helper9.py", "from . import z\n")
    rc, out = tool("plan", "--table", tab, "--root", R6, "--bare", os.path.join(R6, "src", "common.py"), os.path.join(R6, "src/common.py"))
    chk(rc == 1 and "순환 여부를 못 봄" in out, "[6] 전제 P3: 폐포에 상대·동적 import = 위반(못 봄)", out[-300:])
    os.remove(os.path.join(R6, "src", "helper9.py"))
    sh(GIT, "-C", R6, "checkout", "-q", "--", "src/paths.py")
    os.symlink(OUTD, os.path.join(R6, "tools", "ext"))
    rc, out = tool("plan", "--table", tab, "--root", R6, os.path.join(R6, "tools", "ext", "x.py"))
    chk(rc == 2 and "부모 폴더 링크" in out, "[6] 부모 폴더 링크로 트리 밖 파일 인자 = 종료 2", out[-200:])
    os.remove(os.path.join(R6, "tools", "ext"))
    put("tools/z.py", "import common\n\n\ndef g(paths):\n    return common.STATE_DIR\n")
    put("tools/y.py", "import common\nY = common.read_json\n")
    rc, out = tool("apply", "--table", tab, "--root", R6, "--growth-commit", "x", os.path.join(R6, "tools/z.py"), os.path.join(R6, "tools/y.py"))
    chk(rc == 1 and "아무것도 쓰지 않음" in out and "common.read_json" in open(os.path.join(R6, "tools", "y.py"), encoding="utf-8").read(),
        "[6] 거부가 하나라도 있으면 apply 는 아무 파일도 안 씀", out[-300:])
    os.remove(os.path.join(R6, "tools", "z.py"))
    sh(GIT, "-C", R6, "add", "-A")
    sh(GIT, "-C", R6, "commit", "-qm", "y")
    rc, out = tool("apply", "--table", tab, "--root", R6, "--growth-commit", "stage2", os.path.join(R6, "tools/y.py"))
    rc2, out2 = tool("prove", "--table", tab, "--root", R6, "--base", "HEAD")
    chk(rc == 0 and rc2 == 0 and "증명 1파일 · 실패 0" in out2, "[6] 앞 단계 코드모드 성장 줄은 그대로 물려받음(다음 단계 prove 통과)", (out[-200:], out2[-300:]))
    sh(GIT, "-C", R6, "checkout", "-q", "--", "tools/y.py")
    with open(gp, "w", encoding="utf-8") as f:
        f.write(gl.replace('"commit": "시험 표시"', '"commit": "바꿈"'))
    rc, out = tool("prove", "--table", tab, "--root", R6, "--base", "HEAD")
    chk(rc == 1 and "범위 밖 파일의 코드모드 성장 줄이 기준과 다름" in out, "[6] 범위 밖 파일의 앞 단계 성장 줄을 바꾸면 prove 실패", out[-300:])
    with open(gp, "w", encoding="utf-8") as f:
        f.write(gl)
    put("src/big.py", "import common\nY = common.STATE_DIR\n" + "#" * 60000 + "\n")
    sh(GIT, "-C", R6, "add", "-A")
    sh(GIT, "-C", R6, "commit", "-qm", "shrink")
    rc, out = tool("apply", "--table", tab, "--root", R6, "--growth-commit", "s3", os.path.join(R6, "src/big.py"))
    rc2, out2 = tool("prove", "--table", tab, "--root", R6, "--base", "HEAD")
    chk(rc == 0 and rc2 == 0 and '"m": "big", "q": "<file>"' not in open(gp, encoding="utf-8").read(),
        "[6] 기준선 이하가 된 파일의 옛 코드모드 줄 = apply 가 지움 · prove 통과", (out[-200:], out2[-300:]))
    sh(GIT, "-C", R6, "checkout", "-q", "--", "src/big.py", "public/tests/arch_baseline/py_growth.jsonl")
    put("src/big.py", "import common\nY = common.STATE_DIR\n" + "#" * 70100 + "\n")
    with open(gp, "w", encoding="utf-8") as f:
        f.write("{깨진 줄\n")
    rc, out = tool("apply", "--table", tab, "--root", R6, "--growth-commit", "x", os.path.join(R6, "src/big.py"))
    chk(rc == 1 and "아무것도 쓰지 않음" in out and "common.STATE_DIR" in open(os.path.join(R6, "src", "big.py"), encoding="utf-8").read(),
        "[6] 성장 사유 표가 깨졌으면 소스도 안 씀", out[-300:])
    sh(GIT, "-C", R6, "checkout", "-q", "--", "public/tests/arch_baseline/py_growth.jsonl")
    os.chmod(gp, 0o444)
    rc, out = tool("apply", "--table", tab, "--root", R6, "--growth-commit", "x", os.path.join(R6, "src/big.py"), os.path.join(R6, "tools/y.py"))
    os.chmod(gp, 0o644)
    chk(rc == 1 and "아무것도 쓰지 않음" in out and "common.read_json" in open(os.path.join(R6, "tools", "y.py"), encoding="utf-8").read()
        and "common.STATE_DIR" in open(os.path.join(R6, "src", "big.py"), encoding="utf-8").read()
        and not any(f.startswith(".codemod_") for _d, _n, fs in os.walk(R6) for f in fs),
        "[6] 성장 표에 쓸 수 없으면(권한) 소스도 하나도 안 씀 · 임시 파일 0", out[-300:])
    rc, out = tool("census", "--root", R6)
    chk(rc == 1 and "[sh_dated] 1" in out and "[sh_live] 1" in out and "tools/live.sh:1" in out,
        "[6] census = 셸 heredoc 을 날짜 붙은 그 판 전용 / 목록 밖으로 나눔(목록 밖 있으면 종료 1)", out[-400:])

if GIT:
    R8 = os.path.join(T.TMP, "r8")
    shutil.copytree(R5 + "/public", R8 + "/public")
    for rel8, text8 in (("public/tests/arch_baseline/py_growth.jsonl", ""),
                        ("src/settings_store.py", '"""남는 저장소(옮긴 이름 없음)."""\nLOCK = 1\n'),
                        ("src/sw.py", '"""가짜 정의 모듈."""\n\n\ndef add_wallet(a):\n    return a\n'),
                        ("tools/k.py", "import os\nimport settings_store as ss  # noqa\n\n\ndef f():\n    return ss.add_wallet(1), ss.LOCK, os.sep\n"),
                        ("tools/k2.py", "import settings_store as ss\nY = ss.add_wallet, settings_store\n")):
        os.makedirs(os.path.dirname(os.path.join(R8, rel8)), exist_ok=True)
        with open(os.path.join(R8, rel8), "w", encoding="utf-8") as f:
            f.write(text8)
    tab8 = os.path.join(T.TMP, "tab8.json")
    with open(tab8, "w", encoding="utf-8") as f:
        json.dump({"sw": ["add_wallet"]}, f)
    sh(GIT, "-C", R8, "init", "-q")
    sh(GIT, "-C", R8, "add", "-A")
    sh(GIT, "-C", R8, "commit", "-qm", "base")
    rc, out = tool("apply", "--old", "settings_store", "--table", tab8, "--root", R8, "--growth-commit", "g8", os.path.join(R8, "tools/k.py"))
    k8 = open(os.path.join(R8, "tools", "k.py"), encoding="utf-8").read()
    rc2, out2 = tool("prove", "--old", "settings_store", "--table", tab8, "--root", R8, "--base", "HEAD", os.path.join(R8, "tools/k.py"))
    chk(rc == 0 and rc2 == 0 and k8 == "import os\nimport settings_store as ss, sw  # noqa\n\n\ndef f():\n    return sw.add_wallet(1), ss.LOCK, os.sep\n",
        "[8] --old 별칭: ss.add_wallet → sw.add_wallet · 그 줄 = import settings_store as ss, sw(줄 끝 주석 그대로) · prove 통과", (out[-300:], out2[-300:], k8))
    rc, out = tool("apply", "--old", "settings_store", "--table", tab8, "--root", R8, "--growth-commit", "g8", os.path.join(R8, "tools/k2.py"))
    chk(rc == 1 and "함께 나옴" in out and "ss.add_wallet" in open(os.path.join(R8, "tools", "k2.py"), encoding="utf-8").read(),
        "[8] 별칭과 옛 모듈 이름이 맨 이름으로 함께 나옴 = 파일째 거부(안 씀)", out[-300:])
    sh(GIT, "-C", R8, "checkout", "-q", "--", "tools/k.py")
    with open(os.path.join(R8, "src", "settings_store.py"), "a", encoding="utf-8") as f:
        f.write("\n\ndef add_wallet(a):\n    return a\n")
    rc, out = tool("plan", "--old", "settings_store", "--table", tab8, "--root", R8, os.path.join(R8, "tools/k.py"))
    chk(rc == 1 and "P2 src/settings_store.py 가 add_wallet 를 아직" in out, "[8] 옛 모듈이 옮긴 이름을 아직 묶음 = 전제 P2 실패", out[-300:])
    with contextlib.redirect_stdout(io.StringIO()):
        rc9 = C.main(["plan", "--old", "settings_store", "--table", tab8, "--root", R8, os.path.join(R8, "tools/k.py")])
    chk(rc9 == 1 and C.OLD == "common", "[8] 같은 프로세스 main(--old) 이 끝나면 OLD 는 common 으로 되돌아옴", (rc9, C.OLD))

OK9 = [("이어 받기(앞 단계 결과)", b"import common, paths  # noqa: E402\nY = common.read_json(paths.STATE_DIR)\n",
        b"import common, paths, statefile  # noqa: E402\nY = statefile.read_json(paths.STATE_DIR)\n"),
       ("뒤 이름 재사용 + 정렬", b"import common, paths, histmark\nY = common.STATE_DIR, common.read_json\n",
        b"import common, histmark, paths, statefile\nY = paths.STATE_DIR, statefile.read_json\n"),
       ("맨 위 묶음 `import paths` 재사용", b'"""d."""\nimport paths\nimport common\nY = common.STATE_DIR\n',
        b'"""d."""\nimport paths\nimport common\nY = paths.STATE_DIR\n'),
       ("맨 위 묶음 재사용(common 이 앞)", b"import common\nimport logs\n\n\ndef f(e):\n    return common.safe_err(e), logs.x\n",
        b"import common\nimport logs\n\n\ndef f(e):\n    return logs.safe_err(e), logs.x\n")]
for label, a9, b9 in OK9:
    r = C.rewrite("src/q9.py", a9, TAB)
    pr = C.prove("src/q9.py", a9, r.new, TAB)
    chk(r.new == b9 and not r.refused and pr["ok"], "[9] " + label, (r.new, r.refused, pr["why"]))
NO9 = [("뒤 이름이 기반 모듈 아님", b"import common, json\nY = common.STATE_DIR\n"),
       ("뒤 이름 별칭", b"import common, paths as p\nY = common.STATE_DIR\n"),
       ("뒤 이름이 다른 곳에서도 묶임", b"import common, paths\n\n\ndef f():\n    import paths\n    return common.STATE_DIR\n"),
       ("맨 위 묶음 밖 import M", b"import common\nX = 1\nimport paths\nY = common.STATE_DIR\n"),
       ("common 문장이 맨 위 묶음 밖", b"import paths\nX = 1\nimport common\nY = common.STATE_DIR\n"),
       ("뒤 이름 같은 것 둘", b"import common, paths, paths\nY = common.read_json\n"),
       ("줄 이음 괄호 꼴", b"import common, \\\n    paths\nY = common.read_json\n")]
for label, a9 in NO9:
    r = C.rewrite("src/q9.py", a9, TAB)
    chk(r.new == a9 and r.refused, "[9] 파일째 거부: " + label, r.refused)
if GIT:
    R9 = os.path.join(T.TMP, "r9")
    shutil.copytree(R5 + "/public", R9 + "/public")
    for rel9, text9 in (("src/paths.py", '"""가짜."""\nSTATE_DIR = "/tmp/x.invalid"\n'), ("src/statefile.py", '"""가짜."""\n\n\ndef read_json(p):\n    return p\n'),
                        ("src/histmark.py", '"""가짜."""\n'), ("src/common.py", '"""대리."""\nimport paths, statefile\n'),
                        ("tools/a9.py", "import common, paths\nY = common.read_json\n"), ("tools/b9.py", "import common, histmark\nY = common.read_json\n")):
        os.makedirs(os.path.dirname(os.path.join(R9, rel9)), exist_ok=True)
        with open(os.path.join(R9, rel9), "w", encoding="utf-8") as f:
            f.write(text9)
    tab9 = os.path.join(T.TMP, "tab9.json")
    with open(tab9, "w", encoding="utf-8") as f:
        json.dump({"statefile": ["read_json"]}, f)
    rc, out = tool("plan", "--table", tab9, "--root", R9, os.path.join(R9, "tools/a9.py"))
    rc2, out2 = tool("plan", "--table", tab9, "--root", R9, os.path.join(R9, "tools/b9.py"))
    chk(rc == 0 and "P4" not in out and rc2 == 1 and "P4 src/common.py 최상위가 histmark 를 import 하지 않음" in out2,
        "[9] 전제 P4: 뒤 이름을 common 이 맨 위에서 싣으면 통과 · 아니면(histmark) 실패", (out[-300:], out2[-300:]))
    for rel9, text9 in (("src/cfg9.py", '"""가짜 · 폐포에 동적 import."""\n\n\ndef load(p):\n    return __import__(p)\n'),
                        ("src/common.py", '"""대리."""\nimport cfg9, paths, statefile\n'), ("tools/c9.py", "import common\nY = common.load\n"),
                        ("src/n9.py", "import common\nY = common.go\n"), ("src/nn9.py", '"""가짜 · 동적."""\n\n\ndef go():\n    return __import__("x")\n')):
        with open(os.path.join(R9, rel9), "w", encoding="utf-8") as f:
            f.write(text9)
    tab9b = os.path.join(T.TMP, "tab9b.json")
    with open(tab9b, "w", encoding="utf-8") as f:
        json.dump({"cfg9": ["load"], "nn9": ["go"]}, f)
    rc, out = tool("plan", "--table", tab9b, "--root", R9, os.path.join(R9, "tools/c9.py"))
    rc2, out2 = tool("plan", "--table", tab9b, "--root", R9, os.path.join(R9, "src/n9.py"))
    chk(rc == 0 and "P3" not in out and rc2 == 1 and "P3 정의 모듈 nn9 의 import 폐포에 상대·동적" in out2,
        "[9] 전제 P3: common 이 맨 위에서 싣는 정의 모듈(묶기만)은 건너뜀 · 안 싣는 모듈(nn9)은 그대로 검사", (out[-300:], out2[-300:]))

tab7 = {"STATE_DIR": "paths", "DB_PATH": "paths", "CONFIG_PATH": "paths", "read_json": "statefile", "safe_err": "logs"}
KNOWN = ("import common 이 모듈 맨 위 단독 문장", "'common' 이 import 한 번 말고도 묶임", "정의 모듈 이름 '", "이름 공간 접근 철자", "from common import", "f-string", "주석(annotation)", "from … import *", "기반·metaclass")
bad7, ref7, n7 = [], [], 0
for rel in C.py_files(T.ROOT):
    data = open(os.path.join(T.ROOT, rel), "rb").read()
    r = C.rewrite(rel, data, tab7)
    ref7 += [w for _x, w in r.refused]
    if r.new != data:
        n7 += 1
        pr = C.prove(rel, data, r.new, tab7)
        if not pr["ok"]:
            bad7.append((rel, pr["why"]))
chk(not bad7, "[7] 지금 저장소 드라이런: 바꿀 파일 %d(4-6 일괄 교체 뒤 = 0) · 자기 증명 실패 0(파일은 안 씀)" % n7, bad7[:5])
chk(all(any(k in w for k in KNOWN) for w in ref7), "[7] 지금 저장소 거부 %d건 = 모두 알려진 갈래(지원 범위 밖 꼴)" % len(ref7),
    [w for w in ref7 if not any(k in w for k in KNOWN)][:5])
T.finish()
