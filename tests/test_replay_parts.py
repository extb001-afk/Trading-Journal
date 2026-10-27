#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import collections  # noqa: E402
import os  # noqa: E402
import types  # noqa: E402

import accounting_ctx as AC  # noqa: E402

chk = T.chk
STAGES = ("_replay_prep", "_replay_links", "_replay_main")


def _parse(mod):
    with open(os.path.join(T.SRC, mod + ".py"), encoding="utf-8") as f:
        return ast.parse(f.read(), mod + ".py")


rp = _parse("view_b_replay")
fns = {m.name: m for n in ast.walk(rp) if isinstance(n, ast.ClassDef) for m in n.body if isinstance(m, ast.FunctionDef) and m.name in STAGES}
chk(set(fns) == set(STAGES), "리플레이 단계 함수 3개", sorted(fns))
prep = fns["_replay_prep"]

mk = []
for sname in STAGES:
    for n in ast.walk(fns[sname]):
        if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute)
                and isinstance(n.value.func.value, ast.Name) and n.value.func.value.id.startswith("accounting_")
                and n.value.func.attr[:1].isupper() and isinstance(n.targets[0], ast.Name)):
            mk.append((n.lineno, n.targets[0].id, n.value.func.value.id, n.value.func.attr, n))
mk.sort(key=lambda x: x[0])
books = [x for x in mk if x[3] == "Books"]
parts = [x for x in mk if x[3] == "ReplayParts"]
pos = {id(st): i for i, st in enumerate(prep.body)}
ok1 = (len(books) == 1 and len(parts) == 1 and id(books[0][4]) in pos and id(parts[0][4]) in pos
       and pos[id(parts[0][4])] == pos[id(books[0][4])] + 1 and parts[0][1] == "px"
       and not parts[0][4].value.args and {k.arg: ast.unparse(k.value) for k in parts[0][4].value.keywords} == {"sb": "self", "books": "books"})
chk(ok1, "P1 prep: books 바로 다음 문장 = px = accounting_ctx.ReplayParts(sb=self, books=books)", [(x[0], x[1], x[3]) for x in books + parts])
cbst = prep.body[pos[id(parts[0][4])] + 1] if parts and id(parts[0][4]) in pos else None
chk(isinstance(cbst, ast.Assign) and [ast.unparse(t) for t in cbst.targets] == ["cb", "px.cb"]
    and ast.unparse(cbst.value) == "accounting_basis.StrictCostBasis() if calcguard.strict() else accounting_basis.CostBasis()",
    "P1 prep: px 바로 다음 문장 = 원가 장부 cb = px.cb(엄격 = StrictCostBasis · 그 뒤 모든 장부 생성·gstate 부름보다 앞)", cbst and ast.unparse(cbst)[:120])
cbb = [(sn, n.lineno) for sn, f in fns.items() for n in ast.walk(f) if isinstance(n, ast.Name) and n.id == "cb" and isinstance(n.ctx, ast.Store)]


def _head_cb(f):
    b9 = f.body[1:] if f.body and isinstance(f.body[0], ast.Expr) and isinstance(f.body[0].value, ast.Constant) else f.body
    st = b9[0] if b9 else None
    if not (isinstance(st, ast.Assign) and isinstance(st.targets[0], ast.Tuple) and isinstance(st.value, ast.Tuple)):
        return None
    pair = {getattr(t, "id", None): ast.unparse(v) for t, v in zip(st.targets[0].elts, st.value.elts)}
    return st.lineno if pair.get("cb") in ("_bs9['cb']", "li.cb") else None


heads9 = {sn: _head_cb(fns[sn]) for sn in ("_replay_links", "_replay_main")}
chk([x for x in cbb if x[0] == "_replay_prep"] == [("_replay_prep", cbst.lineno if cbst else None)]
    and sorted(x for x in cbb if x[0] != "_replay_prep") == sorted(heads9.items()) and all(heads9.values()),
    "P1 cb 묶음 = prep 1번 + 뒤 단계(links·main)는 머리 풀기의 이름표 cb(같은 객체 · 7-4 원가 칸 쓰기 받는 쪽) 말고 다시 묶지 않음", (cbb, heads9))
