#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import email.message  # noqa: E402
import inspect  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402

import login_auth as LA  # noqa: E402
import login_limits as LL  # noqa: E402
import reqclass as RQ  # noqa: E402
import settings_store as ss  # noqa: E402

A3 = "(3막 A1·A2·A6 에서 의도적으로 바꾼 동작이면 이 시험의 기대값을 새 동작으로 고치세요)"
NOW = [1_790_000_000.0]
LL._now = lambda: NOW[0]


class H:

    def __init__(self, peer="127.0.0.1", **hdr):
        self.client_address = (peer, 50000)
        self.headers = email.message.Message()
        for k, v in hdr.items():
            self.headers[k.replace("_", "-")] = v
        self.sent = []

    def _send_bytes(self, code, raw, gz, ctype, extra=()):
        self.sent.append((code, raw))


print("[L1·L2] 시도 제한 순서 · 전역 상한")
T.chk((LL.FAIL_MAX, LL.LOCK_BASE, LL.GLOBAL_FAILS, LL.GLOBAL_WINDOW) == (5, 900, 50, 600),
      "로그인 제한 상수 = IP 5번 실패 · 15분 잠금 · 전역 50번 · 10분 창" + A3, (LL.FAIL_MAX, LL.LOCK_BASE, LL.GLOBAL_FAILS, LL.GLOBAL_WINDOW))
LL.LIM = LL.Limiter()
for _i in range(4):
    LL.LIM.fail("198.51.100.7")
T.chk(LL.LIM.wait("198.51.100.7", False) == 0, "IP 버킷 4번 실패 = 아직 안 잠김" + A3, LL.LIM.wait("198.51.100.7", False))
LL.LIM.fail("198.51.100.7")
w_ip = LL.LIM.wait("198.51.100.7", False)
T.chk(w_ip == 900, "IP 버킷 5번 실패 = 15분(900초) 잠금" + A3, w_ip)
for i in range(44):
    LL.LIM.fail("203.0.113.%d" % (i % 13))
T.chk(LL.LIM.wait("192.0.2.55", False) == 0, "전역 49번 실패 = 처음 보는 바깥 버킷 대기 없음" + A3, LL.LIM.wait("192.0.2.55", False))
LL.LIM.fail("203.0.113.200")
w_new = LL.LIM.wait("192.0.2.55", False)
T.chk(w_new == 600, "전역 10분 50번 실패 뒤 = 처음 보는 바깥 버킷도 600초 대기(원격 잠김 — 기기 쿠키 예외 없음)" + A3, w_new)
T.chk(LL.LIM.wait("127.0.0.1", True) == 0, "같은 상황에서 루프백 직접 접속 = 대기 없음(전역 상한 예외)" + A3)
DB = "d:0123456789abcdef"
T.chk(LL.LIM.wait(DB, True) == 0, "A1b: 같은 상황(전역 초과)에서 등록 기기 버킷 = 대기 없음(전역 상한 예외)" + A3, LL.LIM.wait(DB, True))
g0 = len(LL.LIM.glob)
for _i in range(4):
    LL.LIM.fail(DB, glob=False)
T.chk(len(LL.LIM.glob) == g0 and LL.LIM.wait(DB, True) == 0, "A1b: 기기 버킷 실패 4번 = 전역 목록에 안 들어감 · 아직 안 잠김" + A3, (len(LL.LIM.glob), g0))
LL.LIM.fail(DB, glob=False)
T.chk(LL.LIM.wait(DB, True) == 900 and len(LL.LIM.glob) == g0, "A1b: 기기 버킷 5번 실패 = 그 기기만 15분(900초) 잠금(같은 규칙)" + A3, LL.LIM.wait(DB, True))
hf = H("192.0.2.77", Cookie="tj_device=" + "A" * 43)
T.chk(LA._limit_ctx(hf) == ("192.0.2.77", False, None), "A1b: 위조 기기 쿠키 = 일반 경로(IP 버킷 · 전역 상한 적용)" + A3, LA._limit_ctx(hf))
T.chk(LL.LIM.wait("198.51.100.7", False) == w_ip, "잠긴 버킷 = 전역 대기가 아니라 그 버킷 잠금 시간(IP 잠금을 먼저 봄)" + A3, (LL.LIM.wait("198.51.100.7", False), w_ip))
src = inspect.getsource(LL.Limiter.wait)
T.chk(src.index("self.ip.get(b)") < src.index("self.glob"), "Limiter.wait 코드 순서 = 버킷 잠금 → 전역(정적 확인)" + A3)
h = H("198.51.100.7")
T.chk(LA._limited(h, "198.51.100.7", False) is True and h.sent and h.sent[0][0] == 429 and json.loads(h.sent[0][1]).get("retryAfter") == w_ip,
      "login_auth._limited 가 바꿔 끼운 login_limits.LIM 을 씀(호출 시점 속성 — 시험의 LL.LIM 바꿔 끼우기가 조용히 안 먹는 일 없게)", h.sent[:1])
