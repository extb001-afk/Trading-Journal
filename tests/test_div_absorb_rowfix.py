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
DAY = 86400
BA = T0 + 240 * DAY
BL = T0 + 270 * DAY
TI = T0 + 290 * DAY
BN = TI + 3600
E8 = 10 ** 8
c = core.Core(config.load_config())
c.svc_exf._quote_usd = lambda q, ts: None
ax = c.svc_exf._exf_asset
A, B, Cc, D, E = (ax("binance", s) for s in ("USA", "USB", "USC", "USD", "USE"))
LOC = "exchange:binance"


def leg(ns, sid, ts, aid, q, lk, ev, seq=0):
    c._post_leg_strict("exchange", ns, sid, seq, ts, aid, LOC, int(Decimal(str(q)) * E8), None, None, lk, ev)


def recon_row(sym, aid, bts, ts, q, seq=0):
    leg("binance:recon", f"exfrecon:{sym}:{bts}", ts, aid, q, "opening", "EXF_ADJUST", seq)


N = [0]


def pay(sym, ts, amt, obs=TI):
    N[0] += 1
    f = {"id": f"binance:div:{N[0]}", "ts": int(ts) * 1000, "src": "income", "late": 1, "asset": sym, "base": sym, "amount": str(amt), "info": "x"}
    c.conn.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('binance','income',?,1,?,?)", (f["id"], json.dumps(f), obs))
    assert c.svc_exf._post_exf_income("binance", f)


for sym in ("USA", "USB"):
    c.conn.execute("INSERT OR IGNORE INTO exf_adj_tomb (ex, sym, bts) VALUES ('binance', ?, ?)", (sym, BA))
recon_row("USA", A, BL, T0, 500)
pay("USA", BA - 9 * DAY, 20)
pay("USA", BA - 8 * DAY, 40)
recon_row("USA", A, BN, BN, -60)
recon_row("USB", B, BL, T0, 500)
leg("binance:trade", "t:usb", T0 + 10 * DAY, B, -470, "disp", "EXF_SELL")
pay("USB", BA - 9 * DAY, 20)
pay("USB", BA - 8 * DAY, 40)
recon_row("USB", B, BN, BN, -60)
recon_row("USC", Cc, BA, T0, 500)
pay("USC", BA + 2 * DAY, 20)
recon_row("USC", Cc, BN, BN, -20)
recon_row("USD", D, BL, T0, 500)
pay("USD", BL - 30 * DAY, 20)
recon_row("USD", D, BL + DAY, BL + DAY, -20)
recon_row("USE", E, BL, T0, 500)
pay("USE", BL - 30 * DAY, 20)
recon_row("USE", E, BN, BN, -20)
G, H, I = (ax("binance", s) for s in ("USG", "USH", "USI"))
c.conn.execute("INSERT OR IGNORE INTO exf_adj_tomb (ex, sym, bts) VALUES ('binance', 'USG', ?)", (BA,))
recon_row("USG", G, BL, T0, 500)
recon_row("USG", G, BL + DAY, T0 + DAY, 500)
pay("USG", BA - 9 * DAY, 60)
recon_row("USG", G, BN, BN, -120)
recon_row("USH", H, BA, T0, 440)
recon_row("USH", H, BL, T0 + DAY, 500)
pay("USH", BA - 9 * DAY, 60)
recon_row("USH", H, BN, BN, -60)
REV = []
pid_h = c.conn.execute("SELECT posting_id FROM postings WHERE source_id=?", (f"exfrecon:USH:{BA}",)).fetchone()[0]
with open(os.path.join(paths.STATE_DIR, "exf_recon_revert.jsonl"), "w", encoding="utf-8") as fh:
    fh.write(json.dumps({"ts": TI, "loc": LOC, "posting_id": pid_h, "source_id": f"exfrecon:USH:{BA}", "leg_seq": 0, "event_ts": T0, "asset_id": H,
                         "old_qty_base": str(500 * E8), "new_qty_base": str(440 * E8), "why": f"지급 내역 앞 보정 대체 흡수(대사 {BA} 구간)"}) + "\n")
