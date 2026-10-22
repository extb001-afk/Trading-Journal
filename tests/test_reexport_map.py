#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402

chk = T.chk
TOOLS = os.path.join(T.ROOT, "tools", "refactor")
if not os.path.isfile(os.path.join(TOOLS, "reexp_map.py")):
    _pub = os.path.realpath(T.HERE) == os.path.realpath(os.path.join(T.ROOT, "tests"))
    chk(_pub, "공개판 배치 — 비공개 도구(tools/refactor/reexp_map.py) 없음 · 건너뜀" if _pub else "저장소 배치인데 비공개 도구 없음(건너뛰지 않고 실패)")
    T.finish()
sys.path.insert(0, TOOLS)
import reexp_map as RM  # noqa: E402

FILES = {
    "src/base.py": '"""바탕."""\nA = 1\nB = 2\nC = 3\nD = 4\nE = 5\nF = 6\nG = 7\nH = 8\n',
    "src/other.py": '"""다른 바탕."""\nJ = 1\nK = 2\n',
    "src/hub.py": '"""모음."""\nimport base\nfrom base import A, B, C, D, E, F, G, H\n',
    "src/solo.py": '"""혼자."""\nfrom other import J\n',
    "src/lone.py": '"""외톨이."""\nfrom other import K\n',
    "src/user.py": '"""쓰는 쪽."""\nimport hub\n\n\ndef f():\n    return hub.C\n',
    "tools/t_set.py": 'import hub as h\nh.D = 1\n',
    "public/tests/test_fake_a.py": 'import hub\nsetattr(hub, "E", 2)\nfor n in ("F",):\n    getattr(hub, n)\n',
    "public/tests/test_fake_b.py": 'from unittest import mock\nfrom hub import H\nmock.patch("hub.G", 1)\n',
    "public/tests/test_fake_c.py": 'import _h\nh2 = _h.hub\nh3 = h2\nprint(h3.B)\n',
    "src/third.py": '"""셋째 바탕."""\nX1 = 1\nX2 = 2\n',
    "src/hub2.py": '"""조건 import 모음."""\nTYPE_CHECKING = False\nif TYPE_CHECKING:\n    import third\nfrom third import X1, X2\n',
    "src/fourth.py": '"""넷째 바탕."""\nY1 = 1\nY2 = 2\n',
    "src/hub3.py": '"""try·with 안 import."""\nimport contextlib\ntry:\n    import missing_opt\n    import fourth\nexcept ImportError:\n    pass\nwith contextlib.suppress(ImportError):\n    import missing_two\n    import fourth\nfrom fourth import Y1\n',
    "src/brokers/__init__.py": '',
    "src/brokers/bbase.py": '"""패키지 바탕."""\nZ1 = 1\nZ2 = 2\n',
    "src/brokers/bhub2.py": '"""패키지 모음 둘."""\nimport brokers.bbase\nfrom .bbase import Z2\n',
    "public/tests/test_fake_g.py": 'import brokers.bhub2\nprint(brokers.bhub2.Z2)\n',
    "src/sixth.py": '"""여섯째 바탕."""\nU1 = 1\nU2 = 2\nR1 = 3\nR2 = 4\n',
    "src/hub7.py": '"""모음 일곱."""\nimport sixth\nfrom sixth import U1, U2\n',
    "src/hub8.py": '"""모음 여덟."""\nimport sixth\nfrom sixth import R1, R2\n',
    "public/tests/test_fake_h.py": 'import hub7\n\n\ndef rd(prefix, name, *rest):\n    return getattr(hub7, name)\n\n\nrd(*("p", "U2"), "U1")\n',
    "src/seventh.py": '"""일곱째 바탕."""\nG1 = 1\nP1 = 2\nP2 = 3\nS1 = 4\nM1 = 5\n',
    "src/hub9.py": '"""자기 globals 글자."""\nimport seventh\nfrom seventh import G1\n\n\ndef f():\n    return globals()["G1"]\n',
    "src/exf_hub.py": '"""접두어 모음."""\nimport seventh\nfrom seventh import P1, P2\n',
    "src/hub10.py": '"""묶음으로 빠지는 모음."""\nimport seventh\nfrom seventh import S1, M1\n',
    "public/tests/test_fake_j.py": 'import _harness as T\nT.patch_moved("P1", 1, ("exf_",))\nfor _n in ("P2",):\n    T.patch_moved(_n, 2, ("exf_",))\n',
    "public/tests/test_fake_k.py": 'import hub10\ngetattr(*(hub10, "S1"))\nfor m in (hub10,):\n    print(m.M1)\n',
    "src/tenth.py": '"""열째 바탕."""\nT1 = 1\nT2 = 2\nT3 = 3\nT4 = 4\nT5 = 5\nT6 = 6\n',
    "src/exf_hub2.py": '"""접두어 모음 둘."""\nimport tenth\nfrom tenth import T1, T2, T3\n',
    "public/tests/test_fake_p.py": ('import _harness as T\nsaved = (1, 2)\nfor _n9, _v9 in zip(("T1", "T2"), saved):\n'
                                    '    T.patch_moved(_n9, _v9, ("exf_",))\n'),
    "src/hub17.py": '"""튜플 대상 모름."""\nimport tenth\nfrom tenth import T4, T5\n',
    "public/tests/test_fake_q.py": ('import hub17\nfor i, nm in enumerate(("T4",)):\n    getattr(hub17, nm)\n'
                                    'for nm2, v in pairs():\n    getattr(hub17, nm2)\n'),
    "src/hub18.py": '"""dict.items 풀이."""\nimport tenth\nfrom tenth import T6\n',
    "public/tests/test_fake_r.py": 'import hub18\nfor k, v in {"T6": 1}.items():\n    getattr(hub18, k)\n',
    "src/eighth.py": '"""여덟째 바탕."""\nK1 = 1\nK2 = 2\nN1 = 3\nB1 = 4\nE1 = 5\n',
    "src/hub11.py": '"""다른 파일이 부르는 읽기 함수."""\nimport eighth\nfrom eighth import K1, K2\n',
    "tools/reader.py": 'import hub11\n\n\ndef read_k(name):\n    return getattr(hub11, name)\n\n\nread_k("K1")\n',
    "public/tests/test_fake_l.py": 'from reader import read_k\nread_k("K2")\n',
    "src/hub12.py": '"""globals 를 담음."""\nimport eighth\nfrom eighth import N1\nns = globals()\n\n\ndef f():\n    return ns["N1"]\n',
    "src/hub13.py": '"""속성에 담기는 모음."""\nimport eighth\nfrom eighth import B1\n',
    "public/tests/test_fake_m.py": 'import hub13\n\n\nclass Box:\n    pass\n\n\nbox = Box()\nbox.mod = hub13\nprint(box.mod.B1)\n',
    "src/hub14.py": '"""BOM 소비자."""\nimport eighth\nfrom eighth import E1\n',
    "public/tests/test_fake_n.py": '\ufeffimport hub14\nprint(hub14.E1)\n',
    "src/ninth.py": '"""아홉째 바탕."""\nQ1 = 1\nQ2 = 2\nH1 = 3\n',
    "src/hub15.py": '"""패키지 읽기 함수가 부르는 모음."""\nimport ninth\nfrom ninth import Q1, Q2\n',
    "src/brokers/breader.py": '"""패키지 읽기 함수."""\nimport hub15\n\n\ndef read_p(name):\n    return getattr(hub15, name)\n\n\nread_p("Q1")\n',
    "public/tests/test_fake_o.py": 'import brokers.breader\nbrokers.breader.read_p("Q2")\n',
    "src/hub16.py": '\ufeff"""BOM 붙은 모음."""\nimport ninth\nfrom ninth import H1\n',
    "public/tests/test_fake_i.py": 'import hub8\nfor name in ("R1",):\n    getattr(hub8, name)\nfrom sel import KEY as name\ngetattr(hub8, name)\n',
    "src/brokers/bhub.py": '"""패키지 모음."""\nimport brokers.bbase\nfrom .bbase import Z1\n',
    "src/brokers/buser.py": '"""패키지 안 쓰는 쪽."""\nfrom .bhub import Z1\n\n\ndef f():\n    return Z1\n',
    "src/fifth.py": '"""다섯째 바탕."""\nW1 = 1\nW2 = 2\nV1 = 3\n',
    "src/hub5.py": '"""모음 다섯."""\nimport fifth\nfrom fifth import W1, W2\n',
    "src/hub6.py": '"""모음 여섯."""\nimport fifth\nfrom fifth import V1\n',
    "public/tests/test_fake_f.py": ('import hub5\nimport hub6\n\n\ndef rd(name):\n    return getattr(hub5, name)\n\n\nreader = rd\nrd("W1")\nreader("W2")\n'
                                    'for n in ("V9",):\n    pass\nfor n, value in [("V1", 1)]:\n    getattr(hub6, n)\n'),
    "src/hub4.py": '"""모음 넷."""\nimport fourth\nfrom fourth import Y2\n',
    "public/tests/test_fake_e.py": ('def left():\n    import hub4 as m\n    return m.Y2\n\n\ndef right():\n    import hub2 as m\n    return m.X1\n'),
    "public/tests/test_fake_d.py": 'import hub2\nfor name in ("Q",):\n    pass\n\n\ndef read(name):\n    return getattr(hub2, name)\n\n\nread("X2")\n',
    "dev/2001/old.py": 'import hub\nname = input()\ngetattr(hub, name)\n',
    "dev/refactor/probe.py": 'import lone\nprint(vars(lone))\n',
    "public/tests/arch_baseline/py_rules.json": '{"src_packages": ["brokers"]}\n',
    "public/tests/arch_baseline/py_imports.jsonl": '{"k":"import.reexport","m":"hub","q":"A","v":1}\n',
}

