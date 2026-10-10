#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _ingest
from _ingest import check, W, SOLW, Reader

import inspect
import json
import os
import time
from datetime import datetime, timedelta, timezone

import common
import core

core.dm = lambda *a, **k: None
KST = timezone(timedelta(hours=9))
DAY = 86400
E18 = 10 ** 18
NOW = int(time.time())
X = "0x" + "b7" * 20
if not (hasattr(common, "hist_late_put") and hasattr(core.Core, "_hist_late_scan")):
    check("늦은 원장 행 표식 장치(common.hist_late_put · core._hist_late_scan) 있음", False, "없음")
    T.finish()


def iso(ts):
    return datetime.fromtimestamp(int(ts), KST).strftime("%Y-%m-%d")


def h(n):
    return "0x" + ("%064x" % n)


def esnap(hx, ts, blk, value):
    return {"tx": {"hash": hx, "from": X, "to": W, "value": str(value), "fee": {"value": "0"}, "status": "ok", "raw_input": "0x",
                   "timestamp": ts, "block_number": blk, "block_hash": "0x" + "d" * 64}, "token_transfers": [], "internal": []}


def feed(c, hx, ts, value=E18, blk=1000):
    c._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": hx, "wallets": [W], "snapshot": esnap(hx, ts, blk, value),
                                    "ts": 1}]), 0, 0)


def marks(c):
    return common.hist_late_read(c.conn)


def npost(c):
    return c.conn.execute("SELECT COUNT(*) FROM postings").fetchone()[0]


import sqlite3
m0 = sqlite3.connect(":memory:")
m0.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
t0 = 1_800_000_000
common.hist_late_put(m0, t0 - 5 * DAY, now=t0)
common.hist_late_put(m0, t0 - 9 * DAY, now=t0 + 60)
a1 = common.hist_late_read(m0)
check("A 2분 안 늦은 행 = 한 표식 · 날 = 최솟값 · id 올림", len(a1) == 1 and a1[0][1] == iso(t0 - 9 * DAY) and a1[0][0] >= (t0 + 60) * 1000 and a1[0][2] == t0,
      a1)
common.hist_late_put(m0, t0 - 2 * DAY, now=t0 + 200)
a2 = common.hist_late_read(m0)
check("A 처음 뒤 2분 넘으면 새 표식(앞 표식 id 고정)", len(a2) == 2 and a2[0] == a1[0] and a2[1][1] == iso(t0 - 2 * DAY) and a2[1][0] > a2[0][0], a2)
for i in range(40):
    common.hist_late_put(m0, t0 - (20 + i) * DAY, now=t0 + 1000 + i * 300)
a3 = common.hist_late_read(m0)
ids3 = [m[0] for m in a3]
check("A 개수 상한 32 — 넘치면 가장 오래된 둘을 접음(가장 이른 날 보존 · id 오름차순)",
      len(a3) == common.HIST_LATE_KEEP and ids3 == sorted(ids3) and min(m[1] for m in a3) == iso(t0 - 59 * DAY) and a3[0][1] <= iso(t0 - 9 * DAY)
      and a3[-1][0] == max(m[0] for m in a3), (len(a3), a3[:2]))
common.hist_late_put(m0, t0 - DAY, now=t0 + common.HIST_LATE_TTL_S + 20000)
a4 = common.hist_late_read(m0)
check("A 마지막 시각이 14일 지난 표식은 정리(새 표식 + 그 안의 것만)", all(t0 + common.HIST_LATE_TTL_S + 20000 - m[3] < common.HIST_LATE_TTL_S for m in a4), a4[:3])
m1 = sqlite3.connect(":memory:")
m1.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
m1.execute("INSERT INTO meta VALUES (?, ?)", (common.HIST_LATE_K, json.dumps({"v": 1, "m": [[(t0 + 99999) * 1000, "2026-01-01", t0, t0]]})))
common.hist_late_put(m1, t0 - DAY, now=t0 + 500)
a5 = common.hist_late_read(m1)
check("A id 는 뒤로 안 감(시계가 돌아가도 직전 id + 1 이상)", a5[-1][0] > (t0 + 99999) * 1000, a5)
m1.execute("UPDATE meta SET v='{not json' WHERE k=?", (common.HIST_LATE_K,))
check("A 손상 표식 = 표식 없음(읽기 [])", common.hist_late_read(m1) == [], common.hist_late_read(m1))

c = core.Core(common.load_config())
c.conn.commit()
feed(c, h(1), NOW - 40 * DAY, 3 * E18, 900)
r0 = c._hist_late_scan()
cur0 = c._meta_get(common.HIST_LATE_PID_K)
check("B 첫 실행 = 커서만(이미 있던 40일 전 행 = 표식 없음)", r0 is None and marks(c) == [] and cur0 is not None and int(cur0) == c.conn.execute(
    "SELECT MAX(posting_id) FROM postings").fetchone()[0], (r0, marks(c), cur0))
TL = NOW - 5 * DAY
feed(c, h(2), TL, E18, 1000)
r1 = c._hist_late_scan()
mk1 = marks(c)
check("B 5일 전 늦은 입금 = 그 날 표식 1개", r1 == iso(TL) and len(mk1) == 1 and mk1[0][1] == iso(TL), (r1, mk1))
n1 = npost(c)
feed(c, h(2), TL, E18, 1000)
r2 = c._hist_late_scan()
check("B 같은 거래 재입력 = 원장 무변 → 표식 무변", r2 is None and npost(c) == n1 and marks(c) == mk1, (r2, npost(c), n1, marks(c)))
TN = common.kst_day0(NOW) + 12 * 3600
feed(c, h(3), TN, E18, 1100)
r3 = c._hist_late_scan(now=TN + 300)
check("B 오늘 시각 거래 = 표식 없음(아직 마감 전)", r3 is None and marks(c) == mk1 and npost(c) > n1, (r3, marks(c)))

