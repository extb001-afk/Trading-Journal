#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402

import _arch_closure as C  # noqa: E402
import _arch_py_facts as F  # noqa: E402
import _arch_py_metrics as M  # noqa: E402
import _arch_py_ratchet as R  # noqa: E402
import _arch_split as S  # noqa: E402

chk = T.chk
LAYERS = ["기반", "수집기", "시세", "core", "화면·계산", "웹·설정"]
MODS = {"common": "기반", "nodekeys": "기반", "bf_engine": "기반", "pricing": "시세", "web": "웹·설정", "helper": "기반",
        "paths": "기반", "envfile": "기반", "config": "기반", "stables": "기반"}

PRE = {
    "common": ("STATE_DIR = 's'\nENV_PATH = 'e'\nCONFIG_PATH = 'c'\nCAS = {'eth': 1}\n\n\n"
               "def read_env():\n    return open(ENV_PATH).read()\n\n\n"
               "def load_config():\n    import nodekeys\n    return CONFIG_PATH\n\n\n"
               "def stable_of(x):\n    import pricing\n    return pricing.lookup(x, CAS)\n\n\n"
               "def gate():\n    return STATE_DIR\n"),
    "nodekeys": "import bf_engine\n",
    "bf_engine": "import common\n\n\ndef boot():\n    return common.load_config()\n",
    "pricing": "def lookup(x, t):\n    return t.get(x)\n",
    "web": "import common\n\n\ndef page():\n    return common.STATE_DIR\n\n\ndef view(paths):\n    return common.STATE_DIR\n",
    "helper": "",
}
MID = {
    "common": "import config, envfile, paths, stables\n\n\ndef gate():\n    return paths.STATE_DIR\n",
    "paths": "STATE_DIR = 's'\nENV_PATH = 'e'\nCONFIG_PATH = 'c'\n",
    "envfile": "import paths\n\n\ndef read_env():\n    return open(paths.ENV_PATH).read()\n",
    "config": "import paths\n\n\ndef load_config():\n    import nodekeys\n    return paths.CONFIG_PATH\n",
    "stables": "CAS = {'eth': 1}\n\n\ndef stable_of(x):\n    import pricing\n    return pricing.lookup(x, CAS)\n",
    "nodekeys": "import bf_engine\n",
    "bf_engine": "import common\n\n\ndef boot():\n    return common.load_config()\n",
    "pricing": "def lookup(x, t):\n    return t.get(x)\n",
    "web": "import paths\n\n\ndef page():\n    return paths.STATE_DIR\n\n\ndef view(paths):\n    return paths.STATE_DIR\n",
    "helper": "",
}
SPLIT_OF = {"paths": "common", "envfile": "common", "config": "common", "stables": "common"}
PROOF = {"origins": {"common": {"base": "0" * 40, "moved": {
    "paths": ["CONFIG_PATH", "ENV_PATH", "STATE_DIR"], "envfile": ["read_env"], "config": ["load_config"], "stables": ["CAS", "stable_of"]},
    "edges": [{"m": "config", "to": "nodekeys", "why": "import", "q": "load_config"},
              {"m": "config", "to": "paths", "why": "subst", "q": "load_config"},
              {"m": "envfile", "to": "paths", "why": "subst", "q": "read_env"},
              {"m": "stables", "to": "pricing", "why": "import", "q": "stable_of"},
              {"m": "common", "to": "paths", "why": "subst", "q": "gate"},
              {"m": "helper", "to": "nodekeys", "why": "import", "q": "<module>"}]}}}


def layers(split_of=None):
    return {"layers": LAYERS, "modules": dict(MODS), "split_of": dict(split_of or {})}


def build(srcs, split_of=None, proof=None):
    index = {m: F.facts(t, m) for m, t in srcs.items()}
    lay = layers(split_of)
    mx = M.compute(index, {}, lay, "")
    if not split_of:
        return mx, None
    sp = S.Split(split_of, PROOF if proof is None else proof, index, {}, lay, lambda rel: srcs[rel[4:-3]])
    sp.normalize_h(mx)
    return mx, sp


