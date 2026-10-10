#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import contextlib
import importlib.util
import io
import json
import os
import urllib.error
from datetime import datetime, timedelta, timezone
from decimal import Decimal

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import common
import core
import pricing
import ex_foreign as XF

assert T.TMP in common.STATE_DIR
core.dm = lambda *a, **k: None
chk = T.chk
KST = timezone(timedelta(hours=9))


def _load(name, rel):
    p = os.path.join(T.ROOT, *rel.split("/"))
    if not os.path.exists(p):
        return None
    spec = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


tool = _load("bithumb_filltime_1010", "tools/bithumb_filltime_1010.py")
rb2 = _load("rb2_bthfill", "tools/rebuild2.py")
chk(tool is not None, "[0] 도구 tools/bithumb_filltime_1010.py 있음")
chk(hasattr(core.Core, "_consume_exf_retime"), "[0] core 처리기 _consume_exf_retime 있음")
chk(rb2 is not None and hasattr(rb2, "exf_trade_rows"), "[0] rebuild2.exf_trade_rows(체결 원본 최신 revision) 있음")
chk(hasattr(pricing.PxCache, "fx_warm"), "[0] 환율 미리 받기 PxCache.fx_warm 있음")
if tool is None or not hasattr(core.Core, "_consume_exf_retime") or not hasattr(rb2, "exf_trade_rows"):
    T.finish()

GJ = []
FAIL_MIN = set()


