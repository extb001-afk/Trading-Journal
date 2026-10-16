#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import copy
import io
import json
import os
import urllib.error

W0 = "0x" + "e0" * 20
W1 = "0x" + "e1" * 20
RT = "0x" + "55" * 20
OT = "0x" + "66" * 20
CFG = {"backfill_months": 0,
       "chains": {"base": {"discovery": "rpc", "chain_id": 8453, "rpcs": ["http://127.0.0.1:9/rpc"], "conf_depth": 10, "blocks_per_day": 43200,
                           "rpc_log_span_caps": {"http://127.0.0.1:9/rpc": 5000}}},
       "wallets": [{"type": "evm", "chain": "base", "address": W0, "label": "w0"}, {"type": "evm", "chain": "base", "address": W1, "label": "w1"}]}
CP = os.path.join(T.TMP, "config.json")
with open(CP, "w", encoding="utf-8") as f:
    json.dump(CFG, f)
os.environ["TJ_CONFIG"] = CP
import common

assert T.TMP in common.STATE_DIR and T.TMP in common.ENV_PATH
import alch_internal as AI
import bf_engine
import core
import evm_watch
import nodekeys as NK


def check(n, c, d=""):
    T.chk(bool(c), n, None if c else str(d)[:900])


AKEY = "TESTalchKEY000000000000001"
AHOST = "base-mainnet.g.alchemy.com"
CN = "https://base-mainnet.chainnodes.org/0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
HCN = "base-mainnet.chainnodes.org"
DRPC = evm_watch.RpcChainWatcher.TRACE_DEFAULT["base"][0]
DH = DRPC.split("/")[2]
HEAD = 50_000_000
BPD = 43200
OLD = HEAD - 60 * BPD
YOUNG = HEAD - 2 * 3600 // 2
RECENT = HEAD - 100


def hx(n):
    return "0x" + f"{n:064x}"


def tr(h, frm, to, raw, path, blk, dec="0x12", addr=None, value=None):
    return {"blockNum": hex(blk), "uniqueId": f"{h}:internal:{path}", "hash": h, "from": frm, "to": to,
            "value": value if value is not None else 1.0e-18, "erc721TokenId": None, "erc1155Metadata": None, "tokenId": None,
            "asset": "ETH", "category": "internal", "rawContract": {"value": raw, "address": addr, "decimal": dec}, "metadata": None}


SCRIPT = {}
AL_PAGES = {}
RECEIPTS = {}
HITS = []


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


GONE = {"code": -32000, "message": "required historical state unavailable (reexec=0)"}
GAP = {"code": -32603, "message": "transaction not found", "data": {"code": "ErrUpstreamsExhausted"}}
RL = {"code": -32005, "message": "rate-limit exceeded", "data": {"code": "ErrProjectRateLimitRuleExceeded"}}


def _alchemy(body):
    prm = (body.get("params") or [{}])[0]
    b0 = int(prm["fromBlock"], 16)
    pages = AL_PAGES.get(b0)
    if pages is None:
        return _Resp({"jsonrpc": "2.0", "id": 1, "result": {"transfers": []}})
    pk = prm.get("pageKey")
    i9 = 0 if not pk else int(str(pk).split("-")[-1])
    act = pages[min(i9, len(pages) - 1)]
    if isinstance(act, tuple) and act[0] == "http":
        raise urllib.error.HTTPError("https://" + AHOST + "/v2/x", act[1], "x", {}, io.BytesIO(act[2].encode()))
    if isinstance(act, tuple) and act[0] == "rpcerr":
        return _Resp({"jsonrpc": "2.0", "id": 1, "error": act[1]})
    return _Resp({"jsonrpc": "2.0", "id": 1, "result": act})


def fake_open(req, timeout):
    h = req.host.split(":")[0].lower()
    body = json.loads(req.data.decode()) if req.data else {}
    if isinstance(body, list):
        HITS.append((h, "batch:" + ",".join(sorted({str(x.get("method")) for x in body}))))
        out = []
        for x in body:
            if x.get("method") == "eth_getTransactionReceipt":
                out.append({"jsonrpc": "2.0", "id": x["id"], "result": RECEIPTS.get(x["params"][0])})
            else:
                out.append({"jsonrpc": "2.0", "id": x["id"], "result": None})
        return _Resp(out)
    HITS.append((h, body.get("method")))
    if h == AHOST:
        return _alchemy(body)
    act = SCRIPT.get(h, ("ok", 0x10))
    if act[0] == "http":
        raise urllib.error.HTTPError(req.full_url, act[1], "x", {}, io.BytesIO(act[2].encode()))
    if act[0] == "rpcerr":
        return _Resp({"jsonrpc": "2.0", "id": 1, "error": act[1]})
    m = body.get("method")
    if m == "eth_getTransactionReceipt":
        return _Resp({"jsonrpc": "2.0", "id": 1, "result": RECEIPTS.get(body["params"][0])})
    if m == "debug_traceBlockByNumber":
        return _Resp({"jsonrpc": "2.0", "id": 1, "result": []})
    if m == "trace_transaction":
        return _Resp({"jsonrpc": "2.0", "id": 1, "result": [{"type": "call", "traceAddress": [], "action": {"from": W0, "to": RT, "value": "0x0", "callType": "call"}},
                                                             {"type": "call", "traceAddress": [0], "action": {"from": RT, "to": W0, "value": hex(act[1]), "callType": "call"}}]})
    return _Resp({"jsonrpc": "2.0", "id": 1, "result": {"type": "CALL", "from": W0, "to": RT, "value": "0x0",
                                                        "calls": [{"type": "CALL", "from": RT, "to": W0, "value": hex(act[1])}]}})


