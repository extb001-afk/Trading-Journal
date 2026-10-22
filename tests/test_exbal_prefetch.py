#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
from decimal import Decimal  # noqa: E402

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
W = "0x" + "1a" * 20
USDT_ETH = "0xdac17f958d2ee523a2206206994597c13d831ec7"
CFG = {"chains": {"eth": {"blockscout": "https://bs.invalid", "conf_depth": 12, "blocks_per_day": 7200, "rpcs": ["https://rpc.invalid"]}},
       "wallets": [{"type": "evm", "chain": "eth", "address": W, "label": "new"}], "backfill_months": 2}
json.dump(CFG, open(os.path.join(T.TMP, "config.json"), "w"))
import config, paths, statefile  # noqa: E402
import core  # noqa: E402
import db as dbm  # noqa: E402
import exprov  # noqa: E402
import ex_foreign as X  # noqa: E402
import histcurve  # noqa: E402
import netpace  # noqa: E402
import web  # noqa: E402

assert T.TMP in paths.STATE_DIR
chk = T.chk
S = paths.STATE_DIR
NOW = int(time.time())
DAY = 86400
E8 = 10 ** 8

EXS = list(X.FETCHERS)
chk(len(EXS) == 7 and EXS[0] == "binance", "A0 해외 거래소 7곳(업비트 = 따로 tj-ex · 5분 안 대사 정상 · 코인베이스 포함) — 바이낸스가 첫 차례", EXS)
LOG = []
BAL = {ex: {"USDT": 100.0 + i, "BTC": 0.01 * (i + 1)} for i, ex in enumerate(EXS)}


class _Stop(Exception):
    pass


def fake_bal(ex):
    def f(env):
        LOG.append(("bal", ex))
        b = X._Bal(BAL[ex])
        b.sources = ["spot"]
        return b
    return f


def fake_wd(ex):
    def f(env, t0, t1, dep_t0=None):
        LOG.append(("wd", ex))
        return [], []
    return f


SLOW = {"on": True}


def fake_fills(ex):
    def f(env, fst, t0, t1):
        LOG.append(("fills", ex))
        if ex == "binance" and SLOW["on"]:
            fst["partial"] = "후보 밖 전 심볼 첫 바퀴 진행 중(합성 — 3,724개 중 200개)"
        return []
    return f


def run_cycles(n, prefetch=True):
    for p in os.listdir(S):
        if p.startswith("exf_") and os.path.isfile(os.path.join(S, p)):
            os.remove(os.path.join(S, p))
    X._VIEW_CYC.clear()
    X._quiet_n.clear()
    LOG.clear()
    cnt = {"n": 0}

    def sleep(_s):
        cnt["n"] += 1
        LOG.append(("cycle_end", cnt["n"]))
        if cnt["n"] >= n:
            raise _Stop()
    saved = {}

    def patch(obj, name, val):
        saved[(obj, name)] = getattr(obj, name)
        setattr(obj, name, val)
    patch(X, "FETCHERS", {ex: (fake_wd(ex), need) for ex, (_f, need) in X.FETCHERS.items()})
    patch(X, "BAL_FETCHERS", {ex: fake_bal(ex) for ex in EXS})
    patch(X, "FILL_FETCHERS", {ex: fake_fills(ex) for ex in EXS})
    patch(X, "_env", lambda: {k: "k" for _f, need in X.FETCHERS.values() for k in need})
    for nm in ("dest_backfill_pass", "krw_backfill_pass", "bybit_internal_pass", "pending_recheck_pass", "futures_snapshot_all", "leverage_pass"):
        patch(X, nm, lambda *a, **k: None)
    patch(X, "convert_rows", lambda *a, **k: [])
    patch(X, "ext_trigger_target", lambda *a, **k: None)
    patch(X, "_hl_on", lambda cfg: False)
    patch(X.depaddr, "start_background", lambda *a, **k: None)
    patch(X.depaddr, "notify", lambda *a, **k: None)
    patch(X.unit_beat, "start", lambda *a, **k: None)
    patch(X.runtime, "cpu_reserve_apply", lambda *a, **k: None)
    patch(X.time, "sleep", sleep)
    if not prefetch:
        patch(X, "balance_prefetch", lambda env, cyc, fetchers=None: {})
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
    return list(LOG)