NOW[0] += 599
T.chk(LL.LIM.wait("192.0.2.55", False) > 0, "전역 창 안(599초 뒤) = 아직 대기" + A3, LL.LIM.wait("192.0.2.55", False))
NOW[0] += 2
T.chk(LL.LIM.wait("192.0.2.55", False) == 0, "전역 창(10분)이 지나면 새 버킷 대기 풀림")

print("[L3] 프록시 경유 버킷")
T.chk(RQ.bucket_of(H("127.0.0.1", Cf_Ray="x")) == "p:?" == RQ.bucket_of(H("127.0.0.1", Via="1.1 proxy")),
      "X-Forwarded-For 없는 프록시 요청 = 'p:?' 하나를 나눠 씀" + A3, [RQ.bucket_of(H("127.0.0.1", Cf_Ray="x"))])
T.chk(RQ.bucket_of(H("127.0.0.1", X_Forwarded_For="203.0.113.9")) == "p:203.0.113.9", "XFF 있는 프록시 요청 = 'p:<마지막 XFF>'")
T.chk(RQ.bucket_of(H("100.64.1.2")) == "100.64.1.2" and RQ.bucket_of(H("fd7a:115c:a1e0::1")) == "fd7a:115c:a1e0::/64", "직접 접속 = IP · IPv6 /64")
T.chk(RQ.direct_loopback(H("127.0.0.1")) and not RQ.direct_loopback(H("127.0.0.1", X_Forwarded_For="203.0.113.4")), "루프백 + 프록시 헤더 = 직접 접속 아님")

print("[L4] PBKDF2 칸")
sem = LL.HASH_SEM
got = [sem.acquire(blocking=False) for _ in range(3)]
for g in got:
    if g:
        sem.release()
T.chk(got == [True, False, False], "PBKDF2 공용 칸 = 1(두 번째는 못 잡음 — A1b: 공용 1 + 기기 1)" + A3, got)
semd = LL.HASH_SEM_DEV
gotd = [semd.acquire(blocking=False) for _ in range(2)]
for g in gotd:
    if g:
        semd.release()
