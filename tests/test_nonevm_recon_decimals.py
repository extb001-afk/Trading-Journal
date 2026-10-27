#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
from _ingest import check  # noqa: E402
import _nonevm as N  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
from decimal import Decimal  # noqa: E402

import config, paths, statefile  # noqa: E402
import core  # noqa: E402
import bf_engine  # noqa: E402
import chain_event as ce  # noqa: E402
import chain_registry as reg  # noqa: E402
import chain_state as cs  # noqa: E402
import chain_watch as cw  # noqa: E402
import address_codec as ac  # noqa: E402
from inbox import SegmentWriter  # noqa: E402
import _tronfake as F  # noqa: E402
import tron_watch as TW  # noqa: E402

fake = F.FakeTron()
F.install_loop_open(bf_engine, T)
TW.TronAdapter.RATE_PAUSE = 0.05
bf_engine._POLICY_OVERRIDES["127.0.0.1"] = {"rate": 1000.0, "burst": 1000, "conc": 8}
A = N.OWN["tron"][0]
SU = N.OWN["sui"][0]
TO = N.OWN["ton"][0]
SIX = "41" + "5e" * 20
NOW = int(time.time() * 1000)
fake.head = [NOW // 3000 + 5, NOW - 60_000, "ab" * 32]
fake.accounts[A] = {"address": A, "balance": 10_000_000}
fake.v1[A] = {"address": A, "trc20": [{F.T(SIX): "1000000"}]}
fake.tokbal[(SIX, A)] = 1_000_000
fake.tokmeta[SIX] = ("SIX", None)
CFG_PATH = os.path.join(T.TMP, "config.json")
cfg = json.load(open(CFG_PATH))
cfg["chain_wallets"] = [{"chain": "tron", "address": ac.tron_display(A)}, {"chain": "sui", "address": SU},
                        {"chain": "ton", "address": ac.ton_friendly(TO)}]
cfg["nonevm"] = {"tron": {"api": fake.base, "rps": 1000, "retries": 1}}
json.dump(cfg, open(CFG_PATH, "w"))
reg.FORCE_AVAILABLE.update({"tron", "sui", "ton"})
DRAINED = {"tron", "sui", "ton"}

ad = TW.make_adapter(config.load_config())
bal = ad.fetch_balances({A}, None, tokens={A: []})
v = ce.validate_balances(bal, "tron", {A})
check("D1 어댑터: 자릿수 모르는 새 토큰 = usable 에서 뺌(0 도 아님) · _unobserved", ("token", SIX) not in (v["usable"].get(A) or {})
      and SIX in (bal["_unobserved"].get(A) or []), (bal["per_wallet"], bal["_unobserved"], bal["_meta"]))
check("D1 어댑터: 대사 보류(_complete 아님 — 완료 도장으로 영구 누락되지 않게 다음 주기 다시)", bal["_complete"] is False and not v["ok"], (bal.get("_why"), v["why"]))

st = cs.ChainState("tron")
ad.state = st
col = cw.Collector(ad, SegmentWriter(os.path.join(paths.INBOX_DIR, "tron")), st, {A})
col.cycle()
check("D1 수집기 준비(창 안 거래 없음)", st.ready({A}), st.status_view())
c = core.Core(config.load_config())
c.conn.commit()
T.patch_moved("dm", lambda *a, **k: None)
c.svc_recon._nonevm_adapters = {"tron": TW.make_adapter(config.load_config()), "sui": None, "ton": None}


def asset(chain, addr):
    r = c.conn.execute("SELECT asset_id, decimals FROM assets WHERE chain=? AND kind='token' AND lower(address)=lower(?)", (chain, addr)).fetchone()
    return (r["asset_id"], r["decimals"]) if r else None


def opening(chain, addr):
    return [int(r["q"]) for r in c.conn.execute(
        "SELECT p.qty_base AS q FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE a.chain=? AND lower(a.address)=lower(?) AND p.source_kind='opening'",
        (chain, addr))]


def pos(chain, addr, w):
    a9 = asset(chain, addr)
    if not a9:
        return None
    r = c.conn.execute("SELECT qty_norm FROM positions WHERE group_id=? AND location=?", (c._group_of(a9[0]), reg.make_location(chain, w))).fetchone()
    return Decimal(r["qty_norm"]) if r else None


def run(chain):
    c.svc_recon._last_recon = 0
    c.svc_recon.recon_pass(DRAINED)
    return bool(c._meta_get(f"recon_done_{chain}"))


done = run("tron")
check("D1 test_tron_new_balance_unknown_decimals: 자산(NULL 자릿수)·opening·position 0 · 완료 도장 없음",
      asset("tron", SIX) is None and not opening("tron", SIX) and pos("tron", SIX, A) is None and not done,
      (asset("tron", SIX), opening("tron", SIX), pos("tron", SIX, A), done))

fake.tokmeta[SIX] = ("SIX", 6)
TW.META_NEG_SEC = 0
done = run("tron")
check("D2 test_tron_metadata_retry_recovers: 자릿수 6 확인 → 자산 6 · opening 1,000,000 한 번 · qty_norm 1 · 완료 도장",
      asset("tron", SIX) and asset("tron", SIX)[1] == 6 and opening("tron", SIX) == [1_000_000] and pos("tron", SIX, A) == Decimal(1) and done,
      (asset("tron", SIX), opening("tron", SIX), pos("tron", SIX, A), done))
run("tron")
check("D2 다시 돌려도 중복 없음", opening("tron", SIX) == [1_000_000] and pos("tron", SIX, A) == Decimal(1), (opening("tron", SIX), pos("tron", SIX, A)))


class Stub:
    def __init__(self, chain, owner):
        self.chain, self.owner = chain, owner
        self.rows, self.meta = {("native", None): 0}, {}

    def fetch_balances(self, owners, boundary, tokens=None):
        kind = {"sui": "checkpoint", "ton": "account_lt"}.get(self.chain, "height")
        return {"per_wallet": {self.owner: dict(self.rows)}, "_meta": dict(self.meta), "_complete": True, "_unobserved": {},
                "_boundary": {"kind": kind, "value": "100", "hash": None}, "_source": "stub", "_ownership_version": "t"}


def ready_state(chain, owner):
    s9 = cs.ChainState(chain)
    s9.set_status(owner, requested_from=1, available_from=1, scanned_through=2, details_complete_through=2)
    s9.mark_synced()


ready_state("sui", SU)
ready_state("ton", TO)
KS = "0x" + "b7" * 32 + "::newc::NEWC"
stub_sui = Stub("sui", SU)
stub_sui.rows[("token", KS)] = 1_000_000
stub_sui.meta[KS] = ("NEWC", None)
c.svc_recon._nonevm_adapters = {"tron": None, "sui": stub_sui, "ton": None}
done = run("sui")
check("D3 test_nonevm_opening_metadata_guard: 어댑터가 자릿수 None 을 usable 로 넘겨도 core 가 쓰기 전 차단(자산·opening·도장 0)",
      asset("sui", KS) is None and not opening("sui", KS) and not done, (asset("sui", KS), opening("sui", KS), done))
KT = "0:" + "b8" * 32
stub_ton = Stub("ton", TO)
c.svc_recon._nonevm_adapters = {"tron": None, "sui": None, "ton": stub_ton}
for bad in (True, -1, 78, "6"):
    stub_ton.rows = {("native", None): 0, ("token", KT): 3_000_000}
    stub_ton.meta = {KT: ("BAD", bad)}
    done = run("ton")
    check(f"D3 잘못된 형식 자릿수 {bad!r} = 계약 검사에서 배제(보류 · 자산·opening·도장 0)", asset("ton", KT) is None and not opening("ton", KT) and not done,
          (asset("ton", KT), opening("ton", KT), done))
    vb = ce.validate_balances(stub_ton.fetch_balances({TO}, None), "ton", {TO})
    check(f"D3 공통 계약 validate_balances 도 자릿수 {bad!r} 거부", not vb["ok"], vb["why"])

K6 = "0:" + "b6" * 32
a6 = c.asset_id("token", "ton", K6, symbol="KS6", decimals=6)
c.conn.commit()
stub_ton.rows = {("native", None): 0, ("token", K6): 2_000_000}
stub_ton.meta = {K6: ("KS6", None)}
done = run("ton")
check("D4 test_nonevm_known_metadata_missing_hint: 원장 6자리 + 힌트 None = 진행 · 자릿수 6 유지 · qty_norm 2(18 아님)",
      done and asset("ton", K6)[1] == 6 and opening("ton", K6) == [2_000_000] and pos("ton", K6, TO) == Decimal(2),
      (done, asset("ton", K6), opening("ton", K6), pos("ton", K6, TO)))

K0 = "0x" + "b0" * 32 + "::zero::ZERO"
stub_sui.rows = {("native", None): 0, ("token", K0): 7}
stub_sui.meta = {K0: ("ZERO", 0)}
c.svc_recon._nonevm_adapters = {"tron": None, "sui": stub_sui, "ton": None}
done = run("sui")
check("D5 test_nonevm_zero_decimals_opening: 0자리 = 0 저장 · opening 7 · qty_norm 7", done and asset("sui", K0) and asset("sui", K0)[1] == 0
      and opening("sui", K0) == [7] and pos("sui", K0, SU) == Decimal(7), (done, asset("sui", K0), opening("sui", K0), pos("sui", K0, SU)))

c.conn.execute("DELETE FROM meta WHERE k='recon_done_tron'")
LEG = "41" + "6e" * 20
CF = "41" + "6f" * 20
loc = reg.make_location("tron", A)
al = c.asset_id("token", "tron", LEG, symbol="LEG", decimals=None)
c.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw,"
               " leg_kind, event, classifier_ver) VALUES ('opening', 'tron', 'legacy:test', 0, ?, ?, ?, '1000000', NULL, NULL, 'opening', 'OPENING', 1)",
               (int(time.time()) - 86400, al, loc))
