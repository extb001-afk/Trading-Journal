#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
from decimal import Decimal

import db as dbm
import web

chk = T.chk
D = Decimal

sell, buy = {7: D(-1000)}, {7: D(1000)}
chk(web._ord_tie([sell, buy], {7: D(0)}) == [1, 0], "O1 보유 0 · 매도가 앞 → 매수 먼저")
chk(web._ord_tie([sell, buy], {7: D(1000)}) == [0, 1], "O1 보유 충분 → 원래 순서(매도 먼저 — 평단 섞임 새로 안 만듦)")
chk(web._ord_tie([sell, buy], {7: D(400)}) == [1, 0], "O1 보유 일부(400 < 1000) → 매수 먼저")
k_sell_first = [("c", "base", 100), ("c", "base", 101)]
chk(web._ord_tie([sell, buy], {7: D(0)}, k_sell_first) == [0, 1], "O1 블록 번호가 매도 먼저 → 보유 0 이어도 확실한 순서 그대로")
chk(web._ord_tie([sell, buy], {7: D(1000)}, [("c", "base", 101), ("c", "base", 100)]) == [1, 0], "O1 블록 번호가 매수 먼저 → 보유 충분해도 매수 먼저")
chk(web._ord_tie([sell, buy], {7: D(0)}, [("c", "base", 100), ("c", "base", 100)]) == [1, 0], "O1 같은 블록 = 모름 → 보유 판정")
chk(web._ord_tie([{}, sell, buy], {7: D(0)}) == [0, 2, 1], "O1 상관없는 블록은 제자리")
chk(web._ord_tie([sell, {}, buy], {7: D(0)}) == [2, 0, 1], "O1 모자란 매도 앞으로는 그 그룹을 취득하는 블록만(상관없는 블록은 매도 뒤 그대로)")
chk(web._ord_tie([sell, {7: D(-5), 8: D(1)}, buy], {7: D(0)}) == [2, 0, 1], "O1 자기도 모자란 블록은 앞으로 안 당김")
chk(web._ord_tie([sell, {9: D(1000)}], {7: D(0), 9: D(0)}) == [0, 1], "O1 다른 그룹만 취득하는 블록 = 도움 안 됨 → 원래 순서")
sellB, swapAB, buyA = {8: D(-500)}, {7: D(-1000), 8: D(500)}, {7: D(1000)}
chk(web._ord_tie([sellB, swapAB, buyA], {7: D(0), 8: D(0)}) == [2, 1, 0], "O1 (L1) 3단계 같은 초 = 아무도 모자라지 않는 순서(매수 → 스왑 → 매도)")
chk(web._ord_tie([swapAB, sellB, buyA], {7: D(0), 8: D(0)}) == [2, 0, 1], "O1 (L1) 3단계 다른 원래 순서도 같은 답")
chk(web._ord_tie([sellB, swapAB, buyA], {7: D(1000), 8: D(500)}) == [0, 1, 2], "O1 (L1) 보유 충분하면 원래 순서 그대로")
chk(web._ord_tie([sellB, {}, swapAB, buyA], {7: D(0), 8: D(0)}) == [3, 2, 0, 1], "O1 (L1) 상관없는 블록은 모자란 매도 뒤 제자리")
chk(web._ord_tie([sellB, swapAB, buyA], {7: D(0), 8: D(0)}, [("c", "base", 100), None, None]) == [2, 1, 0],
    "O1 (L1) 다른 블록 키가 모름이면 탐색 그대로")
chk(web._ord_tie([sellB, swapAB, buyA], {7: D(0), 8: D(0)}, [("c", "base", 100), ("c", "base", 101), ("c", "base", 102)]) == [0, 1, 2],
    "O1 (L1) 블록 번호가 순서를 정하면 그대로(모자라도 확실한 순서 — 탐색 실패 → 한 단계 규칙)")
