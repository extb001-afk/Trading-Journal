#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
from _ingest import check  # noqa: E402
import _btcfake as BF  # noqa: E402

import collections  # noqa: E402
import copy  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
import types  # noqa: E402

import config  # noqa: E402
import address_codec as ac  # noqa: E402
import bf_engine  # noqa: E402
import btc_descriptor as bd  # noqa: E402
import chain_registry as reg  # noqa: E402
import chain_state as cs  # noqa: E402
import btc_watch as bw  # noqa: E402

ZPUB84 = "zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1m4wAcvPhXNfE3EfH1r1ADqtfSdVCToUG868RvUUkgDKf31mGDtKsAYz2oz2AGutZYs"
D = bd.descriptor_from_xpub(ZPUB84)
P = bd.plan_from_descriptor(D)
W2ADDR = "bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr"
X0, X1 = "1LqBGSKuX5yYUonjxT5qGfpUsXKYYWeabA", "1J3J6EvPrv8q6AC3VCjWV45Uf3nssNMRtH"
BTC = 10 ** 8
HA, HB = "blockstream.example", "mempool.example"
CFG_PATH = os.path.join(T.TMP, "config.json")
HD = ac.btc_wallet_id(D)


def R(i):
    return P.derive(0, i)[1]


def C(i):
    return P.derive(1, i)[1]


def mkcfg(**kw):
    cfg = json.load(open(CFG_PATH))
    cfg["chain_wallets"] = [{"chain": "btc", "mode": "descriptor", "descriptor": D}, {"chain": "btc", "mode": "address", "address": W2ADDR}]
    cfg["nonevm"] = BF.cfg_nonevm(**kw)
    json.dump(cfg, open(CFG_PATH, "w"))
    return config.load_config()


cfg = mkcfg()
W2 = sorted(reg.owners(cfg, "btc") - {HD})[0]


class Net:

    def __init__(self, fc, fb=None):
        self.fc, self.fb = fc, fb
        self.rules = []
        self.log = []

    def __call__(self, url):
        host = url.split("/")[2]
        path = "/" + url.split("/", 3)[3][len("api"):].lstrip("/")
        self.log.append(host)
        for h, pred, act in self.rules:
            if host == h and pred(path) and act == "500":
                raise bf_engine.NetError(f"http5xx: {host} 500", "http5xx", code=500, host=host)
        src = self.fb if (host == HB and self.fb is not None) else self.fc
        d = src.transport(url)
        for h, pred, act in self.rules:
            if host == h and pred(path) and callable(act):
                d = act(json.loads(json.dumps(d)))
        return d

    def n(self, host=None):
        return sum(1 for h in self.log if host is None or h == host)

    def hops(self):
        return sum(1 for a, b in zip(self.log, self.log[1:]) if a != b)


def receive(fc, addr, value, fee=1000):
    f = fc.fund(X0, value + fee)
    return fc.spend([(f, 0)], [(addr, value)], fee)


def world(net, sd=None, wr=None):
    st = cs.ChainState("btc", state_dir=sd or tempfile.mkdtemp(dir=T.TMP))
    ad = bw.BtcAdapter(cfg, transport=net).bind(st)
    wr = wr or _ingest.Writer()
    return ad, st, wr, bw.BtcCollector(ad, wr, st, reg.owners(cfg, "btc"))


def run(col, n):
    for _i in range(n):
        for p in col.st.d["pending"].values():
            p["next"] = 0
        col.cycle()


def recs(wr):
    d = collections.defaultdict(list)
    for r in wr.recs:
        d[r["tx_uid"]].append(r)
    return d


def delta(r, wid):
    return sum(int(d["delta_base"]) for d in r["deltas"] if d["owner"] == wid)


def chain3():
    fc = BF.FakeChain()
    t_hd = receive(fc, R(0), BTC)
    t_w2 = receive(fc, W2ADDR, 20_000_000)
    fc.mine()
    t_sp = fc.spend([(t_hd, 0)], [(X1, 60_000_000), (C(0), 39_990_000)], 10_000)
    fc.mine()
    fc.mine_empty(3)
    return fc, (t_hd, t_w2, t_sp)


def is_stats(addr):
    return lambda p: p == "/address/" + addr


def is_hist(addr):
    return lambda p: p.startswith("/address/" + addr + "/txs/chain")


def recovered(name, rules, cycles=12):
    fc, (t_hd, t_w2, t_sp) = chain3()
    net = Net(fc)
    net.rules = rules(fc, t_hd, t_w2, t_sp)
    ad, st, wr, col = world(net)
    run(col, cycles)
    got = recs(wr)
    ok = (net.n(HB) > 0 and all(len(got.get(t, [])) == 1 for t in (t_hd, t_w2, t_sp))
          and delta(got[t_sp][0], HD) == -60_010_000 and delta(got[t_w2][0], W2) == 20_000_000 and delta(got[t_hd][0], HD) == BTC)
    check(f"{name} → {cycles}주기 안에 정상 제공자 B 를 실제로 부르고 3건 모두 1번씩 기장(잔돈 = 내 것 · 순변화 정확)", ok,
          {"fallback_calls": net.n(HB), "emitted": {k[:8]: len(v) for k, v in got.items()}, "host": ad.es.host,
           "pending": len(st.d["pending"]), "gaps": len(st.d["gaps"])})
    return ad, st, wr, net


