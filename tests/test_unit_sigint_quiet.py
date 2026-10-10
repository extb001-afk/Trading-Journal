#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import re
import signal
import subprocess
import time

chk = T.chk


def run_unit(fname, unit):
    base = os.path.join(T.TMP, "u_" + unit)
    os.makedirs(os.path.join(base, "state"), exist_ok=True)
    json.dump({"chains": {}, "wallets": []}, open(os.path.join(base, "config.json"), "w"))
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_")}
    env.update(TJ_BASE=base, PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8",
               HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9", http_proxy="http://127.0.0.1:9", https_proxy="http://127.0.0.1:9")
    p = subprocess.Popen([sys.executable, os.path.join(T.SRC, fname)], env=env, cwd=T.TMP, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, encoding="utf-8", errors="replace")
    beat = os.path.join(base, "state", f"runner_{unit}.json")
    t0 = time.time()
    while time.time() - t0 < 60 and p.poll() is None and not os.path.exists(beat):
        time.sleep(0.2)
    time.sleep(2.0)
    alive = p.poll() is None
    if alive:
        p.send_signal(signal.SIGINT)
    t1 = time.time()
    try:
        out, err = p.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        return {"alive": alive, "timeout": True, "rc": p.returncode, "out": out[-600:], "err": err[-900:], "sec": 20}
    return {"alive": alive, "timeout": False, "rc": p.returncode, "out": out[-600:], "err": err[-900:], "sec": round(time.time() - t1, 1)}


for name, fname, unit in (("S1 업비트(tj-ex)", "upbit_link.py", "ex"), ("S2 해외거래소(tj-exf)", "ex_foreign.py", "exf")):
    r = run_unit(fname, unit)
    both = r["out"] + r["err"]
    chk(r["alive"] and not r["timeout"] and r["rc"] == 0 and "Traceback" not in both and "KeyboardInterrupt" not in both
        and "정지 신호(SIGINT) — 종료" in both,
        f"{name} SIGINT = 트레이스백 없이 '정지 신호(SIGINT) — 종료' 한 줄 · 코드 0 · 20초 안 종료(종전: KeyboardInterrupt 트레이스백)", r)

eco = os.path.join(T.ROOT, "public", "ecosystem.config.js")
eco = eco if os.path.isfile(eco) else os.path.join(T.ROOT, "ecosystem.config.js")
direct = re.findall(r"direct\('[^']+',\s*'([a-z_]+\.py)'\)", open(eco, encoding="utf-8").read()) if os.path.isfile(eco) else []
children = ["core.py", "evm_watch.py", "sol_watch.py", "bsc_watch.py", "web.py"]
miss = []
for fn in sorted(set(direct) | set(children)):
    src = open(os.path.join(T.SRC, fn), encoding="utf-8").read()
    tail = src[src.rfind('if __name__ == "__main__":'):]
    if "except KeyboardInterrupt" not in tail:
        miss.append(fn)
chk(len(direct) >= 3 and not miss, f"S3 유닛 진입부 전부 KeyboardInterrupt 한 줄 규칙(직접 {len(direct)}개 + 러너 자식 {len(children)}개)", {"direct": direct, "miss": miss})
T.finish()
