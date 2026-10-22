#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import time  # noqa: E402
import urllib.error  # noqa: E402

import bf_engine  # noqa: E402
import candles  # noqa: E402,F401
import pricing  # noqa: E402

chk = T.chk
HOST = "api.geckoterminal.com"
CA = "0x" + "a" * 40
SENT = []
MODE = ["ok"]
_sleep = pricing.time.sleep


def fake_gj(url, timeout=10.0):
    SENT.append(url)
    if MODE[0] == "429":
        raise urllib.error.HTTPError(url, 429, "Too Many", {"Retry-After": "90"}, None)
    if MODE[0] == "404":
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
    return {"data": {"attributes": {"token_prices": {CA: "1.5"}, "total_reserve_in_usd": {CA: "50000"}}}}


fake_gj._tj_test_mock = True
pricing._gj = fake_gj


def nosleep(s):
    return None


def reset_gate():
    g = bf_engine.gate(HOST)
    with g.lock:
        g.pause_until = 0.0
        g.open_until = 0.0
        g.tokens = g.burst
    if g.share is not None:
        import os
        import paths
        try:
            os.remove(os.path.join(paths.quota_dir(), "rpc_gap", "gt_free.bucket"))
        except OSError:
            pass
    return g


pricing.time.sleep = nosleep
reset_gate()
MODE[0] = "429"
pricing.gt_token_prices_ex("eth", [CA], keyed=False)
e1 = pricing.gt_take_error()
w1 = bf_engine.gate_wait(HOST)
chk(e1 and e1[0] == "rate" and e1[1] == 429 and w1 >= 60, "G1 가격 조회 429 = 같은 호스트 게이트 쉼(차트가 보는 대기 ≥ 60초)", (e1, round(w1, 1)))

g = reset_gate()
with g.lock:
    g.pause_until = time.time() + 120
MODE[0] = "ok"
del SENT[:]
pricing.time.sleep = _sleep
t9 = time.time()
got = pricing.gt_token_prices_ex("eth", [CA], keyed=False)
e2 = pricing.gt_take_error()
pricing.time.sleep = nosleep
chk(not SENT and got == ({}, {}) and e2 and e2[0] == "rate" and e2[1] == "gate", "G2 게이트 쉼 중 = 보내지 않고 '한도'(rate · 사유 코드 gate — 진짜 429 와 따로 셈)",
    (len(SENT), got, e2))
chk(time.time() - t9 < 20, "G2 게이트 대기 상한 안에서 돌아옴(Spot tick 을 오래 안 잡음)", round(time.time() - t9, 1))

reset_gate()
del SENT[:]
got = pricing.gt_token_prices_ex("eth", [CA], keyed=False)
chk(got == ({CA: 1.5}, {CA: 50000.0}) and len(SENT) == 1 and pricing.gt_take_error() is None, "G3 평소 = 값·유동성 그대로", got)
g = reset_gate()
MODE[0] = "404"
pricing.gt_token_prices_ex("eth", [CA], keyed=False)
e3 = pricing.gt_take_error()
chk(e3 and e3[0] == "http" and e3[1] == 404 and bf_engine.gate_wait(HOST) < 10, "G3 404 = 종전(쉼 없음)", (e3, bf_engine.gate_wait(HOST)))

pol = bf_engine.HOST_POLICIES.get(HOST) or {}
g = reset_gate()
chk(bool(pol.get("share_xproc")) and isinstance(g.share, bf_engine._XprocSharedBucket), "G4 게코터미널 정책 = 프로세스 간 공유 버킷", pol)
if isinstance(g.share, bf_engine._XprocSharedBucket):
    other = bf_engine._XprocSharedBucket(g.share.name, g.share.rate, g.share.burst)
    a = g.share.try_take(1)
    b = other.try_take(1)
    chk(a == 0 and b > 0, "G4 한쪽이 쓴 몫을 다른 프로세스가 본다(기다려야 함)", (a, b))

import web  # noqa: E402
sp = web.Spot()
g = reset_gate()
with g.lock:
    g.pause_until = time.time() + 120
MODE[0] = "ok"
pricing.time.sleep = _sleep
sp.token_pairs = {("eth", CA)}
sp._gt_backoff_until = 0
sp._gt_next_at = 0
sp._gt_round(time.time())
pricing.time.sleep = nosleep
chk(("eth", CA) not in sp._gt_done and sp._gt_backoff_until > time.time(),
    "G5 게이트 쉼 중 Spot = 묶음 완료 아님(pending) · 쉼 설정", (sorted(sp._gt_done), sp._gt_backoff_until - time.time()))
chk(sp._gt_tries.get(("eth", CA), 0) == 1 and sp._gt_polled.get("eth:" + CA, 0) == 0,
    "G5 진짜 429 와 같은 규칙(빈 응답 1회 · 묶음을 뒤로 안 돌림)", (sp._gt_tries, sp._gt_polled.get("eth:" + CA)))

T.finish()
