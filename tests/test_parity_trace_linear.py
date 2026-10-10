import sys

sys.dont_write_bytecode = True
import _harness as T

import random
import time

import evm_watch


def old_failed(ta, bad_list):
    return any(ta[:len(b9)] == b9 for b9 in bad_list)


def rows(paths):
    return [{"traceAddress": list(p), "error": "Reverted"} for p in paths]


rnd = random.Random(7)
same = True
for _ in range(3000):
    bad = [tuple(rnd.randint(0, 3) for _ in range(rnd.randint(0, 4))) for _ in range(rnd.randint(0, 6))]
    idx = evm_watch.trace_fail_index(rows(bad) + [{"traceAddress": [9], "type": "call"}])
    ta = tuple(rnd.randint(0, 3) for _ in range(rnd.randint(1, 5)))
    if old_failed(ta, bad) != evm_watch.trace_path_failed(idx, ta):
        same = False
        break
T.chk(same, "A1 종전 판정과 같은 결과(무작위 3,000)")
T.chk(evm_watch.trace_path_failed(evm_watch.trace_fail_index(rows([()])), (1, 2)) is True, "A2 루트 실패(빈 경로) = 모든 하위 실패")
T.chk(evm_watch.trace_path_failed(evm_watch.trace_fail_index(rows([(1, 3)])), (1, 2)) is False, "A3 형제 경로 실패는 무관")
T.chk(evm_watch.trace_path_failed(evm_watch.trace_fail_index(rows([(1, 2, 3)])), (1, 2)) is False, "A4 자손 실패는 조상을 실패로 만들지 않음")

res = [{"traceAddress": [1, i], "error": "Reverted"} for i in range(20000)]
t0 = time.time()
idx = evm_watch.trace_fail_index(res)
n = sum(1 for i in range(20000) if not evm_watch.trace_path_failed(idx, (2, i)))
dt = time.time() - t0
T.chk(dt < 2.0 and n == 20000, "B1 실패 경로 2만 × 지갑 이동 2만 = 2초 안 · 성공 2만", {"sec": round(dt, 2), "n": n})
deep = [0] * evm_watch.TRACE_DEPTH_MAX
t0 = time.time()
idx2 = evm_watch.trace_fail_index([{"traceAddress": [1], "error": "x"}])
f2 = evm_watch.trace_path_failed(idx2, tuple(deep))
idx3 = evm_watch.trace_fail_index([{"traceAddress": deep, "error": "x"}])
f3 = evm_watch.trace_path_failed(idx3, tuple(deep + [5]))
dt2 = time.time() - t0
T.chk(dt2 < 2.0 and f2 is False and f3 is True, "B2 EVM 상한 깊이(1024) 경로 판정 맞음 · 빠름", {"sec": round(dt2, 2), "f2": f2, "f3": f3})
for name, rows9 in (("깊이 1025", [{"traceAddress": [0] * (evm_watch.TRACE_DEPTH_MAX + 1), "error": "x"}]),
                    ("노드 상한 초과", [{"traceAddress": [i, j], "error": "x"} for i in range(1000) for j in range(201)])):
    try:
        evm_watch.trace_fail_index(rows9)
        r9 = False
    except ValueError:
        r9 = True
    T.chk(r9, f"B2b {name} = ValueError(호출부 형식 오류 · 메모리 증폭 없음)")
T.chk(len(evm_watch.trace_fail_index([{"traceAddress": [i, j], "error": "x"} for i in range(300) for j in range(300)])) == 300,
      "B2c 정상 크기(9만 노드)는 그대로 받음")
try:
    evm_watch.trace_fail_index([{"traceAddress": [[1], 2], "error": "x"}])
    raised = False
except TypeError:
    raised = True
T.chk(raised, "B3 해시 불가 traceAddress = TypeError(호출부 형식 오류)")
T.finish()
