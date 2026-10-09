#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import common

W = "0x" + "a1" * 20
json.dump({"chains": {}, "wallets": [{"chain": "katana", "address": W}], "backfill_months": 5},
          open(os.path.join(os.environ["TJ_BASE"], "config.json"), "w"))
import core
import db as dbm
import netpace
import pricing
import spamguard
import web

FS_EX = getattr(web, "FS_EX", " · 최초 인식 시가")
chk = T.chk
for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker"):
    if hasattr(web.StateBuilder, _m):
        setattr(web.StateBuilder, _m, lambda self: None)
netpace.wait = lambda url, now=None, sleep=None: None
web.pricing._gj = lambda url, timeout=10.0: None
KST = timezone(timedelta(hours=9))
NOW = int(time.time())
DAY = 86400
T1 = int((datetime.fromtimestamp(NOW, KST).replace(hour=10, minute=0, second=0, microsecond=0) - timedelta(days=40)).timestamp())

KAT_KV = {ca: s for ca, s in (pricing.STABLE_CAS.get("katana") or {}).items()}
VB = next((ca for ca, s in KAT_KV.items() if s == "USDC"), "0x" + "0" * 38 + "01")
SHAM = "0x" + "5b" * 20
KAT = "0x" + "7a" * 20


def tx(tag):
    return "0x" + hashlib.sha256(tag.encode()).hexdigest()


