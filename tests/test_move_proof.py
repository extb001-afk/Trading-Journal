#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

chk = T.chk
TOOLS = os.path.join(T.ROOT, "tools", "refactor")
if not os.path.isfile(os.path.join(TOOLS, "move_proof.py")):
    chk(True, "공개판 배치 — 비공개 도구(tools/refactor/move_proof.py) 없음 · 건너뜀")
    T.finish()
sys.path.insert(0, TOOLS)
import move_dump  # noqa: E402
import move_proof as P  # noqa: E402

BASE = {
    "common": ('"""공통."""\nimport os\nimport logs\nimport logs as lg\nfrom logs import f as lf\n\nBASE = "b"\nNONCE = os.urandom(4).hex()\nTABLE = {"a": 1}\n'
               'for k in ("x", "y"):\n    TABLE[k] = 2\nEXTRA = sorted(TABLE)\nHOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n\n\n'
               'def mk():\n    return 1\n\n\nMADE = mk()\n\n\n'
               'def env_path():\n    return os.path.join(BASE, ".env")\n\n\n'
               'def load():\n    import nodekeys\n    return logs.f(env_path()), nodekeys\n\n\n'
               'def shadow(BASE=1):\n    return BASE\n\n\n'
               'def gate():\n    return BASE\n\n\n'
               'def pick(paths):\n    return paths.BASE\n\n\n'
               'class Box:\n    BASE = 1\n    Y = BASE\n\n\n'
               'def keep_ref():\n    import common\n    from common import gate\n    return common.gate(), gate()\n\n\n'
               'def wal(xs):\n    [(BASE := y) for y in xs]\n    return BASE\n\n\n'
               'def getb():\n    from common import BASE\n    return BASE\n\n\n'
               'def uself():\n    return lf(1)\n\n\n'
               'def callsh():\n    return shadow(2)\n\n\n'
               'def reset():\n    global lg\n    lg = None\n\n\n'
               'def uselg():\n    return lg.f(1)\n'),
    "logs": "def f(x):\n    return x\n\n\ndef g(x):\n    return -x\n",
    "nodekeys": "",
}
PROXY = ('import sys\nimport types\nimport config\nimport logs as lg\nimport paths\nimport tables\n\n_MOVED = {"BASE": paths, "env_path": paths, "pick": paths, '
         '"NONCE": tables, "TABLE": tables, "k": tables, "EXTRA": tables, "HOME": tables, "mk": tables, "MADE": tables, "load": config, "keep_ref": config, "getb": config, "uself": config}\n\n\n'
         'class _Proxy(types.ModuleType):\n    def __getattr__(self, n):\n        if n in _MOVED:\n'
         '            return getattr(_MOVED[n], n)\n        raise AttributeError(n)\n\n\n'
         'sys.modules[__name__].__class__ = _Proxy\n\n\n')
GOOD = {
    "common": ('"""공통(대리)."""\n' + PROXY + 'def shadow(BASE=1):\n    return BASE\n\n\ndef gate():\n    return paths.BASE\n\n\n'
               'class Box:\n    BASE = 1\n    Y = BASE\n\n\n'
               'def wal(xs):\n    [(BASE := y) for y in xs]\n    return BASE\n\n\n'
               'def callsh():\n    return shadow(2)\n\n\n'
               'def reset():\n    global lg\n    lg = None\n\n\n'
               'def uselg():\n    return lg.f(1)\n'),
    "paths": ('"""경로."""\nimport os\n\nBASE = "b"\n\n\ndef env_path():\n    return os.path.join(BASE, ".env")\n\n\n'
              'def pick(paths):\n    return paths.BASE\n'),
    "tables": ('import os\n\nNONCE = os.urandom(4).hex()\nTABLE = {"a": 1}\nfor k in ("x", "y"):\n    TABLE[k] = 2\nEXTRA = sorted(TABLE)\n'
               'HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n\n\ndef mk():\n    return 1\n\n\nMADE = mk()\n'),
    "config": ('import logs\nimport paths\nfrom logs import f as lf\n\n\ndef load():\n    import nodekeys\n    return logs.f(paths.env_path()), nodekeys\n\n\n'
               'def keep_ref():\n    import common\n    from common import gate\n    return common.gate(), gate()\n\n\n'
               'def getb():\n    from paths import BASE\n    return BASE\n\n\n'
               'def uself():\n    return lf(1)\n'),
    "logs": BASE["logs"], "nodekeys": "",
}
REPO = tempfile.mkdtemp(prefix="tj_move_proof_", dir=T.TMP)
GIT = ["git", "-C", REPO, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "-c", "commit.gpgsign=false",
       "-c", "init.defaultBranch=main", "-c", "core.hooksPath=/dev/null"]


def write(files):
    src = os.path.join(REPO, "src")
    os.makedirs(src, exist_ok=True)
    for f in os.listdir(src):
        if f.endswith(".py"):
            os.remove(os.path.join(src, f))
    for m, text in files.items():
        with open(os.path.join(src, m + ".py"), "w", encoding="utf-8") as fh:
            fh.write(text)


write(BASE)
for cmd in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "기준"]):
    subprocess.run(GIT + cmd, check=True, capture_output=True)
