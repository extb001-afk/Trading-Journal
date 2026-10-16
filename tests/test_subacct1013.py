#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import time

json.dump({"chains": {}, "wallets": [], "backfill_months": 2}, open(os.path.join(T.TMP, "config.json"), "w"))
import common
import ex_foreign as X

chk = T.chk
S = common.STATE_DIR
NOW = int(time.time())

NB = ("TJ_BYBIT_KEY", "TJ_BYBIT_SECRET")
NO = ("TJ_OKX_KEY", "TJ_OKX_SECRET", "TJ_OKX_PASSPHRASE")
ENV = {"TJ_BYBIT_KEY": "bm", "TJ_BYBIT_SECRET": "bms", "TJ_BYBIT_SUB1_KEY": "bs1", "TJ_BYBIT_SUB1_SECRET": "bs1s",
       "TJ_BYBIT_SUB3_KEY": "half",
       "TJ_OKX_KEY": "om", "TJ_OKX_SECRET": "oms", "TJ_OKX_PASSPHRASE": "omp",
       "TJ_OKX_SUB2_KEY": "os2", "TJ_OKX_SUB2_SECRET": "os2s", "TJ_OKX_SUB2_PASSPHRASE": "os2p",
       "TJ_BITHUMB_KEY": "h", "TJ_BITHUMB_SECRET": "hs", "TJ_BITHUMB_SUB1_KEY": "x", "TJ_BITHUMB_SUB1_SECRET": "y"}
a9 = common.exchange_accounts(ENV, "bybit", NB)
chk([t for t, _e in a9] == ["", "s1"] and a9[1][1]["TJ_BYBIT_KEY"] == "bs1" and a9[1][1]["TJ_BYBIT_SECRET"] == "bs1s" and a9[0][1] is ENV,
    "K1 바이빗 = 메인 + 서브1(서브 env = 메인 이름 자리에 서브 값) · 칸 일부만 넣은 서브3 건너뜀", [(t, e.get("TJ_BYBIT_KEY")) for t, e in a9])
chk([t for t, _e in common.exchange_accounts(ENV, "okx", NO)] == ["", "s2"], "K2 OKX = 메인 + 서브2(번호 건너뛰어도)")
chk([t for t, _e in common.exchange_accounts(ENV, "bithumb", ("TJ_BITHUMB_KEY", "TJ_BITHUMB_SECRET"))] == [""], "K3 빗썸 = 메인만(서브계정 대상 밖)")
chk(common.exchange_accounts({"TJ_BYBIT_SUB1_KEY": "a", "TJ_BYBIT_SUB1_SECRET": "b"}, "bybit", NB) == [], "K4 메인 키 없으면 서브만으로는 안 돎")
chk(common.sub_key_names("okx", 2, NO) == ["TJ_OKX_SUB2_KEY", "TJ_OKX_SUB2_SECRET", "TJ_OKX_SUB2_PASSPHRASE"], "K5 서브 키 이름")
chk(X.sub_tags(ENV, "bybit") == ["s1"], "K6 sub_tags")
chk(bool(common.redact_secret_text("TJ_BYBIT_SUB1_SECRET=abcdefgh1234") != "TJ_BYBIT_SUB1_SECRET=abcdefgh1234"), "K7 서브 키 값도 비밀값 가림 대상(이름 패턴)")

OUT = []


class _MemW:
    def __init__(self, *a, **k):
        pass

    def append(self, rec):
        OUT.append(json.loads(json.dumps(rec)))


sub_st = {"seen": {"bybit:d9": "ACCEPTED" + X.SEEN_NOTIME}}
row = X.norm_row("bybit", "d9", "USDT", 5, 0, "tx9", "ACCEPTED", NOW, NOW)
fill = X.norm_fill("bybit", "e9", NOW * 1000, "BTC", "USDT", "buy", 100, 0.1, 0, "USDT")
aw = X._AcctWriter(_MemW(), "bybit", "s1", sub_st)
aw.append({"v": 1, "kind": "ex_snapshot", "exchange": "bybit", "ts": NOW, "deposits": [row], "withdraws": []})
aw.append({"v": 1, "kind": "exf_fills", "exchange": "bybit", "ts": NOW, "fills": [fill]})
chk(OUT[0]["deposits"][0]["uuid"] == "bybit:s1:d9" and OUT[0]["deposits"][0]["acct"] == "s1" and OUT[1]["fills"][0]["id"] == "bybit:s1:e9"
    and OUT[1]["fills"][0]["acct"] == "s1", "W1 서브 입출금 uuid·체결 id 에 딱지 + acct", OUT)
chk(row["uuid"] == "bybit:d9" and "acct" not in row and fill["id"] == "bybit:e9", "W2 호출측 행은 그대로(seen 은 원래 번호로)")
chk(OUT[0]["deposits"][0].get("late") == 1, "W3 시각 보강 행(그 계정 seen = 상태#notime) = late")
OUT.clear()
aw.append({"v": 1, "kind": "exf_fills", "exchange": "okx", "ts": NOW, "fills": [dict(fill, id="okx:e9")]})
chk(OUT[0]["fills"][0]["id"] == "okx:e9", "W4 다른 거래소 레코드는 손대지 않음")
chk(X._acct_id("bybit", "s1", "bybit:s1:x") == "bybit:s1:x", "W5 이미 딱지 붙은 id 는 그대로")

