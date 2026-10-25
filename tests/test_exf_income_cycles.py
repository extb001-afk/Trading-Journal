#!/usr/bin/env python3
import sys
import time

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
    return c.conn.execute("SELECT count(*) FROM postings WHERE source_id LIKE 'exflate:%' AND CAST(qty_base AS INTEGER) != 0").fetchone()[0]


def n_rows(c, keep=None):
    q = "SELECT count(*) FROM exf_late_pending" + ("" if keep is None else " WHERE substr(lb, 1, 5) " + ("= '@inc:' AND sym IS NOT NULL" if keep else "!= '@inc:'"))
    return c.conn.execute(q).fetchone()[0]


def new_core():
    c = core.Core(config.load_config())
    S._fake_px(c.px)
    S._C[0] = c
    c.svc_exf.EXF_INIT_PHASE = 5
    return c


def setup():
    S.reset(px={"USDT": 1., "TKJ": 1., "DUM": 1.}).conn.close()
    c = new_core()
    S.ex("binance", deposits=[S.norm_row("binance", "seed", "USDT", "100", 0, "seed", "ACCEPTED", T0 - 20, T0 - 20)])
    S.fills("binance", [S.norm_fill("binance", "seedbuy", (T0 - 10) * 1000, "TKJ", "USDT", "buy", "1", "100", "0", "")])
    recon(c, T0, {"TKJ": 100, "USDT": 0})
    recon(c, T0 + 300, {"TKJ": 100, "USDT": 10})
    return c


def consume(c, rows, cycle, idx=0, count=1):
    c.svc_exf._consume_exf_fills({"v": 1, "kind": "exf_fills", "exchange": "binance", "ts": S.NOW, "fills": rows,
                                  "lb": "binance:" + cycle, "lbi": idx, "lbn": count, "lc": cycle})
    c.conn.commit()


def flush(c, cycle=None, force=False):
    if cycle is not None:
        c.svc_exf._late_cycle_done({"exchange": "binance", "lc": cycle})
    if force:
        c.conn.execute("UPDATE exf_late_pending SET at=? WHERE substr(lb, 1, 5) != '@inc:'", (int(time.time()) - c.svc_exf.LATE_BATCH_WAIT - 10,))
    c.conn.commit()
    c.svc_exf._exf_late_flush()
    c.conn.commit()


def finish(c, name, mid_recon=None):
    S.PX["TKJ"] = 2.
    S.fills("binance", [S.norm_fill("binance", "binance:TKJUSDT:9", (T0 + 350) * 1000, "TKJ", "USDT", "sell", "2", "10", "0", "")])
    S.build()
    c = new_core()
    recon(c, T0 + 400, {"TKJ": 90, "USDT": 30, "DUM": 0})
    post = totals(c)
    f, G, _ = S.build()
    got = {"post": {k: str(v) for k, v in post.items()}, "real": round(S.realized(f), 6), "tax": round(S.tax_sum(f), 6), "unk": S.unknown(G)}
    chk(post == {"TKJ": D(90), "USDT": D(30), "DUM": D(0)}, f"{name}: 다음 대사 뒤 원장 = 실잔고", got)
    chk(abs(got["real"] - 20) < 1e-6 and abs(got["tax"] - 20) < 1e-6 and not got["unk"],
        f"{name}: 지급 10 + 매매이익 10 = 실현·세금용 20 · 원가 미상 0(중간 매도 원가가 가짜 수량에 안 섞임)", got)


INC = {"id": "binance:div:1", "ts": (T0 + 100) * 1000, "src": "income", "late": 1, "asset": "TKJ", "base": "TKJ", "amount": "10", "info": "Launchpool"}
SELL = dict(S.norm_fill("binance", "binance:TKJUSDT:1", (T0 + 200) * 1000, "TKJ", "USDT", "sell", "1", "10", "0", ""), late=1)
PRE = {"TKJ": D(100), "USDT": D(10), "DUM": D(0)}

