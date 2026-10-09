#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import glob
import json
import os
import subprocess
import time
from decimal import Decimal

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import common
import core
import health

assert T.TMP in common.STATE_DIR
core.dm = lambda *a, **k: None
core.Core.EXF_REVERT_LOG = os.path.join(common.STATE_DIR, "exf_recon_revert.jsonl")
chk = T.chk
E8 = 10 ** 8
NOW = int(time.time())
SEQ = {"t": NOW - 1700}
BK = os.path.join(common.STATE_DIR, "backups")
os.makedirs(BK, exist_ok=True)
open(os.path.join(BK, "ledger_test.db"), "w").close()
common.atomic_write_json(os.path.join(BK, "backup_status.json"),
                         {"last_ok": int(time.time()) + 86400 * 30, "last_path": os.path.join(BK, "ledger_test.db")})


def mkcore():
    c = core.Core(common.load_config())
    c._quote_usd = lambda q, ts: Decimal(1)
    c.EXF_INIT_PHASE = 5
    return c


C = mkcore()


def tick(d=10):
    SEQ["t"] += d
    return SEQ["t"]


def tick_min():
    SEQ["t"] += 60 - SEQ["t"] % 60 + 1
    return SEQ["t"]


def post(ex, t, sym, qty, ev="EXF_DEPOSIT", lk="move_in", sid=None):
    aid = C._exf_asset(ex, sym)
    qb = int(Decimal(str(qty)) * E8)
    C.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base,"
                   " cost_usd, cost_krw, leg_kind, event, classifier_ver) VALUES ('exchange',?,?,0,?,?,?,?,NULL,NULL,?,?,?)",
                   (f"{ex}:{'deposit' if qty > 0 else 'withdraw'}", sid or f"{ex}:{t}:{sym}:{qty}", int(t), aid, f"exchange:{ex}", str(qb), lk, ev,
                    core.CLASSIFIER_VER))
    C._bump_position(aid, qb, f"exchange:{ex}")
    C.conn.commit()


def futfile(ex, events, ts=None):
    common.atomic_write_json(os.path.join(common.STATE_DIR, f"futures_{ex}.json"), {
        "ts": int(ts if ts is not None else time.time()),
        "events": [{"t": int(t) * 1000 + 123, "symbol": s, "kind": k, "amount": a, "uid": f"u{i}"} for i, (t, s, k, a) in enumerate(events)]})
    for c9 in (C,):
        c9.__dict__.pop("_exf_fut_cache", None)


def recon(ex, bal, sources=("futures",), bts=None, c=None):
    c = c or C
    bts = bts or tick()
    st = common.read_json(os.path.join(common.STATE_DIR, "exf_state.json"), {})
    st.setdefault(ex, {"seen": {}, "backfilled_until": NOW, "fills": {"backfilled_until": NOW}})
    common.atomic_write_json(os.path.join(common.STATE_DIR, "exf_state.json"), st)
    common.atomic_write_json(os.path.join(common.STATE_DIR, f"exf_balances_{ex}.json"),
                             {"ts": bts, "balances": bal, "sources": list(sources)})
    c._drain_at = bts + 5
    c._last_exfrecon = 0
    c.__dict__.pop("_exf_fut_cache", None)
    c.exf_recon_pass({"ex"})
    return bts


def total(ex, sym):
    v = C.conn.execute("SELECT SUM(CAST(p.qty_base AS INTEGER)) FROM postings p JOIN assets a USING(asset_id) WHERE p.location=? AND upper(a.symbol)=?",
                       (f"exchange:{ex}", sym)).fetchone()[0]
    return Decimal(int(v or 0)) / E8


def snap(*exs):
    out = []
    for ex in exs:
        out += sorted(tuple(r) for r in C.conn.execute("SELECT source_ns, source_id, leg_seq, event_ts, qty_base FROM postings WHERE location=?",
                                                       (f"exchange:{ex}",)).fetchall())
    return out


def tombs(*exs):
    return sorted(tuple(r) for r in C.conn.execute("SELECT ex, sym, bts FROM exf_adj_tomb WHERE ex IN (%s)" % ",".join("?" * len(exs)), exs))


