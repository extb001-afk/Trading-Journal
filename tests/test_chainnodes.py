#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import urllib.error  # noqa: E402

W0 = "0x" + "e0" * 20
RT = "0x" + "55" * 20
CFG = {"wallets": [{"type": "evm", "chain": "base", "address": W0, "label": "시험"}],
       "chains": {"base": {"rpc_logs": ["https://pub-base.invalid"], "rpc_log_span_caps": {"https://pub-base.invalid": 5000}}},
       "bsc": {"logs_rpcs": ["https://pub-bsc.invalid"], "detail_rpcs": ["https://pub-bsc-detail.invalid"]}}
CP = os.path.join(T.TMP, "config.json")
with open(CP, "w", encoding="utf-8") as f:
    json.dump(CFG, f)
os.environ["TJ_CONFIG"] = CP
import paths, statefile  # noqa: E402
import logs  # noqa: E402

assert T.TMP in paths.STATE_DIR and T.TMP in paths.ENV_PATH
import bf_engine  # noqa: E402
import evm_watch  # noqa: E402
import nodekeys as NK  # noqa: E402
import onboarding  # noqa: E402
import settings_store as ss  # noqa: E402


def check(n, c, d=""):
    T.chk(bool(c), n, None if c else str(d)[:900])


KEY = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
KEY2 = "ffffffff-1111-4222-8333-444444444444"
CN = "https://base-mainnet.chainnodes.org/" + KEY
HCN = "base-mainnet.chainnodes.org"
QETH = "https://fake-name.quiknode.pro/TESTcnQn000000000001/"
QBASE = NK.qn_chain_url(QETH, "base")
DRPC = evm_watch.RpcChainWatcher.TRACE_DEFAULT["base"]


def applied(env, cfg=None, settings=None):
    c = json.loads(json.dumps(cfg or CFG))
    done = NK.apply(c, env=env, settings=settings or {})
    return c, done


for v, why in ((KEY, "UUID"), (KEY.upper(), "대문자 UUID"), (CN, "Base 주소"), (CN + "/", "끝 /"), ("https://eth-mainnet.chainnodes.org/" + KEY, "다른 체인 주소(키는 같음)"),
               ("  " + CN + "  ", "앞뒤 공백")):
    got = NK.cn_key(v)
    check(f"N1a 받음: {why}", got is not None and got.lower() == KEY, got)
for v, why in (("http://base-mainnet.chainnodes.org/" + KEY, "http"), ("https://u:p@base-mainnet.chainnodes.org/" + KEY, "사용자 정보"),
               ("https://base-mainnet.chainnodes.org:8443/" + KEY, "포트"), ("https://base-mainnet.chainnodes.org.evil.invalid/" + KEY, "다른 호스트"),
               ("https://chainnodes.org/" + KEY, "체인 칸 없음"), ("https://base-mainnet.chainnodes.org/" + KEY + "/x", "경로 덧붙임"),
               ("https://base-mainnet.chainnodes.org/" + KEY + "?a=1", "질의"), ("0a1b2c3d4e5f4a6b8c7d9e0f1a2b3c4d", "하이픈 없음"),
               ("0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4z", "16진 아님"), ("", "빈 값"), (None, "None"), ("https://[::1", "깨진 주소")):
    check(f"N1b 거부: {why}", T.safe(NK.cn_key, v) is None, T.safe(NK.cn_key, v))
check("N1c 주소 = Base 주소(키 포함 — 메모리에서만)", NK.cn_url({NK.ENV_CN: CN}) == CN and NK.cn_url({NK.ENV_CN: KEY}) == CN and NK.cn_url({}) is None)

c0, d0 = applied({})
check("N2a 키 없음 = 종전 그대로(trace_rpcs 안 만듦 · 수집기 해석 = 내장 drpc · 정책 안 얹음)", "trace_rpcs" not in c0["chains"]["base"] and "base_trace" not in d0
      and evm_watch.rpc_nodes(c0, "base")["trace"] == DRPC and "*.chainnodes.org" not in json.dumps(c0.get("backfill") or {}), (c0, d0))