EXS = list(X.FETCHERS)
CFG = {"fail_sub_wd": False, "env": dict(ENV)}
BAL = {"bm": {"USDT": 100.0, "BTC": 1.0}, "bs1": {"USDT": 50.0}, "om": {"USDT": 10.0}, "os2": {"ETH": 2.0}}
SRC = {"bm": ["earn"], "bs1": ["earn"], "om": [], "os2": ["savings"]}
CALLS = []


class _Stop(Exception):
    pass


def k_of(env, ex):
    return env.get(f"TJ_{ex.upper()}_KEY")


def fake_wd(ex):
    def f(env, t0, t1, dep_t0=None):
        k = k_of(env, ex)
        CALLS.append(("wd", ex, k))
        if CFG["fail_sub_wd"] and k == "bs1":
            raise RuntimeError("합성: 서브 입출금 조회 실패")
        if CFG.get("deny_sub_wd") and k == "bs1":
            raise RuntimeError("HTTPError 403 합성: 서브 키 입출금 권한 없음")
        if ex == "bybit":
            return [], [X.norm_row("bybit", "d1", "USDT", 100 if k == "bm" else 50, 0, "t" + k, "ACCEPTED", NOW - 600, NOW - 600)]
        return [], []
    return f


def fake_fills(ex):
    def f(env, fst, t0, t1):
        k = k_of(env, ex)
        CALLS.append(("fills", ex, k))
        if ex == "bybit":
            return [X.norm_fill("bybit", "e1", (NOW - 500) * 1000, "BTC", "USDT", "buy", 100, 1 if k == "bm" else 0.5, 0, "USDT")]
        return []
    return f


def fake_bal(ex):
    def f(env):
        k = k_of(env, ex)
        CALLS.append(("bal", ex, k))
        b = X._Bal(BAL.get(k) or {})
        b.sources = list(SRC.get(k) or [])
        return b
    return f


SUBP = []


def run_cycles(n, clear=True):
    if clear:
        for p in os.listdir(S):
            if (p.startswith("exf_") or p.startswith("futraw_") or p.startswith("futures_")) and os.path.isfile(os.path.join(S, p)):
                os.remove(os.path.join(S, p))
    X._VIEW_CYC.clear()
    X._quiet_n.clear()
    OUT.clear()
    CALLS.clear()
    cnt = {"n": 0}

    def sleep(_s):
        cnt["n"] += 1
        OUT.append({"kind": "_cycle_end", "n": cnt["n"]})
        if cnt["n"] >= n:
            raise _Stop()
    saved = {}

    def patch(obj, name, val):
        saved[(obj, name)] = getattr(obj, name)
        setattr(obj, name, val)
    patch(X, "SegmentWriter", _MemW)
    patch(X, "FETCHERS", {ex: (fake_wd(ex), need) for ex, (_f, need) in X.FETCHERS.items()})
    patch(X, "BAL_FETCHERS", {ex: fake_bal(ex) for ex in EXS})
    patch(X, "FILL_FETCHERS", {ex: fake_fills(ex) for ex in EXS})
    patch(X, "_env", lambda: dict(CFG["env"]))
    for nm in ("dest_backfill_pass", "krw_backfill_pass", "pending_recheck_pass", "leverage_pass"):
        patch(X, nm, lambda *a, **k: None)
    patch(X, "bybit_internal_pass", lambda env, state, writer, now, window: SUBP.append((env.get("TJ_BYBIT_KEY"), state, writer)))
    patch(X, "_fut_binance", lambda env: None)
    patch(X, "_fut_okx", lambda env: None)

    def fut_bb(env):
        k = env.get("TJ_BYBIT_KEY")
        prev = common.read_json(X._fut_path("bybit"), {}) or {}
        ev = [e for e in prev.get("events") or [] if isinstance(e, dict)]
        u = "bb:1" if k == "bm" else "bb:2"
        if u not in {e.get("uid") for e in ev}:
            ev.append({"t": (NOW - 300) * 1000, "symbol": "BTCUSDT", "kind": "REALIZED", "amount": 3.0 if k == "bm" else -1.0, "uid": u})
        X._fut_write("bybit", {"balance": None, "note": "통합계좌"}, [{"symbol": "BTCUSDT", "side": "long", "qty": 1}], ev, {"c": k})
    patch(X, "_fut_bybit", fut_bb)
    patch(X, "convert_rows", lambda *a, **k: [])
    patch(X, "ext_trigger_target", lambda *a, **k: None)
    patch(X, "_hl_on", lambda cfg: False)
    patch(X.depaddr, "start_background", lambda *a, **k: None)
    patch(X.depaddr, "notify", lambda *a, **k: None)
    patch(X.unit_beat, "start", lambda *a, **k: None)
    patch(X.common, "cpu_reserve_apply", lambda *a, **k: None)
    patch(X.time, "sleep", sleep)
    import perp_dex
    import liq_watch
    patch(perp_dex, "start_background", lambda *a, **k: None)
    patch(liq_watch, "start_background", lambda *a, **k: None)
    try:
        X.main()
    except _Stop:
        pass
    finally:
        for (obj, name), v in saved.items():
            setattr(obj, name, v)
    return list(OUT)


