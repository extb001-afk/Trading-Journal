#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import dataclasses  # noqa: E402
import os  # noqa: E402
import types  # noqa: E402

import accounting_ctx as AC  # noqa: E402

chk = T.chk
STAGES = ("_replay_prep", "_replay_rt", "_replay_links", "_replay_main")
INF = 10 ** 9


def _parse(mod):
    with open(os.path.join(T.SRC, mod + ".py"), encoding="utf-8") as f:
        return ast.parse(f.read(), mod + ".py")


rp = _parse("view_b_replay")
fns = {m.name: m for n in ast.walk(rp) if isinstance(n, ast.ClassDef) for m in n.body if isinstance(m, ast.FunctionDef) and m.name in STAGES}
chk(set(fns) == set(STAGES), "리플레이 단계 함수 4개", sorted(fns))
in_cls = {}
for c in _parse("accounting_ctx").body:
    if isinstance(c, ast.ClassDef) and c.name in ("FsIn", "OriginIn", "OffcIn", "LpIn", "SaleIn", "MoveIn", "ReplayFns"):
        in_cls[c.name] = c


def _bs9_rooted(v):
    while isinstance(v, (ast.Attribute, ast.Subscript)):
        if isinstance(v, ast.Subscript) and isinstance(v.value, ast.Name) and v.value.id == "_bs9":
            return True
        v = v.value
    return False


