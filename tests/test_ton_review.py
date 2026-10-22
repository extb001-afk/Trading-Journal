#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
from _ingest import check  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

import config, paths  # noqa: E402
import core  # noqa: E402
import chain_event as ce  # noqa: E402
import chain_registry as reg  # noqa: E402
import chain_state as cs  # noqa: E402
import chain_watch as cw  # noqa: E402
import address_codec as ac  # noqa: E402
from inbox import SegmentWriter, SegmentReader  # noqa: E402
import ton_watch as tw  # noqa: E402
import _ton_fake as F  # noqa: E402

DAY = 86400
NOW = int(time.time())
TON = 10 ** 9
X = F.K("99")
CFG_PATH = os.path.join(T.TMP, "config.json")
INB = os.path.join(paths.INBOX_DIR, "ton")
reg.FORCE_AVAILABLE.add("ton")


def set_wallets(*keys):
    cfg = json.load(open(CFG_PATH))
    cfg["chain_wallets"] = [{"chain": "ton", "address": ac.ton_friendly(k)} for k in keys]
    json.dump(cfg, open(CFG_PATH, "w"))
    return config.load_config()


ch = F.Chain()
srv = F.Server(ch).start()
W = SegmentWriter(INB)


def mk(owners, sd=None, page=3):
    if sd:
        os.makedirs(sd, exist_ok=True)
    st = cs.ChainState("ton", sd)
    ad = tw.TonAdapter(config.load_config(), client=srv.client(), state=st)
    ad.page = page
    return ad, st, cw.Collector(ad, W, st, set(owners), page_budget={"latest": 10, "history": 20}, detail_budget={"latest": 200, "history": 500})


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
    c.conn.commit()


def lsum(owner, sym=None):
    q = ("SELECT SUM(CAST(p.qty_base AS INTEGER)) s FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.location=? AND a.chain='ton'"
         + (" AND a.kind='native'" if sym is None else " AND a.symbol=?"))
    r = c.conn.execute(q, (reg.make_location("ton", owner),) + (() if sym is None else (sym,))).fetchone()
    return int(r["s"] or 0)


def uid_of(t):
    return tw.tx_uid(tw.akey(t["account"]), t["lt"], t["_hex"])


def ev_of(uid):
    r = c.conn.execute("SELECT event FROM tx_class WHERE chain='ton' AND txhash=?", (uid,)).fetchone()
    return r["event"] if r else None


def emitted_uids():
    return [x["tx_uid"] for x in inbox()]


def due_now(st):
    for p in st.d["pending"].values():
        p["next"] = 0


A1, B1 = F.K("41"), F.K("42")
MJ, WA1, WB1 = F.K("e1"), F.K("c1"), F.K("c2")
ch.add_jetton(A1, WA1, MJ, symbol="JJ", decimals="6")
ch.add_jetton(B1, WB1, MJ, symbol="JJ", decimals="6")
ch.tx(A1, NOW - 9 * DAY, in_msg={"src": X, "val": 10 * TON}, tf=1000)
ch.tx(WA1, NOW - 9 * DAY, in_msg={"src": F.K("c9"), "val": 1, "op": tw.OP_INTERNAL_TRANSFER, "body": F.body_internal(50_000_000, X)}, tf=0)
p1 = ch.tx(A1, NOW - 5 * DAY, in_msg={"src": None}, outs=[{"dst": B1, "val": 3 * TON, "fwd": 400}], tf=3000)
p2 = ch.recv(p1, 0, B1, NOW - 5 * DAY + 5, tf=900)
j1 = ch.tx(WA1, NOW - 4 * DAY, in_msg={"src": A1, "val": 1, "op": tw.OP_JETTON_TRANSFER, "body": F.body_transfer(7_000_000, B1, resp=A1)}, tf=0,
           outs=[{"dst": WB1, "val": 1, "fwd": 0, "op": tw.OP_INTERNAL_TRANSFER, "body": F.body_internal(7_000_000, A1, resp=A1)}])
j2 = ch.recv(j1, 0, WB1, NOW - 4 * DAY + 5, tf=0)
ch.jbal[WA1], ch.jbal[WB1] = 43_000_000, 7_000_000
SD1 = os.path.join(T.TMP, "sd1")
set_wallets(B1)
c = core.Core(config.load_config())
c.conn.commit()
ad, st1, col = mk({B1}, SD1)
col.cycle()
drain()
before_b = (lsum(B1), lsum(B1, "JJ"))
set_wallets(A1, B1)
c.chain_owners["ton"] = {A1, B1}
ad, st1, col = mk({A1, B1}, SD1)
for _i in range(2):
    col.cycle()
    due_now(st1)
