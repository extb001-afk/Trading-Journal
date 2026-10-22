#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

chk = T.chk
BASE = os.path.join(T.TMP, "base")
os.makedirs(os.path.join(BASE, "state"), exist_ok=True)
ENV0 = {k: v for k, v in os.environ.items() if not k.startswith("TJ_") or k.startswith("TJ_TEST_")}
CHILD = os.path.join(T.TMP, "paths_child.py")
with open(CHILD, "w", encoding="utf-8") as f:
    f.write(r'''
import json, os, subprocess, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
mode = sys.argv[2]
import importlib
MODS = []   # 4막: common 이 paths·config·seeds·histmark 로 나뉘어도 같은 시험 — 이름마다 정의 모듈(대리 common 은 옮긴 이름을 dict 에 안 둠)
for m9 in ("paths", "config", "seeds", "histmark"):
    try:
        MODS.append(importlib.import_module(m9))
    except ImportError:
        pass
def owner(n):
    for m9 in MODS:
        if n in vars(m9):
            return m9
    raise AttributeError(n)
def g(n):
    return getattr(owner(n), n)
def snap():
    return {"state": g("STATE_DIR"), "inbox": g("INBOX_DIR"), "db": g("DB_PATH"), "env": g("ENV_PATH"), "config": g("CONFIG_PATH"),
            "base": g("BASE_DIR"), "gate": g("ACTIVITY_GATE_PATH"), "speed": g("BACKFILL_SPEED_PATH"), "quota_attr": g("QUOTA_STATE_DIR"),
            "quota": g("quota_dir")(), "iso": g("DEMO_ISOLATED"), "env_demo_state": os.environ.get("TJ_DEMO_STATE")}
out = {"before": snap()}
if mode == "demo":
    out["exists"] = os.path.isdir(g("STATE_DIR"))
    pid = os.fork()
    if pid == 0:
        sys.exit(0)            # fork 자식이 보통 끝남(atexit 돎) — 주인이 아니라 지우면 안 됨
    os.waitpid(pid, 0)
    out["after_fork"] = os.path.isdir(g("STATE_DIR"))
    p = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import %s as M; print(M.STATE_DIR)" % owner("STATE_DIR").__name__,
                        sys.argv[1]], capture_output=True, text=True, timeout=60)
    out["sub_state"] = p.stdout.strip()
    out["after_sub"] = os.path.isdir(g("STATE_DIR"))
elif mode == "rebase":
    d, db, q, cfg_w = sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6]
    cfg = json.loads(cfg_w)
    out["gate_before"] = len(g("gate_decisions")(cfg))
    g("rebase_state")(d)
    out["after"] = snap()
    out["gate_after"] = [x.get("chain") for x in g("gate_decisions")(cfg)]
    out["seed"] = g("seed_json")("paths_probe.json", None, base_dir=sys.argv[7])
    out["mark"] = g("mark_hist_dirty")(1700000000)
    out["mark_file"] = os.path.isfile(os.path.join(d, "hist_dirty.json"))
    g("rebase_state")(d, db_path=db)
    out["after_db"] = snap()
    setattr(owner("QUOTA_STATE_DIR"), "QUOTA_STATE_DIR", q)
    out["quota_set"] = g("quota_dir")()
print("JSON " + json.dumps(out, ensure_ascii=False))
''')


def child(mode, *args, **env):
    e = dict(ENV0, TJ_BASE=BASE, **env)
    p = subprocess.run([sys.executable, CHILD, T.SRC, mode] + list(args), capture_output=True, text=True, timeout=120, env=e)
    js = [x for x in p.stdout.splitlines() if x.startswith("JSON ")]
    return (json.loads(js[-1][5:]) if js else {"_rc": p.returncode, "_out": (p.stdout + p.stderr)[-800:]})


