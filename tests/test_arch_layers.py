#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _arch as A  # noqa: E402

import os  # noqa: E402

T = A.T
A.run_group("layers", finish=False)
st = A.state()
if st.layers is not None and not A.PUBLIC_LAYOUT:
    text = open(A.ARCH_MD, encoding="utf-8").read() if os.path.isfile(A.ARCH_MD) else ""
    block = A.arch_md_block(text)
    T.chk(block == A.layer_table_md(st.layers), "docs/ARCH.md 계층 표(자동 칸) = layers.json — 다르면 %s --sync-doc" % A.SELF_CMD,
          "표식 없음" if block is None else None)
    made = sorted(m for m in st.layers.get("planned", {}) if st.index and m in st.index)
    if made:
        print("안내 계획 모듈이 생김: %s — layers.json 'planned' 에서 'modules' 로 옮기고 --sync-doc" % ", ".join(made), flush=True)
    dup = sorted(set(st.layers.get("planned", {})) & set(st.layers.get("modules", {})))
    T.chk(not dup, "layers.json — 'planned' 와 'modules' 에 같이 있는 모듈 없음", dup)
T.finish()
