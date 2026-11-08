#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402
from _ingest import SOLW, Writer  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
from decimal import Decimal  # noqa: E402

import balcheck  # noqa: E402
import config  # noqa: E402
import core  # noqa: E402
import sol_base  # noqa: E402
import sol_stake  # noqa: E402
import sol_watch  # noqa: E402

chk = T.chk

W2 = "So2" + "2" * 41
NEW = "Nw3" + "3" * 41
OTH = "Ot6" + "6" * 41
EXT = "Ex7" + "7" * 41
SVC = "Sv5" + "5" * 41
SYS = "1" * 32
STAKE_P = sol_base.STAKE_PROGRAM
X = 150 * 10 ** 9
Y = 149_800_000_000
FEE = 5000
BT0 = 1_790_000_000


def stk(tag):
    return "Sk" + str(tag) + "z" + "4" * (41 - len(str(tag)))


cfg9 = json.loads(json.dumps(_ingest.CFG))
cfg9["wallets"].append({"type": "sol", "address": W2})
json.dump(cfg9, open(os.path.join(T.TMP, "config.json"), "w"))


def ix_auth(s, a, n, kind="Withdrawer", typ="authorize"):
    return {"program": "stake", "programId": STAKE_P, "parsed": {"type": typ, "info": {
        "stakeAccount": s, "authority": a, "newAuthority": n, "authorityType": kind}}}


def ix_withdraw(s, a, dest, lam):
    return {"program": "stake", "programId": STAKE_P, "parsed": {"type": "withdraw", "info": {
        "stakeAccount": s, "withdrawAuthority": a, "destination": dest, "lamports": lam}}}


def ix_xfer(src, dst, lam):
    return {"program": "system", "programId": SYS, "parsed": {"type": "transfer", "info": {"source": src, "destination": dst, "lamports": lam}}}


def mk_tx(slot, bal, outer, inner=(), err=None, fee=FEE):
    keys = [{"pubkey": k, "signer": i == 0, "writable": True} for i, (k, _a, _b) in enumerate(bal)]
    keys += [{"pubkey": STAKE_P, "signer": False, "writable": False}]
    return {"slot": slot, "blockTime": BT0 + slot, "meta": {
        "err": err, "fee": fee, "preBalances": [a for _k, a, _b in bal] + [1], "postBalances": [b for _k, _a, b in bal] + [1],
        "innerInstructions": [{"index": 0, "instructions": list(inner)}] if inner else [], "preTokenBalances": [], "postTokenBalances": []},
        "transaction": {"message": {"accountKeys": keys, "instructions": list(outer)}}}


def svc_outer():
    return {"programId": SVC, "accounts": [SOLW], "data": "x"}


w = sol_watch.SolWatcher.__new__(sol_watch.SolWatcher)
w.owners = [SOLW, W2]
w.stake_on = True
w.cursor = {}
w.cursor_path = os.path.join(T.TMP, "state", "cursor_sol.json")
w.ata_owner = {}
w.writer = Writer()
w.emitted = set()
w.cutoff_ts = 0
for i9 in range(1, 17):
    w.cursor["_stk:" + stk(i9)] = {"w": SOLW, "t0": 0, "rwd_next": None, "first": None, "open": True}
TXS = {}


def parse(sig, tx):
    TXS[sig] = tx
    return w._parse_result(sig, tx)


def dl(rec):
    return sorted((d["owner"], int(d["delta"])) for d in rec.get("deltas") or [])


def stake_tx(s, slot, pay=Y, kind="Withdrawer", to=NEW, err=None):
    inner = [ix_auth(s, SOLW, to, "Staker"), ix_auth(s, SOLW, to, kind)] + ([ix_xfer(to, SOLW, pay)] if pay else [])
    bal = [(SOLW, 2 * 10 ** 9, 2 * 10 ** 9 + pay - FEE), (to, 10 ** 15, 10 ** 15 - pay), (s, X, X)]
    return mk_tx(slot, bal, [svc_outer()], inner, err=err)


