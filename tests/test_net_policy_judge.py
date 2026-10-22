#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import http.server  # noqa: E402
import ipaddress  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import socket  # noqa: E402
import threading  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

import net_http as N  # noqa: E402

print("[1] 주소 판정 표(파이썬 %d.%d.%d)" % sys.version_info[:3])
PUB = ["8.8.8.8", "1.1.1.1", "9.9.9.9", "172.15.255.255", "172.32.0.0", "192.167.255.255", "192.169.0.0", "169.253.255.255", "169.255.0.0",
       "100.63.255.255", "100.128.0.0", "223.255.255.255", "2606:4700:4700::1111", "2001:4860:4860::8888", "::ffff:8.8.8.8", "2002:808:808::1",
       "2001:0:4136:e378:8000:0:f7f7:f7f7"]
NOT = ["10.0.0.1", "10.255.255.255", "172.16.0.1", "172.31.255.255", "192.168.0.1", "192.168.255.255", "127.0.0.1", "127.255.255.254", "0.0.0.0",
       "0.1.2.3", "169.254.169.254", "169.254.0.1", "100.64.0.0", "100.64.1.1", "100.127.255.255", "224.0.0.1", "239.255.255.255", "240.0.0.1",
       "255.255.255.255", "192.0.2.1", "198.51.100.1", "203.0.113.1", "198.18.0.1",
       "::1", "::", "fe80::1", "fe80::1%en0", "fc00::1", "fd7a:115c:a1e0::1", "fec0::1", "ff02::1", "4000::1", "2001:db8::1",
       "64:ff9b::7f00:1", "64:ff9b::a9fe:a9fe", "64:ff9b::808:808",
       "::ffff:127.0.0.1", "::ffff:10.0.0.1", "::ffff:169.254.169.254", "::ffff:100.64.1.1", "::ffff:0.0.0.0",
       "2002:7f00:1::1", "2002:a9fe:a9fe::1", "2001:0:4136:e378:8000:63bf:3fff:fdd2",
       "example.com", "", "1.2.3", "::ffff:"]
T.chk([a for a in PUB if not N._public_ip(a)] == [], "공인 경계값 = 통과", [a for a in PUB if not N._public_ip(a)])
T.chk([a for a in NOT if N._public_ip(a)] == [], "사설·루프백·링크로컬·CGNAT·멀티캐스트·예약·미지정·문서용·사상·6to4·Teredo·IP 아님 = 공인 아님",
      [a for a in NOT if N._public_ip(a)])
T.chk(ipaddress.ip_address("fec0::1").is_site_local and ipaddress.ip_address("4000::1").is_reserved,
      "3.9 is_global 함정 자리(fec0::/10 site-local · 4000::/3 예약)가 이 판에서도 그 속성으로 잡힘", sys.version_info[:3])
PROBE = {"192.0.0.9": ipaddress.ip_address("192.0.0.9").is_global, "2001:1::1": ipaddress.ip_address("2001:1::1").is_global}
print("  판 분기(ipaddress 표 고침 반영 여부 · 리눅스 확인 항목): %s" % PROBE)
for a9, g9 in PROBE.items():
    T.chk(N._public_ip(a9) is bool(g9), "판 분기 %s: 이 판 표 = %s → 판정 %s" % (a9, "공인" if g9 else "사설", "통과" if g9 else "거부"), N._public_ip(a9))

print("[2] 첫 요청 스킴")
bad = []
for u in ("http://a.example/x", "https://a.example/x", "HTTP://a.example/x", "HTTPS://a.example/", "URL:https://a.example/x", "<URL:http://a.example/>"):
    for o9 in (u, urllib.request.Request(u)):
        try:
            N._scheme_check(o9)
        except urllib.error.URLError:
            bad.append(u)
for u in ("relative/path", ""):
    try:
        N._scheme_check(u)
    except urllib.error.URLError:
        bad.append(u)
T.chk(not bad, "http·https(대소문자 무관 · 글자·Request) · 스킴 없는 글자 = 판정 통과(urllib 이 지금처럼 처리)", bad)
den = []
for u in ("file:///etc/hosts", "ftp://a.example/x", "data:,x", "gopher://a.example/", "jar:file:/x!/y", "FILE:///x",
          "<file:///etc/hosts>", "<URL:data:,x>", " ftp://a.example/x ", "<URL: file:///x >"):
    for o9 in (u, urllib.request.Request(u)):
        try:
            N._scheme_check(o9)
            den.append(u)
        except urllib.error.URLError as e:
            if not isinstance(e.reason, str) or "/" in e.reason:
                den.append("문구에 URL? " + str(e.reason))
