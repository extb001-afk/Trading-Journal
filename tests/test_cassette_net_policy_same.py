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
import bf_engine  # noqa: E402
import net_http  # noqa: E402

NP.configure()
CAP = {e: net_http.HTTP_BODY_MAX for e in NP.ENTRIES}
CAP.update({"bfe": bf_engine.HTTP_MAX_BYTES, "bfe_key": bf_engine.HTTP_MAX_BYTES, "onboarding": 1 << 20})
OK_BODY = '{"ok":1}'
REDIR = (301, 302, 303, 307)
V6 = {e: "2606:4700:4700::10%02d" % i for i, e in enumerate(NP.ENTRIES, 1)}
V4 = {e: "9.9.9.%d" % (30 + i) for i, e in enumerate(NP.ENTRIES, 1)}


def host(e, s):
    return "%s-%s.policy.invalid" % (e.replace("_", "-"), s)


SCEN = ["r%d" % c for c in REDIR] + ["post302", "h429", "h503", "rtimeout", "refused", "cap", "private", "multi", "dnsflap"]
DNS = {}
EVENTS = {}
for e9 in NP.ENTRIES:
    DNS[host(e9, "multi")] = [V6[e9], V4[e9]]
    DNS[host(e9, "dnsflap")] = {"seq": [[], [V4[e9]]]}
    EVENTS["%s:443" % V6[e9]] = ["refused"]
    EVENTS[host(e9, "refused") + ":443"] = ["refused"]


def url(e, s):
    if s == "private":
        return "http://127.0.0.1:3002/%s/start" % e
    return "https://%s/start" % host(e, s)


HITS = {}


def respond(rq):
    k = rq.host + rq.path
    n = HITS[k] = HITS.get(k, 0) + 1
    seen = {"at": k, "m": rq.method, "n": n}
    if rq.host == "dst.policy.invalid" or rq.path.endswith("/next"):
        return seen
    s = rq.host.split(".")[0].split("-")[-1] if rq.host != "127.0.0.1" else "private"
    e = rq.host.split(".")[0].rsplit("-", 1)[0].replace("-", "_") if rq.host != "127.0.0.1" else rq.path.split("/")[1]
    if s.startswith("r") and s[1:].isdigit():
        return C.Reply("", status=int(s[1:]), headers={"Location": "https://dst.policy.invalid/%s/%s" % (e, s)})
    if s == "post302":
        return C.Reply("", status=302, headers={"Location": "https://dst.policy.invalid/%s/post302" % e})
    if s == "private":
        return C.Reply("", status=302, headers={"Location": "http://127.0.0.1:3002/%s/next" % e})
    if n == 1 and s == "h429":
        return C.Reply({"err": "rate"}, status=429, headers={"Retry-After": "1"})
    if n == 1 and s == "h503":
        return C.Reply({"err": "busy"}, status=503)
    if n == 1 and s == "rtimeout":
        return C.Reply(exc="timeout")
    if s == "cap":
        return C.Reply(json.loads(OK_BODY), pad=CAP[e] + 1 - len(OK_BODY))
    return seen


def run_all():
    out = {}
    for s in SCEN:
        for e in NP.ENTRIES:
            if s == "post302" and e not in NP.POST_OK:
                continue
            r = NP.summary(NP.call, e, url(e, s), post=(s == "post302"))
            out.setdefault(s, {})[e] = r
    return out


cas = C.Cassette("net_policy_same", secrets=NP.SECRETS, responder=respond, dns=DNS, conn_events=EVENTS, preserve=True)
if cas.ready(T):
    res, why = cas.run(run_all)
    T.chk(why is None, "시나리오 전부 끝까지(새 요청·틀 오류 없음)", why)
    res = res or {}
    n_case = sum(len(v) for v in res.values())
    T.chk(n_case == len(SCEN) * len(NP.ENTRIES) - (len(NP.ENTRIES) - len(NP.POST_OK)), "시나리오 × 입구 전부 결과 있음", n_case)
    fol = {e: (res.get("r302") or {}).get(e, {}) for e in NP.ENTRIES}
    T.chk(all("ret" in fol[e] for e in ("rabby", "bfe", "sol_open")) and all("ret" not in fol[e] or (fol[e]["ret"] or [None])[0] == 302
                                                                            for e in ("depaddr", "bfe_key", "onboarding")),
          "302: 비인증 입구 = 따라감 · 인증·키 헤더·연결 테스트 = 안 따라감", fol)
    prv = res.get("private") or {}
    T.chk(all("ret" in prv.get(e, {}) for e in ("rabby", "bfe", "sol_open")), "사설 출발 → 같은 사설 주소 리다이렉트 = 비인증 입구는 따라감", prv)
    cap = res.get("cap") or {}
    T.chk(all("exc" in cap.get(e, {}) for e in ("rabby", "depaddr", "bfe", "bfe_key", "sol_open")), "본문 상한+1 = 상한 있는 입구 전부 실패", cap)
    multi = res.get("multi") or {}
    T.chk(all("ret" in multi.get(e, {}) for e in NP.ENTRIES), "여러 주소: 첫 주소(IPv6) 거부 → 다음 주소로 성공(표준 순서)", multi)
    cas.golden(T, res)
    cas.check(T)
T.finish()
