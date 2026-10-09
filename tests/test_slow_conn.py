#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import ast
import json
import os
import select
import socket
import threading
import time

os.environ["TJ_HEALTH"] = "0"
try:
    import resource
    so9, hd9 = resource.getrlimit(resource.RLIMIT_NOFILE)
    want9 = 4096 if hd9 == resource.RLIM_INFINITY else min(hd9, 4096)
    if so9 != resource.RLIM_INFINITY and so9 < want9:
        resource.setrlimit(resource.RLIMIT_NOFILE, (want9, hd9))
except (ImportError, ValueError, OSError):
    pass
import web


def ck(name, cond, extra=None):
    T.chk(bool(cond), name, extra)


class H(web.Handler):

    def do_POST(self):
        self.close_connection = True
        n = int(self.headers.get("Content-Length") or 0)
        self.connection.settimeout(10)
        body = self.rfile.read(n)
        self._send(200, {"ok": True, "n": len(body)})


def serve(cls=web.QuietHTTPServer, h=H):
    s = cls(("127.0.0.1", 0), h)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, s.server_address[1]


GET = b"GET /api/day_events HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"


def read_resp(s, tmo=5.0):
    s.settimeout(tmo)
    buf = b""
    try:
        while b"\r\n\r\n" not in buf:
            c = s.recv(4096)
            if not c:
                return None, buf
            buf += c
        head, _, rest = buf.partition(b"\r\n\r\n")
        n = 0
        for ln in head.split(b"\r\n")[1:]:
            k, _, v = ln.partition(b":")
            if k.strip().lower() == b"content-length":
                n = int(v.strip())
        while len(rest) < n:
            c = s.recv(4096)
            if not c:
                break
            rest += c
        return int(head.split(b" ")[1]), rest
    except (OSError, ValueError, IndexError):
        return None, buf


def get_status(port, tmo=5.0):
    try:
        c = socket.create_connection(("127.0.0.1", port), timeout=tmo)
    except OSError as e:
        return repr(e)
    try:
        c.sendall(GET)
        return read_resp(c, tmo)[0]
    except OSError as e:
        return repr(e)
    finally:
        c.close()


srv, port = serve()
ck("(전제) 전역 상한 256", web.QuietHTTPServer.MAX_CONN == 256, web.QuietHTTPServer.MAX_CONN)
ck("NC2 듣기 대기열 128(socketserver 기본 5 — 한꺼번에 몰린 연결이 넘쳐 리셋)", web.QuietHTTPServer.request_queue_size >= 128, web.QuietHTTPServer.request_queue_size)
srv2, port2 = serve()
side = {}


def keepalive_idle():
    c = socket.create_connection(("127.0.0.1", port2), timeout=5)
    try:
        c.sendall(GET)
        a = read_resp(c)[0]
        time.sleep(12)
        c.sendall(GET)
        side["ka"] = (a, read_resp(c)[0])
    except OSError as e:
        side["ka"] = repr(e)
    finally:
        c.close()


def slow_body():
    c = socket.create_connection(("127.0.0.1", port2), timeout=5)
    try:
        c.sendall(b"POST /x HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: 5\r\n\r\n")
        for ch in b"12345":
            time.sleep(2.5)
            c.sendall(bytes([ch]))
        code, body = read_resp(c)
        side["body"] = (code, json.loads(body.decode() or "{}").get("n") if code == 200 else body[:80])
    except (OSError, ValueError) as e:
        side["body"] = repr(e)
    finally:
        c.close()


def slow_ok_header():
    c = socket.create_connection(("127.0.0.1", port2), timeout=5)
    try:
        for part in (b"GET /api/day_e", b"vents HTTP/1.1\r\n", b"Host: 127.0", b".0.1\r\n\r\n"):
            c.sendall(part)
            time.sleep(2)
        side["hdr6"] = read_resp(c)[0]
    except OSError as e:
        side["hdr6"] = repr(e)
    finally:
        c.close()


def hdr_trickle():
    c = socket.create_connection(("127.0.0.1", port2), timeout=5)
    t0 = time.monotonic()
    try:
        c.sendall(b"GET /api/day_events HTTP/1.1\r\nHost: 127.0.0.1\r\nX-A: ")
        c.settimeout(2)
        while time.monotonic() - t0 < 14:
            try:
                r = c.recv(10)
                side["trickle"] = (r, round(time.monotonic() - t0, 1))
                return
            except socket.timeout:
                c.sendall(b"a")
    except OSError as e:
        side["trickle"] = (b"" if isinstance(e, (BrokenPipeError, ConnectionResetError)) else repr(e), round(time.monotonic() - t0, 1))
    finally:
        c.close()


