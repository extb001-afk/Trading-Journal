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
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
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
Q, R9, S9 = (ax("okx", s) for s in ("QQQ", "RRR", "TTT"))
OBS = B1 - 3600


def raw(uid, ccy, amt, obs):
    pay = {"uuid": uid, "currency": ccy, "amount": str(amt), "fee": "0", "txid": "0x" + uid[-2:] * 32, "state": "DONE",
           "created_at": "2025-03-01T00:00:00+00:00", "done_at": "2025-03-01T00:00:00+00:00"}
    c.conn.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('okx','withdraw',?,0,?,?)", (uid, json.dumps(pay), obs))
    c.svc_exf._post_exf_withdraw("okx", uid, pay)


for uid, ccy, amt, obs in (("okx:q1", "QQQ", 60, OBS), ("okx:r1", "RRR", 10, OBS), ("okx:t1", "TTT", 10, OBS)):
    raw(uid, ccy, amt, obs)
for sym, aid, q in (("QQQ", Q, 40), ("RRR", R9, 5), ("TTT", S9, 5)):
    c._post_leg_strict("exchange", "okx:recon", f"exfrecon:{sym}:{B1}", 0, T0, aid, "exchange:okx", q * E8, None, None, "opening", "EXF_ADJUST")
for i, (aid, dt, q) in enumerate(((Q, 5, 30), (Q, 10, -25), (Q, 20, 50), (R9, 20, 20), (S9, 20, 20))):
    c._post_leg_strict("exchange", "okx:trade", f"okx:t{i}", 0, T0 + dt * DAY, aid, "exchange:okx", q * E8, None, None, "acq" if q > 0 else "disp", "EXF_BUY")
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


from decimal import Decimal as D  # noqa: E402


def pos(aid):
    g = c.conn.execute("SELECT group_id FROM assets WHERE asset_id=?", (aid,)).fetchone()[0]
    return D(c.conn.execute("SELECT qty_norm FROM positions WHERE group_id=? AND location='exchange:okx'", (g,)).fetchone()[0])


def rows(aid):
    return {(r[0], r[1]): (int(r[2]), int(r[3])) for r in c.conn.execute(
        "SELECT source_ns, source_id, event_ts, qty_base FROM postings WHERE asset_id=? AND source_ns IN ('okx:recon', 'okx:autofix')", (aid,))}


def late(aid, sym, tag, dt, q):
    c._post_leg_strict("exchange", "okx:trade", f"okx:late{tag}", 0, T0 + dt * DAY, aid, "exchange:okx", q * E8, None, None, "acq" if q > 0 else "disp", "EXF_BUY")
    c.svc_exf._exf_absorb_deltas("okx", {sym: [(T0 + dt * DAY, D(q))]}, "늦은 체결")
    c.conn.commit()


c.conn.commit()
rc, out = tool("--kind", "autofix_ws", "--apply")
c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('recon_done_exf_okx', ?)", (str(B1 + DAY),))
c.conn.commit()
rec0 = AF.read_receipts(c.conn)
T.chk(rc == 0 and {k[1]: (v["X"], v["U"], v["tau"]) for k, v in rec0.items()}
      == {"QQQ": ("0", str(20 * E8), T0 + 20 * DAY), "RRR": ("0", str(5 * E8), T0 + 20 * DAY), "TTT": ("0", str(5 * E8), T0 + 20 * DAY)},
      "L0 첫 적용(세 칸 A · X 0 · τ = 창 안 마지막 바닥 아래 다음 사건)", {k[1]: (v["X"], v["U"], v["tau"]) for k, v in rec0.items()})
p_q = pos(Q)
late(Q, "QQQ", "1", 2, -5)
r1 = AF.read_receipts(c.conn)[("okx", "QQQ")]
rq = rows(Q)
T.chk((r1["X"], r1["U"], r1["tau"], r1["state"]) == (str(5 * E8), str(20 * E8), T0 + 20 * DAY, "applied")
      and rq.get(("okx:recon", f"exfrecon:QQQ:{B1}")) == (T0, 5 * E8) and rq.get(("okx:autofix", f"exfauto:QQQ:{B1}")) == (T0 + 20 * DAY + 1, -20 * E8),
      "L1 τ 앞 늦은 출금 −5 = 재계획 X 5(지웠던 앵커 다시) · U 20 · τ 그대로", (r1, rq))
T.chk(pos(Q) == p_q and not any(str(k[1]).startswith("exflate:") for k in rq),
      "L1 I1-late = 포지션 = 늦은 행 직전(관측 잔고 보존) · 종전 상쇄 줄(exflate) 없음", (p_q, pos(Q)))
