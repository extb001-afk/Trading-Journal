#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from types import SimpleNamespace  # noqa: E402

json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(os.environ["TJ_BASE"], "config.json"), "w"))
import db as dbm  # noqa: E402
import histcurve  # noqa: E402
import paths  # noqa: E402
import view_misc  # noqa: E402
import web  # noqa: E402

chk = T.chk
KST = timezone(timedelta(hours=9))
CONN = dbm.open_db(paths.DB_PATH)
CONN.commit()
SEQ = [0]
FX = 1400.0
TODAY = "2026-10-23"
NOW = datetime(2026, 10, 23, 12, tzinfo=KST)


def put_move(ex, d, amount):
    SEQ[0] += 1
    y, m, dd = (int(v) for v in d.split("-"))
    ts = int(datetime(y, m, dd, 12, tzinfo=KST).timestamp())
    when = datetime.fromtimestamp(ts, KST).isoformat()
    pl = {"currency": "KRW", "state": "ACCEPTED" if amount > 0 else "DONE", "amount": str(abs(amount)), "fee": "0",
          "created_at": when, "done_at": when, "txid": "t%d" % SEQ[0]}
    CONN.execute("INSERT INTO raw_ex(exchange, kind, uuid, revision, payload, observed_at) VALUES (?,?,?,?,?,?)",
                 (ex, kind_of(amount), "u%d" % SEQ[0], 1, json.dumps(pl), ts))
    CONN.commit()


def kind_of(amount):
    return "deposit" if amount > 0 else "withdraw"


put_move("upbit", "2026-10-20", 1400000)
put_move("upbit", "2026-10-01", -700000)
put_move("bithumb", "2026-09-30", 2800000)
put_move("upbit", "2026-08-15", 1400000)


def shell():
    b = object.__new__(web.StateBuilder)
    b.daily, b.daily_px = {}, {}
    b.spot = SimpleNamespace(rate=FX, fx_basis=FX)
    b.px = SimpleNamespace(fx_at=lambda ms: FX)
    return b


print("[A] 30일 모드 — 종전 합 + 날짜별")
b = shell()
nf = b._daily_flows(CONN, [{"date": "10-23"}], {}, NOW, {}, rate_now=FX)
vf, vfd = b._venue_flow, b._venue_flow_day
chk(vf == {"exchange:upbit": [1000.0, 500.0], "exchange:bithumb": [2000.0, 0.0]}, "A1 _venue_flow(종전 위치별 30일 합) 그대로 · 창 밖 8/15 없음", vf)
chk(vfd == {"exchange:upbit": {"2026-10-20": [1000.0, 0.0], "2026-10-01": [0.0, 500.0]}, "exchange:bithumb": {"2026-09-30": [2000.0, 0.0]}},
    "A2 _venue_flow_day = 위치 → ISO → [들어옴, 나감](같은 금액·환율)", vfd)
chk(all(abs(sum(v[0] for v in vfd[l].values()) - vf[l][0]) < 1e-9 and abs(sum(v[1] for v in vfd[l].values()) - vf[l][1]) < 1e-9 for l in vf),
    "A3 날짜별 합 = 종전 합(같은 셈)")
chk(abs(nf.get("10-20", (0,))[0] - 1000) < 1e-6 and abs(nf.get("10-01", (0,))[0] + 500) < 1e-6, "A4 일별 순유입 응답은 종전 그대로", nf)

print("[B] 지난날 모드 — _venue_acc")
sh = object.__new__(web.StateBuilder)
sh.daily, sh.daily_px = {}, {}
sh._flow_px_delta, sh._att_fx_at, sh._att_bf = {}, None, None
sh._venue_acc = {}
hf = web.StateBuilder._daily_flows(sh, CONN, None, {}, NOW, {}, days=["2026-08-15"], dpx={"2026-08-14": {"p": {}}, "2026-08-15": {"p": {}}}, fx_day=lambda iso: FX)
chk(sh._venue_acc == {"exchange:upbit": [1000.0, 0.0]} and "_venue_flow" not in sh.__dict__ and "_venue_flow_day" not in sh.__dict__,
    "B1 _venue_acc 에 그 날들의 위치별 합(그날 마감 환율) · 30일 칸은 안 건드림", (sh._venue_acc, sorted(k for k in sh.__dict__ if "venue" in k)))
