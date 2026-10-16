#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _ingest
from _ingest import check, Reader
import _nonevm as N

import json
import os
import time

import common
import core
import chain_event as ce
import chain_registry as reg
import address_codec as ac
from inbox import SegmentWriter

NOW = int(time.time())
DAY = 86400
A, B = N.OWN["tron"]
X = N.EXT["tron"]
EXA = "41" + "e1" * 20
CFG_PATH = os.path.join(T.TMP, "config.json")
base_cfg = json.load(open(CFG_PATH))

c0 = core.Core(common.load_config())
c0.conn.commit()
check("K0 새 체인 지갑 없음 = 새 스트림 0", c0.chain_readers == [] and c0.chain_owners == {}, c0.chain_readers)
check("K0 새 인박스 폴더 안 만듦", not any(os.path.isdir(os.path.join(common.INBOX_DIR, x)) for x in reg.CHAINS),
      os.listdir(common.INBOX_DIR))
c0.conn.close()


def write_cfg(chain_wallets, ex=None):
    cfg = dict(base_cfg, chain_wallets=chain_wallets)
    if ex:
        cfg["exchange_addresses"] = ex
    json.dump(cfg, open(CFG_PATH, "w"))


write_cfg([{"chain": "tron", "address": ac.tron_display(A), "label": "ta"}, {"chain": "ton", "address": "0:" + "31" * 32},
           {"chain": "sui", "address": N.OWN["sui"][0]}],
          ex=[{"exchange": "upbit", "chain": "tron", "address": ac.tron_display(EXA)}])
c = core.Core(common.load_config())
c.conn.commit()
check("K0 지갑 있으면 그 체인 스트림만", [x for x, _r in c.chain_readers] == ["sui", "ton", "tron"] and c.chain_owners["tron"] == {A},
      c.chain_readers)


def feed(rec, stream="tron"):
    return c._drain_stream(stream, Reader([json.loads(json.dumps(rec))]), 0, 0)


def legs(uid, chain="tron"):
    return sorted((r["leg_kind"], r["qty_base"], r["location"], r["event"]) for r in c.conn.execute(
        "SELECT leg_kind, qty_base, location, event FROM postings WHERE source_kind='chain_tx' AND source_ns=? AND source_id=?", (chain, uid)))


def ev(uid, chain="tron"):
    r = c.conn.execute("SELECT event FROM tx_class WHERE chain=? AND txhash=?", (chain, uid)).fetchone()
    return r["event"] if r else None


def wsum(chain, loc_like="wallet:%"):
    return {(r["location"], r["asset_id"]): int(r["s"]) for r in c.conn.execute(
        "SELECT location, asset_id, SUM(CAST(qty_base AS INTEGER)) AS s FROM postings WHERE source_ns=? AND location LIKE ? GROUP BY location, asset_id",
        (chain, loc_like))}


def poison_n():
    p = os.path.join(common.STATE_DIR, "poison.jsonl")
    return sum(1 for _ in open(p)) if os.path.exists(p) else 0


U1 = "a1" * 32
feed(N.rec("tron", U1, NOW - 10 * DAY, [(A, "native", -1_001_000)], fees=[(A, 1_000)], moves=[("native", A, X, 1_000_000)]))
L1 = legs(U1)
LA = reg.make_location("tron", A)
check("K1 TRANSFER_OUT", ev(U1) == "TRANSFER_OUT", ev(U1))
check("K1 레그 = 보냄 −1 TRX · 목적지 out:tron:<받는 이> · 가스 −0.001",
      L1 == sorted([("move_out", "-1000000", LA, "TRANSFER_OUT"), ("move_in", "1000000", f"out:tron:{X}", "TRANSFER_OUT"),
                    ("gas", "-1000", LA, "TRANSFER_OUT")]), L1)
nat = c.conn.execute("SELECT asset_id, decimals, symbol FROM assets WHERE chain='tron' AND kind='native'").fetchone()
check("K1 네이티브 TRX 자릿수 6(18 아님)", nat["decimals"] == 6 and nat["symbol"] == "TRX", dict(nat))
check("K1 지갑 칸 합 = 순변화 −1.001 TRX", wsum("tron") == {(LA, nat["asset_id"]): -1_001_000}, wsum("tron"))
pos = c.conn.execute("SELECT qty_norm FROM positions WHERE location=?", (LA,)).fetchone()
check("K1 포지션 캐시 = −1.001", pos and abs(float(pos["qty_norm"]) + 1.001) < 1e-12, pos and pos["qty_norm"])

