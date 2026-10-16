'use strict';
(function () {
  const POLL_MS = 30000;
  function tjTab(n, X) {
    const f = window.__tjTabs && window.__tjTabs[n];
    if (typeof f !== 'function') throw new Error('[tj] 화면 파일 없음: tab_' + n + '.js');
    return f(X);
  }
  const LS = {
    get(k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { window.localStorage.setItem(k, v); } catch (e) {  } },
    del(k) { try { window.localStorage.removeItem(k); } catch (e) {  } }
  };
  const SS = {
    get(k) { try { return window.sessionStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { window.sessionStorage.setItem(k, v); } catch (e) {  } }
  };
  const J_SORTS = [['recent', '최근 활동'], ['value', '평가금액'], ['cost', '원가'], ['realized', '실현'], ['unreal', '평가손익']];
  const J_FIRST = 15, J_STEP = 40;
  const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const isAirQ = h => /^실매수 이력 없는 에어드랍 유입/.test(String(h || '')) && !/확증|허니팟|매도 불가|가짜 토큰/.test(String(h || ''));
  const impChip = x => (x && x.imp) ? ' <span class="pill e sm" title="' + esc(x.imp) + ' 흉내 — 사칭 토큰">사칭</span>' : '';
  const num = v => { const n = Number(v); return isFinite(n) ? n : 0; };
  const arr = v => (Array.isArray(v) ? v : []);
  const sum = (a, f) => a.reduce((s, x) => s + (f ? f(x) : x), 0);
  const pad2 = n => (n < 10 ? '0' : '') + n;
  const $ = (s, r) => (r || document).querySelector(s);
  const trimZeros = s => (s.indexOf('.') >= 0 ? s.replace(/0+$/, '').replace(/\.$/, '') : s);
  const short = a => { const s = String(a || ''); return s.length > 14 ? s.slice(0, 6) + '…' + s.slice(-4) : s; };
  const shortL = a => { const s = String(a || ''); return s.length > 24 ? s.slice(0, 12) + '…' + s.slice(-10) : s; };

  const EX_ORDER = ['upbit', 'binance', 'bybit', 'okx', 'kucoin', 'gate', 'bithumb', 'hyperliquid'];
  const EX_NAMES = { upbit: '업비트', binance: '바이낸스', bybit: '바이빗', okx: 'OKX', kucoin: '쿠코인', gate: '게이트', bithumb: '빗썸' };
  const DEX_NAMES = { hyperliquid: 'Hyperliquid', dydx: 'dYdX', lighter: 'Lighter', gmx: 'GMX', jupiter: 'Jupiter', pacifica: 'Pacifica' };
  Object.assign(EX_NAMES, DEX_NAMES);
  const isDex = k => Object.prototype.hasOwnProperty.call(DEX_NAMES, k);
  const EX_BRAND = { upbit: ['#0A3A8C', 'U'], binance: ['#F0B90B', 'B', '#1E2026'], bybit: ['#17181E', 'By'], okx: ['#0B0B0B', 'OK'],
    kucoin: ['#1BA27A', 'K', '#1E2026'], gate: ['#2354E6', 'G'], bithumb: ['#F37321', 'B', '#1E2026'],
    hyperliquid: ['#97FCE4', 'HL', '#0B2520'], dydx: ['#5B57F0', 'dY'], lighter: ['#E9E9EF', 'Li', '#16161C'], gmx: ['#2D42FC', 'GX'],
    jupiter: ['#C7F284', 'J', '#1B2A12'], pacifica: ['#5AC8FA', 'P', '#0B2330'] };
  const EX_BY_KO = {}; Object.keys(EX_NAMES).forEach(k => { EX_BY_KO[EX_NAMES[k]] = k; });
  const PERIODS = [
    { k: 'thismonth', label: '이번 달' }, { k: 'lastmonth', label: '지난 달' }, { k: '90d', label: '최근 3개월' },
    { k: 'all', label: '전체 기간' }, { k: 'custom', label: '직접 지정' }];
  const DUST_OPTS = [0, 10, 50, 200, 1000];
  const DOWS = ['일', '월', '화', '수', '목', '금', '토'];
  const CH_RANGES = [[7, '1주'], [30, '1개월'], [90, '3개월'], [180, '6개월'], [365, '1년'], [9999, '전체']];
  const TABS = [
    { k: 'dash', label: '대시보드', short: '대시보드', ko: '대시보드' },
    { k: 'journal', label: '매매일지', short: '매매일지', ko: '매매일지' },
    { k: 'daily', label: '일별 기록', short: '일별', ko: '일별 기록' },
    { k: 'outflows', label: '보낸 내역', short: '보낸 내역', ko: '보낸 내역' },
    { k: 'unmatched', label: '미매칭', short: '미매칭', ko: '미매칭' },
    { k: 'other', label: '기타 자산', short: '기타 자산', ko: '기타 자산' },
    { k: 'settings', label: '설정', short: '설정', ko: '설정' }];

  const sv = (d, x) => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="' + (x || 2) + '" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + d + '</svg>';
  const IC = {
    chev: sv('<path d="M6 9l6 6 6-6"/>'),
    left: sv('<path d="M15 6l-6 6 6 6"/>'),
    right: sv('<path d="M9 6l6 6-6 6"/>'),
    down: sv('<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>'),
    search: sv('<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>'),
    sun: sv('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'),
    moon: sv('<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>'),
    close: sv('<path d="M6 6l12 12M18 6L6 18"/>'),
    cal: sv('<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/>'),
    copy: sv('<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h8"/>'),
    check: sv('<path d="M5 12l5 5 9-10"/>', 2.4),
    gear: sv('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>', 1.8),
    wallet: sv('<path d="M4 7a2 2 0 0 1 2-2h11v4"/><rect x="3" y="7" width="18" height="13" rx="2"/><path d="M16 13.5h.01"/>'),
    alert: sv('<path d="M12 3l9.5 16.5h-19z"/><path d="M12 10v4M12 17h.01"/>'),
    info: sv('<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>'),
    send: sv('<path d="M7 17L17 7M9 7h8v8"/>'),
    shield: sv('<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>'),
    bank: sv('<path d="M3 10l9-6 9 6M5 10v8M9 10v8M15 10v8M19 10v8M3 20h18"/>'),
    undo: sv('<path d="M9 14L4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>'),
    ext: sv('<path d="M14 4h6v6M20 4l-9 9M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/>'),
    coin: sv('<circle cx="12" cy="12" r="8"/><path d="M12 8v8M9.5 10h4a1.5 1.5 0 0 1 0 3h-3a1.5 1.5 0 0 0 0 3h4"/>'),
    scale: sv('<path d="M12 4v16M7 20h10M5 8h14M5 8l-2.5 6a3 3 0 0 0 5 0zM19 8l-2.5 6a3 3 0 0 0 5 0z"/>'),
    layers: sv('<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>'),
    fuel: sv('<path d="M4 20V6a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2v14M3 20h13M7 9h5"/><path d="M15 9h2a2 2 0 0 1 2 2v5a1.5 1.5 0 0 0 3 0V8l-3-3"/>'),
    eye: sv('<path d="M2 12c1-2.5 5-7 10-7s9 4.5 10 7c-1 2.5-5 7-10 7S3 14.5 2 12z"/><circle cx="12" cy="12" r="3"/>'),
    dice: sv('<rect x="4" y="4" width="16" height="16" rx="3.5"/>' + [[8.6, 8.6], [15.4, 8.6], [12, 12], [8.6, 15.4], [15.4, 15.4]].map(c => '<circle cx="' + c[0] + '" cy="' + c[1] + '" r="1.35" fill="currentColor" stroke="none"/>').join('')),
    eyeoff: sv('<path d="M3 3l18 18M10.6 5.1A10 10 0 0 1 12 5c5 0 9 4.5 10 7a13 13 0 0 1-3 4M6.6 6.6C4.3 8 2.7 10.2 2 12c1 2.5 5 7 10 7a9.6 9.6 0 0 0 4.2-1M9.9 9.9a3 3 0 0 0 4.2 4.2"/>'),
    tab: {
      dash: sv('<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>'),
      journal: sv('<path d="M6 3h11a2 2 0 0 1 2 2v16H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zM8 8h7M8 12h7M8 16h4"/>'),
      daily: sv('<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/>'),
      outflows: sv('<path d="M21 3L10 14"/><path d="M21 3l-7 18-4-7-7-4z"/>'),
      unmatched: sv('<circle cx="12" cy="12" r="8.5"/><path d="M12 8v5M12 16h.01"/>'),
      other: sv('<path d="M3 21h18M5 21V10l7-5 7 5v11"/><path d="M9.5 21v-5h5v5"/>'),
      settings: sv('<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/>')
    }
  };

  const mq = window.matchMedia('(max-width: 640px)');
  const mqN = window.matchMedia('(max-width: 900px)');
  const S = {
    data: null, D: null, err: null, errCode: 0, lastOk: 0, seq: 0, applied: 0, inited: false,
    ver: '', cached: false, dirty: false, savedAt: 0,
    tab: 'dash',
    cur: LS.get('tj_v2_cur') === 'USD' ? 'USD' : 'KRW',
    hide: LS.get('tj_v2_hide') === '1',
    rand: LS.get('tj_v2_rand') === '1' && LS.get('tj_v2_hide') !== '1',
    bfMin: SS.get('tj_v2_bfmin') === '1',
    dust: 50,
    hold: { mode: 'all', sort: 'value', dir: -1, limit: mq.matches ? 12 : 15, open: new Set(), showDust: false, showZero: false, dense: LS.get('tj_v2_hold_dense') === '1' },
    venueOpen: new Set(), stOpen: new Set(), lpOpen: new Set(), chartDays: 30, chartUser: false,
    hist: { ver: '', st: '', days: [], building: false, flowBuilding: false, prog: null },
    j: { view: 'cycles', status: 'all', q: '', sort: (v => J_SORTS.some(x => x[0] === v) ? v : 'recent')(LS.get('tj_v2_j_sort')), limit: J_FIRST, open: new Set(), evMore: new Set(), feedLimit: 100, lpGrp: new Set(), grpM: {} },
    g: { period: 'all', from: '', to: '' },
    src: { mode: 'all', key: '' },
    pop: null, rp: { which: 'from', ym: '' },
    taxOpen: null, taxCoinOpen: new Set(),
    day: '', calYM: '', dayEvLimit: 20,
    u: { open: null, item: new Set(), limit: {}, q: '', showHidden: false },
    of: { view: 'pending', open: new Set(), form: {}, period: 'all', coin: '', reason: '', limit: 30, fr: new Set(), fa: new Set(), fsp: new Set(),
      memoEd: null, lk: null, lkc: {}, lkOpt: {}, lkGen: {}, lkT: null },
    aliasEdit: null,
    set: { sec: '', sub: '', open: new Set(), walAll: false, walQ: '', walOpen: '', q: '', qi: 0, qr: [], qOpen: false, hl: '', focus: '', anim: '', sig: '', y: {}, prev: '', restoreY: null, from: '', fromSub: false },
    oa: { st: '', d: null, at: 0, err: '', had: false, filter: 'all', sel: null, form: null, lk: null, busy: false, delArm: null,
      sub: LS.get('tj_v2_oa_sub') === 'nft' ? 'nft' : 'assets' },
    nft: { st: '', d: null, at: 0, err: '', inc: false, more: false, spamOpen: false, spamLim: 40, hidOpen: false, busy: false },
    drafts: {},
    dm: { ed: null, more: {}, local: {} },
    modal: null, drawer: null, fut: null, futErr: null,
    mobile: mq.matches, narrow: mqN.matches, deferred: false,
    anim: { nums: {}, cells: {}, first: true, tab: '' }, justOpened: new Set()
  };

  S.uiFoldS = {};
  S.sheet = null;
  const UI_FOLD_LS = 'tj_v2_fold', UI_FOLD_MAX = 400;
  const uiFoldMem = (() => { try { const o = JSON.parse(LS.get(UI_FOLD_LS) || '{}'); return o && typeof o === 'object' && !Array.isArray(o) ? o : {}; } catch (e) { return {}; } })();
  const uiFoldDef = {};
  const uiHas = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  function uiFoldPut(key, open, def) {
    delete uiFoldMem[key];
    if (!!open !== !!def) uiFoldMem[key] = open ? 1 : 0;
    const ks = Object.keys(uiFoldMem);
    if (ks.length > UI_FOLD_MAX) ks.slice(0, ks.length - UI_FOLD_MAX).forEach(k => { delete uiFoldMem[k]; });
    try { LS.set(UI_FOLD_LS, JSON.stringify(uiFoldMem)); } catch (e) {  }
  }
  function uiOpen(key, def, mem) {
    uiFoldDef[key] = [!!def, mem !== false];
    if (mem === false) return uiHas(S.uiFoldS, key) ? !!S.uiFoldS[key] : !!def;
    return uiHas(uiFoldMem, key) ? uiFoldMem[key] === 1 : !!def;
  }
  function uiSetOpen(key, open) { const d = uiFoldDef[key] || [false, true]; if (d[1]) uiFoldPut(key, open, d[0]); else S.uiFoldS[key] = !!open; }
  const uiReduce = () => !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const UI_CHEV = '<span class="uchev" aria-hidden="true">' + IC.chev + '</span>';
  function uiFold(key, o) {
    const open = uiOpen(key, o.def, o.mem);
    return '<div class="ufold' + (open ? ' open' : '') + (o.cls ? ' ' + o.cls : '') + '"' + (o.anc ? ' data-anc="' + esc(o.anc) + '"' : '') + '>'
      + '<button type="button" class="ufh" data-a="uiFold" data-v="' + esc(key) + '" aria-expanded="' + open + '"' + (o.label ? ' aria-label="' + esc(o.label) + '"' : '') + '>' + o.head + '<span class="sp"></span>' + (o.side || '') + UI_CHEV + '</button>'
      + (open ? clps('uf:' + key, o.body()) : '') + '</div>';
  }
  const uiWrapBtn = (b, o) => o.tr ? '<tr class="umtr"><td colspan="' + o.tr + '"><div class="umore">' + b + '</div></td></tr>' : '<div class="umore' + (o.cls ? ' ' + o.cls : '') + '">' + b + '</div>';
  const uiPgS = () => (S.uiPg || (S.uiPg = {}));
  const uiPageSize = () => { if (S.pgSz !== 10 && S.pgSz !== 20) { let v = null; try { v = LS.get('tj_v2_pgsize'); } catch (e) { v = null; } S.pgSz = v === '20' ? 20 : 10; } return S.pgSz; };
  const uiPgSz = size => Math.max(1, Math.min(+size || 20, uiPageSize()));
  function uiPgSlice(key, items) {
    const size = uiPageSize(), P = uiPgS(), F = S.uiPgFind && S.uiPgFind[key];
    if (F) { delete S.uiPgFind[key]; const i = items.findIndex(F); if (i >= 0) P[key] = Math.floor(i / size); }
    const last = Math.max(0, Math.ceil(items.length / size) - 1), p = Math.max(0, Math.min(last, P[key] | 0));
    if (uiHas(P, key)) P[key] = p;
    return { rows: items.slice(p * size, p * size + size), from: p * size, p, last };
  }
  function uiPgBar(key, total, o) {
    o = o || {};
    const size = uiPageSize(), P = uiPgS(), u = o.unit || '개', k = esc(key);
    const last = Math.max(0, Math.ceil(total / size) - 1), p = Math.max(0, Math.min(last, P[key] | 0));
    const fold = o.fold ? '<button type="button" class="ubtn upgx" data-a="uiPgClose" data-v="' + k + '" aria-label="목록 접기"><span class="upgxt">접기</span><span class="uchev up" aria-hidden="true">' + IC.chev + '</span></button>' : '';
    if (last === 0) return fold ? uiWrapBtn(fold, o) : '';
    const a = p * size + 1, b = Math.min(total, a + size - 1);
    const nav = (d, txt, lbl, dis) => '<button type="button" class="ubtn upgb" data-a="uiPg" data-v="' + k + '" data-p="' + (p + d) + '"' + (dis ? ' disabled' : '') + ' aria-label="' + lbl + '">' + txt + '</button>';
    return uiWrapBtn('<div class="upg" role="group" aria-label="쪽 넘기기">' + nav(-1, '‹ 이전', '이전 쪽', p === 0)
      + '<span class="upgt num pvx" aria-live="polite">' + nf('ko-KR').format(a) + '–' + nf('ko-KR').format(b) + ' <span class="mut">/ ' + nf('ko-KR').format(total) + '<span class="upgu">' + u + '</span></span></span>'
      + nav(1, '다음 ›', '다음 쪽', p === last) + fold + '</div>', o);
  }
  function uiPaged(key, items, row, o) {
    o = o || {};
    if (!items.length) return '';
    const anc = o.tr ? '<tr class="upga" data-pga="' + esc(key) + '"><td colspan="' + o.tr + '"></td></tr>' : '<div class="upga" data-pga="' + esc(key) + '"></div>';
    if (o.more && !uiHas(uiPgS(), key)) return anc + uiWrapBtn('<button type="button" class="ubtn" data-a="uiPgOpen" data-v="' + esc(key) + '">' + o.more(items.length) + UI_CHEV + '</button>', o);
    const s = uiPgSlice(key, items);
    return (o.more || s.last > 0 ? anc : '') + s.rows.map((x, i) => row(x, s.from + i)).join('') + uiPgBar(key, items.length, Object.assign({}, o, { fold: !!o.more }));
  }
  const uiPgReveal = (key, f) => { (S.uiPgFind || (S.uiPgFind = {}))[key] = f; };
  const uiPgReset = (pre) => { const P = uiPgS(); Object.keys(P).forEach(k => { if (k === pre || k.indexOf(pre) === 0) P[k] = 0; }); };
  function uiPgGo(el, v) {
    const k = el.dataset.v, P = uiPgS();
    if (v === null) delete P[k]; else P[k] = v;
    const ov = !!(el.closest && el.closest('#overlay'));
    const act = el.dataset.a, lbl = el.getAttribute('aria-label');
    (ov ? renderOverlay : renderView)();
    if (act === 'uiPg') {
      const bs = Array.from(document.querySelectorAll('[data-a="uiPg"]')).filter(x => x.dataset.v === k);
      const b = bs.find(x => x.getAttribute('aria-label') === lbl && !x.disabled) || bs.find(x => !x.disabled);
      if (b) { try { b.focus({ preventScroll: true }); } catch (e) {  } }
    }
    if (v === 0 && act === 'uiPgOpen') return;
    setTimeout(() => {
      const a = Array.from(document.querySelectorAll('[data-pga],[data-pgh]')).find(x => (x.getAttribute('data-pga') || x.getAttribute('data-pgh')) === k);
      const t = a ? a.closest('[data-pgh]') || a : null;
      if (!t) return;
      const top = t.getBoundingClientRect().top, th = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--toph')) || 72;
      if (top < th + 8 || top > window.innerHeight) t.scrollIntoView({ block: 'start', behavior: uiReduce() ? 'auto' : 'smooth' });
    }, 30);
  }
  const uiHidChip = (n, act, on, title) => '<button type="button" class="uhid pvx' + (on ? ' on' : '') + '" data-a="' + act + '" aria-pressed="' + !!on + '"' + (title ? ' title="' + esc(title) + '"' : '') + '>' + IC.eyeoff + '<span>숨김 ' + nf('ko-KR').format(n) + (on ? ' · 닫기' : '') + '</span>' + IC.right + '</button>';
  const uiCell = (lbl, val, act, v, tip, cls) => '<' + (act ? 'button type="button" data-a="' + act + '"' + (v != null ? ' data-v="' + esc(v) + '"' : '') : 'div') + ' class="ucell' + (cls ? ' ' + cls : '') + '"' + (tip ? ' title="' + esc(tip) + '"' : '') + '><span class="ul">' + lbl + '</span><b class="uv num">' + val + '</b></' + (act ? 'button' : 'div') + '>';
  const mFit = (full, comp) => (comp == null || comp === full ? full : '<span class="mfF">' + full + '</span><span class="mfC">' + comp + '</span>');
  const mCell = (v, o, f) => { f = f || m; o = o || {}; const c = f(v, Object.assign({}, o, { compact: true })); return S.mobile ? c : mFit(f(v, o), c); };
  const mCellF = (v, o, f) => String(mCell(v, o, f)).replace('<span class="mfF">', '<span class="mfF ff">');
  function fitUv(root) {
    (root || document).querySelectorAll('.ucell .uv').forEach(el => {
      el.classList.remove('cmp', 'wrap'); el.style.fontSize = '';
      const over = () => el.clientWidth > 0 && el.scrollWidth > el.clientWidth + 1;
      if (!over()) return;
      const f0 = parseFloat(getComputedStyle(el).fontSize) || 15;
      if (el.querySelector('.mfF.ff')) { for (const k of [0.92, 0.84]) { el.style.fontSize = (f0 * k).toFixed(1) + 'px'; if (!over()) return; } el.style.fontSize = ''; }
      if (el.querySelector('.mfC')) { el.classList.add('cmp'); if (!over()) return; }
      for (const k of [0.92, 0.84]) { el.style.fontSize = (f0 * k).toFixed(1) + 'px'; if (!over()) return; }
      el.classList.add('wrap');
    });
  }
  let fitUvRaf = 0;
  const fitUvSoon = () => { if (fitUvRaf) return; fitUvRaf = requestAnimationFrame(() => { fitUvRaf = 0; fitUv(); }); };
  window.addEventListener('resize', fitUvSoon, { passive: true });
  try { if (document.fonts) { document.fonts.addEventListener('loadingdone', fitUvSoon); document.fonts.ready.then(fitUvSoon); } } catch (e) {  }
  const UI_PICK = {};
  S.uiDateYm = {};
  const uiRe = () => { renderView(); if (S.sheet || S.drawer) renderOverlay(); };
  const uiPopBox = (title, inner, cls) => (S.mobile ? '<div class="sheet-bg" data-a="uiPopClose"></div>' : '') + '<div class="pop upop' + (cls ? ' ' + cls : '') + '" role="dialog" aria-label="' + esc(title) + '"><div class="ptl">' + esc(title) + '</div>' + inner + '</div>';
  function uiPick(key, opts, cur, label, o) {
    o = o || {};
    const pk = 'pick:' + key, open = S.pop === pk, c = opts.find(x => x[0] === cur) || opts[0] || ['', ''];
    const ck = '<svg class="ck" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12l5 5 9-10"/></svg>';
    return '<div class="popw upick' + (o.cls ? ' ' + o.cls : '') + '"><button type="button" class="fbtn upkb' + (o.act && opts[0] && c[0] !== opts[0][0] ? ' act' : '') + '" data-a="uiPopOpen" data-v="' + esc(pk) + '" aria-haspopup="listbox" aria-expanded="' + open + '" aria-label="' + esc(label + ' — ' + c[1]) + '">'
      + (o.pre ? '<span class="upkl">' + esc(o.pre) + '</span>' : '') + '<span class="fbl">' + esc(c[1]) + '</span>' + IC.chev.replace('<svg', '<svg class="cv"') + '</button>'
      + (open ? uiPopBox(label, '<div class="scroll" role="listbox" aria-label="' + esc(label) + '">' + opts.map(x => '<button type="button" class="opt' + (x[0] === c[0] ? ' on' : '') + '" role="option" aria-selected="' + (x[0] === c[0]) + '" data-a="uiPick" data-k="' + esc(key) + '" data-v="' + esc(x[0]) + '">' + esc(x[1]) + ck + '</button>').join('') + '</div>', 'upk') : '') + '</div>';
  }
  function uiDate(key, val, o) {
    o = o || {};
    const pk = 'date:' + key, open = S.pop === pk, v = isISO(val) ? val : '', mx = o.max || todayISO(), mn = o.min || '2000-01-01';
    const dow = iso => DOWS[new Date(iso + 'T00:00:00').getDay()];
    const btn = '<button type="button" class="field udt"' + (o.id ? ' id="' + esc(o.id) + '"' : '') + ' data-a="uiPopOpen" data-v="' + esc(pk) + '" aria-haspopup="dialog" aria-expanded="' + open + '" aria-label="' + esc((o.label || '날짜') + ' — ' + (v || '고르지 않음')) + '">' + IC.cal + '<span class="num pvx">' + (v ? v + ' (' + dow(v) + ')' : '날짜 고르기') + '</span>' + IC.chev.replace('<svg', '<svg class="cv"') + '</button>';
    if (!open) return '<div class="popw udate">' + btn + '</div>';
    const ym = S.uiDateYm[key] || (v || mx).slice(0, 7), y = +ym.slice(0, 4), mo = +ym.slice(5) - 1;
    const first = new Date(y, mo, 1).getDay(), dim = new Date(y, mo + 1, 0).getDate(), td = todayISO();
    let cells = DOWS.map(d => '<span>' + d + '</span>').join('');
    for (let i = 0; i < first; i++) cells += '<span></span>';
    for (let d = 1; d <= dim; d++) { const iso = ym + '-' + pad2(d); cells += '<button type="button" class="' + (iso === v ? 'edge lo hi' : iso === td ? 'tdy' : '') + '" data-a="uiDatePick" data-k="' + esc(key) + '" data-v="' + iso + '"' + (iso > mx || iso < mn ? ' disabled' : '') + ' aria-label="' + iso + '">' + d + '</button>'; }
    const inner = '<div class="mh"><button type="button" data-a="uiDateMonth" data-k="' + esc(key) + '" data-v="-1"' + (ym > mn.slice(0, 7) ? '' : ' disabled') + ' aria-label="이전 달">' + IC.left + '</button><span class="sp pvx" style="text-align:center">' + y + '년 ' + (mo + 1) + '월</span><button type="button" data-a="uiDateMonth" data-k="' + esc(key) + '" data-v="1"' + (ym < mx.slice(0, 7) ? '' : ' disabled') + ' aria-label="다음 달">' + IC.right + '</button></div>'
      + '<div class="g pvx">' + cells + '</div><div class="ft"><button type="button" class="btn sm" data-a="uiDatePick" data-k="' + esc(key) + '" data-v="' + (td <= mx ? td : mx) + '">오늘</button><button type="button" class="btn sm" data-a="uiPopClose">닫기</button></div>';
    return '<div class="popw udate">' + btn + uiPopBox(o.label || '날짜', inner, 'rp udp') + '</div>';
  }
  const UI_SHEETS = {};
  window.__tjSheets = { reg: (k, fn) => { UI_SHEETS[k] = fn; }, open: (k, v, t, el) => uiSheetOpen(k, v, t, el), close: noBack => uiSheetClose(noBack), redraw: () => renderOverlay() };
  function uiSheetOpen(k, v, t, el) {
    if (!UI_SHEETS[k]) return;
    const first = !S.sheet;
    S.sheet = { k, v, t, back: first ? (el && el.getAttribute ? { el, a: el.getAttribute('data-a'), v: el.getAttribute('data-v'), k: el.getAttribute('data-k') } : null) : S.sheet.back };
    S.pop = null;
    if (first) drawerHist();
    renderOverlay();
    setTimeout(() => { const f = $('#overlay .usheet input:not([disabled]):not([type="hidden"]),#overlay .usheet textarea:not([disabled])') || $('#overlay .usheet .ush [data-a="uiSheetClose"]'); if (f) { try { f.focus({ preventScroll: true }); } catch (e) {  } } }, 30);
  }
  function uiSheetClose(noBack) {
    const bk = S.sheet && S.sheet.back;
    if (!S.sheet) return;
    S.sheet = null; S.pop = null; renderOverlay();
    if (history.state && history.state.tjDr) { try { if (noBack) history.replaceState(null, '', location.href); else history.back(); } catch (e) {  } }
    const el = bk && (bk.el && bk.el.isConnected ? bk.el : [...document.querySelectorAll(['#view', '#mtop', 'header.top'].map(r => r + ' [data-a="' + bk.a + '"]').join(','))].find(x => x.getAttribute('data-v') === bk.v && x.getAttribute('data-k') === bk.k));
    if (el && el.focus) { try { el.focus({ preventScroll: true }); } catch (e) {  } }
  }
  function uiSheetCloseThen(then) {
    if (!S.sheet) { then(); return; }
    const back = !!(history.state && history.state.tjDr);
    let done = false;
    const fin = () => { if (done) return; done = true; window.removeEventListener('popstate', onPop9); then(); };
    const onPop9 = () => setTimeout(fin, 0);
    if (back) { window.addEventListener('popstate', onPop9); setTimeout(fin, 600); }
    uiSheetClose();
    if (!back) fin();
  }
  function uiSheetHTML() {
    const s = S.sheet, fn = s && UI_SHEETS[s.k];
    if (!fn) return '';
    return '<div class="usheet-bg" data-a="uiSheetClose"></div><div class="usheet" role="dialog" aria-modal="true" aria-labelledby="usT"><div class="ush dh"><h4 id="usT">' + esc(s.t) + '</h4><span class="sp"></span><button type="button" class="iconbtn" data-a="uiSheetClose" aria-label="닫기">' + IC.close + '</button></div>'
      + '<div class="usb">' + fn(s.v) + '</div></div>';
  }
  window.addEventListener('popstate', ev => { if (S.sheet && !(ev.state && ev.state.tjDr)) uiSheetClose(true); });
  const UI_REVEAL = {};
  const uiAnc = a => { const q = '[data-anc="' + (window.CSS && CSS.escape ? CSS.escape(String(a)) : String(a).replace(/["\\]/g, '\\$&')) + '"]'; const xs = Array.from(document.querySelectorAll(q)); return xs.find(x => x.offsetParent || x.getClientRects().length) || null; };
  function revealAndHighlight(target) {
    const t = typeof target === 'string' ? { kind: target.slice(0, Math.max(0, target.indexOf(':'))), id: target.slice(target.indexOf(':') + 1) } : (target || {});
    const kind = String(t.kind || ''), id = String(t.id == null ? '' : t.id), fn = UI_REVEAL[kind];
    if (!fn || !S.D) return Promise.resolve(false);
    let r = null;
    try { r = fn(id) || {}; } catch (e) { logError('[tj] 찾아가기 실패', e); return Promise.resolve(false); }
    const anc = r.anc || (kind + ':' + id);
    S.pop = null; S.modal = null;
    if (S.drawer) closeDrawer(true);
    if (S.sheet) uiSheetClose(true);
    S.urlPeriod = true;
    if (r.tab && r.tab !== S.tab) { S.tab = r.tab; try { history.pushState(null, '', location.pathname + location.search + '#' + r.tab); } catch (e) {  } syncUrl(); }
    else syncUrl();
    render();
    return new Promise(res => {
      let n = 0;
      const tick = () => {
        const el = uiAnc(anc);
        if (!el) { if (++n < 40) { setTimeout(tick, 100); return; } res(false); return; }
        const red = uiReduce();
        try { el.scrollIntoView({ block: 'center', behavior: red ? 'auto' : 'smooth' }); } catch (e) { el.scrollIntoView(); }
        el.classList.remove('uhl'); void el.offsetWidth; el.classList.add('uhl');
        const f = rowFocusEl(el);
        if (f) { try { f.focus({ preventScroll: true }); } catch (e) {  } }
        setTimeout(() => el.classList.remove('uhl'), 2200);
        res(true);
      };
      requestAnimationFrame(tick);
    });
  }
  function uiPopBack(pk) { if (!pk) return; const b = Array.from(document.querySelectorAll('[data-a="uiPopOpen"]')).find(x => x.getAttribute('data-v') === pk); if (b) { try { b.focus({ preventScroll: true }); } catch (e) {  } } }

  const nowD = () => new Date();
  const KST_MS = 32400000;
  const kstYMD = t => { const z = new Date(t + KST_MS); return { y: z.getUTCFullYear(), m: z.getUTCMonth() + 1, d: z.getUTCDate() }; };
  const kstISOAt = t => { const k = kstYMD(t); return k.y + '-' + pad2(k.m) + '-' + pad2(k.d); };
  const kstMid = iso => Date.parse(iso + 'T00:00:00+09:00');
  const todayISO = () => kstISOAt(nowD().getTime());
  const isISO = s => /^\d{4}-\d{2}-\d{2}$/.test(String(s == null ? '' : s));
  const isMD = s => { if (!s || s.length < 5 || s.charAt(2) !== '-') return false; const mm = +s.slice(0, 2), dd = +s.slice(3, 5); return mm >= 1 && mm <= 12 && dd >= 1 && dd <= 31; };
  const ymShift = off => { const k = kstYMD(nowD().getTime()), d = new Date(Date.UTC(k.y, k.m - 1 + off, 1)); return d.getUTCFullYear() + '-' + pad2(d.getUTCMonth() + 1); };
  const isYMD = s => /^\d{4}-\d{2}-\d{2}/.test(String(s == null ? '' : s));
  const mdOf = k => { const s = String(k == null ? '' : k); return isYMD(s) ? s.slice(5, 10) : s.slice(0, 5); };
  let ymNowC = { since: 0, until: 0, y: 0, m: 0, day: '' };
  function ymNow() {
    const t = Date.now();
    if (t >= ymNowC.until || t < ymNowC.since) {
      const k = kstYMD(t), s0 = Date.UTC(k.y, k.m - 1, k.d) - KST_MS;
      ymNowC = { since: s0, until: s0 + 86400000, y: k.y, m: k.m, day: k.y + '-' + pad2(k.m) + '-' + pad2(k.d) };
    }
    return ymNowC;
  }
  function ymOf(mmdd) {
    if (isYMD(mmdd)) return String(mmdd).slice(0, 7);
    const s = String(mmdd == null ? '' : mmdd).slice(0, 5);
    if (!isMD(s)) return '';
    const c = ymNow(), mm = +s.slice(0, 2);
    const y = mm <= c.m ? c.y : c.y - 1;
    return y + '-' + pad2(mm);
  }
  const isoDay = mmdd => { if (isYMD(mmdd)) return String(mmdd).slice(0, 10); const ym = ymOf(mmdd); return ym ? ym + '-' + String(mmdd).slice(3, 5) : ''; };
  const isoOf = t => { const s = String(t || ''); const ym = ymOf(s); return ym ? ym + '-' + s.slice(3) : ''; };
  const dayKeyOf = v => {
    const s = String(v == null ? '' : v);
    if (!isYMD(s)) return isMD(s.slice(0, 5)) ? s.slice(0, 5) : null;
    const iso = s.slice(0, 10), md = iso.slice(5);
    return iso >= rollMinISO() && iso <= todayISO() && isoDay(md) === iso ? md : null;
  };
  const rollMinISO = () => { const k = kstYMD(nowD().getTime()), d = new Date(Date.UTC(k.y - 1, k.m, 1)); return d.getUTCFullYear() + '-' + pad2(d.getUTCMonth() + 1) + '-01'; };
  const clampISO = v => { const lo = rollMinISO(), hi = todayISO(); return v < lo ? lo : (v > hi ? hi : v); };
  function gRange() {
    const f = isISO(S.g.from) ? S.g.from : '', t = isISO(S.g.to) ? S.g.to : '';
    return (f && t && f > t) ? { lo: t, hi: f } : { lo: f, hi: t };
  }
  function gPass(mmdd) {
    const p = S.g.period;
    if (p === 'all') return true;
    const s = isYMD(mmdd) ? String(mmdd).slice(5, 10) : String(mmdd == null ? '' : mmdd).slice(0, 5);
    if (!isMD(s)) return false;
    const ym = ymOf(isYMD(mmdd) ? mmdd : s);
    if (p === 'thismonth') return ym === ymShift(0);
    if (p === 'lastmonth') return ym === ymShift(-1);
    if (p === '90d') { const d = kstMid(ym + '-' + s.slice(3, 5)); return isFinite(d) && (nowD().getTime() - d) <= 90 * 86400000; }
    if (p === 'custom') {
      const r = gRange(); if (!r.lo && !r.hi) return true;
      const iso = ym + '-' + s.slice(3, 5);
      return !(r.lo && iso < r.lo) && !(r.hi && iso > r.hi);
    }
    return true;
  }
  function perMonthAligned() {
    const p = S.g.period;
    if (p === 'all' || p === 'thismonth' || p === 'lastmonth') return true;
    if (p !== 'custom') return false;
    const r = gRange();
    const loOk = !r.lo || r.lo.slice(8) === '01';
    const hiOk = !r.hi || r.hi >= todayISO() || (() => { const d = new Date(Date.UTC(+r.hi.slice(0, 4), +r.hi.slice(5, 7), 0)); return +r.hi.slice(8) === d.getUTCDate(); })();
    return loOk && hiOk;
  }
  function ymPass(ym) {
    const p = S.g.period;
    if (p === 'all') return true;
    if (p === 'thismonth') return ym === ymShift(0);
    if (p === 'lastmonth') return ym === ymShift(-1);
    if (p === '90d') return ym >= kstISOAt(nowD().getTime() - 90 * 86400000).slice(0, 7) && ym <= ymShift(0);
    if (p === 'custom') { const r = gRange(); if (r.lo && ym < r.lo.slice(0, 7)) return false; if (r.hi && ym > r.hi.slice(0, 7)) return false; return true; }
    return true;
  }
  function periodName() {
    const p = S.g.period;
    if (p === '90d') return '최근 3개월';
    if (p === 'all') return '전체 기간';
    if (p === 'custom') {
      const r = gRange();
      if (!r.lo && !r.hi) return '직접 지정';
      if (!r.lo) return r.hi + ' 까지';
      if (!r.hi) return r.lo + ' 부터';
      if (r.lo === r.hi) return r.lo + ' 하루';
      return r.lo.slice(0, 4) === r.hi.slice(0, 4) ? r.lo.slice(5) + ' → ' + r.hi.slice(5) : r.lo + ' → ' + r.hi;
    }
    return (+ymShift(p === 'lastmonth' ? -1 : 0).slice(5)) + '월';
  }
  function gBounds() {
    const p = S.g.period;
    if (p === 'all') return null;
    if (p === 'thismonth' || p === 'lastmonth') { const ym = ymShift(p === 'lastmonth' ? -1 : 0); return { lo: ym + '-01', hi: ym + '-31' }; }
    if (p === '90d') {
      const c = nowD().getTime() - 90 * 86400000, ci = kstISOAt(c), m0 = kstMid(ci);
      return { lo: m0 < c ? kstISOAt(m0 + 86400000) : ci, hi: todayISO() }; }
    const r = gRange(); return { lo: r.lo || '', hi: r.hi || '' };
  }
  function pAgg(p) {
    if (p._aggK === S.g.period + '|' + S.g.from + '|' + S.g.to) return p._agg;
    const b = gBounds(), a = { has: p.realizedByDay != null, inR: 0, inB: 0, inS: 0, inP: 0, inU: 0, inUP: 0, befR: 0, aftR: 0, aftS: 0, aftD: [], allU: 0, allUP: 0, any: false,
      hasK: !!p.realizedKrwByDay, inRK: 0, befRK: 0, aftRK: 0, allRK: 0 };
    const side = k => { if (gPass(k)) return 0; const iso = isoDay(k); return b && b.lo && iso < b.lo ? -1 : 1; };
    const rb = p.realizedByDay || {}, ab = p.actByDay || {}, ub = p.unvByDay || {};
    Object.keys(rb).forEach(k => { const v = num(rb[k]), sd = side(k); if (!sd) { a.inR += v; a.any = true; } else if (sd < 0) a.befR += v; else { a.aftR += v; if (a.aftD.indexOf(k) < 0) a.aftD.push(k); } });
    const rk = p.realizedKrwByDay || {};
    Object.keys(rk).forEach(k => { const v = num(rk[k]), sd = side(k); a.allRK += v; if (!sd) a.inRK += v; else if (sd < 0) a.befRK += v; else a.aftRK += v; });
    Object.keys(ab).forEach(k => { const x = arr(ab[k]), sd = side(k); if (!sd) { a.inB += num(x[0]); a.inS += num(x[1]); a.any = true; } else if (sd > 0 && num(x[1]) > 0) { a.aftS += num(x[1]); if (a.aftD.indexOf(k) < 0) a.aftD.push(k); } });
    Object.keys(p.payByDay || {}).forEach(k => { if (!side(k)) a.inP += num(p.payByDay[k]); });
    Object.keys(ub).forEach(k => { const x = arr(ub[k]); if (num(x[1]) < 1) return;
      a.allU += num(x[0]); a.allUP += num(x[1]); if (!side(k)) { a.inU += num(x[0]); a.inUP += num(x[1]); a.any = true; } });
    a.aftD.sort((x, y) => isoDay(x) < isoDay(y) ? -1 : 1);
    p._aggK = S.g.period + '|' + S.g.from + '|' + S.g.to; p._agg = a;
    return a;
  }
  function cardReal(p) {
    if (S.g.period === 'all' || p.realizedByDay == null) return num(p.realized) + num(p.realizedFb);
    return pAgg(p).inR;
  }
  function cardRealV(p) {
    const r = cardReal(p);
    if (!p.realizedKrwByDay) return r;
    const a = pAgg(p);
    return KV(r, S.g.period === 'all' ? a.allRK : a.inRK);
  }
  function srcPass(e) {
    const mode = S.src.mode;
    if (mode === 'all') return true;
    const s = e && e.src ? String(e.src) : '';
    const key = S.src.key.toLowerCase();
    if (mode === 'dex') return s.slice(0, 2) === 'w:' && (!key || s.slice(2).toLowerCase() === key);
    if (mode === 'cex') return s.slice(0, 3) === 'ex:' && (!key || s.slice(3).toLowerCase() === key);
    return true;
  }
  function dayCnt(k, all) {
    const D = S.D; if (!D || !D.dayActs) return null;
    const a = D.dayActs[isoDay(k)], o = { n: 0, b: 0, s: 0, dep: 0, pay: 0 };
    if (!a) return o;
    if (all || S.src.mode === 'all') return { n: num(a.n) + num(a.cv) + num(a.kw), b: num(a.b), s: Math.max(0, num(a.s) - num(a.pay)), dep: num(a.dep), pay: num(a.pay) };
    Object.keys(a.src || {}).forEach(sk => { if (!srcPass({ src: sk })) return; const x = arr(a.src[sk]), py = num((a.srcPay || {})[sk]); o.n += num(x[0]); o.b += num(x[1]); o.s += Math.max(0, num(x[2]) - py); o.dep += num(x[3]); o.pay += py; });
    Object.keys(a.cvSrc || {}).forEach(sk => { if (srcPass({ src: sk })) o.n += num(a.cvSrc[sk]); });
    Object.keys(a.kwSrc || {}).forEach(sk => { if (srcPass({ src: sk })) o.n += num(a.kwSrc[sk]); });
    return o;
  }
  function srcAgg(p) {
    if (!p || !p.srcAct) return null;
    const o = { any: false, s: 0, dep: 0 };
    Object.keys(p.srcAct).forEach(sk => { if (!srcPass({ src: sk })) return; const mp = p.srcAct[sk] || {};
      Object.keys(mp).forEach(k => { if (!gPass(k)) return; const x = arr(mp[k]); if (num(x[0]) > 0) o.any = true; o.s += num(x[2]); o.dep += num(x[3]); }); });
    return o;
  }
  const evKind = (k, d) => (k === '전송' && /· 스테이킹 보상 \(/.test(String(d || '')) ? '스테이킹 보상' : k);
  const normDayEv = list => arr(list).filter(e => e && e.k !== '평단 갱신').map(e => ({ t: e.t, sym: e.sym, k: evKind(e.k, e.d), d: e.d, q: e.q, a: e.a, aK: e.aK, tx: e.tx, src: e.src, imp: e.imp, hide: e.hide, hideKind: e.hideKind, of: e.of, ofc: e.ofc,
    pkey: e.kind === 'pos' ? e.pkey : undefined, lp: e.lp, iso: (e.iso ? String(e.iso).slice(0, 10) + ' ' + String(e.t || '').slice(6) : isoOf(e.t)), day: String(e.t || '').slice(0, 5) }));
  async function fetchDayEvents(q) {
    try {
      const r = await fetch('/api/day_events' + (q ? '?' + q : ''), { cache: 'no-store' });
      if (r.status === 401) { onUnauthorized(); return null; }
      if (!r.ok) return null;
      const j = await r.json();
      if (!j || !j.ok) return null;
      const cv = arr(j.conv).concat(arr(j.krw)), ev0 = cv.length ? arr(j.events).concat(cv).sort((x, y) => num(y.ts) - num(x.ts)) : j.events;
      return { events: normDayEv(ev0), hidden: normDayEv(j.hidden), builtAt: j.builtAt, n: num(j.n) - num((j.counts || {})['평단 갱신']) + cv.length, more: !!j.more, nextOffset: num(j.offset) + arr(j.events).length, nHidden: j.nHidden != null ? num(j.nHidden) : null };
    } catch (e) { return null; }
  }
  const FEED_PAGE = 5000, WIDE_DAYS = 120;
  const isoSpanDays = (lo, hi) => (lo && hi) ? Math.round((new Date(hi + 'T00:00:00') - new Date(lo + 'T00:00:00')) / 86400000) : Infinity;
  function dayFull(k) {
    const D = S.D, iso = isoDay(k);
    if (!D || !D.dayActs || !iso) return null;
    const C = S.dayFull || (S.dayFull = {}), c = C[iso];
    if (c && (c.at === D.builtAt || c.st === 'load')) return c.evs || null;
    C[iso] = { at: D.builtAt, st: 'load', evs: c && c.evs };
    fetchDayEvents('date=' + iso).then(x => {
      const cur = C[iso]; if (!cur) return;
      if (x) C[iso] = { at: cur.at, st: 'ok', evs: x.events };
      else C[iso] = { at: cur.at, st: 'err', evs: cur.evs };
      if (S.tab === 'daily' || S.tab === 'dash') render();
    });
    return c && c.evs || null;
  }
  function dayWait(k) { const D = S.D, iso = isoDay(k), c = iso && (S.dayFull || {})[iso]; return !!(D && D.dayActs && c && c.st === 'load' && !c.evs); }
  function evSkel(rows, heads) {
    const bar = w => '<i class="skl" style="width:' + w + '%"></i>';
    let h = '';
    for (let i = 0; i < rows; i++) h += '<div class="evsk">' + bar(24 + (i * 23) % 40) + bar(44 + (i * 31) % 44) + '</div>';
    for (let i = 0; i < heads; i++) h += '<div class="evsk h">' + bar(30 + (i * 17) % 30) + '</div>';
    return '<div class="evskw" aria-hidden="true">' + h + '</div>';
  }
  const rfrTag = () => '<span class="rfr" aria-hidden="true">새로 받는 중</span>';
  function feedFull() {
    const D = S.D; if (!D || !D.dayActs) return null;
    const b = gBounds(), key = b ? (b.lo || '') + '~' + (b.hi || '') : 'all', c = S.feedFull;
    if (c && c.key === key && (c.at === D.builtAt || c.st === 'load' || c.st === 'more' || Date.now() - c.t < 120000)) return c.evs ? c : null;
    const keep = c && c.key === key ? c : null;
    const paged = !b || isoSpanDays(b.lo, b.hi) > WIDE_DAYS;
    const qs = (b ? 'from=' + encodeURIComponent(b.lo || '') + '&to=' + encodeURIComponent(b.hi || '') : '') + (paged ? (b ? '&' : '') + 'limit=' + FEED_PAGE + '&offset=0' : '');
    const nc = S.feedFull = { key, at: D.builtAt, t: Date.now(), st: 'load', evs: keep && keep.evs, hid: keep && keep.hid, paged, qs0: b ? 'from=' + encodeURIComponent(b.lo || '') + '&to=' + encodeURIComponent(b.hi || '') : '', more: keep ? keep.more : false, n: keep ? keep.n : null, nHid: keep ? keep.nHid : null };
    fetchDayEvents(qs).then(x => {
      if (S.feedFull !== nc) return;
      if (x) { nc.st = 'ok'; nc.evs = x.events; nc.hid = x.hidden.slice().reverse(); nc.more = paged && x.more; nc.n = x.n; nc.nHid = x.nHidden; nc.bat = x.builtAt; nc.nextOffset = x.nextOffset; } else nc.st = 'err';
      nc.t = Date.now();
      if (S.tab === 'journal' && S.j.view === 'feed') render();
    });
    return keep && keep.evs ? keep : null;
  }
  function feedMoreLoad() {
    const c = S.feedFull; if (!c || !c.paged || !c.more || c.st !== 'ok' || !c.evs) return;
    c.st = 'more';
    fetchDayEvents((c.qs0 ? c.qs0 + '&' : '') + 'limit=' + FEED_PAGE + '&offset=' + c.nextOffset).then(x => {
      if (S.feedFull !== c) return;
      c.st = 'ok'; c.t = Date.now();
      if (x && x.builtAt === c.bat) { c.evs = c.evs.concat(x.events); c.more = x.more; c.nextOffset = x.nextOffset; }
      else if (x) { const t9 = Date.now(); if (t9 - (S.feedRestartAt || 0) > 30000) { S.feedRestartAt = t9; S.feedFull = null; } else { c.st = 'err'; c.more = false; } }
      else c.st = 'err';
      if (S.tab === 'journal' && S.j.view === 'feed') render();
    });
  }
  const dayEvs = k => dayFull(k) || S.D.evByDay.get(k) || [];
  const PX_STALE = 1800;
  const ageTxt = s => s < 3600 ? Math.max(1, Math.floor(s / 60)) + '분 전' : Math.floor(s / 3600) + '시간 전';
  const PX_SRC = { gecko: 'DEX(게코)', dexscreener: 'DEX(덱스스크리너)', okx: 'DEX(OKX)' };
  const pxSrcTxt = i => {
    if (!i.pxSrc) return '';
    if (i.pxSrc === 'rabby') return 'Rabby 기준' + (i.pxAge != null ? ' · ' + ageTxt(Math.max(60, i.pxAge)) : '');
    const p9 = i.pxSrc.split(':'), lab = p9[0] === 'cex' ? (p9.slice(1).join(':') + ' 시세') : (PX_SRC[p9[1]] || 'DEX');
    return (i.pxPre ? '거래 시작 전 · ' : '') + lab + (i.pxPreN ? ' · ' + i.pxPreN + '곳 일치' : '') + (i.pxAge != null && i.pxAge > PX_STALE ? ' · ≈ ' + ageTxt(i.pxAge) : '');
  };
  const rbChip = g => g && g.rabby ? ' <span class="pill a sm rbchip" title="봇이 추적하지 않는 보유예요 — Rabby(DeBank 데이터)가 이 지갑에 있다고 본 수량·USD 로 총자산에 더했어요(원가·손익 추적 밖). 봇이 그 체인·토큰을 추적하면 자동으로 봇 숫자로 바뀌어요">Rabby 기준 · ' + ago(g.rabby) + '</span>' : '';
  const staleChip = g => g.staleAge && g.staleVal >= g.value * 0.1 ? ' <span class="pill w sm" title="DEX 가격이 ' + ageTxt(g.staleAge) + ' 값이에요 — 조회가 밀려 마지막 가격으로 평가 중(6시간 넘으면 평가 제외)">≈ ' + ageTxt(g.staleAge) + '</span>' : '';
  const ago = ts => {
    const s = Math.max(0, Date.now() / 1000 - num(ts));
    if (s < 60) return '방금'; if (s < 3600) return Math.floor(s / 60) + '분 전'; if (s < 86400) return Math.floor(s / 3600) + '시간 전';
    return Math.floor(s / 86400) + '일 전';
  };
  const fmtTs = v => {
    if (v == null || v === '') return '';
    if (typeof v === 'number' || /^\d+(\.\d+)?$/.test(String(v))) { const n = num(v), d = new Date(n * (n < 1e12 ? 1000 : 1) + KST_MS); return pad2(d.getUTCMonth() + 1) + '-' + pad2(d.getUTCDate()) + ' ' + pad2(d.getUTCHours()) + ':' + pad2(d.getUTCMinutes()); }
    return String(v);
  };

  const NFC = {};
  const nf = (loc, mn, mx) => {
    const k = loc + '|' + mn + '|' + mx;
    return NFC[k] || (NFC[k] = new Intl.NumberFormat(loc, mn == null && mx == null ? undefined
      : (mn == null ? { maximumFractionDigits: mx } : { minimumFractionDigits: mn, maximumFractionDigits: mx })));
  };
  const rate = () => (S.D && S.D.rate) || 1384;
  const isZ = v => { const a = Math.abs(KS(num(v))); return S.cur === 'USD' ? a < 0.005 : a * rate() < 0.5; };
  const KRW_BASIS = '원화 환산 = 업비트 USDT 원화 시세(김프 포함)';
  const KV = (usd, krw) => (S.cur !== 'USD' && krw != null && isFinite(krw)) ? num(krw) / rate() : usd;
  const dayV = x => x ? KV(num(x.val), x.valKrw) : null;
  const retPct = (first, last, flowSum) => (num(first) ? (num(last) - num(first) - num(flowSum)) / num(first) * 100 : null);
  const dayFlowV = x => (x && x.flow != null) ? KV(num(x.flow), x.valKrw != null && num(x.usdt) > 0 ? num(x.flow) * num(x.usdt) : null) : null;
  const PV_A = '\uE000', PV_Z = '\uE001', PV_RE = /\uE000([^\uE001]*)\uE001/g;
  const pvW = s => PV_A + s + PV_Z;
  const PVM = { krw: '8,888,888', krwC: '8,888만', usd: '88,888', usdC: '88.8K', q: '8,888.88', px: '8.8888', cal: '888만', calM: '88만', calU: '8.8K', n: '8,888' };
  const pvMoney = (sg, compact) => sg + (S.cur === 'USD' ? '$' + pvW(compact ? PVM.usdC : PVM.usd) : '₩' + pvW(compact ? PVM.krwC : PVM.krw));
  const pvm = h => '<span class="pvm">' + String(h).replace(PV_RE, '<span class="pv">$1</span>') + '</span>';
  const RK_OK = v => typeof v === 'number' && isFinite(v) && v >= 0.2 && v <= 5 && !(v > 0.8 && v < 1.25);
  const rkFix = () => { const v = parseFloat(LS.get('tj_v2_rk') || ''); return RK_OK(v) ? v : null; };
  const RK_DRAW = (() => {
    let u = 0.5;
    try { const b = new Uint32Array(1); window.crypto.getRandomValues(b); u = b[0] / 4294967296; } catch (e) { u = Math.random(); }
    const L4 = Math.log(4);
    return Math.exp(u < 0.5 ? Math.log(0.2) + u * 2 * L4 : Math.log(1.25) + (u - 0.5) * 2 * L4);
  })();
  let RK = rkFix() || RK_DRAW;
  const RS_A = '\uE004', RS_Z = '\uE005', RS_RE = /\uE004([^\uE005]*)\uE005/g;
  const MK_RE = /(\uE000[^\uE001]*\uE001|\uE004[^\uE005]*\uE005)/;
  function KS(v) { return S.rand ? v * RK : v; }
  const rw = x => (S.rand ? RS_A + x + RS_Z : x);
  const pvNetM = t => String(t == null ? '' : t).split(MK_RE).map((x, i) => (i % 2 ? x : pvNet(x))).join('');
  const pvOn = () => S.hide || S.rand;
  const PR_FAKE = '메모 내용 8,888';
  const prTxt = (t, cls) => '<span class="prt' + (cls ? ' ' + cls : '') + '">' + (pvOn() ? pvW(PR_FAKE) : esc(t)) + '</span>';
  const PV_KEEP_U = /^\s?(%|‰|건|개월|일(?!\s*때)|시간|분(?![할배산류석기])|초(?!반)|월|년|회(?![복수전])|종(?![가료목합])|곳|번(?![호])|가지|명(?![세의])|줄|행(?![사])|주(?=\s?(?:연속|째|간|전|동안|마다|뒤|후|차))|배(?![당분송])|위(?![험치])|단계|차(?![감입익액이단])|칸|승(?![인격])|패(?![턴스])|묶음|지갑|페어|체인|쌍|계정|주소|거래소|블록|[KMGT]B\b|\/시|bp|px|x\b)/;
  const PV_KEEP_DEC = /^\s?(%|‰|배|시간|개월|[KMGT]B\b|bp|px|x\b)/;
  const PV_KEEP_P = /(?:\bnonce|계정)\s?$/;
  const PV_NUM = /([+\-−]?)(?:((?:US)?\$|₩)(\s?))?((?:\d[\d,]*(?:\.\d+)?|\.\d+)(?:[eE][+\-]?\d+)?)(\s?(?:억|만|천|[KMB](?![A-Za-z]))(?:\s?\d[\d,]*(?:\.\d+)?\s?(?:만|천))?)?/g;
  const PV_PROT = /\d{4}-\d{2}(?:-\d{2})?(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?|\b\d{2}-\d{2}(?: \d{1,2}:\d{2}(?::\d{2})?)?|\b\d{1,2}:\d{2}(?::\d{2})?|\b\d{1,2}\/\d{1,2}\b|(?:USDT|매매기준율|환율)\s?₩\s?[\d,]+(?:\.\d+)?|#\d+|[×x]\s?\d+(?:\.\d+)?/g;
  function pvNet(t) {
    t = String(t == null ? '' : t);
    if (typeof ownScrub === 'function') { t = ownScrub(t); if (!/\d/.test(t)) return t; }
    else if (!/\d/.test(t)) return t;
    const prot = [];
    const keep = a => { prot.push(a); return '\uE002' + (prot.length - 1) + '\uE003'; };
    const nre = typeof ownScrub !== 'function' && typeof pvNameRe === 'function' ? pvNameRe() : null;
    if (nre) t = t.replace(nre, (a, pre, nm, suf) => pre + keep(locMask(nm)) + (suf || ''));
    t = t.replace(/\b(?:0x[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?|[A-Za-z0-9]{3,8}…[A-Za-z0-9]{3,6}|[A-Za-z0-9]{12}…[A-Za-z0-9]{10}|[1-9A-HJ-NP-Za-km-z]{32,44})\b/g, (a, off, all) =>
      /^\d+(?:[eE][+\-]?\d+)?(?:[A-Za-z][A-Za-z0-9]{0,9})?$/.test(a) || /[₩$]\s*$/.test(all.slice(0, off)) ? a : keep(a));
    t = t.replace(PV_PROT, (a, off, all) => {
      const next = all.slice(off + a.length);
      const money = /(?:[₩$￦]|\b(?:USD[TC]?|KRW))\s*(?:[+\-−]\s*)?(?:[(\[]\s*)?(?:[\d,.]+\s*[\-−~–—]\s*)*[\d,.]*$/.test(all.slice(0, off))
        || /^[\d,.]*(?:[eE][+\-]?\d+)?\s*(?:[)\]]\s*)*(?:억|천|만(?!기|료|약|큼|일|든|족|나|남|점)|원(?!화|금|래|인|칙|본|문|장|숭|두)|달러|[KMB](?![A-Za-z])|(?:USD[TC]?|KRW)\b)/.test(next);
      if (!money) return keep(a);
      return /^[\d,.eE]/.test(next) ? a : pvW(PVM.n);
    });
    t = t.replace(PV_NUM, (a, sg, cur, sp, n, unit, off, all) => {
      const prev = off > 0 ? all.charAt(off - 1) : '', next = all.slice(off + a.length);
      if (!cur && /[A-Za-z0-9_.\uE002\uE000]/.test(prev) && !(sg && /\d/.test(prev)) && !(/[A-Za-z_]/.test(prev) && /^\d{5,}$/.test(n))) return a;
      if (!cur && !unit && PV_KEEP_U.test(next) && (/^\d[\d,]*,?$/.test(n) || PV_KEEP_DEC.test(next))) return a;
      const countP = all.slice(Math.max(0, off - 12), off), nC = n.replace(/,$/, ''), nxC = nC !== n ? ',' + next : next;
      if (!cur && !unit && !sg && /^\d+$/.test(nC) && PV_KEEP_P.test(countP)
          && (/\bnonce\s?$/.test(countP) ? /^\s*(?:$|[·,;:)\]])/.test(nxC) : /^\s?개(?:$|[\s·,;:)\]])/.test(nxC))) return a;
      if (!cur && !unit && /^0$/.test(n)) return a;
      const won = /^\s?원/.test(next);
      return sg + (cur || '') + (sp || '') + pvW(cur === '₩' || won ? (unit ? PVM.krwC : PVM.krw) : cur ? (unit ? PVM.usdC : PVM.usd) : PVM.n);
    });
    return t.replace(/\uE002(\d+)\uE003/g, (a, i) => prot[+i]);
  }
  function eok(w) {
    if (w >= 1e8 || Math.round(w / 1e4) >= 1e4) return nf('ko-KR', 2, 2).format(w / 1e8) + '억';
    if (w >= 1e4 || Math.round(w) >= 1e4) return nf('ko-KR').format(Math.round(w / 1e4)) + '만';
    return nf('ko-KR').format(Math.round(w));
  }
  function m(usd, o) {
    o = o || {};
    if (usd == null || !isFinite(usd)) return '—';
    if (!o.raw) usd = KS(usd);
    const neg = usd < 0;
    const v = Math.abs(usd);
    const zero = S.cur === 'USD' ? v < 0.005 : v * rate() < 0.5;
    const s = o.sign ? (zero ? '' : usd > 0 ? '+' : (neg ? '−' : '')) : (neg && !zero ? '−' : '');
    if (S.hide) return pvMoney(s, o.compact);
    if (S.cur === 'USD') {
      if (o.compact && (v >= 1e6 || +(v / 1e3).toFixed(1) >= 1000)) return s + '$' + rw(trimZeros((v / 1e6).toFixed(2)) + 'M');
      if (o.compact && v >= 1e4) return s + '$' + rw(trimZeros((v / 1e3).toFixed(1)) + 'K');
      const dec = v >= 100 || v === 0 ? 0 : 2;
      return s + '$' + rw(nf('en-US', dec, dec).format(v));
    }
    const w = v * rate();
    return s + '₩' + rw(o.compact ? eok(w) : nf('ko-KR').format(Math.round(w)));
  }
  const mN = (v, o) => '<span class="num">' + m(v, o) + '</span>';
  const CAL_DOT_USD = 7;
  function mcal(usd) {
    usd = KS(usd);
    const s = usd > 0 ? '+' : usd < 0 ? '−' : '', v = Math.abs(usd);
    if (S.hide) return (S.cur === 'USD' ? v < CAL_DOT_USD : v * rate() < 1e4) ? '·' : s + (S.cur === 'USD' ? '$' + pvW(PVM.calU) : pvW(S.mobile ? PVM.calM : PVM.cal));
    if (S.cur === 'USD') return v < CAL_DOT_USD ? '·' : s + '$' + rw(v >= 1e6 || +(v / 1e3).toFixed(1) >= 1000 ? trimZeros((v / 1e6).toFixed(1)) + 'M' : v >= 1e3 || Math.round(v) >= 1000 ? trimZeros((v / 1e3).toFixed(1)) + 'K' : String(Math.round(v)));
    const w = v * rate();
    if (w < 1e4) return '·';
    return s + rw(w >= 1e8 || Math.round(w / 1e4) >= 1e4 ? trimZeros((w / 1e8).toFixed(1)) + '억' : (S.mobile ? String(Math.round(w / 1e4)) : nf('ko-KR').format(Math.round(w / 1e4))) + '만');
  }
  const calTint = usd => Math.abs(KS(usd)) * (S.cur === 'USD' ? 1384 : rate()) >= 1e4;
  const krw = w => (S.hide ? (w < 0 ? '−' : '') + '₩' + pvW(PVM.krw) : '₩' + rw(nf('ko-KR').format(Math.round(KS(w)))));
  const SUBD = '₀₁₂₃₄₅₆₇₈₉';
  function px(n) {
    if (!(n > 0) || !isFinite(n)) return '—';
    if (S.hide) return '$' + pvW(PVM.px);
    if (n >= 1000) return '$' + rw(nf('en-US', 2, 2).format(n));
    if (n >= 1) return '$' + rw(nf('en-US', 2, 4).format(n));
    const z = Math.floor(-Math.log10(n));
    if (z >= 4) {
      let dg = Math.round(n * Math.pow(10, z + 4));
      let zz = z;
      if (dg >= 10000) { dg = Math.round(dg / 10); zz = z - 1; }
      return '$' + rw('0.0' + String(zz).split('').map(c => SUBD[+c]).join('') + trimZeros('0.' + String(dg)).slice(2));
    }
    return '$' + rw(trimZeros(n.toFixed(Math.min(12, z + 4))));
  }
  function pxC(n) {
    if (S.cur === 'USD' || !(n > 0) || !isFinite(n)) return px(n);
    if (S.hide) return '₩' + pvW(PVM.px);
    const x = n * rate();
    if (x >= 1000) return '₩' + rw(nf('ko-KR', 0, 0).format(Math.round(x)));
    if (x >= 100) return '₩' + rw(nf('ko-KR', 0, 1).format(x));
    if (x >= 1) return '₩' + rw(nf('ko-KR', 2, 2).format(x));
    return px(x).replace('$', '₩');
  }
  const plPx = v => (S.cur === 'USD' || !(v > 0) ? px(v) : '≈' + pxC(v));
  const plCY = () => (window.TJWow && window.TJWow.ccy) || null;
  function plSnap(k) {
    const M = S.planSnap || (S.planSnap = {});
    if (!M[k]) { const live = !!(S.D && S.D.rateLive); M[k] = { rt: rate(), live, cu: live && S.cur !== 'USD' ? 'KRW' : 'USD' }; }
    return M[k];
  }
  const plCur = k => (plCY() ? plSnap(k).cu : 'USD');
  function plQ(k) {
    const CY = plCY(); if (!CY || pvOn()) return '';
    const sn = plSnap(k), cu = sn.cu, rt = sn.rt;
    return [['목표', 't:'], ['손절', 's:']].map(([n, p]) => { const e = CY.eq(S.drafts[p + k], cu, rt); return e ? n + ' ' + e : ''; }).filter(Boolean).join(' · ');
  }
  function moneyTxt(t) {
    t = String(t == null ? '' : t);
    if (pvOn() && typeof ownScrubM === 'function') t = ownScrubM(t);
    if (S.rand) return pvNetM(S.cur === 'USD' ? t : t.replace(/([+\-−]?)\$(?=\d)/g, '$1₩'));
    if (S.cur === 'USD') return t;
    return t.replace(/([+\-−]?)\$([\d,]+(?:\.\d+)?(?:[eE][+\-]?\d+)?)(?![\d])/g, (a, sg, v) => {
      const n = parseFloat(v.replace(/,/g, '')); if (!isFinite(n)) return a;
      if (n > 0 && n * rate() < 100) return (sg === '-' || sg === '−' ? '−' : sg) + pxC(n);
      return m((sg === '-' || sg === '−' ? -1 : 1) * n, { sign: !!sg }); });
  }
  function q(n, raw) {
    if (n == null || !isFinite(n)) return '—';
    if (S.hide) return (n < 0 ? '−' : '') + pvW(PVM.q);
    if (!raw) n = KS(n);
    const a = Math.abs(n);
    let d = 0;
    if (a === 0 || a >= 1000) d = 0; else if (a >= 1) d = 4; else d = Math.min(8, Math.max(2, 3 - Math.floor(Math.log10(a))));
    const t = nf('ko-KR', null, d).format(a);
    return (n < 0 && /[1-9]/.test(t) ? '−' : '') + rw(t);
  }
  const pctS = (v, d) => { if (v == null || !isFinite(v)) return '—'; const t = Math.abs(v).toFixed(d == null ? 1 : d); return (+t === 0 ? '' : v > 0 ? '+' : v < 0 ? '−' : '') + t + '%'; };
  const kimpCol = k => (k == null || !isFinite(k)) ? 'var(--muted)' : 'var(--text2)';
  const kimpChip = k => (k == null || !isFinite(k)) ? '' : k > 2 ? '<span class="kchip hi" title="김프 2% 초과">높음</span>' : k < 0.8 ? '<span class="kchip" title="김프 0.8% 미만">낮음</span>' : '';
  function fxNote(D) {
    if (!D || D.rateSrc === 'live') return '';
    const fb = D.rateSrc === 'fallback';
    const t = fb ? '업비트 USDT 원화 시세를 아직 못 받아 고정 대체값으로 원화를 환산 중이에요 — 원화 숫자가 실제와 다를 수 있어요'
      : '업비트 USDT 원화 시세를 ' + (D.rateAt ? fmtTs(D.rateAt) + ' 뒤로 ' : '한동안 ') + '못 받아 마지막 값으로 환산 중이에요 — 다시 받으면 저절로 풀려요';
    return ' <span class="wtxt" title="' + esc(t) + '">· ' + (fb ? '환율 대체값' : '환율 오래됨') + '</span>';
  }
  const cls = v => (v > 0 ? 'up' : v < 0 ? 'down' : 'mut');
  const clsP = (v, d) => (v == null || !isFinite(v) || +Math.abs(v).toFixed(d == null ? 1 : d) === 0 ? 'mut' : cls(v));
  const clsV = v => cls(v == null || !isFinite(v) || isZ(v) ? 0 : v);
  const parseMoney = s => { const n = parseFloat(String(s || '').replace(/[^0-9.\-]/g, '')); return isFinite(n) ? n : 0; };
  function jo(w, a, b) {
    const t = String(w == null ? '' : w).replace(/<[^>]*>/g, '').replace(/[\s)\]'"’”…»]+$/, ''), ch = t.charAt(t.length - 1), c = ch.charCodeAt(0);
    let k = 'v';
    if (c >= 0xAC00 && c <= 0xD7A3) { const j = (c - 0xAC00) % 28; k = !j ? 'v' : j === 8 ? 'l' : 'c'; }
    else if (/\d/.test(ch)) k = 'c l v c v v c l l v'.split(' ')[+ch];
    else if (/[lr]/i.test(ch)) k = 'l'; else if (/[mn]/i.test(ch)) k = 'c';
    return a === '으로' ? (k === 'c' ? '으로' : '로') : (k === 'v' ? b : a);
  }
  const term = s => String(s == null ? '' : s).replace(/원가\s?미상/g, '원가 미확인').replace(/평균가 폴백|폴백/g, '평균가 대체').replace(/평균가 대체(을|이|은|과)(?![가-힣])/g, (a, j) => '평균가 대체' + ({ 을: '를', 이: '가', 은: '는', 과: '와' })[j]).replace(/스팟/g, '현물').replace(/잔고 대사/g, '잔고 대조');
  function hs(s, money, plain) {
    let t = term(s);
    if (!plain && pvOn() && typeof ownScrubM === 'function') t = ownScrubM(t);
    t = t.replace(/\(POST [^)]*\)/g, '').replace(/\(\/api\/[^)]*\)/g, '').replace(/\/api\/[\w_/]+/g, '').replace(/config\.json[^.·]*[.·]?\s*/g, '')
      .replace(/\s*·?\s*검토 후 \/confirm 처리 예정/g, '').replace(/★/g, '').replace(/\s{2,}/g, ' ');
    if (money && !plain && !(S.rand && !(money === 2 && /^[+\-−]?\$[\d,]+(?:\.\d+)?$/.test(t.trim())))) {
      t = t.replace(/([+\-−]?)\$([\d,]+(?:\.\d+)?(?:[eE][+\-]?\d+)?)(?![\d])/g, (a, sg, v) => { const n = parseFloat(v.replace(/,/g, '')); return (n >= 1 || money === 2) ? m((sg === '-' || sg === '−' ? -1 : 1) * n, { sign: !!sg }) : a; })
        .replace(/([+\-]?)([\d,]+(?:\.\d+)?)\$/g, (a, sg, v) => m((sg === '-' ? -1 : 1) * parseFloat(v.replace(/,/g, '')), { sign: !!sg }));
    }
    t = t.replace(/(\d{1,3}(?:,\d{3})+|\d+)\.(\d+)/g, (a, i, d) => { const iv = +i.replace(/,/g, ''); if (iv >= 1000) { const r = Math.round(parseFloat(iv + '.' + d)); return i.indexOf(',') >= 0 ? nf('ko-KR', 0, 0).format(r) : String(r); } const td = d.replace(/0+$/, ''); return td ? i + '.' + td : i; });
    if (plain) return t.trim();
    if (S.hide) t = t.split(PV_RE).map((x, i) => i % 2 ? pvW(x) : pvNet(x)).join('');
    else if (S.rand) t = pvNetM(t);
    return t.trim();
  }
  const hq = s => { const t = String(s == null ? '' : s).trim();
    if (S.hide && /\d/.test(t)) return (/^[-−]/.test(t) ? '−' : '') + pvW(PVM.q);
    if (S.rand && /\d/.test(t)) { const mr = t.match(/^([-−]?)(\d[\d,]*(?:\.\d+)?)$/); if (mr) { const n9 = parseFloat(mr[2].replace(/,/g, '')); return q(mr[1] ? -n9 : n9); } return hs(s); }
    if (/^\d{4,}(\.\d+)?$/.test(t)) return q(parseFloat(t));
    const mm = t.match(/^([-−])([\d,]+(?:\.\d+)?)$/); if (mm) { const r = hs(mm[2]); return (/[1-9]/.test(r) ? '−' : '') + r; }
    return hs(s); };
  const nbDot = t => String(t).replace(/ · /g, ' ·\u00a0');
  const AUSD = /^\$[\d,]+(?:\.\d+)?$/;
  const evXf = e => !!(S.rand && e && /^(?:전송|외부 전송|입금 확인)$/.test(String(e.k || '')));
  const qXf = v => (S.rand ? pvW(PVM.q) : q(v));
  const evQ = e => (evXf(e) && /\d/.test(String(e.q == null ? '' : e.q)) ? (/^\s*[-−]/.test(String(e.q)) ? '−' : '') + pvW(PVM.q) : hq(e && e.q));
  const evDH = e => { const x = window.TJSale && e && (e.of || e.ofc) ? window.TJSale.rowHTML(e) : null; return x != null ? x : esc(hs(e.d)); };
  const evDT = e => { const x = window.TJSale && e && e.of ? window.TJSale.rowText(e) : null; return x != null ? x : hs(e.d); };
  function evA(e) {
    const a = String((e && e.a) == null ? '' : e.a).trim();
    if (evXf(e) && /\d/.test(a)) return esc(pvMoney(/^[-−]/.test(a) ? '−' : '', false));
    if (S.cur !== 'USD' && AUSD.test(a)) {
      if (e.aK != null && isFinite(e.aK)) return esc(krw(num(e.aK)));
      if (!S.hide) return '<span class="aprx" title="체결 시각 원화가 없어 오늘 환율로 환산했어요">≈ </span>' + esc(hs(a, 2));
    }
    return esc(hs(e && e.a, 2));
  }
  const evAK = list => { let s0 = 0; for (const e of list) { if (!AUSD.test(String(e.a || '').trim())) continue; if (e.aK == null || !isFinite(e.aK)) return null; s0 += num(e.aK); } return s0; };
  const URL_NM = /(https?:\/\/|www\.|t\.me\/)|[a-z0-9-]{2,}\.(com|net|org|io|xyz|top|mom|sbs|bond|website|site|online|app|finance|club|pro|info|vip|cc|gg|link|live|cash|claim|to|us|ai|world|fun|space|pw|shop|win|biz|tech|store|lol|icu|cfd|click|one|dev|network|me|co|fi|gift|today|events|foundation|lat|buzz|rest|cyou|homes|autos|beauty|hair|skin|quest|guru|zone|digital|global|ink|run|ltd|best|asia|cloud|social|games)(?![a-z0-9])/i;
  const spamNm = s => URL_NM.test(String(s == null ? '' : s)) ? '스팸 토큰(URL형 이름)' : s;
  const evNm = e => { const sy = String(e && e.sym || ''); if (e && !e.lp && String(e.src || '') === 'ex:binance' && /^LD[A-Z0-9]{2,}$/.test(sy)) return sy.slice(2) + ' (Earn)'; return spamNm(lpNm(e.sym, e.lp)); };
  const lpNm = (sym, key) => { const mp = S.D && S.D.lpName; if (!mp) return sym; return (key && mp.get(String(key))) || mp.get(String(sym)) || sym; };
  const lpNmHTML = (nm, lp) => { const t = String(nm == null ? '' : nm), mm = lp ? t.match(/^(.*\S)\s+(#\d+)$/) : null;
    return mm ? '<span class="ell lpn" title="' + esc(t) + '"><span class="nm">' + esc(mm[1]) + '</span> <span class="id">' + esc(mm[2]) + '</span></span>' : '<span class="ell">' + esc(t) + '</span>'; };
  const taxNmHTML = nm => { const t = String(nm == null ? '' : nm), mm = t.match(/^(.*\S)\s+(#\d+)$/);
    if (!mm) return '<b class="tnm" title="' + esc(t) + '">' + esc(t) + '</b>';
    return '<b class="tnm lpn" title="' + esc(t) + '"><span class="nm">' + esc(S.mobile ? mm[1].replace(/\s*\/\s*/g, '/') : mm[1]) + '</span> <span class="id">' + esc(mm[2]) + '</span></b>'; };
  const AI_HIDE = 'AI 설명 — 가림 모드에서는 숨겨요';
  const revTxt = (s, plain) => { let t = term(s).replace(/★/g, '').replace(/\s{2,}/g, ' ').trim();
    if (pvOn() && !plain) return AI_HIDE;
    return t; };
  const evTxt = s => {
    let t = revTxt(String(s == null ? '' : s).normalize('NFKC'));
    if (!pvOn()) return t;
    t = t.replace(/([₩$])(\s*)[영공일이삼사오육칠팔구십백천만억조점]+/g, (a, c, sp) => c + sp + pvW(PVM.n));
    const kn = '(?:[일이삼사오육칠팔구십백천만억조몇수여]+|(?:스물|스무|서른|마흔|쉰|예순|일흔|여든|아흔|열)(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉)?|하나|한|둘|두|셋|세|넷|네|다섯|여섯|일곱|여덟|아홉)';
    t = t.replace(new RegExp('(?:약\\s*)?' + kn + '(?:[\\s~∼〜–—−-]+' + kn + ')*\\s*(?=원|달러|불)', 'g'), () => pvW(PVM.n));
    return t.split(/(\uE000[^\uE001]*\uE001)/).map((seg, i) => i % 2 ? seg : seg.replace(/\d+(?::\d{2})+|\d[\d,.]*(?:\s?(?:%|‰|bp|분|시간|건|개월))?/g,
      a => /:\d{2}$/.test(a) || /(?:%|‰|bp)$/.test(a) || /^\d[\d,]*\s?(?:분|건|개월)$/.test(a) || /^\d[\d,.]*\s?시간$/.test(a) ? a : pvW(PVM.n))).join('');
  };
  const chainOf = name => { const s = String(name || ''); const i = s.indexOf(' · '); const c = i >= 0 ? s.slice(i + 3) : ''; return c === '?' ? '' : c; };

  const SPOT_SYMS = new Set('$pac 0xbtc 1inch 2give aave abt act actn ada add adx ae aeon aeur agi agrs aion algo amb amp ampl ankr ant ape apex appc ardr arg ark arn arnx ary ast atlas atm atom audr aury auto avax aywa bab bal band bat bay bcbc bcc bcd bch bcio bcn bco bcpt bdl beam bela bix blcn blk block blz bnb bnt bnty booty bos bpt bq brd bsd bsv btc btcd btch btcp btcz btdx btg btm bts btt btx burst bze call cc cdn cdt cenz chain chat chips chsb chz cix clam cloak cmm cmt cnd cnx cny cob colx comp coqui cred crpt crv crw cs ctr ctxc cvc d dai dash dat data dbc dcn dcr deez dent dew dgb dgd dlt dnt dock doge dot drgn drop dta dth dtr ebst eca edg edo edoge ela elec elf elix ella emb emc emc2 eng enj entrp eon eop eos eqli equa etc eth ethos etn etp eur evx exmo exp fair fct fida fil fjc fldc flo flux fsn ftc fuel fun game gas gbp gbx gbyte generic gin glxt gmr gmt gno gnt gold grc grin grs grt gsc gto gup gusd gvt gxs gzr hight hns hodl hot hpb hsr ht html huc husd hush icn icp icx ignis ilk ink ins ion iop iost iotx iq itc jnt jpy kcs kin klown kmd knc krb ksm lbc lend leo link lkk loom lpt lrc lsk ltc lun maid mana matic max mcap mco mda mds med meetone mft miota mith mkr mln mnx mnz moac mod mona msr mth mtl music mzc nano nas nav ncash ndz nebl neo neos neu nexo ngc nio nkn nlc2 nlg nmc nmr npxs ntbc nuls nxs nxt oax ok omg omni one ong ont oot ost ox oxt oxy part pasc pasl pax paxg pay payx pink pirl pivx plr poa poe polis poly pot powr ppc ppp ppt pre prl pungo pura qash qiwi qlc qnt qrl qsp qtum r rads rap ray rcn rdd rdn ren rep repv2 req rhoc ric rise rlc rpx rub rvn ryo safe safemoon sai salt san sand sbd sberbank sc ser shift sib sin skl sky slr sls smart sngls snm snt snx soc sol spacehbit spank sphtx srn stak start steem storj storm stox stq strat stx sub sumo sushi sys taas tau tbx tel ten tern tgch theta tix tkn tks tnb tnc tnt tomo tpay trig trtl trx tusd tzc ubq uma uni unity usd usdc usdt utk veri vet via vib vibe vivo vrc vrsc vtc vtho wabi wan waves wax wbtc wgr wicc wings wpr wtc x xas xbc xbp xby xcp xdn xem xin xlm xmcc xmg xmo xmr xmy xp xpa xpm xpr xrp xsg xtz xuc xvc xvg xzc yfi yoyow zcl zec zel zen zest zil zilla zrx'.split(' '));
  const TW = { eth: 'ethereum', base: 'base', arbitrum: 'arbitrum', optimism: 'optimism', polygon: 'polygon', bsc: 'smartchain', sol: 'solana', scroll: 'scroll', zksync: 'zksync', gnosis: 'xdai', avalanche: 'avalanchec', kaia: 'klaytn' };
  const CHAIN_KEY = { Ethereum: 'eth', Base: 'base', Arbitrum: 'arbitrum', Optimism: 'optimism', Polygon: 'polygon', BSC: 'bsc', Solana: 'sol', Scroll: 'scroll', zkSync: 'zksync', Gnosis: 'gnosis', Monad: 'monad', MegaETH: 'megaeth', Plasma: 'plasma', 'X Layer': 'xlayer', Kaia: 'kaia', Fraxtal: 'fraxtal', BOB: 'bob', Story: 'story', Somnia: 'somnia', Avalanche: 'avalanche' };
  const CHAIN_SPOT = { eth: 'eth', sol: 'sol', bsc: 'bnb', polygon: 'matic' };
  const CDN = 'https://cdn.jsdelivr.net/gh/';
  const spotUrl = s => CDN + 'spothq/cryptocurrency-icons@master/svg/color/' + s + '.svg';
  const LOGO = {
    fail: (() => { try { const o = JSON.parse(LS.get('tj_logo_fail') || '{}'); const t = Date.now(); Object.keys(o).forEach(k => { if (t - o[k] > 7 * 864e5) delete o[k]; }); return o; } catch (e) { return {}; } })(),
    lists: {}, loading: {},
    bad(u) { return !!this.fail[u]; },
    mark(u) { this.fail[u] = Date.now(); LS.set('tj_logo_fail', JSON.stringify(this.fail)); }
  };
  function symColor(sym) {
    let h = 0; const s = String(sym || '?');
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
    return 'hsl(' + (h % 360) + ' 45% 38%)';
  }
  const letter = sym => (String(sym || '?').replace(/^[^A-Za-z0-9가-힣]+/, '') || '?').slice(0, 1).toUpperCase();
  function icon(sym, sm, o) {
    o = o || {};
    const size = typeof sm === 'string' ? sm : (sm ? 'sm' : '');
    const cb = o.chain ? chainBadge(o.chain) : '';
    const lg = String(sym || '').replace(/[^A-Za-z0-9]/g, '').toLowerCase();
    const data = (o.ck && o.ca ? o.ck + ':' + o.ca : '') + '|' + (o.noSym ? '' : lg);
    return '<span class="ic' + (size ? ' ' + size : '') + '" style="background:' + symColor(sym) + '" aria-hidden="true">' + esc(letter(sym))
      + '<img class="lg" alt="" data-lg="' + esc(data) + '" decoding="async" loading="lazy">' + cb + '</span>';
  }
  function chainBadge(ch) {
    const k = CHAIN_KEY[ch] || ch;
    if (!TW[k]) return '';
    return '<span class="cb" title="' + esc(ch) + '"><img alt="" data-cbk="' + esc(k) + '" decoding="async" loading="lazy"></span>';
  }
  function exLogo(key, title) {
    const b = EX_BRAND[key];
    if (!b) return '<span class="exl w" aria-hidden="true">' + IC.wallet + '</span>';
    return '<span class="exl" style="background:' + b[0] + (b[2] ? ';color:' + b[2] : '') + '" title="' + esc(title || EX_NAMES[key] || key) + '" aria-hidden="true">' + b[1] + '</span>';
  }
  const venueLogo = name => { const n = String(name || ''); const k = EX_BY_KO[n] || EX_BY_KO[n.replace(/ .*$/, '')]; return k ? exLogo(k) : '<span class="exl w" aria-hidden="true">' + IC.wallet + '</span>'; };
  function twList(ck) {
    if (LOGO.lists[ck] || LOGO.loading[ck]) return LOGO.lists[ck] || null;
    LOGO.loading[ck] = fetch(CDN + 'trustwallet/assets@master/blockchains/' + TW[ck] + '/tokenlist.json').then(r => r.ok ? r.json() : null).then(d => {
      const m9 = new Map();
      arr(d && d.tokens).forEach(t => { if (t && t.address) m9.set(String(t.address).toLowerCase(), t.address); });
      LOGO.lists[ck] = m9; hydrateLogos();
    }).catch(() => { LOGO.lists[ck] = new Map(); });
    return null;
  }
  function logoCands(img) {
    const [ca, sym] = String(img.getAttribute('data-lg') || '').split('|');
    const out = [];
    if (ca) {
      const i = ca.indexOf(':'), ck = ca.slice(0, i), addr = ca.slice(i + 1);
      if (TW[ck]) {
        const l = twList(ck);
        if (l === null) return null;
        const cs = l.get(addr.toLowerCase());
        if (cs) out.push(CDN + 'trustwallet/assets@master/blockchains/' + TW[ck] + '/assets/' + cs + '/logo.png');
      }
    }
    if (sym && SPOT_SYMS.has(sym)) out.push(spotUrl(sym));
    return out.filter(u => !LOGO.bad(u));
  }
  let hydT = 0;
  const logosOff = () => LS.get('tj_v2_nologo') === '1';
  function hydrateLogos() {
    if (logosOff()) return;
    cancelAnimationFrame(hydT);
    hydT = requestAnimationFrame(() => {
      document.querySelectorAll('img.lg:not([src]):not([data-none])').forEach(img => {
        const c = logoCands(img);
        if (c === null) return;
        if (!c.length) { img.setAttribute('data-none', '1'); return; }
        img.src = c[0];
      });
      document.querySelectorAll('.cb img:not([src])').forEach(img => {
        const k = img.getAttribute('data-cbk');
        const u = CHAIN_SPOT[k] ? spotUrl(CHAIN_SPOT[k]) : CDN + 'trustwallet/assets@master/blockchains/' + TW[k] + '/info/logo.png';
        if (!LOGO.bad(u)) img.src = u;
      });
    });
  }
  document.addEventListener('load', ev => { const t = ev.target; if (t && t.tagName === 'IMG' && t.parentNode && (t.classList.contains('lg') || t.parentNode.classList.contains('cb'))) t.parentNode.classList.add('ld'); }, true);
  document.addEventListener('error', ev => {
    const t = ev.target;
    if (!t || t.tagName !== 'IMG' || !t.src) return;
    LOGO.mark(t.src);
    if (t.classList.contains('lg')) { const c = logoCands(t) || []; if (c.length) t.src = c[0]; else t.remove(); }
    else if (t.parentNode && t.parentNode.classList.contains('cb')) t.remove();
  }, true);

  function mvDest(p) {
    const mt = arr(p.movedTo).filter(x => Array.isArray(x) && num(x[1]) > 0);
    if (!mt.length || mt.some(x => x[2] === false) || num(p.held) > 0 || num(p.soldQty) > 0 || num(p.unvQty) > 0) return '';
    const mq = num(p.movedQty), own = mt.filter(x => x[2] !== false);
    if (!(mq > 0) || mq < num(p.bought) * 0.98 || !own.length || sum(own, x => num(x[1])) < mq * 0.98) return '';
    return String(own[0][0]) + (own.length > 1 ? ' 외 ' + (own.length - 1) + '곳' : '');
  }
  const evLen = p => p.events ? arr(p.events).length : num(p._evc);
  const evTimes = p => p.events ? arr(p.events).map(e => e.t) : arr(p._evt);
  const LASTISO = new WeakMap();
  function lastIsoOf(p) {
    const a = p.events ? p.events : p._evt, day = ymNow().day;
    const c = a && typeof a === 'object' ? LASTISO.get(a) : null;
    if (c && c.day === day) return c.v;
    let v = ''; evTimes(p).forEach(t => { const i = isoOf(t); if (i > v) v = i; });
    if (a && typeof a === 'object') LASTISO.set(a, { day, v });
    return v;
  }
  const LEGEV = new WeakMap();
  function legEvents(legs) {
    const arrs = legs.map(p => p.events), k0 = arrs[0];
    if (k0 && typeof k0 === 'object') { const c = LEGEV.get(k0); if (c && c.arrs.length === arrs.length && c.arrs.every((a, i) => a === arrs[i])) return c.out; }
    const out = legEventsRaw(legs);
    if (k0 && typeof k0 === 'object') LEGEV.set(k0, { arrs, out });
    return out;
  }
  function legEventsRaw(legs) {
    const events = [];
    legs.forEach(p => arr(p.events).forEach(e => events.push(e)));
    events.sort((a, b) => String(a.t || '') < String(b.t || '') ? -1 : (String(a.t || '') > String(b.t || '') ? 1 : 0));
    return events;
  }
  function symMerge(positions, keyOf) {
    const by = new Map();
    positions.forEach(p => { const k = p.kind === 'quarantined' ? '!q:' + String(p.key || '') : p.symSrc ? '#' + String(p.key || '').replace(/f\d+$/, '') : ((keyOf && keyOf(p)) || String(p.sym || '').toUpperCase()); if (!by.has(k)) by.set(k, []); by.get(k).push(p); });
    const out = [];
    const eff = p => {
      const b = num(p.bought);
      const eb = Math.max(0, b - num(p.movedQty));
      const ec = eb > 0 ? Math.max(0, num(p.cost) - num(p.movedCost)) : 0;
      return { bought: eb, cost: ec, moved: b > 0 && eb <= b * 0.02 };
    };
    by.forEach(legs => {
      if (legs.length === 1 || legs.some(l => l.movedQty == null)) { legs.forEach(l => out.push(Object.assign({}, l, { _legs: [l.key] }))); return; }
      const main = legs.slice().sort((a, b) => (evLen(b) - evLen(a)) || (num(b.cost) - num(a.cost)))[0];
      const effs = new Map(legs.map(l => [l, eff(l)]));
      const live = legs.filter(l => !effs.get(l).moved);
      let held = 0, bought = 0, cost = 0, realized = 0, unreal = 0, fee = 0, ots = Infinity, opened = main.opened;
      let soldQty = 0, soldProceeds = 0, realizedFb = 0, unknownQty = 0, unvQty = 0, unvProceeds = 0, fbCost = 0, paidQty = 0, paidUsd = 0, payReal = 0;
      const chains = [];
      const rbd = {}, act = {}, ubd = {}, rbk = {}, sa = {}, pbd = {};
      let hasK = true, hasSA = true, evN = 0;
      legs.forEach(p => {
        if (p.srcAct) Object.keys(p.srcAct).forEach(sk => { const t = sa[sk] || (sa[sk] = {}), mp = p.srcAct[sk] || {}; Object.keys(mp).forEach(k => { const a = t[k] || (t[k] = [0, 0, 0, 0]), b = arr(mp[k]); for (let i = 0; i < 4; i++) a[i] += num(b[i]); }); }); else hasSA = false;
        evN += p.evN != null ? num(p.evN) : evLen(p);
        Object.keys(p.realizedByDay || {}).forEach(k => { rbd[k] = num(rbd[k]) + num(p.realizedByDay[k]); });
        if (p.realizedKrwByDay) Object.keys(p.realizedKrwByDay).forEach(k => { rbk[k] = num(rbk[k]) + num(p.realizedKrwByDay[k]); }); else hasK = false;
        Object.keys(p.actByDay || {}).forEach(k => { const a = act[k] || (act[k] = [0, 0]), b = arr(p.actByDay[k]); a[0] += num(b[0]); a[1] += num(b[1]); });
        Object.keys(p.unvByDay || {}).forEach(k => { const a = ubd[k] || (ubd[k] = [0, 0]), b = arr(p.unvByDay[k]); a[0] += num(b[0]); a[1] += num(b[1]); });
        Object.keys(p.payByDay || {}).forEach(k => { pbd[k] = num(pbd[k]) + num(p.payByDay[k]); });
        paidQty += num(p.paidQty); paidUsd += num(p.paidUsd); payReal += num(p.payReal);
        held += num(p.held); realized += num(p.realized); unreal += num(p.unreal);
        soldQty += num(p.soldQty); soldProceeds += num(p.soldProceeds); realizedFb += num(p.realizedFb);
        unknownQty += num(p.unknownQty); unvQty += num(p.unvQty); unvProceeds += num(p.unvProceeds); fbCost += num(p.fbCost);
        bought += effs.get(p).bought; cost += effs.get(p).cost;
        fee += parseMoney(p.fee);
        if (p._ots && p._ots < ots) { ots = p._ots; opened = p.opened; }
        const ch = p.chain === '?' ? '거래소' : p.chain;
        if (ch && chains.indexOf(ch) < 0) chains.push(ch);
      });
      const events = legEvents(legs);
      const status = held > 0 ? ((payReal ? Math.abs(realized - payReal) >= 0.005 : realized !== 0) ? '부분 매도' : '보유') : '종료';
      const kb = legs.reduce((s, l) => s + (effs.get(l).cost > 0 ? effs.get(l).bought : 0), 0);
      let mergedAvg = live.length === 1 ? num(live[0].avg) : (kb > 0 ? cost / kb : (bought > 0 ? cost / bought : num(main.avg)));
      const la = legs.filter(l => num(l.avg) > 0 && num(l.bought) > 0);
      if (la.length > 1) {
        const lo = Math.min.apply(null, la.map(l => num(l.avg))), hi = Math.max.apply(null, la.map(l => num(l.avg)));
        if (!(mergedAvg >= lo * 0.8 && mergedAvg <= hi * 1.25))
        mergedAvg = sum(la, l => num(l.avg) * num(l.bought)) / sum(la, l => num(l.bought));
      }
      out.push(Object.assign({}, main, {
        held, bought, cost, realized, unreal, soldQty, soldProceeds, avgSell: soldQty > 0 ? soldProceeds / soldQty : 0, paidQty, paidUsd, payReal, payByDay: pbd,
        lpConvQty: sum(legs, l => num(l.lpConvQty)),
        offcA: legs.some(l => l.offcA) ? { qty: sum(legs, l => num(l.offcA && l.offcA.qty)), realized: sum(legs, l => num(l.offcA && l.offcA.realized)) } : null,
        fsEst: legs.some(l => l.fsEst) ? { cost: sum(legs, l => num(l.fsEst && l.fsEst.cost)), qty: sum(legs, l => num(l.fsEst && l.fsEst.qty)),
          real: sum(legs, l => num(l.fsEst && l.fsEst.real)) } : null,
        realizedFb, unknownQty, unvQty, unvProceeds, fbCost, fbAvg: fbCost > 0 ? mergedAvg : num(main.fbAvg),
        avg: mergedAvg, fee: '$' + fee.toFixed(2), status, opened, _ots: ots === Infinity ? main._ots : ots,
        chain: chains.join(' · '), _nLegs: legs.length,
        realizedByDay: rbd, actByDay: act, unvByDay: ubd, realizedKrwByDay: hasK ? rbk : null,
        srcAct: hasSA ? sa : null, evN,
        movedTo: null, inFrom: null, nBuy: sum(legs, l => num(l.nBuy)),
        events, _legs: legs.map(l => l.key), _legP: legs
      }));
    });
    return out;
  }

  function deriveOF(D, f) {
    D.hasOF = Array.isArray(f.outflows);
    D.of = arr(f.outflows).map(r => { const p = r && r.address && optHas('of') ? optOf('of', String(r.address)) : null; if (!p) return normOF(r); const x = normOF(Object.assign({}, r, p)); if (x) x._opt = true; return x; }).filter(Boolean);
    D.ofPend = D.of.filter(r => (r.status === 'pending' || r.applyWait) && !r.dustPoison);
    D.ofBrU = D.of.filter(r => r.brU);
    D.ofHidden = D.of.filter(r => r.bucket === 'spam' || r.dustPoison);
    D.ofPendN = D.ofPend.length + D.ofBrU.length;
    D.ofPendTxt = D.ofPendN + '곳' + (D.ofBrU.length ? ' (브릿지 미추적 ' + D.ofBrU.length + ' 포함)' : '');
    D.ofPendUsd = sum(D.ofPend, ofNetV);
    D.ofPendTr = D.ofPend.filter(ofTraced).length;
    D.ofRet = D.of.filter(r => r.bucket === 'returned');
    D.ofWait = D.of.filter(r => r.saleWait > 0);
  }
  const POSEV = new WeakMap();
  let EVB = null;
  function buildEvents(D, f) {
    const day = ymNow().day, ps = D.positions, sig = [f.extraEvents, f.extraEventsHidden, f.lpEvents, day];
    ps.forEach(p => { sig.push(p.events, p.sym, p.key); });
    if (EVB && EVB.sig.length === sig.length && EVB.sig.every((x, i) => x === sig[i])) {
      D.events = EVB.events; D.eventsHid = EVB.eventsHid; D.hasSrc = EVB.hasSrc; D.evByDay = EVB.evByDay; return;
    }
    buildEventsRaw(D, f, day);
    EVB = { sig, events: D.events, eventsHid: D.eventsHid, hasSrc: D.hasSrc, evByDay: D.evByDay };
  }
  function buildEventsRaw(D, f, day) {
    const evs = [];
    arr(f.extraEvents).forEach(e => evs.push({ t: e.t, sym: e.sym, k: evKind(e.k, e.d), d: e.d, q: e.q, a: e.a, aK: e.aK, tx: e.tx, src: e.src, imp: e.imp, _ts: e._ts, of: e.of, ofc: e.ofc }));
    D.eventsHid = arr(f.extraEventsHidden).map(e => ({ t: e.t, sym: e.sym, k: evKind(e.k, e.d), d: e.d, q: e.q, a: e.a, aK: e.aK, tx: e.tx, src: e.src, imp: e.imp, hide: e.hide, hideKind: e.hideKind, iso: isoOf(e.t), of: e.of, ofc: e.ofc }));
    arr(f.lpEvents).forEach(e => evs.push({ t: e.t, sym: e.sym, k: e.k, d: e.d, q: e.q, a: e.a, aK: e.aK, tx: e.tx, src: e.src, lp: e.lp, _ts: e._ts }));
    evs.forEach(e => { e.iso = isoOf(e.t); e.day = String(e.t || '').slice(0, 5); });
    D.positions.forEach(p => {
      const ea = p.events;
      let c = ea && typeof ea === 'object' ? POSEV.get(ea) : null;
      if (!c || c.sym !== p.sym || c.key !== p.key || c.day !== day) {
        const list = [];
        arr(ea).forEach(e => {
          if (e.k === '평단 갱신') return;
          const o = { t: e.t, sym: p.sym, k: e.k, d: e.d, q: e.q, a: e.a, aK: e.aK, tx: e.tx, src: e.src, pkey: p.key, of: e.of, ofc: e.ofc };
          o.iso = isoOf(o.t); o.day = String(o.t || '').slice(0, 5);
          list.push(o);
        });
        c = { sym: p.sym, key: p.key, day, list };
        if (ea && typeof ea === 'object') POSEV.set(ea, c);
      }
      for (let i = 0; i < c.list.length; i++) evs.push(c.list[i]);
    });
    evs.sort((a, b) => (a.iso < b.iso ? 1 : a.iso > b.iso ? -1 : 0));
    D.events = evs;
    D.hasSrc = evs.some(e => !!e.src);
    D.evByDay = new Map();
    evs.forEach(e => { if (e._ts && new Date((num(e._ts) + 32400) * 1000).toISOString().slice(0, 10) !== String(e.iso).slice(0, 10)) return;
      if (!D.evByDay.has(e.day)) D.evByDay.set(e.day, []); D.evByDay.get(e.day).push(e); });
  }
  const CHAIN_KO = { eth: 'Ethereum', base: 'Base', arb: 'Arbitrum', arbitrum: 'Arbitrum', op: 'Optimism', optimism: 'Optimism', bsc: 'BSC', polygon: 'Polygon', sol: 'Solana', solana: 'Solana', tron: 'Tron', sui: 'Sui', ton: 'TON', btc: 'Bitcoin', zksync: 'zkSync', scroll: 'Scroll', gnosis: 'Gnosis', robinhood: 'Robinhood', arc: 'Arc', avax: 'Avalanche', linea: 'Linea', blast: 'Blast', mantle: 'Mantle', unichain: 'Unichain', bera: 'Berachain', monad: 'Monad', megaeth: 'MegaETH', plasma: 'Plasma', xlayer: 'X Layer', kaia: 'Kaia', fraxtal: 'Fraxtal', bob: 'BOB', story: 'Story', somnia: 'Somnia', avalanche: 'Avalanche', stable: 'Stable', abstract: 'Abstract', berachain: 'Berachain', hyperevm: 'HyperEVM', sonic: 'Sonic' };
  function normLP(l) {
    if (!l || typeof l !== 'object') return null;
    const oc = (l.onchain && typeof l.onchain === 'object') ? l.onchain : {};
    const s0 = oc.sym0, s1 = oc.sym1;
    const unitSyms = (() => { const o = []; [l.principalUnits, l.returned, l.converted, l.acquired, l.residualUnits].forEach(mp => Object.keys(mp && typeof mp === 'object' ? mp : {}).forEach(k => { if (o.indexOf(k) < 0) o.push(k); }));
      arr(l.pair).forEach(k => { if (k && o.indexOf(String(k)) < 0) o.push(String(k)); });
      const st = x => /^(USDT|USDC|DAI|USDE|USDS|FDUSD|PYUSD|USD1|USDG|TUSD|EURC)$/i.test(x); return o.filter(x => !st(x)).concat(o.filter(st)).slice(0, 3); })();
    const pool = l.pool || (s0 && s1 ? s0 + ' / ' + s1 : (unitSyms.length >= 2 ? unitSyms.join(' / ') : (l.dex || 'LP') + (l.id ? ' #' + l.id : '')));
    const closed = !!l.closed;
    const inR = oc.inRange != null ? !!oc.inRange : (l.status === '범위 내' ? true : l.status === '범위 이탈' ? false : null);
    const state = closed ? 'closed' : inR === true ? 'in' : inR === false ? 'out' : 'unknown';
    const amounts = (s0 || s1) && (oc.amount0 != null || oc.amount1 != null)
      ? [{ sym: s0 || '?', amt: num(oc.amount0) }, { sym: s1 || '?', amt: num(oc.amount1) }]
      : arr(l.comp).map(c => ({ sym: c.sym, amt: /\d/.test(String(c.now == null ? '' : c.now)) ? parseMoney(c.now) : null, lt: /^</.test(String(c.now || '')), then: c.then }));
    const feeAmts = (oc.fees0 != null || oc.fees1 != null) ? [{ sym: s0 || '?', amt: num(oc.fees0) }, { sym: s1 || '?', amt: num(oc.fees1) }].filter(a => a.amt > 0) : [];
    const value = l.value == null ? null : num(l.value);
    const fees = l.fees == null ? null : num(l.fees);
    const dep0 = l.deposit != null ? num(l.deposit) : (l.deposited != null ? num(l.deposited) : null);
    const principal = l.noLedger ? null : (l.principal != null ? num(l.principal) : dep0);
    const pnl = value != null && principal != null && principal > 0 ? value + num(fees) + num(l.rewards) - principal : null;
    const feeTier = l.tier || (oc.fee != null ? trimZeros((num(oc.fee) / 10000).toFixed(3)) + '%' : (oc.tickSpacing ? 'tick ' + oc.tickSpacing : ''));
    const syms = String(pool).split('/').map(x => x.trim()).filter(Boolean);
    return { key: String(l.key || l.id || pool), id: l.idShort || l.id, pool, syms, protocol: l.dex || l.proto || '', chain: l.chain || CHAIN_KO[l.chainKey] || l.chainKey || '',
      staked: l.staked || '', limit: /^지정가/.test(String(l.pendingReason || '')), proto: l.proto || '',
      fee: feeTier, state, stateLabel: closed ? '종료' : inR === true ? '범위 내' : inR === false ? '범위 이탈' : '확인 중',
      lo: num(oc.priceLower), hi: num(oc.priceUpper), price: num(oc.price), quote: s1 && s0 ? s1 + '/' + s0 : '', rangeText: l.range || '',
      amounts, feeAmts, value, fees, rewards: num(l.rewards), deposit: dep0, principal, income: num(l.income),
      realizedK: l.realizedKrwByDay && typeof l.realizedKrwByDay === 'object' ? sum(Object.keys(l.realizedKrwByDay), k => num(l.realizedKrwByDay[k])) : null,
      idLabel: (String(l.dex || '').replace(/^Uniswap\s+/i, '') || 'LP') + (l.id ? ' #' + l.id : ''),
      pnl, pnlPct: pnl != null && principal > 0 ? pnl / principal * 100 : null,
      realized: closed && l.realizedByDay && typeof l.realizedByDay === 'object' ? sum(Object.keys(l.realizedByDay), k => num(l.realizedByDay[k])) : num(l.realized),
      il: l.il != null ? num(l.il) : null, apr: l.apr || '', opened: l.opened, last: l.last, noLedger: !!l.noLedger, raw: l };
  }
  function normFlow(f) {
    if (!f || typeof f !== 'object') return null;
    const o = x => (x && typeof x === 'object' ? x : {});
    const coin = c => ({ sym: String(o(c).sym || '?'), qty: num(o(c).qty), usd: o(c).usd == null ? null : num(o(c).usd) });
    const sc = x => ({ level: ['high', 'mid'].indexOf(o(x).level) >= 0 ? o(x).level : 'none', n: num(o(x).n), ev: arr(o(x).ev).map(e => ({ k: String(o(e).k || ''), t: String(o(e).t || '') })) });
    return { status: String(f.status || 'queued'), scannedAt: num(f.scannedAt), sent: num(f.sent), capped: !!f.capped, held: !!(f.held != null ? f.held : f.capped),
      scanSince: num(f.scanSince), lastTry: num(f.lastTry), scanWhy: String(f.scanWhy || ''),
      returned: { usd: num(o(f.returned).usd), direct: num(o(f.returned).direct), exchange: num(o(f.returned).exchange), hop: num(o(f.returned).hop), bridge: num(o(f.returned).bridge) },
      still: { usd: num(o(f.still).usd), all: o(f.still).all == null ? num(o(f.still).usd) : num(o(f.still).all), items: arr(o(f.still).items).map(x => Object.assign(coin(x), { chain: String(o(x).chain || ''), approx: !!o(x).approx })) },
      elsewhere: { usd: num(o(f.elsewhere).usd), all: o(f.elsewhere).all == null ? num(o(f.elsewhere).usd) : num(o(f.elsewhere).all), n: num(o(f.elsewhere).n), lookMine: num(o(f.elsewhere).lookMine) },
      unexplained: num(f.unexplained), net: f.held == null && f.capped ? num(f.sent) - num(o(f.returned).usd) : num(f.net), mixedIn: { usd: num(o(f.mixedIn).usd), n: num(o(f.mixedIn).n) },
      swaps: { n: num(o(f.swaps).n), sold: arr(o(f.swaps).sold).map(coin), bought: arr(o(f.swaps).bought).map(coin) },
      notes: arr(f.notes).map(String), score: sc(f.score), mineN: num(f.mineN),
      spoofHidden: { n: num(o(f.spoofHidden).n), items: arr(o(f.spoofHidden).items).map(t => ({ ts: num(o(t).ts), tx: String(o(t).tx || ''), chain: String(o(t).chain || ''), sym: String(o(t).sym || '?'), qty: num(o(t).qty), dir: o(t).dir === 'in' ? 'in' : 'out', cp: String(o(t).cp || '') })) },
      recips: arr(f.recips).filter(x => x && x.addr).map(x => ({ addr: String(x.addr), kind: String(x.kind || 'eoa'), base: String(x.base || x.kind || 'eoa'), label: String(x.label || ''),
        chains: arr(x.chains).map(String), usd: num(x.usd), n: num(x.n), first: num(x.first), last: num(x.last), approx: !!x.approx,
        coins: arr(x.coins).map(coin), via: num(x.via), viaN: num(x.viaN), score: sc(x.score), registerable: !!x.registerable,
        bridge: x.bridge && typeof x.bridge === 'object' ? { name: String(x.bridge.name || ''), src: String(x.bridge.src || ''), dst: String(x.bridge.dst || ''), via: String(x.bridge.via || '') } : null,
        txs: arr(x.txs).map(t => ({ ts: num(o(t).ts), tx: String(o(t).tx || ''), chain: String(o(t).chain || ''), sym: String(o(t).sym || ''), qty: num(o(t).qty), usd: o(t).usd == null ? null : num(o(t).usd) })) })) };
  }
  const ofTraced = r => !!(r && r.flow && ['ok', 'partial'].indexOf(r.flow.status) >= 0);
  const ofNetV = r => ofTraced(r) ? Math.max(0, r.flow.net - num(r.linkTokenUsd)) : ((r.returnedUsd || r.matchedUsd || r.linkTokenUsd) && r.netUsd != null ? Math.max(0, r.netUsd) : ((r.sendKnown ? r.usdAtSend : 0) || r.usdNow));
  const RLW = Object.assign(new Set(), { known: false, auto: false, at: 0, stateAt: 0, pin: new Map() });
  let rlBusy = false, rlAgain = false, rlAt = 0;
  async function rlFetch(force) {
    if (S.locked) return;
    if (rlBusy) { if (force) rlAgain = true; return; }
    if (!force && Date.now() - rlAt < 5000) return;
    rlBusy = true; const t0 = rlAt = Date.now();
    try {
      const r = await fetch('/api/wallet_reload', { cache: 'no-store', credentials: 'same-origin' });
      const j = r.ok ? await r.json() : null;
      if (!j || !j.ok || !Array.isArray(j.addrs) || S.locked) return;
      const nx = new Set(j.addrs.map(String));
      RLW.pin.forEach((at, a) => { if (at >= t0) nx.add(a); else RLW.pin.delete(a); });
      const same = nx.size === RLW.size && [...nx].every(a => RLW.has(a));
      const stale = S.D && arr(S.D.of).some(x => x.applyWait ? !nx.has(x.address) : nx.has(x.address) && (x.status === 'pending' || x.status === 'own_restart_needed'));
      const chg = !same || !RLW.known || RLW.auto !== !!j.auto || stale;
      RLW.clear(); nx.forEach(a => RLW.add(a));
      RLW.known = true; RLW.auto = !!j.auto; RLW.at = t0;
      if (chg && S.data && S.D) { S.D = derive(S.data); render(); }
    } catch (e) {  } finally { rlBusy = false; if (rlAgain) { rlAgain = false; rlFetch(true); } }
  }
  function rlWait(r, st) {
    const a = String(r.address);
    if (RLW.has(a) && (st === 'pending' || st === 'own_restart_needed')) return true;
    if (st !== 'own_restart_needed') return false;
    if (r._rlOpt) return true;
    return !!r.applyWait && !(RLW.known && RLW.at >= RLW.stateAt);
  }
  function normOF(r) {
    if (!r || typeof r !== 'object' || !r.address) return null;
    const st = String(r.status || (r.verdict ? r.verdict : 'pending'));
    const aw = rlWait(r, st);
    const bucket = aw || st === 'pending' || st === 'bridge_untracked' ? 'pending' : st === 'spam' ? 'spam' : st === 'system' ? 'system' : st === 'returned' ? 'returned' : st === 'bridge_matched' ? 'bridge' : (st.indexOf('own') === 0 ? 'own' : st.indexOf('exchange') === 0 ? 'exchange' : st === 'external' ? 'external' : 'other');
    const toks0 = arr(r.tokens).map(t => ({ sym: String(t.sym || '?'), qty: num(t.qty), usdAtSend: t.usdAtSend == null ? null : num(t.usdAtSend), usdNow: num(t.usdNow), phantom: !!t.phantom, airdrop: t.quar === 'airdrop' }));
    const realT = toks0.filter(t => !t.phantom || t.airdrop), toks = bucket !== 'spam' && realT.length && realT.length < toks0.length ? realT : toks0;
    const txN = r.txs ? arr(r.txs).length : num(r._txn);
    const fold = bucket !== 'spam' && num(r.phantomTxN) > 0 && num(r.phantomTxN) < (num(r.count) || txN);
    const txs0 = arr(r.txs), txsV = fold ? txs0.filter(t => !(t && t.phantom)) : txs0;
    const chains = arr(r.chains).map(String), names = arr(r.chainNames).length ? arr(r.chainNames).map(String) : chains.map(c => CHAIN_KO[c] || c);
    return { address: String(r.address), chains, chainNames: names, count: num(r.count) || txN, tokens: toks, phantomN: toks0.length - toks.length,
      txsV, phTxN: fold ? num(r.phantomTxN) : 0,
      txsCut: Math.max(0, num(r.txsCut)),
      usdAtSend: num(r.usdAtSend), usdNow: num(r.usdNow), costUsd: num(r.costUsd), status: st, bucket, verdict: r.verdict || null,
      category: r.category || '', memo: r.memo || '', alias: r.alias || '', exchange: r.exchange || '',
      links: arr(r.links).filter(l => l && l.key).map(l => ({ kind: l.kind === 'refund' ? 'refund' : 'tokens', key: String(l.key), sym: String(l.sym || '?'), qty: num(l.qty), ts: num(l.ts),
        where: String(l.where || ''), tx: String(l.tx || ''), st: String(l.st || ''), usd: l.usd == null ? null : num(l.usd), costUsd: l.costUsd == null ? null : num(l.costUsd) })),
      linkRefundUsd: num(r.linkRefundUsd), linkTokenUsd: num(r.linkTokenUsd), saleWait: num(r.saleWait),
      linkPaidUsd: r.linkPaidUsd == null ? null : num(r.linkPaidUsd),
      excludeLegs: arr(r.excludeLegs).map(String), candN: num(r.candN),
      candTop: arr(r.candTop).filter(c => c && c.key).map(c => ({ key: String(c.key), sym: String(c.sym || '?'), qty: num(c.qty), ts: num(c.ts), stable: !!c.stable, where: String(c.where || ''), fromSender: !!c.fromSender, kind: c.kind === 'refund' ? 'refund' : 'tokens' })),
      firstTs: num(r.firstTs), lastTs: num(r.lastTs), first: r.first || '', last: r.last || '', decidedTs: num(r.decidedTs),
      hints: arr(r.hints), flags: arr(r.flags), txs: arr(r.txs),
      applying: st === 'own_restart_needed' || st === 'exchange_applying', applyWait: aw, matched: st === 'exchange_matched' || st === 'bridge_matched',
      brU: st === 'bridge_untracked', bridge: r.bridge && typeof r.bridge === 'object' ? r.bridge : null, arrivals: arr(r.arrivals),
      arrivalsN: r.arrivalsN != null ? num(r.arrivalsN) : arr(r.arrivals).length, returnedN: r.returnedN != null ? num(r.returnedN) : arr(r.returned).length,
      sendKnown: r.usdAtSendKnown !== false && r.usdAtSend != null, special: r.address === 'multi' || r.address === '?',
      autoMatch: r.autoMatch && typeof r.autoMatch === 'object' ? r.autoMatch : null, noAuto: !!r.noAuto,
      suggest: r.suggest && typeof r.suggest === 'object' ? r.suggest : null, suggestions: arr(r.suggestions),
      returned: arr(r.returned), returnedUsd: num(r.returnedUsd), matchedUsd: num(r.matchedUsd), returnKind: r.returnKind || null,
      netUsd: r.netUsd == null ? null : num(r.netUsd),
      retOk: !!r.retOk, retSugg: !!r.retSugg,
      flow: normFlow(r.flow),
      aiOp: r.aiOp && typeof r.aiOp === 'object' ? r.aiOp : null,
      exwd: arr(r.exwd).map(x0 => { const x = x0 && typeof x0 === 'object' ? x0 : {};
        return { exName: String(x.exName || x.ex || ''), sym: String(x.sym || ''), qty: num(x.qty), net: String(x.net || ''),
          txid: String(x.txid || ''), addr: String(x.addr || ''), ts: num(x.ts), cls: x.cls || null, dst: x.dst || null, why: x.why || null, offc: !!x.offc }; }),
      exwdN: num(r.exwdN), exwdOnly: !!r.exwdOnly, noAddr: String(r.address).indexOf('wd:') === 0,
      exwdOffc: r.exwdOffc && typeof r.exwdOffc === 'object' && num(r.exwdOffc.n) > 0 ? { n: num(r.exwdOffc.n), ex: arr(r.exwdOffc.ex).map(String) } : null,
      dustPoison: st === 'pending' && (!!r.dust || (Math.max(num(r.usdAtSend), num(r.usdNow)) < 1 && arr(r.flags).some(f => f && f.kind === 'lookalike'))) };
  }
  function derive(d) {
    const f = (d && d.fields) || {};
    const D = { f, todayKey: d.todayKey || todayISO().slice(5), builtAt: d.builtAt };
    D.rate = num(f.rate) || 1384; D.fx = num(f.fxRate) || D.rate; D.kimp = (D.rate / D.fx - 1) * 100;
    D.rateSrc = ['live', 'stale', 'fallback'].indexOf(f.rateSrc) >= 0 ? f.rateSrc : (num(f.rate) > 0 ? 'live' : 'fallback'); D.rateAt = num(f.rateAt) || null;
    D.rateLive = D.rateSrc === 'live' && num(f.rate) > 0;
    const stables = arr(f.stables), coins = arr(f.coins), fiats = arr(f.fiats), lps = arr(f.lps).map(normLP).filter(Boolean);
    D.stables = stables; D.fiats = fiats; D.lps = lps;
    D.krw = f.krwFlows && typeof f.krwFlows === 'object' && Array.isArray(f.krwFlows.rows) ? f.krwFlows : null;
    D.lpsClosed = lps.filter(l => l.state === 'closed').concat(arr(f.lpsClosed).map(normLP).filter(l => l && l.state === 'closed' && !lps.some(x => x.key === l.key)));
    D.stableTotal = sum(stables, s => num(s.qty) * num(s.price));
    D.coinTotal = sum(coins, c => num(c.qty) * num(c.price));
    D.fiatTotal = sum(fiats, x => num(x.krw) / D.rate);
    const lpLive = lps.filter(l => l.state !== 'closed');
    D.lpValue = sum(lpLive, l => num(l.value)); D.lpDeposit = sum(lpLive, l => num(l.principal));
    D.lpFees = sum(lpLive, l => num(l.fees)); D.lpRewards = sum(lpLive, l => num(l.rewards));
    D.lpTotal = D.lpValue + D.lpFees + D.lpRewards;
    D.cashTotal = D.stableTotal + D.fiatTotal;
    D.rbDebts = arr(f.rabbyDebts); D.rbDebt = sum(D.rbDebts, x => num(x.usd));
    D.rabby = (f.rabby && typeof f.rabby === 'object') ? f.rabby : null;
    D.total = D.stableTotal + D.coinTotal + D.fiatTotal + D.lpTotal + D.rbDebt;
    D.rbValue = sum(coins.filter(c => c && c.rabby), c => num(c.qty) * num(c.price));
    D.coinDex = num(f.coinDexUsd); D.coinCex = num(f.coinCexUsd);

    const G = new Map();
    D.priceOf = {}; D.unkInst = []; D.instOf = {};
    const TWIN_X = 1.5, twinKey = {};
    (() => {
      const bk = new Map();
      coins.forEach(c => { if (c.symSrc || !(num(c.price) > 0) || !(num(c.qty) > 0)) return; const k = String(c.sym || '?').toUpperCase(); (bk.get(k) || bk.set(k, []).get(k)).push(c); });
      bk.forEach((cs, k) => {
        if (cs.length < 2) return;
        const cl = [];
        cs.slice().sort((a, b) => num(b.qty) * num(b.price) - num(a.qty) * num(a.price)).forEach(c => {
          const p = num(c.price), hit = cl.find(x => p <= x.p * TWIN_X && p >= x.p / TWIN_X);
          if (hit) hit.cs.push(c); else cl.push({ p, cs: [c] });
        });
        if (cl.length < 2) return;
        cl.forEach((x, i) => { if (i) x.cs.forEach(c => { twinKey[String(c.key)] = k + '~' + String(x.cs[0].key); }); });
        D.twinSyms = (D.twinSyms || new Set()).add(k);
      });
    })();
    const gKeyOf = c => c.symSrc ? '#' + String(c.key) : (twinKey[String(c.key)] || String(c.sym || '?').toUpperCase());
    const pricedK = new Set(); coins.forEach(c => { if (num(c.qty) > 0 && num(c.price) > 0) pricedK.add(gKeyOf(c)); });
    coins.forEach(c => {
      const sym = String(c.sym || '?'), k = gKeyOf(c);
      let g = G.get(k);
      if (!g) { g = { sym, key: k, insts: [], value: 0, qty: 0, cost: 0, pnl: 0, unkVal: 0, unkQty: 0, unpriced: false, locs: new Map(), wValue: 0, xValue: 0, keys: [] }; G.set(k, g); }
      if (D.twinSyms && D.twinSyms.has(sym.toUpperCase()) && !c.symSrc) g.twin = true;
      if (c.imp) g.imp = c.imp;
      const qty = num(c.qty), price = num(c.price), avg = num(c.avg);
      D.priceOf[c.key] = price;
      const kq = c.kqty != null ? num(c.kqty) : qty, fbc = num(c.fbCost);
      const hasCost = avg > 0 && price > 0;
      const cost = hasCost ? kq * avg + fbc : 0;
      const pnl = hasCost ? (fbc > 0 ? qty * price - cost : (price - avg) * kq) : 0;
      const value = qty * price;
      const rb = c.rabby && typeof c.rabby === 'object' ? c.rabby : null;
      const unkQty = rb ? 0 : avg > 0 ? (fbc > 0 ? 0 : Math.max(0, qty - kq)) : Math.max(0, qty);
      const inst = { key: c.key, sym, name: c.name, chain: chainOf(c.name), ck: c.ck, ca: c.ca, genU: !!c.genU, qty, price, avg, kq, fbQty: num(c.fbQty), fbCost: fbc, cost, pnl, value, unkQty, hasCost,
        pxSrc: String(c.pxSrc || ''), pxAge: c.pxAge != null ? num(c.pxAge) : null, pxPre: !!c.pxPre, pxPreN: num(c.pxPreN), rabby: rb };
      if (rb) { g.rabby = g.rabby ? Math.min(g.rabby, num(rb.at)) : num(rb.at); g.rbValue = (g.rbValue || 0) + value; if (c.rbKind != null) g.rbKind = String(c.rbKind || ''); }
      if (inst.pxSrc.startsWith('dex:') && inst.pxAge != null && inst.pxAge > PX_STALE && value > 0) { g.staleAge = Math.max(g.staleAge || 0, inst.pxAge); g.staleVal = (g.staleVal || 0) + value; }
      g.insts.push(inst); g.keys.push(c.key); D.instOf[c.key] = inst;
      if (qty > 0 && !(price > 0) && pricedK.has(k)) { inst.zero = true; return; }
      g.value += value; g.qty += qty; g.cost += cost; g.pnl += pnl; g.unkVal += unkQty * price; g.unkQty += unkQty;
      if (num(c.fsc) > 0) g.fsc = (g.fsc || 0) + num(c.fsc);
      if (unkQty * price > 0) D.unkInst.push({ key: String(c.key), sym, usd: unkQty * price });
      if (!(price > 0) && qty > 0) g.unpriced = true;
      arr(c.locs).forEach(l => {
        const w = String(l.w || '?'), wallet = w.indexOf('지갑') >= 0, lq = num(l.qty), lv = lq * price;
        let L = g.locs.get(w);
        if (!L) { L = { w, wallet, value: 0, qty: 0, subs: [] }; g.locs.set(w, L); }
        L.value += lv; L.qty += lq;
        L.subs.push({ sub: l.sub || '', ch: l.ch || inst.chain, qty: lq, value: lv, inst: c.key, tr: l.tr && typeof l.tr === 'object' ? l.tr : null });
        if (l.tr && typeof l.tr === 'object') (g.tr = g.tr || []).push(l.tr);
        if (wallet) g.wValue += lv; else g.xValue += lv;
      });
    });
    D.groups = Array.from(G.values()).map(g => {
      g.roi = g.cost > 0 ? g.pnl / g.cost * 100 : null;
      g.unkPct = g.value > 0 ? g.unkVal / g.value : (g.unkQty > 0 ? 1 : 0);
      g.locList = Array.from(g.locs.values()).sort((a, b) => b.value - a.value || b.qty - a.qty);
      const ws = g.locList.filter(l => l.wallet).length, n = g.locList.length;
      g.locSummary = n === 0 ? '—' : (ws === n && n >= 3) ? '지갑 ' + n + '곳'
        : g.locList.slice(0, 2).map(l => l.w).join(' · ') + (n > 2 ? ' 외 ' + (n - 2) + '곳' : '');
      const chs = [], xs = [];
      let xAnon = false;
      g.insts.forEach(i => { if (i.zero) return; if (EX_BY_KO[i.chain]) { if (i.qty > 0 && xs.indexOf(i.chain) < 0) xs.push(i.chain); return; }
        if (!i.chain && i.qty > 0 && !i.rabby) xAnon = true;
        i.chain.split('/').forEach(c => { if (c && chs.indexOf(c) < 0) chs.push(c); }); });
      g.chains = chs;
      const xLbl = xs.length === 1 && !xAnon ? xs[0] : (xs.length || (xAnon && chs.length) ? '거래소' : '');
      const chs2 = xLbl ? chs.concat([xLbl]) : chs;
      g.chainLabel = (chs2.length ? (chs2.length > 2 ? chs2.slice(0, 2).join(' · ') + ' 외 ' + (chs2.length - 2) + '곳' : chs2.join(' · ')) : '거래소') ;
      g.nInst = g.insts.filter(i => !i.zero).length;
      const big = g.insts.filter(i => i.ca && !i.zero).sort((a, b) => b.value - a.value)[0];
      g.logo = { ck: big && big.ck, ca: big && big.ca, chain: chs.length === 1 && g.xValue <= 0 && n > 0 ? chs[0] : '' };
      return g;
    }).sort((a, b) => b.value - a.value);
    D.unreal = sum(D.groups, g => g.pnl);
    D.totalCost = sum(D.groups, g => g.cost);
    D.roiAll = D.totalCost > 0 ? D.unreal / D.totalCost * 100 : 0;
    D.unkVal = sum(D.groups, g => g.unkVal);
    D.unkN = D.groups.filter(g => g.unkVal >= 1).length;
    D.unpriced = arr(f.unpricedSyms).map(String);
    D.zeroInst = coins.filter(c => num(c.qty) > 0 && !(num(c.price) > 0)).map(c => ({ key: String(c.key), sym: spamNm(String(c.sym || '?')), chain: chainOf(c.name), qty: num(c.qty), guard: !!c.guard,
      unv: c.unv ? String(c.unv) : '', genU: !!c.genU, ck: String(c.ck || ''), ca: String(c.ca || ''),
      cost: num(c.avg) > 0 ? num(c.avg) * (c.kqty != null ? num(c.kqty) : num(c.qty)) : 0, where: arr(c.locs).map(l => String(l.w || '')).filter(Boolean) }))
      .sort((a, b) => b.cost - a.cost || (a.guard === b.guard ? 0 : a.guard ? -1 : 1) || (!a.unv === !b.unv ? 0 : a.unv ? -1 : 1) || String(a.sym).localeCompare(String(b.sym)));
    const zg = D.zeroInst.filter(z => z.guard).map(z => z.sym);
    D.unpricedSym = (() => { const c = new Map(), dropG = new Map(); zg.forEach(x => dropG.set(x, (dropG.get(x) || 0) + 1));
      D.unpriced.forEach(x => { const k0 = spamNm(x); if (dropG.get(k0) > 0) { dropG.set(k0, dropG.get(k0) - 1); return; } c.set(k0, (c.get(k0) || 0) + 1); });
      return Array.from(c.entries()).map(([k, n]) => k + (n > 1 ? ' ×' + n : '')); })();
    D.upN = Math.max(0, D.unpriced.length - zg.length);
    D.symLogo = {}; D.groups.forEach(g => { D.symLogo[g.key] = g.logo; });

    const SG = new Map();
    stables.forEach(s => {
      const k = String(s.sym || '?').toUpperCase();
      let g = SG.get(k); if (!g) { g = { sym: s.sym, value: 0, qty: 0, locs: [] }; SG.set(k, g); }
      g.value += num(s.qty) * num(s.price); g.qty += num(s.qty);
      arr(s.locs).forEach(l => { const tr = l.tr && typeof l.tr === 'object' ? l.tr : null; if (tr) (g.tr = g.tr || []).push(tr);
        g.locs.push({ w: l.w, sub: l.sub, qty: num(l.qty), value: num(l.qty) * num(s.price), tr }); });
    });
    D.stableGroups = Array.from(SG.values()).sort((a, b) => b.value - a.value);

    const V = new Map();
    const addV = (name, kind, sub, sym, qtyLabel, usd, ch) => {
      let v = V.get(name); if (!v) { v = { name, kind, sub, total: 0, items: [] }; V.set(name, v); }
      v.total += usd; v.items.push({ sym, qty: qtyLabel, usd, ch: ch || '', sub: sub || '' });
    };
    D.stableSyms = new Set(stables.map(s => String(s.sym || '').toUpperCase()));
    stables.concat(coins).forEach(a => arr(a.locs).forEach(l => {
      const wallet = String(l.w || '').indexOf('지갑') >= 0;
      addV(l.w || '?', wallet ? 'wallet' : 'cex', wallet ? l.sub : '거래소 계정', a.sym, num(l.qty), num(l.qty) * num(a.price), l.ch || chainOf(a.name));
    }));
    fiats.forEach(x => addV(x.ex, 'cex', '거래소 계정', 'KRW', { krw: num(x.krw) }, num(x.krw) / D.rate));
    lps.filter(l => l.state !== 'closed').forEach(l => addV(l.protocol || 'LP', 'lp', l.chain + ' · 풀 컨트랙트', l.pool, l.stateLabel, num(l.value) + num(l.fees) + num(l.rewards), l.chain));
    D.venues = Array.from(V.values()).sort((a, b) => b.total - a.total);
    D.exN = D.venues.filter(v => v.kind === 'cex').length;

    D.positions = arr(f.positions);
    D.plans = (f.plans && typeof f.plans === 'object') ? f.plans : {};
    D.plansMemoOk = !!(f.planMemos && typeof f.planMemos === 'object');
    D.memos = D.plansMemoOk ? f.planMemos : {};
    if (optHas('plan')) optPlans(D);
    D.dmOk = f.dayMemosOk === true;
    D.dayMemos = D.dmOk && f.dayMemos && typeof f.dayMemos === 'object' ? f.dayMemos : {};
    D.dmErr = D.dmOk && f.dayMemosErr ? String(f.dayMemosErr) : '';
    const dustLim = () => Math.max(1, S.dust || 0);
    D.posGrp = {};
    if (D.twinSyms) {
      const ps = D.positions.filter(p => !p.symSrc && D.twinSyms.has(String(p.sym || '').toUpperCase()));
      const gk = k => { const i = D.instOf[k]; return i ? (twinKey[k] || String(i.sym || '?').toUpperCase()) : ''; };
      const rest = [], anc = {};
      ps.forEach(p => { const k = String(p.key), r = k.replace(/f\d+$/, ''), g = gk(k) || (r !== k ? gk(r) : '');
        if (!g) { rest.push(p); return; }
        D.posGrp[k] = g;
        if (num(p.cost) > 0 && num(p.bought) > 0) { const a = anc[g] || (anc[g] = [0, 0]); a[0] += num(p.cost); a[1] += num(p.bought); } });
      rest.forEach(p => {
        const sy = String(p.sym || '').toUpperCase(), av = num(p.avg);
        let best = sy, bd = Infinity;
        if (av > 0) Object.keys(anc).forEach(g => { if (g !== sy && g.indexOf(sy + '~') !== 0) return; const d = Math.abs(Math.log(av / (anc[g][0] / anc[g][1]))); if (d < bd) { bd = d; best = g; } });
        D.posGrp[String(p.key)] = best;
      });
    }
    const posBy = new Map(D.positions.map(x => [x.key, x]));
    D.merged = symMerge(D.positions, p => D.posGrp[String(p.key)]).map(p => {
      let last = '';
      (arr(p._legP).length > 1 ? p._legP : [p]).forEach(lg => { const i = lastIsoOf(lg); if (i > last) last = i; });
      Object.keys(p.actByDay || {}).concat(Object.keys(p.realizedByDay || {})).forEach(k => { const i = isoDay(k); if (i > last.slice(0, 10)) last = i; });
      const legPx = () => { let h = 0, v = 0; const ls = arr(p._legs).length > 1 ? p._legs : [p.key];
        ls.forEach(k => { const lg = ls.length > 1 ? posBy.get(k) : p, hh = lg ? num(lg.held) : 0, i = D.instOf[k]; if (hh > 0 && i && i.price > 0) { h += hh; v += hh * i.price; } });
        return h > 0 ? v / h : 0; };
      const fbPx = p.held > 0 && p.avg > 0 ? num(p.avg) + num(p.unreal) / num(p.held) : 0;
      const price = (num(D.priceOf[p.key]) > 0 ? num(D.priceOf[p.key]) : 0) || legPx() || (fbPx > 0 ? fbPx : 0);
      const tot = num(p.soldQty) + num(p.held);
      const soldPct = tot > 0 ? Math.min(100, num(p.soldQty) / tot * 100) : 0;
      const heldVal = num(p.held) * price;
      let st = p.status;
      if (st !== '종료' && num(p.soldQty) > 0 && price > 0 && heldVal < dustLim() && Math.abs(num(p.unreal)) < dustLim()) st = '종료';
      if (st !== '종료' && !(num(p.held) > 0)) st = '종료';
      return Object.assign(p, { _last: last, _price: price, _soldPct: soldPct, _heldVal: heldVal, _st: st,
        _mv: st === '종료' && !(p._nLegs > 1) ? mvDest(p) : '',
        _dustLeft: st === '종료' && num(p.held) > 0, _noCost: !(num(p.cost) > 0) });
    });
    D.merged.forEach(p => {
      p._now = null;
      if (p._st === '종료' || !(num(p.held) > 0) || p.kind === 'gas' || p.kind === 'stable') return;
      let v = 0, stV = 0, age = 0, unpQ = 0, any = false;
      (arr(p._legs).length ? p._legs : [p.key]).forEach(k => {
        const lg = arr(p._legs).length > 1 ? posBy.get(k) : p, h = lg ? num(lg.held) : 0;
        if (!(h > 0)) return;
        const i = D.instOf[k], pr = i ? i.price : 0;
        if (!(pr > 0)) { unpQ += h; return; }
        const lv = h * pr; v += lv; any = true;
        if (i.pxSrc.startsWith('dex:') && i.pxAge != null && i.pxAge > PX_STALE) { stV += lv; age = Math.max(age, i.pxAge); }
      });
      if (any) p._now = { v, stale: stV > 0 && stV >= v * 0.1 ? age : 0, unpQ };
    });
    const lpR = arr(f.lpsClosed).filter(l => l && typeof l === 'object').concat(arr(f.lpsPending).filter(l => l && Object.keys(l.realizedByDay || {}).length)).map(normLP).filter(Boolean);
    D.lpName = new Map();
    D.lps.concat(arr(f.lpsClosed).concat(arr(f.lpsPending)).map(normLP).filter(Boolean)).forEach(l => {
      if (!l.id || String(l.pool).indexOf('/') < 0) return;
      const nm = l.pool + ' #' + l.id;
      D.lpName.set(String(l.key), nm); if (l.raw && l.raw.key) D.lpName.set(String(l.raw.key), nm);
      if (l.protocol && !D.lpName.has(l.protocol + ' #' + l.id)) D.lpName.set(l.protocol + ' #' + l.id, nm);
    });
    D.lpCycles = D.lps.concat(lpR).map(l => {
      const ev = arr(f.lpEvents).filter(e => e.lp === l.key || e.lp === (l.raw && l.raw.key));
      let last = '';
      ev.forEach(e => { const i = isoOf(e.t); if (i > last) last = i; });
      const closed = l.state === 'closed';
      return { key: 'lp:' + l.key, sym: l.pool, chain: l.chain || '?', status: closed ? '종료' : '보유', _st: closed ? '종료' : '보유', opened: l.opened || '—',
        cost: num(l.principal), realized: l.raw && l.raw.realizedByDay ? sum(Object.keys(l.raw.realizedByDay), k => num(l.raw.realizedByDay[k])) : l.realized,
        realizedFb: 0, realizedByDay: (l.raw && l.raw.realizedByDay) || null, realizedKrwByDay: (l.raw && l.raw.realizedKrwByDay) || null, unreal: l.pnl == null ? 0 : l.pnl, held: closed ? 0 : 1,
        events: ev, steps: ['유동성 예치'].concat(num(l.fees) > 0 ? ['수수료 누적'] : []).concat(l.state === 'out' ? ['범위 이탈'] : []).concat(closed ? ['인출 완료'] : []),
        _lp: l, _last: last, _price: 0, _soldPct: closed ? 100 : 0, _heldVal: num(l.value),
        _now: !closed && l.value != null ? { v: num(l.value), stale: 0, unpQ: 0 } : null };
    });
    buildEvents(D, f);
    D.dayActs = (f.dayActs && typeof f.dayActs === 'object') ? f.dayActs : null;

    D.fut = (f.futures && typeof f.futures === 'object') ? f.futures : {};
    D.realized = {}; D.realizedK = {};
    const mdIn = k => { if (!isYMD(k)) return String(k); const md = String(k).slice(5, 10); return ymOf(md) === String(k).slice(0, 7) ? md : null; };
    const addR = (mp, mk) => Object.keys(mp || {}).forEach(k => { const md = mdIn(k); if (!md) return; D.realized[md] = num(D.realized[md]) + num(mp[k]);
      const kv = mk && mk[k] != null ? num(mk[k]) : num(mp[k]) * rate(); D.realizedK[md] = num(D.realizedK[md]) + kv; });
    addR(f.realizedByDate, f.realizedKrwByDate); addR(D.fut.realizedByDate, D.fut.realizedKrwByDate);
    D.hasKrw = !!f.realizedKrwByDate;
    D.tax = arr(f.taxRows).map(r => Object.assign({}, r));
    const futRows = arr(D.fut.realizedRows).map(r => ({
      sold: num(r._ts) > 0 ? new Date(num(r._ts) + 32400000).toISOString().slice(0, 10) : String(r.t || '').slice(0, 5),
      sym: futSym(r.sym), ticker: r.sym + ' · 선물', ex: r.ex, qty: 0,
      acq: num(r.pnl) < 0 ? -num(r.pnl) : 0, disp: num(r.pnl) > 0 ? num(r.pnl) : 0, fee: 0, fut: true }));
    futRows.forEach(r => D.tax.push(r));
    D.taxSum = arr(f.taxSummary).map(r => ({ ym: r[0], sym: r[1], ex: r[2], n: num(r[3]), qty: num(r[4]), acq: num(r[5]), disp: num(r[6]), fee: num(r[7]),
      pk: r.length > 8 ? num(r[8]) : null, ak: r.length > 10 ? num(r[9]) : null, dk: r.length > 10 ? num(r[10]) : null, tx: r.length > 11 ? num(r[11]) : 0,
      ak2: r.length > 13 ? num(r[12]) : null, pk2: r.length > 13 ? num(r[13]) : null, akfb: r.length > 14 ? num(r[14]) : 0,
      tk: r.length > 15 ? String(r[15] || '') : '' }));
    if (Array.isArray(D.fut.realizedSummary)) {
      const fk = D.fut.realizedKrwByDate || null, fu = D.fut.realizedByDate || {}, eff = {};
      Object.keys(fu).forEach(k => { const ym = String(k).slice(0, 7), u = num(fu[k]), w = fk && fk[k] != null ? num(fk[k]) : u * D.rate; const e = eff[ym] || (eff[ym] = { au: 0, aw: 0, u: 0, w: 0 }); e.au += Math.abs(u); e.aw += Math.abs(w); e.u += u; e.w += w; });
      const fr = D.fut.realizedSummary.map(r => ({ ym: String(r[0] || '기타'), sym: futSym(r[1]), ex: r[2], n: num(r[3]), qty: 0, acq: num(r[5]), disp: num(r[4]), fee: 0, pk: null, ak: null, dk: null, fut: true }));
      Object.keys(eff).forEach(ym => {
        const rs = fr.filter(r => r.ym === ym), d = eff[ym].u - sum(rs, r => r.disp - r.acq);
        if (Math.abs(d) >= 0.005) fr.push({ ym, sym: '선물 수수료·펀딩', ex: '선물', n: 0, qty: 0, acq: 0, disp: 0, fee: -d, pk: null, ak: null, dk: null, fut: true, futFee: true });
      });
      if (fk) Object.keys(eff).forEach(ym => {
        const e = eff[ym], rt = e.au > 0 ? e.aw / e.au : null, rows = fr.filter(r => r.ym === ym);
        if (!rt || !rows.length) return;
        rows.forEach(r => { r.ak = r.acq * rt; r.dk = r.disp * rt; r.pk = (r.disp - r.acq - r.fee) * rt; });
        const big = rows.slice().sort((a, b) => Math.abs(b.disp - b.acq - b.fee) - Math.abs(a.disp - a.acq - a.fee))[0], res = e.w - sum(rows, r => r.pk);
        if (Math.abs(sum(rows, r => r.disp - r.acq - r.fee) - e.u) < Math.max(0.01, Math.abs(e.u) * 1e-8)) { big.pk += res; if (!big.futFee) { if (big.disp >= big.acq) big.dk += res; else big.ak -= res; } }
      });
      fr.forEach(r => D.taxSum.push(r));
    }
    else futRows.forEach(r => D.taxSum.push({ ym: ymOf(r.sold) || '기타', sym: r.sym, ex: r.ex, n: 1, qty: 0, acq: r.acq, disp: r.disp, fee: 0, pk: null, ak: null, dk: null, fut: true }));
    D.taxStableFx = f.taxStableFx && typeof f.taxStableFx === 'object' && !Array.isArray(f.taxStableFx) ? f.taxStableFx : null;
    D.taxFull = Array.isArray(f.taxSummary);
    D.taxN = num(f.taxRowsTotal) || arr(f.taxRows).length;

    D.daily = arr(f.dailySeries).map((x, i, a) => Object.assign({}, x, { val: num(x.val), delta: i > 0 ? num(x.val) - num(a[i - 1].val) : null,
      valKrw: x.valKrw != null && isFinite(+x.valKrw) ? num(x.valKrw) : null }));
    D.daily.forEach((x, i) => { x._prev = i > 0 ? D.daily[i - 1] : null; });
    D.daily.forEach(x => { const a0 = num(x.est) + num(x.xc); x.ap = a0 >= Math.max(50, 0.005 * Math.abs(x.val)) ? a0 : 0; });
    D.dayMap = new Map(D.daily.map(x => [x.date, x]));
    D.usdt = f.usdtByDate || {};
    D.reviews = (f.reviews && typeof f.reviews === 'object') ? f.reviews : {};

    D.pendings = optHas('ign') ? arr(f.pendings).filter(p => !(p && optOf('ign', String(p.key)))) : arr(f.pendings);
    D.pendings.forEach(p => { p._cat = pcat(p); });
    D.pendVis = D.pendings.filter(p => !p.hide);
    D.pendHid = D.pendings.filter(p => !!p.hide);
    D.spamN = D.pendVis.filter(p => p._cat === 'spam').length;
    D.unvN = D.pendVis.filter(p => p._cat === 'unv').length;
    D.unvHidN = D.pendHid.filter(p => p._cat === 'unv').length;
    D.unkhRows = D.pendVis.filter(p => p._cat === 'unkh');
    D.unkhUsd = sum(D.unkhRows, p => num(p.usd));
    D.unkhSymN = new Set(D.unkhRows.map(p => String(p.sym || '').toUpperCase() || p.key)).size;
    D.pendN = D.pendVis.length - D.unkhRows.length + D.unkhSymN;
    D.unkhFbN = D.unkhRows.filter(p => num(p.fbCost) > 0 && /폴백 적용/.test(String(p.kind || ''))).length;
    const unkListed = new Set(D.unkhRows.map(p => String(p.ckey || p.gkey || '')).filter(Boolean));
    const unkRest = D.unkInst.filter(x => !unkListed.has(x.key));
    D.unkRestUsd = sum(unkRest, x => x.usd); D.unkRestN = new Set(unkRest.filter(x => x.usd >= 0.005).map(x => x.sym.toUpperCase())).size;

    D.xferLinks = optLinks(arr(f.xferLinks), 'xfer', 'dep'); D.saleLinks = optLinks(arr(f.saleLinks), 'sale', 'lot'); D.wdDest = arr(f.wdDestUnknown); D.wdDestN = f.wdDestUnknownTotal != null ? num(f.wdDestUnknownTotal) : D.wdDest.length; D.wdDestStats = (f.wdDestStats && typeof f.wdDestStats === 'object') ? f.wdDestStats : {};
    deriveOF(D, f);
    D.saleAlert = f.saleCandAlert !== false;

    D.wallets = optHas('alias') ? arr(f.walletRows).map(w => { const p = w && optOf('alias', String(w.key || w.addr || '')); return p ? Object.assign({}, w, p, { _opt: true }) : w; }) : arr(f.walletRows); D.deposits = arr(f.depositRows); D.aliases = arr(f.aliasRows); D.srcChips = arr(f.srcChips);
    D.walletAlias = (f.walletAlias && typeof f.walletAlias === 'object') ? f.walletAlias : {};
    D.costOv = arr(f.costOverrideRows);
    D.costDecided = arr(f.costDecidedRows);
    D.fallbackOn = !!f.fallbackOn;
    D.firstSeen = f.firstSeen && typeof f.firstSeen === 'object' && !Array.isArray(f.firstSeen) ? f.firstSeen : null;
    D.fsRbd = f.fsRealByDate && typeof f.fsRealByDate === 'object' && !Array.isArray(f.fsRealByDate) ? f.fsRealByDate : {};
    const oc0 = f.offchainSelf && typeof f.offchainSelf === 'object' ? f.offchainSelf : {};
    D.offc = Object.keys(oc0).map(ex => { const o = oc0[ex] && typeof oc0[ex] === 'object' ? oc0[ex] : {};
      return { ex, name: String(o.name || EX_NAMES[ex] || ex), on: o.on === true, answered: o.answered !== false, wdN: num(o.wdN), depN: num(o.depN), syms: num(o.syms),
        excl: arr(o.excl).map(String), exclN: num(o.exclN), byAddr: arr(o.byAddr).filter(b => b && typeof b === 'object'),
        soldN: num(o.assumedSold && o.assumedSold.n), soldReal: num(o.assumedSold && o.assumedSold.realized),
        coinCost: Math.max(0, num(o.wdCost) - num(o.wdCostStable)), stableCost: num(o.wdCostStable), inhN: num(o.inhN),
        inhCoin: Math.max(0, num(o.inhCost) - num(o.inhCostStable)), excessN: num(o.excessN), leftN: num(o.poolLeftN), leftCost: num(o.poolLeftCost),
        bySym: arr(o.bySym).filter(b => b && typeof b === 'object') }; }).filter(o => o.on || o.wdN || o.depN);
    D.dustUsd = num(f.dustUsd); D.hasDust = typeof f.dustUsd === 'number' && isFinite(f.dustUsd);
    D.whitelist = Array.isArray(f.srcWhitelist) ? f.srcWhitelist.map(String) : null;
    D.gasByChain = arr(f.gasByChain); D.gasByMonth = (f.gasByMonth && typeof f.gasByMonth === 'object') ? f.gasByMonth : null;
    D.taxGas = (f.taxGas && typeof f.taxGas === 'object') ? f.taxGas : null;
    D.todayBy = (f.todayByCoin && typeof f.todayByCoin === 'object') ? f.todayByCoin : null;
    D.spark7 = (f.spark7 && typeof f.spark7 === 'object') ? f.spark7 : null;
    D.gasExp = (f.gasExpenseByDate && typeof f.gasExpenseByDate === 'object') ? f.gasExpenseByDate : {};
    D.feeAll = (f.feeAllByDate && typeof f.feeAllByDate === 'object') ? f.feeAllByDate : {};
    D.debts = arr(f.exDebts).map(x => { const s0 = String(x.sym || '').toUpperCase(), g0 = coins.find(c => String(c.sym || '').toUpperCase() === s0), px0 = num(x.price) > 0 ? num(x.price) : g0 && num(g0.price) > 0 ? num(g0.price) : 1;
      return { ex: x.ex, sym: s0, qty: num(x.qty), usd: num(x.qty) * px0, kind: x.kind === 'loan' ? 'loan' : 'margin', note: String(x.note || '') }; }).filter(x => x.qty < 0);
    D.debtLbl = D.debts.some(x => x.kind === 'loan') ? '차입 부채' : '마진 부채';
    D.debtTip = () => D.debts.map(x => x.ex + ' ' + x.sym + ' ' + q(x.qty) + (x.kind === 'loan' ? ' · ' + x.note : '')).join(' · ');
    D.debtUsd = sum(D.debts, x => x.usd);
    D.revWk = (f.reviewsWeekly && typeof f.reviewsWeekly === 'object') ? f.reviewsWeekly : {};
    D.reviewLen = (f.reviewLen && typeof f.reviewLen === 'object' && f.reviewLen.daily) ? f.reviewLen : null;
    D.reviewProg = (f.reviewProgress && typeof f.reviewProgress === 'object') ? f.reviewProgress : null;
    D.legacy = { classic: !!(f.legacyPages && f.legacyPages.classic), futures: !!(f.legacyPages && f.legacyPages.futures) };
    D.reviewFill = (f.reviewFill && typeof f.reviewFill === 'object' && f.reviewFill.order) ? f.reviewFill : null;
    D.reviewPause = (f.reviewPause && typeof f.reviewPause === 'object') ? { on: f.reviewPause.on === true, at: num(f.reviewPause.at) || null } : null;
    D.lastScan = f.lastScan || '';
    D.vflows = f.venueFlows30 && typeof f.venueFlows30 === 'object' ? f.venueFlows30 : null;
    D.exBalTs = f.exBalTs && typeof f.exBalTs === 'object' ? f.exBalTs : {};
    D.upbit = !!f.upbitConnected;
    D.backfill = f.backfillProgress || null;
    D.prov = f.prov && typeof f.prov === 'object' ? f.prov : null;
    const bc = f.balanceCheck;
    D.bfSince = (f.backfillSince && typeof f.backfillSince === 'object') ? f.backfillSince : null;
    D.bc = (bc && typeof bc === 'object') ? { checkedAt: bc.checkedAt, checked: bc.checked, pairs: bc.pairs, capped: bc.capped, unchecked: bc.unchecked != null ? num(bc.unchecked) : null, errors: num(bc.errors), mismatches: arr(bc.mismatches) } : null;
    D.bcConfirmed = D.bc ? D.bc.mismatches.filter(x => x && (x.confirmed === undefined || !!x.confirmed)) : [];
    D.bcWatch = D.bc ? D.bc.mismatches.filter(x => x && x.confirmed === false) : [];
    const pg = (f.priceGuard && typeof f.priceGuard === 'object') ? f.priceGuard : {};
    D.priceGuard = Object.keys(pg).map(k => {
      const i = k.indexOf(':'), ch = i >= 0 ? k.slice(0, i) : '', ca = i >= 0 ? k.slice(i + 1) : k;
      const hit = coins.find(c => c.ca && String(c.ca).toLowerCase() === ca.toLowerCase());
      return { key: k, chain: CHAIN_KO[ch] || ch, ca, sym: hit ? hit.sym : '', reason: String(pg[k] == null ? '' : pg[k]) };
    });
    D.hasFlow = D.daily.some(x => x.flow != null);
    D.flowBig = (fl, base) => Math.abs(num(fl)) >= Math.max(500, 0.005 * Math.abs(num(base)));
    D.daily.forEach((x, i) => { if (x.flow != null && x.delta != null) x.mkt = x.delta - num(x.flow); });
    D.steps = D.daily.filter((x, i) => i > 0 && x.delta != null && (D.hasFlow ? D.flowBig(x.flow, D.daily[i - 1].val) : Math.abs(x.delta) > 0.2 * Math.abs(D.daily[i - 1].val))).map(x => x.date);
    D.flowSplitOk = (fl, delta) => Math.abs(num(fl)) >= Math.max(50, 0.25 * Math.abs(num(delta)));
    D.daily.forEach(x => { x.split = x.flow != null && x.delta != null && (D.steps.indexOf(x.date) >= 0 || D.flowSplitOk(x.flow, x.delta)); });
    const last = D.daily[D.daily.length - 1], pv = D.daily.length > 1 && last.date === D.todayKey ? D.daily[D.daily.length - 2] : last;
    D._today = pv ? D.total - pv.val : null;
    D._pv = pv;
    D._todayFlow = D.hasFlow && last && last.date === D.todayKey ? num(last.flow) : null;
    D._todayFlowTop = last && last.date === D.todayKey ? arr(last.flowTop) : [];
    D._todayStep = D._today != null && (D._todayFlow != null ? D.flowBig(D._todayFlow, pv.val) : pv && pv.val && Math.abs(D._today / pv.val) > 0.2);
    D._todayAp = !!pv && num(pv.ap) > 0;
    D._todaySplit = D._today != null && D._todayFlow != null && (D._todayStep || D.flowSplitOk(D._todayFlow, D._today));
    return D;
  }

  const PCATS = {
    unv: { label: '원가 미확인 매도', desc: '매수 기록 없이 들어온 수량을 판 건이에요. 실현손익에서 빠져 있고, 원가를 지정하면 반영돼요. 원가를 알 수 없으면 매수가 = 매도가로 처리할 수도 있어요.' },
    unkh: { label: '원가 미확인 보유', desc: '원가를 모르는 보유분이에요. 평가손익 계산에서 빠져 있어요 — 원가를 지정하거나 설정에서 평균가 대체를 켜세요.' },
    lost: { label: '창 밖 처분', desc: '옛 기록 수집 범위(5개월) 이전 보유분의 처분이에요. 표시용 보정이라 따로 할 일은 없어요.' },
    xfer: { label: '외부 전송 확인', desc: '미등록 외부 주소로 나간 전송이에요. 내 지갑이면 설정에서 추가하세요.' },
    prog: { label: '프로그램 수령 검토', desc: '컨트랙트를 거쳐 들어온 토큰이에요. 체결인지 에어드랍인지 확인이 필요해요.' },
    nodep: { label: '입금 기록 없음', desc: '거래소 입금 주소로 보냈지만 아직 입금 확인이 없어요.' },
    etc: { label: '기타 보류', desc: '자동 매칭이 보류된 건이에요.' },
    spam: { label: '스팸·에어드랍 의심', desc: '실매수 이력 없이 들어온 토큰이에요. 메인 목록·일별 기록에서 뺐어요 — 실제 보유면 복원하세요.' }
  };
  const PCAT_ORDER = ['unv', 'unkh', 'xfer', 'prog', 'nodep', 'etc', 'spam', 'lost'];
  function pcat(p) {
    const k = String(p.kind || ''), key = String(p.key || '');
    if (k.indexOf('스팸') === 0 || key.indexOf('risk:') === 0) return 'spam';
    if (k.indexOf('원가미상 매도') === 0 || key.indexOf('unv:') === 0) return 'unv';
    if (k.indexOf('원가미상') === 0 || key.indexOf('unkh:') === 0) return 'unkh';
    if (k.indexOf('창 밖') === 0) return 'lost';
    if (k.indexOf('프로그램') === 0) return 'prog';
    if (k.indexOf('전송') >= 0) return 'xfer';
    if (k.indexOf('입금 기록') === 0) return 'nodep';
    return 'etc';
  }

  function applyPatch(a, d) {
    if (d && d.$L) {
      const K = d.k || 'key', m = new Map();
      arr(a).forEach(e => m.set(e[K], e));
      arr(d.r).forEach(k => m.delete(k));
      arr(d.p).forEach(x => m.set(x[0], applyPatch(m.get(x[0]), x[1])));
      let order = d.o;
      if (!order) { order = arr(a).map(e => e[K]).filter(k => m.has(k)); arr(d.n).forEach(e => order.push(e[K])); }
      arr(d.n).forEach(e => m.set(e[K], e));
      return order.map(k => m.get(k));
    }
    const o = Object.assign({}, a);
    arr(d.$r).forEach(k => { delete o[k]; });
    if (d.$s) Object.keys(d.$s).forEach(k => { o[k] = d.$s[k]; });
    if (d.$p) Object.keys(d.$p).forEach(k => { o[k] = applyPatch(o[k], d.$p[k]); });
    if (d.$o) { const x = {}; d.$o.forEach(k => { x[k] = o[k]; }); return x; }
    return o;
  }
  const IDB_WAIT = 5000;
  const idbT = (p, fb) => new Promise(ok => { let done = false; const t = setTimeout(() => { if (!done) { done = true; ok(fb); } }, IDB_WAIT);
    p.then(v => { if (!done) { done = true; clearTimeout(t); ok(v); } }, () => { if (!done) { done = true; clearTimeout(t); ok(fb); } }); });
  const IDB = {
    db: null,
    open() {
      const wait = pr => idbT(pr, null).then(d => { if (!d) throw new Error('저장소 대기 시간 초과'); return d; });
      if (this.db) return wait(this.db);
      const pr = this.db = new Promise((ok, no) => {
        try { const q = indexedDB.open('tj_v2', 1); q.onupgradeneeded = () => q.result.createObjectStore('kv');
          q.onsuccess = () => { const d = q.result; d.onversionchange = () => { try { d.close(); } catch (e) {  } if (IDB.db === pr) IDB.db = null; }; ok(d); };
          q.onerror = () => no(q.error); q.onblocked = () => no(new Error('blocked')); } catch (e) { no(e); }
      });
      idbT(pr.then(() => true), false).then(ok => { if (!ok && this.db === pr) this.db = null; });
      pr.catch(() => { if (this.db === pr) this.db = null; });
      return wait(pr);
    },
    async putKey(key, val) {
      if (S.locked || S.rand) return false;
      try {
        const db = await this.open();
        if (S.rand) return false;
        if (!(await idbT(new Promise((ok, no) => { const t = db.transaction('kv', 'readwrite'); t.objectStore('kv').put(val, key); if (key === 'slim') t.objectStore('kv').delete('state'); t.oncomplete = () => ok(true); t.onerror = () => no(t.error); }), false))) return false;
        if (S.locked) { clearCache(); return false; }
        return true;
      } catch (e) { return false; }
    },
    async del(key) {
      try { const db = await this.open(); await idbT(new Promise(ok => { try { const t = db.transaction('kv', 'readwrite'); t.objectStore('kv').delete(key); t.oncomplete = t.onerror = () => ok(); } catch (e) { ok(); } }), null); }
      catch (e) {  }
    },
    async get(key) {
      try { const db = await this.open(); return await idbT(new Promise(ok => { try { const g = db.transaction('kv').objectStore('kv').get(key); g.onsuccess = () => ok(g.result || null); g.onerror = () => ok(null); } catch (e) { ok(null); } }), null); }
      catch (e) { return null; }
    },
    putState(v, text, parts) {
      if (S.rand) return Promise.resolve(false);
      LS.del('tj_v2_full');
      const P = S.idbParts = { v, need: parts.slice(), have: {}, ok: null };
      P.ok = this.putKey('slim', { v, text, at: Date.now() }).then(ok => { if (ok && S.idbParts === P) { LS.set('tj_v2_ver', v); S.savedAt = Date.now(); if (!parts.length) LS.set('tj_v2_full', '1'); } return ok; });
      return P.ok;
    },
    async putPart(v, name, text) {
      const P = S.idbParts;
      if (S.rand || !P || P.v !== v || !(await P.ok)) return;
      if (S.idbParts === P && await this.putKey('p:' + name, { v, text })) { P.have[name] = 1; if (P.need.every(n => P.have[n]) && LS.get('tj_v2_ver') === v) LS.set('tj_v2_full', '1'); }
    }
  };
  async function clearCache() {
    LS.del('tj_v2_ver'); LS.del('tj_v2_full'); LS.del('tj_v2_todo_hist'); LS.del('tj_v2_srch_recent');
    S.dirty = false; S.savedAt = 0; S.idbParts = null;
    try { const db = IDB.db ? await idbT(IDB.db, null) : null; if (db) db.close(); } catch (e) {  }
    IDB.db = null;
    await new Promise(ok => { try { const r = indexedDB.deleteDatabase('tj_v2'); r.onsuccess = r.onerror = r.onblocked = () => ok(); } catch (e) { ok(); } });
  }
  function lockOut(why) {
    S.locked = true; S.lockWhy = why === 'logoutFail' ? 'logoutFail' : 'logout';
    S.data = null; S.D = null; S.ver = ''; S.cached = false; S.dirty = false; S.parts = null; S.idbParts = null; S.partsFull = false;
    S.feedFull = null; S.dayFull = {}; S.rcpt = null; S.rcptX = {}; S.rcptB = {}; S.rcptE = {}; S.fut = null; S.jLast = null; S.drafts = {};
    if (S.oa) S.oa.d = null;
    S.al = null; if (S.hist) S.hist.days = [];
    S.drawer = null; S.modal = null; S.pop = null; S.err = '401'; S.errCode = 401;
    lockPanels();
    renderLocked();
  }
  function lockPanels() {
    try { const su = window.__tjSetup; if (su && typeof su.lock === 'function') su.lock(); } catch (e) {  }
    try { const h = window.TJHealth; if (h && typeof h.lock === 'function') h.lock(); } catch (e) {  }
    try { const q9 = window.TJSearch; if (q9 && typeof q9.lock === 'function') q9.lock(); } catch (e) {  }
    try { const w9 = window.TJWow; if (w9 && typeof w9.lock === 'function') w9.lock(); } catch (e) {  }
    try { const sl9 = window.TJSale; if (sl9 && typeof sl9.lock === 'function') sl9.lock(); } catch (e) {  }
  }
  async function reopenLocked() {
    let j = null;
    try { const r = await fetch('/api/auth/status', { cache: 'no-store', credentials: 'same-origin' }); j = r.ok ? await r.json() : null; } catch (e) { j = null; }
    if (j && j.ok && !j.enabled) { location.reload(); return; }
    if (j && j.ok && !j.authed) { location.replace('/login'); return; }
    toast(j && j.ok ? '아직 로그아웃되지 않았어요 — 화면은 잠근 채로 둘게요' + (S.lockWhy === 'logoutFail' ? ' · 로그아웃을 다시 시도해 주세요' : ' · 로그아웃이 끝나면 넘어가요') : '로그인 상태를 확인하지 못했어요 — 잠시 뒤 다시 눌러 주세요', true);
  }
  function renderLocked() {
    try { const ae = document.activeElement; if (ae && ae !== document.body && typeof ae.blur === 'function') ae.blur(); } catch (e) {  }
    S.deferred = false;
    try { renderChrome(); } catch (e) {  }
    try { renderView(); } catch (e) {  }
    try { renderOverlay(); } catch (e) {  }
  }
  function toLogin(r) {
    try { if (r && r.status === 401 && r.headers && r.headers.get('X-TJ-Login') && typeof window.__tjToLogin === 'function') { window.__tjToLogin(); return true; } } catch (e) {  }
    return false;
  }
  function onUnauthorized() {
    if (S.locked) return;
    S.locked = true; S.lockWhy = '401';
    clearCache();
    S.data = null; S.D = null; S.ver = ''; S.cached = false; S.err = '401'; S.errCode = 401;
    lockPanels();
    renderLocked();
  }
  (function () {
    const f0 = window.fetch;
    if (!f0) return;
    window.fetch = function (u) {
      return f0.apply(this, arguments).then(r => {
        try { const url = String(u && u.url ? u.url : u); if (r && r.status === 401 && (url[0] === '/' || url.indexOf(location.origin) === 0) && url.indexOf('/api/') >= 0) { toLogin(r); onUnauthorized(); } } catch (e) {  }
        return r;
      });
    };
  })();

  const PART_NEED = { journal: ['ev'], daily: ['ev'], outflows: ['oft'] };
  const partsOf = d => (d && Array.isArray(d.slim)) ? d.slim.filter(n => n === 'ev' || n === 'oft') : [];
  function partsReset(ver, names) {
    const P0 = S.parts;
    const carry = P0 && !P0.done && names.length ? P0 : null;
    const fails = {}; if (carry && carry.fails) names.forEach(n => { if (carry.fails[n]) fails[n] = carry.fails[n]; });
    S.parts = { ver, need: names.slice(), have: {}, busy: {}, q: names.slice(), done: !names.length, t0: carry ? carry.t0 : performance.now(), at: names.length ? 0 : performance.now(), log: [], wait: {}, fails };
    if (P0 && P0.timer) clearTimeout(P0.timer);
  }
  const partHave = n => !S.parts || S.parts.done || !!S.parts.have[n] || S.parts.need.indexOf(n) < 0;
  const partsHaveAll = () => !S.parts || S.parts.done;
  function partsNeed(names, why) {
    const P = S.parts; if (!P || P.done) return true;
    const miss = names.filter(n => !partHave(n));
    if (!miss.length) return true;
    miss.forEach(n => { P.wait[n] = why || 1; P.q = [n].concat(P.q.filter(x => x !== n)); });
    partsPump(true);
    return false;
  }
  function partsPump(urgent) {
    const P = S.parts; if (!P || P.done || S.locked) return;
    const busyN = Object.keys(P.busy).length;
    P.q.filter(n => !P.have[n] && !P.busy[n]).forEach((n, i) => {
      if (P.wait[n] || (busyN === 0 && i === 0)) partFetch(P, n);
    });
  }
  async function partFetch(P, name) {
    P.busy[name] = 1;
    const t0 = performance.now();
    let src = 'net';
    try {
      let text = null;
      if (P.fromIdb && !(P.noIdb && P.noIdb[name])) { const rec = await IDB.get('p:' + name); if (rec && rec.v === P.ver && typeof rec.text === 'string') text = rec.text; }
      src = text != null ? 'idb' : 'net';
      if (text == null) {
        const ac = window.AbortController ? new AbortController() : null;
        const tmo = setTimeout(() => { if (ac) ac.abort(); }, +window.__tjPartTimeout || PART_TIMEOUT);
        try {
          const r = await fetch('/api/v2/part?name=' + name + '&v=' + encodeURIComponent(P.ver), ac ? { cache: 'no-store', signal: ac.signal } : { cache: 'no-store' });
          if (S.parts !== P) { delete P.busy[name]; return; }
          if (r.status === 410 || r.status === 404) { P.log.push([name, 'stale']); delete P.busy[name]; partsFullRecover(); return; }
          if (!r.ok) throw new Error('HTTP ' + r.status);
          text = await r.text();
        } finally { clearTimeout(tmo); }
      }
      const live = () => S.parts === P && P.ver === S.ver && !P.have[name];
      if (!live()) { delete P.busy[name]; return; }
      const tn = performance.now();
      if (!P.wait[name] && window.requestIdleCallback) await new Promise(ok => window.requestIdleCallback(ok, { timeout: 1500 }));
      if (!live()) { delete P.busy[name]; return; }
      const ta = performance.now();
      const obj = JSON.parse(text);
      if (!P.wait[name]) await new Promise(ok => setTimeout(ok, 0));
      if (!live()) { delete P.busy[name]; return; }
      partAttach(name, obj);
      if (src === 'idb' && S.idbParts && S.idbParts.v === P.ver) S.idbParts.have[name] = 1;
      P.have[name] = 1; delete P.busy[name];
      P.log.push([name, src, Math.round(tn - t0), Math.round(performance.now() - ta), text.length]);
      if (src === 'net') IDB.putPart(P.ver, name, text);
      if (P.need.every(n => P.have[n])) { P.done = true; P.at = performance.now(); finishParts(); }
      const waited = !!P.wait[name]; delete P.wait[name];
      if (waited || (PART_NEED[S.tab] || []).indexOf(name) >= 0 || (S.tab === 'dash' && S.partsDash)) { S.partsDash = false; renderView(); }
      partsPump();
    } catch (e) {
      delete P.busy[name];
      P.log.push([name, 'err' + (src === 'idb' ? ':idb' : ''), String(e && e.message || e).slice(0, 80)]);
      if (src === 'idb') { (P.noIdb || (P.noIdb = {}))[name] = 1; LS.del('tj_v2_full'); IDB.del('p:' + name); if (S.parts === P) { P.retryAt = performance.now() + 100; setTimeout(() => partsPump(true), 0); } return; }
      if (S.parts === P && ((P.fails || {})[name] || 0) + 1 >= PART_FAIL_FULL) { delete P.busy[name]; partsFullRecover(); return; }
      if (S.parts === P) { const nf = (P.fails || (P.fails = {}))[name] = (P.fails[name] || 0) + 1, dl = Math.min(60000, 5000 * Math.pow(2, nf - 1));
        P.retryAt = performance.now() + dl + 50; P.timer = setTimeout(() => partsPump(true), dl); }
    }
  }
  function partCheck(name, part, f) {
    const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
    const objs = a => Array.isArray(a) && a.every(e => e && typeof e === 'object');
    if (!part || typeof part !== 'object' || Array.isArray(part)) throw new Error('조각 모양이 아니에요(' + name + ')');
    if (name === 'ev') {
      arr(f.positions).forEach(p => {
        if (!p || typeof p !== 'object' || !('_evc' in p)) return;
        const k = String(p.key), v = part[k];
        if (!own(part, k) || (Array.isArray(v) ? !(v.length === num(p._evc) && objs(v)) : num(p._evc) !== 0)) throw new Error('사이클 기록 조각이 가벼운 상태와 안 맞아요');
      });
    } else if (name === 'oft') {
      arr(f.outflows).forEach(r => {
        if (!r || typeof r !== 'object') return;
        const has = own(part, r.address), e = has ? part[r.address] : null;
        const rc = r.flow && Array.isArray(r.flow.recips) ? r.flow.recips : null;
        const rn = rc ? rc.map(x => x && typeof x === 'object' && '_rtn' in x ? num(x._rtn) : null) : [];
        if (!has) { if ('_txn' in r || rn.some(n => n != null)) throw new Error('전송 목록 조각이 가벼운 상태와 안 맞아요'); return; }
        if (!Array.isArray(e) || e.length !== 2) throw new Error('전송 목록 조각 모양이 아니에요');
        if ('_txn' in r ? !(objs(e[0]) && e[0].length === num(r._txn)) : (e[0] != null && !(Array.isArray(r.txs) && objs(e[0]) && e[0].length === r.txs.length))) throw new Error('전송 목록 조각이 가벼운 상태와 안 맞아요');
        if (e[1] == null) { if (rn.some(n => n != null)) throw new Error('전송 상대 조각이 가벼운 상태와 안 맞아요'); }
        else {
          if (!rc || !Array.isArray(e[1]) || e[1].length !== rc.length) throw new Error('전송 상대 조각이 가벼운 상태와 안 맞아요');
          rc.forEach((x, i) => { const v = e[1][i];
            if (rn[i] != null) { if (!(objs(v) && v.length === rn[i])) throw new Error('전송 상대 조각이 가벼운 상태와 안 맞아요'); }
            else if (v != null && !(x && Array.isArray(x.txs) && objs(v) && v.length === x.txs.length)) throw new Error('전송 상대 조각이 가벼운 상태와 안 맞아요');
          });
        }
      });
    }
  }
  function partAttach(name, part) {
    const d = S.data, f = d && d.fields, D = S.D;
    if (!f) return;
    partCheck(name, part, f);
    if (name === 'ev') {
      arr(f.positions).forEach(p => { if (p && typeof p === 'object' && '_evc' in p) { delete p._evc; delete p._evt; p.events = part[String(p.key)] || []; } });
      if (D) {
        const byKey = new Map(D.positions.map(x => [x.key, x]));
        D.merged.forEach(m => { if (arr(m._legP).length > 1) { m.events = legEvents(m._legP); delete m._evc; delete m._evt; } else if ('_evc' in m) { const raw = byKey.get(m.key); m.events = raw ? arr(raw.events) : []; delete m._evc; delete m._evt; } });
        buildEvents(D, f);
      }
    } else if (name === 'oft') {
      arr(f.outflows).forEach(r => {
        if (!r || typeof r !== 'object' || !part[r.address]) return;
        const e = part[r.address];
        if ('_txn' in r) { delete r._txn; if (e[0] != null) r.txs = e[0]; }
        if (e[1] != null && r.flow && Array.isArray(r.flow.recips)) r.flow.recips.forEach((x, i) => { if (x && typeof x === 'object' && '_rtn' in x) { delete x._rtn; if (e[1][i] != null) x.txs = e[1][i]; } });
      });
      if (D) deriveOF(D, f);
    }
  }
  function finishParts() { if (S.data) delete S.data.slim; }

  function adopt(d, ver, t0, kind) {
    const t1 = performance.now();
    S.data = d; S.ver = ver || S.ver;
    S.D = derive(d);
    S.perf = { kind, parse: t1 - t0, derive: performance.now() - t1 };
    if (kind !== 'cache') { RLW.stateAt = Date.now(); if (RLW.size || arr(S.D && S.D.of).some(x => x.applyWait) || arr(d && d.fields && d.fields.outflows).some(x => x && x.applyWait)) rlFetch(true); else rlFetch(false); }
    if (!S.inited) initFromData();
    else if (kind !== 'cache' && S.bootDay) {
      if (S.day === S.bootDay && S.D.todayKey !== S.bootDay) { S.day = S.D.todayKey; S.calYM = ymOf(S.day) || ymShift(0); }
      S.bootDay = '';
    }
  }
  async function loadResp(r, since) {
    const kind = r.headers.get('X-TJ-Kind') || 'full', ver = r.headers.get('X-TJ-Ver') || '';
    const t0 = performance.now();
    if (kind === 'same') { await r.text(); return (S.data && since === S.ver) ? { kind, ver } : { kind: 'stale' }; }
    if (kind === 'delta') {
      const x = await r.json();
      if (!S.data || x.b !== since || since !== S.ver) return { kind: 'stale' };
      if (!partsHaveAll()) { const ok = await partsFromIdbNow(); if (!ok) return { kind: 'stale' }; }
      if (!S.data || x.b !== since || since !== S.ver) return { kind: 'stale' };
      return { kind, ver: x.v, data: applyPatch(S.data, x.d), t0 };
    }
    const text = await r.text();
    const tp = performance.now();
    return { kind: kind === 'slim' ? 'slim' : 'full', ver, data: JSON.parse(text), text, t0: tp };
  }
  async function partsFromIdbNow() {
    const P = S.parts; if (!P || P.done) return true;
    for (const n of P.need) {
      if (P.have[n]) continue;
      const rec = await IDB.get('p:' + n);
      if (!rec || rec.v !== P.ver || typeof rec.text !== 'string' || S.parts !== P || P.ver !== S.ver) return false;
      if (P.have[n]) continue;
      try { partAttach(n, JSON.parse(rec.text)); }
      catch (e) { LS.del('tj_v2_full'); IDB.del('p:' + n); return false; }
      P.have[n] = 1;
    }
    P.done = true; P.at = performance.now(); finishParts();
    return true;
  }
  const stateUrl = since => S.partsFull ? '/api/v2/state' : '/api/v2/state?slim=1' + (since ? '&since=' + encodeURIComponent(since) + (partsHaveAll() ? '' : '&nd=1') : '');
  const PART_FAIL_FULL = 4;
  function partsFullRecover() {
    if (S.partsFull && S.partsFullLoading) return;
    S.partsFull = true; S.ver = '';
    refresh();
  }
  const PART_POLL_PAUSE = 180000;
  const PART_TIMEOUT = 180000;
  const PART_POLL_CAP = 600000;
  function partsPollHold() {
    const P = S.parts; if (!P || P.done) return false;
    const age = performance.now() - P.t0;
    if (age >= (+window.__tjPollCap || PART_POLL_CAP)) return false;
    return age < (+window.__tjPollPause || PART_POLL_PAUSE) || Object.keys(P.busy).length > 0 || (P.retryAt || 0) > performance.now();
  }
  async function refresh(manual, boot, auto) {
    if (S.locked) return;
    if (auto && S.partsFullLoading && performance.now() - S.partsFullAt < PART_POLL_CAP) return;
    if (auto && !S.partsFull && S.ver && S.parts && !S.parts.done && performance.now() - S.parts.t0 >= (+window.__tjPollCap || PART_POLL_CAP)) { partsFullRecover(); return; }
    if (auto && S.ver && partsPollHold()) { partsPump(); return; }
    if (auto && S.inflight && performance.now() - S.inflight < 60000) return;
    const inT = S.inflight = performance.now();
    const seq = ++S.seq, partsFull = !!S.partsFull;
    if (partsFull) { S.partsFullLoading = seq; S.partsFullAt = performance.now(); boot = null; }
    try {
      let since = S.ver, r;
      if (boot && boot.res && (boot.since || '') === (since || '')) r = await boot.res;
      else r = await fetch(stateUrl(since), { cache: 'no-store' });
      if (r.status === 401) { onUnauthorized(); return; }
      if (r.status === 404) { since = ''; r = await fetch('/api/state', { cache: 'no-store' }); }
      if (r.status === 401) { onUnauthorized(); return; }
      if (!r.ok) throw new Error('HTTP ' + r.status);
      let x = await loadResp(r, since);
      if (seq < S.applied || S.locked) return;
      if (x.kind === 'stale') {
        since = '';
        r = await fetch(stateUrl(''), { cache: 'no-store' });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        x = await loadResp(r, since);
      }
      if (seq < S.applied || S.locked) return;
      S.applied = seq; S.err = null; S.lastOk = Date.now(); S.pulse = true;
      const wasCached = S.cached; S.cached = false;
      const optGone = optSettle(seq);
      if (x.kind === 'same') {
        if (optGone && S.D && S.data) { try { S.D = derive(S.data); } catch (e) { rescue(e, 'derive'); return; } render(); return; }
        if (!S.D) { try { adopt(S.data, S.ver, performance.now(), 'same'); } catch (e) { rescue(e, 'derive'); return; } render(); }
        else { S.perf = { kind: 'same' }; if (wasCached) render(); else renderChrome(); }
        if (S.parts && !S.parts.done) setTimeout(() => partsPump(), 0);
        if (manual) toast('최신 상태를 불러왔어요');
        return;
      }
      if (x.kind === 'slim' || x.kind === 'full' || x.kind === 'delta') partsReset(x.ver || '', x.kind === 'slim' ? partsOf(x.data) : []);
      try { adopt(x.data, x.ver, x.t0, x.kind); } catch (e) { S.data = x.data; S.ver = x.ver || S.ver; rescue(e, 'derive'); return; }
      if (x.kind === 'full') S.partsFull = false;
      if (x.kind === 'slim' || x.kind === 'full') { if (x.ver) IDB.putState(x.ver, x.text, S.parts.need); }
      if (manual) toast('최신 상태를 불러왔어요');
      if (auto) renderAuto(); else render();
      if (S.parts && !S.parts.done) setTimeout(() => partsPump(), 0);
    } catch (e) {
      if (seq < S.applied) return;
      S.err = (e && e.message) || String(e);
      if (!S.D && S.data && S.errCode !== 401) {
        try { S.cached = true; adopt(S.data, S.ver, performance.now(), 'cache'); render(); if (manual) toast('불러오지 못했어요 · 저장된 화면을 보여주는 중', true); return; }
        catch (e2) { S.D = null; S.cached = false; logError('[tj] 저장된 화면 그리기 실패', e2); }
      }
      try { renderChrome(); } catch (e2) { logError('[tj] 상단 그리기 실패', e2); }
      logError('[tj] 불러오기·그리기 실패: ' + S.err, e);
      if (!S.D || !S.viewOk) renderView();
      if (manual) toast('불러오지 못했어요 · 잠시 후 다시 시도해 주세요', true);
    } finally {
      if (partsFull && S.partsFullLoading === seq) S.partsFullLoading = 0;
      if (S.inflight === inT) S.inflight = 0;
    }
  }
  async function bootLoad() {
    const B = window.__tjBoot || {};
    rlFetch(true);
    if (!S.rand && B.idb && B.since) {
      let rec = null;
      try { rec = await B.idb; } catch (e) { rec = null; }
      if (rec && rec.v === B.since && typeof rec.text === 'string' && !S.data) {
        try {
          const t0 = performance.now();
          const d = JSON.parse(rec.text);
          S.ver = rec.v; S.savedAt = rec.at || 0;
          partsReset(rec.v, partsOf(d)); S.parts.fromIdb = true;
          S.idbParts = { v: rec.v, need: S.parts.need.slice(), have: {}, ok: Promise.resolve(true) };
          if (!B.resAt) {
            S.cached = true;
            adopt(d, rec.v, t0, 'cache');
            render();
          } else { S.data = d; }
        } catch (e) { S.ver = ''; S.data = null; S.parts = null; }
      }
    }
    return refresh(false, (B.res && (B.since || '') === (S.ver || '')) ? B : null);
  }
  function initFromData() {
    S.inited = true;
    const ls = LS.get('tj_dust');
    const n = ls != null && ls !== '' ? parseFloat(ls) : NaN;
    if (S.D.hasDust) S.dust = Math.min(Math.max(0, S.D.dustUsd), 1e6);
    else if (!isNaN(n) && n >= 0) S.dust = Math.min(n, 1e6);
    if (!S.day) { S.day = S.D.todayKey; if (S.cached) S.bootDay = S.day; }
    if (!S.calYM) S.calYM = ymOf(S.day) || ymShift(0);
    const lcd = +LS.get('tj_v2_chart_days');
    if (!S.chartUser && CH_RANGES.some(r => r[0] === lcd)) { S.chartDays = lcd; S.chartUser = true; }
    if (!S.chartUser && S.D.daily.length > 7 && S.D.daily.some((x, i) => i > 0 && x.delta != null && Math.abs(x.delta) > 0.2 * Math.abs(S.D.daily[i - 1].val))) S.chartDays = 7;
    if (!S.urlPeriod) { const lp = LS.get('tj_v2_period'); S.g.period = lp && lp !== 'custom' && PERIODS.some(x => x.k === lp) ? lp : 'thismonth'; }
  }

  async function csrf() {
    try { const st = window.__tjSetup && window.__tjSetup.U && window.__tjSetup.U.st; if (st && st.csrf) return st.csrf; } catch (e) {  }
    if (S.csrf) return S.csrf;
    try { const r = await fetch('/api/setup/status', { cache: 'no-store' }); if (r.ok) { const j = await r.json(); S.csrf = (j && j.csrf) || ''; } } catch (e) { S.csrf = ''; }
    return S.csrf || '';
  }
  async function post(path, body, okMsg) {
    const oe = optFor(path, body);
    try {
      const tok = await csrf();
      const hd = { 'Content-Type': 'application/json' };
      if (tok) hd['X-TJ-CSRF'] = tok;
      const r = await fetch(path, { method: 'POST', headers: hd, body: JSON.stringify(body) });
      if (r.status === 401) { optFail(oe); onUnauthorized(); return null; }
      let d = null;
      try { d = await r.json(); } catch (e) { d = null; }
      if (!r.ok || !d || !d.ok) throw new Error((d && d.error) || ('HTTP ' + r.status));
      optOk(oe, d);
      if (okMsg) toast(typeof okMsg === 'function' ? okMsg(d) : okMsg);
      refresh();
      return d;
    } catch (e) {
      optFail(oe);
      toast('저장하지 못했어요 · ' + ((e && e.message) || e), true);
      return null;
    }
  }
  const OPT = { n: 0, list: [] };
  const OPT_ANY = new Set(['/api/cost_override', '/api/risk_override', '/api/genuine_token', '/api/fallback_avg', '/api/first_seen_px', '/api/gas_in_cost', '/api/offchain_self', '/api/dust_threshold',
    '/api/src_whitelist', '/api/wd_dest_register', '/api/flow_register', '/api/review_len', '/api/review_pause', '/api/review_fill']);
  const ofRaw = a => { const f = S.data && S.data.fields; return f ? arr(f.outflows).find(r => r && r.address === a) || null : null; };
  const ofAuto = () => { if (RLW.known) return RLW.auto; const f = S.data && S.data.fields; if (f && f.walletAuto) return true; try { const st = suSt(); return !!(st && st.apply && st.apply.runner); } catch (e) { return false; } };
  function ofPatchOf(r0, dec) {
    const v = dec && dec.verdict && dec.verdict !== 'clear' ? dec.verdict : null, cur = String((r0 && r0.status) || '');
    const p = { verdict: v, category: (dec && dec.category) || null, memo: (dec && dec.memo) || null, alias: (dec && dec.alias) || null, decidedTs: (dec && dec.ts) || null,
      noAuto: !!(dec && dec.noAuto), excludeLegs: arr(dec && dec.excludeLegs).map(x => String(x && typeof x === 'object' ? x.key : x)) };
    if (v === 'external') p.status = 'external';
    else if (v === 'exchange') p.status = cur === 'exchange' ? 'exchange' : 'exchange_applying';
    else if (v === 'own') { p.status = cur === 'own' ? 'own' : 'own_restart_needed'; p.applyWait = p.status === 'own_restart_needed' && ofAuto() && String((r0 && r0.address) || '').indexOf('wd:') !== 0; if (p.applyWait) p._rlOpt = true; }
    if (dec && dec.exchange) p.exchange = dec.exchange;
    const have = new Map(arr(r0 && r0.links).filter(l => l && l.key).map(l => [String(l.key), l]));
    p.links = arr(dec && dec.links).filter(l => l && l.key).map(l => have.get(String(l.key)) || { kind: l.kind, key: String(l.key), sym: l.sym, qty: l.qty, ts: l.ts, where: l.where, tx: l.tx, st: '', usd: null });
    if (v || (dec && dec.ret === false)) p.retOk = false;
    return p;
  }
  function optFor(path, body) {
    try {
      const b = body || {}, out = [];
      if (path === '/api/outflow_resolve' && typeof b.address === 'string' && b.op !== 'salealert') {
        const a = b.address.indexOf('0x') === 0 ? b.address.toLowerCase() : b.address, r0 = ofRaw(a);
        if (r0) {
          const cur = { verdict: r0.verdict || null, category: r0.category || null, memo: r0.memo || null, alias: r0.alias || null, exchange: r0.exchange || null, ts: r0.decidedTs || null,
            noAuto: !!r0.noAuto, links: arr(r0.links), excludeLegs: arr(r0.excludeLegs), ret: !!r0.retOk };
          let dec = Object.assign({}, cur);
          if (b.op === 'memo') dec.memo = String(b.memo || '').trim() || null;
          else if (b.op === 'unlink') dec.links = cur.links.filter(l => String(l.key) !== String(b.key));
          else if (b.op === 'link') { const ks = new Set(cur.links.map(l => String(l.key))); dec.links = cur.links.concat(arr(b.links).filter(x => x && !ks.has(String(x.key))).map(x => ({ kind: x.kind, key: String(x.key) }))); }
          else if (b.op === 'exclude') dec.excludeLegs = cur.excludeLegs.filter(k => k !== String(b.key)).concat([String(b.key)]);
          else if (b.op === 'include') dec.excludeLegs = cur.excludeLegs.filter(k => k !== String(b.key));
          else if (b.op === 'ret') { dec = Object.assign(dec, { verdict: 'clear', ret: !!b.on }); }
          else if (b.verdict) {
            dec = { verdict: b.verdict, category: b.verdict === 'external' ? b.category || null : null, exchange: b.verdict === 'exchange' ? b.exchange || null : null,
              alias: b.verdict === 'own' ? (b.alias || null) : null, memo: 'memo' in b ? (String(b.memo || '').trim() || null) : cur.memo, ts: cur.ts,
              links: b.verdict === 'external' && cur.verdict === 'external' ? cur.links : [], excludeLegs: b.verdict === 'external' && cur.verdict === 'external' ? cur.excludeLegs : [] };
          }
          const p = ofPatchOf(r0, dec);
          if (b.op === 'ret' || b.verdict === 'clear') delete p.status;
          out.push(optAdd('of', a, p));
        }
      } else if (path === '/api/plan' && typeof b.key === 'string') {
        const p = {}; ['target', 'stop', 'memo', 'tags'].forEach(k => { if (k in b) p[k] = b[k]; });
        out.push(optAdd('plan', b.key, p));
      } else if (path === '/api/wallet_alias' && typeof b.address === 'string' && String(b.alias || '').trim()) {
        out.push(optAdd('alias', b.address.indexOf('0x') === 0 ? b.address.toLowerCase() : b.address, { alias: String(b.alias).trim().slice(0, 40) }));
      } else if ((path === '/api/ignore' || path === '/api/ignore_bulk')) {
        arr(path === '/api/ignore' ? [b.key] : b.keys).filter(k => typeof k === 'string' && k).forEach(k => out.push(optAdd('ign', k, {})));
      } else if ((path === '/api/sale_link' || path === '/api/xfer_link') && typeof b.off === 'boolean') {
        out.push(optAdd(path === '/api/sale_link' ? 'sale' : 'xfer', String(path === '/api/sale_link' ? b.lot : b.dep), { off: b.off }));
      } else if (OPT_ANY.has(path)) out.push(optAdd('any', path, {}));
      if (out.length) optRedo(out);
      return out;
    } catch (e) { logError('[tj] 즉시 반영 준비 실패(저장은 계속)', e); return []; }
  }
  function optAdd(kind, key, patch) { const e = { id: ++OPT.n, kind, key: String(key), patch, st: 'send', seq: 0, at: Date.now() }; OPT.list.push(e); return e; }
  function optOk(es, d) {
    if (!es || !es.length) return;
    es.forEach(e => {
      if (e.kind === 'of' && d && typeof d === 'object') {
        if (d.row && d.row.applyWait) { RLW.add(String(e.key)); RLW.pin.set(String(e.key), Date.now()); }
        const r0 = ofRaw(e.key);
        if (d.row && typeof d.row === 'object') { const p = Object.assign({}, d.row); if (p.status == null) delete p.status; if (r0) { const lp = ofPatchOf(r0, d.decision || null); p.links = lp.links; } e.patch = p; }
        else if ('decision' in d && r0) { const keepSt = !('status' in e.patch); e.patch = ofPatchOf(r0, d.decision || null); if (keepSt) delete e.patch.status; }
      }
      e.st = 'ok'; e.seq = S.seq;
    });
    optRedo(es);
  }
  function optFail(es) { if (!es || !es.length) return; const ids = new Set(es.map(e => e.id)); OPT.list = OPT.list.filter(e => !ids.has(e.id)); optRedo(es); }
  function optSettle(seq) {
    const n0 = OPT.list.length;
    OPT.list = OPT.list.filter(e => !(e.st === 'ok' && seq > e.seq));
    return OPT.list.length !== n0;
  }
  const optWaiting = () => OPT.list.length > 0;
  function optRedo(es) {
    if (!S.D || !S.data) return;
    try {
      if (es.every(e => e.kind === 'of' || e.kind === 'any')) { if (es.some(e => e.kind === 'of')) deriveOF(S.D, S.data.fields || {}); }
      else { const t0 = performance.now(); S.D = derive(S.data); S.perf = { kind: 'opt', parse: 0, derive: performance.now() - t0 }; }
      render();
    } catch (e) { logError('[tj] 즉시 반영 그리기 실패', e); }
  }
  const optOf = (kind, key) => { let p = null; for (const e of OPT.list) if (e.kind === kind && e.key === key) p = Object.assign(p || {}, e.patch); return p; };
  const optHas = kind => OPT.list.some(e => e.kind === kind);
  const optLinks = (list, kind, idk) => optHas(kind) ? list.map(x => { const p = x && optOf(kind, String(x[idk])); return p ? Object.assign({}, x, p, { _opt: true }) : x; }) : list;
  function optPlans(D) {
    const P = Object.assign({}, D.plans), M = Object.assign({}, D.memos);
    OPT.list.filter(e => e.kind === 'plan').forEach(e => {
      const k = e.key, p = e.patch, cur = P[k] || {};
      const t = 'target' in p ? (p.target == null || p.target === '' ? 0 : +p.target) : num(cur.target), s = 'stop' in p ? (p.stop == null || p.stop === '' ? 0 : +p.stop) : num(cur.stop);
      const memo = 'memo' in p ? String(p.memo == null ? '' : p.memo) : (M[k] || cur.memo || '');
      if ('memo' in p) { if (memo.trim()) M[k] = memo; else delete M[k]; }
      if (0 < s && s < t && isFinite(t)) P[k] = Object.assign({ src: 'CEX', venue: '감시 중', tags: [] }, cur, { target: t, stop: s, memo, _opt: true }, 'tags' in p ? { tags: arr(p.tags) } : {});
      else if (P[k]) delete P[k];
    });
    D.plans = P; D.memos = M;
  }

  function selInView() {
    try { const sel = window.getSelection(); if (!sel || sel.isCollapsed || !sel.rangeCount) return false; const v = $('#view'); return !!(v && v.contains(sel.getRangeAt(0).commonAncestorContainer)); } catch (e) { return false; }
  }
  function renderAuto() {
    if (selInView() && (!S.selHold || performance.now() - S.selHold < 120000)) {
      if (!S.selHold) S.selHold = performance.now();
      try { renderChrome(); } catch (e) { rescue(e, 'chrome'); }
      return;
    }
    S.selHold = 0; S.autoPaint = true;
    try { render(); } finally { S.autoPaint = false; }
  }
  document.addEventListener('selectionchange', () => { if (S.selHold && !selInView()) { S.selHold = 0; render(); } });
  function render() {
    try { renderChrome(); } catch (e) { rescue(e, 'chrome'); return; }
    const ae = document.activeElement;
    if (ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA' || ae.tagName === 'SELECT') && $('#view').contains(ae)) { S.deferred = true; return; }
    renderView();
  }
  function hmAlign(e) {
    const g = e.querySelector('.hmg'), c = g && g.firstElementChild; if (!c) return;
    g.style.paddingRight = '';
    if (e.scrollWidth <= e.clientWidth + 1) return;
    const cw = c.getBoundingClientRect().width + (parseFloat(getComputedStyle(g).columnGap) || 0); if (!(cw > 0)) return;
    const max = e.scrollWidth - e.clientWidth, gl = g.getBoundingClientRect().left - e.getBoundingClientRect().left + e.scrollLeft, cut = (((max - gl) % cw) + cw) % cw;
    if (cut > 0.5 && cw - cut > 0.5) g.style.paddingRight = (cw - cut).toFixed(2) + 'px';
  }
  function renderView() {
    try { renderViewRaw(); S.viewOk = !!S.D; if (S.rescue) S.rescue.streak = 0; if (S.D && S.rescue && S.rescue.card) S.rescue.card = false; }
    catch (e) { rescue(e, 'render:' + S.tab); }
  }
  const mqLight = (() => { try { return window.matchMedia('(prefers-color-scheme: light)'); } catch (e) { return null; } })();
  const thSys = () => { const t = LS.get('tj_v2_theme'); return t !== 'light' && t !== 'dark'; };
  const themeOf = v => (v === 'light' || v === 'dark' ? v : (mqLight && mqLight.matches ? 'light' : 'dark'));
  if (mqLight && typeof mqLight.addEventListener === 'function') mqLight.addEventListener('change', () => {
    if (!thSys()) return;
    const v = themeOf('system'); document.documentElement.setAttribute('data-theme', v);
    const mt = $('meta[name=theme-color]'); if (mt) mt.setAttribute('content', v === 'light' ? '#F3F4F7' : '#0B0D11');
    if (S.D) render();
  });
  const KEEP_LS = { tj_v2_theme: 1, tj_v2_scheme: 1, tj_v2_hide: 1, tj_v2_rand: 1, tj_v2_nologo: 1, tj_v2_pgsize: 1 };
  function resetPrefs() {
    try {
      const ks = []; for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (k && (k.indexOf('tj_v2_') === 0 || k === 'tj_dust' || k === 'tj_logo_fail') && !KEEP_LS[k]) ks.push(k); }
      ks.forEach(k => LS.del(k));
      const ss = []; for (let i = 0; i < sessionStorage.length; i++) { const k = sessionStorage.key(i); if (k && k.indexOf('tj_v2_') === 0) ss.push(k); }
      ss.forEach(k => { try { sessionStorage.removeItem(k); } catch (e) {  } });
    } catch (e) {  }
  }
  function resetView() {
    S.tab = 'dash'; S.pop = null; S.modal = null; S.drawer = null; S.cur = 'KRW';
    S.g = { period: 'thismonth', from: '', to: '' }; S.src = { mode: 'all', key: '' }; S.chartDays = 30; S.chartUser = false;
    S.j = { view: 'cycles', status: 'all', q: '', sort: 'recent', limit: J_FIRST, open: new Set(), evMore: new Set(), feedLimit: 100, lpGrp: new Set(), grpM: {} };
    S.hold = { mode: 'all', sort: 'value', dir: -1, limit: S.mobile ? 12 : 25, open: new Set(), showDust: false, showZero: false, dense: false };
    S.day = ''; S.calYM = ''; S.drafts = {}; S.justOpened = new Set(); S.anim = { nums: {}, cells: {}, first: true, tab: '' };
    S.set.sec = ''; S.set.sub = ''; S.set.q = ''; S.set.open = new Set();
    try { history.replaceState(null, '', location.pathname + '#dash'); } catch (e) {  }
  }
  function rescue(e, where) {
    const msg = (e && e.message) || String(e);
    logError('[tj] 화면 그리기 실패(' + where + '): ' + msg, e);
    const R = S.rescue || (S.rescue = { n: 0 });
    R.n++; R.msg = msg; R.where = where; R.stack = e && e.stack ? String(e.stack).split('\n').slice(0, 4).join('\n') : '';
    R.streak = (R.streak || 0) + 1;
    if (R.streak < 2 && S.data) {
      try {
        S.pop = null; S.modal = null; S.drawer = null; S.sheet = null;
        if (where === 'derive' || !S.D) { S.D = derive(S.data); if (!S.inited) initFromData(); }
        renderChrome(); renderViewRaw(); S.viewOk = true; R.streak = 0;
        return;
      } catch (e1) {
        const m1 = (e1 && e1.message) || String(e1);
        logError('[tj] 창을 걷고 다시 그리기도 실패: ' + m1, e1);
        R.streak = 2; R.msg = m1; R.where = where + ' → 창 걷고 재시도';
      }
    }
    if (!R.tried && S.data) {
      R.tried = true;
      resetPrefs(); clearCache(); resetView();
      try {
        S.D = derive(S.data); S.inited = false; initFromData();
        renderChrome(); renderViewRaw(); S.viewOk = true; R.recovered = msg;
        toast('화면 설정을 초기화하고 다시 열었어요 · 원인: ' + errTxt(msg).slice(0, 80), true, 7000);
        return;
      } catch (e2) {
        const m2 = (e2 && e2.message) || String(e2);
        logError('[tj] 기본값으로 다시 그리기도 실패: ' + m2, e2);
        R.msg = m2; R.where = where + ' → 기본값 재시도';
      }
    }
    R.card = true;
    try { $('#view').innerHTML = rescueCard(); $('#view').__h = ''; } catch (e3) {  }
  }
  const hideUnknown = () => { try { window.localStorage.getItem('tj_v2_hide'); return false; } catch (e) { return true; } };
  const errTxt = t => (S.hide || S.rand || hideUnknown()) ? String(t == null ? '' : t).replace(/\d[\d,.]*/g, '•••') : String(t == null ? '' : t);
  function logError(msg, e) {
    try {
      if (S.hide || S.rand || hideUnknown()) console.error(errTxt(String(msg) + (e && e.message && String(msg).indexOf(e.message) < 0 ? ' — ' + e.message : '')));
      else console.error(msg, e);
    } catch (x) {  }
  }
  function rescueCard() {
    const R = S.rescue || {};
    return '<div class="card empty" style="margin-top:40px" role="alert"><div class="eic">' + IC.alert + '</div><b>화면을 그리지 못했어요</b>'
      + '<div style="margin:6px 0 16px">이 브라우저에 남은 화면 설정이 맞지 않을 수 있어요. 아래 버튼으로 설정(테마·금액 가리기 제외)과 저장된 화면을 지우고 다시 열 수 있어요.</div>'
      + '<div style="display:flex;gap:8px;justify-content:center;flex-wrap:wrap"><button class="btn pri" data-a="resetPrefs">설정 초기화하고 다시 열기</button><button class="btn" data-a="reloadPage">다시 시도</button></div>'
      + '<details class="errd" style="margin-top:14px;font-size:12.5px" open><summary>오류 내용</summary><div class="cap" style="white-space:pre-wrap;text-align:left">' + esc(errTxt((R.where ? '[' + R.where + '] ' : '') + (R.msg || ''))) + '</div></details></div>';
  }
  function renderViewRaw() {
    const t0 = performance.now();
    S.deferred = false;
    const v = $('#view');
    let html;
    const pw = S.D ? partWait(S.tab) : '';
    if (!S.D) html = S.rescue && S.rescue.card ? rescueCard() : S.err ? errorCard() : skeleton();
    else if (pw) html = pw;
    else if (S.tab === 'journal') html = vJournal();
    else if (S.tab === 'daily') html = vDaily();
    else if (S.tab === 'outflows') html = vOutflows();
    else if (S.tab === 'unmatched') html = vUnmatched();
    else if (S.tab === 'other') html = vOther();
    else if (S.tab === 'settings') html = vSettings();
    else html = vDash();
    if (S.D && !pw && S.tab !== 'settings') { const t9 = TABS.find(t => t.k === S.tab); html = '<h1 class="sr">' + esc(t9 ? t9.ko : '대시보드') + '</h1>' + html; }
    if (S.autoPaint && S.D && html && v.__h === html && S.tab !== 'settings') { renderOverlay(); return; }
    const dpF = dpFocusKey();
    const fk = dpF ? null : focusKey(v);
    const ks = {}; v.querySelectorAll('[data-ks]').forEach(e => { ks[e.getAttribute('data-ks')] = [e.scrollTop, e.scrollLeft]; });
    v.innerHTML = html; v.__h = html;
    v.querySelectorAll('[data-ks]').forEach(e => { const k = ks[e.getAttribute('data-ks')]; if (k) { e.scrollTop = k[0]; e.scrollLeft = k[1]; } });
    v.querySelectorAll('.hmw').forEach(e => { const k9 = ks[e.getAttribute('data-ks')]; hmAlign(e); e.scrollLeft = k9 ? k9[1] : e.scrollWidth; });
    if (fk) focusBack(v, fk);
    v.querySelectorAll('[data-draft]').forEach(el => { const k = el.getAttribute('data-draft'); if (S.drafts[k] != null) el.value = S.drafts[k]; });
    if (window.TJHealth) window.TJHealth.view(S.tab, v);
    if (S.tab === 'settings' && S.D) { try { const su = window.__tjSetup; if (su && typeof su.fill === 'function') su.fill(); } catch (e) { logError('[tj] 연결·키 칸 채우기 실패', e); } sxAfter(); }
    bindChart();
    renderOverlay();
    afterPaint();
    if (dpF) dpRefocus(dpF);
    if (S.perf) S.perf['render_' + S.tab] = performance.now() - t0;
    if (S.D && window.__tjFont) requestAnimationFrame(() => setTimeout(window.__tjFont, 0));
  }
  function focusKey(v) {
    const ae = document.activeElement;
    if (!ae || ae === document.body || !v.contains(ae) || !ae.getAttribute || !(ae.getAttribute('data-a') || ae.getAttribute('data-su')) || /^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName)) return null;
    return { t: ae.tagName, a: ae.getAttribute('data-a'), su: ae.getAttribute('data-su'), v: (ae.getAttribute('data-fv') || ae.getAttribute('data-v')), f: ae.getAttribute('data-f'), k: ae.getAttribute('data-k') };
  }
  function focusBack(v, k) {
    const ae = document.activeElement;
    if (ae && ae !== document.body && v.contains(ae)) return;
    const el = [...v.querySelectorAll(k.t.toLowerCase() + (k.a ? '[data-a="' + k.a + '"]' : '[data-su="' + k.su + '"]'))].find(x => (x.getAttribute('data-fv') || x.getAttribute('data-v')) === k.v && x.getAttribute('data-f') === k.f && x.getAttribute('data-k') === k.k);
    if (el) { try { el.focus({ preventScroll: true }); } catch (e) {  } }
  }
  function subtabEdge() {
    document.querySelectorAll('#view .lpw, #view .cyevw').forEach(st => {
      const edge = () => st.classList.toggle('ovx', st.scrollLeft + st.clientWidth < st.scrollWidth - 1);
      if (!st.__edge) { st.__edge = 1; st.addEventListener('scroll', edge, { passive: true }); }
      edge();
    });
    document.querySelectorAll('#view .subtabs, #view .hscroll, #view .oaflt, #view .total .wowbar').forEach(st => {
      const edge = () => st.classList.toggle('ovx', st.scrollLeft + st.clientWidth < st.scrollWidth - 1);
      const on = st.querySelector('button.on');
      if (on && st.scrollWidth > st.clientWidth + 1) { const r = on.offsetLeft + on.offsetWidth - st.clientWidth + 24; if (r > st.scrollLeft) st.scrollLeft = r; }
      if (!st.__edge) { st.__edge = 1; st.addEventListener('scroll', edge, { passive: true }); }
      edge();
    });
  }
  window.addEventListener('resize', () => requestAnimationFrame(subtabEdge), { passive: true });
  const mqSide = (() => { try { return window.matchMedia('(min-width: 1101px)'); } catch (e) { return null; } })();
  let sideRO = null, sideEl = null, sideTap = 0;
  document.addEventListener('pointerdown', ev => { sideTap = ev.target && ev.target.closest && ev.target.closest('#view .grid2>.side') ? Date.now() : 0; }, { capture: true, passive: true });
  function sideFit() {
    const el = S.tab === 'dash' ? $('#view .grid2>.side') : null;
    if (el !== sideEl) {
      if (sideRO) sideRO.disconnect();
      sideEl = el;
      if (el && window.ResizeObserver) { sideRO = sideRO || new ResizeObserver(() => sideFit()); sideRO.observe(el); }
    }
    if (!el) return;
    const top = parseFloat(getComputedStyle(el).top) || 84;
    const fit = !!(mqSide && mqSide.matches) && el.offsetHeight <= window.innerHeight - top - 16;
    if (fit === el.classList.contains('sfit') && fit === !!S.sideFit) return;
    const y0 = el.getBoundingClientRect().top;
    el.classList.toggle('sfit', fit);
    if (!fit && S.sideFit && Date.now() - sideTap < 2500) { const dy = el.getBoundingClientRect().top - y0; if (Math.abs(dy) > 1) window.scrollBy(0, dy); }
    S.sideFit = fit;
  }
  window.addEventListener('resize', () => requestAnimationFrame(sideFit), { passive: true });
  function afterPaint() {
    fitDayPick();
    fitUvSoon();
    hydrateLogos();
    subtabEdge();
    sideFit();
    if (!S.D) return;
    if (S.hide || S.rand) { const h9 = $('#tjHero'); if (h9) h9.remove(); }
    const A0 = S.anim, first = A0.first || A0.tab !== S.tab;
    const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    document.querySelectorAll('[data-n]').forEach(el => {
      const k = el.getAttribute('data-n'), v = +el.getAttribute('data-v'), fm = el.getAttribute('data-f') || 'm';
      const prev = A0.nums[k];
      A0.nums[k] = v;
      if (first || prev == null || prev === v || S.hide || S.rand || reduce || !isFinite(prev)) return;
      tween(el, prev, v, fm);
      el.classList.add(v > prev ? 'flash-up' : 'flash-down');
    });
    document.querySelectorAll('[data-fl]').forEach(el => {
      const k = el.getAttribute('data-fl'), v = +el.getAttribute('data-v');
      const prev = A0.cells[k];
      A0.cells[k] = v;
      if (first || prev == null || Math.abs(prev - v) < 0.005 || S.hide || S.rand || reduce) return;
      el.classList.add(v > prev ? 'flash-up' : 'flash-down');
    });
    A0.first = false; A0.tab = S.tab;
    S.justOpened.clear();
    if (S.pulse) { S.pulse = false; const d = $('.top .status .dot'); if (d && !reduce) { d.classList.remove('pulse'); void d.offsetWidth; d.classList.add('pulse'); } }
    onScroll();
  }
  const animReset = () => { S.anim.first = true; S.anim.nums = {}; S.anim.cells = {}; };
  const FMT = { m: v => m(v), s: v => m(v, { sign: true }), mc: v => m(v, { compact: true }), sc: v => m(v, { sign: true, compact: true }) };
  function tween(el, a, b, fm) {
    const f = FMT[fm] || FMT.m, t0 = performance.now(), dur = 650;
    const step = t => {
      const p = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - p, 3);
      if (!document.body.contains(el)) return;
      el.textContent = f(a + (b - a) * e);
      if (p < 1) requestAnimationFrame(step); else el.textContent = f(b);
    };
    requestAnimationFrame(step);
  }
  const N = (key, usd, fm, o) => (S.hide || S.rand) ? '<span' + (o ? ' class="' + o + '"' : '') + '>' + (FMT[fm || 'm'] || FMT.m)(usd) + '</span>' : '<span data-n="' + esc(key) + '" data-v="' + (isFinite(usd) ? usd : 0) + '" data-f="' + (fm || 'm') + '"' + (o ? ' class="' + o + '"' : '') + '>' + (FMT[fm || 'm'] || FMT.m)(usd) + '</span>';
  const clps = (key, html) => '<div class="clps' + (S.justOpened.has(key) ? ' in' : '') + '" data-ck="' + esc(key) + '"><div>' + html + '</div></div>';
  function tog(set, key, after) {
    if (set.has(key)) {
      const el = Array.from(document.querySelectorAll('.clps[data-ck]')).find(x => x.getAttribute('data-ck') === key);
      const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      if (el && !reduce) { el.classList.remove('in'); el.classList.add('out'); setTimeout(() => { set.delete(key); (after || renderView)(); }, 170); return; }
      set.delete(key);
    } else { set.add(key); S.justOpened.add(key); }
    (after || renderView)();
  }
  function partWait(tab) {
    const need = PART_NEED[tab];
    if (!need || partsNeed(need, tab)) return '';
    const P = S.parts, lbl = need.indexOf('ev') >= 0 ? '사이클 기록' : '보낸 내역 전송 목록';
    return '<div class="cap" role="status" aria-live="polite" style="margin:2px 0 12px">' + lbl + '을 불러오는 중이에요' + (P && P.log.some(x => x[1] === 'err') ? ' · 연결이 불안정해 다시 시도하는 중' : '') + '</div>' + skeleton();
  }
  function skeleton() {
    const bars = n => Array.from({ length: n }, (_, i) => '<div class="skl" style="width:' + (40 + (i * 37) % 50) + '%;margin:14px 0"></div>').join('');
    if (S.tab === 'journal') return '<div class="skel" style="height:40px;width:60%;border-radius:12px"></div><div class="sum4" style="margin-top:18px"><div class="skel" style="height:104px"></div><div class="skel" style="height:104px"></div><div class="skel" style="height:104px"></div><div class="skel" style="height:104px"></div></div>' + Array.from({ length: 5 }, () => '<div class="skel" style="height:86px;margin-bottom:12px"></div>').join('');
    if (S.tab === 'daily') return '<div class="dgrid"><div class="skel" style="height:560px"></div><div class="skel" style="height:420px"></div></div>';
    if (S.tab === 'settings') return sxWide() ? '<div class="sx sx-wide"><div class="skel" style="height:44px;width:30%;margin-bottom:20px"></div><div class="sx-grid"><div><div class="skel" style="height:150px;margin-bottom:12px"></div><div class="skel" style="height:560px"></div></div><div class="skel" style="height:520px"></div></div></div>'
      : '<div class="sx"><div class="skel" style="height:34px;width:30%;margin:4px 0 14px"></div><div class="skel" style="height:44px;margin-bottom:12px"></div><div class="skel" style="height:150px;margin-bottom:22px"></div><div class="skel" style="height:220px;margin-bottom:22px"></div><div class="skel" style="height:220px"></div></div>';
    if (S.tab === 'unmatched' || S.tab === 'outflows') return '<div class="card" style="padding:20px 24px">' + bars(8) + '</div>';
    if (S.tab === 'other') return '<div class="kpis4"><div class="skel" style="height:112px"></div><div class="skel" style="height:112px"></div><div class="skel" style="height:112px"></div><div class="skel" style="height:112px"></div></div><div class="skel" style="height:420px;margin-top:20px"></div>';
    return '<div class="hero"><div class="card total"><div class="skl" style="width:52px;margin-top:4px"></div><div class="skl" style="width:min(300px,70%);height:50px;margin:10px 0;border-radius:12px"></div><div class="skl" style="width:200px"></div><div class="skel" style="height:220px;border-radius:12px"></div></div>'
      + '<div class="kpis4"><div class="skel" style="height:112px"></div><div class="skel" style="height:112px"></div><div class="skel" style="height:112px"></div><div class="skel" style="height:112px"></div></div>'
      + '<div class="dmid"><div class="skel" style="height:260px"></div><div class="skel" style="height:260px"></div></div></div><div class="skel" style="height:150px;margin-top:20px"></div><div class="skel" style="height:420px;margin-top:20px"></div>';
  }
  function errorCard() {
    if (S.errCode === 401) {
      const lw = S.lockWhy, wait = lw === 'logout', fail = lw === 'logoutFail';
      return '<div class="card empty" style="margin-top:40px"><div class="eic">' + IC.shield + '</div><b>' + (fail ? '로그아웃하지 못했어요' : wait ? '로그아웃하는 중이에요' : '로그인이 필요해요') + '</b>'
        + '<div style="margin:6px 0 16px">' + (fail ? '서버에서 로그인을 끝내지 못했어요 — 이 화면은 잠가 두었고 이 기기의 화면 데이터는 지웠어요. 로그아웃을 다시 시도해 주세요.'
          : wait ? '이 화면은 잠갔어요 — 로그아웃이 끝나면 로그인 화면으로 넘어가요.' : '이 기기에 저장돼 있던 화면 데이터는 지웠어요.') + '</div>'
        + '<div style="display:flex;gap:8px;justify-content:center;flex-wrap:wrap">' + (fail ? '<button class="btn pri" data-a="logoutRetry">로그아웃 다시 시도</button>' : '')
        + '<button class="btn' + (fail ? '' : ' pri') + '" data-a="reopenLocked">다시 열기</button></div></div>';
    }
    return '<div class="card empty" style="margin-top:40px"><div class="eic">' + IC.alert + '</div><b>데이터 서버에 연결하지 못했어요</b>'
      + '<div style="margin:6px 0 16px">잠시 후 다시 시도해 주세요. 계속되면 수집 서버가 켜져 있는지 확인이 필요해요.</div>'
      + '<button class="btn pri" data-a="reload">다시 시도</button><details class="errd" style="margin-top:14px;font-size:12.5px"><summary>자세히</summary>' + esc(errTxt(S.err)) + '</details></div>';
  }
  function scanText(s) {
    const t = String(s || '');
    const m9 = t.match(/(\d+)\s*초\s*전/);
    if (m9) { const n = +m9[1]; return n < 60 ? '방금' : Math.floor(n / 60) + '분 전'; }
    return t.replace(/\s*스캔$/, '') || '수집 대기';
  }
  function statusHTML(short) {
    const D = S.D;
    const age = S.lastOk ? (Date.now() - S.lastOk) / 1000 : 1e9;
    const dc = S.err ? 'e' : (age > POLL_MS * 3 / 1000 ? 'w' : '');
    const scan = S.err ? (S.cached && S.D ? '저장된 화면' + (S.savedAt ? ' · ' + (kstISOAt(S.savedAt) === todayISO() ? fmtTs(S.savedAt / 1000).slice(6) : fmtTs(S.savedAt / 1000)) + ' 기준' : '') + ' · 서버 연결 끊김' : '연결 끊김') : S.cached ? '저장된 화면 · 갱신 중' : (D ? scanText(D.lastScan) + ' 수집' : '불러오는 중');
    const opt = optWaiting() ? '<span class="pill w sm optp" style="margin-left:6px" title="저장했어요 · 서버가 다시 계산하면 총자산·손익도 새 값으로 바뀌어요">반영 중</span>' : '';
    if (short) return '<span class="dot ' + dc + '" title="' + esc(scan) + '"></span>' + opt;
    return '<span class="dot ' + dc + '"' + (D ? ' title="' + esc(scan) + '"' : '') + '></span><span class="scan">' + esc(scan) + '</span>' + opt
      + (D ? '<span class="scanmeta pvx">· 지갑 ' + D.wallets.length + ' · 거래소 ' + D.exN + '</span>'
        + '<span class="fx num" title="업비트 USDT 매도호가 · 김프">USDT ₩' + nf('ko-KR').format(D.rate) + (D.rateSrc === 'fallback' ? '' : ' · 김프 <b style="color:' + kimpCol(D.kimp) + '">' + pctS(D.kimp, 2) + '</b>' + kimpChip(D.kimp)) + fxNote(D) + '</span>' : '');
  }
  function tabBadge(k) {
    const D = S.D;
    if (!D) return '';
    if (k === 'unmatched' && D.pendN) return '<span class="badge" title="' + esc('확인할 것 ' + D.pendN + '개 = ' + pendSplitTxt()) + '">' + D.pendN + '</span>';
    if (k === 'outflows' && D.ofPendN) return '<span class="badge">' + D.ofPendN + '</span>';
    return '';
  }
  function mDispHTML() {
    const krw = S.cur === 'KRW';
    return '<button class="iconbtn mdisp' + (S.rand ? ' on' : '') + '" data-a="mDisp" aria-haspopup="dialog" aria-label="표시 — 기준 통화(지금 ' + (krw ? '원화' : '달러') + ')' + (S.rand ? ' · 랜덤값 켜짐' : '') + '">'
      + (S.rand ? IC.dice : '<b class="mcur">' + (krw ? '₩' : '$') + '</b>') + '</button>';
  }
  UI_SHEETS.mdisp = () => {
    const krw = S.cur === 'KRW', sw = on => '<span class="sw2 sm' + (on ? ' on' : '') + '" aria-hidden="true"></span>';
    return '<div class="mdp">'
      + '<button type="button" class="opt" data-a="curToggle"><span>기준 통화</span><span class="sp"></span><b class="num">' + (krw ? '원화 ₩' : '달러 $') + '</b></button>'
      + '<button type="button" class="opt" data-a="randToggle" aria-pressed="' + S.rand + '">' + IC.dice + '<span>금액 랜덤값</span><span class="sp"></span>' + sw(S.rand) + '</button>'
      + '<button type="button" class="opt" data-a="mDispGo"><span>표시 설정 더 보기</span><span class="sp"></span>' + IC.right + '</button></div>';
  };
  function ledgerBnrHTML() {
    let hs = null;
    try { const T9 = window.TJHealth; hs = T9 && typeof T9.summary === 'function' ? T9.summary() : null; } catch (e) { hs = null; }
    const D = S.D, lw = (hs && hs.ledger) || (D && D.health && D.health.ledger) || null;
    const cmd = t => '<span class="mono" style="overflow-wrap:anywhere;color:var(--text)">' + esc(t) + '</span>';
    let b = '';
    if (lw && lw.title) b += '<div class="bnr e pvx" role="alert"><div><b>' + esc(String(lw.title)) + '</b> — ' + esc(String(lw.detail || ''))
      + '<details><summary>되돌리는 법</summary>' + cmd(String(lw.action || '')) + '</details></div></div>';
    if ((hs && hs.monitorOff) || (D && D.health && D.health.monitorOff)) b += '<div class="bnr w pvx" role="status"><div><b>감시 유닛(tj-alert)이 꺼져 있어요</b> — 원장·백업·수집이 멈춰도 화면·텔레그램으로 알려 주지 못해요'
      + '<details><summary>켜는 법</summary>' + cmd('pm2 start tj-alert') + ' · pm2 없이: ' + cmd('python3 src/alert_bot.py') + '</details></div></div>';
    return b;
  }
  const ledgerBnrSig = () => { try { const T9 = window.TJHealth, h9 = T9 && typeof T9.summary === 'function' ? T9.summary() : null; return JSON.stringify([h9 && h9.ledger, h9 && h9.monitorOff]); } catch (e) { return ''; } };
  function renderChrome() {
    const D = S.D;
    $('#tabs').innerHTML = TABS.map(t => '<a class="tab' + (S.tab === t.k ? ' on' : '') + '" href="#' + t.k + '"' + (S.tab === t.k ? ' aria-current="page"' : '') + '>' + t.label + tabBadge(t.k) + '</a>').join('');
    { const tb = $('#tabs'), on = tb && $('.tab.on', tb);
      if (on && tb.scrollWidth > tb.clientWidth + 1) { const r = on.getBoundingClientRect(), R = tb.getBoundingClientRect(); if (r.left < R.left || r.right > R.right) tb.scrollLeft += (r.left + r.right) / 2 - (R.left + R.right) / 2; } }
    $('#status').innerHTML = statusHTML(false);
    $('#curSeg').innerHTML = ['KRW', 'USD'].map(c => '<button data-a="cur" data-v="' + c + '" class="' + (S.cur === c ? 'on' : '') + '" aria-pressed="' + (S.cur === c) + '">' + (c === 'KRW' ? '원화' : '달러') + '</button>').join('');
    const light = document.documentElement.getAttribute('data-theme') === 'light';
    $('#themeBtn').innerHTML = light ? IC.moon : IC.sun;
    { const hb = $('#hideBtn'); if (hb) { hb.innerHTML = S.hide ? IC.eyeoff : IC.eye; hb.classList.toggle('on', S.hide); hb.setAttribute('aria-pressed', String(S.hide));
      hb.setAttribute('aria-label', S.hide ? '금액 보이기' : '금액 가리기'); hb.setAttribute('title', (S.hide ? '금액 보이기' : '금액 가리기') + ' (Shift+H)'); } }
    { const rb = $('#randBtn'); if (rb) { rb.innerHTML = IC.dice; rb.classList.toggle('on', S.rand); rb.setAttribute('aria-pressed', String(S.rand)); rb.setAttribute('aria-label', '금액 랜덤값'); rb.setAttribute('title', S.rand ? '금액 랜덤값 끄기' : '금액 랜덤값'); } }
    $('#themeBtn').setAttribute('title', light ? '다크 테마로' : '라이트 테마로');
    const tdisc = D && (D._todayStep || D._todaySplit);
    const tot = D ? '<div class="mtot num"><b>' + m(D.total, { compact: true }) + '</b>' + (D._today != null ? '<span class="' + (tdisc ? 'mut' : cls(todayD())) + '"' + (tdisc || D._todayAp ? ' title="' + esc((tdisc ? (D._todayFlow != null ? flowTip(D._todayFlow, D._todayFlowTop) : '입출금 포함') : '') + (D._todayAp ? ' · 전일 마감이 근사(≈)' : '')) + '"' : '') + '>오늘 ' + (D._todayAp ? '≈ ' : '') + m(todayD(), { sign: true, compact: true }) + '</span>' : '') + '</div>' : '';
    $('#mtop').innerHTML = '<a class="logo" href="#dash" aria-label="온체인 매매일지 — 대시보드"><span class="lmark">' + '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 4v16M12 3v18M18 6v12"/><rect x="4" y="8" width="4" height="7" rx="1" fill="currentColor"/><rect x="10" y="6" width="4" height="9" rx="1" fill="currentColor"/><rect x="16" y="9" width="4" height="6" rx="1" fill="currentColor"/></svg></span><span class="ltx"><span class="lw1">온체인 </span>매매일지</span></a>'
      + tot + '<span class="sp"></span>' + (window.TJHealth ? '' : statusHTML(true))
      + '<button class="iconbtn hideb' + (S.hide ? ' on' : '') + '" data-a="hideToggle" aria-pressed="' + S.hide + '" aria-label="' + (S.hide ? '금액 보이기' : '금액 가리기') + '">' + (S.hide ? IC.eyeoff : IC.eye) + '</button>'
      + mDispHTML()
      + '<a class="iconbtn" href="#settings" aria-label="설정"' + (S.tab === 'settings' ? ' aria-current="page" style="color:var(--text);border-color:var(--line2)"' : '') + '>' + IC.gear + '</a>';
    $('#tabbar').innerHTML = TABS.filter(t => t.k !== 'settings').map(t => '<a href="#' + t.k + '" class="' + (S.tab === t.k ? 'on' : '') + '"' + (S.tab === t.k ? ' aria-current="page"' : '') + '>' + IC.tab[t.k] + t.short + tabBadge(t.k) + '</a>').join('');
    let b = '';
    if (S.err && S.D && S.errCode !== 401) b += '<div class="bnr e"><div><b>서버와 연결이 끊겼어요</b> — ' + (S.lastOk ? fmtTs(S.lastOk / 1000).slice(6) + ' 에 받은 값을 보여주는 중' : S.cached ? '이 기기에 저장된 마지막 화면' + (S.savedAt ? '(' + fmtTs(S.savedAt / 1000) + ')' : '') + '을 보여주는 중' : '') + '<details><summary>자세히</summary>' + esc(errTxt(S.err)) + '</details></div><button class="btn sm" data-a="reload">다시 시도</button></div>';
    b += ledgerBnrHTML();
    const fsN = D && D.firstSeen;
    if (fsN && fsN.on && fsN.eff !== false && !fsN.note && !S.fsNoteX && num(fsN.n) > 0) b += '<div class="bnr w pvx" role="status"><div><b>원가 모르는 ' + nf('ko-KR').format(num(fsN.n)) + '건을 최초 인식 시가로 추정했어요</b> — 설정에서 끌 수 있어요<div class="bd">원가를 모르던 수량의 원가를 그 수량이 장부에 처음 생긴 날 시가로 잡아 손익·명세에 넣었어요(\'추정\' 표시)</div></div><a class="btn sm" href="#settings/cost">설정</a><button class="btn sm" data-a="fsNoteX">닫기</button></div>';
    $('#banners').innerHTML = b;
    $('#bf').innerHTML = window.TJHealth ? '' : bfHTML(D && D.backfill);
    bfPad();
    if (window.TJHealth) window.TJHealth.chrome(S.mobile);
    fitTop();
    fitStatus();
    fitLogo();
  }
  function bfHTML(bp) {
    if (!bp) return '';
    const pc = Math.max(0, Math.min(100, num(bp.pct))), jobs = arr(bp.jobs);
    const stl = jobs.length && jobs.every(j => j && j.stalled);
    const st = stl ? '<b class="mut num">멈춤</b>' : '<b class="wtxt num">' + pc + '%</b>';
    if (S.bfMin) return '<button class="bfpill min pvx" data-a="bfMin" aria-expanded="false" title="' + esc(jobs.map(j => j.text).join('\n') || bp.detail || '') + '"><i class="bfdot' + (stl ? ' s' : '') + '"></i>과거 거래 불러오는 중 ' + st + '</button>';
    const lines = jobs.length
      ? jobs.slice(0, 4).map(j => '<div class="bfj"><b>' + esc(j.chain) + '</b> · ' + esc(j.what) + (j.prog || j.via || j.eta || j.stalled ? ' <span class="' + (j.stalled ? 'wtxt' : 'mut') + '">— ' + esc([j.prog, j.stalled ? '멈춤(마지막 진행 ' + (j.last || '?') + ')' : j.eta, j.stalled ? '' : j.via].filter(Boolean).join(' · ')) + '</span>' : '') + '</div>').join('')
        + (jobs.length > 4 ? '<div class="mut">외 ' + (jobs.length - 4) + '건</div>' : '')
      : '<div>' + esc(bp.detail) + '</div>' + (bp.active ? '<div class="mut">' + esc(bp.active) + '</div>' : '');
    return '<div class="bfpill pvx" role="status"><div class="row"><b style="color:var(--text)">과거 거래 불러오는 중</b><span class="sp"></span>' + st
      + '<button class="iconbtn bfx" data-a="bfMin" aria-expanded="true" aria-label="알림 접기" title="접기 — 이 탭을 닫을 때까지 작게">' + IC.chev + '</button></div>'
      + '<div class="mini" style="margin:6px 0"><i style="width:' + pc + '%;background:var(' + (stl ? '--muted' : '--warn') + ')"></i></div>'
      + lines + (bp.remain ? '<div class="wtxt">' + esc(bp.remain) + '</div>' : '') + '</div>';
  }
  function bfInfo() {
    const bp = S.D && S.D.backfill;
    if (!bp) return null;
    const pc = Math.max(0, Math.min(100, Math.round(num(bp.pct)))), jobs = arr(bp.jobs);
    const stl = !!(jobs.length && jobs.every(j => j && j.stalled));
    const lines = jobs.length
      ? jobs.map(j => '<div class="j"><b>' + esc(j.chain) + '</b> · ' + esc(j.what) + (j.prog || j.via || j.eta || j.stalled ? ' <span class="' + (j.stalled ? 'wtxt' : 'mut') + '">— ' + esc([j.prog, j.stalled ? '멈춤(마지막 진행 ' + (j.last || '?') + ')' : j.eta, j.stalled ? '' : j.via].filter(Boolean).join(' · ')) + '</span>' : '') + '</div>').join('')
      : '<div class="j">' + esc(bp.detail) + '</div>' + (bp.active ? '<div class="mut">' + esc(bp.active) + '</div>' : '');
    return { pct: pc, stalled: stl, n: jobs.length, html: '<div class="tjh-bfb pvx"><div class="bar' + (stl ? ' st' : '') + '"><i style="width:' + Math.max(2, pc) + '%"></i></div>' + lines + (bp.remain ? '<div class="wtxt">' + esc(bp.remain) + '</div>' : '') + '</div>' };
  }
  function bfPad() {
    const el = $('#bf') && $('#bf').firstElementChild;
    try { document.documentElement.style.setProperty('--bfh', el ? Math.ceil(el.getBoundingClientRect().height + 12) + 'px' : '0px'); } catch (e) {  }
  }
  function fitStatus() {
    const st = $('#status');
    if (!st) return;
    st.classList.remove('fit0', 'fit1', 'fit2');
    const over = () => {
      if (!st.clientWidth) return false;
      const gap = parseFloat(getComputedStyle(st).columnGap) || 0;
      let w = 0, n = 0;
      for (const k of st.children) { const bw = k.getBoundingClientRect().width; if (bw > 0) { w += bw; n++; } }
      return w + Math.max(0, n - 1) * gap > st.clientWidth + 0.5;
    };
    let f = 0;
    for (const c of ['fit0', 'fit1', 'fit2']) { if (!over()) break; st.classList.add(c); f++; }
    if (f) st.title = Array.from(st.children).map(k => Array.from(k.childNodes).map(n => n.textContent).join(' ').replace(/\s+/g, ' ').replace(/^·\s*/, '').trim()).filter(Boolean).join(' · ');
    else st.removeAttribute('title');
  }
  if (window.ResizeObserver && $('#status')) new ResizeObserver(() => fitStatus()).observe($('#status'));
  const HK = ['hk1', 'hk2', 'hk3', 'hk4'];
  let hkKey = '';
  function fitTop() {
    const de = document.documentElement, top = $('header.top'), inn = top && $('.in', top), tb = $('#tabs'), st = $('#status');
    if (!inn || !tb) return;
    const keyOf = () => innerWidth + '|' + tb.scrollWidth + '|' + Array.from(inn.children).filter(c => c !== st && c !== tb).map(c => c.offsetWidth).join(',') + '|' + HK.map(c => de.classList.contains(c) ? 1 : 0).join('');
    if (!inn.offsetWidth) { if (HK.some(c => de.classList.contains(c))) { HK.forEach(c => de.classList.remove(c)); de.style.removeProperty('--toph'); } hkKey = ''; return; }
    if (hkKey && keyOf() === hkKey) return;
    HK.forEach(c => de.classList.remove(c));
    const over = () => tb.scrollWidth > tb.clientWidth + 1 || (!!st && st.getBoundingClientRect().width < 16);
    for (let i = 0; i < 3 && over(); i++) de.classList.add(HK[i]);
    if (de.classList.contains('hk3') && st && st.getBoundingClientRect().width < 16) de.classList.add('hk4');
    if (de.classList.contains('hk3')) de.style.setProperty('--toph', Math.ceil(top.getBoundingClientRect().height) + 'px'); else de.style.removeProperty('--toph');
    hkKey = keyOf();
    if (tb.scrollWidth > tb.clientWidth + 1) { const on = $('.tab.on', tb); if (on) { const r = on.getBoundingClientRect(), R = tb.getBoundingClientRect(); if (r.left < R.left || r.right > R.right) tb.scrollLeft += (r.left + r.right) / 2 - (R.left + R.right) / 2; } }
  }
  { let hkRaf = 0; const re = () => { cancelAnimationFrame(hkRaf); hkRaf = requestAnimationFrame(() => { try { fitTop(); } catch (e) {  } }); };
    window.addEventListener('resize', re, { passive: true });
    try { if (document.fonts && document.fonts.addEventListener) document.fonts.addEventListener('loadingdone', () => { hkKey = ''; re(); }); } catch (e) {  }
    const inn = $('header.top .in');
    if (inn && window.ResizeObserver) { const ro = new ResizeObserver(re); const obs = () => Array.from(inn.children).forEach(c => { if (c.id !== 'status') ro.observe(c); }); obs(); if (window.MutationObserver) new MutationObserver(obs).observe(inn, { childList: true }); } }
  const logoRO = window.ResizeObserver ? new ResizeObserver(() => fitLogo(true)) : null;
  function fitLogo(fromRO) {
    const top = $('#mtop'), lg = top && top.querySelector('.logo'), t = lg && lg.querySelector('.ltx');
    { const mt9 = top && top.querySelector('.mtot'), sp9 = top && top.querySelector(':scope > .sp'), b9 = sp9 && sp9.nextElementSibling;
      if (mt9 && b9 && top.clientWidth) mt9.style.right = Math.max(0, top.clientWidth - b9.offsetLeft + 8) + 'px'; }
    if (!t) return;
    lg.classList.remove('lt0');
    if (S.mobile && t.scrollWidth > t.clientWidth + 1) lg.classList.add('lt0');
    if (logoRO && !fromRO) { logoRO.disconnect(); const sp = top.querySelector(':scope > .sp'); if (sp) logoRO.observe(sp); }
  }
  { const tb = $('#tabs'); if (tb) { const edge = () => tb.classList.toggle('ovx', tb.scrollLeft + tb.clientWidth < tb.scrollWidth - 1);
    tb.addEventListener('scroll', edge, { passive: true }); if (window.ResizeObserver) new ResizeObserver(edge).observe(tb); if (window.MutationObserver) new MutationObserver(edge).observe(tb, { childList: true }); } }
  let scT = 0;
  function onScroll() {
    cancelAnimationFrame(scT);
    scT = requestAnimationFrame(() => {
      const y = window.scrollY || 0;
      document.body.classList.toggle('sb', y > 6);
      const big = S.tab === 'dash' && S.mobile ? $('#heroBig') : null;
      document.body.classList.toggle('scrolled', !!big && big.getBoundingClientRect().bottom < 56);
    });
  }
  window.addEventListener('scroll', onScroll, { passive: true });

  const {
    attBars, attCore, attdActs, attdPurge, attItems, attLine, attOf, BENCH_K, benchLoad, benchSet, bindChart, exKey, exLinked, flowSplit, flowTip,
    fsKchip, futSym, gMatch, habitsHTML, habLoad, heroNums, histLoad, holdPgHit, holdRows, lpDetail, lpIcon, lpStatePill, monthRealized, ONB_X,
    onbHidden, onbState, pendSplitTxt, planOfGroup, preData, pxr, sparkSVG, SUB_SFX, todayD, upnlH, vDash, venueDrawer, venueOpen, vnModel, vnSrc,
    __late: tjLate_dash
  } = tjTab('dash', {
    $, ago, arr, bfInfo, CH_RANGES, CHAIN_KEY, clps, cls, clsP, clsV, dayCnt, dayFlowV, dayFull, dayV, DOWS, drawerHist, eok, esc, evA, evQ, evXf,
    EX_BY_KO, EX_NAMES, exLogo, fmtTs, futFxNote, hq, hs, IC, icon, impChip, isDex, isISO, isoDay, isYMD, isZ, krw, KS, KV, LS, m, mN, N, nbDot, nf,
    num, onUnauthorized, openDay, pad2, pAgg, partHave, partsNeed, PCAT_ORDER, PCATS, pctS, plPx, prTxt, PVM, pvm, pvW, px, pxC, pxSrcTxt, q, rate,
    rbChip, renderAuto, renderOverlay, renderView, retPct, revealAndHighlight, rw, S, scanText, short, staleChip, sum, toast, todayISO, trimZeros,
    UI_SHEETS, uiCell, uiFold, uiPaged, uiPgBar, uiPgS, uiPgSlice, uiPgSz, uiSheetCloseThen, uiSheetOpen, venueLogo, wowSlot, ymOf, ymShift
  });

  const {
    evPill, jBase, jList, krwDayHTML, lpGroupItems, optCk, plainT, popBox, px4, searchBox, srcBtn, taxTip, vJournal, __late: tjLate_jrnl
  } = tjTab('jrnl', {
    ageTxt, arr, attOf, AUSD, cardReal, cardRealV, chainBadge, clps, cls, clsP, clsV, DOWS, eok, esc, evA, evDH, evDT, evNm, evQ, evSkel, EX_NAMES,
    EX_ORDER, exLogo, feedFull, feedMoreLoad, fsKchip, gBounds, gMatch, gPass, gRange, habitsHTML, IC, icon, impChip, isAirQ, isISO, isoDay, isZ,
    J_SORTS, jo, krw, KRW_BASIS, KS, KV, lpDetail, lpIcon, lpNm, lpNmHTML, lpStatePill, m, mCell, mCellF, mdOf, mN, mvDest, N, nf, num,
    onUnauthorized, pad2, pAgg, parseMoney, pctS, periodName, PERIODS, perMonthAligned, plCur, plCY, plPx, plQ, plSnap, prTxt, PVM, pvOn, pvW, px,
    pxC, pxr, q, rate, renderView, rfrTag, rollMinISO, rw, S, short, srcAgg, srcPass, sum, taxNmHTML, term, todayISO, UI_CHEV, UI_SHEETS, uiCell,
    uiFold, uiHidChip, uiOpen, uiPaged, uiPgBar, uiPgReset, uiPgSlice, venueLogo, wowSlot, ymOf, ymPass
  });
  tjLate_dash({ evPill });

  const {
    apOf, dayContrib, dayPickKey, DM_MAX, dmCoins, dmGet, dmInput, dmRcptHTML, dmSwapKeepForm, dmSym, dpFade, dpFilter, dpFocusKey, dpRefocus, feeRef,
    fitDayPick, groupDayEvs, isAI, isoAdd, monthAtt, monthBarRows, payChip, rcptable, realDays, vDaily, wkOff, wkSelNow, __late: tjLate_daily
  } = tjTab('daily', {
    $, arr, attBars, attCore, attLine, attOf, CAL_DOT_USD, calTint, cls, clsV, dayCnt, dayFlowV, dayFull, dayV, dayWait, DOWS, esc, evA, evAK, evDH,
    evDT, evNm, evPill, evQ, evSkel, evXf, EX_NAMES, flowSplit, flowTip, hs, IC, icon, impChip, isISO, isoDay, isYMD, isZ, kimpChip, kimpCol,
    krwDayHTML, KV, lpNm, lpNmHTML, LS, m, mcal, mN, monthRealized, nf, num, optCk, pad2, parseMoney, pctS, plainT, popBox, prTxt, PVM, pvMoney, pvOn,
    pvW, q, rate, revTxt, rfrTag, rollMinISO, S, short, srcBtn, srcPass, sum, term, todayD, todayISO, UI_SHEETS, uiFold, uiPaged, uiPgBar, uiPgSlice,
    ymOf, ymShift
  });
  tjLate_dash({ apOf, dayContrib, feeRef, groupDayEvs, isoAdd, monthAtt, monthBarRows, realDays });
  tjLate_jrnl({ payChip });

  const {
    D0, EXPL, exUrl, mAlt, ofCatLbl, ofLkInput, ofLkLoad, ofLkOpt, ofName, saleBox, trChip, vOutflows, vUnmatched, xferBox, __late: tjLate_out
  } = tjTab('out', {
    $, ago, AI_HIDE, arr, CHAIN_KO, clps, cls, errTxt, esc, evSkel, EX_NAMES, EX_ORDER, exLogo, fmtTs, hs, IC, icon, impChip, KST_MS, m, mN, nf, num,
    ofAuto, ofNetV, ofTraced, onUnauthorized, pad2, PCAT_ORDER, PCATS, pendSplitTxt, plainT, preData, prTxt, PVM, pvOn, pvW, px, q, renderView, rw, S,
    searchBox, short, shortL, spamNm, sum, UI_CHEV, uiCell, uiHidChip, uiOpen, uiPaged, uiPick, URL_NM, ymShift
  });
  tjLate_dash({ EXPL, mAlt, trChip });
  tjLate_jrnl({ saleBox, xferBox });
  tjLate_daily({ mAlt });

  const {
    alD, alOn, alTier, authLoad, authLogout, authPwSave, copyBtn, Finder, gasRuleTxt, legacyOn, locH, locMask, locName, locNameM, mqW, netOk, nmKey,
    offcAsk, offcGroup, ownAttrs, ownH, ownIn, ownNm, ownScrub, ownScrubM, ownSeg, pvNameRe, REV_FILL, REV_LEN, rpDur, suSt, suU, sxAfter, sxGo,
    sxHash, SXI, sxId, sxIndex, sxIt, sxKeys, sxParse, sxPick, sxPill, sxRoute, sxSearchPaint, sxSeg, sxSig, sxSlotWait, sxSw, sxWalHay, sxWalRows,
    sxWide, unmarkNewWallet, vSettings, __late: tjLate_set
  } = tjTab('set', {
    $, ago, alLoad, arr, CHAIN_KO, clearCache, DUST_OPTS, errTxt, esc, EX_NAMES, exLogo, fmtTs, fxNote, hs, IC, isISO, KST_MS, lockOut, logError,
    logosOff, LS, m, MK_RE, mN, nf, num, ofAuto, onbHidden, onUnauthorized, pad2, pctS, plainT, prTxt, PV_PROT, PVM, pvm, pvOn, pvW, px, q, render,
    renderView, revTxt, rkFix, S, scanText, short, sum, sv, sxAlertsBody, syncUrl, taxTip, thSys, toast, uiDate, uiFold, uiPaged, uiPageSize, uiPgBar,
    uiPgReveal, uiPgS, uiPgSlice, uiPick, venueLogo
  });
  tjLate_dash({ copyBtn, locH, locName, nmKey, suSt, sxKeys });
  tjLate_jrnl({ gasRuleTxt, locH, ownH, ownNm });
  tjLate_out({ locH, locNameM, offcAsk, offcGroup, ownH, ownScrubM, SXI });

  let ovIme = null, ovIdle = false;
  document.addEventListener('compositionstart', ev => { const o = $('#overlay'); ovIme = o && ev.target && o.contains(ev.target) ? ev.target : null; }, true);
  document.addEventListener('compositionend', () => { if (!ovIme) return; ovIme = null; if (ovIdle) { ovIdle = false; renderOverlay(); } }, true);
  let ovErrLast = '';
  function ovErrHTML(e, where, sheet) {
    const msg = (e && e.message) || String(e);
    if (ovErrLast !== where + msg) { ovErrLast = where + msg; logError('[tj] 창 그리기 실패(' + where + '): ' + msg, e); }
    const ic = k => { try { return IC[k] || ''; } catch (e9) { return ''; } };
    const cl = sheet ? 'uiSheetClose' : 'drawerClose', x = '<button type="button" class="iconbtn" data-a="' + cl + '" aria-label="닫기">' + (ic('close') || '×') + '</button>';
    const body = '<div class="empty" role="alert"><div class="eic">' + ic('alert') + '</div><b>이 창을 그리지 못했어요</b><div style="margin:6px 0 14px">화면 설정은 그대로예요 — 닫고 다시 열어 보세요. 계속되면 새로고침해 주세요.</div>'
      + '<button type="button" class="btn" data-a="' + cl + '">닫기</button>'
      + '<details class="errd" style="margin-top:14px;font-size:12.5px"><summary>오류 내용</summary><div class="cap" style="white-space:pre-wrap;text-align:left">' + esc(errTxt('[' + where + '] ' + msg)) + '</div></details></div>';
    return sheet
      ? '<div class="usheet-bg" data-a="uiSheetClose"></div><div class="usheet" role="dialog" aria-modal="true" aria-label="창을 열지 못했어요"><div class="ush dh"><h4>창을 열지 못했어요</h4><span class="sp"></span>' + x + '</div><div class="usb">' + body + '</div></div>'
      : '<div class="drawer-bg" data-a="drawerClose"></div><aside class="drawer" role="dialog" aria-modal="true" aria-label="창을 열지 못했어요"><div class="dh"><h2 class="h2">창을 열지 못했어요</h2><span class="sp"></span>' + x + '</div>' + body + '</aside>';
  }
  const ovPath = (root, el) => { const p = []; for (let n = el; n && n !== root; n = n.parentElement) { const par = n.parentElement; if (!par) return null; p.unshift(Array.prototype.indexOf.call(par.children, n)); } return { p, tag: el.tagName, cls: String(el.className || ''), ks: el.getAttribute && el.getAttribute('data-ks') }; };
  const ovAt = (root, fp) => {
    if (fp.ks) { const k = root.querySelector('[data-ks="' + (window.CSS && CSS.escape ? CSS.escape(fp.ks) : fp.ks) + '"]'); if (k) return k; }
    let n = root; for (const i of fp.p) { n = n && n.children[i]; if (!n) return null; }
    return n && n.tagName === fp.tag ? n : null;
  };
  function ovScrollKeep(root) { const out = []; root.querySelectorAll('*').forEach(e => { if (e.scrollLeft > 0) { const fp = ovPath(root, e); if (fp) out.push([fp, e.scrollLeft]); } }); return out; }
  const ovCls = c => String(c || '').split(/\s+/).filter(x => x && x !== 'fl' && x !== 'fr' && x !== 'ovx').sort().join(' ');
  function ovScrollBack(root, xs) { xs.forEach(([fp, x]) => { const el = ovAt(root, fp); if (el && ovCls(el.className) === ovCls(fp.cls)) el.scrollLeft = x; }); }
  function ovVisBox(el) { const d = el && el.closest && el.closest('.drawer,.usheet,.modal'); if (!d) return null; const b = d.getBoundingClientRect(), hd = d.querySelector(':scope > .dh'); let top = b.top; if (hd && !hd.contains(el) && getComputedStyle(hd).position === 'sticky') top = Math.max(top, hd.getBoundingClientRect().bottom); return { d, top, bottom: b.bottom }; }
  function ovIsVis(el) { try { const v = ovVisBox(el); if (!v) return false; const r = el.getBoundingClientRect(); return r.bottom > v.top && r.top < v.bottom; } catch (e) { return false; } }
  function ovFocusVis(el, was) { if (!was) return; try { const v = ovVisBox(el); if (!v) return; const r = el.getBoundingClientRect(); if (r.bottom > v.bottom) v.d.scrollTop += r.bottom - v.bottom + 12; else if (r.top < v.top) v.d.scrollTop -= v.top - r.top + 12; } catch (e) {  } }
  function ovFocusBack(root, fp, was) { const el = ovAt(root, fp); if (el && el.focus && String(el.className || '').split(' ')[0] === fp.cls.split(' ')[0]) { try { el.focus({ preventScroll: true }); } catch (e) {  } ovFocusVis(el, was); } }
  function renderOverlay() {
    { const o = $('#overlay'), a = document.activeElement;
      if (ovIme && a === ovIme && a.isConnected && o && o.contains(a) && o.getAttribute('data-k') === (S.drawer || '') + '|' + (S.modal ? 'm' : '') + '|' + (S.sheet ? 's:' + S.sheet.k + ':' + S.sheet.v : '')) { ovIdle = true; return; }
      ovIdle = false; }
    let h = '';
    try {
    if (S.drawer === 'fut' && S.D) h += futDrawer();
    if (S.drawer === 'rcpt' && S.D) h += rcptDrawer();
    if (S.drawer === 'frcpt' && S.D) h += futRcptDrawer();
    if (S.drawer === 'lev' && S.D) h += levDrawer();
    if (S.drawer === 'venue' && S.D) h += venueDrawer();
    } catch (e) { h = ovErrHTML(e, 'drawer:' + S.drawer); }
    try {
    if (S.sheet && S.D) h += uiSheetHTML();
    } catch (e) { h += ovErrHTML(e, 'sheet:' + (S.sheet && S.sheet.k), true); }
    if (S.modal) {
      const md = S.modal;
      h += '<div class="modal-bg" data-a="modalBg"><div class="modal" role="dialog" aria-modal="true" aria-labelledby="mdT"><h4 id="mdT"' + (md.pvx ? ' class="pvx"' : '') + '>' + esc(md.title) + '</h4>' + (md.bodyHtml != null ? '<p class="mdb">' + md.bodyHtml + '</p>' : '<p' + (md.pvx ? ' class="pvx"' : '') + '>' + esc(md.body) + '</p>')
        + (md.list ? '<div class="cap num" style="max-height:260px;overflow:auto;margin-top:10px;line-height:1.8;white-space:pre-line">' + esc(md.list) + '</div>' : '')
        + '<div class="ft">' + (md.info ? '<button class="btn pri" data-a="modalCancel">닫기</button>' : '<button class="btn" data-a="modalCancel">취소</button><button class="btn ' + (md.danger ? 'solid-danger' : 'pri') + (md.pvx ? ' pvx' : '') + '" data-a="modalOk">' + esc(md.ok || '확인') + '</button>') + '</div></div></div>';
    }
    const ov = $('#overlay');
    const had = ov.getAttribute('data-k') || '';
    const ae = document.activeElement, fa = ae && ov.contains(ae) && ae.getAttribute ? ae.getAttribute('data-a') : null, fv = fa ? ae.getAttribute('data-v') : null, fk = fa ? ae.getAttribute('data-k') : null;
    const fvis0 = !!(ae && ov.contains(ae) && ovIsVis(ae));
    const key = (S.drawer || '') + '|' + (S.modal ? 'm' : '') + '|' + (S.sheet ? 's:' + S.sheet.k + ':' + S.sheet.v : '');
    const dy0 = had === key && ov.querySelector('.drawer') ? ov.querySelector('.drawer').scrollTop : 0;
    const sy0 = had === key && ov.querySelector('.usheet') ? ov.querySelector('.usheet').scrollTop : 0;
    const fdr = ae && ov.contains(ae) && ae.tagName === 'INPUT' && ae.getAttribute('data-draft') && !ae.disabled && !RV_IN.has(ae) ? { k: ae.getAttribute('data-draft'), a: ae.selectionStart, b: ae.selectionEnd } : null;
    if (had === key && ov.__h === h && h) {
      ov.querySelectorAll('input[data-draft]').forEach(el => { const k9 = el.getAttribute('data-draft'); if (S.drafts[k9] != null && el.value !== S.drafts[k9] && el !== document.activeElement) el.value = S.drafts[k9]; });
      ovAfter(h); return;
    }
    const hx = had === key ? ovScrollKeep(ov) : null, fpath = had === key && ae && ov.contains(ae) && ae !== ov ? ovPath(ov, ae) : null;
    ov.innerHTML = h;
    ov.__h = h;
    if (hx) ovScrollBack(ov, hx);
    ov.querySelectorAll('input[data-draft]').forEach(el => { const k9 = el.getAttribute('data-draft'); if (S.drafts[k9] != null) el.value = S.drafts[k9]; });
    if (fdr) { const el = Array.from(ov.querySelectorAll('input[data-draft]')).find(x => x.getAttribute('data-draft') === fdr.k); if (el) { el.focus(); try { el.setSelectionRange(fdr.a, fdr.b); } catch (e) {  } } }
    if (dy0) { const d = ov.querySelector('.drawer'); if (d) d.scrollTop = dy0; }
    if (sy0) { const u = ov.querySelector('.usheet'); if (u) u.scrollTop = sy0; }
    if (had === key) ov.querySelectorAll('.drawer,.drawer-bg,.sheet-bg,.modal,.modal-bg,.usheet,.usheet-bg').forEach(x => { x.style.animation = 'none'; });
    ov.setAttribute('data-k', key);
    if (fa && had === key) { const fs = [...ov.querySelectorAll(ae.tagName.toLowerCase() + '[data-a="' + fa + '"]')], same = x => x.getAttribute('data-k') === fk, f = fk != null ? fs.find(x => same(x) && (fv == null || x.getAttribute('data-v') === fv)) : (fv != null && fs.find(x => x.getAttribute('data-v') === fv)) || fs[0]; if (f) { try { f.focus({ preventScroll: true }); } catch (e) { f.focus(); } ovFocusVis(f, fvis0); } }
    else if (fpath && !fdr && (document.activeElement === document.body || !ov.contains(document.activeElement))) ovFocusBack(ov, fpath, fvis0);
    hydrateLogos();
    ovAfter(h);
  }
  function ovAfter(h) {
    const ov = $('#overlay');
    if (h) fitUvSoon();
    { const on = !!h; ['header.top', '#mtop', '#banners', '#view', '#tabbar', '#bf'].forEach(sel => { const x = $(sel); if (x && x.inert !== on) x.inert = on; }); }
    document.documentElement.classList.toggle('ov-lock', !!h);
    { const on = !!S.modal; ov.querySelectorAll('.usheet,.usheet-bg,.drawer,.drawer-bg').forEach(x => { if (x.inert !== on) x.inert = on; }); }
    const ok = (S.modal && S.modal.danger ? $('#overlay [data-a="modalCancel"]') : null) || $('#overlay [data-a="modalOk"]') || $('#overlay [data-a="modalCancel"]');
    if (S.modal && ok && !S.modal._focused) { S.modal._focused = true; ok.focus(); }
    if (S.drawer === 'frcpt') frChipFix();
    bindSwipe();
  }
  function swipeSkip(el, t) {
    for (let n = t && t.nodeType === 1 ? t : t && t.parentElement; n && n !== el; n = n.parentElement) {
      if (n.classList && n.classList.contains('pop')) return true;
      if (n.scrollTop > 0 && n.scrollHeight > n.clientHeight + 1) { const oy = getComputedStyle(n).overflowY; if (oy === 'auto' || oy === 'scroll') return true; }
    }
    return false;
  }
  function bindSwipe() {
    if (!S.mobile) return;
    document.querySelectorAll('#overlay .drawer, #view .pop, #overlay .usheet').forEach(el => {
      if (el._sw) return; el._sw = 1;
      let y0 = null, dy = 0;
      el.addEventListener('touchstart', e => { if (swipeSkip(el, e.target) || (el.scrollTop > 0 && !(e.target.closest && e.target.closest('.dh')))) { y0 = null; return; } y0 = e.touches[0].clientY; dy = 0; }, { passive: true });
      el.addEventListener('touchmove', e => { if (y0 == null) return; dy = Math.max(0, e.touches[0].clientY - y0); el.style.transform = dy ? 'translateY(' + dy + 'px)' : ''; }, { passive: true });
      el.addEventListener('touchend', () => {
        if (y0 == null) return;
        if (dy > 90) { if (el.classList.contains('drawer')) closeDrawer(); else if (el.classList.contains('usheet')) uiSheetClose(); else { S.pop = null; renderView(); } }
        else el.style.transform = '';
        y0 = null;
      });
    });
  }
  function confirmAsk(cfg) { S.modal = cfg; S.pop = null; renderOverlay(); }
  function beScopeHTML(sym, n, qt, us) {
    return '<b class="pvx">' + esc(sym) + ' 원가 미상 매도 ' + (n || 0) + '건</b><span class="pvx"> · </span>' + (qt ? '<span class="num">' + q(qt) + '</span><span class="pvx"> ' + esc(sym) + ' · </span>' : '')
      + '<span class="pvx">정산 ' + (S.cur === 'USD' ? '' : '≈ ') + '</span><b class="num">' + m(us) + '</b>';
  }
  let toastT = null;
  function toast(msg, err, ms) {
    clearTimeout(toastT);
    $('#toast').innerHTML = '<div class="toast' + (err ? ' e' : '') + '">' + esc(err ? errTxt(msg) : msg) + '</div>';
    toastT = setTimeout(() => { $('#toast').innerHTML = ''; }, ms || (err ? 4200 : 2600));
  }
  function futFxNote(netUsd) {
    const D = S.D;
    if (!D || S.cur === 'USD' || !D.hasKrw) return '';
    const rb = D.fut.realizedByDate || {}, rk = D.fut.realizedKrwByDate || {};
    const jr = sum(Object.keys(rb), k => rk[k] != null ? num(rk[k]) : num(rb[k]) * rate());
    return Math.abs(jr - num(netUsd) * rate()) >= 1000 ? '원화 = 지금 환율 환산 · 매매일지 선물 ' + m(jr / rate(), { sign: true, compact: true }) + '은 정산 시각 환율이라 달라요' : '';
  }
  function futDrawer() {
    const f = S.D.fut, b = f.pnlBreak || {}, mm = f.mmRatio || {};
    const ps = arr(f.positions);
    const net = num(b.net != null ? b.net : f.realizedTotal);
    const tiles = ps.length ? '<div class="futtiles"><div><div class="l">포지션 규모</div><div class="v num">' + (f.ts && f.notional != null ? m(num(f.notional), { compact: true }) : '—') + '</div></div><div><div class="l">롱 / 숏</div><div class="v num lsv">' + (f.longNotional == null ? '—' : m(num(f.longNotional), { compact: true })) + ' / ' + (f.shortNotional == null ? '—' : m(num(f.shortNotional), { compact: true })) + '</div></div><div><div class="l">평가손익</div><div class="v num ' + cls(num(f.upnl)) + '"' + (f.upnlPartial ? ' title="코인 정산 포지션 일부는 시세가 없어 빼고 더했어요"' : '') + '>' + (f.ts ? upnlH(f.upnl, null, { sign: true, compact: true }) : '—') + '</div></div></div>'
      : '<div class="futnone">' + IC.info.replace('<svg', '<svg width="18" height="18"') + '<span>오픈 포지션 없음 · 누적 순손익 <b class="num ' + cls(net) + '">' + m(net, { sign: true }) + '</b></span></div>';
    const hasDex = Object.keys(f.venues || {}).length > 0;
    const bReal = num(b.realized != null ? b.realized : f.realizedTotal);
    const brk = '<div class="blk" style="margin-top:14px"><div class="ttl">누적 정산 (' + (hasDex ? '거래소·덱스' : '거래소') + ' 합산)</div>'
      + '<div class="kv"><span>실현</span><b class="num ' + cls(bReal) + '">' + m(bReal, { sign: true }) + '</b></div>'
      + (Math.abs(num(b.funding)) >= 0.005 ? '<div class="kv"><span>펀딩</span><b class="num ' + cls(num(b.funding)) + '">' + m(num(b.funding), { sign: true }) + '</b></div>' : '')
      + (Math.abs(num(b.fee)) >= 0.005 ? '<div class="kv"><span>수수료</span><b class="num ' + cls(num(b.fee)) + '">' + m(num(b.fee), { sign: true }) + '</b></div>' : '')
      + '<div class="kv"><span>순손익</span><b class="num ' + cls(net) + '">' + m(net, { sign: true }) + '</b></div>'
      + (futFxNote(net) ? '<div class="cap" style="margin:-2px 0 6px">' + esc(futFxNote(net)) + '</div>' : '')
      + (b.winRate != null ? '<div class="kv"><span title="거래소 정산 건 단위 — 한 포지션이 여러 번 나눠 정산되면 여러 건으로 세요(포지션 단위 아님)">승률(정산 건 기준)</span><b class="num">' + num(b.winRate).toFixed(1) + '% · ' + (num(b.wins) + num(b.losses)) + '건 중 ' + num(b.wins) + '승</b></div>' : '')
      + Object.keys(mm).filter(x => num((mm[x] || {}).maint) > 0).map(x => '<div class="kv"><span>' + esc(EX_NAMES[x] || x) + ' 유지증거금률</span><b class="num">' + num(mm[x].ratio).toFixed(2) + '%</b></div>').join('')
      + (arr(f.staleExchanges).length ? '<div class="fbnote">수집 지연 · 합산에서 제외: ' + esc(arr(f.staleExchanges).map(x => EX_NAMES[x] || x).join(', ')) + '</div>' : '') + '</div>';
    const pos = ps.length ? '<div class="blk" style="margin-top:14px"><div class="ttl">오픈 포지션 ' + ps.length + '</div>' + ps.map(p => '<div class="kv"><span class="row gap8" style="align-items:flex-start;white-space:normal;min-width:0;flex:1">' + exLogo(exKey(p.ex)) + '<span><b style="color:var(--text)">' + esc(futSym(p.sym)) + '</b> <span class="pill ' + (p.side === 'LONG' ? 'up' : 'down') + ' sm">' + (p.side === 'LONG' ? '롱' : '숏') + (p.lev ? ' ×' + esc(p.lev) : '') + '</span><div class="sub num">' + q(num(p.qty)) + ' · 진입 ' + px(num(p.entry)) + ' · 마크 ' + px(num(p.mark)) + (num(p.liq) > 0 ? ' · 청산 ' + px(num(p.liq)) : '') + '</div></span></span><b class="num ' + cls(num(p.upnl)) + '">' + upnlH(p.upnl, p.upnlWhy, { sign: true }) + '</b></div>').join('') + '</div>' : '';
    const rr = arr(f.realizedRows).slice().sort((a, c) => num(c._ts) - num(a._ts)).slice(0, 30);
    const rrRow = r => '<div class="kv" style="font-size:13px"><span class="row gap8">' + exLogo(exKey(r.ex)) + '<span class="num">' + esc(r.t) + ' · <b style="color:var(--text)">' + esc(futSym(r.sym)) + '</b>' + (r.liq ? ' <span class="pill down sm">청산</span>' : '') + (SUB_SFX.test(String(r.ex || '')) ? ' <span class="pill g sm">' + esc(String(r.ex).match(SUB_SFX)[0].slice(3)) + '</span>' : '') + '</span></span><b class="num ' + cls(num(r.pnl)) + '">' + m(num(r.pnl), { sign: true }) + '</b></div>';
    const rows = '<div class="blk" style="margin-top:14px"><div class="ttl">최근 정산 ' + rr.length + '건</div>' + (rr.length ? uiPaged('fut:rr', rr, r => rrRow(r), { unit: '건' }) : '<div class="mut fnone">없음</div>') + '</div>';
    let ex = '';
    if (S.fut) {
      const KN = { REALIZED: '실현', FUNDING: '펀딩', FEE: '수수료', TRANSFER: '이체', OTHER: '기타' };
      ex = '<div class="blk futraw">' + Object.keys(S.fut).map(k => {
        const e = S.fut[k] || {}, w = e.wallet || {}, evs = arr(e.events), dx = isDex(k);
        const kinds = {};
        evs.forEach(x => { kinds[x.kind] = num(kinds[x.kind]) + num(x.amount); });
        const ac = e.accts || {}, errs = Object.keys(ac).filter(a => ac[a] && ac[a].err), nliq = evs.filter(x => x.liq && x.kind === 'REALIZED').length;
        const dline = dx ? '<div class="cap">주소 ' + Object.keys(ac).length + '개' + (w.equity != null ? ' · 계정 가치 ' + m(num(w.equity)) : '') + (nliq ? ' · 청산 ' + nliq + '건' : '') + ' · 총자산 미반영</div>'
          + (errs.length ? '<div class="cap wtxt" title="' + esc(errTxt(errs.map(a => a.slice(0, 6) + '…' + a.slice(-4) + ' — ' + ac[a].err).join('\n'))) + '">수집 오류·지연 주소 ' + errs.length + '개 · 다음 주기에 다시 받아요</div>' : '') : '';
        return '<div style="padding:8px 0;border-bottom:1px solid var(--line)"><div class="row gap8">' + exLogo(k) + '<b>' + esc(EX_NAMES[k] || k) + '</b>' + (dx ? '<span class="pill g sm">덱스</span>' : '') + '<span class="sp"></span><span class="cap num">' + (e.ts ? fmtTs(num(e.ts)) + ' 수집' : '수집 대기') + '</span></div>'
          + (dx ? dline : '<div class="cap">' + (w.balance != null && isFinite(num(w.balance)) ? '가용 증거금 <span class="num">' + m(num(w.balance)) + '</span>' : esc(hs(String(w.note || '').replace(/통합계좌\(UNIFIED\)/g, '통합계좌')))) + ' · 이벤트 ' + evs.length + '건</div>') + '<div class="cap num">' + Object.keys(kinds).map(x => esc(KN[x] || x) + ' ' + mN(kinds[x], { sign: true })).join(' · ') + (evs.some(x => x.px_est) ? ' · 일부 지금 시세 추정' : '') + '</div></div>';
      }).join('') + '</div>';
    } else if (S.futErr) ex = '<div class="fbnote">거래소 원본을 불러오지 못했어요</div>';
    else ex = '<div class="cap">거래소별 원본 불러오는 중…</div>';
    const exT = S.fut && Object.keys(S.fut).some(isDex) ? '거래소·덱스별 원본' : '거래소별 원본';
    ex = '<div class="futrawf">' + uiFold('fut:raw', { cls: 'plain', head: '<b>' + exT + '</b><span class="cap">수집 시각 · 가용 증거금 · 이벤트 합</span>', body: () => ex, label: exT }) + '</div>';
    return '<div class="drawer-bg" data-a="drawerClose"></div><aside class="drawer" role="dialog" aria-modal="true" aria-label="선물 상세"><div class="dh"><h2 class="h2">선물 상세</h2>' + (f.ts ? '<span class="rsum num"><span class="' + cls(net) + '">' + m(net, { sign: true, compact: true }) + '</span></span>' : '') + '<span class="sp"></span>' + (legacyOn("futures") ? '<a class="link hide-sm" href="/futures">기존 선물 페이지</a>' : '') + '<button class="iconbtn" data-a="drawerClose" aria-label="닫기">' + IC.close + '</button></div>'
      + '<div class="cap" style="margin-bottom:12px">' + (f.ts ? fmtTs(num(f.ts)) + ' 기준 · 마크가 · 총자산 미반영 (증거금은 거래소 잔고에 포함)' : '수집 대기') + '</div>'
      + (num(f.coinEst) ? '<div class="fbnote">코인으로 정산된 ' + num(f.coinEst) + '건은 정산 시각 시세 기록이 없어 지금 시세로 추정한 달러예요(나머지는 정산 시각 시세)</div>' : '') + tiles + pos + brk + rows + ex + '</aside>';
  }

  const {
    frChart, frChipFix, frExKey, frLoad, futRcptDrawer, openFutRcpt, openReceipt, postJ, rcbLoad, rcEvalPost, rcLoad, rcOn, rcptDrawer, rcSK, rcV,
    topRcptSym
  } = tjTab('rcpt', {
    $, arr, cls, clsV, csrf, dayContrib, dmRcptHTML, DOWS, dpFade, drawerHist, errTxt, esc, evTxt, EX_NAMES, exLogo, fmtTs, futSym, IC, icon, isAI,
    isISO, KV, m, mN, nf, num, onUnauthorized, pad2, pctS, PV_RE, PVM, pvOn, pvW, px, q, qXf, rate, rcptable, renderOverlay, revTxt, RS_RE, rw, S,
    sum, term, uiFold, uiOpen, uiPaged
  });
  tjLate_dash({ openFutRcpt, topRcptSym });

  function syncUrl() {
    const qs = new URLSearchParams(location.search);
    if (S.src.mode === 'all') qs.delete('src'); else qs.set('src', S.src.mode + (S.src.key ? ':' + S.src.key : ''));
    if (!S.urlPeriod && (S.g.period === 'all' || S.g.period === 'thismonth')) qs.delete('period'); else qs.set('period', S.g.period);
    if (S.g.period === 'custom') { if (isISO(S.g.from)) qs.set('from', S.g.from); else qs.delete('from'); if (isISO(S.g.to)) qs.set('to', S.g.to); else qs.delete('to'); }
    else { qs.delete('from'); qs.delete('to'); }
    qs.delete('tab');
    const s = qs.toString();
    history.replaceState(null, '', location.pathname + (s ? '?' + s : '') + '#' + (S.tab === 'settings' ? sxHash(S.set.sec, S.set.sub) : S.tab));
  }
  function readUrl() {
    const qs = new URLSearchParams(location.search);
    const s = (qs.get('src') || '').trim();
    if (s) { const i = s.indexOf(':'), mode = (i < 0 ? s : s.slice(0, i)).toLowerCase(); if (mode === 'dex' || mode === 'cex') { S.src.mode = mode; S.src.key = i < 0 ? '' : s.slice(i + 1); } }
    const p = (qs.get('period') || '').trim().toLowerCase();
    if (p === 'custom') {
      const f = (qs.get('from') || '').trim(), t = (qs.get('to') || '').trim();
      if (isISO(f)) S.g.from = clampISO(f); if (isISO(t)) S.g.to = clampISO(t);
      S.g.period = 'custom'; defaultRange(); S.urlPeriod = true;
    } else if (PERIODS.some(d => d.k === p)) { S.g.period = p; S.urlPeriod = true; }
    const r9 = sxParse(location.hash), h = r9.tab;
    if (h === 'settings') { S.set.sec = r9.sec; S.set.sub = r9.sub; }
    const tq = qs.get('tab');
    const byKo = TABS.find(t => t.ko === tq || t.k === tq);
    S.tab = TABS.some(t => t.k === h) ? h : (byKo ? byKo.k : 'dash');
  }
  function defaultRange() { if (isISO(S.g.from) || isISO(S.g.to)) return; S.g.from = ymShift(0) + '-01'; S.g.to = todayISO(); }
  function go(tab) { S.pop = null; if (S.tab === tab) { render(); return; } location.hash = tab; }
  function openDay(v) {
    const k = dayKeyOf(v);
    if (!k) { const iso = isYMD(v) ? String(v).slice(0, 10) : String(v == null ? '' : v); toast(iso + ' — 그날 카드(실현·리뷰·기록)는 최근 12개월만 열 수 있어요 · 그 전 기록은 매매일지 전체 기간에서 봐요', false, 5000); return; }
    wkOff(); S.day = k; S.calYM = ymOf(k) || S.calYM; go('daily');
    if (S.mobile) { const t0 = Date.now(), tick = () => { if (S.day !== k || !S.mobile) return; if (!(S.tab === 'daily' && dayCardShow(false)) && Date.now() - t0 < 4000) setTimeout(tick, 80); }; setTimeout(tick, 0); }
  }
  function dayCardShow(smooth) {
    const c = $('#view .card.rev'); if (!c) return false;
    const top = c.getBoundingClientRect().top, mt = parseFloat(getComputedStyle(c).scrollMarginTop) || 0;
    if (top >= mt - 8 && top <= window.innerHeight * 0.45) return true;
    try { c.scrollIntoView({ block: 'start', behavior: smooth && !uiReduce() ? 'smooth' : 'auto' }); } catch (e) { c.scrollIntoView(); }
    return true;
  }
  window.addEventListener('hashchange', () => {
    const r9 = sxParse(location.hash), h = r9.tab;
    if (h === 'settings' && S.tab === 'settings') { sxRoute(r9); return; }
    if (TABS.some(t => t.k === h) && h !== S.tab) {
      if (h === 'settings') { S.set.sec = r9.sec; S.set.sub = r9.sub; S.set.anim = ''; S.set.prev = ''; S.set.q = ''; }
      S.tab = h; S.pop = null; S.modal = null; S.drawer = null; S.sheet = null; syncUrl(); render(); window.scrollTo(0, 0);
    }
  });

  const draft = k => String(S.drafts[k] == null ? '' : S.drafts[k]).trim();
  const pendByKey = k => S.D.pendings.find(p => p.key === k);
  const ofByAddr = a => S.D.of.find(r => r.address === a);
  tjLate_out({ ofByAddr });
  function setDust(v) {
    v = Math.max(0, Math.min(Math.round(v), 1e6));
    S.dust = v; S.hold.showDust = false;
    LS.set('tj_dust', String(v));
    render();
    csrf().then(tok => fetch('/api/dust_threshold', { method: 'POST', headers: Object.assign({ 'Content-Type': 'application/json' }, tok ? { 'X-TJ-CSRF': tok } : {}), body: JSON.stringify({ usd: v }) }))
      .then(r => r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status)))
      .then(d => { if (!d || !d.ok) throw new Error((d && d.error) || '저장 거부'); toast('소액 기준 ' + (v ? '$' + v : '전체 표시') + ' · 저장했어요'); refresh(); })
      .catch(e => toast('지금 화면에만 적용했어요(서버 저장 실패 — 새로 고치면 서버 값) · ' + e.message, true));
  }
  function savePlan(key, fields, okMsg) {
    if (!key) { toast('저장할 카드를 찾지 못했어요', true); return; }
    const body = Object.assign({ key }, fields);
    Object.keys(body).forEach(k => { if (body[k] === undefined) delete body[k]; });
    if (('target' in body || 'stop' in body) && !(body.target === null && body.stop === null)) {
      const cur = S.D.plans[key] || {};
      const nt = 'target' in body ? body.target : cur.target, ns = 'stop' in body ? body.stop : cur.stop;
      if (nt == null || ns == null) okMsg = '저장했어요 · 목표·손절을 모두 채워야 감시해요';
      else if (!(isFinite(nt) && isFinite(ns) && 0 < ns && ns < nt)) { toast('손절선은 0보다 크고 목표가보다 낮아야 해요 · 저장하지 않았어요', true); return; }
    }
    post('/api/plan', body, okMsg).then(d => { if (d) { delete S.drafts['t:' + key]; delete S.drafts['s:' + key]; delete S.drafts['m:' + key]; if (S.planSnap) delete S.planSnap[key]; render(); renderOverlay(); } });
  }
  function saveAlias(key, val, cur) {
    const next = String(val == null ? '' : val).trim();
    S.aliasEdit = null;
    if (!key || next === String(cur == null ? '' : cur)) { renderView(); return; }
    unmarkNewWallet(key);
    post('/api/wallet_alias', { address: key, alias: next }, '지갑 이름을 저장했어요');
    renderView();
  }
  function costUnit(k) {
    const p = pendByKey(k); if (!p || !p.gkey) { toast('원가 지정 대상이 아니에요', true); return; }
    const raw = draft('cu:' + k).replace(/,/g, '');
    const n = Number(raw);
    if (!raw || !isFinite(n) || !(n > 0)) { toast('단가는 0보다 큰 숫자여야 해요', true); return; }
    post('/api/cost_override', { key: p.gkey, mode: 'unit', value: n }, '원가를 적용했어요 · 평가·손익을 다시 계산해요').then(d => { if (d) delete S.drafts['cu:' + k]; });
  }
  function ignoreKeys(keys, label) {
    const ks = keys.filter(Boolean);
    if (!ks.length) { toast('숨길 항목이 없어요', true); return; }
    post('/api/ignore_bulk', { keys: ks }, d => (label || ks.length + '건') + ' 목록에서 숨겼어요 (누적 ' + (d.total || 0) + '건)');
  }
  function copyText(t) {
    const s = String(t || '');
    const ok = () => toast('복사했어요 · ' + short(s));
    const fail = () => { toast('복사하지 못했어요 — 직접 복사하세요', true); try { window.prompt('직접 복사하세요 (Ctrl/Cmd+C)', s); } catch (e) {  } };
    try { if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(s).then(ok, fail); else fail(); } catch (e) { fail(); }
  }
  function closeDrawer(noFocus) {
    const bk = S.drawer === 'rcpt' && S.rcpt ? S.rcpt.back : S.drawer === 'frcpt' && S.frc ? S.frc.back : S.drawer === 'fut' ? S.futBack : S.drawer === 'lev' ? S.levBack : S.drawer === 'venue' ? S.venueBack : null;
    S.drawer = null; renderOverlay();
    if (history.state && history.state.tjDr) { try { if (noFocus) history.replaceState(null, '', location.href); else history.back(); } catch (e) {  } }
    if (noFocus || !bk) return;
    const el = bk.el && bk.el.isConnected ? bk.el : [...document.querySelectorAll('#view [data-a="' + bk.a + '"]')].find(x => (x.getAttribute('data-fv') || x.getAttribute('data-v')) === bk.v && (bk.k == null || x.getAttribute('data-k') === bk.k));
    if (el && el.focus) { try { el.focus(); } catch (e) {  } }
  }
  function closeDrawerThen(then) {
    if (!S.drawer) { then(); return; }
    const back = !!(history.state && history.state.tjDr);
    let done = false;
    const fin = () => { if (done) return; done = true; window.removeEventListener('popstate', onPop9); then(); };
    const onPop9 = () => setTimeout(fin, 0);
    if (back) { window.addEventListener('popstate', onPop9); setTimeout(fin, 600); }
    closeDrawer();
    if (!back) fin();
  }
  function drawerHist() { try { if (!(history.state && history.state.tjDr)) history.pushState({ tjDr: 1 }, '', location.href); } catch (e) {  } }
  window.addEventListener('popstate', ev => {
    if (!S.drawer || (ev.state && ev.state.tjDr)) return;
    const bk = S.drawer === 'rcpt' && S.rcpt ? S.rcpt.back : S.drawer === 'frcpt' && S.frc ? S.frc.back : S.drawer === 'fut' ? S.futBack : S.drawer === 'lev' ? S.levBack : S.drawer === 'venue' ? S.venueBack : null;
    S.drawer = null; renderOverlay();
    const el = bk && (bk.el && bk.el.isConnected ? bk.el : [...document.querySelectorAll('#view [data-a="' + bk.a + '"]')].find(x => (x.getAttribute('data-fv') || x.getAttribute('data-v')) === bk.v && (bk.k == null || x.getAttribute('data-k') === bk.k)));
    if (el && el.focus) { try { el.focus(); } catch (e) {  } }
  });
  function openFut() {
    const ae = document.activeElement;
    S.futBack = ae && ae.getAttribute && ae.getAttribute('data-a') ? { el: ae, a: ae.getAttribute('data-a'), v: ae.getAttribute('data-v') } : null;
    S.drawer = 'fut'; S.futErr = null;
    drawerHist();
    renderOverlay();
    { const b = $('#overlay .drawer [data-a="drawerClose"]'); if (b) b.focus(); }
    fetch('/api/futures', { cache: 'no-store' }).then(r => r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status)))
      .then(d => { S.fut = d; if (S.drawer === 'fut') renderOverlay(); })
      .catch(e => { S.futErr = e.message; if (S.drawer === 'fut') renderOverlay(); });
  }
  const vib = () => { try { if (S.mobile && navigator.vibrate && navigator.userActivation && navigator.userActivation.isActive) navigator.vibrate(8); } catch (e) {  } };
  tjLate_dash({ vib });
  function ofResolve(a, verdict, extra, okMsg) {
    const body = Object.assign({ address: a, verdict }, extra || {});
    return post('/api/outflow_resolve', body, d => okMsg || (d && d.restartNeeded ? '내 지갑으로 등록했어요 · 수집기 재시작 뒤 반영돼요' : verdict === 'own' && d && d.apply && d.apply.runner ? '내 지갑으로 등록했어요 · 곧 자동으로 수집을 시작해요' : '저장했어요')).then(d => {
      if (d) { S.of.form[a] = ''; ['alias', 'chains', 'ex', 'cat', 'memo'].forEach(k => { delete S.drafts['of:' + a + ':' + k]; }); if (verdict !== 'clear') S.of.open.delete(a); }
      if (d && verdict === 'own') rlFetch(true);
      return d;
    });
  }

  const A = {
    reload: () => refresh(true),
    reloadPage: () => location.reload(),
    reopenLocked: () => reopenLocked(),
    logoutRetry: () => authLogout(false),
    authPw: () => { S.authPw = !S.authPw; ['au:cur', 'au:new', 'au:new2'].forEach(k => { delete S.drafts[k]; }); renderView(); if (S.authPw) setTimeout(() => { const n = $('#auCur'); if (n) n.focus(); }, 0); },
    authPwSave: () => authPwSave(),
    authLogout: () => authLogout(false),
    authLogoutAll: () => { if (window.confirm('이 기기를 포함한 모든 기기에서 로그아웃할까요? 다시 쓰려면 비밀번호로 로그인해야 해요.')) authLogout(true); },
    authRetry: () => { authLoad(true); renderView(); },
    resetPrefs: () => { resetPrefs(); clearCache().then(() => { location.replace(location.pathname + '#dash'); location.reload(); }); },
    theme: () => { const light = document.documentElement.getAttribute('data-theme') === 'light'; A.themeSet(null, light ? 'dark' : 'light'); },
    themeSet: (el, v) => { v = typeof v === 'string' ? v : el.dataset.v; LS.set('tj_v2_theme', v === 'system' ? 'system' : v); v = themeOf(v); document.documentElement.setAttribute('data-theme', v); const mt = $('meta[name=theme-color]'); if (mt) mt.setAttribute('content', v === 'light' ? '#F3F4F7' : '#0B0D11'); render(); },
    scheme: el => { const g = el.dataset.v === 'global'; if (g) document.documentElement.setAttribute('data-scheme', 'global'); else document.documentElement.removeAttribute('data-scheme'); LS.set('tj_v2_scheme', g ? 'global' : 'kr'); render(); },
    cur: el => { const c = el.dataset.v === 'USD' ? 'USD' : 'KRW'; if (c !== S.cur) animReset(); S.cur = c; LS.set('tj_v2_cur', S.cur); render(); },
    curToggle: () => { animReset(); S.cur = S.cur === 'KRW' ? 'USD' : 'KRW'; LS.set('tj_v2_cur', S.cur); vib(); render(); },
    hideToggle: () => setHide(!S.hide),
    randToggle: () => setRand(!S.rand),
    rkSet: () => {
      const el = document.querySelector('[data-draft="rk"]'), raw = S.drafts.rk != null ? String(S.drafts.rk) : (el ? el.value : '');
      const v = parseFloat(String(raw).replace(/[×xX\s]/g, ''));
      if (!RK_OK(v)) { toast('배수는 0.2~5 사이(0.8~1.25 제외)로 넣어 주세요', true); return; }
      delete S.drafts.rk; LS.set('tj_v2_rk', String(v)); rkApply(); toast('랜덤값 배수를 고정했어요 — 다시 열어도 같은 배수');
    },
    rkClear: () => { delete S.drafts.rk; LS.del('tj_v2_rk'); rkApply(); toast('랜덤값 배수 고정을 풀었어요 — 열 때마다 무작위'); },
    pgSize: el => { const v = el && el.dataset && el.dataset.v === '20' ? 20 : 10; if (v === uiPageSize()) return; S.pgSz = v; LS.set('tj_v2_pgsize', String(v)); uiPgReset(''); if (S.attdUI) S.attdUI.pg = 0; toast('긴 목록을 ' + v + '개씩 보여 줘요'); render(); },
    logoToggle: () => { LS.set('tj_v2_nologo', logosOff() ? '0' : '1'); toast(logosOff() ? '토큰 로고 끔 — 외부 요청 없음(지금 떠 있는 로고는 새로고침하면 사라져요)' : '토큰 로고 켬'); render(); if (!logosOff()) hydrateLogos(); },
    tipShow: el => toast(String(el.dataset.v || ''), false, 6000),
    bfMin: () => { S.bfMin = !S.bfMin; SS.set('tj_v2_bfmin', S.bfMin ? '1' : '0'); $('#bf').innerHTML = bfHTML(S.D && S.D.backfill); bfPad(); const b = $('#bf [data-a=bfMin]'); if (b) b.focus({ preventScroll: true }); },
    habRetry: () => habLoad(true),
    mDisp: el => uiSheetOpen('mdisp', '', '표시', el),
    mDispGo: () => { uiSheetClose(true); location.hash = '#settings/display'; },
    bestMonths: el => { uiSheetOpen('bestm', '', '최고의 날 · ' + ((CH_RANGES.find(r => r[0] === S.chartDays) || [0, ''])[1] || '기간'), el); },
    bestPick: el => { const iso = String(el.dataset.v || ''); if (!isYMD(iso)) return; S.bestPick = iso; uiSheetClose(true); renderView(); A.receiptTop({ dataset: { v: iso } }); },
    benchRows: el => uiSheetOpen('benchRows', String(el.dataset.v || ''), '안 팔았다면 · 판 것 하나씩', el),
    benchTog: el => { const k = el.dataset.v, s9 = benchSet(); if (BENCH_K.indexOf(k) < 0) return; if (s9.has(k)) s9.delete(k); else s9.add(k);
      LS.set('tj_v2_bench', Array.from(s9).join(',')); if (s9.size) benchLoad(!(S.bench && S.bench.d)); vib(); renderView(); },
    chartDays: el => { const v = +el.dataset.v; if (!CH_RANGES.some(r => r[0] === v)) return; S.chartDays = v; S.chartUser = true; LS.set('tj_v2_chart_days', String(v)); vib(); if (v > 30) histLoad(); renderView(); },
    go: el => go(el.dataset.v),
    goJournalPeriod: el => { S.g.period = el.dataset.v; S.j.view = 'tax'; syncUrl(); go('journal'); },
    goJournalHeld: () => { S.j.status = 'open'; S.j.view = 'cycles'; S.j.sort = 'unreal'; go('journal'); },
    goJournalSym: el => { S.j.q = el.dataset.v; S.drafts.jq = el.dataset.v; S.j.status = 'all'; S.j.view = 'cycles'; S.j.limit = J_FIRST; S.g.period = 'all'; const p = S.D.merged.find(x => String(x.sym).toUpperCase() === String(el.dataset.v).toUpperCase()); if (p) { S.j.open.add(p.key); S.justOpened.add('j:' + p.key); } syncUrl(); go('journal'); },
    goPend: el => { const c = el.dataset.v; S.u.open = new Set([c]); S.u.q = el.dataset.q || ''; S.drafts.uq = S.u.q; go('unmatched'); },
    goDay: el => { wkOff(); S.day = el.dataset.v; S.calYM = ymOf(S.day) || S.calYM; go('daily'); },
    mvDot: el => { const touch = S.mobile || (window.matchMedia && matchMedia('(hover: none)').matches);
      if (touch && !el.classList.contains('on')) { document.querySelectorAll('.chart .mvd.on').forEach(x => x.classList.remove('on')); el.classList.add('on'); return; }
      openDay(el.dataset.v); },
    openFut: openFut,
    drawerClose: () => closeDrawer(),
    futRcpt: el => { const v = String(el.dataset.fv || el.dataset.v || ''), i = v.indexOf('|'); openFutRcpt(i > 0 ? v.slice(0, i) : v, i > 0 ? v.slice(i + 1) : '', el.dataset.rk); },
    frCoin: el => { const R = S.frc; if (!R) return; const d = ((S.frC || {})[R.key] || {}).d; R.coin = String(el.dataset.v || '').slice(0, 60); R.venue = d && !d.empty ? frExKey(R, d) : ''; frChart(); renderOverlay(); },
    frAll: () => { const R = S.frc; if (!R) return; R.ex = ''; renderOverlay(); const b = $('#overlay .frc [data-a="frCoin"][aria-pressed="true"]') || $('#overlay .frc [data-a="drawerClose"]'); if (b) b.focus({ preventScroll: true }); },
    frIv: el => { const R = S.frc; if (!R) return; R.iv = el.dataset.v === '1m' ? '1m' : '5m'; frChart(); renderOverlay(); },
    frVenue: el => { const R = S.frc; if (!R) return; R.venue = String(el.dataset.v || '').slice(0, 40); frChart(); renderOverlay(); },
    frRetry: () => { if (S.frc) { frLoad(true); renderOverlay(); } },
    frChartRetry: () => { if (S.frc) { frChart(true); renderOverlay(); } },
    frFut: () => closeDrawerThen(openFut),
    frDay: () => { const R = S.frc; if (!R) return; const iso = R.iso; closeDrawerThen(() => openDay(iso)); },
    receipt: el => { const v = String(el.dataset.v || ''), i = v.indexOf('|'); if (i > 0) openReceipt(v.slice(0, i), v.slice(i + 1), el.dataset.rk); },
    receiptTop: el => { const iso = isoDay(String(el.dataset.v || '')); if (!iso) return; const rows = dayContrib(iso), i = rows.findIndex(rcptable);
      const fi = rows.findIndex(x => x.fut);
      if (i >= 0) openReceipt(iso, rows[i].sym, i + 1); else if (fi >= 0) openFutRcpt(iso, '', fi + 1); else openDay(iso); },
    lpGo: el => { const v = String(el.dataset.v || '').split('|'), iso = v[0], pool = v[1] || '', key = v[2] || '';
      if (!isISO(iso) || !pool) return;
      const md = iso.slice(5), keys = key ? [key] : S.D.lpCycles.filter(p => String(p.sym) === pool && Math.abs(num((p.realizedByDay || {})[md]) + num((p.realizedByDay || {})[iso])) >= 0.005).map(p => p.key);
      S.j.view = 'cycles'; S.j.status = 'all'; S.j.q = pool; S.drafts.jq = pool; S.j.limit = J_FIRST; S.j.open = new Set(keys);
      S.g.period = 'custom'; S.g.from = iso; S.g.to = iso;
      go('journal');
      if (S.tab === 'journal') syncUrl();
      setTimeout(() => { const c = document.querySelector('#view .card.cyc.open .hd'); if (c) { c.scrollIntoView({ block: 'center' }); try { c.focus({ preventScroll: true }); } catch (e) {  } } }, 120); },
    rcptRetry: () => { const R = S.rcpt; if (R) openReceipt(R.iso, R.sym, R.rank); },
    rcptAi: () => { if (S.rcpt) { S.rcpt.aiOpen = !S.rcpt.aiOpen; renderOverlay(); } },
    rcIv: el => { const R = S.rcpt; if (!R) return; rcV(R).iv = el.dataset.v === '1m' ? '1m' : '5m'; rcLoad(); renderOverlay(); },
    rcAfter: el => { const R = S.rcpt; if (!R) return; const v = el.dataset.v; rcV(R).after = v === '6h' || v === '24h' ? v : '1h'; rcLoad(); renderOverlay(); },
    rcVenue: el => { const R = S.rcpt; if (!R) return; const v = String(el.dataset.v || '').slice(0, 200), x = R.lastK && ((S.rcptX || {})[R.lastK] || {}).d, v0 = x && arr(x.venues)[0];
      rcV(R).venue = v0 && v0.key === v ? '' : v; rcLoad(); renderOverlay(); },
    rcRetry: () => { if (S.rcpt) { rcLoad(true); renderOverlay(); } },
    rcEval: () => { rcEvalPost(false); },
    rcEvalB: () => { rcEvalPost(false, 0, 'buy'); },
    rcEvalReB: () => { rcEvalPost(true, 0, 'buy'); },
    rcBVenue: el => { const R = S.rcpt; if (!R) return; const v = String(el.dataset.v || '').slice(0, 200), x = R.lastBK && ((S.rcptB || {})[R.lastBK] || {}).d, v0 = x && arr(x.venues)[0];
      rcV(R).bvenue = v0 && v0.key === v ? '' : v; rcbLoad(); renderOverlay(); },
    rcRetryB: () => { if (S.rcpt) { rcbLoad(true); renderOverlay(); } },
    rkBrk: el => { const t = el.getAttribute('data-tip'); if (t) toast(t, false, 4200); },
    fbTip: el => { const on = !el.classList.contains('on'); document.querySelectorAll('.fbars .fbc.on').forEach(x => x.classList.remove('on')); if (on) el.classList.add('on'); },
    rcEvalRe: () => { rcEvalPost(true); },
    rcptDay: () => {
      const R = S.rcpt; if (!R) return;
      const d = ((S.rcptC || {})[R.key] || {}).d || {};
      const syms = new Set([R.sym].concat(d.sym ? [d.sym] : [], arr(d.aliases)).map(x => String(x).toUpperCase()));
      wkOff(); S.day = R.iso.slice(5); S.calYM = R.iso.slice(0, 7); S.dayEvLimit = 20; S.daySym = { k: S.day, keys: syms };
      if (S.mobile) S.dayView = 'grp';
      closeDrawer(true);
      const jump = () => setTimeout(() => { const c = document.getElementById('dayEv'); if (!c) return; c.scrollIntoView({ block: 'start' }); const h = c.querySelector('.h2'); if (h) { h.setAttribute('tabindex', '-1'); try { h.focus({ preventScroll: true }); } catch (e) {  } } }, 80);
      if (S.tab !== 'daily') { location.hash = 'daily'; jump(); } else { renderView(); jump(); }
    },
    revTog: el => { S.revOpen = S.revOpen === el.dataset.v ? null : el.dataset.v; renderView(); },
    dxTog: () => { S.dxFull = !S.dxFull; renderView(); },
    attTog: el => { S.attOpen = S.attOpen === el.dataset.v ? null : el.dataset.v; renderView(); },
    onbClose: () => { LS.set(ONB_X, '1'); renderView(); toast('안내 카드를 숨겼어요 — 설정 › 연결·키에서 다시 볼 수 있어요'); },
    onbShow: () => { LS.del(ONB_X); if (onbState()) go('dash'); else { renderView(); toast('지금은 남은 설정이 없어 안내 카드가 뜨지 않아요'); } },
    dayView: el => { S.dayView = el.dataset.v === 'each' ? 'each' : 'grp'; S.dayEvLimit = 20; renderView(); },
    dayB: el => { const st = S.dayBOpen || (S.dayBOpen = new Set()); togSet(st, el.dataset.v); renderView(); },
    dayBEach: el => { const st = S.dayBEach || (S.dayBEach = new Set()); st.add(el.dataset.v); renderView(); },
    daySymClear: () => { S.daySym = null; renderView(); },
    dayPick: el => {
      const key = el.dataset.v, k = S.day || S.D.todayKey; if (!key) return;
      const cur = S.daySym && S.daySym.keys ? new Set(S.daySym.keys) : new Set();
      togSet(cur, key);
      S.daySym = cur.size ? { k, keys: cur } : null; S.dayEvLimit = 20;
      const inPop = !!el.closest('.pop'), sel = (inPop ? '.pop.dpkpop' : '#dayEv .dpr') + ' [data-a=dayPick][data-v="' + (window.CSS && CSS.escape ? CSS.escape(key) : key) + '"]';
      renderView();
      const n = $(sel); if (n) n.focus({ preventScroll: true });
    },
    dayPickAll: el => { const inPop = !!(el && el.closest && el.closest('.pop')); S.daySym = null; S.dayEvLimit = 20; if (inPop) S.pop = null; renderView();
      const n = $('#dayEv [data-a=dayPickAll]'); if (n) n.focus({ preventScroll: true }); },
    guardInfo: () => confirmAsk({ info: true, title: '가격 이상 ' + S.D.priceGuard.length + '종 · 평가 제외', body: 'DEX 가격이 풀 유동성·보유 규모에 비해 비정상이라 평가금액을 0 으로 두고 총자산·손익에서 뺐어요. 가격이 정상화되면 자동으로 다시 포함돼요.', list: S.D.priceGuard.map(g => (g.sym || short(g.ca)) + ' · ' + g.chain + ' — ' + hs(g.reason, true)).join('\n') }),
    unpricedInfo: () => confirmAsk({ info: true, title: '시세 없는 토큰 ' + S.D.upN + '개', body: '가격을 확인할 수 없어 평가금액 0 으로 두고 총자산·손익에서 뺐어요. 상장 폐지·스팸 토큰이거나 가격 소스가 없는 경우예요. 토큰(컨트랙트) 단위로 셌어요 — 이름이 같은 토큰은 ×개수.', list: S.D.unpricedSym.join(' · ') }),
    toggleDust: () => { S.hold.showDust = !S.hold.showDust; renderView(); },
    holdZero: () => { S.hold.showZero = !S.hold.showZero; renderView(); },
    unvTok: el => { const x = arr(S.D.zeroInst).find(z => z.key === el.dataset.k); if (!x || !x.ca) return;
      confirmAsk({ title: x.unv + ' — 확인 필요',
        bodyHtml: esc(x.sym) + (x.chain ? ' · ' + esc(x.chain) : '') + ' · 컨트랙트 <span class="num">' + esc(shortL(x.ca)) + '</span><br>'
          + esc(x.unv) + ' 이름이지만 정품 목록에 없는 컨트랙트이고 유동성 있는 시세도 없어요. 확인 전에는 평가 0 으로 두고 총자산·일별 기록·알림에 넣지 않아요.<br>'
          + '발행사·체인 공식 문서의 토큰 주소와 같을 때만 정품으로 등록하세요 — 등록하면 ' + esc(x.unv) + ' 시세(스테이블은 액면 $1)로 평가해 총자산에 들어가요.'
          + '<br><button class="link" data-a="unvSpam" data-k="' + esc(x.key) + '">가짜로 확정하고 숨기기</button>',
        ok: '정품으로 등록', run: () => post('/api/genuine_token', { chain: x.ck, ca: x.ca, on: true }, '정품으로 등록했어요 · 다음 갱신에 반영돼요') }); },
    unvSpam: el => { const k = String(el.dataset.k || ''); if (!/^g\d+$/.test(k)) return; S.modal = null; renderOverlay(); post('/api/risk_override', { key: k, verdict: 'spam' }, '가짜로 확정했어요 · 숨긴 항목으로 옮겨요'); },
    genTok: el => { const k = el.dataset.k, x = arr(S.D.zeroInst).find(z => z.key === k) || (S.D.instOf || {})[k]; if (!x || !x.ca || !x.ck) return;
      confirmAsk({ title: '정품 등록을 풀까요?', body: (x.sym || '') + ' 컨트랙트(' + short(x.ca) + ')를 직접 등록한 정품 목록에서 빼요. 다시 정품 목록 밖 대표 심볼이면 확인 필요로 돌아가요.', ok: '등록 풀기',
        run: () => post('/api/genuine_token', { chain: x.ck, ca: x.ca, on: false }, '정품 등록을 풀었어요') }); },
    holdMode: el => { S.hold.mode = el.dataset.v; S.hold.limit = 25; uiPgReset('hold'); vib(); renderView(); },
    holdSort: el => { const k = el.dataset.v; if (S.hold.sort === k) S.hold.dir = -S.hold.dir; else { S.hold.sort = k; S.hold.dir = -1; } uiPgReset('hold'); renderView(); },
    holdTog: el => tog(S.hold.open, el.dataset.k),
    holdDense: el => { S.hold.dense = el.dataset.v === '1'; LS.set('tj_v2_hold_dense', S.hold.dense ? '1' : '0'); vib(); renderView(); },
    venueOpen: el => venueOpen(el),
    venueCoin: el => { const sym = String(el.dataset.v || ''); if (sym) revealAndHighlight('coin:' + sym); },
    venueRec: () => { const v = arr(S.D && S.D.venues).find(x => nmKey(x.name) === S.venueK), f = v && vnSrc(vnModel(v)); if (!f) return;
      S.src = { mode: f.mode, key: f.key }; S.j.limit = J_FIRST; closeDrawer(true); S.tab = 'journal'; S.pop = null;
      try { history.pushState(null, '', location.pathname + location.search + '#journal'); } catch (e) {  } syncUrl(); render(); window.scrollTo(0, 0); },
    stTog: el => tog(S.stOpen, el.dataset.k),
    lpTog: el => tog(S.lpOpen, el.dataset.k),
    lpClosed: () => { S.lpClosed = !S.lpClosed; renderView(); },
    pop: el => { const v = el.dataset.v; S.pop = S.pop === v || (v === 'period' && S.pop === 'range') ? null : v; if (S.pop === 'dpk') S.drafts.dpq = ''; renderView();
      if (v === 'dpk') { const n = S.pop === 'dpk' ? (S.mobile ? null : $('.pop.dpkpop input')) : $('#dayEv [data-a=pop][data-v=dpk]'); if (n) n.focus({ preventScroll: true }); } },
    popClose: () => { S.pop = null; renderView(); },
    setSrc: el => { S.src.mode = el.dataset.m; S.src.key = el.dataset.k || ''; S.pop = null; S.j.limit = J_FIRST; syncUrl(); renderView(); },
    setPeriod: el => {
      const v = el.dataset.v;
      S.g.period = v; S.j.limit = J_FIRST;
      if (v !== 'custom') LS.set('tj_v2_period', v);
      if (v === 'custom') { defaultRange(); S.pop = 'range'; S.rp.which = 'from'; S.rp.ym = (isISO(S.g.to) ? S.g.to : todayISO()).slice(0, 7); }
      else { S.pop = null; if (v === 'all') { S.g.from = ''; S.g.to = ''; } }
      syncUrl(); renderView();
    },
    rpWhich: el => { S.rp.which = el.dataset.v; renderView(); },
    rpMonth: el => { const d = new Date(+S.rp.ym.slice(0, 4), +S.rp.ym.slice(5) - 1 + (+el.dataset.v), 1); S.rp.ym = d.getFullYear() + '-' + pad2(d.getMonth() + 1); renderView(); },
    rpPick: el => {
      const v = clampISO(el.dataset.v);
      if (S.rp.which === 'from') { S.g.from = v; if (!isISO(S.g.to) || S.g.to < v) S.g.to = v; S.rp.which = 'to'; }
      else { S.g.to = v; if (!isISO(S.g.from) || S.g.from > v) S.g.from = v; S.rp.which = 'from'; }
      S.g.period = 'custom'; syncUrl(); renderView();
    },
    jStatus: el => { S.j.status = el.dataset.v; S.j.view = 'cycles'; S.j.limit = J_FIRST; renderView(); },
    jView: el => { S.j.view = el.dataset.v; renderView(); },
    jSort: el => { S.j.sort = J_SORTS.some(x => x[0] === el.dataset.v) ? el.dataset.v : 'recent'; LS.set('tj_v2_j_sort', S.j.sort); renderView(); },
    jTog: el => tog(S.j.open, el.dataset.k),
    jGrp: el => { const k = el.dataset.k, ks = S.j.grpM[k] || [];
      if (el.getAttribute('aria-expanded') === 'true') { S.j.lpGrp.delete(k); ks.forEach(x => S.j.open.delete(x)); } else S.j.lpGrp.add(k);
      renderView(); },
    jReset: () => { S.j.q = ''; S.drafts.jq = ''; S.j.status = 'all'; S.src = { mode: 'all', key: '' }; S.g = { period: 'all', from: '', to: '' }; LS.set('tj_v2_period', 'all'); syncUrl(); renderView(); },
    qClear: el => { const k = el.dataset.v; S.drafts[k] = ''; if (k === 'jq') { S.j.q = ''; S.j.limit = J_FIRST; } else S.u.q = ''; renderView(); const n = $('[data-input="' + k + '"]'); if (n) n.focus(); },
    planCcy: el => { const k = el.dataset.k, to = el.dataset.v === 'USD' ? 'USD' : 'KRW', CY = plCY(); if (!CY) return; const sn = plSnap(k); if (to === sn.cu || !(sn.live && sn.rt > 0)) return;
      ['t:', 's:'].forEach(p => { const v = CY.num(S.drafts[p + k]); if (S.drafts[p + k] != null && v != null && isFinite(v) && v > 0) S.drafts[p + k] = CY.inp(sn.cu === 'KRW' ? v / sn.rt : v, to, sn.rt); });
      sn.cu = to; vib(); renderOverlay(); },
    planSheet: el => { if (S.planSnap && !draft('t:' + el.dataset.k) && !draft('s:' + el.dataset.k)) delete S.planSnap[el.dataset.k];
      const k = el.dataset.k, p = S.D && (S.D.merged.find(x => x.key === k) || S.D.lpCycles.find(x => x.key === k)); uiSheetOpen('plan', k, (p ? (p._lp ? lpNm(p.sym, p._lp.key) : p.sym) + ' · ' : '') + '목표가 · 손절 · 메모', el); },
    feedMore: () => { S.j.feedLimit += 100; renderView(); },
    taxTog: el => { if (!S.taxOpen) S.taxOpen = new Set(); tog(S.taxOpen, el.dataset.v); },
    krwTog: el => { if (!S.krwOpen) S.krwOpen = new Set(); tog(S.krwOpen, el.dataset.v); },
    goKrw: el => { const ym = String(el.dataset.v || ''); S.j.view = 'krw'; if (!S.krwOpen) S.krwOpen = new Set(); if (ym) { S.krwOpen.add(ym); if (S.g.period !== 'all' && !ymPass(ym)) { S.g = { period: 'all', from: '', to: '' }; LS.set('tj_v2_period', 'all'); syncUrl(); } } go('journal'); },
    taxCoin: el => { togSet(S.taxCoinOpen, el.dataset.v); renderView(); },
    taxLzRetry: el => { if (S.taxLz) delete S.taxLz[el.dataset.v]; renderView(); },
    stFx: el => { const k = String(el.dataset.v || ''), r = (S.stfxReg || {})[k]; S.stfxOpen = r ? { k, r } : null; uiSheetOpen('stfx', k, (r ? r.sym + ' ' : '') + '환차 상세', el); },
    savePlan: el => {
      const k = el.dataset.k, CY = plCY(), sn = CY ? plSnap(k) : { cu: 'USD' }, cu = sn.cu;
      if (cu === 'KRW' && !(sn.live && sn.rt > 0)) { toast('지금 환율을 받지 못해 원화로는 저장할 수 없어요 — 달러로 넣어 주세요', true); return; }
      const rdP = p => { const v = CY ? CY.num(draft(p + k)) : parseFloat(draft(p + k)); return v != null && isFinite(v) && v > 0 && cu === 'KRW' ? +(v / sn.rt).toPrecision(8) : v; };
      const t = rdP('t:'), s = rdP('s:');
      if (!(t > 0) && !(s > 0)) { toast('목표가·손절선을 입력하세요 (해제는 [해제] 버튼)', true); return; }
      savePlan(k, { target: t > 0 ? t : undefined, stop: s > 0 ? s : undefined }, '목표가·손절선을 저장했어요 · 1분 간격으로 감시해요');
    },
    clearPlan: el => { const k = el.dataset.k; confirmAsk({ title: '목표가·손절선을 해제할까요?', body: '감시를 멈추고 목표가·손절선을 지워요.' + (S.D.plansMemoOk ? ' 메모는 그대로 남아요.' : ' 메모는 계획이 있어야 표시돼요.'), ok: '해제', danger: true, run: () => savePlan(k, { target: null, stop: null }, '목표가·손절선을 해제했어요') }); },
    dmEd: el => { const k = el.dataset.k || '', iso = k.slice(0, 10), sym = k.slice(11); if (!isISO(iso) || !dmSym(sym)) return;
      const c = dmGet(iso, sym); S.dm.ed = k; S.drafts['dm:' + k] = c ? c.memo : ''; renderView(); renderOverlay();
      const n = dmInput(k); if (n) { n.focus(); try { n.setSelectionRange(n.value.length, n.value.length); } catch (e) {  } } },
    dmCancel: el => { const k = el.dataset.k || ''; if (S.dm.ed === k) S.dm.ed = null; delete S.drafts['dm:' + k]; if (document.activeElement && document.activeElement.blur) document.activeElement.blur(); renderView(); renderOverlay(); },
    dmMore: el => { const iso = el.dataset.v; if (!isISO(iso)) return; S.dm.more[iso] = !S.dm.more[iso]; renderView(); },
    dmSheet: el => { const iso = el.dataset.v; if (!isISO(iso)) return; uiSheetOpen('dmemo', iso, (+iso.slice(5, 7)) + '/' + (+iso.slice(8, 10)) + ' 그날 매매 근거', el); },
    dmSave: el => {
      const k = el.dataset.k || '', iso = k.slice(0, 10), sym = k.slice(11);
      if (!isISO(iso) || !dmSym(sym) || dmSym(sym) !== sym || S.dm.busy) return;
      const c = dmGet(iso, sym), dv = S.drafts['dm:' + k], v = String(dv == null ? (c ? c.memo : '') : dv).trim();
      if (v.length > DM_MAX) { toast('근거는 ' + DM_MAX + '자까지예요', true); return; }
      if (!v && !c) { toast('근거를 적어 주세요', true); return; }
      S.dm.busy = true;
      post('/api/day_memo', { date: iso, sym, memo: v }, d => d.changed === false ? '바뀐 내용이 없어요' : !v ? '근거를 지웠어요' : d.reeval ? '근거를 저장했어요 · 그 영수증 AI 평가를 새 근거로 다시 만들어요' : '근거를 저장했어요')
        .then(d => {
          S.dm.busy = false;
          if (!d) return;
          S.dm.local = Object.assign({}, S.dm.local, { [k]: { memo: String(d.memo || ''), at: num(d.at) || Math.floor(Date.now() / 1000) } });
          delete S.drafts['dm:' + k];
          if (S.dm.ed === k) S.dm.ed = null;
          const ae = document.activeElement; if (ae && ae.blur && ae.getAttribute && ae.getAttribute('data-draft') === 'dm:' + k) ae.blur();
          const R = S.rcpt;
          if (d.changed !== false && S.drawer === 'rcpt' && R && R.iso === iso && (dmSym(R.csym || R.sym) === sym || dmSym(R.sym) === sym)) {
            if (S.rcptE) { delete S.rcptE[rcSK(R)]; delete S.rcptE[rcSK(R, 'buy')]; }
            setTimeout(() => { if (S.rcpt === R && rcOn(R)) { rcLoad(true); rcbLoad(true); } }, 600);
          }
          renderView(); renderOverlay();
        }, () => { S.dm.busy = false; });
    },
    rcptDmDay: () => { const R = S.rcpt; if (!R) return; wkOff(); S.day = R.iso.slice(5); S.calYM = R.iso.slice(0, 7); closeDrawer(true);
      const go = () => setTimeout(() => { const c = document.querySelector('#view .dmemo'); if (c) c.scrollIntoView({ block: 'center' }); }, 80);
      if (S.tab !== 'daily') { location.hash = 'daily'; go(); } else { renderView(); go(); } },
    saveMemo: el => { const k = el.dataset.k; if (!S.D.plansMemoOk && !S.D.plans[k]) { toast('목표가·손절선을 먼저 저장해야 메모가 보여요', true); return; } savePlan(k, { memo: draft('m:' + k) }, '메모를 저장했어요'); },
    pickDay: el => { wkOff(); S.day = el.dataset.v; S.calYM = ymOf(S.day) || S.calYM; S.dayEvLimit = 20; renderView();
      if (S.mobile && S.tab === 'daily' && el.closest) dayCardShow(true); },
    calMonth: el => { const d = new Date(+S.calYM.slice(0, 4), +S.calYM.slice(5) - 1 + (+el.dataset.v), 1); S.calYM = d.getFullYear() + '-' + pad2(d.getMonth() + 1); renderView(); },
    calToday: () => { wkOff(); S.day = S.D.todayKey; S.calYM = ymOf(S.day) || ymShift(0); renderView(); },
    calView: el => { LS.set('tj_v2_dcal', el.dataset.v === 'list' ? 'list' : 'cal'); vib(); renderView(); },
    dayStep: el => {
      const iso = isoDay(S.day); if (!iso) return;
      const d = new Date(iso + 'T00:00:00'); d.setDate(d.getDate() + (+el.dataset.v));
      const nIso = d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
      if (nIso > (isoDay(S.D.todayKey) || todayISO()) || nIso < rollMinISO()) return;
      wkOff(); S.day = nIso.slice(5); S.calYM = nIso.slice(0, 7); renderView();
    },
    dayMore: () => { S.dayEvLimit += 60; renderView(); },
    dayGrp: el => { const g = el.dataset.v, st = S.dayGrpOpen || (S.dayGrpOpen = new Set()); if (st.has(g)) st.delete(g); else st.add(g); renderView(); },
    dayRetry: el => { const iso = el.dataset.v; if (S.dayFull) delete S.dayFull[iso]; renderView(); },
    uGrp: (el, ev) => { if (ev && ev.target.closest('[data-a="bulkSpam"]')) return; tog(S.u.open, el.dataset.v === 'bal' ? 'bal' : el.dataset.v); },
    uItem: el => tog(S.u.item, el.dataset.k),
    uMore: el => { S.u.limit[el.dataset.v] = (S.u.limit[el.dataset.v] || (el.dataset.v === 'hid' ? 40 : 30)) + (el.dataset.v === 'hid' ? 40 : 30); renderView(); },
    uHidden: () => { S.u.showHidden = !S.u.showHidden; renderView(); },
    goHidden: () => { S.u.showHidden = true; S.u.q = ''; S.drafts.uq = ''; go('unmatched'); setTimeout(() => { const b = document.getElementById('uHidGrp'); if (b) b.scrollIntoView({ block: 'start' }); }, 120); },
    evHidden: () => { S.j.evHid = !S.j.evHid; renderView(); },
    evDayGo: el => openDay(String(el.dataset.v || '')),
    bulkSpam: () => { const ks = S.D.pendings.filter(p => p._cat === 'spam' && p.hide).map(p => p.key); confirmAsk({ title: '숨긴 스팸 ' + ks.length + '건을 목록에서 지울까요?', body: '자동으로 숨긴 스팸·소액 토큰을 미매칭 목록에서 완전히 빼요. 같은 건이 다시 감지돼도 나타나지 않아요.', ok: '전부 지우기', danger: true, run: () => ignoreKeys(ks) }); },
    ignore: el => { const k = el.dataset.k, p = pendByKey(k); confirmAsk({ title: '이 항목을 목록에서 숨길까요?', body: (p ? (p.sym && p.sym !== '—' ? p.sym + ' · ' : '') + term(p.kind) + '\n' : '') + '같은 건이 다시 감지돼도 나타나지 않아요. 원장·손익은 바뀌지 않아요.', ok: '숨기기', danger: true, run: () => ignoreKeys([k], '1건') }); },
    riskRestore: el => { const k = el.dataset.k, p = pendByKey(k), g = (p && p.gkey) || (k.match(/^risk:(g\d+)$/) || [])[1]; if (!g) return; confirmAsk({ title: '정상 자산으로 복원할까요?', body: (p ? p.sym + (p.chain ? ' (' + p.chain + ')' : '') : g) + ' 를 스팸 격리에서 풀어 메인 목록·일별 기록에 다시 포함해요.', ok: '복원', run: () => post('/api/risk_override', { key: g, verdict: 'visible' }, '복원했어요 · 다음 갱신에 목록에 나타나요') }); },
    riskSpam: el => { const k = el.dataset.k, p = pendByKey(k), g = (p && p.gkey) || (k.match(/^risk:(g\d+)$/) || [])[1]; if (!g) return; post('/api/risk_override', { key: g, verdict: 'spam' }, '스팸으로 확정했어요 · 숨긴 항목으로 옮겨요'); },
    costUnit: el => costUnit(el.dataset.k),
    costMarket: el => { const p = pendByKey(el.dataset.k); if (!p || !p.gkey) return; confirmAsk({ title: '당시 시세로 원가를 추정할까요?', body: p.sym + ' 원가 미확인 수량의 원가를 들어온 날의 시세로 잡아요. 화면 계산만 바뀌고 원장은 그대로예요.', ok: '적용', run: () => post('/api/cost_override', { key: p.gkey, mode: 'market' }, '원가를 적용했어요 · 평가·손익을 다시 계산해요') }); },
    costBe: el => { const p = pendByKey(el.dataset.k); if (!p || !p.gkey) return;
      const D = S.D, rows = D.pendVis.concat(D.pendHid).filter(x => x._cat === 'unv' && x.gkey === p.gkey);
      const L = rows.length ? rows : [p], n = sum(L, x => parseInt(String(x.gap || '').replace(/,/g, ''), 10) || 1), qt = sum(L, x => num(x.qty)), us = sum(L, x => num(x.usd));
      confirmAsk({ title: p.sym + ' 매도를 손익 0으로 처리할까요?', pvx: true, ok: '손익 0으로 처리',
        bodyHtml: beScopeHTML(p.sym, n, qt, us) + '<span class="pvx"><br>범위: 지금까지의 원가 미상 매도 전부 · 이후 새로 생기는 매도는 다시 원가 미확인으로 떠요.<br>매수가를 매도가와 같게 봐서 손익 0으로 계산해요 — 언제든 되돌릴 수 있어요.</span>',
        run: () => post('/api/cost_override', { key: p.gkey, mode: 'breakeven' }, '손익 0으로 처리했어요 · 다시 계산해요') }); },
    costClear: el => { const p = pendByKey(el.dataset.k); if (!p || !p.gkey) return; post('/api/cost_override', { key: p.gkey, mode: 'clear' }, '원가 지정을 해제했어요'); },
    costBeUndo: el => { const k = el.dataset.k; if (!/^g\d+$/.test(String(k || ''))) return; const r = arr(S.D.costDecided).find(x => x.gkey === k) || {};
      confirmAsk({ title: '손익 0 처리를 되돌릴까요?', pvx: true, ok: '되돌리기',
        bodyHtml: (r.sym ? beScopeHTML(r.sym, num(r.n), num(r.qty), num(r.usd)) + '<br>' : '') + '<span class="pvx">' + esc(el.dataset.s || '') + ' 매도가 다시 원가 미확인 매도로 돌아가요(실현손익에서 빠짐).</span>',
        run: () => post('/api/cost_override', { key: k, mode: 'breakeven_clear' }, '되돌렸어요 · 다시 계산해요') }); },
    costClearKey: el => { const k = el.dataset.k, be = el.dataset.m === 'breakeven', r = be ? (arr(S.D.costDecided).find(x => x.gkey === k) || {}) : {}; confirmAsk({ title: be ? '손익 0 처리를 되돌릴까요?' : '원가 지정을 해제할까요?', body: be ? el.dataset.s + ' 매도가 다시 원가 미확인 매도로 돌아가요(실현손익에서 빠짐).' : el.dataset.s + ' 의 원가 지정을 지워요. 해당 건은 다시 미매칭에 나타나요.',
      bodyHtml: be && r.sym ? beScopeHTML(r.sym, num(r.n), num(r.qty), num(r.usd)) + '<br><span class="pvx">' + esc(el.dataset.s || '') + ' 매도가 다시 원가 미확인 매도로 돌아가요(실현손익에서 빠짐).</span>' : undefined, ok: be ? '되돌리기' : '해제', danger: !be, pvx: be, run: () => post('/api/cost_override', { key: k, mode: be ? 'breakeven_clear' : 'clear' }, be ? '되돌렸어요 · 다시 계산해요' : '원가 지정을 해제했어요') }); },
    ofView: el => { S.of.view = el.dataset.v; renderView(); },
    saleTog: el => { const off = el.dataset.off === '1', lot = el.dataset.v;
      confirmAsk({ title: off ? '토큰 세일 연결을 끊을까요?' : '다시 연결할까요?', body: off ? '경매 입찰 원가를 이 토큰에서 풀어요. 세일로 받은 수량은 원가 미확인(실현 제외)으로 돌아가요. 언제든 다시 연결할 수 있어요.' : '경매 입찰 원가(참여 − 환불)를 받은 토큰에 다시 이어 실현손익에 반영해요.',
        ok: off ? '연결 끊기' : '다시 연결', danger: off, run: () => post('/api/sale_link', { lot, off }, off ? '연결을 끊었어요 · 다시 계산해요' : '다시 연결했어요 · 다시 계산해요') }); },
    xferTog: el => { const off = el.dataset.off === '1', dep = el.dataset.v;
      confirmAsk({ title: off ? '이 연결을 끊을까요?' : '다시 연결할까요?', body: off ? '두 거래소 전송의 원가 승계를 풀어요. 이 입금으로 산 수량은 원가 미확인(실현 제외)으로 돌아가요. 언제든 다시 연결할 수 있어요.' : '출금 원가를 이 입금으로 다시 이어 실현손익에 반영해요.',
        ok: off ? '연결 끊기' : '다시 연결', danger: off, run: () => post('/api/xfer_link', { dep, off }, off ? '연결을 끊었어요 · 다시 계산해요' : '다시 연결했어요 · 다시 계산해요') }); },
    wdReg: el => { const a = el.dataset.v;
      confirmAsk({ title: '내 지갑으로 등록할까요?', body: short(a) + ' 를 내 지갑으로 등록하면 수집기가 이 주소의 과거 이력을 가져와 거래소 출금 원가를 이어요. 내 지갑이 아니면 등록하지 마세요.',
        ok: '등록', run: () => post('/api/wd_dest_register', { address: a }, d => '등록했어요' + (d && d.restartNeeded ? ' · 수집기 재시작 뒤 과거 이력을 가져와요' : ' · 과거 이력을 가져오는 중이에요')) }); },
    ofTog: el => tog(S.of.open, el.dataset.k),
    flowRec: el => { const k = el.dataset.k; if (S.of.fr.has(k)) S.of.fr.delete(k); else S.of.fr.add(k); renderView(); },
    flowReg: el => { const a = el.dataset.k, r = ofByAddr(el.dataset.v), x = r && r.flow ? r.flow.recips.find(y => y.addr === a) : null;
      confirmAsk({ title: '내 지갑으로 등록할까요?', body: short(a) + ' 를 추적 지갑에 추가해요' + (x && x.chains.length ? '(' + x.chains.map(c => CHAIN_KO[c] || c).join(' · ') + ')' : '') + '.\n근거: ' + (x ? x.score.ev.map(e => hs(e.t, 1)).join(' · ') : '') + '\n' + (ofAuto() ? '곧 자동으로 수집을 시작해 과거 내역을 채워요.' : '수집기가 다시 시작되면 과거 내역을 채워요.'), ok: '등록',
        run: () => post('/api/flow_register', { address: a }, d => (d && d.restartNeeded ? '내 지갑으로 등록했어요 · 수집기 재시작 뒤 반영돼요' : '내 지갑으로 등록했어요')) }); },
    ofPick: el => { const a = el.dataset.k; S.of.form[a] = S.of.form[a] === el.dataset.v ? '' : el.dataset.v; vib(); renderView(); },
    ofChain: el => { const a = el.dataset.k, k = 'of:' + a + ':chains', r = ofByAddr(a); const cur = S.drafts[k] != null ? String(S.drafts[k]).split(',').filter(Boolean) : (r ? r.chains.slice() : []); const i = cur.indexOf(el.dataset.v); if (i >= 0) cur.splice(i, 1); else cur.push(el.dataset.v); S.drafts[k] = cur.join(','); renderView(); },
    ofEx: el => { S.drafts['of:' + el.dataset.k + ':ex'] = el.dataset.v; renderView(); },
    ofCat: el => { S.drafts['of:' + el.dataset.k + ':cat'] = el.dataset.v; renderView(); },
    ofSave: el => {
      const a = el.dataset.k, v = el.dataset.v, r = ofByAddr(a), dk = k => draft('of:' + a + ':' + k);
      if (v === 'own' && r && (r.noAddr || (r.exwdOnly && !r.chains.length))) {
        confirmAsk({ title: '내 지갑으로 기록할까요?', body: ofName(r) + jo(ofName(r), '을', '를') + ' 내 지갑으로 간 것으로 기록해요(추적 지갑 추가 없음). 되돌리기로 언제든 취소할 수 있어요.', ok: '기록', run: () => ofResolve(a, 'own', { alias: dk('alias') || undefined }, '내 지갑으로 기록했어요') });
      } else if (v === 'own') {
        const chs = S.drafts['of:' + a + ':chains'] != null ? String(S.drafts['of:' + a + ':chains']).split(',').filter(Boolean) : (r ? r.chains : []);
        if (!chs.length) { toast('추적할 체인을 하나 이상 고르세요', true); return; }
        confirmAsk({ title: '내 지갑으로 등록할까요?', body: short(a) + ' 를 ' + (dk('alias') || '새 지갑') + ' 이름으로 추적 지갑에 추가해요.\n' + (ofAuto() ? '곧 자동으로 수집을 시작해' : '수집기가 다시 시작되면') + ' 과거 내역을 채우고, 이 주소로 보낸 전송은 내 지갑 간 이동으로 바뀌어요.', ok: '등록', run: () => ofResolve(a, 'own', { alias: dk('alias') || undefined, chains: chs }) });
      } else if (v === 'exchange') {
        const ex = dk('ex'); if (!ex) { toast('거래소를 고르세요', true); return; }
        ofResolve(a, 'exchange', { exchange: ex, chains: r ? r.chains : undefined }, (EX_NAMES[ex] || ex) + ' 입금 주소로 저장했어요 · 1분 안에 원가가 이어져요');
      } else if (v === 'external') {
        const cat = dk('cat'); if (!cat) { toast('사유를 고르세요', true); return; }
        confirmAsk({ title: '외부 유출로 확정할까요?', body: ofName(r || { address: a }) + jo(ofName(r || { address: a }), '으로', '로') + ' 보낸 ' + (r ? m(r.usdAtSend || r.usdNow) + jo(m(r.usdAtSend || r.usdNow), '을', '를') : '것을') + ' "' + ofCatLbl(cat) + '"' + jo(ofCatLbl(cat), '으로', '로') + ' 기록해요. 되돌리기로 언제든 취소할 수 있어요.', ok: '확정', danger: true, run: () => ofResolve(a, 'external', { category: cat, memo: dk('memo') || undefined }, '외부 유출로 기록했어요') });
      }
    },
    ofOwnQuick: el => { const a = el.dataset.k, r = ofByAddr(a); confirmAsk({ title: '내 지갑으로 등록할까요?', body: short(a) + ' 를 추적 지갑에 추가해요(' + (r ? r.chainNames.join(' · ') : '') + ').\n근거: ' + ((r && r.suggest && r.suggest.evidence) || '') + '\n' + (ofAuto() ? '곧 자동으로 수집을 시작해' : '수집기가 다시 시작되면') + ' 과거 내역을 채우고, 이 주소로 보낸 전송은 내 지갑 간 이동으로 바뀌어요.', ok: '등록', run: () => ofResolve(a, 'own', { alias: short(a), chains: r ? r.chains : undefined }) }); },
    ofRetQuick: el => { const a = el.dataset.k; confirmAsk({ title: '되돌려 받음으로 정리할까요?', body: short(a) + ' 는 흐름 추적으로 보낸 돈 이상을 돌려받았어요(직접·경유·거래소·브릿지).\n\'정리된 내역\'으로 옮기고 확인 필요 합계에서 빼요. 원장·손익은 그대로예요.', ok: '정리', run: () => post('/api/outflow_resolve', { address: a, op: 'ret', on: true }, '되돌려 받음으로 정리했어요') }); },
    flowAll: el => { const a = el.dataset.k; if (S.of.fa.has(a)) S.of.fa.delete(a); else S.of.fa.add(a); renderView(); },
    flowSpoof: el => { const a = el.dataset.k; if (S.of.fsp.has(a)) S.of.fsp.delete(a); else S.of.fsp.add(a); renderView(); },
    ofUndo: el => { const a = el.dataset.k, r0 = (S.D.of || []).find(r => r.address === a);
      if (r0 && r0.retOk) return confirmAsk({ title: '되돌려 받음 정리를 되돌릴까요?', body: short(a) + ' 를 다시 "확인 필요"로 돌려요.', ok: '되돌리기', run: () => post('/api/outflow_resolve', { address: a, op: 'ret', on: false }, '되돌렸어요') });
      const au = r0 && !r0.verdict && (r0.matched || r0.bucket === 'returned' || r0.brU || !!r0.autoMatch); confirmAsk({ title: au ? '자동 매칭을 끌까요?' : '판정을 되돌릴까요?', body: au ? short(a) + ' 의 ' + (r0.matched ? (r0.bucket === 'bridge' ? '브릿지 자동 매칭(원가 이관)' : '거래소 입금 자동 매칭(원가 이관)') : r0.brU ? '브릿지 라벨' : r0.bucket === 'returned' ? '되돌려 받음 상쇄' : '일부 자동 매칭(원가 이관)') + '을 끄고 다시 "확인 필요"로 돌려요.' : short(a) + ' 를 다시 "확인 필요"로 돌려요. 내 지갑 등록은 설정에 남아요(지갑 삭제는 ‘연결 · 키’에서).', ok: '되돌리기', run: () => ofResolve(a, 'clear', {}, '되돌렸어요') }); },
    ofMore: () => { S.of.limit += 30; renderView(); },
    ofMemoEd: el => { const a = el.dataset.k || null, r = a ? ofByAddr(a) : null; S.of.memoEd = a; if (a) S.drafts['ofm:' + a] = r ? r.memo : ''; renderView();
      if (a) { const n = $('.ofmemo.ed input'); if (n) { n.focus(); try { n.setSelectionRange(n.value.length, n.value.length); } catch (e) {  } } } },
    ofMemoSave: el => { const a = el.dataset.k, r0 = ofByAddr(a), v = String(S.drafts['ofm:' + a] == null ? (r0 && !S.of.memoEd ? r0.memo : '') : S.drafts['ofm:' + a]).trim();
      if (v.length > 200) { toast('메모는 200자까지예요', true); return; }
      post('/api/outflow_resolve', { address: a, op: 'memo', memo: v }, v ? '메모를 저장했어요' : '메모를 지웠어요').then(d => { if (d) { S.of.memoEd = null; delete S.drafts['ofm:' + a]; renderView(); } }); },
    ofLkOpen: el => { const a = el.dataset.k; S.of.lk = { a, sel: new Map() }; delete S.drafts.oflq; ofLkLoad(a); renderView(); },
    ofLkClose: () => { S.of.lk = null; renderView(); },
    ofLkTog: el => { const a = el.dataset.v; if (a && (!S.of.lk || S.of.lk.a !== a)) S.of.lk = { a, sel: new Map() };
      const lk = S.of.lk; if (!lk) return; const k = el.dataset.k;
      if (lk.sel.has(k)) lk.sel.delete(k);
      else { const c = S.of.lkc[lk.a], x = c && arr(c.rows).find(y => y.key === k); if (x) lk.sel.set(k, { key: x.key, stable: !!x.stable, qty: num(x.qty), sym: x.sym }); }
      vib(); renderView(); },
    ofLkTab: el => { S.of.lkTab = el.dataset.v; renderView(); },
    ofLkAll: el => { const a = el.dataset.k, o = ofLkOpt(a); o.all = !o.all; if (!S.of.lk || S.of.lk.a !== a) S.of.lk = { a, sel: new Map() }; ofLkLoad(a); renderView(); },
    ofLkSpam: el => { const a = el.dataset.k, o = ofLkOpt(a); o.spam = !o.spam; if (!S.of.lk || S.of.lk.a !== a) S.of.lk = { a, sel: new Map() }; ofLkLoad(a); renderView(); },
    ofCatSet: el => { const a = el.dataset.k, c = el.dataset.v, r = ofByAddr(a); if (!r || r.category === c) return; ofResolve(a, 'external', { category: c }, '분류를 ' + ofCatLbl(c) + jo(ofCatLbl(c), '으로', '로') + ' 바꿨어요').then(d => { if (d) S.of.open.add(a); }); },
    ofLkSave: el => { const a = el.dataset.k, lk = S.of.lk; if (!lk || lk.a !== a || !lk.sel.size) return;
      const pick = [...lk.sel.values()], tk = pick.filter(x => !x.stable).length, rf = pick.length - tk;
      post('/api/outflow_resolve', { address: a, op: 'link', links: pick.map(x => ({ kind: x.stable ? 'refund' : 'tokens', key: x.key })) },
        '연결했어요' + (tk ? ' · 세일 토큰 ' + tk + '건 원가 = 참가금' : '') + (rf ? ' · 환불 ' + rf + '건' : '')).then(d => { if (d) { S.of.lk = null; delete S.of.lkc[a]; renderView(); } }); },
    ofLkUn: el => { const a = el.dataset.k, k = el.dataset.v, r = ofByAddr(a), l = r && r.links.find(x => x.key === k);
      confirmAsk({ title: '연결을 풀까요?', body: (l ? q(l.qty) + ' ' + l.sym + ' ' + (l.kind === 'refund' ? '환불' : '세일 토큰') : '이 유입') + ' 연결을 풀어요.' + (l && l.kind === 'tokens' ? ' 그 유입은 다시 원가 미확인이 돼요.' : ''), ok: '연결 해제',
        run: () => post('/api/outflow_resolve', { address: a, op: 'unlink', key: k }, '연결을 풀었어요').then(d => { if (d) delete S.of.lkc[a]; }) }); },
    ofLegTog: el => { const a = el.dataset.k, k = el.dataset.v, r = ofByAddr(a), off = r && r.excludeLegs.indexOf(k) >= 0;
      post('/api/outflow_resolve', { address: a, op: off ? 'include' : 'exclude', key: k }, off ? '참가금에 다시 넣었어요' : '참가금에서 뺐어요').then(d => { if (d) S.of.open.add(a); }); },
    ofSaleAlert: () => { const on = !S.D.saleAlert; post('/api/outflow_resolve', { op: 'salealert', on }, on ? '후보 알림을 켰어요' : '후보 알림을 껐어요'); },
    ofWaitGo: () => { S.of.view = 'history'; S.of.reason = '세일 참가금'; S.of.period = 'all'; S.of.coin = ''; S.of.limit = 30; uiPgReset('ofh'); renderView(); },
    ofHidden: () => { S.of.showHidden = !S.of.showHidden; if (S.of.showHidden && !D0().ofPend.length) S.of.view = 'history'; renderView(); },
    setDust: el => setDust(+el.dataset.v),
    dustCustom: () => { const v = parseFloat(draft('dust')); if (isFinite(v) && v >= 0) { delete S.drafts.dust; setDust(v); } else toast('0 이상의 금액($)을 입력하세요', true); },
    wkTog: el => { S.wkOpen = S.wkOpen === el.dataset.v ? null : el.dataset.v; render(); },
    wkPick: el => { const wk = el.dataset.v, f = el.dataset.f || '', t = el.dataset.t || '', cur = wkSelNow(); S.wkSel = cur && cur.wk === wk && (cur.f || '') === f ? null : { wk, from: el.dataset.d, f, t, day: S.day || S.D.todayKey }; S.wkMore = null;
      if (S.wkSel && f && S.calYM !== f.slice(0, 7)) S.calYM = f.slice(0, 7);
      vib(); renderView();
      if (S.wkSel) { const h = document.querySelector('.wkpanel .wkt'); if (h) { try { h.focus({ preventScroll: !S.mobile }); } catch (e) {  } } }
      if (S.wkSel && S.mobile) setTimeout(() => { const p = document.querySelector('.wkpanel'); if (p) p.scrollIntoView({ block: 'start', behavior: 'smooth' }); }, 60); },
    wkClose: () => { const w = S.wkSel; S.wkSel = null; S.wkMore = null; renderView();
      if (w) { const c = [...document.querySelectorAll('#view [data-a="wkPick"]')].find(x => x.getAttribute('data-v') === w.wk && (!w.f || x.getAttribute('data-f') === w.f)); if (c) { try { c.focus({ preventScroll: true }); } catch (e) {  } } } },
    wkMore: el => { S.wkMore = S.wkMore === el.dataset.v ? null : el.dataset.v; renderView(); },
    wkDay: el => { wkOff(); S.day = el.dataset.v; S.calYM = ymOf(S.day) || S.calYM; S.dayEvLimit = 20; renderView(); },
    gasCost: () => { const on = !(S.D.taxGas && S.D.taxGas.on !== false); confirmAsk({ title: '가스 반영을 ' + (on ? '켤까요?' : '끌까요?'), body: on ? '스왑 매수 가스는 취득 원가에, 스왑 매도 가스는 그 매도의 실현에서, 매매 외 가스(실패·승인·전송·브릿지·LP)는 그날 실현에서 빼요. 실현손익·세금 명세·일별 기록이 다시 계산돼요.' : '온체인 가스를 원가·실현에서 빼고 가스·수수료 탭에 따로 표시만 해요(거래소 체결 수수료는 그대로 원가·실현에 반영). 실현손익·세금 명세·일별 기록이 다시 계산돼요.', ok: on ? '켜기' : '끄기', run: () => post('/api/gas_in_cost', { on }, '가스 반영 ' + (on ? '켬' : '끔') + ' · 다시 계산해요') }); },
    revLen: async el => { const [kind, len] = String(el.dataset.v || '').split(':'), rl = S.D && S.D.reviewLen;
      const it = rl && (REV_LEN[kind] || []).find(x => x[0] === len);
      if (!it || rl[kind] === len) return;
      const prev = rl[kind]; S.D.reviewLen = Object.assign({}, rl, { [kind]: len }); renderView();
      const d = await post('/api/review_len', { kind, len }, (kind === 'daily' ? '일간' : '주간') + ' 리뷰 분량 ' + it[1] + ' · 새로 쓰는 리뷰부터 적용돼요');
      if (!d && S.D && S.D.reviewLen) { S.D.reviewLen = Object.assign({}, S.D.reviewLen, { [kind]: prev }); renderView(); } },
    revPause: async () => { const rp = S.D && S.D.reviewPause; if (!rp) return;
      const on = !rp.on, prev = rp; S.D.reviewPause = { on, at: Math.floor(Date.now() / 1000) }; renderView();
      const d = await post('/api/review_pause', { on }, on ? 'AI 리뷰 자동 생성 멈춤 — 지금 쓰는 한 건 뒤로 새로 쓰지 않아요' : 'AI 리뷰 자동 생성 다시 켬 — 다음 회차부터 이어서');
      if (!d && S.D) { S.D.reviewPause = prev; renderView(); } else if (d && d.reviewPause && S.D) { S.D.reviewPause = d.reviewPause; renderView(); } },
    revFillAll: () => { const P = S.D && S.D.reviewProg, bl = (P && P.backlog) || {}, n = num((bl.daily || {}).manual), w = num((bl.weekly || {}).manual), rf = S.D && S.D.reviewFill;
      if (!P || !(n || w)) return;
      const par = Math.max(1, num(rf && rf.parallel) || 1), secs = num(P.avgSec) * (n + w) / par;
      confirmAsk({ title: '지난 리뷰를 전체 채울까요?', ok: '전체 채우기',
        body: '지난 리뷰 일간 ' + n + ' · 주간 ' + w + '을 ' + (rf && rf.order === 'oldest' ? '오래된 날부터' : '최근 날부터') + ' 써요 · Claude 사용량을 써요 · '
          + (secs > 0 ? '약 ' + rpDur(Math.max(60, Math.round(secs / 60) * 60)) + (par > 1 ? '(동시에 ' + par + '건)' : '') : '걸리는 시간은 시작 뒤 진행 칸에 보여요') + '. 자동 생성 멈춤으로 언제든 세울 수 있어요.',
        run: () => post('/api/review/fill', {}, d => (d && d.msg) || '요청했어요') }); },
    revFill: async el => { const v = String(el.dataset.v || ''), rf = S.D && S.D.reviewFill, it = REV_FILL.find(x => x[0] === v);
      if (!it || !rf) return;
      const [order, p9] = v.split(':'), parallel = +p9;
      if (rf.order === order && num(rf.parallel) === parallel) return;
      const prev = rf; S.D.reviewFill = { order, parallel }; renderView();
      const d = await post('/api/review_fill', { order, parallel }, 'AI 리뷰 채우는 순서 · ' + it[1] + ' · 다음 작업부터 적용돼요');
      if (!d && S.D) { S.D.reviewFill = prev; renderView(); } },
    offcSelf: el => { const o = (S.D.offc || []).find(x => x.ex === el.dataset.v); if (!o) return; const on = el.dataset.m === 'on' ? true : !o.on, nm = esc(o.name);
      if (on === o.on) return;
      const top = o.bySym.filter(b => !b.stable && num(b.wdCost) >= 1).slice(0, 5).map(b => esc(b.sym) + ' ' + m(num(b.wdCost), { compact: true })).join(' · ');
      confirmAsk({ title: on ? o.name + ' 오프체인 이체를 내 계정 간 이동으로 가정할까요?' : o.name + ' 오프체인 이체 가정을 끌까요?', pvx: true, ok: on ? '가정하기' : '끄기',
        bodyHtml: on ? '<span class="pvx">출금 ' + o.wdN + '건 · 입금 ' + o.depN + '건 · ' + o.syms + '종</span> · 보낸 코인 원가 ' + m(o.coinCost) + (o.stableCost >= 1 ? ' <span class="pvx">(스테이블은 액면 그대로)</span>' : '')
            + (top ? '<br><span class="cap">' + top + '</span>' : '')
            + '<br><br>보낸 원가를 같은 코인의 돌아온 ' + nm + ' 오프체인 입금이 먼저 보낸 것부터 이어받아요(보내기 전에 들어온 입금은 제외). 보낸 것보다 많이 돌아온 몫만 원가 미확인으로 남아요. '
            + '확정이 아니라 가정이라 기록·매도 줄에 ‘내 계정으로 가정’이 붙고, 보낸 내역 ‘내 다른 ' + nm + ' 계정(가정)’에서 건수·원가를 보고 주소별로 뺄 수 있어요. 원장은 그대로이고 언제든 끌 수 있어요.'
          : '<span class="pvx">돌아온 입금 ' + o.inhN + '건</span>이 이어받은 코인 원가(' + m(o.inhCoin) + ')가 빠지고, 오프체인 출금은 다시 받는 주소 미상 출금(원가 유출) · 돌아온 입금은 원가 없는 유입으로 돌아가요.',
        run: () => post('/api/offchain_self', { ex: o.ex, on }, o.name + ' 오프체인 이체 ' + (on ? '내 계정 간 이동으로 가정' : '가정 끔(종전대로)') + ' · 다시 계산해요') }); },
    offcNo: el => { const o = (S.D.offc || []).find(x => x.ex === el.dataset.v); if (!o) return;
      post('/api/offchain_self', { ex: o.ex, on: false }, '아니요로 저장했어요 · 설정에서 언제든 바꿀 수 있어요'); },
    offcAddr: el => { const ex = el.dataset.v, a = el.dataset.k, excl = el.dataset.m === 'on';
      confirmAsk({ title: excl ? '이 주소로 간 오프체인 출금을 남에게 보낸 것으로 볼까요?' : '이 주소를 다시 내 계정으로 가정할까요?', ok: excl ? '남의 주소로 빼기' : '되돌리기',
        bodyHtml: '<span class="mono">' + esc(short(a)) + '</span><br><br>' + (excl ? '이 주소로 간 출금은 가정에서 빠져 받는 주소 미상 출금(원가 유출)으로 돌아가요. 돌아온 입금은 남은 다른 출금의 원가만 이어받아요.' : '이 주소로 간 출금 원가를 다시 돌아온 입금이 이어받아요(가정).'),
        run: () => post('/api/offchain_self', { ex, addr: a, excl }, excl ? '남의 주소로 뺐어요 · 다시 계산해요' : '되돌렸어요 · 다시 계산해요') }); },
    fsNoteX: () => { S.fsNoteX = true; renderChrome(); post('/api/first_seen_px', { note: true }, ''); },
    firstSeen: () => { const fs = S.D.firstSeen; if (!fs) return; const on = !fs.on; confirmAsk({ title: '최초 인식 시가를 ' + (on ? '켤까요?' : '끌까요?'), body: on ? '원가를 모르는 수량(기초 잔고·원가 없는 입금·에어드랍 등)의 원가를 그 수량이 장부에 처음 생긴 날 시가로 잡아 실현·명세에 넣어요(추정 표시). 그날 시세가 없으면 원가 미확인으로 남아요.' : '원가를 모르는 수량을 다시 원가 미확인으로 두고 실현에서 빼요(미매칭에서 직접 원가를 넣을 수 있어요).', ok: on ? '켜기' : '끄기', run: () => post('/api/first_seen_px', { on }, '최초 인식 시가 ' + (on ? '켬' : '끔') + ' · 다시 계산해요') }); },
    fallback: () => { const on = !S.D.fallbackOn; confirmAsk({ title: '평균가 대체를 ' + (on ? '켤까요?' : '끌까요?'), body: on ? '원가 없는 보유·매도를 종목 평균 매수가로 원가 처리해 평가·손익·실현에 반영해요.' : '원가 미확인 수량을 다시 손익 계산에서 빼요.', ok: on ? '켜기' : '끄기', run: () => post('/api/fallback_avg', { on }, '평균가 대체 ' + (on ? '켬' : '끔') + ' · 다시 계산해요') }); },
    aliasEdit: el => { S.aliasEdit = el.dataset.k; renderView(); const i = $('[data-alias]'); if (i) { i.focus(); i.select(); } },
    bfReq: () => {
      const d = draft('bfDate'), sec = draft('bfSec');
      if (!/^\d{4}-\d{2}-\d{2}$/.test(d || '')) { toast('시작 날짜를 고르세요', true); return; }
      const body = sec ? { per: { [sec]: d } } : { since: d };
      confirmAsk({ title: (sec ? ((({ eth: 'Ethereum', base: 'Base', arbitrum: 'Arbitrum', optimism: 'Optimism', polygon: 'Polygon', bsc: 'BNB Chain', sol: 'Solana', upbit: '업비트' })[sec]) || sec) + ' ' : '') + d + '부터 가져올까요?', body: '옛 구간만 추가로 받아요. 끝나면 원장을 자동으로 다시 계산해요(몇 분 동안 새 거래 반영이 잠시 멈춤).', ok: '가져오기',
        run: () => post('/api/backfill_request', body, '요청했어요 · 진행 상황은 이 카드에 표시돼요').then(r => { if (r) { delete S.drafts.bfDate; renderView(); } }) });
    },
    addAlias: () => {
      const addr = draft('naddr'), alias = draft('nalias');
      if (!addr) { toast('주소를 입력하세요', true); return; }
      if (!alias) { toast('표시 이름을 입력하세요', true); return; }
      post('/api/wallet_alias', { address: addr, alias }, '이름을 저장했어요').then(d => { if (d) { delete S.drafts.naddr; delete S.drafts.nalias; renderView(); } });
    },
    covRetry: () => { S.cov = null; renderView(); },
    wlAdd: () => { const a = draft('wl'); if (!a) { toast('주소를 입력하세요', true); return; } post('/api/src_whitelist', { address: a }, '화이트리스트에 추가했어요').then(d => { if (d) { S.wl = arr(d.whitelist); delete S.drafts.wl; renderView(); } }); },
    wlRemove: el => { const a = el.dataset.v || draft('wl'); if (!a) return; confirmAsk({ title: '화이트리스트에서 뺄까요?', body: short(a) + ' 에서 온 토큰이 다시 스팸 판정 대상이 돼요.', ok: '제거', danger: true, run: () => post('/api/src_whitelist', { address: a, remove: true }, '화이트리스트에서 뺐어요').then(d => { if (d) { S.wl = arr(d.whitelist); renderView(); } }) }); },
    copy: el => copyText(el.dataset.v),
    modalOk: () => { const md = S.modal; S.modal = null; renderOverlay(); if (md && typeof md.run === 'function') md.run(); },
    modalCancel: () => { S.modal = null; renderOverlay(); },
    modalBg: (el, ev) => { if (ev.target === el) { S.modal = null; renderOverlay(); } }
  };
  tjLate_dash({ A });
  tjLate_daily({ A });
  const togSet = (set, k) => { if (set.has(k)) set.delete(k); else set.add(k); };
  Object.assign(A, attdActs());

  const {
    brokersBody, levDrawer, levHTML, nftLoad, oaDashLine, oaItems, oaNameTxt, oaNeed, oaTot, oaV, vOther
  } = tjTab('other', {
    $, A, ago, arr, CHAIN_KO, cls, clsP, clsV, drawerHist, errTxt, esc, exLinked, exLogo, fmtTs, IC, isISO, LS, m, mN, nf, num, onUnauthorized, pad2,
    pctS, post, prTxt, PVM, pvMoney, pvOn, pvW, px, q, rate, renderAuto, renderOverlay, renderView, rw, S, sparkSVG, sum, sxGo, toast, todayISO,
    trimZeros, UI_SHEETS, uiCell, uiDate, uiFold, uiPaged, uiPgBar, uiPgReveal, uiPgS, uiPgSlice, uiPick, uiRe, uiSheetClose, uiSheetOpen, vib
  });
  tjLate_dash({ levHTML, oaDashLine });
  tjLate_set({ brokersBody, oaNeed });

  const AL_PRE = { rec: '추천', min: '최소', all: '전부' };
  tjLate_set({ AL_PRE });
  function alLoad(force) {
    const L = S.al || (S.al = { st: '', at: 0, d: null, err: '' });
    if ((L.st === 'loading' && !force) || L.st === 'none') return L;
    if (!force && L.at && Date.now() - L.at < 60000) return L;
    L.st = 'loading';
    const v0 = L.ver || 0, busy0 = (L.pend || 0) > 0;
    const stale = () => busy0 || (L.ver || 0) !== v0 || (L.pend || 0) > 0;
    fetch('/api/alert_prefs', { cache: 'no-store' }).then(r => {
      if (r.status === 401) { onUnauthorized(); throw new Error('HTTP 401'); }
      if (r.status === 404) { L.st = 'none'; L.d = null; return null; }
      return r.json().then(j => { if (!j || !j.ok) throw new Error((j && j.error) || ('HTTP ' + r.status));
        if (stale() && L.d) { L.st = 'ok'; return; }
        L.d = j; L.st = 'ok'; L.err = ''; });
    }).catch(e => { if (stale() && L.d) { L.st = 'ok'; return; } L.st = 'err'; L.err = (e && e.message) || String(e); })
      .then(() => { L.at = Date.now(); if (S.D && S.tab === 'settings') renderView(); });
    return L;
  }
  const alCat = k => arr(S.al && S.al.d && S.al.d.cats).find(c => c.key === k);
  function alThH(key) {
    const D = S.al.d, sp = (D.th || {})[key], v = (D.prefs.th || {})[key];
    if (!sp) return '';
    if (sp.kind === 'bool') return '<span class="alth alsw"><span class="cap pvx">' + esc(sp.label) + '</span>' + sxSw('alThB', v !== false, sp.label, ' data-v="' + esc(key) + '"') + '</span>';
    const isRec = String(v) === String(sp.rec);
    const recB = isRec ? '<span class="pill ok sm altag">추천</span>'
      : '<button class="pill a sm altag" data-a="alThRec" data-v="' + esc(key) + '" title="추천값으로 되돌리기">추천 ' + (sp.kind === 'usd' ? (S.hide || S.rand ? '$' + pvW(PVM.usd) : '$' + nf('en-US').format(num(sp.rec))) : sp.kind === 'pct' ? esc(String(sp.rec)) + '%' : esc(String(sp.rec))) + '</button>';
    let inp;
    if (sp.kind === 'time') { UI_PICK['alth_' + key] = x => alSetTh(key, x); inp = uiPick('alth_' + key, alTimes(String(v)), String(v), sp.label, { cls: 'altm' }); }
    else if (sp.kind === 'usd') inp = S.hide ? '<span class="num alhid">$' + pvW(PVM.usd) + '</span>'
      : '<span class="alu">$</span><input class="field num alin" data-pv="1" inputmode="decimal"' + (S.rand ? ' disabled placeholder="랜덤값 모드 — 가려짐"' : ' value="' + esc(String(v)) + '"') + ' data-alth="' + esc(key) + '" aria-label="' + esc(sp.label) + ' (USD)">'
        + (S.cur !== 'USD' && !S.rand && !S.hide ? '<span class="cap num">≈ ' + mN(num(v), { compact: true }) + '</span>' : '');
    else inp = '<input class="field num alin alpct" inputmode="decimal" value="' + esc(String(v)) + '" data-alth="' + esc(key) + '" aria-label="' + esc(sp.label) + ' (%)"><span class="alu">%</span>';
    return '<span class="alth"><span class="cap pvx">' + esc(sp.label) + '</span>' + inp + recB + '</span>';
  }
  const AL_NOW = ['liq', 'price', 'bigflow', 'arrive', 'depeg', 'balmis', 'health', 'stall', 'move'];
  const AL_DAILY = [['pnl'], ['recon'], ['scam'], ['lprange'], ['review', 'weekly'], ['oa'], ['digest'], ['other']];
  const AL_TIER0 = { now: ['즉시', '지금 폰을 보고 해야 할 일 · 소리'], daily: ['하루 요약', '소리 없이 한 통'], web: ['시스템', '분류·동기화·옛 기록 가져오기·재계산 — 텔레그램 안 보내고 상태 패널에만'] };
  const alTierL = (D, t) => { const x = arr(D.tiers).find(y => y && y.key === t); return [x && x.label || AL_TIER0[t][0], x && x.sub || AL_TIER0[t][1]]; };
  const alTimes = cur => { const o = []; for (let h = 0; h < 24; h++) ['00', '30'].forEach(mm => o.push(pad2(h) + ':' + mm));
    if (/^([01]\d|2[0-3]):[0-5]\d$/.test(cur) && o.indexOf(cur) < 0) { o.push(cur); o.sort(); } return o.map(t => [t, t]); };
  function alSum7(D) {
    const c7 = D.counts7 || {}; let sent = 0, folded = 0, sys = 0;
    arr(D.cats).forEach(c => { const n = c7[c.key] || {}; sent += num(n.sent); folded += num(n.daily) + num(n.web);
      if (alTier(c) === 'web') sys += num(n.sent) + num(n.skip) + num(n.held) + num(n.daily) + num(n.web); });
    return { sent, old: sent + folded, sys };
  }
  function alPrev(txt, tier, chart) {
    let t = String(txt || '').replace(/^(🔴|📋|✅|🌙|🔔)\s*/u, ''); if (!t) return '';
    if (S.hide || S.rand) t = t.replace(/([−+-]?[₩$])\s?\d[\d,.]*(억|만|K|M|B)?/g, (m0, c) => c + '…');
    const L = t.split('\n');
    const sp = chart ? '<svg class="alspark" viewBox="0 0 360 72" aria-hidden="true"><path d="M0 60 C 60 56, 110 44, 160 40 S 260 22, 360 16" fill="none" stroke="currentColor" stroke-width="2.4"/></svg>' : '';
    return '<div class="alpv"><span class="cap pvx">이 문장으로 가요 · 숫자는 예시</span><div class="albub pvx"><b><span class="aldot ' + tier + '"></span>' + esc(L[0]) + '</b>' + sp
      + L.slice(1).map((x, i) => '<span' + (L.length > 2 && i === L.length - 2 && tier === 'now' ? ' class="alb3"' : '') + '>' + esc(x) + '</span>').join('') + '</div></div>';
  }
  function alRow(c) {
    const D = S.al.d, on = alOn(D, c.key), n7 = (D.counts7 || {})[c.key] || {}, id = 'sx-al-' + sxId(c.key), tg = D.tg && D.tg.connected;
    const exp = () => {
      const ths = arr(c.th).length && on ? '<div class="alths">' + arr(c.th).map(alThH).join('') + '</div>' : '';
      const hint = !on ? (c.key === 'move' ? '켜면 총자산에서 비중이 큰 코인만 · 코인마다 하루 한 번' : c.key === 'stall' || c.key === 'balmis' ? '꺼 둬도 상태 패널·대시보드 상태 카드에는 그대로 보여요' : '') : c.key === 'liq' && D.futuresN === 0 ? '지금 선물 포지션이 없어요 — 생기면 판정해요' : c.key === 'lprange' && D.lpOpen === 0 ? '지금 열린 LP 가 없어요' : '';
      const cnt = [num(n7.sent) ? '보냄 ' + num(n7.sent) + '통' : '', num(n7.skip) ? '꺼서 안 보냄 ' + num(n7.skip) + '건' : '', num(n7.held) ? '밤에 모음 ' + num(n7.held) + '건' : ''].filter(Boolean);
      return '<div class="cap pvx">' + esc(c.desc) + '</div>' + ths + (hint ? '<div class="cap alhint">' + esc(hint) + '</div>' : '') + alPrev(c.sample, c.key === 'arrive' ? 'daily' : 'now')
        + '<div class="sx-acts"><span class="cap num al7 pvx">지난 7일 ' + (cnt.length ? cnt.join(' · ') : '0건') + '</span><span class="sp"></span><button class="btn sm altest" data-a="alTest" data-v="' + esc(c.key) + '"' + (tg ? '' : ' disabled title="텔레그램 연결 뒤에 쓸 수 있어요"') + ' aria-label="' + esc(c.label) + ' 테스트 보내기">테스트</button></div>';
    };
    return sxIt(id, esc(c.label), '', sxSw('alCat', on, c.label + ' 알림' + (c.crit ? ' (늘 켜짐 · 끌 수 없음)' : ''), ' data-v="' + esc(c.key) + '"' + (c.crit ? ' disabled aria-disabled="true" title="봇이 멈춘 걸 알려야 해서 끌 수 없어요"' : '')), { exp, cls: 'alrow' + (on ? '' : ' off') });
  }
  function sxAlertsBody() {
    const L = alLoad(false), D = alD();
    if (!D) {
      if (L && L.st === 'none') return '<div class="sx-card"><div class="cap" style="margin-bottom:10px">텔레그램이 연결되면 아래 알림을 보내요 — 목표가·손절선은 매매일지 카드에서 저장하면 1분 간격으로 감시해요</div><div class="chiprow">'
        + ['새 온체인 거래', '거래소 입금 확인', '매도 체결', '목표가 도달', '손절선 이탈', '잔고 불일치', '시스템 오류'].map(x => '<span class="chip">' + x + '</span>').join('') + '</div></div>';
      return '<div class="sx-card">' + (L && (L.st === 'err' || L.d) ? '<div class="sx-empty">알림 설정을 불러오지 못했어요 · <button class="link" data-a="alRetry">다시 시도</button></div>' : sxSlotWait()) + '</div>';
    }
    const pre = D.preset, tg = D.tg && D.tg.connected, pr = arr(D.presets).find(p => p.key === pre), cats = arr(D.cats), s7 = alSum7(D);
    const mig = D.migrated === 'v1-rec' ? '새 방식(즉시 + 하루 요약)으로 옮겼어요 · 예전 설정은 서버에 따로 보관' : D.migrated === 'v1-custom' ? '직접 고른 켬·끔은 그대로 옮겼어요 · 예전 설정은 서버에 따로 보관' : '';
    const migQ = !!(D.prefs && D.prefs.quiet && D.prefs.quiet.on);
    const migL = !D.migrated ? [] : [D.migrated === 'v1-rec' ? '예전 ‘추천’에서 켜져 있던 보유 코인 급등락 알림은 이제 꺼져 있어요 — 받으려면 아래 ‘보유 코인 급등락’을 켜세요.' : '',
      migQ ? '조용한 시간에도 목표가·손절, 스테이블 가격 이탈, 내가 안 한 큰 출금은 이제 바로 와요 — 밤에 모아 두는 건 급등락뿐이에요.' : '',
      '나머지 소식은 하루 한 통 요약으로 묶여요.'].filter(Boolean);
    const migCard = migL.length ? '<div class="sx-card almig" role="note"><b>알림 방식이 바뀌었어요</b>' + migL.map(x => '<div class="cap">' + esc(x) + '</div>').join('') + '</div>' : '';
    const hero = '<div class="alhero"><div class="alhero-t"><b>꼭 필요한 것만</b><span class="cap">' + (mig ? esc(mig) : '급한 건 바로 · 나머지는 하루 한 통') + '</span></div>'
      + '<span class="cap num pvx alhero-n" title="하루 요약·시스템으로 돌린 소식을 하나씩 보냈다면 몇 통이었는지">지난 7일 보냄 ' + s7.sent + '통' + (s7.old > s7.sent ? ' · 예전 같았으면 ' + s7.old + '통' : '') + '</span></div>';
    const presets = '<div class="sx-alp" id="sx-al-pre">' + sxSeg('alPreset', arr(D.presets).map(p => [p.key, esc(p.label), pre === p.key]), '알림 추천값', true).replace(/<button data-a="alPreset" data-v="([^"]*)"/g, (a, k) => { const p9 = arr(D.presets).find(x => esc(x.key) === k); return a + (p9 && p9.desc ? ' title="' + esc(p9.desc) + '"' : ''); })
      + '<button class="btn sm" data-su="tgtest"' + (tg ? '' : ' disabled title="텔레그램 연결 뒤에 쓸 수 있어요"') + '>테스트</button></div>'
      + '<div class="cap sx-alpc"><span class="pill ' + (pre === 'custom' ? 'w' : 'a') + ' sm" data-alpre="' + esc(pre) + '"' + (pr && pr.desc ? ' title="' + esc(pr.desc) + '"' : '') + '>지금: ' + esc(pre === 'custom' ? '직접 설정' : (AL_PRE[pre] || pre)) + '</span> ' + esc(pr && pr.desc ? pr.desc : '누르면 아래를 한 번에 채워요 · 하나라도 바꾸면 ‘직접 설정’') + '</div>';
    const head = (t, extra) => { const tl = alTierL(D, t); return '<div class="alhd2"><span class="aldot ' + t + '"></span><b>' + esc(tl[0]) + '</b><span class="cap">' + esc(tl[1]) + '</span>' + (extra ? '<span class="sp"></span>' + extra : '') + '</div>'; };
    const nowC = cats.filter(c => alTier(c) === 'now').sort((a, b) => (AL_NOW.indexOf(a.key) + 1 || 99) - (AL_NOW.indexOf(b.key) + 1 || 99));
    const q = D.prefs.quiet || {};
    const quiet = alOn(D, 'move') ? sxIt('sx-al-quiet', '밤엔 급등락 모아 두기' + (D.quietNow ? ' ' + sxPill('a', '지금') : ''), '<span class="pvx">' + (q.on ? esc(q.from) + '–' + esc(q.to) + ' · 끝나면 한 통' : '꺼짐 · 밤에도 바로') + (num(D.held) ? ' · 모인 ' + num(D.held) + '건' : '') + '</span>',
      sxSw('alQuiet', q.on, '조용한 시간'), { cls: 'alrow alq' + (q.on ? '' : ' off'), exp: () => (q.on ? '<div class="alths"><span class="alth">' + uiPick('alq_from', alTimes(String(q.from)), String(q.from), '조용한 시간 시작', { cls: 'altm' }) + '<span class="cap">부터</span>'
        + uiPick('alq_to', alTimes(String(q.to)), String(q.to), '조용한 시간 끝', { cls: 'altm' }) + '<span class="cap">까지</span>'
        + (q.from === '01:00' && q.to === '08:00' ? '<span class="pill ok sm altag">추천</span>' : '<button class="pill a sm altag" data-a="alQuietRec" title="추천값으로 되돌리기">추천 01:00~08:00</button>') + '</span></div>' : '<div class="cap">스위치를 켜면 시간을 고를 수 있어요</div>')
        + '<div class="cap pvx" style="margin-top:6px">급등락만 모아요 — 청산가·목표가·큰 출금·스테이블·봇 멈춤·내 이체 도착 확인은 밤에도 바로 와요</div>' }) : '';
    const nowCard = '<div class="sx-card alcard altier" id="sx-al-now">' + head('now') + nowC.map(alRow).join('') + quiet + '</div>';
    const dc = cats.filter(c => alTier(c) === 'daily'), used = new Set(), groups = [];
    AL_DAILY.forEach(g => { const ks = g.filter(k => dc.some(c => c.key === k)); if (ks.length) { groups.push(ks); ks.forEach(k => used.add(k)); } });
    dc.forEach(c => { if (!used.has(c.key)) groups.push([c.key]); });
    const anyD = dc.some(c => alOn(D, c.key)), th = D.prefs.th || {}, dsp = (D.th || {}).digest_time;
    const ck = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12l5 5 9-10"/></svg>';
    const chips = groups.map(ks => { const c = alCat(ks[0]), on = ks.some(k => alOn(D, k));
      return '<button type="button" class="alchip' + (on ? ' on' : '') + '" id="sx-al-' + sxId(ks[0]) + '" data-a="alChip" data-v="' + esc(ks.join(',')) + '" aria-pressed="' + on + '" title="' + esc(c.desc || '') + '">' + (on ? ck : '') + esc(c.label) + '</button>'; }).join('');
    if (dsp) UI_PICK.alDigestTime = x => alSetTh('digest_time', x);
    const tm = dsp ? uiPick('alDigestTime', alTimes(String(th.digest_time || dsp.rec)), String(th.digest_time || dsp.rec), '하루 요약 보내는 시각', { cls: 'altm aldt' }) : '';
    const dg7 = num(((D.counts7 || {}).digest || {}).sent), fold7 = dc.reduce((n, c) => n + num(((D.counts7 || {})[c.key] || {}).daily), 0);
    const dgRow = sxIt('sx-al-dg', '요약 모양 · 미리 보기', '', '', { cls: 'alrow', exp: () => '<div class="alths">' + ['digest_chart', 'digest_axis', 'pnl_time'].map(alThH).join('') + '</div>'
      + alPrev(D.digestSample || '', 'daily', th.digest_chart !== false)
      + '<div class="cap pvx" style="margin-top:6px">숨김·랜덤값은 이 화면 규칙이에요 — 텔레그램에는 실제 값으로 가요(그림 금액 눈금은 위 스위치로)</div>'
      + '<div class="sx-acts"><span class="cap num al7 pvx">지난 7일 요약 ' + dg7 + '통 · 요약에 넣은 소식 ' + fold7 + '건</span><span class="sp"></span><button class="btn sm altest" data-a="alTest" data-v="digest"' + (tg ? '' : ' disabled title="텔레그램 연결 뒤에 쓸 수 있어요"') + ' aria-label="하루 요약 테스트 보내기">테스트</button></div>' });
    const dayCard = '<div class="sx-card alcard altier" id="sx-al-daily">' + head('daily', tm) + '<div class="alchips" role="group" aria-label="하루 요약에 넣을 것">' + chips + '</div>'
      + (anyD ? '' : '<div class="cap alhint" style="margin:-6px 0 12px">하루 요약을 받지 않아요 — 칩을 누르면 다시 넣어요</div>') + dgRow + '</div>';
    const sysCard = '<div class="sx-card alcard altier alsys" id="sx-al-sys"><button type="button" class="alsysb" data-a="sxHealth" aria-label="시스템 소식 — 상태 패널 열기"><span class="aldot web"></span><b>' + esc(alTierL(D, 'web')[0]) + '</b>'
      + '<span class="cap alsysc">' + esc(alTierL(D, 'web')[1]) + '</span><span class="sp"></span><span class="cap num pvx alsysn">7일 ' + s7.sys + '건</span>' + IC.right + '</button></div>';
    return hero + migCard + presets + nowCard + dayCard + sysCard
      + '<div class="cap pvx sx-note" title="내 이체 도착 확인은 소리 없이 · 같은 문제는 생길 때·풀릴 때 두 번(봇 멈춤이 1시간 넘으면 한 번 더) · 테스트는 예시 한 통(시간당 6통)">즉시 = 소리와 함께 밤에도 · 하루 요약 = 소리 없이 하루 한 번</div>';
  }

  async function alSave(body, prev, okMsg) {
    const L = S.al; if (!L || !L.d) return;
    const seq = L.seq = (L.seq || 0) + 1;
    if (!L.pend) L.bat = { n: 0, fail: false };
    L.bat.n++;
    L.ver = (L.ver || 0) + 1; L.pend = (L.pend || 0) + 1;
    renderView();
    const send = () => postJ('/api/alert_prefs', body).catch(e => ({ st: 0, d: null, e }));
    const r = await (L.q = (L.q || Promise.resolve()).then(send, send));
    L.pend = Math.max(0, (L.pend || 0) - 1);
    if (r && r.d && r.d.ok) { if (seq === L.seq) { L.d = r.d; L.at = Date.now(); } if (okMsg) toast(typeof okMsg === 'function' ? okMsg(r.d) : okMsg); }
    else { L.bat.fail = true; if (prev && seq === L.seq) L.d = prev; toast('저장하지 못했어요 · ' + ((r && r.d && r.d.error) || (r && r.st ? 'HTTP ' + r.st : '연결 실패')), true); }
    if (!L.pend && (L.bat.n > 1 || L.bat.fail)) { L.at = 0; alLoad(true); }
    if (S.tab === 'settings') renderView();
  }
  const alClone = d => JSON.parse(JSON.stringify(d));
  function alSetTh(key, raw) {
    const L = S.al; if (!L || !L.d) return;
    const sp = (L.d.th || {})[key]; if (!sp) return;
    let v = sp.kind === 'bool' ? !!raw : String(raw == null ? '' : raw).trim();
    if (sp.kind === 'time' && !/^([01]\d|2[0-3]):[0-5]\d$/.test(v)) { toast('HH:MM 으로 골라 주세요', true); renderView(); return; }
    if (sp.kind !== 'time' && sp.kind !== 'bool') { v = v.replace(/[,\s$%]/g, ''); if (v === '' || !isFinite(+v)) { toast('숫자를 넣어 주세요', true); renderView(); return; } v = +v; }
    if (String(L.d.prefs.th[key]) === String(v)) return;
    const prev = alClone(L.d); L.d.prefs.th[key] = v;
    alSave({ th: { [key]: v } }, prev, sp.label + ' 저장');
  }
  Object.assign(A, {
    alRetry: () => { if (S.al) { S.al.st = ''; S.al.at = 0; } alLoad(true); renderView(); },
    alPreset: el => { const L = S.al, k = el.dataset.v; if (!L || !L.d || !AL_PRE[k]) return;
      const p = arr(L.d.presets).find(x => x.key === k); if (!p) return;
      const prev = alClone(L.d); L.d.prefs = alClone(p.doc); L.d.preset = k; vib();
      alSave({ preset: k }, prev, AL_PRE[k] + ' 알림 설정으로 바꿨어요'); },
    alCat: el => { const L = S.al, k = el.dataset.v, c = alCat(k); if (!L || !L.d || !c) return;
      if (c.crit) { toast('봇 이상 경보는 끌 수 없어요 — 봇이 멈춘 걸 알려야 해서요'); return; }
      if (alTier(c) === 'web') { toast('봇 내부 소식이라 텔레그램으로 보내지 않아요 — 상태 패널에서 봐요'); return; }
      const nx = alOn(L.d, k) ? 'off' : 'on';
      const prev = alClone(L.d); L.d.prefs.cats[k] = nx; L.d.preset = 'custom'; vib();
      alSave({ cats: { [k]: nx } }, prev, c.label + ' ' + (nx === 'off' ? '끔' : '켬')); },
    alChip: el => { const L = S.al; if (!L || !L.d) return;
      const ks = String(el.dataset.v || '').split(',').filter(k => { const c = alCat(k); return c && alTier(c) === 'daily'; }); if (!ks.length) return;
      const nx = ks.some(k => alOn(L.d, k)) ? 'off' : 'on', body = {};
      const prev = alClone(L.d); ks.forEach(k => { L.d.prefs.cats[k] = nx; body[k] = nx; }); L.d.preset = 'custom'; vib();
      alSave({ cats: body }, prev, alCat(ks[0]).label + (nx === 'off' ? ' · 하루 요약에서 뺐어요' : ' · 하루 요약에 넣어요')); },
    alThB: el => { const L = S.al, k = el.dataset.v, sp = L && L.d && (L.d.th || {})[k]; if (!sp || sp.kind !== 'bool') return; vib(); alSetTh(k, L.d.prefs.th[k] === false); },
    alThRec: el => { const L = S.al, k = el.dataset.v, sp = L && L.d && (L.d.th || {})[k]; if (sp) alSetTh(k, sp.rec); },
    alQuiet: () => { const L = S.al; if (!L || !L.d) return; const on = !(L.d.prefs.quiet || {}).on;
      const prev = alClone(L.d); L.d.prefs.quiet = Object.assign({}, L.d.prefs.quiet, { on }); L.d.preset = 'custom';
      alSave({ quiet: { on } }, prev, '조용한 시간 ' + (on ? '켬' : '끔')); },
    alQuietRec: () => { const L = S.al; if (!L || !L.d) return;
      const prev = alClone(L.d); L.d.prefs.quiet = { on: true, from: '01:00', to: '08:00' };
      alSave({ quiet: { on: true, from: '01:00', to: '08:00' } }, prev, '조용한 시간 01:00~08:00'); },
    alTest: async el => { const k = el.dataset.v, c = alCat(k); if (!c) return;
      el.disabled = true;
      let r; try { r = await postJ('/api/alert_test', { cat: k }); } catch (e) { r = { st: 0, d: null }; }
      el.disabled = false;
      if (r && r.d && r.d.ok) toast(c.label + ' 테스트를 보냈어요 — 20초 안에 텔레그램으로 와요');
      else toast('테스트를 보내지 못했어요 · ' + ((r && r.d && r.d.error) || (r && r.st ? 'HTTP ' + r.st : '연결 실패')), true); }
  });
  function alQuietSet(qk, v) {
    const L = S.al; if (!L || !L.d || !/^([01]\d|2[0-3]):[0-5]\d$/.test(String(v || ''))) return;
    if ((L.d.prefs.quiet || {})[qk] === v) return;
    const prev = alClone(L.d); L.d.prefs.quiet = Object.assign({}, L.d.prefs.quiet, { [qk]: v }); L.d.preset = 'custom';
    alSave({ quiet: { [qk]: v } }, prev, '조용한 시간 저장');
  }
  Object.assign(UI_PICK, { alq_from: v => alQuietSet('from', v), alq_to: v => alQuietSet('to', v) });
  document.addEventListener('change', ev => {
    const t = ev.target; if (!t || !t.getAttribute) return;
    const k = t.getAttribute('data-alth');
    if (k) alSetTh(k, t.value);
  });
  document.addEventListener('keydown', ev => { const t = ev.target; if (ev.key === 'Enter' && t && t.matches && t.matches('input[data-alth]')) { ev.preventDefault(); t.blur(); } });

  Object.assign(A, {
    sxTog: el => { const k = el.dataset.v, on = !S.set.open.has(k); if (on) S.set.open.add(k); else S.set.open.delete(k);
      if (on && k === 'wadd') S.set.focus = '[data-su-in="w_addr"]';
      renderView(); },
    sxKeyFill: () => { const K = sxKeys(), k = K && K.empty[0];
      sxGo('keys', '', { pre: () => { const u = suU(); if (u && k) u.xp = k; }, hl: k ? '[data-su="xp"][data-v="' + k + '"]' : '', focus: k ? '.sx [data-su-slot="keys"] .su-acc.open input' : '' }); },
    sxHealth: () => { try { if (window.TJHealth && window.TJHealth.open) window.TJHealth.open(); } catch (e) {  } },
    sxBack: el => { const to = el.dataset.v || 'settings'; if (S.set.prev === to && window.history.length > 1) window.history.back(); else location.hash = to; },
    sxWal: el => { const k = el.dataset.v; S.set.walOpen = S.set.walOpen === k ? '' : k; renderView(); const b = [...document.querySelectorAll('.sx-wx')].find(x => x.getAttribute('data-v') === k); if (b) { try { b.focus({ preventScroll: true }); } catch (e) {  } } },
    sxPick: el => sxPick(+el.dataset.v)
  });
  function sxWalFilter(v) {
    S.set.walQ = String(v || '');
    const q = S.set.walQ.toLowerCase().trim(), wl = $('#sxWl');
    if (!wl) return;
    const hay = new Map(sxWalRows().map(r => [r.k, sxWalHay(r)]));
    let n = 0;
    wl.querySelectorAll('.sx-wr').forEach(r => { const hit = !q || String(hay.get(r.getAttribute('data-wq')) || '').indexOf(q) >= 0; r.hidden = !hit; if (hit) n++; });
    wl.classList.toggle('all', !!q);
    const nm = wl.querySelector('.sx-nomatch'); if (nm) nm.hidden = !(q && !n);
    const mo = $('#walCard .sx-more'); if (mo) mo.hidden = !!q;
  }
  document.addEventListener('keydown', ev => {
    const t = ev.target;
    if (S.tab !== 'settings') return;
    if (t && t.id === 'sxQ') {
      const R = S.set.qr || [];
      if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') { if (!S.set.q || !R.length) return; ev.preventDefault(); S.set.qOpen = true; S.set.qi = (Math.min(S.set.qi || 0, R.length - 1) + (ev.key === 'ArrowDown' ? 1 : R.length - 1)) % R.length; sxSearchPaint(); return; }
      if (ev.key === 'Enter') { ev.preventDefault(); if (S.set.q && R.length) sxPick(Math.min(S.set.qi || 0, R.length - 1)); return; }
      if (ev.key === 'Escape') { ev.preventDefault(); ev.stopImmediatePropagation(); if (S.set.q) { S.set.q = ''; S.set.qi = 0; t.value = ''; sxSearchPaint(); } else t.blur(); return; }
      return;
    }
    if (ev.key === '/' && !ev.ctrlKey && !ev.metaKey && !ev.altKey && !(t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable)) && !S.modal && !kbDialog()) {
      const i = $('#sxQ'); if (i) { ev.preventDefault(); i.focus(); try { i.select(); } catch (e) {  } } return;
    }
    if ((ev.key === 'ArrowDown' || ev.key === 'ArrowUp') && t && t.classList && t.classList.contains('sx-row')) {
      const L = [...document.querySelectorAll('.sx .sx-row')], i = L.indexOf(t);
      if (i >= 0) { ev.preventDefault(); const n = L[(i + (ev.key === 'ArrowDown' ? 1 : L.length - 1)) % L.length]; if (n) n.focus(); }
    }
  });
  document.addEventListener('pointerdown', ev => { if (S.tab === 'settings' && S.set.qOpen && !(ev.target.closest && ev.target.closest('.sx-q'))) { S.set.qOpen = false; sxSearchPaint(); } }, true);
  document.addEventListener('focusin', ev => { if (ev.target && ev.target.id === 'sxQ' && S.set.q && !S.set.qOpen) { S.set.qOpen = true; sxSearchPaint(); } });
  const sxOnSignal = () => { if (S.tab === 'settings' && S.D && !S.locked && sxSig() !== S.set.sig) render(); };
  window.addEventListener('tj:setup', sxOnSignal);
  window.addEventListener('tj:setup', () => { if (S.tab === 'dash' && S.D && !S.locked) { const k9 = JSON.stringify(onbState()); if (k9 !== S.onbSig) { S.onbSig = k9; renderView(); } } });
  window.addEventListener('tj:health', sxOnSignal);
  window.addEventListener('tj:health', () => { const k9 = ledgerBnrSig(); if (k9 !== S.lbnrSig) { S.lbnrSig = k9; if (!S.locked) renderChrome(); } });
  if (mqW && typeof mqW.addEventListener === 'function') mqW.addEventListener('change', () => { if (S.tab === 'settings' && S.D) renderView(); });

  Object.assign(UI_REVEAL, {
    coin: id => { S.hold.mode = 'all'; S.hold.showDust = true; const rows = holdRows().rows, i = rows.findIndex(r => r.g.key === id || r.g.sym === id);
      if (i < 0) { const st9 = arr(S.D.stableGroups).find(g => String(g.sym || '').toUpperCase() === String(id || '').toUpperCase());
        if (st9) { S.stOpen.add(st9.sym); S.justOpened.add('st:' + st9.sym); return { tab: 'dash', anc: 'cash:' + st9.sym }; } }
      if (i < 0) { const sy9 = String(id || '').split('~')[0].toUpperCase(), z9 = arr(S.D.zeroInst).some(x => String(x.sym || '').toUpperCase() === sy9);
        if (!z9) return null; S.hold.showZero = true; uiPgReveal('zero', x => !!x && String(x.sym || '').toUpperCase() === sy9); return { tab: 'dash', anc: 'zcoin:' + sy9 }; } const k = rows[i].g.key; uiPgReveal('hold', holdPgHit(k)); S.hold.open.add(k); S.justOpened.add('h:' + k); return { tab: 'dash', anc: 'coin:' + k }; },
    cycle: id => { S.j.view = 'cycles'; S.j.status = 'all'; S.j.q = ''; S.drafts.jq = '';
      let L = jList().list; if (!L.some(p => p.key === id)) { S.g.period = 'all'; S.src = { mode: 'all', key: '' }; L = jList().list; }
      const i = lpGroupItems(L).findIndex(x => x._grp ? x.ms.some(p => p.key === id) : x.key === id); if (i < 0) return null;
      uiPgReveal('jcy', x => x._grp ? x.ms.some(p => p.key === id) : x.key === id); S.j.open.add(id); S.justOpened.add('j:' + id); return { tab: 'journal' }; },
    evday: id => { if (!isISO(id)) return null; S.j.view = 'feed'; S.src = { mode: 'all', key: '' };
      const b = gBounds(), ff = S.feedFull, wide = !b || isoSpanDays(b.lo, b.hi) > WIDE_DAYS;
      const have = !!(ff && ff.evs && ff.evs.some(e => String(e.iso || '').slice(0, 10) === id));
      if (!gPass(id) || (wide && !have)) { S.g.period = 'custom'; S.g.from = id; S.g.to = id; }
      uiOpen('evd:' + id, false); uiSetOpen('evd:' + id, true); uiPgReveal('evdays', g => !!g && g.iso === id); return { tab: 'journal' }; },
    day: id => { const k = dayKeyOf(id); if (!k) return null; wkOff(); S.day = k; S.calYM = ymOf(k) || S.calYM; return { tab: 'daily', anc: 'day:' + k }; },
    outflow: id => { const r = ofByAddr(id); if (!r) return null; S.of.view = r.bucket === 'pending' ? 'pending' : 'history'; if (r.bucket === 'spam' || r.dustPoison) S.of.showHidden = true;
      S.of.period = 'all'; S.of.coin = ''; S.of.reason = ''; uiPgReveal('ofp', x => !!x && x.address === id); uiPgReveal('ofh', x => !!x && x.address === id); S.of.open.add(id); S.justOpened.add('of:' + id); return { tab: 'outflows' }; },
    pending: id => { const D = S.D, p = arr(D.pendings).find(x => String(x.key) === id); if (!p) return null;
      S.u.q = ''; S.drafts.uq = ''; if (S.u.open == null) S.u.open = new Set();
      if (p.hide) { S.u.showHidden = true; uiPgReveal('ug:hid', x => x === p); }
      else { S.u.open.add(p._cat); uiPgReveal('ug:' + p._cat, x => x === p || (!!x && (x.p === p || (Array.isArray(x.grp) && x.grp.indexOf(p) >= 0))));
        if (p._cat === 'unkh' && D.pendVis.filter(x => x._cat === 'unkh' && String(x.sym || '').toUpperCase() === String(p.sym || '').toUpperCase()).length > 1) S.u.item.add('usym:' + String(p.sym || '').toUpperCase()); }
      S.u.item.add(p.key); S.justOpened.add('u:' + p.key); return { tab: 'unmatched' }; },
    nft: id => { S.oa.sub = 'nft'; const d = S.nft.d, has = l => arr(l).some(x => x && String(x.key) === id);
      const fk = x => !!x && String(x.key) === id;
      if (!d) { ['nftt', 'nftc', 'nftsp', 'nfth'].forEach(k => uiPgReveal(k, fk)); S.nft.spamOpen = true; S.nft.hidOpen = true; return { tab: 'other' }; }
      if (has(d.tracked) || has(d.watch)) { uiPgReveal('nftt', fk); return { tab: 'other' }; }
      if (has(d.candidates)) { uiPgReveal('nftc', fk); return { tab: 'other' }; }
      if (d.spam && has(d.spam.items)) { S.nft.spamOpen = true; uiPgReveal('nftsp', fk); return { tab: 'other' }; }
      if (has(d.hidden)) { S.nft.hidOpen = true; uiPgReveal('nfth', fk); return { tab: 'other' }; }
      return null; },
    other: id => { S.oa.sub = 'assets'; if (S.oa.d && !oaItems().some(o => o.id === id)) return null; S.oa.filter = 'all'; S.oa.sel = id; return { tab: 'other' }; }
  });

  Object.assign(A, {
    uiFold: el => {
      const k = el.dataset.v, open = el.getAttribute('aria-expanded') === 'true', ov = !!(el.closest && el.closest('#overlay'));
      const done = () => { uiSetOpen(k, !open); (ov ? renderOverlay : renderView)(); };
      if (open) {
        const c = Array.from(document.querySelectorAll('.clps[data-ck]')).find(x => x.getAttribute('data-ck') === 'uf:' + k);
        if (c && !uiReduce()) { c.classList.remove('in'); c.classList.add('out'); setTimeout(done, 170); return; }
        done(); return;
      }
      S.justOpened.add('uf:' + k); done();
    },
    uiPgOpen: el => { vib(); uiPgGo(el, 0); },
    uiPg: el => uiPgGo(el, Math.max(0, +el.dataset.p || 0)),
    uiPgClose: el => uiPgGo(el, null),
    uiSheetClose: () => uiSheetClose(),
    uiPopOpen: el => { const v = el.dataset.v; S.pop = S.pop === v ? null : v; uiRe();
      if (S.pop === v) { const f = document.querySelector('.upop .opt.on,.upop .g button.edge:not([disabled])') || document.querySelector('.upop .opt,.upop .g button:not([disabled])'); if (f) { try { f.focus({ preventScroll: true }); } catch (e) {  } } } },
    uiPopClose: () => { const p0 = S.pop; S.pop = null; uiRe(); uiPopBack(p0); },
    uiPick: el => { const k = el.dataset.k, v = el.dataset.v, p0 = S.pop; S.pop = null; if (UI_PICK[k]) UI_PICK[k](v); else S.drafts[k] = v; vib(); uiRe(); uiPopBack(p0); },
    uiDateMonth: el => { const k = el.dataset.k, cur = S.uiDateYm[k] || (isISO(S.drafts[k]) ? S.drafts[k] : todayISO()).slice(0, 7), d = new Date(+cur.slice(0, 4), +cur.slice(5) - 1 + (+el.dataset.v), 1);
      S.uiDateYm[k] = d.getFullYear() + '-' + pad2(d.getMonth() + 1); uiRe(); },
    uiDatePick: el => { const k = el.dataset.k, v = el.dataset.v, p0 = S.pop; if (!isISO(v)) return; S.drafts[k] = v; delete S.uiDateYm[k]; S.pop = null; if (UI_PICK[k]) UI_PICK[k](v); vib(); uiRe(); uiPopBack(p0); },
    uiGo: el => { revealAndHighlight(String(el.dataset.v || '')); }
  });

  document.addEventListener('click', ev => {
    const el = ev.target.closest('[data-a]');
    if (S.pop && !ev.target.closest('.popw')) { S.pop = null; if (!el) { uiRe(); return; } }
    if (!el || el.disabled) return;
    if (S.modal && el.closest && el.closest('.usheet,.drawer') && !el.closest('.modal')) return;
    const fn = A[el.getAttribute('data-a')];
    if (!fn) return;
    if (el.tagName === 'A') return;
    const lk = ev.target.closest('a[href]');
    if (lk && el.contains(lk)) return;
    ev.preventDefault();
    fn(el, ev);
  });
  const PIN_AT = ['data-a', 'data-su', 'data-v', 'data-p', 'data-k', 'data-f'];
  let pin = null;
  const pinSc = el => { for (let p = el.parentElement; p && p !== document.body && p !== document.documentElement; p = p.parentElement) { const o = getComputedStyle(p).overflowY; if ((o === 'auto' || o === 'scroll') && p.scrollHeight > p.clientHeight + 1) return p; } return null; };
  const pinRoute = () => { const w = document.querySelector('#suWizard [aria-current="step"]'); return location.hash + '|' + (w ? w.getAttribute('data-v') : ''); };
  const pinHook = (o, n) => { const f = o && o[n]; if (typeof f !== 'function') return; o[n] = function () { if (pin) pin.scrolled = true; return f.apply(this, arguments); }; };
  pinHook(Element.prototype, 'scrollIntoView'); pinHook(Element.prototype, 'scrollTo'); pinHook(Element.prototype, 'scrollBy'); pinHook(window, 'scrollTo'); pinHook(window, 'scrollBy');
  document.addEventListener('click', ev => {
    pin = null;
    const el = ev.target && ev.target.closest ? ev.target.closest('[data-a],[data-su]') : null;
    if (!el || el.tagName === 'A' || !el.getClientRects().length) return;
    const sc = pinSc(el);
    pin = { el, at: PIN_AT.map(n => el.getAttribute(n)), top: el.getBoundingClientRect().top, route: pinRoute(), st: sc ? sc.scrollTop : 0, sy: window.scrollY };
  }, true);
  const pinMoved = (now, was, max) => Math.abs(now - was) > 1 && !(now < was && now >= max - 1);
  window.addEventListener('click', () => {
    const p = pin; pin = null;
    if (!p || p.scrolled || pinRoute() !== p.route || pinMoved(window.scrollY, p.sy, document.documentElement.scrollHeight - window.innerHeight)) return;
    const same = p.el.isConnected ? [p.el] : [...document.querySelectorAll(p.el.tagName)].filter(x => PIN_AT.every((n, i) => x.getAttribute(n) === p.at[i]) && x.getClientRects().length);
    const el = same.length === 1 ? same[0] : null;
    if (!el) return;
    const sc = pinSc(el), dy = el.getBoundingClientRect().top - p.top;
    if (dy > -2 || (sc && pinMoved(sc.scrollTop, p.st, sc.scrollHeight - sc.clientHeight))) return;
    if (sc) sc.scrollTop += dy;
    else { for (let q = el; q && q !== document.body; q = q.parentElement) if (getComputedStyle(q).position === 'fixed') return; window.scrollTo(0, window.scrollY + dy); }
  });
  document.addEventListener('keydown', ev => {
    if (ev.key === 'Escape') {
      if (S.modal) { S.modal = null; renderOverlay(); return; }
      if (S.pop && /^(pick|date):/.test(S.pop)) { const p0 = S.pop; S.pop = null; uiRe(); uiPopBack(p0); return; }
      if (S.sheet) { uiSheetClose(); return; }
      if (S.drawer) { closeDrawer(); return; }
      if (S.tab === 'outflows' && !S.pop && (S.of.memoEd || S.of.lk)) { S.of.memoEd = null; S.of.lk = null; renderView(); return; }
      if (S.pop) { const p0 = S.pop; S.pop = null; renderView(); if (p0 === 'dpk') { const n = $('#dayEv [data-a=pop][data-v=dpk]'); if (n) n.focus({ preventScroll: true }); } return; }
      if (S.tab === 'daily' && S.D && wkSelNow()) { A.wkClose(); return; }
      if (ev.target.matches && ev.target.matches('[data-alias]')) { S.aliasEdit = null; renderView(); }
      return;
    }
    const t = ev.target;
    if (ev.shiftKey && !ev.ctrlKey && !ev.metaKey && !ev.altKey && (ev.key === 'H' || ev.key === 'h' || ev.code === 'KeyH') && !ev.repeat
      && !(t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable))) { ev.preventDefault(); setHide(!S.hide); return; }
    if (t.closest && dayPickKey(ev, t)) return;
    if (ev.key === 'Enter' && t.matches && t.matches('[data-alias]')) { ev.preventDefault(); if (S.rand || RV_IN.has(t)) return; saveAlias(t.getAttribute('data-alias'), t.value, t.getAttribute('data-cur')); return; }
    if (ev.key === 'Enter' && t.matches && t.matches('input[data-enter]')) { ev.preventDefault(); const fn = A[t.getAttribute('data-enter')]; if (fn) fn(t, ev); return; }
    if ((ev.key === 'Enter' || ev.key === ' ') && t.matches && t.matches('[role="button"][data-a]')) { ev.preventDefault(); const fn = A[t.getAttribute('data-a')]; if (fn) fn(t, ev); }
  });
  document.addEventListener('keydown', ev => {
    if (ev.key !== 'Tab' || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    const ov = $('#overlay'), box = ov ? Array.from(ov.querySelectorAll('.drawer,.usheet,.modal')).filter(e => !e.inert).pop() : null;
    if (!box) return;
    const F = Array.from(box.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]):not([type="hidden"]),textarea:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])'))
      .filter(e => e.getClientRects().length && !e.closest('[inert]') && getComputedStyle(e).visibility !== 'hidden');
    if (!F.length) return;
    const a = document.activeElement, first = F[0], last = F[F.length - 1];
    if (a && a !== document.body && !ov.contains(a) && a.closest && a.closest('[role="dialog"],[aria-modal="true"],#suWizard')) return;
    const to = !box.contains(a) ? (ev.shiftKey ? last : first) : ev.shiftKey && a === first ? last : !ev.shiftKey && a === last ? first : null;
    if (to) { ev.preventDefault(); try { to.focus({ preventScroll: false }); } catch (e) { to.focus(); } }
  });
  let inputT = null;
  document.addEventListener('compositionend', ev => { const t = ev.target, lv = t && t.getAttribute && t.getAttribute('data-input'); if (lv === 'jq' || lv === 'uq') t.dispatchEvent(new Event('input', { bubbles: true })); });
  document.addEventListener('input', ev => {
    const t = ev.target;
    const k = t.getAttribute && t.getAttribute('data-draft');
    if (k) S.drafts[k] = t.value;
    if (k && /^[ts]:/.test(k)) { const q9 = $('#plQ'); if (q9) q9.textContent = plQ(k.slice(2)); }
    const live = t.getAttribute && t.getAttribute('data-input');
    if (live === 'sxq') { S.set.q = t.value; S.set.qi = 0; S.set.qOpen = true; sxSearchPaint(); return; }
    if (live === 'walq') { sxWalFilter(t.value); return; }
    if (live === 'dpq') { dpFilter(t.value); return; }
    if (live === 'oflq') { ofLkInput(t); return; }
    if (live === 'jq' || live === 'uq') {
      clearTimeout(inputT);
      if (ev.isComposing) return;
      inputT = setTimeout(() => {
        if (live === 'jq') { S.j.q = t.value; S.j.limit = J_FIRST; } else { S.u.q = t.value; uiPgReset('ug:'); }
        const pos = t.selectionStart;
        renderView();
        const n = $('[data-input="' + live + '"]');
        if (n) { n.focus(); try { n.setSelectionRange(pos, pos); } catch (e) {  } }
      }, 180);
    }
  });
  Object.assign(UI_PICK, { ofPeriod: v => { S.of.period = v; S.of.limit = 30; uiPgReset('ofh'); }, ofCoin: v => { S.of.coin = v; S.of.limit = 30; uiPgReset('ofh'); }, ofReason: v => { S.of.reason = v; S.of.limit = 30; uiPgReset('ofh'); } });
  document.addEventListener('focusout', ev => {
    const t = ev.target;
    if (!S.rand && !RV_IN.has(t) && !rvLock(t) && t.matches && t.matches('[data-alias]') && S.aliasEdit === t.getAttribute('data-alias')) { saveAlias(t.getAttribute('data-alias'), t.value, t.getAttribute('data-cur')); return; }
    if (S.deferred) setTimeout(() => { const ae = document.activeElement; if (S.deferred && !(ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA' || ae.tagName === 'SELECT') && $('#view').contains(ae))) renderView(); }, 0);
  });
  let fitRaf = 0;
  const fitSoon = () => { if (fitRaf) return; fitRaf = requestAnimationFrame(() => { fitRaf = 0; fitDayPick(); }); };
  window.addEventListener('resize', fitSoon);
  window.addEventListener('resize', () => bfPad());
  try { if (document.fonts) { document.fonts.addEventListener('loadingdone', fitSoon); document.fonts.ready.then(fitSoon); } } catch (e) {  }
  document.addEventListener('scroll', ev => { const t = ev.target; if (t && t.classList && t.classList.contains('dpr')) dpFade(t); }, true);
  const onMQ = () => { const mob = mq.matches, nar = mqN.matches; if (mob !== S.mobile || nar !== S.narrow) { S.mobile = mob; S.narrow = nar; if (S.D) { S.anim.chartKey = ''; renderView(); } } };
  if (mq.addEventListener) mq.addEventListener('change', onMQ); else if (mq.addListener) mq.addListener(onMQ);
  if (mqN.addEventListener) mqN.addEventListener('change', onMQ); else if (mqN.addListener) mqN.addListener(onMQ);
  document.addEventListener('visibilitychange', () => { if (!document.hidden && Date.now() - S.lastOk > POLL_MS) refresh(false, null, true); });

  const SVGNS = 'http://www.w3.org/2000/svg';
  const PV_CNT = '.fbtn > .n,.subtabs .n,.dpc .n,.hidbar .cnts,.contrib .ttl .mut';
  const OWN_WC = typeof WeakMap === 'function' ? new WeakMap() : null;
  function ownText(t, p, v) {
    if (!(S.hide || S.rand) || !v || typeof ownScrub !== 'function' || /^(SCRIPT|STYLE|TEXTAREA|NOSCRIPT)$/.test(p.tagName) || (p.closest && p.closest('.pv,.rv'))) return v;
    const pl9 = p.closest ? p.closest('.pvl') : null, pk9 = pl9 && pl9.getAttribute('data-pk');
    const w = pl9 ? v.split(MK_RE).map((x, i) => (i % 2 ? x : String(x).replace(/^(\s*)([^]*?)(\s*)$/, (a, l, c, r) => l + (c ? (pk9 ? ownNm(c, pk9) : ownIn(c)) : '') + r))).join('') : ownScrubM(v);
    if (w === v || !netOk(t, 't', v, w)) return v;
    t.nodeValue = w; return w;
  }
  function pvTextNode(t) {
    const p = t.parentNode;
    let v = t.nodeValue;
    if (p && v && p.nodeType === 1 && typeof ownText === 'function') v = ownText(t, p, v);
    if (p && v && p.nodeType === 1 && (S.rand || v.indexOf(RS_A) >= 0)) { rvTextNode(t, p, v); return; }
    if (!p || !v || p.nodeType !== 1 || /^(SCRIPT|STYLE|TEXTAREA|NOSCRIPT)$/.test(p.tagName) || (p.closest && p.closest('.pv,.badge,.pvx,' + PV_CNT))) return;
    if (p.closest && p.closest('[data-a="rpPick"],.cal [data-a="pickDay"] > .dn')) return;
    let w = v;
    const pl = S.hide && p.closest ? p.closest('.pvl') : null;
    if (pl) { const pk = pl.getAttribute('data-pk');
      w = v.split(PV_RE).map((x, i) => i % 2 ? pvW(x) : ownSeg(x, pk)).join('');
      if (w.indexOf(PV_A) < 0) { if (w !== v && netOk(t, 't', v, w)) t.nodeValue = w; return; } }
    else if (S.hide && /\d/.test(v)) { const inL = !!(p.closest && p.closest('.pvl'));
      w = v.split(PV_RE).map((x, i) => i % 2 ? pvW(x) : inL ? locName(x) : pvNet(x)).join(''); }
    if (w.indexOf(PV_A) < 0) { if (w !== v && S.hide && netOk(t, 't', v, w)) t.nodeValue = w; return; }
    if (p.namespaceURI === SVGNS) { t.nodeValue = w.replace(PV_RE, '$1'); p.classList.add('pv'); return; }
    const f = document.createDocumentFragment();
    w.split(PV_RE).forEach((x, i) => { if (!x) return; if (i % 2) { const sp = document.createElement('span'); sp.className = 'pv'; sp.textContent = x; f.appendChild(sp); } else f.appendChild(document.createTextNode(x)); });
    p.replaceChild(f, t);
  }
  function pvAttrs(el) {
    if (typeof ownAttrs === 'function') ownAttrs(el);
    if (S.rand || rvHas(el)) { rvAttrs(el); return; }
    if (S.hide && el.closest && el.closest('.pvx')) return;
    for (const a of ['title', 'aria-label']) {
      const v = el.getAttribute && el.getAttribute(a); if (!v) continue;
      const w = (S.hide ? (el.hasAttribute('data-pvl') ? locName : pvNet)(v.replace(PV_RE, '$1')) : v).replace(PV_RE, '$1');
      if (w !== v && netOk(el, a, v, w)) el.setAttribute(a, w);
    }
  }
  const RV_IN = new WeakMap(), RV_IN_SEL = 'input[data-draft="rk"],input[data-pv],input[data-pr],input[data-alias],input[data-draft="nalias"],input[data-draft$=":alias"],input[data-su-in="w_label"],input[data-su-in="p_label"]';
  const RV_VAL = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
  const RV_HIDE_SEL = 'input[data-pr],input[data-alias],input[data-draft="nalias"],input[data-draft$=":alias"],input[data-su-in="w_label"],input[data-su-in="p_label"]';
  const rvLock = el => !!(S.rand || (S.hide && el.matches && el.matches(RV_HIDE_SEL)));
  let rvFoc = null;
  function rvRefocus() {
    const f = rvFoc; if (!f) return;
    const find = () => { const root = f.ov ? $('#overlay') : document; return root ? (f.id ? root.querySelector('#' + f.id) : Array.from(root.querySelectorAll('input[data-draft]')).find(x => x.getAttribute('data-draft') === f.k)) || null : null; };
    const ok = el => !!(el && !el.disabled && !RV_IN.has(el));
    const put = el => { try { if (document.activeElement !== el) el.focus(); el.setSelectionRange(f.a, f.b); } catch (e) {  } };
    const el0 = find(); if (!ok(el0)) return;
    rvFoc = null; put(el0);
    const again = () => { const el = find(), ae = document.activeElement; if (ok(el) && (ae === el || !ae || ae === document.body)) put(el); };
    try { requestAnimationFrame(again); } catch (e) {  }
    setTimeout(again, 0);
  }
  function rvInputs(root) {
    if (!root || root.nodeType !== 1) return;
    const list = root.matches && root.matches(RV_IN_SEL) ? [root] : Array.from(root.querySelectorAll(RV_IN_SEL));
    list.forEach(el => {
      const sv = RV_IN.get(el);
      if (rvLock(el)) {
        if (!sv) {
          if (document.activeElement === el && (el.id || el.getAttribute('data-draft')) && !(rvFoc && rvFoc.id === (el.id || '') && rvFoc.k === (el.getAttribute('data-draft') || ''))) {
            const ov9 = $('#overlay'); rvFoc = { id: el.id || '', k: el.getAttribute('data-draft') || '', a: el.selectionStart, b: el.selectionEnd, ov: !!(ov9 && ov9.contains(el)) };
          }
          RV_IN.set(el, { v: el.value, a: el.getAttribute('value'), c: el.getAttribute('data-cur'), d: el.disabled, ph: el.getAttribute('placeholder') });
          try { Object.defineProperty(el, 'value', { configurable: true, get() { return RV_VAL.get.call(this); },
            set(x) { const s9 = RV_IN.get(this); if (s9 && (s9.own ? !!(S.hide || S.rand) : rvLock(this))) s9.v = String(x == null ? '' : x); else RV_VAL.set.call(this, x); } }); } catch (e) {  }
        }
        RV_VAL.set.call(el, ''); el.removeAttribute('value'); el.removeAttribute('data-cur'); el.disabled = true; el.setAttribute('placeholder', S.rand ? '랜덤값 모드 — 가려짐' : '금액 가리기 — 가려짐');
      } else if (sv) {
        RV_IN.delete(el);
        try { delete el.value; } catch (e) {  }
        if (sv.a != null) el.setAttribute('value', sv.a);
        if (sv.c != null) el.setAttribute('data-cur', sv.c);
        el.value = sv.v; el.disabled = sv.d;
        if (sv.ph != null) el.setAttribute('placeholder', sv.ph); else el.removeAttribute('placeholder');
      }
    });
  }
  const RV_OWN_SEL = 'input[type="search"],input[type="text"],input:not([type])';
  const RV_TYPED = typeof WeakMap === 'function' ? new WeakMap() : null;
  const RV_TYPK = new Map();
  const rvKey = el => { if (!el || !el.getAttribute) return ''; const d9 = el.getAttribute('data-draft'), n9 = el.getAttribute('data-su-in') || el.getAttribute('name') || el.getAttribute('aria-label');
    return d9 ? 'd:' + d9 : el.id ? 'i:' + el.id : n9 ? 'n:' + n9 : ''; };
  if (typeof document !== 'undefined' && document.addEventListener) document.addEventListener('input', ev => {
    const el = ev.target; if (!RV_TYPED || !ev.isTrusted || !(S.hide || S.rand) || !el || !el.matches || !el.matches(RV_OWN_SEL)) return;
    RV_TYPED.set(el, el.value); const k9 = rvKey(el); if (k9) RV_TYPK.set(k9, el.value); }, true);
  function rvOwnInputs(root, live) {
    if (!root || root.nodeType !== 1 || typeof ownScrub !== 'function') return;
    const on = !!(S.hide || S.rand);
    if (!on) RV_TYPK.clear();
    const list9 = root.matches && root.matches(RV_OWN_SEL) ? [root] : Array.from(root.querySelectorAll(RV_OWN_SEL));
    list9.forEach(el => {
      if (el.matches && el.matches(RV_IN_SEL)) return;
      const sv = RV_IN.get(el);
      if (on) {
        const k9 = rvKey(el), typed9 = (RV_TYPED && RV_TYPED.get(el) === el.value) || (!!k9 && RV_TYPK.get(k9) === el.value);
        if (sv || !el.value || typed9 || ownScrub(el.value) === el.value) return;
        if (document.activeElement === el && (el.id || el.getAttribute('data-draft'))) { const ov9 = $('#overlay'); rvFoc = { id: el.id || '', k: el.getAttribute('data-draft') || '', a: el.selectionStart, b: el.selectionEnd, ov: !!(ov9 && ov9.contains(el)) }; }
        RV_IN.set(el, { v: el.value, a: el.getAttribute('value'), c: el.getAttribute('data-cur'), d: el.disabled, ph: el.getAttribute('placeholder'), own: true });
        try { Object.defineProperty(el, 'value', { configurable: true, get() { return RV_VAL.get.call(this); },
          set(x) { const s9 = RV_IN.get(this); if (s9 && (S.hide || S.rand)) s9.v = String(x == null ? '' : x); else RV_VAL.set.call(this, x); } }); } catch (e) {  }
        RV_VAL.set.call(el, ''); el.removeAttribute('value'); el.disabled = true; el.setAttribute('placeholder', S.rand ? '랜덤값 모드 — 가려짐' : '금액 가리기 — 가려짐');
      } else {
        if (RV_TYPED) RV_TYPED.delete(el);
        if (sv && sv.own) {
          RV_IN.delete(el);
          try { delete el.value; } catch (e) {  }
          if (sv.a != null) el.setAttribute('value', sv.a);
          el.value = sv.v; el.disabled = sv.d;
          if (sv.ph != null) el.setAttribute('placeholder', sv.ph); else el.removeAttribute('placeholder');
        }
      }
    });
  }
  function pvAnim(root) {
    if (!root || root.nodeType !== 1 || !(S.hide || S.rand)) return;
    const SEL = '[data-n][data-v],[data-fl][data-v]', list = root.matches && root.matches(SEL) ? [root] : [];
    root.querySelectorAll(SEL).forEach(el => list.push(el));
    list.forEach(el => { el.removeAttribute('data-n'); if (el.getAttribute('data-v') !== '0') el.setAttribute('data-v', '0'); });
  }
  function pvFix(root) {
    if (!root) return;
    if ((S.rand || S.hide) && root.nodeType === 1) { rvInputs(root); if (typeof rvOwnInputs === 'function') rvOwnInputs(root, true); }
    pvAnim(root);
    if (root.nodeType === 3) { pvTextNode(root); return; }
    if (root.nodeType !== 1) return;
    if (!S.hide && !S.rand && root.textContent.indexOf(PV_A) < 0 && root.textContent.indexOf(RS_A) < 0) return;
    const tw = document.createTreeWalker(root, NodeFilter.SHOW_TEXT), list = []; let n;
    while ((n = tw.nextNode())) list.push(n);
    list.forEach(pvTextNode);
    pvAttrs(root); root.querySelectorAll('[title],[aria-label],.lkc[data-q],[placeholder],[data-l]').forEach(pvAttrs);
  }
  if (window.MutationObserver) new MutationObserver(recs => {
    for (const r of recs) {
      if (r.type === 'childList') r.addedNodes.forEach(pvFix);
      else if (r.type === 'characterData') pvTextNode(r.target);
      else if (r.attributeName === 'value' || r.attributeName === 'data-cur') { const s9 = rvLock(r.target) && RV_IN.get(r.target), x9 = s9 && r.target.getAttribute(r.attributeName);
        if (x9 != null && s9) { if (r.attributeName === 'value') s9.a = x9; else s9.c = x9; r.target.removeAttribute(r.attributeName); } }
      else if (S.hide || S.rand) pvAttrs(r.target);
    }
    if ((S.hide || S.rand) && typeof rvOwnInputs === 'function' && recs.some(r => r.type === 'childList' || (r.type === 'attributes' && r.attributeName === 'value'))) rvOwnInputs(document.body, true);
  }).observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['title', 'aria-label', 'data-q', 'value', 'data-cur', 'placeholder', 'data-l'] });
  function rvTextNode(t, p, v) {
    if (/^(SCRIPT|STYLE|TEXTAREA|NOSCRIPT)$/.test(p.tagName)) return;
    const keep = !!(p.closest && (p.closest('.pv,.rv,.badge,.pvx,' + PV_CNT) || p.closest('[data-a="rpPick"],.cal [data-a="pickDay"] > .dn')));
    if (keep && v.indexOf(RS_A) < 0) return;
    let w = v;
    const pl = S.rand && !keep && p.closest ? p.closest('.pvl') : null;
    if (pl) { const pk = pl.getAttribute('data-pk'); w = v.split(MK_RE).map((x, i) => (i % 2 ? x : ownSeg(x, pk))).join('');
      if (w.indexOf(RS_A) < 0 && w.indexOf(PV_A) < 0) { if (w !== v && netOk(t, 't', v, w)) t.nodeValue = w; return; } }
    else if (S.rand && !keep && /\d/.test(v)) w = p.closest && p.closest('.pvl') ? locNameM(v) : pvNetM(v);
    if (w.indexOf(RS_A) < 0 && w.indexOf(PV_A) < 0) { if (w !== v && netOk(t, 't', v, w)) t.nodeValue = w; return; }
    if (p.namespaceURI === SVGNS) { const pv9 = w.indexOf(PV_A) >= 0; t.nodeValue = w.replace(PV_RE, '$1').replace(RS_RE, '$1'); p.classList.add(pv9 ? 'pv' : 'rv'); return; }
    if (w.indexOf(PV_A) < 0) { const sp = document.createElement('span'); sp.className = 'rv'; sp.textContent = w.replace(RS_RE, '$1'); p.replaceChild(sp, t); return; }
    const f = document.createDocumentFragment();
    w.split(MK_RE).forEach((x, i) => { if (!x) return; if (i % 2) { const sp = document.createElement('span'); sp.className = x.charAt(0) === PV_A ? 'pv' : 'rv'; sp.textContent = x.slice(1, -1); f.appendChild(sp); } else f.appendChild(document.createTextNode(x)); });
    p.replaceChild(f, t);
  }
  const RV_SEEN = new Set();
  const rvHas = el => !!(el && el.getAttribute && /\uE004/.test((el.getAttribute('title') || '') + (el.getAttribute('aria-label') || '')));
  function rvAttrs(el) {
    if (!el || !el.getAttribute) return;
    const keep = !!(el.closest && el.closest('.pvx'));
    for (const a of ['title', 'aria-label', 'data-q']) {
      if (a === 'data-q' && !(el.matches && el.matches('.lkc'))) continue;
      const v = el.getAttribute(a); if (!v || RV_SEEN.has(v)) continue;
      const w = a === 'data-q' ? (S.rand && /\d/.test(v) ? pvNet(v).replace(PV_RE, '•••') : v)
        : (S.rand && !keep && (/\d/.test(v) || el.hasAttribute('data-pvl')) ? (el.hasAttribute('data-pvl') ? locNameM : pvNetM)(v) : v).replace(PV_RE, '$1').replace(RS_RE, '$1');
      if (RV_SEEN.size > 20000) RV_SEEN.clear();
      RV_SEEN.add(w);
      if (w !== v && netOk(el, a, v, w)) el.setAttribute(a, w);
    }
  }
  function rvCookie() {
    try {
      const has = /(?:^|;\s*)tj_v2_rand=1(?:;|$)/.test(document.cookie || '');
      if (S.rand === has) return;
      document.cookie = 'tj_v2_rand=' + (S.rand ? '1; Max-Age=31536000' : '0; Max-Age=0') + '; Path=/; SameSite=Strict' + (location.protocol === 'https:' ? '; Secure' : '');
    } catch (e) {  }
  }
  function rvLinks() {
    if (!S.rand) return;
    const pre = []; Object.keys(EXPL).forEach(k => { pre.push(EXPL[k][0], EXPL[k][1]); });
    document.querySelectorAll('a[href]').forEach(a => { const u = a.getAttribute('href') || ''; if (pre.some(p => u.indexOf(p) === 0)) { a.removeAttribute('href'); a.removeAttribute('target'); } });
  }
  function rvMark() {
    rvCookie();
    let wm = document.getElementById('randWm');
    if (!S.rand) { if (wm) wm.remove(); return; }
    if (wm) return;
    wm = document.createElement('div'); wm.id = 'randWm'; wm.className = 'randwm'; wm.setAttribute('aria-hidden', 'true');
    wm.innerHTML = '<span>랜덤값</span><span>랜덤값</span><span>랜덤값</span><span>랜덤값</span>';
    document.body.appendChild(wm);
  }
  function pvStripAmt(t) {
    let s = String(t == null ? '' : t);
    const keep = [], K = x => { keep.push(x); return '\uE010' + (keep.length - 1) + '\uE011'; };
    const N = '[+\\-−]?\\d[\\d,]*(?:\\.\\d+)?';
    s = s.replace(/0x[0-9a-fA-F]{6,}(?:…[0-9a-fA-F]{2,})?|[1-9A-HJ-NP-Za-km-z]{32,}/g, K)
      .replace(/\b\d{4}-\d{2}-\d{2}(?![\d.,])/g, K)
      .replace(new RegExp(N + '\\s*[-~–—]\\s*' + N + '(?=\\s?(?:만(?!기|료|약|큼|일|든|족|나|남|점)|억|천|원(?!화|금|래|인|칙|본|문|장|숭|두)|달러|불|usd[tc]?|krw|[kKmM](?![A-Za-z])))', 'gi'), ' ')
      .replace(new RegExp('(US\\$|\\$|₩|￦|\\bUSD[TC]?|\\bKRW)\\s?' + N + '\\s*[-~–—]\\s*' + N, 'gi'), (a, u) => (/^[A-Za-z]/.test(u) ? u + ' ' : ' '))
      .replace(/\d{4}-\d{2}(?:-\d{2})?/g, K)
      .replace(/(^|[^\d.,])(\d{1,2}\/\d{1,2}|\d{2}-\d{2})(?![\d.,])/g, (a, p, d) => p + K(d))
      .replace(/(?:최근|지난)\s?\d{1,4}\s?(?:일|주|달|개월|년)/g, K)
      .replace(/\d{1,4}\s?(?:년|월|일(?!\s?(?:원|달러))|시|분)/g, K);
    s = s.replace(new RegExp('(?:US\\$|\\$|₩|￦)\\s?' + N + '(?:\\s?(?:만|억|천|[kKmMbB](?![A-Za-z])))?(?:\\s?(?:원|달러|불))?', 'g'), ' ')
      .replace(new RegExp(N + '\\s?(?:만|억|천)(?:\\s?(?:원|달러|불))?', 'g'), ' ')
      .replace(new RegExp(N + '\\s?(?:원|달러|불)', 'g'), ' ')
      .replace(new RegExp(N + '\\s?(usd[tc]?|krw)(?![A-Za-z])', 'gi'), (a, u) => ' ' + u)
      .replace(new RegExp(N + '\\s?[kKmM](?![A-Za-z])', 'g'), ' ')
      .replace(new RegExp('\\b(USD[TC]?|KRW|US)\\s?' + N, 'gi'), (a, u) => u + ' ')
      .replace(new RegExp('(^|[^\\w.])' + N + '\\s+(?=[A-Za-z][A-Za-z0-9]{1,9}\\b)', 'g'), (a, p) => p)
      .replace(new RegExp(N + '\\s?(?:개|주|좌)', 'g'), ' ')
      .replace(new RegExp(N + '(?=\\s?(?:이상|넘|초과|보다|이하|미만|안\\s?되|아래|짜리))', 'g'), ' ')
      .replace(new RegExp('\\b([A-Za-z][A-Za-z0-9]{1,9})\\s+' + N + '(?![\\d.,]|\\s?(?:년|월|일|시|분|주|달|개월))', 'g'), (a, u) => u + ' ')
      .replace(/[+\-−]?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d{5,})(?![\d.])/g, ' ')
      .replace(/(^|[^\w.,])(?!(?:19|20)\d\d(?![\w.,]))[+\-−]?\d{3,4}(?![\w.,])/g, (a, p) => p + ' ');
    return s.replace(/\uE010(\d+)\uE011/g, (a, i) => keep[+i]).replace(/\s{2,}/g, ' ').trim();
  }
  const pvRoot = () => {
    { const ov9 = $('#overlay'); if (ov9) ov9.__h = ''; }
    const r = document.documentElement; r.classList.toggle('pvh', !!(S.hide || S.rand)); r.classList.toggle('pvr', !!S.rand); rvInputs(document.body); pvAnim(document.body);
    const srch9 = window.TJSearch; if (srch9 && typeof srch9._pvGuard === 'function') { try { srch9._pvGuard(); } catch (e) {  } }
    rvOwnInputs(document.body);
    const wow9 = window.TJWow; if (wow9 && typeof wow9.onPv === 'function') { try { wow9.onPv(); } catch (e) {  } }
    const hl9 = window.TJHealth; if (hl9 && hl9._state && (hl9._state.open || hl9._state.pop) && typeof hl9.repaint === 'function') { try { hl9.repaint(); } catch (e) {  } }
    if (S.hide || S.rand) document.querySelectorAll('.sx-usd').forEach(el => { if (!el.querySelector('.pv')) el.innerHTML = '<span class="pv">' + PVM.usd + '</span>'; });
    if (S.hide || S.rand) document.querySelectorAll('.prt').forEach(el => { if (!el.querySelector('.pv')) el.innerHTML = '<span class="pv">' + PR_FAKE + '</span>'; });
    if (S.hide || S.rand) document.querySelectorAll('.aib').forEach(el => { if (el.textContent !== AI_HIDE) el.textContent = AI_HIDE; });
    if (S.hide || S.rand) document.querySelectorAll('.aib-l').forEach(el => { el.textContent = '가림'; });
    if (S.hide || S.rand) document.querySelectorAll('.pvm').forEach(el => { const t9 = String(el.textContent || '').trim(), sg = /^[+−-]/.test(t9) ? t9.charAt(0) : ''; el.innerHTML = sg + pvMoney('', true).replace(PV_RE, '<span class="pv">$1</span>'); });
    if (S.hide || S.rand) document.querySelectorAll('[data-pvt]').forEach(el => { const v9 = el.getAttribute('title'); if (v9) el.setAttribute('title', pvNet(v9.replace(PV_RE, '$1').replace(RS_RE, '$1')).replace(PV_RE, '$1')); });
    rvLinks();
    if (S.hide || S.rand) LS.del('tj_v2_srch_recent');
    rvMark();
    const su9 = window.__tjSetup; if (su9 && su9.U && (su9.U.open || su9.U.tierSheet || su9.U.panelOpen) && typeof su9.render === 'function') { try { su9.render(); } catch (e) {  } }
  };
  function oaSwapKeepForm() {
    const v = $('#view');
    if (!v || !v.querySelector('.oamain') || !S.oa.d) return;
    const t = document.createElement('div');
    t.innerHTML = vOther();
    ['.oak', '.oamain', '.oahist'].forEach(sel => { const a = v.querySelector(sel), b = t.querySelector(sel); if (a && b) a.replaceWith(b); });
  }
  function setHide(on) {
    S.hide = !!on; LS.set('tj_v2_hide', S.hide ? '1' : '0');
    attdPurge();
    if (S.hide && S.rand) { S.rand = false; LS.set('tj_v2_rand', '0'); }
    pvRoot();
    S.anim.first = true; S.anim.nums = {}; S.anim.cells = {};
    vib(); render(); renderOverlay();
    if (S.deferred && S.tab === 'other') oaSwapKeepForm();
    if (S.hide) pvFix(document.body);
    if (S.deferred && S.tab === 'daily') dmSwapKeepForm();
    const hero = $('#tjHero'); if (hero && S.D) hero.remove();
    if (!S.hide && !S.rand) rvRefocus();
    toast(S.hide ? '금액 가리기 켜짐' + (S.mobile ? '' : ' · Shift+H 로 끄기') : '금액 보이기');
  }
  function rkApply() {
    RK = rkFix() || RK_DRAW;
    S.anim.first = true; S.anim.nums = {}; S.anim.cells = {};
    const ae9 = document.activeElement; if (ae9 && ae9.getAttribute && ae9.getAttribute('data-draft') === 'rk') ae9.blur();
    render();
    if (S.rand && S.deferred) renderView();
    renderOverlay();
    if (S.rand) pvFix(document.body);
  }
  function setRand(on) {
    S.rand = !!on; LS.set('tj_v2_rand', S.rand ? '1' : '0');
    attdPurge();
    if (S.rand && S.hide) { S.hide = false; LS.set('tj_v2_hide', '0'); }
    if (S.rand) clearCache();
    pvRoot();
    S.anim.first = true; S.anim.nums = {}; S.anim.cells = {};
    vib(); render(); renderOverlay();
    if (S.deferred && S.tab === 'other') oaSwapKeepForm();
    if (S.rand) pvFix(document.body);
    if (S.deferred && S.tab === 'daily') dmSwapKeepForm();
    const hero = $('#tjHero'); if (hero && S.D) hero.remove();
    if (!S.rand) rvRefocus();
    toast(S.rand ? '금액 랜덤값 켜짐 — 실제와 다른 예시 숫자예요' : '금액 랜덤값 꺼짐');
  }

  function wowSlot(k, x) { try { return window.TJWow && typeof window.TJWow.slot === 'function' ? String(window.TJWow.slot(k, x) || '') : ''; } catch (e) { return ''; } }

  window.__tjSearchApi = {
    pvStripAmt,
    ownNm, locName,
    S, esc, m, px, q, krw, short, fmtTs, isoDay, isoOf, ymOf, pvW, PVM, num, arr, IC, LS, toast, render, icon, CHAIN_KO, chainOf, exUrl, evA, hs, pctS,
    Finder, sxIndex, sxGo, sxWalRows, openReceipt, nftLoad, oaNeed, partHave, dayCnt, dayContrib, rcptable, hydrateLogos, dayKeyOf, oaNameTxt,
    initHash: location.hash,
    closeDrawerThen,
    pvOn: () => !!(S.hide || S.rand),
    goTab: t => { if (S.tab === t) render(); else location.hash = '#' + t; },
    goDay: k => { wkOff(); S.day = k; S.calYM = ymOf(k) || S.calYM; S.dayEvLimit = 20; if (S.tab === 'daily') render(); else location.hash = '#daily'; }
  };

  const KB_TAB = { d: 'dash', j: 'journal', l: 'daily', o: 'outflows', u: 'unmatched', a: 'other', s: 'settings' };
  let kbG = 0;
  const kbRows = () => Array.from(document.querySelectorAll('#view [data-anc]')).filter(x => x.offsetParent || x.getClientRects().length);
  function rowFocusEl(n) {
    if (n.matches('button,[tabindex],a[href]')) return n;
    return Array.from(n.querySelectorAll('button,[tabindex="0"],a[href]')).find(x => !x.closest('[data-kbskip]')) || null;
  }
  function kbMove(dir) {
    const L = kbRows(); if (!L.length) return;
    const cur = document.querySelector('#view .kbsel'), i = cur ? L.indexOf(cur) : -1;
    const n = L[Math.max(0, Math.min(L.length - 1, i < 0 ? (dir > 0 ? 0 : L.length - 1) : i + dir))];
    if (cur && cur !== n) cur.classList.remove('kbsel');
    n.classList.add('kbsel');
    const f = rowFocusEl(n);
    if (f) { try { f.focus({ preventScroll: true }); } catch (e) {  } }
    try { n.scrollIntoView({ block: 'nearest', behavior: uiReduce() ? 'auto' : 'smooth' }); } catch (e) { n.scrollIntoView(); }
  }
  const KB_DLG = '.modal-bg,.drawer,.usheet,.tjh-bg,[aria-modal="true"],[role="dialog"],[role="alertdialog"]';
  const kbDialog = () => !!(S.modal || S.sheet || S.drawer || S.pop) || Array.from(document.querySelectorAll(KB_DLG)).some(e => e.getClientRects().length > 0);
  document.addEventListener('keydown', ev => {
    if (ev.defaultPrevented || ev.ctrlKey || ev.metaKey || ev.altKey || S.locked || !S.D) { kbG = 0; return; }
    const t = ev.target;
    if (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable)) { kbG = 0; return; }
    if (kbDialog()) { kbG = 0; return; }
    const k = ev.key;
    if (kbG && Date.now() - kbG < 1500) {
      kbG = 0;
      if (KB_TAB[k]) { ev.preventDefault(); go(KB_TAB[k]); }
      return;
    }
    if (k === '?') { ev.preventDefault(); uiSheetOpen('keys', '', '키보드 단축키'); return; }
    if (k === 'g') { kbG = Date.now(); return; }
    if (k === 'j' || k === 'k') { ev.preventDefault(); kbMove(k === 'j' ? 1 : -1); }
  });
  UI_SHEETS.keys = () => {
    const kb = s => s.split(' ').map(x => '<kbd>' + esc(x) + '</kbd>').join(' ');
    const rows = [['g d', '대시보드'], ['g j', '매매일지'], ['g l', '일별 기록'], ['g o', '보낸 내역'], ['g u', '미매칭'], ['g a', '기타 자산'], ['g s', '설정'],
      ['j', '목록 다음 줄'], ['k', '목록 이전 줄'], ['Enter', '고른 줄 열기'], ['/', '전체 검색'], ['⌘ K', '전체 검색'], ['⇧ H', '금액 가리기'], ['Esc', '닫기'], ['?', '이 도움말']];
    return '<div class="kbhelp">' + rows.map(r => '<div class="kbr"><span class="kbk">' + kb(r[0]) + '</span><span>' + esc(r[1]) + '</span></div>').join('') + '</div>'
      + '<div class="cap" style="margin-top:10px">입력 칸에 글자를 쓰는 중에는 단축키가 동작하지 않아요</div>';
  };
  (() => {
    let sx = 0, sy = 0, on = false;
    const hScroll = (t, stop) => { for (let n = t; n && n !== stop && n.nodeType === 1; n = n.parentElement) {
      if (n.scrollWidth > n.clientWidth + 1) { let ox = ''; try { ox = getComputedStyle(n).overflowX; } catch (e) {  } if (ox === 'auto' || ox === 'scroll') return true; } } return false; };
    document.addEventListener('touchstart', ev => {
      const c = S.tab === 'daily' && S.mobile && ev.touches.length === 1 && ev.target.closest && ev.target.closest('#view .card.rev');
      if (!c || ev.target.closest('input,textarea,button.dm-ed,.chart,.hmw,.fbars') || hScroll(ev.target, c)) { on = false; return; }
      on = true; sx = ev.touches[0].clientX; sy = ev.touches[0].clientY;
    }, { passive: true });
    document.addEventListener('touchend', ev => {
      if (!on) return; on = false;
      const tt = ev.changedTouches && ev.changedTouches[0]; if (!tt) return;
      const dx = tt.clientX - sx, dy = tt.clientY - sy;
      if (Math.abs(dx) < 60 || Math.abs(dx) < 2 * Math.abs(dy)) return;
      A.dayStep({ dataset: { v: dx < 0 ? '1' : '-1' } });
      vib();
    }, { passive: true });
  })();

  readUrl();
  syncUrl();
  try { if (!S.D && S.tab === 'dash' && $('#tjHero')) renderChrome(); else render(); }
  catch (e) { logError('[tj] 첫 그리기 실패', e); }
  setTimeout(() => { if (S.D && S.viewOk) return; if (S.rescue && S.rescue.card) return;
    const b = $('#banners'); if (b && !$('#tjSlow')) b.insertAdjacentHTML('afterbegin', '<div class="card" id="tjSlow" role="status" style="padding:12px 16px;margin:8px 0;display:flex;gap:10px;align-items:center;flex-wrap:wrap"><span>화면을 여는 데 오래 걸리고 있어요' + (S.err ? ' · ' + esc(errTxt(S.err).slice(0, 80)) : '') + '</span><button class="btn sm" data-a="reloadPage">다시 시도</button><button class="btn sm" data-a="resetPrefs">설정 초기화하고 다시 열기</button></div>'); }, 25000);
  pvRoot();
  if (S.rand) clearCache();
  if (S.hide || S.rand) pvFix(document.body);
  bootLoad();
  setInterval(() => { if (!document.hidden) refresh(false, null, true); }, POLL_MS);
  setInterval(() => { if (!document.hidden && !S.locked && (RLW.size || arr(S.D && S.D.of).some(x => x.applyWait))) rlFetch(false); }, 5000);
  window.TJ = { clearCache: clearCache, onUnauthorized: onUnauthorized, isLocked: () => !!S.locked, pgSize: uiPageSize,
    bfInfo: () => (S.locked ? null : bfInfo()),
    revealAndHighlight: revealAndHighlight,
    ext: { S, m, esc, num, arr, nf, q, px, pxC, short, fmtTs, isoDay, todayISO, pvOn, cls, pctS, IC, LS, toast, post, render, renderView, gMatch, KV, pvStripAmt,
      revealAndHighlight, planOfGroup, rate: () => rate(), rateLive: () => !!(S.D && S.D.rateLive), lockedNow: () => !!S.locked, retPct,
      confirmAsk, pvm, icon, hydrateLogos } };
  if (window.TJHealth && typeof window.TJHealth.chrome === 'function') { try { window.TJHealth.chrome(S.mobile); } catch (e) {  } }
  window.__tjBooted = true;
  window.__tj = { S, A, refresh, applyPatch, derive, clearCache, px, px4, hs, moneyTxt, pxC,
    m, oaTot, oaV,
    attOf,
    attItems, attLine,
    heroNums,
    dmCoins, dmGet,
    partsDbg: { P: () => S.parts, reset: (v, n) => { partsReset(v, n); return S.parts; }, fetch: (P, n) => partFetch(P, n), fromIdbNow: () => partsFromIdbNow() },
    jProbe: () => ({ last: S.jLast || null, cards: jBase().map(p => ({ key: p.key, sym: p.sym, legs: p._legs || null, lp: !!p._lp, kind: p.kind || '', st: p._st || p.status, real: cardReal(p), agg: pAgg(p), soldPct: p._soldPct })) }) };
})();
