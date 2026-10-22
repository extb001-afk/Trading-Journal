#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _cassette as C  # noqa: E402

C.freeze()
import base64  # noqa: E402
import datetime  # noqa: E402
import hashlib  # noqa: E402
import hmac  # noqa: E402
import http.client  # noqa: E402
import http.server  # noqa: E402
import ipaddress  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import socket  # noqa: E402
import ssl  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.parse  # noqa: E402
import urllib.request  # noqa: E402
import uuid  # noqa: E402

import bf_engine  # noqa: E402
import net_http  # noqa: E402

chk = T.chk
D = tempfile.mkdtemp(prefix="tj_casframe_", dir=T.TMP)
SEC = {"api_key": "frameKEY0001zz", "api_secret": "frameSECRET0001zz", "jwt_secret": "frameJWTsecret01zz"}
W = "0x" + "a1" * 20
H1 = "0x" + "0" * 57 + "abc0001"
bf_engine.configure({"backfill": {"hosts": {"rpc.frame.invalid": {"rate": 5000, "burst": 5000, "conc": 8}}}})

print("[f1] 합성 16진수 압축 표기")
TOPIC = "0x" + "0" * 24 + "a1" * 20
for v in (W, H1, TOPIC, "0x" + "AbCd" * 10, "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"):
    e = C.enc({v: [v, "x" + v]})
    chk(C.dec(e) == {v: [v, "x" + v]} and ("«" in json.dumps(e, ensure_ascii=False)) == (not v.endswith("23b3ef")),
        "왕복 그대로 · 합성 꼴 = 압축 표기 · 공개 상수 = 그대로: " + v[:12], e)
REAL = "0x" + hashlib.sha256(b"not synthetic").hexdigest()[:40]
try:
    C.enc({"a": REAL})
    ok = False
except ValueError:
    ok = True
chk(ok, "합성 꼴 아닌 40자리 16진수 = 무손실 표기 거부(실값이 파일로 못 감)")
chk(C.enc(REAL, lossy=True).startswith("0x«~") and REAL[2:] not in C.enc(REAL, lossy=True), "손실 모드 = 지문만", C.enc(REAL, lossy=True))
chk(C.enc("0x" + "ab" * 60) == "0x" + "ab" * 60, "합성 무늬 긴 16진수(ABI 데이터 등)는 그대로(스캔 대상 아님)")
ABI_REAL = "0xa9059cbb" + "0" * 24 + REAL[2:] + "0" * 63 + "1"
try:
    C.enc({"input": ABI_REAL})
    ok = False
except ValueError:
    ok = True
chk(ok and C.enc(ABI_REAL, lossy=True).startswith("0x«~") and REAL[2:] not in C.enc(ABI_REAL, lossy=True),
    "긴 16진수(ABI) 안에 숨은 합성 아닌 주소 = 무손실 거부 · 손실 모드 지문")
ABI_SYN = "0xa9059cbb" + "0" * 24 + "a1" * 20 + "0" * 63 + "1"
chk(C.enc(ABI_SYN) == ABI_SYN, "합성 주소만 든 긴 ABI 데이터 = 그대로(읽기 쉽게)")
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
SIG_REAL = "".join(B58[x % 58] for x in hashlib.sha512(b"not synthetic sig").digest()) + "Ab9"
try:
    C.enc({"sig": SIG_REAL})
    ok = False
except ValueError:
    ok = True
chk(ok and C.enc({"sig": "5" * 80 + "sigaaaa1"}) == {"sig": "5" * 80 + "sigaaaa1"}, "긴 base58 꼴: 대소문자·숫자 섞인 실값 모양 = 거부 · 합성(대문자 없음) = 그대로")

print("[f2] 시각·무작위 고정")
chk(time.time() == C.NOW and int(datetime.datetime.now(datetime.timezone.utc).timestamp()) == int(C.NOW), "time · datetime = 고정 시각",
    [time.time(), datetime.datetime.now(datetime.timezone.utc).isoformat()])
chk(time.strftime("%Y%m%d%H%M%S") == datetime.datetime.fromtimestamp(C.NOW, datetime.timezone.utc).strftime("%Y%m%d%H%M%S") and time.gmtime().tm_year >= 2025,
    "strftime·gmtime 기본값도 고정 시각(UTC)", time.strftime("%Y%m%d%H%M%S"))
m1 = time.monotonic()
chk(C.MONO_BASE <= m1 < C.MONO_BASE + 600 and time.monotonic() >= m1, "monotonic = 고정 기준(오래 돈 서버) + 실제 경과(플랫폼마다 0·부팅 기준이 달라도 같은 판정)", m1)
u1, u2 = uuid.uuid4(), uuid.uuid4()
chk(u1.version == 4 and u1.hex[:10] != u2.hex[:10] and "-5eed-4eed-8eed-" in str(u1) and int(u2.hex[:8], 16) == int(u1.hex[:8], 16) + 1,
    "uuid4 = 결정적 카운터(버전 4 · 짧은 접두도 서로 다름)", [str(u1), str(u2)])
chk(C.enc({"id": "c1:" + str(u2)}) == {"id": "c1:«u:%d»" % int(u2.hex[:8], 16)} and C.dec(C.enc({"id": str(u2)})) == {"id": str(u2)},
    "고정 uuid4 값 = «u:n» 왕복(스캔의 UUID 규칙에 안 걸림)", C.enc({"id": str(u2)}))
try:
    C.enc({"id": str(uuid.UUID(hashlib.md5(b"not a frozen uuid").hexdigest()))})
    ok = False
except ValueError:
    ok = True
chk(ok, "고정 uuid4 가 아닌 UUID = 무손실 표기 거부")


