import json
import os
import shutil
import sys

import _harness as T

TMP = T.TMP
TREE = T.ROOT
os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.makedirs(os.path.join(TMP, "state", "inbox"), exist_ok=True)
shutil.copytree(os.path.join(TREE, "seed"), os.path.join(TMP, "seed"))
W = "0x" + "1a" * 20


def write_cfg(extra=None):
    c = {"chains": {}, "wallets": [{"type": "evm", "chain": "base", "address": W}],
         "native_symbol": {"base": "ETH"}, "backfill_months": 5}
    c.update(extra or {})
    json.dump(c, open(os.path.join(TMP, "config.json"), "w"))


write_cfg()
sys.path.insert(0, os.path.join(TREE, "tools"))


def check(name, ok, detail=""):
    T.chk(bool(ok), name, None if ok else str(detail)[:700])


def done():
    T.finish()
