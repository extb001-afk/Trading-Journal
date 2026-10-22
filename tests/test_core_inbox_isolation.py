#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
from _ingest import check, W, Reader  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

json.dump({"chains": {"base": {"discovery": "rpc", "chain_id": 8453, "conf_depth": 10, "blocks_per_day": 43200, "rpcs": ["https://rpc.invalid"]}},
           "wallets": [{"type": "evm", "chain": "base", "address": W}], "native_symbol": {"base": "ETH"}, "backfill_months": 5},
          open(os.path.join(T.TMP, "config.json"), "w"))
import config, paths  # noqa: E402
import core  # noqa: E402

PZ = os.path.join(paths.STATE_DIR, "poison.jsonl")


def poison_lines():
    return [json.loads(x) for x in open(PZ).read().splitlines()] if os.path.exists(PZ) else []


c = core.Core(config.load_config())
c.conn.commit()

recs = [{"v": 9, "kind": "ex_snapshot_v9", "exchange": "upbit", "deposits": [{"uuid": "u1", "state": "ACCEPTED", "currency": "BTC", "amount": "1"}]},
        {"kind": "_corrupt", "raw": "{bad", "raw_hex": "7b626164"}]
c._drain_stream("ex", Reader(recs), 0, 0)
off = c.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream='ex'").fetchone()
pl = poison_lines()
check("K1 오프셋 = 두 레코드 뒤(격리 뒤 전진)", off is not None and tuple(off) == (0, 2), off and tuple(off))
check("K1 모르는 종류 = 격리 파일에 원문 보존(조용히 버리지 않음)", any((e.get("rec") or {}).get("kind") == "ex_snapshot_v9" and "ex_snapshot_v9" in str(e.get("err"))
                                                          for e in pl), pl)
check("K1 손상 줄(_corrupt)은 종전 그대로 격리", any((e.get("rec") or {}).get("kind") == "_corrupt" and e.get("err") == "_corrupt_inbox_line" for e in pl), pl)
check("K1 원장에 들어간 원본 0", c.conn.execute("SELECT count(*) FROM raw_ex").fetchone()[0] == 0)

RT = "0x" + "e5" * 20
CA = "0x" + "c3" * 20
HX = "0x" + "%064x" % 9
open(os.path.join(paths.STATE_DIR, "rpc_token_meta_base.json"), "w").write('{"0xabc": 6')
snap = {"tx": {"hash": HX, "from": RT, "to": CA, "value": "0", "fee": {"value": "0"}, "status": "ok", "raw_input": "0xa9059cbb",
               "timestamp": int(time.time()) - 86400, "block_number": 1000, "block_hash": "0x" + "d" * 64},
        "token_transfers": [{"from": {"hash": RT}, "to": {"hash": W}, "token": {"address": CA, "symbol": "TK", "type": "ERC-20"},
                             "total": {"value": "1000000"}}], "internal": []}
res = "ok"
try:
    c._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": "base", "txhash": HX, "wallets": [W], "snapshot": snap, "ts": 1}]), 0, 0)
except SystemExit as e:
    res = "SystemExit: " + str(e)[:90]
off = c.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream='evm'").fetchone()
check("K2 손상 토큰 캐시 = 소비 중 SystemExit 아님 · 오프셋 전진", res == "ok" and off is not None and tuple(off) == (0, 1), (res, off and tuple(off)))
check("K2 손상 캐시 원본은 그대로(수집기 파일 — core 가 덮지 않음)", open(os.path.join(paths.STATE_DIR, "rpc_token_meta_base.json")).read() == '{"0xabc": 6')

IP = os.path.join(paths.STATE_DIR, "asset_decimals_issues.json")
open(IP, "w").write('{"items": {"1": ')
res = []
for name, fn in (("prune", c._dec_issues_prune), ("pairs", c._dec_pending_pairs), ("issue", lambda: c._dec_issue(999, "conflict", 6, 18))):
    try:
        fn()
        res.append((name, "ok"))
    except SystemExit as e:
        res.append((name, "SystemExit " + str(e)[:60]))
check("K3 손상 표시 파일 = 기동 정리·재구축 칸·기록 모두 SystemExit 아님", all(r9 == "ok" for _n, r9 in res), res)
try:
    d9 = json.load(open(IP))
except ValueError:
    d9 = None
check("K3 기록은 새로 씀(읽히는 파일 · 그 항목)", isinstance(d9, dict) and (d9.get("items") or {}).get("999", {}).get("kind") == "conflict", d9)
T.finish()
