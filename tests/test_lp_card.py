#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import os
import re
import shutil
import subprocess

JS = r'''// 대시보드 LP 카드 + 레버리지 · 대출 2줄 — 실제 app.js 블록(normLP · uiMore·uiPaged(uipage1011 쪽 넘김) · LP · 레버리지)을 가짜 의존성으로 돌린다(브라우저·서버·네트워크 없음)
import fs from 'node:fs';
const APP = fs.readFileSync(process.env.TJ_TEST_APP, 'utf8');
const cut = (a, b) => { const i = APP.indexOf(a), j = i < 0 ? -1 : APP.indexOf(b, i + 1); if (i < 0 || j < 0) throw new Error('블록을 못 찾음: ' + a.slice(0, 50)); return APP.slice(i, j); };
// 블록 경계 = 코드 줄만(주석 글자 금지 — 공개판 빌드는 주석을 지우므로 주석에 기대면 공개판에서만 실패한다)
const B = [cut('  const CHAIN_KO = {', '  function normFlow(f) {'), cut('  const uiLim = (key, n)', '  const uiHidChip = '),
  cut('  const pxrRaw = v =>', '  function venuesHTML() {'), cut('  function levS() {', '  function oaLoad(force) {')].join('\n');
const R = [];
const chk = (ok, msg, d) => R.push([!!ok, msg, ok ? undefined : d]);
const S = { D: null, mobile: false, hide: false, rand: false, cur: 'USD', uiMore: {}, uiPg: {}, lpOpen: new Set(), lpClosed: false, justOpened: new Set(), tab: 'dash', drawer: null };
const K = 2.5;   // 랜덤값 배수(합성)
const esc = t => String(t == null ? '' : t).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const num = x => (isFinite(+x) ? +x : 0), arr = x => (Array.isArray(x) ? x : []);
const nf = () => ({ format: v => Number(v).toLocaleString('en-US') });
const fmt = v => { const a = Math.abs(v), d = a >= 100 || a === 0 ? 0 : 2; return a.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d }); };
const mk = t => (S.rand ? '' + t + '' : t);
const m = (v, o) => { o = o || {}; if (v == null || !isFinite(v)) return '—'; if (S.rand) v *= K; const s = o.sign ? (v > 0 ? '+' : v < 0 ? '−' : '') : (v < 0 ? '−' : '');
  return S.hide ? s + '$' + (o.compact ? '88.8K' : '88,888') + '' : s + '$' + mk(fmt(v)); };
const q = v => (S.hide ? '8,888.88' : mk(fmt(S.rand ? v * K : v)));
const deps = {
  S, A: {}, esc, num, arr, nf, m, q, hq: t => '8', px: v => (S.hide ? '$8.8888' : '$' + mk(String(v))), trimZeros: s => String(s).replace(/\.?0+$/, ''),
  parseMoney: t => +String(t).replace(/[^\d.\-]/g, ''), pvW: s => '' + s + '', PVM: { px: '8.8888', q: '8,888.88' }, rw: mk,
  sum: (a, f) => a.reduce((s, x) => s + (f ? f(x) : x), 0), cls: v => (v > 0 ? 'up' : v < 0 ? 'down' : 'mut'), clsV: v => (v > 0 ? 'up' : v < 0 ? 'down' : 'mut'), KV: v => v,
  pctS: (v, d) => (v == null || !isFinite(v) ? '—' : (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d == null ? 1 : d) + '%'),
  fmtTs: () => '10-01 12:00', clps: (k, h) => '<div class="clps" data-ck="' + esc(k) + '"><div>' + h + '</div></div>',
  icon: s => '<span class="ic sm">' + esc(String(s).slice(0, 1)) + '</span>', evPill: k => '<span class="pill">' + esc(k) + '</span>', evA: () => '', hs: t => t,
  IC: { right: '<svg class="r"></svg>', chev: '<svg class="c"></svg>', close: '×', info: '<svg></svg>' }, UI_CHEV: '<span class="uchev"></span>',
  uiHas: (o, k) => Object.prototype.hasOwnProperty.call(o, k), fetch: () => Promise.resolve({ status: 404 }), onUnauthorized: () => {}, renderView: () => {}, renderOverlay: () => {}, renderAuto: () => {},
  ago: () => '방금', errTxt: t => String(t), uiFold: (k, o) => o.head + o.body(), uiCell: (l, v) => '<div class="ucell">' + l + v + '</div>', exLogo: () => '', vib: () => {}, drawerHist: () => {}, $: () => null,
  document: { activeElement: null, querySelectorAll: () => [], hidden: false }, setInterval: () => 0, exLinked: () => true,
};
const names = Object.keys(deps);
const F = new Function(...names, B + '\nreturn { normLP, lpCardHTML: typeof lpCardHTML === "function" ? lpCardHTML : null, lpSorted: typeof lpSorted === "function" ? lpSorted : null, levS, levHTML };')(...names.map(k => deps[k]));

// ── 합성 LP(둥근 값 · 서버 순서는 일부러 섞음) ──
const oc = (s0, s1, lo, hi, p, inR) => ({ sym0: s0, sym1: s1, amount0: 1, amount1: 100, priceLower: lo, priceUpper: hi, price: p, inRange: inR, fee: 500 });
const L = (key, id, pool, dex, chain, value, principal, fees, extra) => Object.assign({ key, id, pool, dex, chain, value, principal, deposit: principal, fees, onchain: oc(pool.split(' / ')[0], pool.split(' / ')[1], 10, 20, 15, true) }, extra || {});
const LIVE = [
  L('lp:b', '9184', 'USDT / USDC', 'Uniswap V4', 'Ethereum', 490, 490, 11.4),
  L('lp:a', '51022', 'cbBTC / USDC', 'Aerodrome Slipstream', 'Base', 12480, 12170, 142.1, { rewards: 7.5, staked: '0x' + 'ab'.repeat(20) }),
  L('lp:g', '9185', 'USDE / USDC', 'Uniswap V4', 'Ethereum', 490, 490, 11.4),   // b 와 같은 가치 — 서버 순서(b 먼저) 유지
  L('lp:c', '84213', 'USDC / WETH', 'Uniswap V4', 'Base', 17500, 17500, 0, { onchain: oc('USDC', 'WETH', 10, 20, 25, false) }),
  L('lp:d', '7721', 'WBNB / USDT', 'PancakeSwap V3', 'BSC', 4920, 5010, 61.4),
  L('lp:e', 'DLMM', 'SOL / USDC', 'Meteora DLMM', 'Solana', 2730, 2600, 48.2),
  L('lp:f', '330194', 'ETH / USDC', 'Uniswap V3', 'Arbitrum', 1240, 1300, 22.9, { onchain: oc('ETH', 'USDC', 10, 20, 5, false) }),
];
const CLOSED = [
  { key: 'lp:x1', id: '1001', dex: 'Uniswap V4', chain: 'Base', closed: true, deposited: 3000, pair: ['WETH', 'USDC'], realizedByDay: { '2026-10-01': 35.25 } },
  { key: 'lp:x2', id: '1002', dex: 'Uniswap V4', chain: 'Base', closed: true, deposited: 1500, pair: ['WETH', 'USDC'], realizedByDay: {} },
  { key: 'lp:x3', id: '7Hk2…9fQ', dex: 'Meteora DLMM', chain: 'Solana', closed: true, deposited: 800, pair: ['SOL', 'USDC'], realizedByDay: { '2026-09-20': -12.5 } },
];
const setD = (live, closed) => { const lps = live.map(F.normLP), cl = closed.map(F.normLP);
  S.D = { lps, lpsClosed: cl, events: [], lpValue: lps.reduce((s, l) => s + num(l.value), 0), lpFees: lps.reduce((s, l) => s + num(l.fees), 0), lpRewards: lps.reduce((s, l) => s + num(l.rewards), 0) }; };
const reset = () => { S.mobile = false; S.hide = false; S.rand = false; S.uiMore = {}; S.uiPg = {}; S.lpOpen = new Set(); S.lpClosed = false; };
const keysOf = h => [...h.matchAll(/class="lp[rm](?: lpc)?(?: open)?" role="button" tabindex="0" data-a="lpTog" data-k="([^"]+)"/g)].map(x => x[1]);
const moreBtn = h => { const x = h.match(/data-a="uiPgOpen" data-v="lp:dash"[^>]*>([\s\S]*?)<span class="uchev"/); return x ? x[1].replace(/<[^>]+>/g, '') : null; };

if (!F.lpCardHTML) chk(false, 'LP 카드 함수(lpCardHTML) 없음 — 대시보드 LP 카드 시험 못 함');
else {
reset(); setD(LIVE, CLOSED);
const ORDER = ['lp:c', 'lp:a', 'lp:d', 'lp:e', 'lp:f', 'lp:b', 'lp:g'];
chk(F.lpSorted(S.D.lps).map(l => l.key).join() === ORDER.join(), '정렬 = 현재 가치(가치 + 미청구 + 리워드) 큰 순 · 같은 값은 서버 순서', F.lpSorted(S.D.lps).map(l => l.key));
let h = F.lpCardHTML();
chk(/<section class="card lpk" aria-label="LP 포지션">/.test(h) && /<h2>LP 포지션<\/h2>/.test(h), '넓은 화면 = LP 카드(머리 + 제목)', h.slice(0, 200));
chk(keysOf(h).join() === 'lp:c,lp:a', '처음엔 가치 큰 2개만(lp:c · lp:a)', keysOf(h));
chk(/<span class="lvp pvx">운용 중 7<\/span>/.test(h) && /<span class="lvp num">가치 \$39,850<\/span>/.test(h) && /<span class="lvp num">미청구 \$305<\/span>/.test(h), "머리 칩 = 운용 중 7 · 가치 $39,850 · 미청구 $305(수수료 + 리워드)", h.match(/<div class="lvh">[\s\S]*?<\/div>/)[0]);
chk(/가치 큰 순/.test(h), "머리 '가치 큰 순'");
chk(moreBtn(h) === '5개 더 · WBNB / USDT · SOL / USDC 외 · 합 $9,870', "더보기 = '5개 더 · 풀 이름 2개 외 · 합 $(가치 합)'", moreBtn(h));
chk(/class="umore lvmore"/.test(h), '더보기 = 레버리지와 같은 점선 단추(umore lvmore)');
chk(/class="lpr lphd" aria-hidden="true"><span>풀<\/span><span>범위 · 현재가<\/span><span class="lpv">현재 가치<\/span><span class="lpv lpf">미청구 수수료<\/span><span class="lpv lpp">평가손익<\/span>/.test(h), '넓은 화면 칸 이름 줄');
chk(/data-a="lpClosed" aria-expanded="false"><span class="pvx">종료된 포지션 3개<\/span>/.test(h) && !/lpr lpc/.test(h), "종료 링크 '종료된 포지션 3개'(접힘 = 종료 행 없음)", h.match(/data-a="lpClosed"[^<]*<[^<]*/));
chk(/범위 이탈/.test(h) && /class="lprng"/.test(h) && /<span class="cap">원가 \$17,500<\/span>/.test(h), '줄 = 범위 상태 칩 + 막대 · 현재 가치 아래 원가');
chk(/리워드 \$7\.50/.test(h) && /스테이킹/.test(h) && /Aerodrome CL/.test(h), '미청구 아래 리워드 · lpBadge(프로토콜 짧은 이름 · 스테이킹) 유지');
S.uiPg['lp:dash'] = 0; h = F.lpCardHTML();
chk(keysOf(h).join() === ORDER.join() && /data-a="uiPgClose" data-v="lp:dash"[^>]*><span class="upgxt">접기/.test(h), "'N개 더' 누름 = 7개 모두(가치 큰 순 · 20개 이하 = 한 쪽) + '접기'", keysOf(h));
delete S.uiPg['lp:dash'];
S.lpOpen.add('lp:a'); h = F.lpCardHTML();
chk(/data-k="lp:a" aria-expanded="true">[\s\S]*?<\/div><div class="clps" data-ck="lp:lp:a"><div><div class="lpx">[\s\S]*?LP 이벤트/.test(h), '줄을 누르면(S.lpOpen) 그 줄 바로 아래 제자리 펼침(lpDetail)');
S.lpOpen.add('lp:f'); h = F.lpCardHTML();
chk(!/data-ck="lp:lp:f"/.test(h), '접힌 줄(더보기 안쪽)의 펼침은 그리지 않음');
S.lpOpen = new Set(); S.lpClosed = true; h = F.lpCardHTML();
const cRows = keysOf(h).filter(k => /^lp:x/.test(k));
chk(cRows.join() === 'lp:x1,lp:x2,lp:x3' && /data-a="lpClosed" aria-expanded="true">종료된 포지션 숨기기/.test(h), "종료 링크 누름 = 목록 아래 종료 행 3 + 링크 '숨기기'", cRows);
chk(/<div class="lpcs"><span class="cap"><span class="pvx">종료된 포지션 3개 · 인출 완료<\/span> · 실현 합 \+\$22\.75<\/span><span class="lpcp pvx"><span class="pill g sm lpb">Uni v4 2<\/span> <span class="pill g sm lpb">Meteora DLMM 1<\/span><\/span>/.test(h), '종료 구분 줄 = 개수 · 인출 완료 · 실현 합 · 프로토콜별 개수(pvx)', (h.match(/<div class="lpcs">[\s\S]*?<\/button><\/div>/) || [''])[0]);
chk(h.indexOf('lp:x1') > h.indexOf('data-v="lp:dash"'), '종료 행 = 운용 중 목록(더보기 단추) 아래');
chk(/인출 완료/.test(h) && /예치 \$3,000/.test(h) && /실현 없음/.test(h), '종료 행 = 인출 완료 · 예치 · 실현(없음)');
// 빈 상태 · 종료만 · 하나만
reset(); setD([], []);
chk(F.lpCardHTML() === '', '운용 중·종료 둘 다 0 = 카드 없음');
setD([], CLOSED); h = F.lpCardHTML();
chk(/card lpk lpone/.test(h) && !/class="lprows"/.test(h) && /운용 중인 포지션 없음/.test(h) && /종료된 포지션 3개/.test(h) && !/가치 큰 순/.test(h), '종료만 = 머리만 있는 작은 카드(종료 링크)', h);
S.lpClosed = true; h = F.lpCardHTML();
chk(keysOf(h).length === 3, '종료만 · 링크 누름 = 종료 행 3');
reset(); setD([LIVE[0]], []); h = F.lpCardHTML();
chk(keysOf(h).length === 1 && !/uiMore|uiPg/.test(h) && !/가치 큰 순/.test(h) && !/lpClosed/.test(h), '운용 중 1개 = 줄 1 · 더보기·정렬 글·종료 링크 없음');
setD(LIVE.slice(0, 3), []); h = F.lpCardHTML();
chk(moreBtn(h) === '1개 더 · USDE / USDC · 합 $490', "3개 = 2줄 + '1개 더 · 이름 · 합'(외 없음)", moreBtn(h));
// 가리기 · 랜덤값 — 실제 금액 글자 0
reset(); setD(LIVE, CLOSED); S.lpClosed = true; S.uiPg['lp:dash'] = 0; S.lpOpen = new Set(['lp:a', 'lp:x1']);
const both = () => { S.uiPg['lp:dash'] = 0; const a = F.lpCardHTML(); delete S.uiPg['lp:dash']; const b = F.lpCardHTML(); S.uiPg['lp:dash'] = 0; return a + b; };   // 펼친 목록 + 접힌 더보기 단추(합)
const plain = both();
const REAL = ['17,500', '12,480', '12,170', '142', '4,920', '5,010', '61.40', '2,730', '48.20', '1,240', '22.90', '39,850', '305', '9,870', '7.50', '3,000', '35.25', '22.75'];
chk(REAL.every(t => plain.indexOf(t) >= 0), '대조: 보통 모드엔 합성 금액 글자가 다 보임', REAL.filter(t => plain.indexOf(t) < 0));
const strip = x => x.replace(/[^]*/g, '').replace(/[^]*/g, '');
for (const [mode, mob] of [['hide', false], ['rand', false], ['hide', true], ['rand', true]]) {
  S.hide = mode === 'hide'; S.rand = mode === 'rand'; S.mobile = mob;
  const x = both(), leak = REAL.filter(t => x.indexOf(t) >= 0), out = strip(x).match(/[$₩]\s?[\d.,]+/g) || [];
  chk(!leak.length && !out.length, '금액 ' + (mode === 'hide' ? '가리기' : '랜덤값') + (mob ? ' · 폰' : ' · 넓은 화면') + ' = 실제 금액 글자 0 · 표식 밖 금액 0', { leak, out });
}
S.hide = false; S.rand = true; S.mobile = false;
chk(F.lpCardHTML().indexOf('43,750') >= 0, '랜덤값 = 배수 곱한 값(17,500 × 2.5 = 43,750)으로');
// 폰
reset(); S.mobile = true; setD(LIVE, CLOSED); h = F.lpCardHTML();
chk(/card lpk lpmob/.test(h) && keysOf(h).join() === 'lp:c,lp:a' && /class="lpm" role="button"/.test(h), '폰 = 목록 줄 2개(가치 큰 순)', keysOf(h));
chk(moreBtn(h) === '5개 더 · 합 $9,870', "폰 더보기 = 'N개 더 · 합'", moreBtn(h));
chk(/<div class="lpsum cap">가치 <b class="num">\$39,850<\/b> · 미청구 <span class="num">\$305<\/span><\/div>/.test(h), '폰 머리 아래 = 가치 · 미청구');
chk(/class="lpst st-out">범위 이탈<\/span> · Uni v4 · Base/.test(h) && /<span class="lpmr"><b class="num">\$12,480<\/b><span><span class="num up">\+\$460<\/span> · 미청구 <span class="num">\$142<\/span><\/span><\/span>/.test(h), '폰 줄 = 상태 · 프로토콜 · 체인 / 오른쪽 가치 · 손익 · 미청구');
chk(/<div class="lpcs"><span class="cap"><span class="pvx">종료된 포지션 3개<\/span><\/span><span class="sp"><\/span><button type="button" class="link" data-a="lpClosed" aria-expanded="false">보기<\/button><\/div>/.test(h) && !/data-k="lp:x1"/.test(h), "폰 맨 아래 = '종료된 포지션 3개 · 보기'(종료 행 없음)", (h.match(/<div class="lpcs">[\s\S]*?<\/div>/) || [''])[0]);
S.lpClosed = true; h = F.lpCardHTML();
chk(keysOf(h).filter(k => /^lp:x/.test(k)).length === 3 && /aria-expanded="true">숨기기</.test(h), "폰 '보기' = 종료 행 3 + '숨기기'");
}
// ── 레버리지 · 대출: 넓은 화면 2줄 + 'N개 더' · 폰 다음 1줄 + 'N개 더' ──
const lrow = (i, o) => Object.assign({ id: 'okx:loan:loan:' + i, kind: 'loan', ex: 'okx', exKo: '거래소' + 'ABCDE'[i], product: 'loan', kindKo: '담보대출', key: String(i), measuredAt: 1, fresh: true, state: 'safe',
  gauge: { fill: 0.5, at: 0.9, atKind: 'call' }, lbl: { now: 'LTV 50.0%', mark: '콜 88.0%', end: '청산 98.0%' }, metric: { name: 'ltv', v: 0.5, unit: 'frac', risk: 'up', call: 0.88, liq: 0.98, txt: 'LTV 50.0%' },
  thr: 'api', drop: 'OKB 가 43% 내리면 마진콜', dropShort: 'OKB 43% 내리면 마진콜', dropCall: 0.43, debts: [{ ccy: 'USDT', total: 10, principal: 9, interest: 1, yr: 0.05 }], coll: [{ ccy: 'OKB', qty: 1 }], dayUsd: 0.01, sent: null }, o);
const levDoc = n => ({ v: 1, rows: Array.from({ length: n }, (_, i) => lrow(i)), counts: { danger: 0, warn: 0, unknown: 0, open: n, unconfirmed: 0 }, tabs: { all: n, fut: 0, margin: 0, loan: n }, exchanges: 5, levTs: 1, dayUsd: 0.05, missing: false, unconfirmed: [], unsupported: [] });
const setLev = n => { const Ls = F.levS(); Ls.d = levDoc(n); Ls.st = 'ok'; Ls.at = Date.now() + 1e9; Ls.okAt = Date.now() + 1e9; };
reset(); S.D = { debts: [] };
const levMore = x => { const y = x.match(/data-a="uiPgOpen" data-v="lev:dash"[^>]*>([\s\S]*?)<span class="uchev"/); return y ? y[1].replace(/<[^>]+>/g, '') : null; };
for (const [n, rows, lbl] of [[5, 2, '3개 더 · 거래소C 담보대출 · 거래소D 담보대출 외'], [3, 2, '1개 더 · 거래소C 담보대출'], [2, 2, null], [1, 1, null]]) {
  setLev(n); const x = F.levHTML(), k = (x.match(/class="lvr st-/g) || []).length;
  chk(k === rows && levMore(x) === lbl, '레버리지 넓은 화면 ' + n + '개 = 줄 ' + rows + (lbl ? " + '" + lbl + "'" : ' · 더보기 없음'), { k, more: levMore(x) });
}
setLev(5); S.uiPg['lev:dash'] = 0;
chk((F.levHTML().match(/class="lvr st-/g) || []).length === 5 && /data-a="uiPgClose" data-v="lev:dash"[^>]*><span class="upgxt">접기/.test(F.levHTML()), "레버리지 'N개 더' 누름 = 5줄 + '접기'");
reset(); S.D = { debts: [] }; S.mobile = true;
for (const [n, nx, lbl] of [[5, 1, '3개 더 · 거래소C 담보대출 · 거래소D 담보대출 외'], [3, 1, '1개 더 · 거래소C 담보대출'], [2, 1, null], [1, 0, null]]) {
  setLev(n); const x = F.levHTML(), k = (x.match(/class="lvmr"/g) || []).length, mm = x.match(/<span class="lvmm">([\s\S]*?)<\/span><\/span>/);
  chk(k === nx && (mm ? mm[1].replace(/<[^>]+>/g, '') : null) === lbl && /data-a="levOpen"/.test(x), '레버리지 폰 ' + n + '개 = 맨 위 + 다음 ' + nx + '줄' + (lbl ? " + '" + lbl + "'(카드 = 서랍 단추)" : ''), { k, mm: mm && mm[1] });
}
for (const [ok, msg, d] of R) console.log((ok ? 'PASS ' : 'FAIL ') + msg + (ok || d === undefined ? '' : '  — ' + JSON.stringify(d).slice(0, 600)));
console.log('RESULT ' + R.filter(x => x[0]).length + '/' + R.length);
'''

