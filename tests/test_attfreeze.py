#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import copy  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

import attfreeze  # noqa: E402
import histmark  # noqa: E402
import ledger_backup  # noqa: E402
import paths  # noqa: E402
import view_detail  # noqa: E402

chk = T.chk
P = paths.state(attfreeze.FILE)
TODAY = "2026-10-20"


def rows_for(today, bump=None):
    t = datetime.strptime(today, "%Y-%m-%d")
    out = []
    for i in range(30):
        d = t - timedelta(days=29 - i)
        iso = d.strftime("%Y-%m-%d")
        v = 1000.0 + d.toordinal() % 97 + (bump or {}).get(iso, 0)
        r = {"date": iso[5:], "dow": "월", "val": v, "valKrw": round(v * 1400), "usdt": 1400, "kimp": 0.5, "flow": 10.0,
             "flowTop": [["입금 TKJ", 10.0]]}
        if i:
            r["att"] = {"v": 2, "mk": 1.5, "ev": 1.5, "rz": 0.25, "top": [["TKJ", 1.0, 1.5]], "etc": [0, 0],
                        "topx": [{"sym": "TKJ", "q": 100, "p0": 1.0, "p1": 1.015}], "rest": round(v % 3, 2)}
        out.append(r)
    return out


def det_for(today):
    t = datetime.strptime(today, "%Y-%m-%d")
    return {(t - timedelta(days=k)).strftime("%Y-%m-%d"): {"mk": [["TKJ", 1.5, 1.0, 100, 1.0, 1.015]], "mkN": 1, "fl": [["입금 TKJ", 10.0, []]]}
            for k in range(1, 29)}


class B:
    pass


def disk():
    return json.load(open(P, encoding="utf-8"))


def mtime():
    return os.stat(P).st_mtime_ns


b = B()
rows = rows_for(TODAY)
rows0 = copy.deepcopy(rows)
fut = {"2026-10-10": {"rows": [["binance", "바이낸스", "TKJUSDT", 2.5, 3500, 1, 0]]}}
rep = attfreeze.update(b, rows, det_for(TODAY), fut, TODAY, now=1_000_000)
st = disk()
d = st["d"]
t0 = datetime.strptime(TODAY, "%Y-%m-%d")
want = {(t0 - timedelta(days=k)).strftime("%Y-%m-%d") for k in range(1, 29)}
chk(rep["new"] == 28 and set(d) == want, "F1 창 안 지난날 28일 기록(창 첫 행·오늘 제외)", (rep, sorted(set(d) ^ want)[:4]))
i10 = [r["date"] for r in rows].index("10-10")
r10 = d["2026-10-10"]
chk(r10["r"] == rows[i10] and r10["p"]["val"] == rows[i10 - 1]["val"] and r10["p"]["date"] == rows[i10 - 1]["date"] and r10["det"]["mkN"] == 1
    and r10["fut"]["rows"][0][2] == "TKJUSDT" and r10["at"] == 1_000_000 and "st" not in r10,
    "F1 기록 = 화면 행 그대로 · 전일 값 · 상세 · 선물 · 저장 시각", r10.get("p"))
chk(rows == rows0, "F1 입력 행 무변(표시 전용 — 값 무접촉)")
chk(st.get("_v") == 1 and isinstance(st.get("dm"), list), "F1 스키마 _v 1 · dm")

m0 = mtime()
rep = attfreeze.update(b, rows_for(TODAY, {"2026-10-15": 5.0}), det_for(TODAY), fut, TODAY, now=1_000_100)
i15 = [r["date"] for r in rows].index("10-15")
chk(rep.get("held") == 2 and not rep["wrote"] and mtime() == m0 and disk()["d"]["2026-10-15"]["r"]["val"] == rows[i15]["val"],
    "F2 내용만 바뀐 빌드(그날 + 다음 날 전일 값) = 쓰기 간격 전엔 미룸", rep)
