#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import sqlite3
import time
import urllib.parse

os.environ["TJ_HEALTH"] = "0"
KEY = "TESTankrKEY0000000001"
os.environ["TJ_ANKR_KEY"] = KEY
import common

assert T.TMP in common.STATE_DIR
import addr_tier as AT
try:
    import inflow_probe as IP
except ImportError as e:
    T.chk(False, f"inflow_probe 모듈 있음: {e}")
    T.finish()
import evm_watch as EW
import bf_engine as B


def check(n, c, d=""):
    T.chk(bool(c), n, None if c else str(d)[:900])


S = common.STATE_DIR
TRANSFER = IP.TRANSFER
ALCH = "https://eth-mainnet.g.alchemy.com/v2/ALCHtestKEY00000001"
CFG = {"chains": {"eth": {"blockscout": "https://eth.invalid", "rpcs": ["https://eth-detail.invalid"], "rpc_logs": [ALCH], "conf_depth": 12},
                  "polygon": {"blockscout": "https://polygon.invalid", "rpcs": ["https://polygon-detail.invalid"], "conf_depth": 12}}}


def W(i):
    return "0x" + format(0xabc000 + i, "040x")


def pad(w):
    return "0x" + w[2:].rjust(64, "0")


class Net:

    def __init__(self):
        self.calls, self.logs, self.fail, self.heads, self.cid = [], [], {}, {}, {}
        self.cap = {"rpc.ankr.com": 3000}
        self.amax = {"rpc.ankr.com": 1000}

    def __call__(self, url, method, params):
        sp = urllib.parse.urlsplit(url)
        h = sp.hostname
        self.calls.append((h, sp.path, method, params))
        f = self.fail.get((h, method)) or self.fail.get((h, "*"))
        if f:
            raise RuntimeError(f)
        if method == "eth_chainId":
            return hex(self.cid.get(h, 137 if "polygon" in (h + sp.path) else 1))
        if method == "eth_blockNumber":
            return hex(self.heads.get(h, 1200))
        if method == "eth_getLogs":
            q = params[0]
            a, b = int(q["fromBlock"], 16), int(q["toBlock"], 16)
            if b - a + 1 > self.cap.get(h, 10 ** 9):
                raise RuntimeError("block range too large")
            tp = q["topics"]
            pos = 2 if tp[0] == TRANSFER else 3
            ws = tp[pos]
            if len(ws) > self.amax.get(h, 10 ** 9):
                raise RuntimeError("invalid argument 0: exceed max topics")
            t0s = tp[0] if isinstance(tp[0], list) else [tp[0]]
            if b > self.heads.get(h, 1200):
                return []
            out = []
            for lg in self.logs:
                bn = int(lg["blockNumber"], 16)
                t = lg["topics"]
                if a <= bn <= b and t[0] in t0s and len(t) > pos and t[pos] in ws:
                    out.append(lg)
            return out
        raise RuntimeError("unknown method " + method)

    def gl(self, host=None):
        return [c for c in self.calls if c[2] == "eth_getLogs" and (host is None or c[0] == host)]


def log20(to, blk, ca="0x" + "11" * 20, amount=5, removed=False):
    return {"address": ca, "blockNumber": hex(blk), "topics": [TRANSFER, pad("0x" + "99" * 20), pad(to)], "data": hex(amount), "removed": removed}


def log1155(to, blk, ca="0x" + "22" * 20):
    return {"address": ca, "blockNumber": hex(blk), "topics": [IP.T1155_SINGLE, pad("0x" + "98" * 20), pad("0x" + "97" * 20), pad(to)],
            "data": "0x" + "0" * 63 + "1" + "0" * 63 + "3"}


def log721(to, blk, ca="0x" + "33" * 20):
    return {"address": ca, "blockNumber": hex(blk), "topics": [TRANSFER, pad("0x" + "96" * 20), pad(to), "0x" + "0" * 63 + "7"], "data": "0x"}


NOW = time.time()
OLD = NOW - 400 * 86400


def mkbook(ws, chain="eth", rest=(), t0=(), full_blk=1000, path="etherscan", boot=True, cfg=None):
    for f in ("addr_tier_%s.json" % chain, "inflow_%s.json" % chain):
        try:
            os.remove(os.path.join(S, f))
        except OSError:
            pass
    IP._MEM.pop(chain, None)
    tb = AT.TierBook(chain, cfg or CFG, 120, path, ws, incomplete=lambda w: None)
    if boot:
        tb.boot = {"at": int(NOW), "src": "test", "n": 0}
    for w in ws:
        p = tb._p(w)
        p.update(code="eoa", codeAt=int(NOW), full=int(NOW - 300), fullBlk=full_blk, actAt=int(NOW - 60),
                 act={"n": 3, "b": "1", "blk": full_blk, "at": int(NOW - 300)})
        p["sent"] = int(OLD) if w in rest else int(NOW - 3600)
    return tb


class FW:

    def __init__(self, tb, chain="eth"):
        self.chain, self.wallets, self.cursor, self.conf_depth, self._tier, self.fb_info = chain, list(tb.wallets), {}, 12, tb, None
        self.cursor_path = os.path.join(S, f"cursor_evm_{chain}.json")
        self.due = None

    def cycle(self):
        self.due, self.rest = self._tier.due_list(self.wallets)


