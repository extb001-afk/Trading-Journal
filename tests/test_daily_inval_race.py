#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True


def _core_child(src: str, rec_json: str) -> int:
    import json
    import os
    import socket

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import _cassette_clock
    _cassette_clock.shift(off=float(os.environ["TJ_TEST_CLOCK_OFF"]))

    def deny(*a, **k):
        raise OSError("시험 자식: 바깥 연결 차단")
    socket.socket.connect = deny
    socket.getaddrinfo = deny
    sys.path.insert(0, src)
    import config
    import core
    for mn, m in list(sys.modules.items()):
        if mn.startswith("core_") and m is not None and hasattr(m, "dm"):
            m.dm = lambda *a, **k: None
    c = core.Core(config.load_config())
    print("ready", flush=True)
    if sys.stdin.readline().strip() != "go":
        return 2
    c.conn.execute("BEGIN")
    c._consume_record(json.loads(rec_json))
    c.conn.commit()
    c.conn.close()
    print("done", flush=True)
    return 0


if len(sys.argv) > 3 and sys.argv[1] == "--core-child":
    sys.exit(_core_child(sys.argv[2], sys.argv[3]))

import _cassette_clock  # noqa: E402

CLOCK_OFF = _cassette_clock.shift("12:00:00")
import _harness as T  # noqa: E402
import os  # noqa: E402

FORK = sys.platform.startswith("linux") and os.environ.get("TJ_TEST_FORK") == "1"
os.environ["TJ_BUILD_PROC"] = "fork" if FORK else "off"
import _ingest  # noqa: E402,F401
from _ingest import W, SOLW, Reader  # noqa: E402

import ast  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

json.dump({"chains": {"eth": {"blockscout": "https://bs.invalid", "etherscan_chainid": 1, "conf_depth": 12, "blocks_per_day": 7200,
                              "rpcs": ["https://rpc.invalid"]}},
           "wallets": [{"type": "evm", "chain": "eth", "address": W, "label": "w"}, {"type": "sol", "chain": "sol", "address": SOLW, "label": "s"}],
           "native_symbol": {"eth": "ETH"}, "backfill_months": 5, "sol": {"rpcs": ["https://solrpc.invalid"]}},
          open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
import buildproc  # noqa: E402
import config, paths, statefile  # noqa: E402
import core  # noqa: E402
import db as dbm  # noqa: E402
import discopen  # noqa: E402
import histcurve  # noqa: E402
import netpace  # noqa: E402
import web  # noqa: E402

chk = T.chk
T.patch_moved("dm", lambda *a, **k: None)
for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker"):
    if hasattr(web.StateBuilder, _m):
        setattr(web.StateBuilder, _m, lambda self: None)
netpace.wait = lambda url, now=None, sleep=None: None
DAY = 86400
NOW = int(time.time())
KST = timezone(timedelta(hours=9))
X = "0x" + "b7" * 20
T0 = NOW - 25 * DAY
PX = {"ETH": 2000.0, "SOL": 100.0}
HAS_STATE = hasattr(dbm, "daily_inval_state") and hasattr(dbm, "bump_daily_inval")


def fake_lookup(spec, iso, now=None, w=0.0, ask=True, old=False):
    for s9, p9 in PX.items():
        if s9 in str(spec).upper():
            return p9, "ok"
    return None, "pending"


fake_lookup._tj_test_mock = True
histcurve.DAYCLOSE.lookup = fake_lookup
json.dump({"usd": dict(PX), "usd_ts": {k: NOW for k in PX}, "rate": 1400.0, "updated": NOW, "dex_usd": {}, "dex_ts": {}, "dex_res": {}, "dex_res_ts": {},
           "fx_basis": 1400.0, "ex_usd": {}, "ex_ts": {}}, open(paths.state("spot.json"), "w"))
web.pricing.PxCache.candle_usd = lambda self, sym, ms: PX.get(str(sym).upper())
web.pricing._gj = lambda url, timeout=10.0: None
web.pricing.PxCache.fx_at = lambda self, ms: 1400.0
open(os.path.join(paths.STATE_DIR, "backfill_done"), "w").write("1")
DPATH = paths.state("daily_cache.json")


def sol_tx(sig: str, ts: int, deltas, **extra) -> dict:
    rec = {"v": 1, "kind": "sol_tx", "chain": "sol", "txhash": sig, "slot": 800, "ts": ts, "fee_lamports": 0, "fee_payer_mine": False,
           "fee_payer": None, "wallets": [SOLW], "counterparties": [], "has_program": False, "err": False,
           "deltas": [{"asset": "native", "symbol": "SOL", "decimals": 9, "delta": str(int(q * 10 ** 9)), "owner": o} for o, q in deltas]}
    rec.update(extra)
    return rec


def reward(tag: str, ts: int, sol: int) -> dict:
    return sol_tx(f"stakerwd:STK{tag}:{tag}", ts, [(f"{SOLW}:stake:STK{tag}", sol)], has_program=True,
                  stake_reward={"kind": "epoch", "epoch": 500})


c = core.Core(config.load_config())
c._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": "0x" + "%064x" % 1, "wallets": [W], "ts": 1, "snapshot": {
    "tx": {"hash": "0x" + "%064x" % 1, "from": X, "to": W, "value": str(10 ** 18), "fee": {"value": "0"}, "status": "ok", "raw_input": "0x",
           "timestamp": T0, "block_number": 1500, "block_hash": "0x" + "d" * 64}, "token_transfers": [], "internal": []}}]), 0, 0)
