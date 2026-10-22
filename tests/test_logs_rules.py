#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import socketserver  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
import urllib.parse  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

H64 = "ab12cd34" * 8
PK64 = "4b8f2d6a0e3c5a7b9d1f" * 3 + "2e6a"
ADDR = "1f" * 20
BOT_SEC = "AAHkTxRvBnWqZpMlYsJdGfHc8Ue2"
BOT_BARE = "7712345678:AAGqkzvwpJdLmNbXcVfRtYhUoPgWsEaZx3"
BEARER = "tYp8Ws2Df4Gh6Jk8Lz0Xc2Vb4Nm6Qw"
BASIC = "dXNlcjpwYXNzd29yZDEyMw=="
PATHK = "Kd3Fh5Jl7Zn9Xb1Cv3Mq5Wr7Ey9Tu"
INFURA = "0123456789abcdef0123456789abcdef"
RPCK = "gF4hJ6kL8zX0cV2bN4mQ6wE8rT"
AUTHV = "Qm7Rt2Yp9Wk4Ls8Xz3Nv6Bc1"
CANARY = {
    "봇 토큰 URL": ("발송 실패 https://api.telegram.org/bot8823456789:%s/sendMessage" % BOT_SEC, BOT_SEC),
    "맨 봇 토큰": ("토큰 %s 거부" % BOT_BARE, BOT_BARE.split(":")[1]),
    "Authorization Bearer": ("헤더 Authorization: Bearer %s" % BEARER, BEARER),
    "Authorization 맨 값": ('{"authorization": "%s"}' % AUTHV, AUTHV),
    "Bearer 단독": ("401 Bearer %s 만료" % BEARER, BEARER),
    "Basic": ("헤더 Basic %s 거부" % BASIC, BASIC.rstrip("=")),
    "경로형 키 /v2/": ("RPC 실패 https://base-mainnet.g.alchemy.com/v2/%s" % PATHK, PATHK),
    "infura /v3/<키>": ("연결 실패 https://mainnet.infura.io/v3/%s (시간 초과)" % INFURA, INFURA),
    "경로형 키 /rpc/": ("노드 오류 https://bsc-node.example.invalid/rpc/%s" % RPCK, RPCK),
    "secret=0x64": ("설정 secret=0x%s 읽음" % PK64, PK64),
    "private_key: 0x64": ("private_key: 0x%s" % PK64, PK64),
    "개인키 0x64": ("개인키 0x%s 확인" % PK64, PK64),
    "키 0x64": ("키 0x%s" % PK64, PK64),
    "Authorization Digest 구조형": ('Authorization: Digest username="alice", response="%s"' % INFURA, INFURA),
    "Authorization 목록 밖 스킴": ("Authorization: Negotiate %s" % AUTHV, AUTHV),
    "Authorization JSON 따옴표": ('{"authorization": "Bearer %s", "next": 1}' % AUTHV, AUTHV),
    "basic 소문자": ("basic %s 거부" % BASIC, BASIC.rstrip("=")),
    "bEaReR 섞인 대소문자": ("bEaReR %s" % BEARER, BEARER),
    "Digest 등호 둘레 공백": ('Authorization: Digest username="alice", response = "%s"' % INFURA, INFURA),
    "앞 규칙 뒤 origin_string": ("password=origin_string [%s]" % AUTHV, AUTHV),
    "Digest username*= 뒤 response": ("Authorization: Digest username*=UTF-8''J%%C3%%A4s, response=\"%s\"" % INFURA, INFURA),
    "Digest uri=https 뒤 response": ('Authorization: Digest username="alice", uri="https://x.example.invalid/a?b=1", response="%s", qop=auth' % INFURA,
                                     INFURA),
    "Digest uri 맨 https 뒤 response": ("Authorization: Digest uri=https://x.example.invalid/a, response=%s" % INFURA, INFURA),
    "모르는 스킴 id=…,proof=…": ("Authorization: Foo id=abc,proof=%s" % AUTHV, AUTHV),
    "OAuth realm 뒤 consumer_key": ('Authorization: OAuth realm="x", oauth_consumer_key="%s", oauth_signature="zz"' % AUTHV, AUTHV),
    "OAuth 따옴표 없는 목록": ("Authorization: OAuth realm=x, oauth_token=%s" % AUTHV, AUTHV),
    "Proxy-Authorization": ("Proxy-Authorization: Basic %s" % AUTHV, AUTHV),
    "Authorization kv 꼴": ("요청 authorization=Foo %s&b=1" % AUTHV, AUTHV),
    "Authorization dict 홑따옴표": ("{'Authorization': 'Digest response=\\'%s\\'', 'UA': 'tj'}" % AUTHV, AUTHV),
    "Authorization 튜플": ("[('Authorization', 'Negotiate %s'), ('Host', 'h')]" % AUTHV, AUTHV),
    "JSON 안 JSON(이스케이프된 따옴표)": ('{\\"Authorization\\": \\"Digest username=\\\\\\"bob\\\\\\", response=\\\\\\"%s\\\\\\"\\", \\"x\\": 1}'
                                       % AUTHV, AUTHV),
    "proxy_authorization 밑줄": ("proxy_authorization: x %s" % AUTHV, AUTHV),
}
CONTROL = [
    "tx 0x%s 확인" % H64, "해시 0x%s" % H64, "주소 0x%s 잔고" % ADDR, "pubkey 0x%s" % H64,
    "https://solscan.io/tx/5KtPn1LGuxhFiwjxErkxTb5rMbqXNk2aX3XyZ5kVdD6v8yS2Z4iP9X1Lm3oQ7wR8sT6uV4yN2bH5jK9fC1gE3dA",
    "https://solscan.io/token/EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "https://solscan.io/account/9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",
    "https://etherscan.io/tx/0x%s" % H64, "https://etherscan.io/address/0x%s" % ADDR,
    "https://etherscan.io/token/0x%s?a=0x%s" % (ADDR, "2e" * 20),
    "https://eth.blockscout.com/api/v2/addresses/0x%s/token-balances" % ADDR, "https://base.blockscout.com/tx/0x%s" % H64,
    "token 0x%s" % ADDR, "token: USDT", "블록 12345678:0x%s" % H64, "GET /api/v3/myTrades 실패",
    "/sapi/v1/subaccountTransferHistory 429", "Bearer authentication 실패", "basic information", "기준 시각 2026-10-01T12:34:56",
    "authorization failed: 다시 로그인", "401 Unauthorized: 키 확인", "reauthorization: 필요 없음",
]

