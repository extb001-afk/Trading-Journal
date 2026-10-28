#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import collections  # noqa: E402
import os  # noqa: E402

import accounting_books  # noqa: E402
import accounting_ctx as AC  # noqa: E402

chk = T.chk
LATE2 = {"fbx": ("wd_raw9",), "cpx": ("xc_tok9",)}
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
    return st.lineno if pair.get("cb") in ("li.cb", "pre.cb") else None


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
fill_line["cb"] = cbst.lineno if cbst is not None else 0
slots = set(AC.ReplayParts.__slots__)
cnt = collections.Counter(x[1] for x in ledgers)
R4 = slots - {"sb", "books", "cb"} - set(cnt)
chk(set(cnt) | R4 | {"sb", "books", "cb"} == slots and all(v == 1 for v in cnt.values()) and len(R4) == 5,
    "P1 묶음 칸 = sb·books·cb + 장부마다 채움 1번 + R4 데이터 칸 5", (dict(cnt), sorted(R4)))
HEADS = ("li", "lko", "pre")


def _rooted(v):
    while isinstance(v, (ast.Attribute, ast.Subscript)):
        v = v.value
    return isinstance(v, ast.Name) and v.id in HEADS


r4_fill, r4_bind, r4_bad = collections.defaultdict(list), collections.defaultdict(list), []
for sname in STAGES:
    for n in ast.walk(fns[sname]):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in R4:
            r4_bind[n.name].append((n.lineno, "def"))
        if not isinstance(n, ast.Assign):
            continue
        for t in n.targets:
            if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "px" and t.attr in R4:
                r4_fill[t.attr].append((n.lineno, n))
            if isinstance(t, ast.Name) and t.id in R4:
                r4_bind[t.id].append((n.lineno, "dual" if len(n.targets) == 2 else "single"))
            elif isinstance(t, (ast.Tuple, ast.List)):
                vals = n.value.elts if isinstance(n.value, (ast.Tuple, ast.List)) and len(n.value.elts) == len(t.elts) else [None] * len(t.elts)
                for a, b in zip(t.elts, vals):
                    if isinstance(a, ast.Name) and a.id in R4 and not (b is not None and _rooted(b)):
                        r4_bind[a.id].append((n.lineno, "tuple"))
r4_writes, r4_names, r4_skip = collections.defaultdict(list), collections.defaultdict(list), set()
for sname in STAGES:
    for n in ast.walk(fns[sname]):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, (ast.Tuple, ast.List)) and isinstance(n.value, (ast.Tuple, ast.List)) and len(n.value.elts) == len(t.elts):
                    r4_skip |= {id(a) for a, b in zip(t.elts, n.value.elts) if isinstance(a, ast.Name) and _rooted(b)}
    for n in ast.walk(fns[sname]):
        if isinstance(n, ast.Attribute) and isinstance(n.ctx, (ast.Store, ast.Del)) and isinstance(n.value, ast.Name) and n.value.id == "px" and n.attr in R4:
            r4_writes[n.attr].append(n.lineno)
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)) and n.id in R4 and id(n) not in r4_skip:
            r4_names[n.id].append(n.lineno)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in R4:
            r4_names[n.name].append(n.lineno)