chk(abs(hf.get("2026-08-15", (0,))[0] - 1000) < 1e-6, "B1 지난날 순유입 응답은 종전 그대로", hf)
sh2 = object.__new__(web.StateBuilder)
sh2.daily, sh2.daily_px = {}, {}
sh2._flow_px_delta, sh2._att_fx_at, sh2._att_bf = {}, None, None
hf2 = web.StateBuilder._daily_flows(sh2, CONN, None, {}, NOW, {}, days=["2026-08-15"], dpx={"2026-08-14": {"p": {}}, "2026-08-15": {"p": {}}}, fx_day=lambda iso: FX)
chk(hf2 == hf and not [k for k in sh2.__dict__ if "venue" in k], "B2 _venue_acc 없는 껍데기(장기 곡선·복원) = 종전 그대로(아무것도 안 남김)")

print("[C] venue_flows_view")
NAMES = {"exchange:upbit": "업비트", "exchange:bithumb": "빗썸", "wallet:base:0xabc": "메인 지갑"}
REAL = {("exchange:upbit", "2026-10-22"): [12.5, 17500.0], ("exchange:upbit", "2026-09-01"): [-3.0, -4200.0], ("exchange:bithumb", "2026-05-05"): [8.0, 11200.0],
        ("wallet:base:0xabc", "2026-10-18"): [40.0, 56000.0]}


class FakeConn:
    def execute(self, sql, *a):
        return [("wallet:base:0xabc",), ("exchange:upbit",)]


v30 = view_misc._venue_flows30(vf, REAL, NAMES.get, NOW, keep=b, conn=FakeConn())
chk(v30 == {"days": 30, "flowOk": True, "by": {"업비트": {"in": 1000.0, "out": 500.0, "realized": 12.5, "realizedKrw": 17500},
                                                   "빗썸": {"in": 2000.0, "out": 0.0, "realized": 0.0, "realizedKrw": 0},
                                                   "메인 지갑": {"in": 0.0, "out": 0.0, "realized": 40.0, "realizedKrw": 56000}}},
    "C0 venueFlows30 응답 = 종전 그대로(keep 을 줘도)", v30)
kit = b._venue_kit
chk(isinstance(kit, dict) and kit["today"] == TODAY and kit["real"] is REAL and kit["name"] == {k: NAMES.get(k) for k in NAMES}
    and set(kit["name"]) >= {"wallet:base:0xabc", "exchange:bithumb", "exchange:upbit"}, "C0 _venue_kit = 이름표(원장 모든 위치 + 흐름·실현 위치 + 업비트·빗썸 원화 위치) · 실현 · 오늘(피클 가능)", kit and sorted(kit["name"]))
import pickle  # noqa: E402

chk(len(pickle.dumps((b._venue_kit, b._venue_flow_day))) > 10, "C0 재료가 피클된다(자식 빌드 → 부모 전달)")
b._last_out = {"fields": {"venueFlows30": v30}}
FK = {"today": TODAY, "G": {}, "skip": frozenset(), "offc": frozenset(), "rate": FX, "transit": [], "wdt": {}}
asked = []


def flow_prices(kit9, days):
    asked.append(list(days))
    return {d: {"p": {}} for d in days}


hist = SimpleNamespace(kit={"groups": {}, "fk": FK}, flow_prices=flow_prices, fx=lambda iso: FX)
c, body = view_misc.venue_flows_view(b, hist, "")
chk(c == 200 and body == dict(v30, ok=True), "C1 인자 없음 = 30일 = venueFlows30 그대로 + ok", body)
c, body = view_misc.venue_flows_view(b, hist, "days=30")
chk(c == 200 and body == dict(v30, ok=True) and not asked, "C1 days=30 도 그대로(요청 때 계산 없음)", body)
c, b7 = view_misc.venue_flows_view(b, hist, "days=7")
chk(c == 200 and b7["days"] == 7 and b7["since"] == "2026-10-17" and b7["flowOk"] and b7["flowFrom"] == "2026-09-24"
    and b7["by"] == {"업비트": {"in": 1000.0, "out": 0.0, "realized": 12.5, "realizedKrw": 17500}, "메인 지갑": {"in": 0.0, "out": 0.0, "realized": 40.0, "realizedKrw": 56000}}
    and not asked, "C2 days=7 = 창 날짜별 자르기(10/01 출금·9/30 빗썸 제외) · 요청 때 계산 없음", b7)
