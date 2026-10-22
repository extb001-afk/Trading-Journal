#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import os  # noqa: E402
import time  # noqa: E402

import paths, statefile  # noqa: E402
import health  # noqa: E402
import web  # noqa: E402

chk = T.chk
S = paths.STATE_DIR
NOW = time.time()
UNITS = ["tj-core", "tj-web", "tj-exf"]
HS = health.settings({"health": {"units": UNITS}})
chk(set(health.STABLE_USD) == set(web.EX_STABLE_SYMS), "S1 헬스 STABLE_USD = 웹 EX_STABLE_SYMS",
    sorted(set(health.STABLE_USD) ^ set(web.EX_STABLE_SYMS)))


def obs_of(now, **kw):
    o = {"now": now, "pm2": {u: {"status": "online", "restarts": 0, "pid": 1} for u in UNITS}, "bal_mem": {}, "prev_inc": {}, "sources": []}
    o.update(kw)
    return o


class L:
    units = {"tj-exf": {"debt": {}}}


def case(debts):
    for f in os.listdir(S):
        if f.startswith("exf_balances_") or f == "spot.json":
            os.remove(os.path.join(S, f))
    statefile.atomic_write_json(os.path.join(S, "spot.json"), {"ex_usd": {}, "ex_ts": {}})
    statefile.atomic_write_json(os.path.join(S, "exf_balances_bybit.json"), {"ts": NOW, "balances": {}, "debts": debts})
    rows = health.collect_debt(L(), NOW, HS)
    c = {x["id"]: x for x in health.evaluate(obs_of(NOW, debt=rows), HS)}.get("debt:margin") or {}
    return rows, c


rows, c = case({"USDT": -100.0, "USDE": -12.0, "RLUSD": -5.0, "USD": -3.0, "USDP": -2.0, "USDS": -1.0})
val = {r[2]: r[4] for r in rows}
chk(all(val.get(a) == q for a, q in (("USDE", 12.0), ("RLUSD", 5.0), ("USD", 3.0), ("USDP", 2.0), ("USDS", 1.0))),
    "S2 USDE·RLUSD·USD·USDP·USDS 부채 = $1 × 수량", val)
chk("값 모름" not in str(c.get("title") or ""), "S2 debt:margin 제목에 '값 모름' 없음", c.get("title"))
rows, c = case({"USDT": -100.0, "ZZZ": -5.0})
chk({r[2]: r[4] for r in rows}.get("ZZZ") is None and c.get("level") == "warn", "S3 스테이블 아닌 시세 없는 코인 = 값 모름 · 주의(종전)",
    (rows, c.get("level")))

T.finish()
