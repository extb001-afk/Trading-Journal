#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _sec_lint as L  # noqa: E402
import _harness as T  # noqa: E402

import hmac  # noqa: E402
import http.client  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

t0 = time.time()
PUB_HOST = "tj.example.test"
TS_HOST = "tjbox.tail0a1b2c.ts.net"
with open(os.path.join(T.ROOT, "config.example.json"), encoding="utf-8") as f:
    CFG = json.load(f)
CFG["wallets"], CFG["exchange_addresses"] = [], []
CFG["web"] = {"port": 8023, "bind": "loopback", "allowed_hosts": [PUB_HOST]}
CFG.setdefault("balance_check", {})["enabled"] = False
with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump(CFG, f, ensure_ascii=False)

import paths  # noqa: E402
import login_auth as LA  # noqa: E402
import settings_store as ss  # noqa: E402
import web  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

assert T.TMP in paths.CONFIG_PATH
CFG_OFF = json.loads(json.dumps(CFG))
CFG_OFF["web"]["login"] = {"enabled": False}
SRV = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
PORT = SRV.server_address[1]
LOOP_HOST = "127.0.0.1:%d" % PORT
threading.Thread(target=SRV.serve_forever, daemon=True, name="t-auth-holes").start()

HOLES = set()
VERDICT = {}


def verdict(name, hole, closed, why):
    if hole and not closed:
        HOLES.add(name)
        VERDICT[name] = "뚫림"
    elif closed and not hole:
        VERDICT[name] = "막힘"
    else:
        VERDICT[name] = "판정 불가"
        T.chk(False, "%s: 뚫림·막힘 어느 응답도 아님(시험 대역 고장)" % name, why)


def _apply(jar, cookies):
    for raw in cookies:
        part = raw.split(";")
        k, _, v = part[0].strip().partition("=")
        attrs = {a.strip().split("=", 1)[0].lower(): (a.strip().split("=", 1) + [""])[1] for a in part[1:]}
        if not v or attrs.get("max-age") == "0":
            jar.pop(k, None)
        else:
            jar[k] = v


def req(method, path, hdr=None, body=None, jar=None, host=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=60)
    h = {"Host": host or LOOP_HOST}
    h.update(hdr or {})
    if jar:
        h["Cookie"] = "; ".join("%s=%s" % kv for kv in jar.items())
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
        h.setdefault("Origin", ("https://" if h.get("X-Forwarded-Proto") == "https" else "http://") + h["Host"])
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    raw = r.read()
    cookies = r.headers.get_all("Set-Cookie") or []
    c.close()
    if jar is not None:
        _apply(jar, cookies)
    try:
        js = json.loads(raw.decode("utf-8"))
    except ValueError:
        js = None
    return r.status, js, cookies


def px(ip=None, https=False):
    d = {"Cf-Ray": "8f1e2d3c4b5a6978-ICN"}
    if ip:
        d["X-Forwarded-For"] = ip
    if https:
        d["X-Forwarded-Proto"] = "https"
    return d


TS_SERVE = {"Tailscale-User-Login": "owner@example.test", "Tailscale-User-Name": "Example Owner",
            "Tailscale-User-Profile-Pic": "https://example.test/pic.png", "Tailscale-Headers-Info": "https://example.test/s/serve-headers",
            "Tailscale-App-Capabilities": "{}"}
TS_FUNNEL = {"Tailscale-Funnel-Request": "?1", "Tailscale-Ingress-Target": TS_HOST + ":443"}
TS_FWD = {"X-Forwarded-For": "100.101.102.103", "X-Forwarded-Proto": "http", "X-Forwarded-Host": TS_HOST}
TS_ONLY = (("serve", TS_SERVE), ("funnel", TS_FUNNEL))
TS_FULL = (("serve+fwd", dict(TS_SERVE, **TS_FWD)), ("funnel+fwd", dict(TS_FUNNEL, **TS_FWD)))


