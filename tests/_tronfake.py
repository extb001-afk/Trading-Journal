import json
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import address_codec as ac

TRANSFER = "ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
APPROVAL = "8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925"


def pad(k):
    return "0" * 24 + k[2:]


def T(k):
    return ac.tron_display(k)


def install_loop_open(bf_engine, T):
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _loop_open(req, timeout):
        u = str(getattr(req, "full_url", req))
        if not u.startswith("http://127.0.0.1:"):
            T.NET_TRIES.append("open " + u[:120])
            raise OSError("시험: 바깥 연결 차단")
        return opener.open(req, timeout=timeout)
    _loop_open._tj_test_mock = True
    bf_engine._open = _loop_open


class FakeTron:
    def __init__(self):
        self.txs = []
        self.by_id = {}
        self.accounts = {}
        self.v1 = {}
        self.tokbal = {}
        self.revert = set()
        self.tokmeta = {}
        self.head = [5000, int(time.time() * 1000) - 60_000, "0" * 64]
        self.head_step = 0
        self.inject = []
        self.unsolid = set()
        self.noinfo = set()
        self.no_fp = False
        self.bad_fp = set()
        self.delay = {}
        self.log = []
        self.lock = threading.Lock()
        fk = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, body):
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                st, b = fk.handle("GET", self.path, None, dict(self.headers))
                self._send(st, b)

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                st, b = fk.handle("POST", self.path, raw, dict(self.headers))
                self._send(st, b)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()

    def _add(self, txid, ts, blk, body, info, rows):
        tx = {"txid": txid, "ts": ts, "blk": blk, "body": body, "info": info, "rows": rows}
        self.txs.append(tx)
        self.by_id[txid] = tx
        return tx

    @staticmethod
    def _txrow(body, ts, blk):
        return dict(body, block_timestamp=ts, blockNumber=blk)

    def transfer(self, txid, ts, frm, to, amt, fee=0, blk=None):
        blk = blk or ts // 3000
        body = {"txID": txid, "raw_data": {"contract": [{"type": "TransferContract", "parameter": {"value": {
            "owner_address": frm, "to_address": to, "amount": amt}}}]}, "ret": [{"contractRet": "SUCCESS"}]}
        info = {"id": txid, "blockNumber": blk, "blockTimeStamp": ts, "receipt": {"net_usage": 267}}
        if fee:
            info["fee"] = fee
        row = self._txrow(body, ts, blk)
        return self._add(txid, ts, blk, body, info, [("tx", frm, row), ("tx", to, row)])

    def trc10(self, txid, ts, frm, to, amt, fee=0):
        blk = ts // 3000
        body = {"txID": txid, "raw_data": {"contract": [{"type": "TransferAssetContract", "parameter": {"value": {
            "owner_address": frm, "to_address": to, "amount": amt, "asset_name": "31303030303031"}}}]}, "ret": [{"contractRet": "SUCCESS"}]}
        info = {"id": txid, "blockNumber": blk, "blockTimeStamp": ts, "receipt": {"net_usage": 280}}
        if fee:
            info["fee"] = fee
        row = self._txrow(body, ts, blk)
        return self._add(txid, ts, blk, body, info, [("tx", frm, row), ("tx", to, row)])

    def call(self, txid, ts, sender, contract, logs=(), internals=(), call_value=0, fee=0, ret="SUCCESS", raw_logs=(), blk=None,
             list_value=None):
        blk = blk or ts // 3000
        val = {"owner_address": sender, "contract_address": contract, "data": "a9059cbb"}
        if call_value:
            val["call_value"] = call_value
        body = {"txID": txid, "raw_data": {"contract": [{"type": "TriggerSmartContract", "parameter": {"value": val}}]},
                "ret": [{"contractRet": ret}]}
        ok = ret == "SUCCESS"
        info = {"id": txid, "blockNumber": blk, "blockTimeStamp": ts, "contract_address": contract,
                "receipt": {"result": ret, "energy_usage_total": 30000}}
        if fee:
            info["fee"] = fee
            info["receipt"]["energy_fee"] = fee
        if not ok:
            info["result"] = "FAILED"
        rows = [("tx", sender, self._txrow(body, ts, blk))]
        lg = []
        if ok:
            for tok, f, t, v in logs:
                lg.append({"address": tok[2:], "topics": [TRANSFER, pad(f), pad(t)], "data": "%064x" % v})
                m = self.tokmeta.get(tok)
                ti = {"symbol": m[0], "address": T(tok), "decimals": m[1], "name": m[0]} if m and m[1] is not None else {}
                r = {"transaction_id": txid, "token_info": ti, "block_timestamp": ts, "from": T(f), "to": T(t), "type": "Transfer",
                     "value": str(v if list_value is None else list_value)}
                rows += [("trc20", f, r), ("trc20", t, r)]
            lg += list(raw_logs)
            info["log"] = lg
        its = []
        for i, (c, t, v, rej) in enumerate(internals):
            it = {"hash": "%064x" % (i + 1), "caller_address": c, "transferTo_address": t, "callValueInfo": [{"callValue": v}], "note": "63616c6c"}
            if rej or not ok:
                it["rejected"] = True
            its.append(it)
            r = {"internal_tx_id": "%064x" % (i + 100), "data": {"note": "call", "rejected": bool(rej or not ok), "call_value": {"_": v}},
                 "block_timestamp": ts, "to_address": t, "tx_id": txid, "from_address": c}
            rows += [("internal", c, r), ("internal", t, r)]
        if its:
            info["internal_transactions"] = its
        return self._add(txid, ts, blk, body, info, rows)

    def system(self, txid, ts, sender, ctype, value=None, info_extra=None, fee=0):
        blk = ts // 3000
        v = dict({"owner_address": sender}, **(value or {}))
        body = {"txID": txid, "raw_data": {"contract": [{"type": ctype, "parameter": {"value": v}}]}, "ret": [{"contractRet": "SUCCESS"}]}
        info = dict({"id": txid, "blockNumber": blk, "blockTimeStamp": ts, "receipt": {"net_usage": 300}}, **(info_extra or {}))
        if fee:
            info["fee"] = fee
        return self._add(txid, ts, blk, body, info, [("tx", sender, self._txrow(body, ts, blk))])

    def handle(self, method, path, raw, headers):
        with self.lock:
            self.log.append((method, path, raw, headers))
            for i, (sub, st, b) in enumerate(self.inject):
                if sub in path:
                    self.inject.pop(i)
                    return st, b
            dl = max([v for k, v in self.delay.items() if k in path] or [0])
        if dl:
            time.sleep(dl)
        u = urllib.parse.urlsplit(path)
        q = dict(urllib.parse.parse_qsl(u.query))
        parts = u.path.strip("/").split("/")
        try:
            if method == "GET" and parts[:2] == ["v1", "accounts"]:
                owner = ac.tron_key(parts[2])
                if len(parts) == 3:
                    it = self.v1.get(owner)
                    return 200, json.dumps({"data": [it] if it else [], "success": True, "meta": {"at": 1, "page_size": 1 if it else 0}}).encode()
                lst = {"transactions": "tx", "internal-transactions": "internal"}.get(parts[3]) if len(parts) == 4 else "trc20"
                return 200, self._list(owner, lst, q)
            body = json.loads(raw or b"{}")
            name = parts[-1]
            if name == "gettransactionbyid":
                tx = self.by_id.get(body.get("value"))
                return 200, json.dumps({} if (tx is None or tx["txid"] in self.unsolid) else tx["body"]).encode()
            if name == "gettransactioninfobyid":
                tx = self.by_id.get(body.get("value"))
                bad = tx is None or tx["txid"] in self.unsolid or tx["txid"] in self.noinfo
                return 200, json.dumps({} if bad else tx["info"]).encode()
            if name == "getaccount":
                return 200, json.dumps(self.accounts.get(body.get("address"), {})).encode()
            if name == "getblock":
                with self.lock:
                    h = list(self.head)
                    self.head[0] += self.head_step
                    self.head[1] += 3000 * self.head_step
                return 200, json.dumps({"blockID": h[2], "block_header": {"raw_data": {"number": h[0], "timestamp": h[1]}}}).encode()
            if name == "triggerconstantcontract":
                return 200, self._const(body)
        except Exception as e:   # noqa: BLE001
            return 500, json.dumps({"err": str(e)}).encode()
        return 404, b"{}"

    def _list(self, owner, lst, q):
        fp = q.get("fingerprint")
        if fp in self.bad_fp:
            return json.dumps({"success": False, "error": "fingerprint expired"}).encode()
        lo, hi = int(q.get("min_timestamp") or 0), q.get("max_timestamp")
        rows = [r for tx in self.txs for (l9, o9, r) in tx["rows"] if l9 == lst and o9 == owner and r.get("block_timestamp", 0) >= lo
                and (hi is None or r.get("block_timestamp", 0) <= int(hi))]
        rows.sort(key=lambda r: r["block_timestamp"])
        off = int(fp or 0)
        lim = int(q.get("limit") or 20)
        page = rows[off:off + lim]
        meta = {"at": int(time.time() * 1000), "page_size": len(page)}
        if off + lim < len(rows) and not self.no_fp:
            meta["fingerprint"] = str(off + lim)
        return json.dumps({"data": page, "success": True, "meta": meta}).encode()

    def _const(self, body):
        c, sel, par = body.get("contract_address"), body.get("function_selector"), body.get("parameter") or ""
        bad = {"result": {"code": "CONTRACT_VALIDATE_ERROR", "message": "72657665727465"}}
        if c in self.revert:
            return json.dumps(bad).encode()
        if sel == "balanceOf(address)":
            o = "41" + par[-40:]
            return json.dumps({"constant_result": ["%064x" % self.tokbal.get((c, o), 0)], "result": {"result": True}}).encode()
        m = self.tokmeta.get(c)
        if sel == "decimals()":
            if not m or m[1] is None:
                return json.dumps(bad).encode()
            return json.dumps({"constant_result": ["%064x" % m[1]], "result": {"result": True}}).encode()
        if sel == "symbol()":
            if not m:
                return json.dumps(bad).encode()
            sb = m[0].encode()
            h = "%064x" % 32 + "%064x" % len(sb) + sb.hex().ljust(64, "0")
            return json.dumps({"constant_result": [h], "result": {"result": True}}).encode()
        return json.dumps(bad).encode()