for x in sorted(R4):
    f9, b9 = r4_fill.get(x, []), r4_bind.get(x, [])
    if len(f9) == 1 and not b9 and not r4_names.get(x):
        fl, fst = f9[0]
        if [ast.unparse(t) for t in fst.targets] != ["px." + x] or r4_writes.get(x) != [fl]:
            r4_bad.append("%s 칸만 꼴 %s · 칸 쓰기·삭제 %s" % (x, ast.unparse(fst)[:80], r4_writes.get(x)))
        fill_line[x] = fl
        continue
    if len(f9) != 1 or len(b9) != 1:
        r4_bad.append("%s 채움 %d · 묶음 %s" % (x, len(f9), b9))
        continue
    (fl, fst), (bl, bk) = f9[0], b9[0]
    if r4_writes.get(x) != [fl] or r4_names.get(x) != [bl]:
        r4_bad.append("%s 칸 쓰기·삭제 %s(채움 줄 %d) · 이름 묶음 %s(묶음 줄 %d)" % (x, r4_writes.get(x), fl, r4_names.get(x), bl))
    tg = [ast.unparse(t) for t in fst.targets]
    if tg == [x, "px." + x]:
        ok = bk == "dual" and bl == fl
    else:
        ok = tg == ["px." + x] and ast.unparse(fst.value) == x and bk in ("def", "tuple") and bl < fl
    if not ok:
        r4_bad.append("%s 꼴 %s(묶음 %s 줄 %d)" % (x, ast.unparse(fst)[:80], bk, bl))
    fill_line[x] = fl
chk(not r4_bad, "P1 R4 칸 = `X = px.X = …` 또는 def·튜플 풀기 뒤 `px.X = X` 또는 지역 없이 `px.X = …` · 채움 1번 · 그 이름 리플레이 묶음 1번 이하(머리 풀기 뺌)", r4_bad)
sb0, books0 = object(), accounting_books.Books()
px0 = AC.ReplayParts(sb=sb0, books=books0)
chk(px0.sb is sb0 and px0.books is books0, "P1 고정 칸 sb·books = 묶음 생성자가 받은 객체 그대로(복사·새로 만들기 0)")
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


BOOKS_F = set(accounting_books.Books.names())
CTX_F = set(AC.ReplayCtx.names())


def _fixed_bad(a9, val, me=None):
    s0 = _src_of(val)
    need = ("px", "books", a9) if a9 in BOOKS_F else ("px", a9) if a9 in ("sb", "cb") else ("px", "ctx", a9) if a9 in CTX_F else None
    ctx_ok = a9 in CTX_F and ((isinstance(val, ast.Name) and val.id == a9) or (isinstance(val, ast.Attribute) and val.attr == a9
                                                                                and isinstance(val.value, ast.Name) and val.value.id not in (me, "px")))
    if need is not None and s0 != need and not ctx_ok:
        return "%s ← %s(고정 칸 이름은 그 칸에서만)" % (a9, ast.unparse(val)[:60])
    if not any((isinstance(y, ast.Name) and y.id in ("px", "accounting_util")) or (isinstance(y, ast.Attribute) and y.attr == "px") for y in ast.walk(val)):
        return None
    s9 = _src_of(val)
    if s9 in (("px", "sb"), ("px", "cb")) and a9 == s9[1]:
        return None
    if s9 and len(s9) == 3 and s9[0] == "px" and ((s9[1] == "books" and s9[2] in BOOKS_F) or (s9[1] == "ctx" and s9[2] in CTX_F)) and a9 == s9[2]:
        return None
    return "%s ← %s" % (a9, ast.unparse(val)[:60])


fx_bad = [x for x in (_fixed_bad("realized_by_date", ast.parse("px.books.realized_krw_by_date").body[0].value),
                      _fixed_bad("consume", ast.parse("px.cpx.consume").body[0].value),
                      _fixed_bad("flow_of", ast.parse("px.flow_of").body[0].value),
                      _fixed_bad("cp_pool", ast.parse("accounting_util.cp_pool").body[0].value),
                      _fixed_bad("ev", ast.parse("getattr(px.cpx, 'ev')").body[0].value),
                      _fixed_bad("ex_fee", ast.parse("fbx.px.books.ex_fee_m").body[0].value),
                      _fixed_bad("realized_krw_by_date", ast.parse("lpx.realized_by_date").body[0].value)) if x]
fx_ok = [_fixed_bad("tax_rows", ast.parse("px.books.tax_rows").body[0].value), _fixed_bad("fxb", ast.parse("px.ctx.fxb").body[0].value),
         _fixed_bad("cb", ast.parse("px.cb").body[0].value), _fixed_bad("rows", ast.parse("rows").body[0].value), _fixed_bad("fxb", ast.parse("fxb").body[0].value),
         _fixed_bad("conn", ast.parse("fsin.conn").body[0].value, "fsx")]
