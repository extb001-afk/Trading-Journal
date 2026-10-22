#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import os  # noqa: E402

chk = T.chk
TOOL = os.path.join(T.ROOT, "tools", "refactor", "core_svc_codemod.py")
if not os.path.isfile(TOOL):
    print("SKIP tools/refactor/core_svc_codemod.py 없음(공개판 — 리팩터 도구는 운영 저장소에만)")
    T.finish()
sys.path.insert(0, os.path.dirname(TOOL))
import core_svc_codemod as C  # noqa: E402
import _svc_names as N  # noqa: E402

r = C.run(T.ROOT, list(C.SVC))
files, hand, owned = r["files"], r["hand"], r["owned"]
bad = {k: f["proof"] for k, f in files.items() if f["proof"]}
chk(not bad, "드라이런: 바뀐 파일 %d 전부 증명 통과" % len(files), dict(list(bad.items())[:3]))
per = {}
for f in files.values():
    for g, _rk, _ss in f["edits"].values():
        per[g] = per.get(g, 0) + 1
chk(not per and not files, "드라이런: 9-1~9-3 뒤 EXF·RECON·PRICING 바꿀 자리 0(--write 끝)", per)
covered = {}
for k, f in files.items():
    for _g, _rk, ss in f["edits"].values():
        for s in ss:
            covered[(k, s["line"], s["name"], s["cat"])] = 1
for h in hand:
    covered[(h["file"], h["line"], h["name"], h["cat"])] = 1
sites = [s for s in N.scan_tree(T.ROOT, owned)]
rq = [h for h in hand if h["cat"] == "read?"]
chk(rq and all(h["why"] for h in rq), "드라이런: core 를 import 하는 파일의 받는 쪽 못 정한 읽기 = 손 이전 목록(read? %d)" % len(rq), rq[:3])
lost = [(s["file"], s["line"], s["cat"], s["name"]) for s in sites if (s["file"], s["line"], s["name"], s["cat"]) not in covered]
chk(not lost, "드라이런: 서비스 자리 %d 전부 '바꿀 자리'·'손 이전' 중 하나(조용히 빠짐 0)" % len(sites), lost[:10])
chk(all(h.get("why") for h in hand), "드라이런: 손 이전 자리마다 이유(%d)" % len(hand), [h for h in hand if not h.get("why")][:3])
chk(len([h for h in hand if h["why"].startswith("글 안 코드")]) == 0, "드라이런: 자식 프로세스 래퍼 글 안 자리 0(9-1 이 EXF 3 을 손으로 옮김)",
    [h for h in hand if h["why"].startswith("글 안 코드")])
from collections import Counter  # noqa: E402
hc = Counter((h["file"], h["name"], h["cat"]) for h in hand)
rest = Counter()
for k, f in files.items():
    if k.startswith("src/core"):
        continue
    for x in N.scan_tree_ast(ast.parse(f["new"]), owned, k):
        rest[(k, x["name"], x["cat"])] += 1
over = {k: v for k, v in rest.items() if v > hc.get(k, 0)}
chk(not over, "드라이런: 바꾼 글을 svc_names 로 다시 보면 남은 자리 ⊆ 손 이전 목록(바꾼 자리·다른 서비스 0)", dict(list(over.items())[:8]))
chk(not C.write_allowed(T.ROOT, ["EXF"]) or os.path.isfile(os.path.join(T.SRC, "core_svc.py")),
    "제자리 쓰기 = core_svc.py 가 있을 때만(9-0 = 거부)")
print("INFO 드라이런 바꿀 자리 %s · 손 이전 %d · import core_svc %d" % (per, len(hand), sum(f["nimp"] for f in files.values())))