PRE_MX, _ = build(PRE)
BASE = {k: [R.identity(u) for u in PRE_MX.units.get(k, []) if R.violating(k, u["v"], {})] for k in S.SPLIT_KEYS}


def judge(srcs, split_of=SPLIT_OF, proof=None):
    mx, sp = build(srcs, split_of, proof)
    new = []
    for k in S.SPLIT_KEYS:
        vd = R.compare(k, S.fold_units(sp, k, mx.units.get(k, []), BASE[k]), BASE[k], {}, ())
        new += [(k, u["m"], u["q"]) for u in vd.new] + [(k, u["m"], u["q"]) for u, _b in vd.grew]
    return sorted(new), (sp.hard() if sp else {}), mx.cycles, sp


def edit(**kw):
    out = dict(MID)
    out.update(kw)
    return out


base_e = {(b["m"], b["q"]) for b in BASE["import.cycle_edges"]}
chk(base_e == {("common", "nodekeys"), ("nodekeys", "bf_engine"), ("bf_engine", "common")}
    and {(b["m"], b["q"]) for b in BASE["layer.violations"]} == {("common", "pricing")},
    "[0] 분할 전 기준선 = 순환 간선 3(common→nodekeys→bf_engine→common) · 계층 위반 common→pricing", sorted(base_e))

new, hard, cyc, sp = judge(MID)
chk(not new and not hard, "[1] 증명된 분할 = 새 위반 0 · 굳은 검사 0(① · ④' 다리 간선 common→config 와 바깥 순환 통과)", (new, hard))
chk(any({"common", "config", "nodekeys", "bf_engine"} <= set(c) for c in cyc),
    "[1] 판정은 실제 그래프 — 순환 common→config→nodekeys→bf_engine→common 은 SCC 에 그대로 남음(숨기지 않음)", cyc)
chk(("common", "config") in sp.allow and ("envfile", "paths") in sp.allow and ("config", "paths") in sp.allow
    and ("paths", "envfile") not in sp.allow and ("config", "common") not in sp.allow,
    "[1] 허용 표 = 대리 이름 표(common→옮긴 이름 있는 모듈) ∪ subst 근거 · 거꾸로(A→common · paths→envfile)는 없음", sorted(sp.allow))
CODEMOD_BF = "import config\n\n\ndef boot():\n    return config.load_config()\n"
new2, hard2, cyc2, sp2 = judge(edit(bf_engine=CODEMOD_BF))
notes = " | ".join(sp.notes + sp2.notes)
chk(not new2 and not hard2 and "bf_engine → config = 기준선 bf_engine → common 승계" in notes
    and "config → nodekeys = 기준선 common → nodekeys 승계" in notes and "stables → pricing = 기준선 common → pricing 승계" in notes,
    "[1] 들어옴(치환 꼴 bf_engine→config) · 나감(옮긴 import config→nodekeys) · 계층 위반 나감(stables→pricing)이 옛 common 단위에 짝지어짐",
    (new2, hard2, sp.notes + sp2.notes))

new, hard, _c, _s = judge(edit(paths=MID["paths"] + "\n\ndef ui():\n    import web\n    return web\n"))
chk(("layer.violations", "paths", "web") in new, "[2] 분할 모듈(paths)이 새 위층 모듈(web) import → 새 계층 위반(②)", new)
new, hard, _c, _s = judge(edit(paths=MID["paths"] + "\n\ndef px():\n    import pricing\n    return pricing\n"))
chk(("layer.violations", "paths", "pricing") in new,
    "[2] 근거 없는 paths→pricing 은 기준선 common→pricing(같은 '기반→pricing')을 가져가지 못함 — 증명된 stables→pricing 만 승계", new)

