#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import collections  # noqa: E402
import glob  # noqa: E402
import os  # noqa: E402

chk = T.chk
BS = "_bs9"
STAGES = (("view_b_cards", "_build_cards"), ("view_b_pendings", "_build_pendings"),
          ("view_b_outflows", "_build_outflows"), ("view_b_daily", "_build_daily"), ("view_b_futidx", "_build_futidx"),
          ("view_b_tail", "_build_tail"))
N_REPLAY = 0
ON_BOUNDARY = True
ON_WRITES = True
ALLOWED = {
    ("view_b_daily", "_build_daily", "get", "dep_tr9"): 2,
    ("view_b_daily", "_build_daily", "get", "daily_inval"): 1,
    ("view_b_cards", "_build_cards", "load", "diag"): 1,
}
PASS_TO = {"self." + n for _m, n in STAGES} | {"stage", "accounting_books.screen_check"}
SCOPE_FROM = ("rr.screen_scope",)


def _tree(mod):
    with open(os.path.join(T.SRC, mod + ".py"), encoding="utf-8") as f:
        return ast.parse(f.read(), mod + ".py")


def key_of(n):
    if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id == BS:
        sl = n.slice.value if isinstance(n.slice, ast.Index) else n.slice
        if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
            return sl.value
    return None


def dotted(n):
    parts = []
    while isinstance(n, ast.Attribute):
        parts.append(n.attr)
        n = n.value
    return ".".join([n.id] + parts[::-1]) if isinstance(n, ast.Name) else None


def reload_key(st):
    if not (isinstance(st, ast.If) and isinstance(st.test, ast.Compare) and len(st.test.ops) == 1 and isinstance(st.test.ops[0], ast.In)
            and isinstance(st.test.left, ast.Constant) and isinstance(st.test.comparators[0], ast.Name) and st.test.comparators[0].id == BS):
        return None
    k = st.test.left.value
    b = st.body[0] if len(st.body) == 1 else None
    return k, (not st.orelse and isinstance(b, ast.Assign) and len(b.targets) == 1 and isinstance(b.targets[0], ast.Name)
               and b.targets[0].id == k and key_of(b.value) == k)


def pop_key(st):
    if (isinstance(st, ast.If) and isinstance(st.test, ast.Compare) and isinstance(st.test.ops[0], ast.NotIn)
            and isinstance(st.test.comparators[0], ast.Call) and getattr(st.test.comparators[0].func, "id", "") == "locals"):
        return st.test.left.value
    return None


def is_update(st):
    return (isinstance(st, ast.Expr) and isinstance(st.value, ast.Call) and isinstance(st.value.func, ast.Attribute)
            and st.value.func.attr == "update" and isinstance(st.value.func.value, ast.Name) and st.value.func.value.id == BS)


def body_of(fn):
    return fn.body[1:] if fn.body and isinstance(fn.body[0], ast.Expr) and isinstance(fn.body[0].value, ast.Constant) else fn.body


def head(fn):
    b = body_of(fn)
    st = b[0] if b else None
    if not (isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Tuple) and isinstance(st.value, ast.Tuple)
            and len(st.targets[0].elts) == len(st.value.elts)):
        return None, []
    out = []
    for t, v in zip(st.targets[0].elts, st.value.elts):
        src = ("ctx." + v.attr) if isinstance(v, ast.Attribute) and key_of(v.value) == "ctx" else key_of(v)
        if not isinstance(t, ast.Name) or src is None:
            return None, []
        out.append((t.id, src))
    return st, out


