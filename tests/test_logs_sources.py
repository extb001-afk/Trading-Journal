#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

ENV_KEY = "SYNTHenvQwErTyUiOpZxCv"
FILE_KEY = "SYNTHfileAsDfGhJkLpOiU"
FILE_KEY2 = "SYNTHotherMnBvCxZaQwPl"

CHILD = r'''
import io, json, logging, os, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import logs
out = {"common_loaded": "common" in sys.modules, "paths": list(logs._source_paths())}
buf = io.StringIO()
h = logging.StreamHandler(buf)
h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [tj-synth] %(message)s"))
lg = logging.getLogger("tj-synth")
lg.handlers[:] = [h]
lg.propagate = False
lg.setLevel(logging.INFO)
logs.add_secret_filter([h])
lg.warning("시작 apikey=%s 키 %s 끝", "SYNTHkvKEY12345678", os.environ["TJ_SYNTH_SECRET"])
try:
    raise ValueError("secret=" + sys.argv[5] + " 넣기 실패 " + os.environ["TJ_SYNTH_SECRET"])   # 키 = 실행 시 인자(소스 줄에 리터럴 없음)
except ValueError:
    lg.exception("수집 실패")
try:
    raise LookupError("등록 비밀 길이 %d" % len("@ENV_KEY@"))   # 등록된 비밀(환경) 리터럴이 소스 줄에 — Traceback 소스 줄도 가림
except LookupError:
    lg.exception("소스 줄 확인")
out["log"] = buf.getvalue()
out["red"] = logs.redact_secret_text("오류 apikey=" + "SYNTHkvKEY12345678 https://rpc.example.invalid/v3/abcdefabcdef0123 끝")   # 합성 키(이어 붙임)
out["vals"] = logs._secret_values()
p = [os.path.join(sys.argv[2], "a.env")]
logs.set_sources(lambda: (p[0], ""))
logs._SECRET_CACHE["checked"] = 0.0
out["a"] = logs.redact_secret_text("값 " + sys.argv[3] + " 끝", generic=False)
p[0] = os.path.join(sys.argv[2], "b.env")
logs._SECRET_CACHE["checked"] = 0.0
out["b_old"] = logs.redact_secret_text("값 " + sys.argv[3] + " 끝", generic=False)
out["b_new"] = logs.redact_secret_text("값 " + sys.argv[4] + " 끝", generic=False)
print(json.dumps(out, ensure_ascii=False))
'''

D = os.path.join(T.TMP, "logs_src")
os.makedirs(D, exist_ok=True)
with open(os.path.join(D, "a.env"), "w", encoding="utf-8") as f:
    f.write("UPBIT_SECRET=%s\n" % FILE_KEY)
with open(os.path.join(D, "b.env"), "w", encoding="utf-8") as f:
    f.write("UPBIT_SECRET=%s\n" % FILE_KEY2)
TB_KEY = "SYNTHtb" + "KEYabcdefgh"
CHILD_PY = os.path.join(D, "child_logs.py")
with open(CHILD_PY, "w", encoding="utf-8") as f:
    f.write(CHILD.replace("@ENV_KEY@", ENV_KEY))
env = {"PATH": os.environ.get("PATH", ""), "TJ_SYNTH_SECRET": ENV_KEY, "LANG": "C.UTF-8"}
r = subprocess.run([sys.executable, "-I", CHILD_PY, T.SRC, D, FILE_KEY, FILE_KEY2, TB_KEY], env=env, capture_output=True, text=True,
                   encoding="utf-8", timeout=60)