def _binds(fn, sname, out):
    for a in fn.args.args[1:] + fn.args.kwonlyargs:
        if a.arg != "_bs9":
            out.setdefault(a.arg, []).append(fn.lineno)
    skip = set()
    stack = list(fn.body)
    while stack:
        x = stack.pop()
        if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.setdefault(x.name, []).append(x.lineno)
            for y in ast.walk(x):
                if isinstance(y, ast.Nonlocal):
                    for n in y.names:
                        out.setdefault(n, []).append(INF)
            stack.extend(getattr(x, "decorator_list", []))
            continue
        if isinstance(x, ast.Lambda):
            continue
        if isinstance(x, ast.Assign):
            for t in x.targets:
                if isinstance(t, (ast.Tuple, ast.List)) and isinstance(x.value, (ast.Tuple, ast.List)) and len(t.elts) == len(x.value.elts):
                    for a, b in zip(t.elts, x.value.elts):
                        if isinstance(a, ast.Name) and _bs9_rooted(b):
                            skip.add(id(a))
                elif isinstance(t, ast.Name) and _bs9_rooted(x.value):
                    skip.add(id(t))
        if isinstance(x, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for g in x.generators:
                for y in ast.walk(g.target):
                    skip.add(id(y))
        if isinstance(x, ast.Name) and isinstance(x.ctx, (ast.Store, ast.Del)) and id(x) not in skip:
            out.setdefault(x.id, []).append(x.lineno)
        elif isinstance(x, (ast.Import, ast.ImportFrom)):
            for a in x.names:
                out.setdefault((a.asname or a.name).split(".")[0], []).append(x.lineno)
        elif isinstance(x, ast.ExceptHandler) and x.name:
            out.setdefault(x.name, []).append(x.lineno)
        stack.extend(ast.iter_child_nodes(x))


binds = {}
for sname, fn in fns.items():
    _binds(fn, sname, binds)

mk = {}
ctor = {}
for sname, fn in fns.items():
    for i, st in enumerate(fn.body):
        if not (isinstance(st, ast.Assign) and isinstance(st.value, ast.Call) and isinstance(st.value.func, ast.Attribute)
                and isinstance(st.value.func.value, ast.Name) and st.value.func.value.id.startswith("accounting_")
                and st.value.func.attr[:1].isupper() and isinstance(st.targets[0], ast.Name)):
            continue
        if st.value.func.attr in in_cls:
            chk(st.targets[0].id not in mk and len(st.targets) == 1, "Q1 묶음 %s 문장 한 번(대상 하나)" % st.targets[0].id)
            mk[st.targets[0].id] = (sname, i, st)
        elif st.value.func.attr not in ("Books", "ReplayParts"):
            ctor[st.targets[0].id] = (sname, i, st, st.value.func.value.id, st.value.func.attr)
nested = [n.lineno for fn in fns.values() for st in fn.body for n in ast.walk(st) if st not in [m[2] for m in mk.values()]
          and isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
          and n.func.value.id == "accounting_ctx" and n.func.attr in in_cls]
chk(not nested, "Q1 묶음 클래스 부름 = 단계 몸통 바로 아래 묶음 문장뿐", nested)

want_kw = {}
users = {}
for slot, ents in AC.INPUTS.items():
    for bv, pairs in ents:
        users.setdefault(bv, []).append(slot)
        cur = want_kw.setdefault(bv, [])
        cur += [p for p in pairs if p not in cur]
chk(set(want_kw) == set(mk), "Q1 INPUTS 묶음 지역 = 리플레이 묶음 문장", sorted(set(want_kw) ^ set(mk)))
q1 = []
for bv, (sname, i, st) in mk.items():
    got = [(k.arg, k.value.id if isinstance(k.value, ast.Name) else ast.unparse(k.value)) for k in st.value.keywords]
    if st.value.args or sorted(got) != sorted(want_kw.get(bv, [])):
        q1.append("%s 키워드 %s ≠ 표" % (bv, got))
    first = min(users.get(bv, ["?"]), key=lambda u: ctor[u][2].lineno if u in ctor else INF)
    if first not in ctor or ctor[first][0] != sname:
        q1.append("%s 첫 소비 %s 가 같은 단계 생성이 아님" % (bv, first))
        continue
    j = ctor[first][1]
    between = fns[sname].body[i + 1:j]
    if j <= i or any(id(b) not in {id(m[2]) for m in mk.values()} for b in between):
        q1.append("%s(몸통 %d) 가 첫 소비 %s(몸통 %d) 바로 앞이 아님" % (bv, i, first, j))
chk(not q1, "Q1 묶음 문장 = 첫 소비 생성자 바로 앞(사이엔 묶음 문장뿐) · 키워드 = 표", q1)
q2 = []
for bv, (_s, _i, st) in mk.items():
    cname = st.value.func.attr
    cls = getattr(AC, cname)
    p9 = getattr(cls, "__dataclass_params__", None)
    if p9 is None or not (p9.frozen and not p9.eq and not p9.repr):
        q2.append("%s 꼴(frozen·eq=False·repr=False 아님)" % cname)
        continue
    fl = [f.name for f in dataclasses.fields(cls)]
    order = [k.arg for k in st.value.keywords]
    if fl != order or set(fl) != {f for f, _n in want_kw[bv]}:
        q2.append("%s 필드 %s ≠ 묶음 문장 순서 %s" % (cname, fl, order))
    if any(f.default is not dataclasses.MISSING or f.default_factory is not dataclasses.MISSING for f in dataclasses.fields(cls)):
        q2.append("%s 기본값 있음" % cname)
    if any(n == "gstate" for _f, n in want_kw[bv]):
        q2.append("%s 에 gstate(원가 지문 기록기 자리)" % cname)
chk(not q2, "Q2 묶음 클래스 = frozen·eq=False·repr=False dataclass · 필드 = 표 · 기본값 없음 · gstate 없음", q2)
try:
    AC.FsIn()
    tf = False
except TypeError:
    tf = True
chk(tf, "Q2 필드 빠진 묶음 = TypeError(조용한 None 없음)")

q3 = []
for bv, (_s, _i, st) in mk.items():
    for _f, n in want_kw[bv]:
        lst = binds.get(n, [])
        if not lst:
            q3.append("%s.%s: 묶음 0" % (bv, n))
        elif max(lst) >= st.lineno:
            q3.append("%s.%s: 묶음 줄 %s ≥ 묶음 문장 %d" % (bv, n, ["nonlocal" if x >= INF else x for x in sorted(lst) if x >= st.lineno], st.lineno))
chk(not q3, "Q3 담긴 이름 묶음 전부 묶음 문장 앞(재묶음 0 · nonlocal 0)", q3)
chk(all(len(binds.get(bv, [])) == 1 for bv in mk), "Q3 묶음 지역 자체도 한 번만 묶임(뒤 단계 머리 풀기 빼고)", {bv: binds.get(bv) for bv in mk})

mods = {}
q4 = []
for slot, ents in AC.INPUTS.items():
    _s, _i, st, mod, cname = ctor[slot]
    t = mods.setdefault(mod, _parse(mod))
    c = [x for x in t.body if isinstance(x, ast.ClassDef) and x.name == cname][0]
    ini = [f for f in c.body if isinstance(f, ast.FunctionDef) and f.name == "__init__"][0]
    me = ini.args.args[0].arg
    if [k.arg for k in st.value.keywords] != [a.arg for a in ini.args.kwonlyargs]:
        q4.append("%s 부름 키워드 ≠ __init__ 키워드 전용" % slot)
    if [a.arg for a in ini.args.args[1:]] != [k.id for k in st.value.args if isinstance(k, ast.Name)]:
        q4.append("%s 위치 인자 ≠ 부름" % slot)
    assigns = {}
    for x in ini.body:
        if isinstance(x, ast.Assign) and isinstance(x.targets[0], ast.Attribute) and ast.unparse(x.targets[0].value) == me:
            assigns.setdefault(x.targets[0].attr, []).append(ast.unparse(x.value))
    meth_st = {y.attr for m in c.body if isinstance(m, ast.FunctionDef) and m.name != "__init__" and m.args.args
               for y in ast.walk(m) if isinstance(y, ast.Attribute) and isinstance(y.ctx, (ast.Store, ast.Del))
               and isinstance(y.value, ast.Name) and y.value.id == m.args.args[0].arg}
    stage_st = {(y.value.id, y.attr) for fn in fns.values() for y in ast.walk(fn) if isinstance(y, ast.Attribute)
                and isinstance(y.ctx, (ast.Store, ast.Del)) and isinstance(y.value, ast.Name)}
    for bv, pairs in ents:
        for f, n in pairs:
            if assigns.get(n) != ["%s.%s" % (bv, f)]:
                q4.append("%s.__init__ %s.%s = %s(표 %s.%s)" % (cname, me, n, assigns.get(n), bv, f))
            if n in meth_st:
                q4.append("%s 메서드가 self.%s 다시 대입" % (cname, n))
            if (slot, n) in stage_st:
                q4.append("리플레이가 %s.%s 다시 대입" % (slot, n))
chk(not q4, "Q4 장부 __init__ = 키워드 전용 · 표마다 self.<지역> = <묶음>.<필드> 한 줄 · 그 속성 다시 대입 0", q4)
q4b = []
for bv, us in users.items():
    ok = {id(k.value) for u in us for k in ctor[u][2].value.keywords if k.arg == bv and isinstance(k.value, ast.Name) and k.value.id == bv}
    loads = [y.lineno for fn in fns.values() for y in ast.walk(fn) if isinstance(y, ast.Name) and y.id == bv
             and isinstance(y.ctx, ast.Load) and id(y) not in ok]
    if loads or len(ok) != len(us):
        q4b.append("%s 소비 밖 읽음 %s · 소비 키워드 %d/%d" % (bv, loads, len(ok), len(us)))
chk(not q4b, "Q4 묶음 지역 = 소비 생성자 부름 키워드로만 읽힘", q4b)

q5 = []
for slot, (_s, _i, st, mod, cname) in ctor.items():
    t = mods.setdefault(mod, _parse(mod))
    c = [x for x in t.body if isinstance(x, ast.ClassDef) and x.name == cname][0]
    ini = [f for f in c.body if isinstance(f, ast.FunctionDef) and f.name == "__init__"]
    if not ini:
        continue
    a = ini[0].args
    na = len(a.posonlyargs) + len(a.args) + len(a.kwonlyargs) + bool(a.vararg) + bool(a.kwarg)
    if na > 7:
        q5.append("%s.__init__ %d" % (cname, na))
chk(not q5, "Q5 리플레이 장부 __init__ 인자 ≤ 7(첫 인자 포함)", q5)

prep = fns["_replay_prep"]
q6 = []
for slot, names in AC.ALIASES.items():
    _s, _i, st, mod, cname = ctor[slot]
    t = mods.setdefault(mod, _parse(mod))
    c = [x for x in t.body if isinstance(x, ast.ClassDef) and x.name == cname][0]
    meths = {f.name for f in c.body if isinstance(f, ast.FunctionDef)}
    for n in names:
        al = [x for x in prep.body if isinstance(x, ast.Assign) and len(x.targets) == 1 and isinstance(x.targets[0], ast.Name) and x.targets[0].id == n]
        if len(al) != 1 or ast.unparse(al[0].value) != "%s.%s" % (slot, n) or al[0].lineno <= st.lineno:
            q6.append("prep %s 별칭 %s" % (n, [ast.unparse(x) for x in al]))
        if n not in meths:
            q6.append("%s.%s 메서드 없음" % (cname, n))
        if binds.get(n) != ([al[0].lineno] if al else None):
            q6.append("%s 리플레이 묶음 %s(별칭 한 번이어야 함)" % (n, binds.get(n)))
names6 = {n for v in AC.ALIASES.values() for n in v}
stores6 = []
for f in sorted(os.listdir(T.SRC)):
    if f.endswith(".py"):
        for y in ast.walk(_parse(f[:-3])):
            if isinstance(y, ast.Attribute) and y.attr in names6 and isinstance(y.ctx, (ast.Store, ast.Del)):
                stores6.append("%s:%d" % (f, y.lineno))
chk(not q6 and not stores6, "Q6 offc 별칭 = prep `이름 = ofx.이름` 한 번(생성 뒤) · OffcView 메서드 · 그 이름 속성 대입 0(src 전체)", (q6, stores6))


def _scope(other=None):
    scope, objs, slots = {}, {}, {}
    for slot, ents in AC.INPUTS.items():
        attrs = {}
        for bv, pairs in ents:
            for f, n in pairs:
                scope.setdefault(n, object())
                objs.setdefault(bv, {})[f] = scope[n]
                attrs[n] = object() if other == (slot, n) else scope[n]
        slots[slot] = types.SimpleNamespace(**attrs)
    px = types.SimpleNamespace(**slots)
    scope["px"] = px
    for bv, d in objs.items():
        scope[bv] = types.SimpleNamespace(**d)
    return px, scope


px7, sc7 = _scope()
AC.check_inputs(px7, sc7, "t")
chk(True, "Q7 같은 객체 = 통과")


def _err(fn):
    try:
        fn()
        return None
    except AssertionError as e:
        return str(e)


m1 = _err(lambda: AC.check_inputs(px7, dict(sc7, sale_used=object()), "t1"))
chk(m1 is not None and "salein.sale_used" in m1 and "t1" in m1, "Q7 담긴 이름 다시 묶임 = AssertionError(묶음.필드 · 자리)", m1)
px8, sc8 = _scope(("slx", "xf_wd9"))
m2 = _err(lambda: AC.check_inputs(px8, sc8, "t2"))
chk(m2 is not None and "slx.xf_wd9" in m2, "Q7 장부 속성 다른 객체 = AssertionError", m2)
sc9 = dict(sc7)
del sc9["movein"]
m3 = _err(lambda: AC.check_inputs(px7, sc9, "t3"))
chk(m3 is not None and "movein" in m3, "Q7 이름표에 묶음 없음 = AssertionError", m3)
sc10 = dict(sc7)
del sc10["my_all9"]
m4 = _err(lambda: AC.check_inputs(px7, sc10, "t4"))
chk(m4 is not None and "my_all9" in m4, "Q7 이름표에 담긴 이름 없음 = AssertionError", m4)
cr = [n for n in ast.walk(_parse("accounting_ctx")) if isinstance(n, ast.FunctionDef) and n.name == "check_replay"]
calls = [ast.unparse(x.func) for x in ast.walk(cr[0]) if isinstance(x, ast.Call)] if cr else []
chk("check_inputs" in calls and "check_parts" in calls and "check_ctx" in calls, "Q7 check_replay = check_ctx + check_parts + check_inputs", calls)

T.finish()
