#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as H

import json
import os

import nft


def check(name, ok, d=""):
    H.chk(bool(ok), name, None if ok else str(d)[:600])


def guard(name, fn):
    try:
        return fn()
    except Exception as e:
        check(name + " (예외)", False, repr(e))
        return None


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

    def n_end(self, suffix, host="api.opensea.io"):
        return sum(1 for u in self.calls if host in u and u.split("?", 1)[0].endswith(suffix))


CLOCK = [1791000000.0]
DAY = 86400
NOW = 1791000000.0
_AB = {v: k for k, v in nft.AB_CONTRACTS["eth"].items()}
V0, V1, V3, FLEX = _AB["V0"], _AB["V1"], _AB["V3"], _AB["V3.2 Flex"]
OTHER = "0x" + "cd" * 20
W1, W2, EXT = "0x" + "11" * 20, "0x" + "22" * 20, "0x" + "9e" * 20
BS = "https://eth.bs.test"
CFG = {"wallets": [{"address": W1, "type": "evm", "chain": "eth", "label": "w1"}, {"address": W2, "type": "evm", "chain": "eth", "label": "w2"}],
       "chains": {"eth": {"blockscout": BS}}, "nft": {"enabled": True}}
K = lambda ca, p: f"eth:{ca}/p{p}"

TOK = {
    W1: [(V1, "7000001", "Seven #1"), (V1, "7000002", "Seven #2"), (V1, "7000003", "Seven #3"), (V1, "9000010", "Nine #10"),
         (V1, "9000011", "Nine #11"), (V1, "9000012", "Nine #12"), (V1, "12000005", "Twelve #5"), (OTHER, "1", "Other #1"), (OTHER, "2", "Other #2")],
    W2: [(V1, "7000004", "Seven #4"), (V1, "9000013", "Nine #13"), (V0, "1234", "Zero #1234"), (FLEX, "600000002", "Flex Six #2")],
}


def bs_nft(addr, toks=None):
    items = []
    for ca, tid, nm in (TOK[addr] if toks is None else toks):
        items.append({"token": {"address_hash": ca, "name": "Art Blocks" if ca != OTHER else "Other Coll", "symbol": "BLOCKS" if ca != OTHER else "OTH",
                                "type": "ERC-721", "holders_count": "39000", "total_supply": "190000", "reputation": "ok"},
                      "id": tid, "metadata": {"name": nm, "description": "generative · https://artist.example"},
                      "image_url": f"https://media.example/{ca}/{tid}.png"})
    return (200, {"items": items, "next_page_params": None})


def os_nft(ca, tid, slug, name):
    return (200, {"nft": {"collection": slug, "contract": ca, "identifier": tid, "name": name, "image_url": "https://img.example/x.png"}})


def os_stats(floor, d1=0.0, s1=0, d7=0.0, s7=0, s30=0):
    return (200, {"total": {"volume": 100.0, "sales": 50, "floor_price": floor, "floor_price_symbol": "ETH"},
                  "intervals": [{"interval": "one_day", "volume": d1, "sales": s1}, {"interval": "seven_day", "volume": d7, "sales": s7},
                                {"interval": "thirty_day", "volume": 0.0, "sales": s30}]})


def os_event(ts, wei="37000000000000000"):
    def f(url):
        slug = url.split("/events/collection/", 1)[1].split("?", 1)[0]
        return (200, {"asset_events": [{"event_type": "sale", "event_timestamp": int(ts), "closing_date": int(ts), "quantity": 1, "nft": {"collection": slug},
                                        "payment": {"quantity": wei, "token_address": "0x" + "0" * 40, "decimals": 18, "symbol": "ETH"}}], "next": None})
    return f


CG_WRONG = (200, {"floor_price": {"native_currency": 9.9, "usd": 30000}, "native_currency_symbol": "ETH", "volume_24h": {"native_currency": 50.0},
                  "id": "art-blocks-contract-level"})


def base_router():
    r = Router()
    for w in (W1, W2):
        r.on(f"{BS}/api/v2/addresses/{w}/nft", bs_nft(w))
        r.on(f"{BS}/api/v2/addresses/{w}/token-balances", (200, []))
    for ca in (V0, V1, V3, FLEX):
        r.on(f"api.opensea.io/api/v2/chain/ethereum/contract/{ca}", (200, {"collection": "shared-contract-slug"}))
        r.on(f"api.coingecko.com/api/v3/nfts/ethereum/contract/{ca}", CG_WRONG)
    for tid, slug, nm in (("7000001", "seven-by-a", "Seven #1"), ("7000004", "seven-by-a", "Seven #4"), ("9000010", "nine-by-b", "Nine #10"),
                          ("9000013", "nine-by-b", "Nine #13"), ("12000005", "twelve-by-c", "Twelve #5")):
        r.on(f"api.opensea.io/api/v2/chain/ethereum/contract/{V1}/nfts/{tid}", os_nft(V1, tid, slug, nm))
    r.on(f"api.opensea.io/api/v2/chain/ethereum/contract/{V0}/nfts/1234", os_nft(V0, "1234", "zero-by-z", "Zero #1234"))
    r.on(f"api.opensea.io/api/v2/chain/ethereum/contract/{FLEX}/nfts/600000002", os_nft(FLEX, "600000002", "flex-six", "Flex Six #2"))
    r.on("api.opensea.io/api/v2/collections/seven-by-a/stats", os_stats(1.5, d1=3.0, s1=2))
    r.on("api.opensea.io/api/v2/collections/nine-by-b/stats", os_stats(0.2, d7=0.4, s7=2))
    r.on("api.opensea.io/api/v2/collections/twelve-by-c/stats", os_stats(0.05, s30=4))
    r.on("api.opensea.io/api/v2/collections/zero-by-z/stats", os_stats(2.0, d1=6.0, s1=3))
    r.on("api.opensea.io/api/v2/collections/flex-six/stats", os_stats(4.2, d1=2.4, s1=1))
    r.on("api.opensea.io/api/v2/events/collection/", os_event(CLOCK[0] - 10 * DAY))
    r.on(f"{BS}/api/v2/tokens/", (200, {"items": []}))
    return r


def mk(r, d, env=None, cfg=None):
    os.makedirs(os.path.join(H.TMP, d), exist_ok=True)
    env = {"TJ_OPENSEA_KEY": "OSKEY-A"} if env is None else env
    kw = {k + "_path": os.path.join(H.TMP, d, k + ".json") for k in ("hold", "fp", "prefs")}
    return nft.Tracker(cfg_fn=lambda: (cfg or CFG), px_fn=lambda s: 2700.0 if s == "ETH" else None, rate_fn=lambda: 1400.0, http=r,
                       sleep=lambda s: None, now=lambda: CLOCK[0], env_fn=lambda k: env.get(k, ""), gate_fn=lambda: {},
                       budget_path=os.path.join(H.TMP, d, "budget.json"), **kw)


def pair_items(T, pk):
    return (T.hold["pairs"].get(pk) or {}).get("items") or {}


def row_of(v, key):
    for sec in ("tracked", "candidates", "hidden", "watch"):
        for r in v.get(sec) or []:
            if r.get("key") == key:
                return sec, r
    for r in (v.get("spam") or {}).get("items") or []:
        if r.get("key") == key:
            return "spam", r
    return None, None


try:
    print("[A] 공유 계약 = 토큰 ID 로 시리즈 키 · 시리즈별 개수(대표 ids 5개 상한과 무관) · 여러 지갑")
    r = base_router()
    T = mk(r, "a")
    CLOCK[0] = 1791000000.0
    guard("A scan", lambda: T.scan())
    i1, i2 = pair_items(T, f"eth:{W1}"), pair_items(T, f"eth:{W2}")
    check("A1 W1 시리즈 키 3개(p7·p9·p12) + 다른 계약 그대로 · 계약 단위 키 없음",
          set(i1) == {K(V1, 7), K(V1, 9), K(V1, 12), f"eth:{OTHER}"}, sorted(i1))
    check("A2 W1 시리즈 개수 3·3·1 (7개 = 대표 ids 5개 넘어도 정확)", [i1.get(K(V1, p), {}).get("n") for p in (7, 9, 12)] == [3, 3, 1],
          {k: v.get("n") for k, v in i1.items()})
    check("A3 W2 = V1 p7·p9 + V0 p0 + FLEX p600", set(i2) == {K(V1, 7), K(V1, 9), K(V0, 0), K(FLEX, 600)}, sorted(i2))
    check("A4 대표 ids 는 전부 그 시리즈 토큰", all(nft.tid_in(t, nft.ser_parse(k)[2]) for it in (i1, i2) for k, a in it.items() if nft.ser_parse(k)
                                              for t in a.get("ids") or []) if hasattr(nft, "tid_in") else False)
    c7 = T.hold["cols"].get(K(V1, 7)) or {}
    check("A5 시리즈 메타: 이름 'Seven'(#번호 뗌) · ca = 계약/p7 · pca · proj · 보유자 비움 · 평판 ok · sample 은 시리즈 토큰",
          c7.get("name") == "Seven" and c7.get("ca") == f"{V1}/p7" and c7.get("pca") == V1 and c7.get("proj") == 7 and c7.get("holders") is None
          and c7.get("rep") == "ok" and str(c7.get("sample") or "").startswith("700000"), c7)
    check("A6 키 모양 = KEY_RE 허용(설정 API 통과)", all(nft.KEY_RE.match(k) for k in (K(V1, 7), K(FLEX, 600), K(V0, 0))))
    v = guard("A view", lambda: T.view(CFG)) or {}
    cnt = {k: (row_of(v, k)[1] or {}).get("count") for k in (K(V1, 7), K(V1, 9), K(V1, 12), K(V0, 0), K(FLEX, 600))}
    check("A7 화면 개수(지갑 합산) p7=4 · p9=4 · p12=1 · V0 p0=1 · FLEX p600=1", cnt == {K(V1, 7): 4, K(V1, 9): 4, K(V1, 12): 1, K(V0, 0): 1, K(FLEX, 600): 1}, cnt)

except Exception as _e:
    import traceback as _tb
    check('절 실행(예외)', False, _tb.format_exc()[-600:])