BASE_SOL = sol_tx("solbase1", T0, [(SOLW, 10)])
c._drain_stream("sol", Reader([BASE_SOL]), 0, 0)


def today_iso() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def ledger_state():
    if not HAS_STATE:
        return None
    r = dbm.open_db(paths.DB_PATH, readonly=True)
    try:
        return dbm.daily_inval_state(r)
    finally:
        r.close()


def stamp_now():
    st = ledger_state()
    if st is None:
        return None
    return f"{st[0]}:{'' if st[1] is None else st[1]}" if (st[0] or st[1] is not None) else None


def fresh_builder():
    try:
        os.remove(DPATH)
    except FileNotFoundError:
        pass
    b = web.StateBuilder()
    b.skip_gen_check = True
    return b


def build_pinned(b):
    conn = dbm.open_db(paths.DB_PATH, readonly=True)
    try:
        conn.execute("BEGIN")
        return b._build(conn)["fields"]
    finally:
        conn.close()


def build_real(b):
    b.cache = None
    return b.build()


def frozen(b) -> dict:
    td = today_iso()
    return {k: float(v["val"]) for k, v in b.daily.items()
            if len(str(k)) == 10 and str(k)[4] == "-" and str(k) < td and isinstance(v, dict) and isinstance(v.get("val"), (int, float))}


def oracle() -> dict:
    o = web.StateBuilder()
    o.skip_gen_check = True
    o.daily = {"_v": web.DAILY_V}
    build_pinned(o)
    return frozen(o)


def consume(rec):
    c.conn.execute("BEGIN")
    c._consume_record(rec)
    c.conn.commit()


def child_change(rec) -> tuple:
    p = subprocess.Popen([sys.executable, "-I", os.path.abspath(__file__), "--core-child", T.SRC, json.dumps(rec)],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         env=dict(os.environ, TJ_TEST_CLOCK_OFF=repr(CLOCK_OFF)))

    def until(word):
        for _ in range(500):
            ln = p.stdout.readline()
            if not ln or ln.strip() == word:
                return ln.strip()
        return ""
    try:
        ready = until("ready")
        p.stdin.write("go\n")
        p.stdin.flush()
        done = until("done")
        p.wait(timeout=120)
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
    return ready, done, p.returncode, (p.stderr.read() or "")[-600:]


def check_after(name, b, before, build=build_pinned):
    build(b)
    got = frozen(b)
    want = oracle()
    moved = sorted(d for d in want if d in before and abs(want[d] - before[d]) > 1)
    bad = {d: (round(got[d], 2) if d in got else None, round(want[d], 2)) for d in moved if d not in got or abs(got[d] - want[d]) > 0.01}
    stamp_b = b.daily.get("_inval")
    chk(len(moved) >= 3, f"{name} 전제: 그 core 변경이 지난날 값을 실제로 바꾼다(다시 센 값 ≠ 처음 동결 값)", (len(moved), moved[:3]))
    chk(moved and not bad, f"{name} 경합 뒤 다음 빌드의 지난날 = 새 원장으로 다시 센 값(옛 값이 최신처럼 굳지 않음)", bad)
    if HAS_STATE:
        chk(stamp_b is not None and stamp_b == stamp_now(), f"{name} 다시 센 빌드의 캐시 도장 = 지금 원장 표식", (stamp_b, stamp_now()))


