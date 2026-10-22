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
PLAN = {}
AL_PAGES = {}
AL_DELAY = {"s": 0.3}
AL_HOOK = {"open_after": None}
RECEIPTS = {}
RCPT_DELAY = {"s": 0.05}
HITS = []


def fake_open(req, timeout):
    h = req.host.split(":")[0].lower()
    body = json.loads(req.data.decode()) if req.data else {}
    if isinstance(body, list):
        HITS.append((h, "batch:" + ",".join(sorted({str(x.get("method")) for x in body}))))
        d9 = float(timeout) if RCPT_DELAY["s"] == "rest" else float(RCPT_DELAY["s"])
        adv(min(d9, float(timeout)))
        if RCPT_DELAY["s"] == "rest":
            raise bf_engine.NetError("timed out", "timeout")
        return _Resp([{"jsonrpc": "2.0", "id": x["id"], "result": RECEIPTS.get(x["params"][0]) if x.get("method") == "eth_getTransactionReceipt" else None}
                      for x in body])
    m = body.get("method")
    HITS.append((h, m))
    if h == AHOST:
        adv(AL_DELAY["s"])
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
    if kind == "408":
        raise urllib.error.HTTPError(req.full_url, 408, "Request Timeout", {}, io.BytesIO(b'{"message":"Request timeout on the free plan"}'))
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
    return {h: {"tx": {"hash": h, "block_number": BLK.get(h, OLD), "from": W0, "to": RT, "status": "ok", "synth": "rpc"}, "token_transfers": [], "internal": []}
            for h in hs}


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

H1 = hx(0x5101)
AL_PAGES[OLD] = [{"transfers": [atr(H1, RT, W0, "0x2a", "0_1", OLD)]}]
RECEIPTS[H1] = {"blockNumber": hex(OLD), "status": "0x1", "transactionHash": H1}
PLAN.clear()
PLAN.update(SLOW)
fresh()
w = mk()
setup(w, H1)
obs = []
for _i in range(8):
    obs.append(cycle(w, H1))
    if ent(w, H1) is None:
        break
tot_al = sum(o["al"] for o in obs)
f1 = fills(H1)
check("S1a ★R4 재현★ 지연 408(drpc 남은 ~29.5초) + Chainnodes pruned · 60일 전 = 8사이클 안에 Alchemy 보완(1콜) · int_fill +42 wei 1건 · 큐에서 뺌",
      tot_al == 1 and len(f1) == 1 and (f1[0].get("snapshot") or {}).get("internal") == ROW42 and ent(w, H1) is None,
      [(o["el"], o["al"], o["emit"], (o["e"] or {}).get("n"), (o["e"] or {}).get("stg")) for o in obs])
check("S1b 사이클마다 절대 마감 안(첫 1건 30초 + Alchemy·영수증 몫 ≤ 31초) — 최신 수집을 붙잡지 않음",
      all(o["el"] <= 31.0 for o in obs), [o["el"] for o in obs])
m1 = [sorted({m for _h, m in o["trace"]}) for o in obs]
check("S1c 단계가 이어짐: 1차 callTracer(두 노드 실제 실패) → 2차 parity(두 노드 실제 실패) → 3차 Alchemy 먼저(trace 0콜)",
      len(obs) == 3 and m1[0] == ["debug_traceTransaction"] and m1[1] == ["trace_transaction"] and m1[2] == [] and obs[2]["al"] == 1
      and len(obs[0]["trace"]) == 2 and len(obs[1]["trace"]) == 2, (m1, [o["trace"] for o in obs]))
check("S1d 시도 횟수 n = 실제 실패한 차례만(1 → 2) · 단계는 n 이 아니라 stg(callTracer·parity 노드 지문)",
      len(obs) >= 2 and (obs[0]["e"] or {}).get("n") == 1 and (obs[1]["e"] or {}).get("n") == 2
      and len(((obs[0]["e"] or {}).get("stg") or {}).get("ct") or []) == 2 and not ((obs[0]["e"] or {}).get("stg") or {}).get("pa")
      and len(((obs[1]["e"] or {}).get("stg") or {}).get("pa") or []) == 2, [o["e"] for o in obs])
stg_txt = json.dumps([o["e"] for o in obs])
check("S1e 단계 기록에 비밀 URL·키 없음(노드 지문만)", "0a1b2c3d" not in stg_txt and "chainnodes" not in stg_txt and AKEY not in stg_txt, stg_txt[:300])
FINAL_S1 = [(r.get("repair"), (r.get("snapshot") or {}).get("internal"), (r.get("snapshot") or {}).get("internal_src")) for r in f1]

