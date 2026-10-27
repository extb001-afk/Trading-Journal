#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import collections  # noqa: E402
import glob  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402

import sqlite3  # noqa: E402

import calcguard as CG  # noqa: E402
import chk_base  # noqa: E402
import health  # noqa: E402

chk = T.chk
os.environ.pop("TJ_STRICT", None)

for site, exc in (("t:s1k", KeyError("k")), ("t:s1t", TypeError("t")), ("t:s1z", ZeroDivisionError("z")),
                  ("t:s1u", UnicodeEncodeError("ascii", "Т", 0, 1, "x")), ("t:s1v", ValueError("v")), ("t:s1o", OSError("net")),
                  ("t:s1q", sqlite3.OperationalError("q"))):
    try:
        raise exc
    except Exception as e:
        CG.swallowed(site, e)
sn = CG.snapshot()
chk(all(sn[s].get("sus") == 1 and sn[s].get("bug") == 0 for s in ("t:s1k", "t:s1t", "t:s1z", "t:s1u")), "S1 KeyError·TypeError·0나누기·Unicode = 의심", sn)
chk(sn["t:s1v"].get("sus") == 1 and sn["t:s1q"].get("sus") == 1, "S1 ValueError(int·Decimal 변환)·sqlite3.Error = 의심(세션31 #2-1 · 종전 정보)", sn)
chk(sn["t:s1o"].get("sus") == 0, "S1 네트워크 오류(OSError) = 의심 아님(정보)", sn)

os.environ["TJ_STRICT"] = "1"
try:
    try:
        raise KeyError("k")
    except Exception as e:
        CG.swallowed("t:s2", e)
    ok2 = True
except KeyError:
    ok2 = False
os.environ.pop("TJ_STRICT", None)
chk(ok2, "S2 엄격 모드 = 의심 꼴 재던짐 없음")

def _raised(exc, env, **kw):
    os.environ["TJ_STRICT"] = env
    try:
        try:
            raise exc
        except Exception as e:
            CG.swallowed("t:s5", e, **kw)
        return False
    except Exception as e2:
        return e2 is exc
    finally:
        os.environ.pop("TJ_STRICT", None)


chk(_raised(KeyError("k"), "2") and _raised(ValueError("v"), "2") and _raised(sqlite3.OperationalError("q"), "2"),
    "S5 TJ_STRICT=2 = KeyError·ValueError·sqlite3 재던짐(같은 예외 객체)")
chk(not _raised(KeyError("k"), "2", expected=True) and not _raised(KeyError("k"), "1") and not _raised(OSError("n"), "2"),
    "S5 expected=True·TJ_STRICT=1·네트워크 = 재던짐 없음")
chk(_raised(NameError("q"), "2", expected=True) and _raised(NameError("q"), "1"), "S5 코드 실수 꼴(NameError) = expected 여도 1·2단계 재던짐")
chk(CG.strict_level() == 0 and not CG.strict(), "S5 라이브(TJ_STRICT 없음) = 0단계")
import net_http  # noqa: E402
chk(not _raised(json.JSONDecodeError("x", "{", 0), "2") and not _raised(net_http.ResponseTooLarge("big"), "2")
    and not CG.suspect(json.JSONDecodeError("x", "{", 0)) and not CG.suspect(net_http.ResponseTooLarge("big")),
    "S5 응답 형식 오류(깨진 JSON·응답 상한 넘음 — ValueError 자식) = 의심 아님 · 재던짐 없음(네트워크 쪽)")
chk(all(CG.db_env(sqlite3.OperationalError(m)) for m in ("no such table: raw_ex", "unable to open database file", "database is locked"))
    and not CG.db_env(sqlite3.OperationalError("no such column: qty")) and not CG.db_env(ValueError("no such table")),
    "S5 db_env = 원장 없음·표 없음·잠김만(SQL 오타 꼴 'no such column' 아님)")

