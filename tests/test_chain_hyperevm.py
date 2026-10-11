#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _ingest

import json
import os
import time

import common
import chaincatalog as CC

chk = T.chk
W1 = "0x" + "a1" * 20
W2 = "0x" + "a2" * 20
SYS = "0x2222222222222222222222222222222222222222"
SYS_TOK = "0x20000000000000000000000000000000000000c8"
WHYPE = "0x5555555555555555555555555555555555555555"
E18 = 10 ** 18

blk = CC.CATALOG.get("hyperevm") or {}
chk(CC.is_block("hyperevm") and blk.get("etherscan_chainid") == 999 and blk.get("chain_id") == 999 and not blk.get("blockscout")
    and not blk.get("discovery") and blk.get("rpc_fallback") is False and blk.get("rpcs") == ["https://rpc.hyperliquid.xyz/evm"]
    and blk.get("rpc_log_span_caps") == {"https://rpc.hyperliquid.xyz/evm": 1000},
    "A hyperevm = 수집 블록(이더스캔 chainid 999 · 블록스카웃 없음 · RPC 전용 아님 · RPC 대체 끔 · 공개 RPC 1개 · getLogs 상한 1,000)", blk)
b0, why0 = CC.block_for("hyperevm", False, {"getLogsSpan": 100, "blocksPerSec": 1.017, "windowCalls": 263610, "autoOk": False})
chk(why0 == "catalog" and b0 and b0.get("_auto") == "catalog" and not (set(b0) & set(CC.TABLE_KEYS)) and b0.get("etherscan_chainid") == 999,
    "A block_for = 카탈로그(창 백필 비용 과다 실측이어도 · 표 칸 없음)", (why0, sorted(b0 or {})))
chk(common.EXTRA_CHAINS.get("hyperevm") == ("HyperEVM", "HYPE", 999, WHYPE) and CC.native_of("hyperevm") == ("HYPE", WHYPE),
    "A 네이티브 HYPE · 랩드 WHYPE(온체인 symbol·decimals 확인값)", common.EXTRA_CHAINS.get("hyperevm"))
chk([k for k, v in CC.blocks().items() if CC.es_only(v)] == ["hyperevm"] and not CC.es_only({"etherscan_chainid": 1, "blockscout": "https://x.invalid"})
    and not CC.es_only({"etherscan_chainid": 1}) and not CC.es_only({"etherscan_chainid": 1, "discovery": "rpc", "rpc_fallback": False}),
    "A 이더스캔 전용 판정 = hyperevm 하나(블록스카웃 있음·RPC 대체 허용·RPC 전용 체인은 아님)")
import pricing
import candles
chk(pricing.GT_NETWORK.get("hyperevm") == "hyperevm" and pricing.DS_CHAIN.get("hyperevm") == "hyperevm" and candles.KNOWN_CG_ID.get("HYPE") == "hyperliquid"
    and candles.GT_NETWORK.get("hyperevm") == "hyperevm" and candles.CG_PLATFORM.get("hyperevm") == "hyperevm",
    "A 시세 표: 게코터미널·덱스스크리너 망 id = hyperevm(장기 곡선 표도) · 코인게코 id HYPE = hyperliquid · 코인게코 플랫폼 hyperevm")
al = json.load(open(os.path.join(T.ROOT, "seed", "coverage", "api_limits.json"), encoding="utf-8"))
chk([c for c in al.get("chains") or [] if "hyperevm" in (c.get("match") or [])], "A 수집 한계 표에 HyperEVM 행(설정 › 수집 한계 · 공개 문서)")

CFG = {"chains": {"eth": {"blockscout": "https://eth.invalid", "etherscan_chainid": 1, "rpcs": ["https://eth-rpc.invalid"]},
                  "base": {"discovery": "rpc", "rpcs": ["https://base-rpc.invalid"]}},
       "wallets": [{"type": "evm", "chain": "eth", "address": W1, "label": "가"}, {"type": "evm", "chain": "eth", "address": W2, "label": "나"}],
       "native_symbol": {"eth": "ETH", "base": "ETH"}, "backfill_months": 5,
       "chain_sweep": {"enabled": True, "auto_enable": True, "pace_sec": 0}}
