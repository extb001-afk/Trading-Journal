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


def _unpack_el(e, nm, ctx=None):
    if isinstance(e, ast.Attribute):
        if ctx is not None and isinstance(e.value, ast.Name) and e.value.id == ctx:
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
rr = RR.from_scope(scope)
edge = [f.name for f in dataclasses.fields(RR) if f.name not in ("books", "ctx", "_scope", "_cb")]
chk(rr.books is bk and rr.ctx is cx and all(getattr(rr, f) is scope[AB.OLD.get(f, f)] for f in edge),
    "B5 from_scope = 같은 객체(필드 %d · 옛 이름 %d)" % (len(edge) + 2, len(OLDN)))
old = rr.as_old_names()
chk(set(old) == set(OLDN) and old is not scope and all(old[n] is getattr(bk, n) for n in NAMES) and old["books"] is bk
    and all(old[AB.OLD.get(f, f)] is getattr(rr, f) for f in edge) and "other9" not in old,
    "B5 as_old_names = 옛 이름 새 dict(Books 필드 = 장부 필드 같은 객체 · 경계 밖 리플레이 지역 없음)")
inv = ("e", "1")
sc9 = rr.screen_scope(inv)
chk(sc9["daily_inval"] is inv and set(sc9) == set(OLDN) | {"daily_inval"} and sc9 is not old, "B5 screen_scope = 옛 이름 + daily_inval(부를 때마다 새 dict)")
try:
    RR.from_scope({k: v for k, v in scope.items() if k != "dep_tr9"})
    miss = None
except KeyError as e:
    miss = str(e)
chk(miss == "'dep_tr9'", "B5 경계 이름 빠짐 = KeyError(조용한 None 아님 · .get 으로 읽는 dep_tr9 도)", miss)
try:
    rr.rows = []
    froz = False
except dataclasses.FrozenInstanceError:
    froz = True
chk(froz, "B5 필드 다시 묶기 불가(frozen)")
ctx_calls = []
AB.check_rr(rr, scope, "t", lambda c, s, w: ctx_calls.append((c, w)))
chk(ctx_calls == [(cx, "t")], "B5 check_rr 같은 객체 = 통과(입력 묶음 검사는 넘긴 check_ctx 로)", ctx_calls)
for bad9, want in ((dict(scope, rows=[]), "rows"), (dict(scope, tax_rows=[]), "tax_rows"), (dict(scope, debt_neg9={}), "debt_neg")):
    try:
        AB.check_rr(rr, bad9, "t4", lambda c, s, w: None)
        msg = None
    except AssertionError as e:
        msg = str(e)
    chk(msg is not None and want in msg and "t4" in msg, "B5 check_rr 다시 묶임 = AssertionError(%s)" % want, msg)

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
rr6 = RR.from_scope(dict(scope, books=bk6, **{n: getattr(bk6, n) for n in NAMES}))
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

T.finish()
