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
        f.write("TJ_TG_TOKEN=000000:fake-test-token\nTJ_TG_CHAT=%s\nTJ_TG_API=http://127.0.0.1:9/never\n" % chat)


set_env("12345")
import common
import alert_prefs as AP
import alert_bot as ab


def check(name, ok, detail=""):
    H.chk(bool(ok), name, None if ok else str(detail)[:400])


FQ = getattr(AP, "FAST_QUEUE", "alerts_fast.jsonl")
CLK = [1_900_000_000.0]
_real_time = time.time
MODE = {"v": "403", "ra": 5}
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
    CALLS.append(CLK[0])
    m = MODE["v"]
    if m == "ok":
        return _Ok()
    if m == "net":
        raise urllib.error.URLError("시험: 연결 거부")
    code = int(m)
    body = json.dumps({"ok": False, "error_code": code, "description": "test",
                       "parameters": {"retry_after": MODE["ra"]} if code == 429 else {}}).encode()
    raise urllib.error.HTTPError(getattr(req, "full_url", "x"), code, "test", {}, io.BytesIO(body))


_mock_open._tj_test_mock = True


def setup_urgent(n=1):
    for fn in ("alerts_web.jsonl", "pending_dm.jsonl", FQ, "tg_cursor.json", "alert_hold.json", "alert_stats.json"):
        try:
            os.remove(os.path.join(S, fn))
        except FileNotFoundError:
            pass
    open(os.path.join(S, "alerts_web.jsonl"), "w").close()
    with open(os.path.join(S, FQ), "w", encoding="utf-8") as f:
        for i in range(n):
            f.write(json.dumps({"ts": int(CLK[0]), "kind": "LIQ_NEAR", "cat": "liq", "text": "🔴 긴급 %d\n증거금을 넣으세요." % i}, ensure_ascii=False) + "\n")
    common.atomic_write_json(os.path.join(S, "ui_prefs.json"), {AP.PREF_KEY: AP.preset_doc("rec")})
    cursor = {"alerts_web.jsonl": 0, "pending_dm.jsonl": 0, FQ: 0}
    ab._URG.update(token="000000:fake-test-token", chat="12345", cursor=cursor, doc=AP.load(), conn=None,
                   st=ab.load_stats(), hold=ab.load_hold(), prefs_m=None)
    ab._URG["pos"].clear()
    ab._TG_WAIT_UNTIL[0] = 0.0
    bo = getattr(ab, "_URG_BACKOFF", None)
    if isinstance(bo, dict):
        bo.update(n=0, until=0.0, sig=None, perm=False)


def run_ticks(sec, step=0.5, hook=None):
    sent = 0
    end = CLK[0] + sec
    while CLK[0] < end:
        if hook:
            hook()
        sent += ab.urgent_pass() or 0
        CLK[0] += step
    return sent


ab.urllib.request.urlopen = _mock_open
time.time = lambda: CLK[0]
o_sleep = ab.time.sleep
ab.time.sleep = lambda x: None
try:
    setup_urgent()
    MODE["v"] = "403"
    CALLS.clear()
    run_ticks(300)
    check("U1 403(봇 차단) = 300초 동안 1번만 시도(종전: 0.5초마다 ≈600번)", len(CALLS) == 1, len(CALLS))
    set_env("67890")
    ab._URG.update(chat="67890")
    MODE["v"] = "ok"
    CALLS.clear()
    s5 = run_ticks(2)
    check("U5 영구 실패 대기 중 채팅 ID 를 바꾸면 다음 틱에 바로 다시(보냄)", len(CALLS) == 1 and s5 == 1, (len(CALLS), s5))
    set_env("12345")
    setup_urgent()
    MODE["v"] = "net"
    CALLS.clear()
    t0 = CLK[0]
    run_ticks(300)
    n300 = len(CALLS)
    run_ticks(3300)
    gaps = [b - a for a, b in zip(CALLS, CALLS[1:])]
    check("U2 네트워크 오류 = 지수 백오프(첫 300초 ≤ 12번 · 1시간 ≤ 25번 · 간격 늘어남 · 최대 300초+틱)",
          2 <= n300 <= 12 and len(CALLS) <= 25 and gaps and max(gaps) <= 300.5 and gaps[0] < gaps[-1] and CALLS[0] == t0,
          (n300, len(CALLS), gaps[:12]))
    MODE["v"] = "ok"
    CALLS.clear()
    s3 = run_ticks(301)
    bo = getattr(ab, "_URG_BACKOFF", {}) or {}
    check("U3 백오프 뒤 성공 = 보냄 · 백오프 초기화(n=0)", s3 == 1 and len(CALLS) == 1 and int(bo.get("n", -1)) == 0, (s3, len(CALLS), bo))
    setup_urgent()
    MODE.update(v="429", ra=5)
    CALLS.clear()
    t4 = CLK[0]
    run_ticks(1, hook=lambda: MODE.update(v="ok") if CLK[0] >= t4 + 0.5 else None)
    s4 = run_ticks(6)
    check("U4 429 = retry_after(5초) 뒤 바로 보냄(백오프 아님 · 대기 중 호출 없음)", s4 == 1 and len(CALLS) == 2 and 4.5 <= CALLS[1] - t4 <= 6.0,
          (s4, [round(c - t4, 1) for c in CALLS]))
    setup_urgent()
    MODE["v"] = "400"
    CALLS.clear()
    for _ in range(50):
        ab._urgent_hook()
        CLK[0] += 0.1
    check("U6 일반 경로 긴급 훅(run_source 발송 직전) = 영구 실패 대기 중 호출 없음", len(CALLS) == 1, len(CALLS))
    for fn9 in (FQ, "alerts_web.jsonl"):
        setup_urgent()
        if fn9 == "alerts_web.jsonl":
            os.replace(os.path.join(S, FQ), os.path.join(S, fn9))
        MODE["v"] = "403"
        CALLS.clear()
        ab.urgent_pass()
        cur9 = ab._URG["cursor"]
        for _ in range(20):
            CLK[0] += 20
            ab.run_source(fn9, "000000:fake-test-token", "12345", cur9, ab._URG["doc"], None, ab._URG["st"], ab._URG["hold"], {}, None)
        n7 = len(CALLS)
        CLK[0] += ab.URGENT_PERM_SEC
        MODE["v"] = "ok"
        ab.run_source(fn9, "000000:fake-test-token", "12345", cur9, ab._URG["doc"], None, ab._URG["st"], ab._URG["hold"], {}, None)
        check(f"U7 {fn9}: 403 대기 중 run_source(20판) 호출 0(종전 판마다 재시도) · 줄 보존(커서 그대로) → 대기 뒤 보내고 커서 전진",
              n7 == 1 and len(CALLS) == 2 and int(cur9.get(fn9, 0)) == os.path.getsize(os.path.join(S, fn9)), (n7, len(CALLS), cur9.get(fn9)))