recovered("F1 /blocks 정상 + 한 주소 통계 HTTP 500 영구", lambda fc, *t: [(HA, is_stats(W2ADDR), "500")])
recovered("F2 HTTP 200 + 잘못된 구조 통계 {'chain_stats': {}}", lambda fc, *t: [(HA, is_stats(W2ADDR), lambda d: {"chain_stats": {}})])

recovered("F3 거래 수와 모순된 빈 이력(통계 1건 · 이력 [])", lambda fc, *t: [(HA, is_hist(W2ADDR), lambda d: [])])


def _nospk(d):
    d["vout"][0].pop("scriptpubkey", None)
    return d


def _badst(d):
    d["status"]["confirmed"] = "yes"
    return d


recovered("F3 깨진 상세 tx(출력 scriptPubKey 빠짐)", lambda fc, t_hd, t_w2, t_sp: [(HA, lambda p: p == "/tx/" + t_w2, _nospk)])
_ad, _st, _wr, _net = recovered("F3 잘못된 status(confirmed 가 bool 아님)",
                                lambda fc, t_hd, t_w2, t_sp: [(HA, lambda p: p == "/tx/" + t_w2, _badst)])
check("F3 잘못된 status = 미확정으로 보고 시도 횟수만 태우지 않음(gap 0)", not _st.d["gaps"], _st.d["gaps"][:2])

fc, _t = chain3()
net = Net(fc)
net.rules = [(HA, is_stats(W2ADDR), "500")]
es = bw.Esplora(["https://" + HA + "/api", "https://" + HB + "/api"], transport=net)
T.safe(es.addr_stats, W2ADDR)
es.blocks()
es.addr_stats(R(0))
T.safe(es.addr_stats, W2ADDR)
check("F4 주소 실패 → /blocks·다른 주소 성공 → 같은 주소 실패 = 2번 연속(전환)", es.host == HB, es.host)
fc, _t = chain3()
net = Net(fc)
net.rules = [(HA, is_stats(W2ADDR), lambda d: {"chain_stats": {}})]
es = bw.Esplora(["https://" + HA + "/api", "https://" + HB + "/api"], transport=net)
T.safe(es.addr_stats, W2ADDR)
check("F4 HTTP 200 + 형식 오류 1번 = 실패 1회(성공으로 지우지 않음 · 중복 집계 없음 → 아직 전환 안 함)", es.host == HA, es.host)
T.safe(es.addr_stats, W2ADDR)
check("F4 형식 오류 2번 연속 = 전환", es.host == HB, es.host)

fc, (t_hd, t_w2, t_sp) = chain3()
net = Net(fc)
ad, st, wr, col = world(net)
run(col, 6)
check("F5 (전제) 정상 수집 3건", len(recs(wr)) == 3, sorted(recs(wr)))
t_new = receive(fc, R(1), 777_777)
fc.mine()
fc.mine_empty(3)
net.rules = [(h, lambda p: p == "/tx/" + t_new, "500") for h in (HA, HB)]
run(col, 1)
net.rules = []
check("F5 (전제) 새 거래 = 대기 후보(시도 1)", t_new in st.d["pending"] and st.d["pending"][t_new]["tries"] == 1, st.d["pending"].get(t_new))
fc.down.update({HA, HB})
per = []
for _k in range(24):
    n0 = net.n()
    run(col, 1)
    per.append(net.n() - n0)
hops = net.hops()
check("F5 두 제공자 장애 24주기 = 주기당 호출 ≤ 3(tip 실패면 그 주기 끝 · 후보마다 tip 다시 묻지 않음)", max(per) <= 3, per)
check("F5 두 제공자 장애 = 빠른 교대 없음(냉각 · 24주기에 전환 ≤ 1번)", hops <= 1, hops)
check("F5 장애 동안 대기 후보 시도 횟수를 태우지 않음(gap 으로 안 감 · 유실 0)",
      t_new in st.d["pending"] and int(st.d["pending"][t_new]["tries"]) <= 1 and not st.d["gaps"],
      (st.d["pending"].get(t_new), st.d["gaps"][:1]))
fc.down.discard(HA if ad.es.host == HB else HB)
real_time = bw.time.time
bw.time = types.SimpleNamespace(**{k: getattr(__import__("time"), k) for k in ("sleep", "monotonic")}, time=lambda: real_time() + 7200)
try:
    run(col, 6)
finally:
    bw.time = __import__("time")
check("F5 냉각이 끝나면 회복한 제공자로 옮겨 이어 수집(후보 1번 기장)", len(recs(wr).get(t_new, [])) == 1, (ad.es.host, st.d["pending"].get(t_new)))
fc.down.clear()

