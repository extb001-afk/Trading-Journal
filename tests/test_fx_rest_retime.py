#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import io
import json
import os
import threading
import time
import urllib.error
from datetime import datetime, timedelta, timezone

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import common
import core
import pricing

assert T.TMP in common.STATE_DIR
core.dm = lambda *a, **k: None
chk = T.chk
KST = timezone(timedelta(hours=9))
MIN = 60_000

GJ = []
MODE = {"slow": 0.0, "fail": None, "fail_n": 0, "hook": None}


def rate(m_ms):
    return 1300.0 + ((m_ms // MIN) % 97) * 0.25


def _bars(to_ms, n, px_of):
    out = []
    for k in range(1, n + 1):
        m = to_ms - k * MIN
        if px_of(m) is not None:
            out.append({"candle_date_time_utc": datetime.fromtimestamp(m / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), "opening_price": px_of(m)})
    return out


def fake_gj(url, timeout=10.0):
    GJ.append((url, threading.current_thread().name))
    h9 = MODE.get("hook")
    if h9:
        MODE["hook"] = None
        h9()
    if MODE["slow"]:
        time.sleep(MODE["slow"])
    if MODE["fail"] is not None and MODE["fail_n"] > 0:
        MODE["fail_n"] -= 1
        f = MODE["fail"]
        if f == "transport":
            raise OSError("가짜: 전송 오류")
        if f == "dict":
            return {"error": {"name": "too_many_requests"}}
        raise urllib.error.HTTPError(url, int(f), "limit", {}, io.BytesIO(b""))
    q = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))
    if "api.upbit.com" in url:
        to = int(datetime.strptime(q["to"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp() * 1000)
        if q["market"] == "KRW-USDT":
            return _bars(to, int(q["count"]), lambda m: rate(m) if m >= pricing.FX_USDT_FIRST_MS else None)
        if q["market"] == "KRW-BTC":
            return _bars(to, int(q["count"]), lambda m: rate(m) * 30000.0)
    if "api.binance.com" in url and "BTCUSDT" in url:
        st, en = int(q["startTime"]), int(q["endTime"])
        return [[m, "30000.0"] for m in range(st - st % MIN, en, MIN)][:int(q["limit"])]
    raise OSError("가짜: 모르는 URL " + url[:80])


fake_gj._tj_test_mock = True
REAL_GJ = pricing._gj
pricing._gj = fake_gj


def calls(thread=None):
    return [u for u, th in GJ if thread is None or th == thread]


def rest_on(px):
    with px.lock:
        px.d["neg_ts"]["_fx"] = int(time.time())


def rest_off(px):
    with px.lock:
        px.d["neg_ts"].pop("_fx", None)


def clear(px, mins):
    with px.lock:
        for m in mins:
            px.d["fx"].pop(str((int(m) // MIN) * MIN), None)


def ep(y, mo, d, h, mi):
    return int(datetime(y, mo, d, h, mi, tzinfo=KST).timestamp()) * 1000


PX = pricing.PxCache(os.path.join(T.TMP, "px_t.json"))
W6 = [ep(2025, 12, 20, 3, 0) + k * 300 * MIN for k in range(6)]
clear(PX, W6)
GJ.clear()
rest_on(PX)
st1 = PX.prefetch_fx(W6, max_calls=40, pace=0)
chk(not GJ and not st1.get("done") and st1.get("calls") == 0, "[1] 쉼 표식 중 = 0콜 · done 아님", (st1, calls()))
for f in ("429", "418", "transport", "dict"):
    rest_off(PX)
    clear(PX, W6)
    GJ.clear()
    MODE.update(fail=f, fail_n=99)
    st2 = PX.prefetch_fx(W6, max_calls=40, pace=0)
    MODE.update(fail=None, fail_n=0)
    with PX.lock:
        neg2 = int(PX.d["neg_ts"].get("_fx") or 0)
    chk(len(GJ) == 1 and neg2 > 0 and not st2.get("done"), f"[2] 실패({f}) = 첫 창에서 그만(남은 5창 안 부름) · 쉼 표식 · done 아님", (st2, len(GJ), neg2))
OLD = [ep(2023, 3, 1, 9, 0) + k * 400 * MIN for k in range(3)]
rest_on(PX)
clear(PX, OLD)
GJ.clear()
st3 = PX.prefetch_fx(OLD, max_calls=40, pace=0)
chk(not GJ and not st3.get("done"), "[3] 교차 환율 구간도 쉼 중 0콜", (st3, calls()))
rest_off(PX)
clear(PX, OLD)
GJ.clear()
MODE.update(fail="transport", fail_n=99)
st3b = PX.prefetch_fx(OLD, max_calls=40, pace=0)
MODE.update(fail=None, fail_n=0)
chk(len(GJ) <= 2 and not st3b.get("done"), "[3] 교차 환율 조회 실패 = 그만(창마다 계속 두드리지 않음) · done 아님", (st3b, calls()))
rest_off(PX)
clear(PX, W6 + OLD)
GJ.clear()
st4 = PX.prefetch_fx(W6 + OLD, max_calls=40, pace=0)
ref = pricing.PxCache(os.path.join(T.TMP, "px_ref.json"))
vals = {m: PX.d["fx"].get(str(m)) for m in W6 + OLD}
want = {m: ref.fx_at(m) for m in W6 + OLD}
chk(st4.get("done") and st4.get("calls") == 6 + 2 * 3 and vals == want and all(vals.values()),
    "[4] 정상 = 창마다 1콜(교차 = 2콜) · 값 = fx_at 단건 값 · done", (st4, vals, want))

rest_off(PX)
clear(PX, W6)
GJ.clear()
SL = []
MODE.update(fail="429", fail_n=1)
pat = getattr(PX, "prefetch_fx_patient", None)
st4b = pat(W6, max_calls=40, deadline=time.time() + 600, sleep=lambda x: (SL.append(x), rest_off(PX))) if pat else {}
MODE.update(fail=None, fail_n=0)
with PX.lock:
    vals4b = [PX.d["fx"].get(str(m)) for m in W6]
chk(st4b.get("done") and all(vals4b) and SL == [PX.FX_NEG_SEC + 1] and st4b.get("calls") == 1 + 6,
    "[4] 재구축 대량 선조회 = 429 → 쉼 61초 뒤 남은 분부터 → 전부 채움(1 + 6콜)", (st4b, SL, len(GJ)))

C = core.Core(json.load(open(os.path.join(T.TMP, "config.json"))))
KM = ep(2025, 12, 22, 10, 0)
C.conn.execute("BEGIN")
aid = C._exf_asset("bithumb", "ZZZ")
C.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event,"
               " classifier_ver) VALUES ('exchange','bithumb:trade','bithumb:kf',0,?,?,'exchange:bithumb','100000000','10.0',NULL,'acq','EXF_BUY',?)",
               (KM // 1000, aid, core.CLASSIFIER_VER))
C.conn.commit()
rest_on(C.px)
GJ.clear()
C._last_krw_fill = 0
C.krw_fill_pass()
kf = C.conn.execute("SELECT cost_krw FROM postings WHERE source_id='bithumb:kf'").fetchone()[0]
chk(not GJ and kf is None and not (C.__dict__.get("_krw_fill_fail") or {}), "[5] 원화 원가 채움 = 쉼 중 0콜 · 1시간 쉼으로 적지 않음",
    (calls(), C.__dict__.get("_krw_fill_fail")))
rest_off(C.px)
C._last_krw_fill = 0
C.krw_fill_pass()
kf = C.conn.execute("SELECT cost_krw FROM postings WHERE source_id='bithumb:kf'").fetchone()[0]
chk(kf == repr(10.0 * rate(KM)), "[5] 쉼 끝 = 채움(종전 식)", kf)

T_OLD = {"r1": ep(2025, 11, 5, 10, 0), "r2": ep(2025, 11, 6, 11, 0), "r3": ep(2025, 11, 9, 12, 0), "u1": ep(2025, 11, 10, 9, 0)}
T_NEW = {"r1": ep(2025, 11, 8, 9, 0), "r2": ep(2025, 11, 6, 11, 0) + 5000, "r3": ep(2025, 11, 30, 23, 50), "u1": ep(2025, 12, 1, 0, 10)}
FILLS = [{"id": "bithumb:r1", "qty": "2", "price": "100", "ts": T_OLD["r1"], "base": "AAA", "quote": "KRW", "side": "buy", "fee": "0.1", "fee_ccy": "KRW"},
         {"id": "bithumb:r2", "qty": "1", "price": "150", "ts": T_OLD["r2"], "base": "AAA", "quote": "KRW", "side": "sell", "fee": "0.075", "fee_ccy": "KRW"},
         {"id": "bithumb:r3", "qty": "3", "price": "100", "ts": T_OLD["r3"], "base": "BBB", "quote": "KRW", "side": "buy", "fee": "0.15", "fee_ccy": "KRW"},
         {"id": "bithumb:u1", "qty": "4", "price": "2.5", "ts": T_OLD["u1"], "base": "CCC", "quote": "USDT", "side": "buy", "fee": "0", "fee_ccy": ""}]
C.conn.execute("BEGIN")
C._consume_exf_fills({"v": 1, "kind": "exf_fills", "exchange": "bithumb", "ts": 1, "fills": FILLS})
C.conn.commit()


def legs(fid):
    return [tuple(r) for r in C.conn.execute(
        "SELECT leg_seq, asset_id, location, qty_base, leg_kind, event, event_ts, cost_usd, cost_krw FROM postings"
        " WHERE source_kind='exchange' AND source_ns='bithumb:trade' AND source_id=? ORDER BY leg_seq", (f"bithumb:{fid}",))]


def positions():
    return sorted(tuple(r) for r in C.conn.execute("SELECT group_id, location, qty_norm FROM positions"))


L0 = {k: legs(k) for k in T_OLD}
P0 = positions()
chk(all(L0[k] and L0[k][0][6] == T_OLD[k] // 1000 and L0[k][0][7] is not None and L0[k][0][8] is not None for k in T_OLD),
    "[전] 옛 시각 기장 · 원가 USD·KRW 있음", L0)
REC = {"v": 1, "kind": "exf_fill_retime", "exchange": "bithumb", "ts": int(time.time()), "src": "test",
       "fills": [{"id": f"bithumb:{k}", "ts_old": T_OLD[k], "ts": T_NEW[k]} for k in ("r2", "r1", "r3", "u1")]}


def apply_rec(rec):
    C.conn.execute("BEGIN")
    t0 = time.time()
    try:
        C._consume_record(rec)
    finally:
        C.conn.commit()
    return time.time() - t0


def queue_idle(timeout=20.0):
    q = C.__dict__.get("_exf_retime_pxq")
    w = getattr(q, "wait_idle", None)
    return bool(w and w(timeout))


def nb_off():
    return getattr(C.px._tl, "nb", None) is None


GJ.clear()
MODE["slow"] = 0.4
dt1 = apply_rec(REC)
main_calls = calls("MainThread")
L1 = {k: legs(k) for k in T_OLD}
chk(not main_calls, "[6] 소비 중 core 스레드 바깥 조회 0", main_calls[:3])
chk(dt1 < 0.3, f"[6] 느린 환율 API(0.4초/콜)에도 바로 끝(걸린 시간 {dt1:.2f}초)", dt1)
chk(nb_off(), "[6] 끝나면 비차단 모드 풀림")
rev1 = [r[0] for r in C.conn.execute("SELECT uuid FROM raw_ex WHERE exchange='bithumb' AND revision=2")]
chk(all(L1[k] == L0[k] for k in ("r1", "r3", "u1")) and positions() == P0 and rev1 == ["bithumb:r2"]
    and [r[6] for r in L1["r2"]] == [T_NEW["r2"] // 1000] * len(L0["r2"]),
    "[7] 첫 적용 = 새 시각 환율이 캐시에 있는 체결(r2 — 같은 분)은 바로 바로잡음 · 없는 체결(r1·r3·u1)은 되돌림(원본 개정 취소 · 레그·포지션 그대로)", (rev1, L1))
chk(all(r[8] is not None for k in T_OLD for r in L1[k] if r[0] != 2), "[8] 원가 KRW 가 NULL 로 바뀐 레그 없음", L1["u1"])
idle = queue_idle()
bg = calls("tj-retime-px")
with C.px.lock:
    have = {k: C.px.d["fx"].get(str((T_NEW[k] // MIN) * MIN)) for k in T_NEW}
chk(idle and all(have.values()) and 0 < len(bg) <= 2 and len(calls()) == len(bg),
    "[7] 배경 스레드가 새 시각 환율을 받음(200분 묶음 — 캐시에 없는 3분 → 2콜) · 다른 스레드 조회 0", (idle, have, len(bg), len(calls())))
MODE["slow"] = 0.0
GJ.clear()
apply_rec(REC)
L2 = {k: legs(k) for k in T_OLD}
fx_new = {k: rate((T_NEW[k] // MIN) * MIN) for k in T_NEW}
gross = {"r1": 200.0, "r2": 150.0, "r3": 300.0, "u1": 10.0}
ok7 = all([r[6] for r in L2[k]] == [T_NEW[k] // 1000] * len(L2[k]) and [r[:6] for r in L2[k]] == [r[:6] for r in L0[k]] for k in T_OLD)
ok7 = ok7 and all(abs(float(L2[k][0][7]) - gross[k] / fx_new[k]) < 1e-9 for k in ("r1", "r2", "r3"))
chk(ok7 and not calls() and positions() == P0, "[7] 다시 적용 = 바로잡음(시각 = 새 시각 · 수량·자산 그대로 · 원가 USD = 새 시각 환율) · 조회 0 · 포지션 불변",
    {k: L2[k][:1] for k in T_OLD})
chk(L2["u1"][0][7] == L0["u1"][0][7] and abs(float(L2["u1"][0][8]) - 10.0 * fx_new["u1"]) < 1e-6 and L2["r1"][0][8] == L0["r1"][0][8],
    "[8] USDT 쿼트 = 원가 USD 그대로 · 원가 KRW = 새 시각 환율 · KRW 쿼트 원화 원가 그대로", (L2["u1"][:1], L0["u1"][:1]))
mk = json.loads(C._meta_get("exf_retime:bithumb") or "{}")
chk(mk.get("n") == 4 and mk.get("undo") == 3, "[7] meta 누적(바로잡음 4 · 되돌림 3 — 첫 적용 분)", mk)

C.conn.execute("BEGIN")
C.conn.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('bithumb','trade','bithumb:e1',1,?,1)",
               (json.dumps(dict(FILLS[0], id="bithumb:e1")),))
C._post_exf_fill("bithumb", dict(FILLS[0], id="bithumb:e1"))
C.conn.commit()
real_post = C._post_exf_fill


def boom(*a, **k):
    raise RuntimeError("가짜 처리 오류")


C._post_exf_fill = boom
exc9 = None
C.conn.execute("BEGIN")
try:
    C._consume_exf_retime({"exchange": "bithumb", "ts": 1, "fills": [{"id": "bithumb:e1", "ts_old": T_OLD["r1"], "ts": T_NEW["r1"] + 7 * 86_400_000}]})
except RuntimeError as e:
    exc9 = e
C.conn.rollback()
C._post_exf_fill = real_post
chk(exc9 is not None and nb_off(), "[9] 처리 중 예외(격리 경로)여도 비차단 모드 풀림", repr(exc9))
mf = (T_NEW["r1"] // MIN) * MIN + 3 * 86_400_000
GJ.clear()
fa = C.px.fx_at(mf)
chk(fa == rate(mf) and calls("MainThread"), "[9] 그 뒤 core 스레드 fx_at = 종전 조회(비차단 아님)", (fa, calls()))

T10 = ep(2025, 12, 10, 9, 0)
T10N = ep(2025, 12, 12, 15, 0)
C.conn.execute("BEGIN")
C._consume_exf_fills({"v": 1, "kind": "exf_fills", "exchange": "bithumb", "ts": 1, "fills": [
    {"id": "bithumb:z1", "qty": "1", "price": "500", "ts": T10, "base": "DDD", "quote": "KRW", "side": "buy", "fee": "0", "fee_ccy": ""}]})
C.conn.commit()
z0 = legs("z1")
REC10 = {"v": 1, "kind": "exf_fill_retime", "exchange": "bithumb", "ts": int(time.time()), "src": "test", "fills": [{"id": "bithumb:z1", "ts_old": T10, "ts": T10N}]}
q0 = C.__dict__.get("_exf_retime_pxq")
if q0 is not None and hasattr(q0, "RETRY_SEC"):
    q0.RETRY_SEC = 0.6
GJ.clear()
MODE.update(fail="429", fail_n=1)
apply_rec(REC10)
t_end = time.time() + 10
seen_rest = False
while time.time() < t_end:
    with C.px.lock:
        if C.px.d["neg_ts"].get("_fx"):
            C.px.d["neg_ts"].pop("_fx", None)
            seen_rest = True
            break
    time.sleep(0.01)
idle10 = queue_idle()
MODE.update(fail=None, fail_n=0)
with C.px.lock:
    got10 = C.px.d["fx"].get(str((T10N // MIN) * MIN))
chk(seen_rest and idle10 and got10 == rate((T10N // MIN) * MIN) and len(calls("tj-retime-px")) == 2 and not calls("MainThread"),
    "[10] 배경 첫 조회 429 = 쉼 표식 · 쉼 뒤 배경이 스스로 다시 받음(2콜) · core 스레드 조회 0", (seen_rest, idle10, got10, calls()))
apply_rec(REC10)
chk([r[6] for r in legs("z1")] == [T10N // 1000] * len(z0) and abs(float(legs("z1")[0][7]) - 500.0 / rate((T10N // MIN) * MIN)) < 1e-9,
    "[10] 다시 적용 = 바로잡음", legs("z1"))

STARTS = []


class _Resp(io.BytesIO):
    status = 200
    headers = {}

    def getheader(self, k, d=None):
        return d


def fake_urlopen(req, timeout=10.0, *a, **k):
    url = getattr(req, "full_url", req)
    STARTS.append(time.monotonic())
    return _Resp(json.dumps(fake_gj(url)).encode())


fake_urlopen._tj_test_mock = True
pricing._gj = REAL_GJ
real_uo = __import__("urllib.request").request.urlopen
__import__("urllib.request").request.urlopen = fake_urlopen
PX11 = pricing.PxCache(os.path.join(T.TMP, "px_11.json"))
A11 = [ep(2025, 12, 1, 3, 0) + k * 300 * MIN for k in range(10)]
B11 = [ep(2026, 1, 5, 3, 0) + k * 300 * MIN for k in range(10)]
rest_off(PX11)
GJ.clear()
ta = threading.Thread(target=lambda: PX11.prefetch_fx(A11, max_calls=40, pace=0.15), name="t11-core")
tb = threading.Thread(target=lambda: PX11.fx_warm(B11), name="t11-warm")
ta.start()
tb.start()
ta.join(30)
tb.join(30)
__import__("urllib.request").request.urlopen = real_uo
pricing._gj = fake_gj
st11 = sorted(STARTS)
peak11 = max((sum(1 for t in st11 if s0 <= t < s0 + 1.0) for s0 in st11), default=0)
gap11 = min((b9 - a9 for a9, b9 in zip(st11, st11[1:])), default=1.0)
with PX11.lock:
    ok11 = all(PX11.d["fx"].get(str(m)) == rate(m) for m in A11 + B11)
chk(len(st11) == 20 and ok11 and peak11 <= 8,
    "[11] core 선조회 + 배경 fx_warm 동시 = 업비트 캔들 1초 안 8회 이하(게이트 0.15초 간격) · 값 그대로", (len(st11), peak11, round(gap11, 3), ok11))

PX12 = pricing.PxCache(os.path.join(T.TMP, "px_12.json"))
G12 = [ep(2026, 2, 1, 3, 0) + k * 300 * MIN for k in range(3)]
GJ.clear()
MODE["hook"] = lambda: rest_on(PX12)
n12 = PX12.fx_warm(G12)
with PX12.lock:
    neg12 = PX12.d["neg_ts"].get("_fx")
chk(len(GJ) == 1 and n12 == 1 and neg12, "[12] fx_warm = 도는 중 다른 스레드가 찍은 쉼 표식이면 남은 묶음 안 부름(1콜 · 첫 묶음 값만)", (len(GJ), n12, neg12))
rest_off(PX12)
GJ.clear()
MODE["hook"] = lambda: rest_on(PX12)
st12 = PX12.prefetch_fx([ep(2026, 2, 3, 3, 0) + k * 300 * MIN for k in range(3)], max_calls=40, pace=0)
chk(len(GJ) == 1 and not st12.get("done"), "[12] prefetch_fx 도 같은 규칙(창마다 조회 직전 확인)", (len(GJ), st12))

PX13 = pricing.PxCache(os.path.join(T.TMP, "px_13.json"))
m13 = ep(2026, 2, 5, 3, 0)
rest_off(PX13)
GJ.clear()
MODE["hook"] = lambda: rest_on(PX13)
v13 = PX13.fx_at(m13)
with PX13.lock:
    neg13 = PX13.d["neg_ts"].get("_fx")
chk(v13 == rate(m13) and neg13, "[13] fx_at 성공 = 값 저장 · 조회 도중 다른 스레드가 찍은 쉼 표식은 그대로", (v13, neg13))
with PX13.lock:
    PX13.d["neg_ts"]["_fx"] = int(time.time()) - 120
v13b = PX13.fx_at(m13 + MIN)
with PX13.lock:
    neg13b = PX13.d["neg_ts"].get("_fx")
chk(v13b == rate(m13 + MIN) and neg13b is None, "[13] 조회 전에 보던 지난 표식은 성공 때 지움(종전 정리 그대로)", (v13b, neg13b))
T.finish()
