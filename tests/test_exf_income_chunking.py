#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _costsim as S  # noqa: E402

from decimal import Decimal as D  # noqa: E402

import config  # noqa: E402
import core  # noqa: E402
import paths  # noqa: E402
import statefile  # noqa: E402

chk = T.chk
T0 = S.NOW - 1000


def recon(c, ts, bal):
    statefile.atomic_write_json(paths.state("exf_state.json"), {"binance": {"seen": {}, "backfilled_until": S.NOW, "fills": {"backfilled_until": S.NOW}}})
    statefile.atomic_write_json(paths.state("exf_balances_binance.json"), {"ts": ts, "balances": bal, "sources": ["spot"]})
    c._drain_at = ts + 5
    c.svc_exf._last_exfrecon = 0
    c.svc_exf.exf_recon_pass({"ex"})
    c.conn.commit()


def totals(c):
    out = {}
    for s9 in ("TKJ", "USDT", "DUM"):
        out[s9] = sum((D(int(r[0])) / D(10) ** int(r[1]) for r in c.conn.execute(
            "SELECT p.qty_base, a.decimals FROM postings p JOIN assets a USING(asset_id) WHERE p.location='exchange:binance' AND a.symbol=?", (s9,))), D(0))
    return out


def n_off(c):
    return c.conn.execute("SELECT count(*) FROM postings WHERE source_id LIKE 'exflate:%'").fetchone()[0]


def n_pend(c):
    return c.conn.execute("SELECT count(*) FROM exf_late_pending WHERE substr(lb, 1, 5) != '@inc:'").fetchone()[0]


def n_keep(c):
    return c.conn.execute("SELECT count(*) FROM exf_late_pending WHERE substr(lb, 1, 5) = '@inc:' AND sym IS NOT NULL").fetchone()[0]


def late(f):
    return dict(f, late=1)


def new_core():
    c = core.Core(config.load_config())
    S._fake_px(c.px)
    S._C[0] = c
    c.svc_exf.EXF_INIT_PHASE = 5
    return c


