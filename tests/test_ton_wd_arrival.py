#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
from _ingest import check  # noqa: E402

import base64  # noqa: E402
import glob  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import time  # noqa: E402
from decimal import Decimal  # noqa: E402

import config, paths, statefile  # noqa: E402
import core  # noqa: E402
import db as dbm  # noqa: E402
import chain_registry as reg  # noqa: E402
import chain_state as cs  # noqa: E402
import chain_watch as cw  # noqa: E402
import address_codec as ac  # noqa: E402
from inbox import SegmentWriter, SegmentReader  # noqa: E402
import ton_watch as tw  # noqa: E402
import _ton_fake as F  # noqa: E402

T.patch_moved("dm", lambda *a, **k: None)

DAY = 86400
NOW = int(time.time())
TON = 10 ** 9
X = F.K("99")
CFG_PATH = os.path.join(T.TMP, "config.json")
INB = os.path.join(paths.INBOX_DIR, "ton")
reg.FORCE_AVAILABLE.add("ton")

ch = F.Chain()
srv = F.Server(ch).start()
A1, A2 = F.K("51"), F.K("52")
ta1 = ch.tx(A1, NOW - 600, in_msg={"src": X, "val": 100 * TON}, tf=0)
ta2 = ch.tx(A2, NOW - 3 * DAY, in_msg={"src": X, "val": 100 * TON}, tf=0)


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(t))


def set_wallet(k):
    cfg = json.load(open(CFG_PATH))
    cfg["chain_wallets"] = [{"chain": "ton", "address": ac.ton_friendly(k)}]
    cfg["wallets"] = []
    json.dump(cfg, open(CFG_PATH, "w"))
    return config.load_config()


def mk_core():
    c9 = core.Core(config.load_config())
    c9.svc_exf._quote_usd = lambda q, ts: Decimal(1) if str(q).upper() in ("USDT", "USDC") else None
    c9.px.fx_at = lambda ms: 1400.0
    return c9


def drain(c9):
    rd = SegmentReader(INB)
    for _i in range(50):
        row = c9.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream='ton'").fetchone()
        seg, off = (row["seg"], row["off"]) if row else (1, 0)
        c9._drain_stream("ton", rd, seg, off)
        row2 = c9.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream='ton'").fetchone()
        if row2 and row and (row2["seg"], row2["off"]) == (seg, off):
            break
    c9.conn.commit()


def fresh():
    for p in glob.glob(paths.DB_PATH + "*"):
        os.remove(p)
    shutil.rmtree(INB, ignore_errors=True)
    os.makedirs(INB, exist_ok=True)


def scenario(owner, txid_of, wd_late=False, restart=False, net="TON"):
    fresh()
    set_wallet(owner)
    c = mk_core()
    t0 = (NOW - 600 if owner == A1 else NOW - 3 * DAY) - 7200
    c.svc_exf._consume_ex({"exchange": "binance", "deposits": [{"uuid": "binance:d1", "currency": "USDT", "amount": "1000", "txid": "0x" + "d1" * 32,
                                                         "state": "ACCEPTED", "created_at": iso(t0), "done_at": iso(t0)}]})
    c.svc_exf._consume_exf_fills({"exchange": "binance", "fills": [{"id": "binance:TONUSDT:1", "ts": (t0 + 600) * 1000, "base": "TON", "quote": "USDT",
                                                             "side": "buy", "price": "10", "qty": "100", "fee": "0", "fee_ccy": "TON"}]})
    c.conn.commit()
    st = cs.ChainState("ton", os.path.join(T.TMP, "sd_" + str(time.time_ns())))
    ad = tw.TonAdapter(config.load_config(), client=srv.client(), state=st)
    col = cw.Collector(ad, SegmentWriter(INB), st, {owner}, page_budget={"latest": 10, "history": 20},
                       detail_budget={"latest": 200, "history": 500})
    col.cycle()
    recs = [json.loads(ln) for f in sorted(os.listdir(INB)) if f.endswith(".jsonl") for ln in open(os.path.join(INB, f)) if ln.strip()]
    rec = [r for r in recs if r["owners"] == [owner]][-1]
    arr_ts = int(rec["ts"])
    wts = arr_ts + 300 if wd_late else arr_ts - 120
    w = {"uuid": "binance:w1", "currency": "TON", "amount": "100", "fee": "0", "txid": txid_of(rec["txhash"]), "state": "DONE",
         "address": ac.ton_friendly(owner), "created_at": iso(wts), "done_at": iso(wts + 30)}
    if net:
        w["network"] = net
    c.svc_exf._consume_ex({"exchange": "binance", "withdraws": [w]})
    c.conn.commit()
    drain(c)
    if restart:
        c.conn.close()
        c = mk_core()
        drain(c)
    c.conn.close()
    return rec


import netpace  # noqa: E402
import web  # noqa: E402

for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker"):
    if hasattr(web.StateBuilder, _m):
        setattr(web.StateBuilder, _m, lambda self: None)
netpace.wait = lambda url, now=None, sleep=None: None
web.pricing._gj = lambda url, *a, **k: (_ for _ in ()).throw(OSError("시험: 시세 받기 없음"))
web.pricing.PxCache.fx_at = lambda self, ms: 1400.0
_px = {"USDT": 1.0, "TON": 15.0}
web.pricing.PxCache.candle_usd = lambda self, sym, ms: _px.get(str(sym).upper())


