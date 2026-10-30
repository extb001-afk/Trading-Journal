#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _costsim as S  # noqa: E402

import json  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from decimal import Decimal as D  # noqa: E402

import paths  # noqa: E402
from timeutil import KST  # noqa: E402
import view_tax  # noqa: E402
from view_fspin import KD_PIN, kd_conf, kd_ts  # noqa: E402

chk = T.chk
DAY = 86400
AT = datetime.fromtimestamp(S.NOW - 10 * DAY, KST).strftime("%Y-%m-%d")
TT = kd_ts(AT)
T0 = TT - 20 * DAY
ON = {"kr_deemed": {"on": True, "at": AT}}


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def eth_px(before, at, after):
    return lambda sym, ts: (before if ts < TT - 120 else at if ts <= TT + 120 else after) if sym == "ETH" else None


def rows_of(rr, sym):
    return [r for r in rr.books.tax_rows if r.get("sym") == sym and not r.get("be")]


def kd_flows(G):
    return sum((fl.get("kd") or D(0) for g in G.values() for fl in g.get("flows") or ()), D(0))


def kd_rows(rr):
    return sum(float(r.get("_kd") or 0) for r in rr.books.tax_rows)


def kd_transit(rr):
    tot = D(0)
    for p9 in (rr.ex_transit, rr.fx_transit):
        for v9 in (p9 or {}).values():
            for e9 in (v9 if isinstance(v9, list) else (v9,)):
                if isinstance(e9, dict) and e9.get("kd"):
                    if "left" in e9:
                        tot += e9["kd"] * (e9["left"] / e9["qty"]) if e9.get("qty") else D(0)
                    elif not e9.get("used"):
                        tot += e9["kd"]
    return tot


def summ(rr):
    return (rr.fs_sum or {}).get("kd")


def keys_anywhere(rr):
    bad = [r for r in rr.books.tax_rows if "kd" in r or "_kd" in r or "kdu" in r]
    bad += [g["gid"] for g in rr.G.values() if "_kd" in g or any("kd" in fl for fl in g.get("flows") or ())]
    for p9 in (rr.ex_transit, rr.fx_transit):
        for v9 in (p9 or {}).values():
            bad += [1 for e9 in (v9 if isinstance(v9, list) else (v9,)) if isinstance(e9, dict) and "kd" in e9]
    return bad + (["fs_sum"] if "kd" in (rr.fs_sum or {}) else [])


