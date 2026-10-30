#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
import time

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

LIB = os.path.join(T.ROOT, "tools", "deploy_lib.sh")
if not os.path.isfile(LIB):
    print("SKIP tools/deploy_lib.sh 없음(공개판)")
    T.finish()
BASH = "/bin/bash" if os.path.exists("/bin/bash") else shutil.which("bash")
chk = T.chk
W1 = "0x" + "d1" * 20
W2 = "0x" + "d2" * 20
LIVE = os.path.join(T.TMP, "live")
BK = os.path.join(T.TMP, "bk")
shutil.copytree(T.SRC, os.path.join(LIVE, "src"), ignore=shutil.ignore_patterns("__pycache__"))
os.makedirs(os.path.join(LIVE, "state", "health"))
os.makedirs(BK)
CFG = {"chains": {"eth": {"blockscout": "https://eth.invalid", "rpcs": ["https://eth-rpc.invalid"]},
                  "base": {"discovery": "rpc", "rpcs": ["https://base-rpc.invalid"]}},
       "wallets": [{"type": "evm", "chain": "eth", "address": W1, "label": "가"},
                   {"type": "evm", "chain": "base", "address": W1, "label": "가"}],
       "chain_sweep": {"enabled": True, "auto_enable": True}}


def wj(rel, obj):
    p = os.path.join(LIVE, rel)
    with open(p, "w", encoding="utf-8") as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj))


def hb(unit, srcs, t):
    wj(os.path.join("state", "health", unit + ".json"),
       {"schema": 1, "unit": unit, "ts": t, "started": t, "ok": True,
        "sources": {k: {"kind": "rpc", "ok": True, "last_cycle_ts": t, "last_success_ts": t, "consecutive_failures": 0} for k in srcs}})


def sh(fn, *args):
    env = {k: v for k, v in os.environ.items() if k not in ("TJ_CONFIG", "pm_id")}
    env.update(PY=sys.executable, TJ_BASE=LIVE)
    r = subprocess.run([BASH, "-c", '. "$0"; ' + fn + ' "$@"', LIB] + list(args), capture_output=True, text=True, env=env, timeout=180)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def files(top):
    return sorted(os.path.relpath(os.path.join(dp, f), top) for dp, _d, fs in os.walk(top) for f in fs)


def prestale():
    p = os.path.join(BK, "hb_prestale.json")
    return json.load(open(p)) if os.path.exists(p) else None


wj("config.json", CFG)
t0 = int(time.time()) - 600
hb("evm", ["eth", "base", "zerog", "zerog:rpclog"], t0)
hb("bsc", ["bsc"], t0)
before = files(LIVE)
rc, out = sh("health_baseline", LIVE, BK)
chk(rc == 0 and prestale() == {"evm": ["zerog", "zerog:rpclog"]},
    "P 배포 전 {eth, base, zerog(+rpclog)} · 설정 {eth, base} → hb_prestale {evm: [zerog, zerog:rpclog]}", (rc, prestale(), out[-400:]))
chk("설정에서 빠진 evm 소스" in out and "zerog" in out, "P 사람이 읽을 한 줄", out[-400:])
chk(files(LIVE) == before, "P 라이브 폴더에 새 파일 0(__pycache__·상태 파일 없음)", sorted(set(files(LIVE)) - set(before))[:5])

W2CUR = {"_rpc_v": 3, "_start": 100, W2: 120}
wj(os.path.join("state", "chain_activity.json"), {"version": 1, "pairs": {f"zerog:{W2}": {"active": True, "since_block": None}}})
wj(os.path.join("state", "chain_backfill_speed.json"),
   {"version": 1, "chains": {"zerog": {"getLogsSpan": 1000, "blocksPerSec": 1.0, "windowCalls": 999999, "autoOk": False}}})
wj(os.path.join("state", "cursor_evm_zerog.json"), W2CUR)
wj("config.json", dict(CFG, wallets=CFG["wallets"] + [{"type": "evm", "chain": "eth", "address": W2, "label": "나"}]))
rc, out = sh("health_baseline", LIVE, BK)
chk(rc == 0 and prestale() == {"evm": []}, "P 활동 게이트가 켠 수집 중 체인(커서 · autoOk 거짓) = 빠진 소스 아님", (prestale(), out[-300:]))
wj("config.json", "{깨진")
os.remove(os.path.join(BK, "hb_prestale.json"))
rc, out = sh("health_baseline", LIVE, BK)
chk(rc == 0 and prestale() is None and "계산 실패" in out, "P 설정 손상 = hb_prestale 없음 + 한 줄(종전 규칙)", out[-300:])
wj("config.json", CFG)
os.remove(os.path.join(LIVE, "state", "cursor_evm_zerog.json"))
rc, out = sh("health_baseline", LIVE, BK)
chk(prestale() == {"evm": ["zerog", "zerog:rpclog"]}, "P 되돌림(정상 설정) = 다시 계산", prestale())

t_up = int(time.time()) - 60
hb("evm", ["eth", "base"], t_up + 10)
rc, out = sh("hb_sources_ok", LIVE, BK, "evm", str(t_up))
chk(rc == 0, "V 새 하트비트 {eth, base} · 빠진 소스 zerog = 통과", rc)
rc, out = sh("hb_sources_report", LIVE, BK, "evm", str(t_up))
chk(rc == 0 and "설정에서 빠진 소스(배포 전 프로세스가 재시작 전이라 남아 있던 것) — 제외: zerog, zerog:rpclog" in out,
    "V report 에 '설정에서 빠진 소스 — 제외' 줄", out[-400:])
shutil.copy(os.path.join(BK, "hb_prestale.json"), os.path.join(T.TMP, "prestale.keep"))
os.remove(os.path.join(BK, "hb_prestale.json"))
rc, out = sh("hb_sources_report", LIVE, BK, "evm", str(t_up))
chk(rc == 1 and "기존 소스 zerog" in out, "V hb_prestale 없음 = 종전처럼 실패(zerog 기다림)", out[-400:])
shutil.copy(os.path.join(T.TMP, "prestale.keep"), os.path.join(BK, "hb_prestale.json"))
hb("evm", ["eth"], t_up + 10)
rc, out = sh("hb_sources_report", LIVE, BK, "evm", str(t_up))
chk(rc == 1 and "기존 소스 base" in out, "V 새 하트비트 {eth}(base 빠짐 · base 는 설정에 있음) = 실패", out[-400:])
d = json.load(open(os.path.join(LIVE, "state", "health", "evm.json")))
d["sources"] = {k: dict(d["sources"]["eth"]) for k in ("eth", "base", "zerog")}
d["sources"]["zerog"].update(last_success_ts=t_up - 100, ok=False, consecutive_failures=3)
wj(os.path.join("state", "health", "evm.json"), d)
rc, out = sh("hb_sources_ok", LIVE, BK, "evm", str(t_up))
chk(rc == 1, "V 빠진 소스가 새 하트비트에 있고 기동 뒤 성공 없음 = 실패(기존 소스처럼 성공 요구)", rc)
with open(os.path.join(BK, "hb_presources.json")) as f:
    pres = json.load(f)
pres["bsc"] = ["bsc", "zerog"]
with open(os.path.join(BK, "hb_presources.json"), "w") as f:
    json.dump(pres, f)
hb("bsc", ["bsc"], t_up + 10)
rc, out = sh("hb_sources_ok", LIVE, BK, "bsc", str(t_up))
chk(rc == 1, "V bsc 판정은 hb_prestale 무관(종전 그대로)", rc)

T.finish()
