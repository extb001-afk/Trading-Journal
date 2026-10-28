#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import os  # noqa: E402
import types  # noqa: E402
from decimal import Decimal  # noqa: E402

import accounting_basis as B  # noqa: E402
import accounting_books as AB  # noqa: E402
from view_common import EPS  # noqa: E402

chk = T.chk
D = Decimal
KEYS = ["gid", "sym", "chains", "is_stable", "is_fiat", "qty_known", "cost", "qty_unknown", "realized", "flows", "cur", "transit",
        "qty_timeline"]
FIVE = ("qty_known", "cost", "qty_unknown", "realized")

cb = B.CostBasis()
g1, g2 = cb.new_group(7, "ABC", True, False), cb.new_group(-3, "X", False, True)
types1 = [type(g1[k]).__name__ for k in KEYS]
chk(list(g1) == KEYS and types1 == ["int", "str", "set", "bool", "bool", "Decimal", "Decimal", "Decimal", "Decimal", "list", "NoneType",
                                     "Decimal", "list"]
    and all(str(g1[k]) == "0" for k in FIVE + ("transit",)) and g1["chains"] == set() and g1["flows"] == [] and g1["qty_timeline"] == []
    and (g1["gid"], g1["sym"], g1["is_stable"], g1["is_fiat"]) == (7, "ABC", True, False), "B1 new_group 열쇠·순서·초기값 종류", (list(g1), types1))
chk(g1["chains"] is not g2["chains"] and g1["flows"] is not g2["flows"] and g1["qty_timeline"] is not g2["qty_timeline"]
    and g2["is_fiat"] is True, "B1 부를 때마다 새 set·list")

OLD = {
    "add_known": (lambda g, a: g.__setitem__("qty_known", g["qty_known"] + a[0])),
    "add_unknown": (lambda g, a: g.__setitem__("qty_unknown", g["qty_unknown"] + a[0])),
    "add_cost": (lambda g, a: g.__setitem__("cost", g["cost"] + a[0])),
    "acquire": (lambda g, a: (g.__setitem__("qty_known", g["qty_known"] + a[0]), g.__setitem__("cost", g["cost"] + a[1]))),
    "sub_known": (lambda g, a: g.__setitem__("qty_known", g["qty_known"] - a[0])),
    "sub_unknown": (lambda g, a: g.__setitem__("qty_unknown", g["qty_unknown"] - a[0])),
    "sub_cost": (lambda g, a: g.__setitem__("cost", g["cost"] - a[0])),
    "release": (lambda g, a: (g.__setitem__("qty_known", g["qty_known"] - a[0]), g.__setitem__("cost", g["cost"] - a[1]),
                              g.__setitem__("qty_unknown", max(D(0), g["qty_unknown"] - a[2])))),
    "floor_sub_unknown": (lambda g, a: g.__setitem__("qty_unknown", max(D(0), g["qty_unknown"] - a[0]))),
    "convert": (lambda g, a: (g.__setitem__("qty_unknown", g["qty_unknown"] - a[0]), g.__setitem__("qty_known", g["qty_known"] + a[0]),
                              g.__setitem__("cost", g["cost"] + a[1]))),
    "realize": (lambda g, a: g.__setitem__("realized", g["realized"] + a[0])),
    "unrealize": (lambda g, a: g.__setitem__("realized", g["realized"] - a[0])),
    "snapshot": (lambda g, a: g["qty_timeline"].append((a[0], a[1]))),
}
ARGS = {"add_known": (D("1.25"),), "add_unknown": (D("0.3"),), "add_cost": (D("17.5"),), "acquire": (D("2"), D("3.333")),
        "sub_known": (D("0.75"),), "sub_unknown": (D("0.1"),), "sub_cost": (D("1.000000001"),), "release": (D("0.5"), D("2.5"), D("9")),
        "floor_sub_unknown": (D("0.2"),), "convert": (D("0.05"), D("0.5")), "realize": (D("-4.2"),), "unrealize": (D("1.1"),),
        "snapshot": (1700000000, D("-0.5"))}
seq = list(OLD) * 3
gn, go = cb.new_group(1, "A", False, False), cb.new_group(1, "A", False, False)
for n in seq:
    getattr(cb, n)(gn, *ARGS[n])
    OLD[n](go, ARGS[n])
chk([str(gn[k]) for k in FIVE] == [str(go[k]) for k in FIVE] and gn["qty_timeline"] == go["qty_timeline"],
    "B2 기본 함수 13개 × 3 차례 = 종전 문장(다섯 칸 Decimal 글자·시계열)", ([str(gn[k]) for k in FIVE], [str(go[k]) for k in FIVE]))
