#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import urllib.error  # noqa: E402

CFG = {"wallets": [{"type": "evm", "chain": "base", "address": "0x" + "1f" * 20, "label": "시험"},
                   {"type": "bsc_rpc", "address": "0x" + "2e" * 20, "label": "시험2"}],
       "chains": {"base": {"rpc_logs": ["https://pub-base.invalid"], "rpc_log_span_caps": {"https://pub-base.invalid": 5000}}},
       "bsc": {"logs_rpcs": ["https://pub-bsc.invalid"], "detail_rpcs": ["https://pub-bsc-detail.invalid"]}}
CP = os.path.join(T.TMP, "config.json")
with open(CP, "w", encoding="utf-8") as f:
    json.dump(CFG, f)
os.environ["TJ_CONFIG"] = CP
import paths, statefile  # noqa: E402

assert T.TMP in paths.STATE_DIR and T.TMP in paths.ENV_PATH
import bf_engine  # noqa: E402
import evm_watch  # noqa: E402
import nodekeys as NK  # noqa: E402
import onboarding  # noqa: E402
import settings_store as ss, runner_fp  # noqa: E402


def check(n, c, d=""):
    T.chk(bool(c), n, None if c else str(d)[:900])


TOK = "TESTqnOptional0000000001"
TOK2 = "TESTqnOptional0000000002"
ETH = f"https://fake-name.quiknode.pro/{TOK}/"
ETH2 = f"https://other-name.quiknode.pro/{TOK2}/"
QBASE, QBSC = NK.qn_chain_url(ETH, "base"), NK.qn_chain_url(ETH, "bsc")
HB, HS = "fake-name.base-mainnet.quiknode.pro", "fake-name.bsc.quiknode.pro"
DRPC = evm_watch.RpcChainWatcher.TRACE_DEFAULT["base"]


def fresh_gates():
    with bf_engine._GATES_LOCK:
        bf_engine._GATES.clear()


def fresh_cfg():
    return json.loads(json.dumps(CFG))


def applied(env=None):
    c = fresh_cfg()
    NK.apply(c, env=env, settings={})
    return c


def has_qn(c):
    return "quiknode.pro" in json.dumps({"chains": c.get("chains"), "bsc": c.get("bsc")})


def reset_slot():
    NK._QN_SLOT["at"] = -1e18


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


def fake_open(req, timeout):
    h = req.host.split(":")[0].lower() if hasattr(req, "host") else ""
    HITS.append(h)
    act = SCRIPT.get(h, "ok")
    if act == "timeout":
        raise TimeoutError("timed out")
    if isinstance(act, tuple) and act[0] == "http":
        raise urllib.error.HTTPError(req.full_url, act[1], "x", {}, io.BytesIO(act[2].encode()))
    if isinstance(act, tuple) and act[0] == "json":
        return _Resp(act[1])
    return _Resp({"jsonrpc": "2.0", "id": 1, "result": {"type": "CALL", "from": "0x" + "11" * 20, "to": "0x" + "22" * 20}})


bf_engine._open = fake_open


def call(url):
    try:
        bf_engine.rpc_call(url, "debug_traceTransaction", ["0x" + "ab" * 32, {"tracer": "callTracer"}], retries=1, timeout=5)
        return "ok"
    except Exception as e:   # noqa: BLE001
        return getattr(e, "kind", type(e).__name__)


def rec():
    return statefile.read_json(NK._qn_path(), None)


def set_first(host, ago):
    r = rec()
    r["hosts"][host]["first"] = int(r["hosts"][host]["first"]) - ago
    statefile.atomic_write_json(NK._qn_path(), r)


def fps():
    cfg9 = ss.load_config_quiet()
    return {u: runner_fp.unit_inputs(u, cfg9)[2] for u in ("evm", "bsc", "core", "web")}


for nm9, env9 in (("키 없음", {}), ("Ankr 키만", {NK.ENV_ANKR: "TESTankr0000000000000001"})):
    c = applied(env9)
    nd = evm_watch.rpc_nodes(c, "base")
    check(f"O1 {nm9} = Base trace 내장 drpc(종전 그대로) · QuickNode 없음", nd["trace"] == DRPC and not has_qn(c) and "trace_rpcs" not in c["chains"]["base"],
          (nd["trace"], c["chains"]["base"]))
