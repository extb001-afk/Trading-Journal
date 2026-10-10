"""Synthetic demo data for the dashboard (no real accounts)."""
from __future__ import annotations

import hashlib
import math
import random
import time
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
DOW = ["월", "화", "수", "목", "금", "토", "일"]
CHAIN_NAME = {"eth": "Ethereum", "base": "Base", "arbitrum": "Arbitrum", "optimism": "Optimism",
              "polygon": "Polygon", "scroll": "Scroll", "zksync": "zkSync", "gnosis": "Gnosis",
              "bsc": "BSC", "sol": "Solana"}
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _hex(seed: str, n: int) -> str:
    return hashlib.sha256(("tj-demo:" + seed).encode()).hexdigest()[:n]


def _b58(seed: str) -> str:
    n = int.from_bytes(hashlib.sha256(("tj-demo:" + seed).encode()).digest(), "big")
    s = ""
    while n:
        n, r = divmod(n, 58)
        s = _B58[r] + s
    return s


def demo_evm(i: int) -> str:
    return "0x" + _hex(f"wallet{i}", 40)


def demo_sol(i: int) -> str:
    return _b58(f"sol{i}")


def _short(a: str) -> str:
    return a[:6] + "…" + a[-4:]


def _tx(seed: str, sol: bool = False) -> str:
    if sol:
        s = _b58("tx" + seed)
        return s[:4] + "…" + s[-4:]
    h = _hex("tx" + seed, 64)
    return "0x" + h[:4] + "…" + h[-4:]


def _mmdd(d: datetime) -> str:
    return d.strftime("%m-%d")


def _base(cfg=None) -> dict:
    now = datetime.now(KST)
    return {
        "fields": {
            "costOverrideRows": [], "coinDexUsd": 0.0, "coinCexUsd": 0.0,
            "futures": {"margin": 0, "notional": 0, "mmRatio": {}, "pnlBreak": {}, "longNotional": 0, "shortNotional": 0,
                        "upnl": 0, "posCount": 0, "ts": int(time.time()), "snapshotTs": {}, "staleExchanges": [],
                        "positions": [], "realizedByDate": {}, "realizedRows": [], "realizedTotal": 0},
            "stables": [], "coins": [], "fiats": [], "lps": [], "lpEvents": [], "positions": [], "plans": {},
            "pendings": [], "gasByChain": [], "taxRows": [], "extraEvents": [], "realizedByDate": {}, "reviews": {},
            "rate": 1385.0, "fxRate": 1368.0, "dailySeries": [], "usdtByDate": {}, "lastScan": "",
            "upbitConnected": False, "srcChips": [], "walletRows": [], "depositRows": [], "aliasRows": [],
            "unpricedSyms": [], "backfillProgress": None, "gasByMonth": {}, "walletAlias": {}, "dustUsd": 50.0,
            "fallbackOn": False, "originPending": 0, "costOverrides": {},
        },
        "todayKey": _mmdd(now), "realizedMonth": 0.0, "builtAt": int(time.time()),
    }


def empty(cfg: dict | None) -> dict:
    d = _base()
    f = d["fields"]
    rows = {}
    for w in (cfg or {}).get("wallets") or []:
        t = w.get("type", "evm")
        a = w.get("address") or ""
        k = a if t == "sol" else a.lower()
        r = rows.setdefault(k, {"alias": w.get("label") or "", "addr": k, "key": k, "chains": [], "last": "첫 수집 대기"})
        r["chains"].append(CHAIN_NAME.get("sol" if t == "sol" else w.get("chain"), w.get("chain") or "?"))
    for r in rows.values():
        r["chains"] = " · ".join(sorted(set(r["chains"])))
    f["walletRows"] = list(rows.values())
    f["lastScan"] = "첫 수집 대기"
    if rows:
        f["backfillProgress"] = {"pct": 0, "detail": "수집기가 과거 거래(최근 5개월)를 불러오기 시작합니다",
                                 "active": "원장 생성 대기 — tj-core 가 첫 레코드를 받으면 화면이 채워집니다", "remain": ""}
    return d


_COINS = [
    ("ETH", "eth", 3920.0, 6.4, 3310.0), ("SOL", "sol", 212.0, 118.0, 171.0), ("ARB", "arbitrum", 0.92, 21000, 1.04),
    ("AERO", "base", 1.31, 14500, 0.94), ("JUP", "sol", 0.97, 16800, 0.82), ("PENDLE", "eth", 5.9, 2100, 4.6),
    ("OP", "optimism", 2.05, 5400, 1.72), ("JTO", "sol", 2.4, 3900, 2.9), ("LINK", "eth", 24.6, 610, 19.8),
    ("VIRTUAL", "base", 1.62, 7000, 1.32), ("POL", "polygon", 0.51, 9000, 0.47), ("BNB", "bsc", 690.0, 4.2, 612.0),
]


_LP_VALUE, _LP_FEES = 11986.4, 88.3


def _day_built(now=None) -> int:
    n = now or datetime.now(KST)
    return int(n.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())


