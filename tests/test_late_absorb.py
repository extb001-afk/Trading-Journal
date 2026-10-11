#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _ingest
from _ingest import check, W, SOLW, Reader

import glob
import importlib.util
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

W2 = "0x" + "a2" * 20
json.dump({"chains": {"eth": {"blockscout": "https://bs.invalid", "etherscan_chainid": 1, "conf_depth": 12, "blocks_per_day": 7200,
                              "rpcs": ["https://rpc.invalid"]}},
           "wallets": [{"type": "evm", "chain": "eth", "address": W}, {"type": "evm", "chain": "eth", "address": W2},
                       {"type": "sol", "address": SOLW}],
           "native_symbol": {"eth": "ETH"}, "backfill_months": 5, "sol": {"rpcs": ["https://solrpc.invalid"]}},
          open(os.path.join(T.TMP, "config.json"), "w"))
import common
import core
import discopen

core.dm = lambda *a, **k: None
spec = importlib.util.spec_from_file_location("rb2", os.path.join(T.ROOT, "tools", "rebuild2.py"))
rb2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rb2)
KST = timezone(timedelta(hours=9))
DAY = 86400
E18 = 10 ** 18
NOW = int(time.time())
X = "0x" + "b7" * 20
RT = "0x" + "e5" * 20
TKN = "0x" + "d4" * 20
SD = common.STATE_DIR


def iso(ts):
    return datetime.fromtimestamp(int(ts), KST).strftime("%Y-%m-%d")


def h(n):
    return "0x" + ("%064x" % n)


def reset():
    for p9 in glob.glob(os.path.join(SD, "*")):
        if os.path.isfile(p9):
            os.remove(p9)


def new_core():
    c = core.Core(common.load_config())
    c.conn.commit()
    return c


def esnap(hx, ts, blk, frm, to, value=0, internal=(), toks=(), fee=0):
    return {"tx": {"hash": hx, "from": frm, "to": to, "value": str(value), "fee": {"value": str(fee)}, "status": "ok", "raw_input": "0x12345678",
                   "timestamp": ts, "block_number": blk, "block_hash": "0x" + "d" * 64},
            "token_transfers": [{"from": f, "to": t, "token": {"address": TKN, "symbol": "TKN", "decimals": "18", "type": "ERC-20"},
                                 "total": {"value": str(v), "decimals": "18"}} for (f, t, v) in toks],
            "internal": [{"from": f, "to": t, "value": str(v), "success": True} for (f, t, v) in internal]}


def feed(c, hx, snap, wallets=(W,)):
    c._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": hx, "wallets": list(wallets), "snapshot": snap, "ts": 1}]), 0, 0)


def recon(c, per):
    c._scope_ready = lambda s: True
    c._recon_quiet = lambda *a: True
    c._recon_bal = lambda chain, kind, mode, wallets: ({"per_wallet": per[chain]} if chain in per else None)
    c._last_recon = 0
    c.recon_pass(set())
    for k9 in ("_scope_ready", "_recon_quiet", "_recon_bal"):
        c.__dict__.pop(k9, None)
    for ch9 in per:
        t9 = c._meta_get(f"recon_done_{ch9}")
        if t9:
            c.conn.execute("UPDATE meta SET v=? WHERE k=?", (str(int(float(t9)) - 60), f"recon_done_{ch9}"))
            c.conn.execute("UPDATE raw_observations SET observed_at=observed_at-60 WHERE obs_id=?", (f"recon:{ch9}",))
            c.conn.execute("UPDATE postings SET event_ts=event_ts-60 WHERE source_kind='opening' AND source_id=? AND event_ts=?",
                           (f"recon:{ch9}", int(float(t9))))
    c.conn.commit()
    c.__dict__.pop("_recon_cache", None)


def aid_native(c):
    return c.conn.execute("SELECT asset_id FROM assets WHERE chain='eth' AND kind='native'").fetchone()[0]


def aid_tok(c):
    return c.conn.execute("SELECT asset_id FROM assets WHERE chain='eth' AND kind='token'").fetchone()[0]


