#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _bscchain as B  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import sqlite3  # noqa: E402
import time  # noqa: E402

sys.path.insert(0, os.path.join(T.ROOT, "tools"))
import db as dbm  # noqa: E402
import ledger_restore as LR  # noqa: E402

bw = B.bsc_watch
CH = B.CH
import paths, statefile  # noqa: E402
E18 = 10 ** 18
E17 = 10 ** 17
clk = [time.time()]
bw._now = lambda: clk[0]
T.patch_moved("_now", bw._now, ("bsc_",))
REQ = os.path.join(paths.STATE_DIR, getattr(bw, "DISC_REQ_NAME", "disc_open_request.json"))
BALW = os.path.join(paths.STATE_DIR, "bsc_balw.json")
RX = os.path.join(paths.STATE_DIR, getattr(bw, "BALW_RX_NAME", "bsc_balw_recheck.json"))
BK = os.path.join(paths.STATE_DIR, "backups", "ledger_20990101.db")


def tick(sec, blocks):
    clk[0] += sec
    CH.head += blocks


def gates_reset():
    for g9 in list(getattr(B.bf_engine, "_GATES", {}).values()):
        g9.open_until = g9.pause_until = 0


def setup_db():
    con = dbm.open_db(paths.DB_PATH)
    con.execute("CREATE TABLE IF NOT EXISTS decisions (id INTEGER PRIMARY KEY, created_at INTEGER)")
    con.commit()
    con.close()


def fresh(arch=True, wallets=None):
    ws = wallets or [B.W1, B.W2]
    CH.tx.clear()
    CH.mode, CH.old_below, CH.arch_fail, CH.hang = None, None, None, None
    CH.head = B.H0 + 300_000
    CH.bal0 = {w9: 10 * E18 for w9 in ws}
    CH.prune = 128
    CH.native(CH.head - 5_000, B.W1, B.OTHER, 10 ** 15)
    B.reset_state()
    gates_reset()
    setup_db()
    statefile.atomic_write_json(B.CPATH, {"from_block": CH.head - 30, "head": CH.head - 10, "_cov": B.WIN_BLK, "_bf_start": B.WIN_BLK,
                                       "_wallets": sorted(ws)})
    wr = B.Wr()
    w = mk(wr, arch=arch, wallets=ws)
    CH.arch_calls.clear()
    return w, wr


def mk(wr, arch=True, wallets=None):
    return bw.BscWatcher(B.cfg(archive_rpcs=[B.ARCH]) if arch else B.cfg(), list(wallets or [B.W1, B.W2]), wr)


def ingest(wr):
    con = sqlite3.connect(paths.DB_PATH)
    for r in wr.recs:
        sn = r.get("snapshot") or {}
        b9 = (sn.get("tx") or {}).get("block_number")
        con.execute("INSERT OR REPLACE INTO raw_txs (chain, txhash, block, ts, snapshot, wallets, ingested_at) VALUES ('bsc', ?, ?, NULL, ?, '[]', ?)",
                    (r["txhash"].lower(), b9, json.dumps(sn), int(clk[0])))
    con.commit()
    con.close()


def run(w, wr, n, sec=90, blocks=200, each=None):
    for i in range(n):
        tick(sec, blocks)
        if each:
            each(i)
        B.cycle(w)
        ingest(wr)


def recs(wr, h):
    return [r for r in wr.recs if r["txhash"] == h]


def reqs():
    d = statefile.read_json(REQ, {}) if os.path.exists(REQ) else {}
    return list(d.get("items") or []) if isinstance(d, dict) else []


def balw_st():
    return statefile.read_json(BALW, {}) if os.path.exists(BALW) else {}


def wst(w9=None):
    return ((balw_st().get("w") or {}).get(w9 or B.W1)) or {}


def jobs_left():
    return sum(len((v or {}).get("jobs") or []) for v in (balw_st().get("w") or {}).values())


def ux_left():
    return sum(len((v or {}).get("ux") or []) for v in (balw_st().get("w") or {}).values())


def bd_attr(wr):
    return [(r["txhash"][-6:], i.get("value")) for r in wr.recs for i in (r["snapshot"].get("internal") or []) if i.get("attr") == "balance_delta"]


def in_ledger(h):
    con = sqlite3.connect(paths.DB_PATH)
    try:
        return con.execute("SELECT count(*) FROM raw_txs WHERE chain='bsc' AND txhash=?", (h.lower(),)).fetchone()[0]
    finally:
        con.close()


