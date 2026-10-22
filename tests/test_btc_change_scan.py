#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
from _ingest import check  # noqa: E402
import _btcfake as BF  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402

import config, paths  # noqa: E402
import address_codec as ac  # noqa: E402
import btc_descriptor as bd  # noqa: E402
import chain_event as ce  # noqa: E402
import chain_registry as reg  # noqa: E402
import chain_state as cs  # noqa: E402
import btc_watch as bw  # noqa: E402

ZPUB84 = "zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1m4wAcvPhXNfE3EfH1r1ADqtfSdVCToUG868RvUUkgDKf31mGDtKsAYz2oz2AGutZYs"
D = bd.descriptor_from_xpub(ZPUB84)
P = bd.plan_from_descriptor(D)
A1ADDR = "bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr"
X0, X1 = "1LqBGSKuX5yYUonjxT5qGfpUsXKYYWeabA", "1J3J6EvPrv8q6AC3VCjWV45Uf3nssNMRtH"
BTC = 10 ** 8
CFG_PATH = os.path.join(T.TMP, "config.json")
HD = ac.btc_wallet_id(D)


def R(i):
    return P.derive(0, i)[1]


def C(i):
    return P.derive(1, i)[1]


def mkcfg(wallets, **kw):
    cfg = json.load(open(CFG_PATH))
    cfg["chain_wallets"] = wallets
    cfg["nonevm"] = BF.cfg_nonevm(**kw)
    json.dump(cfg, open(CFG_PATH, "w"))
    return config.load_config()


def world(cfg, fc, sd=None):
    st = cs.ChainState("btc", state_dir=sd or tempfile.mkdtemp(dir=T.TMP))
    ad = bw.BtcAdapter(cfg, transport=fc.transport).bind(st)
    wr = _ingest.Writer()
    return ad, st, wr, bw.BtcCollector(ad, wr, st, reg.owners(cfg, "btc"))


def recs(wr):
    d = {}
    for r in wr.recs:
        d.setdefault(r["tx_uid"], []).append(r)
    return d


def delta(r, wid):
    return sum(int(d["delta_base"]) for d in r["deltas"] if d["owner"] == wid)


def onchain(fc, addrs, upto=None):
    tot = 0
    for h, _hs, _t, txs in fc.blocks:
        if upto is not None and h > upto:
            continue
        for t in txs:
            raw = fc.txs[t]
            tot += sum(v for a, v in raw["vout"] if a in addrs)
            tot -= sum(fc.txs[v["txid"]]["vout"][v["vout"]][1] for v in raw["vin"]
                       if not v.get("coinbase") and fc.txs[v["txid"]]["vout"][v["vout"]][0] in addrs)
    return tot


def receive(fc, addr, value, fee=1000):
    f = fc.fund(X0, value + fee)
    return fc.spend([(f, 0)], [(addr, value)], fee)


def run(col, n):
    for _i in range(n):
        col.cycle()


