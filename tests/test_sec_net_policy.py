#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _sec_lint as L  # noqa: E402
import _harness as T  # noqa: E402

import ast  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402

t0 = time.time()
TRIG = ("check_hostname", "CERT_NONE", "unverified", "RedirectHandler", "build_opener", "internal_headers", "X-TJ-Internal", "127.0.0.1",
        "localhost", "[::1]", "100.", "fd7a:115c", "TJ_TEST_", "TJ_TG_API")
IX = L.PyIndex(T.ROOT, ("src", "tools"), only=lambda n, txt: any(x in txt for x in TRIG))
M = {k: {} for k in ("tls_off", "redirect", "local_http", "tailnet", "internal_hdr", "base_override")}
S = {k: {} for k in M}
LOCAL = re.compile(r"^https?://(?:127\.0\.0\.1|localhost|\[::1\])")
TAIL = re.compile(r"^(?:100\.|100\.64\.0\.0/10$|fd7a:115c:a1e0)")


def add(cat, key, smp):
    M[cat][key] = M[cat].get(key, 0) + 1
    S[cat].setdefault(key, []).append(smp)


for mod, t in sorted(IX.mods.items()):
    rp = IX.path[mod]
    tree = t["tree"]
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and any("RedirectHandler" in ast.unparse(b) for b in node.bases):
            add("redirect", "%s::%s" % (rp, node.name), "%s:%d class %s(%s)" % (rp, node.lineno, node.name, ast.unparse(node.bases[0])))
    units9 = [("%s::%s" % (rp, fi.qual), fi.nodes) for fi in L.func_table(tree)] + [("%s::<mod>" % rp, L.module_nodes(tree))]
    for key, nodes9 in units9:
        for n in nodes9:
            if isinstance(n, ast.Assign):
                for tg in n.targets:
                    if isinstance(tg, ast.Attribute) and tg.attr == "check_hostname" and isinstance(n.value, ast.Constant) and n.value.value is False:
                        add("tls_off", key, "%s:%d check_hostname = False" % (rp, n.lineno))
                    if isinstance(tg, ast.Attribute) and tg.attr == "verify_mode" and "CERT_NONE" in ast.unparse(n.value):
                        add("tls_off", key, "%s:%d verify_mode = CERT_NONE" % (rp, n.lineno))
            elif isinstance(n, ast.Call):
                nm = L.call_name(n)
                if nm.endswith("_create_unverified_context"):
                    add("tls_off", key, "%s:%d %s()" % (rp, n.lineno, nm))
                elif nm.endswith("build_opener"):
                    add("redirect", key, "%s:%d build_opener(%s)" % (rp, n.lineno, ", ".join(ast.unparse(a)[:24] for a in n.args)[:60]))
                elif nm.endswith("internal_headers"):
                    add("internal_hdr", key, "%s:%d %s()" % (rp, n.lineno, nm))
                elif nm in ("os.environ.get", "os.getenv", "environ.get") and n.args and isinstance(n.args[0], ast.Constant) \
                        and isinstance(n.args[0].value, str) and re.match(r"TJ_(?:TEST_BASE_|TG_API$|TEST_.*(?:URL|BASE|API))", n.args[0].value):
                    add("base_override", key, "%s:%d %s(%r)" % (rp, n.lineno, nm, n.args[0].value))
            elif isinstance(n, ast.Constant) and isinstance(n.value, str):
                if LOCAL.match(n.value):
                    add("local_http", key, "%s:%d %r" % (rp, getattr(n, "lineno", 0), n.value[:40]))
                elif TAIL.match(n.value) and len(n.value) < 40:
                    add("tailnet", key, "%s:%d %r" % (rp, getattr(n, "lineno", 0), n.value))
                elif n.value == "X-TJ-Internal":
                    add("internal_hdr", key, "%s:%d 'X-TJ-Internal'" % (rp, getattr(n, "lineno", 0)))
            elif isinstance(n, ast.Compare) and any(isinstance(c, (ast.Tuple, ast.List, ast.Set)) and
                                                    {"localhost", "127.0.0.1"} <= {getattr(e, "value", None) for e in c.elts} for c in n.comparators):
                add("local_http", key, "%s:%d %s" % (rp, n.lineno, ast.unparse(n)[:60]))
