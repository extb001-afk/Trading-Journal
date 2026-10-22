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
const cutOpt = (a, b) => { try { return cut(a, b); } catch (e) { return ''; } };
const HELP = cutOpt('  const sync = {', '  const uiPopBox = ');
const R = []; const chk = (ok, msg, d) => R.push([!!ok, msg, ok ? undefined : d]);
const tick = async (n) => { for (let i = 0; i < (n || 6); i++) await new Promise(r => setTimeout(r, 0)); };
const sec = async (n, f) => { try { await f(); } catch (e) { chk(false, '묶음 ' + n + ' 실행 오류', String((e && e.stack) || e).slice(0, 300)); } };
const item = v => ({ id: 'A', name: 'Synthetic A', cat: 'realestate', cur: 'KRW', value: v, date: '2026-10-20' });
function harness() {
  const S = { drafts: {}, oa: { st: '', d: null, at: 0, err: '', had: false, filter: 'all', sel: null, form: null, lk: null, busy: false, delArm: null }, sheet: null, D: {}, tab: 'other' };
  const gets = [], posts = [], toasts = []; let closed = 0, renders = 0; const wire = { need: null };
  const fetch = (u) => new Promise(res => gets.push({ u, res }));
  const post = (path, body) => new Promise(res => posts.push({ path, body, res }));
  const deps = { S, fetch, post, toast: (m, e) => toasts.push([m, !!e]), onUnauthorized: () => {}, arr: x => (Array.isArray(x) ? x : []), num: x => +x || 0,
    renderAuto: () => { renders++; }, renderView: () => { renders++; if (wire.need) wire.need(60000); }, oaRe: () => { renders++; if (wire.need) wire.need(60000); }, todayISO: () => '2026-10-21', uiSheetClose: () => { closed++; S.sheet = null; },
    oaItems: () => (S.oa.d ? S.oa.d.items : []), isISO: v => /^\d{4}-\d{2}-\d{2}$/.test(v) };
  const api = new Function(...Object.keys(deps), HELP + cut('  function oaLoad(force) {', '  function oaDate(d, o) {') + cut('  function oaFormReset(o) {', '  function oaDashLine() {')
    + '\nreturn { oaLoad, oaNeed, oaFormReset, oaSave, oaDel };')(...Object.values(deps));
  const okResp = (items) => ({ status: 200, ok: true, json: async () => ({ ok: true, items }) });
  return { S, gets, posts, toasts, api, okResp, closed: () => closed, wire };
}
(async () => {
  await sec('F09 새 폼', async () => {
    const h = harness(), { S, api } = h;
    api.oaLoad(true); h.gets[0].res(h.okResp([item(1000000)])); await tick();
    api.oaFormReset(item(1000000)); S.sheet = { k: 'oa' }; S.drafts['oa:value'] = '9000000';
    const pr = api.oaSave(); await tick();
    chk(h.posts.length === 1 && S.oa.busy, 'F09 저장 보냄 · 바쁨', h.posts.length);
    S.sheet = null; api.oaFormReset(); S.sheet = { k: 'oa' }; const B = S.oa.form;   // 시트 닫고 '+ 자산 추가'
    S.drafts['oa:name'] = 'UNSAVED asset B'; S.drafts['oa:value'] = '2222';
    h.posts[0].res({ ok: true, id: 'A' }); await pr; await tick();
    chk(S.oa.form === B && S.drafts['oa:name'] === 'UNSAVED asset B' && S.drafts['oa:value'] === '2222', 'F09 A 응답이 그 사이 연 B 폼·초안을 안 지움', [S.drafts, S.oa.form === B]);
    chk(h.closed() === 0 && S.sheet && S.sheet.k === 'oa', 'F09 A 응답이 B 시트를 안 닫음', h.closed());
  });
  await sec('F09 같은 폼 고쳐 침', async () => {
    const h = harness(), { S, api } = h;
    api.oaFormReset(); S.sheet = { k: 'oa' }; const F = S.oa.form; S.drafts['oa:name'] = 'New C'; S.drafts['oa:value'] = '10';
    const pr = api.oaSave(); await tick(); S.drafts['oa:value'] = '11';
    h.posts[0].res({ ok: true, id: 'C1' }); await pr; await tick();
    chk(S.oa.form === F && S.drafts['oa:value'] === '11' && S.drafts['oa:name'] === 'New C' && h.closed() === 0, 'F09 저장 중 고쳐 친 값 = 폼·초안 그대로(시트 열린 채)', [S.drafts, h.closed()]);
    chk(F.id === 'C1', 'F09 저장 중 고친 새 자산 폼 = 그 자산 고치기로(두 번 추가 안 됨)', F.id);
  });
  await sec('F09 정상', async () => {
    const h = harness(), { S, api } = h;
    api.oaFormReset(); S.sheet = { k: 'oa' }; const F = S.oa.form; S.drafts['oa:name'] = 'New D'; S.drafts['oa:value'] = '5';
    const pr = api.oaSave(); await tick(); h.posts[0].res({ ok: true, id: 'D1' }); await pr; await tick();
    chk(S.oa.form !== F && !S.drafts['oa:name'] && h.closed() === 1 && S.oa.sel === 'D1', 'F09 그대로면 초기화·닫기·고름(정상)', [S.drafts, h.closed(), S.oa.sel]);
  });
  await sec('F09 삭제', async () => {
    const h = harness(), { S, api } = h;
    api.oaLoad(true); h.gets[0].res(h.okResp([item(1)])); await tick();
    api.oaFormReset(item(1)); S.sheet = { k: 'oa' };
    await api.oaDel(); const pr = api.oaDel(); await tick();
    chk(h.posts.length === 1 && S.oa.busy === true, 'F09 삭제 = 바쁨 표식', S.oa.busy);
    api.oaDel(); await tick();
    chk(h.posts.length === 1, 'F09 삭제 중 겹친 누름 버림', h.posts.length);
    S.sheet = null; api.oaFormReset(); S.sheet = { k: 'oa' }; const B = S.oa.form; S.drafts['oa:name'] = 'UNSAVED asset B';
    h.posts[0].res({ ok: true }); await pr; await tick();
    chk(S.oa.form === B && S.drafts['oa:name'] === 'UNSAVED asset B' && h.closed() === 0, 'F09 삭제 응답이 그 사이 연 새 폼을 안 지우고 안 닫음', [S.drafts, h.closed()]);
    const h2 = harness(); h2.api.oaFormReset(item(1)); h2.S.sheet = { k: 'oa' }; await h2.api.oaDel(); const p2 = h2.api.oaDel(); await tick();
    h2.posts[0].res({ ok: true }); await p2; await tick();
    chk(h2.closed() === 1 && h2.S.oa.form && h2.S.oa.form.id === null, 'F09 삭제 정상 = 비우고 닫음', h2.closed());
  });
  await sec('F10 저장 전 읽기', async () => {
    const h = harness(), { S, api } = h;
    api.oaLoad(true); h.gets[0].res(h.okResp([item(1000000)])); await tick();
    api.oaFormReset(item(1000000)); S.drafts['oa:value'] = '9000000';
    S.oa.at = 1; api.oaNeed(60000);   // 60초 넘게 폼을 쓰다 → 낡음 읽기(저장 직전)
    chk(h.gets.length === 2, 'F10 낡음 읽기 떠남', h.gets.length);
    const pr = api.oaSave(); await tick();
    h.posts[0].res({ ok: true, id: 'A' }); await pr; await tick();   // 저장 성공 → oaLoad(true) = 받는 중 → again
    h.gets[1].res(h.okResp([item(1000000)])); await tick();   // 저장 전에 읽은 옛 값 도착
    chk(S.oa.at === 0 && S.oa.st === 'loading', 'F10 저장 전에 떠난 읽기(옛 값) 버림(신선도 안 올림)', [S.oa.at, S.oa.st]);
    chk(h.gets.length === 3, 'F10 버린 뒤 줄 세운 강제 읽기 새로 한 번', h.gets.length);
    if (h.gets[2]) { h.gets[2].res(h.okResp([item(9000000)])); await tick(); }
    chk(S.oa.d && S.oa.d.items[0].value === 9000000 && S.oa.st === 'ok', 'F10 새 읽기 = 저장 뒤 값', S.oa.d);
  });
  await sec('F10 삭제 뒤 읽기', async () => {
    const h = harness(), { S, api } = h;
    api.oaLoad(true); h.gets[0].res(h.okResp([item(1)])); await tick();
    api.oaFormReset(item(1)); await api.oaDel();
    S.oa.at = 1; api.oaNeed(60000);   // 삭제 직전 낡음 읽기
    const pr = api.oaDel(); await tick(); h.posts[0].res({ ok: true }); await pr; await tick();
    h.gets[1].res(h.okResp([item(1)])); await tick();
    chk(h.gets.length === 3 && !(S.oa.d && S.oa.d.items.length && h.gets.length === 2), 'F10 삭제 전 읽기 버림 · 새로 읽기', h.gets.length);
  });
  await sec('F10 정상', async () => {
    const h = harness(), { S, api } = h;
    api.oaLoad(true); api.oaLoad(true);
    chk(h.gets.length === 1 && S.oa.again === true, 'F10 받는 중 강제 = again 표식(겹친 요청 없음)', [h.gets.length, S.oa.again]);
    h.gets[0].res(h.okResp([item(7)])); await tick();
    chk(S.oa.d && S.oa.d.items[0].value === 7 && S.oa.at > 0 && h.gets.length === 2, 'F10 쓰기 없으면 응답 그대로 · again = 새로 한 번', [S.oa.d, h.gets.length]);
  });
  await sec('2차 저장 중 읽기 반복', async () => {
    const h = harness(), { S, api } = h;
    api.oaLoad(true); h.gets[0].res(h.okResp([item(1)])); await tick();
    h.wire.need = api.oaNeed;   // 화면 그리기 = 기타 자산 탭(vOther → oaNeed(60000))
    api.oaFormReset(item(1)); S.drafts['oa:value'] = '2'; S.oa.at = 1;   // 60초 넘게 낡음
    const pr = api.oaSave(); await tick();
    for (let i = 1; i < 6 && h.gets[i]; i++) { h.gets[i].res(h.okResp([item(1)])); await tick(); }
    chk(h.gets.length <= 2, '2차 저장 대기 중 버린 읽기가 다시 그리기 → 또 읽기로 반복하지 않음', h.gets.length);
    h.posts[0].res({ ok: true, id: 'A' }); await pr; await tick();
    const last = h.gets[h.gets.length - 1]; last.res(h.okResp([item(2)])); await tick();
    chk(S.oa.d && S.oa.d.items[0].value === 2, '2차 저장 뒤 새 읽기로 정본(정상)', S.oa.d);
  });
  await sec('2차 잠금 뒤 읽기', async () => {
    const h = harness(), { S, api } = h;
    api.oaLoad(true); S.locked = true; S.oa.d = null;   // 401·로그아웃(lockClear)
    h.gets[0].res(h.okResp([item(5)])); await tick();
    chk(S.oa.d === null, '2차 잠근 뒤 도착한 읽기 = 버림(비운 자산 데이터 안 되살림)', S.oa.d);
  });
  console.log(JSON.stringify(R));
})().catch(e => { console.log(JSON.stringify([[false, '실행 오류: ' + (e && e.stack || e)]])); });
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
