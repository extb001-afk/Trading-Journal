from __future__ import annotations

import base64
import hashlib
import hmac
import json

__all__ = ["binance_sign", "bybit_sign", "okx_sign", "kucoin_sign", "kucoin_passphrase", "gate_sign", "jwt_hs256",
           "query_hash", "ec_key_body", "ec_p256_scalar", "ec_p256_pub", "jwt_es256", "es256_verify"]


def _hex256(key: bytes, msg: bytes) -> str:
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def _b64_256(key: bytes, msg: bytes) -> str:
    return base64.b64encode(hmac.new(key, msg, hashlib.sha256).digest()).decode()


def _hex512(key: bytes, msg: bytes) -> str:
    return hmac.new(key, msg, hashlib.sha512).hexdigest()


def _b64u(b: bytes) -> bytes:
    return base64.urlsafe_b64encode(b).rstrip(b"=")


def _jwt_sig(key: bytes, signing_input: bytes) -> bytes:
    return _b64u(hmac.new(key, signing_input, hashlib.sha256).digest())


def binance_sign(secret: str, qs: str) -> str:
    return _hex256(secret.encode(), qs.encode())


def bybit_sign(secret: str, ts: str, key: str, recv: str, qs: str) -> str:
    return _hex256(secret.encode(), (ts + key + recv + qs).encode())


def okx_sign(secret: str, ts: str, method: str, path: str, body: str = "") -> str:
    return _b64_256(secret.encode(), (ts + method + path + body).encode())


def kucoin_sign(secret: str, ts: str, method: str, path: str, body: str = "") -> str:
    return _b64_256(secret.encode(), (ts + method + path + body).encode())


def kucoin_passphrase(secret: str, passphrase: str) -> str:
    return _b64_256(secret.encode(), passphrase.encode())


def gate_sign(secret: str, method: str, path: str, qs: str, body_hash: str, ts: str) -> str:
    return _hex512(secret.encode(), f"{method}\n{path}\n{qs}\n{body_hash}\n{ts}".encode())


