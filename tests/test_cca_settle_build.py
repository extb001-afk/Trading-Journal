#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from decimal import Decimal  # noqa: E402

import paths, statefile  # noqa: E402

B, C = "0x" + "b7" * 20, "0x" + "c7" * 20
AUC, TKN = "0x" + "a7" * 20, "0x" + "d7" * 20
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
json.dump({"chains": {}, "wallets": [{"chain": "eth", "address": B, "label": "B"}, {"chain": "eth", "address": C, "label": "C"}],
           "backfill_months": 5}, open(os.path.join(os.environ["TJ_BASE"], "config.json"), "w"))
import acct_norm  # noqa: E402
import db as dbm  # noqa: E402
import histcurve  # noqa: E402
import netpace  # noqa: E402
import sale_match  # noqa: E402
import web  # noqa: E402

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
           "fx_basis": 1300.0, "ex_usd": {}, "ex_ts": {}}, open(paths.state("spot.json"), "w"))


class L:
    def __init__(self):
        p = paths.DB_PATH
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
        self.raw(tx, t, frm=B, to=AUC)

    def refund(self, tx, t, q, asset="eth", seq=0, to=B):
        self.post(tx, seq, t, asset, f"wallet:eth:{to}", q, None, "acq", "PROGRAM_IN")
        if asset == "eth":
            self.raw(tx, t, internal=[{"from": AUC, "to": to, "value": str(int(Decimal(str(q)) * E18))}], frm=to, to=AUC)
        else:
            self.raw(tx, t, tts=[{"from": {"hash": AUC}, "to": {"hash": to}, "token": {"address_hash": USDC, "symbol": "USDC", "decimals": "6"},
                                  "total": {"value": str(int(Decimal(str(q)) * 10 ** 6)), "decimals": "6"}}], frm=to, to=AUC)

    def done(self):
        self.c.commit()
        self.c.close()


BID, EXIT = h64(0x101), h64(0x201)


def cache(bids, token=None, cur=None):
    cur = cur or {"addr": "", "sym": "ETH", "dec": 18}
    un = 10 ** int(cur["dec"])
    bl = []
    for i, a, btx, bts, r, etx, ets, f in bids:
        b9 = {"auction": AUC, "id": i, "amount": str(int(Decimal(str(a)) * un)), "bid_tx": btx, "bid_ts": bts, "filled": str(int(Decimal(str(f)) * E18)),
              "refunded": str(int(Decimal(str(r)) * un)), "exit_tx": etx, "exit_ts": ets}
        if token:
            b9.update({"claim_tx": h64(0x900), "claim_ts": d(3)})
        bl.append(b9)
    json.dump({"owners": {f"eth:{B}": {"t": NOW, "chain": "eth", "owner": B, "bids": bl,
                                         "auctions": {AUC: {"ok": True, "why": "seed", "currency": cur,
                                                            "token": {"addr": TKN, "sym": "TKN", "dec": 18} if token else None}}}}},
              open(paths.state("sale_bids.json"), "w"))


BLD = [None]


def build(prefs=None):
    statefile.atomic_write_json(paths.state("ui_prefs.json"), dict({"plans": {}, "ignored": []}, **(prefs or {})))
    b = web.StateBuilder()
    b.skip_gen_check = True
    conn = dbm.open_db(paths.DB_PATH, readonly=True)
    try:
        f = b._build(conn)["fields"]
    finally:
        conn.close()
    BLD[0] = b
    return f, (b._day_idx or {}).get("tax") or []


def rz_sum(f):
    return round(sum(float(v) for v in (f.get("realizedByDate") or {}).values()), 2)


def unv(f):
    return sorted({str(p.get("sym") or "") for p in f.get("pendings") or [] if str(p.get("kind", "")).startswith("원가미상 매도")})


