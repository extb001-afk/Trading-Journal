#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import copy  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import types  # noqa: E402
import urllib.error  # noqa: E402

W0 = "0x" + "e0" * 20
W1 = "0x" + "e1" * 20
RT = "0x" + "55" * 20
CFG = {"backfill_months": 0,
       "chains": {"base": {"discovery": "rpc", "chain_id": 8453, "rpcs": ["http://127.0.0.1:9/rpc"], "conf_depth": 10, "blocks_per_day": 43200,
                           "rpc_log_span_caps": {"http://127.0.0.1:9/rpc": 5000}}},
       "wallets": [{"type": "evm", "chain": "base", "address": W0, "label": "w0"}, {"type": "evm", "chain": "base", "address": W1, "label": "w1"}]}
CP = os.path.join(T.TMP, "config.json")
with open(CP, "w", encoding="utf-8") as f:
    json.dump(CFG, f)
os.environ["TJ_CONFIG"] = CP
import paths, statefile  # noqa: E402

assert T.TMP in paths.STATE_DIR and T.TMP in paths.ENV_PATH
import alch_internal as AI  # noqa: E402
import bf_engine  # noqa: E402
import evm_watch  # noqa: E402
import nodekeys as NK  # noqa: E402


def check(n, c, d=""):
    T.chk(bool(c), n, None if c else str(d)[:1200])


AKEY = "TESTalchKEY000000000000002"
AHOST = "base-mainnet.g.alchemy.com"
CN = "https://base-mainnet.chainnodes.org/0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
HCN = "base-mainnet.chainnodes.org"
DRPC = evm_watch.RpcChainWatcher.TRACE_DEFAULT["base"][0]
DH = DRPC.split("/")[2]
HEAD = 50_000_000
BPD = 43200
OLD = HEAD - 60 * BPD
RECENT = HEAD - 100
DAY = 86400

CLK = {"off": 0.0}
_RT = evm_watch.time


def _mk_ft():
    ft = types.SimpleNamespace(**{k: getattr(_RT, k) for k in dir(_RT) if not k.startswith("__")})
    ft.time = lambda: _RT.time() + CLK["off"]
    ft.monotonic = lambda: _RT.monotonic() + CLK["off"]
    ft.sleep = lambda x: CLK.__setitem__("off", CLK["off"] + max(0.0, float(x)))
    return ft


FT = _mk_ft()
evm_watch.time = FT
T.patch_moved("time", evm_watch.time, ("evm_",))
bf_engine.time = FT
AI.time = FT


def now():
    return FT.time()


def adv(sec):
    CLK["off"] += max(0.0, float(sec))


def hx(n):
    return "0x" + f"{n:064x}"


def atr(h, frm, to, raw, path, blk):
    return {"blockNum": hex(blk), "uniqueId": f"{h}:internal:{path}", "hash": h, "from": frm, "to": to, "value": 1.0e-18,
            "erc721TokenId": None, "erc1155Metadata": None, "tokenId": None, "asset": "ETH", "category": "internal",
            "rawContract": {"value": raw, "address": None, "decimal": "0x12"}, "metadata": None}


class _Resp:
    def __init__(self, obj):
        self._b = json.dumps(obj).encode()
        self.headers = {}
        self.length = len(self._b)

    def read(self, n=-1):
        b, self._b = self._b, b""
        return b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


GAP = {"code": -32603, "message": "transaction not found", "data": {"code": "ErrUpstreamsExhausted"}}
ERRS9 = {"nm": {"code": -32601, "message": "the method debug_traceBlockByNumber does not exist/is not available"},
         "hist": {"code": -32000, "message": "required historical state unavailable (reexec=128)"}}
PLAN = {}
AL_PAGES = {}
AL_DELAY = {"s": 0.3}
AL_FAIL = {"n": 0, "code": 500}
AL_HOOK = {"open_after": None}
RECEIPTS = {}
RCPT_SLOW = set()
RC_HITS = []
BLOCK_TRACE = {}
RCPT_DELAY = {"s": 0.05}
HITS = []


def fake_open(req, timeout):
    h = req.host.split(":")[0].lower()
    body = json.loads(req.data.decode()) if req.data else {}
    if isinstance(body, list):
        HITS.append((h, "batch:" + ",".join(sorted({str(x.get("method")) for x in body}))))
        RC_HITS.extend(str((x.get("params") or [""])[0]) for x in body if x.get("method") == "eth_getTransactionReceipt")
        slow9 = RCPT_DELAY["s"] == "rest" or any((x.get("params") or [None])[0] in RCPT_SLOW for x in body)
        d9 = float(timeout) if slow9 else float(RCPT_DELAY["s"])
        adv(min(d9, float(timeout)))
        if slow9:
            raise bf_engine.NetError("timed out", "timeout")
        return _Resp([{"jsonrpc": "2.0", "id": x["id"], "result": RECEIPTS.get(x["params"][0]) if x.get("method") == "eth_getTransactionReceipt" else None}
                      for x in body])
    m = body.get("method")
    HITS.append((h, m))
    if h == AHOST:
        adv(AL_DELAY["s"])
        if AL_FAIL["n"]:
            AL_FAIL["n"] -= 1
            c9 = int(AL_FAIL.get("code") or 500)
            raise urllib.error.HTTPError(req.full_url, c9, "Unauthorized" if c9 == 401 else "Internal Server Error", {},
                                         io.BytesIO(b'{"message":"unauthorized"}' if c9 == 401 else b'{"message":"internal error"}'))
        prm = (body.get("params") or [{}])[0]
        pages = AL_PAGES.get(int(prm["fromBlock"], 16)) or [{"transfers": []}]
        pk = prm.get("pageKey")
        i9 = 0 if not pk else int(str(pk).split("-")[-1])
        if AL_HOOK["open_after"] is not None and i9 >= AL_HOOK["open_after"]:
            g9 = bf_engine.gate(AHOST)
            g9.open_until, g9.open_count = bf_engine.time.time() + 100000, 2
        return _Resp({"jsonrpc": "2.0", "id": 1, "result": pages[min(i9, len(pages) - 1)]})
    kind, dly = PLAN.get(h, ("ok", 0.0))
    d9 = (float(timeout) - 0.01) if dly == "rest" else float(dly)
    adv(max(0.0, min(d9, float(timeout))))
    if kind == "gap":
        return _Resp({"jsonrpc": "2.0", "id": 1, "error": GAP})
    if kind in ERRS9:
        return _Resp({"jsonrpc": "2.0", "id": 1, "error": ERRS9[kind]})
    if kind == "408":
        raise urllib.error.HTTPError(req.full_url, 408, "Request Timeout", {}, io.BytesIO(b'{"message":"Request timeout on the free plan"}'))
    if m == "debug_traceBlockByNumber":
        return _Resp({"jsonrpc": "2.0", "id": 1, "result": BLOCK_TRACE.get(int(body["params"][0], 16), [])})
    if m == "trace_transaction":
        return _Resp({"jsonrpc": "2.0", "id": 1, "result": [
            {"type": "call", "traceAddress": [], "action": {"from": W0, "to": RT, "value": "0x0", "callType": "call"}},
            {"type": "call", "traceAddress": [0], "action": {"from": RT, "to": W0, "value": "0x2a", "callType": "call"}}]})
    return _Resp({"jsonrpc": "2.0", "id": 1, "result": {"type": "CALL", "from": W0, "to": RT, "value": "0x0",
                                                        "calls": [{"type": "CALL", "from": RT, "to": W0, "value": "0x2a"}]}})


