#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
from decimal import Decimal  # noqa: E402

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import config, paths, statefile  # noqa: E402

assert T.TMP in paths.STATE_DIR
import ex_foreign as EF  # noqa: E402
import exf_binance as XB  # noqa: E402
import exf_net  # noqa: E402

chk = T.chk
NOW = int(time.time())
DAY = 86400
ENV = {"TJ_BINANCE_KEY": "k", "TJ_BINANCE_SECRET": "s"}
S = {"rows": [], "calls": [], "order": "desc", "fail": None}


def fake_call(path, q):
    if path != "/sapi/v1/asset/assetDividend":
        raise AssertionError("예상 밖 경로 " + path)
    S["calls"].append((int(q["startTime"]), int(q["endTime"]), int(q["limit"])))
    if S["fail"]:
        raise S["fail"]
    if "raw" in S:
        return S["raw"]
    hit = [r for r in S["rows"] if int(q["startTime"]) <= int(r["divTime"]) <= int(q["endTime"])]
    hit.sort(key=lambda r: int(r["divTime"]), reverse=(S["order"] == "desc"))
    if not hit and "total" not in S:
        return {"total": 0}
    return {"rows": [dict(r) for r in hit[:int(q["limit"])]], "total": S.get("total", len(hit))}


def row(i, ts_ms, asset="TKA", amt="1.5", info="Launchpool distribution"):
    return {"id": 9000 + i, "amount": amt, "asset": asset, "divTime": int(ts_ms), "enInfo": info, "tranId": 7000 + i}


fn0 = getattr(XB, "dividend_binance", None)
chk(callable(fn0), "D0 exf_binance.dividend_binance 있음")
if not callable(fn0):
    T.finish()


def fn(env, t0, t1):
    return fn0(env, t0, t1, call=fake_call, pace=0)


t_a = (NOW - 5 * DAY) * 1000
S["rows"] = [row(1, t_a), row(2, t_a + 1000, "USDT", "0.3", "Simple Earn Flexible Interest"), row(3, t_a + 2000, "TKB", "0"),
             row(4, t_a + 3000, "NEWX", "100", "Token Swap - Redenomination/Rebranding"), row(5, t_a + 4000, "TKC", "-2")]
out = fn(ENV, NOW - 10 * DAY, NOW)
ids = [r["id"] for r in out]
chk(ids == ["binance:div:9001", "binance:div:9002"], "D1 지급 2건만(0·음수·토큰 교환/개명 분배 제외)", ids)
r1 = out[0] if out else {}
chk(r1.get("src") == "income" and r1.get("late") == 1 and r1.get("asset") == "TKA" and r1.get("amount") == "1.5" and r1.get("ts") == t_a,
    "D1 행 = src income · late · 통화·수량·시각(ms) 그대로", r1)
S["rows"] = [{"id": 1, "asset": "TKA", "divTime": t_a}]
try:
    fn(ENV, NOW - 10 * DAY, NOW)
    bad = False
except RuntimeError:
    bad = True
chk(bad, "D1 필드 누락 = 예외(조용히 0 아님)")
S["rows"] = [dict(row(1, t_a), tranId=555), dict(row(2, t_a + 1000), tranId=555)]
chk(len(fn(ENV, NOW - 10 * DAY, NOW)) == 2, "D1 tranId 가 같은 두 지급(id 다름) = 두 행(행 키 = id)")
S["rows"] = [{k: v for k, v in row(1, t_a).items() if k != "id"}]
try:
    fn(ENV, NOW - 10 * DAY, NOW)
    bad = False
except RuntimeError:
    bad = True
chk(bad, "D1 id 없는 행 = 예외(tranId 로 대신하지 않음 — 공유될 수 있음)")
S["rows"] = [row(1, t_a, info=None), row(2, t_a + 1, info="x" * 90 + " Token Swap"), row(3, t_a + 2, info="  ")]
chk(fn(ENV, NOW - 10 * DAY, NOW) == [], "D1 설명(enInfo) 없음·빈칸 = 안 냄(교환 분배인지 모름 → 종전대로 대사) · 80자 뒤 'Swap' 도 전체 설명으로 판정")
for raw9, lab9 in (({}, "{}"), ({"rows": []}, "{rows: []}"), ([], "목록"), ({"rows": [], "total": "x"}, "total 글자")):
    S["raw"] = raw9
    try:
        fn(ENV, NOW - 10 * DAY, NOW)
        bad = False
    except RuntimeError:
        bad = True
    chk(bad, f"D1 total 없는·형식 틀린 응답({lab9}) = 예외(빈 창으로 보고 백필을 전진시키지 않음)")
