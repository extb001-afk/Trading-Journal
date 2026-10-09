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

A = "0x" + "a1" * 20
json.dump({"chains": {}, "wallets": [{"type": "evm", "chain": "eth", "address": A, "label": "main"}], "backfill_months": 5},
          open(os.path.join(os.environ["TJ_BASE"], "config.json"), "w"))
import acct_norm
import db as dbm
import histcurve
import netpace
import web

chk = T.chk
for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker"):
    if hasattr(web.StateBuilder, _m):
        setattr(web.StateBuilder, _m, lambda self: None)
netpace.wait = lambda url, now=None, sleep=None: None
KST = timezone(timedelta(hours=9))
NOW = int(time.time())
DAY = 86400
W = int((datetime.fromtimestamp(NOW, KST).replace(hour=9, minute=0, second=0, microsecond=0) - timedelta(days=140)).timestamp())
ISO = acct_norm.iso_day
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
E = {k: "0x" + h * 20 for k, h in (("TKN", "e1"), ("TK2", "e2"), ("TK3", "e3"), ("TK4", "c4"), ("TK5", "e5"), ("TKR", "e6"))}
F = "0x" + "f1" * 20

c = dbm.open_db(common.DB_PATH)
G, AS, CA = {}, {}, {}


def grp(name):
    c.execute("INSERT INTO asset_groups (name, norm_decimals) VALUES (?, 18)", (name,))
    return c.execute("SELECT group_id FROM asset_groups WHERE name=?", (name,)).fetchone()[0]


def token(sym, ca, confirmed):
    G[sym] = grp(sym)
    CA[sym] = ca
    c.execute("INSERT INTO assets (kind, chain, address, symbol, decimals, confirmed, group_id) VALUES ('token','eth',?,?,6,?,?)", (ca, sym, confirmed, G[sym]))
    AS[sym] = c.execute("SELECT last_insert_rowid()").fetchone()[0]


token("USDC", USDC, 1)
for i, (sym, conf) in enumerate((("TKN", 1), ("TK2", 1), ("TK3", 1), ("TK4", 1), ("TK5", 1), ("ADT", 0), ("VTK", 1), ("LQT", 0),
                                 ("PTK", 1), ("WTK", 1), ("SDT", 1), ("HTK", 1), ("TKR", 1), ("LPA", 1), ("LPB", 1))):
    token(sym, "0x" + f"{0xb000 + i:040x}", conf)
G["ETH"] = grp("ETH")
c.execute("INSERT INTO assets (kind, chain, address, symbol, decimals, confirmed, group_id) VALUES ('native','eth',NULL,'ETH',18,1,?)", (G["ETH"],))
AS["ETH"] = c.execute("SELECT last_insert_rowid()").fetchone()[0]
G["BTC"] = grp("BTC")
c.execute("INSERT INTO assets (kind, chain, address, symbol, decimals, confirmed, group_id) VALUES ('exchange_currency',NULL,'upbit:BTC','BTC',8,1,?)", (G["BTC"],))
AS["BTC"] = c.execute("SELECT last_insert_rowid()").fetchone()[0]
WL = f"wallet:eth:{A}"
NTX = [0]


def txh():
    NTX[0] += 1
    return "0x" + f"{NTX[0]:064x}"


def leg(h, t, sym, qty, usd, lk, ev, loc=WL, seq=0, ns="eth", kind="chain_tx"):
    dec = 18 if sym == "ETH" else (8 if sym == "BTC" else 6)
    c.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event,"
              " classifier_ver) VALUES (?,?,?,?,?,?,?,?,?,NULL,?,?,4)",
              (kind, ns, h, seq, t, AS[sym], loc, str(int(Decimal(str(qty)) * 10 ** dec)), None if usd is None else repr(float(usd)), lk, ev))