gw = cb.new_group(2, "W", False, False)
w0 = (cb.wac(gw), cb.wac_or_none(gw))
gw["qty_known"], gw["cost"] = EPS, D(5)
w1 = (cb.wac(gw), cb.wac_or_none(gw))
gw["qty_known"] = D(4)
w2 = (cb.wac(gw), cb.wac_or_none(gw))
chk(w0 == (D(0), None) and w1 == (D(0), None) and w2 == (D("1.25"), D("1.25")) and str(w2[0]) == str(D(5) / D(4)),
    "B2 wac(없으면 0)·wac_or_none(없으면 None) — qty_known ≤ EPS 경계", (w0, w1, w2))
bt = ast.parse(open(os.path.join(T.SRC, "accounting_basis.py"), encoding="utf-8").read())
cls = {c.name: c for c in bt.body if isinstance(c, ast.ClassDef)}
meths = [m for m in cls["CostBasis"].body if isinstance(m, ast.FunctionDef)]
dflt = [m.name for m in meths if m.args.defaults or any(d is not None for d in m.args.kw_defaults) or m.args.vararg or m.args.kwarg]
selfread = [m.name for m in meths for x in ast.walk(ast.Module(body=m.body[1:], type_ignores=[])) if isinstance(x, ast.Name) and x.id == "self"]
chk(not dflt and not selfread and {m.name for m in meths} == set(OLD) | {"new_group", "wac", "wac_or_none", "note_cost"},
    "B2 CostBasis 메서드 = 쓰기 13 + new_group·wac·wac_or_none + 기록만 note_cost · 기본값·*인자 없음 · 몸통이 self 를 읽지 않음", (dflt, selfread))
nc9 = next(m for m in meths if m.name == "note_cost")
chk(len(nc9.body) == 1 and ((isinstance(nc9.body[0], ast.Expr) and isinstance(nc9.body[0].value, ast.Constant)) or isinstance(nc9.body[0], ast.Pass)),
    "B2 CostBasis.note_cost 몸통 = 독스트링뿐(공개 빌드 = pass · 라이브 = 아무것도 안 함 · basis_proof R7 = 문장 뺌)")

chk(set(B._WRITES) == set(OLD) and all(getattr(B.StrictCostBasis, n) is not getattr(B.CostBasis, n) for n in B._WRITES)
    and B.StrictCostBasis.wac is B.CostBasis.wac and B.StrictCostBasis.wac_or_none is B.CostBasis.wac_or_none,
    "B3 쓰기 기본 함수 전부 그림자 쌍둥이(_WRITES = CostBasis 쓰기 메서드) · 읽기는 그대로")
sb = B.StrictCostBasis()
G = {}
for gid in (1, 2, 3):
    G[gid] = sb.new_group(gid, "S%d" % gid, False, False)
ga, gb = cb.new_group(1, "S1", False, False), G[1]
for n in seq:
    getattr(sb, n)(G[1], *ARGS[n])
    getattr(sb, n)(G[2], *ARGS[n])
    getattr(cb, n)(ga, *ARGS[n])
try:
    sb.check(G, "t0")
    e0 = None
except AssertionError as e:
    e0 = str(e)
chk(e0 is None and [str(gb[k]) for k in FIVE] == [str(ga[k]) for k in FIVE] and gb["qty_timeline"] == ga["qty_timeline"],
    "B3 기본 함수만 쓴 합성 그룹 = check 통과 · 값 = CostBasis(그림자 쌍둥이가 원본 값을 안 바꿈)", e0)


def _bypass(f, where):
    s2 = B.StrictCostBasis()
    G2 = {9: s2.new_group(9, "Z", False, False)}
    s2.acquire(G2[9], D(3), D(30))
    f(s2, G2)
    try:
        s2.check(G2, where)
        return None
    except AssertionError as e:
        return str(e)


b1 = _bypass(lambda s2, G2: G2[9].__setitem__("cost", G2[9]["cost"] + D("0.01")), "b1")
b2 = _bypass(lambda s2, G2: G2[9].__setitem__("qty_unknown", D(1)), "b2")
b3 = _bypass(lambda s2, G2: G2[9]["qty_timeline"].append((1, D(1))), "b3")
b4 = _bypass(lambda s2, G2: G2[9].__setitem__("realized", G2[9]["realized"] - D(2)), "b4")
chk(all(m is not None and "9" in m and w in m for m, w in ((b1, "b1"), (b2, "b2"), (b3, "b3"), (b4, "b4"))),
    "B3 우회 쓰기(cost 증감 · qty_unknown 대입 · 시계열 append · realized 감소) = AssertionError(자리·그룹)", (b1, b2, b3, b4))
