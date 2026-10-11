#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import socket
import threading
import time
import urllib.request

json.dump({"chains": {"base": {"blockscout": "https://bs.invalid", "conf_depth": 3, "rpcs": ["https://rpc.invalid"]}},
           "wallets": [{"type": "evm", "chain": "base", "address": "0x" + "a1" * 20, "label": "w"}]},
          open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
import bf_engine
import common
import evm_watch

chk = T.chk
print("[1] 블록스카웃 상세 목록 누적 상한")
CAP = getattr(evm_watch, "BsDetailCap", None)
CALLS = []


def fake_pages(mode, per=50, item=None):
    def f(url, prio="fg", deadline=None, retries=None, breaker_5xx=True):
        CALLS.append(url)
        if len(CALLS) > 1500:
            raise KeyboardInterrupt("시험 보호: 1,500쪽 넘게 요청")
        n = len(CALLS)
        it = [dict(item or {"i": n * 1000 + k}) for k in range(per)]
        if mode == "finite" and n >= 3:
            return {"items": it[:30], "next_page_params": None}
        return {"items": it, "next_page_params": {"block_number": 10 ** 6 - n, "index": n}}
    f._tj_test_mock = True
    return f


w = evm_watch.ChainWatcher.__new__(evm_watch.ChainWatcher)
w.base = "https://bs.invalid"
w.chain = "base"
http0 = evm_watch.http_json


def run(mode, **kw):
    del CALLS[:]
    evm_watch.http_json = fake_pages(mode, **kw)
    try:
        return w._fetch_all_items("/api/v2/transactions/0xabc/token-transfers"), None
    except KeyboardInterrupt as e:
        return None, e
    except Exception as e:
        return None, e
    finally:
        evm_watch.http_json = http0


out, err = run("finite")
chk(err is None and len(out) == 130 and len(CALLS) == 3, "정상 3쪽(50·50·30) = 130개 전부 · 3콜", (len(out or []), len(CALLS), err))
out, err = run("endless")
chk(CAP is not None and isinstance(err, CAP) and len(CALLS) == 200 and out is None,
    "다른 커서를 끝없이 줌 = 200쪽에서 BsDetailCap(부분 목록 반환 없음 · 종전 = 끝없이 누적)", (type(err).__name__, len(CALLS)))
out, err = run("endless", per=5000)
chk(CAP is not None and isinstance(err, CAP) and len(CALLS) == 5 and "20,000" in str(err), "쪽마다 5,000개 = 5쪽(25,000개 > 2만)에서 상한", (type(err).__name__, len(CALLS), str(err)[:120]))
w.BS_DETAIL_MAX_BYTES = 200_000
out, err = run("endless", item={"pad": "x" * 1000})
chk(CAP is not None and isinstance(err, CAP) and 3 <= len(CALLS) <= 5 and "바이트" in str(err), "바이트 상한(시험 200KB · 항목 1KB × 50/쪽) = 넷째 쪽 즈음 상한", (type(err).__name__, len(CALLS)))
del w.BS_DETAIL_MAX_BYTES
w.BS_DETAIL_MAX_BYTES = 1_000_000


def fake_bigcur(url, prio="fg", deadline=None, retries=None, breaker_5xx=True):
    CALLS.append(url)
    if len(CALLS) > 1500:
        raise KeyboardInterrupt("시험 보호: 1,500쪽 넘게 요청")
    return {"items": [], "next_page_params": {"k": str(len(CALLS)) + "c" * 200_000}}


fake_bigcur._tj_test_mock = True
del CALLS[:]
evm_watch.http_json = fake_bigcur
try:
    w._fetch_all_items("/api/v2/transactions/0xabc/internal-transactions")
    err = None
except KeyboardInterrupt as e:
    err = e
except Exception as e:
    err = e
finally:
    evm_watch.http_json = http0
    del w.BS_DETAIL_MAX_BYTES
chk(CAP is not None and isinstance(err, CAP) and len(CALLS) <= 6 and "바이트" in str(err),
    "항목 0 · 큰 커서(200KB씩)만 = 바이트 상한(시험 1MB)에 걸림 — 커서도 셈(코덱스 ui904 · 종전 200쪽까지 커서 40MB 보관)", (type(err).__name__, len(CALLS), str(err)[:100]))
TX = {"hash": "0xabc", "block_number": 123, "value": "0", "fee": {"value": "1"}, "status": "ok", "timestamp": "2026-10-11T00:00:00Z"}


def fake_detail(url, prio="fg", deadline=None, retries=None, breaker_5xx=True):
    if url.endswith("/0xabc"):
        return dict(TX)
    return fake_pages("endless")(url)


fake_detail._tj_test_mock = True
del CALLS[:]
evm_watch.http_json = fake_detail
try:
    snap, e9 = w.fetch_detail("0xabc"), None
except KeyboardInterrupt as e:
    snap, e9 = None, e
except Exception as e:
    snap, e9 = None, e
finally:
    evm_watch.http_json = http0
chk(snap is None and CAP is not None and isinstance(e9, CAP), "fetch_detail: 토큰 이동 목록 상한 초과 = 예외(부분 목록으로 완전 상세 안 만듦)", (type(e9).__name__, str(e9)[:100]))
w.enrich = {"0xabc": 0}
w._enrich_5xx = {}
w.emitted = set()
w.cursor = {}


def fd_cap(h, accept_pending=False):
    raise (CAP or RuntimeError)("상세 목록 상한 초과(합성)")


w.fetch_detail = fd_cap
w._enrich_pass(1000, healthy=True)
pz = os.path.join(common.STATE_DIR, "pending_poison.jsonl")
rows = [json.loads(x) for x in open(pz)] if os.path.exists(pz) else []
chk(not w.enrich and any(r.get("src") == "enrich_giveup_cap" and r.get("txhash") == "0xabc" for r in rows),
    "enrich: 상한 초과 = 1번에 포기(pending_poison 기록 · rpc_basic 확정 — 종전 200회 × 최대 200쪽)", (w.enrich, rows[-1:] if rows else None))

print("[2] 응답 본문 수신 절대 마감(bf_engine)")
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def loop_open(req, timeout=None, *a, **k):
    u = getattr(req, "full_url", req)
    if "://127.0.0.1:" not in str(u):
        raise OSError("시험: 바깥 연결 차단")
    return _opener.open(req, timeout=timeout)


loop_open._tj_test_mock = True
bf_engine._open = loop_open


def server(handler):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 0))
    s.listen(8)

    def loop():
        while True:
            try:
                c, _a = s.accept()
            except OSError:
                return
            threading.Thread(target=one, args=(c,), daemon=True).start()

    def one(c):
        try:
            c.settimeout(10)
            buf = b""
            while b"\r\n\r\n" not in buf:
                d = c.recv(4096)
                if not d:
                    return
                buf += d
            handler(c)
        except OSError:
            pass
        finally:
            try:
                c.close()
            except OSError:
                pass
    threading.Thread(target=loop, daemon=True).start()
    return s, "http://127.0.0.1:%d/x" % s.getsockname()[1]


