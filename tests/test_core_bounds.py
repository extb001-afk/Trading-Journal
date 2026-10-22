#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import os  # noqa: E402

import _core_bounds as B  # noqa: E402

chk = T.chk
TAB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "arch_baseline", "core_bounds.json")
TOOLS = os.path.join(T.ROOT, "tools")
HAVE_TOOLS = os.path.isfile(os.path.join(TOOLS, "rebuild2.py"))

tab = B.load_table(TAB_PATH)
fx = B.facts(T.SRC, tab, TOOLS if HAVE_TOOLS else None)
bad, lower = B.judge(fx, tab, T.SRC, have_tools=HAVE_TOOLS)
chk(not bad, "core 묶음 경계: 표 밖 새것 0", bad[:20])
chk(not lower, "core 묶음 경계: 표가 지금 값과 같음(줄어들었으면 --update-lower)", lower[:20])
if not HAVE_TOOLS:
    print("SKIP tools/rebuild2.py 없음(공개판 배치) — 도구의 type(x).__module__ 대조 건너뜀")

rows = {r["group"]: r for r in B.summary(fx)}
for g in B.GROUPS_SVC:
    r = rows.get(g) or {}
    split = (tab.get("runtime") or {}).get(g, "Core") != "Core"
    chk(bool(r.get("classes")) and (bool(r.get("entries")) or split and bool(fx["ports"].get(tab["runtime"][g])))
        and bool(r.get("port_calls")),
        "묶음 %s: 클래스·입구(나뉜 묶음 = 위임 포트)·포트 이름이 있음" % g, {k: len(v) if isinstance(v, list) else v for k, v in r.items()})
sp = [x for x in fx["self_pass"] if x["callee"] == "discopen.Runner"]
chk(len(sp) == 1 and sp[0]["module"] == "discopen" and "conn" in sp[0]["names"] and ["_ver", "CLASSIFIER_VER"] in sp[0]["type_module"],
    "self 넘김 discopen.Runner 가 받는 모듈 흐름(이름·type(x).__module__)으로 풀림", sp)
chk(fx["bypass"] == [] and ["core_prov.py", "ProvMixin._prov_targets", "getattr", "chain_owners"] in fx["getattr_core"]
    and "_recon_view_drop" in fx["edges"].get("RECON>CORE", []),
    "포트 우회 0(9-2 고침 — 5자리 → 포트 이름 getattr 3 · 포트 메서드 _recon_view_drop 2 · 우회 잡기는 [3] 자체 시험)", fx["bypass"])

BASE = {
    "core.py": (
        "import disc\n"
        "from core_a import AMixin\n"
        "from core_b import BMixin\n"
        "CLASSIFIER_VER = 5\n\n\n"
        "class Core(AMixin, BMixin):\n"
        "    def __init__(self):\n"
        "        self.conn = 1\n"
        "        self.cache = {}\n"
        "        self.side = 0\n\n"
        "    def run(self):\n"
        "        self.side = 1\n"
        "        self.a_go()\n"
        "        return self.b_go()\n\n"
        "    def _meta(self):\n"
        "        return self.conn\n"),
    "core_a.py": (
        "class AMixin:\n"
        "    TOL = 1\n\n"
        "    def a_go(self):\n"
        "        return self._meta() + self.conn\n"),
    "core_b.py": (
        "import disc\n\n\n"
        "class BMixin:\n"
        "    def b_go(self):\n"
        "        self.__dict__.pop(\"cache\", None)\n"
        "        return disc.Runner(self)\n"),
    "disc.py": (
        "import sys\n\n\n"
        "def _ver(core):\n"
        "    return getattr(sys.modules.get(type(core).__module__), \"CLASSIFIER_VER\", 3)\n\n\n"
        "class Runner:\n"
        "    def __init__(self, core):\n"
        "        self.core = core\n\n"
        "    def go(self):\n"
        "        c = self.core\n"
        "        return c.conn, _ver(c)\n"),
}
SYN_TAB = {"classes": {"Core": "CORE", "AMixin": "EXF", "BMixin": "RECON"},
           "runtime": {"CORE": "Core", "EXF": "Core", "RECON": "Core"}}
_n = [0]


def syn(edits=None, extra=None):
    _n[0] += 1
    d = os.path.join(T.TMP, "cb_syn_%d" % _n[0], "src")
    os.makedirs(d)
    files = dict(BASE)
    for f, (a, b) in (edits or {}).items():
        assert a in files[f], (f, a)
        files[f] = files[f].replace(a, b, 1)
    files.update(extra or {})
    for f, t in files.items():
        with open(os.path.join(d, f), "w", encoding="utf-8") as fh:
            fh.write(t)
    return d


d0 = syn()
fx0 = B.facts(d0, SYN_TAB)
tab0 = B.table_from(fx0, SYN_TAB)
b0, l0 = B.judge(fx0, tab0, d0)
chk(not b0 and not l0, "자체: 그대로 = 통과", b0 + l0)
chk(fx0["edges"].get("EXF>CORE") == ["_meta"] and fx0["bypass"] == [["core_b.py", "BMixin.b_go", "cache"]]
    and fx0["self_pass"][0]["names"] == ["conn"] and fx0["self_pass"][0]["type_module"] == [["_ver", "CLASSIFIER_VER"]],
    "자체: 합성 사실(경계 _meta · 우회 cache · 받는 쪽 이름 conn · type(x).__module__)", {k: fx0[k] for k in ("edges", "bypass", "self_pass")})


