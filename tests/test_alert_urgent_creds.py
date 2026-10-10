#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as H

import io
import json
import os
import time
import urllib.error

os.environ["TJ_HEALTH"] = "0"
os.environ["TJ_TG_API"] = "http://127.0.0.1:9/never"
S = os.path.join(H.TMP, "state")
with open(os.path.join(H.TMP, "config.json"), "w") as f:
    json.dump({}, f)
ENV = os.path.join(H.TMP, ".env")


def set_env(chat):
    with open(ENV, "w") as f:
        if chat is None:
            f.write("TJ_TG_API=http://127.0.0.1:9/never\n")
        else:
            f.write("TJ_TG_TOKEN=000000:fake-test-token\nTJ_TG_CHAT=%s\nTJ_TG_API=http://127.0.0.1:9/never\n" % chat)


set_env("12345")
import common
import alert_prefs as AP
import alert_bot as ab

FQ = getattr(AP, "FAST_QUEUE", "alerts_fast.jsonl")
CLK = [1_900_000_000.0]
_real_time = time.time
MODE = {"v": "400"}
CALLS = []


class _Ok:
    def __init__(self):
        self._b = json.dumps({"ok": True, "result": {"message_id": 7}}).encode()
        self.length = len(self._b)

    def read(self, n=-1):
        b, self._b = (self._b, b"") if n is None or n < 0 else (self._b[:n], self._b[n:])
        return b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _mock_open(req, timeout=None):
    body = getattr(req, "data", b"") or b""
    CALLS.append((CLK[0], b"99999" in body, b"67890" in body))
    if MODE["v"] == "ok":
        return _Ok()
    code = int(MODE["v"])
    raise urllib.error.HTTPError(getattr(req, "full_url", "x"), code, "test", {},
                                 io.BytesIO(json.dumps({"ok": False, "error_code": code, "description": "test"}).encode()))


_mock_open._tj_test_mock = True


def setup_urgent():
    for fn in ("alerts_web.jsonl", "pending_dm.jsonl", FQ, "tg_cursor.json", "alert_hold.json", "alert_stats.json"):
        try:
            os.remove(os.path.join(S, fn))
        except FileNotFoundError:
            pass
    open(os.path.join(S, "alerts_web.jsonl"), "w").close()
    with open(os.path.join(S, FQ), "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": int(CLK[0]), "kind": "LIQ_NEAR", "cat": "liq", "text": "긴급 0\n증거금을 넣으세요."}, ensure_ascii=False) + "\n")
    common.atomic_write_json(os.path.join(S, "ui_prefs.json"), {AP.PREF_KEY: AP.preset_doc("rec")})
    cursor = {"alerts_web.jsonl": 0, "pending_dm.jsonl": 0, FQ: 0}
    ab._URG.update(token="000000:fake-test-token", chat="12345", cursor=cursor, doc=AP.load(), conn=None,
                   st=ab.load_stats(), hold=ab.load_hold(), prefs_m=None)
    ab._URG["pos"].clear()
    ab._TG_WAIT_UNTIL[0] = 0.0
    ab._URG_BACKOFF.update(n=0, until=0.0, sig=None, perm=False)


def run_ticks(sec, step=0.5):
    sent = 0
    end = CLK[0] + sec
    while CLK[0] < end:
        sent += ab.urgent_pass() or 0
        CLK[0] += step
    return sent


ab.urllib.request.urlopen = _mock_open
time.time = lambda: CLK[0]
o_sleep = ab.time.sleep
ab.time.sleep = lambda x: None
try:
    setup_urgent()
    set_env("99999")
    MODE["v"] = "400"
    CALLS.clear()
    run_ticks(19)
    H.chk(len(CALLS) == 1 and CALLS[0][1], "A1 .env 가 다른 잘못된 채팅 ID(판은 옛 값) · 400 = 19초 동안 시도 1번(종전: 매 틱 ≈38번)",
          [len(CALLS), CALLS[:3]])
    set_env("67890")
    MODE["v"] = "ok"
    CALLS.clear()
    s2 = run_ticks(2)
    H.chk(s2 == 1 and len(CALLS) == 1 and CALLS[0][2], "A2 대기 중 .env 를 다른(맞는) 값으로 바꾸면 다음 틱에 바로 보냄(판은 아직 옛 값)", [s2, CALLS])
    setup_urgent()
    set_env("99999")
    MODE["v"] = "400"
    CALLS.clear()
    run_ticks(1)
    set_env(None)
    n0 = len(CALLS)
    run_ticks(30)
    H.chk(n0 == 1 and len(CALLS) == 1, "A3 대기 중 .env 자격 없어짐(연결 해제) = 더 보내지 않음", [n0, len(CALLS)])
finally:
    time.time = _real_time
    ab.time.sleep = o_sleep
    set_env("12345")
H.finish()
