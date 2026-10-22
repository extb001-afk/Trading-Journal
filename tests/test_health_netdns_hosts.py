#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import time  # noqa: E402

import chk_logs  # noqa: E402
import health  # noqa: E402

NOW = time.time()
H = health.settings({})


def run(lines):
    lw = chk_logs.LogWatch()
    for k in range(0, 3600 + 2400, 60):
        ts = NOW - 3600 + k
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) + ",000"
        for unit, msg in lines:
            lw.feed(unit, f"{stamp} WARNING {msg}")
    src = [{"kind": "exchange", "key": "ex:bybit", "label": "바이빗", "unit": "tj-exf", "last_success": NOW - 4 * 3600, "first_seen": NOW - 86400 * 3},
           {"kind": "chain", "key": "chain:eth", "label": "Ethereum", "unit": "tj-evm", "last_success": NOW - 3 * 3600, "first_seen": NOW - 86400 * 3}]
    st = {}
    pm2 = {u: {"status": "online", "restarts": 0, "pid": 1} for u in H["units"]}
    for n in range(40):
        now = NOW + n * 60
        obs = {"now": now, "pm2": pm2, "sources": [dict(x) for x in src], "logs": {u: lw.summary(u, now, H["t"]) for u in H["units"]}}
        checks = health.evaluate(obs, H, open_ids=list((st.get("incidents") or {}).keys()))
        health.step(st, checks, now, H)
    return {c["id"]: c for c in checks}, sorted((st.get("incidents") or {}).keys())


DEAD = "<urlopen error [Errno -2] Name or service not known>"
by, inc = run([("tj-evm", f"[rpc] https://rpc.deadchain.example 실패: {DEAD}"), ("tj-web", f"가격 조회 실패 https://rpc.deadchain.example/p: {DEAD}")])
T.chk(by["net:dns"]["level"] == "ok", "[1] 같은 죽은 호스트 하나 · 두 유닛 = net:dns 초록", by["net:dns"])
T.chk(by["sync:ex:bybit"]["level"] in ("warn", "crit") and not by["sync:ex:bybit"].get("suppressed") and "sync:ex:bybit" in inc,
      "[1] 거래소 멈춤 경보 = 억제 안 됨 · 사건 열림", (by["sync:ex:bybit"], inc))
T.chk(not by["sync:chain:eth"].get("suppressed") and "sync:chain:eth" in inc, "[1] 체인 멈춤 경보 = 억제 안 됨", (by["sync:chain:eth"], inc))

by, inc = run([("tj-evm", f"[rpc] https://rpc.ankr.com/eth 실패: {DEAD}"), ("tj-exf", f"bybit 조회 실패 HTTPSConnectionPool(host='api.bybit.com', port=443): {DEAD}")])
T.chk(by["net:dns"]["level"] == "crit" and "net:dns" in inc, "[2] 서로 다른 호스트 실패 = net:dns 빨강(종전)", by["net:dns"])
T.chk(by["sync:ex:bybit"].get("suppressed") == "네트워크 끊김" and "sync:ex:bybit" not in inc, "[2] 멈춤 경보 = 네트워크 끊김 억제(종전)", by["sync:ex:bybit"])

by, inc = run([("tj-evm", "[rpc] 조회 실패: [Errno 101] Network is unreachable"), ("tj-exf", "조회 실패: [Errno 101] Network is unreachable")])
T.chk(by["net:dns"]["level"] == "crit" and by["sync:chain:eth"].get("suppressed") == "네트워크 끊김", "[3] 호스트 모름 두 유닛 = 종전대로 빨강·억제",
      (by["net:dns"], by["sync:chain:eth"]))


T.chk(chk_logs.net_host("x https://API.Bybit.com/v5/x y") == "api.bybit.com", "[4] 주소 → 호스트")
T.chk(chk_logs.net_host("HTTPSConnectionPool(host='rpc.ankr.com', port=443): Max retries") == "rpc.ankr.com", "[4] urllib3 host=")
T.chk(chk_logs.net_host("[rpc] rpc.deadchain.example 실패") == "rpc.deadchain.example", "[4] 맨 도메인")
T.chk(chk_logs.net_host("core.py 의 state/health.json 실패: Network is unreachable") is None, "[4] 파일 이름 꼴 = 호스트 아님")
T.finish()