H2 = H1
PLAN.clear()
PLAN.update(FAST)
fresh()
setup(w, H2)
o2 = cycle(w, H2)
f2 = fills(H2)
check("S2a 대조군(오류 즉시) = 첫 사이클 Alchemy 1콜 · int_fill 1건 · 큐에서 뺌", o2["al"] == 1 and len(f2) == 1 and ent(w, H2) is None, o2)
FINAL_S2 = [(r.get("repair"), (r.get("snapshot") or {}).get("internal"), (r.get("snapshot") or {}).get("internal_src")) for r in f2]
check("S2b 지연군과 대조군의 최종 원장(int_fill 기록) 같음", FINAL_S1 == FINAL_S2 and FINAL_S1, (FINAL_S1, FINAL_S2))

H3 = hx(0x5301)
AL_PAGES[OLD] = [{"transfers": [atr(H3, RT, W0, "0x2a", "0_1", OLD)]}]
RECEIPTS[H3] = {"blockNumber": hex(OLD), "status": "0x1", "transactionHash": H3}
PLAN.clear()
PLAN.update(SLOW)
fresh()
setup(w, H3, at=now() - 31 * DAY, n=8)
o3 = [cycle(w, H3)]
check("S3a 30일·8회 넘었어도 Alchemy 를 실제로 못 물은 항목 = 지우지 않음(trace 시도 · giveup 없음)",
      isinstance(o3[0]["e"], dict) and o3[0]["trace"] and not any(n.get("kind") == "trace_later_giveup" for n in w.cursor.get("_native_notes") or []),
      (o3, w.cursor.get("_native_notes")))
for _i in range(4):
    if ent(w, H3) is None:
        break
    o3.append(cycle(w, H3))
check("S3b 그 항목이 이어서 단계 → Alchemy 보완 · int_fill 1건", len(fills(H3)) == 1 and ent(w, H3) is None and sum(o["al"] for o in o3) == 1,
      [(o["al"], o["emit"], o["e"]) for o in o3])
H3b = hx(0x5302)
fresh()
setup(w, H3b, at=now() - 61 * DAY, n=9)
o9 = cycle(w, H3b)
arch = os.path.join(paths.STATE_DIR, "trace_later_unresolved_base.jsonl")
rows9 = []
if os.path.exists(arch):
    with open(arch, encoding="utf-8") as f:
        rows9 = [json.loads(x) for x in f if x.strip()]
check("S3c 2×TTL(60일) 넘도록 Alchemy 0회 = 큐에서 빼되 전체 해시·이유로 보관(archived_unresolved) · HTTP 0",
      ent(w, H3b) is None and any(r.get("h") == H3b and r.get("blk") == OLD and r.get("why") for r in rows9) and not o9["trace"] and not o9["al"],
      (o9, rows9))
fresh(key=False)
H3c = hx(0x5303)
setup(w, H3c, at=now() - 31 * DAY, n=8)
o9 = cycle(w, H3c)
check("S3d 키 없음 = 종전 만료(30일·5회 → trace_later_giveup · HTTP 0)", ent(w, H3c) is None and not o9["trace"] and not o9["al"]
      and any(n.get("kind") == "trace_later_giveup" for n in w.cursor.get("_native_notes") or []), (o9, w.cursor.get("_native_notes")))
fresh()
H3d = hx(0x5304)
setup(w, H3d, at=now() - 31 * DAY, n=8, stg={"v": 1, "ct": [], "pa": [], "al": 1})
o9 = cycle(w, H3d)
check("S3e 이미 Alchemy 를 실제로 물어 본 항목(al ≥ 1) = 종전 만료", ent(w, H3d) is None and not o9["trace"]
      and any(n.get("kind") == "trace_later_giveup" for n in w.cursor.get("_native_notes") or []), o9)

H4 = hx(0x5401)
AL_PAGES[OLD] = [{"transfers": [atr(H4, RT, W0, "0x2a", "0_1", OLD)]}]
RECEIPTS[H4] = {"blockNumber": hex(OLD), "status": "0x1", "transactionHash": H4}


def _open_gate(host):
    g9 = bf_engine.gate(host)
    g9.open_until, g9.open_count = bf_engine.time.time() + 100000, 2


