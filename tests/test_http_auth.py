#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import http.client
import json
import os
import threading
from http.server import ThreadingHTTPServer

with open(os.path.join(T.ROOT, "config.example.json"), encoding="utf-8") as f:
    CFG = json.load(f)
CFG["wallets"], CFG["exchange_addresses"] = [], []
CFG["web"] = {"port": 8023, "bind": "loopback"}
CFG.setdefault("balance_check", {})["enabled"] = False
with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump(CFG, f, ensure_ascii=False)

import common
import login_auth as LA
import onboarding
import settings_store as ss
import web

chk = T.chk
assert T.TMP in common.STATE_DIR and T.TMP in common.CONFIG_PATH
LA.init(CFG)
LA.LIM = LA.Limiter()
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

st, _hd, j, sc = req("POST", "/api/login", body={"password": PW + "x"})
chk(st == 401 and not token(sc), "B1 틀린 비밀번호 = 401 · 쿠키 없음", (st, sc))
LA.LIM = LA.Limiter()
st, _hd, j, sc = req("POST", "/api/login", body={"password": PW})
tok = token(sc)
ck = next((s for s in sc if s.startswith(LA.COOKIE + "=")), "")
chk(st == 200 and tok and "HttpOnly" in ck and "SameSite=Strict" in ck, "B2 맞는 비밀번호 = 200 + 세션 쿠키(HttpOnly · SameSite=Strict)", (st, ck[:120]))
st, _hd, j, _ = req("GET", "/api/setup/status", cookie=tok)
csrf = (j or {}).get("csrf")
chk(st == 200 and csrf, "B3 세션 쿠키로 설정 API = 200 + CSRF 토큰", (st, str(j)[:200]))
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
st, _hd, j, _ = req("POST", "/api/setup/prefs", body={"currency": "USD"}, cookie=tok, headers={"X-TJ-CSRF": csrf})
chk(st == 200 and (j or {}).get("ok"), "D5 같은 출처 + 맞는 CSRF = 200(대조군)", (st, j))

LA.LIM = LA.Limiter()
codes = [req("POST", "/api/login", body={"password": "wrong-password-%d" % i})[0] for i in range(5)]
chk(codes == [401, 401, 401, 401, 429], "E1 10분에 5번 틀리면 5번째에 잠금(429)", codes)
st, hd, j, sc = req("POST", "/api/login", body={"password": PW})
chk(st == 429 and not token(sc) and int(hd.get("retry-after", "0") or 0) > 0, "E2 잠금 중엔 맞는 비밀번호도 429 + Retry-After · 세션 없음", (st, hd.get("retry-after"), sc))

SRV.shutdown()
SRV.server_close()
T.finish()