class PinnedHTTPS(http.client.HTTPSConnection):

    def connect(self):
        ip = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)[0][4][0]
        if not ipaddress.ip_address(ip).is_global:
            raise OSError("사설 IP 거부")
        self.sock = socket.create_connection((ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


class SafeHTTPS(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(PinnedHTTPS, req, context=self._context)


class NoRedir(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


SAFE = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedir(), SafeHTTPS())


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def jwt(secret, q, nonce=None):
    hd = b64u(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    pl = b64u(json.dumps({"access_key": SEC["api_key"], "nonce": nonce or str(uuid.uuid4()), "query_hash": hashlib.sha512(q.encode()).hexdigest(),
                          "query_hash_alg": "SHA512"}).encode())
    return f"{hd}.{pl}." + b64u(hmac.new(secret.encode(), f"{hd}.{pl}".encode(), hashlib.sha256).digest())


def client(var=None):
    var = var or {}
    out = []
    ts = str(int(time.time() * 1000))
    q = f"symbol=TESTUSDT&limit={var.get('limit', 5)}&timestamp={ts}"
    sig = hmac.new(var.get("secret", SEC["api_secret"]).encode(), q.encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request(f"https://ex.frame.invalid/api/v3/myTrades?{q}&signature={sig}",
                                 headers={"X-MBX-APIKEY": SEC["api_key"], "User-Agent": var.get("ua", "frame-ua/1")})
    with urllib.request.urlopen(req, timeout=var.get("timeout", 5)) as r:
        out.append(json.loads(r.read()))
    if not var.get("skip_auth"):
        req = urllib.request.Request("https://ex.frame.invalid/v5/account?accountType=UNIFIED", headers={"X-API-KEY": SEC["api_key"], "X-TS": ts})
        try:
            with net_http.auth_urlopen(req, timeout=5) as r:
                out.append(json.loads(r.read()))
        except urllib.error.HTTPError as e:
            out.append({"http": e.code, "body": json.loads(e.read())})
    res = bf_engine.rpc_batch("https://rpc.frame.invalid/v2/" + SEC["api_key"], [("eth_blockNumber", []), ("eth_getBalance", [W, "latest"])])
    out.append(res)
    c = http.client.HTTPSConnection("plain.frame.invalid", timeout=5)
    c.request("GET", "/status?x=1", headers={"Accept": "application/json"})
    r = c.getresponse()
    out.append([r.status, json.loads(r.read())])
    c.close()
    with SAFE.open(urllib.request.Request("https://pinned.frame.invalid/v1/price?ids=fake", headers={"User-Agent": "frame-ua/1"}), timeout=5) as r:
        out.append(json.loads(r.read()))
    qj = "market=KRW-TEST&state=done"
    req = urllib.request.Request("https://jwt.frame.invalid/v1/orders?" + qj,
                                 headers={"Authorization": "Bearer " + jwt(var.get("jsec", SEC["jwt_secret"]), qj)})
    with urllib.request.urlopen(req, timeout=5) as r:
        out.append(json.loads(r.read()))
    return out


def responder(rq):
    if rq.host == "ex.frame.invalid" and rq.path == "/api/v3/myTrades":
        return [{"id": 7, "qty": "1.5", "price": "100.25", "time": int(C.NOW * 1000)}]
    if rq.path == "/v5/account":
        return C.Reply({"retCode": 10003, "retMsg": "invalid key"}, status=401)
    if rq.host == "rpc.frame.invalid":
        return [{"jsonrpc": "2.0", "id": it["id"], "result": ("0x10" if it["method"] == "eth_blockNumber" else "0xde0b6b3a7640000")} for it in rq.json()]
    if rq.host == "plain.frame.invalid":
        return {"ok": True, "addr": W, "tx": H1}
    if rq.host == "pinned.frame.invalid":
        return {"fake": {"usd": 1.25}}
    if rq.host == "jwt.frame.invalid":
        return [{"uuid": "ord-0001", "market": "KRW-TEST", "side": "bid"}]
    raise AssertionError("모르는 요청 " + rq.url)


class Sink:

    def __init__(self):
        self.res = []

    def chk(self, ok, msg, extra=None):
        self.res.append((bool(ok), msg, extra))

    def bad(self):
        return [m for ok, m, _x in self.res if not ok]


print("[f3] 녹화 → 재생")
rec = C.Cassette("frame_demo", secrets=SEC, responder=responder, dirpath=D, record=True)
out_rec, miss = rec.run(client)
chk(miss is None and len(out_rec) == 6, "녹화: 6갈래 모두 응답기로", [miss, out_rec])
skr = Sink()
rec.golden(skr, {"out": out_rec})
rec.check(skr)
chk(any("녹화 모드" in m for m in skr.bad()) and os.path.isfile(os.path.join(D, "frame_demo.golden.json")),
    "녹화 = 파일 저장 + '판정 아님' FAIL 한 줄(녹화 변수를 남긴 채 게이트를 돌려도 통과 못 함)", skr.res)
txt = open(os.path.join(D, "frame_demo.json"), encoding="utf-8").read()
chk(all(v not in txt for v in SEC.values()) and "<secret:api_key>" in txt, "[f6] 등록 비밀값은 파일에 없음 · <secret:이름> 자리표시")
doc = json.load(open(os.path.join(D, "frame_demo.json"), encoding="utf-8"))
mt = [e for e in doc["interactions"] if "/api/v3/myTrades" in e["key"]]
ms = str(int(C.NOW * 1000))
chk(len(mt) == 1 and mt[0]["key"].endswith("&timestamp=<timestamp>&signature=<signature>") and mt[0]["auth"].get("?timestamp") == ms
    and str(mt[0]["auth"].get("?signature", "")).startswith("h:") and mt[0]["auth"].get("x-mbx-apikey") == "<secret:api_key>",
    "[f6] 시각·서명 칸은 키에서 가림 — 값은 인증 칸(시각 = 원값 · 서명 = 지문 · 키 = 자리표시)", mt and mt[0])
jw = [e["auth"].get("authorization") for e in doc["interactions"] if "jwt.frame" in e["key"]]
chk(jw and jw[0]["jwt"]["signed_by"] == "jwt_secret" and jw[0]["jwt"]["claims"]["nonce"] == "<nonce>"
    and jw[0]["jwt"]["claims"]["access_key"] == "<secret:api_key>", "JWT = claims(nonce 가림) + 서명한 비밀값 이름", jw)
pin = [e for e in doc["interactions"] if "pinned.frame" in e["key"]]
chk(len(pin) == 1, "연결 전 이름 조회·사설 IP 거부·연결 재정의 opener 도 카세트로 감", [e["key"] for e in doc["interactions"]])
chk("0x«a1*20»" in txt and "0x«0*57+abc0001»" in txt and W not in txt and H1 not in txt, "파일 안 합성 주소·해시 = 압축 표기(스캔에 안 걸림)")


def replay(var=None):
    n0 = len(T.NET_TRIES)
    cas = C.Cassette("frame_demo", secrets=SEC, dirpath=D)
    out, miss = cas.run(client, var)
    sk = Sink()
    if miss is None:
        cas.golden(sk, {"out": out})
    cas.check(sk)
    tries = T.NET_TRIES[n0:]
    del T.NET_TRIES[n0:]
    return out, miss, sk, tries, cas


out, miss, sk, tries, _c = replay()
chk(miss is None and out == out_rec and not sk.bad() and not tries, "재생: 같은 결과 · 판정 전부 통과(새 요청 0 · 빠진 요청 0 · 헤더·인증 같음 · 골든 같음)",
    [miss, sk.bad(), tries])

print("[f4] 새 요청 감지")
out, miss, sk, tries, _c = replay({"limit": 6})
chk(miss is not None and "limit=6" in miss and any("카세트에 없는 요청·깨진 전송 0" in m for m in sk.bad()) and tries,
    "쿼리 값 하나 바뀜 = CassetteMiss(무엇이 나갔는지 출력) + 하네스 바깥 시도 기록", [miss, sk.bad(), tries])


def swallowing():
    try:
        client({"limit": 9})
    except Exception:   # noqa: BLE001
        return "삼킴"
    return "통과"


cas9 = C.Cassette("frame_demo", secrets=SEC, dirpath=D)
n0 = len(T.NET_TRIES)
res9, miss9 = cas9.run(swallowing)
del T.NET_TRIES[n0:]
chk(res9 is None and miss9 is not None, "except Exception 으로 감싸도 CassetteMiss 는 시험까지 올라옴", [res9, miss9])
LEAK = []


class WrongPort(http.client.HTTPSConnection):

    def connect(self):
        ip = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)[0][4][0]
        self.sock = self._context.wrap_socket(socket.create_connection((ip, 8443), self.timeout), server_hostname=self.host)


class WrongPortHTTPS(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(WrongPort, req, context=self._context)


def side(kind):
    if kind == "loop":
        return urllib.request.urlopen("http://127.0.0.1:8545/rpc", timeout=1).read()
    if kind == "direct":
        s9 = socket.socket()
        try:
            return s9.connect(("127.0.0.1", 9))
        finally:
            s9.close()
    if kind == "dup":
        c = http.client.HTTPSConnection("plain.frame.invalid", timeout=5)
        c.putrequest("GET", "/status?x=1")
        c.putheader("Accept", "application/json")
        c.putheader("Accept", "text/plain")
        c.endheaders()
        return c.getresponse().status
    if kind == "port":
        rq9 = urllib.request.Request("https://pinned.frame.invalid/v1/price?ids=fake", headers={"User-Agent": "frame-ua/1"})
        return urllib.request.build_opener(NoRedir(), WrongPortHTTPS()).open(rq9, timeout=5).read()
    if kind == "abs":
        c = http.client.HTTPSConnection("pinned.frame.invalid", 8443, timeout=5)
        c.request("GET", "https://pinned.frame.invalid/v1/price?ids=fake", headers={"User-Agent": "frame-ua/1"})
        return c.getresponse().read()
    if kind == "dsec":
        s9 = socket.socket()
        try:
            return s9.connect((SEC["api_key"] + ".frame.invalid", 443))
        finally:
            s9.close()
    if kind == "svc":
        socket.create_connection(("probe.frame.invalid", "https"), timeout=1)
        return "열기만"
    if kind in ("tcp", "recv"):
        s9 = socket.create_connection(("probe.frame.invalid", 443), timeout=1)
        if kind == "tcp":
            s9.close()
            return "닫음"
        s9.sendall(b"PING\r\n")
        return s9.recv(10)
    c = http.client.HTTPSConnection("plain.frame.invalid" if kind != "badlen" else "rpc.frame.invalid", timeout=5)
    if kind == "badlen":
        c.request("POST", "/v2/x", body=b'{"a":1}', headers={"Content-Length": "99", "Content-Type": "application/json"})
        return c.getresponse().status
    c.request("GET", "/ping?" + kind)
    if kind == "unread":
        c.close()
    else:
        LEAK.append(c)
    return "보냄"


for kind9, want9 in (("unread", "/ping?unread"), ("leak", "/ping?leak"), ("badlen", "Content-Length 99"), ("tcp", "HTTP 요청 없는 연결"),
                     ("recv", "직접 읽기"), ("loop", "http://127.0.0.1:8545/rpc"), ("direct", "소켓 직접 연결"), ("dup", "같은 헤더 두 번"),
                     ("port", "pinned.frame.invalid:8443"), ("abs", "요청 대상 URL 원점"), ("dsec", "<secret:api_key>"),
                     ("svc", "HTTP 요청 없는 연결")):
    n0 = len(T.NET_TRIES)
    cas9 = C.Cassette("frame_demo", secrets=SEC, dirpath=D)
    res9, miss9 = cas9.run(side, kind9)
    sk9 = Sink()
    cas9.check(sk9)
    del T.NET_TRIES[n0:]
    got9 = (miss9 or "") + json.dumps(sk9.res, ensure_ascii=False) + json.dumps(cas9.misses, ensure_ascii=False)
    chk(want9 in got9 and SEC["api_key"] not in got9 and any("카세트에 없는 요청·깨진 전송 0" in m for m in sk9.bad())
        and socket.create_connection.__module__ == "socket",
        f"{kind9}: 카세트 밖으로 새지 않음(새 요청·깨진 전송 = 실패 · 문구의 비밀값 가림 · 블록 끝 원복)", [res9, miss9, sk9.bad()])


def noverify():
    ctx9 = ssl.create_default_context()
    ctx9.check_hostname = False
    ctx9.verify_mode = ssl.CERT_NONE
    rq9 = urllib.request.Request("https://pinned.frame.invalid/v1/price?ids=fake", headers={"User-Agent": "frame-ua/1"})
    return urllib.request.urlopen(rq9, timeout=5, context=ctx9).read()


n0 = len(T.NET_TRIES)
for fn9, want9, msg9 in ((noverify, "검증 꺼짐", "TLS 검증 끔 = 같은 요청이어도 실패(:tls 가상 헤더)"),
                         (lambda: "돌아옴", "주기 끝 sleep 전에", "stop_sleep 을 줬는데 함수가 그냥 돌아옴 = 실패(수집기 루프가 끝나는 회귀)")):
    cas9 = C.Cassette("frame_demo", secrets=SEC, dirpath=D)
    res9, miss9 = cas9.run(fn9, stop_sleep=60 if fn9 is not noverify else None)
    sk9 = Sink()
    cas9.check(sk9)
    chk(want9 in (miss9 or "") + json.dumps(sk9.res, ensure_ascii=False) and sk9.bad(), msg9, [miss9, sk9.bad()])
del T.NET_TRIES[n0:]

print("[f5] 빠진 요청·헤더·서명 변화")
out, miss, sk, tries, _c = replay({"skip_auth": True})
chk(miss is None and any("안 나간 요청 0" in m for m in sk.bad()), "녹화한 요청 하나가 안 나감 = 실패", sk.bad())
out, miss, sk, tries, _c = replay({"ua": "frame-ua/2"})
chk(miss is None and any("헤더·인증" in m for m in sk.bad()) and "frame-ua/2" in json.dumps([x for _o, _m, x in sk.res], ensure_ascii=False),
    "User-Agent 바뀜 = 실패(무엇이 바뀌었는지 출력)", sk.res[-2:])
out, miss, sk, tries, _c = replay({"secret": "otherSECRETzz"})
chk(miss is None and any("헤더·인증" in m for m in sk.bad()), "서명 비밀값 바뀜(같은 쿼리) = 인증 칸 실패", sk.bad())
uuid.uuid4()
out, miss, sk, tries, _c = replay()
chk(miss is None and not sk.bad(), "JWT nonce 만 달라짐(uuid 순서) = 통과(nonce 는 가림 · 서명은 검증)", sk.bad())
out, miss, sk, tries, _c = replay({"jsec": "wrongJWTsecretzz"})
chk(miss is None and any("헤더·인증" in m for m in sk.bad()), "JWT 를 다른 비밀값으로 서명 = 실패(signed_by 바뀜)", sk.bad())
out, miss, sk, tries, _c = replay({"timeout": 6})
chk(miss is None and any("헤더·인증" in m for m in sk.bad()) and ":timeout" in json.dumps(sk.res, ensure_ascii=False),
    "요청 timeout 바뀜(공용 opener 로 옮기며 빠짐 등) = 실패(:timeout 가상 헤더)", sk.bad())
casg = C.Cassette("frame_demo", secrets=SEC, dirpath=D)
outg, missg = casg.run(client)
skg = Sink()
casg.golden(skg, {"out": outg, "leak": "k=" + SEC["api_key"]})
casg.check(skg)
gtx = json.dumps(skg.res, ensure_ascii=False)
chk(any("골든 차이" in m for m in skg.bad()) and any("등록 비밀값 없음" in m for m in skg.bad()) and "<secret:api_key>" in gtx and SEC["api_key"] not in gtx,
    "결과에 키가 들어감 = 골든 차이 + '등록 비밀값 없음' 실패 · 차이 출력은 <secret:이름>", skg.bad())
XSEC = dict(SEC, q='q"uo\\te-SEC1', h="ab" * 32)
casx = C.Cassette("frame_demo", secrets=XSEC, dirpath=D)
outx, _mx = casx.run(client)
skx = Sink()
casx.golden(skx, {"out": outx, "leak": {"q": XSEC["q"], "hex": "0x" + XSEC["h"], "long": "x" * 149 + SEC["api_key"]}})
gtx = json.dumps(skx.res, ensure_ascii=False)
chk(any("골든 차이" in m for m in skx.bad()) and "<secret:" in gtx and "uo" not in gtx and "«ab*32»" not in gtx and "frameKE" not in gtx,
    "골든 차이 출력 = 직렬화·축약 전에 값 단위로 가림(이스케이프·압축 표기·긴 값 앞부분으로도 안 샘)", skx.bad())


def jwt_pair(fixed=False):
    out9, n9 = [], str(uuid.uuid4())
    for st in ("done", "cancel"):
        q9 = "market=KRW-TEST&state=" + st
        rq9 = urllib.request.Request("https://jwt.frame.invalid/v1/orders?" + q9,
                                     headers={"Authorization": "Bearer " + jwt(SEC["jwt_secret"], q9, n9 if fixed else None)})
        with urllib.request.urlopen(rq9, timeout=5) as r:
            out9.append(json.loads(r.read()))
    return out9


recj = C.Cassette("frame_jwt", secrets=SEC, responder=responder, dirpath=D, record=True)
oj, mj = recj.run(jwt_pair)
recj.golden(Sink(), {"out": oj})
recj.check(Sink())
for fixed9, bad9 in ((False, False), (True, True)):
    casj = C.Cassette("frame_jwt", secrets=SEC, dirpath=D)
    oj9, mj9 = casj.run(jwt_pair, fixed9)
    skj = Sink()
    casj.golden(skj, {"out": oj9})
    casj.check(skj)
    chk(mj9 is None and any("nonce 재사용" in m for m in skj.bad()) == bad9 and any("헤더·인증" in m for m in skj.bad()) == bad9,
        "JWT nonce " + ("재사용 = 실패(가린 nonce 대신 재사용 검사)" if fixed9 else "매번 다름 = 통과"), skj.bad())

print("[f8] 녹화 실패 = 저장 안 함 · tick")
D2 = tempfile.mkdtemp(prefix="tj_casfail_", dir=T.TMP)


def bad_resp(rq):
    raise KeyError("응답기 실수")


recb = C.Cassette("frame_bad", secrets=SEC, responder=bad_resp, dirpath=D2, record=True)
n0 = len(T.NET_TRIES)
outb, missb = recb.run(client)
del T.NET_TRIES[n0:]
skb = Sink()
recb.golden(skb, {"x": 1})
recb.check(skb)
chk(missb and "응답기 오류" in missb and any("녹화 실패" in m for m in skb.bad()) and not os.listdir(D2),
    "응답기 오류 = CassetteMiss(앱이 못 삼킴) · 부분 카세트 저장 안 함", [missb, skb.bad(), os.listdir(D2)])


def one_get():
    with urllib.request.urlopen("https://bin.frame.invalid/x", timeout=5) as r:
        return r.read()


recn = C.Cassette("frame_bin", responder=lambda rq: C.Reply(b"\xff\xfe\x00raw"), dirpath=D2, record=True)
n0 = len(T.NET_TRIES)
_o9, missn = recn.run(one_get)
del T.NET_TRIES[n0:]
skn = Sink()
recn.golden(skn, {"x": 1})
recn.check(skn)
chk(missn and "바이너리" in missn and not os.listdir(D2), "바이너리 응답 = 녹화 거부(base64 로 비밀값 검사·스캔 우회 못 함)", [missn, os.listdir(D2)])
recp = C.Cassette("frame_prior", responder=lambda rq: {"ok": 1}, dirpath=D2, record=True)
_o9, missp = recp.run(one_get)
skp = Sink()
skp.FAILS = ["앞 검사 실패"]
recp.golden(skp, {"x": 1})
recp.check(skp)
chk(missp is None and any("녹화 실패" in m for m in skp.bad()) and not os.listdir(D2), "앞선 검사가 실패한 녹화 = 기준 파일 안 덮어씀", skp.bad())
QSEC = {"q": 'q"uo\\te-SEC1', "h": "ab" * 32}
recq = C.Cassette("frame_leak", secrets=QSEC, responder=lambda rq: {"echo": QSEC["q"], "hex": "0x" + QSEC["h"]}, dirpath=D2, record=True)
_o9, mq = recq.run(one_get)
skq = Sink()
recq.golden(skq, {"x": 1})
recq.check(skq)
chk(mq is None and any("저장 거부" in m for m in skq.bad()) and not os.listdir(D2), "JSON 이스케이프·압축 표기 속 등록 비밀값도 저장 거부", skq.bad())
recq2 = C.Cassette("frame_leak2", secrets=QSEC, responder=lambda rq: json.dumps({"echo": QSEC["q"]}), dirpath=D2, record=True)
_o9, mq2 = recq2.run(one_get)
skq2 = Sink()
recq2.golden(skq2, {"x": 1})
recq2.check(skq2)
chk(mq2 is None and any("저장 거부" in m for m in skq2.bad()) and not os.listdir(D2), "글자로 돌려준 JSON 응답 속 등록 비밀값도 저장 거부", skq2.bad())
if os.path.isfile(os.path.join(T.ROOT, "tools", "package", "pub_scan.py")):
    UKEY = hashlib.sha256(b"unregistered key").hexdigest()[:24] + "ZzYyXxWw"
    recs = C.Cassette("frame_scan", responder=lambda rq: "see https://x.invalid/?api-key=" + UKEY, dirpath=D2, record=True)
    _o9, ms9 = recs.run(one_get)
    sks = Sink()
    recs.golden(sks, {"x": 1})
    recs.check(sks)
    stx = json.dumps(sks.res, ensure_ascii=False)
    chk(any("저장 거부" in m for m in sks.bad()) and "키 박힌 URL" in stx and UKEY[:8] not in stx and not os.listdir(D2),
        "개인정보 스캔에 걸린 녹화 = 저장 거부 · 실패 문구엔 파일:줄·규칙 이름만(검출 조각 안 옮김)", sks.bad())
else:
    chk(not C.REPO_LAYOUT, "개인정보 스캔 녹화 거부 — 공개판 배치(tools/package/pub_scan.py 없음) · 건너뜀")
NK = hashlib.sha256(b"frame nonsynthetic key").hexdigest()


def key_err(rq):
    raise KeyError(QSEC["q"])


rece = C.Cassette("frame_esc", secrets=QSEC, responder=key_err, dirpath=D2, record=True)
n0 = len(T.NET_TRIES)
_o9, me = rece.run(one_get)
tre = T.NET_TRIES[n0:]
del T.NET_TRIES[n0:]
txe = "\n".join([me or ""] + rece.misses + tre)
forms9 = {QSEC["q"], repr(QSEC["q"])[1:-1], json.dumps(QSEC["q"])[1:-1]}
chk(me and "<secret:q>" in me and not any(f in txe for f in forms9), "오류 문구·기록의 이스케이프 꼴(repr·JSON) 등록 비밀값도 <secret:이름>",
    [me, rece.misses])
LSEC = {"long": "frame-secret-prefix-7Kx9" + "\\" * 2 + "tail", "short": "\\tail"}
casl = C.Cassette("frame_order", secrets=LSEC, responder=key_err, dirpath=D2, record=True)
ol9 = casl._sec_out("오류 " + LSEC["long"] + " · " + repr(LSEC["long"]))
chk("frame-secret-prefix" not in ol9 and "tail" not in ol9 and ol9.count("<secret:") == 2, "짧은 값의 이스케이프 꼴이 긴 값 속에 있어도 긴 값 통째로 가림(접두부 안 남음)", ol9)
USEC = {"long": "frameKEY" + "\\" + "uac", "short": "가나다"}
casu = C.Cassette("frame_order2", secrets=USEC, responder=key_err, dirpath=D2, record=True)
ou9 = casu._sec_out("오류 " + json.dumps(USEC["long"] + "00" + "나다")[1:-1] + " · " + USEC["long"] + json.dumps("\uac00나다")[1:-1])
chk("frameKEY" not in ou9 and "uac" not in ou9, "꼴끼리 겹쳐도(구간 합치기) 어느 값의 조각도 안 남음", ou9)
casd = C.Cassette("frame_demo", secrets=dict(SEC, q=QSEC["q"]), dirpath=D)
casd.diffs = [{"key": "GET https://ex.frame.invalid/x", "헤더": {"user-agent": [json.dumps({"q": QSEC["q"]}), "agent " + json.dumps({"q": QSEC["q"]})]}}]
skd = Sink()
casd.check(skd)

def strs(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for k9, v9 in o.items():
            yield from strs(k9)
            yield from strs(v9)
    elif isinstance(o, (list, tuple)):
        for v9 in o:
            yield from strs(v9)


txd = "\n".join(strs(skd.res))
chk(any("헤더·인증 값 그대로" in m for m in skd.bad()) and not any(f in txd for f in (json.dumps(QSEC["q"])[1:-1], QSEC["q"])),
    "헤더·인증 차이 출력도 값 단위 가림(JSON 이스케이프 꼴 비밀값 안 남음)", skd.res)

def post_body():
    rq9 = urllib.request.Request("https://ex.frame.invalid/api/post", data=json.dumps({"pad": "x" * 270, "q": QSEC["q"]}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(rq9, timeout=5) as r:
        return r.read()


casb = C.Cassette("frame_demo", secrets=dict(SEC, q=QSEC["q"]), dirpath=D)
n0 = len(T.NET_TRIES)
_o9, mb = casb.run(post_body)
trb = T.NET_TRIES[n0:]
del T.NET_TRIES[n0:]
txb = "\n".join([mb or ""] + casb.misses + trb)
chk(mb and "카세트에 없는 요청" in mb and "uo" not in txb.replace("<secret:", ""), "없는 요청 본문 = 가린 뒤 자름(300자 경계에 걸린 비밀값 조각 안 남음)", [mb])


def raw_tcp(pad9):
    s9 = socket.create_connection(("probe.frame.invalid", 443), timeout=1)
    s9.sendall(b"X" * pad9 + SEC["api_key"].encode() + b" tail")
    s9.close()
    return "보냄"


casw = C.Cassette("frame_demo", secrets=SEC, dirpath=D)
n0 = len(T.NET_TRIES)
_o9, mw = casw.run(raw_tcp, 80 - 6)
trw = T.NET_TRIES[n0:]
del T.NET_TRIES[n0:]
txw = "\n".join([mw or ""] + casw.misses + trw)
chk(mw and "요청 머리가 끝나지 않음" in mw and "X" * 20 in mw and SEC["api_key"][:6] not in txw,
    "HTTP 아닌 전송 문구 = 보낸 바이트를 가린 뒤 80자 자름(경계에 걸린 비밀값 앞부분 안 남음)", [mw])
QREP = repr(QSEC["q"])[1:-1]
KPRE = "GET https://ex.frame.invalid/"


def rep_path(pad9):
    c = http.client.HTTPSConnection("ex.frame.invalid", timeout=5)
    c.request("GET", "/" + "-" * pad9 + QREP)
    return c.getresponse().read()


def bad_resp2(rq):
    raise KeyError("응답기 실수")


reck = C.Cassette("frame_kcut", secrets=QSEC, responder=bad_resp2, dirpath=D2, record=True)
n0 = len(T.NET_TRIES)
_o9, mk = reck.run(rep_path, 160 - len(KPRE) - 6)
trk = T.NET_TRIES[n0:]
del T.NET_TRIES[n0:]
txk = "\n".join([mk or ""] + reck.misses + trk)
chk(mk and "응답기 오류" in mk and "-" * 20 in mk and QREP[:4] not in txk and not os.listdir(D2),
    "녹화 응답기 오류 문구 = 요청 키를 가린 뒤 160자 자름(경계에 걸린 비밀값 repr 꼴 앞부분 안 남음)", [mk])
recw = C.Cassette("frame_wcut", secrets=QSEC, responder=lambda rq: {"v": NK}, dirpath=D2, record=True)
_o9, mw2 = recw.run(rep_path, 80 - len(KPRE) - 6)
skw = Sink()
recw.golden(skw, {"x": 1})
recw.check(skw)
txw2 = "\n".join(strs(skw.res))
chk(mw2 is None and any("저장 거부" in m for m in skw.bad()) and "-" * 20 in txw2 and QREP[:4] not in txw2 and not os.listdir(D2),
    "녹화 저장 거부 문구의 위치(응답 + 요청 키) = 가린 뒤 80자 자름(경계에 걸린 비밀값 repr 꼴 앞부분 안 남음)", skw.res)
recv = C.Cassette("frame_frag", secrets={"k": NK}, responder=lambda rq: {"v": NK}, dirpath=D2, record=True)
_o9, mv = recv.run(one_get)
skv = Sink()
recv.golden(skv, {"x": 1})
recv.check(skv)
stv = json.dumps(skv.res, ensure_ascii=False)
chk(mv is None and any("저장 거부" in m for m in skv.bad()) and NK[:6] not in stv and not os.listdir(D2),
    "합성 꼴 아닌 값 = 저장 거부 · 거부 문구엔 값 조각(앞 6자) 안 옮김", skv.bad())
recg = C.Cassette("frame_gleak", secrets={"k": NK}, responder=lambda rq: {"ok": 1}, dirpath=D2, record=True)
_o9, mg = recg.run(one_get)
skg = Sink()
recg.golden(skg, {"leak": NK})
recg.check(skg)
stg = json.dumps(skg.res, ensure_ascii=False)
chk(mg is None and any("녹화 실패" in m for m in skg.bad()) and "등록 비밀값 남음" in stg and NK[:6] not in stg and not os.listdir(D2),
    "녹화: 수집 결과 원본에 등록 비밀값(손실 인코딩이 지문으로 숨기는 꼴) = 저장 안 함", skg.res)
plg = C.Cassette("frame_demo", secrets=dict(SEC, k=NK), dirpath=D)
skp2 = Sink()
plg.golden(skp2, {"out": out_rec, "leak": NK})
chk(not plg.missing and any("등록 비밀값 없음" in m for m in skp2.bad()), "재생: 수집 결과 원본의 등록 비밀값을 인코딩 전에 검사(지문에 숨지 못함)",
    skp2.bad())


def red_resp(rq):
    raise AssertionError("모르는 요청 " + rq.url)


recr = C.Cassette("frame_red", secrets=SEC, responder=red_resp, dirpath=D2, record=True)
n0 = len(T.NET_TRIES)
_o9, mr = recr.run(lambda: bf_engine.rpc_batch("https://rpc.frame.invalid/v2/" + SEC["api_key"], [("eth_blockNumber", [])]))
tr9 = T.NET_TRIES[n0:]
del T.NET_TRIES[n0:]
chk(mr and "<secret:api_key>" in mr and SEC["api_key"] not in mr + json.dumps(recr.misses + tr9, ensure_ascii=False),
    "오류 문구·기록·출력의 등록 비밀값 = <secret:이름>", [mr, recr.misses])
D3 = tempfile.mkdtemp(prefix="tj_caspair_", dir=T.TMP)
for fn9, s9 in (("a.json", "A0"), ("b.json", "B0")):
    with open(os.path.join(D3, fn9), "w", encoding="utf-8") as f9:
        f9.write(s9)
rep0 = os.replace


def flaky(src, dst):
    if src.endswith(".tmp") and dst.endswith("b.json"):
        raise OSError("주입: 둘째 파일 교체 실패")
    return rep0(src, dst)


os.replace = flaky
try:
    C.write_pair(D3, {"a.json": "A1", "b.json": "B1"})
    err9 = None
except OSError as e9:
    err9 = str(e9)
finally:
    os.replace = rep0
got9 = {fn: open(os.path.join(D3, fn), encoding="utf-8").read() for fn in sorted(os.listdir(D3))}
chk(err9 and got9 == {"a.json": "A0", "b.json": "B0"}, "카세트·골든 묶음 교체 — 도중 실패면 둘 다 녹화 전 그대로(.tmp·.bak 안 남음)", [err9, got9])
with open(os.path.join(D3, "b.json.bak"), "w", encoding="utf-8") as f9:
    f9.write("B-old")
try:
    C.write_pair(D3, {"a.json": "A1", "b.json": "B1"})
    err9 = None
except OSError as e9:
    err9 = str(e9)
got9 = {fn: open(os.path.join(D3, fn), encoding="utf-8").read() for fn in sorted(os.listdir(D3))}
chk(err9 and "지난 실행의 백업" in err9 and got9 == {"a.json": "A0", "b.json": "B0", "b.json.bak": "B-old"},
    "지난 실행의 .bak 가 남아 있으면 녹화 시작 안 함(옛 백업을 되살려 짝이 섞이지 않게)", [err9, got9])
rect = C.Cassette("frame_tick", responder=lambda rq: {"t": 1}, dirpath=D2, record=True, tick=0.5)


def two():
    t0 = time.time()
    for p in ("a", "b"):
        with urllib.request.urlopen("https://tick.frame.invalid/" + p, timeout=5) as r:
            r.read()
    return time.time() - t0


t_before = time.time()
dt9, m9 = rect.run(two)
chk(m9 is None and abs(dt9 - 1.0) < 1e-9 and abs(time.time() - t_before - 1.0) < 1e-9,
    "tick = 그 블록 요청마다 고정 시계 전진(앞 블록 요청 수와 무관 · 블록 밖에선 그 자리 고정)", [dt9, time.time() - t_before])

print("[f9] 단계별 예외 · 주소 보존 모드 · 여러 주소 dns · 조회 횟수 · 리다이렉트 사슬 · 본문 덧붙임 · 진짜 루프백 모드")
D9 = tempfile.mkdtemp(prefix="tj_casnet_", dir=T.TMP)
DNS9 = {"multi.frame.invalid": ["2606:4700:4700::1111", "9.9.9.10"],
        "flip.frame.invalid": {"seq": [["9.9.9.11"], ["10.255.0.9"]]},
        "gone.frame.invalid": {"seq": [[]]},
        "pind.frame.invalid": ["9.9.9.12"], "pinx.frame.invalid": ["9.9.9.13"]}
EV9 = {"2606:4700:4700::1111:80": ["refused"], "down.frame.invalid:80": ["refused", "refused"], "slowc.frame.invalid:80": ["timeout"],
       "again.frame.invalid:80": ["refused", "ok"], "pinx.frame.invalid:443": ["refused"]}


def kind9(e):
    if isinstance(e, urllib.error.URLError) and not isinstance(e, urllib.error.HTTPError):
        return "URLError(" + kind9(e.reason) + ")"
    if isinstance(e, urllib.error.HTTPError):
        return "HTTPError %d" % e.code
    for t9, nm9 in ((socket.gaierror, "gaierror"), (socket.timeout, "timeout"), (http.client.RemoteDisconnected, "RemoteDisconnected"),
                    (ConnectionRefusedError, "ConnectionRefusedError"), (ConnectionResetError, "ConnectionResetError")):
        if type(e) is t9:
            return nm9
    return "기타 " + type(e).__name__


def get9(url, data=None):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers={"User-Agent": "frame-ua/1"}), timeout=5) as r:
            b9 = r.read()
            return {"ok": r.status, "url": r.geturl(), "n": len(b9), "j": json.loads(b9)}
    except Exception as e:   # noqa: BLE001
        return {"exc": kind9(e)}


def net_client():
    out = {"multi": get9("http://multi.frame.invalid/a"), "refused": get9("http://down.frame.invalid/x"),
           "conn_timeout": get9("http://slowc.frame.invalid/x"), "again1": get9("http://again.frame.invalid/x"),
           "again2": get9("http://again.frame.invalid/x"), "read_timeout": get9("http://plain.frame.invalid/slow"),
           "reset": get9("http://plain.frame.invalid/reset"), "eof": get9("http://plain.frame.invalid/eof"),
           "chain": get9("http://plain.frame.invalid/r1"), "post302": get9("http://plain.frame.invalid/p1", data=b'{"q":1}'),
           "decimal": get9("http://2130706433:8080/d"), "flip1": get9("http://flip.frame.invalid/f"),
           "flip2": get9("http://flip.frame.invalid/f"), "ua": json.loads(urllib.request.urlopen("http://plain.frame.invalid/ua", timeout=5).read()), "gone": get9("http://gone.frame.invalid/g"), "pad": get9("http://plain.frame.invalid/pad")}
    for k9, u9 in (("pin_fake", "https://pin9.frame.invalid/p"), ("pin_dns", "https://pind.frame.invalid/p"), ("pin_refused", "https://pinx.frame.invalid/p")):
        try:
            with SAFE.open(urllib.request.Request(u9, headers={"User-Agent": "frame-ua/1"}), timeout=5) as r9:
                out[k9] = json.loads(r9.read())
        except Exception as e:   # noqa: BLE001
            out[k9] = {"exc": kind9(e)}
    return out


def net_resp(rq):
    p = rq.path
    if p == "/slow":
        return C.Reply(exc="timeout")
    if p == "/reset":
        return C.Reply(exc="reset")
    if p == "/eof":
        return C.Reply(exc="eof")
    if p == "/r1":
        return C.Reply("", status=302, headers={"Location": "http://127.0.0.1:8545/r2"})
    if p == "/r2":
        return C.Reply("", status=301, headers={"Location": "http://[::1]:9000/r3"})
    if p == "/p1":
        return C.Reply("", status=302, headers={"Location": "/p2"})
    if p == "/pad":
        return C.Reply({"a": 1}, pad=10)
    return {"host": rq.host, "path": p, "method": rq.method}


rec9 = C.Cassette("frame_net", responder=net_resp, dirpath=D9, record=True, dns=DNS9, conn_events=EV9, preserve=True)
o9, m9 = rec9.run(net_client)
chk(m9 is None and not rec9.misses, "녹화: 계획된 예외는 CassetteMiss 아님(앱까지 실제 종류로)", [m9, rec9.misses])
sk9 = Sink()
rec9.golden(sk9, o9)
rec9.check(sk9)
want9 = {"multi": "ok", "refused": "URLError(ConnectionRefusedError)", "conn_timeout": "URLError(timeout)", "again1": "URLError(ConnectionRefusedError)",
         "again2": "ok", "read_timeout": "timeout", "reset": "ConnectionResetError", "eof": "RemoteDisconnected", "gone": "URLError(gaierror)"}
got9 = {k: ("ok" if "ok" in o9[k] else o9[k]["exc"]) for k in want9}
chk(got9 == want9, "연결 단계(거부·시간 초과 · 다음 시도 성공) · 읽기 단계(시간 초과·끊김·헤더 전 EOF) · 이름 풀이 실패 = 실제 예외 종류", got9)
chk(o9["chain"].get("url") == "http://[::1]:9000/r3" and o9["chain"]["j"] == {"host": "::1", "path": "/r3", "method": "GET"},
    "리다이렉트 사슬 302 → IP 문자 127.0.0.1 → 301 → [::1] 그대로 따라감(가짜 주소로 안 바뀜)", o9["chain"])
chk(o9["post302"].get("j", {}).get("method") == "GET" and o9["post302"]["j"]["path"] == "/p2", "POST 302 → GET 다음 요청", o9["post302"])
chk(o9["decimal"].get("url") == "http://2130706433:8080/d" and o9["decimal"]["j"]["host"] == "127.0.0.1", "10진 표기 IP = 숫자 조회(127.0.0.1 로 연결)", o9["decimal"])
chk(o9["pad"].get("n") == len('{"a":1}') + 10 and o9["pad"]["j"] == {"a": 1}, "응답 칸 pad = 본문 앞 공백 바이트(JSON 그대로)", o9["pad"])
doc9 = json.load(open(os.path.join(D9, "frame_net.json"), encoding="utf-8"))
keys9 = [e["key"] for e in doc9["interactions"]]
chk("GET http://127.0.0.1:8545/r2" in keys9 and "GET http://[::1]:9000/r3" in keys9 and "GET http://127.0.0.1:8080/d" in keys9
    and "GET http://multi.frame.invalid/a" in keys9, "요청 키 원점 = 보존한 IP 문자 · 이름(여러 주소)", keys9)
chk(all(e["resp"].get("exc") for e in doc9["interactions"] if e["key"].endswith(("/slow", "/reset", "/eof"))) and doc9["addr_mode"] == "preserve"
    and doc9["dns"] == DNS9 and doc9["conn_events"] == EV9, "파일 = exc 칸 · 주소 모드 · dns · 연결 사건(시험 정의 그대로)", doc9.get("addr_mode"))
chk(rec9.conn_log[:2] == [["multi.frame.invalid:80", "refused", "2606:4700:4700::1111"], ["multi.frame.invalid:80", "ok", "9.9.9.10"]],
    "여러 주소 = 표준 순서(첫 주소 거부 → 둘째 연결) · 상대 주소 기록", rec9.conn_log[:3])
fl9 = [p9 for k9, ev9, p9 in rec9.conn_log if k9 == "flip.frame.invalid:80"]
chk(fl9 == ["9.9.9.11", "10.255.0.9"] and rec9.lookups["name"].get("flip.frame.invalid") == 2,
    "dns seq = 조회마다 다른 답(첫째 공인 · 둘째 사설) · 이름 조회 2번", [fl9, rec9.lookups["name"]])
chk(rec9.lookups["name"].get("multi.frame.invalid") == 1 and rec9.lookups["numeric"].get("127.0.0.1", 0) >= 2
    and rec9.lookups["numeric"].get("::1") == 1 and "127.0.0.1" not in rec9.lookups["name"],
    "조회 기록 = 이름 조회와 숫자 IP 조회를 나눠 셈", rec9.lookups)
chk("GET https://pin9.frame.invalid/p" in keys9 and "GET https://pind.frame.invalid/p" in keys9
    and ["pind.frame.invalid:443", "ok", "9.9.9.12"] in rec9.conn_log and o9["pin_dns"]["host"] == "pind.frame.invalid",
    "IP 로 고정해 잇는 opener = 키 원점·연결 기록이 이름 그대로(가짜 주소 역조회 · dns 표 역조회)", [k for k in keys9 if "pin" in k])
chk(o9["pin_refused"] == {"exc": "URLError(ConnectionRefusedError)"} and ["pinx.frame.invalid:443", "refused", "9.9.9.13"] in rec9.conn_log,
    "IP 로 고정해 잇는 opener 도 이름에 건 연결 사건(거부)을 소비", [o9["pin_refused"], rec9.conn_log[-3:]])
ua9 = [e["hdr"].get("user-agent") for e in doc9["interactions"] if e["key"].endswith("/ua")]
chk(ua9 == ["Python-urllib/<판>"], "urllib 기본 UA 의 파이썬 판은 가림(맥·서버 같은 녹화본) · UA 자체는 비교", ua9)
txt9 = open(os.path.join(D, "frame_demo.json"), encoding="utf-8").read()
chk(not any(k in json.loads(txt9) for k in ("addr_mode", "dns", "conn_events", "conn_log")), "선택 칸을 안 쓴 카세트 = 파일 꼴 그대로(새 칸 0)")


def replay9(var=None, **kw):
    n0 = len(T.NET_TRIES)
    cas = C.Cassette("frame_net", dirpath=D9, **kw)
    out, miss = cas.run(var or net_client)
    sk = Sink()
    if miss is None:
        cas.golden(sk, out)
    cas.check(sk)
    del T.NET_TRIES[n0:]
    return out, miss, sk, cas


o9b, m9b, sk9b, c9b = replay9(dns=DNS9, conn_events=EV9, preserve=True)
chk(m9b is None and o9b == o9 and not sk9b.bad() and c9b.conn_log == rec9.conn_log, "재생: 같은 결과 · 연결 시도 기록 같음 · 판정 전부 통과", [m9b, sk9b.bad()])
_o, _m, sk9p, _c = replay9(dns=DNS9, conn_events=EV9, preserve=False)
chk(any("시험 정의와 파일이 같음" in m for m in sk9p.bad()), "preserve=False 를 명시했는데 파일은 주소 보존 모드 = 실패", sk9p.bad())
_o, _m, sk9c, _c = replay9(conn_events=dict(EV9, **{"down.frame.invalid:80": ["ok"]}))
chk(any("시험 정의와 파일이 같음" in m for m in sk9c.bad()), "시험 정의(연결 사건)가 파일과 다름 = 실패(다시 녹화 없이 바꾼 정의를 못 숨김)", sk9c.bad())


n0 = len(T.NET_TRIES)
c9e = C.Cassette("frame_demo", secrets=SEC, dirpath=D, preserve=True)
_o, m9e = c9e.run(client)
sk9e = Sink()
c9e.check(sk9e)
del T.NET_TRIES[n0:]
chk(m9e is None and not c9e.preserve and "[frame_demo] 주소 모드·dns·연결 사건 = 시험 정의와 파일이 같음" in sk9e.bad(),
    "선택 칸 없는 파일에 시험이 주소 보존 모드를 넘김 = 재생은 파일대로(꺼짐) + 정의 다름 실패", [m9e, sk9e.bad()])


def extra_try():
    out = net_client()
    get9("http://down.frame.invalid/x")
    return out


_o, m9d, sk9d, _c = replay9(var=extra_try)
chk(m9d is None and sk9d.bad() == ["[frame_net] 연결 시도 기록(주소·결과·순서) = 녹화와 같음"], "요청 없이 연결 시도만 늘어도 실패(연결 시도 수 = 녹화와 비교)",
    [m9d, sk9d.bad()])


class _Loop(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/go":
            self.send_response(302)
            self.send_header("Location", "/here")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        b9 = json.dumps({"path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(b9)))
        self.end_headers()
        self.wfile.write(b9)

    def log_message(self, *a):
        pass


LS9 = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Loop)
LT9 = threading.Thread(target=LS9.serve_forever, daemon=True)
LT9.start()
try:
    n0 = len(T.NET_TRIES)
    with C.real_loopback():
        with urllib.request.urlopen("http://127.0.0.1:%d/go" % LS9.server_address[1], timeout=5) as r9:
            lj9 = json.loads(r9.read())
        try:
            urllib.request.urlopen("http://outside.frame.invalid/x", timeout=1)
            out9 = "열림"
        except OSError as e9:
            out9 = kind9(e9)
    tries9 = T.NET_TRIES[n0:]
    del T.NET_TRIES[n0:]
    chk(lj9 == {"path": "/here"} and out9 == "URLError(gaierror)",
        "진짜 루프백 모드: 루프백 서버까지 진짜 연결(302 따라감) · 바깥 이름 = 하네스 차단", [lj9, out9])
    chk(tries9 == ["outside.frame.invalid"], "진짜 루프백 모드의 바깥 시도 = 하네스 기록에 남음", tries9)
finally:
    LS9.shutdown()
    LS9.server_close()
chk(urllib.request.urlopen is T._guard_urlopen, "진짜 루프백 모드 끝 = urlopen 차단기 원래대로")
shutil.rmtree(D9, ignore_errors=True)

print("[f7] 재생 끝 = 원래대로")
chk(urllib.request.urlopen is T._guard_urlopen and socket.create_connection.__module__ == "socket", "urlopen 차단기·소켓 연결 원래대로",
    [getattr(urllib.request.urlopen, "__qualname__", "?"), socket.create_connection.__module__])
try:
    urllib.request.urlopen("https://ex.frame.invalid/after", timeout=1)
    blocked = False
except OSError:
    blocked = True
chk(blocked and T.NET_TRIES, "재생 밖 바깥 요청 = 하네스가 다시 막고 기록")
del T.NET_TRIES[:]
shutil.rmtree(D, ignore_errors=True)
T.finish()