def snap(h, frm, to, legs, event="TRANSFER_IN"):
    c.execute("INSERT INTO raw_txs (chain, txhash, block, blockhash, ts, snapshot, wallets, ingested_at) VALUES ('eth',?,1,'',0,?,'[]',0)",
              (h, json.dumps({"tx": {"hash": h, "from": frm, "to": to, "value": "0", "fee": {"value": "21000"}, "status": "ok", "raw_input": "0x"},
                              "token_transfers": [{"from": {"hash": a}, "to": {"hash": b}, "token": {"address": ca, "type": "ERC-20"},
                                                   "total": {"value": str(v)}} for a, b, ca, v in legs], "internal": []})))
    c.execute("INSERT INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES ('eth',?,?,'{}',4)", (h, event))


def buy(t, sym, qty, usd):
    h = txh()
    leg(h, t, sym, qty, usd, "acq", "SWAP", seq=0)
    leg(h, t, "USDC", -usd, usd, "disp", "SWAP", seq=1)


def sell(t, sym, qty, usd):
    h = txh()
    leg(h, t, sym, -qty, usd, "disp", "SWAP", seq=0)
    leg(h, t, "USDC", usd, usd, "acq", "SWAP", seq=1)


def send_out(t, sym, qty, dest):
    h = txh()
    leg(h, t, sym, -qty, None, "move_out", "TRANSFER_OUT", seq=0)
    leg(h, t, sym, qty, None, "move_in", "TRANSFER_OUT", loc=f"out:eth:{dest}", seq=1)


def recv(t, sym, qty, frm, signer=None, with_snap=True):
    h = txh()
    leg(h, t, sym, qty, None, "acq", "TRANSFER_IN")
    if with_snap:
        snap(h, signer or frm, CA[sym], [(frm, A, CA[sym], int(qty * 10 ** 6))])
    return h


h0 = txh()
leg(h0, W - 3600, "USDC", 1_000_000, None, "acq", "TRANSFER_IN")
snap(h0, F, USDC, [(F, A, USDC, 10 ** 12)])
T1, T2, T3, T4 = W + 1 * DAY, W + 2 * DAY, W + 3 * DAY, W + 4 * DAY
buy(T1, "TKN", 1000, 1000)
send_out(T2, "TKN", 1000, E["TKN"])
recv(T3, "TKN", 1000, E["TKN"])
sell(T4, "TKN", 1000, 10000)
buy(T1, "TK2", 1000, 1000)
send_out(T2, "TK2", 1000, E["TK2"])
recv(T3, "TK2", 1000, E["TK2"], with_snap=False)
sell(T4, "TK2", 1000, 10000)
buy(T1, "TK3", 1000, 1000)
send_out(T2, "TK3", 1000, E["TK3"])
recv(T3, "TK3", 500, F)
sell(T4, "TK3", 500, 6000)
buy(T1, "TK4", 1000, 1000)
send_out(T2, "TK4", 1000, E["TK4"])
recv(T3, "TK4", 1000, E["TK4"], signer=A)
sell(T4, "TK4", 1000, 10000)
buy(T1, "TK5", 1000, 1000)
send_out(T2, "TK5", 1000, E["TK5"])
recv(T3, "TK5", 1100, E["TK5"])
sell(T4, "TK5", 1100, 11000)
recv(T1, "ADT", 1000, F)
sell(T3, "ADT", 1000, 1500)
recv(T1, "VTK", 1000, F)
sell(T3, "VTK", 1000, 1500)
recv(T1, "LQT", 1000, F)
sell(T3, "LQT", 1000, 2500)
recv(T1, "PTK", 1000, F)
sell(T3, "PTK", 1000, 3000)
recv(T1, "WTK", 1000, F)
sell(T3, "WTK", 1000, 500)
D0 = W + 20 * DAY
recv(D0 + 3600, "SDT", 1000, F)
sell(D0 + 5 * 3600, "SDT", 1000, 3000)
buy(T1 - 3600, "HTK", 10, 30)
recv(T1, "HTK", 100, F)
buy(T1, "TKR", 100, 100)
send_out(T2, "TKR", 100, E["TKR"])
recv(T3, "TKR", 100, E["TKR"])
sell(T4, "TKR", 100, 500)
buy(W + 5 * DAY, "TKR", 100, 1000)
send_out(W + 6 * DAY, "TKR", 100, E["TKR"])
recv(W + 7 * DAY, "TKR", 100, E["TKR"])
sell(W + 8 * DAY, "TKR", 100, 1500)
hlp = txh()
leg(hlp, T1, "LPA", 100, None, "acq", "LP_REMOVE", seq=0)
leg(hlp, T1, "LPB", 100, None, "acq", "LP_REMOVE", seq=1)
sell(T3, "LPA", 100, 300)
sell(T3, "LPB", 100, 500)
buy(T1, "ETH", 1, 2000)
hg = txh()
leg(hg, T2, "ETH", "-0.01", None, "gas", "FAILED")
TB = W + 1 * DAY + 3600
leg("G9BD", TB, "BTC", "0.1", None, "move_in", "EX_DEPOSIT", loc="exchange:upbit", ns="upbit:deposit", kind="exchange")
leg("G9BS", W + 9 * DAY, "BTC", "-0.1", 7000, "disp", "EX_SELL", loc="exchange:upbit", ns="upbit:order", kind="exchange")
c.execute("INSERT INTO positions (group_id, location, qty_norm) VALUES (?,?,?)", (G["HTK"], WL, "110"))
c.execute("INSERT INTO positions (group_id, location, qty_norm) VALUES (?,?,?)", (G["ETH"], WL, "0.99"))
c.commit()
c.close()

