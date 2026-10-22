#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
from _ingest import check  # noqa: E402
import _nonevm as N  # noqa: E402,F401

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

import config, paths  # noqa: E402
import core  # noqa: E402
import chain_registry as reg  # noqa: E402
import chain_state as cs  # noqa: E402
import chain_watch as cw  # noqa: E402
import address_codec as ac  # noqa: E402
from inbox import SegmentWriter, SegmentReader  # noqa: E402
import ton_watch as tw  # noqa: E402
import _ton_fake as F  # noqa: E402

DAY = 86400
NOW = int(time.time())
A, B, C9, X, EX, Y = F.K("31"), F.K("32"), F.K("33"), F.K("99"), F.K("98"), F.K("97")
M, M0, MF = F.K("a1"), F.K("a2"), F.K("a3")
WA, WB, WX, WZ, WF = F.K("b1"), F.K("b2"), F.K("b9"), F.K("b3"), F.K("bf")
TON = 10 ** 9
CFG_PATH = os.path.join(T.TMP, "config.json")
INB = os.path.join(paths.INBOX_DIR, "ton")
reg.FORCE_AVAILABLE.add("ton")


def set_wallets(*keys):
    cfg = json.load(open(CFG_PATH))
    cfg["chain_wallets"] = [{"chain": "ton", "address": ac.ton_friendly(k, bounceable=(i % 2 == 0))} for i, k in enumerate(keys)]
    cfg["exchange_addresses"] = [{"exchange": "upbit", "chain": "ton", "address": ac.ton_friendly(EX, bounceable=True)}]
    json.dump(cfg, open(CFG_PATH, "w"))
    return config.load_config()


cfg = set_wallets(A)
ch = F.Chain()
srv = F.Server(ch).start()
W = SegmentWriter(INB)


def mk(owners, st=None, page=3):
    st = st or cs.ChainState("ton")
    ad = tw.TonAdapter(config.load_config(), client=srv.client(), state=st)
    ad.page = page
    return ad, st, cw.Collector(ad, W, st, set(owners), page_budget={"latest": 10, "history": 20},
                                detail_budget={"latest": 200, "history": 500})


def inbox():
    out = []
    for f in sorted(os.listdir(INB)) if os.path.isdir(INB) else []:
        if f.endswith(".jsonl"):
            out += [json.loads(ln) for ln in open(os.path.join(INB, f)) if ln.strip()]
    return out


c = None


def drain():
    rd = SegmentReader(INB)
    for _i in range(50):
        row = c.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream='ton'").fetchone()
        seg, off = (row["seg"], row["off"]) if row else (1, 0)
        c._drain_stream("ton", rd, seg, off)
        row2 = c.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream='ton'").fetchone()
        if row2 and row and (row2["seg"], row2["off"]) == (seg, off):
            break


def lsum(owner, sym=None):
    q = ("SELECT SUM(CAST(p.qty_base AS INTEGER)) s FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.location=? AND a.chain='ton'"
         + (" AND a.kind='native'" if sym is None else " AND a.symbol=?"))
    r = c.conn.execute(q, (reg.make_location("ton", owner),) + (() if sym is None else (sym,))).fetchone()
    return int(r["s"] or 0)


def ev_of(uid):
    r = c.conn.execute("SELECT event FROM tx_class WHERE chain='ton' AND txhash=?", (uid,)).fetchone()
    return r["event"] if r else None


def uid_of(t):
    return tw.tx_uid(tw.akey(t["account"]), t["lt"], t["_hex"])


bt = F.body_transfer(123456789, X, resp=A, qid=77)
pb = tw.parse_jetton_body(bt, tw.OP_JETTON_TRANSFER)
check("B1 transfer 본문: 금액·받는 주인·query_id", pb["amount"] == 123456789 and pb["dest"] == X and pb["qid"] == 77, pb)
pi = tw.parse_jetton_body(F.body_internal(5, None), tw.OP_INTERNAL_TRANSFER)
check("B2 internal_transfer from = addr_none(발행) → None", pi["amount"] == 5 and pi["from"] is None, pi)
pbn = tw.parse_jetton_body(F.body_bounced(tw.OP_INTERNAL_TRANSFER, 9), tw.OP_INTERNAL_TRANSFER)
check("B3 되돌아온 본문(0xFFFFFFFF + 원 op) 금액", pbn["bounced"] and pbn["amount"] == 9, pbn)
check("B4 주소 slice 왕복(get_wallet_address 인자)", tw.Bits(tw.boc_root_bits(tw.boc_one_cell(tw.addr_bits(A)))).addr() == A)
try:
    tw.parse_jetton_body(bt, tw.OP_BURN)
    ok = False
