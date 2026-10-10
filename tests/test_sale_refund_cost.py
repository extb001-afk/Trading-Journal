#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

from decimal import Decimal

import sale_match

chk = T.chk
A, OWN, TOK, USDC = "0x" + "a1" * 20, "0x" + "b1" * 20, "0x" + "c1" * 20, "0x" + "d1" * 20
SEED = {"factories": set(), "chains": ["eth"], "auctions": {}, "redeem": {}}
E18 = 10 ** 18


def bid(amount, refund, bid_ts=1000, exit_ts=2000, filled=1000, i=1):
    return {"auction": A, "id": i, "amount": str(int(amount * E18)), "bid_ts": bid_ts, "bid_tx": "0x%064x" % i,
            "filled": str(int(filled * E18)), "refunded": str(int(refund * E18)), "exit_ts": exit_ts, "exit_tx": "0x%064x" % (100 + i),
            "claim_tx": "0x%064x" % (200 + i), "claim_ts": 3000}


def cache(bids, cur=None):
    return {"owners": {"eth:" + OWN: {"t": 1, "chain": "eth", "owner": OWN, "bids": bids,
                                      "auctions": {A: {"ok": True, "currency": cur or {"addr": "", "sym": "ETH", "dec": 18},
                                                       "token": {"addr": TOK, "sym": "NEW", "dec": 18}}}}}}


def lots_of(c, pf):
    return T.safe(sale_match.build_lots, c, pf, (), SEED) or []


res = []
for exit_px in (1000, 1050, 1111.11, 1200, 900):
    L = lots_of(cache([bid(10, 9)]), lambda s, t, e=exit_px: 1000.0 if t == 1000 else e)
    res.append((exit_px, None if not L else (L[0]["cost"], L[0]["unit"])))
chk(all(r9 and r9[0] == Decimal(1000) and r9[1] == Decimal(1) for _e, r9 in res),
    "S1 10 ETH 입찰·9 ETH 환불·토큰 1,000 — 환불 시세 $1,000/$1,050/$1,111/$1,200/$900 모두 원가 $1,000 · 단가 $1(종전 $1,000/$550/$0.01/삭제/$1,900)",
    [(e, None if r9 is None else (str(r9[0]), str(r9[1]))) for e, r9 in res])

L = lots_of(cache([bid(5, 1, bid_ts=1000, i=1), bid(5, 4, bid_ts=1100, i=2, filled=500)]),
            lambda s, t: {1000: 1000.0, 1100: 2000.0}.get(t, 3000.0))
chk(len(L) == 1 and L[0]["cost"] == Decimal(4 * 1000 + 1 * 2000) and L[0]["qty"] == Decimal(1500),
    "S2 여러 입찰 = (5−1)×$1,000 + (5−4)×$2,000 = $6,000 · 받은 1,500", [(str(l["cost"]), str(l["qty"])) for l in L])

for name, b9 in (("환불 > 입찰", bid(10, 11)), ("환불 < 0", bid(10, -1))):
    L = lots_of(cache([b9]), lambda s, t: 1000.0)
    chk(len(L) == 1 and L[0]["cost"] is None and L[0]["unit"] is None and L[0]["bid_tx"],
        f"S3 {name} = 로트 유지(입찰 인식) · 원가 미확인(종전: 원가 ≤ 0 이면 삭제)", [(l["cost"], l["unit"]) for l in L])

L = lots_of(cache([bid(10, 10)]), lambda s, t: 1000.0)
chk(len(L) == 1 and L[0]["cost"] is None, "S4 전액 환불인데 체결 > 0 = 로트 유지 · 원가 미확인(지우지 않음)", [(l["cost"],) for l in L])

L = lots_of(cache([bid(10, 9)]), lambda s, t: None if t == 1000 else 1200.0)
chk(len(L) == 1 and L[0]["cost"] is None, "S5a 입찰 시세 없음 = 로트 유지 · 원가 미확인(지어내지 않음)", [(l["cost"],) for l in L])
L = lots_of(cache([bid(10, 9)]), lambda s, t: 1000.0 if t == 1000 else None)
chk(len(L) == 1 and L[0]["cost"] == Decimal(1000), "S5b 환불 시세 없음 = 이제 무관(입찰 시세로 원가 $1,000)", [(str(l["cost"]),) for l in L])

usdc = {"addr": USDC, "sym": "USDC", "dec": 6}
cb = cache([{"auction": A, "id": 1, "amount": str(10_000 * 10 ** 6), "bid_ts": 1000, "bid_tx": "0x01", "filled": str(1000 * E18),
             "refunded": str(9_000 * 10 ** 6), "exit_ts": 2000, "exit_tx": "0x02", "claim_tx": "0x03", "claim_ts": 3000}], usdc)
L = lots_of(cb, None)
chk(len(L) == 1 and L[0]["cost"] == Decimal(1000) and L[0]["unit"] == Decimal(1) and L[0]["paid_usd"] == Decimal(10000) and L[0]["refund_usd"] == Decimal(9000),
    "S6 스테이블(USDC) 세일 = 종전과 같음(참여 $10,000 · 환불 $9,000 · 원가 $1,000)", [(str(l["cost"]), str(l["paid_usd"]), str(l["refund_usd"])) for l in L])

L = lots_of(cache([bid(10, 11)]), lambda s, t: 1000.0)
inflow = [{"pid": 7, "kind": "chain", "chain": "eth", "token": TOK, "sym": "NEW", "qty": Decimal(1000), "ts": 3000, "sender": A, "ref": "0x%064x" % 201,
           "to": OWN}]
links = T.safe(sale_match.match, L, inflow) or {}
d9 = T.safe(sale_match.desc, dict(L[0], label="시험 세일")) if L else None
chk(7 in links and links[7].get("unit") is None and links[7].get("cost") is None and isinstance(d9, str) and "단가 미확인" in d9,
    "S7 원가 미확인 로트 — 유입을 로트에 묶되 단가·원가 없음 · 카드 문구 '단가 미확인' · 예외 없음", (links, d9))
T.finish()