bf_engine._open = fake_open


class Wr:
    def __init__(self):
        self.recs = []

    def append(self, rec):
        self.recs.append(copy.deepcopy(rec))


WR = Wr()


def det(hs, **kw):
    return {h: {"tx": {"hash": h, "block_number": BLK.get(h, OLD), "from": FT9.get(h, (W0, RT))[0], "to": FT9.get(h, (W0, RT))[1], "status": "ok", "synth": "rpc"},
                "token_transfers": [], "internal": []} for h in hs}


FT9 = {}


BLK = {}


def mk():
    w9 = evm_watch.RpcChainWatcher(CFG, "base", [W0, W1], WR)
    w9._log_head = HEAD
    w9.trace_rpcs = [CN, DRPC]
    w9._details = det
    w9.cursor["_handover"] = {}
    return w9


def fresh(key=True):
    with bf_engine._GATES_LOCK:
        bf_engine._GATES.clear()
    AI._OFF["until"] = 0.0
    HITS.clear()
    if key:
        os.environ[NK.ENV_ALCHEMY] = AKEY
    else:
        os.environ.pop(NK.ENV_ALCHEMY, None)


def setup(w9, h, blk=OLD, at=None, n=0, stg=None, emit=True):
    t9 = int(now())
    e9 = {"at": int(at if at is not None else t9 - 3600), "n": int(n), "next": t9 - 1, "blk": int(blk), "sent": True}
    if stg is not None:
        e9["stg"] = stg
    w9.cursor["_trace_later"] = {h: e9}
    w9.cursor["_native_notes"] = []
    w9.emitted.add(h)
    BLK[h] = blk
    for k9 in ("_alch_memo", "_trace_slow_until", "_trace_sick_until", "_trace_nf"):
        w9.__dict__.pop(k9, None)
    WR.recs.clear()
    statefile.atomic_write_json(w9.cursor_path, w9.cursor)


def al_hits(hs=None):
    return [m for h, m in (HITS if hs is None else hs) if h == AHOST]


def tr_hits(hs):
    return [(h, m) for h, m in hs if h in (HCN, DH)]


def ent(w9, h):
    return (w9.cursor.get("_trace_later") or {}).get(h)


def cycle(w9, h):
    t0, k0 = now(), len(HITS)
    n9 = w9._trace_later_step(HEAD)
    el = now() - t0
    hs = HITS[k0:]
    e9 = copy.deepcopy(ent(w9, h))
    adv(max(601.0, (int(e9.get("next") or 0) - now() + 1) if isinstance(e9, dict) else 0, 601.0))
    return {"el": round(el, 2), "emit": n9, "al": len(al_hits(hs)), "trace": tr_hits(hs), "e": e9}


def fills(h):
    return [r for r in WR.recs if r.get("repair") == "int_fill" and (r.get("snapshot") or {}).get("tx", {}).get("hash") == h]


ROW42 = [{"from": RT, "to": W0, "value": "42", "success": True}]
SLOW = {HCN: ("gap", 0.5), DH: ("408", "rest")}
FAST = {HCN: ("gap", 0.0), DH: ("408", 0.0)}
NIDS = sorted(evm_watch.RpcChainWatcher._trace_nid(u) for u in (CN, DRPC))
X1, X2 = "0x" + "71" * 20, "0x" + "72" * 20


def rc_n(h, k0):
    return sum(1 for x in RC_HITS[k0:] if x == h)


def setup_tl(w9, items):
    t9 = int(now())
    tl = {}
    for h, blk, nx, stg, n in items:
        tl[h] = {"at": t9 - 3600, "n": int(n), "next": t9 - nx, "blk": int(blk), "sent": True}
        if stg is not None:
            tl[h]["stg"] = copy.deepcopy(stg)
        w9.emitted.add(h)
        BLK[h] = blk
    w9.cursor["_trace_later"] = tl
    w9.cursor.pop("_leaf_later", None)
    w9.cursor["_native_notes"] = []
    for k9 in ("_alch_memo", "_trace_slow_until", "_trace_sick_until", "_trace_nf"):
        w9.__dict__.pop(k9, None)
    WR.recs.clear()
    statefile.atomic_write_json(w9.cursor_path, w9.cursor)


def tl_cycle(w9):
    t0, k0, r0 = now(), len(HITS), len(RC_HITS)
    n9 = w9._trace_later_step(HEAD)
    el = now() - t0
    hs = HITS[k0:]
    adv(601.0)
    return {"el": round(el, 2), "emit": n9, "al": len(al_hits(hs)), "trace": tr_hits(hs), "rc": list(RC_HITS[r0:])}


STG2 = {"v": 1, "ct": NIDS, "pa": NIDS, "al": 0}
OB = OLD - 10
HA, HB = hx(0xF101), hx(0xF102)
AL_PAGES[OLD] = [{"transfers": [atr(HA, RT, W0, "0x2a", "0_1", OLD)]}]
AL_PAGES[OB] = [{"transfers": [atr(HB, RT, W1, "0x2a", "0_1", OB)]}]
RECEIPTS[HA] = {"blockNumber": hex(OLD), "status": "0x1", "transactionHash": HA}
RECEIPTS[HB] = {"blockNumber": hex(OB), "status": "0x1", "transactionHash": HB}
FT9[HB] = (X1, X2)
ROWB = [{"from": RT, "to": W1, "value": "42", "success": True}]
PLAN.clear()
PLAN.update(SLOW)
RCPT_SLOW.clear()
RCPT_SLOW.add(HA)
fresh()
w = mk()
CFG0 = list(w.cfg_rpcs)
w.cfg_rpcs = ["http://127.0.0.1:9/r1", "http://127.0.0.1:9/r2"]
setup_tl(w, [(HA, OLD, 2, STG2, 2), (HB, OB, 1, STG2, 2)])
nxa = ent(w, HA)["next"]
k0 = len(RC_HITS)
of1 = []
for _i in range(8):
    of1.append(tl_cycle(w))
    if ent(w, HB) is None:
        break