for name, order, mode in [("C1 지급→매도 다른 주기", [INC, SELL], "cross"), ("C1 매도→지급 다른 주기", [SELL, INC], "cross"),
                          ("C1 지급→(재시작)→매도", [INC, SELL], "restart"), ("C1 매도→(재시작)→지급", [SELL, INC], "restart"),
                          ("C1 강제 흡수 지급 먼저", [INC, SELL], "forced"), ("C1 강제 흡수 매도 먼저", [SELL, INC], "forced")]:
    c = setup()
    chk(totals(c) == PRE, f"{name} 준비: 대사된 시작 잔고", {k: str(v) for k, v in totals(c).items()})
    if mode == "forced":
        consume(c, [order[0]], "A", 0, 2)
        flush(c, force=True)
        consume(c, [order[1]], "A", 1, 2)
        flush(c, "A", force=True)
    else:
        consume(c, [order[0]], "A")
        flush(c, "A")
        if mode == "restart":
            c.conn.close()
            c = new_core()
        consume(c, [order[1]], "B")
        flush(c, "B")
    after = totals(c)
    chk(after == PRE and n_off(c) == 0 and n_rows(c) == 0, f"{name}: 흡수 끝 원장 = 시작 · 상쇄 줄 0 · 대기표(보류 후보 포함) 비움",
        {"after": {k: str(v) for k, v in after.items()}, "off": n_off(c), "rows": n_rows(c)})
    consume(c, [INC, SELL], "C")
    flush(c, "C")
    chk(totals(c) == after and n_off(c) == 0 and n_rows(c) == 0, f"{name}: C2 두 원본 재전송 = 무동작")
    finish(c, name)

c = setup()
consume(c, [INC], "A")
flush(c, "A")
chk(n_rows(c, keep=True) == 1 and n_rows(c, keep=False) == 0, "C3 지급만 온 주기 끝 = 보류 후보 1(묶음 대기 0)", n_rows(c))
chk(not c.svc_exf._exf_late_pending("binance"), "C4 보류 후보만 있으면 대사를 막지 않음")
recon(c, T0 + 330, {"TKJ": 100, "USDT": 10})
chk(totals(c)["TKJ"] == D(100), "C3 그 사이 대사 = 차이 −10 보정(원장 = 실잔고)", str(totals(c)["TKJ"]))
consume(c, [SELL], "B")
flush(c, "B")
chk(totals(c) == PRE and n_off(c) == 0 and n_rows(c) == 0, "C3 대사 뒤 늦은 매도 = 그 대사 보정 되돌림(후보 만료 · 짝 두 번 안 함 · 상쇄 줄 0)",
    {"after": {k: str(v) for k, v in totals(c).items()}, "off": n_off(c), "rows": n_rows(c)})
finish(c, "C3")

c = setup()
consume(c, [INC], "A")
flush(c, "A")
c.conn.execute("UPDATE exf_late_pending SET lb='@inc:1' WHERE substr(lb, 1, 5) = '@inc:'")
c.conn.commit()
c.conn.close()
c = new_core()
consume(c, [SELL], "B")
flush(c, "B")
chk(n_rows(c) == 0 and n_off(c) == 1 and totals(c)["TKJ"] == D(110), "C4 만료된 보류 후보 = 버림(짝 없음 · 종전 상쇄 줄)",
    {"tkj": str(totals(c)["TKJ"]), "off": n_off(c), "rows": n_rows(c)})
S.reset(px={"USDT": 1., "TKJ": 1., "DUM": 1.}).conn.close()
c = new_core()
S.ex("binance", deposits=[S.norm_row("binance", "seed", "USDT", "100", 0, "seed", "ACCEPTED", T0 - 20, T0 - 20)])
S.fills("binance", [S.norm_fill("binance", "seedbuy", (T0 - 10) * 1000, "TKJ", "USDT", "buy", "1", "100", "0", "")])
recon(c, T0, {"TKJ": 100, "USDT": 0})
recon(c, T0 + 300, {"TKJ": 105, "USDT": 5})
consume(c, [dict(S.norm_fill("binance", "binance:TKJUSDT:5", (T0 + 250) * 1000, "TKJ", "USDT", "buy", "1", "5", "0", ""), late=1)], "A")
flush(c, "A")
consume(c, [SELL], "B")
flush(c, "B")
recon(c, T0 + 500, {"TKJ": 48, "USDT": 62})
consume(c, [INC, dict(S.norm_fill("binance", "binance:TKJUSDT:6", (T0 + 400) * 1000, "TKJ", "USDT", "sell", "1", "57", "0", ""), late=1)], "C")
flush(c, "C")
tkj_off = c.conn.execute("SELECT count(*) FROM postings WHERE source_id LIKE 'exflate:TKJ:%' AND CAST(qty_base AS INTEGER) != 0").fetchone()[0]
chk(totals(c)["TKJ"] == D(48) and tkj_off == 0 and n_rows(c) == 0, "C5 흡수 뒤 여유로 상쇄 되돌림 = 원장 TKJ 48(실잔고) · TKJ 상쇄 줄 0 · 보류 후보 0",
    {"tkj": str(totals(c)["TKJ"]), "tkj_off": tkj_off, "rows": n_rows(c)})


def drain(c, rows, cycle):
    consume(c, rows, cycle)
    flush(c, cycle)