def cell(conn, aid, w=W):
    return sum(int(r[0]) for r in conn.execute("SELECT qty_base FROM postings WHERE asset_id=? AND location=?", (aid, f"wallet:eth:{w}")))


def anchors(conn, w=W):
    return sorted((str(r[0]), int(r[1]), int(r[2]), int(r[3])) for r in conn.execute(
        "SELECT source_id, asset_id, qty_base, event_ts FROM postings WHERE source_kind='opening' AND location=?", (f"wallet:eth:{w}",)))


def pre_marks(c):
    return {r[0]: r[1] for r in c.conn.execute("SELECT k, v FROM meta WHERE k LIKE 'ext_prewindow%'")}


def min_mark(c):
    m9 = common.hist_late_read(c.conn)
    return min(m[1] for m in m9) if m9 else None


def shadow(c, tag):
    c.conn.commit()
    bp, sp = os.path.join(T.TMP, f"la_base_{tag}.db"), os.path.join(T.TMP, f"la_shadow_{tag}.db")
    for p9 in (bp, sp):
        if os.path.exists(p9):
            os.remove(p9)
        d9 = sqlite3.connect(p9)
        c.conn.backup(d9)
        d9.close()
    anc = [tuple(r) for r in sqlite3.connect(bp).execute(rb2.ANCHOR_SQL).fetchall()]
    old9 = common.DB_PATH
    common.DB_PATH = sp
    try:
        sc = core.Core(common.load_config())
    finally:
        common.DB_PATH = old9
    for t9 in rb2.DERIVED_TABLES:
        sc.conn.execute(f"DELETE FROM {t9}")
    sc.conn.commit()
    for r in sc.conn.execute("SELECT chain, txhash, snapshot FROM raw_txs ORDER BY ingested_at, chain, txhash").fetchall():
        sc.conn.execute("BEGIN")
        s9 = json.loads(r["snapshot"])
        if r["chain"] == "sol" and s9.get("kind") == "sol_tx":
            sc.apply_sol(s9)
        else:
            sc.apply(r["chain"], r["txhash"], "", s9)
        sc.conn.commit()
    obs = {r[0]: r[1] for r in sc.conn.execute("SELECT obs_id, observed_at FROM raw_observations")}
    meta = {r[0]: int(r[1]) for r in sc.conn.execute("SELECT k, v FROM meta WHERE k LIKE 'recon_done_%'")}
    rb2.recompute_anchors(bp, sc.conn, sc, anc, obs, meta)
    sc.conn.commit()
    return sc


