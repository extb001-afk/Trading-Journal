#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as H  # noqa: E402

import os  # noqa: E402

import nft  # noqa: E402

chk = H.chk
DAY = 86400
CLOCK = [1791000000.0]
CFG = {"wallets": [], "chains": {}, "nft": {"enabled": True}}

p0, p1 = nft.cg_policy(24, 260), nft.cg_policy(24, 260, True)
chk(p0["floor"] == {"live": 130, "past": 52, "nft": 78}, "P1 오픈시 키 없음 = 종전 몫(데모 260: live 130 · nft 78 · past 52)", p0["floor"])
chk(p1["floor"] == {"live": 208, "past": 52, "nft": 0}, "P2 오픈시 키 있음 = nft 0 · live 208(+78) · past 52 그대로", p1["floor"])
chk({k: p1[k] for k in ("per_min", "per_day", "min_reserve", "hour")} == {k: p0[k] for k in ("per_min", "per_day", "min_reserve", "hour")},
    "P3 분당·하루·live 전용 분당·시간당 상한 = 그대로(바뀌는 건 보장 몫만)", (p0, p1))
q0, q1 = nft.cg_policy(200, 1001), nft.cg_policy(200, 1001, True)
chk(sum(q0["floor"].values()) == 1001 == sum(q1["floor"].values()) and q1["floor"]["live"] - q0["floor"]["live"] == q0["floor"]["nft"] == 300,
    "P4 프로 예(하루 1001) — 합 = 하루 몫 · live 증가 = 종전 nft 몫(300)", (q0["floor"], q1["floor"]))


def live_day(os_val):
    clk = [1791000000.0]
    b = nft._Budget(lambda: clk[0])
    b.os_fn = lambda: os_val
    got, why = 0, {}
    end = clk[0] + DAY
    while clk[0] < end:
        b.act["nft"] = b.act["past"] = clk[0]
        w = b.take_cg("live", 24, 260)
        if w:
            why[w] = why.get(w, 0) + 1
        else:
            got += 1
        clk[0] += 60
    return got, why


g0, w0 = live_day("")
g1, w1 = live_day("OSKEY")
chk(g0 == 130 and w0.get("share"), "B1 오픈시 키 없음 = live 하루 130(nft 78 · past 52 남겨 둠 — 종전)", (g0, w0))
chk(g1 == 208 and w1.get("share"), "B2 오픈시 키 있음 = live 하루 208(+78 · past 52 만 남겨 둠)", (g1, w1))
b4 = nft._Budget(lambda: 1791000000.0)
b4.os_fn = lambda: "OSKEY"
w4a = b4.take_cg("nft", 24, 260)
b4.act["live"] = b4.act["past"] = 1791000000.0
w4b = b4.take_cg("nft", 24, 260)
chk(w4a == "" and w4b == "share", "B4 오픈시 키 = nft 보장 0 이어도 남는 몫은 씀 · 다른 기능이 남은 보장을 다 묶으면 share(무키로)", (w4a, w4b))
os.environ["TJ_OPENSEA_KEY"] = "OSKEY-ENV"
try:
    chk(nft._Budget(lambda: 0.0).os_fn is nft._os_env and nft._os_env() == "OSKEY-ENV", "B3 기본 판정 = 환경변수·.env 의 TJ_OPENSEA_KEY(settings_store.env_value)")
finally:
    os.environ.pop("TJ_OPENSEA_KEY", None)
chk(nft._os_env() == "", "B3 키 없음 = 빈 값(종전 몫)")


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


def mk(r, d, env):
    os.makedirs(os.path.join(H.TMP, d), exist_ok=True)
    kw = {k + "_path": os.path.join(H.TMP, d, k + ".json") for k in ("hold", "fp", "prefs")}
    return nft.Tracker(cfg_fn=lambda: CFG, px_fn=lambda s: 2700.0 if s == "ETH" else (40.0 if s == "HYPE" else None),
                       rate_fn=lambda: 1400.0, http=r, sleep=lambda s: None, now=lambda: CLOCK[0], env_fn=lambda k: env.get(k, ""),
                       gate_fn=lambda: {}, budget_path=os.path.join(H.TMP, d, "budget.json"), **kw)


W = "0x" + "11" * 20
OK, MISS, BAD, THIN, HYP = ("0x" + h * 20 for h in ("a1", "a2", "a3", "a4", "9f"))


def add(T, ch, ca):
    key = f"{ch}:{ca}"
    T.hold["cols"][key] = {"chain": ch, "ca": ca, "name": "C " + ca[:6], "sym": "", "std": "ERC-721", "seen": CLOCK[0], "first": CLOCK[0]}
    T.hold["pairs"].setdefault(f"{ch}:{W}", {"items": {}, "at": CLOCK[0], "err": None})["items"][key] = {"n": 1, "ids": ["1"]}
    T.hold["acq"][key] = {"kind": "bought", "at": CLOCK[0], "tries": 1}
    return key


