#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402

import statefile  # noqa: E402
import bf_engine  # noqa: E402
import health  # noqa: E402
import nodekeys as NK  # noqa: E402
import onboarding  # noqa: E402
import settings_store as ss  # noqa: E402


def check(n, c, d=""):
    T.chk(bool(c), n, None if c else str(d)[:900])


KEY = "TESTalchKey00000000000001"
KEY2 = "TESTalchKey00000000000002"
URL = f"https://eth-mainnet.g.alchemy.com/v2/{KEY}"
URLB = f"https://base-mainnet.g.alchemy.com/v2/{KEY}"
PUB = "https://worldchain-mainnet.g.alchemy.com/public"
MONTH = ('{"jsonrpc":"2.0","id":1,"error":{"code":429,"message":"Monthly capacity limit exceeded. Visit https://dashboard.alchemy.com/settings/billing '
         'to upgrade your scaling policy for continued service."}}')
PERSEC = ('{"jsonrpc":"2.0","id":1,"error":{"code":429,"message":"Your app has exceeded its compute units per second capacity. If you have retries enabled, '
          'you can safely ignore this message."}}')


class NE:
    def __init__(self, code=None, msg="", body=""):
        self.code, self.msg, self.body = code, msg, body

    def __str__(self):
        return self.msg


ss.write_env({NK.ENV_ALCHEMY: KEY})


def rec():
    return statefile.read_json(NK._alch_path(), None)


def wipe():
    try:
        os.remove(NK._alch_path())
    except FileNotFoundError:
        pass


print("[A1] 거절 분류")
W = NK._alch_why
check("A1a 429 + 월 용량 문구 = month", W(err=NE(429, "HTTP Error 429: Too Many Requests"), text=MONTH) == "month")
check("A1b 200 JSON-RPC error 월 용량 문구 = month", W(body={"jsonrpc": "2.0", "id": 1, "error": {"code": -32600, "message": "Monthly capacity limit exceeded."}}) == "month")
check("A1c 배치 응답 안 하나라도 월 용량 = month", W(body=[{"id": 1, "result": "0x1"}, {"id": 2, "error": {"code": 429, "message": "Monthly capacity limit exceeded"}}]) == "month")
check("A1d 402 = pay · 401·403 = key", W(err=NE(402)) == "pay" and W(err=NE(401)) == "key" and W(err=NE(403)) == "key")
check("A1e 초당 한도 429 = 셈 안 함", W(err=NE(429, "HTTP Error 429"), text=PERSEC) is None)
check("A1f 문구 없는 429 · 5xx · 시간 초과 · 실행 오류(200 error) = 셈 안 함",
      W(err=NE(429, "HTTP Error 429: Too Many Requests")) is None and W(err=NE(503, "HTTP Error 503")) is None and W(err=NE(None, "timeout: timed out")) is None
      and W(body={"id": 1, "error": {"code": 3, "message": "execution reverted"}}) is None)
check("A1g 성공 본문 = None", W(body={"jsonrpc": "2.0", "id": 1, "result": "0x10"}) is None)
check("A1h 키 주소만 셈 — /v2/<키> = 해시 · /public · 다른 호스트 · 형식 이상 = None",
      NK.alch_url_kh(URL) and NK.alch_url_kh(URL) == NK.alch_url_kh(URLB) and NK.alch_url_kh(PUB) is None
      and NK.alch_url_kh(f"https://rpc.ankr.com/v2/{KEY}") is None and NK.alch_url_kh("https://eth-mainnet.g.alchemy.com/v2/") is None)
check("A1i 해시 = 12자 · 키 값과 다름", len(NK.alch_url_kh(URL)) == 12 and KEY not in NK.alch_url_kh(URL))

