import json
import os
import shutil
import sqlite3
import threading
import time
import types

import _harness as T

LOGS = "http://127.0.0.1:9/logs"
DET = "http://127.0.0.1:9/detail"
W1 = "0x" + "a1" * 20
W2 = "0x" + "a2" * 20
OTHER = "0x" + "b0" * 20
HOT = "0x" + "c0" * 20
ROUTER = "0x" + "d0" * 20
TK = "0x" + "e1" * 20
USD = "0x" + "e2" * 20
H0 = 30_000_000
BSEC = 0.45
NOW0 = int(time.time())
BASE_T = NOW0 - int(H0 * BSEC)
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def cfg(**bsc):
    b = {"logs_rpcs": [LOGS], "detail_rpcs": [DET], "logs_sleep_sec": 0, "getlogs_span": 5000, "getlogs_span_max": 50000,
         "conf_depth": 20, "detail_batch": 8, "canary": False, "poll_sec": 30, "cycle_budget_sec": 3, "lane_budget_sec": 1.5}
    b.update(bsc)
    return {"backfill_months": 5, "bsc": b, "wallets": [{"type": "bsc_rpc", "address": W1}, {"type": "bsc_rpc", "address": W2}]}


with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump(cfg(), f)
import common
import bf_engine
import bsc_watch
import core

bf_engine.configure(cfg())
bsc_watch.CALL_SLEEP = 0
CPATH = os.path.join(common.STATE_DIR, "cursor_bsc.json")


def pad(a):
    return "0x" + a[2:].rjust(64, "0")


class Chain:

    def __init__(self):
        self.head = H0
        self.tx = {}
        self.mode = None
        self.old_below = None
        self.bad_rc = set()
        self.glog = []
        self.n = 0
        self.lock = threading.Lock()
        self.calls = {}

    def ts(self, b):
        return BASE_T + int(b * BSEC)

    def _h(self):
        self.n += 1
        return "0x" + format(0xABC0000 + self.n, "064x")

    def transfer(self, blk, token, frm, to, val, sender=OTHER):
        h = self._h()
        self.tx[h] = {"blk": blk, "from": sender, "to": token, "value": 0, "logs": [(token, frm, to, val)]}
        return h

    def native(self, blk, frm, to, val):
        h = self._h()
        self.tx[h] = {"blk": blk, "from": frm, "to": to, "value": val, "logs": []}
        return h

    def answer(self, url, m, p):
        with self.lock:
            self.calls[m] = self.calls.get(m, 0) + 1
        if m == "eth_blockNumber":
            return hex(self.head)
        if m == "eth_getBlockByNumber":
            b = int(p[0], 16)
            if not 0 <= b <= self.head:
                return None
            r = {"number": hex(b), "timestamp": hex(self.ts(b)), "hash": "0x" + format(b, "064x")}
            if len(p) > 1 and p[1] is True:
                r["transactions"] = [{"hash": h, "from": t["from"], "to": t["to"]} for h, t in sorted(self.tx.items()) if t["blk"] == b]
            return r
        if m == "eth_getLogs":
            q = p[0]
            a, b = int(q["fromBlock"], 16), int(q["toBlock"], 16)
            with self.lock:
                self.glog.append((a, b))
            if self.mode and self.old_below is not None and a < self.old_below:
                if self.mode == "pruned":
                    return {"_err": {"code": -32000, "message": "header not found"}}
                if self.mode == "429":
                    return {"_err": {"code": 429, "message": "Too Many Requests"}}
                if self.mode == "results":
                    return {"_err": {"code": -32005, "message": "query returned more than 10000 results"}}
                if self.mode == "slow":
                    time.sleep(0.02)
            tp = q["topics"]
            pos = 1 if len(tp) == 2 else 2
            want = {str(x).lower() for x in (tp[pos] or [])}
            out = []
            for h, t in sorted(self.tx.items()):
                if not (a <= t["blk"] <= b):
                    continue
                for j, (tok, fr, to, v) in enumerate(t["logs"]):
                    if pad(fr if pos == 1 else to) in want:
                        out.append({"transactionHash": h, "blockNumber": hex(t["blk"]), "logIndex": hex(j), "address": tok,
                                    "topics": [TRANSFER, pad(fr), pad(to)], "data": hex(v)})
            return out
        if m == "eth_getTransactionByHash":
            t = self.tx.get(p[0])
            if not t or t["blk"] > self.head:
                return None
            return {"hash": p[0], "from": t["from"], "to": t["to"], "value": hex(t["value"]), "input": "0x" if not t["logs"] else "0xa9059cbb",
                    "blockNumber": hex(t["blk"]), "blockHash": "0x" + format(t["blk"], "064x"), "gasPrice": hex(1)}
        if m == "eth_getTransactionReceipt":
            if p[0] in self.bad_rc:
                return {"_err": {"code": -32000, "message": "internal error (synthetic)"}}
            t = self.tx.get(p[0])
            if not t or t["blk"] > self.head:
                return None
            return {"status": "0x1", "gasUsed": hex(21000), "effectiveGasPrice": hex(1), "blockNumber": hex(t["blk"]),
                    "logs": [{"address": tok, "topics": [TRANSFER, pad(fr), pad(to)], "data": hex(v), "logIndex": hex(j)}
                             for j, (tok, fr, to, v) in enumerate(t["logs"])]}
        if m == "eth_call":
            if p[0]["data"] == "0x313ce567":
                return "0x" + format(18, "064x")
            s = b"SYN"
            return "0x" + format(32, "064x") + format(len(s), "064x") + s.hex().ljust(64, "0")
        if m == "eth_getTransactionCount":
            b = self.head if p[1] in ("latest", "pending") else int(p[1], 16)
            return hex(sum(1 for t in self.tx.values() if t["from"] == str(p[0]).lower() and t["blk"] <= b))
        if m == "eth_getCode":
            return "0x"
        if m == "eth_getBalance":
            return "0x0"
        return {"_err": {"code": -32601, "message": "method not mocked " + m}}


