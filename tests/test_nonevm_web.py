#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
from _ingest import check, Reader  # noqa: E402
import _nonevm as N  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

import config  # noqa: E402
import core  # noqa: E402
import address_codec as ac  # noqa: E402

KST = timezone(timedelta(hours=9))
NOW = int(time.time())
DAY = 86400
A = N.OWN["tron"][0]
X = N.EXT["tron"]
TKA = ("token", N.TOK["tron"], "TKA", 6)
CFG_PATH = os.path.join(T.TMP, "config.json")
cfg = json.load(open(CFG_PATH))
cfg["wallets"] = [dict(w, chain=w.get("chain") or ("sol" if w.get("type") == "sol" else "eth")) for w in cfg["wallets"]]
cfg["chain_wallets"] = [{"chain": "tron", "address": ac.tron_display(A)}, {"chain": "sui", "address": N.OWN["sui"][0]}]
json.dump(cfg, open(CFG_PATH, "w"))
c = core.Core(config.load_config())
c.conn.commit()


def feed(rec, stream="tron"):
    c._drain_stream(stream, Reader([json.loads(json.dumps(rec))]), 0, 0)


T_IN, T_UNK, T_OUT = NOW - 40 * DAY, NOW - 30 * DAY, NOW - 20 * DAY
U_IN, U_UNK, U_OUT = "c1" * 32, "c2" * 32, "c3" * 32
feed(N.rec("tron", U_IN, T_IN, [(A, "native", 10_000_000)]))
c.conn.execute("UPDATE postings SET cost_usd='10.0', cost_krw='14000' WHERE source_id=? AND leg_kind='acq'", (U_IN,))
c.conn.commit()
feed(N.rec("tron", U_UNK, T_UNK, [(A, "native", -7_000_000), (A, TKA, 100_000_000)], fees=[(A, 2_000_000)], hint="unknown"))
feed(N.rec("tron", U_OUT, T_OUT, [(A, "native", -1_001_000)], fees=[(A, 1_000)], moves=[("native", A, X, 1_000_000)]))
feed(N.rec("sui", "Rb9", T_OUT, [(N.OWN["sui"][0], "native", 5)], fees=[(N.OWN["sui"][0], -5)]), stream="sui")
c.svc_price._leg_px = lambda aid, ts: 1.0
c.px.fx_at = lambda *a, **k: 1400.0
for u in (U_UNK, U_OUT):
    c.svc_price._price_tx("tron", u)
c.conn.commit()
check("전제: UNKNOWN 분류", c.conn.execute("SELECT event FROM tx_class WHERE txhash=?", (U_UNK,)).fetchone()["event"] == "UNKNOWN")
c.conn.close()

import acct_norm  # noqa: E402
import pricing  # noqa: E402
import web  # noqa: E402


def _no_price(url, *a, **k):
    raise OSError("시험: 시세 받기 없음")


pricing._gj = _no_price
acct_norm.FxBook.candle = lambda self, sym, ts: None
web.Spot.dex_pending = lambda self, c9, ca: False
web.Spot.ex_pending = lambda self, ex: False
b = web.StateBuilder()
web.BUILDER = b
try:
    st = b.build()
except Exception as e:   # noqa: BLE001
    import traceback
    traceback.print_exc()
    st = {"_exc": f"{type(e).__name__}: {e}"}
f = (st or {}).get("fields") or {} if isinstance(st, dict) else {}
check("V1 빌드 성공(새 체인 레그)", bool(f), st if isinstance(st, dict) and st.get("_exc") else "fields 없음")
cards = f.get("_positionsAll") or f.get("positions") or []
trx = [p for p in cards if p.get("sym") == "TRX"]
tka = [p for p in cards if p.get("sym") == "TKA"]
check("V2 TRX 보유 1.999(10 − 보냄 1 − 교환 5 − 수수료 2.001)", any(abs(float(p.get("held") or 0) - 1.999) < 1e-9 for p in trx),
      [(p.get("sym"), p.get("held")) for p in trx])
check("V3 TKA 원가 = 보낸 TRX 소진 원가 $5(가격 없는 교환 — 원가 넘기기)", any(abs(float(p.get("cost") or 0) - 5.0) < 0.01 for p in tka),
      [(p.get("sym"), p.get("cost"), p.get("unknownQty")) for p in tka])
rbd = {k: float(v) for k, v in (f.get("realizedByDate") or {}).items()}
d_unk = datetime.fromtimestamp(T_UNK, KST).strftime("%Y-%m-%d")
check("V3 교환 날 실현 = 수수료만(−$2 · 손익 확정 없음)", abs(rbd.get(d_unk, 0.0) + 2.0) < 0.005, rbd)
pend = f.get("pendings") or []
unk = [p for p in pend if p.get("kind") == "분류 보류" and str(p.get("tx") or "") == U_UNK]
check("V4 '분류 보류' 검토 1건", len(unk) == 1, [p for p in pend if p.get("kind") == "분류 보류"])
T.finish()
