#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _cassette as C  # noqa: E402

C.freeze()
import base64  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402

import ex_sign  # noqa: E402
import exf_coinbase as X  # noqa: E402
import exf_net  # noqa: E402

NAME = "organizations/cas-org-0001/apiKeys/cas-key-0001"
_N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551
D = int.from_bytes(hashlib.sha256(b"tj cassette coinbase synthetic key").digest(), "big") % _N


def _tlv(tag, body):
    n = len(body)
    return bytes([tag]) + (bytes([n]) if n < 128 else bytes([0x81, n])) + body


_PX, _PY = ex_sign.ec_p256_pub(D)
SEC1 = _tlv(0x30, _tlv(0x02, b"\x01") + _tlv(0x04, D.to_bytes(32, "big")) + _tlv(0xA0, bytes.fromhex("06082a8648ce3d030107"))
            + _tlv(0xA1, _tlv(0x03, b"\x00\x04" + _PX.to_bytes(32, "big") + _PY.to_bytes(32, "big"))))
BODY = base64.b64encode(SEC1).decode()
ENV = {"TJ_COINBASE_KEY_NAME": NAME, "TJ_COINBASE_SECRET": BODY}
NOW = int(C.NOW)
H = 3600
DAY = 86400
SEEN = []


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".123456Z"


def tx(i, typ, amt, ccy, ago, status="completed", **extra):
    d = {"id": f"tx-{i:04d}", "type": typ, "status": status, "amount": {"amount": amt, "currency": ccy},
         "native_amount": {"amount": "0", "currency": "USD"}, "created_at": iso(NOW - ago), "resource": "transaction"}
    d.update(extra)
    return d


HASH = lambda n: "0x%064x" % n  # noqa: E731
TXS = {
    "a-btc": [tx(1, "send", "-0.05000000", "BTC", H, status="pending", network={"status": "pending", "hash": HASH(0xB1), "name": "bitcoin"},
                 to={"resource": "bitcoin_address", "address": "bc1qcassette0000000000000000000000000000"}),
              tx(2, "send", "0.00200000", "BTC", 5 * H, network={"status": "off_blockchain", "name": "bitcoin"}, to={"resource": "user"}),
              tx(3, "advanced_trade_fill", "0.02000000", "BTC", 8 * H, advanced_trade_fill={"product_id": "BTC-USD", "order_side": "BUY"}),
              tx(4, "send", "-0.10000000", "BTC", DAY, network={"status": "confirmed", "hash": HASH(0xB2), "name": "bitcoin",
                                                                "transaction_fee": {"amount": "0.00010000", "currency": "BTC"}},
                 to={"resource": "bitcoin_address", "address": "bc1qcassette1111111111111111111111111111"}),
              tx(5, "buy", "0.01000000", "BTC", 2 * DAY, buy={"id": "buy-0001", "resource": "buy"}),
              tx(6, "receive", "0.50000000", "BTC", 3 * DAY, network={"status": "confirmed", "hash": HASH(0xB3), "name": "bitcoin"}),
              tx(7, "receive", "9.00000000", "BTC", 40 * DAY, network={"status": "confirmed", "hash": HASH(0xB4), "name": "bitcoin"})],
    "a-usd": [tx(11, "fiat_withdrawal", "-50.00", "USD", 12 * H),
              tx(12, "trade", "-100.00", "USD", DAY, trade={"id": "trd-0001", "resource": "trade"}),
              tx(13, "buy", "-250.00", "USD", 2 * DAY, buy={"id": "buy-0001", "resource": "buy"}),
              tx(14, "fiat_deposit", "1000.00", "USD", 4 * DAY),
              tx(15, "fiat_deposit", "5.00", "USD", 30 * DAY)],
    "a-usdc": [tx(21, "mystery_type", "1.00", "USDC", 2 * H),
               tx(22, "interest", "0.50", "USDC", 6 * H),
               tx(23, "trade", "100.00", "USDC", DAY, trade={"id": "trd-0001", "resource": "trade"}),
               tx(24, "sell", "-3.00", "USDC", 2 * DAY, sell={"id": "sell-0001", "resource": "sell"}),
               tx(25, "raise_offering_deposit", "-40.00", "USDC", 2 * DAY + H),
               tx(26, "raise_offering_deposit", "-20.00", "USDC", 5 * DAY)],
    "a-raise": [tx(51, "raise_offering_deposit", "40.00", "USDC", 2 * DAY + H),
                tx(52, "raise_offering_pooling", "-20.00", "USDC", 4 * DAY),
                tx(53, "raise_offering_deposit", "20.00", "USDC", 5 * DAY)],
    "a-mon": [tx(61, "raise_offering_distribution", "500.00000000", "MON", 4 * DAY + 60)],
    "a-eth": [],
    "a-eur": [tx(41, "fiat_deposit", "10.00", "EUR", 2 * DAY)],
}
V2_ACCTS = [{"id": "a-btc", "balance": {"amount": "0.35200000", "currency": "BTC"}, "currency": {"code": "BTC"}, "type": "wallet"},
            {"id": "a-usd", "balance": {"amount": "605.00", "currency": "USD"}, "currency": {"code": "USD"}, "type": "fiat"},
            {"id": "a-usdc", "balance": {"amount": "98.50", "currency": "USDC"}, "currency": {"code": "USDC"}, "type": "wallet"},
            {"id": "a-eth", "balance": {"amount": "0", "currency": "ETH"}, "currency": {"code": "ETH"}, "type": "wallet"},
            {"id": "a-eur", "balance": {"amount": "10.00", "currency": "EUR"}, "currency": {"code": "EUR"}, "type": "fiat"},
            {"id": "a-mon", "balance": {"amount": "500.00000000", "currency": "MON"}, "currency": {"code": "MON"}, "type": "wallet"},
            {"id": "a-raise", "name": "Raise Investment (USDC)", "balance": {"amount": "40.00", "currency": "USDC"},
             "currency": {"code": "USDC"}, "type": "wallet"}]