print("— A 파서")
rA1 = parse("sigA1", stake_tx(stk(1), 1001))
chk(dl(rA1) == sorted([(SOLW, Y), (f"{SOLW}:stake:{stk(1)}", -X)]), "A1 넘김 + 대가 = 스테이크 칸 −잔고 · 지갑 +대가", dl(rA1))
chk(rA1.get("stake_auth") == {stk(1): {"from": SOLW, "to": NEW, "mine": False, "lamports": X}} and NEW in rA1["counterparties"],
    "A1 stake_auth(남) · 새 출금권자 = 상대", [rA1.get("stake_auth"), rA1.get("counterparties")])
rA2 = parse("sigA2", stake_tx(stk(2), 1002, pay=0))
chk(dl(rA2) == [(f"{SOLW}:stake:{stk(2)}", -X)] and (rA2.get("stake_auth") or {}).get(stk(2), {}).get("mine") is False,
    "A2 대가 없음 = 스테이크 칸 −잔고 1줄", dl(rA2))
rA3 = parse("sigA3", mk_tx(1003, [(SOLW, 2 * 10 ** 9, 2 * 10 ** 9 - FEE), (stk(3), X, X)], [ix_auth(stk(3), SOLW, W2)]))
chk(dl(rA3) == sorted([(f"{SOLW}:stake:{stk(3)}", -X), (f"{W2}:stake:{stk(3)}", X)]) and rA3["stake_auth"][stk(3)]["mine"] is True,
    "A3 내 다른 지갑 = 넘긴 칸 − · 받은 칸 +", dl(rA3))
rA4 = parse("sigA4", mk_tx(1004, [(SOLW, 2 * 10 ** 9, 2 * 10 ** 9 - FEE), (stk(4), X, X)], [ix_auth(stk(4), SOLW, NEW, "Staker")]))
chk(dl(rA4) == [] and not rA4.get("stake_auth"), "A4 Staker 만 = 기장 없음", dl(rA4))
rA5 = parse("sigA5", stake_tx(stk(4), 1005, err={"InstructionError": [0, "Custom"]}))
chk(not rA5.get("stake_auth") and all(":stake:" not in o for o, _v in dl(rA5)), "A5 실패 tx = 권한 넘김 없음", dl(rA5))
MINE = {SOLW, W2}
d6, a6 = sol_stake.stake_auth_moves([ix_auth(stk(4), NEW, OTH)], [], [stk(4)], [X], MINE, {stk(4): SOLW})
d6b, a6b = sol_stake.stake_auth_moves([ix_auth(stk(99), SOLW, NEW)], [], [stk(99)], [X], MINE, {stk(4): SOLW})
chk(not d6 and not a6 and not d6b and not a6b, "A6 권한자 남 · 모르는 계정 = 없음", [d6, a6, d6b, a6b])
d7, a7 = sol_stake.stake_auth_moves([ix_auth(stk(4), SOLW, W2), ix_auth(stk(4), W2, NEW)], [], [stk(4)], [X], MINE, {stk(4): SOLW})
chk(a7 == {stk(4): {"from": SOLW, "to": NEW, "mine": False, "lamports": X}} and len(d7) == 1, "A7 한 tx 연쇄 A→B→C = A 에서 C 로", [d7, a7])
d7b, a7b = sol_stake.stake_auth_moves([svc_outer(), ix_auth(stk(4), W2, NEW)], [{"index": 0, "instructions": [ix_auth(stk(4), SOLW, W2)]}],
                                      [stk(4)], [X], MINE, {stk(4): SOLW})
chk(a7b == a7 and len(d7b) == 1, "A7 실행 순서 = 바깥 명령 i 다음 그 안쪽 명령(안쪽 A→B 뒤 바깥 B→C)", [d7b, a7b])
sol_stake.stake_emit_prep(w, rA1)
sol_stake.stake_emit_prep(w, rA3)
e1, e3 = w.cursor["_stk:" + stk(1)], w.cursor["_stk:" + stk(3)]
chk(e1.get("away") == 1001 and e1.get("away_sig") == "sigA1" and e3["w"] == W2 and "away" not in e3,
    "A3·A8 방출 반영 = 남 → away 슬롯·서명 · 내 지갑 → 등록 지갑 바뀜", [e1, e3])