try:
    print("[B] 시세 = 오픈시 토큰 단위(nfts/{id} → 슬러그 → 통계) · 계약 단위 슬러그·코인게코 금지 · 시리즈마다 다른 바닥가")
    outs = {}
    for k in (K(V1, 7), K(V1, 9), K(V1, 12), K(V0, 0), K(FLEX, 600)):
        outs[k] = guard("B fetch " + k[-6:], lambda k=k: T.fetch_fp(k, T.hold["cols"][k]))
    fpm = T.fp.get("fp") or {}
    check("B1 다섯 시리즈 모두 ok", all(o == "ok" for o in outs.values()), outs)
    check("B2 바닥가 = 시리즈 값(1.5 · 0.2 · 0.05 · 2.0 · 4.2)", [(fpm.get(k) or {}).get("native") for k in outs] == [1.5, 0.2, 0.05, 2.0, 4.2],
          [(fpm.get(k) or {}).get("native") for k in outs])
    check("B3 계약 단위 /contract/{계약} 0콜 · 코인게코 0콜", sum(r.n_end(f"/contract/{ca}") for ca in (V0, V1, FLEX)) == 0 and r.n("coingecko") == 0,
          [u for u in r.calls if "coingecko" in u or u.split("?")[0].endswith(("/contract/" + V1, "/contract/" + V0))])
    check("B4 기록에 시리즈 확인 표식(ser = 키) · 출처 os", all((fpm.get(k) or {}).get("ser") == k and (fpm.get(k) or {}).get("src") == "os" for k in outs),
          {k: (fpm.get(k) or {}).get("ser") for k in outs})
    mp = (T.fp.get("map") or {}).get(K(V1, 7)) or {}
    check("B5 매핑 = 슬러그·계약·토큰 ID(시리즈 토큰)", mp.get("os") == "seven-by-a" and mp.get("ca") == V1 and nft.tid_in(mp.get("tid"), 7) if hasattr(nft, "tid_in") else False, mp)
    n0 = len(r.calls)
    CLOCK[0] += 1000
    guard("B fetch again", lambda: T.fetch_fp(K(V1, 7), T.hold["cols"][K(V1, 7)]))
    check("B6 두 번째 = 슬러그 캐시(통계 1콜만)", len(r.calls) - n0 == 1 and "stats" in r.calls[-1], r.calls[n0:])
    v = guard("B view", lambda: T.view(CFG)) or {}
    s7, r7 = row_of(v, K(V1, 7))
    check("B7 p7 추적(자동) · 평가 = 1.5 × 4 × 2700", s7 == "tracked" and abs(((r7 or {}).get("value") or {}).get("usd", 0) - 1.5 * 4 * 2700) < 1e-6, (s7, (r7 or {}).get("value")))
    s12, r12 = row_of(v, K(V1, 12))
    check("B8 p12(30일 체결 4건 · 24h·7일 없음) = 거래 뜸 자동(thin) · 플랫폼 계약이라 경위 없이도",
          s12 == "tracked" and (r12 or {}).get("reason") == "thin", (s12, (r12 or {}).get("reason")))
    check("B9 화면 줄: series{plat, ver, proj} · 탐색기 링크 = 계약?a=내 토큰 · trade(30일 안 4건)",
          ((r7 or {}).get("series") or {}).get("proj") == 7 and ((r7 or {}).get("links") or {}).get("explorer", "").startswith("https://etherscan.io/token/" + V1 + "?a=700000")
          and ((r12 or {}).get("trade") or {}).get("within") == 30 and ((r12 or {}).get("trade") or {}).get("n") == 4, ((r7 or {}).get("links"), (r12 or {}).get("trade")))
    check("B10 view.sources.opensea.verified = True(실측 갱신) · every 900", ((v.get("sources") or {}).get("opensea") or {}).get("verified") is True
          and ((v.get("sources") or {}).get("opensea") or {}).get("every") == 900, (v.get("sources") or {}).get("opensea"))

    print("[B'] 실패 경로 — 오픈시 404·429·5xx·키 없음·예산 소진 + 코인게코 200 이어도 다른 값이 섞이지 않음")
    for name, resp in (("404", (404, None)), ("429", (429, None)), ("5xx", (502, None))):
        rb = base_router()
        rb.on(f"api.opensea.io/api/v2/chain/ethereum/contract/{V1}/nfts/9000010", resp)
        rb.on(f"api.opensea.io/api/v2/chain/ethereum/contract/{V1}/nfts/9000013", resp)
        Tb = mk(rb, "b" + name)
        guard("B' scan", lambda: Tb.scan())
        o = guard("B' fetch", lambda: Tb.fetch_fp(K(V1, 9), Tb.hold["cols"][K(V1, 9)]))
        fb = (Tb.fp.get("fp") or {}).get(K(V1, 9))
        hb = (Tb.fp.get("hist") or {}).get(K(V1, 9))
        ng = (Tb.fp.get("neg") or {}).get(K(V1, 9)) or {}
        want = {"404": "none", "429": "budget", "5xx": "err"}[name]
        check(f"B'{name} 결과 {want} · fp·hist 없음 · 코인게코·계약 단위 0콜" + (" · 부정 캐시 src os" if name == "404" else ""),
              o == want and fb is None and not hb and rb.n("coingecko") == 0 and rb.n_end(f"/contract/{V1}") == 0
              and (name != "404" or ng.get("src") == "os"), (o, fb, hb, ng, rb.calls))
        if name == "404":
            mp9 = (Tb.fp.get("map") or {}).get(K(V1, 9)) or {}
            check("B'404 실패 매핑 = 빈 슬러그 + 키 지문 + 재시도 기한", mp9.get("os") == "" and mp9.get("okf") == nft._kfp("OSKEY-A") and mp9.get("retry", 0) > CLOCK[0], mp9)
    rk = base_router()
    Tk = mk(rk, "bnokey", env={})
    guard("B' scan nokey", lambda: Tk.scan())
    o = guard("B' fetch nokey", lambda: Tk.fetch_fp(K(V1, 7), Tk.hold["cols"][K(V1, 7)]))
    check("B'nokey 키 없음 = 0콜(코인게코로 넘기지 않음) · fp 없음 · 부정 캐시 없음", rk.n("opensea") == 0 and rk.n("coingecko") == 0
          and not (Tk.fp.get("fp") or {}).get(K(V1, 7)) and not (Tk.fp.get("neg") or {}).get(K(V1, 7)), (o, rk.calls))
    rbud = base_router()
    Tbud = mk(rbud, "bbudget")
    guard("B' scan budget", lambda: Tbud.scan())
    Tbud.budget.take = lambda key, wins=None: key != "opensea"
    o = guard("B' fetch budget", lambda: Tbud.fetch_fp(K(V1, 7), Tbud.hold["cols"][K(V1, 7)]))
    check("B'budget 오픈시 예산 끝 = budget · 코인게코 0콜 · '봤다'로 안 침", o == "budget" and rbud.n("coingecko") == 0
          and K(V1, 7) not in (Tbud.fp.get("chk") or {}), (o, rbud.calls))
    print("[B''] 직전 값 보존 — 같은 시리즈로 확인한 값만 낡음 표시로 · 표식 없는 값(계약 단위·구버전)은 버림")
    T.fp["fp"][K(V1, 9)]["at"] = CLOCK[0] - 5000
    r.on(f"api.opensea.io/api/v2/collections/nine-by-b/stats", (503, None))
    o = guard("B'' fetch err", lambda: T.fetch_fp(K(V1, 9), T.hold["cols"][K(V1, 9)]))
    f9 = (T.fp.get("fp") or {}).get(K(V1, 9)) or {}
    check("B''1 오류 = 직전 시리즈 값 0.2 유지 + err 표식", o == "err" and f9.get("native") == 0.2 and f9.get("err") == "err", (o, f9))
    T.fp["fp"][K(V1, 9)] = {"src": "os", "native": 9.9, "sym": "ETH", "at": CLOCK[0], "id": "shared-contract-slug"}
    v = guard("B'' view", lambda: T.view(CFG)) or {}
    s9, r9 = row_of(v, K(V1, 9))
    check("B''2 표식 없는 값 = 화면 평가에 안 씀(시세 없음)", (r9 or {}).get("value") is None and (r9 or {}).get("fp") is None, (s9, (r9 or {}).get("fp")))
    guard("B'' fetch drop", lambda: T.fetch_fp(K(V1, 9), T.hold["cols"][K(V1, 9)]))
    check("B''3 다음 조회(오류)에서 표식 없는 값·기록 삭제", K(V1, 9) not in (T.fp.get("fp") or {}) and not (T.fp.get("hist") or {}).get(K(V1, 9)),
          (T.fp.get("fp") or {}).get(K(V1, 9)))
    tot = (v.get("totals") or {})
    check("B''4 합계에 9.9(다른 값) 없음", all(abs(((row_of(v, k)[1] or {}).get("value") or {}).get("native", 0) - 9.9 * 4) > 1e-6 for k in (K(V1, 9),)), tot)

except Exception as _e:
    import traceback as _tb
    check('절 실행(예외)', False, _tb.format_exc()[-600:])
try:
    print("[C] ④ 여러 수령자 거래 — 평판 ok·플랫폼 계약 = 후보(시세 확인) · 그 밖 = 스팸 그대로 · 강한 스팸·숨김 유지")
    colP = {"chain": "eth", "ca": f"{FLEX}/p600", "pca": FLEX, "proj": 600, "name": "Flex Six", "rep": "ok"}
    colN = {"chain": "eth", "ca": OTHER, "name": "Other", "rep": "ok"}
    acqM = {"kind": "airdrop_mass", "n": 44, "tries": 1}
    check("C1 플랫폼(시세 없음) + 대량 = 후보 platform_airdrop", nft.classify(colP, None, acqM) == ("candidate", "platform_airdrop"), nft.classify(colP, None, acqM))
    check("C2 일반 계약 + 대량 = 스팸 mass_airdrop(종전)", nft.classify(colN, None, acqM) == ("spam", "mass_airdrop"))
    check("C3 플랫폼이어도 평판 미확인(rep 없음) = 스팸(평판 ok 일 때만)", nft.classify(dict(colP, rep=None), None, acqM)[0] == "spam")
    check("C4 플랫폼이어도 이름 미끼(강한 스팸) = 스팸", nft.classify(dict(colP, name="claim reward at evil.xyz"), None, acqM)[0] == "spam")
    check("C5 플랫폼 + 남이 보냄 = 후보 · 설명의 작가 링크는 미끼로 안 봄", nft.classify(dict(colP, desc="see https://artist.example"), None, {"kind": "received"}) ==
          ("candidate", "platform_received"))
    rc = base_router()
    Tc = mk(rc, "c")
    guard("C scan", lambda: Tc.scan())
    Tc.hold["acq"][K(FLEX, 600)] = dict(acqM)
    Tc.fp.setdefault("chk", {})[K(FLEX, 600)] = CLOCK[0] - 7 * DAY
    due = [k for k, _c in (guard("C due", lambda: Tc.due_fp()) or [])]
    check("C6 due_fp: 한 번 봤고 시세 없고 대량 수령이어도 플랫폼 = 다시 조회", K(FLEX, 600) in due, due)
    Tc.hold["cols"]["eth:" + OTHER]["rep"] = "ok"
    Tc.hold["acq"]["eth:" + OTHER] = dict(acqM)
    Tc.fp["chk"]["eth:" + OTHER] = CLOCK[0] - 7 * DAY
    due = [k for k, _c in (guard("C due2", lambda: Tc.due_fp()) or [])]
    check("C7 일반 계약 대량 수령(시세 없음·봤음) = 다시 안 부름(종전)", "eth:" + OTHER not in due, due)
    pf = json.load(open(Tc.prefs_path)) if os.path.exists(Tc.prefs_path) else nft.empty_prefs()
    pf["hidden"] = [K(FLEX, 600)]
    nft.atomic_write(Tc.prefs_path, pf)
    due = [k for k, _c in (guard("C due3", lambda: Tc.due_fp()) or [])]
    check("C8 사용자 숨김 = 플랫폼이어도 안 부름", K(FLEX, 600) not in due, due)

except Exception as _e:
    import traceback as _tb
    check('절 실행(예외)', False, _tb.format_exc()[-600:])
try:
    print("[D] ③ 오픈시 키가 새로 생기거나 바뀌면 — 코인게코 부정 캐시·실패 매핑을 한 번 풀어 오픈시로 다시 · 성공 매핑·숨김·강한 스팸 보존 · 재시작 중복 없음")
    KA, KB, KC, KH, KS = ("eth:0x" + x * 20 for x in ("a1", "a2", "a3", "a4", "a5"))
    rd = Router()
    rd.on("api.opensea.io/api/v2/chain/ethereum/contract/0x" + "a1" * 20, (200, {"address": "0x" + "a1" * 20, "collection": "coll-a1"}))
    rd.on("api.opensea.io/api/v2/chain/ethereum/contract/0x" + "a2" * 20, (200, {"address": "0x" + "a2" * 20, "collection": "coll-a2"}))
    rd.on("api.opensea.io/api/v2/collections/coll-a1/stats", os_stats(0.7, d1=1.0, s1=1))
    rd.on("api.opensea.io/api/v2/collections/coll-a2/stats", os_stats(0.3, d7=1.0, s7=1))
    rd.on("api.opensea.io/api/v2/collections/coll-a3/stats", (200, {"total": {"floor_price": None}, "intervals": []}))
    rd.on("api.opensea.io/api/v2/events/collection/", (200, {"asset_events": [], "next": None}))
    rd.on("api.coingecko.com", (404, None))
    env = {"TJ_OPENSEA_KEY": ""}
    Td = mk(rd, "d", env=env)
    for k9 in (KA, KB, KC, KH, KS):
        ca9 = k9.split(":")[1]
        Td.hold["cols"][k9] = {"chain": "eth", "ca": ca9, "name": "Coll " + ca9[2:6], "rep": "ok"}
        Td.hold["pairs"].setdefault(f"eth:{W1}", {"items": {}, "at": CLOCK[0], "err": None})["items"][k9] = {"n": 1, "ids": ["1"]}
        Td.fp["neg"][k9] = {"until": CLOCK[0] + 5 * DAY, "src": "cg"}
        Td.fp["chk"][k9] = CLOCK[0] - DAY
    Td.hold["cols"][KS]["name"] = "visit evil.xyz claim"
    Td.fp["map"][KB] = {"os": ""}
    Td.fp["map"][KC] = {"os": "coll-a3", "at": CLOCK[0]}
    pf = nft.empty_prefs()
    pf["hidden"] = [KH]
    nft.atomic_write(Td.prefs_path, pf)
    Td.save()
    n = guard("D sync nokey", lambda: Td._os_sync_key())
    check("D1 키 없음 = 아무것도 안 풂", n == 0 and all(k9 in Td.fp["neg"] for k9 in (KA, KB, KC)), n)
    env["TJ_OPENSEA_KEY"] = "OSKEY-A"
    n = guard("D sync A", lambda: Td._os_sync_key())
    check("D2 키 생김 = 오픈시 못 물은 부정 캐시(KA)·옛 실패 매핑(KB) 풂 · 성공 매핑(KC) 보존", KA not in Td.fp["neg"] and KB not in Td.fp["neg"]
          and KC in Td.fp["neg"] and "os" not in (Td.fp["map"].get(KB) or {}) and (Td.fp["map"].get(KC) or {}).get("os") == "coll-a3", (n, sorted(Td.fp["neg"])))
    CLOCK[0] += 60
    n0 = len(rd.calls)
    guard("D refresh", lambda: Td.refresh_fp())
    check("D3 다시 물어 시세 회복(KA 0.7 · KB 0.3 · 출처 os)", (Td.fp["fp"].get(KA) or {}).get("native") == 0.7 and (Td.fp["fp"].get(KB) or {}).get("native") == 0.3,
          (Td.fp["fp"].get(KA), Td.fp["fp"].get(KB), rd.calls[n0:]))
    check("D4 숨김(KH)·강한 스팸(KS) = 0콜", not any(("0x" + "a4" * 20) in u or ("0x" + "a5" * 20) in u for u in rd.calls), rd.calls)
    Td2 = mk(rd, "d", env=env)
    CLOCK[0] += 60
    n1 = len(rd.calls)
    guard("D refresh after restart", lambda: Td2.refresh_fp())
    check("D5 재시작 뒤 = 다시 풀지 않음 · 중복 호출 0", len(rd.calls) == n1 and Td2.fp.get("oskey", {}).get("fp") == nft._kfp("OSKEY-A"), rd.calls[n1:])
    Td2.fp["map"][KA] = {"os": "", "okf": nft._kfp("OSKEY-A"), "at": CLOCK[0], "retry": CLOCK[0] + 5 * DAY}
    Td2.fp["fp"].pop(KA, None)
    Td2.fp["chk"].pop(KA, None)
    n2 = len(rd.calls)
    guard("D fetch same key", lambda: Td2.fetch_fp(KA, Td2.hold["cols"][KA]))
    check("D6 같은 키·기한 안 실패 매핑 = 계약 조회 0콜", rd.n_end("/contract/0x" + "a1" * 20) == 1 and all("a1" * 20 not in u or "coingecko" in u for u in rd.calls[n2:]),
          rd.calls[n2:])
    env["TJ_OPENSEA_KEY"] = "OSKEY-B"
    CLOCK[0] += 60
    Td2.fp["neg"].pop(KA, None)
    n3 = len(rd.calls)
    guard("D refresh key B", lambda: Td2.refresh_fp())
    check("D7 키 교체 = 실패 매핑 한 번 다시 확인 → 시세 회복", rd.n_end("/contract/0x" + "a1" * 20) == 2 and (Td2.fp["fp"].get(KA) or {}).get("native") == 0.7,
          rd.calls[n3:])

