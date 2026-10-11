#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os

CFG = {"wallets": [{"type": "evm", "chain": "eth", "address": "0x" + "1f" * 20, "label": "시험"}],
       "chains": {"base": {"rpc_logs": ["https://pub-base.invalid"], "rpc_log_span_caps": {"https://pub-base.invalid": 5000}}},
       "bsc": {"logs_rpcs": ["https://pub-bsc.invalid"], "detail_rpcs": ["https://pub-bsc-detail.invalid"]}}
CP = os.path.join(T.TMP, "config.json")
with open(CP, "w", encoding="utf-8") as f:
    json.dump(CFG, f)
os.environ["TJ_CONFIG"] = CP
import common

assert T.TMP in common.STATE_DIR and T.TMP in common.ENV_PATH
import bf_engine
import nodekeys as NK
import onboarding
import settings_store as ss


def check(n, c, d=""):
    T.chk(bool(c), n, None if c else str(d)[:900])


TOK = "TESTqnMulti00000000000001"
ETH = f"https://fake-name.quiknode.pro/{TOK}/"
QB = "https://old-one.bsc.quiknode.pro/TESTqnOld0000000003/"
QBa = "https://old-two.base-mainnet.quiknode.pro/TESTqnOld0000000004/"

OK = [(ETH, "이더리움(네트워크 칸 없음)"), (f"https://fake-name.base-mainnet.quiknode.pro/{TOK}/", "Base 주소"),
      (f"https://Fake-Name.BSC.quiknode.pro/{TOK}", "대문자·끝 / 없음"), (f"wss://fake-name.quiknode.pro/{TOK}/", "wss"),
      (f"https://fake-name.avalanche-mainnet.quiknode.pro/{TOK}/ext/bc/C/rpc/", "토큰 뒤 경로(아발란체)"),
      (f"https://fake-name.quiknode.pro/{TOK}/?x=1#f", "질의·조각")]
for v, why in OK:
    check(f"Q1a 받음: {why}", NK.qn_parts(v) == ("fake-name", TOK), NK.qn_parts(v))
BAD = [(f"http://fake-name.quiknode.pro/{TOK}/", "http"), (f"https://u:p@fake-name.quiknode.pro/{TOK}/", "사용자 정보"),
       (f"https://fake-name.quiknode.pro:8443/{TOK}/", "포트"), (f"https://a.b.c.quiknode.pro/{TOK}/", "라벨 셋"),
       (f"https://fake-name.quiknode.pro.evil.invalid/{TOK}/", "호스트 끝이 quiknode.pro 아님"), ("https://quiknode.pro/" + TOK + "/", "이름 없음"),
       ("https://fake-name.quiknode.pro/short/", "토큰 짧음"), ("https://fake-name.quiknode.pro/tok-with-dash0000/", "토큰에 -"),
       ("https://fake-name.quiknode.pro/", "토큰 없음"), (f"https://-bad.quiknode.pro/{TOK}/", "이름 - 시작"), ("https://[::1", "깨진 주소"),
       ("", "빈 값"), (None, "None"), (12345, "숫자")]
for v, why in BAD:
    check(f"Q1b 거부: {why}", T.safe(NK.qn_parts, v) is None, T.safe(NK.qn_parts, v))

check("Q2a BSC = 이름.bsc.quiknode.pro/토큰/", NK.qn_chain_url(ETH, "bsc") == f"https://fake-name.bsc.quiknode.pro/{TOK}/", NK.qn_chain_url(ETH, "bsc"))
check("Q2b Base = 이름.base-mainnet.quiknode.pro/토큰/ (Base 주소를 넣어도 같은 모양)",
      NK.qn_chain_url(ETH, "base") == f"https://fake-name.base-mainnet.quiknode.pro/{TOK}/"
      and NK.qn_chain_url(f"https://fake-name.bsc.quiknode.pro/{TOK}/", "base") == NK.qn_chain_url(ETH, "base"))
check("Q2c 모르는 체인·형식 이상 = ''", NK.qn_chain_url(ETH, "eth") == "" and NK.qn_chain_url("https://x.invalid/", "bsc") == "")

