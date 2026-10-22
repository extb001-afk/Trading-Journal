#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import os  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402

chk = T.chk
TOOLS = os.path.join(T.ROOT, "tools", "refactor")
if not os.path.isfile(os.path.join(TOOLS, "reexport_drop.py")):
    _pub = os.path.realpath(T.HERE) == os.path.realpath(os.path.join(T.ROOT, "tests"))
    chk(_pub, "공개판 배치 — 비공개 도구(tools/refactor/reexport_drop.py) 없음 · 건너뜀" if _pub else "저장소 배치인데 비공개 도구 없음(건너뛰지 않고 실패)")
    T.finish()
sys.path.insert(0, TOOLS)
import reexport_drop as RD  # noqa: E402

HUB = ('"""모음."""\nimport base\nfrom base import (  # noqa: F401 — 재수출\n    A,\n    B,\n    C,\n)\n'
       'from base import D, E  # 둘 다 안 씀\nfrom base import F as FF, G\n')
FILES = {
    "src/base.py": '"""바탕."""\nA = 1\nB = 2\nC = 3\nD = 4\nE = 5\nF = 6\nG = 7\nH = 8\n',
    "src/hub.py": HUB,
    "src/hub2.py": '"""한 줄 끝 주석."""\nimport base\nfrom base import C, D  # 끝 주석\n',
    "src/hub3.py": '"""쉼표 없는 마지막 항목 여러 줄."""\nimport base\nfrom base import (A,\n                  B)\n',
    "src/hub4.py": '"""dev 기록만 씀."""\nimport base\nfrom base import A, B\n',
    "src/exf_hub.py": '"""접두어 모음."""\nimport base\nfrom base import H, A as A2\n',
    "src/dup.py": '"""같은 이름 문 둘."""\nimport base\ntry:\n    from base import B, C\nexcept ImportError:\n    from base import B, C\n',
    "src/ms.py": '"""MODSET 대상."""\nimport base\nfrom base import E as E9, A as A9\n',
    "src/user2.py": '"""MODSET 쥔 쪽."""\nMODSET = (("ms", "E9"),)\n',
    "public/tests/test_fake_a.py": ('import hub\nprint(hub.B)\nfrom hub import G\nimport hub2, hub3, hub4\nprint(hub2.C, hub3.A, hub4.B)\n'
                                    'import exf_hub\nprint(exf_hub.A2)\nimport _harness as T\nT.patch_moved("H", 1, ("exf_",))\n'),
    "dev/2001/old.py": 'import hub4\nprint(hub4.A)\n',
}
DROP = {("hub", "A"), ("hub", "C"), ("hub", "FF"), ("hub2", "D"), ("hub3", "B"), ("exf_hub", "H"), ("ms", "A9")}

