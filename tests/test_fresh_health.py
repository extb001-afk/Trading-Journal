#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import time

import common
import health

S = common.STATE_DIR
NOW = time.time()
W = "0x" + "a1" * 20


def wj(name, obj):
    os.makedirs(os.path.dirname(os.path.join(S, name)), exist_ok=True)
    common.atomic_write_json(os.path.join(S, name), obj)


CHAINS = {"eth": {"blockscout": "https://bs.invalid", "blocks_per_day": 7200, "rpcs": ["https://rpc.invalid"]},
          "base": {"blockscout": "https://bs2.invalid", "blocks_per_day": 43200, "rpcs": ["https://rpc2.invalid"]}}
cfg = {"chains": CHAINS, "wallets": [{"type": "evm", "chain": "eth", "address": W}]}
json.dump(cfg, open(common.CONFIG_PATH, "w"))
wj("cursor_evm_eth.json", {W: 100, "_synced_at": NOW - 30})
wj("cursor_evm_base.json", {W: 100, "_synced_at": NOW - 5 * 86400})
ids = {s.get("key") for s in health.collect_sources(common.load_config(), {}, NOW)}
T.chk("chain:eth" in ids, "H1 지갑 있는 체인(eth) 감시", sorted(ids))
T.chk("chain:base" not in ids, "H2 지갑을 지운 체인(base) = 감시 대상 아님(옛 커서 파일만 남음)", sorted(ids))
wj(os.path.join(health.HB_DIR, "evm.json"), {"schema": 1, "unit": "evm", "ts": int(NOW), "pid": 1,
                                             "sources": {"eth": {"kind": "chain", "ok": True, "last_success_ts": NOW - 10},
                                                         "base": {"kind": "chain", "ok": True, "last_success_ts": NOW - 5 * 86400}}})
ids8 = {s.get("key") for s in health.collect_sources(common.load_config(), {}, NOW)}
T.chk(not any("base" in str(k) for k in ids8) and "chain:eth" in ids8, "H8 지운 체인의 옛 하트비트 소스 = 감시 대상 아님", sorted(ids8))
os.remove(os.path.join(health.HB_DIR, "evm.json"))

hb = {"schema": 1, "unit": "evm", "ts": int(NOW - 3600), "pid": 1, "sources": {"eth": {"kind": "chain", "ok": True, "last_success_ts": NOW - 3600}}}
wj(os.path.join(health.HB_DIR, "evm.json"), hb)
cfg0 = {"chains": CHAINS, "wallets": []}
wj("runner_evm.json", {"unit": "evm", "state": "waiting", "why": "EVM 지갑 없음", "ts": int(time.time()), "pid": 1})
T.chk("evm" not in health.read_heartbeats(cfg0), "H3 EVM 지갑 0 + 러너 '지갑 없음' 대기 = tj-evm 하트비트 제외(끈 체인 없어도)")
os.remove(os.path.join(S, "runner_evm.json"))
T.chk("evm" in health.read_heartbeats(cfg0), "H4 러너 기록 없음 = 종전 그대로 하트비트를 본다")
d5 = common.gate_decisions(cfg, {"pairs": {f"base:{W}": {"active": True}}}, {})
r5 = (d5[0] if d5 else {}).get("reason") or ""
T.chk("지갑 추가" in r5 and "관점 재파생" not in r5, "H5 이미 이력 있는 지갑 = '설정 › 지갑 추가' 안내", r5)
def neg_detail():
    obs = {"now": NOW, "webdiag": {"ts": NOW, "neg": {"usd": -500.0, "n": 1, "top": [{"sym": "TKN", "loc": "wallet:eth:" + W, "usd": -500.0}]}}}
    h = health.evaluate(obs, dict(health.DEFAULTS, units=["tj-core", "tj-web"]), ())
    for it in h:
        if isinstance(it, dict) and it.get("id") == "ledger:neg":
            return str(it.get("detail") or "")
    return repr([it.get("id") for it in h if isinstance(it, dict)][:40])


MK = os.path.join(S, "backfill_done")
d7 = neg_detail()
T.chk("첫 백필 중" in d7 and "원장 결손" not in d7, "H7 첫 백필 중 = 놀라지 않는 문구", d7[:160])
open(MK, "w").write("1")
d7b = neg_detail()
T.chk("원장 결손" in d7b, "H7b 백필 완료 표식 뒤 = 종전 문구", d7b[:160])
os.remove(MK)

import web
cfg2 = {"chains": CHAINS, "wallets": [{"type": "evm", "chain": "eth", "address": W}, {"type": "bsc_rpc", "chain": "bsc", "address": "0x" + "b2" * 20}]}
T.chk(web.chainsweep_more_wallets({"checkedAt": NOW - 1200, "wallets": 0}, cfg2, NOW), "H6 지난 점검 지갑 0 → 지금 2 · 20분 전 = 바로 다시")
T.chk(not web.chainsweep_more_wallets({"checkedAt": NOW - 1200, "wallets": 2}, cfg2, NOW), "H6b 같은 수 = 주기대로")
T.chk(not web.chainsweep_more_wallets({"checkedAt": NOW - 300, "wallets": 0}, cfg2, NOW), "H6c 10분 안 = 주기대로(연달아 추가)")
T.chk(not web.chainsweep_more_wallets({}, cfg2, NOW), "H6d 지난 점검 없음 = 종전(첫 점검은 원래 바로)")
T.finish()
