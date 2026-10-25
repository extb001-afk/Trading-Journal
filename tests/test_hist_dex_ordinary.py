#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

import paths  # noqa: E402

json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(os.environ["TJ_BASE"], "config.json"), "w"))
import histcurve as H  # noqa: E402
from view_spot import Spot  # noqa: E402

chk = T.chk
S = paths.STATE_DIR
CA = "0x" + "ab" * 20
KEY = "base:" + CA
SP = "ca:" + KEY
DAYS = H.days_between("2026-08-01", "2026-08-19")
TODAY = "2026-08-20"
NOW = H.day_end(TODAY) - 40000
T0 = H.day_end(DAYS[0]) - 80000
MID = DAYS[9]


def ent(p):
    return {"lo": DAYS[0], "hi": DAYS[-1], "st": "ok", "p": dict(p), "src": ["geckoterminal"], "at": NOW}


def curve(name, specs):
    hc = H.HistCurve(path=os.path.join(S, name + ".json"), px_path=os.path.join(S, name + "_px.json"))
    hc.px["specs"] = json.loads(json.dumps(specs))
    hc.px["fx"] = {"lo": DAYS[0], "hi": DAYS[-1], "st": "ok", "p": dict.fromkeys(DAYS, 1400)}
    return hc


def kit_of(usdc, tok, lp):
    G = {1: {"sym": "USDC", "is_stable": True, "qty_timeline": [(T0, usdc)] if usdc else []},
         2: {"sym": "TKJ", "qty_timeline": [(T0, tok)]}}
    return H.make_kit(TODAY, G, {1: usdc, 2: tok}, set(), {2}, {}, set(), {}, {2: lp}, {2: [("base", CA)]}, [], {}, [], {})


def day_row(hc, iso):
    return next((r for r in hc.view(None)[1]["days"] if r[0] == iso), None)


spot = Spot()
spot.dex_usd[KEY] = 1.0
spot.dex_res[KEY] = 1_000_000.0
spot.dex_res_ts[KEY] = time.time()
spot.token_pairs = [("base", CA)]
spot._gt_done = {("base", CA)}
hA = curve("ordA", {SP: ent(dict.fromkeys(DAYS, 1.0))})
orig = json.loads(json.dumps(hA.px))
seen = []
for i, age in enumerate([0, 6 * 3600 + 1, 0]):
    spot.dex_ts[KEY] = time.time() - age
    lp = spot.dex_price("base", CA) or 0.0
    rep = hA.run_once(kit_of(1000.0, 2000.0, lp), cap=0, now=NOW + i * 700)
    row = day_row(hA, MID)
    seen.append((age, lp, row[1] if row else None, row[3] if row else None, sorted(hA.dexbad), len(rep.get("gfix") or ())))
chk(seen[1][1] == 0.0, "A 준비 — 21,601초 뒤 Spot 지금 시세 만료(0)", seen)
chk([x[2] for x in seen] == [3000.0, 3000.0, 3000.0], "A 신선 → 지금 시세 만료 → 신선: 과거 자산 3,000 그대로(수정 전 만료 때 1,000)", seen)
chk(all(not x[4] for x in seen), "A 믿지 않는 출처 판정 없음(수정 전 만료 때 그 출처)", seen)
chk([x[5] for x in seen[1:]] == [0, 0], "A 전환마다 굳은 날 다시 계산 없음(수정 전 19일씩)", seen)
chk(all(x[3] == 0 for x in seen), "A 모두 값이 있는 날 = 근사 0", seen)
chk(hA.px == orig, "A 과거 가격 저장본 무변", None)

hB = curve("ordB", {SP: ent(dict.fromkeys(DAYS, 1.0))})
verd = {u: H.dex_verdict(hB, kit_of(u, 2000.0, 0.0), list(DAYS)) for u in (0.0, 1000.0, 2001.0)}
chk(all(v == set() for v in verd.values()), "B 스테이블 0·1,000·2,001 모두 정상 과거 DEX 출처 그대로(수정 전 1,000 에서만 뒤집힘)", verd)

hC = curve("ordC", {SP: ent(dict.fromkeys(DAYS, 2.5))})
vals = []
for i, lp in enumerate([2.4, 0.0]):
    hC.run_once(kit_of(100.0, 2000.0, lp), cap=0, now=NOW + i * 700)
    vals.append(((day_row(hC, MID) or [None, None])[1], sorted(hC.dexbad)))
