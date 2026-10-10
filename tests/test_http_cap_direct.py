#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import io
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

import common
import bf_engine as B
import netpace

chk = T.chk
READS = []
CALLS = []
BODY = {"v": b""}
CAP = 4096
ECAP = 64 * 1024


class _Resp:

    def __init__(self, body, length=None):
        self._b = body
        self.headers = {}
        self.status = 200
        if length is not None:
            self.length = length

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


def _uo(req, timeout=None, *a, **k):
    CALLS.append(getattr(req, "full_url", req))
    return _Resp(BODY["v"])


_uo._tj_test_mock = True


def _sol_open(req, timeout, method=None, deadline=None, sol=False):
    CALLS.append(getattr(req, "full_url", req))
    return _Resp(BODY["v"])


B.urllib.request.urlopen = _uo
B.sol_open = _sol_open
B.es_dispatch_wait = lambda *a, **k: None
netpace.interval_for = lambda h: 0.0
common.HTTP_BODY_MAX = CAP


def pad(d, n):
    s = json.dumps(dict(d, pad=""))
    return json.dumps(dict(d, pad="x" * max(0, n - len(s)))).encode()


BIG_N = CAP * 3


def bounded(reads, cap=CAP):
    return bool(reads) and all(isinstance(n, int) and 0 <= n <= cap + 1 for n in reads)


def run(fn, *a, **k):
    try:
        return fn(*a, **k), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def too_large(err):
    return bool(err) and "ResponseTooLarge" in err


print("[0] common.read_capped")
RT = getattr(common, "ResponseTooLarge", None)
rc = getattr(common, "read_capped", None)
chk(RT is not None and issubclass(RT, ValueError) and callable(rc),
    "C0 common.read_capped · ResponseTooLarge(ValueError — 깨진 JSON 과 같은 '응답 형식 오류' 처리) 있음", (RT, rc))
chk(getattr(common, "HTTP_ERR_BODY_MAX", None) == B.HTTP_ERR_MAX_BYTES and B.HTTP_MAX_BYTES == 32 * 1024 * 1024,
    "C1 상한 값 = 공통 요청 경로(bf_engine)와 같음(오류 본문 64KiB · 정상 32MiB)", (getattr(common, "HTTP_ERR_BODY_MAX", None), B.HTTP_ERR_MAX_BYTES))
if callable(rc) and RT is not None:
    READS.clear()
    chk(rc(_Resp(b"a" * CAP)) == b"a" * CAP and READS == [CAP + 1], "C2 정확히 상한 = 통과 · 읽기는 상한+1 에서 끊음", READS)
    READS.clear()
    r9, e9 = run(rc, _Resp(b"b" * (CAP + 1)))
    chk(r9 is None and too_large(e9) and READS == [CAP + 1] and "http" not in (e9 or "").lower(),
        "C3 상한+1 = ResponseTooLarge(명시 오류 · 잘린 본문 반환 없음 · 문구에 URL 없음)", (READS, e9))
    READS.clear()
    r9, e9 = run(rc, _Resp(b"c" * 10, length=CAP + 50))
    chk(r9 is None and too_large(e9) and READS == [], "C4 Content-Length 가 상한보다 큼 = 읽지 않고 실패", (READS, e9))
    READS.clear()
    chk(rc(_Resp(b"d" * 10, length=10)) == b"d" * 10 and READS == [11],
        "C5 Content-Length 를 아는 응답 = 그 길이+1 만 요청(파이썬 3.9 read(n) 은 n 바이트를 미리 잡는다)", READS)
    READS.clear()
    chk(rc(_Resp(b"e" * 10, length=True)) == b"e" * 10 and READS == [CAP + 1], "C6 길이 칸이 정수 아님(bool 등) = 무시(상한+1)", READS)
    READS.clear()
    r9, e9 = run(rc, _Resp(b"f" * 100), cap=50)
    chk(r9 is None and too_large(e9) and READS == [51], "C7 cap 인자 = 그 상한", (READS, e9))
    common.HTTP_BODY_MAX = 32 * 1024 * 1024
    READS.clear()
    chk(rc(_Resp(b"{}")) == b"{}" and READS == [32 * 1024 * 1024 + 1], "C8 기본 상한 = 32MiB(+1 에서 끊음)", READS)
    common.HTTP_BODY_MAX = CAP


