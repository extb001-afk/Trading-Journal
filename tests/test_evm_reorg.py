#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _rpcfake as R  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

CH = "arc"
W0 = "0x" + "a1" * 20
X = "0x" + "c3" * 20
TKJ = "0x" + "d4" * 20
CONF = 10
HEAD0 = 2000
CHAIN = R.Chain(HEAD0, TKJ, int(time.time()) - 4 * HEAD0)
NODE = R.Node(lambda m, p: CHAIN.one(m, p))


def ccfg(**kw):
    c = {"discovery": "rpc", "rpcs": [NODE.url], "rpc_logs": [NODE.url], "trace_rpcs": [], "multicall3": False, "rpc_node_table": False,
         "conf_depth": CONF, "blocks_per_day": 43200, "poll_sec": 60, "cycle_budget_sec": 60, "getlogs_span": 5000, "rpc_lanes": False}
    c.update(kw)
    return c


CFG = {"backfill_months": 0, "chains": {CH: ccfg()}, "wallets": [{"type": "evm", "chain": CH, "address": W0, "label": "w"}],
       "backfill": {"hosts": {"127.0.0.1": {"rate": 5000, "burst": 5000, "conc": 8}}}}
with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump(CFG, f)
import paths, statefile  # noqa: E402
import bf_engine  # noqa: E402
import evm_reorg  # noqa: E402
import evm_watch  # noqa: E402
import health  # noqa: E402

R.loop_open(bf_engine, T)
bf_engine.configure(CFG)
CP = paths.state(f"cursor_evm_{CH}.json")
EP = paths.state(f"emitted_evm_{CH}.json")
C0 = HEAD0 - 200


class Wr:
    def __init__(self):
        self.recs = []

    def append(self, rec):
        self.recs.append(rec)

    def hashes(self):
        return [r["txhash"] for r in self.recs]


HB = []


def mk(cfg=None, cur=None):
    statefile.atomic_write_json(CP, cur if cur is not None else {"_rpc_v": evm_watch.RpcChainWatcher.VERSION, "_start": 0, W0: C0,
                                                                 "_ns": {W0: [C0, 0, str(CHAIN.bal), 0, "0"]}, "_wallets": [W0]})
    statefile.atomic_write_json(EP, [])
    wr = Wr()
    w = evm_watch.RpcChainWatcher(cfg or CFG, CH, [W0], wr)
    w._init = lambda safe: None

    def hc(kind, head, safe, ok, err=None, **extra):
        HB.append({"ok": ok, "reorg": evm_reorg.held(w.cursor), "err": str(err)[:80] if err else None})
    w._health_cycle = hc
    return w, wr


def cyc(w, head):
    CHAIN.head = head
    r = T.safe(w.cycle)
    return r


def disk():
    return statefile.read_json(CP, {})


def blk_calls(since):
    return sum(1 for m, p in NODE.calls[since:] if m == "eth_getBlockByNumber" and p and p[1] is False)


def ready():
    import core_recon
    mix = next(c for c in vars(core_recon).values() if isinstance(c, type) and "_scope_ready" in vars(c) and "_scope_ready_tok" in vars(c))

    class Recon(mix):
        def __init__(self):
            self.cfg = CFG
            self.my_wallets = {CH: {W0}}
            self.chain_owners = {}
    o = Recon()
    full = o._scope_ready(CH)
    cur9 = disk()
    statefile.atomic_write_json(CP, dict(cur9, _synced_at=0, _ext_internal_lag={"ts": int(time.time())}, _synced_tok_at=int(time.time())))
    tok = o._scope_ready_tok(CH)
    statefile.atomic_write_json(CP, cur9)
    return full, tok


def hitems(src_reorg, open_ids=()):
    out = []

    def add(cid, unit, title, level, detail="", action="", **k):
        out.append({"id": cid, "level": level, "title": title, "action": action, "detail": detail})
    evm_reorg.health_items(add, {"hb": {"evm": {"sources": {CH: {"reorg": src_reorg}}}}}, {"tj-evm"}, set(open_ids), health.CHAIN_NAME)
    return out