def init(cfg):
    LA.init(cfg)


GOOD = "Synthetic-Holes-Pass-4417"


def new_password():
    return LA.set_password(GOOD, iters=200_000)


def login(hdr, jar, host=None, pw=GOOD):
    return req("POST", "/api/login", hdr, {"password": pw}, jar=jar, host=host)


def csrf_of(hdr, jar, host=None):
    st, js, _c = req("GET", "/api/auth/status", hdr, jar=jar, host=host)
    return (js or {}).get("csrf") if st == 200 else None


print("[a4] 로그인 꺼짐 + Tailscale 헤더")
init(CFG_OFF)
for nm, hd in TS_FULL:
    st, js, _c = req("GET", "/api/auth/status", hd, host=TS_HOST)
    T.chk(st == 403, "대조 ①(%s): X-Forwarded-* 같이 온 테일스케일 요청 = 지금도 프록시로 보고 403(로그인 꺼짐)" % nm, (st, js))
st_ok, js_ok, _c = req("GET", "/api/auth/status")
T.chk(st_ok == 200 and (js_ok or {}).get("enabled") is False, "대조: 로그인 꺼짐 · 헤더 없는 루프백 직접 = 200", (st_ok, js_ok))
res = [req("GET", "/api/auth/status", hd, host=TS_HOST) for _n, hd in TS_ONLY]
verdict("a4:ts_off_open", any(r[0] == 200 for r in res), all(r[0] == 403 for r in res), [(r[0], r[1]) for r in res])

print("[a4] 비밀번호 없음 + Tailscale 헤더 + 루프백 Host")
init(CFG)
T.chk(LA.password_state()[0] == "none", "시작 = 비밀번호 없음(새 임시 폴더)")
_st, js_d, _c = req("GET", "/api/auth/status")
T.chk((js_d or {}).get("canSetup") is True, "대조: 루프백 직접 = 첫 비밀번호 만들기 가능", js_d)
for nm, hd in TS_FULL:
    _st, js, _c = req("GET", "/api/auth/status", hd)
    T.chk((js or {}).get("canSetup") is False, "대조 ①(%s): X-Forwarded-* 같이 = 첫 비밀번호 불가" % nm, js)
res = [req("GET", "/api/auth/status", hd)[1] or {} for _n, hd in TS_ONLY]
verdict("a4:ts_setup", any(r.get("canSetup") is True for r in res), all(r.get("canSetup") is False for r in res), res)

print("[a4] 내부 토큰 + Tailscale 헤더")
new_password()
itok = LA.internal_token(False)
T.chk(bool(itok), "내부 토큰 파일 있음(로그인 켜짐)")
st_d, _js, _c = req("GET", "/api/zz_holes_probe", {"X-TJ-Internal": itok})
T.chk(st_d != 401, "대조: 루프백 직접 + 내부 토큰 = 로그인 게이트 통과", st_d)
for nm, hd in TS_FULL:
    st, _js, _c = req("GET", "/api/zz_holes_probe", dict(hd, **{"X-TJ-Internal": itok}), host=TS_HOST)
    T.chk(st == 401, "대조 ①(%s): X-Forwarded-* 같이 = 내부 토큰 거부(401)" % nm, st)
sts = [req("GET", "/api/zz_holes_probe", dict(hd, **{"X-TJ-Internal": itok}), host=TS_HOST)[0] for _n, hd in TS_ONLY]
verdict("a4:ts_internal", any(s == st_d for s in sts), all(s == 401 for s in sts), (st_d, sts))

