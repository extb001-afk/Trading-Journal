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

B, C = "0x" + "b3" * 20, "0x" + "c3" * 20
AUC, TKN = "0x" + "a5" * 20, "0x" + "d5" * 20
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
json.dump({"chains": {}, "wallets": [{"chain": "eth", "address": B, "label": "B"}, {"chain": "eth", "address": C, "label": "C"}],
           "backfill_months": 5}, open(os.path.join(os.environ["TJ_BASE"], "config.json"), "w"))
import acct_norm
import db as dbm
import histcurve
import netpace
import web

FS_EX = getattr(web, "FS_EX", " · 최초 인식 시가")
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


class L:
    def __init__(self):
        p = common.DB_PATH
        for sfx in ("", "-wal", "-shm"):
            if os.path.exists(p + sfx):
                os.remove(p + sfx)
        self.c = dbm.open_db(p)
        self.A = {}
        for key, kind, addr, sym, dec in (("eth", "native", None, "ETH", 18), ("usdt", "token", USDT, "USDT", 6),
                                          ("usdc", "token", USDC, "USDC", 6), ("tkn", "token", TKN, "TKN", 18)):
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
                       (tx, t, json.dumps(snap), json.dumps([B, C]), t))

    def tx(self):
        self.n += 1
        return h64(0x5000 + self.n)

    def fund_usdt(self, t, q, w=B):
        tx = self.tx()
        self.post(tx, 0, t, "usdt", f"wallet:eth:{w}", q, None, "acq", "TRANSFER_IN")
        self.raw(tx, t, frm="0x" + "ee" * 20, to=w)

    def buy_eth(self, t, q, usd, krw=None, w=B):
        tx = self.tx()
        self.post(tx, 0, t, "usdt", f"wallet:eth:{w}", -Decimal(str(usd)), usd, "disp", "SWAP")
        self.post(tx, 1, t, "eth", f"wallet:eth:{w}", q, usd, "acq", "SWAP", krw=krw)
        self.raw(tx, t)

    def eth_in_nocost(self, t, q, w=B):
        tx = self.tx()
        self.post(tx, 0, t, "eth", f"wallet:eth:{w}", q, None, "acq", "TRANSFER_IN")
        self.raw(tx, t, frm="0x" + "ef" * 20, to=w, internal=[{"from": "0x" + "ef" * 20, "to": w, "value": str(int(q * E18))}])

    def bid(self, tx, t, q, asset="eth", w=B):
        self.post(tx, 0, t, asset, f"wallet:eth:{w}", -Decimal(str(q)), None, "move_out", "TRANSFER_OUT")
        self.post(tx, 1, t, asset, f"out:eth:{AUC}", q, None, "move_in", "TRANSFER_OUT")
        tts = [] if asset == "eth" else [{"from": {"hash": w}, "to": {"hash": AUC}, "token": {"address_hash": USDC, "symbol": "USDC", "decimals": "6"},
                                          "total": {"value": str(int(q * 10 ** 6)), "decimals": "6"}}]
        self.raw(tx, t, tts=tts, frm=w, to=AUC)

    def refund(self, tx, t, q, w=B, seq=0, ev="PROGRAM_IN", asset="eth"):
        self.post(tx, seq, t, asset, f"wallet:eth:{w}", q, None, "acq", ev)
        if asset == "eth":
            self.raw(tx, t, internal=[{"from": AUC, "to": w, "value": str(int(Decimal(str(q)) * E18))}], frm=w, to=AUC)
        else:
            self.raw(tx, t, tts=[{"from": {"hash": AUC}, "to": {"hash": w}, "token": {"address_hash": USDC, "symbol": "USDC", "decimals": "6"},
                                  "total": {"value": str(int(q * 10 ** 6)), "decimals": "6"}}], frm=w, to=AUC)

    def claim(self, tx, t, q, w=B):
        self.post(tx, 0, t, "tkn", f"wallet:eth:{w}", q, None, "acq", "PROGRAM_IN")
        self.raw(tx, t, tts=[{"from": {"hash": AUC}, "to": {"hash": w}, "token": {"address_hash": TKN, "symbol": "TKN", "decimals": "18"},
                              "total": {"value": str(int(q * E18)), "decimals": "18"}}], frm=w, to=AUC)

    def sell_eth(self, t, q, usd, w=B):
        tx = self.tx()
        self.post(tx, 0, t, "eth", f"wallet:eth:{w}", -Decimal(str(q)), usd, "disp", "SWAP")
        self.post(tx, 1, t, "usdt", f"wallet:eth:{w}", usd, usd, "acq", "SWAP")
        self.raw(tx, t)
        return tx

    def done(self):
        self.c.commit()
        self.c.close()


