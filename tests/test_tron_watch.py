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

import config, paths  # noqa: E402
import core  # noqa: E402
import bf_engine  # noqa: E402
import chain_registry as reg  # noqa: E402
import chain_state as cs  # noqa: E402
import chain_watch as cw  # noqa: E402
import chain_event as ce  # noqa: E402
import address_codec as ac  # noqa: E402
from inbox import SegmentWriter  # noqa: E402
import _tronfake as F  # noqa: E402
import tron_watch as TW  # noqa: E402

fake = F.FakeTron()
F.install_loop_open(bf_engine, T)
TW.TronAdapter.RATE_PAUSE = 0.05
bf_engine._POLICY_OVERRIDES["127.0.0.1"] = {"rate": 1000.0, "burst": 1000, "conc": 8}
A, B = N.OWN["tron"]
X = N.EXT["tron"]
C = "41" + "c1" * 20
DEX = "41" + "d1" * 20
USDT = "41a614f803b6fd780986a42c78ec9c7f77e6ded13c"
TK = N.TOK["tron"]
FAKE = "41" + "f1" * 20
NOMETA = "41" + "e2" * 20
NFT = "41" + "e1" * 20
ZD = "41" + "e3" * 20
fake.tokmeta = {USDT: ("USDT", 6), TK: ("TKA", 18), FAKE: ("USDT", 6), NOMETA: ("NOM", None), ZD: ("ZD", 0)}
NOW = int(time.time() * 1000)
DAY = 86400_000
SD = paths.STATE_DIR
INB = os.path.join(paths.INBOX_DIR, "tron")
CFG_PATH = os.path.join(T.TMP, "config.json")
cfg = json.load(open(CFG_PATH))
cfg["chain_wallets"] = [{"chain": "tron", "address": ac.tron_display(A)}]
cfg["nonevm"] = {"tron": {"api": fake.base, "rps": 1000, "retries": 1}}
json.dump(cfg, open(CFG_PATH, "w"))


def tid(n):
    return ("%02x" % n) * 32


def recs():
    out = []
    for f in sorted(os.listdir(INB)) if os.path.isdir(INB) else []:
        if f.endswith(".jsonl"):
            out += [json.loads(ln) for ln in open(os.path.join(INB, f)) if ln.strip()]
    return out


def uids():
    return [r["tx_uid"] for r in recs()]


def rec_of(n):
    rs = [r for r in recs() if r["tx_uid"] == tid(n)]
    return rs[-1] if rs else None


def reset_gates():
    with bf_engine._GATES_LOCK:
        bf_engine._GATES.clear()


reset_gates()


rows9, errs9 = reg.wallets({"chain_wallets": [{"chain": "tron", "address": ac.tron_display(A)}, {"chain": "tron", "address": A.upper().replace("0X", "")},
                                              {"chain": "tron", "address": "0x" + A[2:]},
                                              {"chain": "tron", "address": ac.tron_display(A)[:-1] + ("A" if ac.tron_display(A)[-1] != "A" else "B")}]},
                           "tron", with_errors=True)
check("TR1 Base58·hex 같은 지갑 = 1개 · EVM 0x·체크섬 오타 = 거부 2", len(rows9) == 1 and rows9[0]["key"] == A and len(errs9) == 2, (rows9, errs9))

fake.transfer(tid(1), NOW - 10 * DAY, X, A, 5_000_000)
fake.transfer(tid(2), NOW - 9 * DAY, A, X, 2_000_000, fee=1_100_000)
fake.call(tid(3), NOW - 8 * DAY, A, USDT, logs=[(USDT, A, X, 100_000_000)])
fake.call(tid(4), NOW - 7 * DAY, X, USDT, logs=[(USDT, X, A, 7_000_000), (USDT, X, A, 7_000_000)],
          raw_logs=[{"address": NFT[2:], "topics": [F.TRANSFER, F.pad(X), F.pad(A), "%064x" % 5], "data": ""},
                    {"address": USDT[2:], "topics": [F.APPROVAL, F.pad(A), F.pad(X)], "data": "%064x" % 999}])
