#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import os  # noqa: E402
import stat  # noqa: E402

import paths  # noqa: E402

R = os.path.join(T.TMP, "s22perm")


def mode(p):
    return stat.S_IMODE(os.lstat(p).st_mode)


def setup(name):
    b = os.path.join(R, name)
    st = os.path.join(b, "state")
    ib = os.path.join(st, "inbox")
    os.makedirs(ib)
    env = os.path.join(b, ".env")
    paths.STATE_DIR, paths.INBOX_DIR, paths.ENV_PATH = st, ib, env
    return b, st, ib, env


def run():
    try:
        paths.ensure_dirs()
        return None
    except Exception as e:   # noqa: BLE001
        return f"{type(e).__name__}: {e}"


S0 = (paths.STATE_DIR, paths.INBOX_DIR, paths.ENV_PATH)

b, st, ib, env = setup("p1")
os.chmod(st, 0o755)
os.chmod(ib, 0o755)
with open(env, "w") as f:
    f.write("K=v\n")
os.chmod(env, 0o644)
inner = os.path.join(st, "a.json")
with open(inner, "w") as f:
    f.write("{}")
os.chmod(inner, 0o644)
e = run()
T.chk(e is None and mode(st) == 0o700 and mode(ib) == 0o700, "P1 state/·inbox/ 755 → 700", [e, oct(mode(st)), oct(mode(ib))])
T.chk(mode(env) == 0o600 and open(env).read() == "K=v\n", "P1 .env 644 → 600(내용 그대로)", oct(mode(env)))
T.chk(mode(inner) == 0o644 and open(inner).read() == "{}", "P5 폴더 안 파일 = 그대로(재귀 chmod 없음)", oct(mode(inner)))

e = run()
T.chk(e is None and (mode(st), mode(ib), mode(env)) == (0o700, 0o700, 0o600), "P2 이미 700·600 = 그대로", [e, oct(mode(st)), oct(mode(env))])

b, st, ib, env = setup("p3")
os.rmdir(ib)
os.rmdir(st)
e = run()
T.chk(e is None and os.path.isdir(ib) and not os.path.exists(env) and mode(st) == 0o700, "P3 .env 없음 = 오류 없음 · 폴더 새로 만듦(700)", [e, os.path.isdir(ib)])

b = os.path.join(R, "p4")
real_st = os.path.join(R, "p4_real_state")
os.makedirs(os.path.join(real_st, "inbox"))
os.makedirs(b)
os.chmod(real_st, 0o755)
os.chmod(os.path.join(real_st, "inbox"), 0o755)
st = os.path.join(b, "state")
os.symlink(real_st, st)
real_env = os.path.join(R, "p4_real.env")
with open(real_env, "w") as f:
    f.write("K=v\n")
os.chmod(real_env, 0o644)
env = os.path.join(b, ".env")
os.symlink(real_env, env)
paths.STATE_DIR, paths.INBOX_DIR, paths.ENV_PATH = st, os.path.join(st, "inbox"), env
e = run()
T.chk(e is None and mode(real_st) == 0o755 and stat.S_IMODE(os.stat(real_env).st_mode) == 0o644,
      "P4 심볼릭 링크 = 대상 권한 안 건드림(state 링크 · .env 링크)", [e, oct(mode(real_st)), oct(stat.S_IMODE(os.stat(real_env).st_mode))])

paths.STATE_DIR, paths.INBOX_DIR, paths.ENV_PATH = S0
T.finish()