def view(first_seen=False):
    spot = {"usd": _px, "usd_ts": {k: NOW for k in _px}, "rate": 1400.0, "updated": NOW, "dex_usd": {}, "dex_ts": {}, "dex_res": {}, "dex_res_ts": {},
            "fx_basis": 1400.0, "ex_usd": {"binance:TON": 15.0, "binance:USDT": 1.0}, "ex_ts": {"binance:TON": NOW, "binance:USDT": NOW}}
    json.dump(spot, open(paths.state("spot.json"), "w"))
    statefile.atomic_write_json(paths.state("ui_prefs.json"), {"plans": {}, "ignored": [], "first_seen_px": bool(first_seen)})
    b = web.StateBuilder()
    b.skip_gen_check = True
    conn = dbm.open_db(paths.DB_PATH, readonly=True)
    try:
        out = b._build(conn)
    finally:
        conn.close()
    f = out["fields"]
    coins = [r for r in (f.get("coins") or []) if str(r.get("sym") or "").upper() == "TON"]
    pos = [p for p in (f.get("positions") or []) if str(p.get("sym") or "").upper() == "TON" and float(p.get("held") or 0) > 0]
    sm = lambda rows, k: round(sum(float(r.get(k) or 0) for r in rows), 6)
    return {"qty": sm(coins, "qty"), "cost": round(sm(pos, "cost"), 2), "unk": sm(pos, "unknownQty"), "unreal": round(sm(pos, "unreal"), 2),
            "total": round(web._hero_summary(out)["total"], 2)}


GOOD = {"qty": 100.0, "cost": 1000.0, "unk": 0.0, "unreal": 500.0, "total": 1500.0}


def ok(v):
    return all(abs(v[k] - GOOD[k]) < 1e-6 for k in GOOD)


FORMS = [("hex", lambda h: h), ("0x hex", lambda h: "0x" + h), ("대문자 hex", lambda h: h.upper()),
         ("base64", lambda h: base64.b64encode(bytes.fromhex(h)).decode()),
         ("base64url(패딩 없음)", lambda h: base64.urlsafe_b64encode(bytes.fromhex(h)).decode().rstrip("="))]
for nm, fn in FORMS:
    scenario(A1, fn)
    v = view()
    check(f"A {nm} 출금 txid → TON 100 · 총자산 $1,500 · 원가 $1,000 · 원가 미상 0 · 미실현 $500", ok(v), v)

scenario(A1, lambda h: h, net=None)
v = view()
check("A 네트워크 칸 없는 출금(hex)도 내 TON 원장 hash 와 같으면 연결", ok(v), v)

scenario(A1, lambda h: h, restart=True)
v = view()
check("B core 재시작 뒤 같은 값", ok(v), v)
scenario(A2, lambda h: base64.b64encode(bytes.fromhex(h)).decode())
v = view()
check("B 전송 중 창이 지난 옛 출금 도착도 원가 $1,000 승계(원가 미상 0)", ok(v), v)
scenario(A1, lambda h: h)
v = view(first_seen=True)
check("B 최초 인식 시가 켬 = 원가 $1,000(새 시가 $1,500 아님)", ok(v), v)
scenario(A1, lambda h: "0x" + h, wd_late=True)
v = view()
check("C 출금 기록이 도착보다 늦어도 같은 값", ok(v), v)

h0 = "ab" * 32
uid0 = tw.tx_uid(F.K("51"), 123, h0)
tm = {h0: uid0}
b64 = base64.b64encode(bytes.fromhex(h0)).decode()
check("D TON 출금 hex·0x·base64·base64url → 내 TON tx_uid", all(web._wd_txk(t, "TON", tm) == uid0 for t in
      (h0, "0x" + h0, h0.upper(), b64, b64.replace("+", "-").replace("/", "_").rstrip("="))) and web._wd_txk(h0, "TON-TON", tm) == uid0,
      [web._wd_txk(t, "TON", tm) for t in (h0, "0x" + h0, b64)])
sol = "5" + "Kj" * 43
check("D 다른 체인 명시(ETH·TRX·BSC·SOL) = 종전 _txk 그대로(같은 hash 문자열이어도 합병 없음)",
      all(web._wd_txk(t, n, tm) == web._txk(t) for t, n in (("0x" + h0, "ETH"), (h0, "TRX"), ("0x" + h0.upper(), "BSC"), (sol, "SOL"),
                                                             (h0, "BTC"), (b64, "ARBITRUM"))),
      [web._wd_txk("0x" + h0, "ETH", tm), web._wd_txk(h0, "TRX", tm)])
check("D 내 TON 원장에 없는 hash · TON 색인 없음 = 종전 _txk",
      web._wd_txk("0x" + "cd" * 32, "TON", tm) == "0x" + "cd" * 32 and web._wd_txk("CD" * 32, "", tm) == "cd" * 32
      and web._wd_txk(h0, "TON", {}) == h0 and web._wd_txk(sol, "", tm) == sol and web._wd_txk("", "TON", tm) == "")
T.finish()