def case(tag, label, call, small_ok, big_ok, small_body, big_body):
    BODY["v"] = small_body
    READS.clear()
    CALLS.clear()
    res, err = run(call)
    chk(small_ok(res, err) and bounded(READS), f"{tag}a {label} — 상한 안 응답 = 종전처럼 받음 · 읽기 상한+1 이하", (res if res is None or len(str(res)) < 200 else str(res)[:200], err, READS))
    BODY["v"] = big_body
    READS.clear()
    CALLS.clear()
    res, err = run(call)
    chk(big_ok(res, err) and bounded(READS), f"{tag}b {label} — 상한 넘는 응답 = 그 요청 실패(잘린 JSON 안 읽음 · 종전: 끝까지 r.read())",
        (str(res)[:120], err, READS))


print("[1] sol_watch 솔라나 수집")
import sol_watch
import collections


class _SolSelf:
    url = "https://sol-a.example.invalid/"
    metered = False
    proc = "test"
    rl_seen = 0
    rl_last = False
    rl_streak = 0

    def __init__(self):
        self.calls = collections.deque()

    def kind(self):
        return "live"


ss = _SolSelf()
case("S1", "sol_watch Rpc._call", lambda: sol_watch.Rpc._call(ss, ss.url, "getSlot", []),
     lambda r, e: r == 123 and e is None, lambda r, e: r is None and too_large(e),
     json.dumps({"jsonrpc": "2.0", "id": 1, "result": 123}).encode(), pad({"jsonrpc": "2.0", "id": 1, "result": 123}, BIG_N))
big_err = b'{"error":"' + b"q" * (200 * 1024) + b' max usage"}'


def _sol_open_429(req, timeout, method=None, deadline=None, sol=False):
    raise urllib.error.HTTPError(req.full_url, 429, "busy", {}, _Fp(big_err))


B.sol_open = _sol_open_429
READS.clear()
r9, e9 = run(sol_watch.Rpc._call, ss, ss.url, "getSlot", [])
chk(e9 is not None and "429" in e9 and READS == [ECAP], "S2 sol_watch 429 오류 본문 = 64KiB 까지만 읽음(종전: 끝까지 e.read())", (READS, e9))
B.sol_open = _sol_open

print("[2] recon 잔고 대사")
import recon
case("R1", "recon._gj(블록스카웃 보유 목록)", lambda: recon._gj("https://bs-r.example.invalid/api", tries=3, sleep=lambda s: None),
     lambda r, e: r == {"items": []} and e is None, lambda r, e: r is None and too_large(e) and len(CALLS) == 1,
     b'{"items": []}', pad({"items": []}, BIG_N))
case("R2", "recon._rpc(솔라나 · 직접)", lambda: recon._rpc("https://sol-r.example.invalid/", "getBalance", ["x"], gap=False),
     lambda r, e: r == {"value": 5} and e is None, lambda r, e: r is None and too_large(e),
     b'{"jsonrpc":"2.0","id":1,"result":{"value":5}}', pad({"jsonrpc": "2.0", "id": 1, "result": {"value": 5}}, BIG_N))
case("R3", "recon._rpc(솔라나 · sol_open)", lambda: recon._rpc("https://sol-r2.example.invalid/", "getBalance", ["x"], gap=True),
     lambda r, e: r == {"value": 5} and e is None, lambda r, e: r is None and too_large(e),
     b'{"jsonrpc":"2.0","id":1,"result":{"value":5}}', pad({"jsonrpc": "2.0", "id": 1, "result": {"value": 5}}, BIG_N))

print("[3] xchain_match 브릿지 추적")
import xchain_match


class _TrSelf:
    budget = 100
    sleep = 0
    calls = 0


tr = _TrSelf()
case("X1", "xchain Tracer._post(솔라나)", lambda: xchain_match.Tracer._post(tr, "https://sol-x.example.invalid/", "getTransaction", ["sig"]),
     lambda r, e: r == {"slot": 1} and e is None, lambda r, e: r is None and too_large(e),
     b'{"jsonrpc":"2.0","id":1,"result":{"slot":1}}', pad({"jsonrpc": "2.0", "id": 1, "result": {"slot": 1}}, BIG_N))