fb = fills(HB)
check("F1a ★B-2 재현★ A 영수증 20초 마감이 이어져도 B 는 유한 사이클(≤ 2) 안에 영수증·Alchemy·int_fill(+42 wei · W1) · 큐에서 뺌",
      len(of1) <= 2 and rc_n(HB, k0) >= 1 and sum(o["al"] for o in of1) >= 1 and len(fb) == 1
      and (fb[0].get("snapshot") or {}).get("internal") == ROWB and ent(w, HB) is None,
      [(o["el"], o["al"], o["emit"], o["rc"]) for o in of1])
ea = ent(w, HA) or {}
check("F1b A 는 큐에 그대로 · n 그대로 2(마감 = 실제 실패 아님 · 가짜 실패 없음) · next 그대로 · 단계 기록 그대로",
      ea.get("n") == 2 and ea.get("next") == nxa and (ea.get("stg") or {}).get("ct") == NIDS and (ea.get("stg") or {}).get("pa") == NIDS, ea)
check("F1c 사이클마다 절대 마감 안(≤ 31초)", all(o["el"] <= 31.0 for o in of1), [o["el"] for o in of1])
check("F1d A 영수증 마감 사이클 = 방출 0(부분 확정 없음) · A 의 int_fill 0", not fills(HA), WR.recs)
fresh()
setup_tl(w, [(HB, OB, 1, STG2, 2)])
k0 = len(RC_HITS)
oc = tl_cycle(w)
check("F1e 대조군(A 를 뺌) = 첫 사이클 B 영수증·Alchemy 1·int_fill 1·큐에서 뺌", rc_n(HB, k0) == 1 and oc["al"] == 1 and len(fills(HB)) == 1 and ent(w, HB) is None, oc)
RCPT_SLOW.add(HB)
fresh()
setup_tl(w, [(HA, OLD, 2, STG2, 2), (HB, OB, 1, STG2, 2)])
k0 = len(RC_HITS)
seq = []
for _i in range(4):
    r0 = len(RC_HITS)
    tl_cycle(w)
    seq.append(tuple(RC_HITS[r0:r0 + 1]))
    if _i == 1:
        w = mk()
        w.cfg_rpcs = ["http://127.0.0.1:9/r1", "http://127.0.0.1:9/r2"]
check("F1f 둘 다 영수증 마감 = 사이클마다 1건 · A → B → A → B 번갈아(재시작 뒤에도) · n 둘 다 2 그대로",
      seq == [(HA,), (HB,), (HA,), (HB,)] and (ent(w, HA) or {}).get("n") == 2 and (ent(w, HB) or {}).get("n") == 2, seq)
RCPT_SLOW.clear()
w.cfg_rpcs = CFG0

HS2 = [hx(0xF200 + i) for i in range(6)]
fresh()
for hh in HS2:
    RECEIPTS[hh] = {"blockNumber": hex(OLD), "status": "0x1", "transactionHash": hh}
setup_tl(w, [(hh, OLD, 10 - i, None, 0) for i, hh in enumerate(HS2)])
VIS = []


def _wrap(w9):
    o9 = type(w9)._trace_internal

    def f9(h, s):
        VIS.append(h)
        return o9(w9, h, s)
    w9._trace_internal = f9


_wrap(w)
per2 = []
for _i in range(6):
    with bf_engine._GATES_LOCK:
        bf_engine._GATES.clear()
    for hh in (HCN, DH):
        g9 = bf_engine.gate(hh)
        g9.open_until, g9.open_count = bf_engine.time.time() + 100000, 2
    v0, k0 = len(VIS), len(HITS)
    o2 = tl_cycle(w)
    per2.append((len(VIS) - v0, len(HITS) - k0))
    if _i == 2:
        w = mk()
        _wrap(w)
check("F2a 모든 trace 서킷(0콜) 항목 6개 = 사이클마다 1건만 · HTTP 0", all(p == (1, 0) for p in per2), per2)
check("F2b 6사이클에 6개 모두 한 번씩 차례(재시작 끼어도 · 같은 것 되풀이 없음)", sorted(VIS) == sorted(HS2), VIS)
check("F2c n 전부 0 그대로 · 단계 기록 없음(0콜 = 실패 아님)", all((ent(w, hh) or {}).get("n") == 0 and not ((ent(w, hh) or {}).get("stg") or {}).get("ct")
                                                     for hh in HS2), [ent(w, hh) for hh in HS2])
w.cursor.pop("_trace_later", None)
w = mk()


def setup_ll(w9, items):
    t9 = int(now())
    ll, ks = {}, []
    for wal, blk, nx, stg, n, at in items:
        k = f"{wal[:12]}:{int(blk)}"
        ll[k] = {"w": wal, "blk": int(blk), "at": int(at if at is not None else t9 - 3600), "n": int(n), "next": t9 - nx}
        if stg is not None:
            ll[k]["stg"] = copy.deepcopy(stg)
        ks.append(k)
    w9.cursor["_leaf_later"] = ll
    w9.cursor.pop("_trace_later", None)
    w9.cursor["_native_notes"] = []
    for k9 in ("_alch_memo", "_trace_slow_until", "_trace_sick_until", "_trace_nf"):
        w9.__dict__.pop(k9, None)
    WR.recs.clear()
    statefile.atomic_write_json(w9.cursor_path, w9.cursor)
    return ks


def lent(w9, k):
    return (w9.cursor.get("_leaf_later") or {}).get(k)


fresh()
kA, kB = setup_ll(w, [(W0, OLD, 2, None, 2, None), (W1, OB, 1, None, 2, None)])
VB = []


def _tb_stub(w9):
    def f9(y):
        VB.append(int(y))
        if int(y) == OLD:
            raise evm_watch.TraceDeferred("budget: 시험 — A 블록 마감")
        return {}, []
    w9._trace_block = f9


_tb_stub(w)
for _i in range(3):
    w._leaf_later_step(HEAD)
    adv(601.0)
    if lent(w, kB) is None:
        break
