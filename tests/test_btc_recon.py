#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
from _ingest import check  # noqa: E402
import _btcfake as BF  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

import config, paths  # noqa: E402
import core  # noqa: E402
import address_codec as ac  # noqa: E402
import btc_descriptor as bd  # noqa: E402
import chain_event as ce  # noqa: E402
import chain_registry as reg  # noqa: E402
import chain_state as cs  # noqa: E402
import btc_watch as bw  # noqa: E402
from inbox import SegmentWriter  # noqa: E402

ZPUB84 = "zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1m4wAcvPhXNfE3EfH1r1ADqtfSdVCToUG868RvUUkgDKf31mGDtKsAYz2oz2AGutZYs"
D = bd.descriptor_from_xpub(ZPUB84)
P = bd.plan_from_descriptor(D)
W2ADDR = "bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr"
X0, X1 = "1LqBGSKuX5yYUonjxT5qGfpUsXKYYWeabA", "1J3J6EvPrv8q6AC3VCjWV45Uf3nssNMRtH"
BTC = 10 ** 8
CFG_PATH = os.path.join(T.TMP, "config.json")
INB = os.path.join(paths.INBOX_DIR, "btc")


def R(i):
    return P.derive(0, i)[1]


def C(i):
    return P.derive(1, i)[1]


cfg0 = json.load(open(CFG_PATH))
cfg0["chain_wallets"] = [{"chain": "btc", "mode": "descriptor", "descriptor": D, "label": "hd"},
                         {"chain": "btc", "mode": "address", "address": W2ADDR, "label": "one"}]
cfg0["nonevm"] = BF.cfg_nonevm()
json.dump(cfg0, open(CFG_PATH, "w"))
cfg = config.load_config()
HD = ac.btc_wallet_id(D)
W2 = sorted(reg.owners(cfg, "btc") - {HD})[0]
OWN = {HD, W2}
HD_ADDRS = {R(i) for i in range(40)} | {C(i) for i in range(40)}
fc = BF.FakeChain()


def onchain(addrs, upto=None):
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


def receive(addr, value, fee=1000, t=None):
    f = fc.fund(X0, value + fee)
    return fc.spend([(f, 0)], [(addr, value)], fee)