def fill(eid, prod, side, px, sz, fee, ago, ttype="FILL", siq=False):
    return {"entry_id": eid, "trade_id": "t" + eid, "order_id": "o" + eid, "trade_time": iso(NOW - ago), "trade_type": ttype,
            "price": px, "size": sz, "commission": fee, "product_id": prod, "sequence_timestamp": iso(NOW - ago),
            "liquidity_indicator": "TAKER", "size_in_quote": siq, "user_id": "u1", "side": side}


FILLS1 = [fill("e-0001", "BTC-USD", "BUY", "60000.00", "0.02", "7.2", 8 * H),
          fill("e-0002", "ETH-USDC", "SELL", "2500.5", "0.4", "1.0005", 20 * H),
          fill("e-0003", "BTC-USD", "SELL", "60000.00", "0.001", "0.1", 9 * H, ttype="REVERSAL"),
          fill("e-0004", "BTC-USD", "BUY", "61000.00", "100.00", "0.5", 10 * H, siq=True)]
FILLS2 = [fill("e-0001", "BTC-USD", "BUY", "60000.00", "0.02", "7.2", 8 * H),
          fill("e-0005", "BIT-31OCT26-CDE", "BUY", "60000", "1", "0.1", 11 * H),
          dict(fill("e-0006", "BTC-PERP", "BUY", "60000", "0.5", "1", 12 * H), product_type="FUTURE")]