with open(common.CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump(CFG, f)
gate = {"version": 1, "chains": {}, "pairs": {
    f"hyperevm:{W1}": {"active": True, "since_block": None},
    f"hyperevm:{W2}": {"active": True, "since_block": 123, "since_state": [0, "0"]},
    f"opbnb:{W1}": {"active": True, "since_block": None},
    f"celo:{W1}": {"active": True, "since_block": None}}}
speed = {"version": 1, "chains": {"hyperevm": {"getLogsSpan": 100, "blocksPerSec": 1.017, "windowCalls": 263610, "autoOk": False},
                                  "opbnb": {"getLogsSpan": 10000, "blocksPerSec": 4.0, "windowCalls": 10370, "autoOk": False},
                                  "celo": {"getLogsSpan": 1000, "blocksPerSec": 1.0, "windowCalls": 25920, "autoOk": False}}}
common.atomic_write_json(common.ACTIVITY_GATE_PATH, gate)
common.atomic_write_json(common.BACKFILL_SPEED_PATH, speed)
CUR = os.path.join(common.STATE_DIR, "cursor_evm_hyperevm.json")


def set_key(v):
    if v is None:
        if os.path.exists(common.ENV_PATH):
            os.remove(common.ENV_PATH)
    else:
        with open(common.ENV_PATH, "w", encoding="utf-8") as f:
            f.write(f"TJ_ETHERSCAN_KEY={v}\n")


set_key(None)
c0 = common.load_config()
d0 = {d["chain"]: d for d in common.gate_decisions(c0, gate, speed)}
chk("hyperevm" not in c0["chains"] and not [w for w in c0["wallets"] if w.get("chain") == "hyperevm"],
    "B 이더스캔 키 없음 = HyperEVM 안 켬(공개 RPC 로 창 백필 안 함)", sorted(c0["chains"]))
chk(d0["hyperevm"]["reason"].startswith("이더스캔 무료 키 필요") and not d0["hyperevm"]["ok"], "B 키 없음 사유 = '이더스캔 무료 키 필요 …'(경고 — 할 일)",
    d0["hyperevm"]["reason"])
chk(d0["opbnb"]["reason"].startswith("창 백필 비용 과다") and d0["celo"]["reason"].startswith("창 백필 비용 과다"),
    "B opBNB·Celo = 종전 그대로(카탈로그 아님 — 창 백필 비용 과다)", (d0["opbnb"]["reason"], d0["celo"]["reason"]))
import settings_store
fp_evm0 = settings_store.unit_inputs("evm", c0, {})[2]
fp_core0 = settings_store.unit_inputs("core", c0, {})[2]

set_key("SYNTHKEY0123")
c1 = common.load_config()
hb = c1["chains"].get("hyperevm") or {}
chk(hb.get("etherscan_chainid") == 999 and hb.get("_auto") == "catalog" and hb.get("rpc_fallback") is False and "alchemy" not in hb,
    "B 키 있음 = HyperEVM 켬(카탈로그 블록 · 이더스캔 경로)", hb)
auto9 = sorted((w["address"], w.get("since_block")) for w in c1["wallets"] if w.get("chain") == "hyperevm")
chk(auto9 == [(W1, None), (W2, 123)], "B 자동 지갑 행 = 활동 쌍 둘(이력 있는 쌍 · 새 활동 쌍 since_block 그대로)", auto9)
chk((c1.get("native_symbol") or {}).get("hyperevm") == "HYPE" and (c1.get("wrapped_native") or {}).get("hyperevm") == WHYPE,
    "B 설정 해석: 네이티브 심볼 HYPE · 랩드 WHYPE 채움(가짜 'HYPEREVM' 심볼 기장 방지)")
chk("opbnb" not in c1["chains"] and "celo" not in c1["chains"], "B 키가 있어도 opBNB·Celo 는 안 켬(이번 판 제외)")
chk(settings_store.unit_inputs("evm", c1, {})[2] != fp_evm0 and settings_store.unit_inputs("core", c1, {})[2] != fp_core0,
    "B 키 저장 → 지갑 목록이 바뀜 → 수집기·원장 입력 지문 바뀜(유닛 러너가 다시 띄움 = 자동으로 켜짐)")
import rabby
res9 = rabby.chain_resolver(c1, {})
chk(res9("hyper") == "hyperevm" and (W1, "hyperevm") in rabby.wallet_chains(c1) and rabby.chain_resolver(c0, {})("hyper") is None,
    "B Rabby: 켠 뒤 HyperEVM = 봇 체인(Rabby 잔고를 또 더하지 않음) · 켜기 전 = Rabby 기준(종전)")

set_key(None)
common.atomic_write_json(CUR, {W1: 1000, "_synced_at": 1})
c2 = common.load_config()
chk("hyperevm" in c2["chains"] and sorted(w["address"] for w in c2["wallets"] if w.get("chain") == "hyperevm") == [W1, W2],
    "B 이미 수집한 체인(커서 있음) = 키가 빠져도 켠 채로(꺼지면 Rabby 가 같은 잔고를 또 더함)", sorted(c2["chains"]))
with open(CUR, "w", encoding="utf-8") as f:
    f.write("{깨짐")
c3 = common.load_config()
chk("hyperevm" in c3["chains"], "B 커서 파일 손상 = 수집한 것으로(켠 채로 — 안전 쪽)")
common.atomic_write_json(CUR, {"_synced_at": 1})
c4 = common.load_config()
chk("hyperevm" not in c4["chains"], "B 커서에 지갑 기록 없음(표식만) = 수집 안 한 것 — 키 없으면 안 켬")
os.remove(CUR)

import evm_watch


class Wr:
    def __init__(self):
        self.recs = []

    def append(self, r):
        self.recs.append(json.loads(json.dumps(r)))


set_key("SYNTHKEY0123")
c1 = common.load_config()
w9 = evm_watch.build_watcher(c1, "hyperevm", [W1, W2], Wr(), "SYNTHKEY0123")
chk(type(w9).__name__ == "EtherscanWatcher" and w9.cid == 999, "C 키 있음 = 이더스캔 워처(chainid 999)", type(w9).__name__)
chk("hyperevm" not in (common.read_json(os.path.join(common.STATE_DIR, evm_watch.EVM_ROUTE_FILE), {}) or {}),
    "C 경로 순서 파일(evm_route)에 hyperevm 을 고정하지 않음(이더스캔 전용 — RPC 우선 판정 대상 아님)")
u0 = evm_watch._ES_DAILY["until"]
evm_watch._ES_DAILY["until"] = time.time() + 3600
try:
    w10 = evm_watch.build_watcher(c1, "hyperevm", [W1, W2], Wr(), "SYNTHKEY0123")
    ok10, e10 = type(w10).__name__ == "EtherscanWatcher", type(w10).__name__
except (Exception, SystemExit) as e:
    ok10, e10 = False, f"{type(e).__name__}: {e}"
chk(ok10, "C 하루 한도 쉼 창 안 기동 = 이더스캔 워처 그대로(블록스카웃 워처 KeyError·RPC 대체 아님 — 창 안 호출은 0콜 거절)", e10)
if ok10:
    nw10 = evm_watch.es_fallback_watcher(c1, w10, Wr(), daily=True)
    chk(nw10 is w10 and not evm_watch.rpcfb_get("hyperevm").get("active"), "C 하루 한도 폴백 = 같은 워처(기다림 · RPC 대체 기록 없음)")
evm_watch._ES_DAILY["until"] = u0
dm_p = os.path.join(common.STATE_DIR, "pending_dm.jsonl")
dm_c = lambda: sum(1 for _ in open(dm_p, encoding="utf-8")) if os.path.exists(dm_p) else 0
dm_a = dm_c()
nw11 = evm_watch.es_fallback_watcher(c1, w9, Wr(), daily=False, why="es_fail")
chk(nw11 is w9 and evm_watch.rpcfb_enter(c1, "hyperevm", [W1], Wr(), "etherscan", "es_fail") is None and dm_c() == dm_a,
    "C 이더스캔 연속 실패 폴백 = 같은 워처(오류 표시하고 기다림 · RPC 대체 수집기 안 만듦 · '블록스카웃 미구성' DM 되풀이 없음)", dm_c() - dm_a)
cr9 = dict(c1, chains=dict(c1["chains"], hyperevm=dict(c1["chains"]["hyperevm"], rpc_logs=["https://rpc.hyperliquid.xyz/evm"])))
w12 = evm_watch.build_watcher(cr9, "hyperevm", [W1], Wr(), "")
chk(type(w12).__name__ == "EtherscanWatcher", "C 설정에 rpc_logs 가 있어도 RPC 우선 본선을 만들지 않음(이더스캔 전용)", type(w12).__name__)
n_net0 = len(T.NET_TRIES)
w13 = evm_watch.build_watcher(c1, "hyperevm", [W1], Wr(), "")
dm_n0 = dm_c()
lp = evm_watch.ChainLoop(c1, w13, lambda cf, ch, ad: evm_watch.build_watcher(cf, ch, ad, Wr(), ""), "", Wr())
alive = lp.step()
dm_n1 = dm_c()
hs9 = (common.read_json(os.path.join(common.STATE_DIR, "health", "evm.json"), {}) or {})
chk(type(w13).__name__ == "EtherscanWatcher" and alive is False and "hyperevm" in evm_watch.DISABLED_CHAINS and len(T.NET_TRIES) == n_net0
    and dm_n1 == dm_n0, "C 키 없음 = 그 체인만 멈춤(ChainDisabled · 0콜 · DM 없음)", (type(w13).__name__, alive, len(T.NET_TRIES) - n_net0, dm_n1 - dm_n0))
chk("이더스캔 무료 키" in json.dumps(hs9, ensure_ascii=False), "C 멈춘 사유가 헬스에 남음('이더스캔 무료 키 …')")

CFGD = {"chains": dict(_ingest.CFG["chains"], hyperevm={k: v for k, v in b0.items() if k != "_auto"}),
        "wallets": [{"type": "evm", "chain": "hyperevm", "address": W1}], "native_symbol": {"eth": "ETH", "base": "ETH"}, "backfill_months": 5}
with open(common.CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump(CFGD, f)
cd = common.load_config()
chk(cd["native_symbol"].get("hyperevm") == "HYPE" and cd["wrapped_native"].get("hyperevm") == WHYPE, "D 설정 체인(명시)도 네이티브 HYPE·랩드 WHYPE")
OTHER, TKN = "0x" + "b5" * 20, "0x" + "c3" * 20
H = ["0x" + (f"{i:x}" * 64)[:64] for i in range(1, 6)]
BH = "0x" + "d" * 64
TS = 1_790_000_000
GP = 100_000_000
TXL = [{"hash": H[0], "blockNumber": "150", "from": W1, "to": SYS, "value": str(E18 // 2), "gasUsed": "22469", "gasPrice": str(GP),
        "txreceipt_status": "1", "isError": "0", "input": "0x", "timeStamp": str(TS), "blockHash": BH},
       {"hash": H[1], "blockNumber": "160", "from": SYS, "to": W1, "value": str(E18), "gasUsed": "0", "gasPrice": "0",
        "txreceipt_status": "1", "isError": "0", "input": "0x", "timeStamp": str(TS + 10), "blockHash": BH},
       {"hash": H[3], "blockNumber": "180", "from": W1, "to": OTHER, "value": str(E18 // 5), "gasUsed": "21000", "gasPrice": str(GP),
        "txreceipt_status": "1", "isError": "0", "input": "0x", "timeStamp": str(TS + 30), "blockHash": BH}]
TTL = [{"hash": H[2], "blockNumber": "170", "from": SYS_TOK, "to": W1, "contractAddress": TKN, "value": str(100 * 10 ** 6), "tokenDecimal": "6",
        "tokenSymbol": "TKN", "tokenName": "Token", "gasPrice": "0", "gasUsed": "0", "timeStamp": str(TS + 20), "blockHash": BH}]
CALLS = []


def fake_es(params):
    a, s, e = params.get("action"), int(params.get("startblock") or 0), int(params.get("endblock") or 10 ** 9)
    CALLS.append(a)
    rows = {"txlist": TXL, "tokentx": TTL, "txlistinternal": []}.get(a, [])
    return [r for r in rows if s <= int(r["blockNumber"]) <= e]


def mk():
    wt = evm_watch.EtherscanWatcher(cd, "hyperevm", [W1], Wr(), 999, "SYNTHKEY0123")
    wt._es = fake_es
    wt._es_extend = lambda head: None
    wt.head_block = lambda: 1000
    wt._ref_head = lambda: 1000
    return wt


evm_watch.lpdec.lp_managers = lambda base: {}
wt = mk()
wt.cursor[W1] = 100
wt.cursor["_cov:" + W1] = 50
wt.cycle()
recs = list(wt.writer.recs)
got = sorted(r["txhash"] for r in recs)
chk(got == sorted([H[0], H[1], H[2], H[3]]) and wt.cursor.get(W1, 0) > 180, "D 1주기 = 4건 방출(내 tx 2 · 시스템 tx 1 · 시스템 토큰 1) · 커서 전진",
    (len(recs), wt.cursor.get(W1)))
snap = {r["txhash"]: r["snapshot"] for r in recs}
chk(snap[H[1]]["tx"]["fee"]["value"] == "0" and snap[H[2]]["tx"]["fee"]["value"] == "0" and snap[H[0]]["tx"]["fee"]["value"] == str(22469 * GP),
    "D 가스: 시스템 tx·시스템 토큰 = 0 · 내 tx = gasUsed×gasPrice")
chk(not [t for t in snap[H[0]]["token_transfers"] if t["token"]["address"] == WHYPE],
    "D EVM→Core(0x2222… 로 보냄)는 랩드 감싸기 레그로 오인하지 않음(받는 쪽 ≠ WHYPE)")
wt2 = mk()
wt2.head_block = lambda: 1010
wt2.cycle()
chk(not wt2.writer.recs, "D 재기동 뒤 사이클 = 다시 안 나감(커서·방출 기록)", [r["txhash"][:10] for r in wt2.writer.recs])

import core
core.dm = lambda *a, **k: None
c = core.Core(cd)


def feed(rs):
    c._drain_stream("evm", _ingest.Reader(rs), 0, 0)
    c.conn.commit()


def qty(kind, ca=None):
    q = "SELECT p.qty_base FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.location=? AND a.kind=? AND a.chain='hyperevm'"
    args = [f"wallet:hyperevm:{W1}", kind]
    if ca:
        q += " AND lower(a.address)=?"
        args.append(ca)
    return sum(int(r[0]) for r in c.conn.execute(q, args))


feed(recs)
want = -(E18 // 2) - 22469 * GP + E18 - (E18 // 5) - 21000 * GP
chk(qty("native") == want, "D core: 네이티브 HYPE = −0.5 −가스 +1.0(Core→EVM) −0.2 −가스(목록 합과 같음)", (qty("native"), want))
chk(qty("token", TKN) == 100 * 10 ** 6, "D core: 시스템 토큰 주소에서 받은 토큰 +100(자릿수 6)", qty("token", TKN))
sym9 = c.conn.execute("SELECT symbol FROM assets WHERE kind='native' AND chain='hyperevm'").fetchone()
chk(sym9 and sym9[0] == "HYPE", "D 네이티브 자산 심볼 = HYPE", sym9)
feed(recs)
chk(qty("native") == want and qty("token", TKN) == 100 * 10 ** 6, "D 같은 레코드 다시 = 무변(멱등)")
T.finish()