bf_engine._open = fake_open


def fresh():
    with bf_engine._GATES_LOCK:
        bf_engine._GATES.clear()
    AI._OFF["until"] = 0.0
    HITS.clear()


def al_hits():
    return [m for h, m in HITS if h == AHOST]


H1, H2, H3 = hx(0xa1), hx(0xa2), hx(0xa3)
L = [AI.norm(t) for t in (
    tr(H1, RT, W0, "0x1fd23bccdb3b7d", "3_0", OLD, value=0.008956878559853438),
    tr(H1, RT, W0, "0x05", "1", OLD),
    tr(H1, W0, RT, "0x07", "2_1", OLD),
    tr(H1, RT, OT, "0x09", "4", OLD),
    tr(H2, RT, W1, "0x0", "0", OLD),
    tr(H3, RT, W0, "0x11", "", OLD))]
R = AI.rows_for(L, {W0, W1})
check("L1a 원시값 그대로(0x1fd23bccdb3b7d = 8956878559853437 — 부동소수 value 아님)",
      R.get(H1) and R[H1][-1]["value"] == str(0x1fd23bccdb3b7d) and str(0x1fd23bccdb3b7d) == "8956878559853437", R)
check("L1b trace 경로순(1 → 2_1 → 3_0) · 남의 행·0 값·루트 제외 · 행 모양 = trace 파서와 같음",
      [r["value"] for r in R.get(H1, [])] == ["5", "7", "8956878559853437"] and H2 not in R and H3 not in R
      and all(set(r) == {"from", "to", "value", "success"} and r["success"] is True for r in R[H1]), R)
try:
    AI.rows_for([AI.norm(tr(H1, RT, W0, None, "1", OLD))], {W0})
    e9 = None
except AI.AlchFail as e:
    e9 = e
check("L1c 내 지갑 행 원시값 없음 = 정밀도 미확인(실패)", isinstance(e9, AI.AlchFail) and e9.kind == "precision", repr(e9))
try:
    AI.rows_for([AI.norm(tr(H1, RT, W0, "0x05", "1", OLD, dec="0x6"))], {W0})
    e9 = None
except AI.AlchFail as e:
    e9 = e
check("L1d decimal 18 아님 = 정밀도 미확인(실패)", isinstance(e9, AI.AlchFail) and e9.kind == "precision", repr(e9))
check("L1e 남의 행의 원시값 없음은 상관없음", AI.rows_for([AI.norm(tr(H1, RT, OT, None, "1", OLD))], {W0}) == {})
for bad, why in ((tr(H1, RT, W0, "0x05", "1", OLD, addr="0x" + "ab" * 20), "네이티브 아님"),
                 (dict(tr(H1, RT, W0, "0x05", "1", OLD), hash="0x12"), "hash 형식"),
                 (dict(tr(H1, RT, W0, "0x05", "1", OLD), uniqueId=None), "uniqueId 없음"),
                 (dict(tr(H1, RT, W0, "0x05", "1", OLD), category="external"), "분류 다름")):
    try:
        AI.norm(bad)
        e9 = None
    except AI.AlchFail as e:
        e9 = e
    check(f"L1f 형식 이상({why}) = 실패", isinstance(e9, AI.AlchFail) and e9.kind == "payload", repr(e9))
check("L1g 실패 문구에 원문 오류 없음(trace '영영 못 줌' 판정에 안 걸림)",
      not evm_watch.RpcChainWatcher._trace_gone(AI.AlchFail("http4xx", "method not found historical state unavailable")))

URL = "https://" + AHOST + "/v2/" + AKEY
B = OLD + 7
p1 = {"transfers": [tr(H1, RT, W0, "0x01", "1", B), tr(H1, RT, W0, "0x01", "2", B)], "pageKey": "pk-1"}
p2 = {"transfers": [tr(H2, RT, W0, "0x02", "1", B)], "pageKey": "pk-2"}
p3 = {"transfers": [tr(H3, RT, W1, "0x03", "1", B)]}
AL_PAGES[B] = [p1, p2, p3]
fresh()
trs, info = AI.fetch_range(URL, B, B)
check("L2a pageKey 끝까지(3쪽) · 한 tx 같은 값 두 이동(uniqueId 다름) 둘 다", len(trs) == 4 and info["pages"] == 3 and len(al_hits()) == 3
      and len(AI.rows_for(trs, {W0, W1})[H1]) == 2, (len(trs), info))
AL_PAGES[B] = [p1, dict(p1, pageKey="pk-2"), p2, p3]
p2b = {"transfers": [tr(H2, RT, W0, "0x02", "1", B)], "pageKey": "pk-3"}
AL_PAGES[B] = [p1, dict(p1, pageKey="pk-2"), p2b, p3]
fresh()
trs, info = AI.fetch_range(URL, B, B)
check("L2b 만료·무효 pageKey(첫 쪽부터 다시) = uniqueId 로 중복 버리고 이어 감 · 처음부터 다시 1",
      len(trs) == 4 and info["restarts"] == 1 and len({t["uid"] for t in trs}) == 4, (len(trs), info))
