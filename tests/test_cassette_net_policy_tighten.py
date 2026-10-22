#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _cassette as C  # noqa: E402

C.freeze()
import http.server  # noqa: E402
import ipaddress  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402

import _net_policy as NP  # noqa: E402

with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump({"chains": {}, "wallets": []}, f)
import bf_engine  # noqa: E402
import login_auth  # noqa: E402
import net_http  # noqa: E402
import review_daily  # noqa: E402

NP.configure()
INTERNAL = "casPOLICYinternalToken0001casPOLICY01"
with open(login_auth.INTERNAL_PATH, "w", encoding="ascii") as f:
    f.write(INTERNAL + "\n")
SECRETS = dict(NP.SECRETS, policy_internal=INTERNAL)
ENTS = ("rabby", "bfe", "sol_open")
TARGETS = {"t_rfc1918": "http://10.255.0.5/%s/t", "t_loop4": "http://127.0.0.1/%s/t", "t_loop6": "http://[::1]/%s/t",
           "t_meta": "http://169.254.169.254/%s/latest/meta-data", "t_cgnat": "http://100.64.1.1/%s/t",
           "t_dnsprv": "https://inner-%s.policy.invalid/t", "t_mapped": "http://[::ffff:127.0.0.1]/%s/t", "t_zero": "http://0.0.0.0/%s/t"}
DNS, ATTACK = {}, ("race", "mixed")
for i9, e9 in enumerate(ENTS):
    h9 = e9.replace("_", "-")
    DNS["inner-%s.policy.invalid" % h9] = ["10.255.0.6"]
    DNS["race-%s.policy.invalid" % h9] = {"seq": [["9.9.9.%d" % (60 + i9)], ["10.255.0.7"]]}
    DNS["mixed-%s.policy.invalid" % h9] = ["9.9.9.%d" % (70 + i9), "10.255.0.8"]


def start(e, k):
    h9 = e.replace("_", "-")
    if k == "race":
        return "https://race-%s.policy.invalid/start" % h9
    return "https://%s-%s.policy.invalid/start" % (h9, k.replace("_", "-"))


def respond(rq):
    seen = {"at": rq.host + rq.path, "m": rq.method, "internal": rq.headers.get("x-tj-internal") == INTERNAL}
    if rq.path == "/api/rd/start":
        return C.Reply("", status=302, headers={"Location": "http://127.0.0.1:8090/api/rd/next" if rq.query.get("to") == "loop"
                                                 else "http://evil.policy.invalid/api/rd/leak"})
    if rq.path != "/start":
        return seen
    lab = rq.host.split(".")[0]
    e = next(x for x in ENTS if lab.endswith(x.replace("_", "-")) or lab.startswith(x.replace("_", "-") + "-"))
    k = next((k for k in list(TARGETS) + list(ATTACK) if lab in ("%s-%s" % (e.replace("_", "-"), k.replace("_", "-")),
                                                                 "%s-%s" % (k, e.replace("_", "-")))), None)
    if k == "race":
        loc = "http://169.254.169.254/%s/race" % e
    elif k == "mixed":
        loc = "https://mixed-%s.policy.invalid/t" % e.replace("_", "-")
    else:
        loc = TARGETS[k] % (e.replace("_", "-") if k == "t_dnsprv" else e)
    return C.Reply("", status=302, headers={"Location": loc})


def private(ip) -> bool:
    try:
        a = ipaddress.ip_address(str(ip))
    except ValueError:
        return False
    a = a.ipv4_mapped or a if a.version == 6 else a
    return not a.is_global or a.is_multicast or a.is_reserved or a.is_link_local or a.is_unspecified


def run_http():
    out, priv = {}, {}
    for k in list(TARGETS) + list(ATTACK):
        for e in ENTS:
            n0 = len(cas.conn_log)
            out.setdefault(k, {})[e] = NP.summary(NP.call, e, start(e, k))
            priv.setdefault(k, {})[e] = sum(1 for _k, ev, p in cas.conn_log[n0:] if ev == "ok" and private(p))
    for k, to in (("rd_loop", "loop"), ("rd_out", "out")):
        n0 = len(cas.conn_log)
        out[k] = NP.summary(review_daily._get_json, {}, "/api/rd/start?to=" + to, timeout=7, hosts=(8090, ["127.0.0.1"]))
        priv[k] = [p for _k, ev, p in cas.conn_log[n0:] if ev == "ok"]
    return out, priv


