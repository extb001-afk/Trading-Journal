#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import time  # noqa: E402
import urllib.error  # noqa: E402

import chain_registry  # noqa: E402
import pricing  # noqa: E402
import spamguard  # noqa: E402
import web  # noqa: E402

chk = T.chk
pricing.time.sleep = lambda s: None

BOOK = {"bn": {}, "bn_fail": False, "krw": {}}
pricing.usdt_krw_ask = lambda: 1400.0
pricing.fx_basis_krw_per_usd = lambda: 1390.0
pricing.upbit_markets = lambda: {"KRW": set(BOOK["krw"]), "BTC": {"GRAM"}, "USDT": {"GRAM"}}


def _bn():
    if BOOK["bn_fail"]:
        raise pricing.BulkError("binance", {"code": -1})
    return dict(BOOK["bn"])


pricing.binance_spot_usdt = _bn
pricing.upbit_spot_krw = lambda syms, dead=None, answered=None, seen=None: {s: BOOK["krw"][s] for s in syms if s in BOOK["krw"]}
web.Spot._upbit_alt_global = lambda self, syms, bn, now, **k: {}
web.Spot._gt_round = lambda self, now: None
web.Spot._ds_round = lambda self, now: None
web.Spot._okx_creds = lambda self: None


def tick(bn, krw=None, fail=False, want=("TON", "BTC", "GRAM")):
    BOOK.update(bn=bn, krw=dict(krw or {}), bn_fail=fail)
    sp = web.Spot()
    sp.usd, sp.usd_ts, sp.ex_usd, sp.ex_ts = {}, {}, {}, {}
    sp._mk_at = 0
    sp.want(list(want))
    sp.tick()
    return sp


sp = tick({"BTC": 100000.0, "GRAM": 2.5})
chk(sp.price("TON") == 2.5, "G1 바이낸스에 TON 없음 · GRAM 있음 = price('TON') = GRAM 값", sp.price("TON"))
sp = tick({"BTC": 100000.0, "TON": 5.0, "GRAM": 2.5})
chk(sp.price("TON") == 2.5, "G2 멈춘 옛 티커 TON 값이 섞여 있어도 = GRAM 값", sp.price("TON"))
sp = tick({}, krw={"TON": 1400.0, "BTC": 140_000_000.0}, fail=True)
chk(sp.price("TON") is None, "G3 바이낸스 실패 + 업비트 KRW-TON(옛 티커) = 글로벌 TON 시세로 안 씀", sp.price("TON"))
chk(sp.ex_usd.get("upbit:TON") == 1.0 and sp.price("BTC") == 100000.0, "G3 업비트 자체가 스탬프·업비트 원화 BTC 글로벌 = 종전 그대로",
    (sp.ex_usd.get("upbit:TON"), sp.price("BTC")))
sp = tick({"BTC": 100000.0, "GRAM": 2.5})
chk(sp.price("GRAM") == 2.5 and sp.price("BTC") == 100000.0, "G4 GRAM·BTC 심볼 시세 = 종전 그대로", (sp.price("GRAM"), sp.price("BTC")))

CALLS = []


