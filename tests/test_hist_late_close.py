#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _ingest
from _ingest import W, SOLW, Reader

import copy
import inspect
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import common
import core
import histcurve
import web
import xparts

chk = T.chk
core.dm = lambda *a, **k: None
S = common.STATE_DIR
open(os.path.join(S, "backfill_done"), "w").write("1")
KST = timezone(timedelta(hours=9))
FX = 1400.0
E18 = 10 ** 18
X = "0x" + "b7" * 20
TODAY = datetime(2026, 10, 10, tzinfo=KST)
NOW = datetime(2026, 10, 10, 12, 0, 0, tzinfo=KST).timestamp()
D0 = int(datetime(2026, 10, 10, tzinfo=KST).timestamp())
Y = "2026-10-09"


def E(m, d, h=23, mi=59, s=59):
    return datetime(2026, m, d, h, mi, s, tzinfo=KST).timestamp()


def days_back(n):
    return (TODAY - timedelta(days=n)).strftime("%Y-%m-%d")


class FakeSpot:
    rate = FX
    fx_basis = FX

    def price(self, sym):
        return None


class FakePx:
    def fx_at(self, ms):
        return FX

    def candle_usd(self, sym, ms):
        return None

    def flush(self):
        pass


XV = {"v": xparts.GEN, "p": {"ku": [0.0, "snap"], "kb": [0.0, "snap"], "ub": [{}, "snap"], "rest": [0.0, "snap"]}, "fx": FX, "how": "live"}


def unit_builder(load=False):
    if not load:
        for p9 in (web.DAILY_PATH, web.DAILY_PX_PATH, os.path.join(S, common.HIST_DIRTY)):
            if os.path.exists(p9):
                os.remove(p9)
    b = object.__new__(web.StateBuilder)
    b.daily = common.read_json(web.DAILY_PATH, None) if load else {"_v": web.DAILY_V, "_risk_rev": ""}
    b.daily_px = common.read_json(web.DAILY_PX_PATH, None) if load else {"_v": 1}
    b._daily_seed = {}
    b._upbit_krw_tl = None
    b.spot = FakeSpot()
    b.px = FakePx()
    return b


def mkx(now_ts):
    return {"ub": 0.0, "fiat": 0.0, "lp": 0.0, "ubs": {}, "ub_tl": {}, "krw_up": 0.0, "krw_other": 0.0, "rate": FX, "krw_up_tl": None,
            "xsrc": {"now": {"ts": now_ts, "ku": 0.0, "kb": 0.0, "ub": {}, "rest": 0.0},
                     "base": {"ku": [0.0, now_ts], "kb": [0.0, now_ts]}, "tl": {"ku": [], "kb": []}, "first": {}}}


def setup(b, tkn=False, pin_y=False):
    for i9 in range(1, 46):
        k9 = days_back(i9)
        b.daily_px[k9] = {"p": {"2": 2.0} if (tkn and (k9 != Y or pin_y)) else {}, "k": {"2": "live"} if (tkn and (k9 != Y or pin_y)) else {},
                          "xv": copy.deepcopy(XV)}
        if k9 == Y:
            continue
        g9 = {"1": 100000.0}
        if tkn:
            g9["2"] = 2000.0
        b.daily[k9] = {"val": float(sum(g9.values())), "usdt": FX, "kimp": None, "g": g9, "x": 0.0, "src": "calc", "st": "1", "xraw": 0.0}
    json.dump(b.daily, open(web.DAILY_PATH, "w"))


def snap(ts, usdc=100000.0, tkn=None, hq=None, pw=None, lg=None):
    g9 = {"1": float(usdc)}
    p9 = {}
    if tkn:
        g9["2"] = float(tkn[0] * tkn[1])
        p9["2"] = float(tkn[1])
    sn9 = {"date": Y, "ts": float(ts), "val": float(sum(g9.values())), "usdt": FX, "kimp": None, "g": g9, "x": 0.0, "defer": False, "p": p9,
           "xv": {"v": 1, "p": {"kb": [0.0, "snap"], "rest": [0.0, "snap"]}, "fx": FX, "ts": int(ts)}}
    if hq:
        sn9["hq"] = int(hq)
    if pw is not None:
        sn9["pw"] = int(pw)
    if lg is not None:
        sn9["lg"] = lg
    return sn9


