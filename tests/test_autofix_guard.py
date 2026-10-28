#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
from decimal import Decimal as D  # noqa: E402

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
CFG = {"chains": {}, "wallets": [], "backfill_months": 5, "backfill_since": "2026-01-01"}
json.dump(CFG, open(os.path.join(T.TMP, "config.json"), "w"))
import config, paths  # noqa: E402
import core  # noqa: E402
import autofix as AF  # noqa: E402
import autofix_apply as AP  # noqa: E402
import ledger_lock  # noqa: E402
import recon_adj  # noqa: E402

DAY = 86400
T0 = 1767225600
B1 = T0 + 200 * DAY
E8 = 10 ** 8
c = core.Core(config.load_config())
ax = c.svc_exf._exf_asset
Q, R9, S9 = (ax("okx", s) for s in ("QQQ", "RRR", "TTT"))
OBS = B1 - 3600


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(ts))


def raw(uid, ccy, amt, obs, ts=1740787200):
    pay = {"uuid": uid, "currency": ccy, "amount": str(amt), "fee": "0", "txid": "0x" + uid[-2:] * 32, "state": "DONE", "created_at": iso(ts), "done_at": iso(ts)}
    c.conn.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('okx','withdraw',?,0,?,?)", (uid, json.dumps(pay), obs))
    c.svc_exf._post_exf_withdraw("okx", uid, pay)


for uid, ccy, amt in (("okx:q1", "QQQ", 60), ("okx:r1", "RRR", 10), ("okx:t1", "TTT", 10)):
    raw(uid, ccy, amt, OBS)
for sym, aid, q in (("QQQ", Q, 40), ("RRR", R9, 5), ("TTT", S9, 5)):
    c._post_leg_strict("exchange", "okx:recon", f"exfrecon:{sym}:{B1}", 0, T0, aid, "exchange:okx", q * E8, None, None, "opening", "EXF_ADJUST")
for i, (aid, dt, q) in enumerate(((Q, 5, 30), (Q, 10, -25), (Q, 20, 50), (R9, 20, 20), (S9, 20, 20))):
    c._post_leg_strict("exchange", "okx:trade", f"okx:t{i}", 0, T0 + dt * DAY, aid, "exchange:okx", q * E8, None, None, "acq" if q > 0 else "disp", "EXF_BUY")
c.conn.commit()
DB = paths.DB_PATH
gid9 = lambda aid: c.conn.execute("SELECT group_id FROM assets WHERE asset_id=?", (aid,)).fetchone()[0]   # noqa: E731
json.dump({"2026-01-01": {"p": {str(gid9(Q)): 100.0, str(gid9(R9)): 1.0, str(gid9(S9)): 1.0}}}, open(paths.state("daily_px.json"), "w"))


def dump():
    k = sqlite3.connect(paths.sqlite_ro_uri(DB), uri=True)
    try:
        p = sorted(k.execute("SELECT * FROM postings").fetchall())
        pos = {(r[0], r[1]): r[2] for r in k.execute("SELECT group_id, location, qty_norm FROM positions").fetchall()}
        mk = sorted(k.execute("SELECT k, v FROM meta WHERE k LIKE 'exf_rawskip:%' OR k LIKE 'autofix%' OR k = 'data_rev'").fetchall())
        return p, pos, mk
    finally:
        k.close()


FAKE = os.path.join(T.TMP, "fakebin")
os.makedirs(FAKE, exist_ok=True)
with open(os.path.join(FAKE, "pm2"), "w") as fh:
    fh.write("#!/bin/sh\necho '[]'\n")
os.chmod(os.path.join(FAKE, "pm2"), 0o755)
with open(os.path.join(FAKE, "pm2_core_on"), "w") as fh:
    fh.write("#!/bin/sh\necho '[{\"name\": \"tj-core\", \"pm2_env\": {\"status\": \"online\"}}]'\n")
os.chmod(os.path.join(FAKE, "pm2_core_on"), 0o755)


def tool(*args, pm2="pm2"):
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_") or k.startswith("TJ_TEST_")}
    env.update(TJ_BASE=T.TMP, PM2_BIN=os.path.join(FAKE, pm2), PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, os.path.join(T.ROOT, "tools", "ledger_rowfix.py")] + list(args), env=env, capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout + r.stderr


