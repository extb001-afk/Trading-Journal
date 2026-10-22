#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _arch as A  # noqa: E402

A.run_group("size")