AL_PAGES[B] = [dict(p1, pageKey="pk-1")]
fresh()
try:
    AI.fetch_range(URL, B, B, max_pages=5)
    e9 = None
except AI.AlchFail as e:
    e9 = e
check("L2c 쪽 상한 넘김 = 미완료(실패 · 부분 결과 안 돌려줌)", isinstance(e9, AI.AlchFail) and e9.kind == "partial" and len(al_hits()) == 5, (repr(e9), len(al_hits())))
for pages, why, kind in (([{"pageKey": None}], "transfers 없음", "payload"),
                         ([{"transfers": [tr(H1, RT, W0, "0x01", "1", B + 1)]}], "범위 밖 블록", "payload"),
                         ([("rpcerr", {"code": -32602, "message": "invalid params"})], "JSON-RPC 오류", None),
                         ([("http", 500, "oops")], "HTTP 500", None),
                         ([p1, ("http", 503, "x")], "둘째 쪽 실패", None)):
    AL_PAGES[B] = pages
    fresh()
    try:
        AI.fetch_range(URL, B, B)
        e9 = None
    except Exception as e:
        e9 = e
    check(f"L2d {why} = 실패(일시 · 부분 결과 없음)", isinstance(e9, AI.AlchFail) and (kind is None or e9.kind == kind)
          and not evm_watch.RpcChainWatcher._trace_gone(e9), repr(e9))
AL_PAGES[B] = [("http", 401, '{"error":"Must be authenticated!"}')]
fresh()
os.environ[NK.ENV_ALCHEMY] = AKEY
try:
    AI.fetch_range(URL, B, B)
    e9 = None
except Exception as e:
    e9 = e
check("L2e 401 = 보완 안 함(AlchSkip) + 1시간 쉼(그동안 url_for = None)", isinstance(e9, AI.AlchSkip) and AI.off_now() and AI.url_for("base") is None, (repr(e9), AI._OFF))
AI._OFF["until"] = 0.0
check("L2f 키 있음·장부 있음 = 주소(메모리) · 지원 안 하는 체인 = None", AI.url_for("base") == URL and AI.url_for("bsc") is None and AI.url_for("robinhood") is None)
os.environ.pop(NK.ENV_ALCHEMY, None)
check("L2g 키 없음 = None", AI.url_for("base") is None)
AL_PAGES.clear()


class Wr:
    def __init__(self):
        self.recs = []

    def append(self, rec):
        self.recs.append(copy.deepcopy(rec))


WR = Wr()
w = evm_watch.RpcChainWatcher(CFG, "base", [W0, W1], WR)
w._log_head = HEAD


def run(plan, blk, key=True, h=None, status="ok", snap_extra=None, nodes=None, pre=None):
    SCRIPT.clear()
    SCRIPT.update(plan)
    fresh()
    if pre is not None:
        pre()
    w._trace_sick_until = 0.0
    w._trace_nf = 0
    w.__dict__.pop("_trace_slow_until", None)
    w.__dict__.pop("_alch_memo", None)
    w.trace_rpcs = list(nodes or [CN, DRPC])
    if key:
        os.environ[NK.ENV_ALCHEMY] = AKEY
    else:
        os.environ.pop(NK.ENV_ALCHEMY, None)
    h = h or hx(blk)
    snap = {"tx": {"hash": h, "block_number": blk, "status": status}}
    if snap_extra is not None:
        snap = dict(snap_extra)
    try:
        w._trace_internal(h, snap)
        return snap, None
    except Exception as e9:
        return snap, e9


TG = evm_watch.RpcChainWatcher._trace_gone
UT = evm_watch.RpcChainWatcher._trace_untried
ALL_GONE = {HCN: ("rpcerr", GAP), DH: ("rpcerr", GONE)}
HO = hx(OLD)
AL_PAGES[OLD] = [{"transfers": [tr(HO, RT, W0, "0x2a", "0_1", OLD), tr(HO, RT, OT, "0x63", "0_2", OLD), tr(hx(0x99), RT, W1, "0x07", "0", OLD)]}]
snap, err = run(ALL_GONE, OLD)
check("L3a 옛 tx(60일) trace 노드 전부 이력 밖 = Alchemy 1콜로 보완 · 내 지갑 행만 · note trace · 출처 표식",
      err is None and snap.get("internal") == [{"from": RT, "to": W0, "value": "42", "success": True}] and snap.get("internal_note") == "trace"
      and snap.get("internal_src") == "alchemy_transfers" and len(al_hits()) == 1, (snap, repr(err), HITS))
check("L3a2 보완 성공은 trace 노드 '아픔' 계수에 안 셈(종전 그대로 0)", int(w.__dict__.get("_trace_nf") or 0) == 0 and not w._trace_sick())
check("L3a3 수집기 기록(_native_notes)에 출처 표식", any(n.get("kind") == "alch_fill" and n.get("src") == "alchemy_transfers" for n in w.cursor.get("_native_notes") or []))
snap, err = run(ALL_GONE, OLD, key=False)
check("L3b 키 없음 = 종전('영영 못 줌' · Alchemy 0콜 · 내부 이동 안 채움)", err is not None and TG(err) and not al_hits() and "internal" not in snap, (repr(err), HITS))
AL_PAGES[RECENT] = [{"transfers": [tr(hx(RECENT), RT, W0, "0x2a", "1", RECENT)]}]
snap, err = run(ALL_GONE, RECENT)
check("L3c 최근 블록(1시간 안) = 종전(Alchemy 0콜 — 색인 지연·실시간에 안 씀)", err is not None and TG(err) and not al_hits(), (repr(err), HITS))
snap, err = run({HCN: ("rpcerr", RL), DH: ("http", 408, '{"message":"Request timeout on the free plan"}')}, OLD)
check("L3d 노드가 바빠 안 물음(Chainnodes 429) = 종전 일시 오류(Alchemy 0콜 — 다음에 trace 가 될 수 있음)",
      err is not None and not TG(err) and not al_hits() and "internal" not in snap, (repr(err), HITS))