fx_bad += [x for x in (_fixed_bad("conn", ast.parse("fsx.conn9").body[0].value, "fsx"),) if x]
chk(len(fx_bad) == 8 and fx_ok == [None] * 6, "P2 (합성) 고정 칸 판정 — 이름 엇갈림·남의 장부·데이터 칸·도우미·우회 복사 = 실패 · 고정 칸 같은 이름 = 통과", (fx_bad, fx_ok))
def _rooted_px(y):
    while isinstance(y, (ast.Attribute, ast.Subscript)):
        y = y.value
    return isinstance(y, ast.Name) and y.id == "px"


got, srcs, sig_bad, order_bad, src_bad, holds = {}, {}, [], [], [], {}
for v, (_c, f) in inits.items():
    me = f.args.args[0].arg
    takes = [a.arg for a in f.args.args[1:]] == ["px"]
    called = bool(call_of[v].args) and ast.unparse(call_of[v].args[0]) == "px"
    if takes != called or (takes and (f.args.args[1:] and not (len(call_of[v].args) == 1))):
        sig_bad.append(v)
    if not takes:
        continue
    names = []
    holds[v] = [st.lineno for st in ast.walk(f) if isinstance(st, ast.Assign) and any(isinstance(t, ast.Attribute) and ast.unparse(t) == me + ".px" for t in st.targets)
                and len(st.targets) == 1 and isinstance(st.value, ast.Name) and st.value.id == "px" and st in f.body]
    px_writes = [n.lineno for n in ast.walk(f) if isinstance(n, ast.Attribute) and isinstance(n.ctx, (ast.Store, ast.Del)) and ast.unparse(n) == me + ".px"]
    if px_writes != holds[v]:
        holds[v] = px_writes + ["다른 px 쓰기"]
    for st in ast.walk(f):
        if not isinstance(st, ast.stmt):
            continue
        pairs9 = []
        if isinstance(st, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and st.value is not None:
            for t in (st.targets if isinstance(st, ast.Assign) else [st.target]):
                if isinstance(t, (ast.Tuple, ast.List)) and isinstance(st.value, (ast.Tuple, ast.List)) and len(t.elts) == len(st.value.elts):
                    pairs9 += list(zip(t.elts, st.value.elts))
                else:
                    pairs9.append((t, st.value))
        own9 = {id(t) for t, _x in pairs9}
        heads9 = ([st.target, st.iter] if isinstance(st, (ast.For, ast.AsyncFor)) else
                  [x for it in st.items for x in (it.context_expr, it.optional_vars) if x is not None] if isinstance(st, (ast.With, ast.AsyncWith)) else
                  [] if hasattr(st, "body") else [st])
        for y in (z for h in heads9 for z in ast.walk(h)):
            if (isinstance(y, ast.Attribute) and isinstance(y.ctx, ast.Store) and ast.unparse(y.value) == me and id(y) not in own9
                    and any(_fixed_bad(y.attr, h, me) for h in heads9)):
                src_bad.append("%s.%s 생성자 그 밖 꼴 쓰기 %s" % (v, y.attr, ast.unparse(st)[:60]))
        for t, val9 in pairs9:
            if not (isinstance(t, ast.Attribute) and ast.unparse(t.value) == me) or (t.attr == "px" and isinstance(val9, ast.Name)):
                continue
            why = _fixed_bad(t.attr, val9, me)
            if why:
                src_bad.append("%s.%s" % (v, why))
            s9 = _src_of(val9)
            if s9 and s9[0] == "px" and not why:
                names.append(t.attr)
                srcs[(v, t.attr)] = s9
                if fill_line.get(s9[1], 10 ** 9) >= fill_line[v]:
                    order_bad.append("%s.%s ← px.%s(채움 줄 %s ≥ %s)" % (v, t.attr, s9[1], fill_line.get(s9[1]), fill_line[v]))
    fixed9 = BOOKS_F | CTX_F | {"sb", "cb"}
    reads9 = {y.attr for m9 in _c.body if isinstance(m9, ast.FunctionDef) and m9.args.args for y in ast.walk(m9)
              if isinstance(y, ast.Attribute) and isinstance(y.ctx, ast.Load) and isinstance(y.value, ast.Name)
              and y.value.id == m9.args.args[0].arg and y.attr in fixed9}
    top9 = {t.attr for st in f.body if isinstance(st, ast.Assign) for t in st.targets if isinstance(t, ast.Attribute) and ast.unparse(t.value) == me}
    src_bad += ["%s.%s 고정 칸 이름 속성을 몸통이 읽는데 생성자 최상위에서 안 채움(빠짐·조건부)" % (v, a9) for a9 in sorted((reads9 | set(names)) - top9)]
    src_bad += ["%s 생성자 px 원천 쓰기·삭제 %s:%d" % (v, ast.unparse(y), y.lineno) for y in ast.walk(f)
                if isinstance(y, (ast.Attribute, ast.Subscript)) and isinstance(y.ctx, (ast.Store, ast.Del)) and _rooted_px(y)]
    for a9 in names:
        w9 = [y.lineno for y in ast.walk(f) if isinstance(y, ast.Attribute) and isinstance(y.ctx, (ast.Store, ast.Del)) and ast.unparse(y.value) == me and y.attr == a9]
        if len(w9) != 1:
            src_bad.append("%s.%s 생성자 쓰기·삭제 %d번 %s" % (v, a9, len(w9), w9))
    got[v] = tuple(names)
chk(not sig_bad, "P2 px 를 받는 장부 = 부름 첫 위치 인자 px 하나 · 나머지 키워드(서명 = (self, px, *, …))", sig_bad)
chk(not src_bad and sum(len(x) for x in got.values()) >= 1,
    "P2 생성 때 복사 = 고정 칸뿐(px.sb · px.cb · px.books.<F> · px.ctx.<F> · 속성 이름 = 끝 이름) — 남의 장부·데이터 칸·도우미는 쓸 때 읽음", src_bad[:10])
kwonly = {v: [a.arg for a in inits[v][1].args.kwonlyargs] for v in got}
kwcall = {v: [k.arg for k in call_of[v].keywords] for v in got}
chk(kwonly == kwcall and all(not set(kwonly[v]) & set(got[v]) for v in got),
    "P2 남은 인자 = 키워드 전용 매개변수 = 부름 키워드(같은 순서) · 고정 칸 복사 이름과 겹침 0", {v: sorted(set(kwonly[v]) ^ set(kwcall[v])) for v in got})
chk(not order_bad, "P2 고정 칸(px.ctx)은 그 생성보다 앞에서 채워짐", order_bad)
bk_w = []
for f9 in sorted(os.listdir(T.SRC)):
    if f9.endswith(".py"):
        for n in ast.walk(_parse(f9[:-3])):
            if isinstance(n, ast.Attribute) and isinstance(n.ctx, (ast.Store, ast.Del)) and n.attr in BOOKS_F \
                    and ((isinstance(n.value, ast.Name) and n.value.id == "books") or (isinstance(n.value, ast.Attribute) and n.value.attr == "books")):
                bk_w.append("%s:%d" % (f9, n.lineno))
chk(not bk_w and len(BOOKS_F) >= 10, "P2 고정 칸 Books 필드 다시 대입 0(src 전체 `books.<F> =` · `<…>.books.<F> =`)", bk_w[:10])
chk(len(holds) == 9 and all(len(x) == 1 for x in holds.values()),
    "P2 장부는 px 를 쥔다: px 받는 장부 9개 __init__ 몸통 `self.px = px` 정확히 1번", holds)
selfpx = [n.lineno for n in ast.walk(rp) if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store) and ast.unparse(n) == "self.px"]
chk(not selfpx, "P2 빌더 속성 self.px 대입 0(장부 묶음 px = 리플레이 지역)", selfpx)

