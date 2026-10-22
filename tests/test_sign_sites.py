#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _cassette as C  # noqa: E402

C.freeze()
import ast  # noqa: E402
import base64  # noqa: E402
import hashlib  # noqa: E402
import hmac  # noqa: E402
import inspect  # noqa: E402
import itertools  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import urllib.parse  # noqa: E402
import urllib.request  # noqa: E402

NAME = "sign_sites"
GPATH = os.path.join(C.CAS_DIR, NAME + ".golden.json")
RECORD = NAME in C.RECORD
NOW_MS = int(C.NOW * 1000)
DAY = 86400
OFF = {"binance": 1111, "bybit": 2222, "okx": 3333, "kucoin": 4444, "gate": 5555, "bithumb": 6666, "coinbase": 7777}
ENV = {"TJ_BINANCE_KEY": "sgBNkey01", "TJ_BINANCE_SECRET": "sgBNsec01",
       "TJ_BYBIT_KEY": "sgBYkey01", "TJ_BYBIT_SECRET": "sgBYsec01",
       "TJ_OKX_KEY": "sgOKkey01", "TJ_OKX_SECRET": "sgOKsec01", "TJ_OKX_PASSPHRASE": "sgOKpp01",
       "TJ_KUCOIN_KEY": "sgKCkey01", "TJ_KUCOIN_SECRET": "sgKCsec01", "TJ_KUCOIN_PASSPHRASE": "sgKCpp01",
       "TJ_GATE_KEY": "sgGTkey01", "TJ_GATE_SECRET": "sgGTsec01",
       "TJ_BITHUMB_KEY": "sgBHkey01", "TJ_BITHUMB_SECRET": "sgBHsec01",
       "UPBIT_ACCESS": "sgUPkey01", "UPBIT_SECRET": "sgUPsec01"}


def _cb_key_body():
    import ex_sign
    n9 = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551
    d9 = int.from_bytes(hashlib.sha256(b"tj sign sites coinbase synthetic").digest(), "big") % n9
    x9, y9 = ex_sign.ec_p256_pub(d9)

    def tlv(t, b):
        return bytes([t]) + (bytes([len(b)]) if len(b) < 128 else bytes([0x81, len(b)])) + b
    der = tlv(0x30, tlv(0x02, b"\x01") + tlv(0x04, d9.to_bytes(32, "big")) + tlv(0xA0, bytes.fromhex("06082a8648ce3d030107"))
              + tlv(0xA1, tlv(0x03, b"\x00\x04" + x9.to_bytes(32, "big") + y9.to_bytes(32, "big"))))
    return base64.b64encode(der).decode(), (x9, y9)


CB_BODY, CB_PUB = _cb_key_body()
ENV.update({"TJ_COINBASE_KEY_NAME": "sgCBkey01", "TJ_COINBASE_SECRET": CB_BODY})

JWT_SECRET = {ENV["UPBIT_ACCESS"]: ENV["UPBIT_SECRET"], ENV["TJ_BITHUMB_KEY"]: ENV["TJ_BITHUMB_SECRET"]}
BAD_JWT = []
REQ_MISMATCH = []

SITE_MODULES = ("depaddr", "exf_binance", "exf_bithumb", "exf_bybit", "exf_coinbase", "exf_gate", "exf_kucoin", "exf_okx",
                "liq_watch", "onboarding", "pricing", "upbit_link")
NOT_SIGN = {"btc_descriptor:XPub.child_pub", "login_auth:_sess_csrf"}
SIGN_HELPERS = {"ex_sign"}
HASH_ONLY = {"ex_sign.query_hash", "ex_sign.ec_key_body", "ex_sign.ec_p256_scalar"}
TRANSPORT = {"http_json", "_http_json_err", "http_get", "_http", "self.call", "net_http.auth_urlopen",
             "net_http.urlopen", "urllib.request.urlopen", "exf_net.http_json"}

