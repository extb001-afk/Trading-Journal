#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
from decimal import Decimal  # noqa: E402

chk = T.chk
TOOLS = os.path.join(T.ROOT, "tools", "refactor")
if not os.path.isfile(os.path.join(TOOLS, "cost_fp.py")):
    chk(True, "공개판 배치 — 비공개 도구(tools/refactor/cost_fp.py) 없음 · 건너뜀")
    T.finish()
sys.path.insert(0, TOOLS)
import cost_fp as CF  # noqa: E402
import cost_cov as CC  # noqa: E402

EPS = Decimal("1e-12")


def grp(gid, qk="1", cost="2", qu="0", rz="0", tl=None, flows=None):
    return {"gid": gid, "sym": "S%d" % gid, "chains": set(), "is_stable": False, "is_fiat": False,
            "qty_known": Decimal(qk), "cost": Decimal(cost), "qty_unknown": Decimal(qu), "realized": Decimal(rz),
            "flows": flows if flows is not None else [{"bought": Decimal(qk), "cost": Decimal(cost), "sold": Decimal(0)}],
            "cur": None, "transit": Decimal(0), "qty_timeline": tl if tl is not None else [(1, Decimal(qk))]}


class Bk:
    def __init__(self, **kw):
        self.realized_by_date = {"2026-01-01": Decimal("1.5"), "2026-01-02": Decimal("-0.5")}
        self.realized_krw_by_date = {"2026-01-01": Decimal(2000)}
        self.realized_by_loc = {("w1", "2026-01-01"): [Decimal(1), Decimal(1300)], ("x", "2026-01-02"): [Decimal(2), Decimal(10)]}
        self.tax_rows = [{"_acq": Decimal(1), "_disp": Decimal(2), "_qty": Decimal(3), "sym": "A"}]
        self.__dict__.update({f: {} for f in CF.SHA_BOOKS})
        self.__dict__.update(kw)


def same(a, b):
    return CF.diff(a, b)[0]


G1 = {1: grp(1), -2: grp(-2, "0", "0", "3")}
G2 = {1: grp(1), -2: grp(-2, "0", "0", "3")}
a = CF.build(G1, Bk(), EPS)
chk(same(a, CF.build(G2, Bk(), EPS)), "F1 같은 G 두 번 = 같은 지문")
chk(a["groups"][0][6] == "2" and a["groups"][1][6] == "0", "F1 wac = cost ÷ qty_known · qty_known ≤ EPS → 0", a["groups"])
G3 = {1: grp(1, "1.0"), -2: grp(-2, "0", "0", "3")}
ok, m = CF.diff(a, CF.build(G3, Bk(), EPS))
chk(not ok and any("qty_known 1 → 1.0" in x for x in m), "F1 Decimal 글자 1 ≠ 1.0 (지수·끝 0 구분)", m)
ok, m = CF.diff(a, CF.build({-2: G1[-2], 1: G1[1]}, Bk(), EPS))
chk(not ok and any("순서" in x for x in m), "F1 그룹 반복 순서 차이", m)
G4 = {1: grp(1, flows=[{"bought": Decimal(1), "cost": Decimal(2), "sold": Decimal(0), "moved_cost": Decimal(1)}]), -2: G1[-2]}
ok, m = CF.diff(a, CF.build(G4, Bk(), EPS))
chk(not ok and any("sha_flows" in x for x in m), "F1 사이클 칸(moved_cost) 차이", m)
G5 = {1: grp(1, tl=[(1, Decimal(1)), (2, Decimal(0))]), -2: G1[-2]}
ok, m = CF.diff(a, CF.build(G5, Bk(), EPS))
chk(not ok and any("n_tl 1 → 2" in x for x in m), "F1 시계열 길이 차이", m)
G6 = {1: grp(1, flows=[{"bought": Decimal(1), "cost": Decimal(2), "sold": Decimal(0), "note": "표시"}]), -2: G1[-2]}
chk(same(a, CF.build(G6, Bk(), EPS)), "F1 사이클의 원가 밖 칸(note)은 지문 밖")

