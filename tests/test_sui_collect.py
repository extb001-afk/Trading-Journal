#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
from _ingest import check  # noqa: E402
import _nonevm as N  # noqa: E402
import _suifake as F  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

import config, paths  # noqa: E402
import core  # noqa: E402
import chain_event  # noqa: E402
import chain_registry as reg  # noqa: E402
import chain_state as cs  # noqa: E402
import address_codec as ac  # noqa: E402
from inbox import SegmentWriter  # noqa: E402
try:
    import sui_watch as SW  # noqa: E402
except ImportError:
    import _wip_sui_watch as SW  # noqa: E402

DAY = 86400
A, B = N.OWN["sui"]
X = N.EXT["sui"]
Y = "0x" + "98" * 32
SUI = F.SUI_T
USDC = "0x" + "a1" * 32 + "::usdc::USDC"
FAKE = "0x" + "b2" * 32 + "::usdc::USDC"
COINA = "0x" + "c3" * 32 + "::coin_a::COINA"
COINa = "0x" + "c3" * 32 + "::coin_a::coina"
E9 = 10 ** 9
G = (1000, 2000, 500)
FEE = 2500

ch = F.Chain()
ch.page_cap = 3
ch.bc_cap = 2
ch.meta = {USDC: ("USDC", 6), FAKE: ("USDC", 6), COINA: ("COINA", 0), COINa: ("coina", 3)}
srv, URL = F.start(ch)
TIP = ch.tip


def ck_days(d):
    return TIP - int(d * DAY)


TX = {}
TX["old"] = ch.add(ck_days(200), [(X, SUI, -E9 - FEE), (A, SUI, E9)], sender=X)
TX["in"] = ch.add(ck_days(100), [(X, SUI, -5 * E9 - FEE), (A, SUI, 5 * E9)], sender=X)
TX["out"] = ch.add(ck_days(90), [(A, SUI, -E9 - FEE), (X, SUI, E9)], sender=A)
TX["tok_in"] = ch.add(ck_days(80), [(X, SUI, -FEE), (X, USDC, -10_000_000), (A, USDC, 10_000_000)], sender=X)
TX["swap"] = ch.add(ck_days(70), [(A, SUI, -2 * E9 - FEE), (A, USDC, 3_000_000)], sender=A)
TX["fail"] = ch.add(ck_days(60), [(A, SUI, -FEE)], sender=A, status="FAILURE")
TX["rebate"] = ch.add(ck_days(50), [(A, SUI, 5000)], sender=A, gas=(1000, 0, 6000))
TX["sponsored"] = ch.add(ck_days(40), [(X, SUI, -FEE), (A, USDC, -2_000_000), (Y, USDC, 2_000_000)], sender=A, sponsor=X)
TX["i_sponsor"] = ch.add(ck_days(30), [(A, SUI, -FEE), (Y, COINA, -1), (X, COINA, 1)], sender=Y, sponsor=A)
TX["merge"] = ch.add(ck_days(20), [(A, SUI, -FEE)], sender=A)
TX["convert"] = ch.add(ck_days(15), [(A, SUI, -FEE), (A, USDC, -100), (A, USDC, 100)], sender=A)
TX["types"] = ch.add(ck_days(10), [(X, SUI, -FEE), (X, COINA, -7), (A, COINA, 7), (X, COINa, -9), (A, COINa, 9),
                                   (X, FAKE, -4_000_000), (A, FAKE, 4_000_000)], sender=X)

CFG_PATH = os.path.join(T.TMP, "config.json")
cfg = json.load(open(CFG_PATH))
cfg["chain_wallets"] = [{"chain": "sui", "address": A}]
cfg["nonevm"] = {"sui": {"graphql_url": URL, "retries": 1}}
json.dump(cfg, open(CFG_PATH, "w"))
cfg = config.load_config()
INB = os.path.join(paths.INBOX_DIR, "sui")
w = SegmentWriter(INB)
PB = {"latest": 5, "history": 20}
DB = {"latest": 100, "history": 500}


