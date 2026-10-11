#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import os
import re
import shutil
import subprocess

JS = r'''import fs from 'node:fs';
const APP = fs.readFileSync(process.env.TJ_TEST_APP, 'utf8');
const cut = (a, b) => { const i = APP.indexOf(a), j = i < 0 ? -1 : APP.indexOf(b, i + 1); if (i < 0 || j < 0) throw new Error('블록을 못 찾음: ' + a.slice(0, 50)); return APP.slice(i, j); };
const line = a => { const i = APP.indexOf(a); if (i < 0) throw new Error('줄을 못 찾음: ' + a); return APP.slice(i, APP.indexOf('\n', i)); };
// 블록 경계 = 코드 줄만(공개판 빌드는 주석을 지운다)
const B = ['let RK = 2.5;', line('  const trimZeros = s =>'), cut('  const NFC = {};', '  const rate = () =>'), line('  const PV_A = '), line('  const pvW = s =>'), line('  const PVM = {'),
  line('  const pvMoney = (sg, compact) =>'), line('  const RS_A = '), line('  function KS(v) {'), line('  const rw = x =>'), cut('  function eok(w) {', '  function m(usd, o) {'), cut('  function m(usd, o) {', '  const CAL_DOT_USD = 7;'),
  line('  const KV = (usd, krw) =>'), line('  const dayV = x =>'), line('  const dayFlowV = x =>'), line('  const rate = () =>'), line('  const isZ = v =>'), line('  const cls = v =>'),
  line('  const clsV = v =>'), line('  const pctS = (v, d) =>'), line('  const attPct = p =>'), line('  function todayD() {'), line('  const futSym = s =>'), line('  const heroDayLbl = k =>'),
  line('  const pad2 = n =>'), line('  const isISO = s =>'),
  cut('  function attOf(k) {', '  const ATT_MVD_TIP ='), cut('  function attBars(a, k, dash) {', "  function rbLine() { return ''; }"),
  cut('  const MATT_K = [', '  function monthGlanceHTML(ym) {'), cut('  function dayContrib(iso) {', '  const rcptable = x =>'),
  cut('  function setHide(on) {', '  function rkApply() {'), cut('  function setRand(on) {', '  function wowSlot(k, x) {')].join('\n');
const R = [];
const chk = (ok, msg, d) => R.push([!!ok, msg, ok ? undefined : d]);
const S = { D: null, mobile: false, hide: false, rand: false, cur: 'USD', attOpen: null, sheet: null, anim: {}, deferred: false, tab: 'dash' };
const K = 2.5;
const esc = t => String(t == null ? '' : t).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const num = x => (isFinite(+x) ? +x : 0), arr = x => (Array.isArray(x) ? x : []);
const sum = (a, f) => a.reduce((s, x) => s + (f ? f(x) : x), 0);
const fmt = v => Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const rw = t => (S.rand ? '' + t + '' : t);
const KS = v => (S.rand ? v * K : v);
const attQ = v => (S.hide ? '8,888.88' : rw(fmt(KS(v))));
const px = v => (!(v > 0) ? '—' : S.hide ? '$8.8888' : '$' + rw(String(v)));
const SENT = [];
let FETCH = null;
const deps = {
  S, A: {}, esc, num, arr, sum, attQ, px, isoDay: k => (String(k).length === 10 ? String(k) : '2026-' + String(k)), ymOf: k => (String(k).length === 10 ? String(k) : '2026-' + String(k)).slice(0, 7),
  todayISO: () => '2026-10-11', apOf: () => false, DOWS: ['일', '월', '화', '수', '목', '금', '토'], EX_NAMES: { binance: '바이낸스', bybit: '바이빗', okx: 'OKX' },
  lpNm: s => s, icon: s => '<span class="ic xs">' + esc(String(s).slice(0, 1)) + '</span>', attTbl: () => '', attLine: () => '', attDetail: () => '<div class="attd"></div>',
  uiFold: (k, o) => o.head + o.body(), IC: { right: '<svg class="r"></svg>', left: '<svg class="l"></svg>', chev: '<svg class="c"></svg>', check: '<svg class="ok"></svg>', alert: '<svg class="w"></svg>', info: '<svg class="i"></svg>',
    send: '<svg class="s"></svg>', bank: '<svg class="b"></svg>', coin: '<svg class="co"></svg>', scale: '<svg class="sc"></svg>', layers: '<svg class="la"></svg>', fuel: '<svg class="f"></svg>', undo: '<svg class="u"></svg>', wallet: '<svg class="wa"></svg>', cal: '<svg class="ca"></svg>' },
  UI_SHEETS: {}, monthRealized: () => 0, fetch: (u, o) => { SENT.push(u); return FETCH ? FETCH(u) : new Promise(() => {}); }, onUnauthorized: () => {}, renderOverlay: () => {},
  uiSheetOpen: (k, v, t) => { S.sheet = { k, v, t }; }, LS: { set: () => {} }, pvRoot: () => {}, render: () => {}, oaSwapKeepForm: () => {}, pvFix: () => {}, dmSwapKeepForm: () => {},
  rvRefocus: () => {}, clearCache: () => {}, document: { body: {}, activeElement: null }, uiSheetClose: () => { S.sheet = null; }, revealAndHighlight: () => Promise.resolve(true), openFutRcpt: () => {}, vib: () => {}, $: () => null, toast: () => {},
};
const names = Object.keys(deps);
const F = new Function(...names, B + '\nreturn { attOf, attItems, attItemsK, attBars, attdParts, attdItems, attdDays, attdRowsDay, attdSheet, attdTitle, attdActs, attdCache, attdFit, setHide: typeof setHide === "function" ? setHide : null, setRand: typeof setRand === "function" ? setRand : null, attdShow: typeof attdShow === "function" ? attdShow : (it => it), attdMoney: typeof attdMoney === "function" ? attdMoney : (v => m(v, { sign: true })), monthAtt, monthBarRows, mgBar, MATT_K };')(...names.map(k => deps[k]));
const A = Object.assign(deps.A, F.attdActs());
// ── 합성 재료(둥글지 않은 값 · 실제와 무관) ──
const R1 = 1400;
const C25 = Array.from({ length: 25 }, (_, i) => ['C' + String.fromCharCode(65 + i) + 'X', Math.round(((i % 3 === 1 ? -1 : 1) * (1234.57 / (i + 1) + 3.21)) * 100) / 100]);
const coinsS = sum(C25, c => c[1]);
const mkDet = C25.slice().sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).map(c => [c[0], c[1], 2.5, 10, 2, 2 + c[1] / 10]);
const top5 = mkDet.slice(0, 5).map(c => [c[0], c[2], c[1]]), etc = [20, Math.round(sum(mkDet.slice(5), c => c[1]) * 100) / 100];
const v2 = (o) => Object.assign({ v: 2, top: top5, etc, xm: 0, ur: 0, gx: 0, lpf: 0, stk: 0, un: 0 }, o);
const kx10 = 3.21, fpx10 = 1.5, xm10 = 12.34, ur10 = -42.5, gx10 = -2.5;
const ev10 = Math.round((coinsS + fpx10 + xm10 + ur10) * 100) / 100;
const fl10 = [['외부 전송 USDC', -300, [['외부 전송 USDC', -300]]], ['원화 입금(은행에서)', 420.4, []], ['스테이킹 보상 SOL', 3.45, []], ['거래소 입금 ETH', -0.3, [['거래소 입금 ETH', 1500], ['외부 전송 ETH', -1500.3]]]];
const flow10 = Math.round(sum(fl10, f => f[1]) * 100) / 100;
const att10 = v2({ mk: Math.round((coinsS + kx10) * 100) / 100, kx: kx10, ev: ev10, xm: xm10, ur: ur10, gx: gx10, fpx: fpx10, rz: 500, lpf: 20, stk: 3.45, un: 7.5, fb: 25.75, rest: 0,
  unp: [1, -120.4], xr: 15, rbv: -4, np: 1 });
const att09 = v2({ mk: 812.33, top: [['CAX', 1.2, 600.11], ['CBX', -0.8, 212.22]], etc: [0, 0], kx: 0, ev: 812.33, rz: 0, rest: 1.11 });
const att11 = v2({ mk: -2345.67, top: [['CAX', -2.0, -2000.5], ['CBX', -1.0, -345.17]], etc: [0, 0], kx: 0, ev: -2345.67, rz: 0, rest: 0 });
const att08 = { mk: 4321.09, top: [['CAX', 3, 4000.01], ['CBX', 1, 321.08]], etc: [0, 0], kx: 2.5, tr: -12.34, fee: -1.5, lp: 3.3, xo: -4.4, rs: 7.7 };
const P07 = { date: '10-07', val: 90000, valKrw: 90000 * 1370, usdt: 1370 };
const P08 = { date: '10-08', val: 94321.09, valKrw: 94321.09 * 1375, usdt: 1375, flow: 0, att: att08 };
const P09 = { date: '10-09', val: 95134.53, valKrw: 95134.53 * 1380, usdt: 1380, flow: 0, att: att09 };
const P10 = { date: '10-10', val: 95134.53 + 1234.57, valKrw: (95134.53 + 1234.57) * 1395, usdt: 1395, flow: flow10, flowTop: [['원화 입금(은행에서)', 420.4], ['외부 전송 USDC', -300]], att: att10 };
const P11 = { date: '10-11', val: 94000, flow: 0, att: att11 };
P08._prev = P07; P09._prev = P08; P10._prev = P09; P11._prev = P10;
const pos = (sym, rbd, kind) => ({ sym, kind, realizedByDay: rbd, realizedKrwByDay: Object.fromEntries(Object.entries(rbd).map(([k, v]) => [k, Math.round(v * 1391)])) });
const D = { rate: R1, todayKey: '10-11', hasKrw: true, builtAt: 111, total: 93888.88, _today: 1, _pv: P10, _todayFlow: 0, _todayFlowTop: [], symLogo: {},
  dayMap: new Map([['10-08', P08], ['10-09', P09], ['10-10', P10], ['10-11', P11]]),
  f: { realizedByDate: { '2026-10-10': 523.45 }, realizedKrwByDate: { '2026-10-10': 728000 } },
  fut: { realizedByDate: { '2026-10-10': 30.75 }, realizedKrwByDate: { '2026-10-10': 43000 },
    realizedByDateEx: { '2026-10-10': [{ ex: '바이낸스', exKey: 'binance', usd: 25.75, krw: 36000, n: 3 }, { ex: '바이빗', exKey: 'bybit', usd: 5, krw: 7000, n: 1 }] } },
  merged: [pos('AAA', { '2026-10-10': 410.0 }), pos('가스 비용', { '2026-10-10': -6.55 }, 'gas'), pos('SOL', { '2026-10-10': 3.45 }, 'stake'), pos('BBB', { '2026-10-10': 96.547 })],
  lpCycles: [{ _lp: { key: 'lp:1' }, key: 'lp:1', sym: 'WETH / USDC', chain: 'Base', realizedByDay: { '2026-10-10': 20 } }] };
const DET = {
  '2026-10-10': { mk: mkDet, mkN: 25, xm: [['ABC', 12.34]], kx: [2.0, 1.21, 0], unp: [['DDD', -120.4, 'cut']], un: [['ZZZ', 7.5]], op: [], fb: [['binance', 25.75]], fl: fl10,
    fut: [['binance', '바이낸스', 'ETHUSDT', 20.25, 28300, 2, -1.1], ['binance', '바이낸스', 'BTCUSDT', 5.5, 7700, 1, 0], ['bybit', '바이빗', 'SOLUSDT', 5, 7000, 1, 0]] },
  '2026-10-09': { mk: [['CAX', 600.11, 1.2, 50, 12, 24.0022], ['CBX', 212.22, -0.8, 7, 30, 60.3171]], mkN: 2, xm: [], kx: [0, 0, 0], unp: [], un: [], op: [], fb: [], fl: [] },
  '2026-10-11': { mk: [['CAX', -2000.5, -2.0], ['CBX', -345.17, -1.0]], mkN: 2, xm: [], kx: [0, 0, 0], unp: [], un: [], op: [], fb: [], fl: [] },
  '2026-10-08': { mk: [['CAX', 4000.01, 3], ['CBX', 321.08, 1]], mkN: 2, xm: [], kx: [0, 0, 0], unp: [], un: [], op: [], fb: [], fl: [] } };
S.D = D;
const KEYS = ['mk', 'rz', 'rzf', 'fl', 'fx', 'fo', 'un', 'op', 'tr', 'oth'];
const near = (x, y, t = 1e-6) => Math.abs(x - y) <= t * Math.max(1, Math.abs(y));
const DAYS = ['10-08', '10-09', '10-10', '10-11'];
for (const cur of ['USD', 'KRW']) {
  S.cur = cur;
  for (const withDet of [true, false]) {
    const bad = [];
    for (const k of DAYS) {
      const a = F.attOf(k), P = F.attdParts(k, withDet ? DET['2026-' + k] : null);
      if (!a || !P) { bad.push([k, '없음']); continue; }
      for (const c of KEYS) { const s = sum(P[c] || [], x => x.v), want = num(a[c]); if (!near(s, want)) bad.push([k, c, s, want]); }
      for (const r of F.attdRowsDay(a)) { const it = F.attdItems({ mode: 'd', at: k, key: r.key }, r, { dets: { ['2026-' + k]: withDet ? DET['2026-' + k] : undefined }, a }); if (!near(sum(it, x => x.v), num(r.v))) bad.push([k, 'row', r.key, sum(it, x => x.v), r.v]); }
    }
    chk(!bad.length, cur + (withDet ? ' 서버 상세 있음' : ' 서버 상세 없음(상태 재료만)') + ': 4일 × 구성 10칸 · 그날 줄 — 항목 합 = 분해 값', bad.slice(0, 6));
  }
  // 그 달 — 'M월 한눈에' 줄과 같은 접기 · 날짜별
  const o = F.monthAtt('2026-10'), rows = F.monthBarRows(o), ctx = { dets: Object.fromEntries(DAYS.map(k => ['2026-' + k, DET['2026-' + k]])), keys: DAYS.slice(), o };
  const badM = [];
  for (const r of rows) {
    const row = { key: r[2], l: r[0], v: num(r[1]), fold: r[3] || [] };
    const it = F.attdItems({ mode: 'm', at: '2026-10', key: row.key }, row, ctx), dd = F.attdDays({ mode: 'm', at: '2026-10', key: row.key }, row, ctx);
    if (!near(sum(it, x => x.v), row.v)) badM.push(['item', row.key, sum(it, x => x.v), row.v]);
    if (!near(sum(dd, x => x.v), row.v, 1e-9)) badM.push(['day', row.key, sum(dd, x => x.v), row.v]);
  }
  chk(o.n === 4 && rows.every(r => r[2]) && !badM.length, cur + " 그 달: 'M월 한눈에' 줄마다 항목 합·날짜별 합 = 줄 값(나머지 = 접힌 줄 포함)", { n: o.n, badM, rows: rows.map(r => [r[0], r[2]]) });
}
S.cur = 'USD';
// 시트 그리기 — 상세 받은 상태
const C = F.attdCache(); Object.assign(C.days, DET); C.st['2026-10-10|2026-10-10'] = 'ok'; C.st['2026-10-08|2026-10-11'] = 'ok'; C.st['2026-10-11|2026-10-11'] = 'ok';
const rowsOf = h => (h.match(/class="adr"/g) || []).length;
const txt = h => h.replace(/<[^>]+>/g, '').replace(/[-]/g, '');
A.attdOpen({ dataset: { v: 'd|10-10|mk' } });
chk(S.sheet && S.sheet.k === 'attd' && S.sheet.t === '시세 · 10월 10일', "줄 누름 → 시트 'attd' · 제목 '시세 · 10월 10일'", S.sheet);
let h = F.attdSheet('d|10-10|mk');
const N0 = 25 + 1 + 3 + 1;   // 코인 25 + 원장 밖 1 + 사고판 분·묶음 차·기준가 교정 3 + (반올림 끝전은 표시 0 이면 숨김)
const nV = +((txt(h).match(/(\d+)개를 모두 더하면/) || [])[1] || 0);
chk(rowsOf(h) === 20 && /1–20 \/ \d+/.test(txt(h)) && /data-a="attdPg" data-v="1"/.test(h) && /data-v="-1" disabled/.test(h) && nV >= N0 - 1, '시세 25코인 + 몫: 첫 쪽 20개 · 1–20 / N · 이전 막힘 · 다음', { rows: rowsOf(h), nV, t: txt(h).slice(0, 200) });
chk(/같아요/.test(h) && !/adck bad/.test(h), "합 확인 = '위 시세 줄과 같아요'", txt(h).match(/[^.]*모두 더하면[^<]*/));
const amts = [...h.matchAll(/<b class="num [a-z]*">([^<]+)<\/b>/g)].map(x => x[1]);
chk(/CAX/.test(h.split('class="adr"')[1] || '') && /\+2\.5%|2\.5%/.test(txt(h)) && /\$2 → \$/.test(txt(h)), '첫 줄 = 기여 가장 큰 코인 · 변동률 · 수량 · 전일가 → 그날가', txt(h).slice(0, 400));
A.attdPg({ dataset: { v: '1' } });
h = F.attdSheet('d|10-10|mk');
chk(rowsOf(h) === nV - 20 && /21–\d+ \/ \d+/.test(txt(h)) && /data-v="1" disabled/.test(h), '다음 쪽 = 나머지(21–N) · 다음 막힘', { rows: rowsOf(h), nV });
A.attdGo({ dataset: { v: 'd|10-10|rz' } });
h = F.attdSheet(S.sheet.v);
chk(S.sheet.t === '현물 실현 · 10월 10일' && /data-a="attdRc" data-v="2026-10-10\|AAA"/.test(h) && /data-a="attdLp"/.test(h) && /가스 비용/.test(h) && rowsOf(h) >= 5 && /같아요/.test(h) && !/1–20/.test(txt(h)),
  '줄 바꾸기(현물 실현) = 첫 쪽부터 · 코인 = 차익 영수증 · LP = LP · 가스·스테이킹 줄 · 합 = 현물 실현', txt(h).slice(0, 300));
h = F.attdSheet('d|10-10|rzf');
chk(/선물 영수증/.test(h) && /data-a="attdFr" data-v="2026-10-10\|binance"/.test(h) && /ETH 무기한/.test(h) && /정산 2건/.test(txt(h)), '선물 실현 = 거래소·종목별 · 선물 영수증', txt(h).slice(0, 300));
h = F.attdSheet('d|10-10|fo');
chk(/바이빗/.test(h) && !/>바이낸스</.test(h) && /같아요/.test(h), '선물 미반영 = 대사가 안 넣은 거래소(바이빗)만 · 다 든 거래소(바이낸스) 0 줄 없음', txt(h).slice(0, 300));
h = F.attdSheet('d|10-10|fl');
chk(/외부 전송 USDC/.test(h) && /거래소 입금 ETH/.test(h) && /외부 전송 ETH/.test(h) && /스테이킹 보상 → 현물 실현으로/.test(h) && /같아요/.test(h), '입출금 = 이동 건 · 상계된 레그(아래 줄) · 스테이킹 보상 옮김 줄', txt(h).slice(0, 400));
S.cur = 'KRW';
h = F.attdSheet('d|10-10|fx');
chk(/달러 자산 원화 환산/.test(h) && /원화 예수금 환산/.test(h) && /업비트 원화 입출금 환율 차/.test(h) && /현물 실현 환산 차/.test(h) && /USDT/.test(h) && /같아요/.test(h), '원화 환율 = 달러 자산 · 예수금 · 입출금 환율 차 · 실현 환산 차', txt(h).slice(0, 400));
S.cur = 'USD';
const a10 = F.attOf('10-10'), rows10 = F.attdRowsDay(a10), oth = rows10.find(r => r.key === 'oth');
h = F.attdSheet('d|10-10|oth');
chk(oth && /DDD — 가격 끊김/.test(h) && /원장 밖 잔고/.test(h) && /Rabby 기준 보유 변화/.test(h) && (oth.fold.length ? /작아서 여기 합친 줄/.test(h) : true) && /같아요/.test(h), "나머지 = 이름 붙은 몫(가격 끊김 DDD · 원장 밖 잔고 · Rabby) + 작아서 합친 줄 + 근사", { fold: oth && oth.fold, t: txt(h).slice(0, 400) });
// 오늘 — 실시간 차
h = F.attdSheet('d|10-11|oth');
const r11 = F.attdRowsDay(F.attOf('10-11'));
chk(!r11.some(r => r.key === 'oth') || /실시간 값과 마지막 분해 시각 차/.test(h), "오늘 나머지 = '실시간 값과 마지막 분해 시각 차'", txt(h).slice(0, 300));
// 그 달 시트 · 날짜별
A.attdOpen({ dataset: { v: 'm|2026-10|mk' } });
h = F.attdSheet(S.sheet.v);
chk(S.sheet.t === '시세 변동 · 10월' && /항목별/.test(h) && /날짜별/.test(h) && /같아요/.test(h) && /일<\/span>/.test(h), "그 달 시트 = '시세 변동 · 10월' · 항목별/날짜별 · 날 수 · 합 = 줄", txt(h).slice(0, 300));
A.attdView({ dataset: { v: 'day' } });
h = F.attdSheet(S.sheet.v);
chk(rowsOf(h) === 4 && /data-a="attdGo" data-v="d\|10-10\|mk"/.test(h) && /같아요/.test(h), '날짜별 = 분해 있는 날 4줄 · 누르면 그날 상세', { rows: rowsOf(h), t: txt(h).slice(0, 300) });
A.attdView({ dataset: { v: 'it' } });
// 금액 숨김·랜덤값 — 실제 금액 글자 0
const real = new Set();
for (const v of ['d|10-10|mk', 'd|10-10|rz', 'd|10-10|rzf', 'd|10-10|fl', 'd|10-10|fx', 'd|10-10|fo', 'd|10-10|oth', 'm|2026-10|mk', 'm|2026-10|fl']) {
  S.attdUI = { v, pg: 0, view: 'it' };
  for (const x of txt(F.attdSheet(v)).matchAll(/\d{1,3}(?:,\d{3})+\.\d\d|\d+\.\d\d/g)) if (x[0].replace(/[,.]/g, '').length >= 4) real.add(x[0]);
}
const leak = mode => { S.hide = mode === 'hide'; S.rand = mode === 'rand'; const out = [];
  for (const v of ['d|10-10|mk', 'd|10-10|rz', 'd|10-10|rzf', 'd|10-10|fl', 'd|10-10|fx', 'd|10-10|fo', 'd|10-10|oth', 'm|2026-10|mk', 'm|2026-10|fl']) {
    S.attdUI = { v, pg: 0, view: 'it' }; const t = F.attdSheet(v).replace(/<[^>]+>/g, ' ');
    const vis = mode === 'rand' ? t.replace(/[^]*/g, ' ') : t.replace(/[^]*/g, ' ');
    real.forEach(r => { if (vis.includes(r)) out.push([v, r]); }); }
  S.hide = false; S.rand = false; return out; };
chk(real.size > 30 && !leak('hide').length, '금액 숨김: 실제 금액 글자 0(시세·실현·선물·입출금·환율·나머지·그 달)', { n: real.size, leak: leak('hide').slice(0, 5) });
chk(!leak('rand').length, '랜덤값: 실제 금액 글자 0(표식 밖)', leak('rand').slice(0, 5));
// 막대·칩·'M월 한눈에' 줄 = 누르는 단추
S.attdUI = null;
const ab = F.attBars(a10, '10-10', true), nRow = 1 + F.attItemsK(a10).length;
chk((ab.match(/<button type="button" class="abr abtn" data-a="attdOpen"/g) || []).length === nRow && /data-v="d\|10-10\|mk"/.test(ab) && /aria-haspopup="dialog"/.test(ab), '대시보드 막대 줄 = 줄마다 단추(data-a=attdOpen · d|날|키)', nRow);
S.mobile = true;
const ac = F.attBars(a10, '10-10', true);
chk((ac.match(/class="achip abtn" data-a="attdOpen"/g) || []).length === nRow, '폰 칩 = 단추', ac.slice(0, 200));
S.mobile = false;
const mg = F.mgBar('시세 변동', 5, 10, 'm|2026-10|mk');
chk(/^<button type="button" class="abr abtn" data-a="attdOpen" data-v="m\|2026-10\|mk"/.test(mg) && /<div class="abr" role="listitem">/.test(F.mgBar('x', 1, 2)), "'M월 한눈에' 줄 = 단추(값 없으면 종전 줄)", mg.slice(0, 120));
chk(JSON.stringify(F.attItems(a10)) === JSON.stringify(F.attItemsK(a10).map(x => [x.l, x.v])), 'attItems(종전 모양) = attItemsK 의 [이름, 값]', F.attItems(a10));
// 받는 중 · 실패 · 옛 서버
(async () => {
  S.attdC = null; S.attdUI = null;
  const hw = F.attdSheet('d|10-09|mk');
  chk(/adsk/.test(hw) && /목록 받는 중/.test(hw) && SENT.some(u => /\/api\/att_detail\?from=2026-10-09&to=2026-10-09/.test(u)), '받는 중 = 뼈대 · 그날 상세 요청', SENT.slice(-2));
  FETCH = () => Promise.resolve({ status: 503, ok: false, json: () => Promise.resolve({ ok: false, error: 'x' }) });
  S.attdC = null; F.attdSheet('d|10-09|mk'); await new Promise(r => setTimeout(r, 10));
  let he = F.attdSheet('d|10-09|mk');
  chk(/다시 시도/.test(he) && /큰 항목만/.test(he) && /같아요/.test(he) && rowsOf(he) >= 2, '실패 = 큰 항목(상태 재료) + 다시 시도 · 합은 그대로', txt(he).slice(0, 300));
  FETCH = () => Promise.resolve({ status: 404, ok: false, json: () => Promise.resolve({}) });
  S.attdC = null; F.attdSheet('d|10-09|mk'); await new Promise(r => setTimeout(r, 10));
  he = F.attdSheet('d|10-09|mk');
  chk(/서버를 업데이트하면/.test(he) && !/다시 시도/.test(he), '옛 서버(404) = 안내(다시 시도 없음)', txt(he).slice(0, 200));
  FETCH = () => Promise.resolve({ status: 200, ok: true, json: () => Promise.resolve({ ok: true, days: { '2026-10-09': DET['2026-10-09'] } }) });
  S.attdC = null; F.attdSheet('d|10-09|mk'); await new Promise(r => setTimeout(r, 10));
  he = F.attdSheet('d|10-09|mk');
  chk(!/큰 항목만/.test(he) && /50/.test(txt(he)) && /같아요/.test(he), '받으면 = 서버 상세(수량·가격) · 안내 없음', txt(he).slice(0, 200));
  // 그 달 = lite 요청 · lite 응답은 이미 받은 그날 전체(수량·가격)를 덮지 않음
  S.attdC = null; FETCH = u => Promise.resolve({ status: 200, ok: true, json: () => Promise.resolve({ ok: true, days: /lite=1/.test(u)
    ? { '2026-10-09': { mk: [['CAX', 600.11, 1.2], ['CBX', 212.22, -0.8]], mkN: 2, fl: [] }, '2026-10-10': { mk: [['ZZZ', 1, 1]], mkN: 1 } } : { '2026-10-09': DET['2026-10-09'] } }) });
  F.attdSheet('d|10-09|mk'); await new Promise(r => setTimeout(r, 10));
  F.attdSheet('m|2026-10|mk'); await new Promise(r => setTimeout(r, 10));
  const C2 = F.attdCache();
  chk(SENT.some(u => /from=2026-10-08&to=2026-10-11&lite=1/.test(u)) && C2.days['2026-10-09'].mk[0].length === 6 && !C2.days['2026-10-09']._lite && C2.days['2026-10-10']._lite,
    "그 달 = lite 요청 · 그날 전체 상세는 lite 로 안 덮임(없던 날만 lite 로)", { sent: SENT.slice(-2), d9: C2.days['2026-10-09'] && C2.days['2026-10-09'].mk[0] });
  // 다른 빌드의 상세(builtAt 다름) = 쓰지 않음 · 큰 항목 + 안내
  S.attdC = null; FETCH = () => Promise.resolve({ status: 200, ok: true, json: () => Promise.resolve({ ok: true, builtAt: 999, days: { '2026-10-09': DET['2026-10-09'] } }) });
  F.attdSheet('d|10-09|mk'); await new Promise(r => setTimeout(r, 10));
  he = F.attdSheet('d|10-09|mk');
  chk(!F.attdCache().days['2026-10-09'] && /방금 새로 계산됐어요/.test(he) && /같아요/.test(he), '다른 빌드(builtAt 다름)의 상세는 안 씀 — 큰 항목 + 안내(합은 그대로)', txt(he).slice(0, 200));
  // ★코덱스 ud706 ①★ 숨김·랜덤값 = 상세 요청 없음 · 받아 둔 원문 버림 · 받는 중 가림 켜면 응답 버림 · 화면 = 상태 재료(합 그대로)
  for (const md of ['hide', 'rand']) {
    S.attdC = null; FETCH = () => Promise.resolve({ status: 200, ok: true, json: () => Promise.resolve({ ok: true, days: DET }) });
    F.attdSheet('d|10-10|mk'); await new Promise(r => setTimeout(r, 10));
    chk(F.attdCache().days['2026-10-10'], md + ': (켜기 전) 받아 둔 상세 있음');
    S.hide = md === 'hide'; S.rand = md === 'rand';
    const n0 = SENT.length;
    const hp = F.attdSheet('d|10-10|mk') + F.attdSheet('m|2026-10|fl') + F.attdSheet('d|10-09|oth');
    const hp1 = F.attdSheet('d|10-10|fl');
    chk(SENT.length === n0 && !S.attdC && /금액 가리기·랜덤값에서는 상세 원문을 받지 않아요/.test(hp) && /같아요/.test(hp1) && !/다시 시도/.test(hp1),
      md + ': 시트를 열어도 /api/att_detail 요청 0 · 받아 둔 원문 버림 · 안내 · 상태 재료로 합 그대로', { sent: SENT.slice(n0), t: txt(hp1).slice(0, 160) });
    S.hide = false; S.rand = false;
  }
  { let res; S.attdC = null; FETCH = () => new Promise(r => { res = r; });
    F.attdSheet('d|10-10|mk'); S.hide = true;
    res({ status: 200, ok: true, json: () => Promise.resolve({ ok: true, days: DET }) }); await new Promise(r => setTimeout(r, 10));
    const C9 = S.attdC; S.hide = false;
    chk(!C9 || (!C9.days['2026-10-10'] && !C9.st['2026-10-10|2026-10-10']), '받는 중 가림을 켜면 도착한 원문을 버림(다음에 일반 모드로 열면 다시 받음)', C9 && Object.keys(C9.days)); }
  // ★코덱스 ud711 ①★ 실제 setHide·setRand 경로 — 시트 닫힌 채 숨김→해제→숨김(랜덤값도): 받아 둔 원문 없음 · 요청 중 가림 켰다 끄면 늦은 응답 버림
  for (const md of ['hide', 'rand']) {
    const set = md === 'hide' ? F.setHide : F.setRand;
    S.attdC = null; S.sheet = null; FETCH = () => Promise.resolve({ status: 200, ok: true, json: () => Promise.resolve({ ok: true, days: DET }) });
    F.attdSheet('d|10-10|mk'); await new Promise(r => setTimeout(r, 10));
    const had = !!(S.attdC && S.attdC.days['2026-10-10']);
    set(true); const a1 = S.attdC; set(false); const a2 = S.attdC; set(true); const a3 = S.attdC; set(false);
    chk(had && !a1 && !a2 && !a3 && !S.hide && !S.rand, md + ': 시트 닫힌 채 켜기→끄기→켜기 — 받아 둔 상세 원문 0(실제 set' + (md === 'hide' ? 'Hide' : 'Rand') + ')', { had, a1: !!a1, a2: !!a2, a3: !!a3 });
    let res; S.attdC = null; FETCH = () => new Promise(r => { res = r; });
    F.attdSheet('d|10-10|mk'); set(true); set(false);
    res({ status: 200, ok: true, json: () => Promise.resolve({ ok: true, days: DET }) }); await new Promise(r => setTimeout(r, 10));
    const late = S.attdC ? Object.keys(S.attdC.days) : [];
    let res2; FETCH = () => new Promise(r => { res2 = r; });
    F.attdSheet('d|10-10|mk');
    chk(!late.length && res2 && !S.attdC.days['2026-10-10'], md + ': 요청 중 켰다가 응답 전 끄기 — 늦은 응답 버림 · 다시 열면 새로 요청', { late });
    if (res2) res2({ status: 200, ok: true, json: () => Promise.resolve({ ok: true, days: DET }) }); await new Promise(r => setTimeout(r, 10));
  }
  // ★코덱스 ud706 ②★ 표시 단위 반올림 — 보이는 금액(센트·원)의 합 = 합 확인 줄 = 큰 값
  S.cur = 'USD';
  { const it = F.attdShow([{ id: 'a', l: 'A', v: 100.49 }, { id: 'b', l: 'B', v: 100.49 }], 200.98);
    chk(it.length === 2 && it.map(x => F.attdMoney(x.v)).join(' ') === '+$100.49 +$100.49' && F.attdMoney(200.98) === '+$200.98', '달러 = 늘 센트까지(종전 m() 은 $100 넘으면 소수 버려 +$100 +$100 ≠ +$201)', it.map(x => F.attdMoney(x.v))); }
  S.cur = 'KRW'; const r0 = D.rate; D.rate = 1380;
  { const it = F.attdShow([{ id: 'a', l: 'A', v: 0.02 }, { id: 'b', l: 'B', v: 0.02 }], 0.04);
    const shown = it.map(x => F.attdMoney(x.v));
    chk(shown.join(' ') === '+₩28 +₩28 −₩1' && F.attdMoney(0.04) === '+₩55' && it[2].l === '반올림 끝전', '원화 ₩28 + ₩28 vs 합 ₩55 → 반올림 끝전 −₩1 줄(보이는 합 = ₩55)', shown); }
  D.rate = r0;
  const units = t => { const x = t.match(/([+−]?)[$₩]([\d,]+(?:\.\d+)?)/); if (!x) return null; const n = Math.round(+x[2].replace(/,/g, '') * (t.includes('$') ? 100 : 1)); return x[1] === '−' ? -n : n; };
  const badU = [];
  S.attdC = null; FETCH = () => Promise.resolve({ status: 200, ok: true, json: () => Promise.resolve({ ok: true, days: DET }) });
  for (const cur of ['USD', 'KRW']) {
    S.cur = cur;
    for (const v of ['d|10-10|mk', 'd|10-10|rz', 'd|10-10|rzf', 'd|10-10|fl', 'd|10-10|fx', 'd|10-10|fo', 'd|10-10|oth', 'd|10-11|mk', 'm|2026-10|mk', 'm|2026-10|oth', 'm|2026-10|fl']) {
      S.attdUI = { v, pg: 0, view: 'it' }; F.attdSheet(v); await new Promise(r => setTimeout(r, 5));
      let tot = 0, head = null, ckv = null;
      for (let pg = 0; pg < 5; pg++) {
        S.attdUI.pg = pg; const h9 = F.attdSheet(v);
        if (pg && !new RegExp((pg * 20 + 1) + '–').test(txt(h9))) break;
        const rows9 = h9.split('class="adr"').slice(1).map(x => (x.match(/<b class="num [a-z]*">([^<]+)<\/b>/) || [])[1]).filter(Boolean);
        rows9.forEach(x => { tot += units(x); });
        head = units((h9.match(/<div class="adsum"><b class="num [a-z]*">([^<]+)<\/b>/) || [])[1] || '');
        ckv = units((h9.match(/모두 더하면 <b class="num [a-z]*">([^<]+)<\/b>/) || [])[1] || '');
        if (!/data-v="1"[^>]*>다음/.test(h9) || /data-v="1" disabled/.test(h9)) break;
      }
      if (tot !== head || ckv !== head) badU.push([cur, v, tot, head, ckv]);
    }
  }
  chk(!badU.length, '달러·원화 × 시트 11개: 보이는 금액(센트·원 정수) 합 = 합 확인 줄 = 큰 값(쪽 넘김 전부)', badU.slice(0, 5));
  S.cur = 'USD';
  // ★코덱스 ud706 ④★ 서버 상한(more) → '그 밖 N개' 한 줄 · 합 보존
  const DM = JSON.parse(JSON.stringify(DET['2026-10-10']));
  DM.mk = DM.mk.slice(0, 20); DM.more = { mk: [5, Math.round(sum(DET['2026-10-10'].mk.slice(20), c => c[1]) * 100) / 100], fut: [1, 5], fl: [7, -0.3] };
  DM.fut = DM.fut.slice(0, 2); DM.fl = DM.fl.slice(0, 3);
  const Pm = F.attdParts('10-10', DM), a9 = F.attOf('10-10');
  chk(Pm.mk.some(x => x.l === '그 밖 5종') && Pm.rzf.some(x => x.l === '그 밖 1종목') && Pm.fl.some(x => x.l === '그 밖 7건')
    && ['mk', 'rzf', 'fl'].every(c => near(sum(Pm[c], x => x.v), num(a9[c]))) && !Pm.mk.some(x => x.rest === 1),
    "서버가 상한으로 자른 몫 = '그 밖 N종·N종목·N건' 한 줄 · 합 = 줄 값(남는 차는 반올림 크기)", Pm.mk.slice(-3).map(x => [x.l, x.v]));
  // ★코덱스 ud711 ③★ 선물 생략분 = 정산 시각 원화 합(more.fut[2]) — 원화 화면에 그날 환율 환산 차가 '반올림 끝전'으로 새지 않게
  S.cur = 'KRW';
  { const DK = JSON.parse(JSON.stringify(DET['2026-10-10'])); DK.fut = DK.fut.slice(0, 2); DK.more = { fut: [1, 5, 7000] };
    const Pk = F.attdParts('10-10', DK), mf = Pk.rzf.find(x => x.l === '그 밖 1종목'), rr = Pk.rzf.find(x => x.rest);
    chk(mf && Math.abs(mf.v * D.rate - 7000) < 1e-6 && (!rr || Math.abs(rr.v * D.rate) < 0.5), "원화: 선물 '그 밖 1종목' = 정산 시각 원화 ₩7,000(그날 환율 환산 아님) · 반올림 끝전 없음", { mf: mf && mf.v * D.rate, rr: rr && rr.v * D.rate }); }
  // ★ui17(문서1 9절 기여도)★ 원화만 남는 선물(USD 상쇄 0 · ₩10만) — 서버가 실은 행 = 그 원화 · 생략 몫이 USD 0 이어도 원화면 '그 밖' 한 줄 · 큰 차를 '반올림 끝전'이라 부르지 않음
  { const k0 = D.fut.realizedKrwByDate['2026-10-10'];
    D.fut.realizedKrwByDate['2026-10-10'] = k0 + 100000;   // 그날 선물 원화 합 = 상쇄된 XRP 몫 ₩10만 포함(USD 합 그대로)
    const DZ = JSON.parse(JSON.stringify(DET['2026-10-10'])); DZ.fut = [...DZ.fut, ['binance', '바이낸스', 'XRPUSDT', 0, 100000, 2, 0]];
    const Pz = F.attdParts('10-10', DZ), xr = Pz.rzf.find(x => x.id === 'f:binance:XRPUSDT'), rz0 = Pz.rzf.find(x => x.rest);
    chk(xr && Math.abs(xr.v * D.rate - 100000) < 1e-6 && (!rz0 || Math.abs(rz0.v * D.rate) < 0.5) && near(sum(Pz.rzf, x => x.v), num(F.attOf('10-10').rzf)),
      '원화: USD 0 · ₩100,000 선물 행 = 그 줄 ₩100,000 · 남는 차 없음 · 합 = 선물 실현', Pz.rzf.map(x => [x.l, Math.round(x.v * D.rate)]));
    const DM2 = JSON.parse(JSON.stringify(DET['2026-10-10'])); DM2.more = { fut: [1, 0, 100000] };
    const Pm2 = F.attdParts('10-10', DM2), mf2 = Pm2.rzf.find(x => x.l === '그 밖 1종목'), rm2 = Pm2.rzf.find(x => x.rest);
    chk(mf2 && Math.abs(mf2.v * D.rate - 100000) < 1e-6 && (!rm2 || Math.abs(rm2.v * D.rate) < 0.5),
      "원화: 생략 몫 more.fut = [1, $0, ₩100,000] → '그 밖 1종목' ₩100,000(종전 USD 0 이라 빠지고 '반올림 끝전' ₩100,000)", Pm2.rzf.map(x => [x.l, Math.round(x.v * D.rate)]));
    const Po = F.attdParts('10-10', DET['2026-10-10']), ro = Po.rzf.find(x => x.rest);   // 옛 서버(그 행을 안 실음) — 남는 ₩10만
    chk(ro && Math.abs(ro.v * D.rate - 100000) < 1 && ro.l !== '반올림 끝전' && ro.rest === 1,
      "옛 서버(행 없음): 남는 ₩100,000 = '그 밖 정산'(센트보다 큰 차를 '반올림 끝전'이라 부르지 않음)", ro && [ro.l, Math.round(ro.v * D.rate)]);
    D.fut.realizedKrwByDate['2026-10-10'] = k0; }
  S.cur = 'USD';
  D.builtAt = 222;
  chk(F.attdCache().at === 222 && !Object.keys(F.attdCache().days).length, '새 빌드(builtAt 바뀜) = 받은 상세 비움(다시 받음)', F.attdCache());
  for (const [ok, msg, d] of R) console.log((ok ? 'PASS ' : 'FAIL ') + msg + (ok || d === undefined ? '' : '  — ' + JSON.stringify(d).slice(0, 700)));
  console.log('RESULT ' + R.filter(x => x[0]).length + '/' + R.length);
})();
'''