def respond(rq):
    assert rq.host == "api.coinbase.com", rq.url
    p, q = rq.path, rq.query
    SEEN.append(p)
    if p == "/api/v3/brokerage/accounts":
        if q.get("cursor") == "acc-p2":
            return {"accounts": [{"uuid": "a-ethx", "currency": "ETH", "available_balance": {"value": "1.5", "currency": "ETH"},
                                  "hold": {"value": "0", "currency": "ETH"}, "type": "ACCOUNT_TYPE_CRYPTO", "platform": "ACCOUNT_PLATFORM_INTX"},
                                 {"uuid": "a-eur", "currency": "EUR", "available_balance": {"value": "10", "currency": "EUR"},
                                  "hold": {"value": "0", "currency": "EUR"}, "type": "ACCOUNT_TYPE_FIAT", "platform": "ACCOUNT_PLATFORM_CONSUMER"}],
                    "has_next": False, "cursor": "", "size": 2}
        return {"accounts": [{"uuid": "a-btc", "currency": "BTC", "available_balance": {"value": "0.342", "currency": "BTC"},
                              "hold": {"value": "0.01", "currency": "BTC"}, "type": "ACCOUNT_TYPE_CRYPTO", "platform": "ACCOUNT_PLATFORM_CONSUMER"},
                             {"uuid": "a-usd", "currency": "USD", "available_balance": {"value": "605.00", "currency": "USD"},
                              "hold": {"value": "0", "currency": "USD"}, "type": "ACCOUNT_TYPE_FIAT", "platform": "ACCOUNT_PLATFORM_CONSUMER"},
                             {"uuid": "a-usdc", "currency": "USDC", "available_balance": {"value": "98.5", "currency": "USDC"},
                              "hold": {"value": "0", "currency": "USDC"}, "type": "ACCOUNT_TYPE_CRYPTO", "platform": "ACCOUNT_PLATFORM_CONSUMER"},
                             {"uuid": "a-eth", "currency": "ETH", "available_balance": {"value": "0", "currency": "ETH"},
                              "hold": {"value": "0", "currency": "ETH"}, "type": "ACCOUNT_TYPE_CRYPTO", "platform": "ACCOUNT_PLATFORM_CONSUMER"},
                             {"uuid": "a-mon", "currency": "MON", "available_balance": {"value": "500", "currency": "MON"},
                              "hold": {"value": "0", "currency": "MON"}, "type": "ACCOUNT_TYPE_VAULT", "platform": "ACCOUNT_PLATFORM_CONSUMER"}],
                "has_next": True, "cursor": "acc-p2", "size": 3}
    if p == "/v2/accounts":
        if q.get("starting_after") == "a-usdc":
            return {"pagination": {"next_uri": None, "limit": 100, "order": "desc"}, "data": V2_ACCTS[3:]}
        return {"pagination": {"next_uri": "/v2/accounts?limit=100&starting_after=a-usdc", "limit": 100, "order": "desc"}, "data": V2_ACCTS[:3]}
    if p.startswith("/v2/accounts/") and p.endswith("/transactions"):
        rows = TXS[p.split("/")[3]]
        i = 0
        if q.get("starting_after"):
            i = [r["id"] for r in rows].index(q["starting_after"]) + 1
        page = rows[i:i + 4]
        nxt = f"{p}?limit=100&starting_after={page[-1]['id']}" if i + 4 < len(rows) else None
        return {"pagination": {"next_uri": nxt, "limit": 100, "order": "desc"}, "data": page}
    if p == "/api/v3/brokerage/orders/historical/fills":
        if q.get("cursor") == "f-p2":
            return {"fills": FILLS2, "cursor": ""}
        return {"fills": FILLS1, "cursor": "f-p2"}
    raise AssertionError("모르는 경로 " + p)


def run():
    t0 = NOW - 7 * DAY
    bal = X.bal_coinbase(ENV)
    w, d = X.fetch_coinbase(ENV, t0, NOW)
    n1 = len(SEEN) if cas.record else cas.served
    w2, d2 = X.fetch_coinbase(ENV, t0, NOW)
    n2 = len(SEEN) if cas.record else cas.served
    cv = X.convert_coinbase(ENV, t0, NOW)
    fst = {}
    fl = X.fills_coinbase(ENV, fst, NOW - 3 * DAY, NOW)
    return {"bal": dict(bal), "w": w, "d": d, "same2": [w2 == w, d2 == d], "cv": list(cv), "cv_partial": getattr(cv, "error", None),
            "fills": fl, "fst": fst, "reuse_calls": n2 - n1}