NET = Net()
IP.RPC_IMPL = NET

W1, W2, W3 = W(1), W(2), W(3)
tb = mkbook([W1, W2, W3], rest=(W1, W2))
NET.heads = {"rpc.ankr.com": 1200, "rpc.mevblocker.io": 1200}
NET.logs = [log20(W1, 1100), log20(W3, 1101)]
t_before = (tb.tier(W1)[0], tb.pairs[W1].get("sent"))
wt = FW(tb)
lp = EW.ChainLoop(CFG, wt, lambda *a: wt, "", None)
lp.step()
p1 = tb.pairs[W1]
check("I1a 쉬는 쌍에 토큰 받음 → 같은 바퀴 due_list 에 그 쌍(탐색기 복구)", wt.due is not None and W1 in wt.due, (wt.due, p1.get("wake")))
check("I1b 깨움 = 'token_in' · 받은 블록 · 활동 아님(sent·계단 그대로)",
      isinstance(p1.get("wake"), dict) and p1["wake"].get("why") == "token_in" and p1["wake"].get("blk") == 1100
      and (tb.tier(W1)[0], p1.get("sent")) == t_before, (p1.get("wake"), tb.tier(W1), t_before))
check("I1c 안 받은 쉬는 쌍 = 쉼(깨움 없음)", W2 not in (wt.due or []) and not tb.pairs[W2].get("wake"), (wt.due, tb.pairs[W2].get("wake")))
check("I1d 지금 주기 쌍은 깨움 표식 없음(어차피 매 주기 탐색기)", not tb.pairs[W3].get("wake"), tb.pairs[W3].get("wake"))
check("I1e 깨움 모양 = 종전 TierBook.wake 와 같음(at·blk·why — 옛 코드로 되돌려도 그대로 읽힘)", set((p1.get("wake") or {}).keys()) == {"at", "blk", "why"}, p1.get("wake"))
st1 = common.read_json(os.path.join(S, "inflow_eth.json"), {})
check("I1f 커서 = 답한 노드 head − 확정 깊이(1188) · 상태 파일", st1.get("blk") == 1188 and st1.get("ok") is True and st1.get("node") == "Ankr", st1)

hosts = [c[0] for c in NET.calls]
check("I2a 첫 노드 = Ankr(/eth/<키>)", NET.gl() and NET.gl()[0][0] == "rpc.ankr.com" and NET.gl()[0][1].startswith("/eth/"), NET.gl()[:1])
check("I2b Alchemy(설정 rpc_logs 에 있어도) 0콜", not any(h and h.endswith("g.alchemy.com") for h in hosts), sorted(set(hosts)))
nl = IP.nodes(CFG, "eth", None)
check("I2c 키 없음 = 공개 logs 노드만(Alchemy·키 노드 빠짐 · 상한 작은 예비 = 뒤)",
      nl and all(k == "pub" for k, *_r in nl) and nl[0][1] == "https://rpc.mevblocker.io" and not any("alchemy" in x[1] for x in nl)
      and nl[-1][1] == "https://eth.drpc.org", [x[1] for x in nl])
nl2 = IP.nodes(CFG, "eth", KEY)
check("I2d 키 있음 = Ankr 먼저(블록 상한 3,000 = nodekeys.SPAN · 주소 1,000) → 공개", nl2[0][0] == "ankr" and nl2[0][2] == 3000 and nl2[0][3] == 1000 and nl2[1][0] == "pub", [x[:1] + x[2:] for x in nl2])
check("I2e Ankr 표 밖 체인 = 공개만", all(x[0] == "pub" for x in IP.nodes({"chains": {"megaeth": {"rpcs": ["https://m.invalid"]}}}, "megaeth", KEY)))
os.environ.pop("TJ_ANKR_KEY")
tb = mkbook([W1, W2], rest=(W1, W2))
NET.calls.clear()
r = IP.tick(CFG, FW(tb), now=NOW)
check("I2f 키 없음 = 첫 getLogs 가 공개 노드(mevblocker)", NET.gl() and NET.gl()[0][0] == "rpc.mevblocker.io" and r and r["woke"] == 1, (NET.gl()[:1], r))
os.environ["TJ_ANKR_KEY"] = KEY

tb = mkbook([W1, W2], rest=(W1, W2))
NET.calls.clear()
NET.heads = {"rpc.ankr.com": 1100, "rpc.mevblocker.io": 1300}
NET.logs = [log20(W2, 1150)]
r = IP.tick(CFG, FW(tb), now=NOW)
st = common.read_json(os.path.join(S, "inflow_eth.json"), {})
check("I3a 뒤처진 노드(head 1100) = 커서 1088 까지만 · 그 너머 받음 아직 안 깨움", st.get("blk") == 1088 and not tb.pairs[W2].get("wake"), (st, r))
NET.heads["rpc.ankr.com"] = 1300
NET.calls.clear()
r = IP.tick(CFG, FW(tb), now=NOW + 601)
g = NET.gl()
check("I3b 다음 바퀴 = 1089 부터(빈틈 없음) → 1150 받음 깨움", g and int(g[0][3][0]["fromBlock"], 16) == 1089 and tb.pairs[W2].get("wake", {}).get("blk") == 1150, (g[:1], r))

