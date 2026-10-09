#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as H

import json
import os
import time

import common
import alert_prefs as AP
import web


def check(name, ok, detail=""):
    H.chk(bool(ok), name, None if ok else str(detail)[:700])


class _Stop(BaseException):
    pass


class FakeBuilder:
    def __init__(self):
        self.out = None
        self.cfg = {}

    def prefs(self):
        return {"plans": {k: {"target": v["target"], "stop": v["stop"]} for k, v in self.out["fields"]["plans"].items()}}

    def latest(self, max_age):
        return self.out


FB = FakeBuilder()
web.BUILDER = FB


def run_once():
    n = [0]
    real = web.time.sleep

    def fake_sleep(sec):
        n[0] += 1
        if n[0] > 1:
            raise _Stop()

    web.time.sleep = fake_sleep
    try:
        web.plan_monitor_loop()
    except _Stop:
        pass
    finally:
        web.time.sleep = real


def alerts():
    p = web.ALERTS_PATH
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def reset():
    for p in (web.ALERTS_PATH, web.ALERTS_SENT_PATH):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass


def build(coin, built_ago=0.0):
    FB.out = {"builtAt": int(time.time() - built_ago),
              "fields": {"coins": [coin], "plans": {coin["key"]: {"target": 200.0, "stop": 90.0}}}}


reset()
build({"key": "g1", "sym": "ABC", "price": 80.0, "pxSrc": "dex:gecko", "pxAge": 3600})
run_once()
a = alerts()
kinds = [x["kind"] for x in a]
check("P1 pxAge 3600 코인이 손절선 아래 → 손절 알림 없음 · '감시 불가' 1통", kinds == ["PLAN_BLIND"] and "목표가·손절 감시를 못 하고 있어요" in a[0]["text"]
      and "약 1시간 전 값" in a[0]["text"], [(x["kind"], x["text"][:120]) for x in a])
run_once()
check("P1 … 같은 날 다시 돌아도 감시 불가 다시 0", [x["kind"] for x in alerts()] == ["PLAN_BLIND"], [x["kind"] for x in alerts()])
check("P1 '감시 불가' 종류 = 목표가·손절 카테고리(price)", AP.cat_of("PLAN_BLIND") == "price", AP.cat_of("PLAN_BLIND"))
reset()
build({"key": "g1", "sym": "ABC", "price": 80.0, "pxSrc": "dex:gecko", "pxAge": 30})
run_once()
check("P2 신선한 값(pxAge 30) → 손절 알림 1통(종전)", [x["kind"] for x in alerts()] == ["STOP_HIT"], [x["kind"] for x in alerts()])
reset()
build({"key": "g1", "sym": "ABC", "price": 80.0, "pxSrc": "cex:글로벌"})
run_once()
check("P2 나이 모름(pxAge 없음 — 글로벌 1분봉) → 종전대로 손절 알림", [x["kind"] for x in alerts()] == ["STOP_HIT"], [x["kind"] for x in alerts()])
reset()
build({"key": "g1", "sym": "ABC", "price": 250.0, "pxSrc": "dex:gecko", "pxAge": 10, "pxFrozen": True})
run_once()
a = alerts()
check("P3 멈춘 값(pxFrozen)이 목표가 위 → 목표가 알림 없음 · 감시 불가 1통('멈춘 값')", [x["kind"] for x in a] == ["PLAN_BLIND"] and "멈춘 값" in a[0]["text"],
      [(x["kind"], x["text"][:100]) for x in a])
reset()
build({"key": "g1", "sym": "ABC", "price": 80.0, "pxSrc": "dex:gecko", "pxAge": 400}, built_ago=300)
run_once()
check("P4 빌드 때 400초 + 빌드 뒤 300초 = 700초(> 10분) → 판정 건너뜀 · 30분 전이라 감시 불가도 아직 0(잠깐 늦은 시세)", not alerts(), [x["kind"] for x in alerts()])
reset()
build({"key": "g1", "sym": "ABC", "price": 80.0, "pxSrc": "dex:gecko", "pxAge": 1700}, built_ago=200)
run_once()
check("P4 … 1,700초 + 200초 = 1,900초(> 30분) → 감시 불가 1통", [x["kind"] for x in alerts()] == ["PLAN_BLIND"], [x["kind"] for x in alerts()])
reset()
build({"key": "g1", "sym": "ABC", "price": 80.0, "pxSrc": "dex:gecko", "pxAge": 333}, built_ago=60)
run_once()
check("P4 … 393초(10분 안 — 라이브 DEX 시세 나이 p90 333초) → 종전대로 손절 알림", [x["kind"] for x in alerts()] == ["STOP_HIT"], [x["kind"] for x in alerts()])
H.finish()