snap, err = run({DH: ("http", 408, '{"message":"Request timeout on the free plan"}')}, OLD, nodes=[DRPC])
check("L3e 30일 넘은 tx · drpc 408(무거운 거래) = 보완", err is None and snap.get("internal") and len(al_hits()) == 1, (snap, repr(err), HITS))
HY = hx(YOUNG)
AL_PAGES[YOUNG] = [{"transfers": [tr(HY, RT, W0, "0x2b", "1", YOUNG)]}]
snap, err = run({DH: ("http", 408, '{"message":"Request timeout on the free plan"}')}, YOUNG, nodes=[DRPC])
check("L3f 2시간 전 tx · 408 첫 실패 = 종전 일시(큐 재시도 몫 · Alchemy 0콜)", err is not None and not TG(err) and not al_hits(), (repr(err), HITS))
snap, err = run({DH: ("http", 408, "x")}, YOUNG, nodes=[DRPC], snap_extra={"tx": {"hash": HY, "block_number": YOUNG, "status": "ok"}, "_alch_n": 2})
check("L3g 같은 tx · 큐 재시도 2번 실패 뒤 = 보완 · 내부 칸(_alch_n) 꺼내 버림", err is None and snap.get("internal") and len(al_hits()) == 1
      and "_alch_n" not in snap and "_alch_blk" not in snap, (snap, repr(err)))
AL_PAGES[OLD] = [("http", 500, "upstream")]
snap, err = run(ALL_GONE, OLD)
check("L3h 보완 시도 실패(HTTP 500) = 일시 오류(영영 못 줌 아님 · 시도함 · 내부 이동 없음으로 안 바꿈)",
      err is not None and isinstance(err, AI.AlchFail) and not TG(err) and not UT(err) and "internal" not in snap and len(al_hits()) == 1, (repr(err), snap))
AL_PAGES[OLD] = [{"transfers": [tr(HO, RT, W0, "0x2a", "0_1", OLD)]}]
snap, err = run(ALL_GONE, OLD, status="error")
check("L3i 실패 tx = 행 전부 success False(실측: 실패 tx 의 안쪽 이동도 목록에 나옴 — trace 파서와 같은 결과)",
      err is None and snap.get("internal") == [{"from": RT, "to": W0, "value": "42", "success": False}], (snap, repr(err)))
snap, err = run({}, OLD)
check("L3j trace 성공 = Alchemy 0콜(이미 완전한 trace 를 목록으로 덮지 않음)", err is None and snap.get("internal_note") == "trace" and not al_hits()
      and "internal_src" not in snap, (snap, HITS))
HO2 = hx(OLD * 2)
AL_PAGES[OLD] = [{"transfers": [tr(HO, RT, W0, "0x2a", "0_1", OLD), tr(HO2, RT, W1, "0x2c", "3", OLD)]}]
snap, err = run(ALL_GONE, OLD)
s2 = {"tx": {"hash": HO2, "block_number": OLD, "status": "ok"}}
SCRIPT.update(ALL_GONE)
err2 = None
try:
    w._trace_internal(HO2, s2)
except Exception as e:
    err2 = e
check("L3k 같은 블록 다른 tx = 메모 재사용(Alchemy 1콜) · 각 tx 행", err is None and err2 is None and len(al_hits()) == 1
      and s2.get("internal") == [{"from": RT, "to": W1, "value": "44", "success": True}], (repr(err2), s2, HITS))
RECEIPTS[HO] = {"blockNumber": hex(OLD), "status": "0x0", "transactionHash": HO}
snap, err = run(ALL_GONE, OLD, h=HO, snap_extra={"_alch_n": 0, "_alch_blk": OLD})
check("L3l 스냅숏 없는 재시도(늦은 채움) = 영수증으로 블록·성공 여부(실패 tx = success False) · 영수증 1콜(공개 상세 노드)",
      err is None and snap.get("internal") == [{"from": RT, "to": W0, "value": "42", "success": False}]
      and any(m.startswith("batch:eth_getTransactionReceipt") for _h, m in HITS), (snap, repr(err), HITS))
RECEIPTS[HO] = {"blockNumber": hex(OLD), "status": "0x1", "transactionHash": HO}
snap, err = run(ALL_GONE, OLD, h=HO, snap_extra={"_alch_n": 0, "_alch_blk": OLD + 5})
check("L3m 표식 블록이 틀려도 영수증 블록으로(성공 tx = success True)", err is None and snap.get("internal") == [{"from": RT, "to": W0, "value": "42", "success": True}],
      (snap, repr(err)))
RECEIPTS.pop(HO, None)
snap, err = run(ALL_GONE, OLD, h=HO, snap_extra={"_alch_blk": OLD})
check("L3n 영수증 못 받음 = 일시 오류(내부 이동 없음으로 안 바꿈)", err is not None and not TG(err) and "internal" not in snap, (repr(err), snap))

