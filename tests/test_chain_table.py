#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import importlib.util
import json
import os
import re

import common
import chaincatalog as CC
import chainsweep as CS

W1 = "0x" + "a1" * 20
W2 = "0x" + "a2" * 20
OLD_BLOCKS = {"monad", "megaeth", "plasma", "xlayer", "kaia", "fraxtal", "bob", "story", "somnia", "avalanche", "stable", "abstract"}
NET_RX = re.compile(r"[a-z0-9]+-mainnet")
TABLE_ONLY_KEYS = {"_table_only", "_note", "chain_id", "name", "native", "alchemy", "alchemy_tokens", "alchemy_only"}

bad = []
for k, v in CC.CATALOG.items():
    if not isinstance(v, dict) or type(v.get("chain_id")) is not int or v["chain_id"] <= 0:
        bad.append((k, "chain_id"))
        continue
    if v.get("_table_only"):
        if set(v) - TABLE_ONLY_KEYS or not isinstance(v.get("name"), str) or not v["name"] or not isinstance(v.get("native"), str) \
                or not 0 < len(v["native"]) <= 10 or not NET_RX.fullmatch(str(v.get("alchemy"))) or type(v.get("alchemy_tokens")) is not bool:
            bad.append((k, "표 전용 칸"))
    else:
        if not (isinstance(v.get("rpcs"), list) and v["rpcs"] and all(str(u).startswith("https://") for u in v["rpcs"])):
            bad.append((k, "rpcs"))
        if v.get("alchemy") is not None and not NET_RX.fullmatch(str(v["alchemy"])):
            bad.append((k, "alchemy"))
        if "alchemy" in v and type(v.get("alchemy_tokens")) is not bool:
            bad.append((k, "alchemy_tokens"))
T.chk(not bad, "카탈로그 형식(수집 블록 = https 노드 · 표 전용 = 정해진 칸만 · alchemy 이름 모양)", bad)
cids = [v["chain_id"] for v in CC.CATALOG.values()]
T.chk(len(cids) == len(set(cids)), "카탈로그 체인 id 중복 없음", sorted(c for c in cids if cids.count(c) > 1))
nets = [CC.alchemy_network(k) for k in CC.CATALOG if CC.alchemy_network(k)]
T.chk(len(nets) == len(set(nets)), "Alchemy 네트워크 이름 중복 없음")
T.chk(len(nets) >= 73, f"Alchemy 지원 EVM 메인넷 전부에 alchemy 칸({len(nets)}개 ≥ 73)")
T.chk(CC.CATALOG["base"].get("alchemy") == "base-mainnet" and CC.CATALOG["eth"].get("alchemy") == "eth-mainnet"
      and CC.CATALOG["arbitrum"].get("alchemy") == "arb-mainnet" and CC.CATALOG["monad"].get("alchemy") == "monad-mainnet"
      and CC.CATALOG["bsc"].get("alchemy") == "bnb-mainnet" and CC.CATALOG["somnia"].get("alchemy") is None,
      "CATALOG[체인].get('alchemy') — 설정 체인(eth·base·arbitrum·bsc)·수집 블록(monad) 모두 · 미지원(somnia) = None")
T.chk(CC.alchemy_tokens("base") and not CC.alchemy_tokens("megaeth") and not CC.alchemy_tokens("somnia") and not CC.alchemy_tokens("nochain"),
      "alchemy_tokens: 토큰 API 켜진 체인만 참")
sw_bad = []
for k, e in CS.SWEEP_CHAINS.items():
    if not (isinstance(e, tuple) and len(e) == 5 and isinstance(e[0], str) and type(e[1]) is int and isinstance(e[2], str)
            and isinstance(e[3], list) and e[3] and all(str(u).startswith("https://") for u in e[3]) and type(e[4]) is int and e[4] >= 1):
        sw_bad.append(k)
