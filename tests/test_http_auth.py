#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import http.client  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

with open(os.path.join(T.ROOT, "config.example.json"), encoding="utf-8") as f:
    CFG = json.load(f)
CFG["wallets"], CFG["exchange_addresses"] = [], []
CFG["web"] = {"port": 8023, "bind": "loopback"}
CFG.setdefault("balance_check", {})["enabled"] = False
with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump(CFG, f, ensure_ascii=False)

import paths  # noqa: E402
import login_auth as LA  # noqa: E402
import login_limits as LL  # noqa: E402
import onboarding  # noqa: E402
import settings_store as ss  # noqa: E402
import web  # noqa: E402

chk = T.chk
assert T.TMP in paths.STATE_DIR and T.TMP in paths.CONFIG_PATH
LA.init(CFG)
LL.LIM = LL.Limiter()
PW = "Synthetic-Horse-7731"
LA.set_password(PW, iters=200_000)
web.BUILDER = onboarding.DemoBuilder()

SRV = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
PORT = SRV.server_address[1]
threading.Thread(target=SRV.serve_forever, daemon=True, name="t-http-auth").start()
ORIGIN = f"http://127.0.0.1:{PORT}"
HOST = f"127.0.0.1:{PORT}"


def req(method, path, body=None, cookie=None, origin=True, host=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=60)
    h = {"Host": host or HOST}
    if method == "POST":
        if origin is True:
            h["Origin"] = ORIGIN
        elif origin:
            h["Origin"] = origin
        h["Content-Type"] = "application/json"
    if cookie:
        h["Cookie"] = f"{LA.COOKIE}={cookie}"
    h.update(headers or {})
    data = json.dumps(body if body is not None else {}).encode() if method == "POST" else None
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    raw = r.read()
    hd = {k.lower(): v for k, v in r.getheaders()}
    sc = r.msg.get_all("Set-Cookie") or []
    c.close()
    try:
        j = json.loads(raw.decode() or "null")
    except ValueError:
        j = None
    return r.status, hd, j, sc


def token(sc):
    for s in sc:
        if s.startswith(LA.COOKIE + "="):
            return s.split(";", 1)[0].split("=", 1)[1] or None
    return None


st, hd, j, _ = req("GET", "/api/state")
chk(st == 401 and hd.get("x-tj-login") == "required", "A1 쿠키 없이 /api/state = 401 + X-TJ-Login: required", (st, hd.get("x-tj-login")))
st, hd, j, _ = req("GET", "/api/setup/status")
chk(st == 401 and not (j or {}).get("csrf"), "A2 쿠키 없이 설정 API = 401(CSRF 토큰도 안 줌)", (st, j))
st, hd, _j, _ = req("GET", "/")
chk(st == 302 and hd.get("location", "").startswith("/login"), "A3 쿠키 없이 화면 = 302 /login", (st, hd.get("location")))
st, _hd, _j, _ = req("POST", "/api/setup/prefs", body={"currency": "USD"}, headers={"X-TJ-CSRF": ss.csrf_token()})
chk(st == 401, "A4 쿠키 없이 쓰기 POST = 401(CSRF 가 맞아도)", st)
for p9, ct9 in (("/v2/login.css", "text/css; charset=utf-8"), ("/v2/login.js", "application/javascript; charset=utf-8")):
    c9 = http.client.HTTPConnection("127.0.0.1", PORT, timeout=60)
    c9.request("GET", p9, headers={"Host": HOST})
    r9 = c9.getresponse()
    b9, hd9 = r9.read(), {k.lower(): v for k, v in r9.getheaders()}
    c9.close()
    with open(os.path.join(T.ROOT, "web", "v2", p9[4:]), "rb") as f9:
        want9 = f9.read()
    chk(r9.status == 200 and hd9.get("content-type") == ct9 and hd9.get("x-content-type-options") == "nosniff" and b9 == want9,
        "A5 쿠키 없이 %s = 200 · %s · nosniff · 파일 글 그대로(CSS 를 JS MIME 으로 내면 스타일이 안 먹음)" % (p9, ct9), (r9.status, hd9.get("content-type")))
st, hd, _j, _ = req("GET", "/v2/app.css")
chk(st == 401 and hd.get("x-tj-login") == "required", "A6 쿠키 없이 앱 CSS(/v2/app.css) = 401(세션 필요 · /v2/app.js 와 같음 · 로그인 화면 CSS 만 공개)", st)

