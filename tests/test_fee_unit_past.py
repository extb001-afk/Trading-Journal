#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

from decimal import Decimal  # noqa: E402

import accounting_books  # noqa: E402
import accounting_fee  # noqa: E402
import acct_norm  # noqa: E402

chk = T.chk
TS = 1_700_000_000


class Spot:
    def __init__(self, p):
        self.p = p

    def price(self, s):
        return self.p


class SB:
    pass


def book(now_px, cand):
    sb = SB()
    sb.spot = Spot(now_px)
    fb = accounting_fee.FeeBook(sb=sb, books=accounting_books.Books(), kst_fmt=None, cb=None)
    fb.fxb = acct_norm.FxBook({}, None, 1400.0, web_candle=cand)
    return fb


def g(sym="BTC", stable=False, qk=0, cost=0):
    return {"is_stable": stable, "is_fiat": False, "sym": sym, "qty_known": Decimal(qk), "cost": Decimal(cost)}


m = TS * 1000 // 60_000 * 60_000
u1 = book(60000.0, {}).fee_unit(g(), TS, None)
u2 = book(90000.0, {}).fee_unit(g(), TS, None)
chk(u1 is None and u2 is None, "P1 캔들·평단 없음 = None(지금 시세로 안 메꿈)", (u1, u2))
u = book(90000.0, {f"BTC:{m + 30 * 60_000}": 37000.0}).fee_unit(g(), TS, None)
chk(u == Decimal("37000.0"), "P2 30분 옆 캐시 봉 = 그 값", u)
u = book(90000.0, {f"BTC:{m + 3 * 86400_000}": 41000.0}).fee_unit(g(), TS, None)
chk(u is None, "P3 3일 떨어진 캐시 봉 = 안 씀(평단 없으면 None)", u)
u = book(90000.0, {f"BTC:{m + 3 * 86400_000}": 41000.0}).fee_unit(g(qk=2, cost=70000), TS, None)
chk(u == Decimal(35000), "P3 3일 떨어진 봉 대신 그룹 평단", u)
u = book(90000.0, {}).fee_unit(g(), TS, Decimal(36000))
chk(u == Decimal(36000), "P4 소진 평단(wac9) = 그 값", u)
chk(book(90000.0, {}).fee_unit(g("USDT", stable=True), TS, None) == Decimal(1), "P4 스테이블 = 1")

T.finish()
