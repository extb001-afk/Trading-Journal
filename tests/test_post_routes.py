#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import inspect  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402

import http_post_prefs  # noqa: E402
import http_route  # noqa: E402

nolock, locked = http_route.post_routes()
T.chk(nolock == http_route._NOLOCK and locked == http_route._LOCKED, "post_routes() = 모듈 전역 표(처음 한 번 만든 것)와 같음")
T.chk(len(nolock) == 11 and len(locked) == 22, "표 크기 잠금 밖 11 · 잠금 안 22", (len(nolock), len(locked)))
both = sorted(set(nolock) & set(locked))
T.chk(not both, "잠금 밖·안 표가 겹치지 않음(겹치면 사슬 차례가 바뀜)", both)
pre = http_route.OPS_PREFIX
under = sorted(k for k in list(nolock) + list(locked) if k.startswith(pre))
T.chk(pre == "/api/ops/" and not under, "표 경로 중 정리 요청 접두어 아래 0(접두어 검사보다 표가 먼저)", under)
odd = sorted(k for k in list(nolock) + list(locked) if not k.startswith("/api/") or k.endswith("/") or "?" in k)
T.chk(not odd, "표 경로 = /api/ 아래 정확 일치 꼴(끝 슬래시·쿼리 없음)", odd)

bad = []
for tbl, want in ((nolock, ["h", "path", "body"]), (locked, ["h", "path", "body", "prefs"])):
    for k, fn in sorted(tbl.items()):
        args = list(inspect.signature(fn).parameters)
        if getattr(fn, "__module__", "") != "http_post_prefs" or not fn.__name__.startswith("post_") or args != want:
            bad.append("%s → %s.%s%s" % (k, getattr(fn, "__module__", "?"), getattr(fn, "__name__", "?"), args))
T.chk(not bad, "처리 함수 = http_post_prefs.post_* · 인자 꼴(잠금 밖 h·path·body · 잠금 안 + prefs)", bad)
names = {fn.__name__ for fn in list(nolock.values()) + list(locked.values())}
T.chk(set(http_post_prefs.__all__) == names, "http_post_prefs.__all__ = 표가 부르는 처리 함수 전부(남는 함수 0)",
      sorted(set(http_post_prefs.__all__) ^ names))

SEC = os.path.join(T.HERE, "arch_baseline", "sec_routes.jsonl")
if os.path.isfile(SEC):
    dec = set()
    with open(SEC, encoding="utf-8") as f:
        for ln in f:
            r = json.loads(ln).get("r") or ""
            if r.startswith("POST ") and not r[5:].startswith(("/api/setup/", "/api/login", "/api/logout", "/api/auth/")):
                dec.add(r[5:])
    ops = {p for p in dec if p.startswith(pre)}
    rest = dec - ops
    got = set(nolock) | set(locked)
    T.chk(ops and rest == got, "표 경로 + 접두어 %d = 선언 POST − setup − 로그인 %d" % (len(ops), len(dec)),
          {"선언만": sorted(rest - got), "표만": sorted(got - rest)})
else:
    print("(sec_routes.jsonl 없음 — 선언 대조 건너뜀)")
T.finish()
