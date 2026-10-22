#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
from decimal import Decimal  # noqa: E402

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import acct_norm  # noqa: E402
import config, paths, statefile  # noqa: E402
import core  # noqa: E402

chk = T.chk
NOW = int(time.time())
DAY = 86400
E8 = 10 ** 8
C = core.Core(config.load_config())
C.px.d["neg_ts"]["_fx"] = NOW + 3600
S = C.svc_exf


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(t))


def row(uid, ccy, amt, st, t, **kw):
    return dict({"uuid": f"coinbase:{uid}", "currency": ccy, "amount": amt, "fee": "0", "txid": "", "state": st,
                 "created_at": iso(t), "done_at": iso(t)}, **kw)


T1 = NOW - 6 * DAY
S._consume_ex({"v": 1, "kind": "ex_snapshot", "exchange": "coinbase", "ts": NOW,
               "deposits": [row("d-usd", "USD", "2000", "ACCEPTED", T1), row("d-rw", "USDC", "0.5", "ACCEPTED", T1 + 3600, reward="interest"),
                            row("d-btc", "BTC", "0.5", "ACCEPTED", T1 + 7200, txid="0x" + "c1" * 32)],
               "withdraws": [row("w-btc", "BTC", "0.1", "DONE", T1 + 4 * DAY, txid="0x" + "c2" * 32, fee="0.0001"),
                             row("w-usd", "USD", "50", "DONE", T1 + 4 * DAY)]})
F = [{"id": "coinbase:e-1", "ts": (T1 + DAY) * 1000, "base": "BTC", "quote": "USD", "side": "buy", "price": "60000", "qty": "0.02",
      "fee": "7.2", "fee_ccy": "USD"},
     {"id": "coinbase:cv:trade:t-1", "ts": (T1 + 2 * DAY) * 1000, "base": "USD", "quote": "USDC", "side": "sell", "price": "1", "qty": "100",
      "fee": "0", "fee_ccy": "", "src": "convert", "cv": {"from": "USD", "from_amt": "100", "to": "USDC", "to_amt": "100"}}]
S._consume_exf_fills({"v": 1, "kind": "exf_fills", "exchange": "coinbase", "ts": NOW, "fills": F})
C.conn.commit()


def held(sym):
    r = C.conn.execute("SELECT COALESCE(SUM(CAST(p.qty_base AS INTEGER)),0) FROM postings p JOIN assets a USING(asset_id)"
                       " WHERE p.location='exchange:coinbase' AND upper(a.symbol)=?", (sym,)).fetchone()
    return Decimal(int(r[0])) / E8


ev = {(r[0], r[1]) for r in C.conn.execute("SELECT p.event, upper(a.symbol) FROM postings p JOIN assets a USING(asset_id) WHERE p.location='exchange:coinbase'")}
chk({("EXF_DEPOSIT", "USD"), ("STAKE_REWARD", "USDC"), ("EXF_DEPOSIT", "BTC"), ("EXF_WITHDRAW", "BTC"), ("EXF_WITHDRAW", "USD")} <= ev
    and ("EXF_DEPOSIT", "USDC") not in ev, "L1 USD 입출금·온체인 입출금 = 원장 기장(USD 원장 밖 아님) · USDC 리워드 = STAKE_REWARD(소득)", sorted(ev))
rw = C.conn.execute("SELECT p.leg_kind, p.cost_usd, p.source_ns FROM postings p WHERE p.event='STAKE_REWARD'").fetchall()
chk([tuple(r) for r in rw] == [("acq", "0.5", "coinbase:deposit")], "L1 리워드 = 취득 레그 · 원가 = 액면 0.5 · 원본 = 입금(재구축 같은 경로)", [tuple(r) for r in rw])
S._consume_ex({"v": 1, "kind": "ex_snapshot", "exchange": "coinbase", "ts": NOW,
               "deposits": [row("d-rw2", "ETH", "0.01", "ACCEPTED", T1 + 3700, reward="staking_reward")], "withdraws": []})
