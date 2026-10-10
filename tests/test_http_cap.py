#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import io
import json
import urllib.error

import bf_engine as B

chk = T.chk
READS = []


class _Resp:

    def __init__(self, body):
        self._b = body
        self.headers = {}
        self.status = 200

    def read(self, n=-1):
        READS.append(n)
        b, self._b = (self._b, b"") if n is None or n < 0 else (self._b[:n], self._b[n:])
        return b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Fp(io.BytesIO):
    def read(self, n=-1):
        READS.append(n)
        return super().read(n)


BODY = {"v": b""}
CALLS = {"n": 0}


def _open(req, timeout):
    CALLS["n"] += 1
    return _Resp(BODY["v"])


B._open = _open
CAP, ECAP = 32 * 1024 * 1024, 64 * 1024
chk(getattr(B, "HTTP_MAX_BYTES", None) == CAP and getattr(B, "HTTP_ERR_MAX_BYTES", None) == ECAP, "H0 상한 = 정상 32MiB · 오류 본문 64KiB",
    (getattr(B, "HTTP_MAX_BYTES", None), getattr(B, "HTTP_ERR_MAX_BYTES", None)))

print("[H] 정상 응답")
BODY["v"] = json.dumps({"jsonrpc": "2.0", "id": 1, "result": ["0x" + "ab" * 64] * 50}).encode()
READS.clear()
d = T.safe(B.http_json, "https://rpc-a.example.invalid/", data=b"{}", retries=3)
chk(isinstance(d, dict) and len(d.get("result") or ()) == 50 and READS == [CAP + 1],
    "H1 상한 안 응답 = 그대로 받음 · 읽기는 상한+1 에서 끊음(종전: 끝까지 r.read())", (READS, str(d)[:80]))

B.HTTP_MAX_BYTES = 4096
BODY["v"] = json.dumps({"jsonrpc": "2.0", "id": 1, "result": ["0x" + "cd" * 64] * 200}).encode()
READS.clear()
CALLS["n"] = 0
err = None
try:
    B.http_json("https://rpc-b.example.invalid/", data=b"{}", retries=3)
except B.NetError as e:
    err = e
chk(err is not None and err.kind == "range" and getattr(err, "results", False) and "response size" in str(err) and CALLS["n"] == 1
    and READS == [4097],
    "H2 상한 넘는 정상 응답 = 그 요청 실패(range · results — 그 청크만 반분 · 재시도 없음 · 상한+1 만 읽음)", (repr(err), CALLS["n"], READS))
chk(err is not None and B.rpc_fail_class(err) == "permanent", "H3 노드 교체 판정 = 그 요청 모양으로는 영구(다른 노드·작은 구간으로 — 같은 요청 되풀이 없음)",
    B.rpc_fail_class(err) if err is not None else None)
BODY["v"] = json.dumps({"r": "x" * (4096 - 9)}).encode()
chk(len(BODY["v"]) == 4096 and isinstance(T.safe(B.http_json, "https://rpc-c.example.invalid/", retries=1), dict),
    "H4 정확히 상한 크기 = 통과(경계)", len(BODY["v"]))
B.HTTP_MAX_BYTES = CAP

print("[E] 오류 본문")
big = b'{"error":"' + b"z" * (200 * 1024) + b'"}'
fp = _Fp(big)
READS.clear()
he = urllib.error.HTTPError("https://rpc-d.example.invalid/", 503, "busy", {}, fp)
ne = B.classify_exc(he, "rpc-d.example.invalid")
chk(ne.kind == "http5xx" and READS == [ECAP] and "HTTP Error 503" in str(ne) and len(str(ne)) < 400,
    "E1 HTTP 오류 본문 = 64KiB 까지만 읽음(종전: 끝까지) · 분류·문구 그대로(앞 300자)", (READS, str(ne)[:120]))

