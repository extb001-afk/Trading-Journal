#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

import paths, statefile  # noqa: E402

json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(os.environ["TJ_BASE"], "config.json"), "w"))
import histcurve as H  # noqa: E402

chk = T.chk
S = paths.STATE_DIR
KST = timezone(timedelta(hours=9))
FX = 1400.0
TODAY = "2026-08-20"
NOW = datetime(2026, 8, 20, 12, tzinfo=KST).timestamp()
CA_A, CA_B, CA_L, CA_D = "0x" + "a1" * 20, "0x" + "b2" * 20, "0x" + "c3" * 20, "0x" + "d4" * 20


def iso(d):
    return "2026-08-%02d" % d


def t(d, h=10):
    return int(datetime(2026, 8, d, h, tzinfo=KST).timestamp())


def close(a, b, tol=0.02):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


G = {1: {"sym": "USDC", "is_stable": True, "qty_timeline": [(t(1), 1_000_000.0)]},
     6: {"sym": "TKC", "qty_timeline": [(t(1), 1.0)]},
     2: {"sym": "TKA", "qty_timeline": [(t(5), 10.0), (t(12), -10.0)]},
     3: {"sym": "TKB", "qty_timeline": [(t(8), 2.0)]},
     4: {"sym": "TKL", "qty_timeline": [(t(1), 1000.0)]},
     5: {"sym": "TKD", "qty_timeline": [(t(1), 2_000_000.0)]}}
HOLD = {1: 1_000_000.0, 2: 0.0, 3: 2.0, 4: 1000.0, 5: 2_000_000.0, 6: 1.0}
CA_C = "0x" + "e5" * 20
PAIRS = {2: [("eth", CA_A)], 3: [("eth", CA_B)], 4: [("base", CA_L)], 5: [("eth", CA_D)], 6: [("eth", CA_C)]}
LIVE = {1: 1.0, 2: 0.0, 3: 0.0, 4: 0.05, 5: 2.0, 6: 0.0}
DAYS = H.days_between(iso(1), iso(19))
L_PX = {d9: 0.001 * (50 ** (i / (len(DAYS) - 1))) for i, d9 in enumerate(DAYS)}
D_PX = {d9: 1.0 + i / (len(DAYS) - 1) for i, d9 in enumerate(DAYS)}


def ent(p):
    return {"st": "ok", "n": 0, "lo": iso(1), "hi": iso(19), "p": dict(p), "src": ["geckoterminal"], "why": ["cg:no_market"], "at": int(NOW) - 60}


SPECS = {f"ca:eth:{CA_A}": ent({iso(5): 5e8, iso(6): 5e8, iso(7): 5e8}),
         f"ca:eth:{CA_B}": ent({iso(9): 3e10, iso(10): 3e10, iso(11): 1.2, iso(12): 1.2, iso(13): 1.2}),
         f"ca:base:{CA_L}": ent(L_PX),
         f"ca:eth:{CA_D}": ent(D_PX),
         f"ca:eth:{CA_C}": ent({iso(2): 5e7, iso(3): 5e7, iso(4): 5e7, iso(15): 1e5, iso(16): 1e5, iso(17): 1e5})}


def kit():
    return H.make_kit(TODAY, G, HOLD, set(), {2, 3, 4, 5, 6}, {}, set(), {}, LIVE, PAIRS, [], {}, [], {})


def expect(d9):
    return 1_000_000.0 + 1000.0 * L_PX[d9] + 2_000_000.0 * D_PX[d9]


def fresh(name, pre=None):
    pth, pxp = os.path.join(S, name + ".json"), os.path.join(S, name + "_px.json")
    if pre is not None:
        statefile.atomic_write_json(pth, pre)
    hc = H.HistCurve(path=pth, px_path=pxp)
    hc.px["specs"] = json.loads(json.dumps(SPECS))
    hc.px["fx"] = {"lo": iso(1), "hi": iso(19), "st": "ok", "p": {d9: FX for d9 in DAYS}}
    return hc


mix = {"st": "ok", "p": {iso(1): 2.0, iso(2): 2.1, iso(3): 5000.0, iso(4): 2.2}, "src": ["coingecko", "geckoterminal"],
       "ps": {iso(1): "coingecko", iso(2): "geckoterminal", iso(3): "geckoterminal", iso(4): "geckoterminal"}}
