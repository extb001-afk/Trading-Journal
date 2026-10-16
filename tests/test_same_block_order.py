#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _ingest
from _ingest import check, W, Writer, Reader

import copy
import json
import os
import time

os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
_cfg = copy.deepcopy(_ingest.CFG)
W2 = "0x" + "a2" * 20
_cfg["wallets"] = [x for x in _cfg["wallets"] if x.get("chain") == "base"] + [{"type": "evm", "chain": "base", "address": W2}]
_cfg["chains"] = {"base": _cfg["chains"]["base"]}
json.dump(_cfg, open(os.environ["TJ_CONFIG"], "w"))

import common
import core
import evm_watch
import bsc_watch
import web
import db as dbm
import pricing
import acct_norm

assert T.TMP in common.STATE_DIR
core.dm = lambda *a, **k: None
T.patch_moved("dm", core.dm)
pricing._gj = lambda *a, **k: None
pricing.PxCache.candle_usd = lambda *a, **k: None
pricing.PxCache.fx_at = lambda *a, **k: 1400.0
acct_norm.FxBook.candle = lambda *a, **k: None
for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker"):
    if hasattr(web.StateBuilder, _m):
        setattr(web.StateBuilder, _m, lambda self: None)
web.Spot.dex_pending = lambda *a: False
web.Spot.ex_pending = lambda *a: False

NOW = int(time.time())
T0 = NOW - 2 * 86400
USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
TKA, TKB, POOL = "0x" + "b2" * 20, "0x" + "b3" * 20, "0x" + "c3" * 20
TOP = evm_watch.RpcSynthMixin.TRANSFER_TOPIC


def H(n):
    return "0x" + format(n, "064x")


def tpc(a):
    return "0x" + a[2:].zfill(64)


RAW = {}


def mklog(ca, fr, to, q, dec, li, txi, hh, blk):
    return {"address": ca, "topics": [TOP, tpc(fr), tpc(to)], "data": hex(q * 10 ** dec), "logIndex": li, "transactionIndex": txi,
            "transactionHash": hh, "blockNumber": hex(blk), "blockHash": H(blk + 1000000), "removed": False}


def fixture(hh, blk, ts, txidx, legs, nonce, fr=W, value=0):
    tx = {"hash": hh, "blockNumber": hex(blk), "blockHash": H(blk + 1000000), "transactionIndex": hex(txidx), "nonce": hex(nonce),
          "to": POOL if fr == W else W, "value": hex(value), "gasPrice": hex(10 ** 6), "gas": hex(200000),
          "input": "0x3593564c" if fr == W else "0x", "type": "0x2", "from": fr}
    rc = {"transactionHash": hh, "blockNumber": hex(blk), "blockHash": H(blk + 1000000), "transactionIndex": hex(txidx),
          "gasUsed": hex(100000), "effectiveGasPrice": hex(10 ** 6), "status": "0x1",
          "logs": [mklog(ca, f, t, q, d, hex(txidx * 10 + i), hex(txidx), hh, blk) for i, (ca, f, t, q, d) in enumerate(legs)]}
    RAW[hh] = (tx, rc, {"timestamp": hex(ts)})


def mk_rpc(raw, wrapped=None):
    w = evm_watch.RpcChainWatcher.__new__(evm_watch.RpcChainWatcher)
    w.chain, w.wallets, w.writer, w.emitted, w.cursor = "base", [W], Writer(), set(), {}
    w._rpc_token_dec = lambda ca: 6 if ca == USDC else 18
    if wrapped:
        w.wrapped_ca = wrapped

    def rpc(method, args):
        if method == "eth_getTransactionByHash":
            return copy.deepcopy(raw[args[0]][0])
        if method == "eth_getTransactionReceipt":
            return copy.deepcopy(raw[args[0]][1])
        if method == "eth_getBlockByNumber":
            return copy.deepcopy(next(v[2] for v in raw.values() if v[1]["blockNumber"] == args[0]))
        raise AssertionError((method, args))
    w._rpc_call = rpc
    return w


