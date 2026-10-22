#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import email.message  # noqa: E402
import http.client  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

with open(os.path.join(T.ROOT, "config.example.json"), encoding="utf-8") as f:
    CFG = json.load(f)
CFG["wallets"], CFG["exchange_addresses"] = [], []
CFG["web"] = {"port": 8023, "bind": "loopback"}
CFG.setdefault("balance_check", {})["enabled"] = False
with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump(CFG, f, ensure_ascii=False)

import paths  # noqa: E402
import csrf_gate  # noqa: E402
import http_post  # noqa: E402
import login_auth as LA  # noqa: E402
import settings_store as ss  # noqa: E402
import web  # noqa: E402

chk = T.chk
assert T.TMP in paths.STATE_DIR
LA.init(CFG)
PW = "Synthetic-Otter-4417"
LA.set_password(PW, iters=200_000)
SRV = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
PORT = SRV.server_address[1]
threading.Thread(target=SRV.serve_forever, daemon=True, name="t-csrf-session").start()
HOST, ORIGIN = "127.0.0.1:%d" % PORT, "http://127.0.0.1:%d" % PORT
CSRF_ERR = "CSRF 토큰 불일치 — 페이지를 새로고침하세요"


def req(method, path, body=None, cookies=None, csrf=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=60)
    h = {"Host": HOST}
    if method == "POST":
        h.update({"Origin": ORIGIN, "Content-Type": "application/json"})
    if csrf:
        h["X-TJ-CSRF"] = csrf
    if cookies:
        h["Cookie"] = "; ".join("%s=%s" % kv for kv in cookies.items())
    c.request(method, path, body=json.dumps(body or {}).encode() if method == "POST" else None, headers=h)
    r = c.getresponse()
    raw = r.read()
    sc = r.msg.get_all("Set-Cookie") or []
    c.close()
    try:
        j = json.loads(raw.decode() or "null")
    except ValueError:
        j = None
    return r.status, j if isinstance(j, dict) else {}, sc


def cookie_val(sc, name):
    for s in sc:
        if s.startswith(name + "="):
            return s.split(";", 1)[0].split("=", 1)[1]
    return None


def login(cookies=None):
    st, j, sc = req("POST", "/api/login", {"password": PW}, cookies=cookies)
    return st, sc


print("[A] 로그인 켬 — 세션 CSRF")
st, sc = login()
t1 = cookie_val(sc, "tj_session")
st, j, _ = req("GET", "/api/setup/status", cookies={"tj_session": t1})
c1 = j.get("csrf")
chk(st == 200 and c1 == LA._sess_csrf(t1) and c1 != ss.csrf_token(), "A1 상태 조회 csrf = 이 세션의 CSRF(설치 토큰 아님)", (st, c1 == ss.csrf_token()))
st, j, _ = req("GET", "/api/auth/status", cookies={"tj_session": t1})
chk(j.get("csrf") == c1, "A2 /api/auth/status 와 /api/setup/status 가 같은 세션 CSRF 를 줌", j.get("csrf") == c1)
for path in ("/api/setup/prefs", "/api/dust_threshold", "/api/logout"):
    st, j, _ = req("POST", path, {"currency": "USD", "usd": 50}, cookies={"tj_session": t1}, csrf=ss.csrf_token())
    chk(st == 403 and j.get("error") == CSRF_ERR, "A3 로그인 켬 + 설치 토큰 = 403(문구 종전 그대로) — " + path, (st, j))
st, j, _ = req("POST", "/api/setup/prefs", {"currency": "USD"}, cookies={"tj_session": t1}, csrf=c1)
chk(st == 200 and j.get("ok"), "A4 세션 CSRF = 통과", (st, j))
st, sc = login(cookies={"tj_session": t1})
t2 = cookie_val(sc, "tj_session")
chk(st == 200 and t2 and t2 != t1 and LA.check_session(t1) is None, "A5 재로그인 = 새 세션 · 옛 세션 폐기", st)
st, j, _ = req("POST", "/api/setup/prefs", {"currency": "USD"}, cookies={"tj_session": t2}, csrf=c1)
chk(st == 403 and j.get("error") == CSRF_ERR, "A6 재로그인 뒤 옛 CSRF = 403 '새로고침'(화면이 이것을 보고 다시 받음)", (st, j))
st, j, _ = req("GET", "/api/setup/status", cookies={"tj_session": t2})
c2 = j.get("csrf")
st2, j2, _ = req("POST", "/api/setup/prefs", {"currency": "USD"}, cookies={"tj_session": t2}, csrf=c2)
chk(c2 and c2 != c1 and st2 == 200 and j2.get("ok"), "A7 상태를 다시 받으면 새 CSRF → 통과", (c2 != c1, st2, j2))
st, j, _ = req("POST", "/api/setup/prefs", {"currency": "USD"}, cookies={"tj_session": t2}, csrf=c1)
chk(st == 403, "A8 옛 CSRF 는 계속 거부(다시 받기 전 값으로는 안 열림)", st)


