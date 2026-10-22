#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _sec_lint as L  # noqa: E402
import _harness as T  # noqa: E402

import ast  # noqa: E402
import http.client  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

t0 = time.time()
RX = re.compile(r"^/(?:api(?:/[A-Za-z0-9_\-]+)+|v2(?:/[A-Za-z0-9_.\-]+)*|login|classic|futures|support\.js|index\.html)?$")
PREFIX_RX = re.compile(r"^/api/(?:[A-Za-z0-9_\-]+/)+$")
SENDERS = {"_send", "_send_bytes", "_send_asset", "send_response"}

found, prefix_of, acts = {}, {}, {}
IXR = L.PyIndex(T.ROOT, ("src",), only=lambda n9, t9: False)
for p in L.py_files(T.ROOT, "src"):
    with open(p, encoding="utf-8") as f9:
        txt9 = f9.read()
    if not any("." + x9 + "(" in txt9 for x9 in sorted(SENDERS)):
        continue
    tree = L.py_parse(p)
    mod = os.path.basename(p)[:-3]
    if not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in SENDERS for n in ast.walk(tree)):
        continue
    docs = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    pres = set()
    owner, fi_of = {}, {}
    for fi in L.func_table(tree):
        for n9 in fi.nodes:
            owner[id(n9)] = fi.qual.rsplit(".", 1)[-1].lower()
            fi_of[id(n9)] = fi
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs:
            if RX.match(n.value):
                fq = owner.get(id(n), "")
                found.setdefault(n.value, set()).add("POST" if "post" in fq else ("GET" if "get" in fq else "?"))
            elif PREFIX_RX.match(n.value):
                pres.add(n.value)
        elif isinstance(n, (ast.Name, ast.Attribute)) and isinstance(getattr(n, "ctx", None), ast.Load):
            v9 = L.resolve_fi(IXR, mod, fi_of.get(id(n)), n)
            if v9 and RX.match(v9):
                fq = owner.get(id(n), "")
                found.setdefault(v9, set()).add("POST" if "post" in fq else ("GET" if "get" in fq else "?"))
            elif v9 and PREFIX_RX.match(v9):
                pres.add(v9)
    for n in ast.walk(tree):
        if isinstance(n, ast.Compare) and isinstance(n.left, ast.Name) and n.left.id == "act":
            for c in n.comparators:
                for v in (list(c.elts) if isinstance(c, (ast.Tuple, ast.List, ast.Set)) else [c]):
                    a9 = v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else \
                        (L.resolve_fi(IXR, mod, fi_of.get(id(n)), v) if isinstance(v, (ast.Name, ast.Attribute)) else "")
                    if a9 and "*" not in a9:
                        for pre in pres:
                            acts.setdefault(pre, set()).add(a9)
    for pre in pres:
        prefix_of.setdefault(pre, set()).add(mod)
ALL_LITS = set()
_LIT_HINT = ("/api/", "/v2", "/login", "/classic", "/futures", "/support.js", "/index.html", '"/"', "'/'")
for p in L.py_files(T.ROOT, "src"):
    with open(p, encoding="utf-8") as f9:
        txt9 = f9.read()
    if not any(x9 in txt9 for x9 in _LIT_HINT):
        continue
    for n in ast.walk(L.py_parse(p)):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and RX.match(n.value):
            ALL_LITS.add(n.value)
import http_assets  # noqa: E402

for fn in http_assets._V2_FILES:
    found.setdefault("/v2/" + fn, set()).add("GET")
for pre, a9 in acts.items():
    for a in a9:
        found.setdefault(pre + a, set()).add("POST")
T.chk(len(found) >= 60 and "/api/state" in found and "/api/setup/wallets/add" in found, "라우트 발견(응답 모듈 문자열 · act · _V2_FILES)", len(found))

with open(os.path.join(T.ROOT, "config.example.json"), encoding="utf-8") as f:
    CFG = json.load(f)
CFG["wallets"], CFG["exchange_addresses"] = [], []
CFG["web"] = {"port": 8023, "bind": "loopback"}
CFG.setdefault("balance_check", {})["enabled"] = False
with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump(CFG, f, ensure_ascii=False)
import login_auth as LA  # noqa: E402
import login_limits as LL  # noqa: E402
import onboarding  # noqa: E402
import settings_store as ss  # noqa: E402
import web  # noqa: E402
import web_ctx  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

LA.init(CFG)
LL.LIM = LL.Limiter()
REC = LA.set_password("Route-Matrix-Horse-4471", iters=200_000)
web.BUILDER = onboarding.DemoBuilder()
web_ctx.mats_ready = lambda path: False
onboarding.SETUP_JS = os.path.join(T.ROOT, "web", "v2", "setup.js")
import logging  # noqa: E402