S.pop("raw")

for order in ("desc", "asc"):
    S["order"] = order
    S["rows"] = [row(i, t_a + i * 7000) for i in range(1, 1301)]
    S["calls"] = []
    out = fn(ENV, NOW - 10 * DAY, NOW)
    got = sorted(int(r["id"].rsplit(":", 1)[1]) for r in out)
    chk(got == list(range(9001, 10301)) and len(out) == len(set(r["id"] for r in out)),
        f"D2 1,300건(창 상한 500) — 반씩 나눠 전부 · 중복 0 ({order})", (len(out), len(S["calls"])))
chk(all(c[2] == 500 for c in S["calls"]) and len(S["calls"]) <= 40, "D2 limit 500 · 나눈 횟수 유한", len(S["calls"]))
S["order"] = "desc"

t0 = NOW - 200 * DAY
edge = (t0 + 89 * DAY) * 1000
S["rows"] = [row(1, edge), row(2, edge + 500), row(3, edge - 1), row(4, NOW * 1000)]
S["calls"] = []
out = fn(ENV, t0, NOW)
chk(sorted(r["id"] for r in out) == ["binance:div:9001", "binance:div:9002", "binance:div:9003", "binance:div:9004"],
    "D3 조각 경계 ms·그 초 안·직전·끝 시각 지급 전부(겹침)", sorted(r["id"] for r in out))
spans = [(c[1] - c[0]) for c in S["calls"]]
chk(max(spans) <= 89 * DAY * 1000 and S["calls"][0][0] == t0 * 1000 and S["calls"][-1][1] == NOW * 1000
    and all(S["calls"][i][1] == S["calls"][i + 1][0] for i in range(len(S["calls"]) - 1)),
    "D3 조각 ≤ 89일 · 시작 = t0 · 끝 = t1 · 이웃 조각은 경계 ms 를 함께 봄", S["calls"])
S["rows"] = [row(i, t_a) for i in range(600)]
try:
    fn(ENV, NOW - 10 * DAY, NOW)
    bad = False
except RuntimeError:
    bad = True
chk(bad, "D3 같은 1초에 500건 넘음 = 예외(창 보류 — 조용한 절단 없음)")
S["rows"] = [row(1, t_a)]
S["calls"] = []
S["total"] = 10 ** 6
try:
    fn(ENV, NOW - 10 * DAY, NOW)
    bad = False
except RuntimeError:
    bad = True
chk(bad and len(S["calls"]) <= XB.BN_DIV_MAX_CALLS, "D3 total 이 늘 행 수보다 큰 응답 = 조회 상한에서 예외(호출 폭주 없음)", len(S["calls"]))
S.pop("total")

S["rows"] = [row(1, t_a)]
fst = {}
S["calls"] = []
EF._DIV_OFF[0] = False
win = 150 * DAY
o1 = EF._convert_src("binance", "cv_div", fn, ENV, fst, NOW, win)
chk([r["id"] for r in o1] == ["binance:div:9001"] and S["calls"] and S["calls"][0][0] == (NOW - win) * 1000 and fst["cv_div"].get("bf"),
    "D4 첫 회 = 수집 창 시작부터 · 백필 표시", (S["calls"][:1], fst.get("cv_div")))
S["calls"] = []
EF._convert_src("binance", "cv_div", fn, ENV, fst, NOW + 600, win)
chk(S["calls"] and S["calls"][0][0] == (NOW + 600 - 3 * DAY) * 1000, "D4 다음 회 = 3일 겹침 증분", S["calls"][:1])
fst2 = {}
S["fail"] = urllib.error.HTTPError("https://api.binance.com/x", 401, "Unauthorized", {}, None)
o2 = EF._convert_src("binance", "cv_div", fn, ENV, fst2, NOW, win)
cv2 = fst2.get("cv_div") or {}
chk(o2 == [] and "401" in str(cv2.get("err") or "") and float(cv2.get("off_until") or 0) > time.time() + 5 * 3600
    and "cv:cv_div" not in (fst2.get("hold_since") or {}), "D4 권한 거부 = 사유 기록 · 6시간 쉼 · 잔고 승격 보류 안 함", cv2)