DC = {}
for sym in ("TKN", "TK2", "TK3", "TK4", "TK5"):
    DC[(f"ca:eth:{CA[sym]}", ISO(T3))] = 10.0
DC[(f"ca:eth:{CA['ADT']}", ISO(T1))] = 50.0
DC[(f"ca:eth:{CA['VTK']}", ISO(T1))] = 50.0
DC[(f"ca:eth:{CA['LQT']}", ISO(T1))] = 2.0
DC[(f"ca:eth:{CA['PTK']}", ISO(T1))] = 2.0
DC[(f"ca:eth:{CA['SDT']}", ISO(D0 + 3600))] = 2.0
DC[(f"ca:eth:{CA['HTK']}", ISO(T1))] = 3.0
DC[(f"ca:eth:{CA['LPA']}", ISO(T1))] = 2.0
DC[(f"ca:eth:{CA['LPB']}", ISO(T1))] = 4.0
DC[("sym:BTC", ISO(TB))] = 60000.0
CALLS = []


def fake_lookup(spec, iso, now=None, w=0.0, ask=True, old=False):
    CALLS.append((spec, iso))
    v = DC.get((spec, iso))
    return (v, "ok") if v else (None, "pending")


fake_lookup._tj_test_mock = True
histcurve.DAYCLOSE.lookup = fake_lookup
px = {"USDC": 1.0, "ETH": 2000.0, "BTC": 70000.0}
json.dump({"usd": px, "usd_ts": {k: NOW for k in px}, "rate": 1400.0, "updated": NOW, "dex_usd": {}, "dex_ts": {}, "dex_res": {}, "dex_res_ts": {},
           "fx_basis": 1400.0, "ex_usd": {"upbit:BTC": 70000.0}, "ex_ts": {"upbit:BTC": NOW}}, open(web.SPOT_PATH, "w"))
web.pricing.PxCache.candle_usd = lambda self, sym, ms: None
web.pricing._gj = lambda url, timeout=10.0: None
MINUTE = {"on": False}


def build(prefs, b=None):
    common.atomic_write_json(web.PREFS_PATH, dict({"plans": {}, "ignored": []}, **prefs))
    b = b or web.StateBuilder()
    b.skip_gen_check = True
    b.spot.dex_res[f"eth:{CA['LQT']}"] = 50000.0
    if MINUTE["on"]:
        b.px.d.setdefault("candle", {})[f"BTC:{(TB * 1000 // 60_000) * 60_000}"] = 50000.0
    conn = dbm.open_db(common.DB_PATH, readonly=True)
    try:
        out = b._build(conn)
    finally:
        conn.close()
    return out["fields"], (b._day_idx or {}).get("tax") or [], b, out


def rz(f, sym):
    return round(sum(float(p.get("realized") or 0) for p in f.get("positions") or [] if p.get("sym") == sym), 2)


def unv(f, sym):
    return [p for p in f.get("pendings") or [] if str(p.get("key") or "").startswith("unv:") and p.get("sym") == sym]