cas = C.Cassette("exf_coinbase", secrets={"cb_name": NAME, "cb_secret": BODY}, responder=respond)
if cas.ready(T):
    out, why = cas.run(run)
    T.chk(why is None and isinstance(out, dict), "드라이버 4갈래 = 예외·새 요청 없음", why)
    if isinstance(out, dict):
        b = out["bal"]
        T.chk(b == {"BTC": 0.352, "USD": 605.0, "USDC": 138.5, "MON": 500.0},
              "[잔고] 현물·법정 USD·보관함 + v2 에만 있는 Raise 예치 계정(USDC 40) · INTX·EUR 뺌 · 2쪽(has_next) · 겹친 계정 두 번 안 셈", b)
        uw = {r["uuid"]: r for r in out["w"]}
        ud = {r["uuid"]: r for r in out["d"]}
        T.chk(set(uw) == {"coinbase:tx-0001", "coinbase:tx-0004", "coinbase:tx-0011"}, "[출금] 송금 2(진행 중 포함)·USD 출금 1", sorted(uw))
        T.chk(uw["coinbase:tx-0004"]["txid"] == HASH(0xB2) and uw["coinbase:tx-0004"]["state"] == "DONE"
              and uw["coinbase:tx-0004"]["amount"] == "0.10000000" and uw["coinbase:tx-0004"]["fee"] == "0.00010000"
              and uw["coinbase:tx-0004"]["address"].startswith("bc1q"), "[출금] txid·완료·양수 수량·수수료·목적지 주소")
        T.chk(uw["coinbase:tx-0001"]["state"] == "PENDING", "[출금] pending = PENDING(재확인 대상)")
        T.chk(set(ud) == {"coinbase:tx-0002", "coinbase:tx-0006", "coinbase:tx-0014", "coinbase:tx-0022"},
              "[입금] 받은 송금(양수 send)·온체인 입금·USD 입금·보상 · EUR 입금·advanced_trade_fill·창 밖(40일·30일) 뺌", sorted(ud))
        T.chk(ud["coinbase:tx-0022"].get("reward") == "interest" and ud["coinbase:tx-0006"]["state"] == "ACCEPTED"
              and ud["coinbase:tx-0014"]["currency"] == "USD", "[입금] 보상 표시 · ACCEPTED · USD 현금 = 원장 안")
        T.chk(out["same2"] == [True, True] and out["reuse_calls"] == 0, "[재사용] 같은 주기 두 번째 조회 = 같은 결과 · 요청 0", out["reuse_calls"])
        cv = {f["id"]: f for f in out["cv"]}
        T.chk(set(cv) == {"coinbase:cv:buy:buy-0001", "coinbase:cv:trade:trd-0001", "coinbase:cv:raise:tx-0061"} and out["cv_partial"],
              "[전환] buy·trade 짝 2건 · 토큰 세일 배분 1건 · 짝 없는 sell = 일부만(보류) · 예치(내 계정 간) = 기장 안 함", (sorted(cv), out["cv_partial"]))
        r1 = cv.get("coinbase:cv:raise:tx-0061") or {}
        T.chk((r1.get("base"), r1.get("quote"), r1.get("side"), r1.get("qty"), (r1.get("cv") or {}).get("from_amt")) == ("MON", "USDC", "buy", "500.00000000", "20.00"),
              "[세일] 배분 = USDC 20 → MON 500 매수(원가 승계)", r1)
        b1 = cv.get("coinbase:cv:buy:buy-0001") or {}
        T.chk((b1.get("base"), b1.get("quote"), b1.get("side"), b1.get("qty"), b1.get("price")) == ("BTC", "USD", "buy", "0.01000000", "25000"),
              "[전환] 간편 매수 = BTC/USD 매수 0.01 @ 250/0.01", b1)
        t1 = cv.get("coinbase:cv:trade:trd-0001") or {}
        T.chk({t1.get("base"), t1.get("quote")} == {"USD", "USDC"} and t1.get("price") in ("1", "1.0000"), "[전환] USD↔USDC = 가격 1", t1)
        fl = {f["id"]: f for f in out["fills"]}
        T.chk(set(fl) == {"coinbase:e-0001", "coinbase:e-0002"}, "[체결] FILL 2건(쪽 겹침 중복 1 제거) · REVERSAL·size_in_quote·선물·무기한(BTC-PERP) 보류", sorted(fl))
        e1 = fl.get("coinbase:e-0001") or {}
        T.chk((e1.get("base"), e1.get("quote"), e1.get("side"), e1.get("fee"), e1.get("fee_ccy")) == ("BTC", "USD", "buy", "7.2", "USD"),
              "[체결] 상품 분해·수수료 통화 = 쿼트", e1)
        T.chk("coinbase" in str(out["fst"].get("recon_hold")) and "cb_fill" in (out["fst"].get("hold_since") or {}),
              "[체결] 보류 체결 = 잔고 승격 보류 표시(상한 뒤 대사 흡수)", out["fst"])
    cas.golden(T, out)
    cas.check(T)