pxb = [n.lineno for f in fns.values() for n in ast.walk(f) if isinstance(n, ast.Name) and n.id == "px" and isinstance(n.ctx, ast.Store)]
chk(len(pxb) == 1 + sum(1 for s in STAGES[1:] if any(isinstance(x, ast.Name) and x.id == "px" for st in fns[s].body[:2]
                                                    if isinstance(st, ast.Assign) and isinstance(st.targets[0], ast.Tuple) for x in st.targets[0].elts)),
    "P1 px 묶음 = prep 1번 + 뒤 단계 머리 풀기뿐(다시 묶지 않음)", pxb)
ledgers = [x for x in mk if x[3] not in ("Books", "ReplayParts") and not (x[2] == "accounting_ctx" and x[3] != "ReplayCtx")]
bad = [x[1] for x in ledgers if not (len(x[4].targets) == 2 and ast.unparse(x[4].targets[1]) == "px." + x[1])]
chk(not bad, "P1 장부 생성 = `X = px.X = accounting_m.Cls(…)`(같은 문장에서 채움)", bad)
fill_line = {x[1]: x[0] for x in ledgers}
fill_line.update(sb=parts[0][0] if parts else 0, books=parts[0][0] if parts else 0)
slots = set(AC.ReplayParts.__slots__)
cnt = collections.Counter(x[1] for x in ledgers)
chk(set(cnt) == slots - {"sb", "books", "cb"} and all(v == 1 for v in cnt.values()), "P1 묶음 칸 = sb·books·cb + 장부마다 채움 1번", dict(cnt))
px0 = AC.ReplayParts(sb=object(), books=object())
try:
    px0.cpx
    unf = False
except AttributeError:
    unf = True
try:
    px0.other = 1
    nos = False
except AttributeError:
    nos = True
chk(unf and nos, "P1 채우기 전 읽기 = AttributeError · 칸 밖 속성 대입 = AttributeError(__slots__)")

cls_of = {x[1]: (x[2], x[3]) for x in ledgers}
call_of = {x[1]: x[4].value for x in ledgers}
inits, mods = {}, {}
for v, (mod, cname) in cls_of.items():
    t = mods.setdefault(mod, _parse(mod))
    c = [c for c in t.body if isinstance(c, ast.ClassDef) and c.name == cname]
    fi = [f for f in c[0].body if isinstance(f, ast.FunctionDef) and f.name == "__init__"]
    if fi:
        inits[v] = (c[0], fi[0])
    else:
        chk(not call_of[v].args, "P2 %s(__init__ 없는 dataclass) 는 px 를 받지 않음" % cname)


def _src_of(e):
    if isinstance(e, ast.Attribute) and isinstance(e.value, ast.Attribute) and isinstance(e.value.value, ast.Name) and e.value.value.id == "px":
        return ("px", e.value.attr, e.attr)
    if isinstance(e, ast.Attribute) and isinstance(e.value, ast.Name) and e.value.id == "px":
        return ("px", e.attr)
    if isinstance(e, ast.Attribute) and isinstance(e.value, ast.Name) and e.value.id == "accounting_util":
        return ("mod", "accounting_util", e.attr)
    return None


got, srcs, sig_bad, order_bad, self_px = {}, {}, [], [], []
for v, (_c, f) in inits.items():
    me = f.args.args[0].arg
    takes = [a.arg for a in f.args.args[1:]] == ["px"]
    called = bool(call_of[v].args) and ast.unparse(call_of[v].args[0]) == "px"
    if takes != called or (takes and (f.args.args[1:] and not (len(call_of[v].args) == 1))):
        sig_bad.append(v)
    if not takes:
        continue
    names = []
    for st in f.body:
        if isinstance(st, ast.Assign) and isinstance(st.targets[0], ast.Attribute) and ast.unparse(st.targets[0].value) == me:
            s9 = _src_of(st.value)
            if st.targets[0].attr == "px" or (isinstance(st.value, ast.Name) and st.value.id == "px"):
                self_px.append(v)
            if s9:
                names.append(st.targets[0].attr)
                srcs[(v, st.targets[0].attr)] = s9
                if s9[0] == "px" and len(s9) == 3 and fill_line.get(s9[1], 10 ** 9) >= fill_line[v]:
                    order_bad.append("%s.%s ← px.%s(채움 줄 %s ≥ %s)" % (v, st.targets[0].attr, s9[1], fill_line.get(s9[1]), fill_line[v]))
    got[v] = tuple(names)
