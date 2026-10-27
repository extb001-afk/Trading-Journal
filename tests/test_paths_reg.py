#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

sys.path.insert(0, T.SRC)
import paths  # noqa: E402

chk = T.chk

VAR_SITES = {"alert_bot": 3, "chk_collect": 1, "core_dec": 1, "core_exf_late": 1, "discopen": 2, "evm_watch": 1, "ops_requests": 1,
             "settings_wallets": 1, "ton_watch": 2, "view_backfill": 1, "view_builder": 1, "view_outflows": 1}
KINDS = {".jsonl": "jsonl", ".json": "json", ".lock": "lock", ".db": "db", ".bin": "bin"}

_strict0 = os.environ.pop("TJ_STRICT", None)
base0 = paths.STATE_DIR
cases = [("ui_prefs.json",), ("candles", "prewarm.json"), ("health", "x", "y.json"), ("backups",), ("/abs/elsewhere.json",)]
same = [paths.state(*c) == os.path.join(paths.STATE_DIR, *c) for c in cases]
chk(all(same), "R1 paths.state = os.path.join(STATE_DIR, …)(조각 1~3 · 절대 조각)", same)
alt = os.path.join(T.TMP, "rebased")
paths.rebase_state(alt)
r_reb = paths.state("ui_prefs.json")
r_set = paths.state("candles", "x.json")
paths.rebase_state(base0)
r_back = paths.state("ui_prefs.json")
chk(r_reb == os.path.join(alt, "ui_prefs.json") and r_set == os.path.join(alt, "candles", "x.json") and r_back == os.path.join(base0, "ui_prefs.json"),
    "R1 호출 시점 — rebase_state 를 따라가고 되돌리면 원래 자리", (r_reb, r_set, r_back))

if _strict0 is not None:
    os.environ["TJ_STRICT"] = _strict0

_old = os.environ.get("TJ_STRICT")
try:
    os.environ["TJ_STRICT"] = "1"
    try:
        paths.state("no_such_state_name.json")
        raised = None
    except paths.UnregisteredStateName as e:
        raised = e
    ok_reg = [paths.state(n) for n in ("ui_prefs.json", "cursor_evm_eth.json", "runner_tj-web.json", "solspool_x.jsonl")]
    slash = paths.registered("cursor_evm_a/b.json")
    os.environ["TJ_STRICT"] = "2"
    try:
        paths.state("no_such_state_name.json")
        raised2 = None
    except paths.UnregisteredStateName as e:
        raised2 = e
    os.environ.pop("TJ_STRICT")
    live = paths.state("no_such_state_name.json")
finally:
    if _old is None:
        os.environ.pop("TJ_STRICT", None)
    else:
        os.environ["TJ_STRICT"] = _old
chk(isinstance(raised, AssertionError) and len(ok_reg) == 4, "R2 엄격 = 미등록 이름 던짐(AssertionError 계열) · 등록·틀 이름 통과", repr(raised))
chk(isinstance(raised2, AssertionError), "R2 엄격 2단계(TJ_STRICT=2 · 시험 하네스)도 미등록 이름 던짐", repr(raised2))
chk(live == os.path.join(paths.STATE_DIR, "no_such_state_name.json") and not slash, "R2 엄격 꺼짐 = 미등록도 그대로 합침 · 틀 {} 는 '/' 를 못 넘음")
chk(not paths.registered(None) and not paths.registered(b"ui_prefs.json"), "R2 글자 아닌 이름 = 미등록")

mods = {f[:-3] for f in os.listdir(T.SRC) if f.endswith(".py")}
bad3 = []
for tbl, is_dyn in ((paths.REG, False), (paths.DYN, True)):
    for k, v in tbl.items():
        if not (isinstance(v, tuple) and len(v) == 4):
            bad3.append((k, "모양"))
            continue
        rel, own, kind, perm = v
        if rel != k:
            bad3.append((k, "상대경로 ≠ 이름"))
        if not own or not set(own.split()) <= mods:
            bad3.append((k, "모듈", own))
        if perm is not None and not isinstance(perm, int):
            bad3.append((k, "권한"))
        if ("{}" in k) != is_dyn or "/" in k:
            bad3.append((k, "틀"))
        ext = next((kd for e, kd in KINDS.items() if k.endswith(e)), None)
        if "*" in k:
            want = {"glob"}
        elif ext:
            want = {ext}
        else:
            want = {"dir", "file"}
        if kind not in want:
            bad3.append((k, "종류", kind, sorted(want)))