def scene(ex, sym_c):
    t0 = tick(0) - 5000
    post(ex, t0, "USDT", 1000, sid=f"{ex}:d0")
    b0 = recon(ex, {"USDT": 1000})
    t1 = t0 + 100
    post(ex, t1, "USDT", -1200, ev="EXF_WITHDRAW", lk="move_out", sid=f"{ex}:w1")
    post(ex, t1 + 7300, "USDT", 500, sid=f"{ex}:d1")
    recon(ex, {"USDT": 300})
    recon(ex, {"USDT": 250})
    tf1 = tick(5)
    b3 = recon(ex, {"USDT": 245})
    tf2 = tick_min()
    b4 = recon(ex, {"USDT": 845})
    return dict(b0=b0, b3=b3, b4=b4, evs=[(tf1, sym_c, "FEE", -5.0), (tf2, sym_c, "REALIZED", 400.0), (tf2 + 1, sym_c, "REALIZED", 201.0),
                                          (tf2 + 2, sym_c, "FEE", -1.0)])


def once(c=None):
    c = c or C
    try:
        return c._exf_fut_place_once(auto=True)
    except TypeError:
        return c._exf_fut_place_once()


def unmark(*exs):
    C.conn.execute("DELETE FROM meta WHERE k IN ('exf_fut_place_v', 'exf_fut_place_wait')")
    for ex in exs:
        C.conn.execute("DELETE FROM meta WHERE k IN (?, ?)", (f"exf_fut_from_{ex}", f"exf_fut_cur_{ex}"))
    C.conn.commit()


FAKE = os.path.join(T.TMP, "fakebin")
os.makedirs(FAKE, exist_ok=True)
with open(os.path.join(FAKE, "pm2"), "w") as fh:
    fh.write("#!/bin/sh\necho '[]'\n")
os.chmod(os.path.join(FAKE, "pm2"), 0o755)
WRAP = os.path.join(T.TMP, "fp_wrap.py")
with open(WRAP, "w") as fh:
    fh.write("import runpy, sys\nsys.dont_write_bytecode = True\nsys.path.insert(0, sys.argv[1])\nimport core\ncore.Core.EXF_INIT_PHASE = 5\n"
             "tool = sys.argv[2]\nsys.argv = [tool] + sys.argv[3:]\nrunpy.run_path(tool, run_name='__main__')\n")


