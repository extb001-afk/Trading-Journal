#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402

W1, W2, W3 = "0x" + "a1" * 20, "0x" + "a2" * 20, "0x" + "a3" * 20
CFG = {"backfill_months": 0, "wrapped_native": {},
       "chains": {"base": {"blockscout": "https://bs.invalid", "rpcs": ["http://127.0.0.1:9/rpc"]},
                  "arbitrum": {"rpcs": ["http://127.0.0.1:9/rpc"], "blocks_per_day": 7200},
                  "plasma": {"discovery": "rpc", "chain_id": 9745, "rpcs": ["http://127.0.0.1:9/rpc"], "conf_depth": 10}},
       "wallets": [{"type": "evm", "chain": c, "address": w} for c in ("base", "arbitrum", "plasma") for w in (W1, W2)]}
json.dump(CFG, open(os.path.join(T.TMP, "config.json"), "w"))
import bf_engine  # noqa: E402
import paths, statefile  # noqa: E402
import evm_watch  # noqa: E402

bf_engine.configure(CFG)


def chk(msg, ok, extra=None):
    T.chk(ok, msg, extra)


class Wr:
    def append(self, r):
        pass


MK = {"블록스카웃": ("base", lambda ws: evm_watch.ChainWatcher(CFG, "base", ws, Wr())),
      "이더스캔": ("arbitrum", lambda ws: evm_watch.EtherscanWatcher(CFG, "arbitrum", ws, Wr(), 42161, "SYNTHKEY0123")),
      "RPC": ("plasma", lambda ws: evm_watch.RpcChainWatcher(CFG, "plasma", ws, Wr()))}
H = ["0x" + ("%02x" % i) * 32 for i in range(1, 4)]
for name, (ch, mk) in MK.items():
    cp = paths.state(f"cursor_evm_{ch}.json")
    ep = paths.state(f"emitted_evm_{ch}.json")
    base9 = {W1: 500, W2: 500} if name != "RPC" else {"_rpc_v": evm_watch.RpcChainWatcher.VERSION, "_start": 1, W1: 500, W2: 500}
    statefile.atomic_write_json(cp, base9)
    statefile.atomic_write_json(ep, H)

    def disk_emitted(ep=ep):
        return set(statefile.read_json(ep, []))

    w = T.safe(mk, [W1, W2])
    ok1 = not isinstance(w, dict)
    chk(f"R1 {name}: 옛 커서 + 같은 지갑 = emitted 그대로 · _wallets 시드", ok1 and w.emitted == set(H) and disk_emitted() == set(H)
        and statefile.read_json(cp, {}).get("_wallets") == sorted([W1, W2]), w if not ok1 else statefile.read_json(cp, {}).get("_wallets"))
    w = T.safe(mk, [W1])
    chk(f"R2 {name}: 지갑 지움 = _wallets 에서 빠짐 · 그 지갑 커서 키 남음 · emitted 그대로",
        not isinstance(w, dict) and w.emitted == set(H) and statefile.read_json(cp, {}).get("_wallets") == [W1]
        and statefile.read_json(cp, {}).get(W2) == 500, statefile.read_json(cp, {}))
    w = T.safe(mk, [W1, W2])
    chk(f"R3 {name}: 다시 등록 = 새 관점 → emitted 초기화(메모리·파일) · _wallets 복원 (종전 = 옛 커서 키라 초기화 없음 → 재방출 없음)",
        not isinstance(w, dict) and not w.emitted and disk_emitted() == set() and statefile.read_json(cp, {}).get("_wallets") == sorted([W1, W2]),
        {"mem": len(w.emitted) if not isinstance(w, dict) else w, "disk": len(disk_emitted())})
    statefile.atomic_write_json(ep, H)
    w = T.safe(mk, [W1, W2])
    chk(f"R4 {name}: 다시 기동(같은 지갑) = 초기화 반복 없음", not isinstance(w, dict) and w.emitted == set(H) and disk_emitted() == set(H))
    w = T.safe(mk, [W1, W2, W3])
    chk(f"R4 {name}: 커서 키 없는 새 지갑 = 종전처럼 초기화", not isinstance(w, dict) and not w.emitted and disk_emitted() == set())
    statefile.atomic_write_json(cp, {} if name != "RPC" else {"_rpc_v": evm_watch.RpcChainWatcher.VERSION, "_start": 1})
    statefile.atomic_write_json(ep, H)
    w = T.safe(mk, [W1, W2])
    chk(f"R4 {name}: 첫 설치(지갑 커서 없음) = 초기화 없음", not isinstance(w, dict) and w.emitted == set(H) and disk_emitted() == set(H))
cp = paths.state("cursor_evm_base.json")
ep = paths.state("emitted_evm_base.json")
statefile.atomic_write_json(cp, {"_rpc_v": evm_watch.RpcChainWatcher.VERSION, "_start": 1, W1: 700, W2: 500, "_wallets": [W1]})
statefile.atomic_write_json(ep, H)
w = T.safe(MK["블록스카웃"][1], [W1, W2])
chk("R5 RPC→탐색기 되돌림 + 재등록 = 새 관점(emitted 초기화) · _wallets 이어받음", not isinstance(w, dict) and not w.emitted
    and statefile.read_json(cp, {}).get("_wallets") == sorted([W1, W2]), statefile.read_json(cp, {}))
T.finish()