A = CHAIN.transfer(HEAD0 - 100, X, W0, 5_000_000)
B = CHAIN.transfer(HEAD0 - 15, X, W0, 6_000_000)
w, wr = mk()
r = cyc(w, HEAD0)
ring1 = disk().get("_ring")
T.chk(r is None and set(wr.hashes()) == {A, B} and isinstance(ring1, list) and len(ring1) == 1 and ring1[0][0] == HEAD0 - CONF
      and disk().get(W0) == HEAD0 - CONF and not disk().get("_reorg"), "G1 첫 사이클: 방출 2 · 고리 1칸(safe) · 보류 없음",
      {"r": r, "ring": ring1, "cur": disk().get(W0), "emit": len(wr.recs)})
Cx = CHAIN.transfer(HEAD0 + 15, X, W0, 7_000_000)
r = cyc(w, HEAD0 + 30)
ring2 = disk().get("_ring")
T.chk(r is None and Cx in wr.hashes() and [e[0] for e in ring2] == [HEAD0 - CONF, HEAD0 + 30 - CONF] and HB[-1]["reorg"] is None
      and all(ready()), "G1 둘째 사이클: 새 거래 방출 · 고리 2칸 · 하트비트 reorg 없음 · 대사 준비",
      {"r": r, "ring": ring2, "hb": HB[-1], "ready": ready()})

FORK = HEAD0 + 5
n_emit0 = len(wr.recs)
D = CHAIN.reorg(FORK, drop=[Cx], add=[(HEAD0 + 8, X, W0, 8_000_000)])[0]
r = cyc(w, HEAD0 + 60)
d2 = disk()
rg = d2.get("_reorg") or {}
T.chk(r is None and rg.get("anc") == HEAD0 - CONF and rg.get("from") == HEAD0 - CONF + 1 and rg.get("top") == HEAD0 + 20,
      "G2 재편 감지: 공통 조상 = 해시 같은 가장 높은 고리 칸 · 영향 블록 from..top", {"r": r, "reorg": rg})
T.chk(D in wr.hashes() and wr.hashes().count(Cx) == 1 and len(wr.recs) == n_emit0 + 1 and d2.get(W0) == HEAD0 + 60 - CONF,
      "G2 커서 되감아 새 갈래 거래 방출 · 사라진 갈래 거래는 다시 안 보냄(원장 자동 삭제 없음) · 같은 사이클에 safe 까지",
      {"emit": wr.hashes()[n_emit0:], "cur": d2.get(W0)})
T.chk(isinstance(HB[-1]["reorg"], dict) and HB[-1]["ok"] and ready() == (False, False),
      "G2 하트비트 사실 reorg(수집은 정상) · core 대사 준비 거짓(전체·토큰 칸 둘 다)", {"hb": HB[-1], "ready": ready()})
it = hitems(rg)
T.chk(len(it) == 1 and it[0]["id"] == f"evm:reorg:{CH}" and it[0]["level"] == "warn" and f"reorg_ack: {rg.get('from')}" in it[0]["action"],
      "G2 헬스 evm:reorg 주황 · 조치 = 그 블록으로 reorg_ack", it)
import discopen  # noqa: E402
lh = discopen.lane_hold(CH, W0, HEAD0)
T.chk(isinstance(lh, str) and "재편" in lh, "G2 발견 기초잔고(arch·대체·재점검) 차선 보류 = 재편 보류 중 대기", lh)
T.chk([e[0] for e in d2.get("_ring") or []] == [HEAD0 - CONF, HEAD0 + 60 - CONF], "G2 고리 = 공통 조상까지 + 이번 safe(새 갈래 · 이번에 훑은 구간을 덮음)", d2.get("_ring"))
r = cyc(w, HEAD0 + 90)
T.chk(r is None and (disk().get("_reorg") or {}).get("from") == rg.get("from") and len(wr.recs) == n_emit0 + 1,
      "G2 다음 사이클: 보류 유지(ack 전) · 중복 방출 없음", {"r": r, "reorg": disk().get("_reorg")})

w.reorg_set = evm_reorg.settings(ccfg(reorg_ack=rg["from"] - 1))
r = cyc(w, HEAD0 + 120)
T.chk(r is None and evm_reorg.held(disk()) is not None and ready() == (False, False), "G3 ack < from = 그대로 보류", disk().get("_reorg"))
w.reorg_set = evm_reorg.settings(ccfg(reorg_ack=rg["from"]))
r = cyc(w, HEAD0 + 150)
T.chk(r is None and "_reorg" not in disk() and HB[-1]["reorg"] is None and all(ready()),
      "G3 ack ≥ from = 수집기 첫 사이클에 보류 기록 지움 · 하트비트 사실 없음 · core 대사 준비", {"reorg": disk().get("_reorg"), "ready": ready()})
