#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
from decimal import Decimal as D  # noqa: E402

import autofix as AF  # noqa: E402

Z = (lambda t: D(0))


def sol(O, ser, t0, b0, floor=Z):
    r = AF.solve(D(O), [(t, D(q)) for t, q in ser], t0, b0, floor)
    return {k: (int(v) if isinstance(v, D) and v == v.to_integral_value() else v) for k, v in r.items()}


r = sol(-10, [(1, 20), (2, -30), (3, 30)], 0, 10)
T.chk(r == {"tau": 3, "X": 10, "U": 20, "obs_b0": 10}, "S1 s30auto1 #0 반례 = τ t3 · X 10 · U 20 (t2 궤적 = X + C = 10 − 10 = 0)", r)
T.chk(10 + (20 - 30) >= 0, "S1 t2 의 새 궤적 = 0 ≥ 바닥")

r = sol(-10, [(20, 20)], 0, 30)
T.chk((r["tau"], r["X"], r["U"], r["obs_b0"]) == (20, 0, 10, 10), "S2 첫 계획 τ 20 · X 0 · U 10 · 관측 10", r)
for late, want in ((( 10, -5), (20, 5, 10)), ((25, -15), (0, 5, 0)), ((10, -15), (20, 15, 10))):
    ser = sorted([(20, 20), late])
    O2 = 10 - sum(q for t, q in ser if t <= 30)
    r = sol(O2, ser, 0, 30)
    T.chk((r["tau"], r["X"], r["U"]) == want and r["obs_b0"] == 10, f"S2 늦은 {late[1]}@{late[0]} → τ·X·U = {want} · b0 잔고 10 그대로", r)

r = sol(5, [(5, 3), (9, -2)], 0, 10)
T.chk((r["tau"], r["X"], r["U"]) == (0, 5, 0), "S3 O ≥ 0 · 바닥 아래 없음 = τ t0 · X = O · U 0(A' 꼴)", r)
r = sol(-4, [(0, 6), (5, 1)], 0, 10)
T.chk((r["tau"], r["X"], r["U"]) == (0, 0, 4), "S3 O < 0 이지만 t0 같은 초 행이 덮음 = 바닥 아래 없음 → τ t0 · X 0 · U 4", r)
r = sol(-10, [(5, 2)], 0, 10)
T.chk(r.get("why") == "floor_end", "S4 b0 에서도 바닥 아래 = floor_end 거부", r)

st = os.path.join(T.TMP, "st_debt")
os.makedirs(st, exist_ok=True)
json.dump({"debts": {"QQQ": -30, "RRR": -5}, "loans": [{"src": "loan", "debt": ["QQQ"], "since": 100}]}, open(os.path.join(st, "exf_balances_okx.json"), "w"))
fl = AF.debt_floor_fn(st)
T.chk(fl("okx", "QQQ", 99) == 0 and fl("okx", "QQQ", 100) == D(-30) and fl("okx", "RRR", 500) == 0 and fl("bybit", "QQQ", 500) == 0,
      "S5 부채 바닥 = since 뒤 −부채 · since 앞 0 · 대출 기록 없는 부채(마진) 0 · 다른 거래소 0")
r = sol(-20, [(150, 30), (160, -25), (170, 50)], 100, 300, floor=lambda t: fl("okx", "QQQ", t))
r0 = sol(-20, [(150, 30), (160, -25), (170, 50)], 100, 300)
T.chk((r["tau"], r["X"], r["U"]) == (100, 0, 20) and (r0["tau"], r0["X"], r0["U"]) == (170, 0, 20),
      "S5 부채 바닥 −30 이면 바닥 아래 없음(τ t0) · 바닥 0 이면 마지막 바닥 아래 다음 사건 τ", (r, r0))

T.chk(AF.auto_ns("okx") == "okx:autofix" and AF.is_auto_ns("okx:autofix") and not AF.is_auto_ns("okx:recon")
      and AF.auto_sid("usdt", 123) == "exfauto:USDT:123" and AF.parse_sid("exfauto:USDT:123") == ("USDT", 123)
      and AF.parse_sid("exfrecon:USDT:1") is None and AF.receipt_key("okx", "usdt") == "autofix:okx:USDT"
      and AF.off_key("okx", "usdt") == "autofix_off:okx:USDT", "S6 행 꼴·열쇠 계약")
T.chk(AF.row_ts(20, 30) == 21 and AF.row_ts(30, 30) == 31, "S6 자동 행 시각 = τ + 1초(τ = b0 여도 — 같은 초 회복 사건 뒤 소진)")
T.chk(not AF.enabled({}) and not AF.enabled({"autofix": {}}) and not AF.enabled({"autofix": {"enabled": "true"}}) and AF.enabled({"autofix": {"enabled": True}}),
      "S6 autofix.enabled 기본 꺼짐(참 bool 만 켬)")
T.finish()
