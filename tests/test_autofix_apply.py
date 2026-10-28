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
Q, P, S, V, X9 = (ax("okx", s) for s in ("QQQ", "PPP", "SSS", "VVV", "XXX"))
OBS = B1 - 3600


def raw(uid, ccy, amt, obs):
    pay = {"uuid": uid, "currency": ccy, "amount": str(amt), "fee": "0", "txid": "0x" + uid[-2:] * 32, "state": "DONE",
           "created_at": "2025-03-01T00:00:00+00:00", "done_at": "2025-03-01T00:00:00+00:00"}
    c.conn.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('okx','withdraw',?,0,?,?)", (uid, json.dumps(pay), obs))
    c.svc_exf._post_exf_withdraw("okx", uid, pay)


for uid, ccy, amt, obs in (("okx:q1", "QQQ", 60, OBS), ("okx:p1", "PPP", 10, OBS), ("okx:s1", "SSS", 5, OBS), ("okx:v1", "VVV", 7, B1 + 60)):
    raw(uid, ccy, amt, obs)
pay_k = {"uuid": "okx:k1", "currency": "KKK", "amount": "7", "fee": "0", "txid": "0x" + "k1" * 32, "state": "ACCEPTED",
         "created_at": "2025-03-01T00:00:00+00:00", "done_at": "2025-03-01T00:00:00+00:00"}
c.conn.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('okx','deposit','okx:k1',0,?,?)", (json.dumps(pay_k), OBS))
c.svc_exf._post_exf_deposit_in("okx", "okx:k1", pay_k)
c._post_leg_strict("exchange", "okx:recon", f"exfrecon:KKK:{B1}", 0, B1, ax("okx", "KKK"), "exchange:okx", -7 * E8, None, None, "opening", "EXF_ADJUST")
for sym, aid, q in (("QQQ", Q, 40), ("PPP", P, 10), ("SSS", S, 8), ("VVV", V, 7)):
    c._post_leg_strict("exchange", "okx:recon", f"exfrecon:{sym}:{B1}", 0, T0, aid, "exchange:okx", q * E8, None, None, "opening", "EXF_ADJUST")
for i, (dt, q) in enumerate(((5, 30), (10, -25), (20, 50))):
    c._post_leg_strict("exchange", "okx:trade", f"okx:t{i}", 0, T0 + dt * DAY, Q, "exchange:okx", q * E8, None, None, "acq" if q > 0 else "disp", "EXF_BUY")
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


pl = plan()
q = pl.get("QQQ") or {}
T.chk({k: (v["kind"], v["why"] if v["kind"] in (AF.KIND_SKIP, AF.KIND_A2) else "") for k, v in pl.items()}
      == {"QQQ": ("A", ""), "PPP": ("A'", "pair"), "SSS": ("A'", "setq"), "VVV": ("skip", "late_obs"), "KKK": ("A'", "pair")},
      "P1 칸 꼴 = QQQ A · PPP A' 쌍 · SSS A' 정정 · VVV 남김(관측 뒤) · KKK A' 쌍(앵커가 창 시작 뒤 · 합 0)", {k: (v["kind"], v["why"]) for k, v in pl.items()})
T.chk(q.get("tau") == T0 + 20 * DAY and q.get("X") == "0" and q.get("U") == str(20 * E8) and len(q.get("delete") or []) == 2 and not q.get("setq")
      and (q.get("add") or [{}])[0].get("qty_base") == str(-20 * E8) and q["add"][0]["event_ts"] == T0 + 20 * DAY + 1, "P1 QQQ = τ 셋째 사건 · X 0(앵커 지움) · U 20 · 자동 행 −20 @ τ+1초(같은 초 회복 매수 뒤)", {k: q.get(k) for k in ("tau", "X", "U")})
T.chk(pl["SSS"]["setq"][0]["set_qty"] == str(3 * E8), "P1 SSS 앵커 8 → 3(창 이전 −5 되받기)")

s0 = dump()
import fcntl  # noqa: E402
with open(os.path.join(T.TMP, ".deploy.lock"), "a") as bar_fh:
    fcntl.flock(bar_fh.fileno(), fcntl.LOCK_EX)
    rc, out = tool("--kind", "autofix_ws", "--apply")
    fcntl.flock(bar_fh.fileno(), fcntl.LOCK_UN)
T.chk(rc == 1 and "배포 장벽" in out and dump() == s0, "P2 배포·롤백이 배포 장벽(.deploy.lock)을 쥐면 --apply 거부(원장 무변 · 롤백 검사 뒤 개정 바뀜 막음)", out[-300:])
rc, out = tool("--kind", "autofix_ws")
T.chk(rc == 0 and "A 1 · A' 3 · 남김 1" in out and dump() == s0 and "U 자릿수" in out, "P2 점검 = 원장 무변 · 칸 수·자릿수", out[-600:])

