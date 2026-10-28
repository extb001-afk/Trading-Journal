#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import dataclasses  # noqa: E402
import os  # noqa: E402

import accounting_ctx as AC  # noqa: E402

chk = T.chk
STAGES = ("_replay_prep", "_replay_links", "_replay_main")
INF = 10 ** 9


def _parse(mod):
    with open(os.path.join(T.SRC, mod + ".py"), encoding="utf-8") as f:
        return ast.parse(f.read(), mod + ".py")


rp = _parse("view_b_replay")
fns = {m.name: m for n in ast.walk(rp) if isinstance(n, ast.ClassDef) for m in n.body if isinstance(m, ast.FunctionDef) and m.name in STAGES}
chk(set(fns) == set(STAGES), "리플레이 단계 함수 3개", sorted(fns))
in_cls = {}
for c in _parse("accounting_ctx").body:
    if isinstance(c, ast.ClassDef) and c.name in ("FsIn", "OriginIn", "OffcIn", "LpIn", "SaleIn", "MoveIn", "ReplayFns"):
        in_cls[c.name] = c


STAGE_IO = ("li", "lko", "pre")


def _bs9_rooted(v):
    while isinstance(v, (ast.Attribute, ast.Subscript)):
        if isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name) and v.value.id in STAGE_IO:
            return True
        v = v.value
    return False


def _binds(fn, sname, out):
    for a in fn.args.args[1:] + fn.args.kwonlyargs:
        if a.arg not in STAGE_IO:
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


def _fld(n):
    n = n[1:] if n.startswith("_") else n
    return n[:-1] if n.endswith("9") else n


def bundle_kw(call):
    kw = [(k.arg, k.value.id if isinstance(k.value, ast.Name) else None) for k in call.keywords]
    bad9 = [(f, n) for f, n in kw if n is None or f != _fld(n)]
    return kw, (bad9 or (["위치 인자"] if call.args else []))


def consumer_bad(call, bundles):
    return ["%s=%s" % (k.arg, ast.unparse(k.value)) for k in call.keywords
            if k.arg in bundles and not (isinstance(k.value, ast.Name) and k.value.id == k.arg)]


def _call(src):
    return ast.parse(src).body[0].value


want_kw = {}
q1 = []
for bv, (_s, _i, st) in mk.items():
    want_kw[bv], bad9 = bundle_kw(st.value)
    if bad9:
        q1.append("%s 키워드 %s(위치 인자 · 맨 이름 아님 · 필드 ≠ 지역 규약)" % (bv, bad9))
users = {}
for v9, (_s, _i, st, _m, _c) in ctor.items():
    users_k = [k.arg for k in st.value.keywords if k.arg in mk]
    for b9 in users_k:
        users.setdefault(b9, []).append(v9)
    q1 += ["%s 생성 키워드 %s(같은 이름 묶음 지역이어야 함)" % (v9, x) for x in consumer_bad(st.value, mk)]
chk(bundle_kw(_call("accounting_ctx.FsIn(fs_spec=fs_floor9, fs_lo=fs_lo9)"))[1] == [("fs_spec", "fs_floor9")],
    "Q1 (합성) 필드 ≠ 지역 규약(이름 엇갈린 연결) = 잡힘")
chk(bundle_kw(_call("accounting_ctx.SaleIn(ro=_ro, xf_wd=xf_wd9, diag=diag)"))[1] == [] and bundle_kw(_call("accounting_ctx.LpIn(x.lpb)"))[1],
    "Q1 (합성) 앞 밑줄·끝 9 뗀 같은 이름 = 통과 · 위치 인자 = 잡힘")
chk(consumer_bad(_call("accounting_sale.SaleBook(px, salein=movein, fns=fns)"), {"salein", "fns", "movein"}) == ["salein=movein"],
    "Q1 (합성) 장부 생성 묶음 키워드 다른 묶음 연결 = 잡힘")
chk(set(users) == set(mk) and len(mk) == len(in_cls), "Q1 묶음 클래스마다 묶음 문장 하나 · 묶음마다 소비 생성자 1개 이상",
    (sorted(set(mk) ^ set(users)), len(mk), len(in_cls)))
for bv, (sname, i, st) in mk.items():
    first = min(users.get(bv, ["?"]), key=lambda u: ctor[u][2].lineno if u in ctor else INF)
    if first not in ctor or ctor[first][0] != sname:
        q1.append("%s 첫 소비 %s 가 같은 단계 생성이 아님" % (bv, first))
        continue
    j = ctor[first][1]
    between = fns[sname].body[i + 1:j]
    if j <= i or any(id(b) not in {id(m[2]) for m in mk.values()} for b in between):
        q1.append("%s(몸통 %d) 가 첫 소비 %s(몸통 %d) 바로 앞이 아님" % (bv, i, first, j))
