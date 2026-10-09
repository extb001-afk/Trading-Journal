#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import calendar

import xparts
from xparts import carry_usd, krw_at, migrate_legacy, resolve, total_usd, tl_bad, ub_cut, upgrade_obs

chk = T.chk
FX = 1400.0


def E(m, d, h=14, mi=59, s=59):
    return calendar.timegm((2026, m, d, h, mi, s))


NOW = E(10, 9)


def src_of(ku=0.0, kb=0.0, ub=None, rest=0.0, tl_ku=(), tl_kb=(), first=None, obs=None, now=NOW, bad=None):
    return {"now": {"ts": now, "ku": ku, "kb": kb, "ub": ub or {}, "rest": rest},
            "base": {"ku": [ku, now], "kb": [kb, now]},
            "tl": {"ku": list(tl_ku) if tl_ku is not None else None, "kb": list(tl_kb) if tl_kb is not None else None},
            "first": first or {}, "obs": obs or {}, "bad": bad or {}}


def near(got, want, tol=0.01):
    return abs(got - want) <= tol


s1 = src_of(rest=10000.0, tl_kb=[(E(3, 1) - 3600, 14e6), (E(10, 1) - 3600, -14e6)], first={"rest": E(1, 1) - 86400, "kb": E(3, 1) - 3600})
chk(near(total_usd(resolve(E(2, 1), s1), FX), 10000), "R cs313 2/1 = LP 만", total_usd(resolve(E(2, 1), s1), FX))
chk(near(total_usd(resolve(E(5, 1), s1), FX), 20000), "R cs313 5/1 = LP + 빗썸", total_usd(resolve(E(5, 1), s1), FX))
chk(near(total_usd(resolve(E(9, 28), s1), FX), 20000), "R cs313 9/28 = LP + 빗썸", total_usd(resolve(E(9, 28), s1), FX))
chk(near(total_usd(resolve(E(10, 5), s1), FX), 10000), "R cs313 10/5 = LP 만", total_usd(resolve(E(10, 5), s1), FX))

s2 = src_of(rest=1500.0)
m2 = migrate_legacy(E(9, 20), 100.0, "live", FX, None, s2)
chk(near(total_usd(m2["p"], FX), 100), "R cs317 실제 마감 보존", m2)
chk(near(total_usd(resolve(E(9, 20), s2, pinned=m2["p"]), FX), 100), "R cs317 실제 마감 보존(다시 resolve)", None)
chk(all(v[1] == "snap" for v in m2["p"].values()), "R cs317 쪼갠 구성요소 = 전부 관측(snap — 다시 매기지 않음)", m2["p"])

s3 = src_of(kb=14e6, rest=10000.0, tl_kb=None)
frozen = resolve(E(9, 30), s3)
chk(near(total_usd(frozen, FX), 20000), "R cs317 동결 값", frozen)
s3["now"]["rest"] = 12000.0
chk(near(total_usd(resolve(E(9, 30), s3, pinned=frozen), FX), 20000), "R cs317 LP 바뀌어도 동결 유지", None)
chk(near(total_usd(resolve(E(9, 30), s3, pinned=resolve(E(9, 30), s3, pinned=frozen)), FX), 20000), "R cs317 캐시 무효화(다시 resolve) 뒤에도", None)

s4 = src_of(kb=14e6, ub={"QQQ": [1000.0, 2000.0]}, tl_kb=None)
p4 = resolve(E(9, 30), s4)
chk(near(100 + total_usd(p4, FX), 12100), "R cs321 매칭 전", total_usd(p4, FX))
LED = {"QQQ": [(7, [(E(9, 1), 1000.0)])]}
cut4, left4 = ub_cut(p4["ub"][0], E(9, 30), LED, lambda gid: 1000.0)
chk(near((100 + 1000 * 2.0) + total_usd(p4, FX) - cut4, 12100) and left4 == {}, "R cs321 매칭 후 = 원장 평가 + x − 빼기(이중 계상 없음)", (cut4, left4))
cut4b, left4b = ub_cut(p4["ub"][0], E(8, 30), LED, lambda gid: 0.0)
chk(cut4b == 0.0 and left4b == {"QQQ": [1000.0, 2000.0]}, "R cs321 원장이 아직 안 세는 날 = 빼지 않음", (cut4b, left4b))

s5 = src_of(ku=28e6, kb=14e6)
m5 = migrate_legacy(E(9, 10), 20000.0, "live", FX, None, s5)
chk(near(total_usd(m5["p"], FX), 30000) and m5["p"]["kb"] == [14e6, "tl"], "R cs321 옛 마감 + 빗썸 추가(출처 tl)", m5)
s5["obs"] = {"2026-09-10": {"end": E(9, 10), "rest": m5["p"]["rest"][0]}}
chk(near(total_usd(resolve(E(9, 9), s5), FX), 30000), "R cs321 장기 곡선 9/9 = 30,000", total_usd(resolve(E(9, 9), s5), FX))
chk(near(total_usd(resolve(E(9, 9), s5), FX) - total_usd(m5["p"], FX), 0), "R cs321 경계 차 0", None)
chk(near(total_usd(migrate_legacy(E(9, 10), 20000.0, "live", FX, None, s5)["p"], FX), total_usd(m5["p"], FX)), "R 이관 멱등(두 번 = 같은 값)", None)

