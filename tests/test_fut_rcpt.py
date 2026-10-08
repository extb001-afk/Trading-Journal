#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
from datetime import datetime, timedelta, timezone

os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
with open(os.environ["TJ_CONFIG"], "w") as f:
    json.dump({}, f)
import common
import fut_rcpt as F

assert T.TMP in common.STATE_DIR
KST = timezone(timedelta(hours=9))
D0 = datetime(2026, 1, 15, tzinfo=KST)
ISO = D0.strftime("%Y-%m-%d")
NOW = int((D0 + timedelta(days=2)).timestamp() * 1000)
EXN = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX"}


def check(name, ok, detail=""):
    T.chk(bool(ok), name, None if ok else detail)


def ms(h, m=0, s=0, d=0):
    return int((D0 + timedelta(days=d, hours=h, minutes=m, seconds=s)).timestamp() * 1000)


def ev(ex, kind, amt, t, sym, uid):
    return (datetime.fromtimestamp(t / 1000, KST).strftime("%Y-%m-%d"), t, amt, amt * 1400.0,
            {"kind": kind, "amount": amt, "t": t, "symbol": sym, "uid": uid, "ex": ex})


def asm(fev, px, iso=ISO):
    return F.assemble(iso, fev, px, EXN, lambda by_ex, exn: {}, NOW, accts={})


def trades(r):
    return [t for c in r.get("coins") or () for t in c["trades"]]


def at(r, t_ms):
    return next((t for t in trades(r) if t["exitTs"] == t_ms / 1000), None)


def bnt(i, side, ps, price, qty, pnl, t, sym="AAAUSDT"):
    return {"symbol": sym, "id": i, "orderId": 1000 + i, "side": side, "positionSide": ps, "price": str(price), "qty": str(qty),
            "realizedPnl": str(pnl), "time": t}


