#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import _arch_py_ratchet as R  # noqa: E402


def U(k, m, q, v, h=None):
    u = {"k": k, "m": m, "q": q, "v": v, "t": R.unit_type(k, q)}
    if h:
        u["h"] = h
    return u


def B(k, m, q, v, h=None):
    d = {"k": k, "m": m, "q": q, "v": v}
    if h:
        d["h"] = h
    return d


seen = set()
shape = []
for row in R.SUCCESSION:
    ok = (len(row) == 4 and row[0] in R.SPECS and R.SPECS[row[0]][1] == "num"
          and all(isinstance(p, tuple) and len(p) == 2 and all(isinstance(x, str) and x for x in p) for p in row[1:3])
          and isinstance(row[3], str) and row[3].strip() and row[1] != row[2])
    if not ok or (row[0], row[2]) in seen:
        shape.append(repr(row)[:120])
    seen.add((row[0], row[2]))
T.chk(R.SUCCESSION and not shape, "[1] 승계 표 모양(개수 지표 · 두 짝 · 이유 · 새 단위 한 줄) — 틀린 줄 %d" % len(shape), shape)

K = "class.mixin_bases"
BASE = [B(K, "core", "Core", 16, "aaaa"), B(K, "core_exf", "ExfMixin", 2, "bbbb")]


def run(k, cur, base):
    return R.compare(k, cur, base, {}, ())


vd = run(K, [U(K, "core", "Core", 12, "cccc"), U(K, "core_svc", "ExfService", 4, "dddd"), U(K, "core_exf", "ExfMixin", 2, "bbbb")], BASE)
T.chk(vd.ok and len(vd.succeeded) == 1 and vd.succeeded[0][1]["q"] == "Core",
      "[2] Core 12 + ExfService 4 = 16 ≤ 16 → 승계 1 · 새 0 · 커짐 0", [len(vd.new), len(vd.grew), len(vd.succeeded)])

vd = run(K, [U(K, "core", "Core", 10, "cccc"), U(K, "core_svc", "ExfService", 4, "dddd"), U(K, "core_svc", "ReconService", 2, "eeee")], BASE)
T.chk(vd.ok and sorted(u["q"] for u, _b in vd.succeeded) == ["ExfService", "ReconService"] and not vd.new,
      "[2b] Core 10 + ExfService 4 + ReconService 2 = 16 ≤ 16 → 승계 2", [len(vd.new), len(vd.grew), len(vd.succeeded)])
vd = run(K, [U(K, "core", "Core", 11, "cccc"), U(K, "core_svc", "ExfService", 4, "dddd"), U(K, "core_svc", "ReconService", 2, "eeee")], BASE)
T.chk(not vd.ok and sorted(u["q"] for u in vd.new) == ["ExfService", "ReconService"] and not vd.succeeded,
      "[2b] 예산 넘침(11 + 4 + 2 > 16) → 두 새 단위 모두 새 위반(예산을 나눠 쓰지 않음)")

vd = run(K, [U(K, "core", "Core", 9, "cccc"), U(K, "core_svc", "ExfService", 4, "dddd"), U(K, "core_svc", "ReconService", 2, "eeee"),
             U(K, "core_svc", "PriceService", 1, "ffff")], BASE)
T.chk(vd.ok and sorted(u["q"] for u, _b in vd.succeeded) == ["ExfService", "PriceService", "ReconService"] and not vd.new,
      "[2c] Core 9 + ExfService 4 + ReconService 2 + PriceService 1 = 16 ≤ 16 → 승계 3", [len(vd.new), len(vd.grew), len(vd.succeeded)])
vd = run(K, [U(K, "core", "Core", 10, "cccc"), U(K, "core_svc", "ExfService", 4, "dddd"), U(K, "core_svc", "ReconService", 2, "eeee"),
             U(K, "core_svc", "PriceService", 1, "ffff")], BASE)
T.chk(not vd.ok and sorted(u["q"] for u in vd.new) == ["ExfService", "PriceService", "ReconService"] and not vd.succeeded,
      "[2c] 예산 넘침(10 + 4 + 2 + 1 > 16) → 세 새 단위 모두 새 위반")

vd = run(K, [U(K, "core", "Core", 13, "cccc"), U(K, "core_svc", "ExfService", 4, "dddd")], BASE)
T.chk(not vd.ok and [u["q"] for u in vd.new] == ["ExfService"] and not vd.succeeded, "[3] 예산 넘침(13 + 4 > 16) → 새 위반")
vd = run(K, [U(K, "core", "Core", 12, "cccc"), U(K, "core_svc", "ExfService", 5, "dddd")], BASE)
T.chk(not vd.ok and [u["q"] for u in vd.new] == ["ExfService"], "[3] 새 단위 5(12 + 5 > 16) → 새 위반")

