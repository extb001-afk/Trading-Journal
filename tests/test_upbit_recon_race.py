#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401

import json  # noqa: E402
import time  # noqa: E402

import config, paths, statefile  # noqa: E402
import core  # noqa: E402

chk = T.chk
NOW = int(time.time())
c = core.Core(config.load_config())
sv = c.svc_exf
statefile.atomic_write_json(paths.state("upbit_orders_state.json"), {"complete": True, "backfilled_until": NOW})


def snap(ts, qty):
    statefile.atomic_write_json(paths.state("upbit_balances.json"), {"ts": ts, "accounts": [{"currency": "XRP", "balance": str(qty), "locked": "0"}]})


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S+09:00", time.gmtime(t + 9 * 3600))


def raw(kind, uid, state, created, done, observed):
    c.conn.execute("INSERT OR REPLACE INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('upbit',?,?,1,?,?)",
                   (kind, uid, json.dumps({"currency": "XRP", "state": state, "amount": "1", "created_at": iso(created), "done_at": iso(done)}), observed))
    c.conn.commit()


def post(ns, uid, ts, qty):
    c._post_leg("exchange", ns, uid, 0, ts, sv._upbit_asset("XRP"), "exchange:upbit", int(qty * 10 ** 8), None, None,
                "move_in" if qty > 0 else "move_out", "EX_DEPOSIT" if qty > 0 else "EX_WITHDRAW")
    raw(ns.split(":")[1], uid, "ACCEPTED" if qty > 0 else "DONE", ts, ts, ts + 2)


def recon():
    sv._last_exrecon = 0
    sv.exchange_recon_pass(frozenset({"ex"}))
    adj = [dict(r) for r in c.conn.execute("SELECT qty_base FROM postings WHERE event='EX_ADJUST'")]
    return adj, sv._meta_get("recon_done_upbit")


def reset():
    c.conn.execute("DELETE FROM postings WHERE source_ns IN ('upbit:recon','upbit:deposit','upbit:withdraw')")
    c.conn.execute("DELETE FROM meta WHERE k='recon_done_upbit'")
    c.conn.execute("DELETE FROM raw_ex")
    c.conn.commit()


B = NOW - 120
post("upbit:deposit", "d-old", NOW - 86400, 100)
post("upbit:deposit", "d-race", B + 3, 5)
snap(B, 100)
adj, mark = recon()
chk(adj == [] and mark is None, "R1 스냅숏 뒤에 끝난 입금 = 대사 보류(종전: −5 보정 + 1회성 표식으로 영구 고정)", [adj, mark])
chk(time.time() - sv._last_exrecon >= 239, "R1 보류 뒤 다음 시도는 1분 뒤(5분 간격과 입출금이 맞물려 계속 비껴가지 않게)", time.time() - sv._last_exrecon)
snap(NOW, 105)
adj, mark = recon()
chk(adj == [] and mark == str(NOW), "R2 다음 주기 스냅숏(입금 반영 105) = 대사 완료 · 보정 0", [adj, mark])
reset()
post("upbit:deposit", "d-old", NOW - 86400, 100)
post("upbit:withdraw", "w-race", B + 2, -10)
snap(B, 100)
adj, mark = recon()
chk(adj == [] and mark is None, "R3 스냅숏 뒤 출금 = 대사 보류(종전: +10 유령 보정)", [adj, mark])
reset()
post("upbit:deposit", "d-old", NOW - 86400, 100)
post("upbit:deposit", "d-early", B - 600, 5)
snap(B, 105)
adj, mark = recon()
chk(adj == [] and mark == str(B), "R4 입출금이 다 스냅숏보다 충분히 앞 = 바로 대사 완료(보류 안 함)", [adj, mark])
reset()
post("upbit:deposit", "d-old", NOW - 86400, 100)
post("upbit:withdraw", "w-late", B - 600, -10)
raw("withdraw", "w-late", "DONE", B - 600, B + 3, B + 5)
snap(B, 100)
adj, mark = recon()
chk(adj == [] and mark is None, "R5 오래전 요청·스냅숏 뒤 완료 출금 = 대사 보류(종전·기장 시각만 보면 +10 영구 보정)", [adj, mark])
reset()
post("upbit:deposit", "d-old", NOW - 86400, 100)
raw("withdraw", "w-odd", "CANCELLED", 4102444800, 4102444800, B - 100)
snap(B, 100)
adj, mark = recon()
chk(adj == [] and mark == str(B), "R6 미래 시각이 적힌 종결 행 = 관측 시각까지만 봄(대사가 영영 막히지 않음)", [adj, mark])
c.conn.close()
T.finish()
