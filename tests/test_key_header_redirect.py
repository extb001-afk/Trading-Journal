#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import urllib.request  # noqa: E402

import bf_engine as B  # noqa: E402

chk = T.chk
R = urllib.request.Request

for h in ("TRON-PRO-API-KEY", "x-cg-demo-api-key", "x-cg-pro-api-key", "x-api-key", "X-API-Key", "Authorization", "OK-ACCESS-PASSPHRASE"):
    chk(B.has_key_header(R("https://a.example/x", headers={h: "k"})), f"K1 키 헤더 = {h}")
chk(not B.has_key_header(R("https://a.example/x", headers={"User-Agent": "tj-bot/1", "Accept": "application/json",
                                                         "Content-Type": "application/json"})), "K1 일반 헤더 = 키 아님")
chk(not B.has_key_header("https://a.example/x"), "K1 문자열 URL = 키 아님")

seen = []
_orig = B.sol_open
B.sol_open = lambda req, timeout, *a, **k: seen.append(k.get("no_redirect")) or (_ for _ in ()).throw(OSError("시험 끝"))
for hdr in ({"TRON-PRO-API-KEY": "k"}, {"Accept": "application/json"}):
    try:
        B._open(R("https://a.example/x", headers=hdr), 5)
    except OSError:
        pass
B.sol_open = _orig
chk(seen == [True, False], "K2 키 헤더 = 리다이렉트 막음 · 일반 = 종전", seen)

import ton_watch as TW  # noqa: E402
src = open(TW.__file__, encoding="utf-8").read()
chk("net_http.auth_urlopen if self.key" in src, "K3 TON 키 요청 = auth_urlopen")

T.finish()
