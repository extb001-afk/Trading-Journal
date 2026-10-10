#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os

for _k in ("TJ_NODEREAL_KEY", "TJ_ANKR_KEY", "TJ_QUICKNODE_BSC_KEY", "TJ_QUICKNODE_BASE_KEY"):
    os.environ.pop(_k, None)
CFG = {"wallets": [{"type": "evm", "chain": "eth", "address": "0x" + "1f" * 20, "label": "시험"}],
       "chains": {"base": {"rpc_logs": ["https://pub-base.invalid"], "rpc_log_span_caps": {"https://pub-base.invalid": 5000}},
                  "eth": {"blockscout": "https://eth-explorer.invalid"}},
       "bsc": {"logs_rpcs": ["https://pub-bsc.invalid"], "detail_rpcs": ["https://pub-bsc-detail.invalid"]}}
CP = os.path.join(T.TMP, "config.json")
with open(CP, "w", encoding="utf-8") as f:
    json.dump(CFG, f)
import common

assert T.TMP in common.STATE_DIR and T.TMP in common.ENV_PATH
import nodekeys as NK
import settings_store as ss


def check(n, c, d=""):
    T.chk(bool(c), n, None if c else str(d)[:900])


def fresh(o):
    return json.loads(json.dumps(o))


NR = "TESTnr0000000000000001"
AK = "TESTak_0000000000000002"
QB = "https://fake-one.bsc.quiknode.pro/TESTqn0000000003/"
QBa = "https://fake-two.base-mainnet.quiknode.pro/TESTqn0000000004/"
ENV = {NK.ENV_NODEREAL: NR, NK.ENV_ANKR: AK, NK.ENV_QN_BSC: QB, NK.ENV_QN_BASE: QBa}

us = NK.urls(ENV)
check("K1a 순서 = BSC NodeReal→Ankr→QuickNode · Base Ankr→QuickNode",
      [p for p, _ in us["bsc"]] == ["nodereal", "ankr", "quicknode"] and [p for p, _ in us["base"]] == ["ankr", "quicknode"], us)
check("K1b 주소 꼴(NodeReal v1 · Ankr 체인 경로 · QuickNode 엔드포인트 그대로)",
      us["bsc"][0][1] == f"https://bsc-mainnet.nodereal.io/v1/{NR}" and us["bsc"][1][1] == f"https://rpc.ankr.com/bsc/{AK}"
      and us["base"][0][1] == f"https://rpc.ankr.com/base/{AK}" and us["bsc"][2][1] == QB and us["base"][1][1] == QBa, us)
check("K1c 키 없음 = 빈 풀", NK.urls({}) == {"bsc": [], "base": []}, NK.urls({}))
check("K1d 앞뒤 공백은 떼고 받음", NK.urls({NK.ENV_ANKR: "  " + AK + " \n"})["bsc"] == [("ankr", f"https://rpc.ankr.com/bsc/{AK}")])
for bad in ("short7x", "has space1234", "slash/inkey1234", "x" * 129, "키한글문자열입니다요", "abc$defgh", ""):
    check(f"K1e 형식 이상 키 = 없음 취급: {bad[:12]!r}", NK.urls({NK.ENV_NODEREAL: bad, NK.ENV_ANKR: bad}) == {"bsc": [], "base": []})
check("K1f 키 길이 경계 8·128 = 받음", NK.urls({NK.ENV_NODEREAL: "a" * 8})["bsc"] and NK.urls({NK.ENV_NODEREAL: "a" * 128})["bsc"])

