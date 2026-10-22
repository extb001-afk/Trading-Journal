#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import os  # noqa: E402
import shutil  # noqa: E402

chk = T.chk
ROOT = T.ROOT
PLAN = os.path.join(ROOT, "tools", "refactor", "deploy_plan.py")
if not (os.path.isfile(os.path.join(ROOT, "tools", "deploy_lib.sh")) and os.path.isfile(PLAN)):
    print("SKIP tools/deploy_lib.sh·tools/refactor/deploy_plan.py 없음(공개판 — 배포 도구는 운영 저장소에만)")
    T.finish()
sys.path.insert(0, os.path.dirname(PLAN))
import _arch_closure as AC  # noqa: E402
import deploy_plan as DP  # noqa: E402

NO_UNIT = {}

D = DP.Deriver(ROOT)
DF = DP.Deriver(ROOT, fast=False)
try:
    fonts = [f for f in DP.runtime_files(ROOT) if f.startswith("web/v2/fonts/")]
    files = [f for f in DP.runtime_files(ROOT) if f not in fonts[1:]]
    src_files = [f for f in files if f.startswith("src/") and f.endswith(".py")]
    brokers = sorted(f for f in src_files if f.startswith("src/brokers/"))
    sample = ["src/paths.py", "src/web.py", "src/core_recon.py", "seed/lp_managers.json", "tools/rebuild2.py", "VERSION"] + brokers[:1]
    diff0 = {f: (D.units([f])[1], DF.units([f])[1]) for f in sample}
    diff0 = {f: v for f, v in diff0.items() if v[0] != v[1]}
    chk(not diff0, "P0 빠른 도출 = 글자 그대로 도출(표본 %d파일)" % len(sample), diff0)
    rc_all, all_units, out_all = D.units(src_files)
    chk(rc_all == 0 and all_units, "P0 src 전체를 한 번에 도출 = 성공", out_all[-300:])

    got = {}
    fails = []
    for f in files:
        rc, units, out = D.units([f])
        if rc:
            fails.append((f, out.strip()[-160:]))
        got[f] = units
    chk(not fails, "P0 파일 %d개 하나씩 도출 = 전부 성공(형식 오류·pm2 목록 오류 없음)" % len(files), fails[:5])

    zero = [f for f in src_files if not got.get(f) and f not in NO_UNIT]
    stale = [f for f in NO_UNIT if got.get(f)]
    chk(src_files and not zero, "P1 src 파일 %d개마다 재시작 유닛 ≥ 1(아니면 NO_UNIT 에 이유와 함께)" % len(src_files), zero)
    chk(not stale, "P1 NO_UNIT 에 적힌 파일에 유닛이 생기면 목록에서 뺀다", stale)

    cl = AC.closures(ROOT)
    _g, node_of = AC.graph(ROOT, *AC.unit_table(ROOT))
    mism = []
    for f in src_files:
        nd = node_of(f)
        want = sorted(u for u, mods in cl.items() if nd in mods)
        if sorted(got.get(f, [])) != want:
            mism.append({"file": f, "도출": got.get(f), "폐포": want})
    chk(not mism, "P2 src 파일별 도출 유닛 = 유닛 import 폐포(따로 짠 구현)에 그 노드가 든 유닛", mism[:6])

    webf = [f for f in files if f.startswith("web/")]
    badw = [(f, got[f]) for f in webf if got[f] != ["tj-web"]]
    chk(webf and not badw, "P3 web/** %d파일 = tj-web 만" % len(webf), badw[:5])
    vu = got.get("VERSION", [])
    chk("tj-web" in vu and sorted(vu) == sorted(u for u, mods in cl.items() if "version" in mods),
        "P3 VERSION = version 모듈을 싣는 유닛(tj-web 포함)", vu)

    toolf = [f for f in files if f.startswith("tools/")]
    badt = []
    for f in toolf:
        want = sorted(u for u, mods in cl.items() if f in mods)
        if sorted(got[f]) != want:
            badt.append({"file": f, "도출": got[f], "폐포": want})
    with_units = sorted(f for f in toolf if got[f])
    chk(toolf and not badt, "P4 tools 최상위 %d파일 = 입구·동적 간선 대상만 유닛(폐포 대조) · 그 밖 1회 도구 = 없음" % len(toolf), badt[:5])
    chk("tools/wallet_reload_watch.py" in with_units and "tools/rebuild2.py" in with_units,
        "P4 유닛 있는 tools = 입구(tj-reload)·run 대상(rebuild2·verify_fixc) — 지금 %s" % " · ".join(with_units))

    seedf = [f for f in files if f.startswith("seed/")] + [f for f in ("config.example.json",) if f in files]
    nos = [f for f in seedf if not got[f]]
    chk(seedf and not nos, "P5 seed·config.example.json %d파일 = 유닛 ≥ 1" % len(seedf), nos)
    full = sorted(all_units)
    wide = [f for f in seedf if sorted(got[f]) == full]
    if wide:
        print("  안내 P5: 읽는 모듈을 못 찾았거나 공용 모듈이 읽어 '전 유닛' 재시작이 되는 seed %d개: %s" % (len(wide), " ".join(os.path.basename(x) for x in wide)))
finally:
    D.close()
    DF.close()

SYN = os.path.join(T.TMP, "plan_syn")
os.makedirs(os.path.join(SYN, "src"))
os.makedirs(os.path.join(SYN, "tools"))
shutil.copy(os.path.join(ROOT, "tools", "deploy_lib.sh"), os.path.join(SYN, "tools", "deploy_lib.sh"))
for rel, body in {"src/web.py": "import a\n", "src/a.py": "", "src/orphan.py": "import a\n"}.items():
    with open(os.path.join(SYN, rel), "w", encoding="utf-8") as fh:
        fh.write(body)
S = DP.Deriver(SYN)
try:
    r_or, r_a = S.units(["src/orphan.py"]), S.units(["src/a.py"])
finally:
    S.close()
chk(r_or[0] == 0 and r_or[1] == [], "P6 반례: 어느 유닛도 싣지 않는 모듈(orphan) = 유닛 0 — P1 이 잡는 꼴", r_or[2][-200:])
chk(r_a[0] == 0 and r_a[1] == ["tj-web"], "P6 입구(web)가 싣는 모듈 = 그 유닛 · 입구 파일 없는 유닛 = 도출 밖", r_a[2][-200:])
T.finish()
