#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import common

B = "0x" + "b4" * 20
AUC, TKN = "0x" + "a6" * 20, "0x" + "d6" * 20
FIN = "0x" + "f6" * 20
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
json.dump({"chains": {}, "wallets": [{"chain": "eth", "address": B, "label": "B"}], "backfill_months": 5},
          open(os.path.join(os.environ["TJ_BASE"], "config.json"), "w"))
import acct_norm
import db as dbm
import histcurve
import netpace
import sale_match
import web

chk = T.chk
for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker"):
    if hasattr(web.StateBuilder, _m):
        setattr(web.StateBuilder, _m, lambda self: None)
netpace.wait = lambda url, now=None, sleep=None: None
KST = timezone(timedelta(hours=9))
NOW = int(time.time())
DAY = 86400
D0 = int((datetime.fromtimestamp(NOW, KST).replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=60)).timestamp())
E18 = 10 ** 18
ISO = acct_norm.iso_day


def d(n, h=0):
    return D0 + n * DAY + h * 3600


def h64(n):
    return "0x%064x" % n


PX = {"ETH": [(0, 1000.0)], "USDT": [(0, 1.0)], "USDC": [(0, 1.0)]}
NO_PX_BEFORE = [0]


def px_at(sym, ts):
    s = str(sym or "").upper()
    if s not in PX:
        return None
    if s == "ETH" and ts < NO_PX_BEFORE[0]:
        return None
    v = None
    for t0, p0 in PX[s]:
        if ts >= t0:
            v = p0
    return v