fst3 = {}
S["fail"] = OSError("합성 장애")
EF._CV_OFF.pop("binance:cv_div", None)
EF._convert_src("binance", "cv_div", fn, ENV, fst3, NOW, win)
chk("cv:cv_div" in (fst3.get("hold_since") or {}), "D4 일시 실패 = 잔고 승격 보류(성공 때까지)", fst3)
S["fail"] = None
EF._CV_OFF.pop("binance:cv_div", None)
far = time.time() + 10 ** 6
fst4 = {"cv": {"off_until": far}, "cv_dust": {"off_until": far}, "cv_div": {}, "hold_since": {"cv:cv_div": NOW - 60}}
EF._DIV_OFF[0] = True
o4 = EF.convert_rows("binance", ENV, fst4, NOW, win)
chk(o4 == [] and "cv:cv_div" not in (fst4.get("hold_since") or {}) and not (fst4.get("cv_div") or {}).get("bf"),
    "D4 config exf.binance_dividends=false = 지급 내역 조회 0(실제 호출기 — 바깥 연결 0 은 맨 끝 검사) · 잔고 승격 보류 풀림", fst4)
EF._DIV_OFF[0] = False
chk(exf_net._BN_W_SAPI.get("/sapi/v1/asset/assetDividend") == 10, "D4 예산 표 가중치 10(IP · sapi 버킷)")

import core  # noqa: E402

C = core.Core(config.load_config())
PX = {"USDT": Decimal(1), "TKA": Decimal("2.5"), "TKB": Decimal("0.1"), "BNB": Decimal(600)}
C.svc_exf._quote_usd = lambda q, ts: PX.get(str(q).upper())
C.px.fx_at = lambda ms: 1380.0
C.svc_exf.EXF_INIT_PHASE = 5
E8 = 10 ** 8
SEQ = {"t": NOW - 1700}


def tick(d=10):
    SEQ["t"] += d
    return SEQ["t"]


def recon(bal):
    bts = tick()
    st = statefile.read_json(os.path.join(paths.STATE_DIR, "exf_state.json"), {})
    st.setdefault("binance", {"seen": {}, "backfilled_until": NOW, "fills": {"backfilled_until": NOW}})
    statefile.atomic_write_json(os.path.join(paths.STATE_DIR, "exf_state.json"), st)
    statefile.atomic_write_json(os.path.join(paths.STATE_DIR, "exf_balances_binance.json"),
                                {"ts": bts, "balances": {k: float(v) for k, v in bal.items()}, "sources": ["spot"]})
    C._drain_at = bts + 5
    C.svc_exf._last_exfrecon = 0
    C.svc_exf.exf_recon_pass({"ex"})
    return bts


def total(sym):
    v = C.conn.execute("SELECT SUM(CAST(p.qty_base AS INTEGER)) FROM postings p JOIN assets a USING(asset_id) WHERE p.location='exchange:binance'"
                       " AND upper(a.symbol)=?", (sym,)).fetchone()[0]
    return Decimal(int(v or 0)) / E8


def adj(sym, after=0):
    return sum(Decimal(int(r[0])) / E8 for r in C.conn.execute(
        "SELECT p.qty_base FROM postings p JOIN assets a USING(asset_id) WHERE p.location='exchange:binance' AND p.event='EXF_ADJUST'"
        " AND upper(a.symbol)=? AND p.event_ts>=?", (sym, after)))


def n_late_off(sym):
    return C.conn.execute("SELECT count(*) FROM postings p JOIN assets a USING(asset_id) WHERE p.source_id LIKE 'exflate:%' AND upper(a.symbol)=?",
                          (sym,)).fetchone()[0]


def income(sym):
    return [(int(r[0]), Decimal(int(r[1])) / E8, r[2], r[3], r[4], r[5]) for r in C.conn.execute(
        "SELECT p.event_ts, p.qty_base, p.cost_usd, p.cost_krw, p.leg_kind, p.event FROM postings p JOIN assets a USING(asset_id)"
        " WHERE p.source_ns='binance:income' AND upper(a.symbol)=? ORDER BY p.event_ts", (sym,)).fetchall()]


def pos_ok(sym):
    g = C._group_of(C.svc_exf._exf_asset("binance", sym))
    r = C.conn.execute("SELECT qty_norm FROM positions WHERE group_id=? AND location='exchange:binance'", (g,)).fetchone()
    return Decimal(r[0] if r else 0) == total(sym)