SET = []
B._rpc_day_of = lambda h: "tb" if "ledger" in h else None
B.rpc_day_unit = lambda n: "bytes"
B._rpc_day_units = lambda n, m=None, c=1: 1 << 20
B.rpc_day_take = lambda n, h, u: 7
B.rpc_day_settle = lambda n, a, r, d: SET.append((a, r))


def _open_err(req, timeout):
    CALLS["n"] += 1
    raise urllib.error.HTTPError(req.full_url, 500, "x", {}, _Fp(ERRB["v"]))


ERRB = {"v": big}
B._open = _open_err
B._RPC_DAY_SAVED = B._RPC_DAY
B._RPC_DAY = {"tb": {}}
READS.clear()
SET.clear()
try:
    B.http_json("https://ledger.example.invalid/", data=b"{}", retries=1)
except B.NetError as e:
    err = e
chk(READS == [ECAP + 1] and SET == [] and err.kind == "http5xx",
    "E2 바이트 장부 노드 오류 본문 = 64KiB+1 까지만 · 상한 넘음 = 받은 양 모름 → 예약 그대로(정산 안 함 · 보수)", (READS, SET, repr(err)))
ERRB["v"] = b'{"error":"small"}'
READS.clear()
SET.clear()
try:
    B.http_json("https://ledger.example.invalid/", data=b"{}", retries=1)
except B.NetError as e:
    err = e
chk(SET == [(len(ERRB["v"]), 1 << 20)] and "small" in str(err), "E3 작은 오류 본문 = 종전처럼 받은 만큼 정산", (SET, str(err)[:80]))
B._open = _open
BODY["v"] = b'{"result":[]}'
READS.clear()
SET.clear()
d = T.safe(B.http_json, "https://ledger.example.invalid/", data=b"{}", retries=1)
chk(d == {"result": []} and READS == [(1 << 20) + 1] and SET == [(len(BODY["v"]), 1 << 20)],
    "E4 바이트 장부 노드 정상 응답 = 종전대로 예약 상한+1(< 32MiB) 에서 끊고 받은 만큼 정산", (READS, SET, d))
B._RPC_DAY = B._RPC_DAY_SAVED

print("[B] 배치 반분(코덱스 fc431 HIGH)")
B._rpc_day_of = lambda h: None
B.HTTP_MAX_BYTES = 4096
SENT = []


def _open_batch(req, timeout):
    calls = json.loads(req.data.decode())
    SENT.append(len(calls))
    return _Resp(json.dumps([{"jsonrpc": "2.0", "id": c["id"], "result": "0x" + "ef" * 200 + format(c["params"][0], "x")}
                             for c in calls]).encode())


B._open = _open_batch
calls9 = [("eth_getBlockByNumber", [i]) for i in range(16)]
out9 = T.safe(B._rpc_batch_once, "https://rpc-batch.example.invalid/", calls9, 10, 1, 0, None, "rpc-batch.example.invalid")
chk(isinstance(out9, list) and len(out9) == 16 and all(str(x if not isinstance(x, dict) else x.get("result", "")).endswith(format(i, "x")) for i, x in enumerate(out9))
    and SENT[0] == 16 and max(SENT[1:] or [99]) < 16,
    "B1 배치 합계가 상한 초과 = 반으로 나눠 다시 · 16개 결과 순서 그대로(종전: 같은 배치를 노드만 바꿔 되풀이 → 계속 실패)", (SENT, type(out9).__name__))
B._open = lambda req, timeout: _Resp(b"[" + b'{"id":0,"result":"' + b"q" * 5000 + b'"}]')
err = None
try:
    B._rpc_batch_once("https://rpc-batch.example.invalid/", [("eth_getBlockByNumber", [1])], 10, 1, 0, None, "rpc-batch.example.invalid")
except B.NetError as e:
    err = e
chk(err is not None and err.kind == "range" and getattr(err, "results", False), "B2 한 건짜리 배치가 상한 초과 = 종전대로 올림(무한 반분 없음)", repr(err))
B.HTTP_MAX_BYTES = CAP
B._open = _open
T.finish()
