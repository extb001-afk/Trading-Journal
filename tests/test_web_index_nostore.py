#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import email.message  # noqa: E402
import io  # noqa: E402
import os  # noqa: E402

import http_assets  # noqa: E402
import http_get  # noqa: E402
import web  # noqa: E402


class _Resp(web.Handler):
    def __init__(self, cookie=None):   # noqa: D107
        self.headers = email.message.Message()
        if cookie:
            self.headers["Cookie"] = cookie
        self.client_address = ("127.0.0.1", 0)
        self.close_connection = True
        self.wfile = io.BytesIO()
        self.sent, self.status = [], None

    def send_response(self, code, message=None):
        self.status = code

    def send_header(self, name, value):
        self.sent.append((name.lower(), value))

    def end_headers(self):
        pass


def cc(h):
    return [v for k, v in h.sent if k == "cache-control"]


V2 = os.path.join(T.ROOT, "web", "v2")
idx = os.path.join(V2, "index.html")
a = http_assets._asset(idx)
h = _Resp()
h._send_v2_index(a)
T.chk(h.status == 200 and cc(h) == ["private, no-store"], "N1 요약 없는 v2 HTML = private, no-store", cc(h))


T.chk(getattr(http_get, "V2_INDEX_CACHE", None) == "private, no-store", "N2 요약 넣은 v2 HTML 갈래의 Cache-Control 상수 = private, no-store", getattr(http_get, "V2_INDEX_CACHE", None))
h = _Resp(cookie="tj_v2_rand=1")
h._send_v2_index(a)
T.chk(h.status == 200 and cc(h) == ["private, no-store"] and b'<script id="tjHero"' not in h.wfile.getvalue(), "N3 랜덤값 = 요약 없음 · no-store", cc(h))
app = os.path.join(V2, "app.js")
aa = http_assets._asset(app)
h = _Resp()
h._send_asset(app, "application/javascript; charset=utf-8", "v=" + aa["hash"])
T.chk(cc(h) == ["private, max-age=31536000, immutable"], "N4 버전 붙은 app.js = 종전 그대로 immutable", cc(h))
T.finish()