TI2 = BN + 2 * DAY
c.conn.execute("INSERT OR IGNORE INTO exf_adj_tomb (ex, sym, bts) VALUES ('binance', 'USI', ?)", (BA,))
recon_row("USI", I, BL, T0, 500)
pay("USI", BA - 9 * DAY, 20, obs=TI2)
recon_row("USI", I, BN + DAY, BN + DAY, -20)
recon_row("USI", I, TI2 + 3600, TI2 + 3600, -20)
J, K = (ax("binance", s) for s in ("USJ", "USK"))
TA, TB = T0 + 100 * DAY, T0 + 120 * DAY
BJ0, BJ1, BJ2 = T0 + 150 * DAY, T0 + 110 * DAY, T0 + 200 * DAY
c.conn.execute("INSERT OR IGNORE INTO exf_adj_tomb (ex, sym, bts) VALUES ('binance', 'USJ', ?)", (BJ2,))
recon_row("USJ", J, BJ0, T0, 480)
recon_row("USJ", J, BL, T0 + DAY, 500)
pay("USJ", TA, 20)
pay("USJ", TB, 20)
recon_row("USJ", J, BN, BN, -20)
pid_j = c.conn.execute("SELECT posting_id FROM postings WHERE source_id=?", (f"exfrecon:USJ:{BJ0}",)).fetchone()[0]
REV.append({"ts": TI, "loc": LOC, "posting_id": 990001, "source_id": f"exfrecon:USJ:{BJ2}", "leg_seq": 0, "event_ts": BJ1, "asset_id": J,
            "old_qty_base": str(20 * E8), "new_qty_base": "0", "why": f"지급 내역 대체 흡수(대사 {BJ0} 구간)"})
REV.append({"ts": TI, "loc": LOC, "posting_id": pid_j, "source_id": f"exfrecon:USJ:{BJ0}", "leg_seq": 0, "event_ts": T0, "asset_id": J,
            "old_qty_base": str(500 * E8), "new_qty_base": str(480 * E8), "why": f"지급 내역 앞 보정 대체 흡수(대사 {BJ0} 구간)"})
c.conn.execute("INSERT OR IGNORE INTO exf_adj_tomb (ex, sym, bts) VALUES ('binance', 'USK', ?)", (BA,))
recon_row("USK", K, BL, T0, 500)
pay("USK", BA - 9 * DAY, 60)
c.conn.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('binance','trade','binance:USKUSDT:1',1,?,?)",
               (json.dumps({"id": "binance:USKUSDT:1", "ts": (BA - 8 * DAY) * 1000, "base": "USK", "quote": "USDT", "side": "sell", "price": "1",
                            "qty": "60", "fee": "0", "fee_ccy": "", "late": 1}), TI))
recon_row("USK", K, BN, BN, -60)
L9 = ax("binance", "USL")
D9 = lambda d: T0 + d * DAY
c.conn.execute("INSERT OR IGNORE INTO exf_adj_tomb (ex, sym, bts) VALUES ('binance', 'USL', ?)", (D9(30),))
recon_row("USL", L9, D9(40), T0, 500)
pay("USL", D9(10), 20, obs=D9(100))
pay("USL", D9(20), 20, obs=D9(50))
recon_row("USL", L9, D9(60), D9(60), -20)
recon_row("USL", L9, D9(110), D9(110), -20)
REV.append({"ts": D9(50), "loc": LOC, "posting_id": 990002, "source_id": f"exfrecon:USL:{D9(30)}", "leg_seq": 0, "event_ts": T0, "asset_id": L9,
            "old_qty_base": str(20 * E8), "new_qty_base": "0", "why": f"지급 내역 앞 보정 대체 흡수(대사 {D9(30)} 구간)"})
M9 = ax("binance", "USM")
for d9 in (5, 70):
    c.conn.execute("INSERT OR IGNORE INTO exf_adj_tomb (ex, sym, bts) VALUES ('binance', 'USM', ?)", (D9(d9),))
recon_row("USM", M9, D9(90), T0, 500)
pay("USM", D9(10), 20, obs=D9(20))
pay("USM", D9(45), 20, obs=D9(100))
recon_row("USM", M9, D9(110), D9(110), -20)
REV.append({"ts": D9(100), "loc": LOC, "posting_id": 990003, "source_id": f"exfrecon:USM:{D9(70)}", "leg_seq": 0, "event_ts": D9(70), "asset_id": M9,
            "old_qty_base": str(20 * E8), "new_qty_base": "0", "why": f"지급 내역 대체 흡수(대사 {D9(70)} 구간)"})
N9 = ax("binance", "USN")
H9 = lambda x: T0 + 300 * DAY + x * 3600
for x9 in (50, 1000):
    c.conn.execute("INSERT OR IGNORE INTO exf_adj_tomb (ex, sym, bts) VALUES ('binance', 'USN', ?)", (H9(x9),))
recon_row("USN", N9, H9(1500), T0, 500)
pay("USN", H9(100), 20, obs=H9(1100))
pay("USN", H9(200), 20, obs=H9(2000))
recon_row("USN", N9, H9(2500), H9(2500), -20)
REV.append({"ts": H9(2000), "loc": LOC, "posting_id": 990004, "source_id": f"exfrecon:USN:{H9(1000)}", "leg_seq": 0, "event_ts": H9(1000), "asset_id": N9,
            "old_qty_base": str(20 * E8), "new_qty_base": "0", "why": f"지급 내역 대체 흡수(대사 {H9(1000)} 구간)"})