n0 = c.conn.execute("SELECT COUNT(*) FROM postings").fetchone()[0]
feed(N.rec("tron", U1, NOW - 10 * DAY, [(A, "native", -1_001_000)], fees=[(A, 1_000)], moves=[("native", A, X, 1_000_000)]))
check("K2 같은 레코드 두 번 = 원장 무변", c.conn.execute("SELECT COUNT(*) FROM postings").fetchone()[0] == n0 and legs(U1) == L1)
p0 = poison_n()
bad = N.rec("tron", "a2" * 32, NOW, [(A, "native", -5)])
bad["deltas"][0]["delta_base"] = "-5.5"
feed(bad)
check("K2 계약 위반 = 격리(poison) · 원장 없음", poison_n() == p0 + 1 and ev("a2" * 32) is None)
feed(N.rec("tron", U1, NOW - 10 * DAY, [(A, "native", -2_001_000)], fees=[(A, 1_000)]))
check("K2 모순 재방출 = 격리 · 저장본 그대로", poison_n() == p0 + 2 and legs(U1) == L1)

U3 = "a3" * 32
LB = reg.make_location("tron", B)
feed(N.rec("tron", U3, NOW - 9 * DAY, [(A, "native", -5_001_000)], fees=[(A, 1_000)], owners=[A], moves=[("native", A, B, 5_000_000)]))
check("K3 B 미등록 = 보낸 내역(TRANSFER_OUT → out:tron:B)", ev(U3) == "TRANSFER_OUT" and ("move_in", "5000000", f"out:tron:{B}", "TRANSFER_OUT") in legs(U3))
c.chain_owners["tron"].add(B)
feed(N.rec("tron", U3, NOW - 9 * DAY, [(A, "native", -5_001_000), (B, "native", 5_000_000)], fees=[(A, 1_000)], owners=[A, B],
           moves=[("native", A, B, 5_000_000)]))
L3 = legs(U3)
check("K3 B 등록 뒤 재방출 = TRANSFER_SELF 로 교체 · out: 칸 없음",
      ev(U3) == "TRANSFER_SELF" and not any(x[2].startswith("out:") for x in L3), L3)
check("K3 수량 = A −5.001 · B +5 (중복 없음)", sum(int(q) for k, q, l9, _e in L3 if l9 == LA) == -5_001_000
      and sum(int(q) for k, q, l9, _e in L3 if l9 == LB) == 5_000_000, L3)
feed(N.rec("tron", U3, NOW - 9 * DAY, [(A, "native", -5_001_000)], fees=[(A, 1_000)], owners=[A]))
check("K3 옛 관점(줄어든) 재방출 = 무시", legs(U3) == L3)

U4, U4b = "a4" * 32, "a5" * 32
feed(N.rec("tron", U4, NOW - 8 * DAY, [(A, "native", -300)], fees=[(A, 300)], failed=True))
check("K4 실패 · 수수료만 = FAILED · 가스 레그만", ev(U4) == "FAILED" and legs(U4) == [("gas", "-300", LA, "FAILED")], legs(U4))
feed(N.rec("tron", U4b, NOW - 8 * DAY, [(A, "native", -1300), (A, ("token", N.TOK["tron"], "TKA", 6), 7)], fees=[(A, 300)], failed=True))
check("K4 실패인데 잔고 변화 = UNKNOWN(수량 보존 · 0 으로 지우지 않음)", ev(U4b) == "UNKNOWN" and
      sorted(x[0] for x in legs(U4b)) == ["acq", "disp", "gas"], legs(U4b))

U5, U6 = "a6" * 32, "a7" * 32
TKA = ("token", N.TOK["tron"], "TKA", 6)
feed(N.rec("tron", U5, NOW - 7 * DAY, [(A, "native", -2_000_100), (A, TKA, 50)], fees=[(A, 100)], hint="swap", trusted=False))
check("K5 검증 안 된 스왑 힌트 = UNKNOWN", ev(U5) == "UNKNOWN", ev(U5))
c._leg_px = lambda aid, ts: 0.5
c.px.fx_at = lambda *a, **k: 1400.0
c._price_tx("tron", U5)
nn = c.conn.execute("SELECT COUNT(*) FROM postings WHERE source_id=? AND leg_kind IN ('disp','acq') AND cost_usd IS NOT NULL", (U5,)).fetchone()[0]
check("K5 UNKNOWN 교환 레그 시세 없음(가격 없는 교환 = 원가 넘기기 · 실현 확정 없음)", nn == 0, nn)
feed(N.rec("tron", U6, NOW - 7 * DAY, [(A, "native", -2_000_100), (A, TKA, 50)], fees=[(A, 100)], hint="swap", trusted=True,
           trace_complete=False))