def backup(seg=5, off=100):
    os.makedirs(os.path.dirname(BK), exist_ok=True)
    for p9 in (BK, BK + "-wal", BK + "-shm"):
        if os.path.exists(p9):
            os.remove(p9)
    s = sqlite3.connect(paths.DB_PATH)
    d = sqlite3.connect(BK)
    s.backup(d)
    d.execute("PRAGMA journal_mode=DELETE").fetchone()
    d.execute("INSERT OR REPLACE INTO inbox_offsets (stream, seg, off) VALUES ('bsc', ?, ?)", (seg, off))
    d.commit()
    d.close()
    s.close()
    os.utime(BK, (clk[0], clk[0]))


def restore():
    p = LR.plan(BK, now=int(clk[0]), state_dir=paths.STATE_DIR)
    LR.apply(p, proc_check=False, state_dir=paths.STATE_DIR, log=lambda *a, **k: None)
    return p


def scenario(arch=True, val=2 * E17, kind="native", wallets=None, to=None):
    to = to or B.W1
    w, wr = fresh(arch=arch, wallets=wallets)
    run(w, wr, 3)
    backup()
    run(w, wr, 2)
    nb = CH.head + 5
    if kind == "native":
        h = CH.native(nb, B.OTHER, to, val)
    elif kind == "int_clue":
        h = CH.internal(nb, B.OTHER, B.ROUTER, to, val, mention=True)
    else:
        h = CH.internal(nb, B.OTHER, B.ROUTER, to, val)
    run(w, wr, 6)
    cp = wst(to).get("cp") or [0]
    return h, nb, wr, int(cp[0])


dep1, nb1, wr0, cp1 = scenario()
T.chk(len(recs(wr0, dep1)) == 1 and in_ledger(dep1) == 1 and cp1 > nb1 and not reqs(),
      "RS1 전제: 복구 전 잔고 감시가 수신을 찾아 방출·원장 반영 · 체크포인트가 수신 뒤", {"n": len(recs(wr0, dep1)), "cp": cp1, "nb": nb1, "req": reqs()})
clk[0] += 600
p1 = restore()
T.chk(p1["rewind"] == ["bsc"] and in_ledger(dep1) == 0 and dep1 not in (statefile.read_json(os.path.join(paths.STATE_DIR, "emitted_bsc.json"), []) or []),
      "RS1 전제: 복구 = BSC 되감기(인박스 부족) · 원장에서 수신 사라짐 · 방출 기록에서도 지움", {"rewind": p1["rewind"], "notes": p1["notes"]})
wr1 = B.Wr()
w1 = mk(wr1)
run(w1, wr1, 40)
T.chk(len(recs(wr1, dep1)) == 1 and recs(wr1, dep1)[0].get("via") == "balw"
      and (recs(wr1, dep1)[0]["snapshot"].get("tx") or {}).get("block_number") == nb1
      and (recs(wr1, dep1)[0]["snapshot"].get("tx") or {}).get("timestamp") == CH.ts(nb1) and in_ledger(dep1) == 1,
      "RS1 복구 뒤 40주기(60분) 안에 로그 없는 수신 0.2 = 원래 블록·시각의 실제 거래 정확히 1건 · 원장 반영(종전 = 누락)",
      {"n": len(recs(wr1, dep1)), "w": wst(), "jobs": jobs_left(), "req": reqs()})
T.chk(not reqs() and not bd_attr(wr1) and jobs_left() == 0 and ux_left() == 0 and not wst().get("rs") and not wst(B.W2).get("rs"),
      "RS1 요청·거짓 귀속 0 · 남은 작업·미해결 구간·복구 표식 0", {"req": reqs(), "bd": bd_attr(wr1), "w": wst()})
run(w1, wr1, 5)
T.chk(len(recs(wr1, dep1)) == 1, "RS1 뒤 주기 — 같은 수신 다시 방출 0")


statefile.atomic_write_json(RX, {"hours": 3})
run(w1, wr1, 8)
T.chk(len(recs(wr1, dep1)) == 1 and not reqs() and not os.path.exists(RX) and jobs_left() == 0,
      "RS7 회수 뒤 운영자 다시 점검(3시간) = 다시 방출·요청 0", {"n": len(recs(wr1, dep1)), "req": reqs(), "w": wst()})
