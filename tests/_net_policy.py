import http.client
import json
import socket
import urllib.error
import urllib.request

AKEY = "casPOLICYexkey0001"
CGKEY = "casPOLICYcgkey0001"
SECRETS = {"policy_exkey": AKEY, "policy_cgkey": CGKEY}
UA = "tj-policy-test/1"
BODY = b'{"q":1}'
ENTRIES = ("rabby", "depaddr", "bfe", "bfe_key", "sol_open", "onboarding")
POST_OK = ("bfe", "bfe_key", "sol_open", "onboarding")


def configure():
    import bf_engine
    wide = {"rate": 5000, "burst": 5000, "conc": 8}
    bf_engine.configure({"backfill": {"hosts": {"*.policy.invalid": wide, "127.0.0.1": wide}}})


def exc_name(e) -> str:
    if isinstance(e, urllib.error.HTTPError):
        return "HTTPError"
    if isinstance(e, urllib.error.URLError):
        return "URLError(%s)" % (exc_name(e.reason) if isinstance(e.reason, BaseException) else type(e.reason).__name__)
    for t9, nm9 in ((socket.gaierror, "gaierror"), (socket.timeout, "timeout"), (http.client.RemoteDisconnected, "RemoteDisconnected"),
                    (ConnectionRefusedError, "ConnectionRefusedError"), (ConnectionResetError, "ConnectionResetError")):
        if type(e) is t9:
            return nm9
    return type(e).__name__


def _plain(o):
    return json.loads(json.dumps(o, ensure_ascii=False, default=str))


def summary(fn, *a, **k) -> dict:
    try:
        return {"ret": _plain(fn(*a, **k))}
    except Exception as e:   # noqa: BLE001
        out = {"exc": exc_name(e)}
        for f9 in ("kind", "code", "status"):
            v9 = getattr(e, f9, None)
            if isinstance(v9, (int, str)) and not isinstance(v9, bool):
                out[f9] = v9
        return out


def call(entry: str, url: str, post: bool = False, timeout: float = 7):
    import bf_engine
    import depaddr
    import net_http
    import onboarding
    import rabby
    data = BODY if post else None
    if entry == "rabby":
        return rabby.http_get(url, timeout=timeout)
    if entry == "depaddr":
        return depaddr.http_get(url, {"X-MBX-APIKEY": AKEY}, timeout=timeout, ex="binance")
    if entry == "bfe":
        return bf_engine.http_request(url, data=data, timeout=timeout, retries=3)
    if entry == "bfe_key":
        return bf_engine.http_request(url, data=data, headers={"x-cg-demo-api-key": CGKEY}, timeout=timeout, retries=3)
    if entry == "sol_open":
        req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept": "application/json"})
        with bf_engine.sol_open(req, timeout) as r:
            return {"status": r.status, "url": r.geturl(), "body": json.loads(net_http.read_capped(r))}
    if entry == "onboarding":
        return onboarding._http(url, data=data, method="POST" if post else None, timeout=timeout)
    raise ValueError("모르는 입구 " + entry)