b5 = _bypass(lambda s2, G2: G2.__setitem__(10, {"qty_known": D(0), "cost": D(0), "qty_unknown": D(0), "realized": D(0), "qty_timeline": []}), "b5")
b6 = _bypass(lambda s2, G2: s2.add_known({"qty_known": D(0)}, D(1)), "b6")
chk(b5 is not None and "new_group 밖" in b5 and b6 is not None and "new_group 밖 그룹 쓰기 1" in b6,
    "B3 new_group 밖 그룹(G 에 직접 넣음 · 기본 함수로 씀) = AssertionError", (b5, b6))

OLDN = AB.ReplayResult.old_names()
bk = AB.Books()
scope = {n: object() for n in OLDN}
scope.update({n: getattr(bk, n) for n in AB.Books.names()}, books=bk, ctx=object())


def _mk(sc, cb=None):
    return AB.ReplayResult(_keep=sc, _cb=cb, **{f: sc[AB.OLD.get(f, f)] for f in AB._CONTRACT})


rr0 = _mk(scope)
cbx = B.StrictCostBasis()
rr1 = _mk(scope, cbx)
fd = {f.name: f for f in __import__("dataclasses").fields(AB.ReplayResult)}
chk(rr0._cb is None and rr1._cb is cbx and "_cb" not in AB._CONTRACT and "_keep" not in AB._CONTRACT
    and "cb" not in rr1.as_old_names() and "cb" not in rr1.screen_scope(None) and not fd["_cb"].compare and not fd["_cb"].repr
    and fd["_cb"].default is None,
    "B4 ReplayResult._cb = 직접 생성 키워드 같은 객체(없으면 None) · 계약·화면 이름표·비교·repr 밖")
def _sc(cb9, G9):
    bk9 = AB.Books()
    rr9 = types.SimpleNamespace(books=bk9, ctx=None, _cb=cb9, G=G9)
    try:
        AB.screen_check(AB.books_seal(bk9), rr9, {n: getattr(bk9, n) for n in AB.Books.names()}, "_build_cards", lambda *a: None)
        return None
    except AssertionError as e:
        return str(e)


s4 = B.StrictCostBasis()
G4 = {1: s4.new_group(1, "Q", False, False)}
s4.acquire(G4[1], D(1), D(2))
sc_none, sc_ok, sc_plain = _sc(None, G4), _sc(s4, G4), _sc(B.CostBasis(), G4)
G4[1]["cost"] += D(1)
sc_bad = _sc(s4, G4)
chk(sc_none is None and sc_ok is None and sc_plain is None and sc_bad is not None and "_build_cards" in sc_bad,
    "B4 screen_check: _cb None·CostBasis(check 없음) = 그림자 검사 안 함 · 그림자 장부 = 통과 · 우회 쓰기 = AssertionError(단계 이름)", (sc_none, sc_ok, sc_plain, sc_bad))

imps = sorted({(n.module if isinstance(n, ast.ImportFrom) else a.name) for n in ast.walk(bt) if isinstance(n, (ast.Import, ast.ImportFrom))
               for a in n.names})
chk(imps == ["__future__", "decimal", "typing", "view_common"]
    and [a.name for n in bt.body if isinstance(n, ast.ImportFrom) and n.module == "view_common" for a in n.names] == ["EPS"],
    "B5 accounting_basis import = __future__·decimal·typing·view_common.EPS 만", imps)
rp = ast.parse(open(os.path.join(T.SRC, "view_b_replay.py"), encoding="utf-8").read())
gs = next(n for n in ast.walk(rp) if isinstance(n, ast.FunctionDef) and n.name == "gstate")
mkg = [ast.unparse(n.value.func) for n in ast.walk(gs) if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)]
lit = [n.lineno for n in ast.walk(rp) if isinstance(n, ast.Dict) and {"qty_known", "qty_timeline"} <= {getattr(k, "value", None) for k in n.keys}]
chk(mkg == ["cb.new_group"] and not lit, "B5 gstate = G[gid] = cb.new_group(…) · src 의 그룹 dict 리터럴 0(view_b_replay)", (mkg, lit))
calls, notes = [], []
for f in sorted(os.listdir(T.SRC)):
    if f.endswith(".py"):
        t = ast.parse(open(os.path.join(T.SRC, f), encoding="utf-8").read())
        par = {c: p for p in ast.walk(t) for c in ast.iter_child_nodes(p)}
        for n in ast.walk(t):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "check" and ast.unparse(n.func.value).endswith("cb"):
                fn = par.get(n)
                while fn is not None and not isinstance(fn, ast.FunctionDef):
                    fn = par.get(fn)
                calls.append((f, fn.name if fn else None, ast.unparse(n)))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "note_cost":
                notes.append((f, n))
