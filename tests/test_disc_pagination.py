#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import urllib.parse  # noqa: E402

import token_discovery as td  # noqa: E402
import bf_engine  # noqa: E402
try:
    import evm_watch  # noqa: E402
    T.patch_moved("es_daily_left", lambda *a, **k: 0, ("evm_",))
except Exception:   # noqa: BLE001
    evm_watch = None

chk = T.chk
W = "0x" + "d1" * 20
ENV = {"TJ_ETHERSCAN_KEY": "k" * 24}
A = "0x" + "a1" * 20
B = "0x" + "b1" * 20
C = "0x" + "c1" * 20
D = "0x" + "e1" * 20
NOOP = lambda *_a, **_k: None   # noqa: E731
ALLOW = {"n": None}


def _take(proc, now=None, kind="head"):
    if ALLOW["n"] is None:
        return True
    if ALLOW["n"] <= 0:
        return False
    ALLOW["n"] -= 1
    return True


bf_engine.es_budget_take = _take


def row(blk, ca, i=0, sym=None):
    return {"blockNumber": str(blk), "contractAddress": ca, "tokenSymbol": sym or ("T" + ca[2:4].upper()), "tokenDecimal": "18",
            "hash": "0x" + format(blk, "x").rjust(40, "0") + format(i, "x").rjust(24, "0")}


class FakeES:

    def __init__(self, rows, cap=1000, window=10000, ignore_page=False):
        self.rows = sorted(rows, key=lambda r: int(r["blockNumber"]))
        self.cap, self.window, self.ignore_page = cap, window, ignore_page
        self.calls = []

    def __call__(self, url, **kw):
        q = dict(urllib.parse.parse_qsl(url.split("?", 1)[1]))
        self.calls.append(q)
        sb = int(q.get("startblock") or 0)
        eb = int(q["endblock"]) if "endblock" in q else 10 ** 12
        page = 1 if self.ignore_page else int(q.get("page") or 1)
        off = int(q.get("offset") or 10000)
        if page * off > self.window:
            return {"status": "0", "message": "NOTOK",
                    "result": "Result window is too large, PageNo x Offset size must be less than or equal to 10000"}
        sel = [r for r in self.rows if sb <= int(r["blockNumber"]) <= eb]
        chunk = sel[(page - 1) * off:(page - 1) * off + min(off, self.cap)]
        if not chunk:
            return {"status": "0", "message": "No transactions found", "result": []}
        return {"status": "1", "message": "OK", "result": [dict(r) for r in chunk]}


def use(fake):
    td._http = fake
    return fake


def disc(sources=("etherscan",), **kw):
    return td.discover("eth", W, env=ENV, sources=list(sources), sleep=NOOP, **kw)


def reset_state():
    td.update_state(lambda cur: {"v": 1, "pairs": {}})


def two_tok(n):
    if n <= 0:
        return []
    return [row(i + 1, A, i) for i in range(n - 1)] + [row(n + 5, B, n)]


reset_state()
f = use(FakeES(two_tok(1001)))
r = disc()
chk(B in r["cas"] and A in r["cas"], "P1 2토큰 1,001행 = 1,001번째 행에 처음 나온 두 번째 토큰 발견(1,000행 상한을 목록 끝으로 오인 안 함)",
    {"cas": sorted(x[:6] for x in r["cas"]), "calls": len(f.calls)})
chk(not r["fail"].get("etherscan"), "P1 완료 = 이더스캔 실패·부분 표시 없음", r["fail"])
chk(all(q.get("offset") == "1000" for q in f.calls), "P1 이더스캔 요청 크기 = 1,000(무료 키 응답 상한)", [q.get("offset") for q in f.calls])

for n in (0, 999, 1000, 1001, 5001, 10001):
    reset_state()
    f = use(FakeES(two_tok(n)))
    r = disc()
    want = set() if n == 0 else ({A, B} if n > 1 else {B})
    chk(set(r["cas"]) == want and not r["fail"], f"P1b {n:,}행(토큰 2개) = 후보 {len(want)}개 전부 · 실패 0",
        {"cas": sorted(x[:6] for x in r["cas"]), "fail": r["fail"], "calls": len(f.calls)})