def acq(rows, sym):
    return round(sum(float(r.get("_acq") or 0) for r in rows if r.get("sym") == sym), 2)


f, rows, b1, out1 = build({})
fs = f.get("firstSeen") or {}
chk(fs.get("on") is True and fs.get("eff") is True, "기본 = 켬", fs)
chk(rz(f, "TKN") == 9000.0 and not unv(f, "TKN"), "G1 (NA1) 돌아온 TKN = 보낼 때 원가 $1,000 승계 → 실현 +$9,000(원가 $10,000 아님 · 검토 행 없음)",
    [rz(f, "TKN"), acq(rows, "TKN"), unv(f, "TKN")])
chk(acq(rows, "TKN") == 1000.0, "G1 명세 취득가액 $1,000", acq(rows, "TKN"))
chk(int(fs.get("ret") or 0) >= 3, "G1 firstSeen.ret = 돌아온 코인 승계 건(TKN·TK4·TK5)", fs)
pt = [p for p in f.get("positions") or [] if p.get("sym") == "TKN"]
chk(pt and any("보냈던 주소에서 돌아옴" in str(e.get("d") or e.get("desc") or "") for p in pt for e in (p.get("events") or [])),
    "G1 기록 줄 '보냈던 주소에서 돌아옴 · 원가 승계'", [e for p in pt for e in (p.get("events") or [])][:6])
u2 = unv(f, "TK2")
chk(rz(f, "TK2") == 0 and u2 and u2[0].get("fsHold") == "ret" and "보냈던 코인" in str(u2[0].get("gap")),
    "G2 (NA1) 누가 보냈는지 모름 = 원가 미확인 그대로 + 검토 행(사유 ret — 최초 인식 시가 보류)", [rz(f, "TK2"), u2])
chk(rz(f, "TK3") == 1000.0 and acq(rows, "TK3") == 5000.0, "G3 다른 주소에서 받음 = 최초 인식 시가($10 × 500 = $5,000) → 실현 +$1,000", [rz(f, "TK3"), acq(rows, "TK3")])
chk(rz(f, "TK4") == 9000.0, "G4 내가 서명한 인출(토큰은 보낸 컨트랙트가 돌려줌)도 승계 → 실현 +$9,000", rz(f, "TK4"))
chk(rz(f, "TK5") == 9000.0 and acq(rows, "TK5") == 2000.0, "G5 1000 보내 1100 돌아옴 = 1000 승계($1,000) + 초과 100 최초 인식 시가($1,000) → 실현 +$9,000",
    [rz(f, "TK5"), acq(rows, "TK5")])
u6 = unv(f, "ADT")
chk(rz(f, "ADT") == 0 and u6 and u6[0].get("fsHold") == "unv", "G6 (NA2) 확인 안 된 컨트랙트 토큰 = 일봉 $50 안 씀(−$48,500 없음 · 원가 미확인 + 검토 사유 unv)",
    [rz(f, "ADT"), u6])
chk(not [x for x in CALLS if x[0] == f"ca:eth:{CA['ADT']}"], "G6 확인 안 된 토큰은 마감가 요청도 안 남김", [x for x in CALLS if "ADT" in x[0]])
u7 = unv(f, "VTK")
chk(rz(f, "VTK") == 0 and u7 and u7[0].get("fsHold") == "cap", "G7 (NA2) 일봉 $50 > 실제 매도 단가 $1.5 × 10 = 보류(원가 미확인 + 검토 사유 cap)", [rz(f, "VTK"), u7])
chk(rz(f, "LQT") == 500.0 and not unv(f, "LQT"), "G8 풀 유동성 기록 $50,000 ≥ 가드 기준 = 적용(원가 $2,000 → 실현 +$500)", [rz(f, "LQT"), unv(f, "LQT")])
chk(rz(f, "PTK") == 1000.0, "G9 첫 빌드 PTK = P1 $2 → 실현 +$1,000", rz(f, "PTK"))
chk(rz(f, "BTC") == 1000.0, "G9b 첫 빌드 BTC = 그날 일봉 $60,000(1분봉 없음) → 실현 +$1,000", rz(f, "BTC"))
PIN_PATH = getattr(web, "FS_PIN_PATH", os.path.join(common.STATE_DIR, "first_seen_px.json"))
pin = json.load(open(PIN_PATH)) if os.path.exists(PIN_PATH) else {}
chk(pin.get("_v") == 1 and any(abs(v[0] - 2.0) < 1e-9 for v in (pin.get("p") or {}).values()), "G9 고정 저장소 파일(state/first_seen_px.json)에 단가 저장", pin)
u10 = unv(f, "WTK")
chk(u10 and u10[0].get("fsHold") == "wait" and int(fs.get("wait") or 0) >= 1 and int((fs.get("hold") or {}).get("wait") or 0) >= 1,
    "G10 (NA3) 그날 시세 기다리는 매도 = 검토 사유 wait · firstSeen.wait(시세 대기 n건)", [u10, fs.get("wait"), fs.get("hold")])
