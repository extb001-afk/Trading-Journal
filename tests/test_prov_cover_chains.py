#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

W = "0x" + "ab" * 20
WB = "0x" + "cd" * 20
TW = "T" + "x" * 33
shutil.copytree(os.path.join(T.ROOT, "seed"), os.path.join(T.TMP, "seed"), dirs_exist_ok=True)
CHAINS = {c: {"blockscout": f"https://bs-{c}.invalid", "conf_depth": 12, "blocks_per_day": 7200, "rpcs": [f"https://rpc-{c}.invalid"]}
          for c in ("eth", "base", "arbitrum", "optimism", "polygon", "scroll", "gnosis", "robinhood")}
CFG = {"wallets": [{"type": "evm", "chain": c, "address": W, "label": "w"} for c in CHAINS]
       + [{"type": "bsc_rpc", "chain": "bsc", "address": WB, "label": "b"}], "backfill_months": 3, "chains": CHAINS,
       "bsc": {"detail_rpcs": ["https://bsc-detail.invalid"], "logs_rpcs": ["https://bsc-logs.invalid"]},
       "native_symbol": {"eth": "ETH"}}
json.dump(CFG, open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
import config, paths  # noqa: E402

assert T.TMP in paths.STATE_DIR
import core  # noqa: E402
import core_svc  # noqa: E402
import core_recon  # noqa: E402
import provbal  # noqa: E402
import token_tables  # noqa: E402
import recon  # noqa: E402
import token_discovery  # noqa: E402

T.patch_moved("dm", lambda *a, **k: None)

PF = os.path.join(paths.STATE_DIR, "prov_bal.json")


def check(name, ok, detail=""):
    T.chk(bool(ok), name, None if ok else str(detail)[:900])


c = core.Core(config.load_config())
for ch9 in CHAINS:
    c.my_wallets.setdefault(ch9, set()).add(W)
c.my_wallets.setdefault("bsc", set()).add(WB)
c.chain_owners = {"tron": {TW}}
c.svc_recon._nonevm_adapters = {"tron": object()}
tg = c.svc_recon._prov_targets()
names = [t[0] for t in tg]
check("C1 대상 = EVM 8 · BSC · Tron(새 체인)", set(names) == set(CHAINS) | {"bsc", "tron"} and ("tron", "nonevm", "chain", [TW]) in tg, tg)

calls = []
gates = {}
BALS = {}


def fake_plan(chain, kind, ws, mode=None, latest=False):
    calls.append((chain, kind, mode, latest))
    ev = gates.setdefault((chain, len(calls)), threading.Event())

    def run():
        ev.wait(5)
        return {"per_wallet": {w: {("native", None): 10 ** 18} for w in ws}, "_meta": {}, "_source": "rpc", "_queried": {w: [] for w in ws}}
    return run


def running():
    return sorted(k for k, j in c.svc_recon._prov_jobs.items() if not j["ev"].is_set())


def wait_set(keys):
    for _ in range(200):
        if all(c.svc_recon._prov_jobs[k]["ev"].is_set() for k in keys if k in c.svc_recon._prov_jobs):
            return
        time.sleep(0.01)


c.svc_recon._recon_fetch_plan = fake_plan
c.svc_recon._prov_last = 0
c.svc_recon.prov_pass()
fast0 = [x for x in calls if x[2] == "fast"]
slow0 = [x for x in calls if x[2] != "fast"]
check("C2 첫 판 = 체인 PROV_PAR(6)개 동시(종전 = 한 체인) · EVM·BSC = 빠른 판(fast) · 지금 블록(latest)",
      len(calls) == core_svc.ReconService.PROV_PAR == len(running()) and len(fast0) == len(calls) and all(x[3] is True for x in calls) and not slow0, calls)
first = [x[0] for x in calls]
for (ch9, i9), ev9 in list(gates.items()):
    if ch9 in first[:2]:
        ev9.set()
wait_set(first[:2])
n0 = len(calls)
c.svc_recon.prov_pass()
pf = json.load(open(PF))
check("C3 끝난 조회 = 틱 기다리지 않고 수확(파일) · 빈 자리만큼 다음 체인 바로 시작 · 받은 체인 중 큰 몫(eth) = 바로 발견 포함 판(한 차선 하나)",
      all(ch9 in pf and pf[ch9].get("fast") == 1 for ch9 in first[:2]) and len(calls) == n0 + 3
      and [x[2] for x in calls[n0:]].count("fast") == 2 and [x[:3] for x in calls[n0:] if x[2] is None] == [("eth", "evm", None)]
      and first[:2] == ["eth", "base"], (first, list(pf), calls[n0:]))
disc_max = 0
for _ in range(30):
    for ev9 in list(gates.values()):
        ev9.set()
    wait_set(list(c.svc_recon._prov_jobs))
    c.svc_recon.prov_pass()
    disc_max = max(disc_max, sum(1 for j in c.svc_recon._prov_jobs.values() if not j["ev"].is_set() and j.get("lane") == "disc"))
for ev9 in list(gates.values()):
    ev9.set()
wait_set(list(c.svc_recon._prov_jobs))
c.svc_recon.prov_pass()
pf = json.load(open(PF))
modes = {}
for x in calls:
    modes.setdefault(x[0], []).append(x[2])
check("C3 모든 대상 첫 잔고(EVM 8 · BSC · Tron) · EVM·BSC = 빠른 판 → 바로 발견 포함 판(대기 없음) · Tron = 종전 조회 한 번",
      set(pf) == set(names) and all(modes.get(ch9) == ["fast", None] for ch9 in list(CHAINS) + ["bsc"]) and modes.get("tron") == [None], modes)
check("C4 발견 포함 판 = 차선마다 한 번에 하나(키 색인 한도 — 종전 규약)", disc_max == 1, disc_max)
check("C4 발견 포함 판 결과 = 빠른 판 표시 지움", not any(v.get("fast") for v in pf.values()), {k: v.get("fast") for k, v in pf.items()})
n1 = len(calls)
for _ in range(3):
    c.svc_recon._prov_last = 0
    c.svc_recon.prov_pass()
check("C4 발견 포함 판 뒤 = PROV_EVERY 간격까지 다시 안 물음(종전)", len(calls) == n1, calls[n1:])

for _ in range(20):
    for ev9 in list(gates.values()):
        ev9.set()
    wait_set(list(c.svc_recon._prov_jobs))
    c.svc_recon._prov_last = 0
    c.svc_recon.prov_pass()
for ch9 in names:
    c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, '1')", (f"recon_done_{ch9}",))