rc, out = tool("--kind", "autofix_ws", "--apply", "--backup-now", "--allow-big")
s1 = dump()
T.chk(rc == 0 and s1[1] == s0[1] and "원장 사본(--backup-now)" in out and "원장 백업 확인" in out, "P3 적용 rc 0 · 포지션 전 칸 무변(I1) · 백업 사본·신선도 확인", out[-600:])
T.chk([bal(s1[0], Q, T0 + d * DAY) for d in (0, 5, 10, 20, 300)] == [x * E8 for x in (0, 30, 5, 55, 35)] and bal(s1[0], Q, T0 + 20 * DAY + 1) == 35 * E8
      and all(bal(s1[0], Q, t) == bal(s0[0], Q, t) for t in (T0 + 20 * DAY + 1, B1, B1 + DAY)),
      "P3 QQQ 궤적 = 창 시작 0 · 30 · 5 · τ 55 · τ+1초 35 (바닥 이상) · 그 뒤 = 적용 전과 같음(I2)", [bal(s1[0], Q, T0 + d * DAY) for d in (0, 5, 10, 20)])
au = [r for r in s1[0] if r[2] == "okx:autofix"]
T.chk(len(au) == 1 and au[0][1:9] == ("exchange", "okx:autofix", f"exfauto:QQQ:{B1}", 0, T0 + 20 * DAY + 1, Q, "exchange:okx", str(-20 * E8))
      and au[0][9] is None and au[0][10] is None and au[0][11:13] == ("opening", "EXF_ADJUST"), "P3 자동 행 꼴(계약)", au)
T.chk("exf_rawskip:okx:withdraw:okx:q1" in s1[2] and ("okx", "QQQ", B1) in s1[3] and not any(r[3] == f"exfrecon:QQQ:{B1}" for r in s1[0]),
      "P3 창 이전 행 재파생 막음 · X 0 앵커 지움 + 대사 경계 묘비", (s1[2], s1[3]))
rec = AF.read_receipts(c.conn)
T.chk({k[1]: v.get("state") for k, v in rec.items()} == {"QQQ": "applied", "PPP": "resolved", "SSS": "resolved", "KKK": "resolved"}
      and dbm.ledger_data_rev(c.conn) == 2 and set(AF.RECEIPT_KEYS) <= set(rec[("okx", "QQQ")]), "P3 영수증 3칸(자동 행 칸 applied · A' resolved) · data_rev 2", rec.keys())
k11 = [r[0] for r in c.conn.execute("SELECT payload FROM raw_observations").fetchall() if '"K11"' in str(r[0])]
T.chk(len(k11) == 1 and "exfauto:QQQ" in k11[0], "P3 보정 갈래 K11 한 줄(자동 행)", k11)
und = sorted(n for n in os.listdir(paths.STATE_DIR) if n.startswith("autofix_undo_okx_"))
T.chk(len(und) == 4 and all(stat.S_IMODE(os.stat(os.path.join(paths.STATE_DIR, n)).st_mode) == 0o600
                            and json.load(open(os.path.join(paths.STATE_DIR, n))).get("applied") is True for n in und), "P3 되돌리기 파일 4(0600 · applied)", und)

rc, out = tool("--kind", "autofix_ws", "--apply")
T.chk(rc == 0 and "할 일 없음" in out and dump() == s1, "P4 두 번째 적용 = 할 일 없음(멱등)", out[-400:])

raw("okx:x1", "XXX", 50, OBS)
c._post_leg_strict("exchange", "okx:recon", f"exfrecon:XXX:{B1}", 0, T0, X9, "exchange:okx", 10 * E8, None, None, "opening", "EXF_ADJUST")
c._post_leg_strict("exchange", "okx:trade", "okx:tx", 0, T0 + 30 * DAY, X9, "exchange:okx", 60 * E8, None, None, "acq", "EXF_BUY")
c.conn.commit()
cx = plan()["XXX"]
s2 = dump()
bad = []
for how in ("qty", "tau"):
    cell = json.loads(json.dumps(cx))
    if how == "qty":
        cell["add"][0]["qty_base"] = str(int(cell["add"][0]["qty_base"]) - 1)
    else:
        cell["tau"] = T0
        cell["add"][0]["event_ts"] = T0
    try:
        AP.apply_cell(c.conn, cell, B1 + DAY)
        bad.append(how + " 통과")
    except AP.Refused as e:
        bad.append(str(e)[:2])
c.conn.execute("INSERT INTO exf_late_pending (ex, lb, lbi, lbn, sym, ts, amt, at, lc) VALUES ('okx', 'b1', 0, 1, 'XXX', 1, '1', 1, NULL)")
c.conn.commit()
try:
    AP.apply_cell(c.conn, json.loads(json.dumps(cx)), B1 + DAY)
    pend_why = "통과"