clk[0] += 600
p7 = restore()
wr7 = B.Wr()
w7 = mk(wr7)
run(w7, wr7, 40)
T.chk(p7["rewind"] == ["bsc"] and len(recs(wr7, dep1)) == 1 and in_ledger(dep1) == 1 and not reqs() and not bd_attr(wr7),
      "RS7 같은 백업으로 두 번째 복구 = 다시 정확히 1건(원장 1줄) · 요청 0", {"n": len(recs(wr7, dep1)), "req": reqs(), "w": wst()})

dep1b, nb1b, _wr, _cp = scenario(to=B.W2)
clk[0] += 600
restore()
wr1b = B.Wr()
w1b = mk(wr1b)
run(w1b, wr1b, 40)
T.chk(len(recs(wr1b, dep1b)) == 1 and (recs(wr1b, dep1b)[0]["snapshot"].get("tx") or {}).get("block_number") == nb1b and in_ledger(dep1b) == 1
      and not reqs() and not bd_attr(wr1b),
      "RS1b 수신만 있는 지갑(발신 0)도 복구 뒤 원래 블록 실제 거래 1건 · 요청 0", {"n": len(recs(wr1b, dep1b)), "req": reqs(), "w": wst(B.W2)})

dep2, nb2, _wr, _cp = scenario(val=5 * 10 ** 13)
clk[0] += 600
restore()
wr2 = B.Wr()
w2 = mk(wr2)
run(w2, wr2, 40)
T.chk(len(recs(wr2, dep2)) == 1 and (recs(wr2, dep2)[0]["snapshot"].get("tx") or {}).get("block_number") == nb2 and in_ledger(dep2) == 1 and not reqs(),
      "RS2 문턱 아래 0.00005 BNB 도 원래 블록 실제 거래 1건 · 요청 0", {"n": len(recs(wr2, dep2)), "req": reqs(), "w": wst()})

dep3, nb3, wr3a, _cp = scenario(val=3 * E17, kind="int")
rq3 = [it for it in reqs() if it.get("wallet") == B.W1 and it.get("block") == nb3]
T.chk(len(rq3) == 1 and int(rq3[0]["diff_raw"]) == 3 * E17 and not recs(wr3a, dep3),
      "RS3a 전제: 복구 전 = 그 블록 기초 잔고 요청(0.3) · 방출 0", {"req": reqs()})
os.remove(REQ)
clk[0] += 600
restore()
wr3 = B.Wr()
w3 = mk(wr3)
run(w3, wr3, 40)
rq3 = [it for it in reqs() if it.get("wallet") == B.W1]
T.chk(len(rq3) == 1 and rq3[0].get("block") == nb3 and int(rq3[0]["diff_raw"]) == 3 * E17 and "bsc_balance_watch" in (rq3[0].get("sources") or [])
      and not recs(wr3, dep3) and not bd_attr(wr3),
      "RS3a 복구 뒤 같은 블록 기초 잔고 요청 정확히 1번(0.3 · 블록 시각 출처) · 거짓 방출·귀속 0", {"req": reqs(), "w": wst()})

dep3b, nb3b, wr3b0, _cp = scenario(val=25 * 10 ** 16, kind="int_clue")
T.chk(len(recs(wr3b0, dep3b)) >= 1 and in_ledger(dep3b) == 1, "RS3b 전제: 복구 전 = 로그 단서 tx 에 귀속 방출", {"n": len(recs(wr3b0, dep3b))})
clk[0] += 600
restore()
wr3b = B.Wr()
w3b = mk(wr3b)
run(w3b, wr3b, 40)
T.chk(len(recs(wr3b, dep3b)) == 1 and [v for _h, v in bd_attr(wr3b)] == [str(25 * 10 ** 16)] and in_ledger(dep3b) == 1 and not reqs(),
      "RS3b 복구 뒤 로그 단서 tx 에 internal 0.25 귀속 1건 · 요청 0", {"n": len(recs(wr3b, dep3b)), "bd": bd_attr(wr3b), "req": reqs()})

dep4, nb4, _wr, _cp = scenario()
clk[0] += 600
restore()
wr4 = B.Wr()
w4 = mk(wr4)
live4 = []


def inflow(_i):
    live4.append(CH.native(CH.head - 30, B.OTHER, B.W1, E17))
    live4.append(CH.native(CH.head - 31, B.OTHER, B.W2, E17))


