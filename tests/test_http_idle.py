#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import socket  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import urllib.request  # noqa: E402

json.dump({"chains": {"base": {"blockscout": "https://bs.invalid", "conf_depth": 3, "rpcs": ["https://rpc.invalid"]}},
           "wallets": [{"type": "evm", "chain": "base", "address": "0x" + "a1" * 20, "label": "w"}]},
          open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
import bf_engine  # noqa: E402
import evm_watch  # noqa: E402

chk = T.chk
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def loop_open(req, timeout=None, *a, **k):
    u = getattr(req, "full_url", req)
    if "://127.0.0.1:" not in str(u):
        raise OSError("시험: 바깥 연결 차단")
    return _opener.open(req, timeout=timeout)


loop_open._tj_test_mock = True
bf_engine._open = loop_open
SERVERS = []
HOLD = 6.0


def server(handler):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 0))
    s.listen(16)

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
            head, _s, body = buf.partition(b"\r\n\r\n")
            ln = 0
            for line in head.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    ln = int(line.split(b":", 1)[1].strip() or 0)
            while len(body) < ln:
                d = c.recv(4096)
                if not d:
                    break
                body += d
            handler(c, body)
        except OSError:
            pass
        finally:
            try:
                c.close()
            except OSError:
                pass
    threading.Thread(target=loop, daemon=True).start()
    SERVERS.append(s)
    return "http://127.0.0.1:%d/x" % s.getsockname()[1]


def _hold(c):
    t0 = time.time()
    while time.time() - t0 < HOLD:
        time.sleep(0.05)


def stall_len(c, _b):
    c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n")
    _hold(c)


def stall_chunk_head(c, _b):
    c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n")
    _hold(c)


def stall_chunk_mid(c, _b):
    c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n1\r\n[\r\n")
    _hold(c)


def stall_500(c, _b):
    c.sendall(b"HTTP/1.1 500 Internal Server Error\r\nContent-Type: application/json\r\nContent-Length: 40\r\nConnection: close\r\n\r\n")
    _hold(c)


def err500(c, _b):
    body = b'{"error":"synthetic upstream failure"}'
    c.sendall(b"HTTP/1.1 500 Internal Server Error\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(body) + body)


DRIP_OK = b'{"ok": 1}       '


def drip_ok_len(c, _b):
    c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(DRIP_OK))
    for i in range(len(DRIP_OK)):
        c.sendall(DRIP_OK[i:i + 1])
        time.sleep(0.1)


def drip_ok_chunked(c, _b):
    c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n")
    for i in range(len(DRIP_OK)):
        c.sendall(b"1\r\n" + DRIP_OK[i:i + 1] + b"\r\n")
        time.sleep(0.1)
    c.sendall(b"0\r\n\r\n")


def drip_forever(c, _b):
    c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2000\r\nConnection: close\r\n\r\n")
    t0 = time.time()
    while time.time() - t0 < HOLD:
        c.sendall(b" ")
        time.sleep(0.1)


def drip_trailer(c, _b):
    c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n2\r\n{}\r\n0\r\n")
    t0 = time.time()
    while time.time() - t0 < HOLD:
        c.sendall(b"X-Pad: a\r\n")
        time.sleep(0.1)
    c.sendall(b"\r\n")


def ok_big(c, _b):
    body = json.dumps({"ok": True, "pad": "y" * 300_000}).encode()
    c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(body) + body)


def ok_chunk_ext(c, _b):
    c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
              b"5;name=v\r\n{\"a\":\r\n2\r\n7}\r\n0\r\nX-T: 1\r\n\r\n")


def ok_small(c, _b):
    body = b'{"ok": 2}'
    c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(body) + body)


def rpc_ok(c, b):
    try:
        req = json.loads(b.decode() or "[]")
    except ValueError:
        req = []
    out = [{"jsonrpc": "2.0", "id": x.get("id"), "result": "0x2a"} for x in (req if isinstance(req, list) else [req])]
    body = json.dumps(out).encode()
    c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(body) + body)


U = {f.__name__: server(f) for f in (stall_len, stall_chunk_head, stall_chunk_mid, stall_500, err500, drip_ok_len, drip_ok_chunked,
                                     drip_forever, drip_trailer, ok_big, ok_chunk_ext, ok_small, rpc_ok)}
