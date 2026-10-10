#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import shutil
import sqlite3
import threading
import time
import types

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
    r = T.safe(w.cycle)
    return r


win_blk = int((NOW0 - 150 * 86400 - BASE_T) / BSEC)
h_old = CH.transfer(win_blk + 1000, TK, OTHER, W1, 5 * 10 ** 18)
h_mid = CH.transfer(H0 - 5_000_000, TK, W2, OTHER, 10 ** 18, sender=ROUTER)
h_usd = CH.transfer(H0 - 100, USD, OTHER, W2, 8_800 * 10 ** 18)
h_bnb = CH.native(H0 - 300, HOT, W1, 15 * 10 ** 17)

reset_state()
exch_withdraw(h_bnb, W1)
CH.mode, CH.old_below = "pruned", H0 - 3_000_000
wr1 = Wr()
w = mk(wr=wr1)
t0 = time.time()
r = cycle(w)
dt = time.time() - t0
c1 = cur()
e1 = emitted(wr1)
T.chk(not isinstance(r, dict), "N1 첫 주기 예외 없음", r)
T.chk(h_usd in e1, "N1 첫 주기에 최근 BEP20 입금 방출(옛 구간 실패 중)", {"emitted": len(e1), "from_block": c1.get("from_block"), "keys": sorted(c1)})
T.chk(h_bnb in e1, "N1 첫 주기에 최근 BNB 입금(거래소 출금 txid) 방출", {"emitted": len(e1)})
T.chk(h_old not in e1 and h_mid not in e1, "N1 옛 구간(노드 실패) 기록은 아직 없음")
lv = c1.get("_live") if isinstance(c1.get("_live"), dict) else {}
T.chk(int(lv.get("done") or 0) >= H0 - 20, "N1 라이브 차선 = 확정 헤드까지", lv)
T.chk(isinstance(c1.get("from_block"), int) and abs(int(c1["from_block"]) - win_blk) < 5000, "N1 옛 차선 커서 = 창 시작(150일 — 개월 설정 5 × 30)",
      {"from_block": c1.get("from_block"), "win": win_blk})
T.chk("_synced_at" not in c1 and not scope_ready(), "N1 옛 차선 끝나기 전 = 도장 없음 · core 대사 준비 거짓")
hb = (common.read_json(os.path.join(common.STATE_DIR, "health", "bsc.json"), {}).get("sources") or {}).get("bsc") or {}
T.chk(hb.get("ok") is True and int(hb.get("lag_blocks") or 0) < 100, "N1 하트비트 = 최신 성공(옛 차선 실패는 사실로만)",
      {k: hb.get(k) for k in ("ok", "lag_blocks", "lanes")})
T.chk(isinstance(hb.get("lanes"), dict) and hb["lanes"].get("stalled"), "N1 하트비트에 옛 차선 멈춤 사실", hb.get("lanes"))
st1 = (bf_engine.read_status().get("bsc") or {}).get("bsc") or {}
T.chk(st1.get("phase") == "scan" and int(st1.get("total") or 0) > int(st1.get("done") or 0) > 0, "N1 진행률 = 옛 기록 받는 중(분모 = 창 전체)",
      {k: st1.get(k) for k in ("phase", "done", "total", "lag")})

fb_before = int(cur().get("from_block") or 0)
for k, mode in enumerate(("pruned", "429", "results")):
    CH.mode = mode
    CH.head += 400
    hn = CH.transfer(CH.head - 30, USD, OTHER, W1, (k + 1) * 10 ** 18)
    w2 = mk(wr=wr1) if k == 1 else w
    if k == 1:
        w = w2
    r = cycle(w)
    T.chk(hn in emitted(wr1), f"N2 옛 구간 '{mode}' 중 새 입금(블록 {CH.head - 30}) 그 주기에 방출", {"r": r, "n": len(wr1.recs)})
    T.chk(int(cur().get("from_block") or 0) == fb_before, f"N2 '{mode}' — 옛 차선 커서 그대로(못 받은 구간을 건너뛰지 않음)")
