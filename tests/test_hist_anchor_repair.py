#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _ingest
from _ingest import check, W, SOLW, Reader

import glob
import json
import os
import time
from datetime import datetime, timedelta, timezone

SOLW2 = "So2" + "2" * 41
json.dump({"chains": {"eth": {"blockscout": "https://bs.invalid", "etherscan_chainid": 1, "conf_depth": 12, "blocks_per_day": 7200,
                              "rpcs": ["https://rpc.invalid"]}},
           "wallets": [{"type": "evm", "chain": "eth", "address": W}, {"type": "sol", "address": SOLW}, {"type": "sol", "address": SOLW2}],
           "native_symbol": {"eth": "ETH"}, "backfill_months": 5, "sol": {"rpcs": ["https://solrpc.invalid"]}},
          open(os.path.join(T.TMP, "config.json"), "w"))
import common
import core

core.dm = lambda *a, **k: None
KST = timezone(timedelta(hours=9))
DAY = 86400
E18 = 10 ** 18
NOW = int(time.time())
RT = "0x" + "e5" * 20
X = "0x" + "b7" * 20
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
    for p9 in glob.glob(os.path.join(SD, "inbox", "*")):
        if os.path.isfile(p9):
            os.remove(p9)


def new_core():
    c = core.Core(common.load_config())
    c.conn.commit()
    return c


def esnap(hx, ts, blk, frm=W, to=RT, value=0, internal=(), toks=()):
    return {"tx": {"hash": hx, "from": frm, "to": to, "value": str(value), "fee": {"value": "0"}, "status": "ok", "raw_input": "0x12345678",
                   "timestamp": ts, "block_number": blk, "block_hash": "0x" + "d" * 64},
            "token_transfers": [{"from": f, "to": t, "token": {"address": TKN, "symbol": "TKN", "decimals": "18", "type": "ERC-20"},
                                 "total": {"value": str(v), "decimals": "18"}} for (f, t, v) in toks],
            "internal": [{"from": f, "to": t, "value": str(v), "success": True} for (f, t, v) in internal]}


def feed(c, hx, snap, repair=None, stream="evm"):
    rec = {"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": hx, "wallets": [W], "snapshot": snap, "ts": 1}
    if repair:
        rec["repair"] = repair
    c._drain_stream(stream, Reader([rec]), 0, 0)


def recon(c, per):
    c._scope_ready = lambda s: True
    c._recon_quiet = lambda *a: True
    c._recon_bal = lambda chain, kind, mode, wallets: ({"per_wallet": per[chain]} if chain in per else None)
    c._last_recon = 0
    c.recon_pass(set())
    for k9 in ("_scope_ready", "_recon_quiet", "_recon_bal"):
        c.__dict__.pop(k9, None)


def eth_aid(c):
    return c.conn.execute("SELECT asset_id FROM assets WHERE chain='eth' AND kind='native'").fetchone()[0]


def anchor_rows(c, chain="eth", loc=None):
    loc = loc or f"wallet:eth:{W}"
    return [(int(r[0]), int(r[1])) for r in c.conn.execute(
        "SELECT qty_base, event_ts FROM postings WHERE source_kind='opening' AND source_ns=? AND location=? ORDER BY leg_seq",
        (chain, loc))]


def cell(c, aid, loc=None):
    loc = loc or f"wallet:eth:{W}"
    return sum(int(r[0]) for r in c.conn.execute("SELECT qty_base FROM postings WHERE asset_id=? AND location=?", (aid, loc)))


def marks(c):
    return common.hist_late_read(c.conn)


def min_mark(c):
    m9 = marks(c)
    return min(m[1] for m in m9) if m9 else None


TL = NOW - 45 * DAY


def setup_int(c, internal_q, anchor_q, hx):
    feed(c, hx, esnap(hx, TL, 1000))
    recon(c, {"eth": {W: {("native", None): anchor_q}}})
    c._hist_late_scan()
    return esnap(hx, TL, 1000, internal=[(RT, W, internal_q)])


reset()
c = new_core()
s1 = setup_int(c, 5 * E18, 10 * E18, h(1))
A = eth_aid(c)
W0 = c._win_t0(None, "eth")
a0 = anchor_rows(c)
check("R1 (전제) 대사 앵커 = 창 시작 10 ETH", a0 == [(10 * E18, W0)] and marks(c) == [], (a0, W0, marks(c)))
feed(c, h(1), s1, repair="int_fill")
a1 = anchor_rows(c)
check("R1 (전제) int_fill 재기장 → 앵커 10 → 5 · 거래 날 +5 · 합 10(종전과 같음)", a1 == [(5 * E18, W0)] and cell(c, A) == 10 * E18, (a1, cell(c, A)))
m1 = marks(c)
check("R1 ★스캔 전(커밋 직후) 이미 원장 표식 — 날 = 앵커 날(창 시작)★(종전 = 표식 없음 · 스캔 뒤 거래 날만)",
      len(m1) == 1 and m1[0][1] == iso(W0), (m1, iso(W0), iso(TL)))