def own_bound(stmts):
    out, stack = set(), list(stmts)
    while stack:
        n = stack.pop()
        if isinstance(n, ast.Name) and not isinstance(n.ctx, ast.Load):
            out.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
            continue
        elif isinstance(n, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            continue
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            out |= {(a.asname or a.name).split(".")[0] for a in n.names}
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        stack.extend(ast.iter_child_nodes(n))
    return out


TREES = {}
FNS = []
for mod, name in STAGES:
    if mod not in TREES:
        TREES[mod] = _tree(mod)
    hits = [n for n in ast.walk(TREES[mod]) if isinstance(n, ast.FunctionDef) and n.name == name]
    chk(len(hits) == 1, "단계 함수 %s.%s 정의 하나" % (mod, name), len(hits))
    FNS.append(hits[0] if hits else None)
if not all(FNS):
    T.finish()


class St:

    def __init__(self, i, fn):
        self.i, self.fn, self.name = i, fn, fn.name
        self.h, self.pairs = head(fn)
        rest = [s for s in body_of(fn) if s is not self.h]
        self.reloads = [reload_key(s) + (s,) for s in rest if reload_key(s)]
        self.pops = [pop_key(s) for s in rest if pop_key(s)]
        self.updates = sum(1 for s in rest if is_update(s))
        core = [s for s in rest if not reload_key(s) and not pop_key(s)]
        self.body_bound = own_bound(core) - {"self", "conn", BS}
        self.gets = [(y.args[0].value, y.lineno) for y in ast.walk(fn) if isinstance(y, ast.Call) and isinstance(y.func, ast.Attribute)
                     and y.func.attr == "get" and isinstance(y.func.value, ast.Name) and y.func.value.id == BS and y.args
                     and isinstance(y.args[0], ast.Constant)]


STS = [St(i, fn) for i, fn in enumerate(FNS)]

counts, bad = collections.Counter(), []
for path in sorted(glob.glob(os.path.join(T.SRC, "view_b_*.py"))) + [os.path.join(T.SRC, "view_builder.py")]:
    mod = os.path.basename(path)[:-3]
    tree = TREES.get(mod) or _tree(mod)
    parent = {ch: n for n in ast.walk(tree) for ch in ast.iter_child_nodes(n)}
    fn_of = {}
    for f in sorted((x for x in ast.walk(tree) if isinstance(x, ast.FunctionDef)), key=lambda x: x.lineno):
        for y in ast.walk(f):
            fn_of[y] = f.name
    heads = {id(head(f)[0]) for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and head(f)[0] is not None}
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Name) and n.id == BS):
            continue
        p, fn = parent.get(n), fn_of.get(n, "<모듈>")
        gp = parent.get(p)
        at = "%s:%d %s" % (mod, n.lineno, fn)
        if isinstance(n.ctx, ast.Store):
            if not (isinstance(p, ast.Assign) and isinstance(p.value, ast.Call) and dotted(p.value.func) in SCOPE_FROM):
                bad.append(at + " 이름표 다시 묶기")
        elif isinstance(p, ast.Subscript) and p.value is n:
            k = key_of(p)
            tup = gp if isinstance(gp, ast.Tuple) else (parent.get(gp) if isinstance(gp, ast.Attribute) else None)
            if k is not None and isinstance(tup, ast.Tuple) and id(parent.get(tup)) in heads:
                continue
            if k is not None and isinstance(gp, ast.Assign) and isinstance(parent.get(gp), ast.If) and reload_key(parent.get(gp)):
                if not reload_key(parent.get(gp))[1]:
                    bad.append(at + " 재적재 꼴 틀림 " + k)
                continue
            counts[(mod, fn, "store" if isinstance(p.ctx, ast.Store) else "load" if isinstance(p.ctx, ast.Load) else "del", k)] += 1
        elif isinstance(p, ast.Compare) and isinstance(gp, ast.If) and gp.test is p and reload_key(gp):
            if not reload_key(gp)[1]:
                bad.append(at + " `if \"…\" in _bs9` 아래가 재적재 꼴이 아님")
        elif isinstance(p, ast.Attribute) and isinstance(gp, ast.Call) and gp.func is p:
            if p.attr == "update" and isinstance(parent.get(gp), ast.Expr):
                continue
            if p.attr == "pop" and pop_key(parent.get(parent.get(gp))):
                continue
            if p.attr == "get" and gp.args and isinstance(gp.args[0], ast.Constant):
                counts[(mod, fn, "get", gp.args[0].value)] += 1
            else:
                bad.append(at + " _bs9.%s(…)" % p.attr)
        elif isinstance(p, ast.Call) and n in p.args and dotted(p.func) in PASS_TO:
            continue
        else:
            bad.append(at + " " + type(p).__name__)
chk(not bad, "K1 이름표는 허용 꼴로만 쓰임(머리 풀기·재적재·update·pop·단계 호출 인자 · 그 밖 = 허용 표)", bad[:20])
chk(dict(counts) == ALLOWED, "K1 머리 풀기·재적재 밖 이름표 읽기·쓰기 = 허용 표와 정확히 같음(%d자리)" % sum(ALLOWED.values()),
    {"더해짐": {"%s.%s %s %s" % k: v for k, v in counts.items() if ALLOWED.get(k) != v},
     "빠짐": {"%s.%s %s %s" % k: v for k, v in ALLOWED.items() if counts.get(k) != v}})

import accounting_books as AB  # noqa: E402

