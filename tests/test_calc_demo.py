#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

from datetime import datetime, timedelta

import demo_data
import wow
import wow2
import onboarding

chk = T.chk

B = onboarding.DemoBuilder()
h = wow.habits(getattr(B, "_day_idx", None))
chk(h.get("ok") and h["n"] >= 50 and sum(1 for row in h["grid"] for c in row if c[0]) >= 20, "D1 데모 습관 = 채워짐(묶음 50+ · 칸 20+)", (h.get("ok"), h.get("n"), h.get("why")))
f = demo_data.build()["fields"]
iso = (datetime.now(wow2.KST) - timedelta(days=5)).strftime("%Y-%m-%d")
t = wow2.tm(iso, hist=None, daily=getattr(B, "daily", None), fields=f, conn=demo_data.ledger(), chain_names=demo_data.CHAIN_NAME,
            now_px={k: float(g.get("ov") or 0) for k, g in demo_data.DemoHist().kit["groups"].items()})
chk(t.get("ok") and len(t["items"]) >= 5 and not any(str(i["sym"]).startswith("#") for i in t["items"]), "D2 데모 타임머신 = 그날 보유(심볼 이름)", (t.get("ok"), t.get("error"), [i["sym"] for i in t.get("items") or []][:6]))
chk(t.get("fx") and t.get("totalKrw") and t["flows"]["miss"] == 0, "D2 그날 환율 원화 · 기간 입출금(모르는 날 0)", (t.get("fx"), t.get("flows")))
fl = wow2.flows(f, conn=demo_data.ledger(), chain_names=demo_data.CHAIN_NAME, hist=demo_data.DemoHist())
tt = fl["totals"]
src = tt["in_krw"] + tt["in_coin"] + tt["in_open"] + tt["back"] + tt["bridge"] + tt["gain"]
chk(tt["in_krw"] > 0 and tt["routes"] >= 5 and tt["bridgeN"] == 1 and tt["gain"] / src < 0.5, "D3 데모 흐름 지도 = 원화 입금 · 거래소 → 지갑 · 브릿지 짝 · 늘어난 몫 < 50%",
    {k: round(tt[k]) for k in ("in_krw", "in_coin", "gain", "routes", "bridgeN")})

T.finish()