class FakeH:
    def __init__(self, tok=None):
        self.headers = email.message.Message()
        self.headers["Host"], self.headers["Origin"], self.headers["Content-Type"] = HOST, ORIGIN, "application/json"
        if tok:
            self.headers["X-TJ-CSRF"] = tok
        self.sent = []

    def _send(self, code, obj, *a, **k):
        self.sent.append((code, obj))


for name, tok, mode, want in (("세션 모드 + 세션 CSRF", c2, "session", True), ("세션 모드 + 설치 토큰", ss.csrf_token(), "session", False),
                              ("설치 모드 + 설치 토큰", ss.csrf_token(), "install", True), ("설치 모드 + 세션 CSRF", c2, "install", False)):
    fh = FakeH(tok)
    if mode == "session":
        csrf_gate.use_session(fh, c2)
    ok = http_post.PostMixin._write_guard(fh)
    chk(ok is want and (want or (fh.sent and fh.sent[0][0] == 403 and fh.sent[0][1].get("error") == CSRF_ERR)),
        "A9 쓰기 공통 관문(_write_guard) — " + name + " = " + ("통과" if want else "403 종전 문구"), (ok, fh.sent))

print("[B] 로그인 꺼짐 — 설치 토큰(종전)")
LA.init(dict(CFG, web={"port": 8023, "bind": "loopback", "login": {"enabled": False}}))
st, j, _ = req("GET", "/api/setup/status")
chk(st == 200 and j.get("csrf") == ss.csrf_token(), "B1 상태 조회 csrf = 설치 토큰", st)
st, j, _ = req("POST", "/api/setup/prefs", {"currency": "USD"}, csrf=ss.csrf_token())
chk(st == 200 and j.get("ok"), "B2 설치 토큰으로 쓰기 통과", (st, j))
st, j, _ = req("POST", "/api/setup/prefs", {"currency": "USD"}, csrf=c2)
chk(st == 403 and j.get("error") == CSRF_ERR, "B3 로그인 꺼짐 + 세션 CSRF 값 = 403(설치 토큰만)", (st, j))
fh = FakeH()
fh.client_address = ("127.0.0.1", 1)
csrf_gate.use_session(fh, "stale")
LA.handle(fh, "GET", "/__nothing__")
chk(fh.tj_csrf_mode == "install" and fh.tj_csrf_expect == "", "B4 login_auth.handle = 요청마다 설치 토큰 모드로 시작(keep-alive 처리기 재사용)", vars(fh).get("tj_csrf_mode"))

print("[C] HTTPS — __Host- 쿠키")
LA.init(dict(CFG, web={"port": 8023, "bind": "loopback", "login": {"secure_cookie": True}}))
st, sc = login()
th = cookie_val(sc, "__Host-tj_session")
new_c = next((s for s in sc if s.startswith("__Host-tj_session=")), "")
old_c = next((s for s in sc if s.startswith("tj_session=")), "")
chk(st == 200 and th and "Secure" in new_c and "Path=/" in new_c and "Domain" not in new_c, "C1 HTTPS 로그인 = __Host-tj_session(Secure · Path=/ · Domain 없음)", sc)
chk(old_c.startswith("tj_session=;") and "Max-Age=0" in old_c, "C2 HTTPS 로그인 = 옛 이름 tj_session 지움(A6 전 쿠키 정리)", sc)
st, j, sc = req("GET", "/api/setup/status", cookies={"__Host-tj_session": th})
chk(st == 200 and j.get("csrf") == LA._sess_csrf(th), "C3 HTTPS + __Host-tj_session = 세션", st)
st, j, sc = req("GET", "/api/setup/status", cookies={"tj_session": th})
names = sorted(s.split("=", 1)[0] for s in sc if "Max-Age=0" in s)
chk(st == 401 and names == ["__Host-tj_session", "tj_session"], "C4 HTTPS 에서 tj_session(밀어 넣은 이름) = 세션 아님 · 401 + 두 이름 지움", (st, sc))
st, j, sc = req("POST", "/api/logout", cookies={"__Host-tj_session": th}, csrf=LA._sess_csrf(th))
names = sorted(s.split("=", 1)[0] for s in sc if "Max-Age=0" in s)
chk(st == 200 and names == ["__Host-tj_session", "tj_session"] and all("Secure" in s for s in sc if s.startswith("__Host-")),
    "C5 HTTPS 로그아웃 = 두 이름 다 지움(__Host- 지우기도 Secure)", (st, sc))