for k in M:
    print("  %-13s %3d 자리 · 합 %d" % (k, len(M[k]), sum(M[k].values())))
T.chk(len(IX.scan) >= 5, "조사기 동작(거른 모듈 5+ — 예외 자리를 다 없애도 FAIL 하지 않게 지표에 하한 없음)", {"모듈": len(IX.scan), **{k: len(v) for k, v in M.items()}})
hints = {k: "새 외부 요청 정책 예외 — 6막 공용 opener 로 옮길 목록이 늘었음: 기존 공용 함수를 쓰거나 기준선에 자리·이유를 손으로 등록" for k in M}
hints["tls_off"] = "인증서 검사 끄기 자리가 늘었음 — localhost 시험 말고는 끄지 마세요"
L.ratchet(T, "net", M, "G1 외부 요청 정책 예외 자리(파일::함수 → 수) — 6막 공용 opener 전환 목록. 늘면 FAIL · 줄면 --update-lower",
          hints=hints, samples=S, exists=lambda f: True)
print("[2] 인증 헤더가 붙은 요청 = 리다이렉트 0(실제 루프백 서버 · 6막 목적지 정책으로 바꿀 때 약해지면 FAIL)")
import http.server  # noqa: E402
import threading  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

HITS = []


class _Redir(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/steal"):
            HITS.append({k.lower(): v for k, v in self.headers.items()})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")
            return
        self.send_response(302)
        self.send_header("Location", "http://127.0.0.1:%d/steal" % RPORT)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_POST = do_GET

    def log_message(self, *a):
        pass


RSRV = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Redir)
RPORT = RSRV.server_address[1]
threading.Thread(target=RSRV.serve_forever, daemon=True, name="t-redir").start()
URL = "http://127.0.0.1:%d/x" % RPORT
AUTH = {"Authorization": "Bearer cnryRedirTok9Qw2", "X-MBX-APIKEY": "cnryRedirKey7Zx4"}


def _real(req, timeout=None, *a, **k):
    return urllib.request.build_opener().open(req, timeout=timeout)


_real.__module__ = "urllib.request"
_real._tj_test_mock = True
import net_http  # noqa: E402
import exf_net  # noqa: E402
import onboarding  # noqa: E402
from brokers import base as brk  # noqa: E402

_guard = net_http.urllib.request.urlopen
net_http.urllib.request.urlopen = _real
try:
    urllib.request.build_opener().open(URL, timeout=10).read()
    T.chk(len(HITS) == 1, "대조군: 기본 opener 는 리다이렉트를 따라감(시험 서버 동작 확인)", len(HITS))
    HITS.clear()
    r9 = T.safe(net_http.auth_urlopen, urllib.request.Request(URL, headers=AUTH), 10)
    T.chk(isinstance(r9, dict) and "302" in str(r9.get("_exc")) and not HITS, "net_http.auth_urlopen: 3xx 를 따라가지 않음(HTTPError 302) · 인증 헤더 재전송 0", (r9, HITS))
    r9 = T.safe(exf_net.http_json, URL, AUTH)
    T.chk(isinstance(r9, dict) and "HTTPError" in str(r9.get("_exc")) and "302" in str(r9.get("_exc")) and not HITS,
          "exf_net.http_json(거래소 서명 요청): HTTPError 302 · 리다이렉트 따라감 0(요청 전 오류는 통과 아님)", (str(r9)[:160], HITS))
    r9 = T.safe(onboarding._http, URL, AUTH)
    T.chk(isinstance(r9, tuple) and r9[0] == 302 and not HITS, "onboarding._http(키 시험): (302, …) 그대로 · 리다이렉트 따라감 0", (str(r9)[:160], HITS))
    r9 = T.safe(brk.default_http, "GET", URL, AUTH)
    T.chk(isinstance(r9, tuple) and r9[0] == 302 and str((r9[2] or {}).get("location", "")).endswith("/steal") and not HITS,
          "brokers.base.default_http(증권사): (302, …, location) 그대로 · 리다이렉트 따라감 0", (str(r9)[:160], HITS))
finally:
    net_http.urllib.request.urlopen = _guard
    RSRV.shutdown()
    RSRV.server_close()
print("(시간 %.1f초)" % (time.time() - t0))
T.finish()
