#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _ingest
from _ingest import W, Reader

import json
import os
import time
from datetime import datetime, timedelta, timezone

json.dump({"chains": {"eth": {"blockscout": "https://bs.invalid", "etherscan_chainid": 1, "conf_depth": 12, "blocks_per_day": 7200,
                              "rpcs": ["https://rpc.invalid"]}},
           "wallets": [{"type": "evm", "chain": "eth", "address": W, "label": "w"}],
           "native_symbol": {"eth": "ETH"}, "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
import common
import core
import db as dbm
import histcurve
import netpace
import web
import xparts

chk = T.chk
core.dm = lambda *a, **k: None
for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker"):
    if hasattr(web.StateBuilder, _m):
        setattr(web.StateBuilder, _m, lambda self: None)
netpace.wait = lambda url, now=None, sleep=None: None
open(os.path.join(common.STATE_DIR, "backfill_done"), "w").write("1")
KST = timezone(timedelta(hours=9))
DAY = 86400
NOW = int(time.time())
TODAY = datetime.fromtimestamp(NOW, KST).replace(hour=0, minute=0, second=0, microsecond=0)
X = "0x" + "b7" * 20
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
MGR = "0x" + "c3" * 20
T0 = NOW - 20 * DAY


def day(i, h=12):
    return int((TODAY - timedelta(days=i)).replace(hour=h).timestamp())


def iso(i):
    return (TODAY - timedelta(days=i)).strftime("%Y-%m-%d")


def mmdd(i):
    return (TODAY - timedelta(days=i)).strftime("%m-%d")


def h(n):
    return "0x" + ("%064x" % n)


def snap(hx, ts, blk, frm, to, toks=()):
    return {"tx": {"hash": hx, "from": frm, "to": to, "value": "0", "fee": {"value": "0"}, "status": "ok", "raw_input": "0xa9059cbb",
                   "timestamp": ts, "block_number": blk, "block_hash": "0x" + "d" * 64},
            "token_transfers": [{"from": f, "to": t, "token": {"address": ca, "symbol": sym, "decimals": 6, "type": "ERC-20"},
                                 "total": {"value": str(v)}} for f, t, ca, sym, v in toks], "internal": []}


c = core.Core(common.load_config())
c._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": h(1), "wallets": [W],
                                "snapshot": snap(h(1), T0, 1500, X, USDC, toks=[(X, W, USDC, "USDC", 100000 * 10 ** 6)]), "ts": 1}]), 0, 0)
c.conn.commit()
aid, gid = c.conn.execute("SELECT asset_id, group_id FROM assets WHERE address=?", (USDC,)).fetchone()
WLOC = c.conn.execute("SELECT location FROM positions WHERE group_id=? AND location LIKE 'wallet:%'", (gid,)).fetchone()[0]
LPLOC = "lp:eth:%s:7" % MGR


def lp_legs(rows):
    for i9, (hx, t9, ev9, lk9, loc9, q9) in enumerate(rows):
        c.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw,"
                       " leg_kind, event, classifier_ver) VALUES ('chain_tx', 'eth', ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, 1)",
                       (hx, i9, t9, aid, loc9, str(q9 * 10 ** 6), lk9, ev9))
        r9 = c.conn.execute("SELECT qty_norm FROM positions WHERE group_id=? AND location=?", (gid, loc9)).fetchone()
        if r9:
            c.conn.execute("UPDATE positions SET qty_norm=? WHERE group_id=? AND location=?", (str(float(r9[0]) + q9), gid, loc9))
        else:
            c.conn.execute("INSERT INTO positions (group_id, location, qty_norm) VALUES (?,?,?)", (gid, loc9, str(float(q9))))
    c.conn.commit()


def pin(lp_days, lp_val):
    d9 = {"_v": 1}
    for i9 in range(1, 30):
        d9[iso(i9)] = {"p": {}, "k": {}, "xv": {"v": xparts.GEN, "p": {"ku": [0.0, "snap"], "kb": [0.0, "snap"], "ub": [{}, "snap"],
                                                                     "rest": [lp_val if i9 in lp_days else 0.0, "snap"]}, "fx": 1400.0, "how": "live"}}
    json.dump(d9, open(web.DAILY_PX_PATH, "w"))


json.dump({"usd": {"ETH": 2000.0}, "usd_ts": {"ETH": NOW}, "rate": 1400.0, "updated": NOW, "dex_usd": {}, "dex_ts": {}, "dex_res": {}, "dex_res_ts": {},
           "fx_basis": 1400.0, "ex_usd": {}, "ex_ts": {}}, open(web.SPOT_PATH, "w"))