LA.init(CFG)
st, sc = login()
tp = cookie_val(sc, "tj_session")
chk(st == 200 and tp and not cookie_val(sc, "__Host-tj_session") and len([c for c in sc if "_session=" in c]) == 1,
    "C6 HTTP 로그인 = 세션 쿠키 tj_session 하나(종전 그대로 · 3막 A1b 기기 쿠키 tj_device 는 따로 — test_login_device)", sc)
st, j, _ = req("GET", "/api/setup/status", cookies={"__Host-tj_session": tp})
chk(st == 401, "C7 HTTP 에서 __Host-tj_session 이름은 세션으로 안 읽음", st)
SRV.shutdown()
SRV.server_close()

print("[D] 화면 재시도(node · 지연 fetch)")
JS = r'''import fs from 'node:fs';
const APP = fs.readFileSync(process.env.TJ_TEST_APP, 'utf8'), SETUP = fs.readFileSync(process.env.TJ_TEST_SETUP, 'utf8'), IX = fs.existsSync(process.env.TJ_TEST_IX) ? fs.readFileSync(process.env.TJ_TEST_IX, 'utf8') : '';   // 공개판 = 옛 화면 없음
const cutOf = SRC => (a, b) => { const i = SRC.indexOf(a), j = i < 0 ? -1 : SRC.indexOf(b, i + 1); if (i < 0 || j < 0) throw new Error('블록을 못 찾음: ' + a.slice(0, 50)); return SRC.slice(i, j); };
const cut = cutOf(APP), cutS = cutOf(SETUP);
const R = []; const chk = (ok, msg, d) => R.push([!!ok, msg, d]);
const ERR = 'CSRF 토큰 불일치 — 페이지를 새로고침하세요';
const delay = ms => new Promise(res => setTimeout(res, ms));
function resp(status, data) { const o = { status, ok: status >= 200 && status < 300, json: async () => data, text: async () => JSON.stringify(data) }; o.clone = () => resp(status, data); return o; }
// 가짜 서버: 지금 받는 토큰 = srv.cur · 상태 조회는 늦게(40ms) 답함 · POST 는 헤더가 srv.cur 면 200, 아니면 403 CSRF(srv.other = CSRF 아닌 403)
function server(cur) {
  const srv = { cur, posts: [], status: 0, other: false };
  srv.fetch = async (url, o) => {
    if (o && o.method === 'POST') {
      const h = (o.headers || {})['X-TJ-CSRF'] || ''; srv.posts.push(h);
      if (srv.other) return resp(403, { ok: false, error: '출처(Origin) 확인 실패 — 같은 화면에서만 요청할 수 있습니다' });
      return h && h === srv.cur ? resp(200, { ok: true }) : resp(403, { ok: false, error: ERR });
    }
    srv.status++; await delay(40);
    return resp(200, { ok: true, enabled: true, authed: true, csrf: srv.cur, exp: 1, sessions: 1, idleDays: 7, pwMin: 10 });
  };
  return srv;
}
const flush = async () => { await delay(150); };
(async () => {
  { // app.js csrf() + post()
    const mk = (srv, setupSt) => {
      const S = {}, toasts = [], win = { __tjSetup: { U: { st: setupSt } } };
      const deps = { S, fetch: srv.fetch, window: win, optFor: () => null, optFail: () => {}, optOk: () => {}, toast: (m, e) => toasts.push([m, !!e]), refresh: () => {}, onUnauthorized: () => {} };
      const api = new Function(...Object.keys(deps), cut('  async function csrf(force) {', '  const OPT =') + '\nreturn {csrf, post};')(...Object.values(deps));
      return { S, toasts, win, api };
    };
    let srv = server('NEW'), h = mk(srv, { csrf: 'OLD' });
    let d = await h.api.post('/api/plan', { key: 'k' }, 'ok');
    chk(d && d.ok && JSON.stringify(srv.posts) === '["OLD","NEW"]' && srv.status === 1, 'post(): 403 CSRF → 상태를 다 받은 뒤 NEW 로 1번 다시 → 성공', srv.posts);
    chk(h.win.__tjSetup.U.st.csrf === '' && h.S.csrf === 'NEW', 'post(): 두 캐시 — setup U.st.csrf 비움 · S.csrf = 새 값', [h.win.__tjSetup.U.st.csrf, h.S.csrf]);
    d = await h.api.post('/api/plan', { key: 'k' }, 'ok');
    chk(d && d.ok && srv.posts.length === 3 && srv.posts[2] === 'NEW' && srv.status === 1, 'post(): 다음 쓰기는 새 값 캐시로 바로(재조회 없음)', srv.posts);
    const s2 = server('x'); s2.fetch = async (u, o) => { if (o && o.method === 'POST') { s2.posts.push((o.headers || {})['X-TJ-CSRF']); return resp(403, { ok: false, error: ERR }); } s2.status++; await delay(40); return resp(200, { ok: true, csrf: 'STILL-BAD' }); };
    h = mk(s2, { csrf: 'OLD' });
    d = await h.api.post('/api/plan', { key: 'k' }, 'ok');
    chk(d === null && s2.posts.length === 2 && s2.status === 1 && h.toasts.some(t => t[1] && /CSRF/.test(t[0])), '계속 403 CSRF = POST 2번에서 끝(무한 반복 없음) · 오류 토스트', [s2.posts, h.toasts]);
    const s3 = server('OLD'); s3.other = true; h = mk(s3, { csrf: 'OLD' });
    d = await h.api.post('/api/plan', { key: 'k' }, 'ok');
    chk(d === null && s3.posts.length === 1 && s3.status === 0, 'CSRF 아닌 403(출처) = 다시 안 함', s3.posts);
    const s4 = server('OLD'); h = mk(s4, null); h.S.csrf = 'OLD';
    d = await h.api.post('/api/plan', {}, 'ok');
    chk(d && d.ok && s4.posts.length === 1 && s4.status === 0, '맞는 토큰 = 종전 그대로 1번 · 상태 조회 없음', s4);
  }
  { // app.js setDust (csrf 포함)
    const srv = server('NEW'), S = { hold: {} }, toasts = [], win = { __tjSetup: { U: { st: { csrf: 'OLD' } } } };
    const deps = { S, fetch: srv.fetch, window: win, LS: { set: () => {} }, render: () => {}, toast: (m, e) => toasts.push([m, !!e]), refresh: () => {},
      optFor: () => null, optFail: () => {}, optOk: () => {}, onUnauthorized: () => {} };
    const api = new Function(...Object.keys(deps), cut('  async function csrf(force) {', '  const OPT =') + cut('  function setDust(v) {', '  function savePlan(') + '\nreturn {setDust};')(...Object.values(deps));
    api.setDust(30); await flush();
    chk(JSON.stringify(srv.posts) === '["OLD","NEW"]' && toasts.length === 1 && !toasts[0][1], 'setDust: 403 CSRF → NEW 로 1번 다시 → 저장 토스트', [srv.posts, toasts]);
  }
  { // tab_rcpt postJ
    for (const [nm, cur, want] of [['바뀜', 'NEW', '["OLD","NEW"]'], ['같음', 'OLD', '["OLD"]']]) {
      const srv = server(cur); let tok = 'OLD';
      const csrf = async force => { if (force) { const r = await srv.fetch('/api/setup/status'); tok = (await r.json()).csrf; } return tok; };
      const postJ = new Function('csrf', 'fetch', 'onUnauthorized', cut('  async function postJ(path, body) {', '  function rcLoad(force) {') + '\nreturn postJ;')(csrf, srv.fetch, () => {});
      const x = await postJ('/api/receipt_eval', {});
      chk(x.st === 200 && JSON.stringify(srv.posts) === want, 'postJ(' + nm + '): 403 CSRF 면 새로 받은 토큰으로 1번만 다시', srv.posts);
    }
  }
  { // setup.js chAutoSet — load() 가 늦게 끝남
    const srv = server('NEW'), U = { st: { csrf: 'OLD' }, ch: { autoOffOn: true } }, toasts = [];
    const deps = { isLocked: () => false, U, fill: () => {}, fetch: srv.fetch, window: {}, toast: (m, e) => toasts.push([m, !!e]), loadChains: async () => {},
      load: async () => { await delay(40); U.st = { csrf: srv.cur }; } };
    const f = new Function(...Object.keys(deps), cutS('  async function chAutoSet(on) {', '  function chainsHTML() {') + '\nreturn chAutoSet;')(...Object.values(deps));
    await f(false);
    chk(JSON.stringify(srv.posts) === '["OLD","NEW"]' && U.ch.autoOffOn === false && toasts.length === 1 && !toasts[0][1], 'chAutoSet: 403 CSRF → 상태 다시 받은 뒤 NEW 로 1번 다시', [srv.posts, toasts]);
    srv.cur = 'NEVER'; let nl = 0;
    const f2 = new Function(...Object.keys(deps), cutS('  async function chAutoSet(on) {', '  function chainsHTML() {') + '\nreturn chAutoSet;')(...Object.values(Object.assign({}, deps, { load: async () => { nl++; await delay(5); U.st = { csrf: 'STILL-BAD' }; } })));
    srv.posts.length = 0; await f2(true);
    chk(srv.posts.length === 2 && nl === 1 && toasts.length === 2 && toasts[1][1], 'chAutoSet: 계속 403 CSRF = 2번에서 끝 · 오류 토스트', [srv.posts, nl, toasts]);
  }
  { // tab_set authLoad·authRefresh·loginBody·authPost·csrfDrop
    const mk = (srv, auth) => {
      const S = { tab: 'settings', locked: false, drafts: {}, csrf: 'APPOLD' }, win = { __tjSetup: { U: { st: { csrf: 'SETUPOLD' } } } }; let rv = 0;
      if (auth) S.auth = auth;
      const deps = { S, fetch: srv.fetch, window: win, renderView: () => { rv++; }, esc: s => String(s), num: x => String(x), fmtTs: x => 'T' + x, errTxt: s => s,
        sxIt: (c, t, d, p) => '[IT ' + t + ' | ' + d + ' | ' + (p || '') + ']', sxPill: (k, t) => '<' + t + '>', sxSlotWait: () => '[WAIT]' };
      const api = new Function(...Object.keys(deps), cut('  function authLoad(force) {', '  function wipeLocal() {') + '\nreturn {authLoad, authRefresh, loginBody, authPost};')(...Object.values(deps));
      return { S, win, api, rv: () => rv };
    };
    let srv = server('NEW'); const d0 = { ok: true, enabled: true, authed: true, csrf: 'OLD', exp: 1, sessions: 1, idleDays: 7, pwMin: 10 };
    let h = mk(srv, { st: 'ok', t: Date.now(), d: d0 });
    const c0 = h.api.authLoad();
    const html1 = h.api.loginBody();
    chk(c0 === h.S.auth && typeof c0.then !== 'function' && srv.status === 0 && html1.indexOf('[IT 이 기기 | ') === 0 && html1.indexOf('<로그인>') > 0,
      'loginBody(캐시 있음) = 조회 없이 캐시로 바로 그림 · authLoad 는 캐시 객체를 동기로 돌려줌', [srv.status, html1.slice(0, 80)]);
    const x = await h.api.authPost('/api/auth/logout_all', {});
    chk(x.st === 200 && x.d.ok && JSON.stringify(srv.posts) === '["OLD","NEW"]' && srv.status === 1, 'authPost: 403 CSRF → authRefresh 조회가 끝난 뒤 NEW 로 1번 다시', [srv.posts, srv.status]);
    chk(h.S.auth.d.csrf === 'NEW' && h.S.auth.st === 'ok' && h.S.csrf === '' && h.win.__tjSetup.U.st.csrf === '', 'authPost: 상태 캐시 = 새 값 · 앱 쓰기 캐시 둘(S.csrf · U.st.csrf) 비움', [h.S.auth.d.csrf, h.S.csrf, h.win.__tjSetup.U.st.csrf]);
    const s2 = server('x'); s2.fetch = async (u, o) => { if (o && o.method === 'POST') { s2.posts.push((o.headers || {})['X-TJ-CSRF']); return resp(403, { ok: false, error: ERR }); } s2.status++; await delay(40); return resp(200, { ok: true, csrf: 'BAD' }); };
    h = mk(s2, { st: 'ok', t: Date.now(), d: Object.assign({}, d0) });
    const y = await h.api.authPost('/api/logout', {});
    chk(y.st === 403 && s2.posts.length === 2 && s2.status === 1, 'authPost: 계속 403 CSRF = 2번에서 끝(무한 반복 없음)', [s2.posts, s2.status]);
    srv = server('NEW'); h = mk(srv, null);
    const html0 = h.api.loginBody();
    chk(html0 === '[WAIT]' && h.S.auth.st === 'load' && srv.status === 1, 'loginBody(캐시 없음) = 기다림 칸 · 조회 1번 시작', [html0, srv.status]);
    await flush();
    const html2 = h.api.loginBody();
    chk(h.S.auth.st === 'ok' && h.rv() === 1 && srv.status === 1 && html2.indexOf('[IT 이 기기 | ') === 0, 'loginBody: 조회가 끝나면 그 화면 1번 다시 그림 · 60초 안엔 다시 안 받음', [h.S.auth.st, h.rv(), srv.status]);
  }
  if (IX) { // web/index.html getTok 감싸개(공개판엔 옛 화면 파일이 없어 건너뜀)
    const m = IX.match(/\(function\(\)\{var f0=window\.fetch[\s\S]*?\}\)\(\);/);
    for (const [nm, cur, other, want] of [['바뀜', 'NEW', false, '["OLD","NEW"]'], ['계속 거부', 'NEVER', false, '["OLD","OLD2"]'], ['출처 403', 'OLD', true, '["OLD"]'], ['같음', 'OLD', false, '["OLD"]']]) {
      const srv = server(cur); srv.other = other; let n = 0;
      const toks = ['OLD', cur === 'NEVER' ? 'OLD2' : cur];
      const win = { fetch: async (u, o) => { if (o && o.method === 'POST') return srv.fetch(u, o); await delay(40); return resp(200, { ok: true, csrf: toks[Math.min(n++, 1)] }); } };
      new Function('window', m[0])(win);
      const r = await win.fetch('/api/plan', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      chk(JSON.stringify(srv.posts) === want && (nm === '바뀜' || nm === '같음' ? r.status === 200 : r.status === 403), 'index.html getTok(' + nm + '): 403 CSRF 면 토큰 새로 받아 1번만 다시', [srv.posts, r.status]);
    }
  }
  for (const [ok, msg, d] of R) console.log((ok ? 'PASS ' : 'FAIL ') + msg + (ok || d === undefined ? '' : '  — ' + JSON.stringify(d).slice(0, 600)));
  console.log('RESULT ' + R.filter(x => x[0]).length + '/' + R.length);
})().catch(e => { console.log('FAIL 실행 오류 ' + (e && e.stack || e)); console.log('RESULT 0/1'); });
'''
NODE = T.node_bin("화면 재시도 시험")
if NODE:
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_")}
    env.update(TJ_TEST_APP=T.app_js_path(), TJ_TEST_SETUP=os.path.join(T.ROOT, "web", "v2", "setup.js"), TJ_TEST_IX=os.path.join(T.ROOT, "web", "index.html"))
    p = subprocess.run([NODE, "--input-type=module", "-"], input=JS, env=env, cwd=T.TMP, capture_output=True, text=True, encoding="utf-8", timeout=120)
    lines = (p.stdout or "").splitlines()
    got = [ln for ln in lines if ln.startswith(("PASS ", "FAIL "))]
    for ln in got:
        T.chk(ln.startswith("PASS "), ln[5:])
    want_n = 21 if os.path.exists(env["TJ_TEST_IX"]) else 17
    T.chk(p.returncode == 0 and len(got) == want_n and any(re.match(r"RESULT \d+/\d+$", ln) for ln in lines), "node 화면 재시도 시험이 끝까지 돌았음(검사 %d개)" % want_n, (len(got), (p.stderr or "")[-600:]))
T.finish()