r = child("demo", TJ_DEMO="1")
b = r.get("before") or {}
st = b.get("state") or ""
chk(os.path.basename(st).startswith("tj_demo_state_") and os.path.dirname(os.path.realpath(st)) == os.path.realpath(tempfile.gettempdir())
    and st != os.path.join(BASE, "state") and r.get("exists") is True, "P1 데모 = 임시 state 폴더(tj_demo_state_*) · 실사용 state 아님", r)
chk(b.get("env") == os.path.join(st, ".env") and b.get("config") == os.path.join(st, "config.json") and b.get("iso") is True,
    "P1 데모 .env·config.json = 데모 state 안(실사용 것을 안 엶) · DEMO_ISOLATED", b)
chk(b.get("inbox") == os.path.join(st, "inbox") and b.get("db") == os.path.join(st, "ledger.db"), "P1 데모 inbox·원장 = 데모 state 안", b)
chk(b.get("env_demo_state") == st and r.get("sub_state") == st, "P1 TJ_DEMO_STATE 를 환경에 남김 → 하위 프로세스가 같은 폴더", r)
chk(r.get("after_fork") is True and r.get("after_sub") is True, "P1 fork 자식·하위 프로세스가 끝나도 폴더 남음(주인 pid 만 지움)", r)
chk(bool(st) and not os.path.exists(st), "P1 주인 프로세스가 끝나면 임시 폴더 지움", st)
cfg_x = os.path.join(T.TMP, "synthetic_config.json")
r = child("demo", TJ_DEMO="1", TJ_CONFIG=cfg_x)
b = r.get("before") or {}
chk(b.get("config") == cfg_x and b.get("env") == os.path.join(b.get("state") or "?", ".env"), "P1 데모 + TJ_CONFIG = 그 설정 · .env 는 여전히 데모 state", b)
given = os.path.join(T.TMP, "given_demo_state")
os.makedirs(given, exist_ok=True)
r = child("demo", TJ_DEMO="1", TJ_DEMO_STATE=given)
b = r.get("before") or {}
chk(b.get("state") == given and b.get("env") == os.path.join(given, ".env") and b.get("config") == os.path.join(given, "config.json")
    and os.path.isdir(given), "P1 TJ_DEMO_STATE 로 준 폴더 = 그대로 쓰고 끝나도 안 지움 · 격리 유지", b)
r = child("demo")
b = r.get("before") or {}
chk(b.get("state") == os.path.join(BASE, "state") and b.get("env") == os.path.join(BASE, ".env") and b.get("config") == os.path.join(BASE, "config.json")
    and b.get("iso") is False and not b.get("env_demo_state"), "P1 데모 아님 = TJ_BASE 아래 종전 경로 · TJ_DEMO_STATE 안 남김", b)

NEW = os.path.join(T.TMP, "rebased_state")
os.makedirs(os.path.join(NEW, "seed_local"), exist_ok=True)
ADDR = "0x" + "ab" * 20
with open(os.path.join(NEW, "chain_activity.json"), "w", encoding="utf-8") as f:
    json.dump({"pairs": {"base:" + ADDR: {"active": True, "since_block": 5}}}, f)
with open(os.path.join(NEW, "seed_local", "paths_probe.json"), "w", encoding="utf-8") as f:
    json.dump({"probe": 1}, f)
EMPTY_TREE = os.path.join(T.TMP, "empty_tree")
os.makedirs(EMPTY_TREE, exist_ok=True)
DB2 = os.path.join(T.TMP, "other_ledger.db")
Q = os.path.join(T.TMP, "quota_live")
CFG = {"wallets": [{"type": "evm", "chain": "eth", "address": ADDR, "label": "합성"}], "chains": {"base": {}}}
r = child("rebase", NEW, DB2, Q, json.dumps(CFG), EMPTY_TREE)
b0, a1, a2 = r.get("before") or {}, r.get("after") or {}, r.get("after_db") or {}
chk(a1.get("state") == NEW and a1.get("inbox") == os.path.join(NEW, "inbox") and a1.get("db") == os.path.join(NEW, "ledger.db")
    and a1.get("gate") == os.path.join(NEW, "chain_activity.json") and a1.get("speed") == os.path.join(NEW, "chain_backfill_speed.json"),
    "P2 rebase_state = 다섯 경로(STATE·INBOX·DB·활동 게이트·백필 속도) 새 폴더로", a1 or r)
