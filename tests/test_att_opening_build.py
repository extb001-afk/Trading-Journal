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
KST = timezone(timedelta(hours=9))


def h(n):
    return "0x" + ("%064x" % n)


def snap(hx, ts, blk, frm, to, value=0, toks=(), fee=0, data="0xa9059cbb"):
    return {"tx": {"hash": hx, "from": frm, "to": to, "value": str(value), "fee": {"value": str(fee)}, "status": "ok", "raw_input": data,
                   "timestamp": ts, "block_number": blk, "block_hash": "0x" + "d" * 64},
            "token_transfers": [{"from": f, "to": t, "token": {"address": ca, "symbol": sym, "decimals": 18, "type": "ERC-20"},
                                 "total": {"value": str(v)}} for f, t, ca, sym, v in toks], "internal": []}


def feed(c, hx, s):
    c._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": hx, "wallets": [W], "snapshot": s, "ts": 1}]), 0, 0)


open(os.path.join(common.STATE_DIR, "backfill_done"), "w").write("1")
os.environ["TJ_NEGABS"] = "0"
c = core.Core(common.load_config())
feed(c, h(1), snap(h(1), T0, 1500, X, W, value=2 * E18, data="0x"))
feed(c, h(2), snap(h(2), TA, 2000, W, TKN, toks=[(W, X, TKN, "TKN", 600 * E18)], fee=10 ** 15))
TKS, TB = "0x" + "e2" * 20, NOW - 3 * DAY
feed(c, h(3), snap(h(3), TB, 2500, W, TKS, toks=[(W, X, TKS, "T\u041aN", 300 * E18)], fee=10 ** 15))
c.conn.commit()

ISO = acct_norm.iso_day


def fake_lookup(spec, iso, now=None, w=0.0, ask=True, old=False):
    if "e2e2" in str(spec).lower():
        return 3.0, "ok"
    if "e1e1" in str(spec).lower() or str(spec).upper().endswith("TKN"):
        return (2.0 if iso >= ISO(TA) else 1.0), "ok"
    if "ETH" in str(spec).upper():
        return 2000.0, "ok"
    return None, "pending"


fake_lookup._tj_test_mock = True
histcurve.DAYCLOSE.lookup = fake_lookup
k9, k9s = f"eth:{TKN}", f"eth:{TKS}"
json.dump({"usd": {"ETH": 2000.0}, "usd_ts": {"ETH": NOW}, "rate": 1400.0, "updated": NOW, "dex_usd": {k9: 2.0, k9s: 3.0}, "dex_ts": {k9: NOW, k9s: NOW},
           "dex_res": {k9: 1e6, k9s: 1e6}, "dex_res_ts": {k9: NOW, k9s: NOW}, "fx_basis": 1400.0, "ex_usd": {}, "ex_ts": {}}, open(web.SPOT_PATH, "w"))
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


aid = c.conn.execute("SELECT asset_id FROM assets WHERE address=?", (TKN,)).fetchone()[0]
sid = discopen.write_anchor(c, "eth", W, aid, TKN, 1000 * E18, 1999, TA - 12, TA - 1, 1000 * E18, "neg_tx", {"_tx": h(2)})
aids = c.conn.execute("SELECT asset_id FROM assets WHERE address=?", (TKS,)).fetchone()[0]
sids = discopen.write_anchor(c, "eth", W, aids, TKS, 500 * E18, 2499, TB - 12, TB - 1, 500 * E18, "neg_tx", {"_tx": h(3)})
c.conn.commit()
fb = build()
ser = fb.get("dailySeries") or []
dk = datetime.fromtimestamp(TA, KST).strftime("%m-%d")
row = next((r for r in ser if r.get("date") == dk), {})
prev = ser[ser.index(row) - 1] if row in ser and ser.index(row) > 0 else {}
a = row.get("att") or {}
dv = float(row.get("val") or 0) - float(prev.get("val") or 0)
chk(sid and abs(dv + 200) < 1.0 and abs(float(prev.get("val") or 0) - 1000) < 1.0,
    "② 지난날(발견 전날) 곡선 = TKN 1,000 × 그날 $1 = $1,000(원래 있던 보유) · 발견 날 −$200(→ 400 × $2)", (sid, dk, dv, prev.get("val")))
chk(not a.get("op") and abs(float(a.get("ev") or 0) - 1000) < 0.5 and abs(float(row.get("flow") or 0) + 1200) < 0.5,
    "② 발견 날 분해 = 시세 +$1,000 · 입출금 −$1,200 · 기초 잔고 정정 줄 없음(앞 날부터 보유 — 같은 시각 기준)", {k: a.get(k) for k in ("op", "ev", "rest")} | {"flow": row.get("flow")})
chk(abs(float(a.get("rest") if a.get("rest") is not None else 9e9)) < 1.0 and not a.get("unp"), "나머지 ≈ 0 · '가격 한쪽 없는 코인' 아님",
    {k: a.get(k) for k in ("op", "rest", "unp", "xr")})
early = [r for r in ser if r.get("date") and r.get("date") < dk and r.get("date") >= ser[0].get("date")]
chk(len(early) >= 3 and all(abs(float(r.get("val") or 0) - 1000) < 1.0 for r in early[:-1]), "② 창 안 지난날 전부 = $1,000(발견 날 전 — 계단 없음)",
    [(r.get("date"), r.get("val")) for r in early[:5]])
dkb = datetime.fromtimestamp(TB - DAY, KST).strftime("%m-%d")
rb = next((r for r in ser if r.get("date") == dkb), {})
chk(sids and abs(float(rb.get("val") or 0) - 800) < 1.0,
    "② 유사 글자 이름 토큰의 발견 시점 기초 잔고(500 × $3) = 지난날로 안 당김(그 전날 = TKN 400 × $2 = $800 만 · 당겼으면 +$1,500)", (sids, dkb, rb.get("val")))
gk = lambda a9: (lambda r9: r9[0] if r9[0] is not None else -a9)(c.conn.execute("SELECT group_id FROM assets WHERE asset_id=?", (a9,)).fetchone())
bk9 = getattr(BB, "_disc_back", None)
chk(isinstance(bk9, set) and gk(aid) in bk9 and gk(aids) not in bk9,
    "② 리플레이가 창 시작으로 당긴 그룹 = TKN 만(유사 글자 이름 토큰은 제자리 — 표시층 사칭 판정과 같은 규칙)", (bk9, gk(aid), gk(aids)))
xqb0 = (BB.daily_px or {}).get("_xqb")
c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('recon_done_upbit', ?)", (str(NOW - 600),))
c.conn.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('upbit', 'order', 'u-1', 1, '{}', ?)", (NOW - 900,))
c.conn.commit()
build()
chk(isinstance(xqb0, dict) and xqb0.get("xq") == "" and getattr(BB, "_xq9", None) == ("upbit", ""),
    "fixc1010 빌드 배선: 처음 기준 = 거래소 없음('') · 그 뒤 업비트 대사 = 지금 'upbit' · 기준 그대로('' — 새 거래소로 판정)", (xqb0, getattr(BB, "_xq9", None)))
c.conn.close()
T.finish()
