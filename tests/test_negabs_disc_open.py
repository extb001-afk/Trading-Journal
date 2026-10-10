#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _ingest
from _ingest import W, Reader

import json
import os
import sqlite3
import subprocess
import time

import common
import core

chk = T.chk
core.dm = lambda *a, **k: None
try:
    import discopen
except ImportError as e:
    chk(False, "발견 시점 기초 잔고 모듈(src/discopen.py) 있음", repr(e))
    T.finish()

E18 = 10 ** 18
DAY = 86400
NOW = int(time.time())
X = "0x" + "b7" * 20
TKN, TK2, TK4, TK5, TK6, TK9, TKA = ("0x" + c * 20 for c in ("e1", "e2", "e4", "e5", "e6", "e9", "ea"))
IMP, SPF = "0x" + "f1" * 20, "0x" + "f2" * 20
T0 = NOW - 20 * DAY


def h(n):
    return "0x" + ("%064x" % n)


def snap(hx, ts, blk, frm, to, value=0, toks=(), fee=0, data="0xa9059cbb"):
    return {"tx": {"hash": hx, "from": frm, "to": to, "value": str(value), "fee": {"value": str(fee)}, "status": "ok", "raw_input": data,
                   "timestamp": ts, "block_number": blk, "block_hash": "0x" + "d" * 64},
            "token_transfers": [{"from": f, "to": t, "token": {"address": ca, "symbol": sym, "decimals": 18, "type": "ERC-20"},
                                 "total": {"value": str(v)}} for f, t, ca, sym, v in toks],
            "internal": []}


def feed(c, hx, s):
    c._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": hx, "wallets": [W], "snapshot": s, "ts": 1}]), 0, 0)


def aid_of(c, ca):
    r = c.conn.execute("SELECT asset_id FROM assets WHERE chain='eth' AND address=?", (ca,)).fetchone()
    return r[0] if r else None


def total(c, ca):
    a = aid_of(c, ca)
    return sum(int(r[0]) for r in c.conn.execute("SELECT qty_base FROM postings WHERE location=? AND asset_id=?", (f"wallet:eth:{W}", a))) if a else 0


def anchors(c, ca=None):
    q = "SELECT source_id, event_ts, qty_base, asset_id FROM postings WHERE source_kind='opening' AND source_id LIKE 'recon:%:disc:%'"
    rows = [tuple(r) for r in c.conn.execute(q + " ORDER BY source_id")]
    return [r for r in rows if ca is None or r[3] == aid_of(c, ca)]


def cand(c, ca):
    return discopen._jload(discopen._meta(c.conn, discopen.cand_key("eth", W, aid_of(c, ca))), None) or {}


CALLS = []
FAKE = {}


def fake_fetch(urls, w, ca, blk, tries=2):
    CALLS.append((ca, int(blk)))
    v = FAKE.get((ca, int(blk)))
    if isinstance(v, BaseException):
        raise v
    if v is None:
        raise RuntimeError("rpc eth_call: 전 엔드포인트 실패 — 시험 목 없음")
    return v


discopen.fetch_at = fake_fetch


def pump(c, n=60):
    for _ in range(n):
        r = c._negabs_runner()
        r.last = 0.0
        c.negabs_pass()
        if not any(not j["ev"].is_set() for j in r.jobs.values()) and not r.jobs:
            return
        time.sleep(0.02)


c = core.Core(common.load_config())
c.conn.commit()
c.conn.execute("INSERT INTO meta (k, v) VALUES (?, ?)", (f"wrecon_done:eth:{W}", str(T0)))
c.conn.execute("INSERT INTO raw_observations (obs_id, kind, venue, payload, observed_at) VALUES (?,?,?,?,?)",
               (f"recon:eth:{W}", "opening_balance", "eth", json.dumps({W: {"native:None": 0}, "_source": "rpc", "_block": 900, "_q": []}), T0))
c.conn.commit()
common.atomic_write_json(os.path.join(common.STATE_DIR, "cursor_evm_eth.json"), {W: 5000, "_synced_at": NOW + 3600})
feed(c, h(1), snap(h(1), T0 + 100, 1500, X, W, value=2 * E18, data="0x"))
c.conn.commit()
PRE = os.path.join(T.TMP, "ledger_before_deploy.db")
_bk = sqlite3.connect(PRE)
c.conn.backup(_bk)
_bk.close()

print("[N1] 조회 성공 흡수")
T1 = T0 + 5 * DAY
FAKE[(TKN, 1999)] = (1000 * E18, T1 - 12)
feed(c, h(11), snap(h(11), T1, 2000, W, TKN, toks=[(W, X, TKN, "TKN", 600 * E18)], fee=10 ** 15))
chk(total(c, TKN) == -600 * E18 and cand(c, TKN).get("st") == "new" and cand(c, TKN).get("tx") == h(11),
    "N1 전제: 원장 −600 · 후보(meta negabs_cand) = 그 tx", (total(c, TKN), cand(c, TKN)))
pump(c)
an = anchors(c, TKN)
sid1 = discopen.sid_of("eth", W, TKN, 1999)
chk(total(c, TKN) == 400 * E18, "N1 앵커 뒤 원장 = 400(실잔고 1,000 − 600)", total(c, TKN))
chk(len(an) == 1 and an[0][0] == sid1 and an[0][1] == T1 - 12 and int(an[0][2]) == 1000 * E18,
    "N1 앵커 = +1,000 · 시각 = 직전 블록 시각(그 tx 앞) · source_id recon:eth:<지갑>:disc:<CA>@B−1", an)
