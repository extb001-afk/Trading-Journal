#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402

import paths  # noqa: E402
import bf_engine  # noqa: E402
import nodesel  # noqa: E402
import evm_watch  # noqa: E402

KEYTOK = "k3yS3cr3tT0ken0123456789"
PUB_A = "https://pub-a.example.org/rpc"
PUB_B = "https://rpc.other-pub.net/"
ANKR_BASE = f"https://rpc.ankr.com/base/{KEYTOK}"
ANKR_BSC = f"https://rpc.ankr.com/bsc/{KEYTOK}"
NODEREAL = f"https://bsc-mainnet.nodereal.io/v1/{KEYTOK}"
QN = f"https://my-endpoint-name.base-mainnet.quiknode.pro/{KEYTOK}/"
SUBKEY = f"https://{KEYTOK.lower()}.custom-vendor.io/"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


CLK = Clock()
nodesel.clock = CLK
HOSTS = {h: {"rate": 1000.0, "burst": 1000, "conc": 8} for h in ("pub-a.example.org", "rpc.other-pub.net")}
HOSTS["rpc.ankr.com"] = {"rate": 1000.0, "burst": 1000, "conc": 8, "call_rate": 1000.0, "call_burst": 1000, "share_rate": 1000.0, "share_burst": 1000}
CFG = {"backfill": {"hosts": HOSTS},
       "rpc_day_limits": {"node_ankr": {"hosts": ["rpc.ankr.com"], "unit": "calls", "day": 10, "pct": 80}}}
bf_engine.configure(CFG)


class FakeResp:
    def __init__(self, body: bytes):
        self.body = body
        self.headers = {}
        self.length = len(body)

    def read(self, n=-1):
        b, self.body = self.body, b""
        return b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


PLAN = {}


def fake_sol_open(req, timeout, *a, **k):
    h = (bf_engine.urllib.parse.urlsplit(req.full_url).hostname or "").lower()
    fn = PLAN.get(h)
    if fn is None:
        raise OSError("시험: 계획 없는 노드")
    sec, out = fn(req)
    CLK.t += sec
    if isinstance(out, BaseException):
        raise out
    return FakeResp(json.dumps(out).encode())


bf_engine.sol_open = fake_sol_open


def ok_result(req):
    body = json.loads(req.data.decode())
    if isinstance(body, list):
        return 0.1, [{"jsonrpc": "2.0", "id": it["id"], "result": "0x1"} for it in body]
    return 0.1, {"jsonrpc": "2.0", "id": body.get("id"), "result": "0x1"}


def http_err(code):
    import io
    import urllib.error
    return urllib.error.HTTPError("https://x/", code, "err", {}, io.BytesIO(b""))


T.chk(nodesel.role_of(["eth_getLogs"]) == "logs", "O1 getLogs = logs")
T.chk(nodesel.role_of(["debug_traceTransaction"]) == "trace" and nodesel.role_of(["trace_block"]) == "trace", "O1 trace·debug = trace")
T.chk(nodesel.role_of(["eth_getBalance", "eth_getTransactionCount"]) == "state", "O1 잔고·nonce = state")
T.chk(nodesel.role_of(["eth_getTransactionReceipt", "eth_getTransactionByHash", "eth_getBlockByNumber"]) == "detail", "O1 tx·receipt·블록 = detail")
T.chk(nodesel.role_of(["eth_blockNumber"]) == "head", "O1 헤드 = head")
T.chk(nodesel.role_of(["eth_getBalance", "eth_getTransactionCount", "eth_getBlockByNumber"]) == "state", "O1 배치 = 많은 쪽")

nodesel.reset()
nodesel.register("base", [PUB_A, ANKR_BASE, QN, SUBKEY])
nodesel.register("bsc", [NODEREAL, ANKR_BSC, PUB_B])
PLAN["pub-a.example.org"] = ok_result
PLAN["rpc.ankr.com"] = ok_result
for _ in range(3):
    bf_engine.rpc_call(PUB_A, "eth_getBalance", ["0x" + "11" * 20, "latest"], retries=1)
