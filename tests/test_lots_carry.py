#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _costsim as S  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
from decimal import Decimal as D  # noqa: E402

import accounting_basis as B  # noqa: E402
import calcguard as CG  # noqa: E402
import paths  # noqa: E402
import xchain_match  # noqa: E402

chk = T.chk
DAY = 86400


def _eth_lots(rr):
    out = []
    for g in rr.G.values():
        bk = rr._cb.lots_of(g)
        if g["sym"] == "ETH" and bk is not None:
            out.extend((x.ts, str(q)) for x, q, _c in bk.eff() if q > 0)
    return sorted(out)


def trip(back):
    c = S.reset()
    ch = S.Ch(c)
    t0 = S.NOW - 40 * DAY
    S.PXF[0] = lambda sym, ts: 2000 if sym == "ETH" else None
    usdc_b = ch.tok("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6)
    eth_b = ch.tok("base", None, "ETH", 18, kind="native")
    eth_a = ch.tok("arbitrum", None, "ETH", 18, kind="native")
    ch.tx("base", "fund", t0, [(usdc_b, 10000, "acq", 10000)], "PROGRAM_IN")
    ch.tx("base", "buy1", t0 + DAY, [(usdc_b, -2000, "disp", 2000), (eth_b, 1, "acq", 2000)], "SWAP")
    ch.tx("base", "buy2", t0 + 2 * DAY, [(usdc_b, -2600, "disp", 2600), (eth_b, 1, "acq", 2600)], "SWAP")
    x = ch.tx("base", "send", t0 + 3 * DAY, [(eth_b, -2, "move_out", None), (eth_b, 2, "move_in", None, "out:base:0x" + "9b" * 20)], "TRANSFER_OUT")
    y = ch.tx("arbitrum", "arr", t0 + 3 * DAY + 120, [(eth_a, 2, "acq", None)], "TRANSFER_IN")
    arr = {f"arbitrum|{y}": {"status": "link", "src_chain": "base", "src_tx": x, "proto": "debridge"}}
    if back:
        x2 = ch.tx("arbitrum", "send2", t0 + 5 * DAY, [(eth_a, -2, "move_out", None), (eth_a, 2, "move_in", None, "out:arbitrum:0x" + "9c" * 20)],
                   "TRANSFER_OUT")
        y2 = ch.tx("base", "arr2", t0 + 5 * DAY + 120, [(eth_b, 2, "acq", None)], "TRANSFER_IN")
        arr[f"base|{y2}"] = {"status": "link", "src_chain": "arbitrum", "src_tx": x2, "proto": "debridge"}
    json.dump({"v": xchain_match.CACHE_V, "arr": arr}, open(os.path.join(paths.STATE_DIR, xchain_match.CACHE_NAME), "w"))
    f, G, rr = S.build()
    return {"t": (t0 + DAY, t0 + 2 * DAY), "lots": _eth_lots(rr), "audit": rr._cb.lots_audit(G, "t"), "stats": rr._cb.lots_stats(G),
            "cost": round(S.cost_end(G), 6), "rz": round(S.realized(f), 6), "arr_ts": (t0 + 3 * DAY + 120, t0 + 5 * DAY + 120)}


for back, lab in ((False, "L-b 브릿지 이동"), (True, "L-f 이동 왕복")):
    r = T.safe(trip, back) or {}
    ts9 = set(t for t, _q in r.get("lots") or ())
    chk(r and ts9 == set(r["t"]) and not (ts9 & set(r["arr_ts"])) and not r["audit"] and r["stats"]["broken"] == 0
        and abs(r["cost"] - 10000) < 1e-6 and abs(r["rz"]) < 1e-6,
        "%s 뒤 받는 쪽 확인 로트 취득 시각 = 보낸 쪽 매수 시각(도착 시각 아님) · 로트 합 = 칸 · 원가·실현 종전과 같음" % lab,
        {k: r.get(k) for k in ("lots", "t", "arr_ts", "audit", "cost", "rz")})

cb = B.StrictCostBasis()
G = {1: cb.new_group(1, "TKG", False, False)}
g = G[1]
cb.acquire(g, D("2.5"), D(50), ts=100, src=77)
cb.acquire(g, u=D("1.5"), ts=100, src=77)
bk = cb.lots_of(g)
n0 = (len(bk.known), len(bk.unknown), bk.known[0].src, bk.unknown[0].src)
fk = min(D(3), g["qty_known"])
cb.release(g, fk, cb.wac(g) * fk, D(3) - fk)
try:
    cb.check(G, "t")
    eg = None
except AssertionError as e:
    eg = str(e)
chk(n0 == (1, 1, 77, 77) and eg is None and not bk.known and str(bk.unknown[0].qty) == "1.0",
    "L-g LP 꼴 같은 posting_id 확인 acquire + 미확인 acquire = 확인 로트 1 · 미확인 로트 1(합침 없음) · 처분 뒤 합 = 칸(엄격 check)", (n0, eg))

snap = CG.snapshot().get("accounting_basis.lots_audit[replay]")
chk(snap is None, "L-k 끝까지 빌드(이동 · 왕복 · 매수 · 매도 섞임) 라이브 감사 = 로트 불일치 기록 0", snap)

T.finish()