def rd(p):
    try:
        return json.load(open(os.path.join(S, p)))
    except FileNotFoundError:
        return None


def cyc(out, i):
    ends = [k for k, r in enumerate(out) if r.get("kind") == "_cycle_end"]
    lo = ends[i - 2] + 1 if i > 1 else 0
    return out[lo:ends[i - 1]]


SUBP.clear()
out = run_cycles(3)
c1 = cyc(out, 1)
dep = [d for r in c1 if r.get("kind") == "ex_snapshot" and r["exchange"] == "bybit" for d in r.get("deposits") or []]
fl = [f for r in c1 if r.get("kind") == "exf_fills" and r["exchange"] == "bybit" for f in r.get("fills") or []]
chk(sorted(d["uuid"] for d in dep) == ["bybit:d1", "bybit:s1:d1"] and [d.get("acct") for d in dep if d["uuid"] == "bybit:s1:d1"] == ["s1"]
    and not [d for d in dep if d["uuid"] == "bybit:d1" and d.get("acct")], "M1 입금: 같은 원래 번호 d1 → 메인 'bybit:d1' · 서브 'bybit:s1:d1'(acct s1) 둘 다", dep)
chk(sorted(f["id"] for f in fl) == ["bybit:e1", "bybit:s1:e1"], "M1 체결: 같은 원래 번호 e1 → 메인·서브 따로(내 두 계정끼리 체결돼도 안 겹침)", fl)
st = rd("exf_state.json") or {}
sb = ((st.get("bybit") or {}).get("accts") or {}).get("s1") or {}
chk("bybit:d1" in (sb.get("seen") or {}) and "bybit:e1" in ((sb.get("fills") or {}).get("seen") or {}) and sb.get("backfilled_until")
    and (sb.get("fills") or {}).get("backfilled_until"), "M1 서브 상태 = state['bybit']['accts']['s1'](원래 번호 seen · 백필 도장)", sb)
chk("accts" not in (st.get("okx") or {}).get("accts", {}).get("s2", {}) and (st.get("okx") or {}).get("accts", {}).get("s2", {}).get("backfilled_until"),
    "M1 OKX 서브2 상태도")
chk(not [r for r in cyc(out, 2) + cyc(out, 3) if r.get("kind") in ("ex_snapshot", "exf_fills")], "M3 둘째·셋째 주기는 다시 안 보냄(계정별 seen)",
    [r for r in cyc(out, 2) + cyc(out, 3) if r.get("kind") in ("ex_snapshot", "exf_fills")])
bb = rd("exf_balances_bybit.json")
chk(bb and bb["balances"] == {"USDT": 150.0, "BTC": 1.0} and sorted(bb.get("sources") or []) == ["earn", "s1:earn", "s1:spot"],
    "M2 바이빗 정식 잔고 = 메인+서브 합(USDT 150 · BTC 1) · 소스 = 메인 그대로 + 's1:earn' + 's1:spot'", bb)
ok = rd("exf_balances_okx.json")
chk(ok and ok["balances"] == {"USDT": 10.0, "ETH": 2.0} and "s2:spot" in (ok.get("sources") or []), "M2 OKX 정식 = 메인+서브2 합", ok)
vw = rd("exf_balances_bybit.json.view")
chk(vw and vw["balances"] == {"USDT": 150.0, "BTC": 1.0}, "M2 표시용(.view)도 합", vw)
sb2 = (((rd("exf_state.json") or {}).get("bybit") or {}).get("accts") or {}).get("s1") or {}
chk((sb2.get("last_bal") or {}).get("b") == {"USDT": 50.0} and "s1:spot" in ((sb2.get("last_bal") or {}).get("src") or []),
    "M2 서브 마지막 잔고(last_bal) 기록", sb2.get("last_bal"))
chk(SUBP and all(k == "bs1" and isinstance(st9, X._AcctState) and list(st9) == ["bybit"] and st9.root is not None and isinstance(w9, X._AcctWriter)
                 for k, st9, w9 in SUBP if k != "bm") and any(k == "bs1" for k, _s, _w in SUBP),
    "M6 바이빗 내부 입금 패스 = 서브는 그 계정 키·가상 상태(저장은 정본)·딱지 출구로", [(k, type(s).__name__, type(w).__name__) for k, s, w in SUBP])

