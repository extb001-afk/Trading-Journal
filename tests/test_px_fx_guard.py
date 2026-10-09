#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import copy
import json
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import common

A = "0x" + "a1" * 20
json.dump({"chains": {}, "wallets": [{"type": "evm", "chain": "eth", "address": A, "label": "main"}], "backfill_months": 5},
          open(os.path.join(os.environ["TJ_BASE"], "config.json"), "w"))
import db as dbm
import netpace
import pricing
import web

chk = T.chk
for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker"):
    if hasattr(web.StateBuilder, _m):
        setattr(web.StateBuilder, _m, lambda self: None)
netpace.wait = lambda url, now=None, sleep=None: None
_sleep0 = pricing.time.sleep
CA = "0x" + "b7" * 20
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"


def ds(pairs):
    pricing._gj = lambda url, timeout=15: pairs
    pricing.time.sleep = lambda s: None
    try:
        return pricing.ds_token_prices("eth", [CA])
    finally:
        pricing.time.sleep = _sleep0


P_NOLIQ = {"chainId": "ethereum", "baseToken": {"address": CA, "symbol": "THN"}, "quoteToken": {"address": WETH}, "priceUsd": "12.5"}
P_LIQ = dict(P_NOLIQ, priceUsd="1.25", liquidity={"usd": 20000})
got = ds([P_NOLIQ])
chk(got == ({}, {}), "D1 유동성 필드 없는 페어(가격 12.5) = 빈 결과(가격·유동성 없음 — 미검증)", got)
got = ds([dict(P_NOLIQ, liquidity={"usd": 50000})])
chk(got == ({CA: 12.5}, {CA: 50000.0}), "D2 유동성 있는 페어 = 가격·유동성 그대로", got)
got = ds([P_NOLIQ, P_LIQ])
chk(got == ({CA: 1.25}, {CA: 20000.0}), "D3 유동성 없는 페어 + 있는 페어 = 있는 페어의 가격만(12.5 안 씀)", got)
got = ds([P_LIQ, P_NOLIQ])
chk(got == ({CA: 1.25}, {CA: 20000.0}), "D3 순서가 바뀌어도 같음", got)

K = f"eth:{CA}"


def spot(px=12.5, res=None, res_age=0, alt=None, src="gecko"):
    sp = web.Spot()
    now = time.time()
    sp.dex_usd = {K: px}
    sp.dex_ts = {K: int(now)}
    sp.dex_src = {K: src}
    sp.dex_res, sp.dex_res_ts = {}, {}
    if res is not None:
        sp.dex_res[K] = res
        sp.dex_res_ts[K] = int(now - res_age)
    sp.guarded, sp._guard_logged = {}, {}
    sp.dex_alt = {}
    for src, (p9, age9) in (alt or {}).items():
        sp._alt_note(K, src, p9, now - age9)
    return sp


sp = spot()
v = sp.dex_price("eth", CA)
chk(v == 0.0 and str(sp.guarded.get(K, "")).startswith("유동성 미상"), "S1 유동성 값 없음 = 0(평가불가) + 가드 사유 '유동성 미상'", (v, sp.guarded))
sp = spot(res=50_000)
chk(sp.dex_price("eth", CA) == 12.5 and K not in sp.guarded, "S2 유동성 충분($50k) = 가격 그대로", sp.guarded)
sp = spot(res=500)
chk(sp.dex_price("eth", CA) == 0.0 and sp.guarded.get(K, "").startswith("풀 유동성"), "S3 유동성 얇음($500) = 0(종전)", sp.guarded)
sp = spot(res=500, res_age=7 * 3600)
v = sp.dex_price("eth", CA)
chk(v == 0.0 and sp.guarded.get(K, "").startswith("풀 유동성") and "마지막 값" in sp.guarded.get(K, ""),
    "S4 유동성 값 6시간 지남 + 마지막 값 $500 < 기준 = 계속 0(종전: 조용히 풀려 12.5 채택)", (v, sp.guarded))
