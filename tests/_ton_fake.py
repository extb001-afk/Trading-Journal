import base64
import hashlib
import json
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import ton_watch as tw
import address_codec as ac

NOW = int(time.time())


def K(byte_hex: str, wc: int = 0) -> str:
    return f"{wc}_" + byte_hex * 32


def raw(key: str) -> str:
    return ac.ton_raw(key).upper()


def b64h(hx: str) -> str:
    return base64.b64encode(bytes.fromhex(hx)).decode()


def _coins(v: int) -> str:
    if v == 0:
        return "0000"
    n = (v.bit_length() + 7) // 8
    return format(n, "04b") + format(v, f"0{8 * n}b")


def _addr(key) -> str:
    return "00" if key is None else tw.addr_bits(key)


def body_transfer(amount, dest, resp=None, qid=1, fwd_ton=0):
    bits = format(tw.OP_JETTON_TRANSFER, "032b") + format(qid, "064b") + _coins(amount) + _addr(dest) + _addr(resp) + "0" + _coins(fwd_ton) + "0"
    return tw.boc_one_cell(bits)


def body_internal(amount, frm, resp=None, qid=1, fwd_ton=0):
    bits = format(tw.OP_INTERNAL_TRANSFER, "032b") + format(qid, "064b") + _coins(amount) + _addr(frm) + _addr(resp) + _coins(fwd_ton) + "0"
    return tw.boc_one_cell(bits)


def body_burn(amount, resp=None, qid=1):
    bits = format(tw.OP_BURN, "032b") + format(qid, "064b") + _coins(amount) + _addr(resp) + "0"
    return tw.boc_one_cell(bits)


def body_bounced(op, amount, qid=1):
    bits = format(tw.OP_BOUNCED, "032b") + format(op, "032b") + format(qid, "064b") + _coins(amount)
    return tw.boc_one_cell(bits)


def body_simple(op, qid=1):
    return tw.boc_one_cell(format(op, "032b") + format(qid, "064b"))