T.chk(discopen.lane_hold(CH, W0, HEAD0) is None, "G3 해제 뒤 발견 기초잔고 차선 보류 없음", discopen.lane_hold(CH, W0, HEAD0))
it = hitems(None, open_ids={f"evm:reorg:{CH}"})
T.chk(len(it) == 1 and it[0]["level"] == "ok" and not hitems(None), "G3 헬스: 열린 사건만 ok(해제) · 평소엔 항목 없음", it)

w, wr = mk()
cyc(w, HEAD0 + 160)
cyc(w, HEAD0 + 180)
last4 = disk()["_ring"][-1][0]
CHAIN.flap[last4] = 1
c4 = disk().get(W0)
r = cyc(w, HEAD0 + 210)
T.chk(r is None and "_reorg" not in disk() and disk().get(W0) == c4 == last4, "G4 한 번 흔들린 해시 = 다시 물어 같음 → 보류·되감기 없음 · 이번 주기 전진 쉼(확인된 블록까지)",
      {"r": r, "reorg": disk().get("_reorg"), "c4": c4, "cur": disk().get(W0)})
r = cyc(w, HEAD0 + 240)
T.chk(r is None and "_reorg" not in disk() and len(disk()["_ring"]) >= 3 and disk().get(W0) == HEAD0 + 240 - CONF, "G4 다음 사이클 정상 기록·전진", disk().get("_ring"))

ring5 = disk()["_ring"]
n5 = len(wr.recs)
D5 = CHAIN.reorg(ring5[0][0] - 30, add=[(ring5[0][0] - 25, X, W0, 1_100_000)])[0]
r = cyc(w, HEAD0 + 270)
rg5 = disk().get("_reorg") or {}
T.chk(r is None and rg5.get("anc") is None and rg5.get("from") == int(disk().get("_start") or 0) + 1 and D5 in wr.hashes()
      and wr.hashes().count(D5) == 1 and len(wr.recs) == n5 + 1,
      "G5 고리 칸 전부 바뀜 = 공통 조상 없음 · 추적 창 시작까지 되감아 고리 앞 새 갈래 거래도 방출 · 중복 0 · 보류",
      {"reorg": rg5, "ring": ring5, "new": wr.hashes()[n5:]})
it = hitems(rg5)
T.chk(len(it) == 1 and it[0]["level"] == "warn" and "고리 밖" in it[0]["detail"], "G5 헬스 주황 · 공통 조상 '고리 밖'", it)

w, wr = mk()
cyc(w, HEAD0 + 300)
cyc(w, HEAD0 + 330)
last8 = disk()["_ring"][-1][0]
F8 = CHAIN.transfer(last8 + 5, X, W0, 1_200_000)
CHAIN.null[last8] = 1
r = cyc(w, HEAD0 + 360)
T.chk(r is None and disk()["_ring"][-1][0] == last8 and "_reorg" not in disk() and disk().get(W0) == last8 and F8 not in wr.hashes(),
      "G8 마지막 칸 null = 새 칸 안 적음 · 커서가 확인된 블록 위로 안 감(그 구간 거래 아직 안 보냄)", {"ring": disk().get("_ring"), "cur": disk().get(W0)})
D8 = CHAIN.reorg(last8 + 3, drop=[F8], add=[(last8 + 4, X, W0, 1_300_000)])[0]
r = cyc(w, HEAD0 + 390)
T.chk(r is None and D8 in wr.hashes() and F8 not in wr.hashes() and "_reorg" not in disk() and disk().get(W0) == HEAD0 + 390 - CONF,
      "G8 확인된 블록 위에서 갈린 재편 = 새 갈래 거래만 방출 · 사라진 거래는 처음부터 안 보냄(보류 불필요)", {"emit": wr.hashes()[-3:], "cur": disk().get(W0)})
last8b = disk()["_ring"][-1][0]
CHAIN.null[last8b] = 3
c8 = disk().get(W0)
cyc(w, HEAD0 + 420)
cyc(w, HEAD0 + 450)
T.chk(disk().get(W0) == c8, "G8 연속 2번 확인 못 함 = 전진 쉼 유지", disk().get(W0))
r = cyc(w, HEAD0 + 480)
T.chk(r is None and disk().get(W0) == HEAD0 + 480 - CONF and disk().get("_ring") == [], "G8 연속 3번 = 고리 새로 시작하고 수집 계속(정지 금지)",
      {"cur": disk().get(W0), "ring": disk().get("_ring")})