def cache(bids, cur=None):
    cur = cur or {"addr": "", "sym": "ETH", "dec": 18}
    un = 10 ** int(cur["dec"])
    bl = [{"auction": AUC, "id": i, "amount": str(int(Decimal(str(a)) * un)), "bid_tx": btx, "bid_ts": bts, "filled": str(int(Decimal(str(f)) * E18)),
           "refunded": str(int(Decimal(str(r)) * un)), "exit_tx": etx, "exit_ts": ets, "claim_tx": h64(0x900), "claim_ts": d(30)}
          for i, a, btx, bts, r, etx, ets, f in bids]
    json.dump({"owners": {f"eth:{B}": {"t": NOW, "chain": "eth", "owner": B, "bids": bl,
                                         "auctions": {AUC: {"ok": True, "why": "seed", "currency": cur, "token": {"addr": TKN, "sym": "TKN", "dec": 18}}}}}},
              open(web.SALE_PATH, "w"))


def build(prefs=None):
    common.atomic_write_json(web.PREFS_PATH, dict({"plans": {}, "ignored": []}, **(prefs or {})))
    b = web.StateBuilder()
    b.skip_gen_check = True
    conn = dbm.open_db(common.DB_PATH, readonly=True)
    try:
        f = b._build(conn)["fields"]
    finally:
        conn.close()
    return f, (b._day_idx or {}).get("tax") or []


def eth_rows(rows):
    return [r for r in rows if r.get("sym") == "ETH"]


def rz(f, day):
    return round(float((f.get("realizedByDate") or {}).get(ISO(day), 0)), 2)


def unv(f):
    return {str(p.get("sym") or "") for p in f.get("pendings") or [] if str(p.get("kind", "")).startswith("원가미상 매도")}


def sale_box(f):
    return [(s.get("costUsd"), s.get("unit"), s.get("usedQty"), s.get("usedCost")) for s in f.get("saleLinks") or []]


def acq_disp(rows):
    return [(round(float(r.get("_qty", r.get("qty")) or 0), 6), round(float(r.get("_acq", r.get("acq")) or 0), 2),
             round(float(r.get("_disp", r.get("disp")) or 0), 2), str(r.get("ex") or "").endswith(FS_EX)) for r in rows]


def reset_px():
    PX["ETH"] = [(0, 1000.0)]
    NO_PX_BEFORE[0] = 0
    pin9 = getattr(web, "FS_PIN_PATH", os.path.join(common.STATE_DIR, "first_seen_px.json"))
    if os.path.exists(pin9):
        os.remove(pin9)


BID, EXIT, CLAIM = h64(0x101), h64(0x201), h64(0x900)


def base_ledger(ref_px=1200.0, bid_px_missing=False):
    reset_px()
    PX["ETH"] = [(0, 1000.0), (d(2) - 3600, ref_px), (d(9), 1200.0)]
    if bid_px_missing:
        NO_PX_BEFORE[0] = d(2) - 3600
    lg = L()
    lg.fund_usdt(d(-1), 30000)
    lg.buy_eth(d(0), 10, 10000, krw=13_000_000)
    lg.bid(BID, d(1), 10)
    lg.refund(EXIT, d(2), 9)
    lg.claim(CLAIM, d(3), 1000)
    lg.sell_eth(d(10), 9, 10800)
    lg.done()
    cache([(1, 10, BID, d(1), 9, EXIT, d(2), 1000)])


base_ledger()
f, rows = build()
er = eth_rows(rows)
chk(sale_box(f) and sale_box(f)[0][0] == 1000.0 and sale_box(f)[0][3] == 1000.0,
    "C1 취득 토큰 원가 $1,000(15차 순매입 원가 그대로 · 입찰 시세 × 실제로 쓴 1 ETH)", sale_box(f))
