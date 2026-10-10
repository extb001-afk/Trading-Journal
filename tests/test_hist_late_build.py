#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _ingest
from _ingest import W, Reader

import json
import os
import time

json.dump({"chains": {"eth": {"blockscout": "https://bs.invalid", "etherscan_chainid": 1, "conf_depth": 12, "blocks_per_day": 7200,
                              "rpcs": ["https://rpc.invalid"]}},
           "wallets": [{"type": "evm", "chain": "eth", "address": W, "label": "w"}],
           "native_symbol": {"eth": "ETH"}, "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
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
ISO = acct_norm.iso_day


def h(n):
    return "0x" + ("%064x" % n)


def snap(hx, ts, blk, value):
    return {"tx": {"hash": hx, "from": X, "to": W, "value": str(value), "fee": {"value": "0"}, "status": "ok", "raw_input": "0x",
                   "timestamp": ts, "block_number": blk, "block_hash": "0x" + "d" * 64}, "token_transfers": [], "internal": []}


def feed(c, hx, ts, value, blk):
    c._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": hx, "wallets": [W], "snapshot": snap(hx, ts, blk, value), "ts": 1}]), 0, 0)


def fake_lookup(spec, iso, now=None, w=0.0, ask=True, old=False):
    if "ETH" in str(spec).upper():
        return 2000.0, "ok"
    return None, "pending"


fake_lookup._tj_test_mock = True
histcurve.DAYCLOSE.lookup = fake_lookup
json.dump({"usd": {"ETH": 2000.0}, "usd_ts": {"ETH": NOW}, "rate": 1400.0, "updated": NOW, "dex_usd": {}, "dex_ts": {}, "dex_res": {}, "dex_res_ts": {},
           "fx_basis": 1400.0, "ex_usd": {}, "ex_ts": {}}, open(web.SPOT_PATH, "w"))
web.pricing.PxCache.candle_usd = lambda self, sym, ms: 2000.0 if str(sym).upper() == "ETH" else None
web.pricing._gj = lambda url, timeout=10.0: None
web.pricing.PxCache.fx_at = lambda self, ms: 1400.0
open(os.path.join(common.STATE_DIR, "backfill_done"), "w").write("1")
web.HL_SETTLE_S = 0


def build(no_marks=False):
    b = web.StateBuilder()
    b.skip_gen_check = True
    conn = dbm.open_db(common.DB_PATH, readonly=True)
    real = getattr(common, "hist_late_read", None)
    if no_marks and real is not None:
        common.hist_late_read = lambda c9: []
    try:
        return b._build(conn)["fields"]
    finally:
        if real is not None:
            common.hist_late_read = real
        conn.close()


def series(f):
    return {d.get("date"): d for d in f.get("dailySeries") or []}


def pnl(ser):
    ks = sorted(ser)
    return {k: round(float(ser[k]["val"]) - float(ser[p]["val"]) - float(ser[k].get("flow") or 0), 2) for p, k in zip(ks, ks[1:])}


c = core.Core(common.load_config())
feed(c, h(1), T0, 2 * E18, 1500)
c.conn.commit()
has9 = hasattr(c, "_hist_late_scan")
if has9:
    c._hist_late_scan()
fa = build()
feed(c, h(2), TL, E18, 2000)
c.conn.commit()
kd = ISO(TL)[5:]
ky = ISO(NOW - DAY)[5:]
k4 = ISO(TL - DAY)[5:]
fb = build(no_marks=True)
sb = series(fb)
pb = pnl(sb)
chk(abs(float(sb[ky]["val"]) - 4000) < 1 and abs(float(sb[ISO(NOW)[5:]]["val"]) - 6000) < 1 and abs(pb.get(kd, 0) + 2000) < 1 and abs(pb.get(ISO(NOW)[5:], 0) - 2000) < 1,
    "F1 표식 전(종전 재현) = 어제 4,000 그대로 · 오늘 6,000 · 사건 날 손익 −2,000 · 오늘 +2,000", (sb[ky]["val"], sb[ISO(NOW)[5:]]["val"], pb.get(kd), pb.get(ISO(NOW)[5:])))
if not has9:
    chk(False, "F2 core 늦은 원장 행 표식(_hist_late_scan) 있음", "없음")
    T.finish()
r9 = c._hist_late_scan()
chk(r9 == ISO(TL), "F2 core 표식 = 사건 날", (r9, ISO(TL)))
fc = build()
sc = series(fc)
pc = pnl(sc)
after = {k: sc[k]["val"] for k in sorted(sc) if k >= kd}
chk(all(abs(float(v) - 6000) < 1 for v in after.values()) and abs(float(sc[k4]["val"]) - 4000) < 1 and abs(float(sc[ISO(T0 + DAY)[5:]]["val"]) - 4000) < 1,
    "F2 다음 빌드 = 사건 날~오늘 6,000 · 사건 전 날 4,000 그대로", (after, sc[k4]["val"]))
chk(all(abs(v) < 1 for v in pc.values()), "F2 손익 쌍(−2,000 / +2,000) 사라짐 — 날별 (값 변화 − 순유입) = 0", {k: v for k, v in pc.items() if abs(v) >= 1})
dc9 = common.read_json(web.DAILY_PATH, {})
hq9 = {k: (dc9.get(k) or {}).get("hq") for k in sorted(dc9) if len(k) == 10 and k[4] == "-" and k >= ISO(TL)}
chk(hq9 and all(v and v == common.hist_late_read(c.conn)[-1][0] for v in hq9.values()), "F2 다시 굳힌 날 지문 hq = 원장 표식 id", hq9)
dc9[ISO(NOW - 2 * DAY)]["val"] = 6001.0
json.dump(dc9, open(web.DAILY_PATH, "w"))
fd = build()
chk(abs(float(series(fd)[ISO(NOW - 2 * DAY)[5:]]["val"]) - 6001) < 0.01, "F2 그다음 빌드 = 손 안 댐(같은 날 반복 없음)", series(fd)[ISO(NOW - 2 * DAY)[5:]]["val"])
feed(c, h(2), TL, E18, 2000)
r10 = c._hist_late_scan()
fe = build()
chk(r10 is None and abs(float(series(fe)[ISO(NOW - 2 * DAY)[5:]]["val"]) - 6001) < 0.01, "F3 같은 거래 재입력 = 표식 없음 → 다시 계산 없음", (r10, series(fe)[ISO(NOW - 2 * DAY)[5:]]["val"]))
c.conn.close()
T.finish()