def c6(gap, order, scale=1, restart=False):
    q = D(10) * D(scale)
    tr = S.NOW - 700
    ts = tr - 300
    ti = ts - gap
    first = ti - 100
    S.reset(cfg_extra={"exf": {"poll_sec": 21600}}, px={"USDT": 1., "TKJ": 1.}).conn.close()
    c = new_core()
    S.PXF[0] = lambda sym, at: (1. if int(at) <= ts else 2.) if sym == "TKJ" else None
    S.ex("binance", deposits=[S.norm_row("binance", "seed", "USDT", str(q * 10), 0, "seed", "ACCEPTED", first - 20, first - 20)])
    S.fills("binance", [S.norm_fill("binance", "seedbuy", (first - 10) * 1000, "TKJ", "USDT", "buy", "1", str(q * 10), "0", "")])
    recon(c, first, {"TKJ": float(q * 10), "USDT": 0})
    recon(c, tr, {"TKJ": float(q * 10), "USDT": float(q)})
    chk(int(float(c.svc_exf._meta_get("recon_done_exf_binance") or 0)) == tr, f"C6 gap={gap} 준비: 두 대사 모두 돎(신선도 안)")
    inc = {"id": "div-1", "ts": ti * 1000, "src": "income", "late": 1, "asset": "TKJ", "base": "TKJ", "amount": str(q), "info": "Staking reward"}
    sale = dict(S.norm_fill("binance", "sale-1", ts * 1000, "TKJ", "USDT", "sell", "1", str(q), "0", ""), late=1)
    groups = {"joint": [[inc, sale]], "income_first": [[inc], [sale]], "sale_first": [[sale], [inc]]}[order]
    for i, rows in enumerate(groups):
        drain(c, rows, str(i))
        if restart and i == 0:
            c.conn.close()
            c = new_core()
    name = f"C6 gap={gap} {order} ×{scale}{' 재시작' if restart else ''}"
    mid = totals(c)
    chk(mid["TKJ"] == q * 10 and mid["USDT"] == q and n_off(c) == 0 and n_rows(c) == 0, f"{name}: 흡수 끝 원장 = 대사된 잔고 · 상쇄 줄 0 · 대기표 비움",
        {"mid": {k: str(v) for k, v in mid.items()}, "off": n_off(c), "rows": n_rows(c)})
    S.PX["TKJ"] = 2.
    S.fills("binance", [S.norm_fill("binance", "new-sale", (tr + 100) * 1000, "TKJ", "USDT", "sell", "2", str(q), "0", "")])
    S.build()
    c = new_core()
    recon(c, tr + 400, {"TKJ": float(q * 9), "USDT": float(q * 3)})
    post = totals(c)
    f, G, _ = S.build()
    got = {"post": {k: str(v) for k, v in post.items()}, "real": S.realized(f), "tax": S.tax_sum(f), "unk": S.unknown(G)}
    chk(post["TKJ"] == q * 9 and abs(got["real"] - float(q * 2)) < .011 and abs(got["tax"] - float(q * 2)) < 1e-5 and not got["unk"],
        f"{name}: 지급 + 매매이익 = 실현·세금용 2q · 원가 미상 0", got)


for gap in (21599, 21600, 21601, 50000):
    for order in ("joint", "income_first", "sale_first"):
        c6(gap, order)
c6(50000, "sale_first", 1000, True)
c6(50000, "income_first", 1000, True)