except AP.Refused as e:
    pend_why = str(e)
T.chk("대기표" in pend_why and dump() == s2, "P5 그 거래소 늦은 행 대기표가 남으면 적용 거부(재계획 불가 상태 방지)", pend_why)
c.conn.execute("DELETE FROM exf_late_pending")
c.conn.commit()
s2 = dump()
T.chk(bad == ["I1", "I2"] and dump() == s2 and ("okx", "XXX") not in AF.read_receipts(c.conn), "P5 불변식 위반 주입 = 거부(I1 · I2) · 원장·영수증 무변", bad)

rc, out = tool("--undo-autofix", "okx:QQQ", "--apply")
s3 = dump()
qa = lambda p: sorted(r for r in p if r[6] == Q)   # noqa: E731
T.chk(rc == 0 and s3[1] == s2[1] and all(bal(s3[0], Q, t) == bal(s0[0], Q, t) for t in (T0 - DAY, T0, T0 + 10 * DAY, T0 + 20 * DAY, B1 + DAY))
      and not any(r[2] == "okx:autofix" for r in s3[0]) and [r for r in qa(s3[0]) if r[2] == "okx:withdraw"] == [r for r in qa(s0[0]) if r[2] == "okx:withdraw"],
      "P6 되돌리기 = 창 이전 행 같은 posting_id · 앵커 원래 수량 · 자동 행 지움 · 포지션·궤적 = 적용 전", out[-500:])
T.chk("exf_rawskip:okx:withdraw:okx:q1" not in s3[2] and "autofix_off:okx:QQQ" in s3[2] and "autofix:okx:QQQ" not in s3[2]
      and any(r[3] == f"exfrecon:QQQ:{B1}" and r[8] == str(40 * E8) for r in s3[0]), "P6 표식·영수증 지움 · autofix_off · 앵커 40", s3[2])
T.chk(plan()["QQQ"]["why"] == "off", "P7 끈 칸 = 남김('off')")
rc, out = tool("--autofix-on", "okx:QQQ", "--apply")
T.chk(rc == 0 and plan()["QQQ"]["kind"] == "A", "P7 --autofix-on 뒤 다시 A", out[-300:])

rc, out = tool("--data-rev-down", "1", "--apply")
T.chk(rc == 4 and dbm.ledger_data_rev(c.conn) == 2, "P8 영수증 남음 = data_rev 내리기 거부", out[-300:])
for sym in ("PPP", "SSS", "KKK"):
    tool("--undo-autofix", f"okx:{sym}", "--apply")
c.conn.commit()
rc, out = tool("--data-rev-down", "1", "--apply")
c.conn.commit()
T.chk(rc == 0 and dbm.ledger_data_rev(c.conn) == 1 and not AF.read_receipts(c.conn), "P8 전부 되돌린 뒤 data_rev 2 → 1", out[-300:])

BIG = ax("okx", "BIG")
c._post_leg_strict("exchange", "okx:trade", "okx:tbig", 0, T0 + 1, BIG, "exchange:okx", 10 ** 6 * E8, None, None, "acq", "EXF_BUY")
gid9 = lambda aid: c.conn.execute("SELECT group_id FROM assets WHERE asset_id=?", (aid,)).fetchone()[0]   # noqa: E731
json.dump({"2026-01-01": {"p": {str(gid9(Q)): 0.001, str(gid9(X9)): 0.001, str(gid9(BIG)): 1.0}}}, open(paths.state("daily_px.json"), "w"))
c.conn.commit()
s4 = dump()
T.chk(AP.core_pass(c.svc_exf, now=B1 + 10 * DAY) == 0 and dump() == s4, "P9 core 자동 경로 기본 꺼짐 = 무동작")
c.cfg["autofix"] = {"enabled": True}
T.chk(AP.core_pass(c.svc_exf, now=B1 + 10 * DAY) == 0 and dump() == s4, "P9 켬 · exf_state 체결 백필 미완료 = 무동작")
json.dump({"okx": {"fills": {"backfilled_until": B1}}}, open(paths.state("exf_state.json"), "w"))
n9 = AP.core_pass(c.svc_exf, now=B1 + 10 * DAY)
rec = AF.read_receipts(c.conn)
T.chk(n9 == 2 and set(rec) == {("okx", "XXX"), ("okx", "QQQ")} and dump()[1] == s4[1],
      "P9 가드 통과 = 적용(다시 켠 QQQ · 새 칸 XXX · 끈 PPP·SSS 는 남김) · 포지션 무변", (n9, list(rec)))
del c.cfg["autofix"]
T.finish()