FUND, OLD1, OLD2 = H(3), H(2), H(4)
BUY1, SELL1 = H(0xFF), H(0x01)
SELL2, BUY2 = H(0xFE), H(0x10)
B1, B2 = 43302, 43400
T2 = T0 + 3600
fixture(FUND, 100, T0 - 86404, 0, [(USDC, POOL, W, 10000, 6)], 0, fr=POOL, value=10 ** 18)
fixture(OLD1, 102, T0 - 86400, 0, [(USDC, W, POOL, 100, 6), (TKA, POOL, W, 100, 18)], 0)
fixture(OLD2, 103, T0 - 86300, 0, [(USDC, W, POOL, 100, 6), (TKB, POOL, W, 100, 18)], 1)
fixture(BUY1, B1, T0, 0, [(USDC, W, POOL, 300, 6), (TKA, POOL, W, 100, 18)], 2)
fixture(SELL1, B1, T0, 1, [(TKA, W, POOL, 100, 18), (USDC, POOL, W, 400, 6)], 3)
fixture(SELL2, B2, T2, 0, [(TKB, W, POOL, 100, 18), (USDC, POOL, W, 400, 6)], 4)
fixture(BUY2, B2, T2, 1, [(USDC, W, POOL, 300, 6), (TKB, POOL, W, 100, 18)], 5)
ALL = [FUND, OLD1, OLD2, BUY1, SELL1, SELL2, BUY2]

wr = mk_rpc(RAW)
snaps = {h: wr._rpc_synth_detail(h) for h in ALL}
pos = {h: snaps[h]["tx"].get("position") for h in ALL}
lis = {h: [t.get("log_index") for t in snaps[h]["token_transfers"]] for h in ALL}
check("E1 RPC 합성 tx.position = 영수증 순번(정수 · 순번 0 포함)",
      pos[BUY1] == 0 and pos[SELL1] == 1 and pos[SELL2] == 0 and pos[BUY2] == 1 and type(pos[BUY1]) is int, pos)
check("E1 RPC 합성 토큰 전송 log_index = 그 로그 번호(정수)",
      lis[BUY1] == [0, 1] and lis[SELL1] == [10, 11] and lis[SELL2] == [0, 1] and lis[BUY2] == [10, 11], lis)
for s in sorted(snaps.values(), key=lambda s: (s["tx"]["block_number"], s["tx"]["hash"])):
    wr._emit(s["tx"]["hash"], s, B2 + 20)
c = core.Core(common.load_config())
c._drain_stream("evm", Reader(wr.writer.recs), 0, 0)
check("E1 격리(poison) 0", not os.path.exists(os.path.join(common.STATE_DIR, "poison.jsonl")))
for ca, sym in ((USDC, "USDC"), (TKA, "TKA"), (TKB, "TKB")):
    c.conn.execute("UPDATE assets SET symbol=? WHERE address=?", (sym, ca))
c.conn.commit()
for h in ALL:
    c._price_tx("base", h)
c.conn.commit()


def build():
    b = web.StateBuilder()
    b.skip_gen_check = True
    con = dbm.open_db(common.DB_PATH, readonly=True)
    try:
        rows = b._replay_order(con, b._load(con))
        order = {t9: list(dict.fromkeys(r["source_id"] for r in rows if r["event_ts"] == t9)) for t9 in (T0, T2)}
        f = b._build(con)["fields"]
    finally:
        con.close()
    ps = f.get("_positionsAll") or f.get("positions") or []

    def summ(sym):
        p9 = [p for p in ps if p.get("sym") == sym]
        return {"realized": round(sum(p["realized"] for p in p9), 6), "held": round(sum(p["held"] for p in p9), 6),
                "basis": round(sum(p["held"] * p["avg"] for p in p9), 6), "cycles": len(p9)}
    return {"order": order, "TKA": summ("TKA"), "TKB": summ("TKB")}


def ledger(cn):
    return ([tuple(r) for r in cn.execute("SELECT * FROM postings ORDER BY posting_id")],
            [tuple(r) for r in cn.execute("SELECT chain, txhash, snapshot, wallets FROM raw_txs ORDER BY chain, txhash")])


r1 = build()
check("E1 화면 재생 순서 = 매수 → 매도(tx 순번 · 해시 순 아님)", r1["order"][T0] == [BUY1, SELL1], r1["order"])
check("E1 실현 $200 · 남은 100개 · 남은 원가 $200 · 주기 1(종전 $300 · $300 · 주기 2)",
      r1["TKA"] == {"realized": 200, "held": 100, "basis": 200, "cycles": 1}, r1["TKA"])
