#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

import nodekeys as NK  # noqa: E402
import onboarding  # noqa: E402
import settings_store as ss  # noqa: E402

chk = T.chk

print("[S] 서버 keys/nodeplan")
r = onboarding._dispatch("keys/nodeplan", {"provider": "ankr", "plan": "paid", "share": 25, "month": 8_000_000})
chk(r.get("ok") and NK.plans()["ankr"] == {"plan": "paid", "share": 25, "month": 8_000_000}, "S1 세 칸 다 보냄 = 종전 그대로", (r, NK.plans()["ankr"]))
r = onboarding._dispatch("keys/nodeplan", {"provider": "ankr", "share": 50})
chk(r.get("ok") and NK.plans()["ankr"] == {"plan": "paid", "share": 50, "month": 8_000_000}, "S2 비율만 = 요금제·월 한도 그대로", (r, NK.plans()["ankr"]))
r = onboarding._dispatch("keys/nodeplan", {"provider": "ankr", "month": None})
chk(r.get("ok") and NK.plans()["ankr"] == {"plan": "paid", "share": 50, "month": None}, "S3 월 한도만(null = 비움) = 비율 그대로", (r, NK.plans()["ankr"]))
r = onboarding._dispatch("keys/nodeplan", {"provider": "ankr", "plan": "free"})
chk(r.get("ok") and NK.plans()["ankr"] == {"plan": "free", "share": 50, "month": None}, "S4 요금제만 = 비율 그대로", (r, NK.plans()["ankr"]))
sp0 = json.dumps(ss.read_settings().get("node_plans"), sort_keys=True)
for body, why in (({"provider": "ankr", "share": 30}, "비율 30"), ({"provider": "ankr", "month": 0}, "월 한도 0"), ({"provider": "ankr", "plan": "gold"}, "요금제 이상"),
                  ({"provider": "ankr", "share": True}, "비율 True"), ({"provider": "ankr", "month": "100"}, "월 한도 글자")):
    r = T.safe(onboarding._dispatch, "keys/nodeplan", body)
    chk(isinstance(r, dict) and r.get("ok") is False and json.dumps(ss.read_settings().get("node_plans"), sort_keys=True) == sp0, "S5 거부(설정 무변): " + why, r)
r = onboarding._dispatch("keys/nodeplan", {"provider": "ankr", "fresh": True})
chk(r.get("ok") and NK.plans()["ankr"].get("fresh_since") and NK.plans()["ankr"]["share"] == 50, "S6 '새로 받은 키'만 = 요금제 칸 그대로", NK.plans()["ankr"])