fresh()
_open_gate(HCN)
_open_gate(DH)
setup(w, H4)
o4 = cycle(w, H4)
check("S4a 모든 trace 노드 서킷(0콜) = 큐 유지 · n 그대로 · 단계 기록 없음 · Alchemy 0콜(허위 자격 없음) · 방출 0",
      isinstance(o4["e"], dict) and o4["e"].get("n") == 0 and not (o4["e"].get("stg") or {}).get("ct") and not (o4["e"].get("stg") or {}).get("pa")
      and not o4["trace"] and not o4["al"] and not WR.recs, o4)
NIDS = sorted(w._trace_nid(u) for u in (CN, DRPC)) if hasattr(w, "_trace_nid") else []
fresh()
_open_gate(HCN)
_open_gate(DH)
setup(w, H4, n=1, stg={"v": 1, "ct": NIDS, "pa": [], "al": 0})
o4 = cycle(w, H4)
check("S4b callTracer 단계 완료 · parity 차례에 모든 노드 서킷 = 단계·n 그대로(parity 를 실패로 안 만듦) · Alchemy 0콜",
      isinstance(o4["e"], dict) and o4["e"].get("n") == 1 and (o4["e"].get("stg") or {}).get("ct") == NIDS and not (o4["e"].get("stg") or {}).get("pa")
      and not o4["al"] and not WR.recs, o4)
fresh()
_open_gate(AHOST)
setup(w, H4, n=2, stg={"v": 1, "ct": NIDS, "pa": NIDS, "al": 0})
o4 = cycle(w, H4)
check("S4c Alchemy 차례 · Alchemy 서킷(0콜) = 큐 유지 · Alchemy HTTP 0 · 방출 0 · 단계 기록 유지 · 실제 시도 수(al) 안 올림",
      isinstance(o4["e"], dict) and not o4["al"] and not WR.recs and (o4["e"].get("stg") or {}).get("pa") == NIDS and not (o4["e"].get("stg") or {}).get("al"), o4)
fresh()
e9 = ent(w, H4)
if isinstance(e9, dict):
    e9["next"] = int(now()) - 1
o4 = cycle(w, H4)
check("S4d 서킷이 닫힌 다음 차례 = 보완 1회 방출 · 큐에서 뺌", o4["al"] == 1 and len(fills(H4)) == 1 and ent(w, H4) is None, o4)

H5 = hx(0x5501)
AL_PAGES[OLD] = [{"transfers": [atr(H5, RT, W0, "0x2a", "0_1", OLD)], "pageKey": "pk-1"}, {"transfers": [atr(H5, RT, W0, "0x2b", "0_2", OLD)]}]
RECEIPTS[H5] = {"blockNumber": hex(OLD), "status": "0x1", "transactionHash": H5}
fresh()
AL_HOOK["open_after"] = 0
setup(w, H5, n=2, stg={"v": 1, "ct": NIDS, "pa": NIDS, "al": 0})
o5 = cycle(w, H5)
AL_HOOK["open_after"] = None
check("S5a 둘째 쪽 0콜 거절 = 부분 방출 0 · 큐 유지 · 단계 기록 유지", o5["al"] == 1 and not WR.recs and isinstance(o5["e"], dict)
      and (o5["e"].get("stg") or {}).get("pa") == NIDS, o5)
fresh()
e9 = ent(w, H5)
if isinstance(e9, dict):
    e9["next"] = int(now()) - 1
w.__dict__.pop("_alch_memo", None)
o5 = cycle(w, H5)
f5 = fills(H5)
check("S5b 다음 차례 두 쪽 완료 = 한 번만 방출(두 행)", len(f5) == 1 and len((f5[0].get("snapshot") or {}).get("internal") or []) == 2 and ent(w, H5) is None, (o5, f5))
H5b = hx(0x5502)
AL_PAGES[OLD] = [{"transfers": [atr(H5b, RT, W0, "0x2a", "0_1", OLD)]}]
RECEIPTS[H5b] = {"blockNumber": hex(OLD), "status": "0x1", "transactionHash": H5b}
fresh()
RCPT_DELAY["s"] = "rest"
cfg0 = list(w.cfg_rpcs)
w.cfg_rpcs = ["http://127.0.0.1:9/r1", "http://127.0.0.1:9/r2"]
setup(w, H5b, n=2, stg={"v": 1, "ct": NIDS, "pa": NIDS, "al": 0})
o5 = cycle(w, H5b)
RCPT_DELAY["s"] = 0.05
w.cfg_rpcs = cfg0
check("S5c 영수증 마감(노드 응답 없음) = 부분 방출 0 · Alchemy 0콜 · n 그대로(미시도) · 큐 유지",
      not o5["al"] and not WR.recs and isinstance(o5["e"], dict) and o5["e"].get("n") == 2, o5)