WROWS = [tx(71, "receive", "0.10000000", "BTC", DAY, network={"status": "confirmed", "hash": HASH(0xC1), "name": "bitcoin"}),
         tx(72, "receive", "0.20000000", "BTC", 10 * DAY, network={"status": "confirmed", "hash": HASH(0xC2), "name": "bitcoin"}),
         tx(73, "send", "-0.05000000", "BTC", 20 * DAY, status="pending", network={"status": "pending", "hash": HASH(0xC3), "name": "bitcoin"},
            to={"resource": "bitcoin_address", "address": "bc1qcassette2222222222222222222222222222"})]
WSTATE = {"acct": 0}


SEEN_W = []


def w_respond(rq):
    assert rq.host == "api.coinbase.com", rq.url
    p, q = rq.path, rq.query
    SEEN_W.append(p)
    if p == "/v2/accounts":
        WSTATE["acct"] += 1
        bal = "1.00" if WSTATE["acct"] == 1 else "1.10"
        return {"pagination": {"next_uri": None}, "data": [{"id": "w-btc", "balance": {"amount": bal, "currency": "BTC"}, "type": "wallet"}]}
    if p == "/v2/accounts/w-btc/transactions":
        ids = [r["id"] for r in WROWS]
        i = ids.index(q["starting_after"]) + 1 if q.get("starting_after") else 0
        nxt = f"{p}?limit=100&starting_after={WROWS[i]['id']}" if i + 1 < len(WROWS) else None
        return {"pagination": {"next_uri": nxt}, "data": WROWS[i:i + 1]}
    if p == "/api/v3/brokerage/orders/historical/fills":
        st9, en9, cur9 = q.get("start_sequence_timestamp"), q.get("end_sequence_timestamp"), q.get("cursor") or ""
        if st9 == C_ISO(NOW - 50 * H):
            return {"fills": [fill("e-r%d" % len(cur9), "BTC-USD", "BUY", "60000", "0.01", "0.1", 50 * H)], "cursor": "zz"}
        tag = f"{st9}|{en9}|{cur9}"
        if tag == f"{C_ISO(NOW - 10 * H)}|{C_ISO(NOW - 6 * H)}|":
            return {"fills": [fill("e-w1", "BTC-USD", "BUY", "60000", "0.01", "0.1", 9 * H)], "cursor": "c1"}
        if tag == f"{C_ISO(NOW - 10 * H)}|{C_ISO(NOW - 6 * H)}|c1":
            return {"fills": [fill("e-w2", "BTC-USD", "BUY", "60000", "0.01", "0.1", 8 * H)], "cursor": "c2"}
        return {"fills": [fill("e-w1", "BTC-USD", "BUY", "60000", "0.01", "0.1", 9 * H),
                          fill("e-s" + st9[11:13], "BTC-USD", "SELL", "60100", "0.01", "0.1", 7 * H)], "cursor": ""}
    raise AssertionError("모르는 경로 " + p)


def C_ISO(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(t)))


def run_win():
    X._V2.clear()
    a = X.fetch_coinbase(ENV, NOW - 150 * DAY, NOW)
    time.sleep(400)
    b = X.fetch_coinbase(ENV, NOW - 7 * DAY, NOW)
    c = X.fetch_coinbase(ENV, NOW - 150 * DAY, NOW)
    time.sleep(400)
    n0 = len(SEEN_W) if cas3.record else cas3.served
    X.fetch_coinbase(ENV, NOW - 7 * DAY, NOW)
    n1 = len(SEEN_W) if cas3.record else cas3.served
    X.fetch_coinbase(dict(ENV, TJ_COINBASE_KEY_NAME=NAME + "-2"), NOW - 7 * DAY, NOW)
    n2 = len(SEEN_W) if cas3.record else cas3.served
    out9, held9, ids9 = [], [], set()
    X._fills_window(ENV, NOW - 10 * H, NOW - 6 * H, out9, held9, ids9, page_max=2)
    err9 = None
    try:
        X._fills_window(ENV, NOW - 50 * H, NOW - 49 * H, [], [], set(), page_max=5)
    except RuntimeError as e:
        err9 = str(e)
    return {"a": sorted(r["uuid"] for r in a[0] + a[1]), "b": sorted(r["uuid"] for r in b[0] + b[1]), "c": sorted(r["uuid"] for r in c[0] + c[1]),
            "split": sorted(f["id"] for f in out9), "loop": err9, "same_bal_calls": n1 - n0, "new_key_calls": n2 - n1}