print("[a6] HTTPS(루프백 프록시 X-Forwarded-Proto: https) 세션 쿠키")
jar_s = {}
st, js, ck = login(px("203.0.113.50", https=True), jar_s, host=PUB_HOST)
T.chk(st == 200, "HTTPS 프록시 경유 로그인 = 200", (st, js))
names = [c.split("=", 1)[0] for c in ck if c.split(";")[0].partition("=")[2]]
sess_names = [n for n in names if n.endswith("tj_session")]
verdict("a6:https_plain_name", sess_names == ["tj_session"], bool(sess_names) and all(n.startswith("__Host-") for n in sess_names), ck)
jar_p = {}
st, js, _c = login({}, jar_p)
T.chk(st == 200 and jar_p.get("tj_session"), "평문 HTTP 루프백 로그인 = tj_session 쿠키", (st, js, jar_p.keys()))
st, js, _c = req("GET", "/api/auth/status", px("203.0.113.50", https=True), jar={"tj_session": jar_p.get("tj_session", "")}, host=PUB_HOST)
verdict("a6:https_plain_accepted", st == 200 and (js or {}).get("authed") is True, st == 200 and (js or {}).get("authed") is False, (st, js))

print("[a2] 세션 CSRF")
jar_a = {}
st, _js, _c = login({}, jar_a)
T.chk(st == 200, "루프백 직접 로그인 = 200", st)
inst = ss.csrf_token()
st, js, _c = req("GET", "/api/setup/status", jar=jar_a)
T.chk(st == 200 and bool((js or {}).get("csrf")), "로그인 상태 /api/setup/status = 200 + csrf", (st, (js or {}).keys()))
got = (js or {}).get("csrf") or ""
verdict("a2:install_supplied", hmac.compare_digest(got, inst), bool(got) and not hmac.compare_digest(got, inst), [got == inst])
out, opened, closed = [], [], []
for path9, body9, want_st9, want_err9 in (("/api/setup/zz_holes_probe", {}, 400, "알 수 없는 요청"),
                                          ("/api/health/restore", {"check": "zz_holes_probe"}, 409, "닫은 기록이 없어요"),
                                          ("/api/logout", {}, 200, "")):
    st, js, _c = req("POST", path9, {"X-TJ-CSRF": inst}, body9, jar=jar_a)
    err9 = (js or {}).get("error", "")
    out.append((path9, st, err9))
    opened.append(st == want_st9 and want_err9 in err9 and (st != 200 or (js or {}).get("ok") is True))
    closed.append(st == 403 and "CSRF" in err9)
    T.chk(opened[-1] or closed[-1], "설치 토큰 POST %s = 처리기 도달 또는 CSRF 거부(그 밖 응답 = 판정 불가)" % path9, out[-1])
verdict("a2:install_accepted", any(opened), all(closed), out)

