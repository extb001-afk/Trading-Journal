from __future__ import annotations

import errno
import http.client
import io
import ipaddress
import json
import socket
import ssl
import urllib.parse
import urllib.request as _ur


class CassetteMiss(BaseException):
    pass


class StopCycle(BaseException):
    pass


EXC_KINDS = ("timeout", "reset", "eof")
CONN_KINDS = ("ok", "refused", "timeout")


def planned(e: BaseException) -> BaseException:
    e._tj_planned = True
    return e


def _conn_exc(kind: str) -> OSError:
    if kind == "refused":
        return planned(ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused"))
    return planned(socket.timeout("timed out"))


def _read_exc(kind: str):
    if kind == "timeout":
        return planned(socket.timeout("timed out"))
    if kind == "reset":
        return planned(ConnectionResetError(errno.ECONNRESET, "Connection reset by peer"))
    return None


class _ExcReply(bytes):
    exc = None


def fake_ip(dns: dict, host: str) -> str:
    host = str(host).lower()
    for ip, h in dns.items():
        if h == host:
            return ip
    if len(dns) >= 254:
        raise CassetteMiss("카세트: 이름 조회 254개 넘음")
    ip = "1.1.1.%d" % (len(dns) + 1)
    dns[ip] = host
    return ip


class Request:

    def __init__(self, method: str, url: str, headers: list, body: bytes):
        self.method, self.url, self.body = method, url, body or b""
        self.headers = {k.lower(): v for k, v in headers}
        sp = urllib.parse.urlsplit(url)
        self.host, self.path = (sp.hostname or "").lower(), sp.path
        self.query = dict(urllib.parse.parse_qsl(sp.query, keep_blank_values=True))

    def json(self):
        try:
            return json.loads(self.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    def form(self) -> dict:
        return dict(urllib.parse.parse_qsl(self.body.decode("utf-8", "replace"), keep_blank_values=True))


class Reply:

    def __init__(self, body=None, status: int = 200, headers=None, exc: str = None, pad: int = 0):
        self.body, self.status = body, int(status)
        self.headers = list((headers or {}).items()) if isinstance(headers, dict) else list(headers or [])
        self.exc, self.pad = exc, int(pad or 0)


def as_reply(r) -> Reply:
    if isinstance(r, Reply):
        return r
    if isinstance(r, tuple) and len(r) == 2 and isinstance(r[0], int):
        return Reply(r[1], status=r[0])
    return Reply(r)


def resp_store(rep: Reply) -> dict:
    b = rep.body
    exc = getattr(rep, "exc", None)
    if exc:
        if exc not in EXC_KINDS:
            raise ValueError(f"카세트: 응답 exc 는 {EXC_KINDS} 중 하나")
        return {"exc": exc}
    out = {"status": rep.status, "headers": [[str(k), str(v)] for k, v in rep.headers]}
    if getattr(rep, "pad", 0):
        out["pad"] = int(rep.pad)
    if isinstance(b, (dict, list)) or b is None or isinstance(b, (int, float, bool)):
        out["json"] = json.loads(json.dumps(b, ensure_ascii=False))
        if not any(k.lower() == "content-type" for k, _v in rep.headers):
            out["headers"].append(["Content-Type", "application/json"])
    elif isinstance(b, str):
        out["text"] = b
    else:
        try:
            out["text"] = bytes(b).decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("카세트: 바이너리 응답은 담지 않음(텍스트·JSON 만)") from None
    return out


def _resp_body(r: dict) -> bytes:
    pad = b" " * int(r.get("pad") or 0)
    if "json" in r:
        return pad + json.dumps(r["json"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if "text" in r:
        return pad + r["text"].encode("utf-8")
    return pad


def resp_raw(r: dict) -> bytes:
    if r.get("exc"):
        b9 = _ExcReply(b"")
        b9.exc = r["exc"]
        return b9
    body = _resp_body(r)
    st = int(r.get("status") or 200)
    lines = ["HTTP/1.1 %d %s" % (st, http.client.responses.get(st, "Status"))]
    lines += ["%s: %s" % (k, v) for k, v in r.get("headers") or [] if k.lower() not in ("content-length", "transfer-encoding", "connection")]
    lines += ["Content-Length: %d" % len(body), "Connection: close", "", ""]
    return "\r\n".join(lines).encode("iso-8859-1") + body


def _dechunk(b: bytes) -> bytes:
    out, i = bytearray(), 0
    while True:
        j = b.find(b"\r\n", i)
        if j < 0:
            raise CassetteMiss("카세트: 청크 본문이 끝나지 않음(깨진 전송)")
        n = int(b[i:j].split(b";")[0].strip() or b"0", 16)
        if n == 0:
            return bytes(out)
        if len(b) < j + 2 + n + 2 or b[j + 2 + n:j + 4 + n] != b"\r\n":
            raise CassetteMiss("카세트: 청크 크기와 본문이 어긋남(깨진 전송)")
        out += b[j + 2:j + 2 + n]
        i = j + 2 + n + 2


def parse_request(raw: bytes, show=None):
    head, sep, rest = raw.partition(b"\r\n\r\n")
    if not sep:
        txt = raw.decode("iso-8859-1", "replace")
        raise CassetteMiss("카세트: 요청 머리가 끝나지 않음(HTTP 아닌 연결?) — " + (show(txt) if show else txt)[:80])
    lines = head.decode("iso-8859-1").split("\r\n")
    parts = lines[0].split(" ")
    hdrs = []
    for ln in lines[1:]:
        k, _s, v = ln.partition(":")
        hdrs.append((k.strip(), v.strip()))
    low = {}
    for k, v in hdrs:
        if k.lower() in low:
            raise CassetteMiss(f"카세트: 같은 헤더 두 번 {k}(깨진 전송 — 앞 값·뒤 값 중 무엇을 쓸지 서버마다 다름)")
        low[k.lower()] = v
    if "chunked" in low.get("transfer-encoding", "").lower():
        body = _dechunk(rest)
    elif "content-length" in low:
        try:
            cl = int(low["content-length"])
        except ValueError:
            raise CassetteMiss("카세트: Content-Length 가 숫자가 아님(깨진 전송)") from None
        if cl != len(rest):
            raise CassetteMiss(f"카세트: Content-Length {cl} ≠ 실제 본문 {len(rest)}바이트(깨진 전송)")
        body = rest
    elif rest:
        raise CassetteMiss(f"카세트: 길이 표시 없는 본문 {len(rest)}바이트(깨진 전송)")
    else:
        body = b""
    return parts[0], (parts[1] if len(parts) > 1 else "/"), hdrs, body


class _RawResp(io.RawIOBase):

    def __init__(self, data: bytes, sock):
        super().__init__()
        self._b, self._sock = io.BytesIO(data), sock
        self._exc = getattr(data, "exc", None)

    def readable(self):
        return True

    def readinto(self, b):
        if self._exc:
            e9, self._exc = _read_exc(self._exc), None
            if e9 is not None:
                raise e9
        chunk = self._b.read(len(b))
        b[:len(chunk)] = chunk
        return len(chunk)


class FakeSock:

    def __init__(self, cas, addr, timeout, name: str = None, peer=None):
        self._cas, self._addr, self._timeout = cas, addr, timeout
        self._name, self._peer = name, peer
        self._timeout0 = timeout
        self._out, self._tls, self._sni, self._verify = bytearray(), False, None, None
        self._n = 0
        cas._socks.append(self)

    def host(self) -> str:
        if self._name:
            return self._name
        return self._cas._dns.get(str(self._addr[0]), str(self._addr[0])).lower()

    def port(self):
        p = self._addr[1] if len(self._addr) > 1 else (443 if self._tls else 80)
        try:
            return int(p)
        except (TypeError, ValueError):
            return {"https": 443, "http": 80}.get(str(p).lower(), str(p))

    def origin(self) -> str:
        p, dflt = self.port(), 443 if self._tls else 80
        h = self.host()
        h = "[%s]" % h if ":" in h else h
        return ("https" if self._tls else "http") + "://" + (h if p == dflt else "%s:%s" % (h, p))

    def timeout_text(self) -> str:
        t = self._timeout0
        return "기본" if t is socket._GLOBAL_DEFAULT_TIMEOUT else "없음" if t is None else "%g" % float(t)

    def _refuse(self, msg: str):
        raise CassetteMiss(self._cas._note_miss(msg))

    def flush(self):
        if self._out:
            raw, self._out = bytes(self._out), bytearray()
            self._n += 1
            self._cas._serve(raw, self)
        elif self._n == 0:
            self._n = -1
            self._refuse("카세트: HTTP 요청 없는 연결 %s(순수 TCP — 카세트가 못 담음)" % self.origin())

    def recv(self, *a, **k):
        self._refuse("카세트: 가짜 소켓 직접 읽기 %s(HTTP 아닌 전송?)" % self.origin())

    recv_into = recvfrom = recv

    def setsockopt(self, *a):
        pass

    def settimeout(self, t):
        self._timeout = t

    def gettimeout(self):
        return self._timeout

    def setblocking(self, flag):
        pass

    def sendall(self, data):
        self._out += bytes(data)

    def send(self, data):
        self._out += bytes(data)
        return len(data)

    def makefile(self, mode="rb", *a, **k):
        raw, self._out = bytes(self._out), bytearray()
        self._n += 1
        return io.BufferedReader(_RawResp(self._cas._serve(raw, self), self))

    def getpeername(self):
        if self._peer is not None:
            return self._peer
        p = self.port()
        return (fake_ip(self._cas._dns, self.host()), p if isinstance(p, int) else 0)

    def getsockname(self):
        return ("127.0.0.1", 40000)

    def shutdown(self, how):
        pass

    def close(self):
        self.flush()

    def fileno(self):
        return -1


def _stdlib_urlopen(url, data=None, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, *, context=None, **_k):
    if context is not None:
        return _ur.build_opener(_ur.HTTPSHandler(context=context)).open(url, data, timeout)
    if _ur._opener is None:
        _ur._opener = _ur.build_opener()
    return _ur._opener.open(url, data, timeout)


_stdlib_urlopen._tj_test_mock = True
_stdlib_urlopen.__module__ = "urllib.request"


def _numeric(h: str):
    h = h[1:-1] if h.startswith("[") and h.endswith("]") else h
    try:
        a = ipaddress.ip_address(h.split("%", 1)[0])
        return (socket.AF_INET6 if a.version == 6 else socket.AF_INET), str(a) if a.version == 4 else h.split("%", 1)[0].lower()
    except ValueError:
        pass
    if h and all(c in "0123456789abcdefxABCDEFX." for c in h) and h[:1].isdigit():
        try:
            return socket.AF_INET, socket.inet_ntoa(socket.inet_aton(h))
        except OSError:
            return None
    return None


def _sa(af: int, ip: str, port: int):
    return (ip, port, 0, 0) if af == socket.AF_INET6 else (ip, port)


def _resolve(cas, host: str, port, family: int = 0) -> list:
    try:
        p = int(port or 0)
    except (TypeError, ValueError):
        p = {"https": 443, "http": 80}.get(str(port).lower(), 443)
    lk = cas.lookups
    num = _numeric(host)
    if num is not None:
        lk["numeric"][num[1]] = lk["numeric"].get(num[1], 0) + 1
        addrs = [num]
    else:
        name = host.lower()
        n9 = lk["name"].get(name, 0)
        lk["name"][name] = n9 + 1
        tbl = (cas.dns or {}).get(name)
        if tbl is None:
            addrs = [(socket.AF_INET, fake_ip(cas._dns, name))]
        else:
            if isinstance(tbl, dict):
                seq = tbl.get("seq") or [[]]
                tbl = seq[min(n9, len(seq) - 1)]
            addrs = []
            for a9 in tbl:
                nm9 = _numeric(str(a9))
                if nm9 is None:
                    raise CassetteMiss(f"카세트 dns: {name} 의 주소 {a9!r} 가 IP 가 아님")
                addrs.append(nm9)
                cas._rdns[nm9[1]] = name
    out = [(af, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", _sa(af, ip, p)) for af, ip in addrs if family in (0, socket.AF_UNSPEC, af)]
    if not out:
        raise planned(socket.gaierror(socket.EAI_NONAME, "nodename nor servname provided, or not known"))
    return out


def _conn_take(cas, keys: list, peer, label: str = None) -> str:
    ev, plan = "ok", getattr(cas, "conn_events", None) or {}
    at = cas._conn_at
    for k in keys:
        q = plan.get(k)
        if q is not None and at.get(k, 0) < len(q):
            ev = q[at.get(k, 0)]
            at[k] = at.get(k, 0) + 1
            break
    if ev not in CONN_KINDS:
        raise CassetteMiss(f"카세트 conn_events: 모르는 사건 {ev!r}({CONN_KINDS} 중 하나)")
    if plan or getattr(cas, "preserve", False):
        cas.conn_log.append([label or keys[0], ev, peer[0] if peer else None])
    return ev


class Transport:

    def __init__(self, cas, real: bool = False):
        self.cas, self.saved, self.real = cas, None, bool(real)

    def install(self):
        self.saved = (socket.create_connection, ssl.SSLContext.wrap_socket, socket.getaddrinfo, socket.gethostbyname,
                      socket.socket.connect, socket.socket.connect_ex, _ur.urlopen, _ur.getproxies)
        ws0, gai0 = self.saved[1], self.saved[2]
        cas = self.cas
        if self.real:
            create_connection, wrap_socket, getaddrinfo, gethostbyname, direct_connect, direct_connect_ex = self.saved[:6]
        else:
            preserve = bool(getattr(cas, "preserve", False))

            def create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, **kw):
                address = tuple(address)
                if not preserve:
                    ev = _conn_take(cas, ["%s:%s" % (str(address[0]).lower(), address[1])], None) if getattr(cas, "conn_events", None) else "ok"
                    if ev != "ok":
                        raise _conn_exc(ev)
                    return FakeSock(cas, address, timeout)
                host, port = str(address[0]), address[1]
                num = _numeric(host)
                err = None
                for af, _st, _pr, _cn, sa in socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM):
                    nm = host.lower() if num is None else (cas._dns.get(sa[0]) or cas._rdns.get(sa[0]) or sa[0])
                    keys9 = list(dict.fromkeys("%s:%s" % (h9, port) for h9 in (sa[0], nm, host.lower())))
                    ev = _conn_take(cas, keys9, sa, "%s:%s" % (nm, port))
                    if ev == "ok":
                        return FakeSock(cas, address, timeout, name=nm, peer=sa)
                    err = _conn_exc(ev)
                raise err if err is not None else OSError("getaddrinfo returns an empty list")

            def wrap_socket(ctx, sock, *a, server_hostname=None, **kw):
                if isinstance(sock, FakeSock):
                    sock._tls, sock._sni = True, server_hostname
                    sock._verify = bool(getattr(ctx, "verify_mode", None) == ssl.CERT_REQUIRED and getattr(ctx, "check_hostname", False))
                    return sock
                return ws0(ctx, sock, *a, server_hostname=server_hostname, **kw)

            def getaddrinfo(host, port, *a, **kw):
                h = host.decode() if isinstance(host, bytes) else host
                if h is None:
                    return gai0(host, port, *a, **kw)
                if preserve:
                    return _resolve(cas, h, port, (a[0] if a else kw.get("family", 0)) or 0)
                try:
                    p = int(port or 0)
                except (TypeError, ValueError):
                    p = 443
                return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (fake_ip(cas._dns, h), p))]

            def gethostbyname(host):
                return _resolve(cas, host, 0, socket.AF_INET)[0][4][0] if preserve else fake_ip(cas._dns, host)

            def direct_connect(sk, addr, *a):
                raise CassetteMiss(cas._note_miss("카세트: 소켓 직접 연결 %r(create_connection·http.client 밖 — 카세트가 못 담음)" % (addr,)))
            direct_connect_ex = direct_connect
        socket.create_connection = create_connection
        ssl.SSLContext.wrap_socket = wrap_socket
        socket.getaddrinfo = getaddrinfo
        socket.gethostbyname = gethostbyname
        socket.socket.connect = direct_connect
        socket.socket.connect_ex = direct_connect_ex
        _ur.urlopen = _stdlib_urlopen
        _ur.getproxies = dict

    def uninstall(self):
        (socket.create_connection, ssl.SSLContext.wrap_socket, socket.getaddrinfo, socket.gethostbyname,
         socket.socket.connect, socket.socket.connect_ex, _ur.urlopen, _ur.getproxies) = self.saved