c, b90 = view_misc.venue_flows_view(b, hist, "days=90")
chk(c == 200 and b90["since"] == "2026-07-26" and b90["flowFrom"] == "2026-07-26" and b90["flowOk"]
    and b90["by"]["업비트"] == {"in": 2000.0, "out": 500.0, "realized": 9.5, "realizedKrw": 13300}
    and b90["by"]["빗썸"] == {"in": 2000.0, "out": 0.0, "realized": 0.0, "realizedKrw": 0}
    and b90["by"]["메인 지갑"]["realized"] == 40.0, "C3 days=90 = 창 안 + 창 밖(8/15 +$1,000 · 실제 _daily_flows 지난날 모드) · 실현 7/26~", b90)
chk(len(asked) == 1 and asked[0][0] == "2026-07-25" and asked[0][1] == "2026-07-26" and asked[0][-1] == "2026-09-23" and len(asked[0]) == 61,
    "C3 창 밖 날 = since ~ 창 전날(60일) + 전일 가격표 하루", asked and (asked[0][:2], asked[0][-1], len(asked[0])))
c, ball = view_misc.venue_flows_view(b, hist, "days=0")
chk(c == 200 and ball["days"] == 0 and ball["since"] is None and ball["flowFrom"] == histcurve.FIRST_DAY
    and ball["by"]["업비트"]["in"] == 2000.0 and ball["by"]["빗썸"]["realized"] == 8.0 and ball["by"]["빗썸"]["in"] == 2000.0
    and asked[-1][0] == (datetime.strptime(histcurve.FIRST_DAY, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d"),
    "C4 days=0 = 전체(첫날 = 장기 곡선 첫날 · 빗썸 5/5 실현 포함)", ball)
chk(view_misc.venue_flows_view(b, hist, "days=90")[1] is b90 and view_misc.venue_flows_view(b, hist, "x=1&days=0")[1] is ball and len(asked) == 2
    and set(b._venue_kit["_cache"]) == {7, 90, 0}, "C5 같은 빌드·같은 기간 = 캐시(재료 kit 안 · 다시 안 셈)")
chk(view_misc.venue_flows_view(b, hist, "days=5")[0] == 400 and view_misc.venue_flows_view(b, hist, "days=abc")[0] == 400, "C6 days 7·30·90·0 밖 = 400")


def fresh_kit():
    b._venue_kit = {k: v for k, v in b._venue_kit.items() if k != "_cache"}


fresh_kit()
c, b90b = view_misc.venue_flows_view(b, hist, "days=90")
chk(b90b is not b90 and b90b == b90 and len(asked) == 3 and "_cache" in b._venue_kit, "R3 새 빌드(새 kit) = 다시 셈(옛 캐시 안 씀) · 캐시는 kit['_cache']", len(asked))
import threading  # noqa: E402
import time  # noqa: E402

fresh_kit()
slow = SimpleNamespace(kit={"groups": {}, "fk": FK}, flow_prices=lambda kit9, days: (time.sleep(0.3), flow_prices(kit9, days))[1], fx=lambda iso: FX)
n_before, got = len(asked), []
ths = [threading.Thread(target=lambda: got.append(view_misc.venue_flows_view(b, slow, "days=90")[1])) for _ in range(4)]
for t in ths:
    t.start()
for t in ths:
    t.join()
chk(len(asked) == n_before + 1 and len(got) == 4 and all(g is got[0] for g in got) and got[0] == b90, "R4 동시 4요청 = 계산 1번 · 모두 같은 답 객체", (len(asked) - n_before, len(got)))
fresh_kit()
inwin = SimpleNamespace(kit={"groups": {}, "fk": FK, "first": "2026-10-01"}, flow_prices=flow_prices, fx=lambda iso: FX)
n_before = len(asked)
c, bw = view_misc.venue_flows_view(b, inwin, "days=0")
chk(c == 200 and bw["flowOk"] and bw["flowFrom"] == "2026-10-01" and len(asked) == n_before and bw["by"]["업비트"]["in"] == 1000.0,
    "R5 전체인데 첫 기록이 창 안 = 창 밖 계산 안 부름(경고 없음) · flowFrom = 첫 기록 날", bw)
fresh_kit()
boom = SimpleNamespace(kit={"groups": {}, "fk": FK}, flow_prices=lambda kit9, days: (_ for _ in ()).throw(RuntimeError("시험: 가격표 잠깐 실패")), fx=lambda iso: FX)
c, bp = view_misc.venue_flows_view(b, boom, "days=90")
chk(c == 200 and bp["ok"] and bp.get("partial") is True and bp["flowFrom"] == "2026-09-24" and bp["by"]["업비트"]["in"] == 1000.0
    and 90 not in b._venue_kit.get("_cache", {}), "R2 창 밖 실패 = ok + partial(창 안만 · flowFrom = 창 시작) · 성공 캐시에 안 넣음", bp)
n_before = len(asked)
c, bp2 = view_misc.venue_flows_view(b, hist, "days=90")
chk(bp2.get("partial") is None and bp2["by"]["업비트"]["in"] == 2000.0 and len(asked) == n_before + 1 and b._venue_kit["_cache"][90] is bp2,
    "R2 재료 복구 뒤 같은 빌드 재요청 = 다시 셈(partial 없음) · 이제 캐시", bp2)
fresh_kit()
dc_hist = SimpleNamespace(kit={"groups": {}, "fk": FK}, flow_prices=flow_prices, fx=lambda iso: 1300.0, st={"d": {"2026-08-15": [1000.0, 1400000.0, 0, "dc"]}})
c, bd = view_misc.venue_flows_view(b, dc_hist, "days=90")
chk(bd["by"]["업비트"]["in"] == 2000.0, "R3 dc 날 = 동결 원화/USD 비율(1,400) · hc 날 = hist.fx — 장기 곡선 flow_fx 와 같은 셈", bd["by"]["업비트"])
fresh_kit()
c, bh = view_misc.venue_flows_view(b, SimpleNamespace(kit={"groups": {}, "fk": FK}, flow_prices=flow_prices, fx=lambda iso: 1300.0, st={"d": {}}), "days=90")
chk(abs(bh["by"]["업비트"]["in"] - (1000.0 + 1400000 / 1300.0)) < 0.01, "R3 동결 행 없으면 hist.fx(1,300 → $1,076.92)", bh["by"]["업비트"])
fresh_kit()
nokit = SimpleNamespace(kit=None, flow_prices=flow_prices, fx=lambda iso: FX)
c, bn = view_misc.venue_flows_view(b, nokit, "days=90")
chk(c == 200 and bn["flowOk"] and bn["flowFrom"] == "2026-09-24" and bn["by"]["업비트"] == {"in": 1000.0, "out": 500.0, "realized": 9.5, "realizedKrw": 13300}
    and bn.get("partial") is True, "C7 장기 곡선 재료 없음 = 창 안 들어옴·나감만(flowFrom = 창 시작 · partial) · 실현은 기간 전체", bn)
b0 = shell()
chk(view_misc.venue_flows_view(b0, hist, "days=90")[1] == {"ok": True, "days": 90, "flowOk": False, "by": {}, "why": "building"}
    and view_misc.venue_flows_view(b0, hist, "")[1] == {"ok": True, "days": 30, "flowOk": False, "by": {}, "why": "building"}, "C8 빌드 전(재료 없음) = flowOk False")
b._venue_flow_day = None
fresh_kit()
c, bf = view_misc.venue_flows_view(b, hist, "days=7")
chk(bf["flowOk"] is False and bf["flowFrom"] is None and bf["by"]["업비트"]["realized"] == 12.5 and bf["by"]["업비트"]["in"] == 0.0,
    "C9 창 흐름 실패한 빌드 = flowOk False(화면 '—') · 실현은 그대로", bf)
chk(view_misc._vn_days("") == 30 and view_misc._vn_days(None) == 30 and view_misc._vn_days("days=0") == 0 and view_misc._vn_days("days=7x") is None, "C10 _vn_days 파싱")
T.finish()