def put_snap(b, sn9):
    b.daily["_live_ok"] = dict(sn9)
    b.daily["_live"] = dict(sn9)
    json.dump(b.daily, open(web.DAILY_PATH, "w"))


def mkG(moves, tkn_moves=None):
    G = {1: {"gid": 1, "sym": "USDC", "is_stable": True, "qty_timeline": [(int(E(7, 1)), Decimal(100000))] + [(int(t9), Decimal(str(q9))) for t9, q9 in moves]}}
    hq = {1: Decimal(100000) + sum(Decimal(str(q9)) for _t, q9 in moves)}
    if tkn_moves is not None:
        G[2] = {"gid": 2, "sym": "TKN", "is_stable": False, "qty_timeline": [(int(E(7, 1)), Decimal(1000))] + [(int(t9), Decimal(str(q9))) for t9, q9 in tkn_moves]}
        hq[2] = Decimal(1000) + sum(Decimal(str(q9)) for _t, q9 in tkn_moves)
    return G, hq


HAS_PW = "late_after" in inspect.signature(web.StateBuilder._daily_series).parameters


def series(b, G, hq, marks, now_ts=NOW, tkn_now=2.0, pw_fn=None, led_gen=None):
    kw = {"hist_late": copy.deepcopy(marks)}
    if HAS_PW:
        kw["late_after"] = pw_fn
        kw["led_pw"] = common.hist_late_pw(c.conn)
    if led_gen is not None:
        kw["led_gen"] = led_gen
    out = b._daily_series(G, TODAY, {}, {2: tkn_now}, ca_gids={2}, ex_gids=set(), skip_gids=set(), pending_gids=set(),
                          hold_qty=dict(hq), extra=copy.deepcopy(mkx(now_ts)), extra_ok=True, now_ts=now_ts, **kw)
    return {r["date"]: r["val"] for r in out}


def close(a, b9, tol=0.01):
    return a is not None and b9 is not None and abs(float(a) - float(b9)) < tol


c = core.Core(common.load_config())
c.conn.commit()
_n = [0]


def reset_ledger():
    c.conn.execute("BEGIN")
    for t9 in ("postings", "tx_class", "transfers", "positions", "raw_txs"):
        c.conn.execute(f"DELETE FROM {t9}")
    c.conn.execute("DELETE FROM meta WHERE k IN (?, ?)", (common.HIST_LATE_K, common.HIST_LATE_PID_K))
    c.conn.commit()
    if hasattr(c, "_hist_late_fence"):
        c._hist_late_fence()
    else:
        c._hist_late_scan(now=E(10, 1, 12, 0, 0))


def post(ts, value=E18):
    _n[0] += 1
    hx = "0x" + ("%064x" % (7000 + _n[0]))
    s9 = {"tx": {"hash": hx, "from": X, "to": W, "value": str(value), "fee": {"value": "0"}, "status": "ok", "raw_input": "0x",
                 "timestamp": int(ts), "block_number": 1000 + _n[0], "block_hash": "0x" + "d" * 64}, "token_transfers": [], "internal": []}
    c._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": hx, "wallets": [W], "snapshot": s9, "ts": 1}]), 0, 0)
    return hx


def pw_now():
    return int(c.conn.execute("SELECT MAX(posting_id) FROM postings").fetchone()[0] or 0)


def pw_fn(pw9, t9):
    return common.hist_late_after(c.conn, pw9, t9) if hasattr(common, "hist_late_after") else False


def marks():
    return common.hist_late_read(c.conn)


def hqmax():
    return max((m[0] for m in marks()), default=0)