def bnpx(trs):
    return {"binance": {"v": 1, "rows": F.rows_binance(trs), "cursor": {"bf_done": True}, "ts": NOW // 1000}}


def bill(bid, st, sz, px, pnl, t, inst="AAA-USDT-SWAP", typ="2"):
    return {"billId": str(bid), "instId": inst, "instType": "SWAP", "type": typ, "subType": str(st), "sz": str(sz), "px": str(px),
            "pnl": str(pnl), "ts": str(t), "ordId": "o" + str(bid)}


def okpx(bills):
    return {"okx": {"v": 1, "rows": F.rows_okx(bills), "ct": {"AAA-USDT-SWAP": 1.0}, "cursor": {"bf_done": True, "bf_v": F.OKX_BF_V},
                    "ts": NOW // 1000}}


T1 = [bnt(1, "BUY", "BOTH", 100, 2, 0, ms(8)), bnt(2, "SELL", "BOTH", 110, 1, 10, ms(9)), bnt(3, "SELL", "BOTH", 120, 1, 20, ms(10)),
      bnt(4, "BUY", "BOTH", 130, 1, 0, ms(11)), bnt(5, "SELL", "BOTH", 125, 1, -5, ms(12))]
E1 = [ev("binance", "REALIZED", 10.0, ms(9), "AAAUSDT", "bn:2:R:1"), ev("binance", "REALIZED", 20.0, ms(10), "AAAUSDT", "bn:3:R:1"),
      ev("binance", "REALIZED", -5.0, ms(12), "AAAUSDT", "bn:5:R:1")]
r = asm(E1, bnpx(T1))
a, b, c = at(r, ms(9)), at(r, ms(10)), at(r, ms(12))
check("[분할] 첫 분할 청산 = 진입 08:00 · 보유 1시간 · 진입가 100", a and a["entryTs"] == ms(8) / 1000 and a["holdS"] == 3600 and a["entryPx"] == 100, a)
check("[분할] 두 번째 분할 청산도 같은 진입 08:00", b and b["entryTs"] == ms(8) / 1000 and b["holdS"] == 7200, b)
check("[분할] 0 이 된 뒤 다시 연 포지션 = 새 진입 11:00", c and c["entryTs"] == ms(11) / 1000 and c["entryPx"] == 130, c)

T2 = [bnt(10, "BUY", "BOTH", 100, 1, 0, ms(8)), bnt(11, "SELL", "BOTH", 110, 3, 10, ms(9)), bnt(12, "BUY", "BOTH", 105, 2, 10, ms(10))]
E2 = [ev("binance", "REALIZED", 10.0, ms(9), "AAAUSDT", "bn:11:R:1"), ev("binance", "REALIZED", 10.0, ms(10), "AAAUSDT", "bn:12:R:1")]
r = asm(E2, bnpx(T2))
a, b = at(r, ms(9)), at(r, ms(10))
check("[반전] 롱 청산분 = 수량 1 · 진입가 100 · 진입 08:00", a and a["side"] == "LONG" and a["qty"] == 1 and a["entryPx"] == 100
      and a["entryTs"] == ms(8) / 1000, a)
check("[반전] 반전으로 연 숏 2 의 청산 = 진입 09:00 · 진입가 110", b and b["side"] == "SHORT" and b["qty"] == 2 and b["entryPx"] == 110
      and b["entryTs"] == ms(9) / 1000, b)

T3 = [bnt(20, "BUY", "BOTH", 100, 1, 0, ms(8)), bnt(21, "SELL", "BOTH", 100, 1, 0, ms(9)), bnt(22, "BUY", "BOTH", 200, 1, 0, ms(10)),
      bnt(23, "SELL", "BOTH", 210, 1, 10, ms(11))]
r = asm([ev("binance", "REALIZED", 10.0, ms(11), "AAAUSDT", "bn:23:R:1")], bnpx(T3))
a = at(r, ms(11))
check("[손익0] 손익 0 청산 뒤 새 진입 = 진입 10:00(옛 08:00 아님) · 진입가 200", a and a["entryTs"] == ms(10) / 1000 and a["entryPx"] == 200, a)
ops = [o for c in r["coins"] for o in c["opens"]]
check("[손익0] 손익 0 청산이 숏 진입 표식(▼)으로 안 그려짐", not any(o["side"] == "SHORT" for o in ops) and len(ops) == 2, ops)
T6 = [bnt(40, "SELL", "BOTH", 100, 1, 0, ms(8)), bnt(41, "SELL", "BOTH", 120, 1, 0, ms(10)), bnt(42, "BUY", "BOTH", 110, 1, 10, ms(11))]
r = asm([ev("binance", "REALIZED", 10.0, ms(11), "AAAUSDT", "bn:42:R:1")], bnpx(T6))
a = at(r, ms(11))
check("[손익0] 평균가 모르는 손익 0 청산(유령 숏) 뒤 진짜 숏 청산 = 진입 10:00(유령 08:00 아님) · 진입가 120",
      a and a["side"] == "SHORT" and a["entryTs"] == ms(10) / 1000 and a["entryPx"] == 120, a)

B_OLD = bill(101, 1, 10, 100, 0, ms(10, d=-2))
B_LIQ = bill(102, 103, 10, 80, -200, ms(3, d=-1))
B_NEW = [bill(103, 1, 5, 90, 0, ms(10)), bill(104, 2, 5, 95, 25, ms(10, 5))]
E4 = [ev("okx", "REALIZED", -200.0, ms(3, d=-1), "AAA-USDT-SWAP", "ok:102:p"), ev("okx", "REALIZED", 25.0, ms(10, 5), "AAA-USDT-SWAP", "ok:104:p")]
r = asm(E4, okpx([B_OLD, B_LIQ] + B_NEW))
a = at(r, ms(10, 5))
check("[누락] 강제청산 103 이 행이 되면 = 5분 거래 보유 300초", a and a["holdS"] == 300 and a["entryTs"] == ms(10) / 1000, a)
liq = asm(E4, okpx([B_OLD, B_LIQ] + B_NEW), iso=(D0 - timedelta(days=1)).strftime("%Y-%m-%d"))
lt = trades(liq)
check("[누락] 강제청산 청산 = 롱 · 강제청산 표시 · 진입 = 이틀 전", lt and lt[0]["side"] == "LONG" and lt[0]["liq"] and lt[0]["entryTs"] == ms(10, d=-2) / 1000, lt)
B_UNK = dict(B_LIQ, subType="199")
check("[누락] 모르는 subType = 가격 행 없음", F.rows_okx([B_UNK]) == [], F.rows_okx([B_UNK]))
r = asm(E4, okpx([B_OLD, B_UNK] + B_NEW))
a = at(r, ms(10, 5))
check("[누락] 청산이 빠져도 5분 거래 = 보유 300초(옛 이틀 전 진입을 안 물려받음 · 평균 진입가 90 으로 다시 세움)",
      a and a["holdS"] == 300 and a["entryTs"] == ms(10) / 1000 and a["entryPx"] == 90, a)
B_MORE = [bill(105, 1, 3, 50, 0, ms(12)), bill(106, 2, 3, 55, 15, ms(12, 30))]
r = asm(E4 + [ev("okx", "REALIZED", 15.0, ms(12, 30), "AAA-USDT-SWAP", "ok:106:p")], okpx([B_OLD, B_UNK] + B_NEW + B_MORE))
b = at(r, ms(12, 30))
check("[누락] 다시 세운 뒤 다음 왕복 = 진입 12:00 · 보유 30분", b and b["entryTs"] == ms(12) / 1000 and b["holdS"] == 1800, b)
B_ODD = [bill(103, 1, 5, 90, 0, ms(10)), bill(104, 2, 5, 95, -20, ms(10, 5))]
r = asm([E4[0], ev("okx", "REALIZED", -20.0, ms(10, 5), "AAA-USDT-SWAP", "ok:104:p")], okpx([B_OLD, B_UNK] + B_ODD))
a = at(r, ms(10, 5))
check("[누락] 맞는 묶음 없음 = 진입 시각 모름(이틀 전 아님) · 가격은 그대로", a and a["entryTs"] is None and a["holdS"] is None and a["px"] != "none", a)
P_ON = round((11.0 - 10.15) * 4, 10)
B_ON = [bill(201, 1, 2, 10.0, 0, ms(20, 42, d=-1)), bill(202, 1, 1, 10.2, 0, ms(21, 54, d=-1)), bill(203, 1, 1, 10.4, 0, ms(23, 28, d=-1)),
        bill(204, 2, 4, 11.0, P_ON, ms(11, 12))]
r = asm([ev("okx", "REALIZED", P_ON, ms(11, 12), "AAA-USDT-SWAP", "ok:204:p")], okpx(B_ON))
a = at(r, ms(11, 12))
check("[누락] 진짜 밤샘 보유 = 전날 20:42 진입 그대로(보유 14시간 30분) · 평균 진입가 10.15",
      a and a["entryTs"] == ms(20, 42, d=-1) / 1000 and a["holdS"] == 14 * 3600 + 30 * 60 and abs(a["entryPx"] - 10.15) < 1e-9, a)

B_PC = [bill(301, 1, 2, 100, 0, ms(8)), bill(302, 2, 1, 110, 10, ms(9)), bill(303, 1, 2, 200, 0, ms(10)),
        bill(304, 2, 1, 170, round(170 - 500 / 3, 10), ms(11)),
        dict(bill(305, 2, 2, 180, round((180 - 500 / 3) * 2, 10), ms(12)), subType="199"),
        bill(306, 1, 2, 150, 0, ms(13)), bill(307, 2, 2, 160, 20, ms(14)), bill(308, 1, 1, 50, 0, ms(15)), bill(309, 2, 1, 55, 5, ms(15, 30))]
E_PC = [ev("okx", "REALIZED", 20.0, ms(14), "AAA-USDT-SWAP", "ok:307:p"), ev("okx", "REALIZED", 5.0, ms(15, 30), "AAA-USDT-SWAP", "ok:309:p")]
r = asm(E_PC, okpx(B_PC))
a, b = at(r, ms(14)), at(r, ms(15, 30))
check("[누락] 부분 청산·추가 진입 뒤 빠진 청산 = 새 진입 13:00(옛 08:00 아님 · 이미 청산된 수량 안 되살림)",
      a and a["entryTs"] == ms(13) / 1000 and a["entryPx"] == 150, a)
check("[누락] 그 뒤 포지션 0 → 다음 왕복 진입 15:00", b and b["entryTs"] == ms(15) / 1000 and b["holdS"] == 1800, b)
_aw = getattr(F, "ANCHOR_WORK", None)
F.ANCHOR_WORK = (0, 0)
try:
    r = asm(E4, okpx([B_OLD, B_UNK] + B_NEW))
finally:
    F.ANCHOR_WORK = _aw
a = at(r, ms(10, 5))
check("[누락] 다시 세우기 작업 상한을 넘으면 = 진입 시각 모름(이틀 전 아님)", a and a["entryTs"] is None and a["px"] != "none", a)
B_SP = [bill(1001, 1, 100, 1.0, 0, ms(10, d=-36)), bill(1002, 2, 60, 1.1, 6, ms(11, d=-36)), dict(bill(1003, 2, 40, 1.1, 4, ms(12, d=-36)), subType="199"),
        bill(1004, 1, 10, 1.0, 0, ms(10)), bill(1005, 2, 10, 1.05, 0.5, ms(10, 5))]
E_SP = [ev("okx", "REALIZED", 0.5, ms(10, 5), "AAA-USDT-SWAP", "ok:1005:p")]
r = asm(E_SP, okpx(B_SP))
a = at(r, ms(10, 5))
check("[누락·같은 가격] 빠진 청산 뒤 같은 가격 재진입 5분 거래 = 보유 300초(36일 아님) · 진입 시각 추정 표식",
      a and a["holdS"] == 300 and a["entryTs"] == ms(10) / 1000 and a.get("entryEst") is True and a["entryPx"] == 1.0, a)
B_SP3 = B_SP[:4] + [bill(1015, 2, 5, 1.05, 0.25, ms(10, 5)), bill(1016, 2, 5, 1.05, 0.25, ms(10, 10))]
r = asm([ev("okx", "REALIZED", 0.25, ms(10, 5), "AAA-USDT-SWAP", "ok:1015:p"), ev("okx", "REALIZED", 0.25, ms(10, 10), "AAA-USDT-SWAP", "ok:1016:p")], okpx(B_SP3))
a, b = at(r, ms(10, 5)), at(r, ms(10, 10))
check("[누락·같은 가격] 추정 포지션 분할 청산 두 번 = 둘 다 진입 10:00 · 진입 시각 추정 표식",
      a and b and a["entryTs"] == ms(10) / 1000 and b["entryTs"] == ms(10) / 1000 and a.get("entryEst") is True and b.get("entryEst") is True, (a, b))
B_SP2 = B_SP + [bill(1006, 1, 3, 1.0, 0, ms(12)), bill(1007, 2, 3, 1.1, 0.3, ms(12, 30))]
r = asm(E_SP + [ev("okx", "REALIZED", 0.3, ms(12, 30), "AAA-USDT-SWAP", "ok:1007:p")], okpx(B_SP2))
b = at(r, ms(12, 30))
check("[누락·같은 가격] 다시 세운 뒤 다음 왕복 = 진입 12:00 · 보유 30분 · 추정 표식 없음", b and b["holdS"] == 1800 and "entryEst" not in b, b)
B_LH = [bill(1101, 1, 100, 1.0, 0, ms(9, d=-40)), bill(1102, 2, 100, 1.2, 20, ms(9))]
r = asm([ev("okx", "REALIZED", 20.0, ms(9), "AAA-USDT-SWAP", "ok:1102:p")], okpx(B_LH))
a = at(r, ms(9))
check("[누락·같은 가격] 진짜 40일 보유 뒤 한 번에 청산 = 40일 그대로 · 추정 표식 없음", a and a["holdS"] == 40 * 86400 and "entryEst" not in a, a)
B_LH2 = [bill(1201, 1, 100, 1.0, 0, ms(9, d=-40)), bill(1202, 2, 30, 1.1, 3, ms(9, d=-1)), bill(1203, 2, 70, 1.2, 14, ms(9))]
r = asm([ev("okx", "REALIZED", 14.0, ms(9), "AAA-USDT-SWAP", "ok:1203:p")], okpx(B_LH2))
a = at(r, ms(9))
check("[누락·같은 가격] 40일 보유 · 하루 전 일부 청산 · 그날 나머지 청산 = 40일 그대로", a and a["holdS"] == 40 * 86400 and "entryEst" not in a, a)
B_LH3 = [bill(1301, 1, 100, 1.0, 0, ms(9, d=-30)), bill(1302, 1, 10, 1.0, 0, ms(9, d=-25)), bill(1303, 2, 10, 1.1, 1, ms(9))]
r = asm([ev("okx", "REALIZED", 1.0, ms(9), "AAA-USDT-SWAP", "ok:1303:p")], okpx(B_LH3))
a = at(r, ms(9))
check("[누락·같은 가격] 보유 중 7일 안 된 공백 뒤 추가 진입 · 일부 청산 = 30일 전 진입 그대로", a and a["entryTs"] == ms(9, d=-30) / 1000 and "entryEst" not in a, a)
B_LH4 = [bill(1401, 1, 10, 1.0, 0, ms(9, d=-30)), bill(1402, 1, 10, 1.0, 0, ms(8)), bill(1403, 2, 15, 1.1, 1.5, ms(9))]
r = asm([ev("okx", "REALIZED", 1.5, ms(9), "AAA-USDT-SWAP", "ok:1403:p")], okpx(B_LH4))
a = at(r, ms(9))
check("[누락·같은 가격] 재진입 묶음이 청산을 못 덮음 = 다시 세우지 않음(30일 전 진입)", a and a["entryTs"] == ms(9, d=-30) / 1000 and "entryEst" not in a, a)

T5 = [bnt(30, "BUY", "LONG", 100, 1, 0, ms(8)), bnt(31, "SELL", "SHORT", 100, 1, 0, ms(8, 30)), bnt(32, "SELL", "LONG", 100, 1, 0, ms(9)),
      bnt(33, "BUY", "SHORT", 90, 1, 10, ms(10)), bnt(34, "BUY", "LONG", 100, 1, 0, ms(11)), bnt(35, "SELL", "LONG", 110, 1, 10, ms(12))]
r = asm([ev("binance", "REALIZED", 10.0, ms(10), "AAAUSDT", "bn:33:R:1"), ev("binance", "REALIZED", 10.0, ms(12), "AAAUSDT", "bn:35:R:1")], bnpx(T5))
a, b = at(r, ms(10)), at(r, ms(12))
check("[헤지] 숏 청산 = 진입 08:30(롱과 따로)", a and a["side"] == "SHORT" and a["entryTs"] == ms(8, 30) / 1000, a)
check("[헤지] 손익 0 롱 청산 뒤 다시 연 롱 = 진입 11:00(08:00 아님)", b and b["side"] == "LONG" and b["entryTs"] == ms(11) / 1000, b)
rw = F.rows_binance([bnt(32, "SELL", "LONG", 100, 1, 0, ms(9))])
check("[헤지] 손익 0 이어도 헤지 모드 매도(롱) = 청산 행", rw and rw[0]["role"] == "close" and rw[0]["side"] == "LONG" and rw[0]["pm"] == "hedge", rw)

WANT = [("1", "0", "open", "LONG"), ("1", "5", "close", "SHORT"), ("2", "0", "open", "SHORT"), ("2", "5", "close", "LONG"),
        ("3", "0", "open", "LONG"), ("4", "0", "open", "SHORT"), ("5", "5", "close", "LONG"), ("6", "5", "close", "SHORT"),
        ("100", "-5", "close", "LONG"), ("101", "-5", "close", "SHORT"), ("102", "-5", "close", "SHORT"), ("103", "-5", "close", "LONG"),
        ("104", "-5", "close", "LONG"), ("105", "-5", "close", "SHORT"), ("106", "-5", "close", "SHORT"), ("107", "-5", "close", "LONG"),
        ("125", "5", "close", "LONG"), ("126", "5", "close", "SHORT"), ("127", "5", "close", "SHORT"), ("128", "5", "close", "LONG"),
        ("204", "0", "open", "LONG"), ("205", "5", "close", "LONG"), ("206", "0", "open", "LONG"), ("209", "5", "close", "SHORT")]
got, bad = {}, []
for i, (st, pnl, role, side) in enumerate(WANT):
    rr = F.rows_okx([bill(500 + i, st, 1, 10, pnl, ms(9), typ="9" if st in ("125", "126", "127", "128") else "5" if st.startswith("10") else "2")])
    if not rr or rr[0]["role"] != role or rr[0]["side"] != side:
        bad.append((st, pnl, rr))
check("[OKX] subType → 역할·방향(1·2 손익으로 · 3~6 · 강제청산 100~107 · ADL 125~128 · 블록 204~209)", not bad, bad)
liqf = {st: bool((F.rows_okx([bill(600, st, 1, 10, -5, ms(9), typ="5")]) or [{}])[0].get("liq")) for st in ("102", "107", "125")}
check("[OKX] 강제청산(102·107) = 강제청산 표시 · ADL(125) = 표시 안 함", liqf == {"102": True, "107": True, "125": False}, liqf)
none = [st for st in ("110", "111", "173", "174", "16", "11", "12") if F.rows_okx([bill(700, st, 1, 10, 5, ms(9), typ="8")])]
check("[OKX] 청산 이체·펀딩·이체 subType = 행 없음", not none, none)
check("[OKX] 1·2 는 거래(type 2)일 때만 · 블록 204 는 종류 무관",
      F.rows_okx([bill(800, "1", 1, 10, 0, ms(9), typ="1")]) == [] and len(F.rows_okx([bill(801, "204", 1, 10, 0, ms(9), typ="")])) == 1, "")
liqn = F.rows_okx([bill(900, "103", 1, 10, -5, ms(9), typ="5")])
check("[OKX] 강제청산·ADL 행 = 역할·수량 확정(pm hedge — 반전으로 가르지 않음) · uid = 정산 uid", liqn and liqn[0]["pm"] == "hedge" and liqn[0]["uid"] == "ok:900:p", liqn)

def by_close(oid, t, pnl, size="100", ent="2.0", ext="2.1"):
    return {"symbol": "BBBUSDT", "side": "Sell", "orderId": oid, "updatedTime": str(t), "closedSize": size, "avgEntryPrice": ent,
            "avgExitPrice": ext, "closedPnl": str(pnl), "openFee": "0.1", "closeFee": "0.1", "leverage": "2", "execType": "Trade"}


def by_open(eid, t, qty="100", px="2.0"):
    return {"symbol": "BBBUSDT", "side": "Buy", "execId": eid, "orderId": "x" + eid, "execTime": str(t), "execQty": qty, "closedSize": "0",
            "execPrice": px, "execType": "Trade"}


def bypx(closes, opens):
    return {"bybit": {"v": 1, "rows": F.rows_bybit(closes) + F.rows_bybit_exec(opens), "cursor": {"bf_done": True}, "ts": NOW // 1000}}


T_IN, T_OUT = ms(9, 50), ms(10, 5)
PNL = round(10 - 0.2 + 1.5, 10)
r = asm([ev("bybit", "REALIZED", PNL, T_OUT, "BBBUSDT", f"bb:c1:{T_OUT}")], bypx([by_close("c1", T_OUT, PNL)], [by_open("e1", T_IN)]))
a = at(r, T_OUT)
check("[펀딩] 진입 시각 앎 · 정시 지남 · 상한 안 = 거래소 가격 표시 · 펀딩 몫 1.5 따로", a and a["px"] == "exchange" and a["entryPx"] == 2.0
      and a["exitPx"] == 2.1 and abs(a.get("fundIncl", 0) - 1.5) < 1e-6 and a["pnl"] == PNL and a["entryTs"] == T_IN / 1000, a)
r = asm([ev("bybit", "REALIZED", PNL, T_OUT, "BBBUSDT", f"bb:c1:{T_OUT}")], bypx([by_close("c1", T_OUT, PNL)], []))
a = at(r, T_OUT)
check("[펀딩] 진입 시각 모름 · 차이가 펀딩 한 번 상한(3%) 안 = 거래소 가격 표시 · 펀딩 몫 1.5 · '펀딩 포함 가능'",
      a and a["px"] == "exchange" and a["entryPx"] == 2.0 and abs(a.get("fundIncl", 0) - 1.5) < 1e-6 and a.get("fundMaybe") is True and a["entryTs"] is None, a)
r = asm([ev("bybit", "REALIZED", PNL, T_OUT, "BBBUSDT", f"bb:c1:{T_OUT}")], bypx([by_close("c1", T_OUT, PNL)], [by_open("e1", T_IN)]))
a = at(r, T_OUT)
check("[펀딩] 진입 시각 앎 = '펀딩 포함 가능' 표식 없음(정시 수로 확인)", a and a["px"] == "exchange" and "fundMaybe" not in a, a)
T_OUT2 = ms(9, 58)
r = asm([ev("bybit", "REALIZED", PNL, T_OUT2, "BBBUSDT", f"bb:c2:{T_OUT2}")], bypx([by_close("c2", T_OUT2, PNL)], [by_open("e1", T_IN)]))
a = at(r, T_OUT2)
check("[펀딩] 정시를 안 지남(펀딩 없었음) = 버림", a and a["px"] == "none", a)
BIG = round(10 - 0.2 + 20, 10)
r = asm([ev("bybit", "REALIZED", BIG, T_OUT, "BBBUSDT", f"bb:c3:{T_OUT}")], bypx([by_close("c3", T_OUT, BIG)], [by_open("e1", T_IN)]))
a = at(r, T_OUT)
check("[펀딩] 차이가 펀딩 상한을 넘음 = 버림", a and a["px"] == "none", a)
r = asm([ev("bybit", "REALIZED", BIG, T_OUT, "BBBUSDT", f"bb:c3:{T_OUT}")], bypx([by_close("c3", T_OUT, BIG)], []))
a = at(r, T_OUT)
check("[펀딩] 진입 시각 모름 · 차이가 펀딩 한 번 상한을 넘음 = 종전처럼 버림('거래소 값끼리 안 맞음')",
      a and a["px"] == "none" and a["why"].startswith("거래소 값끼리") and "fundIncl" not in a, a)
BY_AGG = {"symbol": "BBBUSDT", "side": "Sell", "orderId": "c9", "updatedTime": str(ms(10)), "closedSize": "2", "avgEntryPrice": "97.5",
          "avgExitPrice": "110", "closedPnl": "25", "openFee": "0", "closeFee": "0", "leverage": "2", "execType": "Trade"}
r = asm([ev("bybit", "REALIZED", 25.0, ms(10), "BBBUSDT", f"bb:c9:{ms(10)}")],
        bypx([BY_AGG], [by_open("e8", ms(8), qty="2", px="100"), by_open("e9", ms(9, 30), qty="1", px="90")]))
a = at(r, ms(10))
check("[펀딩·집계] 바이빗 청산 주문 사이 추가 진입 = 진입 시각 08:00 유지 · 거래소 가격", a and a["entryTs"] == ms(8) / 1000 and a["px"] == "exchange"
      and a["entryPx"] == 97.5, a)
OKP = round(10 - 0.2, 10)
r = asm([ev("bybit", "REALIZED", OKP, T_OUT2, "BBBUSDT", f"bb:c4:{T_OUT2}")], bypx([by_close("c4", T_OUT2, OKP)], [by_open("e1", T_IN)]))
a = at(r, T_OUT2)
check("[펀딩] 펀딩 없이 맞는 정산 = 가격 표시 · 펀딩 몫 칸 없음", a and a["px"] == "exchange" and "fundIncl" not in a, a)
T_LH = ms(9, d=-71)
r = asm([ev("bybit", "REALIZED", OKP, T_OUT2, "BBBUSDT", f"bb:c5:{T_OUT2}")], bypx([by_close("c5", T_OUT2, OKP)], [by_open("e5", T_LH)]))
a = at(r, T_OUT2)
check("[누락·같은 가격] 바이빗 71일 보유 뒤 청산 = 진입 71일 전 그대로 · 추정 표식 없음", a and a["entryTs"] == T_LH / 1000 and "entryEst" not in a, a)

E_ALL = (E1 + [ev("binance", "FEE", -0.3, ms(9), "AAAUSDT", "bn:2:F:1"), ev("binance", "FUNDING", 0.07, ms(9, 1), "AAAUSDT", "bn:9:U:1")]
         + [x for x in E4 if x[0] == ISO] + [ev("okx", "FEE", -0.2, ms(10, 5), "AAA-USDT-SWAP", "ok:104:f")]
         + [ev("bybit", "REALIZED", PNL, T_OUT, "BBBUSDT", f"bb:c1:{T_OUT}")])
E_ALL.sort(key=lambda x: x[1])
PX_ALL = dict(bnpx(T1), **okpx([B_OLD, B_UNK] + B_NEW), **bypx([by_close("c1", T_OUT, PNL)], [by_open("e1", T_IN)]))
r1, r0 = asm(E_ALL, PX_ALL), asm(E_ALL, {})
check("[불변] 그날 합·원화·종류별 = 옆 파일 있든 없든 같음", r1["total"] == r0["total"] and r1["exKinds"] == r0["exKinds"], (r1["total"], r0["total"]))
su, sk = 0.0, 0.0
for x in E_ALL:
    su += x[2]
    sk += x[3]
check("[불변] 그날 합 = 이벤트 합(같은 순서)", r1["total"]["usd"] == round(su, 2) and r1["total"]["krw"] == round(sk), (r1["total"], su))
c1 = {c["coin"]: c for c in r1["coins"]}
okc = all(c.get("exStats") for c in r1["coins"])
for c in r1["coins"]:
    es = c.get("exStats") or {}
    okc = okc and abs(sum(x["usd"] for x in es.values()) - c["usd"]) < 1e-6 and sum(x["closes"] for x in es.values()) == c["closes"] \
        and sum(x["priced"]["n"] for x in es.values()) == c["priced"]["n"] and sum(x["wins"] for x in es.values()) == c["wins"]
check("[불변] 거래소별 몫(exStats) 합 = 종목 칸(금액·청산·가격·승)", okc and set(c1["AAA"].get("exStats") or ()) == {"binance", "okx"},
      {k: c.get("exStats") for k, c in c1.items()})
check("[불변] exStats 건수 = 그 거래소 청산 수(tradesTotalEx 와 같음)",
      all(((c.get("exStats") or {}).get(ex) or {}).get("closes") == n for c in r1["coins"] for ex, n in c["tradesTotalEx"].items()), "")

check("rows_* = 형식 틀린 줄 버림(예외 없음)", F.rows_okx([None, 1, {"subType": "1"}]) == [] and F.rows_binance([{"side": "X"}, "a"]) == []
      and F.rows_bybit([{}]) == [] and F.rows_bybit_exec([{"execType": "Funding"}]) == [], "")
check("빈 날 = empty", asm([], {}).get("empty") is True, "")

T.finish()
