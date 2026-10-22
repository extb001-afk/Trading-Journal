#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402
from decimal import Decimal  # noqa: E402

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump({"chains": {}, "wallets": [], "backfill_months": 5, "backfill_since": "2026-01-01"}, open(os.path.join(T.TMP, "config.json"), "w"))
import config, paths  # noqa: E402
import core  # noqa: E402


def chk(msg, ok, extra=None):
    T.chk(ok, msg, extra)


T0 = 1767225600
B1 = T0 + 200 * 86400
E8 = 10 ** 8
c = core.Core(config.load_config())
ax = c.svc_exf._exf_asset
A, Bk, C, D, E, F, G, Hh, Ii = (ax("okx", s) for s in ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH", "III"))


def raw(kind, uid, ts, obs, ccy, amt, state):
    pay = {"uuid": uid, "currency": ccy, "amount": str(amt), "fee": "0", "txid": "0x" + uid[-2:] * 32, "state": state,
           "created_at": ts, "done_at": ts}
    c.conn.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('okx',?,?,0,?,?)", (kind, uid, json.dumps(pay), obs))
    return pay


ISO_PRE = "2025-03-01T00:00:00+00:00"
TS_PRE = 1740787200
OBS = B1 - 3600
W = {}
for uid, ccy, amt, obs in (("okx:a1", "AAA", 60, OBS), ("okx:a2", "AAA", 40, OBS), ("okx:b1", "BBB", 50, OBS), ("okx:d1", "DDD", 20, B1 + 60),
                           ("okx:e1", "EEE", 10, OBS), ("okx:g1", "GGG", 25, OBS),
                           ("okx:h1", "HHH", 7, OBS)):
    W[uid] = raw("withdraw", uid, ISO_PRE, obs, ccy, amt, "DONE")
    c.svc_exf._post_exf_withdraw("okx", uid, W[uid])
W["okx:c1"] = raw("deposit", "okx:c1", ISO_PRE, OBS, "CCC", 30, "ACCEPTED")
c.svc_exf._post_exf_deposit_in("okx", "okx:c1", W["okx:c1"])
W["okx:i1"] = raw("deposit", "okx:i1", ISO_PRE, OBS, "III", 5, "ACCEPTED")
c.svc_exf._post_exf_deposit_in("okx", "okx:i1", W["okx:i1"])
c._post_leg_strict("exchange", "okx:withdraw", "okx:e1", 1, TS_PRE, Bk, "exchange:okx", -1 * E8, None, None, "gas", "EXF_WD_FEE")
for sym, aid, q, ts in (("AAA", A, 100, T0), ("BBB", Bk, 40, T0), ("CCC", C, -30, B1), ("DDD", D, 20, T0), ("EEE", E, 10, T0), ("FFF", F, 3, T0), ("GGG", G, 30, T0), ("III", Ii, -3, B1)):
    c._post_leg_strict("exchange", "okx:recon", f"exfrecon:{sym}:{B1}", 0, ts, aid, "exchange:okx", q * E8, None, None, "opening", "EXF_ADJUST")
c._post_leg_strict("exchange", "okx:trade", "okx:t1", 0, T0 + 10 * 86400, A, "exchange:okx", 5 * E8, "5", None, "acq", "EXF_BUY")
c._post_leg_strict("exchange", "okx:recon", f"exfrecon:AAA:{B1 + 86400}", 0, T0, A, "exchange:okx", 2 * E8, None, None, "opening", "EXF_ADJUST")
c._post_leg_strict("exchange", "okx:recon", f"exfrecon:HHH:{B1 + 86400}", 0, T0, Hh, "exchange:okx", 7 * E8, None, None, "opening", "EXF_ADJUST")
W["okx:a3"] = raw("withdraw", "okx:a3", "2026-01-06T00:00:00+00:00", OBS, "AAA", 3, "DONE")
c.svc_exf._post_exf_withdraw("okx", "okx:a3", W["okx:a3"])
c.conn.commit()
DB = paths.DB_PATH


def dump():
    k = sqlite3.connect(paths.sqlite_ro_uri(DB), uri=True)
    try:
        p = sorted(k.execute("SELECT * FROM postings").fetchall())
        pos = {(r[0], r[1]): Decimal(r[2]) for r in k.execute("SELECT group_id, location, qty_norm FROM positions").fetchall()}
        inv = k.execute("SELECT v FROM meta WHERE k=?", (__import__("db").DAILY_INVAL_K,)).fetchone()
        mk = sorted(r[0] for r in k.execute("SELECT k FROM meta WHERE k LIKE 'exf_rawskip:%'"))
        tomb = sorted(k.execute("SELECT ex, sym, bts FROM exf_adj_tomb").fetchall())
        rx = k.execute("SELECT count(*) FROM raw_ex").fetchone()[0]
        return p, pos, inv, mk, tomb, rx
    finally:
        k.close()


def bal_at(p, aid, t):
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


c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('recon_done_exf_okx', ?)", (str(B1 + 86400),))
c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('exf_fut_place_v', '0:1:1')")
c.conn.commit()
s_pre = dump()
rc, out = tool("--kind", "okx_prewin", "--apply")
chk("P0 선물 정산 이관 미완료(todo) = 할 일 없음(지운 경계가 이관 보류를 부름 · 원장 무변)",
    rc == 0 and "이관 미완료" in out and "할 일 없음" in out and dump()[:4] == s_pre[:4], out[-400:])
c.conn.execute("DELETE FROM meta WHERE k IN ('recon_done_exf_okx', 'exf_fut_place_v')")
c.conn.commit()
s0 = dump()
p0 = s0[0]
rc, out = tool("--kind", "okx_prewin")
chk("P1 점검 = 쌍 칸(AAA) 3행 지움 + 정정 칸(GGG) 창 이전 1행 지움·앵커 1행 수량 정정 · 원장 무변",
    rc == 0 and "지울 행 4개 · 수량 정정 행 1개" in out and dump() == s0, out[-800:])
chk("P1 남는 칸 사유 = BBB 합<0 · CCC 앵커 창 시작 뒤 · DDD 관측 뒤 · EEE 레그 걸침 · HHH 앵커가 거래소 첫 대사 것 아님(FFF = 창 이전 행 없음 = 언급 없음)",
    all(f"남김 자산 {a}:" in out for a in (Bk, C, D, E, Hh)) and "첫 대사의 이 칸 앵커 없음" in out and f"남김 자산 {F}:" not in out
    and "합 + 앵커 < 0" in out and f"남김 자산 {G}:" not in out and "창 시작 뒤" in out and "첫 대사 뒤" in out and "걸침" in out, out[-800:])
rc, out = tool("--kind", "okx_prewin", "--apply")
s1 = dump()
p1 = s1[0]
gone = {r[0] for r in p0} - {r[0] for r in p1}
ga = {r[0]: r for r in p1}
chg = [r for r in p0 if r[0] not in gone and ga[r[0]] != r]
chk("P2 적용 = AAA 창 이전 출금 2행 + 첫 대사 앵커 1행 · GGG 창 이전 1행 삭제 · GGG 첫 대사 앵커만 수량 30→5(다른 대사·체결·다른 칸 그대로)",
    rc == 0 and len(gone) == 4 and {r[3] for r in p0 if r[0] in gone} == {"okx:a1", "okx:a2", f"exfrecon:AAA:{B1}", "okx:g1"}
    and len(chg) == 1 and chg[0][3] == f"exfrecon:GGG:{B1}" and ga[chg[0][0]][8] == str(5 * E8)
    and all(ga[r[0]][:8] == r[:8] and ga[r[0]][9:] == r[9:] for r in chg) and len(p1) == len(p0) - 4, out[-600:])
chk("P2 포지션(현재 잔고) 전 칸 무변 · 창 시작·그 뒤 잔고 궤적 무변 · 일별 무효화 표식",
    s1[1] == s0[1] and all(bal_at(p1, x, t) == bal_at(p0, x, t) for x in (A, G) for t in (T0, T0 + 10 * 86400, B1, B1 + 86400)) and s1[2] != s0[2], (s0[1], s1[1]))
chk("P2 재파생 막음 표식 = 지운 입출금 원본 3개만(정정 앵커는 표식 없음) · 지운 대사 경계 = (okx, AAA, 첫 대사) · 원본(raw_ex) 그대로",
    s1[3] == ["exf_rawskip:okx:withdraw:okx:a1", "exf_rawskip:okx:withdraw:okx:a2", "exf_rawskip:okx:withdraw:okx:g1"] and s1[4] == sorted(s0[4] + [("okx", "AAA", B1)]) and s1[5] == s0[5],
    (s1[3], s1[4]))
c.conn.rollback()
re1 = c.svc_exf._post_exf_withdraw("okx", "okx:a1", W["okx:a1"])
n_new = raw("withdraw", "okx:n1", "2026-03-01T00:00:00+00:00", B1, "AAA", 1, "DONE")
re2 = c.svc_exf._post_exf_withdraw("okx", "okx:n1", n_new)
c.conn.commit()
p_re = dump()[0]
chk("P3 재파생 = 표식 원본(a1) 다시 기장 안 함 · 표식 없는 새 원본(n1)은 기장",
    re1 is False and not any(r[3] == "okx:a1" for r in p_re) and re2 is True and any(r[3] == "okx:n1" for r in p_re), (re1, re2))
s1b = dump()
rc, out = tool("--kind", "okx_prewin", "--apply")
chk("P4 두 번째 적용 = 할 일 없음(멱등 · 원장 무변)", rc == 0 and "할 일 없음" in out and dump()[:4] == s1b[:4], out[-400:])
undo = sorted(os.path.join(paths.STATE_DIR, n) for n in os.listdir(paths.STATE_DIR) if n.startswith("ledger_rowfix_undo_okx_prewin_"))
if undo:
    rc, out = tool("--undo", undo[-1], "--apply")
    s2 = dump()
    chk("P4 되돌리기 = 같은 posting_id 로 복원(새 원본 n1 행은 그대로) · 포지션 = 되돌리기 직전과 같음(쌍 합 0) · 재파생 막음 표식 지움",
        rc == 0 and s2[0] == sorted(p0 + [r for r in s1b[0] if r[3] == "okx:n1"]) and s2[1] == s1b[1] and s2[3] == [], out[-400:])
    c.conn.rollback()
    c.conn.rollback()
    chk("P4 되돌린 뒤 그 원본 = 막음 없음", c.conn.execute("SELECT 1 FROM meta WHERE k='exf_rawskip:okx:withdraw:okx:a1'").fetchone() is None)
    s3 = dump()
    rc, out = tool("--kind", "mirror_open", "--late-anchor")
    chk("L1 --late-anchor 는 okx_prewin 에만(다른 종류 = 거부 · 원장 무변)", rc == 2 and dump()[:4] == s3[:4], out[-300:])
    rc, out = tool("--kind", "okx_prewin", "--late-anchor")
    chk("L2 --late-anchor 점검 = 기본 대상 + 앵커가 창 시작 뒤·합 0 칸(CCC 입금 1 + 앵커 1) · 합≠0(III)·합<0(BBB) 은 남김 · 원장 무변",
        rc == 0 and "지울 행 6개 · 수량 정정 행 1개" in out and f"남김 자산 {C}:" not in out
        and f"남김 자산 {Ii}:" in out and f"남김 자산 {Bk}:" in out and dump()[:4] == s3[:4], out[-800:])
    rc, out = tool("--kind", "okx_prewin", "--late-anchor", "--apply")
    s4 = dump()
    gone4 = {r[0] for r in s3[0]} - {r[0] for r in s4[0]}
    chk("L3 --late-anchor 적용 = CCC 창 이전 입금 + 첫 대사 음수 앵커 쌍 삭제 · 현재 잔고(포지션) 전 칸 무변 · CCC 창 시작~첫 대사 잔고 +30 → 0 · 첫 대사 뒤 0 그대로",
        rc == 0 and {r[3] for r in s3[0] if r[0] in gone4} == {"okx:a1", "okx:a2", f"exfrecon:AAA:{B1}", "okx:g1", "okx:c1", f"exfrecon:CCC:{B1}"} and s4[1] == s3[1]
        and bal_at(s3[0], C, T0) == 30 * E8 and bal_at(s4[0], C, T0) == 0 and bal_at(s4[0], C, B1) == bal_at(s3[0], C, B1) == 0
        and all(bal_at(s4[0], Ii, t) == bal_at(s3[0], Ii, t) for t in (T0, B1)) and "exf_rawskip:okx:deposit:okx:c1" in s4[3], out[-600:])
else:
    chk("P4 되돌리기 파일 없음", False, out[-400:])
T.finish()
