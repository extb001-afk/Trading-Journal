#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
from decimal import Decimal as D  # noqa: E402

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump({"chains": {}, "wallets": [], "backfill_months": 0.2}, open(os.path.join(T.TMP, "config.json"), "w"))
import config  # noqa: E402
import core  # noqa: E402
import db as dbm  # noqa: E402
import paths  # noqa: E402
import statefile  # noqa: E402
import upbit_link  # noqa: E402

chk = T.chk
NOW = time.time()
C = core.Core(config.load_config())
C.px.fx_at = lambda ms: 1000.0


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(t))


T1, T2 = int(NOW) - 3 * 86400, int(NOW) - 2 * 86400
UID = "otk-ord-1"
BASE = {"uuid": UID, "side": "bid", "ord_type": "limit", "price": "100000", "market": "KRW-ETH", "created_at": iso(NOW - 10 * 86400),
        "volume": "1.0"}
OPEN = dict(BASE, state="wait", executed_volume="0.5", remaining_volume="0.5", trades_count=2)
TRADES = [{"market": "KRW-ETH", "uuid": "otk-t0", "side": "bid", "price": "100000", "volume": "0.2", "funds": "20000", "created_at": iso(T1)},
          {"market": "KRW-ETH", "uuid": "otk-t1", "side": "bid", "price": "100000", "volume": "0.3", "funds": "30000", "created_at": iso(T1)},
          {"market": "KRW-ETH", "uuid": "otk-t2", "side": "bid", "price": "100000", "volume": "0.5", "funds": "50000", "created_at": iso(T2)}]
DONE = dict(BASE, state="done", executed_volume="1.0", remaining_volume="0.0", executed_funds="100000", paid_fee="50",
            trades_count=3, trades=TRADES)


class FakeUp:

    def __init__(self):
        self.remaining_min, self._backoff_err = 999, None
        self.open, self.single, self.calls = [], {}, []

    def get(self, path, query=None):
        q = dict(query or {})
        self.calls.append((path, q))
        if path == "/v1/orders/open":
            return [dict(o) for o in self.open] if q.get("state") in (None, "wait") else []
        if path == "/v1/order":
            return json.loads(json.dumps(self.single[q["uuid"]]))
        if path in ("/v1/accounts", "/v1/deposits", "/v1/withdraws", "/v1/orders/closed"):
            return []
        raise AssertionError("모르는 요청 " + path)


class Writer:
    def __init__(self):
        self.recs = []

    def append(self, rec):
        self.recs.append(json.loads(json.dumps(rec)))


def run_cycle(up, w):
    upbit_link.cycle(up, w, 0.2)


def legs(u):
    return [tuple(r) for r in C.conn.execute("SELECT leg_seq, event_ts, qty_base, cost_krw, leg_kind, event"
                                             " FROM postings WHERE source_ns='upbit:order' AND source_id=? ORDER BY leg_seq", (u,))]


def ostate():
    return statefile.read_json(paths.state("upbit_orders_state.json"), {})


up, w = FakeUp(), Writer()
up.open = [OPEN]
run_cycle(up, w)
fills1 = [r for r in w.recs if r.get("kind") == "ex_fills"]
snap = statefile.read_json(paths.state("upbit_balances.json"), {})
chk(not fills1 and UID in (ostate().get("open_track") or {}) and not ostate()["open_track"][UID].get("closed")
    and [o.get("uuid") for o in snap.get("open_orders") or []] == [UID] and not any(p == "/v1/order" for p, _q in up.calls),
    "O1 열린 부분 체결 주문 = 원장 밖(ex_fills 없음) · 추적에 듦 · 잔고 스냅숏 open_orders 에 그 주문 · 단건 조회 0",
    (fills1, ostate().get("open_track"), snap.get("open_orders")))

up.open, up.single, up.calls = [], {UID: DONE}, []
run_cycle(up, w)
fills2 = [r for r in w.recs if r.get("kind") == "ex_fills"]
singles = [q.get("uuid") for p, q in up.calls if p == "/v1/order"]
got = (fills2[0].get("orders") or []) if len(fills2) == 1 else []
chk(singles == [UID] and [o.get("uuid") for o in got] == [UID] and len(got[0].get("trades") or []) == 3
    and UID not in (ostate().get("open_track") or {}) and UID in (ostate().get("uuids") or []) and not ostate().get("track_pending"),
    "O2 목록에서 사라짐 = 단건 조회 1번 → ex_fills 1건(체결 목록 3건 포함) · 추적에서 빠지고 방출 목록(uuids)에", (singles, fills2, ostate()))

for r in fills2:
    C._consume_record(r)
C.conn.commit()
L = legs(UID)
E8 = 10 ** 8
chk([(x[0], x[1], x[2], x[4], x[5]) for x in L] == [(0, T1, str(E8 // 2), "acq", "EX_BUY"), (1, T2, str(E8 // 2), "acq", "EX_BUY")],
    "O3 레그 2(leg 0·1 · 시각 = 각 묶음의 초 · 순수량 각 0.5 · 매수)", L)
chk(sum(D(x[3]) for x in L) == D("100050"), "O3 원화 합 = 체결 금액 100,000 + 수수료 50", [x[3] for x in L])
chk(C.conn.execute("SELECT count(*) FROM raw_ex WHERE uuid=?", (UID,)).fetchone()[0] == 1 and dbm.ledger_data_rev(C.conn) == 3,
    "O3 원본(raw_ex) 한 줄 · data_rev 3(분할 기장)", dbm.ledger_data_rev(C.conn))

p0 = sorted(tuple(r) for r in C.conn.execute("SELECT group_id, location, qty_norm FROM positions"))
for r in fills2:
    C._consume_record(r)
C.conn.commit()
chk(legs(UID) == L and sorted(tuple(r) for r in C.conn.execute("SELECT group_id, location, qty_norm FROM positions")) == p0,
    "O4 같은 ex_fills 다시 = 원장·포지션 무변")
T.finish()