def rd(p):
    try:
        return json.load(open(os.path.join(S, p)))
    except FileNotFoundError:
        return None


lg = run_cycles(2)
c1 = lg[:lg.index(("cycle_end", 1))]
c2 = lg[lg.index(("cycle_end", 1)) + 1:lg.index(("cycle_end", 2))]
first_old = min(i for i, e in enumerate(c1) if e[0] in ("wd", "fills"))
pre1 = [e[1] for e in c1[:first_old] if e[0] == "bal"]
chk(sorted(pre1) == sorted(EXS) and all(e[0] == "bal" for e in c1[:first_old]),
    "A1 첫 주기: 7곳 잔고가 어떤 입출금·체결 수집보다 먼저(바이낸스 체결 첫 바퀴가 부분 주기여도)", c1)
views = {ex: rd(f"exf_balances_{ex}.json.view") for ex in EXS}
chk(all(v and v.get("balances") == BAL[ex] for ex, v in views.items()), "A1 7곳 표시용 잔고(.view) = 지금 잔고", views)
chk(rd("exf_balances_binance.json") is None and rd("exf_balances_binance.json.pending") is None,
    "A2 바이낸스 부분 주기 = 대사용 정식·pending 없음(먼저 읽기는 표시용만 — 승격 규칙 그대로)")
chk(all(rd(f"exf_balances_{ex}.json.pending") for ex in EXS if ex != "binance"), "A2 다른 6곳 = 종전처럼 주기 끝 pending")
n_end1 = sum(1 for e in c1[first_old:] if e[0] == "bal")
chk(n_end1 == 6, "A2 첫 주기 주기 끝 잔고 읽기 = 조용한 6곳(바이낸스 부분 주기 = 종전처럼 안 읽음)", n_end1)
pre2 = [e[1] for e in c2[:min(i for i, e in enumerate(c2) if e[0] in ("wd", "fills"))] if e[0] == "bal"]
chk(pre2 == ["binance"], "A3 둘째 주기 먼저 읽기 = 바이낸스만(나머지는 직전 주기 끝에 썼음 — 호출 안 늘어남)", c2)
chk(sum(1 for e in c2 if e[0] == "bal") == 7, "A3 둘째 주기 잔고 읽기 합 = 7(바이낸스 먼저 1 + 조용한 6곳 주기 끝)")
chk(all(rd(f"exf_balances_{ex}.json") for ex in EXS if ex != "binance") and rd("exf_balances_binance.json") is None,
    "A3 둘째 주기: 6곳 정식 승격(두 표본 일치) · 바이낸스는 여전히 보류(첫 바퀴 중)")

SLOW["on"] = False


def snap_files():
    out = {}
    for ex in EXS:
        for suf in ("", ".pending"):
            d = rd(f"exf_balances_{ex}.json{suf}")
            out[ex + suf] = None if d is None else {k: v for k, v in d.items() if k != "ts"}
    return out


lg_on = run_cycles(3, prefetch=True)
f_on = snap_files()
lg_off = run_cycles(3, prefetch=False)
f_off = snap_files()
chk(f_on == f_off and all(f_on.values()), "A4 라이브 꼴(3주기 · 모두 조용): 정식·pending 값 = 먼저 읽기 끈 것과 같음", [f_on, f_off])
n_on, n_off = sum(1 for e in lg_on if e[0] == "bal"), sum(1 for e in lg_off if e[0] == "bal")
chk(n_on - n_off == 7, "A4 추가 호출 = 기동 첫 주기 거래소당 1번뿐(3주기 합 차이 7)", [n_on, n_off])
chk([e for e in lg_on if e[0] != "bal"] == [e for e in lg_off if e[0] != "bal"], "A4 입출금·체결 수집 순서·횟수 같음")