logging.getLogger("tj-web").setLevel(logging.ERROR)
onboarding._dispatch = lambda act, b: {"ok": True, "stub": act}
SRV = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
PORT = SRV.server_address[1]
threading.Thread(target=SRV.serve_forever, daemon=True, name="t-route-matrix").start()
HOST, ORIGIN = "127.0.0.1:%d" % PORT, "http://127.0.0.1:%d" % PORT
INSTALL = ss.csrf_token()


def req(method, path, cookie=None, origin=True, csrf=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=60)
    h = {"Host": HOST}
    if method == "POST":
        if origin is True:
            h["Origin"] = ORIGIN
        elif origin:
            h["Origin"] = origin
        h["Content-Type"] = "application/json"
        if csrf:
            h["X-TJ-CSRF"] = csrf
    if cookie:
        h["Cookie"] = "%s=%s" % (LA.COOKIE, cookie)
    h.update(headers or {})
    c.request(method, path, body=b"{}" if method == "POST" else None, headers=h)
    r = c.getresponse()
    raw = r.read()
    c.close()
    try:
        err = str((json.loads(raw.decode() or "null") or {}).get("error") or "")
    except (ValueError, AttributeError):
        err = ""
    return r.status, err


FIVE = {}


def kind(st, err):
    if st >= 500:
        FIVE.setdefault((st, err), None)
    if st in (401, 302):
        return "auth"
    if st == 403 and "CSRF" in err:
        return "csrf"
    if st == 403 and ("출처" in err or "Origin" in err or "다른 출처" in err):
        return "origin"
    return "pass"


def sess():
    return LA.new_session(REC)


def probe_get(path):
    a = kind(*req("GET", path))
    s = kind(*req("GET", path, cookie=sess()))
    it = kind(*req("GET", path, headers={LA.INTERNAL_HDR: LA.internal_token(True)}))
    return {"auth": "open" if a == "pass" else "session", "_with_session": s, "internal": it == "pass"}


WRONG = {}


def probe_post(path):
    a = kind(*req("POST", path, csrf=INSTALL))
    no = kind(*req("POST", path, cookie=sess()))
    WRONG[path] = (no, kind(*req("POST", path, cookie=sess(), csrf="g1-invalid-csrf-token")))
    ins = kind(*req("POST", path, cookie=sess(), csrf=INSTALL))
    sc_tok = sess()
    se = kind(*req("POST", path, cookie=sc_tok, csrf=LA._sess_csrf(sc_tok)))
    og = kind(*req("POST", path, cookie=sess(), origin=None, csrf=INSTALL))
    acc = [n for n, k9 in (("install", ins), ("session", se)) if k9 == "pass"]
    return {"auth": "open" if a != "auth" else "session", "csrf": "none" if no == "pass" else ("+".join(acc) or "rejected-all"),
            "origin": "required" if og == "origin" else "optional"}


TNAME = "routes"
L.check_base_ref(T)
loaded = L.load_rows(TNAME)
if loaded is None:
    ref0, rb0, _why0 = L.base_ref_rows(TNAME)
    if rb0 is not None or not L.BASELINE_INIT:
        if rb0 is not None:
            T.chk(False, "표 sec_%s.jsonl 이 없어짐(기준 커밋 %s 에는 있음) — 지우지 말고 줄을 고치세요" % (TNAME, ref0[:10]))
        else:
            print("(표 sec_%s.jsonl 없음 — 비교 건너뜀 · 공개 배치면 정상)" % TNAME)
        SRV.shutdown()
        SRV.server_close()
        T.finish()
doc, rows = loaded if loaded else ("", [])
table = {r["r"]: r for r in rows}

