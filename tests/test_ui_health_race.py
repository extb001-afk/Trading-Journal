#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

JS = r'''
import fs from 'node:fs';
const APP = fs.readFileSync(process.env.TJ_TEST_APP, 'utf8'), HJ = fs.readFileSync(process.env.TJ_TEST_HEALTH, 'utf8');
const cutOf = SRC => (a, b) => { const i = SRC.indexOf(a), j = i < 0 ? -1 : SRC.indexOf(b, i + 1); if (i < 0 || j < 0) throw new Error('블록을 못 찾음: ' + a.slice(0, 50)); return SRC.slice(i, j); };
const cut = cutOf(APP), cutH = cutOf(HJ), opt = f => (a, b) => { try { return f(a, b); } catch (e) { return ''; } };
const HELP = opt(cut)('  const sync = {', '  const uiPopBox = ');
const R = []; const chk = (ok, msg, d) => R.push([!!ok, msg, ok ? undefined : d]);
const tick = async (n) => { for (let i = 0; i < (n || 8); i++) await new Promise(r => setTimeout(r, 0)); };
const sec = async (n, f) => { try { await f(); } catch (e) { chk(false, '묶음 ' + n + ' 실행 오류', String((e && e.stack) || e).slice(0, 300)); } };
const health = st => ({ overall: st === 'open' ? 'warn' : 'ok', open: [{ id: 'synthetic:warn', acked: st !== 'open' }] });
function harness() {
  const H = { data: null, err: null, at: 0, inflight: false }, gets = [], posts = []; let paints = 0;
  const sync = HELP ? new Function('S', HELP + 'return sync;')({}) : null;
  const win = { TJ: sync ? { sync, isLocked: () => false } : { isLocked: () => false } };
  const ext = { post: (path, body) => new Promise(res => posts.push({ path, body, res })) };
  const deps = { H, window: win, isLocked: () => false, fetch: () => new Promise(res => gets.push(res)), paint: () => { paints++; }, ext: () => ext };
  const body = opt(cutH)('  const syn = ', '  async function load(') + cutH('  async function load(', '  function counts() {') + cutH('  async function ackSend(path, body) {', '  const OPS_LINK = ');
  const api = new Function(...Object.keys(deps), body + '\nreturn { load, ackSend };')(...Object.values(deps));
  const ok = st => ({ status: 200, ok: true, json: async () => ({ ok: true, health: health(st), version: 'x', dataRev: 1 }) });
  return { H, gets, posts, api, ok, paints: () => paints };
}
(async () => {
  await sec('A5-04 느린 읽기 뒤 닫기', async () => {
    const h = harness();
    h.api.load(); await tick();                 // 느린 읽기(열림 상태) 떠남
    h.api.ackSend('/api/health/ack', { check: 'synthetic:warn' }); await tick();
    chk(h.posts.length === 1, 'A5-04 닫기 보냄', h.posts.length);
    h.posts[0].res({ ok: true, health: health('acked') }); await tick();
    chk(h.H.data && h.H.data.overall === 'ok', 'A5-04 닫기 응답 = 정본(닫음)', h.H.data);
    h.gets[0](h.ok('open')); await tick();       // 닫기 전에 떠난 읽기가 늦게 도착
    chk(h.H.data && h.H.data.overall === 'ok', 'A5-04 늦게 온 옛 읽기 버림(닫은 주의가 다시 안 뜸)', h.H.data);
    chk(h.gets.length === 2, 'A5-04 닫기 뒤 강제 읽기 = 줄 세워 새로 한 번', h.gets.length);
    if (h.gets[1]) { h.gets[1](h.ok('acked')); await tick(); }
    chk(h.H.data && h.H.data.overall === 'ok' && !h.H.inflight, 'A5-04 새 읽기 반영 · 받는 중 풀림', h.H);
  });
  await sec('A5-04 정상', async () => {
    const h = harness();
    h.api.load(); h.api.load(); await tick();
    chk(h.gets.length === 1, 'A5-04 받는 중 주기 읽기 = 겹친 요청 없음', h.gets.length);
    h.gets[0](h.ok('open')); await tick();
    chk(h.H.data && h.H.data.overall === 'warn' && h.H.at > 0 && h.gets.length === 1, 'A5-04 쓰기 없으면 읽기 그대로 반영(정상)', h.H.data);
  });
  console.log(JSON.stringify(R));
})().catch(e => { console.log(JSON.stringify([[false, '실행 오류: ' + (e && e.stack || e)]])); });
'''


def run_js(js):
    node = T.node_bin("화면 JS 실행")
    if not node:
        return None
    env = dict(os.environ, TJ_TEST_APP=T.app_js_path(), TJ_TEST_HEALTH=os.path.join(T.ROOT, "web", "v2", "health.js"))
    p = subprocess.run([node, "--input-type=module", "-"], input=js, capture_output=True, text=True, timeout=60, env=env)
    out = (p.stdout or "").strip().splitlines()
    if p.returncode != 0 or not out:
        T.chk(False, "node 실행", (p.stderr or "")[-1500:])
        return None
    return json.loads(out[-1])


R = run_js(JS)
for ok, msg, *d in (R or []):
    T.chk(ok, msg, d[0] if d else None)
T.finish()