AL_PAGES[OLD] = [{"transfers": [tr(HO, RT, W0, "0x2a", "0_1", OLD)]}]
bf_engine._rpc_cfg_ensure()
u0 = NK.used_today("alchemy")
snap, err = run(ALL_GONE, OLD)
u1 = NK.used_today("alchemy")
check("L4a 1콜 = node_alchemy 장부 120 CU(alchemy_getAssetTransfers 공식 단가 · 무료 80% 장부)", err is None and u1 - u0 == 120, (u1 - u0, repr(err)))
small = {"hosts": ["*.g.alchemy.com"], "unit": "cu", "month": 31 * 100, "pct": 80.0, "cu": 26, "cu_methods": {"alchemy_getAssetTransfers": 120}}
bf_engine.rpc_day_configure({"rpc_day_limits": {"node_alchemy": small}})
snap, err = run(ALL_GONE, OLD)
check("L4b ★al944 #1★ 하루 몫(80%) 다 씀 = 0콜 거절 → 일시(AlchFail budget · '영영 못 줌' 아님 → 큐 유지) · Alchemy HTTP 0 · 내부 이동 없음으로 안 바꿈",
      isinstance(err, AI.AlchFail) and err.kind == "budget" and not TG(err) and not al_hits() and "internal" not in snap, (repr(err), HITS))
SPEC_REAL = {"rpc_day_limits": {f"node_{p}": NK.budget_spec(p, NK.plans({})[p]) for p in NK.PROVIDERS}}
bf_engine.rpc_day_configure(SPEC_REAL)
AL_PAGES[OLD] = [{"transfers": [tr(HO, RT, W0, "0x2a", "0_1", OLD)], "pageKey": "pk-1"}, {"transfers": [tr(HO, RT, W0, "0x2b", "0_2", OLD)]}]
u9 = NK.used_today("alchemy")
bf_engine.rpc_day_configure({"rpc_day_limits": {"node_alchemy": dict(small, month=None, day=u9 + 180, pct=100.0)}})
snap, err = run(ALL_GONE, OLD)
check("L4c ★al944 #1★ 첫 쪽 받은 뒤 둘째 쪽 장부 0콜 거절 = 일시(AlchFail budget · 부분 결과 안 씀 · 큐 유지)",
      isinstance(err, AI.AlchFail) and err.kind == "budget" and not TG(err) and len(al_hits()) == 1 and "internal" not in snap, (repr(err), HITS, snap))
bf_engine.rpc_day_configure(SPEC_REAL)
AL_PAGES[OLD] = [{"transfers": [tr(HO, RT, W0, "0x2a", "0_1", OLD)]}]


def _open_alch():
    g9 = bf_engine.gate(AHOST)
    g9.open_until, g9.open_count = evm_watch.time.time() + 600, 2


snap, err = run(ALL_GONE, OLD, pre=_open_alch)
check("L4d ★al944 #1★ Alchemy 서킷 열림(0콜 거절) = 일시(AlchFail budget · 큐 유지 · '영영 못 줌' 아님)",
      isinstance(err, AI.AlchFail) and err.kind == "budget" and not TG(err) and not al_hits() and "internal" not in snap, (repr(err), HITS))

HB1, HB2 = hx(0xb1), hx(0xb2)
AL_PAGES[OLD] = [{"transfers": [tr(HB1, RT, W0, "0x10", "2", OLD), tr(HB2, OT, W1, "0x20", "1_0", OLD), tr(hx(0xb3), RT, OT, "0x30", "1", OLD)]}]
RECEIPTS[HB1] = {"blockNumber": hex(OLD), "status": "0x1"}
RECEIPTS[HB2] = {"blockNumber": hex(OLD), "status": "0x0"}


def run_block(plan, blk, ctx_n=None, key=True):
    SCRIPT.clear()
    SCRIPT.update(plan)
    fresh()
    w._trace_sick_until = 0.0
    w._trace_nf = 0
    w.__dict__.pop("_alch_memo", None)
    w.trace_rpcs = [CN, DRPC]
    if key:
        os.environ[NK.ENV_ALCHEMY] = AKEY
    else:
        os.environ.pop(NK.ENV_ALCHEMY, None)
    if ctx_n is not None:
        w._alch_ctx_n = ctx_n
    try:
        return w._trace_block(blk), None
    except Exception as e9:
        return None, e9


res, err = run_block(ALL_GONE, OLD)
check("L5a 옛 블록 trace 전부 이력 밖 = Alchemy 목록으로 그 블록 내 지갑 행(실패 tx = success False) · 못 푼 것 없음",
      err is None and res == ({HB1: [{"from": RT, "to": W0, "value": "16", "success": True}],
                               HB2: [{"from": OT, "to": W1, "value": "32", "success": False}]}, []) and len(al_hits()) == 1, (res, repr(err)))
