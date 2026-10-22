#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
from _ingest import check  # noqa: E402
import _nonevm as N  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

import config, paths  # noqa: E402
import core  # noqa: E402
import core_svc  # noqa: E402
import bf_engine  # noqa: E402
import chain_registry as reg  # noqa: E402
import chain_state as cs  # noqa: E402
import chain_watch as cw  # noqa: E402
import address_codec as ac  # noqa: E402
from inbox import SegmentWriter, SegmentReader  # noqa: E402
import _tronfake as F  # noqa: E402
import tron_watch as TW  # noqa: E402

A, B = N.OWN["tron"]
X = N.EXT["tron"]


def S(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as e:   # noqa: BLE001
        return f"예외:{type(e).__name__}"

SDU = os.path.join(T.TMP, "unit")
os.makedirs(SDU, exist_ok=True)
su = cs.ChainState("tron", SDU)
for o in (A, B):
    su.set_status(o, requested_from=100, available_from=100, scanned_through=200, details_complete_through=200)
su.pending_upsert([("s1", {"owner": A, "lane": "history"})])
su.mark_synced()
check("G1 상한 전 pending = 그 지갑 백필 미완 · 대사 준비 아님", not su.owner_done(A) and not su.ready({A, B}))
r1 = None
for _i in range(cs.MAX_TRIES):
    r1 = su.reschedule("s1", "영수증 지연")
su.mark_synced()
check("G1 재시도 상한 → gap(대기 0 · gap 1)", r1 == "gap" and not su.d["pending"] and len(su.d["gaps"]) == 1, (r1, su.d["pending"], su.d["gaps"]))
check("G1 test_nonevm_gap_readiness: 미해소 gap = owner_done 거짓 · ready 거짓(대기 0 이어도)", not su.owner_done(A) and not su.ready({A, B}),
      (su.owner_done(A), su.ready({A, B})))
sv = su.status_view()
check("G1 화면 complete 도 거짓(대사 준비와 같은 판정) · gaps_open 1", sv[A]["complete"] is False and sv[A].get("gaps_open") == 1, sv[A])
check("G8 다른 지갑(B)의 백필은 끝남 · 전 지갑 준비(core 체인 대사·비Sui 새 지갑 대사가 쓰는 판정)는 A 의 미해소 gap 으로 보류",
      su.owner_done(B) and not su.ready({A, B}), (su.owner_done(B), su.ready({A, B})))
check("G8 ready(지갑 일부) = 넘긴 지갑만(다른 지갑 영향은 호출부 판정 — Sui 지갑별 대사의 종전 계약 유지)", su.ready({B}) is True)
su.save()
su2 = cs.ChainState("tron", SDU)
check("G3 test_nonevm_gap_restart: 저장·재시작 뒤에도 같은 보류", not su2.owner_done(A) and not su2.ready({A, B}) and su2.owner_done(B)
      and S(lambda: len(su2.unresolved_gaps())) == 1)
su2.mark_emitted("s1", "s1", [B])
check("G2 다른 관점(B)으로만 방출 = A 관점 미해소(보류)", not su2.ready({A, B}) and S(lambda: [g[0] for g in su2.unresolved_gaps()]) == ["s1"])
su2.mark_emitted("s1", "s1", [A, B])
sv2 = su2.status_view()
check("G2 test_nonevm_gap_resolved_owner: 발견 지갑 관점으로 방출 = 해소 → 준비 · gap 이력 건수는 남음(증거 보존)",
      su2.ready({A, B}) and su2.owner_done(A) and sv2[A]["complete"] and sv2[A]["gaps"] == 1 and sv2[A].get("gaps_open") == 0, sv2[A])
su2.d["gaps"].append({"id": "s0", "ref": {"owner": A}, "why": "옛 기록", "tries": 12, "at": 1})
su2.em["uids"]["s0"] = 123456
check("G2 관점 없는 옛 방출 기록 = 해소(종전 규칙)", su2.ready({A, B}))
su2.d["gaps"].append({"id": "recv2", "ref": {"owner": B}, "why": "뿌리 못 찾음", "tries": 12, "at": 2})
check("G2 발견 sid ≠ 묶음 uid — 해결 전 = 미해소", not su2.ready({A, B}))
su2.mark_emitted("recv2", "root2", [A, B])
check("G2 발견 sid → 실제 묶음 uid 해결 관계(res) = 해소 · 방출 uid 에는 뿌리만(구성 sid 를 방출 uid 로 안 넣음 → _rebase 오인 없음)",
      su2.ready({A, B}) and su2.emitted("root2") and not su2.emitted("recv2") and (su2.em.get("res") or {}).get("recv2", {}).get("u") == "root2",
      (S(lambda: su2.unresolved_gaps()), su2.em.get("res")))
su2.d["gaps"].append({"id": "recv3", "ref": {"owner": B}, "why": "뿌리 못 찾음", "tries": 12, "at": 3})
S(su2.mark_emitted, "root3", "root3", [A, B], covered=["root3", "recv3"])
check("G2 묶음이 담은 다른 발견 sid(covered) = 해소 · 방출 uid 아님", su2.ready({A, B}) and not su2.emitted("recv3") and "root3" not in (su2.em.get("res") or {}),
      (S(lambda: su2.unresolved_gaps()), su2.em.get("res")))
su2.d["gaps"].append({"id": "recv4", "ref": {"owner": B}, "why": "x", "tries": 12, "at": 4})
S(su2.mark_emitted, "root4", "root4", [A], covered=["recv4"])
check("G2 묶음 관점에 발견 지갑(B)이 없으면 해결 관계가 있어도 미해소", not su2.ready({A, B}) and S(lambda: [g[0] for g in su2.unresolved_gaps()]) == ["recv4"])
su2.d["gaps"] = [g for g in su2.d["gaps"] if g["id"] != "recv4"]
su2.save()
su3 = cs.ChainState("tron", SDU)
raw_em = json.load(open(os.path.join(SDU, reg.spec("tron").emitted_file)))
check("G3 재시작 뒤 해결 관계 유지 · 준비 그대로", su3.ready({A, B}) and su3.em.get("res", {}).get("recv2", {}).get("u") == "root2")
check("G3 롤백 무해: 옛 코드가 읽는 방출 파일 uids 칸 = 실제 레코드 uid 만(구성 sid 없음) · 해결 관계는 따로(res — 옛 코드는 무시·보존)",
      isinstance(raw_em.get("uids"), dict) and "recv2" not in raw_em["uids"] and "recv3" not in raw_em["uids"] and isinstance(raw_em.get("res"), dict),
      sorted(raw_em))
SDO = os.path.join(T.TMP, "old")
os.makedirs(SDO, exist_ok=True)
json.dump({"v": 1, "lanes": {}, "pending": {}, "gaps": [{"id": "g1", "ref": {"owner": A}, "why": "x", "tries": 12, "at": 1}],
           "status": {A: {"details_complete_through": 5}}, "synced_at": int(time.time())}, open(os.path.join(SDO, reg.spec("tron").cursor_file), "w"))
json.dump({"v": 1, "uids": {"g1": {"t": 1, "o": [A]}}}, open(os.path.join(SDO, reg.spec("tron").emitted_file), "w"))
so = cs.ChainState("tron", SDO)
check("G3 옛 형식 방출 파일(res 없음) 읽기 — 이미 방출된 gap = 해소 · 준비", so.ready({A}) and S(lambda: so.unresolved_gaps()) == [])
SDP = os.path.join(T.TMP, "partial")
os.makedirs(SDP, exist_ok=True)
sp = cs.ChainState("tron", SDP)
sp.set_status(A, requested_from=100, available_from=150, scanned_through=300, details_complete_through=300)
sp.mark_synced()
check("G4 test_nonevm_partial_retention: 보존 범위 밖 시작일(partial)만 = 지금 잔고 대사 가능(준비) · 화면 coverage partial",
      sp.ready({A}) and sp.status_view()[A]["coverage"] == "partial")
sp.pending_upsert([("p1", {"owner": A, "lane": "history"})])
for _i in range(cs.MAX_TRIES):
    sp.reschedule("p1", "상세 지연")
check("G4 창 안 상세 누락(gap) = 보류(partial 과 섞지 않음)", not sp.ready({A}))

fake = F.FakeTron()
F.install_loop_open(bf_engine, T)
TW.TronAdapter.RATE_PAUSE = 0.05
bf_engine._POLICY_OVERRIDES["127.0.0.1"] = {"rate": 1000.0, "burst": 1000, "conc": 8}
NOW = int(time.time() * 1000)
DAY = 86400_000
fake.head = [NOW // 3000 + 5, NOW - 60_000, "ab" * 32]
fake.accounts[A] = {"address": A, "balance": 12_000_000}
fake.v1[A] = {"address": A, "trc20": []}
T1 = "%064x" % 0x71
fake.transfer(T1, NOW - 10 * DAY, X, A, 5_000_000)
fake.noinfo.add(T1)
CFG_PATH = os.path.join(T.TMP, "config.json")


def set_wallets(*keys):
    cfg = json.load(open(CFG_PATH))
    cfg["chain_wallets"] = [{"chain": "tron", "address": ac.tron_display(k)} for k in keys]
    cfg["nonevm"] = {"tron": {"api": fake.base, "rps": 1000, "retries": 1}}
    json.dump(cfg, open(CFG_PATH, "w"))
    return config.load_config()


set_wallets(A)
INB = os.path.join(paths.INBOX_DIR, "tron")
W = SegmentWriter(INB)
st = cs.ChainState("tron")
ad = TW.make_adapter(config.load_config())
ad.state = st
col = cw.Collector(ad, W, st, {A})


def run_until_gap(col, st, sid, n=cs.MAX_TRIES + 3):
    for _i in range(n):
        col.cycle()
        if sid not in st.d["pending"]:
            break
        st.d["pending"][sid]["next"] = 0
    col.cycle()


def requeue(st, sid):
    g = [x for x in st.d["gaps"] if x.get("id") == sid][-1]
    st.pending_upsert([(sid, g["ref"])])
    st.d["pending"][sid]["next"] = 0
    st.save()


col.cycle()
check("G5 첫 주기: 창 안 입금 = 대기(방출 안 됨)", T1 in st.d["pending"] and not st.emitted(T1), list(st.d["pending"]))
run_until_gap(col, st, T1)
check("G5 실제 MAX_TRIES 뒤 gap 1 · 대기 0 · 동기화 도장", len(st.d["gaps"]) == 1 and not st.d["pending"] and st.d.get("synced_at"),
      (st.d["gaps"], st.d["pending"]))
reg.FORCE_AVAILABLE.add("tron")
c = core.Core(config.load_config())
c.conn.commit()


def drain(c, chain="tron"):
    rd = SegmentReader(os.path.join(paths.INBOX_DIR, chain))
    for _i in range(50):
        row = c.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream=?", (chain,)).fetchone()
        seg, off = (row["seg"], row["off"]) if row else (1, 0)
        c._drain_stream(chain, rd, seg, off)
        row2 = c.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream=?", (chain,)).fetchone()
        if row2 and row and (row2["seg"], row2["off"]) == (seg, off):
            break
    c.conn.commit()


def openings(c, w=None):
    q = ("SELECT a.address, a.kind, p.location, p.qty_base AS q FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
         " WHERE p.source_kind='opening' AND a.chain='tron'")
    return {(r["address"] or r["kind"], r["location"], int(r["q"])) for r in c.conn.execute(q)
            if w is None or r["location"] == reg.make_location("tron", w)}


drain(c)
c.svc_recon._last_recon = 0
c.svc_recon.recon_pass({"tron"})
st = cs.ChainState("tron")
check("G5 test_tron_gap_recon_hold: 상세 복구 전 = opening 없음(12 TRX 전량 흡수 안 함)", not openings(c), openings(c))
check("G5 상세 복구 전 = recon_done_tron 없음 · ready 거짓 · owner_done 거짓 · 화면 complete 거짓",
      not c._meta_get("recon_done_tron") and not st.ready({A}) and not st.owner_done(A) and st.status_view()[A]["complete"] is False,
      (c._meta_get("recon_done_tron"), st.ready({A}), st.owner_done(A)))
c.conn.close()
c = core.Core(config.load_config())
c.svc_recon._last_recon = 0
c.svc_recon.recon_pass({"tron"})
check("G3 core 재시작 뒤에도 같은 보류(opening·도장 없음)", not openings(c) and not c._meta_get("recon_done_tron"), openings(c))

fake.noinfo.discard(T1)
st = cs.ChainState("tron")
ad.state = st
col = cw.Collector(ad, W, st, {A})
requeue(st, T1)
col.cycle()
drain(c)
st = cs.ChainState("tron")
check("G5 회복 뒤 기장 · gap 해소(이력 1건은 남음) · 준비", st.emitted(T1) and st.ready({A}) and len(st.d["gaps"]) == 1, (st.d["gaps"], st.d["pending"]))

gate = threading.Event()
real_ad = c.svc_recon._nonevm_adapter("tron")


class SlowAd:
    def fetch_balances(self, owners, boundary, tokens=None):
        gate.wait(10)
        return real_ad.fetch_balances(owners, boundary, tokens=tokens)


c.svc_recon._nonevm_adapters = {"tron": SlowAd()}
c.svc_recon.RECON_WAIT_SEC = 0.05
c.svc_recon._last_recon = 0
c.svc_recon.recon_pass({"tron"})
started = ("tron", "chain") in c.svc_recon.__dict__.get("_recon_jobs", {})
GX = "%064x" % 0x7f
st = cs.ChainState("tron")
st.d["gaps"].append({"id": GX, "ref": {"owner": A, "lane": "latest"}, "why": "조회 중 새 gap(합성)", "tries": cs.MAX_TRIES, "at": int(time.time())})
st.save()
gate.set()
time.sleep(0.5)
c.svc_recon._last_recon = time.time()
c.svc_recon.recon_pass({"tron"})
check("G7 test_nonevm_gap_change_during_recon: 조회 시작됨 → 조회 중 gap 생김 → 수확 폐기(opening·도장 없음)",
      started and not openings(c) and not c._meta_get("recon_done_tron") and ("tron", "chain") not in c.svc_recon.__dict__.get("_recon_jobs", {}),
      (started, openings(c), c._meta_get("recon_done_tron")))
st = cs.ChainState("tron")
st.d["gaps"] = [g for g in st.d["gaps"] if g["id"] != GX]
st.save()
c.svc_recon._nonevm_adapters = {"tron": real_ad}
c.svc_recon.RECON_WAIT_SEC = core_svc.ReconService.RECON_WAIT_SEC
c.svc_recon._last_recon = 0
c.svc_recon.recon_pass({"tron"})
check("G5 해소 뒤 대사 = opening 7 TRX(창 이전 실제 보유) · 완료 도장", openings(c) == {("native", reg.make_location("tron", A), 7_000_000)}
      and bool(c._meta_get("recon_done_tron")), openings(c))

fake.accounts[B] = {"address": B, "balance": 4_000_000}
fake.v1[B] = {"address": B, "trc20": []}
T3 = "%064x" % 0x73
fake.transfer(T3, NOW - 120_000, X, A, 1_000_000)
fake.accounts[A]["balance"] += 1_000_000
fake.noinfo.add(T3)
set_wallets(A, B)
c.chain_owners["tron"] = {A, B}
st = cs.ChainState("tron")
ad.state = st
col = cw.Collector(ad, W, st, {A, B})
col.cycle()
fake.txs = [t for t in fake.txs if t["txid"] != T3]
run_until_gap(col, st, T3)
for _i in range(3):
    col.cycle()
drain(c)
st = cs.ChainState("tron")
check("G8 준비 상태: B 백필 끝 · 대기 0 · A 의 새 gap(T3) 미해소", st.owner_done(B) and not st.d["pending"]
      and S(lambda: [g[0] for g in st.unresolved_gaps()]) == [T3] and [g["id"] for g in st.d["gaps"]].count(T3) == 1,
      (st.status_view(), S(lambda: st.unresolved_gaps()), list(st.d["pending"])))
c.svc_recon._last_recon = 0
c.svc_recon.recon_pass({"tron"})
check("G8 test_nonevm_gap_other_wallet: 다른 지갑(A) 미해소 gap = 영향 불명 → 새 지갑 B 기초 잔고 보류", not openings(c, B)
      and not c._meta_get(f"wrecon_done:tron:{B}"), openings(c, B))
fake.noinfo.discard(T3)
requeue(st, T3)
col = cw.Collector(ad, W, st, {A, B})
ad.state = st
col.cycle()
drain(c)
c.svc_recon._last_recon = 0
c.svc_recon.recon_pass({"tron"})
check("G8 A 의 gap 해소 뒤 B 기초 잔고 4 TRX 진행", openings(c, B) == {("native", reg.make_location("tron", B), 4_000_000)}
      and bool(c._meta_get(f"wrecon_done:tron:{B}")), openings(c, B))
reg.FORCE_AVAILABLE.clear()
fake.close()
T.finish()
