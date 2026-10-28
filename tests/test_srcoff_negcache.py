#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import urllib.error  # noqa: E402

import _cassette_clock  # noqa: E402

CK = _cassette_clock.freeze(1_800_000_000.0)
json.dump({"chains": {}, "wallets": []}, open(os.path.join(os.environ["TJ_BASE"], "config.json"), "w"))
import paths  # noqa: E402
import lpchain  # noqa: E402
import pricing  # noqa: E402
import chk_collect  # noqa: E402
import calcguard  # noqa: E402

chk = T.chk
CALLS = []
ROUTE = {}
SEQ = {}


class _Resp:
    def __init__(self, body):
        self._b = json.dumps(body).encode()
        self.headers = {}
        self.status = 200

    def read(self, n=-1):
        b, self._b = (self._b, b"") if n is None or n < 0 else (self._b[:n], self._b[n:])
        return b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _uo(req, timeout=None, *a, **k):
    u = getattr(req, "full_url", req)
    CALLS.append(u)
    for pre, q in SEQ.items():
        if u.startswith(pre) and q:
            code, body = q.pop(0) if len(q) > 1 else q[0]
            if code != 200:
                raise urllib.error.HTTPError(u, code, "합성", {}, io.BytesIO(b"{}"))
            return _Resp(body)
    for pre, (code, body) in ROUTE.items():
        if u.startswith(pre):
            if code != 200:
                raise urllib.error.HTTPError(u, code, "합성", {}, io.BytesIO(json.dumps(body).encode()))
            return _Resp(body)
    raise urllib.error.HTTPError(u, 500, "합성 경로 없음", {}, io.BytesIO(b"{}"))


_uo._tj_test_mock = True
pricing.urllib.request.urlopen = _uo


def n_calls(pre):
    return sum(1 for u in CALLS if u.startswith(pre))


MGR = "0x" + "11" * 20
os.makedirs(os.path.join(paths.STATE_DIR, "seed_local"), exist_ok=True)
json.dump({"base": {MGR: {"proto": "uni_v4", "name": "합성 v4", "stateview": "0x" + "66" * 20}},
           "eth": {MGR: {"proto": "uni_v4", "name": "합성 v4", "stateview": "0x" + "66" * 20}}},
          open(os.path.join(paths.STATE_DIR, "seed_local", "lp_managers.json"), "w"))
BS_B, BS_E = "https://bs-b.example", "https://bs-e.example"
CFG = {"chains": {"base": {"blockscout": BS_B}, "eth": {"blockscout": BS_E}}}
W1, W2 = "0x" + "a1" * 20, "0x" + "a2" * 20
ROUTE[BS_B] = (403, {})
ROUTE[BS_E] = (200, {"items": [{"token": {"address": MGR}, "id": "7"}], "next_page_params": None})
r1 = lpchain.list_wallet_positions(CFG, "base", W1)
chk(r1 is None and n_calls(BS_B) == 1, "[1a] 403 = None(직전 목록 유지) · 1번 부름", {"r": r1, "n": n_calls(BS_B)})
r2 = lpchain.list_wallet_positions(CFG, "base", W2)
chk(r2 is None and n_calls(BS_B) == 1, "[1b] 쉬는 동안 같은 체인 다른 지갑 = 안 부름(None 그대로)", {"n": n_calls(BS_B)})
rE = lpchain.list_wallet_positions(CFG, "eth", W1)
chk(rE == [(MGR, 7)] and n_calls(BS_E) == 1, "[1c] 다른 체인은 그대로 부르고 값도 그대로", {"r": rE})
st = lpchain.bs_off_state(CK.now)
chk(set(st) == {"base"} and st["base"]["why"] == "HTTP 403" and st["base"]["until"] == int(CK.now + lpchain.BS_OFF_SEC),
    "[1d] 쉼 상태(상태 패널 재료) = base · HTTP 403 · 수명 BS_OFF_SEC", st)
