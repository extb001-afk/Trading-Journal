#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

W = "0x" + "a1" * 20
NOW = int(time.time())
T_OFF = NOW - 10 * 86400
T_ACT = T_OFF - 100 * 86400


def cfg_doc(auto=True):
    sc = {"blockscout": "https://scroll.invalid", "conf_depth": 30, "blocks_per_day": 28800, "enabled": False}
    if auto:
        sc["_chainoff"] = {"at": T_OFF, "auto": True, "had": False}
    return {"chains": {"eth": {"blockscout": "https://e.invalid", "etherscan_chainid": 1}, "scroll": sc},
            "wallets": [{"type": "evm", "chain": "eth", "address": W, "label": "메인"}, {"type": "evm", "chain": "scroll", "address": W, "label": "메인"}],
            "native_symbol": {"eth": "ETH", "scroll": "ETH"}, "backfill_months": 5,
            "chain_sweep": {"enabled": True, "auto_enable": False, "min_usd": 1.0}}


with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump(cfg_doc(), f)
import config, paths, statefile  # noqa: E402
import chaincatalog  # noqa: E402
import chainsweep  # noqa: E402
import health  # noqa: E402

chaincatalog.SWEEP_CHAINS = {"scroll": chaincatalog.SWEEP_CHAINS["scroll"]}
chk = T.chk


def run(nonce_new, bal_new, px=2500.0, auto=True, bal_old=10 ** 15, nonce_old=3, seen=True):
    with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg_doc(auto), f)
    cfg = config.load_config()
    gate = {"version": 1, "chains": {}, "pairs": {f"scroll:{W}": {"active": True, "activatedAt": T_ACT, "firstSeen": T_ACT, "since_block": None,
                                                                  "src": "ledger", "nonce": nonce_old, "bal": str(bal_old), "usd": 3.0}}}
    if not seen:
        for k9 in ("nonce", "bal", "usd"):
            gate["pairs"][f"scroll:{W}"].pop(k9)

    def post(url, body, timeout):
        out = []
        for it in (body if isinstance(body, list) else [body]):
            m = it["method"]
            r = {"eth_chainId": hex(chaincatalog.SWEEP_CHAINS["scroll"][1]), "eth_blockNumber": hex(9_000_000),
                 "eth_getTransactionCount": hex(nonce_new), "eth_getBalance": hex(bal_new)}.get(m, "0x")
            out.append({"jsonrpc": "2.0", "id": it["id"], "result": r})
        return out if isinstance(body, list) else out[0]
    res = chainsweep.run_once(cfg, price_fn=lambda s: px if s == "ETH" else None, post=post, gate=gate, now=NOW)
    statefile.atomic_write_json(paths.ACTIVITY_GATE_PATH, gate)
    statefile.atomic_write_json(paths.state("chain_sweep.json"), res)
    cs = health.collect_chainsweep() or {}
    return gate["pairs"][f"scroll:{W}"].get("activatedAt"), len(cs.get("findings") or []), cs.get("off")


a, n, off = run(3, 20 * 10 ** 18)
chk(n == 1 and off == 0 and a == NOW, "A1 끈 뒤 20 ETH 입금 → 헬스 발견 1건(activatedAt = 지금)", [a, n, off])
a, n, off = run(4, 10 ** 15)
chk(n == 1 and a == NOW, "A2 nonce 증가 → 발견 1건", [a, n, off])
a, n, off = run(3, 10 ** 15)
chk(n == 0 and off == 1 and a == T_ACT, "A3 변화 없음 → 억제 그대로 · activatedAt 그대로", [a, n, off])
a, n, off = run(3, 10 ** 15, px=9000.0)
chk(n == 0 and off == 1 and a == T_ACT, "A4 시세만 오름 → 억제 그대로", [a, n, off])
a, n, off = run(3, 10 ** 15 + 2 * 10 ** 14)
chk(n == 0 and off == 1 and a == T_ACT, "A5 문턱 미만 증가 → 억제 그대로", [a, n, off])
a, n, off = run(3, 20 * 10 ** 18, auto=False)
chk(a == T_ACT and n == 0, "A6 손으로 끈 체인 = activatedAt 그대로(종전 억제)", [a, n, off])
a, n, off = run(3, 20 * 10 ** 18, seen=False)
chk(a == T_ACT and n == 0 and off == 1, "A7 점검 값 없던 쌍의 첫 관측 = 기준만(경고 없음)", [a, n, off])

T.finish()
