#!/usr/bin/env python3
import itertools
import sys
from decimal import Decimal as D

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _costsim as S  # noqa: E402

import config  # noqa: E402
import core  # noqa: E402
import paths  # noqa: E402
import statefile  # noqa: E402

chk = T.chk


def new_core():
    c = core.Core(config.load_config())
    S._fake_px(c.px)
    S._C[0] = c
    return c


def run(order, mid, scale="1", fees=(10, -7), rewards=(4, 0), multi=False, base=100, known=0):
    sc = D(scale)
    seed = (base + 100) * sc
    S.reset(px={"TKJ": 2., "DUM": 1., "USDT": 1.}).conn.close()
    c = new_core()
    t = S.NOW - 1310
    first = t - 150
    S.PXF[0] = lambda sym, at: (1. if at < t + 150 else (3. if at < t + 300 else 2.)) if sym == "TKJ" else None
    S.ex("binance", deposits=[S.norm_row("binance", "seed", "USDT", str(seed), 0, "seed", "ACCEPTED", first - 30, first - 30)])
    S.fills("binance", [S.norm_fill("binance", "seedtkj", (first - 20) * 1000, "TKJ", "USDT", "buy", "1", str(base * sc), "0", ""),
                        S.norm_fill("binance", "seeddum", (first - 10) * 1000, "DUM", "USDT", "buy", "1", str(100 * sc), "0", "")])
    def total():
        q = "SELECT p.qty_base, a.decimals FROM postings p JOIN assets a USING(asset_id) WHERE p.location='exchange:binance' AND a.symbol=?"
        return {s: sum((D(int(r[0])) / D(10) ** int(r[1]) for r in c.conn.execute(q, (s,))), D(0)) for s in ("TKJ", "DUM", "USDT")}

    def recon(ts, bal):
        statefile.atomic_write_json(paths.state("exf_state.json"), {"binance": {"seen": {}, "backfilled_until": S.NOW, "fills": {"backfilled_until": S.NOW}}})
        statefile.atomic_write_json(paths.state("exf_balances_binance.json"), {"ts": ts, "balances": {k: float(v) for k, v in bal.items()}, "sources": ["spot"]})
        c._drain_at = ts + 5
        c.svc_exf._last_exfrecon = 0
        c.svc_exf.exf_recon_pass({"ex"})
        c.conn.commit()

    def consume(rows, cy):
        c.svc_exf._consume_exf_fills({"exchange": "binance", "fills": rows, "lc": cy, "lb": "binance:" + cy, "lbi": 0, "lbn": 1})
        c.svc_exf._late_cycle_done({"exchange": "binance", "lc": cy})
        c.conn.commit()
        c.svc_exf._exf_late_flush()
        c.conn.commit()

    recon(first, {"TKJ": base * sc, "DUM": 100 * sc, "USDT": 0})
    target = {"TKJ": (base + sum(rewards) - sum(fees) - known) * sc, "DUM": 80 * sc, "USDT": (20 + 2 * known) * sc}
    if multi:
        recon(t + 150, {"TKJ": (base + rewards[0]) * sc, "DUM": 100 * sc, "USDT": 0})
        recon(t + 300, {"TKJ": (base + sum(rewards) - fees[0]) * sc, "DUM": 90 * sc, "USDT": 10 * sc})
    if known:
        S.fills("binance", [S.norm_fill("binance", "known", (t + 400) * 1000, "TKJ", "USDT", "sell", "2", str(known * sc), "0", "")])
    recon(t + 1000, target)
    ev = {}
    for k, (tm, q) in enumerate(zip((100, 200), rewards)):
        if q:
            ev["i%d" % k] = {"id": "reward%d" % k, "ts": (t + tm) * 1000, "src": "income", "late": 1, "asset": "TKJ", "base": "TKJ",
                             "amount": str(D(q) * sc), "info": "합성 보상 %d" % k}
    for k, (tm, q) in enumerate(zip((250, 500), fees)):
        ev["f%d" % k] = dict(S.norm_fill("binance", "dumfee%d" % k, (t + tm) * 1000, "DUM", "USDT", "sell", "1", str(10 * sc), str(D(q) * sc), "TKJ"), late=1)
    for k, n in enumerate(order):
        consume([ev[n]], str(k))
        if mid:
            recon(t + 1100 + k * 20, target)
        c.conn.close()
        c = new_core()
    after = total()
    consume(list(ev.values()), "dupe")
    dupe = total()
    S.fills("binance", [S.norm_fill("binance", "liqtkj", (t + 1200) * 1000, "TKJ", "USDT", "sell", "2", str(target["TKJ"]), "0", ""),
                        S.norm_fill("binance", "liqdum", (t + 1250) * 1000, "DUM", "USDT", "sell", "1", str(target["DUM"]), "0", "")])
    cash = total()["USDT"]
    profit = cash - seed
    recon(t + 1300, {"TKJ": 0, "DUM": 0, "USDT": cash})
    f, _G, _rr = S.build()
    ok = (after == target and dupe == after and cash == (100 + 2 * known) * sc + 2 * target["TKJ"] and abs(S.realized(f) - float(profit)) < .011
          and abs(S.tax_sum(f) - float(profit)) < 1e-6)
    tag = "%s %s 중간 대사 %s ×%s 수수료 %s%s" % ("여러 구간" if multi else "한 구간", ",".join(order), "있음" if mid else "없음", scale, fees,
                                           " · 적은 보유 %s + 사이 매도 %s" % (base, known) if known else "")
    chk(ok, tag + ": 수량 = 실잔고 · 재전송 무동작 · 실현 = 세금용 = 현금 − 원금",
        {"after": {k: str(v) for k, v in after.items()}, "cash": str(cash), "profit": str(profit), "realized": S.realized(f), "tax": S.tax_sum(f)})


ORDERS = list(itertools.permutations(("i0", "f0", "f1")))
for o in ORDERS:
    run(o, False)
run(("f1", "f0", "i0"), True)
run(("i0", "f0", "f1"), True)
for o in ORDERS:
    run(o, True, multi=True)
run(("f1", "f0", "i0"), True, "1000", multi=True)
run(("i0", "f0", "f1"), True, "1000", multi=True)
run(("f1", "f0", "i0"), False, multi=True)
for o in ORDERS:
    run(o, False, base=12, known=5)
for o in (("i0", "f0", "f1"), ("f1", "f0", "i0")):
    run(o, True, fees=(10, 7))
    run(o, False, fees=(10, 7), multi=True)
T.finish()
