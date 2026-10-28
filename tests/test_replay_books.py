#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import glob  # noqa: E402
import os  # noqa: E402
from decimal import Decimal  # noqa: E402

import accounting_books as AB  # noqa: E402

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


STAGE_CTX = {"view_b_cards.py": ("_cards_", "cst")}


def _norm9(n):
    n = n.lstrip("_")
    return n[:-1] if n.endswith("9") else n


def _unpack_el(e, nm, ctx=None):
    if isinstance(e, ast.Attribute):
        if ctx is not None and isinstance(e.value, ast.Name) and e.value.id == ctx:
            return e.attr == nm
        if isinstance(e.value, ast.Name) and e.value.id == "pre":
            return e.attr == _norm9(nm)
        if isinstance(e.value, ast.Attribute) and isinstance(e.value.value, ast.Name) and e.value.value.id == "pre" and e.value.attr == "ctx":
            return e.attr == nm
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
    pre, cx = STAGE_CTX.get(os.path.basename(f), (None, None))
    for fn in ast.walk(tr):
        if pre and isinstance(fn, ast.FunctionDef) and fn.name.startswith(pre) and [a.arg for a in fn.args.args] == ["self", cx]:
            st = fn.body[0]
            if (isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Tuple)
                    and isinstance(st.value, ast.Tuple) and st.value.elts and len(st.targets[0].elts) == len(st.value.elts)
                    and all(isinstance(t9, ast.Name) and _unpack_el(e, t9.id, cx) for t9, e in zip(st.targets[0].elts, st.value.elts))):
                ok_lines.add(st.lineno)
    if os.path.basename(f) == "view_b_replay.py":
        ok_lines |= alias_lines
        for cl in tr.body:
            if isinstance(cl, ast.ClassDef) and cl.name == "ReplayRun":
                for fn in cl.body:
                    b9 = [x for x in fn.body if not (isinstance(x, ast.Expr) and isinstance(x.value, ast.Constant))] if isinstance(fn, ast.FunctionDef) else []
                    st = b9[0] if b9 else None
                    if (isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Tuple)
                            and isinstance(st.value, ast.Tuple) and st.value.elts and len(st.targets[0].elts) == len(st.value.elts)
                            and all(isinstance(t9, ast.Name) and isinstance(e, ast.Attribute) and isinstance(e.value, ast.Name)
                                    and e.value.id in ("self", "rc") and (t9.id not in NAMES or (e.value.id == "self" and e.attr == t9.id))
                                    for t9, e in zip(st.targets[0].elts, st.value.elts))):
                        ok_lines.add(st.lineno)
        for st in ast.walk(tr):
            if (isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Tuple)
                    and isinstance(st.value, ast.Tuple) and st.value.elts and len(st.targets[0].elts) == len(st.value.elts)
                    and all(isinstance(t9, ast.Name) and isinstance(e, ast.Attribute) and isinstance(e.value, ast.Name)
                            and e.value.id in ("li", "lko", "ri", "rto") and (t9.id not in NAMES or e.attr == t9.id)
                            for t9, e in zip(st.targets[0].elts, st.value.elts))):
                ok_lines.add(st.lineno)
        for cl in tr.body:
            if isinstance(cl, ast.ClassDef) and cl.name in ("LinksIn", "LinksOut", "RtIn", "RtOut", "PrepOut"):
                ok_lines |= {x.lineno for x in cl.body if isinstance(x, ast.AnnAssign) and x.value is None}
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

import dataclasses  # noqa: E402

RR = AB.ReplayResult
OLDN = RR.old_names()
bk = AB.Books()
cx = object()
scope = {n: object() for n in OLDN}
scope.update({n: getattr(bk, n) for n in NAMES}, books=bk, ctx=cx, other9=object())


def _mk(sc, cb=None):
    return RR(_keep=sc, _cb=cb, **{f: sc[AB.OLD.get(f, f)] for f in AB._CONTRACT})


rr = _mk(scope)
edge = [f.name for f in dataclasses.fields(RR) if f.name not in ("books", "ctx") and not f.name.startswith("_")]
chk(rr.books is bk and rr.ctx is cx and all(getattr(rr, f) is scope[AB.OLD.get(f, f)] for f in edge) and rr._keep is scope and rr._cb is None
    and not hasattr(RR, "from_scope") and not hasattr(AB, "check_rr") and not hasattr(AB, "check_pool_aliases"),
    "B5 직접 생성 = 같은 객체(필드 %d · 옛 이름 %d) · _keep = 묶음 · from_scope·check_rr·check_pool_aliases 없음" % (len(edge) + 2, len(OLDN)))