def deliver(rows, lc):
    rec = {"v": 1, "kind": "exf_fills", "exchange": "binance", "ts": NOW, "fills": rows, "lb": f"binance:{lc}", "lbi": 0, "lbn": 1, "lc": lc}
    C.svc_exf._consume_exf_fills(rec)
    C.svc_exf._late_cycle_done({"exchange": "binance", "lc": lc})
    C.conn.commit()
    C.svc_exf._exf_late_flush()
    C.conn.commit()


def div(i, t, sym, amt, info="Launchpool distribution"):
    return {"id": f"binance:div:{i}", "ts": int(t) * 1000, "src": "income", "late": 1, "asset": sym, "base": sym, "amount": str(amt), "info": info}


recon({"BNB": 2, "USDT": 1000})
t_d1 = tick(100)
t_d2 = tick(5)
t_d3 = tick(5)
b2 = recon({"BNB": 2, "USDT": "1012.5", "TKA": 40, "TKB": 3000})
pre = {s: total(s) for s in ("TKA", "TKB", "USDT", "BNB")}
pre_adj = {s: adj(s, b2) for s in ("TKA", "TKB", "USDT")}
chk(pre_adj == {"TKA": 40, "TKB": 3000, "USDT": Decimal("12.5")}, "C2 준비: 지급분이 대사 보정(EXF_ADJUST)으로만 들어가 있음(종전 상태)", pre_adj)
deliver([div(1, t_d1, "TKA", 40), div(2, t_d2, "TKB", 3000), div(3, t_d3, "USDT", "12.5", "Simple Earn Flexible Interest")], "c1")
post_ = {s: total(s) for s in ("TKA", "TKB", "USDT", "BNB")}
chk(post_ == pre, "C2 통화별 원장 합 무변(잔고·총자산 그대로)", (pre, post_))
chk({s: adj(s, b2) for s in ("TKA", "TKB", "USDT")} == {"TKA": 0, "TKB": 0, "USDT": 0}, "C2 그 대사 보정 = 0(수입 행으로 대체)",
    {s: adj(s, b2) for s in ("TKA", "TKB", "USDT")})
inc_a = income("TKA")
chk(len(inc_a) == 1 and inc_a[0][0] == t_d1 and inc_a[0][1] == 40 and inc_a[0][4] == "acq" and inc_a[0][5] == "STAKE_REWARD"
    and abs(float(inc_a[0][2]) - 100.0) < 1e-9 and abs(float(inc_a[0][3]) - 138000.0) < 1e-6,
    "C1 수입 행 = 받은 시각 · STAKE_REWARD 취득 · 원가 = 수량 × 그 시각 시가($100 · ₩138,000)", inc_a)
chk(all(pos_ok(s) for s in ("TKA", "TKB", "USDT")), "C2 포지션 = 원장 합")
chk(n_late_off("TKA") + n_late_off("TKB") + n_late_off("USDT") == 0, "C2 상쇄 줄(exflate) 없음 — 보정을 줄여 대체")
nraw = C.conn.execute("SELECT count(*) FROM raw_ex WHERE exchange='binance' AND kind='income'").fetchone()[0]
chk(nraw == 3, "C1 원본 = raw_ex kind 'income' 3건", nraw)
deliver([div(1, t_d1, "TKA", 40)], "c1b")
chk(len(income("TKA")) == 1 and total("TKA") == pre["TKA"], "C1 같은 지급 다시 = 한 줄(멱등) · 합 무변", income("TKA"))
b3 = recon({"BNB": 2, "USDT": "1012.5", "TKA": 40, "TKB": 3000})
chk(adj("TKA", b3) == 0 and adj("TKB", b3) == 0 and adj("USDT", b3) == 0, "C2 다음 대사 보정 0(원장 = 잔고)")

t_d4 = tick(50)
deliver([div(4, t_d4, "TKA", 5)], "c3")
chk(total("TKA") == 45 and adj("TKA", b2) == 0 and n_late_off("TKA") == 0, "C3 마지막 대사 뒤 지급 = 수입 행만(보정·상쇄 안 건드림)", total("TKA"))
b4 = recon({"BNB": 2, "USDT": "1012.5", "TKA": 45, "TKB": 3000})
chk(adj("TKA", b4) == 0, "C3 다음 대사 차이 없음", adj("TKA", b4))