st, _hd, j, sc = req("POST", "/api/login", body={"password": PW + "x"})
chk(st == 401 and not token(sc), "B1 틀린 비밀번호 = 401 · 쿠키 없음", (st, sc))
LL.LIM = LL.Limiter()
st, _hd, j, sc = req("POST", "/api/login", body={"password": PW})
tok = token(sc)
ck = next((s for s in sc if s.startswith(LA.COOKIE + "=")), "")
chk(st == 200 and tok and "HttpOnly" in ck and "SameSite=Strict" in ck, "B2 맞는 비밀번호 = 200 + 세션 쿠키(HttpOnly · SameSite=Strict)", (st, ck[:120]))
st, _hd, j, _ = req("GET", "/api/setup/status", cookie=tok)
csrf = (j or {}).get("csrf")
chk(st == 200 and csrf, "B3 세션 쿠키로 설정 API = 200 + CSRF 토큰", (st, str(j)[:200]))
chk(csrf == LA._sess_csrf(tok) and csrf != ss.csrf_token(), "B3b CSRF = 이 세션의 CSRF(설치 토큰 아님 · A2)", csrf == ss.csrf_token())
st, _hd, j, _ = req("GET", "/api/setup/status", cookie="x" * 43)
chk(st == 401, "B4 지어낸 세션 쿠키 = 401", st)

for bad_host in ("evil.example", f"evil.example:{PORT}", "127.0.0.1.nip.io"):
    st, _hd, j, _ = req("GET", "/api/setup/status", cookie=tok, host=bad_host)
    chk(st == 421, f"C 허용 안 된 Host '{bad_host}' = 421(세션 있어도)", (st, j))

st, _hd, j, _ = req("POST", "/api/setup/prefs", body={"currency": "USD"}, cookie=tok, origin=None, headers={"X-TJ-CSRF": csrf})
chk(st == 403, "D1 Origin 없는 쓰기 POST = 403", (st, j))
st, _hd, j, _ = req("POST", "/api/setup/prefs", body={"currency": "USD"}, cookie=tok, origin="http://evil.example", headers={"X-TJ-CSRF": csrf})
chk(st == 403, "D2 다른 출처 Origin = 403", (st, j))
st, _hd, j, _ = req("POST", "/api/setup/prefs", body={"currency": "USD"}, cookie=tok)
chk(st == 403, "D3 CSRF 없음 = 403", (st, j))
st, _hd, j, _ = req("POST", "/api/setup/prefs", body={"currency": "USD"}, cookie=tok, headers={"X-TJ-CSRF": "0" * 43})
chk(st == 403, "D4 틀린 CSRF = 403", (st, j))
st, _hd, j, _ = req("POST", "/api/setup/prefs", body={"currency": "USD"}, cookie=tok, headers={"X-TJ-CSRF": ss.csrf_token()})
chk(st == 403 and "CSRF" in str((j or {}).get("error")), "D4b 로그인 켬 + 설치 토큰 = 403(세션 CSRF 만 · A2)", (st, j))
st, _hd, j, _ = req("POST", "/api/setup/prefs", body={"currency": "USD"}, cookie=tok, headers={"X-TJ-CSRF": csrf})
chk(st == 200 and (j or {}).get("ok"), "D5 같은 출처 + 맞는 CSRF = 200(대조군)", (st, j))

import logging  # noqa: E402
import socket  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402


class _Cap(logging.Handler):
    def __init__(self):
        super().__init__()
        self.rows = []

    def emit(self, record):
        self.rows.append((record.levelno, record.getMessage()))


def login_as(web_cfg):
    cap, lg = _Cap(), logging.getLogger("tj-web")
    lg.addHandler(cap)
    try:
        LA.init(dict(CFG, web=web_cfg))
    finally:
        lg.removeHandler(cap)
    st_l, _hd_l, _j_l, sc_l = req("POST", "/api/login", body={"password": PW})
    ck_l = next((x for x in sc_l if x.split("=", 1)[0] in (LA.COOKIE, "__Host-" + LA.COOKIE) and "Max-Age=0" not in x), "")
    return st_l, ck_l, sum(1 for lv, _m in cap.rows if lv >= logging.ERROR)


def has_secure(ck):
    return any(a.strip() == "Secure" for a in ck.split(";")[1:])