check("E2 반대 방향 재생 순서 = 매도 → 매수", r1["order"][T2] == [SELL2, BUY2], r1["order"])
check("E2 실현 $300 · 남은 100개 · 남은 원가 $300 · 주기 2", r1["TKB"] == {"realized": 300, "held": 100, "basis": 300, "cycles": 2}, r1["TKB"])

led0 = ledger(c.conn)
wr2 = mk_rpc(RAW)
snaps2 = {h: wr2._rpc_synth_detail(h) for h in ALL}
check("E3 다시 수집 = 같은 스냅샷(순번·로그 번호 포함 — 결정적)", snaps2 == snaps)
for s in sorted(snaps2.values(), key=lambda s: (s["tx"]["block_number"], s["tx"]["hash"])):
    wr2._emit(s["tx"]["hash"], s, B2 + 40)
c._drain_stream("evm", Reader(wr2.writer.recs), 0, 0)
check("E3 같은 tx 재수신 = 원장(postings)·원본(raw_txs) 무변", ledger(c.conn) == led0)
c.conn.close()
c2 = core.Core(common.load_config())
c2._drain_stream("evm", Reader(wr2.writer.recs), 0, 0)
check("E3 core 재시작 뒤 재수신 = 원장·원본 무변", ledger(c2.conn) == led0)
r2 = build()
check("E3 재수신·재시작 뒤 화면 결과 같음", r2 == r1, (r1, r2))

LEG3 = H(0x33)
fixture(LEG3, 43600, T0 + 7200, 2, [(USDC, POOL, W, 50, 6)], 0, fr=POOL)
s3 = mk_rpc(RAW)._rpc_synth_detail(LEG3)
old3 = copy.deepcopy(s3)
old3["tx"].pop("position", None)
for t9 in old3["token_transfers"]:
    t9.pop("log_index", None)
rec = {"v": 1, "kind": "evm_tx", "chain": "base", "txhash": LEG3, "wallets": [W], "observed_head": 43700, "ts": 1}
c2._drain_stream("evm", Reader([dict(rec, snapshot=old3)]), 0, 0)
led3 = ledger(c2.conn)
c2._drain_stream("evm", Reader([dict(rec, snapshot=s3, ts=2)]), 0, 0)
st3 = json.loads(c2.conn.execute("SELECT snapshot FROM raw_txs WHERE chain='base' AND txhash=?", (LEG3,)).fetchone()[0])
check("E4 옛 저장본 + 순번 있는 새 수집본 = 원장·원본 무변(재기장·승격 없음 · 자동 수리 없음)", ledger(c2.conn) == led3)
check("E4 저장본은 옛 원본 그대로(순번 키 없음)", "position" not in st3["tx"] and all("log_index" not in t9 for t9 in st3["token_transfers"]),
      st3["tx"])
c2.conn.close()

UB = 50000


def one(txi_rc, txi_tx, li=("0x5",), blk_tx=None, extra_logs=None, wrapped=None):
    hh = H(0x7000)
    tx = {"hash": hh, "blockNumber": hex(blk_tx or UB), "blockHash": H((blk_tx or UB) + 1000000), "nonce": "0x9", "to": POOL,
          "value": "0x0", "gasPrice": "0x1", "gas": "0x1", "input": "0x", "type": "0x2", "from": W}
    if txi_tx is not None:
        tx["transactionIndex"] = txi_tx
    logs = [mklog(TKA, POOL, W, 1 + i, 18, x, None, hh, UB) for i, x in enumerate(li)] + list(extra_logs or [])
    for lg in logs:
        lg.pop("transactionIndex", None)
        if lg.get("logIndex") is None:
            lg.pop("logIndex", None)
    rc = {"transactionHash": hh, "blockNumber": hex(UB), "blockHash": H(UB + 1000000), "gasUsed": "0x1", "effectiveGasPrice": "0x1",
          "status": "0x1", "logs": logs}
    if txi_rc is not None:
        rc["transactionIndex"] = txi_rc
    s = mk_rpc({hh: (tx, rc, {"timestamp": hex(T0)})}, wrapped=wrapped)._rpc_synth_detail(hh)
    return s


def P(s):
    return s["tx"].get("position", "없음")


def L(s):
    return [t.get("log_index", "없음") for t in s["token_transfers"]]


