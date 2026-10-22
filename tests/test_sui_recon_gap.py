#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
from _ingest import check  # noqa: E402
import _nonevm as N  # noqa: E402
import _suifake as F  # noqa: E402

import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402

import config, paths  # noqa: E402
import core  # noqa: E402
import chain_registry as reg  # noqa: E402
import chain_state as cs  # noqa: E402
from inbox import SegmentWriter  # noqa: E402
try:
    import sui_watch as SW  # noqa: E402
except ImportError:
    import _wip_sui_watch as SW  # noqa: E402

DAY = 86400
A, B = N.OWN["sui"]
X = N.EXT["sui"]
SUI = F.SUI_T
NM = "0x" + "f7" * 32 + "::nm::NM"
E9 = 10 ** 9
FEE = 2500

ch = F.Chain()
ch.meta = {NM: None}
srv, URL = F.start(ch)
TIP = ch.tip
ch.bal_min_ck = TIP - 3600
D_A2 = ch.add(TIP - 3 * DAY, [(X, SUI, -3 * E9 - FEE), (A, SUI, 3 * E9)], sender=X)
D_A = ch.add(TIP - 2 * DAY, [(X, SUI, -FEE), (X, NM, -1000), (A, NM, 1000)], sender=X)
D_B = ch.add(TIP - 5 * DAY, [(X, SUI, -2 * E9 - FEE), (B, SUI, 2 * E9)], sender=X)
ch.bal[A] = [(SUI, 3 * E9, 3 * E9, 0), (NM, 1000, 1000, None)]
ch.bal[B] = [(SUI, 7 * E9, 7 * E9, 0)]

CFG_PATH = os.path.join(T.TMP, "config.json")
cfg = json.load(open(CFG_PATH))
cfg["chain_wallets"] = [{"chain": "sui", "address": A}, {"chain": "sui", "address": B}]
cfg["nonevm"] = {"sui": {"graphql_url": URL, "retries": 1}}
json.dump(cfg, open(CFG_PATH, "w"))
cfg = config.load_config()
w = SegmentWriter(os.path.join(paths.INBOX_DIR, "sui"))


def col_for():
    return SW.SuiCollector(SW.make_adapter(cfg), w, cs.ChainState("sui"), {A, B},
                           page_budget={"latest": 5, "history": 20}, detail_budget={"latest": 100, "history": 500})


col_for().cycle()
for _i in range(cs.MAX_TRIES + 1):
    st = cs.ChainState("sui")
    if D_A not in st.d["pending"]:
        break
    st.d["pending"][D_A]["next"] = 0
    st.save()
    c9 = col_for()
    c9.details("history")
    c9.details("latest")
col_for().cycle()
st = cs.ChainState("sui")
check("G0 A = gap(메타 없음) · 상세 완료 경계 없음 · 준비 아님", any(g["id"] == D_A for g in st.d["gaps"]) and not st.ready({A}),
      (st.d["gaps"][-1:], st.d["status"].get(A)))
check("G0 B = 준비 · 체인 전체(A·B)는 준비 아님", st.ready({B}) and not st.ready({A, B}), st.d["status"].get(B))

reg.FORCE_AVAILABLE.add("sui")
c = core.Core(config.load_config())
c.conn.commit()
c.svc_recon._nonevm_adapters = {"sui": SW.make_adapter(cfg)}
rd = dict(c.chain_readers)["sui"]
c._drain_stream("sui", rd, 0, 0)
c.conn.commit()
LA, LB = reg.make_location("sui", A), reg.make_location("sui", B)


def recon():
    ch.tip += 20
    c.svc_recon._last_recon = 0
    c.svc_recon.recon_pass({"sui"})


def sum_at(loc, kind=None):
    q = ("SELECT SUM(CAST(p.qty_base AS INTEGER)) FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
         " WHERE p.location=? AND a.chain='sui' AND a.kind='native'" + (" AND p.source_kind='opening'" if kind == "opening" else ""))
    return int(c.conn.execute(q, (loc,)).fetchone()[0] or 0)