ok, m = CF.diff(a, CF.build(G1, Bk(realized_by_date={"2026-01-01": Decimal("1.5"), "2026-01-02": Decimal("-0.50")}), EPS))
chk(not ok and any("books.realized_by_date" in x for x in m), "F2 실현 글자 차이", m)
bb = CF.build(G1, Bk(), EPS)["books"]
chk(bb["realized_by_loc"]["sum"] == ["3", "1310"] and bb["realized_by_date"]["sum"] == "1.0", "F2 실현 합(위치별 USD·원화)", bb)
ok, m = CF.diff(a, CF.build(G1, Bk(tax_rows=[{"_acq": Decimal(1), "_disp": Decimal(2), "_qty": Decimal(4)}]), EPS))
chk(not ok and any("books.tax_rows" in x for x in m), "F2 세금 행 _qty 차이", m)
chk(same(a, CF.build(G1, Bk(tax_rows=[{"_acq": Decimal(1), "_disp": Decimal(2), "_qty": Decimal(3), "sym": "B"}]), EPS)),
    "F2 세금 행 원가 밖 칸(sym)은 지문 밖")
ok, m = CF.diff(a, CF.build(G1, Bk(realized_krw_by_date={"2026-01-02": Decimal(0), "2026-01-01": Decimal(2000)}), EPS))
chk(not ok, "F2 dict 넣은 순서 차이도 잡음(합은 같아도)", m)
ok, m = CF.diff(a, CF.build(G1, Bk(gas_nopx={-2: Decimal(1)}), EPS))
chk(not ok and any("books.gas_nopx" in x for x in m), "F2 가스 원가 칸 차이", m)


bf = CF.build(G1, Bk(realized_by_date={"d1": 1.5, "d2": Decimal("0.5")}, realized_by_loc={("w", "d1"): [0.25, 300.0]}), EPS)["books"]
chk(bf["realized_by_date"]["sum"] == "2.0" and bf["realized_by_loc"]["sum"] == ["0.25", "300.0"], "F2 합계에 float 실현도 듦", bf)


class Bare:
    pass


chk(CF.build(G1, Bare(), EPS)["books"]["tax_rows"] == {"missing": True}, "F2 없는 필드 = missing")

def run_trail(seq, G):
    tr = CF.Trail()

    def gstate(row):
        return G[row["gid"]]
    gs = tr.wrap(gstate)
    for pid, gid, dq in seq:
        g = gs({"posting_id": pid, "gid": gid})
        g["qty_known"] += Decimal(dq)
    tr.finish()
    return tr


Ga = {1: grp(1), 2: grp(2)}
Gb = {1: grp(1), 2: grp(2)}
ta = run_trail([(10, 1, "1"), (11, 2, "1"), (12, 1, "1")], Ga)
tb = run_trail([(10, 1, "1"), (11, 2, "2"), (12, 1, "1")], Gb)
chk(ta.calls == 3 and len(ta.rows) == 3, "F3 호출 3 → 궤적 3(마지막은 finish)", ta.rows)
chk([r[0] for r in ta.rows] == [10, 11, 12] and [r[1] for r in ta.rows] == [1, 2, 1], "F3 궤적 = (posting, 그룹) 차례")
fa = CF.build(Ga, Bk(), EPS, ta)
fb = CF.build(Gb, Bk(), EPS, tb)
ok, m = CF.diff(fa, fb)
chk(not ok and any("처음 갈린 행 #1" in x and "posting 11" in x for x in m), "F3 처음 갈린 행·그룹 보고", m)
Gc = {1: grp(1), 2: grp(2)}
chk(same(fa, CF.build(Gc, Bk(), EPS, run_trail([(10, 1, "1"), (11, 2, "1"), (12, 1, "1")], Gc))), "F3 같은 차례 = 같은 궤적")
Gd = {1: grp(1), 2: grp(2)}
td = run_trail([(10, 1, "1"), (12, 1, "1"), (11, 2, "1")], Gd)
ok, m = CF.diff(fa, CF.build(Gd, Bk(), EPS, td))
chk(not ok and any("궤적" in x for x in m) and not any(x.startswith("그룹 ") for x in m), "F3 최종 값 같아도 중간 차례가 다르면 잡음", m)
chk(CF.Trail._pid({"x": 1}) is None, "F3 posting_id 없는 합성 행 = None")
chk(ta.rows[0][2] != run_trail([(10, 1, "2")], {1: grp(1)}).rows[0][2], "F3 해시 = 그 행 처리 뒤 상태")