T.chk(gotd == [True, False] and semd is not sem, "PBKDF2 기기 전용 칸 = 1(공용과 따로)" + A3, gotd)
mod = ast.parse(inspect.getsource(LA))
users = sorted({f.name for f in ast.walk(mod) if isinstance(f, ast.FunctionDef)
                and any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_verify_limited" for n in ast.walk(f))})
T.chk(users == ["_login", "_session_post"], "로그인·비밀번호 변경이 같은 칸(_verify_limited)을 나눠 씀" + A3, users)


class _Full:
    def acquire(self, timeout=None):
        return False

    def release(self):
        pass


LL.HASH_SEM = _Full()
h = H("127.0.0.1")
ok9, done9 = LA._verify_limited(h, ("127.0.0.1", True, None), "x", {"iter": 1}, "로그인")
hd9 = H("127.0.0.1")
okd, doned = LA._verify_limited(hd9, ("d:fedcba9876543210", True, "fedcba9876543210" + "0" * 48), "x", {"iter": 1}, "로그인")
LL.HASH_SEM = sem
T.chk(ok9 is False and done9 is True and h.sent and h.sent[0][0] == 503, "칸이 없으면 503(잠시 바빠요)", h.sent[:1])
T.chk(okd is False and doned is True and hd9.sent and hd9.sent[0][0] == 409 and LL.LIM.left("d:fedcba9876543210") == 5,
      "A1b: 기기 ctx 는 공용 칸이 막혀도 기기 칸을 잡고(503 아님) 칸 안에서 기기를 다시 확인 — 쿠키 없는 가짜 ctx = 409 · 실패 기록 없음"
      "(실제 기기로 로그인 200 = test_login_device D4)" + A3, (okd, doned, hd9.sent[:1]))

print("[L5] 세션 쿠키")
LA.S = LA.Settings({"enabled": True})
c_plain = LA._set_cookie(H("127.0.0.1"), "t" * 43, 60)[1]
c_px = LA._set_cookie(H("127.0.0.1", X_Forwarded_Proto="https", X_Forwarded_For="203.0.113.4"), "t" * 43, 60)[1]
c_far = LA._set_cookie(H("192.0.2.9", X_Forwarded_Proto="https"), "t" * 43, 60)[1]
LA.S = LA.Settings({"enabled": True, "secure_cookie": True})
c_sec = LA._set_cookie(H("127.0.0.1"), "t" * 43, 60)[1]
LA.S = LA.Settings({"enabled": False})
T.chk(c_plain.startswith("tj_session=") and "__Host-" not in c_plain and c_far.startswith("tj_session="),
      "HTTP 쿠키 이름 = tj_session(__Host- 접두 없음 · 바깥 상대가 보낸 XFP https 는 HTTP 취급)" + A3, [c_plain, c_far])
T.chk(c_px.startswith("__Host-tj_session=") and c_sec.startswith("__Host-tj_session=") and all("Domain" not in c for c in (c_px, c_sec)),
      "HTTPS 쿠키 이름 = __Host-tj_session(Path=/ · Secure · Domain 없음 — 브라우저 규칙)" + A3, [c_px, c_sec])
T.chk(all(x in c_plain for x in ("Path=/", "HttpOnly", "SameSite=Strict", "Max-Age=60")), "Path=/ · HttpOnly · SameSite=Strict · Max-Age", c_plain)
T.chk("Secure" not in c_plain and "Secure" in c_px and "Secure" not in c_far and "Secure" in c_sec,
      "Secure = HTTPS 일 때만(secure_cookie 또는 루프백 프록시 X-Forwarded-Proto: https · 바깥 상대의 XFP 는 안 믿음)" + A3, [c_plain, c_px, c_far, c_sec])

print("[L6] 연결 상한")
import web  # noqa: E402

Q = web.QuietHTTPServer
T.chk(Q.MAX_CONN == 256 and Q.PER_IP == 32, "기본 전역 MAX_CONN 256 · IP당 32" + A3, (Q.MAX_CONN, Q.PER_IP))
srv = Q(("127.0.0.1", 0), web.Handler)
try:
    T.chk(all(srv._ip_take(("127.0.0.1", i)) for i in range(1000)) and srv._ip_take(("::1", 1)) and srv._ip_take(("::ffff:127.0.0.1", 1)),
          "루프백 연결 = IP 상한 없음(터널·리버스 프록시 요청은 전부 루프백 — 전역 상한만)" + A3)
    far = [srv._ip_take(("100.64.9.9", i)) for i in range(33)]
    T.chk(far[:32] == [True] * 32 and far[32] is False, "루프백 아닌 주소 = 32 연결까지(33번째 거절)", far.count(True))
    for i in range(32):
        srv._ip_give(("100.64.9.9", i))
    T.chk("100.64.9.9" not in srv._ip_n and srv._ip_take(("100.64.9.9", 99)), "반납하면 다시 받음")
    got_c = 0
    while srv._conn_sem.acquire(blocking=False):
        got_c += 1
        if got_c > 5000:
            break
    T.chk(got_c == 256, "전역 동시 연결 칸 = 256" + A3, got_c)
finally:
    srv.server_close()

print("[L7] 설치 CSRF 토큰")
with open(os.path.join(T.ROOT, "config.example.json"), encoding="utf-8") as f:
    cfg = json.load(f)
cfg["web"] = {"port": 8023, "bind": "loopback"}
LA.init(cfg)
t1 = ss.csrf_token()
rec = LA.set_password("Login-Freeze-Horse-3381", iters=200_000)
t2 = ss.csrf_token()
s1, s2 = LA.new_session(rec), LA.new_session(rec)
LA.revoke(None)
t3 = ss.csrf_token()
T.chk(t1 != t2 and t2 == t3 and len(t2) >= 32, "설치 토큰 = 비밀번호를 정할 때만 교체 · 로그인·로그아웃으론 그대로(설치 전역 하나)" + A3, [t1 == t2, t2 == t3])
T.chk(LA._sess_csrf(s1) != LA._sess_csrf(s2) and LA._sess_csrf(s1) != t2, "세션 CSRF = 세션마다 다름(HMAC) — 설치 토큰과 별개")

print("[L7b] 쓰기 CSRF 정책(csrf_gate)")
import csrf_gate  # noqa: E402

hq = H("127.0.0.1")
inst = ss.csrf_token()
T.chk(csrf_gate.token_for(hq) == inst, "속성 없는 처리기 = 설치 토큰 모드(로그인 꺼짐·데모·시험 대역)")
csrf_gate.use_session(hq, LA._sess_csrf(s1))
T.chk(csrf_gate.token_for(hq) == LA._sess_csrf(s1) != inst, "세션 모드 = 그 세션 CSRF 를 줌(설치 토큰 아님)" + A3)
hq.headers["X-TJ-CSRF"] = inst
T.chk(csrf_gate.check(hq) is False, "세션 모드 + 설치 토큰 = 거부" + A3)
hq.headers.replace_header("X-TJ-CSRF", LA._sess_csrf(s2))
T.chk(csrf_gate.check(hq) is False, "세션 모드 + 다른 세션의 CSRF = 거부")
hq.headers.replace_header("X-TJ-CSRF", LA._sess_csrf(s1))
T.chk(csrf_gate.check(hq) is True, "세션 모드 + 그 세션 CSRF = 통과")
csrf_gate.begin(hq)
T.chk(csrf_gate.check(hq) is False and hq.tj_csrf_mode == "install", "begin = 설치 토큰 모드로 되돌림(같은 처리기의 앞 요청 세션 값 안 씀)")
hq.headers.replace_header("X-TJ-CSRF", inst)
T.chk(csrf_gate.check(hq) is True, "설치 토큰 모드 + 설치 토큰 = 통과(로그인 꺼짐 동작 무변)")
csrf_gate.use_session(hq, "")
T.chk(csrf_gate.check(hq) is False, "세션 모드 + 빈 기대값 = 거부(빈 헤더와 빈 값이 같다고 보지 않음)")
hq.headers.replace_header("X-TJ-CSRF", "토큰é")
T.chk(csrf_gate.check(hq) is False, "ASCII 아닌 헤더 = 예외 없이 거부")
LA.S = LA.Settings({"enabled": False})
T.finish()
