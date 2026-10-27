#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402

CP = os.path.join(T.TMP, "config.json")
with open(CP, "w", encoding="utf-8") as f:
    json.dump({"wallets": [], "chains": {}}, f)
os.environ["TJ_CONFIG"] = CP
import paths  # noqa: E402

assert T.TMP in paths.STATE_DIR
import bf_engine  # noqa: E402
import leverage as L  # noqa: E402
import xchain_match as xm  # noqa: E402


def check(n, c, d=""):
    T.chk(bool(c), n, None if c else str(d)[:600])


print("[A] 구간 상한 문구")
e = bf_engine.classify_rpc_error({"code": -32602, "message": "block range too large, maximum of 100 blocks allowed"})
check("A1 'maximum of 100 blocks' = range · 상한 100", e.kind == "range" and e.cap == 100, (e.kind, e.cap))
e = bf_engine.classify_rpc_error({"code": -32602, "message": "Block range too large: maximum of 100 block"})
check("A2 단수 'block' 도 상한 100", e.kind == "range" and e.cap == 100, (e.kind, e.cap))
for msg9, cap9 in (("eth_getLogs is limited to a 500 range", 500), ("You can make eth_getLogs requests with up to a 10 block range", 10),
                   ("Block range too large for public access: maximum 1000 blocks", 1000), ("block range greater than 100 max", 100)):
    e = bf_engine.classify_rpc_error({"code": -32000, "message": msg9})
    check(f"A3 종전 문구 그대로 상한 {cap9}", e.kind == "range" and e.cap == cap9, (msg9, e.kind, e.cap))
e = bf_engine.classify_rpc_error({"code": -32011, "message": "request limit reached"})
check("A4 '-32011 request limit reached' = http429 · 냉각 정보 없음(종전 분류)", e.kind == "http429" and e.retry_after is None, (e.kind, e.retry_after))

print("[C] LogScanner — 429 청크 재배치 · 연속 완료 안 건너뜀 · 상한 학습")
EP = "https://scan-a.invalid/rpc"
LOGS = {150: "0x" + "a1" * 32, 350: "0x" + "a2" * 32, 520: "0x" + "a3" * 32}
STATE = {"calls": [], "rl_left": 2, "cap": None}


def fake_rpc_call(url, method, params, **kw):
    q = params[0]
    a, b = int(q["fromBlock"], 16), int(q["toBlock"], 16)
    STATE["calls"].append((a, b))
    if STATE["cap"] and b - a + 1 > STATE["cap"]:
        raise bf_engine.classify_rpc_error({"code": -32602, "message": f"block range too large, maximum of {STATE['cap']} blocks"})
    if a <= 350 <= b and STATE["rl_left"] > 0:
        STATE["rl_left"] -= 1
        raise bf_engine.classify_rpc_error({"code": -32011, "message": "request limit reached"})
    return [{"transactionHash": h, "blockNumber": hex(n)} for n, h in LOGS.items() if a <= n <= b]


_rc0, _sl0 = bf_engine.rpc_call, bf_engine.time.sleep
bf_engine.rpc_call = fake_rpc_call
bf_engine.time.sleep = lambda s: None
try:
    sc = bf_engine.LogScanner([EP], "0x" + "dd" * 32, ["0x" + "00" * 32], span=100, min_span=10, head_guard=False, positions={1: "0x" + "dd" * 32})
    found, last = sc.scan(0, 599)
    check("C1 429 두 번 받은 청크도 끝내 받음 — 연속 완료 = 끝 블록", last == 599, (last, sc.last_stop))
    check("C2 찾은 로그 3건 그대로(429 청크 안 로그 포함)", set(found) == set(LOGS.values()), found)
    check("C3 429 청크(300-399)를 3번 물음(재배치) · 다른 청크는 1번", STATE["calls"].count((300, 399)) == 3 and STATE["calls"].count((0, 99)) == 1, STATE["calls"])
    STATE.update(calls=[], rl_left=10 ** 6)
    sc = bf_engine.LogScanner([EP], "0x" + "dd" * 32, ["0x" + "00" * 32], span=100, min_span=10, head_guard=False, positions={1: "0x" + "dd" * 32})
    found, last = sc.scan(0, 599, deadline=time.time() + 0.5)
    check("C4 계속 429 + 마감 = 연속 완료는 그 청크 앞(299)에서 멈춤 — 뒤 청크를 받았어도 건너뛰지 않음", last == 299 and all(b <= 299 for b in found.values()), (last, found))
    STATE.update(calls=[], rl_left=0, cap=40)
    sc = bf_engine.LogScanner([EP], "0x" + "dd" * 32, ["0x" + "00" * 32], span=100, min_span=10, head_guard=False, positions={1: "0x" + "dd" * 32})
    found, last = sc.scan(0, 199)
    check("C5 '최대 40블록' = 노드 상한 40 그대로 배움(반감 없음) · 끝까지", sc.caps.get(EP) == 40 and last == 199 and sc.metrics["halved"] == 0
          and set(found) == {LOGS[150]}, (sc.caps, last, sc.metrics, found))
    check("C6 상한을 배운 뒤 넓은 창 거부는 1번뿐", sum(1 for a, b in STATE["calls"] if b - a + 1 > 40) == 1, STATE["calls"])