b3 = {7: D(0), 8: D(0)}
web._ord_tie([sellB, swapAB, buyA], b3)
chk(b3 == {7: D(0), 8: D(0)}, "O1 (L1) 탐색 뒤 보유 갱신", b3)
chk(web._ord_feasible([sell, {7: D(-5), 8: D(1)}, buy], {7: D(0)}, [0, 0, 0]) is None, "O1 (L1) 어떻게 해도 모자라면 None(→ 한 단계 규칙)")
b9 = {7: D(0)}
web._ord_tie([sell, buy], b9)
chk(b9 == {7: D(0)}, "O1 보유 갱신(매수 +1000 → 매도 −1000 = 0)", b9)

ab = web._ord_auth_before
chk(ab(("c", "base", 1), ("c", "base", 2)) and not ab(("c", "base", 2), ("c", "base", 1)), "O2 같은 체인 블록 번호")
chk(not ab(("c", "base", 1), ("c", "arbitrum", 2)), "O2 다른 체인 = 모름")
chk(not ab(None, ("c", "base", 2)) and not ab(("c", "base", None), ("c", "base", 2)), "O2 키 없음 = 모름")
chk(ab(("x", "binance", 100, "AUSDT", 9), ("x", "binance", 200, "AUSDT", 1)), "O2 같은 거래소 ms 가 앞이면 먼저(번호 무관)")
chk(ab(("x", "binance", 100, "AUSDT", 999), ("x", "binance", 100, "AUSDT", 1000)), "O2 ms 같으면 같은 시장 체결 번호(999 < 1000 — 글자 순과 반대)")
chk(not ab(("x", "binance", 100, "AUSDT", 1), ("x", "binance", 100, "BUSDT", 2)), "O2 ms 같고 시장 다르면 모름")
chk(not ab(("x", "bithumb", 1000, "", None), ("x", "bithumb", 1000, "", None)), "O2 초 단위 ms·번호 없음(빗썸) = 모름")
chk(not ab(("x", "binance", 100, "A", 1), ("x", "okx", 200, "A", 2)), "O2 다른 거래소 = 모름")
chk(ab(("c", "base", 7, 3, None), ("c", "base", 7, 9, None)) and not ab(("c", "base", 7, 9, None), ("c", "base", 7, 3, None)), "O2 (L1) 같은 블록 tx 순번")
chk(ab(("c", "base", 7, None, 10), ("c", "base", 7, None, 25)), "O2 (L1) 같은 블록 순번 없으면 첫 로그 번호")
chk(ab(("c", "base", 7, 3, 99), ("c", "base", 7, None, 120)), "O2 (L1) 한쪽만 순번 = 로그 번호로")
chk(not ab(("c", "base", 7, 3, None), ("c", "base", 7, None, 5)), "O2 (L1) 서로 다른 종류만 있으면 모름")
chk(ab(("c", "base", 6, 9, 99), ("c", "base", 7, 1, 1)), "O2 (L1) 블록 번호가 먼저")
chk(not ab(("c", "base", 7), ("c", "base", 7, 1, 1)), "O2 (L1) 옛 3칸 키와 같은 블록 = 모름")

R = list(range(10))
chk(web._ord_splice(R, [(2, (6, 8))]) == [0, 1, 6, 7, 2, 3, 4, 5, 8, 9], "O3 블록 6~7 을 2 앞으로")
chk(web._ord_splice(R, [(8, (2, 4))]) == [0, 1, 4, 5, 6, 7, 2, 3, 8, 9], "O3 블록 2~3 을 8 앞(= 7 뒤)으로")
chk(web._ord_splice(R, [(1, (3, 4)), (9, (5, 7))]) == [0, 3, 1, 2, 4, 7, 8, 5, 6, 9], "O3 두 옮김을 한 번에")


def rw(ns, sid, t, gid):
    return {"source_ns": ns, "source_id": sid, "event_ts": t, "group_id": gid, "asset_id": gid}