tmp = tempfile.mkdtemp(prefix="tj_costfp_")
try:
    pa, pb, pc = (os.path.join(tmp, n) for n in ("a.cost.json", "b.cost.json", "c.json"))
    for p, d in ((pa, fa), (pb, fb), (pc, {"x": 1})):
        with open(p, "w", encoding="utf-8") as f:
            json.dump(d, f)
    for args9, want in (([pa, pa], 0), ([pa, pb], 1), ([pa, pc], 2), ([pa], 2)):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = CF.main(["cost_fp.py"] + args9)
        chk(rc == want, "F4 비교 CLI %s → %d" % ([os.path.basename(x) for x in args9], want), (rc, buf.getvalue()[-300:]))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

with open(os.path.join(T.SRC, "view_b_replay.py"), encoding="utf-8") as f:
    VB = f.read()
tree = ast.parse(VB)
fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
prep, mainf = fns.get("_replay_prep"), fns.get("_replay_main")
chk(prep is not None and any(isinstance(n, ast.FunctionDef) and n.name == "gstate" for n in ast.walk(prep)),
    "F5 _replay_prep 안에 def gstate(기록기가 바꿀 이름표 값)")


def head_binds(fn):
    out = {}
    for st in fn.body:
        if isinstance(st, ast.Assign) and isinstance(st.targets[0], ast.Tuple) and isinstance(st.value, ast.Tuple):
            for t, v in zip(st.targets[0].elts, st.value.elts):
                if isinstance(t, ast.Name) and isinstance(v, ast.Subscript) and isinstance(v.value, ast.Name) and v.value.id == "_bs9":
                    k = CC._const_key(v)
                    if k:
                        out[t.id] = k
    return out


hb = head_binds(mainf) if mainf else {}
chk(hb.get("gstate") == "gstate", "F5 _replay_main 머리 풀기 gstate = _bs9['gstate'](기록기가 본 루프에 닿음)", sorted(hb)[:5])
loop_calls = [n for n in ast.walk(mainf) if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
              and isinstance(n.value.func, ast.Name) and n.value.func.id == "gstate"
              and any(isinstance(t, ast.Name) and t.id == "g" for t in n.targets)] if mainf else []
chk(len(loop_calls) >= 1, "F5 본 루프 `g = gstate(…)` 자리 있음", len(loop_calls))
rebind = [n for n in ast.walk(mainf) if isinstance(n, (ast.Assign, ast.AugAssign)) and any(
    isinstance(t, ast.Name) and t.id == "gstate" for t in (n.targets if isinstance(n, ast.Assign) else [n.target]))
    and n not in mainf.body] if mainf else []
chk(not rebind, "F5 _replay_main 안에서 gstate 를 다시 묶지 않음", [n.lineno for n in rebind])
with open(os.path.join(TOOLS, "golden_dump.py"), encoding="utf-8") as f:
    GDT = ast.parse(f.read())


def _attr_path(n):
    parts = []
    while isinstance(n, ast.Attribute):
        parts.append(n.attr)
        n = n.value
    if isinstance(n, ast.Name):
        parts.append(n.id)
    return ".".join(reversed(parts))


