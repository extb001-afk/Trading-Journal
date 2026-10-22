#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import http.client  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

with open(os.path.join(T.ROOT, "config.example.json"), encoding="utf-8") as f:
    CFG = json.load(f)
CFG["wallets"], CFG["exchange_addresses"] = [], []
CFG["web"] = {"port": 8023, "bind": "192.168.0.10", "login": {"enabled": True}}
CFG.setdefault("balance_check", {})["enabled"] = False
with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump(CFG, f, ensure_ascii=False)

import login_auth as LA  # noqa: E402
import settings_store as ss  # noqa: E402
import web  # noqa: E402

chk = T.chk
LA.init(CFG)
PW = "Synthetic-Otter-4417"
LA.set_password(PW, iters=200_000)


FAKE_IP = "192.168.0.20"


class H(web.Handler):
    def setup(self):
        super().setup()
        self.client_address = (FAKE_IP, 50000)


SRV = ThreadingHTTPServer(("127.0.0.1", 0), H)
PORT = SRV.server_address[1]
threading.Thread(target=SRV.serve_forever, daemon=True, name="t-lan-csrf").start()
HOST = "192.168.0.10:%d" % PORT
ORIGIN = "http://" + HOST


def req(method, path, body=None, cookie=None, csrf=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=60)
    h = {"Host": HOST}
    if method == "POST":
        h.update({"Origin": ORIGIN, "Content-Type": "application/json"})
    if csrf:
        h["X-TJ-CSRF"] = csrf
    if cookie:
        h["Cookie"] = cookie
    c.request(method, path, body=json.dumps(body or {}).encode() if method == "POST" else None, headers=h)
    r = c.getresponse()
    raw = r.read()
    sc = r.msg.get_all("Set-Cookie") or []
    c.close()
    try:
        j = json.loads(raw.decode() or "null")
    except ValueError:
        j = None
    return r.status, j, sc


print("[S] 서버 계약")
st, j, sc = req("POST", "/api/login", {"password": PW})
chk(st == 200 and sc, "S1 LAN 로그인 200 · 세션 쿠키", st)
CK = "; ".join(s.split(";")[0] for s in sc)
st, j, _ = req("GET", "/api/setup/status", cookie=CK)
chk(st == 403, "S2 LAN /api/setup/status = 403(루프백·테일넷 전용 — 종전 그대로)", st)
st, j, _ = req("GET", "/api/auth/status", cookie=CK)
chk(st == 200 and (j or {}).get("authed") and (j or {}).get("csrf"), "S3 LAN /api/auth/status = 세션 CSRF", st)
tok = ss.csrf_token()
chk(bool(tok), "S4 설치 토큰 있음(합성 상태)", None)
st, j, _ = req("POST", "/api/dust_threshold", {"usd": 10}, cookie=CK, csrf=tok)
chk(st == 403, "S5 설치 토큰 쓰기 = 403(로그인 켬 · 종전 그대로)", st)