res, err = run_block(ALL_GONE, OLD, key=False)
check("L5b 키 없음 = 종전(영영 못 줌 오류 · 0콜)", err is not None and TG(err) and not al_hits(), repr(err))
AL_PAGES[YOUNG] = [{"transfers": [tr(HB1, RT, W0, "0x10", "2", YOUNG)]}]
RECEIPTS[HB1] = {"blockNumber": hex(YOUNG), "status": "0x1"}
res, err = run_block({HCN: ("http", 408, "x"), DH: ("http", 408, "x")}, YOUNG)
check("L5c 2시간 전 블록 408 · 잎 큐 문맥 없음 = 종전 일시", err is not None and not TG(err) and not al_hits(), repr(err))
res, err = run_block({HCN: ("http", 408, "x"), DH: ("http", 408, "x")}, YOUNG, ctx_n=2)
check("L5d 잎 큐 2번 실패 문맥 = 보완 · 문맥은 이 호출 하나에만(꺼냄)", err is None and res and res[0].get(HB1) and "_alch_ctx_n" not in w.__dict__, (res, repr(err)))
res, err = run_block({HCN: ("http", 408, "x"), DH: ("http", 408, "x")}, YOUNG)
check("L5e 다음 호출은 문맥 없음 = 종전", err is not None and not al_hits(), repr(err))
RECEIPTS.pop(HB2, None)
AL_PAGES[OLD] = [{"transfers": [tr(HB2, OT, W1, "0x20", "1_0", OLD)]}]
res, err = run_block(ALL_GONE, OLD)
check("L5f 블록 보완 영수증 못 받음 = 일시 오류(잎 = 재시도)", err is not None and not TG(err) and res is None, repr(err))

A_rows = [{"from": RT, "to": W0, "value": "42", "success": True}, {"from": RT, "to": W0, "value": "42", "success": True}]
T_rows = [{"from": RT, "to": W0, "value": "42", "success": True}, {"from": RT, "to": W0, "value": "42", "success": True}]
m9 = core.Core._merge_list_snaps({"internal": A_rows}, {"internal": T_rows})
check("L6a Alchemy 행 + trace 행(같은 이동 두 건씩) 합집합 = 두 건(네 건 아님)", len(m9["internal"]) == 2, m9)
m9 = core.Core._merge_list_snaps({"internal": A_rows[:1]}, {"internal": T_rows})
check("L6b 목록이 한 건만 줘도 trace 두 건이 이김(줄지 않음)", len(m9["internal"]) == 2, m9)
m9 = core.Core._merge_list_snaps({"internal": [dict(A_rows[0], success=False)]}, {"internal": [{"from": RT, "to": W0, "value": "42", "success": False}]})
check("L6c 실패 tx 행(success False)끼리도 한 번", len(m9["internal"]) == 1, m9)

HL = hx(0xc1)
AL_PAGES[OLD] = [{"transfers": [tr(HL, RT, W0, "0x2a", "0_1", OLD)]}]
RECEIPTS[HL] = {"blockNumber": hex(OLD), "status": "0x1"}
SCRIPT.clear()
SCRIPT.update(ALL_GONE)
fresh()
os.environ[NK.ENV_ALCHEMY] = AKEY
w.__dict__.pop("_alch_memo", None)
w.trace_rpcs = [CN, DRPC]
w._trace_sick_until = 0.0
now9 = int(evm_watch.time.time())
w.cursor["_handover"] = {}
w.cursor["_trace_later"] = {HL: {"at": now9 - 3600, "n": 0, "next": now9 - 1, "blk": OLD, "sent": True}}
w.emitted.add(HL)
DET = {"n": 0}


def det(hs, **kw):
    DET["n"] += 1
    return {h: {"tx": {"hash": h, "block_number": OLD, "from": W0, "to": RT, "status": "ok", "synth": "rpc"}, "token_transfers": [], "internal": []} for h in hs}


w._details = det
WR.recs.clear()
n9 = w._trace_later_step(HEAD)
rec = WR.recs[-1] if WR.recs else {}
check("L7a 옛 tx 늦은 채움 = Alchemy 보완 → internal 붙여 다시 방출(int_fill) · 출처 표식 · 큐에서 뺌",
      n9 == 1 and rec.get("repair") == "int_fill" and (rec.get("snapshot") or {}).get("internal") == [{"from": RT, "to": W0, "value": "42", "success": True}]
      and (rec.get("snapshot") or {}).get("internal_src") == "alchemy_transfers" and HL not in (w.cursor.get("_trace_later") or {}), (n9, rec, w.cursor.get("_trace_later")))
check("L7b 방출본에 내부 칸(_alch_*) 없음", not any(k.startswith("_alch") for k in (rec.get("snapshot") or {})), rec)
AL_PAGES[OLD] = [("http", 502, "bad gateway")]
w.__dict__.pop("_alch_memo", None)
fresh()
w.cursor["_trace_later"] = {HL: {"at": now9 - 3600, "n": 0, "next": now9 - 1, "blk": OLD, "sent": True}}
WR.recs.clear()
n9 = w._trace_later_step(HEAD)
e9 = (w.cursor.get("_trace_later") or {}).get(HL) or {}
check("L7c 보완 실패(502) = 큐 유지(횟수만 +1 · 지우지 않음 · 방출 없음)", n9 == 0 and e9.get("n") == 1 and not WR.recs, (n9, e9))
os.environ.pop(NK.ENV_ALCHEMY, None)
w.__dict__.pop("_alch_memo", None)
fresh()
w.cursor["_trace_later"] = {HL: {"at": now9 - 3600, "n": 0, "next": now9 - 1, "blk": OLD, "sent": True}}
n9 = w._trace_later_step(HEAD)
check("L7d 키 없음 = 종전(전부 이력 밖 = 기록 남기고 뺌 · Alchemy 0콜)", n9 == 0 and HL not in (w.cursor.get("_trace_later") or {}) and not al_hits()
      and any(n.get("kind") == "trace_later_unsupported" for n in w.cursor.get("_native_notes") or []), (n9, w.cursor.get("_trace_later")))