fc, (t_hd, t_w2, t_sp) = chain3()
net = Net(fc)
net.rules = [(HA, is_stats(W2ADDR), "500")]
sd = tempfile.mkdtemp(dir=T.TMP)
wr = _ingest.Writer()
ad, st, wr, col = world(net, sd, wr)
run(col, 1)
ad, st, wr, col = world(net, sd, wr)
run(col, 2)
sw_host = ad.es.host
ad, st, wr, col = world(net, sd, wr)
check("F6 전환 직후 재시작 = 전환한 제공자(B) 유지(상태에 호스트만 · 주소 없음)", sw_host == HB and ad.es.host == HB, (sw_host, ad.es.host))
run(col, 8)
got = recs(wr)
check("F6 재시작 넘어 3건 모두 정확히 1번(유실 0 · 중복 0) · 대기 0", all(len(got.get(t, [])) == 1 for t in (t_hd, t_w2, t_sp))
      and not st.d["pending"] and not st.d["gaps"], {k[:8]: len(v) for k, v in got.items()})
raw = open(st.path).read()
check("F6 상태 파일에 제공자 전환 기록 · 주소 원문은 전환 기록에 없음",
      '"provider"' in raw and W2ADDR not in json.dumps(json.loads(raw).get("btc", {}).get("provider")), raw[:200])

fc = BF.FakeChain()
t_hd = receive(fc, R(0), BTC)
fc.mine()
t_w2 = receive(fc, W2ADDR, 20_000_000)
fc.mine()
old = copy.deepcopy(fc)
fc.mine_empty(3)
net = Net(fc, fb=old)
net.rules = [(HA, is_stats(W2ADDR), "500")]
ad, st, wr, col = world(net)
run(col, 10)
check("F7 뒤처진 B 로 전환 = B tip 기준 확인 수 미달 거래(W2 수신)는 보류", ad.es.host == HB and t_w2 not in recs(wr), (ad.es.host, sorted(recs(wr))))
old.mine_empty(3)
run(col, 6)
got = recs(wr)
check("F7 B 가 따라잡으면 그 거래를 1번 기장(다른 거래도 1번)", len(got.get(t_w2, [])) == 1 and len(got.get(t_hd, [])) == 1,
      {k[:8]: len(v) for k, v in got.items()})

fc, (t_hd, t_w2, t_sp) = chain3()
net = Net(fc)
ad, st, wr, col = world(net)
run(col, 6)
n6 = net.n()
run(col, 3)
check("F8 tip 그대로 = 주기당 1콜", net.n() - n6 == 3, net.n() - n6)
fc.mine_empty(1)
n9 = net.n()
run(col, 1)
nb = net.n() - n9
check("F8 정상 환경 호출 수 불변(수정 전 실측: 처음 6주기 62콜 · 새 블록 1주기 48콜) · 전부 A", (n6, nb, net.n(HB)) == (62, 48, 0), (n6, nb, net.n(HB)))

def is_bnd(p):
    return p.startswith("/blocks/")


recovered("F9 /blocks 정상 + /blocks/F HTTP 500 영구", lambda fc, *t: [(HA, is_bnd, "500")])
recovered("F9 /blocks 정상 + /blocks/F 깨진 목록", lambda fc, *t: [(HA, is_bnd, lambda d: d[:1] + ["junk"])])
recovered("F9 /blocks 정상 + /blocks/F 첫 블록 높이 ≠ 요청(구조는 정상)",
          lambda fc, *t: [(HA, is_bnd, lambda d: [dict(b, height=b["height"] - 1) for b in d])])

fc, _t = chain3()
net = Net(fc)
net.rules = [(HA, is_bnd, lambda d: [dict(b, height=b["height"] - 1) for b in d])]
es = bw.Esplora(["https://" + HA + "/api", "https://" + HB + "/api"], transport=net)
F9 = fc.height - 2
n0 = net.n()
T.safe(es.blocks, F9)
check("F9 높이 불일치 = 그 논리 호출 안에서 실패 1회(HTTP 1콜 · 이중 집계 없음 · 아직 전환 안 함)",
      net.n() - n0 == 1 and es.host == HA and es.cyc_bad == 1, (net.n() - n0, es.host, es.cyc_bad, es.bad))
es.blocks()
T.safe(es.blocks, F9)
check("F9 경계 실패 → tip 성공 → 경계 실패 = 2번 연속(전환 · tip 성공이 경계 실패를 지우지 않음)", es.host == HB, es.host)
fc, _t = chain3()
net = Net(fc)
net.rules = [(HA, lambda p: p == "/blocks", "500")]
es = bw.Esplora(["https://" + HA + "/api", "https://" + HB + "/api"], transport=net)
T.safe(es.blocks)
es.blocks(fc.height - 2)
T.safe(es.blocks)
check("F9 tip 실패 → 경계 성공 → tip 실패 = 전환(역할 분리 · 반대 방향)", es.host == HB, es.host)
es = bw.Esplora(["https://" + HA + "/api", "https://" + HB + "/api"], transport=Net(fc))
for _k in range(40):
    T.safe(es.blocks, 1_000_000 + _k)
check("F9 실패 범위 키 = 역할(높이마다 갈라지지 않음 · 기록 유한)", len(es.bad) <= 3, sorted(es.bad))

T.finish()