chk(rz(f, "SDT") == 0 and acq(rows, "SDT") == 3000.0, "G11 (NA8②) 같은 날 판 에어드랍 = 매도가 $3,000 이 원가 → 실현 0(장중 차이 +$1,000 아님)", [rz(f, "SDT"), acq(rows, "SDT")])
gp = [p for p in f.get("pendings") or [] if str(p.get("key") or "") == f"gasnopx:{G['ETH']}"]
chk(gp and abs(float(gp[0].get("usd") or 0) - 20.0) < 0.01, "G12 (NA8③) 시세 없는 가스 0.01 ETH 가 원가 $20 만 소진 = 검토 행 gasnopx", gp)

hc = [x for x in f.get("coins") or [] if x.get("sym") == "HTK"]
chk(hc and abs(float(hc[0].get("fsc") or 0) - 300.0) < 0.01, "G15 (ND3) 보유 원가 중 최초 인식 시가 몫 = 코인 행 fsc $300(보유 줄 '추정' 칩)", hc)
chk(not [x for x in f.get("coins") or [] if x.get("sym") == "ETH" and x.get("fsc")], "G15 매수 원가만 있는 보유 = fsc 없음")

chk(rz(f, "TKR") == 900.0, "G16 (fs407 ①) 같은 주소 두 번 왕복 = 둘째 반환은 둘째 송신 원가 $1,000 만 → 실현 +$400 + +$500(둘째 $550 섞임 아님)", rz(f, "TKR"))
chk(rz(f, "LPA") == 100.0 and rz(f, "LPB") == 100.0, "G17 LP 회수 두 자산 첫 빌드 = A $2 · B $4 각각(실현 +$100 · +$100)", [rz(f, "LPA"), rz(f, "LPB")])

DC[(f"ca:eth:{CA['PTK']}", ISO(T1))] = 2.5
DC[(f"ca:eth:{CA['VTK']}", ISO(T1))] = 1.2
MINUTE["on"] = True
f2, rows2, _b2, _o2 = build({})
chk(rz(f2, "PTK") == 1000.0 and acq(rows2, "PTK") == 2000.0, "G9 (NA3) 저장소 값이 P2 $2.5 로 바뀌어도 원가 P1 $2,000 그대로 → 실현 +$1,000", [rz(f2, "PTK"), acq(rows2, "PTK")])
chk(rz(f2, "BTC") == 1000.0, "G9b (NA3) 나중에 들어온 1분봉 $50,000 이 고정 일봉 $60,000 을 안 덮음 → 실현 +$1,000 그대로", rz(f2, "BTC"))
chk(int((f2.get("firstSeen") or {}).get("pin") or 0) >= 1, "G9 둘째 빌드 = 고정값 사용(firstSeen.pin)", f2.get("firstSeen"))
chk(rz(f2, "TKN") == 9000.0 and rz(f2, "SDT") == 0, "G9 둘째 빌드도 G1·G11 그대로", [rz(f2, "TKN"), rz(f2, "SDT")])
chk(rz(f2, "LPA") == 100.0 and rz(f2, "LPB") == 100.0, "G17 (fs407 ②) 둘째 빌드 = 자산마다 따로 고정(A 가 B 값 $4 로 바뀌어 −$100 이 되지 않음)", [rz(f2, "LPA"), rz(f2, "LPB")])
chk(rz(f2, "VTK") == 300.0 and not unv(f2, "VTK"), "G18 (fs407 ③) 보류했던 값은 고정 안 됨 — 시세 $1.2 로 정정되면 적용(원가 $1,200 → 실현 +$300)", [rz(f2, "VTK"), unv(f2, "VTK")])