fake.call(tid(5), NOW - 6 * DAY, A, DEX, call_value=10_000_000, logs=[(TK, DEX, A, 50 * 10 ** 18)], fee=3_000_000)
fake.call(tid(6), NOW - 5 * DAY, X, C, internals=[(C, A, 4_000_000, False), (C, A, 9_000_000, True)])
fake.call(tid(7), NOW - 4 * DAY, A, DEX, call_value=5_000_000, fee=2_000_000, ret="REVERT")
fake.system(tid(8), NOW - 3 * DAY, A, "FreezeBalanceV2Contract", {"frozen_balance": 3_000_000, "resource": "ENERGY"})
fake.system(tid(9), NOW - 2 * DAY, A, "WithdrawExpireUnfreezeContract", info_extra={"withdraw_expire_amount": 1_000_000})
fake.call(tid(10), NOW - 2 * DAY + 5000, X, FAKE, logs=[(FAKE, X, A, 1000_000_000)])
fake.call(tid(11), NOW - 2 * DAY + 8000, X, USDT, logs=[(USDT, A, X, 1)], list_value=0)
fake.trc10(tid(12), NOW - 1 * DAY, X, A, 1000)
fake.transfer(tid(13), NOW - 1 * DAY + 3000, A, B, 1_000_000)
fake.call(tid(14), NOW - 1 * DAY + 6000, X, NOMETA, logs=[(NOMETA, X, A, 77)])
fake.call(tid(16), NOW - 12 * DAY, A, C, call_value=1_000_000, internals=[(C, A, 3_000_000, False)],
          logs=[(USDT, C, A, 5_000_000)], fee=500_000)
fake.transfer(tid(17), NOW - 200 * DAY, X, A, 1_000_000)
fake.call(tid(22), NOW - 13 * DAY, X, ZD, logs=[(ZD, X, A, 9)])
fake.call(tid(20), NOW - 11 * DAY, X, TK, logs=[(TK, A, X, 3)])

st = cs.ChainState("tron")
ad = TW.make_adapter(config.load_config())
ad.state = st
w = SegmentWriter(INB)
col = cw.Collector(ad, w, st, {A}, page_budget={"latest": 5, "history": 50}, detail_budget={"latest": 50, "history": 500})
r1 = col.cycle()
p14 = st.d["pending"].get(tid(14)) or {}
check("TR10 자릿수 모르는 토큰(decimals 거부) 거래 = 보류(방출 안 함 · 대기 사유 · 동기화 도장 없음 — nvint18)",
      tid(14) not in uids() and "자릿수 미확인" in p14.get("why", "") and r1["left"] == 1 and not st.d.get("synced_at"), (r1, p14))
fake.tokmeta[NOMETA] = ("NOM", 4)
ad._meta_neg[NOMETA] = 0
p14["next"] = 0
r1 = col.cycle()
want = {tid(n) for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 13, 14, 16, 20, 22)}
got = set(uids())
check("TR11 창 안 15건 전부 방출 · 대기 0 · 동기화 도장", got == want and r1["left"] == 0 and st.d.get("synced_at"), (r1, sorted(got ^ want)))
check("TR9 값 0 오염(11)·남이 보낸 TRC-10(12)·창 밖(17) = 발견 안 함", not ({tid(11), tid(12), tid(17)} & got))
check("TR9 남이 보낸 TRC-10 = 범위 밖 기록(tron_scope · 숨기지 않음)",
      any(k.startswith("skip_in:TransferAssetContract") for k in (st.d.get("tron_scope") or {}).get(A, {})), st.d.get("tron_scope"))
check("TR3 같은 tx(16)가 세 목록에 다 나와도 레코드 1개", uids().count(tid(16)) == 1, uids().count(tid(16)))

bad = []
for r9 in recs():
    try:
        ce.validate(r9)
        ce.to_core(r9)
    except ce.ContractError as e:
        bad.append((r9["tx_uid"][:6], str(e)))
check("TR15 모든 레코드 계약 통과 · 수량 보존식", not bad, bad)