if loaded is None:
    POST_PATHS = set()
    for p in L.py_files(T.ROOT, "src"):
        tree = L.py_parse(p)
        for fnode in ast.walk(tree):
            if isinstance(fnode, (ast.FunctionDef, ast.AsyncFunctionDef)) and ("POST" in fnode.name or "post" in fnode.name.lower()):
                for n in ast.walk(fnode):
                    if isinstance(n, ast.Constant) and isinstance(n.value, str) and RX.match(n.value):
                        POST_PATHS.add(n.value)
    POST_PATHS |= {p9 for p9 in found if p9.startswith(("/api/setup/", "/api/ops/")) and p9 not in ("/api/setup/status", "/api/setup/tier", "/api/setup/chains")}
    POST_PATHS |= {"/api/login", "/api/logout", "/api/auth/setup", "/api/auth/password", "/api/auth/logout_all"}
    EXT = re.compile(r"^/api/v\d+/(?!state$|part$)|^/api/v3$|^/api/v2$")
    new_rows = []
    for p9 in sorted(found):
        if EXT.match(p9):
            new_rows.append({"r": "EXT " + p9, "note": "바깥 API 주소(응답 모듈 안 문자열 — 우리 라우트 아님)"})
            continue
        if p9 in POST_PATHS:
            new_rows.append(dict({"r": "POST " + p9}, **probe_post(p9)))
        if p9 not in POST_PATHS or p9 in ("/api/receipt_eval", "/api/alert_prefs"):
            g = probe_get(p9)
            g.pop("_with_session", None)
            new_rows.append(dict({"r": "GET " + p9}, **g))
    for extra in ("/", "/v2/", "/v2/fonts/plex.css"):
        g = probe_get(extra)
        g.pop("_with_session", None)
        new_rows.append(dict({"r": "GET " + extra}, **g))
    rows, table = new_rows, {r["r"]: r for r in new_rows}

print("[1] 로그인 켬 — 표의 라우트마다 실제 요청")
bad = []
for r in sorted(table.values(), key=lambda x: x["r"]):
    m9, path = r["r"].split(" ", 1)
    if m9 == "GET":
        o = probe_get(path)
        if o["auth"] == "session" and o["_with_session"] == "auth":
            bad.append("%s: 세션이 있어도 401" % r["r"])
        for k9 in ("auth", "internal"):
            if r.get(k9) != o[k9]:
                bad.append("%s: %s 표 %r ≠ 관측 %r" % (r["r"], k9, r.get(k9), o[k9]))
    elif m9 == "POST":
        o = probe_post(path)
        for k9 in ("auth", "csrf", "origin"):
            if r.get(k9) != o[k9]:
                bad.append("%s: %s 표 %r ≠ 관측 %r" % (r["r"], k9, r.get(k9), o[k9]))
T.chk(not bad, "로그인 켬: 표의 규칙 = 관측(로그인·CSRF 토큰 종류·Origin·내부 토큰)", bad[:20])
wrong9 = sorted(p9 for p9, (no9, wr9) in WRONG.items() if no9 != "pass" and wr9 != "csrf")
T.chk(WRONG and not wrong9, "CSRF 토큰이 필요한 POST = 아무 값 토큰도 거부(있기만 하면 받는 약화 0)", wrong9)
sens = [r["r"] for r in table.values() if r["r"].startswith("GET /api/") and r.get("auth") != "session"
        and r["r"] not in ("GET /api/auth/status",)]
T.chk(not sens, "민감 GET(/api/* — 설정·키·원장)은 로그인 켬일 때 전부 세션 필요(상태 조회만 공개)", sens)
posts_open = [r["r"] for r in table.values() if r["r"].startswith("POST ") and r.get("auth") == "open"]
T.chk(sorted(posts_open) == ["POST /api/auth/setup", "POST /api/login"], "로그인 없이 받는 POST = 로그인·첫 비밀번호 둘뿐", posts_open)
no_csrf = [r["r"] for r in table.values() if r["r"].startswith("POST ") and r.get("csrf") == "none" and r.get("auth") != "open"]
T.chk(not no_csrf, "세션이 필요한 쓰기 POST 는 전부 CSRF 토큰 필요", no_csrf)
no_origin = [r["r"] for r in table.values() if r["r"].startswith("POST ") and r.get("origin") != "required"]
T.chk(not no_origin, "모든 POST = Origin 필수(교차 출처 거부)", no_origin)

print("[2] 로그인 꺼짐 — 프록시 헤더 거부 · CSRF")
LA.init(dict(CFG, web={"port": 8023, "bind": "loopback", "login": {"enabled": False}}))
bad2 = []
obs_off = {}
for r in sorted(table.values(), key=lambda x: x["r"]):
    m9, path = r["r"].split(" ", 1)
    if m9 not in ("GET", "POST"):
        continue
    st, _e = req(m9, path, headers={"X-Forwarded-For": "203.0.113.9"}, csrf=INSTALL if m9 == "POST" else None)
    obs_off[r["r"]] = {"proxy_off": st}
    if m9 == "POST":
        k_off = kind(*req("POST", path))
        obs_off[r["r"]]["csrf_off"] = {"csrf": "install", "pass": "none"}.get(k_off, k_off)
    for k9, v9 in obs_off[r["r"]].items():
        if loaded is None:
            r[k9] = v9
        elif r.get(k9) != v9:
            bad2.append("%s: %s 표 %r ≠ 관측 %r" % (r["r"], k9, r.get(k9), v9))
