#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _cassette as C  # noqa: E402

C.freeze()
import json  # noqa: E402
import os  # noqa: E402

KEY, SECRET, PASS = "casOKXkey0001", "casOKXsecret0001", "casOKXpass01"
NOW_MS = int(C.NOW * 1000)
DAY_MS = 86_400_000
WD_TO = "0x" + "e5" * 20
SEEN = set()


def ok(data):
    return {"code": "0", "msg": "", "data": data}


def respond(rq):
    assert rq.host == "www.okx.com", rq.url
    p, q = rq.path, rq.query
    SEEN.add(p)
    if p == "/api/v5/public/time":
        return ok([{"ts": str(NOW_MS)}])
    if p == "/api/v5/account/balance":
        return ok([{"details": [{"ccy": "USDT", "cashBal": "900.5", "availBal": "900.5", "eq": "900.5"},
                                {"ccy": "ETH", "cashBal": "0.6", "availBal": "0.6", "eq": "0.6"}]}])
    if p == "/api/v5/asset/balances":
        return ok([{"ccy": "USDT", "bal": "10", "availBal": "10"}])
    if p == "/api/v5/asset/withdrawal-history":
        if q.get("after"):
            return ok([])
        return ok([{"wdId": "901", "ccy": "USDT", "chain": "USDT-ERC20", "amt": "100", "fee": "1", "txId": "0x%064x" % 0xA11CE01,
                    "state": "2", "ts": str(NOW_MS - 2 * DAY_MS), "to": WD_TO}])
    if p == "/api/v5/asset/deposit-history":
        if q.get("after"):
            return ok([])
        return ok([{"depId": "701", "ccy": "ETH", "chain": "ETH-ERC20", "amt": "0.5", "txId": "0x%064x" % 0xDE9051,
                    "state": "2", "ts": str(NOW_MS - 3 * DAY_MS), "from": "", "to": "0x" + "f6" * 20}])
    if p == "/api/v5/trade/fills-history":
        if q.get("after"):
            return ok([])
        return ok([{"billId": "502", "instId": "ETH-USDT", "side": "sell", "fillPx": "2600.25", "fillSz": "0.05", "fee": "-0.13",
                    "feeCcy": "USDT", "ts": str(NOW_MS - DAY_MS + 3_600_000), "tradeId": "8802", "ordId": "9902"},
                   {"billId": "501", "instId": "ETH-USDT", "side": "buy", "fillPx": "2500.5", "fillSz": "0.15", "fee": "-0.00015",
                    "feeCcy": "ETH", "ts": str(NOW_MS - DAY_MS), "tradeId": "8801", "ordId": "9901"}])
    if p == "/api/v5/asset/convert/history":
        if q.get("after"):
            return ok([])
        return ok([{"tradeId": "cv-301", "state": "fullyFilled", "ts": str(NOW_MS - 5 * 3_600_000), "side": "buy", "baseCcy": "ETH",
                    "quoteCcy": "USDT", "fillBaseSz": "0.01", "fillQuoteSz": "25.5", "instId": "ETH-USDT", "fillPx": "2550"}])
    return ok([])


CFG = {"chains": {}, "wallets": [], "backfill_months": 5, "exf": {"leverage": False}}
with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump(CFG, f)
import paths  # noqa: E402
import ex_foreign as X  # noqa: E402

with open(paths.ENV_PATH, "w", encoding="utf-8") as f:
    f.write(f"TJ_OKX_KEY={KEY}\nTJ_OKX_SECRET={SECRET}\nTJ_OKX_PASSPHRASE={PASS}\n")
X.depaddr.start_background = lambda *a, **k: None
import perp_dex  # noqa: E402
import liq_watch  # noqa: E402
perp_dex.start_background = lambda *a, **k: None
liq_watch.start_background = lambda *a, **k: None

cas = C.Cassette("exf_okx", secrets={"okx_key": KEY, "okx_secret": SECRET, "okx_pass": PASS}, responder=respond)
if cas.ready(T):
    out, why = cas.run(X.main, stop_sleep=60)
    T.chk(why is None, "main 한 바퀴 = 주기 끝 sleep 까지(예외·새 요청 없음)", why)
    if cas.record:
        print("응답기에 온 경로:", sorted(SEEN))
    snap = C.snap_tree(paths.STATE_DIR)
    recs = [r for k, v in snap.items() if k.startswith("inbox/ex/") for r in v]
    kinds = sorted({r.get("kind") for r in recs if isinstance(r, dict)})
    T.chk({"ex_snapshot", "exf_fills"} <= set(kinds), "inbox ex = 입출금 스냅숏 + 체결(전환 포함)", kinds)
    cas.golden(T, snap)
    cas.check(T)
T.finish()