def eth_rows(rows):
    return sorted((round(float(r.get("_qty", r.get("qty")) or 0), 6), round(float(r.get("_acq", r.get("acq")) or 0), 2),
                   round(float(r.get("_disp", r.get("disp")) or 0), 2)) for r in rows if r.get("sym") == "ETH")


def pay_rows(rows):
    return [r for r in rows if str(r.get("ex") or "").startswith("온체인(토큰 세일)")]


def reset():
    PX["ETH"] = [(0, 1000.0)]
    NO_PX_BEFORE[0] = 0
    pin9 = paths.state("first_seen_px.json")
    if os.path.exists(pin9):
        os.remove(pin9)


def full_refund(token=False, krw=None, refund_t=None):
    reset()
    PX["ETH"] = [(0, 1000.0), (d(1) - 3600, 2000.0), (d(9), 3000.0)]
    lg = L()
    lg.fund(d(-1), 30000)
    lg.swap(d(0), "usdt", 10000, "eth", 10, 10000, krw=krw)
    lg.bid(BID, d(1), 10)
    lg.refund(EXIT, refund_t or d(2), 10)
    lg.swap(d(10), "eth", 10, "usdt", 30000, 30000)
    lg.done()
    cache([(1, 10, BID, d(1), 10, EXIT, refund_t or d(2), 0)], token=token)


full_refund()
res1 = {}
for fs9 in (False, True):
    f1, rows1 = build({"first_seen_px": fs9})
    res1[fs9] = (rz_sum(f1), eth_rows(rows1), unv(f1), len(pay_rows(rows1)), len(f1.get("saleLinks") or []))
    chk(rz_sum(f1) == 20000.0 and eth_rows(rows1) == [(10.0, 10000.0, 30000.0)] and "ETH" not in unv(f1),
        f"S1 전액 환불 · 최초 인식 시가 {'켬' if fs9 else '끔'} = 실현 $20,000 · ETH 명세 취득 $10,000 · 원가미상 매도 없음(종전 끔 = 실현 $0 · 원가미상 10 ETH)",
        res1[fs9])
chk(res1[False] == res1[True], "S1 끔·켬 같은 결과", res1)
chk(res1[False][3] == 0 and res1[False][4] == 0, "S1d 전액 환불 = 결제 코인 처분 행 0(payN 0) · 세일 상자 없음(받은 토큰 원가 로트 없음)", res1[False])
f1x, _r1x = build({"first_seen_px": False})
chk("토큰 세일 환불 · 입찰 원가 복원 ($10,000.00)" in json.dumps(f1x, ensure_ascii=False, default=str) and (f1x.get("_diag") or {}).get("sale_refund_n") == 1,
    "S1 기록 줄 '토큰 세일 환불 · 입찰 원가 복원 ($10,000.00)' · 진단 1건", (f1x.get("_diag") or {}).get("sale_refund_n"))
f1c, rows1c = build({"first_seen_px": False})
chk(rz_sum(f1c) == 20000.0 and eth_rows(rows1c) == res1[False][1], "S1c 다시 빌드 = 같은 값(복원이 쌓이지 않음)", [rz_sum(f1c), eth_rows(rows1c)])
full_refund(token=True)
f1b, rows1b = build({"first_seen_px": False})
chk(rz_sum(f1b) == 20000.0 and eth_rows(rows1b) == [(10.0, 10000.0, 30000.0)] and not (f1b.get("saleLinks") or []),
    "S1b 받은 토큰 정보가 있어도 체결 0 = 같은 값(로트 없음 · 정산 색인으로 복원)", [rz_sum(f1b), eth_rows(rows1b)])

