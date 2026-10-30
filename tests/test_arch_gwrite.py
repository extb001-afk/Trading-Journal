#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _arch as A  # noqa: E402

import os  # noqa: E402
import tempfile  # noqa: E402

import _arch_py_git as G  # noqa: E402
import _arch_py_gwrite as W  # noqa: E402

T = A.T
_SKIP_REF = ("none", "skip", "-", "0", "off")

_SAMPLE = '''
x = {}
x["cost"] = 1
class Book:
    y = {}
    y["realized"] = 0
    def take(self, g, d, xs, k):
        g["cost"] += 1
        g["cost"] -= 2
        d["g"]["realized"] -= 1
        a, (b, g["qty_known"]) = 1, (2, 3)
        del g["qty_unknown"]
        g["qty_timeline"].append((1, 2))
        g["qty_timeline"].extend([])
        g["qty_timeline"].insert(0, (0, 0))
        g["qty_timeline"] = []
        for g["cost"] in xs:
            pass
        g["other"] = 1
        g[k] = 1
        g.update(cost=1)
        tl = g["qty_timeline"]
        tl.append(1)
        g["qty_timeline"].pop()
        def inner(h):
            h["realized"] = 5
        return inner
'''


def _grammar():
    rows = W.scan_text(_SAMPLE)
    got = sorted((r["q"], r["b"], r["s"]) for r in rows)
    want = sorted([
        ("<module>", "x", "cost"), ("Book.<body>", "y", "realized"),
        ("Book.take", "g", "cost"), ("Book.take", "g", "cost"), ("Book.take", "g", "cost"),
        ("Book.take", "d['g']", "realized"), ("Book.take", "g", "qty_known"), ("Book.take", "g", "qty_unknown"),
        ("Book.take", "g", "qty_timeline"), ("Book.take", "g", "qty_timeline"), ("Book.take", "g", "qty_timeline"),
        ("Book.take", "g", "qty_timeline"), ("Book.take.inner", "h", "realized")])
    T.chk(got == want, "money.gwrite 정의: 대입·증감·del·for 대상·튜플 풀기·중첩 바탕·시계열 append·extend·insert·대입 · 모듈·클래스 몸통·안쪽 함수 "
          "이름 사슬 · 상수 열쇠 밖·계산된 열쇠·update·시계열 별칭·pop 은 셈 밖(알려진 한계)", [got, want] if got != want else None)
    inner = [r for r in rows if r["q"] == "Book.take.inner"]
    T.chk(bool(inner) and inner[0]["f"] == "take.inner" and inner[0]["h"], "money.gwrite 정의: 함수 경로 f(클래스 뺌)·지문 h 를 묶음에 적음",
          inner[:1])
    rules = {"money_modules": ["acct_a", "acct_basis", "acct_gone"], "api_allow": {"gwrite": ["acct_basis"]}}
    T.chk(W.counted_modules(rules, ["acct_a", "acct_basis", "other_mod"]) == ["acct_a"],
          "money.gwrite 셈 대상 = money_modules ∩ 있는 모듈 − 허용(api_allow.gwrite) · 아직 없는 모듈은 셈 밖")
    leg = W.legacy_calls_text("def f(cb, g, q, c):\n    cb.acquire(g, q, c, 1, 2, u=q)\n    cb.capitalize(g, c)\n    cb.release(g, q, c, q, floor=False)\n"
                              "    cb.convert(g, q, c)\n    px.cb.add_known(g, q)\n    self.cb.sub_cost(g, c)\n    x.floor_sub_unknown(g, q)\n"
                              "    add_cost(g, c)\n    g.add_unknown\n")
    T.chk([ln for ln, _t in leg] == [6, 7, 8], "API 소유권 정의: 옛 한 칸 쓰기 7개의 메서드 호출만(바탕 무관) · 깔때기 넷·맨 이름 호출·값 참조는 셈 밖", leg)
    with tempfile.TemporaryDirectory() as d:
        for name, text in (("accounting_basis.py", "class CostBasis:\n    def acquire(self, g, q, c):\n        self.add_known(g, q)\n"),
                           ("acct_x.py", "def f(cb, g):\n    cb.add_known(g, 1)\n"), ("acct_ok.py", "def f(cb, g):\n    cb.acquire(g, 1, 1)\n")):
            with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                f.write(text)
        hits = W.legacy_calls(d)
    T.chk(hits == ["src/acct_x.py:2 cb.add_known(g, 1)"], "API 소유권 정의: 깔때기 주인(accounting_basis) 안 호출은 셈 밖 · 밖 모듈 호출 = 자리 글", hits)


def _rows(text, m):
    out = W.scan_text(text)
    for r in out:
        r["m"] = m
    return out


def _rows_sc(text, m, sc):
    out = W.scan_text(text, scopes=sc)
    for r in out + sc:
        r["m"] = m
    return out