reset_state()
rows2 = [row(10, A, 0)] + [row(20, A, i) for i in range(1, 1500)] + [row(20, B, 1500)] + [row(30, C, 1501)]
f = use(FakeES(rows2))
r = disc()
chk({A, B, C} <= set(r["cas"]) and not r["fail"], "P2 한 블록 1,500행(그 블록 끝에 B) + 뒤 블록 C = 모두 발견(그 블록만 쪽 넘김) · 실패 0",
    {"cas": sorted(x[:6] for x in r["cas"]), "fail": r["fail"], "q": [(q.get("startblock"), q.get("endblock"), q.get("page")) for q in f.calls]})

reset_state()
rows2b = [row(20, A, i) for i in range(10000)] + [row(20, B, 10000)] + [row(30, C, 10001)]
f = use(FakeES(rows2b))
r = disc()
chk(C in r["cas"] and str(r["fail"].get("etherscan", "")).startswith("partial"),
    "P2b 한 블록 1만+행(결과 창 밖) = 명시적 'partial'(조용한 완료 아님) · 뒤 블록 토큰 C 는 발견", {"fail": r["fail"], "calls": len(f.calls)})

reset_state()
f = use(FakeES([row(20, A, i) for i in range(1200)] + [row(20, B, 1200)], ignore_page=True))
r = disc()
chk(bool(r["fail"].get("etherscan")) and not str(r["fail"].get("etherscan")).startswith("more"),
    "P2c 쪽 번호를 무시하는 제공자 = 완료로 치지 않음(오류 표시)", {"fail": r["fail"], "calls": len(f.calls)})

reset_state()
rows3 = [row(i + 1, A, i) for i in range(1000)] + [row(1500 + i, B, 1000 + i) for i in range(1500)] + [row(5000 + i, C, 2500 + i) for i in range(1000)]
f = use(FakeES(rows3))
ALLOW["n"] = 2
r = disc()
ALLOW["n"] = None
SIG = {"txn": 3, "txts": 1789000000}
chk(str(r["fail"].get("etherscan", "")).startswith("quota") and A in r["cas"] and C not in r["cas"],
    "P3 2쪽 뒤 한도 = quota 실패 · 받은 후보 A 는 씀", {"fail": r["fail"], "cas": sorted(x[:6] for x in r["cas"])})
td.save_result("eth", W, r, SIG, "first")
ent = td.entry("eth", W)
t0 = float(ent.get("at") or 0)
chk(td.need_refresh(ent, SIG, now=t0 + 3600, srcs=["etherscan"])[0] is False and
    td.need_refresh(ent, SIG, now=t0 + 7 * 3600, srcs=["etherscan"])[1] == "retry",
    "P3 한도 실패 = 6시간 뒤 재시도(그 전엔 0콜)", [td.need_refresh(ent, SIG, now=t0 + 3600, srcs=["etherscan"]),
                                       td.need_refresh(ent, SIG, now=t0 + 7 * 3600, srcs=["etherscan"])])
n0 = len(f.calls)
r2 = disc()
first_sb = int(f.calls[n0].get("startblock") or 0) if len(f.calls) > n0 else -1
chk(first_sb > 0, "P3 재시도 첫 요청 = 블록 0 이 아니라 저장된 커서부터(genesis 재조회 없음)", {"startblock": first_sb})
chk({A, B, C} <= set(r2["cas"]) and not r2["fail"], "P3 재시도 = 앞서 찾은 후보(A) 보존 + 나머지(B·C) 발견 · 완료",
    {"cas": sorted(x[:6] for x in r2["cas"]), "fail": r2["fail"]})
td.save_result("eth", W, r2, SIG, "retry")
ent = td.entry("eth", W)
chk(td.need_refresh(ent, SIG, srcs=["etherscan"]) == (False, "cache"), "P3 완료 뒤 = 캐시(키 API 0콜)", td.need_refresh(ent, SIG, srcs=["etherscan"]))

reset_state()
old_pages = td.ES_PAGES
td.ES_PAGES = 1
rows4 = [row(i + 1, A, i) for i in range(12500)] + [row(20000, D, 12500)]
f = use(FakeES(rows4))
r = disc()
chk(str(r["fail"].get("etherscan", "")).startswith("more") and D not in r["cas"], "P4 한 실행 몫(쪽 상한) 소진 = '진행 중'(more) 표시 — 완료로 안 침",
    {"fail": r["fail"], "calls": len(f.calls)})
