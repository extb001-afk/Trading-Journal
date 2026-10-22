#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _bscchain as B  # noqa: E402

import os  # noqa: E402
from decimal import Decimal  # noqa: E402

import statefile, textutil  # noqa: E402
import bf_engine  # noqa: E402
import bsc_watch  # noqa: E402
import evm_watch  # noqa: E402
import flow_trace  # noqa: E402
import xchain_match  # noqa: E402

chk = T.chk
W = B.W1
TK = "0x" + "e7" * 20
OTHER = B.OTHER
H = "0x" + "11" * 32
AMT = 5 * 10 ** 18
D32 = "0x" + "%064x" % AMT
D64 = D32 + "%064x" % 1
D2032 = D32 + "ff" * 2000


def pad(a):
    return "0x" + a[2:].rjust(64, "0")


def evm_value(data):
    class X(evm_watch.RpcSynthMixin):
        chain = "base"
        wallets = [W]
        rpc_meta = {TK: 18}
        rpc_meta_path = os.path.join(T.TMP, "m.json")
        wrapped_ca = None
        cfg_rpcs = ["x"]

        def _rpc_call(self, m, p):
            if m == "eth_getTransactionByHash":
                return {"hash": H, "from": OTHER, "to": TK, "value": "0x0", "input": "0x", "blockNumber": "0x10", "transactionIndex": "0x0", "nonce": "0x1"}
            if m == "eth_getTransactionReceipt":
                return {"blockNumber": "0x10", "gasUsed": "0x5208", "effectiveGasPrice": "0x1", "status": "0x1", "blockHash": "0x" + "22" * 32,
                        "transactionIndex": "0x0",
                        "logs": [{"address": TK, "topics": [evm_watch.RpcSynthMixin.TRANSFER_TOPIC, pad(OTHER), pad(W)], "data": data, "logIndex": "0x0"}]}
            if m == "eth_getBlockByNumber":
                return {"timestamp": hex(1760000000)}
            raise RuntimeError(m)
    s = X()._rpc_synth_detail(H)
    return [t["total"]["value"] for t in s["token_transfers"]]


def bsc_value(data):
    bw = bsc_watch.BscWatcher.__new__(bsc_watch.BscWatcher)
    bw.wallets = [W]
    bw.token_meta = {TK: ["TK", 18]}
    bw.block_ts = {"0x10": 1760000000}
    bw.wrapped_ca = None
    bw.nodec = bf_engine.nodec_registry("bsc")
    tx = {"hash": H, "from": OTHER, "to": TK, "value": "0x0", "input": "0x", "blockNumber": "0x10", "transactionIndex": "0x0"}
    rc = {"blockNumber": "0x10", "gasUsed": "0x5208", "effectiveGasPrice": "0x1", "status": "0x1", "transactionIndex": "0x0",
          "logs": [{"address": TK, "topics": [bsc_watch.TRANSFER_TOPIC, pad(OTHER), pad(W)], "data": data, "logIndex": "0x0"}]}
    s = bw._build_snapshot(H, tx, rc)
    return [t["total"]["value"] for t in s["token_transfers"]]


for nm, d in (("32바이트", D32), ("64바이트", D64), ("2032바이트", D2032)):
    r = T.safe(evm_value, d)
    chk(r == [str(AMT)], f"L1 EVM 합성 상세 data {nm} → 수량 = 첫 워드(예외 없음)", r if isinstance(r, dict) else [str(x)[:40] for x in r])
    r = T.safe(bsc_value, d)
    chk(r == [str(AMT)], f"L2 BSC 스냅샷 data {nm} → 수량 = 첫 워드(예외 없음)", r if isinstance(r, dict) else [str(x)[:40] for x in r])

B.reset_state()
wr = B.Wr()
B.CH.head = B.H0
statefile.atomic_write_json(B.CPATH, {"from_block": B.H0 - 500, "_bf_start": B.H0 - 500, "_cov": B.H0 - 500, "_wallets": sorted([B.W1, B.W2])})
w = B.mk(B.cfg(lanes=False), wr)
good1 = B.CH.transfer(B.H0 - 400, B.USD, OTHER, W, 5 * 10 ** 18)
poison = B.CH.transfer(B.H0 - 300, TK, OTHER, W, 7)
good2 = B.CH.transfer(B.H0 - 200, B.USD, OTHER, W, 9 * 10 ** 18)
BIG = "0x" + "%064x" % 7 + "ee" * 2000
orig = B.CH.answer