chk(not bad3 and not set(paths.REG) & set(paths.DYN), "R3 표 모양(상대경로 = 이름 · 모듈 · 종류 · 권한 · 틀) — REG %d · DYN %d" % (len(paths.REG), len(paths.DYN)), bad3)

tbl4 = {}
with open(os.path.join(T.HERE, "arch_baseline", "sec_perm_table.jsonl"), encoding="utf-8") as f:
    for ln in f:
        d = json.loads(ln)
        if d.get("m") == "mode" and d.get("k", "").startswith("state/"):
            nm = d["k"][len("state/"):].rstrip("/")
            if nm and "/" not in nm:
                tbl4[nm] = d["n"]
bad4 = [(k, v[3], tbl4[k]) for k, v in paths.REG.items() if k in tbl4 and v[3] != tbl4[k]]
bad4 += [(k, v[3], None) for k, v in paths.REG.items() if v[3] is not None and k not in tbl4]
chk(not bad4 and any(v[3] is not None for v in paths.REG.values()), "R4 권한 열 = sec_perm_table(state/<이름>) · 적힌 권한은 표에 있음", bad4)


def _consts(tree):
    mc, cc = {}, {}
    for st in tree.body:
        if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name) \
                and isinstance(st.value, ast.Constant) and isinstance(st.value.value, str):
            mc[st.targets[0].id] = st.value.value
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef):
            for st in n.body:
                if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name) \
                        and isinstance(st.value, ast.Constant) and isinstance(st.value.value, str):
                    cc.setdefault(st.targets[0].id, set()).add(st.value.value)
    return mc, cc


def _aliases(tree):
    al = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                al[a.asname or a.name] = a.name
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            for a in n.names:
                al[a.asname or a.name] = n.module + "." + a.name
    return al


def _is_state_dir(e):
    return isinstance(e, ast.Attribute) and e.attr == "STATE_DIR" and isinstance(e.value, ast.Name) and e.value.id == "paths"


def state_sites(trees):
    out = []
    for m, tree in trees.items():
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            f9 = n.func
            if isinstance(f9, ast.Attribute) and f9.attr == "join" and isinstance(f9.value, ast.Attribute) and f9.value.attr == "path" \
                    and isinstance(f9.value.value, ast.Name) and f9.value.value.id == "os" and len(n.args) > 1 and _is_state_dir(n.args[0]):
                out.append((m, n.lineno, n.args[1]))
            elif isinstance(f9, ast.Attribute) and f9.attr in ("state", "StatePath") and isinstance(f9.value, ast.Name) and f9.value.id == "paths" and n.args:
                out.append((m, n.lineno, n.args[0]))
    return out


trees = {}
for fn in sorted(os.listdir(T.SRC)):
    if fn.endswith(".py"):
        with open(os.path.join(T.SRC, fn), encoding="utf-8") as f:
            trees[fn[:-3]] = ast.parse(f.read())
CONSTS = {m: _consts(t) for m, t in trees.items()}
ALIASES = {m: _aliases(t) for m, t in trees.items()}


def resolve(m, e):
    mc, cc = CONSTS[m]
    al = ALIASES[m]
    if isinstance(e, ast.Constant) and isinstance(e.value, str):
        return "lit", e.value
    if isinstance(e, ast.JoinedStr):
        return "dyn", "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in e.values)
    if isinstance(e, ast.Name):
        if e.id in mc:
            return "lit", mc[e.id]
        q = al.get(e.id, "")
        mm, _, nn = q.rpartition(".")
        if mm in CONSTS and nn in CONSTS[mm][0]:
            return "lit", CONSTS[mm][0][nn]
    if isinstance(e, ast.Attribute) and isinstance(e.value, ast.Name):
        if e.value.id in ("self", "cls"):
            vals = cc.get(e.attr) or set()
            if len(vals) == 1:
                return "lit", next(iter(vals))
        else:
            mm = al.get(e.value.id)
            if mm in CONSTS and e.attr in CONSTS[mm][0]:
                return "lit", CONSTS[mm][0][e.attr]
    return "var", ast.unparse(e)


