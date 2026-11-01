#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402

import calcguard as CG  # noqa: E402
import paths  # noqa: E402

chk = T.chk
os.environ.pop("TJ_STRICT", None)

try:
    raise ValueError("데이터 이상")
except Exception as e:
    CG.swallowed("t:g1", e)
try:
    undefined_name_xyz  # noqa: F821
except Exception as e:
    CG.swallowed("t:g1", e)
s = CG.snapshot().get("t:g1") or {}
chk(s.get("n") == 2 and s.get("types") == {"ValueError": 1, "NameError": 1} and s.get("bug") == 1, "G1 라이브 = 자리별 횟수·종류·코드 실수 꼴 수 기록(계속 진행)", s)

CG.flush(now=CG.time.time() + 10 ** 6)
p = CG.path_of()
d = json.load(open(p)) if os.path.exists(p) else {}
chk(p.startswith(paths.STATE_DIR) and d.get("v") == 1 and "t:g1" in (d.get("sites") or {}), "G2 저장 파일(state 안 · 자리 기록)", (p, d))
CG.flush_as("build")
chk(os.path.exists(CG.path_of(suffix="build")) or not CG._DIRTY[0], "G2 빌드 자식용 파일 이름(_build) — 바뀐 것 없으면 안 씀", CG.path_of(suffix="build"))

os.environ["TJ_STRICT"] = "1"
caught = []
for exc in (NameError("x"), UnboundLocalError("y"), ImportError("z"), AssertionError("w"), ValueError("v"), KeyError("k"), TypeError("t")):
    try:
        try:
            raise exc
        except Exception as e:
            CG.swallowed("t:g3", e)
        caught.append((type(exc).__name__, "삼킴"))
    except Exception as e2:   # noqa: BLE001
        caught.append((type(e2).__name__, "던짐"))
os.environ.pop("TJ_STRICT", None)
chk(caught == [("NameError", "던짐"), ("UnboundLocalError", "던짐"), ("ImportError", "던짐"), ("AssertionError", "던짐"),
               ("ValueError", "삼킴"), ("KeyError", "삼킴"), ("TypeError", "삼킴")], "G3 엄격 모드 = 코드 실수 꼴만 던짐", caught)

class _Bad(Exception):
    def __str__(self):
        raise RuntimeError("str 실패")


try:
    try:
        raise _Bad()
    except Exception as e:
        CG.swallowed(None, e)
    ok4 = True
except Exception:   # noqa: BLE001
    ok4 = False
chk(ok4, "G4 기록 실패 = 조용히(계산 계속)", ok4)

os.environ.pop("TJ_STRICT", None)
try:
    raise ImportError("선택 모듈 없음")
except Exception as e:
    CG.swallowed("t:g4b", e)
chk((CG.snapshot().get("t:g4b") or {}).get("bug") == 0, "G4b 라이브 = ImportError 는 빨강 수에 안 셈", CG.snapshot().get("t:g4b"))

import health  # noqa: E402
sd5 = os.path.join(T.TMP, "cg5")
os.makedirs(sd5, exist_ok=True)
now5 = 2_000_000_000
json.dump({"v": 1, "proc": "web", "sites": {"view_b_replay:_build_replay": {"n": 3, "last": now5 - 60, "bug": 2, "why": "NameError: x"},
                                             "pricing:p": {"n": 9, "last": now5 - 60, "bug": 0, "why": "ValueError: v"}}},
          open(os.path.join(sd5, "calcguard_web.json"), "w"))
c5 = {c["cid"]: c for c in health.collect_calcguard(now5, sd5)}
chk(c5.get("calc:bug", {}).get("level") == "crit" and c5["calc:bug"].get("notify") is True and "view_b_replay:_build_replay" in c5["calc:bug"]["detail"]
    and c5.get("calc:swallow", {}).get("level") == "ok", "G5 상태 패널 = 코드 실수 꼴 빨강·알림 · 데이터 탓 꼴 정보", c5)
c5b = {c["cid"]: c for c in health.collect_calcguard(now5 + 2 * 86400, sd5)}
chk(c5b.get("calc:bug", {}).get("level") == "ok", "G5 하루 지나면 정상으로", c5b)

try:
    undefined_g6  # noqa: F821
except Exception as e:
    CG.swallowed("t:g6", e)