OWN = {"e_meth": "EXF", "E_CONST": "EXF", "e_state": "EXF", "settle_planner": "EXF", "r_meth": "RECON", "r_state": "RECON", "p_meth": "PRICING"}
SYN = '''import core  # noqa: E402
from x import patch_cls_attr

c = core.Core({})
c.e_meth = 1
v = c.r_meth()  # 주석 그대로
core.Core.E_CONST = 2
hasattr(core.Core, "e_meth")
c.__dict__.pop("e_state", None)
patch_cls_attr(core.Core, "r_meth", 1)
del c.e_meth
w = core.Core({}).p_meth()
for k9 in ("r_meth", "r_state"):
    c.__dict__.pop(k9, None)
for k8 in ("r_meth", "e_state"):
    c.__dict__.pop(k8, None)
sp = core.Core.settle_planner({}, None)
sp.e_meth()
x9 = core.Core.r_meth(core.Core, 1)
x8 = core.Core.r_meth(c)


def unknown(z):
    z.p_meth = 1


def f():
    import core as cm
    return cm.Core.E_CONST
'''
WANT = '''import core  # noqa: E402
import core_svc  # noqa: E402
from x import patch_cls_attr

c = core.Core({})
c.svc_exf.e_meth = 1
v = c.svc_recon.r_meth()  # 주석 그대로
core_svc.ExfService.E_CONST = 2
hasattr(core_svc.ExfService, "e_meth")
c.svc_exf.__dict__.pop("e_state", None)
patch_cls_attr(core_svc.ReconService, "r_meth", 1)
del c.svc_exf.e_meth
w = core.Core({}).svc_price.p_meth()
for k9 in ("r_meth", "r_state"):
    c.svc_recon.__dict__.pop(k9, None)
for k8 in ("r_meth", "e_state"):
    c.__dict__.pop(k8, None)
sp = core.Core.settle_planner({}, None)
sp.e_meth()
x9 = core.Core.r_meth(core.Core, 1)
x8 = core.Core.r_meth(c)


def unknown(z):
    z.p_meth = 1


def f():
    import core as cm
    import core_svc
    return core_svc.ExfService.E_CONST
'''


def plan(text, groups=("EXF", "RECON", "PRICING")):
    t = ast.parse(text)
    edits, h = C.plan_sites(N.scan_tree_ast(t, OWN, "tests/syn.py", reads_unresolved=True), list(groups))
    new, nimp = C.apply_edits(text, t, edits)
    return edits, h, new, nimp


edits, h, new, nimp = plan(SYN)
chk(new == WANT, "합성: 도구 결과 = 기대 글", [ln for ln in zip(new.split("\n"), WANT.split("\n")) if ln[0] != ln[1]][:6])
pr = C.prove(SYN, new, OWN, edits, nimp)
chk(not pr, "합성: 증명 통과", pr)
hw = sorted((x["name"], x["why"][:12]) for x in h)
chk(len([x for x in h if x["name"] == "settle_planner" or x["scope"] == "<module>" and x["name"] == "e_meth" and "settle" in x["why"]]) == 2
    and any(x["name"] == "p_meth" and x["cat"] == "assign?" for x in h)
    and len([x for x in h if "두 묶음" in x["why"]]) == 2 and len([x for x in h if "명시적 self" in x["why"] or "self 로 넘김" in x["why"]]) == 2,
    "합성: 손 이전 = 계획기 2 · 받는 쪽 못 정함 1 · 두 묶음 변수 열쇠 2 · 명시적 self(Core 클래스·인스턴스를 넘김) 2", hw)
_e, hq, _n, _k = plan("import core\n\n\ndef g(q):\n    return q.r_meth()\n")
_e2, hq2, _n2, _k2 = plan("def g(q):\n    return q.r_meth()\n")
chk([x["cat"] for x in hq] == ["read?"] and not hq2, "합성: core 를 import 하는 파일의 못 정한 읽기 = read? 손 이전 · core 없는 파일 = 0", [hq, hq2])
left = N.scan_tree_ast(ast.parse(new), OWN, "tests/syn.py")
hand_keys = sorted((x["name"], x["cat"]) for x in h)
chk(sorted((x["name"], x["cat"]) for x in left) == hand_keys and not [x for x in left if x["cat"] == "svc_mismatch"],
    "합성: 바꾼 글을 svc_names 로 다시 보면 남은 자리 = 손 이전 목록뿐(바꾼 자리 0 · 다른 서비스 0)",
    {"남음": sorted((x["name"], x["cat"], x["line"]) for x in left), "손": hand_keys})