class Crash(Exception):
    pass


def inbox():
    out = []
    for f in sorted(os.listdir(INB)) if os.path.isdir(INB) else []:
        if f.endswith(".jsonl"):
            out += [json.loads(ln) for ln in open(os.path.join(INB, f)) if ln.strip()]
    return out


def uids():
    return [r["tx_uid"] for r in inbox()]


def col_for(owners=(A,), ad=None, st=None):
    return SW.SuiCollector(ad or SW.make_adapter(cfg), w, st or cs.ChainState("sui"), set(owners), page_budget=dict(PB), detail_budget=dict(DB))


def calls(op=None):
    return [c for c in ch.calls if op is None or c[0] == op]


st = cs.ChainState("sui")
col = col_for(st=st)
st.save_cursor = lambda *a, **k: (_ for _ in ()).throw(Crash())
try:
    col.discover("history")
except Crash:
    pass
st2 = cs.ChainState("sui")
check("U6a 죽기 전 첫 쪽 대기열은 디스크에 · history 커서는 그대로(미전진) · 안전 경계 = 시작 경계",
      len(st2.d["pending"]) == 3 and not st2.lane("history:" + A).get("cursor") and st2.lane("history:" + A)["safe"]["upper"] == TIP
      and st2.lane("latest:" + A)["safe"] == {"ck": TIP}, (list(st2.d["pending"]), st2.lane("history:" + A)))

col = col_for(st=st2)
r = col.cycle()
got = uids()
want = [TX[k] for k in TX if k != "old"]
check("U5 창 안 11건 전부 방출(바깥 쪽 3개씩 · 안쪽 2개씩 끝까지) · 창 밖(200일 전) 안 보냄 · 대기 0 · 동기화 도장",
      sorted(got) == sorted(want) and TX["old"] not in got and r["left"] == 0 and st2.d.get("synced_at"), (r, len(got)))
hs = st2.lane("history:" + A)["safe"]
check("U5 history 끝(done) · lo = 받은 가장 옛 체크포인트 · t0 = 5개월 창", hs.get("done") is True and hs.get("lo") == ck_days(100)
      and abs(hs["t0"] - (int(time.time()) - 150 * DAY)) < 120, hs)
check("U5 안쪽 balanceChanges 다음 쪽 조회가 실제로 있었음(2개씩)", len(calls("SuiTxBc")) >= 5, len(calls("SuiTxBc")))
recs = {r["tx_uid"]: r for r in inbox()}
okc = True
for r9 in recs.values():
    try:
        chain_event.to_core(r9)
    except chain_event.ContractError as e:
        okc = False
        print("contract", r9["tx_uid"], e)
check("U1 모든 레코드 계약·보존식 통과(경제 레그 − 수수료 = 순변화)", okc)
ro = recs[TX["out"]]
check("U1 보낸 거래: SUI 순변화 −1,000,002,500 · 가스 2,500(내 지갑) · 상대 X · 힌트 transfer · 체크포인트 순서축",
      ro["deltas"] == [{"owner": A, "asset": {"kind": "native", "symbol": "SUI", "decimals": 9}, "delta_base": str(-E9 - FEE)}]
      and ro["fees"][0]["payer"] == A and ro["fees"][0]["amount_base"] == "2500" and ro["classification"]["hint"] == "transfer"
      and ro["order"]["checkpoint"] == ck_days(90) and any(m["to"] == X for m in ro["movements"]), ro)
rt = recs[TX["tok_in"]]
check("U1 토큰 받음: 코인 타입 전체 · 자릿수 6(coinMetadata) · 가스 없음(남이 냄)",
      rt["deltas"] == [{"owner": A, "asset": {"kind": "token", "id": USDC, "symbol": "USDC", "decimals": 6}, "delta_base": "10000000"}]
      and rt["fees"] == [], rt["deltas"])