CUT = getattr(H, "dex_spike_cut", lambda e, bad=False: (e, set()))
cut_m = CUT(mix)
chk(cut_m[1] == {iso(3)} and cut_m[0]["p"].get(iso(1)) == 2.0, "B 출처 섞인 항목 = DEX 날 중 튄 날만(코인게코 날 그대로)", cut_m[1])
chk(CUT(mix, bad=True)[1] == {iso(2), iso(3), iso(4)}, "A 믿지 않는 출처 = DEX 날 전부 · 코인게코 날은 남김", CUT(mix, bad=True)[1])
amb = {"st": "ok", "p": {iso(1): 2.0, iso(2): 2.1, iso(3): 5000.0, iso(4): 2.2}, "src": ["coingecko", "geckoterminal"]}
chk(CUT(amb)[1] == {iso(3)} and CUT(amb, bad=True)[1] == {iso(3)}, "B 날 출처 모름('?') 옛 항목도 튄 날은 뺌 · A 는 확인된 DEX 날만 더함(코인게코일 수 있는 날 안 뺌)",
    (CUT(amb)[1], CUT(amb, bad=True)[1]))
amb2 = dict(amb, ps={iso(4): "geckoterminal"})
chk(CUT(amb2, bad=True)[1] == {iso(3), iso(4)}, "R6 A 판정이 켜져도 B 로 뺀 출처 모름 튄 날은 그대로 뺌(되살아나지 않음) + 확인된 DEX 날", CUT(amb2, bad=True)[1])
den = {"st": "ok", "lo": iso(1), "hi": "2026-08-24", "src": ["coingecko", "geckoterminal"],
       "p": {**{iso(x): 1.0 for x in range(1, 5)}, **{iso(x): 1.0 for x in range(8, 12)}, **{iso(x): 5000.0 for x in range(12, 16)}},
       "ps": {**{iso(x): "coingecko" for x in range(1, 5)}, **{iso(x): "geckoterminal" for x in range(8, 16)}}}
pm_den = H.pmap_of(CUT(den)[0], "2026-08-24")
chk([pm_den.get(iso(x)) for x in (5, 6, 7)] == [1.0, 1.0, 1.0] and all(pm_den.get(iso(x)) != 5000.0 for x in range(12, 16)),
    "R9 튄 봉을 빼도 잇기 밀도는 가드 전 그대로 — 코인게코 정상 잇기 날(8/5~7)이 '가격 없음'이 되지 않음 · 튄 값은 안 나옴",
    [pm_den.get(iso(x)) for x in range(5, 16)])
cg_only = {"st": "ok", "p": {iso(1): 1.0, iso(2): 9e9}, "src": ["coingecko"]}
chk(CUT(cg_only)[0] is cg_only and CUT(cg_only, bad=True)[0] is cg_only, "DEX 표기 없는 항목 = 원본 그대로(튀어도 — 이 가드 범위 밖)", None)

k1 = kit()
chk(k1["first"] == iso(1) and H.spec_of(k1["groups"][2]) == f"ca:eth:{CA_A}", "준비 — 첫날 8/1 · 스팸 A 출처 키", (k1["first"], H.spec_of(k1["groups"][2])))
H1 = fresh("dsA")
rep1 = H1.run_once(k1, cap=0, now=NOW)
d1 = H1.st.get("d") or {}
chk(rep1.get("spike") == [], "진단 — 가드 뒤 튄 날 없음", rep1.get("spike"))
chk(all(close((d1.get(iso(x)) or [None])[0], expect(iso(x))) for x in (5, 6, 7)),
    "A 봉 하나짜리 엉터리 DEX 값(토큰당 5억 달러 · 10개) = 그날 가격 모름 — 총자산 = 바탕 + 정상 토큰(수정 전 50억 달러 터짐)",
    [(d1.get(iso(x)) or [None])[0] for x in (5, 6, 7)])
chk(all(close((d1.get(iso(x)) or [None])[0], expect(iso(x))) for x in (9, 10)),
    "B 아래 중앙값의 DEX_JUMP_X 배 넘게 튄 날(토큰당 300억 · 2개) = 그날 가격 모름(수정 전 600억 달러 터짐)", [(d1.get(iso(x)) or [None])[0] for x in (9, 10)])
