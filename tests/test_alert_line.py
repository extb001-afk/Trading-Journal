#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import time  # noqa: E402

import alert_prefs as AP  # noqa: E402
import alert_watch  # noqa: E402

chk = T.chk
t0 = int(time.time())
a = AP.alert_line("NFT_CG_SLOW", "⏳ 합성 안내", key="k1")
chk(set(a) == {"ts", "kind", "cat", "text", "key"} and a["kind"] == "NFT_CG_SLOW" and a["cat"] == "oa" and a["text"] == "⏳ 합성 안내"
    and a["key"] == "k1" and isinstance(a["ts"], int) and t0 <= a["ts"] <= int(time.time()),
    "L1 alert_line 꼴 = ts·kind·cat(cat_of)·text + 덧붙인 칸 · NFT_CG_SLOW = 기타 자산(oa)", a)
for kind in ("BIG_FLOW", "LP_RANGE_OUT", "SOMETHING_NEW"):
    x, y = AP.alert_line(kind, "t", day="2026-07-27"), alert_watch._alert(kind, "t", day="2026-07-27")
    x.pop("ts"), y.pop("ts")
    chk(x == y and x["cat"] == AP.cat_of(kind), "L2 alert_watch._alert = alert_line(%s · ts 뺀 칸 전부)" % kind, (x, y))
z = AP.alert_line("BIG_FLOW", "t", cat="custom")
chk(z["cat"] == "custom", "L3 덧붙인 칸이 기본 칸을 덮음(옛 d.update(kw) 와 같음)", z)
T.finish()