reset()
NO_PX_BEFORE[0] = d(0) + 3600
PX["ETH"] = [(0, 1000.0), (d(1) - 3600, 2000.0), (d(9), 3000.0)]
lg = L()
lg.fund(d(-1), 30000)
lg.eth_in_nocost(d(0), 5)
lg.swap(d(0) + 7200, "usdt", 5000, "eth", 5, 5000)
lg.bid(BID, d(1), 10)
lg.refund(EXIT, d(2), 10)
lg.swap(d(10), "eth", 10, "usdt", 30000, 30000)
lg.done()
cache([(1, 10, BID, d(1), 10, EXIT, d(2), 0)])
f2, rows2 = build({"first_seen_px": False})
chk(eth_rows(rows2) == [(5.0, 5000.0, 15000.0)] and "ETH" in unv(f2) and rz_sum(f2) == 10000.0,
    "S2 확인 5 ETH 만 원가 $5,000 복원(실현 $10,000) · 원가 미상 5 ETH 는 원가미상 매도 그대로(지어내지 않음)", [eth_rows(rows2), unv(f2), rz_sum(f2)])

reset()
PX["ETH"] = [(0, 1000.0), (d(1) - 3600, 2000.0), (d(9), 3000.0)]
lg = L()
lg.fund(d(-1), 30000)
lg.swap(d(0), "usdt", 10000, "eth", 10, 10000)
lg.bid(BID, d(1), 10)
lg.refund(EXIT, d(2), 9)
lg.swap(d(10), "eth", 9, "usdt", 27000, 27000)
lg.done()
cache([(1, 10, BID, d(1), 9, EXIT, d(2), 1000)], token=False)
f3, rows3 = build({"first_seen_px": False})
chk(eth_rows(rows3) == [(9.0, 9000.0, 27000.0)] and "ETH" not in unv(f3) and not pay_rows(rows3),
    "S3 받은 토큰 미상 부분 환불 = 환불 9 ETH 원가 $9,000 복원 · 사용 1 ETH 처분 없음(받은 토큰 원가 없음)", [eth_rows(rows3), unv(f3), len(pay_rows(rows3))])

reset()
PX["ETH"] = [(0, 1000.0), (d(1) - 3600, 2000.0), (d(9), 3000.0)]
lg = L()
lg.fund(d(-1), 30000)
lg.swap(d(0), "usdt", 10000, "eth", 10, 10000)
lg.bid(BID, d(1), 10)
lg.refund(EXIT, d(2), 10, to=C)
lg.done()
cache([(1, 10, BID, d(1), 10, EXIT, d(2), 0)])
f4, _rows4 = build({"first_seen_px": False})
chk((f4.get("_diag") or {}).get("sale_refund_n") == 0, "S4 종료 tx 라도 입찰자 아닌 내 지갑 수령 = 연결 안 함", (f4.get("_diag") or {}).get("sale_refund_n"))
reset()
lg = L()
lg.fund(d(-1), 30000)
lg.swap(d(0), "usdt", 10000, "eth", 10, 10000)
lg.bid(BID, d(1), 10)
lg.refund(EXIT, d(2), 10, asset="usdc")
lg.done()
cache([(1, 10, BID, d(1), 10, EXIT, d(2), 0)])
f4b, _rows4b = build({"first_seen_px": False})
chk((f4b.get("_diag") or {}).get("sale_refund_n") == 0, "S4b ETH 입찰인데 종료 tx 로 USDC 수령 = 연결 안 함(지급 자산 다름)", (f4b.get("_diag") or {}).get("sale_refund_n"))

full_refund()
lg = L.__new__(L)
lg.c = dbm.open_db(paths.DB_PATH)
lg.A = {"eth": (lg.c.execute("SELECT asset_id FROM assets WHERE kind='native'").fetchone()[0], 18)}
lg.A["usdt"] = (lg.c.execute("SELECT asset_id FROM assets WHERE symbol='USDT'").fetchone()[0], 6)
lg.n = 90
lg.refund(EXIT, d(2), 10, seq=1)
lg.swap(d(11), "eth", 10, "usdt", 30000, 30000)
lg.done()
f5, rows5 = build({"first_seen_px": False})
f5b, rows5b = build({"first_seen_px": False})
chk(eth_rows(rows5) == [(10.0, 10000.0, 30000.0)] and eth_rows(rows5b) == eth_rows(rows5) and "ETH" in unv(f5),
    "S5 같은 환불 두 줄(20 ETH) = 확인 환불량 10 ETH 까지만 $10,000 한 번(나머지 10 = 원가 미확인) · 다시 빌드 같음", [eth_rows(rows5), unv(f5)])