sp = spot(res=50_000, res_age=7 * 3600)
v = sp.dex_price("eth", CA)
chk(v == 0.0 and sp.guarded.get(K, "").startswith("유동성 미상"), "S5 마지막 값 $50k 라도 6시간 지나면 미검증 0", (v, sp.guarded))
sp = spot(alt={"gecko": (12.5, 0), "okx": (12.0, 60)})
chk(sp.dex_price("eth", CA) == 12.5, "S6 유동성 모름 + OKX DEX 값(12.0)과 게코 값(12.5) 10% 안 = 인정", sp.guarded)
sp = spot(alt={"gecko": (12.5, 0), "okx": (6.0, 60)})
chk(sp.dex_price("eth", CA) == 0.0, "S7 OKX 값(6.0)과 10% 밖 = 0", sp.guarded)
sp = spot(alt={"gecko": (12.5, 0), "dexscreener": (12.5, 30)})
chk(sp.dex_price("eth", CA) == 0.0, "S8 게코·덱스스크리너끼리만 같음(같은 풀을 읽음) = 확인 아님 → 0", sp.guarded)
sp = spot(alt={"gecko": (12.5, 0), "okx": (12.5, 7 * 3600)})
chk(sp.dex_price("eth", CA) == 0.0, "S9 OKX 값이 인정 기간(6시간) 밖 = 0", sp.guarded)
sp = spot()
sp.dex_price("eth", CA)
sp.dex_res[K], sp.dex_res_ts[K] = 50_000, int(time.time())
v = sp.dex_price("eth", CA)
chk(v == 12.5 and K not in sp.guarded, "S10 유동성이 다시 들어오면(≥ 기준) 가드 풀림 · 사유 지움", (v, sp.guarded))
sp = spot(px=100.0, alt={"okx": (1.0, 60), "dexscreener": (1.0, 30), "gecko": (100.0, 0)})
v = sp.dex_price("eth", CA)
chk(v == 0.0 and sp.guarded.get(K, "").startswith("유동성 미상"), "S11 옛 OKX·덱스스크리너 $1 일치 + 지금 게코 $100(유동성 모름) = 0(지금 값이 OKX 와 10% 밖)", (v, sp.guarded))
sp = spot(px=12.0, src="okx", alt={"okx": (12.0, 0), "gecko": (12.5, 60)})
chk(sp.dex_price("eth", CA) == 12.0, "S12 지금 값이 OKX(12.0) + 게코 12.5 가 10% 안 = 인정", sp.guarded)
sp = spot(px=12.0, src="okx", alt={"okx": (12.0, 0)})
chk(sp.dex_price("eth", CA) == 0.0, "S13 지금 값이 OKX 뿐(다른 출처 없음) = 0", sp.guarded)
sp = spot(px=12.0, src="okx", alt={"okx": (12.0, 0), "gecko": (100.0, 60)})
chk(sp.dex_price("eth", CA) == 0.0, "S14 지금 값 OKX 12.0 · 게코 100 = 0", sp.guarded)

NOW = int(time.time())
c = dbm.open_db(common.DB_PATH)
GID = {}


def token(sym, ca):
    c.execute("INSERT INTO asset_groups (name, norm_decimals) VALUES (?, 18)", (sym,))
    GID[sym] = c.execute("SELECT group_id FROM asset_groups WHERE name=?", (sym,)).fetchone()[0]
    c.execute("INSERT INTO assets (kind, chain, address, symbol, decimals, confirmed, group_id) VALUES ('token','eth',?,?,6,1,?)", (ca, sym, GID[sym]))
    return c.execute("SELECT last_insert_rowid()").fetchone()[0]


USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
AS = {"USDC": token("USDC", USDC), "THN": token("THN", CA)}
WL = f"wallet:eth:{A}"


def leg(h, t, sym, qty, usd, lk, ev, seq):
    c.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event,"
              " classifier_ver) VALUES ('chain_tx','eth',?,?,?,?,?,?,?,NULL,?,?,4)",
              (h, seq, t, AS[sym], WL, str(int(Decimal(str(qty)) * 10 ** 6)), None if usd is None else repr(float(usd)), lk, ev))


leg("0x" + "01" * 32, NOW - 20 * 86400, "USDC", 100_000, 100_000, "acq", "TRANSFER_IN", 0)
leg("0x" + "02" * 32, NOW - 10 * 86400, "THN", 1000, 10_000, "acq", "SWAP", 0)
leg("0x" + "02" * 32, NOW - 10 * 86400, "USDC", -10_000, 10_000, "disp", "SWAP", 1)
c.execute("INSERT INTO positions (group_id, location, qty_norm) VALUES (?,?,?)", (GID["THN"], WL, "1000"))
c.execute("INSERT INTO positions (group_id, location, qty_norm) VALUES (?,?,?)", (GID["USDC"], WL, "90000"))
c.commit()
c.close()
web.pricing.PxCache.candle_usd = lambda self, sym, ms: None
web.pricing._gj = lambda url, timeout=10.0: None
common.atomic_write_json(web.PREFS_PATH, {"plans": {}, "ignored": []})
open(os.path.join(common.STATE_DIR, "backfill_done"), "w").write("1")


def spot_file(rate=1380.0, rate_age=0, res=None, legacy=False):
    t = int(time.time())
    d = {"usd": {}, "usd_ts": {}, "rate": rate, "updated": t, "dex_usd": {K: 12.5}, "dex_ts": {K: t}, "dex_src": {K: "gecko"},
         "dex_res": {} if res is None else {K: res}, "dex_res_ts": {} if res is None else {K: t}, "fx_basis": 1370.0, "ex_usd": {}, "ex_ts": {}}
    if rate and not legacy:
        d["rate_ts"] = t - rate_age
    common.atomic_write_json(web.SPOT_PATH, d)