import logs  # noqa: E402

print("[1] 설정에 없는 꼴 — 로그 줄·외부 오류 문구 둘 다 가림")
for name, (text, sec) in CANARY.items():
    lo, ge = logs.redact_secret_text(text, generic=False), logs.redact_secret_text(text)
    T.chk(sec not in lo and sec[:8] not in lo and sec not in ge and "***" in lo, "가림(로그 줄 · 외부 오류): " + name, (lo, ge))
T.chk(logs.redact_secret_text(CANARY["Authorization Bearer"][0], generic=False) == "헤더 Authorization: ***",
      "Authorization 값 = 스킴 낱말까지 통째(세션8 P1b' — 의도된 변경)", logs.redact_secret_text(CANARY["Authorization Bearer"][0], generic=False))
T.chk(logs.redact_secret_text(CANARY["봇 토큰 URL"][0], generic=False) == "발송 실패 https://api.telegram.org/bot***/sendMessage",
      "봇 토큰 URL = 주소 모양 유지(/bot*** )")
T.chk(logs.redact_secret_text("키 0x%s 뒤 tx 0x%s" % (PK64, H64), generic=False) == "키 *** 뒤 tx 0x%s" % H64,
      "앞말 붙은 0x64 만 가리고 같은 줄 tx 해시는 그대로")
T.chk(logs.redact_secret_text('{"authorization": "Bearer %s", "next": 1}' % AUTHV, generic=False) == '{"authorization": "***", "next": 1}',
      "따옴표 안 Authorization 값 = 닫는 따옴표까지만(뒤 필드 그대로)")
H64L = "0x" + H64
EDGE = [
    ("Authorization: Bearer %s https://etherscan.io/tx/%s" % (BEARER, H64L), "Authorization: ***"),
    ("Authorization: Bearer %s %s" % (BEARER, H64L), "Authorization: ***"),
    ("Authorization: Foo %s 끝" % AUTHV, "Authorization: ***"),
    ("Authorization: %s, 확인\r\n다음 줄 tx %s" % (AUTHV, H64L), "Authorization: ***\r\n다음 줄 tx %s" % H64L),
    ("origin_string[%s] 끝" % AUTHV, "origin_string[***] 끝"), ("origin_string: %s" % AUTHV, "origin_string[***]"),
    ('{"Authorization": "Digest a=\\"1\\", response=\\"%s\\"", "Host": "h"} tx %s' % (AUTHV, H64L), '{"Authorization": "***", "Host": "h"} tx %s' % H64L),
    ("{'authorization': 'Basic %s', 'n': 1}" % AUTHV, "{'authorization': '***', 'n': 1}"),
    ('Authorization: "Bearer %s" 뒤' % AUTHV, 'Authorization: "***" 뒤'),
    ('Authorization: "끝없는 %s\n  File "x.py", line 1' % AUTHV, 'Authorization: "***\n  File "x.py", line 1'),
    ("Authorization:\n다음 줄 그대로", "Authorization:\n다음 줄 그대로"),
    (CANARY["JSON 안 JSON(이스케이프된 따옴표)"][0], '{\\"Authorization\\": \\"***\\", \\"x\\": 1}'),
]
bad_e = [(t, logs.redact_secret_text(t, generic=False), w) for t, w in EDGE if logs.redact_secret_text(t, generic=False) != w]
T.chk(not bad_e, "Authorization 값 범위(따옴표 = 닫는 따옴표까지 · 아니면 줄 끝까지 · 줄을 넘지 않음) · origin_string 표식 '[***]' 종전대로", bad_e)
g_url = logs.redact_secret_text("Authorization: Bearer %s http://u:pw@node.example.invalid/Hidden12" % BEARER)
T.chk(g_url == "Authorization***", "외부 오류 문구: Authorization 이름 뒤 줄 끝까지 통째(URL 포함 · 세션9 단순안)", g_url)
GEN = [
    ("Authorization: https://alice:pw@node.example.invalid/rpc?code=shortsecret", "Authorization***"),
    ("연결 실패 AbCdEfGhIjKl/v2/MnOpQrStUvWxYz12", "연결 실패 ***"),
    ("/v3/Kd3Fh5Jl7Zn9Xb1Cv3Mq5Wr7+Z9x8Y7p6Q5", "***"),
]
GEN += [
    (json.dumps({"Authorization": 'OAuth realm="https://x.example.invalid/a", oauth_consumer_key="S8Consumer42Key"', "Host": "h"}),
     '{"Authorization***'),
    (json.dumps({"Authorization": 'Foo uri="https://rpc.example.invalid/a", proof="U7qLm2vRw9ZtN5xB"'}), '{"Authorization***'),
    ("{'authorization': 'Digest uri=\\'https://x.example.invalid/a\\', response=\\'Qm7Rt2Yp9Wk4\\'', 'n': 1}", "{'authorization***"),
    ("a https://u:pw@h.example.invalid/x Authorization: Foo k=Qm7Rt2Yp9Wk4\nb https://h.example.invalid/y", "a h.example.invalid Authorization***\nb h.example.invalid"),
]
bad_g = [(t, logs.safe_err(t), w) for t, w in GEN if logs.safe_err(t) != w]
NEST = [
    repr(RuntimeError(json.dumps({"Authorization": 'Foo id="x", proof="S8Proof42Key"'}))),
    repr(ValueError(json.dumps({"Authorization": 'OAuth realm="x", oauth_consumer_key="S8Consumer42Key"'}))),
    json.dumps(json.dumps({"Authorization": 'Foo id="x", proof="S8Proof42Key"', "n": 1})),
    json.dumps({"Authorization": "a", "Proxy-Authorization": "Foo k=S8Proof42Key"}),
    repr({"authorization": "realm=x\\", "Proxy-Authorization": 'a"b S8Proof42Key'}),
    repr([("Authorization", "v\\"), ("Proxy-Authorization", "Foo k=\"S8Proof42Key\"")]),
]
SEC9 = ("S8Proof42Key", "S8Consumer42Key")
leak9 = [(t, w, r) for t in NEST for w, r in (("로그", logs.redact_secret_text(t, generic=False)), ("외부", logs.safe_err(t)),
                                              ("URL 먼저", logs.redact_secret_text(logs.redact_urls(t), generic=False))) if any(x in r for x in SEC9)]