T.patch_moved("dm", lambda *a, **k: None)
for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker"):
    if hasattr(web.StateBuilder, _m):
        setattr(web.StateBuilder, _m, lambda self: None)
netpace.wait = lambda url, now=None, sleep=None: None
for p in os.listdir(S):
    if p.startswith("exf_"):
        os.remove(os.path.join(S, p))
C = core.Core(config.load_config())
C.svc_exf._quote_usd = lambda q, ts: Decimal(1)
SEQ = {"n": 0}


def post(ex, t, sym, qty, ev="EXF_DEPOSIT", lk="move_in"):
    aid = C.svc_exf._exf_asset(ex, sym)
    qb = int(Decimal(str(qty)) * E8)
    SEQ["n"] += 1
    C.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw,"
                   " leg_kind, event, classifier_ver) VALUES ('exchange',?,?,0,?,?,?,?,?,NULL,?,?,?)",
                   (f"{ex}:{'trade' if ev in ('EXF_BUY', 'EXF_SELL') else 'deposit'}", f"s{SEQ['n']}", int(t), aid, f"exchange:{ex}", str(qb),
                    repr(abs(float(qty))) if lk in ("acq", "disp") else None, lk, ev, core.CLASSIFIER_VER))
    C._bump_position(aid, qb, f"exchange:{ex}")


post("binance", NOW - 20 * DAY, "USDT", 1000)
post("binance", NOW - 10 * DAY, "USDT", -500, "EXF_SELL", "disp")
post("binance", NOW - 10 * DAY, "BTC", "0.01", "EXF_BUY", "acq")
post("bybit", NOW - 20 * DAY, "USDT", 700)
C.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('recon_done_exf_bybit', ?)", (str(NOW - 3600),))
C.conn.commit()
BN = {"balances": {"USDT": 5000.0, "BTC": 0.01, "ETH": 2.0, "KRW": 1400000.0, "USD": 50.0}, "sources": ["spot"]}
BB = {"balances": {"USDT": 700.0}, "sources": ["spot"]}
px = {"BTC": 60000.0, "ETH": 3000.0}
json.dump({"usd": px, "usd_ts": {k: NOW for k in px}, "rate": 1400.0, "updated": NOW, "dex_usd": {}, "dex_ts": {}, "dex_res": {}, "dex_res_ts": {},
           "fx_basis": 1400.0, "ex_usd": {f"{e}:{k}": v for k, v in px.items() for e in ("binance", "bybit")},
           "ex_ts": {f"{e}:{k}": NOW for k in px for e in ("binance", "bybit")}}, open(paths.state("spot.json"), "w"))
web.pricing.PxCache.candle_usd = lambda self, sym, ms: None
web.pricing.PxCache.fx_at = lambda self, ms: 1400.0
web.pricing._gj = lambda url, timeout=10.0: None
histcurve.DAYCLOSE.lookup = lambda spec, iso, now=None, w=0.0, ask=True, old=False: (None, "pending")
histcurve.DAYCLOSE.lookup._tj_test_mock = True
statefile.atomic_write_json(paths.state("ui_prefs.json"), {"plans": {}, "ignored": []})


def wbal(ex, d, suf=".view", ts=None):
    statefile.atomic_write_json(os.path.join(S, f"exf_balances_{ex}.json{suf}"), dict(d, ts=int(ts or time.time() - 30)))