except Exception as _e:
    import traceback as _tb
    check('절 실행(예외)', False, _tb.format_exc()[-600:])
try:
    print("[E] 거래 뜸 — 90일 안 = 자동·총자산 · 90~365일 = 자동·총자산 제외 · 365일+ = 후보 · 믿을 근거(내가 산 것·플랫폼·정상으로) 없으면 후보")
    NOW = 1791000000.0
    colX = {"chain": "eth", "ca": "0x" + "e1" * 20, "name": "Thin Coll", "rep": "ok"}
    rec = lambda **kw: dict({"src": "os", "native": 0.1, "sym": "ETH", "vol24": 0.0, "vol7": 0.0, "sales24": 0, "sales7": 0, "sales30": 0, "at": NOW}, **kw)
    bought = {"kind": "bought"}
    check("E1 30일 체결 3건 + 산 것 = 자동 thin", nft.classify(colX, rec(sales30=3), bought, now=NOW) == ("auto", "thin"),
          guard("E1", lambda: nft.classify(colX, rec(sales30=3), bought, now=NOW)))
    check("E2 마지막 체결 120일 전 = 자동 thin_old", guard("E2", lambda: nft.classify(colX, rec(last={"at": NOW - 120 * DAY}), bought, now=NOW)) == ("auto", "thin_old"))
    check("E3 마지막 체결 400일 전 = 후보 price_no_volume", guard("E3", lambda: nft.classify(colX, rec(last={"at": NOW - 400 * DAY}), bought, now=NOW)) == ("candidate", "price_no_volume"))
    check("E4 근거 없음(체결 기록 없음) = 후보", guard("E4", lambda: nft.classify(colX, rec(), bought, now=NOW)) == ("candidate", "price_no_volume"))
    check("E5 남이 보낸 것(믿을 근거 없음) + 30일 체결 = 후보", guard("E5", lambda: nft.classify(colX, rec(sales30=3), {"kind": "received"}, now=NOW)) == ("candidate", "price_no_volume"))
    check("E6 '정상으로' = 근거 → thin", guard("E6", lambda: nft.classify(colX, rec(sales30=3), {"kind": "received"}, trust=True, now=NOW)) == ("auto", "thin"))
    check("E7 바닥가 없이 마지막 체결가(basis last) + 산 것 + 20일 = 자동 thin",
          guard("E7", lambda: nft.classify(colX, rec(basis="last", last={"at": NOW - 20 * DAY, "px": 0.04}), bought, now=NOW)) == ("auto", "thin"))
    check("E8 basis last + 남이 보냄 = 시세로 안 침 → 종전 스팸 규칙(free_noprice)",
          guard("E8", lambda: nft.classify(colX, rec(basis="last", last={"at": NOW - 20 * DAY, "px": 0.04}), {"kind": "received"}, now=NOW)) == ("spam", "free_noprice"))
    check("E9 거래량 있으면 종전 priced", guard("E9", lambda: nft.classify(colX, rec(vol24=1.0), None, now=NOW)) == ("auto", "priced"))
    check("E10 last_trade: 30일 안 체결 + 이벤트 10일 전 = 정확히 10일", (guard("E10", lambda: nft.last_trade(rec(sales30=2, last={"at": NOW - 10 * DAY, "px": 0.05}), NOW)) or {}).get("days") == 10)
    re_ = base_router()
    Te = mk(re_, "e")
    CLOCK[0] = NOW
    for nm9, k9, r9 in (("Fresh", "eth:0x" + "e2" * 20, rec(sales30=3)), ("Old", "eth:0x" + "e3" * 20, rec(last={"at": NOW - 200 * DAY})),
                        ("Ancient", "eth:0x" + "e4" * 20, rec(last={"at": NOW - 500 * DAY}))):
        Te.hold["cols"][k9] = {"chain": "eth", "ca": k9.split(":")[1], "name": nm9, "rep": "ok"}
        Te.hold["pairs"].setdefault(f"eth:{W1}", {"items": {}, "at": NOW, "err": None})["items"][k9] = {"n": 2, "ids": ["1", "2"]}
        Te.hold["acq"][k9] = {"kind": "bought", "tries": 1}
        Te.fp["fp"][k9] = dict(r9, at=NOW)
    pf = nft.empty_prefs()
    pf["include_in_total"] = True
    nft.atomic_write(Te.prefs_path, pf)
    v = guard("E view", lambda: Te.view(CFG)) or {}
    t9 = v.get("totals") or {}
    u_one = 0.1 * 2 * 2700
    check("E11 자동 2개(Fresh thin · Old thin_old) · Ancient 후보", [row_of(v, "eth:0x" + x * 20)[0] for x in ("e2", "e3", "e4")] == ["tracked", "tracked", "candidates"],
          [row_of(v, "eth:0x" + x * 20)[0] for x in ("e2", "e3", "e4")])
    check("E12 추적 평가 = 둘 다 · 총자산 포함분 = Fresh 만(old_n 1)", abs((t9.get("usd") or 0) - 2 * u_one) < 1e-6 and abs((t9.get("incl_usd") or 0) - u_one) < 1e-6
          and t9.get("old_n") == 1, t9)
    pf["promoted"] = ["eth:0x" + "e3" * 20]
    nft.atomic_write(Te.prefs_path, pf)
    v = guard("E view2", lambda: Te.view(CFG)) or {}
    check("E13 사용자가 직접 추적에 넣은 thin_old = 총자산 포함", abs(((v.get("totals") or {}).get("incl_usd") or 0) - 2 * u_one) < 1e-6, v.get("totals"))
    _s, rF = row_of(v, "eth:0x" + "e2" * 20)
    check("E14 화면 줄 trade(30일 안 3건) · reason thin", ((rF or {}).get("trade") or {}).get("n") == 3 and (rF or {}).get("reason") == "thin", rF and rF.get("trade"))
    rl = Router()
    rl.on("api.opensea.io/api/v2/collections/thin-x/stats", os_stats(0.1))
    rl.on("api.opensea.io/api/v2/collections/busy-x/stats", os_stats(0.1, s30=2))
    rl.on("api.opensea.io/api/v2/events/collection/thin-x", os_event(NOW - 40 * DAY))
    Tl = mk(rl, "l")
    rr, o = Tl._fp_os_slug("thin-x", "eth:0x" + "f1" * 20) if hasattr(Tl, "_os_last") else (None, None)
    check("E15 거래 뜸 = 이벤트 1콜 → last(40일 전 · 0.037)", rl.n("events/collection/thin-x") == 1 and ((rr or {}).get("last") or {}).get("px") == 0.037, (rr, rl.calls))
    if rr:
        Tl.fp["fp"]["eth:0x" + "f1" * 20] = dict(rr, at=NOW)
    CLOCK[0] = NOW + 3600
    guard("E16", lambda: Tl._fp_os_slug("thin-x", "eth:0x" + "f1" * 20))
    check("E16 하루 안 다시 = 이벤트 0콜(직전 값)", rl.n("events/collection/thin-x") == 1, rl.calls)
    guard("E17", lambda: Tl._fp_os_slug("busy-x", "eth:0x" + "f2" * 20))
    check("E17 30일 체결 있음 = 이벤트 안 부름", rl.n("events/collection/busy-x") == 0, rl.calls)

except Exception as _e:
    import traceback as _tb
    check('절 실행(예외)', False, _tb.format_exc()[-600:])
try:
    print("[F] 주기 — 오픈시: 추적 15분 · 그 밖 6시간 · 코인게코 출처는 종전(매시·하루) · 루프 대기")
    CLOCK[0] = NOW
    rf = base_router()
    Tf = mk(rf, "f")
    guard("F scan", lambda: Tf.scan())
    for k9 in (K(V1, 7), K(V1, 12)):
        Tf.fetch_fp(k9, Tf.hold["cols"][k9])
    kcg = "eth:0x" + "c9" * 20
    Tf.hold["cols"][kcg] = {"chain": "eth", "ca": kcg.split(":")[1], "name": "CG coll", "rep": "ok"}
    Tf.fp["fp"][kcg] = {"src": "cg", "native": 1.0, "sym": "ETH", "vol24": 5.0, "at": NOW}
    Tf.fp["chk"][kcg] = NOW
    CLOCK[0] = NOW + 600
    due = {k for k, _c in (guard("F due 600", lambda: Tf.due_fp()) or [])}
    check("F1 10분 뒤 = 추적 시리즈 아직", K(V1, 7) not in due, sorted(due))
    CLOCK[0] = NOW + 901
    due = {k for k, _c in (guard("F due 901", lambda: Tf.due_fp()) or [])}
    check("F2 15분 뒤 = 추적 시리즈(p7 자동·p12 thin 자동) 다시 · 코인게코 출처 추적은 아직(매시)", {K(V1, 7), K(V1, 12)} <= due and kcg not in due, sorted(due))
    CLOCK[0] = NOW + 3601
    due = {k for k, _c in (guard("F due 3601", lambda: Tf.due_fp()) or [])}
    check("F3 1시간 뒤 = 코인게코 출처 추적도", kcg in due, sorted(due))
    ko = "eth:0x" + "c8" * 20
    Tf.hold["cols"][ko] = {"chain": "eth", "ca": ko.split(":")[1], "name": "cand", "rep": "ok"}
    Tf.hold["acq"][ko] = {"kind": "bought", "tries": 1}
    Tf.fp["fp"][ko] = {"src": "os", "native": 1.0, "sym": "ETH", "at": NOW}
    Tf.fp["chk"][ko] = NOW
    CLOCK[0] = NOW + 5 * 3600
    check("F4 후보(오픈시) 5시간 = 아직", ko not in {k for k, _c in Tf.due_fp()})
    CLOCK[0] = NOW + 6 * 3600 + 1
    check("F5 후보(오픈시) 6시간 = 다시(종전 하루)", ko in {k for k, _c in Tf.due_fp()})
    check("F6 루프 대기: 키 있음 900 · 없음 3600 · 설정이 깨움 30", guard("F6", lambda: (Tf._loop_wait(), mk(rf, "f2", env={})._loop_wait())) == (900.0, 3600.0))
    Tf.urgent.add(ko)
    check("F7 urgent = 30", guard("F7", lambda: Tf._loop_wait()) == 30.0)
    Tf.urgent.clear()
    check("F8 오픈시 예산 = 시간당 450(공표 600/h 의 80% 안 · 설정 시험 몫 남김)", nft.BUDGET["opensea"] == (450, 3600), nft.BUDGET["opensea"])

except Exception as _e:
    import traceback as _tb
    check('절 실행(예외)', False, _tb.format_exc()[-600:])
