#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _costsim as S  # noqa: E402
from _ingest import W, Reader  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402

import paths  # noqa: E402
import xchain_match  # noqa: E402

E18, E6, DAY = 10 ** 18, 10 ** 6, 86400
NOW = S.NOW
D0 = NOW - 40 * DAY
X, ROUTER, AUC, TKN = "0x" + "b7" * 20, "0x" + "c7" * 20, "0x" + "a7" * 20, "0x" + "d7" * 20
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
BUSD = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
BR = "0x3154cf16ccdb4c6d922629664174b904d80f2c35"
CFG = {"chains": {"eth": {"blockscout": "https://bs.invalid", "etherscan_chainid": 1, "conf_depth": 12, "blocks_per_day": 7200, "rpcs": ["https://rpc.invalid"]},
                  "base": {"blockscout": "https://base.invalid", "rpcs": ["https://baserpc.invalid"], "conf_depth": 12, "blocks_per_day": 43200}},
       "wallets": [{"type": "evm", "chain": "eth", "address": W, "label": "w"}, {"type": "evm", "chain": "base", "address": W, "label": "b"}],
       "native_symbol": {"eth": "ETH", "base": "ETH"}}
shutil.copy(os.path.join(T.ROOT, "seed", "bridge_contracts.json"), os.path.join(T.TMP, "seed", "bridge_contracts.json"))
chk = T.chk


def h(n):
    return "0x" + ("%064x" % n)


def snap(hx, ts, blk, frm, to, value=0, toks=(), internal=(), data="0x12345678"):
    return {"tx": {"hash": hx, "from": frm, "to": to, "value": str(value), "fee": {"value": "0"}, "status": "ok", "raw_input": data,
                   "timestamp": ts, "block_number": blk, "block_hash": "0x" + "d" * 64},
            "token_transfers": [{"from": f, "to": t, "token": {"address": ca, "symbol": sym, "decimals": dec, "type": "ERC-20"},
                                 "total": {"value": str(v), "decimals": str(dec)}} for f, t, ca, sym, dec, v in toks],
            "internal": [{"from": f, "to": t, "value": str(v), "success": True} for f, t, v in internal]}


