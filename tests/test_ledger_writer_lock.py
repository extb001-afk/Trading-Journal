#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import signal  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
CFG = {"chains": {}, "wallets": [], "backfill_months": 5}
json.dump(CFG, open(os.path.join(T.TMP, "config.json"), "w"))
import config, paths  # noqa: E402
import core  # noqa: E402
import ledger_backup  # noqa: E402
import ledger_lock as LL  # noqa: E402

chk = T.chk
assert T.TMP in paths.STATE_DIR
DB = paths.DB_PATH
LOCKP = os.path.join(paths.STATE_DIR, "core_writer.lock")
core.Core(config.load_config()).conn.close()
PROCS = []


def spawn(code, *args, env=None):
    p = subprocess.Popen([sys.executable, "-c", code] + [str(a) for a in args], env=env or os.environ.copy(),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    PROCS.append(p)
    return p


def wait_file(path, sec=20.0):
    end = time.time() + sec
    while time.time() < end:
        if os.path.exists(path):
            return True
        time.sleep(0.05)
    return False


PROBE = ("import fcntl,os,sys\nfd=os.open(sys.argv[1],os.O_RDWR|os.O_CREAT,0o600)\n"
         "try:\n    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);print('got')\nexcept OSError:\n    print('busy')\n")


def probe(path=LOCKP):
    r = subprocess.run([sys.executable, "-I", "-c", PROBE, path], capture_output=True, text=True, timeout=20)
    return r.stdout.strip()


HOLDER = ("import os,sys,time\nsys.path.insert(0,sys.argv[1])\n"
          "if sys.argv[5]=='core':\n    import core\n    core.writer_lock(sys.argv[2])\n"
          "else:\n    import ledger_lock\n    ledger_lock.acquire(sys.argv[2], who='시험')\n"
          "open(sys.argv[3],'w').close()\n"
          "while not os.path.exists(sys.argv[4]):\n    time.sleep(0.05)\n")


def hold_in_child(db, tag, how="core"):
    ready, rel = os.path.join(T.TMP, f"ready_{tag}"), os.path.join(T.TMP, f"release_{tag}")
    p = spawn(HOLDER, T.SRC, db, ready, rel, how)
    ok = wait_file(ready)
    return p, rel, ok


def let_go(p, rel):
    open(rel, "w").close()
    try:
        p.wait(timeout=20)
    except subprocess.TimeoutExpired:
        p.kill()


def ledger_sig():
    h = hashlib.sha256()
    for sfx in ("", "-wal"):
        if os.path.exists(DB + sfx):
            h.update(open(DB + sfx, "rb").read())
    return h.hexdigest()


FAKE = os.path.join(T.TMP, "fakebin")
os.makedirs(FAKE, exist_ok=True)
with open(os.path.join(FAKE, "pm2"), "w") as fh:
    fh.write("#!/bin/sh\necho '[]'\n")
os.chmod(os.path.join(FAKE, "pm2"), 0o755)


def tool(name, *args, base=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_") or k.startswith("TJ_TEST_")}
    env.update(TJ_BASE=base or T.TMP, PM2_BIN=os.path.join(FAKE, "pm2"), PATH=FAKE + os.pathsep + env.get("PATH", ""),
               PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, os.path.join(T.ROOT, "tools", name)] + list(args), env=env, capture_output=True, text=True, timeout=180)
    return r.returncode, r.stdout + r.stderr


try:
    fd = LL.acquire(DB, who="시험")
    chk(LL.lock_path(DB) == LOCKP and (os.stat(LOCKP).st_mode & 0o777) == 0o600, "A1 잠금 파일 = 원장 폴더 core_writer.lock · 0600",
        (LL.lock_path(DB), oct(os.stat(LOCKP).st_mode & 0o777)))
    chk(not any("core_writer" in e for e in ledger_backup.prior_ledger_evidence(state_dir=paths.STATE_DIR, db_path=DB)),
        "A1 잠금 파일 ≠ 예전 원장 흔적(ledger.db.* 꼴 아님)")
    chk(probe() == "busy", "A2 쥔 동안 다른 프로세스 = 비차단 실패")
    fd2 = LL.acquire(DB, who="시험")
    LL.release(fd2)
    chk(fd2 == fd and probe() == "busy", "A3 같은 프로세스 중첩 = 같은 fd · 한 번 놓아도 아직 쥠", (fd, fd2))
    with LL.hold(DB, who="시험"):
        pass
    chk(probe() == "busy", "A3 중첩 with 문이 끝나도 바깥 잠금은 그대로")
    LL.release(fd)
    chk(probe() == "got", "A3 마지막 release = 풀림")

    p, rel, ok = hold_in_child(DB, "a4", how="tool")
    chk(ok, "A4 (전제) 다른 프로세스가 잠금을 쥠")
    try:
        LL.acquire(DB, who="시험 도구")
        busy = None
    except LL.LedgerBusy as e:
        busy = str(e)
    chk(busy is not None and isinstance(LL.LedgerBusy("x"), SystemExit) and "멈추고 다시" in busy and LOCKP in busy and "시험 도구" in busy,
        "A4 비차단 기본 = LedgerBusy(SystemExit · '라이브 tj-core 가 돌고 있음 — 멈추고 다시' · 잠금 경로 · 누가)", busy)
    t0 = time.monotonic()
    try:
        LL.acquire(DB, who="시험", wait=0.6)
        w9 = "got"
    except LL.LedgerBusy:
        w9 = "busy"
    chk(w9 == "busy" and time.monotonic() - t0 >= 0.55, "A5 wait=초 = 그만큼 기다린 뒤 LedgerBusy", (w9, time.monotonic() - t0))
    other = os.path.join(T.TMP, "shadow_x", "ledger.db")
    os.makedirs(os.path.dirname(other))
    with LL.hold(other, who="shadow"):
        chk(os.path.exists(os.path.join(T.TMP, "shadow_x", "core_writer.lock")), "A6 다른 원장 폴더(shadow) = 그 폴더 잠금 — 라이브가 잠겨도 잡힘")
    with LL.hold_if(False, DB, who="점검"):
        chk(True, "A7 hold_if(False) = 잠그지 않음(점검·읽기 전용 몸통)")
    let_go(p, rel)
    with LL.hold(DB, who="시험", wait=5):
        chk(probe() == "busy", "A8 쥔 쪽이 끝나면 이어받음(wait)")

    fd = LL.acquire(DB, who="시험")
    os.close(fd)
    fd = LL.acquire(DB, who="시험")
    chk(probe() == "busy", "A9 바깥에서 닫은 fd 기록 = 정리하고 새로 잡음")
    LL.release(fd)

    sw = os.path.join(T.TMP, "swap", "state")
    os.makedirs(sw)
    swdb = os.path.join(sw, "ledger.db")
    p, rel, ok = hold_in_child(swdb, "a10", how="tool")
    old_ino = os.stat(os.path.join(sw, "core_writer.lock")).st_ino
    waiter = spawn("import os,sys\nsys.path.insert(0,sys.argv[1])\nimport ledger_lock\nfd=ledger_lock.acquire(sys.argv[2], who='w', wait=True)\n"
                   "print('INO', os.fstat(fd).st_ino, os.stat(ledger_lock.lock_path(sys.argv[2])).st_ino, flush=True)\n", T.SRC, swdb)
    time.sleep(0.5)
    os.rename(sw, sw + "_old")
    os.makedirs(sw)
    open(os.path.join(sw, "core_writer.lock"), "w").close()
    new_ino = os.stat(os.path.join(sw, "core_writer.lock")).st_ino
    let_go(p, rel)
    out9 = waiter.communicate(timeout=20)[0]
    ino9 = [int(x) for x in out9.split()[1:3]] if out9.startswith("INO") else None
    chk(ok and ino9 is not None and ino9[0] == ino9[1] == new_ino != old_ino, "A10 폴더 교체 뒤 = 새 잠금 파일을 잡음(옛 inode 버림)",
        (out9, old_ino, new_ino))

    fd = LL.acquire(DB, who="시험")
    kid = spawn("import time\ntime.sleep(20)")
    LL.release(fd)
    chk(probe() == "got", "A11 자식 프로세스가 잠금 fd 를 물려받지 않음")
    kid.kill()

    sig0 = ledger_sig()
    p, rel, ok = hold_in_child(DB, "b", how="core")
    chk(ok and probe() == "busy", "B0 (전제) core.writer_lock(core.main 과 같은 함수)이 원장 잠금을 쥠")
    for name, args in (("exf_fix_place.py", ["--apply"]), ("exf_fut_place.py", ["--apply"]), ("latefix_move.py", ["--apply"]),
                       ("repair_own_overlap.py", ["--apply", "--force"])):
        if not os.path.isfile(os.path.join(T.ROOT, "tools", name)):
            continue
        rc, out = tool(name, *args)
        chk(rc == 1 and "원장 작성자 잠금" in out and "멈추고 다시" in out and "Traceback" not in out,
            f"B1 core 가 쥔 동안 {name} {' '.join(args)} = 즉시 거부(rc 1 · 안내 · 무한 대기 없음)", (rc, out[-400:]))
    chk(ledger_sig() == sig0, "B1 거부된 도구 = 원장 무변")
    for name in ("exf_fut_place.py", "latefix_move.py"):
        rc, out = tool(name)
        chk(rc == 0 and "원장 작성자 잠금" not in out, f"B2 점검(읽기 전용) {name} = 잠금 없이 그대로 돈다", (rc, out[-300:]))
    sys.path.insert(0, os.path.join(T.ROOT, "tools"))
    import ledger_restore as LR  # noqa: E402
    bk = os.path.join(paths.STATE_DIR, "backups", "ledger_20261001.db")
    os.makedirs(os.path.dirname(bk), exist_ok=True)
    LR.copy_ledger(DB, bk)
    try:
        LR.apply(LR.plan(bk, now=int(time.time())), proc_check=False, log=lambda *a: None)
        r9 = "applied"
    except LL.LedgerBusy as e:
        r9 = str(e)
    chk("원장 작성자 잠금" in r9 and not os.path.exists(os.path.join(paths.STATE_DIR, "restore.lock"))
        and not [f for f in os.listdir(paths.STATE_DIR) if f.startswith("ledger.db.pre_restore_")],
        "B3 복원(restore --apply · ps 확인을 못 하는 --no-proc-check 경로도) = 잠금에서 멈춤 · 원장·보존본·restore.lock 무변", r9)
    cp = os.path.join(T.TMP, "copy")
    os.makedirs(cp)
    shutil.copytree(paths.STATE_DIR, os.path.join(cp, "state"), ignore=shutil.ignore_patterns("core_writer.lock"))
    shutil.copy2(os.path.join(T.TMP, "config.json"), os.path.join(cp, "config.json"))
    shutil.copytree(os.path.join(T.TMP, "seed"), os.path.join(cp, "seed"))
    rc, out = tool("latefix_move.py", "--apply", base=cp)
    chk(rc == 0 and "원장 작성자 잠금" not in out, "B4 다른 state 폴더(사본)의 도구 --apply = 라이브 잠금에 안 막힘", (rc, out[-300:]))
    let_go(p, rel)
    rc, out = tool("exf_fix_place.py", "--apply")
    chk("원장 작성자 잠금" not in out and probe() == "got", "B5 core 가 끝나면 도구 --apply 가 잠금을 잡고 돈 뒤 놓음", (rc, out[-300:]))

    with LL.hold(DB, who="시험 도구"):
        cw = spawn("import sys\nsys.path.insert(0,sys.argv[1])\nimport core\ncore.writer_lock(sys.argv[2])\nprint('CORE_GOT', flush=True)\n", T.SRC, DB)
        seen9, end9 = [], time.time() + 60
        while time.time() < end9 and cw.poll() is None:
            ln9 = cw.stdout.readline()
            seen9.append(ln9)
            if "다른 원장 작성자" in ln9:
                break
        chk(any("다른 원장 작성자" in x for x in seen9) and cw.poll() is None, "B6 도구가 쥔 동안 core 입구 = 대기 로그 한 줄 뒤 기다림(끝나지 않음)", seen9[-3:])
    out9 = cw.communicate(timeout=30)[0]
    chk("CORE_GOT" in out9, "B6 도구가 놓으면 core 가 이어받음", out9[-300:])

    tree = os.path.join(T.TMP, "tree")
    shutil.copytree(T.SRC, os.path.join(tree, "src"), ignore=shutil.ignore_patterns("__pycache__"))
    marker = os.path.join(T.TMP, "stub_core_pid")
    with open(os.path.join(tree, "src", "core.py"), "w") as fh:
        fh.write("import os, sys, time\nsys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\nimport paths, runtime\nimport ledger_lock\n"
                 "paths.ensure_dirs()\nruntime.parent_watch_start(every=0.2)\nledger_lock.acquire(paths.DB_PATH, who='tj-core', wait=True)\n"
                 f"open({marker!r}, 'w').write(str(os.getpid()))\n"
                 "try:\n    while True:\n        time.sleep(0.2)\nexcept KeyboardInterrupt:\n    pass\n")
    renv = {k: v for k, v in os.environ.items() if not k.startswith("TJ_") or k.startswith("TJ_TEST_")}
    renv.update(TJ_BASE=T.TMP, TJ_RUNNER_CHECK_SEC="1", PYTHONDONTWRITEBYTECODE="1")
    runner = subprocess.Popen([sys.executable, os.path.join(tree, "src", "unit_runner.py"), "core"], env=renv,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    PROCS.append(runner)
    ok = wait_file(marker, 40)
    kid_pid = int(open(marker).read() or 0) if ok else 0
    chk(ok and kid_pid and probe() == "busy", "C1 (전제) 러너가 띄운 core 자식이 원장 잠금을 쥠", kid_pid)
    rc, out = tool("exf_fix_place.py", "--apply")
    chk(rc == 1 and "원장 작성자 잠금" in out, "C2 러너 자식 core 가 쥔 동안 도구 --apply = 즉시 거부", (rc, out[-300:]))
    os.kill(runner.pid, signal.SIGKILL)
    runner.wait(timeout=10)
    end9 = time.time() + 20
    gone = False
    while time.time() < end9:
        try:
            os.kill(kid_pid, 0)
        except ProcessLookupError:
            gone = True
            break
        time.sleep(0.1)
    chk(gone and probe() == "got", "C3 러너가 SIGKILL 로 죽으면 자식 core 가 부모 감시로 끝남 → 잠금 풀림(고아 작성자 없음)", (gone, kid_pid))
    if not gone and kid_pid:
        os.kill(kid_pid, signal.SIGKILL)

    TOOLS = os.path.join(T.ROOT, "tools")
    if os.path.isdir(TOOLS):
        def _src(n):
            return ast.unparse(n)

        def writes_ledger(tree9):
            hits = []
            for n in ast.walk(tree9):
                if not isinstance(n, ast.Call):
                    continue
                f = n.func
                name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
                kw = {k.arg: k.value for k in n.keywords if k.arg}
                a0 = _src(n.args[0]) if n.args else ""
                if name == "connect" and "DB_PATH" in a0:
                    uri = kw.get("uri")
                    ro = any(x in a0 for x in ("mode=ro", "immutable", "sqlite_ro_uri"))
                    if not (isinstance(uri, ast.Constant) and uri.value is True and ro):
                        hits.append(f"connect({a0[:40]})")
                elif name == "open_db" and not (isinstance(kw.get("readonly"), ast.Constant) and kw["readonly"].value is True):
                    hits.append(f"open_db({a0[:40]})")
                elif name == "Core" and (isinstance(f, ast.Name) or isinstance(f, ast.Attribute)):
                    hits.append("Core(...)")
                elif name == "swap_in":
                    hits.append("swap_in")
            return hits

        def uses_lock(tree9):
            return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
                       and n.func.value.id == "ledger_lock" and n.func.attr in ("hold", "hold_if", "acquire") for n in ast.walk(tree9))

        EXEMPT = {"prep_hotfix_h_caches.py": "읽기만 — 부속 파일(-wal·-shm) 유지용 연결로 SELECT 1 · 원장 사본 전용(라이브 경로 금지)"}
        writers, missing = [], []
        for fn in sorted(os.listdir(TOOLS)):
            if not fn.endswith(".py"):
                continue
            t9 = ast.parse(open(os.path.join(TOOLS, fn), encoding="utf-8").read())
            h9 = writes_ledger(t9)
            if h9:
                writers.append(fn)
                if not uses_lock(t9) and fn not in EXEMPT:
                    missing.append(f"{fn}: {h9[:3]}")
        chk(not missing, "D1 원장 쓰기 수단이 있는 tools/*.py = 전부 ledger_lock(hold·hold_if·acquire) 사용 — 새 도구도 잠금 없이 못 들어옴", missing)
        known = {"exf_fix_place.py", "exf_fut_place.py", "latefix_move.py", "ledger_restore.py", "rebuild.py", "rebuild2.py", "repair_own_overlap.py"}
        chk(known <= set(writers), "D2 (검사기 자체) 알려진 원장 작성 도구를 원장 쓰기로 알아봄(공개판 도구 7)", sorted(known - set(writers)))
        ro_only = {"verify_fixc.py", "offsite_backup.py", "negabs.py", "token_recheck.py", "negabs_1010.py", "token_recheck_1010.py", "fill_decimals.py", "replay_poison.py"}
        chk(not (ro_only & set(writers)), "D3 (검사기 자체) 읽기 전용·요청 파일 도구는 원장 작성자로 안 봄", sorted(ro_only & set(writers)))
    else:
        chk(True, "D 건너뜀 — tools/ 없는 배치")
finally:
    for p9 in PROCS:
        if p9.poll() is None:
            try:
                p9.kill()
                p9.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                pass

T.finish()
