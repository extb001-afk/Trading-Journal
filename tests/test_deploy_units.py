import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

LIB = os.path.join(T.ROOT, "tools", "deploy_lib.sh")
RB = os.path.join(T.ROOT, "tools", "rollback_hotfix_20260928t.sh")
ECO = os.path.join(T.ROOT, "public", "ecosystem.config.js")
if not (os.path.isfile(LIB) and os.path.isfile(RB)):
    print("SKIP tools/deploy_lib.sh·rollback 없음(공개판 — 배포 도구는 운영 저장소에만)")
    T.finish()
import chain_registry as reg  # noqa: E402

lib_src = open(LIB, encoding="utf-8").read()
rb_src = open(RB, encoding="utf-8").read()
OLD_STOP = "tj-web tj-exf tj-ex tj-sol tj-bsc tj-evm tj-review tj-alert tj-core"
OLD_START = "tj-core tj-evm tj-bsc tj-sol tj-ex tj-exf tj-alert tj-web tj-review"
OLD_WRITERS = "tj-core tj-evm tj-bsc tj-sol tj-ex tj-exf tj-tron tj-sui tj-ton tj-btc"
OLD_RB_STOP = "tj-web tj-tron tj-sui tj-ton tj-btc tj-exf tj-ex tj-sol tj-bsc tj-evm tj-review tj-alert tj-core"
OLD_RB_START = "tj-core tj-evm tj-bsc tj-sol tj-tron tj-sui tj-ton tj-btc tj-ex tj-exf tj-alert tj-web tj-review"


def block(text, var):
    m = re.search(r"^%s='\n(.*?)^'\n" % var, text, re.S | re.M)
    return m.group(1) if m else None


def rows(text, ncol):
    out = []
    for ln in (text or "").splitlines():
        body = ln.split("#", 1)[0].strip()
        if body:
            f = body.split()
            out.append(f if len(f) == ncol else None)
    return out


def bash(script, *args, env=None):
    p = subprocess.run(["/bin/bash", "-c", script, "_"] + list(args), capture_output=True, text=True, env=env)
    return p.returncode, p.stdout, p.stderr


tbl, rbt = block(lib_src, "DEPLOY_UNIT_TABLE"), block(rb_src, "RB_UNIT_TABLE")
T.chk(tbl is not None and tbl == rbt, "U1 유닛 표: deploy_lib 와 롤백 사본이 글자까지 같음(자족 사본 — 바꾸면 둘 다)")
TABLE = rows(tbl, 7)
T.chk(len(TABLE) == 15 and all(TABLE), "U1 유닛 표 15줄 · 줄마다 7칸", len(TABLE))
TABLE = [r for r in TABLE if r]
U = {r[0]: dict(zip(("entry", "runner", "kind", "need", "stop", "start"), r[1:])) for r in TABLE}
rc, out, err = bash('. "$1"; echo "W=$DEPLOY_WRITERS"; echo "C=$DEPLOY_CHAIN_UNITS"; echo "S=$(deploy_units stop "" req)"; '
                    'echo "A=$(deploy_units start "" req)"; echo "SA=$(deploy_units stop)"; echo "TA=$(deploy_units start)"; '
                    'deploy_units_check && echo CHECK_OK', LIB)
got = dict(ln.split("=", 1) for ln in out.splitlines() if "=" in ln)
T.chk(rc == 0 and got.get("W") == OLD_WRITERS and got.get("C") == "tj-tron tj-sui tj-ton tj-btc" and "CHECK_OK" in out,
      "U1 DEPLOY_WRITERS·DEPLOY_CHAIN_UNITS = 종전 문자열 그대로 · 표 해석 검사 통과", (got, err[-300:]))
T.chk(got.get("S") == OLD_STOP and got.get("A") == OLD_START, "U1 req 유닛 정지·기동 순서 = 종전 9유닛 STOP/START_ORDER 그대로", got)
T.chk(got.get("SA", "").split()[0:1] == ["tj-reload"] and got.get("TA", "").split()[-1:] == ["tj-reload"],
      "U1 tj-reload = 맨 먼저 정지 · 맨 끝 기동(배포 도중 재시작을 끼워 넣지 않게)", got)
