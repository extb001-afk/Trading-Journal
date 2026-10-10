#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _ingest
from _ingest import W, SOLW

import json
import os
import time

json.dump({"chains": {"eth": {"blockscout": "https://bs.invalid", "etherscan_chainid": 1, "conf_depth": 12, "blocks_per_day": 7200,
                              "rpcs": ["https://rpc.invalid"]}},
           "wallets": [{"type": "evm", "chain": "eth", "address": W, "label": "w"}, {"type": "sol", "chain": "sol", "address": SOLW, "label": "s"}],
           "native_symbol": {"eth": "ETH"}, "backfill_months": 5, "sol": {"rpcs": ["https://solrpc.invalid"]}},
          open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
import acct_norm
import common
import core
import db as dbm
import histcurve
import netpace
import web

chk = T.chk
core.dm = lambda *a, **k: None
for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker"):
    if hasattr(web.StateBuilder, _m):
        setattr(web.StateBuilder, _m, lambda self: None)
netpace.wait = lambda url, now=None, sleep=None: None
E18 = 10 ** 18
DAY = 86400
NOW = int(time.time())
X = "0x" + "b7" * 20
T0 = NOW - 20 * DAY
TL = NOW - 5 * DAY
TS = NOW - 8 * DAY
ISO = acct_norm.iso_day
PX = {"ETH": 2000.0, "SOL": 100.0}


def h(n):
    return "0x" + ("%064x" % n)


def erec(hx, ts, blk, value):
    snap = {"tx": {"hash": hx, "from": X, "to": W, "value": str(value), "fee": {"value": "0"}, "status": "ok", "raw_input": "0x",
                   "timestamp": ts, "block_number": blk, "block_hash": "0x" + "d" * 64}, "token_transfers": [], "internal": []}
    return {"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": hx, "wallets": [W], "snapshot": snap, "ts": 1}


def srec(sig, ts, lamports):
    return {"v": 1, "kind": "sol_tx", "chain": "sol", "txhash": sig, "slot": 900, "ts": ts, "fee_lamports": 0, "fee_payer_mine": False,
            "fee_payer": None, "wallets": [SOLW], "deltas": [{"asset": "native", "symbol": "SOL", "decimals": 9, "delta": str(lamports), "owner": SOLW}],
            "counterparties": [], "has_program": False, "err": False}


class Once:

    def __init__(self, recs=()):
        self.recs = list(recs)
        self.n = 0

    def read_batch(self, seg, off):
        if self.n or not self.recs:
            return [], seg, off
        self.n += 1
        return [(r, seg, off + i + 1) for i, r in enumerate(self.recs)], seg, off + len(self.recs)

    def gc(self, seg, off):
        pass


class _Stop(Exception):
    pass


def one_cycle(c, evm=(), sol=()):
    c.reader, c.sol_reader, c.bsc_reader, c.ex_reader = Once(evm), Once(sol), Once(), Once()
    c.recon_pass = lambda drained: None
    c.prov_pass = lambda: None
    calls = []

    def stop(*a, **k):
        calls.append(1)
        raise _Stop()
    real = core.ledger_backup.tick
    core.ledger_backup.tick = stop
    try:
        c.run()
    except _Stop:
        pass
    finally:
        core.ledger_backup.tick = real
    return calls


def fake_lookup(spec, iso, now=None, w=0.0, ask=True, old=False):
    for s9, p9 in PX.items():
        if s9 in str(spec).upper():
            return p9, "ok"
    return None, "pending"


fake_lookup._tj_test_mock = True
histcurve.DAYCLOSE.lookup = fake_lookup
json.dump({"usd": dict(PX), "usd_ts": {k: NOW for k in PX}, "rate": 1400.0, "updated": NOW, "dex_usd": {}, "dex_ts": {}, "dex_res": {}, "dex_res_ts": {},
           "fx_basis": 1400.0, "ex_usd": {}, "ex_ts": {}}, open(web.SPOT_PATH, "w"))
web.pricing.PxCache.candle_usd = lambda self, sym, ms: PX.get(str(sym).upper())
web.pricing._gj = lambda url, timeout=10.0: None
web.pricing.PxCache.fx_at = lambda self, ms: 1400.0
open(os.path.join(common.STATE_DIR, "backfill_done"), "w").write("1")
web.HL_SETTLE_S = 0


def build():
    b = web.StateBuilder()
    b.skip_gen_check = True
    conn = dbm.open_db(common.DB_PATH, readonly=True)
    try:
        return b._build(conn)["fields"]
    finally:
        conn.close()


def series(f):
    return {d.get("date"): d for d in f.get("dailySeries") or []}


def pnl(ser):
    ks = sorted(ser)
    return {k: round(float(ser[k]["val"]) - float(ser[p]["val"]) - float(ser[k].get("flow") or 0), 2) for p, k in zip(ks, ks[1:])}


c = core.Core(common.load_config())
c._drain_stream("evm", Once([erec(h(1), T0, 1500, 2 * E18)]), 0, 0)
c._drain_stream("sol", Once([srec("S" + "1" * 87, T0 + 60, 30 * 10 ** 9)]), 0, 0)
c.conn.commit()
fa = build()
sa = series(fa)
ky = ISO(NOW - DAY)[5:]
chk(abs(float(sa[ky]["val"]) - 7000) < 1, "준비: 지난 곡선 동결 = 2 ETH × 2,000 + 30 SOL × 100 = 7,000", sa.get(ky))
c.conn.execute("DELETE FROM meta WHERE k=?", (common.HIST_LATE_PID_K,))
c.conn.commit()
pid_before = c.conn.execute("SELECT MAX(posting_id) FROM postings").fetchone()[0]
import sqlite3
BK0 = common.DB_PATH + ".bk_old"
_b0 = sqlite3.connect(BK0)
c.conn.backup(_b0)
_b0.close()
c.conn.close()

c = core.Core(common.load_config())
st = one_cycle(c, evm=[erec(h(2), TL, 2000, E18)], sol=[srec("S" + "2" * 87, TS, 10 * 10 ** 9)])
n_new = c.conn.execute("SELECT COUNT(*) FROM postings WHERE posting_id > ?", (pid_before,)).fetchone()[0]
mk = common.hist_late_read(c.conn)
cur = c._meta_get(common.HIST_LATE_PID_K)
chk(st == [1] and n_new >= 2, "G1 실제 run 한 바퀴가 늦은 두 거래를 기장하고 바퀴 끝까지 감", (st, n_new))
chk(len(mk) == 1 and mk[0][1] == ISO(TS), "G1 첫 주기 늦은 거래 = 표식(가장 이른 날 = SOL 8일 전) — 종전: 커서만(표식 없음)", (mk, ISO(TS)))
chk(cur is not None and int(cur) == c.conn.execute("SELECT MAX(posting_id) FROM postings").fetchone()[0],
    "G1 바퀴 끝 커서 = 이번 주기 마지막 행", (cur,))
fb = build()
sb = series(fb)
pb = pnl(sb)
ks8, ks5 = ISO(TS)[5:], ISO(TL)[5:]
kb8 = ISO(TS - DAY)[5:]
chk(abs(float(sb[ks8]["val"]) - 8000) < 1 and abs(float(sb[ks5]["val"]) - 10000) < 1 and abs(float(sb[ky]["val"]) - 10000) < 1
    and abs(float(sb[kb8]["val"]) - 7000) < 1,
    "G1 다음 빌드 = SOL 날~ 8,000 · EVM 날~어제 10,000 · 사건 전 날 7,000 그대로", (sb[kb8]["val"], sb[ks8]["val"], sb[ks5]["val"], sb[ky]["val"]))
chk(all(abs(v) < 1 for v in pb.values()), "G1 손익 쌍(사건 날 −X / 오늘 +X) 없음 — 날별 (값 변화 − 순유입) = 0", {k: v for k, v in pb.items() if abs(v) >= 1})

dc9 = common.read_json(web.DAILY_PATH, {})
kmid = ISO(NOW - 3 * DAY)
dc9[kmid]["val"] = 10001.0
json.dump(dc9, open(web.DAILY_PATH, "w"))
fc = build()
chk(abs(float(series(fc)[kmid[5:]]["val"]) - 10001) < 0.01, "G2 그다음 빌드 = 손 안 댐(같은 날 반복 없음)", series(fc)[kmid[5:]]["val"])
c.conn.close()
c = core.Core(common.load_config())
st2 = one_cycle(c)
mk2 = common.hist_late_read(c.conn)
cur2 = c._meta_get(common.HIST_LATE_PID_K)
fd = build()
chk(st2 == [1] and mk2 == mk and cur2 == cur and abs(float(series(fd)[kmid[5:]]["val"]) - 10001) < 0.01,
    "G2 재시작(새 행 없는 run 바퀴) = 커서·표식 그대로 · 다시 계산 없음", (st2, mk2, cur2, cur))

chk(all(m[1] >= ISO(TS) for m in mk2), "G3 배포 전부터 있던 20일 전 행 = 표식 대상 아님(소급 안 함 · 15차 결정 유지)", mk2)

BK1 = common.DB_PATH + ".bk_new"
_b1 = sqlite3.connect(BK1)
c.conn.backup(_b1)
_b1.close()
cur_new = c._meta_get(common.HIST_LATE_PID_K)
mk_new = common.hist_late_read(c.conn)
c.conn.close()


def restore(src9):
    for sfx in ("-wal", "-shm"):
        if os.path.exists(common.DB_PATH + sfx):
            os.remove(common.DB_PATH + sfx)
    _s9 = sqlite3.connect(src9)
    _d9 = sqlite3.connect(common.DB_PATH)
    _s9.backup(_d9)
    _d9.close()
    _s9.close()


restore(BK0)
c = core.Core(common.load_config())
st5 = one_cycle(c)
cur5 = c._meta_get(common.HIST_LATE_PID_K)
chk(st5 == [1] and cur5 is not None and int(cur5) == pid_before and common.hist_late_read(c.conn) == [],
    "G5 커서 없는 옛 백업으로 되돌린 뒤 기동 = 울타리 = 그 원장 MAX(소급 표식 없음)", (cur5, pid_before, common.hist_late_read(c.conn)))
c.conn.close()
restore(BK1)
c = core.Core(common.load_config())
one_cycle(c, evm=[erec(h(3), NOW - 2 * DAY, 2500, E18)])
mk5 = common.hist_late_read(c.conn)
id_new = max((m[0] for m in mk_new), default=0)
chk(int(c._meta_get(common.HIST_LATE_PID_K)) > int(cur_new) and any(m[0] > id_new and m[1] <= ISO(NOW - 2 * DAY) for m in mk5),
    "G5 울타리 있는 백업 = 그 커서 그대로 이어 첫 주기 늦은 거래(2일 전) 표식(새 id · 그 날 이하 — 2분 안 표식은 합침)", (cur_new, mk_new, mk5))
for p9 in (BK0, BK1):
    os.remove(p9)

bw = web.StateBuilder()
bw.skip_gen_check = True
cw = dbm.open_db(common.DB_PATH, readonly=True)
try:
    bw._build(cw)
finally:
    cw.close()
lv = bw.daily.get("_live") or {}
chk(lv.get("pw") == c.conn.execute("SELECT MAX(posting_id) FROM postings").fetchone()[0], "G4 전체 빌드의 오늘 실시간 스냅숏에 원장 수위 pw(문서1 6.2 — 마감 채택 때 그 뒤 행 검사)",
    (lv.get("pw"), lv.get("hq")))
c.conn.close()
T.finish()