drain()
check("X1 받는 쪽 먼저 등록 → 보낸 지갑 추가 뒤 B 의 TON 이 두 번 안 더해짐(B 원장 = 체인 잔고)", lsum(B1) == ch.bal[B1] and lsum(A1) == ch.bal[A1],
      (lsum(B1), ch.bal[B1], lsum(A1), ch.bal[A1], before_b))
check("X1 제톤도 중복 없음(B 제톤 = 7 · A 제톤 = 43)", lsum(B1, "JJ") == 7_000_000 and lsum(A1, "JJ") == 43_000_000, (lsum(B1, "JJ"), lsum(A1, "JJ")))
check("X1 묶음 = 먼저 기장된 받은 쪽 uid 에 grow(TRANSFER_SELF) · 보낸 쪽 uid 새 행 없음",
      ev_of(uid_of(p2)) == "TRANSFER_SELF" and ev_of(uid_of(p1)) is None and ev_of(uid_of(j2)) == "TRANSFER_SELF" and ev_of(uid_of(j1)) is None,
      (ev_of(uid_of(p2)), ev_of(uid_of(p1)), ev_of(uid_of(j2)), ev_of(uid_of(j1))))

D1, WD, MD = F.K("43"), F.K("c3"), F.K("e3")
ch.add_jetton(D1, WD, MD, symbol=None, decimals=None, onchain=False)
dt = ch.tx(WD, NOW - 3 * DAY, in_msg={"src": F.K("c9"), "val": 1, "op": tw.OP_INTERNAL_TRANSFER, "body": F.body_internal(5_000_000, X)}, tf=0)
ch.tx(D1, NOW - 3 * DAY, in_msg={"src": X, "val": TON}, tf=1000)
ch.jbal[WD] = 5_000_000
set_wallets(A1, B1, D1)
c.chain_owners["ton"] = {A1, B1, D1}
tw.META_RETRY_SEC = 0
ad, st2, col = mk({D1})
col.cycle()
drain()
dec_row = c.conn.execute("SELECT decimals FROM assets WHERE chain='ton' AND address=?", (MD,)).fetchone()
check("X2 자릿수 모르는 제톤 = 기장 보류(원장에 자산·수량 없음 · 18 로 안 씀)", uid_of(dt) not in emitted_uids() and dec_row is None,
      (uid_of(dt) in emitted_uids(), dict(dec_row) if dec_row else None))
bal2 = tw.TonAdapter(config.load_config(), client=srv.client()).fetch_balances({D1}, None)
check("X2 대사: 자릿수 모르는 제톤 잔고 = 관측 못 함 + 보류", not bal2["_complete"] and MD in (bal2["_unobserved"].get(D1) or []), (bal2.get("_why"), bal2["_unobserved"]))
ch.masters[MD] = ({"decimals": "6"}, {"valid": True, "type": "jetton_masters", "symbol": "DD", "extra": {}})
due_now(st2)
col.cycle()
drain()
dec_row = c.conn.execute("SELECT decimals FROM assets WHERE chain='ton' AND address=?", (MD,)).fetchone()
check("X2 메타가 나중에 확인되면 다시 조회 → 자릿수 6 으로 기장", dec_row is not None and dec_row["decimals"] == 6 and lsum(D1, "DD") == 5_000_000,
      (dict(dec_row) if dec_row else None, lsum(D1, "DD")))
E2, WE2, ME2 = F.K("44"), F.K("c4"), F.K("e4")
ch.add_jetton(E2, WE2, ME2, symbol="EE", decimals="6")
et = ch.tx(WE2, NOW - 2 * DAY, in_msg={"src": F.K("c9"), "val": 1, "op": tw.OP_INTERNAL_TRANSFER, "body": F.body_internal(2_000_000, X)}, tf=0)
ch.jbal[WE2] = 2_000_000
set_wallets(A1, B1, D1, E2)
c.chain_owners["ton"] = {A1, B1, D1, E2}
ad, st2, col = mk({D1, E2})
srv.faults.append(("/jetton/masters", "500"))
col.cycle()
srv.faults.clear()
due_now(st2)
col.cycle()
due_now(st2)
col.cycle()
drain()
re2 = [x for x in inbox() if x["tx_uid"] == uid_of(et)]
check("X2 검증 직후 메타 조회 실패 → 다음 차례 다시 조회 → 심볼·자릿수 확인 뒤 기장",
      re2 and re2[-1]["deltas"][0]["asset"]["decimals"] == 6 and re2[-1]["deltas"][0]["asset"]["symbol"] == "EE" and lsum(E2, "EE") == 2_000_000,
      re2[-1]["deltas"] if re2 else None)

