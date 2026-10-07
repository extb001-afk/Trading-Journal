import json
import os
import shutil

import _harness as T

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "state", "inbox"), exist_ok=True)
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
_lp = os.path.join(T.ROOT, "seed", "lp_managers.json")
if os.path.exists(_lp):
    shutil.copy(_lp, os.path.join(T.TMP, "seed", "lp_managers.json"))
else:
    json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
W = "0x" + "a1" * 20
SOLW = "So1" + "1" * 41
CFG = {"chains": {"eth": {"blockscout": "https://bs.invalid", "etherscan_chainid": 1, "conf_depth": 12, "blocks_per_day": 7200,
                          "rpcs": ["https://rpc.invalid"]},
                  "base": {"blockscout": "https://bs2.invalid", "conf_depth": 12, "blocks_per_day": 43200, "rpcs": ["https://rpc2.invalid"]}},
       "wallets": [{"type": "evm", "chain": "eth", "address": W}, {"type": "evm", "chain": "base", "address": W},
                   {"type": "sol", "address": SOLW}],
       "native_symbol": {"eth": "ETH", "base": "ETH"}, "backfill_months": 5,
       "sol": {"rpcs": ["https://solrpc.invalid"]}}
json.dump(CFG, open(os.path.join(T.TMP, "config.json"), "w"))


def check(name, ok, detail=""):
    T.chk(bool(ok), name, None if ok else str(detail)[:700])


class Writer:
    def __init__(self):
        self.recs = []

    def append(self, r):
        self.recs.append(json.loads(json.dumps(r)))


class Reader:

    def __init__(self, recs):
        self.recs = recs

    def read_batch(self, seg, off):
        return [(r, 0, i + 1) for i, r in enumerate(self.recs)], 0, len(self.recs)

    def gc(self, seg, off):
        pass