new, hard, _c, sp3 = judge(edit(helper="import nodekeys\n", common=MID["common"] + "import helper\n"))
chk(("import.cycle_edges", "helper", "nodekeys") in new and any("helper → nodekeys" in x for x in sp3.stale),
    "[3] 표 밖 모듈(helper)은 승계 안 함 — 근거 파일에 적혀 있어도 분할 계열 밖 출발 근거는 낡은 근거(③)", (new, sp3.stale))
new, hard, _c, _s = judge(edit(config=MID["config"] + "\n\ndef fresh():\n    return 1\n",
                               bf_engine="import config\n\n\ndef boot():\n    return config.load_config(), config.fresh()\n"))
chk(("import.cycle_edges", "bf_engine", "config") in new,
    "[3] 들어옴 간선이 옮기지 않은 이름(config.fresh)을 쓰면 옛 bf_engine→common 을 승계하지 않음", new)

new, hard, _c, _s = judge(edit(config=MID["config"] + "\n\ndef fresh():\n    return 1\n",
                               bf_engine=("import config as m\nfrom config import load_config\n\n\nclass Holder:\n    import paths as m\n\n\n"
                                          "def boot():\n    return load_config(), m.fresh()\n")))
chk(("import.cycle_edges", "bf_engine", "config") in new,
    "[3] 별칭 m 이 범위마다 다른 모듈(모듈 = config · 클래스 몸통 = paths)이어도 범위대로 풂 — m.fresh 는 config 의 안 옮긴 이름 → 승계 안 함", new)
new, hard, _c, _s = judge(edit(bf_engine="import config\n\n\ndef boot(config):\n    return config.load_config()\n"))
chk(("import.cycle_edges", "bf_engine", "config") in new,
    "[3] 매개변수 config 의 속성(config.load_config)은 모듈 사용이 아님 → 치환 꼴 증명 없음 → 승계 안 함", new)
new, hard, _c, _s = judge(edit(envfile="import paths\n\n\ndef read_env():\n    return open('x').read()\n\n\n"
                                       "def fresh():\n    return paths.STATE_DIR\n"))
chk(any("envfile → paths" in x for x in hard.get("split.internal", [])),
    "[3] subst 근거는 그 범위(read_env)에서만 — 다른 함수가 paths 를 읽어도 근거 아님 → 내부 간선 증명 없음", hard)

new, hard, _c, _s = judge(edit(config=MID["config"] + "\n\ndef fresh():\n    return 1\n",
                               bf_engine="import config\n\n\ndef boot():\n    return config.load_config(), [0 for config in config.fresh()]\n"))
chk(("import.cycle_edges", "bf_engine", "config") in new,
    "[3] 컴프리헨션 첫 iter(config.fresh)는 바깥 범위 = 모듈 config 사용 → 안 옮긴 이름 → 승계 안 함", new)
new, hard, _c, _s = judge(edit(config=MID["config"] + "\n\ndef fresh():\n    return 1\n",
                               bf_engine=("import config\n\n\ndef boot():\n    return config.load_config()\n\n\n"
                                          "class Holder:\n    value = config.fresh()\n    config = None\n")))
chk(("import.cycle_edges", "bf_engine", "config") in new,
    "[3] 클래스 몸통에서 묶이기 전 조회(config.fresh)는 바깥 모듈 사용 → 안 옮긴 이름 → 승계 안 함", new)
TOPS = {"from 최상위 import": "from pricing import lookup\nCAS = {'eth': 1}\n\n\ndef stable_of(x):\n    return lookup(x, CAS)\n",
        "기본값의 최상위 import": "import pricing\nCAS = {'eth': 1}\n\n\ndef stable_of(x, look=pricing.lookup):\n    return look(x, CAS)\n"}
pro_top = {"origins": {"common": dict(PROOF["origins"]["common"], edges=[
    e for e in PROOF["origins"]["common"]["edges"] if e["m"] != "stables"] + [{"m": "stables", "to": "pricing", "why": "top", "q": "stable_of"}])}}
