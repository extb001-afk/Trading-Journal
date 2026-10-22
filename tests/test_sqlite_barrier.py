#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

chk = T.chk
SUCCESSORS = ("paths", "timeutil", "envfile", "runtime", "statefile", "histmark", "seeds", "textutil", "net_http", "config", "token_tables",
              "chaincatalog", "fsio", "logs", "address_codec", "ai_cli", "cfg_schema")
ENV0 = {k: v for k, v in os.environ.items() if not k.startswith("TJ_") or k.startswith("TJ_TEST_")}
ENV0["TJ_BASE"] = os.path.join(T.TMP, "base")
os.makedirs(os.path.join(ENV0["TJ_BASE"], "state"), exist_ok=True)


def run(code, *args, **env):
    p = subprocess.run([sys.executable, "-c", code, T.SRC] + list(args), capture_output=True, text=True, timeout=180, env=dict(ENV0, **env))
    js = [x for x in p.stdout.splitlines() if x.startswith("JSON ")]
    return json.loads(js[-1][5:]) if js else {"_rc": p.returncode, "_out": (p.stdout + p.stderr)[-900:]}


mods = [m for m in ("common",) + SUCCESSORS if os.path.isfile(os.path.join(T.SRC, m + ".py"))]
r = run(r'''
import importlib, json, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
for m in sys.argv[2:]:
    importlib.import_module(m)
print("JSON " + json.dumps({"sqlite3": "sqlite3" in sys.modules, "_sqlite3": "_sqlite3" in sys.modules, "n": len(sys.argv) - 2}))
''', *mods)
chk(r.get("sqlite3") is False and r.get("_sqlite3") is False and r.get("n") == len(mods),
    "S1 기반 모듈 %d개(%s) import 뒤 sqlite3·_sqlite3 없음" % (len(mods), " · ".join(mods)), r)

STARTUP = r'''
import ast, json, os, sys
sys.dont_write_bytecode = True
src = sys.argv[1]
path = os.path.join(src, "web.py")
tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
def is_main(n):
    t = n.test
    return (isinstance(n, ast.If) and isinstance(t, ast.Compare) and isinstance(t.left, ast.Name) and t.left.id == "__name__"
            and len(t.comparators) == 1 and isinstance(t.comparators[0], ast.Constant) and t.comparators[0].value == "__main__")
def memstat_call(n):
    for x in ast.walk(n):
        if isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) and x.func.attr == "sqlite_memstatus_off":
            return x
    return None
idx = [i for i, n in enumerate(tree.body) if isinstance(n, ast.If) and is_main(n) and memstat_call(n) is not None]
out = {"barriers": len(idx)}
if len(idx) == 1:
    i = idx[0]
    ns = {"__name__": "web_startup_probe", "__file__": path}
    pre = ast.Module(body=tree.body[:i], type_ignores=[])
    exec(compile(pre, path, "exec"), ns)
    out["pre_imports"] = sorted(k for k, v in ns.items() if type(v) is type(sys))
    out["pre_src"] = sorted(m for m, v in list(sys.modules.items()) if getattr(v, "__file__", None)
                            and os.path.dirname(os.path.abspath(v.__file__)) == os.path.abspath(src))
    out["sqlite_before"] = ["sqlite3" in sys.modules, "_sqlite3" in sys.modules]
    exec(compile(ast.Module(body=tree.body[i].body, type_ignores=[]), path, "exec"), ns)
    call = memstat_call(tree.body[i])
    owner = ns.get(call.func.value.id) if isinstance(call.func.value, ast.Name) else None
    tgt = [a.targets[0].id for a in ast.walk(tree.body[i]) if isinstance(a, ast.Assign) and a.value is call
           and len(a.targets) == 1 and isinstance(a.targets[0], ast.Name)]
    out["result"] = repr(ns.get(tgt[0], "?")) if tgt else "?"
    out["why"] = (getattr(owner, "SQLITE_MEMSTAT_WHY", None) or ["?"])[0]
print("JSON " + json.dumps(out, ensure_ascii=False))
'''
r = run(STARTUP)
chk(r.get("barriers") == 1, "S2 web.py 기동 장벽(__main__ 블록 안 sqlite_memstatus_off) 정확히 하나", r)
chk(r.get("sqlite_before") == [False, False] and bool(r.get("pre_imports")),
    "S2 장벽 앞 최상위 문장(import 줄 — %s) 실행 뒤 sqlite3·_sqlite3 없음" % "·".join(r.get("pre_imports") or []), r)
chk(bool(r.get("pre_src")) and not set(r.get("pre_src") or []) - set(mods),
    "S1b 장벽 앞에서 실린 src 모듈(%s) 전부 S1 목록 안" % "·".join(r.get("pre_src") or []), sorted(set(r.get("pre_src") or []) - set(mods)))
if sys.platform.startswith("linux"):
    r3 = run(STARTUP, TJ_BUILD_PROC="fork")
    chk(r3.get("sqlite_before") == [False, False] and r3.get("result") not in ("False", "?") and "설정 거부" not in str(r3.get("why")),
        "S3 리눅스 TJ_BUILD_PROC=fork: 웹 기동 순서 그대로 통계 끄기 = False 아님 · '설정 거부' 0", r3)
else:
    chk(r.get("result") == "None", "S3 리눅스 아님 = 통계 끄기 해당 없음(None) — 리눅스 판정은 공개 CI(ubuntu)에서", r.get("result"))
T.finish()
