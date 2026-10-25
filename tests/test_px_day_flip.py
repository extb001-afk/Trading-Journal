#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import os  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

import histcurve as H  # noqa: E402
import view_pxfix  # noqa: E402

chk = T.chk
KST = timezone(timedelta(hours=9))
NOW = time.time()
TODAY = datetime.fromtimestamp(NOW, KST).strftime("%Y-%m-%d")
iso = lambda d: (datetime.fromtimestamp(NOW, KST) - timedelta(days=d)).strftime("%Y-%m-%d")   # noqa: E731

print("[F1] 드문 시세는 뒷날로 잇지 않는다")
pm = {iso(12): 0.02, iso(11): 0.02, iso(10): 0.02, iso(9): 0.02}
ff = H.ffill_map(pm, iso(1))
chk(set(ff) == set(pm), "F1 봉 4개 뒤 8일 조용 = 받은 범위 끝까지 보면 드문 시세 → 뒷날 잇기 없음", sorted(ff))
dense = {iso(d): 1.0 + d * 0.01 for d in range(30, 4, -1)}
ffd = H.ffill_map(dense, iso(2))
chk(all(ffd.get(iso(d)) == dense[iso(5)] for d in (4, 3, 2)), "F1 촘촘한 시세 = 종전대로 마지막 체결가를 잇는다(조용한 거래소 마켓)", [ffd.get(iso(d)) for d in (4, 3, 2)])
holes = {iso(d): 2.0 for d in range(20, 0, -1) if d % 4}
ffh = H.ffill_map(holes, iso(1))
chk(ffh.get(iso(4)) == 2.0 and ffh.get(iso(8)) == 2.0, "F1 사이사이 빈 날(거래 없는 날) = 종전대로 잇는다", [ffh.get(iso(4)), ffh.get(iso(8))])
ent = {"st": "ok", "lo": iso(40), "hi": iso(1), "p": dict(pm)}
chk(H.pmap_of(ent, iso(8)).get(iso(8)) == H.pmap_of(ent, iso(1)).get(iso(8)) is None,
    "F1 저장 항목의 같은 날 값은 조회 끝(upto)과 무관(밀도 = 받은 끝 hi 기준)", [H.pmap_of(ent, iso(8)).get(iso(8)), H.pmap_of(ent, iso(1)).get(iso(8))])
ent2 = {"st": "ok", "lo": iso(40), "hi": iso(2), "p": {k9: v9 for k9, v9 in dense.items()}}
chk(H.pmap_of(ent2, iso(3)).get(iso(3)) == H.pmap_of(ent2, iso(2)).get(iso(3)) == dense[iso(5)], "F1 촘촘한 저장 항목 = 조회 끝과 무관하게 잇기")


print("[F2] 일봉 값이 기준가와 3배 넘게 어긋나고 근거가 약하면 쓰지 않는다")


class FakeHist:
    def __init__(self):
        self.px = {"specs": {}, "fx": None}
        self.pending = False


ADDR_J, ADDR_S = "0x" + "ab" * 20, "0x" + "cd" * 20
SP_J, SP_S = f"ca:eth:{ADDR_J}", f"ca:eth:{ADDR_S}"
G = {7: {"sym": "TKJ"}, 8: {"sym": "TKS"}}
PAIRS = {7: [("eth", ADDR_J)], 8: [("eth", ADDR_S)]}
D = [iso(d) for d in range(16, 1, -1)]
LIVE_J, GT_J = 2.5e-06, 0.02
dc = H.DayClose(path=os.path.join(T.TMP, "dc_flip.json"), hist=FakeHist())
dc.st["s"][SP_J] = {"st": "ok", "n": 0, "lo": iso(50), "hi": iso(2), "src": ["geckoterminal"], "why": ["cg:no_market"], "at": int(NOW),
                    "p": {iso(12): GT_J * 0.93, iso(11): GT_J, iso(10): GT_J, iso(9): GT_J}}
dc.st["s"][SP_S] = {"st": "ok", "n": 0, "lo": iso(50), "hi": iso(2), "src": ["coingecko"], "at": int(NOW),
                    "p": {d9: 5.0 for d9 in D}}
f = dc.resolver(G, {7, 8}, {}, set(), {}, PAIRS, now=NOW)
chk(f.spec(7) == SP_J and f.spec(8) == SP_S, "F2 합성 그룹 출처 키", [f.spec(7), f.spec(8)])
try:
    rj = [f(7, iso(d), 100.0, ref=LIVE_J) for d in (11, 10, 9, 5)]
except TypeError as e9:
    rj = [("TypeError", str(e9))]
chk(rj == [(None, "none")] * 4, "F2 얇은 풀 일봉(8,000배) · 이어 붙인 값 = 쓰지 않음(근사 확정 'none')", rj)
chk(f(7, iso(10), 100.0) == (GT_J, "ok"), "F2 기준가 없이 부르면(종전 호출) = 종전대로 값", f(7, iso(10), 100.0))
try:
    rj2 = f(7, iso(10), 100.0, ref=GT_J / 2)
except TypeError as e9:
    rj2 = ("TypeError", str(e9))
chk(rj2 == (GT_J, "ok"), "F2 얇은 풀이어도 기준가와 3배 안 = 그날 마감가 그대로", rj2)
try:
    rs = f(8, iso(10), 100.0, ref=1.0)