T.chk(not bad2, "로그인 꺼짐: 프록시 헤더 요청 응답·CSRF 규칙 = 표", bad2[:20])
T.chk(all(v.get("proxy_off") == 403 for v in obs_off.values()), "로그인 꺼짐 + 프록시·터널 헤더 = 모든 라우트 403(fail-closed)",
      sorted(k for k, v in obs_off.items() if v.get("proxy_off") != 403)[:10])
MATS_503 = (503, "계산 재료를 만드는 중 — 잠시 뒤 다시 시도하세요")
T.chk(not [k9 for k9 in FIVE if k9 != MATS_503], "라우트 탐침 5xx = 계산 재료 대기 503 만(그 밖 500·503 = 관문 뒤 오류 — 관문 통과로 세지 않음)",
      sorted(k9 for k9 in FIVE if k9 != MATS_503)[:10])
SRV.shutdown()
SRV.server_close()

have = {}
for r in table.values():
    m9, p9 = r["r"].split(" ", 1)
    have.setdefault(p9, set()).add(m9)
listed = set(have)
new = []
for p9, meths in sorted(found.items()):
    for m9 in sorted(meths):
        if (m9 == "?" and not have.get(p9)) or (m9 != "?" and m9 not in have.get(p9, ())):
            new.append("%s %s" % (m9, p9))
T.chk(not new, "표에 없는 새 라우트 0(메서드까지 — 기존 GET 경로에 POST 를 더해도 잡음) — sec_routes.jsonl 에 등록하고 검사 규칙(auth·csrf·origin·internal)을 정하세요", new)
stale = sorted(p9 for p9 in listed if p9 not in found and p9 not in ALL_LITS and p9 not in ("/v2/", "/v2/fonts/plex.css"))
if stale:
    print("안내 [routes] 코드에서 안 보이는 표 줄: %s" % stale[:10])
    if L.STALE_FAIL:
        T.chk(False, "[routes] 표에 지난 라우트 — 지우세요(TJ_ARCH_STALE_FAIL=1)", stale)
if loaded is None:
    L.save_rows(TNAME, "G1 test_sec_route_matrix 선언 표 — 라우트별 로그인·CSRF 토큰 종류·Origin·내부 토큰·로그인 꺼짐 규칙(관측과 같아야 함). "
                       "3막에서 바꾸면 이 줄을 새 관측으로(약해지는 변경 = FAIL)", rows, "r")
    print("(표 새로 만듦: arch_baseline/sec_%s.jsonl · %d줄)" % (TNAME, len(rows)))
else:
    ref, rb, why = L.base_ref_rows(TNAME)
    if rb is None:
        print("(표: 기준 커밋 비교 건너뜀 — %s)" % why)
    else:
        weaker = []
        for b9 in rb:
            c9 = table.get(b9["r"])
            if c9 is None:
                m9, p9 = b9["r"].split(" ", 1)
                if m9 in ("GET", "POST") and (p9 in found or p9 in ALL_LITS):
                    weaker.append("%s: 기준 커밋 표에 있던 줄이 없어짐(코드엔 경로가 그대로)" % b9["r"])
                continue
            if b9.get("auth") == "session" and c9.get("auth") == "open":
                weaker.append("%s: 세션 → 공개" % b9["r"])
            if b9.get("csrf") not in (None, "none") and c9.get("csrf") == "none":
                weaker.append("%s: CSRF → 없음" % b9["r"])
            if b9.get("csrf_off") not in (None, "none") and c9.get("csrf_off") == "none":
                weaker.append("%s: 로그인 꺼짐 CSRF → 없음" % b9["r"])
            if b9.get("origin") == "required" and c9.get("origin") != "required":
                weaker.append("%s: Origin 필수 → 선택" % b9["r"])
            if b9.get("internal") is False and c9.get("internal") is True:
                weaker.append("%s: 내부 토큰 허용 추가" % b9["r"])
            if b9.get("proxy_off") == 403 and c9.get("proxy_off") != 403:
                weaker.append("%s: 로그인 꺼짐 프록시 거부 해제" % b9["r"])
        T.chk(not weaker, "[routes] 표가 기준 커밋(%s)보다 약해지지 않음" % ref[:10], weaker)
n_get = sum(1 for r in table.values() if r["r"].startswith("GET "))
n_post = sum(1 for r in table.values() if r["r"].startswith("POST "))
print("  표: GET %d · POST %d · EXT %d" % (n_get, n_post, sum(1 for r in table.values() if r["r"].startswith("EXT "))))
print("(시간 %.1f초)" % (time.time() - t0))
T.finish()
