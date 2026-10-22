#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _sec_lint as L  # noqa: E402
import _harness as T  # noqa: E402

import ast  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import stat  # noqa: E402
import time  # noqa: E402

t0 = time.time()
OLD_UMASK = os.umask(0o022)
B = T.TMP
SECRET = re.compile(r"^(?:\.env|config\.json|state/setup_token|state/auth[\w.]*|state/backups/.+)$")
SECRET_DIRS = {"state", "state/inbox", "state/backups", "state/backups/files_<day>", "state/backups/offsite"}
STEPS = []


def step(name, fn):
    try:
        fn()
        STEPS.append((name, None))
    except Exception as e:   # noqa: BLE001
        STEPS.append((name, "%s: %s" % (type(e).__name__, str(e)[:200])))


with open(os.path.join(T.ROOT, "config.example.json"), encoding="utf-8") as f:
    CFG = json.load(f)
CFG["wallets"], CFG["exchange_addresses"] = [], []
CFG["web"] = {"port": 8023, "bind": "loopback"}
cfg_path = os.path.join(B, "config.json")
with open(cfg_path, "w", encoding="utf-8") as f:
    json.dump(CFG, f)
with open(os.path.join(B, ".env"), "w") as f:
    f.write("TJ_TG_CHAT=1\n")

import paths, statefile  # noqa: E402
import settings_store as ss  # noqa: E402

step("기동: config 조이기(web 기동과 같음)", lambda: paths.tighten_config_mode())
step("기동: ensure_dirs(state·inbox 0700 · .env 0600)", paths.ensure_dirs)
step(".env 쓰기(설정 화면)", lambda: ss.write_env({"TJ_ETHERSCAN_KEY": "Q" * 34}))
step("설치 CSRF 토큰", ss.csrf_token)
step("settings.json", lambda: ss.update_settings(currency="KRW"))
step("config.json 저장(설정 화면)", lambda: ss.write_config_raw(dict(CFG, backfill_months=5)))


def _login():
    import login_auth as LA
    LA.init({"web": {}})
    rec = LA.set_password("Perm-Audit-Horse-9917", iters=200_000)
    LA.new_session(rec)
    LA.DEVICES.issue("perm-audit-pg", "perm-audit-sg")


step("로그인(내부 토큰·설정 코드·비밀번호·세션·등록 기기)", _login)


def _ledger():
    import db as dbm
    c = dbm.open_db(paths.DB_PATH)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('perm_audit', '1')")
    c.commit()
    c.close()


step("원장 만들기(db.open_db + WAL)", _ledger)


def _writer_lock():
    import core
    core.writer_lock(paths.DB_PATH)


step("원장 작성자 잠금(core.writer_lock)", _writer_lock)
step("상태 JSON(atomic_write_json)", lambda: statefile.atomic_write_json(os.path.join(paths.STATE_DIR, "perm_generic.json"), {"a": 1}))
step("상태 JSONL(append_durable_jsonl)", lambda: statefile.append_durable_jsonl(os.path.join(paths.STATE_DIR, "perm_generic.jsonl"), {"a": 1}))


def _backups():
    import ledger_backup
    ledger_backup.run_once(paths.DB_PATH)
    day = time.strftime("%Y%m%d", time.gmtime(time.time() + 9 * 3600))
    statefile.atomic_write_json(os.path.join(paths.STATE_DIR, "day_memos.json"), {"2026-10-01": {}})
    ledger_backup.backup_files(day, paths.STATE_DIR, paths.CONFIG_PATH)


step("정기 백업(run_once) · 원장 밖 사본(backup_files)", _backups)


def _offsite():
    p = os.path.join(T.ROOT, "tools", "offsite_backup.py")
    if not os.path.isfile(p):
        return
    spec = importlib.util.spec_from_file_location("offsite_backup_perm", p)
    ob = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ob)
    man = ob.build(check=True, log=lambda *a: None)
    ob.write_status({"last_ok": int(time.time()), "stamp": man["stamp"]})


step("offsite 묶음(tools/offsite_backup.build · 상태)", _offsite)


def _caches():
    import flow_trace
    import rabby
    import xchain_match
    rabby._write(os.path.join(paths.STATE_DIR, "rabby_perm.json"), {"a": 1})
    flow_trace.save_cache(paths.STATE_DIR, {"v": 1})
    xchain_match._save(paths.STATE_DIR, {"v": 1})


step("캐시(rabby · flow_trace · xchain_match)", _caches)
os.umask(OLD_UMASK)
for name, err in STEPS:
    T.chk(err is None, "실행: %s" % name, err)


def norm(rp):
    rp = re.sub(r"tjoff_\d{8}_\d{4}", "<stamp>", rp)
    return re.sub(r"(?<!\d)\d{8}(?!\d)", "<day>", rp)