RW = [rw("arbitrum", "a1", 100, 20), rw("base", "x1", 200, 30), rw("base", "d1", 400, 10), rw("base", "d1", 400, 11)]
mv, kp = web._ord_pair_moves(RW, [(0, 2)])
chk(mv == [(0, (2, 4))] and kp == 0 and [r["source_id"] for r in web._ord_splice(RW, mv)] == ["d1", "d1", "a1", "x1"],
    "O3 (NA6) 사이에 출발 그룹 행 없음 → 출발 블록(가스 레그 포함)을 도착 앞으로", (mv, kp))
RW2 = [rw("arbitrum", "a1", 100, 20), rw("base", "x1", 200, 10), rw("base", "d1", 400, 10)]
mv, kp = web._ord_pair_moves(RW2, [(0, 2)])
chk(mv == [(3, (0, 1))] and [r["source_id"] for r in web._ord_splice(RW2, mv)] == ["x1", "d1", "a1"], "O3 (NA6) 사이에 출발 그룹 행 → 도착을 출발 뒤로", mv)
RW3 = [rw("arbitrum", "a1", 100, 20), rw("base", "x1", 200, 10), rw("arbitrum", "y1", 300, 20), rw("base", "d1", 400, 10)]
mv, kp = web._ord_pair_moves(RW3, [(0, 3)])
chk(mv == [] and kp == 1, "O3 (NA6) 사이에 양쪽 그룹 행 = 그대로(못 옮김)", (mv, kp))
RW4 = [rw("arbitrum", "a1", 100, 10), rw("base", "d1", 400, 10)]
mv, kp = web._ord_pair_moves(RW4, [(0, 1)])
chk(mv == [(0, (1, 2))], "O3 (NA6) 같은 그룹(메이저 묶음) 브릿지도 두 블록 사이만 봄 → 출발을 앞으로", mv)


def dep(pid, ord_, qty, ts=1000, chain="base", sym="TKN", addr="0xaa", tx=None):
    return {"pid": pid, "ord": ord_, "sym": sym, "qty": D(str(qty)), "ts": ts, "chain": chain, "addr": addr, "link": (chain, tx or f"0xd{pid}")}


def arr(pid, ord_, qty, ts=1100, chain="arbitrum", sym="TKN", addr="0xbb", spam=False, bridge=False, tx=None):
    return {"pid": pid, "ord": ord_, "sym": sym, "qty": D(str(qty)), "ts": ts, "chain": chain, "addr": addr, "link": (chain, tx or f"0xa{pid}"),
            "spam": spam, "bridge": bridge}


bp = web._bridge_plan
chk(bp([dep(1, 1, 1000)], [arr(10, 2, 100, 1060), arr(11, 3, 999, 1900)]) == {11: 1}, "O4 무관한 100 이 먼저 와도 진짜 999 가 짝")
chk(bp([dep(1, 1, 1000)], [arr(10, 2, 100)]) == {}, "O4 수량 10% 만 온 도착 = 짝 없음(하한)")
chk(bp([dep(1, 1, 1000)], [arr(10, 2, 1021)]) == {}, "O4 102% 초과 = 짝 없음")
chk(bp([dep(1, 1, 259870)], [arr(10, 2, 160000, 4600), arr(11, 3, 99862, 11080)]) == {10: 1, 11: 1}, "O4 분할 도착 160,000 + 99,862 묶음")
chk(bp([dep(1, 1, 259870)], [arr(10, 2, 160000, 4600)]) == {}, "O4 분할 한 조각만(합 62%) = 짝 없음")
chk(bp([dep(1, 1, 1000, addr="0xoft")], [arr(10, 2, 1000, 1030, addr="0xfake"), arr(11, 3, 999, 1120, addr="0xoft")]) == {11: 1},
    "O4 같은 컨트랙트(같은 주소 OFT) 우선 — 먼저 온 다른 컨트랙트 가짜는 안 씀")