def jwt_hs256(payload: dict, secret: str) -> str:
    h = _b64u(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    p = _b64u(json.dumps(payload).encode())
    s = _jwt_sig(secret.encode(), h + b"." + p)
    return (h + b"." + p + b"." + s).decode()


def query_hash(params: dict) -> str:
    return hashlib.sha512("&".join(f"{k}={v}" for k, v in params.items()).encode()).hexdigest()


_EC_P = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffff
_EC_B = 0x5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604b
_EC_N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551
_EC_G = (0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296,
         0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5)
_P256_OID = bytes.fromhex("06082a8648ce3d030107")
_EC_OID = bytes.fromhex("06072a8648ce3d0201")


def _ec_dbl(p):
    if p is None or p[1] == 0:
        return None
    x, y, z = p
    yy = y * y % _EC_P
    s = 4 * x * yy % _EC_P
    zz = z * z % _EC_P
    m = 3 * (x - zz) * (x + zz) % _EC_P
    x3 = (m * m - 2 * s) % _EC_P
    return x3, (m * (s - x3) - 8 * yy * yy) % _EC_P, 2 * y * z % _EC_P


def _ec_add(p, q):
    if p is None:
        return q
    if q is None:
        return p
    x1, y1, z1 = p
    x2, y2, z2 = q
    z1z1, z2z2 = z1 * z1 % _EC_P, z2 * z2 % _EC_P
    u1, u2 = x1 * z2z2 % _EC_P, x2 * z1z1 % _EC_P
    s1, s2 = y1 * z2 * z2z2 % _EC_P, y2 * z1 * z1z1 % _EC_P
    if u1 == u2:
        return _ec_dbl(p) if s1 == s2 else None
    h, r = (u2 - u1) % _EC_P, (s2 - s1) % _EC_P
    h2 = h * h % _EC_P
    h3, u1h2 = h * h2 % _EC_P, u1 * h2 % _EC_P
    x3 = (r * r - h3 - 2 * u1h2) % _EC_P
    return x3, (r * (u1h2 - x3) - s1 * h3) % _EC_P, h * z1 * z2 % _EC_P


def _ec_affine(p):
    if p is None:
        return None
    zi = pow(p[2], -1, _EC_P)
    zi2 = zi * zi % _EC_P
    return p[0] * zi2 % _EC_P, p[1] * zi2 * zi % _EC_P


def _ec_mul(k: int, pt=_EC_G):
    r, q = None, (pt[0], pt[1], 1)
    for bit in bin(k)[2:]:
        r = _ec_dbl(r)
        if bit == "1":
            r = _ec_add(r, q)
    return _ec_affine(r)


def _on_curve(pt) -> bool:
    x, y = pt
    return 0 <= x < _EC_P and 0 <= y < _EC_P and (y * y - (x * x * x - 3 * x + _EC_B)) % _EC_P == 0


def _hm256(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


def _rfc6979_k(d: int, h1: bytes) -> int:
    x = d.to_bytes(32, "big")
    h = (int.from_bytes(h1, "big") % _EC_N).to_bytes(32, "big")
    v, k = b"\x01" * 32, b"\x00" * 32
    k = _hm256(k, v + b"\x00" + x + h)
    v = _hm256(k, v)
    k = _hm256(k, v + b"\x01" + x + h)
    v = _hm256(k, v)
    while True:
        v = _hm256(k, v)
        t = int.from_bytes(v, "big")
        if 1 <= t < _EC_N:
            return t
        k = _hm256(k, v + b"\x00")
        v = _hm256(k, v)


def _der(b: bytes, i: int = 0) -> list:
    out = []
    while i < len(b):
        if i + 2 > len(b):
            raise ValueError("DER 길이 부족")
        tag, ln = b[i], b[i + 1]
        i += 2
        if ln & 0x80:
            n = ln & 0x7F
            if not 1 <= n <= 2 or i + n > len(b):
                raise ValueError("DER 길이 형식")
            ln = int.from_bytes(b[i:i + n], "big")
            i += n
        if i + ln > len(b):
            raise ValueError("DER 내용 부족")
        out.append((tag, b[i:i + ln]))
        i += ln
    return out


def _pem_der(text: str) -> bytes:
    s = str(text or "").replace("\\n", "\n").replace("\\r", "")
    parts = s.split("-----")
    if len(parts) >= 5:
        lab = parts[1].strip()
        if lab not in ("BEGIN EC PRIVATE KEY", "BEGIN PRIVATE KEY") or parts[3].strip() != "END" + lab[5:]:
            raise ValueError("EC 비밀키 PEM 머리·꼬리 형식 오류(EC PRIVATE KEY · PRIVATE KEY 만)")
        s = parts[2]
    elif "-----" in s:
        raise ValueError("PEM 머리·꼬리가 짝이 안 맞음")
    body = "".join(s.split())
    if not body:
        raise ValueError("비밀키가 비었음")
    try:
        return base64.b64decode(body, validate=True)
    except ValueError:
        raise ValueError("비밀키 base64 형식 오류") from None


def _sec1_scalar(der: bytes) -> int:
    top = _der(der)
    if len(top) != 1 or top[0][0] != 0x30:
        raise ValueError("비밀키 DER 바깥 SEQUENCE 아님")
    it = _der(top[0][1])
    if len(it) >= 3 and it[0] == (0x02, b"\x00") and it[1][0] == 0x30 and it[2][0] == 0x04:
        alg = it[1][1]
        if alg != _EC_OID + _P256_OID:
            raise ValueError("P-256(prime256v1) 키가 아님 — 코인베이스 키는 ECDSA 로 만드세요(Ed25519 미지원)")
        return _sec1_scalar(it[2][1])
    if len(it) < 2 or it[0] != (0x02, b"\x01") or it[1][0] != 0x04 or len(it[1][1]) > 32:
        raise ValueError("SEC1 EC 비밀키 형식이 아님")
    d = int.from_bytes(it[1][1], "big")
    for tag, val in it[2:]:
        if tag == 0xA0 and val != _P256_OID:
            raise ValueError("P-256(prime256v1) 키가 아님 — 코인베이스 키는 ECDSA 로 만드세요(Ed25519 미지원)")
    if not 1 <= d < _EC_N:
        raise ValueError("비밀 스칼라 범위 밖")
    for tag, val in it[2:]:
        if tag == 0xA1:
            bs = _der(val)
            if len(bs) != 1 or bs[0][0] != 0x03 or len(bs[0][1]) != 66 or bs[0][1][:2] != b"\x00\x04":
                raise ValueError("공개점 형식 오류")
            pt = (int.from_bytes(bs[0][1][2:34], "big"), int.from_bytes(bs[0][1][34:], "big"))
            if ec_p256_pub(d) != pt:
                raise ValueError("비밀키와 공개점이 맞지 않음(복사가 잘렸거나 바뀜)")
    return d


def ec_p256_scalar(text: str) -> int:
    return _sec1_scalar(_pem_der(text))


def ec_key_body(text: str) -> str:
    der = _pem_der(text)
    _sec1_scalar(der)
    return base64.b64encode(der).decode()


def ec_p256_pub(d: int):
    return _ec_mul(int(d))


def jwt_es256(payload: dict, key: int | str, kid: str, nonce: str) -> str:
    d = key if isinstance(key, int) else ec_p256_scalar(key)
    h = _b64u(json.dumps({"alg": "ES256", "kid": kid, "nonce": nonce, "typ": "JWT"}).encode())
    p = _b64u(json.dumps(payload).encode())
    si = h + b"." + p
    return (si + b"." + _b64u(_es256_sig(d, si))).decode()


def _es256_sig(d: int, msg: bytes) -> bytes:
    if not 1 <= d < _EC_N:
        raise ValueError("비밀 스칼라 범위 밖")
    h1 = hashlib.sha256(msg).digest()
    e = int.from_bytes(h1, "big")
    k = _rfc6979_k(d, h1)
    r = _ec_mul(k)[0] % _EC_N
    s = pow(k, -1, _EC_N) * (e + r * d) % _EC_N
    if not r or not s:
        raise ValueError("ES256 서명 실패(r·s = 0)")
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def es256_verify(signing_input: bytes, sig64: bytes, pub: tuple) -> bool:
    if len(sig64) != 64 or not _on_curve(pub):
        return False
    r, s = int.from_bytes(sig64[:32], "big"), int.from_bytes(sig64[32:], "big")
    if not (1 <= r < _EC_N and 1 <= s < _EC_N):
        return False
    e = int.from_bytes(hashlib.sha256(signing_input).digest(), "big")
    w = pow(s, -1, _EC_N)
    a, b = _ec_mul(e * w % _EC_N), _ec_mul(r * w % _EC_N, pub)
    pt = _ec_affine(_ec_add(None if a is None else (a[0], a[1], 1), None if b is None else (b[0], b[1], 1)))
    return pt is not None and pt[0] % _EC_N == r