def dl(n, owner=A, asset=None):
    r9 = rec_of(n)
    return {(d["owner"], d["asset"].get("id")): int(d["delta_base"]) for d in r9["deltas"]}.get((owner, asset))


r16 = rec_of(16)
check("TR3 세 목록 tx(16) 수수료 1번 · TRX 순변화 −1 −0.5 +3 · USDT +5", dl(16) == 1_500_000 and dl(16, A, USDT) == 5_000_000
      and [f["amount_base"] for f in r16["fees"]] == ["500000"], r16["deltas"])
check("TR2 TRX 입금 +5(남이 수수료 — 내 수수료 레그 없음)", dl(1) == 5_000_000 and not rec_of(1)["fees"])
check("TR2·TR5 TRX 출금 −2 − 소각 수수료 1.1", dl(2) == -3_100_000 and rec_of(2)["fees"][0]["amount_base"] == "1100000")
check("TR5 에너지 충당(fee 0) = 수수료 레그 없음 · USDT −100", not rec_of(3)["fees"] and dl(3, A, USDT) == -100_000_000)
check("TR4 같은 금액 로그 2개 = +14 · TRC-721·Approval 무시", dl(4, A, USDT) == 14_000_000 and dl(4, A, NFT) is None and len(rec_of(4)["deltas"]) == 1,
      rec_of(4)["deltas"])
check("TR2 내부 TRX +4(거절된 9 무시)", dl(6) == 4_000_000)
r7 = rec_of(7)
check("TR5 실패 컨트랙트 = 수수료 −2 만(call_value 안 나감) · failed", dl(7) == -2_000_000 and r7["execution"]["state"] == "failed")
check("TR7 동결 = 유동 TRX −3 · hint stake · 잠금 정보", dl(8) == -3_000_000 and rec_of(8)["classification"]["hint"] == "stake"
      and rec_of(8)["tron"]["stake"]["op"] == "freeze")
check("TR7 만료 해제 출금 = +1 · hint stake", dl(9) == 1_000_000 and rec_of(9)["classification"]["hint"] == "stake")
check("TR8 교환처럼 보임(TRX 냄·토큰 받음) = hint unknown(검증한 스왑 아님)", rec_of(5)["classification"]["hint"] == "unknown"
      and dl(5) == -13_000_000 and dl(5, A, TK) == 50 * 10 ** 18)
check("TR8 내가 부른 컨트랙트에서 들어옴만 = hint program_in", r16["classification"]["hint"] == "program_in")
r10 = rec_of(10)
check("TR9 사칭 'USDT' = 수량 그대로 + spam 표식", dl(10, A, FAKE) == 1000_000_000 and (r10["classification"].get("spam") or {}).get("suspect")
      and "symbol_impersonation" in r10["classification"]["spam"]["why"], r10["classification"])
