#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402
from _ingest import check, W, Writer, Reader  # noqa: E402
import _rpcfake as R  # noqa: E402

import contextlib  # noqa: E402
import copy  # noqa: E402
import glob  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

BLOCKS, NULL = {}, set()


def node_fn(m, p):
    if m != "eth_getBlockByNumber" or p[1] is not False:
        raise RuntimeError("시험: 다른 호출 " + str(m))
    b = int(p[0], 16)
    if b in NULL:
        return None
    hs, lst = BLOCKS[b]
    return {"number": hex(b), "hash": hs, "parentHash": "0x" + "00" * 32, "transactions": list(lst)}


node = R.Node(node_fn)
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
_cfg = copy.deepcopy(_ingest.CFG)
_cfg["wallets"] = [x for x in _cfg["wallets"] if x.get("chain") == "base"]
_cfg["chains"] = {"base": dict(_cfg["chains"]["base"], rpcs=[node.url])}
json.dump(_cfg, open(os.environ["TJ_CONFIG"], "w"))

import config, paths  # noqa: E402
import bf_engine  # noqa: E402
import core  # noqa: E402
import evm_watch  # noqa: E402
import web  # noqa: E402
import db as dbm  # noqa: E402
import ledger_lock  # noqa: E402

sys.path.insert(0, os.path.join(T.ROOT, "tools"))
import evm_txpos_fill as F  # noqa: E402

assert T.TMP in paths.STATE_DIR
R.loop_open(bf_engine, T)

NOW = int(time.time())
T0 = NOW - 2 * 86400
USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
TKA, TKB, POOL = "0x" + "b2" * 20, "0x" + "b3" * 20, "0x" + "c3" * 20
TOP = evm_watch.RpcSynthMixin.TRANSFER_TOPIC


def H(n):
    return "0x" + format(n, "064x")


def BH(blk):
    return H(blk + 1000000)


def tpc(a):
    return "0x" + a[2:].zfill(64)


RAW = {}


def fixture(hh, blk, ts, txidx, legs, nonce, fr=W, value=0):
    tx = {"hash": hh, "blockNumber": hex(blk), "blockHash": BH(blk), "transactionIndex": hex(txidx), "nonce": hex(nonce),
          "to": POOL if fr == W else W, "value": hex(value), "gasPrice": hex(10 ** 6), "gas": hex(200000),
          "input": "0x3593564c" if fr == W else "0x", "type": "0x2", "from": fr}
    logs9 = [{"address": ca, "topics": [TOP, tpc(f), tpc(t)], "data": hex(q * 10 ** d), "logIndex": hex(txidx * 10 + i), "transactionIndex": hex(txidx),
              "transactionHash": hh, "blockNumber": hex(blk), "blockHash": BH(blk), "removed": False} for i, (ca, f, t, q, d) in enumerate(legs)]
    rc = {"transactionHash": hh, "blockNumber": hex(blk), "blockHash": BH(blk), "transactionIndex": hex(txidx),
          "gasUsed": hex(100000), "effectiveGasPrice": hex(10 ** 6), "status": "0x1", "logs": logs9}
    RAW[hh] = (tx, rc, {"timestamp": hex(ts)})


def synth(h):
    w = evm_watch.RpcChainWatcher.__new__(evm_watch.RpcChainWatcher)
    w.chain, w.wallets, w.writer, w.emitted, w.cursor = "base", [W], Writer(), set(), {}
    w._rpc_token_dec = lambda ca: 6 if ca == USDC else 18

    def rpc(method, args):
        if method == "eth_getTransactionByHash":
            return copy.deepcopy(RAW[args[0]][0])
        if method == "eth_getTransactionReceipt":
            return copy.deepcopy(RAW[args[0]][1])
        if method == "eth_getBlockByNumber":
            return copy.deepcopy(next(v[2] for v in RAW.values() if v[1]["blockNumber"] == args[0]))
        raise AssertionError((method, args))
    w._rpc_call = rpc
    return w._rpc_synth_detail(h)