def scenario(name, rec, race):
    b = fresh_builder()
    build_pinned(b)
    before = frozen(b)
    race(b, rec)
    check_after(name, b, before)
    return b


B0 = fresh_builder()
build_pinned(B0)
dc0 = json.load(open(DPATH))
chk(len(frozen(B0)) >= 20, "S0 순번 칸 없는 원장 빌드 = 지난날 동결", len(frozen(B0)))
if HAS_STATE:
    st0 = ledger_state()
    chk(len(st0[0]) == 32 and st0[1] is None and dc0.get("_inval") == f"{st0[0]}:",
        "S0 새 core 가 처음 연 원장 = 신원 생김(uuid4) · 순번 칸 없음 · 캐시 도장 '신원:'", (st0, dc0.get("_inval")))
    d0 = sorted(frozen(B0))[-4]
    true0 = frozen(B0)[d0]
    B0.daily.pop("_inval", None)
    B0.daily[d0]["val"] = round(true0 + 333.0, 2)
    statefile.atomic_write_json(DPATH, B0.daily)
    build_pinned(B0)
    chk(abs(frozen(B0)[d0] - (true0 + 333.0)) < 0.01 and B0.daily.get("_inval") == f"{st0[0]}:" and json.load(open(DPATH)).get("_inval") == f"{st0[0]}:",
        "S0 도장 없는 옛 캐시 + 순번 칸 없는 원장(업데이트 직후) = 다시 계산 없음 · 그대로 받아 도장만 — 그 빌드에 파일에도 저장(재시작 뒤 신원 비교 유지)",
        (d0, frozen(B0).get(d0), true0, json.load(open(DPATH)).get("_inval")))
else:
    chk(False, "S0 db.daily_inval_state 없음(고치기 전 판)")


def race_a(b, rec):
    real = statefile.atomic_write_json
    fired = []

    def hooked(path, obj, *a, **k):
        if not fired and os.path.abspath(str(path)) == os.path.abspath(DPATH):
            fired.append(1)
            consume(rec)
        return real(path, obj, *a, **k)
    b._daily_dirty = True
    statefile.atomic_write_json = hooked
    try:
        build_pinned(b)
    finally:
        statefile.atomic_write_json = real
    chk(fired, "R-A 끼어들기: 빌드의 일별 캐시 저장 직전에 core 변경·신호")


scenario("R-A", reward("A", NOW - 6 * DAY, 5), race_a)


def race_b(b, rec, change=None):
    orig = b._daily_series
    fired = []
    st0 = stamp_now()

    def hooked(*a, **k):
        if not fired:
            fired.append((change or consume)(rec))
        return orig(*a, **k)
    b._daily_series = hooked
    try:
        build_pinned(b)
    finally:
        del b._daily_series
    chk(fired, "R-B 끼어들기: 스냅숏 고정 뒤 · 일별 검사 전에 core 변경·신호")
    if HAS_STATE:
        chk(stamp_now() != st0 and b.daily.get("_inval") == st0,
            "R-B 캐시 도장 = 빌드 스냅숏 안의 표식(빌드 도중 커밋된 새 값을 '소비했다'고 적지 않음)", (st0, b.daily.get("_inval"), stamp_now()))
    return fired


scenario("R-B", reward("B", NOW - 9 * DAY, 4), race_b)


def race_c(b, rec):
    c.conn.execute("BEGIN")
    c._consume_record(rec)
    build_pinned(b)
    c.conn.commit()


scenario("R-C", reward("C", NOW - 12 * DAY, 3), race_c)


def race_d(b, rec):
    got = race_b(b, rec, change=child_change)
    r = got[0] if got else ("", "", None, "")
    chk(r[0] == "ready" and r[1] == "done" and r[2] == 0, "R-D 자식 core 프로세스: 시작 → 'go' → 한 건 소비·커밋", r)


scenario("R-D", reward("D", NOW - 15 * DAY, 2), race_d)

BE = fresh_builder()
build_real(BE)
before_e = frozen(BE)
st_e = stamp_now()
nf0 = int(buildproc._ST.get("n_fork") or 0)
orig_e = BE._daily_series


def hooked_e(*a, **k):
    if not getattr(hooked_e, "fired", False):
        hooked_e.fired = True
        child_change(reward("E", NOW - 18 * DAY, 6))
    return orig_e(*a, **k)


