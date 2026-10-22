#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import collections  # noqa: E402
import glob  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402

import calcguard as CG  # noqa: E402
import health  # noqa: E402

chk = T.chk
os.environ.pop("TJ_STRICT", None)

for site, exc in (("t:s1k", KeyError("k")), ("t:s1t", TypeError("t")), ("t:s1z", ZeroDivisionError("z")),
                  ("t:s1u", UnicodeEncodeError("ascii", "Т", 0, 1, "x")), ("t:s1v", ValueError("v")), ("t:s1o", OSError("net"))):
    try:
        raise exc
    except Exception as e:
        CG.swallowed(site, e)
sn = CG.snapshot()
chk(all(sn[s].get("sus") == 1 and sn[s].get("bug") == 0 for s in ("t:s1k", "t:s1t", "t:s1z", "t:s1u")), "S1 KeyError·TypeError·0나누기·Unicode = 의심", sn)
chk(sn["t:s1v"].get("sus") == 0 and sn["t:s1o"].get("sus") == 0, "S1 값·네트워크 오류 = 의심 아님(정보)", sn)

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

cnt = collections.Counter()
for f in glob.glob(os.path.join(T.SRC, "*.py")) + glob.glob(os.path.join(T.SRC, "*", "*.py")):
    for m in re.finditer(r'calcguard\.swallowed\("([^"]+)"', open(f, encoding="utf-8").read()):
        cnt[m.group(1)] += 1
dup = {k: v for k, v in cnt.items() if v > 1}
chk(len(cnt) > 300 and not dup, "S4 calcguard 자리 이름 전부 고유", dup)

T.finish()