rb_block = re.search(r"^RB_UNIT_TABLE='.*?^RB_START_ORDER=[^\n]*\n", rb_src, re.S | re.M)
rc, out, err = 1, "", "롤백 유닛 블록 못 찾음"
if rb_block:
    with open(os.path.join(T.TMP, "rb_block.sh"), "w", encoding="utf-8") as fh:
        fh.write(rb_block.group(0))
    rc, out, err = bash('. "$1"; echo "ALL=$ALL_UNITS"; echo "OPT=$RB_OPT_UNITS"; echo "RS=$RB_STOP_ORDER"; echo "RA=$RB_START_ORDER"',
                        os.path.join(T.TMP, "rb_block.sh"))
rg = dict(ln.split("=", 1) for ln in out.splitlines() if "=" in ln)
strip = lambda s: " ".join(u for u in s.split() if u != "tj-reload")  # noqa: E731
T.chk(rc == 0 and rg.get("ALL") == OLD_STOP and strip(rg.get("RS", "")) == OLD_RB_STOP and strip(rg.get("RA", "")) == OLD_RB_START
      and rg.get("OPT") == "tj-tron tj-sui tj-ton tj-btc tj-reload",
      "U1 롤백 ALL_UNITS·RB_STOP/START_ORDER = 종전 값(+ tj-reload) · RB_OPT_UNITS = 체인 4 + tj-reload", (rg, err[-300:]))
def fn_body(text, name):
    m = re.search(r"^%s\(\) \{[^\n]*\n(.*?)^\}\n" % re.escape(name), text, re.S | re.M)
    return m.group(1) if m else None


ofu_lib, ofu_rb = fn_body(lib_src, "open_files_under"), fn_body(rb_src, "rb_open_files_under")
T.chk(ofu_lib is not None and ofu_rb is not None and ofu_lib.replace("${PY:-$_DL_PY}", "$PY") == ofu_rb,
      "U1 열린 파일 조사: deploy_lib open_files_under 와 롤백 사본 rb_open_files_under 몸통이 같음(자족 사본 — 조사 실패 = rc 2 규약 포함)")
T.chk(ofu_rb is not None and ofu_rb.count("|| return 2") >= 2 and '"-d", "cwd"' in ofu_rb and "r.stderr.splitlines()" in ofu_rb,
      "U1 열린 파일 조사 실패(/proc 파이썬 실패·lsof 고장·lsof +D 가 대상 폴더 경고) = rc 2(빈 결과를 '열린 파일 0' 으로 읽지 않음)")
bad_tbl = tbl.replace("tj-sui      src/sui_watch.py              sui   chain   opt   4", "tj-sui      src/sui_watch.py              sui   chain   opt   3")
rc, out, err = bash('. "$1"; _deploy_units_check_of "$2"', LIB, bad_tbl)
T.chk(bad_tbl != tbl and rc != 0 and "해석 실패" in err, "U1 순위가 겹친 표 = 해석 검사 실패(배포·롤백이 시작 전에 멈춤)", err[-200:])

eco = open(ECO, encoding="utf-8").read()
runner_keys = re.findall(r"runner\('(\w+)'\)", eco)
direct = re.findall(r"direct\('(tj-[\w-]+)',\s*'([\w.]+)'\)", eco)
chain_js = re.findall(r"\['(\w+)',\s*'(\w+_watch\.py)'\]", eco)
ur = ast.parse(open(os.path.join(T.SRC, "unit_runner.py"), encoding="utf-8").read())
SCRIPTS = next(ast.literal_eval(n.value) for n in ur.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "SCRIPTS")
SCRIPTS.update({c: reg.SPECS[c].module + ".py" for c in reg.CHAINS})
bad = []
for k in runner_keys:
    u = U.get("tj-" + k)
    if not u or u["runner"] != k or u["entry"] != "src/" + SCRIPTS.get(k, "?"):
        bad.append(("runner", k, u))
for name, f in direct:
    u = U.get(name)
    if not u or u["runner"] != "-" or u["entry"] != "src/" + f:
        bad.append(("direct", name, u))