print("[A2] 계수 · 회복")
wipe()
NK.alch_note(URL, err=NE(429, "HTTP Error 429"), text=MONTH)
r = rec()
check("A2a 한 번 = 계수만(off 아님) · 화면 없음", r and r.get("n") == 1 and not r.get("off") and NK.alch_rejected() is None, r)
NK.alch_note(URL, err=NE(429, "HTTP Error 429"), text=MONTH)
check("A2b 두 번이어도 첫 거절에서 60초 안 = off 아님", not (rec() or {}).get("off"), rec())
d = rec()
d["first"] = int(time.time()) - NK.ALCH_REJECT_SEC - 5
statefile.atomic_write_json(NK._alch_path(), d)
NK.alch_note(URL, err=NE(429, "HTTP Error 429"), text=MONTH)
r = rec()
rj = NK.alch_rejected()
check("A2c N번 + 60초 = off · 화면 {why month · n 3}", r.get("off") and rj and rj["why"] == "month" and rj["n"] == 3 and rj["code"] == 429, (r, rj))
raw = open(NK._alch_path(), encoding="utf-8").read()
check("A2d 표식 파일에 키 값 없음", KEY not in raw and "alchemy.com" not in raw, raw)
NK.alch_note(PUB, err=NE(401))
NK.alch_note(URL, err=NE(429, "HTTP Error 429"), text=PERSEC)
NK.alch_note(URL, err=NE(None, "timeout: timed out"))
check("A2e 공개 주소 거절 · 초당 한도 · 시간 초과 = 표식 그대로(n 3)", (rec() or {}).get("n") == 3, rec())
NK.alch_note(URL, body={"jsonrpc": "2.0", "id": 1, "result": "0x1"})
check("A2f 같은 키 성공 1번 = 지움", rec() is None and NK.alch_rejected() is None, rec())
NK.alch_note(URL, body={"jsonrpc": "2.0", "id": 1, "result": "0x1"})
check("A2g 표식 없을 때 성공 = 파일 안 만듦", not os.path.exists(NK._alch_path()))

print("[A3] 실제 요청 길(bf_engine.http_request)")
SCRIPT = {}
HITS = []


class _Resp:
    def __init__(self, obj):
        self._b = json.dumps(obj).encode()
        self.headers = {}
        self.length = len(self._b)

    def read(self, n=-1):
        b, self._b = self._b, b""
        return b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_open(req, timeout):
    h = req.host.split(":")[0].lower() if hasattr(req, "host") else ""
    HITS.append(h)
    act = SCRIPT.get(h, "ok")
    if isinstance(act, tuple) and act[0] == "http":
        raise urllib.error.HTTPError(req.full_url, act[1], "x", {}, io.BytesIO(act[2].encode()))
    return _Resp({"jsonrpc": "2.0", "id": 1, "result": "0x10"})


bf_engine._open = fake_open


def fresh_gates():
    with bf_engine._GATES_LOCK:
        bf_engine._GATES.clear()


def call(url):
    fresh_gates()
    try:
        bf_engine.rpc_call(url, "eth_blockNumber", [], retries=1, timeout=5)
        return "ok"
    except Exception as e:   # noqa: BLE001
        return getattr(e, "kind", type(e).__name__)


H = "eth-mainnet.g.alchemy.com"
wipe()
SCRIPT[H] = ("http", 429, MONTH)
k1 = call(URL)
check("A3a 429 월 용량 = 요청 결과는 종전(실패 http429) · 계수 1", k1 == "http429" and (rec() or {}).get("n") == 1 and (rec() or {}).get("why") == "month", (k1, rec(), HITS[-3:]))
SCRIPT[H] = ("http", 402, '{"error":"payment required"}')
k2 = call(URL)
check("A3b 402 = 계수 2 · why pay", (rec() or {}).get("n") == 2 and rec().get("why") == "pay" and rec().get("code") == 402, (k2, rec()))
SCRIPT[H] = ("http", 401, '{"error":"Must be authenticated!"}')
call(URL)
check("A3c 401 = 계수 3 · why key", (rec() or {}).get("n") == 3 and rec().get("why") == "key", rec())
SCRIPT[H] = ("http", 429, PERSEC)
call(URL)
check("A3d 초당 한도 429 = 계수 그대로", (rec() or {}).get("n") == 3, rec())
SCRIPT["worldchain-mainnet.g.alchemy.com"] = ("http", 401, "{}")
call(PUB)
check("A3e 무키 공개 주소 401 = 계수 그대로", (rec() or {}).get("n") == 3, rec())
SCRIPT[H] = "ok"
k3 = call(URL)
check("A3f 200 성공 = 지움", k3 == "ok" and rec() is None, (k3, rec()))