c._hist_late_scan()
check("R1 스캔 뒤에도 가장 이른 표식 날 = 앵커 날(새 행 날 TL 보다 앞)", min_mark(c) == iso(W0), (marks(c), iso(W0)))
c.conn.close()

reset()
c = new_core()
s2 = setup_int(c, 10 * E18, 10 * E18, h(2))
A = eth_aid(c)
feed(c, h(2), s2, repair="int_fill")
check("R2 (전제) 10 ETH 전부 늦은 internal = 앵커 행 삭제 · 합 10", anchor_rows(c) == [] and cell(c, A) == 10 * E18, (anchor_rows(c), cell(c, A)))
check("R2 ★앵커 삭제(10 → 0)도 앵커 날 표식★", min_mark(c) == iso(c._win_t0(None, "eth")), (marks(c), iso(c._win_t0(None, "eth"))))
c.conn.close()

reset()
c = new_core()
s3 = setup_int(c, 5 * E18, 2 * E18, h(3))
A = eth_aid(c)
W0 = c._win_t0(None, "eth")
T3 = int(float(c._meta_get("recon_done_eth")))
feed(c, h(3), s3, repair="int_fill")
a3 = anchor_rows(c)
check("R3 (전제) +2 → −3 · 앵커 시각이 대사 시각으로 이동", a3 == [(-3 * E18, T3)] and cell(c, A) == 2 * E18, (a3, T3, cell(c, A)))
check("R3 ★부호·시각 전환 = 옛 앵커 날(창 시작) 표식★", min_mark(c) == iso(W0), (marks(c), iso(W0)))

mk4 = marks(c)
n4 = c.conn.execute("SELECT COUNT(*), MAX(posting_id) FROM postings").fetchone()
feed(c, h(3), s3, repair="int_fill")
check("R4 같은 int_fill 다시 = 원장·표식 무변", marks(c) == mk4 and tuple(c.conn.execute("SELECT COUNT(*), MAX(posting_id) FROM postings").fetchone()) == tuple(n4)
      and anchor_rows(c) == a3, (marks(c), mk4))
c.conn.close()

reset()
c = new_core()
s5 = setup_int(c, 5 * E18, 10 * E18, h(5))
A = eth_aid(c)
real_put = common.hist_late_put
boom = {"n": 0}


def put_then_boom(conn, ts, now=None):
    iso9 = real_put(conn, ts, now)
    boom["n"] += 1
    raise RuntimeError("시험: 표식 쓴 직후 예외")


common.hist_late_put = put_then_boom
try:
    feed(c, h(5), s5, repair="int_fill")
finally:
    common.hist_late_put = real_put
check("R5 ★표식 쓴 직후 예외 = 롤백 — 앵커 10 그대로 · 표식 없음★(같은 트랜잭션)",
      boom["n"] >= 1 and anchor_rows(c) == [(10 * E18, c._win_t0(None, "eth"))] and marks(c) == [] and cell(c, A) == 10 * E18,
      (boom, anchor_rows(c), marks(c), cell(c, A)))
c.conn.execute("DELETE FROM raw_txs WHERE txhash=?", (h(5),))
c.conn.commit()
feed(c, h(5), esnap(h(5), TL, 1000))
feed(c, h(5), s5, repair="int_fill")
check("R5 다시 받으면 정상(앵커 5 · 앵커 날 표식)", anchor_rows(c)[:1] == [(5 * E18, c._win_t0(None, "eth"))] and min_mark(c) == iso(c._win_t0(None, "eth")),
      (anchor_rows(c), marks(c)))
c.conn.close()

reset()
c = new_core()
s6 = setup_int(c, 5 * E18, 10 * E18, h(6))
feed(c, h(6), s6, repair="int_fill")
c.conn.close()
c = new_core()
check("R6 ★커밋 직후 종료 → 재시작 뒤에도 앵커 날 표식 그대로★", min_mark(c) == iso(c._win_t0(None, "eth")), (marks(c),))
c._hist_late_scan()
check("R6 재시작 뒤 스캔 = 가장 이른 날 그대로(앵커 날)", min_mark(c) == iso(c._win_t0(None, "eth")), marks(c))
c.conn.close()