sd = os.path.join(T.TMP, "cgs")
os.makedirs(sd, exist_ok=True)
now = 2_000_000_000
json.dump({"v": 1, "proc": "web", "sites": {
    "view_b_replay:ReplayMixin._build_replay[br_deps9#1]": {"n": 2, "last": now - 60, "bug": 0, "sus": 2, "sus_last": now - 60, "sus_why": "KeyError: 'gid'"},
    "pricing:p": {"n": 9, "last": now - 60, "bug": 0, "why": "HTTPError: 429"},
    "old:s": {"n": 5, "last": now - 30, "bug": 0, "sus": 1, "sus_last": now - 3 * 86400, "sus_why": "TypeError: t"}}},
    open(os.path.join(sd, "calcguard_web.json"), "w"))
c = {x["cid"]: x for x in health.collect_calcguard(now, sd)}
s3 = c.get("calc:suspect") or {}
chk(s3.get("level") == "warn" and s3.get("notify") is False and "br_deps9#1" in s3.get("detail", "") and "KeyError" in s3.get("detail", "")
    and "old:s" not in s3.get("detail", ""), "S3 의심 = 노랑·알림 없음 · 자리·사유 표시 · 사흘 전 의심은 안 보임", c)
chk(c.get("calc:bug", {}).get("level") == "ok" and c.get("calc:swallow", {}).get("level") == "ok", "S3 빨강 없음 · 나머지 정보 줄 유지", c)
c2 = {x["cid"]: x for x in health.collect_calcguard(now + 2 * 86400, sd)}
chk("calc:suspect" not in c2, "S3 하루 지나면 노랑 사라짐", c2)

sd6 = os.path.join(T.TMP, "cgs6")
os.makedirs(sd6, exist_ok=True)
sites6 = {"t:o%d" % i: {"n": i + 1, "first": now - 600, "last": now - 60, "bug": 0, "why": "URLError: x%d" % i} for i in range(7)}
json.dump({"v": 1, "proc": "web", "sites": sites6}, open(os.path.join(sd6, "calcguard_web.json"), "w"))
c6 = {x["cid"]: x for x in health.collect_calcguard(now, sd6)}.get("calc:swallow") or {}
chk(c6.get("level") == "ok" and "7자리 · 28회(24h)" in c6.get("title", "") and c6.get("detail", "").startswith("t:o6 7회(URLError: x6)")
    and " 외 2곳" in c6.get("detail", "") and "t:o0 " not in c6.get("detail", "") and c6.get("notify") is False and c6.get("remind") is False,
    "S6 정보 줄 = 7자리·28회 · 많은 자리부터 상위 5 · 외 2곳 · 알림 없음", c6)
sites6["t:o6"].update(n=chk_base.CALC_OTHER_WARN_N)
sites6["t:old"] = {"n": 900, "first": now - 60 - 9 * 86400, "last": now - 60, "bug": 0, "why": "OSError: y"}
json.dump({"v": 1, "proc": "web_build", "sites": sites6}, open(os.path.join(sd6, "calcguard_web.json"), "w"))
c6b = {x["cid"]: x for x in health.collect_calcguard(now, sd6)}.get("calc:swallow") or {}
chk(c6b.get("level") == "warn" and c6b.get("notify") is False and c6b.get("remind") is False and c6b.get("detail", "").startswith("t:o6 100회")
    and "t:old 100회" in c6b.get("detail", "") and c6b.get("action"),
    "S6 한 자리 24시간 100회 = 노랑(알림 없음 · 할 일 안내) · 9일 누적 900회 = 하루 평균 100회", c6b)
sites6["t:o6"].update(n=99)
sites6["t:old"].update(n=890)
json.dump({"v": 1, "proc": "web", "sites": sites6}, open(os.path.join(sd6, "calcguard_web.json"), "w"))
c6c = {x["cid"]: x for x in health.collect_calcguard(now, sd6)}.get("calc:swallow") or {}
chk(c6c.get("level") == "ok" and "action" not in c6c, "S6 반대 방향: 99회·하루 평균 99회 = 정보(노랑 아님)", c6c)

cnt = collections.Counter()
for f in glob.glob(os.path.join(T.SRC, "*.py")) + glob.glob(os.path.join(T.SRC, "*", "*.py")):
    for m in re.finditer(r'calcguard\.swallowed\("([^"]+)"', open(f, encoding="utf-8").read()):
        cnt[m.group(1)] += 1
dup = {k: v for k, v in cnt.items() if v > 1}
chk(len(cnt) > 300 and not dup, "S4 calcguard 자리 이름 전부 고유", dup)

T.finish()