def build(off=False):
    for p9 in (paths.state("daily_cache.json"), paths.state("daily_px.json")):
        try:
            os.remove(p9)
        except FileNotFoundError:
            pass
    b = web.StateBuilder()
    b.skip_gen_check = True
    if off:
        b._exf_prov_items = lambda conn, exb: []
        b._prov_seen = lambda conn, exb: ({}, {})
    conn = dbm.open_db(paths.DB_PATH, readonly=True)
    try:
        return b._build(conn)["fields"]
    finally:
        conn.close()


def coins_usd(f):
    return round(sum(float(x.get("qty") or 0) * float(x.get("price") or 0) for x in (f.get("stables") or []) + (f.get("coins") or [])), 2)


def rows(f, sym):
    return [x for x in (f.get("stables") or []) + (f.get("coins") or []) if str(x.get("sym") or "").upper() == sym]


wbal("binance", BN)
wbal("bybit", BB, suf="")
out_b1 = build()
exp_b1 = 5000 + 600 + 6000 + 700
chk(abs(coins_usd(out_b1) - exp_b1) < 0.02, "B1 첫 대사 전 바이낸스(.view 만 · 승격 보류) = 총자산에 지금 거래소 잔고(코인·스테이블 합)", [coins_usd(out_b1), exp_b1])
pv_b1 = (out_b1.get("prov") or {})
chk("exchange:binance" in (pv_b1.get("chains") or {}) and "바이낸스 거래소" in str(pv_b1.get("note") or ""),
    "B1 안내 칸(prov) = 바이낸스 '지금 잔고(옛 기록 받는 중)' · 바이빗(대사 끝)은 없음", pv_b1)
eth_r = rows(out_b1, "ETH")
usdt_bn = [l for x in rows(out_b1, "USDT") for l in x.get("locs") or [] if l.get("w") == "바이낸스"]
chk(len(eth_r) == 1 and str(eth_r[0].get("key")).startswith("pvx:binance:") and abs(float(eth_r[0]["qty"]) - 2.0) < 1e-9,
    "B2 원장이 모르는 심볼(ETH) = 새 행 pvx:binance:ETH 2", eth_r)
chk(len(usdt_bn) == 1 and abs(float(usdt_bn[0]["qty"]) - 5000) < 1e-6 and usdt_bn[0].get("pv") == 1,
    "B2 원장이 아는 심볼(USDT 원장 500) = 그 행 바이낸스 수량이 지금 잔고 5,000(임시 표시)", usdt_bn)
chk(not rows(out_b1, "KRW") and not rows(out_b1, "USD"), "B2 원화·달러 = 코인 행 아님(원화는 예수금 줄)")
chk(C.conn.execute("SELECT COUNT(*) FROM postings WHERE event='EXF_ADJUST'").fetchone()[0] == 0, "B1 원장 대사 안 됨(EXF_ADJUST 0 — 화면 전용)")
wbal("binance", BN, suf="", ts=NOW - 30)
statefile.atomic_write_json(os.path.join(S, "exf_state.json"), {"binance": {"seen": {}, "backfilled_until": NOW, "fills": {"backfilled_until": NOW}}})
C._drain_at = NOW + 5
C.svc_exf._last_exfrecon = 0
C.svc_exf.exf_recon_pass({"ex"})
nadj = C.conn.execute("SELECT COUNT(*) FROM postings WHERE event='EXF_ADJUST'").fetchone()[0]
chk(nadj >= 2 and C._meta_get("recon_done_exf_binance"), "B3 core 첫 대사 = 기초 잔고(USDT·ETH) · 표식", nadj)
out_b3 = build()
chk(abs(coins_usd(out_b3) - exp_b1) < 0.02, "B3 대사 뒤 총자산 같음(임시 몫 → 원장 기초 잔고 · 이중 계상 0)", [coins_usd(out_b3), exp_b1])
chk("exchange:binance" not in ((out_b3.get("prov") or {}).get("chains") or {}) and not any(str(x.get("key")).startswith("pvx:") for x in
    (out_b3.get("coins") or []) + (out_b3.get("stables") or [])), "B3 대사 뒤 임시 몫·pvx 행 없음(원장 값만)")