def tok_of(ck):
    return ck.split(";", 1)[0].split("=", 1)[1] if ck else None


st, ck, ne = login_as({"port": 8023, "bind": "loopback", "behind_proxy": True})
chk(st == 200 and ck.startswith("__Host-" + LA.COOKIE + "=") and has_secure(ck) and ne == 0,
    "G1 behind_proxy: true(X-Forwarded-Proto 없음) = Set-Cookie 에 Secure · 이름 __Host-tj_session · 기동 ERROR 없음", (st, ck[:140], ne))
tok_proxy = tok_of(ck)
st, ck, ne = login_as({"port": 8023, "bind": "loopback", "behind_proxy": True, "login": {"secure_cookie": False}})
chk(st == 200 and ck.startswith(LA.COOKIE + "=") and not has_secure(ck) and ne == 1,
    "G2 behind_proxy + secure_cookie: false 명시 = Secure 없음(이름 tj_session) · 기동 ERROR 1줄", (st, ck[:140], ne))
st, ck, ne = login_as({"port": 8023, "bind": "loopback", "behind_proxy": True, "login": {"secure_cookie": "false"}})
chk(st == 200 and has_secure(ck), "G2b secure_cookie 글자 'false' = 명시 false 아님 → Secure 그대로", (st, ck[:140]))
st, ck, ne = login_as({"port": 8023, "bind": "loopback"})
tok_plain = tok_of(ck)
chk(st == 200 and ck.startswith(LA.COOKIE + "=") and not has_secure(ck) and ne == 0,
    "G3 반대 방향: behind_proxy 없음 + 루프백 HTTP = Secure 없음 · 이름 tj_session(종전 그대로)", (st, ck[:140], ne))
LA.init(dict(CFG, web={"port": 8023, "bind": "loopback", "behind_proxy": True}))
st, _hd, _j, _sc = req("GET", "/api/state", headers={"Cookie": f"{LA.COOKIE}={tok_plain}"})
chk(st == 401, "G4 배포 직후: behind_proxy 설치의 옛 이름 쿠키(tj_session) = 401 → 한 번 다시 로그인(세션 기록은 서버에 남음)", st)
st, _hd, _j, _sc = req("GET", "/api/state", headers={"Cookie": f"__Host-{LA.COOKIE}={tok_proxy}"})
chk(st == 200, "G4b 새 이름 쿠키(__Host-tj_session) = 200", st)
LA.init(dict(CFG, web={"port": 8023, "bind": "loopback", "behind_proxy": True, "login": {"secure_cookie": False}}))
st, _hd, _j, _sc = req("GET", "/api/state", headers={"Cookie": f"__Host-{LA.COOKIE}={tok_proxy}"})
chk(st == 401, "G4c 롤백(옛 판 = Secure 기본 없음 · secure_cookie:false 와 같은 동작) 방향: __Host- 쿠키 = 401 → 한 번 다시 로그인", st)
LA.init(CFG)

LL.LIM = LL.Limiter()
codes = [req("POST", "/api/login", body={"password": "wrong-password-%d" % i})[0] for i in range(5)]
chk(codes == [401, 401, 401, 401, 429], "E1 10분에 5번 틀리면 5번째에 잠금(429)", codes)
st, hd, j, sc = req("POST", "/api/login", body={"password": PW})
chk(st == 429 and not token(sc) and int(hd.get("retry-after", "0") or 0) > 0, "E2 잠금 중엔 맞는 비밀번호도 429 + Retry-After · 세션 없음", (st, hd.get("retry-after"), sc))

def gate(web_cfg, lan=None):
    cfg_t = dict(CFG, web=web_cfg)
    cap, lg = _Cap(), logging.getLogger("tj-web")
    lg.addHandler(cap)
    rc = None
    try:
        LA.init(cfg_t, lan=lan if lan is not None else web.extra_host(cfg_t)[0])
        if web_cfg.get("bind") != "tailscale":
            web._login_startup_warnings(cfg_t)
    except SystemExit as e:
        rc = e.code
    finally:
        lg.removeHandler(cap)
    return rc, sum(1 for lv, _m in cap.rows if lv >= logging.ERROR), " ".join(m for _lv, m in cap.rows)