def _minute_of(url):
    from datetime import datetime, timedelta
    to9 = datetime.strptime(url.split("to=")[1].split("&")[0], "%Y-%m-%dT%H:%M:%SZ")
    return (to9 - timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%S")


RENAMED_MS = 1_790_000_000_000


def fake_gj(url, timeout=10.0):
    CALLS.append(url)
    if "api.binance.com/api/v3/klines" in url:
        st = int(url.split("startTime=")[1].split("&")[0])
        if "symbol=TONUSDT" in url:
            return [[st, "3.0", "3.0", "3.0", "3.0", "1"]] if st < RENAMED_MS and MODE["bn"] else []
        if "symbol=GRAMUSDT" in url:
            return [[st, "2.5", "2.5", "2.5", "2.5", "1"]] if st >= RENAMED_MS and MODE["bn"] else []
        return []
    if "api.bybit.com" in url:
        return {"retCode": 0, "result": {"list": []}}
    if "api.upbit.com/v1/candles/minutes/1?market=KRW-TON&" in url or "api.upbit.com/v1/candles/minutes/1?market=KRW-USDT&" in url:
        return [{"candle_date_time_utc": _minute_of(url), "opening_price": 1400.0}]
    if "api.upbit.com" in url:
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
    if "coingecko.com" in url:
        raise urllib.error.HTTPError(url, 429, "Too Many", None, None)
    raise OSError("시험: 예상 밖 주소 " + url[:80])


fake_gj._tj_test_mock = True
pricing._gj = fake_gj
MODE = {"bn": True}
px = pricing.PxCache(T.TMP + "/px_ton.json")
m_new = RENAMED_MS + 5 * 60_000


def fresh():
    px.d["neg_ts"].pop("TON", None)
    px.d["neg_n"].pop("TON", None)
    del CALLS[:]


fresh()
v = px.candle_usd("TON", m_new)
chk(v == 2.5 and px.candle_venue("TON", m_new) == "binance", "G5 이름 바꾼 뒤 분 = GRAMUSDT 시가(출처 binance)", (v, px.candle_venue("TON", m_new), CALLS[:3]))
m_old = RENAMED_MS - 86_400_000
fresh()
v = px.candle_usd("TON", m_old)
chk(v == 3.0 and len(CALLS) == 1 and "TONUSDT" in CALLS[0], "G6 이름 바꾸기 전 분 = TONUSDT 그대로 · 호출 1", (v, CALLS))
MODE["bn"] = False
fresh()
v = px.candle_usd("TON", m_new + 60 * 60_000)
up9 = [u for u in CALLS if "api.upbit.com/v1/candles/minutes/1?market=KRW-" in u and "KRW-USDT" not in u]
chk(v is None and up9 and all("KRW-GRAM" in u for u in up9), "G7 거래소 봉 없음 = 업비트는 KRW-GRAM 만(옛 KRW-TON 값 안 씀)", (v, up9))

MAP9 = getattr(pricing, "NATIVE_EX_TICKER", {})
chk(set(MAP9) == {chain_registry.native_symbol("ton")} and MAP9.get("TON") == "GRAM", "G8 매핑 = TON 체인 네이티브 심볼 → GRAM 만", MAP9)
chk(spamguard.major_of("TON") is None and "TON" not in spamguard.MAJORS,
    "G8 'TON' = 대표 심볼 밖(같은 심볼 CA 토큰은 보유 평가에서 심볼 시세 안 받음)", spamguard.major_of("TON"))

import core  # noqa: E402
import db as dbm  # noqa: E402


class _Px:
    calls = []
    checked = []

    def candle_usd(self, sym, ms):
        self.calls.append(str(sym).upper())
        return 2.5 if str(sym).upper() == "TON" else None

    def token_usd_checked(self, sym, ms, chain, ca, cex_px):
        self.checked.append((sym, chain, cex_px))
        return 1.1


cc = dbm.open_db(T.TMP + "/core_ton.db")
C = core.Core.__new__(core.Core)
C.conn, C.wrapped, C.native_sym, C.px = cc, {}, {"ton": "TON", "eth": "ETH"}, _Px()
core.core_svc.attach(C)
C.svc_price._sym_px_verdict = lambda aid, px, sym=None, ts_ms=None: "unknown"
TOK = "0x" + "2b" * 20
a_nat = C.asset_id("native", "ton", None, "TON", 9)
a_tok = C.asset_id("token", "eth", TOK, "TON", 18)
del _Px.calls[:]
chk(C.svc_price._leg_px(a_nat, 1_790_000_000) == 2.5 and _Px.calls == ["TON"], "G9 TON 체인 네이티브 원가 = 심볼 1분봉 'TON'", _Px.calls)
del _Px.calls[:]
v = C.svc_price._leg_px(a_tok, 1_790_000_000)
chk(v == 1.1 and not _Px.calls and _Px.checked[-1] == ("TON", "eth", None), "G9 같은 심볼 CA 토큰 = 심볼 1분봉 후보 없음(코인게코 컨트랙트 값만)",
    (v, _Px.calls, _Px.checked[-1:]))
chk(C.svc_price._leg_px_sym(a_nat) == "TON" and C.svc_price._leg_px_sym(a_tok) is None, "G9 선조회 심볼: 네이티브 = TON · 같은 심볼 CA 토큰 = 없음",
    (C.svc_price._leg_px_sym(a_nat), C.svc_price._leg_px_sym(a_tok)))

T.finish()