print("[a3] 프록시 경유 POST /api/setup/*")
jar_x = {}
st, _js, _c = login(px("203.0.113.60", https=True), jar_x, host=PUB_HOST)
T.chk(st == 200, "프록시 경유 로그인 = 200", st)
st, js, _c = req("GET", "/api/setup/status", px("203.0.113.60", https=True), jar=jar_x, host=PUB_HOST)
tok_x = (js or {}).get("csrf") if st == 200 else None
tok_x = tok_x or csrf_of(px("203.0.113.60", https=True), jar_x, host=PUB_HOST)
T.chk(bool(tok_x), "프록시 경유 세션의 CSRF 토큰 받음(/api/setup/status 또는 /api/auth/status)", st)
st, js, _c = req("POST", "/api/setup/zz_holes_probe", dict(px("203.0.113.60", https=True), **{"X-TJ-CSRF": tok_x or ""}), {}, jar=jar_x, host=PUB_HOST)
err = (js or {}).get("error", "")
verdict("a3:setup_via_proxy", st == 400 and "알 수 없는" in err, st == 403 and "CSRF" not in err and "Origin" not in err, (st, js))
if VERDICT.get("a3:setup_via_proxy") == "막힘":
    T.chk("setup_allow_proxy" in err, "A3: 프록시 경유 설정 쓰기 403 문구가 켜는 법(web.setup_allow_proxy)을 알려 줌", err)
    st_g, _js, _c = req("GET", "/api/setup/status", px("203.0.113.60", https=True), jar=jar_x, host=PUB_HOST)
    T.chk(st_g == 200, "A3: 프록시 경유 설정 읽기(GET /api/setup/status — 화면의 CSRF 공급) = 그대로 200", st_g)

    def _setup_post(hdr, host):
        return req("POST", "/api/setup/zz_holes_probe", dict(hdr, **{"X-TJ-CSRF": tok_x or ""}), {}, jar=jar_x, host=host)[0]
    cfg_path = os.path.join(T.TMP, "config.json")
    cfg_on = json.loads(json.dumps(CFG))
    cfg_on["web"]["setup_allow_proxy"] = True
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg_on, f, ensure_ascii=False)
    T.chk(_setup_post(px("203.0.113.60", https=True), PUB_HOST) == 400, "A3: web.setup_allow_proxy=true 면 프록시 경유 설정 쓰기 = 게이트 통과(종전 동작)")
    for bad in ('{"web": {"setup_allow_proxy": "true"}}', "{not json"):
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write(bad)
        st_b = _setup_post(px("203.0.113.60", https=True), LOOP_HOST)
        T.chk(st_b == 403, "A3: setup_allow_proxy 가 true(불) 아님·config 읽기 실패 = 거부(403)", (bad[:20], st_b))
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(CFG, f, ensure_ascii=False)
    jar_l = {}
    T.chk(login({}, jar_l)[0] == 200, "A3: 루프백 직접 로그인 = 200")
    st_l, js_l, _c = req("GET", "/api/setup/status", jar=jar_l)
    tok_l = (js_l or {}).get("csrf") if st_l == 200 else ""
    st_l = req("POST", "/api/setup/zz_holes_probe", {"X-TJ-CSRF": tok_l or ""}, {}, jar=jar_l, host=LOOP_HOST)[0]
    T.chk(st_l == 400, "A3: 루프백 직접 접속 설정 쓰기 = 그대로 통과(기본 false 에서도)", st_l)

print("[a1] 로그인 가용성 — 전에 로그인했던 기기")


def owner_device(hdr, host=PUB_HOST):
    new_password()
    jar = {}
    st, js, _c = login(hdr, jar, host=host)
    T.chk(st == 200, "기기 첫 로그인 = 200", (st, js))
    tok = csrf_of(hdr, jar, host=host)
    st, js, _c = req("POST", "/api/logout", dict(hdr, **{"X-TJ-CSRF": tok or ""}), {}, jar=jar, host=host)
    T.chk(st == 200, "로그아웃 = 200", (st, js))
    return jar


jar1 = owner_device(px("198.51.100.10"))
for i in range(50):
    st, _js, _c = login(px("192.0.2.%d" % (i + 1)), {}, host=PUB_HOST, pw="wrong-pass-%d" % i)
T.chk(st == 401, "남의 실패 50번(각기 다른 IP · 버킷마다 1번) 기록됨", st)
st, js, _c = login(px("198.51.100.10"), dict(jar1), host=PUB_HOST)
verdict("a1:device_global_lock", st == 429, st == 200, (st, js))
jar2 = owner_device(px())
for i in range(5):
    st, _js, _c = login(px(), {}, host=PUB_HOST, pw="wrong-pass-%d" % i)
T.chk(st == 429, "XFF 없는 프록시 버킷 5번 실패 = 잠김(429)", st)
st, js, _c = req("GET", "/api/auth/status", px(), jar=dict(jar2), host=PUB_HOST)
T.chk(st == 200 and (js or {}).get("authed") is False, "잠금 중 기기 상태 조회 = 200 · 세션 없음", (st, js))
verdict("a1:status_retry_device", "retryAfter" in (js or {}), st == 200 and "retryAfter" not in (js or {}), (st, js))
st, js, _c = login(px(), dict(jar2), host=PUB_HOST)
verdict("a1:device_shared_bucket", st == 429, st == 200, (st, js))
jar3 = owner_device(px("198.51.100.20"))
import login_limits as _LL   # noqa: E402
SEM = _LL.HASH_SEM
held = 0
while held < 64 and SEM.acquire(blocking=False):
    held += 1