OFF = {"enabled": False}
rc, ne, txt = gate({"port": 8023, "bind": "10.0.0.5", "login": OFF})
chk(rc == 2 and "기동 거부" in txt and "allow_lan_without_password" in txt and "loopback" in txt and "***" not in txt,
    "F1 로그인 꺼짐 + bind 10.0.0.5 = 기동 거부(rc 2 · 이유 + 해결법 · 허용 키 이름 · 로그 가림에 안 걸림)", (rc, txt[:300]))
rc, ne, txt = gate({"port": 8023, "bind": "10.0.0.5", "login": dict(OFF, allow_lan_without_password=True)})
chk(rc is None and ne >= 1 and "10.0.0.5" in txt, "F2 allow_lan_without_password: true = 통과 · 기동 ERROR 는 그대로", (rc, ne, txt[:300]))
rc, ne, txt = gate({"port": 8023, "bind": "10.0.0.5", "login": dict(OFF, allow_lan_without_password="true")})
chk(rc == 2, "F2b 허용 키는 참·거짓 true 만(글자 'true' = 거부)", rc)
rc, _ne, _txt = gate({"port": 8023, "bind": "tailscale", "login": OFF}, lan="100.101.102.103")
chk(rc == 2, "F3 로그인 꺼짐 + bind tailscale(테일넷 IP 있음) = 기동 거부", rc)
rc, _ne, _txt = gate({"port": 8023, "bind": "tailscale", "login": OFF}, lan="")
chk(rc == 2, "F3b 테일스케일이 기동 때 꺼져 IP 가 없어도 거부(60초 뒤 붙는 길 막음 — 설정 의도로 판정)", rc)
rc, _ne, _txt = gate({"port": 8023, "bind": "tailscale", "login": dict(OFF, allow_lan_without_password=True)}, lan="")
chk(rc is None, "F3c bind tailscale + 허용 키 = 통과", rc)
rc, _ne, _txt = gate({"port": 8023, "bind": "100.70.1.2", "login": OFF})
chk(rc == 2, "F3d 로그인 꺼짐 + 테일넷(CGNAT) 명시 IP = 기동 거부", rc)
for bind_t in ("loopback", "127.0.0.1", "0.0.0.0", "8.8.8.8", None):
    web_t = {"port": 8023, "login": OFF}
    if bind_t is not None:
        web_t["bind"] = bind_t
    rc, ne, _txt = gate(web_t)
    chk(rc is None and ne == 1, f"F4 반대 방향: 로그인 꺼짐 + bind {bind_t!r}(추가 주소 없음 · 루프백 전용) = 그대로 기동(종전 ERROR 1줄)", (rc, ne))
rc, ne, _txt = gate({"port": 8023, "bind": "10.0.0.5"})
chk(rc is None and ne == 0, "F4b 반대 방향: 로그인 켜짐(기본) + bind 10.0.0.5 = 그대로 기동(거부·ERROR 없음)", (rc, ne))
LA.init(CFG)

PRELUDE = r"""
import os, runpy, socket, sys
WEB = sys.argv[1]
LOOP = ("127.0.0.1", "::1", "localhost")
_c, _ce, _g = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo
def _bad(h):
    return h is not None and h not in LOOP
def connect(self, a):
    if _bad(a[0] if isinstance(a, tuple) else None):
        raise OSError("test: blocked")
    return _c(self, a)
def connect_ex(self, a):
    if _bad(a[0] if isinstance(a, tuple) else None):
        raise OSError("test: blocked")
    return _ce(self, a)
def gai(host, *a, **k):
    h = host.decode() if isinstance(host, bytes) else host
    if _bad(h):
        raise socket.gaierror("test: blocked")
    return _g(host, *a, **k)
socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = connect, connect_ex, gai
sys.argv = [WEB]
sys.path.insert(0, os.path.dirname(WEB))
runpy.run_path(WEB, run_name="__main__")
"""
WEB_PY = os.path.join(T.SRC, "web.py")
LINKS = [(nm, os.path.join(T.ROOT, nm)) for nm in ("web", "seed", "tools", "VERSION", "config.example.json")]