def build() -> dict:
    rnd = random.Random(20260926)
    now = datetime.now(KST)
    d = _base()
    d["builtAt"] = _day_built(now)
    f = d["fields"]
    wallets = [("메인", demo_evm(1), ["eth", "base", "arbitrum", "optimism", "bsc"]),
               ("트레이딩", demo_evm(2), ["base", "arbitrum", "polygon"]),
               ("솔라나", demo_sol(1), ["sol"])]
    wl = {w[1]: w[0] for w in wallets}
    f["walletAlias"] = wl
    f["walletRows"] = [{"alias": a, "addr": ad, "key": ad, "chains": " · ".join(CHAIN_NAME[c] for c in chs),
                        "last": f"{rnd.randint(3, 50)}초 전 스캔"} for a, ad, chs in wallets]
    f["srcChips"] = [{"label": "EVM 7체인 · blockscout", "short": "EVM 2지갑", "addr": "증분 감시 · 12초 전 스캔"},
                     {"label": "Solana · Helius", "short": "SOL 1지갑", "addr": "증분 감시 · 5초 전 스캔"},
                     {"label": "BSC · 공개 RPC", "short": "BSC 1지갑", "addr": "증분 감시 · 40초 전 스캔"}]
    f["depositRows"] = [{"ex": "업비트", "net": "EVM", "addr": demo_evm(90), "memo": "—", "ok": True},
                        {"ex": "업비트", "net": "Solana", "addr": demo_sol(90), "memo": "—", "ok": True},
                        {"ex": "바이낸스", "net": "EVM", "addr": demo_evm(91), "memo": "자동 수집 · 14개 통화", "ok": True},
                        {"ex": "바이낸스", "net": "SOL", "addr": demo_sol(91), "memo": "자동 수집 · 3개 통화", "ok": True},
                        {"ex": "OKX", "net": "EVM", "addr": demo_evm(92), "memo": "자동 수집 · 9개 통화", "ok": True}]
    f["upbitConnected"] = True
    f["lastScan"] = "5초 전 스캔"
    f["fiats"] = [{"ex": "업비트", "krw": 12_450_000.0, "note": "거래소 예수금"}]

    def locs_for(sym, chain, qty):
        if chain == "sol":
            return [{"w": "솔라나 지갑", "ch": "Solana", "sub": "Solana · " + _short(demo_sol(1)), "qty": qty}]
        if sym in ("ETH", "SOL", "ARB"):
            q1 = round(qty * 0.7, 6)
            return [{"w": "메인 지갑", "ch": CHAIN_NAME[chain], "sub": CHAIN_NAME[chain] + " · " + _short(demo_evm(1)), "qty": q1},
                    {"w": "업비트", "sub": "거래소 잔고 (입금·체결 원장)", "qty": round(qty - q1, 6)}]
        wn = "트레이딩 지갑" if chain in ("base", "polygon") else "메인 지갑"
        wa = demo_evm(2) if wn.startswith("트레이딩") else demo_evm(1)
        return [{"w": wn, "ch": CHAIN_NAME[chain], "sub": CHAIN_NAME[chain] + " · " + _short(wa), "qty": qty}]

    coins = []
    for i, (sym, ch, px, qty, avg) in enumerate(_COINS):
        coins.append({"key": f"g{100 + i}", "sym": sym, "name": f"{sym} · {CHAIN_NAME[ch]}", "qty": qty, "price": px,
                      "avg": avg, "kqty": qty, "fbQty": 0, "fbCost": 0, "locs": locs_for(sym, ch, qty)})
    coins.append({"key": "g140", "sym": "DEGEN", "name": "DEGEN · Base", "qty": 52000.0, "price": 0.0068, "avg": 0,
                  "kqty": 0, "fbQty": 0, "fbCost": 0, "locs": locs_for("DEGEN", "base", 52000.0)})
    coins.append({"key": "g141", "sym": "WBTC", "name": "WBTC · Arbitrum", "qty": 0.8, "price": 0, "avg": 0,
                  "kqty": 0, "fbQty": 0, "fbCost": 0, "locs": locs_for("WBTC", "arbitrum", 0.8),
                  "unv": "WBTC", "ck": "arbitrum", "ca": "0x" + _hex("unv-token", 40)})
    for c9 in coins:
        if c9["sym"] == "JUP":
            c9["fsc"] = 2460.0
    f["coins"] = coins
    f["unpricedSyms"] = []
    f["stables"] = [
        {"key": "g200", "sym": "USDC", "name": "USDC", "qty": 18250.0, "price": 1, "avg": 1,
         "locs": [{"w": "메인 지갑", "ch": "Base", "sub": "Base · " + _short(demo_evm(1)), "qty": 12250.0},
                  {"w": "솔라나 지갑", "ch": "Solana", "sub": "Solana · " + _short(demo_sol(1)), "qty": 6000.0}]},
        {"key": "g201", "sym": "USDT", "name": "USDT", "qty": 9400.0, "price": 1, "avg": 1,
         "locs": [{"w": "업비트", "sub": "거래소 잔고 (입금·체결 원장)", "qty": 9400.0}]}]
    f["venueFlows30"] = {"days": 30, "flowOk": True, "by": {
        "메인 지갑": {"in": 4200.0, "out": 1850.0, "realized": 612.4, "realizedKrw": 846000},
        "트레이딩 지갑": {"in": 900.0, "out": 300.0, "realized": -84.2, "realizedKrw": -116500},
        "업비트": {"in": 2500.0, "out": 1200.0, "realized": 233.0, "realizedKrw": 322000}}}
    f["exBalTs"] = {"업비트": round(time.time()) - 180}
    f["coinDexUsd"] = round(sum(c["qty"] * c["price"] for c in coins) * 0.8, 2)
    f["coinCexUsd"] = round(sum(c["qty"] * c["price"] for c in coins) * 0.2, 2)

    positions = []
    evs_all = []
    for i, (sym, ch, px, qty, avg) in enumerate(_COINS[:10]):
        sold = qty * rnd.choice([0, 0, 0.3, 0.5])
        bought = qty + sold
        sell_px = avg * rnd.uniform(1.05, 1.35)
        realized = round(sold * (sell_px - avg), 2)
        plan = []
        off = 0
        for k in range(rnd.randint(1, 3)):
            plan.append((off, "buy", bought / (k + 2) if k == 0 else bought / 3))
            off += rnd.randint(1, 6) * 1440 + rnd.randint(60, 540)
        if sold:
            plan += [(off, "dep", sold), (off + 120, "sell", sold)]
        end = now - timedelta(days=rnd.randint(1, 40) if sold else rnd.randint(0, 15), hours=rnd.randint(1, 10))
        t0 = end - timedelta(minutes=plan[-1][0])
        opened = t0
        events = []
        for m, kind, q in plan:
            ts = (t0 + timedelta(minutes=m)).strftime("%m-%d %H:%M")
            if kind == "buy":
                events.append({"t": ts, "k": "온체인 매수",
                               "d": f"{CHAIN_NAME[ch]} · {'Jupiter' if ch == 'sol' else 'Uniswap V3'} · USDC → {sym}",
                               "q": f"{q:,.2f}", "a": f"${q * avg:,.0f}", "tx": _tx(f"{sym}{m}", ch == "sol"), "src": None})
            elif kind == "dep":
                events.append({"t": ts, "k": "입금 확인", "d": "업비트 입금 (전송 매칭)",
                               "q": f"{q:,.2f}", "a": "—", "tx": _tx(f"{sym}dep", ch == "sol"), "src": "ex:upbit"})
            else:
                events.append({"t": ts, "k": "거래소 매도", "d": f"업비트 {sym}/KRW 체결",
                               "q": f"{q:,.2f}", "a": f"${q * sell_px:,.0f}", "tx": "—", "src": "ex:upbit"})
        steps = ["온체인 매수"] + (["거래소 입금", "매도 진행"] if sold else [])
        status = "부분 매도" if sold else "보유"
        cost = round(bought * avg, 2)
        positions.append({"unknownQty": 0, "fbAvg": 0, "fbCost": 0, "unvQty": 0, "unvProceeds": 0, "realizedFb": 0,
                          "soldProceeds": round(sold * sell_px, 2), "avgSell": round(sell_px, 6) if sold else 0,
                          "key": f"g{100 + i}", "sym": sym, "chain": CHAIN_NAME[ch], "status": status,
                          "held": qty, "bought": bought, "movedQty": 0, "movedCost": 0, "soldQty": sold,
                          "avg": avg, "cost": cost, "realized": realized, "unreal": round(qty * (px - avg), 2),
                          "opened": _mmdd(opened), "_ots": int(opened.timestamp()),
                          "fee": f"${rnd.uniform(0.4, 38):.2f}", "steps": steps, "events": events,
                          "realizedByDay": {e["t"][:5]: realized for e in events if e["k"] == "거래소 매도" and realized}})
        for e in events:
            if e["k"] == "거래소 매도":
                evs_all.append((e, sym, realized, sold, avg, sell_px))
    for j, (sym, ch, avg, out) in enumerate([("PEPE", "eth", 0.0000112, 0.0000131), ("BONK", "sol", 0.0000245, 0.0000219)]):
        closed = now - timedelta(days=9 + j * 16, hours=3)
        opened = closed - timedelta(days=6 + j)
        q = 900_000_000 if sym == "PEPE" else 310_000_000
        realized = round(q * (out - avg), 2)
        positions.append({"unknownQty": 0, "fbAvg": 0, "fbCost": 0, "unvQty": 0, "unvProceeds": 0, "realizedFb": 0,
                          "soldProceeds": round(q * out, 2), "avgSell": out, "key": f"g{150 + j}", "sym": sym,
                          "chain": CHAIN_NAME[ch], "status": "종료", "held": 0.0, "bought": q, "movedQty": 0,
                          "movedCost": 0, "soldQty": q, "avg": avg, "cost": round(q * avg, 2), "realized": realized,
                          "unreal": 0, "opened": _mmdd(opened), "_ots": int(opened.timestamp()), "fee": "$6.20",
                          "realizedByDay": {_mmdd(closed): realized} if realized else {},
                          "steps": ["온체인 매수", "거래소 입금", "전량 매도"],
                          "events": [{"t": opened.strftime("%m-%d %H:%M"), "k": "온체인 매수", "d": f"{CHAIN_NAME[ch]} · 스왑",
                                      "q": f"{q:,.0f}", "a": f"${q * avg:,.0f}", "tx": _tx(sym, ch == "sol"), "src": None},
                                     {"t": closed.strftime("%m-%d %H:%M"), "k": "거래소 매도", "d": f"업비트 {sym}/KRW 체결",
                                      "q": f"{q:,.0f}", "a": f"${q * out:,.0f}", "tx": "—", "src": "ex:upbit"}]})
        f["taxRows"].append({"sold": _mmdd(closed), "sym": sym, "ticker": sym, "ex": "업비트", "qty": float(q),
                             "acq": round(q * avg, 2), "disp": round(q * out, 2), "fee": 0})
    fs_got, fs_sold = now - timedelta(days=24, hours=5), now - timedelta(days=18, hours=2)
    fs_q, fs_px, fs_out = 1250.0, 3.10, 3.62
    fs_real = round(fs_q * (fs_out - fs_px), 2)
    positions.append({"unknownQty": 0, "fbAvg": 0, "fbCost": 0, "unvQty": 0, "unvProceeds": 0, "realizedFb": 0,
                      "soldProceeds": round(fs_q * fs_out, 2), "avgSell": fs_out, "key": "g152", "sym": "ZRO", "chain": "Ethereum",
                      "status": "종료", "held": 0.0, "bought": fs_q, "movedQty": 0, "movedCost": 0, "soldQty": fs_q, "avg": fs_px,
                      "cost": round(fs_q * fs_px, 2), "realized": fs_real, "unreal": 0, "opened": _mmdd(fs_got), "_ots": int(fs_got.timestamp()),
                      "fee": "$2.10", "steps": ["온체인 매수", "거래소 입금", "전량 매도"],
                      "fsEst": {"cost": round(fs_q * fs_px, 2), "qty": fs_q, "real": fs_real},
                      "realizedByDay": {_mmdd(fs_sold): fs_real},
                      "events": [{"t": fs_got.strftime("%m-%d %H:%M"), "k": "전송", "d": "Ethereum 외부 유입 (원가 미상)",
                                  "q": f"{fs_q:,.0f}", "a": "—", "tx": _tx("ZRO"), "src": None},
                                 {"t": fs_sold.strftime("%m-%d %H:%M"), "k": "거래소 매도",
                                  "d": "업비트 · KRW 마켓 체결 · 원가 일부 최초 인식 시가",
                                  "q": f"{fs_q:,.0f}", "a": f"${fs_q * fs_out:,.0f}", "tx": "—", "src": "ex:upbit"}]})
    f["taxRows"].append({"sold": _mmdd(fs_sold), "sym": "ZRO", "ticker": "ZRO", "ex": "업비트 · 최초 인식 시가", "qty": fs_q,
                         "acq": round(fs_q * fs_px, 2), "disp": round(fs_q * fs_out, 2), "fee": 0})
    zb_q, zb_px, zb_out = 300.0, 3.30, 3.55
    zb_t = [now - timedelta(days=16, hours=h) for h in (9, 6, 2)]
    positions.append({"unknownQty": 0, "fbAvg": 0, "fbCost": 0, "unvQty": 0, "unvProceeds": 0, "realizedFb": 0,
                      "soldProceeds": round(zb_q * zb_out, 2), "avgSell": zb_out, "key": "g153", "sym": "ZRO", "chain": "Base",
                      "status": "종료", "held": 0.0, "bought": zb_q, "movedQty": 0, "movedCost": 0, "soldQty": zb_q, "avg": zb_px,
                      "cost": round(zb_q * zb_px, 2), "realized": round(zb_q * (zb_out - zb_px), 2), "unreal": 0, "opened": _mmdd(zb_t[0]),
                      "_ots": int(zb_t[0].timestamp()), "fee": "$0.40", "steps": ["온체인 매수", "전량 매도"],
                      "realizedByDay": {_mmdd(zb_t[2]): round(zb_q * (zb_out - zb_px), 2)},
                      "events": [{"t": zb_t[0].strftime("%m-%d %H:%M"), "k": "온체인 매수", "d": "Base · 스왑", "q": "150", "a": f"${150 * zb_px:,.0f}", "tx": _tx("ZRB1"), "src": None},
                                 {"t": zb_t[1].strftime("%m-%d %H:%M"), "k": "온체인 매수", "d": "Base · 스왑", "q": "150", "a": f"${150 * zb_px:,.0f}", "tx": _tx("ZRB2"), "src": None},
                                 {"t": zb_t[2].strftime("%m-%d %H:%M"), "k": "온체인 매도", "d": "Base · 스왑 매도", "q": "300", "a": f"${zb_q * zb_out:,.0f}", "tx": _tx("ZRB3"), "src": None}]})
    f["taxRows"].append({"sold": _mmdd(zb_t[2]), "sym": "ZRO", "ticker": "ZRO", "ex": "온체인(DEX)", "qty": zb_q,
                         "acq": round(zb_q * zb_px, 2), "disp": round(zb_q * zb_out, 2), "fee": 0})
    wt_got, wt_sold = now - timedelta(days=2, hours=6), now - timedelta(days=1, hours=3)
    wt_q, wt_out = 8000.0, 0.0515
    positions.append({"unknownQty": 0, "fbAvg": 0, "fbCost": 0, "unvQty": wt_q, "unvProceeds": round(wt_q * wt_out, 2), "realizedFb": 0,
                      "soldProceeds": round(wt_q * wt_out, 2), "avgSell": wt_out, "key": "g154", "sym": "WEN", "chain": "Solana",
                      "status": "종료", "held": 0.0, "bought": 0.0, "movedQty": 0, "movedCost": 0, "soldQty": wt_q, "avg": 0,
                      "cost": 0, "realized": 0, "unreal": 0, "opened": _mmdd(wt_got), "_ots": int(wt_got.timestamp()),
                      "fee": "$0.01", "steps": ["외부 유입", "전량 매도"], "realizedByDay": {},
                      "unvByDay": {_mmdd(wt_sold): [1, round(wt_q * wt_out, 2)]},
                      "events": [{"t": wt_got.strftime("%m-%d %H:%M"), "k": "전송", "d": "Solana 외부 유입 (원가 미상)",
                                  "q": f"{wt_q:,.0f}", "a": "—", "tx": _tx("WEN", True), "src": None},
                                 {"t": wt_sold.strftime("%m-%d %H:%M"), "k": "온체인 매도", "d": "Solana · 스왑 매도 · 원가 미확인",
                                  "q": f"{wt_q:,.0f}", "a": f"${wt_q * wt_out:,.0f}", "tx": _tx("WEN2", True), "src": None}]})
    f["fsRealByDate"] = {_mmdd(fs_sold): [fs_real, round(fs_real * f["rate"])]}
    f["firstSeen"] = {"on": True, "eff": True, "fb": False, "n": 3, "usd": round(fs_q * fs_px + 420.0, 2), "miss": 1, "rows": 1,
                      "real": fs_real, "stN": 1, "stUsd": 3000.0,
                      "hold": {"wait": 1, "unv": 2}, "wait": 1, "ret": 1, "sd": 1, "pin": 3, "note": False}
    f["positions"] = positions
    for e, sym, realized, sold, avg, sell_px in evs_all:
        f["taxRows"].append({"sold": e["t"][:5], "sym": sym, "ticker": sym, "ex": "업비트", "qty": sold,
                             "acq": round(sold * avg, 2), "disp": round(sold * sell_px, 2), "fee": 0})
    f["plans"] = {"g103": {"target": 1.6, "stop": 0.85, "src": "CEX", "venue": "업비트 AERO/KRW", "tags": ["스윙"],
                           "memo": "데모 메모 — 1.6 도달 시 절반 정리"}}

    for r in f["taxRows"]:
        f["realizedByDate"][r["sold"]] = round(f["realizedByDate"].get(r["sold"], 0) + r["disp"] - r["acq"], 2)
    total_now = (sum(c["qty"] * c["price"] for c in coins) + sum(s["qty"] for s in f["stables"])
                 + f["fiats"][0]["krw"] / f["rate"] + _LP_VALUE + _LP_FEES)
    paths = _px_paths(now)
    wd = round(total_now * 0.05, 2)
    fixed = sum(s["qty"] for s in f["stables"]) + f["fiats"][0]["krw"] / f["rate"] + _LP_VALUE + _LP_FEES
    qty_of = {c["sym"]: c["qty"] for c in coins if c.get("price")}

    def val_at(i, k):
        return sum(q * paths[s][i] for s, q in qty_of.items()) + fixed + (wd if k > 20 else 0.0)
    series = []
    for k in range(29, -1, -1):
        day = now - timedelta(days=k)
        i = 29 - k
        val = total_now if k == 0 else val_at(i, k)
        usdt = 1360 + rnd.randint(0, 40)
        kimp = round(rnd.uniform(0.2, 2.6), 2)
        row = {"date": _mmdd(day), "dow": DOW[day.weekday()], "val": round(val, 2), "usdt": usdt, "kimp": kimp,
               "flow": -wd if k == 20 else 0.0}
        if i:
            row["att"] = _att(qty_of, paths, i, val - series[-1]["val"], row["flow"])
        series.append(row)
        f["usdtByDate"][_mmdd(day)] = {"usdt": usdt, "kimp": kimp}
    f["dailySeries"] = series
    f["todayByCoin"] = {s.upper(): [round((paths[s][29] / paths[s][28] - 1) * 100, 2), round(q * (paths[s][29] - paths[s][28]), 2)]
                        for s, q in qty_of.items() if paths[s][28] > 0}
    f["spark7"] = {s.upper(): [round(p, 10) for p in paths[s][23:30]] for s in qty_of}
    f["realizedMonth"] = 0.0
    d["realizedMonth"] = round(sum(v for k, v in f["realizedByDate"].items() if k[:2] == now.strftime("%m")), 2)
    for k in range(1, 6):
        day = _mmdd(now - timedelta(days=k))
        f["reviews"][day] = {"s": rnd.choice(["양호", "주의", "보통"]), "note": "데모 리뷰 — 합성 데이터입니다.",
                             "sum": "보유 비중 변화 없이 소액 분할 매수 2건, 업비트에서 1건 매도했다.",
                             "obs": ["매수 2건 모두 계획가 범위 안", "스테이블 비중 28% 유지"], "next": "목표가 도달 종목 절반 정리"}
    f["gasByChain"] = [{"chain": "Ethereum", "spot": 184.2, "lp": 0, "tx": 64}, {"chain": "Base", "spot": 21.7, "lp": 3.1, "tx": 212},
                       {"chain": "Arbitrum", "spot": 9.4, "lp": 0, "tx": 88}, {"chain": "Solana", "spot": 4.8, "lp": 0, "tx": 310}]
    for k in range(4):
        ym = (now.replace(day=1) - timedelta(days=28 * k)).strftime("%Y-%m")
        f["gasByMonth"][ym] = [{"chain": "Ethereum", "spot": round(184.2 / 4, 2), "tx": 16},
                               {"chain": "Base", "spot": round(21.7 / 4, 2), "tx": 53}]
    f["pendings"] = [
        {"key": "p1", "t": (now - timedelta(days=2)).strftime("%m-%d %H:%M"), "kind": "원가미상 보유 (폴백 OFF · 손익 제외(평가 포함))",
         "sym": "DEGEN", "chain": "Base", "qty": 52000.0, "usd": 353.6, "onchain": "52,000 DEGEN · 평가 $354", "ex": "—",
         "gap": "매수 기록 없는 유입", "why": "외부에서 받은 토큰이라 원가를 알 수 없어요. 원가를 지정하거나 평균가 대체를 켜세요.", "cands": []},
        {"key": "p2", "t": (now - timedelta(days=5)).strftime("%m-%d %H:%M"), "kind": "외부 전송 확인", "sym": "USDC",
         "chain": "Arbitrum", "onchain": "2,000 USDC → " + _short(demo_evm(77)), "ex": "—", "gap": "미등록 주소로 전송",
         "why": "본인 지갑이면 설정에서 지갑으로 등록하세요.", "cands": []},
        {"key": "risk:g141", "t": (now - timedelta(days=1)).strftime("%m-%d %H:%M"), "kind": "스팸·에어드랍 의심", "sym": "CLAIM",
         "chain": "Base", "qty": 1000.0, "onchain": "1,000 CLAIM · 평가 $0.00 표시 제외", "ex": "—", "gap": "실매수 이력 없는 에어드랍 유입",
         "why": "실매수·스왑 이력이 없는 유입분이라 목록에서 제외했습니다.", "cands": []},
        {"key": "unv:154", "t": _mmdd(wt_sold), "kind": "원가미상 매도 검토", "sym": "WEN", "chain": "—",
         "onchain": f"{wt_q:,.4f} WEN 매도 · 정산 ${wt_q * wt_out:,.2f}", "ex": "—",
         "gap": "1건 · 실매수 기록 없는 유입분 · 최초 인식 시가 시세 대기(받으면 자동 반영)", "fsHold": "wait",
         "why": "매수 기록이 없는 유입분의 매도라 실현손익에서 제외했습니다. 원가 지정 또는 이체·에어드랍 확인이 필요합니다.",
         "gkey": "g154", "costOv": None, "qty": wt_q, "usd": round(wt_q * wt_out, 2), "cands": [], "candsHint": ""}]
    f["extraEvents"] = [{"t": (now - timedelta(days=3)).strftime("%m-%d %H:%M"), "sym": "USDC", "k": "전송",
                         "d": "메인 → 업비트 입금", "q": "3,000", "a": "$3,000", "tx": _tx("x1"), "src": "ex:upbit",
                         "_ts": int((now - timedelta(days=3)).timestamp())}]
    f["lps"] = [{"key": "lp:base:demo:1", "id": "1", "chain": "Base", "chainKey": "base", "proto": "uni_v3", "dex": "Uniswap v3",
                 "opened": _mmdd(now - timedelta(days=30)), "last": _mmdd(now - timedelta(days=2)), "closed": False,
                 "deposit": 12000, "principal": 12000, "realized": 0, "units": {},
                 "onchain": {"sym0": "WETH", "sym1": "USDC", "amount0": 1.42, "amount1": 6420, "fees0": 0.012, "fees1": 41.3,
                             "price": 3920.0, "priceLower": 3500.0, "priceUpper": 4400.0, "inRange": True, "fee": 500, "liquidity": "1"},
                 "value": _LP_VALUE, "fees": _LP_FEES, "pool": "WETH / USDC"}]
    f["lpEvents"] = [{"t": (now - timedelta(days=30)).strftime("%m-%d %H:%M"), "_ts": int((now - timedelta(days=30)).timestamp()),
                      "lp": "lp:base:demo:1", "sym": "WETH / USDC", "k": "유동성 예치", "d": "Base · Uniswap v3 0.05% · 범위 3,500–4,400",
                      "q": "1.5 WETH + 6,100 USDC", "a": "$12,000", "tx": _tx("lp1"), "src": None}]
    krw0 = total_now * f["rate"]
    f["krwFlows"] = {"rows": [{"dir": "in", "ex": "업비트", "st": "done", "amt": round(krw0 * w9, -4), "t": int((now - timedelta(days=d9)).timestamp())}
                              for w9, d9 in ((0.42, 330), (0.21, 210), (0.12, 120), (0.08, 45))]
                     + [{"dir": "out", "ex": "업비트", "st": "done", "amt": round(krw0 * 0.05, -4), "t": int((now - timedelta(days=20)).timestamp())}]}
    f["futures"].update(fut_state(now))
    f["outflows"] = _outflows(now)
    return d