with open(os.path.join(paths.STATE_DIR, "exf_recon_revert.jsonl"), "a", encoding="utf-8") as fh:
    for e9 in REV:
        fh.write(json.dumps(e9) + "\n")
c.conn.commit()
DB = paths.DB_PATH


def dump():
    k = sqlite3.connect(paths.sqlite_ro_uri(DB), uri=True)
    try:
        p = sorted(k.execute("SELECT * FROM postings").fetchall())
        pos = {(r[0], r[1]): Decimal(r[2]) for r in k.execute("SELECT group_id, location, qty_norm FROM positions").fetchall()}
        inv = k.execute("SELECT v FROM meta WHERE k=?", (__import__("db").DAILY_INVAL_K,)).fetchone()
        tomb = sorted(k.execute("SELECT ex, sym, bts FROM exf_adj_tomb").fetchall())
        return p, pos, inv, tomb
    finally:
        k.close()


def bal_at(p, aid, t):
    return sum(int(r[8]) for r in p if r[6] == aid and r[5] <= t)


def adjq(p, aid):
    return {r[3]: int(r[8]) for r in p if r[6] == aid and r[12] == "EXF_ADJUST"}


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


c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('recon_done_exf_binance', ?)", (str(BN),))
c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('exf_fut_place_v', '0:1:1')")
c.conn.commit()
s_pre = dump()
rc, out = tool("--kind", "div_absorb", "--apply")
chk("R0 선물 정산 이관 미완료 = 할 일 없음(원장 무변)", rc == 0 and "이관 미완료" in out and "할 일 없음" in out and dump()[:2] == s_pre[:2], out[-400:])
c.conn.execute("DELETE FROM meta WHERE k IN ('recon_done_exf_binance', 'exf_fut_place_v')")
c.conn.commit()
s0 = dump()
p0 = s0[0]
rc, out = tool("--kind", "div_absorb")
out_r1 = out
chk("R1 점검 = 지울 줄 2(USA·USI 음수) · 수량 정정 6(USA·USI 앵커 · USB 앵커·음수 · USG 앵커 하나·음수) · 원장 무변",
    rc == 0 and "지울 행 2개 · 수량 정정 행 6개" in out and dump() == s0, out[-1500:])
chk("R1 USB 남는 음수 보정 사유 출력 · USC·USD·USE 고칠 줄 0", "binance USB:" in out and "남김" in out.split("binance USB:")[1].split("\n")[0]
    and all(f"binance {s}:" not in out or "고칠 줄 0" in out.split(f"binance {s}:")[1].split("\n")[0] for s in ("USC", "USD", "USE")), out[-900:])
rc, out = tool("--kind", "div_absorb", "--apply")
s1 = dump()
p1 = s1[0]
chk("R2 USA 앵커 500→440 · 음수 보정 지움 / USB 앵커 500→470 · 음수 −60→−30",
    rc == 0 and adjq(p1, A) == {f"exfrecon:USA:{BL}": 440 * E8} and adjq(p1, B) == {f"exfrecon:USB:{BL}": 470 * E8, f"exfrecon:USB:{BN}": -30 * E8}, out[-600:])
chk("R2 USC·USD·USE 그대로", all(adjq(p1, x) == adjq(p0, x) for x in (Cc, D, E)))
chk("K1 USG 지급 60 = 한 번만 상계(앵커 하나 500→440 · 다른 앵커 500 · 음수 −120→−60)",
    adjq(p1, G) == {f"exfrecon:USG:{BL}": 440 * E8, f"exfrecon:USG:{BL + DAY}": 500 * E8, f"exfrecon:USG:{BN}": -60 * E8}, adjq(p1, G))
chk("K2 USH 이미 대체된 지급(감사 기록) = 다른 앵커·실제 유출 그대로", adjq(p1, H) == adjq(p0, H), adjq(p1, H))
chk("K4 USJ 감사 기록 배정 = core ① → ② 순서(A ← ① 보정 · B ← ② 앵커) → 이미 대체된 지급 · 별도 앵커·실제 유출 그대로", adjq(p1, J) == adjq(p0, J), adjq(p1, J))
chk("K5 USK 지급과 같은 레코드의 늦은 매도(순액 짝 가능) = 그 통화 남김", adjq(p1, K) == adjq(p0, K) and "binance USK:" in out_r1 and "남김" in out_r1.split("binance USK:")[1].split("\n")[0], adjq(p1, K))
chk("K6 USL 관측 회차가 다른 지급 + 감사 기록 = 그 통화 남김(점검 출력 '배정이 모호 · 남김') · 앵커·실제 유출 그대로",
    adjq(p1, L9) == adjq(p0, L9) and all(f"binance {s}:" in out_r1 and "모호 · 남김" in out_r1.split(f"binance {s}:")[1].split("\n")[0] for s in ("USL", "USM", "USN")), adjq(p1, L9))
