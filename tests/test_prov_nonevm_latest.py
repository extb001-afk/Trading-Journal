#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
from _ingest import check  # noqa: E402
import _btcfake as BF  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

import config, paths  # noqa: E402
import core  # noqa: E402
import core_svc  # noqa: E402
import core_recon  # noqa: E402
import address_codec as ac  # noqa: E402
import btc_descriptor as bd  # noqa: E402
import chain_event as ce  # noqa: E402
import chain_registry as reg  # noqa: E402
import chain_state as cs  # noqa: E402
import btc_watch as bw  # noqa: E402
from inbox import SegmentWriter  # noqa: E402

T.patch_moved("dm", lambda *a, **k: None)

ZPUB84 = "zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1m4wAcvPhXNfE3EfH1r1ADqtfSdVCToUG868RvUUkgDKf31mGDtKsAYz2oz2AGutZYs"
D = bd.descriptor_from_xpub(ZPUB84)
P = bd.plan_from_descriptor(D)
W2ADDR = "bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr"
X0, X1 = "1LqBGSKuX5yYUonjxT5qGfpUsXKYYWeabA", "1J3J6EvPrv8q6AC3VCjWV45Uf3nssNMRtH"
BTC = 10 ** 8
CFG_PATH = os.path.join(T.TMP, "config.json")
cfg0 = json.load(open(CFG_PATH))
cfg0["chain_wallets"] = [{"chain": "btc", "mode": "descriptor", "descriptor": D, "label": "hd"},
                         {"chain": "btc", "mode": "address", "address": W2ADDR, "label": "one"}]
cfg0["nonevm"] = BF.cfg_nonevm()
json.dump(cfg0, open(CFG_PATH, "w"))
cfg = config.load_config()
HD = ac.btc_wallet_id(D)
W2 = sorted(reg.owners(cfg, "btc") - {HD})[0]
OWN = {HD, W2}
fc = BF.FakeChain()


def receive(addr, value, fee=1000):
    f = fc.fund(X0, value + fee)
    return fc.spend([(f, 0)], [(addr, value)], fee)