print("[A4] 키 바꿈 · 저장·삭제")
wipe()
off = {"v": 1, "kh": NK.alch_url_kh(URL), "first": int(time.time()) - 999, "n": 5, "last": int(time.time()), "why": "month", "code": 429, "off": True, "off_at": int(time.time()) - 900}
statefile.atomic_write_json(NK._alch_path(), off)
check("A4a 지금 키의 off 표식 = 화면에 보임", NK.alch_rejected() is not None)
ss.write_env({NK.ENV_ALCHEMY: KEY2})
check("A4b 키를 바꾸면 옛 표식 안 보임", NK.alch_rejected() is None)
ss.write_env({NK.ENV_ALCHEMY: KEY})
check("A4c 다른 키(KEY2) 성공은 KEY 표식을 안 지움", (NK.alch_note(f"https://eth-mainnet.g.alchemy.com/v2/{KEY2}", body={"result": "0x1"}) or True) and rec() is not None)
check("A4d alch_reject_clear = 지움 · off 였으면 True", NK.alch_reject_clear() is True and rec() is None)
statefile.atomic_write_json(NK._alch_path(), off)
check("A4e onboarding._alch_clear(키 삭제·저장 확인 통과 때 부름) = 지움", onboarding._alch_clear() is True and rec() is None)
src_on = open(os.path.join(T.SRC, "onboarding.py"), encoding="utf-8").read()
check("A4f 저장 확인 통과·키 삭제 자리에서 _alch_clear 호출", src_on.count("_alch_clear()") >= 2 and 'g == "alchemy" and pr9 == "ok"' in src_on)

print("[A6] 코덱스 rfalch 회귀")
wipe()
statefile.atomic_write_json(NK._alch_path(), off)
for b9 in ({"jsonrpc": "2.0", "id": 1, "error": {"code": 3, "message": "execution reverted"}},
           {"jsonrpc": "2.0", "id": 1, "error": {"code": 429, "message": "Your app has exceeded its compute units per second capacity."}},
           [{"id": 1, "result": "0x1"}, {"id": 2, "error": {"code": -32000, "message": "header not found"}}]):
    NK.alch_note(URL, body=b9)
check("A6a 200 + 월 한도 밖 error(실행 오류·초당 한도·배치 안 하나) = 표식 그대로(거짓 복구 없음)", NK.alch_rejected() is not None and rec().get("n") == 5, rec())
wipe()
NK.alch_note(URL, err=NE(429, "HTTP Error 429"), text=MONTH)
NK.alch_note(URL, body={"jsonrpc": "2.0", "id": 1, "error": {"code": 3, "message": "execution reverted"}})
check("A6b 계수 중 200 실행 오류 = 계수 그대로(초기화 안 함)", (rec() or {}).get("n") == 1, rec())
wipe()
statefile.atomic_write_json(NK._alch_path(), off)
U2 = f"https://eth-mainnet.g.alchemy.com/v2/{KEY2}"
NK.alch_note(U2, err=NE(401, "HTTP Error 401"))
NK.alch_note(U2, err=NE(402, "HTTP Error 402"))
check("A6c 저장 시험 중 후보 키(지금 키 아님) 401·402 = 지금 키 표식 그대로", NK.alch_rejected() is not None and rec().get("kh") == NK.alch_url_kh(URL) and rec().get("n") == 5, rec())
wipe()
NK.alch_note(U2, err=NE(401, "HTTP Error 401"))
check("A6d 지금 키 아닌 응답의 거절 = 표식 안 만듦", rec() is None, rec())
check("A6e 503 + 월 한도 문구 = 일시 · 코드 없는 예외 문구 = 일시 · 429 + 문구 = month",
      W(err=NE(503, "HTTP Error 503"), text=MONTH) is None and W(err=NE(None, "conn: Monthly capacity limit exceeded")) is None
      and W(err=NE(500, "HTTP Error 500 (Monthly capacity limit exceeded)")) is None and W(err=NE(429, "HTTP Error 429"), text=MONTH) == "month")