raw9 = json.dumps({"Authorization": 'Foo uri="https://x.example.invalid/a", proof="U7qLm2vRw9ZtN5xB"'})
T.chk(not leak9 and "U7qLm2vR" not in logs.redact_secret_text(logs.redact_urls(raw9), generic=False),
      "이스케이프 겹수·한 줄 여러 헤더·값 끝 역슬래시·redact_urls 먼저 부르는 호출측(token_discovery·evm_watch 꼴) — 값 0 노출", leak9[:3])
T.chk(logs.redact_secret_text(NEST[0], generic=False) == "RuntimeError('{\"Authorization\": \"***\"}')"
      and logs.redact_urls("https://u:pw@h.example.invalid/v2/K?authorization=x") == "(주소 숨김)authorization***"
      and logs.redact_urls("노드 https://u:pw@h.example.invalid/v2/K 실패") == "노드 h.example.invalid 실패",
      "repr 로 싼 JSON = 닫는 따옴표(역슬래시 0개)까지 · redact_urls 의 순수 URL 결과 = 종전(호스트만) · 이름이 붙은(잘린) URL = '(주소 숨김)'", logs.redact_secret_text(NEST[0], generic=False))
UI = ["https://s8q7lm2v-authorization:pw@node.example.invalid/rpc", "https://authorization:pw@node.example.invalid/rpc",
      "https://User42:authorization=pw@node.example.invalid/rpc", "wss://proxy-authorization:pw@node.example.invalid"]
UI_W = ["(주소 숨김)authorization***", "https://authorization***", "(주소 숨김)authorization***", "(주소 숨김)authorization***"]
ui_bad = [(u, logs.redact_urls(u), logs.safe_err(u)) for u, w in zip(UI, UI_W) if not (logs.redact_urls(u) == logs.safe_err(u) == w)]
T.chk(not ui_bad, "URL authority(userinfo) 속 'authorization' — 이름 뒤 줄 끝까지 · 이름에 붙은 URL 은 '(주소 숨김)'(사용자명·비밀번호 노출 0)", ui_bad)
cj = '{"url":"https://h.example.invalid","Authorization":"Bearer S8Proof42Key"}'
T.chk(all("S8Proof42" not in r for r in (logs.redact_urls(cj), logs.safe_err(cj), logs.redact_secret_text(cj, generic=False))),
      "압축 JSON(경로 없는 URL 바로 뒤 Authorization) — authority 는 따옴표에서 끝나 값은 가림", (logs.redact_urls(cj), logs.safe_err(cj)))
T.chk(not bad_g, "외부 오류 문구: URL 은 먼저 호스트만 · 24자↑ 덩어리도 원문에서 — 쪼개진 꼬리 0", bad_g)
T.chk(logs.redact_secret_text("origin_string[%s]" % AUTHV, generic=False, extra=["origin_s"]) == "***tring[***]",
      "origin_string 이름이 다른 가림과 겹쳐도 값은 가림(원문에서 자리 표시)")
import time  # noqa: E402

