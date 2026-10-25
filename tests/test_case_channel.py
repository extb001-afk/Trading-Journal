#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True

import json  # noqa: E402
import os  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

if len(sys.argv) > 2 and sys.argv[1] == "--case":
    import threading  # noqa: E402
    import _harness as T  # noqa: E402

    case = sys.argv[2]
    out = {"total": 1010.0, "expect": 1010.0, "net": [], "case": case}
    if case == "tail":
        T.case_emit(out)
        sys.stdout.write("INFO 배경 읽기 끝\n")
        sys.stdout.write("CASE " + json.dumps(out) + "INFO 섞인 꼬리\n")
    elif case == "noisy":
        stop = threading.Event()

        def noise():
            while not stop.is_set():
                sys.stdout.write("x")

        th = threading.Thread(target=noise, daemon=True)
        th.start()
        T.case_emit(out)
        stop.set()
        th.join()
    elif case == "late_crash":
        T.case_emit(out)
        raise SystemExit("합성 자식 뒤늦은 실패 TKJ")
    elif case == "crash":
        print("CASE " + json.dumps(out), flush=True)
        raise SystemExit("합성 자식 실패 TKJ")
    sys.exit(0)

import _harness as T  # noqa: E402

chk = T.chk
ME = [sys.executable, os.path.abspath(__file__), "--case"]
WANT = {"total": 1010.0, "expect": 1010.0, "net": []}

line = "CASE " + json.dumps(WANT) + "INFO 섞인 꼬리"
try:
    json.loads(line[5:])
    err = None
except ValueError as e:
    err = str(e)
chk(err is not None and err.startswith("Extra data") and "char %d" % len(json.dumps(WANT)) in err,
    "C1 종전 꼴(JSON 뒤 같은 줄에 다른 글) = Extra data(종전 stdout 해석이 멈추던 자리 = JSON 끝)", err)
r = T.case_run(ME + ["tail"], cwd=HERE)
chk(r == dict(WANT, case="tail"), "C2 같은 줄에 꼬리가 붙어도 결과 = 결과 파일 그대로", r)
bad = [r9 for r9 in (T.case_run(ME + ["noisy"], cwd=HERE) for _ in range(30)) if r9 != dict(WANT, case="noisy")]
chk(not bad, "C3 배경 스레드가 stdout 에 계속 쓰는 동안 30번 = 모두 정확", bad[:2])
r = T.case_run(ME + ["crash"], cwd=HERE)
chk(set(r) == {"_err", "stdout", "stderr"} and "종료값 1" in r["_err"] and "TKJ" in r["stderr"] and "CASE" in r["stdout"],
    "C4 결과 전에 죽음 = 실패(종료값·결과 파일 상태·stderr 꼬리) · stdout 'CASE' 줄로 성공 처리 안 함", r)
r = T.case_run(ME + ["late_crash"], cwd=HERE)
chk(set(r) == {"_err", "result", "stdout", "stderr"} and "종료값 1" in r["_err"] and r["result"] == dict(WANT, case="late_crash"),
    "C4 결과를 낸 뒤 비정상 종료 = 실패(결과는 진단으로만)", r)
T.finish()