ob = c.conn.execute("SELECT kind, payload, observed_at FROM raw_observations WHERE obs_id=?", (sid1,)).fetchone()
pl1 = json.loads(ob[1]) if ob else {}
chk(ob and ob[0] == "opening_balance" and ob[2] == T1 - 11 and pl1.get("_block") == 1999 and pl1.get("_q") == [f"{W}:{TKN}"]
    and pl1.get(W) == {f"token:{TKN}": 1000 * E18} and pl1.get("_basis") == "neg_tx" and pl1.get("_at") == T1 - 12,
    "N1 관측(raw_observations) = 감사 기록 · T = 블록 시각 + 1 · 조회 범위 이 칸만", (ob and ob[2], pl1))
chk(cand(c, TKN).get("st") == "done" and CALLS.count((TKN, 1999)) == 1, "N1 후보 상태 done · 조회 1번", (cand(c, TKN), CALLS))
pr = c.conn.execute("SELECT cost_usd, leg_kind, event FROM postings WHERE source_id=?", (sid1,)).fetchone()
chk(pr and pr[0] is None and pr[1] == "opening" and pr[2] == "OPENING", "N1 원가 NULL · opening/OPENING(대사 앵커 규약)", pr and tuple(pr))

print("[N2] 조회 실패 = 음수 유지")
T2 = T1 + DAY
FAKE[(TK2, 2099)] = RuntimeError("rpc eth_call: 전 엔드포인트 실패 — timeout")
feed(c, h(21), snap(h(21), T2, 2100, W, TK2, toks=[(W, X, TK2, "TKB", 100 * E18)], fee=10 ** 15))
pump(c)
chk(total(c, TK2) == -100 * E18 and not anchors(c, TK2) and cand(c, TK2).get("st") == "retry" and cand(c, TK2).get("n") == 1,
    "N2 조회 실패 1번 = 음수 그대로 · 재시도 대기(n=1)", cand(c, TK2))
for _ in range(discopen.MAX_TRIES + 2):
    d9 = cand(c, TK2)
    if d9.get("st") == "fail":
        break
    d9["next"] = 0
    c._negabs_runner()._put(discopen.cand_key("eth", W, aid_of(c, TK2)), d9)
    c.conn.commit()
    pump(c)
chk(cand(c, TK2).get("st") == "fail" and cand(c, TK2).get("n") == discopen.MAX_TRIES and total(c, TK2) == -100 * E18,
    f"N2 재시도 상한({discopen.MAX_TRIES}) 뒤 'fail' — 종전 음수 유지(상태 패널 주의 그대로)", cand(c, TK2))
n2 = CALLS.count((TK2, 2099))
pump(c)
chk(CALLS.count((TK2, 2099)) == n2, "N2 'fail' 뒤 더 조회 안 함", CALLS.count((TK2, 2099)))

print("[N3] 스팸 무시")
T3 = T2 + DAY
feed(c, h(31), snap(h(31), T3, 2150, W, IMP, toks=[(W, X, IMP, "ÚSDС", 10 * E18)], fee=10 ** 15))
feed(c, h(32), snap(h(32), T3 + 60, 2151, X, SPF, toks=[(W, X, SPF, "SPF", 5 * E18)], fee=10 ** 15))
n3 = len(CALLS)
pump(c)
chk(total(c, IMP) == -10 * E18 and cand(c, IMP).get("st") == "skip" and "사칭" in cand(c, IMP).get("why", ""),
    "N3 사칭 심볼 = 건너뜀(음수 그대로)", cand(c, IMP))
chk(total(c, SPF) == -5 * E18 and cand(c, SPF).get("st") == "skip" and "서명" in cand(c, SPF).get("why", ""),
    "N3 남이 서명한 유출(주소 오염 가짜 전송) = 건너뜀", cand(c, SPF))
chk(len(CALLS) == n3, "N3 스팸 칸은 RPC 조회 0", CALLS[n3:])

print("[N4] 같은 블록·같은 tx 순서")
T4 = T3 + DAY
feed(c, h(41), snap(h(41), T4, 2300, W, TK4, toks=[(W, X, TK4, "TKD", 70 * E18)], fee=10 ** 15))
chk(cand(c, TK4).get("st") == "new", "N4 전제: 보냄만 도착 = 후보", cand(c, TK4))
feed(c, h(42), snap(h(42), T4, 2300, X, TK4, toks=[(X, W, TK4, "TKD", 70 * E18)], data="0xa9059cbb"))
feed(c, h(51), snap(h(51), T4 + 60, 2310, W, X, toks=[(X, W, TK5, "TKE", 20 * E18), (W, X, TK5, "TKE", 20 * E18)], fee=10 ** 15,
                     data="0x12345678"))
n4 = len(CALLS)
pump(c)
chk(total(c, TK4) == 0 and cand(c, TK4).get("st") == "gone" and not anchors(c, TK4), "N4 같은 블록 받기가 늦게 와도 = 음수 아님(gone · 앵커 없음)", cand(c, TK4))
chk(not cand(c, TK5) and not anchors(c, TK5), "N4 같은 tx 안 들어옴·나감(순 0) = 후보 없음", cand(c, TK5))
chk(len(CALLS) == n4, "N4 조회 0", CALLS[n4:])