print("[1b] 세션9 단순안 — 외부 오류 문구(generic)·redact_urls 의 Authorization = 이름 뒤 그 줄 끝까지 통째(값 파싱 없음)")
SV, SU = "Qm7Rt2Yp9Wk4", "Zx8Kp3Lm7Nq2"
S9 = [
    ("s8e1 URL 끝 역슬래시", json.dumps({"Authorization": 'Foo uri="https://x.example.invalid/a\\", proof="%s"' % SV, "Host": "h"})),
    ("s8e1 URL 뒤 따옴표", json.dumps({"Authorization": 'OAuth realm="https://x.example.invalid/a", oauth_consumer_key="%s"' % SV})),
    ("s8e2 겹 이스케이프", json.dumps(json.dumps({"Authorization": 'Foo id="x", proof="%s"' % SV, "n": 1}))),
    ("s8e2 repr 로 싼 JSON", repr(RuntimeError(json.dumps({"Authorization": 'Foo uri="https://x.example.invalid/\\\\", proof="%s"' % SV})))),
    ("s8e2 값 끝 역슬래시 + 둘째 헤더", repr({"authorization": "realm=x\\", "Proxy-Authorization": 'a"b %s' % SV})),
    ("s8e3 userinfo 속 글자", "https://%s:authorization@node.example.invalid/x?k=%s" % (SU, SV)),
    ("s8e3 호스트 속 글자", "https://u:%s@authorization.example.invalid/%s" % (SU, SV)),
    ("s8e3 이름 뒤 userinfo", "https://s8-authorization:%s@node.example.invalid" % SV),
    ("s8e4 홑따옴표 압축 dict", "{'url':'https://h','Authorization':'Foo proof=%s'}" % SV),
    ("s8e4 겹따옴표 압축 JSON", '{"url":"https://h","Authorization":"Foo proof=%s"}' % SV),
    ("s8e4 authority 넘김 @", "{'url':'https://%s@h','Authorization':'Foo@x proof=%s'}" % (SU, SV)),
    ("repr 원시 요청(\\r\\n 바로 뒤 이름)", repr("GET / HTTP/1.1\r\nHost: h\r\nAuthorization: Foo proof=%s\r\n" % SV)),
    ("HAR name/value", json.dumps({"name": "Authorization", "value": "Foo proof=%s" % SV})),
    ("대문자·HTTP/2 소문자", "AUTHORIZATION: Foo %s · authorization: x" % SV),
    ("공백 구분", "header Authorization Foo %s" % SV),
    ("Go map", "map[Authorization:[Foo %s] Host:[h]]" % SV),
    ("튜플", "[('Proxy-Authorization', 'Negotiate %s')]" % SV),
    ("kv 쿼리 속", "https://%s@node.example.invalid/a?authorization=%s" % (SU, SV)),
]
lk = []
for name, t in S9:
    outs = {"redact_urls": logs.redact_urls(t), "safe_err": logs.safe_err(t), "generic": logs.redact_secret_text(t),
            "URL 먼저→로그 줄": logs.redact_secret_text(logs.redact_urls(t), generic=False), "scrub": logs.scrub_secrets({"error": t})[0]["error"]}
    for k, r in outs.items():
        if any(x in r or x.lower() in r for x in (SV, SU, SV[:8], SU[:8])):
            lk.append((name, k, r))
T.chk(not lk, "s8e1~s8e4 계열·이름 꼴 전부 — 값·앞 URL userinfo·경로 0 노출(5 경로 · %d 사례)" % len(S9), lk[:4])
T.chk(logs.redact_urls(S9[8][1]) == "{'url':'(주소 숨김)Authorization***" and logs.safe_err(S9[8][1]) == "{'url':'(주소 숨김)Authorization***",
      "s8e4 사례 = 이름 앞 잘린 URL 은 끝 문장부호까지 '(주소 숨김)' + 이름 뒤 '***'", (logs.redact_urls(S9[8][1]), logs.safe_err(S9[8][1])))
ml = "x Authorization: \"끝없는 %s\r\nTraceback (most recent call last):\n  File \"x.py\", line 1\nProxy-Authorization: Foo %s\n끝 https://u:p@h.example.invalid/k" % (SV, SV)
T.chk(logs.redact_urls(ml) == "x Authorization***\r\nTraceback (most recent call last):\n  File \"x.py\", line 1\nProxy-Authorization***\n끝 h.example.invalid"
      and logs.safe_err(ml).splitlines()[1:3] == ["Traceback (most recent call last):", '  File "x.py", line 1'],
      "가림은 그 물리 줄(CR/LF)에서 끝 — 다음 줄(Traceback·File)·다음 줄의 이름은 따로", logs.redact_urls(ml))
T.chk(logs.redact_urls("Authorization\n다음") == "Authorization\n다음" and logs.redact_urls("a Authorization") == "a Authorization",
      "이름이 줄 끝이면 덧붙임 없음")


def _ref_urls(msg):
    import urllib.parse as up

    def host(m9):
        tok = m9.group(0)
        core = tok.rstrip(".,;:!?)]}'\"")
        tail = tok[len(core):]
        for t9 in (core, tok):
            try:
                h9 = up.urlsplit(t9).hostname
            except ValueError:
                h9 = None
            if h9:
                return h9 + (tail if t9 is core else "")
        return "(주소 숨김)" + tail
    return re.sub(r"(?i)(?:https?|wss?)://\S+", host, str(msg))


import random  # noqa: E402
import re  # noqa: E402

rnd = random.Random(9)
PIECES = ["https://", "wss://", "u:p@", "h.example.invalid", "/v2/", "?k=", "#f", "[::1]", ":8545", "'", '"', "\\", "\\\"", ",", " ", "\n", "\r\n",
          "x", "가", "%40", "auth", "oriz", "ation", "@", "(", ")", ".", "Bearer "]