us = NK.urls({NK.ENV_QN: ETH})
check("Q3a 멀티체인 칸 하나 = BSC·Base 둘 다 QuickNode", us == {"bsc": [("quicknode", NK.qn_chain_url(ETH, "bsc"))],
                                                       "base": [("quicknode", NK.qn_chain_url(ETH, "base"))]}, us)
us2 = NK.urls({NK.ENV_QN: ETH, NK.ENV_QN_BSC: QB, NK.ENV_QN_BASE: QBa})
check("Q3b 멀티체인 칸이 있으면 옛 체인별 칸 안 읽음", us2 == us, us2)
us3 = NK.urls({NK.ENV_QN_BSC: QB, NK.ENV_QN_BASE: QBa})
check("Q3c 멀티체인 칸 없음 = 옛 체인별 칸(옛 설치본)", [u for _p, u in us3["bsc"]] == [QB] and [u for _p, u in us3["base"]] == [QBa], us3)
us4 = NK.urls({NK.ENV_QN: "  ", NK.ENV_QN_BSC: QB})
check("Q3d 멀티체인 칸이 공백뿐 = 없음 취급(옛 칸)", [u for _p, u in us4["bsc"]] == [QB], us4)
cfg = json.loads(json.dumps(CFG))
done = NK.apply(cfg, env={NK.ENV_QN: ETH}, settings={})
cb = cfg["chains"]["base"]
QBASE, QBSC = NK.qn_chain_url(ETH, "base"), NK.qn_chain_url(ETH, "bsc")
check("Q3e apply(qn2) = 로그 풀엔 안 붙임(BSC·Base · getLogs 안 씀) · 상태(archive) 풀 뒤 예비(BSC·Base) · Base trace = QuickNode 하나만",
      done == {"bsc": ["quicknode"], "base": ["quicknode"], "base_trace": ["quicknode"]}
      and QBASE not in cb["rpc_logs"] and QBASE not in cb["rpc_log_span_caps"] and cb["archive_rpcs"][-1] == QBASE
      and QBSC not in cfg["bsc"]["logs_rpcs"] and QBSC not in (cfg["bsc"].get("getlogs_span_caps") or {}) and cfg["bsc"]["archive_rpcs"][-1] == QBSC
      and cb["trace_rpcs"] == [QBASE], (done, cb, cfg["bsc"]))
cfgt = json.loads(json.dumps(CFG))
cfgt["chains"]["base"]["trace_rpcs"] = ["https://my-trace.invalid"]
NK.apply(cfgt, env={NK.ENV_QN: ETH}, settings={})
check("Q3e2 이용자가 config 에 trace_rpcs 를 적었으면 그 앞에 QuickNode 만 끼움", cfgt["chains"]["base"]["trace_rpcs"] == [QBASE, "https://my-trace.invalid"],
      cfgt["chains"]["base"]["trace_rpcs"])
cfgn = json.loads(json.dumps(CFG))
NK.apply(cfgn, env={}, settings={})
check("Q3e3 키 없음 = trace_rpcs 안 만듦(내장 drpc 그대로)", "trace_rpcs" not in cfgn["chains"]["base"], cfgn["chains"]["base"])
import evm_watch
nd = evm_watch.rpc_nodes(cfg, "base")
check("Q3e4 수집기 노드 해석: trace = QuickNode 하나 · 로그 = QuickNode 없음 · 상태 = 뒤 예비", nd["trace"] == [QBASE] and QBASE not in nd["logs"]
      and QBASE in nd["state"], nd)
bf_engine.rpc_day_configure({"rpc_day_limits": cfg["rpc_day_limits"]})
check("Q3f 만든 주소는 하루 장부 node_quicknode 로 계량", bf_engine._rpc_day_of("fake-name.base-mainnet.quiknode.pro") == "node_quicknode")

pl = NK.plans({})["quicknode"]
sp = NK.budget_spec("quicknode", pl)
check("Q4a 기본 = 무료 · 월 1,000만 × 80% · 버스트 · 유료 기본 비율 80", pl["plan"] == "free" and pl["share"] == 80 and sp["month"] == 10_000_000
      and sp["pct"] == 80.0 and sp.get("burst") == float(NK.BURST_X), (pl, sp))