print("[N6] 과거 블록 상태 없음 → 확실할 때만 대체")
T6 = T4 + DAY
FAKE[(TK6, 2399)] = RuntimeError("rpc eth_call: {'code': -32000, 'message': 'missing trie node abc'}")
FAKE[(TK6, 5000)] = (30 * E18, T6 + 3600)
feed(c, h(61), snap(h(61), T6, 2400, W, TK6, toks=[(W, X, TK6, "TKF", 50 * E18)], fee=10 ** 15))
pump(c)
an6 = anchors(c, TK6)
chk(total(c, TK6) == 30 * E18 and len(an6) == 1 and int(an6[0][2]) == 80 * E18 and an6[0][1] == T6 - 1
    and an6[0][0] == discopen.sid_of("eth", W, TK6, 5000),
    "N6 대체 = 커서 블록 잔고 30 − 그 뒤 원장(−50) = 앵커 80(시각 = 그 tx − 1초 · 관측 블록 = 커서)", (an6, total(c, TK6)))
pl6 = json.loads(c.conn.execute("SELECT payload FROM raw_observations WHERE obs_id=?", (an6[0][0],)).fetchone()[0]) if an6 else {}
chk(pl6.get("_basis") == "neg_tx_now_minus_flows" and pl6.get("_block") == 5000, "N6 관측 표식 = 대체 방식 · 관측 블록 5000", pl6)

print("[N5] 재시작 멱등")
n5, a5 = len(CALLS), anchors(c)
p5 = {(r[0], r[1]): r[2] for r in c.conn.execute("SELECT group_id, location, qty_norm FROM positions")}
c.conn.commit()
c2 = core.Core(common.load_config())
pump(c2)
feed(c2, h(11), snap(h(11), T1, 2000, W, TKN, toks=[(W, X, TKN, "TKN", 600 * E18)], fee=10 ** 15))
pump(c2)
p5b = {(r[0], r[1]): r[2] for r in c2.conn.execute("SELECT group_id, location, qty_norm FROM positions")}
chk(anchors(c2) == a5 and len(CALLS) == n5 and p5b == p5, "N5 새 core(재시작) — 앵커·조회 수·포지션 그대로", (len(anchors(c2)), len(a5), CALLS[n5:]))
ra = c2._negabs_runner()
sid9 = discopen.write_anchor(c2, "eth", W, aid_of(c2, TKN), TKN, 5, 1999, T1 - 12, T1 - 1, 1000 * E18, "neg_tx")
c2.conn.commit()
chk(sid9 == "" and anchors(c2) == a5, "N5 같은 관측 다시 쓰기 = 무변(멱등)", sid9)
c.conn.close()
c = c2

print("[N7] rebuild2(재파생 + 앵커 재계산) 뒤 같은 결과")
import importlib.util
spec = importlib.util.spec_from_file_location("rb2", os.path.join(T.ROOT, "tools", "rebuild2.py"))
rb2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rb2)


def shadow_rebuild(tag, mutate=None):
    c.conn.commit()
    bp, sp = os.path.join(T.TMP, f"rb_base_{tag}.db"), os.path.join(T.TMP, f"rb_shadow_{tag}.db")
    for p9 in (bp, sp):
        d9 = sqlite3.connect(p9)
        c.conn.backup(d9)
        d9.close()
    if mutate:
        m9 = sqlite3.connect(sp)
        mutate(m9)
        m9.commit()
        m9.close()
    anc = [tuple(r) for r in sqlite3.connect(bp).execute(rb2.ANCHOR_SQL).fetchall()]
    old9 = common.DB_PATH
    common.DB_PATH = sp
    try:
        sc = core.Core(common.load_config())
    finally:
        common.DB_PATH = old9
    for t9 in rb2.DERIVED_TABLES:
        sc.conn.execute(f"DELETE FROM {t9}")
    sc.conn.commit()
    for r in sc.conn.execute("SELECT chain, txhash, snapshot FROM raw_txs ORDER BY ingested_at, chain, txhash").fetchall():
        sc.conn.execute("BEGIN")
        sc.apply(r["chain"], r["txhash"], "", json.loads(r["snapshot"]))
        sc.conn.commit()
    obs = {r[0]: r[1] for r in sc.conn.execute("SELECT obs_id, observed_at FROM raw_observations")}
    meta = {r[0]: int(r[1]) for r in sc.conn.execute("SELECT k, v FROM meta WHERE k LIKE 'recon_done_%'")}
    rep = rb2.recompute_anchors(bp, sc.conn, sc, anc, obs, meta)
    sc.conn.commit()
    spot9 = os.path.join(T.TMP, "rb_spot.json")
    json.dump({"usd": {"ETH": 2000.0}, "dex_usd": {f"eth:{ca}": 1.0 for ca in (TKN, TK2, TK4, TK6, TK9, TKA)}}, open(spot9, "w"))
    rep["obs_gate"] = rb2.obs_replay_gate(bp, sp, spot9, live_immutable=False)
    return sc, rep


def cells(cc):
    return {(r[0], r[1]): int(r[2]) for r in cc.conn.execute(
        "SELECT location, asset_id, SUM(CAST(qty_base AS INTEGER)) FROM postings WHERE location LIKE 'wallet:%' GROUP BY location, asset_id")}