PLAN["pub-a.example.org"] = lambda req: (2.0, http_err(429))
r = T.safe(bf_engine.rpc_call, PUB_A, "eth_getBalance", ["0x" + "11" * 20, "latest"], retries=1)
PLAN["pub-a.example.org"] = lambda req: (25.0, http_err(408))
r = T.safe(bf_engine.rpc_call, PUB_A, "eth_getBalance", ["0x" + "11" * 20, "latest"], retries=1)
snap = nodesel.snapshot()
row = [x for x in snap["rows"] if x["chain"] == "base" and x["role"] == "state" and x["prov"] == "example.org"]
T.chk(len(row) == 1 and row[0]["n"] == 5 and row[0]["ok"] == 3 and row[0].get("http429") == 1 and row[0].get("t408") == 1,
      "O3 공개 노드 표본 — 성공 3 · 429 1 · 408 1(노드 표본)", row)
T.chk(row and row[0]["p50"] is not None and abs(row[0]["p50"] - 0.1) < 1e-6, "O3 전송 시간 = 실제 전송부터(성공 p50 0.1초)", row)
sent = {"n": 0}


def ankr_ok(req):
    sent["n"] += 1
    return ok_result(req)


PLAN["rpc.ankr.com"] = ankr_ok
errs = []
for _ in range(12):
    try:
        bf_engine.rpc_call(ANKR_BASE, "eth_getBalance", ["0x" + "11" * 20, "0x10"], retries=1)
    except bf_engine.NetError as e:
        errs.append(e)
snap = nodesel.snapshot()
row = [x for x in snap["rows"] if x["chain"] == "base" and x["role"] == "state" and x["prov"] == "ankr"]
T.chk(sent["n"] == 8 and len(errs) == 4 and all(getattr(e, "local", False) for e in errs), "O3 하루 장부 80%(8콜) 뒤 보내지 않음", [sent, len(errs)])
T.chk(row and row[0]["n"] == 8 and row[0]["ok"] == 8 and row[0]["local"] == 4, "O3 장부 거절 = local 칸만(노드 실패 아님)", row)
T.chk(row and row[0].get("ledger") == "node_ankr", "O5 Ankr(Base) 장부 = node_ankr", row)
nodesel.end(ANKR_BSC, ["eth_getLogs"], 1, nodesel.begin())
snap = nodesel.snapshot()
row = [x for x in snap["rows"] if x["chain"] == "bsc" and x["prov"] == "ankr"]
T.chk(row and row[0].get("ledger") == "node_ankr", "O5 같은 Ankr 키(BSC)도 같은 장부 node_ankr", row)
for u in (QN, SUBKEY, NODEREAL):
    nodesel.end(u, ["eth_getBalance"], 1, nodesel.begin())
nodesel._maybe_flush(force=True)
fp = os.path.join(paths.quota_dir(), "node_stats", f"{bf_engine._RPC_DAY_PROC}.json")
raw = open(fp, encoding="utf-8").read() if os.path.exists(fp) else ""
T.chk(bool(raw) and KEYTOK not in raw and KEYTOK.lower() not in raw and "my-endpoint-name" not in raw and "/rpc" not in raw
      and "pub-a" not in raw and "https://" not in raw, "O2 관측 파일에 주소·키·경로·이름 칸 없음", raw[:300])
T.chk({"quicknode", "custom-vendor.io", "nodereal", "ankr", "example.org"} <= {x["prov"] for x in json.loads(raw)["rows"]},
      "O2 서비스 이름만(키 노드 = 서비스 · 공개 = 도메인)", sorted({x["prov"] for x in json.loads(raw)["rows"]}))

nodesel.reset()
nodesel.register("base", [PUB_A, ANKR_BASE])


def put(url, methods, sec, err=None, n=1):
    for _ in range(n):
        t0 = nodesel.begin()
        nodesel.mark_dispatch()
        CLK.t += sec
        nodesel.end(url, methods, 1, t0, err)


