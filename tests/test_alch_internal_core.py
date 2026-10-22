#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402
from _ingest import check, W, Reader  # noqa: E402

import glob  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

json.dump({"chains": {"base": {"discovery": "rpc", "chain_id": 8453, "conf_depth": 10, "blocks_per_day": 43200, "rpcs": ["https://rpc.invalid"]}},
           "wallets": [{"type": "evm", "chain": "base", "address": W}], "native_symbol": {"base": "ETH"}, "backfill_months": 5},
          open(os.path.join(T.TMP, "config.json"), "w"))
import config, paths  # noqa: E402
import core  # noqa: E402

T.patch_moved("dm", lambda *a, **k: None)

E18 = 10 ** 18
NOW = int(time.time())
RT = "0x" + "e5" * 20
SD = paths.STATE_DIR
TS = NOW - 60 * 86400


def h(n):
    return "0x" + ("%064x" % n)


def reset():
    for p9 in glob.glob(os.path.join(SD, "*")):
        if os.path.isfile(p9):
            os.remove(p9)
    for p9 in glob.glob(os.path.join(SD, "inbox", "*")):
        if os.path.isfile(p9):
            os.remove(p9)


def new_core():
    c = core.Core(config.load_config())
    c.conn.commit()
    return c


def snap(hx, rows=(), status="ok", src=None):
    s = {"tx": {"hash": hx, "from": W, "to": RT, "value": "0", "fee": {"value": "0"}, "status": status, "raw_input": "0x12345678",
                "timestamp": TS, "block_number": 1000, "block_hash": "0x" + "d" * 64, "synth": "rpc"},
         "token_transfers": [], "internal": [{"from": f, "to": t, "value": str(v), "success": ok} for (f, t, v, ok) in rows]}
    if rows:
        s["internal_note"] = "trace"
    if src:
        s["internal_src"] = src
    return s


def feed(c, hx, s, repair=None):
    rec = {"v": 1, "kind": "evm_tx", "chain": "base", "txhash": hx, "wallets": [W], "snapshot": s, "ts": 1}
    if repair:
        rec["repair"] = repair
    c._drain_stream("evm", Reader([rec]), 0, 0)


def eth(c):
    r = c.conn.execute("SELECT asset_id FROM assets WHERE chain='base' AND kind='native'").fetchone()
    if not r:
        return 0
    return sum(int(x[0]) for x in c.conn.execute("SELECT qty_base FROM postings WHERE asset_id=? AND location=?", (r[0], f"wallet:base:{W}")))


def npost(c):
    return tuple(c.conn.execute("SELECT COUNT(*), MAX(posting_id) FROM postings").fetchone())


A5 = [(RT, W, 5 * E18, True)]
reset()
c = new_core()
feed(c, h(1), snap(h(1)))
e0 = eth(c)
feed(c, h(1), snap(h(1), A5, src="alchemy_transfers"), repair="int_fill")
e1 = eth(c)
check("C1 내부 이동 없이 먼저 기록된 tx → Alchemy 행 int_fill = +5 ETH", e1 - e0 == 5 * E18, (e0, e1))
n1 = npost(c)
feed(c, h(1), snap(h(1), A5), repair="int_fill")
check("C2 같은 tx trace 행(같은 이동) int_fill = 원장 무변(두 번 안 실림)", eth(c) == e1 and npost(c) == n1, (eth(c), e1, npost(c), n1))
feed(c, h(1), snap(h(1), A5, src="alchemy_transfers"), repair="int_fill")
check("C3 같은 Alchemy int_fill 재수신 = 원장 무변(멱등)", eth(c) == e1 and npost(c) == n1, (eth(c), npost(c), n1))
c.conn.close()

reset()
c = new_core()
feed(c, h(2), snap(h(2)))
e0 = eth(c)
feed(c, h(2), snap(h(2), A5 + A5, src="alchemy_transfers"), repair="int_fill")
e1 = eth(c)
feed(c, h(2), snap(h(2), A5 + A5), repair="int_fill")
check("C4 한 tx 같은 이동 두 건 = +10 · 뒤에 trace 두 건이 와도 +10(네 건 아님)", e1 - e0 == 10 * E18 and eth(c) == e1, (e0, e1, eth(c)))
c.conn.close()

reset()
c = new_core()
feed(c, h(3), snap(h(3), status="error"))
e0 = eth(c)
feed(c, h(3), snap(h(3), [(RT, W, 5 * E18, False)], status="error", src="alchemy_transfers"), repair="int_fill")
check("C5 실패 tx(행 success False) = 원장 0", eth(c) == e0, (e0, eth(c)))
c.conn.close()

reset()
c = new_core()
feed(c, h(4), snap(h(4), A5, src="alchemy_transfers"))
e1 = eth(c)
n1 = npost(c)
feed(c, h(4), snap(h(4), A5), repair="int_fill")
check("C6 처음부터 Alchemy 행으로 기록 = +5 · 뒤 trace int_fill = 무변", e1 == 5 * E18 and eth(c) == e1 and npost(c) == n1, (e1, eth(c), npost(c), n1))
c.conn.close()
T.finish()