r = cyc(w, HEAD0 + 510)
T.chk(r is None and len(disk().get("_ring") or []) == 1, "G8 다음 주기 첫 칸 기록", disk().get("_ring"))

w, wr = mk()
CHAIN.null[HEAD0 + 540 - CONF] = 1
r = cyc(w, HEAD0 + 540)
T.chk(r is None and disk().get(W0) == C0 and not disk().get("_ring"), "G10 고리 없는데 첫 safe 해시 null = 커서 그대로(기준 없이 훑지 않음)",
      {"cur": disk().get(W0), "ring": disk().get("_ring")})
r = cyc(w, HEAD0 + 570)
T.chk(r is None and disk().get(W0) == HEAD0 + 570 - CONF and len(disk().get("_ring") or []) == 1, "G10 다음 주기 첫 칸 기록·전진", disk().get("_ring"))

w, wr = mk()
for k in range(40):
    cyc(w, HEAD0 + 600 + 30 * k)
rg9 = [e[0] for e in disk()["_ring"]]
first9 = HEAD0 + 600 - CONF
T.chk(len(rg9) == evm_reorg.RING_MAX and rg9[0] == first9 and rg9[-evm_reorg.RING_DENSE:] == [HEAD0 + 600 + 30 * k - CONF for k in range(28, 40)]
      and rg9 == sorted(rg9), "G9 고리 = 최대 24칸 · 첫 칸 남김 · 최근 12칸 빽빽 · 앞쪽 성기게", rg9)

def run_calls(cfg9):
    bf_engine._EP_HEADS.clear()
    w9, _wr9 = mk(cfg9)
    cyc(w9, HEAD0 + 2000)
    n0 = len(NODE.calls)
    b0 = blk_calls(n0)
    for k in range(4):
        cyc(w9, HEAD0 + 2030 + 30 * k)
    import collections
    return len(NODE.calls) - n0, blk_calls(n0) - b0, disk(), collections.Counter(m for m, _p in NODE.calls[n0:])


on_n, on_b, _d_on, on_m = run_calls(CFG)
off_cfg = dict(CFG, chains={CH: ccfg(reorg_check=False)})
off_n, off_b, d_off, off_m = run_calls(off_cfg)
T.chk(on_n - off_n == 8 and on_b - off_b == 8, "G6 재편 확인 = 사이클당 정확히 2콜(블록 해시 · 4사이클 8콜)", {"on": on_n, "off": off_n, "blk_on": on_b, "blk_off": off_b,
                                                                                         "on_m": dict(on_m), "off_m": dict(off_m)})
T.chk("_ring" not in d_off and "_reorg" not in d_off, "G6 reorg_check: false = 고리 없음 · 확인 없음", sorted(k for k in d_off if k.startswith("_r")))

w, wr = mk()
r = cyc(w, HEAD0 + 2500)
T.chk(r is None and len(disk().get("_ring") or []) == 1 and "_reorg" not in disk(), "G7 고리 없는 옛 커서 = 첫 사이클 기록만(보류 없음)", disk().get("_ring"))
cur7 = disk()
cur7["_reorg"] = {"at": 1, "from": HEAD0 + 400, "top": HEAD0 + 450, "anc": None, "n": 1, "why": "합성"}
w, wr = mk(cfg=dict(CFG, chains={CH: ccfg(reorg_check=False)}), cur=cur7)
E7 = CHAIN.transfer(HEAD0 + 2520, X, W0, 9_000_000)
r = cyc(w, HEAD0 + 2540)
d7 = disk()
T.chk(r is None and E7 in wr.hashes() and d7.get("_ring") == cur7["_ring"] and d7.get("_reorg") == cur7["_reorg"] and d7.get(W0) == HEAD0 + 2540 - CONF,
      "G7 새 키(_ring·_reorg)가 든 커서로 확인 없는 사이클이 그대로 돌고 키 보존", {"r": r, "keys": sorted(k for k in d7 if k.startswith("_r"))})

