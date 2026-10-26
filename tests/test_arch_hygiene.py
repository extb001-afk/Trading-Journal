#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _arch as A  # noqa: E402

import _arch_py_checks as C  # noqa: E402
import _arch_py_defs as D  # noqa: E402

for txt9, want9 in (("noqa: PLW0603 — 지연 적재 메모", False), ("noqa: BLE001, PLW0603", False), ("noqa: BLE001 10-15 고침", True),
                    ("noqa: BLE001 S4 고침", True), ("noqa: BLE001 HOTFIX 수정", True), ("noqa: BLE001 [x] 10-15", True), ("burst1010 고침", True)):
    A.T.chk(D.is_history(txt9) == want9, "is_history 앞머리 noqa 규칙 코드만 뺌: %r → %s" % (txt9, want9))
C.run_hygiene()
A.T.finish()
