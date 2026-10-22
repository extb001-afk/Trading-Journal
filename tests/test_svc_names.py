#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import os  # noqa: E402

import _core_bounds as B  # noqa: E402
import _svc_names as N  # noqa: E402

chk = T.chk
HERE = os.path.dirname(os.path.abspath(__file__))
TAB = B.load_table(os.path.join(HERE, "arch_baseline", "svc_names.json"))
CB = B.load_table(os.path.join(HERE, "arch_baseline", "core_bounds.json"))

fx = B.facts(T.SRC, CB)
owned = N.owned_names(fx)
sites = N.scan_tree(T.ROOT, owned)
present = {k for k, _ in N.tree_files(T.ROOT)}
bad, lower = N.judge(sites, TAB, present)
chk(not bad, "서비스 이름 자리 ⊆ 표(새 자리·늘어남 0 · 켠 묶음 0)", bad[:20])
if lower:
    print("INFO 줄어든 자리 %d(표 갱신 = tools/refactor/svc_names.py --emit)" % len(lower))
chk(not [s for s in sites if s["cat"] == "parse?"], "검사 대상 파일 전부 파싱됨", [s["file"] for s in sites if s["cat"] == "parse?"][:5])
chk((TAB.get("enforce") or {}) == {"EXF": True, "PRICING": True, "RECON": True},
    "9-1~9-3 = EXF·RECON·PRICING 0 강제 켬", TAB.get("enforce"))
chk(not [s for s in sites if s["group"] == "EXF" and (s["file"], s["scope"], s["cat"], s["group"], s["name"])
         not in {tuple(a["key"]) for a in TAB.get("allow", [])}], "EXF 자리 0(손으로 남긴 자리 = allow + 이유만)")

meth = {n for n, c in fx["owner"].items() if fx["classes"][c]["group"] in B.GROUPS_SVC and any(m.name == n for m in fx["_idx"][c]["methods"])}
tests_only = [s for s in sites if s["file"].startswith("tests/")]
probes = sorted((s["file"], s["name"]) for s in sites if s["cat"] == "probe")
have_tools = os.path.isfile(os.path.join(T.ROOT, "tools", "rebuild2.py"))
chk(not [p for p in probes if fx["classes"][fx["owner"][p[1]]]["group"] == "EXF"] if all(p[1] in fx["owner"] for p in probes) else False,
    "기능 감지 EXF 자리 0(9-1 = 서비스 클래스·c.svc_exf 대상으로 옮김)", probes)
import core  # noqa: E402
import core_svc  # noqa: E402
_pn = {"_upbit_asset", "_consume_exf_retime", "_wd_fee_since_of", "_exf_fut_place_scope"}
chk(_pn <= set(dir(core_svc.ExfService)) and not (_pn & set(dir(core.Core))),
    "기능 감지 6 의 대상 이름 = 서비스 클래스에 있음(감지 참 = 새 판 길 · 옛 판 감지 의미 보존) · Core 에 없음", sorted(_pn & set(dir(core.Core))))
ma = {}
for s in tests_only:
    if s["cat"] == "assign" and s["name"] in meth:
        ma[s["group"]] = ma.get(s["group"], 0) + 1
chk(ma == {}, "시험의 서비스 메서드 갈아 끼우기 대입 0(9-1~9-3 가 c.svc_exf·c.svc_recon·c.svc_price 로)", ma)
emb_real = sorted(s["file"] for s in tests_only if s.get("embedded") and s["name"] == "EXF_INIT_PHASE" and s["cat"] == "assign")
chk(emb_real == [], "자식 프로세스 래퍼 글 안의 core.Core.EXF_INIT_PHASE 대입 0(9-1 이 core_svc.ExfService 로 옮김)", emb_real)
if have_tools:
    rb = sorted({(s["cat"], s["name"]) for s in sites if s["file"] == "tools/rebuild2.py" and s["cat"] == "assign"})
    with open(os.path.join(T.ROOT, "tools", "rebuild2.py"), encoding="utf-8") as fh:
        _rbt = ast.parse(fh.read())
    _asg = [ast.unparse(t) for x in ast.walk(_rbt) if isinstance(x, ast.Assign) for t in x.targets]
    chk(not [n for _c, n in rb if owned.get(n) in ("EXF", "PRICING")] and _asg.count("c.svc_price._last_price_pass") == 2
        and _asg.count("c.svc_exf._last_exrecon") == 1,
        "rebuild2 상태 대입: EXF·PRICING 0 · 덮기는 서비스 받는 쪽으로 옮겨 남음(c.svc_price._last_price_pass 2 · c.svc_exf._last_exrecon 1)", rb)
