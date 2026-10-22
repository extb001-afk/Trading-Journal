#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _nonevm as N  # noqa: E402

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
import paths  # noqa: E402
import settings_store as ss, runner_fp  # noqa: E402
import unit_runner  # noqa: E402

chk = T.chk
A_TRON = N.OWN["tron"][0]
A_TON = N.OWN["ton"][0]
K1, K2 = "k" * 32, "q" * 32


def S(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as e:   # noqa: BLE001
        return f"예외:{type(e).__name__}"


def old_fp(cfg, env):
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


def core_fp(cfg, env):
    r = S(runner_fp.unit_inputs, "core", cfg, env)
    return r[2] if isinstance(r, tuple) else r


def write_env(lines):
    with open(paths.ENV_PATH, "w", encoding="utf-8") as f:
        f.write("".join(x + "\n" for x in lines))


cfg0 = ss.load_config_quiet()

import tron_watch  # noqa: E402
import ton_watch  # noqa: E402
cfg_t = dict(cfg0, chain_wallets=[{"chain": "tron", "network": "mainnet", "address": A_TRON}])
write_env([f"TJ_TRONGRID_KEY={K1}", f"TJ_TONCENTER_KEY={K1}"])
ad_t = S(tron_watch.make_adapter, cfg_t)
ad_n = S(ton_watch.make_adapter, dict(cfg0, chain_wallets=[{"chain": "ton", "network": "mainnet", "address": A_TON}]))
write_env([f"TJ_TRONGRID_KEY={K2}", f"TJ_TONCENTER_KEY={K2}"])
chk(getattr(ad_t, "key", None) == K1 and getattr(getattr(ad_n, "client", None), "key", None) == K1,
    "K0 전제: 만든 어댑터는 .env 를 바꿔도 옛 키 그대로(Tron · TON) — 새 키는 다시 만들어야", (getattr(ad_t, "key", None), getattr(getattr(ad_n, "client", None), "key", None)))
ad_t2 = S(tron_watch.make_adapter, cfg_t)
chk(getattr(ad_t2, "key", None) == K2, "K0 전제: 새로 만든 어댑터 = 새 키")
ad_t3 = S(tron_watch.make_adapter, dict(cfg_t, nonevm={"tron": {"api": "https://tron-alt.invalid"}}))
chk(getattr(ad_t, "base", None) == tron_watch.API_DEFAULT and getattr(ad_t3, "base", None) == "https://tron-alt.invalid",
    "K0 전제: 제공자 주소(nonevm.tron.api)도 만들 때 고정", (getattr(ad_t, "base", None), getattr(ad_t3, "base", None)))
os.remove(paths.ENV_PATH)

base = old_fp(cfg0, {})
chk(core_fp(cfg0, {}) == base, "K1 새 체인 지갑 없음 = core 지문 종전 계산식과 바이트 동일")
chk(core_fp(cfg0, {"TJ_TRONGRID_KEY": K1, "TJ_TONCENTER_KEY": K2}) == base, "K1 지갑 없음 + 새 체인 키 넣음 = 그대로(core 재시작 없음)")
chk(core_fp(dict(cfg0, nonevm={"tron": {"api": "https://tron-alt.invalid"}, "ton": {"base_url": "https://ton-alt.invalid"}}), {}) == base,
    "K1 지갑 없음 + nonevm 설정 바꿈 = 그대로")
chk(core_fp(dict(cfg0, chain_wallets=[]), {"TJ_TRONGRID_KEY": K1}) == base, "K1 빈 chain_wallets 칸 + 키 = 그대로")

t_none = core_fp(cfg_t, {})
t_k1 = core_fp(cfg_t, {"TJ_TRONGRID_KEY": K1})
t_k2 = core_fp(cfg_t, {"TJ_TRONGRID_KEY": K2})
chk(t_none != base, "K2 (종전) Tron 지갑 생기면 core 지문 바뀜")
chk(t_k1 != t_none, "K2 Tron 지갑 + TronGrid 키 없음→있음 = core 지문 바뀜(새 키로 대사 어댑터 다시 만듦)", (t_none, t_k1))
chk(t_k2 != t_k1, "K2 Tron 지갑 + TronGrid 키 값 바뀜 = core 지문 바뀜", (t_k1, t_k2))

t_api = core_fp(dict(cfg_t, nonevm={"tron": {"api": "https://tron-alt.invalid"}}), {})
chk(t_api != t_none, "K3 Tron 지갑 + nonevm.tron(제공자 주소) 바뀜 = core 지문 바뀜", (t_none, t_api))

cfg_n = dict(cfg0, chain_wallets=[{"chain": "ton", "network": "mainnet", "address": A_TON}])
n0 = core_fp(cfg_n, {})
chk(core_fp(cfg_n, {"TJ_TONCENTER_KEY": K1}) != n0, "K4 TON 지갑 + toncenter 키 바뀜 = core 지문 바뀜")
chk(core_fp(cfg_n, {"TJ_TRONGRID_KEY": K1}) == n0 and core_fp(dict(cfg_n, nonevm={"tron": {"api": "https://tron-alt.invalid"}}), {}) == n0,
    "K4 TON 지갑만 있음 + Tron 키·설정만 바뀜 = 그대로(지갑 없는 체인 값은 core 재시작 사유 아님)")

chk(core_fp(cfg_t, {"TJ_TRONGRID_KEY": K1}) == t_k1 and core_fp(cfg_t, {}) == t_none, "K5 같은 입력 = 같은 지문(재시작 반복 없음)")
raw9 = json.load(open(CP))
raw9["chain_wallets"] = [{"chain": "tron", "network": "mainnet", "address": A_TRON}]
json.dump(raw9, open(CP, "w"))
write_env([f"TJ_TRONGRID_KEY={K1}"])
e1 = S(unit_runner._evaluate, "core")
write_env([f"TJ_TRONGRID_KEY={K2}"])
e2 = S(unit_runner._evaluate, "core")
chk(isinstance(e1, tuple) and isinstance(e2, tuple) and e1[0] is True and e1[2] != e2[2],
    "K5 유닛 러너 판정: .env 의 TronGrid 키를 바꾸면 core 지문 바뀜(→ '설정 변경 감지 — 새 설정으로 재시작')", (e1, e2))
write_env([f"TJ_TRONGRID_KEY={K2}"])
chk(S(unit_runner._evaluate, "core") == e2, "K5 러너 판정 반복 = 같은 지문")
os.remove(paths.ENV_PATH)
json.dump(CFG, open(CP, "w"))

_orig = runner_fp._nonevm_unit_inputs


def _boom(*_a, **_k):
    raise RuntimeError("시험: 체인 지문 계산 실패")


runner_fp._nonevm_unit_inputs = _boom
r6 = S(runner_fp.unit_inputs, "core", cfg_t, {"TJ_TRONGRID_KEY": K1})
runner_fp._nonevm_unit_inputs = _orig
chk(isinstance(r6, tuple) and r6[0] is True and isinstance(r6[2], str) and len(r6[2]) == 16, "K6 체인 지문 계산 예외 = core 판정은 그대로 준비(죽지 않음)", r6)
chk(core_fp(cfg0, {}) == base, "K6 뒤에도 지갑 없는 설치 지문 그대로")

T.finish()