T.chk(r.returncode == 0, "(전제) logs 만 가져온 새 프로세스가 끝까지 돎", r.stderr[-800:])
try:
    got = json.loads(r.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    got = {}
log = got.get("log", "")

print("[1] 등록 전 — 파일 비밀값 빈 목록 · 가림 함수는 그대로 동작")
T.chk(got.get("common_loaded") is False, "logs 만 가져오면 common 을 안 가져옴(기반 모듈 · src import 0)", got.get("common_loaded"))
T.chk(got.get("paths") == ["", ""], "등록 전 출처 = 빈 경로(읽을 파일 없음)", got.get("paths"))
T.chk(isinstance(got.get("vals"), list) and ENV_KEY in got.get("vals", []) and FILE_KEY not in got.get("vals", []),
      "등록 전 비밀값 = 환경변수 것만(파일 빈 목록 · 예외 없음)", [len(v) for v in got.get("vals") or []])
T.chk("숨김" not in log and "시작 apikey=*** 키 *** 끝" in log, "로그 줄: 문구 보존 + key=값·환경 비밀값만 가림(통째 숨김 아님)", log[:300])
T.chk("Traceback (most recent call last):" in log and "ValueError: secret=*** 넣기 실패 ***" in log,
      "예외 추적: Traceback 표식·예외 줄 모양 보존 + 비밀값 가림", log[-400:])
T.chk(ENV_KEY not in log and "SYNTHkvKEY" not in log and TB_KEY not in log, "로그 어디에도 합성 키 원문 없음(Traceback 소스 줄 포함)", log[-600:])
T.chk('sys.argv[5] + " 넣기 실패 "' in log, "(전제) Traceback 에 소스 줄이 나옴(파일 실행 — 소스 줄 가림을 실제로 시험)", log[-600:])
T.chk('len("***")' in log and "LookupError: 등록 비밀 길이 %d" % len(ENV_KEY) in log,
      "등록된 비밀 리터럴이 든 Traceback 소스 줄 = 그 값만 가림(줄 모양 보존)", log[-400:])
T.chk(got.get("red") == "오류 apikey=*** rpc.example.invalid 끝", "외부 오류 문구 가림(key=값 · URL 호스트만) — 통째 숨김 아님", got.get("red"))

import chk_logs  # noqa: E402

lw, fst = chk_logs.LogWatch(), {}
for ln in log.splitlines():
    lw.feed("tj-synth", ln, ts_hint=1_800_000_000.0, fstate=fst)
lw.feed("tj-synth", "2027-01-15 12:00:00,000 INFO [tj-synth] 다음 줄", fstate=fst)
evs = [e for e in lw._u("tj-synth")["ev"] if e[1] == "crash"]
T.chk(len(evs) == 2 and evs[0][3].startswith("ValueError: secret=***") and evs[1][3].startswith("LookupError: 등록 비밀 길이"),
      "가린 Traceback 도 chk_logs 크래시 판정 = 예외마다 1건(2건 · 모양 계약)",
      [e[1:] for e in lw._u("tj-synth")["ev"]])

print("[2] 등록 함수는 부를 때마다")
T.chk(got.get("a") == "값 *** 끝", "등록한 .env 의 비밀값 가림", got.get("a"))
T.chk(got.get("b_old") == "값 %s 끝" % FILE_KEY and got.get("b_new") == "값 *** 끝",
      "경로를 바꾸면 새 파일 기준(옛 값은 더 이상 비밀 아님 · 새 값 가림)", (got.get("b_old", "")[:6], got.get("b_new")))

print("[3] paths 가 등록한 출처 · 필터 한 번만")
import paths  # noqa: E402
import logs  # noqa: E402

T.chk(logs._source_paths() == (paths.ENV_PATH, paths.CONFIG_PATH), "paths 가 import 때 출처 등록(.env·config.json 경로 — 부를 때 paths 의 지금 값)")
S0 = "apikey=" + "SYNTHkvKEY12345678 https://u:p@rpc.example.invalid/v3/abcdefabcdef0123?x=1 끝"
T.chk(logs.redact_urls(S0) == "apikey=SYNTHkvKEY12345678 rpc.example.invalid 끝" and logs.redact_secret_text(S0) == "apikey=*** rpc.example.invalid 끝"
      and logs.safe_err(ValueError("secret: abcdefgh123")) == "secret: ***"
      and logs._secret_name("TJ_X_TOKEN") is True and logs._secret_name("TJ_X_CHAIN") is False,
      "가림 함수(옛 common.X 래퍼 자리 · 4-6 부터 logs.X 직접) = 고정 기대값", (logs.redact_urls(S0), logs.redact_secret_text(S0)))
obj = {"err": S0, "keep": S0, "note": [S0]}
T.chk(logs.scrub_secrets(obj) == ({"err": "apikey=*** rpc.example.invalid 끝", "keep": S0, "note": ["apikey=*** rpc.example.invalid 끝"]}, 2)
      and "err" in logs.SECRET_FIELD_KEYS, "scrub_secrets = 비밀 칸(err·note)만 가림 · 2칸", logs.scrub_secrets(obj))
hd = __import__("logging").StreamHandler(io.StringIO())
logs.add_secret_filter([hd])
logs.add_secret_filter([hd])
T.chk(sum(isinstance(f, logs.SecretLogFilter) for f in hd.filters) == 1, "add_secret_filter = 필터 한 번만")

print("[4] 격리 데모 — 비밀값 필터도 데모 state 의 .env 만(실사용 .env 안 엶)")
DEMO = r'''
import builtins, json, os, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
seen, op0 = [], builtins.open
def op(p, *a, **k):
    seen.append(str(p))
    return op0(p, *a, **k)
builtins.open = op
import paths, logs
out = {"env": paths.ENV_PATH, "src": list(logs._source_paths()),
       "base_key": logs.redact_secret_text("x " + sys.argv[2], generic=False),
       "demo_key": logs.redact_secret_text("x " + sys.argv[3], generic=False)}
out["opened"] = [x for x in seen if x.endswith(".env")]
print(json.dumps(out, ensure_ascii=False))
'''
base = os.path.join(D, "base")
st = os.path.join(D, "demo_state")
os.makedirs(base, exist_ok=True)
os.makedirs(st, exist_ok=True)
with open(os.path.join(base, ".env"), "w", encoding="utf-8") as f:
    f.write("UPBIT_SECRET=%s\n" % FILE_KEY)
with open(os.path.join(st, ".env"), "w", encoding="utf-8") as f:
    f.write("UPBIT_SECRET=%s\n" % FILE_KEY2)
denv = {"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8", "TJ_DEMO": "1", "TJ_DEMO_STATE": st, "TJ_BASE": base}
r = subprocess.run([sys.executable, "-I", "-c", DEMO, T.SRC, FILE_KEY, FILE_KEY2], env=denv, capture_output=True, text=True,
                   encoding="utf-8", timeout=60)
T.chk(r.returncode == 0, "(전제) 격리 데모 자식이 끝까지 돎", r.stderr[-600:])
try:
    dg = json.loads(r.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    dg = {}
T.chk(dg.get("env") == os.path.join(st, ".env") and (dg.get("src") or [""])[0] == dg.get("env"), "격리 데모 = 출처 .env 도 데모 state 것", dg.get("src"))
T.chk(os.path.join(base, ".env") not in (dg.get("opened") or []) and dg.get("base_key") == "x " + FILE_KEY and dg.get("demo_key") == "x ***",
      "실사용 .env 는 안 엶(그 값 = 비밀 목록 밖) · 데모 .env 값은 가림", (dg.get("opened"), dg.get("demo_key")))

T.finish()