T.chk(1 <= held < 64, "공용 PBKDF2 칸을 다 잡음(시험 대역 동작)", held)
OWN = []
tho = threading.Thread(target=lambda: OWN.append(login(px("198.51.100.20"), dict(jar3), host=PUB_HOST)[0]), daemon=True, name="t-holes-own")
try:
    tho.start()
    tho.join(3)
    starved = tho.is_alive()
    fast = list(OWN)
finally:
    for _i in range(held):
        SEM.release()
tho.join(30)
T.chk(OWN and OWN[0] == 200, "칸을 놓아 주면 기기 로그인 = 200(칸을 기다리던 요청이 이어감)", OWN)
verdict("a1:pbkdf2_starve", starved, not starved and fast == [200], (held, starved, fast, OWN))
SRV.shutdown()
SRV.server_close()

print("[a4] 정적 — src 에 Tailscale-User-* 를 읽는 곳 없음(접두어 'tailscale-' 는 프록시 표식으로만)")
import ast  # noqa: E402

ts_use = []
for fn in sorted(os.listdir(T.SRC)):
    if fn.endswith(".py"):
        with open(os.path.join(T.SRC, fn), encoding="utf-8") as f:
            tree = ast.parse(f.read(), fn)
        ts_use += ["%s:%d" % (fn, n.lineno) for n in ast.walk(tree)
                   if isinstance(n, ast.Constant) and isinstance(n.value, str) and "tailscale-user" in n.value.lower()]
T.chk(not ts_use, "Tailscale-User-* 신원 헤더 이름이 src 문자열에 없음(신원 헤더 = 인증 근거 아님 — 로그인·세션만)", ts_use)

print("\n구멍별 판정:")
for k in sorted(VERDICT):
    print("  %-26s %s" % (k, VERDICT[k]))
ALL12 = {"a1:device_global_lock", "a1:device_shared_bucket", "a1:status_retry_device", "a1:pbkdf2_starve", "a2:install_accepted",
         "a2:install_supplied", "a3:setup_via_proxy", "a4:ts_off_open", "a4:ts_setup", "a4:ts_internal", "a6:https_plain_name",
         "a6:https_plain_accepted"}
T.chk(set(VERDICT) == ALL12, "12개 구멍 모두 판정함", sorted(ALL12 ^ set(VERDICT)))
DOC = ("3막 인증 알려진 구멍(A0 재현) — '묶음:구멍'(test_sec_auth_holes 머리글 표). 고치면 --update-lower 로 빠짐: "
       "a1 = A1b 등록 기기 · a2 = A2 세션 CSRF · a3 = A3 설정 쓰기 터널 우회 · a4 = A4 Tailscale 헤더 · a6 = A6 __Host- 쿠키")
had = L.load_baseline("auth")
L.known_list(T, "auth", "hole", sorted(HOLES), DOC,
             "새 인증 구멍 — 그 요청이 막혀야 함(머리글 표의 판정 참고 · 프록시 판별 = login_auth/reqclass · 설정 API = onboarding)")
if had is not None and not L.UPDATE_LOWER:
    stale = sorted(k for k in (had.get("metrics") or {}).get("hole", {}) if k not in HOLES and VERDICT.get(k) == "막힘")
    T.chk(not stale, "기준선에 있는데 이제 막힌 구멍 없음 — 있으면 `python3 public/tests/test_sec_auth_holes.py --update-lower` 로 기준선에서 빼라", stale)
print("(시간 %.1f초)" % (time.time() - t0))
T.finish()
