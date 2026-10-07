#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import os
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {k: v for k, v in os.environ.items() if not k.startswith("TJ_") or k.startswith("TJ_TEST_")}
ENV.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8", TJ_TEST_ROOT=T.ROOT)
SWALLOW = ("import urllib.request\n"
           "try:\n    urllib.request.urlopen('https://example.invalid/x', timeout=1)\nexcept Exception:\n    pass\n")


def child(body):
    code = "import sys\nsys.dont_write_bytecode = True\nimport _harness as T\n" + body + "\nT.finish()\n"
    p = subprocess.run([sys.executable, "-c", code], cwd=HERE, env=ENV, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    return p.returncode, (p.stdout + p.stderr)


rc, out = child(SWALLOW)
T.chk(rc == 1 and re.search(r"FAIL 바깥 연결 시도 [1-9]", out), "[h1] urlopen 시도를 삼켜도 = 시도 기록 → FAIL", out[-600:])
rc, out = child("import _ingest\n" + SWALLOW)
T.chk(rc == 1 and re.search(r"FAIL 바깥 연결 시도 [1-9]", out), "[h2] _ingest 를 가져온 뒤에도 urlopen 시도 = 기록 → FAIL", out[-600:])
rc, out = child("import urllib.request\nurllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(OSError('x'))\n" + SWALLOW.split("\n", 1)[1])
T.chk(rc == 1 and "urlopen 차단기" in out, "[h3] 기록 없는 urlopen 으로 바꿔 끼움 = finish() FAIL(차단기 바뀜)", out[-600:])
rc, out = child("import urllib.request\ndef _m(*a, **k):\n    raise OSError('목')\n_m._tj_test_mock = True\nurllib.request.urlopen = _m\n")
T.chk(rc == 0, "[h3] 표시한 목(_tj_test_mock)은 허용", out[-600:])
rc, out = child("import socket\ntry:\n    socket.create_connection(('example.invalid', 443), timeout=1)\nexcept Exception:\n    pass\n")
T.chk(rc == 1 and re.search(r"FAIL 바깥 연결 시도 [1-9]", out), "[h4] 소켓 연결 시도를 삼켜도 = 기록 → FAIL", out[-600:])
rc, out = child("pass")
T.chk(rc == 0 and not re.search(r"^FAIL ", out, re.M), "[h4] 시도 없음 = 통과", out[-600:])
bad = []
for fn in sorted(os.listdir(HERE)):
    if fn.endswith(".py") and fn != "_harness.py":
        src = open(os.path.join(HERE, fn), encoding="utf-8").read()
        if re.search(r"^\s*urllib\.request\.urlopen\s*=", src, re.M):
            bad.append(fn)
T.chk(not bad, "[h5] 시험 파일이 urlopen 을 직접 바꿔 끼우지 않음(차단 = 하네스 한 곳)", bad)
T.finish()