try:
    print("[G] 이관 — 전체 보유 목록으로 다시 읽기 · 설정 잇기 · 사본 · 반복 기동 · 중간 실패 · 재시작")
    CLOCK[0] = NOW
    GD = os.path.join(H.TMP, "g")
    os.makedirs(GD, exist_ok=True)
    old_hold = {"v": 1, "at": NOW - DAY, "scan": {}, "pairs": {
        f"eth:{W1}": {"items": {f"eth:{V1}": {"n": 7, "ids": ["7000001", "7000002", "7000003", "9000010", "9000011"]}, f"eth:{OTHER}": {"n": 2, "ids": ["1", "2"]}},
                      "at": NOW - DAY, "err": None, "src": "blockscout"},
        f"eth:{W2}": {"items": {f"eth:{V1}": {"n": 2, "ids": ["7000004", "9000013"]}, f"eth:{V0}": {"n": 1, "ids": ["1234"]}, f"eth:{FLEX}": {"n": 1, "ids": ["600000002"]}},
                      "at": NOW - DAY, "err": None, "src": "blockscout"}},
        "cols": {f"eth:{ca}": {"chain": "eth", "ca": ca, "name": "Art Blocks", "sym": "BLOCKS", "std": "ERC-721", "holders": 39000.0, "rep": "ok", "seen": NOW - DAY}
                 for ca in (V0, V1, FLEX)},
        "acq": {f"eth:{V1}": {"kind": "bought", "paid": 0.45, "sym": "ETH", "tries": 1}, f"eth:{FLEX}": {"kind": "airdrop_mass", "n": 44, "tries": 1}}}
    old_hold["cols"][f"eth:{OTHER}"] = {"chain": "eth", "ca": OTHER, "name": "Other Coll", "sym": "OTH", "std": "ERC-721", "rep": "ok", "seen": NOW - DAY}
    old_fp = {"v": 1, "fp": {f"eth:{V1}": {"src": "os", "native": 5.0, "sym": "ETH", "vol24": 9.0, "at": NOW - 100, "id": "shared-contract-slug"}},
              "neg": {f"eth:{V0}": {"until": NOW + 5 * DAY, "src": "cg"}, f"eth:{FLEX}": {"until": NOW + 5 * DAY, "src": "cg"}},
              "map": {f"eth:{V1}": {"os": "shared-contract-slug"}}, "hist": {f"eth:{V1}": [["2026-10-01", 5.0, 13500.0, 9.0]]}, "hosts": {},
              "chk": {f"eth:{V1}": NOW - 100, f"eth:{V0}": NOW - 100}, "cgkey": {}, "notify": {}}
    old_prefs = {"v": 1, "promoted": [f"eth:{V1}"], "hidden": [f"eth:{V0}"], "watch": [{"key": f"eth:{V3}", "chain": "eth", "ca": V3, "label": "", "added": 1}],
                 "notspam": [f"eth:{FLEX}"], "include_in_total": True, "updated": 1}
    for nm9, obj in (("hold", old_hold), ("fp", old_fp), ("prefs", old_prefs)):
        nft.atomic_write(os.path.join(GD, nm9 + ".json"), obj)
    orig = {nm9: open(os.path.join(GD, nm9 + ".json"), "rb").read() for nm9 in ("hold", "fp", "prefs")}
    rg = base_router()
    rg.on(f"{BS}/api/v2/addresses/{W2}/nft", (500, None))
    rg.on(f"{BS}/api/v2/tokens/{V1}/instances/7000001/transfers", (200, {"items": [{"to": {"hash": W1}, "from": {"hash": W2}, "transaction_hash": "0x" + "1" * 64,
                                                                             "total": {"token_id": "7000001"}, "token": {"address_hash": V1}}]}))
    rg.on(f"{BS}/api/v2/transactions/0x" + "1" * 64, (200, {"from": W2, "value": "0", "method": "transferFrom"}))
    rg.on(f"{BS}/api/v2/tokens/{V1}/instances/9000010/transfers", (200, {"items": [{"to": {"hash": W1}, "from": {"hash": EXT}, "transaction_hash": "0x" + "2" * 64,
                                                                             "total": {"token_id": "9000010"}, "token": {"address_hash": V1}}]}))
    rg.on(f"{BS}/api/v2/transactions/0x" + "2" * 64, (200, {"from": EXT, "value": "0", "method": "airdrop"}))
    rg.on(f"{BS}/api/v2/transactions/0x" + "2" * 64 + "/token-transfers",
          (200, {"items": [{"token": {"type": "ERC-721", "address_hash": V1}, "to": {"hash": "0x" + ("%040x" % (i + 1))}, "from": {"hash": EXT}} for i in range(30)]}))
    Tg = mk(rg, "g")
    v = guard("G view before", lambda: Tg.view(CFG)) or {}
    sP, rP = row_of(v, f"eth:{V1}")
    check("G1 이관 전 화면: 계약 단위 V1 = 시리즈 나누는 중(추적에 올렸어도 평가 없음 · 대기로 안 셈 — 순자산 안 막음) · 5.0 값 안 씀",
          (rP or {}).get("reason") == "ab_split" and (rP or {}).get("value") is None and (v.get("totals") or {}).get("pending") == 0
          and ((rP or {}).get("series") or {}).get("split") is True, (sP, rP and rP.get("reason"), v.get("totals")))
    out = guard("G run1", lambda: Tg.run_once()) or {}
    for nm9, path in (("hold", Tg.hold_path), ("fp", Tg.fp_path), ("prefs", Tg.prefs_path)):
        b9 = path + getattr(nft, "BAK_SUFFIX", ".bak_ab1006")
        check(f"G2 이관 전 사본 {nm9}{getattr(nft, 'BAK_SUFFIX', '')} = 원본 그대로 · 0600", os.path.exists(b9) and open(b9, "rb").read() == orig[nm9]
              and (os.stat(b9).st_mode & 0o777) == 0o600, b9)
    i1, i2 = pair_items(Tg, f"eth:{W1}"), pair_items(Tg, f"eth:{W2}")
    check("G3 W1 = 전체 목록으로 시리즈(p12 = 대표 ids 밖 토큰도 셈)", {k: a["n"] for k, a in i1.items()} == {K(V1, 7): 3, K(V1, 9): 3, K(V1, 12): 1, f"eth:{OTHER}": 2},
          {k: a.get("n") for k, a in i1.items()})
    pw2 = Tg.hold["pairs"].get(f"eth:{W2}") or {}
    check("G4 W2 읽기 실패 = 옛 항목 유지 + 다시 읽기 표식(rs) + 오류", f"eth:{V1}" in (pw2.get("items") or {}) and pw2.get("rs") and pw2.get("err"), pw2)
    v = guard("G view mid", lambda: Tg.view(CFG)) or {}
    sP, rP = row_of(v, f"eth:{V1}")
    check("G5 중간 상태 화면: W2 몫 계약 단위 V1 2개 = 나누는 중(평가 없음) · 시리즈 p7 = W1 3개", (rP or {}).get("count") == 2 and (rP or {}).get("value") is None
          and (row_of(v, K(V1, 7))[1] or {}).get("count") == 3 and (v.get("totals") or {}).get("pending") == 0, (rP, v.get("totals")))
    fpg = Tg.fp.get("fp") or {}
    check("G6 계약 단위 값(5.0)·경위를 자식에 복사 안 함(시리즈 값 = 오픈시 시리즈 조회)", all((fpg.get(k) or {}).get("native") != 5.0 for k in i1 if nft.ser_parse(k))
          and (fpg.get(K(V1, 7)) or {}).get("native") == 1.5, {k: (fpg.get(k) or {}).get("native") for k in i1})
    acg = Tg.hold.get("acq") or {}
    check("G7 시리즈 경위 = 그 토큰의 실제 수령 거래(p7 = 내 다른 지갑 · p9 = 30곳 대량) · 계약 전송 목록 0콜",
          (acg.get(K(V1, 7)) or {}).get("kind") == "internal" and (acg.get(K(V1, 9)) or {}).get("kind") == "airdrop_mass"
          and rg.n("/token-transfers?type=ERC-721%2CERC-1155&token=" + V1) == 0, ({k: v9.get("kind") for k, v9 in acg.items()}, [u for u in rg.calls if "token-transfers?" in u]))
    p1 = json.load(open(Tg.prefs_path))
    check("G8 설정 잇기(W1 시리즈): V1 추적 → p7·p9·p12 추적 · 계약 키도 남김 · 관심 V3 그대로 · 총자산 켜짐 그대로",
          {K(V1, 7), K(V1, 9), K(V1, 12), f"eth:{V1}"} <= set(p1["promoted"]) and any(w.get("key") == f"eth:{V3}" for w in p1["watch"])
          and p1["include_in_total"] is True, p1)
    CLOCK[0] = NOW + 3601
    rg.on(f"{BS}/api/v2/addresses/{W2}/nft", bs_nft(W2))
    Tg2 = mk(rg, "g")
    out = guard("G run2", lambda: Tg2.run_once()) or {}
    i2 = pair_items(Tg2, f"eth:{W2}")
    check("G9 재시작 뒤 W2 = 시리즈(p7·p9·V0 p0·FLEX p600) · 표식 풀림 · 이관 완료", set(i2) == {K(V1, 7), K(V1, 9), K(V0, 0), K(FLEX, 600)}
          and not (Tg2.hold["pairs"][f"eth:{W2}"]).get("rs") and (Tg2.hold.get("abmig") or {}).get("pending") == 0 and (Tg2.hold.get("abmig") or {}).get("done"),
          (sorted(i2), Tg2.hold.get("abmig")))
    p2 = json.load(open(Tg2.prefs_path))
    check("G10 설정 잇기: V0 숨김 → p0 숨김 · FLEX 정상으로 → p600 · V1 추적 → p7·p9", K(V0, 0) in p2["hidden"] and K(FLEX, 600) in p2["notspam"]
          and {K(V1, 7), K(V1, 9)} <= set(p2["promoted"]) and f"eth:{V0}" in p2["hidden"], p2)
    v = guard("G view after", lambda: Tg2.view(CFG)) or {}
    check("G11 V0 p0 = 숨김 칸 · FLEX p600 = 추적(시세 4.2 · 대량 수령이어도) · 관심 V3 = 남음(시리즈 미확정 · 0콜)",
          row_of(v, K(V0, 0))[0] == "hidden" and row_of(v, K(FLEX, 600))[0] == "tracked" and row_of(v, f"eth:{V3}")[0] == "watch"
          and rg.n(V3) == 0, (row_of(v, K(V0, 0))[0], row_of(v, K(FLEX, 600))[0], row_of(v, f"eth:{V3}")))
    check("G12 V0 부정 캐시(cg) = 시리즈 무관 · 숨김이라 0콜", rg.n("/nfts/1234") == 0, [u for u in rg.calls if "1234" in u])
    b_before = {p9: open(p9 + nft.BAK_SUFFIX, "rb").read() for p9 in (Tg2.hold_path, Tg2.fp_path, Tg2.prefs_path)} if hasattr(nft, "BAK_SUFFIX") else {}
    pr_before = open(Tg2.prefs_path, "rb").read()
    CLOCK[0] += 3700
    guard("G run3", lambda: Tg2.run_once())
    check("G13 반복 기동 = 설정 그대로(바이트) · 사본 덮지 않음 · 다시 읽기 없음", open(Tg2.prefs_path, "rb").read() == pr_before
          and all(open(p9 + nft.BAK_SUFFIX, "rb").read() == b for p9, b in b_before.items()) and not any(p.get("rs") for p in Tg2.hold["pairs"].values()))
    _v, err = guard("G unhide", lambda: Tg2.apply_prefs({"op": "unhide", "key": K(V0, 0)})) or (None, "x")
    CLOCK[0] += 3700
    guard("G run4", lambda: Tg2.run_once())
    check("G14 사용자가 시리즈 하나 숨김 해제 = 다시 숨기지 않음(장부)", err is None and K(V0, 0) not in json.load(open(Tg2.prefs_path))["hidden"], json.load(open(Tg2.prefs_path)))

    print("[G''] 사본 실패 = 이관 안 함 · 토큰 ID 못 읽은 공유 계약 = 표식 반복 없음 · 계약 단위 키 추적 = 30초 바퀴 남지 않음")
    GD2 = os.path.join(H.TMP, "g2")
    os.makedirs(GD2, exist_ok=True)
    for nm9, obj in (("hold", old_hold), ("fp", old_fp), ("prefs", old_prefs)):
        nft.atomic_write(os.path.join(GD2, nm9 + ".json"), obj)
    Tb2 = mk(base_router(), "g2")
    Tb2._ab_backup = lambda: False
    CLOCK[0] = NOW + 10 * DAY
    guard("G'' run nobak", lambda: Tb2.run_once())
    ks2 = set(pair_items(Tb2, f"eth:{W1}"))
    check("G''1 사본 실패 = 다시 읽기 표식 없음 · 하루 발견이 와도 시리즈로 안 바꿈(계약 단위 유지 · 시세 없음)", f"eth:{V1}" in ks2 and not any(nft.ser_parse(k) for k in ks2)
          and not any((p9 or {}).get("rs") for p9 in Tb2.hold["pairs"].values()), (sorted(ks2), {k: p9.get("rs") for k, p9 in Tb2.hold["pairs"].items()}))
    ru = base_router()
    ru.on(f"{BS}/api/v2/addresses/{W1}/nft", bs_nft(W1, [(V1, "abc", "Bad Id"), (OTHER, "1", "Other #1")]))
    Tu = mk(ru, "u")
    CLOCK[0] = NOW
    guard("G'' scan unsplit", lambda: Tu.scan())
    n_bs = ru.n(f"/addresses/{W1}/nft")
    CLOCK[0] += 3700
    guard("G'' run unsplit", lambda: Tu.run_once())
    check("G''2 토큰 ID 못 읽은 공유 계약 = 계약 단위(unsplit) · 다시 읽기 표식 안 붙어 매 바퀴 재조회 없음",
          (pair_items(Tu, f"eth:{W1}").get(f"eth:{V1}") or {}).get("unsplit") is True and not (Tu.hold["pairs"][f"eth:{W1}"]).get("rs")
          and ru.n(f"/addresses/{W1}/nft") == n_bs, (pair_items(Tu, f"eth:{W1}"), ru.n(f"/addresses/{W1}/nft"), n_bs))
    _v, e = guard("G'' promote parent", lambda: Tu.apply_prefs({"op": "promote", "key": f"eth:{V1}"})) or (None, "x")
    guard("G'' due parent", lambda: Tu.due_fp())
    check("G''3 계약 단위 키 추적(설정이 깨움) = 부르지 않고 깨움 표식도 버림(30초 바퀴 안 남음)", e is None and f"eth:{V1}" not in Tu.urgent and Tu._loop_wait() == 900.0,
          (e, Tu.urgent))


except Exception as _e:
    import traceback as _tb
    check('절 실행(예외)', False, _tb.format_exc()[-600:])