BE._daily_series = hooked_e
try:
    build_real(BE)
finally:
    del BE._daily_series
if HAS_STATE:
    chk(stamp_now() != st_e, "R-E 빌드 도중 core 변경(별도 프로세스) 커밋됨", (st_e, stamp_now()))
    chk(BE.daily.get("_inval") == st_e, "R-E build() 의 캐시 도장 = 빌드 스냅숏의 표식" + (" — 포크 자식이 찍어 부모로('daily' INPLACE)" if FORK else ""),
        (st_e, BE.daily.get("_inval"), stamp_now()))
if FORK:
    chk(int(buildproc._ST.get("n_fork") or 0) > nf0, "R-E 실제로 포크 자식이 빌드(TJ_TEST_FORK=1)", (buildproc._ST.get("last"), buildproc._ST.get("why_in")))
check_after("R-E", BE, before_e, build=build_real)

if HAS_STATE:
    s0 = ledger_state()
    c.conn.execute("BEGIN")
    c._consume_record(reward("T", NOW - 7 * DAY, 1))
    c.conn.rollback()
    chk(ledger_state() == s0 and not c.conn.in_transaction, "T1 롤백한 소비 = 순번 그대로(변경과 함께 사라짐)", (s0, ledger_state()))

    def committed(name, fn):
        a9 = ledger_state()
        fn()
        b9 = ledger_state()
        ok9 = a9 is not None and b9 is not None and b9[1] is not None and (a9[1] is None or int(b9[1]) > int(a9[1]))
        chk(ok9 and not c.conn.in_transaction, f"T1 {name} = 순번 올라감 · 커밋 뒤 열린 트랜잭션 없음(방어 롤백에 안 지워짐)", (a9, b9, c.conn.in_transaction))
    committed("스테이킹 보상(apply_sol · core_post)", lambda: consume(reward("U", NOW - 8 * DAY, 1)))
    committed("스테이크 기초잔고(_post_stake_open · core_post)", lambda: consume(sol_tx(
        "stakeopen:STKO", NOW - 20 * DAY, [(f"{SOLW}:stake:STKO", 3)],
        stake_open={"acct": "STKO", "lamports": 3 * 10 ** 9, "wallet": SOLW})))
    committed("솔라나 새 관점 재기장(_maybe_rederive_sol · core_snap)", lambda: consume(dict(
        sol_tx("solbase1", T0, [(SOLW, 10), (f"{SOLW}:stake:STKR", 1)]), repersp=True)))
    aid_eth = c.asset_id("native", "eth", None, symbol="ETH", decimals=18)
    c.conn.commit()

    def anchor():
        sid = discopen.write_anchor(c, "eth", W, aid_eth, None, 10 ** 17, 1400, T0 - 5 * DAY, T0 - 5 * DAY, 10 ** 17, "token_recheck",
                                    {"_sources": ["synthetic"]})
        chk(bool(sid), "T1 발견 시점 앵커 한 칸 기장", sid)
        c.conn.commit()
        discopen.after_write(T0 - 5 * DAY)
    committed("발견 시점 기초 잔고(discopen.write_anchor)", anchor)

    def touch():
        c.conn.execute("BEGIN")
        c.svc_exf._exf_hist_touch(NOW - 3 * DAY)
        chk(c.conn.in_transaction and stamp_now() == st_t, "T1 거래소 touch = 그 트랜잭션 안에서 올림(커밋 전엔 다른 연결에 안 보임)", (stamp_now(), st_t))
        c.conn.commit()
        c.svc_exf._exf_hist_dirty, c.svc_exf._exf_hist_from = False, None
    st_t = stamp_now()
    committed("거래소 지난 시점 touch(_exf_hist_touch · core_exf_late)", touch)
    committed("표식만 올림(_inval_seq) — 트랜잭션 밖이면 곧바로 커밋", c._inval_seq)
else:
    chk(False, "T1 db.daily_inval_state 없음(고치기 전 판)")