BODY0 = bf_engine.HTTP_BODY_MAX_SEC


def call(url, body_max=2.5, **kw):
    bf_engine._GATES.clear()
    bf_engine.HTTP_BODY_MAX_SEC = body_max
    t0 = time.time()
    try:
        return bf_engine.http_request(url, **kw)[0], None, time.time() - t0
    except Exception as e:   # noqa: BLE001
        return None, e, time.time() - t0
    finally:
        bf_engine.HTTP_BODY_MAX_SEC = BODY0


def kind(e):
    return getattr(e, "kind", None)


def info(d, e, t):
    return (type(e).__name__ if e else None, kind(e), round(t, 2), d if e is None else str(e)[:80])


IDLE = 0.25
OK_T = 1.2

print("[1] 헤더 뒤 완전 정지 = 요청 idle timeout 안에 끝")
r = call(U["stall_len"], timeout=IDLE, retries=1)
chk(kind(r[1]) == "timeout" and r[2] < OK_T, "길이 있는 응답 · 헤더 뒤 정지 · 종전 모드 = idle 0.25초에 timeout(종전 = 절대 마감 2.5초)", info(*r))
r = call(U["stall_len"], timeout=IDLE, retries=1, deadline=time.time() + 2.0, sem_timeout=2.0)
chk(kind(r[1]) == "timeout" and r[2] < OK_T, "하드 마감(2초) > idle(0.25초) = idle 에 timeout(종전 = 하드 마감 2초)", info(*r))
r = call(U["stall_len"], timeout=2.0, retries=1, deadline=time.time() + 0.4, sem_timeout=0.4)
chk(kind(r[1]) in ("timeout", "budget") and r[2] < OK_T, "하드 마감(0.4초) < idle(2초) = 하드 마감에 끝", info(*r))
r = call(U["stall_chunk_head"], timeout=IDLE, retries=1)
chk(kind(r[1]) == "timeout" and r[2] < OK_T, "chunked · 헤더 뒤 정지(청크 크기 줄 없음) = idle 에 timeout(종전 = 마감 타이머 2.5초)", info(*r))
r = call(U["stall_chunk_mid"], timeout=IDLE, retries=1, deadline=time.time() + 2.0, sem_timeout=2.0)
chk(kind(r[1]) == "timeout" and r[2] < OK_T, "chunked · 첫 청크 뒤 정지 · 하드 마감 모드 = idle 에 timeout", info(*r))
r = call(U["stall_len"], timeout=IDLE, retries=2, max_inline_wait=0.0)
chk(kind(r[1]) == "timeout" and r[2] < OK_T, "재시도 있어도(백오프 대기 0 · 넘으면 중단) 시도마다 idle", info(*r))

print("[2] 진행 있는 drip = idle 을 넘겨도 계속 · 끝없으면 절대 마감")
r = call(U["drip_ok_len"], body_max=5.0, timeout=0.5, retries=1)
chk(r[1] is None and r[0] == {"ok": 1} and r[2] > 1.0, "길이 있는 응답을 0.1초마다 1바이트(1.6초) · idle 0.5초 = 끝까지 받아 성공", info(*r))
r = call(U["drip_ok_chunked"], body_max=5.0, timeout=0.5, retries=1, deadline=time.time() + 5.0, sem_timeout=5.0)
chk(r[1] is None and r[0] == {"ok": 1}, "chunked 1바이트 청크를 0.1초마다 · 하드 마감 모드 · idle 0.5초 = 성공", info(*r))
r = call(U["drip_forever"], body_max=1.5, timeout=0.5, retries=1)
chk(kind(r[1]) == "timeout" and 1.2 < r[2] < 3.5, "끝없는 drip(0.1초마다) · idle 0.5초 · 절대 1.5초 = 절대 마감에서 timeout(idle 로 안 끊음)", info(*r))
r = call(U["drip_trailer"], body_max=1.5, timeout=0.5, retries=1)
chk(kind(r[1]) == "timeout" and 1.2 < r[2] < 3.5, "chunked trailer drip(0.1초마다) = 마감 타이머(shutdown)로 절대 마감에서 timeout", info(*r))
r = call(U["drip_forever"], body_max=10.0, timeout=0.5, retries=1, deadline=time.time() + 1.5, sem_timeout=1.5)
chk(kind(r[1]) == "timeout" and 1.2 < r[2] < 3.5, "끝없는 drip · 하드 마감 1.5초 = 하드 마감에서 timeout", info(*r))