QN_CASES = [
    ("http://fake-one.bsc.quiknode.pro/x/", "bsc", False, "http"),
    ("https://fake-one.bsc.quiknode.pro.evil.invalid/x/", "bsc", False, "호스트 끝이 quiknode.pro 아님"),
    ("https://user:pw@fake-one.bsc.quiknode.pro/x/", "bsc", False, "사용자 정보"),
    ("https://my-database.quiknode.pro/x/", "base", False, "'base' 글자만 들어간 라벨(ops1008b E8)"),
    ("https://fake.base-sepolia.quiknode.pro/x/", "base", False, "시험망"),
    ("https://fake.bsc-testnet.quiknode.pro/x/", "bsc", False, "BSC 시험망"),
    (QB, "base", False, "BSC 엔드포인트를 Base 칸에"),
    (QBa, "bsc", False, "Base 엔드포인트를 BSC 칸에"),
    ("not a url", "bsc", False, "주소 아님"),
    ("https://[::1/x", "bsc", False, "깨진 주소"),
    (QB, "bsc", True, "정상 BSC"),
    (QBa, "base", True, "정상 Base"),
]
for u, want, ok9, why in QN_CASES:
    got = NK._qn_url(u, want)
    check(f"K2 QuickNode {want} {why} = {'받음' if ok9 else '거부'}", bool(got) == ok9, got)
check("K2 받은 주소 = 질의·조각 떼고 호스트 소문자", NK._qn_url("https://Fake-One.BSC.quiknode.pro/tok12345/?a=1#f", "bsc")
      == "https://fake-one.bsc.quiknode.pro/tok12345/", NK._qn_url("https://Fake-One.BSC.quiknode.pro/tok12345/?a=1#f", "bsc"))

pl0 = NK.plans({})
check("K3a 기본 = NodeReal·Ankr·Alchemy 무료 · QuickNode 유료 10% · 월 한도 없음",
      pl0 == {"nodereal": {"plan": "free", "share": 10, "month": None}, "ankr": {"plan": "free", "share": 10, "month": None},
              "quicknode": {"plan": "paid", "share": 10, "month": None}, "alchemy": {"plan": "free", "share": 10, "month": None}}, pl0)
pl1 = NK.plans({"node_plans": {"nodereal": {"plan": "paid", "share": 25, "month": 500_000_000},
                               "ankr": {"plan": "paid", "share": 7, "month": True},
                               "quicknode": {"plan": "free", "share": 50, "month": 1000}}})
check("K3b 유료 · 비율 25 · 월 한도 그대로", pl1["nodereal"] == {"plan": "paid", "share": 25, "month": 500_000_000}, pl1["nodereal"])
check("K3c 비율 7(목록 밖) = 10 · 월 한도 True(불리언) = 없음", pl1["ankr"] == {"plan": "paid", "share": 10, "month": None}, pl1["ankr"])
check("K3d QuickNode 를 무료로 저장해도 = 유료(무료 등급 없음)", pl1["quicknode"]["plan"] == "paid" and pl1["quicknode"]["share"] == 50, pl1["quicknode"])
for sh in (True, "25", 0, 100, 81, None, 25.5):
    check(f"K3e 비율 {sh!r} = 기본 10", NK.plans({"node_plans": {"ankr": {"plan": "paid", "share": sh}}})["ankr"]["share"] == 10)
for mo, exp in ((0, None), (-5, None), (10 ** 12, 10 ** 12), (10 ** 12 + 1, None), (1.5e6, None), ("1000", None), (1, 1)):
    check(f"K3f 월 한도 {mo!r} → {exp!r}", NK.plans({"node_plans": {"ankr": {"plan": "paid", "month": mo}}})["ankr"]["month"] == exp)
for junk in (None, [], "x", {"node_plans": []}, {"node_plans": {"ankr": "paid"}}, {"node_plans": {"ankr": {"plan": "gold"}}}):
    p9 = T.safe(NK.plans, junk if junk is not None else {})
    check(f"K3g 이상한 설정 {str(junk)[:30]} = 기본(예외 없음)", isinstance(p9, dict) and "_exc" not in p9 and p9["ankr"]["plan"] == "free", p9)

for p in NK.PROVIDERS:
    sp = NK.budget_spec(p, {"plan": "free", "share": 50, "month": 123})
    if NK.PROVIDERS[p]["paid_only"]:
        continue
    check(f"K4a {p} 무료 = 무료 월 한도 × 80%(이용자 비율·월 한도 무시)",
          sp["month"] == NK.PROVIDERS[p]["free_month"] and sp["pct"] == 80.0 == float(NK.FREE_PCT), sp)
