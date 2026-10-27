#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({"base": {"0x" + "ab" * 20: {"proto": "v3", "name": "합성"}}}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
CFG = {"chains": {}, "wallets": [], "backfill_months": 5, "backfill_since": "2026-01-01"}
json.dump(CFG, open(os.path.join(T.TMP, "config.json"), "w"))
import config, paths  # noqa: E402
import core  # noqa: E402
import db as dbm  # noqa: E402
import autofix as AF  # noqa: E402
import autofix_apply as AP  # noqa: E402

DAY = 86400
T0 = 1767225600
B1 = T0 + 200 * DAY
E8 = 10 ** 8
c = core.Core(config.load_config())
ax = c.svc_exf._exf_asset
Q, P, S, V, X9 = (ax("okx", s) for s in ("QQQ", "PPP", "SSS", "VVV", "XXX"))
OBS = B1 - 3600


def raw(uid, ccy, amt, obs):
    pay = {"uuid": uid, "currency": ccy, "amount": str(amt), "fee": "0", "txid": "0x" + uid[-2:] * 32, "state": "DONE",
           "created_at": "2025-03-01T00:00:00+00:00", "done_at": "2025-03-01T00:00:00+00:00"}
    c.conn.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('okx','withdraw',?,0,?,?)", (uid, json.dumps(pay), obs))
    c.svc_exf._post_exf_withdraw("okx", uid, pay)


for uid, ccy, amt, obs in (("okx:q1", "QQQ", 60, OBS), ("okx:p1", "PPP", 10, OBS), ("okx:s1", "SSS", 5, OBS), ("okx:v1", "VVV", 7, B1 + 60)):
    raw(uid, ccy, amt, obs)
for sym, aid, q in (("QQQ", Q, 40), ("PPP", P, 10), ("SSS", S, 8), ("VVV", V, 7)):
    c._post_leg_strict("exchange", "okx:recon", f"exfrecon:{sym}:{B1}", 0, T0, aid, "exchange:okx", q * E8, None, None, "opening", "EXF_ADJUST")
from exf_net import norm_fill  # noqa: E402
c.px.candle_usd = lambda sym, ts_ms: 1.0
c.px.fx_at = lambda ms=None: 1400.0
c.svc_exf._consume_exf_fills({"exchange": "okx", "fills": [norm_fill("okx", f"t{i}", (T0 + dt * DAY) * 1000, "QQQ", "USDT", "buy" if q > 0 else "sell", "1", str(abs(q)), "0", "")
                                                          for i, (dt, q) in enumerate(((5, 30), (10, -25), (20, 50)))]})
c.conn.commit()
DB = paths.DB_PATH


def dump():
    k = sqlite3.connect(paths.sqlite_ro_uri(DB), uri=True)
    try:
        p = sorted(k.execute("SELECT * FROM postings").fetchall())
        pos = {(r[0], r[1]): r[2] for r in k.execute("SELECT group_id, location, qty_norm FROM positions").fetchall()}
        mk = sorted(r[0] for r in k.execute("SELECT k FROM meta WHERE k LIKE 'exf_rawskip:%' OR k LIKE 'autofix%' OR k = 'data_rev'"))
        tomb = sorted(k.execute("SELECT ex, sym, bts FROM exf_adj_tomb").fetchall())
        return p, pos, mk, tomb
    finally:
        k.close()


def bal(p, aid, t):
    return sum(int(r[8]) for r in p if r[6] == aid and r[5] <= t)


FAKE = os.path.join(T.TMP, "fakebin")
os.makedirs(FAKE, exist_ok=True)
with open(os.path.join(FAKE, "pm2"), "w") as fh:
    fh.write("#!/bin/sh\necho '[]'\n")
os.chmod(os.path.join(FAKE, "pm2"), 0o755)