fb = rd("futures_bybit.json")
evs = sorted((e.get("uid"), e.get("acct")) for e in (fb or {}).get("events") or [])
chk(fb and evs == [("bb:1", None), ("bb:2", "s1")] and [p.get("acct") for p in fb.get("positions") or []] == [None, "s1"]
    and (fb.get("cursor") or {}).get("c") == "bm", "F1 선물 정본 = 메인+서브 정산 합집합(서브 acct) · 포지션 이어 붙임 · 커서 = 메인", fb)
chk(rd("futraw_bybit_main.json") and rd("futraw_bybit_s1.json") and (rd("futraw_bybit_s1.json") or {}).get("cursor", {}).get("c") == "bs1",
    "F2 계정별 원본(futraw_bybit_main · futraw_bybit_s1 — 서브 커서 따로)")
raw_s1 = rd("futraw_bybit_s1.json")
raw_s1["ts"] = int(time.time()) - 3600
json.dump(raw_s1, open(os.path.join(S, "futraw_bybit_s1.json"), "w"))
X._fut_merge("bybit", ["", "s1"])
fb2 = rd("futures_bybit.json")
chk(fb2["ts"] == raw_s1["ts"], "F3 정본 ts = 계정 중 가장 이른 것(한 계정이라도 못 덮은 구간은 대사가 기다림)", [fb2["ts"], raw_s1["ts"]])

CFG["fail_sub_wd"] = True
out4 = run_cycles(4)
chk(rd("exf_balances_bybit.json") is None and rd("exf_balances_bybit.json.pending") is None,
    "M4 서브 입출금 계속 실패(이력 미완) = 바이빗 대사용 정식·pending 없음(가짜 보정 방지)", [rd("exf_balances_bybit.json"), rd("exf_balances_bybit.json.pending")])
chk((rd("exf_balances_bybit.json.view") or {}).get("balances") == {"USDT": 150.0, "BTC": 1.0}, "M4 표시용은 합으로 갱신")
chk(rd("exf_balances_okx.json"), "M4 다른 거래소(OKX)는 그대로 승격")
CFG["fail_sub_wd"] = False
run_cycles(3, clear=False)
chk((rd("exf_balances_bybit.json") or {}).get("balances") == {"USDT": 150.0, "BTC": 1.0}, "M4 서브 이력을 받은 뒤 = 합 잔고 승격", rd("exf_balances_bybit.json"))

CFG["deny_sub_wd"] = True
run_cycles(3)
st_r = (((rd("exf_state.json") or {}).get("bybit") or {}).get("accts") or {}).get("s1") or {}
chk((rd("exf_balances_bybit.json") or {}).get("balances") == {"USDT": 150.0, "BTC": 1.0} and st_r.get("wd_denied") and not st_r.get("backfilled_until"),
    "R2 서브 키 입출금 권한 거부(403) = 대사 보류 안 함(합 잔고 승격) · 입출금 백필 도장은 안 찍음", [rd("exf_balances_bybit.json"), st_r.get("wd_denied")])
CFG["deny_sub_wd"] = False
run_cycles(1, clear=False)
dep_r = [d for r in OUT if r.get("kind") == "ex_snapshot" for d in r.get("deposits") or [] if d.get("acct") == "s1"]
chk(dep_r and all(d.get("late") == 1 for d in dep_r), "R2 권한이 생겨 처음 받는 서브 입출금 = late(그 사이 대사 흡수분 되돌림)", dep_r)

CFG["deny_sub_wd"] = True
run_cycles(2, clear=False)
CFG["deny_sub_wd"] = False
_bal_s1 = BAL["bs1"]
_wd_orig = fake_wd


def fake_wd2(ex):
    f0 = _wd_orig(ex)

    def f(env, t0, t1, dep_t0=None):
        w9, d9 = f0(env, t0, t1, dep_t0)
        if ex == "bybit" and k_of(env, ex) == "bs1":
            d9 = d9 + [X.norm_row("bybit", "d2", "USDT", 7, 0, "tbs1b", "ACCEPTED", NOW - 300, NOW - 300)]
        return w9, d9
    return f


fake_wd = fake_wd2
run_cycles(1, clear=False)
fake_wd = _wd_orig
dep_r2 = [d for r in OUT if r.get("kind") == "ex_snapshot" for d in r.get("deposits") or [] if d.get("acct") == "s1"]
chk(dep_r2 and all(d.get("late") == 1 for d in dep_r2) and any(d["uuid"] == "bybit:s1:d2" for d in dep_r2),
    "R2b 백필 끝난 서브가 권한을 잃었다 되찾은 첫 주기 행 = late(이중 계상 방지 · 코덱스 sub1013b)", dep_r2)

CFG["env"] = {k: v for k, v in ENV.items() if not k.startswith("TJ_BYBIT_SUB1_")}
BAL["bm"] = {"USDT": 100.0, "BTC": 1.0}
run_cycles(3, clear=False)
bb5 = rd("exf_balances_bybit.json") or {}
chk(bb5.get("balances") == {"USDT": 150.0, "BTC": 1.0} and "s1:spot" in (bb5.get("sources") or []),
    "M5 서브 키를 지워도 마지막 잔고 USDT 50 을 그대로 더함 · 소스 이름 그대로(새 소스·사라진 소스로 안 보임)", bb5)