k11 = lambda: [r[0] for r in c.conn.execute("SELECT payload FROM raw_observations").fetchall() if '"K11"' in str(r[0]) and "RRR" in str(r[0])]   # noqa: E731
n0 = len(k11())
ob0 = c.conn.execute("SELECT observed_at FROM raw_observations WHERE payload LIKE '%exfauto:RRR%'").fetchone()[0]
p_r = pos(R9)
late(R9, "RRR", "2", 10, 5)
r2 = AF.read_receipts(c.conn)[("okx", "RRR")]
ob1 = c.conn.execute("SELECT observed_at FROM raw_observations WHERE payload LIKE '%exfauto:RRR%'").fetchone()[0]
T.chk((r2["X"], r2["U"], r2["state"]) == ("0", str(10 * E8), "applied") and pos(R9) == p_r and rows(R9)[("okx:autofix", f"exfauto:RRR:{B1}")][1] == -10 * E8,
      "L2 늦은 입금 +5 = 재계획 U 5 → 10(관측 잔고 그대로)", r2)
T.chk(n0 == 1 and len(k11()) == 1 and int(ob1) >= int(ob0) and "커짐" in k11()[0], "L2 U 커짐 = 보정 갈래 K11 다시 기록(경고 시각 새로)", (n0, ob0, ob1))
p_t = pos(S9)
late(S9, "TTT", "3", 25, -5)
r3 = AF.read_receipts(c.conn)[("okx", "TTT")]
T.chk((r3["U"], r3["state"]) == ("0", "resolved") and ("okx:autofix", f"exfauto:TTT:{B1}") not in rows(S9) and pos(S9) == p_t,
      "L3 τ 뒤 늦은 출금 −5 = 설명됨 → U 0 · 자동 행 지움 · 'resolved'(앵커 남김)", r3)
r_before = AF.read_receipts(c.conn)[("okx", "QQQ")]
c._post_leg_strict("exchange", "okx:trade", "okx:late4", 0, B1 + 3600, Q, "exchange:okx", -1 * E8, None, None, "disp", "EXF_BUY")
c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('recon_done_exf_okx', ?)", (str(B1 + 2 * DAY),))
c.svc_exf._exf_absorb_deltas("okx", {"QQQ": [(B1 + 3600, D(-1))]}, "늦은 체결")
c.conn.commit()
T.chk(AF.read_receipts(c.conn)[("okx", "QQQ")] == r_before, "L4 첫 대사 뒤(b0, …] 늦은 행 = 종전 규칙(자동 칸 영수증 무변)")
bad = dict(r_before, obs_b0="-1000")
c.conn.execute("UPDATE meta SET v=? WHERE k='autofix:okx:QQQ'", (json.dumps(bad, sort_keys=True, ensure_ascii=False),))
c.conn.commit()
rq0 = rows(Q)
late(Q, "QQQ", "5", 3, -2)
rq1 = rows(Q)
T.chk(AF.read_receipts(c.conn)[("okx", "QQQ")] == bad and rq1.get(("okx:autofix", f"exfauto:QQQ:{B1}")) == rq0.get(("okx:autofix", f"exfauto:QQQ:{B1}")),
      "L5 재계획 거부(관측과 어긋남 주입) = 그 칸 세이브포인트 되돌림 → 종전 흡수(대사 안 막음 · 영수증·자동 행 무변)", (rq0, rq1))
p_t7 = pos(S9)
c._post_leg_strict("exchange", "okx:trade", "okx:late7", 0, T0 + 4 * DAY, S9, "exchange:okx", -499999999, None, None, "disp", "EXF_BUY")
c.svc_exf._exf_absorb_deltas("okx", {"TTT": [(T0 + 4 * DAY, D("-4.999999995"))]}, "늦은 체결")
c.conn.commit()
r7 = AF.read_receipts(c.conn)[("okx", "TTT")]
T.chk(r7.get("X") == "499999999" and r7.get("U") == "0" and pos(S9) == p_t7,
      "L7 늦은 변화가 기장 전 수량(자리수 절삭 전)이어도 재계획(레그당 1 base 허용) · 포지션 = 늦은 행 직전", (r7.get("X"), r7.get("U"), pos(S9), p_t7))
p6 = pos(R9)
rc, out = tool("--undo-autofix", "okx:RRR", "--apply")
c.conn.commit()
T.chk(rc == 0 and pos(R9) == p6 and ("okx", "RRR") not in AF.read_receipts(c.conn) and not any(k[0] == "okx:autofix" for k in rows(R9))
      and ("okx:recon", f"exfrecon:RRR:{B1}") not in rows(R9),
      "L6 재계획 뒤 --undo-autofix = 칸 합 무변 · 앵커 = obs_b0 − s − C_now(b0) = 15 + 10 − 25 = 0(안 넣음 · 경계 묘비 그대로) · 자동 행 지움", out[-400:])
T.finish()