ROOTD = tempfile.mkdtemp(prefix="tj_reexp_map_", dir=T.TMP)
try:
    for rel, text in FILES.items():
        path = os.path.join(ROOTD, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    data = RM.build(ROOTD)
    items = {(d["module"], d["name"]): d for d in data["items"]}
    cat = {k: d["cat"] for k, d in items.items()}

    chk(set(items) == {("hub", x) for x in "ABCDEFGH"} | {("solo", "J"), ("lone", "K"), ("hub2", "X1"), ("hub2", "X2"), ("hub3", "Y1"), ("hub4", "Y2"), ("brokers.bhub", "Z1"), ("hub5", "W1"), ("hub5", "W2"), ("hub6", "V1"),
                         ("brokers.bhub2", "Z2"), ("hub7", "U1"), ("hub7", "U2"), ("hub8", "R1"), ("hub8", "R2"),
                         ("hub9", "G1"), ("exf_hub", "P1"), ("exf_hub", "P2"), ("hub10", "S1"), ("hub10", "M1"),
                         ("hub11", "K1"), ("hub11", "K2"), ("hub12", "N1"), ("hub13", "B1"), ("hub14", "E1"),
                         ("hub15", "Q1"), ("hub15", "Q2"), ("hub16", "H1"),
                         ("exf_hub2", "T1"), ("exf_hub2", "T2"), ("exf_hub2", "T3"), ("hub17", "T4"), ("hub17", "T5"), ("hub18", "T6")},
        "[1] 재수출 = hub 의 from import 8 + solo J + lone K(쓰는 이름·맨 import 는 아님)", sorted(items))
    chk(all(items[("hub", x)]["defined_in"] == "base" for x in "ABCDEFGH"), "[1] 정의 모듈 = base", None)

    chk(cat[("hub", "A")] == "없음", "[2] 아무도 안 쓰는 이름 = 없음(앞 import base 가 실음 → 부작용 아님)",
        [items[("hub", "A")]])
    chk(cat[("hub", "B")] == "시험", "[2] 다른 객체 속성으로 받은 모듈(_h.hub)의 별칭의 별칭 읽기 = 시험", items[("hub", "B")]["uses"])
    chk(cat[("hub", "C")] == "src", "[2] 다른 src 가 hub.C 를 읽음 = src", items[("hub", "C")]["uses"])
    chk(cat[("hub", "D")] == "도구" and items[("hub", "D")]["write_only"], "[2] tools 의 별칭 대입만 = 도구 · write_only",
        items[("hub", "D")])
    chk(cat[("hub", "E")] == "시험" and any("글자" in u for u in items[("hub", "E")]["uses"]),
        "[2] setattr(모듈, 글자) = 시험(글자)", items[("hub", "E")]["uses"])
    chk(cat[("hub", "F")] == "시험" and any("변수 풀이" in u for u in items[("hub", "F")]["uses"]),
        "[2] for 상수 묶음 변수로 getattr = 그 글자로 풀어 시험", items[("hub", "F")]["uses"])
    chk(cat[("hub", "G")] == "시험", "[2] 점 글자 'hub.G'(mock.patch 류) = 시험", items[("hub", "G")]["uses"])
    chk(cat[("hub", "H")] == "시험" and any(" from" in u for u in items[("hub", "H")]["uses"]),
        "[2] from hub import H = 시험", items[("hub", "H")]["uses"])

    chk(cat[("solo", "J")] == "부작용" and "other" in items[("solo", "J")]["why"],
        "[3] 문이 통째로 비고 앞 import 가 대상 모듈을 안 실음 = 부작용", items[("solo", "J")])
    chk(cat[("lone", "K")] == "모름" and "vars" in items[("lone", "K")]["why"],
        "[3] vars(모듈) 이 있는 모듈 = 모름(부작용보다 먼저)", items[("lone", "K")])

    chk(cat[("hub2", "X1")] == "부작용", "[3] if 가지 안 import(TYPE_CHECKING)는 '이미 실음'으로 안 셈 → 부작용", items[("hub2", "X1")])
    chk(items[("hub2", "X2")]["pre_cat"] == "시험" and any("변수 풀이" in u for u in items[("hub2", "X2")]["uses"]), "[3] 반복 변수와 함수 인자 이름이 같아도 인자 글자(X2)까지 합쳐 풂", items[("hub2", "X2")]["uses"])

    chk(cat[("hub3", "Y1")] == "부작용", "[3] try·with(suppress) 안 import(앞 문장이 실패하면 안 돎)는 '이미 실음'으로 안 셈 → 부작용", items[("hub3", "Y1")])
    chk(cat[("hub4", "Y2")] == "시험", "[3] 함수마다 같은 별칭 이름(m)이 다른 모듈 = 둘 다로 봄(덮어쓰지 않음)", items[("hub4", "Y2")]["uses"])

    chk(cat[("brokers.bhub", "Z1")] == "src", "[3] 패키지 안 상대 import(from .bhub import Z1) = 쓰는 곳", items[("brokers.bhub", "Z1")])
    chk(cat[("hub5", "W2")] == "모름", "[3] 함수 이름을 다른 이름으로 부름(reader = rd) = 인자 못 풂 → 모름", items[("hub5", "W2")])
    chk(cat[("hub6", "V1")] == "시험" and any("변수 풀이" in u for u in items[("hub6", "V1")]["uses"]),
        "[3] 튜플 대상 for(n, v) 가 상수 묶음의 묶음을 돎 = 자리별 글자(V1)까지 합쳐 풂(다른 반복 글자 V9 만으로 풀지 않음)", items[("hub6", "V1")])
    chk(cat[("brokers.bhub2", "Z2")] == "시험", "[3] import brokers.bhub2 뒤 brokers.bhub2.Z2(패키지 점 경로) = 쓰는 곳", items[("brokers.bhub2", "Z2")])
    chk(cat[("hub7", "U2")] == "모름" and cat[("hub7", "U1")] == "모름", "[3] 펼친 인자 rd(*(…), 'U1') = 자리 못 정함 → 모름(추측 금지)",
        [items[("hub7", "U1")], items[("hub7", "U2")]])
    chk(cat[("hub9", "G1")] == "src", "[3] 재수출 모듈 자신의 globals()['G1'] = 쓰는 곳", items[("hub9", "G1")])
    chk(cat[("exf_hub", "P1")] == "시험" and cat[("exf_hub", "P2")] == "시험",
        "[3] patch_moved 접두어 인자(('exf_',)) · 반복 변수 이름 = 그 접두어 모듈의 쓰는 곳", [items[("exf_hub", "P1")], items[("exf_hub", "P2")]])
    chk(cat[("hub10", "S1")] == "모름" and cat[("hub10", "M1")] == "모름",
        "[3] 모듈을 묶음에 넣음(getattr(*(m, …)) · for m in (m,)) = 모름", [items[("hub10", "S1")], items[("hub10", "M1")]])
    chk(cat[("hub11", "K2")] == "모름", "[3] 다른 파일이 from import 해 부르는 함수의 인자 = 못 풂 → 모름", items[("hub11", "K2")])
    chk(cat[("hub12", "N1")] == "모름", "[3] 모듈 자신의 globals() 를 이름에 담음 = 모름", items[("hub12", "N1")])
    chk(cat[("hub13", "B1")] == "모름", "[3] 모듈을 속성에 대입(box.mod = 모듈) = 모름", items[("hub13", "B1")])
    chk(cat[("hub14", "E1")] == "시험", "[3] BOM 붙은 소비자도 읽음(파이썬이 읽는 대로)", items[("hub14", "E1")])
    chk(cat[("hub15", "Q2")] == "모름", "[3] 다른 파일이 패키지 점 경로(brokers.breader.read_p)로 부르는 함수의 인자 = 못 풂 → 모름", items[("hub15", "Q2")])
    chk(cat[("hub16", "H1")] == "없음" and data["summary"]["unparsed"] == [], "[3] BOM 붙은 재수출 모듈도 정의를 읽음(빠지지 않음)", items[("hub16", "H1")])
    chk(cat[("hub8", "R2")] == "모름", "[3] import 로 다시 묶인 반복 변수 이름 = 못 풂 → 모름", items[("hub8", "R2")])

    chk(cat[("exf_hub2", "T1")] == "시험" and cat[("exf_hub2", "T2")] == "시험"
        and any("patch_moved" in u for u in items[("exf_hub2", "T1")]["uses"]),
        "[2b] for _n, _v in zip(상수 글자, 값): patch_moved(_n, …) = 그 글자들로 풀어 시험", [items[("exf_hub2", "T1")], items[("exf_hub2", "T2")]])
    chk(cat[("exf_hub2", "T3")] == "없음", "[2b] zip 상수 묶음에 없는 이름 = 없음(넓게 잡지 않음)", items[("exf_hub2", "T3")])
    chk(cat[("hub17", "T4")] == "모름" and cat[("hub17", "T5")] == "모름" and "getattr(변수)" in items[("hub17", "T5")]["why"],
        "[2b] enumerate 는 풀어도 같은 모듈에 상수 아닌 묶음(pairs())을 도는 튜플 대상 getattr 이 있으면 모름", [items[("hub17", "T4")], items[("hub17", "T5")]])
    chk(cat[("hub18", "T6")] == "시험", "[2b] 상수 dict.items() 의 열쇠 자리 = 풀어 시험", items[("hub18", "T6")])

    s = data["summary"]
    chk("hub" in s["dev_dated_dynamic"] and "hub" not in s["unknown_modules"],
        "[4] dev/<숫자>/ 기록 스크립트의 변수 getattr = 요약에만(모름 아님)", [s["dev_dated_dynamic"], s["unknown_modules"]])
    chk("lone" in s["unknown_modules"], "[4] dev/refactor 의 vars() 는 도구로 셈 → 모름", s["unknown_modules"])

    chk(sum(s["by_cat"].values()) == s["total"] == 42, "[5] 갈래 합 = 전체 42", s["by_cat"])
    chk(RM.baseline_total(ROOTD) == 1, "[5] 기준선 import.reexport 합 읽기", RM.baseline_total(ROOTD))
    o1, o2 = os.path.join(ROOTD, "o1.json"), os.path.join(ROOTD, "o2.json")
    rc1 = RM.main(["--root", ROOTD, "--out", o1])
    rc2 = RM.main(["--root", ROOTD, "--out", o2])
    with open(o1, "rb") as f1, open(o2, "rb") as f2:
        b1, b2 = f1.read(), f2.read()
    chk(rc1 == rc2 == 0 and b1 == b2 and json.loads(b1)["summary"]["total"] == 42, "[5] --out 두 번 = 같은 바이트(결정적)", [rc1, rc2])
    chk(RM.main(["--bad"]) == 2, "[5] 모르는 인자 = rc 2", None)
    with open(os.path.join(ROOTD, "tools", "broken.py"), "w", encoding="utf-8") as f:
        f.write("def (\n")
    with open(os.path.join(ROOTD, "src", "hub_bad.py"), "w", encoding="utf-8") as f:
        f.write("from ninth import Q1\ndef (\n")
    rc3 = RM.main(["--root", ROOTD, "--out", o1])
    up = RM.build(ROOTD)["summary"]["unparsed"]
    chk(rc3 == 1 and "tools/broken.py(SyntaxError)" in up and any(u.startswith("src/hub_bad.py(정의") for u in up),
        "[5] 못 읽는 파일이 있으면 지도 불완전 = rc 1(조용히 건너뛰지 않음)", rc3)
finally:
    shutil.rmtree(ROOTD, ignore_errors=True)
T.finish()