old = receive(P.derive(0, 0)[1], 2 * BTC)
fc.mine(t=int(time.time()) - 400 * 86400)
a2 = receive(W2ADDR, BTC // 5)
fc.mine()
fc.mine_empty(3)
ad = bw.BtcAdapter(cfg, transport=fc.transport)
st = cs.ChainState("btc")
ad.bind(st)
col = bw.BtcCollector(ad, SegmentWriter(os.path.join(paths.INBOX_DIR, "btc")), st, OWN)
for _i in range(6):
    col.cycle()
ok_bal = bw.BtcAdapter(cfg, transport=fc.transport).fetch_balances(OWN, None)
sd = cs.ChainState("btc")
for wid9, w9 in (sd.d["btc"].get("wallets") or {}).items():
    w9["hist_done"] = False
    w9["own_F"] = None
sd.save()
r_rec = T.safe(bw.BtcAdapter(cfg, transport=fc.transport).fetch_balances, OWN, None)
check("EC1a (전제) 대사 경로 = 훑기 미완이면 보류(예외 — 종전)", isinstance(r_rec, dict) and "_exc" in r_rec, r_rec)
r_lat = T.safe(bw.BtcAdapter(cfg, transport=fc.transport).fetch_balances, OWN, None, latest=True)
check("EC1a BTC 임시 잔고(latest) = 훑기 미완이어도 지금 확정 높이 잔고(완료 상태 대사와 같은 값 · 경계 · validate 통과)",
      isinstance(r_lat, dict) and "_exc" not in r_lat and r_lat.get("per_wallet") == ok_bal["per_wallet"]
      and ce.validate_balances(r_lat, "btc", OWN)["ok"], (r_lat, ok_bal.get("per_wallet")))

reg.FORCE_AVAILABLE.add("btc")
c = core.Core(config.load_config())
c.conn.commit()
seen = []


class FakeAd:
    def __init__(self, why):
        self.why = why

    def fetch_balances(self, owners, boundary, tokens=None, **kw):
        seen.append(dict(kw))
        return {"per_wallet": {o: {("native", None): 5} for o in owners}, "_meta": {}, "_boundary": {"kind": "account_lt", "value": "lt:x", "ts": 100},
                "_complete": not self.why, "_why": list(self.why), "_unobserved": {}, "_source": "x"}


c.svc_recon.__dict__["_nonevm_adapters"] = {"btc": FakeAd([])}
r9 = T.safe(c.svc_recon._recon_fetch_plan("btc", "nonevm", sorted(OWN), None, latest=True))
check("EC1b BTC 임시 잔고 계획 = 어댑터에 latest 전달", seen and seen[-1].get("latest") is True and isinstance(r9, dict) and "_exc" not in r9, (seen, r9))
seen.clear()
T.safe(c.svc_recon._recon_fetch_plan("btc", "nonevm", sorted(OWN), None))
check("EC1b BTC 대사 계획 = latest 안 넘김(종전 호출 그대로)", seen and "latest" not in seen[-1], seen)
TW = ["0:" + "a" * 64]
orig_spec = reg.spec
c.svc_recon.__dict__["_nonevm_adapters"]["ton"] = FakeAd(["wallet_lt_ahead", "pending_details"])
sp_ton = orig_spec("ton")
r_t = T.safe(c.svc_recon._nonevm_fetch_plan("ton", TW, None, latest=True))
check("EC1b TON 원장 뒤처짐 사유만 = 임시 잔고로 씀(지금 관측값)", isinstance(r_t, dict) and "_exc" not in r_t and r_t.get("per_wallet", {}).get(TW[0]), r_t)
r_t2 = T.safe(c.svc_recon._nonevm_fetch_plan("ton", TW, None))
check("EC1b TON 대사 경로 = 종전 보류(예외)", isinstance(r_t2, dict) and "_exc" in r_t2, r_t2)
c.svc_recon.__dict__["_nonevm_adapters"]["ton"] = FakeAd(["wallet_lt_ahead", "jetton_list_partial"])
r_t3 = T.safe(c.svc_recon._nonevm_fetch_plan("ton", TW, None, latest=True))
check("EC1b TON 그 밖 사유(제톤 목록 일부) 섞임 = 임시 잔고도 보류(종전)", isinstance(r_t3, dict) and "_exc" in r_t3, r_t3)

SW = "So1" + "a" * 40
PF = os.path.join(paths.STATE_DIR, "prov_bal.json")
SP = os.path.join(paths.STATE_DIR, "sol_stake.json")
c.my_wallets = {}
c.sol_wallets = {SW}
c.chain_owners = {}
c.cfg["chains"] = {}
calls = []


def fake_plan(chain, kind, ws, mode=None, latest=False):
    calls.append(chain)

    def run():
        return core_recon.ReconMixin._prov_sol_fetch("u", ws)
    return run


import recon  # noqa: E402
recon.fetch_sol_balances_fast = lambda lanes, ws, native_url=None, **k: {"per_wallet": {w: {("native", None): 5} for w in ws}, "_meta": {}}
T.patch_cls_attr(core_svc.ReconService, "_prov_sol_stake_live", staticmethod(lambda url, pks, native_url=None: {pk: 7 for pk in pks}))
c.svc_recon._recon_fetch_plan = fake_plan
if os.path.exists(SP):
    os.remove(SP)


def settle():
    for _ in range(300):
        if all(j["ev"].is_set() for j in c.svc_recon.__dict__.get("_prov_jobs", {}).values()):
            return
        time.sleep(0.01)


c.svc_recon._prov_last = 0
c.svc_recon.prov_pass()
settle()
c.svc_recon._prov_last = 0
c.svc_recon.prov_pass()
pf = json.load(open(PF))
check("EC2 (전제) 첫 SOL 임시 잔고 = 스냅숏 없음 → 지갑만", calls == ["sol"] and list((pf.get("sol") or {}).get("wallets") or {}) == [SW], (calls, pf))
c.svc_recon._prov_last = 0
c.svc_recon.prov_pass()
check("EC2 스냅숏 그대로 = 다시 안 받음(종전 간격)", calls == ["sol"], calls)
json.dump({"ts": int(time.time()), "accounts": {"Stk" + "1" * 40: {"w": SW, "lamports": 200 * 10 ** 9}}}, open(SP, "w"))
c.svc_recon._prov_last = 0
c.svc_recon.prov_pass()
settle()
c.svc_recon._prov_last = 0
c.svc_recon.prov_pass()
pf = json.load(open(PF))
check("EC2 스테이크 스냅숏이 새로 생김 = 1시간 기다리지 않고 다시 받음 → 스테이크 칸 실림",
      calls == ["sol", "sol"] and any(":stake:" in k for k in (pf.get("sol") or {}).get("wallets") or {}), (calls, pf))
c.svc_recon._prov_last = 0
c.svc_recon.prov_pass()
check("EC2 같은 세대 = 다시 안 받음", calls == ["sol", "sol"], calls)
del c.svc_recon._recon_fetch_plan
c.conn.close()
T.finish()