c1, d1 = applied({NK.ENV_CN: KEY})
pools9 = json.dumps({k: v for k, v in c1["chains"]["base"].items() if k != "trace_rpcs"}) + json.dumps(c1["bsc"])
check("N2b Chainnodes 만 = Base trace [Chainnodes, drpc] · 로그·상태·아카이브·BSC 풀엔 없음", c1["chains"]["base"]["trace_rpcs"] == [CN] + DRPC
      and "chainnodes" not in pools9 and d1.get("base_trace") == ["chainnodes"] and "chainnodes" not in json.dumps(NK.urls({NK.ENV_CN: KEY})), (c1, d1))
check("N2c 수집기 해석 = 그 순서 · 로그·상태엔 없음", evm_watch.rpc_nodes(c1, "base")["trace"] == [CN] + DRPC
      and CN not in evm_watch.rpc_nodes(c1, "base")["logs"] and CN not in evm_watch.rpc_nodes(c1, "base")["state"])
c2, d2 = applied({NK.ENV_CN: KEY, NK.ENV_QN: QETH, NK.ENV_ANKR: "TESTankr0000000000000001"})
check("N2d Chainnodes + QuickNode + Ankr = [Chainnodes, QuickNode, drpc] · Ankr 는 로그·상태(종전) · Chainnodes 는 풀 밖", c2["chains"]["base"]["trace_rpcs"] == [CN, QBASE] + DRPC
      and d2.get("base_trace") == ["chainnodes", "quicknode"] and CN not in json.dumps(c2["chains"]["base"]["rpc_logs"]) + json.dumps(c2["chains"]["base"].get("archive_rpcs"))
      and "rpc.ankr.com" in json.dumps(c2["chains"]["base"]["rpc_logs"]), (c2["chains"]["base"], d2))
cu = json.loads(json.dumps(CFG))
cu["chains"]["base"]["trace_rpcs"] = ["https://my-trace.invalid"]
c3, _d3 = applied({NK.ENV_CN: KEY, NK.ENV_QN: QETH}, cu)
check("N2e 이용자 trace_rpcs = 그대로 앞 → Chainnodes → QuickNode(이용자 목록이 기본이라 drpc 안 붙음)",
      c3["chains"]["base"]["trace_rpcs"] == ["https://my-trace.invalid", CN, QBASE], c3["chains"]["base"]["trace_rpcs"])
ce = json.loads(json.dumps(CFG))
ce["chains"]["base"]["trace_rpcs"] = []
c4, _d4 = applied({NK.ENV_CN: KEY}, ce)
check("N2f 이용자 trace_rpcs [] (끔) + 키 = 키 노드만(종전 qn2 와 같은 규칙)", c4["chains"]["base"]["trace_rpcs"] == [CN], c4["chains"]["base"]["trace_rpcs"])
c5 = json.loads(json.dumps(c2))
NK.apply(c5, env={NK.ENV_CN: KEY, NK.ENV_QN: QETH, NK.ENV_ANKR: "TESTankr0000000000000001"}, settings={})
check("N2g 두 번 적용해도 같음(중복 없음)", c5["chains"]["base"]["trace_rpcs"] == c2["chains"]["base"]["trace_rpcs"]
      and c5["chains"]["base"]["rpc_logs"] == c2["chains"]["base"]["rpc_logs"], c5["chains"]["base"])
pol = (c1.get("backfill") or {}).get("hosts", {}).get("*.chainnodes.org") or {}
check("N2h 초당 보수 정책(1초 창 콜 2+2 · 동시 1 · 프로세스 합산 공유 버킷) ≤ 공표 25 × 80%", pol.get("conc") == 1 and pol.get("call_burst", 0) + pol.get("call_rate", 0) <= 5
      and pol.get("share") == "node_chainnodes" and pol.get("share_xproc") is True, pol)
