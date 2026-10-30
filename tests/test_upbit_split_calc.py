#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _costsim as S  # noqa: E402

import time  # noqa: E402
from decimal import Decimal as D  # noqa: E402

import acct_norm  # noqa: E402

chk = T.chk
DAY = 86400
T0 = (S.NOW // DAY - 20) * DAY + 3 * 3600


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(t))


def order(uid, side, fills, fee="0"):
    tr = [{"uuid": f"{uid}-t{i}", "market": "KRW-ETH", "side": side, "created_at": iso(t), "volume": q, "funds": str(D(q) * D(p)), "price": p}
          for i, (t, q, p) in enumerate(fills)]
    return {"uuid": uid, "market": "KRW-ETH", "side": side, "state": "done", "ord_type": "limit",
            "executed_volume": str(sum(D(q) for _t, q, _p in fills)), "executed_funds": str(sum(D(x["funds"]) for x in tr)),
            "paid_fee": fee, "created_at": iso(min(t for t, _q, _p in fills)), "trades": tr, "trades_count": len(tr)}


def run(*orders):
    S.reset()
    S.FX[0] = 1000.0
    S.fills_upbit(*orders)
    f, G, rr = S.build()
    eth = [g for g in G.values() if g.get("sym") == "ETH"]
    f["_rbd_in"] = dict(rr.books.realized_by_date)
    return f, (eth[0] if eth else None)


def day(t):
    return acct_norm.iso_day(t)


def rbd(f):
    return {k: round(float(v), 9) for k, v in (f.get("_rbd_in") or {}).items() if abs(float(v)) > 1e-9}


def sells(f):
    return sorted((r.get("date") or r.get("d") or "", round(float(r.get("_acq", r.get("acq")) or 0), 6), round(float(r.get("_fee", r.get("fee")) or 0), 6),
                   round(float(r.get("_disp", r.get("disp")) or 0), 6)) for r in (f.get("_taxRowsAll") or []))


t0, t1, t2, t3 = T0, T0 + DAY, T0 + 2 * DAY, T0 + 3 * DAY
X1, X3 = D(150) - D(50), D(150) - (D(50) + D(200)) / D("1.5") * D("0.5")
o_init = order("init", "bid", [(t0, "1", "100000")])
o_sell = order("sell", "ask", [(t1, "0.5", "300000"), (t3, "0.5", "300000")])
o_mid = order("mid", "bid", [(t2, "1", "200000")])
f1, g1 = run(o_init, o_sell, o_mid)
r1 = rbd(f1)
chk(r1 == {day(t1): round(float(X1), 9), day(t3): round(float(X3), 9)}, "W1 내부 날짜별 실현 = t1 $100 · t3 $66.666666667(독립 산술 · 반올림 전)", r1)
chk(f1.get("realizedByDate") == {day(t1): 100.0, day(t3): 66.67} and round(sum(f1["realizedByDate"].values()), 2) == 166.67
    and round(float(sum((D(str(v)) for v in (f1.get("realizedKrwByDate") or {}).values()), D(0)))) == 166667,
    "W1 화면 값 = 날짜별 $100.00 · $66.67 · 합 $166.67 · 원화 166,667(표시 반올림 · 내부엔 안 넣음)", (f1.get("realizedByDate"), f1.get("realizedKrwByDate")))
q1 = g1["qty_known"] + g1["qty_unknown"]
chk(q1 == 1 and abs(g1["cost"] - (D(50) + D(200)) / D("1.5")) < D("1e-20") and abs(float(g1["cost"]) / float(q1) - 166.666667) < 1e-6,
    "W1 남은 1 ETH(정확) · 원가 = 평단 ≈ $166.666667", (q1, g1["cost"]))
s1 = sells(f1)
chk([round(x[1], 4) for x in s1] == [50.0, 83.3333], "W1 매도 원가 명세 t1 $50 · t3 $83.333…", s1)
o_a = order("sa", "ask", [(t1, "0.5", "300000")])
o_b = order("sb", "ask", [(t3, "0.5", "300000")])
f2, g2 = run(o_mid, o_b, o_init, o_a)
chk(rbd(f2) == r1 and abs(float(g2["cost"]) - float(g1["cost"])) < 1e-9 and sells(f2) == s1,
    "W2 같은 체결을 개별 주문으로(수집 순서도 바꿈) = 날짜별 실현·남은 원가·명세 같음", (rbd(f2), g2["cost"]))