check("K5 trace 미완 스왑 = UNKNOWN", ev(U6) == "UNKNOWN")
U6b = "a8" * 32
feed(N.rec("tron", U6b, NOW - 7 * DAY, [(A, "native", -2_000_100), (A, TKA, 50)], fees=[(A, 100)], hint="swap", trusted=True))
check("K5 수집기가 검증한 스왑만 SWAP", ev(U6b) == "SWAP", ev(U6b))

S1 = N.OWN["sui"][0]
LS = reg.make_location("sui", S1)
feed(N.rec("sui", "Rb1", NOW - 6 * DAY, [(S1, "native", 5)], fees=[(S1, -5)]), stream="sui")
check("K6 Sui 환급 = 같은 지갑 +5(acq) · 이벤트 NOOP", ev("Rb1", "sui") == "NOOP" and legs("Rb1", "sui") == [("acq", "5", LS, "NOOP")],
      legs("Rb1", "sui"))
suin = c.conn.execute("SELECT decimals FROM assets WHERE chain='sui' AND kind='native'").fetchone()[0]
check("K6 SUI 자릿수 9", suin == 9)
feed(N.rec("sui", "Sp1", NOW - 6 * DAY, [(S1, ("token", N.TOK["sui"], "COINA", 6), -9)], fees=[("external", 77)], owners=[S1],
           moves=[(("token", N.TOK["sui"], "COINA", 6), S1, N.EXT["sui"], 9)]), stream="sui")
check("K6 스폰서 수수료 = 내 가스 레그 없음", not any(x[0] == "gas" for x in legs("Sp1", "sui")) and ev("Sp1", "sui") == "TRANSFER_OUT",
      legs("Sp1", "sui"))
mt = c.conn.execute("SELECT address FROM assets WHERE chain='sui' AND kind='token'").fetchone()[0]
check("K6 Sui 토큰 키 = 'mv_…'(Move 타입 이름 대소문자 보존 · 원장 lower() 안전)", ac.sui_asset_type(mt).endswith("::coin_a::COINA"), mt)

TO = N.OWN["ton"][0]
feed(N.rec("ton", TO + ".100.ab", NOW - 5 * DAY, [(TO, "native", 3_000_000_000)], hint="transfer", height=None), stream="ton")
lt = legs(TO + ".100.ab", "ton")
check("K7 TON 유입 = TRANSFER_IN · 위치 'wallet:ton:0_…' 콜론 2개", ev(TO + ".100.ab", "ton") == "TRANSFER_IN"
      and lt[0][2] == "wallet:ton:" + TO and lt[0][2].count(":") == 2, lt)
check("K7 거래소 입금 주소(config Base58) = 원장 키로 저장", c.conn.execute(
    "SELECT 1 FROM exchange_addresses WHERE chain='tron' AND address=?", (EXA,)).fetchone() is not None)
U7 = "a9" * 32
feed(N.rec("tron", U7, NOW - 5 * DAY, [(A, "native", -7_000_500)], fees=[(A, 500)], moves=[("native", A, ac.tron_display(EXA), 7_000_000)]))
check("K7 거래소로 보냄 = TRANSFER_OUT_EX · 이동 중 기록", ev(U7) == "TRANSFER_OUT_EX" and c.conn.execute(
    "SELECT dst FROM transfers WHERE chain_txhash=?", (U7,)).fetchone()["dst"] == "exchange:upbit")
c.conn.commit()

live = {(r["source_ns"], r["source_id"], r["leg_seq"], r["asset_id"], r["location"], r["qty_base"], r["leg_kind"], r["event"])
        for r in c.conn.execute("SELECT * FROM postings WHERE source_kind='chain_tx'")}
c.conn.execute("DELETE FROM postings WHERE source_kind='chain_tx'")
c.conn.execute("DELETE FROM positions")
c.conn.execute("DELETE FROM transfers")
c.conn.commit()
for r in c.conn.execute("SELECT chain, txhash, snapshot FROM raw_txs ORDER BY ingested_at, chain, txhash").fetchall():
    s9 = json.loads(r["snapshot"])
    c.conn.execute("BEGIN")
    if r["chain"] == "sol" and s9.get("kind") == "sol_tx":
        c.apply_sol(s9)
    else:
        c.apply(r["chain"], r["txhash"], "", s9)
    c.conn.commit()
again = {(r["source_ns"], r["source_id"], r["leg_seq"], r["asset_id"], r["location"], r["qty_base"], r["leg_kind"], r["event"])
         for r in c.conn.execute("SELECT * FROM postings WHERE source_kind='chain_tx'")}
