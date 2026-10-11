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
RT = "0x" + "e5" * 20
ISO = acct_norm.iso_day
PX = 2000.0
FX = 1400.0


def h(n):
    return "0x" + ("%064x" % n)


def esnap(hx, ts, blk, internal=()):
    return {"tx": {"hash": hx, "from": W, "to": RT, "value": "0", "fee": {"value": "0"}, "status": "ok", "raw_input": "0x12345678",
                   "timestamp": ts, "block_number": blk, "block_hash": "0x" + "d" * 64}, "token_transfers": [],
            "internal": [{"from": f, "to": t, "value": str(v), "success": True} for (f, t, v) in internal]}


def feed(c, hx, snap, repair=None):
    rec = {"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": hx, "wallets": [W], "snapshot": snap, "ts": 1}
    if repair:
        rec["repair"] = repair
    c._drain_stream("evm", Reader([rec]), 0, 0)


def fake_lookup(spec, iso, now=None, w=0.0, ask=True, old=False):
    if "ETH" in str(spec).upper():
        return PX, "ok"
    return None, "pending"


fake_lookup._tj_test_mock = True
histcurve.DAYCLOSE.lookup = fake_lookup
json.dump({"usd": {"ETH": PX}, "usd_ts": {"ETH": NOW}, "rate": FX, "updated": NOW, "dex_usd": {}, "dex_ts": {}, "dex_res": {}, "dex_res_ts": {},
           "fx_basis": FX, "ex_usd": {}, "ex_ts": {}}, open(web.SPOT_PATH, "w"))
web.pricing.PxCache.candle_usd = lambda self, sym, ms: PX if str(sym).upper() == "ETH" else None
web.pricing._gj = lambda url, timeout=10.0: None
web.pricing.PxCache.fx_at = lambda self, ms: FX
web.HL_SETTLE_S = 0


def fake_entry(k, lo, hi, now, need=None, fx_get=None, prev=None, xref=None, blocked=None):
    return {"st": "ok", "n": 0, "lo": lo, "hi": hi, "p": {d9: PX for d9 in histcurve.days_between(lo, hi)}, "src": ["test"], "at": int(now)}


histcurve.fetch_entry = fake_entry
HH = histcurve.HIST
KIT = {}
HH.offer = lambda today_iso, kit_fn, now=None: KIT.__setitem__("fn", kit_fn) or True


def build():
    b = web.StateBuilder()
    b.skip_gen_check = True
    conn = dbm.open_db(common.DB_PATH, readonly=True)
    try:
        return b._build(conn)["fields"]
    finally:
        conn.close()


def run_hist(now9):
    kit = KIT["fn"]()
    kit["made"] = time.time() + 2 * histcurve.DIRTY_MARGIN_S
    days9 = histcurve.days_between(kit.get("first") or "2026-01-01", kit["today"])
    HH.px["fx"] = {"lo": days9[0], "hi": days9[-1], "st": "ok", "p": {d9: FX for d9 in days9}}
    rep = {}
    for _ in range(6):
        rep = HH.run_once(kit, cap=1000, now=now9)
        if not HH.pending:
            break
    return rep, dict(HH.st.get("d") or {})


def val(d9, ts):
    r9 = d9.get(ISO(ts))
    return float(r9[0]) if isinstance(r9, list) and r9 and r9[0] is not None else None


def near(a, b9, tol=1.0):
    return a is not None and abs(float(a) - float(b9)) < tol


c = core.Core(common.load_config())
c.conn.commit()
TL = NOW - 45 * DAY
feed(c, h(1), esnap(h(1), TL, 1000))
c._scope_ready = lambda s: True
c._recon_quiet = lambda *a: True
c._recon_bal = lambda chain, kind, mode, wallets: {"per_wallet": {W: {("native", None): 10 * E18}}} if chain == "eth" else None
c._last_recon = 0
c.recon_pass(set())
for k9 in ("_scope_ready", "_recon_quiet", "_recon_bal"):
    c.__dict__.pop(k9, None)
W0 = c._win_t0(None, "eth")
c._hist_late_scan()
open(os.path.join(common.STATE_DIR, "backfill_done"), "w").write(repr(time.time() - 3600))
D_MID, D_AFTER, D_WIN = NOW - 100 * DAY, NOW - 40 * DAY, NOW - 10 * DAY
build()
rep1, d1 = run_hist(NOW)
chk(near(val(d1, D_MID), 20000) and near(val(d1, D_AFTER), 20000) and near(val(d1, W0 + DAY), 20000),
    "C1 (전제) 늦게 받기 전 장기 곡선 = 창 밖 날 $20,000(기초 잔고 10 ETH)", (val(d1, W0 + DAY), val(d1, D_MID), val(d1, D_AFTER), rep1.get("computed")))