wraps9 = sorted((n.lineno, n.value.id) for n in ast.walk(GDT) if isinstance(n, ast.Assign) and isinstance(n.value, ast.Name)
                and any(_attr_path(t) == "web.StateBuilder._build_replay" for t in n.targets))
chk([w for _, w in wraps9] == ["_br_v2", "_br_cost"], "F5 --cost 감싸기가 v2 감싸기 뒤(바깥 · v2 지문 자리 그대로)", wraps9)
args9 = [n.args[0].value for n in ast.walk(GDT) if isinstance(n, ast.Call) and _attr_path(n.func) == "ap.add_argument"
         and n.args and isinstance(n.args[0], ast.Constant)]
chk("--cost" in args9 and "--v2" in args9, "F5 golden_dump 인자 --cost(옛 --v2 그대로)", args9)
dumps9 = sorted(n.args[0].id for n in ast.walk(GDT) if isinstance(n, ast.Call) and _attr_path(n.func) == "json.dump"
                and n.args and isinstance(n.args[0], ast.Name))
chk(dumps9 == ["_cres", "res", "v2"], "F5 쓰기 = 옛(res)·v2·원가(_cres) 셋 · 따로", dumps9)

SYN = '''
def f(g, d, flow, k):
    g["qty_known"] += 1
    g["cost"] -= 2; g["qty_unknown"] = max(0, g["qty_unknown"] - 1)
    d["g"]["realized"] -= 3
    g["qty_timeline"].append((1, 2))
    g["qty_timeline"] = []
    flow["cost"] += 1
    g["other"] = 1
    g[k] = 5
    g.setdefault("cost", 0)
    a, g["realized"] = 1, 2
    del g["qty_known"]
    g["qty_timeline"].pop()
class C:
    def m(self, dn):
        dn["qty_timeline"].insert(0, 1)
'''
tmp = tempfile.mkdtemp(prefix="tj_costcov_")
try:
    os.makedirs(os.path.join(tmp, "src"))
    with open(os.path.join(tmp, "src", "accounting_syn.py"), "w", encoding="utf-8") as f:
        f.write(SYN)
    with open(os.path.join(tmp, "src", "other.py"), "w", encoding="utf-8") as f:
        f.write('def h(g):\n    g["cost"] += 1\n')
    rows = CC.sites(os.path.join(tmp, "src"))
    got = sorted((r["l"], r["base"], r["key"], r["kind"]) for r in rows)
    want = [(3, "g", "qty_known", "augAdd"), (4, "g", "cost", "augSub"), (4, "g", "qty_unknown", "set"),
            (5, "d['g']", "realized", "augSub"), (6, "g", "qty_timeline", "call.append"), (7, "g", "qty_timeline", "set"),
            (8, "flow", "cost", "augAdd"), (12, "g", "realized", "set"), (13, "g", "qty_known", "del"),
            (17, "dn", "qty_timeline", "call.insert")]
    chk(got == want, "C1 닫힌 정의 자리(중첩 바탕 · 시계열 · 같은 줄 두 문장 · 튜플 대입 · del · 다른 열쇠·계산된 열쇠·setdefault·pop 제외 · 대상 밖 파일 제외)", got)
    grows = CC.sites(os.path.join(tmp, "src"), group=True)
    chk(sorted({r["base"] for r in grows}) == ["dn", "g"], "C1 --group = 그룹 바탕만(flow·d['g'] 제외 · dn 포함)", sorted({r["base"] for r in grows}))
    chk(CC.GROUP_BASES[-1] == "d9f['g']", "C1 그룹 바탕 표에 중첩 d9f['g'](:3513 꼴)")
    cov = {"accounting_syn.py": [3, 4, 6]}
    r = CC.report(os.path.join(tmp, "src"), [{k: set(v) for k, v in cov.items()}], ["c"])
    chk(r["lines"] == 9 and r["hit"] == {"c": 3} and r["miss"] == [["accounting_syn.py", "C.m", [17]], ["accounting_syn.py", "f", [5, 7, 8, 12, 13]]], "C3 report 줄 수·실행됨·안 지남(함수별)", r)
    env9 = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    g9 = ["git", "-C", tmp]
    subprocess.run(g9 + ["init", "-q"], check=True, env=env9)
    subprocess.run(g9 + ["add", "-A"], check=True, env=env9)
    subprocess.run(g9 + ["commit", "-qm", "b"], check=True, env=env9)
    with open(os.path.join(tmp, "src", "accounting_syn.py"), "w", encoding="utf-8") as f:
        f.write(SYN.replace('g["qty_known"] += 1', 'g["qty_known"] += 7').replace('flow["cost"] += 1', 'flow["cost"] += 9'))
    with open(os.path.join(tmp, "src", "other.py"), "w", encoding="utf-8") as f:
        f.write('def h(g):\n    g["cost"] += 2\n')
    c9 = CC.changed(os.path.join(tmp, "src"), "HEAD", [{"accounting_syn.py": {3}}])
    with open(os.path.join(tmp, "src", "view_b_replay.py"), "w", encoding="utf-8") as f:
        f.write("a = 1\nb = 2\nc = 3\nd = 4\n")
    subprocess.run(g9 + ["add", "-A"], check=True, env=env9)
    subprocess.run(g9 + ["commit", "-qm", "c"], check=True, env=env9)
    with open(os.path.join(tmp, "src", "view_b_replay.py"), "w", encoding="utf-8") as f:
        f.write("a = 1\nb = 2\nd = 4\n")
    del9 = CC.changed_lines(os.path.join(tmp, "src"), "HEAD")
    chk(del9.get("view_b_replay.py") == {3}, "C3 지운 줄만 있는 덩어리(+2,0) = 다음 줄(3)로", del9)
    fs9 = c9["files"].get("accounting_syn.py") or {}
    chk(fs9.get("changed_stmt") == 2 and fs9.get("proved") == 1 and fs9.get("unfold_only") == [8] and "other.py" not in c9["files"],
        "C3 changed: 바뀐 문장 2 = 실행 증명 1 · 펼침 증명만 [8] · 대상 밖 파일 제외", c9)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