def receipts():
    c.conn.commit()
    return AF.read_receipts(c.conn)


def pre_files():
    return sorted(n for n in os.listdir(paths.STATE_DIR) if n.startswith("ledger.db.pre_autofix_"))


def pos(aid):
    return D(c.conn.execute("SELECT qty_norm FROM positions WHERE group_id=? AND location='exchange:okx'", (gid9(aid),)).fetchone()[0])


def auto_row(sym):
    r = c.conn.execute("SELECT qty_base, event_ts FROM postings WHERE source_ns='okx:autofix' AND source_id=?", (f"exfauto:{sym}:{B1}",)).fetchone()
    return None if r is None else tuple(r)


s0 = dump()
rc, out = tool("--kind", "autofix_ws")
T.chk(rc == 0 and "큰 칸 1(--allow-big 없이는 건너뜀)" in out and "U 평가액 $2,000" in out and dump() == s0, "G0 점검 = 큰 칸 1(QQQ U $2,000 ≥ $500) 표시 · 원장 무변", out[-700:])

fd9 = ledger_lock.acquire(DB, who="시험")
rc, out = tool("--kind", "autofix_ws", "--apply", "--backup-now", "--allow-big")
ledger_lock.release(fd9)
T.chk(rc == 1 and "원장 작성자 잠금" in out and dump() == s0 and not pre_files(), "G1 원장 작성자 잠금 바쁨 = --apply 거부(원장 무변 · 사본 안 만듦)", out[-400:])

rc, out = tool("--kind", "autofix_ws", "--apply", "--backup-now", "--allow-big", pm2="pm2_core_on")
T.chk(rc == 1 and "tj-core" in out and dump() == s0 and not pre_files(), "G2 pm2 에 tj-core online = --apply 거부(원장 무변)", out[-400:])

c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('data_rev', '3')")
c.conn.commit()
s3 = dump()
got = {}
for args in (("--kind", "autofix_ws", "--apply", "--backup-now", "--allow-big"), ("--undo-autofix", "okx:QQQ", "--apply"), ("--autofix-on", "okx:QQQ", "--apply"),
             ("--ack-autofix", "okx:QQQ", "--apply"), ("--data-rev-down", "1", "--apply")):
    rc, out = tool(*args)
    got[args[0]] = (rc, "원장 개정 3 > 코드 2" in out and "세대 펜스" in out)
T.chk(got == {"--kind": (1, True), "--undo-autofix": (4, True), "--autofix-on": (4, True), "--ack-autofix": (4, True), "--data-rev-down": (4, True)}
      and dump() == s3 and not pre_files(), "G3 원장 data_rev 3 = 모든 쓰기 경로 거부(세대 펜스 · 원장 무변 · 사본 안 만듦)", got)
rc, out = tool("--kind", "autofix_ws")
T.chk(rc == 0 and "큰 칸 1" in out, "G3 점검(읽기만)은 그대로 됨", out[-300:])
c.conn.execute("DELETE FROM meta WHERE k='data_rev'")
c.conn.commit()
T.chk(dump() == s0, "G3 (정리) data_rev 칸 지움 = 처음 상태")

rc, out = tool("--kind", "autofix_ws", "--apply", "--allow-big")
T.chk(rc == 1 and "백업이 하나도 없음" in out and "--backup-now" in out and dump() == s0, "G4 백업 없음 = 거부(--backup-now 안내 · 원장 무변)", out[-500:])
os.makedirs(paths.state("backups"), exist_ok=True)
BK = paths.state("backups", "ledger_20260101.db")
subprocess.run(["cp", DB, BK], check=True)
last9 = max(os.stat(p).st_mtime for p in (DB, DB + "-wal") if os.path.exists(p))
os.utime(BK, (last9 - 100, last9 - 100))
rc, out = tool("--kind", "autofix_ws", "--apply", "--allow-big")
T.chk(rc == 1 and "오래됨" in out and "ledger_20260101.db" in out and "--backup-now" in out and dump() == s0, "G4 최근 백업이 원장 마지막 쓰기보다 오래됨 = 거부", out[-500:])

