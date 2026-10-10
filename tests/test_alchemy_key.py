#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import time

for _k in ("TJ_NODEREAL_KEY", "TJ_ANKR_KEY", "TJ_QUICKNODE_BSC_KEY", "TJ_QUICKNODE_BASE_KEY", "TJ_ALCHEMY_KEY"):
    os.environ.pop(_k, None)
W_EVM = "0x" + "2e" * 20
CFG = {"wallets": [{"type": "evm", "chain": "base", "address": W_EVM, "label": "시험"}],
       "chains": {"base": {"rpc_logs": ["https://pub-base.invalid"]}, "eth": {"blockscout": "https://eth-explorer.invalid"}},
       "bsc": {"logs_rpcs": ["https://pub-bsc.invalid"]}}
CP = os.path.join(T.TMP, "config.json")
with open(CP, "w", encoding="utf-8") as f:
    json.dump(CFG, f)
import common

assert T.TMP in common.STATE_DIR and T.TMP in common.ENV_PATH
import bf_engine
import nodekeys as NK
import settings_store as ss


def check(n, c, d=""):
    T.chk(bool(c), n, None if c else str(d)[:900])


def fresh(o):
    return json.loads(json.dumps(o))


def write_env(text):
    with open(common.ENV_PATH, "w", encoding="utf-8") as f:
        f.write(text)


AL = "TESTal_00000000000000000000000007"
AK = "TESTak_0000000000000002"

pa = NK.PROVIDERS.get("alchemy") or {}
check("A1a Alchemy 서비스 = 무료 월 3,000만 CU · 무료 키 가능(유료만 아님)",
      pa.get("free_month") == 30_000_000 and pa.get("unit") == "cu" and pa.get("paid_only") is False, pa)
cm = pa.get("cu_methods") or {}
check("A1b 공식 CU 단가(getTokenBalances 20 · getTokenMetadata 10 · eth_call 26 · eth_getBalance 20 · eth_getLogs 60 · getAssetTransfers 120) · 기본 26",
      cm.get("alchemy_getTokenBalances") == 20 and cm.get("alchemy_getTokenMetadata") == 10 and cm.get("eth_call") == 26
      and cm.get("eth_getBalance") == 20 and cm.get("eth_getLogs") == 60 and cm.get("alchemy_getAssetTransfers") == 120 and pa.get("cu") == 26, (cm, pa.get("cu")))
check("A1c 호스트 = *.g.alchemy.com · .env 이름 TJ_ALCHEMY_KEY(비밀값 가림 이름)",
      pa.get("hosts") == ["*.g.alchemy.com"] and getattr(NK, "ENV_ALCHEMY", None) == "TJ_ALCHEMY_KEY" and common._secret_name("TJ_ALCHEMY_KEY"), pa)
sp = NK.budget_spec("alchemy", NK.plans({})["alchemy"]) if "alchemy" in NK.PROVIDERS else {}
check("A1d 기본 = 무료 80% 하루 장부(무료 월 한도 × 80%)", sp.get("month") == 30_000_000 and sp.get("pct") == 80.0 and sp.get("hosts") == ["*.g.alchemy.com"], sp)
sp2 = NK.budget_spec("alchemy", {"plan": "paid", "share": 25, "month": 100_000_000}) if "alchemy" in NK.PROVIDERS else {}
check("A1e 유료 = 이용자 월 한도 × 비율(기존 비율 규칙)", sp2.get("month") == 100_000_000 and sp2.get("pct") == 25.0, sp2)