out_b4 = build(off=True)
chk(coins_usd(out_b4) == coins_usd(out_b3) and json.dumps([(x.get("key"), x.get("qty")) for x in out_b4.get("coins") + out_b4.get("stables")], sort_keys=True)
    == json.dumps([(x.get("key"), x.get("qty")) for x in out_b3.get("coins") + out_b3.get("stables")], sort_keys=True),
    "B4 라이브 꼴(대사 끝): 기능 끈 빌드와 보유·총자산 같음", [coins_usd(out_b3), coins_usd(out_b4)])

T_WD = NOW - 2 * 3600
post("binance", T_WD - 3600, "USDT", 30000)
C.svc_exf._consume_ex({"exchange": "binance", "deposits": [], "withdraws": [{
    "uuid": "wdX1", "currency": "USDT", "amount": "30000", "fee": "0", "txid": "0x" + "ab" * 32, "state": "DONE",
    "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(T_WD)), "done_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(T_WD + 60)),
    "address": W, "network": "ETH"}]})
C.conn.commit()
wbal("binance", dict(BN, balances=dict(BN["balances"], USDT=BN["balances"]["USDT"] - 30000 + 30000)), suf="", ts=NOW - 30)
PROV = {"eth": {"mode": "chain", "at": NOW - 600, "t1": NOW - 590, "block": 100, "bts": NOW - 600, "req": [W],
                "wallets": {W: {"tok": {USDT_ETH: [str(30000 * 10 ** 6), "USDT", 6]}, "q": [USDT_ETH]}}}}
json.dump(PROV, open(os.path.join(S, "prov_bal.json"), "w"))
out_c1 = build()
usdt_c1 = sum(float(x["qty"]) for x in rows(out_c1, "USDT"))
tr_c1 = [l for x in rows(out_c1, "USDT") for l in x.get("locs") or [] if l.get("tr")]
chk(not tr_c1, "C1 받는 지갑 첫 대사 전 + 잔고 관측이 출금 뒤 = '전송 중' 가산 없음", tr_c1)
chk(abs(usdt_c1 - (5000 + 700 + 30000)) < 1e-6, "C1a 아직 보유 = USDT 합 바이낸스 5,000 + 바이빗 700 + 지갑 지금 잔고 30,000 — 한 번만", usdt_c1)
off_c1 = build(off=True)
chk(abs(sum(float(x["qty"]) for x in rows(off_c1, "USDT")) - usdt_c1) < 1e-6,
    "C1a 종전(기능 끔)도 합은 같음(net_pending 이 지갑 몫을 전송 중만큼 상쇄 — 표시만 '전송 중' 대신 지갑 지금 잔고)")
PROV0 = json.loads(json.dumps(PROV))
PROV0["eth"]["wallets"][W]["tok"][USDT_ETH][0] = "0"
json.dump(PROV0, open(os.path.join(S, "prov_bal.json"), "w"))
out_c1b, off_c1b = build(), build(off=True)
u_on, u_off = (sum(float(x["qty"]) for x in rows(f9, "USDT")) for f9 in (out_c1b, off_c1b))
chk(abs(u_on - 5700) < 1e-6 and abs(u_off - 35700) < 1e-6,
    "C1b 이미 다른 데로 나감: 지금 = 5,700(받는 쪽 지금 잔고 0 그대로) · 종전 = 35,700(유령 전송 중 30,000 — 새 설치 실측 꼴)", [u_on, u_off])