chk("more" not in td.FINAL_FAIL, "P4 'more' = 종결 실패 아님(다시 함)", td.FINAL_FAIL)
td.save_result("eth", W, r, SIG, "first")
ent = td.entry("eth", W)
nr = td.need_refresh(ent, SIG, now=float(ent.get("at") or 0) + 60, srcs=["etherscan", "blockscout"])
chk(nr[0] is True and str(nr[1]).startswith("resume"), "P4 새 지갑 활동 없이(신호 그대로) 다음 실행에서 이어서(resume)", nr)
rs = getattr(td, "run_sources", None)
chk(callable(rs) and rs(["etherscan", "blockscout", "rabby"], nr[1]) == ["etherscan"], "P4 이어 받기 = 이더스캔만(다른 출처 재호출 없음)",
    rs(["etherscan", "blockscout", "rabby"], nr[1]) if callable(rs) else None)
prep = {"chain": "eth", "cfg": {"chains": {"eth": {}}}, "sigs": {W: SIG}, "ents": {W: ent}, "genuine": set(), "off": False}
os.environ["TJ_ETHERSCAN_KEY"] = ENV["TJ_ETHERSCAN_KEY"]
reset_state()
f = use(FakeES(rows4))


def only_es(chain, wallet, **kw):
    kw["sources"] = [s for s in (kw.get("sources") or []) if s == "etherscan"]
    return td.discover(chain, wallet, **kw)


ex = td.recon_extra(dict(prep, ents={W: {}}), sleep=NOOP, discover_fn=only_es)
chk(ex["status"].get(W) == "pending", "P4 새 지갑 대사 = 발견 진행 중이면 그 지갑 보류(다음 주기 — 받은 만큼으로 기초 잔고를 굳히지 않음)", ex["status"])
ent = td.entry("eth", W)
n0 = len(f.calls)
ex = td.recon_extra(dict(prep, ents={W: ent}), sleep=NOOP, discover_fn=only_es)
chk(D in ex["extra"].get(W, set()) and ex["status"].get(W) == "ok" and int(f.calls[n0].get("startblock") or 0) > 0,
    "P4 다음 주기 = 커서부터 이어 받아 완료 → 대사 진행(D 포함)", {"status": ex["status"], "sb": f.calls[n0].get("startblock") if len(f.calls) > n0 else None})
reset_state()
f = use(FakeES(rows4))
r = disc()
td.save_result("eth", W, r, SIG, "first")
sm = td.summary(None)
chk(int(sm.get("progress") or 0) == 1 and int(sm.get("done") or 0) == 0 and int(sm.get("failPairs") or 0) == 0,
    "P4 상태 요약 = 진행 중 1쌍(찾은 쌍·실패 쌍에 안 셈)", sm)
ent = td.entry("eth", W)
ent.setdefault("es", {}).setdefault("etherscan", {})["n"] = getattr(td, "ES_DEFER_RUNS", 6)
td.update_state(lambda cur: dict(cur, pairs={td.pair_key("eth", W): ent}))
td.ES_PAGES = 0
ex = td.recon_extra(dict(prep, ents={W: td.entry("eth", W)}), sleep=NOOP, discover_fn=only_es)
chk(ex["status"].get(W) == "partial", "P4 미룬 실행 상한 뒤 = 'partial'(대사는 받은 만큼으로 진행 · 영구 보류 없음)", ex["status"])
td.ES_PAGES = old_pages
c9 = dict(((td.entry("eth", W).get("es") or {}).get("etherscan")) or {})
n0 = len(f.calls)
r = disc(deadline=1.0)
chk(str(r["fail"].get("etherscan", "")).startswith("more") and len(f.calls) == n0 and ((r.get("es") or {}).get("etherscan") or {}).get("lo") == c9.get("lo"),
    "P4 시간 상한(deadline) = 호출 없이 '진행 중' · 커서 그대로", {"fail": r["fail"], "calls": len(f.calls) - n0})
td.ES_PAGES = old_pages
os.environ.pop("TJ_ETHERSCAN_KEY", None)