_VOL = {"ETH": 0.024, "SOL": 0.034, "BNB": 0.018, "LINK": 0.03, "DEGEN": 0.06}


def _px_paths(now=None) -> dict:
    rnd = random.Random(1008)
    out = {}
    for sym, _ch, px, _q, _a in _COINS + [("DEGEN", "base", 0.0068, 52000.0, 0)]:
        lr = [0.0]
        for _ in range(29):
            lr.append(lr[-1] + rnd.gauss(0.0045, _VOL.get(sym, 0.045)))
        out[sym] = [px * math.exp(x - lr[-1]) for x in lr]
    return out


def _att(qty_of, paths, i, dv, flow) -> dict:
    by = {s: q * (paths[s][i] - paths[s][i - 1]) for s, q in qty_of.items()}
    mv = sorted(((s, v) for s, v in by.items() if abs(v) >= 0.005), key=lambda kv: (-abs(kv[1]), kv[0]))
    top = [[s, round((paths[s][i] / paths[s][i - 1] - 1) * 100, 2), round(v, 2)] for s, v in mv[:5]]
    rest = mv[5:]
    mk = sum(by.values())
    return {"mk": round(mk, 2), "top": top, "etc": [len(rest), round(sum(v for _s, v in rest), 2)], "kx": 0.0, "tr": 0.0, "fee": 0.0,
            "lp": 0.0, "xo": 0.0, "rs": round(dv - mk - flow, 2)}