RP = _tree("view_b_replay")
RFN = {n.name: n for n in ast.walk(RP) if isinstance(n, ast.FunctionDef) and n.name in ("_replay_prep", "_replay_main", "_build_replay")}
po_cls = next((n for n in RP.body if isinstance(n, ast.ClassDef) and n.name == "PrepOut"), None)
PO_F = [x.target.id for x in (po_cls.body if po_cls else []) if isinstance(x, ast.AnnAssign) and isinstance(x.target, ast.Name)]


def _norm9(n):
    n = n.lstrip("_")
    return n[:-1] if n[-1:] == "9" else n


def _pre_reads(fn):
    return {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "pre"}


prep_fn, main_fn, br_fn = RFN.get("_replay_prep"), RFN.get("_replay_main"), RFN.get("_build_replay")
pb = body_of(prep_fn) if prep_fn else []
last = pb[-1] if pb else None
prep_ok = (po_cls is not None and isinstance(last, ast.Return) and isinstance(last.value, ast.Call) and getattr(last.value.func, "id", "") == "PrepOut"
           and not last.value.args and all(k.arg and isinstance(k.value, ast.Name) and _norm9(k.value.id) == k.arg for k in last.value.keywords)
           and [k.arg for k in last.value.keywords] == PO_F
           and not any(isinstance(y, ast.Call) and getattr(y.func, "id", "") == "locals" for y in ast.walk(prep_fn))
           and not any(isinstance(y, ast.Name) and y.id == BS for y in ast.walk(prep_fn)))
chk(prep_ok and len(PO_F) == len(set(PO_F)), "K2′ _replay_prep 은 `return PrepOut(필드=지역, …)` 로 끝(키워드 = 필드 순서·이름 규약 · locals() 0 · 이름표 0 · 필드 %d)" % len(PO_F),
    [(k.arg, ast.unparse(k.value)) for k in (last.value.keywords if isinstance(last, ast.Return) and isinstance(last.value, ast.Call) else []) if not (isinstance(k.value, ast.Name) and _norm9(k.value.id) == k.arg)][:10])
mb = body_of(main_fn) if main_fn else []
mh = mb[0] if mb and isinstance(mb[0], ast.Assign) and len(mb[0].targets) == 1 and isinstance(mb[0].targets[0], ast.Tuple) and isinstance(mb[0].value, ast.Tuple) else None
hbad = []
for t, v in (zip(mh.targets[0].elts, mh.value.elts) if mh is not None else ()):
    if isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name) and v.value.id == "pre":
        if not (isinstance(t, ast.Name) and _norm9(t.id) == v.attr):
            hbad.append("%s ← %s" % (ast.unparse(t), ast.unparse(v)))
    elif isinstance(v, ast.Attribute) and isinstance(v.value, ast.Attribute) and getattr(v.value.value, "id", "") == "pre" and v.value.attr == "ctx":
        if not (isinstance(t, ast.Name) and t.id == v.attr):
            hbad.append("%s ← %s" % (ast.unparse(t), ast.unparse(v)))
    else:
        hbad.append("%s ← %s (pre.<f>·pre.ctx.<f> 아님)" % (ast.unparse(t), ast.unparse(v)))
chk(mh is not None and [a.arg for a in main_fn.args.args] == ["self", "pre"] and not hbad and not any(isinstance(y, ast.Name) and y.id == BS for y in ast.walk(main_fn)),
    "K2′ _replay_main(self, pre) 머리 풀기 = 첫 문장 · 오른쪽 pre.<f>·pre.ctx.<f> · 왼쪽 = 필드 이름 규약 · 이름표 0(%d 이름)" % (len(mh.targets[0].elts) if mh is not None else 0), hbad[:10])
reads = _pre_reads(main_fn) if main_fn else set()
chk(main_fn is not None and set(PO_F) == reads, "K2′ PrepOut 필드 = main 이 pre 에서 읽는 이름(머리 풀기 + 꼬리 ReplayResult 생성 · 남는 필드 0 · 모르는 읽기 0 · %d)" % len(reads),
    {"남는 필드": sorted(set(PO_F) - reads), "모르는 읽기": sorted(reads - set(PO_F))})
mret = mb[-1] if mb else None
chk(isinstance(mret, ast.Return) and isinstance(mret.value, ast.Call) and dotted(mret.value.func) == "accounting_books.ReplayResult"
    and not mret.value.args and {k.arg for k in mret.value.keywords} >= set(AB._CONTRACT),
    "K2′ _replay_main 꼬리 = `return accounting_books.ReplayResult(키워드…)`(경계 필드 전부 · 이름표 update 0)")