import importlib.util  # noqa: E402
reset_state()
td.ES_PAGES = 1
f = use(FakeES(rows4))
r = disc()
td.save_result("eth", W, r, SIG, "first")
td.ES_PAGES = old_pages
sp = importlib.util.spec_from_file_location("td_restart", os.path.join(T.SRC, "token_discovery.py"))
td2 = importlib.util.module_from_spec(sp)
sp.loader.exec_module(td2)
td2._http = f
ent = td2.entry("eth", W)
nr = td2.need_refresh(ent, SIG, srcs=["etherscan"])
n0 = len(f.calls)
r = td2.discover("eth", W, env=ENV, sources=(td2.run_sources(["etherscan"], nr[1]) if hasattr(td2, "run_sources") else ["etherscan"]), sleep=NOOP)
td2.save_result("eth", W, r, SIG, nr[1])
chk(str(nr[1]).startswith("resume") and int(f.calls[n0].get("startblock") or 0) > 0 and D in r["cas"] and not r["fail"]
    and td2.need_refresh(td2.entry("eth", W), SIG, srcs=["etherscan"]) == (False, "cache"),
    "P12 재시작(새 모듈) = 저장된 커서부터 이어 받아 완료 · 그 뒤 캐시", {"why": nr[1], "fail": r["fail"]})

X = "0x" + "f1" * 20
S = "0x" + "f2" * 20
H = "0x" + "f3" * 20
v1 = {"at": 1780000000, "why": "first", "sig": dict(SIG), "cas": {A: ["ankr", "etherscan"], X: ["alchemy"], S: ["etherscan"], H: ["recon"]},
      "meta": {X: {"sym": "XX", "px": 2.0, "dexAt": 1780000001}, A: {"sym": "TA1", "wl": True}}, "ok": {"etherscan": 2, "alchemy": 1, "ankr": 1}, "fail": {},
      "calls": {"etherscan": 1, "alchemy": 1}, "n": 4, "skip": {S: "유동성 부족 — 스팸 의심", H: "일시 보류 — 판정 출처 장애"}}
td.update_state(lambda cur: {"v": 1, "pairs": {td.pair_key("eth", W): json.loads(json.dumps(v1))}})
ent = td.entry("eth", W)
nr = td.need_refresh(ent, SIG, srcs=["etherscan", "alchemy"])
chk(nr[0] is True and str(nr[1]).startswith("upgrade"), "P5 구 v1 캐시(커서·완료 증거 없음) = 1회 재검색 예약 ★수정 전 FAIL(영구 캐시)★", nr)
f = use(FakeES(two_tok(1001) + [row(3000, S, 9999)]))
srcs5 = rs(["etherscan", "alchemy"], nr[1]) if callable(rs) else ["etherscan", "alchemy"]
chk(srcs5 == ["etherscan"], "P5 이행 재검색 = 이더스캔만(Alchemy 0콜)", srcs5)
r = disc(sources=srcs5)
td.save_result("eth", W, r, SIG, nr[1])
ent = td.entry("eth", W)
cas5 = ent.get("cas") or {}
chk(B in cas5 and A in cas5 and X in cas5 and H in cas5, "P5 이행 뒤 = 새 후보(B) + 다른 출처 후보(X) + 보류 후보(H) 보존", sorted(x[:6] for x in cas5))
chk((ent.get("skip") or {}).get(S) and (ent.get("skip") or {}).get(H), "P5 사용자·판정 skip 보존", ent.get("skip"))
chk(((ent.get("meta") or {}).get(X) or {}).get("px") == 2.0 and (ent.get("ok") or {}).get("alchemy") == 1,
    "P5 재판정 가격·다른 출처 성공 기록 보존", {"meta": (ent.get("meta") or {}).get(X), "ok": ent.get("ok")})
chk(((ent.get("meta") or {}).get(A) or {}).get("wl") is True and "ankr" in ((ent.get("cas") or {}).get(A) or []),
    "P5 안 부른 출처(Ankr)의 표식·출처 유지(정품 판정이 이행 재검색으로 사라지지 않음)", {"meta": (ent.get("meta") or {}).get(A), "src": (ent.get("cas") or {}).get(A)})
chk(td.need_refresh(ent, SIG, srcs=["etherscan", "alchemy"]) == (False, "cache"), "P5 이행 한 번 뒤 = 캐시(반복 재검색 없음)",
    td.need_refresh(ent, SIG, srcs=["etherscan", "alchemy"]))

cas6 = {"0x" + format(i, "x").rjust(40, "0"): ["etherscan"] for i in range(1, 1501)}
LAST = "0x" + "f" * 40
cas6[LAST] = ["etherscan"]
ent6 = {"at": 1780000000, "sig": dict(SIG), "cas": cas6, "meta": {}, "ok": {"etherscan": 1501, "blockscout": 0}, "fail": {},
        "es": {"etherscan": {"v": getattr(td, "ES_V", 2), "g": 1, "lo": 1, "pg": 0, "hi": None, "done": True, "end": 1, "n": 1}}}
