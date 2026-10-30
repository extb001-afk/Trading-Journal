#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _cassette as C  # noqa: E402

C.freeze()
import datetime  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402

ACCESS, SECRET = "casUPBITaccess01", "casUPBITsecret01"
KST = datetime.timezone(datetime.timedelta(hours=9))


def iso(sec_ago):
    return datetime.datetime.fromtimestamp(C.NOW - sec_ago, KST).isoformat(timespec="seconds")


OPEN = {"uuid": "ord-open-1", "side": "bid", "ord_type": "limit", "price": "2700.0", "state": "wait", "market": "KRW-TSTA",
        "created_at": iso(600), "volume": "10.0", "remaining_volume": "10.0", "reserved_fee": "13.5", "remaining_fee": "13.5", "paid_fee": "0.0",
        "locked": "27013.5", "executed_volume": "0.0", "trades_count": 0}
DONE = {"uuid": "ord-done-1", "side": "bid", "ord_type": "limit", "price": "2650.0", "state": "done", "market": "KRW-TSTA",
        "created_at": iso(7200), "volume": "20.0", "remaining_volume": "0.0", "reserved_fee": "26.5", "remaining_fee": "0.0", "paid_fee": "26.5",
        "locked": "0.0", "executed_volume": "20.0", "executed_funds": "53000.0", "trades_count": 1}
TRADES = [{"market": "KRW-TSTA", "uuid": "trd-0001", "price": "2650.0", "volume": "20.0", "funds": "53000.0", "side": "bid", "created_at": iso(7100)}]


def respond(rq):
    assert rq.host == "api.upbit.com", rq.url
    p, q = rq.path, rq.query
    hdr = {"Remaining-Req": "group=default; min=1799; sec=29"}
    if p == "/v1/orders/open":
        return C.Reply([] if q.get("state") == "watch" else [OPEN], headers=hdr)
    if p == "/v1/accounts":
        return C.Reply([{"currency": "KRW", "balance": "1000000.0", "locked": "27013.5", "avg_buy_price": "0", "avg_buy_price_modified": False,
                         "unit_currency": "KRW"},
                        {"currency": "TSTA", "balance": "60.0", "locked": "0.0", "avg_buy_price": "2650.0", "avg_buy_price_modified": False,
                         "unit_currency": "KRW"}], headers=hdr)
    if p == "/v1/deposits":
        return C.Reply([{"type": "deposit", "uuid": "dep-0001", "currency": "TSTA", "net_type": "TSTA", "txid": "0x%064x" % 0xD0D0,
                         "state": "ACCEPTED", "created_at": iso(86400), "done_at": iso(86000), "amount": "50.0", "fee": "0.0",
                         "transaction_type": "default"}] if q.get("page") == "1" else [], headers=hdr)
    if p == "/v1/withdraws":
        return C.Reply([{"type": "withdraw", "uuid": "wd-0001", "currency": "TSTA", "net_type": "TSTA", "txid": "0x%064x" % 0xE0E0,
                         "state": "DONE", "created_at": iso(43200), "done_at": iso(43000), "amount": "10.0", "fee": "0.5",
                         "transaction_type": "default"}] if q.get("page") == "1" else [], headers=hdr)
    if p == "/v1/orders/closed":
        return C.Reply([DONE] if q.get("state") == "done" else [], headers=hdr)
    if p == "/v1/order" and q.get("uuid") == DONE["uuid"]:
        return C.Reply(dict(DONE, trades=TRADES), headers=hdr)
    raise AssertionError("모르는 요청 " + rq.url)


CFG = {"chains": {}, "wallets": [], "backfill_months": 0.2}
with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump(CFG, f)
import paths  # noqa: E402
import upbit_link  # noqa: E402

with open(paths.ENV_PATH, "w", encoding="utf-8") as f:
    f.write(f"UPBIT_ACCESS={ACCESS}\nUPBIT_SECRET={SECRET}\n")
cas = C.Cassette("upbit", secrets={"upbit_access": ACCESS, "upbit_secret": SECRET}, responder=respond)
if cas.ready(T):
    out, why = cas.run(upbit_link.main, stop_sleep=60)
    T.chk(why is None, "main 한 바퀴 = 주기 끝 sleep 까지(예외·새 요청 없음)", why)
    snap = C.snap_tree(paths.STATE_DIR)
    recs = [r for k, v in snap.items() if k.startswith("inbox/ex/") for r in v]
    kinds = sorted({r.get("kind") for r in recs if isinstance(r, dict)})
    T.chk({"ex_snapshot", "ex_fills"} <= set(kinds), "inbox ex = 입출금 스냅숏 + 체결", kinds)
    T.chk(((snap.get("upbit_sync.json") or {}).get("last_ok") or 0) > 0, "동기화 성공 기록(upbit_sync)", snap.get("upbit_sync.json"))
    cas.golden(T, snap)
    cas.check(T)
T.finish()
