#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _costsim as S  # noqa: E402

import random  # noqa: E402
import time  # noqa: E402
import zlib  # noqa: E402
from decimal import Decimal as D  # noqa: E402

chk = T.chk
DAY = 86400
TIME_CAP_S = 240
TOL = 0.05


def q8(x):
    return x.quantize(D("0.00000001"), rounding="ROUND_DOWN")


def q6(x):
    return x.quantize(D("0.000001"), rounding="ROUND_DOWN")


def price_fn(prb, t0):
    def pf(sym, ts):
        if sym in prb:
            k = (ts - t0) / 86400.0
            return round(prb[sym] * (1 + 0.004 * k + 0.05 * ((zlib.crc32((sym + str(int(k))).encode()) % 7) - 3) / 3), 6)
        return None
    return pf


def gen_exchanges(seed, nops):
    rnd = random.Random(seed)
    t0 = S.NOW - 60 * DAY
    prb = {"BTC": 50000.0, "ETH": 2500.0, "SOL": 150.0, "BNB": 600.0}
    pf = price_fn(prb, t0)
    exs = ["binance", "okx", "bybit", "gate"]
    bal = {}
    recs = []

    def add(ex, sym, q):
        bal[(ex, sym)] = bal.get((ex, sym), D(0)) + q
    start = D(100000)
    t = t0
    for ex in exs:
        recs.append(("ex", ex, {"deposits": [S.norm_row(ex, "fund", "USDT", str(start), 0, "f" + ex, "ACCEPTED", t, t)]}))
        add(ex, "USDT", start)
    n = 0
    for _i in range(nops):
        t += rnd.randint(600, 30000)
        ex = rnd.choice(exs)
        op = rnd.random()
        if op < 0.5:
            base = rnd.choice(list(prb))
            quote = rnd.choice(["USDT", "USDC"] + [x for x in ("BTC", "ETH") if x != base])
            pb = D(str(pf(base, t)))
            pq = D(1) if quote in ("USDT", "USDC") else D(str(pf(quote, t)))
            px = (pb / pq).quantize(D("0.00000001"))
            side = rnd.choice(["buy", "sell"])
            fee_mode = rnd.choice(["none", "base", "quote", "bnb", "rebate"])
            if side == "buy":
                avail = bal.get((ex, quote), D(0))
                if quote == "USDC" and avail < 100:
                    continue
                qty = q8(q8(avail * D(str(rnd.uniform(0.05, 0.4)))) / px)
            else:
                qty = q8(bal.get((ex, base), D(0)) * D(str(rnd.choice([0.3, 0.5, 1.0, 1.0]))))
            if qty <= D("0.0001"):
                continue
            gross = qty * px
            fee, fccy = D(0), ""
            if fee_mode == "base":
                fee, fccy = q8(qty * D("0.001")), base
            elif fee_mode == "quote":
                fee, fccy = q8(gross * D("0.001")), quote
            elif fee_mode == "bnb" and bal.get((ex, "BNB"), D(0)) > D("0.01"):
                fee, fccy = D("0.001"), "BNB"
            elif fee_mode == "rebate":
                fee, fccy = -q8(gross * D("0.0002")), quote
            need = {quote: gross + (fee if fccy == quote and fee > 0 else 0)} if side == "buy" else {base: qty + (fee if fccy == base else 0)}
            if fccy == "BNB":
                need["BNB"] = need.get("BNB", 0) + fee
            if any(bal.get((ex, s), D(0)) < v for s, v in need.items()):
                continue
            n += 1
            recs.append(("fills", ex, [S.norm_fill(ex, f"{base}{quote}:{n}", t * 1000, base, quote, side, format(px, "f"), format(qty, "f"),
                                                   format(fee, "f"), fccy)]))
            sg = 1 if side == "buy" else -1
            add(ex, base, sg * qty)
            add(ex, quote, -sg * q8(gross))
            if fee and fccy:
                add(ex, fccy, -fee)
        elif op < 0.7:
            syms = [s for (e, s), v in bal.items() if e == ex and v > D("0.001") and s != "USDC"]
            if not syms:
                continue
            s = rnd.choice(syms)
            dst = rnd.choice([e for e in exs if e != ex])
            amt = q8(bal[(ex, s)] * D(str(rnd.uniform(0.2, 0.9))))
            wfee = q8(amt * D("0.0005"))
            if amt <= wfee * 2 or amt + wfee > bal[(ex, s)]:
                continue
            n += 1
            tx = f"0xtx{seed}_{n}"
            recs.append(("ex", ex, {"withdraws": [S.norm_row(ex, f"w{n}", s, format(amt, "f"), format(wfee, "f"), tx, "DONE", t, t + 120,
                                                             address="0x" + "11" * 20, network="X")]}))
            inamt = ex == "gate"
            arr = amt - wfee if inamt else (q8(amt * D("0.995")) if rnd.random() < 0.3 else amt)
            recs.append(("ex", dst, {"deposits": [S.norm_row(dst, f"d{n}", s, format(arr, "f"), 0, tx, "ACCEPTED", t + 600, t + 600)]}))
            t += 600
            add(ex, s, -amt - (0 if inamt else wfee))
            add(dst, s, arr)
        elif op < 0.85:
            syms = [s for (e, s), v in bal.items() if e == ex and v > D("0.001")]
            if not syms:
                continue
            fs = rnd.choice(syms)
            ts_ = rnd.choice([s for s in list(prb) + ["USDT"] if s != fs])
            famt = q8(bal[(ex, fs)] * D(str(rnd.uniform(0.2, 0.7))))
            pfr = D(1) if fs in ("USDT", "USDC") else D(str(pf(fs, t)))
            pto = D(1) if ts_ in ("USDT", "USDC") else D(str(pf(ts_, t)))
            tamt = q8(famt * pfr / pto * D("0.998"))
            if famt <= 0 or tamt <= 0:
                continue
            from exf_net import _cv_fill
            n += 1
            recs.append(("fills", ex, [_cv_fill(ex, f"cv{n}", t * 1000, fs, format(famt, "f"), ts_, format(tamt, "f"))]))
            add(ex, fs, -famt)
            add(ex, ts_, tamt)
        else:
            syms = [s for (e, s), v in bal.items() if e == "binance" and v > D("0.001")]
            if not syms:
                continue
            s = rnd.choice(syms)
            amt = q8(bal[("binance", s)] * D(str(rnd.uniform(0.2, 0.8))))
            if amt <= 0:
                continue
            n += 1
            recs.append(("ex", "binance", {"withdraws": [S.norm_row("binance", f"ow{n}", s, format(amt, "f"), "0", f"Off-chain transfer {seed}{n}1",
                                                                     "DONE", t, t, address="me@x", network="")]}))
            recs.append(("ex", "binance", {"deposits": [S.norm_row("binance", f"od{n}", s, format(amt, "f"), 0, f"Off-chain transfer {seed}{n}2",
                                                                    "ACCEPTED", t + 3600, t + 3600)]}))
            t += 3600
    return recs, pf, float(start) * len(exs), n