f2b, g2b = run(o_mid, dict(o_sell, trades=list(reversed(o_sell["trades"]))), o_init)
chk(rbd(f2b) == r1 and abs(float(g2b["cost"]) - float(g1["cost"])) < 1e-9, "W2 체결 역순 · 수집 순서 바꿈 = 같음", rbd(f2b))
f3, g3 = run(order("buy2", "bid", [(t0, "1", "100000"), (t2, "1", "300000")]), order("s3", "ask", [(t1, "0.5", "200000")]))
chk(rbd(f3) == {day(t1): 50.0} and abs(g3["cost"] - 350) < D("1e-20") and g3["qty_known"] + g3["qty_unknown"] == D("1.5"),
    "W3 분할 매수 사이 매도 = t1 실현 $50(첫 체결 원가) · 남은 1.5 ETH 원가 $350", (rbd(f3), g3["cost"]))
f4, g4 = run(o_init, order("s4", "ask", [(t1, "0.5", "200000"), (t3, "1.5", "300000")]), o_mid)
X4 = D(450) - (D(50) + D(200))
chk(rbd(f4) == {day(t1): 50.0, day(t3): round(float(X4), 9)} and (g4 is None or g4["qty_known"] + g4["qty_unknown"] == 0),
    "W4 전량 청산 = 날짜별 t1 $50 · t3 $200 · 남은 0(합만 같은 옛 결과 = t3 하루 $250 와 다름)", rbd(f4))
m = (S.NOW // DAY - 10) * DAY + 15 * 3600
f5, _g5 = run(order("b5", "bid", [(m - DAY, "1", "100000")]), order("s5", "ask", [(m - 1, "0.5", "200000"), (m, "0.5", "300000")]))
chk(rbd(f5) == {day(m - 1): 50.0, day(m): 100.0} and day(m - 1) != day(m), "W5 KST 23:59:59 · 00:00:00 체결 = 두 날짜에 실현", rbd(f5))
ye = 1767193200
grp, _w = acct_norm.fill_groups(order("ye", "ask", [(ye - 1, "0.5", "1"), (ye, "0.5", "1")]))
chk([acct_norm.iso_day(g["ts"]) for g in grp] == ["2025-12-31", "2026-01-01"], "W5 연도 경계 = 묶음 날짜 키 2025-12-31 · 2026-01-01", grp)
f6, _g6 = run(order("b6", "bid", [(t0, "1", "100000")], fee="50"), order("s6", "ask", [(t1, "0.5", "300000"), (t2, "0.5", "300000")], fee="150"))
s6 = sells(f6)
tg = f6.get("taxGas") or {}
chk(round(sum(x[2] for x in s6), 6) == 0.15 and round(sum(x[3] for x in s6), 6) == 300.0,
    "W6 분할 매도 명세 수수료 합 = paid_fee $0.15 · 양도가액 합 = 수수료 전 체결액 $300", s6)
chk(abs(sum(rbd(f6).values()) - S.tax_sum(f6)) < 1e-6 and abs(sum(rbd(f6).values()) - float(D(300) - D("0.15") - D("100.05"))) < 1e-9,
    "W6 실현 = 명세 합 = 300 − 0.15 − 100.05(매수 수수료 원가 포함 · 이중 차감 없음)", (rbd(f6), S.tax_sum(f6)))
chk(round(float(tg.get("exFee") or 0), 2) == 0.2, "W6 수수료 패널(업비트 체결 수수료) = 매수 $0.05 + 매도 $0.15", tg)
o7 = order("u7", "bid", [(t0, "0.5", "2000"), (t1, "0.5", "2000")], fee="1")
for tr7 in o7["trades"]:
    tr7["market"] = "USDT-ETH"
o7["market"] = "USDT-ETH"
f7, g7 = run(o7)
tg7 = f7.get("taxGas") or {}
chk(round(float(tg7.get("exFee") or 0), 6) == 1.0 and g7 is not None and g7["qty_known"] + g7["qty_unknown"] == 1,
    "W7 USDT 마켓 두 날 체결 = 한 주문 두 레그(기준·쿼트) 그대로 · 수수료 패널 $1(쿼트 레그에 또 안 셈)", tg7)
T.finish()
