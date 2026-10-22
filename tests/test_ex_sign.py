#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import base64  # noqa: E402
import hashlib  # noqa: E402
import hmac  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import random  # noqa: E402

import ex_sign as X  # noqa: E402

chk = T.chk

_V = [
    (b"\x0b" * 20, b"Hi There", "sha256", ("b0344c61d8db38535ca8afceaf0bf12b", "881dc200c9833da726e9376c2e32cff7")),
    (b"Jefe", b"what do ya want for nothing?", "sha256",
     ("5bdcc146bf60754e6a042426089575c7", "5a003f089d2739839dec58b964ec3843")),
    (b"\xaa" * 20, b"\xdd" * 50, "sha256", ("773ea91e36800e46854db8ebd09181a7", "2959098b3ef8c122d9635514ced565fe")),
    (b"\x0b" * 20, b"Hi There", "sha512", ("87aa7cdea5ef619d4ff0b4241a1d6cb0", "2379f4e2ce4ec2787ad0b30545e17cde",
                                           "daa833b7d6b8a702038b274eaea3f4e4", "be9d914eeb61f1702e696c203a126854")),
    (b"Jefe", b"what do ya want for nothing?", "sha512",
     ("164b7a7bfcf819e2e395fbe73b56e0a3", "87bd64222e831fd610270cd7ea250554",
      "9758bf75c05a994a6d034f65f8f0e6fd", "caeab1a34d4a6b4b636e070a38bce737")),
]
for i, (k, m, alg, parts) in enumerate(_V, 1):
    want = "".join(parts)
    got = X._hex256(k, m) if alg == "sha256" else X._hex512(k, m)
    chk(got == want, f"V{i} RFC 4231 벡터({alg}) — 내부 도우미")
    if alg == "sha256":
        chk(X._b64_256(k, m) == base64.b64encode(bytes.fromhex(want)).decode(), f"V{i}b 같은 벡터의 base64 꼴")
chk(X.binance_sign("Jefe", "what do ya want for nothing?") == "".join(_V[1][3]), "V6 binance_sign = RFC 4231 케이스 2(sha256 hex)")
chk(X.kucoin_passphrase("Jefe", "what do ya want for nothing?") == base64.b64encode(bytes.fromhex("".join(_V[1][3]))).decode(),
    "V7 kucoin_passphrase = RFC 4231 케이스 2(sha256 base64)")

_BN_SEC = "NhqPtmdSJYdKjVHj" "A7PZj4Mge3R5YNiP" "1e3UZjInClVN65XA" "bvqqM6A7H5fATj0j"
_BN_QS = "symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1&price=0.1&recvWindow=5000&timestamp=1499827319559"
chk(X.binance_sign(_BN_SEC, _BN_QS) == "c8db56825ae71d6d79447849e617115f" "4a920fa2acdcab2b053c4b2838bd6b71", "B1 바이낸스 문서 예시 서명")

rnd = random.Random(20261018)
_ALPHA = "abcXYZ019-_.~:+/=&?% 가나\U0001F600"


def _s(n=None):
    return "".join(rnd.choice(_ALPHA) for _ in range(rnd.randint(0, 24) if n is None else n))


def _old_binance(sec, qs):
    return hmac.new(sec.encode(), qs.encode(), hashlib.sha256).hexdigest()


def _old_bybit(sec, ts, key, recv, qs):
    return hmac.new(sec.encode(), (ts + key + recv + qs).encode(), hashlib.sha256).hexdigest()


def _old_okx(sec, ts, method, path, body=""):
    return base64.b64encode(hmac.new(sec.encode(), (ts + method + path + body).encode(), hashlib.sha256).digest()).decode()


def _old_pph(sec, pph):
    return base64.b64encode(hmac.new(sec.encode(), pph.encode(), hashlib.sha256).digest()).decode()


def _old_gate(sec, path, qs, bh, ts):
    return hmac.new(sec.encode(), f"GET\n{path}\n{qs}\n{bh}\n{ts}".encode(), hashlib.sha512).hexdigest()


