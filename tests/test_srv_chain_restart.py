import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

SCRIPT = os.path.join(T.ROOT, "tools", "srv_chain_restart.sh")
if not os.path.isfile(SCRIPT):
    print("SKIP tools/srv_chain_restart.sh 없음(공개판 — 운영 도구는 운영 저장소에만)")
    T.finish()

chk = T.chk
D = tempfile.mkdtemp(prefix="tj_chainrs_", dir=T.TMP)
RUNS = os.path.join(D, "srv_chain_restart.sh")
shutil.copyfile(SCRIPT, RUNS)
BIN = os.path.join(D, "bin")
os.makedirs(BIN)
CALLS = os.path.join(D, "pm2.calls")
with open(os.path.join(BIN, "pm2"), "w", encoding="utf-8") as f:
    f.write("""#!/bin/bash
echo "$*" >> "%s"
if [ "$1" = jlist ] && [ -n "${TJ_TEST_JLIST_BAD:-}" ]; then
  n=$(grep -c '^jlist' "%s"); [ "$n" = "$TJ_TEST_JLIST_BAD" ] && { echo 'not json'; exit 0; }
fi
if [ "$1" = jlist ]; then
  echo '[{"name":"tj-core","pm2_env":{"status":"online","restart_time":0}},{"name":"tj-tron","pm2_env":{"status":"online","restart_time":1}},{"name":"tj-sui","pm2_env":{"status":"online","restart_time":1}},{"name":"tj-ton","pm2_env":{"status":"online","restart_time":1}}]'
fi
if [ "$1" = restart ] && [ "${TJ_TEST_PM2_FAIL:-}" = "$2" ]; then exit 1; fi
exit 0
""" % (CALLS, CALLS))
os.chmod(os.path.join(BIN, "pm2"), 0o755)
D1_LOG = ("[done] 선택 유닛(체인·tj-reload): 새 코드로 기동 = tj-tron · ★post 의 srv_chain_restart.sh·pm2 restart tj-reload 불필요(D1)★\n"
          "== 핫픽스 t 완료 TS=20990101_000000_1 · 정지 1s\n")
OLD_LOG = "[verify] …\n== 핫픽스 t 완료 TS=20990101_000000_2 · 정지 1s\n"
RUN_LOG = "[backup] 잠깐 정지 …\n[install] …\n"


def run(log_text, force=False, fail=None, bad_jlist=None):
    home = os.path.join(D, "home")
    shutil.rmtree(home, ignore_errors=True)
    os.makedirs(home)
    if log_text is not None:
        with open(os.path.join(home, "deploy_s22.log"), "w", encoding="utf-8") as f:
            f.write(log_text)
    if os.path.exists(CALLS):
        os.remove(CALLS)
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_")}
    env.update(HOME=home, PATH=BIN + os.pathsep + env.get("PATH", "/usr/bin:/bin"), TJ_CHAIN_RESTART_WAIT="0")
    if force:
        env["TJ_CHAIN_RESTART_FORCE"] = "1"
    if fail:
        env["TJ_TEST_PM2_FAIL"] = fail
    if bad_jlist:
        env["TJ_TEST_JLIST_BAD"] = str(bad_jlist)
    p = subprocess.run(["/bin/bash", RUNS], capture_output=True, text=True, env=env, timeout=60)
    calls = open(CALLS, encoding="utf-8").read().splitlines() if os.path.exists(CALLS) else []
    return p.returncode, p.stdout + p.stderr, [c.split()[1] for c in calls if c.startswith("restart ")]


try:
    rc, out, rs = run(D1_LOG)
    chk(rc == 0 and rs == [] and "건너뜀" in out, "C1 D1 배포 로그('불필요(D1)') = 재시작 0 · rc 0 · 건너뜀 안내", [rc, rs, out[-300:]])
    rc, out, rs = run(D1_LOG, force=True)
    chk(rc == 0 and rs == ["tj-tron", "tj-sui", "tj-ton"] and "없음 tj-btc" in out and "가드 넘김" in out,
        "C2 TJ_CHAIN_RESTART_FORCE=1 = 있는 체인 유닛만 재시작 · 없는 유닛 '없음'", [rc, rs, out[-300:]])
    rc, out, rs = run(OLD_LOG)
    chk(rc == 0 and rs == ["tj-tron", "tj-sui", "tj-ton"], "C3 D1 전 배포 로그(완료 줄만) = 종전처럼 재시작", [rc, rs, out[-300:]])
    rc, out, rs = run(RUN_LOG)
    chk(rc == 3 and rs == [] and "완료 줄 없음" in out, "C4 완료 줄 없는 로그(진행 중·실패 흔적) = 재시작 0 · rc 3", [rc, rs, out[-300:]])
    rc, out, rs = run(None)
    chk(rc == 0 and rs == ["tj-tron", "tj-sui", "tj-ton"] and "배포 로그 없음" in out, "C5 로그 없음 = 종전처럼 재시작(안내 줄)", [rc, rs, out[-300:]])
    rc, out, rs = run(OLD_LOG, fail="tj-sui")
    chk(rc == 1 and rs == ["tj-tron", "tj-sui", "tj-ton"] and "restart 실패 tj-sui" in out and "restart tj-ton" in out,
        "C6 재시작 하나 실패 = 나머지는 계속 · rc 1(성공으로 안 보임)", [rc, rs, out[-300:]])
    rc, out, rs = run(OLD_LOG, bad_jlist=2)
    chk(rc == 1 and rs == ["tj-tron", "tj-ton"] and "목록 해석 실패 tj-sui" in out and "없음 tj-sui" not in out,
        "C7 목록 조회가 한 번 깨짐 = '없음' 으로 치지 않음 · 나머지는 계속 · rc 1", [rc, rs, out[-300:]])
    rc, out, rs = run(OLD_LOG, bad_jlist=5)
    chk(rc == 1 and rs == ["tj-tron", "tj-sui", "tj-ton"], "C8 마지막 상태 조회가 깨짐 = rc 1", [rc, rs, out[-300:]])
    r9 = subprocess.run(["/bin/bash", "-n", RUNS], capture_output=True, text=True)
    chk(r9.returncode == 0, "bash -n 문법", r9.stderr)
finally:
    shutil.rmtree(D, ignore_errors=True)
T.finish()