rb = tw.TonAdapter(config.load_config(), client=srv.client())
ok3 = rb.fetch_balances({E2}, None)
ch.jw_patch[WE2] = {"balance": None}
b3 = rb.fetch_balances({E2}, None)
check("X3 제톤 잔고 null = 0 아님(보류 · 그 칸 없음)", ok3["_complete"] and not b3["_complete"] and ("token", ME2) not in b3["per_wallet"][E2],
      (ok3.get("_why"), b3.get("_why"), b3["per_wallet"]))
ch.jw_patch.clear()
ch.states[E2] = 0
ch.acct_patch[E2] = {"balance": None, "status": "uninit"}
e3 = T.safe(rb.fetch_balances, {E2}, None)
check("X3 네이티브 잔고 null(uninit) = 0 아님(예외)", isinstance(e3, dict) and "Transient" in e3.get("_exc", ""), e3 if isinstance(e3, dict) and "_exc" in e3 else "0 으로 통과")
ch.acct_patch[E2] = {"last_transaction_lt": None}
e3b = T.safe(rb.fetch_balances, {E2}, None)
check("X3 last_transaction_lt 빠짐 = 0 아님(예외 또는 보류)", (isinstance(e3b, dict) and "_exc" in e3b) or not e3b.get("_complete"), e3b.get("_why") if "_exc" not in e3b else e3b)
ch.acct_patch.clear()
ch.states.pop(E2, None)

F1, WF1, WF2, MF1, MF2 = F.K("46"), F.K("c6"), F.K("c7"), F.K("e6"), F.K("e7")
ch.add_jetton(F1, WF1, MF1, symbol="F1T", decimals="6")
ch.add_jetton(F1, WF2, MF2, symbol="F2T", decimals="6")
ch.tx(F1, NOW - DAY, in_msg={"src": X, "val": TON}, tf=1000)
ch.tx(WF1, NOW - DAY, in_msg={"src": F.K("c9"), "val": 1, "op": tw.OP_INTERNAL_TRANSFER, "body": F.body_internal(1, X)}, tf=0)
ch.tx(WF2, NOW - DAY, in_msg={"src": F.K("c9"), "val": 1, "op": tw.OP_INTERNAL_TRANSFER, "body": F.body_internal(1, X)}, tf=0)
ad, st4, col = mk({F1}, os.path.join(T.TMP, "sd4"))
col.cycle()
h1 = ch.tx(WF1, NOW - 600, in_msg={"src": F.K("c9"), "val": 1, "op": tw.OP_INTERNAL_TRANSFER, "body": F.body_internal(2, X)}, tf=0)
ch.tx(WF1, NOW - 590, in_msg={"src": F.K("c9"), "val": 1, "op": tw.OP_INTERNAL_TRANSFER, "body": F.body_internal(3, X)}, tf=0)
ch.hidden.add(h1["_hex"])
nf1 = ch.tx(F1, NOW - 500, in_msg={"src": X, "val": TON}, tf=1000)
nf2 = ch.tx(WF2, NOW - 500, in_msg={"src": F.K("c9"), "val": 1, "op": tw.OP_INTERNAL_TRANSFER, "body": F.body_internal(4, X)}, tf=0)
col.cycle()
nf1b = ch.tx(F1, NOW - 400, in_msg={"src": X, "val": TON}, tf=1000)
col.errors = 0
col.cycle()
col.cycle()
pend4 = set(st4.d["pending"]) | set(st4.em["uids"])
check("X4 실패하는 제톤 계정이 있어도 주인 지갑 새 tx 는 다음 주기에 계속 발견", uid_of(nf1b) in pend4 and uid_of(nf1) in pend4, sorted(pend4)[-4:])
check("X4 실패 계정 뒤의 다른 제톤 계정도 계속 수집", uid_of(nf2) in pend4)
check("X4 실패는 오류로 셈(동기화 도장 없음)", col.errors > 0)
ch.hidden.discard(h1["_hex"])