t_d5 = tick(50)
b5 = recon({"BNB": 2, "USDT": "1012.9", "TKA": 45, "TKB": 3000})
chk(adj("USDT", b5) == 0, "C4 준비: 소액 차이는 대사 보류(보정 없음)", adj("USDT", b5))
deliver([div(5, t_d5, "USDT", "0.4", "Simple Earn Flexible Interest")], "c4")
chk(total("USDT") == Decimal("1012.9") and n_late_off("USDT") == 0, "C4 보류분 지급 = 수입 행 그대로(상쇄 줄이 지우지 않음) · 원장 = 잔고",
    (total("USDT"), n_late_off("USDT")))
b6 = recon({"BNB": 2, "USDT": "1012.9", "TKA": 45, "TKB": 3000})
chk(adj("USDT", b6) == 0, "C4 다음 대사 보정 0", adj("USDT", b6))

def post(t, sym, qty, ns="binance:deposit", sid=None, ev="EXF_DEPOSIT", lk="move_in", seq=0):
    aid = C.svc_exf._exf_asset("binance", sym)
    qb = int(Decimal(str(qty)) * E8)
    C.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw,"
                   " leg_kind, event, classifier_ver) VALUES ('exchange',?,?,?,?,?,'exchange:binance',?,NULL,NULL,?,?,?)",
                   (ns, sid or f"t:{t}:{sym}:{qty}", seq, int(t), aid, str(qb), lk, ev, core.CLASSIFIER_VER))
    C._bump_position(aid, qb, "exchange:binance")
    C.conn.commit()


last_b = int(float(C._meta_get("recon_done_exf_binance")))
t1 = last_b - 900
post(t1 - 300, "TKD", "100")
post(t1, "TKD", "-149.6", ns="binance:trade", sid="x1", ev="EXF_SELL", lk="disp")
post(t1, "TKD", "49.6", ns="binance:recon", sid=f"exfrecon:TKD:{last_b}", ev="EXF_ADJUST", lk="opening", seq=1)
post(t1 + 5, "TKD", "-0.5", ns="binance:trade", sid="x2", ev="EXF_FEE", lk="gas")
post(t1 + 9, "TKD", "0.5", ns="binance:deposit", sid="x3")
pre6 = total("TKD")
deliver([div(6, t1 - 200, "TKD", "49.6")], "c6")
chk(total("TKD") == pre6 and adj("TKD") == 0 and len(income("TKD")) == 1 and n_late_off("TKD") == 0,
    "C6 그 뒤 원장에 원래 잠깐 음수가 있어도 보정 49.6 전부 → 수입 행(합 무변 · 일부만 줄지 않음)", (total("TKD"), adj("TKD")))

t_open = int(C.svc_exf._exf_open_ts("binance", last_b))
post(t_open, "TKE", "500", ns="binance:recon", sid=f"exfrecon:TKE:{last_b}", ev="EXF_ADJUST", lk="opening")
post(t_open + 100, "TKE", "-400", ns="binance:trade", sid="x4", ev="EXF_SELL", lk="disp")
pre7 = total("TKE")
deliver([div(7, last_b - 600, "TKE", "20"), div(8, last_b - 500, "TKE", "40")], "c7")
chk(total("TKE") == pre7 and adj("TKE") == Decimal("440") and len(income("TKE")) == 2,
    "C7 기초 잔고 500 → 440 · 지급 20·40 = 수입 행 · 합 무변", (total("TKE"), adj("TKE")))
post(t_open, "TKF", "500", ns="binance:recon", sid=f"exfrecon:TKF:{last_b}", ev="EXF_ADJUST", lk="opening")
post(t_open + 100, "TKF", "-470", ns="binance:trade", sid="x5", ev="EXF_SELL", lk="disp")
deliver([div(9, last_b - 600, "TKF", "20"), div(10, last_b - 500, "TKF", "40")], "c7b")
ser7 = C.svc_exf._exf_series("binance", "TKF")
run7, mn7 = Decimal(0), Decimal(0)
for _t7, q7 in ser7:
    run7 += q7
    mn7 = min(mn7, run7)
chk(adj("TKF") == Decimal("470") and total("TKF") == Decimal("60") and mn7 >= 0,
    "C7 여유가 모자라면(지급 전 매도) 그 여유(30)까지만 대체 · 새 음수 없음 · 나머지 30 은 다음 대사가 차이로", (adj("TKF"), total("TKF"), mn7))