def os_event(ts):
    def f(url):
        slug = url.split("/events/collection/", 1)[1].split("?", 1)[0]
        return (200, {"asset_events": [{"event_type": "sale", "event_timestamp": int(ts), "quantity": 1, "nft": {"collection": slug},
                                        "payment": {"quantity": "37000000000000000", "decimals": 18, "symbol": "ETH"}}], "next": None})
    return f


def router():
    r = Router()
    r.on(f"api.opensea.io/api/v2/chain/ethereum/contract/{OK}", (200, {"address": OK, "collection": "ok-x"}))
    r.on("api.opensea.io/api/v2/collections/ok-x/stats", (200, {"total": {"floor_price": 0.5, "floor_price_symbol": "ETH"},
                                                                "intervals": [{"interval": "one_day", "volume": 2.0, "sales": 3}]}))
    r.on(f"api.opensea.io/api/v2/chain/ethereum/contract/{BAD}", (500, None))
    r.on(f"api.opensea.io/api/v2/chain/ethereum/contract/{THIN}", (200, {"address": THIN, "collection": "thin-x"}))
    r.on("api.opensea.io/api/v2/collections/thin-x/stats", (200, {"total": {"floor_price": None, "floor_price_symbol": "ETH"}, "intervals": []}))
    r.on("api.opensea.io/api/v2/events/collection/thin-x", os_event(CLOCK[0] - 40 * DAY))
    for ca, plat in ((OK, "ethereum"), (MISS, "ethereum"), (BAD, "ethereum"), (THIN, "ethereum"), (HYP, "hyperevm")):
        r.on(f"/nfts/{plat}/contract/{ca}", (200, {"contract_address": ca, "floor_price": {"native_currency": 1.0, "usd": 2700}, "native_currency_symbol": "ETH",
                                                    "volume_24h": {"native_currency": 3.0}, "one_day_sales": 2, "id": "cg-" + ca[2:6], "name": "CG"}))
    return r


def run(T, secs):
    t_end = CLOCK[0] + secs
    while CLOCK[0] < t_end:
        T.refresh_fp()
        CLOCK[0] += T._loop_wait()


ENV_ON = {"TJ_OPENSEA_KEY": "OSKEY-A", "TJ_COINGECKO_KEY": "CG-demo-0000"}
r1 = router()
T1 = mk(r1, "on", ENV_ON)
keys = {nm: add(T1, ch, ca) for nm, ch, ca in (("ok", "eth", OK), ("miss", "eth", MISS), ("bad", "eth", BAD), ("thin", "eth", THIN), ("hyp", "hyperevm", HYP))}
run(T1, DAY)
fp1, neg1 = T1.fp.get("fp") or {}, T1.fp.get("neg") or {}
chk(r1.n("/nfts/ethereum/") == 0 and r1.n("coingecko.com") == r1.n("/nfts/hyperevm/") >= 1,
    "T1 오픈시 키 + 코인게코 키 = 오픈시 체인 코인게코 0콜(바닥가·대체·폴백 · 키·무키) · 코인게코 콜은 전용 체인(hyperevm)만", r1.calls)
u1 = T1.budget.cg_usage()
chk(1 <= u1.get("nft") == u1.get("total") <= r1.n("coingecko.com"), "T2 코인게코 키 = NFT 칸(전용 체인)만 · 보장 0 이어도 남는 몫 씀(지난 24시간)", (u1, r1.n("coingecko.com")))
chk((fp1.get(keys["ok"]) or {}).get("src") == "os" and (fp1.get(keys["ok"]) or {}).get("native") == 0.5, "T3 오픈시 바닥가 = 오픈시 값", fp1.get(keys["ok"]))
chk((neg1.get(keys["miss"]) or {}).get("src") == "os" and keys["miss"] not in fp1, "T4 오픈시에 없음(404) = 시세 없음(부정 캐시 src os · 코인게코로 안 넘어감)", neg1.get(keys["miss"]))
chk(keys["bad"] not in neg1 and keys["bad"] not in fp1, "T5 오픈시 지속 오류 = 미확인(코인게코 폴백 없음 · '없음' 확정 안 함)", neg1.get(keys["bad"]))
th = fp1.get(keys["thin"]) or {}
chk(th.get("basis") == "last" and th.get("src") == "os" and abs(float(th.get("native") or 0) - 0.037) < 1e-9,
    "T6 리스팅 없음 = 오픈시 마지막 체결가(basis=last — 종전엔 코인게코 바닥가 먼저)", th)
