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

B = "0x" + "b8" * 20
X = "0x" + "a8" * 20
TKN = "0x" + "d8" * 20
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
json.dump({"chains": {}, "wallets": [{"chain": "eth", "address": B, "label": "B"}], "backfill_months": 5},
          open(os.path.join(os.environ["TJ_BASE"], "config.json"), "w"))
import acct_norm  # noqa: E402
import db as dbm  # noqa: E402
import histcurve  # noqa: E402
import netpace  # noqa: E402
import web  # noqa: E402

chk = T.chk
for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker", "_rabby_worker"):
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
FX_CORE = os.path.join(paths.STATE_DIR, "px_cache_core.json")


def set_fx(pts):
    if not pts:
        if os.path.exists(FX_CORE):
            os.remove(FX_CORE)
        return
    json.dump({"fx": {str(int(t) * 1000 // 60000 * 60000): r for t, r in pts}, "candle": {}}, open(FX_CORE, "w"))


class L:
    def __init__(self):
        p = paths.DB_PATH
        for sfx in ("", "-wal", "-shm"):
            if os.path.exists(p + sfx):
                os.remove(p + sfx)
        self.c = dbm.open_db(p)
        self.A = {}
        grp = {}
        for key, kind, chain, addr, sym, dec in (("eth", "native", "eth", None, "ETH", 18), ("usdt", "token", "eth", USDT, "USDT", 6),
                                                 ("usdc", "token", "eth", USDC, "USDC", 6), ("tkn", "token", "eth", TKN, "TKN", 18),
                                                 ("gusdt", "exchange_currency", None, None, "USDT", 8)):
            gn = sym if kind != "exchange_currency" else f"{sym}#5"
            if gn not in grp:
                self.c.execute("INSERT INTO asset_groups (name) VALUES (?)", (gn,))
                grp[gn] = self.c.execute("SELECT group_id FROM asset_groups WHERE name=?", (gn,)).fetchone()[0]
            self.c.execute("INSERT INTO assets (kind, chain, address, symbol, decimals, confirmed, group_id) VALUES (?,?,?,?,?,1,?)",
                           (kind, chain, addr, sym, dec, grp[gn]))
            self.A[key] = (self.c.execute("SELECT last_insert_rowid()").fetchone()[0], dec)
        self.n = 0

    def post(self, sid, seq, t, a, loc, qty, usd, lk, ev, krw=None, sk="chain_tx", ns="eth"):
        aid, dec = self.A[a]
        self.c.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd,"
                       " cost_krw, leg_kind, event, classifier_ver) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,3)",
                       (sk, ns, sid, seq, t, aid, loc, str(int(Decimal(str(qty)) * (Decimal(10) ** dec))), None if usd is None else str(usd),
                        None if krw is None else str(krw), lk, ev))

    def raw(self, tx, t, tts=(), internal=(), frm=B, to=X):
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
        self.post(tx, 0, t, a_out, f"wallet:eth:{B}", -Decimal(str(q_out)), usd, "disp", "SWAP", krw=krw)
        self.post(tx, 1, t, a_in, f"wallet:eth:{B}", q_in, usd, "acq", "SWAP", krw=krw)
        self.raw(tx, t)
        return tx

    def send(self, t, q, asset, usd, krw=None):
        tx = self.tx()
        self.post(tx, 0, t, asset, f"wallet:eth:{B}", -Decimal(str(q)), None, "move_out", "TRANSFER_OUT")
        self.post(tx, 1, t, asset, f"out:eth:{X}", q, usd, "move_in", "TRANSFER_OUT", krw=krw)
        self.raw(tx, t, frm=B, to=X)
        return f"chain_tx|eth|{tx}|1"

    def recv(self, t, q, asset="tkn", frm=X):
        tx = self.tx()
        aid, dec = self.A[asset]
        self.post(tx, 0, t, asset, f"wallet:eth:{B}", q, None, "acq", "TRANSFER_IN")
        ca = {"tkn": TKN, "usdc": USDC, "usdt": USDT}.get(asset)
        if ca:
            self.raw(tx, t, tts=[{"from": {"hash": frm}, "to": {"hash": B}, "token": {"address_hash": ca, "symbol": asset.upper(), "decimals": str(dec)},
                                  "total": {"value": str(int(Decimal(str(q)) * 10 ** dec)), "decimals": str(dec)}}], frm=frm, to=B)
        else:
            self.raw(tx, t, internal=[{"from": frm, "to": B, "value": str(int(Decimal(str(q)) * E18))}], frm=frm, to=B)
        return {"key": f"chain_tx|eth|{tx}|0", "asset": f"{'native' if asset == 'eth' else 'token'}:eth:{(ca or 'eth').lower()}",
                "qb": str(int(Decimal(str(q)) * (Decimal(10) ** dec))), "where": f"w:{B}"}

    def ex_dep(self, t, q, uid="gate:D1"):
        self.post(uid, 0, t, "gusdt", "exchange:gate", q, None, "move_in", "EXF_DEPOSIT", sk="exchange", ns="gate:deposit")
        self.c.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('gate','deposit',?,1,?,?)",
                       (uid, json.dumps({"uuid": uid, "currency": "USDT", "amount": str(q), "fee": "0", "txid": "0x" + "d9" * 32, "state": "ACCEPTED",
                                         "network": "ETH"}), t))

    def ex_wd(self, t, amt, fee, uid="gate:W1", to=X):
        self.post(uid, 0, t, "gusdt", "exchange:gate", -Decimal(str(amt)), None, "move_out", "EXF_WITHDRAW", sk="exchange", ns="gate:withdraw")
        self.c.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('gate','withdraw',?,1,?,?)",
                       (uid, json.dumps({"uuid": uid, "currency": "USDT", "amount": str(amt), "fee": str(fee), "txid": "0x" + "e9" * 32, "state": "DONE",
                                         "address": to, "network": "ETH"}), t))

    def done(self):
        self.c.commit()
        self.c.close()


OFP = web.StateBuilder.OUTFLOW_PATH


def link(tokens=(), refunds=(), excl=()):
    ls = [dict(t9, kind="tokens", lts=1) for t9 in tokens] + [dict(r9, kind="refund", lts=2) for r9 in refunds]
    dec = {X: {"verdict": "external", "category": "세일 참가금", "links": ls}}
    if excl:
        dec[X]["excludeLegs"] = list(excl)
    statefile.atomic_write_json(OFP, {"decisions": dec})
    return dec


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


def rows_of(rows, sym, pay=None):
    return sorted((round(float(r.get("_qty", r.get("qty")) or 0), 6), round(float(r.get("_acq", r.get("acq")) or 0), 2),
                   round(float(r.get("_disp", r.get("disp")) or 0), 2)) for r in rows
                  if r.get("sym") == sym and (pay is None or str(r.get("ex") or "").startswith("온체인(토큰 세일)") == pay))


def reset():
    PX["ETH"] = [(0, 1000.0)]
    NO_PX_BEFORE[0] = 0
    set_fx([])
    pin9 = paths.state("first_seen_px.json")
    if os.path.exists(pin9):
        os.remove(pin9)
    if os.path.exists(OFP):
        os.remove(OFP)


def eth_case(v, refund=0, nocost=False, half=False):
    reset()
    PX["ETH"] = [(0, 1000.0), (d(1) - 3600, float(v)), (d(9), 3000.0)]
    lg = L()
    lg.fund(d(-1), 1000)
    if nocost:
        NO_PX_BEFORE[0] = d(0) + 3600
        if half:
            lg.eth_in_nocost(d(0), "0.5")
            lg.swap(d(0) + 7200, "usdt", 500, "eth", "0.5", 500)
        else:
            lg.eth_in_nocost(d(0), 1)
    else:
        lg.swap(d(0), "usdt", 1000, "eth", 1, 1000)
    lg.send(d(1), 1, "eth", v)
    rf = [lg.recv(d(2), refund, "usdc")] if refund else []
    tk = lg.recv(d(3), 1000)
    lg.swap(d(10), "tkn", 1000, "usdt", 3000, 3000)
    lg.done()
    link([tk], rf)
    return 3000 + refund - 1000


for v in (500, 1000, 2000):
    cash = eth_case(v)
    for fs9 in (True, False):
        f1, rows1 = build({"first_seen_px": fs9})
        chk(rz_sum(f1) == 2000.0 and cash == 2000 and rows_of(rows1, "ETH") == [(1.0, 1000.0, float(v))]
            and rows_of(rows1, "TKN") == [(1000.0, float(v), 3000.0)] and unv(f1) == [],
            f"M1 보낼 때 ${v:,} · 최초 인식 시가 {'켬' if fs9 else '끔'} = 실현 합 $2,000 = 현금 이익 · ETH 처분(1 · $1,000 · ${v:,}) · TKN 원가 ${v:,} · 원가미상 없음"
            f"(종전 ${3000 - v:,})", [rz_sum(f1), rows_of(rows1, "ETH"), rows_of(rows1, "TKN"), unv(f1)])
f1b, rows1b = build()
chk(rz_sum(f1b) == 2000.0 and rows_of(rows1b, "ETH") == [(1.0, 1000.0, 2000.0)], "M1 다시 빌드 = 같은 값(처분이 쌓이지 않음)", [rz_sum(f1b), rows_of(rows1b, "ETH")])
pe1 = [e for p in f1b.get("positions") or [] for e in p.get("events") or [] if "토큰 세일 대금 지불" in str(e.get("d") or "")]
chk(len(pe1) == 1 and pe1[0].get("src") == "w:" + B and "보낸 내역 참가금 연결" in str(pe1[0].get("d")) and "TKN" in str(pe1[0].get("d")),
    "M1r 기록 줄 '토큰 세일 대금 지불 · ETH → TKN (보낸 내역 참가금 연결 …)' · 소스 = 보낸 지갑", [(e.get("d"), e.get("src")) for e in pe1])
da1 = f1b.get("dayActs") or {}
a1 = da1.get(ISO(d(3))) or da1.get(ISO(d(3))[5:]) or {}
chk(a1.get("pay") == 1, "M1r 일별 건수(첫 수령일) = 지불 1", a1)
rc1 = BLD[0].receipt(ISO(d(3)), "ETH") or {}
chk(((rc1.get("sell") or {}).get("pay") or {}).get("n") == 1 and (rc1.get("realized") or {}).get("usd") == 1000.0,
    "M1r 영수증(첫 수령일 · ETH) = 지불 1건 · 실현 $1,000", [rc1.get("sell"), rc1.get("realized")])
tr1 = BLD[0].tax_rows(ISO(d(3))[:7], "ETH") or {}
chk(any(abs(float(r.get("xd") or 0) - 2000.0) < 0.01 and abs(float(r.get("xa") or 0) - 1000.0) < 0.01 for r in tr1.get("rows") or []),
    "M1r 명세 API 행(양도 $2,000 · 취득 $1,000)", [(r.get("sold"), r.get("xa"), r.get("xd")) for r in tr1.get("rows") or []])
ofs1 = (getattr(BLD[0], "_of_man_state", None) or {}).get(X) or {}
chk(ofs1.get("costUsd") == Decimal(2000), "M1 수동 연결 상태 = 원가 $2,000 그대로(받은 토큰 원가 규칙 무변)", ofs1.get("costUsd"))

FX2 = [(d(-1), 1300.0), (d(0), 1300.0), (d(1), 1500.0), (d(2), 1500.0), (d(3), 1500.0), (d(10), 1500.0)]


def stable_case(refund=0, swap_ctrl=False, sell=None):
    reset()
    set_fx(FX2)
    lg = L()
    lg.fund(d(-1), 10000, a="usdc")
    if swap_ctrl:
        lg.swap(d(1), "usdc", 10000, "tkn", 1000, 10000, krw=15_000_000)
    else:
        lg.send(d(1), 10000, "usdc", 10000, krw=15_000_000)
    rf = [lg.recv(d(2), refund, "usdc")] if refund else []
    tk = None if swap_ctrl else lg.recv(d(3), 1000)
    lg.swap(d(10), "tkn", 1000, "usdt", sell or (10000 - refund), sell or (10000 - refund))
    lg.done()
    if not swap_ctrl:
        link([tk], rf)


def st_rows(rows):
    return sorted((round(float(r.get("_qty") or 0), 4), round(float(r.get("_akr") or 0)), round(float(r.get("_disp") or 0) * float(r.get("rate") or 0)),
                   round(float(r.get("_sfx") or 0)), r.get("tk")) for r in rows if r.get("sym") == "USDC")


stable_case(swap_ctrl=True)
fc2, rowsc2 = build()
stable_case()
f2, rows2 = build()
chk(st_rows(rows2) == st_rows(rowsc2) and st_rows(rows2) == [(10000.0, 13_000_000, 15_000_000, 2_000_000, "st")] and abs(rz_sum(f2)) < 0.01,
    "M2 USDC 10,000 지급(₩1,300 취득 → ₩1,500 지급) = 일반 스왑과 같은 명세 · 원화 환차 ₩2,000,000 · USD 실현 0(종전 명세 0건)",
    [st_rows(rows2), st_rows(rowsc2), rz_sum(f2)])
tk2 = [r for r in rows2 if r.get("sym") == "TKN"]
chk(len(tk2) == 1 and abs(float(tk2[0].get("_akr") or 0) - 15_000_000) < 5, "M2 받은 토큰 원화 취득가 = 지급 원화 ₩15,000,000(이음매 0)", [r.get("_akr") for r in tk2])

stable_case(refund=4000)
f3, rows3 = build()
chk(rows_of(rows3, "USDC", pay=True) == [(6000.0, 6000.0, 6000.0)] and abs(rz_sum(f3)) < 0.01,
    "M3 USDC 10,000 지급 · 4,000 환불(같은 스테이블) = 사용분 6,000 만 처분 · 반환 4,000 은 처분 아님", [rows_of(rows3, "USDC", pay=True), rz_sum(f3)])
stable_case(refund=10000, sell=500)
f3b, rows3b = build()
chk(rows_of(rows3b, "USDC", pay=True) == [] and rz_sum(f3b) == 500.0, "M3b 전액 환불 = 결제 코인 처분 0(토큰 원가 0 · 매도 $500 = 실현)",
    [rows_of(rows3b, "USDC", pay=True), rz_sum(f3b)])

cash = eth_case(2000, refund=500)
f4, rows4 = build()
chk(rz_sum(f4) == float(cash) == 2500.0 and rows_of(rows4, "ETH") == [(1.0, 1000.0, 2000.0)] and rows_of(rows4, "TKN") == [(1000.0, 1500.0, 3000.0)],
    "M4 ETH 지급 · USDC 500 환불 = ETH 전량 처분(대가 $2,000 = 토큰 원가 $1,500 + 환불 $500) · 실현 합 $2,500 = 현금 이익", [rz_sum(f4), rows_of(rows4, "ETH"), rows_of(rows4, "TKN")])

eth_case(2000, nocost=True)
f5, rows5 = build({"first_seen_px": False})
chk(rows_of(rows5, "ETH") == [] and "ETH" in unv(f5) and rz_sum(f5) == 1000.0,
    "M5 원가 미상 1 ETH 지급 = 처분 몫 원가미상 매도(명시적 미확인 · 지어내지 않음) · 확정 실현 = 토큰 $1,000", [rows_of(rows5, "ETH"), unv(f5), rz_sum(f5)])
eth_case(2000, nocost=True, half=True)
f5b, rows5b = build({"first_seen_px": False})
chk(rows_of(rows5b, "ETH") == [(0.5, 500.0, 1000.0)] and "ETH" in unv(f5b) and rz_sum(f5b) == 1500.0,
    "M5b 확인 0.5(원가 $500 → 대가 $1,000) + 미확인 0.5(원가미상) · 실현 $1,500", [rows_of(rows5b, "ETH"), unv(f5b), rz_sum(f5b)])

reset()
set_fx([(d(-1), 1300.0), (d(0), 1300.0), (d(1), 1500.0), (d(3), 1500.0), (d(10), 1500.0)])
lg = L()
lg.ex_dep(d(-1), 1010)
lg.ex_wd(d(1), 1010, 10)
tk6 = lg.recv(d(3), 1000)
lg.swap(d(10), "tkn", 1000, "usdt", 1000, 1000)
lg.done()
link([tk6])
f6, rows6 = build()
p6 = [r for r in rows6 if r.get("sym") == "USDT" and str(r.get("ex") or "").startswith("온체인(토큰 세일)")]
o6 = [r for r in rows6 if r.get("sym") == "USDT" and not str(r.get("ex") or "").startswith("온체인(토큰 세일)")]
chk(len(p6) == 1 and abs(float(p6[0]["_qty"]) - 1000) < 1e-6 and abs(float(p6[0].get("_sfx") or 0) - 200_000) < 5,
    "M6 게이트 출금 1,010(수수료 10) 참가 = 원금 1,000 만 처분 · 원화 환차 ₩200,000(₩1,300 → ₩1,500)", [(r.get("_qty"), r.get("_akr"), r.get("_sfx"), r.get("ex")) for r in rows6])
chk(sum(float(r.get("_qty") or 0) for r in o6) <= 10.0001 and all(abs(float(r.get("_qty") or 0) - 1000) > 1 for r in o6),
    "M6 출금 수수료는 수수료 처분 행으로만(참가금 처분과 중복 0)", [(r.get("_qty"), r.get("ex")) for r in o6])
chk(abs(rz_sum(f6) + 10) < 0.5, "M6 USD 실현 = −$10(출금 수수료 비용 한 번 · 참가금 처분·토큰 매도는 스테이블 액면이라 0)", rz_sum(f6))

reset()
PX["ETH"] = [(0, 1000.0), (d(1) - 3600, 2000.0), (d(9), 3000.0)]
lg = L()
lg.fund(d(-1), 3000)
lg.swap(d(0), "usdt", 3000, "eth", 3, 3000)
lg.send(d(1), 1, "eth", 2000)
k7x = lg.send(d(1) + 600, 1, "eth", 2000)
tk7 = lg.recv(d(3), 1000)
lg.send(d(5), 1, "eth", 2000)
lg.swap(d(10), "tkn", 1000, "usdt", 3000, 3000)
lg.done()
link([tk7], excl=[k7x])
f7, rows7 = build({"first_seen_px": False})
chk(rows_of(rows7, "ETH") == [(1.0, 1000.0, 2000.0)] and rows_of(rows7, "TKN") == [(1000.0, 2000.0, 3000.0)],
    "M7 참가금 = 제외 안 한 첫 레그 1 ETH 만 처분 · 제외 레그·수령 뒤 송신은 처분 안 함(외부 유출 그대로)", [rows_of(rows7, "ETH"), rows_of(rows7, "TKN")])

reset()
PX["ETH"] = [(0, 1000.0), (d(1) - 3600, 2000.0), (d(9), 3000.0)]
lg = L()
lg.fund(d(-1), 1000)
lg.fund(d(-1), 1000, a="usdc")
lg.swap(d(0), "usdt", 1000, "eth", 1, 1000)
lg.send(d(1), 1, "eth", 2000)
lg.send(d(1) + 60, 1000, "usdc", 1000)
rf8 = lg.recv(d(2), 500, "usdc")
tk8 = lg.recv(d(3), 1000)
lg.swap(d(10), "tkn", 1000, "usdt", 3000, 3000)
lg.done()
link([tk8], [rf8])
f8, rows8 = build()
chk(rows_of(rows8, "ETH", pay=True) == [] and rows_of(rows8, "USDC", pay=True) == [] and rows_of(rows8, "TKN") == [(1000.0, 2500.0, 3000.0)],
    "M8 ETH+USDC 지급 · USDC 환불 = 어느 레그가 환불받았는지 단정 못 함 → 처분 보류 · 토큰 원가 $2,500 그대로(종전)", [rows_of(rows8, "ETH"), rows_of(rows8, "TKN")])
chk(((getattr(BLD[0], "_of_man_state", None) or {}).get(X) or {}).get("payHold") == "mixed_refund", "M8 보류 사유 = mixed_refund(진단)",
    ((getattr(BLD[0], "_of_man_state", None) or {}).get(X) or {}).get("payHold"))

reset()
PX["ETH"] = [(0, 1000.0), (d(1) - 3600, 2000.0), (d(9), 3000.0)]
lg = L()
lg.fund(d(-1), 2000)
lg.swap(d(0), "usdt", 2000, "eth", 2, 2000)
lg.send(d(1), 2, "eth", 4000)
lg.recv(d(2), 1, "eth")
tk9 = lg.recv(d(3), 1000)
lg.swap(d(10), "tkn", 1000, "usdt", 3000, 3000)
lg.done()
link([tk9])
f9, rows9 = build({"first_seen_px": True})
chk(rows_of(rows9, "ETH", pay=True) == [] and ((getattr(BLD[0], "_of_man_state", None) or {}).get(X) or {}).get("payHold") == "returned",
    "M9 보낸 ETH 일부가 같은 목적지에서 이미 돌아와 원가 승계 = 처분 보류(두 번 되돌리지 않음 · 종전)", rows_of(rows9, "ETH"))

reset()
PX["ETH"] = [(0, 1000.0), (d(1) - 3600, 2000.0), (d(2) - 3600, 4000.0), (d(9), 3000.0)]
lg = L()
lg.fund(d(-1), 2000)
lg.swap(d(0), "usdt", 2000, "eth", 2, 2000)
lg.send(d(1), 1, "eth", 2000)
lg.send(d(2), 1, "eth", 4000)
tka = lg.recv(d(3), 400)
tkb = lg.recv(d(4), 600)
lg.swap(d(10), "tkn", 1000, "usdt", 9000, 9000)
lg.done()
link([tka, tkb])
f11, rows11 = build()
chk(rows_of(rows11, "ETH") == [(1.0, 1000.0, 2000.0), (1.0, 1000.0, 4000.0)] and rz_sum(f11) == 7000.0 and unv(f11) == [],
    "M11 지급 레그 2개(보낸 때 $2,000 · $4,000) · 토큰 400 + 600 분할 수령 = 레그별 처분 1번씩 · 실현 합 $7,000 = 현금 이익", [rows_of(rows11, "ETH"), rz_sum(f11)])
st11 = ((getattr(BLD[0], "_of_man_state", None) or {}).get(X) or {}).get("pay") or {}
chk(st11.get("n") == 2 and st11.get("usd") == 6000.0 and st11.get("rz") == 4000.0, "M11 수동 연결 상태 처분 요약 = 2건 · 대가 $6,000 · 실현 $4,000", st11)

reset()
PX["ETH"] = [(0, 1000.0), (d(1) + 3600, 3000.0), (d(9), 5000.0)]
lg = L()
lg.fund(d(-1), 4000)
lg.swap(d(0), "usdt", 1000, "eth", 1, 1000)
k12x = lg.send(d(1), 1, "eth", 1000)
lg.swap(d(1) + 7200, "usdt", 3000, "eth", 1, 3000)
lg.send(d(2), 1, "eth", 4000)
tk12 = lg.recv(d(3), 1000)
lg.recv(d(5), 1, "eth")
lg.swap(d(10), "tkn", 1000, "usdt", 6000, 6000)
lg.swap(d(11), "eth", 1, "usdt", 5000, 5000)
lg.done()
link([tk12], excl=[k12x])
f12, rows12 = build({"first_seen_px": True})
chk(rz_sum(f12) == 7000.0 and rows_of(rows12, "ETH", pay=True) == [(1.0, 3000.0, 4000.0)] and rows_of(rows12, "ETH", pay=False) == [(1.0, 1000.0, 5000.0)],
    "M12 제외 레그($1,000)와 참가 레그($3,000)가 같은 돌아온 코인 풀 = 처분은 참가 레그 원가만 풀에서 뺌 · 돌아온 1 ETH 원가 $1,000 · 실현 합 $7,000 = 현금 이익(종전 평균 차감 $6,000)",
    [rz_sum(f12), rows_of(rows12, "ETH")])

reset()
set_fx([(d(-1), 1300.0), (d(0), 1300.0), (d(1), 1500.0), (d(2), 1500.0), (d(3), 1500.0), (d(10), 1500.0)])
lg = L()
lg.ex_dep(d(-1), 10000)
lg.ex_wd(d(1), 10000, 0)
rf13 = lg.recv(d(2), 4000, "usdt")
tk13 = lg.recv(d(3), 1000)
lg.swap(d(10), "tkn", 1000, "usdt", 6000, 6000)
lg.done()
link([tk13], [rf13])
f13, rows13 = build()
p13 = [r for r in rows13 if r.get("sym") == "USDT" and str(r.get("ex") or "").startswith("온체인(토큰 세일)")]
chk(len(p13) == 1 and abs(float(p13[0]["_qty"]) - 6000) < 1e-6 and abs(float(p13[0].get("_sfx") or 0) - 1_200_000) < 5,
    "M13 거래소 USDT 10,000 참가 · 온체인 USDT 4,000 환불 = 같은 스테이블 → 사용분 6,000 만 처분 · 원화 환차 ₩1,200,000(종전 10,000 · ₩2,000,000)",
    [(r.get("_qty"), r.get("_sfx")) for r in p13])

eth_case(2000)
before10 = open(OFP, "rb").read()
c10 = dbm.open_db(paths.DB_PATH, readonly=True)
n10 = c10.execute("SELECT COUNT(*), COALESCE(SUM(CAST(qty_base AS REAL)), 0) FROM postings").fetchone()
c10.close()
build()
build()
c10 = dbm.open_db(paths.DB_PATH, readonly=True)
n10b = c10.execute("SELECT COUNT(*), COALESCE(SUM(CAST(qty_base AS REAL)), 0) FROM postings").fetchone()
c10.close()
chk(open(OFP, "rb").read() == before10 and tuple(n10) == tuple(n10b), "M10 빌드가 판정 파일(구 수동 링크)·원장을 바꾸지 않음(매 빌드 재계산)", [tuple(n10), tuple(n10b)])
T.finish()
