#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import sqlite3
import subprocess
import time

sys.path.insert(0, os.path.join(T.ROOT, "tools"))
import common
import db as dbm
import inbox
import ledger_backup as lb
import ledger_restore as LR
import unit_runner as U

S = common.STATE_DIR
os.makedirs(os.path.join(S, "inbox"), exist_ok=True)


def ck(name, cond, extra=None):
    T.chk(bool(cond), name, extra)


def wj(name, obj):
    common.atomic_write_json(os.path.join(S, name), obj)


def rj(name):
    with open(os.path.join(S, name), encoding="utf-8") as f:
        return json.load(f)


def clear_state():
    import shutil
    for n in os.listdir(S):
        p = os.path.join(S, n)
        if os.path.isdir(p):
            shutil.rmtree(p)
        else:
            os.remove(p)
    os.makedirs(os.path.join(S, "inbox"), exist_ok=True)


def seg(stream, n, lines=1):
    d = os.path.join(S, "inbox", stream)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{n:09d}.jsonl"), "w", encoding="utf-8") as f:
        for i in range(lines):
            f.write(json.dumps({"kind": "x", "chain": "eth", "i": i}) + "\n")


class Stop(Exception):
    pass


def run_runner_once():
    got = {}

    def fake_popen(argv, env=None, **k):
        got["env"] = dict(env or {})
        raise Stop()

    def fake_sleep(_s):
        raise Stop()

    def fake_beat(unit, **kw):
        got.setdefault("beats", []).append(kw)
    real = (U.subprocess.Popen, U._sleep, U._beat, U._evaluate)
    U.subprocess.Popen, U._sleep, U._beat = fake_popen, fake_sleep, fake_beat
    U._evaluate = lambda unit: (True, "", "fp")
    U._stop["sig"] = None
    sys.argv = ["unit_runner.py", "core"]
    try:
        U.main()
    except Stop:
        pass
    finally:
        U.subprocess.Popen, U._sleep, U._beat, U._evaluate = real
    return got


clear_state()
g = run_runner_once()
ck("[1] 첫 설치(흔적 없음) = 빈 원장 허용(TJ_ALLOW_NEW_LEDGER=1)", (g.get("env") or {}).get("TJ_ALLOW_NEW_LEDGER") == "1", g)

clear_state()
os.makedirs(os.path.join(S, "backups"))
sqlite3.connect(os.path.join(S, "backups", "ledger_20261008.db")).execute("CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT)").connection.commit()
wj("cursor_evm_eth.json", {"0xaaa": 21000000})
g = run_runner_once()
ck("[1] 백업 있음 + 원장 없음 = 빈 원장 만들지 않음(core 안 띄움)", "env" not in g, g.get("env", {}).get("TJ_ALLOW_NEW_LEDGER"))
b9 = (g.get("beats") or [{}])[-1]
ck("[1] 하트비트 = 대기 · 복구 도구 안내", b9.get("state") == "waiting" and "ledger_restore" in str(b9.get("why")), b9)
ck("[1] 흔적 목록에 백업", any("백업" in e for e in b9.get("evidence") or []), b9)

clear_state()
open(os.path.join(S, "ledger.db.pre_extrebuild_20261008_000000"), "w").write("x")
ck("[1] 재구축 보존본만 남음 = 흔적", lb.prior_ledger_evidence() != [])
clear_state()
open(os.path.join(S, "ledger.db-wal"), "w").write("x")
ck("[1] 남은 -wal = 흔적", lb.prior_ledger_evidence() != [])

clear_state()
wj("cursor_evm_eth.json", {"0xaaa": 21000000})
wj("emitted_evm_eth.json", ["0x01"])
seg("evm", 1)
seg("evm", 2)
ck("[1] 수집기만 먼저 돈 첫 설치(인박스 1부터 다 있음) = 흔적 아님", lb.prior_ledger_evidence() == [], lb.prior_ledger_evidence())
g = run_runner_once()
ck("[1] … 그래서 빈 원장 허용(인박스를 처음부터 다시 읽음)", (g.get("env") or {}).get("TJ_ALLOW_NEW_LEDGER") == "1")

clear_state()
wj("cursor_evm_eth.json", {"0xaaa": 21000000})
seg("evm", 7)
ev = lb.prior_ledger_evidence()
ck("[1] 인박스 앞 세그먼트가 지워짐 = 흔적", any("인박스 evm" in e for e in ev), ev)
clear_state()
wj("emitted_sol.json", ["sig1"])
ck("[1] 보낸 기록은 있는데 인박스 비었음 = 흔적", any("sol" in e for e in lb.prior_ledger_evidence()))
clear_state()
wj("emitted_sol.json", [])
wj("cursor_sol.json", {"W": "sig"})
ck("[1] 보낸 기록이 비었고 인박스도 비었음 = 흔적 아님(빈 지갑 첫 설치)", lb.prior_ledger_evidence() == [], lb.prior_ledger_evidence())

clear_state()
os.makedirs(os.path.join(S, "backups"))
open(os.path.join(S, "backups", "backup_status.json"), "w").write("{}")
wj("daily_cache.json", {"x": 1})
rc = LR.new_ledger(apply_=True, log=lambda *a: None)
ck("[1] new --apply = 허용 표식", rc == 0 and os.path.exists(os.path.join(S, lb.NEW_LEDGER_OK)))
hd9 = json.load(open(os.path.join(S, common.HIST_DIRTY), encoding="utf-8")) if os.path.exists(os.path.join(S, common.HIST_DIRTY)) else None
ck("[1] new --apply = 일별 캐시 무효화 + 장기 곡선 처음부터 다시 계산 표식(it326)", not os.path.exists(os.path.join(S, "daily_cache.json"))
   and isinstance(hd9, dict) and hd9.get("from") == "1970-01-01", hd9)