q1s = [x for x in (_fld("fs_spec9"), _fld("_ro"), _fld("my_all9"), _fld("conn"))]
chk(not q1 and q1s == ["fs_spec", "ro", "my_all", "conn"], "Q1 묶음 문장 = 첫 소비 생성자 바로 앞(사이엔 묶음 문장뿐) · 키워드 = 맨 이름 · 필드 = 지역 규약", q1)
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
    if fl != order:
        q2.append("%s 필드 %s ≠ 묶음 문장 순서 %s" % (cname, fl, order))
    if any(f.default is not dataclasses.MISSING or f.default_factory is not dataclasses.MISSING for f in dataclasses.fields(cls)):
        q2.append("%s 기본값 있음" % cname)
    if any(n == "gstate" for _f, n in want_kw[bv]):
        q2.append("%s 에 gstate(원가 지문 기록기 자리)" % cname)
chk(not q2, "Q2 묶음 클래스 = frozen·eq=False·repr=False dataclass · 필드 = 묶음 문장 키워드(순서) · 기본값 없음 · gstate 없음", q2)
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
stage_st = {(y.value.id, y.attr) for fn in fns.values() for y in ast.walk(fn) if isinstance(y, ast.Attribute)
            and isinstance(y.ctx, (ast.Store, ast.Del)) and isinstance(y.value, ast.Name)}


def init_takes(ini, mine, kw_of):
    me = ini.args.args[0].arg
    took, bad, good = [], [], set()
    for x in ini.body:
        if (isinstance(x, ast.Assign) and len(x.targets) == 1 and isinstance(x.targets[0], ast.Attribute) and ast.unparse(x.targets[0].value) == me
                and isinstance(x.value, ast.Attribute) and isinstance(x.value.value, ast.Name) and x.value.value.id in mine):
            bv, f = x.value.value.id, x.value.attr
            loc = dict(kw_of[bv]).get(f)
            took.append((x.targets[0].attr, bv, f))
            good.add(id(x.value.value))
            if loc is None or x.targets[0].attr != loc:
                bad.append("%s.%s = %s.%s(속성 이름 = 그 필드의 지역 %s 이어야 함)" % (me, x.targets[0].attr, bv, f, loc))
    for a9 in sorted({x[0] for x in took}):
        w9 = [y.lineno for y in ast.walk(ini) if isinstance(y, ast.Attribute) and isinstance(y.ctx, (ast.Store, ast.Del)) and ast.unparse(y.value) == me and y.attr == a9]
        if len(w9) != 1:
            bad.append("%s.%s 생성자 쓰기·삭제 %d번" % (me, a9, len(w9)))
    other = [y.lineno for y in ast.walk(ini) if isinstance(y, ast.Name) and y.id in mine and id(y) not in good]
    if other:
        bad.append("묶음을 `self.<지역> = <묶음>.<필드>` 밖에서 읽음 %s" % other)
    return took, bad


def _init(src):
    return ast.parse(src).body[0]


KW9 = {"salein": [("wd_tr", "wd_tr"), ("xf_wd", "xf_wd9")]}
t9, b9 = init_takes(_init("def __init__(slx, px, *, salein):\n    slx.wd_tr = salein.wd_tr\n    slx.xf_wd9 = salein.xf_wd\n"), {"salein"}, KW9)
chk(not b9 and [x[2] for x in t9] == ["wd_tr", "xf_wd"], "Q4 (합성) 필드마다 그 지역 이름 속성 = 통과(필드 둘 꺼냄)")
chk(init_takes(_init("def __init__(slx, px, *, salein):\n    slx.wd_tr = salein.xf_wd\n"), {"salein"}, KW9)[1],
    "Q4 (합성) 속성 이름 ≠ 그 필드의 지역(엇갈린 꺼냄) = 잡힘")
chk(init_takes(_init("def __init__(slx, px, *, salein):\n    slx.wd_tr = salein.wd_tr\n    slx.inb = salein\n"), {"salein"}, KW9)[1],
    "Q4 (합성) 묶음 통째로 쥠 = 잡힘")
chk(init_takes(_init("def __init__(slx, px, *, salein):\n    slx.wd_tr = salein.wd_tr\n    slx.xf_wd9 = salein.xf_wd\n    slx.wd_tr = slx.xf_wd9\n"), {"salein"}, KW9)[1],
    "Q4 (합성) 꺼낸 속성을 생성자 안에서 다른 값으로 바꿈 = 잡힘")
taken = {bv: [] for bv in mk}
for slot in sorted({u for us in users.values() for u in us}):
    _s, _i, st, mod, cname = ctor[slot]
    t = mods.setdefault(mod, _parse(mod))
    c = [x for x in t.body if isinstance(x, ast.ClassDef) and x.name == cname][0]
    ini = [f for f in c.body if isinstance(f, ast.FunctionDef) and f.name == "__init__"][0]
    if [k.arg for k in st.value.keywords] != [a.arg for a in ini.args.kwonlyargs]:
        q4.append("%s 부름 키워드 ≠ __init__ 키워드 전용" % slot)
    if [a.arg for a in ini.args.args[1:]] != [k.id for k in st.value.args if isinstance(k, ast.Name)]:
        q4.append("%s 위치 인자 ≠ 부름" % slot)
    took, bad = init_takes(ini, [bv for bv, us in users.items() if slot in us], want_kw)
    q4 += ["%s.__init__ %s" % (cname, x) for x in bad]
    for a9, bv, f in took:
        taken[bv].append(f)
        if (slot, a9) in stage_st:
            q4.append("리플레이가 %s.%s 다시 대입" % (slot, a9))