CH = Chain()


def fake_call(url, method, params, *, timeout=25.0, retries=2, prio="fg", deadline=None, allow_null=False, **kw):
    r = CH.answer(url, method, params)
    if isinstance(r, dict) and "_err" in r:
        e = bf_engine.classify_rpc_error(r["_err"])
        e.host = "127.0.0.1"
        raise e
    if r is None and not allow_null:
        raise bf_engine.NetError(f"rpc {method}: result null", "null", host="127.0.0.1")
    return r


def fake_batch(url, calls, *, timeout=30.0, retries=2, prio="fg", deadline=None, **kw):
    out = []
    for m, p in calls:
        try:
            out.append(fake_call(url, m, p))
        except bf_engine.NetError as e:
            out.append(e)
    return out


def fake_http_json(url, data=None, **kw):
    body = json.loads(data.decode() if isinstance(data, bytes) else data)

    def one(it):
        r = CH.answer(url, it["method"], it.get("params") or [])
        if isinstance(r, dict) and "_err" in r:
            return {"jsonrpc": "2.0", "id": it.get("id"), "error": r["_err"]}
        return {"jsonrpc": "2.0", "id": it.get("id"), "result": r}
    return [one(it) for it in body] if isinstance(body, list) else one(body)


fake_call._tj_test_mock = True
fake_batch._tj_test_mock = True
fake_http_json._tj_test_mock = True
bf_engine.rpc_call = fake_call
bf_engine.rpc_batch = fake_batch
bf_engine.http_json = fake_http_json
bsc_watch.NONCE_ARCH_GAP = 0


class Wr:
    def __init__(self):
        self.recs = []

    def append(self, rec):
        self.recs.append(rec)


def reset_state():
    shutil.rmtree(common.STATE_DIR, ignore_errors=True)
    os.makedirs(common.STATE_DIR, exist_ok=True)
    bf_engine._PROGRESS.clear()
    with bf_engine._EP_HEADS_LOCK:
        bf_engine._EP_HEADS.clear()
    CH.mode, CH.old_below = None, None


def exch_withdraw(txid, to):
    con = sqlite3.connect(common.DB_PATH)
    con.execute("CREATE TABLE IF NOT EXISTS raw_ex (exchange TEXT NOT NULL, kind TEXT NOT NULL, uuid TEXT NOT NULL, revision INTEGER NOT NULL,"
                " payload TEXT NOT NULL, observed_at INTEGER NOT NULL, PRIMARY KEY (exchange, kind, uuid, revision))")
    con.execute("CREATE TABLE IF NOT EXISTS raw_txs (chain TEXT, txhash TEXT, block INTEGER, snapshot TEXT)")
    con.execute("INSERT INTO raw_ex VALUES ('synex', 'withdraw', ?, 1, ?, ?)",
                (txid[-12:], json.dumps({"currency": "BNB", "state": "DONE", "txid": txid, "network": "BSC", "address": to}), NOW0))
    con.commit()
    con.close()


def mk(c=None, wr=None):
    c = c or cfg()
    return bsc_watch.BscWatcher(c, [W1, W2], wr or Wr())


def emitted(wr):
    return [r["txhash"] for r in wr.recs]


def scope_ready():
    stub = types.SimpleNamespace(_synced=core.Core._synced, sol_wallets=set(), my_wallets={})
    return core.Core._scope_ready(stub, "bsc")


def cur():
    return common.read_json(CPATH, {})


def cycle(w):
    return T.safe(w.cycle)


WIN_BLK = int((NOW0 - 150 * 86400 - BASE_T) / BSEC)
