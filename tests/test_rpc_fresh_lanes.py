#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import glob
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _loop_urlopen(url, data=None, timeout=30, *a, **k):
    u = getattr(url, "full_url", url)
    if urllib.parse.urlsplit(str(u)).hostname not in ("127.0.0.1", "localhost"):
        return T._guard_urlopen(url, data, timeout, *a, **k)
    return _OP.open(url, data=data, timeout=timeout)


_loop_urlopen._tj_test_mock = True

E18 = 10 ** 18
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
W1 = "0x" + "a1" * 20
W2 = "0x" + "b2" * 20
X = "0x" + "c3" * 20
USDC = "0x" + "d4" * 20
HEAD0 = 1_500_000
T0 = int(time.time()) - 2 * HEAD0
LOG_DELAY = 0.004


def pad(a):
    return "0x" + a[2:].rjust(64, "0")


class Chain:
    def __init__(self):
        self.head = HEAD0
        self.txs, self.order = {}, []
        self.lock = threading.Lock()
        self.n_logs = 0
        self.fail_receipt = {}

    def add(self, blk, frm, to, value=0, logs=(), gas=21000, price=10 ** 7, inp="0x", internal=()):
        h = "0x%064x" % (len(self.order) + 1 + blk * 1000)
        n = sum(1 for x in self.order if self.txs[x]["from"] == frm)
        self.txs[h] = {"hash": h, "block": blk, "from": frm, "to": to, "value": value, "nonce": n, "logs": [dict(lg, idx=i) for i, lg in enumerate(logs)],
                       "gas": gas, "price": price, "input": inp, "internal": list(internal)}
        self.order.append(h)
        self.order.sort(key=lambda x: (self.txs[x]["block"], x))
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
            for (f2, t2, v2) in t["internal"]:
                bal += v2 if t2 == a else 0
                bal -= v2 if f2 == a else 0
        return n, bal

    def txobj(self, t):
        return {"hash": t["hash"], "from": t["from"], "to": t["to"], "value": hex(t["value"]), "nonce": hex(t["nonce"]), "blockNumber": hex(t["block"]),
                "blockHash": "0x%064x" % (t["block"] + 7), "gasPrice": hex(t["price"]), "type": "0x2", "input": t["input"]}

    def one(self, m, p, prof):
        if m == "eth_blockNumber":
            return hex(self.head)
        if m == "eth_chainId":
            return hex(8453)
        if m in ("eth_getBalance", "eth_getTransactionCount"):
            blk = self.head if p[1] == "latest" else int(p[1], 16)
            if STATE_CAP.get("max") is not None and blk > STATE_CAP["max"]:
                return {"__err": {"code": -32000, "message": "header not found"}}
            if prof.get("state_win") and blk < self.head - prof["state_win"]:
                return {"__err": {"code": -32000, "message": "missing trie node 5b05 (path ) state is not available"}}
            n, bal = self.state(p[0].lower(), blk)
            return hex(n if m == "eth_getTransactionCount" else bal)
        if m == "eth_getBlockByNumber":
            b = int(p[0], 16)
            if b > self.head:
                return None
            txs = [self.txs[h] for h in self.order if self.txs[h]["block"] == b]
            return {"number": hex(b), "hash": "0x%064x" % (b + 7), "timestamp": hex(T0 + 2 * b),
                    "transactions": [self.txobj(t) for t in txs] if p[1] else [t["hash"] for t in txs]}
        if m == "eth_getTransactionByHash":
            t = self.txs.get(p[0].lower())
            return self.txobj(t) if t and t["block"] <= self.head else None
        if m == "eth_getTransactionReceipt":
            t = self.txs.get(p[0].lower())
            if not t or t["block"] > self.head:
                return None
            with self.lock:
                if self.fail_receipt.get(t["hash"], 0) > 0:
                    self.fail_receipt[t["hash"]] -= 1
                    return {"__err": {"code": -32000, "message": "internal error (injected)"}}
            return {"transactionHash": t["hash"], "blockNumber": hex(t["block"]), "blockHash": "0x%064x" % (t["block"] + 7), "gasUsed": hex(t["gas"]),
                    "effectiveGasPrice": hex(t["price"]), "status": "0x1",
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
        if m == "debug_traceTransaction" and prof.get("trace_ok"):
            t = self.txs.get(p[0].lower())
            if not t:
                return {"__err": {"code": -32000, "message": "transaction not found"}}
            return {"type": "CALL", "from": t["from"], "to": t["to"], "value": hex(t["value"]),
                    "calls": [{"type": "CALL", "from": f2, "to": t2, "value": hex(v2)} for (f2, t2, v2) in t["internal"]]}
        if m == "debug_traceBlockByNumber" and prof.get("trace_ok"):
            b = int(p[0], 16)
            return [{"txHash": h, "result": self.one("debug_traceTransaction", [h], prof)} for h in self.order if self.txs[h]["block"] == b]
        if m.startswith("debug_trace") or m.startswith("trace_"):
            if prof.get("trace_fail"):
                return {"__err": {"code": -32000, "message": "Request timeout on the free tier, please upgrade your tier to the paid one"}, "__http": 408}
            return {"__err": {"code": -32601, "message": f"the method {m} does not exist"}}
        if m == "eth_getLogs" and prof.get("logs_fail"):
            return {"__err": {"code": -32000, "message": "internal server error"}}
        if m == "eth_getLogs":
            f = p[0]
            a, b = int(f["fromBlock"], 16), int(f["toBlock"], 16)
            with self.lock:
                self.n_logs += 1
            time.sleep(LOG_DELAY)
            if prof.get("log_floor") and a < prof["log_floor"]:
                return {"__err": {"code": -32000, "message": f"pruned history unavailable: requested {a}, earliest available {prof['log_floor']}"}}
            if b - a + 1 > prof["cap"]:
                return {"__err": {"code": -32600, "message": f"You can make eth_getLogs requests with up to a {prof['cap']} block range."}}
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
                                    "transactionHash": t["hash"], "logIndex": hex(lg["idx"])})
            return out
        return {"__err": {"code": -32601, "message": f"the method {m} does not exist"}}


CH = Chain()
STATE_CAP = {"max": None}


def mk_handler(prof):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            http9 = []

            def res(it):
                r = CH.one(it["method"], it.get("params") or [], prof)
                if isinstance(r, dict) and "__err" in r:
                    if r.get("__http"):
                        http9.append(r["__http"])
                    return {"jsonrpc": "2.0", "id": it.get("id"), "error": r["__err"]}
                return {"jsonrpc": "2.0", "id": it.get("id"), "result": r}
            out = [res(x) for x in body] if isinstance(body, list) else res(body)
            data = json.dumps(out).encode()
            self.send_response(http9[0] if (http9 and not isinstance(body, list)) else 200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    return H


URL = {}
LOG_FLOOR = HEAD0 - 30 * 43200 + 100_000
for k9, pr9 in {"arch": {"cap": 2000}, "nonarch": {"cap": 2000, "state_win": 3000}, "ret": {"cap": 2000, "log_floor": LOG_FLOOR},
                 "t408": {"cap": 2000, "trace_fail": True}, "trok": {"cap": 2000, "trace_ok": True},
                 "nonarch_tr": {"cap": 2000, "state_win": 3000, "trace_ok": True}, "nolog": {"cap": 2000, "logs_fail": True}}.items():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), mk_handler(pr9))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    URL[k9] = f"http://127.0.0.1:{srv.server_address[1]}/rpc"


