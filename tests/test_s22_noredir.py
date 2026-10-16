#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import urllib.request as _ur
_REAL_UO = _ur.urlopen
import _harness as T

import json
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

import common
import bf_engine
import depaddr
import ex_foreign
import liq_watch
import onboarding
import upbit_link

DEST = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", hdrs=None):
        self.send_response(code)
        for k, v in (hdrs or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _go(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            self.rfile.read(n)
        p = self.path.split("?")[0]
        if p.startswith("/r3"):
            self._send(int(p[2:5]), b"", {"Location": "http://127.0.0.1:%d/dest" % PORT})
        elif p == "/dest":
            DEST.append((p, bool(self.headers.get("Authorization") or self.headers.get("X-API-KEY"))))
            self._send(200, b'{"dest":1}')
        elif p == "/ok":
            self._send(200, b'{"ok":1,"v":[1,2]}', {"Remaining-Req": "group=x; min=55; sec=9"})
        elif p == "/e401":
            self._send(401, b'{"error":{"name":"invalid_access_key"}}')
        elif p == "/e429":
            self._send(429, b"{}", {"Retry-After": "1"})
        elif p == "/big":
            self._send(200, json.dumps({"pad": "x" * 5000}).encode())
        else:
            self._send(404, b"{}")

    do_GET = do_POST = _go


class Srv(ThreadingMixIn, HTTPServer):
    daemon_threads = True


SRV = Srv(("127.0.0.1", 0), H)
PORT = SRV.server_address[1]
BASE = "http://127.0.0.1:%d" % PORT
threading.Thread(target=SRV.serve_forever, daemon=True).start()

common.urllib.request.urlopen = _REAL_UO

CODES = (301, 302, 303, 307, 308)


def exc(fn, *a, **k):
    try:
        return ("ok", fn(*a, **k))
    except Exception as e:
        return ("exc", e)


UP = upbit_link.Upbit("acc", "sec")
upbit_link.API = BASE


def up(p):
    return exc(UP.get, p)


def xf(p):
    return exc(ex_foreign.http_json, BASE + p, {"X-API-KEY": "k"})


def dp(p):
    return exc(depaddr.http_get, BASE + p, {"Authorization": "Bearer t"}, 5, "upbit")


def lq(p):
    return exc(liq_watch._http_default, "GET", BASE + p, {"X-API-KEY": "k"})


def ob(p, sol=False):
    data = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": []}).encode() if sol else None
    return exc(onboarding._http, BASE + p, {"Authorization": "Bearer t"}, data, "POST" if sol else None, 5, sol)


def code_of(r):
    k, v = r
    if k == "ok":
        return v[0] if isinstance(v, tuple) and isinstance(v[0], int) else None
    return getattr(v, "code", None) or getattr(v, "status", None)


PATHS = (("upbit_link.Upbit.get", up), ("ex_foreign.http_json", xf), ("depaddr.http_get", dp),
         ("liq_watch._http_default", lq), ("onboarding._http", ob))

for name, fn in PATHS:
    bad = []
    for c in CODES:
        DEST.clear()
        r = fn("/r%d" % c)
        if DEST or code_of(r) != c:
            bad.append((c, len(DEST), r[0], code_of(r), type(r[1]).__name__))
    T.chk(not bad, "R1 %s: 301·302·303·307·308 = 목적지 호출 0 · 3xx 코드 그대로 오류 길" % name, bad)
r = dp("/r302")
T.chk(r[0] == "exc" and isinstance(r[1], depaddr.ApiError) and r[1].status == 302, "R1 depaddr 3xx = ApiError(302)", repr(r))
r = lq("/r307")
T.chk(r[0] == "exc" and isinstance(r[1], liq_watch.HttpErr) and r[1].status == 307, "R1 liq_watch 3xx = HttpErr(307)", repr(r))
r = up("/r301")
T.chk(r[0] == "exc" and isinstance(r[1], urllib.error.HTTPError) and r[1].code == 301, "R1 upbit 3xx = HTTPError(301)", repr(r))

r = up("/ok")
T.chk(r == ("ok", {"ok": 1, "v": [1, 2]}) and UP.remaining_min == 55, "R2 upbit 200 = 본문·Remaining-Req 그대로", [r, UP.remaining_min])
r = xf("/ok")
T.chk(r == ("ok", {"ok": 1, "v": [1, 2]}), "R2 ex_foreign 200 = 본문 그대로", r)
r = dp("/ok")
T.chk(r[0] == "ok" and r[1][0] == {"ok": 1, "v": [1, 2]} and r[1][1].get("Remaining-Req"), "R2 depaddr 200 = (본문, 헤더) 그대로", repr(r)[:300])
r = lq("/ok")
T.chk(r[0] == "ok" and r[1][0] == 200 and r[1][2] == {"ok": 1, "v": [1, 2]} and r[1][1].get("remaining-req"), "R2 liq_watch 200 = (200, 헤더, 본문)", repr(r)[:300])
r = ob("/ok")
T.chk(r == ("ok", (200, {"ok": 1, "v": [1, 2]})), "R2 onboarding 200 = (200, 본문)", r)

r = up("/e401")
T.chk(r[0] == "exc" and isinstance(r[1], urllib.error.HTTPError) and r[1].code == 401 and upbit_link._note_backoff(UP, r[1]), "R3 upbit 401 = HTTPError → 백오프 기록", repr(r))
r = dp("/e401")
T.chk(r[0] == "exc" and isinstance(r[1], depaddr.ApiError) and r[1].status == 401 and r[1].fatal, "R3 depaddr 401 = ApiError fatal", repr(r))
r = dp("/e429")
T.chk(r[0] == "exc" and isinstance(r[1], depaddr.ApiError) and r[1].status == 429 and r[1].fatal, "R3 depaddr 429 = ApiError fatal", repr(r))
r = lq("/e429")
T.chk(r[0] == "exc" and isinstance(r[1], liq_watch.HttpErr) and r[1].status == 429 and r[1].headers.get("retry-after") == "1", "R3 liq_watch 429 = HttpErr(헤더 그대로)", repr(r))
r = ob("/e401")
T.chk(r[0] == "ok" and r[1][0] == 401 and isinstance(r[1][1], dict), "R3 onboarding 401 = (401, 본문)", r)

_c0, _l0, _x0 = common.HTTP_BODY_MAX, liq_watch.MAX_BYTES, ex_foreign.HTTP_MAX_BYTES
common.HTTP_BODY_MAX, liq_watch.MAX_BYTES, ex_foreign.HTTP_MAX_BYTES = 1000, 1000, 1000
T.patch_moved("HTTP_MAX_BYTES", ex_foreign.HTTP_MAX_BYTES, ("exf_",))
r = dp("/big")
T.chk(r[0] == "exc", "R4 depaddr 크기 상한 그대로(실패)", repr(r)[:200])
r = lq("/big")
T.chk(r[0] == "exc" and isinstance(r[1], ValueError), "R4 liq_watch 크기 상한 그대로(ValueError)", repr(r)[:200])
r = up("/big")
T.chk(r[0] == "exc" and isinstance(r[1], common.ResponseTooLarge), "R4 upbit 크기 상한 그대로(ResponseTooLarge)", repr(r)[:200])
r = xf("/big")
T.chk(r[0] == "exc", "R4 ex_foreign 크기 상한 그대로(실패)", repr(r)[:200])
common.HTTP_BODY_MAX, liq_watch.MAX_BYTES, ex_foreign.HTTP_MAX_BYTES = _c0, _l0, _x0
T.patch_moved("HTTP_MAX_BYTES", ex_foreign.HTTP_MAX_BYTES, ("exf_",))

GAPS = []
_gap0 = bf_engine.rpc_gap
bf_engine.rpc_gap = lambda url, m=None, d=None, sol=False: GAPS.append((m, sol))
DEST.clear()
r = ob("/r302", sol=True)
T.chk(GAPS == [("getBalance", True)] and not DEST and code_of(r) == 302, "R5 onboarding sol=True = rpc_gap 1번(getBalance) · 302 안 따라감", [GAPS, DEST, r])
GAPS.clear()
r = ob("/ok", sol=True)
T.chk(GAPS == [("getBalance", True)] and r == ("ok", (200, {"ok": 1, "v": [1, 2]})), "R5 onboarding sol=True 200 = rpc_gap 1번 · 결과 그대로", [GAPS, r])
bf_engine.rpc_gap = _gap0

r = xf("/e429")
T.chk(r[0] == "exc" and isinstance(r[1], ex_foreign.RateLimited), "R3 ex_foreign 429 = RateLimited", repr(r))

SRV.shutdown()
SRV.server_close()
common.urllib.request.urlopen = T._guard_urlopen
T.finish()
