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
const cutOpt = (a, b) => { try { return cut(a, b); } catch (e) { return ''; } };   // 옛 판(공용 도우미 없음)에서도 돌아 RED 를 보이게
const HELP = cutOpt('  const sync = {', '  const uiPopBox = ');
const R = []; const chk = (ok, msg, d) => R.push([!!ok, msg, ok ? undefined : d]);
const tick = () => new Promise(r => setTimeout(r, 0));
const sec = async (n, f) => { try { await f(); } catch (e) { chk(false, '묶음 ' + n + ' 실행 오류', String((e && e.stack) || e).slice(0, 300)); } };
function harness() {
  const S = { drafts: {}, D: { plans: {} }, planSnap: {} }, toasts = [], posts = [];
  const post = (path, body) => new Promise(res => posts.push({ path, body, res }));
  const deps = { S, post, toast: (m, e) => toasts.push([m, !!e]), render: () => {}, renderOverlay: () => {} };
  const f = new Function(...Object.keys(deps), HELP + cut('  function savePlan(key, fields, okMsg) {', '  function saveAlias(') + '\nreturn savePlan;')(...Object.values(deps));
  return { S, posts, toasts, savePlan: f };
}
(async () => {
  await sec(1, async () => { // 목표가·손절만 저장 — 안 보낸 메모는 남는다
    const h = harness(); h.S.drafts = { 't:K': '300', 's:K': '80', 'm:K': 'UNSAVED MEMO' }; h.S.planSnap.K = { cu: 'KRW' };
    h.savePlan('K', { target: 300, stop: 80 }, 'ok'); h.posts[0].res({ ok: true }); await tick(); await tick();
    chk(h.posts[0].body.memo === undefined, 'F08 목표·손절 저장 본문에 메모 없음', h.posts[0].body);
    chk(h.S.drafts['m:K'] === 'UNSAVED MEMO', 'F08 목표·손절 저장 뒤 안 보낸 메모 초안 남음', h.S.drafts);
    chk(h.S.drafts['t:K'] === undefined && h.S.drafts['s:K'] === undefined, 'F08 보낸 목표·손절 초안은 지움(정상 경로)', h.S.drafts);
    chk(!h.S.planSnap.K, 'F08 목표·손절 초안 다 지움 → 스냅숏 지움', h.S.planSnap);
  });
  await sec(2, async () => { // 저장 대기 중 고쳐 친 목표가 · 새로 친 메모 = 남음
    const h = harness(); h.S.drafts = { 't:K': '310', 's:K': '90' }; h.S.planSnap.K = { cu: 'USD' };
    h.savePlan('K', { target: 310, stop: 90 }, 'ok');
    h.S.drafts['t:K'] = '999'; h.S.drafts['m:K'] = 'TYPED DURING SAVE';
    h.posts[0].res({ ok: true }); await tick(); await tick();
    chk(h.S.drafts['t:K'] === '999', 'F08 저장 대기 중 고쳐 친 목표가 남음', h.S.drafts);
    chk(h.S.drafts['s:K'] === undefined, 'F08 안 바뀐 손절 초안은 지움', h.S.drafts);
    chk(h.S.drafts['m:K'] === 'TYPED DURING SAVE', 'F08 저장 대기 중 친 메모 남음', h.S.drafts);
    chk(!!h.S.planSnap.K, 'F08 목표 초안이 남았으면 스냅숏 유지(칸 통화 그대로)', h.S.planSnap);
  });
  await sec(3, async () => { // 메모 저장은 목표·손절 초안·스냅숏을 안 건드린다
    const h = harness(); h.S.drafts = { 't:K': '320', 's:K': '95', 'm:K': 'memo only' }; h.S.planSnap.K = { cu: 'KRW' };
    h.savePlan('K', { memo: 'memo only' }, 'ok'); h.posts[0].res({ ok: true }); await tick(); await tick();
    chk(h.S.drafts['t:K'] === '320' && h.S.drafts['s:K'] === '95', 'F08 메모 저장이 목표·손절 초안을 안 지움', h.S.drafts);
    chk(h.S.drafts['m:K'] === undefined, 'F08 보낸 메모 초안은 지움', h.S.drafts);
    chk(!!h.S.planSnap.K, 'F08 메모 저장은 스냅숏 유지', h.S.planSnap);
  });
  await sec(4, async () => { // 실패 = 아무것도 안 지움 · 해제(null·null) = 목표·손절만
    const h = harness(); h.S.drafts = { 't:K': '1', 's:K': '2', 'm:K': 'x' };
    h.savePlan('K', { target: 300, stop: 80 }, 'ok'); h.posts[0].res(null); await tick(); await tick();
    chk(h.S.drafts['t:K'] === '1' && h.S.drafts['s:K'] === '2' && h.S.drafts['m:K'] === 'x', 'F08 저장 실패 = 초안 그대로', h.S.drafts);
    h.savePlan('K', { target: null, stop: null }, 'ok'); h.posts[1].res({ ok: true }); await tick(); await tick();
    chk(h.S.drafts['t:K'] === undefined && h.S.drafts['s:K'] === undefined && h.S.drafts['m:K'] === 'x', 'F08 해제 = 목표·손절 초안만 지움 · 메모 남음', h.S.drafts);
  });
  // ── A5-03 dmSave ──
  const dmH = () => {
    const S = { drafts: {}, dm: { ed: null, more: {}, local: {} }, drawer: null, rcpt: null }, toasts = [], posts = [];
    const post = (path, body) => new Promise(res => posts.push({ path, body, res }));
    const deps = { S, post, toast: (m, e) => toasts.push([m, !!e]), isISO: v => /^\d{4}-\d{2}-\d{2}$/.test(v), dmSym: v => v, dmGet: () => null, DM_MAX: 500, num: x => +x || 0,
      document: { activeElement: null }, rcSK: () => '', rcOn: () => false, rcLoad: () => {}, rcbLoad: () => {}, renderView: () => {}, renderOverlay: () => {} };
    const A = new Function(...Object.keys(deps), HELP + 'return ({' + cut('    dmSave: el => {', '    rcptDmDay:') + '});')(...Object.values(deps));
    return { S, toasts, posts, A };
  };
  await sec(5, async () => {
    const h = dmH(), kA = '2026-10-20|BTC', kB = '2026-10-20|ETH';
    h.S.drafts['dm:' + kA] = '근거 A'; h.S.dm.ed = kA;
    h.A.dmSave({ dataset: { k: kA } });
    h.S.drafts['dm:' + kA] = '근거 A — 저장 누른 뒤 이어서 쓴 내용';
    h.S.drafts['dm:' + kB] = '근거 B';
    h.A.dmSave({ dataset: { k: kB } });
    chk(h.posts.length === 2 && h.posts[1].body.sym === 'ETH', 'A5-03 dmSave 바쁨 = 코인별 — A 저장 중에도 B 는 바로 보냄', h.posts.map(x => x.body));
    h.A.dmSave({ dataset: { k: kA } });
    chk(h.posts.length === 2 && h.toasts.some(t => /저장하는 중/.test(t[0])), 'A5-03 dmSave 같은 코인 저장 중 다시 누름 = 알림(조용히 버리지 않음)', h.toasts);
    h.posts[0].res({ ok: true, memo: '근거 A', at: 1 }); h.posts[1].res({ ok: true, memo: '근거 B', at: 1 }); await tick(); await tick();
    chk(h.S.drafts['dm:' + kA] === '근거 A — 저장 누른 뒤 이어서 쓴 내용', 'A5-03 dmSave 저장 대기 중 이어 친 글 남음', h.S.drafts);
    chk(h.S.dm.ed === kA, 'A5-03 dmSave 이어 친 글이 있으면 고치기 상태 그대로', h.S.dm.ed);
    chk(h.S.drafts['dm:' + kB] === undefined && h.S.dm.local[kB] && h.S.dm.local[kB].memo === '근거 B', 'A5-03 dmSave 보낸 그대로면 초안 지움 · 화면 반영(정상)', [h.S.drafts, h.S.dm.local]);
    h.A.dmSave({ dataset: { k: kA } });
    chk(h.posts.length === 3, 'A5-03 dmSave 응답 뒤엔 같은 코인 다시 저장 가능(바쁨 풀림)', h.posts.length);
    h.posts[2].res(null); await tick(); await tick();
    h.A.dmSave({ dataset: { k: kA } });
    chk(h.posts.length === 4 && h.S.drafts['dm:' + kA] != null, 'A5-03 dmSave 실패 뒤 바쁨 풀림 · 초안 남음', [h.posts.length, h.S.drafts]);
  });
  // ── A5-03 같은 꼴 한 칸 저장(app.js) ──
  const oneH = (block, extra) => {
    const S = { drafts: {}, of: { memoEd: null }, wl: [] }, toasts = [], posts = [];
    const post = (path, body) => new Promise(res => posts.push({ path, body, res }));
    const deps = Object.assign({ S, post, toast: (m, e) => toasts.push([m, !!e]), renderView: () => {}, arr: x => (Array.isArray(x) ? x : []),
      draft: k => String(S.drafts[k] == null ? '' : S.drafts[k]).trim(), ofByAddr: () => null, pendByKey: () => ({ gkey: 'G' }),
      confirmAsk: o => o.run() }, extra || {});
    const A = new Function(...Object.keys(deps), HELP + 'return (' + block + ');')(...Object.values(deps));
    return { S, toasts, posts, A };
  };
  const ONE = [
    ['원가 cu', '{ costUnit: ' + cut('  function costUnit(k) {', '  function ignoreKeys(').trim().replace(/^function costUnit/, 'function') + ' }', h => { h.S.drafts['cu:K'] = '12'; h.A.costUnit('K'); }, ['cu:K'], '13'],
    ['보낸 곳 메모 ofm', '{' + cut('    ofMemoSave: el => {', '    ofLkOpen:') + '}', h => { h.S.of.memoEd = '0xA'; h.S.drafts['ofm:0xA'] = 'm1'; h.A.ofMemoSave({ dataset: { k: '0xA' } }); }, ['ofm:0xA'], 'm1 더'],
    ['과거 불러오기 bfDate', '{' + cut('    bfReq: () => {', '    addAlias:') + '}', h => { h.S.drafts.bfDate = '2026-01-01'; h.A.bfReq(); }, ['bfDate'], '2025-01-01'],
    ['지갑 이름 naddr·nalias', '{' + cut('    addAlias: () => {', '    covRetry:') + '}', h => { h.S.drafts.naddr = '0xB'; h.S.drafts.nalias = 'n1'; h.A.addAlias(); }, ['naddr', 'nalias'], 'n2'],
    ['화이트리스트 wl', '{' + cut('    wlAdd: () => {', '    wlRemove:') + '}', h => { h.S.drafts.wl = '0xC'; h.A.wlAdd(); }, ['wl'], '0xD'],
  ];
  await sec('한 칸', async () => { for (const [nm, block, go, keys, typed] of ONE) {
    let h = oneH(block); go(h); await tick();
    chk(h.posts.length === 1, 'A5-03 ' + nm + ' 보냄', h.posts.length);
    h.posts[0].res({ ok: true, whitelist: [] }); await tick(); await tick();
    chk(keys.every(k => h.S.drafts[k] === undefined), 'A5-03 ' + nm + ' 보낸 그대로면 지움(정상)', h.S.drafts);
    h = oneH(block); go(h); await tick();
    const kk = keys[keys.length - 1]; h.S.drafts[kk] = typed;
    h.posts[0].res({ ok: true, whitelist: [] }); await tick(); await tick();
    chk(h.S.drafts[kk] === typed, 'A5-03 ' + nm + ' 저장 대기 중 고쳐 친 칸 남음', h.S.drafts);
  } });
  await sec(6, async () => { // ofMemoSave 이어 친 글 = 고치는 칸 그대로
    const h = oneH('{' + cut('    ofMemoSave: el => {', '    ofLkOpen:') + '}'); h.S.of.memoEd = '0xA'; h.S.drafts['ofm:0xA'] = 'm1';
    h.A.ofMemoSave({ dataset: { k: '0xA' } }); h.S.drafts['ofm:0xA'] = 'm1 더'; h.posts[0].res({ ok: true }); await tick(); await tick();
    chk(h.S.of.memoEd === '0xA', 'A5-03 보낸 곳 메모 이어 친 글이 있으면 고치는 칸 열린 채', h.S.of.memoEd);
  });
  await sec(7, async () => { // NFT 지켜보기(tab_other) — 이어 친 주소 남음 · 시트 안 닫음
    const mk = () => { const S = { drafts: {}, sheet: { k: 'nftw' }, nft: {} }; let closed = 0; const P = []; const deps = { S, toast: () => {}, $: () => null,
      nftWatchBody: v => (v ? { op: 'watch_add', symbol: v } : null), nftPost: () => new Promise(r => P.push(r)), uiSheetClose: () => { closed++; } };
      const A = new Function(...Object.keys(deps), HELP + 'return ({' + cut('    nftWatch: async () => {', '    nftWatchOpen:') + '});')(...Object.values(deps));
      return { S, A, P, closed: () => closed }; };
    let h = mk(); h.S.drafts['nft:watch'] = 'abc'; h.A.nftWatch(); await tick(); h.S.drafts['nft:watch'] = 'abcd'; h.P[0]({ ok: true }); await tick(); await tick();
    chk(h.S.drafts['nft:watch'] === 'abcd' && h.closed() === 0, 'A5-03 NFT 지켜보기 저장 중 고쳐 친 주소 남음 · 시트 안 닫음', [h.S.drafts, h.closed()]);
    h = mk(); h.S.drafts['nft:watch'] = 'abc'; h.A.nftWatch(); await tick(); h.P[0]({ ok: true }); await tick(); await tick();
    chk(h.S.drafts['nft:watch'] === undefined && h.closed() === 1, 'A5-03 NFT 지켜보기 그대로면 비우고 닫음(정상)', [h.S.drafts, h.closed()]);
    h = mk(); h.S.drafts['nft:watch'] = '0xabc'; h.S.drafts['nft:wch'] = 'eth'; h.A.nftWatch(); await tick(); h.S.drafts['nft:wch'] = 'base'; h.P[0]({ ok: true }); await tick(); await tick();
    chk(h.S.drafts['nft:watch'] === '0xabc' && h.closed() === 0, '2차 NFT 저장 중 체인만 바꿈 = 주소 초안 남음 · 시트 안 닫음', [h.S.drafts, h.closed()]);
    h = mk(); h.S.drafts['nft:watch'] = 'abc'; h.A.nftWatch(); await tick(); h.S.sheet = { k: 'nftw' }; h.P[0]({ ok: true }); await tick(); await tick();
    chk(h.closed() === 0, '2차 NFT 저장 중 시트를 닫고 다시 연 새 시트 = 안 닫음', h.closed());
  });
  await sec(8, async () => { // 세일 메모(salelink.js · window.TJ.sync)
    const SL = fs.readFileSync(process.env.TJ_TEST_SALE, 'utf8'), cutL = (a, b) => { const i = SL.indexOf(a), j = SL.indexOf(b, i + 1); if (i < 0 || j < 0) throw new Error('salelink 블록: ' + a); return SL.slice(i, j); };
    const sync = HELP ? new Function('S', HELP + 'return sync;')({}) : null;
    const run = async (typed) => { const S = { drafts: { 'slm:0xS': 's1' } }, P = [];
      const x = { S, toast: () => {}, post: () => new Promise(r => P.push(r)) };
      const deps = { X: () => x, ofRow: () => null, pvOn: () => false, window: { TJ: sync ? { sync } : {} } };
      const A = new Function(...Object.keys(deps), 'return ({' + cutL('    slMemo: el => {', '    slGo:') + '});')(...Object.values(deps));
      A.slMemo({ getAttribute: () => '0xS' }); if (typed) S.drafts['slm:0xS'] = typed; P[0]({ ok: true }); await tick(); await tick(); return S.drafts['slm:0xS']; };
    chk(await run('s1 더') === 's1 더', 'A5-03 세일 메모 저장 중 고쳐 친 글 남음', null);
    chk(await run(null) === undefined, 'A5-03 세일 메모 그대로면 지움(정상)', null);
  });
  await sec(9, async () => { // 연결 키 칸(setup.js ksave) · 노드 월 한도(nmonth)
    const SU = fs.readFileSync(process.env.TJ_TEST_SETUP, 'utf8'), cutU = (a, b) => { const i = SU.indexOf(a), j = SU.indexOf(b, i + 1); if (i < 0 || j < 0) throw new Error('setup 블록: ' + a); return SU.slice(i, j); };
    const sync = HELP ? new Function('S', HELP + 'return sync;')({}) : null;
    const mk = () => { const U = { d: {}, busy: {}, ack: {}, needAck: {}, test: {} }, P = [];
      const grp = { name: 'Etherscan', fields: [{ key: 'etherscan' }] };
      const deps = { U, grpOf: () => grp, groupVals: () => ({ etherscan: String(U.d.k_etherscan || '').trim() }), NODE_KEYS: [], needAck: () => false, toast: () => {}, render: () => {},
        api: () => new Promise(r => P.push(r)), clearVals: () => { delete U.d.k_etherscan; }, xpName: n => ({ t: n }), refreshStatus: async () => {}, window: { TJ: sync ? { sync } : {} },
        draft: k => U.d[k] || '', nodePlanSave: () => new Promise(r => P.push(r)) };
      const A = new Function(...Object.keys(deps), 'return ({' + cutU('    async ksave(el) {', '    async kdel(el) {') + cutU('    async nmonth(el) {', '    async cgshare(el) {') + '});')(...Object.values(deps));
      return { U, A, P }; };
    let h = mk(); h.U.d.k_etherscan = 'KEY1'; let pr = h.A.ksave({ getAttribute: () => 'etherscan' }); await tick(); h.U.d.k_etherscan = 'KEY2'; h.P[0]({ ok: true }); await pr;
    chk(h.U.d.k_etherscan === 'KEY2', 'A5-03 연결 키 저장 중 새로 친 칸 남음', h.U.d);
    h = mk(); h.U.d.k_etherscan = 'KEY1'; pr = h.A.ksave({ getAttribute: () => 'etherscan' }); await tick(); h.P[0]({ ok: true }); await pr;
    chk(h.U.d.k_etherscan === undefined, 'A5-03 연결 키 그대로면 비움(정상)', h.U.d);
    h = mk(); h.U.d.nm_ankr = '8000000'; pr = h.A.nmonth({ getAttribute: () => 'ankr' }); await tick(); h.U.d.nm_ankr = '9000000'; h.P[0]({ ok: true }); await pr;
    chk(h.U.d.nm_ankr === '9000000', 'A5-03 노드 월 한도 저장 중 고쳐 친 값 남음', h.U.d);
    h = mk(); h.U.d.nm_ankr = '8000000'; pr = h.A.nmonth({ getAttribute: () => 'ankr' }); await tick(); h.P[0]({ ok: false, error: 'x' }); await pr;
    chk(h.U.d.nm_ankr === '8000000', 'A5-03 노드 월 한도 저장 실패 = 칸 그대로', h.U.d);
    h = mk(); h.U.d.nm_ankr = '8000000'; pr = h.A.nmonth({ getAttribute: () => 'ankr' }); await tick(); h.P[0]({ ok: true }); await pr;
    chk(h.U.d.nm_ankr === undefined, 'A5-03 노드 월 한도 저장 성공 = 비움(정상)', h.U.d);
  });
  console.log(JSON.stringify(R));
})().catch(e => { console.log(JSON.stringify([[false, '실행 오류: ' + (e && e.stack || e)]])); });
'''


def run_js(js):
    node = T.node_bin("화면 JS 실행")
    if not node:
        return None
    v2 = os.path.join(T.ROOT, "web", "v2")
    env = dict(os.environ, TJ_TEST_APP=T.app_js_path(), TJ_TEST_SALE=os.path.join(v2, "salelink.js"), TJ_TEST_SETUP=os.path.join(v2, "setup.js"))
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
