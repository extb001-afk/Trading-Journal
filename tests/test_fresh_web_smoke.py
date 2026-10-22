#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import http.client  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import signal  # noqa: E402
import socket  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

chk = T.chk
EX = os.path.join(T.ROOT, "config.example.json")
WEB = os.path.join(T.SRC, "web.py")
PRELUDE = r'''
import os, runpy, socket, sys
LOG, WEB = sys.argv[1], sys.argv[2]
LOOP = ("127.0.0.1", "::1", "localhost")
_c, _ce, _g = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo
def _rec(h):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(str(h)[:120] + "\n")
def _host(a):
    return a[0] if isinstance(a, tuple) else None
def connect(self, a):
    h = _host(a)
    if h is not None and h not in LOOP:
        _rec(h)
        raise OSError("smoke: blocked")
    return _c(self, a)
def connect_ex(self, a):
    h = _host(a)
    if h is not None and h not in LOOP:
        _rec(h)
        raise OSError("smoke: blocked")
    return _ce(self, a)
def gai(host, *a, **k):
    h = host.decode() if isinstance(host, bytes) else host
    if h is not None and h not in LOOP:
        _rec(h)
        raise socket.gaierror("smoke: blocked")
    return _g(host, *a, **k)
socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = connect, connect_ex, gai
sys.argv = [WEB]
sys.path.insert(0, os.path.dirname(WEB))
runpy.run_path(WEB, run_name="__main__")
'''


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def get(port, path, timeout=60):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        c.request("GET", path, headers={"Accept-Encoding": "identity"})
        r = c.getresponse()
        return r.status, r.getheader("Content-Type") or "", r.read()
    except (OSError, http.client.HTTPException) as e:
        return None, "", repr(e).encode()
    finally:
        c.close()


BASE = os.path.join(T.TMP, "fresh")
os.makedirs(os.path.join(BASE, "state"))
for nm in ("web", "seed", "tools", "VERSION", "config.example.json"):
    if os.path.exists(os.path.join(T.ROOT, nm)):
        os.symlink(os.path.join(T.ROOT, nm), os.path.join(BASE, nm))
cfg = json.load(open(EX, encoding="utf-8"))
PORT = free_port()
cfg.setdefault("web", {})["port"] = PORT
cfg["web"].setdefault("login", {})["enabled"] = False
with open(os.path.join(BASE, "config.json"), "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False)
NETLOG = os.path.join(BASE, "net_tries.log")
env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_")}
env.update(TJ_BASE=BASE, PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    env.pop(k, None)
LOGF = os.path.join(BASE, "web_out.log")
logfh = open(LOGF, "w", encoding="utf-8")
p = subprocess.Popen([sys.executable, "-c", PRELUDE, NETLOG, WEB], env=env, cwd=BASE, stdout=logfh, stderr=subprocess.STDOUT,
                     preexec_fn=T.sigint_default)
try:
    t0, up = time.time(), False
    while time.time() - t0 < 90 and p.poll() is None:
        st, _ct, _b = get(PORT, "/api/auth/status", timeout=5)
        if st is not None:
            up = True
            break
        time.sleep(0.3)
    chk(up, "W1 tj-web 기동 · 루프백 포트 열림(%.1f초)" % (time.time() - t0), {"rc": p.poll(), "log": open(LOGF, encoding="utf-8", errors="replace").read()[-800:]})
    if up:
        st, ct, body = get(PORT, "/")
        html = body.decode("utf-8", "replace")
        chk(st == 200 and "text/html" in ct and "<html" in html.lower(), "W2 첫 화면 GET / = 200 HTML", {"st": st, "ct": ct, "head": html[:200]})
        refs = sorted(set(re.findall(r'<script[^>]+src="(/[^"]+)"', html) + re.findall(r'<link[^>]+href="(/[^"]+)"', html)))
        bad, js = [], {}
        for ref in refs:
            st2, ct2, b2 = get(PORT, ref)
            if st2 != 200 or not b2:
                bad.append((ref, st2, len(b2)))
            elif ref.split("?", 1)[0].endswith(".js"):
                js[ref] = b2
        names = {r.split("?", 1)[0].rsplit("/", 1)[-1] for r in refs}
        chk(refs and not bad, "W2 화면이 부르는 같은 출처 자산 %d개 = 전부 200(빈 몸 아님)" % len(refs), bad)
        chk("setup.js" in names and "app.js" in names and any(n.startswith("tab_") for n in names),
            "W2 설정 마법사(setup.js)·본 화면(app.js)·탭 파일(tab_*.js)을 부름", sorted(names))
        node = T.node_path()
        if node:
            nbad = []
            for ref, b2 in js.items():
                fp = os.path.join(BASE, "asset_check.js")
                with open(fp, "wb") as f:
                    f.write(b2)
                r = subprocess.run([node, "--check", fp], capture_output=True, text=True)
                if r.returncode:
                    nbad.append((ref, r.stderr[-200:]))
            chk(js and not nbad, "W3 내려받은 스크립트 %d개 문법 통과(node --check)" % len(js), nbad)
        else:
            chk(not T.node_required(), "W3 node 없음 — 스크립트 문법 검사 건너뜀(TJ_TEST_REQUIRE_NODE=1 이면 실패)")
        api = {}
        for path in ("/api/auth/status", "/api/setup/status", "/api/health", "/api/state", "/api/v2/state"):
            st3, ct3, b3 = get(PORT, path, timeout=120)
            try:
                api[path] = (st3, json.loads(b3.decode("utf-8")))
            except ValueError:
                api[path] = (st3, None)
        badapi = {k: v[0] for k, v in api.items() if v[0] != 200 or not isinstance(v[1], dict)}
        chk(not badapi, "W4 /api 5개 = 200 JSON", badapi)
        ss = (api.get("/api/setup/status") or (0, {}))[1] or {}
        chk(ss.get("ok") is True and ss.get("wallets") == [] and not ss.get("demo"), "W4 setup/status = 지갑 0 인 첫 설정 상태(데모 아님)",
            {k: ss.get(k) for k in ("ok", "demo", "wallets", "error")})
        au = (api.get("/api/auth/status") or (0, {}))[1] or {}
        chk(au.get("ok") is True and au.get("enabled") is False, "W4 auth/status = 로그인 꺼짐(config web.login.enabled=false)", au)
finally:
    if p.poll() is None:
        p.send_signal(signal.SIGINT)
    try:
        rc = p.wait(timeout=30)
    except subprocess.TimeoutExpired:
        p.kill()
        rc = p.wait()
    logfh.close()
out = open(LOGF, encoding="utf-8", errors="replace").read()
tries = open(NETLOG, encoding="utf-8").read().split() if os.path.exists(NETLOG) else []
chk("Traceback" not in out, "W5 서버 출력에 Traceback 없음", out[out.find("Traceback") - 200:][:1200] if "Traceback" in out else None)
chk(rc == 0 and "정지 신호(SIGINT) — 종료" in out, "W5 SIGINT = 한 줄 종료 · 코드 0", {"rc": rc, "tail": out[-300:]})
print("  서버 쪽 바깥 연결 시도 %d건(차단됨 · 새 설치본의 공개 시세·노드 조회): %s" % (len(tries), " ".join(sorted(set(tries))[:8])))
T.finish()