s0 = one("0x0", "0x0", li=("0x0",))
check("U1 순번 0 = 유효(키 있음 · 정수 0 · 로그 번호 0 도)", "position" in s0["tx"] and s0["tx"]["position"] == 0
      and type(s0["tx"]["position"]) is int and L(s0) == [0], (P(s0), L(s0)))
check("U1 16진 '0x1f' → 31 · 10진 문자열 '12' → 12 · 정수 7 → 7",
      (P(one("0x1f", None)), P(one("12", None)), P(one(7, None))) == (31, 12, 7),
      (P(one("0x1f", None)), P(one("12", None)), P(one(7, None))))
check("U1 영수증에 순번 없음 → 같은 블록 거래 값", P(one(None, "0x3")) == 3, P(one(None, "0x3")))
check("U1 영수증·거래 둘 다 없음 → position 키 없음(기본 0 금지)", "position" not in one(None, None)["tx"])
bad = ["0xzz", "", "abc", "-1", "1.5", "0x", " ", "1_0", True, -2, 1.0, [], {}]
gotb = {repr(v): P(one(v, None)) for v in bad}
check("U1 잘못된 순번(16진 아님·음수·소수·빈 값·불리언·_ 구분자 등) → 키 없음", all(v == "없음" for v in gotb.values()), gotb)
check("U1 영수증·거래 순번이 다름 → 키 없음", P(one("0x2", "0x3")) == "없음", P(one("0x2", "0x3")))
check("U1 거래가 다른 블록(재조직 사이 조회) · 영수증 순번 없음 → 키 없음", P(one(None, "0x3", blk_tx=UB + 1)) == "없음",
      P(one(None, "0x3", blk_tx=UB + 1)))
sm = one("0x4", "0x4", li=("0x2a", None, "17", "0xzz"))
check("U1 복수 로그: 각 레그 = 자기 로그 번호(16진·10진) · 없음·잘못된 값 = 그 레그만 키 없음 · 레그 수·값 무변",
      L(sm) == [42, "없음", 17, "없음"] and [t["total"]["value"] for t in sm["token_transfers"]] == [str(k * 10 ** 18) for k in (1, 2, 3, 4)],
      (L(sm), [t["total"]["value"] for t in sm["token_transfers"]]))
nft = {"address": "0x" + "d4" * 20, "topics": [TOP, tpc(POOL), tpc(W), "0x" + "0" * 63 + "7"], "data": "0x", "logIndex": "0x9"}
mine_not = mklog(TKA, POOL, "0x" + "e6" * 20, 5, 18, "0x1", None, H(0x7000), UB)
sn = one("0x4", None, li=("0x3",), extra_logs=[mine_not, nft])
check("U1 ERC-721 레그도 로그 번호 · 내 지갑 무관 로그는 레그 아님(번호도 안 섞임)",
      L(sn) == [3, 9] and [t["token"]["type"] for t in sn["token_transfers"]] == ["ERC-20", "ERC-721"], (L(sn), sn["token_transfers"]))
WETH = "0x4200000000000000000000000000000000000006"
dep = {"address": WETH, "topics": [evm_watch.RpcSynthMixin.WETH_DEPOSIT, tpc(W)], "data": hex(10 ** 18), "logIndex": "0xb"}
sw = one("0x4", None, li=(), extra_logs=[dep], wrapped=WETH)
check("U1 랩드 네이티브 감싸기 레그(Deposit 로그)도 로그 번호",
      L(sw) == [11] and sw["token_transfers"][0]["token"]["address"] == WETH, sw["token_transfers"])

EH = H(0x8000)


def es_rows(txi="0", lis=("3", "4"), with_tx=True, tt_txi="0"):
    txr = {"hash": EH, "blockNumber": "500", "timeStamp": str(T0), "from": W, "to": POOL, "value": "0", "gasUsed": "1", "gasPrice": "1",
           "txreceipt_status": "1", "input": "0x3593564c", "blockHash": H(500)}
    if txi is not None:
        txr["transactionIndex"] = txi
    tts = []
    for i, li in enumerate(lis):
        r = {"hash": EH, "blockNumber": "500", "timeStamp": str(T0), "from": POOL, "to": W, "contractAddress": TKA, "value": str(i + 1),
             "tokenDecimal": "18", "tokenSymbol": "TKA", "tokenName": "TKA", "blockHash": H(500)}
        if tt_txi is not None:
            r["transactionIndex"] = tt_txi
        if li is not None:
            r["logIndex"] = li
        tts.append(r)
    ent = evm_watch.EtherscanWatcher.merge_wallet_rows({W: ([txr] if with_tx else [], tts, [])})[EH]
    return evm_watch.EtherscanWatcher._snapshot(None, ent)