for k, f in chain_js:
    u = U.get("tj-" + k)
    if not u or u["runner"] != k or u["kind"] != "chain" or u["entry"] != "src/" + f:
        bad.append(("chain", k, u))
T.chk(runner_keys and direct and chain_js and not bad, "U2 유닛 표 ↔ public/ecosystem.config.js(러너 5 · 직접 · 체인 4) ↔ unit_runner.SCRIPTS 일치",
      {"bad": bad, "runner": runner_keys, "direct": direct, "chain": chain_js})
chains_tbl = sorted(n for n, u in U.items() if u["kind"] == "chain")
chains_reg = sorted(reg.SPECS[c].unit for c in reg.CHAINS)
T.chk(chains_tbl == chains_reg and all(U[reg.SPECS[c].unit]["entry"] == "src/%s.py" % reg.SPECS[c].module for c in reg.CHAINS)
      and all(U[n]["need"] == "opt" for n in chains_tbl),
      "U2 체인 유닛 = chain_registry(유닛 이름·수집기 모듈) · 전부 선택(opt — pm2 에 있고 online 일 때만)", (chains_tbl, chains_reg))
missing = [u["entry"] for u in U.values() if u["entry"] != "-" and not os.path.isfile(os.path.join(T.ROOT, u["entry"]))]
T.chk(not missing, "U2 파이썬 유닛 입구 파일이 저장소에 있음(tools/wallet_reload_watch.py 포함)", missing)
T.chk(U.get("tj-reload", {}).get("entry") == "tools/wallet_reload_watch.py" and U.get("tj-tunnel", {}).get("kind") == "ext"
      and U["tj-tunnel"]["stop"] == "-", "U2 tj-reload = tools 입구 · tj-tunnel = 파이썬 아님(배포 무접촉)", U.get("tj-tunnel"))

EDGE_LINES = [ln for ln in (block(lib_src, "DEPLOY_DYN_EDGES") or "").splitlines() if ln.split("#", 1)[0].strip()]
EDGES = [(ln.split("#", 1)[0].split(), "옛 판" in ln) for ln in EDGE_LINES]


def src_files():
    for f in sorted(os.listdir(T.SRC)):
        p = os.path.join(T.SRC, f)
        if f.endswith(".py"):
            yield f[:-3], p
        elif os.path.isdir(p) and f != "__pycache__":
            for r, _d, fs in os.walk(p):
                for g in sorted(fs):
                    if g.endswith(".py"):
                        yield f, os.path.join(r, g)