web.pricing.PxCache.candle_usd = lambda self, sym, ms: None
web.pricing.PxCache.fx_at = lambda self, ms: 1400.0
web.pricing._gj = lambda url, timeout=10.0: None
histcurve.DAYCLOSE.lookup = (lambda *a, **k: (None, "pending"))
histcurve.DAYCLOSE.lookup._tj_test_mock = True


def build(keep_cache=False):
    if not keep_cache:
        for p9 in (web.DAILY_PATH,):
            if os.path.exists(p9):
                os.remove(p9)
    b = web.StateBuilder()
    b.skip_gen_check = True
    conn = dbm.open_db(common.DB_PATH, readonly=True)
    try:
        f9 = b._build(conn)["fields"]
    finally:
        conn.close()
    return b, {d9.get("date"): d9.get("val") for d9 in f9.get("dailySeries") or []}


def close(a, b9, tol=0.5):
    return a is not None and abs(float(a) - float(b9)) < tol


lp_legs([(h(2), day(4, 15), "LP_ADD", "move_out", WLOC, -30000), (h(2), day(4, 15), "LP_ADD", "move_in", LPLOC, 30000),
         (h(3), day(2, 10), "LP_REMOVE", "move_out", LPLOC, -30000), (h(3), day(2, 10), "LP_REMOVE", "move_in", WLOC, 30000)])
pin({3, 4}, 30015.0)
b1, v1 = build()
chk(close(v1.get(mmdd(5)), 100000) and close(v1.get(mmdd(2)), 100000) and close(v1.get(mmdd(0)), 100000), "B1 예치 전 날·회수 날·오늘 = $100,000",
    (v1.get(mmdd(5)), v1.get(mmdd(2)), v1.get(mmdd(0))))
chk(close(v1.get(mmdd(4)), 100015) and close(v1.get(mmdd(3)), 100015), "B1 LP 열린 날 = 지갑 몫 70,000 + LP 평가 30,015 = $100,015(수정 전 $130,015 — 원금 이중)",
    (v1.get(mmdd(4)), v1.get(mmdd(3))))
b2, v2 = build()
chk(all(close(v2.get(k9), v9) for k9, v9 in v1.items() if k9 != mmdd(0)), "B2 무효화 뒤 다시 계산 = 같은 지난날 값", {k9: (v1[k9], v2.get(k9)) for k9 in list(v1)[-6:]})
try:
    G9 = {gid: {"gid": gid, "sym": "USDC", "is_stable": True, "qty_timeline": [(T0, 100000)],
                "lp_tl": [(day(4, 15), 30000), (day(2, 10), -30000)]}}
    kit9 = histcurve.make_kit(TODAY.strftime("%Y-%m-%d"), G9, {gid: 100000}, set(), set(), {}, set(), {}, {}, {}, [], {}, [], {},
                              xkit=b2.__dict__.get("_x_kit"))
    q9 = histcurve.rewind(kit9, [iso(5), iso(4), iso(3), iso(2)])
except Exception as e9:
    q9 = {"_exc": repr(e9)}
chk(close((q9.get(gid) or {}).get(iso(4)), 70000) and close((q9.get(gid) or {}).get(iso(5)), 100000) and close((q9.get(gid) or {}).get(iso(2)), 100000),
    "B2 장기 곡선 rewind(빌드가 만든 x 재료) = 30일 곡선과 같은 지갑 수량(LP 열린 날 70,000)", q9)
c.conn.execute("DELETE FROM postings WHERE source_id=?", (h(3),))
c.conn.execute("UPDATE positions SET qty_norm=? WHERE group_id=? AND location=?", ("70000", gid, WLOC))
c.conn.execute("UPDATE positions SET qty_norm=? WHERE group_id=? AND location=?", ("30000", gid, LPLOC))
c.conn.commit()
pin({1, 2, 3, 4}, 30015.0)
b3, v3 = build()
chk(close(v3.get(mmdd(5)), 100000), "B3 아직 열린 LP — 예치 전 날 = 지갑 $100,000(수정 전 $70,000 — 지금 LP 원금만큼 모자람)", v3.get(mmdd(5)))
chk(close(v3.get(mmdd(3)), 100015), "B3 예치 뒤 날 = 지갑 몫 70,000 + LP 평가 30,015", v3.get(mmdd(3)))
c.conn.close()
T.finish()