else:
    print("SKIP tools/ 없음(공개판 배치) — 도구 자리 건너뜀")

SYN = '''import core
import core as cm
from core import Core as K
from x import patch_cls_attr, patch_moved

c = core.Core({})
c.e_meth = 1
v = c.r_meth()
core.Core.E_CONST = 2
hasattr(core.Core, "e_meth")
getattr(c, "r_state", None)
K.p_meth(None)
A = core.Core
a2 = A({})
a2.e_meth = 3
n = cm.Core.__new__(cm.Core)
n.r_state = 1
o = object.__new__(core.Core)
o.p_meth()
sp = core.Core.settle_planner({}, None)
sp.e_meth()
d = c
d.r_meth()
c.__dict__["r_state"] = 1
c.__dict__.pop("e_state", None)
"r_state" in c.__dict__
setattr(c, "e_meth", 1)
delattr(c, "e_meth")
patch_cls_attr(core.Core, "r_meth", 1)
patch_moved("e_meth", 1)
del c.e_meth


def mk():
    c9 = core.Core({})
    return c9


m = mk()
m.r_meth = 1
for cc in (c, m):
    cc.__dict__.pop("e_state", None)
for k9 in ("r_meth", "e_state"):
    c.__dict__.pop(k9, None)


def helper(x, key):
    x.r_meth = 1
    setattr(x, key, 1)


helper(c, "a")
helper(m, "b")


def escaped(y):
    y.e_meth = 1


escaped(c)
cb = escaped
mixed = core.Core({})
mixed = 3
mixed.e_meth = 1


def unknown(z):
    z.p_meth = 1
    hasattr(z, "e_meth")
    z.__dict__.pop("r_state", None)


class Box:
    inner = core.Core({})

    def go(self):
        inner.e_meth = 1


class Sub(core.Core):
    def r_meth(self):
        return 0


x9 = core.Core.r_meth(core.Core, 1)
t1, t2 = core.Core({}), 5
t1.e_meth = 1
t2.e_meth = 1
plain = 7
plain.other = 1
'''
SYN_OWNED = {"e_meth": "EXF", "E_CONST": "EXF", "e_state": "EXF", "r_meth": "RECON", "r_state": "RECON", "p_meth": "PRICING"}
syn_path = os.path.join(T.TMP, "svc_syn.py")
with open(syn_path, "w", encoding="utf-8") as fh:
    fh.write(SYN)
ss = N.scan_file(syn_path, SYN_OWNED, "tests/svc_syn.py")
got = [(s["line"], s["cat"], s["name"]) for s in ss]
L = {i + 1: ln for i, ln in enumerate(SYN.split("\n"))}


def line_of(text, nth=1):
    hits = [i for i, ln in L.items() if ln.strip() == text]
    return hits[nth - 1] if len(hits) >= nth else -1


def has(text, cat, name):
    return (line_of(text), cat, name) in got