TA = NOW - 60 * DAY
TB = NOW - 40 * DAY
LATE = esnap(h(9), TB, 2000, X, RT, internal=[(RT, W, 2 * E18 // 10)])


def scenario(absorb=True):
    reset()
    c = new_core()
    if not absorb:
        c._late_absorb = lambda *a, **k: False
    feed(c, h(1), esnap(h(1), TA, 1000, W, RT, internal=[(RT, W, E18)]))
    recon(c, {"eth": {W: {("native", None): 12 * E18 // 10}, W2: {("native", None): 0}}})
    c._hist_late_scan()
    return c


c = scenario()
A = aid_native(c)
W0 = c._win_t0(None, "eth")
a0 = anchors(c.conn)
check("A1 (전제) 첫 대사 = 기초 잔고 0.2 ETH(놓친 internal 을 흡수) · 원장 합 1.2", a0 == [("recon:eth", A, 2 * E18 // 10, W0)] and cell(c.conn, A) == 12 * E18 // 10,
      (a0, cell(c.conn, A)))
feed(c, h(9), LATE)
a1 = anchors(c.conn)
check("A1 ★늦게 온 창 안 옛 internal 입금 = 원장 합 1.2 = 실잔고(겹침 0)★(종전 = 1.4 · 재구축 전까지 이중 계상)", cell(c.conn, A) == 12 * E18 // 10,
      (cell(c.conn, A), a1))
check("A1 ★재구축 대기 표식 없음 · 기초 잔고 0.2 → 0(그만큼 흡수)★", pre_marks(c) == {} and a1 == [], (pre_marks(c), a1))
check("A2 지난 곡선 다시 계산 표식 = 앵커 날(창 시작 — 스캔 전 · 같은 트랜잭션)", min_mark(c) == iso(W0), (common.hist_late_read(c.conn), iso(W0)))
c._hist_late_scan()
mk2 = common.hist_late_read(c.conn)
n2 = c.conn.execute("SELECT COUNT(*), MAX(posting_id) FROM postings").fetchone()
feed(c, h(9), LATE)
check("A2 같은 레코드 재수신 = 원장·표식 무변(멱등)", tuple(c.conn.execute("SELECT COUNT(*), MAX(posting_id) FROM postings").fetchone()) == tuple(n2)
      and common.hist_late_read(c.conn) == mk2 and cell(c.conn, A) == 12 * E18 // 10, (mk2, common.hist_late_read(c.conn)))

sc_new = shadow(c, "new")
check("A3 ★흡수 뒤 rebuild2 = 칸 합·기초 잔고 그대로 이월(멱등)★", cell(sc_new.conn, A) == cell(c.conn, A) and anchors(sc_new.conn) == anchors(c.conn),
      (cell(sc_new.conn, A), anchors(sc_new.conn), anchors(c.conn)))
live_new = (cell(c.conn, A), anchors(c.conn))
sc_new.conn.close()
c.conn.close()
c = scenario(absorb=False)
feed(c, h(9), LATE)
check("A3 (대조) 종전 경로 = 원장 1.4(이중) + 재구축 대기 표식", cell(c.conn, A) == 14 * E18 // 10 and f"ext_prewindow_tx:eth:{h(9)}" in pre_marks(c),
      (cell(c.conn, A), pre_marks(c)))
sc_old = shadow(c, "old")
check("A3 ★종전 경로의 재구축(rebuild2) 결과 = 즉시 흡수 결과(칸 합 1.2 · 기초 잔고)★", (cell(sc_old.conn, A), anchors(sc_old.conn)) == live_new,
      ((cell(sc_old.conn, A), anchors(sc_old.conn)), live_new))
sc_old.conn.close()
c.conn.close()

c = scenario()
A = aid_native(c)
feed(c, h(11), esnap(h(11), TB, 2000, W, X, value=E18 // 10))
check("A4 늦게 온 옛 보냄 = 기초 잔고 0.2 → 0.3 · 원장 합 1.2 = 실잔고 · 표식 없음",
      cell(c.conn, A) == 12 * E18 // 10 and [a[2] for a in anchors(c.conn)] == [3 * E18 // 10] and pre_marks(c) == {}, (cell(c.conn, A), anchors(c.conn), pre_marks(c)))
c.conn.close()
reset()
c = new_core()
recon(c, {"eth": {W: {("native", None): 0, ("token", TKN): 0}, W2: {("native", None): 0}}})
c._hist_late_scan()
feed(c, h(12), esnap(h(12), TB, 2000, W, TKN, toks=[(W, X, 5 * E18)]))
AT = aid_tok(c)
an4 = [a for a in anchors(c.conn) if a[1] == AT]
check("A4 ★앵커 없던 칸의 옛 보냄 = 창 시작 새 기초 잔고 +5(음수 보유 없음 · rebuild2 새 앵커와 같은 자리)★",
      cell(c.conn, AT) == 0 and an4 == [("recon:eth", AT, 5 * E18, c._win_t0(int(float(c._meta_get("recon_done_eth"))), "eth"))] and pre_marks(c) == {},
      (cell(c.conn, AT), an4, pre_marks(c)))
sc4 = shadow(c, "a4")
check("A4 rebuild2 = 같은 결과(이월)", cell(sc4.conn, AT) == 0 and [a for a in anchors(sc4.conn) if a[1] == AT] == an4, anchors(sc4.conn))
sc4.conn.close()
c.conn.close()

reset()
c = new_core()
recon(c, {"eth": {W: {("native", None): 0}}})
c._recon_bal = lambda chain, kind, md, wallets: {"per_wallet": {W2: {("native", None): 3 * E18}}}
c._wallet_backfilled = lambda *a: True
c._recon_quiet = lambda *a: True
c._wrecon_run("eth", "evm", "evm", set(), c._win_t0(None, "eth"), True, "new", [W2])
for k9 in ("_recon_bal", "_wallet_backfilled", "_recon_quiet"):
    c.__dict__.pop(k9, None)
t5 = int(float(c._meta_get(f"wrecon_done:eth:{W2}")))
c.conn.execute("UPDATE meta SET v=? WHERE k=?", (str(t5 - 60), f"wrecon_done:eth:{W2}"))
c.conn.execute("UPDATE raw_observations SET observed_at=? WHERE obs_id=?", (t5 - 60, f"recon:eth:{W2}"))
c.conn.commit()
c._hist_late_scan()
A = aid_native(c)
a5 = anchors(c.conn, W2)
check("A5 (전제) 지갑별 대사 앵커 W2 3 ETH", [a[0] for a in a5] == [f"recon:eth:{W2}"] and a5[0][2] == 3 * E18, a5)
feed(c, h(13), esnap(h(13), TB, 2000, X, RT, internal=[(RT, W2, E18)]), wallets=(W2,))
check("A5 ★지갑별 대사 앵커도 늦게 온 옛 입금 1 ETH 흡수 — 원장 합 3 = 실잔고 · 표식 없음★",
      cell(c.conn, A, W2) == 3 * E18 and [a[2] for a in anchors(c.conn, W2)] == [2 * E18] and pre_marks(c) == {}, (cell(c.conn, A, W2), anchors(c.conn, W2), pre_marks(c)))
c.conn.close()

c = scenario()
A = aid_native(c)
c.conn.execute("UPDATE postings SET event_ts=? WHERE source_kind='opening' AND source_id='recon:eth' AND asset_id=?", (TB + DAY, A))
c.conn.commit()
feed(c, h(9), LATE)
check("A6 앵커가 그 거래보다 뒤(넓힌 창의 옛 조각) = 종전 재구축 표식(rebuild2 가 앵커를 넓힌 창 시작으로) · 기초 잔고 무변",
      f"ext_prewindow_tx:eth:{h(9)}" in pre_marks(c) and anchors(c.conn)[0][2] == 2 * E18 // 10, (pre_marks(c), anchors(c.conn)))
c.conn.close()

reset()
c = new_core()
recon(c, {"sol": {SOLW: {("native", None): 10 * 10 ** 9}}})
c._hist_late_scan()
srec = {"v": 1, "kind": "sol_tx", "chain": "sol", "txhash": "S" + "7" * 87, "slot": 900, "ts": TB, "fee_lamports": 0, "fee_payer_mine": False,
        "fee_payer": None, "wallets": [SOLW], "deltas": [{"asset": "native", "symbol": "SOL", "decimals": 9, "delta": "2000000000", "owner": SOLW}],
        "counterparties": [], "has_program": False, "err": False}
c._drain_stream("sol", Reader([srec]), 0, 0)
check("A7 솔라나 = 종전 재구축 표식(스테이크 기초잔고 칸이 따로)", "ext_prewindow_tx:sol:" + srec["txhash"] in pre_marks(c), pre_marks(c))
c.conn.close()

c = scenario()
A = aid_native(c)
real_put = common.hist_late_put


def boom(conn, ts, now=None):
    real_put(conn, ts, now)
    raise RuntimeError("시험: 표식 쓴 직후 예외")


common.hist_late_put = boom
try:
    feed(c, h(9), LATE)
finally:
    common.hist_late_put = real_put
check("A8 표식 쓴 직후 예외 = 롤백 — 원장(거래·기초 잔고)·표식 둘 다 안 남음",
      cell(c.conn, A) == 12 * E18 // 10 and anchors(c.conn)[0][2] == 2 * E18 // 10 and common.hist_late_read(c.conn) == [] and pre_marks(c) == {}
      and c.conn.execute("SELECT 1 FROM raw_txs WHERE txhash=?", (h(9),)).fetchone() is None, (cell(c.conn, A), anchors(c.conn), common.hist_late_read(c.conn)))
feed(c, h(9), LATE)
check("A8 다시 받으면 정상(흡수 · 합 1.2)", cell(c.conn, A) == 12 * E18 // 10 and anchors(c.conn) == [] and pre_marks(c) == {}, (cell(c.conn, A), anchors(c.conn)))
c.conn.close()

c = scenario()
A = aid_native(c)
feed(c, h(9), esnap(h(9), TB, 2000, X, RT, internal=[(RT, W, 2 * E18 // 10)], toks=[(X, W, 7 * E18), (W, X, 7 * E18)]))
AT = aid_tok(c)
check("A9 순효과 0 토큰 칸이 섞여도 ETH 칸 흡수 — 합 1.2 · TKN 0 · 표식 없음",
      cell(c.conn, A) == 12 * E18 // 10 and cell(c.conn, AT) == 0 and pre_marks(c) == {} and anchors(c.conn) == [], (cell(c.conn, A), cell(c.conn, AT), pre_marks(c), anchors(c.conn)))
c.conn.close()

reset()
c = new_core()
feed(c, h(21), esnap(h(21), NOW - 60 * DAY, 900, X, W, value=10 * E18))
recon(c, {"eth": {W: {("native", None): 8 * E18}, W2: {("native", None): 0}}})
c._hist_late_scan()
A = aid_native(c)
feed(c, h(22), esnap(h(22), TB, 2000, X, RT, internal=[(RT, W, E18)]))
check("A10 (전제) 흡수 → 앵커 −2 → −3 · 합 8 · 표식 없음", [a[2] for a in anchors(c.conn)] == [-3 * E18] and cell(c.conn, A) == 8 * E18 and pre_marks(c) == {},
      (anchors(c.conn), cell(c.conn, A), pre_marks(c)))
check("A10 ★음수 앵커 흡수 = 창 시작 날부터 표식★(종전 = 거래 날)", min_mark(c) is not None and min_mark(c) <= iso(c._win_t0(None, "eth")),
      (common.hist_late_read(c.conn), iso(c._win_t0(None, "eth")), iso(TB)))
c.conn.close()

TK2 = "0x" + "d9" * 20
reset()
c = new_core()
recon(c, {"eth": {W: {("native", None): 0, ("token", TKN): 0, ("token", TK2): 1000 * E18}, W2: {("native", None): 0}}})
c._hist_late_scan()
A2 = c.conn.execute("SELECT asset_id FROM assets WHERE chain='eth' AND kind='token' AND address=?", (TK2,)).fetchone()[0]
T11 = int(float(c._meta_get("recon_done_eth")))
OLD0 = c._win_t0(T11, "eth") + 30 * DAY
c.conn.execute("UPDATE postings SET event_ts=? WHERE source_kind='opening' AND source_id='recon:eth' AND asset_id=?", (OLD0, A2))
c.conn.commit()
L11 = h(23)
feed(c, L11, esnap(L11, OLD0 - 10 * DAY, 1500, W, TKN, toks=[(W, X, 5 * E18)]))
check("A11 ★다른 양수 앵커가 아직 옛 창 시작이면 = 종전 재구축 표식 · 즉시 흡수 안 함★(rebuild2 가 그 체인 양수 대사 앵커를 넓힌 창 시작으로 함께 옮김)",
      f"ext_prewindow_tx:eth:{L11}" in pre_marks(c) and not [a for a in anchors(c.conn) if a[1] != A2],
      (pre_marks(c), anchors(c.conn)))
L12 = h(24)
feed(c, L12, esnap(L12, OLD0 + 10 * DAY, 1600, X, RT, internal=[(RT, W, E18)]))
check("A11 같은 체인 옛 창 안 늦은 거래도 = 종전 표식(재구축이 안 옮겨진 앵커를 같이 정리)", f"ext_prewindow_tx:eth:{L12}" in pre_marks(c), pre_marks(c))
sc11 = shadow(c, "a11")
a11 = [a for a in anchors(sc11.conn) if a[1] == A2]
check("A11 (대조) 그 표식의 rebuild2 = TK2 앵커를 넓힌 창 시작으로 옮김", a11 and a11[0][3] == c._win_t0(T11, "eth"), (a11, c._win_t0(T11, "eth")))
sc11.conn.close()
c.conn.close()
T.finish()