chk(not [c for c in CALLS if c[2] == "bs1"], "M5 지운 서브 키로는 호출 안 함")
fb5 = rd("futures_bybit.json") or {}
chk(("bb:2", "s1") in {(e.get("uid"), e.get("acct")) for e in fb5.get("events") or []}, "M5 지운 서브의 지난 선물 정산은 정본에 남음(메인 단독 모드가 이어 씀)")
CFG["env"] = dict(ENV)

URLS = []
_svh = (X.http_json, X._gov_prepare, X._srv_ms, X.time.sleep)
X.http_json = lambda url, headers=None, data=None, **k: URLS.append(url) or {"retCode": 0, "result": {"rows": []}}
T.patch_moved("http_json", X.http_json, ("exf_",))
X._gov_prepare = lambda h, p: None
T.patch_moved("_gov_prepare", X._gov_prepare, ("exf_",))
X._srv_ms = lambda h: int(time.time() * 1000)
T.patch_moved("_srv_ms", X._srv_ms, ("exf_",))
X.time.sleep = lambda s9: None
try:
    X.fetch_bybit({"TJ_BYBIT_KEY": "a", "TJ_BYBIT_SECRET": "b"}, NOW - 86400, NOW)
    main_u = list(URLS)
    URLS.clear()
    with X._acct_ctx("s1"):
        X.fetch_bybit({"TJ_BYBIT_KEY": "a", "TJ_BYBIT_SECRET": "b"}, NOW - 86400, NOW)
    sub_u = list(URLS)
finally:
    X.http_json, X._gov_prepare, X._srv_ms, X.time.sleep = _svh
    for _n9 in ("http_json", "_gov_prepare", "_srv_ms"):
        T.patch_moved(_n9, getattr(X, _n9), ("exf_",))
chk(any("withdraw/query-record" in u for u in main_u) and not any("withdraw/query-record" in u for u in sub_u) and any("deposit/query-record" in u for u in sub_u),
    "R1 바이빗 서브 = 출금 이력 조회 안 함(메인 UID 전용 API) · 입금은 조회", [main_u, sub_u])
for p9 in ("futures_bybit.json", "futraw_bybit_main.json", "futraw_bybit_s1.json", "futraw_bybit_s2.json"):
    if os.path.exists(os.path.join(S, p9)):
        os.remove(os.path.join(S, p9))
common.atomic_write_json(os.path.join(S, "futures_bybit.json"), {"ts": NOW, "events": [{"t": 1, "kind": "REALIZED", "amount": 5.0, "uid": "bb:old", "acct": "s1"},
                                                                                     {"t": 2, "kind": "REALIZED", "amount": 1.0, "uid": "bb:m"}]})
common.atomic_write_json(os.path.join(S, "futraw_bybit_main.json"), {"ts": NOW, "events": [{"t": 2, "kind": "REALIZED", "amount": 1.0, "uid": "bb:m"}]})
common.atomic_write_json(os.path.join(S, "futraw_bybit_s2.json"), {"ts": NOW, "events": [{"t": 3, "kind": "REALIZED", "amount": 2.0, "uid": "bb:s2"}]})
X._fut_merge("bybit", ["", "s2"])
fr = rd("futures_bybit.json") or {}
chk(sorted((e.get("uid"), e.get("acct")) for e in fr.get("events") or []) == [("bb:m", None), ("bb:old", "s1"), ("bb:s2", "s2")] and "inc_cov_ts" not in fr,
    "R3 서브 여럿 중 s1 키를 지워도 s1 의 지난 선물 정산 보존(메인·s2 와 함께)", fr.get("events"))
os.remove(os.path.join(S, "futraw_bybit_s2.json"))
X._fut_merge("bybit", ["", "s2"])
chk((rd("futures_bybit.json") or {}).get("inc_cov_ts") == 0, "R4 원본이 아직 없는 활성 서브(첫 조회 실패) = 선물 확인 미완(inc_cov_ts 0 → core 가 대사 기다림)")
X._fut_merge("bybit", ["", "s2"], denied={"s2"})
chk("inc_cov_ts" not in (rd("futures_bybit.json") or {}), "R4 그 서브가 권한 거부 쿨다운이면 선물 없음으로(대사 막지 않음)")
import core as _core9

chk(_core9.Core._exf_has_fut_src(["spot", "s1:futures"]) and _core9.Core._exf_has_fut_src(["futures"]) and not _core9.Core._exf_has_fut_src(["s1:spot", "earn"]),
    "R5 바이낸스 선물 지갑 소스 = 'futures' 또는 서브 's1:futures'")

chk(X._ak("bybit") == "bybit", "C1 메인 열쇠 = 거래소 이름(저장된 쿨다운 호환)")
with X._acct_ctx("s1"):
    k1 = X._ak("bybit")
    with X._acct_ctx("s2"):
        k2 = X._ak("bybit")
    k3 = X._ak("bybit")