stage_stores = collections.defaultdict(list)
for f in fns.values():
    for n in ast.walk(f):
        if isinstance(n, ast.Attribute) and isinstance(n.ctx, (ast.Store, ast.Del)) and isinstance(n.value, ast.Name):
            stage_stores[(n.value.id, n.attr)].append(n.lineno)


def _method_stores(v):
    if v not in inits:
        return set()
    c, _f = inits[v]
    out = set()
    for m in c.body:
        if isinstance(m, ast.FunctionDef) and m.name != "__init__" and m.args.args:
            me = m.args.args[0].arg
            for n in ast.walk(m):
                if isinstance(n, ast.Attribute) and isinstance(n.ctx, (ast.Store, ast.Del)) and isinstance(n.value, ast.Name) and n.value.id == me:
                    out.add(n.attr)
    return out


re_bad = []
late_line = {}
for p, names in LATE2.items():
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
px_re = ["리플레이 %s.px = (줄 %s)" % (v, stage_stores[(v, "px")]) for v in holds if stage_stores.get((v, "px"))]
px_re += ["%s 메서드 self.px =" % v for v in holds if "px" in _method_stores(v)]
for v in holds:
    c9, _f9 = inits[v]
    for m in c9.body:
        if isinstance(m, ast.FunctionDef) and m.args.args:
            me9 = m.args.args[0].arg
            px_re += ["%s.%s self.px.… 대입 %s" % (v, m.name, ast.unparse(n)) for n in ast.walk(m)
                      if isinstance(n, ast.Attribute) and isinstance(n.ctx, (ast.Store, ast.Del))
                      and (ast.unparse(n.value) == me9 + ".px" or ast.unparse(n.value).startswith(me9 + ".px."))]