AL_PAGES[OLD] = [{"transfers": [tr(HL, RT, W0, "0x2a", "0_1", OLD)]}]
SMALL0 = {"rpc_day_limits": {"node_alchemy": dict(small, month=None, day=1, pct=100.0)}}
os.environ[NK.ENV_ALCHEMY] = AKEY
bf_engine.rpc_day_configure(SMALL0)
w.__dict__.pop("_alch_memo", None)
fresh()
w.cursor["_native_notes"] = []
w.cursor["_trace_later"] = {HL: {"at": now9 - 3600, "n": 0, "next": now9 - 1, "blk": OLD, "sent": True}}
WR.recs.clear()
n9 = w._trace_later_step(HEAD)
e9 = (w.cursor.get("_trace_later") or {}).get(HL)
check("L8a 늦은 채움 · Alchemy 하루 몫 0콜 거절 = 큐 유지(지우지 않음 · 몫이 돌아오면 다시) · Alchemy HTTP 0 · 방출 없음",
      n9 == 0 and isinstance(e9, dict) and not al_hits() and not WR.recs
      and not any(n.get("kind") == "trace_later_unsupported" for n in w.cursor.get("_native_notes") or []), (n9, e9, w.cursor.get("_native_notes")))
bf_engine.rpc_day_configure(SPEC_REAL)
w.__dict__.pop("_alch_memo", None)
fresh()
if isinstance(e9, dict):
    e9["next"] = now9 - 1
WR.recs.clear()
n9 = w._trace_later_step(HEAD)
check("L8b 몫이 돌아온 다음 차례 = 보완 → internal 붙여 다시 방출 · 큐에서 뺌", n9 == 1 and HL not in (w.cursor.get("_trace_later") or {}) and len(al_hits()) == 1,
      (n9, w.cursor.get("_trace_later"), HITS))
AL_PAGES[OLD] = [{"transfers": [tr(HB1, RT, W0, "0x10", "2", OLD)]}]
RECEIPTS[HB1] = {"blockNumber": hex(OLD), "status": "0x1"}
bf_engine.rpc_day_configure(SMALL0)
w.__dict__.pop("_alch_memo", None)
fresh()
w.cursor["_native_notes"] = []
LK = f"{W0}:{OLD}"
w.cursor["_leaf_later"] = {LK: {"w": W0, "blk": OLD, "n": 0, "next": now9 - 1, "at": now9 - 3600}}
n9 = w._leaf_later_step(HEAD)
e9 = (w.cursor.get("_leaf_later") or {}).get(LK)
check("L8c 잎 큐 · Alchemy 하루 몫 0콜 거절 = 항목 유지(지우지 않음) · Alchemy HTTP 0",
      n9 == 0 and isinstance(e9, dict) and not al_hits()
      and not any(n.get("kind") == "leaf_later_unsupported" for n in w.cursor.get("_native_notes") or []), (n9, e9, w.cursor.get("_native_notes")))
bf_engine.rpc_day_configure(SPEC_REAL)
os.environ.pop(NK.ENV_ALCHEMY, None)
fresh()
w.cursor["_leaf_later"] = {LK: {"w": W0, "blk": OLD, "n": 0, "next": now9 - 1, "at": now9 - 3600}}
n9 = w._leaf_later_step(HEAD)
check("L8d 키 없음 = 종전(전부 이력 밖 = 잎 큐에서 뺌 · 0콜)", LK not in (w.cursor.get("_leaf_later") or {}) and not al_hits(), (w.cursor.get("_leaf_later"), HITS))
w.cursor.pop("_leaf_later", None)

import types

CLK = {"off": 0.0}
_RT = evm_watch.time
FT = types.SimpleNamespace(**{k: getattr(_RT, k) for k in dir(_RT) if not k.startswith("__")})
FT.time = lambda: _RT.time() + CLK["off"]
RB = []
_rb0 = bf_engine.rpc_batch


def _slow_batch(url, calls, **kw):
    RB.append((url, dict(kw)))
    CLK["off"] += float(kw.get("timeout") or 30)
    raise bf_engine.NetError("timed out", "timeout")


cfg0 = list(w.cfg_rpcs)
w.cfg_rpcs = ["http://127.0.0.1:9/r1", "http://127.0.0.1:9/r2", "http://127.0.0.1:9/r3"]
fresh()
evm_watch.time = FT
T.patch_moved("time", evm_watch.time, ("evm_",))
bf_engine.rpc_batch = _slow_batch
try:
    with w._trace_budget(_RT.time() + 2):
        try:
            w._alch_status([HL])
            e9 = None
        except Exception as e:
            e9 = e
finally:
    evm_watch.time = _RT
    T.patch_moved("time", evm_watch.time, ("evm_",))
    bf_engine.rpc_batch = _rb0
    w.cfg_rpcs = cfg0
cap9 = w.ALCH_CALL_SEC
check("L9a 영수증 배치 = 일반 RPC 마감 문맥(timeout ≤ Alchemy 1콜 몫 · sem_timeout·deadline 있음 — 세마포어 무기한 대기 없음)",
      RB and all(k.get("sem_timeout") is not None and k.get("deadline") is not None and float(k["timeout"]) <= cap9 for _u, k in RB), RB)