chk((k1, k2, k3, X._ak("bybit")) == ("bybit~s1", "bybit~s2", "bybit~s1", "bybit"), "C2 서브 열쇠 '거래소~s1' · 중첩·복원", (k1, k2, k3))
X._BAL_SRC_OFF.clear()
X._bal_src_had_load().clear()
X._COOL_ON[0] = False


def deny(o):
    raise RuntimeError("HTTP 403 합성 거부")


try:
    with X._acct_ctx("s1"):
        X._sub_bal("bybit", "earn", deny, X._Bal(), lenient=True)
except Exception:
    pass
chk(("bybit~s1", "earn") in X._BAL_SRC_OFF and ("bybit", "earn") not in X._BAL_SRC_OFF, "C3 서브 Earn 거부 쿨다운 = 서브 열쇠만(메인 Earn 은 계속)", dict(X._BAL_SRC_OFF))

import depaddr

RF = []
_sv = (depaddr.refresh, depaddr.due)
depaddr.refresh = lambda ex, env, reason="manual", only=None, hist_only=False, now=None, pace=None, acct="": RF.append((ex, acct, env.get("TJ_BYBIT_KEY") if ex == "bybit" else env.get("TJ_OKX_KEY"))) or {}
depaddr.due = lambda ex, env, store, now, cc, acct="": ("first", None, False, 0)
try:
    depaddr.tick(lambda: dict(ENV), {})
finally:
    depaddr.refresh, depaddr.due = _sv
chk(("bybit", "", "bm") in RF and ("okx", "", "om") in RF and not [r for r in RF if r[0] in ("bybit", "okx", "bithumb") and r[1]],
    "D1 입금주소 = 바이빗·OKX 서브는 수집 안 함(거래소가 서브 입금을 막음 — 라이브 실측 58209·131003) · 메인은 그대로", RF)
ENV2 = dict(ENV, TJ_GATE_KEY="gm", TJ_GATE_SECRET="gms", TJ_GATE_SUB1_KEY="gs1", TJ_GATE_SUB1_SECRET="gs1s")
RF.clear()
depaddr.refresh = lambda ex, env, reason="manual", only=None, hist_only=False, now=None, pace=None, acct="": RF.append((ex, acct, env.get("TJ_GATE_KEY"))) or {}
depaddr.due = lambda ex, env, store, now, cc, acct="": ("first", None, False, 0)
try:
    depaddr.tick(lambda: dict(ENV2), {})
finally:
    depaddr.refresh, depaddr.due = _sv
chk(("gate", "s1", "gs1") in RF and ("gate", "", "gm") in RF, "D1 서브 입금이 되는 거래소(게이트 등) 서브 = 그 계정 키로 수집(메타 '거래소~딱지')", RF)
store = depaddr._empty_store()
depaddr.merge(store, "bybit", [{"currency": "USDT", "network": "ETH", "address": "0x" + "5" * 40, "source": "api"}], NOW, acct="s1")
chk(store["records"][0]["exchange"] == "bybit" and store["records"][0].get("acct") == "s1", "D2 서브 입금주소 레코드 = exchange 'bybit'(같은 거래소로 판정) · acct", store["records"])
chk(depaddr._rmeta(store["records"][0], {"bybit~s1": {"last_full": 1}, "bybit": {"last_full": 2}}) == {"last_full": 1}, "D3 '지금 주소' 판정은 그 계정 메타로")

import settings_store as ss

chk(list(ss.EXCHANGES) == ["upbit", "bithumb", "binance", "bybit", "okx", "kucoin", "gate"], "S1 EXCHANGES 무변(연결 거래소·백필 표식·입금주소 대상 = 거래소 단위)")
g9 = ss.GROUPS.get("bybit_sub1") or {}
chk([k for k, _l in g9.get("fields") or []] == ["TJ_BYBIT_SUB1_KEY", "TJ_BYBIT_SUB1_SECRET"] and g9.get("name") == "바이빗 서브1" and ss.base_ex("bybit_sub1") == "bybit"
    and ss.base_ex("bybit") == "bybit" and ss.base_ex("etherscan") is None, "S2 서브 그룹 'bybit_sub1'(칸·이름·base)", g9)
chk("TJ_OKX_SUB5_PASSPHRASE" in ss.SECRET_KEYS and "TJ_OKX_SUB5_KEY" in ss.PUBLIC_KEY_FIELDS and "TJ_OKX_SUB5_SECRET" not in ss.PUBLIC_KEY_FIELDS
    and "upbit_sub1" not in ss.GROUPS and "bithumb_sub1" not in ss.GROUPS, "S3 비밀 칸·공개 칸(첫 칸만) · 업비트·빗썸 서브 없음")
with open(common.ENV_PATH, "w") as f9:
    f9.write("".join(f"{k}={v}\n" for k, v in ENV.items()))
import onboarding

