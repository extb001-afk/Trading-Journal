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

chk = T.chk
CALLS = []
ROUTE = {}


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
    for pre, (code, body) in ROUTE.items():
        if u.startswith(pre):
            if code != 200:
                raise urllib.error.HTTPError(u, code, "합성", {}, io.BytesIO(b"{}"))
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

T.finish()
