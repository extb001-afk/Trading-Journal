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
import discopen
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
TKN, TKC, TKO = "0x" + "e1" * 20, "0x" + "e3" * 20, "0x" + "e4" * 20
T0 = NOW - 20 * DAY
TA = NOW - 6 * DAY
KST = timezone(timedelta(hours=9))


def h(n):
    return "0x" + ("%064x" % n)


def feed(c, hx, s):
    c._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": hx, "wallets": [W], "snapshot": s, "ts": 1}]), 0, 0)


open(os.path.join(common.STATE_DIR, "backfill_done"), "w").write("1")
os.environ["TJ_NEGABS"] = "0"
c = core.Core(common.load_config())
feed(c, h(1), {"tx": {"hash": h(1), "from": X, "to": W, "value": str(2 * E18), "fee": {"value": "0"}, "status": "ok", "raw_input": "0x",
                      "timestamp": T0, "block_number": 1500, "block_hash": "0x" + "d" * 64}, "token_transfers": [], "internal": []})
c.conn.commit()


def fake_lookup(spec, iso, now=None, w=0.0, ask=True, old=False):
    s9 = str(spec).lower()
    if "e1e1" in s9:
        return 2.0, "ok"
    if "e3e3" in s9:
        return 3.0, "ok"
    if "e4e4" in s9:
        return 5.0, "ok"
    if "e5e5" in s9:
        return 7.0, "ok"
    if "ETH" in str(spec).upper():
        return 2000.0, "ok"
    return None, "pending"


fake_lookup._tj_test_mock = True
histcurve.DAYCLOSE.lookup = fake_lookup
dex = {f"eth:{TKN}": 2.0, f"eth:{TKC}": 3.0, f"eth:{TKO}": 5.0, "eth:0x" + "e5" * 20: 7.0}
json.dump({"usd": {"ETH": 2000.0}, "usd_ts": {"ETH": NOW}, "rate": 1400.0, "updated": NOW, "dex_usd": dex, "dex_ts": {k: NOW for k in dex},
           "dex_res": {k: 1e6 for k in dex}, "dex_res_ts": {k: NOW for k in dex}, "fx_basis": 1400.0, "ex_usd": {}, "ex_ts": {}}, open(web.SPOT_PATH, "w"))
web.pricing.PxCache.candle_usd = lambda self, sym, ms: None
web.pricing._gj = lambda url, timeout=10.0: None


def build():
    try:
        os.remove(os.path.join(common.STATE_DIR, "daily_cache.json"))
    except FileNotFoundError:
        pass
    global BB
    b = BB = web.StateBuilder()
    b.skip_gen_check = True
    conn = dbm.open_db(common.DB_PATH, readonly=True)
    try:
        return b._build(conn)["fields"]
    finally:
        conn.close()


def anchor(ca, sym, qty, blk, src):
    aid = c.asset_id("token", "eth", ca, symbol=sym, decimals=18)
    sid = discopen.write_anchor(c, "eth", W, aid, ca, qty, blk, TA - 12, TA - 12, qty, "token_recheck", {"_sources": [src], "_diff_raw": str(qty)})
    return aid, sid


aN, sN = anchor(TKN, "TKN", 1000 * E18, 2000, "bsc_balance_watch")
aC, sC = anchor(TKC, "TKC", 500 * E18, 2001, "synthetic")
aO, sO = anchor(TKO, "TKO", 100 * E18, 2002, "bsc_balance_watch_old")
c.conn.commit()
fb = build()
ser = fb.get("dailySeries") or []
dk = datetime.fromtimestamp(TA, KST).strftime("%m-%d")
row = next((r for r in ser if r.get("date") == dk), {})
prev = ser[ser.index(row) - 1] if row in ser and ser.index(row) > 0 else {}
gk = lambda a9: c.conn.execute("SELECT group_id FROM assets WHERE asset_id=?", (a9,)).fetchone()[0]
bk = getattr(BB, "_disc_back", None) or set()
want_prev = 1500 + 500
chk(sN and sC and sO and abs(float(prev.get("val") or 0) - want_prev) < 1.0,
    "C1 입금 전날 곡선 = 잔고 감시 새 입금(TKN 1,000 × $2) 빠짐 · 옛 몫·그 밖 발견 잔고는 소급(종전 = +$2,000 부풂)", (dk, prev.get("date"), prev.get("val"), want_prev))