chk(acq_disp(er) == [(9.0, 9000.0, 10800.0, False)],
    "C1 환불 ETH 매도 명세 = 수량 9 · 취득 $9,000 · 처분 $10,800 · 최초 인식 시가 표기 없음(종전 취득 $10,800 · 추정 표기)", acq_disp(er))
chk(rz(f, d(10)) == 1800.0, "C1 ETH 실현 $1,800(종전 $0)", rz(f, d(10)))
chk("ETH" not in unv(f), "C1 ETH 원가미상 매도 없음", sorted(unv(f)))
akr = [r.get("_akr") for r in er]
chk(len(akr) == 1 and akr[0] is not None and abs(float(akr[0]) - 11_700_000) < 5,
    "C1 명세 원화 취득가액 = 입찰 때 보낸 원화 ₩13,000,000 × 9/10 = ₩11,700,000(환불 시각 환율로 다시 매기지 않음)", akr)
sl1 = (f.get("saleLinks") or [{}])[0]
chk(sl1.get("refundBackQty") == 9.0 and sl1.get("refundBackCost") == 9000.0 and (f.get("_diag") or {}).get("sale_refund_n") == 1,
    "C1 세일 상자 응답 = 환불 9 ETH 에 입찰 원가 $9,000 복원(진단 1건)", [sl1.get("refundBackQty"), sl1.get("refundBackCost"), (f.get("_diag") or {}).get("sale_refund_n")])
chk("토큰 세일 환불 · 입찰 원가 복원 ($9,000.00)" in json.dumps(f, ensure_ascii=False, default=str), "C1 일별 기록 줄 = '토큰 세일 환불 · 입찰 원가 복원 ($9,000.00)'")
f1b, rows1b = build()
chk(acq_disp(eth_rows(rows1b)) == acq_disp(er) and rz(f1b, d(10)) == 1800.0 and sale_box(f1b) == sale_box(f),
    "C1 다시 빌드 = 같은 값(복원이 쌓이지 않음 · 최초 인식 시가 고정값 영향 없음)", [acq_disp(eth_rows(rows1b)), rz(f1b, d(10))])

f2, rows2 = build({"first_seen_px": False})
chk(acq_disp(eth_rows(rows2)) == [(9.0, 9000.0, 10800.0, False)] and rz(f2, d(10)) == 1800.0 and "ETH" not in unv(f2),
    "C2 최초 인식 시가 끔 = 같은 값(취득 $9,000 · 실현 $1,800 — 종전: 원가 미확인 · 명세 행 없음 · 실현 0)", [acq_disp(eth_rows(rows2)), rz(f2, d(10)), sorted(unv(f2))])

lid = f"eth:{AUC}:{B}"
f3, rows3 = build({"sale_link_off": [lid]})
chk(acq_disp(eth_rows(rows3)) == [(9.0, 9000.0, 10800.0, False)] and rz(f3, d(10)) == 1800.0,
    "C3 (대조) 세일 연결 끊기 → 일반 '보냈던 주소에서 돌아옴' 승계 $9,000 · 실현 $1,800(두 경로가 겹쳐 $18,000 이 되지 않음)", [acq_disp(eth_rows(rows3)), rz(f3, d(10))])
f3b, rows3b = build({"sale_link_off": [lid], "first_seen_px": False})
chk(not [r for r in eth_rows(rows3b) if r.get("_acq", 0) > 9000.01], "C3b 연결 끊기 + 최초 인식 시가 끔 = 세일 복원 없음(일반 규칙 · 지어낸 원가 없음)", acq_disp(eth_rows(rows3b)))

res4 = []
for rp in (900.0, 2000.0):
    base_ledger(ref_px=rp)
    f4, rows4 = build()
    res4.append((rp, acq_disp(eth_rows(rows4)), rz(f4, d(10)), sale_box(f4)[0][0] if sale_box(f4) else None))