reset()
c = new_core()
H7 = h(7)
feed(c, H7, esnap(H7, TL, 1000, toks=[(W, X, 1 * E18)]))
recon(c, {"eth": {W: {("token", TKN): 2 * E18}}})
c._hist_late_scan()
AT = c.conn.execute("SELECT asset_id FROM assets WHERE chain='eth' AND kind='token'").fetchone()[0]
a7 = anchor_rows(c)
check("R7 (전제) 토큰 앵커 +3(창 시작)", a7 == [(3 * E18, c._win_t0(None, "eth"))], a7)
hd = os.path.join(SD, common.HIST_DIRTY)
feed(c, H7, esnap(H7, TL, 1000, toks=[(W, X, 1 * E18), (X, W, 3 * E18)]), repair="leg_union")
check("R7 (전제) leg_union 재기장 → 앵커 3 → 0 · 합 2", anchor_rows(c) == [] and cell(c, AT) == 2 * E18, (anchor_rows(c), cell(c, AT)))
check("R7 ★leg_union 도 원장 표식(앵커 날)★", min_mark(c) == iso(c._win_t0(None, "eth")), marks(c))
check("R7 core 가 장기 곡선 파일 표식을 트랜잭션 밖에서 직접 쓰지 않음(롤백돼도 남는 표식 금지 — 원장 표식이 web 을 거쳐 넘김)",
      not os.path.exists(hd), common.read_json(hd, None) if os.path.exists(hd) else None)
c.conn.close()

reset()
c = new_core()
s8 = setup_int(c, 5 * E18, 10 * E18, h(8))
c.conn.execute("INSERT INTO meta (k, v) VALUES (?, ?)", (f"ext_prewindow_tx:eth:{h(8)}", str(TL)))
c.conn.commit()
feed(c, h(8), s8, repair="int_fill")
check("R8 재구축 대기 표식 tx = 앵커 보정 없음 · 원장 표식 없음(rebuild2 가 교체 — 종전 정책)",
      anchor_rows(c) == [(10 * E18, c._win_t0(None, "eth"))] and marks(c) == [], (anchor_rows(c), marks(c)))
c.conn.close()

reset()
c = new_core()
TS9 = NOW - 50 * DAY
SH = "S" + "9" * 87
srec = {"v": 1, "kind": "sol_tx", "chain": "sol", "txhash": SH, "slot": 900, "ts": TS9, "fee_lamports": 0, "fee_payer_mine": False,
        "fee_payer": None, "wallets": [SOLW], "deltas": [{"asset": "native", "symbol": "SOL", "decimals": 9, "delta": "-5000000000", "owner": SOLW}],
        "counterparties": [SOLW2], "has_program": False, "err": False}
c._drain_stream("sol", Reader([srec]), 0, 0)
recon(c, {"sol": {SOLW: {("native", None): 0}, SOLW2: {("native", None): 10 * 10 ** 9}}})
c._hist_late_scan()
LS2 = f"wallet:sol:{SOLW2}"
a9 = anchor_rows(c, "sol", LS2)
W9 = c._win_t0(None, "sol")
check("R9 (전제) 솔라나 SOLW2 앵커 10 SOL(창 시작)", a9 == [(10 * 10 ** 9, W9)], (a9, W9))
srec2 = dict(srec, wallets=[SOLW, SOLW2], repersp=True,
             deltas=srec["deltas"] + [{"asset": "native", "symbol": "SOL", "decimals": 9, "delta": "5000000000", "owner": SOLW2}])
c._drain_stream("sol", Reader([srec2]), 0, 0)
a9b = anchor_rows(c, "sol", LS2)
check("R9 (전제) 새 관점 재기장 → SOLW2 앵커 10 → 5", a9b == [(5 * 10 ** 9, W9)], a9b)
check("R9 ★솔라나 앵커 보정도 앵커 날 표식(스캔 전)★", min_mark(c) == iso(W9), (marks(c), iso(W9)))
c.conn.close()

reset()
c = new_core()
TA10 = NOW - 60 * DAY
feed(c, h(101), esnap(h(101), TA10, 900, frm=X, to=W, value=10 * E18))
feed(c, h(102), esnap(h(102), TL, 1000))
recon(c, {"eth": {W: {("native", None): 8 * E18}}})
c._hist_late_scan()
A = eth_aid(c)
T10 = int(float(c._meta_get("recon_done_eth")))
check("R10 (전제) 음수 앵커 −2(대사 시각)", anchor_rows(c) == [(-2 * E18, T10)], (anchor_rows(c), T10))
feed(c, h(102), esnap(h(102), TL, 1000, internal=[(RT, W, E18)]), repair="int_fill")
check("R10 (전제) int_fill → 앵커 −2 → −3 · 합 8", anchor_rows(c) == [(-3 * E18, T10)] and cell(c, A) == 8 * E18, (anchor_rows(c), cell(c, A)))
check("R10 ★음수 앵커 보정 = 창 시작 날부터 표식★(웹 곡선은 음수 기초 잔고를 창 시작에 둠 — 종전 = 거래 날만이라 60일 전~거래 전날이 옛 값)",
      min_mark(c) is not None and min_mark(c) <= iso(c._win_t0(None, "eth")), (marks(c), iso(c._win_t0(None, "eth")), iso(TL)))
c.conn.close()
T.finish()