def dex(prefs, before=1000, at=2000, after=2500, sell="1", rebuy=False):
    c = S.reset(px=None if at is not None else {"USDT": 1., "USDC": 1.})
    ch = S.Ch(c)
    S.PXF[0] = eth_px(before, at, after)
    usdc = ch.tok("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6)
    eth = ch.tok("base", None, "ETH", 18, kind="native")
    ch.tx("base", "fund", T0, [(usdc, 20000, "acq", 20000)], "PROGRAM_IN")
    ch.tx("base", "buy", T0 + DAY, [(usdc, -before, "disp", before), (eth, 1, "acq", before)], "SWAP")
    ch.tx("base", "tick", TT, [(usdc, 1, "acq", 1)], "PROGRAM_IN")
    if rebuy:
        ch.tx("base", "buy2", TT + DAY, [(usdc, -after, "disp", after), (eth, 1, "acq", after)], "SWAP")
    p = D(after) * D(sell)
    ch.tx("base", "sell", TT + 2 * DAY, [(eth, -D(sell), "disp", p), (usdc, p, "acq", p)], "SWAP")
    f, G, rr = S.build(prefs)
    return f, G, rr


f0, G0, r0 = dex(None)
f1, G1, r1 = dex(ON)
e0, e1 = rows_of(r0, "ETH"), rows_of(r1, "ETH")
chk(len(e0) == len(e1) == 1, "K1 합성 빌드(1 ETH 매수 → T → 매도 · 명세 행 1)", {"off": e0, "on": e1})
if len(e0) == len(e1) == 1:
    a0, a1 = e0[0], e1[0]
    chk(abs(a0["_akr"] - 1_400_000) < 1 and abs(a1["_akr"] - 2_800_000) < 1 and a1.get("kd") == 1_400_000 and abs(a1.get("kdu", 0) - 2_800_000) < 1,
        "K1 명세 원화 취득가액 = max(T 시가, 장부) ₩2,800,000 · 가산 kd ₩1,400,000 · 기준 시가 ₩2,800,000/개(꺼짐 ₩1,400,000)",
        {"off": a0.get("_akr"), "on": a1.get("_akr"), "kd": a1.get("kd"), "kdu": a1.get("kdu")})
    chk(S.realized(f0) == S.realized(f1) and f0.get("realizedKrwByDate") == f1.get("realizedKrwByDate")
        and r0.books.realized_krw_by_date == r1.books.realized_krw_by_date,
        "K1 USD 실현·날짜별 원화 실현(헤더·달력) 그대로", {"usd": (S.realized(f0), S.realized(f1))})
    s0 = {(x[0], x[1], x[2]): x for x in f0.get("taxSummary") or []}
    s1 = {(x[0], x[1], x[2]): x for x in f1.get("taxSummary") or []}
    k9 = [k for k in s0 if k[1] == "ETH"]
    chk(k9 and all(s0[k][8:11] == s1[k][8:11] for k in k9) and all(abs((s0[k][12] + 1_400_000) - s1[k][12]) < 1 for k in k9),
        "K1 요약 8~10열(헤더 정의) 그대로 · 12열(명세 원화 취득) = +가산", {k: (s0[k][8:13], s1[k][8:13]) for k in k9})
    gap1, _tol = view_tax.krw_sum_gap(r1.books.tax_rows, r1.books.realized_krw_by_date)
    gap0, _tol0 = view_tax.krw_sum_gap(r0.books.tax_rows, r0.books.realized_krw_by_date)
    chk(abs(gap1 - gap0) < 1e-6, "K1 감시 차(명세 원화 실현 합 − 날짜별) 켬 = 꺼짐", {"on": gap1, "off": gap0})
    sm = summ(r1)
    chk(sm and sm["state"] == "applied" and sm["n"] >= 1 and sm["rows"] == 1 and sm["add"] == 1_400_000 and sm["lost"] == 0,
        "K1 요약(fs_sum kd) = 적용 · 올린 그룹 · 적용 행 1 · 더한 원화 · 잃은 몫 0", sm)
    chk(abs(float(kd_flows(G1)) + kd_rows(r1) - sm["up"]) < 1 if sm else False,
        "K1 보존식 = 행 가산 + 남은 사이클 가산 = T 에 올린 합", {"flows": float(kd_flows(G1)), "rows": kd_rows(r1), "up": (sm or {}).get("up")})

chk(not keys_anywhere(r0) and kd_conf({}) is None and kd_conf({"kr_deemed": {"on": "true"}}) is None,
    "K9 꺼짐(설정 없음) = 행·그룹·사이클·트랜짓·요약 어디에도 의제 키 없음 · on 은 진짜 true 만", keys_anywhere(r0))

_f2, _G2, r2 = dex(ON, before=1000, at=800, after=900)
e2 = rows_of(r2, "ETH")
chk(e2 and "kd" not in e2[0] and abs(e2[0]["_akr"] - 1_400_000) < 1 and (summ(r2) or {}).get("keep", 0) >= 1 and (summ(r2) or {}).get("n") == 0,
    "K2 산 가격(₩1,400,000) > T 시가(₩1,120,000) = 가산 0 · 장부 그대로(keep)", {"row": e2, "sum": summ(r2)})

_f4, G4, r4 = dex(ON, sell="0.4")
e4 = rows_of(r4, "ETH")
chk(e4 and e4[0].get("kd") == 560_000 and abs(e4[0]["_akr"] - 1_120_000) < 1 and abs(float(kd_flows(G4)) - 840_000) < 1,
    "K4 부분 매도 0.4 = kd ₩560,000 · akr ₩1,120,000 · 남은 사이클 가산 ₩840,000", {"row": e4, "left": float(kd_flows(G4))})

_f3, G3, r3 = dex(ON, rebuy=True)
e3 = rows_of(r3, "ETH")
sm3 = summ(r3) or {}
chk(e3 and e3[0].get("kd") == 700_000 and abs(e3[0]["_akr"] - (4_900_000 / 2 + 700_000)) < 1
    and abs(float(kd_flows(G3)) + kd_rows(r3) - sm3.get("up", -1)) < 1,
    "K3 T 뒤 추가 매수(₩3,500,000) 희석 = 1/2 매도 kd ₩700,000 · akr = 장부 반 + 가산 반 · 보존(행 + 남은 = 올린 합)",
    {"row": e3, "left": float(kd_flows(G3)), "up": sm3.get("up")})


def wd(prefs):
    c = S.reset()
    ch = S.Ch(c)
    S.PXF[0] = eth_px(1000, 2000, 2500)
    usdc = ch.tok("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6)
    eth = ch.tok("base", None, "ETH", 18, kind="native")
    S.ex("binance", deposits=[S.norm_row("binance", "kd0", "USDT", "10000", 0, "kdn0", "ACCEPTED", T0, T0)])
    S.fills("binance", [S.norm_fill("binance", "ETHUSDT:b1", (T0 + DAY) * 1000, "ETH", "USDT", "buy", "1000", "1", "0", "USDT")])
    ch.tx("base", "tick", TT, [(usdc, 1, "acq", 1)], "PROGRAM_IN")
    tx = "0x" + "ab" * 32
    tw = TT + DAY
    S.ex("binance", withdraws=[S.norm_row("binance", "w1", "ETH", "1", "0", tx, "DONE", tw, tw + 60, address=S.WA, network="BASE")])
    c._post_leg("chain_tx", "base", tx, 0, tw + 300, eth, f"wallet:base:{S.WA}", 10 ** 18, None, None, "acq", "TRANSFER_IN")
    c.conn.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES ('base',?,?,'{}',5)", (tx, "TRANSFER_IN"))
    ch.tx("base", "sell", TT + 2 * DAY, [(eth, -1, "disp", 2500), (usdc, 2500, "acq", 2500)], "SWAP")
    return S.build(prefs)


def wd_fee(prefs, ex="binance"):
    c = S.reset()
    ch = S.Ch(c)
    S.PXF[0] = eth_px(1000, 2000, 2500)
    usdc = ch.tok("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6)
    eth = ch.tok("base", None, "ETH", 18, kind="native")
    S.ex(ex, deposits=[S.norm_row(ex, "kd0", "USDT", "10000", 0, "kdn0", "ACCEPTED", T0, T0)])
    S.fills(ex, [S.norm_fill(ex, "ETHUSDT:b1", (T0 + DAY) * 1000, "ETH", "USDT", "buy", "1000", "1", "0", "USDT")])
    ch.tx("base", "tick", TT, [(usdc, 1, "acq", 1)], "PROGRAM_IN")
    tx = "0x" + "ac" * 32
    tw = TT + DAY
    S.ex(ex, withdraws=[S.norm_row(ex, "w1", "ETH", "0.99" if ex == "binance" else "1", "0.01", tx, "DONE", tw, tw + 60, address=S.WA, network="BASE")])
    c._post_leg("chain_tx", "base", tx, 0, tw + 300, eth, f"wallet:base:{S.WA}", 99 * 10 ** 16, None, None, "acq", "TRANSFER_IN")
    c.conn.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES ('base',?,?,'{}',5)", (tx, "TRANSFER_IN"))
    ch.tx("base", "sell", TT + 2 * DAY, [(eth, D("-0.99"), "disp", D("2475")), (usdc, D("2475"), "acq", D("2475"))], "SWAP")
    return S.build(prefs)


f5o, G5o, r5o = wd(None)
f5, G5, r5 = wd(ON)
e5o, e5 = rows_of(r5o, "ETH"), rows_of(r5, "ETH")
sm5 = summ(r5) or {}
chk(e5 and e5o and abs(e5o[0]["_akr"] - 1_400_000) < 1 and e5[0].get("kd") == 1_400_000 and abs(e5[0]["_akr"] - 2_800_000) < 1,
    "K5 거래소 매수 → T → 지갑 출금·도착 → DEX 매도 = 운반 뒤에도 akr ₩2,800,000 · kd ₩1,400,000(꺼짐 ₩1,400,000)", {"off": e5o, "on": e5})
chk(S.realized(f5o) == S.realized(f5) and r5o.books.realized_krw_by_date == r5.books.realized_krw_by_date and not keys_anywhere(r5o),
    "K5 USD 실현·날짜별 원화 실현 그대로 · 꺼짐 키 0", {"usd": (S.realized(f5o), S.realized(f5))})
chk(abs(float(kd_flows(G5)) + kd_rows(r5) + float(kd_transit(r5)) + sm5.get("lost", 0) - sm5.get("up", -1)) < 1 and sm5.get("lost") == 0,
    "K5 보존식(엄격) = 행 + 남은 사이클 + 남은 트랜짓 + 잃은 몫 = 올린 합 · 잃은 몫 0",
    {"flows": float(kd_flows(G5)), "rows": kd_rows(r5), "tr": float(kd_transit(r5)), "sum": sm5})

for ex13 in ("binance", "bithumb"):
    _f13, G13, r13 = wd_fee(ON, ex13)
    e13 = rows_of(r13, "ETH")
    sm13 = summ(r13) or {}
    fee13 = [r for r in e13 if str(r.get("ex") or "").startswith("수수료로 쓴 코인")]
    sale13 = [r for r in e13 if r not in fee13]
    chk(len(fee13) == 1 and len(sale13) == 1 and fee13[0].get("kd") == 14_000 and sale13[0].get("kd") == 1_386_000
        and abs(float(kd_flows(G13)) + kd_rows(r13) + float(kd_transit(r13)) + sm13.get("lost", 0) - sm13.get("up", -1)) < 1,
        "K13 %s 출금 수수료 0.01 ETH = 수수료 처분 행 kd ₩14,000 · 도착 매도 행 kd ₩1,386,000 · 보존식(두 번 붙음·샘 없음)" % ex13,
        {"fee": [(r.get("kd"), r.get("_akr")) for r in fee13], "sale": [(r.get("kd"), r.get("_akr")) for r in sale13], "sum": sm13})

def up_order(uid, side, ts, vol, krw, mkt="KRW-ETH"):
    return {"uuid": uid, "market": mkt, "side": side, "state": "done", "ord_type": "limit", "executed_volume": str(vol), "executed_funds": str(krw),
            "paid_fee": "0", "created_at": iso(ts), "price": str(D(krw) / D(vol))}


def krw_mkt(prefs):
    c = S.reset()
    ch = S.Ch(c)
    S.PXF[0] = eth_px(1000, 2000, 2500)
    usdc = ch.tok("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6)
    S.fills_upbit(up_order("ub1", "bid", T0 + DAY, "1", "1400000"))
    ch.tx("base", "tick", TT, [(usdc, 1, "acq", 1)], "PROGRAM_IN")
    S.fills_upbit(up_order("ua1", "ask", TT + 2 * DAY, "1", "3500000"))
    return S.build(prefs)


f6o, _G6o, r6o = krw_mkt(None)
f6, _G6, r6 = krw_mkt(ON)
k6o, k6 = rows_of(r6o, "ETH"), rows_of(r6, "ETH")
chk(k6 and k6o and k6[0].get("_akm") and abs(k6[0]["_akr"] - 2_800_000) < 1 and k6[0].get("kd") == 1_400_000 and abs(k6o[0]["_akr"] - 1_400_000) < 1,
    "K5b 원화 마켓 사이클 = _akm 행 · 명세 akr ₩2,800,000(가산 ₩1,400,000 · 꺼짐 = 실지불 ₩1,400,000)", {"off": k6o, "on": k6})
s6o = {(x[0], x[1], x[2]): x for x in f6o.get("taxSummary") or []}
s6 = {(x[0], x[1], x[2]): x for x in f6.get("taxSummary") or []}
chk(r6o.books.realized_krw_by_date == r6.books.realized_krw_by_date and f6o.get("realizedKrwByDate") == f6.get("realizedKrwByDate")
    and all(s6o[k][8:11] == s6[k][8:11] for k in s6o if k[1] == "ETH") and any(k[1] == "ETH" for k in s6o),
    "K5b 헤더·달력 원화 실현(C4 보정 포함)·요약 8~10열 그대로(가산은 C4 뒤 · 헤더 정의 밖)", {k: (s6o[k][8:13], s6.get(k, [None] * 13)[8:13]) for k in s6o if k[1] == "ETH"})
gap6, _t6 = view_tax.krw_sum_gap(r6.books.tax_rows, r6.books.realized_krw_by_date)
gap6o, _t6o = view_tax.krw_sum_gap(r6o.books.tax_rows, r6o.books.realized_krw_by_date)
chk(abs(gap6 - gap6o) < 1e-6, "K5b 감시 차(원화 마켓 행 = akr − kd) 켬 = 꺼짐", {"on": gap6, "off": gap6o})


def stable(prefs):
    c = S.reset()
    ch = S.Ch(c)
    usdc = ch.tok("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6)
    S.FXF[0] = lambda ts: 1300.0 if ts < TT - 120 else (1500.0 if ts <= TT + 120 else 1450.0)
    S.fills_upbit(up_order("us1", "bid", T0 + DAY, "10000", "13000000", "KRW-USDT"))
    ch.tx("base", "tick", TT, [(usdc, 1, "acq", 1)], "PROGRAM_IN")
    S.fills_upbit(up_order("us2", "ask", TT + 2 * DAY, "10000", "14500000", "KRW-USDT"))
    return S.build(prefs)


_f7o, _G7o, r7o = stable(None)
_f7, _G7, r7 = stable(ON)
u7o, u7 = rows_of(r7o, "USDT"), rows_of(r7, "USDT")
chk(u7 and u7o and abs(u7o[0].get("_sfx", 0) - 1_500_000) < 1 and abs(u7[0].get("_sfx", 0) + 500_000) < 1 and u7[0].get("kd") == 2_000_000,
    "K6 스테이블 ₩1,300 → T ₩1,500 → ₩1,450 원화 매도 = 환차 −₩500,000(꺼짐 +₩1,500,000) · kd ₩2,000,000",
    {"off": [(r.get("_akr"), r.get("_sfx")) for r in u7o], "on": [(r.get("_akr"), r.get("_sfx"), r.get("kd")) for r in u7]})
chk(r7o.books.realized_krw_by_date == r7.books.realized_krw_by_date, "K6 날짜별 원화 실현 그대로(스테이블 명세만)", None)

_f8, _G8, r8 = dex(ON, at=None)
e8 = rows_of(r8, "ETH")
sm8 = summ(r8) or {}
chk(e8 and "kd" not in e8[0] and abs(e8[0]["_akr"] - 1_400_000) < 1 and sm8.get("state") == "waiting" and sm8.get("wait", 0) >= 1,
    "K7 T 시가 없음 = 가산 0(장부 그대로) · 대기(waiting) 집계", {"row": e8, "sum": sm8})
spec = [k for k in (summ(r1) or {}).get("pin_new", {}) if k != "fx"]
chk(len(spec) == 1, "K7 켬 빌드가 새로 매긴 시가 = 고정 후보(출처 열쇠 1 + 환율)", (summ(r1) or {}).get("pin_new"))


def dex_pinned(pin_at):
    def pre():
        json.dump({"_v": 1, "at": pin_at, "p": {spec[0]: [3_000_000.0, "close", S.NOW]}}, open(paths.state(KD_PIN), "w"))
    c = S.reset(px={"USDT": 1., "USDC": 1.})
    pre()
    ch = S.Ch(c)
    S.PXF[0] = eth_px(1000, None, 2500)
    usdc = ch.tok("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6)
    eth = ch.tok("base", None, "ETH", 18, kind="native")
    ch.tx("base", "fund", T0, [(usdc, 20000, "acq", 20000)], "PROGRAM_IN")
    ch.tx("base", "buy", T0 + DAY, [(usdc, -1000, "disp", 1000), (eth, 1, "acq", 1000)], "SWAP")
    ch.tx("base", "tick", TT, [(usdc, 1, "acq", 1)], "PROGRAM_IN")
    ch.tx("base", "sell", TT + 2 * DAY, [(eth, -1, "disp", 2500), (usdc, 2500, "acq", 2500)], "SWAP")
    return S.build(ON)


if spec:
    _f9, _G9, r9 = dex_pinned(AT)
    e9 = rows_of(r9, "ETH")
    chk(e9 and e9[0].get("kd") == 1_600_000 and (r9.G and any((g.get("_kd") or {}).get("src") == "pin" for g in r9.G.values())),
        "K7 고정값(₩3,000,000/개 · 같은 기준일) = 시가 대신 그것(kd ₩1,600,000 · 출처 pin)", e9)
    _f10, _G10, r10 = dex_pinned("2030-12-31" if AT != "2030-12-31" else "2031-12-31")
    e10 = rows_of(r10, "ETH")
    chk(e10 and "kd" not in e10[0] and (summ(r10) or {}).get("state") == "waiting",
        "K7 기준일이 다른 고정값 = 통째 무시(새로 매김 · 이번엔 시가 없음 → 대기)", {"row": e10, "sum": summ(r10)})

fut = datetime.fromtimestamp(S.NOW + 30 * DAY, KST).strftime("%Y-%m-%d")
_f11, G11, r11 = dex({"kr_deemed": {"on": True, "at": fut}})
e11 = rows_of(r11, "ETH")
chk(e11 and "kd" not in e11[0] and abs(e11[0]["_akr"] - 1_400_000) < 1 and (summ(r11) or {}).get("state") == "before"
    and not any("_kd" in g for g in G11.values()) and kd_flows(G11) == 0,
    "K8 기준일 미래 = 계산 그대로(before · 행·그룹·사이클 가산 없음)", {"row": e11, "sum": summ(r11)})


def unk(prefs):
    c = S.reset()
    ch = S.Ch(c)
    S.PXF[0] = eth_px(1000, 2000, 2500)
    usdc = ch.tok("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6)
    eth = ch.tok("base", None, "ETH", 18, kind="native")
    ch.tx("base", "in", T0 + DAY, [(eth, 1, "acq", None)], "TRANSFER_IN")
    ch.tx("base", "tick", TT, [(usdc, 1, "acq", 1)], "PROGRAM_IN")
    ch.tx("base", "sell", TT + 2 * DAY, [(eth, -1, "disp", 2500), (usdc, 2500, "acq", 2500)], "SWAP")
    return S.build(dict(prefs or {}, first_seen_px=False))


f12o, _G12o, r12o = unk(None)
f12, _G12, r12 = unk(ON)
chk(json.dumps(r12o.books.tax_rows, sort_keys=True, default=str) == json.dumps(r12.books.tax_rows, sort_keys=True, default=str)
    and S.realized(f12o) == S.realized(f12) and (summ(r12) or {}).get("unk", 0) >= 1,
    "K10 최초 인식 끔 + 원가 미확인 매도 = 명세 행·실현 그대로(원가 미확인 = v1 미적용 · 집계 unk)", {"sum": summ(r12)})


import accounting_krw  # noqa: E402
import http_post_prefs  # noqa: E402
import http_route  # noqa: E402
from view_fspin import kd_at_ok, kd_field  # noqa: E402

bad_at = ["2028-02-30", "2025-12-31", "2100-01-01", None, "20281231", 20281231, "2028-1-31"]
chk(not any(kd_at_ok(x) for x in bad_at) and kd_at_ok("2028-12-31") and kd_at_ok("2026-01-01") and kd_at_ok("2099-12-31"),
    "K11 기준일 검증 — 실제 날짜 · 2026-01-01~2099-12-31 · YYYY-MM-DD 글자만", [x for x in bad_at if kd_at_ok(x)])
chk(kd_conf({"kr_deemed": {"on": True}}) == "2028-12-31" and kd_conf({"kr_deemed": {"on": True, "at": "2029-06-30"}}) == "2029-06-30"
    and kd_conf({"kr_deemed": {"on": True, "at": "bad"}}) == "2028-12-31" and kd_conf({"kr_deemed": {"on": False, "at": "2029-06-30"}}) is None
    and kd_conf({"kr_deemed": {"on": 1}}) is None and kd_conf({"kr_deemed": "on"}) is None,
    "K11 설정 읽기 — on 진짜 true 만 · 기준일 없음·틀림 = 기본 2028-12-31", None)
locked = http_route.post_routes()[1]
chk(locked.get("/api/kr_deemed") is http_post_prefs.post_kr_deemed and "post_kr_deemed" in http_post_prefs.__all__,
    "K11 경로 표(설정 잠금 안)·__all__ 등록", sorted(k for k in locked if "kr" in k))
kf0 = kd_field({"kr_deemed": {"on": False, "at": "2030-12-31"}}, None)
kf1 = kd_field({"kr_deemed": {"on": True, "at": AT}}, summ(r1))
chk(kf0 == {"on": False, "at": "2030-12-31"} and kf1.get("on") is True and kf1.get("state") == "applied" and kf1.get("rows") == 1 and kf1.get("add") == 1_400_000,
    "K11 응답 krDeemed = on·at(꺼짐) · 켬이면 요약(state·적용 행·더한 원화)", (kf0, kf1))
chk("krDeemed" not in f0 and (f1.get("krDeemed") or {}).get("on") is True and (f1.get("krDeemed") or {}).get("rows") == 1,
    "K11 설정을 한 번도 안 저장한 빌드(꺼짐 기본) = 응답에 krDeemed 칸 없음 · 켬 빌드 = 칸 있음(적용 행)", (sorted(k for k in f0 if k.startswith("kr")), f1.get("krDeemed")))


class KdFix(accounting_krw.KrDeemed):

    def __init__(self, unit):
        self.unit = unit

    def price(self, grp, t_at):
        return self.unit, "pin"


sm12 = {"tr": 0, "up": 0.0}
st12 = {"gid": 1, "qty": D(1000), "left": D(1000), "known": D(1000), "cost": D(1030), "kc": D(1030), "kk": D(1_442_000), "krw": D(1_442_000)}
KdFix(1500.0)._transit_up({"is_stable": True}, st12, TT, sm12)
cv12 = {"gid": 2, "qty": D(2000), "left": D(2000), "known": D(2000), "cost": D(1000), "krw": D(1_400_000), "_cv": {"from": "SOL", "ratio": 200.0}}
KdFix(280_000.0)._transit_up({"is_stable": False}, cv12, TT, sm12)
nm12 = {"gid": 3, "qty": D(1), "left": D("0.5"), "known": D(1), "cost": D(1000), "krw": D(1_400_000)}
KdFix(2_800_000.0)._transit_up({"is_stable": False}, nm12, TT, sm12)
chk(st12.get("kd") == D(58_000) and cv12.get("kd") == D(1_400_000) and nm12.get("kd") == D(1_400_000) and abs(sm12["up"] - (58_000 + 1_400_000 + 700_000)) < 1e-6,
    "K12 이동 중 올림 — 스테이블 = 수량(known × kc/cost) 기준(₩58,000 · USD 원가 기준 아님) · 교차 자산 = 출발 단위(known ÷ 비율) · 반쯤 도착 = 남은 몫만 집계",
    {"st": st12.get("kd"), "cv": cv12.get("kd"), "nm": nm12.get("kd"), "up": sm12["up"]})
live12 = accounting_krw.KrDeemed.live(({"a": [{"used": False, "qty": 1}, {"used": True, "qty": 1}]}, {"b": {"left": D(0), "qty": 1}, "c": {"left": D(1), "qty": 1}}))
chk(len(live12) == 2, "K12 이동 중 항목 = 안 쓴 입금 대기 · 남은 수량 있는 출금 트랜짓만", live12)

from types import SimpleNamespace as NS  # noqa: E402

import accounting_fee  # noqa: E402
import histcurve  # noqa: E402

kp14 = accounting_krw.KrwPools(None, fxb=NS(rate_at=lambda ts: 1400.0), krw_mkt=set(), up_mkt={}, fx_name={})
kp14.kd_last[0] = D(100)
kp14.kd_reset()
kp14.kd_lose("fee_px", D(5))
kp14.kd_lose("fee_fx", None)
kp14.kd_lose("akr", D(0))
chk(kp14.kd_lost == {"left": [D(100), 1], "fee_px": [D(5), 1]} and kp14.kd_last[0] == 0,
    "K14 잃은 몫 사유별 — 다음 소진에 덮임(left) · 수수료 시가 없음(fee_px) · 값 없음 = 안 셈", kp14.kd_lost)
kp14b = accounting_krw.KrwPools(None, fxb=NS(rate_at=lambda ts: 1400.0), krw_mkt=set(), up_mkt={}, fx_name={})
g14 = accounting_fee.FeeBook.fee_gain(NS(px=NS(kpx=kp14b)), {"is_fiat": False}, None, D(1), D(1000), TT, "d", "base", kd=D(7))
chk(g14 == 0 and kp14b.kd_lost == {"fee_px": [D(7), 1]}, "K14 수수료 처분 시가 없음 = 손익 0 · 넘겨받은 가산분은 fee_px 로 집계(종전 = 소리 없이 빠짐)", kp14b.kd_lost)
kp14c = accounting_krw.KrwPools(None, fxb=NS(rate_at=lambda ts: 1400.0), krw_mkt=set(), up_mkt={}, fx_name={})
ck14 = D(1_400_000)
kp14c.kd_last[0], kp14c.kd_for[0] = D(9), ck14
accounting_fee.FeeBook.fee_gain(NS(px=NS(kpx=kp14c)), {"is_fiat": False}, None, D(1), D(1000), TT, "d", "base", ck14)
kp14c.kd_reset()
chk(kp14c.kd_lost == {"fee_px": [D(9), 1]}, "K14 kd 인자 없는 수수료(직전 소진 원화 객체 그대로) = 그 가산분도 fee_px(덮임 left 아님)", kp14c.kd_lost)

off14 = {"gid": 1, "ts": TT - DAY, "qty": D(1), "left": D(1), "known": D(1), "cost": D(1000), "cost_krw": D(1_400_000)}
rt14 = {"qty": D(2), "left": D(2), "known": D(2), "cost": D(2000), "krw": D(2_800_000)}
ret14 = {"qty": D(1), "left": D(1), "known": D(1), "cost": D(1000), "krw": D(1_400_000)}
br14 = {"gid": 4, "qty": D(1), "left": D(1), "known": D(1), "cost": D(1000)}
st14 = {"gid": 5, "qty": D(1), "left": D(0), "known": D(1), "cost": D(1000), "krw": D(1_400_000)}
G14 = {g: {"gid": g, "is_stable": False} for g in (1, 2, 3, 4, 5)}
sum14 = {"lost": 0.0, "miss": 0.0, "up": 0.0, "add": 0.0, "pin_new": {}}
kx14 = accounting_krw.KrDeemed.__new__(accounting_krw.KrDeemed)
kx14.fsx = NS(px=NS(kpx=kp14b, unx=NS(fs_sum={"kd": sum14})))
kx14.miss = []
kx14.price = lambda grp, t_at, peek=False: (None, "wait") if grp["gid"] == 4 else (2_800_000.0, "pin")
kx14.snap(G14, (("offc", {("upbit", "ETH"): [off14]}), ("rt", {("base", "0xaa", 2): rt14}), ("ret", {3: {"0xdest": ret14}}), ("br", [br14, st14])), TT)
off14["left"] -= D("0.6")
rt14["left"] -= D(2)
br14["left"] = D(0)
kx14.end()
by14 = sum14.get("lostBy") or {}
chk(by14 == {"fee_px": [7, 1], "tr_offc": [840_000, 1], "tr_rt": [2_800_000, 1], "tr_br": [0, 1]} and sum14["miss"] == 3_640_000 and sum14["lost"] == 7,
    "K14 T 에 이동 중 · 올림 안 하는 길 = T 뒤 도착한 몫만 가산이었을 원화로(오프체인 0.6 = ₩840,000 · 예치 복귀 전부 · 외부 주소 안 돌아옴 = 안 셈 · "
    "시가 모름 = 건만 · 남은 수량 0 = 대상 아님) · miss 는 보존식(lost) 밖", {"by": by14, "miss": sum14["miss"], "lost": sum14["lost"]})

pk14 = accounting_krw.KrDeemed.__new__(accounting_krw.KrDeemed)
new14 = {"sym:KDX": [5.0, "close", 0]}
pk14.pin = {}
pk14.fsx = NS(px=NS(unx=NS(fs_sum={"kd": {"pin_new": new14}})), fs_spec=lambda g: g["spec"], fs_ok_ca=lambda g: True, now=S.NOW,
              fxb=NS(rate_src=lambda ts: (1400.0, "minute")))
want14 = "cg:kdpeek" in histcurve.DAYCLOSE.want or "cg:kdpeek" in histcurve.DAYCLOSE.want_old
pp14 = (pk14.price({"is_stable": False, "spec": "sym:KDX"}, TT, peek=True), pk14.price({"is_stable": False, "spec": "cg:kdpeek"}, TT, peek=True),
        pk14.price({"is_stable": True, "spec": "stable"}, TT, peek=True))
chk(pp14[0] == (5.0, "pin") and pp14[1][0] is None and pp14[2] == (1400.0, "fx-minute") and new14 == {"sym:KDX": [5.0, "close", 0]}
    and not want14 and "cg:kdpeek" not in histcurve.DAYCLOSE.want and "cg:kdpeek" not in histcurve.DAYCLOSE.want_old,
    "K14 시가 엿보기(집계용) = 이번 빌드가 매긴 값도 씀 · 새 고정 후보·그날 마감 요청 안 남김", {"p": pp14, "new": new14})
sm1 = summ(r1) or {}
kf14 = kd_field({"kr_deemed": {"on": True, "at": AT}}, sm1)
chk(sm1.get("miss") == 0 and sm1.get("lostBy") == {} and kf14.get("lostBy") == {} and kf14.get("miss") == 0,
    "K14 K1 빌드 = 적용 못 한 몫 0(사유 없음) · 응답 krDeemed 에 miss·lostBy 칸", {"sum": {k: sm1.get(k) for k in ("lost", "miss", "lostBy")}})
T.finish()