def _old_jwt(payload, sec):
    def b64u(b):
        return base64.urlsafe_b64encode(b).rstrip(b"=")
    h = b64u(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    p = b64u(json.dumps(payload).encode())
    s = b64u(hmac.new(sec.encode(), h + b"." + p, hashlib.sha256).digest())
    return (h + b"." + p + b"." + s).decode()


def _old_jwt_str(payload, secret):
    def b64u(b):
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    h = b64u(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    p = b64u(json.dumps(payload).encode())
    s = b64u(hmac.new(secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest())
    return f"{h}.{p}.{s}"


def _old_qh(params):
    return hashlib.sha512("&".join(f"{k}={v}" for k, v in params.items()).encode()).hexdigest()


bad = []
for i in range(300):
    sec, ts, key, recv, qs, path, body = (_s() for _ in range(7))
    bh = hashlib.sha512(_s().encode()).hexdigest()
    pl = {"access_key": _s(8), "nonce": _s(12)}
    if i % 2:
        pl["timestamp"] = rnd.randint(0, 2 ** 45)
    if i % 3:
        prm = {_s(4) or "k": rnd.choice([_s(), rnd.randint(-5, 10 ** 12), 1.5, None, True])}
        pl["query_hash"] = X.query_hash(prm)
        pl["query_hash_alg"] = "SHA512"
        if _old_qh(prm) != pl["query_hash"]:
            bad.append(("qh", i))
    pairs = [
        ("binance", X.binance_sign(sec, qs), _old_binance(sec, qs)),
        ("bybit", X.bybit_sign(sec, ts, key, recv, qs), _old_bybit(sec, ts, key, recv, qs)),
        ("okx", X.okx_sign(sec, ts, "GET", path), _old_okx(sec, ts, "GET", path)),
        ("okx+body", X.okx_sign(sec, ts, "POST", path, body), _old_okx(sec, ts, "POST", path, body)),
        ("kucoin", X.kucoin_sign(sec, ts, "GET", path), _old_okx(sec, ts, "GET", path)),
        ("kucoin_pph", X.kucoin_passphrase(sec, key), _old_pph(sec, key)),
        ("gate", X.gate_sign(sec, "GET", path, qs, bh, ts), _old_gate(sec, path, qs, bh, ts)),
        ("jwt", X.jwt_hs256(pl, sec), _old_jwt(pl, sec)),
        ("jwt_str", X.jwt_hs256(pl, sec), _old_jwt_str(pl, sec)),
    ]
    bad += [(n, i) for n, a, b in pairs if a != b]
chk(not bad, "E1 300벌 — 8개 공식 모두 종전 인라인 식과 같은 문자열(바이트)", bad[:6])


def _exc(f, *a):
    try:
        f(*a)
    except Exception as e:   # noqa: BLE001
        return type(e)
    return None


chk(_exc(X.binance_sign, None, "a=1") is _exc(_old_binance, None, "a=1") is AttributeError, "E2 비밀값 None = AttributeError(종전과 같음)")
chk(_exc(X.bybit_sign, "s", 123, "k", "10000", "q") is _exc(_old_bybit, "s", 123, "k", "10000", "q") is TypeError,
    "E3 숫자 시각 = TypeError(str() 변환 없음 — 종전과 같음)")
chk(_exc(X.bybit_sign, None, 123, "k", "10000", "q") is _exc(_old_bybit, None, 123, "k", "10000", "q") is AttributeError,
    "E4 비밀값·시각 둘 다 틀림 = 비밀값 바이트화가 먼저(평가 순서 = 종전)")
chk(_exc(X.okx_sign, "s", "t", "GET", "/p", None) is TypeError, "E5 OKX 본문 None = TypeError(기본값 채우기 없음)")

pl = {"access_key": "sgUPkey01", "nonce": "00000000-0000-4000-8000-000000000001", "timestamp": 1760000000000,
      "query_hash": X.query_hash({"market": "KRW-BTC", "state": "done"}), "query_hash_alg": "SHA512"}
tok = X.jwt_hs256(pl, "sgUPsec01")
h64, p64, s64 = tok.split(".")
_pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
chk("=" not in tok and "+" not in tok and "/" not in tok, "J1 base64url · 패딩 없음")
chk(base64.urlsafe_b64decode(_pad(h64)) == b'{"alg": "HS256", "typ": "JWT"}', "J2 헤더 = json.dumps 기본 구분자")
chk(base64.urlsafe_b64decode(_pad(p64)) == json.dumps(pl).encode(), "J3 페이로드 = json.dumps(받은 dict) 그대로")
chk(list(json.loads(base64.urlsafe_b64decode(_pad(p64)))) == list(pl), "J4 칸 순서 = 받은 dict 순서")
chk(hmac.compare_digest(base64.urlsafe_b64decode(_pad(s64)),
                        hmac.new(b"sgUPsec01", (h64 + "." + p64).encode(), hashlib.sha256).digest()), "J5 서명 = HS256(header.payload)")
pl2 = {"nonce": pl["nonce"], "access_key": pl["access_key"]}
chk(X.jwt_hs256(pl2, "sgUPsec01").split(".")[1] != X.jwt_hs256({"access_key": pl["access_key"], "nonce": pl["nonce"]}, "sgUPsec01").split(".")[1],
    "J6 칸 순서가 다르면 페이로드 바이트도 다름(ex_sign 이 정렬하지 않음)")

q = {"start_time": "2026-10-18T00:00:00+09:00", "states[]": "done"}
chk(X.query_hash(q) == hashlib.sha512(b"start_time=2026-10-18T00:00:00+09:00&states[]=done").hexdigest(), "Q1 인코딩 전 원문 'k=v&k=v'")
chk(X.query_hash({"a": 1, "b": 2}) != X.query_hash({"b": 2, "a": 1}), "Q2 dict 순서 그대로(정렬 안 함)")
chk(X.query_hash({}) == hashlib.sha512(b"").hexdigest(), "Q3 빈 dict = 빈 문자열 해시")

src = open(os.path.join(T.SRC, "ex_sign.py"), encoding="utf-8").read()
tree = ast.parse(src)
imps = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | \
    {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
chk(imps == {"__future__", "base64", "hashlib", "hmac", "json"}, "M1 표준 라이브러리만(src 모듈 import 0)", sorted(imps))
chk(X.__all__ == ["binance_sign", "bybit_sign", "okx_sign", "kucoin_sign", "kucoin_passphrase", "gate_sign", "jwt_hs256", "query_hash",
                  "ec_key_body", "ec_p256_scalar", "ec_p256_pub", "jwt_es256", "es256_verify"],
    "M2 __all__ = 공식 함수 8 + ES256 5")
hm = sorted(f.name for f in tree.body if isinstance(f, ast.FunctionDef)
            for n in ast.walk(f) if isinstance(n, ast.Call) and ast.unparse(n.func) == "hmac.new")
chk(hm == ["_b64_256", "_hex256", "_hex512", "_hm256", "_jwt_sig"], "M3 hmac.new = 내부 도우미 5개에 하나씩", hm)

_h = lambda *a: int("".join(a), 16)  # noqa: E731
RX = _h("C9AFA9D845BA75166B5C215767B1D693", "4E50C3DB36E89B127B8A622B120F6721")
UX = _h("60FED4BA255A9D31C961EB74C6356D68", "C049B8923B61FA6CE669622E60F29FB6")
UY = _h("7903FE1008B8BC99A41AE9E95628BC64", "F2F1B20C2D7E9F5177A3C294D4462299")
chk(X.ec_p256_pub(RX) == (UX, UY), "S1 RFC 6979 A.2.5 공개점 = d·G")
_SV = [(b"sample", _h("EFD48B2AACB6A8FD1140DD9CD45E81D6", "9D2C877B56AAF991C34D0EA84EAF3716"),
        _h("F7CB1C942D657C41D436C7A1B6E29F65", "F3E900DBB9AFF4064DC4AB2F843ACDA8")),
       (b"test", _h("F1ABB023518351CD71D881567B1EA663", "ED3EFCF6C5132B354F28D3B0B7D38367"),
        _h("019F4113742A2B14BD25926B49C64915", "5F267E60D3814B4C0CC84250E46F0083"))]
for i, (m, r, s_) in enumerate(_SV, 2):
    sg = X._es256_sig(RX, m)
    chk(sg == r.to_bytes(32, "big") + s_.to_bytes(32, "big"), f"S{i} RFC 6979 결정적 서명 r·s('{m.decode()}' · SHA-256)")
    chk(X.es256_verify(m, sg, (UX, UY)), f"S{i}b 같은 서명 검증 참")
    bad9 = bytearray(sg)
    bad9[40] ^= 1
    chk(not X.es256_verify(m, bytes(bad9), (UX, UY)) and not X.es256_verify(m + b"!", sg, (UX, UY)), f"S{i}c 서명 한 비트·메시지 바뀜 = 거짓")


def _tlv(tag, body):
    n = len(body)
    return bytes([tag]) + (bytes([n]) if n < 128 else bytes([0x81, n])) + body


_PUB = b"\x00\x04" + UX.to_bytes(32, "big") + UY.to_bytes(32, "big")
_OID_P256 = bytes.fromhex("06082a8648ce3d030107")
SEC1 = _tlv(0x30, _tlv(0x02, b"\x01") + _tlv(0x04, RX.to_bytes(32, "big")) + _tlv(0xA0, _OID_P256) + _tlv(0xA1, _tlv(0x03, _PUB)))
PK8 = _tlv(0x30, _tlv(0x02, b"\x00") + _tlv(0x30, bytes.fromhex("06072a8648ce3d0201") + _OID_P256)
           + _tlv(0x04, _tlv(0x30, _tlv(0x02, b"\x01") + _tlv(0x04, RX.to_bytes(32, "big")))))


def _pem(der, lab):
    b = base64.b64encode(der).decode()
    return f"-----BEGIN {lab}-----\n" + "\n".join(b[i:i + 64] for i in range(0, len(b), 64)) + f"\n-----END {lab}-----\n"


P_SEC1, P_PK8 = _pem(SEC1, "EC PRIVATE KEY"), _pem(PK8, "PRIVATE KEY")
body = base64.b64encode(SEC1).decode()
forms = {"여러 줄 SEC1": P_SEC1, "PKCS8": P_PK8, "한 줄(입력칸이 줄바꿈 지움)": P_SEC1.replace("\n", ""),
         "공백으로 이음": P_SEC1.replace("\n", " "), "JSON \\n 이스케이프": P_SEC1.replace("\n", "\\n"), "본문만": body, "CRLF": P_SEC1.replace("\n", "\r\n")}
chk(all(X.ec_p256_scalar(v) == RX for v in forms.values()), "K1 PEM 7가지 꼴 → 같은 비밀 스칼라", [k for k, v in forms.items() if X.ec_p256_scalar(v) != RX])
chk(X.ec_key_body(P_SEC1) == body and X.ec_key_body(P_SEC1.replace("\n", "")) == body, "K2 저장 꼴 = 검증한 base64 본문(머리·공백 없음 · 같은 키 = 같은 값)")
chk(" " not in X.ec_key_body(P_PK8) and "-" not in X.ec_key_body(P_PK8), "K3 PKCS8 저장 꼴도 한 줄(공백·머리 없음 — .env 값 규칙)")


def _rej(v):
    try:
        X.ec_key_body(v)
    except ValueError:
        return True
    return False


ED = _pem(_tlv(0x30, _tlv(0x02, b"\x00") + _tlv(0x30, bytes.fromhex("06032b6570")) + _tlv(0x04, _tlv(0x04, b"\x11" * 32))), "PRIVATE KEY")
K1OID = bytes.fromhex("06052b8104000a")
SECK1 = _tlv(0x30, _tlv(0x02, b"\x01") + _tlv(0x04, RX.to_bytes(32, "big")) + _tlv(0xA0, K1OID))
WRONGPUB = _tlv(0x30, _tlv(0x02, b"\x01") + _tlv(0x04, (RX + 1).to_bytes(32, "big")) + _tlv(0xA0, _OID_P256) + _tlv(0xA1, _tlv(0x03, _PUB)))
chk(_rej(ED), "K4 Ed25519 키 = 거부(코인베이스 거래 API 미지원)")
chk(_rej(_pem(SECK1, "EC PRIVATE KEY")), "K5 다른 곡선(secp256k1) = 거부")
chk(_rej(_pem(WRONGPUB, "EC PRIVATE KEY")), "K6 비밀키·공개점 불일치(잘린·바뀐 복사) = 거부")
chk(_rej(P_SEC1.replace("BEGIN EC", "BEGIN RSA").replace("END EC", "END RSA")) and _rej("") and _rej("MHcC!!") and _rej(P_SEC1[:120]),
    "K7 RSA 머리·빈 값·base64 아님·잘린 PEM = 거부")
chk(_rej(_pem(_tlv(0x30, _tlv(0x02, b"\x01") + _tlv(0x04, b"\x00" * 32) + _tlv(0xA0, _OID_P256)), "EC PRIVATE KEY")), "K8 d = 0 = 거부")
PK8X = _tlv(0x30, _tlv(0x02, b"\x00") + _tlv(0x30, bytes.fromhex("06072a8648ce3d0201") + K1OID + _OID_P256)
            + _tlv(0x04, _tlv(0x30, _tlv(0x02, b"\x01") + _tlv(0x04, RX.to_bytes(32, "big")))))
LEAK = "-----" + body + "----------END EC PRIVATE KEY-----"
try:
    X.ec_key_body(LEAK)
    leak_msg = "(거부 안 됨)"
except ValueError as e:
    leak_msg = str(e)
chk(body[:12] not in leak_msg and body[-12:] not in leak_msg and leak_msg != "(거부 안 됨)", "K10 머리 자리에 본문이 든 꼴 = 거부 · 오류 문구에 비밀키 조각 없음", leak_msg[:60])
chk(_rej(_pem(PK8X, "PRIVATE KEY")), "K9 PKCS8 알고리즘에 다른 곡선 OID 를 덧붙인 꼴 = 거부(id-ecPublicKey + prime256v1 정확히)")

KID = "organizations/org-test/apiKeys/key-test"
pl = {"sub": KID, "iss": "cdp", "nbf": 1760000000, "exp": 1760000120, "uri": "GET api.coinbase.com/api/v3/brokerage/accounts"}
tok = X.jwt_es256(pl, P_SEC1, KID, "ab" * 16)
h64, p64, s64 = tok.split(".")
chk("=" not in tok, "J7 base64url 패딩 없음")
chk(json.loads(base64.urlsafe_b64decode(_pad(h64))) == {"alg": "ES256", "kid": KID, "nonce": "ab" * 16, "typ": "JWT"}
    and list(json.loads(base64.urlsafe_b64decode(_pad(h64)))) == ["alg", "kid", "nonce", "typ"], "J8 헤더 칸·순서")
chk(base64.urlsafe_b64decode(_pad(p64)) == json.dumps(pl).encode(), "J9 페이로드 = json.dumps(받은 dict) 그대로")
sg = base64.urlsafe_b64decode(_pad(s64))
chk(len(sg) == 64 and X.es256_verify((h64 + "." + p64).encode(), sg, (UX, UY)), "J10 서명 64바이트 r‖s · 공개점으로 검증 참")
chk(X.jwt_es256(pl, RX, KID, "ab" * 16) == tok and X.jwt_es256(pl, body, KID, "ab" * 16) == tok, "J11 같은 입력 = 같은 토큰(결정적 · 키 꼴 무관)")


def _der_sig(raw):
    def i9(v):
        b = v.to_bytes(33, "big").lstrip(b"\x00")
        return _tlv(0x02, b"\x00" + b if b[0] & 0x80 else b)
    return _tlv(0x30, i9(int.from_bytes(raw[:32], "big")) + i9(int.from_bytes(raw[32:], "big")))


import shutil  # noqa: E402
import subprocess  # noqa: E402
ossl = shutil.which("openssl")
if ossl:
    spki = _tlv(0x30, _tlv(0x30, bytes.fromhex("06072a8648ce3d0201") + _OID_P256) + _tlv(0x03, _PUB))
    d9 = os.path.join(T.TMP, "es256")
    os.makedirs(d9, exist_ok=True)
    with open(os.path.join(d9, "pub.pem"), "w") as f:
        f.write(_pem(spki, "PUBLIC KEY"))
    with open(os.path.join(d9, "sig.der"), "wb") as f:
        f.write(_der_sig(sg))
    with open(os.path.join(d9, "msg"), "wb") as f:
        f.write((h64 + "." + p64).encode())
    pr = subprocess.run([ossl, "dgst", "-sha256", "-verify", os.path.join(d9, "pub.pem"), "-signature", os.path.join(d9, "sig.der"),
                         os.path.join(d9, "msg")], capture_output=True, text=True, timeout=30)
    chk(pr.returncode == 0 and "Verified OK" in pr.stdout, "O1 openssl dgst -verify = Verified OK(바깥 구현이 우리 ES256 을 받아들임)", (pr.stdout + pr.stderr)[:200])
    with open(os.path.join(d9, "msg"), "ab") as f:
        f.write(b"x")
    pr2 = subprocess.run([ossl, "dgst", "-sha256", "-verify", os.path.join(d9, "pub.pem"), "-signature", os.path.join(d9, "sig.der"),
                          os.path.join(d9, "msg")], capture_output=True, text=True, timeout=30)
    chk(pr2.returncode != 0, "O2 메시지 한 바이트 덧붙임 = openssl 검증 실패(반대 방향)")
else:
    print("openssl 없음 — 바깥 검증(O1·O2) 건너뜀", flush=True)
T.finish()