for bv, fs in taken.items():
    if sorted(fs) != sorted(f for f, _n in want_kw[bv]):
        q4.append("%s 꺼낸 필드 %s ≠ 묶음 필드(소비자 합 · 한 번씩)" % (bv, sorted(fs)))
meth_w = []
for slot in sorted({u for us in users.values() for u in us}):
    _s, _i, st, mod, cname = ctor[slot]
    c = [x for x in mods[mod].body if isinstance(x, ast.ClassDef) and x.name == cname][0]
    meth_w += ["%s.%s" % (cname, y.attr) for m in c.body if isinstance(m, ast.FunctionDef) and m.name != "__init__" and m.args.args
               for y in ast.walk(m) if isinstance(y, ast.Attribute) and isinstance(y.ctx, (ast.Store, ast.Del))
               and isinstance(y.value, ast.Name) and y.value.id == m.args.args[0].arg]
chk(not q4 and not meth_w, "Q4 장부 __init__ = 키워드 전용 · 묶음 필드마다 self.<지역> = <묶음>.<필드> 한 줄(소비자 합 = 필드 전부) · 그 속성 다시 대입 0", (q4, meth_w[:6]))
q4b = []


def _export_kw(fn):
    out = set()
    for c in ast.walk(fn):
        if isinstance(c, ast.Call) and getattr(c.func, "id", "") in ("LinksIn", "LinksOut", "RtIn", "RtOut", "PrepOut"):
            out |= {id(k.value) for k in c.keywords if isinstance(k.value, ast.Name)}
    return out


EXPORT_KW = set().union(*(_export_kw(fn) for fn in fns.values()))
for bv, us in users.items():
    ok = {id(k.value) for u in us for k in ctor[u][2].value.keywords if k.arg == bv and isinstance(k.value, ast.Name) and k.value.id == bv}
    loads = [y.lineno for fn in fns.values() for y in ast.walk(fn) if isinstance(y, ast.Name) and y.id == bv
             and isinstance(y.ctx, ast.Load) and id(y) not in ok and id(y) not in EXPORT_KW]
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
_s, _i, ost, omod, ocname = ctor["ofx"]
oc = [x for x in mods.setdefault(omod, _parse(omod)).body if isinstance(x, ast.ClassDef) and x.name == ocname][0]
ometh = {f.name for f in oc.body if isinstance(f, ast.FunctionDef) and not f.name.startswith("_")}


def alias_bad(pfn, owner, meths, after):
    used = {n.id for n in ast.walk(pfn) if isinstance(n, ast.Name)} | {n.name for n in ast.walk(pfn) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    b9 = {}
    _binds(pfn, pfn.name, b9)
    out = []
    for n in sorted(meths & used):
        al = [x for x in pfn.body if isinstance(x, ast.Assign) and len(x.targets) == 1 and isinstance(x.targets[0], ast.Name) and x.targets[0].id == n]
        if len(al) != 1 or ast.unparse(al[0].value) != "%s.%s" % (owner, n) or al[0].lineno <= after:
            out.append("%s 별칭 %s" % (n, [ast.unparse(x) for x in al]))
        elif b9.get(n) != [al[0].lineno]:
            out.append("%s 묶음 %s(별칭 한 번이어야 함)" % (n, b9.get(n)))
    return sorted(meths & used), out


names6, q6 = alias_bad(prep, "ofx", ometh, ost.lineno)
syn6 = ast.parse("def _replay_prep(self, conn):\n    ofx = 1\n    offc_s = ofx.offc_s\n    def offc_add(a):\n        return a\n    offc_add(offc_s)\n").body[0]
chk(alias_bad(syn6, "ofx", {"offc_s", "offc_add"}, 2)[1] == ["offc_add 별칭 []"] and not alias_bad(syn6, "ofx", {"offc_s"}, 2)[1],
    "Q6 (합성) 옛 클로저 def 로 남은 메서드 이름 = 잡힘 · 별칭 한 번 = 통과")
stores6 = []
for f in sorted(os.listdir(T.SRC)):
    if f.endswith(".py"):
        for y in ast.walk(_parse(f[:-3])):
            if isinstance(y, ast.Attribute) and y.attr in names6 and isinstance(y.ctx, (ast.Store, ast.Del)):
                stores6.append("%s:%d" % (f, y.lineno))
chk(names6 and not q6 and not stores6, "Q6 offc 별칭(%s) = prep `이름 = ofx.이름` 한 번(생성 뒤 · 유일 묶음) · 그 이름 속성 대입 0(src 전체)" % " · ".join(names6),
    (q6, stores6))

T.finish()