fresh()
e9 = ent(w, H5b)
if isinstance(e9, dict):
    e9["next"] = int(now()) - 1
o5 = cycle(w, H5b)
check("S5d 다음 차례 = 한 번만 방출", len(fills(H5b)) == 1 and ent(w, H5b) is None and o5["al"] == 1, o5)

H6 = hx(0x5601)
PLAN.clear()
fresh()
setup(w, H6)
o6 = cycle(w, H6)
f6 = fills(H6)
check("S6a 정상 trace 성공 = Alchemy 0콜 · trace 결과로 방출(출처 표식 없음)", not o6["al"] and len(f6) == 1 and (f6[0].get("snapshot") or {}).get("internal") == ROW42
      and not (f6[0].get("snapshot") or {}).get("internal_src"), (o6, f6))
PLAN.clear()
PLAN.update({HCN: ("gap", 0.0), DH: ("ok", 0.0)})
fresh()
setup(w, H6, n=1, stg={"v": 1, "ct": NIDS, "pa": [], "al": 0})
WR.recs.clear()
o6 = cycle(w, H6)
f6 = fills(H6)
check("S6b callTracer 단계 완료 뒤 parity 차례에 parity 가 됨 = trace 결과(Alchemy 0콜)", not o6["al"] and len(f6) == 1
      and [m for _h, m in o6["trace"]] == ["trace_transaction", "trace_transaction"] and not (f6[0].get("snapshot") or {}).get("internal_src"), (o6, f6))

H7 = hx(0x5701)
PLAN.clear()
PLAN.update(FAST)
fresh(key=False)
setup(w, H7, n=2, stg={"v": 1, "ct": NIDS, "pa": NIDS, "al": 0})
o7 = cycle(w, H7)
check("S7a 키 없음 · 단계 완료 = 종전 trace 경로(Alchemy 0콜 · trace 다시 · 큐 유지 · n +1)",
      not o7["al"] and o7["trace"] and isinstance(o7["e"], dict) and o7["e"].get("n") == 3 and not WR.recs, o7)
H7b = hx(0x5702)
fresh()
setup(w, H7b, blk=RECENT, at=now() - 120, n=2, stg={"v": 1, "ct": NIDS, "pa": NIDS, "al": 0})
o7 = cycle(w, H7b)
check("S7b 최근 블록(1시간 안) · 단계 완료 = 종전(Alchemy 0콜 · trace 다시)", not o7["al"] and o7["trace"] and isinstance(o7["e"], dict), o7)

H8 = hx(0x5801)
BIG = 2 ** 53 + 1
AL_PAGES[OLD] = [{"transfers": [atr(H8, RT, W0, hex(BIG), "0_1", OLD), atr(H8, W0, RT, "0x1", "0_2", OLD),
                                atr(H8, RT, W1, "0x7", "0_3", OLD), atr(H8, RT, W1, "0x7", "0_4", OLD)]}]
RECEIPTS[H8] = {"blockNumber": hex(OLD), "status": "0x1", "transactionHash": H8}
PLAN.clear()
PLAN.update(SLOW)
fresh()
setup(w, H8, n=2, stg={"v": 1, "ct": NIDS, "pa": NIDS, "al": 0})
o8 = cycle(w, H8)
f8 = fills(H8)
check("S8 2^53 초과·1 wei·같은 내용 두 행 = 10진 문자열 그대로 · 네 행", len(f8) == 1 and (f8[0].get("snapshot") or {}).get("internal") == [
    {"from": RT, "to": W0, "value": str(BIG), "success": True}, {"from": W0, "to": RT, "value": "1", "success": True},
    {"from": RT, "to": W1, "value": "7", "success": True}, {"from": RT, "to": W1, "value": "7", "success": True}], (o8, f8))

H9 = hx(0x5901)
AL_PAGES[OLD] = [{"transfers": [atr(H9, RT, W0, "0x2a", "0_1", OLD)]}]
RECEIPTS[H9] = {"blockNumber": hex(OLD), "status": "0x1", "transactionHash": H9}
fresh()
setup(w, H9)
o9 = [cycle(w, H9)]
w2 = mk()
e9 = ent(w2, H9)
check("S9a 첫 사이클 뒤 디스크 커서에 단계 기록(stg v1 · callTracer 노드 2) · 옛 칸(at·n·next·blk·sent) 형식 그대로(옛 코드가 읽음)",
      isinstance(e9, dict) and (e9.get("stg") or {}).get("v") == 1 and len((e9.get("stg") or {}).get("ct") or []) == 2
      and all(isinstance(e9.get(k), int) for k in ("at", "n", "next", "blk")) and isinstance(e9.get("sent"), bool), e9)