except ValueError:
    ok = True
check("B5 본문 op ≠ 제공자 opcode = 오류(지어내지 않음)", ok)
check("B6 깨진 BoC = 오류", T.safe(tw.boc_root_bits, "AAAA").get("_exc", "").startswith("ValueError") if isinstance(T.safe(tw.boc_root_bits, "AAAA"), dict) else False)

t1 = ch.tx(A, NOW - 9 * DAY, in_msg={"src": X, "val": 10 * TON}, tf=1200)
t2 = ch.tx(A, NOW - 8 * DAY, in_msg={"src": None}, outs=[{"dst": X, "val": 2 * TON, "fwd": 400}], tf=3000)
t3 = ch.tx(A, NOW - 7 * DAY, in_msg={"src": None}, outs=[{"dst": EX, "val": 1 * TON, "fwd": 400}], tf=3000)
t4 = ch.tx(A, NOW - 6 * DAY, in_msg={"src": Y, "val": 1, "op": 0}, tf=60, aborted=True)
t5 = ch.tx(A, NOW - 5 * DAY, in_msg={"src": None}, tf=500, aborted=True)
t6 = ch.tx(A, NOW - 4 * DAY, in_msg={"src": X, "val": 3 * TON}, tf=800)
ch.no_state.add(t6["_hex"])
t7 = ch.tx(A, NOW - 3 * DAY, in_msg={"src": X, "val": TON}, tf=700, fee_skew=-5)
e1 = tw.wallet_effect(tw.compact(t1))
check("F1 받기 = 잔고 전후 · 수수료 = total_fees", e1["net"] == 10 * TON - 1200 and e1["fee"] == 1200 and not e1["reasons"], e1)
e2 = tw.wallet_effect(tw.compact(t2))
check("F2 보내기 수수료 = total_fees + fwd_fee(이중 차감 없음)", e2["fee"] == 3400 and e2["net"] == -(2 * TON + 3400), e2)
e6 = tw.wallet_effect(tw.compact(ch.strip(t6)))
check("F3 잔고 칸 없음 = 보존식 순변화 + 사유", e6["net"] == 3 * TON - 800 and "state_balance_missing" in e6["reasons"], e6)
e7 = tw.wallet_effect(tw.compact(t7))
check("F4 보존식 어긋남 = 수수료 미확정(None) · 순변화는 실제 잔고", e7["fee"] is None and e7["net"] == TON - 705 and "fee_unresolved" in e7["reasons"], e7)

ad, st, col = mk({A})
r = col.cycle()
c = core.Core(config.load_config())
c.conn.commit()
drain()
check("C0 첫 주기: 7건 방출 · 대기 0 · 동기화 도장", len(inbox()) == 7 and r["left"] == 0 and st.d.get("synced_at"), (r, len(inbox())))
check("C1 지갑 원장 합 = 합성 체인 잔고(수수료·먼지·실패·잔고 칸 없음 포함)", lsum(A) == ch.bal[A], (lsum(A), ch.bal[A]))
evs = [ev_of(uid_of(t)) for t in (t1, t2, t3, t4, t5)]
check("C2 분류: 받기 IN · 보내기 OUT · 거래소 OUT_EX · 먼지 IN · 외부 실패 FAILED",
      evs == ["TRANSFER_IN", "TRANSFER_OUT", "TRANSFER_OUT_EX", "TRANSFER_IN", "FAILED"], evs)
rec7 = [x for x in inbox() if x["tx_uid"] == uid_of(t7)][0]
check("C3 수수료 미확정 레코드 = fees 없음 · 사유 fee_unresolved", not rec7["fees"] and "fee_unresolved" in rec7["completeness"]["reasons"], rec7["fees"])
check("C4 tx_uid = '<계정 원장 키>.<lt>.<hash hex>' · txhash = hex · 순서 lt",
      rec7["tx_uid"].startswith(A + ".") and len(rec7["txhash"]) == 64 and rec7["order"]["lt"] == int(t7["lt"]))