sc, rep = shadow_rebuild("a")
da = sorted((r[0], r[1], r[2]) for r in c.conn.execute("SELECT source_id, event_ts, qty_base FROM postings WHERE source_id LIKE 'recon:%:disc:%'"))
db9 = sorted((r[0], r[1], r[2]) for r in sc.conn.execute("SELECT source_id, event_ts, qty_base FROM postings WHERE source_id LIKE 'recon:%:disc:%'"))
chk(cells(sc) == cells(c), "N7 재구축 뒤 (지갑, 자산) 합 = 라이브와 같음", {str(k): (v, cells(c).get(k)) for k, v in cells(sc).items() if cells(c).get(k) != v})
chk(db9 == da and len(da) == 2, "N7 발견 시점 앵커 = 금액·시각 그대로(창 시작으로 당기지 않음)", (da, db9))
og7 = rep.get("obs_gate") or {}
chk(og7.get("ok") is True and og7.get("worse_n") == 0 and og7.get("checked", 0) >= 1, "N7 rebuild2 관측 재현 게이트(G_obs_replay) 통과 — 발견 시점 관측 = 원장", og7)
sc.conn.close()

print("[N8] 늦게 온 옛 받기(관측 블록 이하) → 재구축이 앵커를 줄임")
feed(c, h(81), snap(h(81), T1 - 600, 1800, X, TKN, toks=[(X, W, TKN, "TKN", 300 * E18)]))
chk(total(c, TKN) == 700 * E18 and discopen._meta(c.conn, f"ext_prewindow_tx:eth:{h(81)}") is not None,
    "N8 라이브 = 700(앵커가 흡수한 흐름 이중 — 재구축 대기 표식 ext_prewindow_tx)", (total(c, TKN), discopen._meta(c.conn, f"ext_prewindow_tx:eth:{h(81)}")))
pl8 = discopen.plan_cell(c.conn, "eth", W, aid_of(c, TKN), {}, {W})
sc, rep = shadow_rebuild("b")
a8 = [tuple(r) for r in sc.conn.execute("SELECT event_ts, qty_base FROM postings WHERE source_id=?", (sid1,))]
t8 = sum(int(r[0]) for r in sc.conn.execute("SELECT qty_base FROM postings WHERE location=? AND asset_id=?", (f"wallet:eth:{W}", aid_of(c, TKN))))
chk(a8 == [(T1 - 12, str(700 * E18))] and t8 == 400 * E18, "N8 재구축 = 앵커 1,000 → 700(시각 그대로) · 합 400 = 실잔고", (a8, t8))
chk((rep.get("obs_gate") or {}).get("ok") is True, "N8 관측 재현 게이트 통과(재구축이 관측에 더 가까워짐)", rep.get("obs_gate"))
sc.conn.close()

print("[N9] 토큰 재점검 결과(JSON 줄) 적용")
T9 = T6 + DAY


def it(ca, blk, cbal, led, spam=False, **kw):
    return dict({"chain": "eth", "wallet": W, "ca": ca, "symbol": "TKI", "decimals": 18, "block": blk, "chain_bal_raw": str(cbal), "ledger_raw": str(led),
                 "diff_raw": str(cbal - led), "spam": spam, "sources": ["synthetic"], "block_ts": T9}, **kw)


items = [it(TK9, 4000, 250 * E18, 0), it(TKA, 4000, 7 * E18, 0, spam=True), it(TKN, 4000, 100 * E18, 400 * E18),
         it(TK2, 4000, 50 * E18, -100 * E18), it(TK9, 6000, 260 * E18, 0)]
common.atomic_write_json(os.path.join(common.STATE_DIR, discopen.RECHK_REQ_NAME), {"items": items, "by": "test"})
pump(c)
res = (common.read_json(os.path.join(common.STATE_DIR, discopen.RES_NAME), {}) or {}).get("recheck") or {}
st9 = {k.split(":")[2]: v.get("st") for k, v in res.items()}
a9 = anchors(c, TK9)
chk(len(a9) == 1 and int(a9[0][2]) == 250 * E18 and a9[0][1] == T9 and a9[0][0] == discopen.sid_of("eth", W, TK9, 4000) and total(c, TK9) == 250 * E18,
    "N9 diff>0 ∧ 스팸 아님 = 그 블록 시각에 +250(원장에 처음 보는 토큰도 자산 생성)", (a9, st9))
chk(st9.get(f"{TKA}@4000") == "skip" and not anchors(c, TKA), "N9 스팸 줄 = 넣지 않음", st9)
chk(st9.get(f"{TKN}@4000") == "list" and st9.get(f"{TK2}@4000") == "list" and st9.get(f"{TK9}@6000") == "wait",
    "N9 원장이 더 많음·그 블록 음수 칸 = 목록만 · 수집기 커서 밖 블록 = 대기", st9)
pr9 = json.loads(c.conn.execute("SELECT payload FROM raw_observations WHERE obs_id=?", (a9[0][0],)).fetchone()[0]) if a9 else {}
chk(pr9.get("_basis") == "token_recheck" and pr9.get("_sources") == ["synthetic"], "N9 관측 = 재점검 출처 기록", pr9)

print("[N10] 지금 음수 칸 도구 → 요청 → core")
os.environ["TJ_NEGABS"] = "0"
FAKE[(TK4, 2799)] = (90 * E18, T6 + 7200)
feed(c, h(91), snap(h(91), T6 + 7200 + 12, 2800, W, TK4, toks=[(W, X, TK4, "TKD", 40 * E18)], fee=10 ** 15))
os.environ.pop("TJ_NEGABS")
c.conn.commit()
c._negabs_runner()._put(discopen.cand_key("eth", W, aid_of(c, TK4)), {"st": "gone"})
c.conn.commit()
env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_") or k.startswith("TJ_TEST_")}
env.update(TJ_BASE=T.TMP, PYTHONDONTWRITEBYTECODE="1")
tl = os.path.join(T.ROOT, "tools", "negabs_1010.py")
r1 = subprocess.run([sys.executable, tl, "--json"], env=env, capture_output=True, text=True, timeout=120)
try:
    pv = json.loads(r1.stdout)