finally:
    bf_engine.rpc_call, bf_engine.time.sleep = _rc0, _sl0

print("[D] 역추적 getLogs — 노드 상한 기억")
xm._LOG_CAP.clear()
UA, UB = "https://cap-a.invalid/rpc", "https://cap-b.invalid/rpc"
CFG = {"wallets": [], "chains": {"zz": {"rpc_logs": [UA, UB]}}}
POSTS = []
BMODE = {"ok": True}


def fake_post(self, url, method, params, timeout=30):
    POSTS.append(url)
    q = params[0]
    n = int(q["toBlock"], 16) - int(q["fromBlock"], 16) + 1
    if url == UA and n > 100:
        raise bf_engine.NetError("{'code': -32602, 'message': 'block range too large, maximum of 100 blocks'}", "range", code=-32602, cap=100)
    if url == UB and not BMODE["ok"]:
        raise bf_engine.NetError("{'code': -32602, 'message': 'block range too large, maximum of 500 blocks'}", "range", code=-32602, cap=500)
    return [{"blockNumber": hex(int(q["fromBlock"], 16)), "transactionHash": "0x" + "b1" * 32}]


tr = xm.Tracer(CFG, {"inflows": {}, "outflows": {}}, None, {}, sleep=0)
_post0 = xm.Tracer._post
xm.Tracer._post = fake_post
try:
    P = [{"address": "0x" + "c0" * 20, "fromBlock": hex(1000), "toBlock": hex(2999), "topics": []}]
    r1 = tr._evm("zz", "eth_getLogs", P, logs=True)
    check("D1 첫 창 = A 거부(상한 배움) → B 답", POSTS == [UA, UB] and xm._LOG_CAP.get(UA) == 100 and r1, (POSTS, xm._LOG_CAP))
    POSTS.clear()
    r2 = tr._evm("zz", "eth_getLogs", P, logs=True)
    check("D2 같은 넓이 창 = A 안 물음(B 만) · 결과 같음", POSTS == [UB] and r2 == r1, (POSTS, r2))
    POSTS.clear()
    xm._LOG_CAP_AT[UA] -= xm.LOG_CAP_SEC + 1
    r_exp = tr._evm("zz", "eth_getLogs", P, logs=True)
    check("D2b 상한 기억 수명(LOG_CAP_SEC) 뒤 = 같은 넓이도 A 다시 확인(거부면 다시 배움) · 결과 같음",
          POSTS == [UA, UB] and r_exp == r1 and xm._LOG_CAP.get(UA) == 100, (POSTS, r_exp))
    POSTS.clear()
    tr._evm("zz", "eth_getLogs", P, logs=True)
    check("D2c 다시 배운 뒤 = 다시 A 안 물음", POSTS == [UB], POSTS)
    POSTS.clear()
    Pn = [dict(P[0], fromBlock=hex(1000), toBlock=hex(1099))]
    tr._evm("zz", "eth_getLogs", Pn, logs=True)
    check("D3 상한 안 창(100블록) = A 그대로 물음", POSTS == [UA], POSTS)
    POSTS.clear()
    BMODE["ok"] = False
    xm._LOG_CAP.clear()
    ex1 = ex2 = None
    try:
        tr._evm("zz", "eth_getLogs", P, logs=True)
    except RuntimeError as x:
        ex1 = x
    n1 = len(POSTS)
    try:
        tr._evm("zz", "eth_getLogs", P, logs=True)
    except RuntimeError as x:
        ex2 = x
    check("D4 전 노드 상한 밖 = 두 번째는 0콜 · 같은 '영구' 판정(종전 실패 판정 그대로)", n1 == 2 and len(POSTS) == 2 and ex1 is not None and ex2 is not None
          and xm._fail_class(ex1) == xm._fail_class(ex2) == "permanent", (POSTS, ex1, ex2))
    check("D5 기억 = 노드 URL 단위(호스트 문자열만 오류 문구에)", set(xm._LOG_CAP) == {UA, UB} and "cap-b.invalid" in str(ex2) and "https://" not in str(ex2), (xm._LOG_CAP, str(ex2)[:200]))
finally:
    xm.Tracer._post = _post0
    xm._LOG_CAP.clear()
_rp0, _nw0 = bf_engine.rpc_post, xm.netpace.wait
bf_engine.rpc_post = lambda url, body, **kw: {"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "block range too large, maximum of 100 blocks"}}
xm.netpace.wait = lambda url, **kw: None
try:
    tr2 = xm.Tracer({"wallets": [], "chains": {"zz": {"rpc_logs": [UA]}}}, {"inflows": {}, "outflows": {}}, None, {}, sleep=0)
    try:
        tr2._evm("zz", "eth_getLogs", P, logs=True)
    except RuntimeError:
        pass
    check("D6 HTTP 200 본문 '-32602 … maximum of 100 blocks' = 상한 100 배움", xm._LOG_CAP.get(UA) == 100, xm._LOG_CAP)
finally:
    bf_engine.rpc_post, xm.netpace.wait = _rp0, _nw0
    xm._LOG_CAP.clear()

print("[E] 역추적 GET — 블록스카웃 403 기억")
xm._DENY.clear()
xm.netpace._reset()
OPENED = []


def fake_urlopen(req, timeout=30):
    OPENED.append(req.full_url)
    raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b"cf"))