NAMES = ["Authorization", "authorization", "AUTHORIZATION", "Proxy-Authorization", "proxy_authorization", "XAuthorization"]
SEPS = ["", ":", "@", "/", "?", "#", "','", '","', "\\\"", "-", "=", "'", " "]
nochg, fz = [], []
for _ in range(400):
    t = "".join(rnd.choice(PIECES) for _ in range(rnd.randint(0, 14)))
    if "authorization" not in t.lower() and logs.redact_urls(t) != _ref_urls(t) and logs.redact_urls(t).lower() != _ref_urls(t).lower():
        nochg.append((t, logs.redact_urls(t), _ref_urls(t)))
    q = rnd.choice(["", "'", '"', "\\\"", "\\\\\\\""])
    u = rnd.choice(["https://", "wss://", "http://u:"]) + SU + rnd.choice(SEPS)
    tail = "".join(rnd.choice([x for x in PIECES[5:] if x not in ("\n", "\r\n")]) for _ in range(rnd.randint(0, 6)))
    line = rnd.choice(["", "앞 ", "x=", "{'url':'"]) + u + q + rnd.choice(NAMES) + q + rnd.choice(SEPS) + tail + SV + tail
    for r in (logs.redact_urls(line), logs.safe_err(line)):
        if (" " not in u and SU.lower() in r.lower()) or SV in r or SV[:8] in r:
            fz.append((line, r))
T.chk(not nochg, "'authorization' 글자 없는 글 400개 = 라이브 redact_urls 와 글자 같음(무변)", nochg[:3])
T.chk(not fz, "무작위 400줄(이름 꼴·따옴표·이스케이프·앞 URL 붙임·사이 글자) — 값·붙은 URL userinfo 0 노출", fz[:3])
UGL = "https://alice:pW9@node.example.invalid/x?code=" + SV
glue = [(pre, r) for pre in ("/v2/AbCdEfGh123", "Bearer abcdefgh12", "123456789:AAabcdefghijklmnopqrstuv")
        for r in (logs.scrub_secrets({"error": pre + UGL})[0]["error"], logs.safe_err(pre + UGL))
        if any(x in r for x in ("alice", "pW9", SV, "://"))]
T.chk(not glue, "경로형 키·Bearer·맨 봇 토큰 바로 뒤에 붙은 URL — scrub_secrets·safe_err 에서 userinfo·쿼리 0 노출(URL 축소 먼저)", glue)
_SRC = os.path.dirname(os.path.abspath(logs.__file__))
_ORD = re.compile(r"redact_urls\((?:common\.|logs\.)?redact_secret_text\((?!(?:common\.|logs\.)?redact_urls\()")
bad_ord = [(f, i) for f in sorted(os.listdir(_SRC)) if f.endswith(".py")
           for i, ln in enumerate(open(os.path.join(_SRC, f), encoding="utf-8"), 1) if _ORD.search(ln)]
T.chk(not bad_ord, "src 에 'redact_urls(redact_secret_text(원문 …))' 꼴 0 — 로그 줄 가림 전에 URL 축소 먼저(안쪽 redact_urls)", bad_ord)
tl = [(u, logs.redact_urls(u)) for u in ("https://u:!!!!!!!!!!!!authorization@h.example.invalid/x", "https://alice:!;:.,!;:.,authorization@h.example.invalid/x",
                                          "{'url':'https://h/rpc/!!!!!!!!!!!!','Authorization':'Foo'}")
      if "!!!!" in logs.redact_urls(u) or "!;:" in logs.redact_urls(u)]
T.chk(not tl, "s9b2: 잘린 URL 의 끝 문장부호(userinfo·경로 일부일 수 있음)도 '(주소 숨김)' 안으로", tl)
MK = "Qm7Rt2Yp9Wk4Zx8K"
_MKD = os.path.join(T.TMP, "logs_rules_host")
os.makedirs(_MKD, exist_ok=True)
with open(os.path.join(_MKD, "mk.env"), "w", encoding="utf-8") as f:
    f.write("UPBIT_SECRET=%s\n" % MK)
_prev_src = logs._SOURCES[0]
logs.set_sources(lambda: (os.path.join(_MKD, "mk.env"), ""))
logs._SECRET_CACHE["checked"] = 0.0
try:
    hk = "노드 https://u:p@%s.example.invalid/x?k=1 실패" % MK
    mk_pre = logs.redact_secret_text("값 %s 끝" % MK, generic=False)
    hl = [(k, r) for k, r in (("scrub", logs.scrub_secrets({"error": hk})[0]["error"]), ("safe_err", logs.safe_err(hk)),
                              ("generic", logs.redact_secret_text(hk)), ("URL 먼저→로그 줄", logs.redact_urls(logs.redact_secret_text(logs.redact_urls(hk), generic=False))))
          if MK[:8] in r or MK[:8].lower() in r]
finally:
    logs.set_sources(_prev_src)
    logs._SECRET_CACHE["checked"] = 0.0
xh = logs.redact_secret_text("https://%s.example.invalid/x" % MK, extra=[MK])
for u9 in ("https://%s.\u0130.example.invalid/x" % MK, "https://\u0130%s.example.invalid/x" % MK, "https://%s%%2Eexample.invalid/x" % MK):
    xh += " | " + logs.redact_secret_text(u9, extra=[MK])