except ValueError:
    pv = []
pvd = {(x.get("ca") or "native"): x.get("plan") for x in pv}
chk(r1.returncode == 0 and pvd.get(TK4) == "go" and pvd.get(IMP) == "skip" and pvd.get(SPF) == "skip" and pvd.get(TK2) == "go",
    "N10 미리보기 = 음수 칸과 가드 판정(TKD go · 사칭·가짜 skip)", (r1.returncode, pvd, r1.stderr[-300:]))
chk(not os.path.exists(os.path.join(common.STATE_DIR, discopen.REQ_NAME)), "N10 미리보기는 요청 파일을 안 씀", None)
r2 = subprocess.run([sys.executable, tl, "--apply"], env=env, capture_output=True, text=True, timeout=120)
rq = common.read_json(os.path.join(common.STATE_DIR, discopen.REQ_NAME), {}) or {}
chk(r2.returncode == 0 and any(x.get("ca") == TK4 for x in rq.get("cells") or []), "N10 --apply = state/negabs_request.json", (r2.stdout[-300:], rq))
pump(c)
a10 = anchors(c, TK4)
chk(len(a10) == 1 and int(a10[0][2]) == 90 * E18 and a10[0][1] == T6 + 7200 and total(c, TK4) == 50 * E18,
    "N10 core = 직전 블록 잔고 90 확인 → 앵커 90(직전 블록 시각) · 원장 50", (a10, total(c, TK4)))
chk(cand(c, TK2).get("st") == "fail" and not anchors(c, TK2), "N10 이미 'fail' 난 칸은 --retry 없이 다시 안 엶", cand(c, TK2))

print("[N12] 이 거래 뒤 잔고를 이미 본 대사 관측이 있는 칸 = 건너뜀(멱등 · 이중 계상 방지)")
TKQ = "0x" + "eb" * 20
TB = T6 + 3 * DAY
c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('recon_done_base', ?)", (str(TB + 100),))
c.conn.execute("INSERT OR REPLACE INTO raw_observations (obs_id, kind, venue, payload, observed_at) VALUES (?,?,?,?,?)",
               ("recon:base", "opening_balance", "base", json.dumps({W: {f"token:{TKQ}": 0}}), TB + 100))
c.conn.commit()
c.conn.execute("BEGIN")
c._consume_record({"v": 1, "kind": "evm_tx", "chain": "base", "txhash": h(121), "wallets": [W],
                   "snapshot": snap(h(121), TB, 777, W, TKQ, toks=[(W, X, TKQ, "TKQ", 5 * E18)], fee=10 ** 15)})
c.conn.execute("DELETE FROM meta WHERE k LIKE 'ext_prewindow%base%'")
c.conn.commit()
n12 = len(CALLS)
pump(c)
aq = c.conn.execute("SELECT asset_id FROM assets WHERE chain='base' AND address=?", (TKQ,)).fetchone()[0]
d12 = discopen._jload(discopen._meta(c.conn, discopen.cand_key("base", W, aq)), {}) or {}
chk(d12.get("st") == "skip" and "이미 봄" in d12.get("why", "") and len(CALLS) == n12, "N12 대사가 그 거래 뒤 잔고(0)를 이미 봤으면 = 건너뜀 · 조회 0", d12)

print("[N13] (코덱스 na438 ②) BSC — 체인 대사가 그 토큰을 안 물었어도 발견 시점 앵커는 늦은 상세 보강을 흡수")
TKB = "0x" + "c1" * 20
TR = T6 + 4 * DAY
c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('recon_done_bsc', ?)", (str(TR),))
c.conn.execute("INSERT OR REPLACE INTO raw_observations (obs_id, kind, venue, payload, observed_at) VALUES (?,?,?,?,?)",
               ("recon:bsc", "opening_balance", "bsc", json.dumps({W: {"native:None": 0}}), TR))
ab = c.asset_id("token", "bsc", TKB, symbol="TKB", decimals=18)
LB = f"wallet:bsc:{W}"
sid13 = discopen.write_anchor(c, "bsc", W, ab, TKB, 40 * E18, 3000, TR + 500, TR + 500, 40 * E18, "neg_tx")
H13 = h(131)
c.conn.execute("INSERT INTO raw_txs (chain, txhash, block, blockhash, ts, snapshot, wallets, ingested_at) VALUES ('bsc',?,?,?,?,?,?,?)",
               (H13, 2900, "0x" + "d" * 64, None, json.dumps({"tx": {"hash": H13, "timestamp": TR - 100, "block_number": 2900}}), json.dumps([W]), NOW))
c.conn.commit()
before13 = c._tx_wallet_sums("bsc", H13)
c.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind,"
               " event, classifier_ver) VALUES ('chain_tx','bsc',?,0,?,?,?,?,NULL,NULL,'acq','TRANSFER_IN',?)",
               (H13, TR - 100, ab, LB, str(100 * E18), core.CLASSIFIER_VER))
c._bump_position(ab, 100 * E18, LB)
n13 = c._anchor_absorb("bsc", H13, before13)
c.conn.commit()
q13 = c.conn.execute("SELECT qty_base FROM postings WHERE source_id=?", (sid13,)).fetchone()
t13 = sum(int(r[0]) for r in c.conn.execute("SELECT qty_base FROM postings WHERE location=? AND asset_id=?", (LB, ab)))
chk(n13 == 1 and q13 is not None and int(q13[0]) == -60 * E18 and t13 == 40 * E18,
    "N13 BSC 발견 앵커(관측 40)가 늦게 붙은 옛 수령 100 을 흡수 → 앵커 −60 · 합 40 = 관측(종전 140 이중)", (n13, q13 and q13[0], t13))