put(PUB_A, ["eth_getBalance"], 15.0, n=12)
put(PUB_A, ["eth_getLogs"], 0.5, n=12)
T.chk(nodesel.demoted("base", "state", PUB_A) and not nodesel.demoted("base", "logs", PUB_A), "O4 상태 느림 → 상태만 뒤로(getLogs 점수 섞이지 않음)")
with bf_engine.ledger_burst():
    put(PUB_A, ["eth_getLogs"], 30.0, n=12)
T.chk(not nodesel.demoted("base", "logs", PUB_A), "O4 백필 걸음 느림은 실시간 getLogs 판정에 안 섞임")
nodesel.reset()
nodesel.register("base", [PUB_A])
put(PUB_A, ["eth_getBalance"], 15.0, n=5)
put(PUB_A, ["eth_getBalance"], 0.3, n=7)
T.chk(not nodesel.demoted("base", "state", PUB_A), "O4 한 창만 느림 = 뒤로 안 보냄(두 창 연속일 때만)")
loc = bf_engine.NetError("quota", "quota")
loc.local = True
for _ in range(12):
    nodesel.end(PUB_A, ["eth_getBalance"], 1, nodesel.begin(), loc)
T.chk(not nodesel.demoted("base", "state", PUB_A), "O4 우리 쪽 거절(local) 12번 = 노드 나쁨 아님")

nodesel.reset()
bf_engine.configure(CFG)
nodesel.configure({"backfill": {"node_select": False}})
T.chk(not nodesel.enabled(), "O6 선택 끔(backfill.node_select false — 되돌림 스위치) = 관측만")
W = object.__new__(evm_watch.RpcChainWatcher)
W.chain, W.state_rpcs, W.cfg_rpcs = "base", [PUB_A, ANKR_BASE], [PUB_A]
nodesel.register("base", W.state_rpcs)
put(PUB_A, ["eth_getBalance"], 15.0, n=12)
T.chk(nodesel.demoted("base", "state", PUB_A), "O6 준비: 공개 상태 노드 느림 판정")
T.chk(W._node_order(W.state_rpcs) == [PUB_A, ANKR_BASE], "O6 선택 끔 = 종전 순서 그대로(공개 먼저)", W._node_order(W.state_rpcs))
sh = nodesel.snapshot()["shadow"]
T.chk(sh.get("base:state:rt", {}).get("diff", 0) >= 1 and sh["base:state:rt"].get("last") == "ankr", "O6 shadow — 선택기라면 Ankr 먼저(횟수만 셈)", sh)
W._key_ctx = True
T.chk(W._node_order(W.state_rpcs) == [ANKR_BASE, PUB_A], "O6 따라잡는 걸음 = 종전 규칙(키 먼저) 그대로")

S1 = "https://rpc.second-pub.io/"
nodesel.reset()
CFG2 = {"backfill": {"hosts": dict(HOSTS, **{"rpc.second-pub.io": {"rate": 1000.0, "burst": 1000, "conc": 8}})},
        "rpc_day_limits": {"s6_ankr": {"hosts": ["rpc.ankr.com"], "unit": "calls", "day": 100000, "pct": 80}}}
bf_engine.configure(CFG2)
T.chk(nodesel.enabled(), "S0 선택 기본 켬(backfill.node_select 없음)")
W = object.__new__(evm_watch.RpcChainWatcher)
W.chain, W.state_rpcs, W.cfg_rpcs, W.trace_rpcs = "base", [PUB_A, ANKR_BASE], [PUB_A], [PUB_A, S1]
nodesel.register("base", W.state_rpcs, W.trace_rpcs)
USED = []


def plan_lat(host, sec):
    def f(req):
        USED.append(host)
        return sec, ok_result(req)[1]
    PLAN[host] = f


plan_lat("pub-a.example.org", 15.0)
plan_lat("rpc.ankr.com", 0.2)
for _ in range(14):
    W._state_call("eth_getBalance", ["0x" + "11" * 20, "0x10"])
T.chk(USED[:12] == ["pub-a.example.org"] * 12 and USED[12:14] == ["rpc.ankr.com"] * 2, "S1 공개 느림 두 창 → 다음 콜부터 Ankr(키) 백업", USED[:14])
USED.clear()
for _ in range(30):
    W._state_call("eth_getBalance", ["0x" + "11" * 20, "0x10"])
    CLK.t += 5.0