vd = run(K, [U(K, "core", "Core", 12, "cccc"), U(K, "core_svc", "OtherService", 1, "eeee")], BASE)
T.chk(not vd.ok and [u["q"] for u in vd.new] == ["OtherService"], "[4] 표 밖 새 이름(OtherService) → 새 위반")
vd = run(K, [U(K, "core", "Core", 12, "cccc"), U(K, "core_x", "ExfService", 4, "dddd")], BASE)
T.chk(not vd.ok and [u["m"] for u in vd.new] == ["core_x"], "[4] 다른 모듈의 같은 이름 → 새 위반")
vd = run("class.methods", [U("class.methods", "core", "Core", 12, "cccc"), U("class.methods", "core_svc", "ExfService", 30, "dddd")],
         [B("class.methods", "core", "Core", 60, "aaaa")])
T.chk(not vd.ok and len(vd.new) == 1, "[4] 표에 없는 지표(class.methods)는 같은 짝이라도 승계 없음")
vd = run(K, [U(K, "core_svc", "ExfService", 4, "dddd")], [B(K, "core_exf", "ExfMixin", 2, "bbbb")])
T.chk(not vd.ok and len(vd.new) == 1, "[4] 옛 단위(Core)가 기준선에 없음 → 승계 없음")

C = "cfg.literal"
CB = [B(C, "core_exf", "ExfMixin.settle_planner", 2, "ffff")]
vd = run(C, [U(C, "core_svc", "exf_settle_planner", 2, "9999")], CB)
T.chk(vd.ok and len(vd.succeeded) == 1, "[5] 옛 메서드 사라짐 · 새 함수 2 ≤ 2 → 승계")
vd = run(C, [U(C, "core_svc", "exf_settle_planner", 3, "9999")], CB)
T.chk(not vd.ok and len(vd.new) == 1, "[5] 새 함수 3 > 2 → 새 위반")

two = R.SUCCESSION + ((K, ("core_exf", "ExfMixin"), ("core_svc", "ExfService"), "시험용 겹친 줄"),)
vd = R.compare(K, [U(K, "core", "Core", 12, "cccc"), U(K, "core_svc", "ExfService", 4, "dddd")], BASE, {}, (), two)
T.chk(not vd.ok and len(vd.new) == 1 and not vd.succeeded, "[1b] 한 새 단위가 두 옛 예산에 걸림 → 승계 안 함(새 위반)")

T.chk(R.succession_rows("ledger.write") == [], "[6] 집합 지표 ledger.write 는 승계 표 대상 아님")

DK, LK = "func.depth", "func.lines"
TB = ((DK, ("mod", "C.big"), ("mod", "C.p1"), "시험"), (DK, ("mod", "C.big"), ("mod", "C.p2"), "시험"),
      (LK, ("mod", "C.big"), ("mod", "C.p1"), "시험"), (LK, ("mod", "C.big"), ("mod", "C.p2"), "시험"))
RULES = {"limits": {"func.depth": 4, "func.lines": 80}}
vd = R.compare(DK, [U(DK, "mod", "C.big", 2), U(DK, "mod", "C.p1", 5), U(DK, "mod", "C.p2", 5)], [B(DK, "mod", "C.big", 5)], RULES, (), TB)
T.chk(DK in R.SUCCESSION_MAX and vd.ok and len(vd.succeeded) == 2, "[7] 깊이 5·5 ≤ 옛 5(최대) → 둘 다 승계", (vd.new, vd.succeeded))
vd = R.compare(DK, [U(DK, "mod", "C.big", 2), U(DK, "mod", "C.p1", 6), U(DK, "mod", "C.p2", 5)], [B(DK, "mod", "C.big", 5)], RULES, (), TB)
T.chk(not vd.ok and len(vd.new) == 2, "[7] 깊이 6 > 옛 5 → 새 위반(둘 다)")
vd = R.compare(LK, [U(LK, "mod", "C.big", 10), U(LK, "mod", "C.p1", 100), U(LK, "mod", "C.p2", 100)], [B(LK, "mod", "C.big", 210)], RULES, (), TB)
T.chk(vd.ok and len(vd.succeeded) == 2, "[7] 줄 수는 합: 10 + 100 + 100 ≤ 210 → 승계")
vd = R.compare(LK, [U(LK, "mod", "C.big", 10), U(LK, "mod", "C.p1", 100), U(LK, "mod", "C.p2", 100)], [B(LK, "mod", "C.big", 209)], RULES, (), TB)
T.chk(not vd.ok and len(vd.new) == 2, "[7] 줄 수 합 210 > 209 → 새 위반")

T.finish()