try:
    print("[I] 시리즈 키 설정 동작 전부 · 관심 추가(오픈시 아이템 링크) · 계약 단위 관심 거부 · '#' 키 400 · 검색 찾아가기")
    CLOCK[0] = NOW
    ri = base_router()
    Ti = mk(ri, "i")
    guard("I scan", lambda: Ti.scan())
    ops = []
    for op in ("promote", "unpromote", "hide", "unhide", "notspam", "spam"):
        _v, e = guard("I " + op, lambda op=op: Ti.apply_prefs({"op": op, "key": K(V1, 9)})) or (None, "x")
        ops.append((op, e))
    check("I1 promote·unpromote·hide·unhide·notspam·spam 모두 200", all(e is None for _o, e in ops), ops)
    _v, e = Ti.apply_prefs({"op": "promote", "key": f"eth:{V1}#9"})
    check("I2 '#' 키 = 400", e and e[0] == 400, e)
    _v, e = guard("I watch link", lambda: Ti.apply_prefs({"op": "watch_add", "link": f"https://opensea.io/item/ethereum/{V3}/400000123"})) or (None, "x")
    w = [x for x in json.load(open(Ti.prefs_path))["watch"] if x.get("key") == K(V3, 400)]
    check("I3 오픈시 아이템 링크(아트블럭) = 시리즈 관심 eth:V3/p400 · 조회 토큰 400000123", e is None and w and w[0].get("sample") == "400000123", (e, w))
    _v, e = Ti.apply_prefs({"op": "watch_add", "chain": "eth", "address": V3})
    check("I4 계약 주소만(아트블럭) = 400 · 아이템 링크 안내", e and e[0] == 400 and "아이템 링크" in e[1], e)
    _v, e = guard("I watch es", lambda: Ti.apply_prefs({"op": "watch_add", "link": f"https://etherscan.io/token/{V1}?a=55000001"})) or (None, "x")
    check("I5 이더스캔 토큰 링크 ?a= = 시리즈 관심 p55", e is None and any(x.get("key") == K(V1, 55) for x in json.load(open(Ti.prefs_path))["watch"]), e)
    ri.on(f"api.opensea.io/api/v2/chain/ethereum/contract/{V3}/nfts/400000123", os_nft(V3, "400000123", "four-hundred", "Four #123"))
    ri.on("api.opensea.io/api/v2/collections/four-hundred/stats", os_stats(0.9, d1=1.0, s1=1))
    guard("I refresh", lambda: Ti.refresh_fp())
    v = guard("I view", lambda: Ti.view(CFG)) or {}
    sW, rW = row_of(v, K(V3, 400))
    check("I6 시리즈 관심(보유 없음) = 시세 0.9 · 관심 칸", sW == "watch" and ((rW or {}).get("fp") or {}).get("native") == 0.9, (sW, rW))
    _v, e = Ti.apply_prefs({"op": "watch_remove", "key": K(V3, 400)})
    check("I7 시리즈 관심 해제 200", e is None, e)
    try:
        import search_index
        docs = search_index.docs_nft(Ti.view(CFG))
        hit = [d for d in docs if d.get("anc") == "nft:" + K(V1, 7)]
        check("I8 검색 색인: 시리즈 이름 'Seven' · 찾아가기 표식 nft:eth:<계약>/p7", hit and hit[0].get("title") == "Seven", hit)
    except Exception as e:
        check("I8 검색 색인", False, repr(e))

except Exception as _e:
    import traceback as _tb
    check('절 실행(예외)', False, _tb.format_exc()[-600:])
try:
    print("[R] 경계 사례 — 표식 없는 체결 캐시 재사용 · 숨긴 시리즈 외부 조회 · 백업 없는 시리즈 전환 · 보유 없는 관심 메타")
    CLOCK[0] = NOW
    rr1 = base_router()
    rr1.on("api.opensea.io/api/v2/collections/seven-by-a/stats", (200, {"total": {"floor_price": None, "floor_price_symbol": "ETH"}, "intervals": []}))
    rr1.on("api.opensea.io/api/v2/events/collection/seven-by-a", os_event(NOW - 10 * DAY, wei="37000000000000000"))
    Tr1 = mk(rr1, "r1")
    guard("R1 scan", lambda: Tr1.scan())
    Tr1.fp["map"][K(V1, 7)] = {"os": "seven-by-a", "ca": V1, "tid": "7000001", "at": NOW}
    Tr1.fp["fp"][K(V1, 7)] = {"src": "os", "native": 9.9, "sym": "ETH", "id": "seven-by-a", "at": NOW - 100,
                              "last": {"at": NOW - 5 * DAY, "px": 7.7, "sym": "ETH", "chk": NOW - 100}}
    o = guard("R1 fetch", lambda: Tr1.fetch_fp(K(V1, 7), Tr1.hold["cols"][K(V1, 7)]))
    f1 = (Tr1.fp.get("fp") or {}).get(K(V1, 7)) or {}
    check("R1 표식 없는 기록의 체결 캐시(7.7) 안 씀 → 이벤트 새로(0.037) · 표식 = 이 시리즈", o == "ok" and f1.get("native") == 0.037 and f1.get("ser") == K(V1, 7)
          and rr1.n("events/collection/seven-by-a") == 1, (o, f1, rr1.calls[-3:]))
    rr2 = base_router()
    Tr2 = mk(rr2, "r2")
    guard("R2 scan", lambda: Tr2.scan())
    for k9 in (K(V1, 7), K(V1, 9)):
        Tr2.fp.setdefault("chk", {})[k9] = NOW
    pf = nft.empty_prefs()
    pf["hidden"] = [K(V1, 7)]
    nft.atomic_write(Tr2.prefs_path, pf)
    n0 = len(rr2.calls)
    guard("R2 acq", lambda: Tr2.acquire_lookups(CFG))
    check("R2 숨긴 시리즈(p7) 경위 조회 0콜 · 안 숨긴 p9 는 조회", rr2.n("/instances/7000001/transfers") == 0 and rr2.n("/instances/9000010/transfers") == 1,
          [u for u in rr2.calls[n0:]])
    pf["watch"] = [{"key": K(V1, 7), "chain": "eth", "ca": f"{V1}/p7", "pca": V1, "proj": 7, "sample": "7000001", "label": "", "added": 1}]
    nft.atomic_write(Tr2.prefs_path, pf)
    Tr2.urgent.add(K(V1, 7))
    due = [k for k, _c in (guard("R3 due", lambda: Tr2.due_fp()) or [])]
    check("R3 숨김 + 관심 = due 에 없음 · urgent 버림", K(V1, 7) not in due and K(V1, 7) not in Tr2.urgent, (due, Tr2.urgent))
    rr4 = base_router()
    Tr4 = mk(rr4, "r4")
    Tr4.hold["pairs"][f"eth:{W2}"] = {"items": {f"eth:{OTHER}": {"n": 1, "ids": ["1"]}}, "at": NOW - 2 * DAY, "err": None, "src": "blockscout"}
    Tr4.save()
    Tr4._ab_backup = lambda: False
    guard("R4 scan nobak", lambda: Tr4.scan())
    ks4 = set(pair_items(Tr4, f"eth:{W1}")) | set(pair_items(Tr4, f"eth:{W2}"))
    check("R4a 사본 실패 = 새 쌍도 시리즈로 안 바꿈(계약 단위)", not any(nft.ser_parse(k) for k in ks4) and f"eth:{V1}" in ks4, sorted(ks4))
    rr4b = base_router()
    Tr4b = mk(rr4b, "r4b")
    Tr4b.hold["pairs"][f"eth:{W2}"] = {"items": {f"eth:{OTHER}": {"n": 1, "ids": ["1"]}}, "at": NOW - 2 * DAY, "err": None, "src": "blockscout"}
    Tr4b.save()
    orig4 = open(Tr4b.hold_path, "rb").read()
    guard("R4b scan", lambda: Tr4b.scan())
    bak4 = Tr4b.hold_path + nft.BAK_SUFFIX
    check("R4b 사본 성공 = 처음 시리즈 쓰기 전 원본 사본(바이트 같음) · 그 뒤 시리즈", os.path.exists(bak4) and open(bak4, "rb").read() == orig4
          and K(V1, 7) in pair_items(Tr4b, f"eth:{W1}"), (os.path.exists(bak4), sorted(pair_items(Tr4b, f"eth:{W1}"))))
    rr4c = Router()
    rr4c.on(f"{BS}/api/v2/addresses/{W1}/nft", bs_nft(W1, [(OTHER, "1", "Other #1")]))
    rr4c.on(f"{BS}/api/v2/addresses/{W2}/nft", bs_nft(W2, [(OTHER, "2", "Other #2")]))
    rr4c.on(f"{BS}/api/v2/addresses/", (200, []))
    Tr4c = mk(rr4c, "r4c")
    Tr4c.save()
    guard("R4c scan", lambda: Tr4c.scan())
    check("R4c 공유 계약 토큰이 없으면 사본 안 만듦(아트블럭 없는 사용자)", not os.path.exists(Tr4c.hold_path + nft.BAK_SUFFIX))
    rr5 = base_router()
    Tr5 = mk(rr5, "r5")
    _v, e5 = Tr5.apply_prefs({"op": "watch_add", "link": f"https://opensea.io/item/ethereum/{V3}/400000123"})
    _v, e6 = Tr5.apply_prefs({"op": "watch_add", "chain": "eth", "address": "0x" + "d7" * 20, "label": "내 관심 컬렉션"})
    v5 = guard("R5 view", lambda: Tr5.view(CFG)) or {}
    _s, w5 = row_of(v5, K(V3, 400))
    _s, w6 = row_of(v5, "eth:0x" + "d7" * 20)
    check("R5a 보유 없는 시리즈 관심 = 이름 'Art Blocks #400' · 탐색기 링크 ?a=조회 토큰 · series 표시", e5 is None and (w5 or {}).get("name") == "Art Blocks #400"
          and ((w5 or {}).get("links") or {}).get("explorer", "").endswith("?a=400000123") and ((w5 or {}).get("series") or {}).get("proj") == 400, w5)
    check("R5b 보유 없는 일반 관심 = 이름 = 붙인 이름", e6 is None and (w6 or {}).get("name") == "내 관심 컬렉션", (e6, (w6 or {}).get("name")))
except Exception as _e:
    import traceback as _tb
    check('절 실행(예외)', False, _tb.format_exc()[-600:])