chk(all(close((d1.get(iso(x)) or [None])[0], expect(iso(x))) for x in (2, 3, 4, 15, 16, 17)),
    "G 떨어진 두 봉(토큰당 5천만 → 10만 · 1개) — 큰 봉이 바탕보다 커 출처 전체 믿지 않음 · 작은 봉 날(바탕의 몇 %)도 가격 모름", [(d1.get(iso(x)) or [None])[0] for x in (2, 15)])
chk(all(close((d1.get(iso(x)) or [None])[0], expect(iso(x)) + 2 * 1.2) for x in (11, 12, 13)),
    "B 튄 날 뒤 정상 값(1.2 · 2개)은 그대로 셈", [(d1.get(iso(x)) or [None])[0] for x in (11, 12, 13)])
chk(all(close((d1.get(d9) or [None])[0], expect(d9) + (2 * 1.2 if "11" <= d9[-2:] <= "13" else 0.0)) for d9 in DAYS if d9[-2:] not in ("02", "03", "04", "05", "06", "07", "09", "10", "15", "16", "17")),
    "C·D 정상 DEX 토큰(50배 오름)·지금 시세로 확인된 큰 DEX 보유(바탕보다 큼)는 그대로(오탐 0)", None)
s1 = H1.st.get("s") or {}
chk([(s1.get(iso(x)) or [0, 0, 0, None])[3] for x in (5, 9, 18)] == [2, 3, 2],
    "A·B 가격 모름 날 = 빠진 그룹(8/5 = A·C · 8/9 = B + 값 없는 A·C · 8/18 = 값 없는 B·C — 지금 시세 0 이라 근사 몫 0 · 종전 규칙)", [(s1.get(iso(x)) or [None])[:4] for x in (5, 9, 18)])
fp1 = H1.flow_prices(k1, [iso(5), iso(9), iso(12), iso(15)])
chk("2" not in fp1[iso(5)]["p"] and "3" not in fp1[iso(9)]["p"] and close(fp1[iso(12)]["p"].get("3"), 1.2) and "4" in fp1[iso(5)]["p"]
    and "6" not in fp1[iso(15)]["p"], "E 입출금 가격표도 같은 가드(스팸 A 8/5 · B 8/9 · C 8/15 가격 없음 · B 8/12 정상 · L 그대로)", {k9: v9["p"] for k9, v9 in fp1.items()})
H1b = H.HistCurve(path=H1.path, px_path=H1.px_path)
H1b.px["specs"] = json.loads(json.dumps(SPECS))
H1b.px["fx"] = H1.px["fx"]
chk(getattr(H1b, "dexbad", None) == {f"ca:eth:{CA_A}", f"ca:eth:{CA_C}"} and "6" not in H1b.flow_prices(k1, [iso(15)])[iso(15)]["p"],
    "G 믿지 않는 DEX 출처 판정은 저장(meta dexbad) — 재시작 뒤 첫 실행 전 읽기 길도 같음", getattr(H1b, "dexbad", None))

G0 = {gid: G[gid] for gid in (2, 4)}
k0 = H.make_kit(TODAY, G0, {2: 0.0, 4: 1000.0}, set(), {2, 4}, {}, set(), {}, {**LIVE, 4: 0.0}, PAIRS, [], {}, [], {})
VERD = getattr(H, "dex_verdict", lambda hc, kit, days: None)
chk(VERD(fresh("ds0"), k0, list(H.days_between(iso(1), iso(19)))) == set(), "A 바탕 0 이면 판정 안 함(지금 시세를 본 적 없는 DEX 토큰만 가진 사용자)", None)
k0b = H.make_kit(TODAY, G0, {2: 0.0, 4: 1000.0}, set(), {2, 4}, {}, set(), {}, LIVE, PAIRS, [], {}, [], {})
chk(VERD(H1, k0b, list(H.days_between(iso(1), iso(19)))) == {f"ca:eth:{CA_A}"},
    "A 지금 시세로 확인된 DEX 보유(L)는 바탕에 셈 → 그보다 큰 스팸 A 는 판정", None)

G6 = {1: {"sym": "USDC", "is_stable": True, "qty_timeline": [(t(1), 1000.0)]}, 8: {"sym": "USDT", "is_stable": True, "qty_timeline": [(t(1), -1000.0)]},
      2: G[2]}
k6 = H.make_kit(TODAY, G6, {1: 1000.0, 8: -1000.0, 2: 0.0}, set(), {2}, {}, set(), {}, LIVE, PAIRS, [], {}, [], {}, neg_ok={8})
chk(VERD(H1, k6, list(H.days_between(iso(1), iso(19)))) == set(), "R5 부채(음수)로 바탕 0 = 판정 안 함(절댓값으로 바탕을 부풀리지 않음)", None)