for _i in range(3):
    if ent(w2, H9) is None:
        break
    o9.append(cycle(w2, H9))
check("S9b 재시작 뒤에도 이어서 parity → Alchemy(총 3차례 · Alchemy 1콜 · 한 번만 방출)", len(o9) == 3 and sum(o["al"] for o in o9) == 1
      and len(fills(H9)) == 1 and ent(w2, H9) is None, [(o["al"], o["trace"], o["e"]) for o in o9])
w = w2
H9b = hx(0x5902)
PLAN.clear()
PLAN.update(FAST)
fresh()
setup(w, H9b, n=1)
o9 = cycle(w, H9b)
AL_PAGES[OLD] = [{"transfers": []}]
check("S9c 옛 레코드(stg 없음) = 종전 교대(n 홀수 → parity 먼저)", o9["trace"][:1] and o9["trace"][0][1] == "trace_transaction", o9)
for bad in ("garbage", {"v": 99, "ct": NIDS, "pa": NIDS}, {"v": 1, "ct": "x", "pa": 5}):
    fresh()
    setup(w, H9b, n=0, stg=bad)
    o9 = cycle(w, H9b)
    check(f"S9d 깨진·모르는 stg({str(bad)[:20]}) = 기본값(종전 교대 · Alchemy 먼저 아님)", o9["trace"][:1] and o9["trace"][0][1] == "debug_traceTransaction", o9)

H10 = hx(0x5a01)
AL_PAGES[OLD] = [{"transfers": [atr(H10, RT, W0, "0x2a", "0_1", OLD)]}]
RECEIPTS[H10] = {"blockNumber": hex(OLD), "status": "0x1", "transactionHash": H10}
PLAN.clear()
PLAN.update({HCN: ("408", "rest"), DH: ("408", "rest")})
fresh()
setup(w, H10)
o10 = []
for _i in range(8):
    o10.append(cycle(w, H10))
    if ent(w, H10) is None:
        break
check("S10 두 노드 모두 남은 시간을 다 쓰는 408 = 실패한 노드는 다음 차례 뒤로 → 유한 차례(≤ 5) 안에 두 단계 완료 → Alchemy 보완 1건",
      len(fills(H10)) == 1 and ent(w, H10) is None and len(o10) <= 5 and sum(o["al"] for o in o10) == 1 and all(o["el"] <= 31.0 for o in o10),
      [(o["el"], o["trace"], (o["e"] or {}).get("stg")) for o in o10])

H11 = hx(0x5b01)
AL_PAGES[OLD] = [{"transfers": [atr(H11, RT, W0, "0x2a", "0_1", OLD)]}]
PLAN.clear()
PLAN.update(SLOW)
fresh()
setup(w, H11)
w.cursor.pop("_trace_later", None)
w.cursor["_hq"] = {H11: 0}
w.__dict__.pop("_hq_stg", None)
w.__dict__.pop("_hq_try", None)
o11 = []
for _i in range(8):
    t0, k0 = now(), len(HITS)
    w._hq_step(HEAD, now() + 5)
    o11.append((round(now() - t0, 2), len(al_hits(HITS[k0:])), sorted({m for _h, m in tr_hits(HITS[k0:])})))
    adv(601)
    if H11 not in (w.cursor.get("_hq") or {}):
        break
check("S11 ★R4★ 인계 큐도 같은 지연 408 = callTracer → parity → Alchemy 먼저(3차례 · Alchemy 1콜) · int_fill 1건 · 큐에서 뺌 · 차례마다 ≤ 31초",
      len(fills(H11)) == 1 and H11 not in (w.cursor.get("_hq") or {}) and len(o11) == 3 and sum(x[1] for x in o11) == 1 and all(x[0] <= 31.0 for x in o11), o11)
w.cursor.pop("_hq", None)

check("Z1 키 값이 기록·커서·보관 파일에 없음", AKEY not in json.dumps(w.cursor, ensure_ascii=False) and AKEY not in json.dumps(WR.recs, ensure_ascii=False)
      and AKEY not in json.dumps(rows9))
check("Z2 바깥 연결 시도 0", not T.NET_TRIES, T.NET_TRIES)
evm_watch.time = _RT
T.patch_moved("time", evm_watch.time, ("evm_",))
bf_engine.time = _RT
AI.time = _RT
T.finish()