def mkey(t):
    return str((t * 1000 // 60_000) * 60_000)


chk(KAT_KV.get(VB) == "USDC" and len(KAT_KV) == 1, "[1] STABLE_CAS katana = vbUSDC 하나 → 그룹 'USDC'", KAT_KV)
names = {v for m in pricing.STABLE_CAS.values() for v in m.values()} | set(pricing.STABLE_MINTS.values())
chk(names <= web.STABLE_GROUPS, "[1] 모든 화이트리스트 그룹명 ⊂ web.STABLE_GROUPS", names - web.STABLE_GROUPS)
chk(spamguard.is_genuine("katana", VB) and not spamguard.is_genuine("katana", SHAM) and not spamguard.is_genuine("eth", VB),
    "[1] 정품 = katana 정식 주소만(사칭 주소·다른 체인의 같은 주소 아님)")


class _Px:
    calls = []

    def candle_usd(self, sym, ms):
        self.calls.append(str(sym).upper())
        return 2.15 if str(sym).upper() == "KAT" else None

    def fx_at(self, ms):
        return 1400.0


cpath = os.path.join(os.environ["TJ_BASE"], "state", "core_t.db")
cc = dbm.open_db(cpath)
C = core.Core.__new__(core.Core)
C.conn, C.wrapped, C.native_sym, C.px = cc, {}, {"katana": "ETH"}, _Px()
C._sym_px_verdict = lambda aid, px, sym=None, ts_ms=None: "ok"
a_vb = C.asset_id("token", "katana", VB, "vbUSDC", 6)
a_sh = C.asset_id("token", "katana", SHAM, "vbUSDC", 6)
a_eth = C.asset_id("token", "eth", VB, "vbUSDC", 6)
a_kat = C.asset_id("token", "katana", KAT, "KAT", 18)
gname = lambda g: cc.execute("SELECT name FROM asset_groups WHERE group_id=?", (g,)).fetchone()[0]
g_vb, g_sh, g_eth = C._group_of(a_vb), C._group_of(a_sh), C._group_of(a_eth)
chk(gname(g_vb) == "USDC" and C._is_stable_aid(a_vb), "[2] 정식 vbUSDC → 'USDC' 그룹 · 검증 스테이블", gname(g_vb))
del _Px.calls[:]
chk(C._leg_px(a_vb, T1) == 1.0 and not _Px.calls, "[2] 정식 vbUSDC 단가 = 1.0(시세 조회 없음)", _Px.calls)
chk(gname(g_sh).startswith("VBUSDC#") and not C._is_stable_aid(a_sh), "[2] 사칭 vbUSDC(다른 주소) = 인스턴스 그룹 · 스테이블 아님", gname(g_sh))
chk(gname(g_eth).startswith("VBUSDC#") and not C._is_stable_aid(a_eth), "[2] 다른 체인의 같은 주소 = 인스턴스 그룹 · 스테이블 아님", gname(g_eth))

cc.execute("INSERT OR IGNORE INTO asset_groups (name) VALUES (?)", (f"VBUSDC#{a_vb}",))
g_old = cc.execute("SELECT group_id FROM asset_groups WHERE name=?", (f"VBUSDC#{a_vb}",)).fetchone()[0]
cc.execute("UPDATE assets SET group_id=? WHERE asset_id=?", (g_old, a_vb))
cc.execute("INSERT INTO positions (group_id, location, qty_norm, qty_unknown_norm, cost_alloc_usd) VALUES (?,?,?,?,?)",
           (g_old, f"wallet:katana:{W}", "7", "7", "0"))
cc.commit()
m1, m2 = C._stable_regroup(), C._stable_regroup()
pos = [tuple(r) for r in cc.execute("SELECT group_id, qty_norm, qty_unknown_norm FROM positions")]
g_now = cc.execute("SELECT group_id FROM assets WHERE asset_id=?", (a_vb,)).fetchone()[0]
chk(len(m1) == 1 and f"VBUSDC#{a_vb}→USDC" in m1[0] and m2 == [] and gname(g_now) == "USDC" and pos == [(g_vb, "7", "7")],
    "[2] 기동 재그룹 'VBUSDC#n' → 'USDC'(포지션 이동) · 두 번째 0건(멱등) · 사칭은 그대로", (m1, m2, pos))

SW = tx("core-swap")
for seq, aid, q, lk in ((0, a_vb, str(-5000 * 10 ** 6), "disp"), (1, a_kat, str(2500 * 10 ** 18), "acq")):
    cc.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd,"
               " cost_krw, leg_kind, event, classifier_ver) VALUES ('chain_tx','katana',?,?,?,?,?,?,NULL,NULL,?,'SWAP',3)",
               (SW, seq, T1, aid, f"wallet:katana:{W}", q, lk))
cc.commit()
C._price_tx("katana", SW)
cs = [float(r[0]) if r[0] is not None else None for r in cc.execute("SELECT cost_usd FROM postings WHERE source_id=? ORDER BY leg_seq", (SW,))]
chk(cs == [5000.0, 5000.0], "[2] 값 없는 vbUSDC 5천 → KAT 2,500 스왑 = 양쪽 $5,000(유출측 액면 · KAT 시세 $2.15 × 2,500 = $5,375 아님)", cs)
cc.close()

c = dbm.open_db(common.DB_PATH)
A = {}


def asset(key, kind, chain, addr, sym, dec, inst=True, gname9=None):
    c.execute("INSERT INTO assets (kind, chain, address, symbol, decimals, confirmed, group_id) VALUES (?,?,?,?,?,1,NULL)", (kind, chain, addr, sym, dec))
    aid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    nm = gname9 or (f"{sym.upper()}#{aid}" if inst else sym.upper())
    c.execute("INSERT INTO asset_groups (name) VALUES (?)", (nm,))
    c.execute("UPDATE assets SET group_id=(SELECT group_id FROM asset_groups WHERE name=?) WHERE asset_id=?", (nm, aid))
    A[key] = (aid, dec)


asset("vb", "token", "katana", VB, "vbUSDC", 6)
asset("sham", "token", "katana", SHAM, "vbUSDC", 6)
asset("kat", "token", "katana", KAT, "KAT", 18)
asset("zzz", "token", "katana", "0x" + "3c" * 20, "ZZZ", 18)
asset("bkat", "exchange_currency", None, "binance:kat", "KAT", 8)
asset("busdt", "exchange_currency", None, "binance:usdt", "USDT", 8)
asset("busdc", "exchange_currency", None, "binance:usdc", "USDC", 8)
asset("bbtc", "exchange_currency", None, "binance:btc", "BTC", 8)
WL, BNL = f"wallet:katana:{W}", "exchange:binance"


def post(kind, ns, sid, leg, t, a, loc, qty, usd, lk, ev):
    aid, dec = A[a]
    c.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event,"
              " classifier_ver) VALUES (?,?,?,?,?,?,?,?,?,NULL,?,?,4)",
              (kind, ns, sid, leg, t, aid, loc, str(int(Decimal(str(qty)) * 10 ** dec)), None if usd is None else repr(float(usd)), lk, ev))


def raw(ex, kind, uid, payload, t):
    c.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES (?,?,?,1,?,?)", (ex, kind, uid, json.dumps(dict(payload, uuid=uid)), t))