chk(bp([dep(1, 1, 1000)], [arr(10, 2, 1000, spam=True), arr(11, 3, 999)]) == {11: 1}, "O4 스팸(스캠 강신호·사칭) 도착 제외")
chk(bp([dep(1, 1, 1000)], [arr(10, 2, 1000), arr(11, 3, 999, bridge=True)]) == {11: 1}, "O4 브릿지·솔버 도착 판정이 있는 쪽 우선")
chk(bp([dep(1, 1, 1000, tx="0xdep")], [arr(10, 2, 999), arr(11, 3, 500, tx="0xid")], {("arbitrum", "0xid"): ("base", "0xdep")}) == {11: 1},
    "O4 id 연결(프로토콜) = 수량 무관 그 도착")
chk(bp([dep(1, 1, 1000, chain="base", tx="0xd1"), dep(2, 2, 1000, chain="eth", tx="0xd2")],
       [arr(10, 3, 999, bridge=True, tx="0xa1"), arr(11, 4, 999, chain="sol", tx="0xa2")], {("arbitrum", "0xa1"): ("eth", "0xd2")}) == {10: 2, 11: 1},
    "O4 (od309 ①) 다른 출발에 id 로 연결된 도착은 앞선 출발의 수량 짝이 가로채지 못함 — id 짝 먼저 확정")
chk(bp([dep(1, 1, 1000, tx="0xd1")], [arr(10, 2, 999, tx="0xa1")], {("arbitrum", "0xa1"): ("optimism", "0xelse")}) == {},
    "O4 (od309 ①) 원장 밖·다른 출발(보낸 내역 등)에 id 로 연결된 도착 = 수량 짝 후보 아님")
chk(bp([dep(1, 1, 100)], [arr(10, 2, 93)]) == {10: 1}, "O4 수수료 7% 소액 · 양방향 유일 → 짝")
chk(bp([dep(1, 1, 100), dep(2, 2, 100, ts=1200)], [arr(10, 3, 93, 1300)]) == {}, "O4 수수료 큰 소액인데 출발 후보 둘 = 짝 없음(모호)")
chk(bp([dep(1, 1, 100)], [arr(10, 2, 93), arr(11, 3, 50)]) == {}, "O4 수수료 큰 소액인데 도착 후보 둘 = 짝 없음(모호)")
chk(bp([dep(1, 1, 100)], [arr(10, 2, 85)]) == {}, "O4 90% 미만 = 짝 없음")
chk(bp([dep(1, 5, 1000)], [arr(10, 4, 999, 990)]) == {10: 1}, "O4 (NA6) 출발보다 먼저 찍힌 도착(창 −10분 안) = 짝(재생 순서는 호출자가 출발을 앞으로)")
chk(bp([dep(1, 5, 1000)], [arr(10, 4, 999, 1000 - 601)]) == {}, "O4 (NA6) 출발보다 10분 넘게 먼저 = 짝 없음(창 밖)")
chk(bp([dep(1, 5, 1000)], [arr(10, 4, 999, 700), arr(11, 6, 1000, 1900)]) == {11: 1}, "O4 (NA6) 같은 컨트랙트 후보면 출발 뒤 도착 우선(직전 무관 유입이 가로채지 않게)")
chk(bp([dep(1, 1, 1000)], [arr(10, 2, 999, chain="base")]) == {}, "O4 같은 체인 유입 = 짝 없음")
chk(bp([dep(1, 1, 1000)], [arr(10, 2, 999, 1000 + 21601)]) == {}, "O4 6시간 창 밖 = 짝 없음")
chk(bp([dep(1, 1, 1000)], [arr(10, 2, 999, sym="TKX")]) == {}, "O4 다른 심볼 = 짝 없음")
chk(bp([dep(1, 1, 1000, ts=1000), dep(2, 3, 1000, ts=4600)], [arr(10, 2, 999, 1600), arr(11, 4, 999, 8200)]) == {10: 1, 11: 2},
    "O4 같은 수량 브릿지 두 번 = 시간 순으로 하나씩")