check("K4b 무료 비율 상수 = 80(오너 규칙 상한)", NK.FREE_PCT == 80)
sp = NK.budget_spec("nodereal", {"plan": "paid", "share": 25, "month": 500_000_000})
check("K4c 유료 = 이용자 월 한도 × 비율 25", sp["month"] == 500_000_000 and sp["pct"] == 25.0, sp)
sp = NK.budget_spec("ankr", {"plan": "paid", "share": 50, "month": None})
check("K4d 유료인데 월 한도 없음 = 무료 월 한도로 보수적", sp["month"] == NK.PROVIDERS["ankr"]["free_month"] and sp["pct"] == 50.0, sp)
sp = NK.budget_spec("quicknode", NK.plans({})["quicknode"])
check("K4e QuickNode 기본 = 유료 10% · 요청당 20 · debug/trace 40", sp["pct"] == 10.0 and sp["cu"] == 20 and sp["cu_heavy"] == 40, sp)
sp = NK.budget_spec("nodereal", NK.plans({})["nodereal"])
check("K4f NodeReal 단가 = 일반 25 · getLogs 50 · 무거운 것 50", sp["cu"] == 25 and sp["cu_methods"] == {"eth_getLogs": 50} and sp["cu_heavy"] == 50, sp)
sp["cu_methods"]["eth_getLogs"] = 1
check("K4g 표는 사본(바꿔도 서비스 표 무변)", NK.PROVIDERS["nodereal"]["cu_methods"]["eth_getLogs"] == 50)
check("K4h 호스트 = 서비스 표 그대로(QuickNode 는 *.quiknode.pro)", NK.budget_spec("quicknode", NK.plans({})["quicknode"])["hosts"] == ["*.quiknode.pro"])

st = NK.status(env=ENV, settings={"node_plans": {"nodereal": {"plan": "paid", "share": 50, "month": 31_000_000}}})
txt = json.dumps(st, ensure_ascii=False)
check("K5a 하루 예산 = 월 ÷ 31 × 비율(유료 50% · 무료 80%)",
      st["nodereal"]["perDay"] == 500_000 and st["ankr"]["perDay"] == int(200_000_000 / 31 * 80 / 100), (st["nodereal"], st["ankr"]))
check("K5b 쓰는 체인(NodeReal = BSC · Ankr = BSC·Base · QuickNode = 둘 다)",
      st["nodereal"]["chains"] == ["bsc"] and st["ankr"]["chains"] == ["bsc", "base"] and st["quicknode"]["chains"] == ["bsc", "base"], st)
check("K5c 상태에 키·노드 주소 없음", all(s not in txt for s in (NR, AK, "TESTqn", "quiknode.pro/", "nodereal.io", "rpc.ankr.com")), txt[:400])
st0 = NK.status(env={}, settings={})
check("K5d 키 없음 = 체인 빈 목록 · 비율 목록 10·25·50·80", all(v["chains"] == [] for v in st0.values()) and st0["ankr"]["shares"] == [10, 25, 50, 80], st0)

OLD_NR = "https://bsc-mainnet.nodereal.io/v1/TESTold0000000009"
cfg = fresh(CFG)
cfg["bsc"]["logs_rpcs"].append(OLD_NR)
done = NK.apply(cfg, env=ENV, settings={})
bc = cfg["bsc"]
check("K6a 반환 = 붙인 서비스(주소 아님)", done == {"bsc": ["nodereal", "ankr", "quicknode"], "base": ["ankr", "quicknode"]}, done)
check("K6b BSC 로그 풀 = 종전(공개 노드) 먼저 · 키 노드는 뒤", bc["logs_rpcs"][:2] == ["https://pub-bsc.invalid", OLD_NR]
      and bc["logs_rpcs"][2:] == [u for _, u in us["bsc"]], bc["logs_rpcs"])
check("K6c BSC 아카이브 = 옛 NodeReal 주소 + 키 노드", bc["archive_rpcs"] == [OLD_NR] + [u for _, u in us["bsc"]], bc["archive_rpcs"])
check("K6d getLogs 상한 = 서비스별(NodeReal 5만 · Ankr 3천 · QuickNode 1만)",
      [bc["getlogs_span_caps"][u] for _, u in us["bsc"]] == [50000, 3000, 10000], bc["getlogs_span_caps"])