_uo0, _nw0 = xm.net_http.urlopen, xm.netpace.wait
xm.net_http.urlopen = fake_urlopen
xm.netpace.wait = lambda url, **kw: None
try:
    tr3 = xm.Tracer({"wallets": [], "chains": {}}, {"inflows": {}, "outflows": {}}, None, {}, sleep=0)
    BS = "https://zz.blockscout.invalid/api/v2/addresses/0x" + "c1" * 20 + "/token-transfers"
    got = []
    for _i in range(3):
        try:
            tr3._get(BS)
        except urllib.error.HTTPError as x:
            got.append((x.code, type(x).__name__))
    check("E1 블록스카웃 403 = 첫 1번만 보냄 · 뒤 2번은 같은 HTTPError 403(Denied)", len(OPENED) == 1 and [c for c, _n in got] == [403, 403, 403]
          and got[1][1] == "Denied", (OPENED, got))
    check("E2 보내지 않은 호출은 예산(calls) 안 씀", tr3.calls == 1, tr3.calls)
    OPENED.clear()
    WS = "https://api.wormholescan.invalid/api/v1/operations?txHash=0x" + "d1" * 32
    for _i in range(2):
        try:
            tr3._get(WS)
        except urllib.error.HTTPError:
            pass
    check("E3 브릿지 API 403 = 기억 안 함(tx 별 확정 판정 그대로 — 매번 보냄)", len(OPENED) == 2, OPENED)
    OPENED.clear()
    for k9 in list(xm._DENY):
        xm._DENY[k9] = time.time() - 1
    try:
        tr3._get(BS)
    except urllib.error.HTTPError:
        pass
    check("E4 6시간 지나면 다시 1번 보냄", len(OPENED) == 1 and xm.DENY_SEC == 6 * 3600, OPENED)
finally:
    xm.net_http.urlopen, xm.netpace.wait = _uo0, _nw0
    xm._DENY.clear()

print("[F] 레버리지 — 키 권한 없음 = 6시간")
NOW = 1_800_000_000
CALLED = []


def fut_noperm():
    CALLED.append(1)
    raise RuntimeError('HTTP 403: {"message":"Request API key does not have futures permission","label":"FORBIDDEN"}')


def fut_403():
    CALLED.append(1)
    raise RuntimeError("HTTP 403: Forbidden")


r = L.Run({}, NOW)
row = r.run("gate", "futures_linear", fut_noperm)
check("F1 '권한 없음' 문구 403 = no_permission · 6시간 뒤 재확인 · 사유 '키 권한 없음…'", row["status"] == "no_permission" and row["retry_at"] == NOW + 6 * 3600
      and row["note"].startswith("키 권한 없음") and "6시간" in row["note"], row)
doc = r.result()
for dt9, want in ((600, 0), (3600 + 600, 0), (6 * 3600 - 60, 0), (6 * 3600 + 1, 1)):
    CALLED.clear()
    r2 = L.Run(doc, NOW + dt9)
    row2 = r2.run("gate", "futures_linear", fut_noperm)
    check(f"F2 +{dt9}초 = 호출 {want}번", len(CALLED) == want and row2["status"] == "no_permission", (len(CALLED), row2))
CALLED.clear()
r = L.Run({}, NOW)
row = r.run("gate", "futures_linear", fut_403)
check("F3 문구 없는 403 = 종전 1시간(IP·WAF 일시 거부 복구)", row["status"] == "no_permission" and row["retry_at"] == NOW + 3600 and row["note"].startswith("키 권한 부족"), row)
r = L.Run(r.result(), NOW + 3601)
CALLED.clear()
row = r.run("gate", "futures_linear", lambda: [])
check("F4 권한을 켠 뒤 재확인 = ok 로 다시 켜짐", row["status"] == "ok", row)


def gate_noperm(path, params=None):
    raise RuntimeError('HTTP 403: {"message":"Request API key does not have unified permission","label":"FORBIDDEN"}')


doc = L.collect({"TJ_GATE_KEY": "k", "TJ_GATE_SECRET": "s"}, {"gate": {"get": gate_noperm}}, now=NOW, cycle_sec=600, fresh_sec=1800)
uni = [p for p in doc["products"] if p["ex"] == "gate" and p["product"] == "unified"][0]
check("F6 게이트 통합계정 키 권한 없음 = 6시간 메모 그대로(수집기의 1시간 안내로 덮지 않음)", uni["status"] == "no_permission" and uni["retry_at"] == NOW + 6 * 3600
      and uni["note"].startswith("키 권한 없음"), uni)
import lev_view  # noqa: E402

check("F5 화면 사유 = '키 권한 없음'(수집기 메모가 '키 권한'으로 시작 = 기본 문구)", lev_view.REASON_KO["no_permission"] == "키 권한 없음", lev_view.REASON_KO)

T.finish()