def go(mode):
    c = S.reset(cfg_extra=CFG, px={"ETH": 10000., "USDT": 1., "USDC": 1.})
    S.FXF[0] = lambda ts: 1300. if ts < D0 + DAY else 1500.
    feed = []

    def add(ch, n, ts, frm, to, toks=(), internal=(), data="0x12345678"):
        hx = h(n)
        c._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": ch, "txhash": hx, "wallets": [W],
                                        "snapshot": snap(hx, ts, 1000 + n, frm, to, toks=toks, internal=internal, data=data), "ts": 1}]), 0, 0)
        feed.append((ch, hx))
        return hx
    add("eth", 1, D0 - DAY, X, W, [(X, W, USDT, "USDT", 6, 10100 * E6)], data="0xa9059cbb")
    buy = add("eth", 2, D0, W, ROUTER, [(W, ROUTER, USDT, "USDT", 6, 10100 * E6), (ROUTER, W, USDC, "USDC", 6, 10000 * E6)])
    if mode in ("bridge", "nolink"):
        send = add("eth", 3, D0 + DAY, W, BR, [(W, BR, USDC, "USDC", 6, 10000 * E6)])
        arrive = add("base", 4, D0 + DAY + 60, X, W, [(BR, W, BUSD, "USDC", 6, 10000 * E6)])
        add("base", 5, D0 + 10 * DAY, W, ROUTER, [(W, ROUTER, BUSD, "USDC", 6, 10000 * E6)], [(ROUTER, W, E18)])
        if mode == "bridge":
            json.dump({"v": xchain_match.CACHE_V, "arr": {xchain_match.arr_key("base", arrive, W, BUSD): {"status": "link", "src_chain": "eth",
                                                                                                         "src_tx": send, "proto": "across"}}},
                      open(os.path.join(paths.STATE_DIR, xchain_match.CACHE_NAME), "w"))
    elif mode == "cca":
        send = add("eth", 3, D0 + DAY, W, AUC, [(W, AUC, USDC, "USDC", 6, 10000 * E6)])
        arrive = add("eth", 4, D0 + 2 * DAY, W, AUC, [(AUC, W, USDC, "USDC", 6, 9000 * E6)])
        claim = add("eth", 5, D0 + 3 * DAY, W, AUC, [(AUC, W, TKN, "TKN", 18, 1000 * E18)])
        add("eth", 6, D0 + 10 * DAY, W, ROUTER, [(W, ROUTER, USDC, "USDC", 6, 9000 * E6)], [(ROUTER, W, 9 * E18 // 10)])
        add("eth", 7, D0 + 11 * DAY, W, ROUTER, [(W, ROUTER, TKN, "TKN", 18, 1000 * E18)], [(ROUTER, W, E18 // 10)])
        json.dump({"owners": {f"eth:{W}": {"t": NOW, "chain": "eth", "owner": W, "bids": [
            {"auction": AUC, "id": 1, "amount": str(10000 * E6), "bid_tx": send, "bid_ts": D0 + DAY, "filled": str(1000 * E18), "refunded": str(9000 * E6),
             "exit_tx": arrive, "exit_ts": D0 + 2 * DAY, "claim_tx": claim, "claim_ts": D0 + 3 * DAY}],
            "auctions": {AUC: {"ok": True, "currency": {"addr": USDC, "sym": "USDC", "dec": 6}, "token": {"addr": TKN, "sym": "TKN", "dec": 18}}}}}},
            open(paths.state("sale_bids.json"), "w"))
    elif mode == "rt":
        P = "0x" + "e9" * 20
        add("eth", 3, D0 + DAY, W, P, [(W, P, USDC, "USDC", 6, 10000 * E6)])
        add("eth", 4, D0 + DAY + 3600, W, P, [(P, W, USDC, "USDC", 6, 10000 * E6)])
        add("eth", 5, D0 + 10 * DAY, W, ROUTER, [(W, ROUTER, USDC, "USDC", 6, 10000 * E6)], [(ROUTER, W, E18)])
    else:
        add("eth", 5, D0 + 10 * DAY, W, ROUTER, [(W, ROUTER, USDC, "USDC", 6, 10000 * E6)], [(ROUTER, W, E18)])
    c.conn.commit()
    for ch, hx in feed:
        c.svc_price._price_tx(ch, hx)
    c.conn.commit()
    orig = c.conn.execute("SELECT p.cost_usd FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.source_id=? AND p.leg_kind='acq' AND a.symbol='USDC'",
                          (buy,)).fetchone()
    f, _G, _rr = S.build()
    r = S.realized(f)
    tax = S.tax_sum(f)
    pend = [str(z.get("key", "")) for z in f.get("pendings", []) if str(z.get("key", "")).startswith(("unv:", "unvlost:", "unkh:", "noproc:"))]
    return {"r": round(r, 6), "tax": round(tax, 6), "pend": pend, "orig": float(orig[0]) if orig else None}


res = {m: T.safe(go, m) or {} for m in ("control", "cca", "bridge", "nolink", "rt")}
chk(res["control"].get("orig") == 10100.0 and res["control"].get("r") == -100.0, "S0 대조 — 스왑 원가 $10,100 · 그대로 매도 = 실현 −$100", res["control"])
chk(res["cca"].get("r") == -100.0, "S1 CCA 스테이블 환불 = 입찰 원가 복원 → 실현 −$100(종전 −$10)", res["cca"])
chk(res["bridge"].get("r") == -100.0, "S2 브릿지 id 연결 스테이블 도착 = 원가 승계 → 실현 −$100(종전 0)", res["bridge"])
chk(res["nolink"].get("r") == 0.0, "S3 id 연결 없는 같은 수량 스테이블 도착 = 액면(수량 휴리스틱 안 넓힘 — 종전 그대로)", res["nolink"])
chk(res["rt"].get("r") == -100.0, "S4 프로그램 예치 왕복(같은 지갑 · 1시간 뒤 같은 수량 복귀) 스테이블 = 원가 복원 → 실현 −$100(종전 0 · F04-v1)", res["rt"])
for m, v in res.items():
    chk(v and abs(v["tax"] - v["r"]) < 0.01 and not v["pend"], f"{m}: 명세 합 = 실현 합 · 원가 미상·검토 대기 없음", v)
T.finish()