c.conn.commit()
check("C1 새 체인도 대사 끝 = 대상에서 빠짐", c.svc_recon._prov_targets() == [], c.svc_recon._prov_targets())
c.svc_recon._prov_jobs.clear()
c.svc_recon._prov_last = 0
c.svc_recon.prov_pass()
n2 = len(calls)
mt9 = os.path.getmtime(PF)
for _ in range(3):
    c.svc_recon._prov_last = 0
    c.svc_recon.prov_pass()
check("C5 라이브 꼴(모든 체인 대사 끝) = 조회 0 · 칸 전부 지움 뒤 파일 무변",
      len(calls) == n2 and json.load(open(PF)) == {} and os.path.getmtime(PF) == mt9, (calls[n2:], json.load(open(PF))))

del c.svc_recon._recon_fetch_plan
cap = []
recon.fetch_evm_rpc_balances = lambda *a, **k: cap.append((a, k)) or {"per_wallet": {}, "_source": "rpc"}
disc = []
c.svc_recon._disc_prep = lambda *a, **k: disc.append(a) or None
bscf = []
token_discovery.bsc_fetch = lambda *a, **k: bscf.append(a) or {}
recon.fetch_bsc_balances = lambda *a, **k: bscf.append(a) or {}
for ch9 in names:
    c.conn.execute("DELETE FROM meta WHERE k=?", (f"recon_done_{ch9}",))
c.conn.commit()
json.dump({W: 100}, open(os.path.join(paths.STATE_DIR, "cursor_evm_eth.json"), "w"))
c.svc_recon._recon_fetch_plan("eth", "evm", [W], "fast", latest=True)()
a6, k6 = cap[-1]
sw6 = {str(x).lower() for x in token_tables.STABLE_CAS.get("eth", {})}
check("C6 EVM 빠른 판 = 발견 없음(블록스카웃 목록 None · 발견 재료 안 만듦) · 검증 스테이블 전부 · 헤드 블록(latest) · 네이티브·토큰",
      k6.get("discover_url") is None and not disc and sw6 and sw6 <= set(k6.get("sweep") or {}) and k6.get("block") is None
      and k6.get("want_native") is False and "wallet_extra" not in k6, k6)
c.svc_recon._recon_fetch_plan("eth", "evm", [W], None, latest=True)()
a6b, k6b = cap[-1]
check("C6 발견 포함 판(mode None · latest) = 종전 그대로(블록스카웃 목록 · 발견 재료)",
      k6b.get("discover_url") == "https://bs-eth.invalid" and len(disc) == 1 and k6b.get("block") is None, (k6b, disc))