def _ratchet():
    old = _rows("class B:\n    def take(self, g):\n        g['cost'] += 1\n        g['cost'] -= 2\n        fl['cost'] += 1\n", "acct_a")
    base = [dict(W.identity(u), c="group" if u["b"] == "g" else "other:flow", t=u["t"]) for u in W.bundles(old)]
    renamed = W.bundles(_rows("class B:\n    def take_out(self, g):\n        g['cost'] += 1\n        g['cost'] -= 2\n"
                              "        fl['cost'] += 1\n", "acct_a"))
    vd = W.compare(renamed, base)
    T.chk(vd.ok and vd.moved == 2, "money.gwrite 래칫: 함수 이름만 바꿈 = 지문 짝으로 이어 받음(새 0 · 옮김 2)", vars(vd) if not vd.ok else None)
    grown = W.bundles(_rows("class B:\n    def take(self, g):\n        g['cost'] += 1\n        g['cost'] -= 2\n        g['cost'] -= 3\n"
                            "        fl['cost'] += 1\n        g9['realized'] = 0\n", "acct_a"))
    vd = W.compare(grown, base)
    T.chk(len(vd.grew) == 1 and len(vd.new) == 1, "money.gwrite 래칫: 묶음 개수 증가 = 커짐 · 표에 없는 묶음 = 새 묶음(분류 강제)",
          [len(vd.grew), len(vd.new)])
    fewer = W.bundles(_rows("class B:\n    def take(self, g):\n        g['cost'] += 1\n", "acct_a"))
    vd = W.compare(fewer, base)
    lines, _vd = W.tighten(fewer, base)
    T.chk(vd.ok and len(vd.stale) == 2 and lines is not None and [(x["b"], x["v"], x["c"]) for x in lines] == [("g", 1, "group")],
          "money.gwrite 래칫: 줄어듦·사라짐 = 낮출 수 있음 · --update-lower 는 분류를 이어받아 줄인 값만", lines)
    new = [dict(b) for b in base]
    new[0]["c"] = "other:agg" if new[0]["c"] == "group" else "group"
    new[1]["v"] += 1
    new.append(dict(base[0], b="g7", v=1, c="other:agg"))
    bad = W.loosened(new, base, W.bundles(old))
    T.chk(sum(x.startswith("분류 바뀜") for x in bad) == 1 and sum(x.startswith("새 줄") for x in bad) == 1
          and sum(x.startswith("커짐") for x in bad) == 1, "money.gwrite 무결성: 분류 바뀜·새 줄·값 올림 = 느슨해짐(총괄 승인)", bad)
    steal_text = ("class B:\n    def take(self, g):\n        return g\n"
                  "class N:\n    def take(self, g):\n        g['cost'] += 1\n")
    sc = []
    steal = _rows_sc(steal_text, "acct_a", sc)
    vd = W.compare(W.bundles(steal), base, sc)
    T.chk(len(vd.new) == 1 and vd.new[0]["q"] == "N.take", "money.gwrite 래칫: 원래 함수가 쓰기 0 으로 남으면 그 자리가 자기 줄을 붙잡음"
          " — 이름·경로가 같은 새 함수의 쓰기 = 새 묶음(가로채기 막기)", [u["q"] for u in vd.new])
    with tempfile.TemporaryDirectory() as d:
        body = "    def take(self, g):\n        g['cost'] += 1\n        g['cost'] -= 2\n        fl['cost'] += 1\n"
        for name, text in (("acct_basis.py", "class B:\n" + body),
                           ("acct_a.py", "class N:\n    def take(self, g):\n        g['cost'] += 1\n")):
            with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                f.write(text)
        rules = {"money_modules": ["acct_a", "acct_basis"], "api_allow": {"gwrite": ["acct_basis"]}}
        rows, sc, errors = W.survey(d, rules)
        vd = W.compare(W.bundles(rows), base, sc)
    T.chk(not errors and len(vd.new) == 1 and {u["m"] for u in sc} == {"acct_a", "acct_basis"},
          "money.gwrite 래칫: 허용 모듈로 옮긴 원래 함수도 짝짓기에 참여(범위 = src 모든 모듈) — 같은 이름 새 함수의 쓰기 = 새 묶음",
          [len(vd.new), sorted({u["m"] for u in sc}), errors])
    forged = [dict(b) for b in base]
    forged[1]["h"] = "0123456789ab"
    bad = W.loosened(forged, base, W.bundles(old))
    T.chk(len(bad) == 1 and bad[0].startswith("지문·경로 바뀜"), "money.gwrite 무결성: 기준선 줄 지문·경로를 손으로 바꿈 = 느슨해짐"
          "(짝짓기 열쇠 세탁 막기 · 지금 소스 값으로 새로 적은 것만 허용)", bad)
    moved = [dict(W.identity(u), c=b["c"]) for u, b in zip(renamed, base)]
    T.chk(not W.loosened(moved, base, renamed), "money.gwrite 무결성: 지금 소스에서 짝지은 옮김(이름 바꿈)의 새 신원 줄은 느슨해짐 아님")
    bad_lines = 0
    for text in ('{"k":"money.gwrite","m":"a","q":"f","b":"g","s":"cost","v":1,"c":"other:마음대로"}',
                 '{"k":"money.gwrite","m":"a","q":"f","b":"g","s":"cost","v":0,"c":"group"}',
                 '{"k":"money.gwrite","m":"a","q":"f","b":"g","s":"price","v":1,"c":"group"}'):
        try:
            W.parse(text, "sample")
        except ValueError:
            bad_lines += 1
    T.chk(bad_lines == 3, "money.gwrite 기준선 줄 모양: 이유는 닫힌 목록 · v ≥ 1 · 열쇠는 다섯 칸만", bad_lines)


