#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

JS = r'''
import fs from 'node:fs';
const APP = fs.readFileSync(process.env.TJ_TEST_APP, 'utf8');
const cut = (a, b) => { const i = APP.indexOf(a), j = i < 0 ? -1 : APP.indexOf(b, i + 1); if (i < 0 || j < 0) throw new Error('블록을 못 찾음: ' + a.slice(0, 50)); return APP.slice(i, j); };
const R = []; const chk = (ok, msg, d) => R.push([!!ok, msg, ok ? undefined : d]);
const SECRET = 'SYNTHETIC_DEST 보낸 ₩12,345,678';
function harness() {
  const S = { D: { x: 1 }, data: { x: 1 }, modal: { title: '외부 유출로 확정할까요?', body: SECRET + '을 기록해요', danger: true }, drafts: { 'ofm:0xA': '비밀 메모' },
    drawer: 'rcpt', sheet: { k: 'oa', v: 'A' }, pop: 'pick:x', rcpt: { iso: '2026-10-20' }, oa: { d: { items: [1] } }, nft: { d: { rows: [1] } }, hist: { days: [1] }, al: {} };
  let html = 'OLD';
  const ov = { getAttribute: () => '', contains: () => false, querySelector: () => null, querySelectorAll: () => [], setAttribute: () => {} };
  const deps = { S, $: s => (s === '#overlay' ? ov : null), document: { activeElement: null, body: {} }, esc: s => String(s == null ? '' : s),
    TJDOM: { set: (e, s) => { html = s; } }, clearCache: () => {}, lockPanels: () => {}, renderChrome: () => {}, renderView: () => {}, hydrateLogos: () => {},
    ovAfter: () => {}, ovScrollKeep: () => null, ovErrHTML: () => '', uiSheetHTML: () => '<div class="usheet">' + SECRET + '</div>',
    futDrawer: () => '', rcptDrawer: () => '<div class="drawer">' + SECRET + '</div>', futRcptDrawer: () => '', levDrawer: () => '', venueDrawer: () => '',
    ovIsVis: () => false, ovPath: () => null, RV_IN: new Set(), window: {} };
  const body = cut('  function lockOut(why) {', '  function lockPanels() {') + cut('  function renderLocked() {', '  function toLogin(r) {')
    + cut('  function onUnauthorized() {', '  (function () {\n    const f0 = window.fetch;') + cut('  function renderOverlay() {', '  function ovAfter(h) {');
  const api = new Function(...Object.keys(deps), 'let ovIme = null, ovIdle = false;\n' + body + '\nreturn { lockOut, onUnauthorized, renderOverlay };')(...Object.values(deps));
  return { S, api, html: () => html };
}
const sens = S => ({ modal: !!S.modal, sheet: !!S.sheet, drawer: !!S.drawer, pop: !!S.pop, drafts: Object.keys(S.drafts || {}).length, rcpt: !!S.rcpt, oa: !!(S.oa && S.oa.d), nft: !!(S.nft && S.nft.d) });
try {
  { const h = harness(); h.api.renderOverlay();
    chk(h.html().indexOf('12,345,678') >= 0, 'F13 잠금 아님 = 확인창 그대로 그림(정상)', h.html()); }
  { const h = harness(); h.api.onUnauthorized();
    const z = sens(h.S);
    chk(h.S.locked && h.S.lockWhy === '401' && h.S.D === null, 'F13 401 = 잠금 · 사유 401 · 본문 데이터 비움', [h.S.locked, h.S.lockWhy]);
    chk(!z.modal && !z.sheet && !z.drawer && !z.pop && !z.drafts && !z.rcpt && !z.oa && !z.nft, 'F13 401 = 확인창·시트·서랍·팝·초안·영수증·기타 자산·NFT 비움(로그아웃과 같은 정리)', z);
    chk(h.html().indexOf('SYNTHETIC_DEST') < 0 && h.html().indexOf('12,345,678') < 0, 'F13 401 뒤 덮개에 민감 글 0', h.html()); }
  { const h = harness(); h.api.lockOut('logout');
    const z = sens(h.S);
    chk(h.S.locked && h.S.lockWhy === 'logout' && !z.modal && !z.sheet && !z.drafts && !z.nft, 'F13 로그아웃 = 같은 정리 · 사유 logout', [h.S.lockWhy, z]); }
  { const h = harness(); h.S.locked = true; h.api.renderOverlay();
    chk(h.html().indexOf('12,345,678') < 0, 'F13 잠금 중 남은 확인창이 있어도 덮개는 비움(방어)', h.html()); }
} catch (e) { chk(false, '실행 오류', String((e && e.stack) || e).slice(0, 400)); }
const postH = () => { const S = { csrf: 'T' }, toasts = [], P = [];
  const deps = { S, fetch: () => new Promise(r => P.push(r)), window: {}, optFor: () => null, optFail: () => {}, optOk: () => {}, toast: (m, e) => toasts.push([m, !!e]), refresh: () => {}, onUnauthorized: () => {} };
  const api = new Function(...Object.keys(deps), cut('  async function csrf(force) {', '  const OPT =') + '\nreturn {post};')(...Object.values(deps));
  return { S, toasts, P, api }; };
const ok200 = { status: 200, ok: true, json: async () => ({ ok: true, rows: [1] }) };
await (async () => {
  let h = postH(); let pr = h.api.post('/api/nft/prefs', {}, '저장했어요'); await new Promise(r => setTimeout(r, 0)); h.S.locked = true; h.P[0](ok200); let d = await pr;
  chk(d === null && !h.toasts.some(t => !t[1]), '3차 저장 대기 중 잠그면 늦은 성공 응답 = null · 성공 알림 없음', [d, h.toasts]);
  h = postH(); pr = h.api.post('/api/nft/prefs', {}, '저장했어요'); await new Promise(r => setTimeout(r, 0));
  let bodyRes; h.P[0]({ status: 200, ok: true, json: () => new Promise(r => { bodyRes = r; }) }); await new Promise(r => setTimeout(r, 0));
  h.S.locked = true; bodyRes({ ok: true, rows: [1] }); d = await pr;   // 헤더 받은 뒤 본문 기다리는 사이 잠금
  chk(d === null && !h.toasts.some(t => !t[1]), '3차 본문 받는 사이 잠겨도 늦은 성공 = null · 성공 알림 없음', [d, h.toasts]);
  h = postH(); pr = h.api.post('/api/nft/prefs', {}, '저장했어요'); await new Promise(r => setTimeout(r, 0)); h.P[0](ok200); d = await pr;
  chk(d && d.ok && h.toasts.some(t => t[0] === '저장했어요'), '3차 잠금 아님 = 그대로 성공(정상)', [d, h.toasts]);
})().catch(e => chk(false, '3차 실행 오류', String((e && e.stack) || e).slice(0, 300)));
console.log(JSON.stringify(R));
'''


def run_js(js):
    node = T.node_bin("화면 JS 실행")
    if not node:
        return None
    env = dict(os.environ, TJ_TEST_APP=T.app_js_path())
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
