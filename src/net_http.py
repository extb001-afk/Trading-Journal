import functools
import http.client
import io
import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional, Union

__all__ = ["request", "urlopen", "auth_urlopen", "net_error_text", "HTTP_BODY_MAX", "HTTP_ERR_BODY_MAX", "ResponseTooLarge", "read_capped",
           "BROWSER_UA", "BROWSER_UA_HOSTS", "ua_for"]


def net_error_text(e) -> str:
    import ssl as _ssl
    r = getattr(e, "reason", None) if isinstance(e, urllib.error.URLError) else None
    x = r if isinstance(r, BaseException) else e
    if isinstance(e, urllib.error.HTTPError):
        return f"상대 서버가 거부했어요(HTTP {e.code}) — 키·권한·IP 허용 목록을 확인하세요"
    if isinstance(x, (socket.timeout, TimeoutError)) or "timed out" in str(x).lower():
        return "응답이 없어요(시간 초과) — 인터넷 연결·방화벽을 확인하고 잠시 뒤 다시 시도하세요"
    if isinstance(x, socket.gaierror):
        return "주소를 찾지 못했어요(DNS) — 인터넷 연결을 확인하세요"
    if isinstance(x, _ssl.SSLError) or "certificate" in str(x).lower():
        return "보안 연결(SSL)에 실패했어요 — 컴퓨터 시계가 맞는지, 회사·학교 프록시가 끼어 있지 않은지 확인하세요"
    if isinstance(x, ConnectionRefusedError):
        return "연결이 거부됐어요 — 방화벽·프록시 설정을 확인하세요"
    if isinstance(x, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
        return "연결이 중간에 끊겼어요 — 잠시 뒤 다시 시도하세요"
    if isinstance(x, OSError):
        return "네트워크 오류로 연결하지 못했어요 — 인터넷 연결을 확인하세요"
    return "연결하지 못했어요 — 잠시 뒤 다시 시도하고, 계속되면 tj-web 로그를 확인하세요"


HTTP_BODY_MAX = 32 * 1024 * 1024
HTTP_ERR_BODY_MAX = 64 * 1024


class ResponseTooLarge(ValueError):
    pass


def read_capped(r, cap: int = None) -> bytes:
    cap = HTTP_BODY_MAX if cap is None else max(0, int(cap))
    n9 = cap + 1
    ln9 = getattr(r, "length", None)
    if isinstance(ln9, int) and not isinstance(ln9, bool) and ln9 >= 0:
        if ln9 > cap:
            raise ResponseTooLarge(f"응답 본문 {ln9:,}바이트가 상한 {cap:,}바이트를 넘음 — 이 요청 실패")
        n9 = ln9 + 1
    raw = r.read(n9) or b""
    if len(raw) > cap:
        raise ResponseTooLarge(f"응답 본문이 상한 {cap:,}바이트를 넘음 — 이 요청 실패")
    return raw


_SCHEMES = ("http", "https")
_DENY = "redirect target not allowed"
_NAT64 = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))


class _Denied(OSError):
    pass


def _public_ip(text: str) -> bool:
    try:
        a = ipaddress.ip_address(str(text).split("%", 1)[0])
    except ValueError:
        return False
    inner = [a]
    if a.version == 6:
        if a.ipv4_mapped is not None:
            inner = [a.ipv4_mapped]
        elif a.sixtofour is not None:
            inner = [a.sixtofour]
        elif a.teredo is not None:
            inner = list(a.teredo)
    for x in inner:
        if (not x.is_global or x.is_private or x.is_loopback or x.is_link_local or x.is_multicast or x.is_reserved or x.is_unspecified
                or (x.version == 6 and x.is_site_local)):
            return False
    return True


def _scheme_check(req: Union[urllib.request.Request, str]) -> None:
    if isinstance(req, str):
        try:
            req = urllib.request.Request(req)
        except ValueError:
            return
    sch = str(getattr(req, "type", "") or "")
    if sch and sch.lower() not in _SCHEMES:
        raise urllib.error.URLError("url scheme not allowed")


def _via_proxy(req: urllib.request.Request, tunnel_host: Optional[str]) -> bool:
    return tunnel_host is not None or bool(req is not None and req.has_proxy())


def _origin_public(req: urllib.request.Request) -> bool:
    o = getattr(req, "tj_origin", None)
    if o is not None:
        return bool(o)
    peer = getattr(req, "tj_conn", None)
    if peer is None:
        return True
    try:
        a = ipaddress.ip_address(str(peer[0]).split("%", 1)[0])
    except ValueError:
        return True
    if any(a in n for n in _NAT64):
        return True
    return _public_ip(str(a))


