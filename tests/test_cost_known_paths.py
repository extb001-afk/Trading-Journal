#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _costsim as S  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
from decimal import Decimal as D  # noqa: E402

import paths  # noqa: E402
import spamguard  # noqa: E402
import xchain_match  # noqa: E402

chk = T.chk
DAY = 86400


def near(a, b, tol=0.01):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


def a102_xasset(mode):
    c = S.reset()
    ch = S.Ch(c)
    t0 = S.NOW - 40 * DAY
    S.PXF[0] = lambda sym, ts: (2000 if ts < t0 + 2 * DAY else 3000) if sym == "ETH" else None
    usdc_b = ch.tok("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6)
    usdc_a = ch.tok("arbitrum", "0xaf88d065e77c8cc2239327c5edb3a432268e5831", "USDC", 6)
    eth_b = ch.tok("base", None, "ETH", 18, kind="native")
    eth_a = ch.tok("arbitrum", None, "ETH", 18, kind="native")
    ch.tx("base", "fund", t0, [(usdc_b, 10000, "acq", 10000)], "PROGRAM_IN")
    ch.tx("base", "buy", t0 + DAY, [(usdc_b, -2000, "disp", 2000), (eth_b, 1, "acq", 2000)], "SWAP")
    x = ch.tx("base", "send", t0 + 3 * DAY, [(eth_b, -1, "move_out", None), (eth_b, 1, "move_in", None, "out:base:0x" + "9b" * 20)], "TRANSFER_OUT")
    if mode == "x2st":
        y = ch.tx("arbitrum", "arr", t0 + 3 * DAY + 120, [(usdc_a, 2990, "acq", None)], "TRANSFER_IN")
    else:
        y = ch.tx("arbitrum", "arr", t0 + 3 * DAY + 120, [(eth_a, D("0.997"), "acq", None)], "TRANSFER_IN")
        ch.tx("arbitrum", "sell", t0 + 5 * DAY, [(eth_a, -D("0.997"), "disp", 2991), (usdc_a, 2991, "acq", 2991)], "SWAP")
    json.dump({"v": xchain_match.CACHE_V, "arr": {f"arbitrum|{y}": {"status": "link", "src_chain": "base", "src_tx": x, "proto": "debridge"}}},
              open(os.path.join(paths.STATE_DIR, xchain_match.CACHE_NAME), "w"))
    f, G, _rr = S.build()
    return {"cash": round(S.stable_qty(G) - 10000, 4), "rz": round(S.realized(f), 4), "tax": round(S.tax_sum(f), 4),
            "inv": round(S.cost_end(G) - S.realized(f) - 10000, 4)}


r = T.safe(a102_xasset, "x2st") or {}
chk(near(r.get("rz"), 990) and near(r.get("cash"), 990) and near(r.get("inv"), 0) and near(r.get("tax"), r.get("rz")),
    "A1-02 교차 자산 브릿지(ETH → USDC · id 연결) = ETH 매도 실현 $990 = 현금 차이 · 원가 불변식 0 · 명세 = 실현(종전 실현 0 · $990 증발)", r)
r = T.safe(a102_xasset, "same") or {}
chk(near(r.get("rz"), 991) and near(r.get("cash"), 991) and near(r.get("inv"), 0), "A1-02 대조 — 같은 자산 브릿지(ETH → ETH) 종전 그대로 실현 $991", r)


def f04v2(with_cache):
    c = S.reset()
    ch = S.Ch(c)
    t0 = S.NOW - 40 * DAY
    usdt_b = ch.tok("base", "0xfde4c96c8593536e31f229ea8f37b2ada2699bb2", "USDT", 6)
    usdc_b = ch.tok("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6)
    ua = "0xaf88d065e77c8cc2239327c5edb3a432268e5831"
    usdc_a = ch.tok("arbitrum", ua, "USDC", 6)
    eth_a = ch.tok("arbitrum", None, "ETH", 18, kind="native")
    ch.tx("base", "fund", t0, [(usdt_b, 10100, "acq", None)], "PROGRAM_IN")
    ch.tx("base", "swap", t0 + DAY, [(usdt_b, -10100, "disp", 10100), (usdc_b, 10000, "acq", 10100)], "SWAP")
    ch.tx("base", "out", t0 + 2 * DAY, [(usdc_b, -10000, "move_out", None), (usdc_b, 10000, "move_in", None, "out:base:0x" + "77" * 20)], "TRANSFER_OUT")
    y = ch.tx("arbitrum", "arr", t0 + 3 * DAY, [(usdc_a, 10000, "acq", None)], "TRANSFER_IN")
    ch.tx("arbitrum", "buy", t0 + 5 * DAY, [(usdc_a, -10000, "disp", 10000), (eth_a, 5, "acq", 10000)], "SWAP")
    if with_cache:
        json.dump({"v": xchain_match.CACHE_V, "arr": {xchain_match.arr_key("arbitrum", y, S.WA, ua): {
            "status": "ok", "cost": "10100", "cov": "10000", "qty": "10000", "label": "경유 역추적", "via": "0x" + "77" * 20}}},
            open(os.path.join(paths.STATE_DIR, xchain_match.CACHE_NAME), "w"))
    f, G, _rr = S.build()
    return {"rz": round(S.realized(f), 4), "tax": round(S.tax_sum(f), 4)}


for c9 in (True, False):
    r = T.safe(f04v2, c9) or {}
    chk(near(r.get("rz"), 0) and near(r.get("tax"), r.get("rz")), f"F04-v2 경유 역추적 스테이블 도착(캐시 {'있음' if c9 else '없음'}) = 액면 그대로(역추적 원가를 스테이블에 안 씀)", r)

KST9 = __import__("datetime").timezone(__import__("datetime").timedelta(hours=9))


def _iso(ts):
    return __import__("datetime").datetime.fromtimestamp(ts, KST9).isoformat()


def a101_offc(offc):
    S.reset()
    t0 = S.NOW - 30 * DAY
    S.PXF[0] = lambda sym, ts: 2000 + 20 * ((ts - t0) / 86400.0) if sym == "ETH" else None
    usd = [D(0)]

    def krw(ts, side, vol, px):
        vol = D(vol)
        funds = (vol * D(px)).quantize(D("1"))
        fee = (funds * D("0.0005")).quantize(D("0.00000001"))
        S.fills_upbit({"uuid": f"o{ts}", "market": "KRW-USDT", "side": side, "executed_volume": str(vol), "executed_funds": str(funds),
                       "paid_fee": str(fee), "created_at": _iso(ts), "state": "done", "ord_type": "limit", "price": str(px)})
        usd[0] += (funds - fee if side == "ask" else -(funds + fee)) / D("1400")
    krw(t0 + DAY, "bid", "10000", 1442)
    tw = t0 + 2 * DAY
    S.ex("upbit", withdraws=[{"uuid": "uw1", "currency": "USDT", "amount": "9999", "fee": "1", "txid": "0xt1", "state": "DONE",
                              "created_at": _iso(tw), "done_at": _iso(tw + 600), "transaction_type": "default"}])
    S.ex("binance", deposits=[S.norm_row("binance", "bd1", "USDT", "9999", 0, "0xt1", "ACCEPTED", tw + 900, tw + 900)])
    to = t0 + 4 * DAY
    S.ex("binance", withdraws=[S.norm_row("binance", "ow1", "USDT", "9999", "0", "Off-chain transfer 111", "DONE", to, to, address="me@x", network="")])
    S.ex("binance", deposits=[S.norm_row("binance", "od1", "USDT", "9999", 0, "Off-chain transfer 222", "ACCEPTED", to + 3 * DAY, to + 3 * DAY)])
    S.fills("binance", [S.norm_fill("binance", "ETHUSDT:1", (t0 + 8 * DAY) * 1000, "ETH", "USDT", "buy", "2160", "4", "0", "")])
    S.fills("binance", [S.norm_fill("binance", "ETHUSDT:2", (t0 + 9 * DAY) * 1000, "ETH", "USDT", "sell", "2200", "4", "0", "")])
    amt2 = D(9999) - 8640 + 8800 - 1
    tw2 = t0 + 10 * DAY
    S.ex("binance", withdraws=[S.norm_row("binance", "bw1", "USDT", str(amt2), "1", "0xt3", "DONE", tw2, tw2 + 300, address="0xup", network="ETH")])
    S.ex("upbit", deposits=[{"uuid": "ud1", "currency": "USDT", "amount": str(amt2), "txid": "0xt3", "state": "ACCEPTED",
                             "created_at": _iso(tw2 + 900), "done_at": _iso(tw2 + 900), "transaction_type": "default"}])
    krw(t0 + 12 * DAY, "ask", str(amt2), 1430)
    f, G, _rr = S.build(prefs={"offchain_self": {"binance": offc}})
    return {"usd": round(float(usd[0]), 4), "rz": round(S.realized(f), 4), "tax": round(S.tax_sum(f), 4)}


r = T.safe(a101_offc, True) or {}
chk(near(r.get("rz"), r.get("usd"), 0.05) and near(r.get("tax"), r.get("rz")),
    "A1-01 오프체인 자기 왕복(켬) 스테이블 귀환 = 풀 원가 승계 → 실현 = 원화 순현금 / 환율(종전 +$305 과대)", r)
r = T.safe(a101_offc, False) or {}
chk(r and r.get("rz", 0) > r.get("usd", 0) + 300, "A1-01 대조 — 끔 = 외부 유출·새 입금(종전 그대로 · 원가는 유출)", r)

def f05_rebate(mode):
    S.reset(px={"USDT": 1., "ETH": 2000.})
    t = S.NOW - 5 * DAY
    S.PXF[0] = lambda sym, ts: (1000. if ts < t + 2 * DAY else 2000.) if sym == "ETH" else None
    S.ex("okx", deposits=[S.norm_row("okx", "dep", "USDT", "1000", 0, "tx", "ACCEPTED", t - 10, t - 10)])
    if mode == "buy":
        S.fills("okx", [S.norm_fill("okx", "1", (t + 1) * 1000, "ETH", "USDT", "buy", "1000", "1", "-0.005", "ETH")])
        S.fills("okx", [S.norm_fill("okx", "2", (t + 3 * DAY) * 1000, "ETH", "USDT", "sell", "2000", "1.005", "0", "USDT")])
    else:
        S.fills("okx", [S.norm_fill("okx", "1", (t + 1) * 1000, "ETH", "USDT", "buy", "1000", "1", "0", "USDT")])
        fee, ccy = {"sell": ("-10", "USDT"), "xyz": ("-5", "XYZ"), "pos": ("10", "USDT")}[mode]
        S.fills("okx", [S.norm_fill("okx", "2", (t + 3 * DAY) * 1000, "ETH", "USDT", "sell", "2000", "1", fee, ccy)])
    f, G, _rr = S.build()
    src = [str(u9.get("kind") or u9.get("k") or u9)[:60] for g9 in G.values() if g9["sym"] == "XYZ" for u9 in (g9.get("unk_src") or [])]
    return {"rz": round(S.realized(f), 4), "tax": round(S.tax_sum(f), 4), "unk": S.unknown(G), "src": src}


for m9, want9 in (("sell", 1010), ("buy", 1010), ("xyz", 1000), ("pos", 990)):
    r = T.safe(f05_rebate, m9) or {}
    ok9 = near(r.get("rz"), want9) and near(r.get("tax"), r.get("rz"))
    if m9 == "xyz":
        ok9 = ok9 and any(k.startswith("XYZ") for k in r.get("unk") or {}) and any("리베이트" in x9 for x9 in r.get("src") or ())
    elif m9 in ("sell", "buy"):
        ok9 = ok9 and not r.get("unk")
    chk(ok9, f"F05 리베이트 {m9} = 실현 ${want9} · 명세 = 실현" + (" · 시세 없는 제3 자산 = 원가 미상 + 원가 미상 출처 기록(원가 지정 검토)" if m9 == "xyz" else
                                                          " · 원가 미상 수량 0(종전 consume(−q) → 미상 +q · 리베이트 실현 누락)" if m9 != "pos" else " (양수 대조 종전 그대로)"), r)

def a104_c11(mode):
    c = S.reset(px={"USDT": 1., "ETH": 2000.} if mode == "futfar" else {"USDT": 1., "ETH": 2000., "BNB": 600.})
    t0 = S.NOW - 20 * DAY
    S.PXF[0] = (lambda sym, ts: 2000. if sym == "ETH" else (600. if sym == "BNB" and ts >= t0 + 4 * DAY else None)) if mode == "futfar" \
        else (lambda sym, ts: {"ETH": 2000., "BNB": 600.}.get(sym))
    S.ex("bybit", deposits=[S.norm_row("bybit", "fund", "USDT", "10000", 0, "f1", "ACCEPTED", t0, t0)])
    S.fills("bybit", [S.norm_fill("bybit", "b0", (t0 + DAY) * 1000, "ETH", "USDT", "buy", "2000", "1.01", "0", ""),
                      S.norm_fill("bybit", "b1", (t0 + DAY) * 1000 + 1, "BNB", "USDT", "buy", "300", "1", "0", "")])
    ts = t0 + 3 * DAY
    if mode in ("int2", "int0"):
        aid = c.svc_exf._exf_asset("bybit", "ETH")
        c._post_leg("exchange", "bybit:recon", f"exfrecon:ETH:{ts}", 2 if mode == "int2" else 0, ts, aid, "exchange:bybit", -1000000, None, None, "opening", "EXF_ADJUST")
    else:
        aid = c.svc_exf._exf_asset("bybit", "BNB")
        c._post_leg("exchange", "bybit:futpnl", f"exfrecon:BNB:{ts}", 0, ts, aid, "exchange:bybit", -10000000, None, None, "opening", "EXF_ADJUST")
    S.fills("bybit", [S.norm_fill("bybit", "s1", (t0 + 5 * DAY) * 1000, "ETH", "USDT", "sell", "2500", "1", "0", "")])
    f, G, _rr = S.build()
    return {"rz": round(S.realized(f), 4), "tax": round(S.tax_sum(f), 4)}


for m9, want9, why9 in (("int2", 480, "A1-04 대출 이자 ETH 0.01 = 시가 비용 $20 + 처분 손익 0 → 실현 $480(종전 $500 · 이자 누락)"),
                        ("int0", 500, "A1-04 대조 — 일반 정정(leg 0) = 종전 그대로(소진만)"),
                        ("fut", 530, "C1-1 선물 정산 BNB 수수료 0.1(원가 $30 · 시가 $60) = 처분 손익 +$30(종전 $500 · 사라짐)"),
                        ("futfar", 500, "C1-1×S-1(합침 코덱스 s20m1) 수수료 시각 ±1시간 안 1분봉 없음(2일 뒤 봉만) = 평단 대체 · 처분 손익 0(먼 봉 $600 → +$30 안 됨)")):
    r = T.safe(a104_c11, m9) or {}
    chk(near(r.get("rz"), want9) and near(r.get("tax"), r.get("rz")), why9 + " · 명세 = 실현", r)

def a105_bridge_native(mode):
    c = S.reset(px={"USDC": 1., "ETH": 3000.})
    ch = S.Ch(c)
    t0 = S.NOW - 40 * DAY
    S.PXF[0] = lambda sym, ts: 3000. if sym == "ETH" else None
    usdc_b = ch.tok("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6)
    usdc_a = ch.tok("arbitrum", "0xaf88d065e77c8cc2239327c5edb3a432268e5831", "USDC", 6)
    tkn_b = ch.tok("base", "0x" + "21" * 20, "TKN", 18)
    tkn_a = ch.tok("arbitrum", "0x" + "22" * 20, "TKN", 18)
    eth_b = ch.tok("base", None, "ETH", 18, kind="native")
    ch.tx("base", "fund", t0, [(usdc_b, 10000, "acq", 10000)], "PROGRAM_IN")
    ch.tx("base", "buy", t0 + DAY, [(usdc_b, -1000, "disp", 1000), (tkn_b, 100, "acq", 1000)], "SWAP")
    ch.tx("base", "beth", t0 + DAY + 60, [(usdc_b, -300, "disp", 300), (eth_b, D("0.1"), "acq", 300)], "SWAP")
    if mode == "xfee":
        ch.tx("base", "bout", t0 + 2 * DAY, [(tkn_b, -100, "move_out", None), (eth_b, D("-0.01"), "move_out", None)], "BRIDGE")
        ch.tx("arbitrum", "bin", t0 + 2 * DAY + 300, [(tkn_a, 100, "acq", None)], "TRANSFER_IN")
        ch.tx("arbitrum", "sell", t0 + 5 * DAY, [(tkn_a, -100, "disp", 1500), (usdc_a, 1500, "acq", 1500)], "SWAP")
        ch.tx("base", "seth", t0 + 6 * DAY, [(eth_b, D("-0.09"), "disp", 270), (usdc_b, 270, "acq", 270)], "SWAP")
    else:
        ch.tx("base", "bout", t0 + 2 * DAY, [(eth_b, D("-0.01"), "move_out", None)], "BRIDGE")
        ch.tx("base", "seth", t0 + 6 * DAY, [(eth_b, D("-0.09"), "disp", 270), (usdc_b, 270, "acq", 270)], "SWAP")
    f, G, _rr = S.build(prefs={"gas_cost": True})
    return {"cash": round(S.stable_qty(G) - 10000, 4), "rz": round(S.realized(f), 4), "tax": round(S.tax_sum(f), 4)}


r = T.safe(a105_bridge_native, "xfee") or {}
chk(near(r.get("rz"), r.get("cash")) and near(r.get("rz"), 470) and near(r.get("tax"), r.get("rz")),
    "A1-05 BRIDGE 동봉 네이티브(짝 없음) = 비용 → 실현 $470 = 현금 차이(종전 $500 · $30 증발)", r)
r = T.safe(a105_bridge_native, "nat") or {}
chk(near(r.get("rz"), 0), "A1-05 대조 — 네이티브만 보낸 BRIDGE(짝 없음) = 종전 그대로(출발 항목 · 이동 중 — 비용으로 안 봄)", r)

def a107_short(mode):
    S.reset(px={"USDT": 1., "ETH": 2000.})
    t0 = S.NOW - 20 * DAY
    S.PXF[0] = lambda sym, ts: 2000 + 50 * ((ts - t0) / 86400.0) if sym == "ETH" else None
    S.ex("binance", deposits=[S.norm_row("binance", "fund", "USDT", "10000", 0, "tx0", "ACCEPTED", t0, t0)])
    S.fills("binance", [S.norm_fill("binance", "ETHUSDT:1", (t0 + DAY) * 1000, "ETH", "USDT", "buy", "2050", "2", "0", "")])
    tw = t0 + 3 * DAY
    arr = "0.99" if mode == "c" else "1"
    S.ex("binance", withdraws=[S.norm_row("binance", "w1", "ETH", "1", "0.01", "0xabc1", "DONE", tw, tw + 300, address="0x" + "11" * 20, network="ETH")])
    S.ex("okx", deposits=[S.norm_row("okx", "d1", "ETH", arr, 0, "0xabc1", "ACCEPTED", tw + 600, tw + 600)])
    S.fills("okx", [S.norm_fill("okx", "ETH-USDT:1", (t0 + 6 * DAY) * 1000, "ETH", "USDT", "sell", "2300", arr, "0", "")])
    S.fills("binance", [S.norm_fill("binance", "ETHUSDT:2", (t0 + 7 * DAY) * 1000, "ETH", "USDT", "sell", "2350", "0.99", "0", "")])
    f, G, _rr = S.build()
    return {"cash": round(S.stable_qty(G) - 10000, 4), "rz": round(S.realized(f), 4), "tax": round(S.tax_sum(f), 4)}


for m9, why9 in (("c", "A1-07 도착 부족 0.01 ETH = 수수료 비용 → 실현 = 현금 차이(종전 원가 $20.5 증발 · 실현 과대)"),
                 ("a", "A1-07 대조 — 전량 도착 = 종전 그대로")):
    r = T.safe(a107_short, m9) or {}
    chk(near(r.get("rz"), r.get("cash")) and near(r.get("tax"), r.get("rz")), why9, r)

def a108_order(dt):
    c = S.reset(px={"USDT": 1., "USDC": 1., "ETH": 2000.})
    ch = S.Ch(c)
    t0 = S.NOW - 30 * DAY
    S.PXF[0] = lambda sym, ts: 2000 + 20 * ((ts - t0) / 86400.0) if sym == "ETH" else None
    eth = ch.tok("base", None, "ETH", 18, kind="native")
    usdc = ch.tok("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6)
    S.ex("binance", deposits=[S.norm_row("binance", "fund", "USDT", "10000", 0, "f", "ACCEPTED", t0, t0)])
    S.fills("binance", [S.norm_fill("binance", "b1", (t0 + DAY) * 1000, "ETH", "USDT", "buy", "2000", "2", "0", "")])
    tw = t0 + 3 * DAY
    tx = "0x" + "c3" * 32
    S.ex("binance", withdraws=[S.norm_row("binance", "w1", "ETH", "2", "0", tx, "DONE", tw, tw + 60, address=S.WA, network="BASE")])
    c._post_leg("chain_tx", "base", tx, 0, tw - dt, eth, f"wallet:base:{S.WA}", 2 * 10 ** 18, None, None, "acq", "TRANSFER_IN")
    c.conn.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES ('base',?,?,'{}',5)", (tx, "TRANSFER_IN"))
    ch.tx("base", "sell", t0 + 6 * DAY, [(eth, -2, "disp", 4400), (usdc, 4400, "acq", 4400)], "SWAP")
    f, G, _rr = S.build()
    return {"rz": round(S.realized(f), 2), "ordgap": [p9["key"] for p9 in (f.get("pendings") or []) if str(p9.get("key", "")).startswith("ordgap:")]}


r = T.safe(a108_order, 600) or {}
chk(near(r.get("rz"), 400) and not r.get("ordgap"), "A1-08 대조 — 10분 먼저 찍힌 도착 = 순서 맞춰 원가 승계(실현 $400) · 검토 행 없음", r)
r = T.safe(a108_order, 4000) or {}
chk(r.get("ordgap") == ["ordgap:" + "0x" + "c3" * 32], "A1-08 1시간 넘게 먼저 찍힌 도착 = 검토 행 'ordgap:' 하나(종전 조용히 시가 — 숫자는 그대로)", r)

def c110_dollar_native():
    c = S.reset(px={"USDT": 1., "USDC": 1., "TKN": 12., "XDAI": 1.})
    ch = S.Ch(c)
    json.dump({"gnosis": {"0x" + "31" * 20: "TKN"}}, open(spamguard.user_path(), "w"))
    spamguard._user_refresh(force=True)
    xd = ch.tok("gnosis", None, "XDAI", 18, kind="native")
    tk = ch.tok("gnosis", "0x" + "31" * 20, "TKN", 18)
    t = ch.tx("gnosis", "sw", S.NOW - 5 * DAY, [(tk, -10, "disp", None), (xd, 100, "acq", None)], "SWAP")
    c.conn.commit()
    c.svc_price._price_tx("gnosis", t)
    c.conn.commit()
    got = {r9[0]: float(r9[1]) if r9[1] is not None else None for r9 in c.conn.execute(
        "SELECT a.symbol, p.cost_usd FROM postings p JOIN assets a ON a.asset_id = p.asset_id WHERE p.source_id = ?", (t,))}
    return got


r = T.safe(c110_dollar_native) or {}
chk(near(r.get("XDAI"), 100) and near(r.get("TKN"), 100), "C1-10 달러 네이티브(xDAI) 받는 스왑 = 받은 액면 $100 로 양쪽 원가(종전 유출측 1분봉 $120)", r)

def c111_stable_krw_card():
    S.reset()
    d0 = (S.NOW - 10 * DAY) // DAY * DAY - 9 * 3600 + 3 * 3600
    S.FXF[0] = lambda ts: 1500.0 if ts >= d0 + 3 * 3600 else 1400.0
    for i9, (ts, side, vol, px) in enumerate(((d0, "bid", 1000, 1414), (d0 + 3600, "ask", 500, 1428), (d0 + 4 * 3600, "ask", 500, 1500))):
        S.fills_upbit({"uuid": f"o{i9}", "market": "KRW-USDT", "side": side, "executed_volume": str(vol), "executed_funds": str(vol * px),
                       "paid_fee": "0", "created_at": _iso(ts), "state": "done", "ord_type": "limit", "price": str(px)})
    f, G, _rr = S.build()
    hk = sum(float(v) for v in (f.get("realizedKrwByDate") or {}).values())
    ck = sum(float(v) for p9 in (f.get("_positionsAll") or f.get("positions") or []) if p9.get("sym") == "USDT"
             for v in (p9.get("realizedKrwByDay") or {}).values())
    return {"rz": round(S.realized(f), 4), "hdr_krw": round(hk), "card_krw": round(ck)}


r = T.safe(c111_stable_krw_card) or {}
chk(near(r.get("rz"), 0) and r.get("hdr_krw") and abs(r.get("hdr_krw", 0) - r.get("card_krw", 0)) <= 1,
    "C1-11 스테이블 카드 원화 실현 = 헤더 원화(USD 0 인 날도 원화 ≥ ₩0.5 면 날짜 유지)", r)

def c19_lp_krw():
    c = S.reset(px={"USDC": 1.})
    ch = S.Ch(c)
    t0 = S.NOW - 30 * DAY
    S.FXF[0] = lambda ts: 1300.0 if ts < t0 + 2 * DAY else 1500.0
    usdc = ch.tok("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6)
    lpx = ch.tok("base", "0x" + "32" * 20, "LPX", 18)
    lpy = ch.tok("base", "0x" + "33" * 20, "LPY", 18)
    ch.tx("base", "fund", t0, [(usdc, 1000, "acq", None)], "PROGRAM_IN")
    ch.tx("base", "buy", t0 + DAY, [(usdc, -100, "disp", 100), (lpx, 50, "acq", 100)], "SWAP")
    ch.tx("base", "conv", t0 + 3 * DAY, [(lpx, -50, "disp", None), (lpy, 200, "acq", None)], "LP_REMOVE")
    ch.tx("base", "sell", t0 + 5 * DAY, [(lpy, -200, "disp", 150), (usdc, 150, "acq", 150)], "SWAP")
    f, G, _rr = S.build()
    rows9 = [r9 for r9 in (f.get("_taxRowsAll") or []) if r9.get("sym") == "LPY"]
    return {"rz": round(S.realized(f), 4), "akr": [round(float(r9.get("_akr") or r9.get("akr") or 0)) for r9 in rows9]}


r = T.safe(c19_lp_krw) or {}
chk(near(r.get("rz"), 50) and r.get("akr") == [130000], "C1-9 LP 전환 취득 코인 원화 원가 = 전환 원금 소진 원화 승계(명세 원화 취득가액 ₩130,000 · 종전 ₩150,000)", r)

def a106_loan_msell(mode):
    from datetime import datetime as _dt, timezone as _tz
    t0 = S.NOW - 40 * DAY
    day = lambda ts: _dt.fromtimestamp(ts, _tz.utc).strftime("%Y-%m-%d")   # noqa: E731
    S.reset(cfg_extra={"wallets": [], "loan_short": [{"exchange": "bybit", "asset": "ETH", "from": day(t0), "to": day(t0 + 30 * DAY)}]},
            px={"USDT": 1., "ETH": 2000.})
    S.PXF[0] = lambda sym, ts: (2000.0 if ts < t0 + 10 * DAY else 1500.0) if sym == "ETH" else None
    S.ex("bybit", deposits=[S.norm_row("bybit", "fund", "USDT", "10000", 0, "f1", "ACCEPTED", t0, t0)])
    if mode == "msell":
        S.fills("bybit", [S.norm_fill("bybit", "ms1", (t0 + 3 * DAY) * 1000, "ETH", "USDT", "sell", "2000", "1", "0", "")])
    else:
        tw = t0 + 2 * DAY
        S.ex("bybit", withdraws=[S.norm_row("bybit", "w1", "ETH", "1", "0", "0xt1", "DONE", tw, tw + 60, address="0x" + "11" * 20, network="ETH")])
        S.ex("binance", deposits=[S.norm_row("binance", "d1", "ETH", "1", 0, "0xt1", "ACCEPTED", tw + 600, tw + 600)])
        S.fills("binance", [S.norm_fill("binance", "s1", (t0 + 3 * DAY) * 1000, "ETH", "USDT", "sell", "2000", "1", "0", "")])
    S.fills("bybit", [S.norm_fill("bybit", "mb1", (t0 + 12 * DAY) * 1000, "ETH", "USDT", "buy", "1500", "1", "0", "")])
    f, G, rr = S.build()
    pend = [str(p9.get("key", "")) for p9 in (f.get("pendings") or []) if str(p9.get("key", "")).startswith(("unv:", "unvlost:"))]
    return {"rz": round(S.realized(f), 4), "tax": round(S.tax_sum(f), 4), "pend": pend}


for m9 in ("msell", "wd"):
    r = T.safe(a106_loan_msell, m9) or {}
    chk(near(r.get("rz"), 500) and near(r.get("tax"), r.get("rz")) and not r.get("pend"),
        f"A1-06 대출 공매도 {m9} = 실현 $500 · 원가 미상 매도·창 밖 처분 행 없음" + (" (종전 0 · 검토 행 2)" if m9 == "msell" else " (대조 무변)"), r)

def a107_split():
    S.reset(px={"USDT": 1., "ETH": 2000.})
    t0 = S.NOW - 20 * DAY
    S.ex("binance", deposits=[S.norm_row("binance", "fund", "USDT", "10000", 0, "tx0", "ACCEPTED", t0, t0)])
    S.fills("binance", [S.norm_fill("binance", "ETHUSDT:1", (t0 + DAY) * 1000, "ETH", "USDT", "buy", "2000", "1", "0", "")])
    tw = t0 + 3 * DAY
    S.ex("binance", withdraws=[S.norm_row("binance", "w1", "ETH", "1", "0", "0xspl1", "DONE", tw, tw + 300, address="0x" + "11" * 20, network="ETH")])
    S.ex("okx", deposits=[S.norm_row("okx", "d1", "ETH", "0.99", 0, "0xspl1", "ACCEPTED", tw + 600, tw + 600),
                          S.norm_row("okx", "d2", "ETH", "0.01", 0, "0xspl1", "ACCEPTED", tw + 900, tw + 900)])
    S.fills("okx", [S.norm_fill("okx", "ETH-USDT:1", (t0 + 6 * DAY) * 1000, "ETH", "USDT", "sell", "2300", "1", "0", "")])
    f, G, _rr = S.build()
    return {"cash": round(S.stable_qty(G) - 10000, 4), "rz": round(S.realized(f), 4), "unk": S.unknown(G)}


r = T.safe(a107_split) or {}
chk(near(r.get("rz"), 300) and near(r.get("cash"), 300) and not r.get("unk"), "A1-07 반례 — 분할 입금(0.99 + 0.01) = 둘 다 원가 승계 · 수수료로 안 지움(실현 $300 = 현금 차이)", r)


def f05_rebate_ov():
    S.reset(px={"USDT": 1., "ETH": 2000.})
    c = S._C[0]
    t = S.NOW - 5 * DAY
    S.PXF[0] = lambda sym, ts: (1000. if ts < t + 2 * DAY else 2000.) if sym == "ETH" else None
    S.ex("okx", deposits=[S.norm_row("okx", "dep", "USDT", "1000", 0, "tx", "ACCEPTED", t - 10, t - 10)])
    S.fills("okx", [S.norm_fill("okx", "1", (t + 1) * 1000, "ETH", "USDT", "buy", "1000", "1", "0", "USDT")])
    S.fills("okx", [S.norm_fill("okx", "2", (t + 3 * DAY) * 1000, "ETH", "USDT", "sell", "2000", "1", "-5", "XYZ")])
    S.fills("okx", [S.norm_fill("okx", "3", (t + 3 * DAY + 600) * 1000, "XYZ", "USDT", "sell", "2", "5", "0", "")])
    gid = c.conn.execute("SELECT COALESCE(group_id, -asset_id) FROM assets WHERE symbol='XYZ'").fetchone()[0]
    f, G, _rr = S.build(prefs={"cost_overrides": {f"g{gid}": {"mode": "unit", "unit": 2}}})
    return {"rz": round(S.realized(f), 4), "tax": round(S.tax_sum(f), 4), "unk": S.unknown(G)}


r = T.safe(f05_rebate_ov) or {}
chk(near(r.get("rz"), 1010) and near(r.get("tax"), r.get("rz")) and not r.get("unk"), "F05 반례 — 시세 없는 리베이트에 원가 지정 = 그 원가만큼 소득(실현 $1,010)", r)


def a105_late_native():
    c = S.reset(px={"USDC": 1., "ETH": 3000.})
    ch = S.Ch(c)
    t0 = S.NOW - 40 * DAY
    S.PXF[0] = lambda sym, ts: 3000. if sym == "ETH" else None
    usdc_b = ch.tok("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6)
    usdc_a = ch.tok("arbitrum", "0xaf88d065e77c8cc2239327c5edb3a432268e5831", "USDC", 6)
    tkn_b = ch.tok("base", "0x" + "21" * 20, "TKN", 18)
    tkn_a = ch.tok("arbitrum", "0x" + "22" * 20, "TKN", 18)
    eth_b = ch.tok("base", None, "ETH", 18, kind="native")
    eth_a = ch.tok("arbitrum", None, "ETH", 18, kind="native")
    ch.tx("base", "fund", t0, [(usdc_b, 10000, "acq", 10000)], "PROGRAM_IN")
    ch.tx("base", "buy", t0 + DAY, [(usdc_b, -1000, "disp", 1000), (tkn_b, 100, "acq", 1000)], "SWAP")
    ch.tx("base", "beth", t0 + DAY + 60, [(usdc_b, -3000, "disp", 3000), (eth_b, 1, "acq", 3000)], "SWAP")
    x = ch.tx("base", "bout", t0 + 2 * DAY, [(tkn_b, -100, "move_out", None), (eth_b, -1, "move_out", None)], "BRIDGE")
    ch.tx("arbitrum", "bin", t0 + 2 * DAY + 300, [(tkn_a, 100, "acq", None)], "TRANSFER_IN")
    y = ch.tx("arbitrum", "bin2", t0 + 2 * DAY + 7 * 3600, [(eth_a, 1, "acq", None)], "TRANSFER_IN")
    ch.tx("arbitrum", "sell", t0 + 5 * DAY, [(tkn_a, -100, "disp", 1500), (usdc_a, 1500, "acq", 1500)], "SWAP")
    ch.tx("arbitrum", "seth", t0 + 6 * DAY, [(eth_a, -1, "disp", 3000), (usdc_a, 3000, "acq", 3000)], "SWAP")
    json.dump({"v": xchain_match.CACHE_V, "arr": {f"arbitrum|{y}": {"status": "link", "src_chain": "base", "src_tx": x, "proto": "stargate"}}},
              open(os.path.join(paths.STATE_DIR, xchain_match.CACHE_NAME), "w"))
    f, G, _rr = S.build(prefs={"gas_cost": True})
    return {"cash": round(S.stable_qty(G) - 10000, 4), "rz": round(S.realized(f), 4), "unk": S.unknown(G)}


r = T.safe(a105_late_native) or {}
chk(near(r.get("rz"), 500) and near(r.get("cash"), 500), "A1-05 반례 — id 연결된 늦은 네이티브 도착 = 진짜 이동(비용 아님 · 실현 $500 = 현금 차이)", r)


def f04v1_krw():
    c = S.reset(px={"USDC": 1., "ETH": 2000.})
    ch = S.Ch(c)
    t0 = S.NOW - 30 * DAY
    S.FXF[0] = lambda ts: 1300.0 if ts < t0 + 2 * DAY else 1500.0
    usdc = ch.tok("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6)
    eth = ch.tok("base", None, "ETH", 18, kind="native")
    ch.tx("base", "fund", t0, [(eth, 1, "acq", 1000)], "PROGRAM_IN")
    ch.tx("base", "sw1", t0 + DAY, [(eth, -1, "disp", 1000), (usdc, 1000, "acq", 1000)], "SWAP")
    ch.tx("base", "pout", t0 + 3 * DAY, [(usdc, -1000, "move_out", None), (usdc, 1000, "move_in", None, "out:base:0x" + "5e" * 20)], "TRANSFER_OUT")
    ch.tx("base", "pin", t0 + 3 * DAY + 3600, [(usdc, 1000, "acq", None)], "PROGRAM_IN")
    ch.tx("base", "sw2", t0 + 5 * DAY, [(usdc, -1000, "disp", 1000), (eth, D("0.5"), "acq", 1000)], "SWAP")
    f, G, _rr = S.build()
    rows9 = [r9 for r9 in (f.get("_taxRowsAll") or []) if r9.get("sym") == "USDC"]
    return {"akr": [round(float(r9.get("_akr") or 0)) for r9 in rows9]}


r = T.safe(f04v1_krw) or {}
chk(r.get("akr") == [1300000], "F04-v1 원화 — 스테이블 예치 왕복 뒤 처분 명세 원화 취득가액 = 처음 원화 기록 ₩1,300,000", r)

def a107_krw():
    S.reset(px={"USDT": 1., "ETH": 2000.})
    t0 = S.NOW - 20 * DAY
    S.FXF[0] = lambda ts: 1300.0 if ts < t0 + 2 * DAY else 1500.0
    S.ex("binance", deposits=[S.norm_row("binance", "fund", "USDT", "10000", 0, "tx0", "ACCEPTED", t0, t0)])
    S.fills("binance", [S.norm_fill("binance", "ETHUSDT:1", (t0 + DAY) * 1000, "ETH", "USDT", "buy", "2000", "1", "0", "")])
    tw = t0 + 3 * DAY
    S.ex("binance", withdraws=[S.norm_row("binance", "w1", "ETH", "1", "0", "0xkrw1", "DONE", tw, tw + 300, address="0x" + "11" * 20, network="ETH")])
    S.ex("okx", deposits=[S.norm_row("okx", "d1", "ETH", "0.99", 0, "0xkrw1", "ACCEPTED", tw + 600, tw + 600)])
    f, G, _rr = S.build()
    rows9 = [r9 for r9 in (f.get("_taxRowsAll") or []) if r9.get("sym") == "ETH" and "수수료" in str(r9.get("ex"))]
    return {"akr": [round(float(r9.get("_akr") or 0)) for r9 in rows9]}


r = T.safe(a107_krw) or {}
chk(r.get("akr") == [26000], "A1-07 원화 — 도착 부족 몫 처분 명세 원화 취득가액 = 출발 때 소진 원화 ₩26,000(도착 환율 ₩30,000 아님)", r)

def f04_of_bridge(linked):
    c = S.reset()
    ch = S.Ch(c)
    t0 = S.NOW - 40 * DAY
    usdt_b = ch.tok("base", "0xfde4c96c8593536e31f229ea8f37b2ada2699bb2", "USDT", 6)
    usdc_b = ch.tok("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6)
    usdc_a = ch.tok("arbitrum", "0xaf88d065e77c8cc2239327c5edb3a432268e5831", "USDC", 6)
    eth_a = ch.tok("arbitrum", None, "ETH", 18, kind="native")
    ch.tx("base", "fund", t0, [(usdt_b, 10100, "acq", None)], "PROGRAM_IN")
    ch.tx("base", "swap", t0 + DAY, [(usdt_b, -10100, "disp", 10100), (usdc_b, 10000, "acq", 10100)], "SWAP")
    x = ch.tx("base", "send", t0 + 3 * DAY, [(usdc_b, -10000, "move_out", None), (usdc_b, 10000, "move_in", None, "out:base:0x" + "9b" * 20)], "TRANSFER_OUT")
    y = ch.tx("arbitrum", "arr", t0 + 3 * DAY + 120, [(usdc_a, 10000, "acq", None)], "TRANSFER_IN")
    ch.tx("arbitrum", "buy", t0 + 5 * DAY, [(usdc_a, -10000, "disp", 10000), (eth_a, 5, "acq", 10000)], "SWAP")
    if linked:
        json.dump({"v": xchain_match.CACHE_V, "arr": {f"arbitrum|{y}": {"status": "link", "src_chain": "base", "src_tx": x, "proto": "across"}}},
                  open(os.path.join(paths.STATE_DIR, xchain_match.CACHE_NAME), "w"))
    f, G, _rr = S.build()
    return {"rz": round(S.realized(f), 4), "tax": round(S.tax_sum(f), 4)}


for l9, want9 in ((True, -100), (False, 0)):
    r = T.safe(f04_of_bridge, l9) or {}
    chk(near(r.get("rz"), want9) and near(r.get("tax"), r.get("rz")),
        "F04 보낸 내역 브릿지 스테이블 — " + ("프로토콜 id 확정 = 원가 승계(실현 −$100)" if l9 else "id 없는 금액·시각 짝 = 종전 액면(실현 0)"), r)

def f04_split_id():
    c = S.reset()
    ch = S.Ch(c)
    t0 = S.NOW - 40 * DAY
    usdt_b = ch.tok("base", "0xfde4c96c8593536e31f229ea8f37b2ada2699bb2", "USDT", 6)
    usdc_b = ch.tok("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6)
    usdc_a = ch.tok("arbitrum", "0xaf88d065e77c8cc2239327c5edb3a432268e5831", "USDC", 6)
    eth_a = ch.tok("arbitrum", None, "ETH", 18, kind="native")
    ch.tx("base", "fund", t0, [(usdt_b, 12000, "acq", None)], "PROGRAM_IN")
    ch.tx("base", "swap", t0 + DAY, [(usdt_b, -12000, "disp", 12000), (usdc_b, 10000, "acq", 12000)], "SWAP")
    x = ch.tx("base", "bout", t0 + 3 * DAY, [(usdc_b, -10000, "move_out", None)], "BRIDGE")
    y1 = ch.tx("arbitrum", "a1", t0 + 3 * DAY + 120, [(usdc_a, 9900, "acq", None)], "TRANSFER_IN")
    y2 = ch.tx("arbitrum", "a2", t0 + 3 * DAY + 240, [(usdc_a, 200, "acq", None)], "TRANSFER_IN")
    ch.tx("arbitrum", "buy", t0 + 5 * DAY, [(usdc_a, -10100, "disp", 10100), (eth_a, 5, "acq", 10100)], "SWAP")
    json.dump({"v": xchain_match.CACHE_V, "arr": {f"arbitrum|{y}": {"status": "link", "src_chain": "base", "src_tx": x, "proto": "across"} for y in (y1, y2)}},
              open(os.path.join(paths.STATE_DIR, xchain_match.CACHE_NAME), "w"))
    f, G, _rr = S.build()
    return {"rz": round(S.realized(f), 4), "tax": round(S.tax_sum(f), 4)}


r = T.safe(f04_split_id) or {}
chk(near(r.get("rz"), -2000) and near(r.get("tax"), r.get("rz")), "F04 반례 — id 확정 분할 도착(9,900 + 200) 둘째 조각도 남은 원가 $120 승계 + 초과 100 액면(실현 −$2,000 · 종전 −$1,980)", r)


def f04v1_ex_wd():
    c = S.reset(px={"USDT": 1., "USDC": 1., "ETH": 2000.})
    ch = S.Ch(c)
    t0 = S.NOW - 30 * DAY
    usdc = ch.tok("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6)
    eth = ch.tok("base", None, "ETH", 18, kind="native")
    ch.tx("base", "fund", t0, [(eth, 1, "acq", 1100)], "PROGRAM_IN")
    ch.tx("base", "sw1", t0 + DAY, [(eth, -1, "disp", 1100), (usdc, 1000, "acq", 1100)], "SWAP")
    S.ex("binance", deposits=[S.norm_row("binance", "fund", "USDT", "1200", 0, "f", "ACCEPTED", t0, t0)])
    S.fills("binance", [S.norm_fill("binance", "USDCUSDT:1", (t0 + DAY) * 1000, "USDC", "USDT", "buy", "1.2", "1000", "0", "")])
    tp = t0 + 3 * DAY
    ch.tx("base", "pout", tp, [(usdc, -1000, "move_out", None), (usdc, 1000, "move_in", None, "out:base:0x" + "5e" * 20)], "TRANSFER_OUT")
    tx = "0x" + "d4" * 32
    S.ex("binance", withdraws=[S.norm_row("binance", "w1", "USDC", "1000", "0", tx, "DONE", tp + 600, tp + 660, address=S.WA, network="BASE")])
    c._post_leg("chain_tx", "base", tx, 0, tp + 900, usdc, f"wallet:base:{S.WA}", 1000 * 10 ** 6, None, None, "acq", "PROGRAM_IN")
    c.conn.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES ('base',?,?,'{}',5)", (tx, "PROGRAM_IN"))
    ch.tx("base", "sw2", t0 + 5 * DAY, [(usdc, -1000, "disp", 1000), (eth, D("0.5"), "acq", 1000)], "SWAP")
    f, G, _rr = S.build()
    return {"rz": round(S.realized(f), 4)}


r = T.safe(f04v1_ex_wd) or {}
chk(near(r.get("rz"), -200), "F04-v1 반례 — txid 확정 거래소 출금 도착 = 출금 원가 승계 먼저(왕복 짝이 안 가로챔 · 실현 −$200)", r)

T.finish()