def run_web(tag, login):
    base = os.path.join(T.TMP, "f5_" + tag)
    os.makedirs(os.path.join(base, "state"))
    for nm, src in LINKS:
        if os.path.exists(src):
            os.symlink(src, os.path.join(base, nm))
    sk = socket.socket()
    sk.bind(("127.0.0.1", 0))
    port = sk.getsockname()[1]
    sk.close()
    with open(os.path.join(base, "config.json"), "w", encoding="utf-8") as fh:
        json.dump(dict(CFG, web={"port": port, "bind": "10.0.0.5", "login": login}), fh, ensure_ascii=False)
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_")}
    env.update(TJ_BASE=base, PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(k, None)
    p = subprocess.Popen([sys.executable, "-c", PRELUDE, WEB_PY], env=env, cwd=base, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, errors="replace", preexec_fn=T.sigint_default)
    up, t0 = False, time.time()
    while time.time() - t0 < 90 and p.poll() is None:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            up = True
            break
        except OSError:
            time.sleep(0.3)
    if p.poll() is None:
        p.send_signal(2)
    try:
        out, _e = p.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        p.kill()
        out, _e = p.communicate(timeout=10)
    return p.returncode, up, out or ""


rc, up, out = run_web("deny", OFF)
chk(rc == 2 and not up and out.count("기동 거부") == 1 and out.count("Traceback") == 0,
    "F5 실제 web.py: 로그인 꺼짐 + bind 10.0.0.5 = rc 2 · 루프백 포트도 안 엶 · 이유 한 줄(트레이스백 없음)", (rc, up, out[-600:]))
rc, up, out = run_web("allow", dict(OFF, allow_lan_without_password=True))
chk(up and out.count("기동 거부") == 0 and out.count("allow_lan_without_password") >= 1,
    "F5b 실제 web.py: allow_lan_without_password: true = 기동(루프백 포트 열림 · ERROR 안내 유지)", (rc, up, out[-600:]))

LA.init(CFG)
os.unlink(LA.AUTH_PATH)
LL.LIM.reset()
chk(LA.password_state()[0] == "none", "H0 비밀번호 파일 지움 = 첫 실행 상태", LA.password_state()[0])
hs = [req("POST", "/api/auth/setup", body={"code": "AAAA-BBBB-CCCC-DDD%d" % i, "password": PW}) for i in range(6)]
chk([x[0] for x in hs] == [403, 403, 403, 403, 403, 429] and int(hs[5][1].get("retry-after", "0") or 0) > 0 and (hs[5][2] or {}).get("retryAfter"),
    "H1 설정 코드 5번 틀림 = 403 · 6번째 = 429 + Retry-After(10분 5번 → 잠금)", [(x[0], x[1].get("retry-after")) for x in hs])
good = LA.setup_code()
st, hd, j, sc = req("POST", "/api/auth/setup", body={"code": good, "password": PW})
chk(st == 429 and not token(sc) and LA.password_state()[0] == "none", "H2 잠금 중엔 맞는 코드도 429 · 비밀번호 안 만듦", (st, j))
st, _hd, _j, _sc = req("POST", "/api/login", body={"password": PW + "x"})
chk(st == 409 and LL.LIM.wait("127.0.0.1", True) == 0 and LL.LIM.left("127.0.0.1") == LL.FAIL_MAX
    and LL.LIM.wait("s:127.0.0.1", True) > 0 and not LL.LIM.glob,
    "H3 설정 코드 잠금 = s: 버킷만(로그인 버킷 실패 0·잠금 없음 · 전역 실패 목록 비어 있음)", (st, sorted(LL.LIM.ip), len(LL.LIM.glob)))
LL.LIM.reset()
for i in range(4):
    req("POST", "/api/auth/setup", body={"code": "AAAA-BBBB-CCCC-DDE%d" % i, "password": PW})
st, _hd, _j, _sc = req("POST", "/api/auth/setup", body={"password": PW})
chk(st == 403 and LL.LIM.left("s:127.0.0.1") == 1, "H4 빈 코드(아직 안 넣음) = 시도로 안 셈", (st, LL.LIM.left("s:127.0.0.1")))
st, hd, j, sc = req("POST", "/api/auth/setup", body={"code": good, "password": PW})
chk(st == 200 and token(sc) and LA.password_state()[0] == "set" and LL.LIM.left("s:127.0.0.1") == LL.FAIL_MAX,
    "H5 반대 방향: 4번 틀린 뒤 맞는 코드 = 200 · 비밀번호 만듦 · 실패 기록 비움", (st, j, LL.LIM.left("s:127.0.0.1")))

SRV.shutdown()
SRV.server_close()
T.finish()