check("F2d 잎 큐: A 블록 마감 보류가 이어져도 B 잎은 다음 사이클에 처리(큐에서 뺌) · A 의 n 그대로 2",
      lent(w, kB) is None and OB in VB and (lent(w, kA) or {}).get("n") == 2, (VB, w.cursor.get("_leaf_later")))
w = mk()

HL = hx(0xF301)
ROWL = [{"from": RT, "to": W1, "value": "42", "success": True}]
LSLOW = {HCN: ("408", "rest"), DH: ("gap", 0.0)}


def lcycle(w9, k):
    t0, k0 = now(), len(HITS)
    n9 = w9._leaf_later_step(HEAD)
    el = now() - t0
    hs = HITS[k0:]
    e9 = copy.deepcopy(lent(w9, k))
    adv(max(601.0, (int(e9.get("next") or 0) - now() + 1) if isinstance(e9, dict) else 0))
    return {"el": round(el, 2), "emit": n9, "al": len(al_hits(hs)), "trace": tr_hits(hs), "e": e9}


def lrecs(h):
    return [r for r in WR.recs if (r.get("snapshot") or {}).get("tx", {}).get("hash") == h]


def lprep():
    AL_PAGES[OLD] = [{"transfers": [atr(HL, RT, W1, "0x2a", "0_1", OLD)]}]
    RECEIPTS[HL] = {"blockNumber": hex(OLD), "status": "0x1", "transactionHash": HL}
    FT9[HL] = (X1, X2)
    BLK[HL] = OLD
    w.emitted.discard(HL)


lprep()
PLAN.clear()
PLAN.update(LSLOW)
fresh()
(kL,) = setup_ll(w, [(W1, OLD, 1, None, 0, None)])
ol = []
for _i in range(8):
    ol.append(lcycle(w, kL))
    if lent(w, kL) is None:
        break
rl = lrecs(HL)
check("F3a ★B-1 재현★ 잎 블록: 첫 노드 59.99초 408 이 이어져도 유한 차례(≤ 3) 안에 drpc 도 묻고 Alchemy 1콜로 발견 · 그 tx 방출(+42 wei · W1) · 큐에서 뺌",
      len(ol) <= 3 and sum(o["al"] for o in ol) == 1 and any(hh == DH for o in ol for hh, _m in o["trace"]) and len(rl) == 1
      and (rl[0].get("snapshot") or {}).get("internal") == ROWL and lent(w, kL) is None,
      [(o["el"], o["al"], o["trace"], (o["e"] or {}).get("n"), (o["e"] or {}).get("stg")) for o in ol])
check("F3b 사이클마다 절대 마감(잎 첫 1건 60초 + Alchemy 최소 몫 8초 + 영수증) ≤ 70초", all(o["el"] <= 70.0 for o in ol), [o["el"] for o in ol])
check("F3c 1차 = Chainnodes 실제 408 만 기록(drpc 는 마감 미전송 = 기록 안 함) · n 1",
      ol and (ol[0]["e"] or {}).get("n") == 1 and ((ol[0]["e"] or {}).get("stg") or {}).get("tb") == [evm_watch.RpcChainWatcher._trace_nid(CN)], ol[:1])
FINAL_L1 = [(r.get("repair"), (r.get("snapshot") or {}).get("internal")) for r in rl]
lprep()
PLAN.clear()
PLAN.update({HCN: ("408", 0.0), DH: ("gap", 0.0)})
fresh()
(kL,) = setup_ll(w, [(W1, OLD, 1, None, 0, None)])
oc = lcycle(w, kL)
FINAL_L2 = [(r.get("repair"), (r.get("snapshot") or {}).get("internal")) for r in lrecs(HL)]
check("F3d 대조군(408 지연 0) = 첫 사이클 drpc 도 묻고 Alchemy 1 · 방출 1 · 지연군과 최종 기록 같음",
      oc["al"] == 1 and lent(w, kL) is None and FINAL_L1 == FINAL_L2 and FINAL_L1, (oc, FINAL_L1, FINAL_L2))

TB2 = sorted(evm_watch.RpcChainWatcher._trace_nid(u) for u in (CN, DRPC))
lprep()
PLAN.clear()
PLAN.update(LSLOW)
fresh()
(kL,) = setup_ll(w, [(W1, OLD, 1, {"v": 1, "tb": TB2, "al": 0}, 2, None)])
o4 = lcycle(w, kL)
check("F4a 현재 노드 전부 실제 실패 기록 = 이번 차례 Alchemy 먼저(trace 0콜) · 방출 1 · 큐에서 뺌",
      not o4["trace"] and o4["al"] == 1 and len(lrecs(HL)) == 1 and lent(w, kL) is None, o4)
lprep()
fresh()
for hh in (HCN, DH):
    g9 = bf_engine.gate(hh)
    g9.open_until, g9.open_count = bf_engine.time.time() + 100000, 2
(kL,) = setup_ll(w, [(W1, OLD, 1, None, 0, None)])
o4 = lcycle(w, kL)
check("F4b 모든 trace 서킷(0콜) = 기록 안 함 · n 그대로 · Alchemy 0콜 · 방출 0",
      isinstance(o4["e"], dict) and o4["e"].get("n") == 0 and not (o4["e"].get("stg") or {}).get("tb") and not o4["al"] and not o4["trace"] and not WR.recs, o4)
lprep()
PLAN.clear()
PLAN.update(LSLOW)
fresh()
(kL,) = setup_ll(w, [(W1, OLD, 1, None, 0, None)])
o4 = [lcycle(w, kL)]
w = mk()
o4.append(lcycle(w, kL))
check("F4c 재시작(디스크 커서) 뒤 둘째 차례 = 실패 기록 없는 drpc 먼저 → 보완 · 방출 1",
      o4[1]["trace"][:1] == [(DH, "debug_traceBlockByNumber")] and len(lrecs(HL)) == 1 and lent(w, kL) is None, o4)
T3 = "https://trace3.invalid/rpc"
lprep()
PLAN.clear()
PLAN.update({HCN: ("408", "rest"), DH: ("408", "rest"), "trace3.invalid": ("gap", 0.0)})
fresh()
w.trace_rpcs = [CN, DRPC, T3]
(kL,) = setup_ll(w, [(W1, OLD, 1, None, 0, None)])
o4 = []
for _i in range(8):
    o4.append(lcycle(w, kL))
    if lent(w, kL) is None:
        break
