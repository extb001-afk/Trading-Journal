#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import ast
import glob
import os
from decimal import Decimal

import accounting_books as AB

chk = T.chk
NAMES = set(AB.Books.names())


def _tree(fn):
    return ast.parse(open(os.path.join(T.SRC, fn), encoding="utf-8").read(), fn)


rp = _tree("view_b_replay.py")
prep = next(n for n in ast.walk(rp) if isinstance(n, ast.FunctionDef) and n.name == "_replay_prep")
alias, direct = {}, []
for st in ast.walk(prep):
    if not isinstance(st, ast.Assign):
        continue
    tg = st.targets[0]
    pairs = []
    if isinstance(tg, ast.Name):
        pairs = [(tg, st.value)]
    elif isinstance(tg, ast.Tuple) and isinstance(st.value, ast.Tuple) and len(tg.elts) == len(st.value.elts):
        pairs = list(zip(tg.elts, st.value.elts))
    for t9, v9 in pairs:
        if isinstance(t9, ast.Name) and t9.id in NAMES:
            if isinstance(v9, ast.Attribute) and isinstance(v9.value, ast.Name) and v9.value.id == "books" and v9.attr == t9.id:
                alias[t9.id] = alias.get(t9.id, 0) + 1
            else:
                direct.append(f"{t9.id}:{st.lineno}")
chk(set(alias) == NAMES and all(v == 1 for v in alias.values()) and not direct, "B1 _replay_prep = 필드마다 별칭 한 번 · 직접 대입 없음",
    (sorted(NAMES - set(alias)), direct))


def _unpack_el(e, nm):
    if isinstance(e, ast.Attribute):
        return e.attr == nm and _unpack_el(e.value, "ctx")
    return isinstance(e, ast.Subscript) and isinstance(e.value, ast.Name) and e.value.id == "_bs9" and isinstance(e.slice, ast.Constant) and e.slice.value == nm


alias_lines = set()
for st in ast.walk(prep):
    if isinstance(st, ast.Assign) and any(isinstance(v9, ast.Attribute) and isinstance(v9.value, ast.Name) and v9.value.id == "books"
                                          for v9 in (st.value.elts if isinstance(st.value, ast.Tuple) else [st.value])):
        alias_lines.add(st.lineno)
bad = []
for f in sorted(glob.glob(os.path.join(T.SRC, "view_b_*.py"))) + [os.path.join(T.SRC, "view_builder.py")]:
    tr = ast.parse(open(f, encoding="utf-8").read(), f)
    ok_lines = {st.lineno for st in ast.walk(tr)
                if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Tuple)
                and isinstance(st.value, ast.Tuple) and st.value.elts and len(st.targets[0].elts) == len(st.value.elts)
                and all(isinstance(t9, ast.Name) and _unpack_el(e, t9.id) for t9, e in zip(st.targets[0].elts, st.value.elts))}
    if os.path.basename(f) == "view_b_replay.py":
        ok_lines |= alias_lines
    for n in ast.walk(tr):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)) and n.id in NAMES and n.lineno not in ok_lines:
            bad.append(f"{os.path.basename(f)}:{n.lineno} {n.id}")
chk(not bad, "B2 결과 이름 재바인딩 = 이름표 풀기뿐", bad)

b = AB.Books()
sc = {n: getattr(b, n) for n in NAMES}
sc["other"] = {}
AB.check_aliases(b, sc, "t")
chk(True, "B3 같은 객체 = 통과")
sc2 = dict(sc, tax_rows=list(b.tax_rows), realized_by_date={})
try:
    AB.check_aliases(b, sc2, "t2")
    msg = None
except AssertionError as e:
    msg = str(e)
chk(msg is not None and "tax_rows" in msg and "realized_by_date" in msg and "t2" in msg, "B3 다시 묶임 = AssertionError(이름·자리)", msg)
AB.check_aliases(b, {"tax_rows": b.tax_rows}, "t3")
chk(True, "B3 이름표에 없는 이름 = 건너뜀")

b2 = AB.Books()
chk(b2.gas_applied == {"buy": Decimal(0), "sell": Decimal(0), "n": 0} and isinstance(b2.gas_applied["buy"], Decimal)
    and all(getattr(b2, n) in ({}, []) for n in NAMES - {"gas_applied"}), "B4 기본값 = 종전 초기값")
chk(all(getattr(b, n) is not getattr(b2, n) for n in NAMES), "B4 인스턴스마다 새 객체")

T.finish()