check("K8 재구축(원본 재생) = 라이브와 같은 레그", again == live, sorted(live ^ again)[:6])
c.conn.execute("BEGIN")
evr = c._rederive_tx("tron", U3)
c.conn.commit()
check("K8 _rederive_tx(새 체인) = 같은 결과", evr == "TRANSFER_SELF" and legs(U3) == L3, (evr, legs(U3)))

wr9 = SegmentWriter(os.path.join(common.INBOX_DIR, "tron"))
U9 = "b1" * 32
wr9.append(N.rec("tron", U9, NOW - DAY, [(A, "native", 4_000_000)]))
seg, off, got = c._drain_stream("tron", dict(c.chain_readers)["tron"], 1, 0)
check("K9 state/inbox/tron 레코드 소비 · 오프셋 'tron'", got == 1 and ev(U9) == "TRANSFER_IN" and c.conn.execute(
    "SELECT off FROM inbox_offsets WHERE stream='tron'").fetchone()["off"] == off, (got, ev(U9)))
write_cfg([])
c2 = core.Core(common.load_config())
c2.conn.commit()
check("K9 지갑을 빼도 이미 쓰인 인박스 스트림은 유지(유실 방지)", "tron" in [x for x, _r in c2.chain_readers], c2.chain_readers)
check("K9 대사 펜스(미소비 체인 목록)에 새 스트림 포함", c2._recon_pending_chains() is not None)

check("K10 새 원본 시각(_tx_hist_ts) = 레코드 ts", c._tx_hist_ts("tron", U9) == NOW - DAY)
c.conn.execute("DELETE FROM postings WHERE source_id=?", (U4,))
check("K10 레그 없는 tx 도 저장 원본 ts 로", c._tx_hist_ts("tron", U4) == NOW - 8 * DAY, c._tx_hist_ts("tron", U4))
c.conn.rollback()

TKN = "41" + "e7" * 20
U11 = "c1" * 32
pz0 = poison_n()
feed(N.rec("tron", U11, NOW - 3 * DAY, [(A, ("token", TKN, "NOM", None), 77)]))
check("K11 자릿수 None 토큰 = 기장 안 함(레그·자산·원본 0) · 격리(원본 보존)", not legs(U11) and ev(U11) is None and poison_n() == pz0 + 1
      and c.conn.execute("SELECT COUNT(*) FROM assets WHERE chain='tron' AND address=?", (TKN,)).fetchone()[0] == 0
      and c.conn.execute("SELECT COUNT(*) FROM raw_txs WHERE chain='tron' AND txhash=?", (U11,)).fetchone()[0] == 0, (legs(U11), poison_n() - pz0))
feed(N.rec("tron", "c2" * 32, NOW - 3 * DAY, [(A, ("token", TKN, "NOM", 4), 50)]))
feed(N.rec("tron", U11, NOW - 3 * DAY, [(A, ("token", TKN, "NOM", None), 77)]))
d11 = c.conn.execute("SELECT decimals FROM assets WHERE chain='tron' AND address=?", (TKN,)).fetchone()
check("K11 원장이 이미 자릿수를 알면(4) 자릿수 없는 레코드도 그 자릿수로 기장", d11 and d11["decimals"] == 4 and ev(U11) == "TRANSFER_IN"
      and wsum("tron").get((LA, c.asset_id("token", "tron", TKN))) == 127, (dict(d11) if d11 else None, ev(U11)))
TK0 = "41" + "e8" * 20
feed(N.rec("tron", "c3" * 32, NOW - 3 * DAY, [(A, ("token", TK0, "ZD", 0), 9)]))
check("K11 자릿수 0 토큰 = 정상 기장(None 과 다름)", ev("c3" * 32) == "TRANSFER_IN")
def _k11_src():
    if not os.path.exists(os.path.join(T.SRC, "core_post.py")):
        return open(os.path.join(T.SRC, "core.py"), encoding="utf-8").read().split("def apply_chain_delta")[0]
    parts = [open(os.path.join(T.SRC, f9), encoding="utf-8").read()
             for f9 in ("core.py", "core_common.py", "core_dec.py", "core_classify.py", "core_outflow.py", "core_lp.py")]
    parts.append(open(os.path.join(T.SRC, "core_post.py"), encoding="utf-8").read().split("def apply_chain_delta")[0])
    return "\n".join(parts)


check("K11 EVM 원본 기장 경로는 이 검사와 무관(apply_chain_delta 안에서만)", "자릿수 미확인" not in _k11_src())
T.finish()
