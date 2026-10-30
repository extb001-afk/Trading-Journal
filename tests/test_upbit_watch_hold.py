#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402

json.dump({"chains": {}, "wallets": [], "backfill_months": 0.2}, open(os.path.join(T.TMP, "config.json"), "w"))
import config  # noqa: E402
import health  # noqa: E402
import paths  # noqa: E402
import statefile  # noqa: E402
import upbit_link  # noqa: E402

chk = T.chk
with open(paths.ENV_PATH, "w") as f:
    f.write("UPBIT_ACCESS=" + "a" * 20 + "\nUPBIT_SECRET=" + "s" * 20 + "\n")


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(t))


NOW0 = time.time()
WO = {"uuid": "hold-w-1", "side": "ask", "ord_type": "limit", "price": "3000", "state": "watch", "market": "KRW-TSTA",
      "created_at": iso(NOW0 - 10 * 86400), "volume": "5.0", "remaining_volume": "5.0", "executed_volume": "0.0", "trades_count": 0}


class FakeUp:

    def __init__(self):
        self.remaining_min, self._backoff_err = 999, None
        self.wait, self.watch = [], []

    def get(self, path, query=None):
        q = dict(query or {})
        if path == "/v1/orders/open":
            if q.get("state") == "watch":
                if self.watch is None:
                    raise urllib.error.HTTPError("https://api.upbit.com/v1/orders/open", 500, "synthetic", {}, None)
                return [dict(o) for o in self.watch]
            return [dict(o) for o in self.wait]
        if path in ("/v1/accounts", "/v1/deposits", "/v1/withdraws", "/v1/orders/closed"):
            return []
        raise AssertionError("모르는 요청 " + path)


class Writer:
    def append(self, rec):
        pass


def run(up):
    upbit_link.cycle(up, Writer(), 0.2)
    return (statefile.read_json(paths.state("upbit_orders_state.json"), {}), statefile.read_json(paths.state("upbit_sync.json"), {}))


HST = {}


def hlevel():
    c = config.load_config()
    now = time.time()
    if not HST:
        health.collect_sources(c, HST, now - 3600)
    obs = {"now": now, "sources": health.collect_sources(c, HST, now), "hb": health.read_heartbeats(c), "keys": health.collect_keys(c, now)}
    it = [i for i in health.evaluate(obs, dict(health.DEFAULTS, units=["tj-ex", "tj-core", "tj-web"]), ()) if isinstance(i, dict) and i.get("id") == "sync:ex:upbit"]
    return (it[0].get("level"), it[0].get("title"), it[0].get("detail")) if it else (None, None, None)


up = FakeUp()
up.watch = None
o, s = run(up)
chk("watch_hold" not in s and o.get("complete") is True and s.get("last_ok"), "H3 추적 중 예약 0건에서 예약 목록 실패 = watch_hold 없음 · complete(종전)", (o.get("complete"), s))
up.watch = [WO]
o, s = run(up)
chk((o.get("open_track") or {}).get(WO["uuid"], {}).get("w") == 1 and o.get("complete") is True and "watch_hold" not in s, "H1 준비: 예약 1건 추적(칸 w) · 도장")
up.watch = None
o, s1 = run(up)
time.sleep(1.1)
o, s2 = run(up)
wh1, wh2 = s1.get("watch_hold") or {}, s2.get("watch_hold") or {}
chk(o.get("complete") is False and wh1.get("since") and wh2.get("since") == wh1["since"] and "예약" in str(wh2.get("msg"))
    and s2.get("last_ok") and not s2.get("last_err"),
    "H1 예약 목록 연속 실패 = complete 보류 · watch_hold(since = 첫 실패 그대로 · 사유) · 동기화 성공 기록은 계속", (s1, s2))
lvl, ttl, det = hlevel()
chk(lvl == "warn" and "부분 동기화" in str(ttl) and "예약" in str(det) and "로그 트랙" not in str(det),
    "H1 헬스 = '업비트 부분 동기화'(warn) · 상세에 예약 목록 사유 · 부분 동기화 기간", (lvl, ttl, det))
up.watch = [WO]
o, s = run(up)
lvl, ttl, det = hlevel()
chk("watch_hold" not in s and o.get("complete") is True and lvl == "ok" and "부분" not in str(ttl),
    "H2 예약 목록 성공 = watch_hold 지움 · complete · 헬스 '업비트 동기화'(ok)", (s, lvl, ttl))
up.wait, up.watch = [dict(WO, state="wait")], []
o, s = run(up)
ent = (o.get("open_track") or {}).get(WO["uuid"], {})
chk(ent and "w" not in ent and not ent.get("closed") and o.get("complete") is True, "R1 발동해 미체결 목록에 보임(같은 uuid) = 칸 w 지움 · 계속 추적", ent)
up.watch = None
o, s = run(up)
chk(o.get("complete") is True and "watch_hold" not in s, "R1 그 뒤 예약 목록 실패 = 도장 보류 없음(추적 예약 0)", (o.get("complete"), s))
T.finish()