try:
    print("[Q] 경계 사례 — 이관 파일의 계약 단위 값 · 체결 조회 실패 = 미확인 · 설정 상속 상한")
    CLOCK[0] = NOW
    GQ = os.path.join(H.TMP, "q1")
    os.makedirs(GQ, exist_ok=True)
    for nm9, obj in (("hold", old_hold), ("fp", old_fp), ("prefs", old_prefs)):
        nft.atomic_write(os.path.join(GQ, nm9 + ".json"), obj)
    rq = base_router()
    rq.on(f"{BS}/api/v2/addresses/{W2}/nft", (500, None))
    Tq = mk(rq, "q1")
    guard("Q1 run", lambda: Tq.run_once())
    fq = json.load(open(Tq.fp_path))
    blocked = {k: (fq.get("neg") or {}).get(f"eth:{k}") for k in (V0, V1, FLEX)}
    check("Q1a 이관 뒤 파일: 계약 단위 fp·hist 없음 · 계약 단위 키 부정 캐시 = 사실상 영구(구버전 재조회 방지) · 사본엔 원본 값",
          f"eth:{V1}" not in (fq.get("fp") or {}) and f"eth:{V1}" not in (fq.get("hist") or {})
          and all(float((b or {}).get("until") or 0) > NOW + 50 * 365 * DAY for b in blocked.values())
          and json.load(open(Tq.fp_path + nft.BAK_SUFFIX))["fp"].get(f"eth:{V1}", {}).get("native") == 5.0, (blocked, sorted(fq.get("fp") or {})))
    for nm9, resp in (("429", (429, None)), ("503", (503, None))):
        rq2 = base_router()
        rq2.on("api.opensea.io/api/v2/collections/seven-by-a/stats", (200, {"total": {"floor_price": None}, "intervals": []}))
        rq2.on("api.opensea.io/api/v2/events/collection/seven-by-a", resp)
        Tq2 = mk(rq2, "q2" + nm9)
        guard("Q2 scan", lambda: Tq2.scan())
        Tq2.fp["map"][K(V1, 7)] = {"os": "seven-by-a", "ca": V1, "tid": "7000001", "at": NOW}
        Tq2.fp["fp"][K(V1, 7)] = {"src": "os", "native": 1.4, "sym": "ETH", "id": "seven-by-a", "at": NOW - 5000, "ser": K(V1, 7)}
        o = guard("Q2 fetch", lambda: Tq2.fetch_fp(K(V1, 7), Tq2.hold["cols"][K(V1, 7)]))
        f2 = (Tq2.fp.get("fp") or {}).get(K(V1, 7)) or {}
        check(f"Q2 체결 조회 {nm9} = 미확인({ {'429': 'budget', '503': 'err'}[nm9]}) · 직전 값 1.4 유지 · 부정 캐시 없음",
              o == {"429": "budget", "503": "err"}[nm9] and f2.get("native") == 1.4 and K(V1, 7) not in (Tq2.fp.get("neg") or {}), (o, f2, (Tq2.fp.get("neg") or {}).get(K(V1, 7))))
    cap0 = nft.MAX_PREF_KEYS
    try:
        nft.MAX_PREF_KEYS = 3
        rq3 = base_router()
        Tq3 = mk(rq3, "q3")
        pf3 = nft.empty_prefs()
        pf3["hidden"] = [f"eth:{V1}", "eth:0x" + "f1" * 20, "eth:0x" + "f2" * 20]
        nft.atomic_write(Tq3.prefs_path, pf3)
        guard("Q3 scan", lambda: Tq3.scan())
        guard("Q3 sync", lambda: Tq3._ab_prefs_sync())
        p3 = json.load(open(Tq3.prefs_path))
        led = (((p3.get("abinh") or {}).get("hidden") or {}).get(f"eth:{V1}") or [])
        check("Q3a 상한이라 못 넣은 시리즈 = 장부에 '완료'로 안 적음", K(V1, 7) not in p3["hidden"] and K(V1, 7) not in led, (p3["hidden"], led))
        for k9 in (K(V1, 7), K(V1, 9), K(V1, 12)):
            Tq3.fp.setdefault("chk", {})[k9] = NOW
        due3 = [k for k, _c in (guard("Q3 due", lambda: Tq3.due_fp()) or [])]
        n3 = len(rq3.calls)
        guard("Q3 acq", lambda: Tq3.acquire_lookups(CFG))
        v3 = guard("Q3 view", lambda: Tq3.view(CFG)) or {}
        check("Q3b 계약 숨김 = 시리즈도 숨김 효력(시세 due 없음 · 경위 0콜 · 화면 숨김 칸)",
              not any(k.startswith(f"eth:{V1}/") for k in due3) and not any("/instances/" in u and V1 in u for u in rq3.calls[n3:])
              and row_of(v3, K(V1, 7))[0] == "hidden", (due3, rq3.calls[n3:], row_of(v3, K(V1, 7))[0]))
        nft.MAX_PREF_KEYS = cap0
        guard("Q3 sync2", lambda: Tq3._ab_prefs_sync())
        p3b = json.load(open(Tq3.prefs_path))
        check("Q3c 자리가 나면 다음 잇기에 숨김 목록·장부에 들어감", {K(V1, 7), K(V1, 9), K(V1, 12)} <= set(p3b["hidden"]), p3b["hidden"])
        _v, e3 = Tq3.apply_prefs({"op": "unhide", "key": K(V1, 9)})
        v3b = Tq3.view(CFG)
        check("Q3d 사용자가 시리즈 하나 숨김 해제 = 계약 숨김이 있어도 그 시리즈는 보임(장부 존중)", e3 is None and row_of(v3b, K(V1, 9))[0] != "hidden", row_of(v3b, K(V1, 9))[0])
        nft.MAX_PREF_KEYS = 3
        Tq4 = mk(base_router(), "q4")
        pf4 = nft.empty_prefs()
        pf4["hidden"] = [f"eth:{V1}", "eth:0x" + "f1" * 20, "eth:0x" + "f2" * 20]
        nft.atomic_write(Tq4.prefs_path, pf4)
        guard("Q3e scan", lambda: Tq4.scan())
        v4 = Tq4.view(CFG)
        _v, e4 = Tq4.apply_prefs({"op": "unhide", "key": K(V1, 12)})
        v4b = Tq4.view(CFG)
        check("Q3e 장부 전 시리즈 '다시 보기' = 보임(장부에 기록) · 다른 시리즈는 계속 숨김", row_of(v4, K(V1, 12))[0] == "hidden" and e4 is None
              and row_of(v4b, K(V1, 12))[0] != "hidden" and row_of(v4b, K(V1, 7))[0] == "hidden", (row_of(v4b, K(V1, 12))[0], row_of(v4b, K(V1, 7))[0]))
    finally:
        nft.MAX_PREF_KEYS = cap0
except Exception as _e:
    import traceback as _tb
    check('절 실행(예외)', False, _tb.format_exc()[-600:])

try:
    print("[P] 경계 사례 — 응답 검증(계약·토큰 ID 필수) · 실패·형식 오류 = 미확인(시세 없음 확정 금지) — 같은 종류 경로 전체")
    CLOCK[0] = NOW

    def p_case(name, routes, prev=None, mp=None):
        rp = base_router()
        for frag, resp in routes:
            rp.on(frag, resp)
        Tp = mk(rp, "p_" + name)
        Tp.scan()
        if mp is not None:
            Tp.fp["map"][K(V1, 7)] = mp
        if prev is not None:
            Tp.fp["fp"][K(V1, 7)] = dict(prev)
        o = Tp.fetch_fp(K(V1, 7), Tp.hold["cols"][K(V1, 7)])
        return Tp, rp, o
    PREV = {"src": "os", "native": 1.4, "sym": "ETH", "id": "seven-by-a", "at": NOW - 5000, "ser": K(V1, 7)}
    NFT_URL = f"api.opensea.io/api/v2/chain/ethereum/contract/{V1}/nfts/7000001"
    for nm9, body in (("noid", {"nft": {"collection": "other-series"}}), ("otherca", {"nft": {"collection": "other-series", "contract": V0, "identifier": "7000001"}}),
                      ("otherid", {"nft": {"collection": "other-series", "contract": V1, "identifier": "7000002"}}), ("malformed", {"x": 1})):
        Tp, rp, o = p_case(nm9, [(NFT_URL, (200, body)), ("api.opensea.io/api/v2/collections/other-series/stats", os_stats(9.9, d1=5.0, s1=3))], prev=PREV)
        fpp = (Tp.fp.get("fp") or {}).get(K(V1, 7)) or {}
        check(f"P1 nfts 응답 {nm9} = err · 매핑 없음 · 통계 0콜 · 직전 1.4 유지 · 부정 캐시 없음", o == "err" and K(V1, 7) not in (Tp.fp.get("map") or {})
              and rp.n("other-series/stats") == 0 and fpp.get("native") == 1.4 and K(V1, 7) not in (Tp.fp.get("neg") or {}), (o, (Tp.fp.get("map") or {}).get(K(V1, 7)), fpp))
    STATS_NOFLOOR = ("api.opensea.io/api/v2/collections/seven-by-a/stats", (200, {"total": {"floor_price": None}, "intervals": []}))
    MAPOK = {"os": "seven-by-a", "ca": V1, "tid": "7000001", "at": NOW}
    for nm9, last, resp, want in (("nosale503", {"at": None, "px": None, "sym": None, "chk": NOW - DAY - 1}, (503, None), "err"),
                                  ("old429", {"at": NOW - 400 * DAY, "px": 0.02, "sym": "ETH", "chk": NOW - DAY - 1}, (429, None), "budget")):
        Tp, rp, o = p_case(nm9, [STATS_NOFLOOR, ("api.opensea.io/api/v2/events/collection/seven-by-a", resp)], prev=dict(PREV, last=last), mp=MAPOK)
        fpp = (Tp.fp.get("fp") or {}).get(K(V1, 7)) or {}
        check(f"P2 체결 캐시({nm9}) + 조회 실패 = {want} · 직전 1.4 유지 · 부정 캐시 없음", o == want and fpp.get("native") == 1.4
              and K(V1, 7) not in (Tp.fp.get("neg") or {}), (o, fpp, (Tp.fp.get("neg") or {}).get(K(V1, 7))))
    Tp, rp, o = p_case("statsbad", [("api.opensea.io/api/v2/collections/seven-by-a/stats", (200, {"oops": 1}))], prev=PREV, mp=MAPOK)
    fpp = (Tp.fp.get("fp") or {}).get(K(V1, 7)) or {}
    check("P3 통계 형식 오류 = err · 직전 1.4 유지 · 부정 캐시 없음", o == "err" and fpp.get("native") == 1.4 and K(V1, 7) not in (Tp.fp.get("neg") or {}), (o, fpp))
    la = nft.parse_os_last_sale({"asset_events": [{"event_type": "sale", "event_timestamp": NOW - DAY, "nft": {"collection": "other-series"},
                                                   "payment": {"quantity": "5000000000000000000", "decimals": 18, "symbol": "ETH"}}]}, "seven-by-a")
    check("P4 다른 컬렉션 체결 이벤트 = 응답 전체 미확인(None — '체결 없음'으로 보지 않음)", la is None, la)
    r5 = Router()
    r5.on("api.opensea.io/api/v2/chain/ethereum/contract/0x" + "b5" * 20, (200, ["not", "a", "dict"]))
    r5.on("api.coingecko.com", (404, None))
    r5.on("api-mainnet.magiceden.dev/v2/tokens/", (200, "garbage"))
    T5 = mk(r5, "p5")
    k5 = "eth:0x" + "b5" * 20
    o5 = T5.fetch_fp(k5, {"chain": "eth", "ca": "0x" + "b5" * 20, "name": "P5"})
    check("P5a 오픈시 계약 조회 형식 오류 = 실패 매핑 안 남김 · 시세 없음 확정 안 함", "os" not in ((T5.fp.get("map") or {}).get(k5) or {}) and o5 != "none" and k5 not in (T5.fp.get("neg") or {}),
          (o5, (T5.fp.get("map") or {}).get(k5), (T5.fp.get("neg") or {}).get(k5)))
    mint = "So11111111111111111111111111111111111111112"
    o6 = T5.fetch_fp("sol:" + mint, {"chain": "sol", "ca": mint, "sample": mint, "name": "P6"})
    check("P5b 매직에덴 토큰 형식 오류 = 빈 심볼 영구 캐시 안 함", "me" not in ((T5.fp.get("map") or {}).get("sol:" + mint) or {}) and o6 != "none", (o6, (T5.fp.get("map") or {}).get("sol:" + mint)))
    r6 = Router()
    r6.on("api.coingecko.com/api/v3/nfts/ethereum/contract/0x" + "b6" * 20, (200, "garbage"))
    T6 = mk(r6, "p6", env={})
    k6 = "eth:0x" + "b6" * 20
    o6c = T6.fetch_fp(k6, {"chain": "eth", "ca": "0x" + "b6" * 20, "name": "P6"})
    check("P6a 코인게코 200 형식 오류 = err · 부정 캐시 없음", o6c == "err" and k6 not in (T6.fp.get("neg") or {}), (o6c, (T6.fp.get("neg") or {}).get(k6)))
    r6.on("api-mainnet.magiceden.dev/v2/collections/symx/stats", (200, ["bad"]))
    o6m = T6.fetch_fp("sol:me/symx", {"chain": "sol", "me": "symx", "name": "P6m"})
    check("P6b 매직에덴 통계 200 형식 오류 = err · 부정 캐시 없음", o6m == "err" and "sol:me/symx" not in (T6.fp.get("neg") or {}), o6m)
    r7 = base_router()
    r7.on(f"{BS}/api/v2/tokens/{V1}/instances/7000001/transfers", (200, {"items": [{"to": {"hash": W1}, "from": {"hash": EXT}, "transaction_hash": "0x" + "3" * 64,
                                                                                    "total": {"token_id": "7000002"}}, {"to": {"hash": W1}, "from": {"hash": EXT}, "transaction_hash": "0x" + "4" * 64}]}))
    T7 = mk(r7, "p7")
    T7.scan()
    r9 = T7._acq_ser(BS, W1, V1, "7000001", {W1, W2}, "ETH")
    check("P7 다른 토큰·token_id 없는 전송 = 안 씀 → 경위 unknown · 거래 조회 0콜", r9 == {"kind": "unknown"} and r7.n("/transactions/0x") == 0, (r9, r7.calls[-3:]))
except Exception as _e:
    import traceback as _tb
    check('절 실행(예외)', False, _tb.format_exc()[-600:])

