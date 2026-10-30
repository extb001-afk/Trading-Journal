#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _cassette as C  # noqa: E402

C.freeze()
import datetime  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402

ACCESS, SECRET = "casUPBITwatch001", "casUPBITwsecr001"
KST = datetime.timezone(datetime.timedelta(hours=9))


def iso(sec_ago):
    return datetime.datetime.fromtimestamp(C.NOW - sec_ago, KST).isoformat(timespec="seconds")


OPEN = {"uuid": "ord-wait-1", "side": "bid", "ord_type": "limit", "price": "2700.0", "state": "wait", "market": "KRW-TSTA",
        "created_at": iso(600), "volume": "10.0", "remaining_volume": "10.0", "executed_volume": "0.0", "trades_count": 0}
W1 = {"uuid": "ord-watch-1", "side": "ask", "ord_type": "limit", "price": "3000.0", "state": "watch", "market": "KRW-TSTA",
      "created_at": iso(10 * 86400), "volume": "5.0", "remaining_volume": "5.0", "executed_volume": "0.0", "trades_count": 0}
W2 = dict(W1, uuid="ord-watch-2", created_at=iso(9 * 86400), price="3100.0")
W3 = dict(W1, uuid="ord-watch-3", created_at=iso(8 * 86400), price="3200.0")
W1_DONE = dict(W1, state="done", remaining_volume="0.0", executed_volume="5.0", executed_funds="15000.0", paid_fee="7.5", trades_count=1,
               trades=[{"market": "KRW-TSTA", "uuid": "trd-w001", "side": "ask", "price": "3000.0", "volume": "5.0", "funds": "15000.0",
                        "created_at": iso(1800)}])
PHASE = [1]


def respond(rq):
    assert rq.host == "api.upbit.com", rq.url
    p, q = rq.path, rq.query
    hdr = {"Remaining-Req": "group=default; min=1799; sec=29"}
    err = C.Reply({"error": {"name": "server_error", "message": "synthetic"}}, status=500, headers=hdr)
    if p == "/v1/orders/open" and q.get("state") == "watch":
        return err if PHASE[0] in (0, 2) else C.Reply({1: [W1, W2], 4: [W1, W2, W3], 3: [W2, W3]}[PHASE[0]], headers=hdr)
    if p == "/v1/orders/open":
        return err if PHASE[0] == 4 else C.Reply([OPEN], headers=hdr)
    if p == "/v1/accounts":
        return C.Reply([{"currency": "KRW", "balance": "1000000.0", "locked": "27000.0", "avg_buy_price": "0", "avg_buy_price_modified": False,
                         "unit_currency": "KRW"},
                        {"currency": "TSTA", "balance": "10.0", "locked": "10.0", "avg_buy_price": "2650.0", "avg_buy_price_modified": False,
                         "unit_currency": "KRW"}], headers=hdr)
    if p in ("/v1/deposits", "/v1/withdraws", "/v1/orders/closed"):
        return C.Reply([], headers=hdr)
    if p == "/v1/order" and q.get("uuid") == W1["uuid"]:
        return C.Reply(W1_DONE, headers=hdr)
    raise AssertionError("모르는 요청 " + rq.url)


CFG = {"chains": {}, "wallets": [], "backfill_months": 0.2}
with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump(CFG, f)
import paths  # noqa: E402
import statefile  # noqa: E402
import upbit_link  # noqa: E402
from inbox import SegmentWriter  # noqa: E402


class RecUp(upbit_link.Upbit):

    def __init__(self, *a):
        super().__init__(*a)
        self.calls = []

    def get(self, path, query=None):
        self.calls.append((path, dict(query or {})))
        return super().get(path, query)


def st(name):
    return statefile.read_json(paths.state(name), {})


def ex_recs():
    snap = C.snap_tree(paths.STATE_DIR)
    return [r for k, v in snap.items() if k.startswith("inbox/ex/") for r in v if isinstance(r, dict)]


