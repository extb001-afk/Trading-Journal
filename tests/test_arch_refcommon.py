#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import _arch_ratchet as R  # noqa: E402
import _arch_refcommon as RC  # noqa: E402

chk = T.chk
D = R._doc
S = RC.SPEC

src = ("import json, common\nimport common as cm\nfrom common import seed_merge\n"
       "x = common.STATE_DIR\ncommon.DB_PATH = 'a'\ndel cm.CFG\n"
       "def f():\n    import common\n    return common.read_json(json.dumps(1)), json.loads('1')\n")
got = RC.count_py(src)
chk(got == {"attr": 4, "imp": 4}, "[0] 속성 4(읽기·대입·삭제·함수 안 · 별칭 cm) · import 4(줄 안 별칭·as 별칭·from·함수 안) · json.* 은 셈 밖", got)
got = RC.count_py("import importlib\nm = importlib.import_module('common')\nn = __import__('common')\nk = importlib.import_module('paths')\n")
chk(got == {"attr": 0, "imp": 2}, "[0] import_module('common')·__import__('common') = import 자리 · 다른 이름은 셈 밖", got)
got = RC.count_py("def f():\n    import bf_engine as _b9\n    return _b9.common.read_capped, _b9.other\n")
chk(got == {"attr": 1, "imp": 0}, "[0] 다른 모듈을 거친 F.common(import F as x 의 x.common) = 속성 참조", got)
got = RC.count_py("import paths\nimport commons\nx = paths.STATE_DIR\ncommon = 1\ny = common.real\n")
chk(got == {"attr": 0, "imp": 0}, "[0] common 을 import 하지 않은 파일의 같은 이름 변수·비슷한 모듈 이름 = 셈 밖", got)
got = RC.count_py("from importlib import import_module as load\nimport importlib\nc = load('common')\nd = importlib.import_module(name='common')\n")
chk(got == {"attr": 0, "imp": 2}, "[0] import_module 별칭(from importlib import … as load) · name= 키워드 = import 자리", got)
got = RC.count_py("from builtins import __import__ as load\nc = load('common')\nfrom bf_engine import common as cm\n")
chk(got == {"attr": 0, "imp": 2}, "[0] builtins.__import__ 별칭 · from F import common(F 를 거친 common) = import 자리", got)
chk(RC.count_sh("python3 - <<'PY'\nimport os, \\\n    common\nPY\n") == {"sh": 1}, "[0] 셸 줄 이음(\\ 줄바꿈)으로 나뉜 import common 도 셈")
chk(RC._may_refer("import importlib\nm = importlib.import_module('com' 'mon')\n") and RC._may_refer("import \uff43ommon\n")
    and not RC._may_refer("import json\n"), "[0] 빠른 거르기 = 쪼갠 글자·동적 import·유니코드 정규화 철자는 건너뛰지 않음")
u = "import importlib as i\nm = i.\uff49\uff4d\uff50\uff4f\uff52\uff54_\uff4d\uff4f\uff44\uff55\uff4c\uff45('com' 'mon')\n"
chk(RC._may_refer(u) and RC.count_py(u) == {"attr": 0, "imp": 1}, "[0] 전각 글자 import_module(NFKC 로 접힘) + 쪼갠 글자 'common' = 거르지 않고 import 자리로 셈")
chk(RC.count_sh("python3 - <<'PY'\nimport \uff43ommon\nPY\n") == {"sh": 1}, "[0] 셸 heredoc 의 유니코드 철자 import ｃommon(NFKC 로 common) 도 셈")
chk(RC.count_py("def (:\n").get("err") == 1, "[0] 파싱 실패 = err 표시(조용히 0 으로 안 셈)")
sh = "cat <<'PY' | python3 -\nimport common\nfrom common import x\nimport commonx\nimport os, sys as s9, common\nPY\n# import common 주석도 셈\n"
chk(RC.count_sh(sh) == {"sh": 4}, "[0] 셸 heredoc 의 import common(여러 이름 줄 포함) · from common import 줄(낱말 경계)", RC.count_sh(sh))

bad, stale = R.compare(S, D({"src/a.py": {"attr": 3, "imp": 1}, "src/new.py": {"attr": 1, "imp": 1}, "src/b.py": {"attr": 1, "imp": 1}}),
                       D({"src/a.py": {"attr": 2, "imp": 1}, "src/b.py": {"attr": 5, "imp": 1}, "src/gone.py": {"attr": 9, "imp": 1}}))
chk(len(bad) == 2 and any("src/a.py: attr 2→3" in x for x in bad) and any("src/new.py: 새 위반" in x for x in bad),
    "[R] 파일 값이 늘거나 새 파일 = 실패", bad)
chk(any("src/b.py: attr 5→1" in x for x in stale) and any("src/gone.py" in x for x in stale), "[R] 줄거나 사라진 파일 = 안내(기준선 조이기)", stale)
chk(R.SPECS.get(S.name) is S and R.parse(S, R.dump(S, D({"tools/x.sh": {"sh": 2}})))["items"] == {"tools/x.sh": {"attr": 0, "imp": 0, "sh": 2}},
    "[R] G0b 엔진에 지표 등록 · JSON Lines 왕복")

if not R.repo_layout():
    chk(True, "[1] 공개판 배치 — tools 가 일부만이라 기준선 비교 건너뜀")
    T.finish()
sc = RC.scan(R._root())
errs = sorted(k for k, v in sc.items() if v.get("err"))
chk(not errs, "[1] 셈 대상 파일 전부 파싱됨", errs[:10])
cur = RC.current(R._root())
print("  합계: " + " · ".join("%s %d" % kv for kv in RC.totals(cur).items()) + " · 파일 %d" % len(cur["items"]))
R.check(T, R._root(), {S.name: cur})
T.finish()