cur = CC.sites(T.SRC, group=True)
keys9 = {(r["fn"].split(".")[-1], r["base"], r["key"]) for r in cur}
out9 = sorted((r["f"], r["fn"], r["base"], r["key"]) for r in cur if r["f"] != "accounting_basis.py")
chk(out9 == [("accounting_unk.py", "UnkBook.note_unk", "g9", "cost")],
    "C2 지금 src 그룹 원가 쓰기(accounting_basis 밖) = UnkBook.note_unk 의 g9 cost 하나(basis_proof R1 거부 · 허용 목록 11막)", out9)
chk(not {k for k in keys9 if k[0] in ("consume", "fee_gain", "_h_disp", "_h_exf_fee", "_h_acq", "_h_move")},
    "C2 7-3·7-4 치환 함수(consume·fee_gain · _h_disp 형제 기증자 dn · _h_exf_fee 중첩 바탕 d9f['g'] · _h_acq · _h_move)의 그룹 자리 0(CostBasis 로 감)",
    sorted(k for k in keys9 if k[0] in ("consume", "fee_gain", "_h_disp", "_h_exf_fee", "_h_acq", "_h_move")))
inb9 = [r for r in cur if r["f"] == "accounting_basis.py"]
chk(inb9 and all(r["fn"].startswith("CostBasis.") for r in inb9) and len(cur) == len(inb9) + 1,
    "C2 나머지 그룹 자리 = CostBasis 기본 함수 몸통 %d문장(75a69cbf = 흩어진 130문장 · 127줄)" % len(inb9), sorted({r["fn"] for r in inb9}))
T.finish()