APP = os.path.join(T.ROOT, "web", "v2", "app.js")
CSS = os.path.join(T.ROOT, "web", "v2", "index.html")
app = open(APP, encoding="utf-8").read()
css = open(CSS, encoding="utf-8").read()

print("[1] 정적 — 단추 · 시트 · 칸")
T.chk("UI_SHEETS.attd = v => attdSheet(v);" in app and "Object.assign(A, attdActs());" in app, "시트 등록(UI_SHEETS.attd) · 액션 연결(attdActs)")
T.chk("mgBar(x[0], num(x[1]), mx, 'm|' + ym + '|' + x[2])" in app, "'M월 한눈에' 막대 = 그 달 상세 단추")
T.chk("fetch('/api/att_detail?from=' + lo + '&to=' + hi" in app, "상세 = GET /api/att_detail(기간)")
T.chk("@media (min-width:641px){ .usheet:has(.attdp){width:min(560px,calc(100vw - 32px))} }" in css, "넓은 화면 = 가운데 창 560px(폰은 종전 아래 시트)")
i9 = css.find(".abars.abtns,")
j9 = css.find("  .attdp .adtabs{margin-right:-16px;padding-right:16px}\n}", max(i9, 0))
blk = css[i9:j9] if 0 <= i9 < j9 else ""
T.chk(bool(blk) and not re.search(r"#[0-9A-Fa-f]{3,8}\b|rgba?\(", blk), "분해 상세 CSS 색 = 토큰 변수만(어두운·밝은 공통)", re.findall(r"#[0-9A-Fa-f]{3,8}\b|rgba?\([^)]*\)", blk)[:5])
T.chk("@media (max-width:640px){\n  .attdp .adr{grid-template-columns:22px minmax(0,1fr) auto 12px" in css, "폰 = 막대 칸 없이 이름·금액(줄 높이 52px)")

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
    T.chk(p.returncode == 0 and got and any(ln.startswith("RESULT ") for ln in lines), "node 화면 함수 시험이 끝까지 돌았음", (p.stderr or "")[-900:])
T.finish()