s6 = CG.snapshot()["t:g6"]
b6 = s6["bug_last"]
try:
    raise ValueError("데이터")
except Exception as e:
    CG.swallowed("t:g6", e)
s6 = CG.snapshot()["t:g6"]
chk(s6["bug_last"] == b6 and s6["bug_why"].startswith("NameError") and s6["why"].startswith("ValueError"), "G6 코드 실수 시각·사유 따로(bug_last·bug_why)", s6)
sd6 = os.path.join(T.TMP, "cg6")
os.makedirs(sd6, exist_ok=True)
json.dump({"v": 1, "proc": "web", "sites": {"x:y": {"n": 5, "last": now5 - 60, "bug": 1, "bug_last": now5 - 3 * 86400, "bug_why": "NameError: q", "why": "ValueError: v"}}},
          open(os.path.join(sd6, "calcguard_web.json"), "w"))
c6 = {c["cid"]: c for c in health.collect_calcguard(now5, sd6)}
chk(c6.get("calc:bug", {}).get("level") == "ok", "G6 사흘 전 코드 실수 + 방금 데이터 예외 = 빨강 아님(종전: 빨강 연장)", c6)
json.dump({"v": 1, "proc": "web", "sites": {"x:y": {"n": 5, "last": now5 - 60, "bug": 1, "bug_last": now5 - 120, "bug_why": "NameError: q", "why": "ValueError: v"}}},
          open(os.path.join(sd6, "calcguard_web.json"), "w"))
c6 = {c["cid"]: c for c in health.collect_calcguard(now5, sd6)}
chk(c6.get("calc:bug", {}).get("level") == "crit" and "NameError: q" in c6["calc:bug"]["detail"], "G6 사유 = 코드 실수 쪽(마지막 데이터 예외 아님)", c6)

try:
    raise RuntimeError("rpc 실패 https://rpc.example.com/v2/abcdefghijklmnopqrstuvwxyz0123456789?api_key=SEKRETVALUE0123456789abcdef")
except Exception as e:
    CG.swallowed("t:g7", e)
CG.flush()
d7 = json.load(open(CG.path_of()))
w7 = (d7["sites"].get("t:g7") or {}).get("why") or ""
chk(w7 and "SEKRETVALUE0123456789abcdef" not in w7 and "abcdefghijklmnopqrstuvwxyz0123456789" not in w7, "G7 저장된 사유에 키·키 든 URL 없음", w7)
chk((os.stat(CG.path_of()).st_mode & 0o077) == 0, "G7 파일 권한 0600", oct(os.stat(CG.path_of()).st_mode))

import time as _t8  # noqa: E402
CG.FLUSH_SEC = 0.2
CG._TIMER["pid"] = None
try:
    undefined_g8  # noqa: F821
except Exception as e:
    CG.swallowed("t:g8", e)
ok8 = False
for _ in range(40):
    _t8.sleep(0.1)
    try:
        if "t:g8" in (json.load(open(CG.path_of())).get("sites") or {}):
            ok8 = True
            break
    except Exception:   # noqa: BLE001
        pass
chk(ok8, "G8 단발 코드 실수도 주기 스레드가 저장(종전: 다음 예외·종료까지 미저장)", ok8)

_po9 = CG.path_of
CG.path_of = lambda state_dir=None, suffix="": os.path.join(T.TMP, "없는_폴더_g9", "x.json")
try:
    raise ValueError("g9")
except Exception as e:
    CG.swallowed("t:g9", e)
CG.flush()
chk(CG._DIRTY[0] is True, "G9 저장 실패 뒤 dirty 유지(종전: 기록 유실)", CG._DIRTY[0])
CG.path_of = _po9
CG.flush()
chk("t:g9" in (json.load(open(CG.path_of())).get("sites") or {}), "G9 다음 저장에 남음", None)

CG.FLUSH_SEC = 60
parent_before = open(CG.path_of()).read()
CG.child_reset("build")
try:
    undefined_g10  # noqa: F821
except Exception as e:
    CG.swallowed("t:g10", e)
CG.flush_as("build")
CG.child_reset("build")
try:
    raise ValueError("g10b")
except Exception as e:
    CG.swallowed("t:g10", e)