chk("K7 USM 나중 대사 보정의 감사 기록 = 그 보정이 있던 뒤 관측한 지급(B) 몫 · 앞 회차 지급(A)에 배정 안 함 → 앵커·실제 유출 그대로", adjq(p1, M9) == adjq(p0, M9), adjq(p1, M9))
chk("K8 USN 지연 대사(스냅샷 bts < 앞 지급 관측 < 감사 기록 ts) = 앵커·실제 유출 그대로", adjq(p1, N9) == adjq(p0, N9), adjq(p1, N9))
chk("K3 USI 지급 원본 관측 전 대사의 음수(실제 유출) 그대로 · 관측 뒤 대사 음수만 짝(앵커 500→480)",
    adjq(p1, I) == {f"exfrecon:USI:{BL}": 480 * E8, f"exfrecon:USI:{BN + DAY}": -20 * E8}, adjq(p1, I))
chk("R2 포지션(현재 잔고) 전 칸 무변 · 음수 보정 시각 뒤 잔고 무변 · [앵커, 음수 보정) 만 −x · 새 음수 없음 · 일별 무효화",
    s1[1] == s0[1] and all(bal_at(p1, x, BN) == bal_at(p0, x, BN) for x in (A, B, Cc, D, E))
    and bal_at(p1, A, T0) == bal_at(p0, A, T0) - 60 * E8 and bal_at(p1, A, BL) == bal_at(p0, A, BL) - 60 * E8
    and bal_at(p1, B, T0 + 10 * DAY) == 30 * E8 - 30 * E8 + 0 and all(bal_at(p1, B, t) >= 0 for t in sorted({r[5] for r in p1 if r[6] == B}))
    and s1[2] != s0[2], (s0[1], s1[1]))
chk("R2 지운 음수 보정의 대사 경계(tomb) 남김", ("binance", "USA", BN) in s1[3] and ("binance", "USB", BN) not in s1[3], s1[3])
s1b = dump()
rc, out = tool("--kind", "div_absorb", "--apply")
chk("R3 두 번째 적용 = 할 일 없음(적용 영수증 = 한 번만 · 원장 무변)", rc == 0 and "영수증 있음" in out and "할 일 없음" in out and dump()[:2] == s1b[:2], out[-400:])
undo = sorted(os.path.join(paths.STATE_DIR, n) for n in os.listdir(paths.STATE_DIR) if n.startswith("ledger_rowfix_undo_div_absorb_"))
if undo:
    rc, out = tool("--undo", undo[-1], "--apply")
    s2 = dump()
    chk("R3 되돌리기 = 원래 줄·포지션 그대로", rc == 0 and s2[0] == p0 and s2[1] == s0[1], out[-400:])
    rc, out = tool("--kind", "div_absorb")
    chk("R3 되돌린 뒤 점검 = 다시 같은 계획(영수증 소비됨)", rc == 0 and "지울 행 2개 · 수량 정정 행 6개" in out, out[-400:])
    rv_p = os.path.join(paths.STATE_DIR, "exf_recon_revert.jsonl")
    os.rename(rv_p, rv_p + ".x")
    rc, out = tool("--kind", "div_absorb")
    chk("R0 감사 기록 없음 = 할 일 없음(지급별 못 맞춘 몫 모름 · fail-closed)", rc == 0 and "감사 기록 없음" in out and "할 일 없음" in out, out[-300:])
    os.rename(rv_p + ".x", rv_p)
else:
    chk("R3 되돌리기 파일 없음", False, out[-400:])
c.conn.rollback()

F = ax("binance", "USF")
c.conn.execute("INSERT OR IGNORE INTO exf_adj_tomb (ex, sym, bts) VALUES ('binance', 'USF', ?)", (BA,))
recon_row("USF", F, BL, T0, 500)
c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('recon_done_exf_binance', ?)", (str(BL),))
c.conn.commit()
fills = [{"id": f"binance:div:f{i}", "ts": int(t) * 1000, "src": "income", "late": 1, "asset": "USF", "base": "USF", "amount": str(a), "info": "x"}
         for i, (t, a) in enumerate(((BA - 9 * DAY, 20), (BA - 8 * DAY, 40)))]
c.svc_exf._consume_exf_fills({"v": 1, "kind": "exf_fills", "exchange": "binance", "ts": BL, "fills": fills})
c.conn.commit()
pf = dump()[0]
chk("R2 지금 core 규칙(처음부터) = USF 앵커 440 · 음수 보정 없음 = 정정 결과(USA)와 같은 값", adjq(pf, F) == {f"exfrecon:USF:{BL}": 440 * E8}, adjq(pf, F))
T.finish()