case("X2", "xchain Tracer._get(탐색기)", lambda: xchain_match.Tracer._get(tr, "https://bs-x.example.invalid/api/v2/x"),
     lambda r, e: r == {"items": []} and e is None, lambda r, e: r is None and too_large(e),
     b'{"items": []}', pad({"items": []}, BIG_N))

print("[4] flow_trace 자금 흐름 추적(이더스캔)")
import flow_trace


class _EsSelf:
    t = _TrSelf()


case("F1", "flow_trace Scanner._es_http", lambda: flow_trace.Scanner._es_http(_EsSelf(), "https://es-f.example.invalid/v2/api?module=account"),
     lambda r, e: r == {"status": "1", "result": []} and e is None, lambda r, e: r is None and too_large(e) and "example" not in (e or ""),
     b'{"status":"1","result":[]}', pad({"status": "1", "result": []}, BIG_N))

print("[5] lpchain LP 목록(블록스카웃 NFT)")
import lpchain
lpchain.lpdec.lp_managers = lambda bd: {"base": {"0x" + "ab" * 20: {}}}
cfg_lp = {"chains": {"base": {"blockscout": "https://bs-lp.example.invalid"}}}
item = {"token": {"address": "0x" + "ab" * 20}, "id": "7"}
case("L1", "lpchain.list_wallet_positions", lambda: lpchain.list_wallet_positions(cfg_lp, "base", "0x" + "cd" * 20),
     lambda r, e: r == [("0x" + "ab" * 20, 7)], lambda r, e: r is None and e is None,
     json.dumps({"items": [item], "next_page_params": None}).encode(), pad({"items": [item], "next_page_params": None}, BIG_N))

print("[6] lpsol 솔라나 LP 계정")
import lpsol
case("P1", "lpsol._rpc", lambda: lpsol._rpc(["https://sol-lp.example.invalid/"], "getMultipleAccounts", [[], {}]),
     lambda r, e: r == {"value": []}, lambda r, e: r is None and e is None,
     b'{"jsonrpc":"2.0","id":1,"result":{"value":[]}}', pad({"jsonrpc": "2.0", "id": 1, "result": {"value": []}}, BIG_N))

print("[7] sale_match 세일 매칭")
import sale_match
case("M1", "sale_match.http_get_json", lambda: sale_match.http_get_json("https://bs-sm.example.invalid/api?module=logs"),
     lambda r, e: r == {"status": "1", "result": []} and e is None, lambda r, e: r is None and too_large(e),
     b'{"status":"1","result":[]}', pad({"status": "1", "result": []}, BIG_N))

print("[8] pricing 시세")
import pricing
case("Q1", "pricing._gj", lambda: pricing._gj("https://px.example.invalid/v1"),
     lambda r, e: r == {"rates": {"KRW": 1}} and e is None, lambda r, e: r is None and too_large(e),
     b'{"rates":{"KRW":1}}', pad({"rates": {"KRW": 1}}, BIG_N))
pricing.okx_headers = lambda *a, **k: {"Content-Type": "application/json"}
anc = pricing._okx_anchor_for("eth")
tok = "0x" + "12" * 20
okx_ok = {"code": "0", "data": [{"chainIndex": "1", "tokenContractAddress": anc, "price": "1.0"},
                                {"chainIndex": "1", "tokenContractAddress": tok, "price": "2.5"}]}
case("Q2", "pricing.okx_dex_prices(OKX 토큰 가격)", lambda: pricing.okx_dex_prices({"k": "synthetic"}, [("eth", tok)]),
     lambda r, e: r == {("eth", tok): 2.5}, lambda r, e: r == {} and e is None,
     json.dumps(okx_ok).encode(), pad(okx_ok, BIG_N))

print("[9] rabby 지갑 조회")
import rabby
case("B1", "rabby.http_get", lambda: rabby.http_get("https://rb.example.invalid/v1/user/total_balance?id=x"),
     lambda r, e: r == {"total_usd_value": 1} and e is None, lambda r, e: r is None and too_large(e),
     b'{"total_usd_value":1}', pad({"total_usd_value": 1}, BIG_N))