tb = mkbook([W1], rest=(W1,))
st0 = {"blk": 1100, "carry": {}}
common.atomic_write_json(os.path.join(S, "inflow_eth.json"), st0)
IP._MEM.pop("eth", None)
NET.heads = {"rpc.ankr.com": 1300, "rpc.mevblocker.io": 1300, "gateway.tenderly.co": 1300, "eth.drpc.org": 1300}
for h in NET.heads:
    NET.fail[(h, "eth_getLogs")] = "HTTP Error 500: boom"
NET.calls.clear()
r = IP.tick(CFG, FW(tb), now=NOW)
st = common.read_json(os.path.join(S, "inflow_eth.json"), {})
check("I4a 모든 노드 실패 = 커서 그대로 · ok 거짓", st.get("blk") == 1100 and st.get("ok") is False, st)
NET.fail.clear()
NET.calls.clear()
check("I4b 실패 뒤 3분 안 = 다시 안 부름", IP.tick(CFG, FW(tb), now=NOW + 100) is None and not NET.calls)
for u in list(IP._MEM["eth"]["cool"]):
    IP._MEM["eth"]["cool"][u] = 0
r = IP.tick(CFG, FW(tb), now=NOW + IP.FAIL_RETRY_SEC + 1)
g = NET.gl()
check("I4c 3분 뒤 = 같은 구간(1101)부터 다시 · 성공", r is not None and g and int(g[0][3][0]["fromBlock"], 16) == 1101
      and common.read_json(os.path.join(S, "inflow_eth.json"), {}).get("blk") == 1288, (g[:1], r))

tb = mkbook([W1], rest=(W1,))
NET.calls.clear()
NET.logs = [log20(W1, 1250)]
NET.fail[("rpc.ankr.com", "*")] = "HTTP Error 403: {'code': -32052, 'message': 'API key is not allowed to access blockchain'}"
r = IP.tick(CFG, FW(tb), now=NOW)
check("I5a Ankr 403 → 같은 바퀴 공개 노드로 받음 탐지(깨움)", r and r["woke"] == 1 and any(c[0] == "rpc.mevblocker.io" for c in NET.gl()), r)
NET.fail.clear()
NET.calls.clear()
IP.tick(CFG, FW(tb), now=NOW + 601)
check("I5b 6시간 안 = Ankr 안 부름(공개 노드)", NET.calls and not any(c[0] == "rpc.ankr.com" for c in NET.calls), [c[0] for c in NET.calls])

con = sqlite3.connect(common.DB_PATH)
con.execute("CREATE TABLE IF NOT EXISTS assets (asset_id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, chain TEXT, address TEXT, symbol TEXT,"
            " decimals INTEGER, confirmed INTEGER NOT NULL DEFAULT 0, hidden INTEGER NOT NULL DEFAULT 0, group_id INTEGER, UNIQUE (kind, chain, address))")
CA_SPAM, CA_OK, CA_NEW = "0x" + "5a" * 20, "0x" + "5b" * 20, "0x" + "5c" * 20
con.execute("INSERT INTO assets(kind, chain, address, symbol, decimals) VALUES ('token','eth',?,?,6)", (CA_SPAM, "U5DТ"))
con.execute("INSERT INTO assets(kind, chain, address, symbol, decimals) VALUES ('token','eth',?,?,18)", (CA_OK, "FOO"))
con.commit()
con.close()
W4, W5, W6, W7, W8 = W(4), W(5), W(6), W(7), W(8)
tb = mkbook([W4, W5, W6, W7, W8], rest=(W4, W5, W6, W7, W8))
NET.calls.clear()
NET.heads = {"rpc.ankr.com": 1300}
NET.logs = [log20(W4, 1200, ca=CA_SPAM), log20(W5, 1200, ca=CA_OK, amount=0), log20(W6, 1200, ca=CA_NEW), log20(W7, 1200, ca=CA_OK),
            log20(W8, 1200, ca=CA_OK, removed=True)]
r = IP.tick(CFG, FW(tb), now=NOW)
wk = {w: bool(tb.pairs[w].get("wake")) for w in (W4, W5, W6, W7, W8)}
check("I6a 사칭 심볼 토큰(원장) = 안 깨움", wk[W4] is False and r["spam"] == 1, (wk, r))
check("I6b 액수 0 ERC-20 = 안 깨움(잔고 안 바뀜)", wk[W5] is False and r["zero"] == 1, (wk, r))
check("I6c 처음 보는 토큰 = 깨움(불확실 = 깨움 쪽) · 보통 토큰 = 깨움", wk[W6] and wk[W7], wk)
check("I6d 지워진(removed) 로그 = 무시", wk[W8] is False, wk)

