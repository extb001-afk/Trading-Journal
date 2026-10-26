#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402

SETUP = next((p for p in (os.path.join(T.ROOT, "tools", "setup.sh"), os.path.join(T.ROOT, "public", "tools", "setup.sh")) if os.path.isfile(p)), None)
bash = shutil.which("bash")


def mk_root(name):
    r = os.path.join(T.TMP, name)
    os.makedirs(os.path.join(r, "tools"))
    os.makedirs(os.path.join(r, "src"))
    shutil.copyfile(SETUP, os.path.join(r, "tools", "setup.sh"))
    with open(os.path.join(r, "src", "tj_pth_probe.py"), "w", encoding="utf-8") as f:
        f.write("OK = 1\n")
    for fn, body in (("config.example.json", "{}\n"), (".env.example", "")):
        with open(os.path.join(r, fn), "w", encoding="utf-8") as f:
            f.write(body)
    return os.path.realpath(r)


def env_for(ub):
    shim = os.path.join(T.TMP, "shim")
    os.makedirs(shim, exist_ok=True)
    with open(os.path.join(shim, "pm2"), "w", encoding="utf-8") as f:
        f.write('#!/bin/sh\necho "[]"\n')
    os.chmod(os.path.join(shim, "pm2"), 0o755)
    e = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    e.update(HOME=os.path.join(T.TMP, "home"), PYTHONUSERBASE=ub, PATH=shim + os.pathsep + e.get("PATH", ""), TJ_PYTHON=sys.executable)
    os.makedirs(e["HOME"], exist_ok=True)
    return e


def run(root, env, *args):
    return subprocess.run([bash, os.path.join(root, "tools", "setup.sh"), *args], capture_output=True, text=True, timeout=120, env=env)


if not (SETUP and bash):
    print("bash·setup.sh 없음 — 건너뜀")
else:
    R = mk_root("r1")
    E = env_for(os.path.join(T.TMP, "ub1"))
    h = run(R, E, "--help")
    T.chk(h.returncode == 0 and "--dev-path" in h.stdout, "[1] --help 에 --dev-path 안내", h.stdout[-300:])
    u = run(R, E, "--nope")
    T.chk(u.returncode == 2, "[1] 모르는 옵션 = rc 2", u.returncode)
    q = subprocess.run([sys.executable, "-c", "import site; print(site.getusersitepackages() if site.ENABLE_USER_SITE else '')"],
                       capture_output=True, text=True, env=E, timeout=60)
    SITE = q.stdout.strip()
    if not SITE:
        r0 = run(R, E, "--dev-path")
        T.chk(r0.returncode != 0 and "site-packages" in r0.stdout, "[2] 사용자 site 를 안 읽는 파이썬 = 안내하고 멈춤", r0.stdout[-300:])
    else:
        PTH = os.path.join(SITE, "tj.pth")
        r1 = run(R, E, "--dev-path")
        body = open(PTH, encoding="utf-8").read() if os.path.isfile(PTH) else None
        T.chk(r1.returncode == 0 and body == os.path.join(R, "src") + "\n", "[2] 처음 = tj.pth 한 줄(<뿌리>/src)", (r1.returncode, body, r1.stdout[-300:]))
        imp = subprocess.run([sys.executable, "-c", "import tj_pth_probe; print(tj_pth_probe.OK)"], capture_output=True, text=True, env=E, cwd=T.TMP, timeout=60)
        T.chk(imp.stdout.strip() == "1", "[2] 그 파이썬이 src 모듈을 import(.pth 가 먹음)", (imp.stdout, imp.stderr[-200:]))
        m1 = os.stat(PTH).st_mtime_ns
        r2 = run(R, E, "--dev-path")
        T.chk(r2.returncode == 0 and "그대로" in r2.stdout and os.stat(PTH).st_mtime_ns == m1, "[3] 다시 = 그대로(무변)", r2.stdout[-300:])
        with open(PTH, "w", encoding="utf-8") as f:
            f.write("/elsewhere/src\n")
        r3 = run(R, E, "--dev-path")
        T.chk(r3.returncode == 0 and "건드리지 않음" in r3.stdout and open(PTH, encoding="utf-8").read() == "/elsewhere/src\n",
              "[4] 다른 곳을 가리키는 tj.pth = 건드리지 않음", r3.stdout[-300:])
        os.remove(PTH)
        os.symlink(os.path.join(SITE, "gone.txt"), PTH)
        r6 = run(R, E, "--dev-path")
        T.chk(r6.returncode == 0 and os.path.islink(PTH) and not os.path.exists(os.path.join(SITE, "gone.txt")),
              "[6] 끊긴 심볼릭 링크 tj.pth = 따라가 만들지 않음(건드리지 않음)", r6.stdout[-300:])
        os.remove(PTH)
        try:
            RN = mk_root("r\nimport os #")
        except OSError:
            RN = None
        if RN:
            rn = run(RN, E, "--dev-path")
            T.chk(rn.returncode != 0 and not os.path.lexists(PTH), "[7] 경로에 줄바꿈 = 멈춤(.pth 에 실행 줄을 쓰지 않음)", rn.stdout[-300:])
        R2 = mk_root("r2")
        E2 = env_for(os.path.join(T.TMP, "ub2"))
        SITE2 = subprocess.run([sys.executable, "-c", "import site; print(site.getusersitepackages())"], capture_output=True, text=True, env=E2, timeout=60).stdout.strip()
        r5 = run(R2, E2)
        T.chk(r5.returncode == 0 and not os.path.exists(os.path.join(SITE2, "tj.pth")) and os.path.isfile(os.path.join(R2, "config.json")),
              "[5] 보통 실행 = tj.pth 안 만듦(설치 0)", (r5.returncode, r5.stdout[-300:]))
T.finish()