SITE_TABLE = {
    "depaddr:_jwt": {"via": ["http_get"], "caller": ["Client._get"]},
    "depaddr:Client._get": {"via": ["http_get"]},
    "exf_binance:fetch_binance.call": {"via": ["http_json"]},
    "exf_binance:_binance_caller.call": {"via": ["http_json"]},
    "exf_binance:_binance_signed": {"via": ["_http_json_err"]},
    "exf_binance:_bal_binance._futures": {"via": ["_http_json_err"]},
    "exf_binance:_fut_binance.fcall": {"via": ["_http_json_err"]},
    "exf_binance:_bn_deriv_get": {"via": ["_http_json_err"]},
    "exf_bithumb:fetch_bithumb.call": {"via": ["http_json"]},
    "exf_bithumb:_bithumb_caller.call": {"via": ["http_json"]},
    "exf_bithumb:_bithumb_get": {"via": ["http_json"]},
    "exf_bybit:fetch_bybit.call": {"via": ["http_json"]},
    "exf_bybit:fills_bybit.call": {"via": ["http_json"]},
    "exf_bybit:_bybit_get": {"via": ["http_json"]},
    "exf_bybit:_bal_bybit": {"via": ["http_json"]},
    "exf_bybit:_fut_bybit.bcall": {"via": ["http_json"]},
    "exf_coinbase:jwt_for": {"via": ["http_json"], "caller": ["_cb_get"]},
    "exf_gate:fetch_gate.call": {"via": ["http_json"]},
    "exf_gate:fills_gate.call": {"via": ["http_json"]},
    "exf_gate:_gate_get": {"via": ["http_json"]},
    "exf_kucoin:fetch_kucoin.call": {"via": ["http_json"]},
    "exf_kucoin:fills_kucoin.call": {"via": ["http_json"]},
    "exf_kucoin:_kucoin_call": {"via": ["http_json"]},
    "exf_kucoin:_kucoin_get": {"via": ["http_json"]},
    "exf_kucoin:_kucoin_fut_get": {"via": ["http_json"]},
    "exf_okx:fetch_okx.call": {"via": ["http_json"]},
    "exf_okx:fills_okx.call": {"via": ["http_json"]},
    "exf_okx:_okx_get": {"via": ["http_json"]},
    "liq_watch:Watcher.bn_get": {"via": ["self.call"]},
    "liq_watch:Watcher.bybit_get": {"via": ["self.call"]},
    "liq_watch:Watcher.okx_get": {"via": ["self.call"]},
    "onboarding:_jwt_hs256": {"via": ["_http"], "caller": ["_test_group"]},
    "onboarding:_test_group": {"via": ["_http"]},
    "onboarding:_test_group.call": {"via": ["_http"]},
    "onboarding:_test_coinbase.call": {"via": ["_http"]},
    "pricing:okx_headers": {"via": ["net_http.auth_urlopen"], "caller": ["okx_dex_prices"]},
    "upbit_link:_jwt": {"via": ["net_http.auth_urlopen"], "caller": ["Upbit.get"]},
}
EXPECT = {
    "exf_binance:fetch_binance.call": 1, "exf_binance:_binance_caller.call": 1,
    "exf_binance:_binance_signed": 7,
    "exf_binance:_bal_binance._futures": 1, "exf_binance:_fut_binance.fcall": 1, "exf_binance:_bn_deriv_get": 1,
    "exf_bithumb:fetch_bithumb.call": 1, "exf_bithumb:_bithumb_caller.call": 1, "exf_bithumb:_bithumb_get": 1,
    "exf_bybit:fetch_bybit.call": 1, "exf_bybit:fills_bybit.call": 1, "exf_bybit:_bybit_get": 1,
    "exf_bybit:_bal_bybit": 2, "exf_bybit:_fut_bybit.bcall": 1,
    "exf_gate:fetch_gate.call": 1, "exf_gate:fills_gate.call": 1, "exf_gate:_gate_get": 2,
    "exf_kucoin:fetch_kucoin.call": 1, "exf_kucoin:fills_kucoin.call": 1, "exf_kucoin:_kucoin_call": 1,
    "exf_kucoin:_kucoin_get": 1, "exf_kucoin:_kucoin_fut_get": 1,
    "exf_okx:fetch_okx.call": 1, "exf_okx:fills_okx.call": 1, "exf_okx:_okx_get": 1,
    "depaddr:_jwt": 3, "depaddr:Client._get": 5,
    "liq_watch:Watcher.bn_get": 1, "liq_watch:Watcher.bybit_get": 1, "liq_watch:Watcher.okx_get": 1,
    "onboarding:_jwt_hs256": 2, "onboarding:_test_group.call": 6, "onboarding:_test_group": 2,
    "upbit_link:_jwt": 2, "pricing:okx_headers": 1,
    "exf_coinbase:jwt_for": 1, "onboarding:_test_coinbase.call": 2,
}


class _Stop(BaseException):
    pass


PENDING = []
SIGN_LINES = {}
SIGN_CODES = {hmac.new.__code__, hmac.digest.__code__, hmac.HMAC.__init__.__code__}
SRC_DIR = os.path.realpath(T.SRC)
_IDX = {}
_MOD_OF = {}


def _qual_index(mod):
    if mod in _IDX:
        return _IDX[mod]
    out = []

    def rec(node, prefix):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append((ch.lineno, ch.end_lineno, prefix + ch.name))
                rec(ch, prefix + ch.name + ".")
            elif isinstance(ch, ast.ClassDef):
                rec(ch, prefix + ch.name + ".")
            else:
                rec(ch, prefix)
    with open(os.path.join(SRC_DIR, mod + ".py"), encoding="utf-8") as f:
        rec(ast.parse(f.read()), "")
    _IDX[mod] = out
    return out


def _qual_at(mod, line):
    best = None
    for a, b, q in _qual_index(mod):
        if a <= line <= b and (best is None or a >= best[0]):
            best = (a, q)
    return best[1] if best else "<모듈>"


