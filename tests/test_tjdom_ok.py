#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import contextlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import signal  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

chk = T.chk
TOOL = os.path.join(T.ROOT, "tools", "refactor", "tjdom_ok.mjs")
TJD = os.path.join(T.ROOT, "web", "v2", "tjdom.js")
if not os.path.isfile(TJD):
    chk(True, "tjdom.js 없음(8-1 앞 트리) · 건너뜀")
    T.finish()
if not os.path.isfile(TOOL) or not os.path.isfile(os.path.join(T.ROOT, "tools", "refactor", "web_golden.mjs")):
    chk(True, "공개판 배치 — 비공개 도구(tools/refactor/tjdom_ok.mjs) 없음 · 건너뜀")
    T.finish()
CHROME = os.environ.get("TJ_CHROME") or os.path.join(os.path.expanduser("~"), "scripts", "tj_chrome", "TJ Chrome.app", "Contents", "MacOS", "Google Chrome")
if not os.path.isfile(CHROME):
    print("SKIP TJ Chrome 사본 없음 — 정상 길 브라우저 시험 건너뜀", flush=True)
    T.finish()
node = T.node_bin("tjdom.js 정상 길 브라우저 시험")
if not node:
    T.finish()

ENV = {k: v for k, v in os.environ.items() if not k.startswith(("TJ_", "WG_"))}
out = tempfile.mkdtemp(prefix="tjdom_ok_")
proc = None
try:
    proc = subprocess.Popen([node, "--expose-internals", TOOL, "--tree", T.ROOT, "--out", out], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, env=ENV, start_new_session=True)
    try:
        so, se = proc.communicate(timeout=600)
    except subprocess.TimeoutExpired:
        so = se = None
        for sig in (signal.SIGTERM, signal.SIGKILL):
            with contextlib.suppress(OSError):
                os.killpg(proc.pid, sig)
            with contextlib.suppress(subprocess.TimeoutExpired):
                so, se = (so, se) if so is not None else proc.communicate(timeout=20)
        so, se = so or "", (se or "") + "\n시간 초과(600초) — 프로세스 그룹 TERM → KILL"
    log = so + se
    chk(proc.returncode == 0 and "TJDOM_OK 통과" in log, "tjdom_ok.mjs 끝 줄 = 통과(rc 0)", [ln for ln in log.splitlines() if not ln.startswith("OK ")][-30:])
    pids = re.findall(r"^CHROME_PID (\d+)$", log, re.M)
    closed = re.findall(r"^CHROME_CLOSED (\d+)$", log, re.M)
    alive = []
    for p in pids:
        try:
            os.kill(int(p), 0)
            alive.append(p)
        except OSError:
            pass
    chk(len(pids) == 1 and pids == closed and not alive, "O7 띄운 크롬 1개 · 끝에 PID 종료 확인(남은 프로세스 0)", {"pid": pids, "closed": closed, "alive": alive})
    rep = {}
    jp = os.path.join(out, "ok.json")
    if os.path.isfile(jp):
        with open(jp, encoding="utf-8") as f:
            rep = json.load(f)
    rows = {x["page"]: x for x in rep.get("table") or []}
    chk(sorted(rows) == ["nott-enforce", "nott-observe", "tt-enforce", "tt-observe"], "결과 표 = 네 문서(TT 있음·없음 × observe·enforce)", sorted(rows))
    n = rep.get("nOps") or 0
    chk(n >= 200 and (rep.get("cases") or 0) >= 40, "정상 장면 %s · 연산 %d(≥ 200)" % (rep.get("cases"), n))
    for pg in ("tt-observe", "nott-observe", "tt-enforce", "nott-enforce"):
        x = rows.get(pg) or {}
        want_pol = pg.startswith("tt-")
        chk(x.get("ops") == n and x.get("dom") == 0 and x.get("err") == 0, "O1 %s: %d연산 DOM·예외 = 브라우저 싱크" % (pg, n), x)
        chk(x.get("mo") == 0 and x.get("mo1") == 0, "O2 %s: MutationObserver 기록 수 1 · 모양 같음" % pg, x)
        chk(x.get("rep") == 0 and x.get("total") == [0, 0, 0], "O2 %s: report() must·compat·drop = 0" % pg, x)
        chk(x.get("policy") is want_pol and x.get("mode") == pg.split("-")[1], "O1 %s: report() policy=%s · mode=%s" % (pg, want_pol, pg.split("-")[1]), x)
        chk(x.get("focus") is True and x.get("v") == 0 and x.get("exc") == 0, "O3 %s: 초점·선택·스크롤 유지 · CSP 위반·예외 0" % pg, x)
    fails = rep.get("fails")
    chk(fails == [], "O4·O5·O6 도구 안 판정(덮음 · 자기 점검 · 두 판 같음 · enforce = observe · 호환 묶음) 실패 0", fails)
    print("결과 표: " + " / ".join("%s dom %s · mo %s · rep %s · policy %s" % (k, v.get("dom"), v.get("mo"), v.get("rep"), v.get("policy")) for k, v in sorted(rows.items())))
finally:
    if proc is not None and proc.poll() is None:
        with contextlib.suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)
    shutil.rmtree(out, ignore_errors=True)
T.finish()