os.utime(BK, (last9 + 5, last9 + 5))
c.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event, classifier_ver)"
               " VALUES ('exchange', 'okx:autofix', ?, 0, ?, ?, 'exchange:okx', '0', NULL, NULL, 'opening', 'EXF_ADJUST', 1)", (f"exfauto:TTT:{B1}", T0 + 1, S9))
c.conn.commit()
rc, out = tool("--kind", "autofix_ws", "--apply")
rec = receipts()
T.chk(rc == 4 and set(rec) == {("okx", "RRR")} and "okx:QQQ 건너뜀" in out and "--allow-big" in out and "okx:TTT 적용 취소" in out and "같은 열쇠" in out
      and "적용 okx:RRR(A)" in out and "원장 백업 확인: backups/ledger_20260101.db" in out,
      "G5·G6 QQQ 큰 칸 건너뜀 · TTT 같은 열쇠 거부 · RRR 적용(한 칸 거부돼도 나머지 적용 · rc 4) · 신선한 백업 통과", (rc, list(rec), out[-900:]))
T.chk(pos(R9) == D(15) and auto_row("RRR") == (str(-5 * E8), T0 + 20 * DAY + 1) and auto_row("QQQ") is None, "G6 RRR 자동 행 −5 @ τ+1초 · QQQ 무변", (pos(R9), auto_row("RRR")))
c.conn.execute("DELETE FROM postings WHERE source_ns='okx:autofix' AND source_id=? AND qty_base='0'", (f"exfauto:TTT:{B1}",))
c.conn.commit()


class _H(logging.Handler):
    def __init__(self):
        super().__init__()
        self.msgs = []

    def emit(self, r):
        self.msgs.append(r.getMessage())


h9 = _H()
logging.getLogger("tj-core").addHandler(h9)
logging.getLogger("tj-core").setLevel(logging.DEBUG)
c.cfg["autofix"] = {"enabled": True}
json.dump({"okx": {"fills": {"backfilled_until": B1}}}, open(paths.state("exf_state.json"), "w"))

c.conn.execute("INSERT INTO meta (k, v) VALUES ('g7_open', '1')")
T.chk(c.conn.in_transaction, "G7 (전제) 열린 트랜잭션")
n7 = AP.core_pass(c.svc_exf, now=B1 + 10 * DAY)
T.chk(n7 == 0 and c.conn.in_transaction and any("열린 트랜잭션" in m for m in h9.msgs), "G7 열린 트랜잭션 = core_pass 0 · 커밋 안 함(아직 열려 있음) · 사유 로그", (n7, h9.msgs[-2:]))
c.conn.rollback()
T.chk(c.conn.execute("SELECT 1 FROM meta WHERE k='g7_open'").fetchone() is None and set(receipts()) == {("okx", "RRR")}, "G7 되돌린 뒤 남의 변경 없음 · 영수증 무변")

h9.msgs.clear()
n6 = AP.core_pass(c.svc_exf, now=B1 + 10 * DAY)
rec = receipts()
T.chk(n6 == 1 and set(rec) == {("okx", "RRR"), ("okx", "TTT")} and any("okx QQQ 건너뜀" in m and "큰 칸" in m and "--allow-big" in m for m in h9.msgs),
      "G6 core 자동 경로 = QQQ 큰 칸 건너뜀(사유 로그 · 1회 도구 --allow-big 안내) · TTT 적용", (n6, list(rec), [m for m in h9.msgs if "QQQ" in m][-1:]))
del c.cfg["autofix"]
logging.getLogger("tj-core").removeHandler(h9)

os.remove(BK)
STALE = os.path.join(paths.STATE_DIR, "ledger.db.autofix_backup_stale9.tmp")
for p9 in (STALE, STALE + "-wal"):
    open(p9, "wb").close()
rc0, out0 = tool("--kind", "autofix_ws", "--apply", "--allow-big")
T.chk(rc0 == 1 and "백업이 하나도 없음" in out0, "G8 찌꺼기 임시 사본(.tmp)은 백업 목록(신선도)에 안 걸림", out0[-300:])
rc, out = tool("--kind", "autofix_ws", "--apply", "--backup-now", "--allow-big")
T.chk(not os.path.exists(STALE) and not os.path.exists(STALE + "-wal") and not [n for n in os.listdir(paths.STATE_DIR) if ".autofix_backup_" in n],
      "G8 --backup-now 가 찌꺼기 임시 사본을 지움 · 새 임시 파일 안 남음")
