#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

JS = r'''
import fs from 'node:fs';
const IDX = fs.readFileSync(process.env.TJ_TEST_INDEX, 'utf8'), APP = fs.readFileSync(process.env.TJ_TEST_APP, 'utf8'),
  HJ = fs.readFileSync(process.env.TJ_TEST_HEALTH, 'utf8');
const cutOf = SRC => (a, b) => { const i = SRC.indexOf(a), j = i < 0 ? -1 : SRC.indexOf(b, i + 1); if (i < 0 || j < 0) throw new Error('블록을 못 찾음: ' + a.slice(0, 50)); return SRC.slice(i, j); };
const lineOf = SRC => a => { const i = SRC.indexOf(a); if (i < 0) throw new Error('줄을 못 찾음: ' + a); return SRC.slice(i, SRC.indexOf('\n', i)); };
const R = []; const chk = (ok, msg, d) => R.push([!!ok, msg, ok ? undefined : d]);
const tick = async (n) => { for (let i = 0; i < (n || 8); i++) await new Promise(r => setTimeout(r, 0)); };
const sec = async (n, f) => { try { await f(); } catch (e) { chk(false, '묶음 ' + n + ' 실행 오류', String((e && e.stack) || e).slice(0, 300)); } };

// 가짜 시계(setTimeout·clearTimeout) — advance(ms) 가 시각이 된 타이머를 차례로 부른다
function clock() {
  let now = 0, id = 0; const q = new Map();
  return { now: () => now, setTimeout: (f, ms) => { q.set(++id, { f, at: now + (ms || 0) }); return id; }, clearTimeout: k => { q.delete(k); },
    advance: ms => { const end = now + ms; for (;;) { let k = null, b = null; for (const [i, t] of q) if (t.at <= end && (!b || t.at < b.at)) { k = i; b = t; }
      if (!b) break; q.delete(k); now = b.at; b.f(); } now = end; }, pending: () => q.size };
}

function wrapper() {
  const c = clock(), calls = [], seen = [];
  const f0 = (u, o) => new Promise((res, rej) => { calls.push({ u, o, res }); if (o && o.signal) o.signal.addEventListener('abort', () => rej(o.signal.reason || new Error('aborted'))); });
  const win = { fetch: f0, AbortController, __tjLoginCheck: r => { seen.push(r); return false; } };
  const code = cutOf(IDX)('(function(){var f0=window.fetch;if(!f0)return;', '\nvar F=null;');
  new Function('window', 'setTimeout', 'clearTimeout', 'AbortController', 'DOMException', code)(win, c.setTimeout, c.clearTimeout, AbortController, DOMException);
  const go = (u, o) => { let st = { done: false, err: null, r: null }; const p = win.fetch(u, o); p.then(r => { st.done = true; st.r = r; }, e => { st.done = true; st.err = e; }); return st; };
  return { c, calls, seen, go };
}

(async () => {
  await sec('A 읽기 20초', async () => {
    const w = wrapper();
    const st = w.go('/api/health', { cache: 'no-store' });
    w.c.advance(19999); await tick();
    chk(!st.done && w.calls.length === 1, 'A 짧은 읽기 = 20초 전에는 기다림', st);
    w.c.advance(1); await tick();
    chk(st.done && st.err && st.err.name === 'TimeoutError' && /20초/.test(st.err.message), 'A 짧은 읽기 = 응답 머리 20초 넘으면 TimeoutError 로 끊음', st.err && [st.err.name, st.err.message]);
    chk(w.calls[0] && w.calls[0].o && w.calls[0].o.cache === 'no-store', 'A 호출부 옵션(cache) 그대로 넘김', w.calls[0] && w.calls[0].o);
    const sh = ['/api/ops', '/api/wallet_reload', '/api/auth/status', '/api/setup/status', '/api/setup/tier?add=1'].map(u => w.go(u));
    const ev = w.go('/api/opsx'), ev2 = w.go('/api/setup/statusx');
    w.c.advance(20000); await tick();
    chk(sh.every(s => s.done && s.err && s.err.name === 'TimeoutError'), 'A 빌드를 안 기다리는 길(정리 요청·재시작 표식·로그인·설정 상태·확인 주기) = 20초', sh.map(s => s.done));
    chk(!ev.done && !ev2.done, 'A 길 이름은 정확히 맞춤(앞부분만 같은 길 = 제한 없음)', [ev.done, ev2.done]);
    const hd = w.go('/api/ops', { method: 'HEAD' });
    w.c.advance(20000); await tick();
    chk(hd.done && hd.err && hd.err.name === 'TimeoutError', 'A HEAD 도 읽기와 같음', hd);
  });
  await sec('A 빌드를 기다리는 읽기 = 제한 없음', async () => {
    const w = wrapper();
    const urls = ['/api/v2/state?slim=1&since=v1', '/api/state', '/api/day_events?date=2001-01-01', '/api/search/ask?q=x', '/api/search?q=x', '/api/other_assets/quote?t=TKJ',
      '/api/receipt_eval?date=2001-01-01&sym=TKJ', '/api/bench', '/api/habits', '/api/curve_hist?range=all', '/api/other_assets', '/api/nft', '/api/alert_prefs', '/api/futures'];
    const sts = urls.map(u => w.go(u, { cache: 'no-store' }));
    w.c.advance(900000); await tick();
    chk(sts.every(s => !s.done) && w.c.pending() === 0 && w.calls.every(x => !x.o.signal),
      'A 그 밖 /api 읽기 = 감싸개 타이머 없음(빌드 대기 — 재구축과 겹친 빌드는 수 분 · 저장본 시작 직후 첫 빌드 대기 · 물어보는 검색·종목 확인)', sts.map(s => s.done));
    w.calls[0].res({ status: 200, ok: true }); await tick();
    chk(sts[0].done && sts[0].r && sts[0].r.status === 200, 'A 오래 걸린 상태 응답도 그대로 받음(15분 뒤 성공)', sts[0]);
  });
  await sec('A 머리 도착 = 타이머 지움', async () => {
    const w = wrapper();
    const st = w.go('/api/health');
    w.c.advance(5000); w.calls[0].res({ status: 200, ok: true }); await tick();
    chk(st.done && st.r && st.r.status === 200 && w.seen.length === 1, 'A 응답 = 그대로 돌려줌 · 401 로그인 감시(__tjLoginCheck) 그대로 부름', [st, w.seen.length]);
    chk(w.c.pending() === 0 && !w.calls[0].o.signal.aborted, 'A 머리가 오면 타이머를 지움(큰 본문 읽기는 안 끊음)', [w.c.pending(), w.calls[0].o.signal.aborted]);
    w.c.advance(300000); await tick();
    chk(!w.calls[0].o.signal.aborted, 'A 머리 뒤 오래 지나도 안 끊음', w.calls[0].o.signal.aborted);
  });
  await sec('A 손대지 않는 요청', async () => {
    const w = wrapper();
    const body = JSON.stringify({ k: 1 }), po = w.go('/api/plan', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body });
    const ac = new AbortController(), own = w.go('/api/search?q=x', { signal: ac.signal });
    const asset = w.go('/v2/fonts/plex.css'), nobj = w.go(new URL('http://127.0.0.1/api/health'));
    w.c.advance(600000); await tick();
    chk(!po.done && !(w.calls[0].o && w.calls[0].o.signal) && w.calls[0].o.body === body, 'A 쓰기(POST) = 시간 제한 없음(끊으면 다시 누르기 = 두 번 저장) · 옵션 그대로', w.calls[0].o);
    chk(!own.done && w.calls[1].o.signal === ac.signal, 'A 호출부가 준 signal = 그대로(감싸개 타이머 없음)', w.calls[1].o);
    chk(!asset.done && !w.calls[2].o && !nobj.done && w.calls.length === 4 && w.c.pending() === 0, 'A /api 밖·문자열 아닌 주소 = 그대로', w.calls.map(x => x.o));
    w.calls[0].res({ status: 401, ok: false }); await tick();
    chk(po.done && po.r && po.r.status === 401 && w.seen.length === 1, 'A 쓰기 응답도 로그인 감시 그대로', [po, w.seen.length]);
  });

  // [B] app.js 폴링 간격 ──────────────────────────────────────────────────────────────────────────────
  await sec('B 간격 규칙', async () => {
    const pollGap = new Function('POLL_MS', lineOf(APP)('  const pollGap = ') + '\nreturn pollGap;')(30000);
    const got = [0, 1, 2, 3, 4, 5, 6, 9].map(n => pollGap(n) / 1000);
    chk(JSON.stringify(got) === JSON.stringify([30, 30, 30, 60, 120, 240, 300, 300]), 'B 연속 실패 2번까지 30초 · 3번째부터 60 → 120 → 240초 → 최대 5분', got);
  });
  await sec('B refresh 실패 수', async () => {
    const S = { locked: false, seq: 0, applied: 0, ver: 'v1', parts: null, D: { ok: 1 }, viewOk: true, data: {}, cached: false };
    let resp = null, now = 1000;
    const deps = { S, PART_POLL_CAP: 600000, window: {}, partsFullRecover: () => {}, partsPollHold: () => false, partsPump: () => {},
      performance: { now: () => now }, fetch: async () => { if (!resp) throw new Error('서버 연결 끊김'); return resp; }, stateUrl: v => '/api/v2/state?since=' + v,
      onUnauthorized: () => {}, loadResp: async () => ({ kind: 'same' }), optSettle: () => false, derive: d => d, rescue: () => {}, render: () => {},
      adopt: () => {}, renderChrome: () => {}, toast: () => {}, setTimeout: () => 0, partsReset: () => {}, partsOf: () => [], IDB: { putState: () => {} },
      renderAuto: () => {}, logError: () => {}, renderView: () => {}, Date: { now: () => now } };
    const refresh = new Function(...Object.keys(deps), cutOf(APP)('  async function refresh(manual, boot, auto) {', '  async function bootLoad() {') + '\nreturn refresh;')(...Object.values(deps));
    await refresh(false, null, true); now += 30000; await refresh(false, null, true);
    chk(S.pollFail === 2 && S.pollFailAt === 31000 && S.err, 'B 자동 폴링 실패 = 연속 실패 수 +1 · 실패 시각', [S.pollFail, S.pollFailAt, S.err]);
    resp = { status: 200, ok: true }; now += 30000; await refresh(false, null, true);
    chk(S.pollFail === 0 && S.err === null, 'B 성공하면 실패 수 0(다음 폴링 30초)', [S.pollFail, S.err]);
  });
  await sec('B 폴링 일정(서버 15분 끊김 → 복구)', async () => {
    const S = {}; let now = 0;
    const due = new Function('S', 'POLL_MS', 'Date', lineOf(APP)('  const pollGap = ') + '\n' + lineOf(APP)('  const pollDue = ') + '\nreturn pollDue;')(S, 30000, { now: () => now });
    const sent = [];
    for (now = 30000; now <= 900000; now += 30000) if (due()) { sent.push(now / 1000); S.pollFail = (S.pollFail || 0) + 1; S.pollFailAt = now; }
    chk(JSON.stringify(sent) === JSON.stringify([30, 60, 90, 150, 270, 510, 810]), 'B 15분 끊김 = 요청 7번(종전 30번) — 30·60·90초 뒤 60·120·240·300초 간격', sent);
    S.pollFail = 0; now += 30000;
    chk(due(), 'B 성공(실패 수 0) 뒤 바로 다음 30초 틱에 폴링', S);
  });

  // [C] health.js ──────────────────────────────────────────────────────────────────────────────────────
  await sec('C 상태 점 실패 수', async () => {
    const cutH = cutOf(HJ), opt = (a, b) => { try { return cutH(a, b); } catch (e) { return ''; } };
    const H = { data: null, err: null, at: 0, inflight: false }; let resp = null;
    const deps = { H, window: { TJ: { isLocked: () => false } }, isLocked: () => false, fetch: async () => { if (!resp) throw new Error('끊김'); return resp; }, paint: () => {} };
    const load = new Function(...Object.keys(deps), opt('  const syn = ', '  async function load(') + cutH('  async function load(', '  function counts() {') + '\nreturn load;')(...Object.values(deps));
    await load(); await load();
    chk(H.fail === 2 && H.failAt > 0 && H.err, 'C 읽기 실패 = 연속 실패 수 +1 · 실패 시각', [H.fail, H.failAt, H.err]);
    resp = { status: 200, ok: true, json: async () => ({ ok: true, health: { overall: 'ok', open: [] }, version: 'x', dataRev: 1 }) };
    await load();
    chk(H.fail === 0 && H.err === null && H.data && H.data.overall === 'ok', 'C 성공하면 실패 수 0', [H.fail, H.err]);
    const gap = new Function('POLL_MS', lineOf(HJ)('  const pollGap = ') + '\nreturn pollGap;')(30000);
    chk([2, 3, 4, 8].map(gap).join() === '30000,60000,120000,300000', 'C 간격 = app.js 와 같은 규칙', [2, 3, 4, 8].map(gap));
    let now = 0; const H2 = { fail: 3, failAt: 0 };
    const due = new Function('H', 'POLL_MS', 'Date', lineOf(HJ)('  const pollGap = ') + '\n' + lineOf(HJ)('  const pollDue = ') + '\nreturn pollDue;')(H2, 30000, { now: () => now });
    now = 30000; const a = due(); now = 60000; const b = due();
    chk(!a && b, 'C 실패 3번 뒤 30초 틱은 건너뛰고 60초 틱에 다시', [a, b]);
  });
  console.log(JSON.stringify(R));
})().catch(e => { console.log(JSON.stringify([[false, '실행 오류: ' + (e && e.stack || e)]])); });
'''


def run_js(js):
    node = T.node_bin("화면 요청 시간 제한 시험")
    if not node:
        return None
    v2 = os.path.join(T.ROOT, "web", "v2")
    env = dict(os.environ, TJ_TEST_INDEX=os.path.join(v2, "index.html"), TJ_TEST_APP=T.app_js_path(), TJ_TEST_HEALTH=os.path.join(v2, "health.js"))
    p = subprocess.run([node, "--input-type=module", "-"], input=js, capture_output=True, text=True, timeout=60, env=env)
    out = (p.stdout or "").strip().splitlines()
    if p.returncode != 0 or not out:
        T.chk(False, "node 실행", (p.stderr or "")[-1500:])
        return None
    return json.loads(out[-1])


R = run_js(JS)
for ok, msg, *d in (R or []):
    T.chk(ok, msg, d[0] if d else None)
T.chk(R is None or len(R) >= 14, "검사 줄 수(묶음이 실행 오류로 빠지지 않음)", len(R or []))
T.finish()