chk(not px_re, "P3 장부 px 속성 다시 대입 0(리플레이 `X.px =` · 메서드 `self.px =` · `self.px.<칸> = …`)", px_re[:10])
own, r3_bad = {}, []
for v, (c9, f9) in inits.items():
    me9 = f9.args.args[0].arg
    pnames = {a.arg for a in f9.args.args + f9.args.kwonlyargs}
    for st in f9.body:
        if (isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Attribute) and ast.unparse(st.targets[0].value) == me9
                and isinstance(st.value, (ast.Dict, ast.List, ast.Set, ast.Tuple, ast.Constant, ast.Call))
                and not any(isinstance(y, ast.Name) and y.id in pnames for y in ast.walk(st.value))):
            own[(v, st.targets[0].attr)] = st.lineno
r3_alias = collections.defaultdict(list)
for sname in STAGES:
    for n in ast.walk(fns[sname]):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and len(n.targets) == 1 and isinstance(n.value, ast.Attribute) and isinstance(n.value.value, ast.Name) \
                        and (n.value.value.id, n.value.attr) in own and n.value.attr == t.id:
                    r3_alias[t.id].append(n.lineno)
binds_all = collections.defaultdict(list)
for sname in STAGES:
    skip9 = set()
    for n in ast.walk(fns[sname]):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, (ast.Tuple, ast.List)) and isinstance(n.value, (ast.Tuple, ast.List)) and len(n.value.elts) == len(t.elts):
                    skip9 |= {id(a) for a, b in zip(t.elts, n.value.elts) if isinstance(a, ast.Name) and _rooted(b)}
                elif isinstance(t, ast.Name) and _rooted(n.value):
                    skip9.add(id(t))
    for n in ast.walk(fns[sname]):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n is not fns[sname]:
            binds_all[n.name].append(n.lineno)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)) and id(n) not in skip9:
            binds_all[n.id].append(n.lineno)