T.chk(len(emitted(wr1)) == len(set(emitted(wr1))), "N2 같은 tx 두 번 방출 0")

CH.mode = None
for _ in range(80):
    cycle(w)
    if not isinstance(cur().get("_live"), dict):
        break
c3 = cur()
e3 = emitted(wr1)
T.chk(not isinstance(c3.get("_live"), dict) and "_lscan" not in c3, "N3 옆 차선 끝 → 한 차선으로 합쳐짐", {k: c3.get(k) for k in ("from_block", "_live")})
T.chk(h_old in e3 and h_mid in e3, "N3 옛 기록(창 시작 직후 · 중간) 방출")
T.chk(len(e3) == len(set(e3)), "N3 같은 tx 두 번 방출 0", len(e3) - len(set(e3)))
CH.head += 50
cycle(w)
T.chk(scope_ready(), "N3 합친 뒤 한 주기 = 도장 · core 대사 준비", {k: cur().get(k) for k in ("from_block", "head", "_synced_at")})

reset_state()
mid_fb = H0 - 20_000_000
common.atomic_write_json(CPATH, {"from_block": mid_fb, "_bf_start": win_blk, "_cov": win_blk, "head": H0 - 1_000_000,
                                 "_wallets": sorted([W1, W2])})
CH.mode, CH.old_below = "slow", H0 - 100_000
CH.head = H0 + 2000
hn4 = CH.transfer(CH.head - 50, USD, OTHER, W2, 7 * 10 ** 18)
wr4 = Wr()
w = mk(wr=wr4)
cycle(w)
c4 = cur()
T.chk(hn4 in emitted(wr4), "N4 진행 중 설치 — 첫 주기에 최신 입금 방출(자동 전환)", {"keys": sorted(c4), "n": len(wr4.recs)})
T.chk(isinstance(c4.get("_live"), dict) and c4["_live"].get("why") == "lag" and int(c4.get("from_block") or 0) >= mid_fb,
      "N4 차선 = 'lag' · 옛 차선은 종전 커서부터", c4.get("_live"))
T.chk("_synced_at" not in c4 and not scope_ready(), "N4 전환 중 도장 없음")

reset_state()
CH.head = H0 + 5000
common.atomic_write_json(CPATH, {"from_block": CH.head - 20 - 60, "head": CH.head - 60, "_cov": win_blk, "_wallets": sorted([W1, W2])})
hn5 = CH.transfer(CH.head - 30, USD, OTHER, W1, 10 ** 18)
wr5 = Wr()
w = mk(wr=wr5)
cycle(w)
c5 = cur()
T.chk(not isinstance(c5.get("_live"), dict) and "_lscan" not in c5, "N5 따라잡은 설치 = 차선 안 만듦", sorted(c5))
T.chk(hn5 in emitted(wr5) and int(c5.get("from_block") or 0) == CH.head - 20 and c5.get("_synced_at"), "N5 종전대로 확정 헤드까지 · 도장",
      {k: c5.get(k) for k in ("from_block", "head", "_synced_at")})

reset_state()
CH.mode, CH.old_below = "pruned", H0 - 3_000_000
CH.head = H0 + 6000
wr6 = Wr()
w = mk(wr=wr6)
cycle(w)
L6 = int((cur().get("_live") or {}).get("done") or 0)
CH.head += 40_000
hn6 = CH.transfer(CH.head - 25, USD, OTHER, W2, 3 * 10 ** 18)
hgap = CH.transfer(L6 + 10_000, USD, OTHER, W1, 4 * 10 ** 18)
w = mk(wr=wr6)
cycle(w)
c6 = cur()
T.chk(hn6 in emitted(wr6), "N6 재시작 첫 주기에 최신 입금(꺼진 동안 쌓인 구간보다 먼저)", {"live": c6.get("_live")})
holes6 = (c6.get("_live") or {}).get("holes") or []
T.chk(len(holes6) == 2 and holes6[-1][0] == L6, "N6 꺼진 구간 = 옆 차선의 둘째 빈 구간", holes6)
CH.mode = None
for _ in range(80):
    cycle(w)
    if not isinstance(cur().get("_live"), dict):
        break