chk(all(a9 == [(9.0, 9000.0, 10800.0, False)] and r9 == 1800.0 and t9 == 1000.0 for _p, a9, r9, t9 in res4),
    "C4 환불 때 시세 $900 · $2,000 = 환불 ETH 원가 $9,000 · 실현 $1,800 · 토큰 원가 $1,000 그대로", res4)

reset_px()
PX["ETH"] = [(0, 1000.0), (d(2), 2000.0), (d(9), 1500.0)]
lg = L()
lg.fund_usdt(d(-1), 30000)
lg.buy_eth(d(0), 5, 5000)
lg.bid(h64(0x111), d(1), 5)
lg.buy_eth(d(2), 5, 10000)
lg.bid(h64(0x112), d(3), 5)
lg.refund(h64(0x211), d(4), 4)
lg.refund(h64(0x212), d(5), 1)
lg.claim(CLAIM, d(6), 500)
lg.sell_eth(d(10), 5, 7500)
lg.done()
cache([(1, 5, h64(0x111), d(1), 4, h64(0x211), d(4), 100), (2, 5, h64(0x112), d(3), 1, h64(0x212), d(5), 400)])
f5, rows5 = build()
chk(acq_disp(eth_rows(rows5)) == [(5.0, 6000.0, 7500.0, False)] and rz(f5, d(10)) == 1500.0,
    "C5 여러 입찰 = 입찰별 보낸 원가 비례(4/5 × $5,000 + 1/5 × $10,000 = $6,000) · 실현 $1,500", [acq_disp(eth_rows(rows5)), rz(f5, d(10))])
chk(sale_box(f5) and sale_box(f5)[0][0] == 1000.0 + 4 * 2000.0, "C5 토큰 원가 = (5−4)×$1,000 + (5−1)×$2,000 = $9,000(15차 그대로)", sale_box(f5))

lg = L()
lg.fund_usdt(d(-1), 30000)
lg.buy_eth(d(0), 5, 5000)
lg.bid(h64(0x111), d(1), 5)
lg.buy_eth(d(2), 5, 10000)
lg.bid(h64(0x112), d(3), 5)
lg.refund(h64(0x213), d(4), 5)
lg.claim(CLAIM, d(6), 500)
lg.sell_eth(d(10), 5, 7500)
lg.done()
cache([(1, 5, h64(0x111), d(1), 4, h64(0x213), d(4), 100), (2, 5, h64(0x112), d(3), 1, h64(0x213), d(4), 400)])
f6, rows6 = build()
chk(acq_disp(eth_rows(rows6)) == [(5.0, 6000.0, 7500.0, False)] and rz(f6, d(10)) == 1500.0,
    "C6 한 종료 tx 에 두 입찰 환불 = 입찰별 확인 환불량 비례 배분($4,000 + $2,000)", [acq_disp(eth_rows(rows6)), rz(f6, d(10))])

reset_px()
PX["ETH"] = [(0, 1000.0), (d(2) - 3600, 1300.0), (d(5), 1500.0), (d(9), 2000.0)]
lg = L()
lg.fund_usdt(d(-1), 30000)
lg.buy_eth(d(0), 12, 12000)
for i in range(3):
    lg.bid(h64(0x121 + i), d(1), 4)
lg.refund(h64(0x221), d(2), 1)
lg.refund(h64(0x222), d(3), 2)
lg.refund(h64(0x223), d(4), 3)
lg.refund(h64(0x2ff), d(6), 2)
lg.claim(CLAIM, d(7), 600)
lg.sell_eth(d(10), 8, 16000)
lg.done()
cache([(1 + i, 4, h64(0x121 + i), d(1), 1 + i, h64(0x221 + i), d(2 + i), 200) for i in range(3)])
f7, rows7 = build()
ad7 = acq_disp(eth_rows(rows7))
chk(len(ad7) == 1 and ad7[0][0] == 8.0 and ad7[0][1] == 9000.0 and rz(f7, d(10)) == 7000.0,
    "C7 부분 환불 1·2·3 = 1/4·2/4·3/4 × $4,000 = $6,000(환불 때 시세 $1,300 아님) + 종료 tx 아닌 2 ETH = 받은 날 시가 $3,000(입찰 원가 안 씀) → 취득 $9,000 · 실현 $7,000",
    [ad7, rz(f7, d(10))])
