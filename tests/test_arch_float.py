#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _arch as A  # noqa: E402

import _arch_py_facts as F  # noqa: E402
import _arch_py_metrics as M  # noqa: E402

T = A.T

_SAMPLE = '''
total = 0.0
total += 1.0
def f(d, a, b, xs):
    d["x"] += float(a)
    d["y"] -= float(a) * b
    d["z"] += float(a) + float(b)
    t = 0.0
    t += b / float(a)
    t += a
    t *= float(b)
    t = t + float(a)
    t += int(a)
    for x in xs:
        t += float(x)
    return t
class K:
    s = 0.0
    s += float("1")
    def g(self, a):
        self.s += float(a); self.s += float(a)
        self.s += (lambda v: float(v))(a)
'''

fx = F.facts(_SAMPLE, "accounting_sample")
sc = fx.get("scopes", {})
got = {q: v.get("faug", 0) for q, v in sc.items() if v.get("faug")}
want = {"f": 6, "K.<body>": 1, "K.g": 3}
T.chk(got == want, "정의: += · -= 의 값 식 안 float(…) 호출 개수(한 식에 둘 = 2 · += a · *= float · t = t + float · += int 는 셈 밖 · 범위 = 함수·클래스 몸통)",
      {"got": got, "want": want})
T.chk(M.FLOAT_ACC_PREFIX == "accounting_", "세는 모듈 = accounting_*(원가 엔진) — 규칙 파일이 아닌 코드 상수(목록을 줄여 느슨해지는 길 없음)",
      M.FLOAT_ACC_PREFIX)

st = A.state()
if st.metrics is None:
    T.chk(True, "공개판 배치 — 규칙·기준선 파일 없음 · 지금 소스 확인 건너뜀")
else:
    units = st.metrics.units.get("float.acc_aug", [])
    hit = sorted({u["m"] for u in units if u["v"]})
    T.chk(hit and all(m.startswith("accounting_") for m in hit), "지금 센 모듈 = accounting_* 만(%d개)" % len(hit), hit)
    other = sorted(m for m, x in st.index.items() if not m.startswith("accounting_")
                   and any(s.get("faug") for s in (x.get("scopes") or {}).values()))
    T.chk(all(not u["v"] for u in units if u["m"] in other),
          "accounting_* 밖의 같은 꼴(%d모듈)은 값 0 — 화면·요약 모듈의 float 합은 이 규칙 밖" % len(other), other[:10])
T.finish()