old = rr.as_old_names()
chk(set(old) == set(OLDN) and old is not scope and all(old[n] is getattr(bk, n) for n in NAMES) and old["books"] is bk
    and all(old[AB.OLD.get(f, f)] is getattr(rr, f) for f in edge) and "other9" not in old,
    "B5 as_old_names = 옛 이름 새 dict(Books 필드 = 장부 필드 같은 객체 · 경계 밖 리플레이 지역 없음)")
inv = ("e", "1")
sc9 = rr.screen_scope(inv)
chk(sc9["daily_inval"] is inv and set(sc9) == set(OLDN) | {"daily_inval"} and sc9 is not old, "B5 screen_scope = 옛 이름 + daily_inval(부를 때마다 새 dict)")
try:
    RR(**{f: scope[AB.OLD.get(f, f)] for f in AB._CONTRACT if f != "dep_tr"})
    miss = None
except TypeError as e:
    miss = str(e)
chk(miss is not None and "dep_tr" in miss, "B5 경계 필드 빠짐 = TypeError(기본값 없음 · 조용한 None 아님 · .get 으로 읽는 dep_tr 도)", miss)
try:
    rr.rows = []
    froz = False
except dataclasses.FrozenInstanceError:
    froz = True
chk(froz, "B5 필드 다시 묶기 불가(frozen)")

chk(set(AB.SCREEN_WRITES) == {"_build_cards", "_build_pendings", "_build_outflows"} and all(set(v) <= NAMES for v in AB.SCREEN_WRITES.values())
    and set(AB.SCREEN_WRITES_DATA) <= {"_build_cards", "_build_pendings", "_build_outflows", "_build_daily", "_build_futidx", "_build_tail"}
    and all(set(v) <= set(OLDN) - NAMES - {"books", "ctx"} for v in AB.SCREEN_WRITES_DATA.values()),
    "B6 선언 표: SCREEN_WRITES = 장부 필드 · SCREEN_WRITES_DATA = 경계 데이터(옛 이름) · 열쇠 = 화면 단계 메서드 이름")
bk6 = AB.Books()
bk6.tax_rows.append({"a": Decimal("1.0")})
sl0 = AB.books_seal(bk6)
chk(set(sl0) == NAMES and sl0 == AB.books_seal(bk6), "B6 books_seal = 필드마다 지문 · 같은 내용 = 같은 봉인")
bk6.tax_rows.append({"a": Decimal("2")})
bk6.realized_by_date["2026-10-18"] = 1.5
sl1 = AB.books_check(sl0, bk6, "_build_cards")
chk(sl1 == AB.books_seal(bk6) and sl1 != sl0, "B6 books_check 선언 안 쓰기(cards: tax_rows·realized_by_date) = 통과 · 새 봉인 반환")
bad6 = []
for stage, mut in (("_build_pendings", lambda: bk6.tax_rows.append({})), ("_build_tail", lambda: bk6.realized_by_date.update(x=1)),
                   ("_build_cards", lambda: bk6.gas_by_chain.update(eth={})), ("_build_cards", lambda: bk6.fee_day.pop("nope", None) or bk6.fee_day.update(d=[0, 0]))):
    s0 = AB.books_seal(bk6)
    mut()
    try:
        AB.books_check(s0, bk6, stage)
        bad6.append(stage)
    except AssertionError as e:
        if stage not in str(e):
            bad6.append(str(e))
chk(not bad6, "B6 books_check 선언 밖 쓰기 = AssertionError(직전↔직후만 비교 · 단계 이름)", bad6)
d6 = AB.Books()
d6.realized_by_date.update(a=1, b=2)
s6 = AB.books_seal(d6)
d6.realized_by_date.clear()
d6.realized_by_date.update(b=2, a=1)
chk(AB.books_seal(d6) != s6, "B6 봉인은 dict 순서 바뀜도 잡음(같은 내용 · 다른 삽입 순서)")
rr6 = _mk(dict(scope, books=bk6, **{n: getattr(bk6, n) for n in NAMES}))
sc6 = rr6.screen_scope(None)
calls6 = []
s7 = AB.screen_check(AB.books_seal(bk6), rr6, sc6, "_build_daily", lambda c, s, w: calls6.append(w))
chk(calls6 == ["_build_daily"] and s7 == AB.books_seal(bk6), "B6 screen_check = 별칭 확인(입력 묶음 = 넘긴 check_ctx) + 봉인 → 새 봉인")
try:
    AB.screen_check(s7, rr6, dict(sc6, tax_rows=[]), "_build_daily", lambda c, s, w: None)
    msg = None
