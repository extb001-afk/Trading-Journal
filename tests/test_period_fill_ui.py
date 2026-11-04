#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import os  # noqa: E402
import subprocess  # noqa: E402

JS = r'''import fs from 'node:fs';
const APP = fs.readFileSync(process.env.TJ_TEST_APP, 'utf8');
const cut = (a, b) => { const i = APP.indexOf(a), j = i < 0 ? -1 : APP.indexOf(b, i + 1); if (i < 0 || j < 0) throw new Error('블록을 못 찾음: ' + a.slice(0, 50)); return APP.slice(i, j); };
const cutFn = a => { const i = APP.indexOf(a); if (i < 0) throw new Error('블록을 못 찾음: ' + a); const j = APP.indexOf('\n  function ', i + 1); return APP.slice(i, j); };
const R = [];
const chk = (ok, msg, d) => R.push([!!ok, msg, ok ? undefined : d]);
const num = x => (isFinite(+x) ? +x : 0), arr = x => (Array.isArray(x) ? x : []);
const esc = t => String(t == null ? '' : t).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const tick = () => new Promise(r => setTimeout(r, 0));
const cnt = (h, re) => (h.match(re) || []).length;

// ── (a) 가스·수수료 ──
{
  const S = { D: null, g: { period: 'custom', from: '2026-10-05', to: '2026-10-20' } };
  const gBounds = () => S.g.period === 'all' ? null : S.g.period === 'thismonth' ? { lo: '2026-10-01', hi: '2026-10-31' }
    : S.g.period === 'lastmonth' ? { lo: '2026-09-01', hi: '2026-09-31' } : S.g.period === '90d' ? { lo: '2026-07-24', hi: '2026-10-22' } : { lo: S.g.from, hi: S.g.to };
  const gPass = iso => { const b = gBounds(); return !b || (iso >= b.lo && iso <= b.hi); };
  const ymPass = ym => { const b = gBounds(); return !b || (ym >= b.lo.slice(0, 7) && ym <= b.hi.slice(0, 7)); };
  const periodName = () => 'P';
  const G = new Function('S', 'gBounds', 'gPass', 'ymPass', 'periodName', 'num', 'arr', cut('  const gasMonthly = ', '  const popBox = ') + '\nreturn { gasList, gasScope };');
  const X = G(S, gBounds, gPass, ymPass, periodName, num, arr);
  const BYM = { '2026-09': [{ chain: 'Base', spot: 10, tx: 2 }, { chain: '업비트 출금 수수료', spot: 3, tx: 1, kind: 'exfee', ex: 'upbit' }],
    '2026-10': [{ chain: 'Base', spot: 20, tx: 4 }, { chain: 'Arbitrum', spot: 5, tx: 1 }] };
  const BYD = { '2026-09-15': [{ chain: 'Base', spot: 4, tx: 1 }, { chain: '업비트 출금 수수료', spot: 3, tx: 1, kind: 'exfee', ex: 'upbit' }], '2026-09-28': [{ chain: 'Base', spot: 6, tx: 1 }],
    '2026-10-03': [{ chain: 'Base', spot: 8, tx: 2 }], '2026-10-10': [{ chain: 'Base', spot: 12, tx: 2 }, { chain: 'Arbitrum', spot: 5, tx: 1 }] };
  const row = (L, c) => L.find(g => g.chain === c) || {};
  const tot = L => L.reduce((s, g) => s + g.spot + g.lp, 0);
  S.D = { gasByMonth: BYM, gasByDate: BYD, gasByChain: [] };
  let L = X.gasList();
  chk(tot(L) === 17 && row(L, 'Base').spot === 12 && row(L, 'Base').tx === 2 && row(L, 'Arbitrum').spot === 5 && L.length === 2, 'J1 직접 지정(10/5~10/20) = 날짜별 정확 합 $17(종전 월 버킷 $25)', L);
  chk(X.gasScope() === 'P', "J1 직접 지정 '≈' 없음(정확)", X.gasScope());
  S.g.period = 'thismonth'; L = X.gasList();
  chk(tot(L) === 25 && row(L, 'Base').tx === 4 && X.gasScope() === 'P', 'J2 이번 달 = 월 버킷 그대로 $25', L);
  S.g.period = 'lastmonth'; L = X.gasList();
  chk(tot(L) === 13 && row(L, '업비트 출금 수수료').kind === 'exfee' && X.gasScope() === 'P', 'J2 지난 달 = 월 버킷 $13(거래소 줄 보존)', L);
  S.g.period = 'all'; L = X.gasList();
  chk(tot(L) === 38 && L.length === 3 && X.gasScope() === 'P', 'J2 전체 = 월 버킷 전부 $38', L);
  S.g.period = '90d'; L = X.gasList();
  chk(tot(L) === 38 && row(L, 'Base').tx === 6 && X.gasScope() === 'P', "J3 최근 3개월 = 날짜별 합(경계 날짜로) · '≈' 없음", L);
  S.D = { gasByMonth: BYM, gasByDate: null, gasByChain: [] };
  S.g.period = 'custom'; L = X.gasList();
  chk(tot(L) === 25 && X.gasScope() === '≈ P', "J4 옛 서버(날짜별 없음) 직접 지정 = 월 버킷 근사 + '≈'", [L, X.gasScope()]);
  S.g.period = '90d';
  chk(X.gasScope() === '≈ P' && tot(X.gasList()) === 38, "J4 옛 서버 최근 3개월도 '≈'(종전엔 표식 없이 근사)", X.gasScope());
  S.g.period = 'thismonth';
  chk(X.gasScope() === 'P' && tot(X.gasList()) === 25, "J4 옛 서버 달 단위 = 정확 · '≈' 없음");
  const BYD2 = {}; Object.keys(BYD).forEach(k => { if (k >= '2026-10') BYD2[k] = BYD[k]; });
  S.D = { gasByMonth: BYM, gasByDate: BYD2, gasByChain: [] };
  S.g = { period: 'custom', from: '2026-09-20', to: '2026-10-10' };
  chk(X.gasScope() === '≈ P' && tot(X.gasList()) === 38, "J5 날짜별 줄이 기간 앞쪽(9월)을 못 덮으면 월 버킷 + '≈'", [X.gasScope(), X.gasList()]);
  S.g = { period: 'custom', from: '2026-10-05', to: '2026-10-10' };
  chk(X.gasScope() === 'P' && tot(X.gasList()) === 17, 'J5 기간이 날짜별 범위 안이면 정확', [X.gasScope(), X.gasList()]);
  S.D = { gasByMonth: null, gasByDate: null, gasByChain: [{ chain: 'Base', spot: 1, lp: 0, tx: 1 }] };
  chk(X.gasScope() === '전체 누적' && X.gasList().length === 1, 'J6 월 버킷도 없는 옛 서버 = 전체 누적');
}

// ── (b) 보관처 서랍 ──
{
  const S = { D: { builtAt: 11, vflows: { days: 30, flowOk: true, by: { '업비트': { in: 100, out: 50, realized: 10, realizedKrw: 14000 } } } }, drawer: 'venue' };
  const calls = [], RESP = { v: null };
  const fetch = url => { calls.push(url); return Promise.resolve({ ok: !!RESP.v, json: () => Promise.resolve(RESP.v) }); };
  let painted = 0; const renderOverlay = () => { painted++; };
  const uiCell = (l, v) => '<c>' + l + '=' + v + '</c>';
  const m = v => 'M' + v, KV = u => u, clsV = () => 'cv', vnSrc = () => ({ mode: 'cex', key: 'upbit' });
  const V = new Function('S', 'fetch', 'renderOverlay', 'uiCell', 'm', 'KV', 'clsV', 'vnSrc', 'num', 'esc',
    cut('  const VN_DAYS = ', '  function vnSrc(M) {') + '\nreturn { vnFlows };');
  const X = V(S, fetch, renderOverlay, uiCell, m, KV, clsV, vnSrc, num, esc);
  const M = { v: { name: '업비트', kind: 'cex' } };
  let h = X.vnFlows(M);
  chk(h.indexOf('드나든 돈 · 최근 30일') > 0 && h.indexOf('들어옴=<span class="up">+M100</span>') > 0 && h.indexOf('나감=<span class="down">−M50</span>') > 0
    && h.indexOf('이곳 매매 실현=<span class="cv">M10</span>') > 0 && calls.length === 0, 'V1 기본 30일 = 상태 재료 그대로 · 요청 없음', h);
  chk(cnt(h, /data-a="vnDays"/g) === 4 && h.indexOf('data-v="30" class="on" aria-pressed="true"') > 0 && h.indexOf('data-a="venueRec"') > 0, 'V1 기간 칩 4개(30일 켜짐) · 이곳 기록 보기 그대로', h);
  S.vn.days = 7; RESP.v = { ok: true, days: 7, since: '2026-10-17', flowOk: true, flowFrom: '2026-09-24', by: { '업비트': { in: 20, out: 0, realized: 3, realizedKrw: 4200 } } };
  h = X.vnFlows(M);
  chk(calls.length === 1 && calls[0] === '/api/venue_flows?days=7' && h.indexOf('최근 7일') > 0 && cnt(h, /…/g) === 3, 'V2 7일 = /api/venue_flows?days=7 요청 · 받는 동안 …', [calls, h]);
  await tick(); await tick(); await tick();
  chk(painted === 1, 'V2 답이 오면 서랍 다시 그림(1번)', painted);
  h = X.vnFlows(M);
  chk(calls.length === 1 && h.indexOf('+M20') > 0 && h.indexOf('나감=<span class="">M0</span>') > 0 && h.indexOf('M3</span>') > 0 && h.indexOf('data-v="7" class="on"') > 0, 'V2 캐시된 답으로 그림(같은 빌드 = 재요청 없음)', h);
  chk(h.indexOf('부터') < 0, 'V2 7일 = flowFrom 이 since 앞이면 안내 없음', h);
  S.vn.days = 0; RESP.v = { ok: true, days: 0, since: null, flowOk: true, flowFrom: '2026-01-01', by: { '업비트': { in: 500, out: 10, realized: 7, realizedKrw: 9800 } } };
  X.vnFlows(M); await tick(); await tick(); await tick(); h = X.vnFlows(M);
  chk(calls[1] === '/api/venue_flows?days=0' && h.indexOf('전체 기간') > 0 && h.indexOf('들어옴·나감은 2026-01-01 부터(가격 기록 있는 날만) · 실현은 기간 전체') > 0, 'V3 전체 = days=0 · 가격 기록 시작 안내', h);
  S.vn.days = 90; RESP.v = null;
  X.vnFlows(M); await tick(); await tick(); await tick(); h = X.vnFlows(M);
  chk(calls[2] === '/api/venue_flows?days=90' && h.indexOf('불러오지 못했어요') > 0 && cnt(h, /<span class="mut">—<\/span>/g) === 3, 'V4 실패 = 안내 + — 3칸', h);
  S.D.builtAt = 12; X.vnFlows(M);
  chk(calls.length === 4 && calls[3] === '/api/venue_flows?days=90', 'V5 새 빌드(builtAt) = 다시 요청', calls);
  S.vn.days = 30; h = X.vnFlows({ v: { name: 'LP 풀', kind: 'lp' } });
  chk(h.indexOf('data-a="vnDays"') < 0 && cnt(h, /<span class="mut">—<\/span>/g) === 3, 'V6 LP 보관처 = 칩 없음 · —', h);
  // V7 새 빌드 = 캐시는 최신 빌드 것만 · 옛 빌드의 늦은 답은 버림
  S.vn.days = 7; RESP.v = { ok: true, days: 7, since: '2026-10-17', flowOk: true, flowFrom: '2026-09-24', by: { '업비트': { in: 1, out: 0, realized: 0, realizedKrw: 0 } } };
  S.D.builtAt = 20; X.vnFlows(M); const n20 = calls.length;
  S.D.builtAt = 21; X.vnFlows(M);
  await tick(); await tick(); await tick();
  chk(calls.length === n20 + 1 && S.vn.ver === '21' && Object.keys(S.vn.cache).join() === '7' && S.vn.cache['7'] === RESP.v && S.vn.busy === '',
    'V7 새 빌드 = 캐시 비우고 다시 요청 · 캐시는 최신 빌드 기간별만 · 옛 빌드 답 버림', [calls.length - n20, S.vn.ver, Object.keys(S.vn.cache)]);
  // V8 실패 = 캐시 안 함 · 그리기마다 재요청도 없음 · 칩 다시 고르면(표식 지움) 다시 요청
  S.vn.days = 90; RESP.v = null; X.vnFlows(M); await tick(); await tick(); await tick();
  const n90 = calls.length; h = X.vnFlows(M); X.vnFlows(M);
  chk(calls.length === n90 && h.indexOf('불러오지 못했어요') > 0 && !('90' in S.vn.cache) && S.vn.fail['90'] === true, 'V8 실패는 캐시 안 함 · 그리기만으론 재요청 없음(표식)', [calls.length - n90, Object.keys(S.vn.cache)]);
  delete S.vn.fail['90']; RESP.v = { ok: true, days: 90, since: '2026-07-26', flowOk: true, flowFrom: '2026-07-26', by: { '업비트': { in: 9, out: 0, realized: 0, realizedKrw: 0 } } };
  X.vnFlows(M); await tick(); await tick(); await tick(); h = X.vnFlows(M);
  chk(calls.length === n90 + 1 && h.indexOf('+M9') > 0 && S.vn.cache['90'] === RESP.v, 'V8 칩 다시 고르면(vnDays 가 표식 지움) 다시 요청해 받음', [calls.length - n90, h.slice(0, 200)]);
  // V9 partial(창 밖 일부 실패) = 보여 주되 성공 캐시 밖 · 그리기만으론 재요청 없음 · 칩 다시 고르면 재요청
  S.vn.days = 0; RESP.v = { ok: true, days: 0, since: null, flowOk: true, flowFrom: '2026-09-24', partial: true, by: { '업비트': { in: 4, out: 0, realized: 0, realizedKrw: 0 } } };
  X.vnFlows(M); await tick(); await tick(); await tick(); const np = calls.length; h = X.vnFlows(M); X.vnFlows(M);
  chk(calls.length === np && h.indexOf('아직 못 셌어요') > 0 && h.indexOf('+M4') > 0 && !('0' in S.vn.cache) && S.vn.part['0'] === RESP.v,
    'V9 partial = 안내 + 창 안 값 표시 · 성공 캐시 밖 · 재요청 없음', [calls.length - np, Object.keys(S.vn.cache)]);
  delete S.vn.part['0']; RESP.v = { ok: true, days: 0, since: null, flowOk: true, flowFrom: '2026-01-01', by: { '업비트': { in: 44, out: 0, realized: 0, realizedKrw: 0 } } };
  X.vnFlows(M); await tick(); await tick(); await tick(); h = X.vnFlows(M);
  chk(calls.length === np + 1 && h.indexOf('+M44') > 0 && S.vn.cache['0'] === RESP.v, 'V9 칩 다시 고르면 재요청 · 온전한 답은 캐시', [calls.length - np]);
}

// ── (c) 습관 ──
{
  const S = { tab: 'journal', j: { view: 'habits' } };
  const calls = []; let resolve9 = null;
  const fetch = url => { calls.push(url); return new Promise(r => { resolve9 = j => r({ ok: true, json: () => Promise.resolve(j) }); }); };
  let rv = 0; const renderView = () => { rv++; };
  const IC = { cal: '<i/>', undo: '<u/>' };
  const cls = v => (v > 0 ? 'up' : v < 0 ? 'down' : ''), pvm = s => s, m = v => 'M' + v, pctS = v => v + '%';
  const noT = () => 0;
  const H = new Function('S', 'fetch', 'renderView', 'IC', 'cls', 'pvm', 'm', 'pctS', 'esc', 'arr', 'num', 'setTimeout', 'clearTimeout',
    cut('  function habLoad(force) {', '  function habitsHTML() {') + cutFn('  function habitsHTML() {') + '\nreturn { habLoad, habitsHTML };');
  const X = H(S, fetch, renderView, IC, cls, pvm, m, pctS, esc, arr, num, noT, noT);
  let h = X.habitsHTML();
  chk(calls.length === 1 && calls[0] === '/api/habits' && S.hab.st === 'loading', 'H1 기본(1년) = /api/habits 인자 없음(종전 요청 그대로)', calls);
  chk(cnt(h, /data-a="habPer"/g) === 4 && h.indexOf('data-v="1y" class="on"') > 0 && h.indexOf('지난 1년') > 0 && h.indexOf('습관을 모으는 중') > 0, 'H1 받는 중 카드에도 기간 칩 4개(1년 켜짐)', h);
  S.hab.per = '3m'; S.hab.d = null; S.hab.st = ''; S.hab.at = 0; X.habLoad(true);
  chk(calls.length === 2 && calls[1] === '/api/habits?days=90', 'H2 3개월 = ?days=90', calls);
  const late = resolve9;
  S.hab.per = 'all'; S.hab.d = null; S.hab.st = ''; S.hab.at = 0; X.habLoad(true);
  chk(calls.length === 3 && calls[2] === '/api/habits?days=0', 'H2 전체 = ?days=0', calls);
  const GRID = Array.from({ length: 7 }, () => Array.from({ length: 12 }, () => [0, 0, 0]));
  GRID[0][5] = [6, 4, 120.5];
  const D1 = { ok: true, n: 6, win: 4, grid: GRID, hold: [{ k: '1주 안', cost: 100, pnl: 10, n: 6 }], next: [2, 4], nextAvg: 1.5, cov: { next: 0.5, pxAt: '2026-10-22' }, excl: {}, since: '', days: 0 };
  late(D1); await tick(); await tick(); await tick();
  chk(S.hab.d === null && S.hab.st === 'loading', 'H3 기간을 바꾼 뒤 늦게 온 옛 기간(3개월) 답은 버림', S.hab);
  resolve9(D1); await tick(); await tick(); await tick();
  chk(S.hab.d === D1 && S.hab.st === 'ok' && rv >= 1, 'H3 지금 기간(전체) 답은 받음 · 화면 다시 그림');
  h = X.habitsHTML();
  chk(h.indexOf('나의 매매 습관 · 전체 기간 · 매도 6묶음') > 0 && h.indexOf('data-v="all" class="on"') > 0 && cnt(h, /data-a="habPer"/g) === 4 && h.indexOf('hbg') > 0, 'H4 본 화면 머리 = 기간 이름 + 묶음 수 + 칩', h);
  S.hab.d = Object.assign({}, D1, { n: 0 }); S.hab.per = '6m';
  h = X.habitsHTML();
  chk(h.indexOf('지난 6개월 매도가 쌓이면') > 0 && h.indexOf('data-v="6m" class="on"') > 0, 'H5 빈 상태 = 기간 이름 + 칩', h);
}
for (const [ok, msg, d] of R) console.log((ok ? 'PASS ' : 'FAIL ') + msg + (ok ? '' : '  — ' + JSON.stringify(d).slice(0, 700)));
console.log('RESULT ' + R.filter(x => x[0]).length + '/' + R.length);
'''

APP = T.app_js_path()
app = open(APP, encoding="utf-8").read()
print("[1] 되돌려 붙인 app.js 있음")
T.chk(len(app) > 1000, "화면 글(app.js + tab_*.js)을 읽음", len(app))

print("[2] 화면 함수(node)")
NODE = T.node_bin("화면 함수 동작 시험")
if NODE:
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_")}
    env["TJ_TEST_APP"] = APP
    p = subprocess.run([NODE, "--input-type=module", "-"], input=JS, env=env, cwd=T.TMP, capture_output=True, text=True, encoding="utf-8", timeout=120)
    lines = (p.stdout or "").splitlines()
    got = [ln for ln in lines if ln.startswith(("PASS ", "FAIL "))]
    for ln in got:
        T.chk(ln.startswith("PASS "), ln[5:])
    T.chk(p.returncode == 0 and got and any(ln.startswith("RESULT ") for ln in lines), "node 화면 함수 시험이 끝까지 돌았음", (p.stderr or "")[-900:])
T.finish()