check("O1c 키 없음 = 거부 표식 없어도·있어도 urls 에 QuickNode 없음", not any(p == "quicknode" for v in NK.urls({}).values() for p, _u in v))

ss.write_env({NK.ENV_QN: ETH})
reset_slot()
c = applied()
nd = evm_watch.rpc_nodes(c, "base")
check("O2 키 있음 = Base trace QuickNode 먼저(뒤 기본 drpc) · BSC·Base 상태 예비 · 로그 풀엔 없음", nd["trace"] == [QBASE] + DRPC and c["chains"]["base"]["archive_rpcs"][-1] == QBASE
      and c["bsc"]["archive_rpcs"][-1] == QBSC and QBASE not in c["chains"]["base"]["rpc_logs"] and QBSC not in c["bsc"]["logs_rpcs"], (nd["trace"], c))
FP0 = fps()

NK.QN_REJECT_SEC = 120
SCRIPT[HB] = ("http", 401, '{"error":"unauthorized"}')
r1 = [call(QBASE) for _ in range(3)]
check("O3a 401 = 그 콜은 실패(http4xx) · 3번이어도 2분 안이면 아직 안 뺌", r1 == ["http4xx"] * 3 and rec()["hosts"][HB]["n"] == 3
      and not rec()["hosts"][HB].get("off") and NK.qn_rejected() is None, (r1, rec()))
set_first(HB, 200)
call(QBASE)
r9 = rec()
check("O3b 첫 거부부터 2분 넘게 성공 없이 계속 = 그 호스트 뺌(표식 — 비밀 없음)", r9["hosts"][HB].get("off") is True and r9["hosts"][HB]["code"] == 401
      and TOK not in json.dumps(r9) and r9["kh"] == NK.qn_kh(), r9)
c = applied()
nd = evm_watch.rpc_nodes(c, "base")
check("O3c Base = 키 없음 경로(trace 내장 drpc · 상태 예비 없음) · BSC 는 QuickNode 그대로(호스트별)",
      nd["trace"] == DRPC and QBASE not in json.dumps(c["chains"]["base"]) and "trace_rpcs" not in c["chains"]["base"]
      and c["bsc"]["archive_rpcs"][-1] == QBSC, (nd["trace"], c["chains"]["base"], c["bsc"]))
FP1 = fps()
check("O3d 재시작 지문 = tj-evm 만 바뀜(tj-bsc·core·web 그대로)", FP1["evm"] != FP0["evm"] and all(FP1[u] == FP0[u] for u in ("bsc", "core", "web")), (FP0, FP1))
st = NK.status()["quicknode"]
check("O3e 화면 상태 = 키 거부됨(날짜·코드·체인 Base) · 쓰는 체인에서 Base 빠짐 · 키·주소 없음",
      st.get("rejected", {}).get("chains") == ["base"] and st["rejected"]["code"] == 401 and st["rejected"]["since"] > 0 and st["chains"] == ["bsc"]
      and TOK not in json.dumps(st) and "quiknode.pro" not in json.dumps(st), st)
check("O3f 같은 키를 세는 연결 테스트용 주소(all_qn)는 그대로", [u for p, u in NK.urls(all_qn=True)["base"] if p == "quicknode"] == [QBASE])
check("O3g 키 없음 상태 칸엔 rejected 없음(종전 모양)", "rejected" not in NK.status(env={})["quicknode"])
SCRIPT[HS] = ("http", 403, "forbidden")
for _ in range(3):
    call(QBSC)
set_first(HS, 200)
call(QBSC)
c = applied()
FP2 = fps()
check("O3h BSC 도 계속 거부 = BSC 상태 예비에서도 뺌 · tj-bsc 지문 바뀜 · 상태 chains BSC·Base", QBSC not in json.dumps(c["bsc"]) and FP2["bsc"] != FP1["bsc"]
      and NK.status()["quicknode"]["rejected"]["chains"] == ["bsc", "base"] and FP2["core"] == FP0["core"], (c["bsc"], NK.status()["quicknode"].get("rejected")))

