#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import dataclasses  # noqa: E402
import glob  # noqa: E402
import os  # noqa: E402

import accounting_ctx as AC  # noqa: E402

chk = T.chk
NAMES = set(AC.ReplayCtx.names())

rp = ast.parse(open(os.path.join(T.SRC, "view_b_replay.py"), encoding="utf-8").read())
prep = next(n for n in ast.walk(rp) if isinstance(n, ast.FunctionDef) and n.name == "_replay_prep")
mk = [n for n in ast.walk(prep) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "ReplayCtx"]
kw = {k.arg: k.value for k in mk[0].keywords} if len(mk) == 1 else {}
chk(len(mk) == 1 and not mk[0].args and set(kw) == NAMES and all(isinstance(v, ast.Name) and v.id == k for k, v in kw.items()),
    "C1 ReplayCtx 한 번 · 필드=같은 이름", (len(mk), sorted(set(kw) ^ NAMES)))
mk_line = mk[0].lineno if mk else 0
late = [f"{n.id}:{n.lineno}" for n in ast.walk(prep) if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)) and n.id in NAMES and n.lineno > mk_line]
chk(not late, "C1 묶은 뒤 prep 에서 다시 묶지 않음", late)
late2 = []
for sn in ("_replay_main", "_replay_links", "_replay_rt"):
    fn = next(n for n in ast.walk(rp) if isinstance(n, ast.FunctionDef) and n.name == sn)
    body = [x for x in fn.body if not (isinstance(x, ast.Expr) and isinstance(x.value, ast.Constant))]
    head = body[0] if body and isinstance(body[0], ast.Assign) and isinstance(body[0].targets[0], ast.Tuple) else None
    late2 += [f"{sn} {n.id}:{n.lineno}" for st in body if st is not head for n in ast.walk(st)
              if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)) and n.id in NAMES]
chk(not late2, "C1′ 뒤 리플레이 단계(main·links·rt) 몸통에서 입력 묶음 필드 이름 재묶음 0(머리 풀기만)", late2)

po9 = next((n for n in ast.walk(rp) if isinstance(n, ast.ClassDef) and n.name == "PrepOut"), None)
po_f = {x.target.id for x in (po9.body if po9 else []) if isinstance(x, ast.AnnAssign)}
chk(po9 is not None and "ctx" in po_f and not (po_f & NAMES), "C2′ PrepOut 필드에 입력 묶음 필드 이름 없음(ctx 칸 하나로만)", sorted(po_f & NAMES))
direct = []
for f in sorted(glob.glob(os.path.join(T.SRC, "view_b_*.py"))):
    s = open(f, encoding="utf-8").read()
    for nm in NAMES:
        if f'_bs9["{nm}"]' in s:
            direct.append(f"{os.path.basename(f)} {nm}")
mainf = next(n for n in ast.walk(rp) if isinstance(n, ast.FunctionDef) and n.name == "_replay_main")
mbody = [x for x in mainf.body if not (isinstance(x, ast.Expr) and isinstance(x.value, ast.Constant))]
mh = mbody[0] if mbody and isinstance(mbody[0], ast.Assign) and isinstance(mbody[0].targets[0], ast.Tuple) else None
for t9, v9 in (zip(mh.targets[0].elts, mh.value.elts) if mh is not None else ()):
    if isinstance(t9, ast.Name) and t9.id in NAMES and ast.unparse(v9) != "pre.ctx.%s" % t9.id:
        direct.append(f"_replay_main {t9.id} ← {ast.unparse(v9)}")
chk(mh is not None and not direct, "C2′ 화면 단계 = _bs9[\"ctx\"].이름 으로만 · main 머리 풀기의 입력 묶음 이름 = pre.ctx.이름 으로만", direct)
import accounting_books as AB  # noqa: E402
both = sorted(set(AB.ReplayResult.old_names()) & NAMES)
chk(not both and "ctx" in AB.ReplayResult.old_names(), "C2 화면 이름표(accounting_books.ReplayResult 옛 이름)에 입력 묶음 필드 이름 없음 · ctx 하나로만 넘김", both)

c = AC.ReplayCtx(conn=object(), prefs={}, fb_on=False, fs_pref=True, fs_on=True, gas_on=True, offc_on=set(), offc_ans=set(), offc_excl=set(),
                 now=1.0, today_kst=object(), fxb=object())
sc = {n: getattr(c, n) for n in NAMES}
AC.check_ctx(c, sc, "t")
chk(True, "C3 같은 객체 = 통과")
try:
    AC.check_ctx(c, dict(sc, prefs={}, fxb=object()), "t2")
    msg = None
except AssertionError as e:
    msg = str(e)
chk(msg is not None and "prefs" in msg and "fxb" in msg and "t2" in msg, "C3 다시 묶임 = AssertionError(이름·자리)", msg)
AC.check_ctx(c, {"fb_on": c.fb_on}, "t3")
chk(True, "C3 이름표에 없는 이름 = 건너뜀")
try:
    c.fb_on = True
    froz = False
except dataclasses.FrozenInstanceError:
    froz = True
chk(froz, "C3 필드 대입 불가(frozen)")

T.finish()