finally:
    time.time = _real_time
    ab.time.sleep = o_sleep

READS = []


class _Big:
    def __init__(self, n):
        self.length = n

    def read(self, n=-1):
        READS.append(n)
        return b"{" + b" " * (max(0, n if n is not None and n >= 0 else self.length) - 2) + b"}"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Fp(io.BytesIO):
    def read(self, n=-1):
        READS.append(n)
        return super().read(n)


def _open_big(req, timeout=None):
    return _Big(50 << 20)


def _open_429big(req, timeout=None):
    raise urllib.error.HTTPError(getattr(req, "full_url", "x"), 429, "test", {}, _Fp(b'{"parameters":{"retry_after":7},"x":"' + b"y" * (5 << 20) + b'"}'))


_open_big._tj_test_mock = _open_429big._tj_test_mock = True
ab._TG_WAIT_UNTIL[0] = 0.0
ab.urllib.request.urlopen = _open_big
READS.clear()
r9 = ab.send_message("000000:fake-test-token", "12345", "시험")
check("R1 정상 응답이 큰 길이를 밝힘 = 읽기 전에 실패(종전 r.read() 끝까지)", r9[0] is False and READS == [], (r9, READS[:3]))
ab.urllib.request.urlopen = _open_429big
READS.clear()
r9 = ab.send_message("000000:fake-test-token", "12345", "시험")
check("R2 429 오류 본문 = 상한+1 까지만 읽고(종전 e.read() 끝까지) 대기는 기본 30초로", r9[0] is False and READS and max(READS) <= (64 << 10) + 1 and -1 not in READS,
      (r9, READS[:3]))
ab._TG_WAIT_UNTIL[0] = 0.0
ab.urllib.request.urlopen = _mock_open

CP = ab.CURSOR_PATH


class _Stop(Exception):
    pass


def boot(raw):
    for p in (CP, CP + ".bad"):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
    if raw is not None:
        with open(CP, "w", encoding="utf-8") as f:
            f.write(raw)
    seen = {}
    o_creds, o_beat, o_tick = ab._tg_creds, ab.unit_beat.start, ab.health_tick

    def creds():
        raise _Stop()
    ab._tg_creds = creds
    ab.unit_beat.start = lambda *a, **k: None
    ab.health_tick = lambda *a, **k: None
    o_load = getattr(ab, "_load_cursor", None)
    if o_load:
        def spy():
            c = o_load()
            seen["c"] = c
            return c
        ab._load_cursor = spy
    try:
        ab.main()
        return "returned", seen.get("c")
    except _Stop:
        return "ok", seen.get("c")
    except SystemExit as e:
        return "exit:" + str(e)[:80], None
    finally:
        ab._tg_creds, ab.unit_beat.start, ab.health_tick = o_creds, o_beat, o_tick
        if o_load:
            ab._load_cursor = o_load


r, c = boot("{broken")
check("C1 깨진 JSON = 죽지 않음(종전 SystemExit → 재시작 반복) · .bad 로 옮김 · {}", r == "ok" and c == {} and os.path.exists(CP + ".bad") and not os.path.exists(CP),
      (r, c, os.path.exists(CP + ".bad")))
r, c = boot("[]")
check("C2 객체가 아님([]) = 같음(종전 init_cursor 에서 죽음)", r == "ok" and c == {} and os.path.exists(CP + ".bad"), (r, c))
r, c = boot(json.dumps({"alerts_web.jsonl": "abc", "pending_dm.jsonl": 5, FQ: -3}))
check("C3 이상한 칸만 버림(정수 ≥ 0 만 남김 · 나머지는 init_cursor 가 다시 잡음)", r == "ok" and isinstance(c, dict) and c.get("pending_dm.jsonl") == 5
      and "alerts_web.jsonl" not in c and FQ not in c and not os.path.exists(CP + ".bad"), (r, c))
r, c = boot(json.dumps({"alerts_web.jsonl": 10, "pending_dm.jsonl": 0}))
check("C4 정상 파일 = 그대로", r == "ok" and c == {"alerts_web.jsonl": 10, "pending_dm.jsonl": 0}, (r, c))
H.finish()