print("[N14] (코덱스 na438 ①) 네이티브·랩드가 같은 그룹 — 그룹 합이 양수여도 자산별 음수면 후보·도구 목록")
WETH = "0x" + "c2" * 20
c.wrapped["eth"] = WETH
T14 = T6 + 5 * DAY
FAKE[(WETH, 3099)] = (int(0.5 * E18), T14 - 12)
feed(c, h(141), snap(h(141), T14, 3100, W, WETH, toks=[(W, X, WETH, "WETH", int(0.2 * E18))], fee=10 ** 15))
aw = aid_of(c, WETH)
ge = c.conn.execute("SELECT qty_norm FROM positions WHERE group_id=? AND location=?", (c._group_of(aw), f"wallet:eth:{W}")).fetchone()
chk(ge is not None and float(ge[0]) > 0 and c._group_of(aw) == c._group_of(c.asset_id("native", "eth", None, symbol="ETH", decimals=18)),
    "N14 전제: ETH·WETH 같은 그룹 · 그룹 합 양수", ge and ge[0])
chk(cand(c, WETH).get("st") == "new", "N14 자산별 음수(WETH −0.2) = 후보(종전 그룹 양수라 없음)", cand(c, WETH))
chk(("eth", W, aw) in discopen.neg_cells(c.conn, {"eth"}), "N14 도구 목록(neg_cells)에도 WETH 칸", None)
pump(c)
chk(total(c, WETH) == int(0.3 * E18) and len(anchors(c, WETH)) == 1, "N14 직전 블록 0.5 확인 → 앵커 0.5 · 원장 0.3", (total(c, WETH), anchors(c, WETH)))

print("[N15] (코덱스 na438 ③) 재점검 결과를 최신→과거 순으로 적용해도 같은 보유분 중복 없음")
common.atomic_write_json(os.path.join(common.STATE_DIR, discopen.RECHK_REQ_NAME),
                         {"items": [it(TK9, 3500, 250 * E18, 0, block_ts=T9 - 1000)], "by": "test"})
pump(c)
res15 = (common.read_json(os.path.join(common.STATE_DIR, discopen.RES_NAME), {}) or {}).get("recheck") or {}
st15 = {k.split(":")[2]: v.get("st") for k, v in res15.items()}
chk(st15.get(f"{TK9}@3500") == "list" and len(anchors(c, TK9)) == 1 and total(c, TK9) == 250 * E18,
    "N15 같은 칸에 더 늦은 블록(4000) 발견 앵커가 있으면 이른 블록(3500) 결과는 목록만 — 합 250 그대로(종전 500)", (st15, total(c, TK9)))

print("[N16] (보안 na438 1) 남이 서명한 '교환' 모양 가짜 유출(공격자 토큰) = 건너뜀 — 미서명 예외는 네이티브·정품 목록만")
ATK = "0x" + "a7" * 20
T16 = T6 + 6 * DAY
FAKE[(ATK, 3299)] = (10 ** 30, T16 - 12)
H16 = h(161)
s16 = snap(H16, T16, 3300, X, ATK, toks=[(W, X, ATK, "ATK", 100 * E18)], data="0x12345678")
s16["internal"] = [{"from": X, "to": W, "value": str(10 ** 15), "success": True}]
feed(c, H16, s16)
ev16 = c.conn.execute("SELECT event FROM tx_class WHERE txhash=?", (H16,)).fetchone()
n16 = len(CALLS)
pump(c)
chk(ev16 and ev16[0] == "SWAP" and cand(c, ATK).get("st") == "skip" and not anchors(c, ATK) and len(CALLS) == n16,
    "N16 공격자 서명 SWAP 모양 + 공격자 토큰 유출 = 건너뜀 · 조회 0(종전 = 허위 앵커)", (ev16 and ev16[0], cand(c, ATK), anchors(c, ATK)))

print("[N20] (na443) 공격자가 가짜 '교환'으로 먼저 confirmed 로 만든 토큰 → 가짜 유출 = 여전히 건너뜀")
ATB, JNK = "0x" + "a8" * 20, "0x" + "a9" * 20
T20 = T6 + 6 * DAY + 3600
s20a = snap(h(201), T20, 3400, X, ATB, toks=[(X, W, ATB, "ATB", 100 * E18), (W, X, JNK, "JNK", 1)], data="0x12345678")
feed(c, h(201), s20a)
cf20 = c.conn.execute("SELECT confirmed FROM assets WHERE chain='eth' AND address=?", (ATB,)).fetchone()
FAKE[(ATB, 3409)] = (10 ** 30, T20 + 60)
s20b = snap(h(202), T20 + 72, 3410, X, ATB, toks=[(W, X, ATB, "ATB", 999 * E18)], data="0x12345678")
s20b["internal"] = [{"from": X, "to": W, "value": str(10 ** 15), "success": True}]
feed(c, h(202), s20b)
ev20 = c.conn.execute("SELECT event FROM tx_class WHERE txhash=?", (h(202),)).fetchone()
n20 = len(CALLS)
pump(c)
chk(cf20 and cf20[0] == 1 and ev20 and ev20[0] == "SWAP" and cand(c, ATB).get("st") == "skip" and not anchors(c, ATB) and len(CALLS) == n20,
    "N20 confirmed 로 만든 공격자 토큰의 미서명 '교환' 유출 = 건너뜀 · 조회 0(종전 = 허위 앵커)", (cf20 and cf20[0], ev20 and ev20[0], cand(c, ATB), anchors(c, ATB)))