post("chain_tx", "katana", tx("p1"), 0, T1, "vb", WL, "10000", None, "acq", "PROGRAM_IN")
post("chain_tx", "katana", tx("ps"), 0, T1 + 60, "sham", WL, "1000", None, "acq", "PROGRAM_IN")
post("chain_tx", "katana", tx("ss"), 0, T1 + 900, "sham", WL, "-1000", 500, "disp", "SWAP")
post("chain_tx", "katana", tx("ss"), 1, T1 + 900, "zzz", WL, "10", 500, "acq", "SWAP")
post("chain_tx", "katana", tx("s1"), 0, T1 + 600, "vb", WL, "-4000", 4300, "disp", "SWAP")
post("chain_tx", "katana", tx("s1"), 1, T1 + 600, "kat", WL, "2000", 4300, "acq", "SWAP")
post("chain_tx", "katana", tx("s2"), 0, T1 + 1200, "vb", WL, "-5000", None, "disp", "SWAP")
post("chain_tx", "katana", tx("s2"), 1, T1 + 1200, "kat", WL, "2500", None, "acq", "SWAP")
TK, TV = tx("k1"), tx("v1")
post("chain_tx", "katana", TK, 0, T1 + DAY, "kat", WL, "-4500", None, "move_out", "TRANSFER_OUT_EX")
raw("binance", "deposit", "BK-D", {"currency": "KAT", "amount": "4500", "txid": TK, "state": "ACCEPTED"}, T1 + DAY + 600)
post("exchange", "binance:deposit", "BK-D", 0, T1 + DAY + 600, "bkat", BNL, "4500", None, "move_in", "EXF_DEPOSIT")
post("exchange", "binance:trade", "BK-T", 0, T1 + 2 * DAY, "bkat", BNL, "-4500", 9900, "disp", "EXF_SELL")
post("exchange", "binance:trade", "BK-T", 1, T1 + 2 * DAY, "busdt", BNL, "9900", 9900, "acq", "EXF_BUY")
post("chain_tx", "katana", TV, 0, T1 + DAY + 120, "vb", WL, "-1000", None, "move_out", "TRANSFER_OUT_EX")
raw("binance", "deposit", "BU-D", {"currency": "USDC", "amount": "1000", "txid": TV, "state": "ACCEPTED"}, T1 + DAY + 700)
post("exchange", "binance:deposit", "BU-D", 0, T1 + DAY + 700, "busdc", BNL, "1000", None, "move_in", "EXF_DEPOSIT")
TB = T1 + 3 * DAY
post("exchange", "binance:trade", "BU-T", 0, TB, "bbtc", BNL, "0.01", 1000, "acq", "EXF_BUY")
post("exchange", "binance:trade", "BU-T", 1, TB, "busdc", BNL, "-1000", 1000, "disp", "EXF_SELL")
c.commit()
c.close()
px = {"USDT": 1.0, "USDC": 1.0, "BTC": 100000.0, "KAT": 2.0}
json.dump({"usd": px, "usd_ts": {k: NOW for k in px}, "rate": 1400.0, "updated": NOW, "dex_usd": {}, "dex_ts": {}, "dex_res": {}, "dex_res_ts": {},
           "fx_basis": 1400.0, "ex_usd": {f"binance:{k}": v for k, v in px.items()}, "ex_ts": {f"binance:{k}": NOW for k in px}}, open(web.SPOT_PATH, "w"))
web.pricing.PxCache.candle_usd = lambda self, sym, ms: None


def build():
    common.atomic_write_json(web.PREFS_PATH, {"plans": {}, "ignored": []})
    b = web.StateBuilder()
    b.skip_gen_check = True
    fx9 = b.px.d.setdefault("fx", {})
    fx9[mkey(T1)] = 1300.0
    fx9[mkey(TB)] = 1420.0
    conn = dbm.open_db(common.DB_PATH, readonly=True)
    try:
        f = b._build(conn)["fields"]
    finally:
        conn.close()
    return f, (b._day_idx or {}).get("tax") or []


def rz(f, sym, chain=None):
    return round(sum(float(p.get("realized") or 0) for p in f.get("positions") or []
                     if p.get("sym") == sym and (chain is None or chain in str(p.get("chain") or p.get("where") or ""))), 2)


def rz_all(f):
    return round(sum(float(v or 0) for v in (f.get("realizedByDate") or {}).values()), 2)


def tax_q(rows, q, pred=lambda r: True):
    r9 = [r for r in rows if abs(abs(float(r.get("_qty") or r.get("qty") or 0)) - q) < 1e-6 and pred(r)]
    return r9[0] if len(r9) == 1 else (r9 or None)