CAP = {}
_ds0 = web.StateBuilder._daily_series


def _ds_cap(self, *a, **kw):
    CAP["extra_rate"] = (kw.get("extra") or {}).get("rate", "없음")
    return _ds0(self, *a, **kw)


web.StateBuilder._daily_series = _ds_cap


def build(no_rate=False):
    b = web.StateBuilder()
    b.skip_gen_check = True
    if no_rate:
        b.spot.rate = 0
    conn = dbm.open_db(common.DB_PATH, readonly=True)
    try:
        f = b._build(conn)["fields"]
    finally:
        conn.close()
    return b, f


def thn(f):
    return next((r for r in f.get("coins") or [] if r.get("sym") == "THN"), None)


spot_file(res=None)
b, f = build()
r9 = thn(f)
tot_unv = f["dailySeries"][-1]["val"] if f.get("dailySeries") else None
pg = f.get("priceGuard") or {}
chk(r9 is not None and not r9.get("price") and K in pg and str(pg[K]).startswith("유동성 미상"),
    "B1 유동성 모르는 DEX 가격(12.5) 코인 = 보유 줄 가격 0 · 가격 이상 목록에 '유동성 미상'", (r9, pg))
spot_file(res=50_000)
b, f = build()
r9 = thn(f)
tot_ok = f["dailySeries"][-1]["val"] if f.get("dailySeries") else None
chk(r9 is not None and r9.get("price") == 12.5 and K not in (f.get("priceGuard") or {}), "B1 유동성 충분 = 가격 12.5 그대로", r9)
chk(tot_unv is not None and tot_ok is not None and abs((tot_ok - tot_unv) - 12_500) < 0.01,
    "B1 총자산 차이 = 1000개 × 12.5 = $12,500(미검증 가격은 합계에서 빠짐)", (tot_unv, tot_ok))

spot_file(res=50_000, rate_age=10)
sp = web.Spot()
chk(abs(sp.rate_ts - (time.time() - 10)) < 3 and sp.rate_state() == "live", "R1 spot.json rate_ts 복원 · 10초 전 = live", (sp.rate_ts, sp.rate_state()))
chk(sp.rate_state(time.time() + web.Spot.RATE_STALE_SEC + 5) == "stale", "R1 RATE_STALE_SEC 넘음 = stale")
sp.rate = 0
chk(sp.rate_state() == "none", "R1 환율 없음 = none")
spot_file(res=50_000, legacy=True)
sp = web.Spot()
chk(abs(sp.rate_ts - time.time()) < 3, "R1 옛 spot.json(rate_ts 없음) = 그 파일 updated 로 어림", sp.rate_ts)

spot_file(res=50_000, rate_age=10)
b, f = build()
chk(f.get("rateSrc") == "live" and abs(int(f.get("rateAt") or 0) - (NOW - 10)) < 120, "R2 신선 = rateSrc live · rateAt = 받은 시각", (f.get("rateSrc"), f.get("rateAt")))
chk(CAP.get("extra_rate") == 1380.0, "R3 원장 밖 금액 재료 extra.rate = 실제 환율", CAP.get("extra_rate"))
lv = b.daily.get("_live") or {}
chk(not lv.get("defer") and not lv.get("fxw") and not (lv.get("xv") or {}).get("fxs"), "R4 신선 = 오늘 스냅숏 유예 아님", {k: lv.get(k) for k in ("defer", "fxw")})
chk(abs(int(lv.get("fxt") or 0) - (NOW - 10)) < 120, "R4 스냅숏에 그 환율을 받은 시각 fxt", lv.get("fxt"))
spot_file(res=50_000, rate_age=2 * 3600)
b, f = build()
chk(f.get("rateSrc") == "stale" and f.get("rate") == 1380.0, "R2 2시간 갱신 안 됨 = rateSrc stale(마지막 값 그대로 표시)", (f.get("rateSrc"), f.get("rate")))
lv = b.daily.get("_live") or {}
chk(lv.get("defer") is True and lv.get("fxw") == 1 and (lv.get("xv") or {}).get("fxs") == 1,
    "R4 환율 낡음 = 오늘 마감 스냅숏 유예(defer) + 사유 fxw + xv fxs", {k: lv.get(k) for k in ("defer", "fxw", "xv")})