run(w4, wr4, 30, each=inflow)
got4 = len(recs(wr4, dep4))
run(w4, wr4, 15)
dup4 = [h[-6:] for h in live4 + [dep4] if len(recs(wr4, h)) > 1]
emit4 = {w9: sum(int(r["snapshot"]["tx"]["value"]) for h in live4 for r in recs(wr4, h) if str(r["snapshot"]["tx"].get("to")).lower() == w9) for w9 in (B.W1, B.W2)}
req4 = {w9: sum(int(it["diff_raw"]) for it in reqs() if it.get("wallet") == w9) for w9 in (B.W1, B.W2)}
T.chk(got4 == 1 and len(recs(wr4, dep4)) == 1 and not dup4,
      "RS4 최신 유입이 계속돼도(30주기 · 지갑 2개 각 0.1) 복구 수신 1건 · 어떤 입금도 두 번 방출 0", {"got": got4, "dup": dup4, "w": wst()})
T.chk(all(emit4[w9] + req4[w9] == 30 * E17 for w9 in (B.W1, B.W2)) and jobs_left() == 0 and ux_left() == 0,
      "RS4 유입이 멈춘 뒤 최신 입금 금액 보존(실제 거래 + 기초 잔고 요청 = 들어온 3 BNB · 지갑마다) · 남은 작업 0", {"emit": emit4, "req": req4})

dep5, nb5, _wr, cp5 = scenario()
clk[0] += 600
p5 = restore()
fb5 = statefile.read_json(B.CPATH, {}).get("from_block")
CH.mode, CH.old_below = "429", int(fb5) + 50_000
wr5 = B.Wr()
w5 = mk(wr5)
run(w5, wr5, 6)
rs5 = wst().get("rs") or {}
T.chk(isinstance(statefile.read_json(B.CPATH, {}).get("_live"), dict) and rs5.get("z") == cp5 and not wst().get("ux") and not recs(wr5, dep5)
      and ((balw_st().get("last") or {}).get("rs") == 2),
      "RS5a 옛 차선 중 = 다시 점검 구간 보존(미해결 구간·작업으로 서둘러 안 넘김 · 하트비트 rs 2) · 방출 0", {"rs": rs5, "cp": cp5, "last": balw_st().get("last")})
w5 = mk(wr5)
run(w5, wr5, 2)
CH.mode, CH.old_below = None, None
for _i in range(8):
    run(w5, wr5, 1)
    if any((u or {}).get("why") == "원장 복구" for u in wst().get("ux") or []):
        break
T.chk(any((u or {}).get("why") == "원장 복구" for u in wst().get("ux") or []) and not wst().get("rs") and not recs(wr5, dep5),
      "RS5b 옛 차선 끝 = 다시 점검 구간이 미해결 구간으로(아직 방출 전)", {"w": wst()})
w5 = mk(wr5)
run(w5, wr5, 40)
T.chk(len(recs(wr5, dep5)) == 1 and in_ledger(dep5) == 1 and not reqs() and jobs_left() == 0 and ux_left() == 0,
      "RS5 두 번 재시작해도 정확히 1건 · 요청·남은 일 0", {"n": len(recs(wr5, dep5)), "req": reqs(), "w": wst()})

dep6, nb6, _wr, cp6 = scenario()
st6 = balw_st()
ws6 = st6["w"][B.W1]
ja6 = nb6 - 150_000
ws6["jobs"] = [{"k": "hist", "a": ja6, "z": nb6 - 140_000, "s": {str(ja6): "1", str(nb6 - 140_000): "2"}, "t0": int(clk[0]), "n": 3, "done": [nb6 - 145_000]}]
ws6["ux"] = [{"a": nb6 - 120_000, "ba": "1", "na": 0, "z": nb6 - 110_000, "bz": "2", "nz": 0, "t0": int(clk[0]), "why": "공백"}]
st6["rqp"] = [{"it": {"chain": "bsc", "wallet": B.W1, "block": nb6, "chain_bal_raw": "1", "block_ts": 1, "diff_raw": str(2 * E17)}, "aft": ["0x" + "9" * 64], "t": int(clk[0])}]
st6["d"][B.W1] = {"0x" + "8" * 64: [nb6, str(2 * E17), 0]}
statefile.atomic_write_json(BALW, st6)
clk[0] += 600
p6 = restore()
rs6 = wst().get("rs") or {}
T.chk(rs6.get("a") == ja6 and rs6.get("z") == cp6 and not wst().get("jobs") and not wst().get("ux") and not balw_st().get("rqp")
      and not (balw_st().get("d") or {}).get(B.W1) and any("bsc_balw.json" in n9 and "작업 1·미해결 구간 1" in n9 for n9 in p6["notes"]),
      "RS6 계획: 다시 점검 구간 = (남은 작업 중 가장 이른 시작, 체크포인트] · 작업·미해결 구간·보류 요청·옛 색인 칸 정리 · 안내", {"rs": rs6, "notes": p6["notes"]})