au = getattr(NK, "alchemy_url", None)
check("A2a 헬퍼 alchemy_url 있음", callable(au))
if callable(au):
    if os.path.exists(common.ENV_PATH):
        os.remove(common.ENV_PATH)
    check("A2b 키 없음 = None", au("base-mainnet") is None)
    write_env(f"# 시험\nTJ_ALCHEMY_KEY={AL}\n")
    check("A2c 키 → https://{net}.g.alchemy.com/v2/{키}", au("base-mainnet") == f"https://base-mainnet.g.alchemy.com/v2/{AL}"
          and au("eth-mainnet") == f"https://eth-mainnet.g.alchemy.com/v2/{AL}", au("base-mainnet"))
    for net in ("", "BASE-MAINNET", "evil.invalid/x", "base-mainnet.evil", "a b", "../x", None, 5, "x" * 65, "-base", "base-"):
        check(f"A2d 이상한 net {str(net)[:16]!r} = None", T.safe(au, net) is None)
    write_env("TJ_ALCHEMY_KEY='" + AL + "'\n")
    check("A2e .env 따옴표 벗김", au("eth-mainnet") == f"https://eth-mainnet.g.alchemy.com/v2/{AL}")
    for bad in ("short7x", "has space1234", "slash/inkey1234", "x" * 129, "abc$defgh"):
        write_env(f"TJ_ALCHEMY_KEY={bad}\n")
        check(f"A2f 형식 이상 키 {bad[:10]!r} = None", au("eth-mainnet") is None)
    write_env(f"TJ_ALCHEMY_KEY={AL}\n")
    u1 = au("eth-mainnet")
    os.remove(common.ENV_PATH)
    check("A2g 부를 때마다 .env 를 읽음(저장·삭제가 재시작 없이 먹음)", u1 and au("eth-mainnet") is None)
    os.environ["TJ_ALCHEMY_KEY"] = AL
    try:
        check("A2h 프로세스 환경변수도 읽음", au("arb-mainnet") == f"https://arb-mainnet.g.alchemy.com/v2/{AL}")
    finally:
        os.environ.pop("TJ_ALCHEMY_KEY", None)

am = getattr(NK, "ankr_multichain_url", None)
check("A3a 헬퍼 ankr_multichain_url 있음", callable(am))
if callable(am):
    check("A3b 키 없음 = None", am() is None)
    write_env(f"TJ_ANKR_KEY={AK}\n")
    check("A3c Ankr 키 → https://rpc.ankr.com/multichain/{키}", am() == f"https://rpc.ankr.com/multichain/{AK}", am())
    write_env("TJ_ANKR_KEY=bad key\n")
    check("A3d 형식 이상 = None", am() is None)
    os.remove(common.ENV_PATH)

ENV = {"TJ_ALCHEMY_KEY": AL}
check("A4a urls() = Alchemy 없음(BSC·Base 노드 풀 무변)", NK.urls(ENV) == {"bsc": [], "base": []}, NK.urls(ENV))
cfg = fresh(CFG)
done = NK.apply(cfg, env=ENV, settings={})
blob = json.dumps(cfg)
check("A4b apply = 노드 풀에 Alchemy 주소 0 · 붙인 서비스 없음", "alchemy.com" not in blob.replace("*.g.alchemy.com", "") and AL not in blob and done == {}, (done, blob[:400]))
check("A4c 장부 표 node_alchemy = 무료 80%", (cfg.get("rpc_day_limits") or {}).get("node_alchemy", {}).get("pct") == 80.0, cfg.get("rpc_day_limits"))
check("A4d Base·BSC 로그 풀 그대로", cfg["chains"]["base"]["rpc_logs"] == CFG["chains"]["base"]["rpc_logs"] and cfg["bsc"]["logs_rpcs"] == CFG["bsc"]["logs_rpcs"], cfg)
write_env(f"TJ_ALCHEMY_KEY={AL}\nTJ_ANKR_KEY={AK}\n")
lc = common.load_config()
check("A4e load_config(Ankr+Alchemy 키) = Ankr 만 풀에 · Alchemy 주소·키 없음", AL not in json.dumps(lc) and any("rpc.ankr.com/base/" in u for u in lc["chains"]["base"]["rpc_logs"]), lc["chains"]["base"])
os.remove(common.ENV_PATH)

pl = NK.plans({})
bf_engine.rpc_day_configure({"rpc_day_limits": {f"node_{p}": NK.budget_spec(p, pl[p]) for p in NK.PROVIDERS}})
check("A5a 호스트 → node_alchemy(체인 서브도메인 전부)", all(bf_engine._rpc_day_of(h) == "node_alchemy" for h in ("base-mainnet.g.alchemy.com", "eth-mainnet.g.alchemy.com", "arb-mainnet.g.alchemy.com")))
check("A5b 닮은 호스트는 아님", all(bf_engine._rpc_day_of(h) != "node_alchemy" for h in ("xg.alchemy.com", "g.alchemy.com.evil.invalid", "alchemy.com")))
ent = bf_engine._RPC_DAY.get("node_alchemy")
check("A5c 하루 몫 = 3,000만 ÷ 31 × 80% = 774,193 CU", ent and ent["meter"].budget == int(30_000_000 / 31 * 0.8), ent and ent["meter"].budget)
U = bf_engine._rpc_day_units
check("A5d 단가: getTokenBalances 20 · +eth_getBalance = 40 · getLogs 60 · getAssetTransfers 120 · 모르는 메서드 = 26 · 메서드 모름 = 가장 비싼 120",
      U("node_alchemy", ["alchemy_getTokenBalances"]) == 20 and U("node_alchemy", ["alchemy_getTokenBalances", "eth_getBalance"]) == 40
      and U("node_alchemy", ["eth_getLogs"]) == 60 and U("node_alchemy", ["alchemy_getAssetTransfers"]) == 120
      and U("node_alchemy", ["eth_somethingNew"]) == 26 and U("node_alchemy", None) == 120,
      [U("node_alchemy", m) for m in (["alchemy_getTokenBalances"], ["eth_getLogs"], ["eth_somethingNew"], None)])