g = run_runner_once()
ck("[1] 표식이 있으면 흔적이 있어도 한 번 허용", (g.get("env") or {}).get("TJ_ALLOW_NEW_LEDGER") == "1")
ck("[1] 표식은 한 번 쓰고 지움", not os.path.exists(os.path.join(S, lb.NEW_LEDGER_OK)))
wj(lb.NEW_LEDGER_OK, {"ts": int(time.time()) - 7200})
ck("[1] 1시간 지난 표식 = 무효", lb.new_ledger_ok() is False)

clear_state()
wj("cursor_evm_eth.json", {"0x" + "a1" * 20: 5000})
wj("emitted_evm_eth.json", ["0x01"])
saved_ru9 = LR.running_units
LR.running_units = lambda root=None: [(4242, "evm_watch.py")]
try:
    try:
        r9 = LR.new_ledger(True, True, log=lambda *a: None)
    except SystemExit as e9:
        r9 = "거부: " + str(e9)
finally:
    LR.running_units = saved_ru9
ck("[1] new --fresh-collect + 수집기 떠 있음 = 거부(정지 안내) · 파일 그대로 · 표식 없음(it329)",
   isinstance(r9, str) and "pm2 stop" in r9 and os.path.exists(os.path.join(S, "cursor_evm_eth.json"))
   and not os.path.exists(os.path.join(S, lb.NEW_LEDGER_OK)), r9)
LR.running_units = lambda root=None: [(4243, "unit_runner.py core"), (4244, "web.py")]
try:
    r9 = T.safe(LR.new_ledger, True, True, log=lambda *a: None)
finally:
    LR.running_units = saved_ru9
ck("[1] 원장 없음으로 기다리는 core 러너·웹만 떠 있음 = 허용(커서 옆으로 · 표식)", r9 == 0 and not os.path.exists(os.path.join(S, "cursor_evm_eth.json"))
   and os.path.exists(os.path.join(S, lb.NEW_LEDGER_OK)), r9)

clear_state()
live = common.DB_PATH


def mkdb(path, rows=1, tag="x"):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE IF NOT EXISTS t(a)")
    for i in range(rows):
        c.execute("INSERT INTO t VALUES(?)", (f"{tag}{i}",))
    c.commit()
    c.close()


mkdb(live, 3, "old")
ino_old = os.stat(live).st_ino
open(live + "-wal", "w").write("")
mkdb(live + ".new", 5, "new")
res = lb.swap_in(live, live + ".new", live + ".pre_test")
ck("[2] 교체 뒤 원장 = 새 내용", sqlite3.connect(live).execute("SELECT count(*) FROM t").fetchone()[0] == 5)
ck("[2] 옛 원장 = 하드 링크(같은 inode · 복사 없음)", res["linked"] and os.stat(live + ".pre_test").st_ino == ino_old)
ck("[2] 옛 -wal 은 보존본 짝 이름으로(새 원장 옆에 남지 않음)", os.path.exists(live + ".pre_test-wal") and not os.path.exists(live + "-wal"))
ck("[2] 임시 파일 없어짐", not os.path.exists(live + ".new"))

mkdb(live + ".new2", 7, "n2")
real_replace = os.replace
calls = []


def bad_replace(a, b):
    calls.append((a, b))
    if os.path.abspath(b) == os.path.abspath(live):
        raise OSError("시험: 마지막 교체 실패")
    return real_replace(a, b)


os.replace = bad_replace
try:
    try:
        lb.swap_in(live, live + ".new2", live + ".pre_test2")
        fail_raised = False
    except OSError:
        fail_raised = True
finally:
    os.replace = real_replace
ck("[2] 마지막 교체가 실패해도 원장 자리가 비지 않음(옛 원장 그대로)", fail_raised and os.path.exists(live)
   and sqlite3.connect(live).execute("SELECT count(*) FROM t").fetchone()[0] == 5)
ck("[2] 교체 이름 바꾸기는 한 번만 시도(원장 → 보존본 이름 바꾸기 없음)", not any(os.path.abspath(a) == os.path.abspath(live) for a, _b in calls), calls)

import core
mkdb(live + ".extnew_X", 2, "ext")
ino_now = os.stat(live).st_ino
core.Core._ext_swap(live, live + ".extnew_X", "20261009_000000")
ck("[2] core 재구축 교체도 같은 방식(보존본 = 같은 inode)", os.stat(live + ".pre_extrebuild_20261009_000000").st_ino == ino_now
   and sqlite3.connect(live).execute("SELECT count(*) FROM t").fetchone()[0] == 2)

lw = os.path.join(T.TMP, "walswap", "ledger.db")
os.makedirs(os.path.dirname(lw))
subprocess.run([sys.executable, "-c", r'''
import sqlite3, sys, os
c = sqlite3.connect(sys.argv[1]); c.execute("PRAGMA journal_mode=WAL"); c.execute("CREATE TABLE t(a)"); c.commit()
c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
for i in range(5): c.execute("INSERT INTO t VALUES (?)", (i,))
c.commit()
os._exit(0)
''', lw], check=True)
ck("[2] (전제) 옛 원장 -wal 에 커밋 5행", os.path.getsize(lw + "-wal") > 0)
mkdb(lw + ".new", 9, "n")
os.replace = lambda a, b: (_ for _ in ()).throw(OSError("시험: 마지막 교체 실패")) if os.path.abspath(b) == os.path.abspath(lw) else real_replace(a, b)
try:
    try:
        lb.swap_in(lw, lw + ".new", lw + ".pre_x")
        raised9 = False
    except OSError:
        raised9 = True