T.chk(USED.count("pub-a.example.org") in (2, 3) and nodesel.demoted("base", "state", PUB_A),
      "S1 뒤로 간 동안 회복 확인 = 60초마다 실제 작업 1번만(나머지 Ankr) · 아직 느림 = 유지", USED.count("pub-a.example.org"))
plan_lat("pub-a.example.org", 0.3)
USED.clear()
for _ in range(60):
    W._state_call("eth_getBalance", ["0x" + "11" * 20, "0x10"])
    CLK.t += 5.0
T.chk(not nodesel.demoted("base", "state", PUB_A), "S1 회복 3번 연속 → 공개로 되돌림")
T.chk(USED[-5:] == ["pub-a.example.org"] * 5, "S1 되돌린 뒤 = 공개 노드 주(종전 순서)", USED[-5:])
sw = sum(1 for a, b in zip(USED, USED[1:]) if a != b)
T.chk(sw <= 7, f"S1 전환 횟수 제한(hysteresis) — {sw}번", USED)

nodesel.reset()
nodesel.register("base", [PUB_A, S1, QN, ANKR_BASE])
put(PUB_A, ["debug_traceTransaction"], 25.0, n=12)
T.chk(W._trace_order() == [S1, PUB_A], "S3 느린 trace 노드 뒤로(정상 노드 먼저)", W._trace_order())
T.chk(nodesel.order("base", "trace", [QN, PUB_A, S1]) == [QN, S1, PUB_A], "S3 QuickNode 가 맨 앞이면 그대로(느린 공개만 뒤로)")
T.chk(nodesel.order("base", "trace", [PUB_A, QN]) == [PUB_A, QN], "S3 뒤에 정상 공개 노드가 없으면 그대로(키 노드로 trace 를 옮기지 않음)")
put(PUB_A, ["eth_getBalance"], 15.0, n=12)
T.chk(nodesel.order("base", "state", [PUB_A, QN, ANKR_BASE]) == [ANKR_BASE, PUB_A, QN],
      "S3 상태 — 느린 공개는 Ankr 뒤로 · QuickNode 는 그 공개 노드를 앞지르지 않음", nodesel.order("base", "state", [PUB_A, QN, ANKR_BASE]))
T.chk(nodesel.order("base", "logs", [PUB_A, QN]) == [PUB_A, QN], "S3 QuickNode 는 잘하는 API 표 밖(getLogs 등) — 앞으로 안 올림")

def lane_run(n_items, day_calls, on=True):
    nodesel.reset()
    cfg = {"backfill": {"hosts": CFG2["backfill"]["hosts"], "bf_target_sec": 300, "node_select": on},
           "rpc_day_limits": {"t_ankr_%d_%d" % (day_calls, int(on)): {"hosts": ["rpc.ankr.com"], "unit": "calls", "day": day_calls, "pct": 80}}}
    bf_engine.configure(cfg)
    nodesel.register("base", W.state_rpcs)
    plan_lat("pub-a.example.org", 2.0)
    plan_lat("rpc.ankr.com", 0.2)
    USED.clear()
    t0 = CLK.t
    with bf_engine.ledger_burst():
        for i in range(n_items):
            W._state_call("eth_getBalance", ["0x" + "11" * 20, hex(100 + i)])
            if (i + 1) % 10 == 0:
                done = i + 1
                el = CLK.t - t0
                nodesel.lane_eta("base", (n_items - done) / (done / el) if el > 0 else None, n_items - done)
    return CLK.t - t0, USED.count("rpc.ankr.com"), USED.count("pub-a.example.org")


t_off, k_off, p_off = lane_run(300, 100000, on=False)
t_on, k_on, p_on = lane_run(300, 100000, on=True)
T.chk(k_off == 0 and p_off == 300, "S4 선택 끔 = 종전(뒤 차선 공개 먼저 — 키 0)", [k_off, p_off])
T.chk(t_on < t_off * 0.3 and k_on >= 250, f"S4 공개 느림 → Ankr 먼저 · 걸린 시간 {t_off:.0f}초 → {t_on:.0f}초", [t_on, k_on, p_on])
t_cap, k_cap, p_cap = lane_run(300, 100, on=True)
T.chk(k_cap <= 80 and k_cap >= 70 and p_cap + k_cap == 300 and t_cap < t_off,
      f"S4 하루 장부 80%(100 × 80% = 80콜) 안에서만 키 · 나머지는 공개로 이어 감(누락 0) — 키 {k_cap} · {t_cap:.0f}초", [k_cap, p_cap])