print("[A] 리다이렉트 목적지(카세트 · 주소 보존 모드)")
cas = C.Cassette("net_policy_tighten", secrets=SECRETS, responder=respond, dns=DNS, preserve=True)
if cas.ready(T):
    res, why = cas.run(run_http)
    T.chk(why is None, "시나리오 전부 끝까지(새 요청·틀 오류 없음)", why)
    out, priv = res or ({}, {})
    deny = {"rabby": ("HTTPError", None), "bfe": ("NetError", "http4xx"), "sol_open": ("HTTPError", None)}
    for k in list(TARGETS) + list(ATTACK):
        r9 = out.get(k) or {}
        T.chk(all((r9.get(e) or {}).get("exc") == deny[e][0] and (r9.get(e) or {}).get("code") == 302 and (r9.get(e) or {}).get("kind") == deny[e][1]
                  for e in ENTS) and all((priv.get(k) or {}).get(e) == 0 for e in ENTS),
              "열쇠 %s: 비인증 입구 3 = 거부(HTTPError 302 · bfe NetError http4xx · 사설 목적지 연결 0)" % k, [out.get(k), priv.get(k)])
    lab9 = [c9[0] for c9 in cas.conn_log]
    T.chk(lab9 and not any(x.startswith(("inner-", "mixed-")) for x in lab9),
          "공인 아닌 주소가 섞인 이름(t_dnsprv · mixed) = 연결 시도 0(판정에서 거부)", lab9)
    T.chk(all(cas.lookups["name"].get("inner-%s.policy.invalid" % e.replace("_", "-")) == 1 for e in ENTS)
          and all(cas.lookups["name"].get("mixed-%s.policy.invalid" % e.replace("_", "-")) == 1 for e in ENTS)
          and all(cas.lookups["name"].get("race-%s.policy.invalid" % e.replace("_", "-")) == 1 for e in ENTS),
          "이름 조회 수 = 판정 1번(판정 뒤 다시 조회 0 · 경합 이름 = 첫 연결 1번뿐 — 출발 판정은 상대 주소로)", cas.lookups["name"])
    for k in ("rd_loop", "rd_out"):
        T.chk((out.get(k) or {}).get("exc") == "RuntimeError" and priv.get(k) == ["127.0.0.1"],
              "열쇠 %s: 루프백 내부 헤더 요청 302 = 안 따라감(auth_urlopen · HTTPError 302 → RuntimeError · 목적지 연결 0)" % k, [out.get(k), priv.get(k)])
    cas.golden(T, {"http": out, "private_conns": priv})
    cas.check(T)

print("[B] 스킴(단위 시험 · 입구 bf_engine.sol_open 문자열 URL · net_http.urlopen · auth_urlopen · 진짜 루프백 모드)")


class _Redir(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(302)
        self.send_header("Location", {"/file": "file://" + FPATH, "/data": "data:,x"}.get(self.path, "ftp://ftp2.policy.invalid/x"))
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


FPATH = os.path.join(T.TMP, "policy_scheme_file.txt")
with open(FPATH, "w", encoding="utf-8") as f:
    f.write("synthetic-file-body")


def sol_read(u):
    with bf_engine.sol_open(u, 5) as r:
        return r.read(1 << 16).decode("utf-8")


def nh_read(u, auth=False):
    with (net_http.auth_urlopen if auth else net_http.urlopen)(u, 5) as r:
        return r.read(1 << 16).decode("utf-8")


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Redir)
th = threading.Thread(target=srv.serve_forever, daemon=True)
th.start()
got, tries = {}, {}
CASES = (("file", "file://" + FPATH), ("data", "data:,x"), ("ftp_first", "ftp://ftp1.policy.invalid/x"),
         ("ftp_redirect", "http://127.0.0.1:%d/go" % srv.server_address[1]),
         ("file_redirect", "http://127.0.0.1:%d/file" % srv.server_address[1]),
         ("data_redirect", "http://127.0.0.1:%d/data" % srv.server_address[1]))
READERS = (("sol_open", sol_read), ("urlopen", nh_read), ("auth_urlopen", lambda u: nh_read(u, True)))
try:
    with C.real_loopback():
        for k, u in CASES:
            for nm9, fn9 in READERS:
                n0 = len(T.NET_TRIES)
                got[(k, nm9)] = NP.summary(fn9, u)
                tries[(k, nm9)] = list(T.NET_TRIES[n0:])
                del T.NET_TRIES[n0:]
finally:
    srv.shutdown()
    srv.server_close()
for nm9, _fn9 in READERS:
    for k in ("file", "data", "ftp_first"):
        g9, t9 = got[(k, nm9)], tries[(k, nm9)]
        T.chk(g9.get("exc") == "URLError(str)" and not t9, "열쇠 %s(%s): 6-2 = 첫 요청 스킴 거부(연결 전 URLError · 내용 안 읽힘 · 차단기 기록 0)" % (k, nm9), [g9, t9])
    for k in ("ftp_redirect", "file_redirect", "data_redirect"):
        g9, t9 = got[(k, nm9)], tries[(k, nm9)]
        T.chk(g9.get("exc") == "HTTPError" and g9.get("code") == 302 and not t9,
              "열쇠 %s(%s): http → %s 리다이렉트 = 거부(HTTPError 302 · 연결 0)%s" % (k, nm9, k.split("_")[0], "" if k == "ftp_redirect" else " — 6-0 부터 그대로"),
              [g9, t9])
T.finish()