finally:
    os.replace = real_replace
wal9 = os.path.exists(lw + "-wal")


def _cnt9():
    c9 = sqlite3.connect(lw)
    try:
        return c9.execute("SELECT count(*) FROM t").fetchone()[0]
    finally:
        c9.close()


n9 = T.safe(_cnt9)
ck("[2] 교체 실패 뒤 옛 원장 = 자기 WAL 커밋까지(5행) — wl314 ②", raised9 and n9 == 5 and wal9, (raised9, n9, wal9))
ck("[2] 교체 실패 = 보존본 링크 정리(옛 원장 그대로라 필요 없음)", not os.path.exists(lw + ".pre_x") and not os.path.exists(lw + ".pre_x-wal"))

pw = os.path.join(T.TMP, "walsrc.db")
subprocess.run([sys.executable, "-c", r'''
import sqlite3, sys, os
c = sqlite3.connect(sys.argv[1]); c.execute("PRAGMA journal_mode=WAL"); c.execute("CREATE TABLE t(a)"); c.commit()
c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
c.execute("INSERT INTO t VALUES (1)"); c.execute("INSERT INTO t VALUES (2)"); c.commit()
os._exit(0)
''', pw], check=True)
ck("[2] (전제) -wal 에 커밋이 남음", os.path.getsize(pw + "-wal") > 0)
LR.copy_ledger(pw, pw + ".copy")
ck("[2] 복원 복사 = WAL 몫까지(2행) · 단일 파일 · 0600", sqlite3.connect(common.sqlite_ro_uri(pw + ".copy", immutable=True), uri=True)
   .execute("SELECT count(*) FROM t").fetchone()[0] == 2 and not os.path.exists(pw + ".copy-wal") and (os.stat(pw + ".copy").st_mode & 0o777) == 0o600)

clear_state()
d = os.path.join(S, "inbox", "evm")
for n in (1, 2, 3, 4):
    seg("evm", n)
rd = inbox.SegmentReader(d)
rd.gc(4, 0)
ck("[3] 다 읽은 세그먼트도 보존 기간 안이면 남김", rd._segs() == [1, 2, 3, 4], rd._segs())
old_t = time.time() - 9 * 86400
os.utime(os.path.join(d, f"{1:09d}.jsonl"), (old_t, old_t))
rd.gc(4, 0)
ck("[3] 보존 기간(8일) 지난 것은 지움", rd._segs() == [2, 3, 4], rd._segs())
os.environ["TJ_INBOX_RETAIN_DAYS"] = "0"
rd.gc(4, 0)
ck("[3] TJ_INBOX_RETAIN_DAYS=0 = 종전처럼 바로 지움 · 활성(최신) 세그먼트는 남김", rd._segs() == [4], rd._segs())
del os.environ["TJ_INBOX_RETAIN_DAYS"]
for n in (5, 6, 7):
    seg("evm", n, lines=3)
saved = inbox.RETAIN_MAX_BYTES
inbox.RETAIN_MAX_BYTES = os.path.getsize(os.path.join(d, f"{6:09d}.jsonl")) + 1
rd.gc(7, 0)
inbox.RETAIN_MAX_BYTES = saved
ck("[3] 보존 크기 상한 = 새 것부터 남기고 오래된 것 지움", rd._segs() == [6, 7], rd._segs())

NOW = int(time.time())
T_BK = NOW - 3 * 86400
W1, W2, WNEW = "0x" + "a1" * 20, "0x" + "b2" * 20, "0x" + "c3" * 20
def SIG(n):
    return "5" + "Kx9mQ" * 17 + str(n)


SOLW, ATA, STK = "So1Wallet1111111111111111111111111111111111", "Ata1111111111111111111111111111111111111111", "Stk1111111111111111111111111111111111111111"