cp9 = json.loads(json.dumps(CFG))
cp9["backfill"] = {"hosts": {"*.chainnodes.org": {"rate": 0.5}}}
c6, _ = applied({NK.ENV_CN: KEY}, cp9)
check("N2i 이용자가 config 에 쓴 Chainnodes 정책 우선", c6["backfill"]["hosts"]["*.chainnodes.org"] == {"rate": 0.5}, c6["backfill"])
nobase = {"wallets": [], "chains": {"eth": {}}, "bsc": {"logs_rpcs": ["https://pub-bsc.invalid"]}}
c7, d7 = applied({NK.ENV_CN: KEY}, nobase)
check("N2j Base 칸 없는 설정 = 아무것도 안 붙음(KeyError 없음)", "base" not in c7["chains"] and "base_trace" not in d7, (c7, d7))
ss.write_env({NK.ENV_QN: QETH, NK.ENV_CN: KEY})
NK._QN_SLOT["at"] = -1e18
statefile.atomic_write_json(NK._qn_path(), {"v": 1, "kh": NK.qn_kh(), "hosts": {NK.qn_chain_url(QETH, "base").split("/")[2]: {"first": 1, "n": 5, "off": True, "off_at": 2, "code": 401}}})
c8, d8 = applied(None)
check("N2k QuickNode 가 거부로 빠짐 = [Chainnodes, drpc]", c8["chains"]["base"]["trace_rpcs"] == [CN] + DRPC and d8.get("base_trace") == ["chainnodes"], c8["chains"]["base"])
NK.qn_reject_clear()
ss.write_env({NK.ENV_QN: None, NK.ENV_CN: None})

lim = c1["rpc_day_limits"]["node_chainnodes"]
check("N3a 장부 = 요청 단위(calls) · 월 1,250만 × 80% · 호스트 *.chainnodes.org", lim["unit"] == "calls" and lim["month"] == 12_500_000 and lim["pct"] == 80.0
      and lim["hosts"] == ["*.chainnodes.org"] and "cu" not in lim, lim)
bf_engine.configure(c1)
check("N3b 호스트 → node_chainnodes · trace 1콜 = 1 요청(무거운 trace 도)", bf_engine._rpc_day_of(HCN) == "node_chainnodes"
      and bf_engine._rpc_day_units("node_chainnodes", ["debug_traceTransaction"], 1) == 1 and bf_engine._rpc_day_units("node_chainnodes", ["eth_chainId"] * 3, 3) == 3)
st = NK.status(env={NK.ENV_CN: KEY}, settings={})["chainnodes"]
check("N3c 화면 상태 = Base · '요청' · trace 전용 · 하루 몫 = 1,250만/31 × 80% · 키·주소 없음", st["chains"] == ["base"] and st["unitKo"] == "요청" and st.get("traceOnly") is True
      and st["perDay"] == int(12_500_000 / 31 * 0.8) and KEY not in json.dumps(st) and "chainnodes.org" not in json.dumps(st), st)
check("N3d 키 없음 = 쓰는 체인 없음", NK.status(env={}, settings={})["chainnodes"]["chains"] == [])
if os.path.exists(paths.ENV_PATH):
    os.remove(paths.ENV_PATH)
fp0 = NK.fingerprint()
ss.write_env({NK.ENV_CN: KEY})
fp1 = NK.fingerprint()
ss.write_env({NK.ENV_CN: KEY2})
fp2 = NK.fingerprint()
ss.write_env({NK.ENV_CN: None})
check("N3e 지문 = 키 넣음·바꿈 = 바뀜(수집기 재시작) · 지움 = 종전 그대로", fp0 != fp1 and fp1 != fp2 and NK.fingerprint() == fp0, (fp0, fp1, fp2))
ss.write_env({NK.ENV_CN: KEY})
logs._SECRET_CACHE["sig"] = None
e9 = bf_engine.NetError(f"conn: 연결 실패 {CN} (url={CN})", "conn")
check("N3f 오류 문구에 키 없음(.env 비밀값 가림)", KEY not in str(e9) and KEY[:13] not in str(e9), str(e9))
check("N3g 노드 키 판정(호스트만)", NK.is_key_node(CN) and not NK.is_key_node("https://chainnodes.org.evil.invalid/x"))

SCRIPT = {}
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


def frame(frm, to, v):
    return {"type": "CALL", "from": W0, "to": RT, "value": "0x0", "calls": [{"type": "CALL", "from": frm, "to": to, "value": hex(v)}]}