check("K6e 상세 노드는 그대로", bc["detail_rpcs"] == CFG["bsc"]["detail_rpcs"], bc.get("detail_rpcs"))
cb = cfg["chains"]["base"]
check("K6f Base 로그 = 키 노드 먼저 · 공개 노드 예비", cb["rpc_logs"] == [u for _, u in us["base"]] + ["https://pub-base.invalid"], cb["rpc_logs"])
check("K6g Base 상한 = 기존 유지 + Ankr 3천 · QuickNode 1만",
      cb["rpc_log_span_caps"] == {"https://pub-base.invalid": 5000, us["base"][0][1]: 3000, us["base"][1][1]: 10000}, cb["rpc_log_span_caps"])
check("K6h Base 상태(archive) = 키 노드는 뒤 예비(공개 상태 풀 먼저)", cb["archive_rpcs"][-2:] == [u for _, u in us["base"]]
      and len(cb["archive_rpcs"]) > 2, cb["archive_rpcs"])
lim = cfg["rpc_day_limits"]
check("K6i 하루 장부 표 = 서비스 넷 다(무료 80% · QuickNode 유료 10% · Alchemy 는 노드 풀 밖이어도 장부는 있음)",
      set(lim) == {"node_nodereal", "node_ankr", "node_quicknode", "node_alchemy"} and lim["node_nodereal"]["pct"] == 80.0 and lim["node_quicknode"]["pct"] == 10.0
      and lim["node_alchemy"]["pct"] == 80.0, lim)
snap1 = json.dumps(cfg, sort_keys=True)
NK.apply(cfg, env=ENV, settings={})
check("K6j 두 번 붙여도 같음(중복 주소 없음)", json.dumps(cfg, sort_keys=True) == snap1)
cfg2 = fresh(CFG)
cfg2["rpc_day_limits"] = {"node_ankr": {"hosts": ["rpc.ankr.com"], "unit": "calls", "day": 7}}
NK.apply(cfg2, env={}, settings={})
check("K6k 이용자가 config 에 쓴 장부 항목 우선 · 키 없어도 표는 넣음(설정에 박힌 옛 주소 계량)",
      cfg2["rpc_day_limits"]["node_ankr"] == {"hosts": ["rpc.ankr.com"], "unit": "calls", "day": 7} and "node_nodereal" in cfg2["rpc_day_limits"]
      and cfg2["bsc"]["logs_rpcs"] == CFG["bsc"]["logs_rpcs"] and "archive_rpcs" not in cfg2["bsc"], cfg2)
cfg3 = fresh(CFG)
cfg3["backfill"] = {"hosts": {"bsc-mainnet.nodereal.io": {"rate": 1.0}}}
NK.apply(cfg3, env={NK.ENV_NODEREAL: NR}, settings={"node_plans": {"nodereal": {"plan": "paid", "share": 10}}})
check("K6l 유료 NodeReal + 이용자 호스트 한도 = 이용자 값 우선", cfg3["backfill"]["hosts"]["bsc-mainnet.nodereal.io"] == {"rate": 1.0}, cfg3["backfill"])
cfg4 = fresh(CFG)
cfg4["backfill"] = {"hosts": {}}
NK.apply(cfg4, env={NK.ENV_NODEREAL: NR}, settings={"node_plans": {"nodereal": {"plan": "paid", "share": 10}}})
check("K6m 유료 NodeReal = 유료 초당 한도 얹음", cfg4["backfill"]["hosts"].get("bsc-mainnet.nodereal.io", {}).get("rate") == 8.0, cfg4["backfill"])
cfg5 = fresh(CFG)
cfg5["backfill"] = {"hosts": {}}
NK.apply(cfg5, env={NK.ENV_NODEREAL: NR}, settings={})
check("K6n 무료 NodeReal = 호스트 한도 안 얹음(내장 무료 기준)", cfg5["backfill"]["hosts"] == {}, cfg5["backfill"])
cfg6 = {"wallets": [], "chains": {"base": {}}, "bsc": {"logs_rpcs": ["https://pub-bsc.invalid"]}}
NK.apply(cfg6, env={NK.ENV_ANKR: AK}, settings={})
rl6 = cfg6["chains"]["base"]["rpc_logs"]
check("K6o 기본 설치 Base(rpc_logs 없음) = 키 노드 + 내장 공개 로그 풀 유지(키 장부 소진에도 최신 수집)",
      rl6[0] == f"https://rpc.ankr.com/base/{AK}" and len(rl6) > 1, rl6)