f0, rows0 = build()
if os.environ.get("TJ_TEST_VERBOSE"):
    for r in rows0:
        print("  전", r.get("sym"), r.get("ex"), r.get("qty"), "tk", r.get("tk"), "acq", r.get("_acq"), "akr", r.get("_akr"), "sfx", r.get("_sfx"))
v0 = tax_q(rows0, 4000, lambda r: r.get("sym") == "VBUSDC")
k0 = rz(f0, "KAT")
chk(abs(k0 - 225.0) < 0.01 and v0 is not None and not isinstance(v0, list) and v0.get("tk") != "st" and str(v0.get("ex") or "").endswith(FS_EX),
    "[3] 전(재현): vbUSDC 원가 미확인 → 최초 인식 시가(같은 날 매도 단가 $1.075) · KAT 실현 +$225 · 명세 코인 표", (k0, v0))

conn9 = dbm.open_db(common.DB_PATH)
C2 = core.Core.__new__(core.Core)
C2.conn, C2.wrapped, C2.native_sym, C2.px = conn9, {}, {"katana": "ETH"}, _Px()
moved = C2._stable_regroup()
conn9.close()
f1, rows1 = build()
if os.environ.get("TJ_TEST_VERBOSE"):
    for r in rows1:
        print("  후", r.get("sym"), r.get("ex"), r.get("qty"), "tk", r.get("tk"), "acq", r.get("_acq"), "akr", r.get("_akr"), "sfx", r.get("_sfx"))
chk(len(moved) == 1 and "VBUSDC#" in moved[0] and "→USDC" in moved[0], "[3] 기동 재그룹 = 정식 vbUSDC 하나만 'USDC' 로(사칭 그대로)", moved)
k1 = rz(f1, "KAT")
chk(abs(k1 - 600.0) < 0.01, "[3] 후: KAT 원가 $4,300 + 액면 $5,000 = $9,300 → 실현 +$600(전 +$225)", k1)
s1 = tax_q(rows1, 4000, lambda r: r.get("sym") == "USDC")
chk(isinstance(s1, dict) and s1.get("tk") == "st" and abs(float(s1.get("_akr") or 0) - 4000 * 1300) < 2,
    "[3] 후: vbUSDC 4천 처분 = 명세 스테이블 원화 환차 표(tk st) · 원화 취득 = 4,000 × 유입 그 분 ₩1,300", s1)
chk(abs(rz_all(f1) - 900.0) < 0.01, "[3] 후: 실현 합 +$900 = KAT 받은 $9,900 − 쓴 vbUSDC 액면 $9,000(전 = 최초 인식 시가로 다름)", (rz_all(f0), rz_all(f1)))
chk(not [r for r in rows1 if r.get("sym") == "VBUSDC" and abs(float(r.get("_qty") or 0) - 1000) > 1e-6],
    "[3] 후: 명세 코인 표에 정식 vbUSDC 행 없음(스테이블 표로 이동 · 남은 VBUSDC 행 = 사칭 1천뿐)",
    [(r.get("ex"), r.get("qty")) for r in rows1 if r.get("sym") == "VBUSDC"])
bu = tax_q(rows1, 1000, lambda r: r.get("sym") == "USDC" and "바이낸스" in str(r.get("ex") or ""))
chk(isinstance(bu, dict) and abs(float(bu.get("_akr") or 0) - 1_300_000) < 2 and abs(float(bu.get("_sfx") or 0) - 120_000) < 2
    and str(bu.get("ex") or "").endswith(FS_EX),
    "[3] 후: 바이낸스로 옮긴 1천 = 유입 환율 ₩1,300 을 들고 감 → 환차 +₩120,000 · '최초 인식 시가' 표기(NA4 이동 경로)", bu)
sh = tax_q(rows1, 1000, lambda r: r.get("sym") == "VBUSDC")
chk(isinstance(sh, dict) and sh.get("tk") != "st" and abs(float(sh.get("_acq") or 0) - 1000) > 1,
    "[3] 후: 사칭 vbUSDC(다른 주소) 1천 처분 = 코인 표 그대로(스테이블 표·액면 원가 $1,000 아님)", sh)
unv1 = {str(p.get("sym") or "") for p in f1.get("pendings") or [] if str(p.get("key") or "").startswith("unv:")}
chk("USDC" not in unv1 and "VBUSDC" not in unv1, "[3] 후: vbUSDC 원가 미확인 매도 검토 행 없음", sorted(unv1))
T.finish()
