#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

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
import recon_adj  # noqa: E402
import recon_auto  # noqa: E402

DAY = 86400
T0 = 1767225600
B1 = T0 + 200 * DAY
E8 = 10 ** 8
OBS = B1 - 3600
c = core.Core(config.load_config())
ax = c.svc_exf._exf_asset
PX = {"TKU": 1000.0, "TKV": 1.0}
AID = {s: ax("okx", s) for s in PX}


def raw(uid, ccy, amt):
    pay = {"uuid": uid, "currency": ccy, "amount": str(amt), "fee": "0", "txid": "0x" + uid[-2:] * 32, "state": "DONE",
           "created_at": "2025-03-01T00:00:00+00:00", "done_at": "2025-03-01T00:00:00+00:00"}
    c.conn.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('okx','withdraw',?,0,?,?)", (uid, json.dumps(pay), OBS))
    c.svc_exf._post_exf_withdraw("okx", uid, pay)


for n, sym in enumerate(PX):
    aid = AID[sym]
    raw(f"okx:w{n}", sym, 60)
    c._post_leg_strict("exchange", "okx:recon", f"exfrecon:{sym}:{B1}", 0, T0, aid, "exchange:okx", 40 * E8, None, None, "opening", "EXF_ADJUST")
    for i, (dt, q) in enumerate(((5, 30), (10, -25), (20, 50))):
        c._post_leg_strict("exchange", "okx:trade", f"okx:{sym}:t{i}", 0, T0 + dt * DAY, aid, "exchange:okx", q * E8, None, None,
                           "acq" if q > 0 else "disp", "EXF_BUY")
c.conn.commit()
GID = {s: int(c.conn.execute("SELECT group_id FROM assets WHERE asset_id=?", (a,)).fetchone()[0]) for s, a in AID.items()}
json.dump({"2026-10-01": {"p": {str(GID[s]): PX[s] for s in PX}}}, open(os.path.join(paths.STATE_DIR, "daily_px.json"), "w"))


def tick(auto_on=None):
    on = config.autofix_enabled(c.cfg) if auto_on is None else auto_on
    got = recon_adj.tick(c.conn, c._win_t0, None, time.time(), {}, auto_on=on)
    doc = json.load(open(paths.state(recon_adj.STATE_NAME)))
    T.chk(got is not None and doc.get("ts") == got.get("ts"), "tick = 다시 판정 + 상태 파일 쓰기", got and got.get("ts"))
    return doc


def syms(lst):
    return sorted(r.get("sym") for r in lst or [])


T.chk(config.autofix_enabled(c.cfg) is False, "E1 config autofix.enabled 기본 꺼짐")
d0 = tick()
T.chk(d0["red_n"] == 2 and d0["red_by"] == {"prewin_rows": 2} and d0["check"]["level"] == "crit", "E1 적용 전 = 두 칸 창 이전 행 빨강(crit)",
      (d0["red_n"], d0["red_by"], d0["check"]["level"]))

pl = {x["sym"]: x for x in AF.plan_cells(c.conn, AF.venue_gap, None, B1 + DAY, win=c.svc_exf)}
T.chk({s: (x["kind"], x.get("U")) for s, x in pl.items()} == {s: (AF.KIND_A, str(20 * E8)) for s in PX}, "E2 계획 = 두 칸 A · U 20개",
      {s: (x["kind"], x.get("U"), x.get("why")) for s, x in pl.items()})
pos0 = sorted(tuple(r) for r in c.conn.execute("SELECT group_id, location, qty_norm FROM positions").fetchall())
for s in sorted(PX):
    rec = AP.apply_cell(c.conn, pl[s], int(time.time()))
    T.chk(rec.get("state") == AF.ST_APPLIED, f"E2 {s} apply_cell = 영수증 applied", rec.get("state"))
T.chk(sorted(tuple(r) for r in c.conn.execute("SELECT group_id, location, qty_norm FROM positions").fetchall()) == pos0, "E2 포지션 전 칸 무변(I1)")

d1 = tick()
T.chk(d1["red_n"] == 0 and d1["check"]["level"] != "crit", "E3 적용 뒤 = 빨강 사라짐", (d1["red_n"], d1["red_by"], d1["check"]["level"]))
T.chk(d1["auto"]["n"] == 2, "E3 자동 처리 집계 = 자동 행 2줄(K11)", d1["auto"])
T.chk(syms(d1["warn"]) == ["TKU"] and d1["warn_auto_n"] == 1 and d1["check"]["level"] == "warn" and d1["check"]["tg"] is True
      and "자동 처리" in d1["check"]["title"], "E3 큰 칸(평가 $2×10^4) = 7일 노랑 + 텔레그램(자동 처리 제목)", (syms(d1["warn"]), d1["check"]))
T.chk(d1["gray"]["auto_n"] == 1 and syms(d1["gray"]["auto"]) == ["TKV"] and any(x.startswith("자동 처리 1칸") for x in d1["check"]["info"]),
      "E3 작은 칸(평가 $20) = 회색 정보 줄(노랑 아님)", (d1["gray"], d1["check"]["info"]))
d2 = tick(auto_on=True)
T.chk(d2["red_n"] == 0 and syms(d2["warn"]) == ["TKU"] and syms(d2["gray"]["auto"]) == ["TKV"], "E3 자동 처리 켬(auto_on) 판정도 같음(적용 뒤)",
      (d2["red_n"], syms(d2["warn"]), d2["gray"]))
k11 = [r for r in recon_adj.load_rows(c.conn, recon_adj.prices(), None) if r["site"] == recon_auto.SITE_AUTO]
T.chk(syms(k11) == ["TKU", "TKV"] and all(r["sid"].startswith(AF.SID_HEAD) for r in k11), "E3 자동 행 = 자리 K11 · 'exfauto:' 열쇠", [(r["sym"], r["sid"]) for r in k11])

tail_b = int(time.time()) - DAY
c._post_leg_strict("exchange", "okx:recon", f"exfrecon:TKV:{tail_b}", 0, tail_b, AID["TKV"], "exchange:okx",
                   2000 * E8, None, None, "opening", "EXF_ADJUST")
c.conn.commit()
d3 = tick()
T.chk(syms(d3["warn"]) == ["TKU", "TKV"] and d3["auto"]["n"] == 2
      and any(r["sym"] == "TKV" and r["site"] == "K7" and r["cls"] == "unexplained" for r in d3["warn"]),
      "E4 삭제 경계 보존: 후속 +$2,000은 기초 잔고가 아니라 설명 안 된 보정", (d3["warn"], d3["auto"]))

T.finish()