w, wr = mk()
cyc(w, HEAD0 + 2600)
cyc(w, HEAD0 + 2630)
r11 = [e[0] for e in disk()["_ring"]]
NB = r11[-2] + 5
CHAIN.reorg(r11[-2] + 2)
CHAIN.nat[NB] = 777_000
nn0 = len(disk().get("_native_notes") or [])
r = cyc(w, HEAD0 + 2660)
d11 = disk()
nt11 = (d11.get("_native_notes") or [])[nn0:]
T.chk(r is None and (d11.get("_reorg") or {}).get("anc") == r11[-2] and not [n for n in nt11 if n.get("kind") == "baseline"]
      and [n for n in nt11 if n.get("kind") == "unexplained" and n.get("blk") == NB and n.get("native") == "777000"],
      "G11 재편 되감기 뒤 네이티브 기준점 = 되감은 블록 상태(새 기준점으로 입금을 삼키지 않음) → 새 갈래 로그 없는 입금이 정합 잎으로 잡힘",
      {"reorg": d11.get("_reorg"), "notes": nt11})
CHAIN.nat.clear()

import threading  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402


class BsH(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        d = ({"items": [{"height": HEAD0, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}]}
             if self.path.startswith("/api/v2/blocks") else {"items": [], "next_page_params": None})
        b = json.dumps(d).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


BS = ThreadingHTTPServer(("127.0.0.1", 0), BsH)
BS.daemon_threads = True
threading.Thread(target=BS.serve_forever, daemon=True).start()
REC12 = {"at": 1, "from": 500, "top": 600, "anc": 499, "n": 1, "why": "합성"}
cc12 = ccfg(discovery="auto", blockscout=f"http://127.0.0.1:{BS.server_address[1]}", etherscan_chainid=1)
cfg12 = dict(CFG, chains={CH: cc12})
cur12 = {"_rpc_v": evm_watch.RpcChainWatcher.VERSION, "_start": 0, W0: C0, "_wallets": [W0], "_reorg": dict(REC12)}


def held12():
    return (disk().get("_reorg") or {}).get("from") == 500


for kind12, mk12 in (("블록스카웃", lambda c: evm_watch.ChainWatcher(c, CH, [W0], Wr())),
                     ("이더스캔", lambda c: evm_watch.EtherscanWatcher(c, CH, [W0], Wr(), 1, "합성키"))):
    statefile.atomic_write_json(CP, dict(cur12))
    nw12 = T.safe(lambda: mk12(cfg12))
    T.chk(not isinstance(nw12, dict) and disk().get("_rpc_v") is None and held12() and ready() == (False, False)
          and isinstance(discopen.lane_hold(CH, W0, HEAD0), str),
          f"G12 RPC → {kind12} 되돌림(rpc_handback): 보류 기록 그대로 · 대사·발견 차선 보류 유지(ack 없이 안 풀림)", {"w": str(nw12)[:60], "cur": sorted(disk())})
    statefile.atomic_write_json(CP, dict(cur12))
    nw12 = T.safe(lambda: mk12(dict(CFG, chains={CH: dict(cc12, reorg_ack=500)})))
    T.chk(not isinstance(nw12, dict) and "_reorg" not in disk(), f"G12 {kind12} 생성 때 reorg_ack ≥ from = 보류 해제", sorted(disk()))
statefile.atomic_write_json(paths.state(evm_watch.EVM_ROUTE_FILE), {CH: {"route": "rpc_first", "at": 1, "why": "합성"}})
w12, _wr12 = mk(cfg12, cur=dict(cur12))
evm_watch._RPCFB_MEM[CH] = {"rpc_fail_since": time.time() - 2 * evm_watch.RPC_LR_SEC, "rpc_fail_n": 2 * evm_watch.RPC_LR_MIN_N}
lr12 = T.safe(lambda: evm_watch.rpc_first_last_resort(cfg12, w12, Wr()))
T.chk(type(lr12).__name__ == "ChainWatcher" and held12() and ready() == (False, False),
      "G12 rpc_first 최후 경로(블록스카웃 전환): 보류 따라감 · 대사 보류 유지", {"ret": type(lr12).__name__, "cur": sorted(disk())})
evm_watch._RPCFB_MEM.pop(CH, None)
statefile.atomic_write_json(CP, {W0: C0, "_wallets": [W0], "_reorg": dict(REC12)})
wr12 = Wr()
w12 = evm_watch.RpcChainWatcher(CFG, CH, [W0], wr12)
r = cyc(w12, HEAD0 + 2700)
T.chk(r is None and disk().get("_rpc_v") is not None and held12(), "G12 탐색기 → RPC 초기화: 보류 기록 따라감(ack 전 유지)", {"r": r, "cur": sorted(disk())})
BS.shutdown()

NODE.close()
T.finish()