cas3 = C.Cassette("exf_coinbase_win", secrets={"cb_name": NAME, "cb_secret": BODY}, responder=w_respond)
if cas3.ready(T):
    out3, why3 = cas3.run(run_win)
    T.chk(why3 is None and isinstance(out3, dict), "창·쪽 시나리오 = 예외·새 요청 없음", why3)
    if isinstance(out3, dict):
        T.chk(out3["a"] == ["coinbase:tx-0071", "coinbase:tx-0072", "coinbase:tx-0073"] and out3["b"] == ["coinbase:tx-0071"],
              "W1 깊은 창 = 3행 · 얕은 창(7일) = 1행", out3)
        T.chk("coinbase:tx-0073" in out3["c"], "W1 얕게 다시 받은 뒤 깊은 창 = 그 계정 다시 받음(20일 전 진행 중 출금 돌아옴 · 종전 = 빠짐)", out3["c"])
        T.chk(len(out3["split"]) >= 3 and len(out3["split"]) == len(set(out3["split"])) and {"coinbase:e-w1", "coinbase:e-w2"} <= set(out3["split"]),
              "W2 쪽 상한 = 창을 반으로 나눠 끝까지(첫 창 2쪽 + 나눈 두 창 · 같은 id 한 번)", out3["split"])
        T.chk(out3["loop"] and "커서 반복" in out3["loop"], "W3 커서 반복 = 예외(완료 도장·과거 확장 전진 없음)", out3["loop"])
        T.chk(out3["new_key_calls"] >= 2, "W5 키를 바꾸면 같은 주기라도 옛 키로 받은 거래 캐시를 안 씀(키 범위)", out3["new_key_calls"])
        T.chk(out3["same_bal_calls"] >= 2, "W4 잔고가 그대로인 계정도 다음 주기에 다시 받음(건너뛴 동안 대사가 흡수한 행이 늦게 와 이중 계상되는 길 없음)", out3["same_bal_calls"])
    cas3.golden(T, out3)
    cas3.check(T)

import candles  # noqa: E402
import pricing  # noqa: E402


def px_respond(rq):
    assert rq.host == "api.coinbase.com" and "authorization" not in {k.lower() for k in (rq.headers or {})}, rq.url
    if rq.path == "/api/v3/brokerage/market/products":
        prods = [{"product_id": "BTC-USD", "price": "60000.5", "volume_24h": "1200", "approximate_quote_24h_volume": "7.2e7",
                  "base_currency_id": "BTC", "quote_currency_id": "USD", "status": "online", "trading_disabled": False, "is_disabled": False},
                 {"product_id": "BTC-USDC", "price": "59990", "volume_24h": "10", "base_currency_id": "BTC", "quote_currency_id": "USDC",
                  "status": "online", "trading_disabled": False},
                 {"product_id": "MON-USDC", "price": "0.045", "volume_24h": "900000", "base_currency_id": "MON", "quote_currency_id": "USDC",
                  "status": "online", "trading_disabled": False},
                 {"product_id": "OLD-USD", "price": "1.5", "volume_24h": "5", "base_currency_id": "OLD", "quote_currency_id": "USD",
                  "status": "delisted", "trading_disabled": True},
                 {"product_id": "ETH-BTC", "price": "0.05", "volume_24h": "5", "base_currency_id": "ETH", "quote_currency_id": "BTC", "status": "online"},
                 {"product_id": "DEAD-USD", "price": "2", "volume_24h": "0", "base_currency_id": "DEAD", "quote_currency_id": "USD", "status": "online"}]
        if rq.query.get("cursor") == "p2":
            return {"products": prods[3:] + [{"product_id": "MON-USD", "price": "0.0452", "volume_24h": "800000", "base_currency_id": "MON",
                                              "quote_currency_id": "USD", "status": "online", "trading_disabled": False}],
                    "num_products": len(prods) + 1, "pagination": {"has_next": False, "next_cursor": ""}}
        return {"products": prods[:3], "num_products": len(prods) + 1, "pagination": {"has_next": True, "next_cursor": "p2"}}
    if rq.path == "/api/v3/brokerage/market/products/MON-USD/candles":
        d0 = int(rq.query.get("end")) // 86400 * 86400
        return {"candles": [{"start": str(d0 - i * 86400), "low": "0.04", "high": "0.05", "open": "0.045", "close": str(0.04 + i / 1000),
                             "volume": "1000"} for i in range(3)]}
    raise AssertionError("모르는 경로 " + rq.path)