check("C5 스왑 힌트 없음(SWAP 안 만듦)", not any(x["classification"]["hint"] == "swap" for x in inbox()))

ch.add_jetton(A, WA, M, symbol="TKA", decimals="6")
ch.add_jetton(A, WF, MF, symbol="USDT", decimals="6", real=False)
ch.add_jetton(A, WZ, M0, symbol="ZRO", decimals="0")
q = ch.tx(WA, NOW - 2 * DAY, in_msg={"src": WX, "val": 50_000_000, "op": tw.OP_INTERNAL_TRANSFER, "body": F.body_internal(100_000_000, X, resp=X, qid=5)}, tf=0)
ch.tx(A, NOW - 2 * DAY + 1, in_msg={"src": WA, "val": 10_000_000, "op": tw.OP_TRANSFER_NOTIFICATION}, tf=300)
s1 = ch.tx(A, NOW - 2 * DAY + 100, in_msg={"src": None}, outs=[{"dst": WA, "val": 50_000_000, "fwd": 500, "op": tw.OP_JETTON_TRANSFER}], tf=4000)
s2 = ch.recv(s1, 0, WA, NOW - 2 * DAY + 101, tf=0)
s2["in_msg"]["message_content"]["body"] = F.body_transfer(40_000_000, X, resp=A, qid=6)
ch.tx(A, NOW - 2 * DAY + 102, in_msg={"src": WX, "val": 30_000_000, "op": tw.OP_EXCESS}, tf=300)
ch.tx(WA, NOW - 2 * DAY + 200, in_msg={"src": M, "val": 1, "op": tw.OP_INTERNAL_TRANSFER, "body": F.body_internal(5_000_000, None)}, tf=0)
b1 = ch.tx(A, NOW - 2 * DAY + 300, in_msg={"src": None}, outs=[{"dst": WA, "val": 50_000_000, "fwd": 500, "op": tw.OP_BURN}], tf=4000)
b2 = ch.recv(b1, 0, WA, NOW - 2 * DAY + 301, tf=0)
b2["in_msg"]["message_content"]["body"] = F.body_burn(1_000_000)
ch.tx(WA, NOW - 2 * DAY + 400, in_msg={"src": A, "val": 1, "op": tw.OP_JETTON_TRANSFER, "body": F.body_transfer(10_000_000, Y)}, tf=0)
ch.tx(WA, NOW - 2 * DAY + 401, in_msg={"src": F.K("b7"), "val": 1, "op": tw.OP_INTERNAL_TRANSFER, "bounced": True,
                                       "body": F.body_bounced(tw.OP_INTERNAL_TRANSFER, 10_000_000)}, tf=0)
ch.tx(WA, NOW - 2 * DAY + 500, in_msg={"src": A, "val": 1, "op": tw.OP_JETTON_TRANSFER, "body": F.body_transfer(999_000_000, Y)}, tf=0,
      aborted=True)
for k in range(2):
    ch.tx(WA, NOW - DAY + k, in_msg={"src": WX, "val": 1, "op": tw.OP_INTERNAL_TRANSFER, "body": F.body_internal(3_000_000, X, qid=42)}, tf=0)
ch.tx(WF, NOW - DAY + 10, in_msg={"src": F.K("c1"), "val": 1, "op": tw.OP_INTERNAL_TRANSFER, "body": F.body_internal(10 ** 12, X)}, tf=0)
ch.tx(A, NOW - DAY + 20, in_msg={"src": Y, "val": 1_000_000, "op": tw.OP_TRANSFER_NOTIFICATION}, tf=300)
ch.tx(WZ, NOW - DAY + 30, in_msg={"src": WX, "val": 1, "op": tw.OP_INTERNAL_TRANSFER, "body": F.body_internal(7, X)}, tf=0)
ch.jbal[WA] = 100_000_000 - 40_000_000 + 5_000_000 - 1_000_000 - 10_000_000 + 10_000_000 + 6_000_000
ch.jbal[WZ] = 7
ch.jbal[WF] = 10 ** 12
srv.jw_cap = 1
r = col.cycle()
srv.jw_cap = None
drain()
check("J1 가짜 제톤 지갑(get_wallet_address 불일치) = 등록 안 함 · 사유 기록", WF not in st.d["ton"]["acct"] and st.d["ton"]["jw"][WF]["ok"] is False
      and WA in st.d["ton"]["acct"], st.d["ton"]["jw"].get(WF))
