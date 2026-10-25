#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402

chk = T.chk
TOOLS = os.path.join(T.ROOT, "tools")
OLD_DIR = os.path.join(TOOLS, "oneoff", "2026.10.10")
PAIRS = (("bithumb_filltime_1010", "bithumb_filltime"), ("negabs_1010", "negabs"), ("token_recheck_1010", "token_recheck"))
STDLIB = {"importlib", "os", "sys"}
ENV = {k: v for k, v in os.environ.items() if not k.startswith("TJ_") or k.startswith("TJ_TEST_")}
ENV.update(TJ_BASE=T.TMP, PYTHONDONTWRITEBYTECODE="1")


def run(path, args, stdin=None, env=None):
    cmd = [sys.executable, "-"] + args if stdin is not None else [sys.executable, path] + args
    r = subprocess.run(cmd, input=stdin, env=env or ENV, capture_output=True, text=True, timeout=120, cwd=T.TMP)
    return r.returncode, r.stdout + r.stderr


def norm(out, old, new):
    out = out.replace(old + ".py", new + ".py").replace("usage: -", "usage: " + new + ".py")
    return re.sub(r"\s+", " ", out).strip()


if not os.path.isfile(os.path.join(TOOLS, "rebuild2.py")):
    chk(True, "E 건너뜀 — tools/ 없는 배치")
    T.finish()

for old, new in PAIRS:
    p = os.path.join(OLD_DIR, old + ".py")
    with open(p, encoding="utf-8") as fh:
        text = fh.read()
    tree = ast.parse(text)
    imps = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imps |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    consts = {t.id: n.value.value for n in tree.body if isinstance(n, ast.Assign) for t in n.targets
              if isinstance(t, ast.Name) and isinstance(n.value, ast.Constant)}
    mainf = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    rets = [n.value for n in ast.walk(mainf) if isinstance(n, ast.Return)] if mainf else []
    calls_main = any(isinstance(r, ast.Call) and isinstance(r.func, ast.Attribute) and r.func.attr == "main" for r in rets)
    chk(imps <= STDLIB and consts.get("NEW") == new and calls_main and len(text.splitlines()) <= 60
        and os.path.isfile(os.path.join(TOOLS, new + ".py")),
        "E1 tools/oneoff/2026.10.10/%s.py = 얇은 입구(표준 라이브러리만 · NEW = %s · main() → 새 이름 main())" % (old, new), (imps, consts, calls_main))

for old, new in PAIRS:
    for args in (["--help"], ["--no-such-option"]):
        ro, oo = run(os.path.join(OLD_DIR, old + ".py"), args)
        rn, on = run(os.path.join(TOOLS, new + ".py"), args)
        chk(ro == rn and ro in (0, 2) and norm(oo, old, new) == norm(on, old, new) and on.strip(),
            "E2 %s %s = 새 이름과 같은 종료 코드(%s)·출력" % (old, " ".join(args), rn), (ro, rn, oo[-300:], on[-300:]))

chk(not any(os.path.exists(os.path.join(TOOLS, o + ".py")) for o, _n in PAIRS), "E1 tools/ 맨 위엔 옛 이름 없음(새 이름만)")

old, new = PAIRS[2]
with open(os.path.join(OLD_DIR, old + ".py"), encoding="utf-8") as fh:
    shim = fh.read()
rn, on = run(os.path.join(TOOLS, new + ".py"), ["--help"])
rb, ob = run(None, ["--base", T.ROOT, "--help"], stdin=shim)
env2 = dict(ENV, TJ_BASE=T.ROOT)
re_, oe = run(None, ["--help"], stdin=shim, env=env2)
env3 = {k: v for k, v in ENV.items() if k != "TJ_BASE"}
rx, ox = run(None, ["--help"], stdin=shim, env=env3)
chk(rb == re_ == rn == 0 and norm(ob, old, new) == norm(on, old, new) == norm(oe, old, new),
    "E3 표준입력 실행(--base · TJ_BASE) = 새 이름 도구와 같은 출력", (rb, re_, ob[-300:]))
chk(rx == 1 and ox.strip() == "--base 필요(표준입력 실행)", "E3 표준입력 실행 · 루트 없음 = 안내와 함께 실패", (rx, ox[-200:]))

T.finish()