T.chk(mk_pre == "값 *** 끝" and not hl and MK[:8].lower() not in xh and MK[:8] not in xh, "호스트 속 대소문자 섞인 설정 비밀값·호출측 값 — scrub·safe_err·generic·호출측 꼴 모두 가림(전제: 임시 .env 조각 대조 켜짐)", (mk_pre, hl, xh))
T.chk(logs.redact_urls("노드 https://u:p@Node.Example.invalid:8545/x 실패") == "노드 Node.Example.invalid 실패"
      and logs.redact_urls("https://[::1]:8545/x") == "::1" and logs.redact_urls("https://U@H.example.invalid") == "H.example.invalid"
      and logs.redact_urls("https://\u0130x.Example.invalid/k") == "\u0130x.Example.invalid" and logs.redact_urls("http://[fe80::1%25Eth0]/") == "fe80::1%25Eth0",
      "URL 축소 = 호스트 글자 원문 그대로(지우기만 · 소문자로 바꾸지 않음) · IPv6·userinfo 뒤 호스트")
idem = [t for _, t in S9 if logs.redact_urls(logs.redact_urls(t)) != logs.redact_urls(t)]
T.chk(not idem, "redact_urls 두 번 = 한 번(외부 오류 문구 경로가 앞·뒤로 두 번 부름)", idem[:2])
slow9 = []
for name, text in (("이름 반복", "authorization" * 5000), ("URL+이름 반복", ("https://a" + "Authorization") * 3000),
                   ("줄마다 이름", "https://h/x Authorization: v\n" * 5000), ("긴 줄 뒤 이름", "x" * 50000 + " authorization: " + "y" * 50000)):
    t9 = time.time()
    logs.safe_err(text)
    if time.time() - t9 > 1.0:
        slow9.append((name, round(time.time() - t9, 2)))
T.chk(not slow9, "외부 오류 문구 Authorization 자르기 = 선형 시간(긴 입력 1초 안)", slow9)


slow = []
for name, text in (("앞말+공백", "secret" + " " * 20000 + "!"), ("authorization+공백", "authorization:" + " " * 20000),
                   ("bearer+공백", "bearer" + " " * 20000 + "!"), ("경로형", "/v2/" + "a" * 20000 + "!"),
                   ("Digest k = v 반복", "authorization: digest " + "a = " * 5000), ("k=, 반복", "authorization: x, " + "a=," * 5000),
                   ("이름 반복", "authorization:" * 3000), ("닫힌 따옴표 반복", 'authorization:"a" ' * 3000),
                   ("역슬래시 따옴표", 'authorization: \\"' + '\\\\"' * 20000), ("k 다른 열기", "".join('authorization: ' + "\\" * k + '"x' for k in range(200)))):
    t9 = time.time()
    logs.redact_secret_text(text, generic=False)
    if time.time() - t9 > 0.5:
        slow.append((name, round(time.time() - t9, 2)))
T.chk(not slow, "긴 공백·긴 덩어리 입력도 선형 시간(역추적 폭주 없음 — 2만 자 0.5초 안)", slow)
both = logs.redact_secret_text("Authorization: Bearer %s\nTraceback (most recent call last):\n  다음 줄" % BEARER, generic=False)
T.chk(both.splitlines()[1:] == ["Traceback (most recent call last):", "  다음 줄"], "가림이 줄을 넘지 않음(값 끝 = 줄바꿈)", both)

print("[2] 대조군 무변(과잉 가림 0)")
over = [(c, logs.redact_secret_text(c, generic=False)) for c in CONTROL if logs.redact_secret_text(c, generic=False) != c]
T.chk(not over, "로그 줄: 대조군 %d개 글자 그대로" % len(CONTROL), over)
want = {c: ("token: ***" if c == "token: USDT" else logs._LONG_RE.sub("***", logs.redact_urls(c))) for c in CONTROL}   
over2 = [(c, logs.redact_secret_text(c), want[c]) for c in CONTROL if logs.redact_secret_text(c) != want[c]]
T.chk(not over2, "외부 오류 문구: 대조군 = 종전 규칙 결과 그대로 — 새 규칙의 추가 가림 0", over2)
T.chk(logs.strip_bidi("a\u202eb\u2066c\u200fd\u061ce") == "abcde" and logs.strip_bidi(None) is None and logs.strip_bidi("주소 0x1f") == "주소 0x1f",
      "strip_bidi = bidi 제어문자만 뺌(None 그대로)")

print("[3] 잡히지 않은 예외 — 자식 프로세스(본·다른 스레드)")
CHILD = r'''
import sys, threading
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import logs
if sys.argv[2] == "1":
    logs.install_excepthook()
    logs.install_excepthook()
def boom():
    raise RuntimeError("스레드 " + sys.argv[3])
t = threading.Thread(target=boom, name="t-synth-worker")
t.start(); t.join()
t2 = threading.Thread(target=lambda: sys.exit(3), name="t-synth-exit")
t2.start(); t2.join()
raise ValueError("본 " + sys.argv[3])
'''
CONF_SEC = "SYNTHconfQwErTyUiOpZxCv"
MSG = "https://x.example.invalid/v2/%s · 키 0x%s · 설정 %s · Authorization: Bearer %s" % (PATHK, PK64, CONF_SEC, BEARER)
cenv = {"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8", "TJ_SYNTH_SECRET": CONF_SEC}