fc = BF.FakeChain()
cfg = mkcfg([{"chain": "btc", "mode": "descriptor", "descriptor": D}], calls_per_page=5, latest_pages=5, history_pages=40)
fund = [receive(fc, R(i), BTC) for i in range(22)]
fc.mine()
fc.mine_empty(3)
ad, st, wr, col = world(cfg, fc)
run(col, 6)
check("K1 (전제) 과거 훑기 끝", ad.sb["wallets"][HD]["hist_done"])
chg = [fc.spend([(fund[i + 1], 0)], [(X1, BTC // 2), (C(i), BTC // 2 - 1000)], 1000) for i in range(21)]
tk = fc.spend([(fund[0], 0)], [(X1, 60_000_000), (C(21), 39_990_000)], 10_000)
fc.mine()
fc.mine_empty(3)
run(col, 12)
rk = recs(wr).get(tk, [])
check("K1 받는 갈래에서 찾은 거래의 잔돈(C21) = 내 것 — 순변화 −60,010,000(외부 송금으로 굳지 않음)",
      rk and all(delta(r, HD) == -60_010_000 for r in rk), [delta(r, HD) for r in rk])

fc = BF.FakeChain()
cfg = mkcfg([{"chain": "btc", "mode": "descriptor", "descriptor": D}, {"chain": "btc", "mode": "address", "address": A1ADDR}],
            calls_per_page=2, latest_pages=5, history_pages=20)
A1 = sorted(reg.owners(cfg, "btc") - {HD})[0]
fa = receive(fc, A1ADDR, BTC)
fb = receive(fc, R(0), BTC)
for i in range(1, 31):
    receive(fc, R(i), 1000 + i)
for i in range(0, 11):
    receive(fc, C(i), 2000 + i)
fc.mine()
tx2 = fc.spend([(fa, 0), (fb, 0)], [(X1, BTC), (C(30), BTC - 10_000)], 10_000)
fc.mine()
fc.mine_empty(3)
ad, st, wr, col = world(cfg, fc)
run(col, 10)
r2 = recs(wr).get(tx2, [])
check("K2 다른 HD 지갑 훑기 전에 그 지갑 잔돈(C30)을 외부로 기장하지 않음 — HD 순변화 −10,000(입력 1 BTC − 잔돈 0.9999 · 그중 수수료 몫 5,000)",
      r2 and all(delta(r, HD) == -10_000 for r in r2), [(delta(r, HD), r["fees"]) for r in r2])

fc = BF.FakeChain()
cfg = mkcfg([{"chain": "btc", "mode": "descriptor", "descriptor": D}], calls_per_page=2, latest_pages=40, history_pages=2)
many = [receive(fc, R(0), 1000 + k) for k in range(400)]
fc.mine(many[:200])
fc.mine(many[200:])
fc.mine_empty(3)
ad, st, wr, col = world(cfg, fc)
for _i in range(40):
    col.cycle()
    if (ad.sb["wallets"][HD]["pass"] or {}).get("phase") == "list" and (ad.sb["wallets"][HD]["pass"].get("c") or {}).get("ls"):
        break
check("K3 (전제) 과거 나열 도중(아직 완료 아님)", not ad.sb["wallets"][HD]["hist_done"], ad.sb["wallets"][HD]["pass"].get("phase"))
new = receive(fc, R(1), 777_777)
fc.mine()
fc.mine_empty(3)
for _i in range(2):
    col.cycle()
check("K3 과거 나열이 끝나기 전에도 새 확정 거래를 바로 보냄(옛 구간 작업에 안 붙잡힘)",
      new in recs(wr) and not ad.sb["wallets"][HD]["hist_done"], (new in recs(wr), ad.sb["wallets"][HD]["hist_done"]))
check("K3 과거 나열 끝나기 전엔 백필 완료(details_complete_through) 안 찍음",
      (st.d["status"].get(HD) or {}).get("details_complete_through") is None, st.d["status"].get(HD))
run(col, 80)
got = recs(wr)
check("K3 과거 나열 완료 뒤 거래 401건 전부 · 각 1번", ad.sb["wallets"][HD]["hist_done"] and set(many) | {new} <= set(got)
      and all(len(v) == 1 for v in got.values()), (ad.sb["wallets"][HD]["hist_done"], len(set(many) & set(got)), max(map(len, got.values()))))

fc = BF.FakeChain()
cfg = mkcfg([{"chain": "btc", "mode": "descriptor", "descriptor": D}], calls_per_page=40)
f4 = [receive(fc, R(i), BTC) for i in range(22)]
fc.mine()
fc.mine_empty(3)
ad, st, wr, col = world(cfg, fc, sd=paths.STATE_DIR)
run(col, 4)
check("K4 (전제) 동기화", ad.sb["wallets"][HD]["hist_done"] and st.d.get("synced_at"))
for i in range(21):
    fc.spend([(f4[i + 1], 0)], [(X1, BTC // 2), (C(i), BTC // 2 - 1000)], 1000)
fc.spend([(f4[0], 0)], [(X1, 1000), (C(21), BTC - 2000)], 1000)
fc.mine()
fc.mine_empty(3)
bal = bw.BtcAdapter(cfg, transport=fc.transport).fetch_balances({HD}, None)
Fb = bal["_boundary"]["value"]
HDA = {R(i) for i in range(80)} | {C(i) for i in range(80)}
check("K4 대사 경계 잔고 = 그 경계의 체인 잔고(소유 범위 확인 전 새 잔돈 주소를 빼고 '완전'으로 내지 않음)",
      bal["per_wallet"][HD][("native", None)] == onchain(fc, HDA, Fb), (Fb, bal["per_wallet"][HD], onchain(fc, HDA, Fb)))

fc = BF.FakeChain()
cfg = mkcfg([{"chain": "btc", "mode": "descriptor", "descriptor": D}])
f5 = receive(fc, R(0), BTC)
fc.mine()
t5 = fc.spend([(f5, 0)], [(X1, 60_000_000), (C(0), 39_990_000)], 10_000)
fc.mine()
fc.mine_empty(3)
real = fc.transport


def strip(url):
    d = real(url)
    if url.endswith("/tx/" + t5) and isinstance(d, dict):
        d["vout"][1].pop("scriptpubkey", None)
    if "/txs/chain" in url and isinstance(d, list):
        for t in d:
            if t.get("txid") == t5:
                t["vout"][1].pop("scriptpubkey", None)
    return d


ad5 = bw.BtcAdapter(cfg, transport=strip).bind(cs.ChainState("btc", state_dir=tempfile.mkdtemp(dir=T.TMP)))
ad5.begin_cycle()
r5 = T.safe(ad5.fetch_and_normalize, {"stable_id": t5, "owner": HD}, {HD})
check("K5 출력 scriptPubKey 빠짐 = 형식 오류(잔돈을 외부로 셈한 기록을 내지 않음)", isinstance(r5, dict) and "_exc" in r5, r5 if "_exc" in (r5 or {}) else
      [d["delta_base"] for d in r5["deltas"]])
r5b = T.safe(ad5._above, R(0), ac.btc_address(R(0))["script"], 0) if False else T.safe(ad5._above, C(0), ac.btc_address(C(0))["script"], 0)
check("K5 대사 _above 도 scriptPubKey 빠짐 = 오류(그 주소 몫을 0 으로 안 셈)", isinstance(r5b, dict) and "_exc" in r5b, r5b)

fc = BF.FakeChain()
cfg = mkcfg([{"chain": "btc", "mode": "descriptor", "descriptor": D}])
t6 = receive(fc, R(0), 123_456)
fc.mine()
fc.mine_empty(3)
ad, st, wr, col = world(cfg, fc)
fc.fail_next(1, "short", match="/address/" + R(0) + "/txs/chain")
run(col, 6)
check("K6 통계 1건 · 이력 빈 쪽 = 완료로 안 봄 → 다음 주기 회복 뒤 그 거래를 보냄", t6 in recs(wr), sorted(recs(wr))[:2])
T.finish()