tb = mkbook([W1], rest=(W1,))
tb.pairs[W1]["wake"] = {"at": 123, "blk": 1050, "why": "nonce"}
NET.logs = [log20(W1, 1100)]
r = IP.tick(CFG, FW(tb), now=NOW)
check("I7 이미 깨운 쌍 = 다시 안 깨움(새로 깨움 0) · 깨운 블록만 1100 으로 · 사유·시각 그대로",
      r["woke"] == 0 and r["ext"] == 1 and tb.pairs[W1]["wake"] == {"at": 123, "blk": 1100, "why": "nonce"}, (r, tb.pairs[W1]["wake"]))

WS = [W(100 + i) for i in range(15)]
tb = mkbook(WS, rest=WS)
NET.logs = [log20(w, 1100 + i) for i, w in enumerate(WS)]
r = IP.tick(CFG, FW(tb), now=NOW)
n1 = sum(1 for w in WS if tb.pairs[w].get("wake"))
check("I8a 한 바퀴 새로 깨움 = WAKE_MAX(10) · 나머지 5 = 이월", r["woke"] == IP.WAKE_MAX == 10 and n1 == 10 and r["carry"] == 5, (r, n1))
NET.logs = []
r = IP.tick(CFG, FW(tb), now=NOW + 601)
check("I8b 다음 바퀴 = 이월분 깨움(새 로그 없어도)", r["woke"] == 5 and all(tb.pairs[w].get("wake") for w in WS), r)

tb = mkbook([W1], rest=(W1,), full_blk=1000)
NET.logs = [log20(W1, 1100)]
IP._mem("eth")["st"]["blk"] = 900
tb.pairs[W1]["fullBlk"] = 1150
r = IP.tick(CFG, FW(tb), now=NOW)
g = NET.gl()
check("I9 탐색기 복구 끝(1150) 아래 = 이미 원장 쪽 → 안 깨움 · 아래 경계 = fullBlk+1 부터 훑음",
      not tb.pairs[W1].get("wake") and g and int(g[-2][3][0]["fromBlock"], 16) >= 1151, (tb.pairs[W1].get("wake"), [x[3][0]["fromBlock"] for x in g[-2:]]))

tb = mkbook([W1], rest=(W1,), full_blk=100)
IP._mem("eth")["st"]["blk"] = 100
NET.heads = {"rpc.ankr.com": 1_000_000}
NET.logs = [log20(W1, 500), log20(W1, 999_000)]
NET.calls.clear()
r = IP.tick(CFG, FW(tb), now=NOW)
g = NET.gl("rpc.ankr.com")
spans = [int(c[3][0]["toBlock"], 16) - int(c[3][0]["fromBlock"], 16) + 1 for c in g]
st = common.read_json(os.path.join(S, "inflow_eth.json"), {})
safe = 1_000_000 - 12
check("I10a 최신 상한(3,000 × 8)만 · 요청마다 3,000 이하 · 묶음 8 × 토픽 2",
      len(g) == 16 and max(spans) <= 3000 and int(g[0][3][0]["fromBlock"], 16) == safe - 24000 + 1 and st.get("blk") == safe, (len(g), max(spans or [0]), st.get("blk")))
check("I10b 최신 받음 = 깨움 · 건너뛴 앞 구간 = 기록(받침 복구 몫)", tb.pairs[W1].get("wake", {}).get("blk") == 999_000 and st.get("skipped") == safe - 24000 - 100,
      (tb.pairs[W1].get("wake"), st.get("skipped")))

MANY = [W(1000 + i) for i in range(1200)]
tb = mkbook(MANY, rest=MANY[:3])
NET.heads = {"rpc.ankr.com": 1300, "rpc.mevblocker.io": 1300}
NET.logs = []
NET.calls.clear()
IP.tick(CFG, FW(tb), now=NOW)
g = NET.gl("rpc.ankr.com")
check("I11a 묶음 크기 = 체인 노드 공통 최소(Ankr 1,000 · 공개 500 → 500 · 1,200 → 3묶음 × 토픽 2 — 진행점을 노드끼리 이어 쓰게 · 코덱스 in474)",
      len(g) == 6 and max(len(c[3][0]["topics"][2] if c[3][0]["topics"][0] == TRANSFER else c[3][0]["topics"][3]) for c in g) == 500, len(g))
os.environ.pop("TJ_ANKR_KEY")
os.remove(os.path.join(S, "inflow_eth.json"))
IP._MEM.pop("eth", None)
NET.calls.clear()
IP.tick(CFG, FW(tb), now=NOW)
g = NET.gl("rpc.mevblocker.io")
check("I11b 공개 노드 = 500개씩(1,200 → 3묶음 × 토픽 2)", len(g) == 6, len(g))
os.environ["TJ_ANKR_KEY"] = KEY

tb = mkbook([W1, W2], rest=(W1, W2))
NET.logs = [log1155(W1, 1150), log721(W2, 1160)]
r = IP.tick(CFG, FW(tb), now=NOW)
check("I12 ERC-1155 TransferSingle(topic3) · ERC-721(토픽 4개) = 깨움", tb.pairs[W1].get("wake", {}).get("blk") == 1150 and tb.pairs[W2].get("wake", {}).get("blk") == 1160, r)
disk = (common.read_json(os.path.join(S, "addr_tier_eth.json"), {}).get("pairs") or {})
check("I12b 깨움 = 커서보다 먼저 장부 파일에(크래시 틈 없음)", (disk.get(W1) or {}).get("wake", {}).get("why") == "token_in"
      and common.read_json(os.path.join(S, "inflow_eth.json"), {}).get("blk") == NET.heads["rpc.ankr.com"] - 12, (disk.get(W1) or {}).get("wake"))