feed(c, h(1), esnap(h(1), TL, 1000, internal=[(RT, W, 5 * E18)]), repair="int_fill")
c._hist_late_scan()
mk = common.hist_late_read(c.conn)
chk(mk and min(m[1] for m in mk) == ISO(W0), "C2 (전제) core 원장 표식 = 앵커 날(창 시작)", (mk, ISO(W0), ISO(TL)))
f2 = build()
rep2, d2 = run_hist(NOW + 60)
chk(near(val(d2, D_MID), 10000) and near(val(d2, W0 + DAY), 10000) and near(val(d2, TL - DAY), 10000),
    "C2 ★늦게 받은 뒤 = 앵커 날~거래 전날 $10,000★(종전 = 표식이 거래 날만이라 $20,000 으로 남음)",
    (val(d2, W0 + DAY), val(d2, D_MID), val(d2, TL - DAY), rep2.get("dirty_from")))
chk(near(val(d2, TL + DAY), 20000) and near(val(d2, D_AFTER), 20000), "C2 거래 날 이후 = $20,000", (val(d2, TL + DAY), val(d2, D_AFTER)))
ser = {r.get("date"): r for r in f2.get("dailySeries") or []}
chk(near((ser.get(ISO(D_WIN)[5:]) or {}).get("val"), 20000) and near((ser.get(ISO(NOW)[5:]) or {}).get("val"), 20000),
    "C3 30일 창 안 날·오늘 = $20,000(10 ETH — 종전과 같음)", ((ser.get(ISO(D_WIN)[5:]) or {}).get("val"), (ser.get(ISO(NOW)[5:]) or {}).get("val")))

mk4 = common.hist_late_read(c.conn)
feed(c, h(1), esnap(h(1), TL, 1000, internal=[(RT, W, 5 * E18)]), repair="int_fill")
c._hist_late_scan()
build()
rep4, d4 = run_hist(NOW + 120)
chk(common.hist_late_read(c.conn) == mk4 and not rep4.get("dirty_from") and near(val(d4, D_MID), 10000),
    "C4 같은 레코드 재수신 = 원장 표식 무변 · 장기 곡선 다시 계산 없음 · 값 그대로", (rep4.get("dirty_from"), val(d4, D_MID)))
c.conn.close()

import glob
for p9 in glob.glob(os.path.join(common.STATE_DIR, "*")):
    if os.path.isfile(p9) and os.path.basename(p9) not in (os.path.basename(web.SPOT_PATH),):
        os.remove(p9)
HH.__init__()
c = core.Core(common.load_config())
c.conn.commit()
T60 = NOW - 60 * DAY
c._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": h(51), "wallets": [W], "ts": 1,
                                "snapshot": dict(esnap(h(51), T60, 900), tx=dict(esnap(h(51), T60, 900)["tx"], **{"from": "0x" + "b7" * 20, "to": W,
                                                                                                                 "value": str(10 * E18)}))}]), 0, 0)
feed(c, h(52), esnap(h(52), TL, 1000))
c._scope_ready = lambda s: True
c._recon_quiet = lambda *a: True
c._recon_bal = lambda chain, kind, mode, wallets: {"per_wallet": {W: {("native", None): 8 * E18}}} if chain == "eth" else None
c._last_recon = 0
c.recon_pass(set())
for k9 in ("_scope_ready", "_recon_quiet", "_recon_bal"):
    c.__dict__.pop(k9, None)
c._hist_late_scan()
open(os.path.join(common.STATE_DIR, "backfill_done"), "w").write(repr(time.time() - 3600))
D50 = NOW - 50 * DAY
build()
rep5, d5 = run_hist(NOW + 200)
chk(near(val(d5, D50), 16000) and near(val(d5, TL + DAY), 16000),
    "C5 (전제) 늦게 받기 전 = 60일 전 뒤 8 ETH($16,000 — 웹이 음수 앵커 −2 를 창 시작에 둠)", (val(d5, D50), val(d5, TL + DAY)))
feed(c, h(52), esnap(h(52), TL, 1000, internal=[(RT, W, E18)]), repair="int_fill")
c._hist_late_scan()
build()
rep6, d6 = run_hist(NOW + 260)
chk(near(val(d6, D50), 14000) and near(val(d6, TL - DAY), 14000),
    "C5 ★음수 앵커 보정 뒤 = 60일 전~거래 전날 7 ETH($14,000)★(종전 = 거래 날부터만 다시 계산 → $16,000 남음)",
    (val(d6, D50), val(d6, TL - DAY), rep6.get("dirty_from")))
chk(near(val(d6, TL + DAY), 16000), "C5 거래 날 뒤 = 8 ETH($16,000)", val(d6, TL + DAY))
c.conn.close()
T.finish()
