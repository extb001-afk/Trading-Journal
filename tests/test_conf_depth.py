#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import bsc_watch  # noqa: E402
import chaincatalog  # noqa: E402
import evm_base  # noqa: E402
import evm_bscout  # noqa: E402
import evm_es  # noqa: E402
import evm_logdisc  # noqa: E402
import evm_rpcw  # noqa: E402

chk = T.chk
cd = evm_base.conf_depth_of

chk(cd({}, "bsc") == 12 and cd({}, "base") == 30 and cd({}, "arbitrum") == 30 and cd({}, "optimism") == 30 and cd({}, "polygon") == 30,
    "C1 키 없는 L2(base·arbitrum·optimism·polygon) = 30 · chains.bsc(쓰지 않는 자리) = 종전 12", [cd({}, c) for c in ("bsc", "base", "arbitrum", "optimism", "polygon")])
chk(cd({}, "eth") == 12 and cd({"conf_depth": None}, "base") == 30, "C1 eth = 12 · null = 키 없음과 같음")
cat = next(c for c, v in chaincatalog.CATALOG.items() if c not in evm_base.CONF_DEPTH_DEFAULT and v.get("conf_depth"))
chk(cd({}, cat) == chaincatalog.CATALOG[cat]["conf_depth"] and cd({}, "no-such-chain") == 12,
    "C1 카탈로그 체인(config chains.<c> 로 직접 쓰고 키 뺌) = 카탈로그 값 · 모르는 체인 = 12", (cat, cd({}, cat)))
chk(cd({"conf_depth": 7}, "base") == 7 and cd({"conf_depth": 0}, "base") == 0 and cd({"conf_depth": "45"}, "eth") == 45,
    "C2 반대 방향: 사용자 값 우선(0 포함 · 글자 숫자도 정수로)")
with open(os.path.join(T.ROOT, "config.example.json"), encoding="utf-8") as f:
    ex = json.load(f)
want = {c: v["conf_depth"] for c, v in ex["chains"].items() if isinstance(v, dict) and "conf_depth" in v}
chk(want and want == evm_base.CONF_DEPTH_DEFAULT, "C3 기본값 표 = config.example.json chains.<c>.conf_depth", (want, evm_base.CONF_DEPTH_DEFAULT))
bw = bsc_watch.BscWatcher({"bsc": {"logs_rpcs": ["https://x.invalid"], "detail_rpcs": ["https://d.invalid"]}, "wallets": []}, [], None)
chk(bw.conf_depth == ex["bsc"]["conf_depth"], "C3 BSC 기본(bsc_watch · 키 없음) = 예시 bsc.conf_depth", (bw.conf_depth, ex["bsc"]["conf_depth"]))
def _cc(extra):
    return {"chains": {"base": dict({"chain_id": 8453, "rpcs": ["https://x.invalid"], "blockscout": "https://bs.invalid",
                                     "rpc_logs": ["https://l.invalid"]}, **extra)}, "wallets": []}


def _watchers(cfg):
    return {"rpcw": evm_rpcw.RpcChainWatcher(cfg, "base", [], None).conf_depth,
            "logdisc": evm_logdisc.RpcLogDiscovery(cfg, "base", [], None, None).conf_depth,
            "es": evm_es.EtherscanWatcher(cfg, "base", [], None, 8453, "k").conf_depth,
            "bscout": evm_bscout.ChainWatcher(cfg, "base", [], None).conf_depth}


w0, w7 = _watchers(_cc({})), _watchers(_cc({"conf_depth": 7}))
chk(set(w0.values()) == {30} and set(w7.values()) == {7}, "C4 EVM 수집기 4곳(RPC·로그 발견·이더스캔·블록스카웃) = 키 없는 base 30 · 사용자 값 7 그대로", (w0, w7))

T.finish()
