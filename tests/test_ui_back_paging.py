#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import os
import shutil
import subprocess

APP = T.app_js_path()
app = open(APP, encoding="utf-8").read()

print("[1] 정적")
i9 = app.find("    ofWaitGo: () => {")
ow = app[i9:app.find("\n", i9)] if i9 >= 0 else ""
T.chk("uiPgReset('ofh')" in ow and "S.uiMore" not in app, "ofWaitGo(세일 참가금만 보기) = 정리 내역 쪽 처음으로(UI_PICK.ofReason 과 같게) · pg19: 옛 앞 n개 상태(S.uiMore) 없음", ow[:200])
for k in ("attdRc", "attdLp", "attdFr", "attdCoin"):
    j9 = app.find("      " + k + ": el => {")
    ln = app[j9:app.find("\n", j9)] if j9 >= 0 else ""
    T.chk("uiSheetCloseThen(" in ln and "uiSheetClose(true)" not in ln, "분해 시트 %s = 시트 기록 칸을 걷은 뒤 이동(uiSheetCloseThen)" % k, ln[:160])
T.chk("function uiSheetCloseThen(then) {" in app, "uiSheetCloseThen 정의(뒤로가기가 끝난 뒤 then — closeDrawerThen 과 같은 규약)")
T.chk("uiPgUnits" not in app and "uiPgSlice('hold', rows)" in app and "uiPgBar('hold', rows.length, { unit: rows.length > nCoin ? '줄' : '종' })" in app,
      "보유표 쪽 = 줄 단위(Rabby 하위 행도 한 줄 · 쪽 바 = 줄 수 — 하위 행 있으면 단위 '줄')")
T.chk("uiPgSlice('zero', z)" in app and "uiPgBar('zero', z.length, {" in app and "uiPgReveal('zero'," in app,
      "값 없는 토큰 = 설정 쪽 크기씩 쪽 · 찾아가기 = 그 쪽(uiPgReveal)")