for name, text in TOPS.items():
    new, hard, _c, _s = judge(edit(stables=text), proof=pro_top)
    chk(not new and not hard, "[1] top 근거 = %s(그 정의 문장 안 — 데코레이터·기본값처럼 바깥 범위 평가 포함)도 지금 쓰이면 유효 → 승계" % name, new)

new, hard, _c, _s = judge(edit(paths=MID["paths"] + "import envfile\n"))
chk(any("paths → envfile" in x for x in hard.get("split.internal", [])) and any("envfile" in x and "paths" in x for x in hard.get("split.cycle", [])),
    "[4] paths→envfile 추가 = 허용 표 밖 내부 간선 + 분할 모듈끼리 순환 → 실패(④)", hard)
pro2 = {"origins": {"common": dict(PROOF["origins"]["common"], moved={k: v for k, v in PROOF["origins"]["common"]["moved"].items()
                                                                     if k != "stables"})}}
new, hard, _c, _s = judge(edit(stables="CAS = 1\n"), proof=pro2)
chk(any("common → stables" in x for x in hard.get("split.internal", [])),
    "[4] 증명 없는 common→A(옮긴 이름이 없는 분할 모듈 import) → 실패(④')", hard)
new, hard, _c, _s = judge(edit(config=MID["config"] + "import common\n"))
chk(any("config → common" in x for x in hard.get("split.internal", [])) and hard.get("split.cycle"),
    "[4] A→common(분할 모듈이 대리를 부름) → 허용 밖 + 계열 안에서만 닫히는 순환 → 실패(④')", hard)

MODS.update(store="기반", wallets="웹·설정")
ST = {"store": "LOCK = 1\n\n\ndef read_cfg():\n    return LOCK\n",
      "wallets": "import store\n\n\ndef add_w(a):\n    return store.read_cfg(), store.LOCK, a\n"}
SO_B = dict(SPLIT_OF, wallets="store")


def pro_b(edges):
    return {"origins": dict(PROOF["origins"], store={"base": "0" * 40, "moved": {"wallets": ["add_w"]}, "edges": edges})}


BACK = [{"m": "wallets", "to": "store", "why": "back", "q": "add_w"}]
new, hard, _c, spb = judge(edit(**ST), split_of=SO_B, proof=pro_b(BACK))
chk(not new and not hard and ("wallets", "store") in spb.allow,
    "[4b] 위층 분할 모듈이 원래 모듈의 남은 이름을 읽음 + back 근거 = 허용(split.internal 0)", (new, hard, sorted(spb.allow)))
new, hard, _c, _s = judge(edit(**ST), split_of=SO_B, proof=pro_b([]))
chk(any("wallets → store" in x and "원래 모듈을 부르는 꼴" in x for x in hard.get("split.internal", [])),
    "[4b] back 근거 없는 A→원래 = 실패(종전 규칙 그대로)", hard)
new, hard, _c, _s = judge(edit(**dict(ST, store=ST["store"] + "\n\ndef w():\n    import wallets\n    return wallets.add_w\n")),
                          split_of=SO_B, proof=pro_b(BACK))
chk(any("store" in x and "wallets" in x for x in hard.get("split.cycle", [])),
    "[4b] back 근거가 있어도 원래→A 간선이 함께 있으면 계열 안 순환 = 실패", hard)
new, hard, _c, spn = judge(edit(**dict(ST, wallets="import store\n\n\ndef add_w(a):\n    return store.add_w, a\n")),
                           split_of=SO_B, proof=pro_b(BACK))
chk(any("wallets → store" in x for x in hard.get("split.internal", [])) and any("wallets → store [back" in x for x in spn.stale),
    "[4b] A 가 원래 모듈의 옮긴 이름만 읽음(store.add_w) = back 근거 낡음 → 실패", (hard, spn.stale))