CASES = [
    ("c.e_meth = 1", "assign", "e_meth", "(a) Core(…) 인스턴스 대입"),
    ("v = c.r_meth()", "read", "r_meth", "(c) 인스턴스 읽기·부르기"),
    ("core.Core.E_CONST = 2", "assign", "E_CONST", "(a) 클래스 상수 대입"),
    ('hasattr(core.Core, "e_meth")', "probe", "e_meth", "(b) 클래스 기능 감지"),
    ('getattr(c, "r_state", None)', "probe", "r_state", "(b) 인스턴스 getattr 글자"),
    ("K.p_meth(None)", "read", "p_meth", "from core import Core as K 의 클래스 쪽 부르기"),
    ("a2.e_meth = 3", "assign", "e_meth", "클래스 별칭(A = core.Core)으로 만든 인스턴스"),
    ("n.r_state = 1", "assign", "r_state", "cm.Core.__new__(cm.Core)"),
    ("o.p_meth()", "read", "p_meth", "object.__new__(core.Core)"),
    ("sp.e_meth()", "read", "e_meth", "settle_planner(…) 결과"),
    ("d.r_meth()", "read", "r_meth", "인스턴스 별칭"),
    ('c.__dict__["r_state"] = 1', "indirect", "r_state", "(e) __dict__[글자] 대입"),
    ('c.__dict__.pop("e_state", None)', "indirect", "e_state", "(e) __dict__.pop(글자)"),
    ('"r_state" in c.__dict__', "indirect", "r_state", "(e) 글자 in __dict__"),
    ('setattr(c, "e_meth", 1)', "indirect", "e_meth", "(e) setattr 글자"),
    ('delattr(c, "e_meth")', "indirect", "e_meth", "(e) delattr 글자"),
    ('patch_cls_attr(core.Core, "r_meth", 1)', "indirect", "r_meth", "(e) patch_cls_attr(core.Core, 글자)"),
    ('patch_moved("e_meth", 1)', "patch_moved", "e_meth", "(e) patch_moved 글자"),
    ("del c.e_meth", "del", "e_meth", "(a) del 인스턴스 이름"),
    ("m.r_meth = 1", "assign", "r_meth", "같은 파일 함수가 돌려준 Core"),
    ('cc.__dict__.pop("e_state", None)', "indirect", "e_state", "Core 튜플을 도는 반복 변수"),
    ("c.__dict__.pop(k9, None)", "indirect", "r_meth", "변수 열쇠 = 같은 범위 글자 튜플로 풂(1)"),
    ("c.__dict__.pop(k9, None)", "indirect", "e_state", "변수 열쇠 = 같은 범위 글자 튜플로 풂(2)"),
    ("x.r_meth = 1", "assign", "r_meth", "인자 = 부르는 곳이 모두 Core"),
    ("setattr(x, key, 1)", "key?", "?", "변수 열쇠를 못 풂 = key?"),
    ("y.e_meth = 1", "assign?", "e_meth", "넘겨진(부르기 밖에서 쓰인) 함수의 인자 = 못 정함"),
    ("mixed.e_meth = 1", "assign?", "e_meth", "Core 와 다른 값이 섞인 이름 = 못 정함"),
    ("z.p_meth = 1", "assign?", "p_meth", "(d) 받는 쪽 못 정한 대입"),
    ('hasattr(z, "e_meth")', "probe?", "e_meth", "받는 쪽 못 정한 기능 감지"),
    ('z.__dict__.pop("r_state", None)', "indirect?", "r_state", "받는 쪽 못 정한 간접 꼴"),
    ("inner.e_meth = 1", "assign?", "e_meth", "클래스 몸통 이름은 메서드에서 안 보임 = 못 정함"),
    ("def r_meth(self):", "subclass", "r_meth", "Core 하위 클래스의 서비스 이름 정의"),
    ("t1.e_meth = 1", "assign", "e_meth", "튜플 풀기(같은 길이)"),
    ("x9 = core.Core.r_meth(core.Core, 1)", "read", "r_meth", "클래스 쪽 부르기(명시적 self)"),
    ("t2.e_meth = 1", "assign?", "e_meth", "튜플 풀기의 Core 아닌 칸 = 못 정함"),
]
for text, cat, name, label in CASES:
    chk(has(text, cat, name), "자체: %s" % label, {"줄": line_of(text), "찾음": [g for g in got if g[0] == line_of(text)]})
RK = {s["line"]: s["rk"] for s in ss}
chk([RK.get(line_of(t)) for t in ("c.e_meth = 1", "core.Core.E_CONST = 2", "n.r_state = 1", "o.p_meth()", "sp.e_meth()", "m.r_meth = 1")]
    == ["inst", "cls", "bare", "bare", "plan", "inst"], "자체: 받는 쪽 꼴(inst · cls · bare = __new__ · plan = settle_planner)",
    [RK.get(line_of(t)) for t in ("c.e_meth = 1", "core.Core.E_CONST = 2", "n.r_state = 1", "o.p_meth()", "sp.e_meth()", "m.r_meth = 1")])
chk(not any(g[2] == "other" for g in got) and not any(g[0] == line_of("plain.other = 1") for g in got),
    "자체: 서비스 이름 아닌 자리 = 0", [g for g in got if g[0] == line_of("plain.other = 1")])
want = {(line_of(t), c, n) for t, c, n, _ in CASES}
extra = sorted(set(got) - want)
chk(not extra, "자체: 기대 밖 자리 0", [(L.get(e[0], "")[:50],) + e for e in extra])

SYN2 = """import core
import core_svc
from core_svc import ReconService as RS

c = core.Core({})
c.svc_exf.e_meth = 1
c.svc_recon.e_meth = 2
s9 = c.svc_recon
s9.r_meth()
s9.e_state = 3
core_svc.ExfService.E_CONST = 1
core_svc.ReconService.E_CONST = 2
RS.r_meth(None)
hasattr(c.svc_exf, "r_meth")
c.svc_exf.__dict__.pop("e_state", None)
for k7 in ("r_meth", "r_state"):
    c.svc_recon.__dict__.pop(k7, None)
WRAP9 = "import sys\\nimport core\\ncore.Core.E_CONST = 5\\nprint(sys.argv)\\n"
WRAP8 = "import core_svc\\ncore_svc.ReconService.E_CONST = 5\\n"
"""
syn2 = os.path.join(T.TMP, "svc_syn2.py")
with open(syn2, "w", encoding="utf-8") as fh:
    fh.write(SYN2)
