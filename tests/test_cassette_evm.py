#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _cassette as C  # noqa: E402

C.freeze()
import json  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402

E18 = 10 ** 18
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
W1 = "0x" + "a1" * 20
W2 = "0x" + "b2" * 20
X = "0x" + "c3" * 20
USDC = "0x" + "d4" * 20
NODE_KEY = "casEVMnodeKEY01"
RPC = "https://base-node.cassette.invalid/v2/" + NODE_KEY
HEAD0 = 2_000_000
BSEC = 2
T0 = int(C.NOW) - BSEC * HEAD0
START = HEAD0 - 2_000


def pad(a):
    return "0x" + a[2:].rjust(64, "0")


class Chain:

    def __init__(self):
        self.head = HEAD0
        self.txs, self.order = {}, []
        self.lock = threading.Lock()

    def add(self, blk, frm, to, value=0):
        h = "0x%064x" % (0xC0DE0000 + len(self.order) + 1)
        n = sum(1 for x in self.order if self.txs[x]["from"] == frm)
        self.txs[h] = {"hash": h, "block": blk, "from": frm, "to": to, "value": value, "nonce": n, "gas": 21000, "price": 10 ** 7, "input": "0x",
                       "logs": []}
        self.order.append(h)
        self.order.sort(key=lambda x: (self.txs[x]["block"], x))
        return h

    def usdc(self, blk, frm, to, amount):
        h = self.add(blk, frm, USDC)
        self.txs[h].update(gas=50_000, input="0xa9059cbb",
                           logs=[{"address": USDC, "topics": [TRANSFER, pad(frm), pad(to)], "data": hex(amount), "idx": 0}])
        return h

    def state(self, a, blk):
        n, bal = 0, 0
        for h in self.order:
            t = self.txs[h]
            if t["block"] > blk:
                break
            if t["from"] == a:
                n += 1
                bal -= t["gas"] * t["price"] + t["value"]
            if t["to"] == a:
                bal += t["value"]
        return n, bal

    def txobj(self, t):
        return {"hash": t["hash"], "from": t["from"], "to": t["to"], "value": hex(t["value"]), "nonce": hex(t["nonce"]),
                "blockNumber": hex(t["block"]), "blockHash": "0x%064x" % (t["block"] + 7), "gasPrice": hex(t["price"]), "type": "0x2",
                "input": t["input"], "transactionIndex": "0x0"}

    def one(self, m, p):
        if m == "eth_blockNumber":
            return hex(self.head)
        if m == "eth_chainId":
            return hex(8453)
        if m in ("eth_getBalance", "eth_getTransactionCount"):
            blk = self.head if p[1] == "latest" else int(p[1], 16)
            n, bal = self.state(p[0].lower(), blk)
            return hex(n if m == "eth_getTransactionCount" else bal)
        if m == "eth_getBlockByNumber":
            b = self.head if p[0] == "latest" else int(p[0], 16)
            if b > self.head:
                return None
            txs = [self.txs[h] for h in self.order if self.txs[h]["block"] == b]
            return {"number": hex(b), "hash": "0x%064x" % (b + 7), "timestamp": hex(T0 + BSEC * b),
                    "transactions": [self.txobj(t) for t in txs] if p[1] else [t["hash"] for t in txs]}
        if m == "eth_getTransactionByHash":
            t = self.txs.get(p[0].lower())
            return self.txobj(t) if t and t["block"] <= self.head else None
        if m == "eth_getTransactionReceipt":
            t = self.txs.get(p[0].lower())
            if not t or t["block"] > self.head:
                return None
            return {"transactionHash": t["hash"], "blockNumber": hex(t["block"]), "blockHash": "0x%064x" % (t["block"] + 7),
                    "gasUsed": hex(t["gas"]), "effectiveGasPrice": hex(t["price"]), "status": "0x1", "from": t["from"], "to": t["to"],
                    "logs": [{"address": lg["address"], "topics": lg["topics"], "data": lg["data"], "blockNumber": hex(t["block"]),
                              "transactionHash": t["hash"], "logIndex": hex(lg["idx"])} for lg in t["logs"]]}
        if m == "eth_call":
            data, to = p[0]["data"], p[0]["to"].lower()
            if to != USDC:
                return {"__err": {"code": 3, "message": "execution reverted"}}
            if data == "0x313ce567":
                return "0x" + "6".rjust(64, "0")
            if data == "0x95d89b41":
                s = b"USDC"
                return "0x" + (32).to_bytes(32, "big").hex() + len(s).to_bytes(32, "big").hex() + s.ljust(32, b"\0").hex()
            return "0x" + "0" * 64
        if m == "eth_getLogs":
            f = p[0]
            a, b = int(f["fromBlock"], 16), int(f["toBlock"], 16)
            tps = f.get("topics") or []
            out = []
            for h in self.order:
                t = self.txs[h]
                if not (a <= t["block"] <= b) or t["block"] > self.head:
                    continue
                for lg in t["logs"]:
                    ok = True
                    for i, cond in enumerate(tps):
                        if cond is None:
                            continue
                        cs = cond if isinstance(cond, list) else [cond]
                        if i >= len(lg["topics"]) or lg["topics"][i] not in cs:
                            ok = False
                            break
                    if ok:
                        out.append({"address": lg["address"], "topics": lg["topics"], "data": lg["data"], "blockNumber": hex(t["block"]),
                                    "transactionHash": t["hash"], "logIndex": hex(lg["idx"]), "blockHash": "0x%064x" % (t["block"] + 7)})
            return out
        return {"__err": {"code": -32601, "message": f"the method {m} does not exist"}}

    def respond(self, rq):
        assert rq.host == "base-node.cassette.invalid", rq.url
        body = rq.json()

        def res(it):
            r = self.one(it["method"], it.get("params") or [])
            if isinstance(r, dict) and "__err" in r:
                return {"jsonrpc": "2.0", "id": it.get("id"), "error": r["__err"]}
            return {"jsonrpc": "2.0", "id": it.get("id"), "result": r}
        return [res(x) for x in body] if isinstance(body, list) else res(body)


