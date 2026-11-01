#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

import paths  # noqa: E402
import chk_collect  # noqa: E402

D = os.path.join(T.TMP, "fakeproc")
os.makedirs(D, exist_ok=True)
CORE = os.path.join(D, "core.py")
with open(CORE, "w") as f:
    f.write("import sys, time\nsys.path.insert(0, %r)\nimport calcguard\n" % T.SRC
            + "for a in sys.argv[1:]:\n"
              "    k, _, n = a.partition('*')\n"
              "    for _i in range(int(n or 1)):\n"
              "        calcguard.swallowed('core:apply_leg' if k == 'bug' else 'core:price_fetch',\n"
              "                            NameError(\"name 'qty9' is not defined\") if k == 'bug' else ConnectionError('rpc down'))\n"
              "    calcguard.flush()\n")
ENV = dict(os.environ, TJ_BASE=paths.BASE_DIR)
ENV.pop("TJ_STRICT", None)
P = os.path.join(paths.STATE_DIR, "calcguard_core.json")


def run(*a):
    subprocess.run([sys.executable, "-I", "-B", CORE] + list(a), env=ENV, check=True)
    time.sleep(1.1)


def sites():
    return (json.load(open(P)).get("sites") or {}) if os.path.exists(P) else {}


run("bug")
cg1 = [(c["cid"], c["level"]) for c in chk_collect.collect_calcguard(time.time(), paths.STATE_DIR)]
T.chk(("calc:bug", "crit") in cg1, "R1 1차 실행 코드 실수 = 빨강", cg1)
run("net")
s = sites()
cg2 = [(c["cid"], c["level"]) for c in chk_collect.collect_calcguard(time.time(), paths.STATE_DIR)]
T.chk("core:apply_leg" in s and s["core:apply_leg"].get("bug") == 1 and "core:price_fetch" in s, "R1 재시작 뒤 저장 = 1차 빨강 자리 남음 + 새 자리", sorted(s))
T.chk(("calc:bug", "crit") in cg2, "R1 상태 패널 빨강 유지", cg2)

run("bug*2", "bug", "bug")
s = sites()
T.chk(s.get("core:apply_leg", {}).get("bug") == 1 + 4 and s.get("core:apply_leg", {}).get("n") == 5, "R2 같은 실행 여러 저장 = 두 번 세지 않음 · 실행 넘어 합(1+4)",
      s.get("core:apply_leg"))
T.chk(s.get("core:price_fetch", {}).get("n") == 1, "R2 이번에 안 난 자리도 직전 기록 그대로", s.get("core:price_fetch"))

d = json.load(open(P))
d["sites"]["core:old_site"] = {"n": 3, "first": 1, "last": int(time.time() - 8 * 86400), "types": {"KeyError": 3}, "why": "x", "bug": 0,
                               "bug_last": 0, "bug_why": "", "sus": 3, "sus_last": int(time.time() - 8 * 86400), "sus_why": "x"}
d["at"] = int(time.time() - 5)
json.dump(d, open(P, "w"))
time.sleep(1.1)
run("net")
s = sites()
T.chk("core:old_site" not in s and "core:apply_leg" in s, "R3 7일 넘은 조용한 자리 = 빠짐 · 나머지 유지", sorted(s))

now4 = int(time.time())
hr4 = now4 // 3600
d = json.load(open(P))
d["sites"]["core:price_fetch"] = {"n": 180000, "first": now4 - 10 * 86400, "last": now4 - 3600, "types": {"ConnectionError": 180000}, "why": "rpc down",
                                  "bug": 0, "bug_last": 0, "bug_why": "", "sus": 0, "sus_last": 0, "sus_why": "", "h": {str(hr4 - 240): 179999, str(hr4 - 1): 1}}
d["sites"]["core:legacy"] = {"n": 50, "first": now4 - 3600, "last": now4 - 600, "types": {"OSError": 50}, "why": "x", "bug": 0}
d["at"] = now4 - 5
json.dump(d, open(P, "w"))
time.sleep(1.1)
run("net", "net")
s = sites()
h4 = s.get("core:price_fetch", {}).get("h") or {}
T.chk(s["core:price_fetch"].get("n") == 180002 and str(hr4 - 240) not in h4 and sum(h4.values()) == 3,
      "R4 재시작 뒤 h = 직전 칸(1) + 이번 2회(저장 2번에도 한 번씩만) · 10일 전 칸 지움", s.get("core:price_fetch"))
T.chk("h" not in s.get("core:legacy", {}) and s["core:legacy"].get("n") == 50, "R4 옛 형식 자리 = h 없이 이어받음", s.get("core:legacy"))
sw4 = {c["cid"]: c for c in chk_collect.collect_calcguard(time.time(), paths.STATE_DIR)}.get("calc:swallow") or {}
T.chk(sw4.get("level") == "ok" and "core:price_fetch 3회" in sw4.get("detail", "") and "core:legacy 50회" in sw4.get("detail", ""),
      "R4 상태 패널 = 24시간 3회(종전 평균 ≈1.8만 = 노랑) · 옛 형식 자리 = 종전 값", sw4)

T.finish()
