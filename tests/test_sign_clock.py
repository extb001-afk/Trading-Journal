#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

import paths  # noqa: E402
import exf_net as N  # noqa: E402

chk = T.chk
N._CLOCK_ON[0] = False
p = os.path.join(paths.STATE_DIR, N.CLOCK_PATH_NAME)
os.makedirs(paths.STATE_DIR, exist_ok=True)

N._CLOCK_FILE["at"] = 0
t0 = int(time.time() * 1000)
v = N.sign_ms("binance")
chk(abs(v - t0) < 2000, "C1 기록 없음 = 로컬 시각", (v, t0))

json.dump({"v": 1, "ex": {"binance": {"off": -15000, "at": time.time() - 60}, "bybit": {"off": 9000, "at": time.time() - 7 * 3600}}}, open(p, "w"))
N._CLOCK_FILE["at"] = 0
t0 = int(time.time() * 1000)
chk(abs(N.sign_ms("binance") - (t0 - 15000)) < 2000, "C2 바이낸스 = 로컬 − 15초(잰 차이)")
chk(abs(N.sign_ms("bybit") - t0) < 2000, "C2 7시간 지난 값 = 안 씀")
chk(abs(N.sign_ms("okx") - t0) < 2000, "C2 기록 없는 거래소 = 로컬")

open(p, "w").write("{not json")
N._CLOCK_FILE["at"] = 0
chk(abs(N.sign_ms("binance") - int(time.time() * 1000)) < 2000, "C3 손상 파일 = 로컬 시각")

chk(N.iso_ms(1_700_000_000_123) == "2023-11-14T22:13:20.123Z", "C4 OKX ISO 밀리초", N.iso_ms(1_700_000_000_123))

N._CLOCK_ON[0] = True
N._CLOCK["binance"] = {"off": 4000, "at": time.time()}
chk(abs(N.sign_ms("binance") - (int(time.time() * 1000) + 4000)) < 2000, "C5 tj-exf = 메모리 보정값")
N._CLOCK["bybit"] = {"off": 4000, "at": time.time() - 2 * 3600}
_sync = N._clock_sync
N._clock_sync = lambda *a, **k: (_ for _ in ()).throw(AssertionError("재측정 호출됨"))
v6 = T.safe(N.sign_ms, "bybit")
N._CLOCK["okx"] = {"off": 4000, "at": time.time() - 7 * 3600}
v7 = T.safe(N.sign_ms, "okx")
N._clock_sync = _sync
chk(isinstance(v6, int) and abs(v6 - (int(time.time() * 1000) + 4000)) < 2000, "C6 2시간 지난 메모리 값 = 재측정 없이 사용", v6)
chk(isinstance(v7, int) and abs(v7 - int(time.time() * 1000)) < 2000, "C6 6시간 넘은 값 = 로컬(재측정 없음)", v7)
N._CLOCK_ON[0] = False
T.finish()
