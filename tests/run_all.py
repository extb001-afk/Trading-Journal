#!/usr/bin/env python3
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SLOW_FIRST = ("test_rpc_fresh_lanes", "test_alch_internal")
SOLO = ("test_unit_sigint_quiet",)


def _root():
    env = os.environ.get("TJ_TEST_ROOT")
    for c in ([env] if env else [os.path.join(HERE, ".."), os.path.join(HERE, "..", "..")]):
        if c and os.path.isfile(os.path.join(c, "src", "version.py")):
            return os.path.abspath(c)
    return None


def _snapshot(root):
    seen = set()
    for top in [os.path.join(root, d) for d in ("src", "web", "tools")] + [HERE]:
        for dp, _dn, fns in os.walk(top):
            for fn in fns:
                seen.add(os.path.join(dp, fn))
    return seen


def _parse(argv):
    args, verbose, jobs = [], False, os.environ.get("TJ_TEST_JOBS") or "1"
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-j", "--jobs"):
            if i + 1 >= len(argv):
                raise ValueError(f"{a} 뒤에 숫자가 필요해요")
            jobs, i = argv[i + 1], i + 1
        elif a.startswith("--jobs="):
            jobs = a.split("=", 1)[1]
        elif a.startswith("-j") and len(a) > 2:
            jobs = a[2:]
        elif a == "-v":
            verbose = True
        elif not a.startswith("-"):
            args.append(a)
        i += 1
    try:
        n = int(jobs)
    except ValueError:
        raise ValueError(f"동시 수가 숫자가 아니에요: {jobs!r}")
    if n < 1:
        raise ValueError(f"동시 수는 1 이상이어야 해요: {n}")
    return args, verbose, n


def _run_one(f, env):
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, os.path.join(HERE, f)], env=env, cwd=HERE, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=900)
        out, rc = p.stdout + p.stderr, p.returncode
    except subprocess.TimeoutExpired as e:
        out, rc = (e.stdout or "") if isinstance(e.stdout, str) else "", "시간 초과"
    dt = time.time() - t0
    m = re.findall(r"결과: (\d+) PASS · (\d+) FAIL", out)
    npass, nfail = (int(m[-1][0]), int(m[-1][1])) if m else (0, 0)
    ok = bool(rc == 0 and m and nfail == 0)
    return f, npass, nfail, dt, ok, rc, out


def _report(res, verbose):
    f, npass, nfail, dt, ok, rc, out = res
    print(f"{'통과' if ok else '실패'}  {f}  {npass} PASS · {nfail} FAIL · {dt:.1f}초" + ("" if ok else f" · 종료 코드 {rc}"))
    if verbose:
        print(out)
    elif not ok:
        lines = out.splitlines()
        fails = [ln for ln in lines if ln.startswith("FAIL ")]
        print("\n".join(fails[:40] or lines[-40:]))
    sys.stdout.flush()


def _priority(f):
    slow = next((i for i, p in enumerate(SLOW_FIRST) if f.startswith(p)), len(SLOW_FIRST))
    try:
        size = os.path.getsize(os.path.join(HERE, f))
    except OSError:
        size = 0
    return slow, -size, f


def _run_parallel(files, env, jobs, verbose):
    solo = [f for f in files if f.startswith(SOLO)] if SOLO else []
    pool_files = sorted((f for f in files if f not in solo), key=_priority)
    done, nxt = {}, 0

    def flush():
        nonlocal nxt
        while nxt < len(files) and files[nxt] in done:
            _report(done[files[nxt]], verbose)
            nxt += 1

    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = {ex.submit(_run_one, f, env): f for f in pool_files}
        for fu in as_completed(futs):
            r = fu.result()
            done[r[0]] = r
            flush()
    for f in sorted(solo):
        done[f] = _run_one(f, env)
        flush()
    flush()
    return [done[f] for f in files]


def main():
    try:
        args, verbose, jobs = _parse(sys.argv[1:])
    except ValueError as e:
        print(e)
        return 1
    root = _root()
    if not root:
        print("src/version.py(뿌리 표식)를 찾지 못했어요 — TJ_TEST_ROOT=<src 가 든 폴더>")
        return 1
    files = sorted(f for f in os.listdir(HERE) if f.startswith("test_") and f.endswith(".py") and (not args or any(a in f for a in args)))
    if not files:
        print("돌릴 시험이 없어요")
        return 1
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_") or k.startswith("TJ_TEST_")}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    before = _snapshot(root)
    jobs = min(jobs, len(files))
    t_all = time.time()
    print(f"소스: {os.path.join(root, 'src')} · 파이썬 {sys.version.split()[0]} · 시험 {len(files)}개"
          + (f" · 동시 {jobs}개" if jobs > 1 else "") + "\n")
    sys.stdout.flush()
    if jobs > 1:
        results = _run_parallel(files, env, jobs, verbose)
    else:
        results = []
        for f in files:
            r = _run_one(f, env)
            results.append(r)
            _report(r, verbose)
    rows = [r[:5] for r in results]
    bad = sum(1 for r in rows if not r[4])
    left = sorted(_snapshot(root) - before)
    if left:
        bad += 1
        print("\n실패  시험이 소스 폴더에 파일을 남김: " + ", ".join(os.path.relpath(x, root) for x in left[:20]))
        if jobs > 1:
            print("      동시 실행이라 어느 시험이 남겼는지 특정할 수 없어요 — -j 1 로 다시 돌려 확인하세요")
    if jobs > 1:
        print(f"\n전체 {time.time() - t_all:.1f}초(동시 {jobs}개)")
    tp, tf = sum(r[1] for r in rows), sum(r[2] for r in rows)
    print(f"\n합계: 시험 파일 {len(rows)}개 · {tp} PASS · {tf} FAIL · " + ("전부 통과" if not bad else f"실패 {bad}"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
