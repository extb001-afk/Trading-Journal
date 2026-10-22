#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import http.client  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import signal  # noqa: E402
import socket  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

import web  # noqa: E402

chk = T.chk
EX = os.path.join(T.ROOT, "config.example.json")
WEB = os.path.join(T.SRC, "web.py")
V2 = os.path.join(T.ROOT, "web", "v2")
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
        raise OSError("legacy routes: blocked")
    return _c(self, a)
def connect_ex(self, a):
    h = _host(a)
    if h is not None and h not in LOOP:
        _rec(h)
        raise OSError("legacy routes: blocked")
    return _ce(self, a)
def gai(host, *a, **k):
    h = host.decode() if isinstance(host, bytes) else host
    if h is not None and h not in LOOP:
        _rec(h)
        raise socket.gaierror("legacy routes: blocked")
    return _g(host, *a, **k)
socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = connect, connect_ex, gai
sys.argv = [WEB]
sys.path.insert(0, os.path.dirname(WEB))
runpy.run_path(WEB, run_name="__main__")
'''
LEGACY = {
    "index.html": "<!doctype html><html><head><title>legacy classic</title></head><body><div id=\"root\">classic 화면 합성본</div>"
                  "<script src=\"/support.js\"></script></body></html>\n".encode("utf-8"),
    "futures.html": "<!doctype html><html><head><title>legacy futures</title></head><body><p>선물 화면 합성본</p></body></html>\n".encode("utf-8"),
    "support.js": b"/* synthetic support runtime */\nwindow.__legacySupport = 1;\n",
}
FUT = {"positions": [{"sym": "AAAUSDT", "side": "long", "qty": 1.5, "upnl": 2.25}],
       "events": [{"t": 1760000000, "kind": "funding", "sym": "AAAUSDT", "usd": -0.5}], "updated_at": 1760000100}
SEC = [(k.lower(), v) for k, v in web.BASE_SEC_HEADERS]
SEC_NAMES = {k for k, _v in SEC}
V2_ONLY = ("script-src", "style-src", "img-src", "connect-src", "font-src", "require-trusted-types-for", "trusted-types", "default-src")


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
        return r.status, [(k.lower(), v) for k, v in r.getheaders()], r.read()
    except (OSError, http.client.HTTPException) as e:
        return None, [], repr(e).encode()
    finally:
        c.close()


def hval(hs, name):
    return [v for k, v in hs if k == name]


def install(name, legacy):
    base = os.path.join(T.TMP, name)
    os.makedirs(os.path.join(base, "state"))
    os.makedirs(os.path.join(base, "web"))
    os.symlink(V2, os.path.join(base, "web", "v2"))
    if legacy:
        for fn, body in LEGACY.items():
            with open(os.path.join(base, "web", fn), "wb") as f:
                f.write(body)
    for nm in ("seed", "tools", "VERSION", "config.example.json"):
        if os.path.exists(os.path.join(T.ROOT, nm)):
            os.symlink(os.path.join(T.ROOT, nm), os.path.join(base, nm))
    with open(os.path.join(base, "state", "futures_binance.json"), "w", encoding="utf-8") as f:
        json.dump(FUT, f)
    with open(EX, encoding="utf-8") as f:
        cfg = json.load(f)
    port = free_port()
    cfg.setdefault("web", {})["port"] = port
    cfg["web"].setdefault("login", {})["enabled"] = False
    with open(os.path.join(base, "config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False)
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_")}
    env.update(TJ_BASE=base, PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(k, None)
    logf = os.path.join(base, "web_out.log")
    fh = open(logf, "w", encoding="utf-8")
    p = subprocess.Popen([sys.executable, "-c", PRELUDE, os.path.join(base, "net_tries.log"), WEB], env=env, cwd=base, stdout=fh,
                         stderr=subprocess.STDOUT, preexec_fn=T.sigint_default)
    return {"name": name, "legacy": legacy, "base": base, "port": port, "p": p, "fh": fh, "log": logf}


def wait_up(s, limit=90):
    t0 = time.time()
    while time.time() - t0 < limit and s["p"].poll() is None:
        st, _h, _b = get(s["port"], "/api/auth/status", timeout=5)
        if st is not None:
            return True, time.time() - t0
        time.sleep(0.3)
    return False, time.time() - t0


def get_ready(port, path, limit=120):
    t0 = time.time()
    while True:
        r = get(port, path, timeout=120)
        if r[0] != 503 or time.time() - t0 > limit:
            return r
        time.sleep(0.5)


def sec_ok(hs):
    bad = []
    for k, v in SEC:
        got = hval(hs, k)
        if got != [v]:
            bad.append((k, got))
    for v in hval(hs, "content-security-policy"):
        for d in V2_ONLY:
            if d in v.lower():
                bad.append(("v2 정책 지시어", d))
    return bad


SRV = []
try:
    for nm0, has0 in (("with_legacy", True), ("no_legacy", False)):
        SRV.append(install(nm0, has0))
    for s in SRV:
        up, dt = wait_up(s)
        s["up"] = up
        chk(up, "R1 %s 설치 tj-web 기동 · 루프백 포트 열림(%.1f초)" % (s["name"], dt),
            {"rc": s["p"].poll(), "log": open(s["log"], encoding="utf-8", errors="replace").read()[-800:]})
    for s in SRV:
        if not s["up"]:
            continue
        nm, port, has = s["name"], s["port"], s["legacy"]
        resp = {}
        for path, fn, ctype in (("/classic", "index.html", "text/html"), ("/futures", "futures.html", "text/html"),
                                ("/support.js", "support.js", "application/javascript")):
            st, hs, body = get(port, path)
            resp[path] = (st, hs)
            ct = (hval(hs, "content-type") or [""])[0]
            if has:
                chk(st == 200 and ct.startswith(ctype) and body == LEGACY[fn], "R%s %s %s = 200 %s · 본문 = 옛 파일 그대로" % (
                    {"/classic": 2, "/futures": 3, "/support.js": 4}[path], nm, path, ctype), {"st": st, "ct": ct, "len": len(body)})
            elif path == "/support.js":
                txt = body.decode("utf-8", "replace")
                chk(st == 404 and s["base"] not in txt and "/web/" not in txt and fn not in txt and json.loads(txt or "{}") == {"error": "not found"},
                    "R4 %s /support.js = 404 · 본문 = {error: not found}(설치 경로·파일 경로 없음)" % nm, {"st": st, "body": txt[:200]})
            else:
                chk(st == 302 and hval(hs, "location") == ["/"] and body == b"", "R%d %s %s = 302 Location / · 빈 본문" % (
                    2 if path == "/classic" else 3, nm, path), {"st": st, "loc": hval(hs, "location"), "len": len(body)})
        st, hs, body = get_ready(port, "/api/futures")
        resp["/api/futures"] = (st, hs)
        try:
            fj = json.loads(body.decode("utf-8"))
        except ValueError:
            fj = None
        chk(st == 200 and (hval(hs, "content-type") or [""])[0].startswith("application/json") and fj == {"binance": FUT},
            "R5 %s /api/futures = 200 JSON · 열쇠 = 선물 파일 있는 거래소(binance)만 · 값 = 파일 그대로" % nm,
            {"st": st, "keys": sorted(fj) if isinstance(fj, dict) else fj})
        for path, (st6, hs6) in sorted(resp.items()):
            chk(st6 is not None and not sec_ok(hs6), "R6 %s %s(%s) 보안 헤더 = BASE_SEC_HEADERS 그대로 · v2 정책 안 샘" % (nm, path, st6), sec_ok(hs6))
        st, hs, _b = get(port, "/v2/")
        csp = hval(hs, "content-security-policy")
        chk(st == 200 and len(csp) == 1 and "script-src" in csp[0], "R6 %s 대조: v2 첫 화면 CSP 에는 script-src 가 있음(시험이 정책 차이를 봄)" % nm, csp)
finally:
    for s in SRV:
        if s["p"].poll() is None:
            s["p"].send_signal(signal.SIGINT)
    for s in SRV:
        try:
            s["rc"] = s["p"].wait(timeout=30)
        except subprocess.TimeoutExpired:
            s["p"].kill()
            s["rc"] = s["p"].wait()
        s["fh"].close()
for s in SRV:
    out = open(s["log"], encoding="utf-8", errors="replace").read()
    chk("Traceback" not in out, "R7 %s 서버 출력에 Traceback 없음" % s["name"], out[out.find("Traceback") - 200:][:1200] if "Traceback" in out else None)
    chk(s["rc"] == 0 and "정지 신호(SIGINT) — 종료" in out, "R7 %s SIGINT = 한 줄 종료 · 코드 0" % s["name"], {"rc": s["rc"], "tail": out[-300:]})
T.finish()