chk(e3.get("w0") == SOLW and sol_stake.stake_open_w(e3) == SOLW and sol_stake.stake_open_w(e1) == SOLW,
    "A3 창 시작 기초잔고 칸 = 처음 출금권자(w0 — 받은 지갑에 두 번 안 놓음)", e3)
chk(sol_stake.stake_live(e1, 1000) and sol_stake.stake_live(e1, 1001, "sigA1") and not sol_stake.stake_live(e1, 1001, "sigX")
    and not sol_stake.stake_live(e1, 1002) and sol_stake.stake_live(e1, None) and sol_stake.stake_live(e1, 1001),
    "A8 stake_live 경계 — 앞 슬롯 셈 · 같은 슬롯은 넘긴 tx 만 · 뒤 슬롯(보상 effectiveSlot 포함) 뺌 · 슬롯 모름 셈")
wd1 = mk_tx(2001, [(NEW, 10 ** 15, 10 ** 15 + X - FEE), (stk(1), X, 0)], [ix_withdraw(stk(1), NEW, NEW, X)])
rA8 = parse("sigA8", wd1)
chk(dl(rA8) == [] and stk(1) not in (rA8.get("stake_pre") or {}), "A8 넘긴 뒤 상대 인출 = 그 계정 레그 없음", [dl(rA8), rA8.get("stake_pre")])
rA8b = parse("sigA1", TXS["sigA1"])
chk(dl(rA8b) == dl(rA1), "A8 넘긴 tx 자체 다시 읽기(같은 슬롯) = 그대로", dl(rA8b))
rA8c = parse("sigA8c", mk_tx(1001, [(NEW, 10 ** 15, 10 ** 15 + X - FEE), (stk(1), X, 0)], [ix_withdraw(stk(1), NEW, NEW, X)]))
chk(dl(rA8c) == [], "A8 같은 슬롯의 다른 tx(상대 인출) = 그 계정 레그 없음", dl(rA8c))
rA9 = parse("sigA9", stake_tx(stk(10), 3001))
rA9w = parse("sigA9w", mk_tx(3002, [(NEW, 10 ** 15, 10 ** 15 + X - FEE), (stk(10), X, 0)], [ix_withdraw(stk(10), NEW, NEW, X)]))
had9 = (f"{SOLW}:stake:{stk(10)}", -X) in dl(rA9w)
sol_stake.stake_emit_prep(w, rA9)
sol_stake.stake_emit_prep(w, rA9w)
chk(had9 and dl(rA9w) == [] and stk(10) not in (rA9w.get("stake_pre") or {}) and dl(rA9) == sorted([(SOLW, Y), (f"{SOLW}:stake:{stk(10)}", -X)]),
    "A9 같은 묶음 선파싱 — 넘김 tx 방출 표식 뒤 상대 인출 레그 뺌(넘김 tx 자체 그대로)", [had9, dl(rA9w), dl(rA9)])
NS = "Ns8" + "8" * 41
Z = 40 * 10 ** 9
ix_split = {"program": "stake", "programId": STAKE_P, "parsed": {"type": "split", "info": {
    "stakeAccount": stk(11), "newSplitAccount": NS, "stakeAuthority": SOLW, "lamports": Z}}}
rA10 = parse("sigA10", mk_tx(4001, [(SOLW, 2 * 10 ** 9, 2 * 10 ** 9 + Y - FEE), (NEW, 10 ** 15, 10 ** 15 - Y), (stk(11), X, X - Z), (NS, 0, Z)],
                             [ix_split, ix_auth(NS, SOLW, NEW, "Staker"), ix_auth(NS, SOLW, NEW), ix_xfer(NEW, SOLW, Y)]))
sol_stake.stake_emit_prep(w, rA10)
eNS = w.cursor.get("_stk:" + NS) or {}
rA10w = parse("sigA10w", mk_tx(4002, [(NEW, 10 ** 15, 10 ** 15 + Z - FEE), (NS, Z, 0)], [ix_withdraw(NS, NEW, NEW, Z)]))
chk(sorted(dl(rA10)) == sorted([(SOLW, Y), (f"{SOLW}:stake:{stk(11)}", -Z), (f"{SOLW}:stake:{NS}", Z), (f"{SOLW}:stake:{NS}", -Z)])
    and eNS.get("away") == 4001 and dl(rA10w) == [],
    "A10 분할 새 계정을 같은 tx 에서 남에게 = 새 계정 칸 +분할 −넘김 · 등록 뒤 넘김 표식 · 상대 인출 레그 없음", [dl(rA10), eNS, dl(rA10w)])