SCRIPT[HB] = "ok"
check("O6a 그 호스트 성공 1번", call(QBASE) == "ok")
c = applied()
FP3 = fps()
check("O6b Base 회복 = 다시 QuickNode(trace) · tj-evm 지문 원래대로 · BSC 는 아직 빠짐", evm_watch.rpc_nodes(c, "base")["trace"] == [QBASE] + DRPC
      and FP3["evm"] == FP0["evm"] and QBSC not in json.dumps(c["bsc"]) and HB not in rec()["hosts"], (FP0, FP3, rec()))
ss.write_env({NK.ENV_QN: ETH2})
reset_slot()
c = applied()
check("O6c 키를 바꾸면 옛 키 표식 무시 = 새 키 QuickNode 사용 · 지문 route 칸 없음", NK.qn_rejected() is None and NK.route_fp("bsc") == ""
      and c["bsc"]["archive_rpcs"][-1] == NK.qn_chain_url(ETH2, "bsc"), c["bsc"])
ss.write_env({NK.ENV_QN: ETH})
reset_slot()
NK.qn_reject_clear()
SCRIPT.clear()

SCRIPT[HB] = ("http", 401, "")
call(QBASE)
call(QBASE)
SCRIPT[HB] = "ok"
call(QBASE)
check("O4a 거부 2번 뒤 성공 1번 = 계수 지움(파일 없음)", rec() is None, rec())
for act9, why in ((("http", 429, '{"error":{"code":-32007,"message":"15/second request limit reached"}}'), "초당 한도 429"),
                  ("timeout", "시간 초과"), (("http", 500, "oops"), "5xx"),
                  (("json", {"jsonrpc": "2.0", "id": 1, "error": {"code": 3, "message": "execution reverted"}}), "실행 오류(200)")):
    SCRIPT[HB] = act9
    for _ in range(4):
        fresh_gates()
        call(QBASE)
    fresh_gates()
    check(f"O4b {why} = 셈 안 함", rec() is None, rec())
SCRIPT["my-own.base-mainnet.quiknode.pro"] = ("http", 401, "")
for _ in range(4):
    call("https://my-own.base-mainnet.quiknode.pro/TESTqnOther0000000009/")
check("O4c 이용자가 config 에 직접 넣은 다른 QuickNode 주소 = 셈 안 함(그 주소는 이용자 선택 그대로)", rec() is None, rec())
SCRIPT.clear()

for act9, why in ((("json", {"jsonrpc": "2.0", "id": 1, "error": {"code": -32001, "message": "Your account has run out of API credits"}}), "200 본문 error"),
                  (("http", 429, '{"error":"monthly credit limit exceeded"}'), "429 본문 크레딧 초과"),
                  (("http", 402, "Payment Required"), "402 결제 필요")):
    NK.qn_reject_clear()
    SCRIPT[HB] = act9
    fresh_gates()
    got9 = call(QBASE)
    check(f"O5 {why} = 거부로 셈", (rec() or {}).get("hosts", {}).get(HB, {}).get("n") == 1, (got9, rec(), NK._qn_slot(), HITS[-3:]))
NK.qn_reject_clear()
SCRIPT.clear()

NK.QN_REJECT_SEC = 0
SCRIPT[HB] = ("http", 401, "")
for _ in range(3):
    call(QBASE)
check("O7a (준비) Base 뺌", NK.qn_rejected() is not None)
TXH = "0x" + "ab" * 32


def rpc_test(u, m, p, timeout=15.0):
    if m == "eth_chainId":
        return hex(8453)
    if m == "eth_blockNumber":
        return hex(50_000_000)
    if m == "eth_getBlockByNumber":
        return {"number": p[0], "transactions": [TXH]}
    if m == "debug_traceTransaction":
        return {"type": "CALL"}
    return "0x0"