chk(not sig_bad, "P2 px 를 받는 장부 = 부름 첫 위치 인자 px 하나 · 나머지 키워드(서명 = (self, px, *, …))", sig_bad)
chk(got == AC.INJECT, "P2 주입 표 INJECT = __init__ 의 px·accounting_util 대입(이름·순서)", sorted(set(got.items()) ^ set(AC.INJECT.items()))[:6])
kwonly = {v: [a.arg for a in inits[v][1].args.kwonlyargs] for v in AC.INJECT}
kwcall = {v: [k.arg for k in call_of[v].keywords] for v in AC.INJECT}
chk(kwonly == kwcall and all(not set(kwonly[v]) & set(AC.INJECT[v]) for v in AC.INJECT),
    "P2 남은 인자 = 키워드 전용 매개변수 = 부름 키워드(같은 순서) · 주입 이름과 겹침 0", {v: sorted(set(kwonly[v]) ^ set(kwcall[v])) for v in AC.INJECT})
chk(not order_bad, "P2 주입 원천 px.<풀> 은 그 생성보다 앞에서 채워짐", order_bad)
selfpx = [n.lineno for n in ast.walk(rp) if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store) and ast.unparse(n) == "self.px"]
chk(not self_px and not selfpx, "P2 장부·빌더가 px 자신을 속성으로 쥐지 않음(빌더·장부 속성 집합 무변)", (self_px, selfpx))

stage_stores = collections.defaultdict(list)
for f in fns.values():
    for n in ast.walk(f):
        if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name):
                    stage_stores[(t.value.id, t.attr)].append(n.lineno)


def _method_stores(v):
    if v not in inits:
        return set()
    c, _f = inits[v]
    out = set()
    for m in c.body:
        if isinstance(m, ast.FunctionDef) and m.name != "__init__" and m.args.args:
            me = m.args.args[0].arg
            for n in ast.walk(m):
                if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                    for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                        if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == me:
                            out.add(t.attr)
    return out


re_bad = []
late_line = {}
for p, names in AC.LATE_WIRES.items():
    for a in names:
        late_line[(p, a)] = stage_stores.get((p, a), [None])[0]
for (v, n), s9 in srcs.items():
    if stage_stores.get((v, n)):
        re_bad.append("리플레이 %s.%s = (줄 %s)" % (v, n, stage_stores[(v, n)]))
    if n in _method_stores(v):
        re_bad.append("%s 메서드 self.%s =" % (v, n))
    if s9[0] == "px" and len(s9) == 3 and s9[1] == "books" and stage_stores.get(("books", s9[2])):
        re_bad.append("원천 books.%s 리플레이 대입" % s9[2])
    if s9[0] == "px" and len(s9) == 3 and s9[1] in cls_of:
        q, a = s9[1], s9[2]
        st9 = stage_stores.get((q, a), [])
        if st9 and not ((q, a) in late_line and st9 == [late_line[(q, a)]] and st9[0] < fill_line[v]):
            re_bad.append("원천 %s.%s 리플레이 대입 %s" % (q, a, st9))
        if a in _method_stores(q):
            re_bad.append("원천 %s 메서드 self.%s =" % (q, a))
chk(not re_bad, "P3 주입 속성·주입 원천 속성 다시 대입 0(원천의 늦은 연결 한 번은 그 생성 전)", re_bad[:20])

late = collections.defaultdict(list)
for f in fns.values():
    for n in ast.walk(f):
        if (isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Attribute)
                and isinstance(n.targets[0].value, ast.Name) and n.targets[0].value.id in fill_line
                and n.lineno > fill_line[n.targets[0].value.id]):
            late[n.targets[0].value.id].append((n.lineno, n.targets[0].attr, ast.unparse(n.value)))
late_t = {p: tuple(a for _l, a, _v in sorted(xs)) for p, xs in late.items()}
vals_bad = [(p, a, v9) for p, xs in late.items() for _l, a, v9 in xs if v9 != a]
chk(late_t == AC.LATE_WIRES and sum(len(x) for x in AC.LATE_WIRES.values()) == 38,
    "P4 늦은 연결 = 표 LATE_WIRES(38 · 장부별 문장 순서) — 새 늦은 연결은 표에 올리고 검토", sorted(set(late_t.items()) ^ set(AC.LATE_WIRES.items()))[:6])