print("[C] 화면 setup.js")
JS = r'''
import fs from 'node:fs';
const APP = fs.readFileSync(process.env.TJ_TEST_APP, 'utf8'), SU = fs.readFileSync(process.env.TJ_TEST_SETUP, 'utf8');
const cutOf = SRC => (a, b) => { const i = SRC.indexOf(a), j = i < 0 ? -1 : SRC.indexOf(b, i + 1); if (i < 0 || j < 0) throw new Error('블록을 못 찾음: ' + a.slice(0, 50)); return SRC.slice(i, j); };
const cut = cutOf(APP), cutU = cutOf(SU), opt = f => (a, b) => { try { return f(a, b); } catch (e) { return ''; } };
const HELP = opt(cut)('  const sync = {', '  const uiPopBox = ');
const R = []; const chk = (ok, msg, d) => R.push([!!ok, msg, ok ? undefined : d]);
const tick = async (n) => { for (let i = 0; i < (n || 10); i++) await new Promise(r => setTimeout(r, 0)); };
const st = share => ({ ok: true, csrf: 'C', nodes: { ankr: { name: 'Ankr', plan: 'paid', share, month: 8000000 } } });
function harness() {
  const U = { st: null, err: null, busy: {}, d: {}, tg: { phase: 'idle' } }, gets = [], posts = [];
  const sync = HELP ? new Function('S', HELP + 'return sync;')({}) : null;
  const resp = j => ({ status: 200, ok: true, json: async () => j });
  const fetch = (u, o) => {
    if (o && o.method === 'POST') return new Promise(res => posts.push({ body: JSON.parse(o.body), res: j => res(resp(j)) }));
    return new Promise(res => gets.push(j => res(resp(j))));
  };
  const deps = { U, window: { TJ: sync ? { sync } : {}, dispatchEvent: () => {} }, isLocked: () => false, fetch, toast: () => {}, render: () => {}, startPoll: () => {},
    Event: function () {}, setTimeout };
  const body = opt(cutU)('  const WG = {};', '  async function load() {') + cutU('  async function load() {', '  function toast(msg, err, ms) {') + cutU('  async function nodePlanSave(p, patch) {', '  function fieldsHTML(')
    + '  async function refreshStatus() { await load(); }\n';
  const api = new Function(...Object.keys(deps), body + '\nreturn { load, nodePlanSave, api };')(...Object.values(deps));
  return { U, gets, posts, api };
}
function harness2() {   // POST 응답을 본문 그대로(상태 · CSRF 403 모양) 돌려줄 수 있게
  const U = { st: null, err: null, busy: {}, d: {}, tg: { phase: 'idle' } }, gets = [], posts = [];
  const sync = HELP ? new Function('S', HELP + 'return sync;')({}) : null;
  const resp = (st, j) => ({ status: st, ok: st < 300, json: async () => j });
  const fetch = (u, o) => {
    if (o && o.method === 'POST') return new Promise(res => posts.push({ body: JSON.parse(o.body), tok: (o.headers || {})['X-TJ-CSRF'], res: (st, j) => res(resp(st, j)) }));
    return new Promise(res => gets.push(j => res(resp(200, j))));
  };
  const deps = { U, window: { TJ: sync ? { sync } : {}, dispatchEvent: () => {} }, isLocked: () => false, fetch, toast: () => {}, render: () => {}, startPoll: () => {},
    Event: function () {}, setTimeout };
  const body = opt(cutU)('  const WG = {};', '  async function load() {') + cutU('  async function load() {', '  function toast(msg, err, ms) {') + cutU('  async function nodePlanSave(p, patch) {', '  function fieldsHTML(')
    + '  async function refreshStatus() { await load(); }\n';
  const api = new Function(...Object.keys(deps), body + '\nreturn { load, nodePlanSave, api };')(...Object.values(deps));
  return { U, gets, posts, api };
}
(async () => {
  try {
    { const h = harness(); h.api.load(); await tick(); h.gets[0](st(10)); await tick();
      chk(h.U.st && h.U.st.nodes.ankr.share === 10, 'C0 첫 상태 = 그대로 받음', h.U.st);
      h.api.load(); await tick();                         // 주기 읽기(느림 — 저장 전 비율 10)
      const p = h.api.nodePlanSave('ankr', { share: 25 }); await tick();
      chk(h.posts.length === 1 && JSON.stringify(h.posts[0].body) === JSON.stringify({ provider: 'ankr', share: 25 }), 'C1 비율 칩 = 바꾼 칸만 보냄', h.posts[0] && h.posts[0].body);
      h.posts[0].res({ ok: true }); await tick();
      h.gets[2](st(25)); await tick();                    // 저장 뒤 refreshStatus 읽기(새 값)
      await p;
      h.gets[1](st(10)); await tick();                    // 저장 전에 떠난 느린 읽기가 늦게 도착
      chk(h.U.st.nodes.ankr.share === 25, 'C2 저장 전 느린 읽기(옛 비율) 버림 — 방금 바꾼 비율 유지', h.U.st.nodes.ankr); }
    { const h = harness(); h.api.load(); await tick(); h.gets[0](st(10)); await tick();
      h.api.load(); h.api.load(); await tick();
      h.gets[2](st(50)); await tick(); h.gets[1](st(10)); await tick();
      chk(h.U.st.nodes.ankr.share === 50, 'C3 나중에 보낸 읽기가 먼저 반영 = 먼저 보낸 늦은 읽기 버림', h.U.st.nodes.ankr); }
    { const h = harness(); h.api.load(); await tick(); h.gets[0](st(10)); await tick();
      const p = h.api.nodePlanSave('ankr', { month: null }); await tick();
      chk(JSON.stringify(h.posts[0].body) === JSON.stringify({ provider: 'ankr', month: null }), 'C4 월 한도 = {provider, month} 만', h.posts[0].body);
      h.posts[0].res({ ok: true }); await tick(); h.gets[1](st(10)); await p; }
  } catch (e) { chk(false, '실행 오류', String((e && e.stack) || e).slice(0, 400)); }
  try {
    { const h = harness2(); h.api.load(); await tick(); h.gets[0](st(10)); await tick();
      const pt = h.api.api('keys/test', { group: 'x' }); await tick();            // 느린 연결 테스트(쓰기 세대 걸림)
      const ps = h.api.nodePlanSave('ankr', { share: 25 }); await tick();
      h.posts[1].res(200, { ok: true }); await tick(); h.gets[1](st(25)); await tick(); await ps;   // 저장 뒤 읽기 = 테스트가 걸려 있어 버려짐
      h.posts[0].res(200, { ok: true, test: { ok: true } }); await pt; await tick();
      if (h.gets[2]) { h.gets[2](st(25)); await tick(); }
      chk(h.U.st.nodes.ankr.share === 25, '2차 겹친 쓰기 뒤 버린 읽기 = 마지막 쓰기 끝에 새로 읽어 정본(25)', [h.U.st.nodes.ankr, h.gets.length]); }
    { const h = harness2(); h.api.load(); await tick(); h.gets[0](st(10)); await tick();
      h.api.load(); await tick();                                                   // 옛 상태 읽기(OLD 토큰) 떠 있음
      const pa = h.api.api('keys/nodeplan', { provider: 'ankr', share: 25 }); await tick();
      h.posts[0].res(403, { ok: false, error: 'CSRF 토큰 불일치' }); await tick();       // 토큰 바뀜 → U.st = null → 새 읽기
      h.gets[1](Object.assign(st(10), { csrf: 'OLD' })); await tick();                  // 옛 읽기가 먼저 도착
      if (h.gets[2]) { h.gets[2](Object.assign(st(10), { csrf: 'NEW' })); await tick(); }
      chk(h.posts.length === 2 && h.posts[1].tok === 'NEW', '2차 CSRF 다시 받기 = 옛 읽기가 먼저 와도 새 토큰으로 다시 보냄', h.posts.map(x => x.tok));
      if (h.posts[1]) h.posts[1].res(200, { ok: true }); await pa; }
  } catch (e) { chk(false, '2차 실행 오류', String((e && e.stack) || e).slice(0, 400)); }
  try {
    { const h = harness2(); h.api.load(); h.api.load(); await tick();
      h.gets[1](Object.assign(st(25), { csrf: 'NEW' })); await tick(); h.gets[0](Object.assign(st(10), { csrf: 'OLD' })); await tick();
      chk(h.U.st.nodes.ankr.share === 25 && h.U.st.csrf === 'NEW', '3차 정본 없을 때 보낸 두 읽기 = 순번 지킴(나중 반영 뒤 늦은 옛 읽기 버림)', [h.U.st.nodes.ankr, h.U.st.csrf]); }
    { const h = harness2(); h.api.load(); await tick(); h.gets[0](st(10)); await tick();
      const pt = h.api.api('keys/test', { group: 'x' }); await tick();
      const ps = h.api.nodePlanSave('ankr', { share: 25 }); await tick();
      h.posts[1].res(200, { ok: true }); await tick();                 // 저장 끝 → 뒤 읽기(gets[1]) 떠남(테스트 걸림 = 버려질 읽기)
      h.posts[0].res(200, { ok: true, test: { ok: true } }); await pt; await tick();   // 마지막 쓰기(테스트)가 읽기보다 먼저 끝남
      h.gets[1](st(25)); await tick(); await ps;                        // 버려짐 → 쓰기 없음 = 바로 새로 읽어야 함
      if (h.gets[2]) { h.gets[2](st(25)); await tick(); }
      chk(h.U.st.nodes.ankr.share === 25 && h.gets.length >= 3, '3차 쓰기가 다 끝난 뒤 버린 읽기 = 바로 새로 읽어 정본(25)', [h.U.st.nodes.ankr, h.gets.length]); }
  } catch (e) { chk(false, '3차 실행 오류', String((e && e.stack) || e).slice(0, 400)); }
  console.log(JSON.stringify(R));
})();
'''
node = T.node_bin("화면 setup.js 요금제")
if node:
    v2 = os.path.join(T.ROOT, "web", "v2")
    env = dict(os.environ, TJ_TEST_APP=T.app_js_path(), TJ_TEST_SETUP=os.path.join(v2, "setup.js"))
    p = subprocess.run([node, "--input-type=module", "-"], input=JS, capture_output=True, text=True, timeout=60, env=env)
    out = (p.stdout or "").strip().splitlines()
    if p.returncode != 0 or not out:
        chk(False, "node 실행", (p.stderr or "")[-1500:])
    else:
        for ok, msg, *d in json.loads(out[-1]):
            chk(ok, msg, d[0] if d else None)
T.finish()