NK.alch_note(URL, err=NE(503, "HTTP Error 503"), text=MONTH)
check("A6f 503 월 문구 = 계수 안 함", rec() is None, rec())
SCRIPT[H] = ("http", 503, MONTH)
call(URL)
check("A6g 실제 요청 길 503 + 월 문구 = 계수 안 함", rec() is None, rec())
SCRIPT[H] = "ok"
wipe()

print("[A7] 코덱스 rfalch2 회귀")
wipe()
new_off = dict(off, kh=NK.alch_url_kh(U2))
_env0 = NK._env
calls9 = []


def env_switch():
    calls9.append(1)
    return {NK.ENV_ALCHEMY: KEY if len(calls9) == 1 else KEY2}


statefile.atomic_write_json(NK._alch_path(), new_off)
NK._env = env_switch
NK.alch_note(URL, err=NE(401, "HTTP Error 401"))
NK._env = _env0
r9 = rec()
check("A7a 옛 키 늦은 401 = 새 키 표식 그대로(덮어쓰지 않음)", r9 and r9.get("kh") == NK.alch_url_kh(U2) and r9.get("n") == 5 and r9.get("off"), r9)
calls9.clear()
statefile.atomic_write_json(NK._alch_path(), dict(off))
NK._env = env_switch
NK.alch_note(URL, body={"jsonrpc": "2.0", "id": 1, "result": "0x1"})
NK._env = _env0
check("A7b 옛 키 늦은 성공(잠금 안에선 키가 바뀜) = 표식 안 지움", rec() is not None and rec().get("kh") == NK.alch_url_kh(URL), rec())
wipe()

print("[A5] 상태 패널 · 텔레그램")
UNITS = ["tj-core", "tj-web", "tj-evm"]
HS = health.settings({"health": {"units": UNITS}})
T0 = 1792044000.0


def obs_of(now, rej):
    return {"now": now, "pm2": {u: {"status": "online", "restarts": 0, "pid": 1} for u in UNITS}, "bal_mem": {}, "prev_inc": {}, "sources": [],
            "keys": {"alchemy": True, "alchemyRej": rej}}


REJ = {"since": int(T0) - 300, "first": int(T0) - 400, "n": 4, "why": "month", "code": 429, "last": int(T0) - 10}
st = {"digest_date": "2026-10-15"}
sent = []


def tick(now, rej):
    cs = health.evaluate(obs_of(now, rej), HS, open_ids={k: v.get("unit") for k, v in (st.get("incidents") or {}).items()})
    ev = health.step(st, cs, now, HS)
    health.plan(st, ev, now, HS, True)
    for o in st.get("outbox") or []:
        if "Alchemy" in str(o.get("text")) and id(o) not in [id(x) for x in sent]:
            sent.append(o)
    return cs