check("L9b 첫 노드가 마감을 다 쓰면 다음 노드 시작 안 함(노드마다 새 30초 아님) · 쓴 시간 ≤ Alchemy 1콜 몫",
      len(RB) == 1 and CLK["off"] <= cap9 + 0.5, (len(RB), CLK["off"]))
check("L9c 마감 넘김 = TraceDeferred(시도 안 함 · 큐 유지 — AlchFail·'영영 못 줌' 아님)",
      isinstance(e9, evm_watch.TraceDeferred) and not TG(e9), repr(e9))
check("L9d 마감 문맥은 그 배치에만(나오면 _rdl 되돌림)", "_rdl" not in w.__dict__, w.__dict__.get("_rdl"))

CU = {"alchemy_getAssetTransfers": 120, "eth_getLogs": 60, "alchemy_getTokenBalances": 20}


def _sim(method, sec=40.0):
    clk = {"t": 1000.0}
    _bt = bf_engine.time
    fk = types.SimpleNamespace(**{k: getattr(_bt, k) for k in dir(_bt) if not k.startswith("__")})
    fk.monotonic = lambda: clk["t"]
    fk.time = lambda: clk["t"]
    fk.sleep = lambda x: clk.__setitem__("t", clk["t"] + max(1e-6, float(x)))
    pol = dict(bf_engine._policy_for(AHOST), share="t_al944_" + method[-8:].lower())
    with bf_engine._SHARES_LOCK:
        bf_engine._SHARES.pop(pol["share"], None)
    fp = os.path.join(common.quota_dir(), "rpc_gap", pol["share"] + ".bucket")
    if os.path.exists(fp):
        os.remove(fp)
    bf_engine.time = fk
    try:
        g9 = bf_engine.HostGate(AHOST, pol)
        ts = []
        while clk["t"] < 1000.0 + sec:
            g9.acquire(prio="bg", deadline=clk["t"] + 60, cost=g9.gate_cost(1, (method,)) if hasattr(g9, "gate_cost") else 1)
            ts.append(clk["t"])
            clk["t"] += 1e-4
    finally:
        bf_engine.time = _bt
        with bf_engine._SHARES_LOCK:
            bf_engine._SHARES.pop(pol["share"], None)
    return ts


def _win_max(ts, win):
    return max(sum(1 for x in ts if t0 <= x <= t0 + win) for t0 in ts)


ts_at = _sim("alchemy_getAssetTransfers")
ts_lg = _sim("eth_getLogs")
m10, m1 = _win_max(ts_at, 10.0) * CU["alchemy_getAssetTransfers"], _win_max(ts_at, 1.0) * CU["alchemy_getAssetTransfers"]
check("L10a getAssetTransfers 연속 호출 · 10초 창 최대 CU ≤ 2,400(무료 3,000 CU/10초의 80%)", m10 <= 2400, (m10, _win_max(ts_at, 10.0)))
check("L10b getAssetTransfers · 1초 창 최대 CU ≤ 240(무료 300 CU/s 의 80%)", m1 <= 240, (m1, _win_max(ts_at, 1.0)))
lg10 = _win_max(ts_lg, 10.0)
check("L10c eth_getLogs(60 CU = 3칸 · exbal1012 칸 20 CU) · 10초 창 ≤ 2,400 CU · 1초 창 ≤ 240 CU · 처리량 종전(10초 22콜) 이상",
      lg10 * CU["eth_getLogs"] <= 2400 and lg10 >= 22 and _win_max(ts_lg, 1.0) * CU["eth_getLogs"] <= 240, (lg10, _win_max(ts_lg, 1.0)))
GC = []
_acq0 = bf_engine.HostGate.acquire


def _rec_acq(self, prio="fg", deadline=None, cost=1):
    if self.host == AHOST:
        GC.append(cost)
    return _acq0(self, prio=prio, deadline=deadline, cost=cost)


AL_PAGES[B] = [{"transfers": [tr(H1, RT, W0, "0x01", "1", B)]}]
os.environ[NK.ENV_ALCHEMY] = AKEY
fresh()
bf_engine.HostGate.acquire = _rec_acq
try:
    AI.fetch_range(URL, B, B)
finally:
    bf_engine.HostGate.acquire = _acq0
os.environ.pop(NK.ENV_ALCHEMY, None)
check("L10d 실제 경로(rpc_call → http_request): getAssetTransfers 1콜이 Alchemy 게이트에서 6칸(120 CU = 20 CU × 6 — exbal1012 칸 20 CU)", GC == [6], GC)
check("L10e 다른 칸(call_cost 없음 — drpc 등) = 칸 수 종전(콜 수) 그대로 · Alchemy 메서드 모름 = 콜마다 2칸 · getLogs 3 + eth_call 2",
      bf_engine.gate(DH).gate_cost(3, ["alchemy_getAssetTransfers"] * 3) == 3 and bf_engine.gate(AHOST).gate_cost(2, None) == 4
      and bf_engine.gate(AHOST).gate_cost(2, ["eth_getLogs", "eth_call"]) == 5)

check("Z 키 값이 기록·오류 문구에 없음", AKEY not in json.dumps(w.cursor, ensure_ascii=False) and AKEY not in json.dumps(WR.recs, ensure_ascii=False))
T.finish()