rs = recs[TX["sponsored"]]
check("U2 남이 스폰서: payer external · 내 SUI 줄 없음 · USDC −2 만", rs["fees"] and rs["fees"][0]["payer"] == "external"
      and [d["asset"]["kind"] for d in rs["deltas"]] == ["token"], rs)
ri = recs[TX["i_sponsor"]]
check("U2 내가 남의 거래 가스만 냄(보낸이 아님) = 발견됨 · 가스 payer = 나 · 순변화 −가스", ri["fees"][0]["payer"] == A
      and ri["deltas"][0]["delta_base"] == str(-FEE), ri)
rr = recs[TX["rebate"]]
check("U3 저장 환급 > 비용 = 수수료 −5,000(부호 보존)", rr["fees"][0]["amount_base"] == "-5000" and rr["deltas"][0]["delta_base"] == "5000", rr["fees"])
rf = recs[TX["fail"]]
check("U3 실패 PTB = execution failed · 가스만", rf["execution"]["state"] == "failed" and rf["fees"][0]["amount_base"] == "2500", rf["execution"])
rw = recs[TX["swap"]]
check("U4 풀 낀 교환 모양 = 힌트 unknown · trusted 아님", rw["classification"]["hint"] == "unknown" and rw["classification"]["trusted"] is False, rw["classification"])
ty = recs[TX["types"]]
ids = {d["asset"].get("id"): d for d in ty["deltas"]}
check("U4 ::COINA 와 ::coina 는 다른 자산(대소문자 보존 · 자릿수 0·3 각자) · COINA 자릿수 0 유효",
      COINA in ids and COINa in ids and ids[COINa]["asset"]["decimals"] == 3 and ids[COINA]["asset"]["decimals"] == 0, list(ids))
check("U4 같은 심볼 'USDC' 가짜 = 다른 원장 키", reg.asset_key("sui", "token", FAKE) != reg.asset_key("sui", "token", USDC)
      and ids[FAKE]["asset"]["symbol"] == "USDC")

reg.FORCE_AVAILABLE.add("sui")
c = core.Core(config.load_config())
c.conn.commit()
rd = dict(c.chain_readers)["sui"]


def drain():
    for _i in range(20):
        row = c.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream='sui'").fetchone()
        s0 = (row["seg"], row["off"]) if row else (0, 0)
        c._drain_stream("sui", rd, *s0)
        row = c.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream='sui'").fetchone()
        if row and (row["seg"], row["off"]) == s0:
            break
    c.conn.commit()


def ev(d):
    r9 = c.conn.execute("SELECT event FROM tx_class WHERE chain='sui' AND txhash=?", (d,)).fetchone()
    return r9["event"] if r9 else None


def qsum(loc, sym=None, d=None):
    q = ("SELECT SUM(CAST(p.qty_base AS INTEGER)) FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.location=?"
         + (" AND a.symbol=?" if sym else "") + (" AND p.source_id=?" if d else ""))
    return c.conn.execute(q, tuple(x for x in (loc, sym, d) if x)).fetchone()[0] or 0


drain()
LA = reg.make_location("sui", A)
evs = {k: ev(TX[k]) for k in TX if k != "old"}
check("U1~U4 core 분류: 받음 TRANSFER_IN · 보냄 TRANSFER_OUT · 토큰 받음 TRANSFER_IN · 교환 UNKNOWN · 실패 FAILED · 환급·merge·남 가스 NOOP · 스폰서 받은 보냄 TRANSFER_OUT",
      evs["in"] == "TRANSFER_IN" and evs["out"] == "TRANSFER_OUT" and evs["tok_in"] == "TRANSFER_IN" and evs["swap"] == "UNKNOWN"
      and evs["fail"] == "FAILED" and evs["rebate"] == "NOOP" and evs["merge"] == "NOOP" and evs["i_sponsor"] == "NOOP"
      and evs["sponsored"] == "TRANSFER_OUT" and evs["convert"] == "NOOP" and ev(TX["old"]) is None, evs)