cs0 = tick(T0 - 600, None)
check("A5a 거절 없음 = 칸 없음", not [c for c in cs0 if c["id"] == "key:alchemy_rej"])
cs = tick(T0, REJ)
c1 = [c for c in cs if c["id"] == "key:alchemy_rej"]
check("A5b 거절 = 주의 'Alchemy 월 한도 초과' · tg_force · 리마인드 없음", c1 and c1[0]["level"] == "warn" and c1[0]["title"] == "Alchemy 월 한도 초과"
      and c1[0].get("tg_force") and c1[0]["remind"] is False, c1)
check("A5c 상세·할 일에 키 값 없음 · 할 일 = 대시보드 사용량·요금제·다른 키", c1 and KEY not in json.dumps(c1, ensure_ascii=False)
      and "dashboard.alchemy.com" in c1[0]["action"] and "429" in c1[0]["detail"], c1)
for k in range(1, 40):
    tick(T0 + 60 * k, REJ)
msgs = [o["text"] for o in sent]
check("A5d 텔레그램 = 40분 동안 1통(📋 · 저절로 안 풀릴 수 있어요)", len(msgs) == 1 and msgs[0].startswith("📋") and "저절로 안 풀릴 수 있어요" in msgs[0], msgs)
check("A5e 텔레그램 문장에 키 값 없음", all(KEY not in m for m in msgs))
for k in range(40, 200):
    tick(T0 + 60 * k, REJ)
check("A5f 3시간 넘게 이어져도 리마인드 없음", len(sent) == 1, [o["text"] for o in sent])
for k in range(200, 230):
    tick(T0 + 60 * k, None)
msgs = [o["text"] for o in sent]
check("A5g 풀리면 복구 1통(✅) · 사건 닫힘", len(msgs) == 2 and msgs[1].startswith("✅") and "key:alchemy_rej" not in (st.get("incidents") or {}), msgs)
cs9 = tick(T0 + 60 * 240, None)
check("A5h 닫힌 뒤 = 칸 다시 없음", not [c for c in cs9 if c["id"] == "key:alchemy_rej"])
rk = dict(REJ, why="key", code=401)
cs = health.evaluate(obs_of(T0, rk), HS, open_ids={})
c2 = [c for c in cs if c["id"] == "key:alchemy_rej"]
check("A5i 키 거부 = 'Alchemy 키 거절' · 할 일 = 설정에서 키 확인", c2 and c2[0]["title"] == "Alchemy 키 거절" and "설정" in c2[0]["action"], c2)
cs = health.evaluate(dict(obs_of(T0, REJ), keys={"alchemy": False, "alchemyRej": REJ}), HS, open_ids={})
check("A5j 키 없음 = 칸 없음(지운 키의 남은 표식)", not [c for c in cs if c["id"] == "key:alchemy_rej"])
import chk_collect  # noqa: E402
statefile.atomic_write_json(NK._alch_path(), off)
kk = chk_collect.collect_keys({"wallets": []})
check("A5k collect_keys = alchemyRej {why·n} (값·지문 없음)", isinstance(kk.get("alchemyRej"), dict) and kk["alchemyRej"]["why"] == "month"
      and "kh" not in kk["alchemyRej"] and KEY not in json.dumps(kk), kk)
wipe()
NIGHT = 1792004400.0
stn = {"digest_date": "2026-10-15", "incidents": {}}
inn = {"id": "key:alchemy_rej#1", "check": "key:alchemy_rej", "unit": "tj-evm", "title": "Alchemy 월 한도 초과", "detail": "d", "level": "warn", "peak": "warn",
       "notify": True, "remind": False, "since": NIGHT - 3600, "opened": NIGHT - 3600, "kind": "key", "tg_force": True}
stn["incidents"]["key:alchemy_rej"] = inn
health.plan(stn, [("open", inn)], NIGHT, HS, True)
obn = stn.get("outbox") or []
check("A7c 조용한 시간 Alchemy 안내 혼자 = 끝난 뒤(not_before = 조용한 시간 끝)", len(obn) == 1 and obn[0].get("not_before") == health._quiet_until(NIGHT) and obn[0]["not_before"], obn)
T.finish()