b_prev = last_b - 3000
post(b_prev - 50, "TKG", "-1", ns="binance:recon", sid=f"exfrecon:TKG:{b_prev}", ev="EXF_ADJUST", lk="opening")
post(b_prev - 4000, "TKG", "300", ns="binance:deposit", sid="x6")
post(b_prev - 2000, "TKG", "-350", ns="binance:trade", sid="x7", ev="EXF_SELL", lk="disp")
post(b_prev - 2000, "TKG", "50", ns="binance:recon", sid=f"exfrecon:TKG:{last_b}", ev="EXF_ADJUST", lk="opening", seq=1)
pre8 = total("TKG")
deliver([div(11, b_prev - 2500, "TKG", "50")], "c8")
chk(total("TKG") == pre8 and adj("TKG") == Decimal("-1") and n_late_off("TKG") == 0,
    "C8 지급(앞 경계 전) = 당겨진 뒤 대사 보정 50 대체 · 앞 대사 보정(−1) 그대로 · 합 무변", (total("TKG"), adj("TKG")))

b_a, b_b = last_b - 2600, last_b - 100
post(b_a - 400, "TKH", "100", ns="binance:deposit", sid="x8")
post(b_a, "TKH", "-30", ns="binance:recon", sid=f"exfrecon:TKH:{b_a}", ev="EXF_ADJUST", lk="opening")
post(b_b, "TKH", "500", ns="binance:recon", sid=f"exfrecon:TKH:{b_b}", ev="EXF_ADJUST", lk="opening")
pre9 = total("TKH")
deliver([div(12, b_a - 200, "TKH", "10")], "c9")
chk(adj("TKH") == Decimal("470") and total("TKH") == pre9 + 10 and n_late_off("TKH") == 0,
    "C9 지급 10 = 수입 행 · 나중 대사 +500 그대로(경계 밖) · 못 맞춘 10 은 다음 대사가 차이로(상쇄 줄 없음)", (adj("TKH"), total("TKH") - pre9))

post(last_b - 5000, "TKJ", "100", ns="binance:deposit", sid="x9")
pre11 = total("TKJ")
sell = {"id": "binance:TKJUSDT:77", "ts": (last_b - 700) * 1000, "base": "TKJ", "quote": "USDT", "side": "sell", "price": "1", "qty": "10",
        "fee": "0", "fee_ccy": "", "late": 1}
pre_u = total("USDT")
deliver([div(13, last_b - 800, "TKJ", "10"), sell], "c11")
chk(total("TKJ") == pre11 and n_late_off("TKJ") == 0, "C11 지급 +10 · 늦은 매도 −10(대사가 둘 다 몰라 차이 0) = TKJ 합 무변 · 상쇄 줄 없음",
    (total("TKJ") - pre11, n_late_off("TKJ")))

post(last_b - 5000, "TKM", "100", ns="binance:deposit", sid="x12")
pre12 = total("TKM")
cv12 = {"id": "binance:cv:TKM:1", "ts": (last_b + 50) * 1000, "src": "convert", "base": "TKM", "quote": "USDT", "side": "buy", "price": "1",
        "qty": "5", "fee": "0", "fee_ccy": ""}
deliver([div(14, last_b - 800, "TKM", "0.4"), cv12], "c12")
chk(total("TKM") == pre12 + Decimal("5.4") and n_late_off("TKM") == 0 and pos_ok("TKM"),
    "C12 대사 전 지급 0.4 + 대사 뒤 새 전환 +5 = 원장 +5.4 · 상쇄 줄 없음(전환이 대사 뒤라 지급 혼자 상쇄되지 않음)",
    (total("TKM") - pre12, n_late_off("TKM")))


def bal_now(**over):
    syms = [r[0].upper() for r in C.conn.execute("SELECT DISTINCT a.symbol FROM postings p JOIN assets a USING(asset_id) WHERE p.location='exchange:binance'")]
    b = {s9: total(s9) for s9 in syms}
    b.update({k: Decimal(str(v)) for k, v in over.items()})
    return {k: str(v) for k, v in b.items()}