tb = mkbook([W1], rest=(W1,))
NET.logs = []
IP.tick(CFG, FW(tb), now=NOW)
NET.calls.clear()
check("I13a 10분 안 다시 = 0콜", IP.tick(CFG, FW(tb), now=NOW + 300) is None and not NET.calls)
check("I13b 10분 뒤 = 다시", IP.tick(CFG, FW(tb), now=NOW + 601) is not None and NET.calls)
NET.calls.clear()
CFG0 = dict(CFG, addr_tier={"inflow_sec": 0})
tb = mkbook([W1], rest=(W1,))
check("I13c inflow_sec 0 = 끔(0콜)", IP.tick(CFG0, FW(tb), now=NOW) is None and not NET.calls)
check("I13d 설정 값 = 기본 600 · 0 끔 · 30 → 60 · 이상한 값 = 600",
      [IP.settings(c)["sec"] for c in ({}, {"addr_tier": {"inflow_sec": 0}}, {"addr_tier": {"inflow_sec": 30}}, {"addr_tier": {"inflow_sec": "x"}},
                                         {"addr_tier": {"inflow_sec": True}})] == [600, 0, 60, 600, 600])

NET.calls.clear()
tb = mkbook([W1], rest=(W1,), boot=False)
check("I14a 부트스트랩 전(장부 비활성) = 0콜", IP.tick(CFG, FW(tb), now=NOW) is None and not NET.calls)
tb = mkbook([W1], rest=(W1,), path="rpc")
check("I14b RPC 경로 장부(늘 지금 주기) = 0콜", IP.tick(CFG, FW(tb), now=NOW) is None and not NET.calls)
tb = mkbook([W1], rest=())
r = IP.tick(CFG, FW(tb), now=NOW)
check("I14c 쉬는 쌍 없음 = 노드 0콜", r is not None and r["targets"] == 0 and not NET.calls, r)
fw = FW(tb)
fw._tier = None
check("I14d 장부 없는 워처(도구·RPC 대체) = 0콜", IP.tick(CFG, fw, now=NOW) is None and not NET.calls)

tb = mkbook([W1], rest=(W1,))
NET.heads = {"rpc.ankr.com": 1300}
IP.tick(CFG, FW(tb), now=NOW)
IP._MEM.clear()
NET.heads = {"rpc.ankr.com": 1400}
NET.calls.clear()
IP.tick(CFG, FW(tb), now=NOW + 601)
g = NET.gl()
check("I15 재시작 = 상태 파일 커서(1288)에서 이어서(1289부터)", g and int(g[0][3][0]["fromBlock"], 16) == 1289, g[:1])

import nodekeys as NK

B.rpc_day_configure({"rpc_day_limits": {"node_ankr": NK.budget_spec("ankr", NK.plans({})["ankr"])}})


class _Resp:
    status = 200
    headers = {}

    def __init__(self, b):
        self.b = b

    def read(self, n=-1):
        return self.b

    def getheader(self, k, d=None):
        return d

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


SENT = []
BURST = []


def _fake_open(req, timeout):
    body = json.loads(req.data.decode())
    SENT.append((urllib.parse.urlsplit(req.full_url).hostname, body.get("method")))
    BURST.append(B.burst_on())
    m = body.get("method")
    res = "0x1" if m == "eth_chainId" else "0x514" if m == "eth_blockNumber" else []
    return _Resp(json.dumps({"jsonrpc": "2.0", "id": 1, "result": res}).encode())


open_real = B._open
B._open = _fake_open
IP.RPC_IMPL = None
try:
    tb = mkbook([W1], rest=(W1,))
    u0 = (B.rpc_day_status().get("node_ankr") or {}).get("used", 0)
    with B.ledger_burst(True):
        r = IP.tick(CFG, FW(tb), now=NOW)
    used = (B.rpc_day_status().get("node_ankr") or {}).get("used", 0) - u0
    na = sum(1 for h, _m in SENT if h == "rpc.ankr.com")
    check("I16a Ankr 호출 = 노드 하루 장부 node_ankr 에 요청당 200 크레딧", r and na >= 3 and used == 200 * na, (r, na, used, SENT))
    check("I16b 받음 탐지 호출 = 실시간 몫(버스트 아님 — 바깥이 버스트여도)", BURST and not any(BURST), BURST)
finally:
    B._open = open_real
    IP.RPC_IMPL = NET

tb = mkbook([W1], rest=(W1,))
NET.heads = {"rpc.ankr.com": 1300}
NET.fail[("rpc.ankr.com", "eth_getLogs")] = f"HTTP Error 500 at https://rpc.ankr.com/eth/{KEY} key={KEY}"
r = IP.tick(CFG, FW(tb), now=NOW)
NET.fail.clear()
raw = open(os.path.join(S, "inflow_eth.json"), encoding="utf-8").read()
check("I17a 노드 실패 문구에 키가 있어도 상태 파일엔 없음", KEY not in raw and "rpc.ankr.com" not in raw.replace('"Ankr"', ""), raw[:300])
for u in list(IP._MEM["eth"]["cool"]):
    IP._MEM["eth"]["cool"][u] = 0