new, hard, _c, spx = judge(MID, proof={"origins": {"common": dict(PROOF["origins"]["common"], edges=PROOF["origins"]["common"]["edges"]
                                                                   + [{"m": "config", "to": "common", "why": "back", "q": "load_config"}])}})
chk(("config", "common") not in spx.allow, "[4b] 지금 안 읽는 back 근거(config → common)는 허용 표에 안 들어감", sorted(spx.allow))

new, hard, _c, _s = judge(edit(paths=MID["paths"] + "\n\ndef cfg():\n    import config\n    return config.load_config()\n"))
chk(any("paths → config" in x for x in hard.get("split.internal", [])) and any("config" in x for x in hard.get("split.cycle", [])),
    "[5] paths→config 추가 → 실패(⑤)", hard)

new, hard, _c, _s = judge(edit(paths=MID["paths"] + "\n\ndef keys():\n    import nodekeys\n    return nodekeys\n"))
chk(("import.cycle_edges", "paths", "nodekeys") in new and ("import.cycle_edges", "config", "nodekeys") not in new,
    "[6] paths→nodekeys(증명 없음)는 새 순환 간선 · 증명된 config→nodekeys 는 그대로 승계(⑥)", new)

cl = {"u-a": ["common", "entry_a", "paths"], "u-b": ["entry_b", "paths"], "u-c": ["entry_c", "extra", "paths"]}
before = {u: list(v) for u, v in cl.items()}
d0, d1 = C.counted(cl, {}), C.counted(cl, {"paths": "common"})
chk(cl == before and {u: x["n"] for u, x in d0["items"].items()} == {"u-a": 3, "u-b": 2, "u-c": 3},
    "[7] split_of 비어 있음 = 실제 노드 수 · 셈이 실제 폐포 목록을 바꾸지 않음(⑦)")
chk({u: x["n"] for u, x in d1["items"].items()} == {"u-a": 2, "u-b": 2, "u-c": 3},
    "[7] 접은 셈: common+paths = 하나 · paths 만 닿아도 common 하나로 · paths 를 거쳐 새로 닿은 모듈(extra)은 그대로 셈")

BASE_DIR = os.path.join(T.HERE, "arch_baseline")
if C.R.repo_layout() and C.unit_table(T.ROOT) is not None and os.path.isdir(BASE_DIR):
    with open(os.path.join(BASE_DIR, "layers.json"), encoding="utf-8") as f:
        LIVE = json.load(f)
    with open(os.path.join(BASE_DIR, S.PROOF_FILE), encoding="utf-8") as f:
        LIVE_PROOF = json.load(f)
    chk("split_of" not in LIVE and C.split_table() == {},
        "[7h] layers.json 에 split_of 없음(4-6 끝 승계 해제 · 결정 18)", sorted(LIVE.get("split_of") or {}))
    chk(LIVE_PROOF.get("origins") == {}, "[7h] 분할 근거 py_split_proof.json origins 비어 있음(옛 근거로 승계 되살리기 0)",
        sorted(LIVE_PROOF.get("origins") or {}))
    real = C.closures(T.ROOT)
    chk(real and C.counted(real)["items"] == {u: {"n": len(v)} for u, v in real.items()},
        "[7h] 폐포 셈 = 실제 노드 수(접힘 0 · 유닛 %d)" % len(real))

    def _have(m):
        top = m.split(".")[0]
        return os.path.isfile(os.path.join(T.SRC, top + ".py")) or os.path.isdir(os.path.join(T.SRC, top))
    ghost = sorted(m for m in LIVE.get("modules", {}) if not _have(m))
    chk(not ghost, "[7h] layers.json modules = src 에 있는 모듈만(지운 원래 모듈 common 등 0)", ghost)
    stale = []
    for fn in ("py_imports.jsonl", "py_layers.jsonl"):
        for ln in R.load_lines(os.path.join(BASE_DIR, fn)) or []:
            if ln.get("k") in S.SPLIT_KEYS and not (_have(ln["m"]) and _have(ln["q"])):
                stale.append("%s %s %s→%s" % (fn, ln["k"], ln["m"], ln["q"]))
    chk(not stale, "[7h] 간선 지표 기준선 줄이 없는 모듈을 가리키지 않음(옛 신원 common→X · X→common 0 — 해제 때 실제 신원으로 고정됨)", stale)
