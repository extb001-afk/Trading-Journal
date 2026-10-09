#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler

os.environ["TJ_HEALTH"] = "0"
import common
import settings_store as ss

S = common.STATE_DIR


def ck(name, cond, extra=None):
    T.chk(bool(cond), name, extra)


for a, why in (("11111111111111111111111111111111", "시스템 프로그램"), ("So11111111111111111111111111111111111111112", "wSOL")):
    r = T.safe(ss.validate_address, a)
    ck(f"W11 {why} 주소 거부", isinstance(r, dict) and "지갑 주소가 아니에요" in r.get("_exc", ""), r)
import pricing
for m9, sym9 in pricing.STABLE_MINTS.items():
    r = T.safe(ss.validate_address, m9)
    ck(f"W11 솔라나 {sym9} 민트 거부(실제 민트 주소 — wl314 ⑥)", isinstance(r, dict) and "지갑 주소가 아니에요" in r.get("_exc", ""), r)
r = T.safe(ss.validate_address, "0x" + "ab" * 32)
ck("W11 한 건 입력 개인 키 = 경고 문구", isinstance(r, dict) and "개인 키" in r.get("_exc", ""), r)
ck("W11 정상 주소는 그대로", T.safe(ss.validate_address, "0x" + "ab" * 20)[0] == "evm"
   and T.safe(ss.validate_address, "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM")[0] == "sol")

with open(ss.SETTINGS_PATH, "w", encoding="utf-8") as f:
    f.write('{"telegram": {"bot": "x"}, ')
ss.update_settings(currency="USD")
bad = [n for n in os.listdir(S) if n.startswith("settings.json.bad.")]
ck("W12② 손상된 settings.json = 증거로 옮긴 뒤 새로 씀(종전 조용히 덮어씀)", bad and ss.read_settings().get("currency") == "USD", (bad, ss.read_settings()))
ck("W12② 증거 파일에 원문", bad and open(os.path.join(S, bad[0]), encoding="utf-8").read().startswith('{"telegram"'))
ss.update_settings(onboarded=True)
ck("W12② 정상 파일은 합쳐 씀", ss.read_settings().get("currency") == "USD" and ss.read_settings().get("onboarded") is True)

import ops_requests as O
recs = [{"ts": 1, "err": "합성", "rec": {"kind": "evm_tx", "chain": "eth", "txhash": f"0x{i:064x}"}} for i in range(3)]
with open(os.path.join(S, "poison.jsonl"), "w", encoding="utf-8") as f:
    for r9 in recs:
        f.write(json.dumps(r9) + "\n")
ents = O.poison_entries(limit=100)
ids = [e["id"] for e in ents]
ok1 = O.poison_request(ids=[ids[0]])
ok2 = O.poison_request(ids=[ids[1]])
req = json.load(open(os.path.join(S, O.POISON_REQ_NAME), encoding="utf-8"))
ck("W12③ 처리 전 두 요청 = 합침(종전 뒤 요청이 앞 요청을 덮음)", ok1[0] and ok2[0] and set(req["ids"]) == {ids[0], ids[1]}, req)
O.poison_request(all_=True)
O.poison_request(ids=[ids[2]])
req = json.load(open(os.path.join(S, O.POISON_REQ_NAME), encoding="utf-8"))
ck("W12③ 앞 요청이 '전부'면 전부 유지", req.get("all") is True, req)

import web


class H0(BaseHTTPRequestHandler):
    timeout = 5

    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()


class Srv(web.QuietHTTPServer):
    MAX_CONN = 8


srv = Srv(("127.0.0.1", 0), H0)
th = threading.Thread(target=srv.serve_forever, daemon=True)
th.start()
port = srv.server_address[1]
held = [socket.create_connection(("127.0.0.1", port)) for _ in range(8)]
time.sleep(0.3)
extra = socket.create_connection(("127.0.0.1", port))
extra.settimeout(3)
try:
    got = extra.recv(200)
except OSError as e:
    got = repr(e).encode()