SHA = subprocess.run(GIT + ["rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
TO = "paths,tables,config"


def prove(files):
    write(files)
    return P.prove(REPO, SHA, "src/common.py", TO)


r = prove(GOOD)
chk(not r["fails"] and r["owner"] == {"BASE": "paths", "env_path": "paths", "pick": "paths", "NONCE": "tables", "TABLE": "tables",
                                      "HOME": "tables", "mk": "tables", "MADE": "tables",
                                      "k": "tables", "EXTRA": "tables", "load": "config", "keep_ref": "config", "getb": "config",
                                      "uself": "config"},
    "[1] 바른 옮김 = 실패 0 · 옮긴 이름 표(최상위 for 의 묶는 이름 k 포함)", (r["fails"], r["owner"]))
chk(not any("getb" in x for x in r["fails"]), "[1] 함수 안 from common import X → from paths import X(X 의 새 주인) = 허용 치환", r["fails"])
chk(any(x.startswith("common: _MOVED") for x in r["extra"]) and any("_Proxy" in x for x in r["extra"]),
    "[1] 대리 모듈 장치(새 대입·클래스·실행문)는 '새 문장(참고)'으로만 — 실패 아님", r["extra"])
ev = {(e["m"], e["to"], e["why"], e["q"]) for e in r["edges"]}
chk(ev == {("config", "nodekeys", "import", "load"), ("config", "logs", "top", "load"), ("config", "paths", "subst", "load"),
           ("common", "paths", "subst", "gate"), ("config", "common", "import", "keep_ref"), ("config", "paths", "import", "getb"),
           ("config", "logs", "top", "uself")},
    "[1] 근거: 옮긴 함수 안 import(config→nodekeys) · 최상위 import 사용(config→logs) · 치환(config→paths) · 다리(common→paths)", sorted(ev))

write(GOOD)
fails = move_dump.compare(REPO, SHA, "common", r["owner"])
chk(not fails, "[2] 덤프: 옮겨 간 모듈만 실어 기준 값과 같음 · 대리 경유 값도 같음 · NONCE(비결정)는 자동 제외", fails)
bad = dict(GOOD, tables="import common\n" + GOOD["tables"])
write(bad)
fails = move_dump.compare(REPO, SHA, "common", r["owner"])
chk(any("함께 실림" in x for x in fails), "[2] 옮겨 간 모듈이 원래 모듈을 실으면 실패(표가 원래 모듈 없이 완성돼야 함)", fails)
bad = dict(GOOD, paths=GOOD["paths"].replace('BASE = "b"', 'BASE = "c"'))
write(bad)
fails = move_dump.compare(REPO, SHA, "common", r["owner"])
chk(any("덤프 다름: paths.BASE" in x for x in fails), "[2] 값이 다르면 실패(옮긴 모듈 · 원래 모듈 경유 둘 다)", fails)
fails = move_dump.compare(REPO, SHA, "common", r["owner"], skip=["BASE"])
chk(not any("BASE" in x for x in fails), "[2] --skip 이름 = 손 제외", fails)

swap = dict(GOOD, tables=GOOD["tables"].replace('EXTRA = sorted(TABLE)\n', '').replace('TABLE = {"a": 1}\n', 'TABLE = {"a": 1}\nEXTRA = sorted(TABLE)\n'))
r = prove(swap)
chk(any(x.startswith("순서: tables") for x in r["fails"]), "[3] 같은 모듈로 간 대입·for 블록의 순서가 바뀌면 실패", r["fails"])
dup = dict(GOOD, common=GOOD["common"] + 'TABLE = {"a": 1}\nfor k in ("x", "y"):\n    TABLE[k] = 2\n')
r = prove(dup)
chk(any("중복 초기화(최상위 exec)" in x for x in r["fails"]) and any("중복 정의" in x for x in r["fails"]),
    "[3] 원래 모듈에 같은 초기화 블록을 남기면 중복 초기화 · 중복 정의로 실패", r["fails"])
chg = dict(GOOD, paths=GOOD["paths"].replace('".env"', '".envx"'))
r = prove(chg)
chk(any("env_path" in x for x in r["fails"]), "[3] 옮긴 함수 본문이 바뀌면 실패", r["fails"])
shd = dict(GOOD, common=GOOD["common"].replace("def shadow(BASE=1):\n    return BASE", "def shadow(BASE=1):\n    return paths.BASE"))
r = prove(shd)
chk(any("shadow" in x for x in r["fails"]), "[3] 지역 이름(인자 BASE)을 paths.BASE 로 바꾸면 치환 표 밖 = 실패", r["fails"])
NEG = {
    "매개변수 paths 의 속성을 전역 BASE 로": dict(GOOD, paths=GOOD["paths"].replace("def pick(paths):\n    return paths.BASE", "def pick(paths):\n    return BASE")),
    "클래스 몸통 BASE 를 paths.BASE 로": dict(GOOD, common=GOOD["common"].replace("    Y = BASE\n", "    Y = paths.BASE\n")),
    "함수 안 import 를 바꾸고 묶이지 않은 common 을 씀": dict(GOOD, config=GOOD["config"].replace("    import common\n    from common", "    import paths\n    from common")),
    "from common import gate → from paths(gate 의 주인 아님)": dict(GOOD, config=GOOD["config"].replace("from common import gate", "from paths import gate")),
    "걸음식으로 묶인 지역 BASE 를 paths.BASE 로": dict(GOOD, common=GOOD["common"].replace(
        "[(BASE := y) for y in xs]\n    return BASE", "[(BASE := y) for y in xs]\n    return paths.BASE")),
    "최상위 from 별칭의 원래 이름 바꿈(f → g as lf)": dict(GOOD, config=GOOD["config"].replace("from logs import f as lf", "from logs import g as lf")),
    "남는 함수(shadow)를 부르는 함수만 옮김 — 옮긴 곳에서 안 묶임": dict(
        GOOD, common=GOOD["common"].replace("def callsh():\n    return shadow(2)\n\n\n", ""),
        config=GOOD["config"] + "\n\ndef callsh():\n    return shadow(2)\n"),
    "여러 꼴 이름(lg)의 최상위 import 출처 바꿈": dict(GOOD, common=GOOD["common"].replace("import logs as lg\n", "import nodekeys as lg\n")),
    "def 와 그 정의를 부르는 대입 순서 뒤집음": dict(GOOD, tables=GOOD["tables"].replace("\n\ndef mk():\n    return 1\n\n\nMADE = mk()\n",
                                                                         "MADE = mk()\n\n\ndef mk():\n    return 1\n")),
    "같은 모듈에 for 블록 두 번": dict(GOOD, tables=GOOD["tables"].replace("EXTRA =", 'for k in ("x", "y"):\n    TABLE[k] = 2\nEXTRA =')),
}
for name, files in NEG.items():
    r = prove(files)
    chk(r["fails"], "[3] 범위·출처·중복 실패 꼴: " + name, r["fails"][:3])
r = prove(NEG["같은 모듈에 for 블록 두 번"])
chk(any("같은 모듈에 두 번" in x for x in r["fails"]), "[3] 같은 문장이 한 모듈에 두 번 = 중복 초기화(참고 출력으로 새지 않음)", r["fails"])
out = os.path.join(REPO, "proof.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump({"origins": {"settings_store": {"base": "x", "moved": {"a": ["n"]}, "edges": []}}}, f)
r = prove(GOOD)
P.emit(out, "common", SHA, r["owner"], r["edges"])
with open(out, encoding="utf-8") as f:
    doc = json.load(f)
chk(set(doc["origins"]) == {"common", "settings_store"} and doc["origins"]["common"]["moved"]["tables"] == ["EXTRA", "HOME", "MADE", "NONCE", "TABLE", "k", "mk"]
    and doc["origins"]["common"]["base"] == SHA, "[3] 근거 파일 쓰기 = 이 원래 모듈 항목만 갈아 끼움(다른 원래 모듈 항목 그대로)")
rc = P.main([SHA, "src/common.py", "--root", REPO, "--to", TO])
chk(rc == 0, "[3] 명령 줄: 바른 옮김 = 종료 0", rc)
write(chg)
with open(out, encoding="utf-8") as f:
    before = f.read()
rc = P.main([SHA, "src/common.py", "--root", REPO, "--to", TO, "--emit", out])
with open(out, encoding="utf-8") as f:
    after = f.read()
chk(rc == 1 and before == after, "[3] 명령 줄: 실패 있으면 종료 1 · 근거 파일을 건드리지 않음", rc)
r = prove(dict(GOOD, common=GOOD["common"] + "\n\ndef setb():\n    global BASE\n    BASE = 1\n"))
chk(any(x.startswith("global 재대입: common 안 global BASE") for x in r["fails"]),
    "[4] 지금 트리 원래 모듈의 새 함수가 옮긴 이름을 global 로 바꿈 = 실패", r["fails"])
BASE2 = {"common": ('"""둘째 기준."""\nfrom __future__ import annotations\nimport math as cfg\n\nX = 1\nREQUIRE_AUTH = True\n\n\n'
                    'def need_auth(required=REQUIRE_AUTH):\n    return required\n\n\nREQUIRE_AUTH = False\n\n\n'
                    'def reset():\n    global X\n    X = 2\n\n\ndef read():\n    return X\n\n\n'
                    'def clear_a():\n    global cfg\n    cfg = None\n\n\ndef clear_b():\n    global cfg\n    cfg = None\n\n\ndef readc():\n    return cfg\n\n\n'
                    'def ann(x: Missing):\n    return x\n')}
write(BASE2)
for cmd in (["add", "-A"], ["commit", "-q", "-m", "기준2"]):
    subprocess.run(GIT + cmd, check=True, capture_output=True)
SHA2 = subprocess.run(GIT + ["rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
GOOD2 = {"common": ('"""둘째(남음)."""\nfrom __future__ import annotations\nimport math as cfg\nimport paths\n\nREQUIRE_AUTH = True\n\n\n'
                    'def need_auth(required=REQUIRE_AUTH):\n    return required\n\n\nREQUIRE_AUTH = False\n\n\n'
                    'def clear_a():\n    global cfg\n    cfg = None\n\n\ndef clear_b():\n    global cfg\n    cfg = None\n\n\ndef readc():\n    return cfg\n'),
         "paths": ('"""경로."""\nfrom __future__ import annotations\n\nX = 1\n\n\ndef reset():\n    global X\n    X = 2\n\n\n'
                   'def read():\n    return X\n\n\ndef ann(x: Missing):\n    return x\n')}


def prove2(files):
    write(files)
    return P.prove(REPO, SHA2, "src/common.py", "paths")


r = prove2(GOOD2)
chk(not r["fails"] and r["owner"] == {"X": "paths", "reset": "paths", "read": "paths", "ann": "paths"},
    "[4] global 쓰는 함수를 이름과 같이 옮김 · 최상위 재대입은 원래 모듈에 그대로 · __future__ 같음 = 통과", (r["fails"], r["owner"]))
r = prove2(dict(GOOD2, paths=GOOD2["paths"] + "\n\n_WARM = None\n\n\ndef warm():\n    global _WARM\n    _WARM = 1\n"))
chk(not r["fails"], "[4] 옮겨 간 모듈 제 이름(원래 이름공간에 없던 것)의 global = 그 모듈 것 · 통과", r["fails"])
NEG2 = {
    "남은 함수(reset)가 global X 로 옛 모듈의 X 를 바꿈(읽는 쪽은 paths.X)": ("global 재대입: common 의 reset 안 global X", dict(
        GOOD2, common=GOOD2["common"].replace("def clear_a", "def reset():\n    global X\n    X = 2\n\n\ndef clear_a"),
        paths=GOOD2["paths"].replace("def reset():\n    global X\n    X = 2\n\n\n", ""))),
    "import 로 묶인 이름(cfg)을 global 로 바꾸는 함수만 옮김": ("global 재대입: paths 의 clear_a 안 global cfg", dict(
        GOOD2, common=GOOD2["common"].replace("def clear_a():\n    global cfg\n    cfg = None\n\n\n", ""),
        paths=GOOD2["paths"].replace("\nX = 1", "import math as cfg\n\nX = 1").replace(
            "def ann", "def clear_a():\n    global cfg\n    cfg = None\n\n\ndef ann"))),
    "읽는 함수(readc)만 옮기고 새 함수의 global cfg 로 꼴만 맞춤(바꾸는 쪽은 남음)": ("global 재대입: paths 안 global cfg", dict(
        GOOD2, common=GOOD2["common"].replace("def readc():\n    return cfg\n", "").rstrip("\n") + "\n",
        paths=GOOD2["paths"].replace("\nX = 1", "import math as cfg\n\nX = 1").replace(
            "def ann", "def readc():\n    return cfg\n\n\ndef _same_shape():\n    global cfg\n    cfg = None\n\n\ndef ann"))),
    "최상위에서 두 번 묶는 이름만 옮기고 사이의 기본값 읽는 함수는 남김": ("최상위 재대입: REQUIRE_AUTH", dict(
        GOOD2, common=GOOD2["common"].replace("REQUIRE_AUTH = True\n\n\n", "").replace("REQUIRE_AUTH = False\n\n\n", "")
        .replace("required=REQUIRE_AUTH", "required=paths.REQUIRE_AUTH"),
        paths=GOOD2["paths"].replace("X = 1\n", "X = 1\nREQUIRE_AUTH = True\nREQUIRE_AUTH = False\n"))),
    "옮겨 갈 모듈에 __future__ annotations 빠짐": ("__future__ 다름: paths", dict(
        GOOD2, paths=GOOD2["paths"].replace("from __future__ import annotations\n", ""))),
    "원래 모듈에서 __future__ annotations 지움": ("__future__ 다름: common", dict(
        GOOD2, common=GOOD2["common"].replace("from __future__ import annotations\n", ""))),
    "옮겨 갈 모듈에만 __future__ 하나 더": ("__future__ 다름: paths", dict(
        GOOD2, paths=GOOD2["paths"].replace("annotations\n", "annotations\nfrom __future__ import generator_stop\n"))),
}
for name, (want, files) in NEG2.items():
    r = prove2(files)
    chk(r["fails"] and all(x.startswith(want) for x in r["fails"]), "[4] 간단 규칙 실패 꼴(이 규칙만 잡음): " + name, r["fails"][:4])
write(NEG2["남은 함수(reset)가 global X 로 옛 모듈의 X 를 바꿈(읽는 쪽은 paths.X)"][1])
rc = P.main([SHA2, "src/common.py", "--root", REPO, "--to", "paths", "--emit", out])
with open(out, encoding="utf-8") as f:
    after2 = f.read()
chk(rc == 1 and after2 == after, "[4] 명령 줄: 간단 규칙 실패도 종료 1 · 근거 파일 그대로(분할 거부)", rc)
BASE3 = {"common": ('"""셋째 기준."""\nimport contextlib\n\nwith contextlib.nullcontext(1) as W:\n    pass\nY = 1\n'
                    'with contextlib.nullcontext(2) as Y:\n    pass\nZ = 1\nFLAG = True\n\n\n'
                    'def resetw():\n    global W\n    W = 2\n\n\ndef readw():\n    return W\n\n\ndef ready():\n    return Y\n\n\n'
                    'def put(v):\n    import common\n    common.Z = v\n\n\ndef readz():\n    return Z\n\n\ndef gate():\n    return FLAG\n\n\n'
                    'if True:\n    def helper():\n        import math as _WARM\n        return _WARM\n\n\ndef modname():\n    return __name__\n')}
write(BASE3)
for cmd in (["add", "-A"], ["commit", "-q", "-m", "기준3"]):
    subprocess.run(GIT + cmd, check=True, capture_output=True)
SHA3 = subprocess.run(GIT + ["rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
GOOD3 = {"common": ('"""셋째(남음)."""\nimport paths\n\nZ = 1\nFLAG = True\n\n\n'
                    'def put(v):\n    import common\n    common.Z = v\n\n\ndef readz():\n    return Z\n\n\ndef gate():\n    return FLAG\n\n\n'
                    'if True:\n    def helper():\n        import math as _WARM\n        return _WARM\n\n\ndef modname():\n    return __name__\n'),
         "paths": ('import contextlib\n\nwith contextlib.nullcontext(1) as W:\n    pass\nY = 1\nwith contextlib.nullcontext(2) as Y:\n    pass\n\n\n'
                   'def resetw():\n    global W\n    W = 2\n\n\ndef readw():\n    return W\n\n\ndef ready():\n    return Y\n')}


def prove3(files):
    write(files)
    return P.prove(REPO, SHA3, "src/common.py", "paths")


r = prove3(GOOD3)
chk(not r["fails"] and r["owner"] == {"W": "paths", "Y": "paths", "resetw": "paths", "readw": "paths", "ready": "paths"},
    "[5] with as 로 묶인 이름(W · Y)도 옮긴 이름 · global 함수와 같이 옮김 = 통과", (r["fails"], r["owner"]))
NEG3 = {
    "with as 블록·읽는 함수만 옮기고 global W 함수는 남김": ("global 재대입: common 의 resetw 안 global W", dict(
        GOOD3, common=GOOD3["common"].replace("def put", "def resetw():\n    global W\n    W = 2\n\n\ndef put"),
        paths=GOOD3["paths"].replace("def resetw():\n    global W\n    W = 2\n\n\n", ""))),
    "Y = 1 만 옮기고 with as Y 는 남김": ("중복 정의: Y", dict(
        GOOD3, common=GOOD3["common"].replace("\nZ = 1", "\nwith contextlib.nullcontext(2) as Y:\n    pass\nZ = 1").replace(
            "import paths\n", "import contextlib\nimport paths\n").replace("def put", "def ready():\n    return paths.Y\n\n\ndef put"),
        paths=GOOD3["paths"].replace("with contextlib.nullcontext(2) as Y:\n    pass\n", "").replace("\n\n\ndef ready():\n    return Y\n", "\n"))),
    "옮긴 Z 를 남은 함수가 common.Z 로 대입": ("옮긴 이름에 주인 밖으로 대입: common:", dict(
        GOOD3, common=GOOD3["common"].replace("Z = 1\n", "").replace("    return Z\n", "    return paths.Z\n"),
        paths=GOOD3["paths"].replace("    pass\n\n\ndef resetw", "    pass\nZ = 1\n\n\ndef resetw"))),
    "옮긴 FLAG 를 옮겨 간 모듈에서 새 문장으로 다시 묶음": ("새 문장이 원래 이름을 다시 묶음: paths: FLAG", dict(
        GOOD3, common=GOOD3["common"].replace("FLAG = True\n", "").replace("    return FLAG\n", "    return paths.FLAG\n"),
        paths=GOOD3["paths"].replace("    pass\n\n\ndef resetw", "    pass\nFLAG = True\nFLAG = False\n\n\ndef resetw"))),
    "옮기지 않은 이름(gate)을 옮겨 간 모듈 새 문장이 묶음": ("새 문장이 원래 이름을 다시 묶음: paths: gate", dict(
        GOOD3, paths=GOOD3["paths"] + "\n\ngate = None\n")),
}
for name, (want, files) in NEG3.items():
    r = prove3(files)
    chk(any(x.startswith(want) for x in r["fails"]), "[5] s9g1 실패 꼴: " + name, r["fails"][:4])
ZMOVED = dict(GOOD3, common=GOOD3["common"].replace("Z = 1\n", "").replace("    return Z\n", "    return paths.Z\n").replace(
    "    import common\n    common.Z = v\n", "    import paths\n    paths.Z = v\n"),
    paths=GOOD3["paths"].replace("    pass\n\n\ndef resetw", "    pass\nZ = 1\n\n\ndef resetw"))
r = prove3(ZMOVED)
chk(not r["fails"], "[6] 옮긴 Z 를 남은 함수가 주인(paths.Z)에 직접 씀 = 통과", r["fails"])
FMOVED = dict(GOOD3, common=GOOD3["common"].replace("FLAG = True\n", "").replace("    return FLAG\n", "    return paths.FLAG\n"),
              paths=GOOD3["paths"].replace("    pass\n\n\ndef resetw", "    pass\nFLAG = True\n\n\ndef resetw"))
r = prove3(FMOVED)
chk(not r["fails"], "[6] 옮긴 FLAG 를 남은 함수가 paths.FLAG 로 읽음 = 통과", r["fails"])
NEG4 = {
    "제3 모듈이 옛 모듈 별칭으로 옮긴 Z 에 씀": ("옮긴 이름에 주인 밖으로 대입: caller:", dict(
        ZMOVED, caller="def put(v):\n    import common as c\n    c.Z = v\n")),
    "여러 꼴 별칭(import 뒤 다시 묶음)으로 씀": ("옮긴 이름에 주인 밖으로 대입: caller:", dict(
        ZMOVED, caller="def put(v):\n    import common as c\n    c.Z = v\n    c = None\n")),
    "지역 별칭(alias = old)으로 씀": ("옮긴 이름에 주인 밖으로 대입: caller:", dict(
        ZMOVED, caller="def put(v):\n    import common as old\n    alias = old\n    alias.Z = v\n")),
    "새 문장 람다 키워드 전용 기본값 걸음식이 옮긴 Y 를 다시 묶음": ("새 문장이 원래 이름을 다시 묶음: paths", dict(
        GOOD3, paths=GOOD3["paths"] + "\n\n_extra = lambda *, flag=(Y := 2): None\n")),
    "새 최상위 문장이 주인 속성으로 옮긴 FLAG 를 바꿈": ("새 문장이 원래 이름에 대입: common", dict(
        FMOVED, common=FMOVED["common"] + "\n\npaths.FLAG = False\n")),
}
for name, (want, files) in NEG4.items():
    r = prove3(files)
    chk(any(x.startswith(want) for x in r["fails"]), "[6] s9g2 실패 꼴: " + name, r["fails"][:4])
r = prove3(dict(GOOD3, paths=GOOD3["paths"] + "\n\n_WARM = None\n\n\ndef warm():\n    global _WARM\n    _WARM = 1\n"))
chk(not r["fails"], "[6] 원래 모듈 블록 안 함수의 지역 import(_WARM)는 원래 이름공간 아님 — 옮겨 간 모듈 제 이름 global 통과", r["fails"])
import ast  # noqa: E402
chk(P._binds(ast.parse("F = [lambda: (Y := 2) for _ in (0,)]").body[0]) == {"F"}
    and P._binds(ast.parse("F = [(Y := 2) for _ in (0,)]").body[0]) == {"F", "Y"},
    "[7] 함축 안 람다 몸통의 걸음식 = 람다 지역(모듈 묶음 아님) · 함축 바로 안 걸음식 = 모듈 묶음")
chk(P._binds(ast.parse("def f(x: (A := 1)) -> (B := 2):\n    pass").body[0]) == {"f", "A", "B"},
    "[7] def 매개변수·반환 주석 안 걸음식 = 모듈 묶음")
r = prove2(dict(GOOD2, common=GOOD2["common"].replace("import paths\n", "import paths\nfrom paths import X, reset\n")))
chk(any(x.startswith("원래 모듈이 옮긴 이름을 import 로 고정 재수출: common") for x in r["fails"]),
    "[7] 원래 모듈이 global 로 바뀌는 옮긴 이름을 from import 로 고정 재수출 = 실패(common.X 가 옛 값에 머묾)", r["fails"])
NEG5 = {
    "새 def 주석 걸음식이 원래 이름(FLAG)을 다시 묶음": ("새 문장이 원래 이름을 다시 묶음: common", dict(
        GOOD3, common=GOOD3["common"] + "\n\ndef _ann(x: (FLAG := False)):\n    pass\n")),
    "옮긴 Z 자리에 값 없는 주석(Z: int)을 남기고 맨 이름으로 읽음": ("값 없는 주석(묶음 아님): common", dict(
        ZMOVED, common=ZMOVED["common"].replace("FLAG = True\n", "Z: int\nFLAG = True\n").replace("    return paths.Z\n", "    return Z\n"))),
    "원래 모듈 끝에 별표 import": ("별표 import: common", dict(
        GOOD3, common=GOOD3["common"] + "\n\nfrom policy import *\n", policy="_FLAG = False\n__all__ = [\"_FLAG\"]\n")),
}
for name, (want, files) in NEG5.items():
    r = prove3(files)
    chk(any(x.startswith(want) for x in r["fails"]), "[7] s9g3 실패 꼴: " + name, r["fails"][:4])
SUBD = os.path.join(REPO, "src", "client")
os.makedirs(SUBD, exist_ok=True)
with open(os.path.join(SUBD, "writer.py"), "w", encoding="utf-8") as fh:
    fh.write("def put(v):\n    import common as c\n    c.Z = v\n")
r = prove3(ZMOVED)
os.remove(os.path.join(SUBD, "writer.py"))
os.rmdir(SUBD)
chk(any(x.startswith("옮긴 이름에 주인 밖으로 대입: client.writer:") for x in r["fails"]),
    "[7] 하위 패키지(src/client/writer.py)의 옛 모듈 쓰기도 잡음", r["fails"][:3])
chk(P._binds(ast.parse("_e = [lambda x=(F := False): None for _ in (0,)]").body[0]) == {"_e", "F"}
    and P._binds(ast.parse("(F := True).unused: int").body[0]) == {"F"}
    and P._binds(ast.parse("([])[(G := 1)]: int").body[0]) == {"G"} and P._binds(ast.parse("H: int").body[0]) == set(),
    "[8] 함축 안 람다 기본값 · 값 없는 주석의 속성·첨자 대상 식 걸음식 = 모듈 묶음 · 이름 대상 값 없는 주석 = 묶음 아님")
chk(P._attr_writes(ast.parse('_POLICY["login"] = False').body[0], {"_POLICY"}) == {"_POLICY"}
    and P._attr_writes(ast.parse("paths.TABLE[k] = v").body[0], {"TABLE"}) == {"TABLE"}
    and P._attr_writes(ast.parse("del x.TABLE[0]").body[0], {"TABLE", "x"}) == {"TABLE", "x"},
    "[8] 첨자 대입·삭제 = 뿌리 이름·속성 이름 값 바꿈")
r = prove(dict(GOOD, common=GOOD["common"] + '\n\ntables.TABLE["a"] = 9\n'))
chk(any(x.startswith("새 문장이 원래 이름에 대입: common") for x in r["fails"]), "[8] 새 최상위 문장의 첨자 대입(tables.TABLE[…]) = 실패", r["fails"])
r = prove(dict(GOOD, config=GOOD["config"].replace("import paths\n", "import paths as p\n").replace("paths.env_path()", "p.env_path()")))
ev = {(e["m"], e["to"], e["why"], e["q"]) for e in r["edges"]}
chk(not r["fails"] and ("config", "paths", "subst", "load") in ev, "[8] 별칭 모듈(import paths as p)의 치환도 subst 근거(config→paths)",
    (r["fails"], sorted(ev)))
r = prove3(dict(GOOD3, common=GOOD3["common"].replace("\n\n\ndef modname():\n    return __name__\n", "\n"),
                paths=GOOD3["paths"] + "\n\ndef modname():\n    return __name__\n"))
chk(any(x.startswith("모듈 신원 이름: paths 의 modname") for x in r["fails"]), "[8] 맨 __name__ 을 읽는 함수를 옮김 = 실패('common' → 'paths')", r["fails"])
_t = {"paths": ast.parse("import contextlib\ncontextlib: object\nfrom os import path as pp\npp: object\nloose: int\n")}
got = P.shape_problems(P.Subst("common", {}), _t, ["paths"], {"contextlib", "pp", "loose"})
chk(got == ["값 없는 주석(묶음 아님): paths:5 loose"],
    "[8] import 로 묶인 이름(contextlib · from 별칭 pp)의 값 없는 주석 = 묶인 이름(거짓 실패 없음) · 안 묶인 loose 만 실패", got)

BASE9 = dict(BASE, common=BASE["common"] + ('\n\nKEYS = logs.KEYS\n\n\ndef wrap_g(x):\n    return logs.g(x)\n\n\n'
                                           'def lsetup(x, keys=logs.KEYS):\n    return logs.g(x), keys, env_path()\n\n\n'
                                           'def lsetup2(x):\n    return wrap_g(x)\n'),
             logs=BASE["logs"] + '\n\nKEYS = frozenset({"a"})\n')
write(BASE9)
for cmd in (["add", "-A"], ["commit", "-q", "-m", "기준9"]):
    subprocess.run(GIT + cmd, check=True, capture_output=True)
SHA9 = subprocess.run(GIT + ["rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
LS = '\n\ndef lsetup(x, keys=KEYS):\n    return g(x), keys, paths.env_path()\n'
GOOD9 = dict(GOOD, common=(GOOD["common"] + '\n\n_MOVED.update({"KEYS": lg, "lsetup": lg})\n\n\ndef wrap_g(x):\n    return logs.g(x)\n\n\n'
                            'def lsetup2(x):\n    return wrap_g(x)\n').replace("import logs as lg\n", "import logs\nimport logs as lg\n"),
             logs="import paths\n\n\n" + BASE9["logs"] + LS)
INTO = {"logs": ["lsetup", "KEYS"]}


def prove9(files, into=None):
    write(files)
    return P.prove(REPO, SHA9, "src/common.py", TO, into=INTO if into is None else into)


r = prove9(GOOD9)
chk(not r["fails"] and r["owner"].get("lsetup") == "logs" and r["owner"].get("KEYS") == "logs" and r["into"] == ["logs"] and r["aliased"] == 1
    and not any("logs" in (e["m"], e["to"]) for e in r["edges"]),
    "[9] 기존 모듈 logs 로 옮겨 넣음 = 통과(옛 logs.g → logs 안 맨 g · 기본값 logs.KEYS → KEYS · 별칭 KEYS 지움) · 근거에 logs 간선 없음",
    (r["fails"], r["owner"].get("lsetup"), r["into"], r["edges"]))
write(GOOD9)
fails = move_dump.compare(REPO, SHA9, "common", r["owner"])
chk(not fails, "[9] 덤프: logs 만 실어 lsetup · KEYS(= 기준 common.KEYS 와 같은 값) · 대리 경유도 같음", fails)
r = prove9(dict(GOOD9, logs=GOOD9["logs"].replace("return g(x)", "return f(x)")))
chk(any(x.startswith("다름(정의): lsetup") for x in r["fails"]), "[9] 옮겨 넣은 본문이 다른 이름을 부름(g → f) = 실패", r["fails"])
r = prove9(dict(GOOD9, common=GOOD9["common"].replace("def lsetup2(x):\n    return wrap_g(x)\n", ""),
                logs=GOOD9["logs"] + "\n\ndef lsetup2(x):\n    return g(x)\n"), {"logs": ["lsetup", "KEYS", "lsetup2"]})
chk(any(x.startswith("다름(정의): lsetup2") for x in r["fails"]),
    "[9] 원래 모듈 최상위 이름(옛 위임 래퍼 wrap_g)을 맨 이름으로 읽던 자리 → logs 안 맨 g = 실패(이름 위생 커밋 먼저)", r["fails"])
r = prove9(dict(GOOD9, common=GOOD9["common"] + LS.replace("KEYS):", "logs.KEYS):").replace("g(x)", "logs.g(x)")))
chk(any("중복" in x and "lsetup" in x for x in r["fails"]), "[9] 원래 모듈에도 남김 = 중복 정의 실패", r["fails"])
r = prove9(dict(GOOD9, common=GOOD9["common"] + "\n\nKEYS = logs.KEYS\n"))
chk(any("별칭 지우기 꼴 아님" in x and "KEYS" in x for x in r["fails"]), "[9] 별칭을 원래 모듈에 남긴 채 --into = 실패", r["fails"])
r = prove9(dict(GOOD9, logs=GOOD9["logs"].replace('frozenset({"a"})', 'frozenset({"b"})')))
chk(any("별칭 지우기 꼴 아님" in x and "KEYS" in x for x in r["fails"]), "[9] 별칭 대상(logs.KEYS)의 정의가 기준과 다름 = 실패", r["fails"])
r = prove9(GOOD9, {"logs": ["lsetup", "KEYS", "f"]})
chk(any("--into logs.f" in x for x in r["fails"]), "[9] 기준 logs 에 이미 있던 이름을 --into = 실패", r["fails"])
r = prove9(GOOD9, {"logs": ["lsetup", "KEYS", "nothere"]})
chk(any("별칭 지우기 꼴 아님" in x and "nothere" in x for x in r["fails"]), "[9] 정의도 별칭도 아닌 이름 = 실패", r["fails"])
pj = os.path.join(REPO, "proof9.json")
with contextlib.redirect_stdout(io.StringIO()):
    rc = P.main([SHA9, "src/common.py", "--to", TO, "--into", "logs=lsetup,KEYS", "--root", REPO, "--emit", pj])
moved9 = json.load(open(pj, encoding="utf-8"))["origins"]["common"]["moved"] if os.path.isfile(pj) else None
chk(rc == 0 and moved9 is not None and "logs" not in moved9 and "BASE" in moved9.get("paths", []),
    "[9] --emit 근거 파일 = 분할 모듈 이름만(logs 는 넣지 않음)", (rc, moved9))

pa = os.path.join(REPO, "proof10.json")


def main_q(*args):
    with contextlib.redirect_stdout(io.StringIO()):
        return P.main(list(args))


write(GOOD)
rc1 = main_q(SHA, "src/common.py", "--to", TO, "--root", REPO, "--emit", pa)
for cmd in (["add", "-A"], ["commit", "-q", "-m", "기준10"]):
    subprocess.run(GIT + cmd, check=True, capture_output=True)
SHA10 = subprocess.run(GIT + ["rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
GOOD10 = dict(GOOD, common=GOOD["common"].replace("def gate():\n    return paths.BASE\n\n\n", ""),
              gates="import paths\n\n\ndef gate():\n    return paths.BASE\n")
write(GOOD10)
r = P.prove(REPO, SHA10, "src/common.py", "gates")
ev0 = {(e["m"], e["to"], e["why"]) for e in r["edges"]}
r = P.prove(REPO, SHA10, "src/common.py", "gates", prior=P.prior_owner(pa, "common"))
ev1 = {(e["m"], e["to"], e["why"]) for e in r["edges"]}
chk(not r["fails"] and ("gates", "paths", "subst") not in ev0 and ("gates", "paths", "subst") in ev1,
    "[10] 앞 묶음이 증명한 옮긴 이름(paths.BASE)을 새 분할 모듈이 읽음 = prior 로 subst 근거(없으면 top 만)", (r["fails"], sorted(ev0), sorted(ev1)))
rc2 = main_q(SHA10, "src/common.py", "--to", "gates", "--root", REPO, "--emit", pa, "--emit-add")
ent = json.load(open(pa, encoding="utf-8"))["origins"]["common"]
chk(rc1 == 0 and rc2 == 0 and sorted(ent["moved"]) == ["config", "gates", "paths", "tables"] and ent["base"] == SHA10
    and ent["base_prev"] == [SHA] and {"m": "gates", "to": "paths", "why": "subst", "q": "gate"} in ent["edges"]
    and {"m": "config", "to": "paths", "why": "subst", "q": "load"} in ent["edges"],
    "[10] --emit-add = 있던 항목에 더함(옮긴 모듈 합 · 간선 합 · base_prev 에 앞 기준)", (rc1, rc2, sorted(ent["moved"]), ent.get("base_prev")))
GOOD10b = dict(GOOD, common=GOOD["common"].replace("def gate():\n    return paths.BASE\n\n\n", ""),
               paths=GOOD["paths"] + "\n\ndef gate():\n    return BASE\n")
write(GOOD10b)
rc3 = main_q(SHA10, "src/common.py", "--to", "paths", "--root", REPO, "--emit", pa, "--emit-add")
chk(rc3 == 1 and json.load(open(pa, encoding="utf-8"))["origins"]["common"]["base"] == SHA10,
    "[10] --emit-add 로 있던 옮긴 모듈(paths)에 더 옮김 = 실패 · 근거 파일 그대로", rc3)
os.remove(pa)
rc4 = main_q(SHA10, "src/common.py", "--to", "gates", "--root", REPO, "--emit", pa, "--emit-add")
chk(rc4 == 1 and not os.path.isfile(pa), "[10] --emit-add 인데 근거 파일에 그 원래 모듈 항목 없음 = 실패", rc4)

PX = ('"""시세."""\nfrom __future__ import annotations\n\nimport os\n\n_O = "0xo"\nCAS = {"eth": {"0xa": "USDC"}, "base": {}}\n'
      'for _ch in ("base",):\n    CAS[_ch][_O] = "USDE"\nSYMS = {"USDC"}\nNAT = {"XDAI"}\nMINTS = {"m1": "USDT"}\n\n\n'
      'def is_stable(ch: str, ca: str) -> bool:\n    return ca in CAS.get(ch, {}) or ca in MINTS\n')
SW11 = '"""점검."""\nfrom __future__ import annotations\n\nimport os\n\nLOG = "x"\nSW = {"eth": ("Ethereum", 1)}\nSW2 = {"bob": ("BOB", 2)}\n'
NAMES = '\n\ndef names(cfg: dict) -> list:\n    return sorted(SW)\n'
CAT = '"""카탈로그."""\nimport json\n\nCATALOG = {"a": 1}\n'
BLK = '\n\ndef block_for(c):\n    return CATALOG.get(c)\n'
BASE11 = {"px": PX, "sw": SW11 + NAMES, "cat": CAT + BLK, "user": "import px\n\n\ndef f():\n    return px.CAS, px.MINTS\n"}
write(BASE11)
for cmd in (["add", "-A"], ["commit", "-q", "-m", "기준11"]):
    subprocess.run(GIT + cmd, check=True, capture_output=True)
SHA11 = subprocess.run(GIT + ["rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
STB = ('"""스테이블."""\nfrom __future__ import annotations\n\n_O = "0xo"\nCAS = {"eth": {"0xa": "USDC"}, "base": {}}\n'
       'for _ch in ("base",):\n    CAS[_ch][_O] = "USDE"\nSYMS = {"USDC"}\nMINTS = {"m1": "USDT"}\n')
PX2 = ('"""시세."""\nfrom __future__ import annotations\n\nimport os\nimport stb\n\nNAT = {"XDAI"}\n\n\n'
       'def is_stable(ch: str, ca: str) -> bool:\n    return ca in stb.CAS.get(ch, {}) or ca in stb.MINTS\n')
SWM = 'SW = {"eth": ("Ethereum", 1)}\nSW2 = {"bob": ("BOB", 2)}\n'
GOOD11 = {"stb": STB, "px": PX2, "user": "import px, stb\n\n\ndef f():\n    return stb.CAS, stb.MINTS\n",
          "sw": '"""점검."""\nfrom __future__ import annotations\n\nimport os\nimport cat\n\nLOG = "x"\n\n\ndef names(cfg: dict) -> list:\n    return sorted(cat.SW)\n',
          "cat": CAT + SWM + BLK}
write(GOOD11)
r = P.prove(REPO, SHA11, "src/px.py", "stb")
chk(not r["fails"] and r["owner"] == {"_O": "stb", "CAS": "stb", "_ch": "stb", "SYMS": "stb", "MINTS": "stb"},
    "[11] 대리 없는 원래 모듈의 초기화 블록(대입 · for 보강)을 새 모듈로 = 통과(남은 함수 맨 이름 → stb.X 치환)", (r["fails"], r["owner"]))
own11 = r["owner"]
chk(not move_dump.compare(REPO, SHA11, "px", own11, via=False), "[11] 덤프 via=False: stb 만 실어 값 같음 · px 에 옮긴 이름 없음 · 남은 NAT 같음")
f11 = move_dump.compare(REPO, SHA11, "px", own11)
chk(any("원래 모듈 경유" in x for x in f11), "[11] 덤프 via=True(대리 전제)를 대리 없는 원래 모듈에 = 경유 실패", f11)
write(dict(GOOD11, px=PX2.replace('NAT = {"XDAI"}\n', 'NAT = {"XDAI"}\nMINTS = {"m1": "USDT"}\n')))
f11 = move_dump.compare(REPO, SHA11, "px", own11, via=False)
chk(any("옮긴 이름이 남음" in x and "MINTS" in x for x in f11), "[11] 덤프 via=False: 원래 모듈에 옮긴 이름이 남음 = 실패", f11)
write(GOOD11)
r = P.prove(REPO, SHA11, "src/sw.py", "cat", into={"cat": ["SW", "SW2"]})
chk(not r["fails"] and r["owner"] == {"SW": "cat", "SW2": "cat"} and r["into"] == ["cat"],
    "[11] --into 데이터 대입(이름 하나) 옮겨 넣기 = 통과(남은 함수 맨 SW → cat.SW · 주석 없는 대입 = annotations 차이 허용)", (r["fails"], r["owner"]))
chk(not move_dump.compare(REPO, SHA11, "sw", r["owner"], via=False), "[11] 덤프: cat 만 실어 SW·SW2 = 기준 sw 의 값 · sw 에 안 남음")
write(dict(GOOD11, cat=CAT + 'SW2 = {"bob": ("BOB", 2)}\nSW = {"eth": ("Ethereum", 1)}\n' + BLK))
r = P.prove(REPO, SHA11, "src/sw.py", "cat", into={"cat": ["SW", "SW2"]})
chk(any(x.startswith("순서:") for x in r["fails"]), "[11] 옮겨 넣은 대입 순서 뒤집음 = 실패", r["fails"])
write(dict(GOOD11, sw='"""점검."""\nfrom __future__ import annotations\n\nimport os\n\nLOG = "x"\n', cat=CAT + SWM + BLK + NAMES))
r = P.prove(REPO, SHA11, "src/sw.py", "cat", into={"cat": ["SW", "SW2", "names"]})
chk(any("__future__ 다름" in x for x in r["fails"]), "[11] 주석 있는 def 를 annotations 다른 기존 모듈로 옮겨 넣음 = 실패", r["fails"])

write(GOOD10)
r11 = P.prove(REPO, SHA10, "src/common.py", "gates")
f_def = move_dump.compare(REPO, SHA10, "common", r11["owner"])
f_np = move_dump.compare(REPO, SHA10, "common", r11["owner"], proxy=False)
chk(r11["owner"] == {"gate": "gates"} and any("원래 모듈 경유): common.gate" in x for x in f_def) and not f_np,
    "[12] 옮긴 이름(gate)을 원래 모듈이 넘기지 않음: 기본 = 경유 비교 실패 · proxy=False = 통과", (r11["owner"], f_def, f_np))
write(dict(GOOD10, gates="import common\n" + GOOD10["gates"]))
f_np2 = move_dump.compare(REPO, SHA10, "common", r11["owner"], proxy=False)
chk(any("함께 실림" in x for x in f_np2), "[12] proxy=False 여도 옮겨 간 모듈이 원래 모듈을 실으면 실패(A 쪽 검사는 그대로)", f_np2)
write(GOOD10)
with contextlib.redirect_stdout(io.StringIO()) as o11b:
    rc11b = P.main([SHA10, "src/common.py", "--to", "gates", "--root", REPO, "--dump"])
with contextlib.redirect_stdout(io.StringIO()) as o11c:
    rc11c = P.main([SHA10, "src/common.py", "--to", "gates", "--root", REPO, "--dump", "--no-proxy"])
chk(rc11b == 1 and "원래 모듈 경유" in o11b.getvalue(), "[12] CLI 기본(--no-proxy 없음) = 실패", (rc11b, o11b.getvalue()[-300:]))
chk(rc11c == 0 and "대리 아님" in o11c.getvalue(), "[12] CLI --no-proxy = 증명 통과 · 안내 문구", (rc11c, o11c.getvalue()[-300:]))

B12 = {"store": '"""저장소."""\nimport os\n\nLOCK = 1\n\n\ndef read_cfg():\n    return LOCK\n\n\n'
                'def add_w(a):\n    return read_cfg(), LOCK, a, os.sep\n'}
write(B12)
for cmd in (["add", "-A"], ["commit", "-q", "-m", "기준12"]):
    subprocess.run(GIT + cmd, check=True, capture_output=True)
SHA12 = subprocess.run(GIT + ["rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
G12 = {"store": '"""저장소."""\nimport os\n\nLOCK = 1\n\n\ndef read_cfg():\n    return LOCK\n',
       "wallets": '"""지갑."""\nimport os\n\nimport store\n\n\ndef add_w(a):\n    return store.read_cfg(), store.LOCK, a, os.sep\n'}
write(G12)
r = P.prove(REPO, SHA12, "src/store.py", "wallets", back=True)
ev12 = {(e["m"], e["to"], e["why"], e["q"]) for e in r["edges"]}
chk(not r["fails"] and r["owner"] == {"add_w": "wallets"} and ("wallets", "store", "back", "add_w") in ev12,
    "[13] 맨 이름 R(원래 모듈에 남음) ↔ `원래.R` = 통과 · 근거 back(wallets → store)", (r["fails"], r["owner"], sorted(ev12)))
r = P.prove(REPO, SHA12, "src/store.py", "wallets")
chk(any("다름(정의): add_w" in x for x in r["fails"]), "[13] --back 없이 = 다름(종전 규칙 그대로)", r["fails"])
write(dict(G12, wallets=G12["wallets"].replace("import store\n", "import store\n\nLOCK = 2\n").replace("store.LOCK", "LOCK")))
r = P.prove(REPO, SHA12, "src/store.py", "wallets", back=True)
chk(any("add_w" in x for x in r["fails"]), "[13] A 가 같은 이름(LOCK)을 따로 묶어 맨 이름으로 읽음 = 실패", r["fails"])
write(dict(G12, store=G12["store"].replace("\n\ndef read_cfg():\n    return LOCK\n", "")))
r = P.prove(REPO, SHA12, "src/store.py", "wallets", back=True)
chk(any("add_w" in x for x in r["fails"]), "[13] 원래 모듈에서 사라진 이름(read_cfg)을 `원래.R` 로 읽음 = 실패", r["fails"])
write(dict(G12, other='"""제3 모듈."""\nimport store\n\n\nclass H:\n    def __init__(self, x):\n        self.add_w = x\n'))
r = P.prove(REPO, SHA12, "src/store.py", "wallets", back=True)
chk(not r["fails"], "[13] 메서드 첫 인자(self)의 인스턴스 속성 이름이 옮긴 이름과 같음 = 모듈 대입 아님(통과)", r["fails"])
write(dict(G12, other='"""제3 모듈."""\nimport wallets\n\n\ndef f(self):\n    self.add_w = 1\n\n\nclass H:\n'
                     '    def m(self):\n        self = wallets\n        self.add_w = 2\n'))
r = P.prove(REPO, SHA12, "src/store.py", "wallets", back=True)
chk(sum("주인 밖으로 대입" in x for x in r["fails"]) == 2, "[13] 메서드 밖 함수의 self · 메서드 안에서 다시 묶은 self 의 속성 대입 = 여전히 실패", r["fails"])
write(G12)
f12 = move_dump.compare(REPO, SHA12, "store", {"add_w": "wallets"}, via=False, back=["wallets"])
f12b = move_dump.compare(REPO, SHA12, "store", {"add_w": "wallets"}, via=False)
chk(not f12 and any("함께 실림" in x for x in f12b), "[13] 덤프: back 모듈은 원래 모듈을 함께 실어도 통과 · back 아니면 실패", (f12, f12b))
T.finish()