c._bump_position(al, 1_000_000, loc)
acf = c.asset_id("token", "tron", CF, symbol="CF", decimals=6)
c.conn.commit()
nat = sum(int(r["q"]) for r in c.conn.execute("SELECT p.qty_base q FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE a.chain='tron' AND a.kind='native'"))
stub_tr = Stub("tron", A)
stub_tr.rows = {("native", None): nat, ("token", SIX): 1_000_000, ("token", LEG): 1_000_000}
stub_tr.meta = {LEG: ("LEG", None)}
c.svc_recon._nonevm_adapters = {"tron": stub_tr, "sui": None, "ton": None}
n_post = c.conn.execute("SELECT COUNT(*) FROM postings").fetchone()[0]
done = run("tron")
check("D6 이미 기장된 NULL 자산 + 힌트 None = 차단(새 posting·도장 0 · 18 로 확정 안 함)",
      not done and c.conn.execute("SELECT COUNT(*) FROM postings").fetchone()[0] == n_post, done)
stub_tr.rows[("token", CF)] = 0
stub_tr.meta = {LEG: ("LEG", 6), CF: ("CF", 8)}
done = run("tron")
iss = statefile.read_json(os.path.join(paths.STATE_DIR, "asset_decimals_issues.json"), {}) or {}
pq6 = c.conn.execute("SELECT p.qty_norm FROM positions p JOIN assets a ON a.group_id=p.group_id WHERE a.chain='tron' AND a.address=? AND p.location=?",
                     (LEG, loc)).fetchone()