chk((fp1.get(keys["hyp"]) or {}).get("src") == "cg" and (fp1.get(keys["hyp"]) or {}).get("native") == 1.0, "T7 코인게코 전용 체인(hyperevm) = 오픈시 키 있어도 코인게코 바닥가", fp1.get(keys["hyp"]))
T1.fp["cgkey"] = {"bad": True, "fp": nft._kfp(ENV_ON["TJ_COINGECKO_KEY"]), "at": CLOCK[0], "st": 401}
v1 = T1.view(CFG)
chk((T1.notice() or {}).get("kind") == "key_bad", "T8 오픈시 키 + 코인게코 키 거부 = 키 거부 안내(종전 — 전용 체인은 코인게코 키를 씀)", T1.notice())
chk({"hyperevm", "eth", "zksync", "sol"} <= set(v1["watch_chains"]), "T9 관심 체인 = 코인게코 ∪ 오픈시 체인 + 솔라나(종전)", v1["watch_chains"])

ENV_OFF = {"TJ_COINGECKO_KEY": "CG-demo-0000"}
CLOCK[0] += 30 * DAY
r2 = router()
T2 = mk(r2, "off", ENV_OFF)
k2 = {nm: add(T2, ch, ca) for nm, ch, ca in (("ok", "eth", OK), ("hyp", "hyperevm", HYP))}
run(T2, DAY)
fp2 = T2.fp.get("fp") or {}
chk(r2.n("/nfts/ethereum/contract/") >= 1 and r2.n("/nfts/hyperevm/contract/") >= 1 and r2.n("api.opensea.io") == 0,
    "T10 오픈시 키 없음 = 코인게코 NFT 호출(종전 · 오픈시 0콜)", (r2.n("coingecko.com"), r2.n("api.opensea.io")))
chk(T2.budget.cg_usage().get("nft", 0) >= 1, "T11 키 없음 = 코인게코 키 NFT 칸 사용(종전)", T2.budget.cg_usage())
chk((fp2.get(k2["ok"]) or {}).get("src") == "cg" and (fp2.get(k2["hyp"]) or {}).get("native") == 1.0, "T12 키 없음 = 코인게코 바닥가(eth·hyperevm)", fp2)
T2.fp["cgkey"] = {"bad": True, "fp": nft._kfp(ENV_OFF["TJ_COINGECKO_KEY"]), "at": CLOCK[0], "st": 401}
v2 = T2.view(CFG)
chk((T2.notice() or {}).get("kind") == "key_bad" and "hyperevm" in v2["watch_chains"], "T13 키 없음 = 키 거부 안내 · 관심 체인 코인게코 포함(종전)", (T2.notice(), v2["watch_chains"]))
chk(T2.budget.os_fn() == "" and T1.budget.os_fn() == "OSKEY-A", "T14 트래커가 만든 예산 = 그 트래커 env_fn 판정", (T1.budget.os_fn(), T2.budget.os_fn()))

CLOCK[0] += 30 * DAY
env3 = {}
r3 = router()
T3 = mk(r3, "race", env3)
ka, kb = add(T3, "eth", OK), add(T3, "eth", MISS)
T3.fetch_fp(ka, T3.hold["cols"][ka])
n_a = r3.n("coingecko.com")
T3.sleep = lambda s9: env3.__setitem__("TJ_OPENSEA_KEY", "OSKEY-LATE")
ob = T3.fetch_fp(kb, T3.hold["cols"][kb])
chk(n_a == 1 and r3.n("coingecko.com") == 1 and ob == "budget" and kb not in (T3.fp.get("neg") or {}),
    "T15 간격 대기 중 오픈시 키 저장 = 코인게코 NFT 안 보냄(예산·미확인 — 부정 캐시 아님)", (n_a, r3.n("coingecko.com"), ob))
st9, _d9 = T3._cg_get(f"{nft.CG_HOST}/api/v3/nfts/ethereum/contract/{OK}")
chk(st9 == nft.NOBUDGET and r3.n("coingecko.com") == 1, "T16 오픈시 키 있음 = 오픈시 체인 코인게코 NFT GET 자체가 0콜(키·무키 모두)", st9)
st9, _d9 = T3._cg_get(f"{nft.CG_HOST}/api/v3/nfts/hyperevm/contract/{HYP}")
chk(st9 == 200 and r3.n("/nfts/hyperevm/") == 1, "T17 오픈시 키 있음 = 전용 체인(hyperevm) 코인게코 NFT GET 은 그대로", st9)
CLOCK[0] += DAY
r4 = router()
T4 = mk(r4, "lean", {"TJ_OPENSEA_KEY": "OSKEY-A", "TJ_COINGECKO_KEY": "CG-demo-0000"})
k4 = add(T4, "hyperevm", HYP)
T4.budget.act["live"] = T4.budget.act["past"] = CLOCK[0]
o4 = T4.fetch_fp(k4, T4.hold["cols"][k4])
chk(o4 == "ok" and r4.n("/nfts/hyperevm/") == 1 and T4.budget.cg_usage().get("nft") == 0, "T18 키 NFT 몫 없음 = 무키 코인게코로 바닥가(키 칸 0)", (o4, T4.budget.cg_usage()))

H.finish()