CK.now += lpchain.BS_OFF_SEC - 10
lpchain.list_wallet_positions(CFG, "base", W1)
chk(n_calls(BS_B) == 1, "[1e] 수명 안 = 계속 안 부름")
CK.now += 20
r3 = lpchain.list_wallet_positions(CFG, "base", W1)
chk(r3 is None and n_calls(BS_B) == 2, "[1f] 수명 뒤 = 다시 부름(여전히 403 → 다시 쉼)", {"n": n_calls(BS_B)})
BS_B2 = "https://bs-c.example"
ROUTE[BS_B2] = (200, {"items": [], "next_page_params": None})
cfg2 = {"chains": {"base": {"blockscout": BS_B2}, "eth": {"blockscout": BS_E}}}
r4 = lpchain.list_wallet_positions(cfg2, "base", W1)
chk(r4 == [] and n_calls(BS_B2) == 1, "[1g] 블록스카웃 주소가 바뀌면 쉼 무시하고 바로 부름", {"r": r4})
chk(lpchain.bs_off_state(CK.now) == {}, "[1h] 답하면 쉼 풀림")
ROUTE[BS_B] = (429, {})
lpchain.list_wallet_positions(CFG, "base", W1)
lpchain.list_wallet_positions(CFG, "base", W2)
chk(n_calls(BS_B) == 4 and lpchain.bs_off_state(CK.now) == {}, "[1i] 429 는 이 쉼 아님(종전대로 매번 — errc 갈래)", {"n": n_calls(BS_B)})

OKX = pricing.OKX_HOST + pricing.OKX_PRICE_PATH
CRED = {"key": "k-합성", "secret": "s-합성", "passphrase": "p-합성"}
ca_eth = next(iter(pricing.token_tables.STABLE_CAS.get("eth") or {}), None)
PAIRS = [("eth", "0x" + f"{i:040x}") for i in range(1, 120)]
ROUTE[OKX] = (401, {})
g1 = pricing.okx_dex_prices(CRED, PAIRS)
chk(g1 == {} and n_calls(OKX) == 1, "[2a] 401 = 빈 결과 · 남은 배치 안 부름(1번)", {"n": n_calls(OKX), "anchor": bool(ca_eth)})
pricing.okx_dex_prices(CRED, PAIRS)
chk(n_calls(OKX) == 1, "[2b] 같은 키 = 쉬는 동안 안 부름")
os9 = pricing.okx_off_state(CK.now)
chk(os9.get("why") == "HTTP 401" and os9.get("until") == int(CK.now + pricing.OKX_OFF_SEC) and "fp" not in os9,
    "[2c] 쉼 상태 = HTTP 401 · 수명 OKX_OFF_SEC · 키 지문은 밖으로 안 냄", os9)
pricing.okx_dex_prices(dict(CRED, key="k2-합성"), PAIRS)
chk(n_calls(OKX) == 2, "[2d] 키가 바뀌면 바로 다시 부름")
CK.now += pricing.OKX_OFF_SEC + 1
anc = pricing._okx_anchor_for("eth")
ROUTE[OKX] = (200, {"code": "0", "data": [{"chainIndex": "1", "tokenContractAddress": anc, "price": "1.0"},
                                         {"chainIndex": "1", "tokenContractAddress": PAIRS[0][1], "price": "2.5"}]})
g2 = pricing.okx_dex_prices(dict(CRED, key="k2-합성"), PAIRS)
chk(n_calls(OKX) == 4 and g2.get(PAIRS[0]) == 2.5 and pricing.okx_off_state(CK.now) == {},
    "[2e] 수명 뒤 다시 · 답하면 값 그대로 받고 쉼 풀림", {"n": n_calls(OKX), "g2": {str(k): v for k, v in g2.items()}})
ROUTE[OKX] = (404, {})
pricing.okx_dex_prices(CRED, PAIRS)
pricing.okx_dex_prices(CRED, PAIRS)
chk(n_calls(OKX) == 8 and pricing.okx_off_state(CK.now) == {}, "[2f] 404·5xx 꼴은 쉼 아님(종전대로 배치마다)", {"n": n_calls(OKX)})
import view_spot  # noqa: E402
with open(paths.ENV_PATH, "a", encoding="utf-8") as _f:
    _f.write("TJ_OKX_KEY=k3-합성\nTJ_OKX_SECRET=s-합성\nTJ_OKX_PASSPHRASE=p-합성\n")
ROUTE[OKX] = (401, {})
sp = view_spot.Spot()
sp.token_pairs = {PAIRS[1]}
n0 = n_calls(OKX)
for _i in range(3):
    CK.now += 61
    sp.tick()
chk(n_calls(OKX) - n0 == 1 and sp._okx_fullscan_tries == 0 and not sp._okx_fullscan_done,
    "[2g] 첫 401 + 쉰 주기 2번 = 풀스캔 시도로 안 셈(끝 아님)", {"n": n_calls(OKX) - n0, "tries": sp._okx_fullscan_tries, "done": sp._okx_fullscan_done})