check("J2 ★제톤 원장 합 = 합성 제톤 잔고★(받기·보내기·발행·소각·되돌아옴·중단·같은 query_id)", lsum(A, "TKA") == ch.jbal[WA], (lsum(A, "TKA"), ch.jbal[WA]))
check("J3 ★지갑 TON 원장 합 = 체인 잔고★(실어 보낸 TON·excess·알림·가짜 알림 포함)", lsum(A) == ch.bal[A], (lsum(A), ch.bal[A]))
check("J4 가짜 master 자산·가짜 지갑 수량 없음", c.conn.execute("SELECT COUNT(*) FROM assets WHERE chain='ton' AND address=?", (MF,)).fetchone()[0] == 0)
ev_s1, ev_s2 = ev_of(uid_of(s1)), ev_of(uid_of(s2))
check("J5 제톤 보내기: 지갑 tx = NOOP(실어 보낸 TON = 수수료) · 제톤 지갑 tx = TRANSFER_OUT(−40)", ev_s1 == "NOOP" and ev_s2 == "TRANSFER_OUT", (ev_s1, ev_s2))
rec_s2 = [x for x in inbox() if x["tx_uid"] == uid_of(s2)][0]
check("J6 보낸 제톤 상대 = 받는 주인(제톤 지갑 아님) · 자산 id = master",
      rec_s2["movements"][0]["to"] == X and rec_s2["deltas"][0]["asset"]["id"] == ac.ton_raw(M) and rec_s2["deltas"][0]["asset"]["decimals"] == 6, rec_s2["movements"])
evs = {x["classification"]["evidence"]: ev_of(x["tx_uid"]) for x in inbox() if x["tx_uid"].startswith(WA + ".")}
check("J7 발행 = PROGRAM_IN(검토) · 되돌아옴 = PROGRAM_IN · 받기 = TRANSFER_IN · 소각 = TRANSFER_OUT · 중단 = NOOP",
      evs.get("ton:jetton:mint") == "PROGRAM_IN" and evs.get("ton:jetton:bounce_refund") == "PROGRAM_IN" and evs.get("ton:jetton:transfer_in") == "TRANSFER_IN"
      and evs.get("ton:jetton:burn") == "TRANSFER_OUT" and evs.get("ton:jetton:aborted") == "NOOP", evs)
refunds = [x for x in inbox() if x["classification"]["evidence"].startswith("ton:wallet") and ":refund" in x["classification"]["evidence"]]
check("J8 excess·알림 TON = 음수 수수료(환급) · 새 수익(TRANSFER_IN) 아님", refunds and all(ev_of(x["tx_uid"]) == "NOOP" and int(x["fees"][0]["amount_base"]) < 0
                                                                    for x in refunds), [(ev_of(x["tx_uid"]), x["fees"]) for x in refunds])
fake_n = [x for x in inbox() if x["tx_uid"].startswith(A + ".") and x["ts"] == NOW - DAY + 20]
check("J8 남(검증 안 된 계약)이 보낸 '알림'의 TON = 그냥 받은 TON(TRANSFER_IN) · 제톤 수량 없음",
      fake_n and ev_of(fake_n[0]["tx_uid"]) == "TRANSFER_IN" and all(d["asset"]["kind"] == "native" for d in fake_n[0]["deltas"]), fake_n[:1])
check("J1 제공자 쪽 상한(1개씩)에도 제톤 지갑 목록 끝까지(빈 쪽 확인)", WZ in st.d["ton"]["acct"] and WA in st.d["ton"]["acct"])
zro = c.conn.execute("SELECT decimals FROM assets WHERE chain='ton' AND address=?", (M0,)).fetchone()
check("J9 자릿수 0 은 0(18 아님)", zro is not None and zro["decimals"] == 0 and lsum(A, "ZRO") == 7, dict(zro) if zro else None)
check("J10 제톤 지갑의 TON 은 내 보유 아님(제톤 지갑 위치 레그 없음)",
      c.conn.execute("SELECT COUNT(*) FROM postings WHERE location LIKE ?", ("%" + WA[2:12] + "%",)).fetchone()[0] == 0)