f7b, rows7b = build({"first_seen_px": False})
chk(sorted(unv(f7b)) == ["ETH"] and acq_disp(eth_rows(rows7b)) == [(6.0, 6000.0, 12000.0, False)] and rz(f7b, d(10)) == 6000.0,
    "C7b 최초 인식 시가 끔 = 환불 6 ETH 는 복원($6,000) · 종료 tx 아닌 2 ETH 만 원가 미확인", [sorted(unv(f7b)), acq_disp(eth_rows(rows7b)), rz(f7b, d(10))])

base_ledger()
lg = L.__new__(L)
lg.c = dbm.open_db(common.DB_PATH)
lg.A = {"eth": (lg.c.execute("SELECT asset_id FROM assets WHERE kind='native'").fetchone()[0], 18)}
lg.A["usdt"] = (lg.c.execute("SELECT asset_id FROM assets WHERE symbol='USDT'").fetchone()[0], 6)
lg.n = 90
lg.refund(EXIT, d(2), 9, seq=1)
lg.sell_eth(d(11), 9, 10800)
lg.done()
f8, rows8 = build({"first_seen_px": False})
f8b, rows8b = build({"first_seen_px": False})
chk(acq_disp(eth_rows(rows8)) == [(9.0, 9000.0, 10800.0, False)] and acq_disp(eth_rows(rows8b)) == acq_disp(eth_rows(rows8)) and "ETH" in unv(f8),
    "C8 같은 환불이 두 줄(18 ETH) = 확인 환불량 9 ETH 까지만 $9,000 한 번(나머지 9 = 원가 미확인 매도) · 다시 빌드해도 같음",
    [acq_disp(eth_rows(rows8)), acq_disp(eth_rows(rows8b)), sorted(unv(f8))])

base_ledger(bid_px_missing=True)
f9, rows9 = build()
chk(sale_box(f9) and sale_box(f9)[0][0] is None, "C9 입찰 시각 시세 없음 = 토큰 원가 미확인(지어내지 않음 · 15차)", sale_box(f9))
chk(acq_disp(eth_rows(rows9)) == [(9.0, 9000.0, 10800.0, False)] and rz(f9, d(10)) == 1800.0,
    "C9 그래도 환불 ETH 원가 = 원장 원가 $9,000 · 실현 $1,800", [acq_disp(eth_rows(rows9)), rz(f9, d(10))])

reset_px()
NO_PX_BEFORE[0] = d(1)
PX["ETH"] = [(0, 1000.0), (d(2) - 3600, 1200.0)]
lg = L()
lg.fund_usdt(d(-1), 30000)
lg.eth_in_nocost(d(0), 10)
lg.bid(BID, d(1), 10)
lg.refund(EXIT, d(2), 9)
lg.claim(CLAIM, d(3), 1000)
lg.sell_eth(d(10), 9, 10800)
lg.done()
cache([(1, 10, BID, d(1), 9, EXIT, d(2), 1000)])
f10, rows10 = build()
chk(not eth_rows(rows10) and "ETH" in unv(f10) and rz(f10, d(10)) == 0,
    "C10 보낼 때 원가 미확인이던 몫 = 환불도 원가 미확인(환불 때 시세 $1,200 로 확정 안 함 · 종전: 취득 $10,800 추정)", [acq_disp(eth_rows(rows10)), sorted(unv(f10))])

base_ledger()
lg = L.__new__(L)
lg.c = dbm.open_db(common.DB_PATH)
lg.c.execute("UPDATE postings SET location=? WHERE source_id=? AND leg_kind='acq'", (f"wallet:eth:{C}", EXIT))
lg.c.commit()
lg.c.close()
f11, rows11 = build({"first_seen_px": False})
chk(not [r for r in eth_rows(rows11) if r.get("_acq", 0) > 0], "C11 종료 tx 라도 입찰자(owner) 아닌 지갑 수령 = 입찰 원가 연결 안 함", acq_disp(eth_rows(rows11)))