CK.now += pricing.OKX_OFF_SEC + 1
ROUTE[OKX] = (200, {"code": "0", "data": [{"chainIndex": "1", "tokenContractAddress": anc, "price": "1.0"},
                                         {"chainIndex": "1", "tokenContractAddress": PAIRS[1][1], "price": "3.5"}]})
sp.tick()
chk(sp._okx_fullscan_done and sp.dex_usd.get(f"eth:{PAIRS[1][1]}") == 3.5, "[2h] 쉼 뒤 = 풀스캔 다시(token_pairs 포함) · 값 받으면 끝",
    {"done": sp._okx_fullscan_done, "px": sp.dex_usd.get(f"eth:{PAIRS[1][1]}")})

UP = "https://api.upbit.com/v1/candles/minutes/1?market=KRW-"
ROUTE[UP + "TKA"] = (404, {})
MS = 1_700_000_000_000
try:
    pricing._upbit_krw_minute("TKA", MS)
    e3 = None
except urllib.error.HTTPError as e:
    e3 = e.code
chk(e3 == 404 and n_calls(UP + "TKA") == 1, "[3a] 첫 404 = 종전대로 HTTPError(부르는 쪽 처리 그대로)", {"e": e3})
v3 = pricing._upbit_krw_minute("TKA", MS + 60_000)
chk(v3 is None and n_calls(UP + "TKA") == 1, "[3b] 수명 안 = 안 부르고 None(404 와 같은 '없음')")
ROUTE[UP + "TKB"] = (500, {})
for _i in range(2):
    try:
        pricing._upbit_krw_minute("TKB", MS)
    except urllib.error.HTTPError:
        pass
chk(n_calls(UP + "TKB") == 2, "[3c] 500(일시) 은 캐시 안 함 — 매번 부름")
CK.now += pricing.UPBIT_NOMKT_SEC + 1
ROUTE[UP + "TKA"] = (200, [])
v3b = pricing._upbit_krw_minute("TKA", MS)
chk(v3b is None and n_calls(UP + "TKA") == 2 and "TKA" not in pricing._UPBIT_NOMKT, "[3d] 수명 뒤 다시 부름 · 답하면 캐시 지움")
px = pricing.PxCache(os.path.join(paths.STATE_DIR, "px_t.json"))
ROUTE[UP + "TKJ"] = (404, {})
ROUTE["https://api.frankfurter.app/"] = (200, {"rates": {"USD": 0.0067}})
j1 = px.jpy_stable_usd("TKJ", MS)
j2 = px.jpy_stable_usd("TKJ", MS + 120_000)
chk(j1 == j2 == 0.0067 and n_calls(UP + "TKJ") == 1, "[3e] 엔화 스테이블: 404 와 캐시 '없음' 이 같은 폴백 값", {"j1": j1, "j2": j2})
import time as _time  # noqa: E402
from datetime import datetime as _dt, timezone as _tz  # noqa: E402


def _bar(ms, price):
    return {"candle_date_time_utc": _dt.fromtimestamp(ms / 1000, _tz.utc).strftime("%Y-%m-%dT%H:%M:%S"), "opening_price": price}


ROUTE[UP + "TKL"] = (404, {})
try:
    pricing._upbit_krw_minute("TKL", MS)
except urllib.error.HTTPError:
    pass