def _real():
    st = A.state()
    if st.load_error or st.metrics is None:
        return T.chk(A.PUBLIC_LAYOUT, "money.gwrite: 규칙 파일 없음·못 읽음(공개판 배치면 건너뜀)", st.load_error or None)
    rows, scopes, errors = W.survey(A.SRC, st.rules)
    T.chk(not errors, "money.gwrite 소스 분석 실패 0", errors)
    cur = W.bundles(rows)
    path = os.path.join(A.BASE_DIR, W.FILE)
    try:
        base = W.load(path)
    except ValueError as e:
        return T.chk(False, "money.gwrite 기준선을 못 읽음", str(e))
    if base is None:
        return T.chk(A.PUBLIC_LAYOUT, "money.gwrite 기준선 있음(arch_baseline/%s — 처음 만들기 = 총괄 --freeze)" % W.FILE)
    vd = W.compare(cur, base, scopes)
    T.chk(not vd.new, "money.gwrite 표에 없는 묶음 0(새 원가 칸 쓰기 자리 = 분류 강제 · 규칙: 원가 칸은 CostBasis(accounting_basis)만 씀 · "
          "고치는 법: CostBasis 기본 함수를 불러라 — 그룹 밖 dict 면 총괄이 other:<이유> 로 분류)",
          ["%s %s %s[%r] = %d" % (u["at"], u["q"], u["b"], u["s"], u["v"]) for u in vd.new][:40])
    T.chk(not vd.grew, "money.gwrite 묶음 개수 증가 0(같은 함수·바탕·열쇠 자리 늘림 금지)",
          ["%s %s %s[%r] %d → %d" % (u["at"], u["q"], u["b"], u["s"], b["v"], u["v"]) for u, b in vd.grew][:40])
    by_key, by_c = W.summary(rows, cur, W.classified(cur, base, vd))
    print("참고 money.gwrite 문장 %s · 합 %d · 묶음 %d · 분류별(묶음, 문장) %s · 옮김 대응 %d" % (
        by_key, len(rows), len(cur), by_c, vd.moved), flush=True)
    if vd.stale:
        note = "money.gwrite 기준선 낮출 수 있음 %d줄(좋아짐·사라짐·옮김) — python3 public/tests/_arch_py_gwrite.py --update-lower" % len(vd.stale)
        if A.STALE_FAIL:
            T.chk(False, note + " (TJ_TEST_ARCH_STALE_FAIL=1)")
        else:
            print("안내 " + note, flush=True)
    _integrity(path, base, cur, scopes)


def _integrity(path, base, cur, scopes):
    ref = A._ENV["TJ_TEST_ARCH_BASE_REF"] or "refactor"
    if ref.lower() in _SKIP_REF:
        return T.chk(True, "money.gwrite 무결성 건너뜀 — TJ_TEST_ARCH_BASE_REF=%s" % ref)
    top = G.toplevel(A.ROOT)
    head, rc = G.commit_of(A.ROOT, "HEAD"), G.commit_of(A.ROOT, ref)
    mb = G.merge_base(A.ROOT, head, rc) if top and head and rc else None
    if not mb:
        return T.chk(True, "money.gwrite 무결성 건너뜀 — git 작업 트리·기준 '%s'·병합 기준점 중 없는 것이 있음" % ref)
    rel = os.path.relpath(os.path.realpath(path), top).replace(os.sep, "/")
    old_text = G.show(A.ROOT, mb, rel)
    if old_text is None:
        return T.chk(True, "money.gwrite 무결성 — 병합 기준점 %s 에 기준선 없음(처음 생기는 커밋) · 비교 없음" % mb[:8])
    try:
        old = W.parse(old_text, "%s@%s" % (W.FILE, mb[:8]))
    except ValueError as e:
        return T.chk(False, "money.gwrite 무결성 — 병합 기준점 기준선을 못 읽음", str(e))
    bad = W.loosened(base, old, cur, scopes)
    T.chk(not bad, "money.gwrite 무결성 — 병합 기준점 %s(%s) 대비 느슨해진 줄 %d(새 줄·값 올림·분류 바뀜 = 총괄 승인 · 기준 브랜치에서만)" % (
        mb[:8], ref, len(bad)), bad[:40])


def _funnel():
    hits = W.legacy_calls(A.SRC)
    T.chk(not hits, "API 소유권: CostBasis 옛 한 칸 쓰기(%s) 호출 = accounting_basis 밖 0건 — 원가 칸은 acquire·capitalize·release·convert 로만"
          % "·".join(W.LEGACY), hits[:40])


_grammar()
_ratchet()
_funnel()
_real()
T.finish()