def fake_open(req, timeout):
    h = req.host.split(":")[0].lower()
    body = json.loads(req.data.decode()) if req.data else {}
    HITS.append((h, body.get("method") if isinstance(body, dict) else "batch"))
    act = SCRIPT.get(h, ("ok", 0x10))
    if act[0] == "http":
        raise urllib.error.HTTPError(req.full_url, act[1], "x", {}, io.BytesIO(act[2].encode()))
    if act[0] == "rpcerr":
        return _Resp({"jsonrpc": "2.0", "id": 1, "error": act[1]})
    if act[0] == "null":
        return _Resp({"jsonrpc": "2.0", "id": 1, "result": None})
    m = body.get("method")
    if m == "trace_transaction":
        return _Resp({"jsonrpc": "2.0", "id": 1, "result": [{"type": "call", "traceAddress": [], "action": {"from": W0, "to": RT, "value": "0x0", "callType": "call"}},
                                                             {"type": "call", "traceAddress": [0], "action": {"from": RT, "to": W0, "value": hex(act[1]), "callType": "call"}}]})
    return _Resp({"jsonrpc": "2.0", "id": 1, "result": frame(RT, W0, act[1])})


bf_engine._open = fake_open
RL = {"code": -32005, "message": "rate-limit exceeded", "data": {"code": "ErrProjectRateLimitRuleExceeded"}}
GAP = {"code": -32603, "message": "transaction not found", "data": {"code": "ErrUpstreamsExhausted"}}
BLK = {"code": -32603, "message": "upstream does not have the requested block yet"}
UEX = {"code": -32603, "message": "request timeout", "data": {"code": "ErrUpstreamsExhausted"}}
GONE = {"code": -32000, "message": "required historical state unavailable (reexec=0)"}


def fresh_gates():
    with bf_engine._GATES_LOCK:
        bf_engine._GATES.clear()


def err_of(url, method="debug_traceTransaction"):
    try:
        bf_engine.rpc_call(url, method, ["0x" + "ab" * 32, {"tracer": "callTracer"}], retries=1, timeout=5)
        return None
    except Exception as e:   # noqa: BLE001
        return e


TG = evm_watch.RpcChainWatcher._trace_gone
SCRIPT[HCN] = ("rpcerr", RL)
fresh_gates()
e = err_of(CN)
check("N4a -32005 rate-limit(HTTP 200) = 속도 제한(http429 · 영구 아님) · 그 호스트 쉼", getattr(e, "kind", None) == "http429" and not TG(e)
      and bf_engine.gate(HCN).resting(), (getattr(e, "kind", None), str(e)))
fresh_gates()
SCRIPT[HCN] = ("http", 429, '{"error":"rate limited","backoff_seconds":7}')
e = err_of(CN)
check("N4b HTTP 429 backoff_seconds 7 = 쉼 7초 · 영구 아님", getattr(e, "kind", None) == "http429" and getattr(e, "retry_after", None) == 7.0 and not TG(e)
      and bf_engine.gate(HCN).pause_until > bf_engine.time.time() + 5, (getattr(e, "retry_after", None)))
fresh_gates()
for raw9, why in ((GAP, "transaction not found + ErrUpstreamsExhausted"), (BLK, "upstream does not have the requested block")):
    SCRIPT[HCN] = ("rpcerr", raw9)
    e = err_of(CN)
    check(f"N4c {why} = 이 제공자 이력 밖(pruned · trace 판정 '영영 못 줌' 후보 — 노드별)", getattr(e, "kind", None) == "pruned" and TG(e), (getattr(e, "kind", None), str(e)))
SCRIPT[HCN] = ("rpcerr", UEX)
e = err_of(CN)
check("N4d ErrUpstreamsExhausted 만(시간 초과 등) = 이력 밖 아님(일시)", getattr(e, "kind", None) != "pruned" and not TG(e), (getattr(e, "kind", None), str(e)))
OTH = "other-node.invalid"
for raw9, why in ((RL, "rate-limit"), (GAP, "transaction not found")):
    SCRIPT[OTH] = ("rpcerr", raw9)
    e = err_of("https://" + OTH + "/rpc")
    check(f"N4e 다른 노드의 같은 문구({why}) = 종전 분류 그대로", getattr(e, "kind", None) == bf_engine.classify_rpc_error(raw9).kind, getattr(e, "kind", None))
SCRIPT.clear()
fresh_gates()