except AssertionError as e:
    msg = str(e)
chk(msg is not None and "tax_rows" in msg and "_build_daily" in msg, "B6 screen_check 장부 별칭 다시 묶임 = AssertionError", msg)

REPLAY_STAGES = ("_replay_prep", "_replay_rt", "_replay_links", "_replay_main")
BUNDLES = ("li", "lko", "ri", "rto", "po", "pre")


def _p7(tree):
    fns = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in REPLAY_STAGES]
    ledgers = set()
    for fn in fns:
        for st in ast.walk(fn):
            if (isinstance(st, ast.Assign) and len(st.targets) == 2 and isinstance(st.targets[0], ast.Name) and isinstance(st.targets[1], ast.Attribute)
                    and getattr(st.targets[1].value, "id", "") == "px" and st.targets[1].attr == st.targets[0].id
                    and isinstance(st.value, ast.Call) and isinstance(st.value.func, ast.Attribute)
                    and getattr(st.value.func.value, "id", "").startswith("accounting_") and st.value.func.attr[:1].isupper()):
                ledgers.add(st.targets[0].id)
    owner, bad = {}, []
    for fn in fns:
        for st in ast.walk(fn):
            if not isinstance(st, ast.Assign):
                continue
            for tg in st.targets:
                if isinstance(tg, ast.Name):
                    pairs = [(tg, st.value)]
                elif isinstance(tg, ast.Tuple) and isinstance(st.value, ast.Tuple) and len(tg.elts) == len(st.value.elts):
                    pairs = list(zip(tg.elts, st.value.elts))
                else:
                    continue
                for t9, v9 in pairs:
                    if not (isinstance(t9, ast.Name) and isinstance(v9, ast.Attribute)):
                        continue
                    at = "%s:%d %s ← %s" % (fn.name, st.lineno, t9.id, ast.unparse(v9))
                    if isinstance(v9.value, ast.Name) and v9.value.id in ledgers:
                        if t9.id != v9.attr:
                            bad.append(at + " (장부 별칭 이름 엇갈림)")
                        owner.setdefault(t9.id, set()).add(v9.value.id)
                    elif isinstance(v9.value, ast.Name) and v9.value.id in BUNDLES:
                        if _norm9(t9.id) != v9.attr:
                            bad.append(at + " (묶음 풀기 이름 ≠ 필드)")
                    elif (isinstance(v9.value, ast.Attribute) and isinstance(v9.value.value, ast.Name) and v9.value.value.id in BUNDLES
                          and v9.value.attr == "ctx"):
                        if t9.id != v9.attr:
                            bad.append(at + " (ctx 풀기 이름 ≠ 필드)")
    bad += ["%s 주인 둘 %s" % (n, sorted(o)) for n, o in sorted(owner.items()) if len(o) > 1]
    return ledgers, bad


led7, bad7 = _p7(rp)
chk(len(led7) >= 11 and not bad7, "P7 리플레이 장부 별칭 `X = <장부>.X` 이름 대응 · 주인 하나 · 묶음 풀기 = 필드 이름(장부변수 %d)" % len(led7), (sorted(led7), bad7[:10]))
SYN7 = """
class M:
    def _replay_prep(self, conn):
        fbx = px.fbx = accounting_fee.FeeBook(px)
        cpx = px.cpx = accounting_cp.CostPools(px)
        wd_fee_add = fbx.wd_fee_add
        ex_fee_add = fbx.wd_fee_add
        (consume, ev,) = (cpx.consume, cpx.cp_emit,)
        wd_fee_q = fbx.wd_fee_q
        wd_fee_q = cpx.wd_fee_q
        other = sb.px
    def _replay_main(self, pre):
        (G, _qfmt, conn, br_arr9, zz,) = (pre.G, pre.qfmt, pre.ctx.conn, lko.br_arr, lko.yy,)
"""
led9, bad9 = _p7(ast.parse(SYN7))
chk(led9 == {"fbx", "cpx"} and len(bad9) == 4 and any("ex_fee_add ← fbx.wd_fee_add" in b for b in bad9) and any("ev ← cpx.cp_emit" in b for b in bad9)
    and any("wd_fee_q 주인 둘" in b for b in bad9) and any("zz ← lko.yy" in b for b in bad9),
    "P7 합성: 이름 엇갈림(단일·튜플 칸) · 주인 둘 · 묶음 풀기 이름 ≠ 필드 = 실패 · 장부 아닌 `sb.px`·규약 맞는 풀기 = 통과", bad9)

