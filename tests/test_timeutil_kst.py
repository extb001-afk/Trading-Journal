#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import math  # noqa: E402
import random  # noqa: E402
import time  # noqa: E402
import warnings  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from decimal import Decimal  # noqa: E402

sys.path.insert(0, T.SRC)
import timeutil  # noqa: E402

chk = T.chk
warnings.simplefilter("ignore", DeprecationWarning)
REF = timezone(timedelta(hours=9))


def outcome(fn, *a):
    try:
        return ("ok", fn(*a))
    except Exception as e:   # noqa: BLE001
        return ("err", type(e).__name__)


B = [k * 86400 - 32400 for k in (-3, -1, 0, 1, 19700, 20000, 20380, 24855)]
NUM = [0, 1, -1, 0.5, -0.5, -1.5, 32399, 32400, 32399.999999, -32400, -32401, 1e-9, -1e-9]
for b in B:
    NUM += [b, b - 1, b + 1, b - 0.5, b + 0.5, b - 1e-6, b + 1e-6, float(b), math.nextafter(float(b), -math.inf),
            math.nextafter(float(b), math.inf)]
rnd = random.Random(4707)
for _ in range(4000):
    x = rnd.uniform(-2e9, 4e9)
    NUM += [x, int(x), math.nextafter(x, math.inf)]
FLOATS = [float(x) for x in NUM]
ODD = [None, "", "1700000000", " 1700000000.5 ", "abc", True, False, Decimal("1700000000.25"), float("nan"), float("inf"), -float("inf"),
       1e300, 10 ** 20, [], {}]

chk(timeutil.KST == REF and type(timeutil.KST) is timezone and repr(timeutil.KST) == repr(REF) and timeutil.KST_OFFSET_S == 32400,
    "K1 KST = timezone(timedelta(hours=9)) · KST_OFFSET_S = 32400", repr(timeutil.KST))
moved = ["acct_norm", "addr_ai", "alert_prefs", "alert_watch", "balcheck", "buychart", "candles", "chk_base", "demo_data", "fut_rcpt",
         "histcurve", "ledger_backup", "nft", "other_assets", "review_daily", "search_index", "sellchart", "wow", "wow2",
         "view_daily", "view_b_replay", "web",
         "brokers.kis", "brokers.kiwoom", "brokers.ls"]
import importlib  # noqa: E402
same = []
for m in moved:
    try:
        same.append(importlib.import_module(m).KST is timeutil.KST)
    except ImportError as e:
        same.append(None if "No module named" in str(e) else False)
chk(all(s is not False for s in same) and same.count(True) >= 22, "K1 머리 정의를 옮긴 모듈의 KST = timeutil.KST(같은 객체 · %d/%d)" % (same.count(True), len(moved)),
    [m for m, s in zip(moved, same) if s is False])

d2 = [x for x in FLOATS if outcome(lambda v: time.strftime("%Y-%m-%d", time.gmtime(v + 9 * 3600)), x) !=
      outcome(timeutil.kst_day, x)]
d2b = [x for x in FLOATS if outcome(lambda v: time.strftime("%Y-%m-%d", time.gmtime(v + 9 * 3600 - 7 * 86400)), x) !=
       outcome(timeutil.kst_day, x, 7)]
chk(not d2 and not d2b, "K2 rabby 인라인 ↔ kst_day(now) · kst_day(now, 7) — %d개 실수 입력 같음" % len(FLOATS), (d2[:5], d2b[:5]))

D = 7
d3 = [x for x in NUM if outcome(lambda v: time.strftime("%Y-%m-%d", time.gmtime(v + 9 * 3600 - D * 86400)), x) !=
      outcome(timeutil.kst_day, x, D)]
chk(not d3, "K3 web 인라인 ↔ kst_day(now, %d) — %d개 정수·실수 입력 같음" % (D, len(NUM)), d3[:5])

def old_hm(ts):
    return time.strftime("%H:%M", time.gmtime(float(ts or 0) + 9 * 3600))


def old_kday(ts):
    try:
        return time.strftime("%Y-%m-%d", time.gmtime(float(ts) + 9 * 3600))
    except (TypeError, ValueError):
        return None


import liq_watch  # noqa: E402
import upbit_link  # noqa: E402
ALL = NUM + ODD
d4 = [x for x in ALL if outcome(old_hm, x) != outcome(liq_watch.hm_kst, x)]
d4b = [x for x in ALL if outcome(old_kday, x) != outcome(upbit_link._kst_day, x)]
chk(not d4 and not d4b, "K4 liq_watch.hm_kst · upbit_link._kst_day ↔ 종전 식 — %d개 입력(문자열·None·bool·nan·inf·큰 값 포함) 결과·예외 같음"
    % len(ALL), (d4[:5], d4b[:5]))

def old_iso(ts):
    return datetime.fromtimestamp(ts, timezone(timedelta(hours=9))).strftime("%Y-%m-%dT%H:%M:%S+09:00")


def old_day0(ts):
    d = datetime.fromtimestamp(int(float(ts)), timezone(timedelta(hours=9)))
    return int(d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())


d5 = [x for x in ALL if outcome(old_iso, x) != outcome(upbit_link._iso, x)]
d5b = [x for x in ALL if outcome(old_day0, x) != outcome(timeutil.kst_day0, x)]
chk(not d5 and not d5b, "K5 upbit_link._iso · kst_day0 ↔ timezone(timedelta(hours=9)) 판 — %d개 입력 같음" % len(ALL), (d5[:5], d5b[:5]))

import acct_norm  # noqa: E402
ints = sorted({int(x) for x in NUM if abs(x) < 2.5e11})


def old_iso_day(ts):
    t = int(ts)
    return (t + 32400) // 86400, datetime.fromtimestamp(t, REF).strftime("%Y-%m-%d")


acct_norm._ISO_DAY.clear()
d6 = []
for x in ints:
    k_old, s_old = old_iso_day(x)
    s_new = acct_norm.iso_day(x)
    if s_new != s_old or acct_norm._ISO_DAY.get(k_old) != s_old:
        d6.append(x)
chk(not d6, "K6 acct_norm.iso_day 칸·글자 ↔ 종전(32400) — %d개 정수 입력 같음" % len(ints), d6[:5])
acct_norm._ISO_DAY.clear()
T.finish()