WCFG = {"backfill_months": 0, "chains": {"base": {"discovery": "rpc", "chain_id": 8453, "rpcs": ["http://127.0.0.1:9/rpc"], "conf_depth": 10,
                                                  "blocks_per_day": 43200, "rpc_log_span_caps": {"http://127.0.0.1:9/rpc": 5000}}},
        "wallets": [{"type": "evm", "chain": "base", "address": W0, "label": "w"}]}


class Wr:
    def append(self, rec):
        pass


w = evm_watch.RpcChainWatcher(WCFG, "base", [W0], Wr())
QH, DH = QBASE.split("/")[2], DRPC[0].split("/")[2]
w.trace_rpcs = [CN, QBASE] + DRPC


def run(plan):
    SCRIPT.clear()
    SCRIPT.update(plan)
    HITS.clear()
    fresh_gates()
    w._trace_sick_until = 0.0
    w._trace_nf = 0
    w.__dict__.pop("_trace_slow_until", None)
    snap = {"tx": {"hash": "0x" + "ab" * 32, "block_number": 100}}
    try:
        w._trace_internal("0x" + "ab" * 32, snap)
        return snap, None
    except Exception as e9:   # noqa: BLE001
        return snap, e9


snap, err = run({})
check("N5a 주 제공자 정상 = Chainnodes 1콜로 끝(QuickNode·drpc 0콜) · 내부 이동 채움", err is None and snap.get("internal") == [{"from": RT, "to": W0, "value": "16", "success": True}]
      and [h for h, _m in HITS] == [HCN], (snap, err, HITS))
snap, err = run({HCN: ("rpcerr", RL)})
check("N5b Chainnodes 한도 = 같은 호출에서 QuickNode 로 완료 · drpc 0콜 · Chainnodes 다음 순서 맨 뒤(쉼)", err is None and snap.get("internal")
      and [h for h, _m in HITS] == [HCN, QH] and w._trace_order()[-1] == CN, (snap, err, HITS, w._trace_order()))
snap, err = run({HCN: ("rpcerr", GAP), QH: ("http", 401, "")})
check("N5c Chainnodes 이력 밖 + QuickNode 거부 = drpc 로 완료", err is None and snap.get("internal") and [h for h, _m in HITS][:3] == [HCN, QH, DH], (snap, err, HITS))
snap, err = run({HCN: ("rpcerr", GAP), QH: ("rpcerr", GONE), DH: ("rpcerr", GONE)})
check("N5d 전부 이력 밖·과거 상태 없음 = 종전 '영영 못 줌'(_trace_gone · 종전 drpc 단독과 같은 판정) · 내부 이동 안 채움", err is not None and TG(err)
      and "internal" not in snap, (snap, err))
snap, err = run({HCN: ("rpcerr", GAP), QH: ("rpcerr", GONE), DH: ("http", 408, '{"message":"Request timeout on the free tier"}')})
check("N5e 이력 밖 + 다른 노드 일시(408) = 일시(큐 유지 — 영영 못 줌 아님)", err is not None and not TG(err) and "internal" not in snap, (snap, str(err)))
snap, err = run({HCN: ("null",), QH: ("null",), DH: ("null",)})
check("N5f 결과 null = 빈 내부 이동으로 완료하지 않음(실패)", err is not None and "internal" not in snap, (snap, err))
SCRIPT.clear()

CALLS = []
real = onboarding._node_rpc
onboarding.CN_TEST_WAIT = 0.0
TXH = "0x" + "cd" * 32


def rpc_test(fail=None, cid=8453):
    def f(u, m, p, timeout=15.0):
        CALLS.append((u.split("/")[2], m))
        if fail and fail(m, len(CALLS)):
            raise fail(m, len(CALLS))
        if m == "eth_chainId":
            return hex(cid)
        if m == "eth_blockNumber":
            return hex(30_000_000)
        if m == "eth_getBlockByNumber":
            return {"number": p[0], "transactions": [TXH]}
        if m == "debug_traceTransaction":
            return {"type": "CALL"}
        return "0x0"
    return f