nodesel.reset()
nodesel.configure({"backfill": {"bf_target_sec": 300}})
nodesel.lane_eta("base", 1000, 100)
T.chk(nodesel.bf_key_first("base"), "S4 ETA 1000초 > 기준 300초 → 키 먼저")
CLK.t += 100
nodesel.lane_eta("base", 50, 10)
T.chk(nodesel.bf_key_first("base"), "S4 공개였다면 예상(1000×10/100 = 100초)이 기준 절반 아래여도 10분 유지(전환 남발 없음)")
CLK.t += 600
nodesel.lane_eta("base", 50, 10)
T.chk(not nodesel.bf_key_first("base"), "S4 10분 지나고 공개 예상 ≤ 기준 절반 → 공개로 되돌림(키 몫 아낌)")
nodesel.lane_eta("base", 0, 0)
T.chk(not nodesel.bf_key_first("base"), "S4 뒤 차선 끝 = 공개(종전)")

nodesel.reset()
nodesel.register("base", [PUB_A, ANKR_BASE])
T.chk(nodesel.via("base") == "", "U1 표본 없음 = 칩 없음")
put(ANKR_BASE, ["eth_getBalance"], 0.2, n=8)
T.chk(nodesel.via("base") == "Ankr", "U1 최근 5분 Ankr 로만 받음 = 'Ankr'", nodesel.via("base"))
put(PUB_A, ["eth_getBalance"], 0.5, n=6)
T.chk(nodesel.via("base") == "Ankr + 공개 노드", "U1 섞임 = 많은 순 2개(20% 이상)", nodesel.via("base"))
CLK.t += 400
T.chk(nodesel.via("base") == "", "U1 5분 지난 표본 = 칩 없음(오래된 표시 안 남김)")
import web  # noqa: E402
import time as _t  # noqa: E402
now9 = _t.time()
j9 = web.StateBuilder._bf_job_text("base:rpc", 0.45, 720, 0, "extend",
                                   {"done": 45, "total": 100, "unit": "blocks", "moved_at": now9 - 10, "updated": now9, "note": None, "via": "Ankr"}, now=now9)
T.chk(j9.get("via") == "Ankr로 받는 중" and "Ankr로 받는 중" in j9["text"] and j9.get("eta"), "U2 백필 줄 = 진행 · 'Ankr로 받는 중' · 예상 남은 시간", j9)
j9 = web.StateBuilder._bf_job_text("base:rpc", 0.45, 720, 0, "extend",
                                   {"done": 45, "total": 100, "unit": "blocks", "moved_at": now9 - 7200, "updated": now9, "note": None, "via": "Ankr"}, now=now9)
T.chk(j9.get("via") is None and "받는 중" not in j9["text"], "U2 멈춤이면 받는 노드 안 씀", j9)
j9 = web.StateBuilder._bf_job_text("base:rpc", 0.45, 720, 0, "extend",
                                   {"done": 45, "total": 100, "unit": "blocks", "moved_at": now9 - 10, "updated": now9, "note": None}, now=now9)
T.chk(j9.get("via") is None and "받는 중" not in j9["text"], "U2 via 없는 옛 상태 파일 = 종전 문구 그대로", j9)