APP = os.path.join(T.ROOT, "web", "v2", "app.js")
CSS = os.path.join(T.ROOT, "web", "v2", "index.html")
app = open(APP, encoding="utf-8").read()
css = open(CSS, encoding="utf-8").read()

print("[1] 정적 — 자리 · 칸")
T.chk("+ levHTML() + lpCardHTML() + '<div class=\"dmid\">'" in app, "머리 = 4칸 요약 → 레버리지 · 대출 → LP 카드 → 오늘 무엇이 움직였나")
vd = app[app.index("  function vDash() {"):app.index("  function histLoad() {")]
T.chk("lpHTML(" not in vd and "function lpHTML(" not in app, "보유 열·오른쪽 열의 큰 LP 표(lpHTML) 없음 — 보유 표·선물 포지션·보관처는 그대로",
      re.findall(r"lpHTML\([^)]*\)", vd))
T.chk("futPosHTML()" in vd and "futPosHTML(true)" in vd and "holdingsHTML()" in vd and "venuesHTML()" in vd, "선물 포지션(왼쪽 · 넓은 화면 오른쪽)·보유·보관처 자리 유지")
T.chk("const LP_TOP = 2;" in app and "rows.slice(0, 2).map(row)" in app and "uiPaged('lev:dash', rows.slice(2)" in app, "앞 2개(LP · 레버리지 넓은 화면)")
T.chk(".card.lpk{" in css and ".lpr{display:grid;grid-template-columns:250px minmax(0,1fr) 150px 140px 130px" in css
      and "@media (max-width:960px){\n  .lpr{grid-template-columns:minmax(0,1fr) minmax(0,1fr)" in css and ".card.lpk.lpmob{" in css, "칸 CSS = 넓은 화면 5칸 격자 · 960px 이하 두 줄 · 폰 목록")
T.chk(".lev .lvmore .ubtn,.lpk .lvmore .ubtn{min-height:44px}" in css and ".lpm{display:flex" in css and "min-height:44px;cursor:pointer}" in css, "누르는 칸 44px(더보기 · 폰 줄)")
i9 = css.find(".card.lpk{padding:")
k9 = css.find(".lpk .link::after{", max(i9, 0))
j9 = css.find("\n}", k9) + 2 if k9 >= 0 and css.find("\n}", k9) >= 0 else -1
blk = css[i9:j9] if 0 <= i9 < j9 else ""
T.chk(bool(blk) and not re.search(r"#[0-9A-Fa-f]{3,8}\b|rgba?\(", blk), "LP 카드 색 = 토큰 변수만(어두운·밝은 공통 · 직접 색 0)", re.findall(r"#[0-9A-Fa-f]{3,8}\b|rgba?\([^)]*\)", blk)[:5])

print("[2] 화면 함수(node)")
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