MAIN_BUNDLE = "pre"


def _b3(tree):
    mainf = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_replay_main"), None)
    if mainf is None:
        return ["_replay_main 없음"]
    body = [x for x in mainf.body if not (isinstance(x, ast.Expr) and isinstance(x.value, ast.Constant))]
    head = body[0] if body and isinstance(body[0], ast.Assign) and isinstance(body[0].targets[0], ast.Tuple) else None
    rebound = {n.id for st in body if st is not head for n in ast.walk(st) if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del))}
    ret = body[-1] if body else None
    if not (isinstance(ret, ast.Return) and isinstance(ret.value, ast.Call) and ast.unparse(ret.value.func) == "accounting_books.ReplayResult" and not ret.value.args):
        return ["꼬리가 `return accounting_books.ReplayResult(키워드…)` 가 아님"]
    kw = {k.arg: k.value for k in ret.value.keywords}
    bad = []
    for f in AB._CONTRACT:
        o = AB.OLD.get(f, f)
        v = kw.get(f)
        if v is None:
            bad.append("%s 빠짐" % f)
            continue
        pre_ok = isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name) and v.value.id == MAIN_BUNDLE and v.attr == f
        bare_ok = isinstance(v, ast.Name) and v.id == o
        if f in ("books", "ctx"):
            if not pre_ok:
                bad.append("%s ← %s (pre.%s 여야)" % (f, ast.unparse(v), f))
        elif pre_ok:
            if o in rebound:
                bad.append("%s ← pre.%s (main 이 %s 를 다시 묶음 → 맨 이름이어야)" % (f, f, o))
        elif bare_ok:
            if o not in rebound:
                bad.append("%s ← %s (main 지역 아님 → pre.%s 여야)" % (f, o, f))
        else:
            bad.append("%s ← %s (맨 이름 %s 도 pre.%s 도 아님)" % (f, ast.unparse(v), o, f))
    if not (isinstance(kw.get("_keep"), ast.Name) and kw["_keep"].id == MAIN_BUNDLE):
        bad.append("_keep=pre 아님")
    if not (isinstance(kw.get("_cb"), ast.Name) and kw["_cb"].id == "cb"):
        bad.append("_cb=cb 아님")
    bad += ["모르는 키워드 %s" % k for k in kw if k not in AB._CONTRACT and k not in ("_keep", "_cb")]
    return bad


bad3 = _b3(rp)
chk(not bad3, "B3′ ReplayResult 직접 생성 = 필드마다 맨 이름(main 재묶음) 또는 pre.<필드> 둘 중 하나 · _keep=pre · _cb=cb · 빠짐 0(경계 %d)" % len(AB._CONTRACT), bad3[:12])
SYN3 = """
class M:
    def _replay_main(self, pre):
        (G, rows, debt_capg9,) = (pre.G, pre.rows, pre.debt_capg,)
        rows = list(rows)
        debt_neg9 = {}
        return accounting_books.ReplayResult(books=pre.books, ctx=pre.ctx, %s, _keep=pre, _cb=cb)
"""
_std = ["%s=%s" % (f, ("rows" if f == "rows" else "debt_neg9" if f == "debt_neg" else "pre." + f)) for f in AB._CONTRACT if f not in ("books", "ctx")]
ok3 = _b3(ast.parse(SYN3 % ", ".join(_std)))
chk(not ok3, "B3′ 합성 정상(맨 이름 = 재묶음 둘 · 나머지 pre) = 통과", ok3)
bad_syn = []
for lab, repl in (("오연결 debt_neg=debt_capg9", ("debt_neg=debt_neg9", "debt_neg=debt_capg9")), ("rows=pre.rows(재묶음인데 pre)", ("rows=rows", "rows=pre.rows")),
                  ("G=G(main 지역 아님)", ("G=pre.G", "G=G")), ("필드 빠짐", ("G=pre.G, ", "")), ("_keep 아님", ("_keep=pre", "_keep=rows")), ("옛 _scope", ("_keep=pre", "_scope=pre"))):
    txt = (SYN3 % ", ".join(_std)).replace(*repl)
    r9 = _b3(ast.parse(txt))
    if not r9:
        bad_syn.append(lab)
chk(not bad_syn, "B3′ 합성 반례(오연결 · 재묶음인데 pre · 지역 아닌 맨 이름 · 필드 빠짐 · _keep 아님 · 옛 _scope) = 실패", bad_syn)

T.finish()
