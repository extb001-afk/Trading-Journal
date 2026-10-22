#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _arch as A  # noqa: E402

import ast  # noqa: E402
import importlib.util  # noqa: E402
import os  # noqa: E402

import _arch_py_defs as D  # noqa: E402

T = A.T
SAMPLES = ("except:\n pass", "except Exception:\n pass", "except BaseException as e:\n raise",
           "except (ValueError, Exception):\n pass", "except (OSError, urllib.error.URLError):\n pass",
           "except builtins.Exception:\n pass", "except ValueError:\n pass", "except (KeyError,):\n pass")
A.run_group("except", finish=False)
audit = os.path.join(A.ROOT, "tools", "refactor", "except_audit.py")
if os.path.isfile(audit) and not A.PUBLIC_LAYOUT:
    spec = importlib.util.spec_from_file_location("_except_audit_for_test", audit)
    ea = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ea)
    diff = []
    for body in SAMPLES:
        h = ast.parse("try:\n x\n" + body).body[0].handlers[0]
        if D.except_kind(h) != ea.kind_of(h):
            diff.append("%r: %s ≠ %s" % (body.split(":")[0], D.except_kind(h), ea.kind_of(h)))
    T.chk(not diff, "except 종류 판정(bare·broad·narrow) = tools/refactor/except_audit.kind_of(합성 표본 %d)" % len(SAMPLES), diff)
else:
    T.chk(True, "except_audit 대조 건너뜀 — 저장소 도구 없음(공개판 배치)")
T.finish()
