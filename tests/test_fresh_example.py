#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import re

p = os.path.join(T.ROOT, "config.example.json")
c = json.load(open(p, encoding="utf-8"))
b = c.get("bsc") or {}
logs = [str(u) for u in b.get("logs_rpcs") or []]
T.chk(any("bsc.rpc.sentio.xyz" in u for u in logs), "E1 BSC 로그 노드에 옛 구간 무키 노드(sentio)", logs)
T.chk(not any("drpc.org" in u for u in logs), "E2 BSC 로그 노드에 무료 drpc 없음", logs)
fb = b.get("logs_rpcs_fallback")
T.chk(isinstance(fb, dict) and fb and all(isinstance(v, int) and v > 0 for v in fb.values()), "E3 BSC 예비 로그 노드 {URL: 상한}", fb)
keyish = re.compile(r"/v\d+/[0-9a-fA-F]{24,}|[?&](?:api[-_]?key|key|token)=|/[A-Za-z0-9_-]{24,}", re.I)
T.chk(not any(keyish.search(u) for u in logs + list(fb or {})), "E4 BSC 예시 노드 = 무키 공개 주소")
T.finish()