CN = "https://base-mainnet.chainnodes.example/" + KEYTOK
DRPC = "https://base.drpc.org/"
nodesel.reset()
bf_engine.configure(CFG2)
W = object.__new__(evm_watch.RpcChainWatcher)
W.chain = "base"
W.trace_rpcs = [S1, PUB_A]
nodesel.register("base", W.trace_rpcs, [CN, DRPC, QN])
put(S1, ["debug_traceTransaction"], 25.0, n=12)
W._trace_slow_until = {PUB_A: _t.time() + 300}
T.chk(nodesel.demoted("base", "trace", S1), "R1 준비: B(25초 정상) 느림 판정 · A = E1 표시(408)")
T.chk(W._trace_order() == [S1, PUB_A], "R1 E1 이 먼저 — 응답 가능한 느린 B 가 최근 408 낸 A 앞(종전: [A, B])", W._trace_order())
W._trace_slow_until = {}
T.chk(W._trace_order() == [PUB_A, S1], "R1 E1 표시 없음 = 느린 B 만 정상 A 뒤로", W._trace_order())
put(CN, ["debug_traceTransaction"], 25.0, n=12)
W.trace_rpcs = [CN, QN, DRPC]
T.chk(W._trace_order() == [CN, QN, DRPC], "R1 nodekeys trace 순서(무료 키 → QuickNode → 내장 drpc) 그대로 — 느린 노드가 키 노드를 건너 뒤로 가지 않음(종전: [drpc, 무료 키, QuickNode])", W._trace_order())
put(DRPC, ["debug_traceTransaction"], 25.0, n=12)
W.trace_rpcs = [QN, DRPC, PUB_A]
T.chk(W._trace_order() == [QN, PUB_A, DRPC], "R1 키 노드 뒤 공개 노드끼리는 느린 것 뒤로", W._trace_order())


import bsc_watch  # noqa: E402
CAP = []


class FakeScanner:
    def __init__(self, endpoints, *a, **k):
        CAP.append((list(endpoints), dict(k.get("fallback") or {})))
        self.caps, self.metrics, self.last_stop, self.retention_floor = {}, {}, None, None

    def scan(self, frm, to, deadline=None, on_advance=None):
        return {}, to


real_ls = bf_engine.LogScanner
bf_engine.LogScanner = FakeScanner
nodesel.reset()
bf_engine.configure(CFG2)
nodesel.register("base", [PUB_A, ANKR_BASE])
nodesel.register("bsc", [PUB_B, ANKR_BSC])
put(PUB_A, ["eth_getLogs"], 40.0, n=12)
T.chk(nodesel.demoted("base", "logs", PUB_A), "G1 준비: 공개 getLogs 노드 느림 판정(Base)")
W = object.__new__(evm_watch.RpcChainWatcher)
W.chain, W.cfg = "base", {"chains": {"base": {}}}
W.logs_rpcs = W.logs_primary = [ANKR_BASE, PUB_A]
W.logs_fallback, W.addr_max, W.span, W.min_span = {}, 0, 5000, 1
W._log_head = 1_000_000
for k in range(3):
    CAP.clear()
    CLK.t += 90.0 if k else 0.0
    W._scan_logs(["0x" + "11" * 20], 999_990, 1_000_000, _t.time() + 60)
    T.chk(CAP and CAP[0][0] == [PUB_A] and ANKR_BASE in CAP[0][1], f"G1 Base 헤드 근처 getLogs {k + 1}번째 = 종전(공개 주 · Ankr 예비)", CAP[:1])
B9 = object.__new__(bsc_watch.BscWatcher)
B9.logs_rpc = bsc_watch.Rpc([PUB_B, ANKR_BSC], rotate_each=True)
B9.logs_fb, B9.span, B9.span_max, B9.span_caps, B9.logs_sleep, B9.scan_workers, B9.topics = {}, 5000, 5000, {}, 0.0, 1, ["0x" + "0" * 64]
B9._log_head = 1_000_000
put(PUB_B, ["eth_getLogs"], 40.0, n=12)
T.chk(nodesel.demoted("bsc", "logs", PUB_B), "G1 준비: 공개 getLogs 노드 느림 판정(BSC)")
CAP.clear()
B9.discover(999_990, 1_000_000, budget_sec=30)
T.chk(CAP and CAP[0][0] == [PUB_B] and ANKR_BSC in CAP[0][1], "G1 BSC 헤드 근처 getLogs = 종전(공개 주 · Ankr 예비)", CAP[:1])
bf_engine.LogScanner = real_ls

T.finish()