bb = body_of(br_fn) if br_fn else []
chk(len(bb) >= 1 and ast.unparse(bb[0]) == "rr = self._replay_main(self._replay_prep(conn))" and isinstance(bb[-1], ast.Return) and ast.unparse(bb[-1]) == "return rr"
    and not any(isinstance(y, ast.Name) and y.id == BS for y in ast.walk(br_fn)),
    "K2′ _build_replay = `rr = self._replay_main(self._replay_prep(conn))` … `return rr`(이름표 0)", [ast.unparse(x)[:60] for x in bb])
shape = []
for s in STS:
    if s.h is None:
        shape.append("%s 머리 풀기 없음" % s.name)
    shape += ["%s 머리 풀기 %s ← %s" % (s.name, t, k) for t, k in s.pairs if t != (k[4:] if k.startswith("ctx.") else k)]
    shape += ["%s 재적재 꼴 틀림 %s" % (s.name, k) for k, ok, _st in s.reloads if not ok]
    want_upd = 0 if s.name == "_build_tail" else 1
    if s.updates != want_upd:
        shape.append("%s update %d개(%d 이어야)" % (s.name, s.updates, want_upd))
    if s.pops:
        shape.append("%s 화면 단계에 pop 줄 %s" % (s.name, s.pops))
chk(not shape, "K2 화면 단계 모양(머리 풀기 왼쪽 = 열쇠 · update 하나(tail 0) · pop 0)", shape)
VIRT = set(AB.ReplayResult.old_names())

made = set(VIRT)
miss = []
for s in STS:
    for k, ln in s.gets:
        if k != "daily_inval" and k not in made:
            miss.append("%s :%d .get(%r)" % (s.name, ln, k))
    made |= s.body_bound | {t for t, _k in s.pairs}
chk(not miss, "K3 화면 단계 .get 열쇠 = 리플레이 산출·앞 단계가 묶는 이름 또는 daily_inval(_build 가 넣음 · 빠지면 조용히 None)", miss)

if not ON_BOUNDARY:
    chk(True, "K4 화면 단계 읽기 ⊆ 경계 — 5-2(ReplayResult) 에서 켬 · 지금 건너뜀")
else:
    import accounting_books  # noqa: E402
    allowed = set(accounting_books.ReplayResult.old_names()) | {"daily_inval", "books", "ctx"}
    over = []
    for s in STS[N_REPLAY:]:
        reads = {("ctx" if k.startswith("ctx.") else k) for _t, k in s.pairs} | {k for k, _ok, _st in s.reloads} | {k for k, _ln in s.gets}
        over += ["%s %s" % (s.name, k) for k in sorted(reads - allowed)]
        allowed |= s.body_bound
    chk(not over, "K4 화면 단계 읽기 ⊆ 경계 ∪ 앞 화면 단계 산출 ∪ {daily_inval}", over[:30])
if not ON_WRITES:
    chk(True, "K5 화면 단계의 리플레이 산출 제자리 쓰기 ⊆ 선언 표 — 5-3 에서 켬 · 지금 건너뜀")
else:
    import accounting_books  # noqa: E402
    MUT = {"append", "extend", "update", "setdefault", "pop", "clear", "insert", "remove", "add", "discard", "sort", "popitem", "reverse"}
    replay_made = set(VIRT)
    over = []
    for s in STS[N_REPLAY:]:
        ins = ({t for t, _k in s.pairs} | {k for k, _ok, _st in s.reloads}) & replay_made
        cand = ins - s.body_bound

        def base(e):
            while isinstance(e, (ast.Subscript, ast.Attribute)):
                e = e.value
            return e.id if isinstance(e, ast.Name) else None
        hit = set()
        for y in ast.walk(s.fn):
            tg = y.targets if isinstance(y, (ast.Assign, ast.Delete)) else [y.target] if isinstance(y, (ast.AugAssign, ast.AnnAssign)) else []
            hit |= {base(t) for t in tg if isinstance(t, (ast.Subscript, ast.Attribute))} & cand
            if isinstance(y, ast.Call) and isinstance(y.func, ast.Attribute) and y.func.attr in MUT:
                hit |= {base(y.func.value)} & cand
        decl = set(accounting_books.SCREEN_WRITES_DATA.get(s.name, ())) | set(accounting_books.SCREEN_WRITES.get(s.name, ()))
        over += ["%s %s" % (s.name, n) for n in sorted(hit - decl)]
    chk(not over, "K5 화면 단계 제자리 쓰기 ⊆ 선언 표", over[:30])
T.finish()