def make_backup(path):
    c = dbm.open_db(path)
    c.execute("INSERT INTO wallets VALUES('eth', ?, 'a', 0)", (W1,))
    c.execute("INSERT INTO wallets VALUES('eth', ?, 'b', 0)", (W2,))
    c.execute("INSERT INTO wallets VALUES('sol', ?, 's', 0)", (SOLW,))
    c.execute("INSERT INTO wallets VALUES('bsc', ?, 'c', 0)", (W1,))

    def tx(chain, h, blk, ts, snap=None, ing=None):
        c.execute("INSERT INTO raw_txs VALUES(?,?,?,?,?,?,?,?)", (chain, h, blk, None, ts, json.dumps(snap or {}), "[]", ing or T_BK))
    tx("eth", "0xE1", 1000, None, ing=T_BK - 20 * 3600)
    tx("eth", "0xE2", 1100, None, ing=T_BK - 13 * 3600)
    tx("eth", "0xE3", 1200, None, ing=T_BK - 1 * 3600)
    tx("bsc", "0xB1", 50000, None)
    tx("sol", SIG(1), 900, T_BK - 30 * 3600, {"fee_payer": SOLW, "deltas": []})
    tx("sol", SIG(2), 950, T_BK - 14 * 3600, {"fee_payer": "x", "deltas": [
        {"asset": "native", "owner": SOLW, "delta": "5"}, {"asset": "native", "owner": f"{SOLW}:stake:{STK}", "delta": "1"}]})
    tx("sol", SIG(3), 990, T_BK - 2 * 3600, {"fee_payer": SOLW, "deltas": []})
    tx("sol", f"stakerwd:{STK}:800", 960, T_BK - 13 * 3600, {"deltas": [{"asset": "native", "owner": f"{SOLW}:stake:{STK}", "delta": "7"},
                                                                    {"asset": "native", "owner": SOLW, "delta": "1"}]})
    ex = [("upbit", "order", "U1", 1, {}), ("binance", "trade", "binance:BTCUSDT:500", 1, {}), ("binance", "trade", "binance:m:ETHUSDT:70", 1, {}),
          ("binance", "deposit", "binance:D1", 1, {"state": "PENDING"}), ("binance", "withdraw", "binance:W1", 1, {"state": "DONE", "txid": "0xabc"})]
    for e in ex:
        c.execute("INSERT INTO raw_ex VALUES(?,?,?,?,?,?)", (e[0], e[1], e[2], e[3], json.dumps(e[4]), T_BK))
    c.execute("INSERT INTO inbox_offsets VALUES('evm', 2, 10)")
    c.execute("INSERT INTO inbox_offsets VALUES('sol', 1, 0)")
    c.execute("INSERT INTO inbox_offsets VALUES('bsc', 1, 0)")
    c.execute("INSERT INTO inbox_offsets VALUES('ex', 3, 0)")
    c.commit()
    c.execute("PRAGMA journal_mode=DELETE")
    c.close()


def state_files():
    wj("cursor_evm_eth.json", {W1: 5000, W2: 5000, WNEW: 5000, "_cov:" + W1: 10, "_disc:" + W1: {"x": 1}, "_cov:" + WNEW: 10,
                               "_synced_at": NOW, "_synced_tok_at": NOW})
    wj("emitted_evm_eth.json", ["0xe1", "0xe2", "0xe3", "0xe4new"])
    wj("cursor_sol.json", {SOLW: SIG(9), "_slot:" + SOLW: 1500, "_pnv:" + SOLW: {"x": 1}, ATA: "atasig9", "_slot:" + ATA: 1490,
                           STK: "stksig9", "_stk:" + STK: {"w": SOLW, "rwd_next": 800}, "_synced_at": NOW,
                           "_fbw:ATANEW": {"o": SOLW, "s": 1400}, "_hl:ATANEW": {"o": SOLW, "sig": "atanew9", "slot": 1495}})
    wj("emitted_sol.json", [SIG(1), SIG(2), SIG(3), SIG(9), f"stakerwd:{STK}:800"])
    wj("cursor_bsc.json", {"from_block": 900000, "head": 900020, "_cov": 1000, "_synced_at": NOW, "_scan": {"a": 1},
                           "_live": {"done": 950000, "holes": [[900000, 940000]], "fb": 900000}, "_lscan": {"frm": 950001}})
    wj("emitted_bsc.json", ["0xb1", "0xb2new"])
    wj("bsc_nonce.json", {"w": {W1: {"hashes": {"0xb1": 50000, "0xb2new": 899000}, "blocks": [50000, 899000], "missing": 1}}, "boot": 1})
    wj("bsc_xin.json", {"tx": {"0xb2new": {"r": "emit"}, "0xb1": {"r": "emit"}, "0xold": {"r": "old"}}})
    wj("upbit_orders_state.json", {"backfilled_until": NOW - 3600, "complete": True, "uuids": ["U1", "U2new"], "open_track": {}})
    wj("exf_state.json", {"binance": {"seen": {"binance:D1": "DONE", "binance:W1": "DONE", "binance:D9new": "DONE"},
                                      "seen_txids": {"binance:D1": True, "binance:W1": True}, "backfilled_until": NOW,
                                      "fills": {"seen": {"binance:BTCUSDT:500": 1, "binance:BTCUSDT:501": 2, "binance:SOLUSDT:9": 3},
                                                "backfilled_until": NOW, "pair_cursor": {"BTCUSDT": 502, "SOLUSDT": 10},
                                                "margin_cursor": {"c:ETHUSDT": 80}, "cv": {"bf": 1, "until": NOW}}},
                          "hyperliquid": {"seen_led": {"u:old": (T_BK - 20 * 3600) * 1000, "u:new": NOW * 1000},
                                          "hl": {"0xh": {"led": {"next": NOW * 1000}, "fil": {"next": NOW * 1000}}},
                                          "fills": {"seen": {"hyperliquid:f1": NOW * 1000}}}})
    wj("exf_balances_binance.json", {"ts": NOW, "balances": {}})
    wj("daily_cache.json", {"x": 1})
    wj("ui_prefs.json", {})


clear_state()
os.makedirs(os.path.join(S, "backups"))
BK = os.path.join(S, "backups", "ledger_20261006.db")
make_backup(BK)
mkdb(live, 1, "cur")
ino_cur = os.stat(live).st_ino
state_files()
for n in (2, 3):
    seg("evm", n)
