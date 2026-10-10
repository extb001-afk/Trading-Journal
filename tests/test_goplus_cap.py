#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import types

import common
import web

chk = T.chk
READS = []
CLOSED = []


class _Resp:

    def __init__(self, body, length="same"):
        self._b = body
        self.length = len(body) if length == "same" else length
        self.headers = {}
        self.status = 200

    def read(self, n=-1):
        READS.append(n)
        if n is None or n < 0:
            b, self._b = self._b, b""
        else:
            b, self._b = self._b[:n], self._b[n:]
        return b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        CLOSED.append(1)
        return False


CA = "0x" + "7e" * 20
RESP = {"v": None}


def _mock_open(req, timeout=None):
    return RESP["v"]


_mock_open._tj_test_mock = True
web.urllib.request.urlopen = _mock_open
CAP = getattr(web, "GOPLUS_BODY_MAX", None)
chk(CAP == 4 << 20, "G0 고플러스 응답 상한 = 4MiB(실측 응답 수 KB · 공용 상한 32MiB 보다 작게)", CAP)
CAP = CAP or (4 << 20)

print("[G] _goplus_fetch")
big = b'{"code":1,"result":{"' + CA.encode() + b'":{"x":"' + b"z" * (CAP + 100) + b'"}}}'
RESP["v"] = _Resp(big)
READS.clear()
err = None
try:
    web._goplus_fetch("8453", CA)
except Exception as e:
    err = e
chk(isinstance(err, common.ResponseTooLarge) and READS == [], "G1 큰 길이를 밝힌 응답 = 본문 읽기 전에 실패(종전: 끝까지 읽음)", (repr(err)[:120], READS[:3]))

RESP["v"] = _Resp(big, length=None)
READS.clear()
err = None
try:
    web._goplus_fetch("8453", CA)
except Exception as e:
    err = e
chk(isinstance(err, common.ResponseTooLarge) and READS == [CAP + 1], "G2 길이 없는 큰 응답 = 상한+1 까지만 읽고 실패", (repr(err)[:120], READS[:3]))

small = json.dumps({"code": 1, "message": "OK", "result": {CA: {"is_honeypot": "0"}}}).encode()
RESP["v"] = _Resp(small)
READS.clear()
CLOSED.clear()
d = T.safe(web._goplus_fetch, "8453", CA)
chk(isinstance(d, dict) and d.get("result", {}).get(CA, {}).get("is_honeypot") == "0" and READS == [len(small) + 1] and CLOSED == [1],
    "G3 작은 정상 응답 = 그대로 · 길이+1 만 요청 · 응답 닫음(종전: 닫지 않음)", (READS, CLOSED, str(d)[:80]))

RESP["v"] = _Resp(small, length=None)
READS.clear()
d = T.safe(web._goplus_fetch, "8453", CA)
chk(isinstance(d, dict) and READS == [CAP + 1], "G4 길이 없는 작은 응답 = 4MiB+1 만 미리 잡음(종전 32MiB 급 · 파이썬 3.9 bytearray)", READS)

print("[R] goplus_round")
key = f"base:{CA}"
NOW = 2_000_000_000.0
old = {key: {"ts": int(NOW - web.GOPLUS_TTL - 10), "risk": {"strong": True, "label": "스캠 확증 is_honeypot"}}}
common.atomic_write_json(web.GOPLUS_PATH, old)
web.BUILDER = types.SimpleNamespace(_goplus_want=[("base", CA)], cfg={}, soft_invalidate=lambda *a, **k: None)
web.GOPLUS_STATUS["limitedUntil"] = 0
RESP["v"] = _Resp(big, length=None)
st = {}
n = T.safe(web.goplus_round, st, NOW, None, lambda s: None)
after = common.read_json(web.GOPLUS_PATH, {})
chk(n == 1 and after == old and st.get("fail_until", {}).get(key) == NOW + web.GOPLUS_FAIL_RETRY and not st.get("net_fail"),
    "G5 상한 넘는 응답 = 위험 캐시 보존 · 그 CA 만 1시간 뒤 · 망 장애 계수 안 올림", (n, after == old, st))
chk(T.NET_TRIES == [], "G6 바깥 연결 0", T.NET_TRIES)
T.finish()