chk(bp([dep(1, 1, 1000), dep(2, 2, 500, ts=1050)], [arr(10, 3, 499, 1100), arr(11, 4, 999, 1300)]) == {10: 2, 11: 1},
    "O4 수량이 맞는 쪽끼리(1000 ↔ 999 · 500 ↔ 499)")
amb = {}
chk(bp([dep(1, 1, 1000)], [arr(10, 2, 995, 1060, addr="0xdecoy"), arr(11, 3, 999, 1900, addr="0xreal")], None, amb) == {} and amb == {10: 1, 11: 1},
    "O4 (L2) 컨트랙트 다른 비슷한 수량 미끼(995)·진짜(999) = 짝 없음 + 모호 목록", amb)
chk(bp([dep(1, 1, 1000, addr="0xreal")], [arr(10, 2, 995, 1060, addr="0xdecoy"), arr(11, 3, 999, 1900, addr="0xreal")]) == {11: 1},
    "O4 (L2) 같은 컨트랙트(공식 매핑) 후보가 있으면 그 층만 → 진짜")
chk(bp([dep(1, 1, 1000)], [arr(10, 2, 995, 1060, addr="0xdecoy"), arr(11, 3, 999, 1900, addr="0xreal", bridge=True)]) == {11: 1},
    "O4 (L2) 브릿지·솔버 도착 판정 후보가 하나면 그 층만 → 그 도착")
chk(bp([dep(1, 1, 1000)], [arr(10, 2, 995, 1060, addr="0xdecoy", bridge=True), arr(11, 3, 999, 1900, addr="0xreal", bridge=True)]) == {},
    "O4 (L2) 브릿지 판정 층에도 컨트랙트가 둘 = 짝 없음")
chk(bp([dep(1, 1, 1000)], [arr(10, 2, 995, 1060, addr="0xsame"), arr(11, 3, 999, 1900, addr="0xsame")]) == {10: 1},
    "O4 (L2) 비슷한 수량 둘이 같은 컨트랙트 = 모호 아님 → 먼저 온 것")
amb2 = {}
chk(bp([dep(1, 1, 1000)], [arr(10, 2, 995, 1060, addr="0xdecoy"), arr(11, 3, 999, 1900, addr="0xreal"), arr(12, 4, 500, 2000, addr="0xreal"),
                            arr(13, 5, 495, 2100, addr="0xreal")], None, amb2) == {} and 12 not in amb2,
    "O4 (L2) 모호하면 그 출발은 분할 묶음·소액 단계도 안 봄(분할 조각이 대신 짝 되지 않음)", amb2)

DB = os.path.join(T.TMP, "state", "ledger_order.db")
c = dbm.open_db(DB)
W = "0x" + "a7" * 20
WB = f"wallet:base:{W}"
c.executemany("INSERT INTO asset_groups (group_id, name) VALUES (?, ?)", [(1, "USDC"), (2, "AAA#2"), (3, "BBB#3"), (4, "KRW#4"), (5, "GGG#5"),
                                                                         (6, "LLL#6"), (7, "LLL#7"), (8, "HHH#8")])
c.executemany("INSERT INTO assets (asset_id, kind, chain, address, symbol, decimals, group_id) VALUES (?,?,?,?,?,?,?)", [
    (1, "token", "base", "0x" + "11" * 20, "USDC", 6, 1), (2, "token", "base", "0x" + "21" * 20, "AAA", 18, 2),
    (3, "token", "base", "0x" + "31" * 20, "BBB", 18, 3), (4, "exchange_currency", None, "bithumb:krw", "KRW", 8, 4),
    (5, "exchange_currency", None, "bithumb:ggg", "GGG", 8, 5), (6, "exchange_currency", None, "upbit:lll", "LLL", 8, 6),
    (7, "token", "base", "0x" + "71" * 20, "LLL", 18, 7), (8, "exchange_currency", None, "bithumb:hhh", "HHH", 8, 8)])