def b_done():
    return bool(c._meta_get(f"wrecon_done:sui:{B}")) or sum_at(LB, "opening") != 0


def edit_state(fn):
    s9 = cs.ChainState("sui")
    fn(s9)
    s9.save()


check("G0 원장: A SUI 3 · B SUI 2(창 안)", sum_at(LA) == 3 * E9 and sum_at(LB) == 2 * E9, (sum_at(LA), sum_at(LB)))

D_S = ch.add(TIP - DAY, [(X, SUI, -E9 - FEE), (B, SUI, E9), (X, NM, -5), (A, NM, 5)], sender=X)
GS = {"id": D_S, "ref": {"stable_id": D_S, "owner": A, "lane": "history"}, "why": "일시 실패: 메타 없음", "tries": cs.MAX_TRIES, "at": TIP}
edit_state(lambda s: s.d["gaps"].append(dict(GS)))
recon()
r1 = SW.make_adapter(cfg).fetch_and_normalize({"stable_id": D_S, "owner": B, "lane": "history"}, {B})
check("H1 전제: 공유 거래의 B 관점 = SUI +1(영향 있음 — 상세 실패가 아니라 순변화로 보류)",
      [(d["owner"], d["delta_base"]) for d in (r1 or {}).get("deltas", [])] == [(B, str(E9))], r1 and r1.get("deltas"))
check("H1 다른 지갑 gap 거래가 B 에 순변화 = B 대사 보류(흡수 안 함)", not b_done() and not c._meta_get("recon_done_sui"), sum_at(LB, "opening"))
edit_state(lambda s: s.d.__setitem__("gaps", [g for g in s.d["gaps"] if g["id"] != D_S]))

D_U = F.digest(9999)
edit_state(lambda s: s.d["gaps"].append(dict(GS, id=D_U, ref={"stable_id": D_U, "owner": A, "lane": "history"})))
recon()
check("H2 gap 거래 상세를 못 읽음(영향 모름) = B 대사 보류", not b_done(), sum_at(LB, "opening"))
edit_state(lambda s: s.d.__setitem__("gaps", [g for g in s.d["gaps"] if g["id"] != D_U]))

edit_state(lambda s: s.pending_upsert([(D_S, {"stable_id": D_S, "owner": A, "lane": "history"})]))
recon()
check("H3 다른 지갑 상세 대기 남음 = B 대사 보류", not b_done(), sum_at(LB, "opening"))
edit_state(lambda s: s.d["pending"].pop(D_S, None))

ad4 = c.svc_recon._nonevm_adapters["sui"]
orig_fb = ad4.fetch_balances


def fb_mutating(*a, **k):
    edit_state(lambda s: s.d["gaps"].append(dict(GS, id=F.digest(9998), ref={"stable_id": F.digest(9998), "owner": A, "lane": "history"})))
    return orig_fb(*a, **k)


ad4.fetch_balances = fb_mutating
recon()
ad4.fetch_balances = orig_fb
check("H4 조회 중 gap 상태가 바뀜 = 수확 버림(대사 안 함)", not b_done(), sum_at(LB, "opening"))
edit_state(lambda s: s.d.__setitem__("gaps", [g for g in s.d["gaps"] if g["id"] != F.digest(9998)]))
col_for().cycle()

recon()
check("G1 B 기초 잔고 = 7 − 2 = 5 SUI · B 합 = 7(경계 잔고)", sum_at(LB, "opening") == 5 * E9 and sum_at(LB) == 7 * E9,
      (sum_at(LB, "opening"), sum_at(LB)))
check("G1 B 지갑별 대사 도장 · 관측 recon:sui:B", bool(c._meta_get(f"wrecon_done:sui:{B}"))
      and c.conn.execute("SELECT 1 FROM raw_observations WHERE obs_id=?", (f"recon:sui:{B}",)).fetchone() is not None)