rec = receipts()
pf = pre_files()
T.chk(rc == 0 and set(rec) == {("okx", "RRR"), ("okx", "TTT"), ("okx", "QQQ")} and "적용 okx:QQQ(A) · 큰 칸(--allow-big)" in out and len(pf) == 1
      and f"원장 백업 확인: {pf[0]}" in out, "G8 --backup-now + --allow-big = 사본 만든 뒤 큰 칸 적용(rc 0)", (rc, pf, out[-700:]))
bp = os.path.join(paths.STATE_DIR, pf[0]) if pf else ""
bk9 = sqlite3.connect(paths.sqlite_ro_uri(bp), uri=True) if bp else None
try:
    jm = bk9.execute("PRAGMA journal_mode").fetchone()[0] if bk9 else None
    ic = bk9.execute("PRAGMA integrity_check").fetchall() if bk9 else None
    n_before = bk9.execute("SELECT count(*) FROM meta WHERE k LIKE 'autofix:okx:QQQ'").fetchone()[0] if bk9 else None
finally:
    if bk9:
        bk9.close()
T.chk(bp and stat.S_IMODE(os.stat(bp).st_mode) == 0o600 and str(jm).lower() == "delete" and ic == [("ok",)] and n_before == 0
      and not os.path.exists(bp + "-wal") and not os.path.exists(bp + ".tmp"),
      "G8 사본 = 0600 · 저널 DELETE · 무결성 ok · 적용 전 내용(QQQ 영수증 없음) · 임시·부속 파일 없음", (jm, ic, n_before))
T.chk(auto_row("QQQ") == (str(-20 * E8), T0 + 20 * DAY + 1) and pos(Q) == D(35), "G8 QQQ 자동 행 −20 · 포지션 35(I1)")

now_r = time.time()


def doc_at(now):
    c.conn.commit()
    return recon_adj.compute(c.conn, now, lambda v, ref: T0)[1]


def warn_syms(doc):
    return sorted(r["sym"] for r in doc["warn"])


d1 = doc_at(now_r + 10 * DAY)
T.chk(warn_syms(d1) == ["QQQ"] and d1["warn_auto_n"] == 1 and d1["check"]["level"] == "warn" and "확인 전" in d1["check"]["title"] and "--ack-autofix" in d1["check"]["action"]
      and d1["auto"]["n7"] == 0, "G9 10일 뒤에도 확인 전 = QQQ(−$2,000) 노랑 유지(제목 '확인 전' · 할 일에 --ack-autofix) · 7일 집계는 0", (warn_syms(d1), d1["check"]))
rc, out = tool("--ack-autofix", "okx:QQQ")
T.chk(rc == 0 and "점검만" in out and "확인함" not in out, "G9 --ack-autofix 점검 = 쓰기 없음 · 아직 확인 전", out[-200:])
rc, out = tool("--ack-autofix", "okx:QQQ", "--apply")
rec = receipts()[("okx", "QQQ")]
T.chk(rc == 0 and "확인 표시 okx:QQQ" in out and rec.get("ack", {}).get("U") == str(20 * E8) and rec["state"] == "applied" and auto_row("QQQ") == (str(-20 * E8), T0 + 20 * DAY + 1),
      "G9 --ack-autofix --apply = 영수증 ack{at, U} · 숫자 무변", (rc, rec.get("ack"), out[-300:]))
rc, out = tool("--ack-autofix", "okx:QQQ")
T.chk(rc == 0 and "확인함" in out, "G9 점검 = '확인함'", out[-200:])
d2 = doc_at(now_r + 10 * DAY)
T.chk(warn_syms(d2) == [] and d2["check"]["level"] == "ok", "G9 확인 뒤 = 노랑 내려감(ok)", (warn_syms(d2), d2["check"]))
c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('recon_done_exf_okx', ?)", (str(B1 + DAY),))
c._post_leg_strict("exchange", "okx:trade", "okx:lateg1", 0, T0 + 10 * DAY, Q, "exchange:okx", 5 * E8, None, None, "acq", "EXF_BUY")
c.svc_exf._exf_absorb_deltas("okx", {"QQQ": [(T0 + 10 * DAY, D(5))]}, "늦은 체결")
c.conn.commit()
rec = receipts()[("okx", "QQQ")]
d3 = doc_at(now_r + 10 * DAY)
T.chk(rec["U"] == str(25 * E8) and "ack" not in rec and warn_syms(d3) == ["QQQ"] and d3["check"]["level"] == "warn",
      "G9 늦은 입금 +5 = 재계획 U 20 → 25 · 확인 표시 지워짐 · 다시 노랑", (rec["U"], rec.get("ack"), warn_syms(d3)))