IP.tick(CFG, FW(tb), now=NOW + 601)
v = IP.web_view(CFG, now=NOW + 700)
row = [x for x in v["rows"] if x["c"] == "eth"]
check("I18a 화면 줄 = 체인 · 마지막 확인 · 노드 'Ankr' · 대상 쌍 수 · 주소 없음", v["sec"] == 600 and row and row[0]["node"] == "Ankr" and row[0]["n"] == 1
      and row[0]["ok"] and KEY not in json.dumps(v) and W1 not in json.dumps(v), v)
f9 = {"at": NOW + 601, "ok": True, "node": "Ankr", "n": 3}
check("I18b 헬스 문구 = '쉬는 지갑 토큰 받음 확인 N분 전(Ankr)' · 대상 0 = 빈 문구",
      IP.health_text(f9, now=NOW + 601 + 300) == "쉬는 지갑 토큰 받음 확인 5분 전(Ankr)" and IP.health_text({"n": 0}) == ""
      and "실패" in IP.health_text(dict(f9, ok=False), now=NOW + 700), IP.health_text(f9, now=NOW + 901))
check("I18c 다른 체인 상태 파일(설정에 없는 체인) = 화면에서 뺌", all(x["c"] in CFG["chains"] for x in IP.web_view(CFG)["rows"]))

import threading

tb = mkbook([W1], rest=(W1,), full_blk=100000)
IP._mem("eth")["st"]["blk"] = 100000
NET.heads = {h: 102412 for h in ("rpc.ankr.com", "rpc.mevblocker.io", "gateway.tenderly.co", "eth.drpc.org")}
NET.logs = [log20(W1, 101000)]
for h in NET.heads:
    NET.fail[(h, "eth_getLogs")] = "HTTP Error 500: boom"
NET.calls.clear()
IP.tick(CFG, FW(tb), now=NOW)
st = common.read_json(os.path.join(S, "inflow_eth.json"), {})
check("R1a 모든 노드 getLogs 실패(마지막 = 작은 상한 예비 노드) = 커서 100000 그대로 · 건너뜀 0", st.get("blk") == 100000 and not st.get("skipped")
      and any(c[0] == "eth.drpc.org" for c in NET.gl()), {k: st.get(k) for k in ("blk", "skipped", "err")})
NET.fail.clear()
for u in list(IP._MEM["eth"]["cool"]):
    IP._MEM["eth"]["cool"][u] = 0
IP.tick(CFG, FW(tb), now=NOW + IP.FAIL_RETRY_SEC + 1)
check("R1b 주 노드 회복 = 그 앞(101000) 입금도 깨움", (tb.pairs[W1].get("wake") or {}).get("blk") == 101000, tb.pairs[W1].get("wake"))

AURL = f"https://rpc.ankr.com/eth/{KEY}"
for msg9, exc9 in (("HTTP Error 403: Forbidden", None), ("blocked", B.NetError("blocked", "http4xx", code=403)),
                   ("HTTP Error 401: Unauthorized", None)):
    tb = mkbook([W1], rest=(W1,))
    NET.heads = {"rpc.ankr.com": 1300, "rpc.mevblocker.io": 1300}

    def _deny(url, method, params, _m=msg9, _e=exc9):
        if urllib.parse.urlsplit(url).hostname == "rpc.ankr.com":
            raise _e if _e is not None else RuntimeError(_m)
        return NET(url, method, params)
    IP.RPC_IMPL = _deny
    IP.tick(CFG, FW(tb), now=NOW)
    IP.RPC_IMPL = NET
    cool9 = IP._MEM["eth"]["cool"].get(AURL, 0) - NOW
    check(f"R1c Ankr '{msg9}' = 거부 → 6시간 쉼", cool9 >= IP.COOL_DENY - 1, cool9)

TOS = []


def _fake_open2(req, timeout):
    body = json.loads(req.data.decode())
    TOS.append((urllib.parse.urlsplit(req.full_url).hostname, float(timeout)))
    m = body.get("method")
    res = "0x1" if m == "eth_chainId" else "0x514" if m == "eth_blockNumber" else []
    return _Resp(json.dumps({"jsonrpc": "2.0", "id": 1, "result": res}).encode())


open_real = B._open
B._open = _fake_open2
IP.RPC_IMPL = None
g9 = B.gate("rpc.ankr.com")
held = 0
while g9.sem.acquire(blocking=False):
    held += 1
try:
    tb = mkbook([W1], rest=(W1,))
    box = {}

    def _run():
        t9 = time.time()
        box["r"] = IP.tick(CFG, FW(tb), now=NOW, deadline=t9 + 1.5)
        box["dt"] = time.time() - t9
    th = threading.Thread(target=_run, daemon=True)
    th.start()
    th.join(6.0)
    alive = th.is_alive()
