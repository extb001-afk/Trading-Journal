#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _arch as A  # noqa: E402

import _arch_py_checks as C  # noqa: E402

C.run_hygiene()
A.T.finish()