print("[N21] (na446) 정품 목록 밖 토큰의 남이 서명한 교환(인텐트·permit) 유출 = 건너뜀 → 사용자가 정품 등록하면 다시 요청으로 기장")
TKU = "0x" + "aa" * 20
T21 = T20 + 3600
feed(c, h(211), snap(h(211), T21, 3500, W, X, toks=[(X, W, TKU, "TKU", 50 * E18)], fee=10 ** 15, data="0x12345678"))
FAKE[(TKU, 3519)] = (80 * E18, T21 + 228)
s21 = snap(h(212), T21 + 240, 3520, X, X, toks=[(W, X, TKU, "TKU", 80 * E18)], data="0x12345678")
s21["internal"] = [{"from": X, "to": W, "value": str(10 ** 15), "success": True}]
feed(c, h(212), s21)
n21 = len(CALLS)
pump(c)
chk(cand(c, TKU).get("st") == "skip" and not anchors(c, TKU) and total(c, TKU) == -30 * E18 and len(CALLS) == n21,
    "N21 정품 등록 전 = 건너뜀(음수 유지 · 조회 0)", (cand(c, TKU), anchors(c, TKU)))
import spamguard
spamguard.set_user_genuine("eth", TKU, "TKU", True)
common.atomic_write_json(os.path.join(common.STATE_DIR, discopen.REQ_NAME), {"cells": [{"chain": "eth", "wallet": W, "ca": TKU, "retry": True}], "by": "test"})
pump(c)
chk([int(a9[2]) for a9 in anchors(c, TKU)] == [30 * E18] and total(c, TKU) == 0, "N21 정품 등록 뒤 다시 요청(--retry) = 직전 블록 80 확인 → 앵커 30 · 원장 0", (anchors(c, TKU), cand(c, TKU)))

print("[N22] (na446 보안) 내가 서명한 거래의 부수 수령(클레임·멀티콜 에어드랍)으로 받은 공격자 토큰 → 남이 서명한 '교환' 유출 = 건너뜀")
ATC = "0x" + "ab" * 20
T22 = T21 + 3600
feed(c, h(221), snap(h(221), T22, 3600, W, X, toks=[(X, W, ATC, "ATC", 1)], fee=10 ** 15, data="0x12345678"))
FAKE[(ATC, 3619)] = (10 ** 30, T22 + 228)
s22 = snap(h(222), T22 + 240, 3620, X, X, toks=[(W, X, ATC, "ATC", 999 * E18)], data="0x12345678")
s22["internal"] = [{"from": X, "to": W, "value": str(10 ** 15), "success": True}]
feed(c, h(222), s22)
n22 = len(CALLS)
pump(c)
chk(cand(c, ATC).get("st") == "skip" and not anchors(c, ATC) and len(CALLS) == n22,
    "N22 부수 수령 이력만 있는 공격자 토큰의 미서명 '교환' 유출 = 건너뜀 · 조회 0(종전 = 허위 앵커)", (cand(c, ATC), anchors(c, ATC)))

print("[N17] (보안 na438 3) 0 이 돼 지워진 발견 앵커 — 관측은 남아 늦은 옛 거래를 여전히 표식")
TKS = "0x" + "d5" * 20
T17 = T6 + 7 * DAY
FAKE[(TKS, 2599)] = (40 * E18, T17 - 12)
feed(c, h(171), snap(h(171), T17, 2600, W, TKS, toks=[(W, X, TKS, "TKS", 40 * E18)], fee=10 ** 15))
pump(c)
sid17 = discopen.sid_of("eth", W, TKS, 2599)
RS = h(172)
rs_snap = snap(RS, T17 - 500, 2550, X, TKS, toks=[(X, W, TKS, "TKS", 40 * E18)])
c.conn.execute("INSERT INTO raw_txs (chain, txhash, block, blockhash, ts, snapshot, wallets, ingested_at) VALUES ('eth',?,?,?,?,?,?,?)",
               (RS, 2550, "0x" + "d" * 64, None, json.dumps(rs_snap), json.dumps([W]), NOW))
c.conn.commit()
b17 = c._tx_wallet_sums("eth", RS)
c.conn.execute("BEGIN")
c.apply("eth", RS, "", rs_snap)
c._anchor_absorb("eth", RS, b17)
c.conn.commit()
gone17 = c.conn.execute("SELECT count(*) FROM postings WHERE source_id=?", (sid17,)).fetchone()[0]
L17 = h(173)
feed(c, L17, snap(L17, T17 - 400, 2560, W, TKS, toks=[(W, X, TKS, "TKS", 5 * E18)], fee=10 ** 15))
chk(gone17 == 0 and discopen._meta(c.conn, f"ext_prewindow_tx:eth:{L17}") is not None,
    "N17 앵커 행이 0 으로 지워져도 관측(raw_observations)으로 찾아 늦은 옛 거래를 재구축 표식", (gone17, discopen._meta(c.conn, f"ext_prewindow_tx:eth:{L17}")))