sites = state_sites(trees)
unreg, var_n, used = [], {}, {}
for m, ln, e in sites:
    kind, val = resolve(m, e)
    if kind == "var":
        var_n[m] = var_n.get(m, 0) + 1
        continue
    tbl = paths.REG if kind == "lit" else paths.DYN
    if val not in tbl:
        unreg.append("%s:%d %s" % (m, ln, val))
    used.setdefault((kind, val), set()).add(m)
chk(len(sites) > 300 and not unreg, "R5 src state 경로 자리 %d — 글자·틀·상수 이름 전부 등록부에 있음" % len(sites), unreg[:20])
over = {m: (n, VAR_SITES.get(m, 0)) for m, n in var_n.items() if n > VAR_SITES.get(m, 0)}
chk(not over, "R5 못 푸는 변수 자리 = 모듈별 상한 안(합 %d)" % sum(var_n.values()), over)
miss6, stale6 = [], []
for (kind, val), ms in sorted(used.items()):
    own = set((paths.REG if kind == "lit" else paths.DYN)[val][1].split())
    if not ms <= own:
        miss6.append((val, sorted(ms - own)))
src_text = {}
for kind, tbl in (("lit", paths.REG), ("dyn", paths.DYN)):
    for k, v in tbl.items():
        for m in v[1].split():
            if m in used.get((kind, k), ()):
                continue
            if m not in src_text:
                with open(os.path.join(T.SRC, m + ".py"), encoding="utf-8") as f:
                    src_text[m] = f.read()
            if m in var_n:
                continue
            if kind == "dyn" or ('"%s"' % k not in src_text[m] and "'%s'" % k not in src_text[m]):
                stale6.append((k, m))
chk(not miss6 and not stale6, "R6 만지는 모듈 열 = 정적 자리 모듈 전부 · 적힌 모듈은 그 이름을 씀", {"빠짐": miss6[:10], "안 씀": stale6[:10]})
unused = [k for k in paths.REG if ("lit", k) not in used] + [k for k in paths.DYN if ("dyn", k) not in used]
print("안내 R6 정적 자리 없이 변수로만 닿는 이름: %s" % unused[:12])

KEEP = {"core_exf.ExfMixin.EXF_DEBT_FIRST_SEEN": "BASE_DIR(설치 뿌리) — rebase_state 대상 아님 · 프로세스 동안 고정",
        "coverage_limits.SEED_DIR": "BASE_DIR — 위와 같음",
        "http_assets.WEB_DIR": "BASE_DIR — 위와 같음",
        "onboarding.SETUP_JS": "BASE_DIR — 위와 같음",
        "login_auth.DEV_PATH": "DEVICES = login_device.DeviceStore(DEV_PATH) — 메모리 사본·잠금을 가진 객체가 import 때 경로로 만들어짐",
        "login_auth.AUTH_PATH": "인증 state 경로 묶음(DEV_PATH 와 같이) — tools/reset_password 가 모듈 속성으로 읽음",
        "login_auth.SESS_PATH": "위와 같음", "login_auth.INTERNAL_PATH": "위와 같음", "login_auth.SETUP_CODE_PATH": "위와 같음",
        "candles.CACHE_DIR": "경로 도우미 4개(_cpath·_neg_path·_pools_path·_cgx_path)의 뿌리 — 호출 시점화하면 copy.statepath 새 위반(드러남)이라 paths 도우미로 옮길 때 같이",
        "nft.BUDGET_PATH": "재구축 도구(rebuild2)가 라이브 state 로 다시 묶어 호출 예산을 합산(paths.QUOTA_STATE_DIR 와 같은 뜻)"}