post(int(float(C._meta_get("recon_done_exf_binance"))) + 1, "USDC", "100", ns="binance:deposit", sid="x13")
t_sell13 = tick(20)
r1_13 = recon(bal_now(USDC="90"))
t_inc13 = tick(20)
r2_13 = recon(bal_now(USDC="90.4"))
chk(adj("USDC", r1_13) == Decimal("-10") and adj("USDC", r2_13) == 0, "C13 준비: R1 보정 −10 · R2 소액 보류", (adj("USDC", r1_13), adj("USDC", r2_13)))
sell13 = {"id": "binance:USDCTKQ:13", "ts": t_sell13 * 1000, "base": "USDC", "quote": "TKQ", "side": "sell", "price": "1", "qty": "10",
          "fee": "0", "fee_ccy": "", "late": 1}
deliver([div(15, t_inc13, "USDC", "0.4"), sell13], "c13")
chk(total("USDC") == Decimal("90.4") and n_late_off("USDC") == 0 and pos_ok("USDC"),
    "C13 R1 구간 늦은 매도 −10(R1 보정 되돌림) + R2 구간 지급 +0.4 = 원장 90.4(실잔고) · 상쇄 줄 없음", (total("USDC"), n_late_off("USDC")))

post(int(float(C._meta_get("recon_done_exf_binance"))) + 1, "DAI", "100", ns="binance:deposit", sid="x14")
t_b14, t_s14, t_i14 = tick(20), tick(5), tick(5)
r14 = recon(bal_now(DAI="100.4"))
chk(adj("DAI", r14) == 0, "C14 준비: 대사 차이 +0.4 소액 보류", adj("DAI", r14))
fill14 = lambda i, t, side: {"id": f"binance:DAITKQ:{i}", "ts": t * 1000, "base": "DAI", "quote": "TKQ", "side": side, "price": "1", "qty": "10",
                             "fee": "0", "fee_ccy": "", "late": 1}
deliver([div(16, t_i14, "DAI", "0.4"), fill14(141, t_b14, "buy"), fill14(142, t_s14, "sell")], "c14")
chk(total("DAI") == Decimal("100.4") and n_late_off("DAI") == 0 and pos_ok("DAI"),
    "C14 같은 구간 늦은 매수 +10·매도 −10 + 지급 +0.4 = 원장 100.4(실잔고) · 상쇄 줄 없음", (total("DAI"), n_late_off("DAI")))

lb15 = int(float(C._meta_get("recon_done_exf_binance")))
t_open15 = int(C.svc_exf._exf_open_ts("binance", lb15))
b_a15 = lb15 - 2600


def tomb(sym, b9):
    C.conn.execute("INSERT OR IGNORE INTO exf_adj_tomb (ex, sym, bts) VALUES ('binance', ?, ?)", (sym, int(b9)))
    C.conn.commit()


tomb("TKU", b_a15)
post(t_open15, "TKU", "500", ns="binance:recon", sid=f"exfrecon:TKU:{lb15}", ev="EXF_ADJUST", lk="opening")
pre15 = total("TKU")
deliver([div(21, b_a15 - 900, "TKU", "20"), div(22, b_a15 - 800, "TKU", "40")], "c15")
chk(total("TKU") == pre15 and adj("TKU") == Decimal("440") and len(income("TKU")) == 2 and n_late_off("TKU") == 0 and pos_ok("TKU"),
    "C15 지급 뒤 첫 경계(앞 대사)는 흡수 안 함 · 나중 대사(bts ≥ 지급)가 창 시작에 적은 앵커 500 → 440 = 수입 행으로 대체 · 합 무변",
    (total("TKU") - pre15, adj("TKU")))
tomb("TKY", b_a15)
post(t_open15 + 50, "TKY", "300", ns="binance:deposit", sid="x15y")
post(b_a15 - 3000, "TKY", "-350", ns="binance:trade", sid="x15y2", ev="EXF_SELL", lk="disp")
post(b_a15 - 3000, "TKY", "80", ns="binance:recon", sid=f"exfrecon:TKY:{lb15}", ev="EXF_ADJUST", lk="opening", seq=1)
pre15y = total("TKY")
deliver([div(23, b_a15 - 700, "TKY", "30")], "c15y")
chk(total("TKY") == pre15y and adj("TKY") == Decimal("50") and n_late_off("TKY") == 0, "C15 당겨진 나중 대사 보정 80 → 50(여유 30 = 지급분만 · 결손 50 은 그대로)",
    (total("TKY") - pre15y, adj("TKY")))