rep = attfreeze.update(b, rows_for(TODAY, {"2026-10-15": 5.0}), det_for(TODAY), fut, TODAY, now=1_000_000 + attfreeze.WRITE_GAP_S + 1)
chk(rep["upd"] == 2 and disk()["d"]["2026-10-15"]["r"]["val"] == rows[i15]["val"] + 5.0 and disk()["d"]["2026-10-16"]["p"]["val"] == rows[i15]["val"] + 5.0,
    "F2 간격 뒤 = 창 안 날 새 값으로 덮어씀(다음 날 전일 값도)", rep)

T2 = "2026-10-21"
gone = "2026-09-22"
keep = disk()["d"][gone]
rep = attfreeze.update(b, rows_for(T2), det_for(T2), {}, T2, now=1_100_000)
chk(rep["new"] == 1 and disk()["d"][gone] == keep, "F3 창이 밀림 = 새 어제 1일 · 창 첫 행이 된 날은 마지막 값 그대로", rep)
T3 = "2026-10-22"
rep = attfreeze.update(b, rows_for(T3, {gone: 77.0}), det_for(T3), {}, T3, now=1_200_000)
chk(disk()["d"][gone] == keep and "2026-09-21" not in disk()["d"], "F3 창 밖 날 = 다른 값이 와도 그대로(동결) · 분해 한 번도 없던 날(창 첫 행만) = 기록 없음")

T4 = "2026-10-25"
rep = attfreeze.update(b, rows_for(T4), det_for(T4), {}, T4, now=1_250_000)
T3 = T4
ts = int(datetime(2026, 9, 24, 12, tzinfo=timezone(timedelta(hours=9))).timestamp())
mark_day = histmark.mark_hist_dirty(ts)
rep = attfreeze.update(b, rows_for(T3), det_for(T3), {}, T3, now=1_300_000)
dd = disk()["d"]
win_lo = (datetime.strptime(T3, "%Y-%m-%d") - timedelta(days=29)).strftime("%Y-%m-%d")
stale = sorted(k for k, v in dd.items() if v.get("st") == "s")
want_s = sorted(k for k in dd if mark_day <= k <= win_lo)
chk(stale == want_s == ["2026-09-24", "2026-09-25", "2026-09-26"] and all(dd[k]["r"]["att"] for k in stale) and all(dd[k].get("sx") == mark_day for k in stale),
    "F4 정정 표식 = 그 날 이후 기록 중 이번 빌드가 다시 안 쓴 날(창 밖 · 창 첫 행)만 '정정 전 값'(값 그대로 · sx = 표식 날)", (mark_day, stale, want_s))
chk(all("st" not in dd[k] for k in dd if k < mark_day or k > win_lo), "F4 표식 전 날·다시 쓴 창 안 날 = 무표식")
m1 = mtime()
rep = attfreeze.update(b, rows_for(T3), det_for(T3), {}, T3, now=1_300_100)
chk(rep["stale"] == 0 and not rep["wrote"] and mtime() == m1, "F4 같은 표식 두 번 = 한 번(다시 안 씀)", rep)
os.remove(paths.state(histmark.HIST_DIRTY))
rep = attfreeze.update(b, rows_for(T3), det_for(T3), {}, T3, now=1_300_200)
chk(disk()["dm"] == [] and sorted(k for k, v in disk()["d"].items() if v.get("st") == "s") == stale, "F4 표식 파일이 비어도 '정정 전 값' 유지", rep)

m2 = mtime()
b2 = B()
rep = attfreeze.update(b2, rows_for(T3), det_for(T3), {}, T3, now=1_400_000)
chk(not rep["wrote"] and mtime() == m2, "F5 재시작(새 빌더) = 같은 내용이면 다시 안 씀", rep)
got = attfreeze.read([gone, "2026-01-01", "2026-10-21"])
chk(set(got) == {gone, "2026-10-21"} and got[gone] == disk()["d"][gone], "F5 읽기 = 있는 날만 · 저장 그대로")

