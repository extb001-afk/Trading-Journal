#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as H  # noqa: E402

import os  # noqa: E402

import nft  # noqa: E402

chk = H.chk
CLOCK = [1791000000.0]
DAY = 86400
CFG = {"wallets": [], "chains": {}, "nft": {"enabled": True}}


class Router:
    def __init__(self):
        self.routes, self.calls = {}, []

    def on(self, frag, resp):
        self.routes[frag] = resp

    def __call__(self, url, data=None, headers=None):
        self.calls.append(url)
        hit = [f for f in self.routes if f in url]
        if not hit:
            return 404, None
        r = self.routes[max(hit, key=len)]
        return r(url) if callable(r) else r

    def n(self, frag):
        return sum(1 for u in self.calls if frag in u)


def mk(r, d, env=None):
    os.makedirs(os.path.join(H.TMP, d), exist_ok=True)
    env = {"TJ_OPENSEA_KEY": "OSKEY-A"} if env is None else env
    kw = {k + "_path": os.path.join(H.TMP, d, k + ".json") for k in ("hold", "fp", "prefs")}
    return nft.Tracker(cfg_fn=lambda: CFG, px_fn=lambda s: 2700.0 if s == "ETH" else (40.0 if s == "HYPE" else None),
                       rate_fn=lambda: 1400.0, http=r, sleep=lambda s: None, now=lambda: CLOCK[0], env_fn=lambda k: env.get(k, ""),
                       gate_fn=lambda: {}, budget_path=os.path.join(H.TMP, d, "budget.json"), **kw)


W = "0x" + "11" * 20
BERA = "0x" + "be" * 20
RAR = "0x" + "ab" * 20
HYP = "0x" + "9f" * 20
OLD = "0x" + "d4" * 20
REC = "0x" + "e5" * 20


def add(T, ch, ca, nm):
    key = f"{ch}:{ca}"
    T.hold["cols"][key] = {"chain": ch, "ca": ca, "name": nm, "sym": "", "std": "ERC-721", "seen": CLOCK[0], "first": CLOCK[0]}
    T.hold["pairs"].setdefault(f"{ch}:{W}", {"items": {}, "at": CLOCK[0], "err": None})["items"][key] = {"n": 1, "ids": ["1"]}
    T.hold["acq"][key] = {"kind": "bought", "at": CLOCK[0], "tries": 1}
    return key


def run(T, secs):
    t_end = CLOCK[0] + secs
    while CLOCK[0] < t_end:
        T.refresh_fp()
        CLOCK[0] += T._loop_wait()


def row_of(v, key):
    for sec in ("tracked", "candidates", "hidden", "watch"):
        for r9 in v.get(sec) or []:
            if r9.get("key") == key:
                return r9
    return None


HYP_OK = (200, {"contract_address": HYP, "floor_price": {"native_currency": 1200.0, "usd": 48000}, "native_currency_symbol": "HYPE",
                "volume_24h": {"native_currency": 5000.0}, "one_day_sales": 4, "id": "hypurr", "name": "Hypurr"})
r = Router()
r.on(f"api.opensea.io/api/v2/chain/berachain/contract/{BERA}", (500, None))
r.on(f"api.opensea.io/api/v2/chain/ethereum/contract/{RAR}", (200, {"address": "0x" + "00" * 20, "collection": "rarible"}))
r.on(f"api.opensea.io/api/v2/chain/ethereum/contract/{OLD}", (500, None))
r.on(f"/nfts/hyperevm/contract/{HYP}", HYP_OK)
r.on("/nfts/", (404, {"error": "nft collection not found"}))
T = mk(r, "a")
kb, kr, kh, ko = add(T, "berachain", BERA, "Bera NFT Lottery"), add(T, "eth", RAR, "Rarible"), add(T, "hyperevm", HYP, "Hypurr"), add(T, "eth", OLD, "Old")
T.fp["fp"][ko] = {"src": "os", "native": 0.5, "sym": "ETH", "at": CLOCK[0] - 600}
T.fp["chk"][ko] = CLOCK[0] - 600
t0 = CLOCK[0]
run(T, DAY)
neg = T.fp.get("neg") or {}
nb_os, nr_os = r.n(f"chain/berachain/contract/{BERA}"), r.n(f"chain/ethereum/contract/{RAR}")
chk(r.n("coingecko.com") == r.n("/nfts/hyperevm/") and r.n("/nfts/ethereum/") == 0 and r.n("/nfts/berachain/") == 0,
    "R0 오픈시 키 있음 = 오픈시 체인 코인게코 0콜(대체·폴백 포함 · 코인게코 콜은 hyperevm 만)", r.calls)
chk(2 <= nb_os <= 48 and kb not in neg and kb in (T.fp.get("retry") or {}),
    "R1 오픈시 500 지속 = 코인게코 확인 없이 '없음' 확정 안 함(미확인 · 30분마다 오픈시만 · 하루 ≤ 48)", (nb_os, neg.get(kb)))
chk(2 <= nr_os <= 48 and kr not in neg, "R2 오픈시 주소 불일치 = 같음(코인게코 0콜)", nr_os)
chk(1 <= r.n("/nfts/hyperevm/") <= 7 and ((T.fp.get("fp") or {}).get(kh) or {}).get("src") == "cg",
    "R3 오픈시 키 있음 + 코인게코 전용 체인(hyperevm) = 코인게코 바닥가(4시간마다 · 24시간 CG ≤ 7)", r.n("/nfts/hyperevm/"))