chk(not vals_bad, "P4 늦은 연결 값 = 같은 이름 지역(맨 이름)", vals_bad[:6])
chk(all(a in AC.LATE_WIRES.get(p, ()) and q in slots for p, a, q in AC.CYCLE), "P4 순환(FirstSeen↔UnkBook) ⊆ 늦은 연결 표", AC.CYCLE)


class _Q:
    def m(self):
        return 1


q9 = _Q()
pxu = AC.ReplayParts(sb=object(), books=object())
scope = {"self": pxu.sb, "px": pxu}
attrs = collections.defaultdict(dict)
for tab in (AC.INJECT, AC.LATE_WIRES, AC.ALIASES, AC.HELD):
    for s, names in tab.items():
        for n in names:
            if n == "sb":
                attrs[s]["sb"] = pxu.sb
            elif n == "cp_emit" or tab is AC.ALIASES:
                scope[n] = q9.m
                attrs[s][n] = q9.m
            else:
                attrs[s][n] = scope.setdefault(n, object())
ns = {s: types.SimpleNamespace(**attrs[s]) for s in AC.ReplayParts.__slots__ if s not in ("sb", "books", "cb")}
(pxu.ctx, pxu.fbx, pxu.ofx, pxu.kpx, pxu.unx, pxu.fsx, pxu.orx, pxu.cpx, pxu.lpx, pxu.slx, pxu.lnx, pxu.omx) = (
    ns["ctx"], ns["fbx"], ns["ofx"], ns["kpx"], ns["unx"], ns["fsx"], ns["orx"], ns["cpx"], ns["lpx"], ns["slx"], ns["lnx"], ns["omx"])
chk(scope["cp_emit"] is not pxu.lnx.cp_emit and scope["cp_emit"] == pxu.lnx.cp_emit, "P5 (준비) 묶인 메서드 = 다른 객체 · ==")
AC.check_parts(pxu, scope, "t")
chk(True, "P5 같은 객체(묶인 메서드는 다시 만든 것 ==) = 통과")
try:
    AC.check_parts(pxu, dict(scope, krw_mix=object()), "t2")
    m2 = None
except AssertionError as e:
    m2 = str(e)
chk(m2 is not None and "krw_mix" in m2 and "t2" in m2, "P5 데이터 다시 묶임 = AssertionError(자리·이름)", m2)
try:
    AC.check_parts(pxu, dict(scope, cp_emit=_Q().m), "t3")
    m3 = None
except AssertionError as e:
    m3 = str(e)
chk(m3 is not None and "cp_emit" in m3, "P5 다른 객체의 묶인 메서드 = AssertionError", m3)
try:
    AC.check_parts(pxu, dict(scope, offc_s=lambda ex9: None), "t3b")
    m3b = None
except AssertionError as e:
    m3b = str(e)
chk(m3b is not None and "offc_s" in m3b, "P5 메서드 별칭(ALIASES) 자리에 함수(옛 클로저) = AssertionError", m3b)
try:
    AC.check_parts(pxu, dict(scope, cb=object()), "t3c")
    m3c = None
except AssertionError as e:
    m3c = str(e)
chk(m3c is not None and "fbx.cb" in m3c and "unx.cb" in m3c and "cpx.cb" in m3c, "P5 원가 장부 cb 다른 객체(주입 INJECT · 생성자 키워드 HELD) = AssertionError", m3c)
sc4 = dict(scope)
del sc4["krw_stl"]
try:
    AC.check_parts(pxu, sc4, "t4")
    m4 = None
except AssertionError as e:
    m4 = str(e)
chk(m4 is not None and "krw_stl" in m4, "P5 이름표에 없음 = AssertionError", m4)
cx = AC.ReplayCtx(conn=object(), prefs={}, fb_on=False, fs_pref=True, fs_on=True, gas_on=True, offc_on=set(), offc_ans=set(), offc_excl=set(),
                  now=1.0, today_kst=object(), fxb=object())
try:
    AC.check_replay(cx, {}, "t5")
    k5 = False
except KeyError:
    k5 = True
chk(k5, "P5 check_replay = 이름표에 px 없으면 KeyError(조용히 건너뛰지 않음)")

T.finish()