def att_detail(d_from, d_to) -> dict:
    d = build()
    f = d["fields"]
    now = datetime.now(KST)
    paths = _px_paths(now)
    qty_of = {c["sym"]: c["qty"] for c in f["coins"] if c.get("price")}
    ser = f["dailySeries"]
    days = {}
    for i, r in enumerate(ser):
        if not i or not r.get("att"):
            continue
        iso = (now - timedelta(days=len(ser) - 1 - i)).strftime("%Y-%m-%d")
        if not (str(d_from) <= iso <= str(d_to)):
            continue
        mk = []
        for s, q in qty_of.items():
            p0, p1 = paths[s][i - 1], paths[s][i]
            v = q * (p1 - p0)
            if abs(v) >= 0.005 and p0 > 0:
                mk.append([s.upper(), round(v, 2), round((p1 / p0 - 1) * 100, 2), q, float("%.8g" % p0), float("%.8g" % p1)])
        mk.sort(key=lambda x: (-abs(x[1]), x[0]))
        fl = [["원화 출금(은행으로)", round(float(r["flow"]), 2), []]] if abs(float(r.get("flow") or 0)) >= 0.005 else []
        days[iso] = {"mk": mk, "mkN": len(mk), "xm": [], "kx": [0.0, 0.0, 0.0], "unp": [], "un": [], "op": [], "fb": [], "fl": fl}
    return {"ok": True, "builtAt": d.get("builtAt"), "days": days}


FUT_RATE = 1385.0
FUT_EXN = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX"}


def _ms(day, h, mi, s=0, ms=0) -> int:
    return int(day.replace(hour=h, minute=mi, second=s, microsecond=0).timestamp() * 1000) + ms