chk(sorted(calls) == [("accounting_books.py", "screen_check", "rr._cb.check(rr.G, stage)"),
                      ("view_b_replay.py", "_build_replay", "rr._cb.check(rr.G, 'replay')")],
    "B5 7-4: 그림자 검사(cb.check) 부르는 src = _build_replay 끝 엄격 블록 + screen_check 둘뿐", calls)
br = next(n for n in ast.walk(rp) if isinstance(n, ast.FunctionDef) and n.name == "_build_replay")
blk = next((n for n in ast.walk(br) if isinstance(n, ast.If) and ast.unparse(n.test) == "calcguard.strict()"), None)
bt9 = [ast.unparse(x) for x in blk.body] if blk else []
chk(len(bt9) == 2 and bt9[0].startswith("if not isinstance(rr._cb, accounting_basis.StrictCostBasis):")
    and "raise AssertionError" in bt9[0] and bt9[1] == "rr._cb.check(rr.G, 'replay')",
    "B5 _build_replay 엄격 블록 = StrictCostBasis 아니면 AssertionError → cb.check(G) 두 문장(세션33 B1: 런타임 별칭 검사 check_rr 삭제 · 정적 시험으로)", bt9)
sc9 = next(n for n in ast.walk(ast.parse(open(os.path.join(T.SRC, "accounting_books.py"), encoding="utf-8").read()))
           if isinstance(n, ast.FunctionDef) and n.name == "screen_check")
chk(any(isinstance(x, ast.If) and ast.unparse(x.test) == "callable(getattr(rr._cb, 'check', None))" for x in sc9.body),
    "B5 screen_check 의 그림자 검사 = _cb 에 check 가 있을 때만(None = 시험이 만든 이름표)")

gq = cb.new_group(5, "N", False, False)
before9 = [str(gq[k]) for k in FIVE]
cb.note_cost(gq, D("2"), 1.5)
chk([str(gq[k]) for k in FIVE] == before9 and gq["qty_timeline"] == [], "B6 CostBasis.note_cost = 아무것도 안 함(값·시계열 무변)")


def _note(direct, note):
    s6 = B.StrictCostBasis()
    G6 = {5: s6.new_group(5, "N", False, False)}
    s6.add_unknown(G6[5], D(3))
    take, unit9 = min(D("2"), G6[5]["qty_unknown"]), 0.123456789
    s6.sub_unknown(G6[5], take)
    s6.add_known(G6[5], take)
    if direct:
        G6[5]["cost"] += take * Decimal(str(unit9))
    if note:
        s6.note_cost(G6[5], take, unit9)
    try:
        s6.check(G6, "n")
        return None, str(G6[5]["cost"])
    except AssertionError as e:
        return str(e), str(G6[5]["cost"])


n_ok, n_dir, n_note = _note(True, True), _note(True, False), _note(False, True)
chk(n_ok == (None, str(D("2") * Decimal(str(0.123456789)))) and n_dir[0] and "우회" in n_dir[0] and n_note[0] and n_note[1] == "0",
    "B6 직접 쓰기 + note_cost = check 통과(값 = 직접 쓰기) · 직접 쓰기만 = AssertionError · note_cost 만 = AssertionError(값 무변)", (n_ok, n_dir, n_note))
un = ast.parse(open(os.path.join(T.SRC, "accounting_unk.py"), encoding="utf-8").read())
pair9 = []
for n in ast.walk(un):
    for fld in ("body", "orelse"):
        b9 = getattr(n, fld, None)
        if isinstance(b9, list):
            for a9, c9 in zip(b9, b9[1:]):
                if isinstance(c9, ast.Expr) and isinstance(c9.value, ast.Call) and getattr(c9.value.func, "attr", None) == "note_cost":
                    pair9.append((ast.unparse(a9), ast.unparse(c9)))
chk(len(notes) == 1 and notes[0][0] == "accounting_unk.py"
    and pair9 == [("g9['cost'] += take * Decimal(str(unit9))", "unx.cb.note_cost(g9, take, unit9)")],
    "B6 note_cost 부름 = src 한 자리(UnkBook.note_unk · 직접 쓰기 바로 다음 문장 · 같은 바탕·수량·단가)", (len(notes), pair9))

T.finish()
