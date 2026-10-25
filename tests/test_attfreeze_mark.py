#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

import attfreeze  # noqa: E402
import histmark  # noqa: E402
import paths  # noqa: E402

chk = T.chk
P = paths.state(attfreeze.FILE)
HD = paths.state(histmark.HIST_DIRTY)
KST9 = timezone(timedelta(hours=9))
TODAY = "2026-10-23"
TM = 1_792_600_000
OLD = [(datetime(2026, 8, 1) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(17)]


def rows_for(today):
    t = datetime.strptime(today, "%Y-%m-%d")
    out = []
    for i in range(30):
        iso = (t - timedelta(days=29 - i)).strftime("%Y-%m-%d")
        r = {"date": iso[5:], "dow": "월", "val": 1000.0 + i, "valKrw": 1400000 + i, "usdt": 1400, "flow": 0.0}
        if i:
            r["att"] = {"v": 2, "mk": 1.0, "top": [["TKJ", 1.0, 1.0]], "rest": 0}
        out.append(r)
    return out


class B:
    pass


def disk():
    return json.load(open(P, encoding="utf-8"))


def put_marks(marks):
    json.dump({"from": min(m[1] for m in marks), "seq": max(m[0] for m in marks), "marks": marks}, open(HD, "w"))


def reset():
    for p in (P, HD):
        if os.path.exists(p):
            os.remove(p)


def fake_records(owner, conn, ctx, mats, days, now):
    return {d: {"r": {"date": d[5:], "val": 1.0, "att": {"v": 2}}, "p": {"date": "x", "val": 1.0}, "det": {}, "st": "b", "at": str(int(now)), "h": "x"}
            for d in days}


def no_flow(*a, **k):
    return {}


open(os.path.join(paths.STATE_DIR, "backfill_done"), "w").write("1")


def ctx_at(t):
    return ({}, datetime.fromtimestamp(t, KST9), {}, frozenset(), {}, None, None)


def build(b, t_start, t_bf, rows=None):
    attfreeze.note_marks(b)
    attfreeze.backfill(b, None, lambda: {}, ctx_at(t_start), now=t_bf, records_fn=fake_records, flow_fn=no_flow)
    return attfreeze.update(b, rows or rows_for(TODAY), {}, {}, TODAY, now=t_start)


reset()
put_marks([[1, "2026-05-01", TM]])
b = B()
b.daily_px = {d: {"p": {"1": 1.0}} for d in OLD}
rep = build(b, TM + 86_400, TM + 86_400 + 40)
dd = disk()["d"]
chk(sorted(d for d in OLD if d in dd) == OLD and all(dd[d].get("st") == "b" for d in OLD) and not any("sx" in dd[d] or "st0" in dd[d] for d in OLD)
    and rep["stale"] == 0, "M1 표식 뒤 첫 생성 빌드의 복원 기록 = 'b' 그대로('정정 전 값' 아님)", (rep, sorted({dd[d].get("st") for d in OLD if d in dd})))
chk(disk()["dm"] == [[1, "2026-05-01", TM]], "M1 표식은 처리한 것으로 남음(dm)", disk()["dm"])

reset()
put_marks([[1, "2026-05-01", TM]])
late = TM + attfreeze.MARK_SLACK_S + 1
store = {"_v": 1, "dm": [], "d": {"2026-08-01": {"r": {"val": 1, "att": {}}, "p": {}, "at": str(late), "st": "b"},
                                  "2026-08-02": {"r": {"val": 1, "att": {}}, "p": {}, "at": late},
                                  "2026-08-03": {"r": {"val": 1, "att": {}}, "p": {}, "at": float(late) + 0.5}}}
json.dump(store, open(P, "w"))
rep = attfreeze.update(B(), rows_for(TODAY), {}, {}, TODAY, now=late + 10)
dd = disk()["d"]
chk(rep["stale"] == 0 and dd["2026-08-01"]["st"] == "b" and "st" not in dd["2026-08-02"] and "st" not in dd["2026-08-03"],
    "M2 표식 시각보다 나중에 센 창 밖 기록 = 무표식(at 문자열·숫자·소수)", rep)

reset()
put_marks([[1, "2026-05-01", TM]])
store = {"_v": 1, "dm": [], "d": {
    "2026-08-01": {"r": {"val": 1, "att": {}}, "p": {}, "at": TM - 1, "st": "b"},
    "2026-08-02": {"r": {"val": 1, "att": {}}, "p": {}, "at": str(TM + attfreeze.MARK_SLACK_S)},
    "2026-08-03": {"r": {"val": 1, "att": {}}, "p": {}},
    "2026-08-04": {"r": {"val": 1, "att": {}}, "p": {}, "at": "깨짐"},
    "2026-08-05": {"r": {"val": 1, "att": {}}, "p": {}, "at": "1e309"},
    "2026-04-30": {"r": {"val": 1, "att": {}}, "p": {}, "at": TM - 1}}}
json.dump(store, open(P, "w"))
b3 = B()
rep = attfreeze.update(b3, rows_for(TODAY), {}, {}, TODAY, now=TM + 100_000)
dd = disk()["d"]
chk(rep["stale"] == 5 and all(dd[d].get("st") == "s" and dd[d].get("sx") == "2026-05-01" and dd[d].get("sxt") == TM for d in ("2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04", "2026-08-05"))
    and dd["2026-08-01"].get("st0") == "b" and "st" not in dd["2026-04-30"],
    "M3 표식 전·여유 안·at 없음·깨짐·무한대 = 's'(st0 · sx · 표식 시각 sxt) · 표식 날 전 = 무표식", (rep, {d: (v.get("st"), v.get("sxt")) for d, v in dd.items()}))
win_days = [d for d in dd if d >= "2026-09-25"]
chk(len(win_days) == 28 and all("st" not in dd[d] for d in win_days), "M3 창 안 덮어쓴 날 = 무표식(종전)")
rep = attfreeze.update(b3, rows_for(TODAY), {}, {}, TODAY, now=TM + 100_100)
chk(rep["stale"] == 0 and not rep["wrote"], "M3 같은 표식 두 번 = 한 번(종전)", rep)
put_marks([[1, "2026-05-01", TM], [2, "2026-08-02", TM + 50]])
rep = attfreeze.update(b3, rows_for(TODAY), {}, {}, TODAY, now=TM + 100_200)
dd = disk()["d"]
chk(rep["stale"] == 0 and dd["2026-08-02"]["sxt"] == TM + 50 and dd["2026-08-01"]["sxt"] == TM and disk()["dm"] == [[1, "2026-05-01", TM], [2, "2026-08-02", TM + 50]],
    "M3 이미 's' 인 날에 새 표식 = sxt 늦은 쪽 · 새로 단 수 0 · dm = 지금 표식(종전)", (rep, dd["2026-08-02"]))

reset()
put_marks([[1, "2026-05-01", TM]])
b4 = B()
b4.daily_px = {d: {"p": {"1": 1.0}} for d in OLD}
rep = build(b4, TM - 5, TM + 30)
dd = disk()["d"]
chk(rep["stale"] == 17 and all(dd[d].get("st") == "s" and dd[d].get("st0") == "b" for d in OLD),
    "M3 빌드 시작 뒤 찍힌 표식 = 이번 빌드 복원 기록도 's'(보수)", rep)
reset()
put_marks([[1, "2026-05-01", TM]])
b5 = B()
b5.daily_px = {d: {"p": {"1": 1.0}} for d in OLD}
rep = build(b5, TM + attfreeze.BUILD_SLACK_S + 1, TM + attfreeze.BUILD_SLACK_S + 60)
chk(rep["stale"] == 0 and b5.__dict__.get("_att_frz_bfd") is None, "M3 빌드 시작 = 표식 + 빌드 여유 넘음 = 이번 빌드 복원 무표식 · 빌더 속성 비움", rep)

reset()
b7 = B()
b7.daily_px = {d: {"p": {"1": 1.0}} for d in OLD}
attfreeze.note_marks(b7)
put_marks([[1, "2026-05-01", TM + 10_000]])
attfreeze.backfill(b7, None, lambda: {}, ctx_at(TM), now=TM + 30, records_fn=fake_records, flow_fn=no_flow)
rep = attfreeze.update(b7, rows_for(TODAY), {}, {}, TODAY, now=TM + 50_000)
chk(rep["stale"] == 17, "M3 복원 속성은 그 빌드 시작 시각으로 판정(뒤 빌드 시각을 쓰지 않음)", rep)

sys.path.insert(0, os.path.join(T.ROOT, "tools"))
import attfreeze_unstale as U  # noqa: E402
import contextlib  # noqa: E402
import io  # noqa: E402

AT = 1_792_683_000
live = {"_v": 1, "dm": [], "bf": {"v": 2, "at": AT + 9000, "n": 0, "want": 1, "re": 0}, "d": {}}
for d in OLD:
    live["d"][d] = {"r": {"date": d[5:], "val": 1.0, "att": {"v": 2}}, "p": {}, "det": {}, "st": "s", "st0": "b", "sx": "2026-05-01", "at": str(AT), "h": "h" + d}
for i in range(28):
    d = (datetime(2026, 9, 25) + timedelta(days=i)).strftime("%Y-%m-%d")
    live["d"][d] = {"r": {"date": d[5:], "val": 2.0, "att": {"v": 2}}, "p": {}, "at": AT + 9000, "h": "w" + d}
others = {"2026-07-01": {"r": {}, "p": {}, "st": "s", "st0": "b", "sx": "2026-05-01", "sxt": TM, "at": str(AT), "h": "x1"},
          "2026-07-02": {"r": {}, "p": {}, "st": "s", "st0": "b", "sx": "2026-05-01", "at": AT - 1, "h": "x2"},
          "2026-07-03": {"r": {}, "p": {}, "st": "s", "sx": "2026-05-01", "at": AT, "h": "x3"},
          "2026-07-04": {"r": {}, "p": {}, "st": "b", "at": AT, "h": "x4"}}
live["d"].update(others)
reset()
json.dump(live, open(P, "w"))
UND = os.path.join(T.TMP, "unstale_undo.json")


def run(*argv, running=None):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = U.main(list(argv), running=running)
    return rc, buf.getvalue()


raw0 = open(P, "rb").read()
rc, out = run("--at", str(AT))
chk(rc == 0 and "대상 17일" in out and "점검" in out and open(P, "rb").read() == raw0 and not os.path.exists(UND) and "2026-" not in out,
    "U1 점검(기본) = 건수만(날짜 없음) · 파일 무변", out)
rc, out = run("--at", str(AT), "--apply", "--undo-out", UND, "--no-proc-check")
dd = disk()
chk(rc == 0 and "대상 17일" in out and all(dd["d"][d]["st"] == "b" and "st0" not in dd["d"][d] and "sx" not in dd["d"][d] and dd["d"][d]["r"] == live["d"][d]["r"] for d in OLD)
    and all(dd["d"][d] == v for d, v in live["d"].items() if d not in OLD) and dd["bf"] == {"v": 1, "at": AT + 9000, "n": 0, "want": 1, "re": 0, "unstale": dd["bf"]["unstale"]}
    and os.path.exists(UND), "U2 적용 = 대상만 'b'(st0·sx 지움 · 값 그대로) · 나머지(sxt 있음·다른 at·st0 없음·창 안) 무변 · bf.v 1 · 되돌리기 파일", out)
rc, out = run("--at", str(AT), "--apply", "--undo-out", UND + "2", "--no-proc-check")
chk(rc == 0 and "대상 0일" in out and not os.path.exists(UND + "2"), "U3 다시 = 0(되돌리기 파일도 안 만듦)", out)
after_apply = disk()

SEEN = []


def probe(owner, conn, ctx, mats, days, now):
    SEEN.append(sorted(days))
    return {}


b6 = B()
b6.daily_px = {d: {"p": {"1": 1.0}} for d in OLD}
attfreeze.backfill(b6, None, lambda: {}, ctx_at(AT + 20_000), now=AT + 20_000, records_fn=probe, flow_fn=no_flow)
chk(SEEN == [OLD], "U4 적용 뒤 다음 빌드 = 그 17일을 옛 세대 'b' 로 다시 계산 후보", SEEN)
json.dump(after_apply, open(P, "w"))

rc, out = run("--undo", UND)
chk(rc == 0 and "되돌림 17일" in out and disk() == after_apply, "U5 되돌리기 점검 = 건수만 · 무변", out)
rc, out = run("--undo", UND, "--apply", "--no-proc-check")
chk(rc == 0 and disk() == live, "U5 되돌리기 적용 = 적용 전 저장본과 같음", out)
moved = dict(after_apply, d=dict(after_apply["d"]))
moved["d"][OLD[0]] = dict(moved["d"][OLD[0]], h="new", at=AT + 30_000)
moved["bf"] = {"v": 2, "at": AT + 30_000, "n": 1, "want": 17, "re": 1}
json.dump(moved, open(P, "w"))
rc, out = run("--undo", UND, "--apply", "--no-proc-check")
dd = disk()
chk("되돌림 16일" in out and "건너뜀 1일" in out and dd["d"][OLD[0]]["h"] == "new" and dd["d"][OLD[1]]["st"] == "s" and dd["bf"]["v"] == 2,
    "U5 그 뒤 다시 계산한 날·bf = 그대로(건너뜀)", out)

json.dump(live, open(P, "w"))
chk(U.web_running() is None, "U6 실제 판정(ps · 이 임시 설치) = 떠 있는 tj-web 없음")
raw1 = open(P, "rb").read()
rc, out = run("--at", str(AT), "--apply", "--undo-out", UND + "3", running=lambda: "먼저 tj-web 을 멈추세요: pm2 stop tj-web")
chk(rc == 2 and "pm2 stop tj-web" in out and open(P, "rb").read() == raw1 and not os.path.exists(UND + "3"), "U6 tj-web 떠 있으면 거부(무변)", out)
try:
    with contextlib.redirect_stderr(io.StringIO()):
        U.main(["--at", str(AT), "--apply", "--no-proc-check"])
    ok6 = False
except SystemExit as e:
    ok6 = e.code == 2
chk(ok6 and open(P, "rb").read() == raw1, "U6 --apply 에 되돌리기 파일 없으면 거부")

tam = json.load(open(UND, encoding="utf-8"))
for u in tam["days"].values():
    u["before"] = dict(u["before"], r={"val": 999.0}, det={"x": 1}, h="tampered")
UNDT = os.path.join(T.TMP, "unstale_undo_tampered.json")
json.dump(tam, open(UNDT, "w"))
json.dump(after_apply, open(P, "w"))
rc, out = run("--undo", UNDT, "--apply", "--no-proc-check")
dd = disk()
chk(rc == 0 and "되돌림 17일" in out and all(dd["d"][d]["r"] == live["d"][d]["r"] and dd["d"][d]["h"] == live["d"][d]["h"] and "det" in dd["d"][d]
                                             and dd["d"][d]["det"] == live["d"][d]["det"] and dd["d"][d]["st"] == "s" for d in OLD),
    "U7 조작된 되돌리기 파일의 표식 밖 키 = 무시(표식만 되돌림)", out)

import threading  # noqa: E402
import time  # noqa: E402

import fsio  # noqa: E402
import statefile  # noqa: E402

XD = "2026-06-30"


def hold_then_add(ready, hold_s=0.4):
    with fsio.locked(P):
        cur = disk()
        ready.set()
        time.sleep(hold_s)
        cur["d"][XD] = {"r": {"date": XD[5:]}, "p": {}, "at": 1, "h": "lk"}
        statefile.atomic_write_json(P, cur)


def race(fn):
    ready = threading.Event()
    th = threading.Thread(target=hold_then_add, args=(ready,))
    th.start()
    ready.wait(5)
    try:
        return fn()
    finally:
        th.join(10)


reset()
bL = B()
attfreeze.update(bL, rows_for(TODAY), {}, {}, TODAY, now=TM)
race(lambda: attfreeze.update(bL, rows_for("2026-10-24"), {}, {}, "2026-10-24", now=TM + 86_400))
dd = disk()["d"]
chk(XD in dd and "2026-10-23" in dd, "L1 빌드 끝 update 가 다른 작성자의 쓰기를 기다렸다가 다시 읽고 합침(잃지 않음)", sorted(dd)[:2])
os.remove(P)
json.dump({"_v": 1, "dm": [], "d": {}, "bf": {"v": 1}}, open(P, "w"))
bL2 = B()
bL2.daily_px = {d: {"p": {"1": 1.0}} for d in OLD}
race(lambda: attfreeze.backfill(bL2, None, lambda: {}, ctx_at(TM), now=TM, records_fn=fake_records, flow_fn=no_flow))
dd = disk()
chk(XD in dd["d"] and all(d in dd["d"] for d in OLD) and dd["bf"]["v"] == attfreeze.BF_V, "L2 복원(backfill) 저장도 같은 잠금 — 다른 작성자의 날을 잃지 않음", sorted(dd["d"])[:1])
json.dump(live, open(P, "w"))
rc, out = race(lambda: run("--at", str(AT), "--apply", "--undo-out", UND + "4", "--no-proc-check"))
dd = disk()
chk(rc == 0 and "대상 17일" in out and XD in dd["d"] and all(dd["d"][d]["st"] == "b" for d in OLD),
    "L3 1회 도구 --apply 도 같은 잠금 — 빌드 쓰기가 끝난 뒤 읽고 적용(경합 거부·잃음 없음)", out)
chk(os.path.exists(fsio.lock_path(P)), "L4 잠금 파일 = <att_frozen.json>.lock(빌드·도구 공용)")

reset()
TM2 = TM + 100_000
XOLD = [(datetime(2026, 9, 8) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(17)]
put_marks([[1, "2026-09-21", TM2]])
bX = B()
bX.daily_px = {d: {"p": {"1": 1.0}} for d in XOLD}
rep = build(bX, TM2 + 92, TM2 + 92)
XS = [d for d in XOLD if d >= "2026-09-21"]
dd = disk()["d"]
chk(rep["stale"] == len(XS) == 4 and all(dd[d]["st"] == "s" and dd[d]["st0"] == "b" and dd[d]["sxt"] == TM2 and dd[d]["sx"] == "2026-09-21" for d in XS)
    and all(dd[d]["st"] == "b" and "sxt" not in dd[d] for d in XOLD if d not in XS), "X0 재현: 표식 뒤 92초 재시작 빌드 복원 4일 = 's'(sxt · at > sxt)", rep)
xs = disk()
xs["d"].update({"2026-09-01": {"r": {}, "p": {}, "st": "s", "st0": "b", "sx": "2026-09-21", "sxt": TM2, "at": TM2 - 5, "h": "y1"},
                "2026-09-02": {"r": {}, "p": {}, "st": "s", "st0": "b", "sx": "2026-09-21", "sxt": TM2 + 1, "at": TM2 + 92, "h": "y2"},
                "2026-09-03": {"r": {}, "p": {}, "st": "s", "sx": "2026-09-21", "sxt": TM2, "at": TM2 + 92, "h": "y3"},
                "2026-09-04": {"r": {}, "p": {}, "st": "s", "st0": "b", "sx": "2026-09-21", "sxt": TM2, "at": str(TM2), "h": "y4"},
                "2026-09-05": {"r": {}, "p": {}, "st": "s", "st0": "b", "sx": "2026-09-21", "at": TM2 + 92, "h": "y5"}})
json.dump(xs, open(P, "w"))
UNDX = os.path.join(T.TMP, "unstale_undo_sxt.json")


def runx(*argv):
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            return run(*argv)
    except SystemExit as e:
        return e.code, ""


raw0 = open(P, "rb").read()
rc, out = runx("--sxt", str(TM2), "--at", str(TM2 + 92))
chk(rc == 0 and "대상 4일" in out and "점검" in out and open(P, "rb").read() == raw0 and "2026-" not in out, "X1 --sxt 점검 = 건수만 · 무변", (rc, out))
rc, out = runx("--sxt", str(TM2))
chk(rc == 2 and open(P, "rb").read() == raw0, "X1 --sxt 만(--at 없음) = 거부(복원 시각으로 한 빌드에 묶음)", rc)
rc, out = runx("--sxt", str(TM2), "--at", str(TM2 + 93))
chk(rc == 0 and "대상 0일" in out and open(P, "rb").read() == raw0, "X1 --at 같이 주면 그 빌드 시각만(불일치 = 0)", (rc, out))
rc, out = runx("--sxt", str(TM2), "--at", str(TM2 + 92), "--apply", "--undo-out", UNDX, "--no-proc-check")
dd = disk()
chk(rc == 0 and "대상 4일" in out and all(dd["d"][d]["st"] == "b" and not ({"st0", "sx", "sxt"} & set(dd["d"][d])) and dd["d"][d]["r"] == xs["d"][d]["r"]
                                         and dd["d"][d]["h"] == xs["d"][d]["h"] for d in XS)
    and all(dd["d"][d] == v for d, v in xs["d"].items() if d not in XS) and dd["bf"]["v"] == 1 and os.path.exists(UNDX),
    "X2 적용 = 그 4일만 'b'(st0·sx·sxt 지움 · 값 그대로) · 표식 전·다른 표식·st0 없음·at = sxt·sxt 없음 = 무변 · bf.v 1", (rc, out))
rc, out = runx("--sxt", str(TM2), "--at", str(TM2 + 92), "--apply", "--undo-out", UNDX + "2", "--no-proc-check")
chk(rc == 0 and "대상 0일" in out and not os.path.exists(UNDX + "2"), "X3 다시 = 0", out)
rc, out = runx("--at", str(TM2 + 92))
chk(rc == 0 and "대상 1일" in out, "X3 첫 꼴(--at · sxt 없음)은 그대로 — sxt 있는 날은 안 잡음", out)
rc, out = runx("--undo", UNDX, "--apply", "--no-proc-check")
chk(rc == 0 and "되돌림 4일" in out and disk() == xs, "X4 되돌리기 왕복 = 적용 전과 같음(sxt 복원 포함)", out)
for mk, want in (([2, "2026-09-21", TM2 - 1], 2), ([2, "2026-09-22", TM2 - 30], 2), ([2, "2026-09-25", TM2 - 1], 0), ([2, "2026-09-21", TM2 - U.OTHER_S - 1], 0)):
    json.dump(dict(xs, dm=xs["dm"] + [mk]), open(P, "w"))
    rc, out = runx("--sxt", str(TM2), "--at", str(TM2 + 92))
    chk(rc == want and ("거부" in out) == (want == 2) and json.load(open(P)) == dict(xs, dm=xs["dm"] + [mk]),
        "X6 다른 처리 표식 " + ("같이 걸림 = 거부" if want else "범위 밖(늦은 날·오래전) = 진행"), (mk, rc, out))
json.dump(xs, open(P, "w"))
rc, _o = runx("--sxt", str(TM2), "--at", str(TM2 + 92), "--apply", "--no-proc-check")
rc2, _o = runx("--sxt", str(TM2), "--at", str(TM2 + 92), "--undo", UNDX)
chk(rc == 2 and rc2 == 2 and disk() == xs, "X5 --sxt --apply 에 되돌리기 파일 없음·--undo 와 같이 = 거부", (rc, rc2))

T.finish()