good = open(P, encoding="utf-8").read()
open(P, "w").write("{망가짐")
chk(attfreeze.read([gone]) == {}, "F6 손상 파일 읽기 = {}(예외 없음 — 화면은 종전 안내)")
rep = attfreeze.update(B(), rows_for(T3), det_for(T3), {}, T3, now=1_500_000)
bads = [n for n in os.listdir(paths.STATE_DIR) if n.startswith("att_frozen.json.bad_")]
chk(rep["wrote"] and len(bads) == 1 and open(os.path.join(paths.STATE_DIR, bads[0]), encoding="utf-8").read() == "{망가짐" and len(disk()["d"]) == 28,
    "F6 손상 쓰기 = 옆으로 옮겨 두고(내용 보존) 새로 시작", (rep, bads))
open(P, "w").write(good)


ts2 = int(datetime(2026, 9, 23, 12, tzinfo=timezone(timedelta(hours=9))).timestamp())
histmark.mark_hist_dirty(ts2)
bsnap = B()
attfreeze.note_marks(bsnap)
os.remove(paths.state(histmark.HIST_DIRTY))
rep = attfreeze.update(bsnap, rows_for(T3), det_for(T3), {}, T3, now=1_350_000)
chk(rep["stale"] == 1 and disk()["d"]["2026-09-23"].get("st") == "s" and bsnap.__dict__.get("_att_frz_mk") is None,
    "F4b 빌드 앞에 잡은 표식(장기 곡선이 지운 뒤) = 그 날 기록 '정정 전 값'", rep)

class Bld(view_detail.DetailApiMixin):
    ATT_DET_SPAN = 40
    ATT_DET_CAP = 100


bd = Bld()
win_det = det_for(T3)
bd._day_idx = {"builtAt": int(datetime(2026, 10, 25, 12, tzinfo=timezone(timedelta(hours=9))).timestamp()), "attDet": win_det, "attFut": {}}
res = bd.att_detail(gone, gone)
chk(res["days"].get(gone) == disk()["d"][gone]["det"] and res["frz"][gone]["r"] == disk()["d"][gone]["r"]
    and res["frz"][gone]["p"] == disk()["d"][gone]["p"] and "det" not in res["frz"][gone], "F7 창 밖 날 = 동결 상세 + frz{r, p, at}", res.get("frz", {}).get(gone, {}).keys())
s_day = stale[0]
res = bd.att_detail(s_day, s_day)
chk(res["frz"][s_day].get("st") == "s" and res["frz"][s_day].get("sx") == "2026-09-23", "F7 정정 전 값 표식도 같이(sx = 가장 이른 표식 날)")
res = bd.att_detail("2026-10-15", "2026-10-15")
chk(res["days"]["2026-10-15"] == win_det["2026-10-15"] and "frz" not in res, "F7 창 안 날 = 빌드 상세(동결 안 읽음)")
res = bd.att_detail("2026-09-01", "2026-10-15", lite=True)
chk("frz" not in res and set(res["days"]) <= set(win_det), "F7 lite(그 달 합치기) = 동결 안 실음")
dfx = disk()
dfx["d"][gone]["fut"] = {"rows": [["bybit", "바이빗", "TKJUSDT", 1.25, 1700, 1, 0]], "more": [3, 0.5, 700]}
json.dump(dfx, open(P, "w"))
res = bd.att_detail(gone, gone)
chk(res["days"][gone]["fut"][0][2] == "TKJUSDT" and res["days"][gone]["more"]["fut"] == [3, 0.5, 700], "F7 동결 선물 거래소·종목별 = 빌드 상세와 같은 자리(fut · more.fut)")
bd._day_idx = dict(bd._day_idx, attDet={})
res = bd.att_detail("2026-10-10", "2026-10-12")
chk(res["days"] == {} and "frz" not in res and "2026-10-10" in disk()["d"], "F7 분해 실패 빌드의 창 안 날 = 빈 상세(동결 기록이 있어도 안 냄)")
res = bd.att_detail("2026-01-01", "2026-01-02")
chk(res["days"] == {} and "frz" not in res, "F7 기록 없는 날 = 종전(빈 상세)")