def silent():
    c = socket.create_connection(("127.0.0.1", port2), timeout=5)
    t0 = time.monotonic()
    c.settimeout(14)
    try:
        r = c.recv(10)
        side["silent"] = (r, round(time.monotonic() - t0, 1))
    except OSError as e:
        side["silent"] = (repr(e), round(time.monotonic() - t0, 1))
    finally:
        c.close()


ths = [threading.Thread(target=f, daemon=True) for f in (keepalive_idle, slow_body, slow_ok_header, silent, hdr_trickle)]
for t9 in ths:
    t9.start()

t0 = time.monotonic()
socks = []
for i in range(256):
    s = socket.create_connection(("127.0.0.1", port), timeout=10)
    s.sendall(b"G")
    socks.append(s)
SLOW = b"ET /api/day_events HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Slow: " + b"a" * 64
pos = {s: 0 for s in socks}
closed, early = {}, []
next_send = t0 + 5
while time.monotonic() - t0 < 12.5 and len(closed) < len(socks):
    live = [s for s in socks if s not in closed]
    r9, _, _ = select.select(live, [], [], 0.25)
    for s in r9:
        try:
            d = s.recv(256)
        except OSError:
            d = b""
        closed[s] = time.monotonic() - t0
        if d:
            early.append(d[:40])
    if time.monotonic() >= next_send:
        next_send += 5
        for s in [s for s in socks if s not in closed]:
            try:
                s.sendall(SLOW[pos[s]:pos[s] + 1])
                pos[s] += 1
            except OSError:
                closed[s] = time.monotonic() - t0
n_closed = len(closed)
mx = max(closed.values()) if closed else None
ck("NC2① 1바이트씩 흘리는 연결 256개 = 12초 안에 모두 끊김(종전 = 그대로 붙잡힘)", n_closed == 256 and mx is not None and mx <= 12.0,
   {"끊김": n_closed, "마지막": mx and round(mx, 1)})
ck("NC2① 마감 전에 끊기지 않음(8초 전 끊김 0 — 마감이 너무 짧지 않음)", n_closed and min(closed.values()) >= 8.0, closed and round(min(closed.values()), 1))
ck("NC2① 끊을 때 응답 없음(503 거절 아님 — 다 받아 놓고 마감으로 끊음)", not early, early[:3])
while time.monotonic() - t0 < 15:
    time.sleep(0.1)
st15 = get_status(port)
ck("NC2① 15초 시점 GET = 200(종전 = 503)", st15 == 200, st15)
for s in socks:
    s.close()
for t9 in ths:
    t9.join(20)
ck("NC2② keep-alive 연결이 12초 쉰 뒤 다음 요청 = 200(유휴는 종전 120초 — 마감은 첫 바이트부터)", side.get("ka") == (200, 200), side.get("ka"))
ck("NC2② 본문을 12.5초에 걸쳐 보내는 POST = 200(마감은 헤더에만 — 업로드·느린 본문 무관)", side.get("body") == (200, 5), side.get("body"))
ck("NC2② 헤더를 6초에 걸쳐 조각으로 보내도(마감 안) = 200", side.get("hdr6") == 200, side.get("hdr6"))
tr = side.get("trickle")
ck("NC2② 요청 줄은 바로 · 헤더를 2초마다 1바이트 = 12초 안에 끊김(헤더까지 합계 마감)", tr and tr[0] == b"" and 8 <= tr[1] <= 12, tr)
sl = side.get("silent")
ck("NC2② 연결만 하고 안 보내는 연결 = 12초 안에 끊김(첫 요청 마감 = 연결 시각부터)", sl and sl[0] == b"" and 8 <= sl[1] <= 12, sl)
def read_resp_f(f):
    try:
        st = f.readline()
        n = 0
        while True:
            ln = f.readline()
            if ln in (b"\r\n", b"\n", b""):
                break
            k, _, v = ln.partition(b":")
            if k.strip().lower() == b"content-length":
                n = int(v.strip())
        f.read(n)
        return int(st.split(b" ")[1])
    except (OSError, ValueError, IndexError):
        return None


c9 = socket.create_connection(("127.0.0.1", port2), timeout=5)
c9.sendall(GET + GET)
f9 = c9.makefile("rb")
pp9 = (read_resp_f(f9), read_resp_f(f9))
f9.close()
c9.close()
ck("NC2② 한 번에 보낸 두 요청(파이프라인·keep-alive) = 200 · 200", pp9 == (200, 200), pp9)
srv.shutdown()
srv.server_close()
srv2.shutdown()
srv2.server_close()

ck("(전제) IP당 상한 기본 32", getattr(web.QuietHTTPServer, "PER_IP", None) == 32, getattr(web.QuietHTTPServer, "PER_IP", None))