def run_child(hook):
    r = subprocess.run([sys.executable, "-I", "-c", CHILD, T.SRC, hook, MSG], env=cenv, capture_output=True, text=True,
                       encoding="utf-8", timeout=60)
    return r.returncode, r.stderr


rc1, e1 = run_child("1")
rc0, e0 = run_child("0")
T.chk(rc1 == rc0 == 1 and "ValueError" in e1, "(전제) 자식이 예외로 끝남(훅 있음·없음 같은 종료 코드)", (rc1, rc0, e1[-300:]))
T.chk(all(s not in e1 for s in (BEARER, PATHK, PK64, CONF_SEC[:8])) and BEARER in e0, "훅 = 추적·예외 줄의 비밀값 0(훅 없으면 샘 — 시험 뜻 확인)")
l1, l0 = e1.splitlines(), e0.splitlines()
T.chk(len(l1) == len(l0) and "Exception in thread t-synth-worker:" in l1 and "t-synth-exit" not in e1,
      "줄 수 같음 · 'Exception in thread NAME:' 보존 · 스레드 SystemExit 은 조용(기본 훅과 같음)", (len(l1), len(l0)))
diff = [(a, b) for a, b in zip(l1, l0) if a != b and a != logs.redact_secret_text(b, generic=False, extra=[CONF_SEC])]
T.chk(not diff and sum(a != b for a, b in zip(l1, l0)) == 2, "다른 줄 = 예외 줄 2개뿐이고 그 줄 = 로그 필터 규칙으로 가린 것", diff[:3])

import chk_logs  # noqa: E402


def crashes(lines):
    lw, fst = chk_logs.LogWatch(), {}
    lw.feed("tj-synth", "2027-01-15 12:00:00,000 INFO [tj-synth] 시작", fstate=fst)
    for ln in lines:
        lw.feed("tj-synth", ln, ts_hint=1_800_000_000.0, fstate=fst)
    lw.feed("tj-synth", "2027-01-15 12:00:01,000 INFO [tj-synth] 다음 줄", fstate=fst)
    return [e[3] for e in lw._u("tj-synth")["ev"] if e[1] == "crash"]


c1, c0 = crashes(l1), crashes(l0)
T.chk(len(c1) == len(c0) == 2 and c1[0].startswith("RuntimeError: 스레드 https://x.example.invalid/v2/*** · 키 *** · 설정 *** · Authorization: ***") and c1[1].startswith("ValueError: 본 "),
      "chk_logs 크래시 판정 = 훅 없는 출력과 같은 2건(스레드·본) · 예외 줄은 가린 글", c1)
CHILD_NAME = r'''
import sys, threading
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import logs
logs.install_excepthook()
t = threading.Thread(target=lambda: 1 / 0, name="scan-" + sys.argv[2])
t.start(); t.join()
'''
rn = subprocess.run([sys.executable, "-I", "-c", CHILD_NAME, T.SRC, CONF_SEC[-12:]], env=cenv, capture_output=True, text=True, encoding="utf-8",
                    timeout=60)
T.chk("Exception in thread scan-***:" in rn.stderr and CONF_SEC[-12:] not in rn.stderr and "ZeroDivisionError" in rn.stderr,
      "스레드 이름에 든 설정 비밀값 조각도 가림(머리 줄 모양 그대로)", rn.stderr[:300])
fb = logs.format_exception_redacted(ValueError, 5, None)
T.chk(fb.splitlines() == ["Traceback (most recent call last):", "  (추적 숨김 — 가리기 실패)", "ValueError"] and crashes(fb.splitlines()) == ["ValueError"],
      "가리기 실패 = Traceback 머리 + 타입 이름만(크래시 판정 유지)", fb)
UNT = ['2027-01-15 12:00:00,500 ERROR [tj-synth] 요청 실패 Authorization: "unterminated Digest response=%s' % INFURA,
       "Traceback (most recent call last):", '  File "x.py", line 3, in <module>', "    go()", "ValueError: 끝"]
u_red = logs.redact_secret_text("\n".join(UNT), generic=False).split("\n")
T.chk(INFURA[:8] not in "\n".join(u_red) and u_red[1:] == UNT[1:] and crashes(u_red) == crashes(UNT) == ["ValueError: 끝"],
      "닫히지 않은 따옴표 Authorization 뒤 Traceback·File 줄 = 그대로(물리 줄에서 끝) · chk_logs 크래시 판정 같음", (u_red, crashes(u_red)))


def _chained():
    try:
        try:
            raise KeyError('Authorization: "unterminated %s' % INFURA)
        except KeyError as e8:
            raise ValueError('Proxy-Authorization: Digest uri="https://x.example.invalid/a", response="%s' % INFURA) from e8
    except ValueError:
        try:
            raise RuntimeError("Authorization: OAuth realm=x, oauth_consumer_key=%s" % AUTHV)
        except RuntimeError:
            return sys.exc_info()


import traceback  # noqa: E402

ei = _chained()
ch_raw, ch_red = "".join(traceback.format_exception(*ei)), logs.format_exception_redacted(*ei)
rl, dl = ch_raw.splitlines(), ch_red.splitlines()
kept = [ln for ln in rl if ln.startswith(("Traceback", "  File ", "During handling", "The above exception"))]
T.chk(INFURA[:8] not in ch_red and AUTHV[:8] not in ch_red and INFURA in ch_raw and len(dl) == len(rl)
      and [ln for ln in dl if ln.startswith(("Traceback", "  File ", "During handling", "The above exception"))] == kept and len(kept) >= 6,
      "연쇄 예외(from · 처리 중 예외) = 비밀값 0 · 줄 수·Traceback·File·연결 문구 줄 그대로", dl)
