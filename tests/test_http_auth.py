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

LL.LIM = LL.Limiter()
codes = [req("POST", "/api/login", body={"password": "wrong-password-%d" % i})[0] for i in range(5)]
chk(codes == [401, 401, 401, 401, 429], "E1 10분에 5번 틀리면 5번째에 잠금(429)", codes)
st, hd, j, sc = req("POST", "/api/login", body={"password": PW})
chk(st == 429 and not token(sc) and int(hd.get("retry-after", "0") or 0) > 0, "E2 잠금 중엔 맞는 비밀번호도 429 + Retry-After · 세션 없음", (st, hd.get("retry-after"), sc))

SRV.shutdown()
SRV.server_close()
T.finish()
