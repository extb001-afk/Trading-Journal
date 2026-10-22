#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _arch_closure as C  # noqa: E402
import _arch_ratchet as R  # noqa: E402
import _harness as T  # noqa: E402

import os  # noqa: E402
import tempfile  # noqa: E402

chk = T.chk
D = R._doc

SYN = tempfile.mkdtemp(prefix="tj_closure_", dir=T.TMP)
FILES = {
    "src/entry_a.py": "import common\n\ndef f():\n    import lazy_dep   # 지연 import 도 간선\n",
    "src/common.py": "import os\n",
    "src/lazy_dep.py": "from pkg import thing\n",
    "src/pkg/__init__.py": "from . import thing\n",
    "src/pkg/thing.py": "import deep\n",
    "src/deep.py": "",
    "src/unit_runner.py": "import common\n",
    "src/entry_b.py": "import spawner\n",
    "src/spawner.py": "",
    "src/worker.py": "import deep\n",
    "src/chain_x.py": "import common\n",
    "src/recon.py": "",
    "src/orphan.py": "import entry_a\n",
    "tools/runner_only.py": "import orphan\n",
    "tools/watch.py": "import common\n",
    "tools/deploy_lib.sh": ("DEPLOY_UNIT_TABLE='\n# 이름 입구 러너 종류 필요 정지 기동\n"
                            "u-a   src/entry_a.py  -   web    req  1  3\n"
                            "u-b   src/entry_b.py  b   writer req  2  2\n"
                            "u-x   src/chain_x.py  x   chain  opt  3  4\n"
                            "u-t   tools/watch.py  -   aux    opt  4  1\n"
                            "u-n   src/missing.py  -   aux    opt  5  5\n"
                            "u-e   -               -   ext    -    -  -\n'\n"
                            "DEPLOY_DYN_EDGES='\n"
                            "spawner  spawn   src/worker.py\n"
                            "spawner  run     tools/runner_only.py\n"
                            "recon    import  @chain\n"
                            "ghost    import  @chain   # 출발 모듈 없음 = 무시\n'\n"),
}
for rel, body in FILES.items():
    p = os.path.join(SYN, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(body)
cl = C.closures(SYN)
chk(cl is not None and set(cl) == {"u-a", "u-b", "u-x", "u-t"}, "[0] 입구 '-'(u-e)·없는 파일(u-n) = 셈 밖", sorted(cl or {}))
chk(cl and cl["u-a"] == ["common", "deep", "entry_a", "lazy_dep", "pkg"],
    "[0] 지연 import 간선 · 하위 패키지 = 노드 하나(pkg) · 패키지 안 import(deep)까지 · 패키지 안 상대 import 는 같은 노드", cl and cl["u-a"])
chk(cl and cl["u-b"] == ["common", "deep", "entry_b", "spawner", "tools/runner_only.py", "unit_runner", "worker"],
    "[0] 러너 키 = unit_runner 폐포 · spawn = 대상 폐포(worker→deep) · run = 대본 노드만(그 대본의 import orphan 은 안 따라감)", cl and cl["u-b"])
chk(cl and cl["u-x"] == ["chain_x", "common", "unit_runner"] and "chain_x" not in cl["u-a"],
    "[0] chain 유닛 = 자기 입구 + 러너 · @chain 간선은 출발 모듈(recon)을 싣는 유닛에만", cl and cl["u-x"])
chk(cl and cl["u-t"] == ["common", "tools/watch.py"], "[0] tools 입구(tj-reload 꼴) = 대본 노드 + 그 import", cl and cl["u-t"])
txt = open(os.path.join(SYN, "tools", "deploy_lib.sh"), encoding="utf-8").read()
txt = txt.replace("spawner  run     tools/runner_only.py\n", "spawner  run     tools/runner_only.py\nspawner  run     tools/watch.py\n", 1)
with open(os.path.join(SYN, "tools", "deploy_lib.sh"), "w", encoding="utf-8") as f:
    f.write(txt)
cl2 = C.closures(SYN)
chk(cl2 and cl2["u-t"] == ["common", "tools/watch.py"] and {"tools/watch.py", "common"} <= set(cl2["u-b"]),
    "[0] run 대상이 유닛 입구이기도 하면 = 입구 쪽 import 를 그대로 읽음(run 이 빈 노드로 먼저 막지 않음)", (cl2 or {}).get("u-t"))
os.remove(os.path.join(SYN, "tools", "deploy_lib.sh"))
chk(C.closures(SYN) is None and C.current(SYN) is None, "[0] 배포 도구 없음(공개판 배치) = None(건너뜀)")
with open(os.path.join(SYN, "tools", "deploy_lib.sh"), "w", encoding="utf-8") as f:
    f.write("DEPLOY_UNIT_TABLE='\nu-a src/entry_a.py -\n'\nDEPLOY_DYN_EDGES='\n'\n")
try:
    C.closures(SYN)
    bad_tbl = None
except ValueError as e:
    bad_tbl = str(e)
chk(bad_tbl and "칸 7개" in bad_tbl, "[0] 유닛 표 칸 수가 틀리면 오류(조용히 0 이 되지 않음)", bad_tbl)

S = C.SPEC
bad, stale = R.compare(S, D({"tj-web": {"n": 173}, "tj-new": {"n": 3}, "tj-core": {"n": 80}}),
                       D({"tj-web": {"n": 172}, "tj-core": {"n": 81}, "tj-gone": {"n": 9}}))
chk(len(bad) == 2 and any("tj-web: n 172→173" in x for x in bad) and any("tj-new: 새 위반" in x for x in bad),
    "[R] 폐포가 늘거나 새 유닛 = 실패", bad)
chk(any("tj-core: n 81→80" in x for x in stale) and any("tj-gone" in x for x in stale), "[R] 줄거나 사라진 유닛 = 안내(기준선 조이기)", stale)
chk(R.SPECS.get(S.name) is S and R.parse(S, R.dump(S, D({"u": {"n": 5}})))["items"] == {"u": {"n": 5}},
    "[R] G0b 엔진에 지표 등록 · JSON Lines 왕복")

ROOT = T.ROOT
ut = C.unit_table(ROOT) if R.repo_layout() else None
if ut is None:
    chk(True, "[1][2] 공개판 배치 — 배포 도구(tools/deploy_lib.sh)·기준선 없음 · 건너뜀")
    T.finish()
table, _edges = ut
cl = C.closures(ROOT)
py_units = {r[0]: r for r in table if r[1] != "-" and os.path.isfile(os.path.join(ROOT, r[1]))}
miss = [u for u, r in py_units.items() if u not in cl or (r[1][4:-3] if r[1].startswith("src/") else r[1]) not in cl[u]]
chk(py_units and not miss and set(cl) == set(py_units), "[1] 파이썬 유닛 %d개마다 폐포에 자기 입구" % len(py_units), miss)
no_runner = [u for u, r in py_units.items() if r[2] != "-" and "unit_runner" not in cl[u]]
chk(not no_runner, "[1] 러너 키가 있는 유닛 = unit_runner 폐포 포함(공개 구성은 러너가 입구를 띄움)", no_runner)
chk("brokers" in cl.get("tj-web", ()) and "web" in cl.get("tj-web", ()), "[1] tj-web 폐포 = web + 증권사 패키지(brokers — 하위 패키지 노드)")
cur = C.counted(cl)
chk(cur["items"] == {u: {"n": len(v)} for u, v in cl.items()},
    "[2] 분할 승계 해제됨: 기준선과 견주는 셈 = 실제 노드 수(접힘 0 · 다시 켜면 이 시험과 test_arch_split [7h] 를 함께 고침)",
    sorted(u for u in cl if cur["items"].get(u, {}).get("n") != len(cl[u])))
print("  폐포 크기: " + " · ".join("%s %d" % (u, len(cl[u])) for u in sorted(cl)))
R.check(T, R._root(), {S.name: cur})
T.finish()
