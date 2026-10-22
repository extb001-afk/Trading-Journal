#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
from _ingest import check  # noqa: E402
import _nonevm as N  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time as _rt  # noqa: E402
import types  # noqa: E402

import config, paths  # noqa: E402
import chain_registry as reg  # noqa: E402
import chain_state as cs  # noqa: E402
import chain_watch as cw  # noqa: E402
import address_codec as ac  # noqa: E402
from inbox import SegmentWriter, SegmentReader  # noqa: E402


def S(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as e:   # noqa: BLE001
        return f"예외:{type(e).__name__}"


RETRY = getattr(cs, "GAP_RETRY_SEC", 6 * 3600)
A, B = N.OWN["tron"]
UID = "ab" * 32
T_REAL = int(_rt.time())


class Clock:
    t = float(T_REAL)

    def time(self):
        return Clock.t


cs.time = types.SimpleNamespace(time=Clock().time)
cw.time = types.SimpleNamespace(time=Clock().time, sleep=lambda s: None)


class Ad(reg.ChainAdapter):
    chain = "tron"
    down = True
    found = False
    fetches = 0

    def discovery_query(self, owner, lane):
        return ({"lane": lane}, "fp")

    def discover_page(self, owner, q, cur):
        if q["lane"] == "latest" and owner == A and not Ad.found:
            Ad.found = True
            return [{"stable_id": UID}], None
        return [], None

    def fetch_and_normalize(self, ref, owners):
        Ad.fetches += 1
        if Ad.down:
            raise cw.Transient("제공자 하루 몫 소진(합성) — UTC 자정 뒤 이어서")
        return N.rec("tron", UID, T_REAL - 86400, [(A, "native", 5_000_000)], height=150)


CFG_PATH = os.path.join(T.TMP, "config.json")
cfg = json.load(open(CFG_PATH))
cfg["chain_wallets"] = [{"chain": "tron", "address": ac.tron_display(A)}]
json.dump(cfg, open(CFG_PATH, "w"))
reg.FORCE_AVAILABLE.add("tron")
INB = os.path.join(paths.INBOX_DIR, "tron")
W = SegmentWriter(INB)
st = cs.ChainState("tron")
st.set_status(A, requested_from=0, available_from=0, scanned_through=100, details_complete_through=100)
col = cw.Collector(Ad({}), W, st, {A})


def run(sec, step=60):
    end = Clock.t + sec
    while Clock.t < end:
        col.cycle()
        Clock.t += step


t0 = Clock.t
while st.d["pending"] or not Ad.found:
    col.cycle()
    Clock.t += 60
check("RQ1 장애 약 14.6시간 뒤 gap 1 · 대기 0", [g["id"] for g in st.d["gaps"]] == [UID] and not st.d["pending"]
      and 14 * 3600 < Clock.t - t0 < 15 * 3600, ((Clock.t - t0) / 3600, st.d["gaps"], list(st.d["pending"])))

import health  # noqa: E402
g6 = health.collect_nonevm_gaps(config.load_config())
check("RQ6 헬스: 재시도 성공 전 미해소 1건(ledger:gap:tron 재료)", (g6.get("tron") or {}).get("n") == 1, g6)

import core  # noqa: E402
c = core.Core(config.load_config())
c.conn.commit()


class BalAd(reg.ChainAdapter):
    chain = "tron"

    def fetch_balances(self, owners, boundary, tokens=None):
        return {"per_wallet": {A: {("native", None): 7_000_000}}, "_meta": {},
                "_boundary": {"kind": "height", "value": "200", "hash": None, "ts": T_REAL - 3600},
                "_complete": True, "_source": "fake", "_ownership_version": "x"}


c.svc_recon._nonevm_adapters = {"tron": BalAd({})}


def drain():
    rd = SegmentReader(INB)
    for _i in range(20):
        row = c.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream='tron'").fetchone()
        seg, off = (row["seg"], row["off"]) if row else (1, 0)
        c._drain_stream("tron", rd, seg, off)
        row2 = c.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream='tron'").fetchone()
        if row2 and row and (row2["seg"], row2["off"]) == (seg, off):
            break
    c.conn.commit()


def recon():
    drain()
    c.svc_recon._last_recon = 0
    c.svc_recon.recon_pass({"tron"})


recon()
check("RQ7 gap 미해소 = 체인 준비 아님 · 대사 보류(recon_done_tron 없음)", not c.svc_recon._scope_ready("tron") and not c._meta_get("recon_done_tron"),
      (c.svc_recon._scope_ready("tron"), c._meta_get("recon_done_tron")))

Ad.down = False
f0 = Ad.fetches
run(RETRY - 3600)
check("RQ2 회복했어도 gap 직후(재시도 간격 안) = 재시도 없음 · 방출 없음", Ad.fetches == f0 and not st.emitted(UID) and len(st.unresolved_gaps()) == 1,
      (Ad.fetches - f0, st.d["pending"]))

run(2 * 3600)
st = cs.ChainState("tron")
check("RQ3 회복 + 재시도 간격 지남 = 자동 재시도로 방출 1 · 미해소 gap 0", st.emitted(UID) and st.unresolved_gaps() == [] and Ad.fetches == f0 + 1,
      (Ad.fetches - f0, st.d["gaps"], list(st.d["pending"])))
check("RQ3 그 지갑 백필 완료(owner_done) · 체인 준비(ready) · 화면 complete", st.owner_done(A) and st.ready({A}) and st.status_view()[A]["complete"],
      (st.owner_done(A), st.ready({A}), st.status_view().get(A)))
check("RQ3 gap 이력 1줄은 남음(증거 · 해소로 판정)", len(st.d["gaps"]) == 1 and st.status_view()[A]["gaps"] == 1, st.d["gaps"])

g6 = health.collect_nonevm_gaps(config.load_config())
check("RQ6 헬스: 재시도 성공 뒤 미해소 0건(ledger:gap 풀림)", (g6.get("tron") or {}).get("n") == 0, g6)

recon()
op = {(r["location"], int(r["q"])) for r in c.conn.execute(
    "SELECT p.location, p.qty_base AS q FROM postings p WHERE p.source_kind='opening'")}
check("RQ7 재시도 성공 뒤 체인 준비 → 기초잔고 대사 완료(recon_done_tron) · 기초잔고 = 7 − 5 = 2 TRX(누락분 5 를 흡수하지 않음)",
      bool(c._meta_get("recon_done_tron")) and op == {(reg.make_location("tron", A), 2_000_000)}, (c._meta_get("recon_done_tron"), op))
c.conn.close()

U2 = "cd" * 32
st.pending_upsert([(U2, {"owner": A, "lane": "history"})])
for _i in range(cs.MAX_TRIES):
    st.reschedule(U2, "일시 실패: 합성")
Ad.down = True
col = cw.Collector(Ad({}), W, st, {A})
f0 = Ad.fetches
run(3 * RETRY + 1800)
gl = [g for g in st.d["gaps"] if g.get("id") == U2]
check("RQ4 계속 장애 = 재시도 간격마다 상세 1회만(3회) · 실패 즉시 gap 으로", Ad.fetches - f0 == 3 and U2 not in st.d["pending"],
      (Ad.fetches - f0, st.d["pending"].get(U2)))
check("RQ4 gap 목록은 (id, 지갑) 1줄 유지(재시도마다 자라지 않음) · 마지막 실패 시각으로", len(gl) == 1 and gl[0]["at"] > T_REAL + RETRY, gl)

SD5 = os.path.join(T.TMP, "rq5")
os.makedirs(SD5, exist_ok=True)
s5 = cs.ChainState("btc", SD5)
old = int(Clock.t) - RETRY - 10
s5.d["gaps"] = [{"id": "reorg:900", "ref": {"owner": "w1", "lane": "reorg"}, "why": "깊은 재편", "tries": 0, "at": old},
                {"id": "gone1", "ref": {"owner": "w9", "lane": "history"}, "why": "x", "tries": 12, "at": old},
                {"id": "done1", "ref": {"owner": "w1", "lane": "history"}, "why": "x", "tries": 12, "at": old},
                {"id": "fresh1", "ref": {"owner": "w1", "lane": "latest"}, "why": "x", "tries": 12, "at": int(Clock.t) - 60},
                {"id": "dup1", "ref": {"owner": "w1", "lane": "history"}, "why": "x", "tries": 12, "at": old},
                {"id": "ok1", "ref": {"owner": "w1", "lane": "history", "h": 5}, "why": "x", "tries": 12, "at": old}]
s5.em["uids"]["done1"] = {"t": 1, "o": ["w1"]}
s5.d["pending"]["dup1"] = {"ref": {"owner": "w1", "lane": "history"}, "first": 1, "tries": 3, "next": 0, "why": "x"}
n5 = S(lambda: s5.requeue_gaps({"w1"}))
check("RQ5 재투입 = 6시간 지난 미해소 gap 만(재편·지갑 밖·해소·대기 중·갓 생긴 것 제외) · ref 그대로 · tries = MAX_TRIES-1",
      n5 == 1 and set(s5.d["pending"]) == {"dup1", "ok1"} and (s5.d["pending"].get("ok1") or {}).get("ref") == {"owner": "w1", "lane": "history", "h": 5}
      and (s5.d["pending"].get("ok1") or {}).get("tries") == cs.MAX_TRIES - 1 and s5.d["pending"]["dup1"]["tries"] == 3, (n5, s5.d["pending"]))
check("RQ5 재편 gap 은 남음(설정 reorg_ack 로만 풀림)", any(g["id"] == "reorg:900" for g in s5.d["gaps"]))

cs.time = _rt
cw.time = _rt
T.finish()
