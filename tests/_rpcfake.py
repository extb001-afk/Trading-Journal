import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DOWN = object()


class Node:
    def __init__(self, fn):
        self.fn = fn
        self.calls = []
        self.lock = threading.Lock()
        nd = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"null")
                items = body if isinstance(body, list) else [body]
                out = []
                for it in items:
                    with nd.lock:
                        nd.calls.append((it.get("method"), it.get("params")))
                    try:
                        r = nd.fn(it.get("method"), it.get("params"))
                    except Exception as e:   # noqa: BLE001
                        out.append({"jsonrpc": "2.0", "id": it.get("id"), "error": {"code": 3, "message": "execution reverted: " + str(e)}})
                        continue
                    if r is DOWN:
                        self.send_response(500)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    out.append({"jsonrpc": "2.0", "id": it.get("id"), "result": r})
                b = json.dumps(out if isinstance(body, list) else out[0]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/rpc"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def loop_open(bf_engine, T):
    import _tronfake
    _tronfake.install_loop_open(bf_engine, T)


TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def pad(a):
    return "0x" + a[2:].rjust(64, "0")


class Chain:

    def __init__(self, head, token, start_ts, bal=10 ** 18, symbol=b"TKJ", decimals=6):
        self.head, self.token, self.t0, self.bal = int(head), token.lower(), int(start_ts), int(bal)
        self.symbol, self.decimals = symbol, decimals
        self.txs = {}
        self.forks = []
        self.flap = {}
        self.null = {}
        self.nat = {}
        self.lock = threading.Lock()
        self.n = 0

    def bhash(self, b):
        k = sum(1 for f in self.forks if b >= f)
        return "0x%064x" % (int(b) * 1000 + 7 + k * 10 ** 15)

    def transfer(self, blk, frm, to, amount):
        with self.lock:
            self.n += 1
            h = "0x%064x" % (self.n + 10 ** 12 + 10 ** 20 * len(self.forks))
        self.txs[h] = {"hash": h, "block": int(blk), "from": frm.lower(), "to": to.lower(), "amount": int(amount)}
        return h

    def reorg(self, n, drop=(), add=()):
        self.forks.append(int(n))
        for h in drop:
            self.txs.pop(h, None)
        return [self.transfer(*a) for a in add]

    def _tx(self, t):
        return {"hash": t["hash"], "from": t["from"], "to": self.token, "value": "0x0", "nonce": "0x0", "blockNumber": hex(t["block"]),
                "blockHash": self.bhash(t["block"]), "gasPrice": "0x1", "type": "0x2", "input": "0xa9059cbb", "transactionIndex": "0x0"}

    def _log(self, t):
        return {"address": self.token, "topics": [TRANSFER, pad(t["from"]), pad(t["to"])], "data": "0x%064x" % t["amount"],
                "blockNumber": hex(t["block"]), "blockHash": self.bhash(t["block"]), "transactionHash": t["hash"], "logIndex": "0x0"}

    def one(self, m, p):
        if m == "eth_blockNumber":
            return hex(self.head)
        if m in ("eth_getBalance", "eth_getTransactionCount"):
            b9 = int(p[1], 16) if len(p) > 1 and str(p[1]).startswith("0x") else self.head
            return hex(self.bal + sum(v for k, v in self.nat.items() if k <= b9)) if m == "eth_getBalance" else "0x0"
        if m == "eth_getBlockByNumber":
            b = int(p[0], 16)
            if b > self.head:
                return None
            hs = self.bhash(b)
            with self.lock:
                if self.null.get(b, 0) > 0:
                    self.null[b] -= 1
                    return None
                if self.flap.get(b, 0) > 0:
                    self.flap[b] -= 1
                    hs = "0x" + "ee" * 32
            txs = [t for t in self.txs.values() if t["block"] == b]
            return {"number": hex(b), "hash": hs, "parentHash": self.bhash(b - 1), "timestamp": hex(self.t0 + 2 * b),
                    "transactions": [self._tx(t) for t in txs] if p[1] else [t["hash"] for t in txs]}
        if m in ("eth_getTransactionByHash", "eth_getTransactionReceipt"):
            t = self.txs.get(str(p[0]).lower())
            if not t or t["block"] > self.head:
                return None
            if m == "eth_getTransactionByHash":
                return self._tx(t)
            return {"transactionHash": t["hash"], "blockNumber": hex(t["block"]), "blockHash": self.bhash(t["block"]), "gasUsed": hex(50000),
                    "effectiveGasPrice": "0x1", "status": "0x1", "from": t["from"], "to": self.token, "logs": [self._log(t)]}
        if m == "eth_call":
            data = p[0].get("data") or p[0].get("input")
            if str(p[0].get("to")).lower() != self.token:
                raise RuntimeError("no code")
            if data == "0x313ce567":
                return "0x" + hex(self.decimals)[2:].rjust(64, "0")
            if data == "0x95d89b41":
                s = self.symbol
                return "0x" + (32).to_bytes(32, "big").hex() + len(s).to_bytes(32, "big").hex() + s.ljust(32, b"\0").hex()
            return "0x" + "0" * 64
        if m == "eth_getLogs":
            f = p[0]
            a, b = int(f["fromBlock"], 16), int(f["toBlock"], 16)
            tps = f.get("topics") or []
            out = []
            for t in sorted(self.txs.values(), key=lambda x: (x["block"], x["hash"])):
                if not (a <= t["block"] <= min(b, self.head)):
                    continue
                lg = self._log(t)
                if all(c is None or lg["topics"][i] in (c if isinstance(c, list) else [c]) for i, c in enumerate(tps) if i < len(lg["topics"])):
                    out.append(lg)
            return out
        raise RuntimeError(f"the method {m} does not exist")