check("U3 코인↔주소 잔고 변환 = 순변화 줄 없음(USDC −100·+100 합 0) · 가스만", [d["asset"]["kind"] for d in recs[TX["convert"]]["deltas"]] == ["native"]
      and qsum(LA, "USDC", TX["convert"]) == 0, recs[TX["convert"]]["deltas"])
net_sui = sum(v for t in ch.txs if t["digest"] in want for o, ty9, v in t["changes"] if o == A and ty9 == SUI)
check("U1 지갑 SUI 원장 합 = 합성 체인 순변화 합(가스·환급 포함 · 이중 계상 없음)", qsum(LA, "SUI") == net_sui, (qsum(LA, "SUI"), net_sui))
check("U3 환급 거래 = 취득 레그 +5,000 · 가스 레그 없음", qsum(LA, "SUI", TX["rebate"]) == 5000)
n_raw = c.conn.execute("SELECT COUNT(*) FROM raw_txs WHERE chain='sui'").fetchone()[0]

ch.tip += 1000
TX["new1"] = ch.add(TIP + 500, [(X, SUI, -3 * E9 - FEE), (A, SUI, 3 * E9)], sender=X)
st3 = cs.ChainState("sui")
col = col_for(st=st3)
st3.mark_emitted = lambda *a, **k: (_ for _ in ()).throw(Crash())
try:
    col.cycle()
except Crash:
    pass
st4 = cs.ChainState("sui")
col = col_for(st=st4)
col.cycle()
check("U6b append 뒤 죽음 → 다시 보냄(인박스 2번)", uids().count(TX["new1"]) == 2, uids().count(TX["new1"]))
drain()
check("U6b 원장은 한 번(raw +1 · 그 거래 +3 SUI 한 번)", c.conn.execute("SELECT COUNT(*) FROM raw_txs WHERE chain='sui'").fetchone()[0] == n_raw + 1
      and qsum(LA, "SUI", TX["new1"]) == 3 * E9)

ls = st4.lane("latest:" + A)["safe"]
n_before = len(uids())
ch.calls.clear()
col = col_for(st=cs.ChainState("sui"))
col.cycle()
check("U7 latest 안전 경계 = 본 체크포인트(tip) · 새 거래 없으면 새 방출 0", ls == {"ck": ch.tip} and len(uids()) == n_before, (ls, ch.tip))
check("U7 끝난 history lane = 과거 질의 0 · 이번 주기 latest 질의 1번", len(calls("SuiTxBack")) == 0 and len(calls("SuiTxFwd")) == 1,
      [c9[0] for c9 in ch.calls])
fv = calls("SuiTxFwd")[0][1]
check("U7 latest 질의 = affectedAddress + afterCheckpoint(경계 − 겹침 600)", fv["a"] == A and fv["ack"] == ch.tip - 600, fv)
st9 = cs.ChainState("sui")
sv = st9.status_view().get(A) or {}
check("U7 상태: 요청 시작·상세 완료 경계·complete(보존 범위 = 제네시스부터)", sv.get("details_complete_through") == ch.tip and sv.get("complete") is True
      and sv.get("coverage") == "full" and st9.ready({A}), sv)

ch.tip += 1000
TX["new2"] = ch.add(ch.tip - 10, [(X, SUI, -E9 - FEE), (A, SUI, E9)], sender=X)
for kind in ("http429", "http500", "badjson", "short", "gqlerr", "partial"):
    st5 = cs.ChainState("sui")
    st5.d.pop("synced_at", None)
    st5.save()
    s_before = st5.lane("latest:" + A)["safe"]
    ch.inject["SuiTxFwd"] = [kind]
    col = col_for(st=st5)
    col.discover("latest")
    st6 = cs.ChainState("sui")
    check(f"U8 발견 {kind} = 경계 전진 없음 · 새 후보 없음 · 오류 셈", st6.lane("latest:" + A)["safe"] == s_before and col.errors >= 1
          and TX["new2"] not in st6.d["pending"], (kind, st6.lane("latest:" + A), col.errors))
