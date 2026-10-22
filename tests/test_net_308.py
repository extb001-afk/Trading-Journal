#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _cassette as C  # noqa: E402

import http.server  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402

import _net_policy as NP  # noqa: E402
import pricing  # noqa: E402
import rabby  # noqa: E402

FOLLOWS = sys.version_info >= (3, 11)
HITS = []


class _H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        HITS.append(self.path)
        if self.path.startswith("/src/"):
            self.send_response(308)
            self.send_header("Location", "/dst/" + self.path.split("/", 2)[2])
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        b9 = json.dumps({"at": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b9)))
        self.end_headers()
        self.wfile.write(b9)

    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
th = threading.Thread(target=srv.serve_forever, daemon=True)
th.start()
base = "http://127.0.0.1:%d" % srv.server_address[1]
print("파이썬 %d.%d — 308 기대 = %s" % (sys.version_info[0], sys.version_info[1], "따라감" if FOLLOWS else "HTTPError 308"))
try:
    with C.real_loopback():
        for name, fn in (("rabby.http_get", rabby.http_get), ("pricing._gj", pricing._gj)):
            del HITS[:]
            r = NP.summary(fn, base + "/src/" + name, timeout=5)
            if FOLLOWS:
                T.chk(r.get("ret") == {"at": "/dst/" + name} and HITS == ["/src/" + name, "/dst/" + name],
                      "%s: 3.11+ = 308 따라감(목적지 응답 · 요청 2)" % name, [r, HITS])
            else:
                T.chk(r.get("exc") == "HTTPError" and r.get("code") == 308 and HITS == ["/src/" + name],
                      "%s: 3.9 = 308 안 따라감(HTTPError 308 · 요청 1)" % name, [r, HITS])
finally:
    srv.shutdown()
    srv.server_close()
T.finish()
