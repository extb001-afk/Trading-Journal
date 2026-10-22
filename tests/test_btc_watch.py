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

import config, paths, statefile  # noqa: E402
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


def R(i):
    return P.derive(0, i)[1]


def C(i):
    return P.derive(1, i)[1]


W2ADDR = "bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr"
X0, X1 = "1LqBGSKuX5yYUonjxT5qGfpUsXKYYWeabA", "1J3J6EvPrv8q6AC3VCjWV45Uf3nssNMRtH"
X2 = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
CFG_PATH = os.path.join(T.TMP, "config.json")
INB = os.path.join(paths.INBOX_DIR, "btc")
BTC = 10 ** 8


def set_cfg(wallets, **kw):
    cfg = json.load(open(CFG_PATH))
    cfg["chain_wallets"] = wallets
    cfg["nonevm"] = BF.cfg_nonevm(**kw)
    json.dump(cfg, open(CFG_PATH, "w"))
    return config.load_config()


WALLETS = [{"chain": "btc", "mode": "descriptor", "descriptor": D, "label": "hd"},
           {"chain": "btc", "mode": "address", "address": W2ADDR, "label": "one"}]
cfg = set_cfg(WALLETS)
HD = ac.btc_wallet_id(D)
W2 = reg.owners(cfg, "btc") - {HD}
W2 = sorted(W2)[0]
OWN = {HD, W2}
fc = BF.FakeChain()
w = SegmentWriter(INB)


def inbox():
    out = []
    for f in sorted(os.listdir(INB)) if os.path.isdir(INB) else []:
        if f.endswith(".jsonl"):
            out += [json.loads(ln) for ln in open(os.path.join(INB, f)) if ln.strip()]
    return out


def recs():
    d = {}
    for r in inbox():
        d.setdefault(r["tx_uid"], r)
    return d


def new_col(cfg9=None, owners=None):
    cfg9 = cfg9 or cfg
    ad = bw.BtcAdapter(cfg9, transport=fc.transport)
    st = cs.ChainState("btc")
    ad.bind(st)
    return ad, st, bw.BtcCollector(ad, w, st, owners or reg.owners(cfg9, "btc"))


def run(col, n=8):
    r = None
    for _i in range(n):
        r = col.cycle()
        if not r["left"] and col.st.d.get("synced_at") and not any(x.get("sweep") for x in col.ad.sb["wallets"].values()):
            break
    return r


def receive(addr, value, fee=1000):
    f = fc.fund(X0, value + fee)
    return fc.spend([(f, 0)], [(addr, value)], fee)