json.dump(PROV, open(os.path.join(S, "prov_bal.json"), "w"))
C.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('recon_done_eth', ?)", (str(NOW - 60),))
C.conn.commit()
out_c2 = build()
tr_c2 = [l for x in rows(out_c2, "USDT") for l in x.get("locs") or [] if l.get("tr")]
chk(len(tr_c2) == 1 and abs(float(tr_c2[0]["qty"]) - 30000) < 1e-6, "C2 prov 풀린 뒤 도착 전 = 전송 중 30,000 그대로(종전 규칙)", tr_c2)
off_c2 = build(off=True)
chk(coins_usd(off_c2) == coins_usd(out_c2), "C2 라이브 꼴(대사 끝) = 기능 끈 빌드와 총자산 같음", [coins_usd(out_c2), coins_usd(off_c2)])
C.conn.execute("DELETE FROM meta WHERE k='recon_done_eth'")
C.conn.commit()
norm = web.xfer_match.norm_addr
cs = {("eth", norm(W)): 2000}
e0 = {"state": "pending", "cls": "wallet", "addr": W, "net": "ETH", "sym": "USDT", "start": 1500}
chk(exprov.covered(e0, chain_seen=cs, ex_seen={}, chain_of=web.depaddr.chain_of, norm=norm), "C3 관측 2000 ≥ 출금 1500 = 받는 쪽이 셈")
chk(not exprov.covered(dict(e0, start=2500), chain_seen=cs, ex_seen={}, chain_of=web.depaddr.chain_of, norm=norm), "C3 관측이 출금 전 = 전송 중 그대로")
chk(not exprov.covered(dict(e0, cls="unknown"), chain_seen=cs, ex_seen={}, chain_of=web.depaddr.chain_of, norm=norm), "C3 남의 주소 = 종전")
chk(not exprov.covered(dict(e0, net="BSC"), chain_seen=cs, ex_seen={}, chain_of=web.depaddr.chain_of, norm=norm), "C3 다른 체인(BSC 는 대사 끝) = 종전")
chk(exprov.covered({"state": "pending", "cls": "exchange", "dex": "okx", "start": 1500}, chain_seen={}, ex_seen={"okx": 1600},
                   chain_of=web.depaddr.chain_of, norm=norm), "C3 거래소행(받는 거래소 첫 대사 전 · 스냅숏이 출금 뒤) = 받는 쪽이 셈")
chk(not exprov.covered({"state": "pending", "cls": "exchange", "dex": "okx", "start": 1500}, chain_seen={}, ex_seen={},
                       chain_of=web.depaddr.chain_of, norm=norm), "C3 거래소행 · 받는 거래소 대사 끝 = 종전")
wl = [dict(e0, src="바이낸스", ev={"d": "x"}), dict(e0, state="arrived"), dict(e0, start=2500)]
n9 = web.StateBuilder._wdt_prov_mark(wl, cs, {})
chk(n9 == 1 and wl[0]["state"] == "prov" and "이미 반영" in wl[0]["ev"]["d"] and wl[1]["state"] == "arrived" and wl[2]["state"] == "pending",
    "C3 표식 = 전송 중 1건만 'prov'(기록 줄 문구) · 도착·관측 전 출금 그대로", wl)
import hl_spot  # noqa: E402
os.remove(os.path.join(S, "prov_bal.json"))
base_e = coins_usd(build())
post("okx", NOW - 5 * DAY, "USDT", -20000, "EXF_WITHDRAW", "move_out")
C.conn.commit()
OKX = {"balances": {"USDT": 19500.0, "ETH": 2.0}, "debts": {"USDT": -20300.0}, "sources": ["spot", "loan"],
       "loans": [{"src": "loan", "label": "담보대출", "debt": {"USDT": 20300.0}, "principal": {"USDT": 20000.0}, "collateral": {"ETH": 2.0}, "since": NOW - 30 * DAY}]}
px2 = dict(px, HYPE=40.0)
json.dump({"usd": px2, "usd_ts": {k: NOW for k in px2}, "rate": 1400.0, "updated": NOW, "dex_usd": {}, "dex_ts": {}, "dex_res": {}, "dex_res_ts": {},
           "fx_basis": 1400.0, "ex_usd": {f"{e}:{k}": v for k, v in px2.items() for e in ("binance", "bybit", "okx", "hyperliquid")},
           "ex_ts": {f"{e}:{k}": NOW for k in px2 for e in ("binance", "bybit", "okx", "hyperliquid")}}, open(paths.state("spot.json"), "w"))