def gen_wallet(seed, nops):
    rnd = random.Random(seed)
    t0 = S.NOW - 60 * DAY
    prb = {"ETH": 2500.0, "BTC": 50000.0}
    pf = price_fn(prb, t0)
    exs = ["binance", "okx"]
    start = D(50000)

    def run(c):
        ch = S.Ch(c)
        eth_w = ch.tok("base", None, "ETH", 18, kind="native")
        usdc_w = ch.tok("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6)
        wtok = {"ETH": eth_w, "USDC": usdc_w}
        bal = {}

        def add(loc, sym, q):
            bal[(loc, sym)] = bal.get((loc, sym), D(0)) + q
        t = t0
        for ex in exs:
            S.ex(ex, deposits=[S.norm_row(ex, "fund", "USDT", str(start), 0, "f" + ex, "ACCEPTED", t, t)])
            S.ex(ex, deposits=[S.norm_row(ex, "fundc", "USDC", str(start), 0, "fc" + ex, "ACCEPTED", t, t)])
            add(ex, "USDT", start)
            add(ex, "USDC", start)
        n = 0
        for _i in range(nops):
            t += rnd.randint(1200, 30000)
            op = rnd.random()
            ex = rnd.choice(exs)
            if op < 0.4:
                base, quote = rnd.choice(["ETH", "BTC"]), rnd.choice(["USDT", "USDC"])
                px = D(str(pf(base, t)))
                side = rnd.choice(["buy", "sell"])
                av = bal.get((ex, quote if side == "buy" else base), D(0))
                if side == "buy":
                    if av < 50:
                        continue
                    qty = q8(av * D(str(rnd.uniform(0.05, 0.4))) / px)
                else:
                    qty = q8(av * D(str(rnd.choice([0.5, 1.0]))))
                if qty <= D("0.0001"):
                    continue
                n += 1
                S.fills(ex, [S.norm_fill(ex, f"{base}{quote}:{n}", t * 1000, base, quote, side, format(px, "f"), format(qty, "f"), "0", "")])
                sg = 1 if side == "buy" else -1
                add(ex, base, sg * qty)
                add(ex, quote, -sg * q8(qty * px))
            elif op < 0.6:
                s = rnd.choice(["ETH", "USDC"])
                av = bal.get((ex, s), D(0))
                if av <= D("0.01"):
                    continue
                amt = q6(av * D(str(rnd.uniform(0.3, 0.9))))
                wfee = D("0.0005") if s == "ETH" else D("1")
                if amt <= wfee * 2 or amt + wfee > av:
                    continue
                n += 1
                tx = "0x" + format(zlib.crc32(f"w{seed}:{n}".encode()), "08x") * 8
                S.ex(ex, withdraws=[S.norm_row(ex, f"w{n}", s, format(amt, "f"), format(wfee, "f"), tx, "DONE", t, t + 60, address=S.WA, network="BASE")])
                c._post_leg("chain_tx", "base", tx, 0, t + 300, wtok[s], f"wallet:base:{S.WA}", int(amt * D(10) ** ch.dec[wtok[s]]), None, None, "acq", "TRANSFER_IN")
                c.conn.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES ('base',?,?,'{}',5)", (tx, "TRANSFER_IN"))
                add(ex, s, -amt - wfee)
                add("w", s, amt)
            elif op < 0.8:
                s = rnd.choice(["ETH", "USDC"])
                av = bal.get(("w", s), D(0))
                if av <= D("0.01"):
                    continue
                amt = q6(av * D(str(rnd.uniform(0.3, 1.0))))
                if amt <= 0:
                    continue
                n += 1
                tx = "0x" + format(zlib.crc32(f"d{seed}:{n}".encode()), "08x") * 8
                c._post_leg("chain_tx", "base", tx, 0, t, wtok[s], f"wallet:base:{S.WA}", -int(amt * D(10) ** ch.dec[wtok[s]]), None, None, "move_out", "TRANSFER_OUT_EX")
                gq = D("0.0002")
                if bal.get(("w", "ETH"), D(0)) - (amt if s == "ETH" else 0) > gq:
                    c._post_leg("chain_tx", "base", tx, 1, t, eth_w, f"wallet:base:{S.WA}", -int(gq * D(10) ** 18), repr(float(gq * D(str(pf("ETH", t))))),
                                None, "gas", "TRANSFER_OUT_EX")
                    add("w", "ETH", -gq)
                c.conn.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES ('base',?,?,'{}',5)", (tx, "TRANSFER_OUT_EX"))
                S.ex(ex, deposits=[S.norm_row(ex, f"d{n}", s, format(amt, "f"), 0, tx, "ACCEPTED", t + 600, t + 600)])
                add("w", s, -amt)
                add(ex, s, amt)
            else:
                px = D(str(pf("ETH", t)))
                if rnd.random() < 0.5:
                    av = bal.get(("w", "USDC"), D(0))
                    if av < 20:
                        continue
                    usd = q6(av * D(str(rnd.uniform(0.2, 0.8))))
                    eq = (usd / px).quantize(D("0.000000000001"), rounding="ROUND_DOWN")
                    legs = [(usdc_w, -usd, "disp", usd), (eth_w, eq, "acq", usd)]
                    add("w", "USDC", -usd)
                    add("w", "ETH", eq)
                else:
                    av = bal.get(("w", "ETH"), D(0))
                    if av < D("0.002"):
                        continue
                    eq = (av * D(str(rnd.uniform(0.2, 0.9)))).quantize(D("0.000000000001"), rounding="ROUND_DOWN")
                    usd = q6(eq * px)
                    legs = [(eth_w, -eq, "disp", usd), (usdc_w, usd, "acq", usd)]
                    add("w", "ETH", -eq)
                    add("w", "USDC", usd)
                n += 1
                ch.tx("base", f"sw{seed}:{n}", t, legs, "SWAP")
        return n
    return run, pf, float(start) * len(exs) * 2


def measure(f, G, init):
    rz = S.realized(f)
    unv = {u["sym"]: round(float(u["proceeds"]), 2) for u in (getattr(RR[0], "unverified", None) or {}).values() if u["proceeds"] > D("0.01")}
    return {"I1": round(S.cost_end(G) - rz - init, 4), "I2": round(S.tax_sum(f) - rz, 4), "rz": round(rz, 4), "unk": S.unknown(G), "unv": unv}


RR = [None]


def run_exchanges(seed, nops, feed="seq"):
    recs, pf, init, n = gen_exchanges(seed, nops)
    S.reset(px={"USDT": 1., "USDC": 1., "ETH": 2500., "BTC": 50000., "SOL": 150., "BNB": 600.}, pxf=pf)
    if feed == "shuffle":
        head, rest = recs[:4], recs[4:]
        random.Random(seed * 7 + 1).shuffle(rest)
        recs = head + rest
    elif feed == "dup":
        recs = recs + recs
    for kind, ex, rec in recs:
        if kind == "ex":
            S.ex(ex, **rec)
        else:
            S.fills(ex, rec)
    f, G, RR[0] = S.build(prefs={"offchain_self": {"binance": True}})
    return dict(measure(f, G, init), ops=n)


def run_wallet(seed, nops):
    run, pf, init = gen_wallet(seed, nops)
    c = S.reset(px={"USDT": 1., "USDC": 1., "ETH": 2500., "BTC": 50000.}, pxf=pf)
    n = run(c)
    f, G, RR[0] = S.build()
    return dict(measure(f, G, init), ops=n)


def ok(r):
    return bool(r) and abs(r["I1"]) <= TOL and abs(r["I2"]) <= TOL and not r["unk"] and not r["unv"]


t_start = time.time()
done = []
for seed in (11, 12, 13, 17):
    if time.time() - t_start > TIME_CAP_S:
        break
    r = T.safe(run_exchanges, seed, 60) or {}
    done.append(("ex", seed))
    chk(ok(r), f"거래소 시드 {seed}({r.get('ops')}건): I1 원가 불변식 · I2 명세 = 실현 · 원가 미상 0", r)
for seed in (3, 5):
    if time.time() - t_start > TIME_CAP_S:
        break
    r = T.safe(run_wallet, seed, 60) or {}
    done.append(("exw", seed))
    chk(ok(r), f"거래소+지갑 시드 {seed}({r.get('ops')}건): I1 · I2 · 원가 미상 0", r)
if time.time() - t_start <= TIME_CAP_S:
    base = T.safe(run_exchanges, 11, 60) or {}
    shuf = T.safe(run_exchanges, 11, 60, "shuffle") or {}
    dup = T.safe(run_exchanges, 11, 60, "dup") or {}
    done.append(("feed", 11))
    chk(ok(shuf), "순서 섞음(시드 11) — 같은 기록 다른 순서에도 I1 · I2 · 원가 미상 0", shuf)
    chk(ok(dup) and base and abs(dup["rz"] - base["rz"]) <= 0.01, "중복(시드 11) — 같은 기록 두 번 = 한 번과 같은 실현(멱등)", {"base": base.get("rz"), "dup": dup.get("rz")})
chk(len(done) >= 3, f"시간 상한 {TIME_CAP_S}초 안에 돈 묶음 {len(done)}개(3개 이상)", {"done": done, "s": round(time.time() - t_start, 1)})
T.finish()
