#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json

import bf_engine as B

chk = T.chk
READS = []


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
        return False


R = {"v": None}
B._open = lambda req, timeout: R["v"]
CAP = B.HTTP_MAX_BYTES
small = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "0x1234"}).encode()

print("[K] 일반 노드")
R["v"] = _Resp(small)
READS.clear()
d = T.safe(B.http_json, "https://rpc-a.example.invalid/", data=b"{}", retries=1)
chk(d == {"jsonrpc": "2.0", "id": 1, "result": "0x1234"} and READS == [len(small) + 1],
    "K1 길이 밝힌 작은 응답 = 길이+1 만 요청(종전 32MiB+1 — 3.9 큰 할당)", (READS, d))

B.HTTP_MAX_BYTES = 4096
bigb = json.dumps({"r": "x" * 9000}).encode()
R["v"] = _Resp(bigb)
READS.clear()
err = None
try:
    B.http_json("https://rpc-b.example.invalid/", data=b"{}", retries=3)
except B.NetError as e:
    err = e
chk(err is not None and err.kind == "range" and getattr(err, "results", False) and "response size" in str(err) and READS == [4097],
    "K2 길이가 상한보다 커도 미리 거절 없이 상한+1 만 읽고 종전 실패(range·results · 재시도 없음)", (repr(err), READS))
B.HTTP_MAX_BYTES = CAP

R["v"] = _Resp(small, length=None)
READS.clear()
T.safe(B.http_json, "https://rpc-c.example.invalid/", data=b"{}", retries=1)
chk(READS == [CAP + 1], "K5 길이 없음 = 종전 상한+1", READS)
for lv in (True, -1):
    R["v"] = _Resp(small, length=lv)
    READS.clear()
    T.safe(B.http_json, "https://rpc-c.example.invalid/", data=b"{}", retries=1)
    chk(READS == [CAP + 1], f"K6 길이 칸 {lv!r} = 무시(종전 상한+1)", READS)

print("[L] 바이트 장부 노드")
SET = []
o9 = (B._rpc_day_of, B.rpc_day_unit, B._rpc_day_units, B.rpc_day_take, B.rpc_day_settle, B._RPC_DAY)
B._rpc_day_of = lambda h: "tb" if "ledger" in h else None
B.rpc_day_unit = lambda n: "bytes"
B._rpc_day_units = lambda n, m=None, c=1: 1 << 20
B.rpc_day_take = lambda n, h, u: 7
B.rpc_day_settle = lambda n, a, r, d: SET.append((a, r))
B._RPC_DAY = {"tb": {}}
try:
    R["v"] = _Resp(small)
    READS.clear()
    SET.clear()
    d = T.safe(B.http_json, "https://ledger.example.invalid/", data=b"{}", retries=1)
    chk(isinstance(d, dict) and READS == [len(small) + 1] and SET == [(len(small), 1 << 20)],
        "K3 바이트 장부 노드 작은 응답 = 길이+1 · 받은 만큼 정산(종전 예약 1MiB+1 요청)", (READS, SET))
    big2 = b'{"r":"' + b"y" * ((1 << 20) + 50) + b'"}'
    R["v"] = _Resp(big2)
    READS.clear()
    SET.clear()
    err = None
    try:
        B.http_json("https://ledger.example.invalid/", data=b"{}", retries=1)
    except B.NetError as e:
        err = e
    chk(err is not None and "예약 상한" in str(err) and getattr(err, "results", False) and READS == [(1 << 20) + 1] and SET == [((1 << 20) + 1, 1 << 20)],
        "K4 예약 초과 = 예약+1 읽고 종전 실패·받은 만큼 정산(장부 오류가 32MiB 검사보다 먼저 — 우선순위 그대로)", (repr(err)[:120], READS, SET))
finally:
    B._rpc_day_of, B.rpc_day_unit, B._rpc_day_units, B.rpc_day_take, B.rpc_day_settle, B._RPC_DAY = o9
T.finish()