G1 = F.K("47")
gts = [ch.tx(G1, NOW - (10 - i) * DAY, in_msg={"src": X, "val": TON}, tf=1000) for i in range(4)]
ch.tx_patch[gts[1]["_hex"]] = {"prev_trans_lt": "__del__"}
ad, st5, col = mk({G1}, os.path.join(T.TMP, "sd5"))
col.cycle()
a5 = st5.d["ton"]["acct"].get(G1) or {}
check("X5 prev_trans_lt 빠진 행 = 첫 tx 로 오인 안 함(genesis·done 아님)", not a5.get("genesis") and a5.get("hist") != "done", a5)
ch.tx_patch.clear()
for _i in range(2):
    col.cycle()
check("X5 회복 뒤 옛 tx 까지 4건 모두", all(uid_of(t) in set(st5.em["uids"]) for t in gts), [uid_of(t) in set(st5.em["uids"]) for t in gts])
g5 = ch.tx(G1, NOW - 300, in_msg={"src": X, "val": TON}, tf=1000)
ch.tx_patch[g5["_hex"]] = {"description": {"aborted": "__del__"}}
col.cycle()
check("X5 aborted 칸 빠짐 = 성공으로 오인 안 함(방출 안 함)", uid_of(g5) not in set(st5.em["uids"]) and uid_of(g5) not in st5.d["pending"])
ch.tx_patch.clear()

H1, WH, MH = F.K("48"), F.K("c8"), F.K("e8")
ch.add_jetton(H1, WH, MH, symbol="HH", decimals="6")
ch.tx(H1, NOW - DAY, in_msg={"src": X, "val": TON}, tf=1000)
ad, st6, col = mk({H1}, os.path.join(T.TMP, "sd6"))
col.cycle()
ht = ch.tx(WH, NOW - 200, in_msg={"src": F.K("c9"), "val": 1, "op": tw.OP_INTERNAL_TRANSFER, "body": F.body_internal(9_000_000, X)}, tf=0)
ch.tx_patch[ht["_hex"]] = {"in_msg": None}
hw0 = (st6.d["ton"]["acct"].get(WH) or {}).get("hw")
col.cycle()
check("X6 in_msg null(ord tx) = 0 확정 안 함 · hw 그대로", uid_of(ht) not in set(st6.em["uids"]) and uid_of(ht) not in st6.d["pending"]
      and (st6.d["ton"]["acct"].get(WH) or {}).get("hw") == hw0, ((st6.d["ton"]["acct"].get(WH) or {}).get("hw"), hw0))
ch.tx_patch[ht["_hex"]] = {"in_msg": {"message_content": {}}}
col.cycle()
check("X6 제톤 op 인데 본문 없음 = 대기열에 불완전 저장 안 함", uid_of(ht) not in st6.d["pending"] and uid_of(ht) not in set(st6.em["uids"]))
ch.tx_patch.clear()
col.cycle()
rec6 = [x for x in inbox() if x["tx_uid"] == uid_of(ht)]
check("X6 회복 뒤 정상 기장(+9)", rec6 and rec6[-1]["deltas"] and rec6[-1]["deltas"][0]["delta_base"] == "9000000", rec6[-1]["deltas"] if rec6 else None)

I1, WI, MI = F.K("49"), F.K("ca"), F.K("ea")
ch.add_jetton(I1, WI, MI, symbol="II", decimals="6")
ch.tx(I1, NOW - DAY, in_msg={"src": X, "val": TON}, tf=1000)
ad, st7, col = mk({I1}, os.path.join(T.TMP, "sd7"))
srv.faults.append(("/runGetMethod", "errstack"))
col.cycle()
v7 = st7.d["ton"]["jw"].get(WI)
check("X7 runGetMethod error+stack = 가짜 지갑으로 캐시 안 함", v7 is None or v7.get("ok") is not False, v7)
col.cycle()
check("X7 다음 차례 검증 성공", (st7.d["ton"]["jw"].get(WI) or {}).get("ok") is True, st7.d["ton"]["jw"].get(WI))
srv.faults.append(("/transactions", "errlist"))
r7 = T.safe(srv.client().transactions, F.raw(I1), sort="desc", limit=3)
check("X7 error + 빈 거래 목록 = Transient(거래 없음 아님)", isinstance(r7, dict) and "Transient" in r7.get("_exc", ""), r7)
srv.faults.clear()