cfg7 = {"wallets": [], "chains": {"eth": {}}, "bsc": "깨짐"}
r7 = T.safe(NK.apply, cfg7, env=ENV, settings={})
check("K6p 체인 블록 없음·이상한 꼴 = 예외 없이 건너뜀", "_exc" not in r7 and cfg7["bsc"] == "깨짐" and "base" not in cfg7["chains"], (r7, cfg7))

with open(CP, "rb") as f:
    b0 = f.read()
with open(common.ENV_PATH, "w", encoding="utf-8") as f:
    f.write(f"# 시험\nTJ_NODEREAL_KEY={NR}\nTJ_ANKR_KEY='{AK}'\n")
lc = common.load_config()
mem = json.dumps(lc)
check("K7a load_config = 메모리에 키 노드 붙음", NR in mem and AK in mem and any(u.endswith(NR) for u in lc["bsc"]["logs_rpcs"]), lc["bsc"])
with open(CP, "rb") as f:
    check("K7b load_config 뒤 config.json 바이트 그대로", f.read() == b0)
n9 = ss.rename_wallet("0x" + "1f" * 20, "시험2")
with open(CP, "r", encoding="utf-8") as f:
    disk = f.read()
check("K7c 설정 저장(지갑 이름 바꿈) 뒤에도 config.json 에 키·키 노드 주소 없음",
      n9 == 1 and "시험2" in disk and NR not in disk and AK not in disk and "rpc.ankr.com" not in disk and "rpc_day_limits" not in disk, disk[:500])
lc2 = ss.load_config_quiet()
check("K7d 설정 화면용 읽기(load_config_quiet)도 키를 안 붙임(화면 응답에 키 주소가 섞이지 않게)", NR not in json.dumps(lc2) and AK not in json.dumps(lc2))

e9 = NK._env()
check("K8a .env 따옴표 벗김", e9.get(NK.ENV_ANKR) == AK and e9.get(NK.ENV_NODEREAL) == NR, {k: len(v) for k, v in e9.items()})
fp1 = NK.fingerprint()
with open(common.ENV_PATH, "a", encoding="utf-8") as f:
    f.write("export TJ_QUICKNODE_BSC_KEY=" + QB + "\n")
fp2 = NK.fingerprint()
check("K8b export 줄도 읽음 · 키 늘면 지문 바뀜", NK._env().get(NK.ENV_QN_BSC) == QB and fp1 != fp2, (fp1, fp2))
ss.update_settings(node_plans={"ankr": {"plan": "paid", "share": 25, "month": None}})
fp3 = NK.fingerprint()
check("K8c 요금제 바뀌면 지문 바뀜(유닛 러너 재시작)", fp3 != fp2, (fp2, fp3))
check("K8d 지문 = 12자 해시(키 값 안 담김)", len(fp3) == 12 and all(c in "0123456789abcdef" for c in fp3) and NR not in fp3)
os.environ[NK.ENV_ANKR] = "TESTenv0000000000000005"
try:
    check("K8e 프로세스 환경변수 우선", NK._env()[NK.ENV_ANKR] == "TESTenv0000000000000005")
    check("K8f 환경변수로 바꿔도 지문 바뀜", NK.fingerprint() != fp3)
finally:
    os.environ.pop(NK.ENV_ANKR, None)
check("K8g 환경변수 지우면 지문 원래대로(같은 입력 = 같은 지문)", NK.fingerprint() == fp3)
os.remove(common.ENV_PATH)
check("K8h .env 없음 = 빈 값(예외 없음)", NK._env() == {} and NK.urls() == {"bsc": [], "base": []})