rA11 = parse("sigA11", mk_tx(5001, [(SOLW, 2 * 10 ** 9, 2 * 10 ** 9 - FEE), (stk(12), X, X)], [ix_auth(stk(12), SOLW, W2)]))
rA11w = parse("sigA11w", mk_tx(5002, [(W2, 10 ** 9, 10 ** 9 + X - FEE), (stk(12), X, 0)], [ix_withdraw(stk(12), W2, W2, X)]))
stale11 = (f"{SOLW}:stake:{stk(12)}", -X) in dl(rA11w)
sol_stake.stake_emit_prep(w, rA11)
sol_stake.stake_emit_prep(w, rA11w)
chk(stale11 and dl(rA11w) == sorted([(W2, X), (f"{W2}:stake:{stk(12)}", -X)]),
    "A11 내 지갑끼리 넘긴 뒤 같은 묶음 인출 = 옛 칸 이름 → 받은 지갑 칸", [stale11, dl(rA11w)])
rA12a = parse("sigA12a", stake_tx(stk(13), 6001))
sol_stake.stake_emit_prep(w, rA12a)
rA12o = parse("sigA12o", mk_tx(5500, [(W2, 2 * 10 ** 9, 2 * 10 ** 9 - FEE), (stk(13), X, X)], [ix_auth(stk(13), W2, SOLW)]))
sol_stake.stake_emit_prep(w, rA12o)
e13 = w.cursor["_stk:" + stk(13)]
chk(e13.get("away") == 6001 and e13["w"] == SOLW and e13.get("w0") == W2, "A12 옛 구간 재생 = 최근 넘김 표식 그대로 · 처음 출금권자만 앞당김", e13)
rA13 = parse("sigA13", mk_tx(7001, [(SOLW, 2 * 10 ** 9, 2 * 10 ** 9 - FEE), (stk(15), X, X)], [ix_auth(stk(15), SOLW, W2)]))
sol_stake.stake_emit_prep(w, rA13)
rA13b = parse("sigA13b", mk_tx(7002, [(W2, 2 * 10 ** 9, 2 * 10 ** 9 - FEE), (stk(15), X, X)], [ix_auth(stk(15), W2, SOLW)]))
sol_stake.stake_emit_prep(w, rA13b)
chk(dl(rA13b) == sorted([(f"{W2}:stake:{stk(15)}", -X), (f"{SOLW}:stake:{stk(15)}", X)]) and w.cursor["_stk:" + stk(15)]["w"] == SOLW,
    "A13 내 지갑끼리 연달아 넘김 = 둘째 tx 레그 그대로 · 등록 지갑 되돌아옴", [dl(rA13b), w.cursor["_stk:" + stk(15)]])
rA14 = parse("sigA14", mk_tx(8001, [(SOLW, 2 * 10 ** 9, 2 * 10 ** 9 - FEE), (stk(16), X, X)], [ix_auth(stk(16), SOLW, W2)]))
rA14b = parse("sigA14b", mk_tx(8002, [(W2, 10 ** 9, 10 ** 9 + Z - FEE), (stk(16), X, X - Z)],
                               [ix_withdraw(stk(16), W2, W2, Z), ix_auth(stk(16), W2, NEW)]))
sol_stake.stake_emit_prep(w, rA14)
sol_stake.stake_emit_prep(w, rA14b)
s16 = {}
for o, v in dl(rA14) + dl(rA14b):
    if ":stake:" in o:
        s16[o.split(":stake:")[0]] = s16.get(o.split(":stake:")[0], 0) + v