def ccfg(node="arch", **kw):
    c = {"chain_id": 8453, "rpcs": [URL[node]], "rpc_logs": [URL[node]], "trace_rpcs": [], "multicall3": False, "conf_depth": 10,
         "blocks_per_day": 43200, "poll_sec": 60, "cycle_budget_sec": 4.0, "rpc_backfill_budget_sec": 0.6, "getlogs_span": 2000,
         "rpc_log_span_caps": {URL[node]: 2000}, "rpc_handover": "adopt"}
    c.update(kw)
    return c


CFG = {"backfill_months": 1, "chains": {"base": ccfg()},
       "wallets": [{"type": "evm", "chain": "base", "address": w, "label": "w"} for w in (W1, W2)],
       "native_symbol": {"base": "ETH"}, "backfill": {"hosts": {"127.0.0.1": {"rate": 5000, "burst": 5000, "conc": 8}}}}
with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump(CFG, f)
import common
import bf_engine
import evm_watch

evm_watch._dm = lambda *a, **k: None
bf_engine.urllib.request.urlopen = _loop_urlopen
bf_engine.configure(CFG)
SD = common.STATE_DIR
CP = os.path.join(SD, "cursor_evm_base.json")

START_EXPECT = HEAD0 - 30 * 43200
H = {}
H["old_nat"] = CH.add(START_EXPECT + 5_000, X, W1, value=2 * E18)
H["old_usdc"] = CH.add(START_EXPECT + 40_000, X, USDC, logs=[{"address": USDC, "topics": [TRANSFER, pad(X), pad(W2)], "data": hex(5_000_000)}],
                       gas=50_000, inp="0xa9059cbb")
H["mid_usdc"] = CH.add(START_EXPECT + 150_000, X, USDC, logs=[{"address": USDC, "topics": [TRANSFER, pad(X), pad(W2)], "data": hex(7_000_000)}],
                       gas=50_000, inp="0xa9059cbb")