except TypeError as e9:
    rs = ("TypeError", str(e9))
chk(rs == (5.0, "ok"), "F2 근거 강한 출처(코인게코 · 5배) = 그날 마감가 그대로(진짜로 움직인 값)", rs)
chk(f(7, iso(5), 100.0) in ((None, "none"),), "F2 마지막 봉 뒤 조용한 날(잇기 없음) = 받을 곳 없음(근사 확정)", f(7, iso(5), 100.0))
chk(abs(H.DC_SPIKE_X - 3.0) < 1e-12 if hasattr(H, "DC_SPIKE_X") else False, "F2 어긋남 배수 = 화면 '튐 주의'(ATT_SPIKE 3배)와 같은 값")


print("[F3] 근사로 동결된 지난날 재평가 — 얇은 풀 일봉으로 바꾸지 않는다")
Q_J, Q_S = 500000.0, 10.0
daily, dpx = {}, {"_v": 1}
for d9 in D:
    gj, gs = round(Q_J * LIVE_J, 4), round(Q_S * 1.0, 4)
    daily[d9] = {"val": round(1000.0 + gj + gs, 2), "g": {"7": gj, "8": gs}, "est": round(gj + gs, 2), "src": "calc"}
    dpx[d9] = {"p": {"7": LIVE_J, "8": 1.0}, "k": {}}
val0 = {d9: daily[d9]["val"] for d9 in D}
try:
    r = view_pxfix._reprice_now_days(daily, dpx, G, TODAY, NOW, f, set(), backup=lambda ts: [])
except TypeError as e9:
    r = {"err": str(e9)}
kj = [(dpx[d9].get("k") or {}).get("7") for d9 in D]
pj = [(dpx[d9].get("p") or {}).get("7") for d9 in D]
chk(all(k9 is None for k9 in kj) and all(p9 == LIVE_J for p9 in pj), "F3 TKJ 날별 가격 = 한 출처(근사) 그대로 — 'd' 로 뒤집힌 날 0", list(zip(kj, pj)))
chk(all("7" in (dpx[d9].get("dcn") or ()) for d9 in D), "F3 TKJ = 근사 확정(dcn) — 빌드마다 다시 묻지 않음", [dpx[d9].get("dcn") for d9 in D])
ks = [(dpx[d9].get("k") or {}).get("8") for d9 in D]
chk(all(k9 == "d" for k9 in ks) and all(abs(daily[d9]["g"]["8"] - 50.0) < 1e-6 for d9 in D), "F3 TKS(코인게코 · 5배) = 종전대로 그날 마감가로 재평가", ks)
dv = [round(daily[d9]["val"] - val0[d9], 2) for d9 in D]
chk(all(abs(x9 - 40.0) < 0.011 for x9 in dv), "F3 총자산 차 = TKS 재평가 몫(+$40)만 — TKJ 가짜 출렁임 0", dv)


print("[F5] 상설 감시 — 날별 가격 출처 뒤집힘")
import chk_collect  # noqa: E402
import health  # noqa: E402
dcache = {"_v": 1, "_risk_rev": "99"}
for i9, d9 in enumerate(D):
    flip = i9 in (3, 4, 5, 9, 10)
    pj9 = GT_J if flip else LIVE_J
    pk9 = "d" if flip else "live"
    dcache[d9] = {"val": 1.0, "g": {"7": round(Q_J * pj9, 4), "8": 10.0 * (1 + i9 * 0.01), "99": 5.0 * (8000 if i9 % 2 else 1)},
                  "px": {"p": {"7": pj9, "8": 1.0 + i9 * 0.01, "99": 1.0 * (8000 if i9 % 2 else 1)}, "k": {"7": pk9}}}
fn = getattr(chk_collect, "px_flip_scan", None)
res = fn(dcache, TODAY) if fn else None
chk(isinstance(res, dict) and res.get("n") == 1 and [g9[0] for g9 in res.get("top") or ()] == ["7"]
    and abs(res["top"][0][1] - (Q_J * (GT_J - LIVE_J))) < 1.0, "F5 뒤집힘 그룹 = TKJ 1개(격리 그룹 99 제외 · 꾸준한 TKS 제외) · 금액 = 수량 × 가격 차", res)
added = []
fadd = lambda *a, **k: added.append((a, k))   # noqa: E731
if hasattr(health, "_px_flip_item"):
    health._px_flip_item(fadd, {"px_flip": res}, ["tj-web"], set())
chk(added and added[-1][0][0] == "px:flip" and added[-1][0][3] == "warn", "F5 헬스 '날별 가격 뒤집힘' 주의(금액 큰 순)", added[-1:] if added else added)
bad = dict(dcache, **{D[-1]: {"px": {"p": [1]}, "g": 5}, D[-2]: "x", D[-3]: {"px": {"p": {"7": "?", "8": float("nan")}}}})
chk(fn(bad, TODAY)["n"] in (0, 1), "F5 깨진 칸(p 가 목록·항목이 글자·숫자 아닌 값) = 예외 없이 건너뜀")
added.clear()
if hasattr(health, "_px_flip_item"):
    health._px_flip_item(fadd, {"px_flip": {"n": 0, "top": []}}, ["tj-web"], set())
chk(added and added[-1][0][3] == "ok", "F5 뒤집힘 없음 = 정상", added[-1:] if added else added)

T.finish()