chk(dl(rA14b) == sorted([(W2, Z), (f"{W2}:stake:{stk(16)}", -Z), (f"{W2}:stake:{stk(16)}", -(X - Z))]) and s16 == {SOLW: -X, W2: 0},
    "A14 같은 묶음 내 지갑끼리 넘김 뒤 일부 인출+남에게 넘김 = 실제 인출 레그도 그때 출금권자 칸(옛 칸 −X · 받은 칸 +X−Z−(X−Z) = 0)", [dl(rA14b), s16])

print("— B core 기장")
c = core.Core(config.load_config())


def consume(rec):
    c.conn.execute("BEGIN")
    c._consume_record(json.loads(json.dumps(rec)))
    c.conn.commit()


def legs(sig):
    return sorted((r["location"], r["leg_kind"], int(r["qty_base"])) for r in c.conn.execute(
        "SELECT location, leg_kind, qty_base FROM postings WHERE source_kind='chain_tx' AND source_ns='sol' AND source_id=?", (sig,)).fetchall())


def ev(sig):
    r = c.conn.execute("SELECT event FROM tx_class WHERE chain='sol' AND txhash=?", (sig,)).fetchone()
    return r["event"] if r else None


def loc_sum(loc):
    r = c.conn.execute("SELECT SUM(CAST(qty_base AS INTEGER)) FROM postings WHERE location=?", (loc,)).fetchone()
    return int(r[0] or 0)


def pos(loc):
    r = c.conn.execute("SELECT qty_norm FROM positions WHERE location=?", (loc,)).fetchone()
    return Decimal(r[0]) if r else Decimal(0)


def sol_rec(sig, slot, deltas, cps=(), has_program=True):
    return {"v": 1, "kind": "sol_tx", "chain": "sol", "txhash": sig, "slot": slot, "ts": BT0 + slot, "fee_lamports": 0,
            "fee_payer_mine": False, "fee_payer": None, "wallets": [SOLW, W2], "counterparties": list(cps), "has_program": has_program,
            "err": False, "deltas": [{"asset": "native", "symbol": "SOL", "decimals": 9, "delta": str(v), "owner": o} for o, v in deltas]}


def wsum():
    r = c.conn.execute("SELECT SUM(CAST(qty_base AS INTEGER)) FROM postings WHERE location LIKE 'wallet:sol:%'").fetchone()
    return int(r[0] or 0)


consume(sol_rec("base1", 10, [(SOLW, 20 * X)], cps=[EXT], has_program=False))
for i9 in (1, 2, 3, 4, 5, 6, 7):
    consume(sol_rec(f"dep{i9}", 20 + i9, [(SOLW, -X), (f"{SOLW}:stake:{stk(i9)}", X)]))
chk(all(loc_sum(f"wallet:sol:{SOLW}:stake:{stk(i9)}") == X for i9 in range(1, 8)) and ev("dep1") == "TRANSFER_SELF", "B0 위임 7개 = 스테이크 칸 X")
s0 = wsum()
consume(rA1)
L1 = legs("sigA1")
chk(ev("sigA1") == "TRANSFER_OUT" and loc_sum(f"wallet:sol:{SOLW}:stake:{stk(1)}") == 0 and pos(f"wallet:sol:{SOLW}:stake:{stk(1)}") == 0,
    "B1 넘김 + 대가 = TRANSFER_OUT · 스테이크 칸 0", [ev("sigA1"), L1])
chk(sorted(L1) == sorted([(f"wallet:sol:{SOLW}:stake:{stk(1)}", "move_out", -X), (f"wallet:sol:{SOLW}", "move_in", Y),
                          (f"out:sol:{NEW}", "move_in", X - Y), (f"wallet:sol:{SOLW}", "gas", -FEE)]),
    "B1 레그 = 칸 이동(새 취득 없음) · 모자란 몫 보낸 내역 out:sol:<새 출금권자> · 가스", L1)
chk(wsum() - s0 == -(X - Y) - FEE, "B1 내 SOL 합 = 언스테이크 몫·가스만 줄어듦(이중 계상 없음)", wsum() - s0)
consume(rA2)
chk(ev("sigA2") == "TRANSFER_OUT" and loc_sum(f"wallet:sol:{SOLW}:stake:{stk(2)}") == 0 and (f"out:sol:{NEW}", "move_in", X) in legs("sigA2"),
    "B2 대가 없음 = TRANSFER_OUT · 전부 보낸 내역", legs("sigA2"))