rows, covs, xs = {}, {}, {}
for d9 in DAYS:
    v9 = expect(d9) + (2 * 1.2 if "11" <= d9[-2:] <= "13" else 0.0)
    if d9[-2:] in ("05", "06", "07"):
        v9 += 10 * 5e8
    if d9 == iso(18):
        v9 = 1234567.0
    rows[d9] = [v9, round(v9 * FX), 0, "hc", 0]
    covs[d9] = [v9, 0.0, 0.0, 0, 0.0]
    xs[d9] = {"p": {"ku": [0.0, "snap"], "kb": [0.0, "snap"], "ub": [{}, "snap"], "rest": [0.0, "snap"]}, "fx": FX, "cut": 0.0, "x": 0.0, "xc": 0.0,
              "uat": H.day_end(d9) - 1}
pre = {"_v": H.HIST_V, "d": rows, "s": covs, "x": xs, "f": {d9: [0.0, 0.0, None, "hc"] for d9 in DAYS}, "fv": H.FLOW_V,
       "meta": {"pending": False, "flow_pending": False, "updated": int(NOW) - 600}}
H2 = fresh("dsF", pre)
H2.run_once(k1, cap=0, now=NOW)
d2 = H2.st.get("d") or {}
chk(all(close((d2.get(iso(x)) or [None])[0], expect(iso(x))) for x in (5, 6, 7)),
    "F 엉터리 값으로 굳은 hc 행(8/5~8/7) = 배포 뒤 첫 실행에 다시 계산(바탕 + 정상 토큰)", [(d2.get(iso(x)) or [None])[0] for x in (5, 6, 7)])
chk(close((d2.get(iso(18)) or [None])[0], 1234567.0), "F 가드와 무관한 hc 행(8/18 — 그날 수량 있는 그룹 값이 가드로 안 바뀜)은 다시 계산 안 함(값 그대로)",
    d2.get(iso(18)))
gk = (H2.st.get("meta") or {}).get("gk")
chk(isinstance(gk, list) and gk[:1] == [getattr(H, "GUARD_V", None)], "F 가드 확인 표식(meta gk) 저장", gk)
st2 = H2.st
st2["d"] = dict(st2["d"], **{iso(5): [5e9, None, 0, "hc", 0]})
st2["s"] = dict(st2["s"], **{iso(5): [5e9, 0.0, 0.0, 0, 0.0]})
rep2 = H2.run_once(k1, cap=0, now=NOW + 700)
chk(close(((H2.st.get("d") or {}).get(iso(5)) or [None])[0], 5e9), "F 두 번째 실행 = 다시 보지 않음(1회)", (H2.st.get("d") or {}).get(iso(5)))
chk(rep2.get("spike") == [iso(5)], "진단 — 앞뒤 날의 SPIKE_WARN_X 배 넘게 튄 창 밖 날 = 실행 보고·경고 로그", rep2.get("spike"))
st3 = H2.st
st3["meta"] = dict(st3.get("meta") or {}, updated=int(NOW) + 900)
statefile.atomic_write_json(H2.path, st3)
H3 = fresh("dsF")
H3.run_once(k1, cap=0, now=NOW + 1000)
chk(close(((H3.st.get("d") or {}).get(iso(5)) or [None])[0], expect(iso(5))), "F 옛 판이 그 사이 실행했으면(meta updated ≠ gk) 다시 봄 → 교정",
    (H3.st.get("d") or {}).get(iso(5)))

f3 = H3.st.get("f") or {}
chk(all(iso(x) not in f3 for x in (5, 6, 7, 8)) and iso(14) in f3,
    "F 입출금 = 가드로 값이 바뀐 날과 그다음 날(마감 수량 0 인 전량 전송 날 포함)의 hc 입출금도 버림 · 무관한 날(8/14) 그대로", sorted(set(DAYS) - set(f3)))

H4 = fresh("dsR1")
H4.run_once(k1, cap=0, now=NOW)
st4 = H4.st
st4["d"] = dict(st4["d"], **{iso(15): [3e5 + expect(iso(15)), None, 0, "hc", 0]})
st4["s"] = dict(st4["s"], **{iso(15): [3e5 + expect(iso(15)), 0.0, 0.0, 0, 0.0]})
st4["meta"] = dict(st4["meta"], dexbad=[], dexcut={})
statefile.atomic_write_json(H4.path, st4)
H4 = fresh("dsR1")