def old(s):
    s = copy.deepcopy(s)
    s["tx"].pop("position", None)
    for t9 in s["token_transfers"]:
        t9.pop("log_index", None)
    return s


FUND, OLD1, OLD2 = H(3), H(2), H(4)
BUY1, SELL1 = H(0xFF), H(0x01)
SELL2, BUY2 = H(0xFE), H(0x10)
R3A, R3B = H(0x31), H(0x32)
R4A, R4B = H(0x41), H(0x42)
R5A, R5B = H(0x51), H(0x52)
B1, B2, B3, B4, B5 = 43302, 43400, 43500, 43600, 43700
T2 = T0 + 3600
fixture(FUND, 100, T0 - 86404, 0, [(USDC, POOL, W, 10000, 6)], 0, fr=POOL, value=10 ** 18)
fixture(OLD1, 102, T0 - 86400, 0, [(USDC, W, POOL, 100, 6), (TKA, POOL, W, 100, 18)], 0)
fixture(OLD2, 103, T0 - 86300, 0, [(USDC, W, POOL, 100, 6), (TKB, POOL, W, 100, 18)], 1)
fixture(BUY1, B1, T0, 0, [(USDC, W, POOL, 300, 6), (TKA, POOL, W, 100, 18)], 2)
fixture(SELL1, B1, T0, 1, [(TKA, W, POOL, 100, 18), (USDC, POOL, W, 400, 6)], 3)
fixture(SELL2, B2, T2, 0, [(TKB, W, POOL, 100, 18), (USDC, POOL, W, 400, 6)], 4)
fixture(BUY2, B2, T2, 1, [(USDC, W, POOL, 300, 6), (TKB, POOL, W, 100, 18)], 5)
for hh, blk, i in ((R3A, B3, 0), (R3B, B3, 1), (R4A, B4, 1), (R4B, B4, 0), (R5A, B5, 0), (R5B, B5, 2)):
    fixture(hh, blk, T0 + 7200 + blk - B3, i, [(USDC, POOL, W, 5, 6)], 0, fr=POOL)
KEEP = {R4A, R5A}
SN = {h: (synth(h) if h in KEEP else old(synth(h))) for h in RAW}
BLOCKS.update({B1: (BH(B1), [BUY1, SELL1]), B2: (H(0xEE), [SELL2, BUY2]), B3: (BH(B3), [R3A, R3B]),
               B4: (BH(B4), [R4B, R4A]), B5: (BH(B5), [R5B, R5A, H(0x902)])})
NULL.add(B3)

c = core.Core(config.load_config())
recs = [{"v": 1, "kind": "evm_tx", "chain": "base", "txhash": h, "wallets": [W], "observed_head": B5 + 50, "ts": 1, "snapshot": SN[h]}
        for h in sorted(RAW, key=lambda x: (int(RAW[x][0]["blockNumber"], 16), x))]
c._drain_stream("evm", Reader(recs), 0, 0)
check("(전제) 격리(poison) 0", not os.path.exists(os.path.join(paths.STATE_DIR, "poison.jsonl")))
c.conn.close()


def build():
    b = web.StateBuilder()
    con = dbm.open_db(paths.DB_PATH, readonly=True)
    try:
        rows = b._replay_order(con, b._load(con))
        order = {t9: list(dict.fromkeys(r["source_id"] for r in rows if r["event_ts"] == t9)) for t9 in (T0, T2)}
        keys = {h: b._ord_key(con, {"source_ns": "base", "source_id": h, "leg_kind": "acq"}) for h in (BUY1, SELL1)}
    finally:
        con.close()
    return {"order": order, "keys": keys}