check("A5e 다른 장부 단가 무변(NodeReal getLogs 50 + 일반 25 · Ankr 200)",
      U("node_nodereal", ["eth_getLogs", "eth_call"]) == 75 and U("node_ankr", ["eth_call"]) == 200 and U("node_ankr", None) == 200)
pol = bf_engine._policy_for("base-mainnet.g.alchemy.com")
check("A5f 초당 한도 = 무료 300 CU/s·15rps 의 80% 아래(1초 창 (버스트 + 초당) × 60CU ≤ 240) · 계정 합산 공유 버킷(프로세스 합산)",
      pol.get("call_rate") and (pol["call_burst"] + pol["call_rate"]) * 60 <= 240 and (pol["call_burst"] + pol["call_rate"]) <= 12
      and pol.get("share") == "node_alchemy" and pol.get("share_xproc") is True, pol)


class _Resp:
    def __init__(self, b):
        self.b = b
        self.status = 200
        self.headers = {}

    def read(self, n=-1):
        return self.b

    def getheader(self, k, d=None):
        return d

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


SENT = []


def _fake_open(req, timeout):
    SENT.append(req.full_url)
    if b'"eth_blockNumber"' in (req.data or b""):
        return _Resp(b'{"jsonrpc": "2.0", "id": 1, "result": "0x10"}')
    return _Resp(b'{"jsonrpc": "2.0", "id": 1, "result": {"address": "0x0", "tokenBalances": []}}')


open_real = bf_engine._open
bf_engine._open = _fake_open
try:
    bf_engine._rpc_cfg_ensure()
    small = {"hosts": ["*.g.alchemy.com"], "unit": "cu", "month": 31 * 100, "pct": 80.0, "cu": 26,
             "cu_methods": dict(cm) if cm else {"alchemy_getTokenBalances": 20}}
    bf_engine.rpc_day_configure({"rpc_day_limits": {"node_alchemy": small}})
    URL = f"https://base-mainnet.g.alchemy.com/v2/{AL}"
    body = {"jsonrpc": "2.0", "id": 1, "method": "alchemy_getTokenBalances", "params": [W_EVM, "erc20"]}
    ok_n, err = 0, None
    for _i in range(10):
        try:
            bf_engine.rpc_post(URL, body, retries=1)
            ok_n += 1
        except Exception as e:
            err = e
            break
    net = getattr(err, "net", err)
    check("A6a 하루 몫 80 CU = getTokenBalances(20) 4번만 보내고 5번째는 0콜 거절(quota)",
          ok_n == 4 and len(SENT) == 4 and getattr(net, "kind", "") == "quota", (ok_n, len(SENT), repr(err)[:200]))
    check("A6b 거절 뒤 그 호스트 게이트 닫힘(UTC 자정까지 — 다른 노드로)", bf_engine.gate("base-mainnet.g.alchemy.com").is_open())
    st6 = bf_engine.rpc_day_status().get("node_alchemy") or {}
    check("A6c 장부 = 80/80 · 거절 1", st6.get("used") == 80 and st6.get("budget") == 80 and st6.get("refused") == 1, st6)
    check("A6d 거절 문구에 키 없음", AL not in str(err) and AL not in repr(err), str(err)[:200])
    if callable(getattr(NK, "used_today", None)):
        check("A6e 화면용 오늘 쓴 양 = 장부 파일 합(프로세스 합산)", NK.used_today("alchemy") == 80, NK.used_today("alchemy"))
    else:
        check("A6e used_today 헬퍼 있음", False)
    bf_engine.rpc_day_configure({"rpc_day_limits": {"node_ankr": NK.budget_spec("ankr", pl["ankr"])}})
    SENT.clear()
    MU = f"https://rpc.ankr.com/multichain/{AK}"
    bf_engine.rpc_post(MU, {"jsonrpc": "2.0", "id": 1, "method": "ankr_getAccountBalance", "params": {"walletAddress": W_EVM, "blockchain": ["base"]}}, retries=1)
    s7 = bf_engine.rpc_day_status().get("node_ankr") or {}
    check("A7a multichain 호출 = 같은 Ankr 장부 · 700 크레딧(공표 Advanced API 단가)", s7.get("used") == 700 and len(SENT) == 1, s7)
    bf_engine.http_request(MU, data=b'{"jsonrpc":"2.0","id":1,"method":"ankr_getTokenHolders","params":{}}', retries=1)
    s7b = bf_engine.rpc_day_status().get("node_ankr") or {}
    check("A7b 메서드를 안 넘긴 multichain 호출도 700(보수)", s7b.get("used") == 1400, s7b)
    bf_engine.rpc_post(f"https://rpc.ankr.com/base/{AK}", {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}, retries=1)
    s7c = bf_engine.rpc_day_status().get("node_ankr") or {}
    check("A7c 노드 API(rpc.ankr.com/base) 단가는 그대로 200", s7c.get("used") == 1600, s7c)
    g_adv = bf_engine._GATES.get(getattr(bf_engine, "ANKR_ADV_GATE", "?"))
    g_node = bf_engine._GATES.get("rpc.ankr.com")
    check("A7d multichain = 노드 API 와 다른 게이트 칸(Freemium Advanced 분당 50 · 10분 500 의 80% 아래)",
          g_adv is not None and g_node is not None and g_adv is not g_node and (g_adv.burst + g_adv.rate * 60) <= 40
          and (g_adv.burst + g_adv.rate * 600) <= 400, (g_adv and (g_adv.rate, g_adv.burst)))
