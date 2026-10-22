#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _rpcfake as R  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402

EOA, CON, RICH, EOA2 = "0x" + "a1" * 20, "0x" + "c0" * 20, "0x" + "b2" * 20, "0x" + "d3" * 20
CON2 = "0x" + "c0" * 19 + "c2"
CON3 = "0x" + "c0" * 19 + "c3"


def node_fn(method, params):
    a = str(params[0] if method != "eth_call" else "0x" + str(params[0]["data"])[-40:]).lower()
    if method == "eth_getCode":
        return "0x6080604052" if a in (CON, CON2, CON3) else "0x"
    if method == "eth_getBalance":
        if a == CON3:
            raise RuntimeError("시험: 잔고 항목만 오류")
        return hex(10 ** 17)
    if method == "eth_call":
        if params[0]["data"] == "0x313ce567":
            return "0x" + "%064x" % 6
        return "0x" + "%064x" % ((2_000_000 * 10 ** 6) if a == RICH and str(params[0]["to"]).lower() == USDX else 0)
    raise RuntimeError(method)


node = R.Node(node_fn)
CFG = {"chains": {"eth": {"rpcs": [node.url]}, "base": {"rpcs": ["http://127.0.0.1:9/dead"]}},
       "wallets": [], "native_symbol": {"eth": "ETH", "base": "ETH"}}
json.dump(CFG, open(os.path.join(T.TMP, "config.json"), "w"))
import bf_engine  # noqa: E402
import paths, statefile  # noqa: E402
import settings_store as ss  # noqa: E402
import token_tables  # noqa: E402
import wallet_register as WR  # noqa: E402
import http_outflow  # noqa: E402
import onboarding  # noqa: E402

R.loop_open(bf_engine, T)
USDX = list((token_tables.STABLE_CAS.get("eth") or {}).items())[0][0]
statefile.atomic_write_json(paths.state("spot.json"), {"usd": {"ETH": 2000.0}})


def chk(msg, ok, extra=None):
    T.chk(ok, msg, extra)


c1, c2, c3, c4 = WR.sanity_check(EOA, ["eth"]), WR.sanity_check(CON, ["eth"]), WR.sanity_check(RICH, ["eth"]), WR.sanity_check(EOA2, ["base"])
chk("D1 평범한 EOA = 통과", c1 == {"confirm": [], "unchecked": []}, c1)
chk("D1 컨트랙트 코드 = 확인 요구", len(c2["confirm"]) == 1 and "컨트랙트" in c2["confirm"][0], c2)
chk("D1 스테이블 합계 ≥ $100만 = 확인 요구", any("잔고" in x for x in c3["confirm"]), c3)
chk("D1 노드 죽음 = 확인 못 함(막지 않음)", c4["confirm"] == [] and c4["unchecked"] == ["base"], c4)
c5 = WR.sanity_check(CON3, ["eth"])
chk("D1 잔고 항목만 오류 = 읽힌 코드는 그대로 확인 요구 + 확인 못 함 경고", len(c5["confirm"]) == 1 and c5["unchecked"] == ["eth"], c5)
c6 = WR.sanity_check(CON, ["aaa0", "aaa1", "aaa2", "aaa3", "eth"])
chk("D1 없는 체인 이름으로 검사 칸 채우기 = 무시(저장될 체인만 검사)", len(c6["confirm"]) == 1 and "eth" in c6["confirm"][0], c6)


def wallets():
    return [(w["chain"], w["address"]) for w in ss.read_config_raw().get("wallets") or []]


r = T.safe(WR.register_wallet, CON, ["eth"], "c")
chk("D2 확인 요구 = NeedConfirm · 설정 무변", isinstance(r, dict) and "NeedConfirm" in str(r.get("_exc")) and wallets() == [], r)
r = T.safe(WR.register_wallet, CON, ["eth"], "c", confirm=True)
chk("D2 confirm = 저장", isinstance(r, dict) and "_exc" not in r and ("eth", CON) in wallets(), r)
n0 = len(node.calls)
r = T.safe(WR.register_wallet, CON, ["eth"], "c", idempotent=True)
chk("D2 이미 등록한 체인 = 검사 안 함(호출 0) · 멱등", len(node.calls) == n0 and isinstance(r, dict) and "_exc" not in r, (len(node.calls) - n0, r))
r = T.safe(WR.register_wallet, EOA2, ["base"], "d")
chk("D2 노드 죽음 = 저장 + warn(fail-open)", isinstance(r, dict) and ("base", EOA2) in wallets() and "확인 못 함" in (r.get("warn") or ""), r)
r = T.safe(WR.register_wallets, [RICH, EOA], ["eth"])
stat = [x.get("status") for x in (r.get("results") or [])] if isinstance(r, dict) else r
chk("D3 여러 개: 확인 요구 주소만 confirm · 나머지 저장 · 입력 순서", stat == ["confirm", "added"] and ("eth", EOA) in wallets()
    and ("eth", RICH) not in wallets(), r)
r = T.safe(WR.register_wallets, [RICH], ["eth"], confirm=[RICH])
chk("D3 confirm 목록 = 저장", isinstance(r, dict) and [x.get("status") for x in r.get("results") or []] == ["added"] and ("eth", RICH) in wallets(), r)

pick = http_outflow.OutflowMixin._reg_chains_pick
p1, p2, p3, p4 = pick(None, EOA, {}), pick(None, EOA, {"chains": ["base"]}), pick(None, EOA, {"chains": ["nochain"]}), pick(None, "So1" + "1" * 41, {})
chk("D4 체인 모름 = 409 needChains(고를 목록 · 종전 4체인 일괄 아님)", p1[0] is None and p1[1][0] == 409 and p1[1][1].get("needChains")
    and set(p1[1][1].get("chains")) <= {"eth", "base", "bsc"}, p1)
chk("D4 본문 chains(허용) = 그대로 · 잘못 = 400 · Solana = sol", p2 == (["base"], None) and p3[0] is None and p3[1][0] == 400 and p4 == (["sol"], None),
    (p2, p3, p4))

o1 = T.safe(onboarding._dispatch, "wallets/add", {"address": "0x" + "c1" * 20, "chains": ["eth"], "label": "x"})
chk("D5 onboarding wallets/add = 평범한 주소 저장(종전)", isinstance(o1, dict) and o1.get("ok") is True, o1)
o3 = T.safe(onboarding._dispatch, "wallets/add", {"address": CON2, "chains": ["eth"], "label": "y"})
chk("D5 onboarding wallets/add 컨트랙트 = needConfirm 전달(저장 안 함)", isinstance(o3, dict) and o3.get("needConfirm") is True and ("eth", CON2) not in wallets(), o3)
o2 = T.safe(onboarding._dispatch, "wallets/add_many", {"addresses": [CON2], "chains": ["eth"], "confirm": "x"})
chk("D5 add_many confirm 형식 검사", isinstance(o2, dict) and o2.get("ok") is False, o2)
node.close()
T.finish()
