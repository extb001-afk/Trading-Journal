#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _rpcfake as R  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
W1, W2 = "0x" + "11" * 20, "0x" + "22" * 20
SCAM = "0x" + "ab" * 20


def node_fn(method, params):
    if method == "eth_getBalance":
        return "0x0"
    if method == "eth_call":
        return hex(17500 * 10 ** 18) if str(params[0]["to"]).lower() == SCAM else "0x0"
    raise RuntimeError(method)


node = R.Node(node_fn)
CFG = {"chains": {}, "wallets": [{"type": "bsc_rpc", "chain": "bsc", "address": W1}, {"type": "bsc_rpc", "chain": "bsc", "address": W2}],
       "native_symbol": {"bsc": "BNB"}, "backfill_months": 5, "bsc": {"detail_rpcs": [node.url]},
       "token_discovery": {"enabled": False}}
json.dump(CFG, open(os.path.join(T.TMP, "config.json"), "w"))
import bf_engine  # noqa: E402
import config  # noqa: E402
import core  # noqa: E402
import recon  # noqa: E402
import token_tables  # noqa: E402

R.loop_open(bf_engine, T)


def chk(msg, ok, extra=None):
    T.chk(ok, msg, extra)


def asked(to, w):
    return any(m == "eth_call" and str(p[0]["to"]).lower() == to and str(p[0]["data"]).endswith(w[2:]) for m, p in node.calls)


out = T.safe(recon.fetch_bsc_balances, [node.url], [W1, W2], {SCAM: ("AICC", 18)}, wallet_cas={W1: {SCAM}, W2: set()})
chk("B1 받은 적 없는 지갑 = 스캠 안 물음(잔고·_zero 없음 = 미관측) · 받은 지갑 = 물음",
    isinstance(out, dict) and "_exc" not in out and not out["per_wallet"][W2].get(("token", SCAM)) and SCAM not in out["_zero"][W2]
    and out["per_wallet"][W1].get(("token", SCAM)) and not asked(SCAM, W2) and asked(SCAM, W1), out)
node.calls.clear()
out2 = T.safe(recon.fetch_bsc_balances, [node.url], [W1, W2], {SCAM: ("AICC", 18)})
chk("B2 반대: wallet_cas 없음 = 종전(전 토큰 × 전 지갑)", isinstance(out2, dict) and out2["per_wallet"][W2].get(("token", SCAM)) and asked(SCAM, W2), out2)

c = core.Core(config.load_config())
USDT = str(sorted(token_tables.STABLE_CAS.get("bsc") or {})[0]).lower()
a_scam = c.asset_id("token", "bsc", SCAM, symbol="AICC", decimals=18)
c.asset_id("token", "bsc", USDT, symbol="USDT", decimals=18)
c._post_leg_strict("chain_tx", "bsc", "0x" + "33" * 32, 0, 1760000000, a_scam, f"wallet:bsc:{W1}", 10 ** 18, None, None, "move_in", "TRANSFER_IN")
c.conn.commit()
node.calls.clear()
b3 = T.safe(lambda: c.svc_recon._recon_fetch_plan("bsc", "bsc", [W1, W2], None)())
chk("B3 core 대체 경로 = 지갑별(그 지갑 원장 토큰 ∪ 정품) — W2 에 스캠 안 물음(가짜 기초잔고 없음) · W2 검증 스테이블은 물음 · W1 스캠 물음",
    isinstance(b3, dict) and "_exc" not in b3 and not ((b3.get("per_wallet") or {}).get(W2) or {}).get(("token", SCAM))
    and not asked(SCAM, W2) and asked(USDT, W2) and asked(SCAM, W1), (b3, node.calls[:6]))
node.close()
T.finish()