if HAS_STATE:
    p1 = os.path.join(T.TMP, "seq_unit.db")
    a1 = dbm.open_db(p1)
    r1 = dbm.open_db(p1, readonly=True)

    def seq(cn=None):
        st = dbm.daily_inval_state(cn or r1)
        return None if st[1] is None else int(st[1])
    a1.execute("BEGIN")
    dbm.bump_daily_inval(a1, now=1000.0)
    chk(seq() is None and seq(a1) == 1000000, "S1 커밋 전 = 쓴 연결만 보임 · 다른 연결(웹 스냅숏)엔 안 보임", (seq(), seq(a1)))
    a1.rollback()
    chk(seq(a1) is None, "S1 롤백 = 안 올라감(변경과 함께 사라짐)", seq(a1))
    vals = []
    for now9 in (1000.0, 999.0, 999.0, 2000.0):
        a1.execute("BEGIN")
        dbm.bump_daily_inval(a1, now=now9)
        a1.commit()
        vals.append(seq())
    chk(vals == [1000000, 1000001, 1000002, 2000000], "S1 순번 = max(지금 + 1, 지금 ms) — 단조 증가(시계 역행에도)", vals)
    a1.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    bk1 = p1 + ".bak"
    shutil.copyfile(p1, bk1)
    for now9 in (2000.0, 2000.0):
        a1.execute("BEGIN")
        dbm.bump_daily_inval(a1, now=now9)
        a1.commit()
    s_new = seq()
    r1.close()
    a1.close()
    for sfx in ("-wal", "-shm"):
        if os.path.exists(p1 + sfx):
            os.remove(p1 + sfx)
    shutil.copyfile(bk1, p1)
    a1 = dbm.open_db(p1)
    r1 = dbm.open_db(p1, readonly=True)
    a1.execute("BEGIN")
    dbm.bump_daily_inval(a1, now=2001.0)
    a1.commit()
    chk(s_new == 2000002 and seq() == 2001000, "S1 원장을 옛 백업으로 되돌린 뒤 올린 순번 ≠ 되돌리기 전 순번(시각 바닥 — 옛 캐시 도장과 우연히 같아지지 않음)",
        (s_new, seq()))
    a1.execute("UPDATE meta SET v='x1' WHERE k=?", (dbm.DAILY_INVAL_K,))
    a1.commit()
    a1.execute("BEGIN")
    dbm.bump_daily_inval(a1, now=3000.0)
    a1.commit()
    chk(seq() == 3000000, "S1 손상 값(숫자 아님) = 0 으로 보고 지금 ms", seq())
    e0 = dbm.daily_inval_state(r1)[0]
    a1.execute("BEGIN")
    e1 = dbm.renew_ledger_epoch(a1)
    a1.commit()
    chk(len(e0) == 32 and e1 != e0 and len(e1) == 32 and dbm.daily_inval_state(r1) == (e1, "3000000"),
        "S1 신원 = 처음 쓰기 연결 때 생김 · renew = 새 무작위 값 · 표식 = (신원, 순번) 원문", (e0, e1, dbm.daily_inval_state(r1)))
    chk(dbm.DAILY_INVAL_K.startswith("cache_inval:") and dbm.DAILY_INVAL_K not in ("schema_version", "data_rev"),
        "S1 meta 키 = 'cache_inval:' 이름공간(마이그레이션 번호 행과 안 겹침)", dbm.DAILY_INVAL_K)
    r1.close()
    a1.close()
else:
    chk(False, "S1 db.bump_daily_inval·daily_inval_state 없음(고치기 전 판)")

B2 = fresh_builder()
build_pinned(B2)
d2 = sorted(frozen(B2))[-5]
true2 = frozen(B2)[d2]


def tamper():
    B2.daily[d2]["val"] = round(true2 + 777.0, 2)
    statefile.atomic_write_json(DPATH, B2.daily)


tamper()
build_pinned(B2)
chk(abs(frozen(B2)[d2] - (true2 + 777.0)) < 0.01, "S2 원장·표식이 그대로면 동결 유지(헛 무효화 없음)", (d2, frozen(B2).get(d2), true2))
os.remove(DPATH)
build_pinned(B2)
chk(abs(frozen(B2)[d2] - true2) < 0.01, "S2 옛 신호(파일 삭제만)도 동결 버림 — 다시 센 값", (d2, frozen(B2).get(d2), true2))
if HAS_STATE:
    tamper()
    c.conn.execute("BEGIN")
    dbm.renew_ledger_epoch(c.conn)
    dbm.bump_daily_inval(c.conn)
    c.conn.commit()
    build_pinned(B2)
    chk(abs(frozen(B2)[d2] - true2) < 0.01 and B2.daily.get("_inval") == stamp_now(), "S2 원장 교체 표식(새 신원 + 순번)이면 동결 버림 · 새 도장",
        (d2, frozen(B2).get(d2), true2, B2.daily.get("_inval"), stamp_now()))