else:
    chk(True, "[7h] 지금 저장소 대조 — 공개판 배치(배포 도구·기준선 없음) · 건너뜀")

pre_h = {u["q"]: u["h"] for u in PRE_MX.units["func.lines"]}
mx, sp = build(edit(bf_engine=CODEMOD_BF), SPLIT_OF)
mid_h = {(u["m"], u["q"]): u["h"] for u in mx.units["func.lines"]}
chk(mid_h[("config", "load_config")] == pre_h["load_config"] and mid_h[("common", "gate")] == pre_h["gate"]
    and mid_h[("envfile", "read_env")] == pre_h["read_env"] and mid_h[("web", "page")] == pre_h["page"]
    and mid_h[("bf_engine", "boot")] == pre_h["boot"],
    "[8] 치환 자리만 기준선 꼴로: 옮긴 함수(paths.X → 맨 X) · 남은 함수 · 바깥 함수(paths.X → common.X)의 지문 = 기준선 지문")
chk(mid_h[("web", "view")] != pre_h["view"],
    "[8] 매개변수 paths 의 속성(paths.STATE_DIR)은 정규화하지 않음 — 모듈 common.STATE_DIR 를 읽던 기준선 함수와 지문이 다름")
mx_raw, _ = build(edit(bf_engine=CODEMOD_BF))
raw_h = {(u["m"], u["q"]): u["h"] for u in mx_raw.units["func.lines"]}
chk(raw_h[("web", "page")] != pre_h["page"] and raw_h[("pricing", "lookup")] == mid_h[("pricing", "lookup")],
    "[8] 정규화 없이는 지문이 다름(정규화가 실제로 일함) · 치환 자리가 없는 함수는 그대로")


class _St:
    def __init__(self, lay):
        self.layers, self.metrics, self.index, self.rules = lay, PRE_MX, {}, {}


chk(S.attach(_St({"layers": LAYERS, "modules": MODS}), T.SRC) is None and S.attach(_St(layers({})), T.SRC) is None
    and S.fold_units(None, "import.cycle_edges", [1], []) == [1],
    "[8] split_of 가 없거나 비면 attach = None · 비교 단위 그대로(도입 전과 같음)")

import ast  # noqa: E402

import _arch_scope as SC  # noqa: E402


def resolved(text, name, nth=0):
    t = SC.annotate(ast.parse(text))
    hits = [n._r for n in ast.walk(t) if isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Load)]
    return hits[nth] if len(hits) > nth else None


chk(resolved("X = 7\n\n\ndef f(xs):\n    [(X := y) for y in xs]\n    return X\n", "X") == ("local",),
    "[8'] 걸음식(:=)은 컴프리헨션 밖 함수에 묶음 → return X = 지역")
chk(resolved("import paths\n\n\ndef f():\n    global paths\n    import pricing as paths\n    return paths.X\n", "paths")[0] == "amb",
    "[8'] global 아래 import 는 모듈 범위에 묶음 → 모듈의 paths 가 두 꼴(amb)")
chk(resolved("import paths\n\n\ndef f():\n    paths = 1\n\n    def g():\n        nonlocal paths\n        return paths\n    return g\n", "paths")
    == ("local",), "[8'] nonlocal = 바깥 함수의 지역")
chk(resolved("import config\n\n\ndef f():\n    return [0 for config in config.fresh()]\n", "config") == ("mod", "config"),
    "[8'] 컴프리헨션 첫 iter = 바깥 범위(모듈 config)")