fo = (T.fp.get("fp") or {}).get(ko) or {}
chk(fo.get("native") == 0.5 and fo.get("err") and ko not in neg,
    "R4 직전 시세 있음 = 오픈시 오류가 이어져도 부정 캐시 안 함(직전 값 · 오류 표시)", (fo, neg.get(ko)))

CLOCK[0] = t0 + 2 * DAY
r3 = Router()
r3.on(f"/nfts/hyperevm/contract/{HYP}", HYP_OK)
T3 = mk(r3, "r3", env={})
kh = add(T3, "hyperevm", HYP, "Hypurr")
run(T3, DAY)
nh = r3.n(f"nfts/hyperevm/contract/{HYP}")
chk(1 <= nh <= 7, "R3k 키 없음 = 코인게코 전용 체인 추적 = 4시간마다(24시간 CG ≤ 7)", nh)
fh = (T3.fp.get("fp") or {}).get(kh) or {}
CLOCK[0] = float(fh.get("at") or 0) + 4.5 * 3600
rh = row_of(T3.view(CFG), kh) or {}
chk(rh.get("fp") and not rh["fp"].get("stale"), "R3k 4시간 반 지난 코인게코 전용 체인 값 = '오래됨' 아님(주기 4시간)", rh.get("fp"))
CLOCK[0] = float(fh.get("at") or 0) + 6 * 3600
rh = row_of(T3.view(CFG), kh) or {}
chk(rh.get("fp") and rh["fp"].get("stale"), "R3k 6시간 지난 값 = '오래됨'", rh.get("fp"))

CLOCK[0] = t0 + 4 * DAY
env5 = {"TJ_OPENSEA_KEY": "OSKEY-A"}
r5 = Router()
r5.on(f"/nfts/ethereum/contract/{REC}", (200, {"contract_address": REC, "floor_price": {"native_currency": 0.3}, "native_currency_symbol": "ETH",
                                                 "volume_24h": {"native_currency": 2.0}, "id": "rec", "name": "Rec"}))
T5 = mk(r5, "r5", env=env5)
k5 = add(T5, "eth", REC, "Recover")
T5._os_sync_key()
o5 = T5.fetch_fp(k5, T5.hold["cols"][k5])
chk(o5 == "none" and (T5.fp.get("neg") or {}).get(k5, {}).get("src") == "os" and r5.n("coingecko.com") == 0,
    "R5 오픈시 404 = 시세 없음(부정 캐시 src os) · 코인게코 0콜", (o5, (T5.fp.get("neg") or {}).get(k5), r5.n("coingecko.com")))

env5["TJ_OPENSEA_KEY"] = "OSKEY-B"
T5._os_sync_key()
chk(k5 not in (T5.fp.get("neg") or {}) and k5 in {k for k, _c in T5.due_fp()}, "R6 키 바뀜 = 부정 캐시 풀림 · 다시 물을 대상")
T5.fetch_fp(k5, T5.hold["cols"][k5])
env5["TJ_OPENSEA_KEY"] = ""
n6 = T5._os_sync_key()
chk(n6 == 1 and k5 not in (T5.fp.get("neg") or {}) and k5 in {k for k, _c in T5.due_fp()}, "R6b 키 뺌 = 오픈시 부정 캐시(src os) 풀림 · 다시 물을 대상", n6)
o6 = T5.fetch_fp(k5, T5.hold["cols"][k5])
chk(o6 == "ok" and r5.n(f"nfts/ethereum/contract/{REC}") == 1 and ((T5.fp.get("fp") or {}).get(k5) or {}).get("native") == 0.3,
    "R6b 키 없음 = 코인게코 바닥가(종전)", (o6, r5.n("coingecko.com")))

CLOCK[0] = t0 + 6 * DAY
env8 = {"TJ_OPENSEA_KEY": ""}
T8 = mk(r5, "r6c", env=env8)
k8 = add(T8, "eth", REC, "Recover")
T8._os_sync_key()
env8["TJ_OPENSEA_KEY"] = "OSKEY-MID"
o8 = T8.fetch_fp(k8, T8.hold["cols"][k8])
env8["TJ_OPENSEA_KEY"] = ""
n8 = T8._os_sync_key()
chk(o8 == "none" and n8 == 1 and k8 not in (T8.fp.get("neg") or {}) and T8._os_sync_key() == 0,
    "R6c 바퀴 도중 넣었다 뺀 키 = 오픈시 부정 캐시 풀림(한 번만)", (o8, n8))

CLOCK[0] = t0 + 7 * DAY
T7 = mk(Router(), "r7")
k7 = "eth:0x" + "c9" * 20
T7.hold["cols"][k7] = {"chain": "eth", "ca": k7.split(":")[1], "name": "CG coll", "rep": "ok"}
T7.fp["fp"][k7] = {"src": "cg", "native": 1.0, "sym": "ETH", "vol24": 5.0, "at": CLOCK[0]}
T7.fp["chk"][k7] = CLOCK[0]
CLOCK[0] += 3601
chk(k7 in {k for k, _c in T7.due_fp()}, "R7 eth 코인게코 출처 추적 = 1시간 뒤 다시(종전)")

H.finish()