def tool(*args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_") or k.startswith("TJ_TEST_")}
    env.update(TJ_BASE=T.TMP, PM2_BIN=os.path.join(FAKE, "pm2"), PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, WRAP, T.SRC, os.path.join(T.ROOT, "tools", "exf_fut_place.py")] + list(args), env=env,
                       capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout + r.stderr


UNDO = os.path.join(common.STATE_DIR, f"exf_fut_place_v{core.Core.EXF_FUT_V}.json")

print("[V] 선물 파일 하나가 낡아도 준비된 거래소는 옮김")
VB = scene("bybit", "VVVUSDT")
VO = scene("okx", "VVV-USDT-SWAP")
futfile("bybit", VB["evs"])
last_okx = int(C._meta_get("recon_done_exf_okx"))
futfile("okx", VO["evs"], ts=last_okx - 100)
unmark("bybit", "okx")
snapV0 = snap("bybit", "okx")
tombV0 = tombs("bybit", "okx")
totV0 = (total("bybit", "USDT"), total("okx", "USDT"))
n = once()
fb = [r for r in snap("bybit") if r[0] == "bybit:futpnl"]
fo = [r for r in snap("okx") if r[0] == "okx:futpnl"]
wait9 = json.loads(C._meta_get("exf_fut_place_wait") or "null")
chk(n == 1 and len(fb) == 2 and not fo and snap("okx") == [r for r in snapV0 if r[0].startswith("okx:")],
    "V1 바이빗 = 옮김(선물 줄 2) · OKX = 그대로(낡은 파일)", (n, fb, fo))
chk(str(C._meta_get("exf_fut_place_v")).split(":")[0] == "1" and str(C._meta_get("exf_fut_place_v")).split(":")[2] == "1"
    and isinstance(wait9, dict) and list((wait9.get("ex") or {})) == ["okx"] and "낡음" in wait9["ex"]["okx"],
    "V2 표식 '1:시각:1' + 대기 거래소 {okx: 사유}", (C._meta_get("exf_fut_place_v"), wait9))
hv = {c["cid"]: c for c in health.collect_fut_wait(time.time())}
chk(hv.get("futplace:okx", {}).get("level") == "warn" and hv["futplace:okx"]["title"].startswith("선물 재배치 대기: OKX — ")
    and hv.get("futplace:bybit", {}).get("level") == "ok" and hv["futplace:okx"]["notify"] is False,
    "V3 상태 패널 '선물 재배치 대기: OKX — <이유>'(주의 · 알림 없음) · 바이빗 = 정상", {k: (v["level"], v["title"]) for k, v in hv.items() if k.startswith("futplace")})
chk((total("bybit", "USDT"), total("okx", "USDT")) == totV0, "V4 두 거래소 원장 합 무변", ((total("bybit", "USDT"), total("okx", "USDT")), totV0))
futfile("okx", VO["evs"])
n2 = once()
fo = [r for r in snap("okx") if r[0] == "okx:futpnl"]
ud = json.load(open(UNDO))
chk(n2 == 1 and len(fo) == 2 and C._meta_get("exf_fut_place_wait") is None and str(C._meta_get("exf_fut_place_v")).split(":")[2] == "2"
    and sorted({m["ex"] for m in ud["plan"] if m.get("cands")}) == ["bybit", "okx"],
    "V5 파일이 되살아나면 다음 회차에 OKX 만 옮김 · 대기 표식 지움 · 표식 통화 수 2 · 되돌리기 자료 이어 붙음(두 거래소)", (n2, fo, C._meta_get("exf_fut_place_v")))
hv = {c["cid"]: c for c in health.collect_fut_wait(time.time())}
chk(hv.get("futplace:okx", {}).get("level") == "ok", "V6 대기 끝 = 상태 패널 정상", hv.get("futplace:okx"))
chk(once() is None, "V7 끝난 뒤 다시 = 할 일 없음")

print("[U] --undo 유지 · 새 core 대사 = 다시 적용 안 함")
snapU1 = snap("bybit", "okx")
tombU1 = tombs("bybit", "okx")
rc, out = tool("--undo", UNDO)
chk(rc == 0 and snap("bybit", "okx") == snapV0, "U1 되돌리기 = 재배치 전 줄 그대로(두 거래소 · 이어 붙인 자료 한 번에)", out[-300:])
chk(str(C._meta_get("exf_fut_place_v")).startswith("1:undone:") and C._meta_get("exf_fut_place_wait") is None,
    "U2 표식 = '1:undone:시각'(자동 적용 금지 — 종전: 표식 지움 → 다음 대사에 다시 적용)", C._meta_get("exf_fut_place_v"))
chk(len(tombU1) > len(tombV0) and tombs("bybit", "okx") == tombV0, "U3 재배치가 남긴 지운 대사 경계(tomb) 줄도 지움(되돌린 뒤 = 재배치 전 경계 표식 그대로)",
    (tombV0, tombU1, tombs("bybit", "okx")))
C2 = mkcore()
recon("bybit", {"USDT": 845}, c=C2)
recon("okx", {"USDT": 845}, c=C2)
chk(snap("bybit", "okx") == snapV0 and not [r for r in snap("bybit", "okx") if r[0].endswith(":futpnl")],
    "U4 되돌린 뒤 새 core 로 대사 1회 → 원장 = 재배치 전(다시 적용 안 함)", [r for r in snap("bybit", "okx") if r not in snapV0][:6])
rc, out = tool("--json", os.path.join(T.TMP, "plan_u.json"))
chk(rc == 0 and "되돌린 원장" in out and "--apply" in out, "U5 미리보기 = '되돌린 원장 — --apply 로 다시 할 때의 계획'", out[-300:])
bk0 = set(glob.glob(os.path.join(BK, "ledger_pre_futplace_v*.db")))
rc, out = tool("--apply", "--expect", os.path.join(T.TMP, "plan_u.json"))
bk1 = set(glob.glob(os.path.join(BK, "ledger_pre_futplace_v*.db"))) - bk0
chk(rc == 0 and len(bk1) == 1 and "적용 전 원장 백업" in out and snap("bybit", "okx") == snapU1 and not str(C._meta_get("exf_fut_place_v")).startswith("1:undone"),
    "U6 --apply = 적용 전 원장 백업 1부(state/backups/ledger_pre_futplace_*) · 다시 적용(첫 적용과 같은 줄) · 표식 새로", (rc, out[-400:], sorted(bk1)))
if bk1:
    import sqlite3
    b9 = sqlite3.connect(next(iter(bk1)))
    nb9 = b9.execute("SELECT count(*) FROM postings WHERE location IN ('exchange:bybit','exchange:okx') AND source_ns LIKE '%:futpnl'").fetchone()[0]
    nrow9 = b9.execute("SELECT count(*) FROM postings WHERE location IN ('exchange:bybit','exchange:okx')").fetchone()[0]
    b9.close()
    chk(nb9 == 0 and nrow9 == len(snapV0), "U7 백업본 = 적용 직전 원장(선물 줄 0 · 행 수 = 재배치 전)", (nb9, nrow9, len(snapV0)))
rc, out = tool("--undo", UNDO)
mk9 = C._meta_get("exf_fut_place_v")
rc2, out2 = tool("--apply", "--no-backup")
bk2 = set(glob.glob(os.path.join(BK, "ledger_pre_futplace_v*.db"))) - bk0 - bk1
chk(rc == 0 and str(mk9).startswith("1:undone:") and rc2 == 0 and not bk2 and snap("bybit", "okx") == snapU1, "U8 --no-backup = 백업 없이 적용(배포 도구 경로)",
    (out[-200:], out2[-300:], sorted(bk2)))
C.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('exf_fut_place_v', '1:1790000000:1')")
C.conn.commit()
C3 = mkcore()
snapU9 = snap("bybit", "okx")
recon("bybit", {"USDT": 845}, c=C3)
recon("okx", {"USDT": 845}, c=C3)
chk(snap("bybit", "okx") == snapU9 and getattr(C3, "_exf_fut_place_scope", lambda: None)() == ("done", None) and once(C3) is None
    and C._meta_get("exf_fut_place_v") == "1:1790000000:1", "U9 라이브 모양 끝난 표식('1:1790000000:1') = 새 core 대사 뒤에도 원장·표식 무변(재적용·되돌림 0)",
    [r for r in snap("bybit", "okx") if r not in snapU9][:4])
rc, out = tool("--json", os.path.join(T.TMP, "plan_u9.json"))
chk(rc == 0 and "이미 적용" in out and "바뀌는 통화 0" in out, "U10 끝난 원장 미리보기 = '이미 적용' · 바뀌는 통화 0", out[-300:])
rc, out = tool("-h")
chk(rc == 0 and "usage:" in out and "--no-backup" in out, "U11 -h = 사용법만(원장 무접촉)", out[-300:])
s0 = snap("bybit", "okx")
rc, out = tool("--undo")
chk(rc == 2 and "usage:" in out and "Traceback" not in out and snap("bybit", "okx") == s0, "U12 --undo 경로 없음 = 사용법 오류(종전 IndexError) · 원장 무변", out[-300:])
rc, out = tool("--apply", "--help")
chk(rc == 0 and "usage:" in out and snap("bybit", "okx") == s0 and C._meta_get("exf_fut_place_v") == "1:1790000000:1",
    "U13 --apply --help = 사용법만 · 적용 안 함", out[-200:])

print("[W] 선물 정산 대기 시작 시각 = 재시작에도 이어짐 · 종전 규칙 동안 '주의' 유지")
WP = C.EXF_FUT_WAIT_PATH
CW = mkcore()
futfile("bybit", [], ts=NOW - 50)
balw = {"sources": ["futures"]}
t_w0 = NOW
held1 = CW._exf_fut_hold("bybit", balw, NOW, NOW - 600, t_w0)
since1 = (json.load(open(WP)).get("wait") or {}).get("bybit", {}).get("since")
CW2 = mkcore()
held2 = CW2._exf_fut_hold("bybit", balw, NOW, NOW - 600, t_w0 + 7200)
since2 = (json.load(open(WP)).get("wait") or {}).get("bybit", {}).get("since")
held3 = CW2._exf_fut_hold("bybit", balw, NOW, NOW - 600, t_w0 + 3 * 3600 + 60)
chk(held1 and held2 and since1 == t_w0 and since2 == t_w0 and not held3,
    "W1 재시작 뒤에도 대기 시작 = 처음 시각(2시간 뒤 재시작 → 1시간 더 기다리고 3시간에 종전 규칙 · 종전: 재시작마다 3시간 다시)", (held1, held2, held3, since1, since2))
wd = json.load(open(WP))
chk((wd.get("wait") or {}).get("bybit", {}).get("fallback") is True, "W2 종전 규칙 전환 = 대기 표식 fallback", wd.get("wait"))
t_late = t_w0 + 3 * 3600 + 60 + health.FUT_FB_SHOW_S + 3600
CW2._exf_fut_hold("bybit", balw, NOW, NOW - 600, t_late)
wd = json.load(open(WP))
wd["ts"] = int(t_late)
common.atomic_write_json(WP, wd)
hw = {c["cid"]: c for c in health.collect_fut_wait(t_late + 60)}
chk(hw.get("futwait:fb:bybit", {}).get("level") == "warn" and "대사 중" in hw["futwait:fb:bybit"]["title"],
    "W3 종전 규칙으로 물러난 지 하루가 넘어도 계속 물러나 있으면 '주의'(종전: 하루 뒤 초록)", hw.get("futwait:fb:bybit"))
futfile("bybit", [])
CW2._exf_fut_hold("bybit", balw, NOW - 100, NOW - 600, t_late + 120)
hw = {c["cid"]: c for c in health.collect_fut_wait(time.time())}
chk(not (json.load(open(WP)).get("wait") or {}).get("bybit") and hw.get("futwait:bybit", {}).get("level") == "ok",
    "W4 파일이 덮으면 대기 끝(표식 지움)", json.load(open(WP)).get("wait"))
C.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('exf_fut_place_v', '1:1790000000:2')")
C.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('exf_fut_place_wait', ?)", (json.dumps({"v": 1, "ex": {"okx": "선물 정산 파일 낡음"}}),))
C.conn.commit()
futfile("okx", [], ts=int(C._meta_get("recon_done_exf_okx")) - 100)
futfile("bybit", [], ts=SEQ["t"] - 50)
C5 = mkcore()
recon("bybit", {"USDT": 845}, c=C5)
wd = json.load(open(WP))
t_old = int(time.time()) - 7200
wd["wait"]["bybit"]["since"] = t_old
common.atomic_write_json(WP, wd)
C6 = mkcore()
d0 = C._meta_get("recon_done_exf_bybit")
recon("bybit", {"USDT": 845}, c=C6)
wd = json.load(open(WP))
chk(C._meta_get("recon_done_exf_bybit") == d0 and (wd.get("wait") or {}).get("bybit", {}).get("since") == t_old and "okx" in (wd.get("place") or {}),
    "W5 (fu406) 재시작 뒤 대사 주기(재배치 대기 저장이 먼저) = 대기 시작 시각 그대로(2시간 전) · 아직 대기 · 재배치 대기(okx) 표시",
    (C._meta_get("recon_done_exf_bybit"), d0, wd.get("wait"), t_old))
wd["wait"]["bybit"]["since"] = int(time.time()) - 3 * 3600 - 60
common.atomic_write_json(WP, wd)
C7 = mkcore()
recon("bybit", {"USDT": 845}, c=C7)
wd = json.load(open(WP))
chk(C._meta_get("recon_done_exf_bybit") != d0 and (wd.get("wait") or {}).get("bybit", {}).get("fallback") is True,
    "W6 (fu406) 재시작이 이어져도 처음 시작부터 3시간 = 종전 규칙으로 대사(대기가 재시작마다 밀리지 않음)", (C._meta_get("recon_done_exf_bybit"), d0, wd.get("wait")))
T.finish()