else:
    chk(False, "S2 원장 교체 표식 — db 도우미 없음(고치기 전 판)")

if HAS_STATE:
    import ledger_backup  # noqa: E402
    import sqlite3  # noqa: E402
    aid_sol = c.asset_id("native", "sol", None, symbol="SOL", decimals=9)
    c.conn.commit()
    bk3 = os.path.join(paths.STATE_DIR, "s3_backup.db")
    s_src, s_dst = sqlite3.connect(paths.DB_PATH), sqlite3.connect(bk3)
    s_src.backup(s_dst)
    s_dst.execute("PRAGMA journal_mode=DELETE").fetchone()
    s_dst.close()
    s_src.close()
    st_bk = ledger_state()
    c._post_leg_strict("opening", "sol", "s3:after-backup", 0, NOW - 4 * DAY, aid_sol, f"wallet:sol:{SOLW}", 2 * 10 ** 9, None, None, "opening", "OPENING")
    c.conn.commit()
    chk(ledger_state() == st_bk, "S3 전제: 백업 뒤 평범한 기장은 표식을 안 바꾼다 — 복원하면 (옛 신원·순번) 짝이 도장과 같아진다", (st_bk, ledger_state()))
    B3 = fresh_builder()
    build_pinned(B3)
    before3 = frozen(B3)
    y3 = (datetime.now(KST) - timedelta(days=1)).strftime("%Y-%m-%d")
    e3 = dict(B3.daily.get(y3) or {})
    end3 = datetime.strptime(y3, "%Y-%m-%d").replace(tzinfo=KST, hour=23, minute=59, second=59).timestamp()
    snap3 = {"date": y3, "ts": end3 - 60, "val": e3.get("val"), "usdt": 1450.0, "kimp": None, "g": dict(e3.get("g") or {}),
             "x": float(e3.get("x") or 0), "defer": False, "p": dict(((B3.daily_px or {}).get(y3) or {}).get("p") or {}), "dq": e3.get("dq", "")}
    B3.daily["_live_ok"], B3.daily["_live"] = dict(snap3), dict(snap3)
    B3.daily.pop(y3, None)
    statefile.atomic_write_json(DPATH, B3.daily)
    tmp3 = paths.DB_PATH + ".s3restore.tmp"
    shutil.copyfile(bk3, tmp3)
    t3 = sqlite3.connect(tmp3)
    dbm.renew_ledger_epoch(t3)
    t3.commit()
    t3.close()
    c.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.conn.close()
    ledger_backup.swap_in(paths.DB_PATH, tmp3, paths.DB_PATH + ".pre_s3")
    chk(os.path.exists(DPATH) and ledger_state()[1] == st_bk[1] and ledger_state()[0] != st_bk[0],
        "S3 교체 뒤 = 순번은 도장과 같은 옛 값 · 신원만 새것 · 캐시 파일 남음", (st_bk, ledger_state()))
    check_after("S3", B3, before3)
    ey3 = B3.daily.get(y3) or {}
    chk(ey3.get("why") == "led" and ey3.get("usdt") == 1450.0 and (B3.daily.get("_live_ok") or {}).get("led_other") == 1,
        "S3 신원이 바뀐 복원 = 어제 마감 스냅숏 수량은 안 쓰고 복원 원장으로 다시 셈(사유 'led') · 그 순간 환율(1,450 — 지금 조회 1,400 아님)은 그대로",
        ({k: ey3.get(k) for k in ("why", "usdt", "src")}, (B3.daily.get("_live_ok") or {}).get("led_other")))
else:
    chk(False, "S3 백업 복원 — db 도우미 없음(고치기 전 판)")