a1 = receive(R(0), BTC)
a2 = receive(R(5), BTC // 2)
fc.mine()
a3 = fc.spend([(a2, 0)], [(X1, BTC // 2 - 2000)], 2000)
a4 = receive(R(24), BTC // 5)
fc.mine()
a5 = fc.spend([(a1, 0)], [(X1, 60_000_000), (C(0), 39_990_000)], 10_000)
a6 = receive(R(50), 3 * BTC // 10)
cb = fc.fund(R(2), 625_000_000)
fc.mine()
many = [receive(R(1), 10_000 + k) for k in range(51)]
fc.mine(many[:30])
fc.mine(many[30:])
both = fc.spend([(a4, 0)], [(R(24), BTC // 10), (C(1), BTC // 10 - 1500)], 1500)
fc.mine()
fc.mine_empty(3)

ad, st, col = new_col()
r = run(col)
got = recs()
check("H1 HD 받는·잔돈 갈래 발견 — 사용 주소 거래 전부(외부 지급 coinbase 는 안 닿음)",
      {a1, a2, a3, a4, a5, cb, both} | set(many) <= set(got) and a6 not in got, (len(got), r))
check("H1 잔고 0 이지만 이력 있는 R5 뒤의 R24 도 찾음(사용 = 이력 기준)", a4 in got)
check("H1 gap 밖 R50 은 못 찾음(BIP44 gap 20 관행)", a6 not in got)
sv = bw.status_view(st)
check("H1 상태: HD 과거 훑기 끝 · 단일 주소 지갑 경고 notes", sv["wallets"][HD]["hist_done"] and "single_address" in sv["wallets"][W2]["notes"], sv)
check("H1 동기화 도장(오류 없음 · 대기 0)", bool(st.d.get("synced_at")) and r["left"] == 0, r)
r5 = got[a5]
check("H2 1 BTC 예: 순변화 −0.6001 · 수수료 0.0001 내 입력 지갑", [(d["owner"], d["delta_base"]) for d in r5["deltas"]] == [(HD, "-60010000")]
      and [(f["payer"], f["amount_base"]) for f in r5["fees"]] == [(HD, "10000")], (r5["deltas"], r5["fees"]))
core_v = ce.to_core(r5)
check("H2 경제 변화 = 외부 0.6 만(수수료 따로) · 보존식 통과", core_v["econ"] == {(HD, ("native", None)): -60_000_000}, core_v["econ"])
check("H2 목적지 = 외부 주소(잔돈은 내 것)", core_v["dest"].get((HD, ("native", None))) == X1, core_v["dest"])
check("H3 51건 쪽 넘김(25·25·1) 전부 · 같은 높이 동률 보존", set(many) <= set(got) and all(got[t]["order"]["height"] in (fc.where[many[0]], fc.where[many[-1]]) for t in many))
check("H3 같은 tx 가 내 주소 여러 개 = 1번(관점 owners 1 지갑)", sum(1 for x in inbox() if x["tx_uid"] == both) == 1 and got[both]["owners"] == [HD])
check("H3 R24 입력·출력 + C1 출력 = 순변화 −수수료만", [(d["owner"], d["delta_base"]) for d in got[both]["deltas"]] == [(HD, "-1500")], got[both]["deltas"])
check("H4 수신만 = 수수료 줄 없음", got[a1]["fees"] == [] and got[a1]["deltas"][0]["delta_base"] == str(BTC))
check("H4 coinbase 수신 = 검토 유입 힌트(program_in) · 수수료 없음", got[cb]["classification"]["hint"] == "program_in" and not got[cb]["fees"])
check("H13 기록 형식 = 계약 v1 통과(전부)", all(ce.validate(x) for x in got.values()))

cfg_r = set_cfg([dict(WALLETS[0], range_end=60), WALLETS[1]])
ad_r, st_r, col_r = new_col(cfg_r)
run(col_r)
check("H1 사용자 range_end 60 = gap 밖 R50 거래도 찾음", a6 in recs(), len(recs()))
cfg = set_cfg([dict(WALLETS[0], range_end=60), WALLETS[1]])

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


def ev(t):
    r9 = c.conn.execute("SELECT event FROM tx_class WHERE chain='btc' AND txhash=?", (t,)).fetchone()
    return r9["event"] if r9 else None


def wsum(wid):
    r9 = c.conn.execute("SELECT SUM(CAST(qty_base AS INTEGER)) FROM postings WHERE location=?", (reg.make_location("btc", wid),)).fetchone()
    return int(r9[0] or 0)


def onchain(wid_addrs, upto=None):
    tot = 0
    for h, _hs, _t, txs in fc.blocks:
        if upto is not None and h > upto:
            continue
        for t in txs:
            raw = fc.txs[t]
            tot += sum(v for a, v in raw["vout"] if a in wid_addrs)
            tot -= sum(fc.txs[v["txid"]]["vout"][v["vout"]][1] for v in raw["vin"]
                       if not v.get("coinbase") and fc.txs[v["txid"]]["vout"][v["vout"]][0] in wid_addrs)
    return tot


HD_ADDRS = {R(i) for i in range(0, 70)} | {C(i) for i in range(0, 30)}
drain()
check("H2 core: 1 BTC 예 = TRANSFER_OUT(보낸 내역 0.6) + 가스 0.0001", ev(a5) == "TRANSFER_OUT", ev(a5))
gas = c.conn.execute("SELECT SUM(CAST(qty_base AS INTEGER)) FROM postings WHERE source_id=? AND leg_kind='gas'", (a5,)).fetchone()[0]
check("H2 core: 가스 레그 = −10,000 sat(자릿수 8)", int(gas or 0) == -10_000, gas)
check("H4 core: coinbase = PROGRAM_IN(검토)", ev(cb) == "PROGRAM_IN", ev(cb))
check("H2 core: HD 지갑 칸 합 = 합성 체인 잔고(확정 거래 전부)", wsum(HD) == onchain(HD_ADDRS), (wsum(HD), onchain(HD_ADDRS)))

ad, st, col = new_col()
run(col)
calls0 = len(fc.calls)
col.cycle()
check("H11 tip 그대로 = 주기당 1콜(/blocks)", len(fc.calls) - calls0 == 1, fc.calls[calls0:])
cons = fc.spend([(both, 0), (a5, 1)], [(C(2), BTC // 10 + 39_990_000 - 800)], 800)
to_w2 = fc.spend([(both, 1)], [(W2ADDR, BTC // 20), (C(3), BTC // 10 - 1500 - BTC // 20 - 700)], 700)
fx = fc.fund(X2, BTC)
cj = fc.spend([(many[0], 0), (fx, 0)], [(X1, BTC // 2), (R(3), 10_000 - 300), (X2, BTC // 2 - 400)], 700)
fc.mine()
fc.mine_empty(2)
unfinal = receive(R(4), 7777)
fc.mine([unfinal])
mem = receive(R(6), 8888)
calls0 = len(fc.calls)
run(col)
got = recs()
check("H7 확정 깊이 미만·mempool = 안 보냄", unfinal not in got and mem not in got)
check("H7 상세 단계도 확정 깊이 확인(다른 제공자가 미확정 tx 를 알려 줘도 None = 다시 예약)",
      ad.fetch_and_normalize({"stable_id": unfinal, "owner": HD}, OWN) is None and ad.fetch_and_normalize({"stable_id": mem, "owner": HD}, OWN) is None)
check("H4·H5 새 확정 거래 3건 보냄", {cons, to_w2, cj} <= set(got))
stat_calls = sum(1 for _h, p in fc.calls[calls0:] if p.startswith("/address/") and "/txs" not in p)
check("H11 새 확정 블록 = 전 주소 통계 1번씩(HD 주소 + 단일 주소)", stat_calls >= len(ad.sb["wallets"][HD]["addrs"]), stat_calls)
drain()
check("H4 자기 통합(출력 전부 내 것) = 순변화 −수수료만 · NOOP", [(d["owner"], d["delta_base"]) for d in got[cons]["deltas"]] == [(HD, "-800")]
      and ev(cons) == "NOOP", (got[cons]["deltas"], ev(cons)))
check("H4 두 내 지갑 사이 = TRANSFER_SELF · 수수료 = 보낸 지갑", ev(to_w2) == "TRANSFER_SELF" and [f["payer"] for f in got[to_w2]["fees"]] == [HD]
      and sorted(got[to_w2]["owners"]) == sorted(OWN), (ev(to_w2), got[to_w2]["fees"]))
check("H5 CoinJoin 모양 = 수수료 줄 없음 · hint unknown · 사유 fee_attribution_unknown",
      not got[cj]["fees"] and got[cj]["classification"]["hint"] == "unknown" and "fee_attribution_unknown" in got[cj]["completeness"]["reasons"],
      got[cj]["classification"])
check("H4 단일 주소 지갑 칸 = 받은 0.05 BTC", wsum(W2) == BTC // 20, wsum(W2))
fc.mine_empty(2)
run(col)
check("H7 확정 깊이 도달 = 1번 보냄", sum(1 for x in inbox() if x["tx_uid"] == unfinal) == 1)

mw = fc.spend([(to_w2, 0), (many[1], 0)], [(X1, BTC // 20 + 10_001 - 1000)], 1000)
rbf1 = fc.spend([(many[2], 0)], [(X1, 10_002 - 500)], 500)
fc.mempool.remove(rbf1)
rbf2 = fc.spend([(many[2], 0)], [(X1, 10_002 - 900)], 900)
fc.mine()
fc.mine_empty(2)
run(col)
got = recs()
fs = {f["payer"]: int(f["amount_base"]) for f in got[mw]["fees"]}
check("H5 여러 내 지갑 입력 = 비례 분할(합 = 1000 · 큰 입력 W2 쪽이 큼) · 사유", sum(fs.values()) == 1000 and fs.get(W2, 0) > fs.get(HD, 0) > 0
      and "fee_split_proportional" in got[mw]["completeness"]["reasons"], fs)
check("H7 RBF = 이긴 tx 만(교체된 tx 없음)", rbf2 in got and rbf1 not in got)
drain()
check("H5 core: 비례 분할 수수료 = 지갑별 가스 레그 합 −1000", sum(int(r9[0]) for r9 in c.conn.execute(
    "SELECT qty_base FROM postings WHERE source_id=? AND leg_kind='gas'", (mw,))) == -1000)

sh = receive(R(7), 4444)
fc.mine([sh])
run(col)
fc.reorg(1, keep=[sh])
fc.mine_empty(2)
run(col)
got = recs()
check("H7 얕은 재편 = 새 블록 해시로 1번", sum(1 for x in inbox() if x["tx_uid"] == sh) == 1
      and got[sh]["finality"]["blockhash"] == fc._blk(fc.where[sh])[1])

ad_fresh = bw.BtcAdapter(cfg, transport=fc.transport).bind(cs.ChainState("btc", state_dir=__import__("tempfile").mkdtemp(dir=T.TMP)))
r_fresh = ad_fresh.fetch_and_normalize({"stable_id": a1, "owner": HD}, OWN)
check("H13 발견 상태가 아직 없는 새 인스턴스도 소유 지도 = 설정 지갑 전부(받는 0 수신 정확)", r_fresh and r_fresh["deltas"][0]["delta_base"] == str(BTC), r_fresh and r_fresh["deltas"])
r_none = T.safe(ad.fetch_and_normalize, {"stable_id": fx, "owner": HD}, OWN)
check("H13 내 스크립트가 안 보이는 tx = NOOP 로 굳히지 않고 일시 실패(다시 예약)", isinstance(r_none, dict) and "_exc" in r_none, r_none)

po = fc.spend([(many[3], 0)], [(X1, 10_003 - 600)], 600)
fc.hide_prevout.add(po)
fc.mine()
fc.mine_empty(2)
fc.fail_next(1, "http429", match="/tx/" + many[3])
r = run(col, 1)
check("H6 prevout 보강 실패 = 안 보냄(0 으로 안 셈) · 다시 예약", po not in recs() and po in st.d["pending"], (r, list(st.d["pending"])[:2]))
st.d["pending"][po]["next"] = 0
run(col)
got = recs()
check("H6 prevout 생략 → 참조 tx 로 보강 = 순변화·수수료 정확", got.get(po, {}).get("fees", [{}])[0].get("amount_base") == "600"
      and got[po]["deltas"][0]["delta_base"] == str(-10_003), got.get(po))

e1 = receive(R(8), 5555)
fc.mine()
fc.mine_empty(2)
n_before = len(recs())
st.d.pop("synced_at", None)
st.save()
for kind in ("http429", "timeout", "payload", "null", "short"):
    fc.fail_next(1, kind, match="/address/")
    r = col.cycle()
    check(f"H9 {kind} = 동기화 도장 없음 · 빈 결과로 안 바꿈", not st.d.get("synced_at") and e1 not in recs(), (kind, r))
run(col)
check("H9 다음 주기에 빠짐 없이 완주(오류 동안 진행 저장)", e1 in recs() and st.d.get("synced_at"), len(recs()) - n_before)
fc.down.add("blockstream.example")
e2 = receive(R(9), 6666)
fc.mine()
fc.mine_empty(2)
run(col, 6)
check("H9 제공자 장애 = 다음 인스턴스(mempool.example)로 이어 수집", e2 in recs() and ad.es.host == "mempool.example", ad.es.host)
fc.down.clear()

e3 = receive(R(10), 7070)
fc.mine()
fc.mine_empty(2)


class Crash(Exception):
    pass


st.mark_emitted = lambda *a, **k: (_ for _ in ()).throw(Crash())
try:
    col.cycle()
except Crash:
    pass
ad, st, col = new_col()
run(col)
check("H10 append 뒤 죽음 → 다시 보냄(인박스 2번)", sum(1 for x in inbox() if x["tx_uid"] == e3) == 2)
drain()
check("H10 원장은 1번(raw_txs 1행)", c.conn.execute("SELECT COUNT(*) FROM raw_txs WHERE chain='btc' AND txhash=?", (e3,)).fetchone()[0] == 1)
check("H10 원장 지갑 칸 합 = 합성 체인 확정 잔고(HD · 단일 주소)", wsum(HD) == onchain(HD_ADDRS) and wsum(W2) == onchain({W2ADDR}),
      (wsum(HD), onchain(HD_ADDRS), wsum(W2), onchain({W2ADDR})))

dr = receive(R(11), 9090)
fc.mine()
fc.mine_empty(3)
run(col)
check("H8 (전제) 확정 거래 보냄", dr in recs())
fc.reorg(5, keep=[])
fc.mine_empty(1, salt=2)
st.d.pop("synced_at", None)
st.save()
col.cycle()
hold = ad.sb.get("hold")
check("H8 깊은 재편 = 보류 · 동기화 도장 없음 · gap 사유(내구)", bool(hold) and not st.d.get("synced_at")
      and any(g["id"].startswith("reorg:") for g in cs.ChainState("btc").d["gaps"]), hold)
ad2 = bw.BtcAdapter(cfg, transport=fc.transport)
b8 = bw._settings(cfg)
r8 = T.safe(ad2.fetch_balances, OWN, None)
check("H8 보류 중 대사 = 보류(예외 · 0 잔고 아님)", isinstance(r8, dict) and "_exc" in r8, r8)
cfg_ack = set_cfg([dict(WALLETS[0], range_end=60), WALLETS[1]], reorg_ack=hold["from_height"])
ad, st, col = new_col(cfg_ack)
run(col)
check("H8 reorg_ack 로 보류 해제 · 다시 동기화 · 재편 gap 기록 정리(완료 판정)", not ad.sb.get("hold") and st.d.get("synced_at")
      and not any(str(g["id"]).startswith("reorg:") for g in st.d["gaps"]) and cs.ChainState("btc").status_view()[HD]["gaps"] == 0,
      st.d["gaps"][-2:])
cfg = cfg_ack

old = fc.fund(X0, BTC)
fc.mine(t=int(time.time()) - 400 * 86400)
fc.mine_empty(3)
cfg12 = json.load(open(CFG_PATH))
oldtx = receive(R(12), 1212)
fc.mine()
fc.mine_empty(2)
cfg_new = set_cfg([{"chain": "btc", "mode": "descriptor", "descriptor": D.split("#")[0].replace("/<0;1>/*", "/<0;1>/*"), "label": "hd"}])
k_hd = reg.owners(cfg_new, "btc")
check("H13 체크섬 없이 넣어도 같은 지갑 id", k_hd == {HD}, k_hd)
pre = fc.spend([(old, 0)], [(R(13), BTC - 500)], 500)
fc.mine([pre], t=int(time.time()) - 300 * 86400)
fc.mine_empty(3)
cfg = set_cfg([dict(WALLETS[0], range_end=60), WALLETS[1]], reorg_ack=hold["from_height"])
ad, st, col = new_col()
run(col)
check("H12 창 밖 시각 거래는 안 보냄", pre not in recs() and oldtx in recs())
cfg_w = json.load(open(CFG_PATH))
cfg_w["backfill_months"] = 12
json.dump(cfg_w, open(CFG_PATH, "w"))
cfg = config.load_config()
ad, st, col = new_col(cfg)
run(col, 12)
check("H12 창을 넓히면 옛 거래를 나중에 보냄", pre in recs())

blob = open(os.path.join(paths.STATE_DIR, "cursor_btc.json")).read() + json.dumps(inbox())
check("H13 상태·인박스에 xpub·디스크립터 원문 없음", ZPUB84[:20] not in blob and "xpub" not in blob and D.split("#")[1] not in blob)
cfg_d = set_cfg([dict(WALLETS[0], range_end=60), {"chain": "btc", "mode": "address", "address": R(0), "label": "dup"}],
                reorg_ack=hold["from_height"])
ad_d = bw.BtcAdapter(cfg_d, transport=fc.transport)
ad_d.bind(cs.ChainState("btc"))
own = ad_d.ownership(sorted(reg.owners(cfg_d, "btc")))
dupw = sorted(reg.owners(cfg_d, "btc") - {HD})[0]
check("H13 같은 스크립트 두 지갑 = HD 지갑 1번만(단일 주소 지갑 소유 0 · dup 경고)",
      own[ac.btc_address(R(0))["script"]][0] == HD and not ad_d.owned_addrs(dupw, own)
      and any(n.startswith("dup:") for n in ad_d.sb["wallets"][dupw]["notes"]), ad_d.sb["wallets"][dupw]["notes"])
tmpd = __import__("tempfile").mkdtemp(dir=T.TMP)
std = cs.ChainState("btc", state_dir=tmpd)
cfg_hd = set_cfg([dict(WALLETS[0], range_end=60)], reorg_ack=hold["from_height"])
wd = _ingest.Writer()
cold = bw.BtcCollector(bw.BtcAdapter(cfg_hd, transport=fc.transport).bind(std), wd, std, {HD})
for _i in range(8):
    cold.cycle()
cfg_d = set_cfg([dict(WALLETS[0], range_end=60), {"chain": "btc", "mode": "address", "address": R(0), "label": "dup"}],
                reorg_ack=hold["from_height"])
add = bw.BtcAdapter(cfg_d, transport=fc.transport).bind(std)
cold = bw.BtcCollector(add, wd, std, reg.owners(cfg_d, "btc"))
for _i in range(8):
    cold.cycle()
ud = [x["tx_uid"] for x in wd.recs]
check("H13 중복 스크립트 = 같은 거래를 두 지갑 관점으로 거듭 보내지 않음(HD 지갑 1번)", len(ud) == len(set(ud)) and all(x["owners"] == [HD] or HD in x["owners"]
      for x in wd.recs if x["tx_uid"] == a1), (len(ud), len(set(ud))))

import tempfile  # noqa: E402
tmp50 = tempfile.mkdtemp(dir=T.TMP)
fc.page = 50
st50 = cs.ChainState("btc", state_dir=tmp50)
ad50 = bw.BtcAdapter(cfg, transport=fc.transport).bind(st50)
w50 = _ingest.Writer()
col50 = bw.BtcCollector(ad50, w50, st50, OWN)
for _i in range(10):
    col50.cycle()
    if st50.d.get("synced_at") and not st50.d["pending"]:
        break
u50 = {x["tx_uid"] for x in w50.recs}
u25 = {x["tx_uid"] for x in inbox() if x["tx_uid"] in fc.where}
check("H3 쪽 크기 50 = 쪽 25 와 같은 거래 집합(빈 쪽 = 끝으로만 판정)", u50 == u25, (len(u50), len(u25), sorted(u25 - u50)[:2]))
fc.page = 25

cfg = set_cfg([dict(WALLETS[0], range_end=60), WALLETS[1], {"chain": "btc", "mode": "address", "address": X2, "label": "late"}],
              reorg_ack=hold["from_height"])
W3 = sorted(reg.owners(cfg, "btc") - OWN)[0]
c.chain_owners["btc"] = set(reg.owners(cfg, "btc"))
ad, st, col = new_col(cfg)
run(col)
again = [x for x in inbox() if x["tx_uid"] == cj]
check("H14 나중 등록 지갑(X2)이 옛 CoinJoin 모양 tx 를 다시 찾음 → 관점 넓혀 재방출(owners + W3)", len(again) == 2 and W3 in again[-1]["owners"],
      [x["owners"] for x in again])
drain()
r14 = c.conn.execute("SELECT SUM(CAST(qty_base AS INTEGER)) FROM postings WHERE source_id=? AND location=?", (cj, reg.make_location("btc", W3))).fetchone()[0]
check("H14 core 교체 재기장 = 새 지갑 몫(입력 −1 BTC + 출력 0.5 BTC − 400) 1번", int(r14 or 0) == -BTC + BTC // 2 - 400, r14)
check("H14 새 지갑 칸 합 = 합성 체인 잔고(수량 중복 없음)", wsum(W3) == onchain({X2}), (wsum(W3), onchain({X2})))
cfg = set_cfg([dict(WALLETS[0], range_end=60), WALLETS[1]], reorg_ack=hold["from_height"])
ad, st, col = new_col(cfg)
n_gone = ad.prune_wallets(reg.owners(cfg, "btc"))
check("H14 지갑 빼면 그 발견 상태 정리(원장·방출 기록은 그대로)", n_gone == 1 and W3 not in ad.sb["wallets"], n_gone)

st.save()
raw9 = json.load(open(os.path.join(paths.STATE_DIR, "cursor_btc.json")))
raw9["btc"]["v"] = 0
statefile.atomic_write_json(os.path.join(paths.STATE_DIR, "cursor_btc.json"), raw9)
n9 = len(inbox())
ad, st, col = new_col(cfg)
run(col, 12)
check("H10 상태 세대 바뀜 = 다시 훑기(새 상태) · 이미 보낸 거래 다시 안 보냄", st.d["btc"]["v"] == bw.STATE_VERSION
      and ad.sb["wallets"][HD]["hist_done"] and len(inbox()) == n9, (len(inbox()), n9))

seed = "abandon " * 11 + "about"
rows, errs = reg.wallets({"chain_wallets": [{"chain": "btc", "mode": "address", "address": seed},
                                             {"chain": "btc", "mode": "descriptor", "descriptor": seed}]}, with_errors=True)
check("H13 시드 문구 = 지갑 줄 거부(주소·디스크립터 둘 다)", not rows and len(errs) == 2, errs)
reg.FORCE_AVAILABLE.clear()
T.finish()
