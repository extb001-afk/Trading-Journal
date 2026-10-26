#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _costsim as S  # noqa: E402

import random  # noqa: E402
from decimal import Decimal as D, ROUND_HALF_EVEN  # noqa: E402

import calcguard  # noqa: E402
import view_tax  # noqa: E402

chk = T.chk
DAY = 86400
KST9 = __import__("datetime").timezone(__import__("datetime").timedelta(hours=9))
N_UP, N_CH = 500, 500


def _iso(ts):
    return __import__("datetime").datetime.fromtimestamp(ts, KST9).isoformat()


def fx(ts):
    return 1300.0 + ((ts // 3600) % 97) * 1.37 + 0.123


def gen(seed):
    rnd = random.Random(seed)
    t0 = S.NOW - 50 * DAY
    recs, up_lots, ch_lots, up_sells, ch_sells = [], [], [], [], []
    t = t0 + 3600
    for i in range(N_UP):
        t += rnd.randint(1200, 3600)
        vol = D(rnd.randint(100000, 5000000)) / D(10 ** 8)
        px = D(2700000 + rnd.randint(-200000, 200000))
        funds = vol * px
        fee = (funds * D("0.0005")).quantize(D("0.00000001"))
        recs.append(("up", {"uuid": f"ub{i}", "market": "KRW-ETH", "side": "bid", "executed_volume": str(vol), "executed_funds": str(funds),
                            "paid_fee": str(fee), "created_at": _iso(t), "state": "done", "ord_type": "limit", "price": str(px)}))
        up_lots.append((t, vol, funds, fee))
    tc = t0 + 1800
    recs.append(("ch", ("fund", tc, "usdc", D(10 ** 7), None)))
    for i in range(N_CH):
        tc += rnd.randint(1200, 3600)
        q = D(rnd.randint(10 ** 18, 50 * 10 ** 18)) / D(10 ** 18)
        usd = (q * D(str(rnd.uniform(0.9, 1.3)))).quantize(D("0.000001"))
        recs.append(("ch", (f"b{i}", tc, "buy", q, usd)))
        ch_lots.append((tc, q, usd))
    ts = max(t, tc) + DAY
    upq = sum((x[1] for x in up_lots), D(0))
    chq = sum((x[1] for x in ch_lots), D(0))
    left_u, left_c = upq, chq
    for j in range(20):
        ts += rnd.randint(3 * 3600, DAY)
        qu = left_u if j == 19 else (upq / 25 * D(str(rnd.uniform(0.5, 1.5)))).quantize(D("0.00000001"))
        pxs = D(2800000 + rnd.randint(-150000, 150000))
        fu = qu * pxs
        feu = (fu * D("0.0005")).quantize(D("0.00000001"))
        recs.append(("up", {"uuid": f"ua{j}", "market": "KRW-ETH", "side": "ask", "executed_volume": str(qu), "executed_funds": str(fu),
                            "paid_fee": str(feu), "created_at": _iso(ts), "state": "done", "ord_type": "limit", "price": str(pxs)}))
        up_sells.append((ts, qu, fu, feu))
        left_u -= qu
        qc = left_c if j == 19 else (chq / 25 * D(str(rnd.uniform(0.5, 1.5)))).quantize(D("0.000000000000000001"))
        usd = (qc * D(str(rnd.uniform(1.0, 1.6)))).quantize(D("0.000001"))
        recs.append(("ch", (f"s{j}", ts + 600, "sell", qc, usd)))
        ch_sells.append((ts + 600, qc, usd))
        left_c -= qc
    tb = t0 + 600
    recs.append(("bnd", tb))
    for k in range(6):
        tb += 7200
        side = "buy" if k % 2 == 0 else "sell"
        px = format(D(2000 + 37 * k) + D("0.37"), "f")
        recs.append(("bn", S.norm_fill("binance", f"ETHUSDT:{k}", tb * 1000, "ETH", "USDT", side, px, "0.5", "-0.0" + str(17 + k), "USDT")))
    return recs, (up_lots, up_sells, ch_lots, ch_sells)


def run(seed, shuffle=None):
    recs, exp = gen(seed)
    S.reset(px={"USDT": 1., "USDC": 1., "ETH": 2000., "TKD": 1.2})
    S.FXF[0] = fx
    c = S._C[0]
    ch = S.Ch(c)
    usdc = ch.tok("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6)
    tkd = ch.tok("base", "0x" + "5d" * 20, "TKD", 18)
    if shuffle is not None:
        head, rest = recs[:1], recs[1:]
        random.Random(shuffle).shuffle(rest)
        recs = head + rest
    for kind, r in recs:
        if kind == "up":
            S.fills_upbit(r)
        elif kind == "bnd":
            S.ex("binance", deposits=[S.norm_row("binance", "fb", "USDT", "100000", 0, "fbn", "ACCEPTED", r, r)])
        elif kind == "bn":
            S.fills("binance", [r])
        else:
            tag, ts, how, q, usd = r
            if how == "usdc":
                ch.tx("base", tag, ts, [(usdc, q, "acq", None)], "PROGRAM_IN")
            elif how == "buy":
                ch.tx("base", tag, ts, [(usdc, -usd, "disp", usd), (tkd, q, "acq", usd)], "SWAP")
            else:
                ch.tx("base", tag, ts, [(tkd, -q, "disp", usd), (usdc, usd, "acq", usd)], "SWAP")
    f, G, rr = S.build()
    return f, G, rr, exp


def q0(x):
    return int(D(repr(x) if isinstance(x, float) else x).to_integral_value(ROUND_HALF_EVEN))


def shadow_wac(lots, sells, krw_of):
    pq = sum((x[1] for x in lots), D(0))
    pk = sum((krw_of(x) for x in lots), D(0))
    out = []
    for s9 in sells:
        k9 = pk * s9[1] / pq
        out.append(k9)
        pk -= k9
        pq -= s9[1]
    return out


def key9(r):
    return (str(r.get("sold") or ""), str(r.get("sym") or ""), str(r.get("ex") or ""), str(r.get("_akr")), str(r.get("_disp")))


def snap(f, rr):
    bk = rr.books
    rows = f.get("_taxRowsAll") or []
    return {"rbd": dict(bk.realized_by_date), "rkd": dict(bk.realized_krw_by_date), "sum": f.get("taxSummary"),
            "akr": sorted((key9(r), r.get("akr")) for r in rows), "out_k": f.get("realizedKrwByDate"), "out_u": f.get("realizedByDate")}


f, G, rr, exp = T.safe(run, 29) or (None, None, None, None)
chk(f is not None and rr is not None, "합성 원장 빌드(매수 1,000 · 매도 40 · 리베이트 체결)")
if f is not None and rr is not None:
    bk = rr.books
    rows = f.get("_taxRowsAll") or []
    up_lots, up_sells, ch_lots, ch_sells = exp
    rows_up = sorted((r for r in rows if r.get("sym") == "ETH" and r.get("_akm")), key=lambda r: str(r.get("sold")))
    rows_ch = sorted((r for r in rows if r.get("sym") == "TKD"), key=lambda r: str(r.get("sold")))
    rz_day = sum(float(v) for v in bk.realized_by_date.values())
    rz_cyc = sum((fl["realized"] for g in G.values() for fl in g["flows"]), D(0))
    chk(abs(D(repr(rz_day)) - rz_cyc) <= D("1e-9") * max(D(1), abs(rz_cyc)),
        "P1 USD 날짜별 실현 합(float) = 사이클 실현 합(Decimal) 상대 1e-9", {"day": rz_day, "cyc": str(rz_cyc)})
    krw_day = sum(float(v) for v in bk.realized_krw_by_date.values())
    gap, tol = view_tax.krw_sum_gap(rows, bk.realized_krw_by_date)
    chk(q0(krw_day) == q0(krw_day + gap) and abs(gap) < 0.01, "P1 원화 날짜별 실현 합 = 세금 명세 원화 실현 합(정수 같음 · 차 0.01원 미만)",
        {"day": round(krw_day, 4), "gap": gap})
    out_k = f.get("realizedKrwByDate") or {}
    chk(all(v == round(bk.realized_krw_by_date[k], 2) for k, v in out_k.items()) and q0(sum(out_k.values())) == q0(krw_day + gap),
        "P1 화면 날짜별 원화 = 장부 값 소수 둘째 자리(세션29 krw) · 그 합(원) = 명세 원화 실현 합(원)", len(out_k))
    sh_up = shadow_wac(up_lots, up_sells, lambda x: x[2] + x[3])
    sh_ch = shadow_wac(ch_lots, ch_sells, lambda x: x[2] * D(repr(fx(x[0]))))
    for nm, rs, sh in (("업비트 원화 마켓", rows_up, sh_up), ("소수 18자리 토큰", rows_ch, sh_ch)):
        d9 = [abs(D(int(r.get("akr"))) - k9) for r, k9 in zip(rs, sh)] if len(rs) == len(sh) else None
        chk(d9 is not None and max(d9) <= 1, f"P3 {nm} 명세 원화 취득가(akr) 행마다 Decimal 그림자 ±1원({len(sh)}행)",
            {"rows": len(rs), "max": str(max(d9)) if d9 else None})
        tot9 = sum((D(repr(float(r.get("_akr")))) for r in rs), D(0))
        chk(abs(tot9 - sum(sh, D(0))) < 1, f"P3 {nm} 원화 취득가 합(반올림 전) = 그림자 합 ±1원", {"diff": str(tot9 - sum(sh, D(0)))})
    tk_rz = sum((fl["realized"] for g in G.values() if g["sym"] == "TKD" for fl in g["flows"]), D(0))
    tk_ex = sum((x[2] for x in ch_sells), D(0)) - sum((x[2] for x in ch_lots), D(0))
    chk(abs(tk_rz - tk_ex) <= D("0.000001"), "P3 소수 18자리 토큰 USD 실현 = Σ매도 − Σ매수(정확)", {"rz": str(tk_rz), "ex": str(tk_ex)})
    base9 = snap(f, rr)
    for sh9 in (7, 8):
        r9 = T.safe(run, 29, sh9)
        if not r9:
            chk(False, f"P2 순서 섞음 {sh9} 빌드")
            continue
        o9 = snap(r9[0], r9[2])
        diff9 = [k for k in base9 if base9[k] != o9[k]]
        chk(not diff9, f"P2 같은 사건 다른 기장 순서(섞음 {sh9}) — 날짜별 실현·원화·세금 요약·명세 원화 취득가 똑같음", diff9)
    chk("view_tax:krw_sum" not in calcguard.snapshot(), "P4 정상 빌드 = 감시 기록 없음")
    rk9 = dict(bk.realized_krw_by_date)
    d0 = sorted(rk9)[0]
    rk9[d0] = rk9[d0] + 5.0
    g9 = view_tax.krw_sum_check(rows, rk9)
    s9 = calcguard.snapshot().get("view_tax:krw_sum") or {}
    chk(g9 is not None and round(g9) == -5 and s9.get("sus", 0) >= 1, "P4 한쪽 장부만 5원 → calcguard 의심(노랑) 기록 · 차 반환", {"gap": g9, "site": s9})
    rk9[d0] = rk9[d0] - 4.5
    n9 = s9.get("sus", 0)
    view_tax.krw_sum_check(rows, rk9)
    chk((calcguard.snapshot().get("view_tax:krw_sum") or {}).get("sus", 0) == n9, "P4 1원 미만 차 = 기록 안 함(반올림 끝전 허용)")
rt_raw = 91000000 / 65789.1
disp_usd, akr_krw = 41500000 / rt_raw, 40000000.0
row_akm = {"sold": "2024-03-01", "sym": "TKA", "ex": "업비트", "qty": 1, "acq": 0, "disp": round(disp_usd, 2), "fee": 0, "rate": round(rt_raw, 4),
           "_acq": 28000.0, "_disp": disp_usd, "_akr": akr_krw, "akr": round(akr_krw), "_akm": 1}
rkd_akm = {"2024-03-01": disp_usd * rt_raw - akr_krw}
g_akm, tol_akm = view_tax.krw_sum_gap([row_akm], rkd_akm)
n9 = (calcguard.snapshot().get("view_tax:krw_sum") or {}).get("sus", 0)
view_tax.krw_sum_check([row_akm], rkd_akm)
chk(abs(g_akm) >= 1 and abs(g_akm) < tol_akm and (calcguard.snapshot().get("view_tax:krw_sum") or {}).get("sus", 0) == n9,
    "P4b 원화 마켓 매도 · 소수 많은 환율 — 반올림 몫(1원 넘음)은 허용 안 → 기록 없음", {"gap": g_akm, "tol": tol_akm})
view_tax.krw_sum_check([row_akm], {"2024-03-01": rkd_akm["2024-03-01"] - 100.0})
chk((calcguard.snapshot().get("view_tax:krw_sum") or {}).get("sus", 0) == n9 + 1, "P4b 같은 행 + 날짜 장부 100원 어긋남(허용 밖) = 기록", {"tol": tol_akm})
T.finish()