big = {"_v": 1, "dm": [], "d": {(datetime(2025, 1, 1) + timedelta(days=i)).strftime("%Y-%m-%d"): {"r": {"val": i}, "p": {}, "at": 1} for i in range(100)}}
keep_txt = open(P, encoding="utf-8").read()
json.dump(big, open(P, "w"))
dlist = sorted(big["d"])
got3 = [attfreeze.read(dlist[a:a + 41]) for a in (0, 20, 40)]
chk(all(len(g) == 41 for g in got3), "F7b 겹친 41일 조회 3번(캐시 상한 넘음) = 매번 41일 전부", [len(g) for g in got3])
open(P, "w").write(keep_txt)

chk(paths.REG.get("att_frozen.json", (None,))[0] == "att_frozen.json" and "attfreeze" in paths.REG["att_frozen.json"][1], "F8 state 등록부")
chk("att_frozen.json" in ledger_backup.FILES_CACHE and "att_frozen.json" not in ledger_backup.FILES_STATE, "F8 정기 백업(files_<날>) 목록 · 보관본 규칙(없을 때만 되돌림)")

chk(attfreeze._bf_seqs(["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-05", "2026-09-06"]) == [["2026-09-01", "2026-09-02", "2026-09-03"], ["2026-09-05", "2026-09-06"]]
    and len(attfreeze._bf_seqs([(datetime(2026, 1, 1) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(60)])) == 3,
    "F10 조각 = 빈 날에서 끊고 앞 날 하나 겹침(29일씩)")
json.dump({"2026-08-01": {"p": {"1": 9.0}}, "2026-09-10": {"p": {"1": 8.0}}}, open(paths.state(attfreeze.BF_PX), "w"))
mp = attfreeze._bf_px({"2026-09-10": {"p": {"1": 1.0}}, "_v": 3})
chk(mp == {"2026-09-10": {"p": {"1": 1.0}}, "2026-08-01": {"p": {"1": 9.0}}}, "F10 보탬 가격표 = daily_px 에 없는 날만(있는 날은 daily_px 그대로)", mp)
CALLS = []


def fake_records(owner, conn, ctx, mats, days, now):
    CALLS.append(list(days))
    return {d: {"r": {"date": d[5:], "val": 1.0, "att": {"v": 2}}, "p": {"date": "x", "val": 1.0}, "det": {}, "st": "b", "at": int(now), "h": "x"} for d in days}


def no_flow(*a, **k):
    return {}


INJ = {"records_fn": fake_records, "flow_fn": no_flow}
store0 = disk()
keep_day = sorted(k for k in store0["d"] if k < "2026-09-26")[0]
keep_rec = store0["d"][keep_day]
bb = B()
bb.daily_px = {d: {"p": {"1": 1.0}} for d in ("2026-09-18", "2026-09-19", keep_day, "2026-09-26", "2026-09-27")}
bb.daily_px["2026-09-20"] = {"x": 1}
ctx = ({}, datetime(2026, 10, 25, 12, tzinfo=timezone(timedelta(hours=9))), {}, frozenset(), {}, None, None)
rep = attfreeze.backfill(bb, None, lambda: {}, None, now=2_000_000, **INJ)
chk(rep["n"] == 0 and not CALLS, "F10 분해 실패 빌드(ctx 없음) = 안 함")
rep = attfreeze.backfill(bb, None, lambda: {}, ctx, now=2_000_000, **INJ)
chk(rep["n"] == 0 and not CALLS, "F10 백필 완료 표식 전 = 안 함")
open(os.path.join(paths.STATE_DIR, "backfill_done"), "w").write("1")
rep = attfreeze.backfill(bb, None, lambda: {}, ctx, now=2_000_000, **INJ)
dd = disk()
chk(len(CALLS) == 1 and sorted(CALLS[0]) == ["2026-08-01", "2026-09-10", "2026-09-18", "2026-09-19"] and rep["n"] == 4 and dd["d"][keep_day] == keep_rec
    and all(dd["d"][d]["st"] == "b" for d in CALLS[0]) and dd["bf"]["v"] == attfreeze.BF_V and dd["d"]["2026-09-27"].get("st") != "b",
    "F10 창 첫 날 이하 · 가격표 있는 · 기록 없는 날만 'b'(창 첫 날은 이미 기록 · 있는 기록 무변) · 창 안 날 안 함", (CALLS, rep))
m3 = mtime()
rep = attfreeze.backfill(bb, None, lambda: {}, ctx, now=2_000_100, **INJ)
rep2 = attfreeze.backfill(B(), None, lambda: {}, ctx, now=2_000_100, **INJ)
chk(len(CALLS) == 1 and mtime() == m3 and bb.__dict__.get("_att_frz_bf") == attfreeze.BF_V, "F10 한 번 하면 다시 안 함(재시작 빌더도 · 파일 무변)", len(CALLS))
dd["bf"] = {"v": 0}
json.dump(dd, open(P, "w"))


def boom(*a, **k):
    raise RuntimeError("합성 실패")


INJ["records_fn"] = boom
bb3 = B()
bb3.daily_px = {"2026-07-01": {"p": {"1": 1.0}}}
for i in range(attfreeze.BF_TRIES + 2):
    attfreeze.backfill(bb3, None, lambda: {}, ctx, now=2_000_200 + i, **INJ)
chk(disk()["bf"].get("tries") == attfreeze.BF_TRIES and "합성 실패" in disk()["bf"].get("err", "") and len(disk()["d"]) == len(dd["d"]),
    "F10 실패 = 횟수만 남김(기록 무변) · BF_TRIES 번에서 멈춤", disk()["bf"])

bb4 = B()
gap_days = ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04"]
bb4.daily_px = {d: {"p": {"1": 1.0}} for d in gap_days}
gstore = disk()
gstore["d"]["2026-06-02"] = {"r": {"val": 1, "att": {}}, "p": {}, "at": 1}
gstore["bf"] = {"v": 0}
json.dump(gstore, open(P, "w"))
SEEN = []


def rows_probe(owner, conn, ctx, mats, days, now):
    SEEN.append(sorted(days))
    return {}


attfreeze.backfill(bb4, None, lambda: {}, ctx, now=2_100_000, records_fn=rows_probe, flow_fn=no_flow)
chk(SEEN == [["2026-06-01", "2026-06-03", "2026-06-04", "2026-08-01", "2026-09-10"]] and disk()["d"]["2026-06-02"]["at"] == 1,
    "F10 기록 있는 날 사이 날도 후보(있는 기록 무변 · 옛 세대 'b' 는 다시 계산 후보)", SEEN)
chk([d for d in attfreeze._bf_seqs(sorted({"2026-06-03", "2026-06-02", "2026-06-04"}))] == [["2026-06-02", "2026-06-03", "2026-06-04"]],
    "F10 각 날의 전일 재료가 들어가면 조각이 끊기지 않음(전일 = 이미 기록 있는 날)")

st11 = disk()
st11["d"]["2026-05-01"] = {"r": {"val": 1, "att": {}}, "p": {}, "at": 1, "st": "b"}
json.dump(st11, open(P, "w"))
RZ = {"2026-10-20": 12.5, "05-01": 3.25}
b11 = B()
rep = attfreeze.update(b11, rows_for(T3), det_for(T3), {}, T3, now=2_200_000, rzd=lambda iso: {"s": RZ.get(iso, RZ.get(iso[5:], 0.0))})
d11 = disk()["d"]
chk(rep["wrote"] and d11["2026-10-20"].get("rzd") == {"s": 12.5} and d11["2026-05-01"].get("rzd") == {"s": 3.25} and d11["2026-05-01"]["st"] == "b",
    "F11 창 안 날 = 그날 실현(rzd) 같이 · 실현 없던 복원 기록 = 이번 쓰기에 채움(st 그대로)", (rep, d11["2026-10-20"].get("rzd"), d11["2026-05-01"].get("rzd")))
res = bd.att_detail("2026-05-01", "2026-05-01")
chk(res["frz"]["2026-05-01"].get("rzd") == {"s": 3.25}, "F11 /api/att_detail frz 에 rzd")

JS = r'''import fs from 'node:fs';
const APP = fs.readFileSync(process.env.TJ_TEST_APP, 'utf8');
const cut = (a, b) => { const i = APP.indexOf(a), j = i < 0 ? -1 : APP.indexOf(b, i + 1); if (i < 0 || j < 0) throw new Error('블록을 못 찾음: ' + a.slice(0, 50)); return APP.slice(i, j); };
const B = cut('  function dayFrz(k, load) {', '  function evSkel(rows, heads) {');
const R = [], chk = (ok, msg, d) => R.push([!!ok, msg, ok ? undefined : d]);
const S = { D: { todayKey: '10-22', builtAt: 7 }, tab: 'daily' };
const num = x => (isFinite(+x) ? +x : 0);
const SENT = []; let RESP = null, RENDER = 0;
const fetch = u => { SENT.push(u); return Promise.resolve(RESP); };
const F = new Function('S', 'num', 'isoDay', 'fetch', 'onUnauthorized', 'render', B + '\nreturn { dayFrz, frzRow };')(S, num, k => '2026-' + k, fetch, () => {}, () => { RENDER++; });
const rec = { r: { date: '09-20', val: '1234.5', valKrw: 1728300, usdt: 1400, est: 30, xc: 40, att: { v: 2, mk: 1 } }, p: { date: '09-19', val: 1200, valKrw: 1680000, usdt: 1400 }, at: 99, st: 's', sx: '2026-09-18' };
RESP = { ok: true, status: 200, json: () => Promise.resolve({ ok: true, builtAt: 7, days: {}, frz: { '2026-09-20': rec } }) };
chk(F.dayFrz('09-20', true) === null && SENT.length === 1 && SENT[0] === '/api/att_detail?frz=1&date=2026-09-20', '첫 호출 = 받는 중 null · /api/att_detail?frz=1&date= 한 번(동결 행만)', SENT);
await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0));
const x = F.dayFrz('09-20', true);
chk(x && x.val === 1234.5 && x.valKrw === 1728300 && x._prev.val === 1200 && Math.abs(x.delta - 34.5) < 1e-9 && x.ap === 70 && x._frz.st === 's' && x._frz.sx === '2026-09-18' && x.att.mk === 1 && RENDER === 1,
  '받은 뒤 = 창 안 행 모양(val·valKrw·_prev·delta·근사 ap·_frz) · 다시 그림 1번', x);
chk(SENT.length === 1 && F.dayFrz('09-20') === x, '같은 빌드 = 다시 안 받음 · load 없이 = 받아 둔 것만', SENT.length);
S.D.builtAt = 8; RESP = { ok: true, status: 200, json: () => Promise.resolve({ ok: true, builtAt: 8, days: {} }) };
F.dayFrz('09-20', true); await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0));
chk(SENT.length === 2 && F.dayFrz('09-20') === null, '새 빌드에 기록 없음 = null(종전 마감 기록 없음)', SENT.length);
RESP = { ok: false, status: 500, json: () => Promise.resolve(null) };
F.dayFrz('09-21', true); await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0));
chk(F.dayFrz('09-21') === null, '실패 = null(화면 안 깨짐)');
chk(F.dayFrz('10-22', true) === null && SENT.length === 3, '오늘 = 안 받음', SENT.length);
chk(F.frzRow({ r: { date: '09-20', val: 1 }, p: { val: 1 } }) === null && F.frzRow(null) === null && F.frzRow({ r: { val: 'x', att: {} }, p: { val: 1 } }) === null, '분해 없는·깨진 기록 = null');
console.log(JSON.stringify(R));
'''
node = T.node_bin("동결 분해 화면 함수")
if node:
    env = dict(os.environ, TJ_TEST_APP=T.app_js_path())
    p = subprocess.run([node, "--input-type=module", "-"], input=JS, env=env, cwd=T.TMP, capture_output=True, text=True, encoding="utf-8", timeout=60)
    try:
        res = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        res = None
    chk(res is not None, "F9 node 화면 함수 시험이 끝까지 돌았음", (p.stdout[-400:], p.stderr[-800:]))
    for ok, msg, dd in res or []:
        chk(ok, "F9 " + msg, dd)

T.finish()