e0 = es_rows()
check("U2 txlist transactionIndex '0' → position 0 · tokentx logIndex 10진 → log_index", P(e0) == 0 and L(e0) == [3, 4], (P(e0), L(e0)))
e1 = es_rows(txi="12", lis=(None, "7"), tt_txi="12")
check("U2 logIndex 없는 행 = 그 레그만 키 없음(tokentx 기본 응답) · 레그 수 무변", P(e1) == 12 and L(e1) == ["없음", 7], (P(e1), L(e1)))
e2 = es_rows(txi=None, with_tx=False, tt_txi="4")
check("U2 개시 안 한 tx(토큰 행만) → 토큰 행 transactionIndex", P(e2) == 4 and e2["tx"]["raw_input"] == "0x01", (P(e2), e2["tx"]))
e3 = es_rows(txi="x1", lis=("-3", ""), tt_txi=None)
check("U2 잘못된 순번·로그 번호 → 키 없음", P(e3) == "없음" and L(e3) == ["없음", "없음"], (P(e3), L(e3)))
e4 = es_rows(txi="5", tt_txi="6")
check("U2 txlist·tokentx 순번이 다름 → 키 없음", P(e4) == "없음", P(e4))
e5 = es_rows(txi=None, tt_txi=None, lis=(None, None))
check("U2 순번·로그 번호 없는 응답 = 종전 스냅샷과 같은 키(새 키 없음)",
      "position" not in e5["tx"] and all(set(t) == {"from", "to", "token", "total"} for t in e5["token_transfers"]), e5)
check("U2 로그 번호가 붙어도 이더스캔 목록 모양(core._es_shape · _es_list) 유지", core.Core._es_shape(e0) and core.Core._es_list(e0)
      and core.Core._es_list(e1))


def mk_bsc():
    b = bsc_watch.BscWatcher.__new__(bsc_watch.BscWatcher)
    b.wallets = [W]
    b.token_meta = {TKA: ("TKA", 18)}
    b.block_ts = {hex(700): T0}
    return b


def bsc_one(txi_rc, txi_tx, lis):
    hh = H(0x9000)
    tx = {"hash": hh, "blockNumber": hex(700), "blockHash": H(700 + 1000000), "from": W, "to": POOL, "value": "0x0", "gasPrice": "0x1",
          "input": "0x"}
    if txi_tx is not None:
        tx["transactionIndex"] = txi_tx
    logs = []
    for i, li in enumerate(lis):
        lg = mklog(TKA, POOL, W, i + 1, 18, li, None, hh, 700)
        lg.pop("transactionIndex", None)
        if li is None:
            lg.pop("logIndex")
        logs.append(lg)
    rc = {"transactionHash": hh, "blockNumber": hex(700), "blockHash": H(700 + 1000000), "gasUsed": "0x1", "status": "0x1", "logs": logs}
    if txi_rc is not None:
        rc["transactionIndex"] = txi_rc
    return mk_bsc()._build_snapshot(hh, tx, rc)


b0 = bsc_one("0x0", "0x0", ("0x0", "0x1"))
check("U3 BSC 순번 0 · 로그 번호(정수)", P(b0) == 0 and L(b0) == [0, 1], (P(b0), L(b0)))
b1 = bsc_one(None, None, ("0xq", None))
check("U3 BSC 순번 없음·잘못된 로그 번호 → 키 없음 · 레그 수 무변", P(b1) == "없음" and L(b1) == ["없음", "없음"], (P(b1), L(b1)))
b2 = bsc_one("0x2", "0x5", ("0x20",))
check("U3 BSC 영수증·거래 순번 다름 → 키 없음", P(b2) == "없음" and L(b2) == [32], (P(b2), L(b2)))
check("U3 BSC 스냅샷 = 이더스캔 목록 모양 판정 유지(새 관점 합집합 규칙)", core.Core._es_shape(b0) and core.Core._es_list(b0))

