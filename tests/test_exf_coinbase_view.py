#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import config, paths  # noqa: E402
import core  # noqa: E402
import db as dbm  # noqa: E402
import web  # noqa: E402

chk = T.chk
NOW = int(time.time())
DAY = 86400
C = core.Core(config.load_config())
C.px.d["neg_ts"]["_fx"] = NOW + 3600


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(t))


def row(uid, ccy, amt, st, t, **kw):
    return dict({"uuid": f"coinbase:{uid}", "currency": ccy, "amount": amt, "fee": "0", "txid": "", "state": st,
                 "created_at": iso(t), "done_at": iso(t)}, **kw)


T1 = NOW - 3 * DAY
C.svc_exf._consume_ex({"v": 1, "kind": "ex_snapshot", "exchange": "coinbase", "ts": NOW,
                       "deposits": [row("d-usd", "USD", "300", "ACCEPTED", T1), row("d-rw", "USDC", "0.75", "ACCEPTED", T1 + 3600, reward="interest")],
                       "withdraws": [row("w-usd", "USD", "100", "DONE", T1 + DAY)]})
C.conn.commit()
C.conn.close()
json.dump({"neg_ts": {"_fx": NOW + 3600}}, open(paths.state("px_cache_web.json"), "w"))
b = web.StateBuilder()
b.skip_gen_check = True
conn = dbm.open_db(paths.DB_PATH, readonly=True)
try:
    out = b._build(conn)
finally:
    conn.close()
f = out["fields"]
ev9 = [e for k9 in ("extraEvents", "extraEventsHidden") for e in (f.get(k9) or []) if isinstance(e, dict) and e.get("sym") == "USDC"]
chk([e.get("d") for e in ev9] == ["코인베이스 · 지급 내역(배당·에어드랍·런치풀·Earn 이자 — 받은 시각 시가 = 소득)"],
    "V1 거래소 리워드 기록 줄 = 거래소 지급 내역 문구 1줄(바이낸스 지급 내역과 같은 분기 · 솔라나 '에폭·MEV 팁' 문구 아님)",
    [e.get("d") for e in ev9])
chk(abs(sum(float(v) for v in (f.get("realizedByDate") or {}).values()) - 0.75) < 1e-9 and abs(float(f.get("stakeRealized") or 0) - 0.75) < 1e-9,
    "V1 받은 날 실현 소득 = 액면 0.75(스테이킹 보상 카드와 같은 규약)", [f.get("realizedByDate"), f.get("stakeRealized")])
st = [x for x in (f.get("stables") or []) if str(x.get("sym") or "").upper() in ("USD", "USDC")]
q9 = {str(x.get("sym")).upper(): round(float(x.get("qty") or 0), 6) for x in st}
chk(q9.get("USD") == 200.0 and q9.get("USDC") == 0.75, "V2 코인베이스 USD 현금 200(입금 300 − 출금 100) · USDC 0.75 = 스테이블 보유 행", q9)
T.finish()