print("[3] HTTP 오류 본문")
r = call(U["stall_500"], timeout=IDLE, retries=1, retry_5xx=False)
chk(kind(r[1]) == "http5xx" and r[2] < OK_T, "HTTP 500 · 헤더 뒤 본문 정지 = idle 에 본문 포기하고 http5xx(종전 = 절대 마감 2.5초)", info(*r))
r = call(U["stall_500"], timeout=IDLE, retries=1, retry_5xx=False, deadline=time.time() + 2.0, sem_timeout=2.0)
chk(kind(r[1]) == "http5xx" and r[2] < OK_T, "HTTP 500 본문 정지 · 하드 마감 모드 = idle 에 http5xx", info(*r))
r = call(U["err500"], timeout=IDLE, retries=1, retry_5xx=False)
chk(kind(r[1]) == "http5xx" and "synthetic upstream failure" in str(r[1]), "정상 HTTP 500 본문 = 분류에 본문 앞부분 그대로", info(*r))

SET = []
SAVED = {k: getattr(bf_engine, k) for k in ("_rpc_day_of", "rpc_day_unit", "_rpc_day_units", "rpc_day_take", "rpc_day_settle", "_RPC_DAY")}
bf_engine._rpc_day_of = lambda h: "tb" if h == "127.0.0.1" else None
bf_engine.rpc_day_unit = lambda n: "bytes"
bf_engine._rpc_day_units = lambda n, m=None, c=1: 1 << 20
bf_engine.rpc_day_take = lambda n, h, u: 7
bf_engine.rpc_day_settle = lambda n, a, rr, d: SET.append((a, rr))
bf_engine._RPC_DAY = {"tb": {}}
try:
    r = call(U["stall_500"], timeout=IDLE, retries=1, retry_5xx=False, data=b"{}")
finally:
    for k9, v9 in SAVED.items():
        setattr(bf_engine, k9, v9)
chk(kind(r[1]) == "http5xx" and r[2] < OK_T and SET == [], "바이트 장부 노드 HTTP 500 본문 정지 = idle 에 http5xx · 받은 양 모름 → 예약 그대로(정산 안 함)", (info(*r), SET))

print("[4] 세마포어 포화 · 다음 노드")
bf_engine._POLICY_OVERRIDES["127.0.0.1"] = {"conc": 1, "rate": 1000, "burst": 1000}


def pair(kw_a, kw_b, url_b):
    bf_engine._GATES.clear()
    bf_engine.HTTP_BODY_MAX_SEC = 2.5
    res = {}

    def go(name, url, kw):
        t0 = time.time()
        try:
            res[name] = (bf_engine.http_request(url, **kw)[0], None, time.time() - t0)
        except Exception as e:   # noqa: BLE001
            res[name] = (None, e, time.time() - t0)
    try:
        ta = threading.Thread(target=go, args=("a", U["stall_len"], kw_a), daemon=True)
        ta.start()
        time.sleep(0.1)
        tb = threading.Thread(target=go, args=("b", url_b, kw_b), daemon=True)
        tb.start()
        ta.join(10)
        tb.join(10)
    finally:
        bf_engine.HTTP_BODY_MAX_SEC = BODY0
    g9 = bf_engine.gate("127.0.0.1")
    got = g9.sem.acquire(blocking=False)
    if got:
        g9.sem.release()
    return res.get("a", (None, None, -1)), res.get("b", (None, None, -1)), got


ra, rb, free = pair({"timeout": IDLE, "retries": 1}, {"timeout": 5.0, "retries": 1}, U["ok_small"])
chk(kind(ra[1]) == "timeout" and ra[2] < OK_T, "동시성 1 · 종전 모드: 정지 노드 A = idle 에 timeout", info(*ra))
chk(rb[1] is None and rb[0] == {"ok": 2} and rb[2] < OK_T, "동시성 1 · 뒤 요청 B = A 가 슬롯을 idle 만큼만 잡아 제때 성공(종전 ≈2.5초 대기)", info(*rb))
chk(free, "끝난 뒤 세마포어 회수(슬롯 비어 있음)")
ra, rb, free = pair({"timeout": IDLE, "retries": 1, "deadline": time.time() + 3.0, "sem_timeout": 3.0},
                    {"timeout": 1.0, "retries": 1, "deadline": time.time() + 1.0, "sem_timeout": 1.0}, U["ok_small"])