T.chk(hgap in emitted(wr6) and not isinstance(cur().get("_live"), dict), "N6 옆 차선이 꺼진 구간까지 채우고 합쳐짐")
T.chk(len(emitted(wr6)) == len(set(emitted(wr6))), "N6 같은 tx 두 번 방출 0")

reset_state()
CH.mode, CH.old_below = "pruned", H0 - 3_000_000
CH.head = H0 + 50_000
wr7 = Wr()
w = mk(wr=wr7)
cycle(w)
c7 = cur()
L7 = int((c7.get("_live") or {}).get("done") or 0)
c7["from_block"] = L7 + 5
c7.pop("_scan", None)
common.atomic_write_json(CPATH, c7)
w = mk(wr=wr7)
CH.head += 100
cycle(w)
c7b = cur()
T.chk(not isinstance(c7b.get("_live"), dict) and int(c7b.get("from_block") or 0) >= L7 + 5, "N7 옛 코드가 지나친 커서 → 차선 합쳐짐(빈 구간 없음)",
      {k: c7b.get(k) for k in ("from_block", "_live")})
reset_state()
CH.mode, CH.old_below = None, None
w = mk(wr=Wr())
CH.mode, CH.old_below = "pruned", H0 - 3_000_000
cycle(w)
c7c = cur()
fb7 = int(c7c["from_block"])
c7c["from_block"] = fb7 - 7000
common.atomic_write_json(CPATH, c7c)
w = mk(wr=Wr())
cycle(w)
c7d = cur()
lv7 = c7d.get("_live") if isinstance(c7d.get("_live"), dict) else {}
T.chk(int(c7d.get("from_block") or 0) == fb7 - 7000 and (not lv7 or (lv7.get("holes") or [[0]])[0][0] == fb7 - 7000),
      "N7 되감긴 커서 = 차선 기록을 믿지 않고 되감은 곳부터(건너뛰기 0)", {"fb": c7d.get("from_block"), "live": lv7})

reset_state()
CH.mode, CH.old_below = "pruned", H0 - 3_000_000
w = mk(cfg(lanes=False), wr=Wr())
cycle(w)
c8 = cur()
T.chk(not isinstance(c8.get("_live"), dict), "N8 lanes=false = 차선 없음(종전 한 차선)", sorted(c8))

reset_state()
CH.mode, CH.old_below = "pruned", H0 - 3_000_000
CH.head = H0 + 70_000
w = mk(wr=Wr())
cycle(w)
CH.head += 200
hb10 = CH.transfer(CH.head - 50, USD, OTHER, W1, 6 * 10 ** 18)
CH.bad_rc.add(hb10)
wr10 = Wr()
w = mk(wr=wr10)
cycle(w)
c10 = cur()
ls10 = c10.get("_lscan") if isinstance(c10.get("_lscan"), dict) else {}
hb = (common.read_json(os.path.join(common.STATE_DIR, "health", "bsc.json"), {}).get("sources") or {}).get("bsc") or {}
T.chk(hb10 in (ls10.get("found") or []) and hb10 not in emitted(wr10) and hb.get("ok") is False,
      "N10 상세 실패 = 라이브 체크포인트에 남김 · 방출 안 함 · 하트비트 실패", {"lscan": ls10, "ok": hb.get("ok")})
CH.bad_rc.clear()
g0 = len(CH.glog)
cycle(w)
again = [g for g in CH.glog[g0:] if g[0] <= int(ls10.get("to") or 0) and g[1] >= int(ls10.get("frm") or 0)]
T.chk(hb10 in emitted(wr10) and not again, "N10 다음 주기 = 그 구간 getLogs 0콜 · 상세만 다시 → 방출", {"again": again[:3]})