pl2 = NK.plans({"node_plans": {"quicknode": {"plan": "paid"}}})["quicknode"]
sp2 = NK.budget_spec("quicknode", pl2)
check("Q4b 유료 · 비율 안 고름 = 80% · 버스트 없음", pl2 == {"plan": "paid", "share": 80, "month": None} and sp2["pct"] == 80.0 and "burst" not in sp2, (pl2, sp2))
pl3 = NK.plans({"node_plans": {"quicknode": {"plan": "paid", "share": 25, "month": 80_000_000}}})["quicknode"]
sp3 = NK.budget_spec("quicknode", pl3)
check("Q4c 유료 비율 25 · 월 8,000만 = 그 값", sp3["pct"] == 25.0 and sp3["month"] == 80_000_000, sp3)
check("Q4d 다른 서비스 유료 기본 비율은 10 그대로", NK.plans({"node_plans": {"ankr": {"plan": "paid"}}})["ankr"]["share"] == 10)
cfgf = json.loads(json.dumps(CFG))
NK.apply(cfgf, env={NK.ENV_QN: ETH}, settings={})
bf_engine.configure(cfgf)
pf = bf_engine._policy_for("fake-name.base-mainnet.quiknode.pro")
check("Q4f 무료 QuickNode 초당 = 콜 6+6 · 공유 6+6(프로세스 합산 유지 · 장부 node_quicknode)",
      pf["call_rate"] == 6.0 and pf["call_burst"] == 6 and pf["share_rate"] == 6.0 and pf["share_burst"] == 6 and pf.get("share") == "node_quicknode"
      and pf.get("share_xproc") is True and pf["call_burst"] + pf["call_rate"] <= 15 * 0.8, pf)
cfgp = json.loads(json.dumps(CFG))
NK.apply(cfgp, env={NK.ENV_QN: ETH}, settings={"node_plans": {"quicknode": {"plan": "paid"}}})
bf_engine.configure(cfgp)
pp = bf_engine._policy_for("fake-name.bsc.quiknode.pro")
check("Q4g 유료 QuickNode = 내장 정책(10+10) 그대로 · config 에 덮어쓰기 없음",
      pp["call_rate"] == 10.0 and pp["share_burst"] == 10 and "*.quiknode.pro" not in ((cfgp.get("backfill") or {}).get("hosts") or {}), pp)
cfgu = json.loads(json.dumps(CFG))
cfgu["backfill"] = {"hosts": {"*.quiknode.pro": {"call_rate": 3.0}}}
NK.apply(cfgu, env={NK.ENV_QN: ETH}, settings={})
check("Q4h 이용자가 config 에 쓴 QuickNode 정책 우선", cfgu["backfill"]["hosts"]["*.quiknode.pro"] == {"call_rate": 3.0}, cfgu["backfill"])
bf_engine.configure({})
st = NK.status(env={NK.ENV_QN: ETH}, settings={})
check("Q4e 화면 상태 = 유료만 아님 · 쓰는 체인 BSC·Base · 키·주소 없음", st["quicknode"]["paidOnly"] is False and st["quicknode"]["chains"] == ["bsc", "base"]
      and TOK not in json.dumps(st) and "quiknode.pro" not in json.dumps(st), st["quicknode"])

if os.path.exists(common.ENV_PATH):
    os.remove(common.ENV_PATH)
fp0 = NK.fingerprint()
ss.write_env({NK.ENV_QN: ETH})
fp1 = NK.fingerprint()
check("Q5a 멀티체인 칸 넣으면 지문 바뀜(수집기 재시작)", fp0 != fp1, (fp0, fp1))
os.environ[NK.ENV_QN] = ""
try:
    ss.write_env({NK.ENV_QN: None})
    check("Q5b 칸 지우면(빈 값) 종전 지문 그대로(불필요한 재시작 없음)", NK.fingerprint() == fp0)