CG.flush_as("build")
db10 = json.load(open(CG.path_of(suffix="build")))
s10 = db10["sites"].get("t:g10") or {}
chk(open(CG.path_of()).read() == parent_before, "G10 자식 저장이 부모 파일을 안 덮음", None)
chk("t:g1" not in db10["sites"] and s10.get("n") == 2 and s10.get("bug") == 1 and str(s10.get("bug_why", "")).startswith("NameError"),
    "G10 _build 파일 = 자식 기록만 · 다음 빌드가 앞 빌드의 코드 실수 기록을 안 지움(더함)", s10)
CG._SUFFIX[0] = ""
CG._MERGE[0] = False

import importlib  # noqa: E402
import sys as _s11  # noqa: E402
_fr = _s11.modules.get("fut_rcpt")
_s11.modules["fut_rcpt"] = None
_s11.modules.pop("view_detail", None)
try:
    vd11 = importlib.import_module("view_detail")
    ok11 = vd11.fut_rcpt is None
except Exception as e:   # noqa: BLE001
    ok11 = repr(e)
finally:
    if _fr is not None:
        _s11.modules["fut_rcpt"] = _fr
    else:
        _s11.modules.pop("fut_rcpt", None)
    _s11.modules.pop("view_detail", None)
chk(ok11 is True, "G11 fut_rcpt 없어도 view_detail import(fut_rcpt=None 폴백)", ok11)

bp = CG.path_of(suffix="build")
nowg = int(_t8.time())
json.dump({"v": 1, "sites": {"old:raw": {"n": 1, "last": nowg - 60, "bug": 0, "why": "RuntimeError: https://x.example/v2/abcdefghijklmnopqrstuvwxyz0123456789?api_key=OLDSEKRET0123456789abcdefgh"},
                             "old:bad": {"n": "x", "last": "bad"},
                             "old:bug": {"n": 1, "last": nowg - 60, "bug": 1, "why": "NameError: oldname"}}}, open(bp, "w"))
CG.child_reset("build")
try:
    raise ValueError("새 데이터 예외")
except Exception as e:
    CG.swallowed("old:bug", e)
CG.flush_as("build")
db12 = json.load(open(bp))
st12 = db12["sites"]
chk("OLDSEKRET0123456789abcdefgh" not in json.dumps(st12), "G12 병합한 옛 사유도 가림", st12.get("old:raw"))
chk("old:bad" not in st12 and "old:bug" in st12, "G13 옛 파일의 이상한 칸만 버리고 이번 기록 저장", list(st12))
chk(st12["old:bug"].get("bug") == 1 and int(st12["old:bug"].get("bug_last") or 0) >= nowg - 60 and "NameError" in st12["old:bug"].get("bug_why", ""),
    "G14 옛 형식 빨강 = 병합 뒤에도 코드 실수 시각·사유 유지", st12["old:bug"])
json.dump({"v": 1, "sites": [1, 2]}, open(bp, "w"))
try:
    undefined_g13  # noqa: F821
except Exception as e:
    CG.swallowed("t:g13", e)
CG.flush_as("build")
chk("t:g13" in (json.load(open(bp)).get("sites") or {}), "G13 옛 파일 sites 가 리스트여도 저장", None)
CG._SUFFIX[0] = ""
CG._MERGE[0] = False

for f15, k15 in (("core_prov.py", "core_prov:ProvMixin.prov_pass"), ("discopen.py", "discopen:Runner._harvest"), ("recon.py", "recon:fetch_evm_rpc_balances")):
    chk(k15 in open(os.path.join(T.SRC, f15), encoding="utf-8").read(), "G15 %s 메인 소비 자리 계측" % f15, k15)

import time as _t16  # noqa: E402
_sl16, _fl16, _n16 = _t16.sleep, CG.flush, [0]
_t16.sleep = lambda s: None
CG.flush = lambda *a, **k: (_n16.__setitem__(0, _n16[0] + 1), _fl16(*a, **k))[1]
CG.FLUSH_SEC = 60
CG._TIMER["pid"] = None
try:
    raise ValueError("g16")
except Exception as e:
    CG.swallowed("t:g16", e)
_t0 = _t16.monotonic()
while _t16.monotonic() - _t0 < 0.5:
    pass