p_r = pos(R9)
raw("okx:rlate", "RRR", 3, B1 + DAY, ts=T0 + 25 * DAY)
c.svc_exf._exf_absorb_deltas("okx", {"RRR": [(T0 + 25 * DAY, D(-3))]}, "늦은 출금")
c.conn.commit()
rec = receipts()[("okx", "RRR")]
T.chk(rec["U"] == str(2 * E8) and rec["state"] == "applied" and rec.get("late_at") and auto_row("RRR") == (str(-2 * E8), T0 + 20 * DAY + 1) and pos(R9) == p_r
      and c.conn.execute("SELECT count(*) FROM postings WHERE source_ns='okx:withdraw' AND source_id='okx:rlate'").fetchone()[0] == 1,
      "G10 늦은 진짜 출금 −3 = U 5 → 2 · late_at · 자동 행 −2 · 포지션 = 늦은 행 직전 · 출금 행 기장됨", (rec["U"], rec.get("late_at"), auto_row("RRR"), pos(R9), p_r))

rc, out = tool("--ack-autofix", "okx:ZZZ", "--apply")
T.chk(rc == 4 and "영수증 없음" in out, "G11 영수증 없는 칸 --ack-autofix = 거부", out[-200:])
raw("okx:tlate", "TTT", 5, B1 + DAY, ts=T0 + 25 * DAY)
c.svc_exf._exf_absorb_deltas("okx", {"TTT": [(T0 + 25 * DAY, D(-5))]}, "늦은 출금")
c.conn.commit()
rec = receipts()[("okx", "TTT")]
rc, out = tool("--ack-autofix", "okx:TTT", "--apply")
T.chk(rec["state"] == "resolved" and rc == 0 and "할 일 없음" in out and "ack" not in receipts()[("okx", "TTT")], "G11 자동 행 없는 칸(resolved) = 할 일 없음(표시 안 넣음)", (rec["state"], out[-200:]))
import recon_adj as RA  # noqa: E402
c2 = sqlite3.connect(":memory:")
c2.execute("CREATE TABLE assets (asset_id INTEGER, kind TEXT, symbol TEXT, decimals INTEGER, group_id INTEGER)")
c2.execute("INSERT INTO assets VALUES (1, 'exchange_currency', 'ZZZ', 8, 7)")
cell9 = {"ex": "okx", "sym": "ZZZ", "add": [{"asset_id": 1}], "U": str(1 * E8)}
try:
    AP.big_why(c2, cell9, {"grp": {7: 1.0}, "leg": {}}, None)
    g12 = "통과(잘못)"
except sqlite3.Error as e:
    g12 = "예외 " + type(e).__name__
T.chk(g12.startswith("예외") and RA.venue_values(c2, {"grp": {}}) == {} and AP.big_why(c2, cell9, {"grp": {7: 1.0}, "leg": {}}, {"okx": 10.0}).startswith("큰 칸"),
      "G12 positions 없는 원장: big_why(values 없음) = 예외(평가액 0 아님) · 감시용 venue_values 기본 = 빈 표 · 평가액 $10 의 2% 넘는 $1 = 큰 칸", g12)
c2.close()
rc1, o1 = tool("--undo-autofix", "okx:QQQ", "--apply", "--backup-now")
rc2, o2 = tool("--kind", "autofix_ws", "--allow-big")
T.chk(rc1 == 2 and rc2 == 2 and "autofix_ws --apply 에만" in o1 + o2 and ("okx", "QQQ") in receipts(), "G11 --backup-now · --allow-big 는 autofix_ws --apply 에만(rc 2 · 원장 무변)", (o1[-150:], o2[-150:]))
T.finish()