try:
    ss.write_env({NK.ENV_CN: None})
    r = onboarding._dispatch("keys/save", {"group": "chainnodes", "values": {NK.ENV_CN: "https://base-mainnet.chainnodes.org/nope"}})
    check("N6a 형식 이상 = 저장 안 함 · 값 없음", r.get("ok") is False and "nope" not in json.dumps(r, ensure_ascii=False) and not ss.read_env().get(NK.ENV_CN), r)
    CALLS.clear()
    onboarding._node_rpc = rpc_test()
    r = onboarding._dispatch("keys/save", {"group": "chainnodes", "values": {NK.ENV_CN: CN}})
    check("N6b 주소 붙여 넣기 = 키만 저장 · 저장 확인 1콜(Base) · 응답에 키 없음", r.get("ok") is True and ss.read_env().get(NK.ENV_CN) == KEY
          and CALLS == [(HCN, "eth_blockNumber")] and KEY not in json.dumps(r, ensure_ascii=False), (r, CALLS))
    ss.write_env({NK.ENV_CN: None})
    onboarding._node_rpc = rpc_test(fail=lambda m, n: bf_engine.NetError("시험", "http4xx", code=401))
    r = onboarding._dispatch("keys/save", {"group": "chainnodes", "values": {NK.ENV_CN: KEY}})
    check("N6c 거부(401) = 저장 안 함", r.get("ok") is False and not ss.read_env().get(NK.ENV_CN), r)
    onboarding._node_rpc = rpc_test(fail=lambda m, n: RuntimeError("노드가 거절(코드 -32005)"))
    r = onboarding._dispatch("keys/save", {"group": "chainnodes", "values": {NK.ENV_CN: KEY}})
    check("N6d 한도(-32005) = 저장 + 경고", r.get("ok") is True and ss.read_env().get(NK.ENV_CN) == KEY and r.get("note"), r)
    CALLS.clear()
    onboarding._node_rpc = rpc_test()
    r = onboarding._node_test("chainnodes", {})
    check("N6e 연결 시험 = 4콜(체인 번호·최신 블록·공개 블록·callTracer) · Base 만 · 키 없음", r["test"]["ok"] is True
          and [m for _h, m in CALLS] == ["eth_chainId", "eth_blockNumber", "eth_getBlockByNumber", "debug_traceTransaction"]
          and {h for h, _m in CALLS} == {HCN} and KEY not in json.dumps(r, ensure_ascii=False), (r, CALLS))
    CALLS.clear()
    onboarding._node_rpc = rpc_test(fail=lambda m, n: RuntimeError("노드가 거절(코드 -32005)") if n == 4 else None)
    r = onboarding._node_test("chainnodes", {})
    check("N6f trace 단계 한도(냉각 정보 없음) = 다시 안 보냄(4콜) · 한도 안내", r["test"]["ok"] is False and len(CALLS) == 4 and "한도" in r["test"]["detail"], (r, CALLS))
    CALLS.clear()
    onboarding._node_rpc = rpc_test(fail=lambda m, n: RuntimeError("노드가 거절(코드 -32005)") if m == "debug_traceTransaction" else None)
    r = onboarding._node_test("chainnodes", {})
    check("N6g 한도가 계속 = 실패 '한도·속도 제한(키 문제 아님)'", r["test"]["ok"] is False and "한도" in r["test"]["detail"] and "키 문제 아님" in r["test"]["detail"], r)
    onboarding._node_rpc = rpc_test(fail=lambda m, n: bf_engine.NetError("시험", "http4xx", code=403))
    r = onboarding._node_test("chainnodes", {})
    check("N6h 403 = 키 문제", r["test"]["ok"] is False and "키 거부" in r["test"]["detail"], r)
    CALLS.clear()
    onboarding._node_rpc = rpc_test(cid=1)
    r = onboarding._node_test("chainnodes", {})
    check("N6i 다른 체인(체인 번호 1) = 실패 1콜", r["test"]["ok"] is False and "8453" in r["test"]["detail"] and len(CALLS) == 1, (r, CALLS))
    ex9 = onboarding._explorers_status(lambda g: {"name": g["name"], "set": bool(ss.read_env().get(g["fields"][0][0])), "partial": bool(ss.read_env().get(g["fields"][0][0])),
                                                   "fields": [{"key": k, "set": bool(ss.read_env().get(k)), "masked": ss.mask(ss.read_env().get(k, ""))} for k, _l in g["fields"]]})
    check("N6j 설정 화면 = 저장됨 · 가린 값(키 원문 없음)", ex9["chainnodes"]["set"] is True and KEY not in json.dumps(ex9, ensure_ascii=False), ex9.get("chainnodes"))
    r = onboarding._dispatch("keys/delete", {"group": "chainnodes"})
    check("N6k 삭제 = 칸 비움", r.get("ok") is True and not ss.read_env().get(NK.ENV_CN), r)