seg("ex", 3)
seg("sol", 1)
seg("bsc", 1)
before = {n: open(os.path.join(S, n), "rb").read() for n in os.listdir(S) if n.endswith(".json") and n != "daily_cache.json"}
rows = LR.backups()
ck("[4] 목록 = 정기 백업", [r["name"] for r in rows] == ["backups/ledger_20261006.db"], rows)
p = LR.plan(BK)
ck("[4] 인박스에 백업 위치가 다 남음 = 되감기 없음", p["rewind"] == [] and all(v["state"] == "replay" for v in p["coverage"].values()), p["coverage"])
after_preview = {n: open(os.path.join(S, n), "rb").read() for n in before}
ck("[6] 미리보기(계획)는 아무것도 안 바꿈", after_preview == before and os.stat(live).st_ino == ino_cur)
rec = LR.apply(p, proc_check=False, log=lambda *a: None)
c = sqlite3.connect(common.sqlite_ro_uri(live), uri=True)
ck("[4] 원장 = 백업 내용(inbox_offsets 포함 — core 가 그 위치부터 다시 읽음)",
   c.execute("SELECT seg, off FROM inbox_offsets WHERE stream='evm'").fetchone() == (2, 10))
c.close()
ck("[4] 이전 원장 보존(하드 링크)", rec["kept"] and os.stat(rec["kept"]).st_ino == ino_cur)
ck("[4] 수집기 상태 파일 그대로", {n: open(os.path.join(S, n), "rb").read() for n in before} == before)
ck("[4] 일별 캐시 무효화", not os.path.exists(os.path.join(S, "daily_cache.json")))
hd9 = json.load(open(os.path.join(S, common.HIST_DIRTY), encoding="utf-8")) if os.path.exists(os.path.join(S, common.HIST_DIRTY)) else None
ck("[4] 장기 곡선 처음부터 다시 계산 표식(hist_dirty — it326: 옛 원장 기준 창 밖 동결 행이 남지 않게)", isinstance(hd9, dict) and hd9.get("from") == "1970-01-01", hd9)
ck("[4] 기록 plan.json · 잠금 해제", os.path.exists(os.path.join(rec["originals"], "plan.json")) and not os.path.exists(os.path.join(S, "restore.lock")))
ck("[4] 백업 파일은 그대로(복사해서 씀)", os.path.exists(BK))