for (v, x), _ln in sorted(own.items()):
    if (x in r3_alias or x in binds_all) and (len(r3_alias.get(x, ())) != 1 or binds_all.get(x) != r3_alias[x]):
        r3_bad.append("%s.%s 별칭 %s · 묶음 %s" % (v, x, r3_alias.get(x), binds_all.get(x)))
    if x in _method_stores(v) or any(isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Del) and n.attr == x and isinstance(n.value, ast.Name)
                                     for n in ast.walk(inits[v][0])):
        r3_bad.append("%s 메서드 self.%s 다시 대입·삭제" % (v, x))
    if stage_stores.get((v, x)):
        r3_bad.append("리플레이 %s.%s = %s" % (v, x, stage_stores[(v, x)]))
cls_attrs = {}
for v, (c9, f9) in inits.items():
    me9 = f9.args.args[0].arg
    cls_attrs[v] = {m.name for m in c9.body if isinstance(m, ast.FunctionDef)} | {
        t.attr for st in f9.body if isinstance(st, ast.Assign) for t in st.targets if isinstance(t, ast.Attribute) and ast.unparse(t.value) == me9}
    cls_attrs[v] |= set(LATE2.get(v, ()))
cls_attrs["ctx"] = set(AC.ReplayCtx.names())
p5_bad = []
for v in holds:
    c9, _f9 = inits[v]
    for m in c9.body:
        if not (isinstance(m, ast.FunctionDef) and m.args.args):
            continue
        me9 = m.args.args[0].arg
        for n in ast.walk(m):
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == me9 and n.attr == "px":
                continue
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Attribute) and isinstance(n.value.value, ast.Name) \
                    and n.value.value.id == me9 and n.value.attr == "px" and n.attr not in slots:
                p5_bad.append("%s.%s %s.px.%s(칸 아님)" % (v, m.name, me9, n.attr))
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Attribute) and isinstance(n.value.value, ast.Attribute) \
                    and ast.unparse(n.value.value) == me9 + ".px" and n.value.attr in cls_attrs and n.attr not in cls_attrs[n.value.attr]:
                p5_bad.append("%s.%s %s(그 장부에 없는 이름)" % (v, m.name, ast.unparse(n)))
chk(not p5_bad, "P5 장부 몸통 px 접근 이름 = 칸(__slots__) · 남의 장부 이름 = 그 장부 메서드·생성자 속성(같은 이름 다른 장부 실수 막음)", p5_bad[:10])
meth_w = sorted("%s.%s" % (v, a9) for v in inits for a9 in _method_stores(v))
chk(not meth_w, "P3 장부 메서드(__init__ 밖)의 self 속성 쓰기·삭제 0(R2 로 남이 읽는 원천·자기 그릇·키워드 속성 모두 — 접근 시점 값 = 생성 때 값)", meth_w[:10])
late_ok = {(pv, a9) for pv, names in LATE2.items() for a9 in names}
st_w = sorted("%s.%s %s" % (k[0], k[1], ln) for k, ln in stage_stores.items() if k[0] in fill_line and k[0] not in ("sb", "books") and k[0] not in R4
              and not (k in late_ok and len(ln) == 1))
chk(not st_w, "P4 리플레이 단계의 장부 속성 쓰기·삭제 = 늦은 연결 표 한 줄씩뿐", st_w[:10])
slot_w = collections.defaultdict(list)
for f9 in fns.values():
    for n in ast.walk(f9):
        if isinstance(n, ast.Attribute) and isinstance(n.ctx, (ast.Store, ast.Del)) and isinstance(n.value, ast.Name) and n.value.id == "px":
            slot_w[n.attr].append(n.lineno)
want_w = {k: [ln] for k, ln in fill_line.items() if k not in ("sb", "books")}
chk(dict(slot_w) == want_w, "P1 px 칸 쓰기·삭제 = 칸마다 채움 한 줄(장부 생성 · cb · R4 — 교체·삭제 0)",
    sorted(set(map(str, slot_w.items())) ^ set(map(str, want_w.items())))[:6])