f0, rows0, _b0, _o0 = build({"first_seen_px": False})
chk(rz(f0, "TKN") == 0 and unv(f0, "TKN") and rz(f0, "PTK") == 0 and int((f0.get("firstSeen") or {}).get("pin") or 0) == 0,
    "G13 끔 = 돌아온 코인도 원가 미확인(실현 0 · 검토 행) · 고정값 안 씀", [rz(f0, "TKN"), rz(f0, "PTK"), f0.get("firstSeen")])
chk(not [p for p in f0.get("pendings") or [] if p.get("fsHold")], "G13 끔 = 보류 사유 표기 없음")
chk(not [x for x in f0.get("coins") or [] if x.get("fsc")], "G13 끔 = 보유 줄 '추정' 재료(fsc) 없음")

chk((f.get("firstSeen") or {}).get("note") is False, "G14 처음 = 배너 안 닫음(firstSeen.note false)", f.get("firstSeen"))
common.atomic_write_json(web.PREFS_PATH, {"plans": {}, "ignored": [], "first_seen_note": int(time.time())})
b1.__dict__.pop("_prefs_c", None)
mp = b1._mp_apply(out1, {"fsnote"})
chk(((mp.get("fields") or {}).get("firstSeen") or {}).get("note") is True and (mp["fields"]["firstSeen"].get("n") == fs.get("n")),
    "G14 닫음(ui_prefs first_seen_note) → 칸 고치기(mpatch fsnote) firstSeen.note true · 다른 칸 그대로", (mp.get("fields") or {}).get("firstSeen"))
chk("first_seen_note" in web.StateBuilder.PREFS_NOBUILD and "fsnote" in web.StateBuilder.MP_KINDS, "G14 닫기는 재빌드 안 부름(PREFS_NOBUILD · MP_KINDS)")
f3, _r3, _b3, _o3 = build({"first_seen_note": int(time.time())})
chk((f3.get("firstSeen") or {}).get("note") is True, "G14 다음 빌드도 note true", f3.get("firstSeen"))

load = getattr(web, "_fs_pin_load", None)
with open(PIN_PATH, "w") as fh:
    fh.write('{"_v": 1, "p": {"bad_obj": {}, "bad_str": "x", "bad_nan": [NaN], "bad_neg": [-1, "close"], '
             '"ok_nan_ts": [1.5, "close", "2026-01-01", NaN], "ok_inf_ts": [1.5, "close", "2026-01-01", Infinity], "ok": [2.0, "close", "2026-01-01", 123]}}')
r19 = T.safe(load) if load else {"_exc": "없음"}
chk(isinstance(r19, dict) and "_exc" not in r19 and set(r19) == {"ok_nan_ts", "ok_inf_ts", "ok"} and r19["ok_inf_ts"][3] == 0,
    "G19 (fs407 ④) 항목 손상(빈 객체·글자·NaN 단가·음수·NaN/무한대 시각) = 나쁜 항목만 버림 · 시각은 0", r19)
f19 = T.safe(lambda: build({})[0])
chk(isinstance(f19, dict) and "_exc" not in f19 and (f19.get("firstSeen") or {}).get("on") is True, "G19 손상 항목이 든 저장소로도 빌드 계속", f19 if "_exc" in (f19 or {}) else None)
with open(PIN_PATH, "w") as fh:
    fh.write('{"_v": 1, "p": [1, 2]}')
r19b = T.safe(load) if load else {"_exc": "없음"}
chk(r19b == {} and os.path.exists(PIN_PATH + ".bad") and not os.path.exists(PIN_PATH), "G19 최상위가 깨지면 .bad 로 옮기고 빈 저장소", [r19b, os.path.exists(PIN_PATH + ".bad")])
T.finish()