check("F4d 노드 3개(느린 둘 + pruned) = 각 노드가 차례를 받고 유한 차례(≤ 4) 안에 Alchemy 로 발견 · 방출 1",
      len(o4) <= 4 and len(lrecs(HL)) == 1 and lent(w, kL) is None and sum(o["al"] for o in o4) == 1, [(o["el"], o["trace"], o["al"], (o["e"] or {}).get("stg")) for o in o4])
check("F4e 노드 3개에서 셋째 노드도 실제로 물음", any(hh == "trace3.invalid" for hh, _m in HITS), None)
w = mk()

lprep()
PLAN.clear()
PLAN.update(LSLOW)
fresh()
(kL,) = setup_ll(w, [(W1, OLD, 1, None, 8, now() - 31 * DAY)])
o5 = lcycle(w, kL)
check("F5a 31일·8회 · Alchemy 실제 0회 = 지우지 않고 trace 차례(leaf_later_giveup 없음)",
      o5["trace"] and not any(n.get("kind") == "leaf_later_giveup" for n in w.cursor.get("_native_notes") or []), (o5, w.cursor.get("_native_notes")))
LARCH = os.path.join(paths.STATE_DIR, "leaf_later_unresolved_base.jsonl")
os.makedirs(LARCH, exist_ok=True)
fresh()
(kL,) = setup_ll(w, [(W1, OLD, 1, None, 9, now() - 61 * DAY)])
o5 = lcycle(w, kL)
check("F5b 61일 · 보관 쓰기 실패 = 큐 유지(지우지 않음)", isinstance(o5["e"], dict), o5)
os.rmdir(LARCH)
fresh()
(kL,) = setup_ll(w, [(W1, OLD, 1, None, 9, now() - 61 * DAY)])
o5 = lcycle(w, kL)
arows = []
if os.path.exists(LARCH):
    with open(LARCH, encoding="utf-8") as f:
        arows = [json.loads(x) for x in f if x.strip()]
check("F5c 61일(2×TTL) · Alchemy 실제 0회 = 전체 식별자(chain·전체 지갑·block·at·n·이유) 보관 뒤 뺌 · HTTP 0",
      lent(w, kL) is None and not o5["trace"] and not o5["al"]
      and any(r.get("chain") == "base" and r.get("w") == W1 and r.get("blk") == OLD and r.get("why") and r.get("at") for r in arows), (o5, arows))
fresh(key=False)
(kL,) = setup_ll(w, [(W1, OLD, 1, None, 8, now() - 31 * DAY)])
o5 = lcycle(w, kL)
check("F5d 키 없음 = 종전 만료(31일·5회 → leaf_later_giveup · HTTP 0)", lent(w, kL) is None and not o5["trace"]
      and any(n.get("kind") == "leaf_later_giveup" for n in w.cursor.get("_native_notes") or []), o5)
fresh()
(kL,) = setup_ll(w, [(W1, OLD, 1, {"v": 1, "tb": [], "al": 1}, 8, now() - 31 * DAY)])
o5 = lcycle(w, kL)
check("F5e 이미 Alchemy 를 실제로 물은 잎(al ≥ 1) = 종전 만료", lent(w, kL) is None and not o5["trace"]
      and any(n.get("kind") == "leaf_later_giveup" for n in w.cursor.get("_native_notes") or []), o5)
for bad in ("garbage", {"v": 9, "tb": TB2, "al": 0}, {"v": 1, "tb": "x", "al": "y"}):
    lprep()
    fresh()
    (kL,) = setup_ll(w, [(W1, OLD, 1, bad, 0, None)])
    o5 = lcycle(w, kL)
    check(f"F5f 깨진·모르는 stg({str(bad)[:16]}) = 기본값(Alchemy 먼저 아님 · trace 부터)", bool(o5["trace"]), o5)

lprep()
BLOCK_TRACE[OLD] = [{"txHash": HL, "result": {"type": "CALL", "from": X1, "to": RT, "value": "0x0",
                                              "calls": [{"type": "CALL", "from": RT, "to": W1, "value": "0x2a"}]}}]
PLAN.clear()
fresh()
(kL,) = setup_ll(w, [(W1, OLD, 1, None, 0, None)])
o6 = lcycle(w, kL)
check("F6a 정상 블록 trace 성공 = Alchemy 0콜 · 방출 1(trace 결과)", not o6["al"] and len(lrecs(HL)) == 1 and lent(w, kL) is None
      and (lrecs(HL)[0].get("snapshot") or {}).get("internal") == ROWL, o6)
lprep()
fresh()
(kL,) = setup_ll(w, [(W1, OLD, 1, {"v": 1, "tb": [evm_watch.RpcChainWatcher._trace_nid(CN)], "al": 0}, 1, None)])
o6 = lcycle(w, kL)
check("F6b 한 노드만 실패 기록 · 다른 노드 정상 = 그 노드 먼저 trace 성공(Alchemy 0콜)", not o6["al"] and o6["trace"][:1] == [(DH, "debug_traceBlockByNumber")]
      and lent(w, kL) is None, o6)
BLOCK_TRACE.pop(OLD, None)
lprep()
PLAN.clear()
PLAN.update(LSLOW)
fresh(key=False)
(kL,) = setup_ll(w, [(W1, OLD, 1, {"v": 1, "tb": TB2, "al": 0}, 2, None)])
o6 = lcycle(w, kL)
check("F6c 키 없음 · 노드 전부 실패 기록 = 종전 trace 경로(Alchemy 0콜 · 큐 유지 · n +1)", not o6["al"] and o6["trace"] and isinstance(o6["e"], dict)
      and o6["e"].get("n") == 3, o6)
w = mk()

TARCH = os.path.join(paths.STATE_DIR, "trace_later_unresolved_base.jsonl")


