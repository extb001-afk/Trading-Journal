#!/usr/bin/env python3
import os
import re
import subprocess
import sys
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _root():
    env = os.environ.get("TJ_TEST_ROOT")
    for c in ([env] if env else [os.path.join(HERE, ".."), os.path.join(HERE, "..", "..")]):
        if c and os.path.isfile(os.path.join(c, "src", "common.py")):
            return os.path.abspath(c)
    return None


def _snapshot(root):
    seen = set()
    for top in [os.path.join(root, d) for d in ("src", "web", "tools")] + [HERE]:
        for dp, _dn, fns in os.walk(top):
            for fn in fns:
                seen.add(os.path.join(dp, fn))
    return seen


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    verbose = "-v" in sys.argv[1:]
    root = _root()
    if not root:
        print("src/common.py 를 찾지 못했어요 — TJ_TEST_ROOT=<src 가 든 폴더>")
        return 1
    files = sorted(f for f in os.listdir(HERE) if f.startswith("test_") and f.endswith(".py") and (not args or any(a in f for a in args)))
    if not files:
        print("돌릴 시험이 없어요")
        return 1
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_") or k.startswith("TJ_TEST_")}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    before = _snapshot(root)
    rows, bad = [], 0
    print(f"소스: {os.path.join(root, 'src')} · 파이썬 {sys.version.split()[0]} · 시험 {len(files)}개\n")
    for f in files:
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
        ok = rc == 0 and m and nfail == 0
        bad += not ok
        rows.append((f, npass, nfail, dt, ok))
        print(f"{'통과' if ok else '실패'}  {f}  {npass} PASS · {nfail} FAIL · {dt:.1f}초" + ("" if ok else f" · 종료 코드 {rc}"))
        if verbose:
            print(out)
        elif not ok:
            lines = out.splitlines()
            fails = [ln for ln in lines if ln.startswith("FAIL ")]
            print("\n".join(fails[:40] or lines[-40:]))
    left = sorted(_snapshot(root) - before)
    if left:
        bad += 1
        print("\n실패  시험이 소스 폴더에 파일을 남김: " + ", ".join(os.path.relpath(x, root) for x in left[:20]))
    tp, tf = sum(r[1] for r in rows), sum(r[2] for r in rows)
    print(f"\n합계: 시험 파일 {len(rows)}개 · {tp} PASS · {tf} FAIL · " + ("전부 통과" if not bad else f"실패 {bad}"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