chk(all(a1.get(k) == b0.get(k) for k in ("env", "config", "base", "quota_attr")) and b0.get("quota_attr") is None,
    "P2 ENV_PATH·CONFIG_PATH·BASE_DIR·QUOTA_STATE_DIR 는 안 바뀜", {k: (b0.get(k), a1.get(k)) for k in ("env", "config", "base", "quota_attr")})
chk(b0.get("quota") == b0.get("state") and a1.get("quota") == NEW and r.get("quota_set") == Q,
    "P2 quota_dir() = 지금 STATE_DIR(호출 시점) · QUOTA_STATE_DIR 를 주면 그것", (b0.get("quota"), a1.get("quota"), r.get("quota_set")))
chk(a2.get("db") == DB2 and a2.get("state") == NEW, "P2 rebase_state(db_path=…) = 원장 경로는 그 값", a2)
chk(r.get("gate_before") == 0 and r.get("gate_after") == ["base"], "P2 호출 시점 반영 — gate_decisions 가 바뀐 폴더의 활동 게이트를 읽음",
    (r.get("gate_before"), r.get("gate_after")))
chk(r.get("seed") == {"probe": 1}, "P2 호출 시점 반영 — seed_json 이 바뀐 폴더의 seed_local 덮어쓰기를 읽음", r.get("seed"))
chk(r.get("mark_file") is True and bool(r.get("mark")), "P2 호출 시점 반영 — mark_hist_dirty 가 바뀐 폴더에 표식", r.get("mark"))


def _eager_imports(path):
    tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    out, stack = set(), list(tree.body)
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(n, ast.Import):
            out |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            out.add(n.module.split(".")[0])
        stack.extend(ast.iter_child_nodes(n))
    return out


def _registers(path):
    tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    for st9 in tree.body:
        for n in ast.walk(st9) if not isinstance(st9, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else ():
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "set_sources":
                return True
    return False


import _arch_closure as AC  # noqa: E402
UT = AC.unit_table(T.ROOT)
if UT is None:
    print("SKIP 배포 유닛 표 없음(공개판 배치) — P3 건너뜀")
else:
    mods = {f[:-3] for f in os.listdir(T.SRC) if f.endswith(".py")}
    regs = sorted(m for m in mods if _registers(os.path.join(T.SRC, m + ".py")))
    chk(bool(regs) and "logs" not in regs, "P3 등록 지점 = 최상위에서 logs.set_sources 를 부르는 src 모듈(logs 자신 아님)", regs)
    memo = {}

    def closure(path):
        seen, st9 = set(), [path]
        while st9:
            p = st9.pop()
            if p in seen:
                continue
            seen.add(p)
            if p not in memo:
                memo[p] = {os.path.join(T.SRC, m + ".py") for m in _eager_imports(p) if m in mods}
            st9.extend(memo[p])
        return {os.path.basename(x)[:-3] for x in seen}

    table, _edges = UT
    miss, seen_units = {}, []
    for name, entry, runner, *_rest in table:
        if entry == "-" or not os.path.isfile(os.path.join(T.ROOT, entry)):
            continue
        starts = [os.path.join(T.ROOT, entry)] + ([os.path.join(T.SRC, "unit_runner.py")] if runner != "-" else [])
        for s9 in starts:
            seen_units.append("%s:%s" % (name, os.path.relpath(s9, T.ROOT)))
            if not set(regs) & closure(s9):
                miss.setdefault(name, []).append(os.path.relpath(s9, T.ROOT))
    chk(len(seen_units) >= 10 and not miss, "P3 모든 유닛 입구(+ 러너)의 최상위 import 폐포에 등록 지점(%s) 있음 — %d곳" % ("·".join(regs), len(seen_units)),
        miss or seen_units)
T.finish()