dyn_sites, spawn_sites = set(), set()
for mod, path in src_files():
    for n in ast.walk(ast.parse(open(path, encoding="utf-8").read(), filename=path)):
        if not isinstance(n, ast.Call):
            continue
        fn = n.func
        name = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else ""
        if name in ("import_module", "__import__") and n.args and not isinstance(n.args[0], ast.Constant):
            dyn_sites.add(mod)
        if name == "join":
            consts = [a.value for a in n.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            for c in consts:
                if c.endswith(".py"):
                    spawn_sites.add((mod, ("tools/" if "tools" in consts else "src/") + c))
imp_src = {e[0] for e, old in EDGES if e[1] == "import" and not old}
imp_old = {e[0] for e, old in EDGES if e[1] == "import" and old}
T.chk(dyn_sites == imp_src, "U3 동적 import 호출 모듈(상수 아님) = 간선 표 import 출발(옛 판 줄 제외) — 새 importlib 은 표에 등록해야 함",
      {"code": sorted(dyn_sites), "table": sorted(imp_src)})
T.chk(all(e[2] == "@chain" for e, _o in EDGES if e[1] == "import")
      and sorted(U[n]["entry"] for n in chains_tbl) == sorted("src/%s.py" % reg.SPECS[c].module for c in reg.CHAINS),
      "U3 import 간선 대상 @chain = 유닛 표 체인 입구 = chain_registry 수집기 모듈(core_recon 이 importlib 으로 부르는 것)")
src9 = open(os.path.join(T.SRC, "core_recon.py"), encoding="utf-8").read()
T.chk("importlib.import_module(chain_registry.spec(chain).module)" in src9, "U3 core_recon 의 실제 importlib 문자열 = chain_registry.spec(chain).module(간선 표가 가정한 꼴)")
sp_tbl = {(e[0], e[2]) for e, old in EDGES if e[1] in ("spawn", "run") and not old}
T.chk(spawn_sites == sp_tbl, "U3 하위 프로세스 대본 os.path.join(…, '<x>.py') = 간선 표 spawn·run(옛 판 제외) — 새 대본은 표에 등록해야 함",
      {"code": sorted(spawn_sites), "table": sorted(sp_tbl)})
T.chk(imp_old <= {"core"} and all(e[0] == "core" for e, old in EDGES if old), "U3 '옛 판' 줄 = core(리팩터 P4 전 판)만", sorted(imp_old))

W = tempfile.mkdtemp(prefix="tj_d1_units_")


def pm2file(name, states):
    p = os.path.join(W, name)
    json.dump([{"name": n, "pm2_env": {"status": s}} for n, s in states.items()], open(p, "w"))
    return p


ALLON = pm2file("all.json", {n: "online" for n in U})
PART = pm2file("part.json", dict({n: "online" for n in U if n not in ("tj-reload", "tj-ton", "tj-btc")}, **{"tj-sui": "stopped"}))


def derive(pm2, *files):
    rc, out, err = bash('. "$1"; PY=/usr/bin/python3; [ -x "$PY" ] || PY=python3; shift; deploy_derive_units "$@"', LIB, T.ROOT, pm2, *files)
    lines = out.splitlines()
    return rc, (lines[0].split() if lines else []), out, err


cases = [
    ("src/brokers/kis.py", ALLON, {"tj-web"}, set(), "하위 패키지 src/brokers → 그것을 싣는 tj-web(종전 = 0유닛)"),
    ("src/unit_runner.py", ALLON, {"tj-core", "tj-evm", "tj-sol", "tj-bsc", "tj-web", "tj-tron", "tj-sui", "tj-ton", "tj-btc"},
     {"tj-ex", "tj-exf", "tj-alert", "tj-review", "tj-reload"}, "unit_runner → 공개 구성이 러너로 감싸는 유닛 전부(종전 = 0유닛)"),
    ("src/tron_watch.py", ALLON, {"tj-tron", "tj-core"}, {"tj-sui", "tj-evm"}, "체인 수집기 → 그 유닛 + 동적 import 하는 tj-core"),
    ("tools/wallet_reload_watch.py", ALLON, {"tj-reload"}, {"tj-core", "tj-web"}, "tools 입구 → tj-reload"),
    ("tools/rebuild2.py", ALLON, {"tj-core"}, {"tj-web"}, "run 간선 대상(core_ext 가 부르는 대본) → tj-core"),
    ("src/search_worker.py", ALLON, {"tj-web"}, {"tj-core"}, "spawn 간선(검색 일꾼) → tj-web"),
]
for f, pm2, want, nope, why in cases:
    rc, got, out, err = derive(pm2, f)
    T.chk(rc == 0 and want <= set(got) and not (nope & set(got)), "U4 " + why, {"file": f, "got": got, "err": err[-300:]})
rc, got, out, err = derive(ALLON, "tools/pin_frozen_x.py")
T.chk(rc == 0 and got == [], "U4 1회 도구(tools/*.py · 입구·간선 대상 아님) = 유닛 없음(종전과 같음)", out[-200:])
rc, got, out, err = derive(PART, "src/paths.py")
T.chk(rc == 0 and "tj-tron" in got and not ({"tj-sui", "tj-ton", "tj-btc", "tj-reload"} & set(got))
      and re.search(r"tj-sui .*선택 유닛 — pm2 stopped", out) and re.search(r"tj-reload .*pm2 목록에 없음", out),
      "U4 선택 유닛 = pm2 online 인 것만(stopped·없음 = 무접촉 · 근거 줄에 표시) · req 9유닛은 종전처럼", {"got": got, "out": out[-600:]})
rc, got, out, err = derive(PART, "src/paths.py", "web/v2/app.js")
T.chk(rc == 0 and got[:2] == ["tj-web", "tj-tron"] and got[-1] == "tj-core", "U4 출력 순서 = 유닛 표 정지 순서", got)
WAITP = pm2file("wait.json", dict({n: "online" for n in U}, **{"tj-tron": "waiting restart"}))
rc, got, out, err = derive(WAITP, "src/tron_watch.py")
T.chk(rc != 0 and "전이 상태" in (out + err) and "tj-tron" in (out + err),
      "U4 바뀐 파일을 싣는 선택 유닛이 전이 상태(waiting restart) = 도출 실패(라이브 무변 — 곧 online 이 돼 스냅숏이 구 코드로 되살리는 혼합 창 막음)", (out + err)[-300:])
rc, got, out, err = derive(WAITP, "src/view_daily.py")
T.chk(rc == 0 and got == ["tj-web"], "U4 전이 상태 선택 유닛이 바뀐 파일을 안 실으면 = 상관없음(종전대로 진행)", got)
broken = os.path.join(W, "broken.json")
open(broken, "w").write("{not json")
rc, got, out, err = derive(broken, "src/paths.py")
T.chk(rc != 0 and "pm2 목록을 읽지 못함" in (out + err), "U4 pm2 목록 깨짐 = 도출 실패(배포 시작 전 중단 — 바뀐 체인 유닛을 옛 코드로 두지 않게)", (out + err)[-200:])
rc, out, err = bash('. "$1"; PY=/usr/bin/python3; [ -x "$PY" ] || PY=python3; DEPLOY_DYN_EDGES="core_recon teleport @chain"; '
                         'shift; deploy_derive_units "$@"', LIB, T.ROOT, ALLON, "src/paths.py")
T.chk(rc != 0 and "동적 간선 방식 오류" in (out + err), "U4 간선 표 형식 오류 = 도출 실패", (out + err)[-200:])

m = re.search(r"^deploy_snap_state\(\) \{.*?<<'PY'\n(.*?)^PY\n", lib_src, re.S | re.M)
SNAP_PY = m.group(1) if m else ""
T.chk("TMP_NAME = re.compile" in SNAP_PY and "VITAL = re.compile" in SNAP_PY, "U5 deploy_snap_state 필수만 복사 코드 글자 꺼냄(TMP_NAME·VITAL)")
PRELUDE = r'''
import os, shutil, sys
_SRC = sys.argv[1]   # 결함 주입(시험 전용): 이 상대 경로들은 복사 직전(T_VANISH_COPY)·목록 크기 재기 직전(T_VANISH_PLAN)에 원본을 지운다
_VC = set(x for x in os.environ.get("T_VANISH_COPY", "").split(",") if x)
_VP = set(x for x in os.environ.get("T_VANISH_PLAN", "").split(",") if x)
_c2, _ls = shutil.copy2, os.lstat
def _rel(p):
    try:
        return os.path.relpath(p, _SRC)   # 문자열로만(realpath·lexists 는 os.lstat 을 불러 재귀)
    except (TypeError, ValueError):
        return None
def _exists(p):
    try:
        _ls(p)
        return True
    except OSError:
        return False
def _copy2(s, d, *a, **k):
    if _rel(s) in _VC and _exists(s):
        os.remove(s)
    return _c2(s, d, *a, **k)
def _lstat(p, *a, **k):
    if isinstance(p, str) and _rel(p) in _VP and _exists(p):
        os.remove(p)
    return _ls(p, *a, **k)
shutil.copy2, os.lstat = _copy2, _lstat
'''
TMP_NAMES = [".tmp_x0nvpuov", ".tmp_cursor_evm_eth.json.k2j3h4.tmp", "cursor_evm_eth.json.tmp", "calcguard_core.json.tmp12345",
             "rabby_state.json.tmp4242", ".intent.ab12cd", ".tmp_set_abcd", ".tmp_oa_123_ab12", ".nft_123_ab12.tmp", "web_snap_last.bin.tmp",
             "inbox/evm/.tmp_seg.x1y2.tmp"]
KEEP_NAMES = ["cursor_evm_eth.json", "emitted_tron.json", "x.tmpl", "foo.tmp.json", "tmp_notes.json", "settings.json", "intent.json",
              "inbox/evm/000000001.jsonl", "inbox/evm/.queue.lock", "health_req.json", "alerts_cache.json"]


def mk_state(root):
    sd = os.path.join(root, "state")
    for n in TMP_NAMES + KEEP_NAMES:
        p = os.path.join(sd, n)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write("x")
    import sqlite3
    c = sqlite3.connect(os.path.join(sd, "ledger.db"))
    c.execute("CREATE TABLE m(k)")
    c.commit()
    c.close()
    return sd


def snap(tag, vanish_copy="", vanish_plan=""):
    root = os.path.join(W, tag)
    sd = mk_state(root)
    dst = os.path.join(root, "bk", "state_full")
    os.makedirs(os.path.dirname(dst))
    env = dict(os.environ, T_VANISH_COPY=vanish_copy, T_VANISH_PLAN=vanish_plan)
    p = subprocess.run([sys.executable, "-", sd, dst, os.path.dirname(dst), "state_full", "", "", "", str(10 ** 9)],
                       input=PRELUDE + SNAP_PY, capture_output=True, text=True, env=env)
    man = None
    if os.path.isfile(dst + ".essential.json"):
        man = json.load(open(dst + ".essential.json"))
    return p.returncode, p.stdout + p.stderr, dst, man


rc, out, dst, man = snap("v0")
T.chk(rc == 0 and not [n for n in TMP_NAMES if os.path.lexists(os.path.join(dst, n))]
      and all(os.path.isfile(os.path.join(dst, n)) for n in KEEP_NAMES),
      "U5 임시 이름(R2 꼴 .tmp_<대상>.<난수>.tmp · .tmp_… · ….tmp · ….tmp<pid> · .intent.…) 안 베낌 · 일반 이름(….tmpl·….tmp.json·tmp_…)은 베낌",
      {"rc": rc, "out": out[-400:], "copied_tmp": [n for n in TMP_NAMES if os.path.lexists(os.path.join(dst, n))],
       "missing": [n for n in KEEP_NAMES if not os.path.isfile(os.path.join(dst, n))]})
rc, out, dst, man = snap("v1", vanish_copy="health_req.json", vanish_plan="alerts_cache.json")
T.chk(rc == 0 and man and sorted(man.get("vanished") or []) == ["alerts_cache.json", "health_req.json"] and "사라진 비필수 파일 2개" in out
      and os.path.isfile(os.path.join(dst, "cursor_evm_eth.json")),
      "U5 복사 중·목록 중 사라진 비필수 파일 = 건너뜀(배포 계속) · 목록 vanished 에 기록", {"rc": rc, "out": out[-400:], "man": man})
rc, out, dst, man = snap("v2", vanish_copy="inbox/evm/000000001.jsonl")
T.chk(rc != 0 and not os.path.exists(dst) and not os.path.exists(dst + ".essential.json") and "필수만 스냅숏 실패" in out,
      "U5 복사 중 사라진 필수 파일(inbox 세그먼트) = 실패 · 부분 사본·목록 지움(종전처럼 중단)", out[-300:])
rc, out, dst, man = snap("v3", vanish_plan="cursor_evm_eth.json")
T.chk(rc != 0 and not os.path.exists(dst) and "필수 파일이 목록 중 사라짐" in out, "U5 목록 중 사라진 필수 파일(커서) = 실패", out[-300:])
rx = re.search(r'^TMP_NAME = re\.compile\(r"(.*?)"\)', SNAP_PY, re.M)
T.chk(bool(rx) and all(re.search(rx.group(1), os.path.basename(n)) for n in TMP_NAMES)
      and not any(re.search(rx.group(1), os.path.basename(n)) for n in KEEP_NAMES), "U5 TMP_NAME 정규식 대조표(걸러야 할 꼴 전부 · 일반 이름 0)")
shutil.rmtree(W, ignore_errors=True)
T.finish()
