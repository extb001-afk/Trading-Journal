#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _gate as _x
from _gate import check, done
import builtins
import os
import shutil
import sqlite3
import subprocess
import time
import common
import core
import db as dbm
import ledger_backup as LB
import ledger_restore as LR

assert _x.TMP in common.STATE_DIR
core.dm = lambda *a, **k: None
T.patch_moved("dm", core.dm)
c = core.Core(common.load_config())
S = common.STATE_DIR
LIVE = common.DB_PATH
BK = os.path.join(S, "backups")
HOME = os.path.join(_x.TMP, "home_rp")
os.makedirs(HOME, exist_ok=True)
c.cfg.setdefault("backfill", {})["rebuild_dir"] = HOME
MB = 1 << 20
DEV = LB.dev_of(S)
restore_state = getattr(LB, "restore_state", None)


def rs(path, deep=True):
    if restore_state is None:
        return ("(없음)", "restore_state 없음")
    r9 = T.safe(restore_state, path, deep=deep)
    return ("(예외)", r9["_exc"]) if isinstance(r9, dict) else tuple(r9)


def mk(path, tag, meta=None, pad=0):
    for sfx in ("", "-wal", "-shm", "-journal"):
        try:
            os.remove(path + sfx)
        except FileNotFoundError:
            pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cx = dbm.open_db(path)
    cx.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('tag', ?)", (tag,))
    for k, v in (meta or {}).items():
        cx.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (k, v))
    cx.execute("CREATE TABLE IF NOT EXISTS filler (x BLOB)")
    cx.executemany("INSERT INTO filler VALUES (?)", [(os.urandom(900),) for _ in range(300)])
    cx.commit()
    cx.execute("PRAGMA journal_mode=DELETE").fetchone()
    cx.close()
    for sfx in ("-wal", "-shm"):
        if os.path.exists(path + sfx):
            os.remove(path + sfx)
    if pad:
        os.truncate(path, os.path.getsize(path) + pad)
    return path


def to_wal(path):
    cx = sqlite3.connect(path)
    cx.execute("PRAGMA journal_mode=WAL").fetchone()
    cx.close()
    return path


def bad_wal(path):
    to_wal(path)
    with open(path + "-wal", "wb") as f:
        f.write(b"\xab" * 8192)


def tag(path):
    cx = sqlite3.connect(common.sqlite_ro_uri(path, immutable=True), uri=True)
    try:
        return cx.execute("SELECT v FROM meta WHERE k='tag'").fetchone()[0]
    finally:
        cx.close()


def restorable(path):
    return os.path.isfile(path) and bool(LR.check(path).get("ok"))


def junk(path, size=64 * 1024):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.truncate(size)


def clear():
    for n in os.listdir(S):
        if n.startswith("ledger.db.") or n == "ext_rebuild_status.json":
            os.remove(os.path.join(S, n))
    shutil.rmtree(BK, ignore_errors=True)
    LB.__dict__.pop("open", None)
    cache = getattr(LB, "_VERIFIED", None)
    if isinstance(cache, dict):
        cache.clear()


def always_short():
    return {DEV: 1 << 50}


def deny_read(*targets):
    tg = {os.path.abspath(t) for t in targets}

    def _open(p, *a, **k):
        if isinstance(p, str) and os.path.abspath(p) in tg:
            raise PermissionError(13, "합성: 권한 없음", p)
        return builtins.open(p, *a, **k)
    LB.open = _open


PRE = [LIVE + ".pre_extrebuild_2026100%d_000000" % i for i in (1, 2, 3)]
DAY = [os.path.join(BK, "ledger_2026100%d.db" % i) for i in (1, 2, 3)]