BK = common.DB_PATH + ".bk_test"
_bk = sqlite3.connect(BK)
c.conn.backup(_bk)
_bk.close()
ID_B = mk1[-1][0]

feed(c, h(4), NOW - 12 * DAY, E18, 1200)
c.conn.execute("INSERT INTO meta (k, v) VALUES (?, ?)", (f"ext_prewindow_tx:eth:{h(4)}", str(NOW - 12 * DAY)))
c.conn.commit()
time.sleep(0)
r4 = c._hist_late_scan(now=NOW + 300)
check("C 재구축 대기 표식(대사 앵커가 흡수한 옛 조각) tx = 표식 없음 · 커서는 전진", r4 is None and marks(c) == mk1 and int(c._meta_get(common.HIST_LATE_PID_K)) == c.conn.execute(
    "SELECT MAX(posting_id) FROM postings").fetchone()[0], (r4, marks(c)))

T7 = NOW - 7 * DAY
feed(c, h(5), T7, E18, 1300)
c.conn.close()
c = core.Core(common.load_config())
c.conn.commit()
r5 = c._hist_late_scan(now=NOW + 400)
mk5 = marks(c)
check("D 커밋 직후 종료 → 재시작 첫 바퀴에 같은 행 표식(커서가 안 움직였음)", r5 == iso(T7) and mk5[-1][1] == iso(T7) and len(mk5) == 2, (r5, mk5))
T9 = NOW - 9 * DAY
feed(c, h(6), T9, E18, 1400)
feed(c, h(7), NOW - 3 * DAY, E18, 1450)
r6 = c._hist_late_scan(now=NOW + 1000)
check("D 옛 코드(롤백 중)가 쓴 늦은 행 = 돌아온 뒤 가장 이른 날로 표식", r6 == iso(T9) and marks(c)[-1][1] == iso(T9), (r6, marks(c)))

TS8 = NOW - 8 * DAY
srec = {"v": 1, "kind": "sol_tx", "chain": "sol", "txhash": "S" + "8" * 87, "slot": 900, "ts": TS8, "fee_lamports": 0, "fee_payer_mine": False,
        "fee_payer": None, "wallets": [SOLW], "deltas": [{"asset": "native", "symbol": "SOL", "decimals": 9, "delta": "5000000000", "owner": SOLW}],
        "counterparties": [], "has_program": False, "err": False}
c._drain_stream("sol", Reader([srec]), 0, 0)
r7 = c._hist_late_scan(now=NOW + 2000)
check("E 솔라나 8일 전 늦은 tx = 그 날 표식", r7 == iso(TS8) and marks(c)[-1][1] == iso(TS8), (r7, marks(c)[-1:]))
c.conn.execute("BEGIN")
for t9 in ("postings", "tx_class", "transfers", "positions"):
    c.conn.execute(f"DELETE FROM {t9}")
c.conn.execute("DELETE FROM meta WHERE k LIKE 'ext\\_prewindow\\_tx:%' ESCAPE '\\'")
c.conn.commit()
for r9 in c.conn.execute("SELECT chain, txhash, snapshot FROM raw_txs ORDER BY ingested_at, chain, txhash").fetchall():
    c.conn.execute("BEGIN")
    s9 = json.loads(r9["snapshot"])
    if r9["chain"] == "sol" and s9.get("kind") == "sol_tx":
        c.apply_sol(s9)
    else:
        c.apply(r9["chain"], r9["txhash"], "", s9)
    c.conn.commit()
r8 = c._hist_late_scan(now=NOW + 3000)
check("E 재구축식 다시 기장(새 posting id) = 가장 이른 날(40일 전)부터 표식 — 교체 뒤 장기 곡선 창 밖도 다시", r8 == iso(NOW - 40 * DAY), (r8, marks(c)[-1:]))
src9 = inspect.getsource(core.Core.run)
check("E 소비 루프 한 바퀴마다 부름(예외는 로그 — 커서 그대로)", "self._hist_late_scan()" in src9, "run() 에 호출 없음")
last_id = marks(c)[-1][0]
c.conn.close()

import shutil
for sfx in ("-wal", "-shm"):
    if os.path.exists(common.DB_PATH + sfx):
        os.remove(common.DB_PATH + sfx)
shutil.copyfile(BK, common.DB_PATH)
c = core.Core(common.load_config())
c.conn.commit()
mkF = marks(c)
rF0 = c._hist_late_scan(now=NOW + 4000)
feed(c, h(9), NOW - 2 * DAY, E18, 1600)
rF = c._hist_late_scan(now=NOW + 4100)
mkF2 = marks(c)
check("F 되돌린 원장 = 그때 표식·커서 그대로(새 행 없으면 표식 없음) · 그 뒤 늦은 행 = 새 표식 id 가 되돌리기 전 id 보다 큼(지문 비교가 뒤로 안 감)",
      mkF == mk1 and rF0 is None and rF == iso(NOW - 2 * DAY) and mkF2[-1][0] > last_id and mkF2[-1][0] > ID_B, (mkF, rF0, rF, mkF2[-1:], last_id))
c.conn.close()
T.finish()