check("G1 A = 대사 없음(기초 잔고 0행 · 도장 없음) · 체인 대사 도장 없음", sum_at(LA, "opening") == 0
      and not c._meta_get(f"wrecon_done:sui:{A}") and not c._meta_get("recon_done_sui"))
recon()
check("G1 다시 돌려도 B 기초 잔고 그대로(멱등)", sum_at(LB, "opening") == 5 * E9 and sum_at(LB) == 7 * E9, sum_at(LB))

ch.meta[NM] = ("NM", 0)
edit_state(lambda s: s.pending_upsert([(D_A, {"stable_id": D_A, "owner": A, "lane": "latest"})]))
col_for().cycle()
st = cs.ChainState("sui")
check("G2 A gap 풀림 · 체인 전체 준비", st.ready({A, B}), st.d["status"].get(A))
c._drain_stream("sui", rd, *[(r["seg"], r["off"]) for r in c.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream='sui'")][0])
c.conn.commit()
recon()
check("G2 체인 대사 도장", bool(c._meta_get("recon_done_sui")))
check("G2 A SUI 합 = 3 · B SUI 합 = 7(이중 계상 없음)", sum_at(LA) == 3 * E9 and sum_at(LB) == 7 * E9, (sum_at(LA), sum_at(LB)))

spec9 = importlib.util.spec_from_file_location("rb2", os.path.join(T.ROOT, "tools", "rebuild2.py"))
rb2 = importlib.util.module_from_spec(spec9)
spec9.loader.exec_module(rb2)


def b_anchors(conn):
    return sorted((str(r[0]), int(r[1])) for r in conn.execute(
        "SELECT p.source_id, p.qty_base FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
        " WHERE p.source_kind='opening' AND p.location=? AND a.kind='native'", (LB,)))


def lsum(conn, loc):
    return sum(int(r[0]) for r in conn.execute("SELECT p.qty_base FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                                               " WHERE p.location=? AND a.chain='sui' AND a.kind='native'", (loc,)))


def copy_core(tag):
    c.conn.commit()
    bp, sp = os.path.join(T.TMP, f"gr_base_{tag}.db"), os.path.join(T.TMP, f"gr_shadow_{tag}.db")
    for p9 in (bp, sp):
        if os.path.exists(p9):
            os.remove(p9)
        d9 = sqlite3.connect(p9)
        c.conn.backup(d9)
        d9.close()
    old9 = paths.DB_PATH
    paths.DB_PATH = sp
    try:
        sc = core.Core(config.load_config())
    finally:
        paths.DB_PATH = old9
    sc.svc_recon._nonevm_adapters = {"sui": SW.make_adapter(cfg)}
    return bp, sc


def replay(sc):
    for t9 in rb2.DERIVED_TABLES:
        sc.conn.execute(f"DELETE FROM {t9}")
    sc.conn.commit()
    for r in sc.conn.execute("SELECT chain, txhash, snapshot FROM raw_txs ORDER BY ingested_at, chain, txhash").fetchall():
        sc.conn.execute("BEGIN")
        sc.apply(r["chain"], r["txhash"], "", json.loads(r["snapshot"]))
        sc.conn.commit()


ba0 = b_anchors(c.conn)
check("GR 전제: B 칸 앵커 = 지갑별 대사 5(recon:sui:B) 하나 — 체인 대사 차이 0 이라 recon:sui 레그 없음 · 체인 대사 관측 payload 에 B 있음",
      ba0 == [(f"recon:sui:{B}", 5 * E9)] and B in json.loads(c.conn.execute(
          "SELECT payload FROM raw_observations WHERE obs_id='recon:sui'").fetchone()[0]), ba0)
bp, sc = copy_core("rb2")
anc = [tuple(r) for r in sqlite3.connect(bp).execute(rb2.ANCHOR_SQL).fetchall()]
replay(sc)
obs = {r[0]: r[1] for r in sc.conn.execute("SELECT obs_id, observed_at FROM raw_observations")}
meta = {r[0]: int(float(r[1])) for r in sc.conn.execute("SELECT k, v FROM meta WHERE k LIKE 'recon_done_%'")}
rb2.recompute_anchors(bp, sc.conn, sc, anc, obs, meta)
sc.conn.commit()
check("GR rebuild2 = B 합 7 · 앵커 그대로(5 하나) · A 합 3", lsum(sc.conn, LB) == 7 * E9 and b_anchors(sc.conn) == ba0 and lsum(sc.conn, LA) == 3 * E9,
      (lsum(sc.conn, LB), b_anchors(sc.conn), lsum(sc.conn, LA)))
sc.conn.close()
bp, sc = copy_core("rb2b")
c2 = sqlite3.connect(bp)
aid9 = c2.execute("SELECT asset_id FROM assets WHERE chain='sui' AND kind='native'").fetchone()[0]
t9 = int(float(c2.execute("SELECT v FROM meta WHERE k='recon_done_sui'").fetchone()[0]))
c2.execute("UPDATE postings SET qty_base=? WHERE source_kind='opening' AND source_id=? AND location=?", (str(4 * E9), f"recon:sui:{B}", LB))
c2.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw,"
           " leg_kind, event, classifier_ver) VALUES ('opening','sui','recon:sui',99,?,?,?,?,NULL,NULL,'opening','OPENING',?)",
           (t9, aid9, LB, str(E9), core.CLASSIFIER_VER))
c2.commit()
check("GR (합성) 앵커 둘 = 4(recon:sui:B) + 1(recon:sui) · 합 7", lsum(c2, LB) == 7 * E9, lsum(c2, LB))
c2.close()
anc = [tuple(r) for r in sqlite3.connect(bp).execute(rb2.ANCHOR_SQL).fetchall()]
replay(sc)
rb2.recompute_anchors(bp, sc.conn, sc, anc, obs, meta)
sc.conn.commit()
check("GR rebuild2(앵커 둘) = B 합 7(이중 계상 없음 · 두 앵커 그대로 이월)", lsum(sc.conn, LB) == 7 * E9
      and b_anchors(sc.conn) == sorted([(f"recon:sui:{B}", 4 * E9), ("recon:sui", E9)]), (lsum(sc.conn, LB), b_anchors(sc.conn)))
sc.conn.close()
bp, sc = copy_core("rb1")
replay(sc)
sc.conn.execute("DELETE FROM meta WHERE k LIKE 'recon_done_%'")
sc.conn.commit()
check("GR rebuild 재생 직후 = B 합 2(앵커 없음)", lsum(sc.conn, LB) == 2 * E9, lsum(sc.conn, LB))
ch.tip += 20
sc.svc_recon._last_recon = 0
sc.svc_recon.recon_pass({"sui"})
check("GR rebuild 뒤 다시 대사 = B 합 7 · A 합 3(이중 계상 없음)", lsum(sc.conn, LB) == 7 * E9 and lsum(sc.conn, LA) == 3 * E9,
      (lsum(sc.conn, LB), lsum(sc.conn, LA), b_anchors(sc.conn)))
sc.conn.close()
bp, sc = copy_core("rs")
pos0 = {tuple(r) for r in c.conn.execute("SELECT * FROM positions")}
ch.tip += 20
sc.svc_recon._last_recon = 0
sc.svc_recon.recon_pass({"sui"})
check("GR 재시작 뒤 대사 주기 = B 합 7 · 앵커 무변 · 보유(positions) 그대로", lsum(sc.conn, LB) == 7 * E9 and b_anchors(sc.conn) == ba0
      and {tuple(r) for r in sc.conn.execute("SELECT * FROM positions")} == pos0, (lsum(sc.conn, LB), b_anchors(sc.conn)))
sc.conn.close()

reg.FORCE_AVAILABLE.clear()
srv.shutdown()
T.finish()