def arch_rows(p):
    if not os.path.isfile(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


STG_TB = {"v": 1, "tb": TB2, "al": 0}
lprep()
PLAN.clear()
PLAN.update(LSLOW)
fresh()
(kL,) = setup_ll(w, [(W1, OLD, 1, STG_TB, 8, now() - 31 * DAY)])
at7 = lent(w, kL)["at"]
a0 = len(arch_rows(LARCH))
AL_FAIL["n"] = 1
o7 = [lcycle(w, kL)]
AL_FAIL["n"] = 0
PLAN.clear()
o7.append(lcycle(w, kL))
ar7 = arch_rows(LARCH)[a0:]
check("F7a 1주기 = Alchemy 먼저 1콜(500) · 잎 남음 · al 1 · n 9", o7[0]["al"] == 1 and not o7[0]["trace"] and isinstance(o7[0]["e"], dict)
      and (o7[0]["e"].get("stg") or {}).get("al") == 1 and o7[0]["e"].get("n") == 9, o7[0])
check("F7b ★6.2 재현★ 2주기 만료(HTTP 0 · 뺌) 전에 전체 식별자 보관 — chain·k·전체 지갑·block·원래 at·n·stg(tb·al)·사유",
      lent(w, kL) is None and not o7[1]["trace"] and not o7[1]["al"]
      and any(r.get("chain") == "base" and r.get("k") == kL and r.get("w") == W1 and r.get("blk") == OLD and r.get("at") == at7 and r.get("n") == 9
              and (r.get("stg") or {}).get("al") == 1 and (r.get("stg") or {}).get("tb") == TB2 and r.get("why") for r in ar7), (o7[1], ar7))
os.makedirs(LARCH + ".d", exist_ok=True)
os.replace(LARCH, LARCH + ".d/keep") if os.path.isfile(LARCH) else None
os.makedirs(LARCH, exist_ok=True)
fresh()
(kL,) = setup_ll(w, [(W1, OLD, 1, {"v": 1, "tb": TB2, "al": 1}, 9, now() - 31 * DAY)])
AL_FAIL["n"] = 1
o7c = lcycle(w, kL)
AL_FAIL["n"] = 0
check("F7c al ≥ 1 잎도 보관 쓰기 실패 = 큐 유지(지우지 않음 · leaf_later_giveup 없음)", isinstance(o7c["e"], dict)
      and not any(n.get("kind") == "leaf_later_giveup" for n in w.cursor.get("_native_notes") or []), o7c)
os.rmdir(LARCH)
os.replace(LARCH + ".d/keep", LARCH) if os.path.isfile(LARCH + ".d/keep") else None
os.rmdir(LARCH + ".d")
lprep()
fresh(key=False)
(kL,) = setup_ll(w, [(W0, OLD - 3, 1, None, 8, now() - 31 * DAY)])
a0 = len(arch_rows(LARCH))
o7d = lcycle(w, kL)
check("F7d 키 없음 만료(종전처럼 뺌)도 전체 식별자 보관(전체 지갑·block)", lent(w, kL) is None and not o7d["trace"]
      and any(r.get("w") == W0 and r.get("blk") == OLD - 3 and r.get("why") for r in arch_rows(LARCH)[a0:]), (o7d, arch_rows(LARCH)[a0:]))
H7 = hx(0xF701)
fresh()
setup_tl(w, [(H7, OLD, 1, {"v": 1, "ct": NIDS, "pa": NIDS, "al": 1}, 8)])
w.cursor["_trace_later"][H7]["at"] = int(now() - 31 * DAY)
at7t = w.cursor["_trace_later"][H7]["at"]
a0 = len(arch_rows(TARCH))
o7e = tl_cycle(w)
ar7t = arch_rows(TARCH)[a0:]
check("F7e 늦은 채움 al 1 만료 = 전체 tx 해시·block·at·n·stg·사유 보관 뒤 뺌 · HTTP 0", ent(w, H7) is None and not o7e["trace"] and not o7e["al"]
      and any(r.get("chain") == "base" and r.get("h") == H7 and r.get("blk") == OLD and r.get("at") == at7t and r.get("n") == 8
              and (r.get("stg") or {}).get("al") == 1 and r.get("why") for r in ar7t), (o7e, ar7t))
os.makedirs(TARCH + ".d", exist_ok=True)
os.replace(TARCH, TARCH + ".d/keep") if os.path.isfile(TARCH) else None
os.makedirs(TARCH, exist_ok=True)
fresh()
setup_tl(w, [(H7, OLD, 1, {"v": 1, "ct": NIDS, "pa": NIDS, "al": 1}, 8)])
w.cursor["_trace_later"][H7]["at"] = int(now() - 31 * DAY)
try:
    o7f = tl_cycle(w)
except Exception as x9:  # noqa: BLE001
    o7f = {"exc": repr(x9)}
check("F7f 늦은 채움 보관 쓰기 실패 = 큐 유지(예외 없음 · 지우지 않음)", "exc" not in o7f and isinstance(ent(w, H7), dict), o7f)
os.rmdir(TARCH)
os.replace(TARCH + ".d/keep", TARCH) if os.path.isfile(TARCH + ".d/keep") else None
os.rmdir(TARCH + ".d")
w.cursor.pop("_trace_later", None)
w = mk()

lprep()
BLOCK_TRACE[OLD] = [{"txHash": HL, "result": {"type": "CALL", "from": X1, "to": RT, "value": "0x0",
                                              "calls": [{"type": "CALL", "from": RT, "to": W1, "value": "0x2a"}]}}]
PLAN.clear()
fresh()
(kL,) = setup_ll(w, [(W1, OLD, 1, {"v": 1, "tb": TB2, "al": 0}, 2, None)])
AL_FAIL["n"] = 99
o8 = []
for _i in range(3):
    o8.append(lcycle(w, kL))
    if lent(w, kL) is None:
        break
AL_FAIL["n"] = 0
r8 = lrecs(HL)
check("F8a ★6.3 재현★ 정상 trace · Alchemy 500 만 = 3차례 안에 trace 재확인으로 방출(+42 wei · W1) · 큐에서 뺌",
      lent(w, kL) is None and len(r8) == 1 and (r8[0].get("snapshot") or {}).get("internal") == ROWL,
      [(o["el"], o["al"], o["trace"], (o["e"] or {}).get("stg"), (o["e"] or {}).get("n")) for o in o8])
check("F8b 1차 = Alchemy 먼저(trace 0콜) · 재확인 차례 = trace 1콜만", o8 and o8[0]["al"] >= 1 and not o8[0]["trace"]
      and all(len(o["trace"]) <= 1 for o in o8), [(o["al"], o["trace"]) for o in o8])
BLOCK_TRACE.pop(OLD, None)
lprep()
PLAN.clear()
PLAN.update(LSLOW)
fresh()
(kL,) = setup_ll(w, [(W1, OLD, 1, {"v": 1, "tb": TB2, "al": 0}, 2, None)])
AL_FAIL["n"] = 99
o8c = []
for _i in range(5):
    with bf_engine._GATES_LOCK:
        bf_engine._GATES.clear()
    o8c.append(lcycle(w, kL))
AL_FAIL["n"] = 0
check("F8c trace·Alchemy 계속 실패 = 차례마다 trace ≤ 1콜(전 노드 재호출 없음) · 재확인은 한 차례 걸러 · 큐 유지 · 마감 ≤ 70초",
      all(len(o["trace"]) <= 1 for o in o8c) and sum(1 for o in o8c if o["trace"]) <= 3 and any(o["trace"] for o in o8c)
      and isinstance(lent(w, kL), dict) and all(o["el"] <= 70.0 for o in o8c),
      [(o["el"], o["al"], o["trace"], (o["e"] or {}).get("stg")) for o in o8c])
U8 = sorted((CN, DRPC), key=evm_watch.RpcChainWatcher._trace_nid)
BAD8, OK8 = U8[0].split("/")[2], U8[1].split("/")[2]
lprep()
BLOCK_TRACE[OLD] = [{"txHash": HL, "result": {"type": "CALL", "from": X1, "to": RT, "value": "0x0",
                                              "calls": [{"type": "CALL", "from": RT, "to": W1, "value": "0x2a"}]}}]
PLAN.clear()
PLAN.update({BAD8: ("408", 0.0)})
fresh()
(kL,) = setup_ll(w, [(W1, OLD, 1, {"v": 1, "tb": TB2, "al": 0}, 2, None)])
AL_FAIL["n"] = 99
o8d = []
for _i in range(6):
    with bf_engine._GATES_LOCK:
        bf_engine._GATES.clear()
    o8d.append(lcycle(w, kL))
    if lent(w, kL) is None:
        break
AL_FAIL["n"] = 0
BLOCK_TRACE.pop(OLD, None)
check("F8d 첫 노드 계속 고장 · 둘째 노드 회복 = 재확인이 노드를 돌아가며 유한 차례(≤ 4) 안에 둘째 노드로 방출 · 차례마다 trace ≤ 1콜",
      lent(w, kL) is None and len(lrecs(HL)) == 1 and len(o8d) <= 4 and all(len(o["trace"]) <= 1 for o in o8d)
      and any(hh == BAD8 for o in o8d for hh, _m in o["trace"]) and any(hh == OK8 for o in o8d for hh, _m in o["trace"]),
      [(o["el"], o["al"], o["trace"], (o["e"] or {}).get("stg")) for o in o8d])
w = mk()

TRACE42 = [{"txHash": HL, "result": {"type": "CALL", "from": X1, "to": RT, "value": "0x0",
                                     "calls": [{"type": "CALL", "from": RT, "to": W1, "value": "0x2a"}]}}]
BAD9, OK9 = U8[0].split("/")[2], U8[1].split("/")[2]


def restart():
    with bf_engine._GATES_LOCK:
        bf_engine._GATES.clear()
    AI._OFF["until"] = 0.0
    return mk()


def notes(w9, kind):
    return [x for x in (w9.cursor.get("_native_notes") or []) if x.get("kind") == kind]


def f9_turn2(w9, k, mode):
    PLAN.clear()
    PLAN.update({BAD9: ("hist" if mode == "hist" else "nm", 0.0)})
    AL_FAIL.update(n=99, code=401)
    if mode == "nokey":
        os.environ.pop(NK.ENV_ALCHEMY, None)
    if mode == "off":
        AI._OFF["until"] = now() + 3600
    if mode == "budget":
        AL_FAIL.update(n=0, code=500)
        g9 = bf_engine.gate(AHOST)
        g9.open_until, g9.open_count = bf_engine.time.time() + 100000, 2
    try:
        return lcycle(w9, k)
    finally:
        os.environ[NK.ENV_ALCHEMY] = AKEY
        AI._OFF["until"] = 0.0
        with bf_engine._GATES_LOCK:
            bf_engine._GATES.pop(AHOST, None)


def f9_fixture(mode):
    global w  # noqa: PLW0603
    lprep()
    BLOCK_TRACE[OLD] = copy.deepcopy(TRACE42)
    PLAN.clear()
    fresh()
    (k,) = setup_ll(w, [(W1, OLD, 1, {"v": 1, "tb": TB2, "al": 0}, 2, None)])
    AL_FAIL.update(n=1, code=500)
    o1 = lcycle(w, k)
    w = restart()
    o2 = f9_turn2(w, k, mode)
    PLAN.clear()
    PLAN.update({BAD9: ("nm", 0.0)})
    AL_FAIL.update(n=99, code=401)
    o3 = lcycle(w, k) if isinstance(lent(w, k), dict) else None
    AL_FAIL.update(n=0, code=500)
    BLOCK_TRACE.pop(OLD, None)
    return k, o1, o2, o3


def f9_ok(k, o1, o2, o3, tag):
    s1 = (o1["e"] or {}).get("stg") or {}
    check(f"F9{tag}-1 1차 = Alchemy 먼저 실제 500 1콜(trace 0콜) · rc 예약 · n 3", o1["al"] == 1 and not o1["trace"] and s1.get("rc") == 1
          and (o1["e"] or {}).get("n") == 3, o1)
    s2 = (o2["e"] or {}).get("stg") or {}
    check(f"F9{tag}-2 ★B1★ 재확인 = 첫 노드 1콜만(영구 실패) · 큐 유지 · leaf_later_unsupported 없음 · rc 다시 예약 · ri+1 · n+1 · 방출 0",
          o2["trace"] == [(BAD9, "debug_traceBlockByNumber")] and isinstance(o2["e"], dict) and not notes(w, "leaf_later_unsupported")
          and s2.get("rc") == 1 and s2.get("ri") == 1 and o2["e"].get("n") == 4 and o2["emit"] == 0, (o2, notes(w, "leaf_later_unsupported")))
    r9 = lrecs(HL)
    check(f"F9{tag}-3 다음 재확인 = 다른 정상 노드 1콜로 +42 wei(W1) 정확히 한 번 방출 · 큐에서 뺌",
          o3 is not None and o3["trace"] == [(OK9, "debug_traceBlockByNumber")] and len(r9) == 1
          and (r9[0].get("snapshot") or {}).get("internal") == ROWL and lent(w, k) is None and notes(w, "leaf_later_done"),
          (o3, [(r.get("repair"), (r.get("snapshot") or {}).get("internal")) for r in r9]))


k9, a1, a2, a3 = f9_fixture("401")
f9_ok(k9, a1, a2, a3, "a")
for md9, tg9 in (("nokey", "b"), ("off", "c"), ("hist", "d")):
    k9, a1, a2, a3 = f9_fixture(md9)
    f9_ok(k9, a1, a2, a3, tg9)
k9, a1, a2, a3 = f9_fixture("budget")
check("F9e Alchemy 0콜 거절 = 재확인 노드 1콜 · Alchemy HTTP 0 · 큐 유지(미지원 삭제 없음) · 다음 차례 방출 1",
      a2["trace"] == [(BAD9, "debug_traceBlockByNumber")] and not a2["al"] and isinstance(a2["e"], dict) and not notes(w, "leaf_later_unsupported")
      and a3 is not None and len(lrecs(HL)) == 1 and lent(w, k9) is None, (a2, a3))

lprep()
BLOCK_TRACE[OLD] = copy.deepcopy(TRACE42)
fresh()
w.cursor["_leaf_later"], w.cursor["_leaf_fail"], w.cursor["_native_notes"] = {}, {}, []
for k9 in ("_alch_memo", "_trace_slow_until", "_trace_sick_until", "_trace_nf"):
    w.__dict__.pop(k9, None)
WR.recs.clear()
w._leaf_retry(W1, OLD, False, c=OLD - 100, nk="_bkns")
statefile.atomic_write_json(w.cursor_path, w.cursor)
(kN,) = list(w.cursor["_leaf_later"])
atN = lent(w, kN)["at"]
adv(601.0)
PLAN.clear()
PLAN.update({HCN: ("408", 0.0), DH: ("408", 0.0)})
AL_FAIL.update(n=99, code=500)
oN = [lcycle(w, kN)]
with bf_engine._GATES_LOCK:
    bf_engine._GATES.clear()
oN.append(lcycle(w, kN))
w = restart()
sN = (lent(w, kN) or {}).get("stg") or {}
check("F9f 자연 생성 = 1차 trace 두 노드 실제 실패(tb 둘) · 2차 Alchemy 먼저 500(trace 0콜) · rc 예약 · n 2 · 큐 약 70분",
      len(oN[0]["trace"]) == 2 and not oN[1]["trace"] and sorted(sN.get("tb") or []) == TB2 and sN.get("rc") == 1
      and (lent(w, kN) or {}).get("n") == 2 and 60 * 60 <= now() - atN <= 80 * 60, (oN, lent(w, kN), round((now() - atN) / 60)))
PLAN.clear()
PLAN.update({BAD9: ("nm", 0.0)})
AL_FAIL.update(n=99, code=401)
oN.append(lcycle(w, kN))
oN.append(lcycle(w, kN) if isinstance(lent(w, kN), dict) else None)
AL_FAIL.update(n=0, code=500)
BLOCK_TRACE.pop(OLD, None)
check("F9g ★B1 자연 생성★ 첫 노드 미지원 + Alchemy 401 = 큐 유지 → 다음 재확인 다른 노드로 +42 wei 정확히 한 번 · 미지원 삭제 없음",
      oN[2]["trace"] == [(BAD9, "debug_traceBlockByNumber")] and isinstance(oN[2]["e"], dict) and oN[3] is not None
      and oN[3]["trace"] == [(OK9, "debug_traceBlockByNumber")] and len(lrecs(HL)) == 1 and lent(w, kN) is None
      and not notes(w, "leaf_later_unsupported"), (oN[2:], notes(w, "leaf_later_unsupported")))

lprep()
PLAN.clear()
fresh()
(kD,) = setup_ll(w, [(W1, OLD, 1, {"v": 1, "tb": TB2, "al": 0}, 2, None)])
AL_FAIL.update(n=1, code=500)
oD = [lcycle(w, kD)]
w = restart()
PLAN.update({HCN: ("nm", 0.0), DH: ("nm", 0.0)})
AL_FAIL.update(n=99, code=401)
for _i in range(4):
    oD.append(lcycle(w, kD))
check("F9h 두 노드 계속 미지원 = 재확인 차례마다 trace 1콜 · 두 노드 모두 물음 · 큐 유지 · 미지원 삭제 없음",
      all(len(o["trace"]) == 1 for o in oD[1:]) and {hh for o in oD[1:] for hh, _m in o["trace"]} == {HCN, DH}
      and isinstance(lent(w, kD), dict) and not notes(w, "leaf_later_unsupported"), [(o["trace"], (o["e"] or {}).get("stg")) for o in oD])
a0 = len(arch_rows(LARCH))
if isinstance(lent(w, kD), dict):
    lent(w, kD)["at"] = int(now() - 31 * DAY)
    oD.append(lcycle(w, kD))
AL_FAIL.update(n=0, code=500)
check("F9i 두 노드 계속 실패 · 31일 = 전체 식별자(chain·k·전체 지갑·block·stg·사유) 보관 뒤 만료(HTTP 0)",
      lent(w, kD) is None and not oD[-1]["trace"] and not oD[-1]["al"]
      and any(r.get("chain") == "base" and r.get("k") == kD and r.get("w") == W1 and r.get("blk") == OLD and r.get("why") for r in arch_rows(LARCH)[a0:]),
      (oD[-1], arch_rows(LARCH)[a0:]))

lprep()
PLAN.clear()
fresh()
w.trace_rpcs = [DRPC]
(kS,) = setup_ll(w, [(W1, OLD, 1, {"v": 1, "tb": [evm_watch.RpcChainWatcher._trace_nid(DRPC)], "al": 0}, 2, None)])
AL_FAIL.update(n=1, code=500)
oS = [lcycle(w, kS)]
w = restart()
w.trace_rpcs = [DRPC]
PLAN.update({DH: ("nm", 0.0)})
AL_FAIL.update(n=99, code=401)
oS.append(lcycle(w, kS))
AL_FAIL.update(n=0, code=500)
check("F9j 단일 trace 노드 구성 = 종전대로 미지원 확정(leaf_later_unsupported · 큐에서 뺌) · 재확인 1콜",
      (oS[0]["e"] or {}).get("stg", {}).get("rc") == 1 and oS[1]["trace"] == [(DH, "debug_traceBlockByNumber")] and lent(w, kS) is None
      and notes(w, "leaf_later_unsupported"), oS)
w = mk()

check("Z1 키 값이 기록·커서에 없음", AKEY not in json.dumps(w.cursor, ensure_ascii=False) and AKEY not in json.dumps(WR.recs, ensure_ascii=False))
check("Z2 바깥 연결 시도 0", not T.NET_TRIES, T.NET_TRIES)
evm_watch.time = _RT
T.patch_moved("time", evm_watch.time, ("evm_",))
bf_engine.time = _RT
AI.time = _RT
T.finish()
