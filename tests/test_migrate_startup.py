#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import calcguard  # noqa: E402
import config, paths  # noqa: E402
import core  # noqa: E402

assert T.TMP in paths.STATE_DIR
chk = T.chk
NAMES = ("_reclass_plain_xfer_once", "_reclass_added_lp_mgrs_once", "_out_px_band_fix_once")
SITE = {n: "core:Core.run[%s]" % n for n in NAMES}
FAIL_LOG = {"_reclass_plain_xfer_once": "평범한 전송 재분류 실패(원장 무변, 다음 기동 재시도): ",
            "_reclass_added_lp_mgrs_once": "새 LP 관리자 재분류 실패(원장 무변, 다음 기동 재시도): ",
            "_out_px_band_fix_once": "보낸 내역 시가 되돌림 실패(원장 무변, 다음 기동 재시도): "}


class _Stop(Exception):
    pass


class _Logs(logging.Handler):

    def __init__(self):
        super().__init__(logging.ERROR)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


LOGS = _Logs()
logging.getLogger("tj-core").addHandler(LOGS)


class _Mgrs(dict):

    def __init__(self, hook):
        super().__init__()
        self.hook = hook

    def items(self):
        self.hook()
        return super().items()

    def __bool__(self):
        return True


def boot(c, fakes=None):
    order = []
    fakes = fakes or {}

    def hook(name):
        how = fakes.get(name)
        if how is None:
            return
        order.append(name)
        c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", ("t_probe:" + name, how))
        if how == "raise":
            raise sqlite3.OperationalError("database is locked")
        c.conn.commit()
    real_get = type(c)._meta_get
    stamp_of = {"reclass_q_plainxfer": NAMES[0], "px_out_band_r": NAMES[2]}

    def meta_get(k, *a, **kw):
        if k in stamp_of:
            hook(stamp_of[k])
        return real_get(c, k, *a, **kw)

    def stop(*a, **k):
        order.append("drain")
        raise _Stop()
    mgrs = c.lp_mgrs
    c._meta_get = meta_get
    c.lp_mgrs = _Mgrs(lambda: hook(NAMES[1]))
    c._drain_stream = stop
    before = calcguard.snapshot()
    LOGS.lines = []
    try:
        c.run()
    except _Stop:
        pass
    finally:
        c.lp_mgrs = mgrs
        del c._meta_get
        del c._drain_stream
    after = calcguard.snapshot()
    grew = {}
    for k, v in after.items():
        b0 = before.get(k) or {}
        if v["n"] > b0.get("n", 0):
            grew[k] = (v["n"] - b0.get("n", 0), sorted(t for t, m in v["types"].items() if m > b0.get("types", {}).get(t, 0)))
    return order, list(LOGS.lines), grew


def probes(c):
    return {r[0].split(":", 1)[1]: r[1] for r in c.conn.execute("SELECT k, v FROM meta WHERE k LIKE 't_probe:%'")}


C = core.Core(config.load_config())
chk(not C.lp_mgrs, "S0 합성 LP 관리자 시드 = 비어 있음")

order, logs, grew = boot(C)
st1 = {k: C._meta_get(k) for k in ("reclass_q_plainxfer", "px_out_band_r")}
lp1 = C.conn.execute("SELECT count(*) FROM meta WHERE k LIKE 'reclass_lp_mgr:%'").fetchone()[0]
chk(all(st1.values()) and lp1 == 0 and order == ["drain"] and not logs and not grew,
    "S1 실제 세 변환 = 도장 2(평범한 전송 · 보낸 내역 시가) · LP 관리자 도장 0 · 실패 0 · 첫 소비까지 감", (st1, lp1, order, logs, grew))
boot(C)
chk({k: C._meta_get(k) for k in st1} == st1, "S1 두 번째 기동 = 도장 값 그대로(1회 · 다시 안 돎)")

order, logs, grew = boot(C, {n: "ok" for n in NAMES})
chk(order == list(NAMES) + ["drain"] and not logs and not [k for k in grew if k in SITE.values()],
    "S2 차례 = 평범한 전송 → 새 LP 관리자 → 보낸 내역 시가 → 첫 소비 · 실패 기록·로그 0", (order, logs, grew))
C.conn.execute("DELETE FROM meta WHERE k LIKE 't_probe:%'")
C.conn.commit()

for bad in NAMES:
    order, logs, grew = boot(C, {n: ("raise" if n == bad else "ok") for n in NAMES})
    pr = probes(C)
    want_pr = {n: "ok" for n in NAMES if n != bad}
    chk(order == list(NAMES) + ["drain"], "S3 %s 던짐 = 나머지 변환 계속 · 차례 같음 · 첫 소비까지 감" % bad, order)
    chk({k: v for k, v in grew.items() if k in SITE.values()} == {SITE[bad]: (1, ["OperationalError"])},
        "S3 %s 던짐 = 위치 글 %s 기록 1(예외 종류 그대로)" % (bad, SITE[bad]), grew)
    chk(logs == [FAIL_LOG[bad] + "database is locked"], "S3 %s 던짐 = 오류 로그 한 줄(글 그대로)" % bad, logs)
    chk(pr == want_pr, "S3 %s 던짐 = 쓰다 만 원장 쓰기 되돌림(다음 커밋에 안 섞임) · 성공한 변환 쓰기는 남음" % bad, pr)
    C.conn.execute("DELETE FROM meta WHERE k LIKE 't_probe:%'")
    C.conn.commit()

order, logs, grew = boot(C, {n: "raise" for n in NAMES})
chk(order == list(NAMES) + ["drain"] and logs == [FAIL_LOG[n] + "database is locked" for n in NAMES]
    and {k: v for k, v in grew.items() if k in SITE.values()} == {SITE[n]: (1, ["OperationalError"]) for n in NAMES} and probes(C) == {},
    "S4 셋 다 던짐 = 위치 글 3 · 오류 로그 3(차례대로) · 쓰다 만 것 0 · 첫 소비까지 감", (order, logs, grew))

T.finish()