DEC = {1: 6, 2: 18, 3: 18, 4: 8, 5: 8, 6: 8, 7: 18, 8: 8}
SEQ = {}


def post(sk, ns, sid, t, aid, loc, qty, lk, ev):
    n9 = SEQ.get((ns, sid), 0)
    SEQ[(ns, sid)] = n9 + 1
    c.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw,"
              " leg_kind, event, classifier_ver) VALUES (?,?,?,?,?,?,?,?,NULL,NULL,?,?,5)",
              (sk, ns, sid, n9, t, aid, loc, str(int(D(str(qty)) * 10 ** DEC[aid])), lk, ev))


def swap(tx, t, aid, qty, buy):
    if buy:
        post("chain_tx", "base", tx, t, 1, WB, -qty, "disp", "SWAP")
        post("chain_tx", "base", tx, t, aid, WB, qty, "acq", "SWAP")
    else:
        post("chain_tx", "base", tx, t, aid, WB, -qty, "disp", "SWAP")
        post("chain_tx", "base", tx, t, 1, WB, qty, "acq", "SWAP")


T0 = 1_780_000_000
post("opening", "base", "recon:base:usdc", T0 - 999, 1, WB, 10 ** 6, "opening", "OPENING")
TX_SELL_A, TX_BUY_A = "0x" + "0a" * 32, "0x" + "fa" * 32
swap(TX_SELL_A, T0, 2, 1000, False)
swap(TX_BUY_A, T0, 2, 1000, True)
TX_SELL_B, TX_BUY_B = "0x" + "0b" * 32, "0x" + "fb" * 32
swap(TX_SELL_B, T0 + 10, 3, 1000, False)
swap(TX_BUY_B, T0 + 10, 3, 1000, True)
for tx9, blk9 in ((TX_SELL_B, 100), (TX_BUY_B, 101)):
    c.execute("INSERT INTO raw_txs (chain, txhash, block, ts, snapshot, wallets, ingested_at) VALUES ('base', ?, ?, ?, '{}', '[]', 0)", (tx9, blk9, T0 + 10))
HX = "exchange:bithumb"
post("exchange", "bithumb:trade", "bithumb:C1", T0 + 20, 5, HX, 10, "acq", "EXF_BUY")
post("exchange", "bithumb:trade", "bithumb:C1", T0 + 20, 4, HX, -130000, "disp", "EXF_SELL")
post("exchange", "bithumb:trade", "bithumb:C2", T0 + 20, 8, HX, -10, "disp", "EXF_SELL")
post("exchange", "bithumb:trade", "bithumb:C2", T0 + 20, 4, HX, 135000, "acq", "EXF_BUY")
TX_L = "0x" + "1c" * 32
post("exchange", "upbit:order", "o-1", T0 - 500, 6, "exchange:upbit", 1, "acq", "EX_BUY")
post("chain_tx", "base", TX_L, T0 + 30, 7, WB, 1, "acq", "TRANSFER_IN")
post("chain_tx", "base", "0x" + "2d" * 32, T0 + 60, 2, WB, -1, "move_out", "TRANSFER_OUT")
post("exchange", "upbit:withdraw", "wd-1", T0 + 150, 6, "exchange:upbit", -1, "move_out", "EX_WITHDRAW")
c.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('upbit', 'withdraw', 'wd-1', 1, ?, 0)",
          (json.dumps({"uuid": "wd-1", "currency": "LLL", "txid": TX_L, "state": "DONE", "amount": "1", "fee": "0"}),))