def c7(order, mid_recon):
    t = S.NOW - 1000
    first = t - 400
    S.reset(px={"TKJ": 1., "DUM": 1., "USDT": 1.}).conn.close()
    c = new_core()
    S.PXF[0] = lambda sym, at: (1. if int(at) < t + 200 else 2.) if sym == "TKJ" else None
    S.ex("binance", deposits=[S.norm_row("binance", "seed", "USDT", "200", 0, "seed", "ACCEPTED", first - 30, first - 30)])
    S.fills("binance", [S.norm_fill("binance", "buytkj", (first - 20) * 1000, "TKJ", "USDT", "buy", "1", "100", "0", ""),
                        S.norm_fill("binance", "buydum", (first - 10) * 1000, "DUM", "USDT", "buy", "1", "100", "0", "")])
    recon(c, first, {"TKJ": 100, "DUM": 100, "USDT": 0})
    target = {"TKJ": D(94), "DUM": D(90), "USDT": D(10)}
    recon(c, t + 300, {k: float(v) for k, v in target.items()})
    chk(c.svc_exf._meta_get("recon_src_exf_binance") is not None and int(float(c.svc_exf._meta_get("recon_done_exf_binance") or 0)) == t + 300,
        f"C7 {order} 준비: 두 대사 모두 돎")
    reward = {"id": "reward", "ts": (t + 100) * 1000, "src": "income", "asset": "TKJ", "base": "TKJ", "amount": "4", "info": "reward"}
    trade = dict(S.norm_fill("binance", "dum-sell-fee", (t + 200) * 1000, "DUM", "USDT", "sell", "1", "10", "10", "TKJ"), late=1)
    rows = [reward, trade] if order == "income_first" else [trade, reward]
    drain(c, [rows[0]], "a")
    if mid_recon:
        recon(c, t + 330, {k: float(v) for k, v in target.items()})
    c.conn.close()
    c = new_core()
    drain(c, [rows[1]], "b")
    name = f"C7 {order}{' 그 사이 대사' if mid_recon else ''}"
    after = totals(c)
    exflate = c.conn.execute("SELECT count(*) FROM postings WHERE source_id LIKE 'exflate:TKJ:%' AND CAST(qty_base AS INTEGER) != 0").fetchone()[0]
    chk(after == target and exflate == 0, f"{name}: 원장 = 실잔고 · TKJ 상쇄 줄 0", {"after": {k: str(v) for k, v in after.items()}, "exflate": exflate})
    try:
        why_ok = [r.get("why") for r in c.svc_exf._exf_revert_rows()]
    except ValueError as e:
        why_ok = ["오류 " + str(e)]
    chk(not any(str(w).startswith("오류") for w in why_ok) and (not (mid_recon and order == "income_first") or any("지급 맞춘" in str(w) for w in why_ok)),
        f"{name}: 되돌림 감사 기록 읽힘(사유 검증식 통과)", why_ok[-3:])
    drain(c, [reward, trade], "dup")
    chk(totals(c) == after, f"{name}: 재전송 무동작")
    S.PX["TKJ"] = 2.
    S.fills("binance", [S.norm_fill("binance", "sell-all-tkj", (t + 400) * 1000, "TKJ", "USDT", "sell", "2", "94", "0", ""),
                        S.norm_fill("binance", "sell-all-dum", (t + 410) * 1000, "DUM", "USDT", "sell", "1", "90", "0", "")])
    cash = totals(c)["USDT"]
    recon(c, t + 500, {"TKJ": 0, "DUM": 0, "USDT": float(cash)})
    f, G, _ = S.build()
    got = {"cash": str(cash), "real": S.realized(f), "tax": S.tax_sum(f), "unk": S.unknown(G)}
    chk(cash == D(288) and abs(got["real"] - 88) < .011 and abs(got["tax"] - 88) < 1e-6, f"{name}: 전량 청산 실현·세금용 = 현금 288 − 200 = 88", got)


for order in ("income_first", "fee_first"):
    for mid in (False, True):
        c7(order, mid)

t = S.NOW - 1000
S.reset(px={"TKJ": 1., "DUM": 1., "USDT": 1.}).conn.close()
c = new_core()
S.ex("binance", deposits=[S.norm_row("binance", "seed", "USDT", "200", 0, "seed", "ACCEPTED", t - 430, t - 430)])
S.fills("binance", [S.norm_fill("binance", "buytkj", (t - 420) * 1000, "TKJ", "USDT", "buy", "1", "100", "0", ""),
                    S.norm_fill("binance", "buydum", (t - 410) * 1000, "DUM", "USDT", "buy", "1", "100", "0", "")])
recon(c, t - 400, {"TKJ": 100, "DUM": 100, "USDT": 0})
recon(c, t + 300, {"TKJ": 94, "DUM": 90, "USDT": 10})
drain(c, [{"id": "reward", "ts": (t + 100) * 1000, "src": "income", "asset": "TKJ", "base": "TKJ", "amount": "4", "info": "reward"}], "a")
R2 = {"TKJ": D(89), "DUM": D(80), "USDT": D(20)}
recon(c, t + 330, {k: float(v) for k, v in R2.items()})
drain(c, [dict(S.norm_fill("binance", "fee-a", (t + 200) * 1000, "DUM", "USDT", "sell", "1", "10", "10", "TKJ"), late=1),
          dict(S.norm_fill("binance", "fee-b", (t + 320) * 1000, "DUM", "USDT", "sell", "1", "10", "5", "TKJ"), late=1)], "b")
pos = sum((D(r[0]) for r in c.conn.execute("SELECT p.qty_norm FROM positions p WHERE p.location='exchange:binance' AND p.group_id IN"
                                            " (SELECT group_id FROM assets WHERE symbol='TKJ')")), D(0))
got = {k: str(v) for k, v in totals(c).items()}
chk(totals(c)["TKJ"] == D(89) and pos == D(89) and n_off(c) == 0, "C8 같은 흡수 두 구간: 원장 합 = positions = 실잔고 89 · 상쇄 줄 0", {"ledger": got, "pos": str(pos), "off": n_off(c)})
T.finish()
