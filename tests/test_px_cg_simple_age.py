#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import bf_engine  # noqa: E402
import candles  # noqa: E402
import pricing  # noqa: E402
import web  # noqa: E402

chk = T.chk
CG = {"n": 0, "ok": True, "px": 10.0}


def fake_get(url, **kw):
    CG["n"] += 1
    if not CG["ok"]:
        raise bf_engine.NetError("429", "http429", host="api.coingecko.com")
    return {"some-coin": {"usd": CG["px"]}}


candles._get = fake_get
candles._keyed = lambda url, lane, allow, valid, dl: ("skip", "nokey")
t0 = 1_800_000_000.0
chk(candles.cg_simple_usd(["some-coin"], now=t0) == {"some-coin": 10.0}, "A1 받은 직후 = 값")
CG["ok"] = False
f = []
r = candles.cg_simple_usd(["some-coin"], now=t0 + 900, fail=f)
chk(r == {"some-coin": 10.0} and f == ["coingecko"], "A2 15분 뒤 실패 = 직전 값(상한 안) · fail 표시", (r, f))
f = []
r = candles.cg_simple_usd(["some-coin"], now=t0 + 26 * 3600, fail=f)
chk(r == {} and f == ["coingecko"], "A3 26시간 실패 = 값 없음(묵은 값을 '방금 시세'로 안 돌려줌)", (r, f))
r = candles.cg_simple_usd(["some-coin"], now=t0 + 26 * 3600, keyed=True, key_only=True)
chk(r == {}, "A4 key_only 경로도 같은 상한", r)

candles.holder_cg_id = lambda holder, base, now=None, fetch=True: "some-coin"
candles.same_coin = lambda *a, **k: (None, "")
pricing.ex_spot_usd = lambda ex, rate=0: {}
sp = web.Spot()
sp.rate = 1400.0
out = sp._upbit_alt_global(["ABC"], {"BTC": 1.0}, t0 + 26 * 3600)
chk("ABC" not in out, "A5 업비트 비원화 코인: 코인게코 26시간 실패 = 이번 tick 값 없음(묵은 값 '방금'으로 안 찍음)", out)
CG["ok"], CG["px"] = True, 4.0
r = candles.cg_simple_usd(["some-coin"], now=t0 + 27 * 3600)
chk(r == {"some-coin": 4.0}, "A6 다시 성공 = 새 값", r)

T.finish()