import view_regroup  # noqa: E402
if hasattr(view_regroup, "daily_inval_apply"):
    MK2 = ("_v", "_risk_rev", "_live", "_live_ok", "_reset_at", "_inval")
    td2 = datetime.now(KST)

    def rule(old, inval, gone=False):
        d9 = {"_v": web.DAILY_V, "2000-01-01": {"val": 1.0}, "_live": {"date": "x"}, "_live_ok": {"date": "x"}}
        if old is not None:
            d9["_inval"] = old
        out9, st9 = view_regroup.daily_inval_apply(d9, inval, td2, gone, MK2)
        unmarked9 = all(isinstance(out9.get(k9), dict) and not out9[k9].get("led_other") for k9 in ("_live", "_live_ok"))
        return "2000-01-01" in out9, unmarked9, out9.get("_inval"), st9
    table = [
        ((None, None, False), (True, True, None, False), "모름 + 파일 있음 = 그대로"),
        ((None, None, True), (False, True, None, False), "모름 + 옛 신호(파일 없음) = 동결 버림 · 스냅숏 이어받음"),
        ((None, ("E", None)), (True, True, "E:", True), "도장 없는 옛 캐시 + 순번 칸 없음 = 그대로 받아 도장만 · 그 도장은 저장"),
        ((None, ("E", "5")), (False, True, "E:5", True), "도장 없는 캐시 + 순번 있음 = 다시 셈"),
        (("E:5", ("E", "5")), (True, True, "E:5", False), "같은 도장 = 그대로"),
        (("E:5", ("E", "5"), True), (False, True, "E:5", False), "같은 도장 + 옛 신호 = 동결 버림(저장 강제 없음)"),
        (("E:5", ("E", "6")), (False, True, "E:6", True), "순번 바뀜 = 다시 셈 · 같은 원장이라 스냅숏 이어받음"),
        (("E:5", ("F", "5")), (False, False, "F:5", True), "신원 바뀜(복원·교체) = 다시 셈 + 마감 스냅숏에 다른 원장 표지"),
        (("E:", ("F", None)), (False, False, "F:", True), "순번 없는 채 신원 바뀜 = 다시 셈 + 스냅숏 표지"),
        (("E:5", ("E", None)), (False, True, "E:", True), "순번 칸이 사라짐(순번 전 백업) = 다시 셈"),
        ((None, ("", None)), (True, True, None, False), "신원·순번 둘 다 없음(쓰기 연결 전 원장 — 골든 기준) = 도장 없음·그대로"),
    ]
    bad2 = [(why, rule(*args), want) for args, want, why in table if rule(*args) != want]
    chk(not bad2, f"T2 판정 규칙 표 {len(table)}칸 = (동결 유지?, 마감 스냅숏 표지 없음?, 새 도장, 저장?)", bad2)
else:
    chk(False, "T2 view_regroup.daily_inval_apply 없음(고치기 전 판)")

BUMPS = ("_inval_daily", "_inval_seq", "bump_daily_inval", "_exf_hist_touch")
HELPERS = ("_inval_daily", "_inval_seq", "_exf_hist_touch", "bump_daily_inval")


def call_name(n):
    f = n.func
    return f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)


bad_sites, n_sites = [], 0
for fn9 in sorted(f for f in os.listdir(T.SRC) if f.endswith(".py") and (f.startswith("core") or f == "discopen.py")):
    tree = ast.parse(open(os.path.join(T.SRC, fn9), encoding="utf-8").read())
    for fd in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        if fd.name in HELPERS:
            continue
        calls = [n for n in ast.walk(fd) if isinstance(n, ast.Call)]
        bumps = [n.lineno for n in calls if call_name(n) in BUMPS]
        commits = [n.lineno for n in calls if call_name(n) == "commit"]
        for ln in bumps:
            n_sites += 1
            if commits and not any(cl > ln for cl in commits):
                bad_sites.append(f"{fn9}:{fd.name}:{ln}")
chk(n_sites >= 15 and not bad_sites, f"P1 표식 올림 {n_sites}자리 = 같은 함수의 커밋 앞(커밋 뒤에만 남은 자리 0 · 커밋 없는 함수 = 부르는 쪽 트랜잭션)", bad_sites)
vb = ast.parse(open(os.path.join(T.SRC, "view_builder.py"), encoding="utf-8").read())
bfn = next(n for n in ast.walk(vb) if isinstance(n, ast.FunctionDef) and n.name == "_build")
order = [call_name(n) for n in sorted((n for n in ast.walk(bfn) if isinstance(n, ast.Call)), key=lambda n: (n.lineno, n.col_offset))]
chk("daily_inval_state" in order and "_build_replay" in order and order.index("daily_inval_state") < order.index("_build_replay"),
    "P1 빌드 첫머리 = 원장 행(리플레이)보다 먼저 같은 연결에서 표식 읽기", order[:4])