full_refund(krw=13_000_000)
for fs9 in (False, True):
    f6, rows6 = build({"first_seen_px": fs9})
    er6 = [r for r in rows6 if r.get("sym") == "ETH"]
    chk(len(er6) == 1 and abs(float(er6[0].get("_akr") or 0) - 13_000_000) < 5,
        f"S6 원화 취득가 = 원래 원화 ₩13,000,000(환불 시각 환율로 다시 매기지 않음 · {'켬' if fs9 else '끔'})", [r.get("_akr") for r in er6])

full_refund(refund_t=d(1) + 7200)
for fs9 in (False, True):
    f7, rows7 = build({"first_seen_px": fs9})
    chk(eth_rows(rows7) == [(10.0, 10000.0, 30000.0)] and rz_sum(f7) == 20000.0,
        f"S7 입찰 2시간 뒤 전액 환불 = 원가 $10,000 한 번(이중 $20,000 아님 · {'켬' if fs9 else '끔'})", [eth_rows(rows7), rz_sum(f7)])

reset()
PX["ETH"] = [(0, 1000.0), (d(2), 2000.0), (d(9), 3000.0)]
lg = L()
lg.fund(d(-1), 30000)
lg.swap(d(0), "usdt", 4000, "eth", 4, 4000)
lg.bid(h64(0x111), d(1), 4)
lg.swap(d(2), "usdt", 12000, "eth", 6, 12000)
lg.bid(h64(0x112), d(3), 6)
lg.refund(h64(0x213), d(4), 10)
lg.swap(d(10), "eth", 10, "usdt", 30000, 30000)
lg.done()
cache([(1, 4, h64(0x111), d(1), 4, h64(0x213), d(4), 0), (2, 6, h64(0x112), d(3), 6, h64(0x213), d(4), 0)])
f8, rows8 = build({"first_seen_px": False})
chk(eth_rows(rows8) == [(10.0, 16000.0, 30000.0)] and rz_sum(f8) == 14000.0,
    "S8 두 입찰을 한 종료 tx 로 환불 = 입찰별 원가 $4,000 + $12,000 = $16,000 · 실현 $14,000", [eth_rows(rows8), rz_sum(f8)])

full_refund()
f9, rows9 = build({"first_seen_px": False, "sale_link_off": [f"eth:{AUC}:{B}"]})
chk((f9.get("_diag") or {}).get("sale_refund_n") == 0 and "ETH" in unv(f9),
    "S9 오너가 끈 경매(sale_link_off) = 정산 복원 안 함(끔 = 종전 원가 미확인)", [(f9.get("_diag") or {}).get("sale_refund_n"), unv(f9)])
f9b, rows9b = build({"first_seen_px": True, "sale_link_off": [f"eth:{AUC}:{B}"]})
chk(eth_rows(rows9b) == [(10.0, 10000.0, 30000.0)], "S9b 끈 경매 + 최초 인식 시가 켬 = 종전 '돌아온 코인' 승계 그대로($10,000)", eth_rows(rows9b))

reset()
PX["ETH"] = [(0, 1000.0), (d(1) - 3600, 2000.0), (d(9), 3000.0)]
lg = L()
lg.fund(d(-1), 30000)
lg.swap(d(0), "usdt", 10000, "eth", 10, 10000)
lg.bid(h64(0x121), d(1), 5)
lg.bid(h64(0x122), d(1), 5)
lg.refund(h64(0x221), d(2), 5)
lg.refund(h64(0x222), d(2), 3)
lg.post(h64(0x900), 0, d(3), "tkn", f"wallet:eth:{B}", 1000, None, "acq", "PROGRAM_IN")
lg.raw(h64(0x900), d(3), tts=[{"from": {"hash": AUC}, "to": {"hash": B}, "token": {"address_hash": TKN, "symbol": "TKN", "decimals": "18"},
                               "total": {"value": str(1000 * E18), "decimals": "18"}}])