reset_state()
CH.mode, CH.old_below = "pruned", H0 - 3_000_000
CH.head = H0 + 80_000
hb11 = CH.transfer(CH.head - 50, USD, OTHER, W1, 5 * 10 ** 18)
hn11 = CH.native(CH.head - 120, HOT, W2, 2 * 10 ** 17)
exch_withdraw(hn11, W2)
CH.bad_rc.add(hb11)
wr11 = Wr()
w = mk(wr=wr11)
cycle(w)
ls11 = cur().get("_lscan") if isinstance(cur().get("_lscan"), dict) else {}
T.chk(hb11 in (ls11.get("found") or []) and hb11 not in emitted(wr11), "N11 전제: 라이브 상세 실패(그 해시는 체크포인트)", ls11)
T.chk(hn11 in emitted(wr11), "N11 별개의 거래소 출금 BNB 입금은 그 주기에 방출(상세 실패와 무관)", {"n": len(wr11.recs)})
CH.bad_rc.clear()

reset_state()
CH.mode, CH.old_below = "pruned", H0 - 3_000_000
CH.head = H0 + 90_000
hs_new = CH.native(CH.head - 300, W1, OTHER, 10 ** 17)
hs_old = CH.native(CH.head - 2_000_000, W1, OTHER, 2 * 10 ** 17)
exch_withdraw("0x" + "f" * 64, W2)
wr12 = Wr()
w = mk(wr=wr12)
cycle(w)
nst = common.read_json(os.path.join(common.STATE_DIR, "bsc_nonce.json"), {})
recs12 = {r["txhash"]: r for r in wr12.recs}
T.chk(hs_new in recs12 and recs12[hs_new].get("via") == "nonce", "N12 차선 중 라이브 범위 순수 BNB 발신 = 첫 주기에 회수(nonce)",
      {"emitted": len(recs12), "w": {k[:6]: {kk: v.get(kk) for kk in ("lo", "top", "missing")} for k, v in (nst.get("w") or {}).items()}})
T.chk(hs_old not in recs12, "N12 옛 구간 발신은 차선 중엔 안 찾음(색인 불완전 — 차선 끝난 뒤)")
CH.mode = None
for _ in range(80):
    cycle(w)
    if not isinstance(cur().get("_live"), dict):
        break
off = [0.0]
bsc_watch._now = lambda: time.time() + off[0]
for _ in range(6):
    off[0] += 400
    CH.head += 10
    cycle(w)
    if hs_old in emitted(wr12):
        break
bsc_watch._now = time.time
T.chk(not isinstance(cur().get("_live"), dict) and hs_old in emitted(wr12), "N12 차선 끝 뒤 기본 하한으로 옛 구간 발신도 회수",
      {"live": cur().get("_live"), "n": len(wr12.recs)})
T.chk(len(emitted(wr12)) == len(set(emitted(wr12))), "N12 같은 tx 두 번 방출 0")

f9 = getattr(bf_engine, "bsc_backfill_days", None)
T.chk(callable(f9), "N9 bf_engine.bsc_backfill_days 있음")
if callable(f9):
    T.chk(f9({"backfill_months": 0.5, "bsc": {"backfill_days": 150}}) == 150, "N9 명시값 우선")
    T.chk(f9({"backfill_months": 0.5, "bsc": {}}) == 15, "N9 명시 없음 = 개월 × 30(0.5 → 15일)")
    T.chk(f9({"backfill_months": 5}) == 150, "N9 개월 5 → 150일")
    T.chk(f9({"bsc": {}}) == 120 and f9({"backfill_months": 5, "backfill_full_history": True}) == 120, "N9 개월 없음·전체 이력 = 종전 120")
w9 = bsc_watch.BscWatcher({"backfill_months": 0.5, "bsc": dict(cfg()["bsc"]), "wallets": []}, [W1], Wr())
T.chk(w9.backfill_days == 15, "N9 tj-bsc 가 개월 설정을 따름(예시 설정처럼 backfill_days 없을 때)", w9.backfill_days)

T.finish()