try:
    print("[O] 경계 사례 — 확인된 응답만 '없음' · 그 밖 미확인(직전 값·재시도) — 오픈시(시리즈·계약·통계·체결)·코인게코·매직에덴(통계·토큰)·키 없음·재시도·평가")
    CLOCK[0] = NOW
    MAPOK = {"os": "seven-by-a", "ca": V1, "tid": "7000001", "at": NOW}
    PREV = {"src": "os", "native": 1.4, "sym": "ETH", "id": "seven-by-a", "at": NOW - 5000, "ser": K(V1, 7)}
    STATS_NULL = ("api.opensea.io/api/v2/collections/seven-by-a/stats", (200, {"total": {"floor_price": None}, "intervals": []}))
    EV_URL = "api.opensea.io/api/v2/events/collection/seven-by-a"

    def ser_run(name, routes, prev=PREV, mp=MAPOK):
        rp = base_router()
        for frag, resp in routes:
            rp.on(frag, resp)
        Tp = mk(rp, "o_" + name)
        Tp.scan()
        if mp is not None:
            Tp.fp["map"][K(V1, 7)] = dict(mp)
        if prev is not None:
            Tp.fp["fp"][K(V1, 7)] = dict(prev)
        o = Tp.fetch_fp(K(V1, 7), Tp.hold["cols"][K(V1, 7)])
        f = (Tp.fp.get("fp") or {}).get(K(V1, 7)) or {}
        return Tp, rp, o, f
    ev = lambda **kw: dict({"event_type": "sale", "event_timestamp": NOW - 20 * DAY, "quantity": 1, "nft": {"collection": "seven-by-a"},
                            "payment": {"quantity": "40000000000000000", "decimals": 18, "symbol": "ETH"}}, **kw)
    for nm9, evs in (("othercoll", [ev(nft={"collection": "other"})]), ("nocoll", [ev(nft={})]), ("badts", [ev(event_timestamp="x", closing_date=None)]),
                     ("badqty", [ev(payment={"quantity": "-1", "decimals": 18, "symbol": "ETH"})]), ("nosym", [ev(payment={"quantity": "1", "decimals": 18})]),
                     ("notsale", [ev(event_type="transfer")])):
        Tp, rp, o, f = ser_run("ev_" + nm9, [STATS_NULL, (EV_URL, (200, {"asset_events": evs}))])
        check(f"O1 체결 이벤트 {nm9} = err · 직전 1.4 유지 · 부정 캐시 없음", o == "err" and f.get("native") == 1.4 and K(V1, 7) not in (Tp.fp.get("neg") or {}), (o, f))
    Tp, rp, o, f = ser_run("ev_empty", [STATS_NULL, (EV_URL, (200, {"asset_events": []}))])
    check("O1 체결 목록 비어 있음(확인된 없음) + 바닥가 null = none(부정 캐시 os)", o == "none" and (Tp.fp.get("neg") or {}).get(K(V1, 7), {}).get("src") == "os", o)
    Tp, rp, o, f = ser_run("ev_ok", [STATS_NULL, (EV_URL, (200, {"asset_events": [ev()]}))])
    check("O1 정상 체결(20일 전 0.04) = basis last 기록", o == "ok" and f.get("basis") == "last" and f.get("native") == 0.04, (o, f))
    for nm9, body in (("totalempty", {"total": {}, "intervals": []}), ("floorstr", {"total": {"floor_price": "abc"}, "intervals": []})):
        Tp, rp, o, f = ser_run("st_" + nm9, [("api.opensea.io/api/v2/collections/seven-by-a/stats", (200, body)), (EV_URL, (200, {"asset_events": []}))])
        check(f"O2 오픈시 통계 {nm9} = err · 직전 유지", o == "err" and f.get("native") == 1.4 and K(V1, 7) not in (Tp.fp.get("neg") or {}), (o, f))
    NFTU = f"api.opensea.io/api/v2/chain/ethereum/contract/{V1}/nfts/7000001"
    for nm9, nb, want in (("collbad", {"contract": V1, "identifier": "7000001", "collection": 123}, "err"),
                          ("collmissing", {"contract": V1, "identifier": "7000001"}, "err"),
                          ("collnull", {"contract": V1, "identifier": "7000001", "collection": None}, "none")):
        Tp, rp, o, f = ser_run("nf_" + nm9, [(NFTU, (200, {"nft": nb}))], mp=None)
        mp9 = (Tp.fp.get("map") or {}).get(K(V1, 7))
        check(f"O2 시리즈 토큰 {nm9} = {want}" + (" · 매핑·부정 캐시 없음 · 직전 유지" if want == "err" else " · 실패 매핑(키 지문)"),
              o == want and ((want == "err" and mp9 is None and f.get("native") == 1.4) or (want == "none" and (mp9 or {}).get("os") == "" and (mp9 or {}).get("okf"))), (o, mp9, f))
    rg2 = Router()
    kx = lambda x: "eth:0x" + x * 20
    rg2.on("api.opensea.io/api/v2/chain/ethereum/contract/0x" + "c1" * 20, (200, {}))
    rg2.on("api.opensea.io/api/v2/chain/ethereum/contract/0x" + "c2" * 20, (200, {"address": "0x" + "c2" * 20, "collection": None}))
    rg2.on("api.coingecko.com/api/v3/nfts/ethereum/contract/0x" + "c3" * 20, (200, {}))
    rg2.on("api.coingecko.com/api/v3/nfts/ethereum/contract/0x" + "c4" * 20, (200, {"floor_price": {"native_currency": "abc"}}))
    rg2.on("api.coingecko.com/api/v3/nfts/ethereum/contract/0x" + "c5" * 20, (200, {"contract_address": "0x" + "c5" * 20, "floor_price": {"native_currency": None, "usd": None}}))
    rg2.on("api.coingecko.com/api/v3/nfts/ethereum/contract/0x" + "c1" * 20, (404, None))
    rg2.on("api.coingecko.com/api/v3/nfts/ethereum/contract/0x" + "c2" * 20, (404, None))
    To = mk(rg2, "o_gen")
    for x, want, desc in (("c1", "err", "오픈시 계약 200 {} (+코인게코 404)"), ("c2", "none", "오픈시 계약 collection null(+코인게코 404)")):
        To.fp["fp"][kx(x)] = {"src": "os", "native": 0.5, "sym": "ETH", "at": NOW - 100}
        o = To.fetch_fp(kx(x), {"chain": "eth", "ca": "0x" + x * 20, "name": x})
        mpx = (To.fp.get("map") or {}).get(kx(x)) or {}
        check(f"O2 {desc} = {want}", o == want and ((want == "err" and "os" not in mpx and (To.fp["fp"].get(kx(x)) or {}).get("native") == 0.5)
                                                     or (want == "none" and mpx.get("os") == "")), (o, mpx))
    Tc = mk(rg2, "o_cg", env={})
    for x, want, desc in (("c3", "err", "코인게코 200 {}"), ("c4", "err", "코인게코 바닥가 문자열"), ("c5", "none", "코인게코 바닥가 null")):
        Tc.fp["fp"][kx(x)] = {"src": "cg", "native": 0.5, "sym": "ETH", "at": NOW - 100}
        o = Tc.fetch_fp(kx(x), {"chain": "eth", "ca": "0x" + x * 20, "name": x})
        check(f"O2 {desc} = {want}" + (" · 직전 유지" if want == "err" else ""), o == want and (want != "err" or (Tc.fp["fp"].get(kx(x)) or {}).get("native") == 0.5), o)
    rm = Router()
    mint1, mint2, mint3, mint4 = [("So%d" % i) + "1" * 40 for i in range(1, 5)]
    rm.on("api-mainnet.magiceden.dev/v2/tokens/" + mint1, (200, {}))
    rm.on("api-mainnet.magiceden.dev/v2/tokens/" + mint2, (200, {"mintAddress": mint2}))
    rm.on("api-mainnet.magiceden.dev/v2/tokens/" + mint3, (400, None))
    rm.on("api-mainnet.magiceden.dev/v2/tokens/" + mint4, (200, {"mintAddress": mint4, "collection": "symok"}))
    rm.on("api-mainnet.magiceden.dev/v2/collections/symok/stats", (200, {}))
    rm.on("api-mainnet.magiceden.dev/v2/collections/symnull/stats", (200, {"symbol": "symnull", "floorPrice": None}))
    Tm = mk(rm, "o_me", env={})
    for mnt, want, desc in ((mint1, "err", "매직에덴 토큰 200 {}"), (mint2, "none", "매직에덴 토큰 확인됨·컬렉션 칸 없음"), (mint3, "err", "매직에덴 토큰 400")):
        o = Tm.fetch_fp("sol:" + mnt, {"chain": "sol", "ca": mnt, "sample": mnt, "name": "m"})
        mpm = (Tm.fp.get("map") or {}).get("sol:" + mnt) or {}
        check(f"O2 {desc} = {want}" + (" · 빈 심볼 저장 안 함" if want == "err" else " · 빈 심볼 저장"), o == want and (("me" not in mpm) if want == "err" else mpm.get("me") == ""), (o, mpm))
    o = Tm.fetch_fp("sol:" + mint4, {"chain": "sol", "ca": mint4, "sample": mint4, "name": "m4"})
    check("O2 매직에덴 통계 200 {} = err · 부정 캐시 없음", o == "err" and "sol:me/symok" not in (Tm.fp.get("neg") or {}), o)
    o = Tm.fetch_fp("sol:me/symnull", {"chain": "sol", "me": "symnull", "name": "mn"})
    check("O2 매직에덴 통계 바닥가 null = none", o == "none", o)
    rr3 = base_router()
    rr3.on(f"api.opensea.io/api/v2/chain/ethereum/contract/{V1}/nfts/12000005", (503, None))
    T3 = mk(rr3, "o_retry")
    T3.scan()
    T3.fetch_fp(K(V1, 12), T3.hold["cols"][K(V1, 12)])
    CLOCK[0] = NOW + nft.ERR_RETRY + 1
    d3 = {k for k, _c in T3.due_fp()}
    check("O3a 시리즈 503(직전 값 없음) = ERR_RETRY(30분) 뒤 다시 due(종전 6시간)", K(V1, 12) in d3 and (T3.fp.get("retry") or {}).get(K(V1, 12)), sorted(d3))
    kg = "eth:0x" + "c6" * 20
    rr4 = Router()
    rr4.on("api.coingecko.com/api/v3/nfts/ethereum/contract/0x" + "c6" * 20, (503, None))
    T4 = mk(rr4, "o_retry2", env={})
    CLOCK[0] = NOW
    T4.hold["cols"][kg] = {"chain": "eth", "ca": kg.split(":")[1], "name": "Gen", "rep": "ok"}
    T4.hold["pairs"][f"eth:{W1}"] = {"items": {kg: {"n": 1, "ids": ["1"]}}, "at": NOW, "err": None}
    T4.fetch_fp(kg, T4.hold["cols"][kg])
    T4.hold["acq"][kg] = {"kind": "received", "n": 1, "tries": 1}
    CLOCK[0] = NOW + nft.ERR_RETRY + 1
    check("O3b 오류 뒤 경위 '남이 보냄'(스팸)이어도 미확인이면 다시 due", kg in {k for k, _c in T4.due_fp()})
    rr4.on("api.coingecko.com/api/v3/nfts/ethereum/contract/0x" + "c6" * 20, (404, None))
    T4.fetch_fp(kg, T4.hold["cols"][kg])
    CLOCK[0] = NOW + 30 * DAY
    check("O3c 확인된 없음(404) 뒤엔 종전대로 스팸 확정 건너뛰기", kg not in {k for k, _c in T4.due_fp()} and kg not in (T4.fp.get("retry") or {}))
    CLOCK[0] = NOW
    env4 = {"TJ_OPENSEA_KEY": ""}
    T5 = mk(Router(), "o_oswatch", env=env4)
    T5.fp["fp"]["os:watched-coll"] = {"src": "os", "native": 2.2, "sym": "ETH", "id": "watched-coll", "at": NOW - 100}
    o = T5.fetch_fp("os:watched-coll", {"chain": "os", "os": "watched-coll"})
    check("O4a 오픈시 관심 + 키 없음 = err · 직전 2.2 유지 · 부정 캐시 없음", o == "err" and (T5.fp["fp"].get("os:watched-coll") or {}).get("native") == 2.2
          and "os:watched-coll" not in (T5.fp.get("neg") or {}), o)
    T5.fp["neg"]["os:watched-coll"] = {"until": NOW + 5 * DAY, "src": "os"}
    T5._os_sync_key()
    env4["TJ_OPENSEA_KEY"] = "OSKEY-N"
    T5._os_sync_key()
    check("O4b 키가 생기면 os:<슬러그> 부정 캐시도 한 번 풀림", "os:watched-coll" not in (T5.fp.get("neg") or {}))
    r6 = base_router()
    T6 = mk(r6, "o_val")
    ku, kt = "eth:0x" + "c7" * 20, "eth:0x" + "c8" * 20
    for k9 in (ku, kt):
        T6.hold["cols"][k9] = {"chain": "eth", "ca": k9.split(":")[1], "name": "L" + k9[-2:], "rep": "ok"}
        T6.hold["pairs"].setdefault(f"eth:{W1}", {"items": {}, "at": NOW, "err": None})["items"][k9] = {"n": 1, "ids": ["1"]}
        T6.fp["fp"][k9] = {"src": "os", "basis": "last", "native": 0.04, "sym": "ETH", "at": NOW, "last": {"at": NOW - 20 * DAY, "px": 0.04}}
        T6.fp["hist"][k9] = [[nft.today_iso(NOW), 0.04, 108.0, 0.0]]
    T6.hold["acq"][ku] = {"kind": "unknown", "tries": 1}
    T6.hold["acq"][kt] = {"kind": "bought", "tries": 1}
    pf6 = nft.empty_prefs()
    pf6["promoted"] = [ku, kt]
    pf6["include_in_total"] = True
    nft.atomic_write(T6.prefs_path, pf6)
    v6 = T6.view(CFG)
    _s, ru = row_of(v6, ku)
    _s, rt = row_of(v6, kt)
    check("O5 근거 없는 마지막 체결가(직접 추적) = 평가·추이 없음 · 근거 있는 것만 합계", (ru or {}).get("value") is None and not (ru or {}).get("series7")
          and abs(((v6.get("totals") or {}).get("usd") or 0) - 0.04 * 2700) < 1e-6, ((ru or {}).get("value"), (rt or {}).get("value"), v6.get("totals")))
except Exception as _e:
    import traceback as _tb
    check('절 실행(예외)', False, _tb.format_exc()[-600:])