c.svc_recon._recon_fetch_plan("eth", "evm", [W], None)()
a6c, k6c = cap[-1]
check("C6 대사 경로(latest 아님) = 종전 그대로(수집기 커서 블록 · 발견)", k6c.get("block") == 100 and k6c.get("discover_url") == "https://bs-eth.invalid"
      and len(disc) == 2, k6c)
n_cap = len(cap)
c.svc_recon._recon_fetch_plan("bsc", "bsc", [WB], "fast", latest=True)()
a7, k7 = cap[-1] if len(cap) > n_cap else ((), {})
swb = {str(x).lower() for x in token_tables.STABLE_CAS.get("bsc", {})}
check("C7 BSC 빠른 판 = 공용 RPC 멀티콜(상세 RPC · Multicall3 · 지갑별 원장 토큰 · BSC 검증 스테이블) · 종전 단건·발견 경로 안 탐",
      len(cap) == n_cap + 1 and list(a7[0]) == ["https://bsc-detail.invalid"] and k7.get("multicall") == token_tables.MULTICALL3
      and swb and swb <= set(k7.get("sweep") or {}) and k7.get("discover_url") is None and k7.get("block") is None
      and k7.get("wallet_cas") == {WB: set()} and not bscf and len(disc) == 2, (a7, k7, bscf))
c.svc_recon._recon_fetch_plan("bsc", "bsc", [WB], None, latest=True)()
check("C7 BSC 임시 잔고 발견 포함 판(latest) = 같은 멀티콜 조회 + 발견 재료(종전 bsc_fetch 단건은 지갑 수백이면 수 시간)",
      len(cap) == n_cap + 2 and len(disc) == 3 and not bscf and cap[-1][1].get("multicall") == token_tables.MULTICALL3, (bscf, disc, cap[-1]))
c.svc_recon._recon_fetch_plan("bsc", "bsc", [WB], None)()
check("C7 BSC 대사(latest 아님) = 종전 경로(발견 재료 · bsc_fetch)", len(cap) == n_cap + 2 and len(disc) == 4 and bscf, (bscf, disc))

WX = "0x" + "ef" * 20
mcs, singles = [], []
recon.fetch_evm_rpc_balances = lambda urls, ws, cas, **k: {"per_wallet": {w: {("token", "0x" + "11" * 20): 5} for w in ws}, "_source": "rpc",
                                                          "_block": 77, "_block_ts": 1000, "_multicall": True, "_hold": {}, "_queried": {w: [] for w in ws}}
recon._mc_call = lambda urls, blk, items, mc, **k: mcs.append((blk, [it[2][:8] for it in items], mc)) or {
    it[0]: ((12 * 10 ** 18).to_bytes(32, "big") if it[0][1] == W else None) for it in items}
recon._rpc_any = lambda urls, m, params, check=None, **k: singles.append((m, params)) or 3
r9 = core_recon.ReconMixin._prov_fast_fetch("eth", ["u"], [W, WX], {}, multicall=token_tables.MULTICALL3)
check("C9 네이티브 = 같은 블록(조회 블록) Multicall3 getEthBalance 한 묶음 · 못 읽은 지갑 = 보류(0 으로 안 보임) · 단건 0콜",
      mcs == [(hex(77), ["4d2301cc", "4d2301cc"], token_tables.MULTICALL3)] and r9["per_wallet"][W][("native", None)] == 12 * 10 ** 18
      and WX not in r9["per_wallet"] and WX in r9["_hold"] and not singles, (mcs, r9, singles))
r9z = core_recon.ReconMixin._prov_fast_fetch("zksync", ["u"], [W], {}, multicall="0x" + "99" * 20)
check("C9 ZK Stack 체인 = 네이티브 종전 단건(eth_getBalance · 같은 블록)", singles == [("eth_getBalance", [W, hex(77)])]
      and r9z["per_wallet"][W][("native", None)] == 3 and len(mcs) == 1, (singles, r9z))

ent = {"tron": {"mode": "chain", "at": 100, "wallets": {TW: {"native": "2500000", "tok": {}, "q": []}}}}
its = provbal.items(ent, done_chain=lambda ch9: False, asset_of=lambda *a: None, ledger=lambda loc, e: ({}, set()), ainfo=lambda a: None)
check("C8 Tron 네이티브 자리수 = 6(원장 자산 없음 · 18 로 안 지음) · 심볼 = 등록표(TRX)",
      len(its) == 1 and str(its[0]["qty"]) == "2.5" and provbal._unit(its[0]) == "TRX", its)

c.conn.close()
T.finish()