clear()
V = os.path.join(_x.TMP, "v")
good = mk(os.path.join(V, "good.db"), "g")
check("[V] (전제) 합성 원장 = 복구 도구 통과", restorable(good), LR.check(good)["why"])
check("[V] 정상 사본 = valid(깊은 검사 · 가벼운 검사 모두)", rs(good)[0] == "valid" and rs(good, deep=False)[0] == "valid", (rs(good), rs(good, False)))
t100 = mk(os.path.join(V, "t100.db"), "t")
os.truncate(t100, 100)
check("[V] 100바이트로 잘림 = invalid(복구 도구도 거부)", rs(t100)[0] == "invalid" and not restorable(t100), rs(t100))
thalf = mk(os.path.join(V, "thalf.db"), "t")
ps = int.from_bytes(open(thalf, "rb").read(100)[16:18], "big")
os.truncate(thalf, (os.path.getsize(thalf) // ps // 2) * ps)
check("[V] 페이지 경계에서 절반으로 잘림 = invalid(가벼운 검사로도 — 머리의 페이지 수보다 짧음)", rs(thalf, deep=False)[0] == "invalid"
      and not restorable(thalf), (rs(thalf, False), LR.check(thalf)["why"]))
mid = mk(os.path.join(V, "mid.db"), "m")
with open(mid, "r+b") as f:
    f.seek(os.path.getsize(mid) // 2)
    f.write(b"\xa5" * (ps * 3))
check("[V] 중간 페이지 손상 = 깊은 검사(quick_check) invalid · 복구 도구도 거부", rs(mid)[0] == "invalid" and not restorable(mid), rs(mid))
inc = mk(os.path.join(V, "inc.db"), "i", meta={"rebuild_incomplete": "1"})
oldsv = mk(os.path.join(V, "oldsv.db"), "o")
cx = sqlite3.connect(oldsv)
cx.execute("UPDATE meta SET v=? WHERE k='schema_version'", (str(dbm.SCHEMA_VERSION - 1),))
cx.commit()
cx.close()
check("[V] 재파생 미완 표식 · 원장 세대 다름 = invalid(복구 도구도 거부)", rs(inc)[0] == "invalid" and rs(oldsv)[0] == "invalid"
      and not restorable(inc) and not restorable(oldsv), (rs(inc), rs(oldsv)))
walbad = mk(os.path.join(V, "walbad.db"), "w")
bad_wal(walbad)
check("[V] 원장(WAL 형식)은 정상인데 -wal 머리 손상 = invalid(그 WAL 의 커밋은 sqlite 가 통째로 버림)", rs(walbad)[0] == "invalid", rs(walbad))
stray = mk(os.path.join(V, "stray.db"), "s")
open(stray + "-wal", "wb").write(b"\xab" * 8192)
check("[V] 단일 파일(DELETE 저널) 사본 옆의 엉뚱한 -wal 은 sqlite 가 안 봄 = valid", rs(stray)[0] == "valid" and restorable(stray), rs(stray))
den = mk(os.path.join(V, "den.db"), "d")
deny_read(den)
r_den = rs(den)
LB.__dict__.pop("open", None)
check("[V] 읽기 권한 오류 = unknown(종전 가벼운 검사는 '검사 못 함'을 통과로 침)", r_den[0] == "unknown", r_den)
check("[V] 없는 파일 = valid 아님", rs(os.path.join(V, "nope.db"))[0] in ("invalid", "unknown"), rs(os.path.join(V, "nope.db")))
wv = os.path.join(V, "walok.db")
subprocess.run([sys.executable, "-c", r'''
import os, shutil, sqlite3, sys
sys.path.insert(0, sys.argv[2])
import db
p = sys.argv[1]
c = db.open_db(p); c.execute("PRAGMA journal_mode=WAL").fetchone(); c.execute("PRAGMA wal_autocheckpoint=0"); c.commit()
c.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('tag', 'inwal')"); c.commit()
for s in ("", "-wal", "-shm"):
    shutil.copyfile(p + s, p + ".cp" + s)
os._exit(0)
''', wv, T.SRC], check=True, env=dict(os.environ))
wvc = wv + ".cp"
check("[V] (전제) 커밋이 WAL 에만 있음 · 복구 도구 통과", os.path.getsize(wvc + "-wal") > 0 and restorable(wvc), LR.check(wvc)["why"])
check("[V] 커밋이 WAL 에만 있는 정상 사본 = valid(WAL 머리 체크섬 확인)", rs(wvc)[0] == "valid", rs(wvc))
good2 = mk(os.path.join(V, "good2.db"), "g2")
r1 = rs(good2)
os.truncate(good2, 100)
r2 = rs(good2)
check("[V] 검사 결과 캐시는 파일이 바뀌면 무효(정상 → 잘림 = invalid)", r1[0] == "valid" and r2[0] == "invalid", (r1, r2))
shutil.rmtree(V, ignore_errors=True)

clear()
mk(PRE[1], "old")
mk(PRE[2], "latest")
os.truncate(PRE[2], 100)
rP = LB.relieve(LIVE, always_short)
check("[P] pre_extrebuild 정상 old + 잘린 latest → 정상 old 남음(복구 도구 통과)", restorable(PRE[1]) and tag(PRE[1]) == "old",
      {"left": [os.path.basename(p) for p in PRE if os.path.exists(p)], "removed": rP.get("removed")})
check("[P] 잘린 latest 도 지우지 않음(손상 판정은 보류 — 자동 삭제 안 함) · 확보 실패 = ok False", os.path.exists(PRE[2]) and rP.get("ok") is False, rP)
check("[P] 남긴 이유가 relief 기록(skipped)에", any("pre_extrebuild_20261003" in str(s.get("name")) for s in rP.get("skipped") or []), rP.get("skipped"))
clear()
junk(PRE[0], 3 * MB)
junk(PRE[0] + "-wal", 1 * MB)
mk(PRE[1], "old")
mk(PRE[2], "latest")
os.truncate(PRE[2], 100)
rP3 = LB.relieve(LIVE, always_short)
check("[P] 보호본(가장 최신의 검증된 사본)보다 오래된 것은 정리 · 보호본·잘린 latest 는 남김",
      not os.path.exists(PRE[0]) and not os.path.exists(PRE[0] + "-wal") and restorable(PRE[1]) and os.path.exists(PRE[2]),
      {"left": [os.path.basename(p) for p in PRE if os.path.exists(p)], "removed": rP3.get("removed")})

clear()
junk(DAY[0], 2 * MB)
mk(DAY[1], "d-old")
mk(DAY[2], "d-latest")
os.truncate(DAY[2], 100)
rD = LB.relieve(LIVE, always_short)
check("[D] 일일 백업 정상 old + 잘린 latest → 정상 old 남음 · 더 오래된 것만 정리", restorable(DAY[1]) and os.path.exists(DAY[2])
      and not os.path.exists(DAY[0]), {"left": [os.path.basename(p) for p in DAY if os.path.exists(p)], "removed": rD.get("removed")})

clear()
junk(DAY[0], 2 * MB)
mk(DAY[1], "d-latest")
junk(PRE[1], 2 * MB)
mk(PRE[2], "latest")
n_rs = []
real_rs = getattr(LB, "restore_state", None)
if real_rs is not None:
    LB.restore_state = lambda *a, **k: (n_rs.append(a[0]), real_rs(*a, **k))[1]
try:
    rO = LB.relieve(LIVE, lambda: {DEV + 7777: 1 << 50})
finally:
    if real_rs is not None:
        LB.restore_state = real_rs
check("[D] 모자란 디스크 밖의 계열 = 검사 없이 보류(복구 검사 0회) · 하나도 안 지움",
      not n_rs and real_rs is not None and all(os.path.exists(p) for p in (DAY[0], DAY[1], PRE[1], PRE[2])) and not rO.get("removed"),
      {"checked": [os.path.basename(x) for x in n_rs], "removed": rO.get("removed")})

clear()
mk(PRE[1], "old")
mk(PRE[2], "latest")
mk(DAY[1], "d-old")
mk(DAY[2], "d-latest")
deny_read(PRE[2], DAY[2])
rU = LB.relieve(LIVE, always_short)
LB.__dict__.pop("open", None)
check("[U] 검사 불가(권한 오류) latest → 정상 old 남음 · latest 도 그대로(unknown = 삭제 보류)",
      restorable(PRE[1]) and restorable(DAY[1]) and os.path.exists(PRE[2]) and os.path.exists(DAY[2]),
      {"pre": [os.path.basename(p) for p in PRE if os.path.exists(p)], "day": [os.path.basename(p) for p in DAY if os.path.exists(p)],
       "removed": rU.get("removed")})
clear()
junk(PRE[1], 2 * MB)
mk(PRE[2], "latest")
deny_read(PRE[2])
rU2 = LB.relieve(LIVE, always_short)
LB.__dict__.pop("open", None)
check("[U] 검증된 사본이 하나도 없으면(latest 검사 불가 · old 손상) 그 계열은 하나도 안 지움", os.path.exists(PRE[1]) and os.path.exists(PRE[2]),
      rU2.get("removed"))

for lbl, prep in (("원장(WAL 형식) 정상·WAL 머리 손상", bad_wal),
                  ("재파생 미완 표식", lambda p: mk(p, "latest", meta={"rebuild_incomplete": "1"})),
                  ("원장 세대 다름", lambda p: mk(p, "latest", meta={"schema_version": str(dbm.SCHEMA_VERSION + 1)}))):
    clear()
    mk(PRE[1], "old")
    mk(PRE[2], "latest")
    prep(PRE[2])
    rW = LB.relieve(LIVE, always_short)
    check(f"[W] latest {lbl} → 정상 old 남음(복구 도구 통과)", restorable(PRE[1]) and os.path.exists(PRE[2]), rW.get("removed"))

clear()
junk(PRE[0], 3 * MB)
mk(PRE[1], "old")
mk(PRE[2], "latest")
os.truncate(PRE[2], 100)
junk(DAY[0], 3 * MB)
mk(DAY[1], "d-old")
mk(DAY[2], "d-latest")
os.truncate(DAY[2], 100)


def plan_f(home, live):
    short9 = (1 if os.path.exists(PRE[0]) else 0) + (1 if os.path.exists(DAY[0]) else 0)
    p9 = {"size": 1 * MB, "same": True, "at": int(time.time()),
          "rows": [{"dev": DEV, "what": "same", "free": 100 * MB - short9 * 2 * MB, "need": 99 * MB}]}
    c._ext_disk = p9
    return p9


class _R2:
    returncode, stdout, stderr = 2, "", "합성: 업비트 재대사 미완(rc=2)"


calls = []
real_run, real_plan = subprocess.run, c._ext_disk_plan
subprocess.run = lambda *a, **k: (calls.append(a[0] if a else k.get("args")), _R2())[1]
c._ext_disk_plan = plan_f
n_net = len(T.NET_TRIES)
try:
    c._ext_rebuild({"base": 1}, [])
finally:
    subprocess.run, c._ext_disk_plan = real_run, real_plan
errF = str(c._meta_get("ext_rebuild_last_error") or "")
check("[F] (전제) 자동 정리로 충분 → rebuild2 1회 실행 → rc=2 실패(원인 transient_rpc)",
      len(calls) == 1 and errF.startswith("rebuild2 rc=2") and c._meta_get("ext_rebuild_fail_code") == "transient_rpc", (len(calls), errF))
check("[F] rebuild2 실패 뒤에도 pre_extrebuild·일일 백업 각각 복구 가능한 사본이 남음(복구 도구 통과)",
      restorable(PRE[1]) and restorable(DAY[1]) and tag(PRE[1]) == "old" and tag(DAY[1]) == "d-old",
      {"pre": [os.path.basename(p) for p in PRE if os.path.exists(p)], "day": [os.path.basename(p) for p in DAY if os.path.exists(p)]})
check("[F] 쓸모없는 가장 오래된 사본은 정리 · 손상 latest 는 남김 · 바깥 연결 0",
      not os.path.exists(PRE[0]) and not os.path.exists(DAY[0]) and os.path.exists(PRE[2]) and os.path.exists(DAY[2])
      and len(T.NET_TRIES) == n_net, T.NET_TRIES[n_net:])

clear()


def swap_dir(name):
    d9 = os.path.join(_x.TMP, name)
    os.makedirs(d9)
    lv = os.path.join(d9, "ledger.db")
    for tsx in ("20260101_000000", "20260201_000000"):
        mk(lv + ".pre_extrebuild_" + tsx, "old" + tsx[4:6])
    mk(lv, "cur")
    mk(lv + ".extnew_X", "new")
    return d9, lv


d, live = swap_dir("swap_unknown")
deny_read(live + ".pre_extrebuild_20260401_000000")
try:
    core.Core._ext_swap(live, live + ".extnew_X", "20260401_000000")
finally:
    LB.__dict__.pop("open", None)
left = sorted(f for f in os.listdir(d) if ".pre_extrebuild_" in f and not f.endswith(("-wal", "-shm")))
check("[S] 이번 보존본을 검사할 수 없으면(unknown) 옛 보존본 2개 그대로 + 이번 것", len(left) == 3 and tag(live) == "new", left)
d2, live2 = swap_dir("swap_ok")
core.Core._ext_swap(live2, live2 + ".extnew_X", "20260401_000000")
left2 = sorted(f for f in os.listdir(d2) if ".pre_extrebuild_" in f and not f.endswith(("-wal", "-shm")))
check("[S] 정상 교체 = 종전대로 이번 것 1개(옛 보존본 정리)", left2 == ["ledger.db.pre_extrebuild_20260401_000000"]
      and tag(live2 + ".pre_extrebuild_20260401_000000") == "cur", left2)

clear()
junk(PRE[0], 2 * MB)
junk(PRE[1], 2 * MB)
mk(PRE[2], "latest")
junk(DAY[0], 2 * MB)
mk(DAY[1], "d-latest")
rN = LB.relieve(LIVE, always_short)
check("[N] 정상 latest → 옛 사본 정리 · latest 남음(종전과 같음)", [os.path.exists(p) for p in PRE] == [False, False, True]
      and [os.path.exists(p) for p in DAY[:2]] == [False, True] and restorable(PRE[2]) and restorable(DAY[1]), rN.get("removed"))
clear()
mk(PRE[2], "only")
os.truncate(PRE[2], 100)
check("[N] 사본이 하나뿐이면 후보 0(손상이어도 종전처럼 남김)", LB.relief_candidates("pre_extrebuild", LIVE) == [],
      LB.relief_candidates("pre_extrebuild", LIVE))
clear()
done()