MOVES = {
    "입금": (50000, None, 50000, 150000.0, 0.0),
    "출금": (-30000, None, -30000, 70000.0, 0.0),
    "매매": (1500, -500, 0, 102500.0, 500.0),
}
for mv, (du, dt, fl, want, gain) in MOVES.items():
    for scr, t_sn, t_ev in (("활성 화면", E(10, 9, 23, 59, 20), E(10, 9, 23, 59, 50)), ("화면 15분 쉼", E(10, 9, 23, 45, 30), E(10, 9, 23, 52, 0))):
        for with_pw in ((True, False) if mv == "입금" else (True,)):
            lab = f"{mv}·{scr}" + ("" if with_pw else "·수위 없는 옛 형식 스냅숏(B10 표식만)")
            tk = dt is not None
            reset_ledger()
            b = unit_builder()
            setup(b, tkn=tk)
            put_snap(b, snap(t_sn, tkn=(1000, 2.0) if tk else None, hq=hqmax(), pw=pw_now() if with_pw else None))
            post(t_ev)
            r_a = c._hist_late_scan(now=t_ev + 5)
            r_b = c._hist_late_scan(now=D0 + 30)
            G, hq = mkG([(t_ev, du)], tkn_moves=[(t_ev, dt)] if tk else None)
            v1 = series(b, G, hq, marks(), pw_fn=pw_fn)
            e1 = b.daily.get(Y) or {}
            pn = {k9: round(v1[k9] - v1[p9] - (fl if k9 == "10-09" else 0), 2) for p9, k9 in (("10-08", "10-09"), ("10-09", "10-10"))}
            chk(close(v1.get("10-09"), want) and close(v1.get("10-10"), want) and e1.get("src") != "live" and r_b is None
                and abs(pn["10-09"] - gain) < 0.01 and abs(pn["10-10"]) < 0.01,
                f"C1 {lab}: 어제 마감 = {want:,.0f}(마감 전 스냅숏 값 아님) · 손익(값 변화 − 순유입) 10/9 = 실제 {gain:,.0f} · 10/10 = 0(−X/+X 쌍 없음) · 자정 뒤 스캔 표식 없음",
                (v1.get("10-08"), v1.get("10-09"), v1.get("10-10"), e1.get("src"), pn, r_a, r_b, marks()))
            b.daily[Y]["val"] = want + 1
            json.dump(b.daily, open(web.DAILY_PATH, "w"))
            v2 = series(b, G, hq, marks(), now_ts=NOW + 60, pw_fn=pw_fn)
            b3 = unit_builder(load=True)
            v3 = series(b3, G, hq, marks(), now_ts=NOW + 120, pw_fn=pw_fn)
            chk(close(v2.get("10-09"), want + 1) and close(v3.get("10-09"), want + 1), f"C1 {lab}: 두 번째 빌드·재시작 = 손 안 댐(반복 무효화 없음)",
                (v2.get("10-09"), v3.get("10-09")))