def fails(label, edits=None, extra=None, tab=None, want=None):
    d = syn(edits, extra)
    t = tab or tab0
    fx1 = B.facts(d, t)
    b1, _ = B.judge(fx1, t, d)
    chk(bool(b1) and (want is None or any(want in x for x in b1)), "자체: %s = 실패" % label, b1)


fails("(a) 새 경계 이름", {"core_a.py": ("return self._meta()", "self.b_go()\n        return self._meta()")}, want="새 경계 이름 EXF>RECON")
fails("(b) __dict__ 공유 열쇠", {"core_a.py": ("return self._meta()", "self.__dict__.get(\"cache\")\n        return self._meta()")},
      want="공유 상태 cache")
fails("(b2) 서비스의 __dict__ 우회 자리 늘어남", {"core_b.py": ("return disc", "self.__dict__.get(\"side\")\n        return disc")},
      want="포트 우회")
fails("(c) getattr 공유 글자", {"core_a.py": ("return self._meta()", "getattr(self, \"side\", 0)\n        return self._meta()")},
      want="새 공유 상태 side")
fails("(c2) getattr CORE 글자 자리", {"core_a.py": ("return self._meta()", "getattr(self, \"conn\", 0)\n        return self._meta()")},
      want="getattr CORE 글자")
fails("표에 없는 core 클래스", extra={"core_z.py": "class ZMixin:\n    def z(self):\n        return 1\n"}, want="묶음 표에 없는 core 클래스 ZMixin")
fails("받는 쪽(self 넘김)이 새 이름을 씀", {"disc.py": ("return c.conn,", "return c.conn, c.side,")}, want="표 밖 names")
fails("받는 쪽이 쓰는 이름이 실제 클래스에 없음", {"disc.py": ("return c.conn,", "return c.conn, c.nope,")},
      tab=dict(tab0, self_pass=[dict(tab0["self_pass"][0], names=["conn", "nope"])]), want="포트 빠짐")
fails("type(x).__module__ 이 찾는 모듈 속성 빠짐", {"core.py": ("CLASSIFIER_VER = 5\n", "")}, want="CLASSIFIER_VER")
fails("실제 클래스 바탕에서 믹스인 빠짐", {"core.py": ("class Core(AMixin, BMixin):", "class Core(AMixin):")}, want="바탕에 없음")
fails("새 self 넘김 자리", {"core_a.py": ("return self._meta()", "print(self)\n        return self._meta()")}, want="새 self 넘김")
for lab, code in (("받는 쪽 별칭", "s9 = self"), ("getattr(self, 변수)", "getattr(self, k)"), ("vars(self)", "vars(self)"),
                  ("type(self)", "type(self)"), ("self.__class__", "self.__class__"), ("__dict__ 통째", "d9 = self.__dict__")):
    fails("분석 밖 꼴 %s" % lab, {"core_a.py": ("return self._meta()", "k = 'x'\n        %s\n        return self._meta()" % code)},
          want="받는 쪽 분석 밖 꼴")
fails("core*.py 모듈 함수가 인자에서 서비스 이름을 씀", {"core_b.py": ("import disc\n", "import disc\n\n\ndef helper(c):\n    return c.b_go()\n")},
      want="모듈 함수의 서비스 이름")
fails("다른 모듈 믹스인이 바탕", {"core.py": ("class Core(AMixin, BMixin):", "class Core(AMixin, BMixin, disc.Runner):")},
      want="못 찾음")
SVC_SRC = ("from core_a import AMixin\n\n\nclass SvcA(AMixin):\n    def __init__(self, core):\n        self.core = core\n\n"
           "    def _meta(self):\n        return self.core._meta()\n\n"
           "    @property\n    def conn(self):\n        return self.core.conn\n")
TAB_S = dict(tab0, classes=dict(SYN_TAB["classes"], SvcA="EXF"), services=["SvcA"], ports={"SvcA": ["_meta", "conn"]},
             runtime=dict(SYN_TAB["runtime"], EXF="SvcA"))
d3 = syn(extra={"core_svc.py": SVC_SRC})
fx3 = B.facts(d3, TAB_S)
b3, l3 = B.judge(fx3, TAB_S, d3)
chk(fx3["ports"] == {"SvcA": ["_meta", "conn"]} and "conn" not in fx3["owner"] and fx3["owner"].get("_meta") == "Core"
    and "conn" in fx3["state"], "자체: 서비스의 상태 읽기 속성(conn)·같은 이름 메서드 = 포트(주인 = 원래 쪽 · 상태는 그대로 공유 상태)",
    {"ports": fx3["ports"], "owner_conn": fx3["owner"].get("conn"), "state": fx3["state"]})
