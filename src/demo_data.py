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


def build() -> dict:
    rnd = random.Random(20260926)
    now = datetime.now(KST)
    d = _base()
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
    f["coins"] = coins
    f["unpricedSyms"] = []
    f["stables"] = [
        {"key": "g200", "sym": "USDC", "name": "USDC", "qty": 18250.0, "price": 1, "avg": 1,
         "locs": [{"w": "메인 지갑", "ch": "Base", "sub": "Base · " + _short(demo_evm(1)), "qty": 12250.0},
                  {"w": "솔라나 지갑", "ch": "Solana", "sub": "Solana · " + _short(demo_sol(1)), "qty": 6000.0}]},
        {"key": "g201", "sym": "USDT", "name": "USDT", "qty": 9400.0, "price": 1, "avg": 1,
         "locs": [{"w": "업비트", "sub": "거래소 잔고 (입금·체결 원장)", "qty": 9400.0}]}]
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
                          "fee": f"${rnd.uniform(0.4, 38):.2f}", "steps": steps, "events": events})
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
                          "steps": ["온체인 매수", "거래소 입금", "전량 매도"],
                          "events": [{"t": opened.strftime("%m-%d %H:%M"), "k": "온체인 매수", "d": f"{CHAIN_NAME[ch]} · 스왑",
                                      "q": f"{q:,.0f}", "a": f"${q * avg:,.0f}", "tx": _tx(sym, ch == "sol"), "src": None},
                                     {"t": closed.strftime("%m-%d %H:%M"), "k": "거래소 매도", "d": f"업비트 {sym}/KRW 체결",
                                      "q": f"{q:,.0f}", "a": f"${q * out:,.0f}", "tx": "—", "src": "ex:upbit"}]})
        f["taxRows"].append({"sold": _mmdd(closed), "sym": sym, "ticker": sym, "ex": "업비트", "qty": float(q),
                             "acq": round(q * avg, 2), "disp": round(q * out, 2), "fee": 0})
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
    walk = [1.0]
    for _ in range(29):
        walk.append(walk[-1] * (1 + rnd.uniform(-0.028, 0.034)))
    a0, a1 = math.log(0.86 / walk[0]), math.log(1.0 / walk[-1])
    vals = [total_now * w * math.exp(a0 + (a1 - a0) * i / 29) for i, w in enumerate(walk)]
    series = []
    for k in range(29, -1, -1):
        day = now - timedelta(days=k)
        val = vals[29 - k]
        usdt = 1360 + rnd.randint(0, 40)
        kimp = round(rnd.uniform(0.2, 2.6), 2)
        series.append({"date": _mmdd(day), "dow": DOW[day.weekday()], "val": round(val, 2), "usdt": usdt, "kimp": kimp})
        f["usdtByDate"][_mmdd(day)] = {"usdt": usdt, "kimp": kimp}
    f["dailySeries"] = series
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
         "sym": "DEGEN", "chain": "Base", "onchain": "52,000 DEGEN · 평가 $354", "ex": "—",
         "gap": "매수 기록 없는 유입", "why": "외부에서 받은 토큰이라 원가를 알 수 없습니다. 원가를 지정하거나 평균가 폴백을 켜세요.", "cands": []},
        {"key": "p2", "t": (now - timedelta(days=5)).strftime("%m-%d %H:%M"), "kind": "외부 전송 확인", "sym": "USDC",
         "chain": "Arbitrum", "onchain": "2,000 USDC → " + _short(demo_evm(77)), "ex": "—", "gap": "미등록 주소로 전송",
         "why": "본인 지갑이면 설정에서 지갑으로 등록하세요.", "cands": []},
        {"key": "risk:g141", "t": (now - timedelta(days=1)).strftime("%m-%d %H:%M"), "kind": "스팸·에어드랍 의심", "sym": "CLAIM",
         "chain": "Base", "onchain": "1,000 CLAIM · 평가 $0.00 표시 제외", "ex": "—", "gap": "실매수 이력 없는 에어드랍 유입",
         "why": "실매수·스왑 이력이 없는 유입분이라 목록에서 제외했습니다.", "cands": []}]
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
    fut = f["futures"]
    fut.update({"realizedRows": [{"t": (now - timedelta(days=k)).strftime("%m-%d %H:%M"), "_ts": int((now - timedelta(days=k)).timestamp() * 1000),
                                  "sym": "ETHUSDT", "ex": "바이낸스", "pnl": round(rnd.uniform(-120, 260), 2)} for k in (1, 4, 9)]})
    fut["realizedTotal"] = round(sum(r["pnl"] for r in fut["realizedRows"]), 2)
    for r in fut["realizedRows"]:
        fut["realizedByDate"][r["t"][:5]] = round(fut["realizedByDate"].get(r["t"][:5], 0) + r["pnl"], 2)
    return d


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