check("J11 메타 없음(체인 밖 URI 만·색인 없음) = 자릿수 None(18 로 안 지음)",
      tw._meta_of({"jetton_content": {"uri": "https://x.invalid"}}, {})["decimals"] is None and tw._meta_of({"jetton_content": {"decimals": "0"}}, {})["decimals"] == 0
      and tw._meta_of(None, {"m": {"token_info": [{"valid": True, "type": "jetton_masters", "symbol": "Q", "extra": {}}]}})["decimals"] == 9)

ch2 = F.Chain()
srv2 = F.Server(ch2).start()
SP = F.K("5a")
for i in range(25):
    ch2.add_jetton(SP, F.K("%02x" % (0x60 + i)), F.K("%02x" % (0x80 + i)), symbol="SPAM%d" % i, decimals="9")
os.makedirs(os.path.join(T.TMP, "st2"), exist_ok=True)
st2 = cs.ChainState("ton", os.path.join(T.TMP, "st2"))
ad2 = tw.TonAdapter(config.load_config(), client=srv2.client(), state=st2)
ad2.discover_page(SP, {"owner": SP, "lane": "latest"}, None)
n1 = sum(1 for v in st2.d["ton"]["jw"].values())
ad2.discover_page(SP, {"owner": SP, "lane": "latest"}, None)
n2 = sum(1 for v in st2.d["ton"]["jw"].values())
check("J12 새 제톤 지갑 검증 = 한 차례 10개 상한 · 다음 차례 이어서", n1 == tw.JW_VERIFY_PER_PASS and n2 == 2 * tw.JW_VERIFY_PER_PASS, (n1, n2))
srv2.stop()

