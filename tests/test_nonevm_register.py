#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _nonevm as N  # noqa: E402

import copy  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402

CFG = {"chains": {"eth": {"blockscout": "https://bs.invalid", "rpcs": ["https://rpc.invalid"]}},
       "wallets": [{"type": "evm", "chain": "eth", "address": "0x" + "a1" * 20, "label": "w"},
                   {"type": "sol", "chain": "sol", "address": "So1" + "1" * 41, "label": "s"}],
       "sol": {"rpc": "https://solrpc.invalid"}, "backfill_months": 5}
CP = os.path.join(T.TMP, "config.json")
json.dump(CFG, open(CP, "w"))
os.environ["TJ_CONFIG"] = CP
import settings_store as ss, runner_fp, settings_wallets  # noqa: E402
import chain_registry as reg  # noqa: E402
import wallet_register as wr  # noqa: E402
import paths  # noqa: E402
import unit_runner  # noqa: E402

reg.available = lambda c: c in reg.FORCE_AVAILABLE

chk = T.chk


def raw():
    return json.load(open(CP))


def old_fp(unit, cfg, env):
    genv = lambda k: os.environ.get(k) or env.get(k, "")  # noqa: E731
    ws = cfg.get("wallets") or []
    hk = hashlib.sha256(genv("TJ_HELIUS_KEY").encode()).hexdigest()[:8] if genv("TJ_HELIUS_KEY") else ""
    try:
        import nodekeys
        nk = nodekeys.fingerprint()
    except Exception:   # noqa: BLE001
        nk = ""
    allw = sorted({(w.get("type", "evm"), w.get("chain"), w.get("address") if w.get("type") == "sol"
                    else (w.get("address") or "").lower()) for w in ws})
    return runner_fp._h([allw, cfg.get("exchange_addresses"), hk, nk, cfg.get("backfill_months"), cfg.get("backfill_full_history")])


cfg0 = ss.load_config_quiet()
env = {}
fp0 = {u: runner_fp.unit_inputs(u, cfg0, env) for u in runner_fp.RUNNER_UNITS}
chk(fp0["core"][2] == old_fp("core", cfg0, env), "R1 core 지문 = 종전 계산식(새 지갑 없음 → 배포만으로 재시작 없음)")
chk(runner_fp.unit_inputs("core", dict(cfg0, chain_wallets=[]), env) == fp0["core"], "R1 빈 chain_wallets 칸도 종전 지문")
chk(runner_fp.runner_units(cfg0) == runner_fp.RUNNER_UNITS == ("evm", "sol", "bsc", "core", "web"), "R1 화면 유닛 줄 = 종전 5개")
chk(set(runner_fp.runner_status()) == set(), "R1 하트비트 없음 = 빈 목록(종전과 같음)")
chk(all(k in unit_runner.SCRIPTS for k in ("evm", "sol", "bsc", "core", "web")) and unit_runner.SCRIPTS["tron"] == "tron_watch.py",
    "R1 러너 기존 유닛 그대로 + 새 체인 유닛 이름")