seen = {}
for dp, dns, fns in os.walk(B):
    for n in dns + fns:
        p = os.path.join(dp, n)
        rp = os.path.relpath(p, B).replace(os.sep, "/")
        if rp.startswith(("_", "tj_appjs")) or "/.tmp" in rp or rp.endswith(".pyc"):
            continue
        st = os.lstat(p)
        if stat.S_ISLNK(st.st_mode):
            continue
        k = norm(rp) + ("/" if stat.S_ISDIR(st.st_mode) else "")
        seen[k] = seen.get(k, 0) | stat.S_IMODE(st.st_mode)

print("[2] 절대 규칙")
for k, mode in sorted(seen.items()):
    key = k.rstrip("/")
    if k.endswith("/") and key in SECRET_DIRS:
        T.chk(mode == 0o700, "폴더 %s = 0700" % key, oct(mode))
    elif not k.endswith("/") and SECRET.match(key):
        T.chk(not (mode & 0o077), "비밀 파일 %s = 그룹·다른 사용자 비트 0" % key, oct(mode))
for must in (".env", "config.json", "state/setup_token", "state/auth.json", "state/auth_sessions.json", "state/auth_devices.json", "state/auth_internal_token",
             "state/"):
    T.chk(must in seen, "만들어짐: %s" % must, sorted(seen)[:40])

print("[1] 파일별 기대 권한 표")
TNAME = "perm_table"
L.check_base_ref(T)
base = L.load_baseline(TNAME)
cur = {"mode": {k: v for k, v in seen.items()}}
ref0, rb0, _why0 = L.base_ref_baseline(TNAME) if base is None else (None, None, "")
if base is None and rb0 is not None:
    T.chk(False, "표 sec_%s.jsonl 이 없어짐(기준 커밋 %s 에는 있음) — 지우지 말고 --update-lower 로만" % (TNAME, ref0[:10]))
elif base is None:
    if L.BASELINE_INIT:
        L.save_baseline(TNAME, {"_doc": "G1 test_perm_audit 파일별 기대 권한 표 — n = 지금 권한(8진수의 10진 값 · 예 384 = 0o600). "
                                         "표에 없는 비트가 생기면 FAIL · 조이면 --update-lower", "metrics": cur})
        print("(기준선 새로 만듦: arch_baseline/sec_%s.jsonl)" % TNAME)
    else:
        print("(기준선 sec_%s.jsonl 없음 — 표 비교 건너뜀 · 공개 배치면 정상)" % TNAME)
else:
    tbl = base["metrics"].get("mode", {})
    ref, rb, why = L.base_ref_baseline(TNAME)
    if rb is not None:
        rt = rb["metrics"].get("mode", {})
        loose = ["%s: 표 %s > 기준 커밋 %s" % (k, oct(v), oct(rt[k])) for k, v in tbl.items() if k in rt and v & ~rt[k]]
        T.chk(not loose, "[perm_table] 표가 기준 커밋(%s)보다 느슨해지지 않음" % ref[:10], loose)
    else:
        print("(표: 기준 커밋 비교 건너뜀 — %s)" % why)
    worse, new, tighter, gone = [], [], [], []
    for k, mode in sorted(seen.items()):
        if k not in tbl:
            new.append("%s %s" % (k, oct(mode)))
        elif mode & ~tbl[k]:
            worse.append("%s: 지금 %s · 표 %s" % (k, oct(mode), oct(tbl[k])))
        elif mode != tbl[k]:
            tighter.append(k)
    gone = sorted(k for k in tbl if k not in seen)
    T.chk(not worse, "표보다 느슨해진 파일·폴더 0", worse)
    secure_new = [x for x in new if not (int(x.rsplit(" ", 1)[1], 8) & 0o077) or x.split(" ", 1)[0].endswith(".lock")]
    loose_new = [x for x in new if x not in secure_new]
    T.chk(not loose_new, "표에 없는 새 파일 중 그룹·남 비트 있는 데이터 파일 0(있으면 0600 으로 만들거나 표에 손으로 등록하고 이유를 남기세요)", loose_new)
    if secure_new and not L.UPDATE_LOWER:
        print("안내 [perm_table] 표에 없는 새 파일(본인만 권한·잠금 파일): %s — `--update-lower` 로 표에 넣으세요" % secure_new[:8])
        if L.STALE_FAIL:
            T.chk(False, "[perm_table] 표에 없는 새 파일 — --update-lower(TJ_ARCH_STALE_FAIL=1)", secure_new)
    if tighter or gone:
        print("안내 [perm_table] 조여짐: %s · 이번 실행에서 안 생김: %s" % (tighter[:8], gone[:8]))
        if L.STALE_FAIL and not L.UPDATE_LOWER:
            T.chk(False, "[perm_table] 표가 지금보다 느슨함 — --update-lower(TJ_ARCH_STALE_FAIL=1)", {"tighter": tighter, "gone": gone})
    if L.UPDATE_LOWER and not worse and not loose_new:
        out = {k: v for k, v in seen.items()}
        L.save_baseline(TNAME, {"_doc": base["_doc"], "metrics": {"mode": out}})
        print("(표 갱신: 조여진 권한·새 본인만 파일 반영)")
    loose_now = sorted("%s %s" % (k, oct(v)) for k, v in seen.items() if not k.endswith("/") and v & 0o077)
    print("  지금 그룹·남 읽기 가능한 파일(state 0700 폴더 안): %s" % ", ".join(loose_now))