ch.inject.clear()
st7 = cs.ChainState("sui")
st7.d.pop("synced_at", None)
st7.save()
ch.inject["SuiTx"] = ["nulltx"]
col = col_for(st=st7)
col.ad._cache.clear()
col.discover("latest")
col.ad._cache.clear()
col.details("latest")
st8 = cs.ChainState("sui")
check("U8 상세 null(아직 색인 안 됨) = 다시 예약(없는 거래로 결론 안 냄) · 방출 없음", TX["new2"] in st8.d["pending"]
      and st8.d["pending"][TX["new2"]]["tries"] == 1 and TX["new2"] not in uids(), st8.d["pending"].get(TX["new2"]))
for kind in ("noeffects", "notime", "http500"):
    ch.inject["SuiTx"] = [kind]
    st8.d["pending"][TX["new2"]]["next"] = 0
    col = col_for(st=st8)
    col.ad._cache.clear()
    col.details("latest")
    check(f"U8 상세 {kind} = 방출 없음 · 다시 예약", TX["new2"] not in uids() and TX["new2"] in st8.d["pending"], kind)
ch.inject["SuiTxBc"] = ["gqlerr"]
st8.d["pending"][TX["new2"]]["next"] = 0
col = col_for(st=st8)
col.ad._cache.clear()
ch.bc_cap = 1
col.details("latest")
check("U8 안쪽 balanceChanges 둘째 쪽 실패 = 부분 레코드 안 보냄", TX["new2"] not in uids() and TX["new2"] in st8.d["pending"])
ch.bc_cap = 2
st8.d["pending"][TX["new2"]]["next"] = 0
col = col_for(st=st8)
r8 = col.cycle()
check("U8 회복 뒤 정상 방출 · 동기화 도장", TX["new2"] in uids() and cs.ChainState("sui").d.get("synced_at"), r8)

ch.tip += 5000
base9 = ch.tip - 4000
for i in range(7):
    TX[f"b{i}"] = ch.add(base9 + (i if i < 4 else i * 100), [(X, SUI, -(i + 1) - FEE), (A, SUI, i + 1)], sender=X)
for i in range(4):
    TX[f"tie{i}"] = ch.add(base9 + 2, [(X, SUI, -(20 + i) - FEE), (A, SUI, 20 + i)], sender=X)
st10 = cs.ChainState("sui")
col = col_for(st=st10)
col.page_budget = {"latest": 1, "history": 20}
col.discover("latest")
cur10 = cs.ChainState("sui").lane("latest:" + A).get("cursor")
ch.inject["SuiTxFwd"] = ["gqlerr"]
col = col_for(st=cs.ChainState("sui"))
col.discover("latest")
cur11 = cs.ChainState("sui").lane("latest:" + A).get("cursor")
check("U9 이어 읽기 커서가 GraphQL 오류 → 커서 버림(경계부터 다시)", isinstance(cur10, dict) and cur10.get("c") and cur11 is None, (cur10, cur11))
col = col_for(st=cs.ChainState("sui"))
col.cycle()
got9 = uids()
check("U9 다시 읽어 7건 + 같은 체크포인트 4건 전부 · 중복 방출 없음(쪽 경계의 동률 보존)",
      all(got9.count(TX[f"b{i}"]) == 1 for i in range(7)) and all(got9.count(TX[f"tie{i}"]) == 1 for i in range(4)),
      [got9.count(TX[k]) for k in TX if k.startswith(("b", "tie"))])
cfg_l = json.loads(json.dumps(cfg))
cfg_l["nonevm"]["sui"]["graphql_url"] = URL.replace("127.0.0.1", "localhost")
ch.tip += 300
TX["p1"] = ch.add(ch.tip - 5, [(X, SUI, -11 - FEE), (A, SUI, 11)], sender=X)
n9 = len(uids())
col = col_for(ad=SW.make_adapter(cfg_l), st=cs.ChainState("sui"))
col.cycle()
st11 = cs.ChainState("sui")
check("U9 제공자 바뀜(지문) = lane 커서 초기화 · 안전 경계 유지 · 새 거래 1건만 방출", st11.lane("latest:" + A)["fp"].endswith("|localhost|latest")
      and len(uids()) == n9 + 1 and TX["p1"] in uids(), (st11.lane("latest:" + A), len(uids()) - n9))