def run_px():
    spot = pricing.ex_spot_usd("coinbase")
    r = candles.fetch_cex("coinbase", "MON", "USD", "1d", NOW - 3 * DAY, NOW, now=NOW)
    return {"spot": spot, "dead": sorted(pricing.EX_DEAD_SYMS.get("coinbase") or ()), "candles": r.candles, "why": r.why}


cas2 = C.Cassette("px_coinbase", responder=px_respond)
if cas2.ready(T):
    out2, why2 = cas2.run(run_px)
    T.chk(why2 is None and isinstance(out2, dict), "공개 시세 = 예외·새 요청 없음", why2)
    if isinstance(out2, dict):
        T.chk(out2["spot"] == {"BTC": 60000.5, "MON": 0.0452}, "[시세] 두 쪽 다 받음(next_cursor) · 현물 USD 우선(뒤쪽 USD 책 포함) · 거래 중지·비활성·BTC 쿼트 뺌", out2["spot"])
        T.chk(out2["dead"] == ["DEAD"], "[시세] 24h 거래 0 = 멈춘 가격(뺌 · 종전 규약)", out2["dead"])
        T.chk(out2["why"] is None and [c[0] for c in out2["candles"] or []] == sorted(c[0] for c in out2["candles"] or [])
              and len(out2["candles"] or []) >= 2, "[일봉] 코인베이스 자체 일봉 = 과거→최신 정렬(장기 곡선 R89 자체 시세)", out2["candles"])
        T.chk(candles.market_name("coinbase", "mon", "usd") == "MON-USD", "[일봉] 마켓 이름 BASE-QUOTE")
    cas2.golden(T, out2)
    cas2.check(T)

L9 = NOW - 7 * DAY
RG = {"pool": [tx(81, "raise_offering_pooling", "-10.00", "USDC", NOW - (L9 - 600)), tx(84, "raise_offering_pooling", "-20.00", "USDC", NOW - (L9 + 600))],
      "dist": [tx(82, "raise_offering_distribution", "200", "BBB", NOW - (L9 - 300)), tx(83, "raise_offering_distribution", "100", "AAA", NOW - (L9 + 300))],
      "odd": []}
in_w = lambda t: X._in_win(t, L9 + X.OVERLAP, NOW)  # noqa: E731
f_all, b_all = X._raise_pairs(RG, in_w)
f_cut, _b = X._raise_pairs({k: [t for t in v if in_w(t)] for k, v in RG.items()})
T.chk(f_all == [] and b_all >= 1 and len(f_cut) == 1, "[세일] 창 밖 후보까지 보고 모호한 두 세일 = 보류(창 안 후보만 보면 잘못된 1:1 전환 — 종전)", (f_all, b_all, len(f_cut)))

T.chk(X.perm_of({"can_view": True, "can_trade": False, "can_transfer": False, "portfolio_uuid": "p", "portfolio_type": "DEFAULT"}) == [],
      "[권한] View 만 = 위험 0")
T.chk([k for k, _l in X.perm_of({"can_view": True, "can_trade": True, "can_transfer": True})] == ["trade", "withdraw"], "[권한] Trade·Transfer = 위험 2")
T.chk(X.perm_of({"can_view": True, "can_trade": "false", "can_transfer": False}) is None and X.perm_of([]) is None
      and X.perm_of({"can_view": False, "can_trade": False, "can_transfer": False}) is None, "[권한] 낯선 모양·View 없음 = 판정 불가(None)")
T.chk(exf_net._clock_parse("coinbase", {"data": {"iso": "x", "epoch": 1760000000}}, None) == 1760000000500
      and exf_net._clock_parse("coinbase", {"data": {}}, None) is None, "[시각] /v2/time epoch(초) → ms(+500) · 형식 오류 = None")
T.chk(json.dumps(ENV).count("BEGIN") == 0, "[키] .env 값 = base64 본문(머리·공백 없음)")
T.finish()