wr6 = B.Wr()
w6 = mk(wr6)
run(w6, wr6, 40)
T.chk(len(recs(wr6, dep6)) == 1 and in_ledger(dep6) == 1 and not reqs() and jobs_left() == 0 and ux_left() == 0,
      "RS6 복구 뒤 정확히 1건 · 옛 보류 요청 안 씀 · 남은 일 0", {"n": len(recs(wr6, dep6)), "req": reqs(), "w": wst()})

dep8, nb8, wr8a, cp8 = scenario(arch=False)
T.chk(len(recs(wr8a, dep8)) == 1 and in_ledger(dep8) == 1, "RS8 전제: 아카이브 없어도 최근 수신은 공개 노드로 찾음", {"n": len(recs(wr8a, dep8)), "req": reqs()})
clk[0] += 600
restore()
wr8 = B.Wr()
w8 = mk(wr8, arch=False)
run(w8, wr8, 40)
rq8 = [it for it in reqs() if it.get("wallet") == B.W1]
lg8 = [r9 for r9 in (balw_st().get("reqs") or []) if "아카이브 없음" in str(r9[3])]
T.chk(len(rq8) == 1 and rq8[0].get("block") == cp8 and rq8[0].get("sources") == ["bsc_balance_watch_old"] and not recs(wr8, dep8)
      and lg8 and "원장 복구" in str(lg8[-1][3]) and not wst().get("rs"),
      "RS8 아카이브 없음 = 다시 점검 구간 끝 블록 기초 잔고 요청 1번(옛 몫 · 범위·이유 기록) · 거짓 방출 0 · 조용한 완료 없음",
      {"req": reqs(), "log": balw_st().get("reqs"), "w": wst()})

dep9, nb9, _wr, _cp = scenario()
backup(seg=1, off=0)
before9 = balw_st()
p9 = restore()
T.chk(p9["rewind"] == [] and "bsc_balw.json" not in p9["files"] and balw_st() == before9,
      "RS9 정상 다시 읽기(인박스 연속) = BSC 되감기 없음 · 잔고 감시 상태 그대로", {"rewind": p9["rewind"], "files": sorted(p9["files"])})

WX = "0x" + "a9" * 20
st_p = {"v": 1, "w": {B.W1: {"cp": [1000, "5", 2], "cp_at": 1, "jobs": [{"a": 700}], "ux": [{"a": 800}], "rs": {"a": 650, "z": 900}},
                      B.W2: {"cp": [1000, "5", 2]}, WX: {"cp": [400, "1", 0]}},
        "d": {B.W1: {"0xaa": [950, "1", 0], "0xbb": [1100, "1", 0], "0xcc": [1100, "1", 0]}, WX: {"0xaa": [500, "1", 0], "0xcc": [500, "1", 0]}},
        "rqp": [{"it": {"wallet": B.W1, "block": 990}}, {"it": {"wallet": "0x" + "a8" * 20, "block": 990}}]}
B.reset_state()
statefile.atomic_write_json(BALW, st_p)
nt = []
out = LR._plan_bsc_balw(paths.STATE_DIR, {"0xaa", "0xbb"}, 900, 77, nt)
T.chk(out["w"][B.W1]["rs"] == {"a": 650, "z": 1000, "bz": "5", "nz": 2, "t0": 77} and "jobs" not in out["w"][B.W1] and "ux" not in out["w"][B.W1]
      and out["w"][B.W2]["rs"]["a"] == 900 and "rs" not in out["w"][WX]
      and out["d"][B.W1] == {"0xbb": [1100, "1", 0]} and out["d"][WX] == {"0xaa": [500, "1", 0]}
      and [e["it"]["wallet"] for e in out["rqp"]] == ["0x" + "a8" * 20] and nt and "2개 지갑" in nt[0],
      "P1 계획: 시작 = min(되감은 커서·작업·미해결·지난 복구 구간) · 끝 = 체크포인트 · 체크포인트가 되감기 앞인 지갑 무변 · 색인 = 구간 밖·백업에 있는 것만 · 보류 요청 정리",
      {"out": out, "notes": nt})
T.chk(LR._plan_bsc_balw(paths.STATE_DIR, set(), 900, 77, []) is not None and LR._plan_bsc_balw(os.path.join(paths.STATE_DIR, "없음"), set(), 900, 77, []) is None,
      "P1 상태 파일 없음 = 계획 없음(새 설치)")

T.finish()
