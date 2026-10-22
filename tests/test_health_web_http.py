#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import os  # noqa: E402
import socket  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from http.server import BaseHTTPRequestHandler, HTTPServer  # noqa: E402

os.environ.pop("TJ_HEALTH_NO_NET", None)
import chk_collect  # noqa: E402
import health  # noqa: E402

H = health.settings({})


def lvl(port):
    t0 = time.time()
    r = chk_collect.collect_web({"web": {"port": port}}, {}, time.time())
    by = {c["id"]: c for c in health.evaluate({"now": time.time(), "web": r}, H, ())}
    return by["web:loopback"]["level"], time.time() - t0, by["web:loopback"]["detail"]


s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", 9911))
s.listen(16)
lv, dt, det = lvl(9911)
T.chk(lv == "crit" and dt < 8, "H1 듣기만 하고 응답 없음 = 빨강(3초 시간 초과)", (lv, round(dt, 1), det))
s.close()


def serve(port, code):
    class Hd(BaseHTTPRequestHandler):
        def do_GET(self):
            b = b'{"ok":true}'
            self.send_response(code)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", port), Hd)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


for port, code in ((9912, 200), (9913, 401)):
    srv = serve(port, code)
    lv, dt, det = lvl(port)
    T.chk(lv == "ok", f"H2 HTTP {code} 응답 = 초록", (lv, det))
    srv.shutdown()
    srv.server_close()
lv, dt, det = lvl(9914)
T.chk(lv == "crit", "H2 포트 닫힘 = 빨강", (lv, det))
prox = serve(9915, 502)
os.environ["http_proxy"] = os.environ["HTTP_PROXY"] = "http://127.0.0.1:9915"
os.environ.pop("no_proxy", None)
os.environ.pop("NO_PROXY", None)
lv, dt, det = lvl(9914)
T.chk(lv == "crit", "H3 tj-web 꺼짐 + 환경 프록시 = 빨강(프록시 502 를 응답으로 안 봄)", (lv, det))
prox.shutdown()
prox.server_close()


class _Slow(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "1")
        self.end_headers()
        self.wfile.flush()
        time.sleep(5)
        self.wfile.write(b"x")

    def log_message(self, *a):
        pass


slow = HTTPServer(("127.0.0.1", 9916), _Slow)
threading.Thread(target=slow.serve_forever, daemon=True).start()
lv, dt, det = lvl(9916)
T.chk(lv == "ok" and dt < 4, "H4 헤더 바로 · 본문 늦음 = 초록(본문 안 기다림)", (lv, round(dt, 1), det))
slow.shutdown()
slow.server_close()
T.finish()