finally:
    onboarding._node_rpc = real

import time as _tm  # noqa: E402
fresh_gates()
pad9 = "x" * 320
SCRIPT[HCN] = ("http", 429, json.dumps({"error": "rate limited", "detail": pad9, "backoff_seconds": 100}))
e = err_of(CN)
check("N8a 429 본문 300바이트 뒤 backoff_seconds 100 도 읽음", getattr(e, "retry_after", None) == 100.0, (getattr(e, "retry_after", None), len(SCRIPT[HCN][2])))
fresh_gates()
SCRIPT[HCN] = ("http", 429, '{"error":"rate limited","backoff_seconds":300}')
e = err_of(CN)
g9 = bf_engine.gate(HCN)
left9 = g9.pause_until - _tm.time()
check("N8b backoff 300초 = 그대로 쉼(종전 120초 상한 아님) · 서킷 열림(기다리지 않고 0콜)", 290 <= left9 <= 301 and g9.is_open(), (left9, g9.is_open()))
HITS.clear()
if g9.is_open():
    e = err_of(CN)
    check("N8c 냉각 중 호출 = 0콜 · 서킷(미전송 — trace 판정상 '시도 안 함')", HITS == [] and getattr(e, "kind", None) == "circuit", (HITS, getattr(e, "kind", None)))
else:
    check("N8c 냉각 중 호출 = 0콜 · 서킷(미전송 — trace 판정상 '시도 안 함')", False, "서킷 안 열림(수정 전 = 마감 없는 호출이 120초 기다린 뒤 냉각 중에 보냄)")
fresh_gates()
SCRIPT[HCN] = ("rpcerr", {"code": -32005, "message": "rate-limit exceeded", "data": {"code": "ErrProjectRateLimitRuleExceeded", "backoff_seconds": 45}})
e = err_of(CN)
g9 = bf_engine.gate(HCN)
check("N8d 200 본문 -32005 backoff 45 = 45초 쉼 · 서킷", getattr(e, "retry_after", None) == 45.0 and 40 <= g9.pause_until - _tm.time() <= 46 and g9.is_open(),
      (getattr(e, "retry_after", None), g9.pause_until - _tm.time()))
fresh_gates()
SCRIPT[HCN] = ("rpcerr", RL)
e = err_of(CN)
g9 = bf_engine.gate(HCN)
check("N8e 냉각 정보 없는 -32005 = 종전 짧은 쉼(10~20초 · 서킷 아님)", getattr(e, "retry_after", None) is None and 5 <= g9.pause_until - _tm.time() <= 31 and not g9.is_open(),
      (g9.pause_until - _tm.time(), g9.is_open()))
fresh_gates()
OTH9 = "other-429.invalid"


class _H429(urllib.error.HTTPError):
    pass


def open_other(req, timeout):
    if req.host.split(":")[0].lower() == OTH9:
        raise urllib.error.HTTPError(req.full_url, 429, "x", {"Retry-After": "300"}, io.BytesIO(b'{"backoff_seconds":300}'))
    return fake_open(req, timeout)


bf_engine._open = open_other
e = err_of("https://" + OTH9 + "/rpc")
g9 = bf_engine.gate(OTH9)
check("N8f 다른 노드 429 Retry-After 300 = 종전 그대로(120초 상한 · 서킷 아님)", 110 <= g9.pause_until - _tm.time() <= 121 and not g9.is_open(), (g9.pause_until - _tm.time(), g9.is_open()))
bf_engine._open = fake_open
fresh_gates()
SCRIPT.clear()

