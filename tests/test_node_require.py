#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

chk = T.chk
OWNERS = {"_harness.py", "_arch_js_acorn.py"}


def _which_node_calls(path):
    tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    out = []
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "which" and n.args
                and isinstance(n.args[0], ast.Constant) and n.args[0].value == "node"):
            out.append(n.lineno)
    return out


direct = {}
for fn in sorted(os.listdir(T.HERE)):
    if fn.endswith(".py") and fn not in OWNERS:
        lines = _which_node_calls(os.path.join(T.HERE, fn))
        if lines:
            direct[fn] = lines
chk(not direct, "N1 시험 파일이 node 를 직접 찾지 않음(공용 입구 _harness.node_bin 만 — 스위치를 따름)", direct)
chk(all(_which_node_calls(os.path.join(T.HERE, f)) for f in OWNERS if os.path.isfile(os.path.join(T.HERE, f))),
    "N1 공용 입구·acorn 도구는 그대로 node 를 찾음(검사 대상이 살아 있음)")

EMPTY = os.path.join(T.TMP, "nopath")
os.makedirs(EMPTY, exist_ok=True)
CHILD = os.path.join(T.TMP, "node_child.py")
with open(CHILD, "w", encoding="utf-8") as f:
    f.write(r'''
import os, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
mode = sys.argv[2]
if mode == "alias":
    import _sec_lint as L
import _harness as T
if mode == "alias":
    print("got=%r" % (L.require_node(T, "합성 시험"),))
elif mode == "unusable":
    T.node_unusable("합성 대조", "내장 acorn 을 못 부름(합성)")
else:
    print("got=%r" % (T.node_bin("합성 시험"),))
T.finish()
''')
BASE_ENV = {k: v for k, v in os.environ.items() if not k.startswith("TJ_")}


def child(mode, path, **env):
    e = dict(BASE_ENV, PATH=path, **env)
    p = subprocess.run([sys.executable, CHILD, T.HERE, mode], capture_output=True, text=True, timeout=120, env=e)
    return p.returncode, p.stdout + p.stderr


rc, out = child("bin", EMPTY, TJ_TEST_REQUIRE_NODE="1")
chk(rc == 1 and "FAIL node 없음 — 합성 시험 못 돌림(TJ_TEST_REQUIRE_NODE=1)" in out and "got=None" in out,
    "N2 node 없는 PATH + 스위치 = FAIL · 경로 None", out[-600:])
rc, out = child("bin", EMPTY)
chk(rc == 0 and "SKIP node 없음 — 합성 시험 건너뜀" in out and "got=None" in out and not any(x.startswith("FAIL") for x in out.splitlines()),
    "N2 node 없는 PATH + 스위치 없음 = SKIP 줄 · rc 0", out[-600:])
rc, out = child("unusable", os.environ.get("PATH", ""), TJ_TEST_REQUIRE_NODE="1")
chk(rc == 1 and "FAIL 내장 acorn 을 못 부름(합성) — 합성 대조 못 돌림" in out, "N2 node 를 못 씀(acorn 로드 실패) + 스위치 = FAIL", out[-600:])
rc, out = child("unusable", os.environ.get("PATH", ""))
chk(rc == 0 and "SKIP 내장 acorn 을 못 부름(합성) — 합성 대조 건너뜀" in out, "N2 node 를 못 씀 + 스위치 없음 = SKIP 줄", out[-600:])
rc, out = child("alias", EMPTY, TJ_REQUIRE_NODE="1")
chk(rc == 1 and "FAIL node 없음 — 합성 시험 못 돌림" in out, "N3 별칭 TJ_REQUIRE_NODE=1(_sec_lint 가 먼저 읽음) = 같은 FAIL", out[-600:])
rc, out = child("alias", EMPTY)
chk(rc == 0 and "SKIP node 없음" in out, "N3 별칭도 없으면 SKIP", out[-600:])

REAL = os.path.join(T.HERE, "test_curve_hold_hidden.py")
if os.path.isfile(REAL):
    e0 = dict(BASE_ENV, PATH=EMPTY)
    p1 = subprocess.run([sys.executable, REAL], capture_output=True, text=True, timeout=300, env=dict(e0, TJ_TEST_REQUIRE_NODE="1"))
    chk(p1.returncode == 1 and "FAIL node 없음" in p1.stdout, "N4 실제 node 시험 + node 없음 + 스위치 = rc 1(FAIL)", (p1.returncode, p1.stdout[-500:]))
    p2 = subprocess.run([sys.executable, REAL], capture_output=True, text=True, timeout=300, env=e0)
    chk(p2.returncode == 0 and "SKIP node 없음" in p2.stdout, "N4 실제 node 시험 + node 없음 + 스위치 없음 = rc 0 · SKIP 줄",
        (p2.returncode, p2.stdout[-500:]))
else:
    print("SKIP test_curve_hold_hidden.py 없음 — N4 건너뜀")
T.finish()