def _pinned_connect(infos: list, port: int, timeout: object, source_address: Optional[tuple], url: str,
                    connect: Callable[..., socket.socket]) -> socket.socket:
    ips = [ai[4][0] for ai in infos]
    if not ips:
        raise OSError("getaddrinfo returns an empty list")
    if not all(_public_ip(ip) for ip in ips):
        raise _Denied(url)
    err = None
    for ip in ips:
        try:
            return connect((ip, port), timeout, source_address)
        except OSError as e:
            err = e
    raise err


class _PinConn:

    def __init__(self, *a, tj_req: urllib.request.Request = None, **k):
        super().__init__(*a, **k)
        self.tj_req = tj_req
        self._create_connection = self._connect

    def _connect(self, address: tuple, timeout: object, source_address: Optional[tuple]) -> socket.socket:
        req = self.tj_req
        proxied = _via_proxy(req, self._tunnel_host)
        if getattr(req, "tj_origin", None) is True and not proxied:
            infos = socket.getaddrinfo(address[0], address[1], 0, socket.SOCK_STREAM)
            sock = _pinned_connect(infos, address[1], timeout, source_address, req.full_url, socket.create_connection)
        else:
            sock = socket.create_connection(address, timeout, source_address)
        peer = None
        if not proxied:
            try:
                peer = sock.getpeername()
            except OSError:
                peer = None
        if req is not None:
            req.tj_conn = peer
        return sock


class _PinHTTP(_PinConn, http.client.HTTPConnection):
    pass


class _PinHTTPS(_PinConn, http.client.HTTPSConnection):
    pass


class _PinHTTPHandler(urllib.request.HTTPHandler):

    def do_open(self, http_class, req, **http_conn_args):
        return super().do_open(functools.partial(_PinHTTP, tj_req=req), req, **http_conn_args)


class _PinHTTPSHandler(urllib.request.HTTPSHandler):

    def do_open(self, http_class, req, **http_conn_args):
        return super().do_open(functools.partial(_PinHTTPS, tj_req=req), req, **http_conn_args)


class _PolicyFTPHandler(urllib.request.FTPHandler):

    def ftp_open(self, req):
        if getattr(req, "tj_origin", None) is not None and not _via_proxy(req, None):
            raise urllib.error.URLError(_Denied(req.full_url))
        return super().ftp_open(req)


class _PolicyRedirect(urllib.request.HTTPRedirectHandler):

    def __init__(self, auth: bool):
        super().__init__()
        self.auth = bool(auth)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if self.auth:
            return None
        try:
            sch = urllib.request.Request(newurl).type
        except ValueError:
            sch = ""
        if sch not in _SCHEMES + ("ftp",):
            raise urllib.error.HTTPError(newurl, code, _DENY, headers, fp)
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.tj_origin = _origin_public(req)
        return new

    def http_error_302(self, req, fp, code, msg, headers):
        try:
            return super().http_error_302(req, fp, code, msg, headers)
        except urllib.error.URLError as e:
            if isinstance(e.reason, _Denied):
                raise urllib.error.HTTPError(str(e.reason.args[0]), code, _DENY, headers, io.BytesIO(b"")) from None
            raise

    http_error_301 = http_error_303 = http_error_307 = http_error_302
    if hasattr(urllib.request.HTTPRedirectHandler, "http_error_308"):
        http_error_308 = http_error_302


_OPENERS = {}


def _opener(auth: bool) -> urllib.request.OpenerDirector:
    o = _OPENERS.get(bool(auth))
    if o is None:
        hs = (_PolicyRedirect(True),) if auth else (_PolicyRedirect(False), _PinHTTPHandler(), _PinHTTPSHandler(), _PolicyFTPHandler())
        o = _OPENERS.setdefault(bool(auth), urllib.request.build_opener(*hs))
    return o


def request(url: str, data: Optional[bytes] = None, headers: Optional[dict] = None,
            method: Optional[str] = None) -> urllib.request.Request:
    return urllib.request.Request(url, data=data, headers={} if headers is None else headers, method=method)


def urlopen(req: Union[urllib.request.Request, str], timeout: float):
    return _send(req, timeout, False)


def auth_urlopen(req, timeout=20):
    return _send(req, timeout, True)


def _send(req, timeout, auth: bool):
    _scheme_check(req)
    if getattr(urllib.request.urlopen, "__module__", None) != "urllib.request":
        return urllib.request.urlopen(req, timeout=timeout)
    return _opener(auth).open(req, timeout=timeout)


BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"
              " Chrome/128.0.0.0 Safari/537.36")
BROWSER_UA_HOSTS = set()


def ua_for(url: str, default: str) -> str:
    try:
        host = urllib.parse.urlsplit(url).hostname or ""
    except Exception:  # noqa: BLE001 [fallback]
        host = ""
    return BROWSER_UA if host and host.lower() in BROWSER_UA_HOSTS else default