T404 = int(_time.time() * 1000)
M_AFTER = (T404 // 60_000 + 2) * 60_000
CK.now += 180
ROUTE[UP + "TKL"] = (200, [_bar(M_AFTER, 1500.0)])
v3f = pricing._upbit_krw_minute("TKL", M_AFTER)
v3f_old = pricing._upbit_krw_minute("TKL", MS + 60_000)
chk(v3f == 1500.0 and n_calls(UP + "TKL") == 3 and v3f_old is None, "[3f] 404 본 뒤의 분 = 캐시 안 씀(상장 직후 값 그대로) · 답하면 캐시 지움", {"v": v3f, "n": n_calls(UP + "TKL")})
ROUTE[UP + "TKM"] = (404, {})
j3 = px.jpy_stable_usd("TKM", MS)
M2 = (int(_time.time() * 1000) // 60_000 + 2) * 60_000
CK.now += 180
ROUTE[UP + "TKM"] = (200, [_bar(M2, 1000.0)])
ROUTE[UP + "USDT"] = (200, [_bar(M2, 1400.0)])
j4 = px.jpy_stable_usd("TKM", M2)
chk(j3 == 0.0067 and j4 is not None and abs(j4 - 1000.0 / 1400.0) < 1e-12 and n_calls(UP + "TKM") == 2,
    "[3g] 엔화 스테이블: 404 본 뒤 상장된 분 = 업비트 값(엔 환율 폴백 아님)", {"j3": j3, "j4": j4})
ROUTE[UP + "TKN"] = (404, {})
CK.now = (int(CK.now) // 60 + 1) * 60 + 10
try:
    pricing._upbit_krw_minute("TKN", MS)
except urllib.error.HTTPError:
    pass
M_SAME = (int(CK.now) // 60) * 60_000
CK.now += 35
ROUTE[UP + "TKN"] = (200, [_bar(M_SAME, 1200.0)])
v3h = pricing._upbit_krw_minute("TKN", M_SAME)
chk(v3h == 1200.0 and n_calls(UP + "TKN") == 2, "[3h] 404 와 같은 분에 상장 = 그 분 봉 다시 물음(캐시 안 씀)", {"v": v3h, "n": n_calls(UP + "TKN")})

BN = "https://api.binance.com/api/v3/klines?symbol="
NOSYM = {"code": -1121, "msg": "Invalid symbol."}
CK.now = (int(CK.now) // 60 + 1) * 60 + 5
ROUTE[BN + "TKBUSDT"] = (400, NOSYM)
T0B = CK.now
try:
    pricing._c_binance("TKB", MS)
    e3i = None
except urllib.error.HTTPError as e:
    e3i = e.code
chk(e3i == 400 and n_calls(BN + "TKBUSDT") == 1 and "TKB" in pricing._BN_NOSYM, "[3i] 첫 -1121 = 종전대로 HTTPError(부르는 쪽 처리 그대로) · 심볼 기억", {"e": e3i})
past = [pricing._c_binance("TKB", (int(T0B) // 60 - 120 + i) * 60_000) for i in range(59)]
chk(all(v is None for v in past) and n_calls(BN + "TKBUSDT") == 1, "[3j] 서로 다른 지난 분(400 요청 전에 끝난 분) 59번 더 = 안 부르고 None(합 60번 → 1번)",
    {"n": n_calls(BN + "TKBUSDT")})
n0 = n_calls(BN + "TKBUSDT")
for i in range(60):
    CK.now = T0B + 60 * (i + 1)
    try:
        pricing._c_binance("TKB", (int(CK.now) // 60) * 60_000)
    except urllib.error.HTTPError:
        pass
chk(n_calls(BN + "TKBUSDT") - n0 == 60, "[3k] 지금 분 60번 = 매번 부름(종전과 같음 — 그사이 상장됐을 수 있음)", {"n": n_calls(BN + "TKBUSDT") - n0})
ROUTE[BN + "TKCUSDT"] = (400, {"code": -1100, "msg": "Illegal characters found in parameter 'symbol'"})
ROUTE[BN + "TKDUSDT"] = (500, {})
for _i in range(2):
    for s9 in ("TKC", "TKD"):
        try:
            pricing._c_binance(s9, MS)
        except urllib.error.HTTPError:
            pass
chk(n_calls(BN + "TKCUSDT") == 2 and n_calls(BN + "TKDUSDT") == 2 and "TKC" not in pricing._BN_NOSYM and "TKD" not in pricing._BN_NOSYM,
    "[3l] -1121 아닌 400·500 = 캐시 안 함(매번 부름)")
CK.now += pricing.BN_NOSYM_SEC + 1
ROUTE[BN + "TKBUSDT"] = (200, [])
v3m = pricing._c_binance("TKB", MS)
chk(v3m is None and n_calls(BN + "TKBUSDT") == n0 + 61 and "TKB" not in pricing._BN_NOSYM, "[3m] 수명 뒤 다시 부름 · 답하면 캐시 지움")
ROUTE[BN + "TKEUSDT"] = (400, NOSYM)
ROUTE["https://api.bybit.com/v5/market/kline?category=spot&symbol=TKEUSDT"] = (200, {"retCode": 10001, "result": {}})
ROUTE[UP + "TKE"] = (404, {})
pxe = pricing.PxCache(os.path.join(paths.STATE_DIR, "px_e.json"))
s0 = (calcguard.snapshot().get("pricing:PxCache.candle_usd[fn]") or {}).get("n", 0)
TE = int(CK.now)
for i in range(60):
    pxe.d["neg_ts"].pop("TKE", None)
    pxe.candle_usd("TKE", (TE // 60 - 200 + i) * 60_000)
s1 = (calcguard.snapshot().get("pricing:PxCache.candle_usd[fn]") or {}).get("n", 0)
chk(n_calls(BN + "TKEUSDT") == 1 and n_calls(UP + "TKE") == 1 and s1 - s0 == 2, "[3n] 1분봉 경로 지난 분 60번 = 바이낸스 1번·업비트 1번 · 삼킴 기록 2(종전 바이낸스 60 + 업비트 1 = 61)",
    {"bn": n_calls(BN + "TKEUSDT"), "up": n_calls(UP + "TKE"), "sw": s1 - s0})
n0 = n_calls(BN + "TKEUSDT")
for i in range(5):
    CK.now += 60
    pxe.d["neg_ts"].pop("TKE", None)
    pxe.candle_usd("TKE", (int(CK.now) // 60) * 60_000)
chk(n_calls(BN + "TKEUSDT") - n0 == 5, "[3o] 1분봉 경로 지금 분 = 바이낸스 매번(종전과 같음)", {"n": n_calls(BN + "TKEUSDT") - n0})

CG = "https://cg.example/coins/tkc"
ROUTE[CG] = (404, {})
store = {}
D0 = 1_699_920_000
p1 = pricing.cg_points_day("id:tkc", CG, D0, store)
chk(p1 == [] and n_calls(CG) == 1, "[4a] 404 = [](없음) · 1번", {"p": p1})
CK.now += pricing.CG_MIN_GAP_S + 1
p2 = pricing.cg_points_day("id:tkc", CG, D0 + 86400, store)
chk(p2 == [] and n_calls(CG) == 1 and f"id:tkc:{D0 + 86400}" not in store, "[4b] 같은 코인 다른 날 = 안 부르고 [] · 지난날 저장 안 함", {"store": sorted(store)})
CG2 = "https://cg.example/coins/tkd"
ROUTE[CG2] = (200, {"prices": [[D0 * 1000, 1.5]]})
p3 = pricing.cg_points_day("id:tkd", CG2, D0, store)
chk(p3 == [[D0 * 1000, 1.5]] and n_calls(CG2) == 1, "[4c] 다른 코인은 그대로")
CK.now += pricing.CG_404_SEC + 1
pricing.cg_points_day("id:tkc", CG, D0 + 2 * 86400, store)
chk(n_calls(CG) == 2, "[4d] 수명 뒤 다시 부름")

SD = os.path.join(paths.STATE_DIR, "srcoff_t")
os.makedirs(SD, exist_ok=True)
NOW = 3_000_000.0
chk(chk_collect.collect_src_off(NOW, SD) == [], "[5a] 재료 파일 없음 = 줄 없음")
json.dump({"okx_off": {"until": NOW + 100, "at": NOW - 10, "why": "HTTP 401"}}, open(os.path.join(SD, "spot.json"), "w"))
json.dump({"positions": {}, "bs_off": {"base": {"until": NOW + 50, "at": NOW - 5, "why": "HTTP 403"},
                                       "eth": {"until": NOW - 1, "at": NOW - 99, "why": "HTTP 403"}}}, open(os.path.join(SD, "lp_positions.json"), "w"))
rows = chk_collect.collect_src_off(NOW, SD)
r0 = rows[0] if rows else {}
chk(len(rows) == 1 and r0.get("cid") == "src:off" and r0.get("level") == "ok" and r0.get("notify") is False and r0.get("remind") is False
    and "OKX" in r0.get("detail", "") and "base" in r0.get("detail", "") and "eth" not in r0.get("detail", "") and "2곳" in r0.get("title", ""),
    "[5b] 쉬는 2곳 = 정보 한 줄(알림 없음 · 끝난 쉼은 뺌)", r0)
chk(r0.get("chip") == "외부 조회 쉼 2곳", "[5b2] 칩이 있어야 상태 패널 유닛 '그 밖' 목록에 보인다(ok 줄은 칩 없으면 숨음)", r0.get("chip"))
chk(chk_collect.collect_src_off(NOW + 200, SD) == [], "[5c] 다 끝나면 줄 없음")
json.dump({"okx_off": "깨짐"}, open(os.path.join(SD, "spot.json"), "w"))
json.dump(["깨짐"], open(os.path.join(SD, "lp_positions.json"), "w"))
chk(chk_collect.collect_src_off(NOW, SD) == [], "[5d] 형식 이상 = 줄 없음(죽지 않음)")

import config  # noqa: E402
import health  # noqa: E402
NOW6 = CK.now
json.dump({"okx_off": {"until": NOW6 + 100, "at": NOW6 - 10, "why": "HTTP 401"}}, open(os.path.join(paths.STATE_DIR, "spot.json"), "w"))
json.dump({"chains": {}, "wallets": [], "health": {"pm2_bin": os.path.join(paths.STATE_DIR, "no_pm2")}}, open(paths.CONFIG_PATH, "w"))
cfg6 = config.load_config()
h6 = health.settings(cfg6)
obs6 = health.Monitor(probes={"inbox": lambda: {}, "disk": lambda: {"free": 1, "total": 2}, "web": lambda: None,
                              "tunnel": lambda: None}).observe(cfg6, h6, NOW6, False)
cs6 = health.evaluate(obs6, h6, open_ids={})
row6 = [c for c in cs6 if c["id"] == "src:off"]
st6 = health.build_status({}, obs6, cs6, NOW6, h6)
web6 = [o["id"] for u in st6["units"] if u["unit"] == "tj-web" for o in u["other"]]
chk(len(row6) == 1 and row6[0]["notify"] is False and row6[0]["level"] == "ok" and "src:off" in web6,
    "[6] 종단: src:off 가 tj-web 유닛 '그 밖' 목록에 보임(칩) · 알림 없음", {"row": row6, "web": web6})

BS7 = "https://bs-7.example"
CFG7 = {"chains": {"base": {"blockscout": BS7}}}
W7 = "0x" + "b7" * 20
OTHER = "0x" + "99" * 20
NFT7 = BS7 + "/api/v2/addresses/" + W7 + "/nft?"
COL7 = BS7 + "/api/v2/addresses/" + W7 + "/nft/collections?"
C7 = []


def run7(nft, col):
    SEQ[COL7], SEQ[NFT7] = list(col), list(nft)
    c0 = len(CALLS)
    n0 = (calcguard.snapshot().get("lpchain:list_wallet_positions") or {}).get("n", 0)
    r = lpchain.list_wallet_positions(CFG7, "base", W7)
    n1 = (calcguard.snapshot().get("lpchain:list_wallet_positions") or {}).get("n", 0)
    C7[:] = CALLS[c0:]
    return r, n1 - n0, sum(1 for u in C7 if u.startswith(COL7))


def colpage(*addrs, nxt=None):
    return (200, {"items": [{"token": {"address_hash": a, "type": "ERC-721"}, "amount": "1", "token_instances": []} for a in addrs],
                  "next_page_params": nxt})


E500 = (500, {})
r, n, nc = run7([E500], [colpage(OTHER)])
chk(r == [] and n == 0 and nc == 1, "[7a] /nft 500 · 컬렉션에 관리자 없음(완전) = [] · 삼킴 기록 0", {"r": r, "n": n, "nc": nc})
r, n, nc = run7([E500], [colpage()])
chk(r == [] and n == 0, "[7a2] /nft 500 · 컬렉션 0개 = []", {"r": r, "n": n})
r, n, nc = run7([E500], [colpage(OTHER, MGR)])
chk(r is None and n == 1, "[7b] /nft 500 · 컬렉션에 관리자 있음 = None(직전 목록 유지 · 토큰을 컬렉션으로 채우지 않음) · 기록 1", {"r": r, "n": n})
r, n, nc = run7([E500], [(200, {"items": []})])
chk(r is None and n == 1, "[7c5] 컬렉션 끝 표시(next_page_params: null) 없음 = None(완전한지 모름)", {"r": r, "n": n})
for bad9 in ({}, [], "", False, 0):
    r, n, nc = run7([E500], [(200, {"items": [], "next_page_params": bad9})])
    chk(r is None and n == 1, f"[7c6] 컬렉션 커서 이상({bad9!r}) = None", {"r": r, "n": n})
r, n, nc = run7([E500], [(502, {})])
chk(r is None and n == 1 and nc == 1, "[7c] 대체 확인도 실패 = None · 기록 1", {"r": r, "n": n})
r, n, nc = run7([E500], [(200, {"items": "깨짐"})])
chk(r is None and n == 1, "[7c2] 대체 확인 형식 이상(items 가 목록 아님) = None", {"r": r, "n": n})
r, n, nc = run7([E500], [(200, {"items": [{"token": {}}], "next_page_params": None})])
chk(r is None and n == 1, "[7c3] 컬렉션 주소 못 읽음 = None(관리자 없음 확신 못 함)", {"r": r, "n": n})
r, n, nc = run7([E500], [colpage(OTHER, nxt="깨짐")])
chk(r is None and n == 1, "[7c4] next_page_params 형식 이상 = None", {"r": r, "n": n})
r, n, nc = run7([E500], [colpage(OTHER, nxt={"k": 1}), colpage(OTHER, nxt={"k": 2}), colpage()])
chk(r == [] and n == 0 and nc == 3, "[7d] 컬렉션 여러 페이지 끝까지 관리자 없음 = []", {"r": r, "n": n, "nc": nc})
r, n, nc = run7([E500], [colpage(OTHER, nxt={"k": 1}), colpage(MGR, nxt={"k": 2}), colpage()])
chk(r is None and n == 1 and nc == 2, "[7d2] 2페이지째 관리자 = None", {"r": r, "n": n, "nc": nc})
r, n, nc = run7([E500], [colpage(OTHER, nxt={"k": 1}), colpage(OTHER, nxt={"k": 1})])
chk(r is None and n == 1 and nc == 2, "[7e] 컬렉션 커서 순환 = None(불완전)", {"r": r, "n": n, "nc": nc})
r, n, nc = run7([E500], [colpage(OTHER, nxt={"k": i}) for i in range(lpchain.NFT_PAGES_MAX + 5)])
chk(r is None and n == 1 and nc == lpchain.NFT_PAGES_MAX, "[7e2] 컬렉션 페이지 상한 초과 = None(상한만큼만 부름)", {"r": r, "n": n, "nc": nc})
p1 = (200, {"items": [{"token": {"address": OTHER}, "id": "1"}], "next_page_params": {"p": 2}})
r, n, nc = run7([p1, E500], [colpage(OTHER)])
chk(r == [] and n == 0 and nc == 1, "[7f] 1페이지 성공 뒤 2페이지째 500 · 관리자 없음 = []", {"r": r, "n": n})
p1m = (200, {"items": [{"token": {"address": MGR}, "id": "5"}], "next_page_params": {"p": 2}})
r, n, nc = run7([p1m, E500], [colpage(MGR)])
chk(r is None and n == 1, "[7g] 1페이지에 관리자 포지션 · 2페이지째 500 = None(부분 목록을 완전으로 안 봄)", {"r": r, "n": n})
r, n, nc = run7([p1m, E500], [colpage(OTHER)])
chk(r is None and n == 1 and nc == 0, "[7g2] 1페이지에 관리자 포지션 · 2페이지째 500 · 컬렉션엔 관리자 없음(두 색인 엇갈림) = None(찾은 포지션을 []로 지우지 않음 · 대체 확인 안 부름)",
    {"r": r, "n": n, "nc": nc})
r, n, nc = run7([(404, {})], [colpage()])
chk(r is None and n == 1 and nc == 0, "[7h] 4xx(404) 는 대체 확인 안 함(종전 None)", {"r": r, "n": n, "nc": nc})
r, n, nc = run7([(403, {})], [colpage()])
chk(r is None and n == 1 and nc == 0 and "base" in lpchain.bs_off_state(CK.now), "[7i] 403 = 종전 쉼 그대로(대체 확인 안 함)", {"r": r, "nc": nc})
r, n, nc = run7([E500], [colpage()])
chk(r is None and n == 0 and len(C7) == 0, "[7j] 쉬는 동안은 아예 안 부름(종전)", {"r": r, "c": C7})
lpchain._BS_OFF.clear()
r, n, nc = run7([(200, {"items": [{"token": {"address": MGR}, "id": "9"}], "next_page_params": None})], [colpage()])
chk(r == [(MGR, 9)] and nc == 0 and n == 0, "[7k] 정상 /nft 는 그대로(대체 확인 안 부름)", {"r": r, "nc": nc})
SEQ.clear()

T.finish()