T.chk(not den, "file·ftp·data·gopher·jar(감싼 <…>·URL:·공백 꼴 포함) = URLError(문구에 URL 없음 · 글자·Request 둘 다)", den)
print("[3] 출발 판정")


def rq(url, conn=False, origin=None):
    r9 = urllib.request.Request(url)
    if conn is not False:
        r9.tj_conn = conn
    if origin is not None:
        r9.tj_origin = origin
    return r9


O = [("loop peer", rq("http://localhost:3002/x", ("127.0.0.1", 3002)), False),
     ("tailnet peer", rq("http://node.example/x", ("100.100.1.2", 80)), False),
     ("ula peer", rq("http://node.example/x", ("fd7a:115c:a1e0::5", 80, 0, 0)), False),
     ("public peer", rq("https://a.example/x", ("8.8.8.8", 443)), True),
     ("peer unknown(목·읽기 실패)", rq("http://127.0.0.1/x"), True),
     ("peer None(프록시 경유 · 읽기 실패)", rq("http://10.255.0.7/x", None), True),
     ("NAT64 상대(바깥 IPv4 공인)", rq("http://v4only.example/x", ("64:ff9b::808:808", 80, 0, 0)), True),
     ("NAT64 상대(안쪽 루프백 꼴)", rq("http://v4only.example/x", ("64:ff9b::7f00:1", 80, 0, 0)), True),
     ("지역용 NAT64 상대", rq("http://v4only.example/x", ("64:ff9b:1::a00:1", 80, 0, 0)), True),
     ("물려받음 공인", rq("http://127.0.0.1/x", ("127.0.0.1", 80), True), True),
     ("물려받음 사설", rq("https://a.example/x", ("8.8.8.8", 443), False), False)]
T.chk([n9 for n9, r9, w9 in O if N._origin_public(r9) is not w9] == [], "출발 = 첫 연결 상대 주소(모르면 공인 — 프록시 경유는 호스트 글자를 해석하지 않음 · NAT64 상대 = 공인) · 리다이렉트 사슬은 물려받음",
      [(n9, N._origin_public(r9)) for n9, r9, w9 in O])

print("[4] 주소 고정(판정한 목록을 그 순서로 · 연결 함수 주입)")
CALLS = []
SENT = object()


def infos(*ips, port=443):
    return [((socket.AF_INET6 if ":" in ip else socket.AF_INET), socket.SOCK_STREAM, 6, "", (ip, port) + ((0, 0) if ":" in ip else ())) for ip in ips]


def pin(ips, fail=None, to=7, src=None):
    del CALLS[:]

    def cc(address, timeout=None, source_address=None):
        CALLS.append((tuple(address), timeout, source_address))
        if address[0] in (fail or {}):
            raise fail[address[0]]
        return SENT
    try:
        return N._pinned_connect(infos(*ips), 443, to, src, "https://two.example/t", cc)
    except Exception as e:   # noqa: BLE001
        return e


r = pin(["2606:4700:4700::2001", "9.9.9.81"], {"2606:4700:4700::2001": ConnectionRefusedError(61, "refused")}, to=7, src=("0.0.0.0", 0))
T.chk(r is SENT and [c[0] for c in CALLS] == [("2606:4700:4700::2001", 443), ("9.9.9.81", 443)] and all(c[1:] == (7, ("0.0.0.0", 0)) for c in CALLS),
      "주소 2개: 첫째 거부 → 둘째 성공 · 주소마다 create_connection((ip, port), 같은 timeout·source_address)", [r, CALLS])
e9 = [TimeoutError("t1"), ConnectionRefusedError(61, "last")]
r = pin(["9.9.9.81", "9.9.9.82"], {"9.9.9.81": e9[0], "9.9.9.82": e9[1]})
T.chk(r is e9[1] and len(CALLS) == 2, "전부 실패 = 마지막 오류 그대로(표준 create_connection 과 같음)", [r, CALLS])
for ips9, nm9 in ((["9.9.9.81", "10.255.0.8"], "공인·사설 섞임"), (["::ffff:127.0.0.1"], "IPv4 사상 루프백"), (["169.254.169.254"], "메타데이터")):
    r = pin(ips9)
    T.chk(isinstance(r, N._Denied) and isinstance(r, OSError) and not CALLS and r.args == ("https://two.example/t",),
          "%s = 정책 거부 표식(OSError 하위 · 연결 0 · args = 그 요청 URL)" % nm9, [r, CALLS])
