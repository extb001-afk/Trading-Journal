#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import view_tax  # noqa: E402

chk = T.chk
rows = [{"sold": "2026-09-0%d" % i, "sym": "BTC", "ticker": "BTC", "ex": "업비트", "qty": 0.0, "_qty": 0.00004,
         "acq": 4.0, "disp": 4.4, "fee": 0, "rate": 1380.0, "rateSrc": "spot", "_acq": 4.0, "_disp": 4.4} for i in (1, 2, 3)]
sm = view_tax._tax_summary(rows, "2026-10-16")
chk(len(sm) == 1 and sm[0][3] == 3 and abs(sm[0][4] - 0.00012) < 1e-12, "Q1 월별 요약 수량 = 반올림 전 합(0.00012 · 종전 0)", sm)
old = [dict(r, qty=0.5) for r in rows]
for r in old:
    r.pop("_qty")
sm2 = view_tax._tax_summary(old, "2026-10-16")
chk(abs(sm2[0][4] - 1.5) < 1e-12, "Q2 _qty 없는 행 = qty 그대로", sm2)
T.finish()