cas = C.Cassette("upbit_watch", secrets={"upbit_access": ACCESS, "upbit_secret": SECRET}, responder=respond)
if cas.ready(T):
    paths.ensure_dirs()
    up, writer = RecUp(ACCESS, SECRET), SegmentWriter(os.path.join(paths.INBOX_DIR, "ex"))
    runs = []
    for ph in (0, 1, 2, 4, 3):
        PHASE[0] = ph
        up.calls = []
        _out, why = cas.run(upbit_link.cycle, up, writer, 0.2)
        T.chk(why is None, f"단계 W{ph} = 예외·새 요청 없음", why)
        runs.append({"calls": list(up.calls), "orders": st("upbit_orders_state.json"), "bal": st("upbit_balances.json"),
                     "sync": st("upbit_sync.json"), "fills": [r for r in ex_recs() if r.get("kind") == "ex_fills"]})
    r0, r1, r2, r4, r3 = runs
    T.chk(sorted(r0["orders"].get("open_track") or {}) == [OPEN["uuid"]] and r0["orders"].get("complete") is True and r0["sync"].get("last_ok")
          and not r0["sync"].get("last_err") and not r0["fills"] and [o.get("uuid") for o in r0["bal"].get("open_orders") or []] == [OPEN["uuid"]]
          and [(p, q.get("state")) for p, q in r0["calls"][:4]] == [("/v1/orders/open", None), ("/v1/accounts", None), ("/v1/orders/open", None),
                                                                    ("/v1/orders/open", "watch")],
          "W0 예약 목록 실패 · 추적 중 예약 없음 = 종전 결과(추적 = 미체결만 · 완주 도장 · 동기화 성공) · 예약 목록은 잔고 뒤", (r0["orders"], r0["calls"][:4]))
    tr1 = r1["orders"].get("open_track") or {}
    T.chk(sorted(tr1) == sorted([OPEN["uuid"], W1["uuid"], W2["uuid"]]) and all(tr1[u].get("w") == 1 and not tr1[u].get("closed") for u in (W1["uuid"], W2["uuid"]))
          and not tr1[OPEN["uuid"]].get("w") and not any(p == "/v1/order" for p, _q in r1["calls"])
          and [o.get("uuid") for o in r1["bal"].get("open_orders") or []] == [OPEN["uuid"]] and not r1["fills"],
          "W1 예약 2건 = 추적(칸 w · 종결 아님) · 단건 0 · 잔고 스냅숏 open_orders = 미체결만 · ex_fills 없음", (tr1, r1["bal"].get("open_orders")))
    T.chk([q.get("state") for p, q in r1["calls"] if p == "/v1/orders/open"] == [None, None, "watch"],
          "W1 목록 호출 = 예약 1 + 미체결 2(주기당 +1콜)", [(p, q.get("state")) for p, q in r1["calls"]])
    tr2 = r2["orders"].get("open_track") or {}
    T.chk(tr2 == tr1 and not any(p == "/v1/order" for p, _q in r2["calls"]) and not r2["fills"]
          and r2["bal"].get("open_orders") == r1["bal"].get("open_orders")
          and r2["orders"].get("complete") is False and r1["orders"].get("complete") is True and not r2["orders"].get("track_pending")
          and r2["sync"].get("last_ok", 0) > r1["sync"].get("last_ok", 0) and up._backoff_err is None
          and (r2["sync"].get("watch_hold") or {}).get("since") and "watch_hold" not in r1["sync"] and "watch_hold" not in r0["sync"],
          "W2 예약 목록 실패 + 추적 중 예약 = 추적 그대로 · 단건 0 · 완주 도장 보류(동기화 기록 watch_hold) · 스냅숏·동기화 그대로 · 백오프 없음", (tr2, r2["orders"].get("complete"), r2["sync"]))
    tr4 = r4["orders"].get("open_track") or {}
    T.chk(sorted(tr4) == sorted(list(tr1) + [W3["uuid"]]) and tr4[W3["uuid"]].get("w") == 1 and not any(e.get("closed") for e in tr4.values())
          and not any(p == "/v1/order" for p, _q in r4["calls"]) and r4["orders"].get("complete") is False and "open_orders" not in r4["bal"],
          "W4 미체결 목록 실패 · 예약 목록 성공 = 새 예약만 기억(칸 w) · 종결 판정 없음(단건 0) · 완주 도장 없음", tr4)
    tr3 = r3["orders"].get("open_track") or {}
    got = [o for r in r3["fills"] for o in (r.get("orders") or [])]
    T.chk([q.get("uuid") for p, q in r3["calls"] if p == "/v1/order"] == [W1["uuid"]]
          and [o.get("uuid") for o in got] == [W1["uuid"]] and got[0].get("state") == "done" and len(got[0].get("trades") or []) == 1
          and W1["uuid"] not in tr3 and tr3.get(W2["uuid"], {}).get("w") == 1 and not tr3[W2["uuid"]].get("closed")
          and W1["uuid"] in (r3["orders"].get("uuids") or []) and tr3.get(W3["uuid"], {}).get("w") == 1 and r3["orders"].get("complete") is True and "watch_hold" not in r3["sync"],
          "W3 사라진 예약 = 단건 done 1번 → ex_fills 1건(체결 목록 포함) · 추적에서 빠짐 · 남은 예약은 계속 추적", (got, tr3))
    cas.golden(T, C.snap_tree(paths.STATE_DIR))
    cas.check(T)
T.finish()