chk(not r3_bad and len(own) >= 1, "P3 R3 자기 그릇(%d) = 리플레이 별칭 `X = <장부>.X` 가 그 이름 유일 묶음 · 다시 대입·삭제 0" % len(own), r3_bad[:10])

late = collections.defaultdict(list)
for f in fns.values():
    for n in ast.walk(f):
        if (isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Attribute)
                and isinstance(n.targets[0].value, ast.Name) and n.targets[0].value.id in fill_line
                and n.lineno > fill_line[n.targets[0].value.id]):
            late[n.targets[0].value.id].append((n.lineno, n.targets[0].attr, ast.unparse(n.value)))
late_t = {p: tuple(a for _l, a, _v in sorted(xs)) for p, xs in late.items()}
vals_bad = [(p, a, v9) for p, xs in late.items() for _l, a, v9 in xs if v9 != a]
chk(late_t == LATE2, "P4 늦은 연결 = 이름으로 고정한 두 자리(%s) — 새 늦은 연결은 LATE2 에 올리고 검토" % sorted(LATE2.items()),
    sorted(set(late_t.items()) ^ set(LATE2.items()))[:6])
chk(not vals_bad, "P4 늦은 연결 값 = 같은 이름 지역(맨 이름)", vals_bad[:6])
lb_bad = []
for p, xs in late.items():
    for ln, a, _v in xs:
        if binds_all.get(a) is None or len(binds_all[a]) != 1 or binds_all[a][0] >= ln:
            lb_bad.append("%s.%s(늦은 연결 줄 %d · 지역 묶음 %s)" % (p, a, ln, binds_all.get(a)))
chk(not lb_bad and late, "P4 늦은 연결 지역 = 늦은 연결 앞에서 한 번만 묶임(그 뒤 재묶음 0 → 장부 속성 = 지역 끝까지 같은 객체)", lb_bad)


def dyn_calls(tree, allow_basis=False):
    loop9 = ast.dump(ast.parse("for _n in _WRITES:\n    setattr(StrictCostBasis, _n, _twin(_n))").body[0])
    ok9 = {id(n) for st in tree.body if allow_basis and ast.dump(st) == loop9 for n in ast.walk(st)}
    dyn9 = ("setattr", "delattr", "__setattr__", "__delattr__", "locals", "vars", "globals", "exec", "eval")
    return [(n.lineno, ast.unparse(n)[:60]) for n in ast.walk(tree) if id(n) not in ok9
            and ((isinstance(n, ast.Name) and n.id in dyn9) or (isinstance(n, ast.Attribute) and n.attr in dyn9))]


dyn_bad = []
for f9 in sorted(os.listdir(T.SRC)):
    if f9.endswith(".py") and (f9.startswith("accounting_") or f9 == "view_b_replay.py"):
        dyn_bad += ["%s:%d %s" % (f9, ln, t9) for ln, t9 in dyn_calls(_parse(f9[:-3]), f9 == "accounting_basis.py")]
syn_d = dyn_calls(ast.parse("for _n in _WRITES:\n    setattr(StrictCostBasis, _n, _twin(_n))\nsetattr(fbx, 'ex_fee', px.books.ex_fee_m)\nvars(slx).update(a=1)\n"
                             "f = setattr\nobject.__setattr__(fbx, 'wd_raw9', {})\n"), True)
chk(not dyn_bad and sorted(x[0] for x in syn_d) == [3, 4, 5, 6], "P4 리플레이·장부 모듈 동적 재묶음(setattr·locals·vars·exec 등) 0 — StrictCostBasis 고정 루프 한 자리만 예외(합성 반례 포함)",
    (dyn_bad[:6], syn_d))


def _is_name(e, names):
    if isinstance(e, ast.Name) and e.id in names:
        return e.id
    if isinstance(e, ast.Attribute) and e.attr in names:
        return e.attr
    return None