real = onboarding._node_rpc
try:
    def rpc_rej(u, m, p, timeout=15.0):
        raise bf_engine.NetError("시험 오류", "http4xx", code=401)
    onboarding._node_rpc = rpc_rej
    r = onboarding._node_test("quicknode", {})
    check("O7b 빠진 키도 시험함 · 거부 = 체험 끝 안내(키·주소 없음) · 표식 그대로", r["test"]["ok"] is False and "체험" in r["test"]["detail"]
          and TOK not in json.dumps(r, ensure_ascii=False) and NK.qn_rejected() is not None, r)
    onboarding._node_rpc = rpc_test
    r = onboarding._node_test("quicknode", {})
    check("O7c 저장된 키 시험 통과 = 표식 지움 · '다시 써요' 안내", r["test"]["ok"] is True and NK.qn_rejected() is None and rec() is None
          and "다시" in r["test"]["detail"], r)
    for _ in range(3):
        call(QBASE)
    r = onboarding._node_test("quicknode", {NK.ENV_QN: ETH2})
    check("O7d 다른(새) 주소 시험 통과 = 저장된 키 표식은 그대로(저장 때 정리)", r["test"]["ok"] is True and NK.qn_rejected() is not None, r)
    r = onboarding._dispatch("keys/save", {"group": "quicknode", "values": {NK.ENV_QN: ETH}})
    check("O7e 같은 키 다시 저장 + 저장 확인 통과(유료로 바꿈) = 표식 지움", r.get("ok") is True and rec() is None, (r, rec()))
    for _ in range(3):
        call(QBASE)
    r = onboarding._dispatch("keys/delete", {"group": "quicknode"})
    check("O7f 삭제 = 표식 지움 · 키 없음 = 종전 경로", r.get("ok") is True and rec() is None and evm_watch.rpc_nodes(applied(), "base")["trace"] == DRPC, (r, rec()))

    def rpc_402(u, m, p, timeout=15.0):
        raise bf_engine.NetError("시험 오류", "http4xx", code=402)
    onboarding._node_rpc = rpc_402
    r = onboarding._dispatch("keys/save", {"group": "quicknode", "values": {NK.ENV_QN: ETH}})
    check("O7g 저장 확인 402(결제 필요 — 체험 끝) = 저장 안 함 · 체험 안내", r.get("ok") is False and not ss.read_env().get(NK.ENV_QN) and "체험" in r.get("error", ""), r)
finally:
    onboarding._node_rpc = real
    NK.QN_REJECT_SEC = 120
    SCRIPT.clear()

js = open(os.path.join(T.ROOT, "web", "v2", "setup.js"), encoding="utf-8").read()
i9 = js.index("XP_HELP.quicknode")
qh = js[i9:js.index("\n", i9)]
check("O8a 안내 = 유료나 1개월 무료 체험 · 상시 무료 문구 없음 · 필수 없음", "1개월 무료 체험" in qh and "무료 플랜" not in qh and "필수" not in qh, qh)
check("O8b 요금제 칩 '1개월 체험' · '키 거부됨' 표시 · QuickNode 필수 알약 없음", "'1개월 체험'" in js and "키 거부됨(체험 끝났을 수 있음)" in js and "pill('w', '키 거부됨')" in js
      and "k === 'quicknode'" in js and "QuickNode 필수" not in js)
nm9 = ss.GROUPS["quicknode"]["name"]
check("O8c 설정 칸 이름 = 유료나 1개월 무료 체험 · '무료 플랜' 없음", "1개월 무료 체험" in nm9 and "무료 플랜" not in nm9 and "필수" not in nm9, nm9)
for fn in (".env.example", "README.md", os.path.join("docs", "API_KEYS.md")):
    tx = T.doc_text(fn)
    check(f"O8d {fn} = QuickNode 1개월 무료 체험·상시 무료 없음(무료 플랜도 됨 문구 없음)", "1개월 무료 체험" in tx and "무료 플랜도 됨" not in tx)
src9 = open(os.path.join(T.SRC, "onboarding.py"), encoding="utf-8").read()
check("O8e 설정 상태에 QuickNode 필수 판정 없음(needs_quicknode·evmNeedsQuickNode 없음)", "needs_quicknode" not in src9 and "NeedsQuick" not in src9 and "NeedsQuick" not in js)

T.finish()
