#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
from _ingest import check, Reader  # noqa: E402
import _nonevm as N  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

import config  # noqa: E402
import core  # noqa: E402
import chain_registry as reg  # noqa: E402
import chain_state as cs  # noqa: E402
import address_codec as ac  # noqa: E402

NOW = int(time.time())
DAY = 86400
A = N.OWN["tron"][0]
TKA = ("token", N.TOK["tron"], "TKA", 6)
TKB = ("token", "41" + "b2" * 20, "TKB", 6)
CFG_PATH = os.path.join(T.TMP, "config.json")
cfg = json.load(open(CFG_PATH))
cfg["chain_wallets"] = [{"chain": "tron", "address": ac.tron_display(A)}]
json.dump(cfg, open(CFG_PATH, "w"))
reg.FORCE_AVAILABLE.add("tron")
c = core.Core(config.load_config())
c.conn.commit()
c.svc_recon._nonevm_adapters = {"tron": None}
LA = reg.make_location("tron", A)


def feed(rec):
    c._drain_stream("tron", Reader([json.loads(json.dumps(rec))]), 0, 0)


def scopes():
    jobs = {}
    sc = []
    c.svc_recon._recon_bal = lambda chain, kind, mode, wallets: sc.append((chain, kind)) or None
    c.svc_recon._scope_ready = lambda scope: True
    c.svc_recon._recon_quiet = lambda *a: True
    try:
        c.svc_recon._recon_pass_scopes(set(), True, jobs)
    finally:
        for k9 in ("_recon_bal", "_scope_ready", "_recon_quiet"):
            c.svc_recon.__dict__.pop(k9, None)
    return sc


def wsum():
    out = {}
    for r in c.conn.execute("SELECT a.symbol, SUM(CAST(p.qty_base AS INTEGER)) AS s FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                            " WHERE p.location=? GROUP BY a.symbol", (LA,)):
        out[r["symbol"]] = int(r["s"])
    return out


def openings():
    return {(r["symbol"], int(r["q"])) for r in c.conn.execute(
        "SELECT a.symbol, p.qty_base AS q FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.source_kind='opening'")}


feed(N.rec("tron", "c1" * 32, NOW - 20 * DAY, [(A, "native", 5_000_000), (A, TKA, 5_000_000), (A, TKB, 4_000_000)], height=120))
feed(N.rec("tron", "c2" * 32, NOW - 60, [(A, "native", 1_000_000)], height=260))
c.conn.commit()

check("N0 어댑터 없음 = 새 체인 대사 스코프 없음", ("tron", "nonevm") not in scopes(), scopes())


class FakeAdapter(reg.ChainAdapter):
    chain = "tron"
    mode = "full"
    calls = []

    def fetch_balances(self, owners, boundary, tokens=None):
        self.calls.append((sorted(owners), tokens))
        pw = {A: {("native", None): 12_000_000, ("token", N.TOK["tron"]): 3_000_000}}
        if self.mode == "missing":
            pw = {}
        return {"per_wallet": pw, "_meta": {N.TOK["tron"]: ("TKA", 6)},
                "_boundary": {"kind": "height", "value": "200", "hash": None, "ts": NOW - 3600},
                "_complete": self.mode != "partial", "_source": "fake", "_ownership_version": "x"}


ad = FakeAdapter({})
c.svc_recon._nonevm_adapters = {"tron": ad}
check("N0 어댑터 있으면 스코프 (tron, nonevm)", ("tron", "nonevm") in scopes())

c.svc_recon._last_recon = 0
c.svc_recon.recon_pass({"tron"})
check("N1 동기화 도장 없음 = 대사 안 함", not c._meta_get("recon_done_tron") and not ad.calls)
st = cs.ChainState("tron")
st.set_status(A, requested_from=0, details_complete_through=NOW)
st.pending_upsert([("p1", {"owner": A})])
st.mark_synced()
check("N1 대기 남음 = 준비 안 됨", not c.svc_recon._scope_ready("tron"))
st.mark_emitted("p1", "c1" * 32)
st.save()
check("N1 도장 신선 + 백필 완료 + 대기 0 = 준비", c.svc_recon._scope_ready("tron"))

ad.mode = "partial"
c.svc_recon._last_recon = 0
c.svc_recon.recon_pass({"tron"})
check("N4 부분 결과 = 보류(기초 잔고·도장 없음)", not c._meta_get("recon_done_tron") and not openings(), openings())
ad.mode = "missing"
c.svc_recon._last_recon = 0
c.svc_recon.recon_pass({"tron"})
check("N4 지갑 빠진 결과 = 보류", not c._meta_get("recon_done_tron") and not openings())

ad.mode = "full"
c.svc_recon._last_recon = 0
c.svc_recon.recon_pass({"tron"})
check("N2 대사 완료 도장", bool(c._meta_get("recon_done_tron")))
check("N2 어댑터에 원장 토큰 키 전달(지갑별)", ad.calls[-1][1] == {A: sorted([N.TOK["tron"], "41" + "b2" * 20])}, ad.calls[-1])
op = openings()
check("N2·N6 기초 잔고 = 경계 잔고 − 경계까지 원장(TRX 12 − 5 = +7 · 경계 뒤 +1 은 안 섞임) · TKA 3 − 5 = −2", op == {("TRX", 7_000_000), ("TKA", -2_000_000)}, op)
check("N3 조회 범위 밖 원장 토큰(TKB) = 레그 없음(0 으로 안 봄)", not any(s == "TKB" for s, _q in op))
pay = json.loads(c.conn.execute("SELECT payload FROM raw_observations WHERE obs_id='recon:tron'").fetchone()[0])
check("N2 관측 payload = 경계 블록 200 · 조회 범위", pay.get("_block") == 200 and pay.get("_source") == "rpc" and pay.get("_q"), pay)
check("N2 지갑 칸 합 = 관측 잔고 + 경계 뒤 유입(TRX 13 · TKA 3 · TKB 4)", wsum() == {"TRX": 13_000_000, "TKA": 3_000_000, "TKB": 4_000_000}, wsum())

feed(N.rec("tron", "c3" * 32, NOW - 10 * DAY, [(A, "native", 2_000_000)], height=150))
c.conn.commit()
check("N5 경계 이전 늦은 유입 +2 → 기초 잔고 7 → 5 로 흡수(합 그대로 13)", wsum()["TRX"] == 13_000_000 and ("TRX", 5_000_000) in openings(),
      (wsum(), openings()))
feed(N.rec("tron", "c4" * 32, NOW - 30, [(A, "native", 1_000_000)], height=300))
c.conn.commit()
check("N5 경계 뒤 새 유입은 그대로 더함(14)", wsum()["TRX"] == 14_000_000, wsum())
reg.FORCE_AVAILABLE.clear()
T.finish()