chk(resolved("import config\n\n\nclass H:\n    v = config.fresh()\n    config = None\n", "config") == ("mod", "config")
    and resolved("import config\n\n\nclass H:\n    config = None\n    v = config\n", "config") == ("local",)
    and resolved("import config\n\n\nclass H:\n    if v:\n        config = None\n    w = config\n", "config")[0] == "amb",
    "[8'] 클래스 몸통 = 문장 순서(묶이기 전 = 바깥 모듈 · 무조건 묶인 뒤 = 클래스 · 조건부로 묶인 뒤 = 여러 꼴)")
chk(resolved("from logs import f as lf\n\n\ndef u():\n    return lf(1)\n", "lf") == ("from", "logs", "f"),
    "[8'] from import = (from, 모듈, 원래 이름) — 별칭만 같고 원래 이름이 다르면 다른 풀이")
chk(resolved("import pricing\n\n\ndef f(x=pricing.Y):\n    return x\n", "pricing") == ("mod", "pricing"),
    "[8'] 기본값은 바깥 범위에서 풂")
chk(resolved("import config\n\n\ndef boot():\n    import config as cfg\n\n    def middle():\n        def change():\n            nonlocal cfg\n"
             "            import helper as cfg\n        return cfg.fresh()\n    return middle\n", "cfg")[0] == "amb",
    "[8'] nonlocal 재묶음 = 그 이름을 실제로 묶는 바깥 함수(boot)에 더함 → middle 의 cfg 는 여러 꼴(amb)")
if sys.version_info >= (3, 10):
    chk(resolved("X = 7\n\n\ndef f(v):\n    match v:\n        case X:\n            return X\n", "X") == ("local",),
        "[8'] match 패턴 묶음(case X)은 함수 지역")
else:
    chk(True, "[8'] match 패턴 — 파이썬 3.10 미만이라 건너뜀")

_n, hard, _c, _s = judge(MID, split_of=dict(SPLIT_OF, ghost="common"))
chk(any("ghost" in x for x in hard.get("split.proof", [])), "[9] split_of 의 분할 모듈이 src 에 없으면 split.proof 실패", hard)
_n, hard, _c, _s = judge(MID, proof={"origins": {}})
chk(any("항목 없음" in x for x in hard.get("split.proof", [])) and any("common → config" in x for x in hard.get("split.internal", [])),
    "[9] 근거 파일에 원래 모듈 항목이 없으면 split.proof 실패 · 대리 다리 간선도 증명 없음", hard)
dup = {"origins": {"common": dict(PROOF["origins"]["common"], moved=dict(PROOF["origins"]["common"]["moved"], envfile=["read_env", "STATE_DIR"]))}}
_n, hard, _c, _s = judge(MID, proof=dup)
chk(any("겹침" in x for x in hard.get("split.proof", [])), "[9] 옮긴 이름이 두 분할 모듈에 겹치면 split.proof 실패", hard)
if os.path.isfile(os.path.join(T.HERE, "_arch_py_checks.py")):
    import _arch_py_checks as K  # noqa: E402
    old = {"layers": LAYERS, "modules": MODS}
    chk(K._loosened_layers(dict(old, split_of={"paths": "common"}), old)
        and not K._loosened_layers(old, dict(old, split_of={"paths": "common"})),
        "[9] 무결성: split_of 늘림 = 느슨해짐(총괄 커밋) · 지움 = 괜찮음")
    chk(K._loosened_split_proof(PROOF, {"origins": {}}) and not K._loosened_split_proof({"origins": {}}, PROOF)
        and not K._loosened_split_proof(PROOF, PROOF)
        and K._loosened_split_proof({"origins": {"settings": {"edges": PROOF["origins"]["common"]["edges"][:1]}}},
                                    {"origins": {"common": {"edges": PROOF["origins"]["common"]["edges"][:1]}}}),
        "[9] 무결성: 근거(옮긴 이름·간선) 늘림 = 느슨해짐 · 지움·그대로 = 괜찮음 · 같은 간선을 다른 원래 모듈로 옮김도 늘림")
T.finish()