L2 = {i + 1: ln for i, ln in enumerate(SYN2.split("\n"))}
g2 = sorted((L2[x["line"]].strip(), x["cat"], x["name"]) for x in N.scan_file(syn2, SYN_OWNED, "tests/svc_syn2.py"))
chk(g2 == sorted([("c.svc_recon.e_meth = 2", "svc_mismatch", "e_meth"), ("s9.e_state = 3", "svc_mismatch", "e_state"),
                  ("core_svc.ReconService.E_CONST = 2", "svc_mismatch", "E_CONST"),
                  ('hasattr(c.svc_exf, "r_meth")', "svc_mismatch", "r_meth"),
                  ('WRAP9 = "import sys\\nimport core\\ncore.Core.E_CONST = 5\\nprint(sys.argv)\\n"', "assign", "E_CONST"),
                  ('WRAP8 = "import core_svc\\ncore_svc.ReconService.E_CONST = 5\\n"', "svc_mismatch", "E_CONST")]),
    "자체: 서비스 쪽 받는 쪽(c.svc_x · 별칭 · core_svc.X · from core_svc import) = 제 묶음 0 · 다른 묶음 = svc_mismatch · 글 안 코드도 같은 규칙", g2)
emb = [x for x in N.scan_file(syn2, SYN_OWNED, "tests/svc_syn2.py") if x.get("embedded")]
chk(len(emb) == 2 and all(x["scope"] == "<module><글>" for x in emb), "자체: 글 안 코드 자리 = 둘레 범위 뒤 '<글>' · embedded 표시", [(x["scope"], x["name"]) for x in emb])

base = N.table_from(ss, {})
b0, l0 = N.judge(ss, base, {"tests/svc_syn.py"})
chk(not b0 and not l0, "자체 판정: 같은 자리 = 통과", b0 + l0)
b1, _ = N.judge(ss + [dict(ss[0], name="e_new", line=999)], base, {"tests/svc_syn.py"})
chk(any("표 밖 새 자리" in x for x in b1), "자체 판정: 새 자리 = 실패", b1)
b2, _ = N.judge(ss + [dict(ss[0])], base, {"tests/svc_syn.py"})
chk(any("자리 늘어남" in x for x in b2), "자체 판정: 같은 열쇠 자리 늘어남 = 실패", b2)
b3, l3 = N.judge(ss[1:], base, {"tests/svc_syn.py"})
chk(not b3 and l3, "자체 판정: 줄어듦 = 문제 0 · 줄어듦 목록", {"bad": b3, "lower": l3})
_, l4 = N.judge(ss[1:], base, set())
chk(not l4, "자체 판정: 지금 배치에 없는 파일의 표 줄 = 건너뜀(공개판)", l4)
enf = dict(base, enforce={"EXF": True, "PRICING": False, "RECON": False})
b5, _ = N.judge(ss, enf, {"tests/svc_syn.py"})
chk(b5 and all("EXF" in x or "(못 정함)" in x for x in b5) and len(b5) == len({k for k in N.counts(ss) if k[3] in ("EXF", "?")}),
    "자체 판정: enforce EXF = EXF 자리(못 정함 포함)·묶음 못 정한 자리 전부 실패 · 다른 묶음 무관", b5[:5])
allow = dict(enf, allow=[{"key": list(k), "why": "합성 이유"} for k in N.counts(ss) if k[3] in ("EXF", "?")])
b6, _ = N.judge(ss, allow, {"tests/svc_syn.py"})
chk(not b6, "자체 판정: allow(이유 줄) 자리는 enforce 에서도 통과", b6[:5])
qk = [k for k in N.counts(ss) if k[3] == "?"]
b7, _ = N.judge(ss, dict(base, enforce={"EXF": False, "PRICING": True, "RECON": False}), {"tests/svc_syn.py"})
chk(qk and all(any("|".join(k) in x for x in b7) for k in qk), "자체 판정: 묶음 못 정한 자리(key?)는 어느 묶음이든 enforce 켜면 실패(allow 필요)", b7[:5])
rk_self = [s for s in ss if s.get("self_arg")]
chk([(s["name"], s["line"]) for s in rk_self] == [("r_meth", line_of("x9 = core.Core.r_meth(core.Core, 1)"))],
    "자체: 클래스 쪽 부르기에 Core 클래스를 넘기는 자리 = self_arg 표시", [(s["name"], s["line"]) for s in rk_self])

T.finish()
