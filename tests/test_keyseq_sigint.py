#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import ast
import os


def main_block(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and getattr(node.test.left, "id", None) == "__name__" \
                and any(isinstance(c, ast.Constant) and c.value == "__main__" for c in node.test.comparators) \
                and any(isinstance(x, (ast.Expr, ast.Try)) and "main" in ast.dump(x) for x in node.body):
            last = node
    return compile(ast.Module(body=[last], type_ignores=[]), path, "exec")


class Log:
    def __init__(self):
        self.lines = []

    def info(self, *a):
        self.lines.append(a[0] % a[1:] if len(a) > 1 else a[0])

    warning = error = critical = info


def run_block(code, exc):
    lg = Log()

    def fake_main():
        raise exc

    ns = {"__name__": "__main__", "main": fake_main, "log": lg}
    try:
        exec(code, ns)
        return None, lg.lines
    except BaseException as e:
        return type(e).__name__, lg.lines


for i, f in enumerate(("evm_watch.py", "sol_watch.py", "bsc_watch.py"), 1):
    code = main_block(os.path.join(T.SRC, f))
    err, lines = run_block(code, KeyboardInterrupt())
    T.chk(err is None and any("SIGINT" in ln for ln in lines), f"S{i} {f}: KeyboardInterrupt = 트레이스백 없이 정지 한 줄", (err, lines))
    err2, _l = run_block(code, RuntimeError("진짜 오류"))
    T.chk(err2 == "RuntimeError", f"S4 {f}: 다른 예외는 그대로 올라감", err2)
T.finish()