def ident_uses(tree, names):
    hits = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Compare) and any(isinstance(o, (ast.Is, ast.IsNot)) for o in n.ops):
            hits += [(n.lineno, "is", m) for m in (_is_name(e, names) for e in [n.left] + list(n.comparators)) if m]
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "id":
            hits += [(n.lineno, "id()", m) for m in (_is_name(e, names) for e in n.args) if m]
        if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)):
            for t in (n.targets if isinstance(n, (ast.Assign, ast.Delete)) else [n.target]):
                m = _is_name(t.value, names) if isinstance(t, ast.Attribute) else None
                if m:
                    hits.append((n.lineno, "속성 쓰기", m))
        if isinstance(n, ast.Dict):
            hits += [(n.lineno, "dict 열쇠", m) for m in (_is_name(k, names) for k in n.keys if k is not None) if m]
        if isinstance(n, ast.Subscript):
            m = _is_name(n.slice, names)
            if m:
                hits.append((n.lineno, "첨자 열쇠", m))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("get", "setdefault", "pop", "add") and n.args:
            m = _is_name(n.args[0], names)
            if m:
                hits.append((n.lineno, "열쇠(%s)" % n.func.attr, m))
    return hits


meths6 = {v: {m.name for m in inits[v][0].body if isinstance(m, ast.FunctionDef)} for v in inits}
r2m = set()
for v in holds:
    for n in ast.walk(inits[v][0]):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Attribute) and isinstance(n.value.value, ast.Attribute) \
                and n.value.value.attr == "px" and n.value.attr in meths6 and n.attr in meths6[n.value.attr]:
            r2m.add(n.attr)
al6 = set()
for f in fns.values():
    for n in ast.walk(f):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                pairs = zip(t.elts, n.value.elts) if isinstance(t, ast.Tuple) and isinstance(n.value, ast.Tuple) else [(t, n.value)]
                for a, b in pairs:
                    if isinstance(a, ast.Name) and isinstance(b, ast.Attribute) and isinstance(b.value, ast.Name) and b.attr in meths6.get(b.value.id, ()):
                        al6.add(a.id)
decl6 = {m for ms in meths6.values() for m in ms if not m.startswith("__")}
names6 = r2m | al6 | decl6
hits6 = []
for f9 in sorted(os.listdir(T.SRC)):
    if f9.endswith(".py") and (f9.startswith("view_b_") or f9.startswith("accounting_")):
        hits6 += ["%s:%d %s %s" % (f9, ln, k, m) for ln, k, m in ident_uses(_parse(f9[:-3]), names6)]
syn6 = ident_uses(ast.parse("if fee_gain is g: pass\nd = {px.cpx.consume: 1}\nk = id(ev)\nfee_gain.cache = 1\ns.add(note_unk)\n"), {"fee_gain", "consume", "ev", "note_unk"})
chk(len(r2m) >= 10 and len(al6) >= 30 and not hits6,
    "P6 남의 장부 메서드(쓸 때 읽음 %d)·리플레이 장부 별칭(%d) 신원 쓰임 0 — 접근마다 새 바운드 메서드라도 숫자 무관" % (len(r2m), len(al6)), hits6[:10])
chk(sorted(k for _l, k, _m in syn6) == sorted(["is", "dict 열쇠", "id()", "속성 쓰기", "열쇠(add)"]), "P6 (합성) is·dict 열쇠·id()·속성 쓰기·set 열쇠 = 잡힘", syn6)
syn6d = ident_uses(ast.parse("x = id(fsx.fs_hold)\nlpx.lp_bucket.cache = 1\n"), names6)
chk(sorted((k, m) for _l, k, m in syn6d) == [("id()", "fs_hold"), ("속성 쓰기", "lp_bucket")] and {"fs_hold", "lp_bucket", "of_finalize"} <= decl6,
    "P6 (합성) 리플레이 별칭 없는 장부 메서드도 검사 대상(선언 %d)" % len(decl6), syn6d)

T.finish()