class SrvExt(web.QuietHTTPServer):
    PER_IP = 4

    @staticmethod
    def _loopback(ip):
        return False


class SrvLo(web.QuietHTTPServer):
    PER_IP = 4


def held_then_extra(cls, n_hold):
    s9, p9 = serve(cls)
    held = [socket.create_connection(("127.0.0.1", p9), timeout=5) for _ in range(n_hold)]
    time.sleep(0.3)
    x = socket.create_connection(("127.0.0.1", p9), timeout=5)
    x.sendall(GET)
    code = read_resp(x, 3)[0]
    x.close()
    return s9, p9, held, code


s9, p9, held, code = held_then_extra(SrvExt, 4)
ck("NC2③ 같은 바깥 주소 5번째 연결 = 503(IP당 4 · 종전 = 받음)", code == 503, code)
held[0].close()
time.sleep(0.4)
st9 = get_status(p9)
ck("NC2③ 한 칸 풀리면 다시 받음", st9 == 200, st9)
for c9 in held[1:]:
    c9.close()
s9.shutdown()
s9.server_close()
s9, p9, held, code = held_then_extra(SrvLo, 10)
ck("NC2③ 루프백(터널·리버스 프록시)은 IP당 상한 없음 — 11번째도 200", code == 200, code)
for c9 in held:
    c9.close()
s9.shutdown()
s9.server_close()
ck("NC2③ 루프백 판정(127.x · ::1 · ::ffff:127.x = 루프백 · 사설·테일넷 = 아님)",
   all(web.QuietHTTPServer._loopback(a) for a in ("127.0.0.1", "127.3.4.5", "::1", "::ffff:127.0.0.1"))
   and not any(web.QuietHTTPServer._loopback(a) for a in ("100.64.1.2", "192.168.0.7", "10.0.0.1", "::ffff:10.0.0.1", "", None))
   if hasattr(web.QuietHTTPServer, "_loopback") else False)

import onboarding
src = open(onboarding.__file__, encoding="utf-8").read()
fn = next((n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "demo_main"), None)
names = []
for n in (ast.walk(fn) if fn else ()):
    if isinstance(n, ast.Call):
        f = n.func
        names.append(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", ""))
ck("NC2④ 데모 서버 = QuietHTTPServer(전역 상한·IP당 상한·헤더 마감 · 종전 = ThreadingHTTPServer 상한 없음)",
   "QuietHTTPServer" in names and "ThreadingHTTPServer" not in names, names)

import logging


class Cap(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.recs = []

    def emit(self, r):
        self.recs.append((r.levelno, r.getMessage()))


cap = Cap()
web.log.addHandler(cap)
lv0 = web.log.level
web.log.setLevel(logging.DEBUG)


class HR(H):
    gone = True

    def _send(self, code, body, *a, **k):
        n = getattr(self, "_n9", 0)
        self._n9 = n + 1
        if n == 0:
            raise ConnectionResetError(54, "합성 리셋")
        if HR.gone:
            raise BrokenPipeError(32, "합성 끊김")
        return super()._send(code, body, *a, **k)


s9, p9 = serve(h=HR)
for gone in (True, False):
    HR.gone = gone
    cap.recs.clear()
    c9 = socket.create_connection(("127.0.0.1", p9), timeout=5)
    c9.sendall(GET)
    code9 = read_resp(c9, 3)[0]
    c9.close()
    time.sleep(0.2)
    warn9 = [m for lv, m in cap.recs if lv >= logging.WARNING]
    dbg9 = [m for lv, m in cap.recs if lv == logging.DEBUG and "끊음" in m]
    if gone:
        ck("NC2⑤ 상대가 끊은 연결 = debug 한 줄 · 경고 0(종전 = 리셋은 경고+트레이스백)", dbg9 and not warn9, {"warn": warn9[:2], "debug": dbg9[:2]})
    else:
        ck("NC2⑤ 연결은 살아 있는데 처리 중 리셋(바깥 호출) = 종전처럼 500 + 경고", code9 == 500 and warn9 and not dbg9, {"code": code9, "warn": warn9[:1]})
s9.shutdown()
s9.server_close()
web.log.removeHandler(cap)
web.log.setLevel(lv0)
wsrc = open(web.__file__, encoding="utf-8").read()
fns = {n.name: n for n in ast.walk(ast.parse(wsrc)) if isinstance(n, ast.FunctionDef) and n.name in ("do_GET", "do_POST")}
ck("NC2⑤ do_GET·do_POST 둘 다 같은 끊김 처리(_gone_or_500)",
   all(any(isinstance(x, ast.Attribute) and x.attr == "_gone_or_500" for x in ast.walk(fns.get(k) or ast.parse(""))) for k in ("do_GET", "do_POST")))

T.finish()
