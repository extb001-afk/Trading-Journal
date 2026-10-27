#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402, F401
from _ingest import W, Reader  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
from decimal import Decimal, localcontext  # noqa: E402

json.dump({"chains": {"eth": {"blockscout": "https://bs.invalid", "etherscan_chainid": 1, "conf_depth": 12, "blocks_per_day": 7200,
                              "rpcs": ["https://rpc.invalid"]}},
           "wallets": [{"type": "evm", "chain": "eth", "address": W, "label": "w"}],
           "native_symbol": {"eth": "ETH"}, "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
os.environ["TJ_NEGABS"] = "0"
import config, paths, statefile  # noqa: E402
import core  # noqa: E402
import health  # noqa: E402

assert T.TMP in paths.STATE_DIR
chk = T.chk
X = "0x" + "c8" * 20
TA, TB, TC, TD, TP, TS = ("0x" + x * 20 for x in ("e1", "e2", "e3", "e4", "e5", "e6"))
NOW = int(time.time())
LOC = f"wallet:eth:{W.lower()}"


def leg(f, t, ca, v, dec=None):
    return {"from": {"hash": f}, "to": {"hash": t}, "token": {"address": ca, "symbol": "T" + ca[2:4], "decimals": dec, "type": "ERC-20"},
            "total": {"value": str(v)}}


def snap(hx, ts, blk, frm, to, legs):
    return {"tx": {"hash": hx, "from": frm, "to": to, "value": "0", "fee": {"value": "0"}, "status": "ok", "raw_input": "0xa9059cbb",
                   "timestamp": ts, "block_number": blk, "block_hash": "0x" + "d" * 64},
            "token_transfers": legs, "internal": []}


def h(n):
    return "0x" + ("%064x" % n)


c = core.Core(config.load_config())
c.conn.commit()
HS = health.settings({"health": {"units": ["tj-core"]}})


def feed(n, legs, frm=None, to=None, ts=None):
    s = snap(h(n), ts or NOW - 86400 + n, 100 + n, frm or X, to or W, legs)
    c._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": h(n), "wallets": [W], "snapshot": s, "ts": 1}]), 0, 0)


def aid_of(ca):
    r = c.conn.execute("SELECT asset_id FROM assets WHERE address=?", (ca,)).fetchone()
    return r[0] if r else None


def gid_of(ca):
    r = c.conn.execute("SELECT group_id FROM assets WHERE address=?", (ca,)).fetchone()
    return r[0] if r else None


def pos(gid, loc=LOC):
    r = c.conn.execute("SELECT qty_norm FROM positions WHERE group_id=? AND location=?", (gid, loc)).fetchone()
    return None if r is None else Decimal(r[0])


def pos_map(conn):
    return {(int(g), loc): Decimal(q) for g, loc, q in conn.execute("SELECT group_id, location, qty_norm FROM positions").fetchall()}


def ledger_map(conn):
    out = {}
    with localcontext() as ctx:
        ctx.prec = 100
        for g, loc, qb, dec in conn.execute("SELECT a.group_id, p.location, p.qty_base, a.decimals FROM postings p"
                                            " JOIN assets a ON a.asset_id=p.asset_id").fetchall():
            k = (int(g), loc)
            out[k] = out.get(k, Decimal(0)) + Decimal(int(qb)) / (Decimal(10) ** (18 if dec is None else int(dec)))
    return out


def same_maps(a, b):
    return all(a.get(k, Decimal(0)) == b.get(k, Decimal(0)) for k in set(a) | set(b))


def renorm_panel(doc, now=None):
    out = []
    chk_add = (lambda cid, unit, title, level, detail="", action="", **k: out.append({"id": cid, "title": title, "level": level}))
    import chk_base
    chk_base.decwait_item(chk_add, lambda t: None, doc, ["tj-core"], (), now or time.time())
    return {x["id"]: x for x in out}


feed(1, [leg(X, W, TA, 100)])
aa, ga = aid_of(TA), gid_of(TA)
pl = c.conn.execute("SELECT qty_base FROM postings WHERE asset_id=?", (aa,)).fetchall()
chk([r[0] for r in pl] == ["100"], "R1 원장 1줄 qty_base='100'(자릿수와 무관하게 정확)", [tuple(r) for r in pl])
chk(pos(ga) == Decimal(100) / Decimal(10) ** 18, "R1 positions = 임시 해석(18 — 재구축과 같은 값 · 종전 표시와 같음)", pos(ga))
try:
    c._norm(aa, 100)
    r1n = "예외 없음"
except core.MissingDecimals:
    r1n = True
chk(r1n is True, "R1 Core._norm(자릿수 NULL) = MissingDecimals(18 로 지어내지 않음)", r1n)
chk(same_maps(pos_map(c.conn), ledger_map(c.conn)), "E1 R1 뒤 positions = Σ 원장 정규화")

ISS = []
_orig_issue = c._dec_issue
c._dec_issue = lambda *a, **k: (ISS.append(a), _orig_issue(*a, **k))
feed(2, [leg(X, W, TA, 50, dec="6")])
chk(pos(ga) == Decimal("0.00015"), "R2 같은 패스에서 positions = (100+50)/10^6 = 0.00015(앞 입금 재정규화 + 이번 입금)", pos(ga))
chk(not ISS and c._meta_get("ext_prewindow:decimals_fix") is None, "R2 _dec_issue 0회 · 재구축 표식 없음(재구축 불필요)", (ISS, c._meta_get("ext_prewindow:decimals_fix")))
chk(same_maps(pos_map(c.conn), ledger_map(c.conn)), "E1 R2 뒤 positions = Σ 원장 정규화")
c._dec_issue = _orig_issue

feed(3, [leg(X, W, TB, 2 * 10 ** 6, dec="6")])
feed(4, [leg(X, W, TC, 100)])
gb, ac = gid_of(TB), aid_of(TC)
gc0 = gid_of(TC)
c.conn.execute("DELETE FROM positions WHERE group_id=?", (gc0,))
c.conn.execute("UPDATE assets SET group_id=? WHERE asset_id=?", (gb, ac))
c._renorm_asset(aid_of(TB))
c.conn.commit()
chk(pos(gb) == Decimal(2) + Decimal(100) / Decimal(10) ** 18,
    "R3 6 자산 재정규화 = NULL 몫은 임시 해석 그대로(지어내지 않음)", pos(gb))
c.conn.execute("BEGIN")
c.asset_id("token", "eth", TC, decimals=2)
c.conn.commit()
chk(pos(gb) == Decimal(3), "R3 NULL 쪽 자릿수(2) 도착 = 한 번에 정확(2 + 100/10^2 = 3)", pos(gb))
chk(same_maps(pos_map(c.conn), ledger_map(c.conn)), "E1 R3 뒤 positions = Σ 원장 정규화")

BIG = 10 ** 28
feed(5, [leg(X, W, TD, BIG)])
feed(6, [leg(X, W, TD, BIG + 7)])
gd = gid_of(TD)
import histmark  # noqa: E402
c.conn.execute("DELETE FROM meta WHERE k=?", (histmark.HIST_LATE_K,))
c.conn.commit()
c.conn.execute("BEGIN")
c.asset_id("token", "eth", TD, decimals=20)
c.conn.commit()
t5 = c.conn.execute("SELECT MIN(event_ts) FROM postings WHERE asset_id=?", (aid_of(TD),)).fetchone()[0]
d5 = time.strftime("%Y-%m-%d", time.gmtime(t5 + 9 * 3600))
chk([m[1] for m in histmark.hist_late_read(c.conn)] == [d5],
    "R5 자릿수 도착(18 아님) = 늦은 행 표식 = 그 자산 첫 기장 날(동결된 지난날 곡선 재계산 · 순잔고와 무관)", (histmark.hist_late_read(c.conn), d5))
with localcontext() as ctx5:
    ctx5.prec = 100
    want5 = Decimal(2 * BIG + 7) / Decimal(10) ** 20
chk(pos(gd) == want5 and str(c.conn.execute("SELECT qty_norm FROM positions WHERE group_id=?", (gd,)).fetchone()[0]) == "200000000.00000000000000000007",
    "R5 2^63 넘는 합 = 파이썬 int 합산 — 정확(200000000.00000000000000000007)", pos(gd))

feed(7, [leg(X, W, TS, 10 * 10 ** 6, dec="6")])
feed(8, [leg(W, X, TP, 500), leg(X, W, TS, 10 * 10 ** 6, dec="6")], frm=W, to=X)
ev8 = c.conn.execute("SELECT DISTINCT event FROM postings WHERE source_id=?", (h(8),)).fetchall()
sv = c.svc_price
PX = {aid_of(TP): 5.0, aid_of(TS): 2.0}
sv._leg_px = lambda aid, ts: PX.get(aid)
sv.px.fx_at = lambda ms: 1300.0
c.conn.execute("UPDATE postings SET cost_usd=NULL, cost_krw=NULL WHERE source_id=? AND event='SWAP'", (h(8),))
c.conn.commit()
sv._price_tx("eth", h(8))
cs = {r[0]: r[1] for r in c.conn.execute("SELECT leg_kind, cost_usd FROM postings WHERE source_id=? AND event='SWAP'", (h(8),)).fetchall()}
chk([tuple(r) for r in ev8] == [("SWAP",)] and cs.get("disp") is not None and abs(float(cs["disp"]) - 20.0) < 1e-9 and abs(float(cs.get("acq") or 0) - 20.0) < 1e-9,
    "P1 유출 쪽 자릿수 모름 = '시세 모름' → 유입 쪽 값(10×$2=$20)으로 양쪽 확정(종전 18 가정 수량 × $5 ≈ 0)", ([tuple(r) for r in ev8], cs))

c.conn.execute("UPDATE assets SET group_id=? WHERE asset_id=?", (gc0, ac))
c.conn.execute("DELETE FROM positions")
c.conn.commit()
for (a9,) in c.conn.execute("SELECT DISTINCT asset_id FROM postings").fetchall():
    c._renorm_asset(a9)
c.conn.commit()
pre = pos_map(c.conn)
for t9 in ("postings", "tx_class", "transfers", "positions"):
    c.conn.execute(f"DELETE FROM {t9}")
c.conn.commit()
for r in c.conn.execute("SELECT chain, txhash, snapshot FROM raw_txs ORDER BY ingested_at, chain, txhash").fetchall():
    c.conn.execute("BEGIN")
    c.apply(r["chain"], r["txhash"], "", json.loads(r["snapshot"]))
    c.conn.commit()
post = pos_map(c.conn)
chk(pre and same_maps(pre, post), "E1 재구축 positions == 재정규화 positions(같은 원장 → 같은 수량 · 칸 %d)" % len(pre),
    sorted((k, str(pre.get(k)), str(post.get(k))) for k in set(pre) | set(post) if pre.get(k, Decimal(0)) != post.get(k, Decimal(0))))

feed(20, [leg(X, W, TA[:-2] + "77", 300)])
TM = TA[:-2] + "77"
am, gm = aid_of(TM), gid_of(TM)
chk(pos(gm) == Decimal(300) / Decimal(10) ** 18, "R4 준비: 옛 판 = 18 해석 positions", pos(gm))
statefile.atomic_write_json(c.DEC_ISSUES_PATH, {"ts": NOW, "items": {str(am): {"kind": "pending", "chain": "eth", "address": TM, "symbol": "T77",
                                                                                 "stored": None, "seen": 6, "ts": NOW}}})
c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_prewindow:decimals_fix', '1')")
c.conn.commit()
c.conn.close()
c = core.Core(config.load_config())
c._dec_wait_scan(force=True)
doc = statefile.read_json(c.DEC_WAIT_PATH, {})
items = (statefile.read_json(c.DEC_ISSUES_PATH, {}) or {}).get("items") or {}
chk(pos(gm) == Decimal("0.0003") and c._meta_get("ext_prewindow:decimals_fix") is None and str(am) not in items,
    "R4 첫 기동 = 채움 + 재정규화(0.0003) · 재구축 표식 내림 · 대기 항목 정리", (pos(gm), c._meta_get("ext_prewindow:decimals_fix"), items))
p4 = renorm_panel(doc)
chk((doc.get("renorm") or {}).get("n") == 1 and "ledger:renorm" in p4 and "1개" in p4["ledger:renorm"]["title"] and p4["ledger:renorm"]["level"] == "ok",
    "R4 상태 패널 ledger:renorm 1개(정보)", (doc.get("renorm"), p4))
chk("ledger:renorm" not in renorm_panel(doc, now=time.time() + 86400 + 60), "R4 24시간 뒤 = 줄 없음")
m1 = pos_map(c.conn)
c.conn.close()
c = core.Core(config.load_config())
chk(pos_map(c.conn) == m1 and not c.__dict__.get("_renorm_info"), "R4 두 번째 기동 = 무변화(멱등 · 새 재정규화 0)")
chk(same_maps(pos_map(c.conn), ledger_map(c.conn)), "E1 R4 뒤 positions = Σ 원장 정규화")
c.conn.close()
T.finish()