finally:
    for _i in range(held):
        g9.sem.release()
th.join(30.0)
check("R1d Ankr 동시성 칸이 다 차도 받음 탐지 = 마감(1.5초) 안에 끝(무기한 대기 없음)", held > 0 and not alive and box.get("dt", 99) <= 3.0, (held, alive, box.get("dt")))
TOS.clear()
tb = mkbook([W1], rest=(W1,))
IP.tick(CFG, FW(tb), now=NOW, deadline=time.time() + 1.5)
B._open = open_real
IP.RPC_IMPL = NET
check("R1e 소켓 시간 상한 = 남은 시간 이하(바닥 3초로 늘리지 않음)", TOS and max(t for _h, t in TOS) <= 1.5 + 1e-6, TOS[:6])


CFG32 = json.loads(json.dumps(CFG))
CFG32["chains"]["eth"]["getlogs_max_addrs"] = 32
MANY2 = [W(5000 + i) for i in range(400)]
tb = mkbook(MANY2, rest=MANY2)
NET.heads = {"rpc.ankr.com": 1300}
NET.logs = [log20(MANY2[0], 1250), log20(MANY2[-1], 1260)]


class SlowNet:
    def __call__(self, url, method, params):
        if method == "eth_getLogs":
            time.sleep(0.04)
        return NET(url, method, params)


IP.RPC_IMPL = SlowNet()
NET.calls.clear()
blks, ticks, first_woke = [], 0, None
for k in range(12):
    r = IP.tick(CFG32, FW(tb), now=NOW + k * (IP.FAIL_RETRY_SEC + 1), deadline=time.time() + 0.45)
    ticks += 1
    stk = common.read_json(os.path.join(S, "inflow_eth.json"), {})
    blks.append(stk.get("blk"))
    if first_woke is None:
        first_woke = bool(tb.pairs[MANY2[0]].get("wake"))
    if stk.get("blk") == 1288:
        break
IP.RPC_IMPL = NET
ng = len(NET.gl("rpc.ankr.com"))
check("R2a 마감 안에 못 끝낸 구간 = 다음 바퀴에 이어서 결국 전진(1288) · 같은 묶음 다시 안 부름(26콜 남짓)",
      blks[-1] == 1288 and ticks >= 2 and ng <= 26 + 2, (blks, ticks, ng))
check("R2b 이미 받은 묶음의 받음 = 그 바퀴에 깨움 · 마지막 묶음 지갑도 결국 깨움", first_woke and (tb.pairs[MANY2[-1]].get("wake") or {}).get("blk") == 1260,
      (first_woke, tb.pairs[MANY2[-1]].get("wake")))
check("R2c 마감(시간 상한) = 노드 쉼·구간 반감 아님", IP._MEM["eth"]["cool"].get(f"https://rpc.ankr.com/eth/{KEY}", 0) <= NOW
      and not IP._MEM["eth"]["span"].get(f"https://rpc.ankr.com/eth/{KEY}"), (IP._MEM["eth"]["cool"], IP._MEM["eth"]["span"]))
tb = mkbook([W1, W2], rest=(W1, W2))
st9 = IP._mem("eth")["st"]
st9["blk"] = 1100
st9["scan"] = {"from": 1101, "to": 1288, "next": 1, "shape": "다른모양"}
NET.logs = [log20(W1, 1150)]
NET.calls.clear()
IP.tick(CFG, FW(tb), now=NOW)
g = NET.gl()
check("R2d 지갑 목록·노드 묶음 모양이 바뀐 진행점 = 버리고 그 구간 처음부터(빠짐 없음)", g and g[0][3][0]["topics"][0] == TRANSFER
      and int(g[0][3][0]["fromBlock"], 16) == 1101 and (tb.pairs[W1].get("wake") or {}).get("blk") == 1150, g[:1])

B.rpc_day_configure({"rpc_day_limits": {"node_ankr": NK.budget_spec("ankr", NK.plans({})["ankr"])}})
B._open = _fake_open2
IP.RPC_IMPL = None
held = 0
while g9.sem.acquire(blocking=False):
    held += 1
TOS.clear()
try:
    tb = mkbook([W1], rest=(W1,))
    u0 = (B.rpc_day_status().get("node_ankr") or {}).get("used", 0)
    IP.tick(CFG, FW(tb), now=NOW, deadline=time.time() + 0.6)
    u1 = (B.rpc_day_status().get("node_ankr") or {}).get("used", 0)
finally:
    for _i in range(held):
        g9.sem.release()
    B._open = open_real
    IP.RPC_IMPL = NET