def _candle(self, sym, ms):
    return px_at(sym, int(ms) // 1000)


def fake_lookup(spec, iso, now=None, w=0.0, ask=True, old=False):
    sp = str(spec or "").upper()
    if "ETH" not in sp:
        return None, "pending"
    t9 = int(datetime.strptime(iso, "%Y-%m-%d").replace(hour=23, minute=59, tzinfo=KST).timestamp())
    v = px_at("ETH", t9)
    return (v, "ok") if v else (None, "pending")


fake_lookup._tj_test_mock = True
web.pricing.PxCache.candle_usd = _candle
web.pricing._gj = lambda url, timeout=10.0: None
histcurve.DAYCLOSE.lookup = fake_lookup
spot = {"ETH": 2000.0, "USDT": 1.0, "USDC": 1.0}
json.dump({"usd": spot, "usd_ts": {k: NOW for k in spot}, "rate": 1300.0, "updated": NOW, "dex_usd": {}, "dex_ts": {}, "dex_res": {}, "dex_res_ts": {},
           "fx_basis": 1300.0, "ex_usd": {}, "ex_ts": {}}, open(web.SPOT_PATH, "w"))
FX_CORE = os.path.join(common.STATE_DIR, "px_cache_core.json")


def set_fx(pts):
    if not pts:
        if os.path.exists(FX_CORE):
            os.remove(FX_CORE)
        return
    json.dump({"fx": {str(int(t) * 1000 // 60000 * 60000): r for t, r in pts}, "candle": {}}, open(FX_CORE, "w"))


class L:
    def __init__(self):
        p = common.DB_PATH
        for sfx in ("", "-wal", "-shm"):
            if os.path.exists(p + sfx):
                os.remove(p + sfx)
        self.c = dbm.open_db(p)
        self.A = {}
        for key, kind, addr, sym, dec in (("eth", "native", None, "ETH", 18), ("usdt", "token", USDT, "USDT", 6),
                                          ("usdc", "token", USDC, "USDC", 6), ("tkn", "token", TKN, "TKN", 18),
                                          ("fin", "token", FIN, "FIN", 18)):
            self.c.execute("INSERT INTO asset_groups (name) VALUES (?)", (sym,))
            g9 = self.c.execute("SELECT group_id FROM asset_groups WHERE name=?", (sym,)).fetchone()[0]
            self.c.execute("INSERT INTO assets (kind, chain, address, symbol, decimals, confirmed, group_id) VALUES (?,?,?,?,?,1,?)",
                           (kind, "eth", addr, sym, dec, g9))
            self.A[key] = (self.c.execute("SELECT last_insert_rowid()").fetchone()[0], dec)
        self.n = 0

    def post(self, sid, seq, t, a, loc, qty, usd, lk, ev, krw=None):
        aid, dec = self.A[a]
        self.c.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd,"
                       " cost_krw, leg_kind, event, classifier_ver) VALUES ('chain_tx','eth',?,?,?,?,?,?,?,?,?,?,3)",
                       (sid, seq, t, aid, loc, str(int(Decimal(str(qty)) * (Decimal(10) ** dec))), None if usd is None else str(usd),
                        None if krw is None else str(krw), lk, ev))

    def raw(self, tx, t, tts=(), internal=(), frm=B, to=AUC):
        if self.c.execute("SELECT 1 FROM raw_txs WHERE chain='eth' AND txhash=?", (tx,)).fetchone():
            return
        snap = {"tx": {"hash": tx, "from": {"hash": frm}, "to": {"hash": to}, "value": "0", "status": "ok"},
                "token_transfers": list(tts), "internal": list(internal)}
        self.c.execute("INSERT INTO raw_txs (chain, txhash, block, blockhash, ts, snapshot, wallets, ingested_at) VALUES ('eth',?,1,'0x',?,?,?,?)",
                       (tx, t, json.dumps(snap), json.dumps([B]), t))

    def tx(self):
        self.n += 1
        return h64(0x7000 + self.n)

    def fund(self, t, q, a="usdt"):
        tx = self.tx()
        self.post(tx, 0, t, a, f"wallet:eth:{B}", q, None, "acq", "TRANSFER_IN")
        self.raw(tx, t, frm="0x" + "ee" * 20, to=B)

    def eth_in_nocost(self, t, q):
        tx = self.tx()
        self.post(tx, 0, t, "eth", f"wallet:eth:{B}", q, None, "acq", "TRANSFER_IN")
        self.raw(tx, t, frm="0x" + "ef" * 20, to=B, internal=[{"from": "0x" + "ef" * 20, "to": B, "value": str(int(Decimal(str(q)) * E18))}])

    def swap(self, t, a_out, q_out, a_in, q_in, usd, krw=None):
        tx = self.tx()
        self.post(tx, 0, t, a_out, f"wallet:eth:{B}", -Decimal(str(q_out)), usd, "disp", "SWAP")
        self.post(tx, 1, t, a_in, f"wallet:eth:{B}", q_in, usd, "acq", "SWAP", krw=krw)
        self.raw(tx, t)
        return tx

    def bid(self, tx, t, q, asset="eth", seq0=0):
        self.post(tx, seq0, t, asset, f"wallet:eth:{B}", -Decimal(str(q)), None, "move_out", "TRANSFER_OUT")
        self.post(tx, seq0 + 1, t, asset, f"out:eth:{AUC}", q, None, "move_in", "TRANSFER_OUT")
        tts = [] if asset == "eth" else [{"from": {"hash": B}, "to": {"hash": AUC}, "token": {"address_hash": USDC, "symbol": "USDC", "decimals": "6"},
                                          "total": {"value": str(int(Decimal(str(q)) * 10 ** 6)), "decimals": "6"}}]
        self.raw(tx, t, tts=tts, frm=B, to=AUC)

    def refund(self, tx, t, q, asset="eth"):
        self.post(tx, 0, t, asset, f"wallet:eth:{B}", q, None, "acq", "PROGRAM_IN")
        if asset == "eth":
            self.raw(tx, t, internal=[{"from": AUC, "to": B, "value": str(int(Decimal(str(q)) * E18))}], frm=B, to=AUC)
        else:
            self.raw(tx, t, tts=[{"from": {"hash": AUC}, "to": {"hash": B}, "token": {"address_hash": USDC, "symbol": "USDC", "decimals": "6"},
                                  "total": {"value": str(int(Decimal(str(q)) * 10 ** 6)), "decimals": "6"}}], frm=B, to=AUC)

    def claim(self, tx, t, q):
        self.post(tx, 0, t, "tkn", f"wallet:eth:{B}", q, None, "acq", "PROGRAM_IN")
        self.raw(tx, t, tts=[{"from": {"hash": AUC}, "to": {"hash": B}, "token": {"address_hash": TKN, "symbol": "TKN", "decimals": "18"},
                              "total": {"value": str(int(Decimal(str(q)) * E18)), "decimals": "18"}}], frm=B, to=AUC)

    def done(self):
        self.c.commit()
        self.c.close()


def cache(bids, cur=None, redeem=None):
    cur = cur or {"addr": "", "sym": "ETH", "dec": 18}
    un = 10 ** int(cur["dec"])
    bl = [{"auction": AUC, "id": i, "amount": str(int(Decimal(str(a)) * un)), "bid_tx": btx, "bid_ts": bts, "filled": str(int(Decimal(str(f)) * E18)),
           "refunded": str(int(Decimal(str(r)) * un)), "exit_tx": etx, "exit_ts": ets, "claim_tx": CLAIM, "claim_ts": d(3)}
          for i, a, btx, bts, r, etx, ets, f in bids]
    json.dump({"owners": {f"eth:{B}": {"t": NOW, "chain": "eth", "owner": B, "bids": bl,
                                         "auctions": {AUC: {"ok": True, "why": "seed", "currency": cur, "token": {"addr": TKN, "sym": "TKN", "dec": 18},
                                                            **({"redeem": redeem} if redeem else {})}}}}},
              open(web.SALE_PATH, "w"))


BLD = [None]


def build(prefs=None):
    common.atomic_write_json(web.PREFS_PATH, dict({"plans": {}, "ignored": []}, **(prefs or {})))
    b = web.StateBuilder()
    b.skip_gen_check = True
    conn = dbm.open_db(common.DB_PATH, readonly=True)
    try:
        f = b._build(conn)["fields"]
    finally:
        conn.close()
    BLD[0] = b
    return f, (b._day_idx or {}).get("tax") or []


def rz_sum(f):
    return round(sum(float(v) for v in (f.get("realizedByDate") or {}).values()), 2)


def rz(f, day):
    return round(float((f.get("realizedByDate") or {}).get(ISO(day), 0)), 2)


def unv(f):
    return sorted({str(p.get("sym") or "") for p in f.get("pendings") or [] if str(p.get("kind", "")).startswith("원가미상 매도")})


def unreal(f):
    return round(sum(float(p.get("unreal") or 0) for p in f.get("positions") or []), 2)


def rows_of(rows, sym):
    return sorted((round(float(r.get("_qty", r.get("qty")) or 0), 6), round(float(r.get("_acq", r.get("acq")) or 0), 2),
                   round(float(r.get("_disp", r.get("disp")) or 0), 2)) for r in rows if r.get("sym") == sym)


def tok_cost(f):
    s = (f.get("saleLinks") or [{}])[0]
    return s.get("costUsd")


def reset():
    PX["ETH"] = [(0, 1000.0)]
    NO_PX_BEFORE[0] = 0
    set_fx([])
    pin9 = getattr(web, "FS_PIN_PATH", os.path.join(common.STATE_DIR, "first_seen_px.json"))
    if os.path.exists(pin9):
        os.remove(pin9)


BID, EXIT, CLAIM = h64(0x101), h64(0x201), h64(0x900)


def roundtrip(bid_px, sell9, sell_t, used=1, bid_q=10, krw=None):
    reset()
    PX["ETH"] = [(0, 1000.0), (d(1) - 3600, float(bid_px)), (d(9), 3000.0)]
    lg = L()
    lg.fund(d(-1), 30000)
    lg.swap(d(0), "usdt", 10000, "eth", 10, 10000, krw=krw)
    lg.bid(BID, d(1), bid_q)
    if bid_q - used > 0:
        lg.refund(EXIT, d(2), bid_q - used)
        lg.swap(d(10), "eth", bid_q - used, "usdt", sell9, sell9)
    lg.claim(CLAIM, d(3), 1000)
    lg.swap(d(11), "tkn", 1000, "usdt", sell_t, sell_t)
    lg.done()
    cache([(1, bid_q, BID, d(1), bid_q - used, EXIT, d(2), 1000)])
    return (sell9 if bid_q - used > 0 else 0) + sell_t - 10000


cash = roundtrip(2000, 27000, 2000)
f, rows = build()
chk(cash == 19000 and rz_sum(f) == 19000.0, "P1 완전 청산 실현 합 $19,000 = 현금 증가(종전 $18,000 — 사용분 1 ETH 처분 손익 누락)", [cash, rz_sum(f)])
chk(rows_of(rows, "ETH") == [(1.0, 1000.0, 2000.0), (9.0, 9000.0, 27000.0)],
    "P1 ETH 명세 = 사용분 1 ETH(취득 $1,000 원래 원가 · 양도 $2,000 = 받은 토큰 시장가 원가) + 환불 9 ETH 매도", rows_of(rows, "ETH"))
chk(rows_of(rows, "TKN") == [(1000.0, 2000.0, 2000.0)] and tok_cost(f) == 2000.0, "P1 토큰 원가 $2,000 그대로(시장가 원가 규칙 유지) · 매도 실현 0",
    [rows_of(rows, "TKN"), tok_cost(f)])
chk(rz(f, d(2)) == 1000.0 and rz(f, d(10)) == 18000.0, "P1 사용분 실현 $1,000 = 입찰 종료(확정) 날 · 환불 ETH 매도 $18,000", [rz(f, d(2)), rz(f, d(10))])
chk(unreal(f) == 0 and unv(f) == [], "P1 미실현 0 · 원가미상 매도 없음", [unreal(f), unv(f)])
sl = (f.get("saleLinks") or [{}])[0]
chk(sl.get("payQty") == 1.0 and sl.get("payCost") == 1000.0 and sl.get("payProceeds") == 2000.0 and sl.get("payRealized") == 1000.0,
    "P1 세일 상자 = 사용분 1 ETH · 원래 원가 $1,000 · 대가 $2,000 · 실현 $1,000", {k: sl.get(k) for k in ("payQty", "payCost", "payProceeds", "payRealized")})
ev_all = json.dumps(f.get("positions") or [], ensure_ascii=False, default=str)
chk("토큰 세일 대금 지불" in ev_all, "P1 카드 기록 줄 '토큰 세일 대금 지불'")
eth_cards = [p for p in f.get("positions") or [] if p.get("sym") == "ETH"]
chk(round(sum(float(p.get("payReal") or 0) for p in eth_cards), 2) == 1000.0 and round(sum(float(p.get("paidQty") or 0) for p in eth_cards), 6) == 1.0
    and round(sum(float(p.get("realized") or 0) for p in eth_cards), 2) == 19000.0,
    "P1 ETH 카드 = 지불 1 ETH · 지불 실현 $1,000 · 카드 실현 합 $19,000", [(p.get("paidQty"), p.get("payReal"), p.get("realized"), p.get("movedQty")) for p in eth_cards])
rc = BLD[0].receipt(ISO(d(2)), "ETH") or {}
chk(((rc.get("sell") or {}).get("pay") or {}).get("n") == 1 and (rc.get("tax") or {}).get("recon") is True and (rc.get("realized") or {}).get("usd") == 1000.0,
    "P1r 영수증(종료일·ETH) = 지불 1건 · 명세 손익 = 카드 실현 $1,000", [rc.get("sell"), rc.get("tax"), rc.get("realized")])
tr = BLD[0].tax_rows(ISO(d(2))[:7], "ETH") or {}
chk(any(abs(float(r.get("xd") or 0) - 2000.0) < 0.01 and abs(float(r.get("xa") or 0) - 1000.0) < 0.01 for r in tr.get("rows") or []),
    "P1x 내보내기(명세 행 API) = 사용분 처분 행(양도 $2,000 · 취득 $1,000)", [(r.get("sold"), r.get("xa"), r.get("xd")) for r in tr.get("rows") or []])
f1b, rows1b = build()
chk(rz_sum(f1b) == 19000.0 and rows_of(rows1b, "ETH") == rows_of(rows, "ETH") and rows_of(rows1b, "TKN") == rows_of(rows, "TKN"),
    "P1b 다시 빌드 = 같은 값(처분이 쌓이지 않음)", [rz_sum(f1b), rows_of(rows1b, "ETH")])

reset()
PX["ETH"] = [(0, 1000.0), (d(1) - 3600, 2000.0), (d(9), 3000.0)]
lg = L()
lg.fund(d(-1), 30000)
lg.swap(d(0), "usdt", 10000, "eth", 10, 10000)
lg.swap(d(1), "eth", 1, "tkn", 1000, 2000)
lg.swap(d(10), "eth", 9, "usdt", 27000, 27000)
lg.swap(d(11), "tkn", 1000, "usdt", 2000, 2000)
lg.done()
json.dump({"owners": {}}, open(web.SALE_PATH, "w"))
fc, rowsc = build()
chk(rz_sum(fc) == 19000.0 and rows_of(rowsc, "ETH") == rows_of(rows, "ETH"),
    "P1c 대조(같은 1 ETH → TKN 일반 스왑) = $19,000 · ETH 명세 행이 CCA 와 같음", [rz_sum(fc), rows_of(rowsc, "ETH")])

res = []
for nm, args in (("P2 가격 하락(입찰 때 $500)", (500, 27000, 2000)), ("P3 가격 동일($1,000)", (1000, 27000, 2000)),
                 ("P4 환불 0 낙찰(10 ETH 전부 사용 · 입찰 때 $2,000)", (2000, 0, 25000, 10))):
    cash = roundtrip(*args)
    f9, rows9 = build()
    res.append((nm, cash, rz_sum(f9), rows_of(rows9, "ETH"), unv(f9)))
    chk(rz_sum(f9) == float(cash) and unv(f9) == [], f"{nm} = 실현 합 = 현금 증가 ${cash:,} · 원가미상 매도 없음", res[-1])
chk(res[0][3][0] == (1.0, 1000.0, 500.0), "P2 사용분 처분 = 양도 $500 · 취득 $1,000(손실 −$500 이 사라지지 않음 — 종전 이익 과대)", res[0][3])
chk(res[1][3][0] == (1.0, 1000.0, 1000.0), "P3 사용분 처분 = 양도·취득 $1,000(실현 0)", res[1][3])
chk(res[2][3] == [(10.0, 10000.0, 20000.0)], "P4 환불 0 = 10 ETH 처분(취득 $10,000 · 양도 $20,000)", res[2][3])

reset()
PX["ETH"] = [(0, 1000.0), (d(1) - 3600, 2000.0), (d(9), 3000.0)]
lg = L()
lg.fund(d(-1), 30000)
lg.swap(d(0), "usdt", 10000, "eth", 10, 10000)
lg.bid(h64(0x111), d(1), 5)
lg.bid(h64(0x112), d(1), 5)
lg.refund(h64(0x211), d(2), 5)
lg.refund(h64(0x212), d(2), 3)
lg.claim(CLAIM, d(3), 1000)
lg.swap(d(10), "eth", 8, "usdt", 24000, 24000)
lg.swap(d(11), "tkn", 1000, "usdt", 5000, 5000)
lg.done()
cache([(1, 5, h64(0x111), d(1), 5, h64(0x211), d(2), 0), (2, 5, h64(0x112), d(1), 3, h64(0x212), d(2), 1000)])
f5, rows5 = build()
chk(rz_sum(f5) == 24000 + 5000 - 10000 and rows_of(rows5, "ETH") == [(2.0, 2000.0, 4000.0), (8.0, 8000.0, 24000.0)],
    "P5 전액 환불 입찰(5)은 처분 없음 · 사용 입찰 2 ETH 만 처분($2,000 → $4,000) · 합 = 현금 증가 $19,000", [rz_sum(f5), rows_of(rows5, "ETH")])
reset()
lg = L()
lg.fund(d(-1), 30000)
lg.swap(d(0), "usdt", 10000, "eth", 10, 10000)
lg.bid(BID, d(1), 10)
lg.refund(EXIT, d(2), 10)
lg.swap(d(10), "eth", 10, "usdt", 30000, 30000)
lg.done()
cache([(1, 10, BID, d(1), 10, EXIT, d(2), 0)])
f5b, rows5b = build()
chk(rz_sum(f5b) == 20000.0 and rows_of(rows5b, "ETH") == [(10.0, 10000.0, 30000.0)] and not (f5b.get("saleLinks") or []),
    "P5b 로트 전체 전액 환불(체결 0) = 로트 없음 · 종전 경로(돌아온 코인 원가 승계) · 실현 $20,000", [rz_sum(f5b), rows_of(rows5b, "ETH")])

reset()
PX["ETH"] = [(0, 1000.0), (d(1) - 3600, 2000.0), (d(2), 3000.0), (d(9), 2500.0)]
lg = L()
lg.fund(d(-1), 30000)
lg.swap(d(0), "usdt", 5000, "eth", 5, 5000)
lg.bid(h64(0x121), d(1), 5)
lg.swap(d(2), "usdt", 10000, "eth", 5, 10000)
lg.bid(h64(0x122), d(3), 5)
lg.refund(h64(0x221), d(4), 4)
lg.refund(h64(0x222), d(5), 1)
lg.claim(CLAIM, d(6), 1000)
lg.swap(d(10), "eth", 5, "usdt", 12500, 12500)
lg.swap(d(11), "tkn", 1000, "usdt", 15000, 15000)
lg.done()
cache([(1, 5, h64(0x121), d(1), 4, h64(0x221), d(4), 200), (2, 5, h64(0x122), d(3), 1, h64(0x222), d(5), 800)])
f6, rows6 = build()
chk(rows_of(rows6, "ETH")[:2] == [(1.0, 1000.0, 2000.0), (4.0, 8000.0, 12000.0)] and tok_cost(f6) == 14000.0,
    "P6 입찰별 = 입찰 1 사용 1 ETH(원가 $1,000 · 대가 $2,000) · 입찰 2 사용 4 ETH(원가 $8,000 · 대가 $12,000) · 토큰 원가 $14,000", [rows_of(rows6, "ETH"), tok_cost(f6)])
chk(rz_sum(f6) == float(12500 + 15000 - 15000), "P6 합 = 현금 증가 $12,500", rz_sum(f6))

reset()
PX["ETH"] = [(0, 1000.0), (d(1) - 3600, 2000.0), (d(9), 3000.0)]
lg = L()
lg.fund(d(-1), 30000)
lg.swap(d(0), "usdt", 10000, "eth", 10, 10000)
lg.bid(BID, d(1), 10)
lg.refund(EXIT, d(2), 9)
lg.claim(CLAIM, d(3), 400)
lg.claim(h64(0x901), d(4), 600)
lg.swap(d(10), "eth", 9, "usdt", 27000, 27000)
lg.swap(d(11), "tkn", 1000, "usdt", 2000, 2000)
lg.done()
cache([(1, 10, BID, d(1), 9, EXIT, d(2), 1000)])
f7, rows7 = build()
chk(rz_sum(f7) == 19000.0 and rows_of(rows7, "ETH") == [(1.0, 1000.0, 2000.0), (9.0, 9000.0, 27000.0)],
    "P7 토큰 두 번 수령(400 + 600) = 사용분 처분 한 번 · 합 $19,000", [rz_sum(f7), rows_of(rows7, "ETH"), rows_of(rows7, "TKN")])

reset()
NO_PX_BEFORE[0] = d(0) + 3600
PX["ETH"] = [(0, 1000.0), (d(1) - 3600, 2000.0), (d(9), 3000.0)]
lg = L()
lg.fund(d(-1), 30000)
lg.eth_in_nocost(d(0), 5)
lg.swap(d(0) + 7200, "usdt", 5000, "eth", 5, 5000)
lg.bid(BID, d(1), 10)
lg.refund(EXIT, d(2), 9)
lg.claim(CLAIM, d(3), 1000)
lg.swap(d(10), "eth", 9, "usdt", 27000, 27000)
lg.done()
cache([(1, 10, BID, d(1), 9, EXIT, d(2), 1000)])
f8, rows8 = build({"first_seen_px": False})
pend8 = [p for p in f8.get("pendings") or [] if p.get("sym") == "ETH" and str(p.get("kind", "")).startswith("원가미상 매도")]
chk(rows_of(rows8, "ETH")[0] == (0.5, 500.0, 1000.0) and rz(f8, d(2)) == 500.0,
    "P8 사용분 1 ETH = 확인 0.5(원가 $500 · 대가 $1,000 → 실현 $500) + 미확인 0.5(원가 지어내지 않음)", [rows_of(rows8, "ETH"), rz(f8, d(2))])
chk("ETH" in unv(f8), "P8 미확인 몫은 원가미상 매도(검토 행)로 — 불명 유지", [unv(f8), pend8[:1]])

cash = roundtrip(2000, 27000, 2000, krw=13_000_000)
set_fx([(d(-1), 1250.0), (d(0), 1300.0), (d(1), 1350.0), (d(2), 1400.0), (d(3), 1450.0), (d(10), 1500.0), (d(11), 1500.0)])
f9, rows9 = build()
er9 = [r for r in rows9 if r.get("sym") == "ETH" and abs(float(r.get("_qty") or 0) - 1.0) < 1e-9]
tk9 = [r for r in rows9 if r.get("sym") == "TKN"]
chk(len(er9) == 1 and abs(float(er9[0].get("_akr") or 0) - 1_300_000) < 5 and abs(float(er9[0].get("rate") or 0) - 1400.0) < 1e-6,
    "P9 사용분 명세 원화 취득가 = 원래 원화 ₩1,300,000(₩1,300/$ 매수) · 양도 환율 = 종료 시각 ₩1,400", [(r.get("_akr"), r.get("rate")) for r in er9])
chk(len(tk9) == 1 and len(er9) == 1 and abs(float(tk9[0].get("_akr") or 0) - float(er9[0].get("_disp")) * float(er9[0].get("rate"))) < 5,
    "P9 토큰 원화 취득가 = 사용분 원화 양도가 ₩2,800,000(이음매 0 — 종전 수령 시각 ₩1,450 환산 ₩2,900,000)", [(r.get("_akr"), r.get("rate")) for r in tk9])
chk(rz_sum(f9) == 19000.0, "P9 USD 실현 합은 환율과 무관 $19,000", rz_sum(f9))

roundtrip(2000, 27000, 2000)
NO_PX_BEFORE[0] = d(2)
PX["ETH"] = [(0, 1000.0), (d(9), 3000.0)]
f10, rows10 = build({"first_seen_px": False})
chk(tok_cost(f10) is None and not [r for r in rows10 if r.get("sym") == "ETH" and abs(float(r.get("_qty") or 0) - 1.0) < 1e-9],
    "P10 입찰 시세 없음(토큰 원가 미확인) = 사용분 처분 없음(대가를 지어내지 않음 · 종전)", [tok_cost(f10), rows_of(rows10, "ETH")])
roundtrip(2000, 27000, 2000)
f11, rows11 = build({"sale_link_off": [f"eth:{AUC}:{B}"]})
chk(not [r for r in rows11 if r.get("sym") == "ETH" and abs(float(r.get("_qty") or 0) - 1.0) < 1e-9],
    "P11 세일 연결 끄기 = 사용분 처분 없음(일반 경로)", rows_of(rows11, "ETH"))

roundtrip(2000, 27000, 2000)
lg = L.__new__(L)
lg.c = dbm.open_db(common.DB_PATH)
lg.A = {"eth": (lg.c.execute("SELECT asset_id FROM assets WHERE kind='native'").fetchone()[0], 18)}
lg.post(BID, 2, d(1), "eth", f"wallet:eth:{B}", -10, None, "move_out", "TRANSFER_OUT")
lg.post(BID, 3, d(1), "eth", f"out:eth:{AUC}", 10, None, "move_in", "TRANSFER_OUT")
lg.c.commit()
lg.c.close()
f12, rows12 = build()
chk(len([r for r in rows12 if r.get("sym") == "ETH" and abs(float(r.get("_qty") or 0) - 1.0) < 1e-9]) == 1 and rz(f12, d(2)) == 1000.0,
    "P12 같은 입찰 송금 두 줄 = 사용분 처분 한 번(입찰별 사용량 상한)", [rows_of(rows12, "ETH"), rz(f12, d(2))])

reset()
lg = L()
lg.fund(d(-1), 10000, a="usdc")
lg.bid(BID, d(1), 10000, asset="usdc")
lg.refund(EXIT, d(2), 9000, asset="usdc")
lg.claim(CLAIM, d(3), 1000)
lg.done()
cache([(1, 10000, BID, d(1), 9000, EXIT, d(2), 1000)], {"addr": USDC, "sym": "USDC", "dec": 6})
f13, rows13 = build()
st13 = [r for r in rows13 if r.get("sym") == "USDC"]
chk(tok_cost(f13) == 1000.0 and abs(rz_sum(f13)) < 0.01 and "USDC" not in unv(f13),
    "P13 스테이블 세일 = 토큰 원가 $1,000 그대로 · USD 실현 0 · 원가미상 매도 없음", [tok_cost(f13), rz_sum(f13), unv(f13), rows_of(rows13, "USDC")])
chk(len(st13) == 1 and all(r.get("tk") == "st" for r in st13) and abs(float(st13[0].get("_qty") or 0) - 1000.0) < 1e-6, "P13 스테이블 사용분 처분 행 = 스테이블 표식(환차손익 줄로 모임 · 일반 스테이블 지불과 같음)", [(r.get("tk"), r.get("_qty")) for r in st13])

reset()
PX["ETH"] = [(0, 1000.0), (d(1) - 3600, 2000.0), (d(9), 3000.0)]
lg = L()
lg.fund(d(-1), 30000)
lg.swap(d(0), "usdt", 10000, "eth", 10, 10000)
lg.bid(BID, d(1), 10)
lg.refund(EXIT, d(2), 9)
lg.claim(CLAIM, d(3), 1000)
lg.swap(d(4), "tkn", 1000, "fin", 1000, 5000)
lg.swap(d(10), "eth", 9, "usdt", 27000, 27000)
lg.swap(d(11), "fin", 1000, "usdt", 2000, 2000)
lg.done()
cache([(1, 10, BID, d(1), 9, EXIT, d(2), 1000)], redeem={"to": FIN, "sym": "FIN", "decimals": 18, "ratio": "1", "src": "seed"})
f14, rows14 = build()
chk(rz_sum(f14) == 19000.0 and rows_of(rows14, "ETH") == [(1.0, 1000.0, 2000.0), (9.0, 9000.0, 27000.0)] and rows_of(rows14, "FIN") == [(1000.0, 2000.0, 2000.0)],
    "P14 영수증 수령 → 본 토큰 교환 → 매도 = 사용분 처분 한 번 · 본 토큰 원가 $2,000 승계 · 합 $19,000", [rz_sum(f14), rows_of(rows14, "ETH"), rows_of(rows14, "FIN")])

reset()
PX["ETH"] = [(0, 1000.0), (d(1) - 3600, 2000.0), (d(9), 3000.0)]
lg = L()
lg.fund(d(-1), 30000)
lg.swap(d(0), "usdt", 10000, "eth", 10, 10000, krw=13_000_000)
lg.bid(h64(0x131), d(1), 5)
lg.bid(h64(0x132), d(1) + 60, 5)
lg.refund(h64(0x231), d(2), 4)
lg.claim(CLAIM, d(3), 1000)
lg.refund(h64(0x232), d(4), 4)
lg.claim(h64(0x902), d(5), 1000)
lg.swap(d(10), "eth", 8, "usdt", 24000, 24000)
lg.swap(d(11), "tkn", 2000, "usdt", 5000, 5000)
lg.done()
cache([(1, 5, h64(0x131), d(1), 4, h64(0x231), d(2), 1000), (2, 5, h64(0x132), d(1) + 60, 4, h64(0x232), d(4), 1000)])
set_fx([(d(0), 1300.0), (d(1), 1300.0), (d(2), 1300.0), (d(3), 1350.0), (d(4), 1500.0), (d(5), 1450.0), (d(10), 1500.0), (d(11), 1500.0)])
f15, rows15 = build()
pay15 = [r for r in rows15 if r.get("sym") == "ETH" and str(r.get("ex") or "").startswith("온체인(토큰 세일)")]
tk15 = [r for r in rows15 if r.get("sym") == "TKN"]
kd15 = sum(float(r["_disp"]) * float(r["rate"]) for r in pay15)
chk(len(pay15) == 2 and abs(kd15 - (2000 * 1300 + 2000 * 1500)) < 5 and len(tk15) == 1 and abs(float(tk15[0].get("_akr") or 0) - kd15) < 5,
    "P15 종료 사이에 수령이 껴도 토큰 원화 취득가 = 사용분 처분 원화 양도가 합 ₩5,600,000(종전 수령 때 누계 평균 → ₩5,400,000)",
    [[(r.get("_disp"), r.get("rate")) for r in pay15], [r.get("_akr") for r in tk15]])
chk(rz_sum(f15) == float(24000 + 5000 - 10000), "P15 USD 실현 합 = 현금 증가 $19,000", rz_sum(f15))

reset()
PX["ETH"] = [(0, 1000.0), (d(40) - 3600, 2000.0), (d(49), 3000.0)]
lg = L()
lg.fund(d(38), 30000)
lg.swap(d(39), "usdt", 10000, "eth", 10, 10000)
lg.bid(BID, d(40), 10)
lg.refund(EXIT, d(41), 9)
lg.claim(CLAIM, d(42), 1000)
lg.swap(d(50), "eth", 9, "usdt", 27000, 27000)
lg.swap(d(51), "tkn", 1000, "usdt", 2000, 2000)
lg.done()
cache([(1, 10, BID, d(40), 9, EXIT, d(41), 1000)])
f16, rows16 = build()
vb16 = ((f16.get("venueFlows30") or {}).get("by") or {})
chk(rz_sum(f16) == 19000.0 and round(sum(float(v.get("realized") or 0) for v in vb16.values()), 2) == 19000.0,
    "P16 보관처 '이곳 매매 실현'(최근 30일) 합 = 전체 실현 $19,000(종전 사용분 $1,000 이 out:<경매> 위치로 가 빠짐)", [rz_sum(f16), vb16])
pe16 = [e for p in f16.get("positions") or [] for e in p.get("events") or [] if "토큰 세일 대금 지불" in str(e.get("d") or "")]
chk(len(pe16) == 1 and pe16[0].get("src") == "w:" + B, "P16 처분 기록 줄 소스 = 입찰 지갑(지갑 필터에 잡힘 · 종전 소스 없음)", [e.get("src") for e in pe16])
sa16 = [p.get("srcAct") or {} for p in f16.get("positions") or [] if p.get("sym") == "ETH" and (p.get("realizedByDay") or {}).get(ISO(d(41)))]
chk(sa16 and ISO(d(41)) in (sa16[0].get("w:" + B) or {}), "P16 그 카드 지갑별 활동(srcAct)에 종료일 있음 — 지갑 필터에서 카드가 사라지지 않음", sa16)
da16 = (f16.get("dayActs") or {})
a16 = da16.get(ISO(d(41))) or da16.get(ISO(d(41))[5:]) or {}
chk(a16.get("pay") == 1, "P16 일별 건수 = 지불 1(일반 매도 아님 · 카드 payByDay·영수증과 같음)", a16)

reset()
PX["ETH"] = [(0, 1000.0), (d(1) - 3600, 2000.0), (d(9), 3000.0)]
lg = L()
lg.fund(d(-1), 30000)
lg.swap(d(0), "usdt", 10000, "eth", 10, 10000)
lg.bid(h64(0x141), d(1), 5)
lg.bid(h64(0x142), d(1) + 60, 5)
lg.refund(h64(0x241), d(2), 4)
lg.refund(h64(0x242), d(2) + 60, 4)
lg.claim(CLAIM, d(3), 2000)
lg.swap(d(10), "eth", 8, "usdt", 24000, 24000)
lg.done()
cache([(1, 5, h64(0x141), d(1), 4, h64(0x241), 253402300800, 1000), (2, 5, h64(0x142), d(1) + 60, 4, h64(0x242), d(2) + 60, 1000)])
try:
    f17, rows17 = build()
except Exception as e17:
    f17, rows17 = None, [repr(e17)[:200]]
pay17 = [r for r in rows17 if isinstance(r, dict) and r.get("sym") == "ETH" and str(r.get("ex") or "").startswith("온체인(토큰 세일)")]
chk(f17 is not None and rows_of(pay17, "ETH") == [(1.0, 1000.0, 2000.0)],
    "P17 한 입찰의 종료 시각이 범위 밖(9999년 뒤) = 빌드 성공 · 그 입찰 처분만 건너뜀 · 정상 입찰 처분 1건 그대로", [f17 is not None, rows_of(pay17, "ETH"), rows17[:1]])

SEED = {"factories": set(), "chains": ["eth"], "auctions": {}, "redeem": {}}


def lots_dec(cdec, tdec):
    un = Decimal(10) ** cdec
    tun = Decimal(10) ** tdec
    c = {"owners": {f"eth:{B}": {"t": 1, "chain": "eth", "owner": B,
                                 "bids": [{"auction": AUC, "id": 1, "amount": str(int(10 * un)), "bid_tx": BID, "bid_ts": 1000, "filled": str(int(1000 * tun)),
                                           "refunded": str(int(9 * un)), "exit_tx": EXIT, "exit_ts": 2000, "claim_tx": CLAIM, "claim_ts": 3000}],
                                 "auctions": {AUC: {"ok": True, "currency": {"addr": USDC, "sym": "USDC", "dec": cdec},
                                                    "token": {"addr": TKN, "sym": "TKN", "dec": tdec}}}}}}
    return sale_match.build_lots(c, lambda s9, t9: 1.0, (), SEED)


for cd9, td9 in ((0, 0), (6, 8), (8, 6), (18, 18), (0, 18), (18, 0)):
    lt = lots_dec(cd9, td9)
    chk(len(lt) == 1 and lt[0]["paid"] == Decimal(10) and lt[0]["refund"] == Decimal(9) and lt[0]["filled"] == Decimal(1000) and lt[0]["cost"] == Decimal(1),
        f"D1 통화 decimals {cd9} · 토큰 decimals {td9} = 입찰 10 · 환불 9 · 체결 1,000 · 원가 $1(0 을 18 로 바꾸지 않음)",
        [lt and (lt[0]["paid"], lt[0]["refund"], lt[0]["filled"], lt[0]["cost"])])
for bad9, nm in ((None, "None"), ("", "빈 값"), ("x", "글자"), (-1, "음수")):
    c9 = {"owners": {f"eth:{B}": {"t": 1, "chain": "eth", "owner": B,
                                  "bids": [{"auction": AUC, "id": 1, "amount": str(10 * E18), "bid_tx": BID, "bid_ts": 1000, "filled": str(1000 * E18),
                                            "refunded": str(9 * E18), "exit_tx": EXIT, "exit_ts": 2000, "claim_tx": CLAIM, "claim_ts": 3000}],
                                  "auctions": {AUC: {"ok": True, "currency": {"addr": USDC, "sym": "USDC", "dec": bad9},
                                                     "token": {"addr": TKN, "sym": "TKN", **({} if bad9 is None else {"dec": bad9})}}}}}}
    lt = sale_match.build_lots(c9, lambda s9, t9: 1.0, (), SEED)
    chk(len(lt) == 1 and lt[0]["paid"] == Decimal(10) and lt[0]["filled"] == Decimal(1000), f"D2 decimals {nm}·누락 = 기본 18", [lt and (lt[0]["paid"], lt[0]["filled"])])


def _get_stub(url):
    if "/api/v2/addresses/" in url and "token-transfers" not in url:
        return {}
    return {"items": []}


T_SUB, T_EXIT, T_CLM = sale_match.T_BID_SUBMITTED, sale_match.T_BID_EXITED, sale_match.T_TOKENS_CLAIMED


def _logs_stub(get, base, topic0, owner, address=None):
    if topic0 == T_SUB:
        return [{"address": AUC, "topics": [topic0, "0x" + "0" * 63 + "1"], "data": "0x" + "%064x" % 1 + "%064x" % (10 * E18),
                 "transactionHash": BID, "timeStamp": "0x3e8"}]
    if topic0 == T_EXIT:
        return [{"address": AUC, "topics": [topic0, "0x" + "0" * 63 + "1"], "data": "0x" + "%064x" % (1000 * E18) + "%064x" % (9 * E18),
                 "transactionHash": EXIT, "timeStamp": "0x7d0"}]
    return [{"address": AUC, "topics": [topic0, "0x" + "0" * 63 + "1"], "data": "0x", "transactionHash": CLAIM, "timeStamp": "0xbb8"}]


def _tx_stub(get, base, tx):
    if tx == CLAIM:
        return [{"addr": TKN, "sym": "TKN", "dec": 18, "raw": 1000 * E18, "from": AUC, "to": B}]
    return []


_o = (sale_match._get_logs, sale_match._tx_transfers)
sale_match._get_logs, sale_match._tx_transfers = _logs_stub, _tx_stub
try:
    seed9 = {"factories": set(), "chains": ["eth"], "auctions": {f"eth:{AUC}": {}}, "redeem": {f"eth:{TKN}": {"to": USDC, "sym": "X0", "decimals": 0, "ratio": "1"}}}
    rec9 = sale_match.fetch_owner(_get_stub, "https://example.invalid", "eth", B, seed9, now=5000)
    rd9 = ((rec9.get("auctions") or {}).get(AUC) or {}).get("redeem") or {}
    chk(rd9.get("decimals") == 0, "D3 영수증 교환 seed decimals 0 = 0 그대로(종전 18)", rd9)
    seed9["redeem"][f"eth:{TKN}"].pop("decimals")
    rec9 = sale_match.fetch_owner(_get_stub, "https://example.invalid", "eth", B, seed9, now=5000)
    chk((((rec9.get("auctions") or {}).get(AUC) or {}).get("redeem") or {}).get("decimals") == 18, "D3b seed decimals 누락 = 기본 18")
finally:
    sale_match._get_logs, sale_match._tx_transfers = _o
chk(sale_match._decimals(0) == 0 and sale_match._decimals("6") == 6 and sale_match._decimals(None) == 18 and sale_match._decimals("") == 18
    and sale_match._decimals(-3) == 18 and sale_match._decimals(256) == 18 and sale_match._decimals(True) == 18,
    "D4 decimals 해석 = 0~255 정수만 그대로 · None·빈 값·음수·256↑·불리언 = 18")
T.finish()