chk(kind(ra[1]) == "timeout" and ra[2] < OK_T, "동시성 1 · 하드 마감 모드: 정지 노드 A = idle 에 timeout(하드 마감 3초 아님)", info(*ra))
chk(rb[1] is None and rb[0] == {"ok": 2}, "하드 마감 모드 B(세마포어 대기 1초) = 슬롯 받아 성공(종전 = budget '동시 요청 대기 초과')", info(*rb))
chk(free, "하드 마감 모드도 끝난 뒤 세마포어 회수")
bf_engine._POLICY_OVERRIDES.pop("127.0.0.1", None)
bf_engine._GATES.clear()


class W(evm_watch.RpcChainWatcher):
    def _rpc_kw(self, cap):
        kw9 = super()._rpc_kw(cap)
        if kw9 is not None:
            kw9["timeout"] = min(float(kw9["timeout"]), IDLE)
        return kw9


w = W.__new__(W)
w.chain = "base"
w.chain_id = 8453
w.cfg_rpcs = [U["stall_len"], U["rpc_ok"]]
bf_engine.HTTP_BODY_MAX_SEC = 2.5
t0 = time.time()
try:
    out9, e9 = w._batch([("eth_blockNumber", []), ("eth_chainId", [])]), None
except Exception as e:   # noqa: BLE001
    out9, e9 = None, e
finally:
    bf_engine.HTTP_BODY_MAX_SEC = BODY0
t9 = time.time() - t0
chk(e9 is None and out9 == ["0x2a", "0x2a"] and t9 < OK_T, "노드 목록(evm_watch RpcChainWatcher._batch): 정지 노드 → idle 뒤 다음 노드 결과(종전 = 절대 마감 2.5초 뒤 이동)",
    (type(e9).__name__ if e9 else None, str(e9)[:120] if e9 else None, out9, round(t9, 2)))

print("[5] 정상 응답·소켓 timeout 복원")
r = call(U["ok_big"], timeout=IDLE, retries=1)
chk(r[1] is None and len((r[0] or {}).get("pad") or "") == 300_000, "정상 큰 JSON(300KB) = 그대로", info(r[0] and {"n": len(r[0].get("pad") or "")}, r[1], r[2]))
r = call(U["ok_chunk_ext"], timeout=IDLE, retries=1, deadline=time.time() + 3.0, sem_timeout=3.0)
chk(r[1] is None and r[0] == {"a": 7}, "chunked 확장·trailer 있는 정상 응답 = 그대로", info(*r))
with _opener.open(urllib.request.Request(U["ok_small"]), timeout=0.7) as r9:
    sk9 = bf_engine._resp_sock(r9)
    raw9 = bf_engine._read_capped(r9, 1000, time.time() + 5.0)
    to9 = sk9.gettimeout() if sk9 is not None else None
chk(raw9 == b'{"ok": 2}' and to9 is not None and abs(to9 - 0.7) < 1e-6, "_read_capped 뒤 소켓 timeout = 원래 값(0.7초)으로 복원", (raw9, to9))
bf_engine.HTTP_BODY_MAX_SEC = 2.5
t0 = time.time()
try:
    with _opener.open(urllib.request.Request(U["stall_len"]), timeout=IDLE) as r9:
        bf_engine._read_capped(r9, 10, time.time() + 2.5)
    e9 = None
except Exception as e:   # noqa: BLE001
    e9 = e
t9 = time.time() - t0
chk(isinstance(e9, socket.timeout) and t9 < OK_T, "idle 인자 없이 부른 _read_capped = 들어올 때 소켓 timeout(0.25초)을 idle 로", (type(e9).__name__, str(e9)[:60], round(t9, 2)))
time.sleep(0.2)
chk(not [t for t in threading.enumerate() if isinstance(t, threading.Timer) and t.is_alive()], "마감 타이머 스레드 남지 않음",
    [t.name for t in threading.enumerate()])
for s9 in SERVERS:
    try:
        s9.close()
    except OSError:
        pass
T.finish()