leg_new = e0["token_transfers"][0]
leg_old = {k: v for k, v in leg_new.items() if k != "log_index"}
check("D1 정규 키(core._leg_row_key) = 로그 번호 무관", core.Core._leg_row_key("token_transfers", leg_new)
      == core.Core._leg_row_key("token_transfers", leg_old))
old_es = copy.deepcopy(e0)
old_es["tx"].pop("position", None)
for t9 in old_es["token_transfers"]:
    t9.pop("log_index", None)
check("D1 합집합(옛 저장본 번호 없음 + 새 수집본 번호 있음) = 저장본 그대로(같은 이동 두 번 없음)",
      core.Core._merge_list_snaps(old_es, e0) == old_es and not core.Core._legs_grow(old_es, e0))
old_rpc = copy.deepcopy(sm)
old_rpc["tx"].pop("position", None)
for t9 in old_rpc["token_transfers"]:
    t9.pop("log_index", None)
check("D1 RPC 합성도 같음(복수 로그 · 같은 키 반복 횟수 보존)", core.Core._merge_list_snaps(old_rpc, sm) == old_rpc
      and not core.Core._legs_grow(old_rpc, sm) and core.Core._legs_cover(old_rpc, sm) and core.Core._legs_cover(sm, old_rpc))

c3 = core.Core(common.load_config())


def es_tok(h, legs, with_li):
    out = []
    for i, (fr, to, v) in enumerate(legs):
        r = {"from": fr, "to": to, "token": {"address": TKA, "symbol": "TKA", "decimals": 18, "type": "ERC-20"}, "total": {"value": str(v)}}
        if with_li:
            r["log_index"] = 20 + i
        out.append(r)
    return out


def es_snap(h, legs, with_li):
    tx = {"hash": h, "from": POOL, "to": TKA, "value": "0", "fee": {"value": "0"}, "status": "ok", "raw_input": "0x01", "timestamp": T0 + 9000,
          "block_number": 800, "block_hash": H(800)}
    if with_li:
        tx["position"] = 3
    return {"tx": tx, "token_transfers": es_tok(h, legs, with_li), "internal": []}


def tok_rows(cn, h):
    return sorted((r[0], int(r[1])) for r in cn.execute("SELECT location, qty_base FROM postings WHERE source_id=? AND leg_kind!='gas'", (h,)))


HU = H(0xA001)
c3._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": "base", "txhash": HU, "wallets": [W], "ts": 1,
                                 "snapshot": es_snap(HU, [(POOL, W, 5)], False)}]), 0, 0)
c3._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": "base", "txhash": HU, "wallets": [W], "ts": 2, "repair": "leg_union",
                                 "snapshot": es_snap(HU, [(POOL, W, 5), (POOL, W, 7)], True)}]), 0, 0)
gu = tok_rows(c3.conn, HU)
su = json.loads(c3.conn.execute("SELECT snapshot FROM raw_txs WHERE txhash=?", (HU,)).fetchone()[0])
check("D1 이더스캔 모양 leg_union(옛 번호 없음 + 새 번호 있음) = 새 레그만 한 번 더(같은 레그 두 번 없음 · 5 + 7 = 12)",
      sum(q for _l, q in gu) == 12 and sorted(int(t9["total"]["value"]) for t9 in su["token_transfers"]) == [5, 7], (gu, su["token_transfers"]))
HA = H(0xA002)
c3._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": "base", "txhash": HA, "wallets": [W], "ts": 1,
                                 "snapshot": es_snap(HA, [(POOL, W, 5)], False)}]), 0, 0)
c3._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": "base", "txhash": HA, "wallets": [W2], "ts": 2,
                                 "snapshot": es_snap(HA, [(POOL, W2, 9)], True)}]), 0, 0)
ga = tok_rows(c3.conn, HA)
sa = json.loads(c3.conn.execute("SELECT snapshot FROM raw_txs WHERE txhash=?", (HA,)).fetchone()[0])
check("D1 새 관점(지갑 추가) 이더스캔 모양 = 합집합(저장 레그 유지 · 승격 교체 아님)",
      sorted(q for _l, q in ga) == [5, 9] and len(sa["token_transfers"]) == 2, (ga, sa["token_transfers"]))
c3.conn.close()
T.finish()