def fut_fixture(now=None):
    import fut_rcpt
    now = now or datetime.now(KST)
    d0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    d1, d4, d9 = d0 - timedelta(days=1), d0 - timedelta(days=4), d0 - timedelta(days=9)
    trades, ev = [], []

    def bt(sym, tid, oid, side, px, q, pnl, t, fee):
        trades.append({"symbol": sym, "id": tid, "orderId": oid, "side": side, "positionSide": "BOTH", "price": f"{px}", "qty": f"{q}",
                       "realizedPnl": f"{pnl}", "time": t})
        ts = t // 1000 * 1000
        if pnl:
            ev.append({"t": ts, "symbol": sym, "kind": "REALIZED", "amount": pnl, "uid": f"bn:{tid}1:REALIZED_PNL:{ts}", "ex": "binance"})
        ev.append({"t": ts, "symbol": sym, "kind": "FEE", "amount": fee, "uid": f"bn:{tid}2:COMMISSION:{ts}", "ex": "binance"})
    bt("ETHUSDT", 51001, 81001, "BUY", 3850.0, 1.2, 0, _ms(d1, 9, 12, 5, 312), -1.848)
    bt("ETHUSDT", 51002, 81002, "BUY", 3862.5, 0.8, 0, _ms(d1, 9, 31, 40, 118), -1.236)
    bt("ETHUSDT", 51003, 81003, "SELL", 3905.4, 1.0, 50.4, _ms(d1, 11, 47, 22, 904), -1.5622)
    bt("ETHUSDT", 51004, 81004, "SELL", 3921.1, 1.0, 66.1, _ms(d1, 13, 52, 10, 450), -1.5684)
    bt("SOLUSDT", 52001, 82001, "BUY", 210.0, 10, 0, _ms(d1, 0, 40, 12, 200), -0.84)
    bt("SOLUSDT", 52002, 82002, "SELL", 214.0, 15, 40.0, _ms(d1, 14, 20, 33, 250), -1.284)
    bt("SOLUSDT", 52003, 82003, "BUY", 211.5, 5, 12.5, _ms(d1, 15, 40, 10, 700), -0.423)
    for h9, a9 in ((1, -0.42), (9, -0.38)):
        t9 = _ms(d1, h9, 0)
        ev.append({"t": t9, "symbol": "SOLUSDT", "kind": "FUNDING", "amount": a9, "uid": f"bn:5300{h9}:FUNDING_FEE:{t9}", "ex": "binance"})
    t9 = _ms(d4, 21, 3, 44)
    ev += [{"t": t9, "symbol": "BTCUSDT", "kind": "REALIZED", "amount": -25.4, "uid": f"bn:54001:REALIZED_PNL:{t9}", "ex": "binance"},
           {"t": t9, "symbol": "BTCUSDT", "kind": "FEE", "amount": -1.27, "uid": f"bn:54002:COMMISSION:{t9}", "ex": "binance"}]
    bt("ETHUSDT", 50901, 80901, "BUY", 3700.0, 0.6, 0, _ms(d9, 8, 5), -0.888)
    bt("ETHUSDT", 50902, 80902, "SELL", 3846.7, 0.6, 88.02, _ms(d9, 19, 44, 31, 555), -0.9232)
    items = []

    def bb(oid, sym, side, q, ep, xp, of, cf, lev, t):
        sg = 1 if side == "Sell" else -1
        pnl = round((xp - ep) * q * sg - of - cf, 4)
        items.append({"symbol": sym, "orderId": oid, "side": side, "qty": f"{q}", "closedSize": f"{q}", "avgEntryPrice": f"{ep}", "avgExitPrice": f"{xp}",
                      "closedPnl": f"{pnl}", "openFee": f"{of}", "closeFee": f"{cf}", "leverage": lev, "updatedTime": f"{t}", "execType": "Trade"})
        ev.append({"t": t, "symbol": sym, "kind": "REALIZED", "amount": pnl, "uid": f"bb:{oid}:{t}", "ex": "bybit"})
    bb("dm-bb-0001", "BTCUSDT", "Buy", 0.05, 64250.0, 63810.0, 1.6063, 1.5953, "5", _ms(d1, 12, 15, 40, 210))
    bb("dm-bb-0002", "ETHUSDT", "Sell", 0.5, 3890.0, 3871.2, 0.9725, 0.9678, "10", _ms(d1, 16, 5, 12, 480))
    bb("dm-bb-0003", "SOLUSDT", "Sell", 20, 205.1, 206.95, 2.051, 2.0695, "3", _ms(d4, 10, 22, 5))
    ev.sort(key=lambda r: (r["t"], r["uid"]))
    now_ms = int(now.timestamp() * 1000)
    px = {"binance": {"v": fut_rcpt.PX_V, "ts": now_ms // 1000, "cursor": {}, "rows": fut_rcpt.merge([], fut_rcpt.rows_binance(trades), now_ms)},
          "bybit": {"v": fut_rcpt.PX_V, "ts": now_ms // 1000, "cursor": {}, "rows": fut_rcpt.merge([], fut_rcpt.rows_bybit(items), now_ms)}}
    return ev, px


def fut_fev(ev) -> list:
    out = []
    for r in ev:
        t9, a9 = int(r["t"]), float(r["amount"])
        out.append((datetime.fromtimestamp(t9 / 1000, KST).strftime("%Y-%m-%d"), t9, a9, a9 * FUT_RATE, r))
    return out


def fut_by_date_ex(by_date_ex, exn) -> dict:
    out = {}
    for (dk9, ex9), v9 in by_date_ex.items():
        if abs(v9[0]) < 0.005:
            continue
        r9 = {"ex": exn.get(ex9, ex9), "exKey": ex9, "usd": round(v9[0], 2), "krw": round(v9[1]),
              "n": v9[2], "t": datetime.fromtimestamp(v9[3] / 1000, KST).strftime("%H:%M") if v9[3] else ""}
        if v9[3]:
            r9["ts"] = int(v9[3] // 1000)
        out.setdefault(dk9, []).append(r9)
    for l9 in out.values():
        l9.sort(key=lambda x: (-abs(x["usd"]), str(x["exKey"])))
    return out


def fut_state(now=None) -> dict:
    ev, _px = fut_fixture(now)
    by_date, by_krw, by_ex, rows = {}, {}, {}, []
    for dk9, t9, a9, k9, r9 in fut_fev(ev):
        by_date[dk9] = by_date.get(dk9, 0) + a9
        by_krw[dk9] = by_krw.get(dk9, 0) + k9
        x9 = by_ex.setdefault((dk9, r9["ex"]), [0.0, 0.0, 0, 0])
        x9[0] += a9
        x9[1] += k9
        x9[2] += 1 if r9["kind"] == "REALIZED" else 0
        x9[3] = max(x9[3], t9)
        if r9["kind"] == "REALIZED":
            rows.append({"t": datetime.fromtimestamp(t9 / 1000, KST).strftime("%m-%d %H:%M"), "_ts": t9, "sym": r9["symbol"],
                         "ex": FUT_EXN.get(r9["ex"], r9["ex"]), "pnl": round(a9, 4)})
    rows.sort(key=lambda x: -x["_ts"])
    brk = {"REALIZED": 0.0, "FUNDING": 0.0, "FEE": 0.0}
    for r9 in ev:
        brk[r9["kind"]] += r9["amount"]
    w9 = sum(1 for r in ev if r["kind"] == "REALIZED" and r["amount"] > 0)
    l9 = sum(1 for r in ev if r["kind"] == "REALIZED" and r["amount"] < 0)
    fsum = {}
    for x9 in rows:
        k9 = (datetime.fromtimestamp(x9["_ts"] / 1000, KST).strftime("%Y-%m"), x9["sym"], x9["ex"])
        a9 = fsum.setdefault(k9, [0, 0.0, 0.0])
        a9[0] += 1
        if x9["pnl"] > 0:
            a9[1] += x9["pnl"]
        else:
            a9[2] -= x9["pnl"]
    return {"realizedByDate": {k: round(v, 2) for k, v in by_date.items()}, "realizedKrwByDate": {k: round(v) for k, v in by_krw.items()},
            "realizedByDateEx": fut_by_date_ex(by_ex, FUT_EXN), "realizedRows": rows[:60], "realizedRowsTotal": len(rows),
            "realizedSummary": [[k[0], k[1], k[2], v[0], round(v[1], 4), round(v[2], 4)] for k, v in sorted(fsum.items())],
            "realizedTotal": round(sum(r["pnl"] for r in rows), 2),
            "pnlBreak": {"realized": round(brk["REALIZED"], 2), "funding": round(brk["FUNDING"], 2), "fee": round(brk["FEE"], 2),
                         "net": round(brk["REALIZED"] + brk["FUNDING"] + brk["FEE"], 2), "wins": w9, "losses": l9,
                         "winRate": round(w9 / (w9 + l9) * 100, 1) if (w9 + l9) else None}}


def fut_raw(now=None) -> dict:
    ev, _px = fut_fixture(now)
    t = int(time.time()) - 240
    out = {}
    for ex, bal in (("binance", 4820.5), ("bybit", 2310.0)):
        out[ex] = {"ts": t, "wallet": {"balance": bal}, "positions": [], "events": [{k: v for k, v in r.items() if k != "ex"} for r in ev if r["ex"] == ex]}
    return out


def _outflows(now) -> list:
    def row(addr, chains, toks, status, days, extra=None):
        ts = int((now - timedelta(days=days)).timestamp())
        txs = [{"ts": ts - 600 * j, "t": datetime.fromtimestamp(ts - 600 * j, KST).strftime("%Y-%m-%d %H:%M"), "chain": chains[0],
                "tx": "0x" + _hex(f"of:{addr}:{j}", 64), "sym": t["sym"], "qty": t["qty"], "usdAtSend": t.get("usdAtSend"), "costUsd": t.get("usdAtSend")}
               for j, t in enumerate(toks)]
        send = sum(t.get("usdAtSend") or 0 for t in toks)
        cur = sum(t["usdNow"] for t in toks)
        r = {"address": addr, "chains": chains, "chainNames": [CHAIN_NAME.get(c, c) for c in chains], "firstTs": ts - 600 * (len(toks) - 1), "lastTs": ts,
             "first": datetime.fromtimestamp(ts, KST).strftime("%Y-%m-%d"), "last": datetime.fromtimestamp(ts, KST).strftime("%Y-%m-%d"),
             "count": len(toks), "tokens": toks, "usdAtSend": round(send, 2), "usdNow": round(cur, 2), "costUsd": round(send, 2), "usdAtSendKnown": True,
             "dust": False, "status": status, "verdict": None, "retOk": False, "applyWait": False, "category": None, "memo": None, "alias": None,
             "links": [], "linkRefundUsd": 0, "linkTokenUsd": 0, "saleWait": None, "excludeLegs": [], "candN": None, "candTop": [], "linkPaidUsd": None,
             "exchange": None, "decidedTs": None, "hints": [], "flags": [], "autoMatch": None, "noAuto": False, "bridge": None, "arrivals": [], "arrivalsN": 0,
             "suggest": None, "suggestions": [], "returned": [], "returnedN": 0, "returnedUsd": 0, "returnKind": None, "netUsd": round(send, 2), "matchedUsd": 0,
             "priorIn": {"n": 0, "usd": 0}, "txs": txs, "txsCut": 0, "phantomTxN": 0}
        r.update(extra or {})
        return r
    usdc = lambda q: {"sym": "USDC", "qty": q, "usdAtSend": q, "usdNow": q, "costUsd": q, "unknownCostQty": 0}
    ex9 = row(demo_evm(90), ["eth"], [usdc(3000.0)], "exchange_matched", 3,
              {"exchange": "업비트", "autoMatch": {"basis": ["txid"], "matched": 1, "of": 1, "exchange": "업비트"}, "matchedUsd": 3000.0,
               "hints": [{"kind": "exchange_txid", "chip": "업비트 입금 자동 매칭 · 1/1건", "label": "업비트 입금으로 자동 매칭(근거: txid 일치) · 1/1건 · 원가 이관됨"}]})
    ex9["txs"][0]["match"] = {"basis": "txid", "exchange": "업비트"}
    return [row(demo_evm(77), ["arbitrum"], [usdc(2000.0)], "pending", 5),
            ex9,
            row(demo_evm(78), ["base"], [{"sym": "ETH", "qty": 0.5, "usdAtSend": 1850.0, "usdNow": 1960.0, "costUsd": 1655.0, "unknownCostQty": 0}],
                "external", 12, {"verdict": "external", "memo": "데모 — 다른 사람에게 보낸 돈(합성)", "decidedTs": int((now - timedelta(days=11)).timestamp())})]


def depaddr_status() -> dict:
    now = int(time.time())
    rows = {"upbit": (38, 2, 3 * 3600), "binance": (126, 5, 5 * 3600), "okx": (97, 4, 7 * 3600),
            "bybit": (41, 3, 2 * 3600), "bithumb": (64, 2, 9 * 3600)}
    out = {}
    for ex, (n, nadr, ago) in rows.items():
        out[ex] = {"count": n, "addresses": max(nadr, n // 3), "currencies": max(1, n * 2 // 3), "current": n - 4,
                   "fromHistory": n // 4, "lastRefresh": now - ago, "lastFull": now - ago, "lastError": None,
                   "lastAttempt": now - ago, "running": False, "requested": False, "nextTry": None}
    return out


_EXTRA = {"day": None, "idx": None, "daily": None}


def _extra_key():
    return datetime.now(KST).strftime("%Y-%m-%d")


_HAB_HOURS = (10, 10, 11, 11, 11, 14, 15, 22, 22, 23, 23)


def day_idx() -> dict:
    k = _extra_key()
    if _EXTRA["day"] == k and _EXTRA["idx"] is not None:
        return _EXTRA["idx"]
    rnd = random.Random(1006)
    now = datetime.now(KST)
    pos, tax, ix = [], [], {}
    for i, (sym, ch, px, _q, avg) in enumerate(_COINS):
        for j in range(rnd.randint(2, 4)):
            start = now - timedelta(days=rnd.randint(20, 360), hours=rnd.randint(0, 23))
            key = f"g{100 + i}f{j + 1}"
            rbd = {}
            for _s in range(rnd.randint(1, 5)):
                hold_h = rnd.choice([3, 10, 30, 46, 80, 200, 500, 1500, 3000])
                t = start + timedelta(hours=hold_h + rnd.randint(0, 48))
                hh = _HAB_HOURS[rnd.randrange(len(_HAB_HOURS))] if rnd.random() < 0.75 else t.hour
                t += timedelta(hours=(hh - t.hour) % 24)
                if t >= now - timedelta(hours=1):
                    continue
                hr = t.hour
                edge = -0.25 if hr >= 20 or hr < 2 else 0.12 if 9 <= hr < 13 else 0.0
                r = rnd.uniform(-0.18, 0.32) + edge
                qty = round(rnd.uniform(200, 4000) / max(px, 0.01), 6)
                cost = qty * avg
                disp = cost * (1 + r)
                iso = t.strftime("%Y-%m-%d")
                rbd[iso] = round(rbd.get(iso, 0.0) + (disp - cost), 2)
                tax.append({"sold": iso, "sym": sym, "ticker": sym, "ex": "업비트", "qty": qty, "acq": round(cost, 2), "disp": round(disp, 2), "fee": 0})
                ix.setdefault(iso, []).append((int(t.timestamp()), "pos", {"k": "거래소 매도", "a": f"${disp:,.2f}", "sym": sym}, (key, sym, CHAIN_NAME[ch])))
            if rbd:
                pos.append({"key": key, "sym": sym, "_ots": int(start.timestamp()), "realizedByDay": rbd, "kind": None})
    t9 = now - timedelta(days=12)
    pos.append({"key": "s1", "sym": "USDT", "kind": "stable", "_ots": int((t9 - timedelta(days=30)).timestamp()), "realizedByDay": {t9.strftime("%Y-%m-%d"): 4.2}})
    _EXTRA.update(day=k, idx={"builtAt": _day_built(), "pos": pos, "tax": tax, "ix": ix})
    return _EXTRA["idx"]


def daily_freeze() -> dict:
    k = _extra_key()
    if _EXTRA.get("dday") == k and _EXTRA["daily"] is not None:
        return _EXTRA["daily"]
    d = build()
    f = d["fields"]
    now = datetime.now(KST)
    coins = [c for c in f["coins"] if c.get("price")]
    paths = _px_paths(now)
    out = {}
    ser = f["dailySeries"]
    for i, r in enumerate(ser):
        day = now - timedelta(days=len(ser) - 1 - i)
        iso = day.strftime("%Y-%m-%d")
        if iso >= now.strftime("%Y-%m-%d"):
            continue
        j = 29 - (len(ser) - 1 - i)
        pd = {c["key"][1:]: paths[c["sym"]][j] for c in coins}
        g = {c["key"][1:]: round(c["qty"] * pd[c["key"][1:]], 2) for c in coins}
        for s9 in f["stables"]:
            g[s9["key"][1:]] = round(s9["qty"], 2)
        out[iso] = {"g": g, "val": float(r["val"]), "x": round(float(r["val"]) - sum(g.values()), 2), "usdt": r.get("usdt"),
                    "px": {"p": {k9: round(v9, 10) for k9, v9 in pd.items()}},
                    "sym": dict({c["key"][1:]: c["sym"] for c in coins}, **{s9["key"][1:]: s9["sym"] for s9 in f["stables"]})}
    _EXTRA.update(dday=k, daily=out)
    return out


class DemoHist:

    def __init__(self):
        f = build()["fields"]
        g = {c["key"][1:]: {"sym": c["sym"], "ov": c["price"]} for c in f["coins"] if c.get("price")}
        g.update({s9["key"][1:]: {"sym": s9["sym"], "st": True} for s9 in f["stables"]})
        self.kit = {"groups": g}
        self.st = {"d": {}, "f": {}, "meta": {}}
        self.px = {"specs": {}}

    def _clean(self, sp, specs):
        return sp


def ledger():
    import sqlite3
    f = build()["fields"]
    now = datetime.now(KST)
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.executescript("""
    CREATE TABLE asset_groups (group_id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, norm_decimals INTEGER NOT NULL DEFAULT 18);
    CREATE TABLE assets (asset_id INTEGER PRIMARY KEY, kind TEXT, chain TEXT, address TEXT, symbol TEXT, decimals INTEGER, confirmed INTEGER DEFAULT 0, hidden INTEGER DEFAULT 0, group_id INTEGER);
    CREATE TABLE postings (posting_id INTEGER PRIMARY KEY AUTOINCREMENT, source_kind TEXT, source_ns TEXT, source_id TEXT, leg_seq INTEGER, event_ts INTEGER NOT NULL,
      asset_id INTEGER NOT NULL, location TEXT NOT NULL, qty_base TEXT NOT NULL, cost_usd TEXT, cost_krw TEXT, leg_kind TEXT NOT NULL, event TEXT NOT NULL, classifier_ver INTEGER);
    """)
    rows, P = [], []
    for c9 in f["coins"]:
        gid = int(c9["key"][1:])
        rows.append((gid, c9["sym"]))
    rows += [(int(s9["key"][1:]), s9["sym"]) for s9 in f["stables"]]
    c.executemany("INSERT INTO asset_groups(group_id, name) VALUES (?, ?)", rows)
    c.executemany("INSERT INTO assets(asset_id, kind, chain, symbol, decimals, group_id) VALUES (?,?,?,?,?,?)", [(g9, "token", None, n9, 8, g9) for g9, n9 in rows])
    W1, W2 = demo_evm(1), demo_evm(2)

    def post(days, gid, loc, qty, leg, ev, tx):
        P.append((int((now - timedelta(days=days)).timestamp()), gid, loc, str(int(round(qty * 1e8))), leg, ev, tx))
    rnd = random.Random(7)
    for i, (sym, ch, px, qty, _avg) in enumerate(_COINS[:10]):
        gid = 100 + i
        q = qty * 0.75
        d0 = rnd.randint(60, 300)
        post(d0, gid, "exchange:upbit", q, "acq", "EX_BUY", f"b{i}")
        wloc = f"wallet:{ch}:{W2 if ch in ('base', 'polygon') else W1}"
        post(d0 - 1, gid, "exchange:upbit", -q, "move_out", "EX_WITHDRAW", f"w{i}")
        post(d0 - 1 - 0.02, gid, wloc, q * 0.999, "acq", "TRANSFER_IN", f"a{i}")
        if i in (1, 3):
            post(d0 - 20, gid, wloc, -q * 0.2, "move_out", "TRANSFER_OUT_EX", f"o{i}")
            post(d0 - 20 - 0.01, gid, "exchange:upbit", q * 0.2, "move_in", "EX_DEPOSIT", f"o{i}")
    post(90, 200, f"wallet:eth:{W1}", 5000, "acq", "TRANSFER_IN", "u1")
    post(80, 200, f"wallet:eth:{W1}", -5000, "move_out", "BRIDGE", "br1")
    post(80 - 0.01, 200, f"wallet:base:{W1}", 4995, "acq", "TRANSFER_IN", "br1a")
    c.executemany("INSERT INTO postings(event_ts, asset_id, location, qty_base, leg_kind, event, source_id, source_kind, source_ns, leg_seq, classifier_ver)"
                  " VALUES (?,?,?,?,?,?,?, 'demo', 'demo', 0, 1)", P)
    c.commit()
    return c


_DEMO_W = (("메인", "evm", 1, ("eth", "base", "arbitrum", "optimism", "bsc")), ("트레이딩", "evm", 2, ("base", "arbitrum", "polygon")),
           ("솔라나", "sol", 1, ("sol",)))


def demo_config() -> dict:
    import json
    import os
    import common
    try:
        with open(os.path.join(common.BASE_DIR, "config.example.json"), encoding="utf-8") as f9:
            ex = json.load(f9)
    except (OSError, ValueError):
        ex = {}
    cfg = {k: ex[k] for k in ("chains", "bsc", "sol", "evm_poll_sec", "backfill_months") if k in ex}
    cfg.setdefault("chains", {c: {} for c in ("eth", "base", "arbitrum", "optimism", "polygon")})
    ws = []
    for lab, kind, i, chs in _DEMO_W:
        for c in chs:
            if kind == "sol":
                ws.append({"type": "sol", "address": demo_sol(i), "label": lab})
            else:
                ws.append({"type": "bsc_rpc" if c == "bsc" else "evm", "chain": c, "address": demo_evm(i), "label": lab})
    cfg["wallets"] = ws
    return cfg


def _wkey(kind, i):
    return demo_sol(i) if kind == "sol" else demo_evm(i).lower()


def _tier_books(now: float):
    import addr_tier
    poll = {"eth": 45, "arbitrum": 45, "optimism": 45, "polygon": 45, "sol": 60}
    path = {"eth": "etherscan", "arbitrum": "etherscan", "polygon": "etherscan", "optimism": "blockscout", "sol": "helius"}
    pairs = [("eth", "evm", 1, 0, None, None, False, 2), ("arbitrum", "evm", 1, 0, None, None, False, 4), ("arbitrum", "evm", 2, 1, None, None, False, 70),
             ("optimism", "evm", 1, 1, None, None, False, 150), ("polygon", "evm", 2, 0, None, "extend", False, 1), ("sol", "sol", 1, 0, None, None, False, 1)]
    addrs, sums = {}, {}
    for sc, kind, i, t, h, fill, empty, sent_d in pairs:
        iv = None if t == 0 else addr_tier.ACT_MAX_SEC
        full = now - rnd_off(sc, i)
        addrs.setdefault(_wkey(kind, i), []).append({"c": sc, "t": t, "h": h, "full": int(full), "sent": int(now - sent_d * 86400),
                                                     "nextAct": int(full + iv) if iv else None, "nextFull": int(full + addr_tier.BACKSTOP_MAX_SEC) if iv else None,
                                                     "wake": False, "f": fill, "e": empty})
        s9 = sums.setdefault(sc, {"scope": sc, "path": path[sc], "safe": True, "active": True, "tiers": [0] * len(addr_tier.TIER_LABELS), "holds": {}, "fullPerDay": 0.0,
                                  "actPerDay": 0.0, "stretch": 1.0, "gate": False, "basePoll": poll[sc], "pairs": 0, "period": poll[sc], "t0": 0,
                                  "filling": 0, "empty": 0, "lastCycle": {}})
        s9["tiers"][t] += 1
        s9["pairs"] += 1
        s9["t0"] += 1 if t == 0 else 0
        s9["filling"] += 1 if fill else 0
        s9["fullPerDay"] += 86400.0 / poll[sc] if t == 0 else 86400.0 / addr_tier.BACKSTOP_MAX_SEC + 0.5
        s9["actPerDay"] += 0.0 if t == 0 else 86400.0 / iv
    books = {}
    for sc, s9 in sums.items():
        s9["fullPerDay"] = round(s9["fullPerDay"], 1)
        s9["actPerDay"] = round(s9["actPerDay"], 1)
        if s9["path"] == "helius":
            s9["solCost"] = round(s9["fullPerDay"] * 1.2)
            s9["actPerDay"] = 0.0
        books[sc] = {"path": s9["path"], "summary": s9, "updatedAt": int(now - 40),
                     "perDay": s9.get("solCost") if s9["path"] == "helius" else round(s9["fullPerDay"] * addr_tier.per_check_calls(s9["path"], s9["path"] == "etherscan"))}
    return books, addrs


def chains_view(now=None) -> dict:
    import chainoff
    now = int(now or time.time())
    rnd = random.Random(108)
    nm = chainoff._names()
    cfg = demo_config()
    books, _addrs = _tier_books(now)
    by = {}
    for _lab, kind, i, chs in _DEMO_W:
        for c in chs:
            by.setdefault(c, []).append(_wkey(kind, i))

    def spark(n):
        sp = [0] * chainoff.SPARK_N
        for _ in range(n):
            sp[rnd.randrange(chainoff.SPARK_N)] += 1
        return sp
    plan = {
        "eth": ([184], 23, 61840.2, ""), "arbitrum": ([96, 41], 12, 31220.7, ""), "base": ([312, 77], 31, 46910.4, chainoff.RPC_ONLY_WHY),
        "optimism": ([6], 0, 64.3, ""), "polygon": ([3], 0, 4590.1, ""), "bsc": ([58], 4, 2898.0, chainoff.UNSUPPORTED["bsc"]),
        "sol": ([None], 18, 31790.5, chainoff.UNSUPPORTED["sol"])}
    rows = []
    for k, (nonces, sent, usd, why) in plan.items():
        ws = by.get(k) or []
        book = books.get(k) or {}
        sm = book.get("summary") or {}
        tiers = sm.get("tiers")
        known = [n for n in nonces if n is not None]
        rec = bool(not why and known and len(known) == len(nonces) and max(known) <= chainoff.NONCE_MAX and not sent and sm and not sm.get("filling"))
        rows.append({"key": k, "name": nm.get(k, k), "on": True, "can": not why, "why": why,
                     "lock": None if not why else ("sep" if k in chainoff.UNSUPPORTED else "rpc"), "auto": False,
                     "wallets": len(ws), "nonces": nonces, "maxNonce": max(known) if known else None, "unknown": len(nonces) - len(known),
                     "status": chainoff._status_of(book, len(ws)), "fill": int(sm.get("filling") or 0) if sm else None,
                     "rest": sum(int(x or 0) for x in tiers[1:]) if tiers else None, "pollSec": chainoff._poll_sec(k, cfg, cfg, book),
                     "calls": chainoff._calls_of(book, cfg), "sent30": sent, "spark": spark(sent), "usd": usd, "big": usd >= chainoff.BIG_USD,
                     "offAt": None, "autoOff": False, "autoNewDays": None, "recommend": rec})
    rows.append({"key": "gnosis", "name": nm.get("gnosis", "Gnosis"), "on": False, "can": True, "why": "", "lock": None, "auto": False,
                 "wallets": 1, "nonces": [0], "maxNonce": 0, "unknown": 0, "status": "off", "fill": None, "rest": None, "pollSec": None, "calls": None,
                 "sent30": 0, "spark": [0] * chainoff.SPARK_N, "usd": 0.0, "big": False, "offAt": now - 9 * 86400, "autoOff": True, "autoNewDays": None,
                 "recommend": False})
    on = [r for r in rows if r["on"]]
    rec = [r for r in rows if r["recommend"]]
    tot = [r["calls"]["perDay"] for r in on if r.get("calls")]
    return {"ok": True, "at": now, "rows": rows, "nOn": len(on), "nOff": len(rows) - len(on), "nRec": len(rec), "nWallets": len(_DEMO_W),
            "nonceMax": chainoff.NONCE_MAX, "bigUsd": chainoff.BIG_USD, "autoGraceDays": getattr(chainoff, "AUTO_GRACE_DAYS", 30),
            "sweptAt": now - 5 * 3600, "callsDay": sum(tot) if tot else None,
            "recCallsDay": sum(r["calls"]["perDay"] for r in rec if r.get("calls")) if rec and all(r.get("calls") for r in rec) else None,
            "pollSteps": None, "apply": {"runner": True, "mode": "runner", "evmRunner": True, "manual": chainoff.MANUAL, "units": list(chainoff.UNITS)}}


def tier_view(raw_path: str = "", now=None) -> dict:
    import addr_tier
    import settings_store as ss
    now = float(now or time.time())
    cfg = demo_config()
    out = addr_tier.web_view(cfg, now=now)
    books, addrs = _tier_books(now)
    scopes = {}
    for sc, b in books.items():
        s9 = b["summary"]
        scopes[sc] = {"path": b["path"], "safe": True, "safeNote": None, "gate": False, "stretch": 1.0, "boot": True, "tiers": s9["tiers"],
                      "updatedAt": b["updatedAt"], "stale": False, "pairs": s9["pairs"], "t0": s9["t0"], "period": s9["period"], "basePoll": s9["basePoll"],
                      "empty": 0, "filling": s9["filling"], "perDay": b["perDay"],
                      "prov": b["path"] if b["path"] in ("helius", "etherscan") else f"{b['path']}:{sc}"}
    budget = addr_tier.estimate([dict(b["summary"], lp=b["path"] == "etherscan") for b in books.values()], cfg)
    for v in budget.values():
        v["now"] = v["perDay"]
    es = dict(out.get("esToday") or {}, n=int((budget.get("etherscan") or {}).get("perDay", 0) * 0.42))
    out.update(scopes=scopes, addrs=addrs, budget=budget, esToday=es, at=int(now),
               cap={"max": ss.MAX_ADDRESSES, "batch": ss.MAX_BATCH, "n": len(_DEMO_W)})
    return out


def rnd_off(sc, i) -> int:
    return 60 + (int(_hex(f"tier:{sc}:{i}", 6), 16) % 3000)


def coverage(now=None) -> dict:
    import sqlite3
    import coverage_limits
    now = int(now or time.time())
    c = sqlite3.connect(":memory:")
    try:
        c.executescript("CREATE TABLE wallets (chain TEXT, address TEXT, label TEXT);"
                        "CREATE TABLE postings (location TEXT, event_ts INTEGER, leg_kind TEXT);")
        for lab, kind, i, chs in _DEMO_W:
            for ch in chs:
                a = demo_sol(i) if kind == "sol" else demo_evm(i).lower()
                c.execute("INSERT INTO wallets VALUES (?,?,?)", (ch, a, lab))
                c.execute("INSERT INTO postings VALUES (?,?,?)", (f"wallet:{ch}:{a}", now - (120 + 7 * i) * 86400, "acq"))
        c.execute("INSERT INTO postings VALUES ('wallet:eth:x', ?, 'opening')", (now - 150 * 86400,))
        c.commit()
        return coverage_limits.build(now=now, conn=c)
    finally:
        c.close()


def fut_candles(out: dict) -> dict:
    import candles
    w = out["window"]
    iv = out.get("ivUse") or out.get("iv") or "5m"
    step = int(candles.IV_SEC.get(iv, 300))
    pts = sorted((float(m["ts"]), float(m["px"])) for m in out.get("marks") or () if m.get("px"))
    if not pts:
        pts = [(float(w["from"]), {"BTC": 64000.0, "ETH": 3880.0, "SOL": 210.0}.get(str(out.get("sym")), 100.0))]

    def at(t):
        if t <= pts[0][0]:
            return pts[0][1]
        for (t0, p0), (t1, p1) in zip(pts, pts[1:]):
            if t0 <= t <= t1:
                return p0 + (p1 - p0) * ((t - t0) / (t1 - t0) if t1 > t0 else 1.0)
        return pts[-1][1]
    cs, t, prev = [], int(w["from"]), None
    while t <= int(w["to"]):
        c = at(t + step) * (1 + 0.0011 * math.sin(t / 1700.0) + 0.0005 * math.sin(t / 290.0))
        o = c if prev is None else prev
        cs.append([t, round(o, 6), round(max(o, c) * 1.0006, 6), round(min(o, c) * 0.9994, 6), round(c, 6), round(40 + 30 * abs(math.sin(t / 1300.0)), 3)])
        prev, t = c, t + step
    out["chart"] = {"ok": True, "src": {"label": "합성 시세(데모)", "key": "demo:" + str(out.get("sym")), "venue": "demo", "iv": iv, "tag": "primary",
                                        "fallback": False}, "tried": [], "candles": cs, "complete": True, "volUnit": "coin", "why": None}
    for m in out.get("marks") or ():
        if not m.get("px") and cs:
            m["px"] = next((r[4] for r in reversed(cs) if r[0] <= m["ts"]), cs[0][4])
    return out
