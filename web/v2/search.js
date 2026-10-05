(function () {
  'use strict';
  if (window.TJSearch) return;
  const API = () => window.__tjSearchApi || null;
  const $ = (s, r) => (r || document).querySelector(s);
  const LS_RECENT = 'tj_v2_srch_recent', LS_SAVED = 'tj_v2_srch_saved';
  const RECENT_MAX = 8, SAVED_MAX = 12, GROUP_N = 3, GROUP_ALL = 40, SRV_DEBOUNCE = 150, Q_MAX = 120;
  const KINDS = [['coin', '코인'], ['cycle', '매매일지'], ['outflow', '보낸 내역'], ['tx', '거래·해시'], ['event', '기록'], ['day', '날짜'], ['receipt', '차익 영수증'],
    ['review', '리뷰'], ['memo', '근거 메모'], ['pending', '미매칭'], ['nft', 'NFT'], ['other', '기타 자산'], ['wallet', '지갑'], ['deposit', '입금 주소'], ['setting', '설정']];
  const KL = Object.fromEntries(KINDS);
  const KORD = Object.fromEntries(KINDS.map((k, i) => [k[0], i]));
  const SCOPE0 = [['all', '전체'], ['coin', '코인'], ['wallet', '지갑·주소'], ['tx', '거래·해시'], ['day', '날짜'], ['outflow', '보낸 내역'], ['pending', '미매칭'], ['nft', 'NFT'], ['setting', '설정']];
  const TABK = { coin: 'dash', cycle: 'journal', event: 'journal', tx: 'journal', outflow: 'outflows', pending: 'unmatched', nft: 'other', other: 'other', day: 'daily', review: 'daily', receipt: 'daily', memo: 'daily' };
  const CHAIN_ALIAS = { ethereum: 'eth', eth: 'eth', mainnet: 'eth', base: 'base', arb: 'arbitrum', arbitrum: 'arbitrum', op: 'optimism', optimism: 'optimism', bsc: 'bsc', bnb: 'bsc',
    polygon: 'polygon', matic: 'polygon', sol: 'sol', solana: 'sol', zksync: 'zksync', scroll: 'scroll', gnosis: 'gnosis', avax: 'avalanche', avalanche: 'avalanche', linea: 'linea',
    blast: 'blast', mantle: 'mantle', monad: 'monad', kaia: 'kaia', bera: 'berachain', berachain: 'berachain', hyperevm: 'hyperevm', sonic: 'sonic', abstract: 'abstract', robinhood: 'robinhood' };
  const TYPE_WORDS = { swap: ['스왑', '온체인 매수', '온체인 매도', 'swap'], buy: ['매수'], sell: ['매도'], deposit: ['입금'], withdraw: ['출금'], send: ['전송', '보냄'], lp: ['lp', '유동성'],
    fee: ['가스', '수수료'], airdrop: ['에어드랍', 'airdrop'] };
  const SCOPE_WORDS = { 코인: 'coin', 보유: 'coin', 매매일지: 'cycle', 사이클: 'cycle', 보낸: 'outflow', 보낸내역: 'outflow', 해시: 'tx', tx: 'tx', 기록: 'event', 날짜: 'day', 일별: 'day', 리뷰: 'review',
    영수증: 'receipt', 메모: 'memo', 미매칭: 'pending', nft: 'nft', 기타: 'other', 지갑: 'wallet', 입금: 'deposit', 설정: 'setting' };
  const SV = d => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + d + '</svg>';
  const IX = { x: SV('<path d="M6 6l12 12M18 6L6 18"/>'), clock: SV('<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>'), hash: SV('<path d="M5 9h14M5 15h14M10 4L8 20M16 4l-2 16"/>'),
    img: SV('<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><circle cx="9" cy="10" r="1.6"/><path d="M20.5 16l-5-5-8.5 8.5"/>'), rcpt: SV('<path d="M6 3h12v18l-3-2-3 2-3-2-3 2z"/><path d="M9 8h6M9 12h6"/>'),
    filter: SV('<path d="M4 5h16l-6 7.5V19l-4-2v-4.5z"/>'), eyeoff: SV('<path d="M3 3l18 18M10.6 5.1A10 10 0 0 1 12 5c5 0 9 4.5 10 7-.4 1-1.3 2.4-2.6 3.7M6.6 6.6C4.4 8 2.9 10.2 2 12c1 2.5 5 7 10 7 1.6 0 3.1-.5 4.4-1.2"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>'),
    star: SV('<path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/>'), spark: SV('<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M6 18l2.5-2.5M15.5 8.5L18 6"/>'),
    pulse: SV('<path d="M3 12h4l2.5-6 4 12 2.5-6H21"/>'), memo: SV('<path d="M5 4h14v16H5z"/><path d="M8 9h8M8 13h8M8 17h5"/>'), nft: SV('<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M12 12l8-4.5M12 12v9M12 12L4 7.5"/>'),
    other: SV('<path d="M4 20V9l8-5 8 5v11z"/><path d="M9 20v-6h6v6"/>'), key: SV('<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M17 6l3 3M15 8l2 2"/>'), back: SV('<path d="M15 6l-6 6 6 6"/>'),
    ext: SV('<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>'), copy: SV('<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>'),
    tag: SV('<path d="M3 12V4h8l10 10-8 8z"/><circle cx="7.5" cy="7.5" r="1.5"/>'), go: SV('<path d="M9 6l6 6-6 6"/>'), enter: SV('<path d="M20 5v7a3 3 0 0 1-3 3H6"/><path d="M10 11l-4 4 4 4"/>') };

  const ST = {
    open: false, q: '', scope: 'all', sel: 0, expand: '', P: null, items: [], flat: [], groups: [], srv: null, srvQ: '', srvBusy: false, srvErr: '', ctl: null, tmr: 0,
    prevFocus: null, pushed: false, back: null, backTmr: 0, copyArm: -1, kbd: false,
    ask: null, askBusy: '', askTmr: 0,
    pvSig: null, srvPv: null, pend: null
  };
  const lsGet = (k, d) => { try { const v = JSON.parse(localStorage.getItem(k) || 'null'); return v == null ? d : v; } catch (e) { return d; } };
  const lsSet = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {  } };
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const num = v => { const n = Number(v); return isFinite(n) ? n : 0; };
  const arr = v => (Array.isArray(v) ? v : []);
  const pvOn = () => { const a = API(); return !!(a && a.pvOn()); };
  const locked = () => { const a = API(); return !a || !a.S || !!a.S.locked || !a.S.D; };
  const wide = () => { try { return window.matchMedia('(min-width: 641px)').matches; } catch (e) { return true; } };
  const reduce = () => { try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { return false; } };
  const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || '');
  const KMOD = isMac ? '⌘' : 'Ctrl';
  const norm = s => String(s == null ? '' : s).toLowerCase().replace(/<[^>]*>/g, '').replace(/[\s·・,.\-_/()'’‘"`›>|:]+/g, '');
  const CHO = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ';
  const cho = s => { let o = ''; for (const ch of String(s)) { const c = ch.charCodeAt(0) - 0xAC00; o += c >= 0 && c < 11172 ? CHO.charAt(Math.floor(c / 588)) : ch; } return o; };
  const isCho = s => /^[ㄱ-ㅎ]+$/.test(s);
  const pad2 = n => (n < 10 ? '0' : '') + n;

  const KST = 9 * 3600e3;
  const kstNow = () => new Date(Date.now() + KST);
  const isoOfD = d => d.getUTCFullYear() + '-' + pad2(d.getUTCMonth() + 1) + '-' + pad2(d.getUTCDate());
  const todayIso = () => isoOfD(kstNow());
  const addDays = (iso, n) => { const d = new Date(Date.parse(iso + 'T00:00:00Z') + n * 864e5); return isoOfD(d); };
  const DOW = ['일', '월', '화', '수', '목', '금', '토'];
  const dowOf = iso => DOW[new Date(Date.parse(iso + 'T00:00:00Z')).getUTCDay()];
  const lastDay = (y, m) => new Date(Date.UTC(y, m, 0)).getUTCDate();
  function mdToIso(mm, dd) {
    const t = todayIso(), y = +t.slice(0, 4);
    let iso = y + '-' + pad2(mm) + '-' + pad2(dd);
    if (iso > t) iso = (y - 1) + '-' + pad2(mm) + '-' + pad2(dd);
    return iso;
  }
  function validIso(s) { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s); if (!m) return false; const y = +m[1], mo = +m[2], d = +m[3]; return mo >= 1 && mo <= 12 && d >= 1 && d <= lastDay(y, mo); }
  function parseDate(s0) {
    const s = String(s0 || '').trim().replace(/\s+/g, ' ');
    if (!s) return null;
    const t = todayIso();
    const one = iso => (validIso(iso) ? { from: iso, to: iso, label: (+iso.slice(5, 7)) + '월 ' + (+iso.slice(8, 10)) + '일 (' + dowOf(iso) + ')' } : null);
    if (s === '오늘') return one(t);
    if (s === '어제') return one(addDays(t, -1));
    if (s === '그제' || s === '그저께') return one(addDays(t, -2));
    const wd = new Date(Date.parse(t + 'T00:00:00Z')).getUTCDay(), mon = addDays(t, -((wd + 6) % 7));
    if (s === '이번주' || s === '이번 주') return { from: mon, to: t, label: '이번 주' };
    if (s === '지난주' || s === '지난 주') return { from: addDays(mon, -7), to: addDays(mon, -1), label: '지난주 ' + (+addDays(mon, -7).slice(5, 7)) + '/' + (+addDays(mon, -7).slice(8)) + '–' + (+addDays(mon, -1).slice(5, 7)) + '/' + (+addDays(mon, -1).slice(8)) };
    const month = (y, mo) => (mo >= 1 && mo <= 12 ? { from: y + '-' + pad2(mo) + '-01', to: y + '-' + pad2(mo) + '-' + pad2(lastDay(y, mo)), label: (y !== +t.slice(0, 4) ? y + '년 ' : '') + mo + '월' } : null);
    if (s === '이번달' || s === '이번 달') return month(+t.slice(0, 4), +t.slice(5, 7));
    if (s === '지난달' || s === '지난 달') { const y = +t.slice(0, 4), mo = +t.slice(5, 7); return mo === 1 ? month(y - 1, 12) : month(y, mo - 1); }
    let m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(s); if (m) return one(m[1] + '-' + pad2(+m[2]) + '-' + pad2(+m[3]));
    m = /^(\d{4})[-.](\d{1,2})$/.exec(s); if (m) return month(+m[1], +m[2]);
    m = /^(\d{4})\.(\d{1,2})\.(\d{1,2})\.?$/.exec(s); if (m) return one(m[1] + '-' + pad2(+m[2]) + '-' + pad2(+m[3]));
    m = /^(\d{1,2})[/.-](\d{1,2})$/.exec(s); if (m && +m[1] >= 1 && +m[1] <= 12 && +m[2] >= 1 && +m[2] <= 31) return one(mdToIso(+m[1], +m[2]));
    m = /^(\d{1,2})월\s?(\d{1,2})일?$/.exec(s); if (m) return one(mdToIso(+m[1], +m[2]));
    m = /^(\d{1,2})월$/.exec(s); if (m) { const mo = +m[1], y = +t.slice(0, 4); return month(mo > +t.slice(5, 7) ? y - 1 : y, mo); }
    return null;
  }
  function parseAmt(s0, rate) {
    const s = String(s0 || '').trim().replace(/,/g, '');
    const m = /^([₩$])?\s?(\d+(?:\.\d+)?)\s?(만|억|천|k|m)?(원)?$/i.exec(s);
    if (!m) return null;
    let v = +m[2];
    const u = (m[3] || '').toLowerCase();
    v *= u === '만' ? 1e4 : u === '억' ? 1e8 : u === '천' ? 1e3 : u === 'k' ? 1e3 : u === 'm' ? 1e6 : 1;
    const krw = m[1] === '₩' || m[4] || u === '만' || u === '억' || u === '천';
    return krw ? v / (rate || 1384) : v;
  }

  const FILT_RE = /(^|\s)(coin|sym|chain|type|kind|after|before|on|pnl|amt|in):(\S+)/gi;
  function parseQ(raw0) {
    const raw = String(raw0 || '').slice(0, Q_MAX);
    const P = { raw, text: '', toks: [], f: {}, chips: [], type: 'text', date: null, amt: null, hex: '', scope: '' };
    const a = API(), rate = a && a.S.D ? num(a.S.D.rate) || 1384 : 1384;
    let rest = raw.replace(FILT_RE, (all, sp, k0, v0) => {
      const k = k0.toLowerCase(), v = String(v0);
      if (k === 'coin' || k === 'sym') { P.f.coin = v.toUpperCase(); P.chips.push({ k: 'coin', t: '코인 ' + v.toUpperCase() }); }
      else if (k === 'chain') { const c = CHAIN_ALIAS[v.toLowerCase()] || v.toLowerCase(); P.f.chain = c; P.chips.push({ k: 'chain', t: '체인 ' + ((a && a.CHAIN_KO[c]) || v) }); }
      else if (k === 'type' || k === 'kind') { const w = v.toLowerCase(); P.f.type = TYPE_WORDS[w] ? w : w; P.chips.push({ k: 'type', t: '종류 ' + (TYPE_WORDS[w] ? TYPE_WORDS[w][0] : v) }); }
      else if (k === 'after' || k === 'before' || k === 'on') {
        const d = parseDate(v);
        if (d) { if (k === 'after') P.f.after = d.from; else if (k === 'before') P.f.before = d.to; else { P.f.after = d.from; P.f.before = d.to; } P.chips.push({ k, t: (k === 'after' ? d.label + ' 이후' : k === 'before' ? d.label + ' 이전' : d.label) }); }
      } else if (k === 'pnl' || k === 'amt') {
        const m = /^(<=|>=|<|>|=)?(-?[₩$]?[\d.,]+(?:만|억|천|k|m)?)$/i.exec(v);
        if (m) { const neg = /^-/.test(m[2]), n0 = parseAmt(m[2].replace(/^-/, ''), rate); if (n0 != null) { P.f[k] = { op: m[1] || (k === 'amt' ? '>=' : '='), v: neg ? -n0 : n0 }; P.chips.push({ k, t: (k === 'pnl' ? '손익 ' : '금액 ') + (m[1] || '') + v.replace(/^[<>=]+/, '') }); } }
      } else if (k === 'in') { const sc = SCOPE_WORDS[v] || SCOPE_WORDS[v.toLowerCase()] || (KL[v] ? v : ''); if (sc) { P.scope = sc; P.chips.push({ k: 'in', t: KL[sc] + '에서' }); } }
      return sp;
    }).trim();
    P.text = rest;
    P.toks = rest.split(/\s+/).map(norm).filter(Boolean);
    const one = rest.replace(/\s+/g, '');
    if (/^0x[0-9a-f]{2,}$/i.test(one)) { P.type = 'hex'; P.hex = one.toLowerCase(); }
    else if (/^[1-9A-HJ-NP-Za-km-z]{6,}$/.test(one) && /\d/.test(one) && /[a-z]/.test(one) && /[A-Z]/.test(one)) { P.type = 'b58'; P.hex = one; }
    else {
      const d = parseDate(rest);
      if (d) { P.type = 'date'; P.date = d; }
      else {
        const am = /^[₩$]?\s?\d[\d,]*(?:\.\d+)?\s?(?:만|억|천|k|m)?원?$/i.test(rest) && !/^\d{1,3}$/.test(rest) ? parseAmt(rest, rate) : null;
        if (am != null && am >= 50) { P.type = 'amt'; P.amt = am; }
        else if (/^[A-Za-z0-9]{2,12}$/.test(rest)) P.type = 'ticker';
      }
    }
    return P;
  }

  function score(name, extra, toks) {
    if (!toks.length) return 1;
    const n = norm(name), k = norm(extra);
    let tot = 0;
    for (const t of toks) {
      let s = 0;
      if (isCho(t)) s = cho(n).indexOf(t) >= 0 ? 45 : cho(k).indexOf(t) >= 0 ? 25 : 0;
      else s = n === t ? 100 : n.indexOf(t) === 0 ? 80 : n.indexOf(t) > 0 ? 60 : k.indexOf(t) >= 0 ? 35 : 0;
      if (!s) return 0;
      tot += s;
    }
    return tot;
  }
  function addrScore(v, P) {
    if (!P.hex || !v) return 0;
    const s = String(v), sl = s.toLowerCase(), h = P.hex.toLowerCase();
    if (sl === h) return 120;
    if (sl.indexOf(h) === 0) return 90;
    if (P.hex.length >= 6 && sl.indexOf(h) > 0) return 40;
    return 0;
  }
  function mark(text, terms) {
    const t = String(text == null ? '' : text);
    const ws = arr(terms).map(x => String(x || '').trim()).filter(x => x.length >= 1).sort((a, b) => b.length - a.length);
    if (!ws.length) return esc(t);
    const low = t.toLowerCase(), hit = new Uint8Array(t.length);
    ws.forEach(w => { const wl = w.toLowerCase(); let i = low.indexOf(wl); let guard = 0; while (i >= 0 && guard++ < 20) { for (let j = i; j < i + wl.length; j++) hit[j] = 1; i = low.indexOf(wl, i + wl.length); } });
    let o = '', on = false;
    for (let i = 0; i < t.length; i++) { if (hit[i] && !on) { o += '<mark>'; on = true; } else if (!hit[i] && on) { o += '</mark>'; on = false; } o += esc(t[i]); }
    return o + (on ? '</mark>' : '');
  }
  const termsOf = P => (P.type === 'hex' || P.type === 'b58' ? [P.hex] : P.text.split(/\s+/).filter(Boolean));
  function shortMark(addr, P) {
    const s = String(addr || '');
    if (s.length <= 14) return '<span class="pvx">' + mark(s, termsOf(P)) + '</span>';
    const h = P.hex && s.toLowerCase().indexOf(P.hex.toLowerCase()) === 0 ? Math.min(P.hex.length, 10) : 0;
    const head = s.slice(0, Math.max(6, h)), tail = s.slice(-4);
    return '<span class="pvx">' + (h ? '<mark>' + esc(head.slice(0, h)) + '</mark>' + esc(head.slice(h)) : esc(head)) + '…' + esc(tail) + '</span>';
  }
  const pvx = s => '<span class="pvx">' + s + '</span>';
  function locHTML(g) {
    const L = arr(g && g.locList), n = L.length;
    if (!n) return g && g.locSummary && g.locSummary !== '—' ? esc(nameMask(g.locSummary)) : '';
    const ws = L.filter(l => l.wallet).length;
    if (ws === n && n >= 3) return esc('지갑 ') + pvx(n + '곳');
    return L.slice(0, 2).map(l => esc(nameMask(l.w))).join(' · ') + (n > 2 ? ' 외 ' + pvx((n - 2) + '곳') : '');
  }
  function nameMask(s) {
    const t = String(s == null ? '' : s);
    if (!pvOn() || !/\d/.test(t)) return t;
    const a = API(), fake = a ? a.pvW((a.PVM && a.PVM.n) || '8,888') : '•••';
    return t.split(/(0x[0-9a-fA-F]{40}|[A-Za-z0-9]{4,10}…[A-Za-z0-9]{3,6}|[1-9A-HJ-NP-Za-km-z]{32,44})/).map((x, i) => (i % 2 ? x : x.replace(/\d[\d,.]*/g, () => fake))).join('');
  }

  const inRange = (iso, f) => (!f.after || (iso && iso >= f.after)) && (!f.before || (iso && iso.slice(0, 10) <= f.before));
  const cmp = (v, c) => { if (!c || v == null) return true; const x = num(v); return c.op === '<' ? x < c.v : c.op === '<=' ? x <= c.v : c.op === '>' ? x > c.v : c.op === '>=' ? x >= c.v : Math.abs(x - c.v) <= Math.max(1, Math.abs(c.v) * 0.01); };
  function passF(it, P) {
    const f = P.f, pv = pvOn();
    if (f.coin && it.sym && String(it.sym).toUpperCase() !== f.coin) return false;
    if (f.coin && !it.sym && it.kind !== 'setting') return false;
    if (f.chain && it.chains && it.chains.length && it.chains.indexOf(f.chain) < 0) return false;
    if (f.chain && it.chains && !it.chains.length && it.kind !== 'setting') return false;
    if ((f.after || f.before) && it.iso !== undefined && !inRange(it.iso, f)) return false;
    if ((f.after || f.before) && it.iso === undefined && it.kind !== 'setting' && it.kind !== 'coin' && it.kind !== 'wallet' && it.kind !== 'deposit') return false;
    if (f.type) { const ws = TYPE_WORDS[f.type] || [f.type], kk = String(it.evk || '').toLowerCase(); if (!it.evk || !ws.some(w => kk.indexOf(w.toLowerCase()) >= 0)) return false; }
    if (!pv && f.pnl && !cmp(it.pnl, f.pnl)) return false;
    if (!pv && f.pnl && it.pnl == null) return false;
    if (!pv && f.amt && (it.usd == null || !cmp(Math.abs(num(it.usd)), f.amt))) return false;
    return true;
  }

  const tic = (svg, cls) => '<span class="tjs-ic' + (cls ? ' ' + cls : '') + '" aria-hidden="true">' + svg + '</span>';
  function kindIcon(kind, it) {
    const a = API(), IC = (a && a.IC) || {}, T = IC.tab || {};
    if (kind === 'coin' || (kind === 'cycle' && it && it.sym && a)) { try { return '<span class="tjs-cic">' + a.icon(it.sym, 'sm', { chain: it.chainName || '' }) + '</span>'; } catch (e) {  } }
    const m0 = { cycle: T.journal, event: T.journal, tx: IX.hash, outflow: T.outflows, pending: T.unmatched, day: T.daily, review: IX.spark, receipt: IX.rcpt, memo: IX.memo, nft: IX.nft, other: IX.other,
      wallet: IC.wallet, deposit: IC.bank || IC.wallet, setting: IC.gear }[kind];
    return tic(m0 || IX.go);
  }

  function clientItems(P) {
    const a = API();
    if (!a || !a.S || !a.S.D) return [];
    const S = a.S, D = S.D, out = [], T = termsOf(P), toks = P.toks, m = a.m, pv = pvOn();
    const want = k => !P.scope || P.scope === k || (P.scope === 'wallet' && k === 'deposit') || (P.scope === 'tx' && k === 'tx');
    const addrQ = P.type === 'hex' || P.type === 'b58';
    const push = it => { if (it && it.sc > 0 && passF(it, P)) out.push(it); };
    const chainKeys = names => arr(names).map(x => { const s = String(x || '').toLowerCase(); return CHAIN_ALIAS[s] || Object.keys(a.CHAIN_KO).find(k => a.CHAIN_KO[k].toLowerCase() === s) || s; });
    const amtNear = usd => (P.type === 'amt' && !pv && usd != null && num(usd) !== 0 ? (Math.abs(Math.abs(num(usd)) - P.amt) <= Math.max(5, P.amt * 0.1) ? 70 : 0) : 0);
    const textOrNone = (name, extra) => (P.toks.length && P.type !== 'amt' && P.type !== 'date' ? score(name, extra, toks) : 0);
    const onlyFilters = !P.text && (P.chips.length > 0);

    if (want('coin')) arr(D.groups).forEach(g => {
      const cas = arr(g.insts).map(i => i.ca).filter(Boolean);
      let sc = addrQ ? Math.max(0, ...cas.map(c => addrScore(c, P))) : textOrNone(g.sym, arr(g.insts).map(i => String(i.name || '').split(' · ')[0]).join(' '));
      sc = sc || amtNear(g.value) || (onlyFilters ? 10 : 0);
      if (P.type === 'ticker' && sc && norm(g.sym) === norm(P.text)) sc += 50;
      if (sc) sc += Math.min(20, Math.log10(Math.max(1, num(g.value))) * 3);
      const roi = g.roi != null && isFinite(g.roi) ? g.roi : null;
      const cyc9 = arr(D.merged).find(p => arr(p._legs).some(k => arr(g.keys).indexOf(k) >= 0));
      push({ kind: 'coin', id: g.key, sc, sym: g.sym, chains: chainKeys(g.chains), usd: g.value, pnl: g.pnl, chainName: g.chains && g.chains.length === 1 ? g.chains[0] : '',
        title: mark(g.sym, T) + (g.twin ? ' <span class="tjs-mut">' + esc(g.key.indexOf('~') > 0 ? '(다른 시세)' : '') + '</span>' : ''),
        sub: esc(g.chainLabel || '') + (locHTML(g) ? ' · ' + locHTML(g) : '') + (g.unkPct > 0.005 ? ' · ' + pvx('원가 확인 ' + Math.round((1 - g.unkPct) * 100) + '%') : ''),
        rt: rtHTML(m(g.value, { compact: true }), roi == null ? '' : (pv ? '<span class="tjs-mask">•••%</span>' : '<span class="' + (roi >= 0 ? 'up' : 'down') + '">' + esc(a.pctS(roi, 1)) + '</span>')),
        anc: 'coin:' + g.key, tab: 'dash', g,
        alt: cyc9 ? { t: '매매일지 사이클', go: () => goAnc('cycle', cyc9.key, 'journal') } : null });
    });
    if (want('cycle')) arr(D.merged).concat(arr(D.lpCycles)).forEach(p => {
      if (!p || !p.sym) return;
      let sc = textOrNone(p.sym, (p._lp ? 'lp 유동성 ' + (p._lp.protocol || '') : '') + ' ' + (p._st || p.status || ''));
      if (!sc && P.type === 'date' && p._last && p._last.slice(0, 10) >= P.date.from && String(p.opened || '').length >= 5) { const o = a.isoDay(String(p.opened).slice(0, 5)); if (o && o <= P.date.to) sc = 30; }
      sc = sc || (onlyFilters ? 10 : 0);
      const realized = num(p.realized) + num(p.realizedFb);
      const chn = p.chain && p.chain !== '?' ? (a.CHAIN_KO[p.chain] || p.chain) : '거래소';
      push({ kind: 'cycle', id: p.key, sc: sc ? sc + (p._st === '종료' ? 0 : 5) : 0, sym: p.sym, chains: p.chain && p.chain !== '?' ? [p.chain] : [], iso: p._last ? p._last.slice(0, 10) : '', usd: p._heldVal, pnl: realized,
        title: mark(p._lp ? p.sym + ' LP' : p.sym, T) + ' <span class="pill sm ' + (p._st === '종료' ? 'g' : num(p._soldPct) > 0 ? 'w' : 'ok') + '">' + esc(p._st === '종료' ? '종료' : num(p._soldPct) > 0 ? '부분 매도' : '보유') + '</span>',
        sub: esc(chn) + (p.opened && p.opened !== '—' ? ' · ' + esc(String(p.opened).slice(0, 5)) + ' 시작' : '') + (p._nLegs > 1 ? ' · ' + pvx('포지션 ' + p._nLegs + '개') : ''),
        rt: rtHTML(realized ? m(realized, { sign: true, compact: true }) : '—', realized ? '기간 실현' : ''), anc: 'cycle:' + p.key, tab: 'journal' });
    });
    const SPAM_PILL = ' <span class="pill g sm">숨김·스팸</span>';
    if (want('outflow') || (addrQ && want('tx'))) arr(D.of).forEach(r => {
      const nm = r.alias || '';
      const spamR = r.bucket === 'spam' || !!r.dustPoison;
      let sc = addrQ ? addrScore(r.address, P) : textOrNone(nm || r.address, [r.memo, r.exchange, arr(r.tokens).map(t => t.sym).join(' '), arr(r.chainNames).join(' '), r.category].join(' '));
      sc = sc || amtNear(r.usdAtSend) || (onlyFilters ? 10 : 0);
      const iso = r.lastTs ? isoOfD(new Date(num(r.lastTs) * 1000 + KST)) : '';
      if (want('outflow')) push({ kind: 'outflow', id: r.address, sc, addr: r.address, chains: arr(r.chains), iso, usd: r.usdAtSend, sym: arr(r.tokens)[0] ? arr(r.tokens)[0].sym : '', spam: spamR,
        title: (r.special ? esc('여러 주소') : nm ? mark(nameMask(nm), T) + ' <span class="tjs-mono tjs-mut">' + shortMark(r.address, P) + '</span>' : '<span class="tjs-mono">' + shortMark(r.address, P) + '</span>')
          + (spamR ? (r.dustPoison ? ' <span class="pill g sm">주소 오염 의심</span>' : SPAM_PILL) : r.bucket === 'own' ? ' <span class="pill ok sm">내 지갑</span>' : r.bucket === 'exchange' ? ' <span class="pill a sm">거래소 입금</span>' : r.bucket === 'pending' ? ' <span class="pill w sm">확인 필요</span>' : ''),
        sub: esc(arr(r.chainNames).slice(0, 3).join(' · ')) + ' · ' + pvx(num(r.count) + '건'),
        rt: rtHTML(r.sendKnown && r.usdAtSend ? m(r.usdAtSend, { compact: true }) : '—', r.netUsd != null && num(r.netUsd) > 0.5 ? '순유출 ' + m(num(r.netUsd), { compact: true }) : ''),
        anc: 'outflow:' + r.address, tab: 'outflows', of: r, acts: spamR ? (addrActs(r.address, arr(r.chains)[0], true) || []).filter(x => !x.copy) : addrActs(r.address, arr(r.chains)[0], true) });
      if (addrQ && want('tx')) arr(r.txs).forEach(t => {
        const s9 = addrScore(t && t.tx, P); if (!s9) return;
        const tiso = t.ts ? isoOfD(new Date(num(t.ts) * 1000 + KST)) : '';
        const spamT = spamR || !!(t && t.phantom);
        push({ kind: 'tx', id: 'of|' + t.tx, sc: s9, tx: t.tx, chains: t.chain ? [t.chain] : [], iso: tiso, usd: t.usd, sym: t.sym, evk: '전송', spam: spamT,
          title: '<span class="tjs-mono">tx ' + shortMark(t.tx, P) + '</span>' + (spamT ? (t && t.phantom ? ' <span class="pill g sm">가짜 전송</span>' : SPAM_PILL) : ''), sub: esc((tiso ? tiso.slice(5) + ' · ' : '') + '보낸 전송 ' + (t.sym || '') + (t.chain ? ' · ' + (a.CHAIN_KO[t.chain] || t.chain) : '') + ' → ') + '<span class="tjs-mono">' + esc(a.short(r.address)) + '</span>',
          rt: rtHTML(t.usd != null ? m(num(t.usd), { compact: true }) : '', ''), anc: 'outflow:' + r.address, tab: 'outflows', acts: txActs(t.tx, t.chain) });
      });
    });
    const evs = arr(D.events);
    if (want('event') || want('tx')) {
      const lim = addrQ ? evs.length : 4000;
      for (let i = 0; i < evs.length && i < lim; i++) {
        const e = evs[i];
        const iso = e.iso ? String(e.iso).slice(0, 10) : '';
        let sc = 0, kind = 'event';
        if (addrQ) { sc = addrScore(e.tx, P); kind = 'tx'; }
        else if (P.type === 'date') sc = iso >= P.date.from && iso <= P.date.to ? 20 : 0;
        else if (P.toks.length && P.type !== 'amt') sc = score(e.sym, (e.k || '') + ' ' + (e.d || ''), toks) * 0.6;
        else if (P.type === 'amt') sc = 0;
        else if (onlyFilters) sc = 8;
        if (!sc) continue;
        if ((kind === 'tx' && !want('tx')) || (kind === 'event' && !want('event'))) continue;
        const sr9 = String(e.src || ''), ch9 = sr9.indexOf('w:') === 0 ? (CHAIN_ALIAS[sr9.slice(2).toLowerCase()] || sr9.slice(2).toLowerCase()) : '';
        const fullTx = typeof e.tx === 'string' && e.tx && e.tx !== '—' && e.tx.indexOf('…') < 0;
        push({ kind, id: (e.src || '') + '|' + (e.tx || '') + '|' + e.t + '|' + (e.sym || '') + '|' + (e.k || ''), sc, tx: e.tx, sym: e.sym, iso, evk: e.k, usd: null, chains: ch9 ? [ch9] : [],
          title: (kind === 'tx' ? '<span class="tjs-mono">tx ' + shortMark(e.tx, P) + '</span> ' : '') + '<span class="tjs-kb">' + esc(e.k || '') + '</span> ' + mark(e.sym || '', T),
          sub: esc(String(e.t || '')) + (e.d ? ' · ' + esc(String(e.d).slice(0, 60)) : ''), rt: rtHTML(a.evA(e) || '', ''),
          anc: 'evday:' + iso, tab: 'journal', acts: fullTx && ch9 ? txActs(e.tx, ch9) : null });
      }
    }
    if (P.type === 'date' || (P.f.after && P.f.before && P.f.after === P.f.before)) {
      const dr = P.date || { from: P.f.after, to: P.f.before };
      const days = []; for (let d = dr.from, n = 0; d <= dr.to && n < 62; d = addDays(d, 1), n++) days.push(d);
      if (want('day')) days.slice().reverse().forEach(iso => {
        const k = a.dayKeyOf ? a.dayKeyOf(iso) : iso.slice(5), inWin = !!k;
        const rz = inWin ? (D.realized || {})[k] : undefined, rv = inWin ? (D.reviews || {})[k] : null;
        let c = inWin && a.dayCnt ? a.dayCnt(k, true) : null;
        if (!c && inWin) { const es = evs.filter(e => String(e.iso || '').slice(0, 10) === iso); c = { n: es.length, b: es.filter(e => /매수/.test(e.k)).length, s: es.filter(e => /매도/.test(e.k)).length, dep: es.filter(e => /입금/.test(e.k)).length }; }
        if (iso > todayIso()) return;
        if (inWin && !c && rz == null && !rv && days.length > 1) return;
        if (inWin && c && !c.n && rz == null && !rv && days.length > 1) return;
        if (!inWin && days.length > 1 && !evs.some(e => String(e.iso || '').slice(0, 10) === iso)) return;
        push({ kind: 'day', id: iso, sc: 100, iso, usd: rz,
          title: '<mark>' + esc((+iso.slice(5, 7)) + '월 ' + (+iso.slice(8)) + '일') + '</mark> <span class="tjs-mut">(' + dowOf(iso) + ')</span>',
          sub: inWin ? pvx([c && c.s ? '매도 ' + c.s : '', c && c.b ? '매수 ' + c.b : '', c && c.dep ? '입금 ' + c.dep : '', c && c.n ? '기록 ' + c.n + '건' : '기록 없음'].filter(Boolean).join(' · ')) + (rv ? ' · AI 리뷰 있음' : '') : '최근 12개월 밖 — 매매일지 전체 기록에서 그날',
          rt: rtHTML(rz != null ? m(num(rz), { sign: true, compact: true }) : '—', rz != null ? '그날 실현' : inWin ? '' : '1년 전 · 전체 기록'),
          anc: inWin ? 'day:' + k : 'evday:' + iso, tab: inWin ? 'daily' : 'journal', dayK: inWin ? k : '' });
      });
      if (want('receipt') && a.dayContrib && days.length <= 7) days.forEach(iso => {
        let rows = []; try { rows = a.dayContrib(iso) || []; } catch (e) { rows = []; }
        rows.filter(x => a.rcptable(x) && Math.abs(num(x.v)) >= 1).sort((x, y) => num(y.v) - num(x.v)).slice(0, 6).forEach((x, i) => push({ kind: 'receipt', id: iso + '|' + x.sym, sc: 90 - i, iso, sym: x.sym, usd: x.v, pnl: x.v,
          title: mark(x.sym, T) + (i === 0 && num(x.v) > 0 ? ' <span class="pill a sm">실현 1위</span>' : ''), sub: esc(iso.slice(5)) + ' · 그날 차익 영수증',
          rt: rtHTML(m(num(x.v), { sign: true, compact: true }), ''), go: () => closeKeep(() => a.openReceipt(iso, x.sym, i + 1)) }));
      });
    }
    if (want('review') && P.type !== 'amt' && !addrQ) {
      const R = D.reviews || {};
      Object.keys(R).forEach(k => {
        const rv = R[k]; if (!rv || typeof rv !== 'object') return;
        const iso = rv.iso ? String(rv.iso).slice(0, 10) : (a.isoDay(k) || '');
        const body = [rv.sum, rv.note, arr(rv.obs).join(' '), rv.next].filter(Boolean).join(' ');
        let sc = 0;
        if (P.type === 'date') sc = iso >= P.date.from && iso <= P.date.to ? 60 : 0;
        else if (P.toks.length) sc = score('', body, toks) * 0.8;
        if (!sc) return;
        const rk9 = iso && a.dayKeyOf ? a.dayKeyOf(iso) : (iso ? iso.slice(5) : k);
        push({ kind: 'review', id: 'd|' + iso, sc, iso, title: esc((+iso.slice(5, 7)) + '월 ' + (+iso.slice(8)) + '일 리뷰') + (rv.s ? ' <span class="pill sm ' + (/양호|좋/.test(rv.s) ? 'ok' : /주의|나쁨|손실/.test(rv.s) ? 'w' : 'g') + '">' + esc(rv.s) + '</span>' : ''),
          sub: pv ? '본문은 가리기 중이라 숨겨요' : snippet(body, P), rt: '', anc: rk9 ? 'day:' + rk9 : 'evday:' + iso, tab: rk9 ? 'daily' : 'journal', dayK: rk9 || '' });
      });
      const W = D.revWk || {};
      Object.keys(W).forEach(k => {
        const rv = W[k]; if (!rv || typeof rv !== 'object') return;
        const body = [rv.sum, rv.note, arr(rv.patterns || rv.obs).map(x => (typeof x === 'string' ? x : (x && (x.t || x.text)) || '')).join(' '), rv.rule, rv.next].filter(Boolean).join(' ');
        let sc = 0, from = String(rv.from || ''), to = String(rv.to || '');
        if (P.type === 'date') sc = from && to && !(to < P.date.from || from > P.date.to) ? 55 : 0;
        else if (P.toks.length) sc = score('주간 리뷰 ' + k, body, toks) * 0.75;
        if (!sc) return;
        push({ kind: 'review', id: 'w|' + k, sc, iso: to || from, title: esc('주간 리뷰 ' + (from ? (+from.slice(5, 7)) + '/' + (+from.slice(8)) + '–' + (+to.slice(5, 7)) + '/' + (+to.slice(8)) : k)) + (rv.s ? ' <span class="pill ok sm">' + esc(rv.s) + '</span>' : ''),
          sub: pv ? '본문은 가리기 중이라 숨겨요' : snippet(body, P), rt: '', anc: to && a.dayKeyOf && a.dayKeyOf(to) ? 'day:' + a.dayKeyOf(to) : to ? 'evday:' + to : '', tab: 'daily', dayK: to && a.dayKeyOf ? a.dayKeyOf(to) || '' : '',
          go: weekGo(k, rv) });
      });
    }
    if (want('pending')) arr(D.pendings).forEach(p => {
      if (!p || p.hide) return;
      let sc = addrQ ? Math.max(addrScore(p.to, P), addrScore(p.tx, P)) : textOrNone(p.sym, [p.kind, p.chain, p.ex, p._cat].join(' '));
      sc = sc || amtNear(p.usd) || (onlyFilters ? 10 : 0);
      const iso = p.t ? (a.isoOf(String(p.t)) || '').slice(0, 10) : '';
      push({ kind: 'pending', id: p.key, sc, sym: p.sym, iso, usd: p.usd, chains: p.chain ? [String(p.chain).toLowerCase()] : [], addr: p.to, tx: p.tx,
        title: mark(p.sym || '?', T) + ' ' + esc(p.kind || '미매칭'), sub: esc([p.ex || (p.chain ? a.CHAIN_KO[p.chain] || p.chain : ''), String(p.t || '').slice(0, 5)].filter(Boolean).join(' · ')),
        rt: rtHTML(p.usd != null ? m(num(p.usd), { compact: true }) : '', ''), anc: 'pending:' + p.key, tab: 'unmatched' });
    });
    const N = S.nft && S.nft.d;
    if (want('nft') && N && P.type !== 'amt' && P.type !== 'date') {
      const seen = new Set();
      [['tracked', '추적 중'], ['watch', '지켜보는 중'], ['candidates', '후보']].forEach(([k, lab]) => arr(N[k]).forEach(r => {
        if (!r || !r.key || seen.has(r.key)) return; seen.add(r.key);
        const sc = addrQ ? addrScore(r.ca || r.contract || r.addr, P) : textOrNone(r.name || r.sym || '', (r.sym || '') + ' ' + (r.chain || ''));
        push({ kind: 'nft', id: r.key, sc: sc ? sc + (k === 'tracked' ? 5 : 0) : 0, sym: r.sym, chains: r.chain ? [String(r.chain).toLowerCase()] : [], usd: r.value && r.value.usd,
          title: mark(r.name || r.sym || r.key, T), sub: esc([r.chain ? (a.CHAIN_KO[r.chain] || r.chain) : '', lab].filter(Boolean).join(' · ')) + (r.count ? ' · ' + (pv ? a.pvW((a.PVM && a.PVM.q) || '8,888') + '개' : pvx(num(r.count) + '개')) : ''),
          rt: k === 'candidates' ? '<span class="pill g sm">후보</span>' : '<span class="pill ok sm">추적</span>', anc: 'nft:' + r.key, tab: 'other' });
      }));
    }
    const OA = S.oa && S.oa.d;
    if (want('other') && OA && !addrQ && P.type !== 'date') arr(OA.items).forEach(o => {
      if (!o) return;
      let sc = textOrNone(o.name || '', [o.ticker, o.cat, o.code].join(' ')) || (onlyFilters ? 10 : 0);
      if (!sc) return;
      const usd = o.cur === 'KRW' ? num(o.value) / (num(D.rate) || 1384) : num(o.value);
      const nm9 = a.oaNameTxt ? a.oaNameTxt(o) : (pv ? String(o.name || '').replace(/\d[\d,.]*/g, () => a.pvW(a.PVM.n || '8,888')) : String(o.name || ''));
      push({ kind: 'other', id: o.id, sc, usd, title: mark(nm9 || '(이름 없음)', T) + (o.liab ? ' <span class="pill w sm">부채</span>' : ''), sub: esc([o.cat, pv ? '' : o.ticker].filter(Boolean).join(' · ')),
        rt: rtHTML(o.value != null ? m(o.liab ? -usd : usd, { compact: true }) : '', ''), anc: 'other:' + o.id, tab: 'other' });
    });
    if (want('wallet') && a.sxWalRows) { let rows = []; try { rows = a.sxWalRows(); } catch (e) { rows = []; }
      rows.forEach(r => {
        const addr = r.w ? r.w.addr : r.s && r.s.address, chains = r.w ? String(r.w.chains || '') : arr(r.s && r.s.chains).join(' ');
        const sc = addrQ ? addrScore(addr, P) : textOrNone(r.alias || '', chains + ' 지갑');
        push({ kind: 'wallet', id: r.k, sc, addr, chains: chainKeys(String(chains).split(/\s*[,·/]\s*/)),
          title: mark(nameMask(r.alias) || '(이름 없음)', T) + ' <span class="tjs-mono tjs-mut">' + shortMark(addr, P) + '</span>', sub: esc((r.s && r.s.kind === 'sol') || !/^0x/i.test(String(addr)) ? 'Solana 지갑' : 'EVM 지갑') + ' · 설정 › 지갑 · 주소',
          rt: r.wait ? '<span class="pill g sm">수집 대기</span>' : '', go: () => closeKeep(() => a.sxGo('wallets', '', { pre: () => { S.set.walAll = true; S.set.walOpen = r.k; S.set.walQ = ''; }, hl: '.sx-wr.open' })),
          acts: addrActs(addr, '', false) });
      });
    }
    if (want('deposit')) arr(D.deposits).forEach(d0 => {
      const sc = addrQ ? addrScore(d0.addr, P) : textOrNone((d0.ex || '') + ' ' + (d0.net || ''), (d0.memo || '') + ' 입금 주소');
      push({ kind: 'deposit', id: (d0.ex || '') + '|' + (d0.net || '') + '|' + d0.addr, sc, addr: d0.addr, title: mark((d0.ex || '') + ' · ' + (d0.net || ''), T) + ' <span class="tjs-mono tjs-mut">' + shortMark(d0.addr, P) + '</span>',
        sub: '거래소 입금 주소 · 설정 › 지갑 · 주소 › 입금 주소', rt: '', go: () => closeKeep(() => a.sxGo('wallets', 'deposits', { hl: '' })), acts: addrActs(d0.addr, '', false) });
    });
    if (want('setting') && P.text && !addrQ && P.type !== 'amt' && a.Finder && a.sxIndex) {
      let es = []; try { es = a.Finder.find(a.sxIndex(), P.text, P.scope === 'setting' ? 30 : 6); } catch (e) { es = []; }
      es.forEach((e, i) => push({ kind: 'setting', id: e.s + '/' + e.sub + '/' + e.t, sc: 60 - i, title: mark(e.t, T), sub: esc('설정 › ' + e.path), rt: '',
        go: () => closeKeep(() => a.sxGo(e.s, e.sub, { pre: e.pre, hl: e.sel })) }));
    }
    return out;
  }
  function weekGo(k, rv) {
    const a = API();
    if (!a || !rv) return null;
    const m9 = /^(\d{4}-W\d{2})[ab]?$/.exec(String(k || ''));
    const f = String(rv.from || ''), t = String(rv.to || '');
    if (!m9 || !/^\d{4}-\d{2}-\d{2}$/.test(f)) return null;
    const t9 = /^\d{4}-\d{2}-\d{2}$/.test(t) ? t : addDays(f, 6);
    const dk = a.dayKeyOf ? a.dayKeyOf(t9 > todayIso() ? todayIso() : t9) : null;
    if (!dk) return null;
    const wd = (new Date(Date.parse(f + 'T00:00:00Z')).getUTCDay() + 6) % 7, mon = addDays(f, -wd);
    return () => closeKeep(() => { const S = a.S; S.day = dk; S.calYM = (a.ymOf && a.ymOf(dk)) || S.calYM; S.wkSel = { wk: m9[1], from: mon, f, t: t9, day: dk }; S.wkMore = null; a.goTab('daily'); });
  }
  function snippet(body, P) {
    const b = String(body || '').replace(/\s+/g, ' ');
    const w = P.text.split(/\s+/).filter(Boolean)[0] || '';
    let i = w ? b.toLowerCase().indexOf(w.toLowerCase()) : -1;
    if (i < 0) return esc(b.slice(0, 70)) + (b.length > 70 ? '…' : '');
    const s0 = Math.max(0, i - 24);
    return (s0 ? '…' : '') + mark(b.slice(s0, s0 + 76), [w]) + (s0 + 76 < b.length ? '…' : '');
  }
  const rtHTML = (a, b) => '<div class="tjs-rt"><b>' + (a || '') + '</b>' + (b ? '<span>' + b + '</span>' : '') + '</div>';
  function addrActs(addr, chain, of) {
    const a = API(); if (!a || !addr) return null;
    const ch = chain || (String(addr).indexOf('0x') === 0 ? 'eth' : 'sol');
    const acts = [];
    if (!of && (a.S.D && arr(a.S.D.of).some(r => r.address === addr))) acts.push({ t: '보낸 내역에서 열기', go: () => goAnc('outflow', addr, 'outflows') });
    acts.push({ t: '탐색기에서 보기', ext: a.exUrl(ch, addr, true) });
    acts.push({ t: '주소 복사', copy: addr });
    acts.push({ t: '이름 붙이기', sub: '설정 › 지갑 · 주소', go: () => closeKeep(() => a.sxGo('wallets', 'names', { hl: '' })) });
    return acts;
  }
  function txActs(tx, chain) {
    const a = API(); if (!a || typeof tx !== 'string' || !tx || tx === '—' || tx.indexOf('…') >= 0) return null;
    const ch = chain || (String(tx).indexOf('0x') === 0 ? 'eth' : 'sol');
    return [{ t: '탐색기에서 tx 보기', ext: a.exUrl(ch, tx, false) }, { t: '해시 복사', copy: tx }];
  }

  function serverItems(P) {
    const R = ST.srv, a = API();
    if (!R || ST.srvQ !== P.raw || !a || locked() || ST.srvPv !== pvOn()) return [];
    const out = [], T = termsOf(P), m = a.m;
    arr(R.groups).forEach(g => arr(g.items).forEach((x, i) => {
      if (!x || typeof x !== 'object') return;
      const kind = KL[x.kind] ? x.kind : (KL[g.kind] ? g.kind : 'event');
      if (P.scope && P.scope !== kind && !(P.scope === 'wallet' && kind === 'deposit')) return;
      const anc = String(x.anc || '');
      const pv9 = pvOn(), numMask = s9 => String(s9 || '').replace(/\d[\d,.]*/g, () => a.pvW((a.PVM && a.PVM.n) || '8,888'));
      const ttl9 = pv9 && (kind === 'other' || kind === 'wallet' || kind === 'outflow' || kind === 'deposit') ? nameMask(x.title) : String(x.title || '');
      const title = x.tx ? '<span class="tjs-mono">tx ' + shortMark(x.tx, P) + '</span>' + (ttl9 ? ' ' + mark(ttl9, T) : '') : x.addr && !ttl9 ? '<span class="tjs-mono">' + shortMark(x.addr, P) + '</span>' : mark(ttl9, T);
      const bodyKind = kind === 'memo' || kind === 'review';
      const it = { kind, id: String(x.id != null ? x.id : (x.tx || x.addr || i)), sc: 50 - i * 0.01 + num(x.score) * 0.01, srv: true, sym: x.sym, iso: x.date ? String(x.date).slice(0, 10) : '', usd: x.usd, tx: x.tx, addr: x.addr,
        chains: x.chain ? [String(x.chain).toLowerCase()] : [], spam: !!x.spam,
        title: title + (x.spam ? ' <span class="pill g sm">숨김·스팸</span>' : ''),
        sub: pv9 && bodyKind ? '본문은 가리기 중이라 숨겨요' : typeof x.hl === 'string' && x.hl && !pv9 ? hlSafe(x.hl) : esc(pv9 && kind === 'other' ? numMask(x.sub) : (x.sub || '')),
        rt: rtHTML(x.usd != null && isFinite(+x.usd) ? m(num(x.usd), { compact: true }) : '', ''), anc, tab: TABK[kind] || '' };
      if ((kind === 'memo' || kind === 'review') && /^\d{4}-\d{2}-\d{2}/.test(String(x.date || '')) && !/^rw:/.test(String(x.id || ''))) {
        const d9 = String(x.date).slice(0, 10), k9 = a.dayKeyOf ? a.dayKeyOf(d9) : null;
        it.anc = k9 ? 'day:' + k9 : 'evday:' + d9; it.tab = k9 ? 'daily' : 'journal';
      }
      if (kind === 'review' && /^rw:/.test(String(x.id || ''))) { const wk9 = String(x.id).slice(3), rvw = a.S.D && a.S.D.revWk ? a.S.D.revWk[wk9] : null, g9 = weekGo(wk9, rvw); if (g9) it.go = g9; }
      if (kind === 'wallet' && !anc) it.go = () => closeKeep(() => { let k9 = ''; try { const rw = a.sxWalRows(); const hit = rw.find(r9 => String((r9.w ? r9.w.addr : r9.s && r9.s.address) || r9.k).toLowerCase() === String(x.addr || '').toLowerCase()); k9 = hit ? hit.k : ''; } catch (e) { k9 = ''; }
        a.sxGo('wallets', '', { pre: () => { a.S.set.walAll = true; a.S.set.walOpen = k9; a.S.set.walQ = ''; }, hl: k9 ? '.sx-wr.open' : '' }); });
      if (kind === 'deposit' && !anc) it.go = () => closeKeep(() => a.sxGo('wallets', 'deposits', { hl: '' }));
      if (x.tx) it.acts = txActs(x.tx, x.chain);
      else if (x.addr) it.acts = addrActs(x.addr, x.chain, kind === 'outflow');
      if (it.spam && it.acts) it.acts = it.acts.filter(y => !y.copy);
      out.push(it);
    }));
    return out;
  }
  function hlSafe(s) { return String(s || '').split(/(<mark>|<\/mark>)/).map(p => (p === '<mark>' || p === '</mark>' ? p : esc(p))).join(''); }

  function canonKey(it) {
    const id = String(it.id == null ? '' : it.id), low = s => String(s || '').toLowerCase(), strip = (s, p) => (s.indexOf(p) === 0 ? s.slice(p.length) : s);
    switch (it.kind) {
      case 'tx': return 'tx|' + low(it.tx || strip(id, 'tx:'));
      case 'coin': return 'coin|' + (it.srv ? strip(id, 'coin:').toUpperCase() : id);
      case 'outflow': return 'of|' + low(it.addr || strip(id, 'of:'));
      case 'wallet': return 'w|' + low(it.addr || strip(id, 'w:'));
      case 'deposit': return 'dep|' + low(it.addr || id);
      case 'other': return 'oa|' + strip(id, 'oa:');
      case 'nft': return 'nft|' + strip(id, 'nft:');
      case 'review': return id.indexOf('d|') === 0 ? 'rv|' + id.slice(2) : id.indexOf('w|') === 0 ? 'rw|' + id.slice(2) : id.indexOf('rv:') === 0 ? 'rv|' + id.slice(3) : id.indexOf('rw:') === 0 ? 'rw|' + id.slice(3) : 'review|' + id;
      case 'event': return typeof it.tx === 'string' && it.tx ? 'ev|' + low(it.tx) + '|' + low(it.sym) : 'event|' + id;
      default: return it.kind + '|' + id;
    }
  }
  function mergeItems(cli, srv) {
    const by = new Map(), out = [];
    const keyOf = canonKey;
    cli.forEach(it => { const k = keyOf(it); if (!by.has(k)) { by.set(k, it); out.push(it); } else if (by.get(k).sc < it.sc) by.get(k).sc = it.sc; });
    const txs = new Map();
    cli.forEach(x => { if (typeof x.tx === 'string' && x.tx) { const k9 = x.tx.toLowerCase(); if (!txs.has(k9)) txs.set(k9, []); txs.get(k9).push(x); } });
    const markSpam = c => { if (!c.spam) { c.spam = true; if (typeof c.title === 'string' && c.title.indexOf('숨김·스팸') < 0) c.title += ' <span class="pill g sm">숨김·스팸</span>'; }
      if (c.acts) c.acts = c.acts.filter(y => !y.copy); };
    srv.forEach(it => {
      if (typeof it.tx === 'string' && it.tx && txs.has(it.tx.toLowerCase()) && (it.kind === 'tx' || it.kind === 'event')) { if (it.spam) txs.get(it.tx.toLowerCase()).forEach(markSpam); return; }
      const k = keyOf(it);
      if (by.has(k)) { const c = by.get(k); c.sc = Math.max(c.sc, it.sc); if (!c.srv) c.both = true;
        if (it.spam) markSpam(c);
        return; }
      by.set(k, it); out.push(it);
    });
    return out;
  }
  function groupOf(items, P) {
    const g = new Map();
    items.forEach(it => { if (!g.has(it.kind)) g.set(it.kind, []); g.get(it.kind).push(it); });
    const lead = P.type === 'hex' || P.type === 'b58' ? ['outflow', 'tx', 'wallet', 'deposit', 'pending', 'coin'] : P.type === 'date' ? ['day', 'receipt', 'review', 'event'] : P.type === 'amt' ? ['coin', 'outflow', 'pending', 'other'] : [];
    const ord = k => (lead.indexOf(k) >= 0 ? lead.indexOf(k) - 100 : KORD[k]);
    const best = k => Math.max(...g.get(k).map(x => x.sc));
    const ks = Array.from(g.keys()).sort((x, y) => (lead.length ? ord(x) - ord(y) : 0) || best(y) - best(x) || KORD[x] - KORD[y]);
    return ks.map(k => ({ kind: k, items: g.get(k).sort((x, y) => (x.spam ? 1 : 0) - (y.spam ? 1 : 0) || y.sc - x.sc || String(y.iso || '').localeCompare(String(x.iso || ''))) }));
  }

  const ASK_KEYS = ['coin', 'chain', 'type', 'after', 'before', 'pnl', 'amt'];
  const ASK_CACHE = new Map();
  function looksAsk(q) {
    const s = String(q || '').trim();
    if (!s || FILT_RE.test(s)) { FILT_RE.lastIndex = 0; return false; }
    FILT_RE.lastIndex = 0;
    if (/[?？]$/.test(s) && s.length >= 4) return true;
    const w = s.split(/\s+/).filter(Boolean);
    return w.length >= 3 && /[가-힣]/.test(s) && /(에서|에게|으로|부터|까지|에|을|를|은|는|이|가|로|의|한|본|된|산|판|던|었|았|거래|때|만|보여|찾아|알려|얼마|몇|언제|어디|무엇|뭐)(\s|$|[?.!])/.test(s);
  }
  const askVal = (k, v) => {
    if (v == null || v === '') return '';
    if (typeof v === 'object') return v.op != null && v.v != null ? String(v.op) + String(v.v) : '';
    if (typeof v === 'number') return (k === 'pnl' || k === 'amt') ? '=' + v : String(v);
    return String(v).replace(/\s+/g, '');
  };
  function askChips(A) {
    const f = A && A.filters || {}, on = k => !A.off.has(k) && askVal(k, f[k]);
    const out = [];
    const d = ['after', 'before'].filter(on); if (d.length) out.push({ keys: d, t: d.map(k => k + ':' + askVal(k, f[k])).join(' '), lab: '날짜 조건' });
    if (on('coin')) out.push({ keys: ['coin'], t: 'coin:' + askVal('coin', f.coin), lab: '코인 조건' });
    if (on('chain')) out.push({ keys: ['chain'], t: 'chain:' + askVal('chain', f.chain), lab: '체인 조건' });
    const tp = ['type', 'pnl'].filter(on); if (tp.length) out.push({ keys: tp, t: tp.map(k => k + ':' + askVal(k, f[k])).join(' '), lab: tp.indexOf('pnl') >= 0 ? '손익 조건' : '종류 조건' });
    if (on('amt')) out.push({ keys: ['amt'], t: 'amt:' + askVal('amt', f.amt), lab: '금액 조건' });
    return out;
  }
  function effQ() {
    const A = ST.ask;
    if (!A || A.q !== ST.q) return ST.q;
    const parts = askChips(A).map(c => c.t);
    const rest = String(A.text || '').trim();
    return (parts.join(' ') + (rest ? ' ' + rest : '')).trim() || ST.q;
  }
  function askKick() {
    clearTimeout(ST.askTmr);
    const q0 = ST.q.trim();
    const fn = window.TJ && typeof window.TJ.askParse === 'function' ? window.TJ.askParse : null;
    if (!fn || !looksAsk(q0)) { if (ST.askBusy) { ST.askBusy = ''; paintMeta(); } return; }
    if (ST.ask && ST.ask.q === ST.q) return;
    if (ASK_CACHE.has(q0)) { askApply(q0, ASK_CACHE.get(q0)); return; }
    ST.askTmr = setTimeout(() => {
      ST.askBusy = q0; paintMeta(); paintHead();
      let p = null;
      const a9 = API(), qs9 = pvOn() && a9 && typeof a9.pvStripAmt === 'function' ? a9.pvStripAmt(q0) : q0;
      try { p = Promise.resolve(fn(qs9)); } catch (e) { p = Promise.resolve(null); }
      p.then(r => { const ok = r && r.ok && r.filters && typeof r.filters === 'object' ? r : null; if (ASK_CACHE.size > 30) ASK_CACHE.clear(); ASK_CACHE.set(q0, ok); askApply(q0, ok); },
        () => { ASK_CACHE.set(q0, null); askApply(q0, null); });
    }, 350);
  }
  function askApply(q0, r) {
    if (ST.askBusy === q0) ST.askBusy = '';
    if (ST.q.trim() !== q0) return;
    ST.ask = r && ASK_KEYS.some(k => askVal(k, r.filters[k])) ? { q: ST.q, filters: r.filters, text: String(r.text || ''), via: String(r.via || ''), echo: String(r.echo || ''), off: new Set() } : null;
    ST.sel = 0;
    run(); srvKick(); paintBody(); paintHead();
  }

  function run() {
    pvGuard();
    const prevSig = ST.selSig, prevKey = ST.flat && ST.flat[ST.sel] ? canonKey(ST.flat[ST.sel]) : '';
    const P = parseQ(effQ());
    ST.P = P;
    if (!P.raw.trim() || locked()) { ST.groups = []; ST.flat = []; ST.items = []; ST.selSig = ''; return; }
    const a = API();
    if (a) { try { a.nftLoad(false); } catch (e) {  } try { a.oaNeed(300000); } catch (e) {  } }
    const scope = ST.scope !== 'all' ? ST.scope : P.scope;
    const P2 = Object.assign({}, P, { scope });
    let items = mergeItems(clientItems(P2), serverItems(P2));
    ST.items = items;
    ST.groups = groupOf(items, P2);
    ST.flat = [];
    ST.groups.forEach(gr => { const lim = scope || ST.expand === gr.kind ? GROUP_ALL : GROUP_N; gr.shown = gr.items.slice(0, lim); gr.more = gr.items.length > lim; gr.shown.forEach(it => ST.flat.push(it)); });
    const sig = effQ() + '|' + scope + '|' + (ST.expand || '');
    if (prevKey && prevSig === sig) { const j = ST.flat.findIndex(it => canonKey(it) === prevKey); if (j >= 0) ST.sel = j; }
    ST.selSig = sig;
    if (ST.sel >= ST.flat.length) ST.sel = Math.max(0, ST.flat.length - 1);
  }
  const SRV_TYPE = { swap: 'swap', buy: 'buy', sell: 'sell', deposit: 'deposit', withdraw: 'withdraw', lp: 'lp', fee: 'gas', gas: 'gas', send: 'transfer', transfer: 'transfer' };
  const SRV_KINDS = { coin: 'coin', cycle: 'event', event: 'event', tx: 'tx', outflow: 'outflow', pending: 'event', review: 'review', memo: 'memo', nft: 'nft', other: 'other', wallet: 'wallet,deposit', deposit: 'deposit', day: 'event,review,memo' };
  const cmpTxt = c => (c && c.v != null ? (c.op || '=') + String(Math.round(c.v * 100) / 100) : '');
  function srvParamsOf(q, scope) {
    const P = parseQ(String(q || ''));
    const pv = pvOn(), f = P.f, out = [];
    if (f.coin) out.push('coin:' + f.coin);
    if (f.chain) out.push('chain:' + f.chain);
    if (f.type && SRV_TYPE[f.type]) out.push('type:' + SRV_TYPE[f.type]);
    if (f.after) out.push('after:' + f.after);
    if (f.before) out.push('before:' + f.before);
    if (!pv && f.pnl) out.push('pnl:' + cmpTxt(f.pnl));
    if (!pv && f.amt) out.push('amt:' + cmpTxt(f.amt));
    let text = P.text;
    if (pv) { const a9 = API(); text = a9 && typeof a9.pvStripAmt === 'function' ? a9.pvStripAmt(text) : text.replace(/(^|\s)[₩$]?\s?\d[\d,]*(?:\.\d+)?\s?(?:만|억|천|k|m)?원?(?=\s|$)/gi, (all, sp) => (/^\s*\d{1,2}$/.test(all) ? all : sp)).replace(/\s{2,}/g, ' ').trim(); }
    const sc = scope && scope !== 'all' ? scope : P.scope;
    const skip = sc === 'setting' || sc === 'receipt' || (!text && !out.length);
    return { q: (out.join(' ') + (text ? ' ' + text : '')).trim().slice(0, Q_MAX), kinds: sc ? (SRV_KINDS[sc] || '') : '', skip };
  }
  const srvQueryOf = q => srvParamsOf(q).q;
  function srvKick() {
    clearTimeout(ST.tmr);
    const raw = srvParamsOf(effQ(), ST.scope).q;
    if (!raw || raw.length < 2) { if (ST.ctl) { try { ST.ctl.abort(); } catch (e) {  } } ST.srvBusy = false; return; }
    ST.tmr = setTimeout(() => {
      if (ST.ctl) { try { ST.ctl.abort(); } catch (e) {  } }
      const ctl = typeof AbortController === 'function' ? new AbortController() : null;
      ST.ctl = ctl; ST.srvBusy = true; ST.srvErr = '';
      const q0 = effQ(), sp = srvParamsOf(q0, ST.scope), pv0 = pvOn();
      if (!sp.q || sp.skip || locked()) { ST.srvBusy = false; return; }
      paintMeta();
      fetch('/api/search?q=' + encodeURIComponent(sp.q) + (sp.kinds ? '&kinds=' + encodeURIComponent(sp.kinds) : '') + '&limit=30', { cache: 'no-store', credentials: 'same-origin', signal: ctl ? ctl.signal : undefined })
        .then(r => (r.ok ? r.json() : Promise.reject(new Error(r.status === 404 ? 'none' : 'HTTP ' + r.status))))
        .then(j => { if (ST.ctl !== ctl || q0 !== effQ() || locked() || pv0 !== pvOn()) return; ST.srv = j && j.ok ? j : null; ST.srvQ = q0; ST.srvPv = pv0; ST.srvBusy = false; ST.srvErr = j && j.ok ? '' : 'err'; run(); paintBody(); })
        .catch(e => { if (e && e.name === 'AbortError') return; if (ST.ctl !== ctl) return; ST.srvBusy = false; ST.srvErr = String((e && e.message) || 'err'); paintMeta(); });
    }, SRV_DEBOUNCE);
  }

  const recentGet = () => arr(lsGet(LS_RECENT, [])).filter(x => x && typeof x.q === 'string').slice(0, RECENT_MAX);
  const savedGet = () => arr(lsGet(LS_SAVED, [])).filter(x => x && typeof x.q === 'string').slice(0, SAVED_MAX);
  function recentAdd(q, lab) {
    if (pvOn()) return;
    const s = String(q || '').trim(); if (!s) return;
    const r = recentGet().filter(x => x.q !== s); r.unshift({ q: s, lab: lab || '', t: Date.now() }); lsSet(LS_RECENT, r.slice(0, RECENT_MAX));
  }
  function savedToggle() {
    if (pvOn()) return;
    const s = ST.q.trim(); if (!s) return;
    const v = savedGet(), i = v.findIndex(x => x.q === s);
    if (i >= 0) v.splice(i, 1); else v.unshift({ q: s, t: Date.now() });
    lsSet(LS_SAVED, v.slice(0, SAVED_MAX));
    const a = API(); if (a) a.toast(i >= 0 ? '저장한 검색에서 뺐어요' : '검색을 저장했어요 — 처음 화면 ‘저장한 검색’');
    paintHead();
  }
  function askSave() {
    if (pvOn()) return;
    const a = API(), q = effQ().trim(); if (!q) return;
    const sv = savedGet().filter(x => x.q !== q); sv.unshift({ q, lab: ST.q.trim(), t: Date.now() }); lsSet(LS_SAVED, sv.slice(0, SAVED_MAX));
    if (a) a.toast('이 조건을 저장했어요 — 처음 화면 ‘저장한 검색’'); paintBody();
  }
  const ago = t => { const s = Math.max(0, (Date.now() - num(t)) / 1000); return s < 3600 ? '방금' : s < 86400 ? Math.floor(s / 3600) + '시간 전' : s < 172800 ? '어제' : Math.floor(s / 86400) + '일 전'; };

  let ROOT = null;
  function ensureRoot() {
    if (ROOT && document.body.contains(ROOT)) return ROOT;
    ROOT = document.createElement('div');
    ROOT.id = 'tjSearch';
    ROOT.className = 'tjs-root';
    ROOT.innerHTML = '<div class="tjs-dim" data-srch="close"></div><div class="tjs-box" role="dialog" aria-modal="true" aria-label="전체 검색"><div class="tjs-head"></div><div class="tjs-meta"></div><div class="tjs-body"><div class="tjs-list" role="listbox" aria-label="검색 결과"></div><div class="tjs-pv" aria-live="polite"></div></div><div class="tjs-keys"></div></div>';
    document.body.appendChild(ROOT);
    return ROOT;
  }
  function paintHead() {
    const R = ensureRoot(), h = $('.tjs-head', R), a = API();
    const inp = $('#tjsQ', R);
    const saved = savedGet().some(x => x.q === ST.q.trim());
    const ph = '코인 · 주소 · 해시 · 날짜 · 설정' + (wide() ? ' — 예: sol · 0x17a0 · 10/2 · coin:ETH after:2026-09' : '');
    if (!inp) {
      h.innerHTML = '<label class="tjs-in">' + ((a && a.IC.search) || '') + '<input id="tjsQ" type="text" inputmode="search" enterkeyhint="search" autocomplete="off" autocapitalize="off" spellcheck="false" role="combobox" aria-expanded="true" aria-controls="tjsList" aria-autocomplete="list" aria-label="전체 검색" maxlength="' + Q_MAX + '" placeholder="' + esc(ph) + '">'
        + '<span class="tjs-askb" hidden>' + IX.spark + '<span class="t">문장으로 찾기</span></span><button type="button" class="tjs-star" data-srch="save" aria-label="이 검색 저장">' + IX.star + '</button><button type="button" class="tjs-x" data-srch="clear" aria-label="지우기">' + IX.x + '</button>'
        + (wide() ? '<span class="tjs-cnt"></span><kbd class="tjs-kk">Esc</kbd>' : '') + '</label>' + (wide() ? '' : '<button type="button" class="tjs-close" data-srch="close">닫기</button>');
      const i2 = $('#tjsQ', R);
      i2.value = ST.q;
      i2.addEventListener('input', () => { ST.q = i2.value; ST.sel = 0; ST.expand = ''; ST.copyArm = -1; ST.kbd = false; if (ST.ask && ST.ask.q !== ST.q) ST.ask = null; run(); srvKick(); askKick(); paintBody(); });
    }
    const i3 = $('#tjsQ', R);
    if (i3 && i3.value !== ST.q) i3.value = ST.q;
    const st = $('.tjs-star', R); if (st) { st.hidden = !ST.q.trim() || pvOn(); st.classList.toggle('on', saved); st.setAttribute('aria-pressed', String(saved)); st.setAttribute('aria-label', saved ? '저장한 검색에서 빼기' : '이 검색 저장'); }
    const x = $('.tjs-x', R); if (x) x.hidden = !ST.q;
    const ab = $('.tjs-askb', R); if (ab) { const on = !!((ST.ask && ST.ask.q === ST.q) || (ST.askBusy && ST.askBusy === ST.q.trim())); ab.hidden = !on; ab.classList.toggle('busy', !!ST.askBusy); }
    if (i3) { if (ST.flat.length && ST.q.trim()) i3.setAttribute('aria-activedescendant', 'tjsO' + ST.sel); else i3.removeAttribute('aria-activedescendant'); }
  }
  function paintMeta() {
    const R = ensureRoot(), mt = $('.tjs-meta', R), a = API(), P = ST.P || parseQ(ST.q);
    let h = '';
    if (pvOn()) h += '<div class="tjs-hide">' + IX.eyeoff + '<span>' + (a && a.S.rand ? '금액 랜덤값 켜짐 — 결과 금액도 바뀐 값' : '금액 가리기 켜짐 — 결과 금액은 •••') + ' · 주소는 앞뒤만 · 최근 검색 숨김 · 금액으로 찾기 끔</span></div>';
    const A = ST.ask && ST.ask.q === ST.q ? ST.ask : null;
    if (A) {
      const cs = askChips(A);
      h += '<div class="tjs-ask"><span class="tjs-asklab">이렇게 알아들었어요</span>' + cs.map((c, i) => '<span class="tjs-ac">' + esc(c.t) + '<button type="button" data-srch="askoff" data-v="' + i + '" aria-label="' + esc(c.lab) + ' 빼기">' + IX.x + '</button></span>').join('')
        + (A.text.trim() ? '<span class="tjs-ac txt">' + esc(A.text.trim()) + '</span>' : '') + (cs.length ? '' : '<span class="tjs-asklab">조건을 다 뺐어요 — 문자로 찾는 중</span>')
        + '<span class="sp"></span><button type="button" class="tjs-asksave" data-srch="asksave">이 조건 저장</button>'
        + '<span class="tjs-asknote">' + esc(A.via === 'claude' ? '이 컴퓨터의 claude 가 문장 → 조건만 바꿔요 · 데이터는 밖으로 안 나가요' : '규칙으로 알아들었어요(모델 호출 없음)') + '</span>'
        + (A.echo ? '<div class="tjs-askecho">' + esc(A.echo) + '</div>' : '') + '</div>';
    } else if (ST.askBusy && ST.askBusy === ST.q.trim()) h += '<div class="tjs-ask"><span class="tjs-spin" aria-hidden="true"></span><span class="tjs-asklab">문장을 조건으로 바꾸는 중… 그동안 글자로 먼저 찾았어요</span></div>';
    if (pvOn() && (P.f.amt || P.f.pnl)) h += '<div class="tjs-tip" style="margin-top:8px">가리기·랜덤값 중에는 금액·손익 조건(amt: · pnl:)을 쓰지 않고 찾아요</div>';
    if (P.chips.length && !A) h += '<div class="tjs-fchips">' + IX.filter + P.chips.map((c, i) => '<button type="button" class="tjs-fc" data-srch="unf" data-v="' + i + '">' + esc(c.t) + '<span aria-hidden="true">' + IX.x + '</span><span class="sr">필터 지우기</span></button>').join('') + '</div>';
    const q = ST.q.trim();
    const counts = {}; ST.items.forEach(it => { counts[it.kind] = (counts[it.kind] || 0) + 1; });
    const scopes = q ? [['all', '전체', ST.items.length]].concat(ST.groups.map(g => [g.kind, KL[g.kind], g.items.length])) : SCOPE0.map(s => [s[0], s[1], null]);
    if (q && ST.scope !== 'all' && !counts[ST.scope]) scopes.push([ST.scope, KL[ST.scope], 0]);
    h += '<div class="tjs-scopes" role="tablist" aria-label="찾을 종류">' + scopes.map(s => '<button type="button" role="tab" class="tjs-chip' + (ST.scope === s[0] ? ' on' : '') + '" aria-selected="' + (ST.scope === s[0]) + '" data-srch="scope" data-v="' + s[0] + '">' + esc(s[1]) + (s[2] != null ? ' <small class="pvx">' + s[2] + '</small>' : '') + '</button>').join('') + '</div>';
    mt.innerHTML = h;
    const cnt = $('.tjs-cnt', R);
    if (cnt) cnt.innerHTML = q ? pvx(ST.items.length + '개') + (ST.srvBusy ? ' <span class="tjs-spin" aria-hidden="true"></span>' : '') : '';
  }
  function rowHTML(it, i) {
    const sel = i === ST.sel && (wide() || ST.kbd);
    return '<div class="tjs-r' + (sel ? ' sel' : '') + (it.spam ? ' spam' : '') + '" role="option" id="tjsO' + i + '" aria-selected="' + sel + '" data-srch="pick" data-v="' + i + '">' + kindIcon(it.kind, it)
      + '<div class="tjs-tx"><b>' + it.title + '</b><span>' + (it.sub || '') + '</span></div>' + (it.rt || '') + (sel && wide() ? '<kbd class="tjs-kbd" aria-hidden="true">' + IX.enter + '</kbd>' : '') + '</div>';
  }
  function emptyHTML() {
    const a = API(), D = a && a.S.D, rec = pvOn() ? [] : recentGet().slice(0, 4), sv = pvOn() ? [] : savedGet().slice(0, 4);
    let h = '';
    if (sv.length) h += '<div class="tjs-gh">저장한 검색 <span class="sp"></span></div><div class="tjs-sl">' + sv.map((r, i) => '<div class="tjs-r" data-srch="again" data-v="s' + i + '">' + tic(IX.star, 'star') + '<div class="tjs-tx"><b>' + esc(r.lab || r.q) + '</b><span>' + (r.lab ? '<span class="tjs-mono">' + esc(r.q) + '</span> · ' : '') + '저장 ' + esc(ago(r.t)) + '</span></div><button type="button" class="tjs-rx" data-srch="unsave" data-v="' + i + '" aria-label="저장 지우기">' + IX.x + '</button></div>').join('') + '</div>';
    if (rec.length) h += '<div class="tjs-gh">최근 검색 <span class="sp"></span><button type="button" class="tjs-lnk" data-srch="clrRecent">지우기</button></div><div class="tjs-sl">' + rec.map((r, i) => '<div class="tjs-r" data-srch="again" data-v="r' + i + '">' + tic(IX.clock) + '<div class="tjs-tx"><b>' + esc(r.q) + '</b><span>' + esc((r.lab ? r.lab + ' · ' : '') + ago(r.t)) + '</span></div><button type="button" class="tjs-rx" data-srch="unrecent" data-v="' + i + '" aria-label="최근 검색 지우기">' + IX.x + '</button></div>').join('') + '</div>';
    else if (pvOn()) h += '<div class="tjs-tip"><b>가리기·랜덤값 중</b> · 지난 검색어는 지웠고 새로 남기지 않아요 · 저장해 둔 조건은 숨겨요(끄면 다시 보여요)</div>';
    if (D && a) {
      const T = (a.IC && a.IC.tab) || {}, tk = String(D.todayKey || todayIso().slice(5)), c = a.dayCnt ? a.dayCnt(tk, true) : null, rz = (D.realized || {})[tk];
      const iso = todayIso();
      const pendN = arr(D.ofPend).length, unk = arr(D.pendings).filter(p => p && !p.hide).length, H = window.TJHealth && window.TJHealth.summary ? (() => { try { return window.TJHealth.summary(); } catch (e) { return null; } })() : null;
      const go = (ic, t, s, tag, v) => '<div class="tjs-r" data-srch="quick" data-v="' + v + '">' + tic(ic) + '<div class="tjs-tx"><b>' + t + '</b><span>' + s + '</span></div><span class="tjs-go">' + tag + '</span></div>';
      h += '<div class="tjs-gh">바로 가기</div><div class="tjs-sl">'
        + go(T.daily || IX.clock, '오늘 기록', esc((+iso.slice(5, 7)) + '월 ' + (+iso.slice(8)) + '일 (' + dowOf(iso) + ')') + (c ? ' · ' + pvx(c.n + '건') : '') + (rz != null ? ' · 실현 ' + a.m(num(rz), { sign: true, compact: true }) : ''), '일별', 'today')
        + (D.of ? go(T.outflows || IX.go, '확인 필요 전송', pvx(pendN + '곳') + (D.ofPendUsd ? ' · 순유출 ' + a.m(num(D.ofPendUsd), { compact: true }) : ''), '보낸 내역', 'of') : '')
        + go(T.unmatched || IX.go, '미매칭 확인', pvx(unk + '건') + ' · 원가 미확인·출처 미상', '미매칭', 'unm')
        + (H && H.loaded ? go(IX.pulse, '상태 · ' + esc(H.label || ''), H.crit + H.warn ? '주의할 것 ' + pvx((H.crit + H.warn) + '건') : '손댈 것 없음', '패널', 'health') : '')
        + '</div>';
    }
    h += '<div class="tjs-tip"><b>이렇게도 찾아요</b> · 주소·해시는 앞 4자리부터 · 날짜는 10-02 · 10/2 · 어제 · 지난주 · 설정 이름(소액 기준, 조용한 시간) · 필터 <code>coin:ETH</code> <code>chain:base</code> <code>type:sell</code> <code>after:2026-09</code> <code>pnl:&lt;0</code> <code>amt:&gt;1000</code></div>';
    return h;
  }
  function paintBody() {
    const R = ensureRoot(), L = $('.tjs-list', R), q = ST.q.trim(), a = API(), P = ST.P || parseQ(ST.q);
    L.id = 'tjsList';
    paintMeta();
    if (!q) { L.innerHTML = emptyHTML(); paintPv(); keysPaint(); logos(); return; }
    let h = '';
    const exact = (P.type === 'hex' || P.type === 'b58') && P.hex.length >= 10 ? ST.flat.find(it => (it.addr && String(it.addr).toLowerCase() === P.hex.toLowerCase()) || (it.tx && String(it.tx).toLowerCase() === P.hex.toLowerCase())) : null;
    let i = 0;
    ST.groups.forEach(g => {
      h += '<div class="tjs-gh">' + esc(KL[g.kind]) + ' <span class="n pvx">' + g.items.length + '</span><span class="sp"></span>' + (g.more ? '<button type="button" class="tjs-lnk" data-srch="more" data-v="' + g.kind + '">모두 ›</button>' : (ST.expand === g.kind ? '<button type="button" class="tjs-lnk" data-srch="less" data-v="' + g.kind + '">접기</button>' : '')) + '</div>';
      h += '<div class="tjs-sl">' + g.shown.map(it => rowHTML(it, i++)).join('') + '</div>';
      if (g.kind === 'coin' && P.type === 'ticker' && g.items[0] && !ST.scope.match(/cycle|event/)) {
        const s0 = g.items[0].sym;
        h += '<button type="button" class="tjs-moreq" data-srch="filt" data-v="' + esc(String(s0 || '').toUpperCase()) + '">' + IX.filter + '<span><b>' + esc(s0) + '</b> 기록 — 매매일지 전체 기록에서 거르기</span><span class="sp"></span>›</button>';
      }
    });
    if (!ST.flat.length) h += '<div class="tjs-none"><b>‘' + esc(q) + '’와 맞는 결과가 없어요</b><span>' + (ST.srvBusy ? '전체 기록에서 더 찾는 중…' : P.type === 'amt' && pvOn() ? '가리기·랜덤값 중에는 금액으로 찾지 않아요' : '주소·해시는 앞 4자리부터, 날짜는 10/2 · 어제처럼 넣어 보세요') + '</span></div>';
    if (exact && exact.acts && !wide()) h += '<div class="tjs-gh">정확히 일치하면</div><div class="tjs-exact"><div class="tjs-exh">' + exact.title + '</div><div class="tjs-acts">' + exact.acts.map((x, k) => actBtn(x, 'x' + k, k === 0)).join('') + '</div></div>';
    if ((P.type === 'hex' || P.type === 'b58') && P.hex.length < 10 && ST.flat.length) h += '<div class="tjs-tip"><b>전체 주소·해시를 붙여 넣으면</b> 정확히 하나로 좁혀요 — 보낸 전송·미매칭은 전체 해시로, 체결은 앞 6 · 뒤 4 자리로 맞춰요</div>';
    if (ST.srv && ST.srv.building) h += '<div class="tjs-tip"><span class="tjs-spin" aria-hidden="true"></span> 전체 기록 색인을 만드는 중 — 받아 둔 화면 데이터에서 먼저 찾았어요</div>';
    else if (ST.srvErr && ST.srvErr !== 'none' && ST.srvErr !== 'err') h += '<div class="tjs-tip">전체 기록 검색에 닿지 못했어요 — 받아 둔 화면 데이터에서만 찾았어요</div>';
    L.innerHTML = h;
    paintPv();
    keysPaint();
    paintHead();
    logos();
    const se = $('#tjsO' + ST.sel, R); if (se && ST.kbd) { try { se.scrollIntoView({ block: 'nearest' }); } catch (e) {  } }
  }
  const logos = () => { const a = API(); if (a && a.hydrateLogos) { try { a.hydrateLogos(); } catch (e) {  } } };
  function actBtn(x, v, pri) {
    if (x.ext) return '<a class="btn sm' + (pri ? ' pri' : '') + '" href="' + esc(x.ext) + '" target="_blank" rel="noopener noreferrer">' + esc(x.t) + ' ↗</a>';
    const armed = x.copy && ST.copyArm === v;
    return '<button type="button" class="btn sm' + (pri ? ' pri' : '') + '" data-srch="act" data-v="' + v + '">' + esc(armed ? '한 번 더 누르면 복사' : x.t) + '</button>';
  }
  function paintPv() {
    const R = ensureRoot(), V = $('.tjs-pv', R), a = API();
    if (!wide()) { V.innerHTML = ''; return; }
    const it = ST.q.trim() ? ST.flat[ST.sel] : null;
    if (!it || !a) { V.innerHTML = '<div class="tjs-pv0">' + IX.spark + '<b>' + (ST.q.trim() ? '결과를 고르면 여기서 미리 봐요' : '찾고 싶은 걸 넣어 보세요') + '</b><span>↑↓ 로 고르고 ↵ 로 그 화면 그 자리로</span></div>'; return; }
    const m = a.m, kv = (k, v) => '<div><span>' + k + '</span><b>' + v + '</b></div>';
    let h = '<div class="tjs-pt">' + kindIcon(it.kind, it) + '<div><b>' + it.title + '</b><span>' + esc(KL[it.kind]) + '</span></div></div>';
    if (it.kind === 'coin' && it.g) {
      const g = it.g;
      h += '<div class="tjs-big">' + m(g.value) + '</div><div class="tjs-kvs">' + kv('평가손익', g.roi != null ? (pvOn() ? '<span class="tjs-mask">•••%</span>' : '<span class="' + (g.roi >= 0 ? 'up' : 'down') + '">' + esc(a.pctS(g.roi, 1)) + '</span>') : '—')
        + kv('손익', m(num(g.pnl), { sign: true, compact: true })) + kv('원가 확인', pvx(Math.round((1 - num(g.unkPct)) * 100) + '%')) + kv('보관', locHTML(g) || '—') + '</div>';
    } else if (it.kind === 'outflow' && it.of) {
      const r = it.of;
      h += '<div class="tjs-kvs">' + kv('보냄', r.sendKnown ? m(num(r.usdAtSend), { compact: true }) : '—') + kv('순유출', r.netUsd != null ? m(Math.max(0, num(r.netUsd)), { compact: true }) : '—')
        + kv('돌려받음', m(num(r.returnedUsd), { compact: true })) + kv('전송', pvx(num(r.count) + '건')) + '</div><div class="tjs-chs">' + arr(r.chainNames).slice(0, 4).map(c => '<span class="pill g sm">' + esc(c) + '</span>').join(' ') + '</div>';
    } else if (it.sub) h += '<div class="tjs-pvsub">' + it.sub + '</div>' + (it.rt ? '<div class="tjs-pvrt">' + it.rt + '</div>' : '');
    const acts = [{ t: openLabel(it), go: () => openItem(it), k: '↵' }].concat(it.alt ? [Object.assign({ k: KMOD + '↵' }, it.alt)] : []).concat(arr(it.acts));
    h += '<div class="tjs-pacts">' + acts.map((x, k) => (x.ext ? '<a class="tjs-pa" href="' + esc(x.ext) + '" target="_blank" rel="noopener noreferrer"><span>' + esc(x.t) + ' ↗</span><span class="sp"></span></a>'
      : '<button type="button" class="tjs-pa' + (k === 0 ? ' pri' : '') + '" data-srch="pact" data-v="' + k + '"><span>' + esc(x.copy && ST.copyArm === 'p' + k ? '한 번 더 누르면 복사' : x.t) + '</span>' + (x.sub ? '<small>' + esc(x.sub) + '</small>' : '') + '<span class="sp"></span>' + (x.k ? '<kbd class="tjs-kk">' + esc(x.k) + '</kbd>' : '') + '</button>')).join('') + '</div>';
    V.innerHTML = h;
    V._acts = acts; V._it = it;
  }
  const openLabel = it => ({ coin: '대시보드 보유 코인에서 열기', cycle: '매매일지 사이클 열기', outflow: '보낸 내역에서 열기', tx: '그날 기록에서 열기', event: '그날 기록에서 열기', day: '일별에서 열기',
    receipt: '차익 영수증 열기', review: '그날 리뷰 열기', memo: '그날 근거 메모 열기', pending: '미매칭에서 열기', nft: 'NFT 에서 열기', other: '기타 자산에서 열기', wallet: '설정 › 지갑에서 열기',
    deposit: '입금 주소 열기', setting: '그 설정으로 가기' }[it.kind] || '열기');
  function keysPaint() {
    const R = ensureRoot(), K = $('.tjs-keys', R);
    if (!wide()) { K.innerHTML = ''; return; }
    const kk = s => '<kbd class="tjs-kk">' + s + '</kbd>';
    K.innerHTML = '<span>' + kk('↑') + kk('↓') + ' 이동</span><span>' + kk('↵') + ' 열기</span><span>' + kk(KMOD + '↵') + ' 다른 화면으로</span><span>' + kk('Tab') + ' 종류 바꾸기</span><span>' + kk('Esc') + ' 닫기</span><span class="sp"></span><span>' + kk('/') + ' 또는 ' + kk(KMOD + 'K') + ' 로 열기</span>';
  }
  function paintAll() { run(); paintHead(); paintBody(); }

  function open(q, scope) {
    const a = API();
    if (!a || locked()) { if (typeof q === 'string' && a && a.S && !a.S.locked) ST.pend = { q, scope: scope || 'all' }; return; }
    pvGuard();
    ensureRoot(); addCss();
    if (typeof q === 'string') { ST.q = q.slice(0, Q_MAX); ST.sel = 0; ST.expand = ''; }
    if (scope) ST.scope = scope;
    if (!ST.open) {
      ST.open = true; ST.prevFocus = document.activeElement; ST.kbd = false; ST.copyArm = -1;
      document.documentElement.classList.add('tjs-on');
      ROOT.classList.add('open');
      if (!wide()) { try { history.pushState({ tjSrch: 1 }, '', location.href); ST.pushed = true; } catch (e) { ST.pushed = false; } }
      hideBack();
    }
    paintAll(); srvKick(); askKick();
    const i = $('#tjsQ', ROOT); if (i) { try { i.focus({ preventScroll: true }); i.setSelectionRange(i.value.length, i.value.length); } catch (e) { i.focus(); } }
  }
  function pvGuard() {
    const p = pvOn();
    if (p) { try { if (localStorage.getItem(LS_RECENT) != null) localStorage.removeItem(LS_RECENT); } catch (e) {  } }
    if (ST.pvSig === null) { ST.pvSig = p; return false; }
    if (p === ST.pvSig) return false;
    ST.pvSig = p;
    if (!p) return false;
    if (ST.ctl) { try { ST.ctl.abort(); } catch (e) {  } }
    clearTimeout(ST.tmr); clearTimeout(ST.askTmr);
    ST.ctl = null; ST.srv = null; ST.srvQ = ''; ST.srvPv = null; ST.srvBusy = false; ST.srvErr = ''; ST.items = []; ST.flat = []; ST.groups = []; ST.P = null;
    ST.ask = null; ST.askBusy = ''; ASK_CACHE.clear(); ST.q = ''; ST.sel = 0; ST.expand = '';
    if (ROOT) { ['.tjs-list', '.tjs-pv', '.tjs-meta'].forEach(sel => { const e = ROOT.querySelector(sel); if (e) e.innerHTML = ''; }); const i = ROOT.querySelector('#tjsQ'); if (i) i.value = ''; }
    hideBack(); ST.back = null;
    return true;
  }
  function lock() {
    try { if (ST.open) close(); } catch (e) {  }
    if (ST.ctl) { try { ST.ctl.abort(); } catch (e) {  } }
    clearTimeout(ST.tmr); clearTimeout(ST.askTmr);
    ST.ctl = null; ST.srv = null; ST.srvQ = ''; ST.srvBusy = false; ST.srvErr = ''; ST.items = []; ST.flat = []; ST.groups = []; ST.P = null;
    ST.ask = null; ST.askBusy = ''; ST.q = ''; ST.after = null; ST.pend = null; ST.srvPv = null; ASK_CACHE.clear();
    hideBack(); ST.back = null;
    if (ROOT) ['.tjs-list', '.tjs-pv', '.tjs-meta'].forEach(sel => { const e = ROOT.querySelector(sel); if (e) e.innerHTML = ''; });
    const i = ROOT && ROOT.querySelector('#tjsQ'); if (i) i.value = '';
  }
  function close(viaPop) {
    if (!ST.open) return;
    ST.open = false;
    if (ST.ctl) { try { ST.ctl.abort(); } catch (e) {  } }
    clearTimeout(ST.tmr);
    document.documentElement.classList.remove('tjs-on');
    if (ROOT) ROOT.classList.remove('open');
    if (ST.pushed && !viaPop) { ST.pushed = false; try { history.back(); } catch (e) {  } }
    ST.pushed = false;
    const f = ST.prevFocus; ST.prevFocus = null;
    if (f && f.focus && document.body.contains(f)) { try { f.focus({ preventScroll: true }); } catch (e) {  } }
  }
  function closeKeep(then) {
    if (!ST.open) { if (then) then(); return; }
    const q = ST.q.trim(), sc = ST.scope;
    if (q) recentAdd(q, ST.flat[ST.sel] ? KL[ST.flat[ST.sel].kind] : '');
    let go = then || null;
    if (ST.pushed) {
      ST.pushed = false;
      if (go) {
        const run9 = go; go = null;
        let done = false;
        const fin = () => { if (done) return; done = true; window.removeEventListener('popstate', onPop9); run9(); };
        const onPop9 = () => setTimeout(fin, 0);
        window.addEventListener('popstate', onPop9);
        setTimeout(fin, 600);
        try { history.back(); } catch (e) { fin(); }
      } else { try { history.back(); } catch (e) {  } }
    }
    ST.open = false;
    if (ST.ctl) { try { ST.ctl.abort(); } catch (e) {  } }
    document.documentElement.classList.remove('tjs-on');
    if (ROOT) ROOT.classList.remove('open');
    ST.prevFocus = null;
    if (q) showBack(q, sc);
    if (go) go();
  }
  function goAnc(kind, id, tab) {
    const a = API(); if (!a) return;
    closeKeep(() => {
      const anc = kind + ':' + id;
      const R = window.TJ && typeof window.TJ.revealAndHighlight === 'function' ? window.TJ.revealAndHighlight : null;
      if (R) { try { R(anc); return; } catch (e) {  } }
      if (kind === 'day') { a.goDay(String(id).slice(0, 5)); return; }
      if (tab) a.goTab(tab);
    });
  }
  function openItem(it) {
    if (!it) return;
    if (it.go) { it.go(); return; }
    if ((it.kind === 'day' || it.kind === 'review') && it.dayK) { goAnc('day', it.dayK, 'daily'); return; }
    if (it.anc) { const i = it.anc.indexOf(':'); goAnc(it.anc.slice(0, i), it.anc.slice(i + 1), it.tab); return; }
    if (it.tab) closeKeep(() => API().goTab(it.tab));
  }
  function runAct(x, key, it) {
    if (!x) return;
    if (x.copy && it && it.spam) { const a0 = API(); if (a0) a0.toast('스팸·주소 오염 의심 주소는 복사하지 않아요 — 그 주소로 보내지 않게', true); return; }
    if (x.copy) {
      if (pvOn() && ST.copyArm !== key) { ST.copyArm = key; paintBody(); return; }
      ST.copyArm = -1;
      const a = API();
      const done = () => { if (a) a.toast('복사했어요'); paintBody(); };
      try { navigator.clipboard.writeText(String(x.copy)).then(done, () => { if (a) a.toast('복사하지 못했어요', true); }); } catch (e) { if (a) a.toast('복사하지 못했어요', true); }
      return;
    }
    if (x.go) x.go();
  }
  let backEl = null, backObs = null;
  function showBack(q, sc) {
    hideBack();
    const el = document.createElement('div');
    el.id = 'tjsBack'; el.className = 'tjs-back'; el.setAttribute('role', 'status');
    el.innerHTML = ((API() && API().IC.search) || '') + '<span class="tjs-bt">검색 ‘' + esc(q.length > 24 ? q.slice(0, 24) + '…' : q) + '’ 에서 열림</span><span class="sp"></span><button type="button" data-srch="reopen">결과로 ‹</button><button type="button" class="x" data-srch="unback" aria-label="닫기">' + IX.x + '</button>';
    backEl = el;
    ST.back = { q, sc, at: Date.now(), hc: 0 };
    const B = document.getElementById('banners');
    const put = () => { if (!backEl) return; const b9 = document.getElementById('banners'); if (b9 && b9.firstChild !== backEl) b9.insertBefore(backEl, b9.firstChild); };
    if (B) { put(); try { backObs = new MutationObserver(put); backObs.observe(B, { childList: true }); } catch (e) {  } }
    else document.body.appendChild(el);
    clearTimeout(ST.backTmr);
    ST.backTmr = setTimeout(hideBack, 45000);
  }
  function hideBack() {
    clearTimeout(ST.backTmr);
    if (backObs) { try { backObs.disconnect(); } catch (e) {  } backObs = null; }
    if (backEl) { backEl.remove(); backEl = null; }
    ST.back = ST.back && ST.open ? ST.back : null;
  }

  function onClick(ev) {
    const t = ev.target && ev.target.closest ? ev.target.closest('[data-srch]') : null;
    if (!t) return;
    const k = t.getAttribute('data-srch'), v = t.getAttribute('data-v');
    const inSearch = ROOT && ROOT.contains(t);
    if (k === 'open') { ev.preventDefault(); open(null); return; }
    if (k === 'reopen') { ev.preventDefault(); const b = ST.back; hideBack(); if (b) open(b.q, b.sc || 'all'); return; }
    if (k === 'unback') { ev.preventDefault(); hideBack(); return; }
    if (!inSearch) return;
    ev.preventDefault();
    const a = API();
    if (k === 'close') close();
    else if (k === 'clear') { ST.q = ''; ST.sel = 0; ST.scope = 'all'; ST.expand = ''; paintAll(); const i = $('#tjsQ', ROOT); if (i) i.focus(); }
    else if (k === 'save') savedToggle();
    else if (k === 'askoff') { const A = ST.ask; if (A) { const c = askChips(A)[+v]; if (c) c.keys.forEach(x => A.off.add(x)); ST.sel = 0; run(); srvKick(); paintBody(); refocus(); } }
    else if (k === 'asksave') askSave();
    else if (k === 'scope') { ST.scope = v || 'all'; ST.sel = 0; ST.expand = ''; paintAll(); srvKick(); refocus(); }
    else if (k === 'more') { if (ST.q.trim()) { ST.scope = v; ST.sel = 0; paintAll(); srvKick(); refocus(); } }
    else if (k === 'less') { ST.expand = ''; paintAll(); refocus(); }
    else if (k === 'pick') { const i = +v; ST.sel = i; const it = ST.flat[i]; if (wide() && !ev.detail) { paintBody(); return; } openItem(it); }
    else if (k === 'again') { const r = v.charAt(0) === 's' ? savedGet()[+v.slice(1)] : recentGet()[+v.slice(1)]; if (r) { ST.q = r.q; ST.sel = 0; if (ST.ask && ST.ask.q !== ST.q) ST.ask = null; paintAll(); srvKick(); askKick(); refocus(); } }
    else if (k === 'unrecent') { const r = recentGet(); r.splice(+v, 1); lsSet(LS_RECENT, r); paintBody(); }
    else if (k === 'unsave') { const r = savedGet(); r.splice(+v, 1); lsSet(LS_SAVED, r); paintBody(); }
    else if (k === 'clrRecent') { lsSet(LS_RECENT, []); paintBody(); }
    else if (k === 'unf') { const P = ST.P || parseQ(ST.q), c = P.chips[+v]; if (c) { ST.q = removeFilter(ST.q, c.k); paintAll(); srvKick(); refocus(); } }
    else if (k === 'filt') { ST.q = 'coin:' + v; ST.scope = 'event'; ST.sel = 0; paintAll(); srvKick(); refocus(); }
    else if (k === 'quick') {
      if (!a) return;
      if (v === 'today') closeKeep(() => a.goDay(String((a.S.D && a.S.D.todayKey) || todayIso().slice(5))));
      else if (v === 'of') closeKeep(() => a.goTab('outflows'));
      else if (v === 'unm') closeKeep(() => a.goTab('unmatched'));
      else if (v === 'health') closeKeep(() => { try { if (window.TJHealth && window.TJHealth.open) window.TJHealth.open(); } catch (e) {  } });
    } else if (k === 'act') {
      const i = String(v || '');
      if (i.charAt(0) === 'x') { const P = ST.P; const ex = ST.flat.find(it => (it.addr && P && String(it.addr).toLowerCase() === P.hex.toLowerCase()) || (it.tx && P && String(it.tx).toLowerCase() === P.hex.toLowerCase())); if (ex && ex.acts) runAct(ex.acts[+i.slice(1)], i, ex); }
    } else if (k === 'pact') { const V = $('.tjs-pv', ROOT), acts = V && V._acts; if (acts) runAct(acts[+v], 'p' + v, V._it); }
  }
  function removeFilter(q, k) {
    const keys = k === 'coin' ? ['coin', 'sym'] : k === 'type' ? ['type', 'kind'] : [k];
    return String(q).replace(FILT_RE, (all, sp, k0) => (keys.indexOf(k0.toLowerCase()) >= 0 ? sp : all)).replace(/\s{2,}/g, ' ').trim();
  }
  const refocus = () => { const i = $('#tjsQ', ROOT); if (i && document.activeElement !== i) { try { i.focus({ preventScroll: true }); } catch (e) { i.focus(); } } };
  function inField(t) { return !!(t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)); }
  function otherDialog() {
    const a = API();
    if (a && a.S && (a.S.modal || a.S.drawer || a.S.sheet)) return true;
    const sel = '.modal-bg,.drawer,.usheet,.usheet-bg,#suWizard,#suPerm,.tjh-bg,[aria-modal="true"],[role="dialog"]';
    return Array.from(document.querySelectorAll(sel)).some(e => !(ROOT && ROOT.contains(e)) && e.getClientRects().length > 0);
  }
  function onKey(ev) {
    const a = API();
    const mod = ev.metaKey || ev.ctrlKey;
    if (mod && !ev.altKey && !ev.shiftKey && (ev.key === 'k' || ev.key === 'K')) {
      if (ST.open) { ev.preventDefault(); ev.stopPropagation(); close(); return; }
      if (otherDialog() || locked()) return;
      ev.preventDefault(); ev.stopPropagation(); open(null); return;
    }
    if (!ST.open) {
      if (ev.key === '/' && !mod && !ev.altKey && !inField(ev.target) && a && a.S.tab !== 'settings' && !otherDialog() && !locked()) { ev.preventDefault(); open(null); }
      return;
    }
    if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); if (ST.q && !wide()) { close(); return; } close(); return; }
    if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
      if (!ST.flat.length) return;
      ev.preventDefault(); ST.kbd = true; ST.copyArm = -1;
      ST.sel = (ST.sel + (ev.key === 'ArrowDown' ? 1 : -1) + ST.flat.length) % ST.flat.length;
      paintBody(); return;
    }
    if (ev.key === 'Enter' && !ev.isComposing) {
      const it = ST.flat[ST.sel];
      if (ev.target && ev.target.closest && ev.target.closest('[data-srch="pact"],[data-srch="act"],a,button') && ev.target.id !== 'tjsQ') return;
      if (!it) return;
      ev.preventDefault();
      if (mod && it.alt) { it.alt.go(); return; }
      if (mod && it.tab) { closeKeep(() => a.goTab(it.tab)); return; }
      openItem(it); return;
    }
    if (ev.key === 'Tab') {
      ev.preventDefault();
      const chips = Array.from(ROOT.querySelectorAll('.tjs-chip'));
      if (!chips.length) return;
      const ci = chips.findIndex(c => c.classList.contains('on'));
      const nx = chips[(ci + (ev.shiftKey ? -1 : 1) + chips.length) % chips.length];
      ST.scope = nx.getAttribute('data-v') || 'all'; ST.sel = 0; ST.expand = '';
      paintAll(); srvKick(); refocus(); return;
    }
  }
  function onHash() {
    const h = location.hash || '';
    if (h.indexOf('#search=') === 0) {
      let q = ''; try { q = decodeURIComponent(h.slice(8).replace(/\+/g, ' ')); } catch (e) { q = h.slice(8); }
      const a = API();
      try { history.replaceState(null, '', location.pathname + location.search + '#' + ((a && a.S.tab) || 'dash')); } catch (e) {  }
      setTimeout(() => open(q, 'all'), 0);
      return true;
    }
    return false;
  }

  function mountHeader() {
    const a = API();
    const top = document.querySelector('header.top .in');
    if (top && !document.getElementById('srchBtn')) {
      const b = document.createElement('button');
      b.type = 'button'; b.id = 'srchBtn'; b.className = 'tjs-spill'; b.setAttribute('data-srch', 'open'); b.setAttribute('aria-label', '전체 검색 (' + KMOD + '+K)');
      b.innerHTML = ((a && a.IC.search) || '') + '<span class="t">검색</span><span class="sp"></span><kbd class="tjs-kk">' + (isMac ? '⌘K' : 'Ctrl K') + '</kbd>';
      const st = document.getElementById('status');
      top.insertBefore(b, st || null);
    }
    const mt = document.getElementById('mtop');
    if (mt && !mt.__tjs) {
      mt.__tjs = true;
      const put = () => {
        if (mt.querySelector('.srchb')) return;
        const anchor = mt.querySelector('.hideb') || mt.querySelector('.curb');
        if (!anchor) return;
        const b = document.createElement('button');
        b.type = 'button'; b.className = 'iconbtn srchb'; b.setAttribute('data-srch', 'open'); b.setAttribute('aria-label', '전체 검색');
        b.innerHTML = (a && a.IC.search) || '';
        mt.insertBefore(b, anchor);
      };
      put();
      try { new MutationObserver(put).observe(mt, { childList: true }); } catch (e) {  }
    }
  }

  function addCss() {
    if (document.getElementById('tjsCss')) return;
    const s = document.createElement('style');
    s.id = 'tjsCss';
    s.textContent = CSS;
    document.head.appendChild(s);
  }
  const CSS = [
    'html.tjs-on{overflow:hidden}',
    '.tjs-root{display:none;position:fixed;inset:0;z-index:90}',
    '.tjs-root.open{display:block}',
    '.tjs-root [hidden]{display:none!important}',
    '.tjs-dim{position:absolute;inset:0;background:var(--dim);-webkit-backdrop-filter:blur(2px);backdrop-filter:blur(2px);animation:tjsFade .16s var(--ease)}',
    '.tjs-box{position:absolute;left:50%;top:84px;transform:translateX(-50%);width:min(860px,calc(100vw - 48px));max-height:calc(100vh - 120px);background:var(--surface);border:1px solid var(--line2);border-radius:16px;box-shadow:var(--pop);display:flex;flex-direction:column;overflow:hidden;animation:tjsIn .2s var(--ease)}',
    '@keyframes tjsIn{from{opacity:0;transform:translate(-50%,-8px) scale(.985)}to{opacity:1;transform:translate(-50%,0)}}',
    '@keyframes tjsFade{from{opacity:0}to{opacity:1}}',
    '.tjs-head{display:flex;align-items:center;gap:8px;padding:12px 14px;border-bottom:1px solid var(--line)}',
    '.tjs-in{flex:1;display:flex;align-items:center;gap:10px;min-width:0;height:44px;padding:0 6px 0 10px;border-radius:12px;background:var(--surface2);border:1.5px solid var(--accent);box-shadow:0 0 0 3px var(--accentBg);cursor:text}',
    '.tjs-in>svg{width:19px;height:19px;color:var(--muted);flex:none}',
    '.tjs-in input{flex:1;min-width:0;height:100%;border:0;outline:0;background:transparent;color:var(--text);font:inherit;font-size:16px;font-weight:600;letter-spacing:-.01em;-webkit-appearance:none;appearance:none}',
    '.tjs-in input::placeholder{color:var(--faint);font-weight:500}',
    '.tjs-in input::-webkit-search-cancel-button{display:none}',
    '.tjs-x,.tjs-star{width:28px;height:28px;border-radius:50%;display:grid;place-items:center;color:var(--muted);background:var(--surface3);border:0;flex:none;cursor:pointer}',
    '.tjs-star{background:transparent}.tjs-star.on{color:var(--warn)}.tjs-star.on svg{fill:currentColor}',
    '.tjs-x svg{width:13px;height:13px}.tjs-star svg{width:17px;height:17px}',
    '.tjs-cnt{font-size:12.5px;color:var(--muted);white-space:nowrap;display:inline-flex;align-items:center;gap:6px}',
    '.tjs-close{font-size:15px;font-weight:700;color:var(--accent);background:none;border:0;padding:10px 4px;cursor:pointer;white-space:nowrap}',
    '.tjs-kk{font-family:var(--mono);font-size:11px;font-weight:700;color:var(--text2);background:var(--surface3);border:1px solid var(--line2);border-bottom-width:2px;border-radius:5px;padding:0 5px;line-height:1.6;white-space:nowrap}',
    '.tjs-meta{padding:0 14px}',
    '.tjs-hide{display:flex;align-items:center;gap:8px;margin:10px 0 0;padding:8px 12px;border-radius:10px;background:var(--warnBg);color:var(--warn);font-size:12.5px;font-weight:650}',
    '.tjs-hide svg{width:16px;height:16px;flex:none}',
    '.tjs-askb{flex:none;height:26px;padding:0 10px;border-radius:8px;background:color-mix(in srgb,var(--c4) 16%,transparent);color:var(--c4);font-size:12px;font-weight:650;display:inline-flex;align-items:center;gap:5px;white-space:nowrap}.tjs-askb svg{width:13px;height:13px}.tjs-askb.busy svg{animation:tjsSpin 1.2s linear infinite}',
    '.tjs-ask{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:10px -14px 0;padding:10px 14px;background:var(--surface2);border-top:1px solid var(--line);border-bottom:1px solid var(--line)}',
    '.tjs-asklab{font-size:12.5px;color:var(--muted)}.tjs-ask .sp{flex:1}',
    '.tjs-ac{height:30px;padding:0 6px 0 12px;border-radius:999px;background:var(--segOn);font-family:var(--mono);font-size:12.5px;display:inline-flex;align-items:center;gap:6px;color:var(--text)}.tjs-ac.txt{font-family:inherit;padding-right:12px;color:var(--text2)}',
    '.tjs-ac button{border:0;background:transparent;color:var(--muted);padding:0;width:22px;height:22px;display:grid;place-items:center;border-radius:50%;cursor:pointer}.tjs-ac button:hover{background:var(--surface3);color:var(--text)}.tjs-ac svg{width:12px;height:12px}',
    '.tjs-asksave{height:30px;padding:0 12px;border-radius:10px;border:1px solid var(--line2);background:var(--surface);color:var(--text2);font-size:12.5px;font-weight:650;cursor:pointer;white-space:nowrap}.tjs-asksave:hover{color:var(--text);border-color:var(--text2)}',
    '.tjs-asknote{font-size:12px;color:var(--faint);flex-basis:100%;text-align:right}.tjs-askecho{flex-basis:100%;font-size:12.5px;color:var(--text2)}',
    '@media (max-width:640px){.tjs-asknote{display:none}.tjs-ask{margin-top:6px}.tjs-askb{width:26px;padding:0;justify-content:center}.tjs-askb .t{display:none}}',
    '.tjs-fchips{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:10px}.tjs-fchips>svg{width:15px;height:15px;color:var(--accent)}',
    '.tjs-fc{display:inline-flex;align-items:center;gap:4px;height:28px;padding:0 6px 0 10px;border-radius:99px;border:1px solid color-mix(in srgb,var(--accent) 40%,transparent);background:var(--accentBg);color:var(--accent);font-size:12.5px;font-weight:700;cursor:pointer}',
    '.tjs-fc svg{width:12px;height:12px}.tjs-fc .sr,.tjs-root .sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}',
    '.tjs-scopes{display:flex;gap:6px;padding:10px 0;overflow-x:auto;scrollbar-width:none;border-bottom:1px solid var(--line);margin:0 -14px;padding-left:14px;padding-right:14px}',
    '.tjs-scopes::-webkit-scrollbar{display:none}',
    '.tjs-chip{flex:none;height:32px;display:inline-flex;align-items:center;gap:5px;padding:0 12px;border-radius:99px;background:var(--surface2);border:1px solid var(--line);color:var(--text2);font-size:13px;font-weight:650;cursor:pointer;white-space:nowrap}',
    '.tjs-chip small{color:var(--faint);font-weight:650}',
    '.tjs-chip.on{background:var(--accentBg);border-color:color-mix(in srgb,var(--accent) 45%,transparent);color:var(--accent)}.tjs-chip.on small{color:var(--accent)}',
    '.tjs-body{flex:1;min-height:0;display:grid;grid-template-columns:minmax(0,1fr) 320px}',
    '.tjs-list{overflow-y:auto;padding:2px 12px 14px;min-height:0;overscroll-behavior:contain}',
    '.tjs-pv{border-left:1px solid var(--line);background:var(--surface2);padding:16px;overflow-y:auto;min-height:0}',
    '.tjs-gh{display:flex;align-items:center;gap:6px;font-size:12.5px;font-weight:750;color:var(--muted);margin:14px 4px 6px}.tjs-gh .n{color:var(--faint);font-weight:650}.tjs-gh .sp{flex:1}',
    '.tjs-lnk{background:none;border:0;color:var(--accent);font-size:12.5px;font-weight:700;cursor:pointer;padding:4px 2px}',
    '.tjs-sl{border-radius:14px;background:var(--surface);border:1px solid var(--line);padding:2px 6px}',
    '.tjs-r{display:flex;align-items:center;gap:10px;padding:9px 8px;border-radius:10px;min-width:0;cursor:pointer;position:relative;transition:background .12s}',
    '.tjs-r+.tjs-r{box-shadow:0 -1px 0 var(--line)}',
    '.tjs-r:hover{background:var(--surface2)}',
    '.tjs-r.sel{background:var(--accentBg);box-shadow:none}.tjs-r.sel+.tjs-r{box-shadow:none}',
    '.tjs-r.spam{opacity:.6}',
    '.tjs-ic{width:32px;height:32px;border-radius:10px;display:grid;place-items:center;flex:none;background:var(--surface2);color:var(--text2);border:1px solid var(--line)}',
    '.tjs-ic svg{width:16px;height:16px}.tjs-ic.star{color:var(--warn)}',
    '.tjs-cic{flex:none;display:grid;place-items:center;width:32px;height:32px}',
    '.tjs-tx{flex:1;min-width:0}',
    '.tjs-tx>b{display:block;font-size:14.5px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text)}',
    '.tjs-tx>b .pill{margin-left:6px}',
    '.tjs-tx>span{display:block;font-size:12.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:1px}',
    '.tjs-root mark{background:transparent;color:var(--accent);font-weight:800}',
    '.tjs-mono{font-family:var(--mono);font-size:.93em;font-weight:650}.tjs-mut{color:var(--muted);font-weight:500}',
    '.tjs-kb{display:inline-block;font-size:11px;font-weight:750;padding:0 6px;border-radius:5px;background:var(--surface3);color:var(--text2);line-height:1.6;vertical-align:1px}',
    '.tjs-rt{text-align:right;flex:none;max-width:46%;display:flex;flex-direction:column;align-items:flex-end}.tjs-rt>b{display:flex;align-items:baseline;justify-content:flex-end;font-family:var(--mono);font-size:13px;font-weight:650;white-space:nowrap}.tjs-rt>span{display:block;font-size:11.5px;color:var(--muted);white-space:nowrap}',
    '.tjs-rt .up{color:var(--up)}.tjs-rt .down{color:var(--down)}.tjs-rt .aprx{display:inline;color:var(--faint);font-weight:500}',
    '.tjs-mask{font-family:var(--mono);letter-spacing:.06em;color:var(--muted)}',
    '.tjs-go{font-size:11.5px;color:var(--faint);font-weight:700;white-space:nowrap;flex:none}',
    '.tjs-kbd{flex:none;display:grid;place-items:center;width:24px;height:22px;border-radius:6px;border:1px solid color-mix(in srgb,var(--accent) 45%,transparent);color:var(--accent)}.tjs-kbd svg{width:13px;height:13px}',
    '.tjs-rx{flex:none;width:28px;height:28px;border-radius:8px;display:grid;place-items:center;color:var(--faint);background:none;border:0;cursor:pointer}.tjs-rx svg{width:14px;height:14px}.tjs-rx:hover{color:var(--text);background:var(--surface3)}',
    '.tjs-moreq{display:flex;align-items:center;gap:10px;width:100%;padding:10px 12px;border-radius:12px;border:1px dashed var(--line2);margin-top:8px;font-size:13px;color:var(--text2);background:none;cursor:pointer;text-align:left}',
    '.tjs-moreq svg{width:16px;height:16px;color:var(--accent);flex:none}.tjs-moreq .sp{flex:1}',
    '.tjs-tip{font-size:12px;color:var(--muted);line-height:1.65;padding:10px 12px;border-radius:12px;background:var(--surface2);margin-top:12px}.tjs-tip b{color:var(--text2)}',
    '.tjs-tip code{font-family:var(--mono);font-size:11.5px;background:var(--surface3);padding:0 4px;border-radius:4px;color:var(--text2)}',
    '.tjs-none{display:flex;flex-direction:column;gap:4px;padding:28px 12px;text-align:center;color:var(--muted);font-size:13px}.tjs-none b{color:var(--text);font-size:14.5px}',
    '.tjs-exact{border-radius:14px;background:var(--surface);border:1px solid var(--line);padding:12px}.tjs-exh{font-size:14px;font-weight:700;margin-bottom:8px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
    '.tjs-acts{display:flex;flex-wrap:wrap;gap:6px}',
    '.tjs-pv0{display:flex;flex-direction:column;align-items:center;gap:6px;text-align:center;color:var(--muted);font-size:12.5px;padding:60px 12px}.tjs-pv0 svg{width:28px;height:28px;color:var(--accent);opacity:.8}.tjs-pv0 b{color:var(--text2);font-size:14px}',
    '.tjs-pt{display:flex;align-items:center;gap:10px}.tjs-pt>div{min-width:0}.tjs-pt b{display:block;font-size:17px;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.tjs-pt span{font-size:12px;color:var(--muted)}',
    '.tjs-big{font-size:26px;font-weight:800;letter-spacing:-.03em;font-variant-numeric:tabular-nums;margin-top:12px}',
    '.tjs-kvs{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:12px}.tjs-kvs>div{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:8px 10px;min-width:0}',
    '.tjs-kvs span{font-size:11.5px;color:var(--muted);display:block;font-weight:600}.tjs-kvs b{font-size:14px;font-variant-numeric:tabular-nums;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
    '.tjs-kvs .up{color:var(--up)}.tjs-kvs .down{color:var(--down)}',
    '.tjs-chs{margin-top:10px;display:flex;flex-wrap:wrap;gap:4px}',
    '.tjs-pvsub{margin-top:12px;font-size:13px;color:var(--text2);line-height:1.6}.tjs-pvrt{margin-top:8px}.tjs-pvrt .tjs-rt{text-align:left;max-width:none}.tjs-pvrt .tjs-rt b{font-size:18px}',
    '.tjs-pacts{display:flex;flex-direction:column;gap:6px;margin-top:16px}',
    '.tjs-pa{display:flex;align-items:center;gap:8px;padding:9px 10px;border-radius:10px;background:var(--surface);border:1px solid var(--line);font-size:13px;font-weight:650;color:var(--text2);cursor:pointer;text-align:left;text-decoration:none}',
    '.tjs-pa small{font-size:11px;color:var(--faint);font-weight:600}.tjs-pa .sp{flex:1}.tjs-pa:hover{border-color:var(--line2);color:var(--text)}',
    '.tjs-pa.pri{background:var(--accentBg);border-color:transparent;color:var(--accent)}',
    '.tjs-keys{display:flex;gap:14px;align-items:center;padding:9px 16px;border-top:1px solid var(--line);font-size:12px;color:var(--muted);background:var(--surface)}',
    '.tjs-keys span{display:inline-flex;gap:5px;align-items:center;white-space:nowrap}.tjs-keys .sp{flex:1}',
    '.tjs-spin{width:12px;height:12px;border-radius:50%;border:2px solid var(--line2);border-top-color:var(--accent);display:inline-block;animation:tjsSpin .8s linear infinite;vertical-align:-2px}',
    '@keyframes tjsSpin{to{transform:rotate(360deg)}}',
    '.tjs-spill{display:inline-flex;align-items:center;gap:8px;height:36px;padding:0 8px 0 11px;border-radius:10px;border:1px solid var(--line2);background:var(--surface);color:var(--muted);font:inherit;font-size:13.5px;font-weight:600;white-space:nowrap;min-width:132px;cursor:pointer;flex:none;transition:border-color .15s,color .15s}',
    '.tjs-spill:hover{border-color:var(--accent);color:var(--text)}.tjs-spill svg{width:16px;height:16px}.tjs-spill .sp{flex:1}',
    '@media (max-width:1360px){.tjs-spill{min-width:0}.tjs-spill .t,.tjs-spill .sp{display:none}}',
    '@media (max-width:1100px){.tjs-spill{display:none}}',
    '.m-top .srchb{color:var(--text)}',
    '@media (max-width:440px){.m-top .logo .ltx{display:none}}',
    '.tjs-back{display:flex;align-items:center;gap:8px;padding:6px 6px 6px 12px;border-radius:10px;background:var(--accentBg);color:var(--accent);font-size:13px;font-weight:700;min-width:0;animation:tjsFade .2s var(--ease)}',
    '.tjs-back>svg{width:15px;height:15px;flex:none}.tjs-back .tjs-bt{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}.tjs-back .sp{flex:1;min-width:6px}',
    '.tjs-back button{background:none;border:0;color:var(--accent);font:inherit;font-weight:750;cursor:pointer;padding:4px 6px;white-space:nowrap}.tjs-back button.x{color:var(--muted);display:grid;place-items:center}.tjs-back button.x svg{width:14px;height:14px}',
    '@media (max-width:640px){',
    '  .tjs-box{left:0;top:0;transform:none;width:100%;height:100%;max-height:none;border-radius:0;border:0;animation:tjsUp .22s var(--ease)}',
    '  @keyframes tjsUp{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:none}}',
    '  .tjs-head{padding:max(10px,env(safe-area-inset-top)) 14px 8px;border-bottom:0}',
    '  .tjs-body{grid-template-columns:1fr}.tjs-pv{display:none}',
    '  .tjs-list{padding:0 14px calc(24px + env(safe-area-inset-bottom))}',
    '  .tjs-r{padding:10px 6px;min-height:52px}',
    '  .tjs-keys{display:none}',
    '  .tjs-chip{height:34px}',
    '}',
    '@media (prefers-reduced-motion:reduce){.tjs-box,.tjs-dim,.tjs-back{animation:none}}'
  ].join('\n');

  function watchSig() {
    const a = API();
    if (!a || !a.S) return '';
    const S = a.S, P9 = S.parts;
    const parts = P9 ? (P9.done ? 'done' : Object.keys(P9.have || {}).filter(k => P9.have[k]).sort().join(',')) : '';
    return [S.hide, S.rand, S.cur, S.ver, (S.nft && S.nft.at) || 0, (S.oa && S.oa.at) || 0, parts].join('|');
  }
  function boot() {
    if (!API()) { setTimeout(boot, 50); return; }
    addCss();
    mountHeader();
    document.addEventListener('click', onClick, true);
    window.addEventListener('keydown', onKey, true);
    window.addEventListener('hashchange', () => { if (onHash()) return; if (ST.back && backEl && ++ST.back.hc > 1) hideBack(); }, true);
    window.addEventListener('popstate', ev => { if (ST.open && ST.pushed) { ST.pushed = false; close(true); } });
    const ih = String((API() && API().initHash) || '');
    if (ih.indexOf('#search=') === 0) { try { history.replaceState(null, '', location.pathname + location.search + ih); } catch (e) {  } onHash(); }
    let sig = '';
    setInterval(() => {
      pvGuard();
      if (ST.pend && !locked()) { const p9 = ST.pend; ST.pend = null; open(p9.q, p9.scope); return; }
      if (!ST.open) return;
      const a = API();
      const s9 = watchSig();
      if (s9 !== sig) { const pvc = sig && sig.split('|').slice(0, 2).join('|') !== s9.split('|').slice(0, 2).join('|'); sig = s9; paintAll(); if (pvc) srvKick(); }
    }, 700);
  }
  window.TJSearch = { open, close, lock, srvQueryOf, srvParamsOf, canonKey, _run: run, _pvGuard: pvGuard, _sig: watchSig, _runAct: runAct, _savedToggle: savedToggle, _askSave: askSave, parseQ, parseDate, parseAmt, mark, score, mergeItems, groupOf, clientItems, serverItems, removeFilter, looksAsk, askChips, effQ, _rowHTML: rowHTML, _emptyHTML: emptyHTML, _hlSafe: hlSafe, _st: ST };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