def answer(url, m, p):
    r = orig(url, m, p)
    if m == "eth_getTransactionReceipt" and p and p[0] == poison and isinstance(r, dict):
        for lg in r["logs"]:
            lg["data"] = BIG
    return r


B.CH.answer = answer
try:
    for _ in range(3):
        B.cycle(w)
finally:
    B.CH.answer = orig
c = B.cur()
em = B.emitted(wr)
chk(int(c.get("from_block") or 0) > B.H0 - 200, "L3 BSC 커서 전진(스팸 로그 tx 를 지나감)", {"from_block": c.get("from_block"), "start": B.H0 - 500})
chk(not (c.get("_detail_fail") or {}) and not (c.get("_quarantine") or {}), "L3 상세 실패·격리 기록 0", {k: c.get(k) for k in ("_detail_fail", "_quarantine")})
chk(set(em) >= {good1, poison, good2}, "L3 정상 입금 둘 + 스팸 tx 모두 방출", len(em))
pv = [t["total"]["value"] for r9 in wr.recs if r9["txhash"] == poison for t in (r9["snapshot"].get("token_transfers") or [])]
chk(pv == ["7"], "L3 스팸 tx 수량 = 첫 워드(7)", [str(x)[:40] for x in pv])

r = T.safe(bf_engine.decimals_from_result, "0x" + "11" * 2000)
chk(isinstance(r, tuple) and r[0] is None and r[1], "L4 decimals 긴 반환(2000바이트) = 예외 없이 (None, 사유)", r)
chk(T.safe(bf_engine.decimals_from_result, "0x" + "00" * 31 + "12" + "00" * 32) == (18, None), "L4 decimals 64바이트(첫 워드 18) = 18")
chk(T.safe(bf_engine.decimals_from_result, "0x" + "%064x" % 6) == (6, None), "L4 decimals 표준 32바이트 그대로")
r = T.safe(bf_engine.decimals_from_result, "0x" + "%064x" % 300)
chk(isinstance(r, tuple) and r[0] is None, "L4 decimals 범위 밖(300) 그대로 거절", r)
r = T.safe(bf_engine.decimals_from_result, "0x")
chk(isinstance(r, tuple) and r[0] is None, "L4 decimals 빈 반환 그대로 (None, 사유)", r)

TR = xchain_match.TR
for nm, d in (("32바이트", D32), ("64바이트", D64), ("2032바이트", D2032)):
    lg = {"address": TK, "topics": [TR, pad(OTHER), pad(W)], "data": d, "blockNumber": "0x10", "transactionHash": H}
    r = T.safe(flow_trace.log_legs, W, [lg], lambda t: 18, lambda t: "TK", lambda b: 1760000000)
    q = [x.get("qty") for x in r] if isinstance(r, list) else r
    chk(isinstance(q, list) and len(q) == 1 and Decimal(q[0]) == Decimal(5), f"L5 flow_trace.log_legs data {nm} → 5 TK", q)
    cr = {"logs": [{"a": xchain_match.norm(TK), "t": [xchain_match.TR, pad(OTHER), pad(W)], "d": d}]}
    r = T.safe(xchain_match.evm_owner_deltas, cr, W)
    chk(r == {xchain_match.norm(TK): AMT}, f"L5 xchain_match.evm_owner_deltas data {nm} → 첫 워드", r if isinstance(r, dict) and "_exc" in r else {k: hex(v)[:30] for k, v in (r or {}).items()})

same = all(textutil.log_word0(x) == int(x, 16) for x in ("0x0", "0x5", D32, "0X1f", "05", "0x" + "f" * 64))
chk(same, "L6 log_word0 = int(x, 16)(32바이트 이하)")
errs = []
for x in ("0x", "", "0xzz"):
    try:
        textutil.log_word0(x)
        errs.append(x)
    except ValueError:
        pass
chk(not errs, "L6 빈 값·hex 아님 = ValueError(종전 호출자 처리 그대로)", errs)

T.finish()
