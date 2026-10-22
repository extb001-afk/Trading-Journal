#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import os  # noqa: E402

chk = T.chk
TOOL = os.path.join(T.ROOT, "tools", "refactor", "codemod_net.py")
if not os.path.isfile(TOOL):
    print("SKIP tools/refactor/codemod_net.py 없음(공개판 — 리팩터 도구는 운영 저장소에만)")
    T.finish()
sys.path.insert(0, os.path.dirname(TOOL))
import codemod_net as C  # noqa: E402

MODS = {"config", "logs", "net_http", "paths"}


def run(text, hand=()):
    edits, table, imp, why = C.plan_file("src/x.py", text, MODS, hand)
    return (C.apply_edits(text, edits) if edits else text), table, imp, why


SRC1 = '''"""doc."""
import json
import urllib.request
import config, logs, paths


def f(url, hdr, opener):
    req = urllib.request.Request(url, data=b"x",
                                 headers={"A": "1"})
    with urllib.request.urlopen(urllib.request.Request(url, headers=hdr) if hdr else url, timeout=3) as r:
        r.read()
    o = opener or urllib.request.urlopen
    return o(req, timeout=5), json.dumps(1)
'''
new1, tab1, imp1, why1 = run(SRC1)
chk(not why1, "[1] 합성 글 거부 없음", why1)
chk("net_http.request(url, data=b\"x\",\n                           headers={\"A\": \"1\"})" in new1, "[1] Request → net_http.request · 이어지는 줄 공백만 왼쪽으로", new1[:400])
chk("net_http.urlopen(net_http.request(url, headers=hdr) if hdr else url, timeout=3)" in new1, "[1] 한 줄 두 호출 둘 다", "")
chk("o = opener or net_http.urlopen" in new1, "[1] 값 참조 → net_http.urlopen", "")
chk([(t[3], t[6]) for t in tab1] == [("call", "코드모드")] * 3 + [("val", "코드모드")], "[1] 자리 표 = 호출 3 · 값 1", tab1)
chk("import urllib.request" not in new1, "[2] 범위(모듈)에 urllib 쓰임 0 → import urllib.request 지움", "")
chk("import config, logs, net_http, paths\n" in new1, "[2] net_http 를 맨 위 src import 줄 정렬 자리로", "")
ast.parse(new1)

SRC2 = '''import urllib.request
import logs, net_http


def g(u):
    try:
        return urllib.request.urlopen(u, timeout=1)
    except urllib.error.HTTPError:
        return None


def h(u):
    import urllib.request
    return urllib.request.urlopen(u, timeout=2)
'''
new2, tab2, imp2, why2 = run(SRC2)
chk(not why2 and new2.startswith("import urllib.request\nimport logs, net_http\n"), "[2] urllib.error 쓰임 남음 → 맨 위 import 남김 · net_http 있으면 그대로",
    (why2, new2[:80]))
chk("def h(u):\n    return net_http.urlopen(u, timeout=2)" in new2, "[2] 지역 import(그 함수에 urllib 쓰임 0) 지움", new2[-120:])

BAD = {
    "별칭": "import urllib.request as ur\nimport logs\n\n\ndef f(u):\n    return urllib.request.urlopen(u, timeout=1)\n",
    "from": "from urllib.request import urlopen\nimport urllib.request\nimport logs\n\n\ndef f(u):\n    return urllib.request.urlopen(u, timeout=1)\n",
    "지역 net_http": "import urllib.request\nimport logs\n\n\ndef f(u):\n    import net_http\n    return urllib.request.urlopen(u, timeout=1)\n",
    "urllib 대입": "import urllib.request\nimport logs\nurllib = None\n\n\ndef f(u):\n    return urllib.request.urlopen(u, timeout=1)\n",
    "다른 모듈 as net_http": "import urllib.request\nimport logs\n\n\ndef f(u):\n    import json as net_http\n    return urllib.request.urlopen(u, timeout=1)\n",
    "다른 모듈 as urllib": "import urllib.request\nimport logs\n\n\ndef f(u):\n    import json as urllib\n    return urllib.request.urlopen(u, timeout=1)\n",
    "from … import net_http": "import urllib.request\nimport logs\nfrom pkg import net_http\n\n\ndef f(u):\n    return urllib.request.urlopen(u, timeout=1)\n",
    "urlopen data=": "import urllib.request\nimport logs\n\n\ndef f(u):\n    return urllib.request.urlopen(u, data=b'x', timeout=3)\n",
    "urlopen 위치 2": "import urllib.request\nimport logs\n\n\ndef f(u):\n    return urllib.request.urlopen(u, None, 3)\n",
    "urlopen timeout 없음": "import urllib.request\nimport logs\n\n\ndef f(u):\n    return urllib.request.urlopen(u)\n",
    "Request 위치 4": "import urllib.request\nimport logs\n\n\ndef f(u):\n    return urllib.request.Request(u, None, {}, 'h')\n",
    "Request **kw": "import urllib.request\nimport logs\n\n\ndef f(u, kw):\n    return urllib.request.Request(u, **kw)\n",
    "값 대입": "import urllib.request\nimport logs\n\n\ndef f(fake):\n    urllib.request.urlopen = fake\n",
    "붙일 줄 없음": "import urllib.request\n\n\ndef f(u):\n    return urllib.request.urlopen(u, timeout=1)\n",
}
for name, src in BAD.items():
    out, _t, _i, why = run(src)
    chk(bool(why), "[3] 거부: %s" % name, why)
ok_parse = "import urllib.parse as up\nimport urllib.request\nimport logs\n\n\ndef f(u):\n    return urllib.request.urlopen(up.quote(u), timeout=1)\n"
chk(not run(ok_parse)[3], "[3] urllib.parse 별칭은 거부 아님(다른 이름을 묶음)", run(ok_parse)[3])

SRC4 = '''import urllib.request
import logs


class R:
    def a(self, u):
        return urllib.request.Request(u, headers={})

    def b(self, u):
        return urllib.request.Request(u, headers={})
'''
new4, tab4, imp4, why4 = run(SRC4, ("R.b",))
chk(not why4 and [t[6] for t in tab4] == ["코드모드", "손"], "[4] 손 자리 = 표에 '손' · 건너뜀", tab4)
chk("import urllib.request\n" in new4 and new4.count("urllib.request.Request(") == 1, "[4] 손 자리가 남은 범위의 import urllib.request 남김", new4)

import subprocess  # noqa: E402
r6 = subprocess.run([sys.executable, "-I", TOOL, "prove", "--root", T.ROOT, "--base", "no-such-ref-w61"], capture_output=True, text=True)
chk(r6.returncode == 1 and "통과" not in r6.stdout, "[6] prove --base 없는 커밋 = 실패(rc 1 · 통과 문구 없음)", (r6.returncode, r6.stdout[-200:], r6.stderr[-200:]))
try:
    C._git_show(T.ROOT, "no-such-ref-w61", "src/net_http.py")
    chk(False, "[6] git show 실패 = RuntimeError(파일 없음 None 과 구분)", "예외 없음")
except RuntimeError:
    chk(True, "[6] git show 실패 = RuntimeError(파일 없음 None 과 구분)")

left = []
for rel in C.targets(T.ROOT):
    with open(os.path.join(T.ROOT, rel), encoding="utf-8") as f:
        left += ["%s:%d" % (rel, a.lineno) for k, a, c in C.sites(ast.parse(f.read()))]
chk(not left, "[5] 지금 src 에 net_http 밖 urllib.request.Request·urlopen 자리 0(brokers/base 는 대상 밖)", left)
T.finish()