finally:
    bf_engine._open = open_real

check("A8a is_key_node(Alchemy) = 참(최신 구간은 공개 노드 먼저)", NK.is_key_node(f"https://base-mainnet.g.alchemy.com/v2/{AL}")
      and not NK.is_key_node("https://g.alchemy.com.evil.invalid/x"))
write_env(f"TJ_ANKR_KEY={AK}\n")
fp0 = NK.fingerprint()
write_env(f"TJ_ANKR_KEY={AK}\nTJ_ALCHEMY_KEY={AL}\n")
fp1 = NK.fingerprint()
check("A8b Alchemy 키 저장·삭제 = 재시작 지문 그대로(노드 풀에 안 붙음 · 부를 때마다 .env 읽음)", fp0 == fp1, (fp0, fp1))
ss.update_settings(node_plans={"alchemy": {"plan": "paid", "share": 25, "month": None}})
fp2 = NK.fingerprint()
check("A8c Alchemy 요금제 바꿈 = 지문 바뀜(하루 장부는 기동 때)", fp2 != fp1, (fp1, fp2))
ss.update_settings(node_plans={})
os.remove(common.ENV_PATH)

check("A9a Alchemy 키 칸(EXPLORERS · NODE_GROUPS · 필드 TJ_ALCHEMY_KEY)", "alchemy" in ss.NODE_GROUPS and ss.EXPLORERS.get("alchemy", {}).get("fields") == [("TJ_ALCHEMY_KEY", "API Key")]
      and "TJ_ALCHEMY_KEY" in ss.SECRET_KEYS, ss.EXPLORERS.get("alchemy"))
na = getattr(ss, "needs_alchemy", None)
check("A9b needs_alchemy 있음", callable(na))
if callable(na):
    check("A9c EVM 지갑 = 필수", na({"wallets": [{"type": "evm", "chain": "eth", "address": W_EVM}]}) is True)
    check("A9d BSC 전용(bsc_rpc) 지갑 = 필수(Alchemy BNB 지원)", na({"wallets": [{"type": "bsc_rpc", "address": W_EVM}]}) is True)
    check("A9e 솔라나만 · 지갑 없음 · 이상한 꼴 = 필수 아님",
          na({"wallets": [{"type": "sol", "address": "So1aNaAddr3ss111111111111111111111111111111"}]}) is False and na({}) is False
          and na({"wallets": "x"}) is False and na(None) is False and na({"wallets": [None, {"type": "evm"}]}) is False)

import onboarding