chk(not b3 and not l3, "자체: 서비스 클래스의 위임 포트(표 ports 에 적음) = 겹침 아님 · 통과", b3 + l3)
d4 = syn(extra={"core_svc.py": SVC_SRC + "\n    def run(self):\n        return 1\n"})
b4, _ = B.judge(B.facts(d4, TAB_S), TAB_S, d4)
chk(any("SvcA 의 표에 없는 포트 이름 run" in x for x in b4), "자체: 표에 없는 포트 이름 = 실패", b4)
d6 = syn(extra={"core_svc.py": SVC_SRC.replace("    @property\n    def conn(self):\n        return self.core.conn\n", "")})
b6, _ = B.judge(B.facts(d6, TAB_S), TAB_S, d6)
chk(any("이름 conn 가 실제 클래스 SvcA 에 없음" in x for x in b6), "자체: 서비스 몸통이 찾는 CORE 상태(conn)의 포트 빠짐 = 실패", b6)
d7 = syn(extra={"core_svc.py": SVC_SRC.replace("    @property\n    def conn(self):\n        return self.core.conn\n", "").replace(
    "        self.core = core\n", "        self.core = core\n        self.conn = core.conn\n")})
b7, _ = B.judge(B.facts(d7, TAB_S), TAB_S, d7)
chk(any("자기 객체에 씀(Core 와 갈라짐)" in x for x in b7), "자체: 서비스가 CORE 공유 상태를 자기 객체에 씀 = 갈라짐 실패", b7)
d13 = syn(extra={"core_svc.py": SVC_SRC.replace("return self.core.conn", "return getattr(self.core, \"nope9\", 0)")})
b13, _ = B.judge(B.facts(d13, TAB_S), TAB_S, d13)
chk(any("self.core 의 이름 nope9" in x for x in b13), "자체: 포트가 self.core 로 찾는 이름이 실제 Core 에 없음 = 실패", b13)
TAB_D = dict(TAB_S, duty={"EXF": ["lazy9"]})
b9, _ = B.judge(B.facts(d3, TAB_D), TAB_D, d3)
chk(any("의무 이름 lazy9" in x for x in b9), "자체: 의무(duty) 이름을 실제 클래스가 정의·대입 안 함 = 실패", b9)
d10 = syn(extra={"core_svc.py": SVC_SRC.replace("        self.core = core\n", "        self.core = core\n        self.lazy9 = 0\n")})
b10, l10 = B.judge(B.facts(d10, TAB_D), TAB_D, d10)
chk(not b10, "자체: 의무 이름을 서비스 __init__ 이 대입 = 통과", b10)
d11 = syn({"core_a.py": ("return self._meta()", "self.__dict__.get(\"side\")\n        return self._meta()")}, extra={"core_svc.py": SVC_SRC})
fx11 = B.facts(d11, TAB_S)
b11, _ = B.judge(fx11, dict(TAB_S, bypass=fx11["bypass"], state=fx11["state"]), d11)
chk(any("포트 우회" in x and "남음" in x for x in b11), "자체: 서비스로 나뉜 묶음에 표에 있는 포트 우회가 남음 = 실패", b11)
SVC_B = ("from core_b import BMixin\n\n\nclass SvcB(BMixin):\n    def __init__(self, core):\n        self.core = core\n\n"
         "    @property\n    def cache(self):\n        return self.core.cache\n")
TAB_2 = dict(TAB_S, classes=dict(TAB_S["classes"], SvcB="RECON"), services=["SvcA", "SvcB"], ports={"SvcA": ["_meta", "conn"], "SvcB": ["cache"]})
d12 = syn(extra={"core_svc.py": SVC_SRC, "core_svc_b.py": SVC_B})
fx12 = B.facts(d12, TAB_2)
chk("core" not in fx12["state_all"] and not [x for x in B.judge(fx12, TAB_2, d12)[0] if "core " in x or " core" in x],
    "자체: 서비스 둘이 각자 self.core 를 쥠 = 상태 아님(갈라짐·포트 오판 0)", {"state": sorted(fx12["state_all"]), "bad": B.judge(fx12, TAB_2, d12)[0]})
d8 = syn({"core_b.py": ("return disc.Runner(self)", "self.core.__dict__.get(\"cache\")\n        return disc.Runner(self)")})
fx8 = B.facts(d8, tab0)
chk(fx8["bypass"] == fx0["bypass"], "자체: self.core.__dict__ 글자 = core 객체 사전(우회 아님 · 우회 표 그대로)", fx8["bypass"])
b5, _ = B.judge(B.facts(d3, dict(TAB_S, services=[])), dict(TAB_S, services=[]), d3)
chk(any("이름 겹침 _meta" in x for x in b5), "자체: 서비스로 적지 않은 클래스의 같은 이름 = 겹침 실패", b5)
d2 = syn({"core_a.py": ("return self._meta() + self.conn", "return 0")})
b2, l2 = B.judge(B.facts(d2, tab0), tab0, d2)
chk(not b2 and any("줄어듦" in x for x in l2), "자체: 경계가 줄어듦 = 문제 0 · 줄어듦 목록에 남음(--update-lower 대상)", {"bad": b2, "lower": l2})

T.finish()