T.chk([c.split(":")[0] for c in crashes(dl)] == [c.split(":")[0] for c in crashes(rl)] and crashes(dl),
      "연쇄 예외 chk_logs 크래시 판정(예외 타입) = 가리기 전과 같음", (crashes(dl), crashes(rl)))

print("[4] tj-web 요청 처리 예외(QuietHTTPServer.handle_error)")
with open(os.path.join(T.ROOT, "config.example.json"), encoding="utf-8") as f:
    CFG = json.load(f)
CFG["wallets"], CFG["exchange_addresses"] = [], []
CFG["web"] = {"port": 8023, "bind": "loopback"}
with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump(CFG, f, ensure_ascii=False)
import web  # noqa: E402

SRV = web.QuietHTTPServer(("127.0.0.1", 0), web.Handler)
ADDR9 = ("127.0.0.1", 50123)


def handled(exc, base=False):
    buf = io.StringIO()
    try:
        raise exc
    except Exception:   # noqa: BLE001
        with contextlib.redirect_stderr(buf):
            if base:
                socketserver.BaseServer.handle_error(SRV, None, ADDR9)
            else:
                SRV.handle_error(None, ADDR9)
    return buf.getvalue()


got = handled(RuntimeError("처리 실패 Authorization: Bearer %s · %s" % (BEARER, PATHK)))
ref = handled(RuntimeError("처리 실패 Authorization: Bearer %s · %s" % (BEARER, PATHK)), base=True)
g9, r9 = got.splitlines(), ref.splitlines()
T.chk(BEARER not in got and BEARER in ref, "추적의 비밀값 가림(기본 socketserver 출력엔 샘 — 시험 뜻 확인)")
T.chk(len(g9) == len(r9) and g9[0] == r9[0] == "-" * 40 and g9[1] == r9[1] == "Exception occurred during processing of request from %s" % (ADDR9,)
      and g9[2] == "Traceback (most recent call last):" and g9[-1] == "-" * 40 and g9[-2] == "RuntimeError: 처리 실패 Authorization: ***",
      "모양 = socketserver.BaseServer.handle_error 와 같음(줄 40·안내 줄·추적·줄 40)", g9[:3] + g9[-2:])
T.chk(handled(ConnectionResetError("끊김")) == "" and handled(BrokenPipeError("끊김")) == "", "클라이언트가 끊은 연결은 조용(종전)")
SRV.server_close()

print("[5] 텔레그램 발송 — bidi 제어문자 제거 + 가림(자식 프로세스 → 루프백 모의 서버 · 실제 HTTP 경로)")
SENT = []


class _TG(BaseHTTPRequestHandler):
    def do_POST(self):
        SENT.append((self.path, self.rfile.read(int(self.headers.get("Content-Length") or 0))))
        b = b'{"ok": true, "result": {"message_id": 7}}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass


TG = ThreadingHTTPServer(("127.0.0.1", 0), _TG)
threading.Thread(target=TG.serve_forever, daemon=True, name="t-logs-rules-tg").start()
CHILD_TG = r"""
import json, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import alert_bot
a = alert_bot.send_message(sys.argv[2], "123", sys.argv[3])
b = alert_bot.send_photo(sys.argv[2], "123", b"PNG-synth", caption=sys.argv[4])
print(json.dumps([a[0], b[0]]))
"""
TOK = "5512345678:AAQwErTyUiOpAsDfGhJkLzXcVbNm12"
RLO, LRO, LRI, PDI = "\u202e", "\u202d", "\u2066", "\u2069"
tenv = {"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8", "TJ_BASE": T.TMP, "TJ_TG_API": "http://127.0.0.1:%d" % TG.server_address[1]}
r5 = subprocess.run([sys.executable, "-I", "-c", CHILD_TG, T.SRC, TOK, "주소 0x%s 받음%s 거꾸로 %sBearer %s%s" % (ADDR, RLO, LRI, BEARER, PDI),
                     "요약%s 키 0x%s" % (LRO, PK64)], env=tenv, capture_output=True, text=True, encoding="utf-8", timeout=60)
TG.shutdown()
TG.server_close()
T.chk(r5.returncode == 0 and r5.stdout.strip().splitlines()[-1:] == ["[true, true]"] and len(SENT) == 2, "(전제) 자식이 모의 서버로 2통 보냄",
      (r5.returncode, r5.stdout[-200:], r5.stderr[-400:], len(SENT)))
by = {p9.rsplit("/", 1)[-1]: b9 for p9, b9 in SENT}
txt5 = urllib.parse.parse_qs(by.get("sendMessage", b"").decode("utf-8")).get("text", [""])[0]
T.chk(txt5 == "주소 0x%s 받음 거꾸로 Bearer ***" % ADDR, "send_message 본문: bidi 0 · Bearer 가림 · 주소 그대로", txt5)
cap6 = by.get("sendPhoto", b"").split(b'name="caption"\r\n\r\n', 1)[-1].split(b"\r\n--", 1)[0].decode("utf-8", "replace")
T.chk(cap6 == "요약 키 ***", "send_photo 캡션: bidi 0 · 앞말+0x64 가림", cap6)

T.finish()