ROOTD = tempfile.mkdtemp(prefix="tj_rxdrop_", dir=T.TMP)
try:
    for rel, text in FILES.items():
        path = os.path.join(ROOTD, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    BASE = os.path.join(T.TMP, "tj_rxdrop_base_%d" % os.getpid())
    shutil.copytree(ROOTD, BASE)

    pl = RD.plan(ROOTD)
    got = {(d["module"], d["name"]) for d in pl["drop"]}
    keep = {(d["module"], d["name"]): d["reason"] for d in pl["keep"]}
    chk(got == DROP, "[1] 지울 이름 = 없음 + patch_moved 만(같은 문에 다른 이름이 남는 것만)", sorted(got ^ DROP))
    chk({d["class"] for d in pl["drop"] if d["module"] == "exf_hub"} == {"patch"}, "[1] patch_moved 글자만 쓰는 이름 = 갈래 patch", pl["drop"])
    chk("비게 됨" in keep.get(("hub", "D"), "") and "비게 됨" in keep.get(("hub", "E"), ""),
        "[1] 문의 지울 이름을 다 지우면 문이 빔 = 둘 다 남김(로드 차례 보존)", [keep.get(("hub", "D")), keep.get(("hub", "E"))])
    chk("쓰는 곳" in keep.get(("hub", "B"), "") and "쓰는 곳" in keep.get(("hub", "G"), "") and "쓰는 곳" in keep.get(("exf_hub", "A2"), ""),
        "[1] 시험이 읽는 이름(hub.B · from hub import G · exf_hub.A2) = 남김", keep)
    chk("문 2개" in keep.get(("dup", "B"), ""), "[1] 같은 이름을 묶는 문이 둘(try/except) = 남김", keep.get(("dup", "B")))
    chk(keep.get(("ms", "E9")) == "MODSET/MODDICT 쌍", "[1] MODSET 쌍이 가리키는 이름 = 남김", keep.get(("ms", "E9")))
    chk("쓰는 곳" in keep.get(("hub4", "A"), ""), "[1] dev/<날짜> 기록이 쓰는 이름 = 기본 남김", keep.get(("hub4", "A")))
    pld = RD.plan(ROOTD, ("none", "patch", "dated"))
    chk(any(d["module"] == "hub4" and d["name"] == "A" and d["class"] == "dated" for d in pld["drop"]),
        "[1] --classes dated = dev/<날짜> 기록만 쓰는 이름도 지움(갈래 dated)", [d for d in pld["drop"] if d["module"] == "hub4"])

    n, notes = RD.apply(ROOTD, pl)
    rd = lambda rel: open(os.path.join(ROOTD, rel), encoding="utf-8").read()  # noqa: E731
    chk(n == len(DROP), "[2] apply 지운 수 = plan", n)
    chk(rd("src/hub.py") == ('"""모음."""\nimport base\nfrom base import (  # noqa: F401 — 재수출\n    B,\n)\n'
                             'from base import D, E  # 둘 다 안 씀\nfrom base import G\n'),
        "[2] 괄호 여러 줄의 줄 통째 지움 · 머리 주석 그대로 · as 별칭(F as FF) 지움", rd("src/hub.py"))
    chk(rd("src/hub2.py").endswith("from base import C  # 끝 주석\n"), "[2] 한 줄 마지막 항목 = 앞 쉼표와 함께 · 끝 주석 그대로", rd("src/hub2.py"))
    chk(rd("src/hub3.py").endswith("from base import (A\n                  )\n"), "[2] 쉼표 없는 마지막 항목(다른 줄) = 앞 쉼표·그 이름만", rd("src/hub3.py"))
    chk(rd("src/exf_hub.py").endswith("from base import A as A2\n") and rd("src/ms.py").endswith("from base import E as E9\n"),
        "[2] 첫 항목 지움(쉼표 뒤 공백까지)", [rd("src/exf_hub.py"), rd("src/ms.py")])
    try:
        RD.drop_text(rd("src/hub.py"), {(6, 0): {"D", "E"}})
        err = ""
    except ValueError as e:
        err = str(e)
    chk("문이 빔" in err, "[2] 문이 통째로 비는 지움 = ValueError(쓰지 않음)", err)

    res = RD.verify(ROOTD, BASE, pl=pl)
    chk(not res["fails"] and res["deleted"] == len(DROP) and res["hand_files"] == [], "[3] apply 결과 verify 통과 · 지운 수 = plan", res)
    with open(os.path.join(ROOTD, "public", "tests", "test_fake_b.py"), "w", encoding="utf-8") as f:
        f.write("import hub\nprint(hub.C)\n")
    res = RD.verify(ROOTD, BASE, pl=pl)
    chk(any(x.startswith("③hub.C") for x in res["fails"]), "[3] 지운 이름을 다시 쓰면 실패(③)", res["fails"])
    os.remove(os.path.join(ROOTD, "public", "tests", "test_fake_b.py"))
    with open(os.path.join(ROOTD, "src", "hub2.py"), "a", encoding="utf-8") as f:
        f.write("X = 1\n")
    res = RD.verify(ROOTD, BASE, pl=pl)
    chk(res["hand_files"] == ["src/hub2.py"] and not res["fails"], "[3] 별칭 말고 다른 변경 = 손 변경 파일(지운 이름은 그대로 셈)", res)
    pl2 = dict(pl, drop=[d for d in pl["drop"] if d["name"] != "FF"])
    res = RD.verify(ROOTD, BASE, pl=pl2)
    chk(any(x.startswith("⑤") for x in res["fails"]), "[3] 지운 집합 ≠ plan = 실패(⑤)", res["fails"])

    with open(os.path.join(ROOTD, "src", "m1.py"), "w", encoding="utf-8") as f:
        f.write("import m2\n")
    with open(os.path.join(ROOTD, "src", "m2.py"), "w", encoding="utf-8") as f:
        f.write("import m3\n")
    with open(os.path.join(ROOTD, "src", "m3.py"), "w", encoding="utf-8") as f:
        f.write("X = 1\n")
    for name in ("m1.py", "m2.py", "m3.py"):
        shutil.copy(os.path.join(ROOTD, "src", name), os.path.join(BASE, "src", name))
    with open(os.path.join(ROOTD, "src", "m2.py"), "w", encoding="utf-8") as f:
        f.write("X = 2\n")
    it = RD.importtime_ab(ROOTD, BASE, entries=[("u1", "src/m1.py")])
    chk(it["u1"]["missing"] == ["m3"] and it["u1"]["rc"] == [0, 0], "[4] 작업 트리에서 새로 빠진 모듈(m3) 을 잡음", it)
finally:
    shutil.rmtree(ROOTD, ignore_errors=True)
    shutil.rmtree(os.path.join(T.TMP, "tj_rxdrop_base_%d" % os.getpid()), ignore_errors=True)
T.finish()