H["recent_nat"] = CH.add(HEAD0 - 20_000, X, W2, value=E18)
RT = "0x" + "e5" * 20
H["recent_int"] = CH.add(HEAD0 - 30_000, X, RT, internal=[(RT, W1, 3 * E18 // 10)], gas=90_000, inp="0xbbbbbbbb")
H["old_int"] = CH.add(START_EXPECT + 70_000, X, RT, internal=[(RT, W2, 2 * E18 // 10)], gas=90_000, inp="0xbbbbbbbb")
H["fresh_nat"] = CH.add(HEAD0 - 500, X, W1, value=E18 // 2)
H["sweep_usdc"] = CH.add(HEAD0 - 19_000, X, USDC, logs=[{"address": USDC, "topics": [TRANSFER, pad(X), pad(W2)], "data": hex(3_300_000)}],
                         gas=50_000, inp="0xa9059cbb")
H["bk_mixed"] = CH.add(START_EXPECT + 90_000, X, RT, logs=[{"address": USDC, "topics": [TRANSFER, pad(RT), pad(W1)], "data": hex(9_000_000)}],
                       internal=[(RT, W1, E18 // 20)], gas=120_000, inp="0xcccccccc")
H["newest_nat"] = CH.add(HEAD0 - 40, X, W1, value=E18 // 4)
H["peek_int"] = CH.add(HEAD0 - 100, X, RT, internal=[(RT, W1, E18 // 7)], gas=90_000, inp="0xbbbbbbbb")
H["peek_nat2"] = CH.add(HEAD0 - 80, X, W2, value=E18 // 9)
H["newest"] = CH.add(HEAD0 - 60, X, USDC, logs=[{"address": USDC, "topics": [TRANSFER, pad(X), pad(W2)], "data": hex(4_400_000_000)}],
                     gas=50_000, inp="0xa9059cbb")
H["recent_usdc"] = CH.add(HEAD0 - 2_000, X, USDC, logs=[{"address": USDC, "topics": [TRANSFER, pad(X), pad(W1)], "data": hex(8_800_000_000)}],
                          gas=50_000, inp="0xa9059cbb")


class Wr:
    def __init__(self):
        self.recs = []

    def append(self, rec):
        self.recs.append(rec)

    def hashes(self):
        return {r["txhash"] for r in self.recs}


def reset_state():
    for p9 in glob.glob(os.path.join(SD, "*")):
        if os.path.isfile(p9):
            os.remove(p9)
    bf_engine._PROGRESS.clear()
    CH.head = HEAD0


def new_watcher(cfg, wr):
    return evm_watch.RpcChainWatcher(cfg, "base", [W1, W2], wr)


def cyc(w):
    return T.safe(w.cycle)


def cur():
    return common.read_json(CP, {})


reset_state()
wr = Wr()
w = new_watcher(CFG, wr)
t0 = time.time()
r1 = cyc(w)
el1 = time.time() - t0
c1 = cur()
T.chk(not isinstance(r1, dict), "F1 첫 주기 예외 없음", r1)
T.chk(H["recent_usdc"] in wr.hashes(),
      "F1 ★빈 상태 새 설치본 첫 주기 안에 1시간 전 USDC 입금 방출★(종전 = 창 시작부터 순서대로 — 옛 기록을 다 따라잡기 전엔 못 봄)",
      {"emitted": sorted(h[-6:] for h in wr.hashes()), "cursor": {k: v for k, v in c1.items() if not k.startswith("_")}, "el": round(el1, 2)})
T.chk(H["recent_nat"] in wr.hashes(), "F1 최근 창 안 로그 없는 네이티브 입금(11시간 전)도 첫 주기에 방출(라이브 기준점 = 아카이브 상태 · 정합 이분 탐색)",
      sorted(h[-6:] for h in wr.hashes()))
ho1 = c1.get("_handover") if isinstance(c1.get("_handover"), dict) else {}
jobs1 = {k[4:]: v for k, v in c1.items() if k.startswith("_bk:")}
T.chk(ho1.get("from") == "fresh" and set(jobs1) == {W1, W2} and all(j.get("why") == "new" for j in jobs1.values()),
      "F1 커서 = 차선 모드(_handover from fresh) · 두 지갑 뒤 차선 why=new", {"ho": ho1, "jobs": jobs1})
L1 = int(ho1.get("live") or 0)
T.chk(all(int(j["to"]) == L1 for j in jobs1.values()) and L1 == (HEAD0 - 10) - 86_400 and int(c1.get("_start") or 0) < L1,
      "F1 라이브 시작 = safe − 최근 창(48시간 = 86,400블록) · 뒤 차선 = 창 시작 → 라이브 시작", {"live": L1, "start": c1.get("_start"), "jobs": jobs1})
T.chk(all(int(c1.get(x) or 0) >= HEAD0 - 2000 for x in (W1, W2)),
      "F1 라이브 커서가 첫 주기에 최근 입금 블록을 지남(fixa1010: 걸음을 나눠 · 뒤 차선 몫을 남기며 — 최신은 엿보기)", {x[:6]: c1.get(x) for x in (W1, W2)})
T.chk(set((c1.get("_ns") or {})) == {W1, W2} and set((c1.get("_bkns") or {})) <= {W1, W2},
      "F1 라이브 기준점(_ns) 두 지갑 · 뒤 차선 기준점(_bkns)", {"ns": sorted(c1.get("_ns") or {}), "bkns": sorted(c1.get("_bkns") or {})})
T.chk(not c1.get("_synced_at"), "F2 뒤 차선 new 가 남은 동안 동기화 도장 없음(종전 단일 차선과 같음 — core 가 기초 잔고를 아직 대사하지 않게)", c1.get("_synced_at"))
CH.head = HEAD0 + 30
H["live_usdc"] = CH.add(HEAD0 + 15, X, USDC, logs=[{"address": USDC, "topics": [TRANSFER, pad(X), pad(W2)], "data": hex(1_000_000)}], gas=50_000, inp="0xa9059cbb")
n9 = 0
while n9 < 80:
    n9 += 1
    r9 = cyc(w)
    if isinstance(r9, dict):
        break
    if H["live_usdc"] not in wr.hashes():
        T.chk(False, "F2 다음 주기 라이브 새 입금 방출", n9)
        break
    if not w._bk_jobs():
        break
c2 = cur()
T.chk(H["live_usdc"] in wr.hashes(), "F2 둘째 주기 = 라이브 새 입금 바로 방출(뒤 차선이 남아도)", sorted(h[-6:] for h in wr.hashes()))
T.chk(all(int(c2.get(x) or 0) == CH.head - 10 for x in (W1, W2)), "F2 라이브 커서 = safe(몇 주기 안)", {x[:6]: c2.get(x) for x in (W1, W2)})
T.chk(not w._bk_jobs() and H["old_nat"] in wr.hashes() and H["old_usdc"] in wr.hashes() and H["mid_usdc"] in wr.hashes(),
      "F2 주기를 돌면 뒤 차선 완주 · 옛 로그 없는 입금·옛 토큰 입금까지 방출", {"cycles": n9, "left": w._bk_jobs(), "r": r9 if isinstance(r9, dict) else None,
                                                             "emitted": sorted(h[-6:] for h in wr.hashes())})
T.chk(bool(c2.get("_synced_at")), "F2 뒤 차선 완주 뒤 동기화 도장", {k: v for k, v in c2.items() if k in ("_synced_at", "_handover")})
T.chk(len(wr.recs) == len(wr.hashes()), "F2 같은 tx 두 번 방출 0", len(wr.recs) - len(wr.hashes()))

reset_state()
cfg3 = json.loads(json.dumps(CFG))
cfg3["chains"]["base"] = ccfg("nonarch")
wr3 = Wr()
w3 = new_watcher(cfg3, wr3)
r3 = cyc(w3)
c3 = cur()
ho3 = c3.get("_handover") if isinstance(c3.get("_handover"), dict) else {}
T.chk(not isinstance(r3, dict) and H["recent_usdc"] in wr3.hashes(),
      "F3 비아카이브 노드(기준점 없음) — 멈추지 않고 첫 주기에 최근 USDC 입금 방출", {"r": r3, "emitted": sorted(h[-6:] for h in wr3.hashes()), "ho": ho3})
T.chk(ho3.get("from") == "fresh" and ho3.get("nobase") == [0, 2] and HEAD0 - 3000 <= int(ho3.get("live") or 0) <= HEAD0 - 2900,
      "F3 (코덱스 ln472) 비아카이브 = 라이브 시작을 상태 보관 구간(최근 3,000블록)으로 옮겨 라이브 기준점 있음 · 그 앞은 뒤 차선(기준점 없음 = 감수)", ho3)
T.chk(H["fresh_nat"] in wr3.hashes(),
      "F3 ★(코덱스 ln472 HIGH) 상태 보관 구간 안 로그 없는 ETH 입금(17분 전) = 첫 주기 방출 — 기초 잔고로 흡수하지 않음★(수정 전 = 첫 확인 지점 safe 를 기준점으로 삼아 흡수)",
      sorted(h[-6:] for h in wr3.hashes()))
T.chk(H["sweep_usdc"] in wr3.hashes() and not c3.get("_sweep"),
      "F3 최근 창 앞부분(상태 보관 밖 · 라이브 시작 앞) 토큰 입금 = 로그만으로 첫 주기 먼저 방출(_sweep · 끝나면 지움)", {"sweep": c3.get("_sweep"),
                                                                                                       "emitted": sorted(h[-6:] for h in wr3.hashes())})
cfg3t = json.loads(json.dumps(CFG))
cfg3t["chains"]["base"] = ccfg("nonarch_tr", trace_rpcs=[URL["nonarch_tr"]])
reset_state()
wr3t = Wr()
w3t = new_watcher(cfg3t, wr3t)
for _ in range(80):
    r3t = cyc(w3t)
    if isinstance(r3t, dict) or not w3t._bk_jobs():
        break
rec3t = [r for r in wr3t.recs if r["txhash"] == H["bk_mixed"]]
T.chk(rec3t and any((it.get("to") or "").lower() == W1 and int(it.get("value") or 0) == E18 // 20 for it in (rec3t[-1]["snapshot"].get("internal") or [])),
      "F3 ★(코덱스 ln472 HIGH) 기준점 없는 뒤 차선(비아카이브)의 남의 tx 토큰+ETH 입금 = trace 해서 ETH 레그까지 방출★(수정 전 = 'own' trace 라 ETH 레그 유실)",
      {"r": r3t if isinstance(r3t, dict) else None, "recs": [(r.get("repair"), r["snapshot"].get("internal")) for r in rec3t]})

reset_state()
cfg4 = json.loads(json.dumps(CFG))
cfg4["chains"]["base"] = ccfg(rpc_lanes=False)
wr4 = Wr()
w4 = new_watcher(cfg4, wr4)
r4 = cyc(w4)
c4 = cur()
T.chk(not isinstance(r4, dict) and not c4.get("_handover") and not any(k.startswith("_bk:") for k in c4) and int(c4.get("_start") or 0) > 0,
      "F4 config rpc_lanes: false = 종전 단일 차선(창 시작부터 · 차선 모드 아님)", {k: v for k, v in c4.items() if not isinstance(v, dict)})

reset_state()
cfg5 = json.loads(json.dumps(CFG))
cfg5["chains"]["base"] = ccfg("ret")
evm_watch.RETENTION_CONFIRM_SEC = 0
wr5r = Wr()
w5r = new_watcher(cfg5, wr5r)
r5r = None
for i9 in range(40):
    r5r = cyc(w5r)
    if isinstance(r5r, dict) or not w5r._bk_jobs():
        break
c5r = cur()
g5 = [g for g in (c5r.get("_retention_gaps") or []) if g.get("lane") == "bk"]
T.chk(H["recent_usdc"] in wr5r.hashes() and not w5r._bk_jobs() and g5 and int(g5[0]["to"]) == LOG_FLOOR - 1,
      "F5 로그 보관 밖 옛 구간 — 뒤 차선이 확인(3사이클) 뒤 미수집 범위(lane bk)로 넘기고 완주(종전엔 영영 멈춤 → 도장 없음)",
      {"cycles": i9 + 1, "r": r5r if isinstance(r5r, dict) else None, "left": w5r._bk_jobs(), "gaps": g5, "cand": c5r.get("_bk_retention_cand")})
T.chk(bool(c5r.get("_synced_at")) and H["mid_usdc"] in wr5r.hashes() and H["old_usdc"] not in wr5r.hashes(),
      "F5 완주 뒤 도장 · 보관 안의 옛 토큰 입금 방출 · 보관 밖 구간 입금은 미수집(기초 잔고 대조가 맞춤 — 종전 규약)",
      {"synced": c5r.get("_synced_at"), "emitted": sorted(h[-6:] for h in wr5r.hashes())})
evm_watch.RETENTION_CONFIRM_SEC = 1800

reset_state()
cfg6 = json.loads(json.dumps(CFG))
cfg6["chains"]["base"] = ccfg(trace_rpcs=[URL["t408"]])
wr6 = Wr()
w6r = new_watcher(cfg6, wr6)
r6r = cyc(w6r)
T.chk(H["newest"] in wr6.hashes() and type((w6r.cursor.get("_leaf_hold") or {}).get("since")) is int,
      "F6 첫 주기 = 잎 실패로 라이브 꼬리 잠깐 보류(일시 오류는 바로 다음 사이클에 풀리게) · 그래도 최신 블록(2분 전) 입금은 엿보기로 방출",
      {"r": r6r, "emitted": sorted(h[-6:] for h in wr6.hashes()), "hold": w6r.cursor.get("_leaf_hold")})
if isinstance(w6r.cursor.get("_leaf_hold"), dict):
    w6r.cursor["_leaf_hold"]["since"] = int(time.time()) - 10 * getattr(evm_watch.RpcChainWatcher, "LANES_LEAF_HOLD_SEC", 120)
r6r = cyc(w6r)
c6r = cur()
ll6 = c6r.get("_leaf_later") or {}
T.chk(not isinstance(r6r, dict) and H["recent_usdc"] in wr6.hashes() and all(int(c6r.get(x) or 0) == HEAD0 - 10 for x in (W1, W2)),
      "F6 ★보류 시간이 지나면 잎 trace 408 이 계속돼도 라이브 꼬리 전진 · 최근 USDC 입금 방출 · 꼬리 커서 safe★(종전 = 잎·지갑별 10회 ∧ 30분 — 잎 블록이 바뀌면 무기한 정지)",
      {"r": r6r, "emitted": sorted(h[-6:] for h in wr6.hashes()), "cur": {x[:6]: c6r.get(x) for x in (W1, W2)}, "leaf_fail": c6r.get("_leaf_fail")})
T.chk(any(v.get("blk") == HEAD0 - 30_000 for v in ll6.values() if isinstance(v, dict)),
      "F6 그 잎 블록 = '나중에 다시'(_leaf_later — 백오프로 블록 trace 재시도 · 풀리면 그 입금 tx 방출)", {"later": ll6})
r6b = cyc(w6r)
T.chk(not isinstance(r6b, dict), "F6 다음 주기도 예외 없음(잎 재시도가 꼬리를 막지 않음)", r6b)

reset_state()
cfg7 = json.loads(json.dumps(CFG))
cfg7["chains"]["base"] = ccfg(trace_rpcs=[URL["t408"]], rpc_lanes_recent_hours=1)
wr7 = Wr()
w7f = new_watcher(cfg7, wr7)
ok7, miss7 = 0, []
for i9 in range(4):
    CH.head = HEAD0 + 40 * (i9 + 1)
    h9 = CH.add(CH.head - 20, X, USDC, logs=[{"address": USDC, "topics": [TRANSFER, pad(X), pad(W1 if i9 % 2 else W2)], "data": hex(1_000_000 + i9)}],
                gas=50_000, inp="0xa9059cbb")
    r9 = cyc(w7f)
    if h9 in wr7.hashes():
        ok7 += 1
    else:
        miss7.append((i9, r9 if isinstance(r9, dict) else None))
c7f = cur()
T.chk(ok7 == 4, "F7 ★옛 구간·라이브 창 잎 trace 408 주입 중에도 4주기 연속 그 주기의 최신 입금 방출(꼬리가 잠깐 보류돼도 엿보기)★", {"ok": ok7, "miss": miss7, "leaf_fail": c7f.get("_leaf_fail")})
for h9 in [x for x in CH.order if CH.txs[x]["block"] > HEAD0]:
    CH.txs.pop(h9)
CH.order = [x for x in CH.order if x in CH.txs]
CH.head = HEAD0

reset_state()
cfgp = json.loads(json.dumps(CFG))
cfgp["chains"]["base"] = ccfg(rpc_lanes_recent_hours=24 * 25, cycle_budget_sec=1.0)
wrp = Wr()
wp = new_watcher(cfgp, wrp)
rp = cyc(wp)
cp1 = cur()
T.chk(not isinstance(rp, dict) and min(int(cp1.get(x) or 0) for x in (W1, W2)) < HEAD0 - 10 - 2000,
      "P1 (전제) 첫 주기 라이브 차선이 최근 창을 다 못 훑음(느린 노드 흉내)", {x[:6]: cp1.get(x) for x in (W1, W2)})
T.chk(H["newest"] in wrp.hashes(), "P1 ★그래도 첫 주기에 최신 블록(2분 전) 입금 방출★ — 최신 블록 엿보기(라이브 차선보다 먼저)",
      {"emitted": sorted(h[-6:] for h in wrp.hashes()), "peek_to": cp1.get("_peek_to")})
T.chk(type(cp1.get("_peek_to")) is int and cp1["_peek_to"] == HEAD0 - 10, "P1 엿보기 끝 = safe(커서 _peek_to)", cp1.get("_peek_to"))
T.chk(H["newest_nat"] in wrp.hashes(), "P1 ★(코덱스 ln472 HIGH) 1분 전 로그 없는 ETH 입금도 첫 주기 방출 — 엿보기 네이티브 정합(이분 탐색 → 잎 블록)★",
      sorted(h[-6:] for h in wrp.hashes()))
CH.head = HEAD0 + 60
hp2 = CH.add(HEAD0 + 40, X, USDC, logs=[{"address": USDC, "topics": [TRANSFER, pad(X), pad(W1)], "data": hex(123_456)}], gas=50_000, inp="0xa9059cbb")
rp2 = cyc(wp)
T.chk(not isinstance(rp2, dict) and hp2 in wrp.hashes(), "P1 둘째 주기 = 그 사이 새 최신 입금도 방출(라이브 차선은 아직 따라잡는 중)", {"r": rp2})
wp.cycle_budget = 60.0
for _ in range(30):
    rr = cyc(wp)
    cpx = cur()
    if isinstance(rr, dict) or min(int(cpx.get(x) or 0) for x in (W1, W2)) >= CH.head - 10:
        break
cp3 = cur()
T.chk(min(int(cp3.get(x) or 0) for x in (W1, W2)) >= CH.head - 10 and H["recent_usdc"] in wrp.hashes() and len(wrp.recs) == len(wrp.hashes()),
      "P1 라이브 차선이 따라오면 최근 창 입금까지 방출 · 같은 tx 두 번 0", {"cur": {x[:6]: cp3.get(x) for x in (W1, W2)}, "dup": len(wrp.recs) - len(wrp.hashes())})
cyc(wp)
T.chk("_peek_to" not in cur(), "P1 따라잡은 뒤 엿보기 끝(커서 _peek_to 지움)", cur().get("_peek_to"))
CH.head += 30
sl0, scans9 = wp._scan_logs, []


def _rec_scan(ws9, c9, t9, dl9):
    scans9.append((int(c9), int(t9)))
    return sl0(ws9, c9, t9, dl9)


wp._scan_logs = _rec_scan
cyc(wp)
del wp._scan_logs
head9 = [x for x in scans9 if x[1] == CH.head - 10]
T.chk(len(head9) == 1 and "_peek_to" not in cur(), "P1 평소(라이브가 한 주기 몫만 뒤) = 엿보기 없음 · 최신 구간은 라이브 차선 한 번만 훑음", scans9[:6])
for h9 in [x for x in CH.order if CH.txs[x]["block"] > HEAD0]:
    CH.txs.pop(h9)
CH.order = [x for x in CH.order if x in CH.txs]
CH.head = HEAD0

reset_state()
CH.fail_receipt[H["newest"]] = 2
wrr = Wr()
wpr = new_watcher(cfgp, wrr)
cyc(wpr)
cpr = cur()
T.chk(H["newest"] not in wrr.hashes() and type(cpr.get("_peek_to")) is int and cpr["_peek_to"] < CH.txs[H["newest"]]["block"],
      "P1r 엿보기에서 상세 실패한 최신 tx = 엿보기 끝을 그 블록 앞까지만(지나치지 않음)", {"peek_to": cpr.get("_peek_to"), "blk": CH.txs[H["newest"]]["block"]})
cyc(wpr)
T.chk(H["newest"] in wrr.hashes(), "P1r ★다음 주기 엿보기가 다시 받아 방출★(수정 전 = 엿보기 끝이 지나가 라이브 차선이 올 때까지 숨음)", sorted(h[-6:] for h in wrr.hashes()))
CH.fail_receipt.clear()

reset_state()
STATE_CAP["max"] = HEAD0 - 30
wrs = Wr()
wps = new_watcher(cfgp, wrs)
cyc(wps)
cps = cur()
T.chk(H["newest_nat"] not in wrs.hashes() and cps.get("_peek_to") is None,
      "P1s 엿보기 끝 블록 상태 일시 없음 = 네이티브 정합 '실패' — 엿보기 끝 안 옮김(수정 전 = '상태 없음'으로 완료 처리 → 다시 안 봄)",
      {"peek_to": cps.get("_peek_to"), "emitted": sorted(h[-6:] for h in wrs.hashes())})
STATE_CAP["max"] = None
cyc(wps)
T.chk(H["newest_nat"] in wrs.hashes(), "P1s ★노드 회복 다음 사이클 엿보기가 다시 봐서 1분 전 ETH 입금 방출★", sorted(h[-6:] for h in wrs.hashes()))

reset_state()
cfgpt = json.loads(json.dumps(cfgp))
cfgpt["chains"]["base"]["trace_rpcs"] = [URL["t408"]]
wrt = Wr()
wpt = new_watcher(cfgpt, wrt)
rpt = cyc(wpt)
cpt = cur()
lf9 = cpt.get("_leaf_fail") or {}
T.chk(not isinstance(rpt, dict) and H["peek_nat2"] in wrt.hashes() and H["newest_nat"] in wrt.hashes(),
      "P1t ★엿보기 창 안 W1 internal 입금의 잎 trace 408 이 W2 순수 ETH 입금·W1 다른 ETH 입금 방출을 막지 않음(같은 주기)★(수정 전 = 한 지갑 예외로 전체 엿보기 정합 건너뜀)",
      {"r": rpt, "emitted": sorted(h[-6:] for h in wrt.hashes())})
lv9 = int((cpt.get("_handover") or {}).get("live") or 0)
T.chk(not any(("@_peek_ns" in k9) or k9.endswith(f":{HEAD0 - 100}") for k9 in lf9)
      and not any(int((v or {}).get("blk") or 0) > lv9 for v in (cpt.get("_leaf_later") or {}).values()),
      "P1t 엿보기 잎 실패 = 보류·계수 없음(_leaf_fail·_leaf_later 안 남김 — 라이브 차선이 그 블록을 라이브 규약으로)", {"leaf_fail": lf9, "later": cpt.get("_leaf_later"), "live": lv9})
T.chk(W2 in (cpt.get("_peek_wdone") or {}) and W1 not in (cpt.get("_peek_wdone") or {}),
      "P1t 성공한 지갑만 엿보기 정합 끝 기록(_peek_wdone W2) · 실패 지갑(W1)은 다음 사이클 다시", cpt.get("_peek_wdone"))
rpt2 = cyc(wpt)
T.chk(not isinstance(rpt2, dict) and len(wrt.recs) == len(wrt.hashes()), "P1t 다음 주기도 예외 없음 · 같은 tx 두 번 0", {"r": rpt2, "dup": len(wrt.recs) - len(wrt.hashes())})

reset_state()
H["relay"] = CH.add(HEAD0 - 120, W1, RT, value=E18 // 3, internal=[(RT, W2, E18 // 3)], gas=60_000, inp="0x")
cfgpu = json.loads(json.dumps(cfgp))
cfgpu["chains"]["base"]["trace_rpcs"] = [URL["trok"]]
wru = Wr()
wpu = new_watcher(cfgpu, wru)
rpu = cyc(wpu)
cpu = cur()
ru = [r for r in wru.recs if r["txhash"] == H["relay"]]
T.chk(not isinstance(rpu, dict) and ru and any((it.get("to") or "").lower() == W2 and int(it.get("value") or 0) == E18 // 3
                                               for it in (ru[-1]["snapshot"].get("internal") or [])),
      "P1u ★W1 의 중계 송금(로그 없음)이 W2 에 준 internal ETH = 같은 주기 엿보기 방출에 실림(W2 잎 trace 가 같은 스냅숏을 보강)★(수정 전 = W1 스냅숏(internal 없음)만 남아 W2 입금 유실)",
      {"r": rpu, "recs": [(r.get("repair"), r["snapshot"].get("internal")) for r in ru]})
T.chk(W1 in (cpu.get("_peek_wdone") or {}) and W2 in (cpu.get("_peek_wdone") or {}) and len(wru.recs) >= len(wru.hashes()),
      "P1u 두 지갑 엿보기 정합 끝 기록 · 예외 없음", cpu.get("_peek_wdone"))
CH.txs.pop(H["relay"])
CH.order = [x for x in CH.order if x in CH.txs]

reset_state()
bis0 = evm_watch.RpcChainWatcher._bisect


adv0 = evm_watch.RpcChainWatcher._advance


def costly_bisect(self, w, a, b, sa, sb, pool, deadline):
    if not getattr(self, "_t_bk", False) and int(b) - int(a) > 20_000:
        raise RuntimeError("이분 탐색 예산 소진")
    return bis0(self, w, a, b, sa, sb, pool, deadline)


def adv_flag(self, ws, c, target, head, deadline, bk=False):
    self._t_bk = bk
    try:
        return adv0(self, ws, c, target, head, deadline, bk=bk)
    finally:
        self._t_bk = False


evm_watch.RpcChainWatcher._bisect = costly_bisect
evm_watch.RpcChainWatcher._advance = adv_flag
try:
    wr4 = Wr()
    w4 = new_watcher(CFG, wr4)
    reached, errs4, bk_moves, trail4 = None, 0, 0, []
    for i9 in range(10):
        bk0 = min((int(j["done"]) for j in w4._bk_jobs().values()), default=None)
        r9 = cyc(w4)
        errs4 += isinstance(r9, dict)
        c9 = cur()
        bk1 = min((int(j["done"]) for k9, j in c9.items() if k9.startswith("_bk:") and isinstance(j, dict)), default=None)
        bk_moves += bool(bk0 is not None and bk1 is not None and bk1 > bk0)
        trail4.append((min(int(c9.get(W1) or 0), int(c9.get(W2) or 0)), c9.get("_lvspan"), r9.get("_exc", "")[:40] if isinstance(r9, dict) else None))
        if min(int(c9.get(W1) or 0), int(c9.get(W2) or 0)) >= HEAD0 - 10:
            reached = i9 + 1
            break
    T.chk(reached is not None and reached <= 6 and errs4 == 0,
          "P4 ★넓은 걸음 이분 탐색이 예산을 넘는 노드에서도 라이브 차선이 몇 사이클 안에 헤드 도달 · 사이클 예외 0★(수정 전 = 48h 한 걸음 '예산 소진' 반복 · 커서 정지)",
          {"reached": reached, "errs": errs4, "trail": trail4})
    T.chk(any(t9[1] is not None for t9 in trail4) or reached is not None, "P4 걸음 실패면 걸음 줄여 디스크(_lvspan) · 빨리 끝나면 늘림", trail4)
    T.chk(bk_moves >= 1, "P4 라이브 따라잡는 동안에도 뒤 차선이 전진한 사이클 있음(라이브 걸음 실패가 뒤 차선을 막지 않음)", {"bk_moves": bk_moves})
    T.chk(H["recent_usdc"] in wr4.hashes() and H["recent_nat"] in wr4.hashes() and H["fresh_nat"] in wr4.hashes(),
          "P4 최근 창 입금(토큰·로그 없는 ETH) 방출", sorted(h[-6:] for h in wr4.hashes()))
finally:
    evm_watch.RpcChainWatcher._bisect = bis0
    evm_watch.RpcChainWatcher._advance = adv0

reset_state()
common.atomic_write_json(CP, {W1: START_EXPECT + 1000, W2: START_EXPECT + 1000, "_cov:" + W1: START_EXPECT, "_cov:" + W2: START_EXPECT, "_synced_at": 1})
cfg2p = json.loads(json.dumps(CFG))
cfg2p["chains"]["base"] = ccfg(cycle_budget_sec=1.0)
wr2p = Wr()
w2p = new_watcher(cfg2p, wr2p)
r2p = cyc(w2p)
c2p = cur()
T.chk(not isinstance(r2p, dict) and (c2p.get("_handover") or {}).get("from") == "explorer" and H["newest"] in wr2p.hashes(),
      "P2 ★탐색기 → RPC 인계(탐색기 커서 한 달 전) 첫 주기에 최신 블록 입금 방출★", {"r": r2p, "ho": (c2p.get("_handover") or {}).get("from"),
                                                                     "emitted": sorted(h[-6:] for h in wr2p.hashes())})

W3 = "0x" + "f6" * 20
H["w3_recent"] = CH.add(HEAD0 - 1_800, X, USDC, logs=[{"address": USDC, "topics": [TRANSFER, pad(X), pad(W3)], "data": hex(2_200_000_000)}],
                        gas=50_000, inp="0xa9059cbb")
for node9, nm9 in (("arch", "아카이브"), ("nonarch", "비아카이브")):
    reset_state()
    cfg3p = json.loads(json.dumps(CFG))
    cfg3p["chains"]["base"] = ccfg(node9)
    n1, b1 = CH.state(W1, HEAD0 - 10)
    n2, b2 = CH.state(W2, HEAD0 - 10)
    common.atomic_write_json(CP, {"_rpc_v": 1, "_start": START_EXPECT, W1: HEAD0 - 10, W2: HEAD0 - 10, "_ns": {W1: [HEAD0 - 10, n1, str(b1), 0, "0"],
                                                                                                         W2: [HEAD0 - 10, n2, str(b2), 0, "0"]},
                                  "_handover": {"from": "fresh", "at": 1, "live": HEAD0 - 10, "start": START_EXPECT}, "_xcurs": {}})
    CH.head = HEAD0 + 20
    hj = CH.add(HEAD0 + 5, X, USDC, logs=[{"address": USDC, "topics": [TRANSFER, pad(X), pad(W3)], "data": hex(77)}], gas=50_000, inp="0xa9059cbb")
    wr3p = Wr()
    w3p = evm_watch.RpcChainWatcher(cfg3p, "base", [W1, W2, W3], wr3p)
    r3p = cyc(w3p)
    c3p = cur()
    T.chk(not isinstance(r3p, dict) and H["w3_recent"] in wr3p.hashes() and hj in wr3p.hashes()
          and (c3p.get("_bk:" + W3) or {}).get("why") == "new" and all(int(c3p.get(x) or 0) == HEAD0 + 10 for x in (W1, W2, W3)),
          f"P3 ★새 지갑 합류({nm9} 노드) — 첫 주기에 합류 1시간 전·최신 입금 방출 · 체인 멈춤 없음 · 옛 구간 = 뒤 차선★",
          {"r": r3p, "emitted": sorted(h[-6:] for h in wr3p.hashes()), "cur": {x[:6]: c3p.get(x) for x in (W1, W2, W3)}, "bk": c3p.get("_bk:" + W3)})
    CH.txs.pop(hj)
    CH.order = [x for x in CH.order if x in CH.txs]
CH.head = HEAD0
CH.txs.pop(H["w3_recent"])
CH.order = [x for x in CH.order if x in CH.txs]

reset_state()
LC = {"backfill_months": 1, "chains": {"optimism": {"blockscout": "https://optimism.blockscout.invalid", "conf_depth": 30, "blocks_per_day": 43200,
                                                    "rpcs": [URL["arch"]], "rpc_logs": [URL["arch"]], "trace_rpcs": [], "chain_id": 8453,
                                                    "rpc_node_table": False}},
      "wallets": []}
wrl = Wr()


def mk_l(cfg9, chain9, addrs9):
    return evm_watch.build_watcher(cfg9, chain9, addrs9, wrl, "")


wl = mk_l(LC, "optimism", [W1])
lp = evm_watch.ChainLoop(LC, wl, mk_l, "", wrl)
T.chk(isinstance(lp.wt, evm_watch.RpcChainWatcher), "L0 새 설치본 optimism = RPC 우선 본선", type(lp.wt).__name__)


def rpc_boom(*a, **k):
    raise RuntimeError("시험: RPC 노드 전부 실패")


probe = {"bs": (True, None), "rpc": (False, "down")}
bs0, rp0, cwc0, rwc0 = evm_watch._bs_probe, evm_watch._rpc_probe, evm_watch.ChainWatcher.cycle, evm_watch.RpcChainWatcher.cycle
evm_watch._bs_probe = lambda cfg9, chain9, w9=None: probe["bs"]
evm_watch._rpc_probe = lambda cfg9, chain9, w9=None: probe["rpc"]
evm_watch.ChainWatcher.cycle = lambda self: None
lr0 = evm_watch.RPC_LR_SEC
try:
    lp.wt.cycle = rpc_boom
    for _ in range(4):
        lp.step()
    T.chk(isinstance(lp.wt, evm_watch.RpcChainWatcher), "L1 RPC 연속 실패가 30분 안 = RPC 그대로 재시도(블록스카웃으로 안 감)", type(lp.wt).__name__)
    evm_watch.RPC_LR_SEC = 0
    probe["bs"] = (False, "HTTP Error 403")
    evm_watch._RPCFB_MEM["optimism"]["lr_probe_next"] = 0
    lp.wt.cycle = rpc_boom
    lp.step()
    T.chk(isinstance(lp.wt, evm_watch.RpcChainWatcher), "L2 RPC 오래 실패 + 블록스카웃 403 = RPC 그대로 재시도", type(lp.wt).__name__)
    probe["bs"] = (True, None)
    evm_watch._RPCFB_MEM["optimism"]["lr_probe_next"] = 0
    lp.wt.cycle = rpc_boom
    lp.step()
    T.chk(isinstance(lp.wt, evm_watch.ChainWatcher) and getattr(lp.wt, "lr_info", None),
          "L3 ★RPC 오래 연속 실패 + 블록스카웃 살아 있음 = 블록스카웃을 최후 경로로★(수정 전 = 영구 차단)", type(lp.wt).__name__)
    lp.step()
    T.chk(isinstance(lp.wt, evm_watch.ChainWatcher), "L4 최후 경로 중 RPC 아직 안 됨 = 블록스카웃 유지", type(lp.wt).__name__)
    probe["rpc"] = (True, None)
    lp.wt.lr_info["since"] = 1
    evm_watch._RPCFB_MEM["optimism"]["lr_back_next"] = 0
    evm_watch.RpcChainWatcher.cycle = lambda self: None
    lp.step()
    T.chk(isinstance(lp.wt, evm_watch.RpcChainWatcher) and not getattr(lp.wt, "fb_info", None),
          "L5 RPC 회복 = RPC 우선 본선 복귀(대체 기록 없음)", type(lp.wt).__name__)
    evm_watch.RpcChainWatcher.cycle = rwc0
    reset_state()
    evm_watch._RPCFB_MEM.clear()
    LC6 = json.loads(json.dumps(LC))
    LC6["chains"]["optimism"].update(rpcs=[URL["nolog"]], rpc_logs=[URL["nolog"]], cycle_budget_sec=1.5, rpc_backfill_budget_sec=0.2)
    wl6 = mk_l(LC6, "optimism", [W1])
    lp6 = evm_watch.ChainLoop(LC6, wl6, mk_l, "", wrl)
    probe["rpc"] = (False, "down")
    for _ in range(4):
        evm_watch._RPCFB_MEM.setdefault("optimism", {})["lr_probe_next"] = 0
        lp6.step()
        if isinstance(lp6.wt, evm_watch.ChainWatcher):
            break
    T.chk(isinstance(lp6.wt, evm_watch.ChainWatcher) and getattr(lp6.wt, "lr_info", None),
          "L6 ★헤드는 되고 getLogs 만 계속 실패(사이클은 예외 없이 무전진) = 실패로 세어 최후 경로로★(수정 전 = 성공으로 보고 실패 계수 초기화 → 영영 못 감)",
          {"wt": type(lp6.wt).__name__, "mem": evm_watch._RPCFB_MEM.get("optimism")})
    reset_state()
    evm_watch._RPCFB_MEM.clear()
    LC7 = json.loads(json.dumps(LC))
    LC7["chains"]["optimism"]["etherscan_chainid"] = 10
    ew = evm_watch.build_watcher(LC7, "optimism", [W1], wrl, "SYNTHKEY")
    T.chk(isinstance(ew, evm_watch.EtherscanWatcher), "L7 (전제) 이더스캔 키 + 지원 체인 = 이더스캔", type(ew).__name__)
    fb7 = evm_watch.es_fallback_watcher(LC7, ew, wrl, daily=False, why="key")
    T.chk(isinstance(fb7, evm_watch.RpcChainWatcher) and getattr(fb7, "fb_info", None), "L7 (전제) 이더스캔 키 거부 = RPC 대체(fb_info)", type(fb7).__name__)

    def mk7(cfg9, chain9, addrs9):
        return evm_watch.build_watcher(cfg9, chain9, addrs9, wrl, "SYNTHKEY")
    lp7 = evm_watch.ChainLoop(LC7, fb7, mk7, "SYNTHKEY", wrl)
    probe["rpc"] = (False, "down")
    for _ in range(4):
        evm_watch._RPCFB_MEM.setdefault("optimism", {})["lr_probe_next"] = 0
        lp7.wt.cycle = rpc_boom
        lp7.step()
        if isinstance(lp7.wt, evm_watch.ChainWatcher):
            break
    T.chk(isinstance(lp7.wt, evm_watch.ChainWatcher) and (lp7.wt.lr_info or {}).get("fb_info", {}).get("src") == "etherscan",
          "L7 ★이더스캔 대체 RPC 가 오래 실패 + 블록스카웃 살아 있음 = 최후 경로(대체 표시 보관)★(수정 전 = fb_info 라 제외 → 영구 차단)",
          {"wt": type(lp7.wt).__name__, "lr": getattr(lp7.wt, "lr_info", None)})
    probe["rpc"] = (True, None)
    if getattr(lp7.wt, "lr_info", None):
        lp7.wt.lr_info["since"] = 1
    evm_watch._RPCFB_MEM["optimism"]["lr_back_next"] = 0
    evm_watch.RpcChainWatcher.cycle = lambda self: None
    lp7.step()
    T.chk(isinstance(lp7.wt, evm_watch.RpcChainWatcher) and (getattr(lp7.wt, "fb_info", None) or {}).get("src") == "etherscan",
          "L7 RPC 회복 = RPC 로 돌아오며 이더스캔 대체 표시 되살림(이더스캔 복귀 시험 이어짐)", {"wt": type(lp7.wt).__name__, "fb": getattr(lp7.wt, "fb_info", None)})
finally:
    evm_watch._bs_probe, evm_watch._rpc_probe, evm_watch.ChainWatcher.cycle, evm_watch.RpcChainWatcher.cycle = bs0, rp0, cwc0, rwc0
    evm_watch.RPC_LR_SEC = lr0

reset_state()
wr5 = Wr()
S0 = START_EXPECT + 2
CS = S0 + 50_000
n_cs, b_cs = CH.state(W1, CS)
stuck = {"_rpc_v": 1, "_start": S0, W1: CS, W2: CS, "_ns": {W1: [CS, n_cs, str(b_cs), 0, "0"]}, "_xcurs": {},
         "_scan": {"frm": CS + 1, "to": CS + 2000, "ws": sorted([W1, W2]), "found": {}}}
common.atomic_write_json(CP, stuck)
w5 = new_watcher(CFG, wr5)
r5 = cyc(w5)
c5 = cur()
ho5 = c5.get("_handover") if isinstance(c5.get("_handover"), dict) else {}
j5 = {k[4:]: v for k, v in c5.items() if k.startswith("_bk:")}
T.chk(not isinstance(r5, dict) and H["recent_usdc"] in wr5.hashes(),
      "S1 ★단일 차선으로 멈춘 설치본 — 첫 주기에 최근 USDC 입금 방출★(종전 = 멈춘 커서부터 순서대로)", {"r": r5, "emitted": sorted(h[-6:] for h in wr5.hashes()),
                                                                                 "cursor": {k: v for k, v in c5.items() if not k.startswith("_")}})
T.chk(ho5.get("from") == "stall" and set(j5) == {W1, W2} and all(int(j["from"]) == CS and j["why"] == "new" for j in j5.values())
      and all(int(j["to"]) == int(ho5.get("live") or -1) for j in j5.values()),
      "S1 전환 = _handover from stall · 뒤 차선 (멈춘 커서, 라이브 시작] why=new", {"ho": ho5, "jobs": j5})
T.chk((c5.get("_bkns") or {}).get(W1) == stuck["_ns"][W1] or any(int(j["done"]) > CS for j in j5.values()),
      "S1 종전 기준점(_ns) = 뒤 차선 기준점(_bkns)으로 옮김(옛 구간 정합 이어감)", {"bkns": c5.get("_bkns"), "jobs": j5})
pre9 = glob.glob(CP + ".pre_lanes_*")
T.chk(len(pre9) == 1 and common.read_json(pre9[0], {}).get(W1) == CS, "S1 전환 전 커서 보존본 .pre_lanes_* (원본 그대로)", [os.path.basename(x) for x in pre9])
w6 = new_watcher(CFG, wr5)
r6 = cyc(w6)
c6 = cur()
T.chk(not isinstance(r6, dict) and (c6.get("_handover") or {}).get("at") == ho5.get("at") and len(glob.glob(CP + ".pre_lanes_*")) == 1,
      "S3 전환 뒤 재시작 = 그대로 이어감(재전환 0 · 보존본 1개)", {"r": r6, "ho": c6.get("_handover")})

reset_state()
near = {"_rpc_v": 1, "_start": START_EXPECT, W1: HEAD0 - 10 - 5_000, W2: HEAD0 - 10 - 5_000, "_xcurs": {}}
common.atomic_write_json(CP, near)
w7 = new_watcher(CFG, Wr())
r7 = cyc(w7)
c7 = cur()
T.chk(not isinstance(r7, dict) and not c7.get("_handover") and not glob.glob(CP + ".pre_lanes_*") and int(c7.get(W1) or 0) == HEAD0 - 10,
      "S2 최근 창 안에서 조금 뒤처진 단일 차선 = 전환 안 함(라이브 그대로 따라잡음)", {k: v for k, v in c7.items() if not isinstance(v, dict)})
reset_state()
ext = {"_rpc_v": 1, "_start": S0, W1: S0 + 10, W2: S0 + 10, "_xcurs": {},
       "_since_ext": {"from": S0, "to": S0 + 100_000, "at": 1, "live": {W1: HEAD0 - 10, W2: HEAD0 - 10}, "ns": {}}}
common.atomic_write_json(CP, ext)
w8 = new_watcher(CFG, Wr())
T.safe(getattr(w8, "_lanes_unstall", lambda s: None), HEAD0 - 10)
T.chk(not cur().get("_handover"), "S2 과거 창 확장 중(_since_ext — 일부러 뒤로 감) = 전환 안 함", cur().get("_handover"))

reset_state()
RC = {"backfill_months": 1, "chains": {
    "optimism": {"blockscout": "https://optimism.blockscout.invalid", "conf_depth": 30, "blocks_per_day": 43200},
    "eth": {"blockscout": "https://eth.blockscout.invalid", "conf_depth": 12, "blocks_per_day": 7200, "etherscan_chainid": 1},
    "zksync": {"blockscout": "https://zksync.blockscout.invalid", "conf_depth": 30, "blocks_per_day": 80000},
    "somnia": {"blockscout": "https://somnia.blockscout.invalid", "chain_id": 5031, "rpcs": ["https://somnia.rpc.invalid"], "conf_depth": 100,
               "blocks_per_day": 864000},
    "gnosis": {"blockscout": "https://gnosis.blockscout.invalid", "conf_depth": 20, "blocks_per_day": 17000, "discovery": "explorer"}},
    "wallets": []}
op = evm_watch.build_watcher(RC, "optimism", [W1], Wr(), "")
T.chk(isinstance(op, evm_watch.RpcChainWatcher) and not getattr(op, "fb_info", None),
      "R1 ★새 설치본 optimism(블록스카웃 칸 · 이더스캔 키 없음) = RPC 우선(블록스카웃 워처 아님)★", type(op).__name__)
rt = common.read_json(os.path.join(SD, "evm_route.json"), {})
T.chk((rt.get("optimism") or {}).get("route") == "rpc_first", "R1 state/evm_route.json 에 rpc_first 고정", rt)
e1 = evm_watch.build_watcher(RC, "eth", [W1], Wr(), "SYNTHKEY")
T.chk(isinstance(e1, evm_watch.EtherscanWatcher), "R2 이더스캔 키 + 이더스캔 지원 체인 = 이더스캔 먼저(종전과 같음)", type(e1).__name__)
nw = evm_watch.es_fallback_watcher(RC, e1, Wr(), daily=False, why="key")
T.chk(isinstance(nw, evm_watch.RpcChainWatcher) and (evm_watch.rpcfb_get("eth") or {}).get("src") == "etherscan",
      "R2 이더스캔이 막히면(키 거부) 블록스카웃이 아니라 RPC 대체(복귀 = 이더스캔 시험)", {"type": type(nw).__name__, "rec": evm_watch.rpcfb_get("eth")})
e0 = evm_watch.build_watcher(RC, "eth", [W1], Wr(), "")
T.chk(isinstance(e0, (evm_watch.RpcChainWatcher,)) and not isinstance(e0, evm_watch.ChainWatcher),
      "R2 이더스캔 키 없는 eth = 블록스카웃이 아니라 RPC", type(e0).__name__)
common.atomic_write_json(os.path.join(SD, "cursor_evm_zksync.json"), {W1: 72_000_000, "_cov:" + W1: 70_000_000, "_synced_at": 1})
zk = evm_watch.build_watcher(RC, "zksync", [W1], Wr(), "")
T.chk(isinstance(zk, evm_watch.ChainWatcher) and (common.read_json(os.path.join(SD, "evm_route.json"), {}).get("zksync") or {}).get("route") == "legacy",
      "R3 탐색기 시절 커서가 있는 기존 설치본(zksync 블록스카웃 정상) = 종전 순서 유지 · legacy 고정", type(zk).__name__)
sm = evm_watch.build_watcher(RC, "somnia", [W1], Wr(), "")
T.chk(isinstance(sm, evm_watch.ChainWatcher), "R3 RPC 노드 표에 없는 체인(공개 RPC 수집 미검증) = 종전(블록스카웃)", type(sm).__name__)
gn = evm_watch.build_watcher(RC, "gnosis", [W1], Wr(), "")
T.chk(isinstance(gn, evm_watch.ChainWatcher), "R3 discovery: explorer 명시 = 종전(블록스카웃)", type(gn).__name__)
common.atomic_write_json(os.path.join(SD, "cursor_evm_zksync.json"), {})
zk2 = evm_watch.build_watcher(RC, "zksync", [W1], Wr(), "")
T.chk(isinstance(zk2, evm_watch.ChainWatcher), "R3 한 번 정한 순서는 고정(커서를 지워도 legacy 유지)", type(zk2).__name__)

T.finish()