ev2 = {tuple(r) for r in C.conn.execute("SELECT p.event, p.leg_kind FROM postings p WHERE p.source_id='coinbase:d-rw2'")}
chk(ev2 == {("EXF_DEPOSIT", "move_in")}, "L1 스테이블 아닌 리워드(ETH) = 종전 입금(원가 없음 — 시가 소급 경로 없음 · 보수)", ev2)
usd9 = Decimal("2000") - Decimal("50") - Decimal("1200") - Decimal("7.2") - Decimal("100")
chk(held("USD") == usd9 and held("USDC") == Decimal("100.5") and held("BTC") == Decimal("0.42") and held("ETH") == Decimal("0.01"),
    "L2 체결·수수료·전환 대칭 레그 — USD 642.8 · USDC 100.5 · BTC 0.42", (held("USD"), held("USDC"), held("BTC")))
cu = C.conn.execute("SELECT p.cost_usd FROM postings p WHERE p.source_ns='coinbase:trade' AND p.source_id='coinbase:e-1' AND p.leg_seq=0").fetchone()
chk(cu and abs(float(cu[0]) - 1200.0) < 1e-9, "L2 BTC 매수 원가 = USD 액면 1,200", cu and cu[0])

statefile.atomic_write_json(os.path.join(paths.STATE_DIR, "exf_balances_coinbase.json"),
                            {"balances": {"USD": float(usd9), "USDC": 100.5, "BTC": 0.41, "ETH": 0.01, "KRW": 5.0}, "ts": NOW - 30, "sources": ["spot"]})
statefile.atomic_write_json(os.path.join(paths.STATE_DIR, "exf_state.json"),
                            {"coinbase": {"seen": {}, "backfilled_until": NOW, "fills": {"backfilled_until": NOW}}})
S._exf_late_flush()
C.conn.commit()
C._drain_at = NOW + 5
S._last_exfrecon = 0
S.exf_recon_pass({"ex"})
adj = {r[0]: Decimal(int(r[1])) / E8 for r in C.conn.execute(
    "SELECT upper(a.symbol), SUM(CAST(p.qty_base AS INTEGER)) FROM postings p JOIN assets a USING(asset_id)"
    " WHERE p.event='EXF_ADJUST' AND p.location='exchange:coinbase' GROUP BY upper(a.symbol)")}
chk(C.conn.execute("SELECT v FROM meta WHERE k='recon_done_exf_coinbase'").fetchone() is not None, "L3 코인베이스 대사가 열림(첫 대사)")
chk("USD" not in adj and "USDC" not in adj and "KRW" not in adj, "L3 USD·USDC 정정 0(원장 = 잔고) · 원화(KRW) 잔고는 대사 밖", adj)
chk(adj.get("BTC") == Decimal("-0.01"), "L3 BTC 차이 −0.01 만 정정", adj)
chk(held("USD") == usd9, "L3 대사 뒤 원장 USD = 잔고 USD(0 으로 깎이지 않음)", held("USD"))

chk(acct_norm.ex_off_ledger("coinbase") == ("KRW",) and acct_norm.ex_off_ledger("gate") == ("KRW", "USD")
    and acct_norm.ex_off_ledger("") == ("KRW", "USD"), "L4 원장 밖 법정통화 — 코인베이스 KRW 만 · 그 밖 KRW·USD(종전)")
chk(set(acct_norm.ex_off_ledger("binance")) == set(S.EXF_FIX_SKIP), "L4 다른 거래소의 양수 정정 재배치 제외 = 종전 EXF_FIX_SKIP 그대로")
import exprov  # noqa: E402
import ex_foreign  # noqa: E402
snap = {"balances": {"USD": 10, "KRW": 5, "BTC": 1}}
chk(exprov.actual_of(snap, "coinbase") == {"USD": Decimal(10), "BTC": Decimal(1)} and exprov.actual_of(snap, "gate") == {"BTC": Decimal(1)}
    and exprov.actual_of(snap) == {"BTC": Decimal(1)}, "L4 첫 대사 전 임시 보유(exprov) — 코인베이스만 USD 포함")
chk(ex_foreign._snap_flat(snap, "coinbase") == {"USD": 10.0, "BTC": 1.0} and ex_foreign._snap_flat(snap, "okx") == {"BTC": 1.0}
    and ex_foreign._snap_agree({"balances": {"USD": 10}}, {"balances": {"USD": 99}}, "gate")[0] is True
    and ex_foreign._snap_agree({"balances": {"USD": 10}}, {"balances": {"USD": 99}}, "coinbase")[0] is False,
    "L4 두 표본 비교 — 코인베이스 USD 다르면 승격 보류 · 그 밖 거래소는 USD 비교 안 함(종전)")
C.conn.close()
T.finish()