K1, WK, MK = F.K("4b"), F.K("cb"), F.K("eb")
ch.add_jetton(K1, WK, MK, symbol="KK", decimals="6")
ch.tx(K1, NOW - DAY, in_msg={"src": X, "val": 5 * TON}, tf=1000)
k8 = ch.tx(K1, NOW - 100, in_msg={"src": None}, outs=[{"dst": X, "val": TON, "fwd": 400, "op": tw.OP_JETTON_TRANSFER}], tf=3000)
ad, st8, col = mk({K1}, os.path.join(T.TMP, "sd8"))
col.cycle()
r8 = [x for x in inbox() if x["tx_uid"] == uid_of(k8)]
e8 = ce.to_core(r8[-1]) if r8 else {}
check("X8 남(검증 안 됨)에게 opcode 붙여 보낸 1 TON = 보낸 내역(경제 −1 TON · 상대 X) · 수수료 아님",
      r8 and e8["econ"].get((K1, ("native", None))) == -TON and X in e8["cps"] and int(r8[-1]["fees"][0]["amount_base"]) == 3400,
      (e8.get("econ"), r8[-1]["fees"] if r8 else None))
K2, WK2, MK2 = F.K("4c"), F.K("cc"), F.K("ec")
ch.add_jetton(K2, WK2, MK2, symbol="K2", decimals="6")
ch.tx(K2, NOW - DAY, in_msg={"src": X, "val": 5 * TON}, tf=1000)
k9 = ch.tx(K2, NOW - 90, in_msg={"src": None}, outs=[{"dst": WK2, "val": 50_000_000, "fwd": 400, "op": tw.OP_JETTON_TRANSFER}], tf=3000)
old_budget = tw.JW_VERIFY_PER_PASS
tw.JW_VERIFY_PER_PASS = 0
ad, st9, col = mk({K2}, os.path.join(T.TMP, "sd9"))
col.cycle()
held = uid_of(k9) not in set(st9.em["uids"])
tw.JW_VERIFY_PER_PASS = old_budget
due_now(st9)
col.cycle()
r9 = [x for x in inbox() if x["tx_uid"] == uid_of(k9)]
check("X8 목록에 있는데 아직 검증 전인 내 제톤 지갑으로 보낸 TON = 검증까지 대기 → 검증 뒤 수수료(NOOP 모양)",
      held and r9 and not ce.to_core(r9[-1])["econ"], (held, ce.to_core(r9[-1])["econ"] if r9 else None))

check("X9 설정 min_interval_sec 0 = 무키 1rps 간격 유지", tw.TonClient({"min_interval_sec": 0}, key="").min_interval >= 1.0)
check("X9 키 있어도 0.01 = 8rps(0.125초) 아래로 안 감", tw.TonClient({"min_interval_sec": 0.01}, key="k" * 30).min_interval >= 0.125)
check("X9 더 느리게는 허용(2초)", tw.TonClient({"min_interval_sec": 2}, key="").min_interval == 2.0)
SD11 = os.path.join(T.TMP, "sd11")
os.makedirs(SD11, exist_ok=True)
st11 = cs.ChainState("ton", SD11)
ad11 = tw.TonAdapter(config.load_config(), client=srv.client(), state=st11)


def P11(b, lt):
    k = F.K(b)
    return ({"a": k, "lt": str(lt), "h": "%064x" % lt}, "wallet", k, None)


def u11(p):
    return tw.tx_uid(p[0]["a"], p[0]["lt"], p[0]["h"])


r11, b11, c11 = P11("51", 1), P11("52", 2), P11("53", 3)
check("X11 방출된 줄 없음 = 그대로", ad11._rebase([r11, b11, c11], None)[0] == [r11, b11, c11])
st11.mark_emitted("s1", u11(b11), [b11[2]])
pp, ee = ad11._rebase([r11, b11, c11], {0: "E0"})
check("X11 받는 줄 하나만 먼저 나감 = 그 줄이 뿌리(grow) · 나머지 그대로 · effects 번호 따라감", pp == [b11, r11, c11] and ee == {1: "E0"}, (pp, ee))
st11.mark_emitted("s2", u11(c11), [c11[2]])
check("X11 받는 줄 둘이 각자 나감 = 첫 줄이 뿌리 · 다른 방출 줄은 뺌(이중 기장 없음)", ad11._rebase([r11, b11, c11], None)[0] == [b11, r11])
st11.mark_emitted("s3", u11(r11), [r11[2]])
check("X11 뿌리도 이미 나감 = 뿌리 그대로 · 방출된 받는 줄은 뺌", ad11._rebase([r11, b11, c11], None)[0] == [r11])
check("X10 poison 0", not os.path.exists(os.path.join(paths.STATE_DIR, "poison.jsonl")))
srv.stop()
reg.FORCE_AVAILABLE.clear()
T.finish()