T.chk(not sw_bad, "점검 목록 형식(표시명·체인 id·심볼·https 노드·배치 상한)", sw_bad)
swc = [e[1] for e in CS.SWEEP_CHAINS.values()]
T.chk(len(swc) == len(set(swc)), "점검 목록 체인 id 중복 없음")
mis = [k for k in CC.CATALOG if k in CS.SWEEP_CHAINS and CC.CATALOG[k]["chain_id"] != CS.SWEEP_CHAINS[k][1]]
T.chk(not mis, "카탈로그·점검 목록 같은 체인 = 같은 체인 id", mis)
only = [k for k, v in CC.CATALOG.items() if v.get("alchemy_only")]
T.chk(only and not [k for k in only if k in CS.SWEEP_CHAINS], "알케미 전용(무키 노드 없음) 체인은 점검 목록 밖", only)
T.chk("tempo" not in CS.SWEEP_CHAINS and "xmtp" not in CS.SWEEP_CHAINS and "edge" not in CS.SWEEP_CHAINS,
      "점검 불가 체인(tempo 잔고 고정값 · xmtp·edge 가스 토큰 미확인)은 점검 목록 밖")
new9 = ("adi", "anime", "astar", "boba", "citrea", "earnm", "galactica", "gensyn", "humanity", "mythos", "rise", "settlus",
        "superseed", "worldmobile", "zetachain", "pharos", "jovay")
T.chk(all(k in CS.SWEEP_CHAINS and CC.alchemy_network(k) for k in new9), "새 Alchemy 체인 17개 = 점검 목록 + alchemy 칸")

T.chk(set(CC.blocks()) == OLD_BLOCKS and all(CC.is_block(k) for k in OLD_BLOCKS) and not CC.is_block("eth") and not CC.is_block("nochain"),
      "blocks()·is_block = 종전 수집 블록 12개만(표 전용 항목 제외)", sorted(CC.blocks()))
b, why = CC.block_for("monad", False, None)
T.chk(why == "catalog" and b and set(b) == {"_note", "discovery", "chain_id", "rpcs", "rpc_logs", "getlogs_span", "conf_depth", "blocks_per_day",
                                             "poll_sec", "_auto"} and b["rpcs"] == ["https://rpc2.monad.xyz", "https://rpc.monad.xyz"],
      "수집 블록 = 종전 키만(alchemy·alchemy_tokens 를 블록에 싣지 않음)", sorted(b or {}))
leak = [k for k in OLD_BLOCKS if set(CC.block_for(k, False, None)[0] or {}) & set(CC.TABLE_KEYS)]
T.chk(not leak, "수집 블록 12개 전부 표 칸 없음", leak)
T.chk("alchemy" in CC.CATALOG["monad"], "떼어 낸 건 사본 — 카탈로그 원본 칸은 그대로")
b, why = CC.block_for("eth", False, None)
T.chk(b is None and why.startswith("실측 없음"), "표 전용(점검 목록 체인 eth) = 종전 경로(실측 없음 → 안 켬)", why)
b, why = CC.block_for("pharos", True, None)
T.chk(b is None and why.startswith("실측 없음"), "새 점검 체인(pharos) 실측 전 = 안 켬", why)
b, why = CC.block_for("zetachain", True, {"getLogsSpan": 10000, "blocksPerSec": 0.26})
T.chk(why == "generic" and b["chain_id"] == 7000 and "alchemy" not in b and b["rpcs"][0].startswith("https://zetachain-mainnet"),
      "새 점검 체인 + 실측 + 새 활동 = 종전 범용 블록(알케미 노드 아님)", b)
b, why = CC.block_for("zetachain", False, {"getLogsSpan": 10000, "blocksPerSec": 0.26, "windowCalls": 9999, "autoOk": False})
T.chk(b is None and why.startswith("창 백필 비용 과다"), "이력 있는 쌍 + 창 비용 과다 = 안 켬(종전)", why)
for c9 in ("crossfi", "tempo", "xmtp", "edge"):
    b, why = CC.block_for(c9, True, {"getLogsSpan": 100000, "blocksPerSec": 1})
    T.chk(b is None and why == "점검 목록에 없는 체인", f"표 전용·점검 불가 체인({c9}) = 실측이 있어도 안 켬", why)