st = onboarding.status()
check("A10a evmNeedsAlchemy = EVM 지갑 있음", st.get("evmNeedsAlchemy") is True, st.get("evmNeedsAlchemy"))
check("A10b explorers.alchemy = 미설정", (st.get("explorers") or {}).get("alchemy", {}).get("set") is False, (st.get("explorers") or {}).get("alchemy"))
na10 = (st.get("nodes") or {}).get("alchemy") or {}
check("A10c 노드 상태 = 하루 몫 774,193 · 오늘 쓴 양 숫자 · 쓰는 체인 없음(노드 풀 아님)",
      na10.get("perDay") == int(30_000_000 / 31 * 80 / 100) and isinstance(na10.get("usedToday"), int) and na10.get("chains") == [], na10)
check("A10d 다른 노드도 오늘 쓴 양", all(isinstance(v.get("usedToday"), int) for v in (st.get("nodes") or {}).values()), st.get("nodes"))

RL = os.path.join(common.STATE_DIR, "wallet_reload.json")
import wallet_register

RL = getattr(wallet_register, "RELOAD_PATH", RL)


def reload_n():
    try:
        with open(RL, encoding="utf-8") as f:
            return len(json.load(f).get("requests") or [])
    except (OSError, ValueError):
        return 0


for bad in ("short", "has space 123456", "x" * 129):
    r = T.safe(onboarding._dispatch, "keys/save", {"group": "alchemy", "values": {"TJ_ALCHEMY_KEY": bad}})
    check(f"A11a 형식 이상 저장 거부 {bad[:8]!r}", (r.get("ok") is False or "_exc" in r) and not ss.read_env().get("TJ_ALCHEMY_KEY"), r)
n0 = reload_n()
r = onboarding._dispatch("keys/save", {"group": "alchemy", "values": {"TJ_ALCHEMY_KEY": AL}})
check("A11b 저장 = .env 에만 · 재시작 요청 없음(부를 때마다 읽음)", r.get("ok") and ss.read_env().get("TJ_ALCHEMY_KEY") == AL and reload_n() == n0, (r, reload_n(), n0))
with open(CP, encoding="utf-8") as f:
    check("A11c config.json 에 키 없음", AL not in f.read())
st2 = onboarding.status()
txt = json.dumps(st2, ensure_ascii=False)
check("A11d 상태 = 저장됨 · 키 값 안 나감", st2["explorers"]["alchemy"]["set"] is True and AL not in txt and AL[-6:] not in txt, st2["explorers"]["alchemy"])
r = onboarding._dispatch("keys/delete", {"group": "alchemy"})
check("A11e 삭제 = .env 에서 지움 · 재시작 요청 없음", r.get("ok") and not ss.read_env().get("TJ_ALCHEMY_KEY") and reload_n() == n0, (r, reload_n()))
r = onboarding._dispatch("keys/save", {"group": "ankr", "values": {"TJ_ANKR_KEY": AK}})
check("A11f Ankr(노드 풀) 저장은 종전대로 재시작 요청", r.get("ok") and reload_n() == n0 + 1, (r, reload_n()))
r = onboarding._dispatch("keys/nodeplan", {"provider": "alchemy", "plan": "paid", "share": 10, "month": 100_000_000})
check("A11g Alchemy 요금제 저장 = 재시작 요청(장부 한도는 기동 때) · 하루 몫 = 1억 ÷ 31 × 10%",
      r.get("ok") and reload_n() == n0 + 2 and r["nodes"]["alchemy"]["perDay"] == int(100_000_000 / 31 * 10 / 100), (r.get("nodes", {}).get("alchemy"), reload_n()))
onboarding._dispatch("keys/nodeplan", {"provider": "alchemy", "plan": "free", "share": 10, "month": None})

CALLS = []


def fake_rpc(url, method, params, timeout=15.0):
    CALLS.append((url, method))
    return "0x1234"