print("[W][U] 화면 csrf()·post() (node)")
JS = r'''
import fs from 'node:fs';
import http from 'node:http';
const APP = fs.readFileSync(process.env.TJ_TEST_APP, 'utf8');
const cut = (a, b) => { const i = APP.indexOf(a), j = i < 0 ? -1 : APP.indexOf(b, i + 1); if (i < 0 || j < 0) throw new Error('블록을 못 찾음: ' + a.slice(0, 50)); return APP.slice(i, j); };
const R = []; const chk = (ok, msg, d) => R.push([!!ok, msg, ok ? undefined : d]);
const [PORT, HOST, CK] = [+process.env.T_PORT, process.env.T_HOST, process.env.T_CK];
const seen = [];
// 브라우저 fetch 흉내: 같은 출처(Host·Origin)·쿠키 — node:http 로 시험 서버에
const realFetch = (u, o) => new Promise((res, rej) => {
  o = o || {}; const m = (o.method || 'GET').toUpperCase(), h = Object.assign({ Host: HOST, Cookie: CK }, o.headers || {});
  if (m === 'POST') { h.Origin = 'http://' + HOST; h['Content-Length'] = Buffer.byteLength(o.body || ''); }
  seen.push(m + ' ' + u);
  const q = http.request({ host: '127.0.0.1', port: PORT, path: u, method: m, headers: h }, s => { let b = ''; s.on('data', d => b += d); s.on('end', () => {
    res({ status: s.statusCode, ok: s.statusCode >= 200 && s.statusCode < 300, json: async () => JSON.parse(b), headers: { get: k => s.headers[String(k).toLowerCase()] || null } }); }); });
  q.on('error', rej); if (o.body) q.write(o.body); q.end(); });
const mk = fetch => { const S = {}, toasts = [];
  const deps = { S, fetch, window: {}, optFor: () => null, optFail: () => {}, optOk: () => {}, toast: (m, e) => toasts.push([m, !!e]), refresh: () => {}, onUnauthorized: () => {} };
  const api = new Function(...Object.keys(deps), cut('  async function csrf(force) {', '  const OPT =') + '\nreturn {csrf, post};')(...Object.values(deps));
  return { S, toasts, api }; };
(async () => {
  try {
    const h = mk(realFetch);
    const d = await h.api.post('/api/other_assets/save', { name: 'Synthetic cash', cat: 'cash', cur: 'KRW', memo: '', qty: null, value: 1000, date: '2026-10-20' }, 'ok');
    chk(d && d.ok, 'W1 LAN + 로그인 켬: app.js post() 쓰기 200 ok(세션 CSRF)', [d, h.toasts, seen]);
    chk(seen.indexOf('GET /api/auth/status') >= 0, 'W2 토큰 출처 = /api/auth/status(설정 상태 403 뒤)', seen);
    const resp = (st, j) => ({ status: st, ok: st < 300, json: async () => j });
    const fk = (setup, auth) => async (u) => (u.indexOf('/api/setup/status') === 0 ? setup : auth);
    let u = mk(fk(resp(200, { ok: true, csrf: 'INSTALL' }), resp(200, { ok: true, enabled: false })));
    chk(await u.api.csrf() === 'INSTALL', 'U1 설정 상태가 토큰을 주면 그대로(로그인 꺼짐·루프백 = 종전)', null);
    u = mk(fk(resp(403, { ok: false }), resp(200, { ok: true, enabled: false, csrf: 'NOPE' })));
    chk(await u.api.csrf() === '', 'U2 로그인 꺼짐 = auth 상태에서 토큰 안 받음', null);
    u = mk(fk(resp(403, { ok: false }), resp(200, { ok: true, enabled: true, authed: false })));
    chk(await u.api.csrf() === '', 'U3 세션 없음 = 토큰 없음', null);
    u = mk(fk(resp(403, { ok: false }), resp(200, { ok: true, enabled: true, authed: true, csrf: 'SESS' })));
    chk(await u.api.csrf() === 'SESS' && await u.api.csrf() === 'SESS', 'U4 로그인 켬 + 세션 = 세션 CSRF(캐시)', null);
  } catch (e) { chk(false, '실행 오류', String((e && e.stack) || e).slice(0, 400)); }
  console.log(JSON.stringify(R));
})();
'''
node = T.node_bin("화면 csrf() LAN 쓰기")
if node:
    env = dict(os.environ, TJ_TEST_APP=T.app_js_path(), T_PORT=str(PORT), T_HOST=HOST, T_CK=CK)
    p = subprocess.run([node, "--input-type=module", "-"], input=JS, capture_output=True, text=True, timeout=120, env=env)
    out = (p.stdout or "").strip().splitlines()
    if p.returncode != 0 or not out:
        chk(False, "node 실행", (p.stderr or "")[-1500:])
    else:
        for ok, msg, *d in json.loads(out[-1]):
            chk(ok, msg, d[0] if d else None)
SRV.shutdown()
T.finish()