print("[N18] (보안 na438 4) rebuild2 — 발견 관측은 'payload 잔고 − 블록 이하 재파생 합'으로 · 0 으로 지워진 앵커도 복원")
TKR = "0x" + "d6" * 20
T18 = T6 + 8 * DAY
R1 = h(181)
feed(c, R1, snap(R1, T18 - 300, 2450, X, TKR, toks=[(X, W, TKR, "TKR", 20 * E18)]))
FAKE[(TKR, 2499)] = (50 * E18, T18 - 12)
feed(c, h(182), snap(h(182), T18, 2500, W, TKR, toks=[(W, X, TKR, "TKR", 50 * E18)], fee=10 ** 15))
pump(c)
chk([int(a[2]) for a in anchors(c, TKR)] == [30 * E18], "N18 전제: 앵커 = 50 − 20 = 30", anchors(c, TKR))


def _mut18(m9):
    s9 = json.loads(m9.execute("SELECT snapshot FROM raw_txs WHERE chain='eth' AND txhash=?", (R1,)).fetchone()[0])
    s9["token_transfers"][0]["total"]["value"] = str(25 * E18)
    m9.execute("UPDATE raw_txs SET snapshot=? WHERE chain='eth' AND txhash=?", (json.dumps(s9), R1))


sc, rep = shadow_rebuild("c", _mut18)


def scell(ca):
    a9 = sc.conn.execute("SELECT asset_id FROM assets WHERE chain='eth' AND address=?", (ca,)).fetchone()[0]
    return sum(int(r[0]) for r in sc.conn.execute("SELECT qty_base FROM postings WHERE location=? AND asset_id=?", (f"wallet:eth:{W}", a9)))


ar18 = [tuple(r) for r in sc.conn.execute("SELECT qty_base FROM postings WHERE source_id=?", (discopen.sid_of("eth", W, TKR, 2499),))]
as18 = [tuple(r) for r in sc.conn.execute("SELECT qty_base, event_ts FROM postings WHERE source_id=?", (sid17,))]
chk(ar18 == [(str(25 * E18),)] and scell(TKR) == 0, "N18 재파생이 달라져도(+25) 앵커 = 관측 50 − 25 = 25 · 합 0 = 실잔고(종전 KnownIndex 역산 30 → 합 5)", (ar18, scell(TKR)))
chk(as18 == [(str(5 * E18), T17 - 12)] and scell(TKS) == 0, "N18 0 으로 지워진 발견 앵커 = 관측으로 복원 5(블록 이하 40 − 5 = 35 · 40 − 35) · 합 0", (as18, scell(TKS)))
sc.conn.close()

print("[N19] (보안 na438 5·7) 재점검 적용 — 상세 대기 있으면 'wait' 로 요청에 남김 · 풀리면 적용 · 처리 중 새 요청 합침")
TKW, TKV = "0x" + "d7" * 20, "0x" + "d8" * 20
PD = os.path.join(common.STATE_DIR, "pending_detail_eth.json")
common.atomic_write_json(PD, {h(999): {"w": W}})
RQ = os.path.join(common.STATE_DIR, discopen.RECHK_REQ_NAME)
common.atomic_write_json(RQ, {"items": [it(TKW, 4100, 9 * E18, 0, block_ts=T9 + 100)], "by": "test"})
pump(c)
pend19 = common.read_json(RQ + ".processing", {}) or {}
keys19 = [(x.get("ca"), x.get("block")) for x in pend19.get("items") or []]
chk(not anchors(c, TKW) and (TKW, 4100) in keys19 and not os.path.exists(RQ), "N19 상세 대기(pending_detail) = 기장 안 함 · 항목은 .processing 에 남음(종전 = 버림)", keys19)
common.atomic_write_json(RQ, {"items": [it(TKV, 4100, 3 * E18, 0, block_ts=T9 + 100)], "by": "test2"})
os.remove(PD)
pump(c)
pend19b = common.read_json(RQ + ".processing", {}) or {}
keys19b = [(x.get("ca"), x.get("block")) for x in pend19b.get("items") or []]
chk([int(a[2]) for a in anchors(c, TKW)] == [9 * E18] and [int(a[2]) for a in anchors(c, TKV)] == [3 * E18]
    and (TKW, 4100) not in keys19b and (TKV, 4100) not in keys19b and not os.path.exists(RQ),
    "N19 대기 풀림 → 남은 항목 적용 · 처리 중 들어온 새 요청도 합쳐 적용 · 끝난 항목은 .processing 에서 빠짐", (keys19b, anchors(c, TKW), anchors(c, TKV)))

print("[N11] 롤백(--ledger = 배포 직전 원장으로 교체)")
c.conn.close()
for sfx in ("", "-wal", "-shm"):
    if os.path.exists(common.DB_PATH + sfx):
        os.remove(common.DB_PATH + sfx)
_s = sqlite3.connect(PRE)
_d = sqlite3.connect(common.DB_PATH)
_s.backup(_d)
_s.close()
_d.close()
n11 = len(CALLS)
c = core.Core(common.load_config())
pump(c)
left = (c.conn.execute("SELECT count(*) FROM postings WHERE source_id LIKE 'recon:%:disc:%'").fetchone()[0],
        c.conn.execute("SELECT count(*) FROM raw_observations WHERE obs_id LIKE 'recon:%:disc:%'").fetchone()[0],
        c.conn.execute("SELECT count(*) FROM meta WHERE k LIKE 'negabs%'").fetchone()[0])
chk(left == (0, 0, 0) and len(CALLS) == n11, "N11 되돌린 원장 = 발견 시점 앵커·관측·후보 0 · 기동해도 조회·기장 없음(요청 없으면 무동작)", (left, CALLS[n11:]))
c.conn.close()
T.finish()