real_rpc = onboarding._node_rpc
onboarding._node_rpc = fake_rpc
try:
    tr = onboarding._node_test("alchemy", {"TJ_ALCHEMY_KEY": AL})
    t12 = json.dumps(tr, ensure_ascii=False)
    check("A12a 넣은 키로 Ethereum·Base eth_blockNumber 1콜씩", [m for _u, m in CALLS] == ["eth_blockNumber", "eth_blockNumber"]
          and [u.split("//")[1].split(".")[0] for u, _m in CALLS] == ["eth-mainnet", "base-mainnet"], CALLS)
    check("A12b 결과 성공 · 키·주소 없음", tr.get("ok") and (tr.get("test") or {}).get("ok") and AL not in t12 and "alchemy.com/v2" not in t12, tr)

    class NE(Exception):
        kind = "http4xx"

    def boom(*a, **k):
        raise NE("403 Forbidden for https://base-mainnet.g.alchemy.com/v2/" + AL)
    onboarding._node_rpc = boom
    tr2 = onboarding._node_test("alchemy", {"TJ_ALCHEMY_KEY": AL})
    t12b = json.dumps(tr2, ensure_ascii=False)
    check("A12c 실패 = 분류만(키 거부·네트워크 꺼짐 안내) · 키 없음", tr2.get("ok") and not tr2["test"]["ok"] and AL not in t12b and "alchemy.com" not in t12b, tr2)
    CALLS.clear()
    onboarding._node_rpc = fake_rpc
    tr3 = onboarding._node_test("alchemy", {})
    check("A12d 저장된 키 없고 넣은 값도 없음 = 시험 0콜 · 안내", CALLS == [] and tr3.get("ok") is False, tr3)
    tr4 = onboarding._node_test("alchemy", {"TJ_ALCHEMY_KEY": "bad key"})
    check("A12e 형식 이상 = 0콜 거부", CALLS == [] and tr4.get("ok") is False, tr4)
finally:
    onboarding._node_rpc = real_rpc

SENT.clear()
with bf_engine._GATES_LOCK:
    bf_engine._GATES.clear()
bf_engine.rpc_day_configure({"rpc_day_limits": {"node_alchemy": NK.budget_spec("alchemy", NK.plans({})["alchemy"])}})
u0 = NK.used_today("alchemy")
bf_engine._open = _fake_open
try:
    tr5 = onboarding._node_test("alchemy", {"TJ_ALCHEMY_KEY": AL})
finally:
    bf_engine._open = open_real
u1 = NK.used_today("alchemy")
check("A12f 키 확인 2콜 = 실제 계량 경로에서 eth_blockNumber 10 CU × 2 = 20(메서드 단가 · 종전 240)",
      len(SENT) == 2 and u1 - u0 == 20 and (tr5.get("test") or {}).get("ok"), (len(SENT), u1 - u0, tr5))

import health

kk = health.collect_keys(CFG)
check("A13a collect_keys = alchemy 필요·없음(값 없음)", kk.get("alchemyNeed") is True and kk.get("alchemy") is False and AL not in json.dumps(kk), kk)
hh = dict(health.DEFAULTS, units=["tj-evm"])


def card(obs_keys):
    cs = [c for c in health.evaluate({"now": time.time(), "keys": obs_keys}, hh) if c["id"] == "key:alchemy"]
    return cs[0] if cs else None


c1 = card({"evm": True, "etherscan": True, "alchemyNeed": True, "alchemy": False})
check("A13b EVM 지갑 + 키 없음 = 주의 카드(알림 아님) · '옛 보유 토큰 찾기가 약해짐' 설명",
      c1 and c1["level"] == "warn" and c1["notify"] is False and "옛 보유" in c1["detail"] and "dashboard.alchemy.com" in c1["action"], c1)
c2 = card({"evm": True, "etherscan": True, "alchemyNeed": True, "alchemy": True})
check("A13c 키 있음 = 정상", c2 and c2["level"] == "ok", c2)
check("A13d EVM 지갑 없음 = 카드 없음 · 옛 서버 관측(칸 없음) = 카드 없음",
      card({"evm": False, "etherscan": False, "alchemyNeed": False, "alchemy": False}) is None and card({"evm": True, "etherscan": True}) is None)

PUB = os.path.dirname(T.README)


def rd(p):
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


readme, apik, envx = rd(T.README), rd(os.path.join(PUB, "docs", "API_KEYS.md")), rd(os.path.join(PUB, ".env.example"))
for nm, txt9 in (("README", readme), ("API_KEYS", apik)):
    check(f"A14a {nm}: TJ_ALCHEMY_KEY · TJ_ANKR_KEY · 받는 곳(dashboard.alchemy.com/signup · ankr.com/rpc) · 80%",
          all(s in txt9 for s in ("TJ_ALCHEMY_KEY", "TJ_ANKR_KEY", "dashboard.alchemy.com/signup", "ankr.com/rpc", "80%")))
check("A14b .env.example: TJ_ALCHEMY_KEY= · TJ_ANKR_KEY= (빈 값)", "\nTJ_ALCHEMY_KEY=\n" in envx and "\nTJ_ANKR_KEY=\n" in envx)
check("A14c API_KEYS: 용도(잔고·토큰 찾기 · 감시는 무료 노드)", "토큰" in apik and "무료 노드" in apik)

T.finish()