check("D6 test_nonevm_decimals_conflict_rebuild: 힌트 6 = 바로 채움 + 재정규화(세션31 #1 · 재구축 표식 없음 · base 수량 보존) · 대사 진행",
      done and asset("tron", LEG)[1] == 6 and c._meta_get("ext_prewindow:decimals_fix") is None and opening("tron", LEG) == [1_000_000]
      and pq6 is not None and float(pq6[0]) == 1.0,
      (done, asset("tron", LEG), c._meta_get("ext_prewindow:decimals_fix"), opening("tron", LEG), pq6 and pq6[0]))
check("D6 저장 6 과 다른 관측 8 = 덮지 않음(충돌 기록)", asset("tron", CF)[1] == 6 and "conflict" in json.dumps(iss, ensure_ascii=False),
      (asset("tron", CF), str(iss)[:300]))
n2 = c.conn.execute("SELECT COUNT(*) FROM postings").fetchone()[0]
c.conn.execute("DELETE FROM meta WHERE k='recon_done_tron'")
run("tron")
check("D6 다시 대사해도 멱등(새 posting 없음 · 자릿수 그대로)", c.conn.execute("SELECT COUNT(*) FROM postings").fetchone()[0] == n2
      and asset("tron", LEG)[1] == 6 and asset("tron", CF)[1] == 6)
reg.FORCE_AVAILABLE.clear()
fake.close()
T.finish()