hC2 = H.HistCurve(path=hC.path, px_path=hC.px_path)
hC2.px["specs"], hC2.px["fx"] = hC.px["specs"], hC.px["fx"]
rep_c = hC2.run_once(kit_of(100.0, 2000.0, 0.0), cap=0, now=NOW + 1400)
vals.append(((day_row(hC2, MID) or [None, None])[1], sorted(hC2.dexbad)))
chk([v[0] for v in vals] == [5100.0, 5100.0, 5100.0] and all(not v[1] for v in vals) and not rep_c.get("gfix"),
    "C 지금 시세로 한 번 확인된 큰 DEX 보유 = 만료·재시작 뒤에도 그대로(5,100)", vals)

hD = curve("ordD", {SP: ent(dict.fromkeys(DAYS, 5e5))})
for lp_d, nm in ((0.0, "지금 시세 없음"), (100.0, "지금 시세의 DEX_JUMP_X 배 넘음")):
    hD.st, hD.dexbad, hD.dexcut, hD.dexlp = {"_v": H.HIST_V, "d": {}, "s": {}, "x": {}, "f": {}, "meta": {}}, set(), {}, {}
    hD.run_once(kit_of(1000.0, 2000.0, lp_d), cap=0, now=NOW)
    r = day_row(hD, MID)
    chk(hD.dexbad == {SP} and r is not None and r[1] == 1000.0 and r[3] == 1, "D 스팸 꼴(%s) = 출처 막음 · 그날 = 바탕만 · API 근사 1" % nm, (sorted(hD.dexbad), r))
r0 = day_row(hD, DAYS[0])
chk(r0 is not None and r0[1] == 1000.0 and r0[3] == 1, "D 막은 출처의 다른 날(값 빠짐)도 API 근사 1(지금 시세 추정이 없어도)", r0)

hE = curve("ordE", {})
hE.run_once(kit_of(100.0, 2000.0, 2.4), cap=0, now=NOW)
hE.px["specs"] = {SP: ent(dict.fromkeys(DAYS, 2.5))}
hE.run_once(kit_of(100.0, 2000.0, 0.0), cap=0, now=NOW + 700)
chk((day_row(hE, MID) or [None, None])[1] == 5100.0 and not hE.dexbad, "E 일봉 받기 전 본 지금 시세도 근거(받은 뒤 만료 = 그대로 5,100)", (day_row(hE, MID), sorted(hE.dexbad)))


def kit_g(lp, dg):
    k = kit_of(1000.0, 2000.0, lp)
    k["dg"] = dg
    return k


hF = curve("ordF", {SP: ent(dict.fromkeys(DAYS, 500_000.0))})
hF.run_once(kit_g(1000.0, []), cap=0, now=NOW)
f_ok = (day_row(hF, MID) or [None, None])[1]
hF.run_once(kit_g(0.0, [2]), cap=0, now=NOW + 700)
chk(f_ok == 1_000_001_000.0 and hF.dexbad == {SP} and (day_row(hF, MID) or [None, None])[1] == 1000.0 and SP not in hF.dexlp,
    "F 지금 시세가 있던 동안은 종전 예외 · 거부 뒤엔 기억 버리고 막음(바탕만)", (f_ok, sorted(hF.dexbad), day_row(hF, MID)))

pth = os.path.join(S, "ordG.json")
json.dump({"_v": H.HIST_V, "d": {}, "s": {}, "x": {}, "f": {}, "meta": {"dexlp": 1, "dexcut": "broken"}}, open(pth, "w"))
try:
    hG = H.HistCurve(path=pth, px_path=os.path.join(S, "ordG_px.json"))
    g_ok = (hG.dexlp, hG.dexcut)
    hG.px["specs"], hG.px["fx"] = {SP: ent(dict.fromkeys(DAYS, 1.0))}, {"lo": DAYS[0], "hi": DAYS[-1], "st": "ok", "p": dict.fromkeys(DAYS, 1400)}
    hG.run_once(kit_of(1000.0, 2000.0, 0.0), cap=0, now=NOW)
    g_ok = g_ok if (day_row(hG, MID) or [None, None])[1] == 3000.0 else ("실행 값", day_row(hG, MID))
except Exception as e9:   # noqa: BLE001
    g_ok = repr(e9)
chk(g_ok == ({}, {}), "G 깨진 meta dexlp·dexcut = 빈 값으로 기동 · 실행도 정상(3,000)", g_ok)

T.finish()
