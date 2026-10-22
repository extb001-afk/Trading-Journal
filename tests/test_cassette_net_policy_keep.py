#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _cassette as C  # noqa: E402

C.freeze()
import json  # noqa: E402
import os  # noqa: E402

import _net_policy as NP  # noqa: E402

with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump({"chains": {}, "wallets": []}, f)
import recon  # noqa: E402

NP.configure()
ENTS = ("rabby", "bfe", "sol_open")
V6 = {e: "2606:4700:4700::20%02d" % i for i, e in enumerate(ENTS, 1)}
V4 = {e: "9.9.9.%d" % (80 + i) for i, e in enumerate(ENTS, 1)}
DNS, EVENTS = {}, {}
for e9 in ENTS + ("gj",):
    h9 = e9.replace("_", "-")
    v4 = V4.get(e9, "9.9.9.90")
    if e9 != "gj":
        DNS["two-%s.policy.invalid" % h9] = [V6[e9], v4]
        EVENTS["%s:443" % V6[e9]] = ["refused"]
    DNS["flap1-%s.policy.invalid" % h9] = {"seq": [[], [v4]]}
DNS["flap4-gj.policy.invalid"] = {"seq": [[], [], [], [], ["9.9.9.91"]]}


def respond(rq):
    if rq.path != "/start":
        return {"at": rq.host + rq.path, "m": rq.method}
    lab = rq.host.split(".")[0]
    e, s = lab.rsplit("-", 1)
    dst = {"multi": "two", "flap1": "flap1", "flap4": "flap4"}[s]
    return C.Reply("", status=302, headers={"Location": "https://%s-%s.policy.invalid/t" % (dst, e)})


def start(e, s):
    return "https://%s-%s.policy.invalid/start" % (e.replace("_", "-"), s)


def run_all():
    out = {}
    for s in ("multi", "flap1"):
        for e in ENTS:
            out.setdefault(s, {})[e] = NP.summary(NP.call, e, start(e, s))
    out["flap1"]["recon_gj"] = NP.summary(recon._gj, start("gj", "flap1"), timeout=7, sleep=lambda _s: None)
    out["gj5"] = NP.summary(recon._gj, start("gj", "flap4"), timeout=7, sleep=lambda _s: None)
    return out


cas = C.Cassette("net_policy_keep", secrets=NP.SECRETS, responder=respond, dns=DNS, conn_events=EVENTS, preserve=True)
if cas.ready(T):
    res, why = cas.run(run_all)
    T.chk(why is None, "시나리오 전부 끝까지(새 요청·틀 오류 없음)", why)
    res = res or {}
    mu = res.get("multi") or {}
    T.chk(all("ret" in mu.get(e, {}) for e in ENTS), "multi: 공인 출발 → 주소 2개 공인 이름(첫째 거부) = 리다이렉트 성공", mu)
    for e in ENTS:
        lab9 = "two-%s.policy.invalid:443" % e.replace("_", "-")
        T.chk([c9[1:] for c9 in cas.conn_log if c9[0] == lab9] == [["refused", V6[e]], ["ok", V4[e]]],
              "multi %s: 목적지 연결 시도 2(IPv6 거부 → IPv4 · 표준 순서)" % e, [c9 for c9 in cas.conn_log if c9[0] == lab9])
    fl = res.get("flap1") or {}
    T.chk("ret" in fl.get("bfe", {}) and "ret" in fl.get("recon_gj", {}), "flap1: 목적지 조회 일시 실패 → bf_engine.http_request·recon._gj 재시도 뒤 성공",
          fl)
    T.chk(all(fl.get(e, {}).get("exc") == "URLError(gaierror)" for e in ("rabby", "sol_open")),
          "flap1: 재시도 없는 입구(rabby·sol_open) = URLError(gaierror)(조회 실패 = URLError(원래 예외))", fl)
    g5 = res.get("gj5") or {}
    T.chk(g5.get("exc") == "HTTPError" and g5.get("code") == 302 and cas.lookups["name"].get("flap4-gj.policy.invalid") == 4,
          "gj5: recon._gj 같은 Request 5번 · 목적지 조회 4번 실패 → 5번째 HTTPError 302(리다이렉트 계수)", [g5, cas.lookups["name"]])
    nm9 = cas.lookups["name"]
    T.chk(all(nm9.get("two-%s.policy.invalid" % e.replace("_", "-")) == 1 for e in ENTS)
          and nm9.get("flap1-bfe.policy.invalid") == 2 and nm9.get("flap1-gj.policy.invalid") == 2,
          "목적지 이름 조회 = 연결마다 1번(판정 뒤 다시 조회 0)", nm9)
    cas.golden(T, res)
    cas.check(T)
T.finish()