check("U9 제공자 바뀜에도 끝난 history 는 다시 안 훑음", st11.lane("history:" + A)["safe"].get("done") is True)

ch.tip += 300
TX["self"] = ch.add(ch.tip - 50, [(A, SUI, -2 * E9 - FEE), (B, SUI, 2 * E9)], sender=A)
col = col_for(st=cs.ChainState("sui"))
col.cycle()
drain()
check("U10 B 등록 전 = A 관점만(TRANSFER_OUT)", ev(TX["self"]) == "TRANSFER_OUT")
c.chain_owners["sui"] = {A, B}
col = col_for(owners=(A, B), st=cs.ChainState("sui"))
col.cycle()
drain()
LB = reg.make_location("sui", B)
check("U10 B 등록 뒤 같은 digest 넓은 관점 재방출 → TRANSFER_SELF · B +2 SUI 한 번", ev(TX["self"]) == "TRANSFER_SELF"
      and qsum(LB, "SUI", TX["self"]) == 2 * E9, (ev(TX["self"]), qsum(LB, "SUI", TX["self"])))
st12 = cs.ChainState("sui")
check("U10 B 의 history·latest lane 따로 시작(B 의 과거 lane 끝까지)", st12.lane("history:" + B).get("safe", {}).get("done") is True
      and st12.lane("latest:" + B).get("safe"), st12.lane("history:" + B))
n_raw2 = c.conn.execute("SELECT COUNT(*) FROM raw_txs WHERE chain='sui'").fetchone()[0]
col = col_for(owners=(A, B), st=cs.ChainState("sui"))
col.cycle()
col.cycle()
drain()
check("U6 다시 돌려도 새 방출·새 원장 행 0(멱등)", c.conn.execute("SELECT COUNT(*) FROM raw_txs WHERE chain='sui'").fetchone()[0] == n_raw2)
st14 = cs.ChainState("sui")
st14.drop_owner({A})
st14.save()
ch.tip += 400
TX["b_gone"] = ch.add(ch.tip - 100, [(X, SUI, -31 - FEE), (B, SUI, 31)], sender=X)
col = col_for(owners=(A,), st=cs.ChainState("sui"))
col.cycle()
check("U10 B 뺀 동안 B 거래는 안 봄", TX["b_gone"] not in uids())
ch.tip += 400
col = col_for(owners=(A, B), st=cs.ChainState("sui"))
col.cycle()
st15 = cs.ChainState("sui")
check("U10 B 다시 등록 = 옛 안전 경계부터 이어 읽어 빠진 동안의 거래도 발견(구멍 없음) · 과거 lane 다시 안 훑음",
      uids().count(TX["b_gone"]) == 1 and st15.lane("history:" + B)["safe"].get("done") is True, uids().count(TX["b_gone"]))

ch.avail = (ck_days(120), ch.ts(ck_days(120)))
col = col_for(owners=(A, B), st=cs.ChainState("sui"))
col.ad.preflight(force=True)
col.cycle()
sv = cs.ChainState("sui").status_view()
check("U11 availableRange 시작이 창 시작보다 늦음 = coverage partial · available_from · complete 아님", sv[A]["coverage"] == "partial"
      and sv[A]["available_from"] == ch.ts(ck_days(120)) and sv[A]["complete"] is False, sv[A])
check("U11 partial 이어도 지금 잔고 대사 준비는 됨(ready)", cs.ChainState("sui").ready({A, B}))
ch.avail = (0, ch.base)