clear_state()
os.makedirs(os.path.join(S, "backups"))
make_backup(BK)
mkdb(live, 1, "cur")
state_files()
with open(common.CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump({"wallets": [{"type": "sol", "address": SOLW}]}, f)
for st9, n in (("evm", 9), ("sol", 4), ("bsc", 6), ("ex", 8)):
    seg(st9, n)
p = LR.plan(BK, now=NOW)
ck("[5] 인박스 앞부분 지워짐 = 네 스트림 모두 되감기", sorted(p["rewind"]) == ["bsc", "evm", "ex", "sol"], p["coverage"])
ck("[5] 기준 시각 = 백업 데이터 시각 · 여유 12시간", p["T"] == T_BK and p["cut"] == T_BK - 12 * 3600, (p["T"], p["cut"]))
rec = LR.apply(p, proc_check=False, log=lambda *a: None)
ce = rj("cursor_evm_eth.json")
ck("[5] EVM 지갑 커서 = 여유 이전에 들어온 마지막 블록(1100 · ts 없는 실제 모양)", ce.get(W1) == 1100 and ce.get(W2) == 1100, ce)
ck("[5] EVM 백업 뒤 넣은 지갑 = 기록 지움(새 지갑처럼)", WNEW not in ce and "_cov:" + WNEW not in ce, ce)
ck("[5] EVM 동기화 도장·발견 체크포인트 지움 · 창 하한 유지", "_synced_at" not in ce and "_synced_tok_at" not in ce and "_disc:" + W1 not in ce
   and ce.get("_cov:" + W1) == 10, ce)
ck("[5] EVM 방출 기록 = 백업에 있는 것만", rj("emitted_evm_eth.json") == ["0xe1", "0xe2", "0xe3"], rj("emitted_evm_eth.json"))
ck("[5] 쉬는 지갑 깨우기 요청", "*" in (rj("addr_tier_req.json").get("reqs") or {}))
cs = rj("cursor_sol.json")
ck("[5] 솔라나 지갑 커서 = 여유 이전 그 지갑이 낀 마지막 서명(+ 슬롯) · 대조 장부 지움",
   cs.get(SOLW) == SIG(2) and cs.get("_slot:" + SOLW) == 950 and "_pnv:" + SOLW not in cs, cs)
ck("[5] 솔라나 스테이크 계정 커서 = 그 계정 잔고가 바뀐 서명", cs.get(STK) == SIG(2), cs)
ck("[5] 솔라나 토큰 계정 커서 = 지움(목록 처음부터 · 방출 기록이 거름)", ATA not in cs and "_slot:" + ATA not in cs, cs)
ck("[5] 솔라나 스테이킹 보상 다음 에폭 낮춤", cs["_stk:" + STK]["rwd_next"] < 800, cs["_stk:" + STK])
ck("[5] 솔라나 첫 백필 진행 표식·엿보기 기준(_fbw·_hl) 지움(되감은 원장 = 처음부터 새 관점으로 다시 읽음 · sollive1010)",
   not [k for k in cs if k.startswith(("_fbw:", "_hl:"))], [k for k in cs if k.startswith(("_fbw:", "_hl:"))])
ck("[5] 솔라나 방출 기록 = 백업에 있는 것만(합성 보상 ID 포함)", rj("emitted_sol.json") == [SIG(1), SIG(2), SIG(3), f"stakerwd:{STK}:800"], rj("emitted_sol.json"))
ck("[5] 합성 ID(stakerwd:…)는 서명 커서로 안 씀(wl316 ①)", not any(str(v).startswith(("stakerwd:", "stakeopen:")) for v in cs.values()), cs)
cb = rj("cursor_bsc.json")
ck("[5] BSC from_block 되감음(창 하한 위) · 체크포인트·도장 지움", 1000 <= cb["from_block"] < 900000 and "_scan" not in cb and "_synced_at" not in cb, cb)
ck("[5] BSC 라이브 차선 기록(_live·_lscan) 지움 — 되감기 기준 뒤를 받은 것으로 남기지 않음(bsclive1010)", "_live" not in cb and "_lscan" not in cb, cb)
ck("[5] BSC 방출 기록·발신 색인·출금 회수 기록 = 백업 것만", rj("emitted_bsc.json") == ["0xb1"]
   and list(rj("bsc_nonce.json")["w"][W1]["hashes"]) == ["0xb1"] and "missing" not in rj("bsc_nonce.json")["w"][W1]
   and "0xb2new" not in rj("bsc_xin.json")["tx"] and "0xold" in rj("bsc_xin.json")["tx"])
up = rj("upbit_orders_state.json")
ck("[5] 업비트 주문 uuid = 백업 것만 · 창 시작 앞당김 · 완료 도장 내림", up["uuids"] == ["U1"] and up["backfilled_until"] <= p["cut"] - 30 * 86400
   and up["complete"] is False, up)
xb = rj("exf_state.json")["binance"]
ck("[5] 해외 입출금 seen = 백업 마지막 상태(D1 PENDING → DONE 다시 보냄) · 백업에 없는 행 지움",
   xb["seen"] == {"binance:D1": "PENDING", "binance:W1": "DONE"}, xb["seen"])
ck("[5] txid 표시도 백업 기준", xb["seen_txids"] == {"binance:W1": True}, xb["seen_txids"])
ck("[5] 체결 seen = 백업 것만 · 창 시작 = 여유 이전", list(xb["fills"]["seen"]) == ["binance:BTCUSDT:500"]
   and xb["fills"]["backfilled_until"] == p["cut"] and xb["backfilled_until"] == p["cut"] and xb["fills"]["cv"]["until"] == p["cut"], xb["fills"])
ck("[5] 바이낸스 페어 커서 = 백업 마지막 id + 1 · 백업에 없는 페어 = 0 · 마진 커서도",
   xb["fills"]["pair_cursor"] == {"BTCUSDT": 501, "SOLUSDT": 0} and xb["fills"]["margin_cursor"] == {"c:ETHUSDT": 71}
   and xb["fills"]["pair_chk"].get("BTCUSDT") == 0, xb["fills"])
xh = rj("exf_state.json")["hyperliquid"]
ck("[5] 하이퍼리퀴드 커서 = 여유 이전 · 그 뒤에 본 기록 지움", xh["hl"]["0xh"]["led"]["next"] == p["cut"] * 1000
   and list(xh["seen_led"]) == ["u:old"] and xh["fills"]["seen"] == {}, xh)
ck("[5] 해외 잔고 스냅숏 치움(다시 받기 전 대사 방지)", not os.path.exists(os.path.join(S, "exf_balances_binance.json")))
ck("[5] 바꾼 파일 원본 보존", os.path.exists(os.path.join(rec["originals"], "cursor_evm_eth.json"))
   and os.path.exists(os.path.join(rec["originals"], "exf_balances_binance.json")))
ck("[5] 원장 = 백업", sqlite3.connect(common.sqlite_ro_uri(live), uri=True).execute("SELECT count(*) FROM raw_txs").fetchone()[0] == 8)

clear_state()
os.makedirs(os.path.join(S, "backups"))
make_backup(BK)
c9 = sqlite3.connect(BK)
c9.execute("UPDATE inbox_offsets SET seg=400, off=12000 WHERE stream='evm'")
c9.commit()
c9.close()
state_files()
with open(common.CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump({"wallets": []}, f)
seg("evm", 1, lines=2)
seg("evm", 2, lines=1)
for st9 in ("sol", "bsc", "ex"):
    seg(st9, 1)
p = LR.plan(BK, now=NOW)
ck("[7] 인박스 잃음 = evm gap", p["coverage"]["evm"]["state"] == "gap", p["coverage"]["evm"])
LR.apply(p, proc_check=False, log=lambda *a: None)
c9 = sqlite3.connect(common.sqlite_ro_uri(live), uri=True)
row9 = c9.execute("SELECT seg, off FROM inbox_offsets WHERE stream='evm'").fetchone()
c9.close()
seg0, off0 = row9 if row9 else (1, 0)
got9, _s9, _o9 = inbox.SegmentReader(os.path.join(S, "inbox", "evm")).read_batch(seg0, off0)
ck("[7] 복구 뒤 core 가 새 인박스를 처음부터 읽음(3건 — wl314 ①)", len(got9) == 3, (row9, len(got9)))
ck("[7] 이어읽기 스트림(sol)은 백업 위치 그대로", sqlite3.connect(common.sqlite_ro_uri(live), uri=True)
   .execute("SELECT seg, off FROM inbox_offsets WHERE stream='sol'").fetchone() == (1, 0))
ck("[7] 복구 원장 단일 파일(-wal 없음)", not os.path.exists(live + "-wal") or os.path.getsize(live + "-wal") == 0)
clear_state()
seg("evm", 2, lines=1)
cv9 = LR.coverage({"evm": (2, 99999)}, os.path.join(S, "inbox"))
ck("[7] 같은 번호 세그먼트가 백업 위치보다 짧음 = gap", cv9["evm"]["state"] == "gap", cv9["evm"])

fake = os.path.join(T.TMP, "fakeinst")
os.makedirs(os.path.join(fake, "src"))
with open(os.path.join(fake, "src", "core.py"), "w") as f:
    f.write("import time\ntime.sleep(60)\n")
pr = subprocess.Popen([sys.executable, os.path.join(fake, "src", "core.py")])
try:
    time.sleep(0.5)
    run = LR.running_units(fake)
    ck("[6] 떠 있는 core 를 찾음(경로로 이 설치만)", run is not None and any(pid == pr.pid for pid, _n in run), run)
    ck("[6] 다른 설치 경로는 안 잡음", not any(pid == pr.pid for pid, _n in (LR.running_units(os.path.join(T.TMP, "other")) or [])))
finally:
    pr.kill()
    pr.wait()
os.makedirs(os.path.join(S, "backups"), exist_ok=True)
if not os.path.exists(BK):
    make_backup(BK)
saved_ru = LR.running_units
LR.running_units = lambda root=None: [(4242, "core.py")]
try:
    try:
        LR.apply(LR.plan(BK), proc_check=True, log=lambda *a: None)
        refused = False
    except SystemExit as e:
        refused = "pm2 stop" in str(e)
    ck("[6] 유닛이 떠 있으면 적용 거부(정지 안내)", refused)
finally:
    LR.running_units = saved_ru
import contextlib
import io


def run_cli(argv):
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            rc = LR.main(argv)
        return rc, out.getvalue(), None
    except SystemExit as e:
        return (e.code if isinstance(e.code, int) else str(e.code)), out.getvalue(), None
    except Exception as e:
        return None, out.getvalue(), type(e).__name__


clear_state()
os.makedirs(os.path.join(S, "backups"))
Z0 = os.path.join(S, "backups", "ledger_20261001.db")
open(Z0, "wb").close()
GB = os.path.join(S, "backups", "ledger_20261002.db")
with open(GB, "wb") as f:
    f.write(os.urandom(64 * 1024))
r9 = run_cli(["check", GB])
ck("[8] ① 깨진 백업 check = '열기 실패'(traceback 없음)", r9[2] is None and r9[0] == 1 and "열기 실패" in r9[1], r9)
r9 = run_cli(["restore", GB])
ck("[8] ① 깨진 백업 restore = '열기 실패' 거부(traceback 없음)", r9[2] is None and "열기 실패" in str(r9[0]), r9)
r9 = run_cli(["restore", Z0, "--rewind", "all"])
ck("[8] ① 0바이트 백업 restore(되감기 포함) = '원장 백업이 아니에요' 거부(traceback 없음)", r9[2] is None and "원장 백업이 아니에요" in str(r9[0]), r9)
r9 = run_cli(["list"])
ck("[8] ① list 는 깨진 것도 한 줄로(열기 실패 표시)", r9[2] is None and r9[0] == 0, r9)

clear_state()
os.makedirs(os.path.join(S, "backups"))
make_backup(BK)
mkdb(live, 1, "cur")
c9 = sqlite3.connect(live)
c9.execute("CREATE TABLE decisions (decision_id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, target TEXT NOT NULL, payload TEXT NOT NULL, created_at INTEGER NOT NULL)")
for at9 in (T_BK - 86400, T_BK + 60, NOW - 60):
    c9.execute("INSERT INTO decisions (kind, target, payload, created_at) VALUES ('x', 't', '{}', ?)", (at9,))
c9.commit()
c9.close()
state_files()
for n in (2, 3):
    seg("evm", n)
seg("ex", 3)
seg("sol", 1)
seg("bsc", 1)
p9 = LR.plan(BK, now=NOW)
ck("[8] ④ 미리보기 = 백업 뒤 판정 수(되돌리면 사라짐)", p9.get("decisions_after") == 2, p9.get("decisions_after"))
real_strftime = time.strftime
time.strftime = lambda fmt, *a: "20261009_120000" if fmt == "%Y%m%d_%H%M%S" else real_strftime(fmt, *a)
res9 = []
try:
    for _ in range(3):
        res9.append(T.safe(LR.apply, LR.plan(BK, now=NOW), proc_check=False, log=lambda *a: None))
finally:
    time.strftime = real_strftime
ck("[8] ② 같은 초에 세 번 적용 = 모두 끝까지(기록 폴더 _2·_3) · 잠금 파일 안 남음",
   all(isinstance(r, dict) and "originals" in r for r in res9) and not os.path.exists(os.path.join(S, "restore.lock"))
   and len({r.get("originals") for r in res9 if isinstance(r, dict)}) == 3, res9)
pre9 = sorted(n for n in os.listdir(S) if n.startswith("ledger.db.pre_restore_") and not n.endswith(("-wal", "-shm")))
ck("[8] ③ 복구 전 보존본 = 최근 2개만(오래된 것 정리)", len(pre9) == 2 and any(n.endswith("_3") for n in pre9), pre9)

clear_state()
os.makedirs(os.path.join(S, "backups", "files_20261008"))
fd9 = os.path.join(S, "backups", "files_20261008")
for n9, v9 in (("daily_px.json", {"2026-10-07": {"BTC": 1}}), ("settings.json", {"tg": {"chat": "x"}}),
               ("seed_local__ticker_aliases.json", {"A": "B"}), ("config_subset.json", {"wallets": []}), ("evil.sh", "x")):
    with open(os.path.join(fd9, n9), "w", encoding="utf-8") as f:
        json.dump(v9, f)
with open(os.path.join(S, "backups", "prefs_20261008.json"), "w", encoding="utf-8") as f:
    json.dump({"ts": 1, "decisions": [{"kind": "x"}], "ui_prefs": {"hide": True}, "outflow_decisions": {"0xa": "mine"}}, f)
wj("daily_px.json", {"2026-10-07": {"BTC": 999}})
wj("daily_cache.json", {"x": 1})
r9 = run_cli(["files"])
ck("[8] ⑥ files = 사본 날짜 목록", r9[2] is None and r9[0] == 0 and "20261008" in r9[1], r9)
r9 = run_cli(["files", "20261008"])
ck("[8] ⑥ files <날짜> = 미리보기(아무것도 안 바꿈)", r9[2] is None and r9[0] == 0 and rj("daily_px.json") == {"2026-10-07": {"BTC": 999}}
   and "daily_px.json" in r9[1] and "config.json" in r9[1], r9)
saved_ru = LR.running_units
LR.running_units = lambda root=None, **k: [(4242, "web.py")]
try:
    r9 = run_cli(["files", "20261008", "--apply"])
finally:
    LR.running_units = saved_ru
ck("[8] ⑥ tj-web 이 떠 있으면 적용 거부", r9[2] is None and "pm2 stop tj-web" in str(r9[0]) and rj("daily_px.json")["2026-10-07"]["BTC"] == 999, r9)
r9 = run_cli(["files", "20261008", "--apply", "--no-proc-check"])
kept9 = [n for n in os.listdir(S) if n.startswith("restore_files_")]
ck("[8] ⑥ 적용 = 지난날 고정가·설정·seed_local·화면 설정·보낸 내역 판정 되돌림",
   r9[2] is None and r9[0] == 0 and rj("daily_px.json") == {"2026-10-07": {"BTC": 1}} and rj("settings.json") == {"tg": {"chat": "x"}}
   and rj(os.path.join("seed_local", "ticker_aliases.json")) == {"A": "B"} and rj("ui_prefs.json") == {"hide": True}
   and rj("outflow_decisions.json") == {"0xa": "mine"}, r9)
ck("[8] ⑥ 이름 규칙 밖 파일·설정 부분 사본은 자동으로 안 씀", not os.path.exists(os.path.join(S, "evil.sh")) and not os.path.exists(os.path.join(S, "config_subset.json")))
ck("[8] ⑥ 지금 파일은 restore_files_<시각>/ 에 먼저 보존 · 고정가가 바뀌면 곡선 캐시 무효화",
   len(kept9) == 1 and json.load(open(os.path.join(S, kept9[0], "daily_px.json"), encoding="utf-8")) == {"2026-10-07": {"BTC": 999}}
   and not os.path.exists(os.path.join(S, "daily_cache.json")), kept9)
open(os.path.join(fd9, "daily_px.json"), "w", encoding="utf-8").write('{"2026-10-07": {"BTC": 1')
wj("daily_px.json", {"2026-10-07": {"BTC": 777}})
wj("settings.json", {"tg": {"chat": "now"}})
r9 = run_cli(["files", "20261008", "--apply", "--no-proc-check"])
ck("[8] op405 ② 깨진 사본(잘린 daily_px) 하나 = 전체 거부 · 지금 파일 무변 · 보존 폴더 안 만듦",
   r9[2] is None and "깨진 사본" in str(r9[0]) and rj("daily_px.json") == {"2026-10-07": {"BTC": 777}} and rj("settings.json") == {"tg": {"chat": "now"}}
   and len([n for n in os.listdir(S) if n.startswith("restore_files_")]) == 1, r9)
r9 = run_cli(["files", "20261008"])
ck("[8] op405 ② 미리보기에 깨진 사본 표시", r9[2] is None and "깨짐" in r9[1] and "daily_px.json" in r9[1], r9)
with open(os.path.join(fd9, "daily_px.json"), "w", encoding="utf-8") as f:
    json.dump({"2026-10-07": {"BTC": 1}}, f)
LR.running_units = lambda root=None, **k: [(4243, "review_daily.py")] if "review_daily.py" in (k.get("scripts") or ()) else []
try:
    r9 = run_cli(["files", "20261008", "--apply"])
finally:
    LR.running_units = saved_ru
ck("[8] op405 ③ tj-review(review_daily.py)가 떠 있으면 files 적용 거부(정지 안내)", r9[2] is None and "pm2 stop tj-web tj-review" in str(r9[0])
   and "review_daily.py" in str(r9[0]) and rj("daily_px.json") == {"2026-10-07": {"BTC": 777}}, r9)
ck("[8] op405 ③ 원장 되돌리기(restore)는 tj-review 를 막지 않음(원장을 안 씀) — 기본 검사 목록에 없음", "review_daily.py" not in LR.UNIT_SCRIPTS)
r9 = run_cli(["files", "2026-10-08"])
ck("[8] ⑥ 날짜 형식이 틀리면 안내(traceback 없음)", r9[2] is None and "YYYYMMDD" in str(r9[0]), r9)
T.finish()
