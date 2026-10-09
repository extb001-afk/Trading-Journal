#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _ingest
from _ingest import check, W, Reader

import json
import os
import time
from datetime import datetime, timedelta, timezone

json.dump({"chains": {"eth": {"blockscout": "https://bs.invalid", "etherscan_chainid": 1, "conf_depth": 12, "blocks_per_day": 7200,
                              "rpcs": ["https://rpc.invalid"]},
                      "base": {"blockscout": "https://bs2.invalid", "conf_depth": 12, "blocks_per_day": 43200, "rpcs": ["https://rpc2.invalid"]}},
           "wallets": [{"type": "evm", "chain": "eth", "address": W, "label": "w"}, {"type": "evm", "chain": "base", "address": W, "label": "w"}],
           "native_symbol": {"eth": "ETH", "base": "ETH"}, "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
import common
import core
import db as dbm

assert T.TMP in common.STATE_DIR
KST = timezone(timedelta(hours=9))
DAY = 86400
NOW = int(time.time())
B = "0x" + "b2" * 20
C = "0x" + "c3" * 20
RT = "0x" + "d4" * 20
TKN, TKB = "0x" + "e1" * 20, "0x" + "e2" * 20
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
E18 = 10 ** 18


def h(n):
    return "0x" + ("%064x" % n)


def snap(hx, ts, frm, to, value, toks=(), fee=0, data="0x", internal=()):
    return {"tx": {"hash": hx, "from": frm, "to": to, "value": str(value), "fee": {"value": str(fee)}, "status": "ok", "raw_input": data,
                   "timestamp": ts, "block_number": 1000 + (ts % 100000), "block_hash": "0x" + "d" * 64},
            "token_transfers": [{"from": f, "to": t, "token": {"address": ca, "symbol": sym, "decimals": dec, "type": "ERC-20"},
                                 "total": {"value": str(v)}} for f, t, ca, sym, dec, v in toks],
            "internal": [{"from": f, "to": t, "value": str(v), "success": True} for f, t, v in internal]}


def feed(c, hx, s, chain="eth"):
    c._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": chain, "txhash": hx, "wallets": [W], "snapshot": s, "ts": 1}]), 0, 0)


def pos(c, sym, chain="eth"):
    tot = 0
    for r in c.conn.execute("SELECT p.qty_base, a.decimals FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                            " WHERE a.symbol=? AND a.chain=? AND p.location LIKE 'wallet:%'", (sym, chain)):
        tot += int(r["qty_base"]) / 10 ** int(r["decimals"] if r["decimals"] is not None else 18)
    return round(tot, 9)


def ev_of(c, hx, chain="eth"):
    r = c.conn.execute("SELECT event FROM tx_class WHERE chain=? AND txhash=?", (chain, hx)).fetchone()
    return r["event"] if r else None


c = core.Core(common.load_config())
c.conn.commit()
T_FUND, T_U1 = NOW - 60 * DAY, NOW - 30 * DAY
H_FUND, H_U1, H_U2, H_SELL = h(0xF0), h(0xA1), h(0xA2), h(0xA3)
feed(c, H_FUND, snap(H_FUND, T_FUND, B, W, 10 * E18))
check("전제: 10 ETH 외부 유입 = TRANSFER_IN", ev_of(c, H_FUND) == "TRANSFER_IN", ev_of(c, H_FUND))
c.conn.execute("UPDATE postings SET cost_usd='20000.0' WHERE source_id=? AND leg_kind='acq'", (H_FUND,))
c.conn.commit()
feed(c, H_U1, snap(H_U1, T_U1, W, C, E18, toks=[(C, W, TKN, "TKN", 18, 1000 * E18)], fee=E18 // 1000))
check("U1 calldata 없음 · 나감+들어옴 = UNKNOWN(분류 보류)", ev_of(c, H_U1) == "UNKNOWN", ev_of(c, H_U1))
check("U1 원장 ETH = 8.999(보낸 1 + 가스 0.001)", abs(pos(c, "ETH") - 8.999) < 1e-9, pos(c, "ETH"))
check("U1 원장 TKN = 1,000", abs(pos(c, "TKN") - 1000) < 1e-9, pos(c, "TKN"))
pc = {r["leg_kind"]: r["n"] for r in c.conn.execute(
    "SELECT leg_kind, COUNT(*) AS n FROM postings WHERE source_id=? GROUP BY leg_kind", (H_U1,))}
check("U1 레그 = 처분 1 · 취득 1 · 가스 1(가격 없는 교환 — 시세를 매기지 않음)", pc == {"disp": 1, "acq": 1, "gas": 1}, pc)
c._leg_px = lambda aid, ts: 2000.0
c.px.fx_at = lambda *a, **k: 1400.0
c._price_tx("eth", H_U1)
gas9 = c.conn.execute("SELECT cost_usd FROM postings WHERE source_id=? AND leg_kind='gas'", (H_U1,)).fetchone()[0]
check("U1 가스는 시세 매김(종전 그대로 · 0.001 × $2,000)", gas9 is not None and abs(float(gas9) - 2.0) < 1e-6, gas9)
nul = c.conn.execute("SELECT COUNT(*) FROM postings WHERE source_id=? AND leg_kind IN ('disp','acq') AND cost_usd IS NOT NULL",
                     (H_U1,)).fetchone()[0]
check("U1 가격 패스가 교환 레그에 시세를 안 매김(원가 넘기기 몫)", nul == 0, nul)
dm_n = 0
if os.path.exists(core.DM_PATH):
    dm_n = sum(1 for ln in open(core.DM_PATH, encoding="utf-8") if H_U1 in ln)
check("전제: U1 은 30일 전이라 6시간 알림 큐에 없음", dm_n == 0, dm_n)

T_U2 = NOW - 1200
feed(c, H_U2, snap(H_U2, T_U2, W, C, E18, toks=[(C, W, TKB, "TKB", 18, 500 * E18)], fee=E18 // 1000))
feed(c, H_SELL, snap(H_SELL, T_U2 + 300, W, RT, 0, toks=[(W, RT, TKB, "TKB", 18, 500 * E18), (RT, W, USDC, "USDC", 6, 3000 * 10 ** 6)],
                     data="0x12345678"))
check("전제: TKB 매도 = SWAP", ev_of(c, H_SELL) == "SWAP", ev_of(c, H_SELL))
c.conn.execute("UPDATE postings SET cost_usd='3000.0' WHERE source_id=? AND leg_kind IN ('disp','acq')", (H_SELL,))
c.conn.commit()
dm2 = sum(1 for ln in open(core.DM_PATH, encoding="utf-8") if H_U2 in ln and '"UNKNOWN"' in ln) if os.path.exists(core.DM_PATH) else 0
check("전제: U2 는 알림 큐에도 있음(중복 없애기 시험)", dm2 == 1, dm2)

W2 = "0x" + "a2" * 20
c.my_wallets.setdefault("base", set()).add(W2)
H_FB, H_U3 = h(0xB0), h(0xB3)
feed(c, H_FB, snap(H_FB, T_FUND, B, W, 2 * E18), chain="base")
c.conn.execute("UPDATE postings SET cost_usd='4000.0' WHERE source_id=? AND leg_kind='acq'", (H_FB,))
c.conn.commit()
feed(c, H_U3, snap(H_U3, T_U1, W, C, E18, toks=[(C, W2, "0x" + "e3" * 20, "TKC", 18, 10 * E18)], internal=[(C, W2, 4 * E18 // 10)]),
     chain="base")
l3 = sorted((r["leg_kind"], r["location"].split(":")[-1][:6], int(r["qty_base"])) for r in c.conn.execute(
    "SELECT leg_kind, location, qty_base FROM postings WHERE source_ns='base' AND source_id=?", (H_U3,)))
want3 = sorted([("move_out", W[:6], -4 * E18 // 10), ("move_in", W2[:6], 4 * E18 // 10), ("disp", W[:6], -6 * E18 // 10), ("acq", W2[:6], 10 * E18)])
check("U3 UNKNOWN · 내 지갑 간 0.4 ETH = 위치 이동 · 나머지 0.6 = 교환 처분 · TKC 취득", ev_of(c, H_U3, "base") == "UNKNOWN" and l3 == want3, l3)
c.my_wallets["base"].discard(W2)
check("원장 이더리움 ETH = 7.998(U1·U2 각 1 + 가스 0.001)", abs(pos(c, "ETH") - 7.998) < 1e-9, pos(c, "ETH"))
check("원장 베이스 ETH = 1.4(2 − 보낸 1 + 내 다른 지갑에 돌아온 0.4)", abs(pos(c, "ETH", "base") - 1.4) < 1e-9, pos(c, "ETH", "base"))
c.conn.close()

import acct_norm
import pricing
import web


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
except Exception as e:
    import traceback
    traceback.print_exc()
    st = {"_exc": f"{type(e).__name__}: {e}"}
f = (st or {}).get("fields") or {} if isinstance(st, dict) else {}
check("빌드 성공", bool(f), st if isinstance(st, dict) and st.get("_exc") else "fields 없음")
cards = f.get("_positionsAll") or f.get("positions") or []
pend = f.get("pendings") or []
rbd = {k: float(v) for k, v in (f.get("realizedByDate") or {}).items()}


def card(sym):
    return [p for p in cards if p.get("sym") == sym and str(p.get("chainKey") or p.get("chain") or "").lower() in ("eth", "ethereum", "이더리움", "")] \
        or [p for p in cards if p.get("sym") == sym]


def qty(p):
    return float(p.get("held") or 0)


eth9 = card("ETH")
tkn9 = card("TKN")
check("화면 ETH = 9.398(이더리움 7.998 + 베이스 1.4 — 같은 ETH 묶음)", any(abs(qty(p) - 9.398) < 1e-6 for p in eth9),
      [(p.get("sym"), p.get("held")) for p in eth9])
check("화면 TKN = 1,000", any(abs(qty(p) - 1000) < 1e-6 for p in tkn9), [(p.get("sym"), p.get("qty")) for p in tkn9])
check("U1 TKN 원가 = 보낸 ETH 소진 원가 $2,000(원가 넘기기 · 원가 미상 0)",
      any(abs(float(p.get("cost") or 0) - 2000) < 0.05 and abs(float(p.get("unknownQty") or 0)) < 1e-9 for p in tkn9),
      [(p.get("cost"), p.get("unknownQty")) for p in tkn9])
check("U3 TKC 원가 = 교환된 0.6 ETH 소진 원가 $1,200(이동분 0.4 는 원가 그대로)",
      any(abs(float(p.get("cost") or 0) - 1200) < 0.05 for p in card("TKC")), [(p.get("sym"), p.get("cost")) for p in card("TKC")])
d_u1 = datetime.fromtimestamp(T_U1, KST).strftime("%Y-%m-%d")
check("U1 교환 날 실현 = 가스 비용만 −$2(가격 없는 교환 — 손익 없음)", abs(rbd.get(d_u1, 0.0) + 2.0) < 0.005, rbd)
d_u2 = datetime.fromtimestamp(T_U2 + 300, KST).strftime("%Y-%m-%d")
check("U2 TKB 매도 실현 +$1,000(3,000 − 넘겨받은 원가 2,000)", abs(rbd.get(d_u2, 0.0) - 1000) < 0.05, rbd)
unk = [p for p in pend if p.get("kind") == "분류 보류"]
u1 = [p for p in unk if str(p.get("tx") or "").lower() == H_U1]
u2 = [p for p in unk if str(p.get("tx") or "").lower() == H_U2]
check("U1 '분류 보류' 검토 1건(알림 큐에 없어도 원장에서) · 보임", len(u1) == 1 and not u1[0].get("hide"), u1 or unk)
check("U2 '분류 보류' 검토 1건(알림·원장 중복 없음) · 보임", len(u2) == 1 and not u2[0].get("hide"), u2 or unk)
check("검토 행에 코인 이름(원장 레그) · 금액 없음", bool(u1) and "TKN" in str(u1[0].get("sym")) and "ETH" in str(u1[0].get("sym"))
      and not any(k9 in u1[0] for k9 in ("usd", "qty")), u1)
check("미매칭(원가미상 매도) 검토에 TKB 없음 — 원가가 넘어갔다",
      not [p for p in pend if p.get("sym") == "TKB" and str(p.get("key") or "").startswith(("unv:", "unkh:", "noproc:", "unvlost:"))],
      [p for p in pend if p.get("sym") == "TKB"])
conn9 = dbm.open_db(os.path.join(common.STATE_DIR, "ledger.db"), readonly=True)
try:
    GG, LIVE = {}, {}
    for r9 in conn9.execute("SELECT asset_id, group_id, symbol FROM assets"):
        g9 = r9["group_id"] or -r9["asset_id"]
        GG[g9] = {"sym": r9["symbol"], "is_stable": r9["symbol"] == "USDC", "qty_timeline": []}
        LIVE[g9] = {"ETH": 2000.0, "TKB": 6.0, "TKN": 2.0, "TKC": 120.0}.get(r9["symbol"], 1.0)
    T0 = datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0)
    ROWS30 = [{"date": (T0 - timedelta(days=i)).strftime("%m-%d"), "val": 0} for i in range(29, -1, -1)]
    fl9 = b._daily_flows(conn9, ROWS30, GG, T0, LIVE, frozenset(), 1384.0)
finally:
    conn9.close()
td9 = fl9.get(datetime.fromtimestamp(T_U2, KST).strftime("%m-%d")) or (0, [])
check("U2 날 순유입 = 0 · 'UNKNOWN' 입출금 줄 없음(분류 보류 교환 = 매매 — 일별 성과 분해·곡선 순유입에 안 섞임)",
      abs(float(td9[0] or 0)) < 0.005 and not any("UNKNOWN" in str(x9[0]) for x9 in (td9[1] or [])), td9)
conn9 = dbm.open_db(os.path.join(common.STATE_DIR, "ledger.db"), readonly=True)
try:
    p9 = b._pendings(conn9, {"ignored": [f"UNKNOWN:{H_U1}"]})
finally:
    conn9.close()
check("U4 무시한 검토 키 = 원장 행도 숨김 · 다른 행은 그대로",
      not [p for p in p9 if str(p.get("tx") or "").lower() == H_U1] and [p for p in p9 if str(p.get("tx") or "").lower() == H_U2],
      [(p.get("key"), p.get("kind")) for p in p9])
T.finish()