chk(abs(float(row.get("val") or 0) - (want_prev + 2000)) < 1.0, "C1 입금 날부터 = TKN 포함", (row.get("date"), row.get("val")))
chk(gk(aN) not in bk and gk(aC) in bk and gk(aO) in bk, "C2 창 시작으로 당긴 그룹 = 그 밖 발견 잔고·옛 몫만(잔고 감시 새 입금은 제자리)", (bk, gk(aN), gk(aC), gk(aO)))
early = [r for r in ser if r.get("date") and r.get("date") < dk]
chk(len(early) >= 3 and all(abs(float(r.get("val") or 0) - want_prev) < 1.0 for r in early[-5:]), "C1 입금 전 지난날 전부 같은 값(계단 없음)",
    [(r.get("date"), r.get("val")) for r in early[-5:]])
FX0 = BB.daily.get(datetime.fromtimestamp(NOW - 3 * DAY, KST).strftime("%Y-%m-%d")) or {}
chk(str(FX0.get("dq") or "").startswith("3:"), "C3 동결 항목 지문 dq = 발견 시점 기초 잔고 3건(잔고 감시 새 입금 포함 — 제자리여도 지문엔 듦)", FX0.get("dq"))

TKY = "0x" + "e5" * 20
yk = datetime.fromtimestamp(NOW, KST).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
y_iso = yk.strftime("%Y-%m-%d")
end_y = yk.replace(hour=23, minute=59, second=59).timestamp()
ent = dict(BB.daily.get(y_iso) or {})
g_y = dict(ent.get("g") or {})
snap_y = {"date": y_iso, "ts": end_y - 60, "val": float(ent.get("val") or 0), "usdt": 1400.0, "kimp": None, "g": g_y, "x": 0.0,
          "defer": False, "p": {}, "dq": ent.get("dq", "")}
BB.daily["_live_ok"] = dict(snap_y)
BB.daily["_live"] = dict(snap_y)
aY = c.asset_id("token", "eth", TKY, symbol="TKY", decimals=18)
tY = int(end_y) - 29 * 60
sY = discopen.write_anchor(c, "eth", W, aY, TKY, 10 * E18, 2100, tY, tY, 10 * E18, "token_recheck", {"_sources": ["bsc_balance_watch"], "_diff_raw": str(10 * E18)})
c.conn.commit()
try:
    os.remove(os.path.join(common.STATE_DIR, "daily_cache.json"))
except FileNotFoundError:
    pass
conn4 = dbm.open_db(common.DB_PATH, readonly=True)
try:
    fb4 = BB._build(conn4)["fields"]
finally:
    conn4.close()
ser4 = fb4.get("dailySeries") or []
r4 = next((r for r in ser4 if r.get("date") == yk.strftime("%m-%d")), {})
want4 = float(snap_y["val"]) + 10 * 7.0
chk(sY and abs(float(r4.get("val") or 0) - want4) < 1.0,
    "C4 입금 빠진 어제 마감 스냅숏을 다시 굳히지 않음 — 어제 = 스냅숏 값 + TKY 10 × $7(종전 = 스냅숏 그대로 · 입금 누락 동결)", (r4.get("date"), r4.get("val"), want4, snap_y["val"]))
chk((BB.daily.get(y_iso) or {}).get("src") != "live", "C4 어제 동결 항목 = 원장 다시 계산(스냅숏 'live' 아님)", (BB.daily.get(y_iso) or {}).get("src"))
c.conn.close()
T.finish()