wbal("okx", OKX)
out_e1 = build()
usdt_okx = [l for x in rows(out_e1, "USDT") for l in x.get("locs") or [] if l.get("w") == "OKX"]
chk(abs(coins_usd(out_e1) - (base_e - 800 + 6000)) < 0.02,
    "E1 OKX 담보대출 첫 대사 전 = 총자산에 USDT −800(잔고 + 부채) + 담보 ETH — 원장 음수 −20,000 을 빼지 않음(2차 실측 꼴 A)", [coins_usd(out_e1), base_e - 800 + 6000])
chk(len(usdt_okx) == 1 and abs(float(usdt_okx[0]["qty"]) + 800) < 1e-6, "E1 OKX USDT 보관처 줄 = −800(빌린 몫 · 총자산에서 차감)", usdt_okx)
dbt_e1 = [d for d in out_e1.get("exDebts") or [] if d.get("ex") == "OKX"]
chk(dbt_e1 and abs(sum(float(d["qty"]) for d in dbt_e1) + 20300) < 1e-6, "E1 빌린 돈 줄(exDebts) = −20,300 표시 전용(합계에 또 안 더함)", dbt_e1)
off_e1 = build(off=True)
chk(abs(coins_usd(off_e1) - (base_e - 20000)) < 0.02, "E1 종전(1차 전) = 원장 음수 −20,000 차감(대조)", coins_usd(off_e1))
statefile.atomic_write_json(os.path.join(S, "exf_balances_hyperliquid.json.view"), {"ts": int(time.time()) - 20, "balances": {"USDC": 1000.0, "HYPE": 10.0}})
out_e2 = build()
chk(abs(coins_usd(out_e2) - coins_usd(out_e1) - 1400) < 0.02, "E2 Hyperliquid 현물 첫 대사 전 = USDC 1,000 + HYPE 10 × $40 총자산에(2차 실측 D)",
    [coins_usd(out_e2), coins_usd(out_e1)])
chk("exchange:hyperliquid" in ((out_e2.get("prov") or {}).get("chains") or {}) and "Hyperliquid 거래소" in str((out_e2.get("prov") or {}).get("note")),
    "E2 안내 칸에 Hyperliquid", out_e2.get("prov"))
HLA = "0x" + "2b" * 20
sv = (hl_spot.addresses, hl_spot.load_meta, hl_spot._pre_one)
hl_spot.addresses = lambda cfg: [HLA]
hl_spot.load_meta = lambda *a, **k: None
CALLS = []


def _fb(addr, meta, deadline):
    CALLS.append(addr)
    return {"USDC": Decimal("7"), "HYPE": Decimal("1")}


hl_spot._pre_one = _fb
r1 = hl_spot.prefetch_view({}, poll=600)
vp = os.path.join(S, "exf_balances_hyperliquid.json.view")
statefile.atomic_write_json(vp, {"ts": int(time.time()) - 4000, "balances": {"USDC": 1.0}})
r2 = hl_spot.prefetch_view({}, poll=600)
v2 = json.load(open(vp))
chk(r1 == "skip" and r2.startswith("ok") and v2.get("balances") == {"HYPE": 1.0, "USDC": 7.0} and v2.get("pre") == 1 and CALLS == [HLA],
    "E3 HL 먼저 읽기 = 표시 파일이 한 주기 + 5분 안이면 안 부름 · 낡으면 주소마다 읽어 .view 만", [r1, r2, v2, CALLS])
chk(not os.path.exists(os.path.join(S, "exf_balances_hyperliquid.json.pending")) and not os.path.exists(os.path.join(S, "exf_balances_hyperliquid.json")),
    "E3 대사용 정식·pending 은 안 씀")