ch.tip += 200
TX["mm"] = ch.add(ch.tip - 10, [(X, SUI, -41 - FEE), (A, SUI, 41)], sender=X)
col = col_for(owners=(A, B), st=cs.ChainState("sui"))
col.discover("latest")
ch.inject["SuiPreflight"] = ["testnet"] * 50
ch.calls.clear()
ad12 = SW.make_adapter(cfg)
st13 = cs.ChainState("sui")
st13.d.pop("synced_at", None)
st13.save()
col = col_for(owners=(A, B), ad=ad12, st=st13)
n13 = len(uids())
col.cycle()
check("U12 테스트넷 chainIdentifier = 수집 안 함 · 동기화 도장 없음 · 대기 중 상세도 묻지 않음(다시 예약)", len(uids()) == n13
      and not cs.ChainState("sui").d.get("synced_at") and col.errors >= 1 and not calls("SuiTx") and not calls("SuiTxFwd")
      and TX["mm"] in cs.ChainState("sui").d["pending"], [c9[0] for c9 in ch.calls])
check("U12 망 불일치 기억 = 대기 거래마다 다시 묻지 않음(사전 점검 1번)", len(calls("SuiPreflight")) == 1, len(calls("SuiPreflight")))
ch.inject.clear()
cs9 = cs.ChainState("sui")
cs9.d["pending"][TX["mm"]]["next"] = 0
cs9.save()
col = col_for(owners=(A, B), st=cs9)
col.cycle()
check("U12 메인넷으로 돌아오면 대기 거래 방출", TX["mm"] in uids())
ch.inject.clear()
cfg_x = json.load(open(CFG_PATH))
cfg_x["backfill_since"] = time.strftime("%Y-%m-%d", time.gmtime(ch.ts(ck_days(210))))
json.dump(cfg_x, open(CFG_PATH, "w"))
os.utime(CFG_PATH, (time.time() + 5, time.time() + 5))
col = col_for(owners=(A, B), st=cs.ChainState("sui"))
col.cycle()
check("U12 창 확장(backfill_since 210일 전) = 200일 전 거래 추가 방출 · 기존 거래 재방출 없음", TX["old"] in uids()
      and uids().count(TX["in"]) == 1, uids().count(TX["old"]))
check("U12 확장 뒤 history done · t0 = 새 창", cs.ChainState("sui").lane("history:" + A)["safe"].get("done") is True)

cfg_m = json.load(open(CFG_PATH))
cfg_m.setdefault("backfill", {}).setdefault("hosts", {})["127.0.0.1"] = {"rate": 10000.0, "burst": 10000, "conc": 16, "breaker_fails": 100}
json.dump(cfg_m, open(CFG_PATH, "w"))
ch.tip += 100
TX["main"] = ch.add(ch.tip - 5, [(X, SUI, -51 - FEE), (A, SUI, 51)], sender=X)
sleep0 = SW.time.sleep
SW.time.sleep = lambda _s: (_ for _ in ()).throw(KeyboardInterrupt())
try:
    rm = T.safe(SW.main)
finally:
    SW.time.sleep = sleep0
check("U13 main 한 주기 = 새 거래 방출 · SIGINT 조용히 종료(예외 없음)", TX["main"] in uids() and rm is None, rm)
json.dump(dict(cfg_m, chain_wallets=[]), open(CFG_PATH, "w"))
try:
    SW.main()
    rm2 = "returned"
except SystemExit as e:
    rm2 = str(e)
check("U13 지갑 없음 = 바로 끝(SystemExit — 러너가 대기로 돌림)", "지갑이 없음" in rm2, rm2)
json.dump(dict(cfg_m, nonevm={"sui": {"graphql_url": "http://example.invalid/graphql"}}), open(CFG_PATH, "w"))
try:
    SW.main()
    rm3 = "returned"
except SystemExit as e:
    rm3 = str(e)
check("U13 https 아닌 graphql_url = 설정 오류로 끝(재시작 폭주 없음 · 바깥 연결 없음)", "설정 오류" in rm3, rm3)

reg.FORCE_AVAILABLE.clear()
srv.shutdown()
T.finish()