s6 = src_of(kb=50e6, rest=20000.0, tl_kb=[(E(9, 15), 50e6)], first={"kb": E(9, 15), "rest": E(10, 1)})
chk(near(total_usd(resolve(E(1, 15), s6), FX), 0), "R K8 1/15 = 0", total_usd(resolve(E(1, 15), s6), FX))
chk(near(total_usd(resolve(E(9, 20), s6), FX), 50e6 / FX), "R K8 9/20 = 빗썸만", None)
chk(near(total_usd(resolve(E(10, 5), s6), FX), 50e6 / FX + 20000), "R K8 10/5 = 빗썸 + LP", None)
chk(resolve(E(1, 15), s6)["rest"][1] == "zero" and resolve(E(10, 5), s6)["rest"][1] == "carry", "R K8 출처(zero · carry)", None)

chk(krw_at([0.0, NOW], [(E(10, 1), 5e6)], E(9, 1)) is None, "R 이력 불완전 = None", None)
s7 = src_of(kb=0.0, rest=0.0, tl_kb=[(E(10, 1), 5e6)])
chk(resolve(E(9, 1), s7)["kb"] == [0.0, "carry"], "R 이력 불완전 → 이월(지금 값)", resolve(E(9, 1), s7)["kb"])

tl8 = [(E(9, 1), 10e6), (E(9, 20), 5e6)]
base8 = [15e6, NOW]
chk(tl_bad(base8, tl8, [(E(9, 25), 15e6)]) == 0, "S 맞는 관측 = 전부 믿음", None)
b8 = tl_bad(base8, tl8, [(E(9, 5), 7e6), (E(9, 25), 15e6)])
chk(b8 == E(9, 5), "S 어긋난 관측 = 그 시각이 불신 상한", b8)
s8 = {"now": {"ts": NOW, "kb": 15e6}, "base": {"kb": base8}, "tl": {"kb": tl8}, "bad": {"kb": b8},
      "obs": {"2026-09-05": {"end": E(9, 5), "kb": 7e6}}}
chk(resolve(E(9, 3), s8)["kb"] == [7e6, "carry"] and resolve(E(9, 22), s8)["kb"] == [15e6, "tl"], "S 불신 구간 = 이월(가까운 관측) · 그 뒤 = 되감기", None)
chk(tl_bad(base8, tl8, [(E(9, 5), 10e6 + 50_000)]) == 0, "S 작은 차(허용 안) = 믿음", None)
chk(tl_bad(None, tl8, [(E(9, 5), 1.0)]) == 0 and tl_bad(base8, None, [(E(9, 5), 1.0)]) == 0, "S 재료 없음 = 점검 안 함", None)
pin8 = {"kb": [9e6, "tl"]}
chk(resolve(E(9, 3), s8, pinned=pin8)["kb"][1] == "carry", "S 불신 구간의 옛 tl 고정값 = 이월로 내림", resolve(E(9, 3), s8, pinned=pin8))

tl9 = [(E(9, 20), 1e6), (E(10, 2), 2e6)]
chk(near(krw_at([5e6, E(9, 30)], tl9, E(10, 5)), 7e6), "T 잔고 시각 뒤 = 기준 + 그 뒤 증감", krw_at([5e6, E(9, 30)], tl9, E(10, 5)))
chk(near(krw_at([5e6, E(9, 30)], tl9, E(9, 10)), 4e6), "T 잔고 시각 앞 = 기준 − 그 뒤 증감", None)
s9 = {"now": {"ts": NOW}, "base": {}, "tl": {"kb": tl9}}
chk(resolve(E(9, 10), s9, pinned={"kb": [4e6, "tl"]})["kb"] == [4e6, "tl"], "T 기준 없음 = 전에 되감은 값 유지", None)
chk(resolve(E(9, 10), s9)["kb"] == [0.0, "carry"], "T 기준·관측 없음 = 지금 값(모름 0) 이월", None)

s10 = src_of(ku=1e6, kb=3e6, ub={"QQQ": [5.0, 50.0]}, rest=99.0, tl_kb=[(E(9, 28), 1e6)])
p10 = upgrade_obs({"kb": [2e6, "carry"], "rest": [10.0, "snap"]}, E(9, 27), s10)
chk(p10["rest"] == [10.0, "snap"] and p10["kb"] == [2e6, "tl"] and p10["ku"][1] in ("tl", "carry") and p10["ub"][1] == "carry",
    "U snap 그대로 · 낡은 빗썸 = 그날 되감기 · 못 읽은 업비트 = 채움", p10)
