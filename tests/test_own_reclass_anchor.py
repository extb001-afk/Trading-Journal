#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402
from _ingest import check, W, Reader  # noqa: E402

import glob  # noqa: E402
import importlib.util  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402
import time  # noqa: E402
from contextlib import redirect_stdout  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

W2 = "0x" + "a2" * 20
W3 = "0x" + "a3" * 20
CH = {"eth": {"blockscout": "https://bs.invalid", "etherscan_chainid": 1, "conf_depth": 12, "blocks_per_day": 7200,
              "rpcs": ["https://rpc.invalid"]}}


def write_cfg(ws):
    json.dump({"chains": CH, "wallets": [{"type": "evm", "chain": "eth", "address": w} for w in ws],
               "native_symbol": {"eth": "ETH"}, "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))


write_cfg([W])
import config, histmark, paths  # noqa: E402
import core  # noqa: E402
import core_svc  # noqa: E402

T.patch_moved("dm", lambda *a, **k: None)

core_svc.PriceService._price_tx = lambda self, *a, **k: None
spec = importlib.util.spec_from_file_location("rb2", os.path.join(T.ROOT, "tools", "rebuild2.py"))
rb2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rb2)
KST = timezone(timedelta(hours=9))
DAY = 86400
E18 = 10 ** 18
E6 = 10 ** 6
NOW = int(time.time())
X = "0x" + "b7" * 20
USDC = "0x" + "c6" * 20
SD = paths.STATE_DIR
OUTF = os.path.join(SD, "outflow_decisions.json")
TS_IN, TS_OUT = NOW - 120 * DAY, NOW - 100 * DAY


def iso(ts):
    return datetime.fromtimestamp(int(ts), KST).strftime("%Y-%m-%d")


def h(n):
    return "0x" + ("%064x" % n)


def reset(ws=(W,)):
    for p9 in glob.glob(os.path.join(SD, "*")):
        if os.path.isfile(p9):
            os.remove(p9)
    write_cfg(list(ws))


def new_core():
    c = core.Core(config.load_config())
    c.conn.commit()
    return c


def esnap(hx, ts, blk, frm, to, value=0, toks=(), fee=0):
    return {"tx": {"hash": hx, "from": frm, "to": to, "value": str(value), "fee": {"value": str(fee)}, "status": "ok", "raw_input": "0x",
                   "timestamp": ts, "block_number": blk, "block_hash": "0x" + "d" * 64},
            "token_transfers": [{"from": f, "to": t, "token": {"address": USDC, "symbol": "USDC", "decimals": "6", "type": "ERC-20"},
                                 "total": {"value": str(v), "decimals": "6"}} for (f, t, v) in toks],
            "internal": []}


def feed(c, hx, snap, wallets=(W,)):
    c._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": hx, "wallets": list(wallets), "snapshot": snap, "ts": 1}]), 0, 0)


def age_ingest(c, sec=7200):
    c.conn.execute("UPDATE raw_txs SET ingested_at=ingested_at-?", (sec,))
    c.conn.commit()


def recon_full(c, per):
    c.svc_recon._scope_ready = lambda s: True
    c.svc_recon._recon_quiet = lambda *a: True
    c.svc_recon._recon_bal = lambda chain, kind, mode, wallets: ({"per_wallet": per[chain]} if chain in per else None)
    c.svc_recon._last_recon = 0
    c.svc_recon.recon_pass(set())
    for k9 in ("_scope_ready", "_recon_quiet", "_recon_bal"):
        c.svc_recon.__dict__.pop(k9, None)
    c.conn.commit()
    c.__dict__.pop("_recon_cache", None)


def wrecon(c, w, bal, extra=None):
    b9 = {"per_wallet": {w: bal}}
    b9.update(extra or {})
    c.svc_recon._recon_bal = lambda chain, kind, md, wallets: b9
    c.svc_recon._wallet_backfilled = lambda *a: True
    c.svc_recon._recon_quiet = lambda *a: True
    c.svc_recon._wrecon_run("eth", "evm", "evm", set(), c._win_t0(None, "eth"), True, "new", [w])
    for k9 in ("_recon_bal", "_wallet_backfilled", "_recon_quiet"):
        c.svc_recon.__dict__.pop(k9, None)
    c.conn.commit()


def own(addrs, chains=("eth",)):
    json.dump({"decisions": {a: {"verdict": "own", "chains": list(chains), "ts": NOW} for a in addrs}}, open(OUTF, "w"))


def aid_native(c):
    return c.conn.execute("SELECT asset_id FROM assets WHERE chain='eth' AND kind='native'").fetchone()[0]


def aid_usdc(c):
    return c.conn.execute("SELECT asset_id FROM assets WHERE chain='eth' AND kind='token' AND address=?", (USDC,)).fetchone()[0]


def cell(conn, aid, w):
    return sum(int(r[0]) for r in conn.execute("SELECT qty_base FROM postings WHERE asset_id=? AND location=?", (aid, f"wallet:eth:{w}")))


def pos(c, aid, w):
    g = c.conn.execute("SELECT group_id FROM assets WHERE asset_id=?", (aid,)).fetchone()[0]
    r = c.conn.execute("SELECT qty_norm FROM positions WHERE group_id=? AND location=?", (g, f"wallet:eth:{w}")).fetchone()
    return float(r[0]) if r else 0.0


def anchors(conn, w):
    return sorted((str(r[0]), int(r[1]), int(r[2]), int(r[3])) for r in conn.execute(
        "SELECT source_id, asset_id, qty_base, event_ts FROM postings WHERE source_kind='opening' AND location=?", (f"wallet:eth:{w}",)))


def outs(conn, w):
    return sum(int(r[0]) for r in conn.execute("SELECT qty_base FROM postings WHERE location=?", (f"out:eth:{w}",)))


def min_mark(c):
    m9 = histmark.hist_late_read(c.conn)
    return min(m[1] for m in m9) if m9 else None


def shadow(c, tag):
    c.conn.commit()
    bp, sp = os.path.join(T.TMP, f"or_base_{tag}.db"), os.path.join(T.TMP, f"or_shadow_{tag}.db")
    for p9 in (bp, sp):
        if os.path.exists(p9):
            os.remove(p9)
        d9 = sqlite3.connect(p9)
        c.conn.backup(d9)
        d9.close()
    anc = [tuple(r) for r in sqlite3.connect(bp).execute(rb2.ANCHOR_SQL).fetchall()]
    old9 = paths.DB_PATH
    paths.DB_PATH = sp
    try:
        sc = core.Core(config.load_config())
    finally:
        paths.DB_PATH = old9
    for t9 in rb2.DERIVED_TABLES:
        sc.conn.execute(f"DELETE FROM {t9}")
    sc.conn.commit()
    for r in sc.conn.execute("SELECT chain, txhash, snapshot FROM raw_txs ORDER BY ingested_at, chain, txhash").fetchall():
        sc.conn.execute("BEGIN")
        sc.apply(r["chain"], r["txhash"], "", json.loads(r["snapshot"]))
        sc.conn.commit()
    obs = {r[0]: r[1] for r in sc.conn.execute("SELECT obs_id, observed_at FROM raw_observations")}
    meta = {r[0]: int(r[1]) for r in sc.conn.execute("SELECT k, v FROM meta WHERE k LIKE 'recon_done_%'")}
    rb2.recompute_anchors(bp, sc.conn, sc, anc, obs, meta)
    sc.conn.commit()
    return sc


FEE = E18 // 1000
OUT_TX = esnap(h(2), TS_OUT, 2000, W, W2, value=10 * E18, fee=FEE)


def base(c):
    feed(c, h(1), esnap(h(1), TS_IN, 1000, X, W, value=11 * E18))
    feed(c, h(2), OUT_TX)
    age_ingest(c)
    recon_full(c, {"eth": {W: {("native", None): 11 * E18 - 10 * E18 - FEE}}})


def scenario_a(old_path=False):
    reset()
    c = new_core()
    base(c)
    c.conn.close()
    write_cfg([W, W2])
    c = new_core()
    wrecon(c, W2, {("native", None): 10 * E18})
    own([W2])
    if old_path:
        c._rederive_tx_anchor_safe = c._rederive_tx
    c.outflow_pass(force=True)
    c.__dict__.pop("_rederive_tx_anchor_safe", None)
    return c


c = scenario_a()
A = aid_native(c)
wt = int(float(c._meta_get(f"wrecon_done:eth:{W2}")))
check("O1 (전제) own 재분류 = W→W2 가 내 지갑 간 이동(out: 0 · 적용 도장 own:1)", outs(c.conn, W2) == 0
      and str(c._meta_get(f"outflow_applied:{W2}")).startswith("own:1"), (outs(c.conn, W2), c._meta_get(f"outflow_applied:{W2}")))
check("O1 ★W2 보유 = 10 ETH(실잔고 · 종전 20)★", cell(c.conn, A, W2) == 10 * E18, (cell(c.conn, A, W2), anchors(c.conn, W2)))
check("O1 ★받는 지갑 기초 잔고 10 → 0(행 삭제)★ · 보유 캐시(positions) 10", anchors(c.conn, W2) == [] and abs(pos(c, A, W2) - 10) < 1e-9,
      (anchors(c.conn, W2), pos(c, A, W2)))
check("O1 보낸 쪽 W 무변(0.999 · 기초 잔고 없음)", cell(c.conn, A, W) == 11 * E18 - 10 * E18 - FEE and anchors(c.conn, W) == [],
      (cell(c.conn, A, W), anchors(c.conn, W)))
check("O1 지난 곡선 다시 계산 표식 = 고친 기초 잔고 날(창 시작 쪽 — 같은 트랜잭션)", min_mark(c) is not None and min_mark(c) <= iso(c._win_t0(wt, "eth")),
      (histmark.hist_late_read(c.conn), iso(c._win_t0(wt, "eth"))))

n0 = c.conn.execute("SELECT COUNT(*), MAX(posting_id) FROM postings").fetchone()
mk0 = histmark.hist_late_read(c.conn)
c.outflow_pass(force=True)
check("O2 같은 판정 반복 = 원장·표식 무변", tuple(c.conn.execute("SELECT COUNT(*), MAX(posting_id) FROM postings").fetchone()) == tuple(n0)
      and histmark.hist_late_read(c.conn) == mk0 and cell(c.conn, A, W2) == 10 * E18, (cell(c.conn, A, W2),))
c.conn.close()
c = new_core()
c.outflow_pass(force=True)
check("O2 재시작 뒤 패스 = 10 그대로", cell(c.conn, A, W2) == 10 * E18 and anchors(c.conn, W2) == [], (cell(c.conn, A, W2), anchors(c.conn, W2)))
feed(c, h(2), OUT_TX, wallets=(W2,))
check("O2 뒤늦은 수집기 새 관점 재방출 = 10 그대로(관점만 합침 · 앵커 무변)", cell(c.conn, A, W2) == 10 * E18 and anchors(c.conn, W2) == []
      and cell(c.conn, A, W) == 11 * E18 - 10 * E18 - FEE, (cell(c.conn, A, W2), anchors(c.conn, W2), cell(c.conn, A, W)))

c.conn.close()
c = new_core()
c._rederive_tx_anchor_safe = c._rederive_tx
c.outflow_pass(force=True)
check("O2 이전 코드로 롤백·재기동 = 10 그대로(적용 도장 같음 → 재기장 없음)", cell(c.conn, A, W2) == 10 * E18 and anchors(c.conn, W2) == [],
      (cell(c.conn, A, W2), anchors(c.conn, W2)))
c.__dict__.pop("_rederive_tx_anchor_safe", None)

sc = shadow(c, "o3")
check("O3 ★rebuild2 재구축 = 직접 적용 결과(W2 10 · 기초 잔고 없음 · W 0.999)★", cell(sc.conn, A, W2) == 10 * E18 and anchors(sc.conn, W2) == []
      and cell(sc.conn, A, W) == cell(c.conn, A, W), (cell(sc.conn, A, W2), anchors(sc.conn, W2)))
sc.conn.close()
c.conn.close()

reset()
c = new_core()
base(c)
c.conn.close()
write_cfg([W, W2])
c = new_core()
own([W2])
c.outflow_pass(force=True)
wrecon(c, W2, {("native", None): 10 * E18})
check("O4 (대조) 대사 전 own 재분류 = W2 10 · 기초 잔고 없음", cell(c.conn, A, W2) == 10 * E18 and anchors(c.conn, W2) == [],
      (cell(c.conn, A, W2), anchors(c.conn, W2)))
c.conn.close()

reset()
c = new_core()
base(c)
write_cfg([W, W2])
own([W2])
json.dump({"v": 1, "pairs": {}}, open(paths.ACTIVITY_GATE_PATH, "w"))
c._last_outflow = 0
c.outflow_pass()
check("O5 (전제) 옛 core = own:0 도장(아직 W2 모름 · 재기장 없음)", str(c._meta_get(f"outflow_applied:{W2}")).startswith("own:0") and outs(c.conn, W2) == 10 * E18,
      (c._meta_get(f"outflow_applied:{W2}"), outs(c.conn, W2)))
c.svc_recon._gate_at = 0
added = c.svc_recon._gate_reload()
check("O5 (전제) 활동 게이트 hot-add = W2 합류(재기동 없이)", added == 1 and W2 in c.my_wallets.get("eth", set()), (added, c.my_wallets))
c.svc_recon._scope_ready = lambda s: True
c.svc_recon._wallet_backfilled = lambda *a: True
c.svc_recon._recon_quiet = lambda *a: True
c.svc_recon._recon_bal = lambda chain, kind, md, wallets: {"per_wallet": {W2: {("native", None): 10 * E18}}}
c.svc_recon._last_recon = 0
c.svc_recon.recon_pass(set())
for k9 in ("_scope_ready", "_wallet_backfilled", "_recon_quiet", "_recon_bal"):
    c.svc_recon.__dict__.pop(k9, None)
check("O5 (전제) 대사가 먼저 = W2 기초 잔고 10", [a[2] for a in anchors(c.conn, W2)] == [10 * E18], anchors(c.conn, W2))
c._last_outflow = time.time() - 61
c.outflow_pass()
A = aid_native(c)
check("O5 ★60초 뒤 outflow = own:1 재분류 · W2 10(종전 20)★", str(c._meta_get(f"outflow_applied:{W2}")).startswith("own:1")
      and cell(c.conn, A, W2) == 10 * E18 and anchors(c.conn, W2) == [], (c._meta_get(f"outflow_applied:{W2}"), cell(c.conn, A, W2), anchors(c.conn, W2)))
c.conn.close()

reset()
c = new_core()
feed(c, h(31), esnap(h(31), TS_IN, 1000, X, W, toks=[(X, W, 30 * E6)], value=E18))
feed(c, h(32), esnap(h(32), TS_OUT, 2000, W, USDC, toks=[(W, W2, 10 * E6), (W, W3, 4 * E6)], fee=FEE))
age_ingest(c)
recon_full(c, {"eth": {W: {("native", None): E18 - FEE, ("token", USDC): 16 * E6}}})
c.conn.close()
write_cfg([W, W2, W3])
c = new_core()
wrecon(c, W2, {("native", None): 0, ("token", USDC): 15 * E6})
wrecon(c, W3, {("native", None): 0, ("token", USDC): 4 * E6})
AU = aid_usdc(c)
check("O6 (전제) 기초 잔고 W2 15 · W3 4 USDC", [a[2] for a in anchors(c.conn, W2)] == [15 * E6] and [a[2] for a in anchors(c.conn, W3)] == [4 * E6],
      (anchors(c.conn, W2), anchors(c.conn, W3)))
own([W2, W3])
c.outflow_pass(force=True)
check("O6 ★ERC-20(6자리) W2 = 15(기초 잔고 15 → 5 · 받은 10) · W3 = 4(4 → 0 삭제)★",
      cell(c.conn, AU, W2) == 15 * E6 and [a[2] for a in anchors(c.conn, W2)] == [5 * E6] and cell(c.conn, AU, W3) == 4 * E6 and anchors(c.conn, W3) == [],
      (cell(c.conn, AU, W2), anchors(c.conn, W2), cell(c.conn, AU, W3), anchors(c.conn, W3)))
A = aid_native(c)
check("O6 보낸 쪽 W(USDC 16 · 수수료 ETH) 무변", cell(c.conn, AU, W) == 16 * E6 and cell(c.conn, A, W) == E18 - FEE, (cell(c.conn, AU, W), cell(c.conn, A, W)))
sc = shadow(c, "o6")
check("O6 rebuild2 = 같은 결과(W2 15 · 기초 5 · W3 4)", cell(sc.conn, AU, W2) == 15 * E6 and [a[2] for a in anchors(sc.conn, W2)] == [5 * E6]
      and cell(sc.conn, AU, W3) == 4 * E6 and anchors(sc.conn, W3) == [], (cell(sc.conn, AU, W2), anchors(sc.conn, W2), anchors(sc.conn, W3)))
sc.conn.close()
c.conn.close()

reset()
c = new_core()
base(c)
c.conn.close()
write_cfg([W, W2])
c = new_core()
wrecon(c, W2, {("native", None): 2 * E18})
A = aid_native(c)
own([W2])
c.outflow_pass(force=True)
wt7 = int(float(c._meta_get(f"wrecon_done:eth:{W2}")))
a7 = anchors(c.conn, W2)
check("O7 ★부호 전환 = 기초 잔고 +2 → −8(대사 시각) · W2 = 2(실잔고)★", cell(c.conn, A, W2) == 2 * E18 and [(a[2], a[3]) for a in a7] == [(-8 * E18, wt7)],
      (cell(c.conn, A, W2), a7, wt7))
c.conn.close()

for tag, blk_rx, want_anchor in (("same", 2000, []), ("next", 2001, [10 * E18])):
    reset()
    c = new_core()
    feed(c, h(1), esnap(h(1), TS_IN, 1000, X, W, value=11 * E18))
    feed(c, h(2), esnap(h(2), TS_OUT, blk_rx, W, W2, value=10 * E18, fee=FEE))
    age_ingest(c)
    recon_full(c, {"eth": {W: {("native", None): 11 * E18 - 10 * E18 - FEE}}})
    c.conn.close()
    write_cfg([W, W2])
    c = new_core()
    wrecon(c, W2, {("native", None): 10 * E18 if blk_rx == 2000 else 0},
           extra={"_source": "rpc", "_block": 2000, "_block_ts": TS_OUT + (0 if blk_rx == 2000 else -1)})
    if blk_rx != 2000:
        c.conn.execute("UPDATE raw_observations SET observed_at=? WHERE obs_id=?", (TS_OUT, f"recon:eth:{W2}"))
        c.conn.execute("UPDATE meta SET v=? WHERE k=?", (str(TS_OUT), f"wrecon_done:eth:{W2}"))
        c.conn.commit()
    A = aid_native(c)
    own([W2])
    c.outflow_pass(force=True)
    check(f"O8 동블록 경계({tag}) — 받은 블록 {'= 관측 블록 → 기초 잔고 흡수' if blk_rx == 2000 else '> 관측 블록 → 기초 잔고 무변'} · W2 = 10",
          cell(c.conn, A, W2) == 10 * E18 and [a[2] for a in anchors(c.conn, W2)] == [], (cell(c.conn, A, W2), anchors(c.conn, W2)))
    c.conn.close()

reset()
c = new_core()
base(c)
c.conn.close()
write_cfg([W, W2])
c = new_core()
wrecon(c, W2, {("native", None): 10 * E18})
A = aid_native(c)
own([W2])
snap9 = (cell(c.conn, A, W2), anchors(c.conn, W2), pos(c, A, W2), outs(c.conn, W2), histmark.hist_late_read(c.conn), c._meta_get(f"outflow_applied:{W2}"))
real_put = histmark.hist_late_put


def boom(conn, ts, now=None):
    real_put(conn, ts, now)
    raise RuntimeError("시험: 표식 쓴 직후 예외")


histmark.hist_late_put = boom
err = None
try:
    c.outflow_pass(force=True)
except RuntimeError as e:
    err = e
finally:
    histmark.hist_late_put = real_put
check("O9 ★예외 = 롤백 — 받는 레그·기초 잔고·보유 캐시·out:·표식·적용 도장 모두 그대로★", err is not None and
      (cell(c.conn, A, W2), anchors(c.conn, W2), pos(c, A, W2), outs(c.conn, W2), histmark.hist_late_read(c.conn), c._meta_get(f"outflow_applied:{W2}")) == snap9,
      (err, snap9, cell(c.conn, A, W2), anchors(c.conn, W2)))
c.outflow_pass(force=True)
check("O9 다음 패스 = 정상(W2 10 · 기초 잔고 없음)", cell(c.conn, A, W2) == 10 * E18 and anchors(c.conn, W2) == [], (cell(c.conn, A, W2), anchors(c.conn, W2)))
c.conn.close()

c = scenario_a(old_path=True)
A = aid_native(c)
check("O10 (전제) 종전 경로로 만든 오염 원장 = W2 20(기초 잔고 10 + 받은 10)", cell(c.conn, A, W2) == 20 * E18 and [a[2] for a in anchors(c.conn, W2)] == [10 * E18],
      (cell(c.conn, A, W2), anchors(c.conn, W2)))
sc = shadow(c, "o10a")
check("O10 (대조) 일반 rebuild2 는 오염 20 을 그대로 이월(재구축만으로는 못 고침)", cell(sc.conn, A, W2) == 20 * E18, cell(sc.conn, A, W2))
sc.conn.close()
n0 = c.conn.execute("SELECT COUNT(*), MAX(posting_id), total_changes() FROM postings").fetchone()[:2]
rep = c.own_overlap_repair(apply=False)
check("O10 점검 = 대상 1칸(W2 ETH · 차이 = 받은 10) · 쓰기 0", [(r["wallet"], r["action"], r["extra"]) for r in rep] == [(W2, "fix", str(10 * E18))]
      and tuple(c.conn.execute("SELECT COUNT(*), MAX(posting_id) FROM postings").fetchone()) == tuple(n0) and cell(c.conn, A, W2) == 20 * E18
      and not c.conn.in_transaction, (rep, cell(c.conn, A, W2)))
rep = c.own_overlap_repair(apply=True)
check("O10 ★복구 = W2 10 · 기초 잔고 10 → 0 · 보유 캐시 10 · 지난 곡선 표식★", [r["action"] for r in rep] == ["fix"] and cell(c.conn, A, W2) == 10 * E18
      and anchors(c.conn, W2) == [] and abs(pos(c, A, W2) - 10) < 1e-9 and min_mark(c) is not None and not c.conn.in_transaction,
      (rep, cell(c.conn, A, W2), anchors(c.conn, W2), pos(c, A, W2), histmark.hist_late_read(c.conn)))
n1 = c.conn.execute("SELECT COUNT(*), MAX(posting_id) FROM postings").fetchone()
rep2 = c.own_overlap_repair(apply=True)
check("O10 ★두 번째 = 무변(대상 칸 = 정상 'ok')★", [r["action"] for r in rep2] == ["ok"] and tuple(c.conn.execute("SELECT COUNT(*), MAX(posting_id) FROM postings").fetchone()) == tuple(n1)
      and cell(c.conn, A, W2) == 10 * E18, (rep2, cell(c.conn, A, W2)))
sc = shadow(c, "o10b")
check("O10 복구 뒤 rebuild2 = 10(이월)", cell(sc.conn, A, W2) == 10 * E18 and anchors(sc.conn, W2) == [], (cell(sc.conn, A, W2), anchors(sc.conn, W2)))
sc.conn.close()
c.conn.close()
c = scenario_a()
rep = c.own_overlap_repair(apply=True)
check("O10 깨끗한 원장(새 코드로 적용) = 'ok' 만 · 무변", [r["action"] for r in rep] == ["ok"] and cell(c.conn, aid_native(c), W2) == 10 * E18, rep)
c.conn.close()
c = scenario_a(old_path=True)
A = aid_native(c)
r9 = c.conn.execute("SELECT posting_id, qty_base FROM postings WHERE source_kind='opening' AND location=?", (f"wallet:eth:{W2}",)).fetchone()
c.conn.execute("UPDATE postings SET qty_base=? WHERE posting_id=?", (str(int(r9[1]) + 3 * E18), r9[0]))
c.conn.commit()
rep = c.own_overlap_repair(apply=True)
check("O10 설명 안 되는 차이(13 ≠ 받은 10) = 'skip' · 안 건드림", [r["action"] for r in rep] == ["skip"] and cell(c.conn, A, W2) == 23 * E18, (rep, cell(c.conn, A, W2)))
c.conn.close()
c = scenario_a(old_path=True)
c.conn.close()
spt = importlib.util.spec_from_file_location("rpo", os.path.join(T.ROOT, "tools", "repair_own_overlap.py"))
rpo = importlib.util.module_from_spec(spt)
spt.loader.exec_module(rpo)
rpo._core_running = lambda: False
buf = io.StringIO()
with redirect_stdout(buf):
    rc0 = rpo.main([])
c = new_core()
A = aid_native(c)
check("O10 도구 점검(기본) = 무변 · 대상 1칸 출력", rc0 == 0 and cell(c.conn, A, W2) == 20 * E18 and "fix" in buf.getvalue(), (rc0, buf.getvalue()[-400:]))
c.conn.close()
rpo._core_running = lambda: True
with redirect_stdout(io.StringIO()):
    rc_run = rpo.main(["--apply"])
rpo._core_running = lambda: None
with redirect_stdout(io.StringIO()):
    rc_unk = rpo.main(["--apply"])
c = new_core()
check("O10 도구 가드 = tj-core 가동 중·판정 불가면 거부(무변)", rc_run == 1 and rc_unk == 1 and cell(c.conn, A, W2) == 20 * E18, (rc_run, rc_unk))
c.conn.close()
rpo._core_running = lambda: False
buf = io.StringIO()
with redirect_stdout(buf):
    rc1 = rpo.main(["--apply"])
bk = [p9 for p9 in glob.glob(os.path.join(SD, "ledger.db.pre_ownfix_*")) if not p9.endswith(("-wal", "-shm", "-journal"))]
c = new_core()
check("O10 ★도구 --apply = 백업 뒤 복구(W2 10)★", rc1 == 0 and len(bk) == 1 and cell(c.conn, A, W2) == 10 * E18, (rc1, bk, buf.getvalue()[-400:]))
c.conn.close()
if bk:
    b9 = sqlite3.connect(bk[0])
    check("O10 백업 = 복구 전 원장(W2 20)", cell(b9, A, W2) == 20 * E18, cell(b9, A, W2))
    b9.close()
with redirect_stdout(io.StringIO()):
    rc2 = rpo.main(["--apply"])
c = new_core()
bk2 = glob.glob(os.path.join(SD, "ledger.db.pre_ownfix_*"))
check("O10 도구 두 번째 = 고칠 칸 없음 · 백업 안 만듦(백업 = 파일 하나) · 무변", rc2 == 0 and bk2 == bk and cell(c.conn, A, W2) == 10 * E18, (rc2, bk2, bk))
c.conn.close()

c = scenario_a(old_path=True)
A = aid_native(c)
LOC2 = f"wallet:eth:{W2}"
c._anchor_adjust("eth", f"rebal20260901:eth:{W2}:{A}", int(time.time()), A, LOC2, -10 * E18, "rebal")
c.conn.commit()
check("O12 (전제) 재정렬 앵커가 이미 맞춘 칸 = W2 10(실잔고)", cell(c.conn, A, W2) == 10 * E18, (cell(c.conn, A, W2), anchors(c.conn, W2)))
rep = c.own_overlap_repair(apply=True)
check("O12 ★다른 기초 잔고 행(재정렬 등)이 있는 칸 = 'skip' · W2 10 그대로(다시 빼서 0 이 되지 않음)★",
      [r["action"] for r in rep] == ["skip"] and cell(c.conn, A, W2) == 10 * E18 and abs(pos(c, A, W2) - 10) < 1e-9, (rep, cell(c.conn, A, W2)))
c.conn.close()

c = scenario_a(old_path=True)
A = aid_native(c)
feed(c, h(2), OUT_TX, wallets=(W2,))
check("O13 (전제) 재방출 뒤에도 오염 20 · 관점에 W2", cell(c.conn, A, W2) == 20 * E18
      and W2 in json.loads(c.conn.execute("SELECT wallets FROM raw_txs WHERE txhash=?", (h(2),)).fetchone()[0]), cell(c.conn, A, W2))
rep = c.own_overlap_repair(apply=True)
check("O13 ★관점·도착 시각이 바뀐 받은 레그도 차이와 정확히 같으면 복구 = W2 10★", [r["action"] for r in rep] == ["fix"] and cell(c.conn, A, W2) == 10 * E18
      and anchors(c.conn, W2) == [], (rep, cell(c.conn, A, W2), anchors(c.conn, W2)))
rep = c.own_overlap_repair(apply=True)
check("O13 두 번째 = 'ok' · 무변", [r["action"] for r in rep] == ["ok"] and cell(c.conn, A, W2) == 10 * E18, (rep, cell(c.conn, A, W2)))
c.conn.close()

W9 = "0x" + "a9" * 20
c = scenario_a(old_path=True)
c.conn.close()
write_cfg([W, W2, W9])


def w9_rows(path=None):
    c9 = sqlite3.connect(path or paths.DB_PATH)
    try:
        return c9.execute("SELECT COUNT(*) FROM wallets WHERE address=?", (W9,)).fetchone()[0]
    finally:
        c9.close()


rpo._core_running = lambda: False
for f9 in glob.glob(os.path.join(SD, "ledger.db.pre_ownfix_*")):
    os.remove(f9)
with redirect_stdout(io.StringIO()):
    rc14 = rpo.main([])
check("O14 ★도구 점검(기본) = 원장 쓰기 0(설정의 새 지갑도 등록 안 함)★", rc14 == 0 and w9_rows() == 0, (rc14, w9_rows()))
with redirect_stdout(io.StringIO()):
    rc14b = rpo.main(["--apply"])
bk14 = [p9 for p9 in glob.glob(os.path.join(SD, "ledger.db.pre_ownfix_*")) if not p9.endswith(("-wal", "-shm", "-journal"))]
check("O14 ★--apply 백업 = 실행 직전 원장(생성자 등록 전 · W2 20)★ · 적용 = 10", rc14b == 0 and len(bk14) == 1 and w9_rows(bk14[0]) == 0
      and cell(sqlite3.connect(bk14[0]), A, W2) == 20 * E18 and cell(sqlite3.connect(paths.DB_PATH), A, W2) == 10 * E18, (rc14b, bk14))
write_cfg([W, W2])

reset()
c = new_core()
feed(c, h(41), esnap(h(41), TS_IN, 1000, X, W, toks=[(X, W, 30 * E6)]))
feed(c, h(42), esnap(h(42), TS_OUT, 2000, W, USDC, toks=[(W, X, 10 * E6)]))
age_ingest(c)
recon_full(c, {"eth": {W: {("native", None): 0, ("token", USDC): 25 * E6}}})
AU = aid_usdc(c)
c.conn.execute("UPDATE tx_class SET event='BRIDGE' WHERE chain='eth' AND txhash=?", (h(42),))
c.conn.commit()
a11 = anchors(c.conn, W)
nre = c._reclass_plain_xfer_once()
check("O11 평범한 전송 재분류(공용 재기장) = 1건 · 지갑 칸 무변 → 기초 잔고 무변(5)",
      nre == 1 and anchors(c.conn, W) == a11 and cell(c.conn, AU, W) == 25 * E6
      and c.conn.execute("SELECT event FROM tx_class WHERE txhash=?", (h(42),)).fetchone()[0] != "BRIDGE", (nre, anchors(c.conn, W), a11, cell(c.conn, AU, W)))
c.conn.close()
T.finish()