CALLED6 = []
ex = td.recon_extra({"chain": "eth", "cfg": {"chains": {"eth": {}}}, "sigs": {W: SIG}, "ents": {W: ent6}, "genuine": set(), "off": False},
                    sleep=NOOP, discover_fn=lambda *a, **k: CALLED6.append(1) or {"cas": dict(cas6), "meta": {}, "ok": {"etherscan": 1501}, "fail": {}, "calls": {}})
chk(not CALLED6 and ex["status"].get(W) == "cache", "P6 캐시 경로(발견 0콜)", ex["status"])
chk(LAST in ex["extra"].get(W, set()) and len(ex["extra"].get(W, set())) == 1501,
    "P6 1,501번째(정렬 맨 뒤) 후보 = 대사 질문 목록 포함(고정 앞 1,500 에 굶지 않음)", len(ex["extra"].get(W, set())))

reset_state()
rows7 = [row(i + 1, "0x" + format(i + 1, "x").rjust(40, "0"), i) for i in range(3001)]
f = use(FakeES(rows7))
r = disc()
chk(str(r["fail"].get("etherscan", "")).startswith("cap"), "P7 3,001번째 후보 = 조용히 버리지 않음('cap' — 후보 상한 미완료 표시)", r["fail"])
td.save_result("eth", W, r, SIG, "first")
sm = td.summary(None)
chk(int(sm.get("failPairs") or 0) >= 1 and "etherscan" in (sm.get("failBy") or {}), "P7 상태 요약(헬스 '토큰 발견') 실패 쌍에 드러남", sm)

reset_state()
f = use(FakeES(two_tok(10)))
ent8 = {"at": 1780000000, "why": "first", "sig": dict(SIG), "cas": {A: ["etherscan"], B: ["etherscan"], X: ["alchemy"]},
        "meta": {X: {"sym": "XX", "alnz": True}}, "ok": {"etherscan": 2, "alchemy": 1}, "fail": {},
        "es": {"etherscan": {"v": getattr(td, "ES_V", 2), "g": 1, "lo": 15, "pg": 0, "hi": None, "done": True, "end": 15, "n": 1}}}
td.update_state(lambda cur: {"v": 1, "pairs": {td.pair_key("eth", W): json.loads(json.dumps(ent8))}})
real_al = td.src_alchemy


def al_quota(*a, **k):
    raise td.SourceFail("quota", "429")


td.src_alchemy = al_quota
r = td.discover("eth", W, env=dict(ENV, TJ_ALCHEMY_KEY="a" * 24), sources=["etherscan", "alchemy"], sleep=NOOP)
td.src_alchemy = real_al
td.save_result("eth", W, r, dict(SIG, txn=4), "changed:txn")
ent = td.entry("eth", W)
chk(X in (ent.get("cas") or {}) and ((ent.get("meta") or {}).get(X) or {}).get("alnz") is True,
    "P8 Alchemy 일시 실패(한도) = Alchemy 가 전에 찾은 후보 X 보존(실패 응답으로 후보 삭제 0)", sorted(x[:6] for x in (ent.get("cas") or {})))

reset_state()
f = use(FakeES(two_tok(1500), cap=10000))
r = td.discover("avalanche", W, env={}, sources=["routescan"], sleep=NOOP)
chk(B in r["cas"] and not r["fail"] and len(f.calls) <= 2 and f.calls[0].get("offset") == "10000",
    "P9 루트스캔 = 요청 1만 그대로(기존 계약) · 1,500행 2토큰 발견 · 2콜 이하", {"calls": len(f.calls), "fail": r["fail"]})
f = use(FakeES(two_tok(1500), cap=1000))
r = td.discover("avalanche", W, env={}, sources=["routescan"], sleep=NOOP)
chk(B in r["cas"] and not r["fail"], "P9 루트스캔이 1,000행에서 잘라도 이어 받음", {"calls": len(f.calls), "fail": r["fail"]})

reset_state()
rows10 = two_tok(1001)
f = use(FakeES(rows10 + [row(5000, D, 99999)]))
r = disc(upto=2000)
chk(D not in r["cas"] and all(q.get("endblock") == "2000" for q in f.calls if q.get("page") == "1"),
    "P10 고정 endblock(수집기 커서) = 그 뒤 새 거래는 이번 세대에 안 섞임", {"cas": sorted(x[:6] for x in r["cas"])})
