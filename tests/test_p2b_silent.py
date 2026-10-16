#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import logging
import os
import time
from decimal import Decimal

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import calcguard as CG
import common
import core
import core_pricing

assert T.TMP in common.STATE_DIR
core.dm = lambda *a, **k: None
T.patch_moved("dm", core.dm)
chk = T.chk
NOW = int(time.time())
E8 = 10 ** 8
SITE = "core_exf:ExfMixin._consume_exf_fills:skip"


class _Cap(logging.Handler):
    def __init__(self):
        super().__init__()
        self.msgs = []

    def emit(self, r):
        self.msgs.append(r.getMessage())


cap = _Cap()
logging.getLogger("tj-core").addHandler(cap)
BTC_PX = {}


def mk_core():
    c9 = core.Core(common.load_config())
    c9.px.fx_at = lambda ms: 1380.0
    c9.px.candle_usd = lambda sym, ms: BTC_PX.get(str(sym).upper())
    c9.px.flush = lambda: None
    return c9


def fill(fid, side="buy", qty="1", price="3000", quote="USDT", base="ETH", ts=None):
    return {"id": fid, "ts": (ts or NOW - 3600) * 1000, "base": base, "quote": quote, "side": side, "price": price, "qty": qty,
            "fee": "0", "fee_ccy": base}


def legs(c9, fid, ex="binance"):
    return [(r[0], int(r[1]), r[2]) for r in c9.conn.execute(
        "SELECT leg_seq, qty_base, cost_usd FROM postings WHERE source_ns=? AND source_id=? ORDER BY leg_seq", (f"{ex}:trade", fid))]


def raw_has(c9, fid, ex="binance"):
    return bool(c9.conn.execute("SELECT 1 FROM raw_ex WHERE exchange=? AND kind='trade' AND uuid=?", (ex, fid)).fetchone())


def site_n():
    return int((CG.snapshot().get(SITE) or {}).get("n") or 0)


c = mk_core()

bad = [fill("binance:ETHUSDT:b1", qty="0"), fill("binance:ETHUSDT:b2", side="hold"), fill("binance:ETHUSDT:b3", ts=-1)]
n0 = site_n()
cap.msgs.clear()
c._consume_exf_fills({"exchange": "binance", "fills": bad})
c.conn.commit()
chk(all(raw_has(c, f["id"]) and not legs(c, f["id"]) for f in bad), "S1 형식 이상 = 원본 보존 · 기장 없음(재구축이 원본에서 다시 시도)",
    [(f["id"], raw_has(c, f["id"]), legs(c, f["id"])) for f in bad])
chk(site_n() - n0 == 3 and sum("기장 안 됨" in m for m in cap.msgs) == 3 and any("qty ≤ 0" in m for m in cap.msgs) and any("side 가 buy/sell 아님" in m for m in cap.msgs), "S1 ★누락마다 경고 로그 + calcguard 기록★(종전 = 무음)",
    (site_n() - n0, cap.msgs))
chk(CG.snapshot().get(SITE, {}).get("bug") in (0, None), "S1 데이터 탓 = 코드 실수 꼴 아님(빨강·텔레그램 없음 · calc:swallow 정보)", CG.snapshot().get(SITE))
c._consume_exf_fills({"exchange": "binance", "fills": bad})
chk(site_n() - n0 == 3, "S1 같은 체결 다시 옴 = 멱등(기록 늘지 않음)", site_n() - n0)
n1 = site_n()
c._consume_exf_fills({"exchange": "binance", "fills": [fill("binance:ETHUSDT:g1")]})
c.conn.commit()
chk(site_n() == n1 and [l9[:2] for l9 in legs(c, "binance:ETHUSDT:g1")] == [(0, E8), (1, -3000 * E8)], "S1 정상 체결 = 기장 · 기록 없음",
    legs(c, "binance:ETHUSDT:g1"))

SECRET = "ab'cd\"ef-SYNTH-SECRET"
cap.msgs.clear()
c._consume_exf_fills({"exchange": "binance", "fills": [fill("binance:ETHUSDT:b9", qty=SECRET)]})
c.conn.commit()
CG.flush()
d9 = open(CG.path_of(), encoding="utf-8").read() if os.path.exists(CG.path_of()) else ""
chk(not any("SYNTH-SECRET" in m for m in cap.msgs) and "SYNTH-SECRET" not in d9 and any("qty 숫자 아님" in m for m in cap.msgs),
    "S1b 로그·calcguard 파일에 원문 값 없음(칸 이름·종류만)", cap.msgs)

q = "0.123456789"
c._consume_exf_fills({"exchange": "binance", "fills": [fill("binance:ETHUSDT:t1", qty=q, price="1"), fill("binance:ETHUSDT:t2", side="sell", qty=q, price="1")]})
c.conn.commit()
b1, s1 = legs(c, "binance:ETHUSDT:t1")[0][1], legs(c, "binance:ETHUSDT:t2")[0][1]
err = Decimal(q) - Decimal(b1) / E8
chk(b1 == 12345678 and Decimal(0) <= err < Decimal("1e-8"), "S2 버림 오차 < 1e-8(체결 1건)", (b1, err))
chk(b1 + s1 == 0, "S2 동일 수량 1:1 매수·매도 = 왕복 잔량 0(분할 체결은 별도)", (b1, s1))

BTC_PX.clear()
c._consume_exf_fills({"exchange": "binance", "fills": [fill("binance:ETHBTC:q1", quote="BTC", price="0.05", qty="2")]})
c.conn.commit()
chk([l9[2] for l9 in legs(c, "binance:ETHBTC:q1")] == [None, None], "S3 시세 없음 = 원가 미상(지어내지 않음)", legs(c, "binance:ETHBTC:q1"))
BTC_PX["BTC"] = 60000.0
core_pricing.time.sleep = lambda s: None
T.patch_moved("PRICE_IDLE_SEC", 0)
c._last_price_pass = 0
c.price_pass()
cu = [l9[2] for l9 in legs(c, "binance:ETHBTC:q1")]
chk(cu[0] is not None and abs(float(cu[0]) - 6000.0) < 1e-6 and cu[1] == cu[0], "S3 ★가격 패스가 원본에서 소급(2×0.05×60,000 = $6,000 · 두 레그)★", cu)

calls = []
c._price_tx = lambda ch, h: calls.append(h) or False
c.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw,"
               " leg_kind, event, classifier_ver) VALUES ('chain_tx', 'eth', '0xfeed', 0, ?, 1, 'w:x', '-1', NULL, NULL, 'gas', 'GAS', 1)", (NOW - 60,))
c.conn.commit()
c._last_price_pass = 0
c.price_pass()
c._last_price_pass = 0
c.price_pass()
bo = c._px_backoff.get(("eth", "0xfeed"))
chk(calls == ["0xfeed"] and bo and bo[1] >= core_pricing.PRICE_BACKOFF_MIN and bo[0] > time.time(), "S4 못 찾은 tx = 백오프(바로 다음 패스에 다시 안 집음)",
    (calls, bo))

T.finish()
