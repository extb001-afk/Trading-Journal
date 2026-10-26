(function () {
  'use strict';
  const POLL_MS = 30000;
  const pollGap = n => (n < 3 ? POLL_MS : Math.min(300000, POLL_MS * 2 ** (n - 2)));
  const esc = TJDOM.esc;
  const money = v => (window.__tj && typeof window.__tj.moneyTxt === 'function') ? window.__tj.moneyTxt(v) : String(v == null ? '' : v);
  const H = { data: null, err: null, at: 0, open: false, pop: false, inflight: false, showAllResolved: false, knownOpen: false, incOpen: new Set(), unitsAll: false };
  const OPS = { d: null, err: null, at: 0, ask: '', askBody: '', det: new Set(), busy: false, inflight: false, scrollTo: '' };
  const bfInfo = () => { try { const f = window.TJ && window.TJ.bfInfo; return typeof f === 'function' ? f() : null; } catch (e) { return null; } };
  const bfRing = b => { const r = 5.5, c = 2 * Math.PI * r, p = Math.max(0, Math.min(100, b.pct)) / 100;
    return '<svg class="tjh-ring' + (b.stalled ? ' st' : '') + '" viewBox="0 0 14 14" width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="' + r + '" fill="none" stroke-width="2" class="bg"/><circle cx="7" cy="7" r="' + r + '" fill="none" stroke-width="2" class="fg" stroke-dasharray="' + (c * Math.max(p, 0.04)).toFixed(2) + ' ' + c.toFixed(2) + '" transform="rotate(-90 7 7)"/></svg>'; };
  const isKnown = x => !!(x && (x.known || x.acked) && x.level !== 'crit');
  const openNew = () => ((H.data && H.data.open) || []).filter(x => !isKnown(x));
  const openKnown = () => ((H.data && H.data.open) || []).filter(isKnown);
  const actTxt = t => String(t == null ? '' : t)
    .replace(/pm2 logs (tj-[a-z]+)(?:\s+--(?:err|lines\s+\d+))*/g, (a, u) => (UNIT_KO[u] || u) + ' 로그')
    .replace(/pm2 restart (tj-[a-z]+)/g, (a, u) => (UNIT_KO[u] || u) + ' 재시작')
    .replace(/pm2 monit/g, '메모리 추이');
  const LV = { ok: 0, warn: 1, crit: 2 };
  const LBL = { ok: '정상', warn: '주의', crit: '오류', get unknown() { return H.err && !H.data ? '상태 못 받음' : '감시 꺼짐·첫 점검 전'; } };
  const UNIT_KO = {
    'tj-evm': 'EVM 수집', 'tj-sol': 'Solana 수집', 'tj-bsc': 'BSC 수집', 'tj-core': '원장 처리', 'tj-web': '대시보드·시세',
    'tj-alert': '알림·감시', 'tj-review': '하루 리뷰', 'tj-ex': '업비트', 'tj-exf': '해외 거래소', system: '시스템'
  };

  const nowS = () => Date.now() / 1000;
  function ago(sec) {
    if (sec == null || !isFinite(sec)) return '—';
    sec = Math.max(0, Math.round(sec));
    if (sec < 60) return sec + '초';
    if (sec < 5400) return Math.floor(sec / 60) + '분';
    if (sec < 172800) { const mins = Math.floor(sec / 60), h = Math.floor(mins / 60), m = mins % 60; return h + '시간' + (m && h < 10 ? ' ' + m + '분' : ''); }
    return Math.floor(sec / 86400) + '일';
  }
  function hm(ts) {
    if (!ts) return '—';
    const d = new Date(ts * 1000 + 32400000), p = n => (n < 10 ? '0' : '') + n;
    return p(d.getUTCMonth() + 1) + '-' + p(d.getUTCDate()) + ' ' + p(d.getUTCHours()) + ':' + p(d.getUTCMinutes());
  }

  const LVW = (v, dflt) => (v === 'ok' || v === 'warn' || v === 'crit' || v === 'off' || v === 'unknown') ? v : dflt;
  function overall() {
    if (H.err && !H.data) return 'unknown';
    const d = H.data;
    if (!d) return 'unknown';
    return LVW(d.overall, 'unknown');
  }
  const isLocked = () => !!(H.locked || (window.TJ && typeof window.TJ.isLocked === 'function' && window.TJ.isLocked()));
  function lock() {
    H.locked = true; H.data = null; H.err = null; H.at = 0; H.pop = false; H.open = false; H.knownOpen = false; H.showAllResolved = false; H.ackBusy = false;
    OPS.d = null; OPS.err = null; OPS.ask = ''; OPS.askBody = ''; OPS.det.clear();
    const ov = document.getElementById('tjhOverlay'); if (ov) ov.remove();
    bgSync();
    document.documentElement.classList.remove('tjh-lock');
    const pp = document.getElementById('tjhPop'); if (pp) pp.remove();
    try { chrome(); } catch (e) {  }
  }
  const syn = () => (window.TJ && window.TJ.sync) || null, WG = {};
  async function load(force) {
    if (isLocked()) return;
    if (H.inflight) { if (force) H.again = true; return; }
    H.inflight = true;
    const sy = syn(), stale = sy ? sy.rd(WG) : () => false; let gone = false;
    try {
      const r = await fetch('/api/health', { cache: 'no-store' });
      if (r.status === 401 && typeof window.__tjLoginCheck === 'function' && window.__tjLoginCheck(r)) return;
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const j = await r.json();
      if (isLocked()) { H.data = null; return; }
      if (stale()) gone = true;
      else { H.data = j.health || null; H.ver = typeof j.version === 'string' ? j.version.slice(0, 40) : '';
        H.drev = Number.isInteger(j.dataRev) ? j.dataRev : null; H.err = null; H.at = Date.now(); H.fail = 0; }
    } catch (e) {
      if (stale()) gone = true;
      else { H.err = (e && e.message) || String(e); H.fail = (H.fail || 0) + 1; H.failAt = Date.now(); }
    } finally {
      H.inflight = false;
    }
    if (isLocked()) return;
    const again = H.again; H.again = false; if (again && !WG.pend) load(true);
    if (!gone) paint();
  }

  function counts() {
    const op = openNew();
    return { crit: op.filter(x => x.level === 'crit').length, warn: op.filter(x => x.level !== 'crit').length, known: openKnown().length };
  }
  function splitLabel(c) {
    return [c.crit ? LBL.crit + ' ' + c.crit : '', c.warn ? LBL.warn + ' ' + c.warn : ''].filter(Boolean).join(' · ');
  }
  function extOf(x) {
    const c = String(x.check || x.id || ''), t = String(x.title || '') + ' ' + String(x.detail || '');
    if (!/^quota:/.test(c) && !/\(외부\)/.test(t)) return null;
    return { src: /helius/i.test(c + ' ' + t) ? 'Helius' : /블록스카웃|blockscout/i.test(t) ? 'blockscout' : '' };
  }
  function partTone(lv) {
    const op = openNew().filter(x => (x.level === 'crit') === (lv === 'crit'));
    return op.length && op.every(x => extOf(x)) ? 'ext' : lv;
  }
  function btnHTML(mobile) {
    const b9 = bfInfo(), bfP = b9 ? (mobile ? bfRing(b9) : '<span class="tjh-sep" aria-hidden="true"> · </span><span class="tjh-part bf' + (b9.stalled ? ' st' : '') + '">' + bfRing(b9) + '<span class="tjh-n"><span class="bfw">과거 </span>' + b9.pct + '%' + (b9.stalled ? '<span class="bfw"> 멈춤</span>' : '') + '</span></span>') : '';
    return btnCore(mobile) + bfP;
  }
  function btnCore(mobile) {
    const o = overall(), c = counts();
    const n = c.crit + c.warn;
    const col = k => 'var(--' + ({ crit: 'danger', warn: 'warn', ext: 'ext' }[partTone(k)]) + ')';
    const dotC = n ? o : 'off';
    const shortH = () => { const part = (k, v) => '<span style="color:' + col(k) + '">' + v + '</span>';
      return '<span class="tjh-dot ' + dotC + '"></span><span class="tjh-n">' + [c.crit ? part('crit', c.crit) : '', c.warn ? part('warn', c.warn) : '', c.known ? '<span style="color:var(--muted)" title="닫은 주의">' + c.known + '</span>' : ''].filter(Boolean).join('<span style="color:var(--muted);margin:0 2px">·</span>') + '</span>'; };
    if (mobile && o !== 'unknown' && (n || c.known)) return shortH();
    if (o !== 'unknown' && (n || c.known)) {
      const part = (k, v) => '<span class="tjh-part ' + partTone(k) + '"><i></i><span class="tjh-n">' + LBL[k] + ' ' + v + '</span></span>';
      return '<span class="tjh-long">' + [c.crit ? part('crit', c.crit) : '', c.warn ? part('warn', c.warn) : '', c.known ? '<span class="tjh-part known"><i></i><span class="tjh-n">닫은 주의 ' + c.known + '</span></span>' : ''].filter(Boolean).join('<span class="tjh-sep" aria-hidden="true"> · </span>') + '</span><span class="tjh-short" aria-hidden="true">' + shortH() + '</span>';
    }
    const label = o === 'unknown' ? (mobile ? '' : H.err && !H.data ? LBL.unknown : '감시 꺼짐') : (mobile ? '' : '정상');
    return '<span class="tjh-dot ' + o + '"></span>' + (label ? '<span class="tjh-n">' + esc(label) + '</span>' : '');
  }
  function btnTitle() {
    const o = overall(), c = counts();
    const ex = lv => partTone(lv) === 'ext' ? '(외부 원인)' : '';
    const b9 = bfInfo();
    return '시스템 상태: ' + (c.crit + c.warn ? LBL[o] : c.known ? '새 문제 없음' : LBL[o]) + (c.crit ? ' · 오류 ' + c.crit + '건' + ex('crit') : '') + (c.warn ? ' · 주의 ' + c.warn + '건' + ex('warn') : '') + (c.known ? ' · 닫은 주의 ' + c.known + '건(같은 내용이면 안 띄움 · 판정은 그대로)' : '')
      + (b9 ? ' · 과거 거래 불러오는 중 ' + b9.pct + '%' + (b9.stalled ? '(멈춤)' : '') : '');
  }
  function popHTML() {
    const d = H.data;
    if (!d) return '<div class="ph"><span>' + (H.err ? '상태를 불러오지 못했어요 · ' + esc(H.err) : '불러오는 중…') + '</span></div>' + popFoot();
    const op = openNew().slice().sort((a, b) => ((b.level === 'crit') - (a.level === 'crit')) || ((extOf(b) ? 1 : 0) - (extOf(a) ? 1 : 0)));
    const kn = openKnown();
    const anyExt = op.some(x => extOf(x));
    const age = d.updatedAt ? nowS() - d.updatedAt : null;
    const head = '<div class="ph"><span>' + (d.interval || 60) + '초마다 판정 · ' + (age == null ? '—' : age < 60 ? '방금 전' : esc(ago(age)) + ' 전') + '</span>'
      + (anyExt ? '<span class="lg"><i></i>주황 = 외부 서비스 원인' + (op.some(x => !extOf(x) && x.level !== 'crit') ? ' <i class="w"></i>노랑 = 주의(내 계정·데이터)' : '(내 데이터 문제 아님)') + '</span>' : '') + '</div>';
    let prevExt = null;
    const rows = op.map((x, i) => {
      const e = extOf(x), lv = x.level === 'crit' ? 'crit' : 'warn';
      const own = /^debt:/.test(String(x.check || ''));
      const tag = e ? '<span class="ext">외부' + (e.src ? ' · ' + esc(e.src) : '') + '</span>' : own ? '<span class="own">내 계정</span>' : '<span>' + esc(UNIT_KO[x.unit] || x.unit || '') + '</span>';
      const sep = i > 0 && prevExt && !e; prevExt = !!e;
      return '<div class="tjh-row ' + lv + (e ? ' ext' : '') + (lv === 'crit' ? ' hi' : '') + (sep ? ' sep' : '') + '"><i></i><div class="rb"><div class="r1"><b>' + LBL[lv] + ' · ' + esc(money(x.title)) + '</b>' + tag + '</div>'
        + '<span class="r2" title="' + esc(money(x.detail)) + '">' + esc(money(x.detail)) + '</span>' + ackBtns(x, false) + '</div></div>';
    }).join('');
    const knH = kn.length ? '<button class="tjh-kn" data-h="known" aria-expanded="' + H.knownOpen + '"><span class="pvx">닫은 주의 ' + kn.length + '</span><span class="sp"></span><span>' + (H.knownOpen ? '접기' : '같은 내용이면 안 띄움 ›') + '</span></button>'
      + (H.knownOpen ? kn.map(x => '<div class="tjh-row kn"><i></i><div class="rb"><div class="r1"><b>' + esc(money(x.title)) + '</b><span>' + esc(knTxt(x)) + '</span></div><span class="r2" title="' + esc(money(x.detail)) + '">' + esc(money(x.detail)) + '</span>' + ackBtns(x, true) + '</div></div>').join('') : '') : '';
    const b9 = bfInfo();
    const bfH = b9 ? '<button class="tjh-bfl" data-h="full" title="과거 거래 불러오기 — 작업별 진행은 전체 상태에서">' + bfRing(b9) + '<span>과거 거래 불러오는 중 <b class="pvx">' + b9.pct + '%' + (b9.stalled ? ' · 멈춤' : '') + '</b></span><span class="sp"></span><span class="pvx">' + (b9.n ? '작업 ' + b9.n + '개 ›' : '자세히 ›') + '</span></button>' : '';
    return head + bfH + (rows || okOrUnk(false, kn.length)) + knH + tgNote() + popFoot();
  }
  function okOrUnk(panel, kn) {
    if (overall() === 'unknown') {
      const why = (H.data && H.data.note) || (H.err ? '상태를 불러오지 못했어요' : '아직 상태 점검 결과가 없어요');
      return panel ? '<div class="tjh-empty unk"><span class="tjh-dot unknown"></span><span>' + esc(LBL.unknown) + ' — 문제가 있는지 아직 알 수 없어요</span></div>'
        : '<div class="ok unk"><span class="tjh-dot unknown"></span><span>' + esc(LBL.unknown) + ' — ' + esc(why) + '</span></div>';
    }
    return panel ? '<div class="tjh-empty"><span class="tjh-dot"></span>' + (kn ? '새 문제가 없어요' : '열린 문제가 없어요') + '</div>'
      : '<div class="ok"><span class="tjh-dot"></span>' + (kn ? '새 문제가 없어요' : '열린 문제가 없어요') + '</div>';
  }
  function tgNote() {
    const t = (H.data && H.data.telegram) || null;
    return t && !t.configured ? '<div class="tjh-tgn"><span>알림 봇 미연결 — 오류가 떠도 알림이 안 가요</span><button data-h="tg">설정에서 연결 ›</button></div>' : '';
  }
  function popFoot() { return '<div class="pf"><button data-h="full">유닛별 상태 · 최근 복구 · 알림 ›</button></div>'; }
  function incHTML(x, compact, known) {
    const lv = x.level === 'crit' ? 'crit' : 'warn';
    const id = String(x.id || x.check || x.title || ''), open = (lv === 'crit' && !known) !== H.incOpen.has(id);
    const since = x.since || x.opened;
    const tgOn = !!(H.data && H.data.telegram && H.data.telegram.configured);
    const tg = x.telegram === false ? '대시보드 표시만' : x.notified ? '텔레그램 알림 보냄' : (lv === 'crit' && tgOn ? '텔레그램 대기' : '대시보드 표시만');
    const e = extOf(x), own = /^debt:/.test(String(x.check || ''));
    const badge = known ? '<span class="tjh-pill g">' + esc(knTxt(x)) + '</span>' : e ? '<span class="tjh-pill ext">외부' + (e.src ? ' · ' + esc(e.src) : '') + '</span>' : own ? '<span class="tjh-pill own">내 계정</span>' : '<span class="tjh-pill g" title="' + esc(x.unit) + '">' + esc(UNIT_KO[x.unit] || x.unit || '') + '</span>';
    const chev = '<svg class="tjh-cv" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>';
    return '<div class="tjh-inc ' + lv + (known ? ' kn' : '') + (open ? ' open' : '') + '"><button class="tjh-ih" data-h="inc" data-v="' + esc(id) + '" aria-expanded="' + open + '"><i class="tjh-lv"></i><b>' + (known ? '' : LBL[lv] + ' · ') + esc(money(x.title)) + '</b><span class="sp"></span>' + badge + chev + '</button>'
      + (open ? '<div class="tjh-ib"><div class="d">' + esc(money(x.detail)) + '</div>'
        + '<div class="m"><span>' + esc(x.unit) + '</span><span>시작 ' + esc(hm(since)) + ' · ' + esc(ago(nowS() - since)) + '째</span><span>' + esc(tg) + '</span></div>'
        + (compact ? '' : (x.action ? '<div class="act" title="' + esc(x.action) + '"><b>조치</b> · ' + esc(actTxt(x.action)) + '</div>' : ''))
        + (compact ? '' : opsLinkHTML(x)) + (compact ? '' : ackBtns(x, !!known, true)) + '</div>' : '') + '</div>';
  }
  const knTxt = x => x && x.acked ? '닫음' + (x.acked.at ? ' ' + hm(x.acked.at) : '') : (x && x.known) || '닫은 주의';
  const ACK_GOTO = { 'chainsweep:untracked': { label: '지갑 추가 ›', hash: 'settings/wallets' } };
  function ackBtns(x, known, card) {
    if (!x || x.level === 'crit') return '';
    const c9 = String(x.check || ''), g = ACK_GOTO[c9], busy = H.ackBusy ? ' disabled' : '';
    const st = card ? ' style="margin-top:8px"' : '';
    if (known && x.acked) return '<div class="tjh-acks"' + st + '><button class="link" data-h="ackUndo" data-v="' + esc(c9) + '"' + busy + '>되살리기</button></div>';
    if (known || !(x.ack && x.ack.fp)) return '';
    return '<div class="tjh-acks"' + st + '>' + (x.ackChanged ? '<span class="cap">닫은 뒤 내용이 바뀌어 다시 보여요</span>' : '')
      + '<button class="link" data-h="ack" data-v="' + esc(c9) + '" data-fp="' + esc(x.ack.fp) + '" title="같은 내용이면 화면·텔레그램에 다시 안 띄워요 — 새 코인·지갑이 생기거나 금액이 크게 늘면 다시 보여요"' + busy + '>닫기</button>'
      + (g ? '<button class="link" data-h="ackGoto" data-v="' + esc(g.hash) + '">' + esc(g.label) + '</button>' : '') + '</div>';
  }
  function ackIdleHTML() {
    const ai = ((H.data && H.data.acks) || []).filter(a => a && !a.open);
    return ai.map(a => '<div class="tjh-res"><span class="tjh-dot sm off"></span><span><b>' + esc(money(a.title)) + '</b> <span class="cap">지금은 해당 없음 · 닫음 ' + esc(hm(a.at)) + '</span></span>'
      + '<span class="w"><button class="link" data-h="ackUndo" data-v="' + esc(a.check) + '"' + (H.ackBusy ? ' disabled' : '') + '>되살리기</button></span></div>').join('');
  }
  async function ackSend(path, body) {
    const e = ext();
    if (!e || typeof e.post !== 'function' || H.ackBusy || isLocked()) return;
    H.ackBusy = true; paint();
    const sy = syn(), done = sy ? sy.wr(WG) : () => {};
    try {
      const d = await e.post(path, body, x => (x && x.msg) || '완료');
      if (d && d.health && !isLocked()) { H.data = d.health; H.at = Date.now(); }
    } finally { done(); H.ackBusy = false; if (!isLocked()) { paint(); load(true); } }
  }
  const OPS_LINK = { 'ledger:poison': 'poison', 'rebuild:pnl': 'pnl', 'ledger:decimals': 'dec' };
  const KEY_LINK = { 'key:etherscan': 'etherscan', 'key:alchemy': 'alchemy', 'key:ankr': 'ankr', 'key:helius': 'helius' };
  function opsLinkHTML(x) {
    const id9 = String(x.check || x.id || '').split('#')[0], kk = KEY_LINK[id9] || KEY_LINK[String(x.id || '')];
    if (kk) return '<div style="margin-top:8px"><button class="link" data-h="keyGoto" data-v="' + kk + '">설정에서 키 넣기 ›</button></div>';
    const k = OPS_LINK[id9] || OPS_LINK[String(x.id || '')];
    return k ? '<div style="margin-top:8px"><button class="link" data-h="opsGoto" data-v="' + k + '">정리 요청에서 처리 ›</button></div>' : '';
  }
  function inflowLine(u) {
    const rx = /쉬는 지갑 토큰 받음 확인 ((?:(?!\s·\s).)+)(\s·\s직전 확인 실패 — 곧 다시)?/;
    const parts = (u.sources || []).map(s0 => { const mm = rx.exec(String(s0.detail || '')); return mm ? esc(s0.label) + ' ' + esc(mm[1]) + (mm[2] ? ' — 직전 확인 실패, 곧 다시' : '') : ''; }).filter(Boolean);
    return parts.length ? '<div class="tjh-ifl">쉬는 지갑 토큰 받음 확인 · ' + parts.join(' · ') + '</div>' : '';
  }
  function unitsHTML() {
    const us = (H.data && H.data.units) || [];
    if (!us.length) return '<div class="tjh-bnr g">유닛 정보 없음</div>';
    const pvc = t => /[$₩]/.test(String(t || '')) ? '' : ' class="pvx"';
    const srcLv = s0 => s0.level === 'crit' ? 'crit' : s0.level === 'warn' ? 'warn' : s0.level == null ? 'off' : '';
    const othLv = o => o.level === 'off' || o.level == null || o.acked ? 'off' : o.level === 'ok' ? '' : LVW(o.level, 'off');
    const bad = u => { const lvl = u.ignored ? 'off' : LVW(u.level || 'ok', 'off'); return (lvl !== 'ok' && lvl !== 'off') || (u.sources || []).some(x => srcLv(x) === 'crit' || srcLv(x) === 'warn') || (u.other || []).some(o => othLv(o) === 'crit' || othLv(o) === 'warn'); };
    const row = (u, all) => {
      const p = u.proc;
      const ps = !p ? '—' : (p.status === 'online' ? '실행 중' : (p.status || '—'));
      const sub = [p && p.restarts ? '재시작 ' + p.restarts : '', u.lastLog ? '로그 ' + ago(nowS() - u.lastLog) + ' 전' : '', u.errors60 ? '오류 ' + u.errors60 + '/시' : ''].filter(Boolean).join(' · ');
      const lvl = u.ignored ? 'off' : LVW(u.level || 'ok', 'off');
      let okN = 0;
      const srcs = (u.sources || []).map(s0 => {
        const l = srcLv(s0);
        if (!all && !l) { okN++; return ''; }
        const st9 = s0.label + ' ' + (s0.age != null ? ago(s0.age) : String(s0.id || '').indexOf('inbox:') === 0 ? (s0.level === 'ok' ? '밀림 없음' : '밀림') : '—');
        return '<span class="tjh-src ' + l + '" title="' + esc(money(s0.detail)) + '"><span class="tjh-dot sm ' + (l || 'ok') + '"></span><span' + pvc(st9) + '>' + esc(st9) + '</span></span>';
      }).join('') + (u.other || []).map(o => { const l = othLv(o); if (!all && !l) { okN++; return ''; } const ct9 = money(o.chip || o.title); return '<span class="tjh-src ' + l + '" title="' + esc(money(o.detail)) + '"><span class="tjh-dot sm ' + (l || 'ok') + '"></span><span' + pvc(ct9) + '>' + esc(ct9) + '</span></span>'; }).join('')
        + (okN ? '<span class="tjh-src pvx"><span class="tjh-dot sm ok"></span>정상 ' + okN + '</span>' : '');
      return '<tr data-anc="unit:' + esc(u.unit) + '"><td style="width:118px"><div class="tjh-u"><span class="tjh-dot sm ' + lvl + '"></span><b>' + esc(u.unit) + '</b></div><div class="tjh-k">' + esc(UNIT_KO[u.unit] || '') + '</div></td>'
        + '<td class="lg pvx" style="width:112px">' + esc(ps) + (sub ? '<div class="cap" style="font-size:12px">' + esc(sub) + '</div>' : '') + '</td>'
        + '<td><div class="tjh-srcs">' + (srcs || '<span class="tjh-src off">추적 소스 없음</span>') + '</div>' + inflowLine(u) + '</td></tr>';
    };
    const badU = us.filter(bad), okU = us.filter(u => !bad(u));
    const list = H.unitsAll ? us.map(u => row(u, true)) : badU.map(u => row(u, false));
    const okBtn = okU.length ? '<button class="tjh-okall" data-h="units" aria-expanded="' + H.unitsAll + '"><span class="tjh-dot sm ok"></span><b class="pvx">' + (H.unitsAll ? '정상만 접기' : '정상 ' + okU.length + '개') + '</b><span class="cap ell">' + (H.unitsAll ? '문제 있는 유닛만 보기' : esc(okU.map(u => UNIT_KO[u.unit] || u.unit).join(' · '))) + '</span><span class="sp"></span><span class="pvx">' + (H.unitsAll ? '‹' : '›') + '</span></button>' : '';
    return (list.length ? '<table class="tjh-tbl"><thead><tr><th>유닛</th><th>프로세스</th><th>데이터 신선도</th></tr></thead><tbody>' + list.join('') + '</tbody></table>' : '') + okBtn;
  }
  function tgHTML() {
    const t = (H.data && H.data.telegram) || {};
    if (!t.configured) return '<div class="tjh-tg"><span class="tjh-dot off"></span><div><b>텔레그램 미연결</b><div class="cap">연결하면 오류(빨강)만 알림으로 받아요 · 주의(주황)는 이 화면에만</div></div></div>';
    const bad = t.consecFail > 0;
    return '<div class="tjh-tg"><span class="tjh-dot ' + (bad ? 'crit' : 'ok') + '"></span><div><b>텔레그램 연결됨</b><div class="cap">'
      + (bad ? '최근 발송 실패 ' + t.consecFail + '회' + (t.lastError ? ' · ' + esc(t.lastError) : '') : (t.lastOk ? '마지막 발송 ' + esc(ago(nowS() - t.lastOk)) + ' 전' : '아직 발송 없음'))
      + ' · 봇 멈춤(빨강)만 알림 · 1시간 넘게 이어지면 한 번 더 · 풀리면 한 번 · 안 풀린 문제는 하루 요약에' + (t.queued ? ' · 대기 ' + t.queued + '통' : '') + '</div></div></div>';
  }
  function resolvedHTML(limit) {
    const rs = (H.data && H.data.resolved) || [];
    if (!rs.length) return '<div class="cap">최근 7일 복구 기록 없음</div>';
    const shown = rs.slice(0, limit);
    return shown.map(x => '<div class="tjh-res"><span class="tjh-dot sm ' + (x.peak === 'crit' ? 'crit' : 'warn') + '"></span><span><b>' + esc(x.unit) + '</b> · ' + esc(money(x.title)) + '</span><span class="w">' + esc(hm(x.resolved)) + ' 복구 · ' + esc(ago((x.resolved || 0) - (x.since || x.opened || 0))) + '</span></div>').join('')
      + (rs.length > limit ? '<div style="margin-top:8px"><button class="link" data-h="moreRes">' + (rs.length - limit) + '건 더 보기</button></div>' : '');
  }
  function headerLine() {
    const d = H.data;
    if (!d) return H.err ? '상태를 불러오지 못했어요 · ' + esc(H.err) : '불러오는 중…';
    return '마지막 점검 ' + (d.updatedAt ? esc(ago(nowS() - d.updatedAt)) + ' 전' : '—') + ' · 60초마다 점검';
  }
  function bodyHTML(inSettings) {
    const d = H.data;
    let h = '';
    if (!d) return '<div class="tjh-bnr g">' + (H.err ? '상태를 불러오지 못했어요 — ' + esc(H.err) : '불러오는 중…') + '</div>';
    if (d.note) h += '<div class="tjh-bnr g">' + esc(d.note) + '</div>';
    const op = openNew(), kn = openKnown();
    const crit = op.filter(x => x.level === 'crit'), warn = op.filter(x => x.level !== 'crit');
    h += '<div class="tjh-sec"><div class="tt">열린 문제 <span class="n pvx">' + op.length + '</span>' + (op.length ? '<span class="n">· 누르면 설명·조치</span>' : '') + '</div>'
      + (op.length ? crit.concat(warn).map(x => incHTML(x, false)).join('') : okOrUnk(true, kn.length)) + '</div>';
    const ai9 = ackIdleHTML();
    if (d.ackErr) h += '<div class="tjh-bnr g">' + esc(d.ackErr) + '</div>';
    if (kn.length || ai9) h += '<div class="tjh-sec"><button class="tt tjh-kn" style="padding:0;margin-bottom:10px" data-h="known" aria-expanded="' + H.knownOpen + '">닫은 주의 <span class="n pvx">' + (kn.length || '') + (kn.length ? ' · ' : '') + '같은 내용이면 안 띄움 · 판정은 그대로</span><span class="sp"></span><span class="n pvx">' + (H.knownOpen ? '접기' : '펼치기') + '</span></button>'
      + (H.knownOpen ? kn.map(x => incHTML(x, false, true)).join('') + ai9 : '') + '</div>';
    const b9 = bfInfo();
    if (b9) h += '<div class="tjh-sec tjh-bf"><div class="tt">' + bfRing(b9) + '과거 거래 불러오기 <span class="n pvx">' + b9.pct + '%' + (b9.stalled ? ' · 멈춤' : '') + '</span></div>' + b9.html + '</div>';
    const wt = (d.watching || []).filter(x => !x.suppressed);
    const sup = (d.watching || []).filter(x => x.suppressed);
    if (wt.length || sup.length) {
      h += '<div class="tjh-sec"><div class="tt">관찰 중 <span class="n pvx">아직 지속 조건 전 · 알림 없음</span></div>'
        + wt.concat(sup).map(x => '<div class="tjh-watch"><span class="tjh-dot sm ' + (x.suppressed ? 'off' : LVW(x.level, 'off')) + '"></span><span><b>' + esc(x.unit) + '</b> · ' + esc(money(x.title)) + ' <span class="cap">' + esc(x.suppressed ? '(' + x.suppressed + ' — 원인 쪽에서 추적)' : x.detail) + '</span></span></div>').join('') + '</div>';
    }
    if (!inSettings) h += opsHTML();
    h += '<div class="tjh-sec"><div class="tt">유닛별 상태·신선도</div>' + unitsHTML() + '</div>';
    h += '<div class="tjh-sec"><div class="tt">최근 복구</div>' + resolvedHTML(H.showAllResolved ? 20 : (inSettings ? 5 : 8)) + '</div>';
    h += '<div class="tjh-sec"><div class="tt">알림</div>' + tgHTML() + '</div>';
    return h;
  }
  const ext = () => (window.TJ && window.TJ.ext) || null;
  const pvOn = () => { const e = ext(); try { return !!(e && e.pvOn && e.pvOn()); } catch (er) { return false; } };
  const usd = (v, sign) => { const e = ext(); if (e && typeof e.m === 'function') return e.m(+v || 0, { sign: !!sign }); const n = +v || 0; return (sign && n > 0 ? '+' : n < 0 ? '−' : '') + '$' + Math.abs(n).toFixed(2); };
  async function loadOps() {
    if (OPS.inflight || isLocked()) return;
    OPS.inflight = true;
    try {
      const r = await fetch('/api/ops', { cache: 'no-store' });
      if (r.status === 401 && typeof window.__tjLoginCheck === 'function' && window.__tjLoginCheck(r)) return;
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const j = await r.json();
      if (isLocked()) { OPS.d = null; return; }
      OPS.d = j && j.ok ? j : null; OPS.err = null; OPS.at = Date.now();
      if (OPS.ask && JSON.stringify(opsBody(OPS.ask, OPS.d)) !== OPS.askBody) { OPS.ask = ''; OPS.askBody = ''; }
    } catch (e) { OPS.err = (e && e.message) || String(e); } finally { OPS.inflight = false; }
    if (!isLocked() && H.open) paint();
  }
  async function opsSend(path, body) {
    const e = ext();
    if (!e || typeof e.post !== 'function' || OPS.busy) return;
    OPS.busy = true; paint();
    try {
      const d = await e.post(path, body, x => (x && x.msg) || '요청함');
      if (d && d.ops) { OPS.d = d.ops; OPS.ask = ''; OPS.askBody = ''; }
    } finally { OPS.busy = false; paint(); loadOps(); }
  }
  function opsHead(id, title, cap, tag) {
    const open = OPS.det.has(id);
    return '<button class="oh" style="width:100%;text-align:left" data-h="opsDet" data-v="' + esc(id) + '" aria-expanded="' + open + '"><b>' + esc(title) + '</b>'
      + (tag || '') + '<span class="cap pvx">' + esc(cap) + '</span><span class="sp"></span><span class="more pvx">' + (open ? '접기' : '자세히') + '</span></button>';
  }
  function opsPnl(d) {
    const p = d.pnl, ap = d.approve;
    if (!p || (!p.pending && !(ap && ap.live))) return '';
    const id = 'pnl', open = OPS.det.has(id) || OPS.ask === 'approve' || OPS.ask === 'cancel';
    const mo = (p.months || []).map(x => '<div class="r"><span class="k pvx">' + esc(x.month) + '</span><span class="v">실현 ' + esc(usd(x.before)) + ' → ' + esc(usd(x.after)) + '</span><span class="n">' + esc(usd(x.diff, true)) + '</span></div>').join('');
    const oc = (p.open_cost || []).map(x => '<div class="r"><span class="k">' + esc(x.sym || ('그룹 ' + x.group)) + '</span><span class="v">안 판 원가 ' + esc(usd(x.before)) + ' → ' + esc(usd(x.after)) + '</span><span class="n">' + esc(usd(x.diff, true)) + '</span></div>').join('');
    const more = ((p.n_months || 0) > (p.months || []).length ? '<div class="note pvx">… 외 ' + ((p.n_months || 0) - (p.months || []).length) + '달</div>' : '')
      + ((p.n_open_cost || 0) > (p.open_cost || []).length ? '<div class="note pvx">… 포지션 ' + ((p.n_open_cost || 0) - (p.open_cost || []).length) + '개 더</div>' : '');
    const nM = p.n_months || 0, nO = p.n_open_cost || 0;
    const mine = !!(ap && ap.live && ap.report_sha && p.report_sha && ap.report_sha === p.report_sha);
    const cap = mine ? '승인함 · 다음 재계산에서 같은 결과면 반영' : p.pending ? [nM ? '바뀌는 달 ' + nM : '', nO ? '포지션 원가 ' + nO : '', p.unv && (p.unv.after || 0) > (p.unv.before || 0) ? '원가미상 증가' : ''].filter(Boolean).join(' · ') || '자세히 보고 판단'
      : '승인됨 · ' + hm(ap.until) + '까지';
    let b = '<div class="ob">';
    if (p.pending) {
      b += '<div class="note">재계산이 과거 손익·안 판 포지션 원가를 바꿔 원장 교체를 멈췄어요(원장은 그대로). 아래 차이가 의도한 것(새로 받은 과거 거래·수수료 반영 등)이면 승인하세요 — <b>이 결과에만</b> 적용돼요.</div>'
        + (p.why ? '<div class="note pvx">재계산 사유: ' + esc(p.why) + '</div>' : '')
        + (p.reason ? '<div class="note">보류 사유: ' + esc(money(p.reason)) + '</div>' : '')
        + (mo || oc ? '<div class="rows">' + mo + oc + '</div>' + more : '')
        + (p.unv && (p.unv.after || 0) > (p.unv.before || 0) ? '<div class="note">원가미상 매도 ' + esc(usd(p.unv.before)) + ' → ' + esc(usd(p.unv.after)) + '</div>' : '')
        + (p.approve_note ? '<div class="note">' + esc(pvOn() ? '승인 상태 안내가 있어요(금액 보이기에서 확인)' : p.approve_note) + '</div>' : '')
        + '<div class="note pvx">보고서 ' + (p.report_sha ? esc(p.report_sha.slice(0, 12)) + '… · ' + (p.report_ok ? '보존됨' : '보존본 없음') : '없음') + ' · ' + esc(hm(p.ts)) + '</div>';
      if (mine) {
        b += '<div class="note">이 결과를 승인했어요 — 다음 자동 재계산(약 10분 안)이 같은 결과면 원장을 바꾸고, 다르면 다시 여기서 물어봐요.</div>';
      } else if (OPS.ask === 'approve') {
        b += '<div class="cf" role="group" aria-label="재계산 승인 확인"><b>이 결과를 승인할까요?</b><br>보고서 <span class="pvx">' + esc((p.report_sha || '').slice(0, 12)) + '…</span>와 <b>같은 결과</b>가 나오는 다음 재계산 1회(48시간 안)만 원장을 바꿔요. 결과가 달라지면 다시 멈추고 여기서 다시 물어봐요.'
          + '<div class="acts"><button class="btn sm pri" data-h="opsGo" data-v="approve"' + (OPS.busy ? ' disabled' : '') + '>승인</button><button class="btn sm" data-h="opsNo">취소</button></div></div>';
      } else if (p.report_sha && p.report_ok && p.approvable === false) {
        b += '<div class="note">보고서에 빠진 재료가 있어 승인할 수 없어요(원장은 그대로) — 재계산이 온전한 보고서를 만들면 다시 판단해요.</div>';
      } else if (p.report_sha && p.report_ok) {
        b += '<div class="acts"><button class="btn sm" data-h="opsAsk" data-v="approve">이 결과 승인…</button></div>';
      } else {
        b += '<div class="note">보고서가 없어 승인할 수 없어요 — 다음 자동 재계산 결과로 다시 판단해요.</div>';
      }
    }
    if (ap && ap.live) {
      b += (p.pending ? '<div class="note" style="margin-top:8px">' : '<div class="note">') + '승인 있음 · <span class="pvx">' + esc(hm(ap.until)) + '까지 · 보고서 ' + esc((ap.report_sha || '').slice(0, 12)) + '…</span></div>';
      b += OPS.ask === 'cancel'
        ? '<div class="cf"><b>승인을 취소할까요?</b> 다음 재계산은 차이가 있으면 다시 멈춰요.<div class="acts"><button class="btn sm warn" data-h="opsGo" data-v="cancel"' + (OPS.busy ? ' disabled' : '') + '>승인 취소</button><button class="btn sm" data-h="opsNo">닫기</button></div></div>'
        : '<div class="acts"><button class="btn sm" data-h="opsAsk" data-v="cancel">승인 취소…</button></div>';
    }
    b += '</div>';
    return '<div class="tjh-ops">' + opsHead(id, '재계산 승인', cap, p.pending && !mine ? ' <span class="tag w pvx">대기</span>' : ' <span class="tag ok pvx">승인됨</span>') + (open ? b : '') + '</div>';
  }
  function opsPoison(d) {
    const q = d.poison || {};
    if (!q.n) return '';
    const id = 'poison', open = OPS.det.has(id) || OPS.ask === 'poison';
    const wait = (q.items || []).filter(x => x.state !== '성공' && !x.corrupt);
    const cap = [q.waiting ? '대기 ' + q.waiting : '', q.failed ? '다시 실패 ' + q.failed : '', q.done ? '처리됨 ' + q.done : ''].filter(Boolean).join(' · ') + (q.requested ? ' · 요청 처리 중' : '');
    let b = '<div class="ob"><div class="note">수집한 기록 중 장부에 넣다 오류가 난 것은 원본 그대로 따로 보관돼요(장부에서 빠진 상태). 원인을 고친 뒤 다시 처리하면 같은 경로로 장부에 넣어요 — 또 실패하면 기록만 남고 그대로예요.</div><div class="rows">'
      + (q.items || []).slice(0, 12).map(x => '<div class="r"><span class="k pvx">' + esc(hm(x.ts)) + '</span><span class="v" title="' + esc(x.err) + '">' + esc((x.chain ? x.chain + ' · ' : '') + x.kind + (x.ref ? ' · ' + x.ref : '') + ' — ' + x.err) + '</span><span class="n pvx">' + esc(x.state) + '</span></div>').join('') + '</div>'
      + ((q.items || []).length > 12 ? '<div class="note pvx">… ' + ((q.n || 0) - 12) + '건 더 · 전체 목록: python3 tools/replay_poison.py</div>' : '');
    if (wait.length) {
      b += OPS.ask === 'poison'
        ? '<div class="cf"><b>' + wait.length + '건을 다시 처리할까요?</b> tj-core 가 다음 주기(몇 초~1분)에 하나씩 장부에 넣어요. 성공한 것은 다시 하지 않아요.<div class="acts"><button class="btn sm pri" data-h="opsGo" data-v="poison"' + (OPS.busy ? ' disabled' : '') + '>다시 처리</button><button class="btn sm" data-h="opsNo">취소</button></div></div>'
        : '<div class="acts"><button class="btn sm" data-h="opsAsk" data-v="poison">' + (wait.length === 1 ? '1건' : wait.length + '건') + ' 다시 처리…</button></div>';
    }
    b += '</div>';
    return '<div class="tjh-ops">' + opsHead(id, '격리된 기록', cap, q.waiting || q.failed ? ' <span class="tag w pvx">' + ((q.waiting || 0) + (q.failed || 0)) + '</span>' : '') + (open ? b : '') + '</div>';
  }
  function opsDec(d) {
    const z = d.decimals || {}, its = z.items || [];
    if (!its.length) return '';
    const id = 'dec', cf = its.filter(x => x.kind === 'conflict'), wt = its.filter(x => x.kind !== 'conflict');
    const open = OPS.det.has(id) || /^dec:/.test(OPS.ask);
    const cap = [cf.length ? '다름 ' + cf.length : '', wt.length ? '다음 재계산 대기 ' + wt.length : ''].filter(Boolean).join(' · ');
    const lab = { conflict: '다름', pending: '채움 대기', resolve: '해결 대기' };
    let b = '<div class="ob"><div class="note" title="저장값은 덮지 않았어요 — 지금 장부는 그대로이고, 다음 자동 재계산이 새 자리수로 다시 계산해요(손익이 바뀌면 재계산 승인에서 다시 물어봐요)">토큰 소수점 자리가 장부와 수집기 관측이 달라요 — 관측값이 맞으면 ‘관측값으로…’를 누르세요</div><div class="rows">';
    for (const x of its.slice(0, 12)) {
      const key = 'dec:' + x.aid, res = (z.results || {})[String(x.aid)];
      b += '<div class="r"><span class="k">' + esc(x.symbol || '?') + '</span><span class="v pvx">' + esc((x.chain || '') + ' · 저장 ' + (x.stored == null ? '없음' : x.stored) + ' → 관측 ' + x.seen) + (res && !res.ok ? ' · 거절: ' + esc(res.err || '') : '') + '</span><span class="n pvx">'
        + (x.kind === 'conflict' && (z.requested || []).indexOf(x.aid) < 0 ? '<button class="link" data-h="opsAsk" data-v="' + key + '">관측값으로…</button>' : esc((z.requested || []).indexOf(x.aid) >= 0 ? '요청 처리 중' : lab[x.kind] || x.kind)) + '</span></div>';
      if (OPS.ask === key) {
        b += '<div class="cf"><b>' + esc(x.symbol || '?') + ' 자리수를 ' + esc(String(x.stored)) + ' → ' + esc(String(x.seen)) + '(으)로 다시 기장할까요?</b> 지금 장부는 그대로예요. 다음 자동 재계산에서 이 자산의 수량이 새 자리수로 다시 계산돼요.'
          + '<div class="acts"><button class="btn sm pri" data-h="opsGo" data-v="' + key + '"' + (OPS.busy ? ' disabled' : '') + '>요청</button><button class="btn sm" data-h="opsNo">취소</button></div></div>';
      }
    }
    b += '</div></div>';
    return '<div class="tjh-ops">' + opsHead(id, '토큰 자리수', cap, cf.length ? ' <span class="tag w pvx">' + cf.length + '</span>' : '') + (open ? b : '') + '</div>';
  }
  function opsHTML() {
    const d = OPS.d;
    if (!d) return OPS.err ? '<div class="tjh-sec"><div class="tt">정리 요청</div><div class="tjh-opsnone">불러오지 못했어요 — ' + esc(OPS.err) + '</div></div>' : '';
    const parts = [opsPnl(d), opsPoison(d), opsDec(d)].filter(Boolean);
    const apMine = !!(d.approve && d.approve.live && d.pnl && d.approve.report_sha && d.approve.report_sha === d.pnl.report_sha);
    const n = (d.pnl && d.pnl.pending && !apMine ? 1 : 0) + ((d.poison || {}).waiting || 0) + ((d.poison || {}).failed || 0) + ((d.decimals || {}).conflicts || 0);
    return '<div class="tjh-sec"><div class="tt">정리 요청 <span class="n pvx">' + (n ? n + '건 · 확인 뒤 버튼으로' : '처리할 것 없음') + '</span></div>'
      + (parts.length ? parts.join('') : '<div class="tjh-opsnone">손으로 정리할 기록이 없어요(격리 기록 · 재계산 승인 · 자리수 다름).</div>') + '</div>';
  }
  function opsBody(v, d) {
    if (!d) return null;
    if (v === 'approve') return d.pnl && d.pnl.report_sha ? { path: '/api/ops/rebuild_approve', body: { report_sha: d.pnl.report_sha } } : null;
    if (v === 'cancel') return d.approve && d.approve.live ? { path: '/api/ops/rebuild_cancel', body: {} } : null;
    if (v === 'poison') { const ids = ((d.poison || {}).items || []).filter(x => x.state !== '성공' && !x.corrupt).map(x => x.id); return ids.length ? { path: '/api/ops/poison_replay', body: { ids } } : null; }
    if (/^dec:\d+$/.test(v)) {
      const x = ((d.decimals || {}).items || []).find(y => 'dec:' + y.aid === v && y.kind === 'conflict');
      return x ? { path: '/api/ops/decimals_resolve', body: { asset_id: x.aid, stored: x.stored, seen: x.seen } } : null;
    }
    return null;
  }
  function opsClick(a, v) {
    const d = OPS.d;
    if (a === 'opsDet') { if (OPS.det.has(v)) OPS.det.delete(v); else OPS.det.add(v); paint(); refocus('[data-h="opsDet"]', v); return; }
    if (a === 'opsAsk') { const t = opsBody(v, d); if (!t) return; OPS.ask = v; OPS.askBody = JSON.stringify(t); paint(); const b = document.querySelector('#tjhOverlay [data-h="opsGo"]'); if (b) try { b.focus({ preventScroll: false }); } catch (e) {  } return; }
    if (a === 'opsNo') { OPS.ask = ''; OPS.askBody = ''; paint(); return; }
    if (a !== 'opsGo' || v !== OPS.ask || !OPS.askBody) return;
    const t = JSON.parse(OPS.askBody);
    opsSend(t.path, t.body);
  }
  function panelHTML() {
    const o = overall();
    return '<div class="tjh-bg" data-h="close"></div><div class="tjh-panel" role="dialog" aria-modal="true" aria-labelledby="tjhTitle">'
      + '<div class="tjh-hd"><h3 id="tjhTitle">시스템 상태</h3><span class="tjh-pill ' + (counts().crit + counts().warn || !counts().known ? o : 'g') + '">' + (counts().crit + counts().warn || !counts().known ? LBL[o] : '새 문제 없음') + '</span><span class="sp" style="flex:1"></span>'
      + '<button class="iconbtn" data-h="refresh" aria-label="다시 점검 결과 불러오기" title="새로고침"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/></svg></button>'
      + '<button class="iconbtn" data-h="close" id="tjhClose" aria-label="닫기"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>'
      + '<div class="tjh-sub">' + headerLine() + '</div>' + bodyHTML(false) + '</div>';
  }
  function summary() {
    const c = counts(), o = overall();
    return { loaded: !!H.data, err: H.err || '', overall: o, crit: c.crit, warn: c.warn, known: c.known, label: c.crit + c.warn ? splitLabel(c) : c.known ? '닫은 주의 ' + c.known : LBL[o],
      ext: (c.crit + c.warn) > 0 && openNew().every(x => extOf(x)), tg: !!(H.data && H.data.telegram && H.data.telegram.configured),
      ledger: H.data && H.data.ledgerWait && typeof H.data.ledgerWait === 'object' ? H.data.ledgerWait : null, monitorOff: !!(H.data && H.data.monitorOff),
      version: H.ver || '', dataRev: H.drev };
  }

  function ensureBtn(host, before, mobile) {
    if (!host) return null;
    let b = host.querySelector(':scope > .tjh-btn');
    if (!b) {
      b = document.createElement('button');
      b.className = 'tjh-btn pvx';
      b.setAttribute('data-h', 'pop');
      b.setAttribute('aria-haspopup', 'dialog');
      host.insertBefore(b, before && before.parentNode === host ? before : null);
    }
    TJDOM.set(b, btnHTML(mobile));
    b.title = btnTitle();
    b.setAttribute('aria-label', btnTitle());
    b.setAttribute('aria-expanded', H.pop || H.open ? 'true' : 'false');
    b.setAttribute('data-h', 'pop');
    return b;
  }
  function chrome() {
    const top = document.querySelector('.top .in');
    ensureBtn(top, document.getElementById('themeBtn'), false);
    const mt = document.getElementById('mtop');
    if (mt) ensureBtn(mt, mt.querySelector('.curb') || mt.querySelector('.iconbtn[data-a="theme"]'), true);
  }
  function view(tab, el) { void tab; void el; }
  function paint() {
    chrome();
    try { window.dispatchEvent(new Event('tj:health')); } catch (e) {  }
    const ov = document.getElementById('tjhOverlay');
    document.documentElement.classList.toggle('tjh-lock', !!H.open);
    if (H.open) {
      const scrollTop = ov && ov.querySelector('.tjh-panel') ? ov.querySelector('.tjh-panel').scrollTop : 0;
      let host = ov;
      if (!host) { host = document.createElement('div'); host.id = 'tjhOverlay'; document.body.appendChild(host); }
      TJDOM.set(host, panelHTML());
      const p = host.querySelector('.tjh-panel');
      if (p) p.scrollTop = scrollTop;
      if (OPS.scrollTo) {
        const b = host.querySelector('[data-h="opsDet"][data-v="' + OPS.scrollTo + '"]');
        if (b) { OPS.scrollTo = ''; try { b.scrollIntoView({ block: 'start' }); b.focus({ preventScroll: true }); } catch (e9) {  } }
        else if (OPS.d && !OPS.inflight) OPS.scrollTo = '';
      }
    } else if (ov) {
      ov.remove();
    }
    bgSync();
    paintPop();
  }
  function bgSync() { try { const T = window.TJ; if (T && typeof T.bgInert === 'function') T.bgInert(); } catch (e) {  } }
  function paintPop() {
    let host = document.getElementById('tjhPop');
    if (!H.pop || H.open) { if (host) host.remove(); return; }
    const btn = Array.from(document.querySelectorAll('.tjh-btn')).find(b => b.offsetParent);
    if (!host) { host = document.createElement('div'); host.id = 'tjhPop'; document.body.appendChild(host); }
    const mob = window.matchMedia && window.matchMedia('(max-width:640px)').matches;
    TJDOM.set(host, (mob ? '<div class="tjh-pbg" data-h="popClose"></div>' : '') + '<div class="tjh-pop" role="dialog" aria-label="상태 상세">' + popHTML() + '</div>');
    const p = host.querySelector('.tjh-pop');
    if (btn && p && !mob) { const r = btn.getBoundingClientRect(); p.style.top = Math.round(r.bottom + 6) + 'px'; p.style.right = Math.max(12, Math.round(window.innerWidth - r.right)) + 'px'; }
  }
  function togglePop(force) {
    if (isLocked()) { H.pop = false; paintPop(); return; }
    H.pop = force != null ? !!force : !H.pop;
    paint();
    if (H.pop) load();
  }
  function openPanel() {
    if (isLocked()) return;
    H.open = true;
    paint();
    const c = document.getElementById('tjhClose');
    if (c) c.focus();
    load();
    loadOps();
  }
  function closePanel() {
    H.open = false;
    paint();
    const b = document.querySelector('.tjh-btn');
    if (b && b.offsetParent) b.focus();
  }

  document.addEventListener('click', ev => {
    const el = ev.target.closest('[data-h]');
    if (!el) return;
    const a = el.getAttribute('data-h');
    if (a === 'open') { ev.preventDefault(); H.pop = false; openPanel(); }
    else if (a === 'pop') { ev.preventDefault(); togglePop(); }
    else if (a === 'popClose') togglePop(false);
    else if (a === 'full') { H.pop = false; openPanel(); }
    else if (a === 'close') closePanel();
    else if (a === 'refresh') { load(); loadOps(); }
    else if (a === 'moreRes') { H.showAllResolved = true; paint(); }
    else if (a === 'known') { ev.preventDefault(); H.knownOpen = !H.knownOpen; paint(); }
    else if (a === 'ack') { ev.preventDefault(); ackSend('/api/health/ack', { check: el.getAttribute('data-v') || '', fp: el.getAttribute('data-fp') || '' }); }
    else if (a === 'ackUndo') { ev.preventDefault(); ackSend('/api/health/restore', { check: el.getAttribute('data-v') || '' }); }
    else if (a === 'ackGoto') { ev.preventDefault(); H.pop = false; H.open = false; paint(); try { location.hash = el.getAttribute('data-v') || 'settings/wallets'; } catch (e) {  } }
    else if (a === 'inc') { ev.preventDefault(); const v = el.getAttribute('data-v') || ''; if (H.incOpen.has(v)) H.incOpen.delete(v); else H.incOpen.add(v); paint(); refocus('[data-h="inc"]', v); }
    else if (a === 'units') { ev.preventDefault(); H.unitsAll = !H.unitsAll; paint(); refocus('[data-h="units"]', null); }
    else if (a === 'opsDet' || a === 'opsAsk' || a === 'opsNo' || a === 'opsGo') { ev.preventDefault(); opsClick(a, el.getAttribute('data-v') || ''); }
    else if (a === 'opsGoto') {
      ev.preventDefault(); const v = el.getAttribute('data-v') || ''; OPS.det.add(v); H.pop = false;
      if (!H.open) openPanel(); else { paint(); loadOps(); }
      OPS.scrollTo = v; paint();
    }
    else if (a === 'keyGoto') {
      ev.preventDefault(); H.pop = false; H.open = false; paint();
      try {
        const su = window.__tjSetup, k = el.getAttribute('data-v') || '';
        if (su && su.U) su.U.xp = k;
        if (location.hash === '#settings/keys') { if (su && typeof su.render === 'function') su.render(); }
        else location.hash = 'settings/keys';
      } catch (e) {  }
    }
    else if (a === 'tg') {
      ev.preventDefault(); H.pop = false; H.open = false; paint();
      try {
        const su = window.__tjSetup;
        if (su && su.U) { su.U.panelOpen = true; su.U.where = 'telegram'; }
        location.hash = 'settings/keys/telegram';
      } catch (e) {  }
    }
  });
  document.addEventListener('keydown', ev => {
    if (ev.key === 'Escape' && H.open && OPS.ask) { ev.stopPropagation(); OPS.ask = ''; OPS.askBody = ''; paint(); }
    else if (ev.key === 'Escape' && H.open) { ev.stopPropagation(); closePanel(); }
    else if (ev.key === 'Escape' && H.pop) { ev.stopPropagation(); togglePop(false); const b = Array.from(document.querySelectorAll('.tjh-btn')).find(x => x.offsetParent); if (b) b.focus(); }
  }, true);
  document.addEventListener('pointerdown', ev => { if (H.pop && !ev.target.closest('.tjh-pop') && !ev.target.closest('.tjh-btn')) togglePop(false); }, true);
  window.addEventListener('resize', () => { if (H.pop) paintPop(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden && Date.now() - H.at > POLL_MS) load(); });
  const pollDue = () => Date.now() - (H.failAt || 0) >= pollGap(H.fail || 0) - 1000;
  setInterval(() => { if (!document.hidden && pollDue()) { load(); if (H.open) loadOps(); } }, POLL_MS);
  setInterval(() => { const s = document.querySelector('#tjhOverlay .tjh-sub'); if (s && !document.hidden) TJDOM.set(s, headerLine()); }, 15000);

  function refocus(sel, v) { const b = Array.from(document.querySelectorAll('#tjhOverlay ' + sel + ', #tjhCard ' + sel + ', #tjhPop ' + sel)).find(x => v == null || x.getAttribute('data-v') === v); if (b) { try { b.focus({ preventScroll: true }); } catch (e) {  } } }
  window.TJHealth = { chrome: chrome, view: view, summary: summary, open: openPanel, close: closePanel, pop: togglePop, reload: load, lock: lock, _state: H, repaint: () => paint() };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => { chrome(); load(); });
  else { chrome(); load(); }
})();