reset_ledger()
b = unit_builder()
setup(b)
put_snap(b, snap(E(10, 9, 23, 59, 20), pw=pw_now()))
post(E(10, 9, 23, 59, 50))
c.conn.execute("INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (common.HIST_LATE_PID_K, str(pw_now())))
c.conn.commit()
G, hq = mkG([(E(10, 9, 23, 59, 50), 50000)])
v1 = series(b, G, hq, marks(), pw_fn=pw_fn)
chk(close(v1.get("10-09"), 150000) and marks() == [], "C1 표식이 없어도 스냅숏 수위(pw) 뒤 그날 행 = 마감 재료 아님 → 150,000", (v1.get("10-09"), marks()))

reset_ledger()
b = unit_builder()
setup(b, tkn=True)
put_snap(b, snap(E(10, 9, 23, 59, 20), tkn=(1000, 2.0), hq=hqmax(), pw=pw_now()))
post(E(10, 9, 23, 59, 50))
c._hist_late_scan(now=E(10, 9, 23, 59, 55))
G, hq = mkG([(E(10, 9, 23, 59, 50), 1500)], tkn_moves=[(E(10, 9, 23, 59, 50), -500)])
v2t = series(b, G, hq, marks(), tkn_now=5.0, pw_fn=pw_fn)
chk(close(v2t.get("10-09"), 102500), "C2 매매: 23:59:50 TKN 500 매도(+1,500 USDC) = 101,500 + 500 × 마감가 $2 = 102,500(스냅숏 102,000 아님 · 지금 $5 아님)",
    v2t.get("10-09"))

reset_ledger()
b = unit_builder()
setup(b)
post(E(10, 9, 23, 30, 0))
r3 = c._hist_late_scan(now=E(10, 9, 23, 30, 5))
put_snap(b, snap(E(10, 9, 23, 50, 0), usdc=150000.0, hq=hqmax(), pw=pw_now()))
G, hq = mkG([(E(10, 9, 23, 30, 0), 50000)])
v3 = series(b, G, hq, marks(), pw_fn=pw_fn)
chk(r3 is None and (b.daily.get(Y) or {}).get("src") == "live" and close(v3.get("10-09"), 150000),
    "C3 스냅숏이 이미 본 행 = 종전대로 실시간 마감(live) — 표식·수위 거르기 없음", (r3, b.daily.get(Y)))
reset_ledger()
b = unit_builder()
setup(b)
b.daily[Y] = {"val": 100000.0, "usdt": FX, "kimp": None, "g": {"1": 100000.0}, "x": 0.0, "src": "calc", "st": "1", "xraw": 0.0}
json.dump(b.daily, open(web.DAILY_PATH, "w"))
post(E(10, 10, 23, 55, 0))
r3b = c._hist_late_scan(now=E(10, 10, 23, 55, 5))
G, hq = mkG([])
v3b = series(b, G, hq, marks(), now_ts=E(10, 10, 23, 56, 0) + 400, pw_fn=pw_fn)
chk(r3b == "2026-10-10" and close(v3b.get("10-09"), 100000) and "hq" not in (b.daily.get(Y) or {}),
    "C3 오늘 날짜 표식(마감 직전 16분) = 이미 굳은 지난날 안 건드림", (r3b, v3b.get("10-09"), b.daily.get(Y)))

reset_ledger()
b = unit_builder()
setup(b)
pw0 = pw_now()
post(E(10, 9, 23, 40, 0))
r4 = c._hist_late_scan(now=E(10, 9, 23, 40, 5))
put_snap(b, snap(E(10, 9, 23, 46, 0), hq=hqmax(), pw=pw0))
G, hq = mkG([(E(10, 9, 23, 40, 0), 50000)])
v4 = series(b, G, hq, marks(), pw_fn=pw_fn)
chk(r4 is None and close(v4.get("10-09"), 150000), "C4 표식 창 밖 기장인데 스냅숏 수량에 없음 = 수위(pw)로 거름 → 150,000(종전·표식만: 100,000)", (r4, v4.get("10-09")))

reset_ledger()
b = unit_builder()
setup(b, tkn=True)
put_snap(b, snap(E(10, 9, 23, 58, 0), tkn=(1000, 2.0), hq=hqmax(), pw=pw_now()))
post(E(10, 9, 23, 50, 0))
c._hist_late_scan(now=D0 + 300)
G, hq = mkG([(E(10, 9, 23, 50, 0), 50000)], tkn_moves=[])
v5 = series(b, G, hq, marks(), tkn_now=5.0, pw_fn=pw_fn)
px5 = (b.daily_px.get(Y) or {})
chk(close(v5.get("10-09"), 152000) and (px5.get("p") or {}).get("2") == 2.0 and (px5.get("k") or {}).get("2") == "live",
    "C5 늦은 행으로 스냅숏을 버려도 그날 마감가 고정: TKN $2 → 152,000(종전 155,000 — 지금 $5 근사)", (v5.get("10-09"), px5))
reset_ledger()
b = unit_builder()
setup(b, tkn=True)
put_snap(b, snap(E(10, 9, 23, 58, 0), tkn=(1000, 2.0), hq=hqmax(), pw=pw_now(), lg=111))
post(E(10, 9, 23, 50, 0))
c._hist_late_scan(now=D0 + 300)
v5g = series(b, G, hq, marks(), tkn_now=5.0, pw_fn=pw_fn, led_gen=222)
chk(close(v5g.get("10-09"), 155000) and (b.daily_px.get(Y) or {}).get("k", {}).get("2") != "live",
    "C5 원장 세대가 바뀐 스냅숏(gen) = 가격 고정 안 함(그룹 id 가 달라질 수 있음 — 종전 규칙)", (v5g.get("10-09"), b.daily_px.get(Y)))

reset_ledger()
b = unit_builder()
setup(b)
b.daily_px.pop(Y, None)
sn5x = snap(E(10, 9, 23, 59, 20), hq=hqmax(), pw=pw_now())
sn5x.update(x=5000.0, val=105000.0, xv={"v": 1, "p": {"kb": [0.0, "snap"], "rest": [5000.0, "snap"]}, "fx": FX, "ts": int(E(10, 9, 23, 59, 20))})
put_snap(b, sn5x)
post(E(10, 9, 23, 59, 50))
c._hist_late_scan(now=E(10, 9, 23, 59, 55))
G, hq = mkG([(E(10, 9, 23, 59, 50), 50000)])
v5x = series(b, G, hq, marks(), pw_fn=pw_fn)
chk(close(v5x.get("10-09"), 155000) and (b.daily.get(Y) or {}).get("src") != "live",
    "C5 버린 스냅숏의 원장 밖 금액(LP 5,000 — 그 마감 관측)도 그대로 + 원장 수량만 다시 = 155,000", (v5x.get("10-09"), b.daily.get(Y)))

reset_ledger()
post(D0 - 120)
r6 = c._hist_late_scan(now=D0 - 20)
chk(r6 == Y and marks()[-1][1] == Y, "C6 자정 2분 전 행을 자정 20초 전에 스캔 = 그날(오늘) 날짜 표식", (r6, marks()))
post(D0 - 2000)
r6b = c._hist_late_scan(now=D0 - 1990)
chk(r6b is None and len(marks()) == 1, "C6 자정 33분 전 행·스캔 = 표식 없음(마감 창 전 — 그 뒤 스냅숏이 본다)", (r6b, marks()))
post(D0 - 100)
r6c = c._hist_late_scan(now=D0 + 30)
chk(r6c == Y, "C6 자정 뒤 스캔 = 종전대로 지난날 표식", r6c)
chk(getattr(common, "HIST_LATE_CLOSE_S", 0) >= web.DAILY_LIVE_WIN + 60, "C6 마감 직전 표식 창 ≥ 웹 마감 창(DAILY_LIVE_WIN) + 60초", (getattr(common, "HIST_LATE_CLOSE_S", None), web.DAILY_LIVE_WIN))

has_f = hasattr(core.Core, "_hist_late_fence")
chk(has_f, "C7 커서 울타리(_hist_late_fence) 있음", "없음")
if has_f:
    reset_ledger()
    post(E(10, 1, 12, 0, 0))
    post(E(10, 2, 12, 0, 0))
    c.conn.execute("UPDATE meta SET v='1' WHERE k=?", (common.HIST_LATE_PID_K,))
    c.conn.commit()
    k7 = c._hist_late_fence()
    chk(k7 == "keep" and c._meta_get(common.HIST_LATE_PID_K) == "1", "C7 유효한 커서 = 그대로(재시작 · 더 최신 울타리를 MAX 로 덮지 않음)", (k7, c._meta_get(common.HIST_LATE_PID_K)))
    for bad in (None, "abc", "-5"):
        if bad is None:
            c.conn.execute("DELETE FROM meta WHERE k=?", (common.HIST_LATE_PID_K,))
        else:
            c.conn.execute("UPDATE meta SET v=? WHERE k=?", (bad, common.HIST_LATE_PID_K))
        c.conn.commit()
        k7b = c._hist_late_fence()
        chk(k7b == "init" and int(c._meta_get(common.HIST_LATE_PID_K)) == pw_now(), f"C7 커서 {bad!r} = 지금 MAX 로 초기화", (k7b, c._meta_get(common.HIST_LATE_PID_K)))
    c2 = core.Core(common.load_config())
    c2.HL_FENCE_SLEEP = 0
    drained = []
    c2._drain_stream = lambda *a, **k: drained.append(1) or (1, 0, 0)

    def boom():
        raise sqlite3.OperationalError("database is locked")
    c2._hist_late_fence = boom
    try:
        c2.run()
        ex7 = None
    except SystemExit as e:
        ex7 = str(e)
    chk(ex7 is not None and not drained, "C7 울타리가 끝내 실패 = 수집 소비를 시작하지 않고 멈춤(울타리 없이 넘어가면 그 주기 늦은 행이 지나감)", (ex7, drained))
    c2.conn.close()

import time as _time
RN = int(_time.time())


def kiso(ts):
    return datetime.fromtimestamp(int(ts), KST).strftime("%Y-%m-%d")


reset_ledger()
T8 = RN - 20 * 86400
h8 = post(T8)
c._hist_late_scan()
mk8 = list(marks())
c.conn.execute("BEGIN")
saved = set(c.my_wallets.get("eth") or ())
c.my_wallets["eth"] = set()
c._rederive_tx("eth", h8)
c.my_wallets["eth"] = saved
c.conn.commit()
n8 = c.conn.execute("SELECT COUNT(*) FROM postings WHERE source_id=?", (h8,)).fetchone()[0]
mk8b = marks()
chk(n8 == 0 and mk8b != mk8 and min(m[1] for m in mk8b) == kiso(T8) and max(m[0] for m in mk8b) > max([m[0] for m in mk8] or [0]),
    "C8 다시 기장 레그 0개 = 지운 행 시각(20일 전)부터 표식(새 행이 없어 스캔이 못 봄)", (n8, mk8, mk8b))
T8b = RN - 18 * 86400
h8b = post(T8b)
c._hist_late_scan()
mk8c = list(marks())
c.conn.execute("BEGIN")
c._rederive_tx("eth", h8b)
c.conn.commit()
chk(marks() == mk8c, "C8 보통 다시 기장(같은 시각 레그) = 직접 표식 없음(스캔이 새 id 로 봄)", (mk8c, marks()))
r8s = c._hist_late_scan()
chk(r8s == kiso(T8b), "C8 그 다시 기장 행 = 다음 스캔이 그 날 표식", (r8s, kiso(T8b)))
ACCT = "Stk" + "9" * 41
rec_o = {"stake_open": {"acct": ACCT, "wallet": SOLW, "lamports": 5 * 10 ** 9},
         "deltas": [{"asset": "native", "delta": str(5 * 10 ** 9), "owner": f"{SOLW}:stake:{ACCT}"}]}
TO = RN - 40 * 86400
c.conn.execute("BEGIN")
c._post_stake_open(rec_o, int(TO))
c.conn.commit()
_time.sleep(0)
c._hist_late_scan()
mk8d = list(marks())
c.conn.execute("BEGIN")
c._post_stake_open({"stake_open": dict(rec_o["stake_open"], reopen=True, lamports=0), "deltas": []}, int(RN - 60 * 86400))
c.conn.commit()
n8o = c.conn.execute("SELECT COUNT(*) FROM postings WHERE source_kind='opening' AND source_id=?", ("recon:sol:stake:" + ACCT,)).fetchone()[0]
chk(n8o == 0 and max(m[0] for m in marks()) > max(m[0] for m in mk8d) and min(m[1] for m in marks()) == kiso(TO),
    "C8 스테이크 기초잔고 재개 0 = 옛 기초잔고 시각(40일 전)부터 표식", (n8o, mk8d, marks()))

hc = object.__new__(histcurve.HistCurve)
hc.px = {"specs": {}}
hc.st = {}
hc.fx = lambda iso: FX
hc._clean = lambda sp, specs: {}
hc._x_rec = lambda kit, iso, qf, old=None, qcache=None: {"x": 0.0, "xc": 0.0, "cut": 0.0, "p": {}, "fx": FX}
kit9 = {"groups": {1: {"sym": "USDC", "st": True}, 2: {"sym": "ETH", "maj": True, "lp": 2000.0}, 3: {"sym": "BTC", "maj": True, "lp": 50000.0}}}
out9 = hc._compute(kit9, ["2026-01-05"], {1: {"2026-01-05": 100000.0}, 2: {"2026-01-05": 1.0}, 3: {"2026-01-05": -0.04}})
cov9 = out9["2026-01-05"]["cov"]
chk(close(cov9[1], 4000.0) and out9["2026-01-05"]["row"][0] == 100000.0, "C9 근사 몫 = |+1 ETH × 2,000| + |−0.04 BTC × 50,000| = 4,000(종전 0 — 부채가 깎음) · 값 무변", (cov9, out9["2026-01-05"]["row"]))
c.conn.close()
T.finish()