def _mod_of(code):
    p = code.co_filename
    if p not in _MOD_OF:
        rp = os.path.realpath(p)
        _MOD_OF[p] = os.path.splitext(os.path.basename(rp))[0] if os.path.dirname(rp) == SRC_DIR else None
    return _MOD_OF[p]


def _prof(frame, event, arg):
    if event != "call" or frame.f_code not in SIGN_CODES:
        return
    f = frame.f_back
    while f is not None and _mod_of(f.f_code) in SIGN_HELPERS:
        f = f.f_back
    mod = _mod_of(f.f_code) if f is not None else None
    if mod is None:
        return
    SIGN_LINES[(mod, f.f_lineno)] = SIGN_LINES.get((mod, f.f_lineno), 0) + 1
    PENDING.append(f"{mod}:{_qual_at(mod, f.f_lineno)}")


_SIGKEY = re.compile(r"sign|passphrase", re.I)


def _sigfp(v):
    return "sig~" + hashlib.sha256(str(v).encode("utf-8")).hexdigest()[:20]


def _jwt_view(tok):
    parts = tok.split(".")
    if len(parts) != 3:
        return tok

    def d(s):
        return json.loads(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode("utf-8"))
    try:
        hd, cl = d(parts[0]), d(parts[1])
    except ValueError:
        return tok
    sec = JWT_SECRET.get(cl.get("access_key"))
    if hd.get("alg") == "ES256":
        import ex_sign
        good = hd.get("kid") == cl.get("sub") == ENV["TJ_COINBASE_KEY_NAME"] and ex_sign.es256_verify(
            f"{parts[0]}.{parts[1]}".encode(), base64.urlsafe_b64decode(parts[2] + "=" * (-len(parts[2]) % 4)), CB_PUB)
    else:
        good = bool(sec) and hmac.compare_digest(
            base64.urlsafe_b64encode(hmac.new(sec.encode(), f"{parts[0]}.{parts[1]}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode(), parts[2])
    if not good:
        BAD_JWT.append(cl.get("access_key"))
    return {"jwt_header": [[k, v] for k, v in hd.items()], "jwt_claims": [[k, v] for k, v in cl.items()], "jwt_sig": _sigfp(parts[2]),
            "jwt_raw": _sigfp(tok), "jwt_valid": good}


def _hval(hname, v):
    if isinstance(v, str) and hname.lower() == "authorization" and v.startswith("Bearer "):
        return {"bearer": _jwt_view(v[7:])}
    if isinstance(v, str) and _SIGKEY.search(hname) and len(v) >= 32:
        return _sigfp(v)
    return v


def _url(u):
    sp = urllib.parse.urlsplit(u)
    q = urllib.parse.parse_qsl(sp.query, keep_blank_values=True)
    raw = re.sub(r"([?&]signature=)([^&#]*)", lambda m: m.group(1) + _sigfp(urllib.parse.unquote(m.group(2))), u)
    return {"base": f"{sp.scheme}://{sp.netloc}{sp.path}", "q": [[k, _sigfp(v) if k == "signature" else v] for k, v in q], "raw": raw}


def _body(b):
    if b is None:
        return None
    if isinstance(b, (bytes, bytearray)):
        try:
            return {"bytes": bytes(b).decode("utf-8")}
        except UnicodeDecodeError:
            return {"bytes_hex": bytes(b).hex()}
    if isinstance(b, str):
        return {"str": b}
    return {type(b).__name__: repr(b)}


def _norm_call(params):
    out = {}
    for k, v in params.items():
        if isinstance(v, urllib.request.Request):
            sp9 = urllib.parse.urlsplit(v.full_url)
            want9 = (sp9.scheme, sp9.netloc, urllib.parse.urlunsplit(("", "", sp9.path or "/", sp9.query, "")))
            if (v.type, v.host, v.selector) != want9:
                REQ_MISMATCH.append([v.type, v.host, v.selector, *want9])
            hs = dict(v.unredirected_hdrs)
            hs.update({hk: hv for hk, hv in v.headers.items() if hk not in hs})
            out[k] = {"method": v.get_method(), "url": _url(v.full_url),
                      "headers": [[hk, _hval(hk, hv)] for hk, hv in hs.items()], "data": _body(v.data)}
        elif k == "url" and isinstance(v, str):
            out[k] = _url(v)
        elif k in ("headers",) and isinstance(v, dict):
            out[k] = [[hk, _hval(hk, hv)] for hk, hv in v.items()]
        elif k in ("data", "body"):
            out[k] = _body(v)
        else:
            out[k] = v
    return out


CAPS = []
REPLY = [None]
TRAPS = []
TRAP_NAMES = {"exf_net.http_json", "exf_net._http_json_err", "urllib.request.urlopen", "net_http.urlopen"}


def _fake(name, real):
    try:
        sig = inspect.signature(real)
    except (TypeError, ValueError):
        sig = None

    def f(*a, **k):
        try:
            params = dict(sig.bind(*a, **k).arguments) if sig else {"args": list(a), **k}
        except TypeError:
            params = {"args": list(a), **k}
        params.pop("self", None)
        rec = {"via": name, "sites": list(PENDING), **_norm_call(params)}
        PENDING.clear()
        if name in TRAP_NAMES:
            TRAPS.append(name)
        CAPS.append(rec)
        r = REPLY[0]
        if r is None:
            raise _Stop()
        return r(rec, len(CAPS) - 1)
    f.__wrapped_real__ = real
    f._tj_test_mock = True
    return f


def seq(*vals):
    def r(rec, i):
        if i < len(vals):
            v = vals[i]
            if isinstance(v, BaseException):
                raise v
            return v
        raise _Stop()
    return r


T.chk(sys.version_info >= (3, 8), "파이썬 3.8+(ast end_lineno)")
import exf_net  # noqa: E402
import net_http  # noqa: E402
import depaddr  # noqa: E402
import exf_binance  # noqa: E402
import exf_bithumb  # noqa: E402
import exf_bybit  # noqa: E402
import exf_coinbase  # noqa: E402
import exf_gate  # noqa: E402
import exf_kucoin  # noqa: E402
import exf_okx  # noqa: E402
import liq_watch  # noqa: E402
import onboarding  # noqa: E402
import pricing  # noqa: E402
import upbit_link  # noqa: E402

MODS = {m: sys.modules[m] for m in SITE_MODULES}

exf_net._CLOCK_ON[0] = True
exf_net._CLOCK.clear()
for _ex, _off in OFF.items():
    exf_net._CLOCK[_ex] = {"off": _off, "at": C.NOW, "rtt": 7}

_PATCHED = []


def _patch(obj, attr, name):
    real = getattr(obj, attr)
    setattr(obj, attr, _fake(name, real))
    _PATCHED.append(name)


for _site, _row in SITE_TABLE.items():
    _m = _site.split(":", 1)[0]
    for _v in _row["via"]:
        if _v == "self.call" or "." in _v:
            continue
        _nm = f"{_m}.{_v}"
        if _nm not in _PATCHED:
            _patch(MODS[_m], _v, _nm)
_patch(net_http, "auth_urlopen", "net_http.auth_urlopen")
_patch(exf_net, "http_json", "exf_net.http_json")
_patch(exf_net, "_http_json_err", "exf_net._http_json_err")
_patch(urllib.request, "urlopen", "urllib.request.urlopen")
if hasattr(net_http, "urlopen"):
    _patch(net_http, "urlopen", "net_http.urlopen")


T1 = int(C.NOW)
T0 = T1 - 3 * DAY
OKX_PAIR = ("eth", "0x" + "c4" * 20)


def _watcher():
    w = liq_watch.Watcher(sync=True)
    w.call = _fake("self.call", liq_watch.Watcher.call.__get__(w))
    return w


def _unsigned_fail(rec, i):
    if not rec["sites"]:
        raise RuntimeError("합성: 공개 목록 생략")
    raise _Stop()


def _bn_bal_reply(rec, i):
    base = rec["url"]["base"]
    if base.endswith("/fapi/v2/balance"):
        raise _Stop()
    if base.endswith("/api/v3/account"):
        return {"balances": []}
    raise RuntimeError("HTTP 403 합성 거부")


def _depaddr(ex, path, params):
    return lambda: depaddr.Client(ex, dict(ENV), pace=0).get(path, params)


DRIVERS = [
    ("binance.fetch", lambda: exf_binance.fetch_binance(dict(ENV), T0, T1), None),
    ("binance.caller", lambda: exf_binance._binance_caller(dict(ENV))("/api/v3/myTrades", {"symbol": "ETHUSDT", "fromId": 7, "limit": 1000}), None),
    ("binance.signed_get", lambda: exf_binance._binance_signed(dict(ENV), "/api/v3/account", {"omitZeroBalances": "true"}), None),
    ("binance.signed_post", lambda: exf_binance._binance_signed(dict(ENV), "/sapi/v1/asset/get-funding-asset", method="POST"), None),
    ("binance.bal_futures", lambda: exf_binance._bal_binance(dict(ENV)), _bn_bal_reply),
    ("binance.fut_fcall", lambda: exf_binance._fut_binance(dict(ENV)), None),
    ("binance.deriv_get", lambda: exf_binance._bn_deriv_get(dict(ENV), "dapi.binance.com", "/dapi/v1/account", {"x": "1"}), None),
    ("bithumb.fetch", lambda: exf_bithumb.fetch_bithumb(dict(ENV), T0, T1), None),
    ("bithumb.caller", lambda: exf_bithumb._bithumb_caller(dict(ENV))("/v1/orders", {"market": "KRW-BTC", "state": "done", "limit": 100}), None),
    ("bithumb.get", lambda: exf_bithumb._bithumb_get(dict(ENV), "/v1/accounts"), None),
    ("bybit.fetch", lambda: exf_bybit.fetch_bybit(dict(ENV), T0, T1), None),
    ("bybit.fills", lambda: exf_bybit.fills_bybit(dict(ENV), {}, T0, T1), _unsigned_fail),
    ("bybit.get", lambda: exf_bybit._bybit_get(dict(ENV), "/v5/user/query-api", {}), None),
    ("bybit.bal", lambda: exf_bybit._bal_bybit(dict(ENV)), seq({"retCode": 0, "result": {"list": []}})),
    ("bybit.fut", lambda: exf_bybit._fut_bybit(dict(ENV)), None),
    ("coinbase.get", lambda: exf_coinbase._cb_get(dict(ENV), "/api/v3/brokerage/accounts", {"limit": 250}), None),
    ("gate.fetch", lambda: exf_gate.fetch_gate(dict(ENV), T0, T1), None),
    ("gate.fills", lambda: exf_gate.fills_gate(dict(ENV), {}, T0, T1), None),
    ("gate.get", lambda: exf_gate._gate_get(dict(ENV), "/api/v4/wallet/total_balance", {"currency": "USDT"}), None),
    ("gate.get_noq", lambda: exf_gate._gate_get(dict(ENV), "/api/v4/spot/accounts"), None),
    ("kucoin.fetch", lambda: exf_kucoin.fetch_kucoin(dict(ENV), T0, T1), None),
    ("kucoin.fills", lambda: exf_kucoin.fills_kucoin(dict(ENV), {}, T0, T1), None),
    ("kucoin.call", lambda: exf_kucoin._kucoin_call(dict(ENV), "/api/v1/accounts?type=main"), None),
    ("kucoin.get", lambda: exf_kucoin._kucoin_get(dict(ENV), "/api/v1/accounts"), None),
    ("kucoin.fut_get", lambda: exf_kucoin._kucoin_fut_get(dict(ENV), "/api/v1/positions"), None),
    ("okx.fetch", lambda: exf_okx.fetch_okx(dict(ENV), T0, T1), None),
    ("okx.fills", lambda: exf_okx.fills_okx(dict(ENV), {}, T0, T1), None),
    ("okx.get", lambda: exf_okx._okx_get(dict(ENV), "/api/v5/account/balance", {"ccy": "USDT"}), None),
    ("depaddr.upbit", _depaddr("upbit", "/v1/deposits/coin_addresses", {}), None),
    ("depaddr.upbit_q", _depaddr("upbit", "/v1/deposits", {"currency": "ETH", "limit": 100}), None),
    ("depaddr.bithumb", _depaddr("bithumb", "/v1/deposits/coin_addresses", {"currency": "BTC"}), None),
    ("depaddr.binance", _depaddr("binance", "/sapi/v1/capital/deposit/address", {"coin": "ETH", "network": "ETH"}), None),
    ("depaddr.bybit", _depaddr("bybit", "/v5/asset/deposit/query-address", {"coin": "ETH"}), None),
    ("depaddr.okx", _depaddr("okx", "/api/v5/asset/deposit-address", {"ccy": "ETH"}), None),
    ("depaddr.kucoin", _depaddr("kucoin", "/api/v3/deposit-addresses", {"currency": "ETH"}), None),
    ("depaddr.gate", _depaddr("gate", "/api/v4/wallet/deposit_address", {"currency": "ETH"}), None),
    ("liq.bn_get", lambda: _watcher().bn_get(dict(ENV), "fapi.binance.com", "/fapi/v2/positionRisk"), None),
    ("liq.bybit_get", lambda: _watcher().bybit_get(dict(ENV), "/v5/position/list", {"category": "linear", "settleCoin": "USDT"}), None),
    ("liq.okx_get", lambda: _watcher().okx_get(dict(ENV), "/api/v5/account/positions", {"instType": "SWAP"}, "okx_pos"), None),
    ("onb.upbit", lambda: onboarding._test_group("upbit", [ENV["UPBIT_ACCESS"], ENV["UPBIT_SECRET"]]), None),
    ("onb.bithumb", lambda: onboarding._test_group("bithumb", [ENV["TJ_BITHUMB_KEY"], ENV["TJ_BITHUMB_SECRET"]]), None),
    ("onb.binance", lambda: onboarding._test_group("binance", [ENV["TJ_BINANCE_KEY"], ENV["TJ_BINANCE_SECRET"]]),
     seq((200, {"balances": [{"asset": "ETH", "free": "1", "locked": "0"}]}))),
    ("onb.bybit", lambda: onboarding._test_group("bybit", [ENV["TJ_BYBIT_KEY"], ENV["TJ_BYBIT_SECRET"]]),
     seq((200, {"retCode": 0, "result": {}}))),
    ("onb.okx", lambda: onboarding._test_group("okx", [ENV["TJ_OKX_KEY"], ENV["TJ_OKX_SECRET"], ENV["TJ_OKX_PASSPHRASE"]]),
     seq((200, {"code": "0", "data": []}))),
    ("onb.kucoin", lambda: onboarding._test_group("kucoin", [ENV["TJ_KUCOIN_KEY"], ENV["TJ_KUCOIN_SECRET"], ENV["TJ_KUCOIN_PASSPHRASE"]]), None),
    ("onb.gate", lambda: onboarding._test_group("gate", [ENV["TJ_GATE_KEY"], ENV["TJ_GATE_SECRET"]]), None),
    ("onb.coinbase", lambda: onboarding._test_group("coinbase", [ENV["TJ_COINBASE_KEY_NAME"], ENV["TJ_COINBASE_SECRET"]]),
     seq((200, {"accounts": [], "has_next": False}))),
    ("upbit.get_q", lambda: upbit_link.Upbit(ENV["UPBIT_ACCESS"], ENV["UPBIT_SECRET"]).get("/v1/withdraws", {"limit": 100, "page": 1, "order_by": "desc"}), None),
    ("upbit.get", lambda: upbit_link.Upbit(ENV["UPBIT_ACCESS"], ENV["UPBIT_SECRET"]).get("/v1/accounts"), None),
    ("pricing.okx_dex", lambda: pricing.okx_dex_prices({"key": ENV["TJ_OKX_KEY"], "secret": ENV["TJ_OKX_SECRET"], "passphrase": ENV["TJ_OKX_PASSPHRASE"]}, [OKX_PAIR]), None),
]

GOLD = {}
ERRS = {}
for name, fn, reply in DRIVERS:
    CAPS.clear()
    PENDING.clear()
    REPLY[0] = reply
    sys.setprofile(_prof)
    try:
        fn()
        ERRS[name] = "캡처 전에 끝남(멈춤 없음)"
    except _Stop:
        pass
    except Exception as e:   # noqa: BLE001
        ERRS[name] = f"{type(e).__name__}: {str(e)[:160]}"
    finally:
        sys.setprofile(None)
    if PENDING:
        ERRS[name] = f"서명했는데 안 나감: {PENDING}"
    GOLD[name] = [dict(c) for c in CAPS]
REPLY[0] = None

T.chk(not ERRS, "드라이버마다 목에서 멈춤(목에 닿기 전 실패·멈춤 없음·서명만 하고 안 나감 0)", ERRS)
T.chk(not REQ_MISMATCH, "Request.type·host·selector = full_url 을 다시 쪼갠 값(보낸 목적지·경로 = 캡처)", REQ_MISMATCH[:4])
T.chk(not BAD_JWT, "보낸 JWT 전부 전송 원문(header.payload)에 대한 서명이 맞음(HS256 · 코인베이스 ES256)", BAD_JWT)
T.chk(not TRAPS, "함정 전송 이름(받은 이름을 안 부르고 원본·다른 길로 감) 호출 0", TRAPS)
T.chk(not T.NET_TRIES, "바깥 연결 시도 0", T.NET_TRIES[:5])

got = {}
bad_via = []
for name, caps in GOLD.items():
    for c in caps:
        for s in sorted(set(c["sites"])):
            got[s] = got.get(s, 0) + 1
            row = SITE_TABLE.get(s)
            if row is None or c["via"] not in [(s.split(":")[0] + "." + v) if ("." not in v and v != "self.call") else v for v in row["via"]]:
                bad_via.append((name, s, c["via"]))
T.chk(set(got) == set(SITE_TABLE), "서명 자리 함수 전부 캡처됨(자리 표 = 실행에서 잡힌 자리)",
      {"안 잡힘": sorted(set(SITE_TABLE) - set(got)), "표 밖": sorted(set(got) - set(SITE_TABLE))})
T.chk(not bad_via, "캡처가 그 자리의 실제 전송 이름(자리 표 via)을 지남", bad_via[:8])
if EXPECT:
    T.chk(got == EXPECT, "자리별 캡처 수 = 기대 수", {k: (got.get(k), EXPECT.get(k)) for k in set(got) | set(EXPECT) if got.get(k) != EXPECT.get(k)})
else:
    T.chk(False, "EXPECT(자리별 기대 캡처 수) 채움", got)


def _dn(f):
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        b = _dn(f.value)
        return (b + "." if b else "?.") + f.attr
    return None


def _is_sign_call(d):
    return d in ("hmac.new", "hmac.digest", "hmac.HMAC") or bool(d and d.split(".")[0] in SIGN_HELPERS and d not in HASH_ONLY)


def ast_scan():
    lines, table = set(), {}
    SKIPPED.clear()
    for fn in sorted(os.listdir(T.SRC)):
        if not fn.endswith(".py"):
            continue
        mod = fn[:-3]
        if mod in SIGN_HELPERS:
            continue
        tree = ast.parse(open(os.path.join(T.SRC, fn), encoding="utf-8").read())
        for n9 in ast.walk(tree):
            if (isinstance(n9, ast.ImportFrom) and n9.module == "hmac") or \
                    (isinstance(n9, ast.Import) and any(a.name == "hmac" and a.asname for a in n9.names)):
                ALIAS_HMAC.append(f"{mod}:{n9.lineno}")
        funcs = {}

        def visit(node, qual):
            sig, calls = [], set()

            def w(n):
                for c in ast.iter_child_nodes(n):
                    if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                        continue
                    if isinstance(c, ast.Call):
                        d = _dn(c.func)
                        if _is_sign_call(d):
                            sig.append(c.lineno)
                        elif d:
                            calls.add(d)
                    w(c)
            w(node)
            o_sig, o_calls = funcs.get(qual, ([], set()))
            funcs[qual] = (o_sig + sig, o_calls | calls)

        def rec(node, prefix):
            for ch in ast.iter_child_nodes(node):
                if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    visit(ch, prefix + ch.name)
                    rec(ch, prefix + ch.name + ".")
                elif isinstance(ch, ast.ClassDef):
                    rec(ch, prefix + ch.name + ".")
                else:
                    rec(ch, prefix)
        rec(tree, "")
        for q, (sig, calls) in funcs.items():
            if sig and f"{mod}:{q}" in NOT_SIGN:
                SKIPPED.add(f"{mod}:{q}")
            if not sig or f"{mod}:{q}" in NOT_SIGN:
                continue
            lines.update((mod, ln) for ln in sig)
            via = sorted(calls & TRANSPORT)
            row = {"via": via}
            if not via:
                short = q.rsplit(".", 1)[-1]
                callers = sorted(q2 for q2, (_s, c2) in funcs.items() if q2 != q and (short in c2 or "self." + short in c2))
                row = {"via": sorted({v for q2 in callers for v in (funcs[q2][1] & TRANSPORT)}), "caller": callers}
            table[f"{mod}:{q}"] = row
    return lines, table


SKIPPED = set()
ALIAS_HMAC = []
S_LINES, S_TABLE = ast_scan()
T.chk(not ALIAS_HMAC, "src 에 from hmac import·import hmac as 없음(서명 줄 탐지·관찰 밖 꼴)", ALIAS_HMAC)
T.chk(SKIPPED == NOT_SIGN, "서명 아닌 hmac 허용 자리(NOT_SIGN)가 지금도 그 함수에 있음(낡은 허용 0)", sorted(SKIPPED ^ NOT_SIGN))
T.chk(S_TABLE == SITE_TABLE, "AST 함수별 전송 이름 표 = 자리 표(SITE_TABLE)",
      {k: (S_TABLE.get(k), SITE_TABLE.get(k)) for k in set(S_TABLE) | set(SITE_TABLE) if S_TABLE.get(k) != SITE_TABLE.get(k)})
T.chk({m for m, _ in S_LINES} == set(SITE_MODULES), "서명 줄 가진 모듈 = SITE_MODULES", sorted({m for m, _ in S_LINES} ^ set(SITE_MODULES)))
_unrun = sorted(S_LINES - set(SIGN_LINES))
T.chk(not _unrun, f"서명 호출 줄 {len(S_LINES)}개 전부 실행 중 서명함", _unrun)
T.chk(not (set(SIGN_LINES) - S_LINES), "실행 중 서명한 줄 = AST 서명 줄(표 밖 서명 0)", sorted(set(SIGN_LINES) - S_LINES)[:8])
print(f"서명 줄 {len(S_LINES)} · 자리 함수 {len(SITE_TABLE)} · 드라이버 {len(DRIVERS)} · 캡처 {sum(len(v) for v in GOLD.values())}", flush=True)


TS_LOCAL = {"depaddr.bithumb",
            "onb.bithumb", "onb.binance", "onb.bybit", "onb.okx", "onb.kucoin", "onb.gate", "onb.coinbase", "pricing.okx_dex"}
TS_NONE = {"depaddr.upbit", "depaddr.upbit_q", "onb.upbit", "upbit.get_q", "upbit.get"}
_HEAD_EX = {"binance": "binance", "bybit": "bybit", "okx": "okx", "kucoin": "kucoin", "gate": "gate", "bithumb": "bithumb", "coinbase": "coinbase",
            "bn": "binance"}


def ts_expect(name):
    if name in TS_NONE:
        return None
    if name in TS_LOCAL:
        return "local"
    head, tail = name.split(".", 1)
    return ("off", _HEAD_EX[tail.split("_")[0]] if head in ("depaddr", "liq") else _HEAD_EX[head])


def _ts_forms(off):
    ms = NOW_MS + off
    return {str(ms), str(ms // 1000), exf_net.iso_ms(ms)}


TS_KEYS = {"timestamp", "x-bapi-timestamp", "ok-access-timestamp", "kc-api-timestamp", "nbf"}


def ts_values(o, out):
    if isinstance(o, list):
        if len(o) == 2 and isinstance(o[0], str) and o[0].lower() in TS_KEYS and not isinstance(o[1], (list, dict)):
            out.append(str(o[1]))
        else:
            for x in o:
                ts_values(x, out)
    elif isinstance(o, dict):
        for x in o.values():
            ts_values(x, out)
    return out


miss_off = []
for name, caps in GOLD.items():
    want = ts_expect(name)
    vals = ts_values([c for c in caps if c["sites"]], [])
    if want is None:
        ok9 = not vals
    else:
        forms = _ts_forms(0 if want == "local" else OFF[want[1]])
        ok9 = bool(vals) and all(v in forms for v in vals)
    if not ok9:
        miss_off.append((name, want, vals[:3]))
T.chk(not miss_off, "서명 시각 = 기대 보정(거래소별 고정 차이 · 보정 없는 자리는 로컬 시각)만 — 다른 거래소 차이 섞임 0", miss_off)

_V = [
    (b"\x0b" * 20, b"Hi There", "sha256", "b0344c61d8db38535ca8afceaf0bf12b", "881dc200c9833da726e9376c2e32cff7"),
    (b"Jefe", b"what do ya want for nothing?", "sha256", "5bdcc146bf60754e6a042426089575c7", "5a003f089d2739839dec58b964ec3843"),
    (b"\xaa" * 20, b"\xdd" * 50, "sha256", "773ea91e36800e46854db8ebd09181a7", "2959098b3ef8c122d9635514ced565fe"),
    (b"\x0b" * 20, b"Hi There", "sha512", "87aa7cdea5ef619d4ff0b4241a1d6cb0", "2379f4e2ce4ec2787ad0b30545e17cde"
     "daa833b7d6b8a702038b274eaea3f4e4" "be9d914eeb61f1702e696c203a126854"),
    (b"Jefe", b"what do ya want for nothing?", "sha512", "164b7a7bfcf819e2e395fbe73b56e0a3", "87bd64222e831fd610270cd7ea250554"
     "9758bf75c05a994a6d034f65f8f0e6fd" "caeab1a34d4a6b4b636e070a38bce737"),
]
for i, (k, m, alg, a, b) in enumerate(_V, 1):
    T.chk(hmac.new(k, m, getattr(hashlib, alg)).hexdigest() == a + b, f"RFC 4231 벡터 {i}({alg})")
_BN_SEC = "NhqPtmdSJYdKjVHj" "A7PZj4Mge3R5YNiP" "1e3UZjInClVN65XA" "bvqqM6A7H5fATj0j"
_BN_QS = "symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1&price=0.1&recvWindow=5000&timestamp=1499827319559"
T.chk(hmac.new(_BN_SEC.encode(), _BN_QS.encode(), hashlib.sha256).hexdigest()
      == "c8db56825ae71d6d79447849e617115f" "4a920fa2acdcab2b053c4b2838bd6b71", "바이낸스 문서 예시 서명")

live = C.enc(C.canon(GOLD), lossy=True, where="서명 골든")
if RECORD:
    if getattr(T, "FAILS", None):
        T.chk(False, f"[{NAME}] 녹화 실패 — 앞선 검사 실패 {len(T.FAILS)}건(저장 안 함)")
    else:
        doc = {"_doc": "합성 데이터(지어낸 키 · 고정 시각·nonce) — test_sign_sites 의 서명 자리 요청 골든. 다시 녹화 = TJ_TEST_RECORD=%s · "
                       "«~…» = 서명 등 합성 꼴 아닌 16진수의 지문 · «u:n» = 고정 uuid4" % NAME,
               "version": 1, "name": NAME, "clock": {"now": C.NOW, "off_ms": OFF}, "golden": live}
        texts = {os.path.basename(GPATH): json.dumps(doc, ensure_ascii=False, indent=1) + "\n"}
        C._privacy_gate(texts, required=C.REPO_LAYOUT)
        C.write_pair(C.CAS_DIR, texts)
        T.chk(False, f"[{NAME}] 녹화 모드 — 드라이버 {len(GOLD)}개 저장함(판정 아님: 변수 없이 다시 돌려 재생 통과를 확인할 것)")
elif not os.path.isfile(GPATH):
    if C.REPO_LAYOUT:
        T.chk(False, f"[{NAME}] 골든 파일 있음(cassettes/{NAME}.golden.json)", f"TJ_TEST_RECORD={NAME} 로 녹화")
    else:
        print("골든 파일 없음 — 공개 패키지 배치라 골든 비교는 건너뜀", flush=True)
else:
    want = json.load(open(GPATH, encoding="utf-8"))["golden"]
    ds = list(itertools.islice(C.diff(want, live, "$"), 25))
    T.chk(not ds, f"[{NAME}] 골든 차이 0(서명 자리 요청 = 녹화 때와 같음)", ds)
T.finish()