before = open(CP).read()
try:
    settings_wallets.add_chain_wallet("tron", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t")
    chk(False, "R2 수집기 없는 체인 등록 거부")
except ValueError as e:
    chk("준비 중" in str(e), "R2 수집기 없는 체인 등록 거부('준비 중')", str(e))
chk(open(CP).read() == before, "R2 거부 = config.json 무변")
r9 = runner_fp.unit_inputs("tron", dict(cfg0, chain_wallets=[{"chain": "tron", "address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"}]), env)
chk(r9[0] is False and "준비 중" in r9[1], "R2 손으로 넣은 지갑이 있어도 수집기 없으면 유닛 대기(띄우지 않음)", r9)

reg.FORCE_AVAILABLE.update(reg.CHAINS)
w_before = copy.deepcopy(raw()["wallets"])
a1 = settings_wallets.add_chain_wallet("tron", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t")
chk(a1["key"] == "41a614f803b6fd780986a42c78ec9c7f77e6ded13c" and a1["label"] == "Tron 1", "R3 Tron 등록 · 자동 이름", a1)
try:
    settings_wallets.add_chain_wallet("tron", "41A614F803B6FD780986A42C78EC9C7F77E6DED13C")
    chk(False, "R3 Base58/hex 같은 주소 두 번 거부")
except ValueError as e:
    chk("이미" in str(e), "R3 Base58/hex 같은 주소 두 번 거부")
EQ = "EQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPrHF"
a2 = settings_wallets.add_chain_wallet("ton", EQ, label="톤")
ent = [w for w in raw()["chain_wallets"] if w["chain"] == "ton"][0]
chk(ent["address"].startswith("0:") and a2["display"].startswith("UQ"), "R3 TON 저장 = raw · 표시 = non-bounceable", (ent, a2))
d = f"wpkh([d34db33f/84h/0h/0h]{N.BTC_XPUB}/<0;1>/*)"
a3 = settings_wallets.add_chain_wallet("btc", mode="descriptor", descriptor=d, label="hd")
ent3 = [w for w in raw()["chain_wallets"] if w.get("mode") == "descriptor"][0]
chk("#" in ent3["descriptor"] and ent3["gap_limit"] == 20 and N.BTC_XPUB not in a3["display"], "R3 BTC 디스크립터 정규형 저장 · 응답은 가림", a3)
a4 = settings_wallets.add_chain_wallet("btc", N.BTC_ADDR)
chk("이 주소만" in a4["note"], "R3 BTC 단일 주소 모드 = 잔돈 누락 가능 안내", a4)
for bad_in, kw in ((None, {"mode": "descriptor", "descriptor": "wpkh(xprv9s21ZrQH143K3QTDL4LXw2F7HEK3wJUD2nW2nRk4stbPy6cq3jPPqjiChkVvvNKmPGJxWUtg6LnF5kejMRNNU3TGtRBeJgk33yuGBxrMPHi/<0;1>/*)"}),
                   ("ab" * 32, {}), (" ".join(["apple"] * 12), {})):
    try:
        settings_wallets.add_chain_wallet("btc" if kw else "tron", bad_in, **kw)
        chk(False, "R3 개인 키·시드 거부", bad_in)
    except ValueError as e:
        chk("개인 키" in str(e) or "시드" in str(e), "R3 개인 키·시드·xprv 거부(값 없이)", str(e))
try:
    settings_wallets.add_chain_wallet("sui", "suiprivkey1qq" + "q" * 50)
    chk(False, "R3 Sui 개인 키(suiprivkey) 거부")
except ValueError as e:
    chk("개인 키" in str(e), "R3 Sui 개인 키(suiprivkey) 거부", str(e))
chk(raw()["wallets"] == w_before, "R3 wallets[] 무변(기존 소비 경로가 새 지갑을 못 봄)")
chk("41a614f803b6fd780986a42c78ec9c7f77e6ded13c" not in json.dumps(raw()["wallets"]), "R3 새 지갑이 wallets[] 에 안 섞임")
cl = settings_wallets.chain_wallet_list(raw())
chk([x["chain"] for x in cl] == ["tron", "ton", "btc", "btc"] and all(N.BTC_XPUB not in x["display"] for x in cl), "R3 화면 목록(가림)", cl)

cfg1 = ss.load_config_quiet()
t1 = runner_fp.unit_inputs("tron", cfg1, env)
chk(t1[0] is True, "R4 지갑 있고 수집기 있으면 시작", t1)
chk(runner_fp.unit_inputs("sui", cfg1, env)[0] is False and "지갑 없음" in runner_fp.unit_inputs("sui", cfg1, env)[1], "R4 지갑 없는 체인 = 대기")
t2 = runner_fp.unit_inputs("tron", cfg1, {"TJ_TRONGRID_KEY": "k" * 32})
chk(t2[2] != t1[2] and t2[0] is True, "R4 선택 키 바뀌면 지문 바뀜(키 없어도 시작)")
chk(runner_fp.unit_inputs("core", cfg1, env)[2] != fp0["core"][2], "R4 새 지갑 생기면 core 지문 바뀜(원장이 새 스트림을 읽게 재시작)")
chk(all(runner_fp.unit_inputs(u, cfg1, env)[2] == fp0[u][2] for u in ("evm", "sol", "bsc")), "R4 EVM·SOL·BSC 유닛 지문 무변(재시작 없음)")
chk(runner_fp.runner_units(cfg1) == runner_fp.RUNNER_UNITS + ("btc", "ton", "tron"), "R4 화면 유닛 줄 = 지갑 있는 새 체인만 더함")

r5 = wr.register_chain_wallet("sui", "0x" + "ab" * 32, source="setup")
rq = json.load(open(paths.state("wallet_reload.json")))["requests"][-1]
chk(rq["units"] == ["tj-core", "tj-sui", "tj-web"] and r5["apply"]["units"] == rq["units"], "R5 적용 요청 = 그 체인 유닛 + core·web", rq)
chk(r5["apply"]["manual"] == "pm2 restart tj-core tj-sui tj-web", "R5 수동 재시작 안내 = 그 체인 유닛 + core·web", r5["apply"])
r5e = wr.apply_info(wr._units_for("evm", ["eth"]))
chk(r5e["manual"] == "pm2 restart tj-core tj-evm tj-web", "R5 EVM 지갑 수동 재시작 안내 = tj-evm + core·web", r5e)
chk(wr.apply_info()["manual"] == wr.MANUAL, "R5 영향 유닛 모름(이미 등록 — 무변경) = 종전 안내 그대로", wr.apply_info())
wr.register_chain_wallet("btc", mode="descriptor", descriptor=f"pkh({N.BTC_XPUB}/<0;1>/*)", source="setup")
chk(N.BTC_XPUB not in open(paths.state("wallet_reload.json")).read(), "R5 적용 요청 기록에 디스크립터·xpub 원문 없음")
chk("tj-tron" in wr.RELOAD_UNITS and "tj-evm" in wr.RELOAD_UNITS, "R5 감시기 허용 목록에 새 유닛(pm2 에 있을 때만 재시작)")
chk(settings_wallets.rename_chain_wallet("ton", "0_ca6e321c7cce9ecedf0a8ca2492ec8592494aa5fb5ce0387dff96ef6af982a3e", "새이름") == 1
    and [w for w in raw()["chain_wallets"] if w["chain"] == "ton"][0]["label"] == "새이름", "R5 이름 바꾸기(원장 키로)")
chk(settings_wallets.remove_chain_wallet("tron", "41a614f803b6fd780986a42c78ec9c7f77e6ded13c") == 1
    and not any(w["chain"] == "tron" for w in raw()["chain_wallets"]), "R5 빼기(같은 주소 다른 표기로도)")
chk(settings_wallets.remove_chain_wallet("tron", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t") == 0, "R5 없는 지갑 빼기 = 0")
chk(raw()["wallets"] == w_before, "R5 끝까지 wallets[] 무변")

import onboarding  # noqa: E402
reg.FORCE_AVAILABLE.clear()
r6 = None
try:
    r6 = onboarding._dispatch("chain_wallets/add", {"chain": "tron", "address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"})
except ValueError as e:
    r6 = {"ok": False, "error": str(e)}
chk(r6.get("ok") is False and "준비 중" in r6.get("error", ""), "R6 API — 수집기 없으면 '준비 중' 거부", r6)
reg.FORCE_AVAILABLE.add("tron")
r6 = onboarding._dispatch("chain_wallets/add", {"chain": "tron", "address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", "label": "트론"})
chk(r6.get("ok") and r6["added"]["label"] == "트론", "R6 API 등록", r6)
r6 = onboarding._dispatch("chain_wallets/label", {"chain": "tron", "address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", "label": "트론2"})
chk(r6.get("ok"), "R6 API 이름")
r6 = onboarding._dispatch("chain_wallets/remove", {"chain": "tron", "address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"})
chk(r6.get("ok") and r6["removed"] == 1, "R6 API 빼기")
chk(any(x["key"] == "tron" and x["available"] for x in onboarding._nonevm_status()), "R6 상태 nonevm 표(수집기 있음 표시)")

import btc_descriptor as bd9  # noqa: E402
reg.FORCE_AVAILABLE.add("btc")
ZPUB9 = bd9.XPub.parse(N.BTC_XPUB).serialize(bytes.fromhex("04b24746"))
r7 = onboarding._dispatch("chain_wallets/add", {"chain": "btc", "mode": "descriptor", "descriptor": ZPUB9, "label": "비트 HD"})
d7 = [w for w in raw()["chain_wallets"] if w["chain"] == "btc" and w.get("label") == "비트 HD"]
chk(r7.get("ok") and d7 and d7[0]["descriptor"].startswith("wpkh(xpub") and "/<0;1>/*)#" in d7[0]["descriptor"] and ZPUB9 not in json.dumps(r7),
    "R7 zpub 하나 = wpkh 두 갈래 디스크립터로 저장(응답에 원문 없음)", (r7, d7))
e7 = None
try:
    onboarding._dispatch("chain_wallets/add", {"chain": "btc", "mode": "descriptor", "descriptor": "  " + N.BTC_XPUB + " "})
except ValueError as e:
    e7 = str(e)
chk(e7 and "형식" in e7, "R7 xpub 은 주소 형식을 골라야 함(지어내지 않음)", e7)
e7 = None
try:
    onboarding._dispatch("chain_wallets/add", {"chain": "btc", "mode": "descriptor", "descriptor": N.BTC_XPUB, "script_type": "wpkh"})
except ValueError as e:
    e7 = str(e)
chk(e7 == "이미 등록된 지갑입니다", "R7 같은 키를 xpub + wpkh 로 다시 = 같은 지갑(중복 거부)", e7)
r7 = onboarding._dispatch("chain_wallets/add", {"chain": "btc", "mode": "descriptor", "descriptor": N.BTC_XPUB, "script_type": "tr"})
chk(r7.get("ok") and any(w.get("descriptor", "").startswith("tr(xpub") for w in raw()["chain_wallets"]), "R7 xpub + tr = 단일 키 taproot HD", r7)
e7 = None
try:
    onboarding._dispatch("chain_wallets/add", {"chain": "btc", "mode": "descriptor", "descriptor": "xprv9s21ZrQH143K3QTDL4LXw2F7HEK3wJUD2nW2nRk4stbPy6cq3jPPqjiChkVvvNKmPGJxWUtg6LnF5kejMRNNU3TGtRBeJgk33yuGBxrMPHi"})
except ValueError as e:
    e7 = str(e)
chk(e7 and "xprv9s21" not in e7, "R7 확장 개인 키(xprv) = 거부 · 값 안 보여 줌", e7)
for w in [w for w in raw()["chain_wallets"] if w["chain"] == "btc"]:
    settings_wallets.remove_chain_wallet("btc", w.get("descriptor") or w.get("address"))
reg.FORCE_AVAILABLE.clear()
T.finish()