print("[10] upbit_link 업비트")
import upbit_link
up = upbit_link.Upbit("synthetic-access", "synthetic-secret")
case("U1", "upbit_link.Upbit.get", lambda: up.get("/v1/accounts"),
     lambda r, e: r == [] and e is None, lambda r, e: r is None and too_large(e),
     b"[]", json.dumps([{"pad": "x" * BIG_N}]).encode())

print("[11] depaddr 입금 주소")
import depaddr
case("D1", "depaddr.http_get", lambda: depaddr.http_get("https://ex-d.example.invalid/api/v1/x", {}),
     lambda r, e: isinstance(r, tuple) and r[0] == {"ok": 1} and e is None,
     lambda r, e: r is None and bool(e) and "ApiError" in e and "ResponseTooLarge" in e,
     b'{"ok":1}', pad({"ok": 1}, BIG_N))


def _uo_400(req, timeout=None, *a, **k):
    raise urllib.error.HTTPError(getattr(req, "full_url", req), 400, "bad", {}, _Fp(b'{"msg":"' + b"z" * (200 * 1024) + b'"}'))


_uo_400._tj_test_mock = True
B.urllib.request.urlopen = _uo_400
READS.clear()
r9, e9 = run(depaddr.http_get, "https://ex-d2.example.invalid/api/v1/x", {})
chk(e9 is not None and "HTTP 400" in e9 and READS == [ECAP], "D2 depaddr HTTP 오류 본문 = 64KiB 까지만 읽음(종전: 끝까지 e.read())", (READS, (e9 or "")[:80]))
B.urllib.request.urlopen = _uo

print("[12] web 거래 출처(_origin_worker)")
import web


class _Stop(BaseException):
    pass


class _WebSelf:
    cfg = {}

    def __init__(self):
        self._origin_lock = threading.Lock()
        self._origin_pending = {"0x" + "77" * 32}

    def _origin_chains(self):
        return [("base", "https://bs-w.example.invalid")]

    def _origin_net_hints(self, todo):
        return {}

    def soft_invalidate(self):
        pass


_sleep0 = time.sleep


def _origin_once():
    n = {"s": 0}

    def _sl(s):
        if s == 60:
            n["s"] += 1
            if n["s"] >= 2:
                raise _Stop()

    time.sleep = _sl
    try:
        try:
            web.StateBuilder._origin_worker(_WebSelf())
        except _Stop:
            pass
    finally:
        time.sleep = _sleep0
    c = common.read_json(os.path.join(common.STATE_DIR, "tx_origin_cache.json"), {})
    try:
        os.remove(os.path.join(common.STATE_DIR, "tx_origin_cache.json"))
    except OSError:
        pass
    return c.get("0x" + "77" * 32) or {}


txd = {"hash": "0x" + "77" * 32, "from": {"hash": "0x" + "a1" * 20}, "to": {"hash": "0x" + "b2" * 20}}
case("W1", "web StateBuilder._origin_worker", _origin_once,
     lambda r, e: (r or {}).get("from") == "0x" + "a1" * 20 and (r or {}).get("chain") == "base",
     lambda r, e: isinstance(r, dict) and r.get("from") is None and r.get("n") == 1,
     json.dumps(txd).encode(), pad(txd, BIG_N))

print("[13] 정적 — 직접 조회 파일에 끝까지 읽는 r.read()·e.read() 없음")
FILES = ["sol_watch", "recon", "xchain_match", "flow_trace", "lpchain", "lpsol", "sale_match", "pricing", "rabby", "upbit_link", "depaddr", "web"]
pat = re.compile(r"\b(?:r|r9|e)\.read\(\)")
left = []
for m in FILES:
    with open(os.path.join(T.SRC, m + ".py"), encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if pat.search(line):
                left.append(f"{m}.py:{i}")
chk(not left, "Z1 12개 파일에 응답·오류 본문을 끝까지 읽는 곳 0(새로 생겨도 여기서 잡힘)", left)

T.finish()