DX = F.K("d1")
d1 = ch.tx(A, NOW - 1800, in_msg={"src": None}, outs=[{"dst": DX, "val": 2 * TON, "fwd": 400, "op": 0x25938561}], tf=3000)
d2 = ch.tx(WA, NOW - 1790, in_msg={"src": WX, "val": 1, "op": tw.OP_INTERNAL_TRANSFER, "body": F.body_internal(4_000_000, DX)}, tf=0, trace=d1["_hex"])
d3 = ch.tx(A, NOW - 1780, in_msg={"src": DX, "val": TON // 10}, tf=300, trace=d1["_hex"])
ch.jbal[WA] += 4_000_000
r = col.cycle()
drain()
check("D1 내 스왑 결과 제톤·TON 유입 = PROGRAM_IN(검토 · 일반 받기로 단정 안 함) · 보낸 TON = TRANSFER_OUT · SWAP 없음",
      ev_of(uid_of(d1)) == "TRANSFER_OUT" and ev_of(uid_of(d2)) == "PROGRAM_IN" and ev_of(uid_of(d3)) == "PROGRAM_IN", (ev_of(uid_of(d1)), ev_of(uid_of(d2)), ev_of(uid_of(d3))))
check("D2 수량은 그대로(제톤·TON 원장 합 = 잔고)", lsum(A, "TKA") == ch.jbal[WA] and lsum(A) == ch.bal[A], (lsum(A, "TKA"), ch.jbal[WA]))

cfg = set_wallets(A, B)
c.chain_owners["ton"] = {A, B}
p1 = ch.tx(A, NOW - 3600, in_msg={"src": None}, outs=[{"dst": B, "val": 3 * TON, "fwd": 400}], tf=3000)
p2 = ch.recv(p1, 0, B, NOW - 3590, tf=900)
ad, st, col = mk({A, B}, st)
r = col.cycle()
drain()
recs = [x for x in inbox() if x["tx_uid"] == uid_of(p1)]
check("S1 보낸·받은 tx = 한 레코드(uid = 보낸 tx) · TRANSFER_SELF · 받은 tx 따로 없음",
      recs and ev_of(uid_of(p1)) == "TRANSFER_SELF" and ev_of(uid_of(p2)) is None and set(recs[-1]["owners"]) == {A, B}, (ev_of(uid_of(p1)), len(recs)))
check("S2 두 지갑 원장 합 = 각 체인 잔고(수수료만 줄어듦)", lsum(A) == ch.bal[A] and lsum(B) == ch.bal[B], (lsum(A), ch.bal[A], lsum(B), ch.bal[B]))
n_raw = c.conn.execute("SELECT COUNT(*) FROM raw_txs WHERE chain='ton' AND txhash=?", (uid_of(p1),)).fetchone()[0]
check("S3 같은 묶음이 두 번 와도(보낸 쪽·받은 쪽) 원장 1번", n_raw == 1 and len(recs) >= 1, (n_raw, len(recs)))
p3 = ch.tx(A, NOW - 3000, in_msg={"src": None}, outs=[{"dst": B, "val": TON, "fwd": 400}], tf=3000)
p4 = ch.recv(p3, 0, B, NOW - 2990, tf=900)
ch.hidden.add(p3["_hex"])
r = col.cycle()
drain()
first = ev_of(uid_of(p3))
ch.hidden.discard(p3["_hex"])
r = col.cycle()
drain()
check("S4 받는 쪽 먼저 처리 → 뿌리 uid 로 TRANSFER_SELF · 보낸 쪽이 나중에 와도 같음(원장 1번)",
      first == "TRANSFER_SELF" and ev_of(uid_of(p3)) == "TRANSFER_SELF" and ev_of(uid_of(p4)) is None and lsum(A) == ch.bal[A] and lsum(B) == ch.bal[B],
      (first, ev_of(uid_of(p3)), lsum(A), ch.bal[A]))
p5 = ch.tx(A, NOW - 2000, in_msg={"src": None}, outs=[{"dst": C9, "val": 2 * TON, "fwd": 400}], tf=3000)
ch.recv(p5, 0, C9, NOW - 1990, tf=900)
r = col.cycle()
drain()
before = ev_of(uid_of(p5))
cfg = set_wallets(A, B, C9)
c.chain_owners["ton"] = {A, B, C9}
ad, st, col = mk({A, B, C9}, st)
r = col.cycle()
drain()
check("S5 나중 등록: TRANSFER_OUT → 받은 쪽 발견 뒤 TRANSFER_SELF(grow 교체 · 수량 중복 없음)",
      before == "TRANSFER_OUT" and ev_of(uid_of(p5)) == "TRANSFER_SELF" and lsum(C9) == ch.bal[C9] and lsum(A) == ch.bal[A], (before, ev_of(uid_of(p5)), lsum(C9), ch.bal[C9]))
ch.add_jetton(B, WB, M, symbol="TKA", decimals="6")
j1 = ch.tx(WA, NOW - 1000, in_msg={"src": A, "val": 1, "op": tw.OP_JETTON_TRANSFER, "body": F.body_transfer(7_000_000, B, resp=A)}, tf=0,
           outs=[{"dst": WB, "val": 1, "fwd": 0, "op": tw.OP_INTERNAL_TRANSFER, "body": F.body_internal(7_000_000, A, resp=A)}])
j2 = ch.recv(j1, 0, WB, NOW - 999, tf=0)
ch.jbal[WA] -= 7_000_000
ch.jbal[WB] = 7_000_000
r = col.cycle()
drain()
check("S6 제톤 자기이체 = 한 레코드 TRANSFER_SELF · 양쪽 제톤 합 = 각 잔고",
      ev_of(uid_of(j1)) == "TRANSFER_SELF" and ev_of(uid_of(j2)) is None and lsum(A, "TKA") == ch.jbal[WA] and lsum(B, "TKA") == 7_000_000,
      (ev_of(uid_of(j1)), lsum(A, "TKA"), ch.jbal[WA], lsum(B, "TKA")))

n0 = len(inbox())
r1 = ch.tx(A, NOW - 500, in_msg={"src": X, "val": TON}, tf=700)
st_r = cs.ChainState("ton")
ad, st_r, col = mk({A, B, C9}, st_r)
st_r.save_cursor = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("죽음"))
try:
    col.discover("latest")
except RuntimeError:
    pass
st_r2 = cs.ChainState("ton")
check("R1 대기열·hw 는 함께 저장 → 커서 저장 전 죽어도 빠짐 없음", uid_of(r1) in st_r2.d["pending"]
      and st_r2.d["ton"]["acct"][A]["hw"][0] == int(r1["lt"]), list(st_r2.d["pending"])[:3])
ad, st_r2, col = mk({A, B, C9}, st_r2)
st_r2.mark_emitted = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("죽음"))
try:
    col.cycle()