old = receive(R(0), 2 * BTC)
fc.mine(t=int(time.time()) - 400 * 86400)
fc.mine_empty(2)
a1 = receive(R(1), BTC)
a2 = receive(W2ADDR, BTC // 5)
fc.mine()
s1 = fc.spend([(old, 0)], [(X1, 150_000_000), (C(0), 49_990_000)], 10_000)
fc.mine()
fc.mine_empty(3)
ad = bw.BtcAdapter(cfg, transport=fc.transport)
st = cs.ChainState("btc")
ad.bind(st)
w = SegmentWriter(INB)
col = bw.BtcCollector(ad, w, st, OWN)

adq = bw.BtcAdapter(cfg, transport=fc.transport)
r = T.safe(adq.fetch_balances, OWN, None)
check("Q3 과거 훑기 미완 = 예외(0 잔고 아님)", isinstance(r, dict) and "_exc" in r, r)
for _i in range(6):
    col.cycle()
check("(전제) 수집 동기화", bool(st.d.get("synced_at")))
up = receive(R(2), 30_000_000)
fc.mine([up])
mem = receive(R(3), 1234)
for _i in range(2):
    col.cycle()

adq = bw.BtcAdapter(cfg, transport=fc.transport)
bal = adq.fetch_balances(OWN, None)
F = fc.height - 3 + 1
chk = ce.validate_balances(bal, "btc", OWN)
check("Q1 반환 계약 통과(지갑 전부 · 경계 · 완전)", chk["ok"] and set(bal["per_wallet"]) == OWN, chk)
b9 = bal["_boundary"]
check("Q1 경계 = 확정 높이 F(= 수집기가 소유 범위·이력을 확인한 높이) · 그 블록 해시·시각", b9["kind"] == "height" and b9["value"] == F
      and F == cs.ChainState("btc").d["btc"]["wallets"][HD]["own_F"] and b9["hash"] == fc._blk(F)[1] and b9["ts"] == fc._blk(F)[2], (b9, F))
check("Q2 HD 잔고 = 높이 F 까지 확정 거래만(F 위 0.3 BTC · mempool 제외)", bal["per_wallet"][HD][("native", None)] == onchain(HD_ADDRS, F)
      and onchain(HD_ADDRS) - onchain(HD_ADDRS, F) == 30_000_000, (bal["per_wallet"][HD], onchain(HD_ADDRS, F)))
check("Q5 단일 주소 지갑 잔고 = 0.2 BTC", bal["per_wallet"][W2][("native", None)] == BTC // 5, bal["per_wallet"][W2])

real = fc.transport
n_calls = {"n": 0, "mine_at": 6, "always": False}


def moving(url):
    n_calls["n"] += 1
    if n_calls["n"] == n_calls["mine_at"] or (n_calls["always"] and "/address/" in url and url.endswith("/address/" + R(0))):
        fc.mine_empty(1)
    return real(url)


adm = bw.BtcAdapter(cfg, transport=moving)
bal2 = adm.fetch_balances(OWN, None)
F2 = fc.height - 3 + 1
Fb2 = bal2["_boundary"]["value"]
check("Q3 읽는 사이 새 블록 1번 = 다시 읽어 맞춤 · 경계는 수집기가 확인한 높이(새 블록을 안 훑었으면 그 아래) · 잔고 = 그 경계 체인 잔고",
      Fb2 == min(F2, cs.ChainState("btc").d["btc"]["wallets"][HD]["own_F"]) and
      bal2["per_wallet"][HD][("native", None)] == onchain(HD_ADDRS, Fb2), (bal2["_boundary"], F2))
n_calls.update(n=0, mine_at=-1, always=True)
r = T.safe(adm.fetch_balances, OWN, None)
check("Q3 매번 새 블록 = 예외(다음 주기 · 0 잔고 아님)", isinstance(r, dict) and "_exc" in r, r)
n_calls.update(always=False)
fc.fail_next(1, "http429", match="/address/")
r = T.safe(bw.BtcAdapter(cfg, transport=fc.transport).fetch_balances, OWN, None)
check("Q3 제공자 오류 = 예외(0 잔고 아님)", isinstance(r, dict) and "_exc" in r, r)


def shifted(url):
    d = real(url)
    return [dict(b, height=b["height"] - 1) for b in d] if "/blocks/" in url else d


adw = bw.BtcAdapter(cfg, transport=shifted)
r = T.safe(adw.fetch_balances, OWN, None)
check("Q3 대사 확정 경계 첫 블록 높이 ≠ 요청 = 예외 + 그 제공자 경계(bnd) 실패 1회로 셈(tip 성공이 지우지 않음)",
      isinstance(r, dict) and "_exc" in r and (adw.es.bad.get("bnd") or (0,))[0] == 1 and "tip" not in adw.es.bad, (r, adw.es.bad))

reg.FORCE_AVAILABLE.add("btc")
c = core.Core(config.load_config())
c.conn.commit()


def drain():
    rd = dict(c.chain_readers)["btc"]
    for _i in range(50):
        row = c.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream='btc'").fetchone()
        seg, off = (row["seg"], row["off"]) if row else (1, 0)
        c._drain_stream("btc", rd, seg, off)
        row2 = c.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream='btc'").fetchone()
        if row2 and row and (row2["seg"], row2["off"]) == (seg, off):
            break
    c.conn.commit()


def wsum(wid):
    r9 = c.conn.execute("SELECT SUM(CAST(qty_base AS INTEGER)) FROM postings WHERE location=?", (reg.make_location("btc", wid),)).fetchone()
    return int(r9[0] or 0)


def openings():
    return {(r9["location"], int(r9["q"])) for r9 in c.conn.execute(
        "SELECT p.location, p.qty_base AS q FROM postings p WHERE p.source_kind='opening' AND p.source_ns='btc'")}


drain()
check("(전제) 창 이전 거래는 원장에 없음(창 안 3건)", c.conn.execute("SELECT COUNT(*) FROM raw_txs WHERE chain='btc'").fetchone()[0] == 3)
for _i in range(3):
    col.cycle()
drain()
up2 = receive(R(4), 40_000_000)
fc.mine([up2])
for _i in range(2):
    col.cycle()
c.svc_recon._nonevm_adapters = {"btc": bw.BtcAdapter(c.cfg, transport=fc.transport)}
check("Q4 (전제) 수집기 준비(도장 신선·백필 완료·대기 0)", c.svc_recon._scope_ready("btc"))
c.svc_recon._last_recon = 0
c.svc_recon.recon_pass({"btc"})
if not c._meta_get("recon_done_btc"):
    for _i in range(40):
        time.sleep(0.05)
        c.svc_recon._last_recon = 0
        c.svc_recon.recon_pass({"btc"})
        if c._meta_get("recon_done_btc"):
            break
check("Q4 대사 완료 도장", bool(c._meta_get("recon_done_btc")))
check("Q4 (전제) 경계 위 0.4 BTC 는 대사 때 원장에 없음", c.conn.execute("SELECT COUNT(*) FROM raw_txs WHERE chain='btc' AND txhash=?", (up2,)).fetchone()[0] == 0)
op = openings()
check("Q4 기초 잔고 = 창 이전 보유 2 BTC(HD) · 단일 주소 지갑 0", op == {(reg.make_location("btc", HD), 2 * BTC)}, op)
pay = json.loads(c.conn.execute("SELECT payload FROM raw_observations WHERE obs_id='recon:btc'").fetchone()[0])
check("Q4 관측 payload = 경계 블록(확정 높이)", isinstance(pay.get("_block"), int) and pay["_block"] <= fc.height - 2, pay.get("_block"))
fc.mine_empty(3)
for _i in range(4):
    col.cycle()
drain()
check("Q4 경계 위 0.4 BTC 는 확정 뒤 원장에 1번", c.conn.execute("SELECT COUNT(*) FROM raw_txs WHERE chain='btc' AND txhash=?", (up2,)).fetchone()[0] == 1)
check("Q4 경계 뒤 0.4 BTC 는 확정 뒤 기장 · 지갑 칸 = 체인 잔고(이중 계상 없음)", wsum(HD) == onchain(HD_ADDRS) and wsum(W2) == onchain({W2ADDR}),
      (wsum(HD), onchain(HD_ADDRS), wsum(W2), onchain({W2ADDR})))
reg.FORCE_AVAILABLE.clear()
T.finish()