def fillers():
    sides = [("buy" if i % 2 == 0 else "sell", "1") for i in range(496)] + [("buy", "1"), ("sell", "0.5"), ("sell", "0.5")]
    return [late(S.norm_fill("binance", f"binance:DUMUSDT:{i}", (T0 + 1 + i // 6) * 1000, "DUM", "USDT", sd, "1", q, "0", ""))
            for i, (sd, q) in enumerate(sides)]


def run(parts, restart_at=None, inc_amt="10", sell=True, extra=()):
    S.reset(px={"USDT": 1., "TKJ": 1., "DUM": 1.}).conn.close()
    c = new_core()
    S.ex("binance", deposits=[S.norm_row("binance", "seed", "USDT", "100", 0, "seed", "ACCEPTED", T0 - 20, T0 - 20)])
    S.fills("binance", [S.norm_fill("binance", "seedbuy", (T0 - 10) * 1000, "TKJ", "USDT", "buy", "1", "100", "0", "")])
    recon(c, T0, {"TKJ": 100, "USDT": 0})
    recon(c, T0 + 300, {"TKJ": 100, "USDT": 10 if sell else 0})
    pre = totals(c)
    for i, rows in enumerate(parts):
        if restart_at is not None and i == restart_at:
            c.conn.commit()
            c.conn.close()
            c = new_core()
        c.svc_exf._consume_exf_fills({"v": 1, "kind": "exf_fills", "exchange": "binance", "ts": S.NOW, "fills": rows,
                                      "lb": "binance:cyc", "lbi": i, "lbn": len(parts), "lc": "cyc"})
        c.conn.commit()
    c.svc_exf._late_cycle_done({"exchange": "binance", "lc": "cyc"})
    c.conn.commit()
    c.svc_exf._exf_late_flush()
    c.conn.commit()
    after, off, pend = totals(c), n_off(c), n_pend(c)
    for i, rows in enumerate(parts):
        c.svc_exf._consume_exf_fills({"exchange": "binance", "fills": rows, "lb": "binance:cyc2", "lbi": i, "lbn": len(parts), "lc": "cyc2"})
    c.svc_exf._late_cycle_done({"exchange": "binance", "lc": "cyc2"})
    c.conn.commit()
    c.svc_exf._exf_late_flush()
    c.conn.commit()
    dup_ok = totals(c) == after and n_off(c) == off and n_pend(c) == 0
    return c, pre, after, off, pend, dup_ok


INC = {"id": "binance:div:1", "ts": (T0 + 100) * 1000, "src": "income", "late": 1, "asset": "TKJ", "base": "TKJ", "amount": "10", "info": "Launchpool"}
SELL = late(S.norm_fill("binance", "binance:TKJUSDT:1", (T0 + 200) * 1000, "TKJ", "USDT", "sell", "1", "10", "0", ""))
F499 = fillers()
EV = F499 + [SELL]
SPLITS = {
    "1 레코드": ([EV + [INC]], None),
    "500+1": ([EV, [INC]], None),
    "1+500": ([[INC], EV], None),
    "작은 여러 레코드": ([EV[k:k + 120] for k in range(0, 360, 120)] + [[INC]] + [EV[360:]], None),
    "500+1 사이 재시작": ([EV, [INC]], 1),
    "1+500 사이 재시작": ([[INC], EV], 1),
}
res = {}
for name, (parts, rs) in SPLITS.items():
    c, pre, after, off, pend, dup_ok = run(parts, rs)
    chk(pre == {"TKJ": D(100), "USDT": D(10), "DUM": D(0)}, f"K1 준비({name}): 대사된 시작 잔고 TKJ 100 · USDT 10", pre)
    chk(after == pre and off == 0 and pend == 0, f"K1 {name}: 드레인 끝 원장 합 = 시작 · 상쇄 줄 0 · 대기표 비움",
        {"after": {k: str(v) for k, v in after.items()}, "off": off, "pend": pend})
    chk(dup_ok, f"K2 {name}: 같은 주기 다시 = 무동작")
    S.PX["TKJ"] = 2.
    S.fills("binance", [S.norm_fill("binance", "binance:TKJUSDT:2", (T0 + 350) * 1000, "TKJ", "USDT", "sell", "2", "10", "0", "")])
    f0, G0, _ = S.build()
    c = new_core()
    recon(c, T0 + 400, {"TKJ": 90, "USDT": 30, "DUM": 0})
    post = totals(c)
    f, G, _ = S.build()
    res[name] = {"qty_mid": round(sum(float(g["qty_known"] + g["qty_unknown"]) for g in G0.values() if g["sym"] == "TKJ"), 8),
                 "real_mid": round(S.realized(f0), 6), "qty": round(sum(float(g["qty_known"] + g["qty_unknown"]) for g in G.values() if g["sym"] == "TKJ"), 8),
                 "real": round(S.realized(f), 6), "tax": round(S.tax_sum(f), 6), "unk": S.unknown(G), "post": {k: str(v) for k, v in post.items()}}
    chk(post == {"TKJ": D(90), "USDT": D(30), "DUM": D(0)}, f"K3 {name}: 다음 대사 뒤 원장 = 실잔고", res[name]["post"])
    chk(abs(res[name]["real"] - 20) < 1e-6 and abs(res[name]["tax"] - 20) < 1e-6 and not res[name]["unk"],
        f"K3 {name}: 지급 10 + 매매이익 10 = 실현·세금용 20 · 원가 미상 0(중간 거래 원가가 가짜 수량에 안 섞임)", res[name])
base = res["1 레코드"]
chk(all(v == base for v in res.values()), "K3 나눔·재시작과 무관하게 수량·실현·세금용·원가 미상이 같음(중간 시점 포함)",
    {k: v for k, v in res.items() if v != base})

for name, parts in {"혼자 남은 지급 1 레코드": [F499 + [INC]], "혼자 남은 지급 나눔": [F499, [INC]]}.items():
    c, pre, after, off, pend, dup_ok = run(parts, sell=False)
    chk(after["TKJ"] == pre["TKJ"] + 10 and off == 0 and pend == 0 and dup_ok and n_keep(c) == 1,
        f"K4 {name}: 그 통화 늦은 변화 없음 = 짝 없음(지급 그대로 · 상쇄 줄 0 · 다음 대사까지 보류 후보 1)",
        {"d": str(after["TKJ"] - pre["TKJ"]), "off": off, "keep": n_keep(c)})
BUY = late(S.norm_fill("binance", "binance:TKJUSDT:3", (T0 + 150) * 1000, "TKJ", "USDT", "buy", "1", "10", "0", ""))
SELL0 = late(S.norm_fill("binance", "binance:TKJUSDT:4", (T0 + 160) * 1000, "TKJ", "USDT", "sell", "1", "10", "0", ""))
for name, parts in {"순액 0 1 레코드": [[BUY, SELL0, INC]], "순액 0 나눔": [[BUY], [INC], [SELL0]]}.items():
    c, pre, after, off, pend, dup_ok = run(parts, sell=False)
    chk(after["TKJ"] == pre["TKJ"] + 10 and off == 0 and pend == 0 and dup_ok and n_keep(c) == 1,
        f"K4 {name}: 같은 구간 늦은 매수 +10·매도 −10 = 짝 없음(지급 그대로 · 상쇄 줄 0 · 보류 후보 1)",
        {"d": str(after["TKJ"] - pre["TKJ"]), "off": off, "keep": n_keep(c)})
T.finish()