consume(rA3)
chk(ev("sigA3") == "TRANSFER_SELF" and loc_sum(f"wallet:sol:{SOLW}:stake:{stk(3)}") == 0 and loc_sum(f"wallet:sol:{W2}:stake:{stk(3)}") == X,
    "B3 내 다른 지갑 = TRANSFER_SELF · 칸만 바뀜", legs("sigA3"))
consume(rA4)
chk(loc_sum(f"wallet:sol:{SOLW}:stake:{stk(4)}") == X and legs("sigA4") == [(f"wallet:sol:{SOLW}", "gas", -FEE)], "B4 Staker 만 = 가스만", legs("sigA4"))
r5 = parse("sigB5", mk_tx(1101, [(SOLW, 2 * 10 ** 9, 2 * 10 ** 9 + X - FEE), (stk(5), X, 0)], [ix_withdraw(stk(5), SOLW, SOLW, X)]))
consume(r5)
chk(ev("sigB5") == "TRANSFER_SELF" and loc_sum(f"wallet:sol:{SOLW}:stake:{stk(5)}") == 0 and not r5.get("stake_auth"),
    "B5 withdraw → 내 지갑 = TRANSFER_SELF(종전)", legs("sigB5"))
r6 = parse("sigB6", mk_tx(1102, [(SOLW, 2 * 10 ** 9, 2 * 10 ** 9 - FEE), (stk(6), X, 0), (OTH, 10 ** 9, 10 ** 9 + X)],
                         [ix_withdraw(stk(6), SOLW, OTH, X)]))
consume(r6)
chk(ev("sigB6") == "TRANSFER_OUT" and (f"out:sol:{OTH}", "move_in", X) in legs("sigB6") and loc_sum(f"wallet:sol:{SOLW}:stake:{stk(6)}") == 0,
    "B5 withdraw → 남 지갑 = TRANSFER_OUT out:sol:<받은 이>(종전)", legs("sigB6"))

print("— C 판 전 데이터 고침")
new7 = parse("sigC7", stake_tx(stk(7), 1201))
old7 = dict(new7, deltas=[d for d in new7["deltas"] if ":stake:" not in d["owner"]])
old7.pop("stake_auth", None)
consume(old7)
chk(ev("sigC7") == "PROGRAM_IN" and (f"wallet:sol:{SOLW}", "acq", Y) in legs("sigC7") and loc_sum(f"wallet:sol:{SOLW}:stake:{stk(7)}") == X,
    "C1 옛 저장본 재현 = 지갑 새 취득 · 스테이크 칸 그대로(유령)", legs("sigC7"))
s7 = wsum()
e7 = w.cursor["_stk:" + stk(7)]
e7["gone"] = BT0 + 1300
for k9 in ("_stk:" + stk(8), "_stk:" + stk(9)):
    w.cursor[k9]["gone"] = BT0 + 1300
w.cursor["_stk:" + stk(8)]["auth_chk"] = 1
CALLS = []
FAIL9 = {"n": 0}


def sigs_between(s, lo, hi):
    CALLS.append(s)
    if s == stk(9):
        FAIL9["n"] += 1
        raise RuntimeError("서명 목록 실패(흉내)")
    return [x for x in ("dep7", "sigC7") if s == stk(7)]


w._stake_sigs_between = sigs_between
w._stake_hl_ok = lambda need, what: True
w.parse_tx = lambda sig: w._parse_result(sig, TXS[sig]) if sig in TXS else None
w.writer = Writer()
n1 = sol_stake.stake_auth_heal(w)
chk(n1 == 1 and len(w.writer.recs) == 1 and w.writer.recs[0]["txhash"] == "sigC7" and w.writer.recs[0].get("repersp") is True,
    "C1 1회 고침 = 그 tx 를 새 관점으로 다시 보냄", [n1, [r.get("txhash") for r in w.writer.recs]])
chk(e7.get("auth_chk") == 1 and e7.get("away") == 1201 and stk(8) not in CALLS, "C1 계정 표식(auth_chk · away) · 이미 확인한 계정 = 대상 아님",
    [e7, CALLS])