for u, exp in ((f"https://bsc-mainnet.nodereal.io/v1/{NR}", True), (f"https://rpc.ankr.com/base/{AK}", True), (QBa, True),
               ("https://pub-bsc.invalid", False), ("https://rpc.ankr.com.evil.invalid/x", False), ("https://quiknode.pro.invalid/", False),
               ("https://[::1", False), ("", False), (None, False)):
    check(f"K9 is_key_node({str(u)[:40]}) = {exp}", NK.is_key_node(u) is exp)

import bf_engine

pl10 = NK.plans({"node_plans": {"nodereal": {"plan": "paid", "share": 25, "month": 310_000_000}}})
bf_engine.rpc_day_configure({"rpc_day_limits": {f"node_{p}": NK.budget_spec(p, pl10[p]) for p in NK.PROVIDERS}})
ent = bf_engine._RPC_DAY
check("K10a NodeReal 유료 25% = 310,000,000 ÷ 31 × 25% = 2,500,000", ent["node_nodereal"]["meter"].budget == 2_500_000, ent["node_nodereal"]["meter"].budget)
check("K10b Ankr 무료 = 2억 ÷ 31 × 80%", ent["node_ankr"]["meter"].budget == int(200_000_000 / 31 * 80 / 100), ent["node_ankr"]["meter"].budget)
check("K10c 호스트 → 장부(QuickNode 와일드카드 포함)", bf_engine._rpc_day_of("bsc-mainnet.nodereal.io") == "node_nodereal"
      and bf_engine._rpc_day_of("rpc.ankr.com") == "node_ankr" and bf_engine._rpc_day_of("fake-one.bsc.quiknode.pro") == "node_quicknode")
check("K10d 단가: getLogs 50 + 일반 25 · 메서드 모름 = 가장 비싼 값",
      bf_engine._rpc_day_units("node_nodereal", ["eth_getLogs", "eth_call"]) == 75 and bf_engine._rpc_day_units("node_nodereal", None) == 50)

import onboarding

BAD = [({"provider": "nope", "plan": "free", "share": 10}, "알 수 없는 서비스"),
       ({"provider": "quicknode", "plan": "free", "share": 10}, "QuickNode 무료"),
       ({"provider": "ankr", "plan": "paid", "share": 30}, "비율 30"),
       ({"provider": "ankr", "plan": "paid", "share": True}, "비율 True"),
       ({"provider": "ankr", "plan": "paid", "share": 10, "month": 0}, "월 한도 0"),
       ({"provider": "ankr", "plan": "paid", "share": 10, "month": "100"}, "월 한도 글자"),
       ({"provider": "ankr", "plan": "paid", "share": 10, "month": False}, "월 한도 False")]
sp0 = ss.read_settings().get("node_plans")
for body, why in BAD:
    r = T.safe(onboarding._dispatch, "keys/nodeplan", body)
    check(f"K11a 저장 거부: {why}", isinstance(r, dict) and r.get("ok") is False and ss.read_settings().get("node_plans") == sp0, r)
r = onboarding._dispatch("keys/nodeplan", {"provider": "nodereal", "plan": "paid", "share": 50, "month": 62_000_000})
st11 = NK.plans()
check("K11b 저장 → settings.json → plans() 왕복 · 다른 서비스 요금제 보존",
      r.get("ok") and st11["nodereal"] == {"plan": "paid", "share": 50, "month": 62_000_000} and st11["ankr"]["plan"] == "paid", (r.get("ok"), st11))
check("K11c 저장 응답 상태 = 하루 예산 1,000,000(6,200만 ÷ 31 × 50%) · 키·주소 없음",
      r["nodes"]["nodereal"]["perDay"] == 1_000_000 and "nodereal.io" not in json.dumps(r, ensure_ascii=False), r.get("nodes", {}).get("nodereal"))
with open(os.path.join(common.STATE_DIR, "settings.json"), encoding="utf-8") as f:
    sdisk = f.read()
check("K11d settings.json 에 키 없음(요금제만 · 비밀 아님)", NR not in sdisk and AK not in sdisk and "node_plans" in sdisk)
with open(CP, "rb") as f:
    check("K11e 요금제 저장은 config.json 을 건드리지 않음", NR.encode() not in f.read())

T.finish()