reset_px()
PX["ETH"] = [(0, 1000.0), (d(1) + 3600, 1200.0)]
lg = L()
lg.fund_usdt(d(-1), 30000)
lg.buy_eth(d(0), 10, 10000)
lg.bid(BID, d(1), 10)
lg.refund(EXIT, d(1) + 7200, "9.96")
lg.claim(CLAIM, d(3), 10)
lg.sell_eth(d(10), "9.96", "11952")
lg.done()
cache([(1, 10, BID, d(1), "9.96", EXIT, d(1) + 7200, 10)])
f13, rows13 = build()
chk(acq_disp(eth_rows(rows13)) == [(9.96, 9960.0, 11952.0, False)] and rz(f13, d(10)) == 1992.0,
    "C13 입찰 2시간 뒤 9.96 ETH 환불(왕복 짝과 겹침) = 원가 $9,960 한 번(이중 $19,920 아님) · 실현 $1,992", [acq_disp(eth_rows(rows13)), rz(f13, d(10))])

reset_px()
PX["ETH"] = [(0, 1000.0), (d(1) + 3600, 1200.0)]
lg = L()
lg.fund_usdt(d(-1), 30000)
lg.buy_eth(d(0), 10, 10000)
lg.bid(BID, d(1), 10)
tx14 = h64(0x3333)
lg.post(tx14, 0, d(1) + 7200, "eth", f"wallet:eth:{B}", 10, None, "acq", "PROGRAM_IN")
lg.raw(tx14, d(1) + 7200, internal=[{"from": "0x" + "9a" * 20, "to": B, "value": str(10 * E18)}], frm=B, to="0x" + "9a" * 20)
lg.refund(EXIT, d(2), 9)
lg.claim(CLAIM, d(3), 1000)
lg.sell_eth(d(10), 19, 22800)
lg.done()
cache([(1, 10, BID, d(1), 9, EXIT, d(2), 1000)])
f14, rows14 = build({"first_seen_px": False})
chk(acq_disp(eth_rows(rows14)) == [(9.0, 9000.0, 10800.0, False)] and "ETH" in unv(f14),
    "C14 입찰 송금이 무관한 유입과 왕복 짝이 돼도 입찰 원가는 종료 tx 환불에만 한 번($9,000 · 무관한 10 ETH = 원가 미확인 — 종전 $19,000 이중)",
    [acq_disp(eth_rows(rows14)), sorted(unv(f14))])

reset_px()
lg = L()
lg.post(h64(0x701), 0, d(-1), "usdc", f"wallet:eth:{B}", 10000, None, "acq", "TRANSFER_IN")
lg.raw(h64(0x701), d(-1), frm="0x" + "ee" * 20, to=B)
lg.bid(BID, d(1), 10000, asset="usdc")
lg.refund(EXIT, d(2), 9000, asset="usdc")
lg.claim(CLAIM, d(3), 1000)
lg.done()
cache([(1, 10000, BID, d(1), 9000, EXIT, d(2), 1000)], {"addr": USDC, "sym": "USDC", "dec": 6})
f12, _r12 = build()
chk(sale_box(f12) and sale_box(f12)[0][0] == 1000.0, "C12 스테이블 세일 토큰 원가 $1,000(종전)", sale_box(f12))

import sale_match
SEED = {"factories": set(), "chains": ["eth"], "auctions": {}, "redeem": {}}
cache([(1, 10, BID, d(1), 9, EXIT, d(2), 1000), (2, 5, h64(0x102), d(1), 6, h64(0x202), d(2), 100)])
lu = sale_match.build_lots(json.load(open(web.SALE_PATH)), lambda s9, t9: 1000.0, (), SEED)
bd = sorted(((b9["bid_tx"], b9["exit_tx"], b9["amount"], b9["refunded"]) for b9 in (lu[0].get("bid_d") or [])), key=str) if lu else []
chk(len(lu) == 1 and lu[0].get("cur_addr") == "" and bd == sorted([(BID, EXIT, Decimal(10), Decimal(9)), (h64(0x102), h64(0x202), Decimal(5), None)], key=str),
    "U1 입찰별 재료 = 입찰 tx · 종료 tx · 입찰량 · 확인 환불량(환불 > 입찰 = None — 연결 안 함) · 네이티브 지급 = cur_addr ''", [lu[:1] and lu[0].get("cur_addr"), bd])
T.finish()
