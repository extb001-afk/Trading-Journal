#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _costsim as S  # noqa: E402

from decimal import Decimal as D  # noqa: E402

import accounting_basis as B  # noqa: E402
import accounting_krw as AK  # noqa: E402
import accounting_util as AU  # noqa: E402
from view_common import EPS  # noqa: E402

chk = T.chk
DAY = 86400


def run(sym, dec, sell_q):
    c = S.reset(px={"USDT": 1., "USDC": 1., "ETH": 2000., sym: 150.})
    ch = S.Ch(c)
    usdc = ch.tok("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6)
    tk = ch.tok("base", "0x" + ("d1" if dec == 18 else "d2") * 20, sym, dec)
    t0 = S.NOW - 20 * DAY
    ch.tx("base", "fund_" + sym, t0, [(usdc, 1000, "acq", 1000)], "PROGRAM_IN")
    ch.tx("base", "buy_" + sym, t0 + DAY, [(usdc, -100, "disp", 100), (tk, 1, "acq", 100)], "SWAP")
    ch.tx("base", "sell_" + sym, t0 + 2 * DAY, [(tk, -sell_q, "disp", 150), (usdc, 150, "acq", 150)], "SWAP")
    f, G, _rr = S.build()
    g = [x for x in G.values() if x["sym"] == sym]
    return f, G, g


f1, G1, g1 = run("TKD", 18, D("0.9999999999"))
chk(len(g1) == 1, "D1 그룹 하나", [x["sym"] for x in G1.values()])
if g1:
    gd = g1[0]
    chk(D(0) <= gd["qty_known"] <= EPS, "D1 남은 수량 ≤ EPS(먼지)", str(gd["qty_known"]))
    chk(abs(gd["cost"]) < D("0.000001"), "D1 먼지에 남은 원가 < $0.000001(비례 소진)", str(gd["cost"]))
    chk(abs(float(gd["realized"]) - 50.0) < 0.001, "D1 실현 ≈ +$50(원가 거의 전부 실현)", str(gd["realized"]))
    chk(gd["qty_unknown"] == 0, "D1 원가 미상 0", str(gd["qty_unknown"]))
r1 = S.realized(f1)
chk(abs(S.cost_end(G1) - r1 - 1000) < 0.01, "D1 Σ원가(끝) − Σ실현 = 초기 원가 $1,000(알려진 원가는 사라지지 않음)", (S.cost_end(G1), r1))
chk(int(((f1.get("_diag") or {}).get("inv_cost_no_qty")) or 0) == 0, "D1 빌드 진단 inv_cost_no_qty = 0", (f1.get("_diag") or {}).get("inv_cost_no_qty"))

f2, G2, g2 = run("TKS", 6, D("0.999999"))
chk(len(g2) == 1, "D2 그룹 하나", [x["sym"] for x in G2.values()])
if g2:
    gs = g2[0]
    chk(gs["qty_known"] == D("0.000001"), "D2 남은 수량 = 0.000001(> EPS · 그대로)", str(gs["qty_known"]))
    w = B.CostBasis().wac(gs)
    chk(abs(w - D(100)) < D("0.0000001"), "D2 남은 먼지 평단 = $100(부풀거나 0 되지 않음)", str(w))
    chk(abs(float(gs["realized"]) - (150 - 100 * 0.999999)) < 0.001, "D2 실현 = 150 − 100 × 0.999999", str(gs["realized"]))

cb = B.CostBasis()
gk = cb.new_group(9001, "KRW", False, True)
cb.acquire(gk, D(1000), D("0.70"))
cb.release(gk, D("999.5"), cb.wac(gk) * D("999.5"), D(0))
chk(gk["qty_known"] == D("0.5") and gk["qty_known"] > EPS, "D3 원화 0.5 잔량 > EPS(먼지 아님)", str(gk["qty_known"]))
chk(cb.wac(gk) == D("0.70") / D(1000), "D3 원화 잔량 평단 = 원래 평단(비례 소진)", str(cb.wac(gk)))

iv = AU.Invariants()
iv.check(1, "TKA", D(0), D("0.0000000001"), D("0.00000001"))
chk(iv.n["cost_no_qty"] == 0, "D4 비례 잔여(≈ $1e-8) = 잡지 않음", iv.n)
iv.check(2, "TKB", D(0), D(0), D("5"))
chk(iv.n["cost_no_qty"] == 1, "D4 수량 0 · 원가 $5 = cost_no_qty 1", iv.n)

def krw_chain(first_sell_q):
    c5 = S.reset(px={"USDT": 1., "USDC": 1., "ETH": 2000., "TKF": 150.})
    ch5 = S.Ch(c5)
    usdc5 = ch5.tok("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6)
    tk5 = ch5.tok("base", "0x" + "d5" * 20, "TKF", 18)
    t5 = S.NOW // 60 * 60 - 20 * DAY
    S.FXF[0] = lambda ts: 1200. if ts < t5 + 5 * DAY else 1600.
    ch5.tx("base", "dust_fx_fund", t5, [(usdc5, 1000, "acq", 1000)], "PROGRAM_IN")
    for i5, (q5, usd5, sell5) in enumerate(((D(1), D(100), False), (first_sell_q, D(150), True), (D(1), D(100), False),
                                            (D("0.5"), D(75), True), (D(1), D(100), False), (D("0.75"), D("112.5"), True)), 1):
        legs5 = ([(tk5, -q5, "disp", usd5), (usdc5, usd5, "acq", usd5)] if sell5 else [(usdc5, -usd5, "disp", usd5), (tk5, q5, "acq", usd5)])
        ch5.tx("base", "dust_fx_%d" % i5, t5 + i5 * DAY, legs5, "SWAP")
    f5, _G5, _rr5 = S.build()
    return sorted((r for r in f5["_taxRowsAll"] if r.get("sym") == "TKF"), key=lambda r: r["sold"])


for lab5, q5 in (("먼지", D("0.9999999999")), ("대조(전량)", D(1))):
    tax5 = krw_chain(q5)
    chk(len(tax5) == 3, f"D5 {lab5} 매도 세 건", len(tax5))
    if len(tax5) == 3:
        akr5 = tax5[-1].get("_akr")
        chk(akr5 is not None and abs(akr5 - 110000.) < 0.01,
            f"D5 {lab5} 마지막 원화 취득가액 = 남은 0.5개 60,000 + 새 1개 160,000 의 절반 = 110,000원(누적 평균 105,000 금지)", akr5)
        chk(abs(tax5[1].get("_akr") - 60000.) < 0.01, f"D5 {lab5} 가운데 매도 원화 취득가액 60,000원", tax5[1].get("_akr"))
S.FXF[0] = None

def pool(gcost, stable=False, fcost=D(100), fkrw=D(120000)):
    kp = AK.KrwPools(None, None, None, None)
    kp.krw_mix, kp.fs_last, kp.krw_flow, kp.krw_stl = [D(0)], [D(0)], [None], [None]
    fl = {"cost": fcost, "cost_krw": fkrw}
    g = {"cur": fl, "cost": gcost, "is_stable": stable}
    return kp, g, fl


kp6, g6, fl6 = pool(D(100) + D("0.00000001"))
tk6 = kp6.consume_krw(g6, D(50))
chk(tk6 is not None and abs(tk6 - D(60000)) < D("0.01") and fl6["cost"] - fl6["_cost_used"] == g6["cost"] - D(50),
    "D6 잔여 $1e-8 = 흡수 · 로트 소진 60,000원 · 풀 남은 원가 = 그룹 남은 원가", (tk6, fl6))
kpb, gb, flb = pool(D(1) + D("0.00000001"), fcost=D(1), fkrw=D(1200))
okb = True
for _i in range(3):
    tkb = kpb.consume_krw(gb, gb["cost"] / 2)
    okb = okb and tkb is not None
    gb["cost"] -= gb["cost"] / 2
chk(okb and flb["_cost_krw_used"] <= flb["cost_krw"], "D6 작은 그룹($1) · 부분 소진 세 번 = 계속 로트 소진 · 풀 초과 없음", flb)
kp7, g7, fl7 = pool(D(100) + D("0.00001"))
chk(kp7.consume_krw(g7, D(50)) is None and "_cost_used" not in fl7, "D6 잔여 $1e-5(사이클 밖 승계) = None(종전 환산 · 풀 무변)", fl7)
kp8, g8, fl8 = pool(D(100) + D("0.00000001"), stable=True)
tk8 = kp8.consume_krw(g8, D(50))
chk(tk8 is not None and kp8.krw_mix[0] > 0 and fl8["_cost_used"] < D(50), "D6 스테이블 = 종전 섞임 분할(krw_mix > 0)", (tk8, kp8.krw_mix, fl8))
kp9, g9, fl9 = pool(D("2e-8"), fcost=D("1e-8"), fkrw=D("0.000012"))
neg9 = []
c9 = D("1.5e-8")
for i9 in range(27):
    kp9.consume_krw(g9, c9)
    g9["cost"] -= c9
    neg9.append(fl9["cost_krw"] - fl9.get("_cost_krw_used", D(0)) < -D("1e-18") or fl9["cost"] - fl9.get("_cost_used", D(0)) < -D("1e-18"))
    g9["cost"] += D("7e-9")
    fl9["cost"] += D("7e-9")
    fl9["cost_krw"] += D("7e-9") * (D(1600) if i9 % 2 else D(1200))
    c9 = D("7e-9")
krw9 = fl9["cost_krw"] - fl9.get("_cost_krw_used", D(0))
chk(not any(neg9) and D(0) <= krw9 <= fl9["cost_krw"], "D6 풀 ≈ 잔여 크기 · 재취득·소진 26번 = 원화·USD 풀 음수 0 · 증폭 0", (neg9.count(True), str(krw9)))
kpa, ga, fla = pool(D(100) + D("0.00000001"))
tka = kpa.consume_krw(ga, ga["cost"])
chk(tka is not None and tka / ga["cost"] == D(1200) and kpa.krw_mix[0] == 0, "D6 잔여 든 전량 이동 = 반환 원화 ÷ 소진 USD = 풀 환율 1,200 그대로 · krw_mix 0", (tka, kpa.krw_mix))
kpc, gc, flc = pool(D(200))
skipc = kpc.consume_krw(gc, D("99.9999995"))
gc["cost"] -= D("99.9999995")
cc = gc["cost"]
kpc.krw_last = [kpc.consume_krw(gc, cc)]
kpc.fxb = type("FxStub", (), {"rate_at": lambda self, ts: 1600.})()
movedc = kpc.krw_took(cc, 0)
chk(skipc is None and kpc.krw_last[0] is None and "_cost_used" not in flc and "_cost_krw_used" not in flc
    and abs(movedc - D("160000.0008")) < D("0.000001") and kpc.krw_rec(cc) == (D(0), D(0)),
    "D6 None 소진 뒤 낡은 풀이 우연히 $1e-6 안 = 흡수 안 함(종전처럼 출발 환율 · 풀 무변)", (skipc, kpc.krw_last, flc, movedc))
chk(AK.POOL_DUST_USD == D("0.000001"), "D6 흡수 상한 = $1e-6", AK.POOL_DUST_USD)

T.finish()
