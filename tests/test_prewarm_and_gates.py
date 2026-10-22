#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import logging  # noqa: E402
import os  # noqa: E402

os.environ["TJ_HEALTH"] = "0"
import config  # noqa: E402
import bf_engine  # noqa: E402
import review_daily as rd  # noqa: E402

chk = T.chk
TODAY = "2026-10-12"

items = [{"date": TODAY, "sym": "AAA", "vk": ["cex"]}, {"date": "2026-10-11", "sym": "BBB", "vk": ["cex"]}]
o1 = rd.prewarm_order(items, {}, TODAY)
chk(not any(r9[0] == TODAY for r9 in o1), "1 오늘 영수증 = 미리 받기 차례에서 뺌(다음 날부터 — 오늘 '다 받음'이 굳지 않게)", o1)
chk(sorted((r9[1], r9[2]) for r9 in o1) == [("BBB", "buy"), ("BBB", "sell")], "1 어제 영수증 = 그대로 매도·매수 둘 다", o1)
o1b = rd.prewarm_order(items, {}, "2026-10-13")
chk(any(r9[0] == TODAY and r9[1] == "AAA" for r9 in o1b), "1 다음 날 = 그 영수증 차례에 들어옴", o1b)

import web  # noqa: E402
import login_auth  # noqa: E402
import reqclass  # noqa: E402


class FH:
    _DAY_RE, _IV_OK, _AFTER_OK = web.Handler._DAY_RE, web.Handler._IV_OK, web.Handler._AFTER_OK
    _chart_args = web.Handler._chart_args

    def __init__(self, headers=None, peer="127.0.0.1"):
        self.headers = dict({"Host": "127.0.0.1:8023"}, **(headers or {}))
        self.client_address = (peer, 1)
        self.out = None

    def _send(self, code, body, *a, **k):
        self.out = (code, body)


class FB:

    def __init__(self):
        self.calls = []

    def snapshot(self):
        return None

    def chart_request(self, *a, **k):
        self.calls.append(bool(k.get("bg")))
        return None, "preparing"


def send(q, headers=None, peer="127.0.0.1"):
    old = web.BUILDER
    fb = web.BUILDER = FB()
    try:
        h = FH(headers, peer)
        r = T.safe(web.Handler._send_receipt_chart, h, q)
        return (h.out[0] if h.out else r), fb.calls
    finally:
        web.BUILDER = old