def rate(m_ms):
    return 1300.0 + ((m_ms // 60000) % 97) * 0.25


def fake_gj(url, timeout=10.0):
    GJ.append(url)
    assert "market=KRW-USDT" in url, url
    q = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))
    to = int(datetime.strptime(q["to"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp() * 1000)
    n = int(q["count"])
    out = []
    for k in range(1, n + 1):
        m = to - k * 60000
        if m in FAIL_MIN:
            raise OSError("가짜: 환율 조회 실패")
        out.append({"candle_date_time_utc": datetime.fromtimestamp(m / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), "opening_price": rate(m)})
    return out


pricing._gj = fake_gj


def kiso(y, mo, d, h, mi, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=KST).strftime("%Y-%m-%dT%H:%M:%S+09:00")


def ep(s):
    return int(datetime.fromisoformat(s).timestamp())


def order(u, side, ot, market, created, ev, funds, fee, trades=None, state="done"):
    o = {"uuid": u, "side": side, "ord_type": ot, "price": str(Decimal(funds) / Decimal(ev)), "state": state, "market": market,
         "created_at": created, "volume": ev, "remaining_volume": "0", "executed_volume": ev, "executed_funds": funds, "paid_fee": fee}
    if trades is not None:
        o["trades"] = [{"created_at": t, "volume": v, "funds": f} for t, v, f in trades]
    return o


C1 = kiso(2025, 11, 5, 10, 0)
ROWS = {
    "b1": order("b1", "bid", "limit", "KRW-AAA", C1, "2", "200", "0.1"),
    "b2": order("b2", "ask", "limit", "KRW-AAA", kiso(2025, 11, 6, 11, 0), "1", "150", "0.075"),
    "b3": order("b3", "ask", "market", "KRW-AAA", kiso(2025, 11, 9, 12, 0), "1", "120", "0.06"),
    "b4": order("b4", "bid", "limit", "KRW-BBB", kiso(2025, 11, 10, 9, 0), "1", "50", "0.025"),
    "b5": order("b5", "bid", "limit", "KRW-BBB", kiso(2025, 11, 11, 9, 0), "1", "60", "0.03"),
    "b6": order("b6", "bid", "limit", "KRW-BBB", kiso(2025, 11, 12, 9, 0), "1", "70", "0.035"),
    "b7": order("b7", "bid", "limit", "KRW-AAA", kiso(2025, 11, 30, 23, 50), "3", "300", "0.15"),
    "b8": order("b8", "ask", "limit", "KRW-BBB", kiso(2025, 12, 2, 9, 0), "2", "400", "0.2"),
    "b9": order("b9", "bid", "limit", "KRW-BBB", kiso(2025, 12, 3, 9, 0), "1", "80", "0.04"),
}
T1A, T1B = kiso(2025, 11, 7, 15, 30), kiso(2025, 11, 8, 9, 0)
T2 = kiso(2025, 11, 6, 11, 0, 5)
T6 = kiso(2025, 11, 13, 10, 0)
T7 = kiso(2025, 12, 1, 0, 10)
T8 = kiso(2025, 12, 4, 10, 0)
RESP = {
    "b1": dict(ROWS["b1"], trades=[{"created_at": T1A, "volume": "1", "funds": "100"}, {"created_at": T1B, "volume": "1", "funds": "100"}]),
    "b2": dict(ROWS["b2"], trades=[{"created_at": T2, "volume": "1", "funds": "150"}]),
    "b3": dict(ROWS["b3"], trades=[{"created_at": kiso(2025, 11, 9, 12, 0, 1), "volume": "1", "funds": "120"}]),
    "b5": dict(ROWS["b5"], trades=[{"created_at": kiso(2025, 11, 12, 9, 0), "volume": "0.5", "funds": "30"}]),
    "b6": dict(ROWS["b6"], trades=[{"created_at": T6, "volume": "1", "funds": "70"}]),
    "b7": dict(ROWS["b7"], trades=[{"created_at": T7, "volume": "3", "funds": "300"}]),
    "b8": dict(ROWS["b8"], trades=[{"created_at": T8, "volume": "2", "funds": "400"}]),
    "b9": dict(ROWS["b9"], created_at="2025-12-03T09:00:00", trades=[{"created_at": "2025-12-05T09:00:00", "volume": "1", "funds": "80"}]),
}

C = core.Core(json.load(open(os.path.join(T.TMP, "config.json"))))
fills = []
for u, r in ROWS.items():
    ts9 = ep(T6) * 1000 if u == "b6" else XF._bithumb_row_ts(r, None) * 1000
    fills.append(XF._bithumb_fill(r, ts9))
C.conn.execute("BEGIN")
C._consume_exf_fills({"v": 1, "kind": "exf_fills", "exchange": "bithumb", "ts": 1, "fills": fills})
aaa = C._exf_asset("bithumb", "AAA")
BTS = ep(kiso(2025, 11, 6, 12, 0))
C.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event,"
               " classifier_ver) VALUES ('exchange','bithumb:recon',?,0,?,?,'exchange:bithumb','0',NULL,NULL,'opening','EXF_ADJUST',?)",
               (f"exfrecon:AAA:{BTS}", BTS, aaa, core.CLASSIFIER_VER))
C.conn.commit()


def legs(fid):
    return [tuple(r) for r in C.conn.execute(
        "SELECT leg_seq, asset_id, location, qty_base, leg_kind, event, event_ts, cost_usd, cost_krw FROM postings"
        " WHERE source_kind='exchange' AND source_ns='bithumb:trade' AND source_id=? ORDER BY leg_seq", (fid,))]


def positions():
    return sorted(tuple(r) for r in C.conn.execute("SELECT group_id, location, qty_norm FROM positions"))


IDS = {u: f"bithumb:{u}" for u in ROWS}
L0 = {u: legs(IDS[u]) for u in ROWS}
P0 = positions()
chk(L0["b1"][0][6] == ep(C1) and L0["b6"][0][6] == ep(T6), "[전] 지정가 b1 = 생성 시각 기장(재현) · b6 = 이미 체결 시각", (L0["b1"][:1], L0["b6"][:1]))

ro = __import__("sqlite3").connect(common.sqlite_ro_uri(common.DB_PATH), uri=True)
S, n_done = tool.targets(ro)
REC = tool.recon_times(ro)
chk(sorted(S) == sorted(ROWS) and n_done == 0 and S["b1"]["ts"] == ep(C1) * 1000 and S["b1"]["qty"] == "2", "[1] 대상 9건 · 이미 바로잡음 0 · 원장 요약", sorted(S))
chk(REC == [BTS], "[1] 대사 시각 목록(빗썸 대사 보정 줄)", REC)


class Clock:
    def __init__(self):
        self.t, self.sl = 0.0, []

    def __call__(self):
        return self.t

    def sleep(self, x):
        self.sl.append(round(x, 6))
        self.t += x


class RL(RuntimeError):
    code = 429


CALLS = []


def mkcall(fail_at=None):
    def call(path, params):
        assert path == "/v1/order", path
        u = params["uuid"]
        CALLS.append(u)
        if fail_at is not None and len(CALLS) == fail_at:
            raise RL("가짜 429")
        if u not in RESP:
            raise urllib.error.HTTPError("x", 404, "nf", {}, io.BytesIO(b"{}"))
        return json.loads(json.dumps(RESP[u]))
    return call


PROG = os.path.join(common.STATE_DIR, tool.PROGRESS)
buf = io.StringIO()
with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
    rcf = tool.main(["--base", T.TMP, "--fetch"])
chk(rcf == 2 and "키 없음" in buf.getvalue() and not os.path.exists(PROG) and not CALLS, "[2] 키 없는 받기 = 종료 2 · 호출 0 · 진행 파일 없음", buf.getvalue())
st = tool.load_progress(PROG)
ck = Clock()
r1 = tool.fetch(S, st, mkcall(fail_at=3), rps=100, save=lambda: tool.save_progress(PROG, st), clock=ck, sleep=ck.sleep, log=lambda *a: None)
first2 = list(CALLS[:2])
chk(r1["stopped"] and "429" in r1["stopped"] and len(st["got"]) + len(st["keep"]) + len(st["bad"]) == 2 and os.path.exists(PROG),
    "[2] 429 = 멈춤·저장(받은 2건 보존)", (r1, st["got"], st["keep"]))
chk(ck.sl[:2] == [0.2, 0.2], "[2] 상한: 초당 100 요청 → 초당 5(0.2초 간격)", ck.sl)
CALLS.clear()
st = tool.load_progress(PROG)
r2 = tool.fetch(S, st, mkcall(), rps=4, daily_max=3, save=None, clock=Clock(), sleep=lambda x: None, log=lambda *a: None, today=lambda: "2025-12-10")
chk(r2["stopped"] and "하루 한도" in r2["stopped"] and r2["calls"] == 3 and not (set(CALLS) & set(first2)), "[2] 하루 한도 3 = 3회 뒤 멈춤 · 받은 것 다시 안 부름", (r2, CALLS))
for _ in range(3):
    tool.fetch(S, st, mkcall(), rps=4, save=None, clock=Clock(), sleep=lambda x: None, log=lambda *a: None, today=lambda: "2025-12-11")
CALLS.clear()
r3 = tool.fetch(S, st, mkcall(), rps=4, save=None, clock=Clock(), sleep=lambda x: None, log=lambda *a: None)
chk(r3["calls"] == 0 and not CALLS, "[2] 다 받은 뒤 = 0콜", r3)
chk(set(st["got"]) == {"b1", "b2", "b7", "b8"} and st["got"]["b1"]["ts"] == ep(T1B) * 1000 and st["got"]["b1"]["first"] == ep(T1A) * 1000
    and st["got"]["b1"]["ntr"] == 2, "[2] 지정가 4건 = 마지막 체결 시각(b1 = 둘째 체결)", st["got"])
chk(st["keep"] == {"b3": "market", "b6": "fill"}, "[2] 시장가·이미 체결 시각 = 그대로(조회는 했지만 바꾸지 않음)", st["keep"])
chk(set(st["bad"]) == {"b5", "b9"} and "수량" in st["bad"]["b5"]["why"] and "시간대" in st["bad"]["b9"]["why"] and st["nf"].get("b4") == 3,
    "[2] 검사 실패 = 수량 합 다름(b5)·시간대 없는 시각(b9) · 404 3번 포기(b4)", (st["bad"], st["nf"]))
XF.PACE = 0
rt = XF._bithumb_retime(lambda p, q: json.loads(json.dumps(RESP[q["uuid"]])), [dict(fills[0])], {"b1": ROWS["b1"]}, {}, None)
chk(rt[0]["ts"] == st["got"]["b1"]["ts"], "[2] X12(_bithumb_retime)와 같은 시각", (rt[0]["ts"], st["got"]["b1"]))
tool.save_progress(PROG, st)

rep = tool.impact(S, st, REC)
chk(rep["changed"] == 4 and rep["day"] == 3 and rep["month"] == 1 and rep["multi_day"] == 1 and rep["cross_recon"] == 1,
    "[3] 바뀜 4 · 날짜 바뀜 3(b1·b7·b8) · 달 바뀜 1(b7) · 여러 날 체결 1(b1) · 대사 시점을 넘는 건 1(b1)", rep)
chk(rep["krw_changed"] == Decimal(1050) and rep["krw_day"] == Decimal(900) and rep["judged"] == 9 and rep["nf_giveup"] == 1,
    "[3] 영향 금액 합(원화) 바뀜 1,050 · 날짜 바뀜 900 · 판정 9", rep)
mo = rep["months"]
chk(tool.between_sells(ro, S, st) == 1, "[3] 늦춰지는 매수 사이에 같은 코인 매도가 낀 건 1(b1 ↔ b2 매도)")
chk(mo["2025-11"]["n"] == 7 and mo["2025-11"]["chg"] == 3 and mo["2025-11"]["day"] == 2 and mo["2025-12"]["day"] == 1
    and mo["2025-12"]["krw_day"] == Decimal(400), "[3] 월별(옛 시각 기준 한국 달)", mo)
ro.close()

inbox_dir = os.path.join(common.INBOX_DIR, "ex")


def inbox_recs():
    out = []
    if os.path.isdir(inbox_dir):
        for fn in sorted(os.listdir(inbox_dir)):
            if fn.endswith(".jsonl"):
                out += [json.loads(x) for x in open(os.path.join(inbox_dir, fn)) if x.strip()]
    return out


buf = io.StringIO()
with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
    rc0 = tool.main(["--base", T.TMP])
    rcf = tool.main(["--base", T.TMP, "--fetch"])
chk(rc0 == 0 and rcf == 0 and "받을 것 없음" in buf.getvalue() and not inbox_recs(), "[4] 미리보기 = 종료 0 · 다 받은 뒤 받기 = '받을 것 없음' · 쓰기 0",
    (rc0, rcf, buf.getvalue()[-400:]))
out0 = buf.getvalue()
chk("같은 코인 매도가 낀 건 1건" in out0 and "한국 날짜 바뀜 3건" in out0 and "2025-11 | 7 | 7 | 3 | 2" in out0 and "레코드 1개(체결 4건)" in out0, "[4] 미리보기에 비교 표·월별·적용 예정", out0[:1500])
with contextlib.redirect_stdout(io.StringIO()):
    rc1 = tool.main(["--base", T.TMP, "--apply"])
IR = inbox_recs()
chk(rc1 == 0 and len(IR) == 1 and IR[0]["kind"] == "exf_fill_retime" and IR[0]["exchange"] == "bithumb"
    and [f["id"] for f in IR[0]["fills"]] == ["bithumb:b2", "bithumb:b1", "bithumb:b7", "bithumb:b8"],
    "[4] --apply = inbox 'exf_fill_retime' 1개 · 바뀌는 4건만 · 새 시각 순", IR)

open(os.path.join(common.STATE_DIR, "daily_cache.json"), "w").write("{}")
obs1 = dict(C.conn.execute("SELECT uuid, observed_at FROM raw_ex WHERE exchange='bithumb' AND revision=1").fetchall())
FAIL_MIN.add((ep(T8) * 1000 // 60000) * 60000)
GJ.clear()
C.conn.execute("BEGIN")
C._consume_record(IR[0])
C.conn.commit()
n_gj_apply = len(GJ)
rev = {r[0]: (r[1], json.loads(r[2])) for r in C.conn.execute("SELECT uuid, observed_at, payload FROM raw_ex WHERE exchange='bithumb' AND revision=2")}
chk(sorted(rev) == ["bithumb:b1", "bithumb:b2", "bithumb:b7"] and all(rev[k][0] == obs1[k] for k in rev)
    and rev["bithumb:b1"][1]["ts"] == ep(T1B) * 1000 and rev["bithumb:b1"][1]["_tj_retime"]["old"] == ep(C1) * 1000
    and {k: v for k, v in rev["bithumb:b1"][1].items() if k not in ("ts", "_tj_retime")} == {k: v for k, v in fills[0].items() if k != "ts"},
    "[5] raw_ex 새 revision 3건(b8 = 환율 실패로 되돌림) · observed_at 그대로 · 시각만 바뀜 · 표식", {k: v[1].get("_tj_retime") for k, v in rev.items()})
l1, l7 = legs(IDS["b1"]), legs(IDS["b7"])
fx1 = rate((ep(T1B) * 1000 // 60000) * 60000)
chk([x[6] for x in l1] == [ep(T1B)] * 3 and [x[:6] for x in l1] == [x[:6] for x in L0["b1"]] and [x[8] for x in l1] == [x[8] for x in L0["b1"]]
    and abs(float(l1[0][7]) - 200 / fx1) < 1e-9, "[5] b1 레그 3개 시각 = 마지막 체결 · 수량·자산·원화 그대로 · 원가 USD = 새 시각 환율", (l1, L0["b1"], fx1))
chk([x[6] for x in l7] == [ep(T7)] * 3 and datetime.fromtimestamp(l7[0][6], KST).strftime("%Y-%m-%d") == "2025-12-01",
    "[5] b7 = 다음 달 첫날(한국 날짜)로", l7)
chk(all(legs(IDS[u]) == L0[u] for u in ("b3", "b4", "b5", "b6", "b8", "b9")) and positions() == P0, "[5] 그 밖 체결 그대로 · 포지션 합 불변", positions())
hd = common.read_json(os.path.join(common.STATE_DIR, common.HIST_DIRTY), {}) or {}
chk(not os.path.exists(os.path.join(common.STATE_DIR, "daily_cache.json")) and hd.get("from") == "2025-11-05",
    "[5] 일별 동결 캐시 삭제 · 장기 곡선 다시 계산 표식 = 가장 이른 옛 날(2025-11-05)부터", hd)
mk = json.loads(C._meta_get("exf_retime:bithumb") or "{}")
chk(mk.get("n") == 3 and mk.get("undo") == 1, "[5] meta 표식(바로잡은 3 · 되돌림 1)", mk)
chk(n_gj_apply <= 5, "[5] 환율 = 묶음마다 1콜(4묶음 + 실패 재시도 ≤1)", (n_gj_apply, GJ))

snap = (positions(), {u: legs(IDS[u]) for u in ROWS}, C.conn.execute("SELECT COUNT(*) FROM raw_ex").fetchone()[0])
C.conn.execute("BEGIN")
C._consume_record(IR[0])
C._consume_record({"v": 1, "kind": "exf_fill_retime", "exchange": "bithumb", "ts": 1, "fills": [
    {"id": "bithumb:b3", "ts_old": ep(C1) * 1000, "ts": ep(T1B) * 1000},
    {"id": "bithumb:b5", "ts_old": S["b5"]["ts"], "ts": S["b5"]["ts"] - 3600 * 1000},
    {"id": "bithumb:zz", "ts_old": 1, "ts": 2}]})
C.conn.commit()
FAIL_MIN.discard((ep(T8) * 1000 // 60000) * 60000)
chk((positions(), {u: legs(IDS[u]) for u in ROWS if u != "b8"}, C.conn.execute("SELECT COUNT(*) FROM raw_ex").fetchone()[0])
    == (snap[0], {u: v for u, v in snap[1].items() if u != "b8"}, snap[2]), "[6] 두 번 적용·어긋난 요청 = 무변(멱등 · 거부)")

C.px.d["neg_ts"].pop("_fx", None)
with contextlib.redirect_stdout(io.StringIO()):
    rc2 = tool.main(["--base", T.TMP, "--apply"])
IR2 = inbox_recs()[1:]
C.conn.execute("BEGIN")
for r in IR2:
    C._consume_record(r)
C.conn.commit()
chk(rc2 == 0 and len(IR2) == 1 and [f["id"] for f in IR2[0]["fills"]] == ["bithumb:b8"] and [x[6] for x in legs(IDS["b8"])] == [ep(T8)] * 3
    and positions() == P0, "[7] 환율 실패로 되돌린 b8 = 다음 --apply 때 반영", (IR2, legs(IDS["b8"])))

live = {u: legs(IDS[u]) for u in ROWS}
C.conn.execute("BEGIN")
for r in C.conn.execute("SELECT asset_id, location, qty_base FROM postings WHERE source_kind='exchange' AND source_ns='bithumb:trade'").fetchall():
    C._bump_position(r[0], -int(r[2]), r[1])
C.conn.execute("DELETE FROM postings WHERE source_kind='exchange' AND source_ns='bithumb:trade'")
for t in rb2.exf_trade_rows(C.conn):
    C._post_exf_fill(t["exchange"], json.loads(t["payload"]))
reb = {u: legs(IDS[u]) for u in ROWS}
pos_reb = positions()
C.conn.execute("DELETE FROM postings WHERE source_kind='exchange' AND source_ns='bithumb:trade'")
for t in C.conn.execute("SELECT exchange, payload FROM raw_ex WHERE kind='trade' AND exchange != 'upbit' ORDER BY observed_at, exchange, uuid, revision").fetchall():
    C._post_exf_fill(t["exchange"], json.loads(t["payload"]))
old_way = {u: legs(IDS[u]) for u in ROWS}
C.conn.rollback()
chk(reb == live and pos_reb == P0, "[8] 재구축(최신 revision) = 같은 시각·레그·원가 · 포지션 불변", {u: (reb[u][:1], live[u][:1]) for u in ROWS if reb[u] != live[u]})
chk(old_way["b1"][0][6] == ep(C1) and old_way["b1"] != live["b1"], "[8] (재현) 종전 SQL = 첫 revision 이 자리를 먼저 차지 → 옛 생성 시각으로 되돌아감", old_way["b1"][:1])

ro = __import__("sqlite3").connect(common.sqlite_ro_uri(common.DB_PATH), uri=True)
S2, n_done2 = tool.targets(ro)
ro.close()
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc3 = tool.main(["--base", T.TMP, "--apply"])
chk(n_done2 == 4 and sorted(S2) == ["b3", "b4", "b5", "b6", "b9"] and rc3 == 0 and "적용할 것 없음" in buf.getvalue() and len(inbox_recs()) == 2,
    "[9] 적용 뒤 = 이미 바로잡음 4 · 남은 대상에 바뀔 것 없음 · 레코드 0", (n_done2, sorted(S2), buf.getvalue()))

GJ.clear()
mins = [(ep(kiso(2025, 12, 20, 3, 0)) + k * 60) * 1000 for k in (0, 1, 7, 150, 260, 600)]
for m in mins:
    C.px.d["fx"].pop(str(m), None)
nw = C.px.fx_warm([m + 30000 for m in mins])
n_warm = len(GJ)
warm_vals = {m: C.px.d["fx"].get(str(m)) for m in mins}
ref_vals = {m: pricing._fx_candle_krw_per_usdt(m) for m in mins}
chk(nw == len(mins) and n_warm == 3 and warm_vals == ref_vals, "[10] 미리 받기 = 1분봉 하나씩 받은 값과 같음 · 6분 → 3콜(200분 묶음)", (nw, n_warm, warm_vals, ref_vals))
GJ.clear()
chk(C.px.fx_warm(mins) == 0 and not GJ, "[10] 이미 있는 분 = 0콜", GJ)

mins2 = [(ep(kiso(2025, 12, 21, 3, 0)) + k * 300 * 60) * 1000 for k in range(6)]
for m in mins2:
    C.px.d["fx"].pop(str(m), None)
C.px.d["neg_ts"]["_fx"] = int(__import__("time").time())
GJ.clear()
nw0 = C.px.fx_warm(mins2)
chk(nw0 == 0 and not GJ, "[11] fx_at 60초 쉼 표식 중 = 미리 받기 0콜", GJ)
for code in (429, 418):
    C.px.d["neg_ts"].pop("_fx", None)
    for m in mins2:
        C.px.d["fx"].pop(str(m), None)
    GJ.clear()
    real_gj = pricing._gj

    def gj_lim(url, timeout=10.0, _c=code):
        GJ.append(url)
        raise urllib.error.HTTPError(url, _c, "limit", {}, io.BytesIO(b""))
    pricing._gj = gj_lim
    nw1 = C.px.fx_warm(mins2)
    n_after_warm = len(GJ)
    fa = C.px.fx_at(mins2[0])
    pricing._gj = real_gj
    chk(nw1 == 0 and n_after_warm == 1 and int(C.px.d["neg_ts"].get("_fx") or 0) > 0 and fa is None and len(GJ) == 1,
        f"[11] HTTP {code} = 첫 묶음에서 즉시 그만(남은 5묶음 안 부름) · fx_at 과 같은 쉼 표식 → fx_at 도 안 부름", (code, nw1, GJ))
C.px.d["neg_ts"].pop("_fx", None)
for m in mins2:
    C.px.d["fx"].pop(str(m), None)
GJ.clear()
FAIL_MIN.add(mins2[0])
nw2 = C.px.fx_warm(mins2)
FAIL_MIN.discard(mins2[0])
chk(nw2 == 0 and len(GJ) == 1 and int(C.px.d["neg_ts"].get("_fx") or 0) > 0, "[11] 전송 오류도 fx_at 과 같은 규칙(쉼 표식 · 그만)", GJ)
C.px.d["neg_ts"].pop("_fx", None)
T.finish()