print("[2] 화면 함수(node)")
JS = r'''import fs from 'node:fs';
const APP = fs.readFileSync(process.env.TJ_TEST_APP, 'utf8');
const cut = (a, b) => { const i = APP.indexOf(a), j = i < 0 ? -1 : APP.indexOf(b, i + 1); if (i < 0 || j < 0) throw new Error('블록을 못 찾음: ' + a.slice(0, 50)); return APP.slice(i, j); };
const line = a => { const i = APP.indexOf(a); if (i < 0) throw new Error('줄을 못 찾음: ' + a); return APP.slice(i, APP.indexOf('\n', i)); };
const R = [];
const chk = (ok, msg, d) => R.push([!!ok, msg, ok ? undefined : d]);
const esc = t => String(t == null ? '' : t).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
// ── 가짜 history — pushState·replaceState 즉시 · back() = 다음 틱 popstate(브라우저와 같은 비동기) ──
const H = { st: [{ s: null }], i: 0, L: [] };
const history = { get state() { return H.st[H.i].s; },
  pushState(s) { H.st = H.st.slice(0, H.i + 1); H.st.push({ s }); H.i++; }, replaceState(s) { H.st[H.i] = { s }; },
  back() { if (H.i > 0) { H.i--; const s = H.st[H.i].s; setTimeout(() => H.L.slice().forEach(f => f({ state: s })), 0); } } };
const window = { addEventListener: (t, f) => { if (t === 'popstate') H.L.push(f); }, removeEventListener: (t, f) => { H.L = H.L.filter(x => x !== f); } };
const S = { sheet: null, drawer: null, pop: null, uiPg: {}, uiMore: {}, of: {}, hold: { mode: 'all', showZero: true }, D: null, pgSz: 20 };   // ui18: 아래 종전 검사 = 쪽 크기 20(종전 그대로)
const UI_SHEETS = { attd: () => '' };
const document = { querySelectorAll: () => [], activeElement: null };
const location = { href: 'https://tj.invalid/#dash', pathname: '/', search: '' };
const deps = { S, UI_SHEETS, history, window, document, location, esc, renderOverlay: () => {}, renderView: () => {}, $: () => null, setTimeout,
  nf: () => ({ format: v => Number(v).toLocaleString('en-US') }), IC: { chev: '<svg class="c"></svg>', right: '<svg class="r"></svg>' }, UI_CHEV: '<span class="uchev"></span>',
  uiHas: (o, k) => Object.prototype.hasOwnProperty.call(o, k), uiReduce: () => true, getComputedStyle: () => ({ getPropertyValue: () => '' }),
  q: v => String(v), m: v => '$' + v, locH: s => '<span class="pvl">' + esc(s) + '</span>' };
const B = [cut('  function uiSheetOpen(k, v, t, el) {', '  function uiSheetHTML() {'), line("  window.addEventListener('popstate', ev => { if (S.sheet"), line('  function drawerHist() {'),
  cut('  const uiWrapBtn = (b, o) =>', '  const uiHidChip = '), cut('  function zeroFoldHTML() {', '  const holdTh = (k, label, x) =>')].join('\n');
const acts = ['attdRc', 'attdCoin', 'attdFr'].map(k => line('      ' + k + ': el => {').trim().replace(/,$/, '')).join(',\n');
const ow = line('    ofWaitGo: () => {').trim().replace(/,(\s*\/\/.*)?$/, '');
const names = Object.keys(deps);
let A = {}, revealN = 0, frN = 0;
const F = new Function(...names, 'A', 'revealAndHighlight', 'openFutRcpt', 'toast', 'uiPgReset0', B + '\nconst ACT = {' + acts + ', ' + ow + '};\n'
  + 'return { uiSheetOpen, uiSheetClose, drawerHist, uiPgSlice, uiPgBar, uiPgReveal, uiPgReset, zeroFoldHTML, ACT };')(
  ...names.map(k => deps[k]), A, () => { revealN++; return Promise.resolve(true); }, () => { frN++; S.drawer = 'frcpt'; F0().drawerHist(); }, () => {}, null);
function F0() { return F; }
// 서랍 popstate(app.js 10937 과 같은 규칙 — 표식 없는 칸으로 돌아오면 서랍 닫기)
window.addEventListener('popstate', ev => { if (S.drawer && !(ev.state && ev.state.tjDr)) S.drawer = null; });
A.receipt = () => { const first = S.drawer !== 'rcpt'; S.drawer = 'rcpt'; if (first) F.drawerHist(); };   // openReceipt 의 기록 규칙 그대로
const tick = () => new Promise(r => setTimeout(r, 20));
(async () => {
  // ofWaitGo
  S.uiPg = { ofh: 3, ofp: 2 }; S.of = { view: 'pending', reason: '', period: '30d', coin: 'ETH', limit: 90 };
  F.ACT.ofWaitGo();
  chk(S.uiPg.ofh === 0 && S.uiPg.ofp === 2 && S.of.reason === '세일 참가금' && S.of.view === 'history',
    "세일 참가금만 보기 = 정리 내역(ofh) 첫 쪽 · 다른 목록 쪽 그대로", { pg: S.uiPg });
  // 분해 시트 → 차익 영수증 → 뒤로
  const base = H.i;
  F.uiSheetOpen('attd', 'd|10-10|rz', '현물 실현', null);
  const opened = H.i - base;
  F.ACT.attdRc({ dataset: { v: '2026-10-10|AAA' } }); await tick();
  const inRc = S.drawer === 'rcpt' && !S.sheet;
  history.back(); await tick();
  chk(opened === 1 && inRc && !S.drawer && H.i === base && !(history.state && history.state.tjDr),
    "분해 시트 → 차익 영수증 → '뒤로' 1번 = 서랍 닫힘 · 남는 빈 기록 칸 0(종전 1칸 — 다음 '뒤로'가 헛돎)", { opened, inRc, drawer: S.drawer, extra: H.i - base });
  // 분해 시트 → 선물 영수증
  F.uiSheetOpen('attd', 'd|10-10|rzf', '선물 실현', null);
  F.ACT.attdFr({ dataset: { v: '2026-10-10|binance' } }); await tick();
  const inFr = S.drawer === 'frcpt' && frN === 1;
  history.back(); await tick();
  chk(inFr && !S.drawer && H.i === base, "분해 시트 → 선물 영수증 → '뒤로' 1번 = 서랍 닫힘 · 빈 칸 0", { inFr, extra: H.i - base });
  // 분해 시트 → 보유 코인(같은 탭 — 찾아가기는 탭이 같으면 기록을 안 쌓음)
  F.uiSheetOpen('attd', 'd|10-10|mk', '시세', null);
  F.ACT.attdCoin({ dataset: { v: 'ETH' } }); await tick();
  chk(revealN === 1 && !S.sheet && H.i === base && !(history.state && history.state.tjDr), "분해 시트 → 보유 코인 = 시트 기록 칸 걷힘(빈 칸 0 — '뒤로'가 바로 앞 화면으로)", { revealN, extra: H.i - base });
  // 보유표 — Rabby 하위 행이 쪽 경계에 · rev1012(오너 10-12 '스테이킹된 것도 10개 안에 포함'): 줄 단위 — 하위 행은 다음 쪽 맨 위(한 쪽 = 정확히 쪽 크기).
  //   종전 ui17 기대(본행 쪽에 붙어 첫 쪽 21줄)는 쪽마다 줄 수가 달라 쪽 바 위치가 바뀌어 오너 지시로 바꿈
  const HR = Array.from({ length: 30 }, (_, i) => ({ g: { key: 'C' + i } })); HR.splice(20, 0, { g: { key: '#rb:C19' }, sub: true });   // 20번째 본행(C19) 바로 뒤
  S.uiPg = { hold: 0 };
  const p0 = F.uiPgSlice('hold', HR).rows;
  S.uiPg.hold = 1; const p1 = F.uiPgSlice('hold', HR).rows;
  chk(p0.length === 20 && p0[19].g.key === 'C19' && p1.length === 11 && p1[0].g.key === '#rb:C19' && p1[1].g.key === 'C20',
    'Rabby 하위 행(20번째 본행 C19 뒤) = 줄 단위 — 첫 쪽 정확히 20줄 · 하위 행은 둘째 쪽 맨 위', { p0: p0.slice(-1).map(r => r.g.key), p1: p1.slice(0, 2).map(r => r.g.key) });
  S.uiPg = {}; const hp = k => r => !!r && !!r.g && r.g.key === k;
  F.uiPgReveal('hold', hp('#rb:C19'));
  const pr = F.uiPgSlice('hold', HR).rows;
  chk(S.uiPg.hold === 1 && pr[0].g.key === '#rb:C19', '찾아가기(Rabby 하위 행 키) = 그 줄 쪽(둘째 쪽 맨 위)', S.uiPg);
  // 값 없는 토큰 45개
  S.D = { zeroInst: Array.from({ length: 45 }, (_, i) => ({ sym: 'Z' + i, key: 'k' + i, chain: 'Base', where: [], qty: i + 1, cost: 0 })) };
  S.uiPg = {}; S.hold = { mode: 'all', showZero: true };
  let h = F.zeroFoldHTML();
  const zi = h0 => (h0.match(/class="zi"/g) || []).length;
  chk(zi(h) === 20 && /1–20 <span class="mut">\/ 45<span class="upgu">개/.test(h) && /data-a="uiPg" data-v="zero" data-p="1" aria-label="다음 쪽"/.test(h) && !/uiPgOpen|uiPgClose|모두 보기/.test(h) && /data-pga="zero"/.test(h),
    "pg19: 값 없는 토큰 45개 펼침 = 바로 1–20 / 45 + '다음'(종전 앞 20개 + '45개 모두 보기' · 그 전엔 45개 한 번에) · 접기 단추 없음", zi(h));
  S.uiPg.zero = 1; h = F.zeroFoldHTML();
  chk(zi(h) === 20 && /21–40/.test(h) && /data-anc="zcoin:Z20"/.test(h) && !/data-anc="zcoin:Z19"/.test(h), '둘째 쪽 = 21–40(Z20~Z39)', zi(h));
  S.uiPg = {}; F.uiPgReveal('zero', x => !!x && String(x.sym).toUpperCase() === 'Z42'); h = F.zeroFoldHTML();
  chk(S.uiPg.zero === 2 && /data-anc="zcoin:Z42"/.test(h), '찾아가기(심볼 Z42) = 셋째 쪽', S.uiPg);
  S.D = { zeroInst: S.D.zeroInst.slice(0, 20) }; S.uiPg = {}; h = F.zeroFoldHTML();
  chk(zi(h) === 20 && !/upg|upga|umore/.test(h), '딱 한 쪽(20개 · 쪽 크기 20) = 쪽 바·앵커 없음', h.slice(-160));
  S.D = { zeroInst: Array.from({ length: 45 }, (_, i) => ({ sym: 'Z' + i, key: 'k' + i, chain: 'Base', where: [], qty: i + 1, cost: 0 })) };
  S.hold.showZero = false; h = F.zeroFoldHTML();
  chk(zi(h) === 0 && /값 없는 토큰/.test(h), '접힘 = 머리 한 줄만', h.slice(0, 80));
  // ui18: 쪽 크기 10(기본)
  S.pgSz = 10; S.uiPg = {}; S.hold = { mode: 'all', showZero: true }; h = F.zeroFoldHTML();
  chk(zi(h) === 10 && /1–10 <span class="mut">\/ 45/.test(h) && !/uiPgOpen|모두 보기/.test(h) && /data-pga="zero"/.test(h), "쪽 크기 10: 값 없는 토큰 펼침 = 바로 1–10 / 45 + 앵커(pg19)", zi(h));
  S.uiPg.zero = 1; h = F.zeroFoldHTML();
  chk(zi(h) === 10 && /11–20/.test(h) && /data-anc="zcoin:Z10"/.test(h) && !/data-anc="zcoin:Z20"/.test(h), '쪽 크기 10: 둘째 쪽 = 11–20', zi(h));
  S.uiPg = {}; F.uiPgReveal('zero', x => !!x && String(x.sym).toUpperCase() === 'Z42'); h = F.zeroFoldHTML();
  chk(S.uiPg.zero === 4 && /data-anc="zcoin:Z42"/.test(h), '쪽 크기 10: 찾아가기(Z42) = 다섯째 쪽', S.uiPg);
  const HR2 = Array.from({ length: 30 }, (_, i) => ({ g: { key: 'C' + i } })); HR2.splice(10, 0, { g: { key: '#rb:C9' }, sub: true });
  S.uiPg = { hold: 0 }; const r0 = F.uiPgSlice('hold', HR2).rows; S.uiPg.hold = 1; const r1 = F.uiPgSlice('hold', HR2).rows;
  chk(r0.length === 10 && r0[9].g.key === 'C9' && r1.length === 10 && r1[0].g.key === '#rb:C9' && r1[1].g.key === 'C10', '쪽 크기 10: Rabby 하위 행(10번째 본행 C9 뒤) = 첫 쪽 정확히 10줄 · 하위 행은 둘째 쪽 맨 위(rev1012)', r0.slice(-1).concat(r1.slice(0, 2)).map(r => r.g.key));
  S.pgSz = 20;
  for (const [ok, msg, d] of R) console.log((ok ? 'PASS ' : 'FAIL ') + msg + (ok || d === undefined ? '' : '  — ' + JSON.stringify(d).slice(0, 600)));
  console.log('RESULT ' + R.filter(x => x[0]).length + '/' + R.length);
})().catch(e => { console.log('FAIL 실행 오류 ' + (e && e.stack || e)); console.log('RESULT 0/1'); });
'''
NODE = shutil.which("node")
if not NODE:
    print("SKIP node 없음 — 화면 함수 동작 시험 건너뜀")
else:
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_")}
    env["TJ_TEST_APP"] = APP
    p = subprocess.run([NODE, "--input-type=module", "-"], input=JS, env=env, cwd=T.TMP, capture_output=True, text=True, encoding="utf-8", timeout=120)
    lines = (p.stdout or "").splitlines()
    got = [ln for ln in lines if ln.startswith(("PASS ", "FAIL "))]
    for ln in got:
        T.chk(ln.startswith("PASS "), ln[5:])
    T.chk(p.returncode == 0 and got and any(ln.startswith("RESULT ") for ln in lines), "node 화면 함수 시험이 끝까지 돌았음", (p.stderr or "")[-600:])
T.finish()