def drip(c):
    c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2000\r\nConnection: close\r\n\r\n")
    t0 = time.time()
    while time.time() - t0 < 6.0:
        c.sendall(b" ")
        time.sleep(0.2)


def ok_len(c):
    body = json.dumps({"ok": True, "pad": "y" * 200_000}).encode()
    c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(body) + body)


def ok_chunked(c):
    body = json.dumps({"ok": True, "n": 7}).encode()
    c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n")
    for i in range(0, len(body), 5):
        part = body[i:i + 5]
        c.sendall(b"%x\r\n" % len(part) + part + b"\r\n")
        time.sleep(0.01)
    c.sendall(b"0\r\n\r\n")


def drip_trailer(c):
    c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n2\r\n{}\r\n0\r\n")
    t0 = time.time()
    while time.time() - t0 < 6.0:
        c.sendall(b"X-Pad: a\r\n")
        time.sleep(0.2)
    c.sendall(b"\r\n")


def drip_chunkext(c):
    c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n2;")
    t0 = time.time()
    while time.time() - t0 < 6.0:
        c.sendall(b"x")
        time.sleep(0.2)
    c.sendall(b"\r\n{}\r\n0\r\n\r\n")


def err500(c):
    body = b'{"error":"synthetic upstream failure"}'
    c.sendall(b"HTTP/1.1 500 Internal Server Error\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(body) + body)


def call(url, **kw):
    bf_engine._GATES.clear()
    t0 = time.time()
    try:
        return bf_engine.http_request(url, **kw)[0], None, time.time() - t0
    except Exception as e:
        return None, e, time.time() - t0


srv = []
for h9 in (ok_len, ok_chunked, err500, drip, drip, drip_trailer, drip_trailer, drip_chunkext):
    srv.append(server(h9))
d9, e9, t9 = call(srv[0][1], timeout=5.0, retries=1)
chk(e9 is None and d9.get("ok") and len(d9.get("pad") or "") == 200_000, "정상 200KB(길이 있음) = 그대로 받음", (e9, t9))
d9, e9, t9 = call(srv[1][1], timeout=5.0, retries=1, deadline=time.time() + 5, sem_timeout=5)
chk(e9 is None and d9 == {"ok": True, "n": 7}, "chunked 응답(하드 마감 모드) = 그대로", (e9, d9))
d9, e9, t9 = call(srv[2][1], timeout=5.0, retries=1, retry_5xx=False)
chk(isinstance(e9, bf_engine.NetError) and e9.kind == "http5xx" and "synthetic upstream failure" in str(e9), "HTTP 500 = http5xx · 본문 앞부분 분류(같은 마감으로 읽음)", (type(e9).__name__, str(e9)[:120]))
d9, e9, t9 = call(srv[3][1], timeout=1.0, retries=1, deadline=time.time() + 1.5, sem_timeout=1.5)
chk(isinstance(e9, bf_engine.NetError) and e9.kind == "timeout" and t9 < 3.0,
    "하드 마감(1.5초) + 0.2초마다 1바이트 = 마감 안에 timeout(종전 ≈6초 붙잡힌 뒤 payload)", (type(e9).__name__, getattr(e9, "kind", None), round(t9, 2)))
body0 = bf_engine.__dict__.get("HTTP_BODY_MAX_SEC")
bf_engine.HTTP_BODY_MAX_SEC = 1.0
try:
    d9, e9, t9 = call(srv[4][1], timeout=0.5, retries=1)
finally:
    if body0 is None:
        del bf_engine.HTTP_BODY_MAX_SEC
    else:
        bf_engine.HTTP_BODY_MAX_SEC = body0
chk(isinstance(e9, bf_engine.NetError) and e9.kind == "timeout" and t9 < 3.0,
    "종전 모드: 시도마다 max(timeout, HTTP_BODY_MAX_SEC=1초) 안에 timeout(종전 ≈6초)", (type(e9).__name__, getattr(e9, "kind", None), round(t9, 2)))
d9, e9, t9 = call(srv[5][1], timeout=1.0, retries=1, deadline=time.time() + 1.5, sem_timeout=1.5)
chk(isinstance(e9, bf_engine.NetError) and e9.kind == "timeout" and t9 < 3.0,
    "chunked: 0 청크 뒤 trailer 를 0.2초마다 = 하드 마감(1.5초) 안에 timeout(코덱스 ui904 · 종전 ≈6초 뒤 성공 반환)", (type(e9).__name__, getattr(e9, "kind", None), round(t9, 2), d9))
bf_engine.HTTP_BODY_MAX_SEC = 1.0
try:
    d9, e9, t9 = call(srv[6][1], timeout=0.5, retries=1)
finally:
    if body0 is None:
        del bf_engine.HTTP_BODY_MAX_SEC
    else:
        bf_engine.HTTP_BODY_MAX_SEC = body0
chk(isinstance(e9, bf_engine.NetError) and e9.kind == "timeout" and t9 < 3.0,
    "chunked trailer drip · 종전 모드 = max(timeout, HTTP_BODY_MAX_SEC=1초) 안에 timeout", (type(e9).__name__, getattr(e9, "kind", None), round(t9, 2)))
d9, e9, t9 = call(srv[7][1], timeout=1.0, retries=1, deadline=time.time() + 1.5, sem_timeout=1.5)
chk(isinstance(e9, bf_engine.NetError) and e9.kind == "timeout" and t9 < 3.0,
    "chunked: 청크 크기 줄(확장)을 한 바이트씩 = 하드 마감 안에 timeout", (type(e9).__name__, getattr(e9, "kind", None), round(t9, 2)))
d9, e9, t9 = call(srv[1][1], timeout=5.0, retries=1)
chk(e9 is None and d9 == {"ok": True, "n": 7} and threading.active_count() < 40, "정상 chunked(종전 모드) = 그대로 · 마감 타이머 스레드 남지 않음", (e9, threading.active_count()))
mx0 = bf_engine.HTTP_MAX_BYTES
bf_engine.HTTP_MAX_BYTES = 1000
try:
    d9, e9, t9 = call(srv[0][1], timeout=5.0, retries=1)
finally:
    bf_engine.HTTP_MAX_BYTES = mx0
chk(isinstance(e9, bf_engine.NetError) and e9.kind == "range" and "response size" in str(e9), "본문 상한 초과 = 종전 그대로(range · response size)", (type(e9).__name__, str(e9)[:100]))
for s9, _u in srv:
    try:
        s9.close()
    except OSError:
        pass
T.finish()