except RuntimeError:
    pass
ad, st, col = mk({A, B, C9})
col.cycle()
drain()
check("R2 append 뒤 방출 기록 전 죽음 → 다시 보냄(인박스 2번) · 원장 1번",
      [x["tx_uid"] for x in inbox()].count(uid_of(r1)) == 2 and c.conn.execute("SELECT COUNT(*) FROM raw_txs WHERE txhash=?", (uid_of(r1),)).fetchone()[0] == 1
      and lsum(A) == ch.bal[A], [x["tx_uid"] for x in inbox()].count(uid_of(r1)))
g1 = ch.tx(A, NOW - 400, in_msg={"src": X, "val": TON}, tf=700)
g2 = ch.tx(A, NOW - 300, in_msg={"src": X, "val": 2 * TON}, tf=700)
ch.hidden.add(g1["_hex"])
hw0 = st.d["ton"]["acct"][A]["hw"][0]
r = col.cycle()
check("R3 연속성 끊김(가운데 tx 가 색인에 늦게) = 전진 안 함 · 동기화 도장 없음 · '거래 없음' 아님",
      st.d["ton"]["acct"][A]["hw"][0] == hw0 and uid_of(g2) not in st.d["pending"] and col.errors > 0, (st.d["ton"]["acct"][A]["hw"], r))
ch.hidden.discard(g1["_hex"])
col.cycle()
drain()
check("R4 색인 회복 → 두 건 모두 순서대로 · 원장 합 = 잔고", ev_of(uid_of(g1)) == "TRANSFER_IN" and ev_of(uid_of(g2)) == "TRANSFER_IN" and lsum(A) == ch.bal[A])

e_t = ch.tx(A, NOW - 200, in_msg={"src": X, "val": TON}, tf=700)
for kind in ("429", "500", "trunc", "badjson", "empty"):
    hw0 = st.d["ton"]["acct"][A]["hw"][0]
    srv.faults.append(("/transactions", kind)) if kind != "empty" else srv.faults.append(("/jetton/wallets", "500"))
    col.errors = 0
    col.discover("latest")
    if kind == "empty":
        check("E1 제톤 목록 500: Transient(오류 셈) · 주인 지갑 최신 tx 는 계속 발견", col.errors >= 1 and uid_of(e_t) in st.d["pending"],
              (kind, col.errors, st.d["ton"]["acct"][A]["hw"][0], hw0))
        continue
    check(f"E1 {kind}: Transient(오류 셈) · hw·대기 그대로", col.errors >= 1 and st.d["ton"]["acct"][A]["hw"][0] == hw0 and uid_of(e_t) not in st.d["pending"],
          (kind, col.errors, st.d["ton"]["acct"][A]["hw"][0], hw0))
    srv.faults.clear()
slow = srv.client(timeout=0.5)
srv.faults.append(("/transactions", "slow"))
rs = T.safe(slow.transactions, F.raw(A), sort="asc", limit=3)
check("E2 느린 응답(시간 초과) = Transient", isinstance(rs, dict) and "Transient" in rs.get("_exc", ""), rs)
srv.faults.clear()
SECRET = "k" * 20 + "SECRETKEY" + "z" * 20
kc = srv.client(key=SECRET)
srv.log.clear()
kc.transactions(F.raw(A), sort="desc", limit=1)
m0, p0, q0, h0 = srv.log[-1]
srv.faults.append(("/transactions", "500"))
ek = T.safe(kc.transactions, F.raw(A), sort="desc", limit=1)
check("E3 키 = X-API-Key 헤더만 · URL·쿼리·오류 문구에 없음", {k.lower(): v for k, v in h0.items()}.get("x-api-key") == SECRET and SECRET not in json.dumps(q0) and SECRET not in json.dumps(ek), (list(h0), ek))
srv.faults.clear()
check("E4 속도 간격: 무키 ≥1초(1rps) · 키 = 8rps(무료 10rps 의 80%)",
      tw.TonClient({}, key="").min_interval >= 1.0 and abs(tw.TonClient({}, key=SECRET).min_interval - 0.125) < 1e-9)
pace = os.path.join(T.TMP, "pace.lock")
p1c = tw.TonClient({}, key="", min_interval=0.3, pace_file=pace)
p2c = tw.TonClient({}, key="", min_interval=0.3, pace_file=pace)
t0 = time.time()
for cl in (p1c, p2c, p1c):
    cl._pace()
