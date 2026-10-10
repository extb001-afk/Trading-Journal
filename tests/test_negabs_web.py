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
try:
    import discopen
except ImportError as e:
    chk(False, "발견 시점 기초 잔고 모듈(src/discopen.py) 있음", repr(e))
    T.finish()
KO = getattr(web, "DISC_OPEN_KO", "발견 시점 기초 잔고 — 원가 미상, 발견 시각 시세로 추정")
for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker"):
    if hasattr(web.StateBuilder, _m):
        setattr(web.StateBuilder, _m, lambda self: None)
netpace.wait = lambda url, now=None, sleep=None: None
E18 = 10 ** 18
DAY = 86400
NOW = int(time.time())
X = "0x" + "b7" * 20
TKN = "0x" + "e1" * 20
T0 = NOW - 20 * DAY
TA = NOW - 6 * DAY


def h(n):
    return "0x" + ("%064x" % n)


def snap(hx, ts, blk, frm, to, value=0, toks=(), fee=0, data="0xa9059cbb"):
    return {"tx": {"hash": hx, "from": frm, "to": to, "value": str(value), "fee": {"value": str(fee)}, "status": "ok", "raw_input": data,
                   "timestamp": ts, "block_number": blk, "block_hash": "0x" + "d" * 64},
            "token_transfers": [{"from": f, "to": t, "token": {"address": ca, "symbol": sym, "decimals": 18, "type": "ERC-20"},
                                 "total": {"value": str(v)}} for f, t, ca, sym, v in toks], "internal": []}


def feed(c, hx, s):
    c._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": hx, "wallets": [W], "snapshot": s, "ts": 1}]), 0, 0)


os.environ["TJ_NEGABS"] = "0"
c = core.Core(common.load_config())
feed(c, h(1), snap(h(1), T0, 1500, X, W, value=2 * E18, data="0x"))
feed(c, h(2), snap(h(2), TA, 2000, W, TKN, toks=[(W, X, TKN, "TKN", 600 * E18)], fee=10 ** 15))
c.conn.commit()

ISO = acct_norm.iso_day


def fake_lookup(spec, iso, now=None, w=0.0, ask=True, old=False):
    if "e1e1" in str(spec).lower() or str(spec).upper().endswith("TKN"):
        return (2.0 if iso >= ISO(TA) else 1.0), "ok"
    if "ETH" in str(spec).upper():
        return 2000.0, "ok"
    return None, "pending"


fake_lookup._tj_test_mock = True
histcurve.DAYCLOSE.lookup = fake_lookup
k9 = f"eth:{TKN}"
json.dump({"usd": {"ETH": 2000.0}, "usd_ts": {"ETH": NOW}, "rate": 1400.0, "updated": NOW, "dex_usd": {k9: 2.0}, "dex_ts": {k9: NOW},
           "dex_res": {k9: 1e6}, "dex_res_ts": {k9: NOW}, "fx_basis": 1400.0, "ex_usd": {}, "ex_ts": {}}, open(web.SPOT_PATH, "w"))
web.pricing.PxCache.candle_usd = lambda self, sym, ms: None
web.pricing._gj = lambda url, timeout=10.0: None


def build():
    try:
        os.remove(os.path.join(common.STATE_DIR, "daily_cache.json"))
    except FileNotFoundError:
        pass
    b = web.StateBuilder()
    b.skip_gen_check = True
    conn = dbm.open_db(common.DB_PATH, readonly=True)
    try:
        return b._build(conn)["fields"]
    finally:
        conn.close()


fa = build()
aid = c.conn.execute("SELECT asset_id FROM assets WHERE address=?", (TKN,)).fetchone()[0]
sid = discopen.write_anchor(c, "eth", W, aid, TKN, 1000 * E18, 1999, TA - 12, TA - 1, 1000 * E18, "neg_tx", {"_tx": h(2)})
c.conn.commit()
fb = build()
ev = [e for e in (fb.get("extraEvents") or []) + (fb.get("extraEventsHidden") or []) if KO in str(e.get("d") or "")]
old = [e for e in (fb.get("extraEvents") or []) + (fb.get("extraEventsHidden") or []) if "백필 창 이전" in str(e.get("d") or "") and e.get("sym") == "TKN"]
chk(sid and len(ev) == 1 and not old, "D1 기록 문구 = 발견 시점 기초 잔고(종전 '백필 창 이전 보유분' 아님)", (sid, ev[:1], old[:1]))
cs = [x for x in fb.get("coins") or [] if x.get("sym") == "TKN"]
p0 = cs[0] if cs else {}
chk(p0 and abs(float(p0.get("qty") or 0) - 400) < 1e-9 and abs(float(p0.get("avg") or 0) - 2.0) < 1e-9 and abs(float(p0.get("fsc") or 0) - 800) < 1e-6,
    "D2 보유 400 · 평단 = 발견 날 시세 $2(창 시작 $1·오늘 아님) · 최초 인식 시가 원가 $800", {k: p0.get(k) for k in ("qty", "avg", "fsc", "kqty")})
da = {d.get("date") or d.get("d") or d.get("k"): d for d in fa.get("dailySeries") or []}
db = {d.get("date") or d.get("d") or d.get("k"): d for d in fb.get("dailySeries") or []}
key_a = sorted(k for k in da if k)
before = [k for k in key_a if str(k) < ISO(TA)[(len(ISO(TA)) - len(str(k))):] or (len(str(k)) == len(ISO(TA)) and str(k) < ISO(TA))]
diff_b = {k: (da[k].get("val"), (db.get(k) or {}).get("val")) for k in before if da[k].get("val") != (db.get(k) or {}).get("val")}
chk(len(before) >= 3 and not diff_b, f"D3 발견 날 전 일별 값 {len(before)}일 = 앵커 넣기 전과 같음(지난날 무변)", (diff_b, key_a[:3], ISO(TA)))
last = key_a[-1] if key_a else None
dv = ((db.get(last) or {}).get("val") or 0) - ((da.get(last) or {}).get("val") or 0) if last else None
chk(dv is not None and abs(dv - 800) < 1.0, "D3 오늘 값 = +$800(보유 400 × $2 — 음수는 0 으로 가려졌던 몫)", (last, dv))
TD = TA + 2 * DAY
discopen.write_anchor(c, "eth", W, aid, TKN, -100 * E18, 2100, TD - 12, TD, 300 * E18, "neg_tx")
c.conn.commit()
fc = build()
dc = {d.get("date") or d.get("d") or d.get("k"): d for d in fc.get("dailySeries") or []}
before_d = [k for k in key_a if str(k) < ISO(TD)[len(ISO(TD)) - len(str(k)):]]
diff_c = {k: ((db.get(k) or {}).get("val"), (dc.get(k) or {}).get("val")) for k in before_d if (db.get(k) or {}).get("val") != (dc.get(k) or {}).get("val")}
chk(len(before_d) >= 3 and not diff_c, f"D4 음수 발견 앵커 = 제자리(발견 날 전 {len(before_d)}일 값 무변 — 종전 창 시작으로 당겨 지난날 총자산 변함)", diff_c)
c.conn.close()
T.finish()