ck("W3 상한 넘는 새 연결 = 503 바로", got.startswith(b"HTTP/1.1 503"), got[:60])
for s9 in held:
    s9.close()
extra.close()
time.sleep(0.5)
c2 = socket.create_connection(("127.0.0.1", port))
c2.settimeout(3)
c2.sendall(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
ck("W3 연결이 풀리면 다시 받음", c2.recv(100).startswith(b"HTTP/1.0 200"))
c2.close()
srv.shutdown()
srv.server_close()

sb = web.StateBuilder.__new__(web.StateBuilder)
cache = {}
for i in range(web.StateBuilder.CHART_CACHE_MAX + 10):
    sb._chart_cache_put(cache, ("k", i), {"i": i})
ck("W8 캐시 넣기 = 상한 지킴 · 최근 것 남음", len(cache) == web.StateBuilder.CHART_CACHE_MAX and ("k", web.StateBuilder.CHART_CACHE_MAX + 9) in cache, len(cache))
src = open(os.path.join(T.SRC, "web.py"), encoding="utf-8").read()
ck("W8 이른 반환 세 곳도 _chart_cache_put", src.count("self._chart_cache_put(cache, ck, out)") >= 3)

import alert_prefs
r9 = T.safe(alert_prefs.apply_post, {}, {"preset": ["rec"]})
ck("W9 알림 preset 배열 = 오류 문구(종전 TypeError 500)", isinstance(r9, tuple) and r9[0] is None and "preset" in str(r9[1]), r9)
import onboarding


class FakeH:
    headers = {"Host": "127.0.0.1:8023"}
    client_address = ("127.0.0.1", 1)

    def __init__(self, path):
        self.path = path
        self.sent = None

    def _send(self, code, body, *a, **k):
        self.sent = (code, body)


ck("(전제) 원장 없음", not os.path.exists(common.DB_PATH))
for p9 in ("/api/fut_receipt", "/api/receipt_list", "/api/outflow_candidates"):
    h9 = FakeH(p9)
    hit = T.safe(onboarding.handle_get, h9, p9)
    ck(f"W9 원장 없음 = {p9} 빈 응답(빌드 시도 없음)", hit is True and h9.sent and h9.sent[0] == 200 and h9.sent[1].get("empty") is True, (hit, h9.sent))
src_w = open(os.path.join(T.SRC, "web.py"), encoding="utf-8").read()
ck("W9 POST 본문 RecursionError = 400", "except (ValueError, RecursionError):" in src_w)
try:
    json.loads("[" * 100000)
    deep_ok = False
except RecursionError:
    deep_ok = True
except ValueError:
    deep_ok = True
ck("W9 (재현) 깊은 중첩은 RecursionError 를 낼 수 있음 — ValueError 만 잡으면 500", deep_ok)

ck("W10① override 키 = g + 숫자 1~12자", 'r"g\\d{1,12}"' in src_w and 'r"g\\d+"' not in src_w)
ck("W10② 계획 저장 = 0 < 손절 < 목표 검사", "손절선은 목표가보다 낮아야 해요" in src_w)

import ast
_tw = ast.parse(src_w)


def _sysexit_caught(fn):
    return any(isinstance(n, ast.ExceptHandler) and isinstance(n.type, ast.Tuple)
               and {getattr(e, "id", None) for e in n.type.elts} >= {"Exception", "SystemExit"} for n in ast.walk(fn))


_snap = [n for n in _tw.body if isinstance(n, ast.FunctionDef) and n.name == "snapshot_refresher"]
_spot = [m for c in _tw.body if isinstance(c, ast.ClassDef) and c.name == "Spot" for m in c.body if isinstance(m, ast.FunctionDef) and m.name == "loop"]
ck("W12① 스냅샷 갱신기·시세 루프 = SystemExit 도 잡음", len(_snap) == 1 and len(_spot) == 1 and _sysexit_caught(_snap[0]) and _sysexit_caught(_spot[0]),
   (len(_snap), len(_spot)))
T.finish()