print("[3] 비밀 파일 쓰기 자리(정적)")
SEC_TRIG = (".env", "config.json", "setup_token", "auth", "CONFIG_PATH", "ENV_PATH", "TOKEN_PATH", "INTERNAL_PATH", "SETUP_CODE_PATH", "SESS_PATH")
IX = L.PyIndex(T.ROOT, ("src", "tools"), only=lambda n, txt: any(x in txt for x in SEC_TRIG))
SECRET_NAMES = {".env", "config.json", "setup_token", "auth.json", "auth_sessions.json", "auth_devices.json", "auth_internal_token", "auth_setup_code"}
RANK = {"0600": 0, "preserve": 1, "umask": 2, "loose": 3}
pol, smp = {}, {}
for mod, t in sorted(IX.mods.items()):
    rp = IX.path[mod]
    L.kw_to_pos(t["tree"])
    for fi in L.func_table(t["tree"]) + L.module_fis(t["tree"]):
        nodes = fi.nodes
        txt = " ".join(ast.unparse(n) for n in nodes if isinstance(n, ast.Call) and L.call_name(n) in ("os.fchmod", "os.chmod", "os.stat", "tempfile.mkstemp"))
        def _arg(call, pos, kw):
            if len(call.args) > pos:
                return call.args[pos]
            return next((k.value for k in call.keywords if k.arg == kw), None)

        def _pol(m9, dflt):
            if m9 is None:
                return dflt
            if isinstance(m9, ast.Constant) and isinstance(m9.value, int):
                return "loose" if m9.value & 0o077 else "0600"
            return "preserve"
        for n in nodes:
            if not isinstance(n, ast.Call):
                continue
            nm = L.call_name(n)
            tgt, p9 = None, None
            if nm.endswith("atomic_write_json") and n.args:
                tgt, p9 = n.args[0], "0600"
            elif nm.endswith("atomic_write_text") and n.args:
                tgt, p9 = n.args[0], _pol(_arg(n, 2, "mode"), "0600")
            elif nm == "os.open" and len(n.args) >= 2 and "O_CREAT" in ast.unparse(n.args[1]):
                tgt, p9 = n.args[0], _pol(_arg(n, 2, "mode"), "umask")
            elif nm == "open" and n.args and isinstance(_arg(n, 1, "mode"), ast.Constant) and any(c in str(_arg(n, 1, "mode").value) for c in "wax"):
                tgt, p9 = n.args[0], "umask"
            elif nm == "os.replace" and len(n.args) == 2:
                tgt = n.args[1]
                p9 = "0600" if ("mkstemp" in txt or "0o600" in txt) else ("preserve" if "os.stat" in txt or "st_mode" in txt else "umask")
            elif nm == "shutil.copy2" and len(n.args) == 2:
                tgt, p9 = n.args[1], "preserve"
            if tgt is None:
                continue
            b = (L.resolve_fi(IX, mod, fi, tgt) or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
            if b in SECRET_NAMES:
                key = "%s::%s" % (rp, fi.qual)
                pol[key] = max(pol.get(key, 0), RANK[p9])
                smp.setdefault(key, []).append("%s:%d %s → %s (%s)" % (rp, n.lineno, nm, b, p9))
print("  비밀 파일 쓰기 자리 %d · umask/loose %d" % (len(pol), sum(1 for v in pol.values() if v >= 2)))
T.chk(len(pol) >= 5, "비밀 파일 쓰기 자리를 찾음(조사기 고장 아님)", sorted(pol))
L.ratchet(T, "perm_static", {"secret_writer_policy": pol},
          "G1 비밀 파일 쓰기 자리 권한 정책(n = 0 0600 · 1 preserve(기존 권한 유지) · 2 umask(기본) · 3 loose) — 늘면 FAIL",
          hints={"secret_writer_policy": "비밀 파일을 기본 권한(umask)으로 씀 — os.open(…, 0o600)·mkstemp·statefile.atomic_write_json 으로"},
          samples={"secret_writer_policy": smp})
print("(시간 %.1f초)" % (time.time() - t0))
T.finish()