def tool(*args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_") or k.startswith("TJ_TEST_")}
    env.update(TJ_BASE=T.TMP, PM2_BIN=os.path.join(FAKE, "pm2"), PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, os.path.join(T.ROOT, "tools", "ledger_rowfix.py")] + list(args), env=env,
                       capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout + r.stderr


def plan():
    c.conn.commit()
    return {x["sym"]: x for x in AF.plan_cells(c.conn, AF.venue_gap, None, B1 + DAY, win=c.svc_exf)}


rc, out = tool("--kind", "autofix_ws", "--apply")
T.chk(rc == 0 and "A 1 · A' 2" in out, "B0 적용(A 1 · A' 2)", out[-300:])
SH = os.path.join(os.path.realpath(T.TMP), "shadow")
env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_") or k.startswith("TJ_TEST_")}
env.update(TJ_BASE=T.TMP, PM2_BIN=os.path.join(FAKE, "pm2"), PYTHONDONTWRITEBYTECODE="1")
r = subprocess.run([sys.executable, os.path.join(T.ROOT, "tools", "rebuild2.py"), "--shadow-dir", SH, "--report", os.path.join(T.TMP, "rb.json")],
                   env=env, capture_output=True, text=True, timeout=600)
SDB = os.path.join(SH, "ledger.db")


def sums(path):
    k = sqlite3.connect(paths.sqlite_ro_uri(path), uri=True)
    try:
        q9 = {}
        for aid, loc, qb in k.execute("SELECT asset_id, location, qty_base FROM postings"):
            q9[(aid, loc)] = q9.get((aid, loc), 0) + int(qb)
        auto9 = k.execute("SELECT source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base FROM postings WHERE source_ns LIKE '%:autofix'").fetchall()
        anc9 = sorted(k.execute("SELECT source_id, event_ts, qty_base FROM postings WHERE source_ns='okx:recon'").fetchall())
        pre9 = k.execute("SELECT count(*) FROM postings WHERE source_ns='okx:withdraw'").fetchone()[0]
        rec9 = sorted(r[0] for r in k.execute("SELECT k FROM meta WHERE k LIKE 'autofix:%' OR k LIKE 'exf_rawskip:%'"))
        return q9, auto9, anc9, pre9, rec9
    finally:
        k.close()


L, Sh = sums(DB), (sums(SDB) if os.path.exists(SDB) else None)
T.chk(Sh is not None and Sh[0] == L[0], "B1 재구축(rebuild2 shadow) = (자산, 위치) 수량 합 라이브와 같음", ((r.stdout + r.stderr)[-800:],))
T.chk(Sh is not None and Sh[1] == L[1] and len(L[1]) == 1 and Sh[2] == L[2],
      "B2 자동 행(−U @ τ)·첫 대사 앵커(X·정정 수량) 그대로 이월(역산 안 함 · 시각 무변)", (L[1:3], Sh and Sh[1:3]))
T.chk(Sh is not None and Sh[3] == L[3] == 1 and Sh[4] == L[4], "B2 지운 창 이전 행 = 재파생 안 됨(막음 표식) · 영수증·표식 이월(남은 창 이전 행 = 남김 칸 VVV 1)", (L[3:], Sh and Sh[3:]))
R2 = os.path.join(os.path.realpath(T.TMP), "r2")
os.makedirs(os.path.join(R2, "state"), exist_ok=True)
src9, dst9 = sqlite3.connect(SDB), sqlite3.connect(os.path.join(R2, "state", "ledger.db"))
src9.backup(dst9)
src9.close()
dst9.close()
env2 = dict(env, TJ_BASE=R2)
r = subprocess.run([sys.executable, os.path.join(T.ROOT, "tools", "ledger_rowfix.py"), "--undo-autofix", "okx:QQQ", "--apply"], env=env2,
                   capture_output=True, text=True, timeout=300)
A2 = sums(os.path.join(R2, "state", "ledger.db"))
T.chk(r.returncode == 0 and A2[0] == L[0] and not A2[1] and A2[3] == 2 and "autofix:okx:QQQ" not in A2[4],
      "B3 재구축 뒤 --undo-autofix(열쇠 기준 · posting_id 무관) = 자동 행 지움 · 창 이전 행 복원 · 수량 합 무변", (r.stdout + r.stderr)[-500:])
T.finish()