check("R2e 칸 대기 만료(Ankr 전송 0콜) = node_ankr 장부 그대로(예약 환불)", held > 0 and not any(h == "rpc.ankr.com" for h, _t in TOS) and u1 == u0, (held, u0, u1, TOS[:3]))
try:
    B.rpc_day_configure({"rpc_day_limits": {"node_ankr": NK.budget_spec("ankr", NK.plans({})["ankr"])}})
    u0 = (B.rpc_day_status().get("node_ankr") or {}).get("used", 0)
    e9 = None
    try:
        B.rpc_call(f"https://rpc.ankr.com/eth/{KEY}", "eth_blockNumber", [], timeout=5, retries=1, deadline=time.time() - 1, sem_timeout=5)
    except B.NetError as e:
        e9 = e
    u1 = (B.rpc_day_status().get("node_ankr") or {}).get("used", 0)
    check("R2f 마감이 이미 지난 마감 모드 호출 = 0콜 거절 · 장부 그대로", e9 is not None and e9.kind == "budget" and u1 == u0, (repr(e9), u0, u1))
    held = 0
    while g9.sem.acquire(blocking=False):
        held += 1
    try:
        e9 = None
        try:
            B.rpc_call(f"https://rpc.ankr.com/eth/{KEY}", "eth_blockNumber", [], timeout=5, retries=1, deadline=time.time() + 0.3, sem_timeout=0.3)
        except B.NetError as e:
            e9 = e
        u2 = (B.rpc_day_status().get("node_ankr") or {}).get("used", 0)
    finally:
        for _i in range(held):
            g9.sem.release()
    check("R2g 동시성 칸 대기 만료 = budget 거절 · 장부 그대로(예약했다면 환불)", e9 is not None and e9.kind == "budget" and u2 == u0, (repr(e9), u0, u2))
finally:
    pass


tb = mkbook(MANY2, rest=MANY2)
IP._mem("eth")["st"]["blk"] = 1100
NET.heads = {h: 1300 for h in ("rpc.ankr.com", "rpc.mevblocker.io", "gateway.tenderly.co", "eth.drpc.org")}
NET.logs = [log20(MANY2[-1], 1270)]
CNT = {"ankr": 0}


class FlakyNet:

    def __init__(self, ankr_ok):
        self.ankr_ok = ankr_ok

    def __call__(self, url, method, params):
        h = urllib.parse.urlsplit(url).hostname
        if method == "eth_getLogs":
            CNT.setdefault("hosts", []).append(h)
            if h == "rpc.ankr.com":
                CNT["ankr"] += 1
                if CNT["ankr"] > self.ankr_ok:
                    raise RuntimeError("HTTP Error 502: Bad Gateway")
            else:
                raise RuntimeError("HTTP Error 500: boom")
        return NET(url, method, params)


IP.RPC_IMPL = FlakyNet(10)
NET.calls.clear()
IP.tick(CFG32, FW(tb), now=NOW)
sc = dict(IP._mem("eth")["st"].get("scan") or {})
hit_drpc = "eth.drpc.org" in CNT.get("hosts", [])
check("R3a 앞 노드 진행점(10/26)이 예비 노드(이어 쓰지 못함)의 첫 조회 실패로 지워지지 않음", sc.get("next") == 10 and sc.get("from") == 1101 and hit_drpc,
      (sc, hit_drpc))
for u in list(IP._MEM["eth"]["cool"]):
    IP._MEM["eth"]["cool"][u] = 0
IP.RPC_IMPL = NET
NET.calls.clear()
IP.tick(CFG32, FW(tb), now=NOW + IP.FAIL_RETRY_SEC + 1)
ga = NET.gl("rpc.ankr.com")
first_w = ("0x" + ga[0][3][0]["topics"][2][0][-40:]) if ga and ga[0][3][0]["topics"][0] == TRANSFER else None
check("R3b 다음 바퀴 = 진행점(묶음 5 · 조회 10)부터 이어서 그 구간 끝까지 · 마지막 묶음 받음 깨움",
      first_w == MANY2[5 * 32] and common.read_json(os.path.join(S, "inflow_eth.json"), {}).get("blk") == 1288
      and (tb.pairs[MANY2[-1]].get("wake") or {}).get("blk") == 1270, (first_w, len(ga), common.read_json(os.path.join(S, "inflow_eth.json"), {}).get("blk")))

for where in ("eth_blockNumber", "eth_getLogs"):
    tb = mkbook([W1], rest=(W1,))
    NET.heads = {"rpc.ankr.com": 1300, "rpc.mevblocker.io": 1300}
    NET.logs = [log20(W1, 1250)]

    def _busy(url, method, params, _w=where):
        if urllib.parse.urlsplit(url).hostname == "rpc.ankr.com" and method == _w:
            raise B.NetError("budget: rpc.ankr.com 대기 25s > 남은 예산", "budget", host="rpc.ankr.com")
        return NET(url, method, params)
    IP.RPC_IMPL = _busy
    IP.tick(CFG, FW(tb), now=NOW, deadline=time.time() + 15)
    IP.RPC_IMPL = NET
    m9 = IP._MEM["eth"]
    a9 = f"https://rpc.ankr.com/eth/{KEY}"
    check(f"R3c 마감 전 시간 예산 거절({where}) = Ankr 쉼·반감 없음 · 같은 바퀴 다른 노드로 받음 탐지",
          m9["cool"].get(a9, 0) <= NOW and not m9["span"].get(a9) and not m9["addr"].get(a9) and (tb.pairs[W1].get("wake") or {}).get("blk") == 1250,
          (m9["cool"].get(a9), m9["span"].get(a9), tb.pairs[W1].get("wake")))


T.finish()