Q = "date=2026-10-11&sym=AAA"
S0 = login_auth.S
try:
    login_auth.S = login_auth.Settings({"enabled": True})
    tok = login_auth.internal_token(True)
    c1, k1 = send(Q + "&bg=1")
    chk(c1 == 403 and k1 == [], "2 로그인 켜짐 · 내부 토큰 없는 bg=1(로그인 세션) = 403 · 수집 시작 0", (c1, k1))
    c2, k2 = send(Q + "&bg=1", {login_auth.INTERNAL_HDR: tok})
    chk(c2 == 202 and k2 == [True], "2 같은 기기 내부 토큰(tj-review) bg=1 = 그대로(bg=True)", (c2, k2))
    c3, k3 = send(Q + "&bg=1", {login_auth.INTERNAL_HDR: tok, "Cf-Connecting-Ip": "203.0.113.9"})
    chk(c3 == 403 and k3 == [], "2 프록시(터널) 경유는 토큰이 있어도 bg=1 = 403", (c3, k3))
    c4, k4 = send(Q)
    chk(c4 == 202 and k4 == [False], "2 화면 요청(bg 없음) = 그대로", (c4, k4))
    login_auth.S = login_auth.Settings({"enabled": False})
    c5, k5 = send(Q + "&bg=1")
    chk(c5 == 202 and k5 == [True], "2 로그인 꺼짐 · 루프백 직접 bg=1 = 그대로", (c5, k5))
    c6, k6 = send(Q + "&bg=1", {"X-Forwarded-For": "203.0.113.9"})
    chk(c6 == 403 and k6 == [], "2 로그인 꺼짐 · 프록시 경유 bg=1 = 403", (c6, k6))
    login_auth.S = login_auth.Settings({"enabled": True})
    c7, k7 = send(Q + "&bg=1", {login_auth.INTERNAL_HDR: tok, "X-Forwarded-For": "127.0.0.1"})
    chk(c7 == 403 and k7 == [], "2 X-Forwarded-For 가 있으면 토큰 문자열만으로 내부 인정 안 함 = 403", (c7, k7))

    def keepalive(reqs):
        old9 = web.BUILDER
        fb = web.BUILDER = FB()
        out9 = []
        try:
            h = FH()
            for hd in reqs:
                h.headers = dict({"Host": "127.0.0.1:8023"}, **hd)
                h.out = None
                reqclass.mark_conn(h)
                T.safe(web.Handler._send_receipt_chart, h, Q + "&bg=1")
                out9.append(h.out[0] if h.out else None)
        finally:
            web.BUILDER = old9
        return out9, fb.calls
    o8, k8 = keepalive([{login_auth.INTERNAL_HDR: tok}, {}])
    chk(o8 == [202, 403] and k8 == [True], "2 keep-alive: 내부 토큰 요청 다음의 토큰 없는 요청 = 403(내부 표식 안 남음)", (o8, k8))
    o9, k9 = keepalive([{"Cf-Connecting-Ip": "203.0.113.9"}, {login_auth.INTERNAL_HDR: tok}])
    chk(o9 == [403, 403] and k9 == [], "2 keep-alive: 프록시 표식 본 연결의 다음 요청 = 토큰 있어도 403", (o9, k9))
    bp0 = reqclass.BEHIND_PROXY
    try:
        reqclass.BEHIND_PROXY = True
        c10, k10 = send(Q + "&bg=1", {login_auth.INTERNAL_HDR: tok})
        chk(c10 == 202 and k10 == [True], "2 behind_proxy 설치 · 루프백 내부 토큰(tj-review prewarm) = bg 유지", (c10, k10))
        c11, k11 = send(Q + "&bg=1")
        chk(c11 == 403 and k11 == [], "2 behind_proxy 설치 · 토큰 없음 = 403", (c11, k11))
    finally:
        reqclass.BEHIND_PROXY = bp0
    import onboarding  # noqa: E402
    dm0 = onboarding.DEMO
    try:
        onboarding.DEMO = True
        c12, k12 = send(Q + "&bg=1")
        chk(c12 == 202 and k12 == [True], "2 데모 = 종전 동작(bg 그대로)", (c12, k12))
    finally:
        onboarding.DEMO = dm0
finally:
    login_auth.S = S0

REC = []


class LH(logging.Handler):
    def emit(self, rec):
        if "비활성 체인" in rec.getMessage():
            REC.append(rec.getMessage())


lg = logging.getLogger("tj")
lh = LH()
lg.addHandler(lh)
lv0 = lg.level
lg.setLevel(logging.INFO)
try:
    def drop(names):
        cfg = {"chains": dict({n: {"enabled": False} for n in names}, ethereum={"enabled": True}), "wallets": []}
        config._drop_disabled_chains(cfg)
        return cfg

    c9 = drop(["zz1", "zz2"])
    n1 = len(REC)
    for _ in range(5):
        drop(["zz2", "zz1"])
    n2 = len(REC)
    drop(["zz1"])
    n3 = len(REC)
    chk(n1 == 1 and "zz1, zz2" in REC[0], "3 첫 번 = 한 줄 찍음", REC)
    chk(n2 == 1, "3 같은 목록 반복(1분마다 다시 읽기) = 더 안 찍음", REC)
    chk(n3 == 2, "3 목록이 바뀌면 = 다시 한 줄", REC)
    chk(c9.get("_disabled_chains") == ["zz1", "zz2"] and "zz1" not in c9["chains"], "3 설정에서 빼기·진단 표기는 그대로", c9)
finally:
    lg.removeHandler(lh)
    lg.setLevel(lv0)

p4 = bf_engine._policy_for("mainnet.base.org")
chk(p4.get("rate") == 0.5 and p4.get("burst") == 1 and p4.get("call_burst") == 10, "4 mainnet.base.org 기본 = 초당 0.5요청(버스트 1 · 배치 10 그대로)", p4)

T.finish()