st9 = T.safe(onboarding.status) or {}
exs9 = st9.get("exchanges") or {}
bbx, okx9 = exs9.get("bybit") or {}, exs9.get("okx") or {}
chk([x.get("group") for x in bbx.get("subs") or []] == ["bybit_sub1", "bybit_sub3"] and (bbx.get("subs") or [{}])[0].get("set") is True
    and (bbx.get("subs") or [{}, {}])[1].get("partial") is True and (bbx.get("subNext") or {}).get("group") == "bybit_sub2"
    and (bbx.get("subNext") or {}).get("permCheck") is True, "S4 설정 상태: 바이빗 서브1 연결됨 · 서브3 일부 입력 · 다음 빈 칸 서브2", bbx.get("subs"))
chk([x.get("group") for x in okx9.get("subs") or []] == ["okx_sub2"] and (okx9.get("subNext") or {}).get("group") == "okx_sub1"
    and "subs" not in (exs9.get("upbit") or {}), "S5 OKX 서브2 · 다음 빈 칸 서브1 · 업비트 = 서브 칸 없음")
chk(not [k for x in bbx.get("subs") or [] for f in x.get("fields") or [] for k in ("bs1", "bs1s") if k in json.dumps(f)],
    "S6 설정 상태에 서브 키 값 없음(가림)", bbx.get("subs"))
os.remove(common.ENV_PATH)

web_src = T.web_src()
import re

rx = re.compile(r"^[a-z]+:(s[1-9]):")
chk(rx.match("bybit:s1:123") and not rx.match("binance:BNBUSDT:1") and not rx.match("bybit:int:5"), "V1 서브 id 판정(메인 id·내부 입금 id 아님)")
chk('SUB_SID_RE = re.compile(r"^[a-z]+:(s[1-9]):")' in web_src and 'd = f"{d} · 서브{ms9.group(1)[1:]}"' in web_src, "V2 기록 줄 '· 서브N' 딱지(ev)")
setup_js = open(os.path.join(T.ROOT, "web", "v2", "setup.js"), encoding="utf-8").read()
chk("function subsHTML(k, g)" in setup_js and "+ 서브계정 키 추가" in setup_js and "subx(el)" in setup_js, "V3 설정 화면 서브계정 칸·추가 단추")
from decimal import Decimal

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
import core
import db as dbm

core.dm = lambda *a, **k: None
T.patch_moved("dm", core.dm)

c = core.Core(common.load_config())
c._quote_usd = lambda q, ts: Decimal(1) if str(q).upper() in ("USDT", "USDC") else None
c.px.fx_at = lambda ms: 1380.0
recs = [r for r in c1 if r.get("kind") in ("ex_snapshot", "exf_fills") and r.get("exchange") == "bybit"]
for r in recs:
    (c._consume_ex if r["kind"] == "ex_snapshot" else c._consume_exf_fills)(r)
c.conn.commit()