try:
    print("[N] 경계 사례 — 출처 없음·키 없음(zkSync 등) · 매직에덴 민트 검증 · 비 ETH 최근 체결 · 오픈시 계약·코인게코·매직에덴 통계 응답 검증 · 옛 빈 심볼 재확인")
    CLOCK[0] = NOW
    neg_of = lambda T9, k9: (T9.fp.get("neg") or {}).get(k9)
    for nm9, ch9, ca9, env9 in (("zksync_nokey", "zksync", "0x" + "d1" * 20, {}), ("scroll_nosrc", "scroll", "0x" + "d2" * 20, {"TJ_OPENSEA_KEY": "OSKEY-A"}),
                                ("eth_badca", "eth", "0xzz", {})):
        rn = Router()
        Tn = mk(rn, "n1_" + nm9, env=env9)
        k9 = f"{ch9}:{ca9}"
        Tn.fp["fp"][k9] = {"src": "os", "native": 0.3, "sym": "ETH", "at": NOW - 100}
        o = guard("N1 " + nm9, lambda: Tn.fetch_fp(k9, {"chain": ch9, "ca": ca9, "name": nm9}))
        f9 = Tn.fp["fp"].get(k9) or {}
        check(f"N1 {nm9} = err · 0콜 · 직전 0.3 유지 · 부정 캐시 없음 · 미확인 표식",
              o == "err" and not rn.calls and f9.get("native") == 0.3 and neg_of(Tn, k9) is None and k9 in (Tn.fp.get("retry") or {}), (o, rn.calls, f9, neg_of(Tn, k9)))
    rn = Router()
    rn.on("api.opensea.io/api/v2/chain/zksync/contract/0x" + "d3" * 20, (404, None))
    Tn = mk(rn, "n1_zk_key")
    o = Tn.fetch_fp("zksync:0x" + "d3" * 20, {"chain": "zksync", "ca": "0x" + "d3" * 20, "name": "zk"})
    check("N1 zkSync + 키 + 오픈시 404(확인된 없음) = none(종전 그대로)", o == "none" and neg_of(Tn, "zksync:0x" + "d3" * 20) is not None, o)
    mm = {nm9: ("Sn%d" % i) + "2" * 40 for i, nm9 in enumerate(("nullnomint", "nullother", "symother", "symnomint", "nullok", "symok2"))}
    other = "Sx" + "3" * 40
    rm2 = Router()
    rm2.on("api-mainnet.magiceden.dev/v2/tokens/" + mm["nullnomint"], (200, {"collection": None}))
    rm2.on("api-mainnet.magiceden.dev/v2/tokens/" + mm["nullother"], (200, {"mintAddress": other, "collection": None}))
    rm2.on("api-mainnet.magiceden.dev/v2/tokens/" + mm["symother"], (200, {"mintAddress": other, "collection": "wrongsym"}))
    rm2.on("api-mainnet.magiceden.dev/v2/tokens/" + mm["symnomint"], (200, {"collection": "wrongsym"}))
    rm2.on("api-mainnet.magiceden.dev/v2/tokens/" + mm["nullok"], (200, {"mintAddress": mm["nullok"], "collection": None}))
    rm2.on("api-mainnet.magiceden.dev/v2/tokens/" + mm["symok2"], (200, {"mintAddress": mm["symok2"], "collection": "goodsym"}))
    rm2.on("api-mainnet.magiceden.dev/v2/collections/goodsym/stats", (200, {"symbol": "goodsym", "floorPrice": 2500000000, "volume24hr": 1e9}))
    Tm2 = mk(rm2, "n2", env={})
    for nm9, want in (("nullnomint", "err"), ("nullother", "err"), ("symother", "err"), ("symnomint", "err"), ("nullok", "none"), ("symok2", "ok")):
        k9 = "sol:" + mm[nm9]
        Tm2.fp["fp"][k9] = {"src": "me", "native": 1.1, "sym": "SOL", "at": NOW - 100}
        o = guard("N2 " + nm9, lambda k9=k9, nm9=nm9: Tm2.fetch_fp(k9, {"chain": "sol", "ca": mm[nm9], "sample": mm[nm9], "name": nm9}))
        mp9 = (Tm2.fp.get("map") or {}).get(k9) or {}
        if want == "err":
            ok9 = o == "err" and "me" not in mp9 and neg_of(Tm2, k9) is None and (Tm2.fp["fp"].get(k9) or {}).get("native") == 1.1
        elif want == "none":
            ok9 = o == "none" and mp9.get("me") == "" and float(mp9.get("retry") or 0) > NOW
        else:
            ok9 = o == "ok" and mp9.get("me") == "goodsym" and (Tm2.fp["fp"].get("sol:me/goodsym") or {}).get("native") == 2.5
        check(f"N2 매직에덴 토큰 {nm9} = {want}", ok9, (o, mp9, neg_of(Tm2, k9)))
    rm3 = Router()
    Tm3 = mk(rm3, "n2b", env={})
    o = Tm3.fetch_fp("sol:notamint", {"chain": "sol", "ca": "notamint", "name": "x"})
    check("N2 민트 모름 = err · 0콜 · 부정 캐시·빈 심볼 없음", o == "err" and not rm3.calls and neg_of(Tm3, "sol:notamint") is None
          and "me" not in ((Tm3.fp.get("map") or {}).get("sol:notamint") or {}), (o, rm3.calls))
    rm4 = Router()
    m4 = "Sq" + "4" * 40
    rm4.on("api-mainnet.magiceden.dev/v2/tokens/" + m4, (200, {"mintAddress": m4, "collection": "latesym"}))
    rm4.on("api-mainnet.magiceden.dev/v2/collections/latesym/stats", (200, {"symbol": "latesym", "floorPrice": 1500000000, "volume24hr": 1e9}))
    Tm4 = mk(rm4, "n2c", env={})
    Tm4.fp["map"]["sol:" + m4] = {"me": "", "at": NOW - 9 * DAY}
    o = Tm4.fetch_fp("sol:" + m4, {"chain": "sol", "ca": m4, "sample": m4, "name": "late"})
    check("N2 옛 빈 심볼(표식 없음) = 토큰 다시 확인 → 심볼 찾음", o == "ok" and rm4.n("/v2/tokens/") == 1
          and ((Tm4.fp.get("map") or {}).get("sol:" + m4) or {}).get("me") == "latesym", (o, rm4.calls))
    m5 = "Sr" + "5" * 40
    Tm4.fp["map"]["sol:" + m5] = {"me": "", "at": NOW, "retry": NOW + 3 * DAY}
    n0 = len(rm4.calls)
    o = Tm4.fetch_fp("sol:" + m5, {"chain": "sol", "ca": m5, "sample": m5, "name": "conf"})
    check("N2 확인된 빈 심볼(기한 안) = 0콜 · none", o == "none" and len(rm4.calls) == n0, (o, rm4.calls[n0:]))
    for nm9, ts9, want in (("usdc_recent", NOW - 20 * DAY, "err"), ("usdc_old", NOW - 400 * DAY, "none"), ("future", NOW + 5 * DAY, "err")):
        evx = ev(event_timestamp=ts9, closing_date=ts9, payment={"quantity": "40000000", "decimals": 6, "symbol": "USDC"}) if nm9 != "future" else ev(event_timestamp=ts9, closing_date=ts9)
        Tp, rp, o, f = ser_run("n3_" + nm9, [STATS_NULL, (EV_URL, (200, {"asset_events": [evx]}))])
        if want == "err":
            ok9 = o == "err" and f.get("native") == 1.4 and K(V1, 7) not in (Tp.fp.get("neg") or {})
        else:
            ok9 = o == "none" and (Tp.fp.get("neg") or {}).get(K(V1, 7), {}).get("src") == "os"
        check(f"N3 바닥가 null + 체결 {nm9} = {want}", ok9, (o, f))
    rg4 = Router()
    ca_ = {x: "0x" + x * 20 for x in ("e1", "e2", "e3", "e4", "e5")}
    rg4.on("api.opensea.io/api/v2/chain/ethereum/contract/" + ca_["e1"], (200, {"collection": None}))
    rg4.on("api.opensea.io/api/v2/chain/ethereum/contract/" + ca_["e2"], (200, {"address": OTHER, "collection": None}))
    rg4.on("api.opensea.io/api/v2/chain/ethereum/contract/" + ca_["e3"], (200, {"address": ca_["e3"].upper().replace("0X", "0x"), "collection": None}))
    rg4.on("api.opensea.io/api/v2/chain/ethereum/contract/" + ca_["e4"], (200, {"address": OTHER, "collection": "wrong-coll"}))
    rg4.on("api.opensea.io/api/v2/chain/ethereum/contract/" + ca_["e5"], (200, {"address": ca_["e5"], "collection": "right-coll"}))
    rg4.on("api.opensea.io/api/v2/collections/right-coll/stats", os_stats(0.7, d1=1.0, s1=1))
    for x in ca_:
        rg4.on("api.coingecko.com/api/v3/nfts/ethereum/contract/" + ca_[x], (404, None))
    T4n = mk(rg4, "n4")
    for x, want, desc in (("e1", "err", "address 없음 + collection null"), ("e2", "err", "다른 address + collection null"),
                          ("e3", "none", "같은 address(대문자) + collection null"), ("e4", "err", "다른 address + 슬러그"), ("e5", "ok", "같은 address + 슬러그")):
        k9 = "eth:" + ca_[x]
        T4n.fp["fp"][k9] = {"src": "os", "native": 0.5, "sym": "ETH", "at": NOW - 100}
        o = T4n.fetch_fp(k9, {"chain": "eth", "ca": ca_[x], "name": x})
        mpx = (T4n.fp.get("map") or {}).get(k9) or {}
        if want == "err":
            ok9 = o == "err" and "os" not in mpx and (T4n.fp["fp"].get(k9) or {}).get("native") == 0.5 and neg_of(T4n, k9) is None
        elif want == "none":
            ok9 = o == "none" and mpx.get("os") == ""
        else:
            ok9 = o == "ok" and mpx.get("os") == "right-coll" and (T4n.fp["fp"].get(k9) or {}).get("native") == 0.7
        check(f"N4 오픈시 계약 {desc} = {want}", ok9, (o, mpx))
    check("N4 다른 계약 슬러그 통계 0콜", rg4.n("/collections/wrong-coll/") == 0)
    rg5 = Router()
    cb = {x: "0x" + x * 20 for x in ("f1", "f2", "f3", "f4")}
    rg5.on("api.coingecko.com/api/v3/nfts/ethereum/contract/" + cb["f1"], (200, {"floor_price": {"native_currency": None, "usd": None}}))
    rg5.on("api.coingecko.com/api/v3/nfts/ethereum/contract/" + cb["f2"], (200, {"contract_address": OTHER, "floor_price": {"native_currency": None, "usd": None}}))
    rg5.on("api.coingecko.com/api/v3/nfts/ethereum/contract/" + cb["f3"], (200, {"contract_address": cb["f3"], "floor_price": {"native_currency": None, "usd": None}}))
    rg5.on("api.coingecko.com/api/v3/nfts/ethereum/contract/" + cb["f4"], (200, {"contract_address": OTHER, "floor_price": {"native_currency": 3.3, "usd": 9000},
                                                                                 "native_currency_symbol": "ETH", "volume_24h": {"native_currency": 5.0}}))
    T5n = mk(rg5, "n5", env={})
    for x, want, desc in (("f1", "err", "contract_address 없음 + 바닥가 null"), ("f2", "err", "다른 계약 + 바닥가 null"),
                          ("f3", "none", "같은 계약 + 바닥가 null"), ("f4", "err", "다른 계약 + 바닥가")):
        k9 = "eth:" + cb[x]
        T5n.fp["fp"][k9] = {"src": "cg", "native": 0.5, "sym": "ETH", "at": NOW - 100}
        o = T5n.fetch_fp(k9, {"chain": "eth", "ca": cb[x], "name": x})
        f9 = T5n.fp["fp"].get(k9) or {}
        ok9 = (o == "err" and f9.get("native") == 0.5 and neg_of(T5n, k9) is None) if want == "err" else (o == "none" and neg_of(T5n, k9) is not None)
        check(f"N5 코인게코 {desc} = {want}", ok9, (o, f9))
    rg6 = Router()
    rg6.on("api-mainnet.magiceden.dev/v2/collections/s6a/stats", (200, {"floorPrice": None}))
    rg6.on("api-mainnet.magiceden.dev/v2/collections/s6b/stats", (200, {"symbol": "zzz", "floorPrice": None}))
    rg6.on("api-mainnet.magiceden.dev/v2/collections/s6c/stats", (200, {"symbol": "s6c", "floorPrice": None}))
    rg6.on("api-mainnet.magiceden.dev/v2/collections/s6d/stats", (200, {"symbol": "zzz", "floorPrice": 5e9}))
    T6n = mk(rg6, "n6", env={})
    for s9, want, desc in (("s6a", "err", "symbol 없음 + 바닥가 null"), ("s6b", "err", "다른 심볼 + 바닥가 null"), ("s6c", "none", "같은 심볼 + 바닥가 null"),
                           ("s6d", "err", "다른 심볼 + 바닥가")):
        k9 = "sol:me/" + s9
        T6n.fp["fp"][k9] = {"src": "me", "native": 0.9, "sym": "SOL", "at": NOW - 1000}
        o = T6n.fetch_fp(k9, {"chain": "sol", "me": s9, "name": s9})
        f9 = T6n.fp["fp"].get(k9) or {}
        ok9 = (o == "err" and f9.get("native") == 0.9 and neg_of(T6n, k9) is None) if want == "err" else (o == "none" and neg_of(T6n, k9) is not None)
        check(f"N6 매직에덴 통계 {desc} = {want}", ok9, (o, f9))
except Exception as _e:
    import traceback as _tb
    check('절 실행(예외)', False, _tb.format_exc()[-600:])

H.finish()
