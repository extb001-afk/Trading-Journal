#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import ast
import json
import os
import socket
import threading
import time

os.environ["TJ_HEALTH"] = "0"
import web
import login_auth
import settings_store as ss


def ck(name, cond, extra=None):
    T.chk(bool(cond), name, extra)


PW = "synthetic-pass-9137"
login_auth.init({"web": {"login": {"enabled": True}}})
login_auth.set_password(PW)
ck("(전제) 로그인 켜짐 · 비밀번호 있음", login_auth.S.enabled and login_auth.password_state()[0] == "set")
srv = web.QuietHTTPServer(("127.0.0.1", 0), web.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
HOST = f"127.0.0.1:{port}"


def head(path, n, extra=""):
    return (f"POST {path} HTTP/1.1\r\nHost: {HOST}\r\nOrigin: http://{HOST}\r\nContent-Type: application/json\r\n"
            f"Content-Length: {n}\r\n{extra}\r\n").encode()


def read_resp(c, tmo):
    c.settimeout(tmo)
    buf = b""
    try:
        while b"\r\n\r\n" not in buf:
            d = c.recv(65536)
            if not d:
                return None, buf, b""
            buf += d
        hd, _, rest = buf.partition(b"\r\n\r\n")
        n = 0
        for ln in hd.split(b"\r\n")[1:]:
            k, _, v = ln.partition(b":")
            if k.strip().lower() == b"content-length":
                n = int(v.strip())
        while len(rest) < n:
            d = c.recv(65536)
            if not d:
                break
            rest += d
        return int(hd.split(b" ")[1]), hd, rest
    except (OSError, ValueError, IndexError) as e:
        return repr(e), buf, b""


side = {}


def slow_login():
    body = json.dumps({"password": "x" * 22}).encode()
    body = body + b" " * (40 - len(body))
    c = socket.create_connection(("127.0.0.1", port), timeout=5)
    t0 = time.monotonic()
    try:
        c.sendall(head("/api/login", len(body)))
        got, i = None, 0
        while time.monotonic() - t0 < 16 and i < len(body):
            c.sendall(body[i:i + 1])
            i += 1
            r = read_resp(c, 9)
            if r[0] is not None and not (isinstance(r[0], str) and "timed out" in r[0]):
                got = r
                break
        el = round(time.monotonic() - t0, 1)
        after = None
        try:
            c.settimeout(2)
            after = c.recv(10)
        except OSError as e:
            after = repr(e)
        side["slow"] = (got and got[0], el, after, got and got[2][:80])
    except OSError as e:
        side["slow"] = (repr(e), round(time.monotonic() - t0, 1), None, None)
    finally:
        c.close()


th = threading.Thread(target=slow_login, daemon=True)
th.start()

body = json.dumps({"password": PW}).encode()
c = socket.create_connection(("127.0.0.1", port), timeout=10)
c.sendall(head("/api/login", len(body)) + body)
code, hd, rest = read_resp(c, 20)
c.close()
tok = None
for ln in (hd or b"").split(b"\r\n"):
    if ln.lower().startswith(b"set-cookie:") and b"tj_session=" in ln:
        tok = ln.split(b"tj_session=", 1)[1].split(b";", 1)[0].decode()
ck("NC2+② 정상 로그인(본문 한 번에) = 200 + 세션 쿠키", code == 200 and tok, (code, rest[:80]))

big = json.dumps(["a" * 1000] * 200).encode()
c = socket.create_connection(("127.0.0.1", port), timeout=10)
t0 = time.monotonic()
c.sendall(head("/api/__synthetic__", len(big), f"Cookie: tj_session={tok}\r\nX-TJ-CSRF: {ss.csrf_token()}\r\n"))
step = len(big) // 20 + 1
for i in range(0, len(big), step):
    time.sleep(0.75)
    c.sendall(big[i:i + step])
code, hd, rest = read_resp(c, 20)
el = round(time.monotonic() - t0, 1)
c.close()
ck("NC2+③ 인증된 큰 본문(약 200KB · 15초에 걸쳐) = 끝까지 받음(400 'JSON 객체 필요' · 시간 초과 500 아님)",
   code == 400 and "객체".encode() in rest and el >= 14, (code, el, rest[:80]))

th.join(30)
sl = side.get("slow")
ck("NC2+① 로그인 전 /api/login 본문 9초마다 1바이트 = 10초 남짓에 응답하고 닫음(종전 = 붙잡힘)",
   sl and sl[0] == 400 and 9.5 <= sl[1] <= 13 and sl[2] == b"", sl)
srv.shutdown()
srv.server_close()


class FakeH:
    def __init__(self, n):
        self.headers = {"Content-Length": str(n)}
        self.rfile = None
        self.calls = []

        class _C:
            def settimeout(self, v):
                pass
        self.connection = _C()

    def tj_read_within(self, n, sec):
        self.calls.append((n, sec))
        return b"{}"


for n9, want in ((40, 10.0), (4096, 10.0)):
    h9 = FakeH(n9)
    login_auth._read_json(h9, pre_auth=True) if "pre_auth" in login_auth._read_json.__code__.co_varnames else None
    ck(f"NC2+④ 로그인 전 본문 {n9}바이트 = 총 마감 {want}초", h9.calls == [(n9, want)], h9.calls)
h9 = FakeH(100000)
if "pre_auth" in login_auth._read_json.__code__.co_varnames:
    login_auth._read_json(h9, limit=200000, pre_auth=True)
ck("NC2+④ n ÷ 4KB/s 가 10초보다 크면 그만큼(100000바이트 ≈ 24.4초)", h9.calls and abs(h9.calls[0][1] - 100000 / 4096) < 0.01, h9.calls)
src = open(login_auth.__file__, encoding="utf-8").read()
fns = {n.name: n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef)}


def rj_pre(fn):
    out = []
    for n in ast.walk(fns[fn]):
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_read_json":
            out.append(any(k.arg == "pre_auth" and getattr(k.value, "value", None) is True for k in n.keywords))
    return out


ck("NC2+④ 로그인 전에 본문을 받는 두 곳(_login · _setup) = 총 마감", rj_pre("_login") == [True] and rj_pre("_setup") == [True],
   (rj_pre("_login"), rj_pre("_setup")))
ck("NC2+④ 로그인 뒤(비밀번호 변경 _session_post) = 총 마감 없음(종전 그대로)", rj_pre("_session_post") == [False], rj_pre("_session_post"))

T.finish()