ss.write_env({NK.ENV_CN: KEY})
onboarding.CN_TEST_WAIT = 0.0
HITS.clear()
SCRIPT[HCN] = ("rpcerr", {"code": -32005, "message": "rate-limit exceeded", "data": {"code": "ErrProjectRateLimitRuleExceeded", "backoff_seconds": 30}})
r = onboarding._node_test("chainnodes", {})
n9 = sum(1 for h, _m in HITS if h == HCN)
check("N9a 시험 중 -32005(냉각 30초) = 다시 안 보냄(1콜) · 실패 문구 = 한도(키 문제 아님) · 그 호스트 냉각", n9 == 1 and r["test"]["ok"] is False and "한도" in r["test"]["detail"]
      and "키 문제 아님" in r["test"]["detail"] and bf_engine.gate(HCN).is_open(), (n9, r, HITS))
HITS.clear()
r = onboarding._node_test("chainnodes", {})
check("N9b 냉각 중 다시 누른 시험 = 0콜 · 한도·냉각 안내", sum(1 for h, _m in HITS if h == HCN) == 0 and r["test"]["ok"] is False and "키 문제 아님" in r["test"]["detail"], (HITS, r))
fresh_gates()
HITS.clear()
SCRIPT[HCN] = ("rpcerr", RL)
r = onboarding._node_test("chainnodes", {})
check("N9c 냉각 정보 없는 -32005 = 다시 안 보냄(1콜)", sum(1 for h, _m in HITS if h == HCN) == 1 and r["test"]["ok"] is False, (HITS, r))
fresh_gates()
HITS.clear()
CNT9 = {"n": 0}


def open_short(req, timeout):
    h = req.host.split(":")[0].lower()
    body = json.loads(req.data.decode())
    HITS.append((h, body.get("method")))
    m = body.get("method")
    if m == "eth_blockNumber" and CNT9["n"] == 0:
        CNT9["n"] += 1
        return _Resp({"jsonrpc": "2.0", "id": 1, "error": {"code": -32005, "message": "rate-limit exceeded", "data": {"backoff_seconds": 0.3}}})
    res = {"eth_chainId": "0x2105", "eth_blockNumber": hex(30_000_000), "eth_getBlockByNumber": {"number": "0x1", "transactions": ["0x" + "cd" * 32]},
           "debug_traceTransaction": {"type": "CALL"}}.get(m)
    return _Resp({"jsonrpc": "2.0", "id": 1, "result": res})


bf_engine._open = open_short
t9 = _tm.time()
r = onboarding._node_test("chainnodes", {})
check("N9d 짧은 냉각(0.3초) = 그만큼 쉬고 1번 다시 → 통과(5콜)", r["test"]["ok"] is True and len(HITS) == 5 and _tm.time() - t9 >= 0.3, (r, HITS))
bf_engine._open = fake_open
fresh_gates()
SCRIPT.clear()
ss.write_env({NK.ENV_CN: None})

js = open(os.path.join(T.ROOT, "web", "v2", "setup.js"), encoding="utf-8").read()
check("N7a 화면 = 설정 칸 안내·NODE_KEYS(QuickNode 앞)·trace 전용 문구 · 필수 표시 없음", "XP_HELP.chainnodes" in js and "'chainnodes', 'quicknode'" in js
      and "n.traceOnly" in js and "Chainnodes 필수" not in js)
check("N7b 설정 칸 = 노드 키 그룹 · 이름 = 무료 Core·Base trace · 필수 아님", "chainnodes" in ss.NODE_GROUPS and "무료 Core" in ss.GROUPS["chainnodes"]["name"]
      and "필수" not in ss.GROUPS["chainnodes"]["name"] and [k for k, _l in ss.GROUPS["chainnodes"]["fields"]] == [NK.ENV_CN])
for fn in (".env.example", "README.md", os.path.join("docs", "API_KEYS.md")):
    tx = T.doc_text(fn)
    check(f"N7c {fn} = TJ_CHAINNODES_KEY · 1,250만 · Base trace", "TJ_CHAINNODES_KEY" in tx and "1,250만" in tx and "trace" in tx)
src9 = open(os.path.join(T.SRC, "onboarding.py"), encoding="utf-8").read()
check("N7d 필수 판정 없음(evmNeedsChainnodes 없음)", "NeedsChainnodes" not in src9 and "needs_chainnodes" not in src9)

T.finish()