CFG = {"chains": {"eth": {"blockscout": "https://eth.invalid", "rpcs": ["https://eth-rpc.invalid"]},
                  "base": {"discovery": "rpc", "rpcs": ["https://base-rpc.invalid"]}},
       "wallets": [{"type": "evm", "chain": "eth", "address": W1, "label": "가"},
                   {"type": "evm", "chain": "base", "address": W1, "label": "가"},
                   {"type": "evm", "chain": "eth", "address": W2, "label": "나"}],
       "chain_sweep": {"enabled": True, "auto_enable": True, "pace_sec": 0}}
with open(common.CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump(CFG, f)


def load():
    return common.load_config()


c0 = load()
T.chk(set(c0["chains"]) == {"eth", "base"} and len(c0["wallets"]) == 3, "게이트 파일 없음 = 설정 그대로(표가 커져도 체인이 늘지 않음)", sorted(c0["chains"]))
gate = {"version": 1, "chains": {}, "pairs": {
    f"monad:{W1}": {"active": True, "since_block": None},
    f"zetachain:{W1}": {"active": True, "since_block": 123, "since_state": [0, "0"]},
    f"pharos:{W1}": {"active": True, "since_block": None},
    f"gensyn:{W2}": {"active": True, "since_block": 7},
    f"edge:{W2}": {"active": True, "since_block": 7},
    f"crossfi:{W1}": {"active": True, "since_block": 9},
    f"tempo:{W2}": {"active": True, "since_block": 9},
    f"adi:{W1}": {"active": False}}}
speed = {"version": 1, "chains": {"zetachain": {"getLogsSpan": 10000, "blocksPerSec": 0.26, "autoOk": False},
                                  "gensyn": {"getLogsSpan": None, "blocksPerSec": 0.5, "autoOk": False}}}
common.atomic_write_json(common.ACTIVITY_GATE_PATH, gate)
common.atomic_write_json(common.BACKFILL_SPEED_PATH, speed)
c1 = load()
T.chk(set(c1["chains"]) == {"eth", "base", "monad", "zetachain"}, "게이트: 수집 블록(monad)·새 활동+실측(zetachain)만 켬 — 표 전용·알케미 전용·실측 없음은 안 켬",
      sorted(c1["chains"]))
auto9 = sorted((w["chain"], w["address"]) for w in c1["wallets"] if w.get("_auto"))
T.chk(auto9 == [("monad", W1), ("zetachain", W1)], "자동 지갑 행 = 켠 쌍만", auto9)
T.chk("alchemy" not in c1["chains"]["monad"] and "alchemy" not in c1["chains"]["zetachain"]
      and c1["chains"]["zetachain"]["rpcs"] == list(CS.SWEEP_CHAINS["zetachain"][3]),
      "켠 체인 블록에 Alchemy 칸·Alchemy 노드 없음(감시 = 무료 노드)", c1["chains"]["zetachain"].get("rpcs"))
dec = {d["chain"]: d for d in common.gate_decisions(c0, gate, speed)}
T.chk(dec["crossfi"]["reason"] == "점검 목록에 없는 체인" and dec["tempo"]["reason"] == "점검 목록에 없는 체인"
      and dec["edge"]["reason"] == "점검 목록에 없는 체인"
      and dec["pharos"]["reason"].startswith("실측 없음") and dec["gensyn"]["reason"].startswith("실측 없음") and "adi" not in dec,
      "판정 사유: 표 전용 = 점검 목록 없음 · 새 체인 실측 전 = 실측 없음 · 비활성 쌍 = 판정 없음", {k: v["reason"] for k, v in dec.items()})
CFG2 = dict(CFG, chain_sweep={"enabled": True, "auto_enable": False, "pace_sec": 0})
with open(common.CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump(CFG2, f)
c2 = load()
T.chk(set(c2["chains"]) == {"eth", "base"} and not [w for w in c2["wallets"] if w.get("_auto")], "자동 켜기 끔 = 아무 체인도 안 켬")
with open(common.CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump(CFG, f)

lst = CS.chain_list(c0)
T.chk(all(k in lst for k in new9) and not [k for k in ("tempo", "xmtp", "edge", "crossfi", "race") if k in lst], "점검 목록(chain_list) = 새 체인 포함 · 표 전용 제외")
URL_CID = {}
for k, e in lst.items():
    for u in e[3]:
        URL_CID.setdefault(u, e[1])
CALLS = []


def fake_post(url, body, timeout):
    reqs = body if isinstance(body, list) else [body]
    CALLS.append(url)
    out = []
    for r in reqs:
        m, p = r["method"], r["params"]
        if m == "eth_chainId":
            v = hex(URL_CID[url])
        elif m == "eth_blockNumber":
            v = hex(5000)
        elif m == "eth_getTransactionCount":
            v = "0x4" if (url == lst["pharos"][3][0] and p[0] == W1) else "0x0"
        elif m == "eth_getBalance":
            v = "0x0"
        else:
            v = "0x0"
        out.append({"jsonrpc": "2.0", "id": r["id"], "result": v})
    return out if isinstance(body, list) else out[0]


g9 = {}
res = CS.run_once(c0, price_fn=lambda s: None, post=fake_post, now=1_900_000_000, gate=g9)
f9 = [f for f in res["findings"] if f["chain"] == "pharos"]
T.chk(not res["errors"] and len(res["chains"]) == len(lst), "점검 1바퀴 = 목록 전 체인 성공(가짜 노드)", res["errors"])
T.chk(f9 and f9[0]["wallet"] == W1 and f9[0]["reason"].startswith("실측 없음") and not [a for a in res["autoEnabled"] if a["chain"] == "pharos"],
      "새 체인 활동(pharos nonce 4) = 경고만(실측 전 자동 켜기 아님)", f9)
T.chk(not [u for u in CALLS if "/v2/" in u], "점검은 키 붙은 Alchemy 주소를 부르지 않음")

SEED_P = os.path.join(T.ROOT, "seed", "coverage", "evm_chains.json")
raw = open(SEED_P, encoding="utf-8").read()
doc = json.loads(raw)
rows = CC.chain_table()
T.chk(doc.get("schema") == 1 and isinstance(doc.get("chains"), dict) and rows == doc["chains"], "표 읽기(chain_table) = seed 파일")
miss = [k for k in CC.CATALOG if CC.alchemy_network(k) and k not in rows]
extra = [k for k in rows if not CC.alchemy_network(k)]
T.chk(not miss and not extra, "표 = 카탈로그의 Alchemy 체인과 같은 집합", {"빠짐": miss, "남음": extra})
diff = []
for k, r in rows.items():
    v = CC.CATALOG.get(k) or {}
    st = "catalog" if CC.is_block(k) else "sweep" if k in CS.SWEEP_CHAINS else "table"
    if r.get("alchemy") != v.get("alchemy") or r.get("chain_id") != v.get("chain_id") or bool(r.get("alchemy_tokens")) != bool(v.get("alchemy_tokens")):
        diff.append((k, "이름·id·토큰"))
    if bool(r.get("free_path")) == bool(v.get("alchemy_only")):
        diff.append((k, "무료 경로"))
    if r.get("status") != st:
        diff.append((k, "status", r.get("status"), st))
    u = r.get("uses") or {}
    if not all(isinstance(u.get(x), dict) and set(u[x]) == {"free", "alchemy"} for x in ("tokens", "backfill", "watch")):
        diff.append((k, "세 용도"))
    if not (isinstance(r.get("native"), list) and len(r["native"]) == 2 and r["native"][1] == 18):
        diff.append((k, "native"))
T.chk(not diff, "표 행 = 카탈로그(이름·id·토큰 API·무료 경로·상태) · 세 용도 칸 · 네이티브 [심볼, 18]", diff[:12])
T.chk(not re.search(r"0x[0-9a-fA-F]{40}", raw) and not re.search(r"alchemy\.com/v2/", raw), "표에 주소 모양 값·키 붙는 엔드포인트 없음(공개판 공용 사실만)")
nat_bad = []
for k, r in rows.items():
    v = CC.CATALOG.get(k) or {}
    want = CC.native_of(k)[0] if CC.is_block(k) else v.get("native")
    if (r.get("native") or [None])[0] != want:
        nat_bad.append((k, "표≠카탈로그", r.get("native"), want))
    if not CC.is_block(k) and k in CS.SWEEP_CHAINS and CS.SWEEP_CHAINS[k][2] != v.get("native"):
        nat_bad.append((k, "점검 목록≠카탈로그", CS.SWEEP_CHAINS[k][2], v.get("native")))
T.chk(not nat_bad, "네이티브(가스) 심볼 = 표·카탈로그·점검 목록 일치", nat_bad)
nc_bad = [k for k, r in rows.items() if not str(r.get("native_check") or "").strip()]
T.chk(not nc_bad, "표 행마다 가스 토큰 근거(native_check)", nc_bad[:10])
unv = [k for k, r in rows.items() if str(r.get("native_check") or "").startswith(("미확인", "체인 목록 값(미확인", "네이티브 가스 토큰 없음"))]
T.chk(unv and not [k for k in unv if k in CS.SWEEP_CHAINS], "가스 토큰 미확인·없음 체인은 점검 목록 밖(잘못된 시세로 문턱·금액 계산 방지)",
      [k for k in unv if k in CS.SWEEP_CHAINS])
T.chk(CS.SWEEP_CHAINS["mythos"][2] == "ETH" == CC.CATALOG["mythos"]["native"] and "MYTH 는 생태계 토큰" in rows["mythos"]["native_check"],
      "Mythos(42018) 가스 = ETH(OP L1Block·탐색기·Alchemy 'Gas token') — 생태계 토큰 MYTH 아님(근거 기록)")
af = doc.get("alchemy_free_tier") or {}
T.chk(af.get("getlogs_max_blocks") == 10 and af.get("cap_pct") == 80 and isinstance(af.get("rules"), list) and len(af["rules"]) >= 3,
      "Alchemy 무료 등급 규칙(getLogs 10블록 · 80% 상한 · 용도 규칙)")

import bf_engine
SMALL = {"zetachain-evm.blockpi.network": 3}
cap_bad = []
for k, e in CS.SWEEP_CHAINS.items():
    for u in e[3]:
        h = u.split("/")[2]
        cap = bf_engine.gate(u).batch_cap(int(e[4]))
        lim = SMALL.get(h) or (3 if h.endswith(".drpc.org") else None)
        if lim is not None and cap > lim:
            cap_bad.append((k, h, cap, lim))
T.chk(not cap_bad, "점검 노드별 배치 상한 — 상한 작은 노드에 큰 배치 없음(ZetaChain 예비 노드 포함)", cap_bad)
T.chk(bf_engine.gate("https://zeta-chain.drpc.org").batch_cap(23) == 3, "ZetaChain 예비 노드(drpc) = 호스트 게이트가 배치 3 으로 줄임")

TP = os.path.join(T.ROOT, "tools", "allchains_enable.py")
if os.path.isfile(TP):
    spec = importlib.util.spec_from_file_location("allchains_enable_t", TP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    T.chk(set(mod.CHAINS) == OLD_BLOCKS, "allchains_enable: 시드 가능한 체인 = 수집 블록만(표 전용 eth·base 아님)", sorted(mod.CHAINS))
    try:
        mod.seed_pairs(c0, common.STATE_DIR, [f"eth:{W1}"])
        T.chk(False, "allchains_enable --seed-pair 표 전용 체인 = 거부")
    except ValueError as e:
        T.chk("카탈로그에 없는 체인" in str(e), "allchains_enable --seed-pair 표 전용 체인 = 거부(종전 문구)", str(e)[:80])
T.finish()