class Chain:
    def __init__(self):
        self.txs = {}
        self.bal = {}
        self.lt = 1000000
        self.jw = []
        self.masters = {}
        self.gwa = {}
        self.hidden = set()
        self.no_state = set()
        self.states = {}
        self.jbal = {}
        self.tx_patch = {}
        self.acct_patch = {}
        self.jw_patch = {}

    def _h(self, *parts) -> str:
        return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()

    def tx(self, acct, now, in_msg=None, outs=(), tf=1000, aborted=False, fin="finalized", mc=1, fee_skew=0, state=True, trace=None):
        self.lt += 1000
        lt = self.lt
        h = self._h("tx", acct, lt)
        lst = self.txs.setdefault(acct, [])
        prev = lst[-1] if lst else None
        b0 = self.bal.get(acct, 0)
        im = None
        inv = 0
        if in_msg is not None:
            src = in_msg.get("src")
            inv = int(in_msg.get("val") or 0) if src else 0
            mh = in_msg.get("hash") or self._h("in", acct, lt)
            op = in_msg.get("op")
            im = {"hash": b64h(mh), "source": raw(src) if src else None, "destination": raw(acct),
                  "value": str(inv) if src else None, "value_extra_currencies": {}, "fwd_fee": "0" if src else None,
                  "opcode": (f"0x{op:08x}" if op is not None else None), "bounce": False, "bounced": bool(in_msg.get("bounced")),
                  "message_content": {"hash": b64h(self._h("c", mh)), "body": in_msg.get("body") or "te6cckEBAQEAAgAAAEysuc0=", "decoded": None}}
        om = []
        sent = 0
        for i, o in enumerate(outs):
            mh = self._h("out", acct, lt, i)
            v, f = int(o.get("val") or 0), int(o.get("fwd", 300))
            sent += v + f
            op = o.get("op")
            om.append({"hash": b64h(mh), "source": raw(acct), "destination": raw(o["dst"]), "value": str(v), "value_extra_currencies": {},
                       "fwd_fee": str(f), "opcode": (f"0x{op:08x}" if op is not None else None), "bounced": False,
                       "message_content": {"hash": b64h(self._h("c", mh)), "body": o.get("body") or "te6cckEBAQEAAgAAAEysuc0=", "decoded": None},
                       "_hex": mh})
        b1 = b0 + inv - sent - tf + fee_skew
        self.bal[acct] = b1
        t = {"account": raw(acct), "hash": b64h(h), "lt": str(lt), "now": int(now), "mc_block_seqno": mc, "trace_id": b64h(trace or h),
             "prev_trans_hash": b64h(prev["_hex"]) if prev else b64h("0" * 64), "prev_trans_lt": prev["lt"] if prev else "0",
             "orig_status": "active", "end_status": "active", "total_fees": str(tf), "total_fees_extra_currencies": {},
             "description": {"type": "ord", "aborted": bool(aborted), "destroyed": False},
             "in_msg": im, "out_msgs": om,
             "account_state_before": {"hash": b64h(self._h("s", h, 0)), "balance": str(b0) if state else None, "extra_currencies": {}},
             "account_state_after": {"hash": b64h(self._h("s", h, 1)), "balance": str(b1) if state else None, "extra_currencies": {}},
             "emulated": False, "finality": fin, "_hex": h}
        lst.append(t)
        return t

    @staticmethod
    def out_hex(t, i=0):
        return t["out_msgs"][i]["_hex"]

    @staticmethod
    def hx(t):
        return t["_hex"]

    def recv(self, src_tx, i, acct, now, tf=500, **kw):
        o = src_tx["out_msgs"][i]
        op = int(o["opcode"], 16) if o.get("opcode") else None
        return self.tx(acct, now, in_msg={"src": tw.akey(src_tx["account"]), "val": int(o["value"]), "op": op, "hash": o["_hex"],
                                          "body": o["message_content"]["body"]}, tf=tf, **kw)

    def add_jetton(self, owner, wallet, master, symbol="TKA", decimals="6", real=True, onchain=True):
        self.jw.append({"address": raw(wallet), "balance": "0", "owner": raw(owner), "jetton": raw(master),
                        "last_transaction_lt": "0", "code_hash": "x", "data_hash": "y"})
        if real:
            self.gwa[(master, owner)] = wallet
        else:
            self.gwa[(master, owner)] = K("ee")
        if master not in self.masters:
            jc = {"decimals": decimals} if onchain and decimals is not None else {"uri": "https://meta.invalid/x.json"}
            ti = {"valid": True, "type": "jetton_masters", "symbol": symbol, "is_scam": False, "extra": {}} if symbol else None
            self.masters[master] = (jc, ti)

    def strip(self, t):
        t2 = {k: v for k, v in t.items() if not k.startswith("_")}
        t2["out_msgs"] = [{k: v for k, v in m.items() if not k.startswith("_")} for m in t["out_msgs"]]
        if t["_hex"] in self.no_state:
            t2["account_state_before"] = dict(t2["account_state_before"], balance=None)
            t2["account_state_after"] = dict(t2["account_state_after"], balance=None)
        for k, v in (self.tx_patch.get(t["_hex"]) or {}).items():
            if v == "__del__":
                t2.pop(k, None)
            elif isinstance(v, dict) and isinstance(t2.get(k), dict):
                t2[k] = {kk: vv for kk, vv in dict(t2[k], **v).items() if vv != "__del__"}
            else:
                t2[k] = v
        return t2

    def visible(self, acct):
        return [t for t in self.txs.get(acct, []) if t["_hex"] not in self.hidden]

    def jw_rows(self):
        out = []
        for r in self.jw:
            w = tw.akey(r["address"])
            lst = self.visible(w)
            out.append(dict(dict(r, balance=str(self.jbal.get(w, 0)), last_transaction_lt=lst[-1]["lt"] if lst else "0"), **self.jw_patch.get(w, {})))
        return out


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj=None, raw_body=None, clen=None):
        b = raw_body if raw_body is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(clen if clen is not None else len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        self._route("GET", None)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self._route("POST", json.loads(self.rfile.read(n) or b"{}"))

    def _route(self, method, body):
        srv = self.server.fake
        u = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(u.query)
        path = u.path[len("/api/v3"):] if u.path.startswith("/api/v3") else u.path
        srv.log.append((method, path, {k: v for k, v in q.items()}, dict(self.headers)))
        for i, (pfx, kind) in enumerate(list(srv.faults)):
            if path.startswith(pfx):
                srv.faults.pop(i)
                if kind == "429":
                    return self._send(429, {"error": "rate limit"})
                if kind == "500":
                    return self._send(500, {"error": "boom"})
                if kind == "trunc":
                    return self._send(200, raw_body=b'{"transactions": [', clen=500)
                if kind == "badjson":
                    return self._send(200, raw_body=b"<html>oops</html>")
                if kind == "slow":
                    time.sleep(1.5)
                    return self._send(200, {"transactions": []})
                if kind == "errstack":
                    return self._send(200, {"error": "temporary failure", "stack": []})
                if kind == "errlist":
                    return self._send(200, {"error": "temporary failure", "transactions": [], "jetton_wallets": []})
                if kind == "empty":
                    return self._send(200, {"transactions": [], "jetton_wallets": [], "accounts": []})
                break
        ch = srv.ch
        g = lambda k, d=None: (q.get(k) or [d])[0]   # noqa: E731
        if path == "/transactions":
            acct = tw.akey(g("account"))
            rows = ch.visible(acct)
            if g("start_lt"):
                rows = [t for t in rows if int(t["lt"]) >= int(g("start_lt"))]
            if g("end_lt"):
                rows = [t for t in rows if int(t["lt"]) <= int(g("end_lt"))]
            rows = sorted(rows, key=lambda t: int(t["lt"]), reverse=(g("sort", "desc") == "desc"))
            off, lim = int(g("offset", 0)), int(g("limit", 10))
            return self._send(200, {"transactions": [ch.strip(t) for t in rows[off:off + lim]], "address_book": {}})
        if path == "/transactionsByMessage":
            mh = tw.hhex(g("msg_hash"))
            d = g("direction")
            out = []
            for lst in ch.txs.values():
                for t in lst:
                    if d == "in" and t["in_msg"] and tw.hhex(t["in_msg"]["hash"]) == mh:
                        out.append(ch.strip(t))
                    if d == "out" and any(m["_hex"] == mh for m in t["out_msgs"]):
                        out.append(ch.strip(t))
            return self._send(200, {"transactions": out, "address_book": {}})
        if path == "/jetton/wallets":
            rows = ch.jw_rows()
            if g("owner_address"):
                o = tw.akey(g("owner_address"))
                rows = [r for r in rows if tw.akey(r["owner"]) == o]
            if g("address"):
                a = tw.akey(g("address"))
                rows = [r for r in rows if tw.akey(r["address"]) == a]
            off, lim = int(g("offset", 0)), int(g("limit", 10))
            if srv.jw_cap:
                lim = min(lim, srv.jw_cap)
            return self._send(200, {"jetton_wallets": rows[off:off + lim], "address_book": {}, "metadata": {}})
        if path == "/jetton/masters":
            m = tw.akey(g("address"))
            if m not in ch.masters:
                return self._send(200, {"jetton_masters": [], "address_book": {}, "metadata": {}})
            jc, ti = ch.masters[m]
            md = {raw(m): {"is_indexed": True, "token_info": [ti]}} if ti else {}
            return self._send(200, {"jetton_masters": [{"address": raw(m), "jetton_content": jc}], "address_book": {}, "metadata": md})
        if path == "/accountStates":
            out = []
            for a in q.get("address") or []:
                k = tw.akey(a)
                lst = ch.visible(k)
                if not lst and k not in ch.states:
                    continue
                out.append(dict({"address": raw(k), "balance": str(ch.states.get(k, ch.bal.get(k, 0))), "status": "active",
                                 "last_transaction_lt": lst[-1]["lt"] if lst else "0",
                                 "last_transaction_hash": lst[-1]["hash"] if lst else None}, **ch.acct_patch.get(k, {})))
            return self._send(200, {"accounts": out, "address_book": {}, "metadata": {}})
        if path == "/runGetMethod" and method == "POST":
            m = tw.akey(body.get("address"))
            try:
                o = tw.Bits(tw.boc_root_bits(body["stack"][0]["value"])).addr()
            except Exception:   # noqa: BLE001
                return self._send(200, {"exit_code": 9, "stack": []})
            w = ch.gwa.get((m, o))
            if w is None:
                return self._send(200, {"exit_code": 11, "stack": []})
            return self._send(200, {"gas_used": 1, "exit_code": 0, "stack": [{"type": "cell", "value": tw.boc_one_cell(tw.addr_bits(w))}]})
        return self._send(404, {"error": "not found"})


class Server:
    def __init__(self, ch: Chain):
        self.ch = ch
        self.faults = []
        self.log = []
        self.jw_cap = None
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _H)
        self.httpd.fake = self
        self.httpd.daemon_threads = True

    def start(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/api/v3"

    def client(self, key="", timeout=5.0):
        op = urllib.request.build_opener(urllib.request.ProxyHandler({})).open
        return tw.TonClient({}, base=self.base, key=key, opener=op, min_interval=0, timeout=timeout)

    def calls(self, path=None):
        return [x for x in self.log if path is None or x[1] == path]
