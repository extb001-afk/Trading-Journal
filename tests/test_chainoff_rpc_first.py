#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402

W1 = "0x" + "11" * 20
cfg = {"chains": {"arbitrum": {"blockscout": "https://arb.blockscout.invalid", "chain_id": 42161, "rpcs": ["http://127.0.0.1:9/rpc"],
                               "rpc_logs": ["http://127.0.0.1:9/rpc"]},
                  "eth": {"blockscout": "https://eth.blockscout.invalid", "rpcs": ["http://127.0.0.1:9/rpc"]}},
       "wallets": [{"type": "evm", "chain": "arbitrum", "address": W1, "label": "w"}]}
json.dump(cfg, open(os.path.join(T.TMP, "config.json"), "w"))
import paths, statefile  # noqa: E402
import chainoff  # noqa: E402
import evm_watch  # noqa: E402


def chk(msg, ok, extra=None):
    T.chk(ok, msg, extra)


cc = cfg["chains"]["arbitrum"]


def why(cfg9, cc9=None):
    rt = evm_watch.evm_route(cfg9, "arbitrum", decide=False)
    return chainoff._off_reason("arbitrum", cc9 or cfg9["chains"]["arbitrum"], {"arbitrum", "eth"}, True, wallets=[], route=rt), rt


statefile.atomic_write_json(paths.state("evm_route.json"), {"arbitrum": {"route": "rpc_first", "at": 1, "why": "새 체인(커서 없음)"}})
w1, r1 = why(cfg)
chk("C1 rpc_first 체인 = RPC 전용 잠금 사유 · 수집기 주 경로(rpc)와 일치", w1 == chainoff.RPC_ONLY_WHY and r1 == "rpc_first"
    and evm_watch._primary_kind(cfg, "arbitrum", "") == "rpc", (w1, r1))
w5, r5 = why(dict(cfg, rpc_first=False))
chk("C2 반대: 전역 rpc_first false = 경로 파일과 무관하게 legacy · 끌 수 있음", w5 == "" and r5 == "legacy", (w5, r5))
cfg6 = json.loads(json.dumps(cfg))
cfg6["chains"]["arbitrum"]["discovery"] = "explorer"
w3, _r3 = why(cfg6)
statefile.atomic_write_json(paths.state("evm_route.json"), {"arbitrum": {"route": "legacy", "at": 1, "why": "x"}})
w2, _r2 = why(cfg)
chk("C2 반대: legacy 경로 · discovery explorer 명시 = 끌 수 있음(종전)", (w2, w3) == ("", ""), (w2, w3))
T.finish()