post(t_open15, "TKX", "10", ns="binance:recon", sid=f"exfrecon:TKX:{b_a15}", ev="EXF_ADJUST", lk="opening")
post(t_open15, "TKX", "500", ns="binance:recon", sid=f"exfrecon:TKX:{lb15}", ev="EXF_ADJUST", lk="opening")
pre15x = total("TKX")
deliver([div(24, b_a15 - 900, "TKX", "20")], "c15x")
a15x = {int(str(r[0]).rsplit(":", 1)[1]): Decimal(int(r[1])) / E8 for r in C.conn.execute(
    "SELECT p.source_id, p.qty_base FROM postings p JOIN assets a USING(asset_id) WHERE p.event='EXF_ADJUST' AND upper(a.symbol)='TKX'")}
chk(total("TKX") == pre15x and a15x == {lb15: Decimal("490")}, "C15 경계 대사 앵커 10 먼저(→ 0 · 지움) · 나머지 10 = 나중 대사 앵커 500 → 490", a15x)
tomb("TKW", b_a15)
post(t_open15, "TKW", "500", ns="binance:recon", sid=f"exfrecon:TKW:{lb15}", ev="EXF_ADJUST", lk="opening")
post(t_open15 + 100, "TKW", "-470", ns="binance:trade", sid="x15w", ev="EXF_SELL", lk="disp")
deliver([div(25, b_a15 - 900, "TKW", "20"), div(26, b_a15 - 800, "TKW", "40")], "c15w")
run15, mn15 = Decimal(0), Decimal(0)
for _t15, q15 in C.svc_exf._exf_series("binance", "TKW"):
    run15 += q15
    mn15 = min(mn15, run15)
chk(adj("TKW") == Decimal("470") and total("TKW") == Decimal("60") and mn15 >= 0, "C15 나중 대사 앵커도 [그 시각, 지급) 여유(30) 안에서만 · 새 음수 없음",
    (adj("TKW"), total("TKW"), mn15))

post(t_open15, "TKV", "500", ns="binance:recon", sid=f"exfrecon:TKV:{b_a15}", ev="EXF_ADJUST", lk="opening")
post(lb15, "TKV", "-5", ns="binance:recon", sid=f"exfrecon:TKV:{lb15}", ev="EXF_ADJUST", lk="opening")
pre16 = total("TKV")
deliver([div(27, b_a15 + 100, "TKV", "20")], "c16")
chk(adj("TKV") == Decimal("495") and total("TKV") == pre16 + 20 and n_late_off("TKV") == 0,
    "C16 지급 앞 대사의 앵커 500 그대로 · 뒤 대사 음수 보정 그대로 · 수입 행 20 만(못 맞춘 몫 = 다음 대사가 차이로)", (adj("TKV"), total("TKV") - pre16))

try:
    rv = C.svc_exf._exf_revert_rows()
    ok10 = any("지급 내역" in str(e.get("why")) for e in rv)
except ValueError as e10:
    ok10, rv = False, repr(e10)
chk(ok10, "C10 지급 대체 감사 줄(state/exf_recon_revert.jsonl)이 선물 이관 검사(_exf_revert_row_ok · 사유 꼴)를 통과", str(rv)[:300])

raw = C.conn.execute("SELECT payload FROM raw_ex WHERE exchange='binance' AND kind='income' AND uuid='binance:div:2'").fetchone()[0]
before = C.conn.execute("SELECT event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event FROM postings"
                        " WHERE source_ns='binance:income' AND source_id='binance:div:2'").fetchall()
C.conn.execute("DELETE FROM postings WHERE source_ns='binance:income' AND source_id='binance:div:2'")
ok5 = C.svc_exf._post_exf_income("binance", json.loads(raw))
after = C.conn.execute("SELECT event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event FROM postings"
                       " WHERE source_ns='binance:income' AND source_id='binance:div:2'").fetchall()
chk(ok5 and [tuple(r) for r in before] == [tuple(r) for r in after] and not C.svc_exf._post_exf_income("binance", json.loads(raw)),
    "C5 원본에서 다시 = 같은 줄 · 두 번째 무동작", ([tuple(r) for r in before], [tuple(r) for r in after]))
C.conn.rollback()
RB = os.path.join(T.ROOT, "tools", "rebuild2.py")
if os.path.exists(RB):
    tree = ast.parse(open(RB, encoding="utf-8").read())
    consts = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    chk(any("kind='income'" in c for c in consts) and "_post_exf_income" in attrs, "C5 rebuild2 가 raw_ex 'income' 을 같은 함수로 재파생")
C.conn.close()
T.finish()