def held(sym, loc="exchange:bybit"):
    r9 = c.conn.execute("SELECT COALESCE(sum(CAST(p.qty_base AS INTEGER)), 0), max(a.decimals) FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                        " WHERE p.location=? AND upper(a.symbol)=?", (loc, sym)).fetchone()
    return Decimal(r9[0]) / (Decimal(10) ** int(r9[1] or 8))


sids = sorted(r[0] for r in c.conn.execute("SELECT DISTINCT source_id FROM postings WHERE location='exchange:bybit'"))
chk("bybit:s1:d1" in sids and "bybit:d1" in sids and "bybit:s1:e1" in sids and "bybit:e1" in sids,
    "E1 서브 입금·체결 = 같은 위치 exchange:bybit 에 따로 기장(같은 원래 번호여도)", sids)
chk(held("BTC") == Decimal("1.5") and held("USDT") == 0, "E1 원장 = 메인+서브(BTC 1 + 0.5 · USDT 100+50 입금 − 매수 100+50)", (held("BTC"), held("USDT")))
for p9 in os.listdir(S):
    if p9.startswith(("exf_balances_", "futures_", "futraw_")):
        os.remove(os.path.join(S, p9))
common.atomic_write_json(os.path.join(S, "exf_state.json"), {"bybit": {"seen": {}, "backfilled_until": NOW, "fills": {"backfilled_until": NOW}}})
common.atomic_write_json(os.path.join(S, "exf_balances_bybit.json"), {"ts": NOW, "balances": {"BTC": 1.5}, "sources": ["s1:spot"]})
c._last_exfrecon = 0
c._drain_at = NOW + 100000
T.safe(c.exf_recon_pass, drained=frozenset({"ex"}))
adj = c.conn.execute("SELECT count(*) FROM postings WHERE source_ns='bybit:recon'").fetchone()[0]
chk(adj == 0 and c._meta_get("recon_done_exf_bybit"), "E2 메인+서브 합 잔고(BTC 1.5)로 첫 대사 = 보정 0 · 대사 완료 표식", adj)
common.atomic_write_json(os.path.join(S, "exf_balances_bybit.json"), {"ts": NOW + 400, "balances": {"BTC": 1.5, "ETH": 2.0},
                                                                       "sources": ["s1:spot", "s2:spot"]})
c._last_exfrecon = 0
T.safe(c.exf_recon_pass, drained=frozenset({"ex"}))
c.conn.commit()
eth = c.conn.execute("SELECT p.event_ts, p.qty_base FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.source_ns='bybit:recon' AND upper(a.symbol)='ETH'").fetchall()
chk(len(eth) == 1 and int(eth[0][0]) < NOW - 30 * 86400 and held("ETH") == 2,
    "E3 나중에 붙인 서브의 원래 보유 ETH 2 = 수집 이전 보유(창 시작 시각 — 그날 유입·손익으로 안 보임)", [tuple(x) for x in eth])
c.conn.close()

import netpace
import web

for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker"):
    if hasattr(web.StateBuilder, _m):
        setattr(web.StateBuilder, _m, lambda self: None)
netpace.wait = lambda url, now=None, sleep=None: None
web.pricing._gj = lambda url, *a, **k: (_ for _ in ()).throw(OSError("시험: 시세 받기 없음"))
web.pricing.PxCache.fx_at = lambda self, ms: 1380.0
_px = {"USDT": 1.0, "BTC": 100.0, "ETH": 3000.0}
web.pricing.PxCache.candle_usd = lambda self, sym, ms: _px.get(str(sym).upper())
json.dump({"usd": _px, "usd_ts": {k: NOW for k in _px}, "rate": 1380.0, "updated": NOW, "dex_usd": {}, "dex_ts": {}, "dex_res": {}, "dex_res_ts": {},
           "fx_basis": 1380.0, "ex_usd": {}, "ex_ts": {}}, open(web.SPOT_PATH, "w"))
common.atomic_write_json(web.PREFS_PATH, {"plans": {}, "ignored": []})
b = web.StateBuilder()
b.skip_gen_check = True
conn = dbm.open_db(common.DB_PATH, readonly=True)
try:
    f = (T.safe(b._build, conn) or {}).get("fields") or {}
finally:
    conn.close()
evs = [e for p9 in (f.get("_positionsAll") or f.get("positions") or []) for e in (p9.get("events") or []) if "바이빗" in str(e.get("d"))]
chk(any("· 서브1" in str(e.get("d")) for e in evs) and any("· 서브1" not in str(e.get("d")) and "현물 체결" in str(e.get("d")) for e in evs),
    "E4 화면 기록 줄: 서브 체결·입금 = '· 서브1' · 메인 줄은 딱지 없음", [e.get("d") for e in evs])
common.atomic_write_json(os.path.join(S, "futures_bybit.json"), {"ts": int(time.time()), "wallet": {"balance": None}, "accts": ["main", "s1"],
    "positions": [{"symbol": "WOOUSDT", "side": "LONG", "qty": 10, "entry": 0.1, "mark": 0.11, "upnl": 0.1, "leverage": "5", "liq": 0, "acct": "s1"},
                  {"symbol": "BTCUSDT", "side": "SHORT", "qty": 1, "entry": 100, "mark": 99, "upnl": 1, "leverage": "2", "liq": 0}],
    "events": [{"t": (NOW - 600) * 1000, "symbol": "WOOUSDT", "kind": "REALIZED", "amount": -0.015, "uid": "bb:w1", "acct": "s1"},
               {"t": (NOW - 500) * 1000, "symbol": "WOOUSDT", "kind": "FEE", "amount": -0.002, "uid": "bb:w1f", "acct": "s1"},
               {"t": (NOW - 400) * 1000, "symbol": "BTCUSDT", "kind": "REALIZED", "amount": 2.0, "uid": "bb:m1"}]})
fv = T.safe(b._futures_view) or {}
rws = {(r.get("sym"), r.get("ex")) for r in fv.get("realizedRows") or []}
psx = {(p9.get("sym"), p9.get("ex"), p9.get("exKey")) for p9 in fv.get("positions") or []}
chk(("WOOUSDT", "바이빗 · 서브1") in rws and ("BTCUSDT", "바이빗") in rws, "G1 선물 정산 목록 = 서브 줄 '바이빗 · 서브1' · 메인 '바이빗'", rws)
chk(("WOOUSDT", "바이빗 · 서브1", "bybit") in psx and ("BTCUSDT", "바이빗", "bybit") in psx, "G2 선물 포지션 = 서브 '바이빗 · 서브1'(exKey 는 bybit 그대로)", psx)
fee_ex = {x.get("ex") for x in (getattr(b, "_fut_detail", None) or {}).get("fee") or []}
chk(fee_ex == {"바이빗 · 서브1"}, "G3 선물 수수료·펀딩 명세 = 서브 딱지", fee_ex)
app_js = T.app_js()
chk("const SUB_SFX = / · 서브[1-9]$/;" in app_js and "esc(exNm(p.ex))" in app_js and "replace(SUB_SFX, '')" in app_js,
    "G4 화면: 거래소 키 찾기는 딱지를 떼고(로고) · 이름엔 딱지 붙여 보임")
T.finish()
