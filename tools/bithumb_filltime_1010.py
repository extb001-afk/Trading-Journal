#!/usr/bin/env python3
import importlib.util
import os
import sys

NEW = "bithumb_filltime"


def _tools_dir(argv: list) -> str:
    try:
        here = os.path.abspath(__file__)
    except NameError:
        here = ""
    if os.path.isfile(here):
        return os.path.dirname(here)
    base = os.environ.get("TJ_BASE", "")
    for i, a in enumerate(argv):
        if a == "--base" and i + 1 < len(argv):
            base = argv[i + 1]
        elif a.startswith("--base="):
            base = a.split("=", 1)[1]
    if not base:
        raise SystemExit("--base 필요(표준입력 실행)")
    return os.path.join(base, "tools")


def main() -> int:
    path = os.path.join(_tools_dir(sys.argv[1:]), NEW + ".py")
    spec = importlib.util.spec_from_file_location(NEW, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[NEW] = mod
    spec.loader.exec_module(mod)
    return mod.main()


if __name__ == "__main__":
    sys.exit(main())