CH = Chain()
CH.add(START - 100, X, W1, value=E18 // 2)
CH.usdc(HEAD0 - 1_500, X, W2, 5_000_000)
CH.usdc(HEAD0 - 1_200, W1, X, 1_250_000)
CH.add(HEAD0 - 900, X, W1, value=E18)
CH.usdc(HEAD0 - 300, X, W1, 8_800_000)
CFG = {"backfill_months": 1,
       "chains": {"base": {"chain_id": 8453, "rpcs": [RPC], "rpc_logs": [RPC], "trace_rpcs": [], "multicall3": False, "conf_depth": 10,
                           "blocks_per_day": 43200, "poll_sec": 60, "cycle_budget_sec": 120, "getlogs_span": 5000,
                           "rpc_log_span_caps": {RPC: 5000}, "start_block": START}},
       "wallets": [{"type": "evm", "chain": "base", "address": w, "label": "w"} for w in (W1, W2)],
       "native_symbol": {"base": "ETH"},
       "backfill": {"hosts": {"base-node.cassette.invalid": {"rate": 5000, "burst": 5000, "conc": 8}}}}
with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump(CFG, f)
import config, paths  # noqa: E402
import bf_engine  # noqa: E402
import evm_watch  # noqa: E402
from inbox import SegmentWriter  # noqa: E402

cas = C.Cassette("evm_rpc", secrets={"node_key": NODE_KEY}, responder=CH.respond)


def scenario():
    paths.ensure_dirs()
    cfg = config.load_config()
    bf_engine.configure(cfg)
    wr = SegmentWriter(os.path.join(paths.INBOX_DIR, "evm"))

    def make(cfg9, chain, addrs):
        return evm_watch.build_watcher(cfg9, chain, addrs, wr, "")
    wt = make(cfg, "base", [W1, W2])
    lp = evm_watch.ChainLoop(cfg, wt, make, "", wr)
    r1 = lp.step()
    CH.head = HEAD0 + 30
    CH.usdc(HEAD0 + 12, X, W2, 2_500_000)
    C.CLOCK.now += 60
    r2 = lp.step()
    return {"step": [r1, r2], "watcher": type(lp.wt).__name__}


if cas.ready(T):
    out, why = cas.run(scenario)
    T.chk(why is None and out == {"step": [True, True], "watcher": "RpcChainWatcher"}, "두 주기 정상 끝(RpcChainWatcher)", [why, out])
    snap = C.snap_tree(paths.STATE_DIR)
    recs = [r for k, v in snap.items() if k.startswith("inbox/evm/") for r in v]
    T.chk(len(recs) >= 5, "inbox evm 레코드 = 합성 체인 이동(토큰 4 · 네이티브 1)", len(recs))
    cas.golden(T, snap)
    cas.check(T)
T.finish()