e1, h1, new1, n1 = plan(SYN, ("EXF",))
chk("c.svc_exf.e_meth = 1" in new1 and "v = c.r_meth()" in new1 and not C.prove(SYN, new1, OWN, e1, n1),
    "합성: 묶음 하나만(--group EXF) = 그 묶음 자리만 바꾸고 증명 통과", new1.split("\n")[:8])


def broken(label, a, b, count=1):
    assert new.count(a) >= 1, a
    bad_text = new.replace(a, b, count)
    chk(bool(C.prove(SYN, bad_text, OWN, edits, nimp)), "증명: %s = 실패" % label)


broken("묶음 틀림(svc_recon.e_meth)", "c.svc_exf.e_meth = 1", "c.svc_recon.e_meth = 1")
broken("계획 밖 마디 더함", "sp.e_meth()", "sp.svc_exf.e_meth()")
broken("계획한 마디 빠짐", "c.svc_exf.e_meth = 1", "c.e_meth = 1")
broken("다른 글자 바뀜", "E_CONST = 2", "E_CONST = 3")
broken("클래스 서비스 틀림", "core_svc.ExfService.E_CONST = 2", "core_svc.ReconService.E_CONST = 2")
broken("import core_svc 빠짐", "import core_svc  # noqa: E402\n", "")
broken("import core_svc 더함", "from x import patch_cls_attr\n", "from x import patch_cls_attr\nimport core_svc\n")
broken("글자 열쇠 묶음 틀림", 'c.svc_exf.__dict__.pop("e_state", None)', 'c.svc_recon.__dict__.pop("e_state", None)')
broken("글자 인자 묶음 틀림", 'hasattr(core_svc.ExfService, "e_meth")', 'hasattr(core_svc.PriceService, "e_meth")')

CORE_SRC = '''class Core:
    def __init__(self):
        self.e_state = 0
        self.conn = None

    def run(self):
        self.__dict__.pop("e_state", None)
        self.e_meth()
        if hasattr(self, "r_meth"):
            return self.r_meth()
        return self.conn
'''
t = ast.parse(CORE_SRC)
ce, ch = C.core_body_plan(t, "src/core.py", OWN, list(C.SVC), {"Core": "CORE"})
cnew, cn = C.apply_edits(CORE_SRC, t, ce)
chk("        self.svc_exf.e_meth()" in cnew and 'hasattr(self.svc_recon, "r_meth")' in cnew and "return self.svc_recon.r_meth()" in cnew
    and "self.e_state = 0" in cnew and not C.prove(CORE_SRC, cnew, OWN, ce, cn),
    "Core 몸통: self.N → self.<svc>.N(부르기·감지) · 증명 통과", cnew.split("\n"))
chk(sorted((x["name"], x["scope"], x["why"].split("(")[0]) for x in ch)
    == [("e_state", "Core.__init__", "Core.__init__ 서비스 소유 상태 줄"), ("e_state", "Core.run", "Core 몸통 self.__dict__ 글자")],
    "Core 몸통: __init__ 서비스 소유 상태 줄 · self.__dict__ 서비스 글자 = 손 이전", ch)
d9 = os.path.join(T.TMP, "cm_tree")
os.makedirs(os.path.join(d9, "src"))
chk(not C.write_allowed(d9, ["EXF"]), "제자리 쓰기: core_svc.py 없음 = 거부")
with open(os.path.join(d9, "src", "core_svc.py"), "w", encoding="utf-8") as fh:
    fh.write("\n")
chk(C.write_allowed(d9, ["EXF"]) and not C.write_allowed(d9, ["EXF", "RECON"]), "제자리 쓰기: core_svc.py 있음 + 묶음 하나만 = 허용")

T.finish()
