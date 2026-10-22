#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import os  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402

import pricing  # noqa: E402

chk = T.chk
real_time = time.time
OFF = [0.0]
pricing.time.time = lambda: real_time() + OFF[0]
pricing.time.sleep = lambda s: None
CALLS = []


def fake_gj(url, timeout=10.0):
    CALLS.append(url)
    now_ms = int(pricing.time.time() * 1000)
    if "binance.com/api/v3/klines" in url:
        if "symbol=DEADUSDT" in url:
            return []
        st = int(url.split("startTime=")[1].split("&")[0])
        return [[st, "2.5", "2.5", "2.5", "2.5", "1"]] if st > now_ms - 3600_000 else []
    if "bybit.com" in url:
        return {"retCode": 10001, "result": {}}
    raise urllib.error.HTTPError(url, 429, "x", None, None)


fake_gj._tj_test_mock = True
pricing._gj = fake_gj
px = pricing.PxCache(os.path.join(T.TMP, "px.json"))
q = pricing.PxFetchQueue(px)
base_ms = int(real_time() * 1000)
old_ms = base_ms - 400 * 86400_000


def build(sym, i):
    OFF[0] = i * 60.0
    px.nb_begin()
    px.candle_usd(sym, old_ms)
    v = px.candle_recent(sym, base_ms + i * 60_000)
    miss = px.nb_end()
    q.q |= set(miss)
    q.drain()
    return v


got = [1 if build("XYZ", i) else 0 for i in range(30)]
chk(sum(got) >= 29, "N1 30분 동안 현재가 있는 빌드 ≥ 29(첫 빌드만 대기)", "".join(map(str, got)))

order = []
px2 = pricing.PxCache(os.path.join(T.TMP, "px2.json"))
px2.candle_usd = lambda sym, m: order.append((sym, m))
q2 = pricing.PxFetchQueue(px2)
q2.q |= {("c", "AAA", 60_000), ("c", "AAA", 180_000), ("c", "AAA", 120_000), ("c", "BBB", 60_000)}
q2.drain()
chk([m for s, m in order if s == "AAA"] == [180_000, 120_000, 60_000], "N2 drain = 같은 심볼 최신 분 먼저", order)

OFF[0] = 0.0
del CALLS[:]
for i in range(30):
    OFF[0] = 3600.0 + i * 60.0
    px.nb_begin()
    px.candle_recent("DEAD", base_ms + 3600_000 + i * 60_000)
    q.q |= set(px.nb_end())
    q.drain()
n_dead = sum(1 for u in CALLS if "DEADUSDT" in u)
chk(1 <= n_dead <= 6, "N3 봉 없는 심볼 = 지수 쉼 그대로(30분에 바이낸스 조회 몇 번만)", n_dead)

px.nb_begin()
chk(px.candle_recent("USDT", base_ms) == 1.0, "N4 스테이블 = 1.0(종전)")
px.nb_end()

T.finish()