lg.swap(d(10), "eth", 8, "usdt", 24000, 24000)
lg.swap(d(11), "tkn", 1000, "usdt", 5000, 5000)
lg.done()
cache([(1, 5, h64(0x121), d(1), 5, h64(0x221), d(2), 0), (2, 5, h64(0x122), d(1), 3, h64(0x222), d(2), 1000)], token=True)
f10, rows10 = build({"first_seen_px": False})
chk(rz_sum(f10) == 19000.0 and eth_rows(rows10) == [(2.0, 2000.0, 4000.0), (8.0, 8000.0, 24000.0)] and (f10.get("_diag") or {}).get("sale_refund_n") == 2,
    "S10 낙찰 + 전액 환불 입찰 한 경매 = 로트 경로 그대로(환불 2건 · 사용분 2 ETH 처분 · 합 $19,000 = 현금 증가)", [rz_sum(f10), eth_rows(rows10)])


def rec(bids, ok=True, cur=None):
    cur = cur or {"addr": "", "sym": "ETH", "dec": 18}
    return {"owners": {f"eth:{B}": {"t": 1, "chain": "eth", "owner": B, "bids": bids,
                                    "auctions": {AUC: {"ok": ok, "currency": cur, "token": None}}}}}


def bid9(i, amt, ref, exit_tx=EXIT, filled="0", **kw):
    b9 = {"auction": AUC, "id": i, "amount": str(amt), "bid_tx": h64(0x100 + i), "bid_ts": 1, "refunded": str(ref), "exit_tx": exit_tx, "exit_ts": 2}
    if filled is not None:
        b9["filled"] = filled
    b9.update(kw)
    return b9


u1 = sale_match.build_settlements(rec([bid9(1, 10 * E18, 10 * E18), bid9(2, 5 * E18, 0), bid9(3, 5 * E18, 6 * E18), bid9(4, 5 * E18, 5 * E18, exit_tx=""),
                                       bid9(5, 5 * E18, 5 * E18, filled=None)]))
chk(len(u1) == 1 and [(b["id"], b["amount"], b["refunded"]) for b in u1[0]["bid_d"]] == [(1, Decimal(10), Decimal(10))] and u1[0]["cur_addr"] == ""
    and u1[0]["id"] == f"eth:{AUC}:{B}" and u1[0]["bidder"] == B,
    "U1 정산 재료 = 종료 증거·0 < 환불 ≤ 입찰 인 입찰만(환불 0 · 환불 > 입찰 · 종료 tx 없음 · 미종료 제외) · 네이티브 지급 = ''", u1)
chk(sale_match.build_settlements(rec([bid9(1, 10 * E18, 10 * E18)]), skip={f"eth:{AUC}:{B}"}) == []
    and sale_match.build_settlements(rec([bid9(1, 10 * E18, 10 * E18)]), off=[f"eth:{AUC}:{B}"]) == []
    and sale_match.build_settlements(rec([bid9(1, 10 * E18, 10 * E18)], ok=False)) == [],
    "U2 로트 있는 경매(skip)·끈 경매(off)·확인 안 된 경매 = 정산 재료 없음")
u3 = sale_match.build_settlements(rec([bid9(1, 10 * 10 ** 6, 4 * 10 ** 6)], cur={"addr": USDC, "sym": "USDC", "dec": 6}))
chk(len(u3) == 1 and u3[0]["bid_d"][0]["amount"] == Decimal(10) and u3[0]["bid_d"][0]["refunded"] == Decimal(4) and u3[0]["cur_addr"] == USDC,
    "U3 통화 decimals 6 · 토큰 지급 = 주소", u3)
T.finish()