def boom(*_a, **_k):
    raise RuntimeError("시험 — 저장 전 실패")


H4._compute = boom
try:
    H4.run_once(k1, cap=0, now=NOW + 60)
except RuntimeError:
    pass
del H4._compute
H4.run_once(k1, cap=0, now=NOW + 120)
chk(close(((H4.st.get("d") or {}).get(iso(15)) or [None])[0], expect(iso(15))), "R1 판정 바뀐 실행이 저장 전 실패 → 다음 실행이 교정(실행 중 판정이 아니라 저장본과 비교)",
    (H4.st.get("d") or {}).get(iso(15)))

CA_E = "0x" + "f6" * 20
G5 = {1: G[1], 7: {"sym": "TKE", "qty_timeline": [(t(1), 1.0)]}}
k5 = H.make_kit(TODAY, G5, {1: 1_000_000.0, 7: 1.0}, set(), {7}, {}, set(), {}, {1: 1.0, 7: 0.0}, {7: [("eth", CA_E)]}, [], {}, [], {})
H5 = fresh("dsR2")
H5.px["specs"] = {f"ca:eth:{CA_E}": ent({iso(5): 1e5})}
H5.run_once(k5, cap=0, now=NOW)
chk(close(((H5.st.get("d") or {}).get(iso(5)) or [None])[0], 1_100_000.0), "R2 준비 — 봉 하나(바탕의 10%) = 가드 통과(값 그대로)", (H5.st.get("d") or {}).get(iso(5)))
H5.px["specs"][f"ca:eth:{CA_E}"]["p"].update({iso(10): 1.0, iso(11): 1.0})
H5.run_once(k5, cap=0, now=NOW + 60)
chk(close(((H5.st.get("d") or {}).get(iso(5)) or [None])[0], 1_000_000.0), "R2 새 값으로 아래 중앙값 1 → 8/5(10만) 튄 날 = 굳은 hc 행 다시 계산(가드 상태 meta dexcut 비교)",
    (H5.st.get("d") or {}).get(iso(5)))

H8 = fresh("dsR8")
H8.px["specs"] = {f"ca:eth:{CA_E}": ent({iso(5): 20_000_000.0})}
H8.run_once(k5, cap=0, now=NOW)
chk(close(((H8.st.get("d") or {}).get(iso(5)) or [None])[0], 1_000_000.0), "R8 준비 — 바탕의 DEX_SHARE_X 배 넘는 DEX 값(지금 시세 없음) = (A) 판정", (H8.st.get("d") or {}).get(iso(5)))
st8 = H8.st
st8["meta"] = dict(st8["meta"], updated=int(NOW) + 300)
statefile.atomic_write_json(H8.path, st8)
H8 = fresh("dsR8")
H8.px["specs"] = {f"ca:eth:{CA_E}": ent({iso(5): 20_000_000.0})}
k8 = H.make_kit(TODAY, G5, {1: 1_000_000.0, 7: 1.0}, set(), {7}, {}, set(), {}, {1: 1.0, 7: 20000.0}, {7: [("eth", CA_E)]}, [], {}, [], {})
H8.run_once(k8, cap=0, now=NOW + 600)
chk(close(((H8.st.get("d") or {}).get(iso(5)) or [None])[0], 21_000_000.0), "R8 롤백 복귀 + 가드 풀림(지금 시세 생김) = 저장 상태와 비교해 굳은 행 되돌림",
    (H8.st.get("d") or {}).get(iso(5)))

H7 = fresh("dsR7")
H7.px["specs"] = {f"ca:eth:{CA_E}": ent({iso(x): 5e8 for x in range(1, 16)})}
f7 = {iso(x): [0.0, 0.0, None, "hc"] for x in range(1, 20)}
H7.st = {"meta": {}}
r7 = H.guard_hits(H7, k5, [], {}, {f"ca:eth:{CA_E}": [iso(x) for x in range(1, 16)]}, iso(19))
chk(iso(18) in r7[1] and iso(19) in r7[1], "R7 행이 없어도(ck 빈) 잇기 날(8/16~8/19) 입출금 다시 셀 날에 듦", r7)

T.finish()
