#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os

import calcguard as CG
import common

chk = T.chk
os.environ.pop("TJ_STRICT", None)

try:
    raise ValueError("데이터 이상")
except Exception as e:
    CG.swallowed("t:g1", e)
try:
    undefined_name_xyz
except Exception as e:
    CG.swallowed("t:g1", e)
s = CG.snapshot().get("t:g1") or {}
chk(s.get("n") == 2 and s.get("types") == {"ValueError": 1, "NameError": 1} and s.get("bug") == 1, "G1 라이브 = 자리별 횟수·종류·코드 실수 꼴 수 기록(계속 진행)", s)

CG.flush(now=CG.time.time() + 10 ** 6)
p = CG.path_of()
d = json.load(open(p)) if os.path.exists(p) else {}
chk(p.startswith(common.STATE_DIR) and d.get("v") == 1 and "t:g1" in (d.get("sites") or {}), "G2 저장 파일(state 안 · 자리 기록)", (p, d))
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
    except Exception as e2:
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
except Exception:
    ok4 = False
chk(ok4, "G4 기록 실패 = 조용히(계산 계속)", ok4)

os.environ.pop("TJ_STRICT", None)
try:
    raise ImportError("선택 모듈 없음")
except Exception as e:
    CG.swallowed("t:g4b", e)
chk((CG.snapshot().get("t:g4b") or {}).get("bug") == 0, "G4b 라이브 = ImportError 는 빨강 수에 안 셈", CG.snapshot().get("t:g4b"))

import health
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
    undefined_g6
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

import time as _t8
CG.FLUSH_SEC = 0.2
CG._TIMER["pid"] = None
try:
    undefined_g8
except Exception as e:
    CG.swallowed("t:g8", e)
ok8 = False
for _ in range(40):
    _t8.sleep(0.1)
    try:
        if "t:g8" in (json.load(open(CG.path_of())).get("sites") or {}):
            ok8 = True
            break
    except Exception:
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
    undefined_g10
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

import importlib
import sys as _s11
_fr = _s11.modules.get("fut_rcpt")
_s11.modules["fut_rcpt"] = None
_s11.modules.pop("view_detail", None)
try:
    vd11 = importlib.import_module("view_detail")
    ok11 = vd11.fut_rcpt is None
except Exception as e:
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
    undefined_g13
except Exception as e:
    CG.swallowed("t:g13", e)
CG.flush_as("build")
chk("t:g13" in (json.load(open(bp)).get("sites") or {}), "G13 옛 파일 sites 가 리스트여도 저장", None)
CG._SUFFIX[0] = ""
CG._MERGE[0] = False

for f15, k15 in (("core_prov.py", "core_prov:ProvMixin.prov_pass"), ("discopen.py", "discopen:Runner._harvest"), ("recon.py", "recon:fetch_evm_rpc_balances")):
    chk(k15 in open(os.path.join(T.SRC, f15), encoding="utf-8").read(), "G15 %s 메인 소비 자리 계측" % f15, k15)

import time as _t16
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
T.finish()
