#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import math  # noqa: E402

import bf_engine  # noqa: E402
import nodekeys  # noqa: E402

chk = T.chk
pol = bf_engine._policy_for("eth-mainnet.g.alchemy.com")
g = bf_engine.HostGate("eth-mainnet.g.alchemy.com", pol)
cu = nodekeys.PROVIDERS["alchemy"]["cu_methods"]
UNIT = 20
bad = {m: (g.gate_cost(1, [m]), c) for m, c in cu.items() if g.gate_cost(1, [m]) < math.ceil(c / UNIT)}
chk(not bad, "G1 메서드별 칸 ≥ ⌈CU ÷ 20⌉(공식 CU 표 전부)", bad)
chk(g.gate_cost(1, ["alchemy_getTokenBalances"]) == 1 and g.gate_cost(1, ["eth_call"]) == 2 and g.gate_cost(1, ["eth_somethingNew"]) == 2
    and g.gate_cost(1, ["debug_traceTransaction"]) == 4 and g.gate_cost(1, ["trace_block"]) == 4 and g.gate_cost(1, ["eth_getLogs"]) == 3
    and g.gate_cost(1, ["alchemy_getAssetTransfers"]) == 6, "G1 칸: getTokenBalances 1 · eth_call 2 · 모름 2 · debug_/trace_ 4 · getLogs 3 · getAssetTransfers 6")
chk(g.gate_cost(3, None) == 6 and g.gate_cost(2, ["eth_getBalance", "eth_getLogs"]) == 4, "G1 메서드 모름 = 콜마다 2칸 · 배치 = 칸 합")
chk(nodekeys.PROVIDERS["alchemy"]["cu"] <= 2 * UNIT and nodekeys.PROVIDERS["alchemy"]["cu_heavy"] <= 4 * UNIT, "G1 표에 없는 메서드 CU(26)·무거운 것(80) ≤ 기본·접두 칸")
sr, sb = float(pol["share_rate"]), float(pol["share_burst"])
chk(pol.get("share_xproc") is True and pol.get("share") == "node_alchemy", "G2 공유 버킷 = 프로세스 합산(node_alchemy)")
chk((sb + sr * 1) * UNIT <= 240 and (sb + sr * 10) * UNIT <= 2400 and sb + sr <= 12,
    "G2 1초 창 ≤ 240 CU · 10초 창 ≤ 2,400 CU · 1초 요청 ≤ 12(칸 ≥ 요청)", [(sb + sr) * UNIT, (sb + sr * 10) * UNIT, sb + sr])
clock = {"t": 1000.0}
_mono, _wall = bf_engine.time.monotonic, bf_engine.time.time
bf_engine.time.monotonic = lambda: clock["t"]
bf_engine.time.time = lambda: clock["t"]
g3 = bf_engine.HostGate("x.g.alchemy.com", dict(pol, share=None))
g3.share = None
n = 0
while clock["t"] < 1060.0:
    w = g3._wait_needed("fg", g3.gate_cost(1, ["alchemy_getTokenBalances"]))
    if w <= 0:
        g3.tokens -= 1.0
        g3.c_tokens -= 1.0
        n += 1
    else:
        clock["t"] += max(w, 1e-3)
bf_engine.time.monotonic, bf_engine.time.time = _mono, _wall
chk(355 <= n <= 365, "G3 getTokenBalances 초당 ≈6콜(1분 ≈360 · 종전 120)", n)
cfg_p = {"backfill": {"hosts": {}}}
nodekeys.apply(cfg_p, env={}, settings={"node_plans": {"alchemy": {"plan": "paid"}}})
cfg_f = {"backfill": {"hosts": {}}}
nodekeys.apply(cfg_f, env={}, settings={})
hp = cfg_p["backfill"]["hosts"].get("*.g.alchemy.com") or {}
chk(hp.get("share_rate") == 25.0 and hp.get("rate") == 15.0 and "*.g.alchemy.com" not in cfg_f["backfill"]["hosts"],
    "G4 유료 = 칸 초당 25(520 CU/s ≤ 옛 유료 최저 660 의 80%) · 요청 15 · 무료 = 내장", [hp, cfg_f["backfill"]["hosts"]])
merged = dict(pol, **hp)
chk(merged.get("call_cost") == pol.get("call_cost"), "G4 유료 덮어쓰기도 메서드별 칸은 내장 그대로")
g5 = bf_engine.HostGate("rpc.ankr.com", bf_engine._policy_for("rpc.ankr.com"))
chk(g5.gate_cost(3, None) == 3 and g5.gate_cost(1, ["eth_call"]) == 1, "G5 call_cost 없는 호스트 = cost 그대로(종전)")
T.finish()
sys.exit(1 if T.FAILS else 0)
