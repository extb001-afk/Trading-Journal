#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import email.message  # noqa: E402
import http.client  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402
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
import login_device as LD  # noqa: E402
import login_limits as LL  # noqa: E402
import onboarding  # noqa: E402
import web  # noqa: E402

chk = T.chk
assert os.path.dirname(LA.DEV_PATH) == paths.STATE_DIR == os.path.join(T.TMP, "state")
LA.init(CFG)
LL.LIM.reset()
PW = "Synthetic-Device-Otter-5512"
LA.set_password(PW)

SRV = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
PORT = SRV.server_address[1]
threading.Thread(target=SRV.serve_forever, daemon=True, name="t-login-device").start()
ORIGIN = f"http://127.0.0.1:{PORT}"
HOST = f"127.0.0.1:{PORT}"


def req(method, path, body=None, cookies=None, xff=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=60)
    h = {"Host": HOST}
    if xff:
        h["X-Forwarded-For"] = xff
    if method == "POST":
        h["Origin"] = ORIGIN
        h["Content-Type"] = "application/json"
    if cookies:
        h["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items() if v)
    h.update(headers or {})
    data = json.dumps(body if body is not None else {}).encode() if method == "POST" else None
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    raw = r.read()
    sc = r.msg.get_all("Set-Cookie") or []
    c.close()
    try:
        j = json.loads(raw.decode() or "null")
    except ValueError:
        j = None
    return r.status, j, sc


def ck(sc, name):
    for s in sc:
        if s.startswith(name + "="):
            return s
    return ""


def val(sc, name):
    s = ck(sc, name)
    return s.split(";", 1)[0].split("=", 1)[1] if s else None


def login(xff=None, dev=None, pw=None):
    st, j, sc = req("POST", "/api/login", body={"password": pw or PW}, cookies={LD.COOKIE: dev}, xff=xff)
    return st, j, val(sc, LA.COOKIE), val(sc, LD.COOKIE), sc


def devs():
    with open(LA.DEV_PATH, encoding="utf-8") as f:
        return json.load(f)


class H:
    def __init__(self, peer="127.0.0.1", **hdr):
        self.client_address = (peer, 50000)
        self.headers = email.message.Message()
        for k, v in hdr.items():
            self.headers[k.replace("_", "-")] = v
        self.sent = []

    def _send_bytes(self, code, raw, gz, ctype, extra=()):
        self.sent.append((code, raw))


def ctx_of(dev, xff="198.51.100.200"):
    return LA._limit_ctx(H("127.0.0.1", X_Forwarded_For=xff, Cookie=f"{LD.COOKIE}={dev}"))


print("[D1] 발급")
st, _j, stok, dev, sc = login(xff="203.0.113.5")
dck = ck(sc, LD.COOKIE)
chk(st == 200 and stok and dev and len(dev) == 43, "D1 로그인 성공 = 세션 쿠키 + 기기 쿠키(43자)", (st, sc))
chk(all(x in dck for x in ("Path=/", "HttpOnly", "SameSite=Strict", "Max-Age=%d" % (365 * 86400))) and "Secure" not in dck and "Domain" not in dck,
    "D1 기기 쿠키 = Path=/ · HttpOnly · SameSite=Strict · Max-Age 365일(HTTP = Secure 없음)", dck)
chk(stat.S_IMODE(os.stat(LA.DEV_PATH).st_mode) == 0o600, "D1 state/auth_devices.json = 0600", oct(os.stat(LA.DEV_PATH).st_mode))
raw = open(LA.DEV_PATH, encoding="utf-8").read()
rec0 = list(devs().values())[0]
chk(dev not in raw and len(devs()) == 1 and set(rec0) == {"c", "s", "pg", "sg", "e"} and rec0["e"] - rec0["c"] == 365 * 86400,
    "D1 기록 = sha256(토큰) → {c,s,pg,sg,e} · 토큰 원문 없음 · e = 발급 + 365일", rec0)
sess_raw = json.load(open(LA.SESS_PATH, encoding="utf-8"))
chk(rec0["sg"] == sess_raw.get("_g") and len(sess_raw["_g"]) >= 16, "D1 sg = 세션 파일 nonce(_g)", (rec0["sg"], sess_raw.get("_g")))
chk(ctx_of(dev)[0] == "d:" + LD.tid_of(dev)[:16] and ctx_of(dev)[1] is True, "D1 유효 기기 = 기기 버킷 'd:<tid 앞 16>' · 전역 예외", ctx_of(dev))
st, _j, _s, dev_again, sc = login(xff="203.0.113.5", dev=dev)
chk(st == 200 and dev_again is None and len(devs()) == 1, "D1 유효 기기로 다시 로그인 = 기기 쿠키 새로 안 줌(그대로) · 기록 1개", (st, sc))

print("[D2] IP 잠금·전역 상한 면제")
LL.LIM.reset()
for _i in range(5):
    LL.LIM.fail("p:203.0.113.5")
st, _j, _s, _d, _sc = login(xff="203.0.113.5")
chk(st == 429, "D2 대조군: 기기 없이 같은 IP(p:203.0.113.5 잠김) = 429", st)
st, _j, s2, _d, _sc = login(xff="203.0.113.5", dev=dev)
chk(st == 200 and s2, "D2 a1:device_shared_bucket — 기기 있으면 그 IP 가 잠겨도 로그인 200", st)
for i in range(50):
    LL.LIM.fail("p:198.51.100.%d" % (i % 13))
st, j, _s, _d, _sc = login(xff="192.0.2.44")
chk(st == 429 and (j or {}).get("retryAfter"), "D2 전역 10분 50번 초과 = 새 기기(쿠키 없음) 429(본문 읽기 전)", (st, j))
hb = H("127.0.0.1", X_Forwarded_For="192.0.2.44")
hb.rfile = None
sent = []
hb._send_bytes = lambda code, raw, gz, ctype, extra=(): sent.append(code)
hb.headers["Origin"], hb.headers["Host"], hb.headers["Content-Type"], hb.headers["Content-Length"] = ORIGIN, HOST, "application/json", "30"
LA._login(hb, onboarding)
chk(sent == [429], "D2 새 기기 전역 초과 = 본문 읽기 전 즉시 429(본문 스트림 안 건드림)", sent)
st, _j, s3, _d, _sc = login(xff="192.0.2.44", dev=dev)
chk(st == 200 and s3, "D2 a1:device_global_lock — 전역 초과여도 등록 기기는 로그인 200", st)
st, _j, s4, _d, _sc = login()
chk(st == 200 and s4, "D2 루프백 직접 접속(프록시 헤더 없음)은 기기 없이도 전역 예외 유지", st)

print("[D3] 위조 쿠키 · 기기 버킷")
st, _j, _s, _d, _sc = login(xff="192.0.2.45", dev="A" * 43)
chk(st == 429 and ctx_of("A" * 43, "192.0.2.45") == ("p:192.0.2.45", False, None), "D3 위조 기기 쿠키 = 일반 경로(전역 초과면 429)", st)
g0 = len(LL.LIM.glob)
codes = [login(xff="192.0.2.46", dev=dev, pw="wrong-%d-password" % i)[0] for i in range(5)]
chk(codes == [401, 401, 401, 401, 429], "D3 기기로 5번 틀림 = 4번 401 · 5번째 429(그 기기 버킷 15분)", codes)
chk(len(LL.LIM.glob) == g0, "D3 기기 버킷 실패는 전역 목록에 안 들어감", (len(LL.LIM.glob), g0))
chk(LL.LIM.wait("d:" + LD.tid_of(dev)[:16], True) == 900, "D3 잠긴 건 그 기기 버킷만(900초)", LL.LIM.wait("d:" + LD.tid_of(dev)[:16], True))
st, _j, _s, _d, _sc = login(xff="192.0.2.46", dev=dev)
chk(st == 429, "D3 잠긴 기기 = 맞는 비밀번호도 429", st)

print("[D4] 상태 조회 · PBKDF2 칸")
LL.LIM.reset()
for i in range(50):
    LL.LIM.fail("p:198.51.100.%d" % (i % 13))
st, j, _sc = req("GET", "/api/auth/status", xff="192.0.2.50")
chk(st == 200 and (j or {}).get("retryAfter"), "D4 대조군: 기기 없이 전역 초과 = 상태 조회 retryAfter(화면이 입력 잠금)", j)
st, j, _sc = req("GET", "/api/auth/status", xff="192.0.2.50", cookies={LD.COOKIE: dev})
chk(st == 200 and not (j or {}).get("retryAfter") and not j.get("authed"), "D4 a1:status_retry_device — 기기면 전역 초과여도 retryAfter 없음(기기 버킷 기준)", j)
held = LL.HASH_SEM.acquire(blocking=False)
try:
    st_d, _j, s5, _d, _sc = login(dev=dev)
finally:
    if held:
        LL.HASH_SEM.release()
chk(held and st_d == 200 and s5, "D4 a1:pbkdf2_starve — 공용 칸이 막혀도(밖의 폭주) 등록 기기는 기기 칸으로 로그인 200", (held, st_d))

print("[D5] 만료(절대·idle)")
tid0 = ctx_of(dev)[2]
base = float(devs()[tid0]["c"])
pg0, sg0 = devs()[tid0]["pg"], devs()[tid0]["sg"]
chk(LA.DEVICES.check(dev, pg0, sg0, now=base + 89 * 86400) == tid0, "D5 89일 미사용 = 아직 유효")
for day in (80, 160, 240, 320):
    chk(LA.DEVICES.touch(tid0, pg0, sg0, now=base + day * 86400), "D5 %d일째 사용(touch) = 유효" % day)
chk(LA.DEVICES.check(dev, pg0, sg0, now=base + 365 * 86400 - 5) == tid0 and devs()[tid0]["e"] == base + 365 * 86400,
    "D5 365일 직전 = 유효(idle 안 지남) · 절대 만료 e 는 touch 로 안 늘어남", devs().get(tid0))
chk(LA.DEVICES.check(dev, pg0, sg0, now=base + 365 * 86400 + 1) is None and tid0 not in devs(), "D5 절대 만료(발급 + 365일) — 사용 중이어도 무효 · 기록 지움",
    sorted(devs()))
tokA, _age = LA.DEVICES.issue(pg0, sg0, now=base)
chk(LA.DEVICES.check(tokA, pg0, sg0, now=base + 90 * 86400) is not None, "D5 마지막 사용 + 90일 정각 = 아직 유효")
chk(LA.DEVICES.check(tokA, pg0, sg0, now=base + 90 * 86400 + 5) is None and ctx_of(tokA)[2] is None, "D5 idle 만료(마지막 사용 + 90일) = 무효 · 기록 지움")
chk(ctx_of(dev, "192.0.2.60") == ("p:192.0.2.60", False, None), "D5 만료 기기 쿠키 = 일반 경로", ctx_of(dev, "192.0.2.60"))

print("[D6] 비밀번호 변경 · 모든 기기 로그아웃 · 로그아웃")
LL.LIM.reset()
_st, _j, sx, dx, _sc = login()
_st, _j, sy, dy, _sc = login()
chk(dx and dy and dx != dy and ctx_of(dx)[2] and ctx_of(dy)[2], "D6 기기 X·Y 등록(각 로그인)")
st, j, sc = req("GET", "/api/auth/status", cookies={LA.COOKIE: sx})
csrf_x = (j or {}).get("csrf")
st, j, sc = req("POST", "/api/logout", cookies={LA.COOKIE: sx, LD.COOKIE: dx}, headers={"X-TJ-CSRF": csrf_x})
chk(st == 200 and ctx_of(dx)[2] and not ck(sc, LD.COOKIE), "D6 로그아웃(한 기기) = 기기 유지(쿠키도 안 지움)", (st, sc))
_st, _j, sx, _d, _sc = login(dev=dx)
st, j, sc = req("GET", "/api/auth/status", cookies={LA.COOKIE: sx})
csrf_x = (j or {}).get("csrf")
st, j, sc = req("POST", "/api/auth/logout_all", cookies={LA.COOKIE: sx, LD.COOKIE: dx}, headers={"X-TJ-CSRF": csrf_x})
chk(st == 200 and ctx_of(dx)[2] and ctx_of(dy)[2] is None and ctx_of(dev)[2] is None and len(devs()) == 1,
    "D6 모든 기기 로그아웃 = 이 기기(X)만 남김 · 다른 기기(Y·처음 기기) 무효", sorted(devs()))
_st, _j, sx, _d, _sc = login(dev=dx)
_st, _j, sy, dy, _sc = login()
st, j, sc = req("GET", "/api/auth/status", cookies={LA.COOKIE: sx})
csrf_x = (j or {}).get("csrf")
NEWPW = "Synthetic-Device-Heron-7740"
st, j, sc = req("POST", "/api/auth/password", body={"current": PW, "new": NEWPW}, cookies={LA.COOKIE: sx, LD.COOKIE: dx},
                headers={"X-TJ-CSRF": csrf_x})
dx2 = val(sc, LD.COOKIE)
chk(st == 200 and dx2 and dx2 != dx, "D6 비밀번호 변경 = 이 기기 새 기기 쿠키", (st, sc))
chk(ctx_of(dx)[2] is None and ctx_of(dy)[2] is None and ctx_of(dx2)[2] and list(devs()) == [LD.tid_of(dx2)],
    "D6 비밀번호 변경 뒤 옛 기기(X·Y) 전부 무효 · 기록 = 새 기기 하나", sorted(devs()))
PW = NEWPW

print("[D7] 세션 파일 재생성 · reset_password")
_st, _j, _s, dz, _sc = login()
chk(ctx_of(dz)[2], "D7 기기 Z 등록")
os.unlink(LA.SESS_PATH)
chk(ctx_of(dz)[2] is None, "D7 세션 파일 삭제(통째 다시 만들어질 상황) = 기기 무효", ctx_of(dz))
_st, _j, _s, dz2, _sc = login()
chk(dz2 and ctx_of(dz)[2] is None and ctx_of(dz2)[2], "D7 새 세션 파일(새 nonce) 뒤에도 옛 기기 무효 · 새로 로그인한 기기만 유효")
d9 = json.load(open(LA.SESS_PATH, encoding="utf-8"))
d9.pop("_g", None)
with open(LA.SESS_PATH, "w", encoding="utf-8") as f:
    json.dump(d9, f)
os.chmod(LA.SESS_PATH, 0o600)
chk(ctx_of(dz2)[2] is None, "D7 nonce 없는 세션 파일(옛 판이 다시 씀) = 기기 무효")
_st, _j, _s, dz4, _sc = login()
d9 = json.load(open(LA.SESS_PATH, encoding="utf-8"))
d9["_g"] = "Z" * 22
with open(LA.SESS_PATH, "w", encoding="utf-8") as f:
    json.dump(d9, f)
os.chmod(LA.SESS_PATH, 0o600)
chk(dz4 and ctx_of(dz4)[2] is None and LD.tid_of(dz4) in devs(), "D7 세션 파일 nonce 가 바뀜 = 기록이 남아 있어도 기기 무효(sg 대조)", sorted(devs()))
_st, _j, _s, dz3, _sc = login()
chk(dz3 and os.path.exists(LA.DEV_PATH), "D7 reset 전: 기기 파일 있음")
env = dict(os.environ, TJ_BASE=T.TMP)
proc = subprocess.run([sys.executable, "-I", "-B", os.path.join(T.ROOT, "tools", "reset_password.py"), "-y"], env=env, capture_output=True, text=True,
                      timeout=60)
chk(proc.returncode == 0 and not os.path.exists(LA.DEV_PATH) and not os.path.exists(LA.SESS_PATH), "D7 tools/reset_password.py -y = auth_devices.json 도 지움",
    (proc.returncode, proc.stdout[-300:], proc.stderr[-300:]))

print("[D8] HTTPS 쿠키 이름 · 최대 20개")
LA.set_password(PW)
LL.LIM.reset()
st, _j, sc = req("POST", "/api/login", body={"password": PW}, headers={"X-Forwarded-Proto": "https"})
hck = ck(sc, "__Host-" + LD.COOKIE)
dh = val(sc, "__Host-" + LD.COOKIE)
pck = ck(sc, LD.COOKIE)
chk(st == 200 and dh and "Secure" in hck and "Path=/" in hck and "Max-Age=%d" % (365 * 86400) in hck,
    "D8 HTTPS = __Host-tj_device + Secure · Path=/ · Max-Age 365일(login_auth.cookie_name 규칙)", (st, sc))
chk(pck.startswith(LD.COOKIE + "=;") and "Max-Age=0" in pck, "D8 HTTPS 발급 때 옛 이름 tj_device 는 지움(세션 쿠키와 같은 규칙)", pck)
hs = H("127.0.0.1", X_Forwarded_Proto="https", X_Forwarded_For="192.0.2.70", Cookie=f"{LD.COOKIE}={dh}")
hs2 = H("127.0.0.1", X_Forwarded_Proto="https", X_Forwarded_For="192.0.2.70", Cookie=f"__Host-{LD.COOKIE}={dh}")
chk(LA._limit_ctx(hs)[2] is None and LA._limit_ctx(hs2)[2], "D8 HTTPS 에선 __Host- 이름만 읽음(접두 없는 이름 = 일반 경로)")
pg1, sg1 = LA._pg(LA.password_state()[1]), json.load(open(LA.SESS_PATH))["_g"]
first = LA.DEVICES.issue(pg1, sg1)[0]
for _i in range(25):
    LA.DEVICES.issue(pg1, sg1)
chk(len(devs()) == LD.MAX_DEVICES == 20 and LA.DEVICES.check(first, pg1, sg1) is None, "D8 최대 20개 — 넘치면 마지막 사용이 오래된 것부터 뺌", len(devs()))

print("[D9] 대기 중 폐기 · 폐기 저장 실패")
LL.LIM.reset()
_st, _j, _s, dq, _sc = login()
hq = H("127.0.0.1", X_Forwarded_For="192.0.2.80", Cookie=f"{LD.COOKIE}={dq}")
ctxq = LA._limit_ctx(hq)
chk(ctxq[2], "D9 기기 Q 유효(본문을 보내기 전 판정)")
LA.DEVICES.revoke_all()
g9 = len(LL.LIM.glob)
okq, doneq = LA._verify_limited(hq, ctxq, "wrong-password-q", LA.password_state()[1], "로그인")
chk(okq is False and doneq is True and hq.sent and hq.sent[0][0] == 409 and LL.LIM.left(ctxq[0]) == 5 and len(LL.LIM.glob) == g9,
    "D9 대기 중 폐기된 기기 = 409 · 기기 버킷·전역 목록 어디에도 실패 기록 없음(면제 안 씀)", (hq.sent[:1], LL.LIM.left(ctxq[0])))
_st, _j, _s, dr, _sc = login()
sd = os.path.dirname(LA.DEV_PATH)
os.chmod(sd, 0o500)
try:
    try:
        LA.DEVICES.revoke_all()
        failed = False
    except OSError:
        failed = True
finally:
    os.chmod(sd, 0o700)
chk(failed, "D9 저장 실패 = OSError(logout_all 은 503 · 세션 무변)")
chk(LA.DEVICES.revoke_all() >= 1 and LD.tid_of(dr) not in devs() and LD.DeviceStore(LA.DEV_PATH).check(dr, *[devs().get(LD.tid_of(dr), {}).get(x) for x in ("pg", "sg")]) is None,
    "D9 저장 실패 뒤 재시도 = 디스크 다시 읽어 폐기 확정(새로 연 저장소 = 재시작에서도 무효)", sorted(devs()))

print("[D10] 일반 요청의 기기 사용 갱신")
_st, _j, sw, dw, _sc = login()
tw = LD.tid_of(dw)
d10 = devs()
old_s = d10[tw]["s"] - 89 * 86400
d10[tw]["s"] = old_s
with open(LA.DEV_PATH, "w", encoding="utf-8") as f:
    json.dump(d10, f)
os.chmod(LA.DEV_PATH, 0o600)
pgw, sgw = d10[tw]["pg"], d10[tw]["sg"]
req("GET", "/api/v2/state", cookies={LA.COOKIE: sw, LD.COOKIE: dw})
chk(LA.DEVICES.check(dw, pgw, sgw, now=old_s + 91 * 86400) == tw, "D10 세션으로 일반 API 를 쓰면 기기 마지막 사용 갱신(89일 전 → 지금 · 2일 뒤에도 유효)")
_st, _j, _s, dv, _sc = login()
d10 = devs()
d10[LD.tid_of(dv)]["s"] = old_s
with open(LA.DEV_PATH, "w", encoding="utf-8") as f:
    json.dump(d10, f)
os.chmod(LA.DEV_PATH, 0o600)
req("GET", "/api/v2/state", cookies={LD.COOKIE: dv})
chk(LA.DEVICES.check(dv, pgw, sgw, now=old_s + 91 * 86400) is None, "D10 대조군: 세션 없는 요청(401)은 기기 사용으로 안 침(idle 그대로 만료)")

SRV.shutdown()
SRV.server_close()
T.finish()