_t16.sleep, CG.flush = _sl16, _fl16
chk(_n16[0] <= 1, "G16 sleep 패치에도 저장 스레드 바쁜 루프 없음(0.5초 동안 flush %d번)" % _n16[0], _n16[0])

hr17 = int(_t16.time()) // 3600
for _i in range(2):
    try:
        raise ConnectionError("g17")
    except Exception as e:
        CG.swallowed("t:g17", e)
h17 = CG.snapshot()["t:g17"]["h"]
chk(sum(h17.values()) == 2 and set(h17) <= {str(hr17), str(hr17 + 1)}, "G17 swallowed = 지금 시 칸 +1", h17)
CG._SITES["t:g17"]["h"] = {str(hr17 - 30): 9, str(hr17 - 3): 2}
try:
    raise ConnectionError("g17b")
except Exception as e:
    CG.swallowed("t:g17", e)
h17 = CG.snapshot()["t:g17"]["h"]
chk(str(hr17 - 30) not in h17 and h17.get(str(hr17 - 3)) == 2 and sum(h17.values()) == 3, "G17 새 시 칸이 생길 때 25시간 넘은 칸 지움", h17)
CG.snapshot()["t:g17"]["h"][str(hr17 - 3)] = 99
chk(CG._SITES["t:g17"]["h"].get(str(hr17 - 3)) == 2, "G17 snapshot 복사본의 h 를 바꿔도 원본 무변(얕은 복사 공유 없음)", CG._SITES["t:g17"]["h"])

now18 = 2_000_000_000
hr18 = now18 // 3600
base18 = {"first": now18 - 3600, "last": now18 - 60, "types": {}, "why": "", "bug": 0, "bug_last": 0, "bug_why": "", "sus": 0, "sus_last": 0, "sus_why": ""}
old18 = {"a": dict(base18, n=5, h={str(hr18 - 1): 3, str(hr18 - 26): 4, "bad": 1, str(hr18 - 2): "x"}),
         "b": dict(base18, n=2, h=[1, 2]),
         "c": dict(base18, n=1, h={str(hr18): 1}),
         "e": dict(base18, n=7)}
snap18 = {"a": dict(base18, n=2, h={str(hr18 - 1): 1, str(hr18): 1}),
          "b": dict(base18, n=1, h={str(hr18): 1}),
          "d": dict(base18, n=2, h={str(hr18 - 30): 5, str(hr18): 2})}
m18 = CG._merge_old("", snap18, now18, old=old18)
chk(m18["a"]["h"] == {str(hr18 - 1): 4, str(hr18): 1} and m18["a"]["n"] == 7, "G18 같은 자리 = 칸별 합 · 26시간 전·모양 이상 칸 버림", m18["a"])
chk(m18["b"]["h"] == {str(hr18): 1} and m18["b"]["n"] == 3, "G18 옛 h 가 리스트 = 그 칸만 버리고 이번 시 칸·횟수는 합", m18["b"])
chk(m18["c"]["h"] == {str(hr18): 1} and "h" not in m18["e"] and m18["e"]["n"] == 7, "G18 이번에 안 난 옛 자리 = h 정리 · 옛 형식(h 없음)은 h 없이 유지(패널 = 종전 평균)", m18)
chk(m18["d"]["h"] == {str(hr18): 2}, "G18 새 자리도 25시간 넘은 칸 지움", m18["d"])
chk(len(old18["a"]["h"]) == 4 and snap18["a"]["h"] == {str(hr18 - 1): 1, str(hr18): 1}, "G18 입력(직전 실행 기록·스냅숏) 원본 무변", (old18["a"], snap18["a"]))

os.environ["TJ_STRICT"] = "1"
n19 = sum(CG.snapshot()["t:g17"]["h"].values())
try:
    try:
        raise NameError("g19")
    except Exception as e:
        CG.swallowed("t:g17", e)
    r19 = "삼킴"
except NameError:
    r19 = "던짐"
try:
    raise ConnectionError("g19b")
except Exception as e:
    CG.swallowed("t:g17", e)
os.environ.pop("TJ_STRICT", None)
chk(r19 == "던짐" and sum(CG.snapshot()["t:g17"]["h"].values()) == n19 + 1, "G19 엄격 1단계 = NameError 던짐(기록 없음) · 네트워크 꼴은 시 칸 +1", (r19, n19))
T.finish()