td.save_result("eth", W, r, SIG, "first")
n0 = len(f.calls)
r = disc(upto=6000)
sb10 = int(f.calls[n0].get("startblock") or 0) if len(f.calls) > n0 else -1
chk(D in r["cas"] and {A, B} <= set(r["cas"]) and sb10 >= 2000, "P10 다음 세대 = 지난 끝 블록부터(블록 0 재조회 없음) · 앞 세대 후보 보존 · 새 토큰 발견",
    {"startblock": sb10, "cas": sorted(x[:6] for x in r["cas"])})

reset_state()
rows13 = [row(i + 1, A, i) for i in range(1500)] + [row(1600, B, 1500)] + [row(5000, D, 1501)]
f = use(FakeES(rows13))
td.ES_PAGES = 0
r = disc(upto=2000)
td.ES_PAGES = old_pages
td.save_result("eth", W, r, SIG, "first")
SIG2 = dict(SIG, txn=SIG["txn"] + 1)
ent = td.entry("eth", W)
nr = td.need_refresh(ent, SIG2, srcs=["etherscan"])
r = disc(upto=6000, sources=(rs(["etherscan"], nr[1]) if callable(rs) else ["etherscan"]))
td.save_result("eth", W, r, SIG2, nr[1])
ent = td.entry("eth", W)
got13 = set(ent.get("cas") or {})
nr2 = td.need_refresh(ent, SIG2, srcs=["etherscan"])
chk(D in got13 or nr2[0] is True, "P13 고정 endblock 재개 중 새 활동 = 옛 끝(2000) 뒤 구간도 이어서(새 토큰 D 를 찾거나 다시 찾기 예약 — 캐시에 묻지 않음)",
    {"why": nr[1], "next": nr2, "cas": sorted(x[:6] for x in got13), "es": (ent.get("es") or {}).get("etherscan")})
chk(D in got13 and B in got13 and not (ent.get("fail") or {}).get("etherscan"), "P13 같은 실행에서 옛 구간 끝낸 뒤 새 구간(2000~6000)까지 완료",
    {"fail": ent.get("fail"), "es": (ent.get("es") or {}).get("etherscan")})
reset_state()
f = use(FakeES(rows13))
td.ES_PAGES = 0
r = disc(upto=2000)
td.ES_PAGES = old_pages
td.save_result("eth", W, r, SIG, "first")
r = disc()
chk(D in r["cas"] and not r["fail"], "P13 열린 구간(upto 없음)으로 이어 받기 = 옛 hi 뒤까지 끝까지", {"fail": r["fail"], "cas": sorted(x[:6] for x in r["cas"])})

reset_state()
cas14 = {"0x" + format(i, "x").rjust(40, "0"): ["etherscan"] for i in range(1, 2001)}
cas14.update({"0x" + format(i, "x").rjust(40, "0"): ["alchemy"] for i in range(5001, 6002)})
ent14 = {"at": 1780000000, "sig": dict(SIG), "cas": cas14, "meta": {}, "ok": {"etherscan": 2000, "alchemy": 1001}, "fail": {},
         "es": {"etherscan": {"v": getattr(td, "ES_V", 2), "g": 1, "lo": 1, "pg": 0, "hi": None, "done": True, "end": 1, "n": 1}}}
td.update_state(lambda cur: {"v": 1, "pairs": {td.pair_key("eth", W): json.loads(json.dumps(ent14))}})
sm = td.summary(None)
chk(int(sm.get("failPairs") or 0) == 1, "P14 출처별 상한 안(2,000 + 1,001)이어도 합이 질문 상한(3,000) 넘음 = 상태 요약 실패 쌍(헬스 주의)", sm)
td.update_state(lambda cur: {"v": 1, "pairs": {td.pair_key("eth", W): dict(json.loads(json.dumps(ent14)),
                                                                            cas={k9: v9 for k9, v9 in list(cas14.items())[:3000]})}})
chk(int(td.summary(None).get("failPairs") or 0) == 0, "P14 상한 안(3,000) = 실패 아님", td.summary(None))

chk("etherscan" not in td.plan("bsc", {}, ENV), "P11 BSC = 이더스캔 유료 — 출처 표에 이더스캔 없음(기존 정책 유지)", td.plan("bsc", {}, ENV))

T.finish()