c.commit()
sb = web.StateBuilder.__new__(web.StateBuilder)
rows0 = web.StateBuilder._load(sb, c)
keys0 = [(r["source_ns"], r["source_id"]) for r in rows0]
rows1 = web.StateBuilder._replay_order(sb, c, rows0)
keys1 = [(r["source_ns"], r["source_id"]) for r in rows1]


def first(keys, k):
    return keys.index(k)


chk(first(keys0, ("base", TX_SELL_A)) < first(keys0, ("base", TX_BUY_A)), "O5 (전제) 종전 정렬 = 해시 글자 순 매도 먼저")
chk(first(keys1, ("base", TX_BUY_A)) < first(keys1, ("base", TX_SELL_A)), "O5 같은 초 · 보유 0 → 매수 먼저", keys1)
chk(first(keys1, ("base", TX_SELL_B)) < first(keys1, ("base", TX_BUY_B)), "O5 블록 번호 매도 100 < 매수 101 → 그대로")
chk(first(keys1, ("bithumb:trade", "bithumb:C1")) < first(keys1, ("bithumb:trade", "bithumb:C2")), "O5 빗썸 원화 처분·취득 = 그대로(원화 판정 제외)")
chk(first(keys1, ("upbit:withdraw", "wd-1")) < first(keys1, ("base", TX_L)), "O5 늦게 기록된 업비트 출금 → 같은 txid 도착 바로 앞으로")
chk(keys1.index(("upbit:withdraw", "wd-1")) + 1 == keys1.index(("base", TX_L)), "O5 출금 블록이 도착 바로 앞")
chk(sorted(map(id, rows1)) == sorted(map(id, rows0)) and len(rows1) == len(rows0), "O5 행 집합 무변(옮기기만)")
od = sb._ord_diag
chk((od["tieRuns"], od["tieMoved"], od["wdMoved"], od["arrMoved"], od["wdKept"]) == (2, 1, 1, 0, 0), "O5 진단 = 판정 묶음 2(AAA·BBB) · 바뀜 1 · 출금 앞으로 1", od)
chk([r["event_ts"] for r in rows1 if (r["source_ns"], r["source_id"]) == ("base", TX_L)] == [T0 + 30], "O5 시각 값 무변")
post("exchange", "upbit:order", "o-2", T0 + 90, 6, "exchange:upbit", 1, "acq", "EX_BUY")
post("chain_tx", "base", "0x" + "3e" * 32, T0 + 100, 7, WB, -1, "move_out", "TRANSFER_OUT")
c.commit()
sb2 = web.StateBuilder.__new__(web.StateBuilder)
rows2 = web.StateBuilder._replay_order(sb2, c, web.StateBuilder._load(sb2, c))
keys2 = [(r["source_ns"], r["source_id"]) for r in rows2]
chk(first(keys2, ("base", TX_L)) < first(keys2, ("upbit:withdraw", "wd-1")) and sb2._ord_diag["wdKept"] == 1,
    "O5 사이에 양쪽 그룹 행이 다 있으면 못 옮김(그룹별 순서 지킴 · wdKept)", sb2._ord_diag)
c.execute("DELETE FROM postings WHERE source_id IN ('o-2', ?)", ("0x" + "3e" * 32,))
post("exchange", "upbit:order", "o-3", T0 + 90, 6, "exchange:upbit", 1, "acq", "EX_BUY")
c.commit()
sb3 = web.StateBuilder.__new__(web.StateBuilder)
rows3 = web.StateBuilder._replay_order(sb3, c, web.StateBuilder._load(sb3, c))
keys3 = [(r["source_ns"], r["source_id"]) for r in rows3]
chk(keys3.index(("base", TX_L)) == keys3.index(("upbit:withdraw", "wd-1")) + 1 and sb3._ord_diag["arrMoved"] == 1,
    "O5 사이에 출금 그룹 행만 있으면 도착을 출금 바로 뒤로", sb3._ord_diag)