check("TR9 진짜 USDT 받음 = 표식 없음", "spam" not in rec_of(4)["classification"])
r20 = rec_of(20)
check("TR9 내가 서명 안 한 토큰 유출 = 수량 −3 그대로 + unsigned_outflow 표식", dl(20, A, TK) == -3 and "unsigned_outflow" in r20["classification"]["spam"]["why"])
a14 = [d["asset"] for d in rec_of(14)["deltas"]][0]
check("TR10 token_info 없는 토큰 = 상수 호출 symbol · 자릿수를 알게 된 뒤 방출(4 · 18 로 짐작 안 함)", a14.get("symbol") == "NOM" and a14.get("decimals") == 4, a14)
a22 = [d["asset"] for d in rec_of(22)["deltas"]][0]
check("TR10 자릿수 0 토큰 = 0(정상 · None·18 아님) · +9", a22.get("decimals") == 0 and dl(22, A, ZD) == 9, a22)
a4 = [d["asset"] for d in rec_of(4)["deltas"]][0]
check("TR10 목록 token_info 메타(USDT 6)", a4.get("symbol") == "USDT" and a4.get("decimals") == 6, a4)
check("TR11 순서 높이·시각 = 영수증 블록", rec_of(2)["order"]["height"] == fake.by_id[tid(2)]["blk"] and rec_of(2)["ts"] == (NOW - 9 * DAY) // 1000)

reg.FORCE_AVAILABLE.add("tron")
c = core.Core(config.load_config())
c.conn.commit()
rd = dict(c.chain_readers)["tron"]


def drain():
    row = c.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream='tron'").fetchone()
    c._drain_stream("tron", rd, *((row["seg"], row["off"]) if row else (1, 0)))
    c.conn.commit()


drain()
LA = reg.make_location("tron", A)


def wsum(loc=LA):
    out = {}
    for r in c.conn.execute("SELECT a.kind, a.address, p.qty_base FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.location=?", (loc,)):
        k = (r["kind"], r["address"])
        out[k] = out.get(k, 0) + int(r["qty_base"])
    return out


def ev(n):
    r9 = c.conn.execute("SELECT event FROM tx_class WHERE chain='tron' AND txhash=?", (tid(n),)).fetchone()
    return r9["event"] if r9 else None


ws = wsum()
exp_trx = 5_000_000 - 3_100_000 - 13_000_000 + 4_000_000 - 2_000_000 - 3_000_000 + 1_000_000 - 1_000_000 + 1_500_000
check("TR15 원장 TRX 합 = 순변화 합 · USDT −100+14+5 · TK +50e18 − 3", ws.get(("native", None)) == exp_trx and ws.get(("token", USDT)) == -81_000_000
      and ws.get(("token", TK)) == 50 * 10 ** 18 - 3, ws)
nat = c.conn.execute("SELECT decimals, symbol FROM assets WHERE chain='tron' AND kind='native'").fetchone()
check("TR15 TRX 자산 = 6자리", nat and nat["decimals"] == 6 and nat["symbol"] == "TRX", dict(nat) if nat else None)
evs = {n: ev(n) for n in (1, 2, 3, 5, 7, 8, 9, 16)}
check("TR2·5·7·8 분류: 입금 TRANSFER_IN · 출금 TRANSFER_OUT · 교환처럼 = UNKNOWN(SWAP 아님) · 실패 FAILED · 동결 TRANSFER_OUT · 해제 출금·청구 PROGRAM_IN",
      evs == {1: "TRANSFER_IN", 2: "TRANSFER_OUT", 3: "TRANSFER_OUT", 5: "UNKNOWN", 7: "FAILED", 8: "TRANSFER_OUT", 9: "PROGRAM_IN",
              16: "PROGRAM_IN"}, evs)
gas7 = sum(int(r[0]) for r in c.conn.execute("SELECT qty_base FROM postings WHERE source_id=? AND leg_kind='gas'", (tid(7),)))
check("TR5 실패 tx 수수료 = gas 레그 −2 TRX", gas7 == -2_000_000, gas7)
raw10 = json.loads(c.conn.execute("SELECT snapshot FROM raw_txs WHERE chain='tron' AND txhash=?", (tid(10),)).fetchone()[0])
check("TR9 스팸 의심도 원본 보존(raw_txs)", (raw10["classification"].get("spam") or {}).get("suspect") is True)

n0 = len(recs())
lists0 = len(fake.log)
col.cycle()
hist_calls = [p for (_m, p, _r, _h) in fake.log[lists0:] if "/v1/accounts/" in p and "max_timestamp" in p]
check("TR11 두 번째 주기 = 새 레코드 0 · 과거(history) 목록 호출 0", len(recs()) == n0 and not hist_calls, (len(recs()) - n0, hist_calls[:2]))
st2 = cs.ChainState("tron")
ad2 = TW.make_adapter(config.load_config())
ad2.state = st2
col2 = cw.Collector(ad2, w, st2, {A})
col2.cycle()
check("TR11 재시작(디스크 상태) = 다시 보내지 않음", len(recs()) == n0, len(recs()) - n0)
hs9 = st2.lane("history:" + A).get("safe") or {}
check("TR11 과거 회차 끝 표식(done·창 시작) · 지갑 상세 완료(대사 준비 재료)", hs9.get("done") is True and st2.owner_done(A), (hs9, st2.d["status"].get(A)))
fake.transfer(tid(15), NOW - 60_000, X, A, 500_000)
col2.cycle()
check("TR11 최신 새 거래(15) = 다음 주기에 방출", tid(15) in uids() and len(recs()) == n0 + 1)

fake.call(tid(18), int(time.time() * 1000) - 30_000, A, USDT, logs=[(USDT, A, X, 1_000_000)], fee=345_000)
fake.noinfo.add(tid(18))
st2.d.pop("synced_at", None)
col2.cycle()
check("TR6 영수증 지연 = 안 보냄 · 대기열에 남음 · 동기화 도장 없음", tid(18) not in uids() and tid(18) in st2.d["pending"] and not st2.d.get("synced_at"),
      st2.d["pending"].get(tid(18)))
fake.noinfo.discard(tid(18))
st2.d["pending"][tid(18)]["next"] = 0
col2.cycle()
r18 = rec_of(18)
check("TR6 영수증 온 뒤 = 정확한 수수료(0.345) · USDT −1", r18 and r18["fees"][0]["amount_base"] == "345000" and dl(18, A, USDT) == -1_000_000)

fake.transfer(tid(19), int(time.time() * 1000) - 20_000, X, A, 700_000)
n1 = len(recs())
for name, sub, status, body in (("429", "transactions?", 429, b"{}"),
                                ("'Error' 정지", "transactions?", 200, b'{"Error":"request rate exceeded the allowed_rps(1), and the query server is suspended for 5 s"}'),
                                ("잘린 본문", "transactions?", 200, b'{"data": [{"txID": "ab'),
                                ("success false", "transactions?", 200, b'{"success": false, "data": [], "meta": {}}'),
                                ("500", "transactions?", 500, b'{"x":1}')):
    reset_gates()
    ad2._pause_until = 0.0
    safe0 = (st2.lane("latest:" + A).get("safe") or {}).get("t")
    st2.d.pop("synced_at", None)
    fake.inject.append((sub, status, body))
    col2.cycle()
    safe1 = (st2.lane("latest:" + A).get("safe") or {}).get("t")
    check(f"TR12 {name} = 새 레코드 0 · 안전 경계 그대로 · 동기화 도장 없음", len(recs()) == n1 and safe0 == safe1 and not st2.d.get("synced_at"),
          (len(recs()) - n1, safe0, safe1))
reset_gates()
ad2._pause_until = 0.0
col2.cycle()
check("TR12 회복 뒤 빠짐 없음(19 방출)", tid(19) in uids())
fake.transfer(tid(21), int(time.time() * 1000) - 10_000, X, A, 800_000)
for sub, status, body in (("gettransactioninfobyid", 500, b"{}"), ("gettransactionbyid", 200, b'{"txID": "zz'),
                          ("gettransactioninfobyid", 200, b'{"Error": "busy"}')):
    reset_gates()
    fake.inject.append((sub, status, body))
    col2.cycle()
    check(f"TR12 상세 오류({sub} {status}) = 안 보냄 · 대기열에 남음", tid(21) not in uids() and tid(21) in st2.d["pending"])
    st2.d["pending"][tid(21)]["next"] = 0
reset_gates()
col2.cycle()
check("TR12 상세 회복 = 방출(+0.8)", dl(21) == 800_000)

drain()
check("TR2 B 등록 전 A→B = TRANSFER_OUT", ev(13) == "TRANSFER_OUT")
cfg = json.load(open(CFG_PATH))
cfg["chain_wallets"].append({"chain": "tron", "address": ac.tron_display(B)})
json.dump(cfg, open(CFG_PATH, "w"))
c.chain_owners["tron"] = {A, B}
st3 = cs.ChainState("tron")
ad3 = TW.make_adapter(config.load_config())
ad3.state = st3
col3 = cw.Collector(ad3, w, st3, {A, B}, detail_budget={"latest": 50, "history": 500})
col3.cycle()
r13 = rec_of(13)
check("TR2 B 의 과거 발견이 같은 tx 를 넓은 관점(A·B)으로 재방출", r13["owners"] == sorted([A, B]) and uids().count(tid(13)) == 2, r13["owners"])
drain()
lb = wsum(reg.make_location("tron", B))
check("TR2 core 교체 → TRANSFER_SELF · B +1 TRX 한 번", ev(13) == "TRANSFER_SELF" and lb.get(("native", None)) == 1_000_000, (ev(13), lb))

live = {(r["source_id"], r["leg_seq"], r["asset_id"], r["location"], r["qty_base"], r["leg_kind"], r["event"])
        for r in c.conn.execute("SELECT * FROM postings WHERE source_kind='chain_tx' AND source_ns='tron'")}
c.conn.execute("DELETE FROM postings WHERE source_kind='chain_tx'")
c.conn.execute("DELETE FROM positions")
c.conn.execute("DELETE FROM transfers")
c.conn.commit()
for r9 in c.conn.execute("SELECT chain, txhash, snapshot FROM raw_txs WHERE chain='tron' ORDER BY ingested_at, txhash").fetchall():
    c.conn.execute("BEGIN")
    c.apply(r9["chain"], r9["txhash"], "", json.loads(r9["snapshot"]))
    c.conn.commit()
again = {(r["source_id"], r["leg_seq"], r["asset_id"], r["location"], r["qty_base"], r["leg_kind"], r["event"])
         for r in c.conn.execute("SELECT * FROM postings WHERE source_kind='chain_tx' AND source_ns='tron'")}
check("TR16 재구축(원본 재생) = 라이브와 같은 레그(Tron 레코드 전부)", again == live and len(live) > 20, (len(live), sorted(live ^ again)[:4]))

wa0, wb0, n7 = wsum(), wsum(reg.make_location("tron", B)), len(recs())
for f9 in ("cursor_tron.json", "emitted_tron.json"):
    os.remove(os.path.join(SD, f9))
st7 = cs.ChainState("tron")
ad7 = TW.make_adapter(config.load_config())
ad7.state = st7
cw.Collector(ad7, w, st7, {A, B}, detail_budget={"latest": 100, "history": 500}).cycle()
drain()
check("TR17 상태 파일 없이 다시 = 다시 방출(창 처음부터) · 원장 합 그대로(A·B)", len(recs()) > n7 and wsum() == wa0
      and wsum(reg.make_location("tron", B)) == wb0, (len(recs()) - n7, wsum() == wa0))

cfg = json.load(open(CFG_PATH))
cfg["backfill_since"] = "2025-01-01"
json.dump(cfg, open(CFG_PATH, "w"))
time.sleep(0.01)
os.utime(CFG_PATH, None)
ad4 = TW.make_adapter(config.load_config())
ad4.state = st3
q4, _fp4 = ad4.discovery_query(A, "history")
check("TR11 창을 앞당기면 끝낸 구간 앞쪽만 다시(새 하한 · 상한 = 예전 창 시작 + 겹침)", not q4.get("done") and q4["lo"] < hs9["from"]
      and q4["hi"] == hs9["from"] + TW.OVERLAP_MS, (q4, hs9))

P = "41" + "55" * 20
base = NOW - 30 * DAY
for i in range(450):
    ts9 = base + (195 if 195 <= i < 206 else i) * 1000
    fake.call("%064x" % (0x10000 + i), ts9, X, USDT, logs=[(USDT, X, P, 1 + i)])
pa = TW.make_adapter(config.load_config())
q = {"lane": "latest", "lo": base - 1000, "hi": None, "limit": 200}


def walk(adp, qq, cap=40):
    seen, cur, n = [], None, 0
    while n < cap:
        n += 1
        try:
            its, cur = adp.discover_page(P, qq, cur)
        except cw.Transient:
            continue
        seen += [it["stable_id"] for it in its]
        if cur is None:
            break
    return seen, n


seen, n = walk(pa, q)
check("TR13 450건(쪽 200·200·50 + 같은 시각 동률이 쪽 경계에 걸침) 전부", len(set(seen)) == 450 and len(seen) == 450, (len(set(seen)), len(seen), n))
fake.bad_fp = {"200"}
seen, n = walk(pa, q, cap=80)
check("TR13 fingerprint 거절 반복 → 마지막 본 시각부터 다시(빠짐 0 · 중복은 멱등)", len(set(seen)) == 450, (len(set(seen)), n))
fake.bad_fp = set()
fake.no_fp = True
seen, n = walk(pa, q)
check("TR13 fingerprint 없는 꽉 찬 쪽 = 마지막 본 시각부터 이어감(빠짐 0)", len(set(seen)) == 450, (len(set(seen)), n))
fake.no_fp = False

KEY = "tk_synthetic_value_0123456789abcdef"
os.environ["TJ_TRONGRID_KEY"] = KEY
cfgk = config.load_config()
cfgk["nonevm"]["tron"]["daily_limit"] = 10
ak = TW.make_adapter(cfgk)
mark = len(fake.log)
okn = 0
err9 = ""
for _i in range(12):
    try:
        ak._head()
        okn += 1
    except cw.Transient as e:
        err9 = str(e)
        break
hdrs = [{k.lower(): v for k, v in h.items()} for (_m, _p, _r, h) in fake.log[mark:]]
check("TR14 키 = 헤더로만(TRON-PRO-API-KEY) · URL 에 없음", hdrs and all(h.get("tron-pro-api-key") == KEY for h in hdrs)
      and not any(KEY in p for (_m, p, _r, _h) in fake.log), len(hdrs))
check("TR14 하루 몫 = 공표 10 × 80% = 8콜 뒤 요청 안 보냄", okn == 8 and len(fake.log) - mark == 8 and "하루 몫" in err9, (okn, len(fake.log) - mark, err9))
del os.environ["TJ_TRONGRID_KEY"]
reset_gates()
fake.inject.append(("getblock", 403, b'{"msg": "forbidden"}'))
try:
    TW.make_adapter(cfgk)._head()
    e403 = ""
except cw.Transient as e:
    e403 = str(e)
check("TR12 403 = 일시 실패(Transient · 빈 결과 아님)", e403.startswith("TronGrid"), e403)
cfgt = config.load_config()
cfgt["nonevm"]["tron"]["timeout_sec"] = 0.3
fake.delay["getblock"] = 1.5
reset_gates()
t9 = time.time()
try:
    TW.make_adapter(cfgt)._head()
    eto = ""
except cw.Transient as e:
    eto = str(e)
fake.delay.clear()
check("TR12 시간 초과 = 일시 실패(제때 · 빈 결과 아님)", "timeout" in eto and time.time() - t9 < 1.4, (eto, round(time.time() - t9, 2)))

import pricing  # noqa: E402
import spamguard  # noqa: E402
aid_u = c.conn.execute("SELECT asset_id FROM assets WHERE chain='tron' AND address=?", (USDT,)).fetchone()[0]
aid_f = c.conn.execute("SELECT asset_id FROM assets WHERE chain='tron' AND address=?", (FAKE,)).fetchone()[0]
gname = c.conn.execute("SELECT g.name FROM assets a JOIN asset_groups g ON g.group_id=a.group_id WHERE a.asset_id=?", (aid_u,)).fetchone()
check("TR21 정식 Tron USDT = 검증 스테이블 · 정품 · 그룹 USDT(인스턴스 그룹 아님)", c.svc_price._is_stable_aid(aid_u) and spamguard.is_genuine("tron", USDT)
      and gname and gname[0] == "USDT", (c.svc_price._is_stable_aid(aid_u), spamguard.is_genuine("tron", USDT), gname and gname[0]))
check("TR21 사칭 'USDT'(다른 계약) = 스테이블·정품 아님", not c.svc_price._is_stable_aid(aid_f) and not spamguard.is_genuine("tron", FAKE))

class _Clock:
    def __init__(self, real):
        self.r, self.off = real, 0.0

    def time(self):
        return self.r.time() + self.off

    def monotonic(self):
        return self.r.monotonic()

    def sleep(self, x):
        return self.r.sleep(x)


cfg = json.load(open(CFG_PATH))
cfg.pop("backfill_since", None)
json.dump(cfg, open(CFG_PATH, "w"))
os.utime(CFG_PATH, (time.time() + 5, time.time() + 5))
P2 = "41" + "66" * 20
for i in range(450):
    fake.transfer("%064x" % (0x20000 + i), NOW - 40 * DAY + i * 60_000, X, P2, 1_000 + i)
SD18 = os.path.join(T.TMP, "st18")
os.makedirs(SD18, exist_ok=True)
st18 = cs.ChainState("tron", SD18)
ad18 = TW.make_adapter(config.load_config())
ad18.state = st18
clk = _Clock(time)
real_time = TW.time
TW.time = clk
try:
    col18 = cw.Collector(ad18, SegmentWriter(os.path.join(SD18, "inbox")), st18, {P2}, page_budget={"latest": 5, "history": 1},
                         detail_budget={"latest": 0, "history": 0})
    for _i in range(10):
        col18.cycle()
        clk.off += 60.0
        if (st18.lane("history:" + P2).get("safe") or {}).get("done"):
            break
finally:
    TW.time = real_time
hs18 = st18.lane("history:" + P2).get("safe") or {}
check("TR18 과거 회차가 주기마다 1쪽씩(450건 = 3쪽 + 빈 목록 2쪽) — 창 하한이 움직여도 끝까지 · 450건 전부 대기열", hs18.get("done") is True
      and len(st18.d["pending"]) == 450, (hs18, len(st18.d["pending"])))

os.environ["TJ_TRONGRID_KEY"] = KEY
cfg19 = json.load(open(CFG_PATH))
cfg19["nonevm"]["tron"].pop("retries", None)
cfg19["nonevm"]["tron"]["daily_limit"] = 1000
reset_gates()
a19 = TW.make_adapter(cfg19)
a19.meter = bf_engine.DayMeter("rpc_day_trongrid_t19", a19.day_budget, burst=1.0, keep=0.0)
fake.inject.append(("getblock", 500, b'{"x": 1}'))
m19 = len(fake.log)
u0 = a19.meter.used()[0]
try:
    a19._head()
    r19 = "결과"
except cw.Transient:
    r19 = "예외"
check("TR19 500 한 번 = 일시 실패(다음 주기에 다시) · 실제 요청 1 = 장부 1(내부 재시도가 장부·간격 검사를 우회하지 않음)",
      r19 == "예외" and len(fake.log) - m19 == 1 and a19.meter.used()[0] - u0 == 1, (r19, len(fake.log) - m19, a19.meter.used()[0] - u0))

cfg20 = json.load(open(CFG_PATH))
cfg20["nonevm"]["tron"]["daily_limit"] = 25
a20 = TW.make_adapter(cfg20)
a20.meter = bf_engine.DayMeter("rpc_day_trongrid_t20", a20.day_budget, burst=1.0, keep=0.0)
nh = 0
for _i in range(30):
    try:
        a20._call("/walletsolidity/getblock", {"detail": False}, kind="history")
        nh += 1
    except cw.Transient:
        break
nl = 0
for _i in range(30):
    try:
        a20._call("/walletsolidity/getblock", {"detail": False}, kind="latest")
        nl += 1
    except cw.Transient:
        break
check("TR20 과거가 먼저 다 써도 최신 몫이 남음(과거 ≤ 장부 − 최신 몫 · 최신은 장부 끝까지)", 0 < nh < a20.day_budget and nl == a20.day_budget - nh and nl >= 1,
      (nh, nl, a20.day_budget))
kinds = []
a20.meter = None
o_call = a20._call
a20._call = lambda path, payload=None, params=None, kind="head": (kinds.append(kind), o_call(path, payload, params, kind="latest"))[1]
a20.meta.clear()
a20.fetch_and_normalize({"stable_id": tid(14), "owner": A, "lane": "history"}, {A})
del a20._call
check("TR20 과거 상세·토큰 메타 호출 = 과거 몫(history)으로 셈", kinds and all(k == "history" for k in kinds), kinds)
del os.environ["TJ_TRONGRID_KEY"]

fake.close()
reg.FORCE_AVAILABLE.clear()
T.finish()