check("E5 공용 속도 조절(파일 잠금 · 다른 호출기·프로세스 합산) — 3번 = 0.6초 이상", time.time() - t0 >= 0.55, time.time() - t0)
col.cycle()
drain()

H = F.K("44")
for i in range(7):
    ch.tx(H, NOW - (200 if i == 0 else 20 - i) * DAY, in_msg={"src": X, "val": TON}, tf=500)
cfg = set_wallets(A, B, C9, H)
c.chain_owners["ton"] = {A, B, C9, H}
ad, st, col = mk({A, B, C9, H}, st)
col.cycle()
drain()
hrec = [x for x in inbox() if x["tx_uid"].startswith(H + ".")]
check("H1 쪽 넘김 끝까지(3·3·1) · 창 밖 1건은 안 보냄 · 첫 tx(prev 0) 도달 = 끝", len(hrec) == 6 and st.d["ton"]["acct"][H]["hist"] == "done"
      and st.d["ton"]["acct"][H].get("genesis"), (len(hrec), st.d["ton"]["acct"][H]))
sv = st.status_view().get(H) or {}
check("H2 상태 칸: requested_from · details_complete_through · coverage full · complete", sv.get("details_complete_through") and sv.get("coverage") == "full"
      and sv.get("complete"), sv)
G = F.K("45")
gt = [ch.tx(G, NOW - (30 - i) * DAY, in_msg={"src": X, "val": TON}, tf=500) for i in range(6)]
for t in gt[:2]:
    ch.hidden.add(t["_hex"])
cfg = set_wallets(A, B, C9, H, G)
c.chain_owners["ton"] = {A, B, C9, H, G}
ad, st, col = mk({A, B, C9, H, G}, st)
for _i in range(4):
    col.cycle()
ag = st.d["ton"]["acct"][G]
sv = st.status_view().get(G) or {}
check("H3 옛 쪽 비어 있음(첫 tx 전) = 3번 확인 뒤 partial · available_from = 받은 가장 옛 tx 시각 · '완료' 아님",
      ag.get("hist") == "partial" and ag.get("avail") == int(gt[2]["now"]) and sv.get("coverage") == "partial" and not sv.get("complete"), (ag, sv))
check("H4 동기화 도장은 그 사이 오류 주기엔 없음(Transient) · partial 뒤엔 다시 찍힘", st.d.get("synced_at"))
drain()
live = {(r["source_id"], r["leg_seq"], r["asset_id"], r["location"], r["qty_base"], r["leg_kind"], r["event"])
        for r in c.conn.execute("SELECT * FROM postings WHERE source_kind='chain_tx' AND source_ns='ton'")}
c.conn.execute("DELETE FROM postings WHERE source_kind='chain_tx' AND source_ns='ton'")
c.conn.execute("DELETE FROM positions")
c.conn.execute("DELETE FROM transfers")
c.conn.commit()
for r in c.conn.execute("SELECT chain, txhash, snapshot FROM raw_txs WHERE chain='ton' ORDER BY ingested_at, txhash").fetchall():
    c.conn.execute("BEGIN")
    c.apply(r["chain"], r["txhash"], "", json.loads(r["snapshot"]))
    c.conn.commit()
again = {(r["source_id"], r["leg_seq"], r["asset_id"], r["location"], r["qty_base"], r["leg_kind"], r["event"])
         for r in c.conn.execute("SELECT * FROM postings WHERE source_kind='chain_tx' AND source_ns='ton'")}
check("K1 재구축(원본 재생) = 라이브와 같은 레그 · 지갑 합 = 체인 잔고", again == live and lsum(A) == ch.bal[A] and lsum(A, "TKA") == ch.jbal[WA],
      (len(live), len(again), sorted(live ^ again)[:4]))
check("H5 poison 0(계약 위반·모순 재방출 없음)", not os.path.exists(os.path.join(paths.STATE_DIR, "poison.jsonl")),
      open(os.path.join(paths.STATE_DIR, "poison.jsonl")).read()[:600] if os.path.exists(os.path.join(paths.STATE_DIR, "poison.jsonl")) else "")
srv.stop()
reg.FORCE_AVAILABLE.clear()
T.finish()