b, f = build(no_rate=True)
chk(f.get("rateSrc") == "fallback" and f.get("rateAt") is None, "R2 환율 없음 = fallback · rateAt 없음", (f.get("rateSrc"), f.get("rateAt")))
chk(CAP.get("extra_rate") is None, "R3 환율 없음 = extra.rate None(고정 대체값 1384 를 넘기지 않음)", CAP.get("extra_rate"))
lv = b.daily.get("_live") or {}
chk(lv.get("defer") is True and lv.get("fxw") == 1 and (lv.get("xv") or {}).get("fxd") == 1, "R4 환율 없음 = 유예 + fxw + xv fxd(종전 표식)",
    {k: lv.get(k) for k in ("defer", "fxw")})
web.StateBuilder._daily_series = _ds0

KST = timezone(timedelta(hours=9))
D27 = datetime(2026, 9, 27, tzinfo=KST)
D28 = datetime(2026, 9, 28, tzinfo=KST)
T_CLOSE = D27.replace(hour=23, minute=55).timestamp()
T_NEXT = D28.replace(minute=5).timestamp()
FX_MIN = 1400.0
FX_STALE = 1300.0


class FakeSpot:
    fx_basis = 1350.0

    def __init__(self, state):
        self.rate = FX_STALE
        self.state = state

    def price(self, sym):
        return None

    def rate_state(self, now=None):
        return self.state


class FakePx:
    def fx_at(self, ms):
        return FX_MIN

    def candle_usd(self, sym, ms):
        return None

    def flush(self):
        pass


def unit_builder(state):
    b = object.__new__(web.StateBuilder)
    b.daily = {"_v": web.DAILY_V}
    b.daily_px = {"_v": 1}
    b._daily_seed = {}
    b._upbit_krw_tl = None
    b.spot = FakeSpot(state)
    b.px = FakePx()
    return b


T0 = (D27 - timedelta(days=60)).timestamp()
G = {10: {"gid": 10, "sym": "TOK", "is_stable": False, "qty_timeline": [(T0, Decimal(100))]}}
HOLD = {10: Decimal(100)}
XV = {"v": web.XV_V, "p": {"ku": [1300000.0, "snap"], "rest": [0.0, "snap"]}, "fx": FX_STALE, "rt": {"upbit": 1}}
X = {"ub": 0.0, "fiat": 1000.0, "lp": 0.0, "ubs": {}, "ub_tl": {}, "krw_up": 1300000.0, "krw_other": 0.0, "rate": FX_STALE, "krw_up_tl": None}


def series(state):
    for p9 in (web.DAILY_PATH, web.DAILY_PX_PATH):
        if os.path.exists(p9):
            os.remove(p9)
    b = unit_builder(state)
    x1 = dict(copy.deepcopy(X), xv=dict(copy.deepcopy(XV), **({"fxs": 1} if state == "stale" else {})))
    b._daily_series(G, D27, {}, {10: 2.0}, ca_gids={10}, ex_gids=set(), skip_gids=set(), pending_gids=set(),
                    hold_qty=HOLD, extra=x1, extra_ok=True, now_ts=T_CLOSE)
    lv = copy.deepcopy(b.daily.get("_live") or {})
    b.spot.state = "live"
    x2 = dict(copy.deepcopy(X), rate=FX_MIN, fiat=round(1300000.0 / FX_MIN, 2), xv=dict(copy.deepcopy(XV), fx=FX_MIN))
    d = b._daily_series(G, D28, {}, {10: 2.0}, ca_gids={10}, ex_gids=set(), skip_gids=set(), pending_gids=set(),
                        hold_qty=HOLD, extra=x2, extra_ok=True, now_ts=T_NEXT)
    return lv, b.daily.get("2026-09-27") or {}, d


lv, c27, d = series("stale")
chk(lv.get("defer") is True and lv.get("fxw") == 1, "R5 낡은 환율의 마감 창 스냅숏 = 유예", {k: lv.get(k) for k in ("defer", "fxw", "usdt")})
chk(c27.get("src") != "live" and c27.get("usdt") == round(FX_MIN),
    "R5 다음 날 동결 = 낡은 환율 스냅숏으로 마감 안 함 → 그날 1분봉 환율로 계산 동결(usdt 1400 · 낡은 1300 아님)", {k: c27.get(k) for k in ("src", "usdt", "val", "x")})
chk(abs(float(c27.get("x") or 0) - 1300000.0 / FX_MIN) < 0.01, "R5 원장 밖 원화(₩1,300,000)도 그날 환율 1400 으로(낡은 1300 아님)", c27.get("x"))
lv, c27, d = series("live")
chk(not lv.get("defer") and c27.get("src") == "live" and c27.get("usdt") == FX_STALE,
    "R6 신선한 환율 = 종전대로 스냅숏 마감(src live · usdt = 그때 환율)", {k: c27.get(k) for k in ("src", "usdt")})

T.finish()