def ledger():
    cn = dbm.open_db(paths.DB_PATH, readonly=True)
    try:
        return ([tuple(r) for r in cn.execute("SELECT * FROM postings ORDER BY posting_id")],
                [tuple(r) for r in cn.execute("SELECT * FROM positions ORDER BY 1, 2")],
                {(r[0], r[1]): r[2] for r in cn.execute("SELECT chain, txhash, snapshot FROM raw_txs")},
                {r[0]: r[1] for r in cn.execute("SELECT k, v FROM meta")})
    finally:
        cn.close()


def run(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = F.main(list(argv))
    return rc, buf.getvalue()


def pos_of(snaps, h):
    return json.loads(snaps[("base", h)])["tx"].get("position")


def undo_files():
    return sorted(glob.glob(os.path.join(paths.STATE_DIR, F.UNDO_PREFIX + "*.json")))


r0 = build()
check("(전제) 옛 원본 = 해시 순 재생(매도 → 매수 · 보유 충분이라 재정렬 판정이 손대지 않음)", r0["order"][T0] == [SELL1, BUY1], r0)
check("(전제) 순서 키 = 블록까지만(순번·로그 번호 없음)", r0["keys"][BUY1] == ("c", "base", B1, None, None), r0["keys"])

L0 = ledger()
rc, out = run()
cn = dbm.open_db(paths.DB_PATH, readonly=True)
fd = F.scan(cn)
fa = F.scan(cn, every=True)
cn.close()
check("(a) 미리보기 = 외부 0콜 · 바깥 연결 시도 0", rc == 0 and node.calls == [] and not T.NET_TRIES, (rc, node.calls, T.NET_TRIES))
check("(a) 미리보기 = 원장·원본·meta 무변 · 받기 파일 없음", ledger() == L0 and not os.path.exists(os.path.join(paths.STATE_DIR, F.CACHE)))
check("(a) 기본 후보 = 같은 블록 매수·매도 블록만(B1·B2)", sorted(k for k, b in fd.items() if b["cand"]) == [("base", B1), ("base", B2)],
      {k: b["cand"] for k, b in fd.items()})
check("(a) --all 후보 = 같은 지갑이 낀 같은 블록 전부(B1~B5)", sorted(k[1] for k, b in fa.items() if b["cand"]) == [B1, B2, B3, B4, B5])
check("(a) 출력 = 체인별 블록·예상 호출·가장 이른 날", "후보 블록 2" in out and "예상 호출 2(블록당 1)" in out and F._day(T0) in out, out)

rc, out = run("--fetch", "--all", "--limit", "1")
cache = F.load_cache()
check("(b) --limit 1 = 1콜(B1 · eth_getBlockByNumber [번호, false])", rc == 0 and node.calls == [("eth_getBlockByNumber", [hex(B1), False])]
      and list(cache["ok"]) == [f"base:{B1}"], (node.calls, cache))
check("(b) 받기 파일 0600", stat.S_IMODE(os.stat(os.path.join(paths.STATE_DIR, F.CACHE)).st_mode) == 0o600)
rc, out = run("--fetch", "--all")
cache = F.load_cache()
blks = [int(p[0], 16) for m, p in node.calls]
check("(b) 이어 받기 = 남은 블록만 블록당 1콜(B1 다시 안 부름)", blks == [B1, B2, B3, B4, B5], blks)
check("(b) 받은 블록 = B1·B4 · 자리 = 목록 순서", sorted(cache["ok"]) == [f"base:{B1}", f"base:{B4}"]
      and cache["ok"][f"base:{B1}"]["pos"] == {BUY1: 0, SELL1: 1} and cache["ok"][f"base:{B4}"]["pos"] == {R4A: 1, R4B: 0}, cache["ok"])
fw = {k: v["why"] for k, v in cache["fail"].items()}
check("(b) 블록 해시 불일치 · 빈 응답(null) · 이미 있는 순번과 다름 = 그 블록 실패(사유)",
      "해시" in fw.get(f"base:{B2}", "") and "조회 실패" in fw.get(f"base:{B3}", "") and "순번" in fw.get(f"base:{B5}", ""), fw)
rc, out = run("--fetch", "--all")
check("(b) 다시 받기 = 실패 블록만 다시(받은 블록 0콜)", [int(p[0], 16) for m, p in node.calls[5:]] == [B2, B3, B5], node.calls[5:])
n9 = len(node.calls)
sl = []
st9 = F.fetch([(k, b) for k, b in sorted(fa.items()) if k[1] in (B1, B4)], {"v": 1, "ok": {}, "fail": {}}, config.load_config(), 50,
              clock=lambda: 0.0, sleep=sl.append)
check("(b) --rps 상한 2(초당 50 요청 → 0.5초 간격)", st9["calls"] == 2 and sl == [0.5] and len(node.calls) == n9 + 2, (st9, sl))
bad = R.Node(lambda m, p: R.DOWN)
cfg2 = dict(config.load_config(), chains={"base": dict(_cfg["chains"]["base"], rpcs=[bad.url, node.url, node.url])})
two = [(k, b9) for k, b9 in sorted(fa.items()) if k[1] == B1]
n9, sl = len(node.calls), []
st9 = F.fetch(two, {"v": 1, "ok": {}, "fail": {}}, cfg2, 2, clock=lambda: 0.0, sleep=sl.append)
check("(b) 앞 노드 전송 실패 = 다음 노드(블록당 최대 2) · 콜마다 셈·간격", st9["calls"] == 2 and st9["ok"] == 1 and len(bad.calls) >= 1
      and len(node.calls) == n9 + 1 and sl == [0.5], (st9, len(bad.calls), sl))
c9 = {"v": 1, "ok": {}, "fail": {}}
st9 = F.fetch(two, c9, cfg2, 2, limit=1, clock=lambda: 0.0, sleep=sl.append)
check("(b) --limit = 콜 수 상한(앞 노드 실패 뒤 다음 노드로 넘어가도 1콜에서 멈춤 · 그 블록 실패 기록)", st9["calls"] == 1 and len(node.calls) == n9 + 1
      and f"base:{B1}" in c9["fail"], (st9, c9))
bad.close()
fake = {}
for i in range(7):
    BLOCKS[90000 + i] = (H(0xEF), [H(0x6000 + i)])
    fake[("base", 90000 + i)] = {"txs": {H(0x6000 + i): {"id": H(0x6000 + i), "pos": None, "bh": BH(90000 + i), "ts": T0, "fill": True}}, "cand": True}
n9 = len(node.calls)
st9 = F.fetch(sorted(fake.items()), {"v": 1, "ok": {}, "fail": {}}, config.load_config(), 2, clock=lambda: 0.0, sleep=lambda x: None)
check("(b) 응답 검사 실패(해시 다름)도 연속 실패 — 5블록이면 멈춤(후보 전부를 부르지 않음)", st9["calls"] == 5 and len(node.calls) == n9 + 5
      and st9["stopped"].startswith("연속 실패"), st9)
c9 = {"v": 1, "ok": {f"base:{B4}": {"h": BH(B4), "pos": {R4A: 1}, "at": 1}}, "fail": {}}
st9 = F.fetch([(("base", B4), fa[("base", B4)])], c9, config.load_config(), 2, clock=lambda: 0.0, sleep=lambda x: None)
check("(b) 받은 블록에 새 거래가 생기면 다시 받음(이번 거래 전부로 검사)", st9["calls"] == 1 and c9["ok"][f"base:{B4}"]["pos"] == {R4A: 1, R4B: 0}, (st9, c9))
check("(b) 받기 = 원장 무변", ledger() == L0)

ready = os.path.join(T.TMP, "lock_ready")
hold = subprocess.Popen([sys.executable, "-c", "import sys, time; sys.path.insert(0, sys.argv[1]); import ledger_lock; "
                         "fd = ledger_lock.acquire(sys.argv[2], who='시험'); open(sys.argv[3], 'w').write('1'); time.sleep(120)",
                         T.SRC, paths.DB_PATH, ready], env=os.environ.copy())
try:
    for _ in range(400):
        if os.path.exists(ready):
            break
        time.sleep(0.05)
    busy = []
    for argv in (("--apply",),):
        try:
            run(*argv)
        except ledger_lock.LedgerBusy as e:
            busy.append(str(e))
    rc_pv, _o = run()
    check("(f) 다른 작성자가 잠금 = --apply 거부(LedgerBusy) · 원장 무변 · 미리보기는 통과", len(busy) == 1 and ledger() == L0 and rc_pv == 0, busy)
finally:
    hold.kill()
    hold.wait()

cn = dbm.open_db(paths.DB_PATH)
cn.execute("UPDATE raw_txs SET blockhash=? WHERE chain='base' AND txhash=?", (H(0xAB), R4A))
cn.commit()
cn.close()
c9 = {"v": 1, "ok": {f"base:{B4}": F.load_cache()["ok"][f"base:{B4}"]}, "fail": {}}
with ledger_lock.hold(paths.DB_PATH, who="시험"):
    res9 = F.apply(c9)
cn = dbm.open_db(paths.DB_PATH, readonly=True)
fr9 = F.scan(cn, every=True)
cn.close()
check("(g) 받은 뒤 같은 블록 거래 해시가 바뀜 = 그 블록 전체 건너뜀(R4B 에 옛 목록 자리 안 적음) · 다시 받기 대상",
      res9["n"] == 0 and res9["undo"] is None and ledger()[2] == L0[2] and not F._have(c9, f"base:{B4}", fr9[("base", B4)]), res9)
cn = dbm.open_db(paths.DB_PATH)
cn.execute("UPDATE raw_txs SET blockhash=? WHERE chain='base' AND txhash=?", (BH(B4), R4A))
cn.commit()
cn.close()
cn = dbm.open_db(paths.DB_PATH)
cn.execute("UPDATE raw_txs SET blockhash=NULL WHERE chain='base' AND txhash=?", (R4A,))
cn.commit()
cn.close()
cn = dbm.open_db(paths.DB_PATH, readonly=True)
fr9 = F.scan(cn, every=True)
cn.close()
n9 = len(node.calls)
st9 = F.fetch([(("base", B4), fr9[("base", B4)])], {"v": 1, "ok": {}, "fail": {}}, config.load_config(), 2, clock=lambda: 0.0, sleep=lambda x: None)
with ledger_lock.hold(paths.DB_PATH, who="시험"):
    res9 = F.apply(c9)
rc, out9 = run("--all")
check("(g) 저장 블록 해시 없는 거래가 낀 블록 = 적용 범위 밖(부르지 않음 · 적용 0 · 미리보기 '해시 없음 건너뜀')",
      st9["calls"] == 0 and st9["nohash"] == 1 and len(node.calls) == n9 and res9["n"] == 0 and res9["skip"].get("해시 없음 건너뜀") == 2
      and "해시 없음 건너뜀 1" in out9 and ledger()[2] == L0[2], (st9, res9, out9))
cn = dbm.open_db(paths.DB_PATH)
cn.execute("UPDATE raw_txs SET blockhash=? WHERE chain='base' AND txhash=?", (BH(B4), R4A))
cn.execute("INSERT INTO raw_txs (chain, txhash, block, blockhash, ts, snapshot, wallets, ingested_at) VALUES ('base', ?, ?, ?, NULL, '{}', '[]', 1)",
           (H(0x4C), B4, H(0xAC)))
cn.commit()
cn.close()
with ledger_lock.hold(paths.DB_PATH, who="시험"):
    res9 = F.apply(c9)
check("(g) 받은 뒤 같은 높이에 다른 해시 거래가 생김(받아 둔 목록 밖) = 그 블록 전체 건너뜀", res9["n"] == 0 and res9["skip"].get("블록 대조 다름(다시 --fetch)") == 2
      and ledger()[2] == {**L0[2], ("base", H(0x4C)): "{}"}, res9)
cn = dbm.open_db(paths.DB_PATH)
cn.execute("DELETE FROM raw_txs WHERE chain='base' AND txhash=?", (H(0x4C),))
cn.commit()
cn.close()
check("(g) (복원) 원장·원본 = 처음 그대로", ledger()[:3] == L0[:3])

inval0 = L0[3].get(dbm.DAILY_INVAL_K)
rc, out = run("--apply")
L1 = ledger()
uf = undo_files()
check("(c) 적용 = 3건(BUY1·SELL1·R4B) · 되돌리기 파일 1개(0600)", rc == 0 and "채움 3건" in out and len(uf) == 1
      and stat.S_IMODE(os.stat(uf[0]).st_mode) == 0o600, (out, uf))
check("(c) 원본 tx.position = 목록 자리", (pos_of(L1[2], BUY1), pos_of(L1[2], SELL1), pos_of(L1[2], R4B)) == (0, 1, 0))
check("(c) 원장 행(postings·positions) 무변", L1[0] == L0[0] and L1[1] == L0[1])
check("(c) meta 영수증 txpos_fill:<체인>:<해시> 3 · 일별 마감 무효화 표식 올라감",
      sorted(k for k in L1[3] if k.startswith(F.RECEIPT)) == sorted(F.RECEIPT + "base:" + h for h in (BUY1, SELL1, R4B))
      and L1[3].get(dbm.DAILY_INVAL_K) not in (None, inval0), {k: v for k, v in L1[3].items() if k.startswith(F.RECEIPT) or k == dbm.DAILY_INVAL_K})
hd = json.load(open(os.path.join(paths.STATE_DIR, "hist_dirty.json")))
check("(c) 장기 곡선 다시 계산 표식 = 가장 이른 채운 거래 날", hd.get("from") == F._day(T0), hd)
r1 = build()
check("(c) 순서 키 = 순번(재생이 읽음)", r1["keys"][BUY1] == ("c", "base", B1, 0, None) and r1["keys"][SELL1] == ("c", "base", B1, 1, None), r1["keys"])
check("(c) ★화면 재생 = 실제 실행 순서(매수 → 매도)★", r1["order"][T0] == [BUY1, SELL1], r1)
check("(c) 못 받은 블록(B2 해시 불일치) = 무변(해시 순 그대로)", r1["order"][T2] == r0["order"][T2] == [BUY2, SELL2], (r0, r1))
check("(g) 이미 있는 순번 무변(R4A 원본 바이트 그대로) · 받기 실패 블록 B3·B5 원본 무변",
      all(L1[2][("base", h)] == L0[2][("base", h)] for h in (R4A, R3A, R3B, R5A, R5B, SELL2, BUY2)))

rc, out = run("--apply")
check("(d) 두 번째 적용 = 할 일 없음 · 원장·원본·meta 무변 · 되돌리기 파일 안 늘어남", rc == 0 and "할 일 없음" in out and ledger() == L1 and undo_files() == uf, out)

cn = dbm.open_db(paths.DB_PATH)
tamper = json.loads(L1[2][("base", R4B)])
tamper["_later"] = 1
cn.execute("UPDATE raw_txs SET snapshot=? WHERE chain='base' AND txhash=?", (json.dumps(tamper, ensure_ascii=False), R4B))
cn.commit()
cn.close()
L1b = ledger()
rc, out = run("--undo", uf[0])
check("(e) 되돌리기 미리보기 = 쓰기 0 · 2건 가능 · 1건 거부", rc == 0 and ledger() == L1b and "2건" in out and "sha256" in out, out)
busy = []
hold = subprocess.Popen([sys.executable, "-c", "import sys, time; sys.path.insert(0, sys.argv[1]); import ledger_lock; "
                         "fd = ledger_lock.acquire(sys.argv[2], who='시험'); open(sys.argv[3], 'w').write('1'); time.sleep(120)",
                         T.SRC, paths.DB_PATH, ready + "2"], env=os.environ.copy())
try:
    for _ in range(400):
        if os.path.exists(ready + "2"):
            break
        time.sleep(0.05)
    try:
        run("--undo", uf[0], "--apply")
    except ledger_lock.LedgerBusy as e:
        busy.append(str(e))
    check("(f) 잠금 중 --undo --apply = LedgerBusy · 원장 무변", len(busy) == 1 and ledger() == L1b, busy)
finally:
    hold.kill()
    hold.wait()
rc, out = run("--undo", uf[0], "--apply")
L2 = ledger()
check("(e) 되돌림 2건 · BUY1·SELL1 원본 = 적용 전 바이트 그대로 · 영수증 지움",
      rc == 0 and "되돌림 2건" in out and all(L2[2][("base", h)] == L0[2][("base", h)] for h in (BUY1, SELL1))
      and not any(k in L2[3] for k in (F.RECEIPT + "base:" + BUY1, F.RECEIPT + "base:" + SELL1)), out)
check("(e) 그 뒤 바뀐 원본(sha256 다름) = 그 건 거부 · 원본·영수증 그대로", L2[2][("base", R4B)] == L1b[2][("base", R4B)]
      and F.RECEIPT + "base:" + R4B in L2[3])
check("(e) 되돌린 뒤 원장 행 무변 · 재생 = 옛 순서", L2[0] == L0[0] and build() == r0)
rc, out = run("--undo", uf[0], "--apply")
check("(e) 두 번째 되돌리기 = 전부 거부 · 원장 무변", rc == 0 and "되돌림 0건" in out and ledger() == L2, out)

ph = {"raw_input": "0x01", "fee": {"value": "0"}, "hash": BUY1, "block_number": B1}
real = {"raw_input": "0x3593564c", "hash": BUY1, "block_number": B1, "from": W, "fee": {"value": "100"}}
m1 = core.Core._merge_list_snaps({"tx": dict(ph, position=4), "token_transfers": []}, {"tx": dict(real), "token_transfers": []})
m2 = core.Core._merge_list_snaps({"tx": dict(ph, position=4), "token_transfers": []}, {"tx": dict(real, position=2), "token_transfers": []})
m3 = core.Core._merge_list_snaps({"tx": dict(ph), "token_transfers": []}, {"tx": dict(real), "token_transfers": []})
check("(h) 자리표시 → 실제 tx 교체 · 새 쪽에 순번 없음 = 저장본 순번 유지(나머지 = 새 tx)", m1["tx"] == dict(real, position=4), m1["tx"])
check("(h) 새 쪽에 순번 있음 = 새 값 · 둘 다 없음 = 키 없음(기본 0 금지)", m2["tx"] == dict(real, position=2) and m3["tx"] == real, (m2["tx"], m3["tx"]))
m4 = core.Core._merge_list_snaps({"tx": dict(ph, position=4, block_number=B1 + 1), "token_transfers": []}, {"tx": dict(real), "token_transfers": []})
m5 = core.Core._merge_list_snaps({"tx": dict(ph, position=4, block_hash=H(0xA1)), "token_transfers": []},
                                 {"tx": dict(real, block_hash=H(0xA2)), "token_transfers": []})
m6 = core.Core._merge_list_snaps({"tx": dict(ph, position=4, block_hash=H(0xA1).upper().replace("0X", "0x")), "token_transfers": []},
                                 {"tx": dict(real, block_hash=H(0xA1)), "token_transfers": []})
check("(h) 다른 블록(번호 다름 · 알려진 해시 다름 = 재조직) = 저장본 순번 안 옮김 · 같은 해시(대소문자 무관) = 유지",
      "position" not in m4["tx"] and "position" not in m5["tx"] and m6["tx"].get("position") == 4, (m4["tx"], m5["tx"], m6["tx"]))
node.close()
check("바깥 연결 시도 0", not T.NET_TRIES, T.NET_TRIES)
T.finish()