p10b = upgrade_obs({"kb": [2e6, "carry"]}, E(9, 27), dict(s10, tl={"ku": None, "kb": None}))
chk(p10b["kb"] == [2e6, "carry"], "U 낡은 원화 + 이력 없음 = 그 관측값 고정(이월)", p10b)

cutv, leftv = ub_cut({"ABC": [100.0, 50.0]}, E(9, 30), {"ABC": [(3, [(E(9, 1), 40.0)])]}, lambda gid: 25.0)
chk(near(cutv, 12.5) and leftv == {"ABC": [75.0, 37.5]}, "V 원장 수량(평가 수량 25 로 막힘) 비율만 뺌", (cutv, leftv))

m11 = migrate_legacy(E(9, 10), 5000.0, "calc", FX, {"QQQ": [5.0, 50.0]}, src_of(ku=1.4e6, kb=0.0, rest=123.0))
chk(m11["p"]["ub"] == [{"QQQ": [5.0, 50.0]}, "carry"] and m11["p"]["rest"] == [123.0, "carry"] and m11["p"]["ku"] == [1.4e6, "tl"],
    "W calc = 옛 합계 버리고 규칙대로(미매칭 분해만 이어받음)", m11)
m12 = migrate_legacy(E(9, 10), 10.0, "live", FX, {"QQQ": [5.0, 5000.0]}, src_of())
chk(m12["note"].startswith("분해 불가") and near(total_usd(m12["p"], FX), 10.0), "W 쪼갤 수 없는 옛 마감 = 덩어리(합계 보존)", m12)
m13 = migrate_legacy(E(9, 10), 2000.0, "live", FX, None, src_of(ku=2.8e6, kb=0.0))
chk(near(total_usd(m13["p"], FX), 2000.0) and m13["p"]["ku"] == [2.8e6, "snap"], "W 쪼개기 = 합계 그대로(업비트 원화 관측)", m13)
chk(near(carry_usd(resolve(E(9, 9), src_of(rest=7.0)), FX), 7.0), "W 이월 몫 = carry 구성요소 합", None)
chk(xparts.same(m13["p"], migrate_legacy(E(9, 10), 2000.0, "live", FX, None, src_of(ku=2.8e6, kb=0.0))["p"]), "W 같은 입력 = 같은 구성요소(결정적)", None)

ku15 = [(E(9, 1), 3e6)]
kb15 = [(E(9, 1), 1e6)]
s15 = src_of(ku=3e6, kb=1e6, tl_ku=ku15, tl_kb=kb15)
m15 = migrate_legacy(E(9, 10), 100.0, "live", FX, None, s15)
chk(m15["p"]["ku"] == [0.0, "snap"] and m15["p"]["kb"] == [1e6, "tl"], "X NK1 옛 마감 $100 · 업비트 이력 ₩300만 · 빗썸 ₩100만 → ku [0, snap] · kb [100만, tl]", m15)
chk(near(total_usd(m15["p"], FX), 100.0 + 1e6 / FX) and m15["p"]["rest"] == [100.0, "snap"], "X NK1 합계 = 옛 마감 + 빗썸 원화만(업비트 원화를 얹지 않음)",
    total_usd(m15["p"], FX))
chk("분해 불가(ku" in m15["note"] and "원화 추가(kb)" in m15["note"], "X NK1 문구 = 더한 키(kb) + 분해 불가(ku)", m15["note"])
m16 = migrate_legacy(E(9, 10), 2000.0, "live", FX, None, src_of(ku=2.8e6, kb=1.4e6, tl_ku=[(E(9, 1), 2.8e6)], tl_kb=[(E(9, 1), 1.4e6)]))
chk(m16["p"]["ku"] == [2.8e6, "snap"] and m16["p"]["kb"] == [1.4e6, "tl"] and near(total_usd(m16["p"], FX), 3000.0) and "분해 불가" not in m16["note"],
    "X NK1 업비트가 맞는 옛 마감(빗썸만 빠짐) = 업비트 관측 · 빗썸 추가(종전 그대로)", m16)
m17 = migrate_legacy(E(9, 10), 1000.0, "live", FX, None, src_of(ku=2.8e6, kb=0.0, tl_ku=[(E(9, 1), 2.8e6)], tl_kb=[]))
chk(m17["p"]["ku"] == [0.0, "snap"] and near(total_usd(m17["p"], FX), 1000.0) and "분해 불가(ku" in m17["note"] and "원화 추가" not in m17["note"],
    "X NK1 빗썸 없음 · 업비트 안 맞음 = 합계 그대로 · 분해 불가(ku)만", m17)

T.finish()