_PATH_ATTRS = {"STATE_DIR", "BASE_DIR", "INBOX_DIR", "DB_PATH", "CONFIG_PATH", "ENV_PATH", "ACTIVITY_GATE_PATH", "BACKFILL_SPEED_PATH", "QUOTA_STATE_DIR"}


def _reads_path(e):
    stack = [e]
    while stack:
        x = stack.pop()
        if isinstance(x, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name) and x.value.id == "paths" and x.attr in _PATH_ATTRS:
            return True
        if isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) and isinstance(x.func.value, ast.Name) and x.func.value.id == "paths" \
                and x.func.attr in ("state", "quota_dir"):
            return True
        stack.extend(ast.iter_child_nodes(x))
    return False


def _copies(body, qual, out):
    for st9 in body:
        if isinstance(st9, ast.If) and "__main__" in ast.unparse(st9.test):
            continue
        if isinstance(st9, ast.ClassDef):
            _copies(st9.body, qual + st9.name + ".", out)
            continue
        if isinstance(st9, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(_reads_path(d) for d in st9.args.defaults + [d for d in st9.args.kw_defaults if d is not None]):
                out.append(qual + st9.name + "(기본 인자)")
            continue
        if isinstance(st9, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and st9.value is not None and _reads_path(st9.value):
            tg = st9.targets if isinstance(st9, ast.Assign) else [st9.target]
            out.extend(qual + ast.unparse(x) for x in tg)
        for fld in ("body", "orelse", "finalbody", "handlers"):
            sub = getattr(st9, fld, None)
            if sub and not isinstance(st9, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                _copies([h for x in sub for h in (x.body if isinstance(x, ast.ExceptHandler) else [x])], qual, out)


copies = []
for m, tree in trees.items():
    if m != "paths":
        _copies(tree.body, m + ".", copies)
chk(sorted(copies) == sorted(KEEP), "R8 import 시점 경로 사본 = 남긴 %d자리(KEEP · 이유 적힘)뿐 — 새 사본은 호출 시점(paths.state · paths.StatePath)으로" % len(KEEP),
    {"새로": sorted(set(copies) - set(KEEP)), "없어짐": sorted(set(KEEP) - set(copies))})
statep = [(m, n.lineno) for m, tree in trees.items() for n in ast.walk(tree)
          if isinstance(n, ast.Call) and ast.unparse(n.func) == "paths.StatePath"]
cls_sp = [(m, s9.lineno) for m, tree in trees.items() for c in ast.walk(tree) if isinstance(c, ast.ClassDef) for s9 in c.body
          if isinstance(s9, ast.Assign) and isinstance(s9.value, ast.Call) and ast.unparse(s9.value.func) == "paths.StatePath"]
chk(statep and sorted(statep) == sorted(cls_sp), "R8 paths.StatePath = 클래스 몸통 대입에서만(%d)" % len(statep), sorted(set(statep) - set(cls_sp)))

env7 = {k: v for k, v in os.environ.items() if not k.startswith("TJ_")}
env7.update({"TJ_BASE": T.TMP, "TJ_DEMO": "1", "PYTHONDONTWRITEBYTECODE": "1"})
code7 = ("import sys; sys.path.insert(0, %r); import paths, os, json; "
         "print(json.dumps([paths.STATE_DIR, paths.state('ui_prefs.json'), paths.DEMO_ISOLATED]))") % T.SRC
p7 = subprocess.run([sys.executable, "-I", "-B", "-c", code7], env=env7, capture_output=True, text=True, timeout=60)
try:
    sd7, st7, iso7 = json.loads(p7.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    sd7, st7, iso7 = "", "", False
real7 = os.path.join(T.TMP, "state")
chk(iso7 and st7 == os.path.join(sd7, "ui_prefs.json") and not st7.startswith(real7 + os.sep), "R7 데모 격리 — paths.state 가 데모 임시 state 안",
    (sd7, st7, p7.stderr[-300:]))
T.finish()