r = pin([])
T.chk(type(r) is OSError and not CALLS, "조회 결과 0개 = OSError(표준 문구 꼴)", r)

print("[5] 프록시 판정(표준 ProxyHandler 가 고친 요청)")
ENV0 = {k: os.environ.get(k) for k in ("http_proxy", "https_proxy", "no_proxy", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY")}


def env(**kv):
    for k in ENV0:
        os.environ.pop(k, None)
    os.environ.update(kv)


def routed(url, table):
    r9 = urllib.request.Request(url)
    ph = urllib.request.ProxyHandler(table)
    meth = getattr(ph, r9.type + "_open", None)
    if meth is not None:
        meth(r9)
    return N._via_proxy(r9, getattr(r9, "_tunnel_host", None))


TBL = {"http": "http://127.0.0.1:9", "https": "http://127.0.0.1:9"}
try:
    env(http_proxy="http://127.0.0.1:9", no_proxy="bypass.example,localhost")
    R5 = {"http 경유": (routed("http://a.example/x", TBL), True), "https 경유(터널)": (routed("https://a.example/x", TBL), True),
          "no_proxy 이름 = 직접": (routed("http://bypass.example/x", TBL), False), "no_proxy localhost:포트 = 직접": (routed("http://localhost:8/x", TBL), False),
          "표에 없는 스킴(https 만 없음) = 직접": (routed("https://a.example/x", {"http": TBL["http"]}), False), "빈 표 = 직접": (routed("http://a.example/x", {}), False)}
finally:
    env(**{k: v for k, v in ENV0.items() if v is not None})
T.chk(all(g9 is w9 for g9, w9 in R5.values()), "경유/직접 = ProxyHandler 의 실제 판정(표 · no_proxy 우회 · 스킴별)", R5)
T.chk(N._via_proxy(urllib.request.Request("http://a.example/"), None) is False and N._via_proxy(None, "a.example:443") is True and N._via_proxy(None, "") is True,
      "직접 요청 = 직접 · 터널 호스트 있음 = 경유(빈 터널 호스트 '' 도 — https://:443/)")

print("[6] 루프백 가짜 프록시 서버(경유 hop = 지금 라이브와 같음)")
PHITS, DHITS = [], []
LOC = {"start-name": "http://inner.policy.invalid/t", "start-lit": "http://10.255.0.9/t", "start-np": None,
       "start-lit2": "http://10.255.0.9/t2", "start-enc": "http://%31%30.255.0.9/t3",
       "start-v6p": "https://[fd00::1]/t4", "start-v6g": "https://[2606:4700:4700::1111]/t5",
       "start-ui": "http://u%2f@127.0.0.1:8023/t6", "start-tui": "https://u@127.0.0.1/t7", "start-tsl": "https://127.0.0.1%2fignored/t8",
       "start-tname": "https://www.policy.invalid/t9", "start-ftp": "ftp://f.policy.invalid/t10", "start-meta": "http://169.254.169.254/latest/t11"}


class _Proxy(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        PHITS.append(self.path)
        k9 = self.path.rsplit("/", 1)[-1]
        loc = ("http://localhost:%d/t" % DPORT) if k9 == "start-np" else LOC.get(k9)
        if loc:
            self.send_response(302)
            self.send_header("Location", loc)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        b9 = json.dumps({"at": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(b9)))
        self.end_headers()
        self.wfile.write(b9)

    def do_CONNECT(self):
        PHITS.append("CONNECT " + self.path)
        self.send_response(403)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


class _Dst(_Proxy):
    def do_GET(self):
        DHITS.append(self.path)
        super().do_GET()


psrv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Proxy)
dsrv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Dst)
PPORT, DPORT = psrv.server_address[1], dsrv.server_address[1]
_cs = socket.socket()
_cs.bind(("127.0.0.1", 0))
CLOSED = _cs.getsockname()[1]
_cs.close()
for s9 in (psrv, dsrv):
    threading.Thread(target=s9.serve_forever, daemon=True).start()
PT = {"http": "http://127.0.0.1:%d" % PPORT, "https": "http://127.0.0.1:%d" % PPORT, "ftp": "http://127.0.0.1:%d" % PPORT}
POL = (N._PolicyRedirect, N._PinHTTPHandler, N._PinHTTPSHandler, N._PolicyFTPHandler)
op = urllib.request.build_opener(*[c9(False) if c9 is N._PolicyRedirect else c9() for c9 in POL], urllib.request.ProxyHandler(PT))
live = urllib.request.build_opener(urllib.request.ProxyHandler(PT))
op_noftp = urllib.request.build_opener(*[c9(False) if c9 is N._PolicyRedirect else c9() for c9 in POL],
                                       urllib.request.ProxyHandler({k: v for k, v in PT.items() if k != "ftp"}))


FLIP = []


class _FlipProxy(urllib.request.ProxyHandler):

    def proxy_open(self, req, proxy, type):
        if "f.policy.invalid" in str(req.host):
            FLIP.append(req.host)
            if len(FLIP) > 1:
                return None
        return super().proxy_open(req, proxy, type)


op_flip = urllib.request.build_opener(*[c9(False) if c9 is N._PolicyRedirect else c9() for c9 in POL], _FlipProxy(PT))


def go(o9, url):
    del PHITS[:], DHITS[:]
    try:
        with o9.open(url, timeout=5) as r9:
            out = {"ret": json.loads(r9.read().decode()), "url": r9.geturl()}
    except urllib.error.HTTPError as e:
        out = {"exc": "HTTPError", "code": e.code, "msg": e.msg, "url": e.geturl(), "body": e.read()}
    except urllib.error.URLError as e:
        out = {"exc": "URLError", "reason": type(e.reason).__name__, "rs": str(e.reason)}
    out["ph"], out["dh"] = list(PHITS), list(DHITS)
    return out


SAME = (("name", "http://pub.policy.invalid/start-name"), ("lit", "http://pub.policy.invalid/start-lit"), ("lit2", "http://10.255.0.7/start-lit2"),
        ("enc", "http://pub.policy.invalid/start-enc"), ("v6p", "http://pub.policy.invalid/start-v6p"), ("v6g", "http://pub.policy.invalid/start-v6g"),
        ("ui", "http://pub.policy.invalid/start-ui"), ("v6o", "http://2606:4700:4700::1111:80/start-lit"), ("tui", "http://pub.policy.invalid/start-tui"),
        ("tsl", "http://pub.policy.invalid/start-tsl"), ("tname", "http://pub.policy.invalid/start-tname"), ("ftp", "http://pub.policy.invalid/start-ftp"),
        ("meta", "http://pub.policy.invalid/start-meta"))
try:
    env(http_proxy="http://127.0.0.1:%d" % PPORT, no_proxy="localhost")
    R6 = {k: (go(op, u), go(live, u)) for k, u in SAME}
    NP = (go(op, "http://pub.policy.invalid/start-np"), go(live, "http://pub.policy.invalid/start-np"))
    FTPD = go(op_noftp, "http://pub.policy.invalid/start-ftp")
    env(http_proxy="http://127.0.0.1:%d" % PPORT, no_proxy="localhost,f.policy.invalid")
    FTPB = go(op, "http://pub.policy.invalid/start-ftp")
    env(http_proxy="http://127.0.0.1:%d" % PPORT, no_proxy="localhost")
    FTPF = (go(op_flip, "http://pub.policy.invalid/start-ftp"), go(op_flip, "http://pub.policy.invalid/start-ftp"))
    FP = {}
    for nm9, px9 in (("ftp://", "ftp://127.0.0.1:%d" % CLOSED), ("스킴 없음", "127.0.0.1:%d" % CLOSED)):
        t9 = dict(PT, ftp=px9)
        FP[nm9] = tuple(go(urllib.request.build_opener(*hs9, urllib.request.ProxyHandler(t9)), "http://pub.policy.invalid/start-ftp")
                        for hs9 in ([c9(False) if c9 is N._PolicyRedirect else c9() for c9 in POL], []))
finally:
    env(**{k: v for k, v in ENV0.items() if v is not None})
    for s9 in (psrv, dsrv):
        s9.shutdown()
        s9.server_close()
T.chk([k9 for k9, (a9, b9) in R6.items() if a9 != b9] == [], "프록시 경유 hop = 지금 라이브와 같은 결과·같은 프록시 요청(IP 문자 사설·퍼센트·userinfo·대괄호 없는 IPv6·터널·ftp·메타데이터 — 알려진 한계)",
      {k9: v9 for k9, v9 in R6.items() if v9[0] != v9[1]})
T.chk((R6["name"][0].get("ret") or {}).get("at") == "http://inner.policy.invalid/t" and (R6["meta"][0].get("ret") or {}).get("at") == LOC["start-meta"]
      and (R6["ftp"][0].get("ret") or {}).get("at") == LOC["start-ftp"],
      "녹화 확인: 경유 이름·메타데이터 IP·ftp 목적지 = 프록시로 따라감(라이브 그대로)", [R6["name"][0], R6["meta"][0], R6["ftp"][0]])
T.chk(R6["v6p"][0].get("exc") == "URLError" and any(p9.startswith("CONNECT ") and "fd00::1" in p9 for p9 in R6["v6p"][0]["ph"]),
      "녹화 확인: CONNECT 터널 경유 = 프록시에 CONNECT(이 시험 프록시는 터널 거절 → URLError — 라이브 그대로)", R6["v6p"][0])
T.chk(NP[0].get("exc") == "HTTPError" and NP[0].get("code") == 302 and NP[0].get("msg") == "redirect target not allowed"
      and NP[0].get("url") == "http://localhost:%d/t" % DPORT and NP[0].get("body") == b"" and NP[0]["dh"] == [],
      "no_proxy 로 직접이 된 사설 목적지(localhost · 출발 = 프록시라 모름 = 공인) = 거부 HTTPError(목적지 URL · 302 · 본문 b'') · 목적지 서버 요청 0", NP[0])
T.chk((NP[1].get("ret") or {}).get("at") == "/t" and NP[1]["dh"] == ["/t"], "대조: 라이브는 그 직접 사설 목적지를 따라감(이것이 조임)", NP[1])
T.chk(FTPD.get("exc") == "HTTPError" and FTPD.get("code") == 302 and FTPD.get("msg") == "redirect target not allowed" and FTPD.get("url") == LOC["start-ftp"],
      "직접 연결 ftp 리다이렉트(표에 ftp 없음) = 거부(연결 전)", FTPD)
T.chk(FTPB.get("exc") == "HTTPError" and FTPB.get("msg") == "redirect target not allowed" and FTPB.get("url") == LOC["start-ftp"]
      and not any("ftp://" in p9 for p9 in FTPB["ph"]), "표에 ftp 가 있어도 no_proxy 우회 = 직접 ftp = 거부(프록시에도 안 감)", FTPB)
T.chk((FTPF[0].get("ret") or {}).get("at") == LOC["start-ftp"] and FTPF[1].get("exc") == "HTTPError" and FTPF[1].get("msg") == "redirect target not allowed"
      and len(FLIP) == 2, "우회 판정이 바뀌는 꼴: ProxyHandler 가 경유를 고른 번 = 프록시로(라이브 그대로) · 직접을 고른 번 = 거부(판정 한 곳)", [FTPF, FLIP])
T.chk(all(a9 == b9 and a9.get("exc") == "URLError" and a9.get("reason") != "_Denied" for a9, b9 in FP.values()),
      "ftp:// · 스킴 없는 ftp 프록시 경유 hop = 라이브와 같은 결과(FTP 처리기가 프록시로 연결 시도 · 정책 거부 아님)", FP)

print("[7] opener 수명")
o1, o2 = N._opener(False), N._opener(True)
T.chk(N._opener(False) is o1 and N._opener(True) is o2 and o1 is not o2, "정책별 opener 한 번 · 재사용")
T.chk(all(any(type(h) is c9 for h in o1.handlers) for c9 in POL) and not any(isinstance(h, (N._PinHTTPHandler, N._PinHTTPSHandler, N._PolicyFTPHandler)) for h in o2.handlers)
      and not any(type(h) is urllib.request.FTPHandler for h in o1.handlers)
      and [h.auth for h in o1.handlers if isinstance(h, N._PolicyRedirect)] == [False] and [h.auth for h in o2.handlers if isinstance(h, N._PolicyRedirect)] == [True],
      "비인증 = 정책 처리기 + 정책 연결 · 인증 = 리다이렉트 0 처리기 + 표준 연결", [type(h).__name__ for h in o1.handlers])
T.chk(not any(type(h) is urllib.request.HTTPRedirectHandler for h in o1.handlers + o2.handlers), "표준 리다이렉트 처리기는 정책 처리기로 대체(둘이 겹치지 않음)")
T.finish()