consume(w.writer.recs[0])
chk(ev("sigC7") == "TRANSFER_OUT" and loc_sum(f"wallet:sol:{SOLW}:stake:{stk(7)}") == 0
    and sorted(legs("sigC7")) == sorted([(f"wallet:sol:{SOLW}:stake:{stk(7)}", "move_out", -X), (f"wallet:sol:{SOLW}", "move_in", Y),
                                         (f"out:sol:{NEW}", "move_in", X - Y), (f"wallet:sol:{SOLW}", "gas", -FEE)]),
    "C1 재기장 = TRANSFER_OUT · 스테이크 칸 0 · 칸 = B1 과 같음", [ev("sigC7"), legs("sigC7")])
chk(wsum() - s7 == -X, "C1 내 SOL 합 = 유령 스테이크 몫만 빠짐", wsum() - s7)
before = legs("sigC7")
consume(w.writer.recs[0])
chk(legs("sigC7") == before and loc_sum(f"wallet:sol:{SOLW}:stake:{stk(7)}") == 0, "C2 같은 레코드 재방출 = 원장 무변", legs("sigC7"))
n9 = FAIL9["n"]
chk("auth_chk" not in w.cursor["_stk:" + stk(9)] and w.cursor["_stk:" + stk(9)].get("auth_try") == 1 and n9 == 1,
    "C2 조회 실패 = 표식 없이 다음 주기(시도 수만)", w.cursor["_stk:" + stk(9)])
CALLS.clear()
w.writer = Writer()
for _i in range(sol_stake.AUTH_HEAL_TRIES):
    sol_stake.stake_auth_heal(w)
chk(w.cursor["_stk:" + stk(9)].get("auth_chk") == 1 and FAIL9["n"] == sol_stake.AUTH_HEAL_TRIES and not w.writer.recs,
    "C2 실패가 이어지면 포기 표식(매 주기 호출 안 먹음)", [w.cursor["_stk:" + stk(9)], FAIL9["n"]])
CALLS.clear()
n2 = sol_stake.stake_auth_heal(w)
chk(n2 == 0 and not CALLS and not w.writer.recs, "C2 두 번째 = 호출 0 · 다시 보냄 0", [n2, CALLS])
saved = json.load(open(w.cursor_path))
chk(saved.get("_stk:" + stk(7), {}).get("auth_chk") == 1, "C2 표식은 커서 파일에 남음(재시작에도)", saved.get("_stk:" + stk(7)))


class BadWriter:
    def append(self, r):
        raise OSError("받은 편지함 쓰기 실패(흉내)")


TXS["sigC14"] = stake_tx(stk(14), 1401)
w.cursor["_stk:" + stk(14)]["gone"] = BT0 + 1500
w._stake_sigs_between = lambda s, lo, hi: ["sigC14"] if s == stk(14) else []
w.writer = BadWriter()
n3 = sol_stake.stake_auth_heal(w)
e14 = w.cursor["_stk:" + stk(14)]
chk(n3 == 0 and "away" not in e14 and "auth_chk" not in e14, "C2 다시 보내기 쓰기 실패 = 표식 되돌림(다음 주기 다시)", e14)
w.writer = Writer()
n4 = sol_stake.stake_auth_heal(w)
chk(n4 == 1 and e14.get("away") == 1401 and e14.get("auth_chk") == 1 and len(w.writer.recs) == 1, "C2 다음 주기 = 다시 보냄", [n4, e14])

print("— D 잔고 대조 이름")
chk(balcheck._stake_sym({"state": "closed"}, Decimal("207.5")) == "SOL(스테이킹 · 닫힌 계정 — 원장 칸 남음)", "D 닫힌 계정 + 원장 칸 남음 = 이름에 밝힘")
chk(balcheck._stake_sym({"state": "active"}, Decimal("1")) == "SOL(스테이킹)" and balcheck._stake_sym({"state": "closed"}, Decimal(0)) == "SOL(스테이킹)",
    "D 열린 계정 · 닫힌 계정 0 = 종전 이름")
c.conn.close()
T.finish()
