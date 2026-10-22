#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from decimal import Decimal  # noqa: E402

W = "0x" + "ab" * 20
SW = "So1" + "a" * 40
SW2 = "So2" + "b" * 40
PK1, PK2, PK3 = "Stk" + "1" * 40, "Stk" + "2" * 40, "Stk" + "3" * 40
shutil.copytree(os.path.join(T.ROOT, "seed"), os.path.join(T.TMP, "seed"), dirs_exist_ok=True)
CHAINS = {c: {"blockscout": f"https://bs-{c}.invalid", "conf_depth": 12, "blocks_per_day": 7200, "rpcs": [f"https://rpc-{c}.invalid"]}
          for c in ("eth", "base")}
CFG = {"wallets": [{"type": "evm", "chain": c, "address": W, "label": "w"} for c in CHAINS], "backfill_months": 3, "chains": CHAINS}
json.dump(CFG, open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
import paths  # noqa: E402
import config  # noqa: E402

assert T.TMP in paths.STATE_DIR
import core  # noqa: E402
import core_svc  # noqa: E402
import core_recon  # noqa: E402
import core_prov  # noqa: E402
import provbal  # noqa: E402
import recon  # noqa: E402
import token_discovery  # noqa: E402

T.patch_moved("dm", lambda *a, **k: None)

PF = os.path.join(paths.STATE_DIR, "prov_bal.json")
NOW = time.time()


def check(name, ok, detail=""):
    T.chk(bool(ok), name, None if ok else str(detail)[:900])


_real_fast_sol = recon.fetch_sol_balances
recon.fetch_sol_balances_fast = lambda lanes, ws, native_url=None, **k: {"per_wallet": {w: {("native", None): 5 * 10 ** 8} for w in ws}, "_meta": {}}
recon.fetch_sol_balances = lambda url, ws: {"per_wallet": {w: {("native", None): 5 * 10 ** 8} for w in ws}, "_meta": {}}
_real_stake_live = core_svc.ReconService._prov_sol_stake_live
T.patch_cls_attr(core_svc.ReconService, "_prov_sol_stake_live", staticmethod(lambda url, pks, native_url=None: {pk: {PK1: 200 * 10 ** 9}.get(pk, 0) for pk in pks}))
SP = os.path.join(paths.STATE_DIR, "sol_stake.json")
json.dump({"ts": int(NOW - 600), "accounts": {
    PK1: {"w": SW, "lamports": 200 * 10 ** 9, "state": "active"},
    PK2: {"w": SW, "lamports": 0, "state": "closed"},
    PK3: {"w": SW2, "lamports": 7 * 10 ** 9, "state": "active"}}}, open(SP, "w"))
r1 = core_recon.ReconMixin._prov_sol_fetch("u", [SW], now=NOW)
pw = r1["per_wallet"]
check("B1 SOL 임시 잔고 = 지갑 + 스테이크 계정 칸('<지갑>:stake:<계정>' = 원장 위치 키) · 닫힌 계정 = 0 · 다른 지갑 계정 = 안 실음",
      pw.get(SW) == {("native", None): 5 * 10 ** 8} and pw.get(f"{SW}:stake:{PK1}") == {("native", None): 200 * 10 ** 9}
      and pw.get(f"{SW}:stake:{PK2}") == {("native", None): 0} and not any(PK3 in k for k in pw), pw)
r2 = core_recon.ReconMixin._prov_sol_fetch("u", [SW], now=NOW + 4 * 3600)
check("B2 낡은 스테이크 스냅숏(3시간 넘음) = 안 실음(원장 그대로)", list(r2["per_wallet"]) == [SW], r2)
os.remove(SP)
check("B2 스냅숏 없음 = 지갑만(종전)", list(core_recon.ReconMixin._prov_sol_fetch("u", [SW])["per_wallet"]) == [SW])
json.dump({"ts": int(time.time()), "accounts": {PK1: {"w": SW, "lamports": 200 * 10 ** 9}}}, open(SP, "w"))
c = core.Core(config.load_config())
c.svc_recon._sol_rpc_url = lambda: "https://sol.invalid"
got_l = c.svc_recon._recon_fetch_plan("sol", "sol", [SW], None, latest=True)()
got_r = c.svc_recon._recon_fetch_plan("sol", "sol", [SW], None)()
check("B2 임시 잔고 조회(latest) = 스테이크 포함 · 대사 경로(latest 아님) = 종전 조회 그대로(지갑만)",
      f"{SW}:stake:{PK1}" in got_l["per_wallet"] and list(got_r["per_wallet"]) == [SW], (got_l, got_r))
T.patch_cls_attr(core_svc.ReconService, "_prov_sol_stake_live", _real_stake_live)
pk9 = core_prov.ProvMixin._prov_pack(r1, "chain", NOW - 5, req=[SW], t1=NOW - 4, kind="sol")
LOC_S = f"wallet:sol:{SW}:stake:{PK1}"
led9 = {LOC_S: {11: Decimal("150")}}
its = provbal.items({"sol": pk9}, done_chain=lambda ch9: False,
                    asset_of=lambda ch9, kind, addr: (11, 5, "SOL", 9) if kind == "native" else None,
                    ledger=lambda loc, e: (led9.get(loc, {}), set()), ainfo=lambda a: ("native", None, "SOL", 9, 5))
st9 = [it for it in its if it["loc"] == LOC_S]
check("B3 provbal: 스테이크 칸 위치 = wallet:sol:<지갑>:stake:<계정> · 원장 몫(150)을 빼고 차이(50)만 · 지갑 칸 따로",
      len(st9) == 1 and st9[0]["qty"] == Decimal("50") and st9[0]["gid"] == 5
      and any(it["loc"] == f"wallet:sol:{SW}" and it["qty"] == Decimal("0.5") for it in its), its)

ENV = {"TJ_ALCHEMY_KEY": "k" * 32}
token_discovery._env = lambda: dict(ENV)
token_discovery.alchemy_net = lambda ch9: "base-mainnet" if ch9 in ("base", "eth") else None
token_discovery.alchemy_url = lambda ch9, env=None: ("https://x.g.alchemy.com/v2/k" if token_discovery.alchemy_net(ch9) and (env or token_discovery._env()).get("TJ_ALCHEMY_KEY") else None)
CA_NZ, CA_Z, CA_G = "0x" + "a1" * 20, "0x" + "a2" * 20, "0x" + "a3" * 20
dcalls = []


def fake_disc(chain, w, **kw):
    dcalls.append((chain, w, kw.get("sources")))
    return {"cas": {CA_NZ: ["alchemy"], CA_Z: ["alchemy"]}, "meta": {CA_NZ: {"sym": "BNKR", "alnz": True}, CA_Z: {"sym": "OLD", "alnz": False}},
            "ok": {"alchemy": 2}, "fail": {}, "calls": {"alchemy": 1}, "ran": ["alchemy"]}


saved = []
token_discovery.save_result = lambda *a, **k: saved.append(a)
prep = {"chain": "base", "kind": "evm", "cfg": {}, "sigs": {W: {}}, "genuine": {CA_G}, "off": False}
ex1 = token_discovery.fast_extra(prep, discover_fn=fake_disc)
check("C1 fast_extra = Alchemy 한 출처(지갑당) · 잔고 있음(alnz)만 + 원장 정품 · 발견 캐시 저장 안 함",
      dcalls == [("base", W, ["alchemy"])] and ex1["extra"].get(W) == {CA_NZ, CA_G} and ex1["status"].get(W) == "ok"
      and ex1["src"][W].get(CA_NZ) == ["alchemy"] and "ledger" in ex1["src"][W].get(CA_G, []) and not saved
      and ex1["meta"].get(CA_NZ, {}).get("sym") == "BNKR", (dcalls, ex1, saved))
ENV.clear()
ex2 = token_discovery.fast_extra(prep, discover_fn=fake_disc)
check("C1 Alchemy 키 없음 = 빈 것(종전 빠른 판) · 호출 0", ex2["extra"] == {} and len(dcalls) == 1, ex2)
ENV["TJ_ALCHEMY_KEY"] = "k" * 32
ex3 = token_discovery.fast_extra(dict(prep, chain="polygon"), discover_fn=fake_disc)
check("C1 토큰 API 안 되는 체인 = 빈 것 · 호출 0", ex3["extra"] == {} and len(dcalls) == 1, ex3)
ex4 = token_discovery.fast_extra(prep, deadline=time.time() - 1, discover_fn=fake_disc)
check("C1 시간 상한 지남 = 남은 지갑 발견 없이(보류 아님 — status 없음)", ex4["extra"] == {} and ex4["status"] == {} and len(dcalls) == 1, ex4)

real_filter = token_discovery.filter_result
fx_kw, flt = [], []
token_discovery.fast_extra = lambda p, **k: ex1
token_discovery.filter_result = lambda bal, p, e, **k: flt.append((p, e, k)) or dict(bal, _filtered=1)
b2 = core_recon.ReconMixin._prov_fastx("base", prep, lambda **k: fx_kw.append(k) or {"per_wallet": {}})
check("C2 둘째 판 = 발견 CA 를 같은 블록 RPC 로 더 묻고(wallet_extra) 대사와 같은 스팸 거르기(filter_result)",
      fx_kw == [{"wallet_extra": ex1["extra"]}] and flt and flt[-1][0] is prep and flt[-1][2] == {"keep_pending": True} and b2.get("_filtered") == 1, (fx_kw, b2))
b3 = core_recon.ReconMixin._prov_fastx("base", None, lambda **k: fx_kw.append(k) or {"per_wallet": {}})
check("C2 발견 재료 없음(첫 판·발견 끔) = 종전 빠른 판(wallet_extra 없음 · 거르기 없음)", fx_kw[-1] == {} and len(flt) == 1 and "_filtered" not in b3)
rex = []
token_discovery.recon_extra_safe = lambda p, **k: rex.append(p) or {"extra": {W: {CA_Z}}, "status": {W: "ok"}}
b4 = core_recon.ReconMixin._prov_fastx("bsc", prep, lambda **k: fx_kw.append(k) or {"per_wallet": {}}, full=True)
check("C2 full(BSC 발견 포함 판) = 전체 발견(recon_extra) + 같은 멀티콜 조회 + 거르기", rex == [prep] and fx_kw[-1] == {"wallet_extra": {W: {CA_Z}}}
      and b4.get("_filtered") == 1, (rex, fx_kw[-1]))

c.my_wallets = {"eth": {W}, "base": {W}}
c.sol_wallets = set()
c.chain_owners = {}
calls, gates = [], {}


def fake_plan(chain, kind, ws, mode=None, latest=False):
    calls.append((chain, mode))
    ev = gates.setdefault(len(calls), threading.Event())

    def run():
        ev.wait(5)
        return {"per_wallet": {w: {("native", None): 1} for w in ws}, "_meta": {}, "_source": "rpc", "_queried": {w: [] for w in ws}}
    return run


def settle():
    for _ in range(300):
        for ev9 in list(gates.values()):
            ev9.set()
        if all(j["ev"].is_set() for j in c.svc_recon._prov_jobs.values()):
            return
        time.sleep(0.01)


c.svc_recon._recon_fetch_plan = fake_plan
c.svc_recon._prov_alch_ok = lambda ch9: ch9 == "base"
c.svc_recon._prov_last = 0
c.svc_recon.prov_pass()
check("C3 첫 판 = 두 체인 빠른 판(fast) 동시 · 순서 = 큰 몫 먼저(eth → base)", calls == [("eth", "fast"), ("base", "fast")], calls)
settle()
c.svc_recon.prov_pass()
n1 = len(calls)
pf = json.load(open(PF))
check("C3 수확 직후 Alchemy 되는 체인(base) = 기다림 없이 둘째 판(fastx) · eth(안 됨) = 기다림 없이 발견 포함 판(다른 차선 — 동시)",
      pf["base"].get("fast") == 1 and pf["eth"].get("fast") == 1 and calls[2:] == [("eth", None), ("base", "fastx")], (pf, calls))
c.svc_recon._prov_last = 0
c.svc_recon.prov_pass()
check("C3 둘째 판은 한 번에 하나(도는 동안 더 안 시작)", len(calls) == n1, calls[n1:])
settle()
c.svc_recon.prov_pass()
pf = json.load(open(PF))
n2 = len(calls)
check("C3 둘째 판 결과 = fast 2 · eth 발견 포함 판 결과 = 표시 지움(그 뒤 간격 안 = 다시 안 물음)",
      pf["base"].get("fast") == 2 and not pf["eth"].get("fast") and n2 == n1, (pf, calls[n1:]))
for ch9 in pf:
    pf[ch9]["at"] = int(time.time()) - core_svc.ReconService.PROV_FAST_UPGRADE - 5
json.dump(pf, open(PF, "w"))
c.svc_recon._prov_last = 0
c.svc_recon.prov_pass()
check("C4 Alchemy 둘째 판(fast 2) → PROV_FAST_UPGRADE 뒤 = 발견 포함 판(mode None) · 이미 받은 eth = 안 물음", calls[n2:] == [("base", None)], calls[n2:])
settle()
c.svc_recon.prov_pass()

WP = "0x" + "77" * 20
bal_p = {"per_wallet": {W: {("native", None): 1}, WP: {("native", None): 2}}, "_meta": {}}
bp1 = real_filter({"per_wallet": dict(bal_p["per_wallet"]), "_meta": {}}, {"chain": "base", "off": False}, {"status": {WP: "pending"}})
bp2 = real_filter({"per_wallet": dict(bal_p["per_wallet"]), "_meta": {}}, {"chain": "base", "off": False}, {"status": {WP: "pending"}}, keep_pending=True)
check("P1 filter_result: 대사(기본) = 발견 진행 중 지갑 보류(종전) · 임시 잔고(keep_pending) = 빼지 않음(받은 칸 그대로)",
      WP not in bp1["per_wallet"] and WP in bp1.get("_hold", {}) and WP in bp2["per_wallet"] and not bp2.get("_hold")
      and bp2["_disc"]["status"] == {WP: "pending"}, (bp1, bp2))
calls.clear()
gates.clear()
pend_once = [True]


def plan_p(chain, kind, ws, mode=None, latest=False):
    calls.append((chain, mode))
    st9 = {"status": {ws[0]: "pending"}} if (chain == "eth" and mode is None and pend_once[0]) else {"status": {}}
    if chain == "eth" and mode is None:
        pend_once[0] = False
    return lambda: {"per_wallet": {w: {("native", None): 1} for w in ws}, "_meta": {}, "_source": "rpc", "_queried": {w: [] for w in ws}, "_disc": st9}


c.svc_recon._recon_fetch_plan = plan_p
pf = json.load(open(PF))
pf["eth"]["fast"] = 1
json.dump(pf, open(PF, "w"))
c.svc_recon._prov_last = 0
c.svc_recon.prov_pass()
settle()
c.svc_recon.prov_pass()
pf = json.load(open(PF))
check("P2 발견 포함 판에 시간 상한 지갑이 남음 = fast 3 표시 · 다음 바퀴 바로 이어 받기(캐시로 이어짐)", pf["eth"].get("fast") == 3
      and calls == [("eth", None), ("eth", None)], (pf["eth"].get("fast"), calls))
settle()
c.svc_recon.prov_pass()
pf = json.load(open(PF))
n9 = len(calls)
c.svc_recon._prov_last = 0
c.svc_recon.prov_pass()
check("P2 다 끝나면 표시 지움 · 그 뒤 간격 안 = 다시 안 물음", not pf["eth"].get("fast") and len(calls) == n9, (pf["eth"], calls))
del c.svc_recon._recon_fetch_plan

cap, disc = [], []
recon.fetch_evm_rpc_balances = lambda *a, **k: cap.append(k) or {"per_wallet": {}, "_source": "rpc", "_block": 1, "_multicall": False, "_hold": {}}
recon._rpc_any = lambda *a, **k: 0
c.svc_recon._disc_prep = lambda *a, **k: disc.append(a) or {"chain": a[0], "off": False, "sigs": {}}
c.svc_recon._recon_fetch_plan("base", "evm", [W], "fastx", latest=True)()
check("C5 'fastx' = 발견 재료 만들고(_disc_prep) 둘째 판(wallet_extra · 거르기)", len(disc) == 1 and cap[-1].get("wallet_extra") == ex1["extra"]
      and cap[-1].get("discover_url") is None and cap[-1].get("block") is None, (disc, cap[-1]))
c.svc_recon._recon_fetch_plan("base", "evm", [W], "fast", latest=True)()
check("C5 'fast' = 발견 재료 없음 · wallet_extra 없음(종전 빠른 판)", len(disc) == 1 and "wallet_extra" not in cap[-1], cap[-1])

import importlib  # noqa: E402
recon2 = importlib.reload(recon)
SOLS = ["So" + str(i).rjust(42, "x") for i in range(205)]
rpcs_log = []
lock9 = threading.Lock()
FAIL_PRIMARY = {SOLS[3]}
DEAD = {SOLS[7]}


def fake_rpc(url, method, params, **k):
    with lock9:
        rpcs_log.append((url, method, params[0] if method != "getMultipleAccounts" else len(params[0])))
    if method == "getMultipleAccounts":
        if url == "https://head.invalid" and len(rpcs_log) == 1:
            raise RuntimeError("head down")
        return {"value": [None if a == SOLS[0] else {"lamports": 10 + i} for i, a in enumerate(params[0])]}
    if method == "getBalance":
        return {"value": 1}
    o = params[0]
    if o in DEAD or (o in FAIL_PRIMARY and url == "https://hel.invalid"):
        raise RuntimeError("429")
    if params[1]["programId"].startswith("Tokenz"):
        return {"value": []}
    return {"value": [{"account": {"data": {"parsed": {"info": {"mint": "M1", "tokenAmount": {"amount": "5", "decimals": 6}}}}}}]}


recon2._rpc = fake_rpc
rs = recon2.fetch_sol_balances_fast(["https://hel.invalid", "https://arch.invalid"], SOLS, native_url="https://head.invalid", workers=4)
gma = [x for x in rpcs_log if x[1] == "getMultipleAccounts"]
toks = [x for x in rpcs_log if x[1] == "getTokenAccountsByOwner"]
check("S1 네이티브 = getMultipleAccounts 100개 묶음(205 지갑 = 3묶음 · head 차선 · 실패 묶음만 주 RPC) · 없는 계정 = 0 · 지갑마다 getBalance 0콜",
      [(x[0], x[2]) for x in gma] == [("https://head.invalid", 100), ("https://hel.invalid", 100), ("https://head.invalid", 100), ("https://head.invalid", 5)]
      and rs["per_wallet"][SOLS[0]][("native", None)] == 0 and rs["per_wallet"][SOLS[1]][("native", None)] == 11
      and not any(x[1] == "getBalance" for x in rpcs_log), gma)
check("S1 토큰 = 지갑 × (Token · Token-2022) 병렬 · 주 RPC + 공개 차선 둘 다 씀 · 합산·소수",
      len({x[0] for x in toks}) == 2 and rs["per_wallet"][SOLS[1]][("token", "M1")] == 5 and rs["_meta"]["M1"] == (None, 6), {x[0] for x in toks})
check("S1 한 차선 실패 = 다른 차선으로(그 지갑 살림) · 끝내 실패 = 그 지갑만 _hold(0 으로 안 보임) · 나머지 지갑 그대로",
      SOLS[3] in rs["per_wallet"] and SOLS[7] not in rs["per_wallet"] and SOLS[7] in rs["_hold"] and len(rs["per_wallet"]) == 204, rs["_hold"])
DEAD = set(SOLS[:3])
try:
    recon2.fetch_sol_balances_fast(["https://hel.invalid"], SOLS[:3])
    ok9 = False
except RuntimeError:
    ok9 = True
check("S1 전 지갑 실패 = 예외(빈 칸으로 1시간 막지 않음 — 다음 바퀴)", ok9)
DEAD = set()
rpcs_log.clear()
recon2.fetch_sol_balances("https://hel.invalid", SOLS[:2])
check("S1 대사 경로(fetch_sol_balances) = 종전 그대로(지갑마다 getBalance + 토큰 2콜 · 한 줄)",
      [x[1] for x in rpcs_log] == ["getBalance", "getTokenAccountsByOwner", "getTokenAccountsByOwner"] * 2, rpcs_log)
c.cfg["sol"] = {"rpc": "helius"}
ln, nat = c.svc_recon._prov_sol_lanes("https://mainnet.helius-rpc.com/?api-key=x")
ln2, nat2 = c.svc_recon._prov_sol_lanes("https://my-sol.invalid")
check("S2 차선: 헬리우스 = [헬리우스, mainnet-beta(토큰 1스레드)] + 네이티브 publicnode · 헬리우스 아님 = 주 RPC 만(종전 노드)",
      ln == ["https://mainnet.helius-rpc.com/?api-key=x", "https://api.mainnet-beta.solana.com"] and nat == "https://solana-rpc.publicnode.com"
      and (ln2, nat2) == (["https://my-sol.invalid"], None), (ln, nat, ln2, nat2))

c.my_wallets = {ch9: {"0x" + str(i).rjust(40, "0") for i in range(n9)} for ch9, n9 in (("zora", 50), ("polygon", 3), ("eth", 1), ("base", 2), ("abstract", 9))}
c.cfg["chains"] = {ch9: dict(CHAINS["eth"]) for ch9 in c.my_wallets}
c.sol_wallets = {SW}
c.chain_owners = {}
calls, gates = [], {}
c.svc_recon._recon_fetch_plan = fake_plan
c.svc_recon._prov_jobs = {}
if os.path.exists(PF):
    os.remove(PF)
c.svc_recon.PROV_PAR = 3
c.svc_recon._prov_last = 0
c.svc_recon.prov_pass()
first3 = [x[0] for x in calls]
settle()
c.svc_recon.prov_pass()
check("O1 첫 판 순서 = 큰 몫 기본 순위(eth·base·sol …) 먼저 → 그다음 지갑 수 많은 체인(zora 50 > abstract 9)",
      first3 == ["eth", "base", "sol"] and [x[0] for x in calls if x[1] == "fast" or x[0] == "sol"][:6] == ["eth", "base", "sol", "polygon", "zora", "abstract"], calls)
settle()
del c.svc_recon._recon_fetch_plan
c.svc_recon.PROV_PAR = core_svc.ReconService.PROV_PAR

loads = []
real_load = config.load_config
config.load_config = lambda *a, **k: loads.append(1) or real_load(*a, **k)
json.dump({"pairs": {}}, open(paths.ACTIVITY_GATE_PATH, "w"))
c.svc_recon._gate_at = 0
c.svc_recon._gate_reload()
n_e = len(loads)
c.svc_recon._gate_reload()
check("E1 10분 안 · 파일 그대로 = 다시 안 읽음(종전 주기)", len(loads) == n_e, loads)
time.sleep(0.01)
json.dump({"pairs": {"monad:" + W: {"active": True}}}, open(paths.ACTIVITY_GATE_PATH, "w"))
c.svc_recon._gate_reload()
check("E1 게이트 파일 바뀜(tj-web 첫 점검 · 기동 4분 뒤) = 10분 기다리지 않고 바로 합류 판정", len(loads) == n_e + 1, loads)
json.dump({"chains": {"monad": {}}}, open(paths.BACKFILL_SPEED_PATH, "w"))
c.svc_recon._gate_reload()
check("E1 속도 실측 파일 바뀜(첫 점검 직후 실측) = 바로 다시 합류 판정", len(loads) == n_e + 2, loads)
c.svc_recon._gate_reload()
check("E1 그 뒤 그대로면 다시 10분 주기", len(loads) == n_e + 2, loads)
config.load_config = real_load

c.conn.close()

import db as dbm  # noqa: E402
import web  # noqa: E402

cb = dbm.open_db(os.path.join(T.TMP, "b4_stake.db"))
cb.execute("INSERT INTO asset_groups (group_id, name, norm_decimals) VALUES (91, 'SOL#b4', 18)")
cb.execute("INSERT INTO assets (asset_id, kind, chain, address, symbol, decimals, confirmed, hidden, group_id) VALUES (91, 'native', 'sol', NULL, 'SOL', 9, 1, 0, 91)")
T_WD = int(NOW) - 1800
for pid9, loc9, q9 in ((1, f"wallet:sol:{SW}:stake:{PK1}", -200), (2, f"wallet:sol:{SW}", 200)):
    cb.execute("INSERT INTO postings (posting_id, source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd,"
               " cost_krw, leg_kind, event, classifier_ver) VALUES (?, 'chain_tx', 'sol', 'sigB4', ?, ?, 91, ?, ?, NULL, NULL, 'move', 'withdraw_stake', 5)",
               (pid9, pid9, T_WD, loc9, str(q9 * 10 ** 9)))
cb.commit()
bal4 = {"per_wallet": {SW: {("native", None): 200 * 10 ** 9}, f"{SW}:stake:{PK1}": {("native", None): 200 * 10 ** 9}}, "_meta": {}}
pk4 = core_prov.ProvMixin._prov_pack(bal4, "chain", NOW - 5, req=[SW], t1=NOW - 4, kind="sol")
pk4["stake_ts"] = int(NOW) - 3000
json.dump({"sol": pk4}, open(PF, "w"))
its4 = web.StateBuilder._prov_items(object(), cb)
tot4 = sum((it["qty"] for it in its4 if it.get("qty") is not None), Decimal(0))
check("B4 스냅숏 뒤 스테이크 인출 = 지갑 200 + 스테이크 0 → 임시 몫 합 200(원장 지금 0 + 200) · 400 으로 이중 계상 안 함",
      tot4 == Decimal(200), [(it["loc"], it["qty"]) for it in its4])
cb.close()
os.remove(PF)
T.finish()