def _fb_fail(addr, meta, deadline):
    raise ValueError("합성 실패")


hl_spot._pre_one = _fb_fail
statefile.atomic_write_json(vp, {"ts": int(time.time()) - 4000, "balances": {"USDC": 1.0}})
chk(T.safe(hl_spot.prefetch_view, {}, poll=600).get("_exc", "").startswith("ValueError") and json.load(open(vp))["balances"] == {"USDC": 1.0},
    "E3 주소 실패 = 안 씀(일부 합으로 덜 보이지 않게 · 부르는 쪽이 예외를 삼킴)")
hl_spot.addresses, hl_spot.load_meta, hl_spot._pre_one = sv
T_SNAP = NOW - 900
wbal("bithumb", {"balances": {"KRW": 50000000.0}, "sources": ["spot"]}, ts=T_SNAP)


def bt_krw(f):
    return sum(float(x.get("krw") or 0) for x in f.get("fiats") or [] if x.get("ex") == "빗썸")


k0 = bt_krw(build())
C.conn.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('bithumb','trade','C0000000',1,?,?)",
               (json.dumps({"side": "buy", "quote": "KRW", "base": "AAA", "funds": "30000000", "fee": "0", "fee_ccy": "KRW", "qty": "100000",
                            "ts": (T_SNAP + 600) * 1000}), NOW - 200))
C.conn.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('bithumb','trade','C0000001',1,?,?)",
               (json.dumps({"side": "buy", "quote": "KRW", "base": "AAA", "funds": "1000", "fee": "0", "fee_ccy": "KRW", "qty": "1",
                            "ts": (T_SNAP + 2) * 1000}), NOW - 200))
C.conn.commit()
out_k1 = build()
k1 = bt_krw(out_k1)
chk(abs(k0 - 50000000) < 1 and abs(k1 - (50000000 - 30000000)) < 1,
    "K1 체결 직후 · 잔고 스냅숏 매수 전 → 화면 빗썸 원화 = 스냅숏 − 뒤 체결 원화 ₩30,000,000 = ₩20,000,000(이중 계상 0)", [k0, k1])
f_k1 = [x for x in out_k1.get("fiats") or [] if x.get("ex") == "빗썸"]
chk(f_k1 and not f_k1[0].get("stale"), "K1 나이 표기 = 그 스냅숏 그대로(15분 = 신선)", f_k1)
wbal("bithumb", {"balances": {"KRW": 19990000.0}, "sources": ["spot"]}, ts=NOW - 30)
k2 = bt_krw(build())
chk(abs(k2 - 19990000) < 1, "K2 다음 스냅숏 = 굴림 0(스냅숏 그대로)", k2)
wbal("bithumb", {"balances": {"KRW": 1000.0}, "sources": ["spot"]}, ts=T_SNAP)
chk(bt_krw(build()) == 0, "K3 굴린 값이 음수 = 0 하한(행 없음)")
chk(web.StateBuilder._krw_roll([(100, -5), (106, -7), (200, 3)], 100) == (-4.0, 200.0) and web.StateBuilder._krw_roll(None, 50) == (0.0, 50.0),
    "K4 굴림 = 스냅숏 + 여유(5초) 뒤 증감 합 · 마지막 시각")
C.conn.execute("DELETE FROM raw_ex WHERE exchange='bithumb'")
C.conn.commit()
os.remove(os.path.join(S, "exf_balances_bithumb.json.view"))
act = exprov.actual_of({"balances": {"usdt": "10", "KRW": 5, "BTC": 1}, "debts": {"USDT": -3, "BTC": 0.5}})
chk(act == {"USDT": Decimal(7), "BTC": Decimal(1)}, "B5 잔고 + 부채(음수만) · 원화·달러 제외 = core 대사 actual 과 같음", act)
T.finish()
sys.exit(1 if T.FAILS else 0)