c.close()

DB6 = os.path.join(T.TMP, "state", "ledger_order6.db")
c = dbm.open_db(DB6)
c.executemany("INSERT INTO asset_groups (group_id, name) VALUES (?, ?)", [(1, "USDC"), (2, "AAA#2"), (3, "BBB#3")])
c.executemany("INSERT INTO assets (asset_id, kind, chain, address, symbol, decimals, group_id) VALUES (?,?,?,?,?,?,?)", [
    (1, "token", "base", "0x" + "11" * 20, "USDC", 6, 1), (2, "token", "base", "0x" + "21" * 20, "AAA", 18, 2),
    (3, "token", "base", "0x" + "31" * 20, "BBB", 18, 3)])
SEQ.clear()
post("opening", "base", "recon:base:usdc", T0 - 999, 1, WB, 10 ** 6, "opening", "OPENING")
post("chain_tx", "base", "0x" + "77" * 32, T0 - 500, 2, WB, 1000, "acq", "TRANSFER_IN")
post("chain_tx", "base", "0x" + "78" * 32, T0 - 500, 3, WB, 1000, "acq", "TRANSFER_IN")
TX6 = {"a_buy": "0x" + "1a" * 32, "a_sell": "0x" + "9a" * 32, "b_buy": "0x" + "1b" * 32, "b_sell": "0x" + "9b" * 32}
swap(TX6["a_buy"], T0, 2, 1000, True)
swap(TX6["a_sell"], T0, 2, 1000, False)
swap(TX6["b_buy"], T0 + 10, 3, 1000, True)
swap(TX6["b_sell"], T0 + 10, 3, 1000, False)
for tx9, t9, snap9 in ((TX6["a_buy"], T0, {"tx": {"position": 7}}), (TX6["a_sell"], T0, {"tx": {"position": 3}}),
                       (TX6["b_buy"], T0 + 10, {"tx": {}, "token_transfers": [{"log_index": 40}]}),
                       (TX6["b_sell"], T0 + 10, {"tx": {}, "token_transfers": [{"log_index": 12}, {"log_index": 13}]})):
    c.execute("INSERT INTO raw_txs (chain, txhash, block, ts, snapshot, wallets, ingested_at) VALUES ('base', ?, 900, ?, ?, '[]', 0)", (tx9, t9, json.dumps(snap9)))
c.commit()
sb6 = web.StateBuilder.__new__(web.StateBuilder)
rows6 = web.StateBuilder._load(sb6, c)
chk(web.StateBuilder._ord_key(c, next(r for r in rows6 if r["source_id"] == TX6["a_sell"])) == ("c", "base", 900, 3, None)
    and web.StateBuilder._ord_key(c, next(r for r in rows6 if r["source_id"] == TX6["b_sell"])) == ("c", "base", 900, None, 12),
    "O6 키 = (체인, 블록, tx 순번, 첫 로그 번호) — 스냅샷 원본 값")
k6 = [(r["source_ns"], r["source_id"]) for r in web.StateBuilder._replay_order(sb6, c, rows6)]
chk(k6.index(("base", TX6["a_sell"])) < k6.index(("base", TX6["a_buy"])), "O6 tx.position 매도 3 < 매수 7 → 보유 충분해도 매도 먼저", k6)
chk(k6.index(("base", TX6["b_sell"])) < k6.index(("base", TX6["b_buy"])), "O6 log_index 매도 12 < 매수 40 → 매도 먼저", k6)
c.execute("UPDATE raw_txs SET snapshot = 'not json' WHERE txhash = ?", (TX6["a_sell"],))
c.commit()
chk(web.StateBuilder._ord_key(c, next(r for r in rows6 if r["source_id"] == TX6["a_sell"])) == ("c", "base", 900, None, None),
    "O6 스냅샷이 깨져도 블록 번호까지는(순번 모름)")
c.close()
T.finish()