finally:
    os.environ.pop(NK.ENV_QN, None)

CALLS = []


def rpc_ok(u, m, p, timeout=15.0):
    CALLS.append((u, m))
    return "0x10"


def rpc_rej_on(sub, code=401):
    def f(u, m, p, timeout=15.0):
        CALLS.append((u, m))
        if sub in u:
            raise bf_engine.NetError("시험 오류", "http4xx", code=code)
        return "0x10"
    return f


real = onboarding._node_rpc
try:
    r = onboarding._dispatch("keys/save", {"group": "quicknode", "values": {NK.ENV_QN: "https://fake-name.quiknode.pro/bad/"}})
    check("Q6a 형식 이상 = 저장 안 함 · 값은 응답에 없음", r.get("ok") is False and "bad/" not in json.dumps(r, ensure_ascii=False)
          and not ss.read_env().get(NK.ENV_QN), r)
    ss.write_env({NK.ENV_QN_BSC: QB, NK.ENV_QN_BASE: QBa})
    CALLS.clear()
    onboarding._node_rpc = rpc_ok
    r = onboarding._dispatch("keys/save", {"group": "quicknode", "values": {NK.ENV_QN: ETH}})
    e6 = ss.read_env()
    check("Q6b 정상 = 저장 · Base 1콜(만든 주소 — qn2 쓰는 곳) · 옛 체인별 칸 지움",
          r.get("ok") is True and not r.get("note") and e6.get(NK.ENV_QN) == ETH and not e6.get(NK.ENV_QN_BSC) and not e6.get(NK.ENV_QN_BASE)
          and [u for u, _m in CALLS] == [NK.qn_chain_url(ETH, "base")], (r, CALLS))
    CALLS.clear()
    onboarding._node_rpc = rpc_rej_on(".base-mainnet.", 401)
    ss.write_env({NK.ENV_QN: None})
    r = onboarding._dispatch("keys/save", {"group": "quicknode", "values": {NK.ENV_QN: ETH}})
    check("Q6c Base 거부(401) = 저장 안 함 · 키 없음", r.get("ok") is False and not ss.read_env().get(NK.ENV_QN)
          and TOK not in json.dumps(r, ensure_ascii=False) and len(CALLS) == 1, (r, CALLS))
    CALLS.clear()

    def rpc_conn(u, m, p, timeout=15.0):
        CALLS.append((u, m))
        raise bf_engine.NetError("시험 오류", "conn")
    onboarding._node_rpc = rpc_conn
    r = onboarding._dispatch("keys/save", {"group": "quicknode", "values": {NK.ENV_QN: ETH}})
    check("Q6d 연결 실패 = 저장 + 경고", r.get("ok") is True and ss.read_env().get(NK.ENV_QN) == ETH and r.get("note"), (r, CALLS))
    ss.write_env({NK.ENV_QN: ETH, NK.ENV_QN_BSC: QB})
    r = onboarding._dispatch("keys/delete", {"group": "quicknode"})
    e6 = ss.read_env()
    check("Q6e 삭제 = 새 칸 + 옛 칸 같이", r.get("ok") is True and not e6.get(NK.ENV_QN) and not e6.get(NK.ENV_QN_BSC), e6)
    r = onboarding._dispatch("keys/nodeplan", {"provider": "quicknode", "plan": "free", "share": 80})
    check("Q6f 요금제 무료 저장 = 받음(종전 '유료만' 거부 없음)", r.get("ok") is True and NK.plans()["quicknode"]["plan"] == "free", r)
    r = onboarding._dispatch("keys/nodeplan", {"provider": "quicknode", "plan": "paid", "share": 50})
    check("Q6g 유료 비율 50 저장", r.get("ok") is True and NK.plans()["quicknode"] == {"plan": "paid", "share": 50, "month": None}, r)
    ss.write_env({NK.ENV_QN_BASE: QBa})
    env9 = ss.read_env()

    def grp9(g):
        fields = [{"key": k, "set": bool(env9.get(k))} for k, _l in g["fields"]]
        return {"name": g["name"], "set": all(x["set"] for x in fields),
                "partial": any(x["set"] for x in fields) or any(bool(env9.get(k)) for k in g.get("legacy", ())), "fields": fields}
    ex9 = onboarding._explorers_status(grp9)
    check("Q6h 옛 체인별 칸만 있음 = '저장됨'(설정 화면 grp 와 같은 규칙)", ex9["quicknode"]["set"] is True, ex9.get("quicknode"))
    src9 = open(os.path.join(T.SRC, "onboarding.py"), encoding="utf-8").read()
    check("Q6i 설정 화면 grp 가 legacy 칸을 봄(소스)", 'g.get("legacy", ())' in src9)
    ss.write_env({NK.ENV_QN_BASE: None})
    CALLS.clear()

    TXH = "0x" + "ab" * 32

    def rpc_test(u, m, p, timeout=15.0, trace_ok=True):
        CALLS.append((u, m))
        if m == "eth_chainId":
            return hex(8453)
        if m == "eth_blockNumber":
            return hex(50_000_000)
        if m == "eth_getBlockByNumber":
            return {"number": p[0], "transactions": [TXH]}
        if m == "debug_traceTransaction":
            if not trace_ok:
                raise bf_engine.NetError("시험 오류", "http4xx", code=403)
            return {"type": "CALL", "from": "0x" + "11" * 20, "to": "0x" + "22" * 20}
        return "0x0"
    onboarding._node_rpc = rpc_test
    r = onboarding._node_test("quicknode", {NK.ENV_QN: ETH})
    hosts = sorted({u.split("/")[2] for u, _m in CALLS})
    check("Q7a 연결 테스트(qn2) = 쓰는 곳 Base 만 4콜(체인 번호·최신 블록·블록·trace) · trace 됨", r.get("ok") and r["test"]["ok"] and r["test"]["results"][0].get("trace") is True
          and [m for _u, m in CALLS] == ["eth_chainId", "eth_blockNumber", "eth_getBlockByNumber", "debug_traceTransaction"]
          and hosts == ["fake-name.base-mainnet.quiknode.pro"] and TOK not in json.dumps(r, ensure_ascii=False), (r, CALLS))
    CALLS.clear()
    onboarding._node_rpc = lambda u, m, p, timeout=15.0: rpc_test(u, m, p, timeout, trace_ok=False)
    r = onboarding._node_test("quicknode", {NK.ENV_QN: ETH})
    check("Q7b trace 거절 = 테스트 실패 표시(분류만 · 키 없음)", r.get("ok") and r["test"]["ok"] is False and "실패" in r["test"]["detail"]
          and TOK not in json.dumps(r, ensure_ascii=False), r)
    CALLS.clear()
    onboarding._node_rpc = lambda u, m, p, timeout=15.0: (CALLS.append((u, m)), hex(1))[1]
    r = onboarding._node_test("quicknode", {NK.ENV_QN: ETH})
    check("Q7c 다른 체인 주소(체인 번호 1) = 실패 1콜", r["test"]["ok"] is False and "8453" in r["test"]["detail"] and len(CALLS) == 1, (r, CALLS))
finally:
    onboarding._node_rpc = real

root = os.path.abspath(os.path.join(T.HERE, ".."))
envx = open(os.path.join(root, ".env.example"), encoding="utf-8").read()
check("Q8a .env.example = TJ_QUICKNODE_KEY 한 칸(옛 칸 줄 없음)", "\nTJ_QUICKNODE_KEY=" in envx and "\nTJ_QUICKNODE_BSC_KEY=" not in envx)
js = open(os.path.join(T.ROOT, "web", "v2", "setup.js"), encoding="utf-8").read()
check("Q8b 화면 안내 = 멀티체인 · 무료 플랜 · 기본 80%", "멀티체인" in js and "무료 플랜도 돼요" in js and "기본 80%" in js and "유료만(무료 등급 없음)" not in js)
check("Q8c 설정 칸 = 멀티체인 한 칸", [k for k, _l in ss.GROUPS["quicknode"]["fields"]] == [NK.ENV_QN])

T.finish()