bsrc = open(os.path.join(T.SRC, "buildproc.py"), encoding="utf-8").read()
bt = ast.parse(bsrc)
ro = next(n for n in ast.walk(bt) if isinstance(n, ast.FunctionDef) and n.name == "_run_once")
cr = next(n for n in ast.walk(bt) if isinstance(n, ast.FunctionDef) and n.name == "_child_run")
seq_ro = sorted((n for n in ast.walk(ro) if isinstance(n, ast.Call)), key=lambda n: (n.lineno, n.col_offset))
lit = [(call_name(n), n.args[0].value if n.args and isinstance(n.args[0], ast.Constant) else None, n.lineno) for n in seq_ro]
l_begin = min((ln for nm, a, ln in lit if nm == "execute" and a == "BEGIN"), default=None)
l_sel = min((ln for nm, a, ln in lit if nm == "execute" and isinstance(a, str) and a.lstrip().upper().startswith("SELECT")), default=None)
l_fork = min((ln for nm, a, ln in lit if nm == "fork"), default=None)
l_child = min((ln for nm, a, ln in lit if nm == "_child_run"), default=None)
cr_build = [n for n in ast.walk(cr) if isinstance(n, ast.Call) and call_name(n) == "_build" and n.args and isinstance(n.args[0], ast.Name)
            and n.args[0].id == "conn"]
chk(None not in (l_begin, l_sel, l_fork, l_child) and l_begin < l_sel < l_fork < l_child and cr_build and cr.args.args[1].arg == "conn",
    "P1 포크 경로: 부모가 BEGIN + 첫 SELECT 로 스냅숏 고정 → fork → 자식 _build(그 conn) = 표식도 그 스냅숏", (l_begin, l_sel, l_fork, l_child))
chk("daily" in buildproc.INPLACE and "daily" not in buildproc.PARENT_ONLY and "daily" not in buildproc.CHILD_ONLY,
    "P1 포크 자식이 고친 'daily'(도장 포함)는 늘 부모로 보냄(INPLACE)")
real_w, real_nc = statefile.atomic_write_json, histcurve.DAYCLOSE.note_change
try:
    hs = buildproc._hist_begin()
    statefile.atomic_write_json(DPATH, {"_v": web.DAILY_V, "_inval": "g:1"})
    dc_path = os.path.abspath(str(histcurve.DAYCLOSE.path))
    had = os.path.exists(dc_path)
    statefile.atomic_write_json(dc_path, {"probe": 1})
    blocked = (not had and not os.path.exists(dc_path)) or (had and statefile.read_json(dc_path, {}).get("probe") != 1)
finally:
    statefile.atomic_write_json, histcurve.DAYCLOSE.note_change = real_w, real_nc
chk(hs is not None and json.load(open(DPATH)).get("_inval") == "g:1" and blocked,
    "P1 포크 자식의 저장 막기는 그날 마감가 파일만 — 일별 캐시(도장)는 자식이 그대로 쓴다", (hs is not None, blocked))
pb = web.StateBuilder()
d_child = {"_v": web.DAILY_V, "_inval": "g:7", "2000-01-01": {"val": 1.0}}
buildproc.apply(pb, {"st": {"daily": d_child}}, {})
chk(pb.daily is d_child and pb.daily.get("_inval") == "g:7", "P1 buildproc.apply = 자식 'daily' 를 도장째 부모 빌더로", pb.daily.get("_inval"))
ce = ast.parse(open(os.path.join(T.SRC, "core_ext.py"), encoding="utf-8").read())
rb_fn = next(n for n in ast.walk(ce) if isinstance(n, ast.FunctionDef) and n.name == "_ext_rebuild")
c2_calls = []
for n in ast.walk(rb_fn):
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
        nm = call_name(n)
        if nm in ("renew_ledger_epoch", "bump_daily_inval") or (nm == "commit" and isinstance(n.func.value, ast.Name) and n.func.value.id == "c2"):
            c2_calls.append((n.lineno, nm))
ln_of = {nm: [ln for ln, x in sorted(c2_calls) if x == nm] for nm in ("renew_ledger_epoch", "bump_daily_inval", "commit")}
chk(all(ln_of.values()) and max(ln_of["renew_ledger_epoch"] + ln_of["bump_daily_inval"]) < max(ln_of["commit"]),
    "P1 재구축 교체 = 교체 전 새 원장(c2)에 새 신원 + 순번 → 그 커밋(교체와 같은 순간 · 크래시 창 없음)", sorted(c2_calls))
c.conn.close()
T.finish()
