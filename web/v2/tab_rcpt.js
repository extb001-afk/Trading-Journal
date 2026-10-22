'use strict';
(window.__tjTabs = window.__tjTabs || {}).rcpt = function (X) {
  const {
    $, arr, cls, clsV, csrf, dayContrib, dmRcptHTML, DOWS, dpFade, drawerHist, errTxt, esc, evTxt, EX_NAMES, exLogo, fmtTs, futSym, IC, icon, isAI,
    isISO, KV, m, mN, nf, num, onUnauthorized, pad2, pctS, PV_RE, PVM, pvOn, pvW, px, q, qXf, rate, rcptable, renderOverlay, revTxt, RS_RE, rw, S,
    sum, term, uiFold, uiOpen, uiPaged
  } = X;
  function openReceipt(iso, sym, rank) {
    if (!S.D || !isISO(iso) || !sym) return;
    const key = iso + '|' + sym, C = S.rcptC || (S.rcptC = {}), c = C[key];
    const first = S.drawer !== 'rcpt';
    S.drawer = 'rcpt'; S.pop = null; S.modal = null;
    const ae = document.activeElement, back = first ? (ae && ae.getAttribute && ae.getAttribute('data-a') ? { el: ae, a: ae.getAttribute('data-a'), v: ae.getAttribute('data-v') } : null) : (S.rcpt && S.rcpt.back);
    S.rcpt = { iso, sym, key, rank: +rank || 0, aiOpen: false, back };
    if (first) drawerHist();
    if (!c || c.st === 'err' || (c.st === 'ok' && c.at !== S.D.builtAt)) {
      const at = S.D.builtAt;
      C[key] = { st: 'load', at, d: c && c.d };
      fetch('/api/receipt?date=' + iso + '&sym=' + encodeURIComponent(sym), { cache: 'no-store' })
        .then(r => { if (r.status === 401) { onUnauthorized(); throw new Error('401'); } if (r.status === 404) { const e = new Error('old'); e.old = true; throw e; } return r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status)); })
        .then(d => { if (!d || !d.ok) throw new Error('bad'); C[key] = { st: 'ok', at, d }; })
        .catch(e => { C[key] = { st: 'err', at: 0, old: !!e.old, d: C[key] && C[key].d }; })
        .then(() => { if (S.drawer === 'rcpt' && S.rcpt && S.rcpt.key === key) renderOverlay(); });
    }
    rcLoad();
    renderOverlay();
    if (first) { const b = $('#overlay .drawer [data-a="drawerClose"]'); if (b) b.focus(); }
  }
  function topRcptSym(iso) { const x = dayContrib(iso).filter(rcptable)[0]; return x ? x.sym : null; }
  const durTxt = s => { const mn = Math.max(0, Math.round(s / 60)); if (mn < 60) return mn + '분'; if (mn < 1440) return Math.floor(mn / 60) + '시간' + (mn % 60 ? ' ' + (mn % 60) + '분' : ''); const d = Math.floor(mn / 1440), h = Math.floor((mn % 1440) / 60); return d + '일' + (h ? ' ' + h + '시간' : ''); };
  const kstHM = ts => { const x = new Date((ts + 32400) * 1000); return pad2(x.getUTCHours()) + ':' + pad2(x.getUTCMinutes()); };
  const shortK = k => ({ '온체인 매수': '스왑', 'LP 전환 매수': 'LP 전환', '거래소 매수': '거래소' }[k] || term(k));
  const RC_TRIES = 20, RC_POLLS = 100;
  const RK_SHORT_S = 6 * 3600, RK_FOLD_S = 3 * 3600;
  const RC_IVS = [['5m', '5분봉'], ['1m', '1분봉']], RC_AFTERS = [['1h', '1시간'], ['6h', '6시간'], ['24h', '24시간']];
  const RC_IVK = { '1m': '1분봉', '5m': '5분봉', '1h': '1시간봉' }, RC_AFK = { '1h': '1시간', '6h': '6시간', '24h': '24시간' };
  const rcV = R => R.cv || (R.cv = { iv: '5m', after: '1h', venue: '', bvenue: '' });
  const rcK = R => { const v = rcV(R); return R.key + '|' + v.iv + '|' + v.after + '|' + v.venue; };
  const rcEK = R => R.iso + '|' + (R.csym || R.sym);
  const rcBK = R => { const v = rcV(R); return R.key + '|' + v.iv + '|' + v.venue + '|' + (v.bvenue || ''); };
  const rcSK = (R, side) => rcEK(R) + (side === 'buy' ? '|buy' : '');
  const rcDefView = R => { const v = rcV(R); return v.iv === '5m' && v.after === '1h' && !v.venue && !v.bvenue; };
  const rcFbTxt = t => t && t.why === 'deferred' ? ' 봉 대신 ' : ' 봉 없음 → ';
  const rcLaterTxt = w => w === 'deferred' ? '오늘 몫 소진 — DEX 봉은 나중에 채움' : 'DEX 봉을 지금 못 받아 나중에 채움';
  function rcAuto(R, side) {
    if (!R || !rcOn(R) || !rcDefView(R)) return;
    const c = side === 'buy' ? (S.rcptB || {})[rcBK(R)] : (S.rcptX || {})[rcK(R)];
    const x = c && c.st === 'ok' ? c.d : null;
    if (!x || !x.autoEval || !x.evalFp || x.empty) return;
    if (S.D && S.D.reviewPause && S.D.reviewPause.on) return;
    const k = rcSK(R, side), e = (S.rcptE || {})[k];
    if (!e || e.st !== 'ready') return;
    const ev = e.ev, bd = e.budget;
    if (ev && ev.fp === x.evalFp && !ev.old) return;
    if (bd && bd.left != null && num(bd.left) <= 0) return;
    const A = S.rcAutoDone || (S.rcAutoDone = new Set()), ak = k + '|' + x.evalFp;
    if (A.has(ak)) return;
    A.add(ak);
    rcEvalPost(!!(ev && ev.fp === x.evalFp && ev.old), 0, side, true);
  }
  const rcOn = R => S.drawer === 'rcpt' && S.rcpt && S.rcpt.key === R.key;
  async function postJ(path, body) {
    let r, d;
    for (let n = 0; n < 2; n++) {
      const tok = await csrf(n > 0), hd = { 'Content-Type': 'application/json' };
      if (tok) hd['X-TJ-CSRF'] = tok;
      r = await fetch(path, { method: 'POST', headers: hd, body: JSON.stringify(body) });
      if (r.status === 401) { onUnauthorized(); return { st: 401, d: null }; }
      try { d = await r.json(); } catch (e) { d = null; }
      if (!(r.status === 403 && d && /CSRF/.test(d.error || ''))) break;
    }
    return { st: r.status, d };
  }
  function rcLoad(force) {
    const R = S.rcpt; if (!R || !S.D) return;
    const k = rcK(R), C = S.rcptX || (S.rcptX = {}), c = C[k];
    if (!force && c && (c.st === 'load' || c.st === 'prep' || c.st === 'old' || (c.st === 'ok' && c.at === S.D.builtAt))) { if (c.st === 'ok') { rcEvalLoad(R); if (c.d && c.d.buySide) rcbLoad(); rcPrefetch(R); } return; }
    const gen = (S.rcGen = (S.rcGen || 0) + 1);
    C[k] = { st: 'load', gen, at: S.D.builtAt, n: 0, d: c && c.d };
    rcFetch(R, k, Object.assign({}, rcV(R)), gen, 0);
  }
  function rcPrefetch(R) {
    if (!R || !rcOn(R) || R.preOff || !S.D) return;
    const v = rcV(R); if (v.iv !== '5m' || v.after !== '1h') return;
    const X = S.rcptX || (S.rcptX = {}), Bc = S.rcptB || (S.rcptB = {}), x = X[rcK(R)] || {}, b = Bc[rcBK(R)] || {};
    if (x.st !== 'ok' || !x.d || (x.d.buySide && b.st !== 'ok' && b.st !== 'err' && b.st !== 'old')) return;
    const P = S.rcPre, pc = P && (P.side === 'buy' ? Bc : X)[P.k];
    if (pc && pc.gen === P.gen && (pc.st === 'load' || pc.st === 'prep')) return;
    const cands = [];
    arr(x.d.venues).slice(0, 3).forEach((o, i) => { const vv = i ? String((o && o.key) || '') : ''; const k = R.key + '|5m|1h|' + vv; if (vv !== v.venue && (!i || vv) && !X[k]) cands.push({ side: 'sell', k, cv: { iv: '5m', after: '1h', venue: vv, bvenue: '' } }); });
    if (b.st === 'ok' && b.d) arr(b.d.venues).slice(0, 3).forEach((o, i) => { const bv = i ? String((o && o.key) || '') : ''; const k = R.key + '|5m|' + v.venue + '|' + bv; if (bv !== (v.bvenue || '') && (!i || bv) && !Bc[k]) cands.push({ side: 'buy', k, cv: { iv: '5m', after: '1h', venue: v.venue, bvenue: bv } }); });
    const c = cands[0]; if (!c) return;
    const buy = c.side === 'buy', C = buy ? Bc : X, gen = buy ? (S.rcbGen = (S.rcbGen || 0) + 1) : (S.rcGen = (S.rcGen || 0) + 1);
    C[c.k] = { st: 'load', gen, at: S.D.builtAt, n: 0, pre: true };
    S.rcPre = { side: c.side, k: c.k, gen };
    (buy ? rcbFetch : rcFetch)(R, c.k, c.cv, gen, 0);
  }
  function rcFetch(R, k, v, gen, n) {
    const C = S.rcptX, live = () => !!C[k] && C[k].gen === gen, pre = !!(C[k] && C[k].pre);
    const url = '/api/receipt_chart?date=' + R.iso + '&sym=' + encodeURIComponent(R.csym || R.sym) + '&iv=' + v.iv + '&after=' + v.after + (v.venue ? '&venue=' + encodeURIComponent(v.venue) : '');
    fetch(url, { cache: 'no-store' })
      .then(r => {
        if (r.status === 401) { onUnauthorized(); throw new Error('로그인이 필요해요'); }
        if (r.status === 404) { const e = new Error('old'); e.old = true; throw e; }
        return r.json().catch(() => null).then(d => {
          if ((r.status === 202 && d && d.ok) || r.status === 503) return { prep: d || {}, idx: r.status === 503 };
          if (!r.ok || !d || !d.ok) throw new Error((d && d.error) || ('HTTP ' + r.status));
          return { d };
        });
      })
      .then(x => {
        if (!live()) return;
        if (x.prep) {
          if (pre && x.prep.status === 'busy' && !(S.rcpt && rcK(S.rcpt) === k)) { delete C[k]; R.preOff = true; return; }
          if (n + 1 >= RC_TRIES) { C[k] = { st: 'err', gen, at: 0, msg: '시세를 1분 넘게 받는 중이에요 — 잠시 뒤 다시 눌러 주세요', d: C[k].d }; return; }
          C[k] = Object.assign({}, C[k], { st: 'prep', n: n + 1, busy: x.prep.status === 'busy', idx: !!x.idx });
          const wait = Math.min(10, Math.max(1, num(x.prep.retryAfter) || 3)) * 1000;
          setTimeout(() => {
            if (!live()) return;
            if (!rcOn(R)) { delete C[k]; return; }
            rcFetch(S.rcpt, k, v, gen, n + 1);
          }, wait);
          return;
        }
        C[k] = { st: 'ok', gen, at: C[k].at, d: x.d };
        const Rn = S.rcpt;
        if (rcOn(R)) {
          if (x.d.sym) Rn.csym = x.d.sym;
          if (x.d.evalFp) (S.rcFp || (S.rcFp = {}))[x.d.evalFp] = { iv: x.d.iv, after: x.d.after, venue: x.d.venue };
          if (rcK(Rn) === k) {
            Rn.lastK = k;
            rcEvalLoad(Rn);
            rcAuto(Rn);
            if (x.d.buySide) rcbLoad();
          }
        }
      })
      .catch(e => { if (live()) C[k] = { st: e && e.old ? 'old' : 'err', gen, at: 0, msg: e && e.old ? '' : String((e && e.message) || e), d: C[k].d }; })
      .then(() => { if (S.drawer === 'rcpt' && S.rcpt && rcK(S.rcpt) === k) renderOverlay(); if (pre || (S.rcpt && rcK(S.rcpt) === k)) rcPrefetch(S.rcpt); });
  }
  function rcbLoad(force) {
    const R = S.rcpt; if (!R || !S.D) return;
    const k = rcBK(R), C = S.rcptB || (S.rcptB = {}), c = C[k];
    if (!force && c && (c.st === 'load' || c.st === 'prep' || c.st === 'old' || (c.st === 'ok' && c.at === S.D.builtAt))) { if (c.st === 'ok') { rcEvalLoad(R, false, 'buy'); rcPrefetch(R); } return; }
    const gen = (S.rcbGen = (S.rcbGen || 0) + 1);
    C[k] = { st: 'load', gen, at: S.D.builtAt, n: 0, d: c && c.d };
    rcbFetch(R, k, Object.assign({}, rcV(R)), gen, 0);
  }
  function rcbFetch(R, k, v, gen, n) {
    const C = S.rcptB, live = () => !!C[k] && C[k].gen === gen, pre = !!(C[k] && C[k].pre);
    const url = '/api/receipt_chart?side=buy&date=' + R.iso + '&sym=' + encodeURIComponent(R.csym || R.sym) + '&iv=' + v.iv + (v.venue ? '&venue=' + encodeURIComponent(v.venue) : '') + (v.bvenue ? '&bvenue=' + encodeURIComponent(v.bvenue) : '');
    fetch(url, { cache: 'no-store' })
      .then(r => {
        if (r.status === 401) { onUnauthorized(); throw new Error('로그인이 필요해요'); }
        if (r.status === 404) { const e = new Error('old'); e.old = true; throw e; }
        return r.json().catch(() => null).then(d => {
          if ((r.status === 202 && d && d.ok) || r.status === 503) return { prep: d || {} };
          if (!r.ok || !d || !d.ok) throw new Error((d && d.error) || ('HTTP ' + r.status));
          if (d.side !== 'buy') { const e = new Error('old'); e.old = true; throw e; }
          return { d };
        });
      })
      .then(x => {
        if (!live()) return;
        if (x.prep) {
          if (pre && x.prep.status === 'busy' && !(S.rcpt && rcBK(S.rcpt) === k)) { delete C[k]; R.preOff = true; return; }
          if (n + 1 >= RC_TRIES) { C[k] = { st: 'err', gen, at: 0, msg: '매수 쪽 시세를 1분 넘게 받는 중이에요', d: C[k].d }; return; }
          C[k] = Object.assign({}, C[k], { st: 'prep', n: n + 1 });
          setTimeout(() => {
            if (!live()) return;
            if (!rcOn(R)) { delete C[k]; return; }
            rcbFetch(S.rcpt, k, v, gen, n + 1);
          }, Math.min(10, Math.max(1, num(x.prep.retryAfter) || 3)) * 1000);
          return;
        }
        C[k] = { st: 'ok', gen, at: C[k].at, d: x.d };
        if (rcOn(R)) {
          if (x.d.evalFp) (S.rcFpB || (S.rcFpB = {}))[x.d.evalFp] = { iv: x.d.iv };
          if (rcBK(S.rcpt) === k) {
            S.rcpt.lastBK = k;
            rcEvalLoad(S.rcpt, false, 'buy');
            rcAuto(S.rcpt, 'buy');
          }
        }
      })
      .catch(e => { if (live()) C[k] = { st: e && e.old ? 'old' : 'err', gen, at: 0, msg: e && e.old ? '' : String((e && e.message) || e), d: C[k].d }; })
      .then(() => { if (S.drawer === 'rcpt' && S.rcpt && rcBK(S.rcpt) === k) renderOverlay(); if (pre || (S.rcpt && rcBK(S.rcpt) === k)) rcPrefetch(S.rcpt); });
  }
  function rcEvalLoad(R, force, side) {
    const k = rcSK(R, side), E = S.rcptE || (S.rcptE = {}), e = E[k];
    if (!force && e && e.st !== 'idle') return;
    E[k] = Object.assign({}, e || {}, { st: e && e.st === 'running' ? 'running' : 'load' });
    rcEvalGet(R, k, 0, side);
  }
  function rcEvalGet(R, k, n, side) {
    const E = S.rcptE;
    fetch('/api/receipt_eval?date=' + R.iso + '&sym=' + encodeURIComponent(R.csym || R.sym) + (side === 'buy' ? '&side=buy' : ''), { cache: 'no-store' })
      .then(r => { if (r.status === 401) { onUnauthorized(); throw new Error('401'); } if (r.status === 404) { const e = new Error('old'); e.old = true; throw e; } return r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status)); })
      .then(j => {
        const e = E[k] || {}, run = j.status === 'running';
        E[k] = { st: run ? 'running' : 'ready', ev: j.eval || null, budget: j.budget || e.budget || null,
          msg: j.status === 'error' ? { t: '지난 평가를 만들지 못했어요 — ' + (j.error || '오류'), c: 'e' } : run ? null : e.msg };
        if (!run) { if (j.status !== 'error' && S.rcpt && rcSK(S.rcpt, side) === k) setTimeout(() => rcAuto(S.rcpt, side), 0); return; }
        if (n + 1 >= RC_POLLS) { E[k].st = 'ready'; E[k].msg = { t: '평가가 오래 걸려요 — 잠시 뒤 서랍을 다시 열어 보세요', c: 'w' }; return; }
        setTimeout(() => { if (S.drawer === 'rcpt' && S.rcpt && rcSK(S.rcpt, side) === k) rcEvalGet(S.rcpt, k, n + 1, side); else if (E[k]) E[k].st = 'idle'; }, 3000);
      })
      .catch(e => { E[k] = Object.assign({}, E[k], { st: e && e.old ? 'old' : 'ready', msg: e && e.old ? null : { t: '평가 상태를 불러오지 못했어요', c: 'e' } }); })
      .then(() => { if (S.drawer === 'rcpt' && S.rcpt && rcSK(S.rcpt, side) === k) renderOverlay(); });
  }
  async function rcEvalPost(force, tries, side, auto, v0) {
    const R = S.rcpt; if (!R || !rcOn(R)) return;
    const v = v0 || Object.assign({}, rcV(R)), k = rcSK(R, side), E = S.rcptE || (S.rcptE = {});
    if (E[k] && (E[k].st === 'post' || E[k].st === 'running') && !tries) return;
    E[k] = Object.assign({}, E[k], { st: 'post', msg: null });
    renderOverlay();
    const body = { date: R.iso, sym: R.csym || R.sym, iv: v.iv, after: v.after, force: !!force };
    if (auto) body.auto = true;
    if (v.venue) body.venue = v.venue;
    if (side === 'buy') { body.side = 'buy'; if (v.bvenue) body.bvenue = v.bvenue; }
    const sideKo = side === 'buy' ? '매수' : '매도';
    let x;
    try { x = await postJ('/api/receipt_eval', body); } catch (e) { x = { st: 0, d: null }; }
    const j = x.d || {}, e0 = E[k] || {}, set = o => { E[k] = Object.assign({}, e0, o); };
    const later = (fn, ms) => {
      const pending = E[k];
      setTimeout(() => {
        if (E[k] !== pending) return;
        if (rcOn(R) && S.rcpt === R && rcSK(R, side) === k) fn();
        else {
          E[k] = Object.assign({}, pending, { st: 'idle', msg: null });
          if (rcOn(R)) renderOverlay();
        }
      }, ms);
    };
    if (x.st === 401) { set({ st: 'ready' }); }
    else if (x.st === 202 && j.status === 'running') { set({ st: 'running', msg: null }); later(() => rcEvalGet(R, k, 0, side), 3000); }
    else if (x.st === 202) {
      if ((tries || 0) + 1 >= 10) set({ st: 'ready', msg: { t: '차트를 아직 준비하는 중이에요 — 잠시 뒤 다시 눌러 주세요', c: 'w' } });
      else {
        set({ st: 'post', msg: { t: '차트를 준비하는 중 — 곧 이어서 평가해요', c: '' } });
        later(() => {
          const c = rcV(R);
          if (['iv', 'after', 'venue', 'bvenue'].every(f => (c[f] || '') === (v[f] || ''))) rcEvalPost(force, (tries || 0) + 1, side, auto, v);
          else { E[k] = Object.assign({}, E[k], { st: 'idle', msg: null }); renderOverlay(); }
        }, Math.min(10, Math.max(1, num(j.retryAfter) || 3)) * 1000);
      }
    }
    else if (x.st === 200 && j.eval) set({ st: 'ready', ev: j.eval, msg: j.cached ? { t: '같은 입력으로 만든 평가가 있어 그대로 보여 줘요(한도 차감 없음)', c: '' } : null });
    else if (x.st === 409) set({ st: 'ready', msg: { t: j.error || '다른 ' + sideKo + ' 평가가 진행 중이에요 — 끝나면 다시 눌러 주세요', c: 'w' } });
    else if (x.st === 429) set({ st: 'ready', budget: Object.assign({}, e0.budget || {}, { left: 0 }), msg: { t: j.error || '오늘 AI ' + sideKo + ' 평가 한도를 다 썼어요', c: 'w' } });
    else if (x.st === 422) set({ st: 'ready', msg: { t: '차트(봉)가 없어 평가할 수 없어요', c: 'w' } });
    else set({ st: 'ready', msg: { t: 'AI 평가를 시작하지 못했어요 · ' + (j.error || (x.st ? 'HTTP ' + x.st : '연결 실패')), c: 'e' } });
    if (S.drawer === 'rcpt' && S.rcpt && rcSK(S.rcpt, side) === k) renderOverlay();
  }
  function rcTicks(a, b, n) {
    const span = b - a; if (!(span > 0)) return [a];
    const raw = span / n, p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p;
    const st = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p;
    const out = []; for (let v = Math.ceil(a / st) * st; v <= b + st * 1e-9; v += st) out.push(+v.toPrecision(12));
    return out;
  }
  function rcBin(cs, maxN) {
    if (cs.length <= maxN) return { cs, k: 1 };
    const k = Math.ceil(cs.length / maxN), out = [];
    for (let i = 0; i < cs.length; i += k) { const g = cs.slice(i, i + k); out.push([g[0][0], g[0][1], Math.max.apply(null, g.map(c => c[2])), Math.min.apply(null, g.map(c => c[3])), g[g.length - 1][4], sum(g, c => c[5])]); }
    return { cs: out, k };
  }
  const rkTw = (s0, fs) => Array.from(String(s0).replace(PV_RE, '$1').replace(RS_RE, '$1')).reduce((a0, ch0) => a0 + (/[ㄱ-힝]/.test(ch0) ? fs : /[0-9]/.test(ch0) ? fs * 0.6 : ch0 === ' ' ? fs * 0.3 : fs * 0.5), 0);
  function rkFit(occ, cands, x0, x1, obs, pad) {
    pad = pad == null ? 2 : pad;
    const hit = (b, list) => list.some(o => b[0] < o[2] + pad && o[0] < b[2] + pad && b[1] < o[3] + pad && o[1] < b[3] + pad);
    for (const c of cands) {
      if (!(c.x >= x0 - 0.01 && c.x + c.w <= x1 + 0.01)) continue;
      const b = [c.x, c.y, c.x + c.w, c.y + c.h];
      if (hit(b, occ) || (obs && hit(b, obs))) continue;
      occ.push(b);
      return c;
    }
    return null;
  }
  function rkHiPill(hx, hy, labs, occ, hard, soft, x0, x1, yMax) {
    for (const obs of [hard.concat(soft), hard]) for (const lab of labs) {
      const tw0 = Array.from(String(lab).replace(PV_RE, '$1').replace(RS_RE, '$1')).reduce((a0, ch0) => a0 + (/[ㄱ-힝]/.test(ch0) ? 11.5 : 7), 0) + 14;
      const cx0 = v => Math.max(x0, Math.min(x1 - tw0, v)), xC = cx0(hx - tw0 / 2), xR = cx0(hx + 8), xL = cx0(hx - tw0 - 8);
      const rows = [[Math.max(2, hy - 26), [xC, xR, xL]], [hy - 9.5, [xR, xL]], [hy + 8, [xC, xR, xL]]];
      const cands = [];
      rows.forEach(([y, xs]) => { if (y < 2 || y + 19 > yMax) return; xs.forEach((x, i) => { if (xs.findIndex(u => Math.abs(u - x) < 0.5) === i) cands.push({ x, y, w: tw0, h: 19, lab }); }); });
      const c = rkFit(occ, cands, x0, x1, obs);
      if (c) return c;
    }
    return null;
  }
  const rkHiSvg = (c, hx, hy, full) => '<g class="him">' + (c ? '<rect x="' + c.x.toFixed(1) + '" y="' + c.y.toFixed(1) + '" width="' + c.w.toFixed(1) + '" height="19" rx="6"/><text x="' + (c.x + 7).toFixed(1) + '" y="' + (c.y + 13.5).toFixed(1) + '">' + esc(c.lab) + '</text>' : '')
    + '<circle cx="' + hx.toFixed(1) + '" cy="' + hy.toFixed(1) + '" r="2.6">' + (c && c.lab === full ? '' : '<title>' + esc(full) + '</title>') + '</circle></g>';
  function rkWhat(R, side) {
    const v = rcV(R), buy = side === 'buy', c0 = ((buy ? S.rcptB : S.rcptX) || {})[buy ? R.lastBK : R.lastK], vs = c0 && c0.d ? arr(c0.d.venues) : [];
    const cur = buy ? v.bvenue : v.venue, o = vs.find(z => z && z.key === cur) || (!cur && vs[0]) || null;
    return (buy ? '매수 ' : '') + (o && o.label ? o.label + ' ' : '') + (RC_IVK[v.iv] || '') + (!buy && v.after !== '1h' ? ' · 판 뒤 ' + (RC_AFK[v.after] || '') : '');
  }
  const rkRe = t => '<div class="rkre" aria-hidden="true"><i class="spin"></i>' + t + '</div>';
  function rkSkel(R, msg) {
    const v = rcV(R), X = (S.rcptX || {})[R.lastK] || {}, Bq = (S.rcptB || {})[R.lastBK] || {};
    const xs = X.d ? arr(X.d.venues) : [], bs = Bq.d ? arr(Bq.d.venues) : [], combo = !!(X.d && X.d.buySide);
    const segB = (a, list, cur0, lab) => '<div class="seg rkseg" role="group" aria-label="' + lab + '">' + list.map(o => '<button data-a="' + a + '" data-v="' + o[0] + '" class="' + (cur0 === o[0] ? 'on' : '') + '" aria-pressed="' + (cur0 === o[0]) + '">' + (a === 'rcAfter' && !S.mobile && o[0] === '1h' ? '판 뒤 ' : '') + o[1] + '</button>').join('') + '</div>';
    const chips = (list, cur0, act, lab) => list.length > 1 ? '<div class="rkvn" role="group" aria-label="' + lab + '"><span class="cap rkvl">' + lab.split(' —')[0] + '</span>' + list.map(o => { const on = o.key === (cur0 || list[0].key); return '<button class="chip' + (on ? ' on' : '') + '" data-a="' + act + '" data-v="' + esc(o.key) + '" aria-pressed="' + on + '">' + esc(o.label) + ' <span class="mut num">' + (o.sharePct != null ? nf('ko-KR', 0, 0).format(num(o.sharePct)) + '% · ' : '') + num(o.n) + '회</span></button>'; }).join('') + '</div>' : '';
    const H = 30 + (S.mobile ? 210 : 270) + 8 + (S.mobile ? 40 : 52) + 22;
    const head = '<div class="row rtth rkh"><span class="rtt">실제 시세 위 내 ' + (combo ? '매수·매도' : '매도') + ' — 점 크기 = 금액</span><span class="sp"></span>' + segB('rcIv', RC_IVS, v.iv, '봉 간격') + segB('rcAfter', RC_AFTERS, v.after, '판 뒤 구간') + '</div>';
    const tile = '<div class="rkt rkskt" aria-hidden="true" style="min-height:' + (S.mobile ? 105 : 112) + 'px"><span class="l"><i></i></span><b class="num"><i></i></b><span class="s"><i></i><i></i></span></div>';
    const bars = n => Array.from({ length: n }, () => '<i></i>').join('');
    const aiH = uiOpen('rk:ai', true) ? (combo ? (S.mobile ? 660 : 433) : (S.mobile ? 330 : 220)) : 0;
    return '<section class="rsec rkc rksks" aria-busy="true">' + head + chips(xs, v.venue, 'rcVenue', '매도 장소 — 장소마다 그 시장 봉') + chips(bs, v.bvenue, 'rcBVenue', '매수 장소 — 매수 구간 봉 출처')
      + '<div class="rkleg cap rkskl" aria-hidden="true">' + bars(combo ? (S.mobile ? 5 : 3) : 1) + '</div><div class="rscw rkw rksk"><div class="rkskb" style="height:' + H + 'px" aria-hidden="true"><i></i></div>'
      + '<div class="rkov"><span class="rkwait" role="status" aria-live="polite"><i class="spin" aria-hidden="true"></i>' + msg + '</span></div></div><div class="rksrc cap rkskl" aria-hidden="true">' + bars(combo ? (S.mobile ? 5 : 3) : 1) + '</div></section>'
      + '<div class="rk4' + (combo ? ' rk4m' : '') + ' rkskq" aria-hidden="true">' + tile + tile + tile + tile + '</div><div class="rkskf" aria-hidden="true">' + (combo ? '<i class="a"></i>' : '') + (aiH ? '<i style="height:' + aiH + 'px"></i>' : '<i></i>') + '</div>';
  }
  function rkSection(R, d, cx) {
    const v = rcV(R), C = S.rcptX || {}, c = C[rcK(R)] || {};
    const loading = c.st === 'load' || c.st === 'prep';
    const x = c.st === 'ok' ? c.d : loading && c.d ? c.d : null;
    const tries = c.n ? ' <span class="mut">(' + c.n + '번째 확인)</span>' : '';
    const waitTxt = c.idx ? '기록 색인을 만드는 중 — 잠시 뒤 다시 확인해요' : c.busy ? '다른 차트를 먼저 받는 중 — 차례를 기다려요' : esc(rkWhat(R)) + ' 시세 받는 중…';
    const prog = loading ? rkRe('새로 받는 중' + tries) : '';
    if (!x) {
      if (loading) return { ok: true, html: rkSkel(R, waitTxt + tries) };
      if (c.st === 'old') return { ok: false, html: '' };
      if (c.st === 'err') return { ok: false, html: '<div class="rkwhy cap" role="status">실제 시세를 받지 못해 체결 점만 보여 줘요 · ' + esc(errTxt(c.msg || '오류')) + ' <button class="link" data-a="rcRetry">다시 받기</button></div>' };
      return { ok: false, html: '' };
    }
    const ch = x.chart || {}, cs0 = arr(ch.candles).filter(r => Array.isArray(r) && r.length >= 6 && isFinite(r[2]) && isFinite(r[3]));
    const fills = arr(x.fills).filter(f => f && f.ts && num(f.px) > 0);
    const sNo = x.empty || !ch.ok || !cs0.length || !fills.length;
    const bc = (S.rcptB || {})[rcBK(R)] || {}, bLoad = bc.st === 'load' || bc.st === 'prep';
    const bx = bc.st === 'ok' ? bc.d : bLoad && bc.d ? bc.d : null;
    const Rk = d.tax && d.tax.dispKrw != null && num(d.tax.disp) > 0 ? d.tax.dispKrw / d.tax.disp : rate();
    const bNote = !x.buySide ? '' : bLoad ? '<div class="rkbw cap" role="status"><i class="spin" aria-hidden="true"></i> 매수 타점 받는 중…</div>'
      : bc.st === 'err' ? '<div class="rkbw cap" role="status">매수 타점을 받지 못했어요 · ' + esc(errTxt(bc.msg || '오류')) + ' <button class="link" data-a="rcRetryB">다시 받기</button></div>'
      : bc.st === 'ok' && bx && (sNo || !rkComboOk(bx, x)) ? '<div class="rkbw cap" role="status">매수 타점을 차트에 올리지 못했어요 · ' + esc(bx.why || (bx.chart || {}).why || (sNo ? '매도 시세를 받지 못했어요' : bx.cur !== x.cur ? '통화가 달라요' : '매수 봉 없음'))
        + (arr(bx.inflows).length ? '<br>' + arr(bx.inflows).slice(0, 6).map(f => esc(kstHM(f.ts) + ' 입금 ' + (f.chain ? f.chain + ' ' : '') + q(num(f.q)) + '개' + (num(f.px) > 0 ? ' · 원가 단가 ' + cx.P(num(f.px) * ((bx.cur === 'KRW') === (S.cur !== 'USD') ? 1 : bx.cur === 'KRW' ? 1 / Rk : Rk)) : '') + (f.rule ? ' · ' + f.rule : ''))).join('<br>') : '') + '</div>' : '';
    if (sNo) {
      const why = x.why || ch.why || (x.empty ? '그날 매도 기록이 없어요' : '봉을 받지 못했어요');
      return { ok: false, html: '<div class="rkwhy cap" role="status" title="' + esc(arr(ch.tried).map(t => t.label + ': ' + (t.note || t.why)).join('\n')) + '">실제 시세를 받지 못해 체결 점만 보여 줘요 · ' + esc(why) + ' <button class="link" data-a="rcRetry">다시 받기</button></div>' + bNote };
    }
    if (x.buySide && !bx && (bLoad || !bc.st)) return { ok: true, html: rkSkel(R, esc(rkWhat(R, 'buy')) + ' 시세 받는 중…' + (bc.n ? ' <span class="mut">(' + bc.n + '번째 확인)</span>' : '')) };
    if (bx && rkComboOk(bx, x)) return rkCombo(R, d, cx, x, bx, loading || bLoad, prog || (bLoad ? rkRe('매수 새로 받는 중') : ''));
    const { P, M, uc, sym, dt } = cx;
    const dc = S.cur === 'USD' ? 'USD' : 'KRW', xc = x.cur === 'KRW' ? 'KRW' : x.cur === 'USD' ? 'USD' : dc;
    const fk = xc === dc ? 1 : xc === 'KRW' ? 1 / Rk : Rk;
    const sm = x.summary || {}, src = ch.src || {}, w = x.window || {};
    const ivS = { '1m': 60, '5m': 300, '1h': 3600 }[src.iv] || 300;
    const avg = num(sm.avgPx) * fk, hi = num(sm.hi) * fk, lo = num(sm.lo) * fk;
    const Wd = Math.round(Math.max(300, Math.min(756, S.mobile ? (window.innerWidth || 390) - 34 : 756)));
    const PH = S.mobile ? 210 : 270, VH = S.mobile ? 40 : 52, GAP = 8, AX = 22, T = 30, Lp = 8, Rp = 10;
    const H = T + PH + GAP + VH + AX;
    const t0 = num(w.from) || cs0[0][0], t1 = (num(w.to) || cs0[cs0.length - 1][0]) + ivS;
    const inView = cs0.filter(r => r[0] + ivS > t0 && r[0] < t1);
    const bn = rcBin(inView.length ? inView : cs0, Math.floor((Wd - Lp - Rp) / 2.5)), cs = bn.cs, bS = ivS * bn.k;
    const X = t => Lp + (t - t0) / (t1 - t0) * (Wd - Lp - Rp);
    const ys = [];
    cs.forEach(r => { ys.push(r[2] * fk, r[3] * fk); });
    fills.forEach(f => ys.push(num(f.px) * fk));
    if (avg > 0) ys.push(avg);
    let y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
    const rng0 = (y1 - y0) || y1 * 0.05 || 1;
    const ucIn = uc > 0 && uc >= y0 - rng0 * 0.6 && uc <= y1 + rng0 * 0.6;
    if (ucIn) { y0 = Math.min(y0, uc); y1 = Math.max(y1, uc); }
    const pad = (y1 - y0) * 0.07 || y1 * 0.05 || 1; y0 = Math.max(0, y0 - pad); y1 += pad;
    const Y = p => T + (1 - (p - y0) / (y1 - y0)) * PH;
    const vmax = Math.max.apply(null, cs.map(r => num(r[5]))) || 1, VB = T + PH + GAP + VH;
    const bw = Math.max(1, Math.min(9, 0.68 * (Wd - Lp - Rp) * bS / (t1 - t0)));
    const sp = sm.spike && sm.spike.from ? sm.spike : null;
    const inSp = t => sp && t >= sp.from && t < sp.to;
    const sellTo = num(w.sellTo) || Math.max.apply(null, fills.map(f => f.ts));
    const yt = rcTicks(y0, y1, S.mobile ? 3 : 4).filter(p => Y(p) > T + 8 && Y(p) < T + PH - 4);
    const grid = yt.map(p => '<line x1="' + Lp + '" x2="' + (Wd - Rp) + '" y1="' + Y(p).toFixed(1) + '" y2="' + Y(p).toFixed(1) + '" class="gl"/><text x="' + (Lp + 4) + '" y="' + (Y(p) - 4).toFixed(1) + '" class="tk">' + esc(P(p)) + '</text>').join('');
    const stp = [5, 10, 15, 30, 60, 120, 180, 360, 720, 1440].find(s0 => (t1 - t0) / 60 / s0 <= (S.mobile ? 4 : 7)) || 1440;
    const xt = []; for (let t = Math.ceil((t0 + 32400) / (stp * 60)) * stp * 60 - 32400; t <= t1; t += stp * 60) xt.push(t);
    const xax = xt.map((t, i) => '<text x="' + X(t).toFixed(1) + '" y="' + (H - 6) + '" text-anchor="' + (X(t) < 24 ? 'start' : X(t) > Wd - 24 ? 'end' : 'middle') + '" class="tk">' + kstHM(t) + '</text>').join('');
    const af = (sm.after || {})[v.after] || (sm.after || {})[x.after] || null;
    const sx = Math.max(Lp, Math.min(Wd - Rp, X(sellTo)));
    const afLab = '판 뒤 ' + (RC_AFK[x.after] || RC_AFK[v.after] || '') + (af ? ' 최저 ' + pctS(af.loPct, 1) + (num(af.hiPct) > 0.05 ? ' · 최고 ' + pctS(af.hiPct, 1) : '') : '');
    const shade = '<rect x="' + sx.toFixed(1) + '" y="' + (T - 22) + '" width="' + Math.max(0, Wd - Rp - sx).toFixed(1) + '" height="' + (PH + 22 + GAP + VH) + '" class="aft"/><line x1="' + sx.toFixed(1) + '" x2="' + sx.toFixed(1) + '" y1="' + (T - 22) + '" y2="' + VB + '" class="aftl"/>'
      + '<text x="' + (Wd - Rp - 6) + '" y="' + (T - 8) + '" text-anchor="end" class="aftt">' + esc(afLab) + '</text>';
    const cbx = [];
    const candles = cs.map(r => {
      const xm = X(r[0] + bS / 2), o = r[1] * fk, h = r[2] * fk, l = r[3] * fk, cl = r[4] * fk, up = cl >= o, yo = Y(Math.max(o, cl)), yc = Y(Math.min(o, cl));
      const vh = num(r[5]) / vmax * VH;
      cbx.push([xm - Math.max(1, bw / 2), Y(h), xm + Math.max(1, bw / 2), Y(l)]);
      return '<g class="' + (up ? 'cu' : 'cd') + '"><line x1="' + xm.toFixed(1) + '" x2="' + xm.toFixed(1) + '" y1="' + Y(h).toFixed(1) + '" y2="' + Y(l).toFixed(1) + '"/><rect x="' + (xm - bw / 2).toFixed(1) + '" y="' + yo.toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + Math.max(1, yc - yo).toFixed(1) + '"/>'
        + '<rect class="vb' + (inSp(r[0]) ? ' sp' : '') + '" x="' + (xm - bw / 2).toFixed(1) + '" y="' + (VB - vh).toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + Math.max(0.5, vh).toFixed(1) + '"/>'
        + '<title>' + esc(kstHM(r[0]) + (bn.k > 1 ? ' (' + bn.k + '봉 묶음)' : '') + ' · 시 ' + P(o) + ' · 고 ' + P(h) + ' · 저 ' + P(l) + ' · 종 ' + P(cl) + ' · 거래량 ' + (ch.volUnit === 'usd' ? M(num(r[5]) * (dc === 'USD' ? 1 : Rk), { raw: true }) : q(num(r[5]), true) + ' ' + sym)) + '</title></g>';
    }).join('');
    const spBar = sp ? '<line x1="' + X(sp.from).toFixed(1) + '" x2="' + X(sp.to).toFixed(1) + '" y1="' + (VB + 3) + '" y2="' + (VB + 3) + '" class="spl"/>' : '';
    const hl = (p, c0, dash) => p > 0 ? '<line x1="' + Lp + '" x2="' + (Wd - Rp) + '" y1="' + Y(p).toFixed(1) + '" y2="' + Y(p).toFixed(1) + '" class="' + c0 + '"' + (dash ? ' stroke-dasharray="4 4"' : '') + '/>' : '';
    const ucOut = uc > 0 && !ucIn ? '<text x="' + (Lp + 4) + '" y="' + (T + PH - 4) + '" class="ucx">평단 ' + esc(P(uc)) + ' ↓ (아래)</text>' : '';
    let hiMk = '';
    if (hi > 0 && sm.hiTs) {
      const hx = X(num(sm.hiTs) + ivS / 2), hy = Y(hi), lab = '구간 고가 ' + P(hi) + ' ' + kstHM(num(sm.hiTs));
      const afR = Wd - Rp - 6, occ = [[afR - rkTw(afLab, 11) - 2, T - 20, afR + 1, T - 4]];
      const c9 = rkHiPill(hx, hy, [lab, '고가 ' + P(hi)], occ, [], cbx, Lp + 2, Wd - Rp - 2, T + PH);
      hiMk = rkHiSvg(c9, hx, hy, lab);
    }
    const amx = Math.max.apply(null, fills.map(f => num(f.amt))) || 1;
    const dots = fills.slice().sort((a, b) => num(b.amt) - num(a.amt)).map(f => {
      const p = num(f.px) * fk, a = num(f.amt) * fk, r0 = 3.5 + (S.mobile ? 10 : 14) * Math.sqrt(num(f.amt) / amx);
      return '<circle cx="' + X(f.ts).toFixed(1) + '" cy="' + Y(p).toFixed(1) + '" r="' + r0.toFixed(1) + '" class="sd"><title>' + esc(kstHM(f.ts) + ' 매도 · ' + P(p) + ' · ' + q(num(f.q)) + ' ' + sym + ' · ' + M(a)) + '</title></circle>';
    }).join('');
    const posTxt = sm.posPct != null ? '저가에서 ' + nf('ko-KR', 1, 1).format(num(sm.posPct)) + '%' : '';
    const aria = (dt.getMonth() + 1) + '월 ' + dt.getDate() + '일 ' + sym + ' ' + (src.label || '') + ' ' + (RC_IVK[src.iv] || '') + ' ' + inView.length + '개 위에 내 매도 ' + fills.length + '회'
      + (posTxt ? ' · 평균 매도가 위치 ' + posTxt : '') + (sm.fromHighPct != null ? ' · 고점 대비 ' + pctS(sm.fromHighPct, 1) : '') + (af ? ' · ' + afLab : '');
    const svg = '<svg class="rsc rkg cmb" width="' + Wd + '" height="' + H + '" viewBox="0 0 ' + Wd + ' ' + H + '" role="img" aria-label="' + esc(aria) + '">'
      + shade + grid + '<line x1="' + Lp + '" x2="' + (Wd - Rp) + '" y1="' + VB + '" y2="' + VB + '" class="gl"/>' + candles + spBar + hl(uc && ucIn ? uc : 0, 'ucl', true) + hl(avg, 'avl', false) + ucOut + dots + hiMk + xax + '</svg>';
    const segB = (a, list, cur0, lab) => '<div class="seg rkseg" role="group" aria-label="' + lab + '">' + list.map(o => '<button data-a="' + a + '" data-v="' + o[0] + '" class="' + (cur0 === o[0] ? 'on' : '') + '" aria-pressed="' + (cur0 === o[0]) + '">' + (a === 'rcAfter' && !S.mobile && o[0] === '1h' ? '판 뒤 ' : '') + o[1] + '</button>').join('') + '</div>';
    const vns = arr(x.venues);
    const vchips = vns.length > 1 ? '<div class="rkvn" role="group" aria-label="매도 장소 — 장소마다 그 시장 봉">' + vns.map(o => { const on = o.key === x.venue; return '<button class="chip' + (on ? ' on' : '') + '" data-a="rcVenue" data-v="' + esc(o.key) + '" aria-pressed="' + on + '">' + esc(o.label) + ' <span class="mut num">' + (o.sharePct != null ? nf('ko-KR', 0, 0).format(num(o.sharePct)) + '% · ' : '') + num(o.n) + '회</span></button>'; }).join('') + '</div>' : '';
    const leg = '<div class="rkleg cap"><span><i class="lg sdr" aria-hidden="true"></i>내 매도</span>' + (avg > 0 ? '<span><i class="lg avlr" aria-hidden="true"></i>평균 매도 <b class="num">' + P(avg) + '</b></span>' : '')
      + (uc > 0 ? '<span><i class="lg ucl" aria-hidden="true"></i>평단 <b class="num">' + P(uc) + '</b></span>' : '') + '<span><i class="lg aft" aria-hidden="true"></i>판 뒤 ' + (RC_AFK[x.after] || '') + '</span>' + (sp ? '<span><i class="lg spl" aria-hidden="true"></i>거래량 급증</span>' : '') + '</div>';
    const tr = arr(ch.tried), ivTxt = RC_IVK[src.iv] || src.iv || '';
    let srcTxt = (src.fallback && tr.length ? tr[0].label + rcFbTxt(tr[0]) : '') + (src.label || '') + ' ' + ivTxt;
    if (src.fx) srcTxt += src.fx.mode === 'KRW→USD' ? '(달러 환산)' : '(원화 환산)';
    if (x.dexLater) srcTxt += ' · ' + rcLaterTxt(x.dexLater);
    if (src.iv && src.iv !== x.iv) srcTxt += ' · ' + (RC_IVK[x.iv] || x.iv) + '이 없어 저해상도';
    if (src.venue === 'dex' && src.poolMatched === false) srcTxt += ' · 내 거래 풀과 다른 풀일 수 있어요';
    if (bn.k > 1) srcTxt += ' · ' + bn.k + '봉씩 묶어 그림';
    if (fk !== 1) srcTxt += ' · ' + (dc === 'USD' ? '달러' : '원화') + ' 환산(그날 매도 환율 ₩' + nf('ko-KR', 0, 0).format(Rk) + ')';
    const openTxt = sm.firstFromOpenMin != null && num(sm.firstFromOpenMin) >= 0 ? '거래 시작 ' + durTxt(num(sm.firstFromOpenMin) * 60) + ' 뒤 첫 매도' : '';
    const srcLine = '<div class="rksrc cap"><span title="' + esc(tr.length ? '시도: ' + tr.map(t => t.label + ' — ' + (t.note || t.why)).join('\n') : '') + '">' + esc(srcTxt) + '</span>' + (openTxt ? '<span class="sp"></span><span>' + esc(openTxt) + '</span>' : '') + '</div>';
    const head = '<div class="row rtth rkh"><span class="rtt">실제 시세 위 내 매도 — 점 크기 = 금액</span><span class="sp"></span>' + segB('rcIv', RC_IVS, v.iv, '봉 간격') + segB('rcAfter', RC_AFTERS, v.after, '판 뒤 구간') + '</div>';
    const pc = (vv, dd) => vv == null || !isFinite(vv) ? '—' : pctS(vv, dd == null ? 1 : dd);
    const a1 = (sm.after || {})['1h'], a6 = (sm.after || {})['6h'], a24 = (sm.after || {})['24h'];
    const tile = (l, vh, s, c0, tt) => '<div class="rkt"' + (tt ? ' title="' + esc(tt) + '"' : '') + '><span class="l">' + l + '</span><b class="num ' + (c0 || '') + '">' + vh + '</b><span class="s num">' + s + '</span></div>';
    const t1x = sm.posPct != null ? tile('평균 매도가 위치', esc(posTxt) + '<span class="rkbar" aria-hidden="true"><i style="left:' + Math.max(0, Math.min(100, num(sm.posPct))).toFixed(1) + '%"></i></span>',
      '구간 저가 ' + P(lo) + ' ~ 고가 ' + P(hi), '', '0% = 구간(첫 매도 1시간 전 ~ 마지막 매도 1시간 뒤) 저가 · 100% = 고가' + (sm.vsVwapPct != null ? ' · 매도 기간 시장 평균가 대비 ' + pctS(sm.vsVwapPct, 1) : '') + (sm.volPctile != null ? ' · 그 구간 거래량의 ' + nf('ko-KR', 0, 1).format(num(sm.volPctile)) + '%가 내 평균가 이하에서 거래' : ''))
      : tile('평균 매도가 위치', '—', '구간 봉 없음');
    const t2x = tile('고점 대비', pc(sm.fromHighPct), '평균 ' + P(avg) + ' vs 고가 ' + P(hi), sm.fromHighPct != null && num(sm.fromHighPct) < 0 ? 'down' : '');
    const t3x = a1 ? tile('판 뒤 1시간 최저', pc(a1.loPct), (num(a1.hiPct) > 0.05 ? '최고 ' + pc(a1.hiPct) + ' · ' : '') + (a6 || a24 ? [a6 ? '6시간 ' + pc(a6.loPct) : '', a24 ? '24시간 ' + pc(a24.loPct) : ''].filter(Boolean).join(' · ') : '6시간·24시간은 위 \'판 뒤\'에서'),
      num(a1.loPct) < 0 ? 'okc' : '', '마지막 매도 뒤 구간의 최저·최고·종가를 내 평균 매도가와 비교' + [['1시간', a1], ['6시간', a6], ['24시간', a24]].filter(z => z[1]).map(z => ' · ' + z[0] + ' 최저 ' + pc(z[1].loPct) + ' 최고 ' + pc(z[1].hiPct) + ' 종가 ' + pc(z[1].closePct)).join(''))
      : tile('판 뒤 1시간', '—', '그 뒤 봉 없음');
    const t4x = sp ? tile('거래량 급증 때 매도', nf('ko-KR', 0, 1).format(num(sp.sharePct)) + '%', kstHM(sp.from) + '~' + kstHM(sp.to) + ' 물량 비중', 'wc', '거래량 급증 = 구간 봉 거래량 중앙값 2배 이상 · 상위 20%' + (sp.volSharePct != null ? ' · 그 구간이 시장 거래량의 ' + nf('ko-KR', 0, 1).format(num(sp.volSharePct)) + '%' : '') + (sp.allSpikeSharePct != null ? ' · 급증 봉 전체에서 판 비중 ' + nf('ko-KR', 0, 1).format(num(sp.allSpikeSharePct)) + '%' : ''))
      : tile('거래량 급증 때 매도', '—', '뚜렷한 급증 구간 없음');
    const tiles = '<div class="rk4">' + t1x + t2x + t3x + t4x + '</div>';
    const busy = loading ? ' aria-busy="true"' : '';
    const html = '<section class="rsec rkc"' + busy + '>' + head + vchips + leg
      + '<div class="rscw rkw">' + prog + svg + '</div>' + srcLine + bNote + '</section>' + tiles + rkAiFold(R, [{ side: 'sell', x, box: rkEvalBox(R, x, cx, loading) }]);
    return { ok: true, html };
  }
  function rkComboOk(b, x) {
    return !!(b && b.side === 'buy' && b.ok && !b.empty && arr(b.fills).some(f => f && f.ts && num(f.px) > 0) && b.cur === x.cur
      && arr(b.segs).some(sg => sg && sg.ok && arr(sg.candles).length));
  }
  function rkCombo(R, d, cx, x, b, loading, prog) {
    const v = rcV(R), { P, M, uc, sym, dt } = cx;
    const ch = x.chart || {}, src = ch.src || {}, w = x.window || {}, sm = x.summary || {}, bsm = b.summary || {};
    const dc = S.cur === 'USD' ? 'USD' : 'KRW', xc = x.cur === 'KRW' ? 'KRW' : x.cur === 'USD' ? 'USD' : dc;
    const Rk = d.tax && d.tax.dispKrw != null && num(d.tax.disp) > 0 ? d.tax.dispKrw / d.tax.disp : rate();
    const fk = xc === dc ? 1 : xc === 'KRW' ? 1 / Rk : Rk;
    const IVS = { '1m': 60, '5m': 300, '1h': 3600 }, ivS = IVS[src.iv] || 300;
    const okc = r => Array.isArray(r) && r.length >= 6 && isFinite(r[2]) && isFinite(r[3]);
    const sCs = arr(ch.candles).filter(okc).sort((a0, b0) => a0[0] - b0[0]);
    const sFrom = num(w.from) || sCs[0][0], sTo = (num(w.to) || sCs[sCs.length - 1][0]) + ivS;
    const bnd = sCs.length ? Math.max(sFrom, sCs[0][0]) : sFrom;
    const parts = [];
    arr(b.segs).forEach(sg => {
      const cs = arr(sg.candles).filter(okc).filter(c => c[6] !== 2).sort((a0, b0) => a0[0] - b0[0]); if (!sg.ok || !cs.length) return;
      const gIv = IVS[(sg.src || {}).iv] || ivS, a0 = num(sg.from), a1 = num(sg.to) + gIv;
      if (a0 < bnd) { const e0 = Math.min(a1, bnd); parts.push({ from: a0, to: e0, cs: cs.filter(c => c[0] < e0), iv: gIv, kind: 'buy', sg }); }
      if (a1 > sTo) { const s0 = Math.max(a0, sTo); parts.push({ from: s0, to: a1, cs: cs.filter(c => c[0] >= s0), iv: gIv, kind: 'buy', sg }); }
    });
    parts.push({ from: sFrom, to: sTo, cs: sCs.filter(c => c[0] + ivS > sFrom && c[0] < sTo), iv: ivS, kind: 'sell' });
    arr(b.gapBridges).forEach(gb => {
      const cs = arr(gb && gb.candles).filter(okc).sort((a0, b0) => a0[0] - b0[0]), a0 = num(gb && gb.from), a1 = num(gb && gb.to);
      if (!cs.length || !(a1 > a0)) return;
      parts.push({ from: a0, to: a1, cs: cs.filter(c => c[0] < a1), iv: num(cs[0][7]) || IVS[(gb.src || {}).iv] || ivS, kind: 'bridge', gb });
    });
    parts.sort((p0, p1) => p0.from - p1.from);
    const fbT = num(bsm.firstTs) || Math.min.apply(null, arr(b.fills).map(f => num(f && f.ts)).filter(t => t > 0).concat([Infinity]));
    const lsT = num(w.sellTo) || Math.max.apply(null, arr(x.fills).map(f => num(f && f.ts)).concat([0]));
    const shortT = fbT > 0 && isFinite(fbT) && lsT > fbT && lsT - fbT <= RK_SHORT_S;
    const GAPK = shortT ? Infinity : RK_FOLD_S, ranges = [];
    parts.forEach(p0 => { const r = ranges[ranges.length - 1]; if (r && p0.from - r.to <= GAPK) { r.to = Math.max(r.to, p0.to); r.parts.push(p0); } else ranges.push({ from: p0.from, to: p0.to, parts: [p0] }); });
    const Wd = Math.round(Math.max(300, Math.min(756, S.mobile ? (window.innerWidth || 390) - 34 : 756)));
    const PH = S.mobile ? 210 : 270, VH = S.mobile ? 40 : 52, GAP = 8, AX = 22, T = 30, Lp = 8, Rp = 10, H = T + PH + GAP + VH + AX;
    const BW = S.mobile ? 22 : 30, nb = ranges.length - 1, PW = Wd - Lp - Rp - nb * BW;
    let fr = ranges.map(r => Math.max(1, r.to - r.from)); const ft = fr.reduce((a0, c) => a0 + c, 0); fr = fr.map(f => f / ft);
    if (ranges.length > 1) { const fmin = Math.min(0.3, 0.6 / ranges.length); fr = fr.map(f => Math.max(f, fmin)); const s0 = fr.reduce((a0, c) => a0 + c, 0); fr = fr.map(f => f / s0); }
    let xo = Lp; ranges.forEach((r, i) => { r.x0 = xo; r.w = fr[i] * PW; xo += r.w + (i < nb ? BW : 0); });
    const inR = t => ranges.some(r => t >= r.from && t <= r.to);
    const X = t => { for (const r of ranges) { if (t <= r.to) return t < r.from ? r.x0 : r.x0 + (t - r.from) / (r.to - r.from) * r.w; } const r = ranges[ranges.length - 1]; return r.x0 + r.w; };
    const bF = arr(b.fills).filter(f => f && f.ts && num(f.px) > 0 && inR(f.ts)), sF = arr(x.fills).filter(f => f && f.ts && num(f.px) > 0);
    const iF = arr(b.inflows).filter(f => f && f.ts && num(f.px) > 0 && inR(f.ts));
    const avgB = num(bsm.avgPx) * fk, avgS = num(sm.avgPx) * fk, hi = num(sm.hi) * fk, lo = num(sm.lo) * fk;
    parts.forEach(p0 => { const r = ranges.find(r0 => r0.parts.indexOf(p0) >= 0); p0.px = Math.max(8, (p0.to - p0.from) / Math.max(1, r.to - r.from) * r.w);
      const bn = rcBin(p0.cs, Math.max(4, Math.floor(p0.px / 2.5))); p0.bn = bn; p0.bS = p0.iv * bn.k; p0.bw = Math.max(1, Math.min(9, 0.68 * p0.px * p0.bS / Math.max(1, p0.to - p0.from)));
      p0.vmax = Math.max.apply(null, bn.cs.map(c => num(c[5])).concat([0])) || 1; });
    const ys = [];
    parts.forEach(p0 => p0.bn.cs.forEach(c => ys.push(c[2] * fk, c[3] * fk)));
    bF.concat(sF, iF).forEach(f => ys.push(num(f.px) * fk));
    if (avgB > 0) ys.push(avgB); if (avgS > 0) ys.push(avgS);
    let y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
    const rng0 = (y1 - y0) || y1 * 0.05 || 1;
    const ucShow = uc > 0 && !(avgB > 0 && Math.abs(uc / avgB - 1) < 0.02);
    const ucIn = ucShow && uc >= y0 - rng0 * 0.6 && uc <= y1 + rng0 * 0.6;
    if (ucIn) { y0 = Math.min(y0, uc); y1 = Math.max(y1, uc); }
    const pad = (y1 - y0) * 0.07 || y1 * 0.05 || 1; y0 = Math.max(0, y0 - pad); y1 += pad;
    const Y = p0 => T + (1 - (p0 - y0) / (y1 - y0)) * PH, VB = T + PH + GAP + VH;
    const yt = rcTicks(y0, y1, S.mobile ? 3 : 4).filter(p0 => Y(p0) > T + 8 && Y(p0) < T + PH - 4);
    const grid = yt.map(p0 => '<line x1="' + Lp + '" x2="' + (Wd - Rp) + '" y1="' + Y(p0).toFixed(1) + '" y2="' + Y(p0).toFixed(1) + '" class="gl"/><text x="' + (Lp + 4) + '" y="' + (Y(p0) - 4).toFixed(1) + '" class="tk">' + esc(P(p0)) + '</text>').join('');
    const md = t => { const z = new Date((t + 32400) * 1000); return (z.getUTCMonth() + 1) + '/' + z.getUTCDate(); };
    const isoOf = t => { const z = new Date((t + 32400) * 1000); return z.getUTCFullYear() + '-' + pad2(z.getUTCMonth() + 1) + '-' + pad2(z.getUTCDate()); };
    const tLab = t => (isoOf(t) === R.iso ? '' : md(t) + ' ') + kstHM(t);
    const twd = (s0, fs) => Array.from(String(s0)).reduce((a0, ch0) => a0 + (/[ㄱ-힝]/.test(ch0) ? fs : /[0-9]/.test(ch0) ? fs * 0.6 : ch0 === ' ' ? fs * 0.3 : fs * 0.5), 0);
    const fLab = (t, xd) => (xd || isoOf(t) !== R.iso ? md(t) + ' ' : '') + kstHM(t);
    const axl = [];
    ranges.forEach((r, i) => {
      const n0 = Math.max(1, Math.floor(r.w / (S.mobile ? 62 : 74))), span = (r.to - r.from) / 60;
      const stp = [5, 10, 15, 30, 60, 120, 180, 360, 720, 1440, 2880].find(s0 => span / s0 <= n0) || 2880;
      let first = true;
      for (let t = Math.ceil((r.from + 32400) / (stp * 60)) * stp * 60 - 32400; t <= r.to; t += stp * 60) {
        const xx = X(t); if (xx < r.x0 + 2 || xx > r.x0 + r.w - 2) continue;
        const lab = first && (i > 0 || isoOf(t) !== R.iso) ? tLab(t) : kstHM(t); first = false;
        axl.push({ x: xx, a: xx < 24 ? 'start' : xx > Wd - 24 ? 'end' : 'middle', t: lab, p: 1 });
      }
      if (first && i === 0) {
        const t9 = Math.ceil(r.from / 60) * 60;
        axl.push({ x: r.x0 + 1, a: 'start', t: isoOf(t9) !== R.iso ? tLab(t9) : kstHM(t9), p: 2 });
      }
    });
    ranges.slice(0, -1).forEach((r, i) => {
      const n9 = ranges[i + 1], xd = isoOf(r.to) !== isoOf(n9.from);
      axl.push({ x: r.x0 + r.w - 2, a: 'end', t: fLab(r.to, xd), p: 3, e: 1 }, { x: r.x0 + r.w + BW + 2, a: 'start', t: fLab(n9.from, xd), p: 3, e: 1 });
    });
    const axSpan = l => { const w9 = twd(l.t, 11); return l.a === 'end' ? [l.x - w9, l.x] : l.a === 'start' ? [l.x, l.x + w9] : [l.x - w9 / 2, l.x + w9 / 2]; };
    const axKeep = [], axFits = l => { const [a0, a1] = axSpan(l); return axKeep.every(k => { const [b0, b1] = axSpan(k); return a1 + 4 < b0 || b1 + 4 < a0; }); };
    axl.slice().sort((p0, p1) => p1.p - p0.p || p0.x - p1.x).forEach(l => { if (axFits(l)) axKeep.push(l); });
    if (nb) ranges.forEach(r => {
      if (r.w < 80 || axKeep.some(l => !l.e && l.x >= r.x0 && l.x <= r.x0 + r.w)) return;
      for (const st2 of [60, 30, 15, 10, 5]) {
        let add = 0;
        for (let t = Math.ceil((r.from + 32400) / (st2 * 60)) * st2 * 60 - 32400; t <= r.to; t += st2 * 60) {
          const xx = X(t); if (xx < r.x0 + 2 || xx > r.x0 + r.w - 2) continue;
          const l = { x: xx, a: xx < 24 ? 'start' : xx > Wd - 24 ? 'end' : 'middle', t: kstHM(t), p: 1 };
          if (axFits(l)) { axKeep.push(l); add++; }
        }
        if (add) break;
      }
    });
    const xax = axKeep.sort((p0, p1) => p0.x - p1.x).map(l => '<text x="' + l.x.toFixed(1) + '" y="' + (H - 6) + '" text-anchor="' + l.a + '" class="tk' + (l.e ? ' tke' : '') + '">' + esc(l.t) + '</text>').join('');
    let brks = '';
    const af = (sm.after || {})[v.after] || (sm.after || {})[x.after] || null;
    const afLab = '판 뒤 ' + (RC_AFK[x.after] || RC_AFK[v.after] || '') + (af ? ' 최저 ' + pctS(af.loPct, 1) + (num(af.hiPct) > 0.05 ? ' · 최고 ' + pctS(af.hiPct, 1) : '') : '');
    const afW = twd(afLab, 11);
    const sellTo = num(w.sellTo) || Math.max.apply(null, sF.map(f => f.ts));
    const sPart = parts.find(p0 => p0.kind === 'sell'), sx = Math.max(Lp, Math.min(Wd - Rp, X(sellTo))), ex = X(sTo);
    const shade = '<rect x="' + sx.toFixed(1) + '" y="' + (T - 22) + '" width="' + Math.max(0, ex - sx).toFixed(1) + '" height="' + (PH + 22 + GAP + VH) + '" class="aft"/><line x1="' + sx.toFixed(1) + '" x2="' + sx.toFixed(1) + '" y1="' + (T - 22) + '" y2="' + VB + '" class="aftl"/>'
      + '<text x="' + (ex - 6).toFixed(1) + '" y="' + (T - 8) + '" text-anchor="end" class="aftt">' + esc(afLab) + '</text>';
    const shortSrc = s0 => String((s0 || {}).label || '').replace(/^DEX /, '').replace(/ \(.*\)$/, '');
    let plab = '';
    parts.forEach(p0 => {
      const lab = p0.kind === 'sell' ? shortSrc(src) : p0.kind === 'bridge' ? '' : shortSrc(p0.sg.src);
      const x0 = X(p0.kind === 'sell' ? Math.max(p0.from, bnd) : p0.from);
      const prevB = parts.some(q0 => q0 !== p0 && q0.kind !== p0.kind && Math.abs(q0.to - Math.max(p0.from, p0.kind === 'sell' ? bnd : p0.from)) < 1);
      if (prevB) plab += '<line x1="' + x0.toFixed(1) + '" x2="' + x0.toFixed(1) + '" y1="' + T + '" y2="' + VB + '" class="pdv"/>';
      if (p0.px > 70 && lab) plab += '<text x="' + (x0 + 4).toFixed(1) + '" y="' + (T + PH - 6) + '" class="pl">' + esc(lab.length > 22 ? lab.slice(0, 21) + '…' : lab) + '</text>';
    });
    const brP = parts.filter(p0 => p0.kind === 'bridge');
    let brgBg = '';
    brP.forEach(p0 => {
      const gb = p0.gb, x0 = X(p0.from), x1 = X(p0.to), bw9 = x1 - x0, sh = String(gb.short || '빈 시간'), full = String(gb.label || sh);
      const rest = full.indexOf(sh + ' · ') === 0 ? full.slice(sh.length + 3) : '';
      const tip = tLab(p0.from) + ' ~ ' + tLab(p0.to) + ' · ' + full + ' — 흐린 봉 · 표시만(점수·AI 평가 밖)';
      brgBg += '<rect class="brg" x="' + x0.toFixed(1) + '" y="' + T + '" width="' + Math.max(0, bw9).toFixed(1) + '" height="' + (VB - T) + '"><title>' + esc(tip) + '</title></rect>';
      p0.lab9 = { x0, x1, bw9, sh, rest };
    });
    const sp = sm.spike && sm.spike.from ? sm.spike : null, inSp = t => sp && t >= sp.from && t < sp.to;
    let cnd = '';
    const cbx = [];
    parts.forEach(p0 => p0.bn.cs.forEach((r, i) => {
      const tail = p0.cs[Math.min(p0.cs.length, (i + 1) * p0.bn.k) - 1] || r, t9a = Math.max(p0.from, r[0]), t9b = Math.min(p0.to, tail[0] + p0.iv);
      const xm = X((t9a + t9b) / 2), o = r[1] * fk, h = r[2] * fk, l = r[3] * fk, cl = r[4] * fk, up = cl >= o, yo = Y(Math.max(o, cl)), yc = Y(Math.min(o, cl)), vh = num(r[5]) / p0.vmax * VH, ff = p0.bn.k === 1 && r[6] === 1;
      const brc = p0.kind === 'bridge';
      cbx.push([xm - Math.max(1, p0.bw / 2), Y(h), xm + Math.max(1, p0.bw / 2), Y(l)]);
      cnd += '<g class="' + (up ? 'cu' : 'cd') + (ff ? ' ff' : '') + (brc ? ' brc' : '') + '"><line x1="' + xm.toFixed(1) + '" x2="' + xm.toFixed(1) + '" y1="' + Y(h).toFixed(1) + '" y2="' + Y(l).toFixed(1) + '"/><rect x="' + (xm - p0.bw / 2).toFixed(1) + '" y="' + yo.toFixed(1) + '" width="' + p0.bw.toFixed(1) + '" height="' + Math.max(1, yc - yo).toFixed(1) + '"/>'
        + '<rect class="vb' + (p0.kind === 'sell' && inSp(r[0]) ? ' sp' : '') + '" x="' + (xm - p0.bw / 2).toFixed(1) + '" y="' + (VB - vh).toFixed(1) + '" width="' + p0.bw.toFixed(1) + '" height="' + Math.max(0.5, vh).toFixed(1) + '"/>'
        + '<title>' + esc(tLab(r[0]) + (brc ? ' · ' + (p0.gb.short || '빈 시간') + '(표시만)' : '') + (p0.bn.k > 1 ? ' (' + p0.bn.k + '봉 묶음)' : '') + (ff ? ' · 거래 없음(직전 가격)' : '') + ' · 시 ' + P(o) + ' · 고 ' + P(h) + ' · 저 ' + P(l) + ' · 종 ' + P(cl)) + '</title></g>';
    }));
    const spBar = sp ? '<line x1="' + X(sp.from).toFixed(1) + '" x2="' + X(sp.to).toFixed(1) + '" y1="' + (VB + 3) + '" y2="' + (VB + 3) + '" class="spl"/>' : '';
    const hl = (p0, c0, dash) => p0 > 0 ? '<line x1="' + Lp + '" x2="' + (Wd - Rp) + '" y1="' + Y(p0).toFixed(1) + '" y2="' + Y(p0).toFixed(1) + '" class="' + c0 + '"' + (dash ? ' stroke-dasharray="4 4"' : '') + '/>' : '';
    const ucOut = ucShow && !ucIn ? '<text x="' + (Lp + 4) + '" y="' + (T + PH - 4) + '" class="ucx">평단 ' + esc(P(uc)) + ' ↓ (아래)</text>' : '';
    const amx = Math.max.apply(null, bF.concat(sF).map(f => num(f.amt))) || 1;
    const dots = bF.map(f => ['b', f]).concat(sF.map(f => ['s', f])).sort((a0, b0) => num(b0[1].amt) - num(a0[1].amt)).map(([k0, f]) => {
      const p0 = num(f.px) * fk, a0 = num(f.amt) * fk, r0 = 3.5 + (S.mobile ? 10 : 14) * Math.sqrt(num(f.amt) / amx);
      const tt = k0 === 'b' ? tLab(f.ts) + ' 매수 · ' + (f.kind || '') + (f.from ? '(원래 ' + f.from + ')' : '') + (f.venue ? ' · ' + f.venue : '') + ' · ' + P(p0) + ' · ' + q(num(f.q)) + ' ' + sym + ' · ' + M(a0)
        : kstHM(f.ts) + ' 매도 · ' + P(p0) + ' · ' + q(num(f.q)) + ' ' + sym + ' · ' + M(a0);
      return '<circle cx="' + X(f.ts).toFixed(1) + '" cy="' + Y(p0).toFixed(1) + '" r="' + r0.toFixed(1) + '" class="' + (k0 === 'b' ? 'bd' : 'sd') + '"><title>' + esc(tt) + '</title></circle>';
    }).join('') + iF.map(f => {
      const p0 = num(f.px) * fk, cx9 = X(f.ts), cy9 = Y(p0), r0 = S.mobile ? 6 : 7;
      const tt = tLab(f.ts) + ' 입금' + (f.chain ? ' · ' + f.chain : '') + ' · 원가 단가 ' + P(p0) + ' · ' + q(num(f.q)) + ' ' + sym + (f.rule ? ' · 원가 규칙: ' + f.rule : '');
      return '<path class="idm" d="M' + cx9.toFixed(1) + ' ' + (cy9 - r0).toFixed(1) + ' L' + (cx9 + r0).toFixed(1) + ' ' + cy9.toFixed(1) + ' L' + cx9.toFixed(1) + ' ' + (cy9 + r0).toFixed(1) + ' L' + (cx9 - r0).toFixed(1) + ' ' + cy9.toFixed(1) + ' Z"><title>' + esc(tt) + '</title></path>';
    }).join('');
    const exR = X(sTo) - 6, occ = [[exR - afW - 2, T - 20, exR + 1, T - 4]];
    const dbx = bF.concat(sF).map(f => { const r0 = 3.5 + (S.mobile ? 10 : 14) * Math.sqrt(num(f.amt) / amx), cx9 = X(f.ts), cy9 = Y(num(f.px) * fk); return [cx9 - r0, cy9 - r0, cx9 + r0, cy9 + r0]; });
    const y0w = T - 2, y1w = H - 2;
    const bands = ranges.slice(0, -1).map(r => [r.x0 + r.w, y0w, r.x0 + r.w + BW, y1w]);
    ranges.slice(0, -1).forEach((r, i) => {
      const n9 = ranges[i + 1], bx0 = r.x0 + r.w, bx1 = bx0 + BW, cxm = bx0 + BW / 2, gapS = n9.from - r.to;
      const wave = x9 => { let dd = 'M' + x9.toFixed(1) + ' ' + y0w; for (let yy = y0w, k = 0; yy < y1w; yy += 6, k++) dd += ' L' + (x9 + (k % 2 ? -2.2 : 2.2)).toFixed(1) + ' ' + Math.min(y1w, yy + 6); return dd; };
      const tip = fLab(r.to, true) + ' → ' + fLab(n9.from, true) + ' (' + durTxt(gapS) + ') 접음 — 매수·매도가 없던 시간';
      const full = durTxt(gapS), major = full.split(' ')[0], cands = [];
      [full + ' 접음', major + ' 접음', major].filter((t, j, a9) => a9.indexOf(t) === j).forEach(t => {
        const lw = twd(t, 10.5) + 12, lim = Math.max(0, lw / 2 - 6);
        [T - 21, T + 4].forEach(ly => [0, 0.5, -0.5, 1, -1].forEach(k9 => cands.push({ x: Math.max(Lp, Math.min(Wd - Rp - lw, cxm - lw / 2 + k9 * lim)), y: ly, w: lw, h: 16, t })));
      });
      const pk = rkFit(occ, cands, Lp, Wd - Rp, cbx.concat(dbx, bands.filter((_, j) => j !== i)));
      brks += '<g class="brk" data-a="rkBrk" data-tip="' + esc(tip) + '" role="button" tabindex="0" aria-label="' + esc(tip) + '"><rect class="bb" x="' + bx0.toFixed(1) + '" y="' + y0w + '" width="' + BW + '" height="' + (y1w - y0w) + '"/>'
        + '<path class="wv" d="' + wave(bx0 + 3) + ' ' + wave(bx1 - 3) + '"/>'
        + (pk ? '<g class="bp"><rect class="bpr" x="' + pk.x.toFixed(1) + '" y="' + pk.y + '" width="' + pk.w.toFixed(1) + '" height="16" rx="8"/><text x="' + (pk.x + pk.w / 2).toFixed(1) + '" y="' + (pk.y + 11.5) + '" text-anchor="middle">' + esc(pk.t) + '</text></g>' : '')
        + '<title>' + esc(tip) + '</title></g>';
    });
    let hiMk = '';
    if (hi > 0 && sm.hiTs && inR(num(sm.hiTs))) {
      const hx = X(num(sm.hiTs) + ivS / 2), hy = Y(hi), lab = '구간 고가 ' + P(hi) + ' ' + kstHM(num(sm.hiTs));
      const c9 = rkHiPill(hx, hy, [lab, '고가 ' + P(hi)], occ, bands, cbx, Lp + 2, Wd - Rp - 2, T + PH);
      hiMk = rkHiSvg(c9, hx, hy, lab);
    }
    let brgLab = '';
    brP.forEach(p0 => {
      const L9 = p0.lab9; if (!L9) return;
      const c9 = p0.bn.cs, yTop = c9.length ? Math.min.apply(null, c9.map(c => Y(c[2] * fk))) : T + PH / 2, yBot = c9.length ? Math.max.apply(null, c9.map(c => Y(c[3] * fk))) : T + PH / 2;
      const show1 = L9.bw9 >= twd(L9.sh, 11) + 6;
      let show2 = show1 && !!L9.rest && L9.bw9 >= twd(L9.rest, 10.5) + 6, hgt = show2 ? 30 : 16;
      const box = top => (top ? [L9.x0, T + 1, L9.x1, T + 1 + hgt] : [L9.x0, T + PH - 4 - hgt, L9.x1, T + PH - 4]);
      const hit = bb => occ.some(o => bb[0] < o[2] && o[0] < bb[2] && bb[1] < o[3] && o[1] < bb[3]);
      let top = yTop - T >= T + PH - yBot;
      if (hit(box(top)) && !hit(box(!top))) top = !top;
      if (!show1) return;
      if (hit(box(top)) && show2) { show2 = false; hgt = 16; if (hit(box(top)) && !hit(box(!top))) top = !top; }
      if (hit(box(top))) return;
      occ.push(box(top));
      const cxb = (L9.x0 + L9.x1) / 2, y1 = top ? T + 13 : T + PH - (show2 ? 20 : 6);
      brgLab += '<text class="brgt b1" x="' + cxb.toFixed(1) + '" y="' + y1 + '" text-anchor="middle">' + esc(L9.sh) + '</text>';
      if (show2) brgLab += '<text class="brgt" x="' + cxb.toFixed(1) + '" y="' + (y1 + 14) + '" text-anchor="middle">' + esc(L9.rest) + '</text>';
    });
    const aria = (dt.getMonth() + 1) + '월 ' + dt.getDate() + '일 ' + sym + ' 실제 시세 위 내 매수 ' + bF.length + '회 · 매도 ' + sF.length + '회'
      + (bsm.botPct != null ? ' · 평균 매수가 위치 저가에서 ' + nf('ko-KR', 1, 1).format(num(bsm.botPct)) + '%' : '') + (sm.posPct != null ? ' · 평균 매도가 위치 저가에서 ' + nf('ko-KR', 1, 1).format(num(sm.posPct)) + '%' : '') + (nb ? ' · 비어 있는 시간 ' + nb + '곳 접음' : '')
      + (brP.length ? ' · ' + brP.map(p0 => String(p0.gb.label || p0.gb.short || '')).join(' · ') + ' 구간은 흐린 봉(표시만 · 점수 밖)' : '');
    const svg = '<svg class="rsc rkg cmb" width="' + Wd + '" height="' + H + '" viewBox="0 0 ' + Wd + ' ' + H + '" role="img" aria-label="' + esc(aria) + '">'
      + shade + brgBg + grid + '<line x1="' + Lp + '" x2="' + (Wd - Rp) + '" y1="' + VB + '" y2="' + VB + '" class="gl"/>' + plab + cnd + brgLab + brks + spBar + hl(ucIn ? uc : 0, 'ucl', true) + hl(avgB, 'abl', false) + hl(avgS, 'avl', false) + ucOut + dots + hiMk + xax + '</svg>';
    const segB = (a0, list, cur0, lab) => '<div class="seg rkseg" role="group" aria-label="' + lab + '">' + list.map(o => '<button data-a="' + a0 + '" data-v="' + o[0] + '" class="' + (cur0 === o[0] ? 'on' : '') + '" aria-pressed="' + (cur0 === o[0]) + '">' + (a0 === 'rcAfter' && !S.mobile && o[0] === '1h' ? '판 뒤 ' : '') + o[1] + '</button>').join('') + '</div>';
    const chips = (list, cur0, act, lab) => list.length > 1 ? '<div class="rkvn" role="group" aria-label="' + lab + '"><span class="cap rkvl">' + lab.split(' —')[0] + '</span>' + list.map(o => { const on = o.key === cur0; return '<button class="chip' + (on ? ' on' : '') + '" data-a="' + act + '" data-v="' + esc(o.key) + '" aria-pressed="' + on + '">' + esc(o.label) + ' <span class="mut num">' + (o.sharePct != null ? nf('ko-KR', 0, 0).format(num(o.sharePct)) + '% · ' : '') + num(o.n) + '회</span></button>'; }).join('') + '</div>' : '';
    const vchips = chips(arr(x.venues), x.venue, 'rcVenue', '매도 장소 — 장소마다 그 시장 봉') + chips(arr(b.venues), b.venue, 'rcBVenue', '매수 장소 — 매수 구간 봉 출처');
    const lpq = num(((b.legs || {}).lpFee || {}).qty), cpx = num((b.sell || {}).costPx) * fk;
    const lpNote = lpq > 0 && cpx > 0 ? 'LP 수수료로 받은 <b class="num">' + q(lpq) + '</b>개(받은 때 시가 원가) 포함 평균 매수가 <b class="num">' + P(cpx) + '</b>' : '';
    const leg = '<div class="rkleg cap"><span><i class="lg bd" aria-hidden="true"></i>내 매수</span>' + (iF.length ? '<span><i class="lg idm" aria-hidden="true"></i>입금(원가가 매수 아닌 입금)</span>' : '') + (avgB > 0 ? '<span><i class="lg abl" aria-hidden="true"></i>평균 매수 <b class="num">' + P(avgB) + '</b></span>' : '')
      + (lpNote ? '<span class="rklp">' + lpNote + '</span>' : '')
      + '<span><i class="lg sdr" aria-hidden="true"></i>내 매도</span>' + (avgS > 0 ? '<span><i class="lg avlr" aria-hidden="true"></i>평균 매도 <b class="num">' + P(avgS) + '</b></span>' : '')
      + (ucShow ? '<span><i class="lg ucl" aria-hidden="true"></i>평단 <b class="num">' + P(uc) + '</b></span>' : '') + '<span><i class="lg aft" aria-hidden="true"></i>판 뒤 ' + (RC_AFK[x.after] || '') + '</span>'
      + (sp ? '<span><i class="lg spl" aria-hidden="true"></i>거래량 급증</span>' : '') + (nb ? '<span><i class="lg brk" aria-hidden="true"></i>빈 시간 접음</span>' : '')
      + Array.from(new Set(brP.map(p0 => String(p0.gb.label || p0.gb.short || '')))).map(t => '<span class="rkbrl"><i class="lg brg" aria-hidden="true"></i>' + esc(t) + ' <span class="mut">(흐린 봉 · 점수 밖)</span></span>').join('') + '</div>';
    const ivTxt = s0 => RC_IVK[(s0 || {}).iv] || (s0 || {}).iv || '';
    const bSrc = arr(b.segs).find(sg => sg.ok && sg.src) || {}, bs0 = bSrc.src || {}, btr = arr(bSrc.tried);
    let bTxt = '매수 봉 ' + (bs0.fallback && btr.length ? btr[0].label + rcFbTxt(btr[0]) : '') + (bs0.label || '') + ' ' + ivTxt(bs0) + (bs0.fx ? (bs0.fx.mode === 'KRW→USD' ? '(달러 환산)' : '(원화 환산)') : '');
    if (bs0.venue === 'dex' && bs0.poolMatched === false) bTxt += ' · 내 거래 풀과 다른 풀일 수 있어요';
    if (arr(b.segs).some(sg => num(sg.filled) > 0)) bTxt += ' · 거래 없는 칸은 직전 가격(흐린 봉)';
    const tr = arr(ch.tried);
    let sTxt = '매도 봉 ' + (src.fallback && tr.length ? tr[0].label + rcFbTxt(tr[0]) : '') + (src.label || '') + ' ' + ivTxt(src) + (src.fx ? (src.fx.mode === 'KRW→USD' ? '(달러 환산)' : '(원화 환산)') : '');
    if (src.iv && src.iv !== x.iv) sTxt += ' · ' + (RC_IVK[x.iv] || x.iv) + '이 없어 저해상도';
    if (b.dexLater || x.dexLater) sTxt += ' · ' + rcLaterTxt(b.dexLater || x.dexLater);
    if (fk !== 1) sTxt += ' · ' + (dc === 'USD' ? '달러' : '원화') + ' 환산(그날 매도 환율 ₩' + nf('ko-KR', 0, 0).format(Rk) + ')';
    const brTxt = Array.from(new Set(brP.map(p0 => (p0.gb.short || '빈 시간') + ' 봉 ' + ((p0.gb.src || {}).label || '') + ' ' + ivTxt(p0.gb.src)))).join(' · ');
    const outTxt = b.outside && num(b.outside.n) > 0 ? '그림 밖 매수 ' + num(b.outside.n) + '회(금액 큰 묶음 3개만 그림)' : '';
    const lg = b.legs || {}, lpf = lg.lpFee || {};
    const legTxt = [num(lpf.n) > 0 ? 'LP 수수료로 받은 ' + num(lpf.n) + '건은 매수가 아니라 점 없음' : '', num((lg.trimmed || {}).n) > 0 ? '오래된 매수 ' + num(lg.trimmed.n) + '회는 이번 매도 물량 밖' : '', num(lg.unmatched) > 0 ? '원가 승계 ' + num(lg.unmatched) + '건은 출발 기록을 못 찾음' : '', num(lg.fallback) > 0 ? '원가 승계 ' + num(lg.fallback) + '건은 엔진 연결이 없어 수량·시각으로 추정' : '',
      lg.source === 'sim' ? '원가 구성은 기록으로 다시 계산(엔진 구성 없음)' : '', lg.source === 'mixed' ? '매도 ' + num(lg.simSells) + '건의 원가 구성은 기록으로 다시 계산(엔진 구성 없음)' : '', lg.other && num(lg.other.qty) > 0 ? '출처를 모르는 원가 몫 ' + q(num(lg.other.qty)) + '개(점 없음)' : '',
      num(lg.unknownQty) > 0 ? '원가 미상 ' + q(num(lg.unknownQty)) + '개(점 없음)' : '',
      num(lg.inflows) > 0 ? '입금으로 원가가 잡힌 몫 ' + q(num(lg.inflowQty)) + '개 ' + num(lg.inflows) + '건(마름모 · 원가 규칙: ' + Array.from(new Set(arr(b.inflows).map(f => f && f.rule).filter(Boolean))).join(' / ') + ')' : ''].filter(Boolean).join(' · ');
    const srcLine = '<div class="rksrc cap"><span title="' + esc(btr.concat(tr).map(t => t.label + ' — ' + (t.note || t.why)).join('\n')) + '">' + esc(bTxt) + '</span><span>' + esc(sTxt) + '</span>' + (brTxt ? '<span class="rkbrs">' + esc(brTxt + ' — 표시만(점수·AI 평가 밖)') + '</span>' : '') + (outTxt ? '<span>' + esc(outTxt) + '</span>' : '') + (legTxt ? '<span>' + esc(legTxt) + '</span>' : '') + '</div>';
    const head = '<div class="row rtth rkh"><span class="rtt">실제 시세 위 내 매수·매도 — 점 크기 = 금액</span><span class="sp"></span>' + segB('rcIv', RC_IVS, v.iv, '봉 간격') + segB('rcAfter', RC_AFTERS, v.after, '판 뒤 구간') + '</div>';
    const pc = (vv, dd) => vv == null || !isFinite(vv) ? '—' : pctS(vv, dd == null ? 1 : dd);
    const tile = (l, vh, s0, c0, tt) => '<div class="rkt"' + (tt ? ' title="' + esc(tt) + '"' : '') + '><span class="l">' + l + '</span><b class="num ' + (c0 || '') + '">' + vh + '</b><span class="s num">' + s0 + '</span></div>';
    const bLo = num(bsm.lo) * fk, bHi = num(bsm.hi) * fk, us = bsm.untilSell || null;
    const b1 = bsm.botPct != null ? tile('평균 매수가 위치', '저가에서 ' + nf('ko-KR', 1, 1).format(num(bsm.botPct)) + '%<span class="rkbar b" aria-hidden="true"><i style="left:' + Math.max(0, Math.min(100, num(bsm.botPct))).toFixed(1) + '%"></i></span>',
      '범위 ' + arr(b.segs).map(sg => tLab(num(sg.from)) + '~' + tLab(num(sg.to))).join(' · ') + ' 저가 ' + P(bLo) + ' ~ 고가 ' + P(bHi), '', '0% = 매수 구간(묶음마다 첫 매수 1시간 전 ~ 마지막 매수 1시간 뒤) 저가 · 100% = 고가 — 낮을수록 싸게 산 것') : tile('평균 매수가 위치', '—', '구간 봉 없음');
    const b2 = tile('그때 시세 대비', pc(bsm.vsMarketPct), bsm.vsMarketPct != null ? '체결 시각 봉 중간가 대비 · ' + num(bsm.mktN) + '/' + num(bsm.n) + '회' : '체결 시각 봉 없음', bsm.vsMarketPct != null && num(bsm.vsMarketPct) < 0 ? 'okc' : '', '체결마다 그 시각 봉(상장 전 = 매수 장소 봉 · 그 뒤 = 화면 봉)의 (고가+저가)/2 와 비교 · 금액 가중 — 음수 = 그때 시세보다 싸게 삼');
    const b3 = tile('추격 매수', pc(bsm.chasePct), bsm.chasePct != null ? '직전 1시간 평균 대비 · ' + num(bsm.chaseN) + '회' : '직전 1시간 봉 없음', bsm.chasePct != null && num(bsm.chasePct) > 5 ? 'wc' : bsm.chasePct != null && num(bsm.chasePct) <= 0 ? 'okc' : '', '체결가 vs 직전 1시간 시장 평균(금액 가중) — 양수 = 오른 뒤 따라 삼');
    const b4 = us ? tile('첫 매도까지 최고', pc(us.hiPct), '최저 ' + pc(us.loPct) + ' · 매수 평균 대비 · ' + durTxt(num(us.horizonMin) * 60), num(us.hiPct) > 0 ? 'okc' : 'down', '첫 매수부터 첫 매도까지 시세의 최고·최저를 평균 매수가와 비교' + (us.covered === false ? ' · 그 사이 봉이 다 있지 않음' : '') + (bsm.sell && bsm.sell.premiumPct != null ? ' · 매도 평균가는 매수 평균가보다 ' + pctS(bsm.sell.premiumPct, 1) : ''))
      : tile('첫 매도까지 최고', '—', '그 사이 봉 없음');
    const a1 = (sm.after || {})['1h'], a6 = (sm.after || {})['6h'], a24 = (sm.after || {})['24h'];
    const posTxt = sm.posPct != null ? '저가에서 ' + nf('ko-KR', 1, 1).format(num(sm.posPct)) + '%' : '';
    const s1 = sm.posPct != null ? tile('평균 매도가 위치', esc(posTxt) + '<span class="rkbar" aria-hidden="true"><i style="left:' + Math.max(0, Math.min(100, num(sm.posPct))).toFixed(1) + '%"></i></span>', '구간 저가 ' + P(lo) + ' ~ 고가 ' + P(hi), '', '0% = 구간 저가 · 100% = 고가 — 높을수록 비싸게 판 것') : tile('평균 매도가 위치', '—', '구간 봉 없음');
    const s2 = tile('고점 대비', pc(sm.fromHighPct), '평균 ' + P(avgS) + ' vs 고가 ' + P(hi), sm.fromHighPct != null && num(sm.fromHighPct) < 0 ? 'down' : '');
    const s3 = a1 ? tile('판 뒤 1시간 최저', pc(a1.loPct), (num(a1.hiPct) > 0.05 ? '최고 ' + pc(a1.hiPct) + ' · ' : '') + (a6 || a24 ? [a6 ? '6시간 ' + pc(a6.loPct) : '', a24 ? '24시간 ' + pc(a24.loPct) : ''].filter(Boolean).join(' · ') : '6시간·24시간은 위 \'판 뒤\'에서'), num(a1.loPct) < 0 ? 'okc' : '') : tile('판 뒤 1시간', '—', '그 뒤 봉 없음');
    const s4 = sp ? tile('거래량 급증 때 매도', nf('ko-KR', 0, 1).format(num(sp.sharePct)) + '%', kstHM(sp.from) + '~' + kstHM(sp.to) + ' 물량 비중', 'wc') : tile('거래량 급증 때 매도', '—', '뚜렷한 급증 구간 없음');
    const sd = (h, k) => h.replace('<div class="rkt"', '<div class="rkt ' + k + '"');
    const tiles = '<div class="rk4 rk4m" role="group" aria-label="핵심 숫자 — 매수 · 매도">' + sd(b1, 'b') + sd(b2, 'b') + sd(s1, 's') + sd(s3, 's') + '</div>'
      + uiFold('rk:more', { cls: 'plain rkmore', head: '<span class="cap">숫자 4개 더 — 추격 매수 · 첫 매도까지 최고 · 고점 대비 · 거래량 급증</span>', body: () => '<div class="rk4 rk4m">' + sd(b3, 'b') + sd(b4, 'b') + sd(s2, 's') + sd(s4, 's') + '</div>', label: '숫자 4개 더 보기' });
    const ai = rkAiFold(R, [{ side: 'buy', x: b, box: rkEvalBox(R, b, cx, loading, 'buy') }, { side: 'sell', x, box: rkEvalBox(R, x, cx, loading) }]);
    const busy = loading ? ' aria-busy="true"' : '';
    const html = '<section class="rsec rkc"' + busy + '>' + head + vchips + leg
      + '<div class="rscw rkw">' + prog + svg + '</div>' + srcLine + '</section>' + tiles + ai;
    return { ok: true, html };
  }
  const rkVc = vd => vd === '잘 팔았음' || vd === '잘 샀음' ? 'ok' : vd === '아쉬움' ? 'e' : 'w';
  function rkAiSum(R, x, side) {
    const E = (S.rcptE || {})[rcSK(R, side === 'buy' ? 'buy' : undefined)] || {};
    const ev = E.ev !== undefined && E.st !== 'load' ? E.ev : (E.ev || (x && x.eval) || null);
    const run = E.st === 'running' || E.st === 'post' || (!E.st || E.st === 'load' ? !!(x && x.evalStatus === 'running') : false);
    const c = ((x && x.summary) || {}).score || {};
    const sc = ev && ev.score != null ? ev.score : c.total;
    return { sc: sc == null || !isFinite(+sc) ? null : Math.max(0, Math.min(100, Math.round(num(sc)))), vd: String((ev ? ev.verdict : c.verdict) || ''), run, ev: !!ev, err: !!(E.msg && E.msg.c === 'e') };
  }
  function rkAiFold(R, parts) {
    const P0 = parts.filter(p => p.box);
    if (!P0.length) return '';
    const sm = P0.map(p => Object.assign({ side: p.side }, rkAiSum(R, p.x, p.side)));
    const pill = a => '<span class="pill sm rkap pvx ' + (a.side === 'buy' ? 'b' : 's') + '">' + (a.side === 'buy' ? '매수' : '매도') + (a.sc != null ? ' <b class="num">' + a.sc + '</b>' : '') + (a.vd ? '<i class="rkv ' + rkVc(a.vd) + '">' + esc(a.vd) + '</i>' : '') + '</span>';
    const st = sm.some(a => a.run) ? '<span class="pill a sm">진행 중</span>' : sm.some(a => a.err) ? '<span class="pill e sm">오류</span>' : '<span class="cap rkac pvx">' + (sm.every(a => a.ev) ? '설명 ' + sm.length + '개' : sm.some(a => a.ev) ? '설명 일부' : '구성·설명') + '</span>';
    const lab = 'AI 평가 — ' + sm.map(a => (a.side === 'buy' ? '매수' : '매도') + (a.sc != null ? ' ' + a.sc + '점' : '') + (a.vd ? ' ' + a.vd : '')).join(' · ');
    return '<section class="rkes rkfold" aria-label="AI 평가">' + uiFold('rk:ai', { def: true, cls: 'plain rkaif', head: '<b class="rkat">AI 평가</b>' + sm.map(pill).join(''), side: st, label: lab,
      body: () => '<div class="rkab">' + (P0.length > 1 ? '<div class="cap rkacap">점수는 차트 숫자로 계산(구성 아래) · AI는 왜 그런지 설명만</div>' : '') + P0.map(p => p.box).join('') + '</div>' }) + '</section>';
  }
  const RK_CK = { pos: '위치', vwap: '시장 평균', mkt: '그때 시세', after: '', spike: '급증', chase: '추격' };
  function rkBreak(sc, side) {
    if (!sc || !arr(sc.components).length) return '';
    const it = arr(sc.components).map(c => {
      const lab = c.k === 'after' ? (side === 'buy' ? '매수 뒤' : '판 뒤') : (RK_CK[c.k] || c.label || c.k), mx = num(c.max), miss = c.pts == null;
      const p = miss ? 0 : Math.max(0, Math.min(mx, num(c.pts)));
      return '<li class="' + (miss ? 'ms' : '') + '" title="' + esc((c.label || lab) + ' — ' + (c.why || '')) + '"><span class="l">' + esc(lab) + '</span><span class="rkbb" aria-hidden="true"><i style="width:' + (mx > 0 ? (p / mx * 100).toFixed(1) : 0) + '%"></i></span><b class="num">' + (miss ? '빠짐' : nf('ko-KR', 0, 1).format(p) + '<span>/' + mx + '</span>') + '</b></li>';
    }).join('');
    return '<ul class="rkbd pvx" aria-label="점수 구성(계산식)">' + it + '</ul>' + (sc.scaled ? '<div class="cap">빠진 구성은 빼고 남은 만점으로 100점 환산</div>' : '');
  }
  function rkEvalBox(R, x, cx, loading, side) {
    const buy = side === 'buy', E = (S.rcptE || {})[rcSK(R, side)] || {};
    const ev = E.ev !== undefined && E.st !== 'load' ? E.ev : (E.ev || x.eval || null);
    const run = E.st === 'running' || E.st === 'post' || (!E.st || E.st === 'load' ? x.evalStatus === 'running' : false);
    const bd = E.budget, left = bd && bd.left != null ? num(bd.left) : null, out = left != null && left <= 0;
    const budTxt = bd && bd.max != null ? (num(bd.max) === 0
      ? '<span class="cap pvx" title="설정 파일 review.' + (side === 'buy' ? 'buy' : 'sell') + '_eval_daily_max">AI 평가 꺼짐 — 하루 한도가 0이에요</span>'
      : '<span class="cap pvx">오늘 남은 한도 <b class="num">' + Math.max(0, num(bd.left)) + '/' + num(bd.max) + '</b></span>') : '';
    const msg = E.msg && E.msg.t ? '<div class="rkem ' + (E.msg.c === 'e' ? 'e' : E.msg.c === 'w' ? 'w' : '') + '" role="' + (E.msg.c === 'e' ? 'alert' : 'status') + '">' + esc(E.msg.c === 'e' ? errTxt(E.msg.t) : E.msg.t) + '</div>' : '';
    const dis = loading || run || out ? ' disabled' : '';
    const old = E.st === 'old';
    if (old && !ev) return '';
    const sideCls = buy ? ' rkbx' : '';
    const ttl = '<b class="rket">' + (buy ? 'AI 매수 평가' : 'AI 매도 평가') + '</b>';
    const vcOf = vd => vd === '잘 팔았음' || vd === '잘 샀음' ? 'ok' : vd === '아쉬움' ? 'e' : 'w';
    const ringOf = (sc0, vd, vc) => { const C0 = 2 * Math.PI * 31; return '<div class="rkring ' + vc + ' pvx" role="img" aria-label="' + (buy ? '매수 ' : '') + '점수 ' + sc0 + '점(100점 만점) · ' + esc(vd) + '"><svg width="76" height="76" viewBox="0 0 76 76" aria-hidden="true"><circle cx="38" cy="38" r="31" class="bg"/><circle cx="38" cy="38" r="31" class="fg" stroke-dasharray="' + (C0 * sc0 / 100).toFixed(1) + ' ' + C0.toFixed(1) + '" transform="rotate(-90 38 38)"/></svg><b class="num">' + sc0 + '</b><span>/100</span></div>'; };
    const scNow = (x.summary || {}).score || null;
    const auto9 = !!x.autoEval && !(S.D && S.D.reviewPause && S.D.reviewPause.on), defv = rcDefView(R);
    const getBtn = (lab0) => auto9 ? '<button class="link sm rkelk" data-a="' + (buy ? 'rcEvalB' : 'rcEval') + '"' + dis + '>' + (defv ? '다시 시도' : '이 보기로 평가') + '</button>'
      : '<button class="btn pri sm" data-a="' + (buy ? 'rcEvalB' : 'rcEval') + '"' + dis + '>' + lab0 + '</button>';
    const autoCap = auto9 ? '<div class="cap">' + (defv ? '서랍을 열면 AI 설명을 자동으로 만들어요' : '기본 보기(5분봉 · 판 뒤 1시간)만 자동이에요 — 이 보기는 링크로') + '</div>' : '';
    if (run) return '<section class="rke run' + sideCls + '" aria-busy="true"><div class="rkeb"><div class="rkeh">' + ttl + '<span class="pill a sm">진행 중</span></div><div class="rkwait" role="status" aria-live="polite"><i class="spin" aria-hidden="true"></i>' + (E.st === 'post' && E.msg && E.msg.t ? '' : 'AI가 차트와 체결을 보고 ' + (buy ? '매수 타점을' : '') + ' 평가하는 중 — 보통 1분 안팎') + '</div>' + msg + '</div></section>';
    if (!ev) {
      if (scNow && scNow.total != null) {
        const vd0 = String(scNow.verdict || ''), sc1 = Math.max(0, Math.min(100, Math.round(num(scNow.total))));
        return '<section class="rke none calc' + sideCls + '">' + ringOf(sc1, vd0, vcOf(vd0)) + '<div class="rkeb"><div class="rkeh">' + ttl + '<span class="pill ' + vcOf(vd0) + ' sm">' + esc(vd0) + '</span><span class="cap">점수 = 아래 계산식(차트 숫자) · ' + (auto9 ? (defv ? 'AI 설명은 자동으로 붙어요' : 'AI 설명은 기본 보기만 자동') : 'AI 설명은 버튼을 눌렀을 때만') + '</span></div>' + rkBreak(scNow, side) + msg + '</div>'
          + '<div class="rkea">' + budTxt + getBtn('AI 설명 받기') + '</div></section>';
      }
      return '<section class="rke none' + sideCls + '"><div class="rkeb"><div class="rkeh">' + ttl + '</div>' + (auto9 ? autoCap : '<div class="cap">위 실제 차트와 숫자로 \'' + (buy ? '잘 샀는지' : '잘 팔았는지') + '\' 점수·3~4줄 — 버튼을 눌렀을 때만 만들어 저장해요</div>') + msg + '</div>'
        + '<div class="rkea">' + budTxt + getBtn('AI 평가 받기') + '</div></section>';
    }
    const fpM = (buy ? S.rcFpB : S.rcFp) || {}, cur0 = x.evalFp;
    let stale = '';
    if (ev.old) stale = '<div class="rkem w" role="status"><span class="pill w sm">다시 평가 권장</span> 옛 방식 점수(AI가 매긴 점수)예요 — 다시 평가하면 계산식 점수로 바뀌어요</div>';
    else if (cur0 && ev.fp && ev.fp !== cur0) {
      const o = fpM[ev.fp];
      if (o) stale = '<div class="rkem">이 평가는 ' + esc(buy ? (RC_IVK[o.iv] || o.iv) : (RC_IVK[o.iv] || o.iv) + ' · 판 뒤 ' + (RC_AFK[o.after] || o.after)) + ' 보기 기준이에요 — 지금 보기로 다시 평가할 수 있어요</div>';
      else if (ev.iv && x.chart && x.chart.src && ev.iv !== x.chart.src.iv) stale = '<div class="rkem">이 평가는 ' + esc(RC_IVK[ev.iv] || ev.iv) + ' 기준이에요 — 지금 보기로 다시 평가할 수 있어요</div>';
      else stale = '<div class="rkem w" role="status"><span class="pill w sm">다시 평가 권장</span> 평가 뒤 체결·시세 입력이 바뀌었어요</div>';
    }
    const vd = String(ev.verdict || ''), vc = vcOf(vd), sc0 = Math.max(0, Math.min(100, Math.round(num(ev.score))));
    const ring = ringOf(sc0, vd, vc);
    const cvn = x.cur && (x.cur === 'KRW') !== (S.cur !== 'USD') ? '<span> · 문장 속 가격은 ' + (x.cur === 'KRW' ? '원화' : '달러') + ' 마켓 기준</span>' : '';
    const memoChip = ev.memoUsed ? '<span class="pill g sm" title="그날 매매 근거 메모를 함께 보고 쓴 평가예요(점수는 계산식 그대로)">근거 반영</span>' : '';
    const meta = memoChip + '<span class="cap">' + esc([ev.src ? ev.src + (ev.iv ? ' ' + (RC_IVK[ev.iv] || ev.iv) : '') : '', ev.nFills ? '체결 ' + ev.nFills + '회 기준' : '', ev.at ? fmtTs(num(ev.at)) + ' 생성' : ''].filter(Boolean).join(' · ')) + cvn + '</span>';
    const lines = pvOn() ? '<li class="cap rkhid">' + (S.rand ? '랜덤값' : '숨김') + ' 모드에서는 AI 설명을 가려요 — 점수와 항목 점수만 보여요</li>'
      : arr(ev.lines).map(t => '<li class="aib">' + esc(evTxt(t)) + '</li>').join('') + (ev.next ? '<li class="nx aib"><b>다음엔</b> ' + esc(evTxt(ev.next)) + '</li>' : '');
    const warn = arr(ev.warn).indexOf('unit') >= 0 ? '<div class="cap">일부 숫자에 통화 기호가 빠졌을 수 있어요 — 가격은 위 차트·칸이 기준</div>' : '';
    const brk = arr(ev.components).length ? rkBreak({ components: ev.components, scaled: ev.scaled }, side) : '';
    return '<section class="rke done' + sideCls + '">' + ring + '<div class="rkeb"><div class="rkeh">' + ttl + '<span class="pill ' + vc + ' sm">' + esc(vd) + '</span>' + meta + '</div>' + brk + '<ul class="rkel">' + lines + '</ul>' + warn + stale + msg + '</div>'
      + '<div class="rkea">' + budTxt + '<button class="' + (auto9 ? 'link sm rkelk' : 'btn sm') + '" data-a="' + (buy ? 'rcEvalReB' : 'rcEvalRe') + '"' + dis + '>다시 평가</button></div></section>';
  }
  function rcptBody(R, d) {
    const D = S.D, md = R.iso.slice(5), sym = d.sym;
    const kr = S.cur !== 'USD' && d.tax.dispKrw != null && d.realized.krw != null && d.tax.disp > 0;
    const Rw = kr ? d.tax.dispKrw / d.tax.disp : (S.cur === 'USD' ? 1 : rate());
    const M = (x, o) => m(S.cur === 'USD' ? x : x / rate(), o);
    const P = x => { if (!(x > 0) || !isFinite(x)) return '—'; if (S.hide) return (S.cur === 'USD' ? '$' : '₩') + pvW(PVM.px); if (S.cur === 'USD') return px(x); if (x >= 1000) return '₩' + rw(nf('ko-KR', 0, 0).format(Math.round(x))); if (x >= 100) return '₩' + rw(nf('ko-KR', 0, 1).format(x)); if (x >= 1) return '₩' + rw(nf('ko-KR', 2, 2).format(x)); return px(x).replace('$', '₩'); };
    const rz = kr ? d.realized.krw : d.realized.usd * Rw;
    const hasTax = d.tax.n > 0;
    const pr = hasTax ? (kr ? d.tax.dispKrw : d.tax.disp * Rw) : num(d.sell.usd) * Rw;
    const recon = hasTax && d.tax.recon && d.sell.qty > 0;
    const cost = recon ? pr - rz : null, roi = recon && cost > 0 ? rz / cost * 100 : null;
    const uc = recon ? cost / d.sell.qty : null, us = d.sell.qty > 0 ? pr / d.sell.qty : null;
    const u = D.usdt[md] || {}, kp = d.sell.krwMarket && u.kimp != null ? num(u.kimp) : null;
    const ck = d.sell.costKnownPct;
    const dt = new Date(R.iso + 'T00:00:00');
    const fills = arr(d.fills), fpx = f => num(f.px) * (kr ? (f.rate || Rw) : Rw), famt = f => num(f.usd) * (kr ? (f.rate || Rw) : Rw);
    const pt = d.pathTs || {}, path = d.path || {};
    const bv = arr(d.buy.venues), sv = arr(d.sell.venues);
    const route = (bv.length ? bv.slice(0, 2).join('·') + (bv.length > 2 ? ' 외' : '') : d.carry ? '이전 보유분' : '') + (sv.length ? (bv.length || d.carry ? ' → ' : '') + sv.slice(0, 2).join('·') : '');
    const chips = (route ? '<span class="pill g sm">' + esc(route) + '</span>' : '') + (d.sell.krwMarket ? '<span class="pill a sm">원화 마켓 매도</span>' : '') + (arr(d.aliases).length ? '<span class="pill g sm" title="같은 코인 다른 표기 합침">' + esc(arr(d.aliases).join(' · ')) + ' 포함</span>' : '');
    const ckTxt = ck == null ? '' : '원가 확인 ' + (ck >= 99.95 ? '100' : nf('ko-KR', 0, 1).format(ck)) + '%';
    const payN = Math.min(num(d.sell.n), num((d.sell.pay || {}).n)), convN = Math.min(num(d.sell.n) - payN, num((d.sell.conv || {}).n)), saleN = num(d.sell.n) - payN - convN;
    const kindsN = [[saleN, '매도'], [convN, '전환'], [payN, '스왑 지불']].filter(x => x[0] > 0);
    const cntTxt = kindsN.length ? kindsN.map(x => x[1] + ' ' + x[0] + '회').join(' · ') + ' 체결' : '매도 체결 0회';
    const dispL = (kindsN.length ? kindsN.map(x => x[1]).join('·') : '매도') + ' 대금';
    const fbTxt = num(d.tax.fb) ? '평균가 대체 ' + d.tax.fb + '행 포함' : '';
    const eq = recon ? dispL + ' ' + '<span class="num">' + M(pr) + '</span>' + ' − 원가 ' + '<span class="num">' + M(cost) + '</span>' + (ckTxt ? ' · ' + ckTxt : '') + (fbTxt ? ' · ' + fbTxt : '')
      : (d.sell.n ? dispL + ' ' + '<span class="num">' + M(pr) + '</span>' + (ckTxt ? ' · ' + ckTxt : '') + (hasTax ? ' · <span title="세금 명세 손익과 카드 실현이 ' + esc(m(Math.abs(num(d.tax.diff)))) + ' 달라 원가·수익률은 생략">원가 대조 차이</span>' : '') : '그날 ' + esc(sym) + ' 매도 기록 없음');
    const fxd = (() => {
      if (!(kr && d.tax.acqKrw != null && d.tax.fxDiffKrw != null && Math.abs(num(d.tax.fxDiffKrw)) >= 1)) return '';
      const fxA = recon ? cost - num(d.tax.acqKrw) : null, feeA = -num(d.tax.feeKrw);
      const ok = fxA != null && Math.abs(fxA + feeA - num(d.tax.fxDiffKrw)) <= 2;
      const tip = '세금 명세 원화 손익 ' + M(num(d.tax.pnlKrw)) + ' − 화면 원화 실현 ' + M(rz) + ' = ' + M(num(d.tax.fxDiffKrw), { sign: true }) + (ok ? ' (취득 환율 차 + 수수료)' : '');
      return '<div class="cap num rfxd" title="' + esc(tip) + '">세금 명세 원화 취득 ' + '<span class="num">' + M(num(d.tax.acqKrw)) + '</span>' + ' · '
        + (ok ? '취득 환율 차 ' + '<span class="num">' + M(fxA, { sign: true }) + '</span>' + (Math.abs(feeA) >= 0.5 ? ' · 수수료 ' + '<span class="num">' + M(feeA, { sign: true }) + '</span>' : '')
          : '화면 실현과 차 ' + '<span class="num">' + M(num(d.tax.fxDiffKrw), { sign: true }) + '</span>' + '(취득 환율 차·수수료)') + '</div>';
    })();
    const stats = [];
    if (roi != null) stats.push(['수익률', '<span class="' + cls(rz) + '">' + pctS(roi, 1) + '</span>', '원가 대비']);
    if (kp != null) stats.push(['김프', pctS(kp, 2), u.usdt ? 'USDT ₩' + nf('ko-KR').format(num(u.usdt)) : '그날 마감']);
    const pGap = (a, b, mn) => a && b ? (Math.floor(b / 60) - Math.floor(a / 60)) * 60 : mn * 60;
    if (path.dep_to_sell_min != null) stats.push(['입금→첫 매도', durTxt(pGap(pt.deposit, pt.first_sell, path.dep_to_sell_min)), cntTxt]);
    else if (path.hold_min != null) stats.push(['매수→마지막 매도', durTxt(pGap(pt.first_buy, pt.last_sell, path.hold_min)), path.first_buy ? path.first_buy + ' 첫 매수' : '']);
    else if (d.carry && d.carry.held_days != null) stats.push(['보유', d.carry.held_days + '일', d.carry.first_buy_date ? (+d.carry.first_buy_date.slice(5, 7)) + '/' + (+d.carry.first_buy_date.slice(8)) + ' 첫 매수' : '']);
    if (stats.length < 3 && d.sell.n && kindsN.length) stats.push([kindsN[0][1] + ' 체결', kindsN[0][0] + '회', kindsN.length > 1 ? kindsN.slice(1).map(x => x[1] + ' ' + x[0] + '회').join(' · ') + ' 별도' : sv.slice(0, 2).join(' · ')]);
    const rhBar = recon && pr > 0 && cost > 0 ? '<div class="rhbar">' + (rz >= 0 ? '<div class="rbar"><i style="width:' + (cost / pr * 100).toFixed(1) + '%"></i><i class="p" style="width:' + (rz / pr * 100).toFixed(1) + '%"></i></div><div class="rbl num"><span>' + q(num(d.sell.qty)) + ' ' + esc(sym) + ' · ' + dispL + ' 중 원가 ' + Math.round(cost / pr * 100) + '%</span><span class="up">차익 ' + Math.round(rz / pr * 100) + '%</span></div>'
      : '<div class="rbar"><i style="width:' + (pr / cost * 100).toFixed(1) + '%"></i><i class="n" style="width:' + (-rz / cost * 100).toFixed(1) + '%"></i></div><div class="rbl num"><span>' + q(num(d.sell.qty)) + ' ' + esc(sym) + ' · 원가 중 회수 ' + Math.round(pr / cost * 100) + '%</span><span class="down">손실 ' + Math.round(-rz / cost * 100) + '%</span></div>') + '</div>' : '';
    const head = '<div class="rch"><div class="rcl"><div class="row gap8 rcn">' + icon(sym, 'sm', D.symLogo[String(sym).toUpperCase()] || {}) + '<b class="rsym">' + esc(sym) + '</b>' + chips + '</div>'
      + '<div class="rbig num ' + cls(rz) + '">' + M(rz, { sign: true }) + '</div><div class="cap num">' + eq + '</div>' + rhBar + fxd + '</div>'
      + (stats.length ? '<div class="rst">' + stats.slice(0, 3).map(x => '<div><span class="l">' + x[0] + '</span><b class="num">' + x[1] + '</b><span class="s num">' + esc(x[2]) + '</span></div>').join('') + '</div>' : '') + '</div>';
    const nodes = [];
    const fMin = ts => fills.filter(f => f.ts && Math.floor(f.ts / 60) === Math.floor(ts / 60));
    const fKind = fs => fs.length && fs.every(f => f.pay) ? '스왑 지불' : fs.length && fs.every(f => f.conv) ? '전환' : '매도';
    const nodeT = (fs, title) => { const k = fKind(fs); return k === '매도' ? title : title.replace(/매도$/, k); };
    const sellNode = (ts, title) => { const fs = fMin(ts); if (!fs.length) return { ts, t: kstHM(ts), up: true, title, lines: [] }; title = nodeT(fs, title);
      const fq = sum(fs, f => num(f.q)), fa = sum(fs, famt), fp = fq > 0 ? fa / fq : 0;
      return { ts, t: kstHM(ts), up: true, title: title + (fs.length > 1 ? ' <span class="t2">· ' + fs.length + '회 체결</span>' : ''), lines: [q(fq) + ' ' + esc(sym), (fs.length > 1 ? '평균 ' : '체결 ') + P(fp) + (uc && fp > 0 ? ' <span class="' + cls(fp - uc) + '">(' + pctS((fp / uc - 1) * 100, 1) + ')</span>' : ''), '<span class="t2">' + M(fa) + '</span>'] }; };
    const sameMin = pt.first_sell && pt.last_sell && Math.floor(pt.first_sell / 60) === Math.floor(pt.last_sell / 60);
    if (pt.first_buy) {
      const ks = Object.keys(d.buy.kinds || {}).sort((a, b) => d.buy.kinds[b] - d.buy.kinds[a]);
      nodes.push({ ts: pt.first_buy, t: path.first_buy || kstHM(pt.first_buy), title: '매수' + (bv.length ? ' · ' + esc(bv.slice(0, 2).join('·')) : ''), lines: [esc(ks.map(k0 => shortK(k0) + ' ' + d.buy.kinds[k0] + '건').join(' + ')),
        uc ? '매도분 평균 매수가 <b>' + P(uc) + '</b>' : (d.buy.vwap ? '평균 매수 ' + P(num(d.buy.vwap) * Rw) : ''), recon ? '<span class="t2">원가 ' + M(cost, { compact: true }) + '</span>' : ''] });
    } else if (d.carry && d.carry.first_buy_date) {
      const fb = d.carry.first_buy_date;
      nodes.push({ ts: null, t: (+fb.slice(5, 7)) + '/' + (+fb.slice(8)), title: '이전 매수분', lines: [uc ? '매도분 평균 매수가 <b>' + P(uc) + '</b>' : '', recon ? '<span class="t2">원가 ' + M(cost, { compact: true }) + '</span>' : ''] });
    }
    if (pt.deposit && d.dep.first) nodes.push({ ts: pt.deposit, t: path.deposit || kstHM(pt.deposit), title: esc(path.deposit_venue || d.dep.first.v || '') + ' 입금 확인', lines: ['첫 입금 ' + qXf(num(d.dep.first.q)) + ' ' + esc(sym), '입금 ' + d.dep.n + '회 · ' + qXf(num(d.dep.qty)) + ' ' + esc(sym), d.dep.first.carry ? '<span class="t2">원가 승계</span>' : ''] });
    if (pt.first_sell) nodes.push(sellNode(pt.first_sell, pt.last_sell && pt.last_sell !== pt.first_sell && !sameMin ? '첫 매도' : '매도'));
    if (pt.last_sell && pt.last_sell !== pt.first_sell && !sameMin) nodes.push(sellNode(pt.last_sell, '마지막 매도'));
    (() => { const byM = new Map(); fills.filter(f => f.conv && f.ts).forEach(f => { const k = Math.floor(f.ts / 60); byM.set(k, (byM.get(k) || 0) + num(f.usd)); });
      const have = new Set(nodes.filter(n0 => n0.ts).map(n0 => Math.floor(n0.ts / 60)));
      Array.from(byM.entries()).filter(e => !have.has(e[0])).sort((a, b) => b[1] - a[1]).slice(0, 2).forEach(e => {
        const f0 = fills.find(f => f.conv && Math.floor(f.ts / 60) === e[0]); const n0 = sellNode(f0.ts, '전환');
        n0.title = esc(f0.conv === '원화 환전' ? '원화 환전' : '스테이블 교환') + n0.title.replace(/^전환/, ''); nodes.push(n0); }); })();
    nodes.sort((a, b) => (a.ts == null ? -1 : b.ts == null ? 1 : a.ts - b.ts));
    const upN = nodes.filter(n0 => n0.up).length;
    const mGap = (a, b) => (Math.floor(b / 60) - Math.floor(a / 60)) * 60;
    const segTxt = (a, b) => a.up && b.up ? (upN > 2 ? '+' + durTxt(mGap(a.ts, b.ts)) : cntTxt + ' · ' + durTxt(mGap(a.ts, b.ts))) : a.ts == null ? (d.carry && d.carry.held_days != null ? '보유 ' + d.carry.held_days + '일' : '') : '+' + durTxt(mGap(a.ts, b.ts));
    const flow = nodes.length >= 2 ? '<section class="rsec rflow"><div class="rtt">흐름</div><div class="rtl" style="--n:' + nodes.length + '">' + nodes.map((n0, i) => { const nx = nodes[i + 1];
      return '<div class="rn' + (n0.up ? ' up' : '') + (nx && nx.up ? ' toup' : '') + '"><div class="rtr"><i class="dot"></i>' + (nx ? '<i class="ln"></i><span class="pl num">' + esc(segTxt(n0, nx)) + '</span>' : '') + '</div>'
        + '<div class="rtx"><b class="tm num">' + esc(n0.t) + '</b><span class="tt">' + n0.title + '</span>' + n0.lines.filter(Boolean).map(l => '<span class="ln2 num">' + l + '</span>').join('') + '</div></div>'; }).join('') + '</div></section>' : '';
    const sc = (() => {
      const pts = fills.filter(f => f.ts && num(f.px) > 0).map(f => ({ ts: f.ts, p: fpx(f), a: famt(f), f }));
      if (!pts.length) return '';
      const tw = t => Array.from(String(t).replace(PV_RE, '$1').replace(RS_RE, '$1')).reduce((a, c) => a + (/[\u3131-\uD79D]/.test(c) ? 11.5 : 7), 0);
      const labs = [uc ? '평단 ' + P(uc) : '', us ? '평균 ' + P(us) : ''];
      const W = Math.round(Math.max(300, Math.min(756, S.mobile ? (window.innerWidth || 390) - 28 : 756))), H = S.mobile ? 200 : 260, L = 14, RT = Math.max(S.mobile ? 70 : 84, Math.ceil(Math.max.apply(null, labs.map(tw))) + 14), T = 14, B = 26;
      let t0 = Math.min.apply(null, pts.map(x => x.ts)), t1 = Math.max.apply(null, pts.map(x => x.ts));
      if (t1 - t0 < 600) { t0 -= 900; t1 += 900; }
      const ys = pts.map(x => x.p).concat(us ? [us] : [], uc ? [uc] : []);
      let y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys); const pad = (y1 - y0) * 0.1 || y1 * 0.05 || 1; y0 = Math.max(0, y0 - pad); y1 += pad;
      const X = t => L + (t - t0) / (t1 - t0) * (W - L - RT - 14), Y = v => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);
      const amx = Math.max.apply(null, pts.map(x => x.a)) || 1;
      const stp = [5, 10, 15, 30, 60, 120, 180, 360, 720, 1440].find(s0 => (t1 - t0) / 60 / s0 <= (S.mobile ? 4 : 7)) || 1440;
      const ticks = []; for (let t = Math.ceil((t0 + 32400) / (stp * 60)) * stp * 60 - 32400; t <= t1; t += stp * 60) ticks.push(t);
      const hline = (v, c0, lab, dash, dy) => v ? '<line x1="' + L + '" x2="' + (W - RT + 4) + '" y1="' + Y(v).toFixed(1) + '" y2="' + Y(v).toFixed(1) + '" style="stroke:var(' + c0 + ')" stroke-opacity=".75"' + (dash ? ' stroke-dasharray="3 4"' : '') + '/><text x="' + (W - RT + 8) + '" y="' + (Y(v) + 4 + (dy || 0)).toFixed(1) + '" style="fill:var(' + c0 + ')">' + esc(lab) + '</text>' : '';
      const best = pts.reduce((a, b) => (b.p > a.p ? b : a));
      const ov = uc && us ? Math.abs(Y(us) - Y(uc)) < 13 : false;
      const svg = '<svg class="rsc" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc((dt.getMonth() + 1) + '월 ' + dt.getDate() + '일 ' + sym + ' 매도 체결가 ' + pts.length + '건') + '">'
        + '<line x1="' + L + '" x2="' + (W - RT + 4) + '" y1="' + (H - B) + '" y2="' + (H - B) + '" style="stroke:var(--line)"/>'
        + ticks.map(t => '<text x="' + X(t).toFixed(1) + '" y="' + (H - 6) + '" text-anchor="middle" class="tk">' + kstHM(t) + '</text>').join('')
        + hline(uc, '--accent', labs[0], true, ov ? (Y(uc) >= Y(us) ? 7 : -7) : 0)
        + hline(us, '--up', labs[1], false, ov ? (Y(us) > Y(uc) ? 7 : -7) : 0)
        + pts.map(x => '<circle cx="' + X(x.ts).toFixed(1) + '" cy="' + Y(x.p).toFixed(1) + '" r="' + (4 + (S.mobile ? 11 : 15) * Math.sqrt(x.a / amx)).toFixed(1) + '" style="fill:var(--up);stroke:var(--up)" fill-opacity="' + (x.f.pay ? '0' : '.28') + '"' + (x.f.pay ? ' stroke-width="1.5"' : '') + '><title>' + esc(kstHM(x.ts) + (x.f.pay ? ' · 스왑 지불' : '') + ' · ' + P(x.p) + ' · ' + q(num(x.f.q)) + ' ' + sym + ' · ' + M(x.a)) + '</title></circle>').join('')
        + '</svg>';
      return '<section class="rsec rscs"><div class="row rtth"><span class="rtt">' + (kindsN.length ? kindsN.map(x => x[1]).join('·') : '매도') + ' 체결 — 점 크기 = 금액 <span class="mut">' + (S.cur === 'USD' ? '$' : '₩') + '/' + esc(sym) + (payN && kindsN.length > 1 ? ' · 빈 원 = 스왑 지불' : '') + '</span></span><span class="sp"></span><span class="cap num">최고 체결 ' + kstHM(best.ts) + (best.f && best.f.conv ? ' · ' + esc(best.f.conv) : '') + ' <b class="up">' + P(best.p) + '</b>' + (uc ? ' (평균 매수가의 ' + nf('ko-KR', 1, 1).format(best.p / uc) + '배)' : '') + '</span></div>'
        + '<div class="rscw">' + svg + '</div>' + (d.fillsTotal > fills.length ? '<div class="cap">큰 매도 ' + fills.length + '건만 표시 · 전체 ' + d.fillsTotal + '건</div>' : '') + '</section>';
    })();
    const rv = D.reviews[md], ai = isAI(rv);
    const ai1 = (() => {
      if (!ai) return '';
      const hit = t => String(t || '').toUpperCase().indexOf(String(sym).toUpperCase()) >= 0;
      const top1 = topRcptSym(R.iso) === sym || topRcptSym(R.iso) === R.sym;
      let t = arr(rv.obs).find(hit) || (top1 && arr(rv.obs)[0]) || (hit(rv.note) ? rv.note : '') || (hit(rv.sum) ? rv.sum : '');
      if (!t) return '';
      const mt = String(t).match(/^\s*\[([^\]]{1,12})\]\s*/), tag = mt ? mt[1] : '';
      if (mt) t = String(t).slice(mt[0].length);
      const long = String(t).length > (S.mobile ? 60 : 140);
      return '<div class="rai"><b>AI 복기</b>' + (tag ? '<span class="pill g sm aib-l">' + esc(pvOn() ? '가림' : tag) + '</span>' : '') + (rv.stale ? '<span class="pill w sm">다시 만들기 대기</span>' : '')
        + '<span class="rat aib' + (long && !R.aiOpen ? ' clamp2' : '') + (rv.stale ? ' mut' : '') + '">' + esc(revTxt(t)) + '</span>' + (long ? '<button class="link" data-a="rcptAi" aria-expanded="' + !!R.aiOpen + '">' + (R.aiOpen ? '접기' : '펼치기') + '</button>' : '') + '</div>';
    })();
    const lp = dayContrib(R.iso).filter(x => x.lp && String(x.lpN ? x.pool : (x.p && x.p.sym) || x.sym).toUpperCase().split(/[\s/]+/).indexOf(String(sym).toUpperCase()) >= 0);
    const lpTxt = lp.length ? '<span class="cap">같은 날 <b class="t1">' + esc(lp.map(x => x.lpN ? x.sym + ' ' + x.lpN + '개' : String(x.sym)).join(' · ')) + '</b> 실현 <b class="num ' + clsV(sum(lp, x => KV(x.v, x.vk))) + '">' + m(sum(lp, x => KV(x.v, x.vk)), { sign: true }) + '</b> 은 따로</span>' : '';
    const foot = '<div class="rft">' + lpTxt + '<span class="sp"></span><button class="btn sm" data-a="rcptDay">그날 ' + esc(sym) + ' 기록 보기</button></div>';
    const rk = rkSection(R, d, { P, M, uc, sym, dt });
    return head + dmRcptHTML(R, d) + (rk.ok ? rk.html : rk.html + sc) + flow + ai1 + foot;
  }
  function rcptDrawer() {
    const R = S.rcpt; if (!R) return '';
    const c = (S.rcptC || {})[R.key] || {}, d = c.d;
    const dt = new Date(R.iso + 'T00:00:00');
    const ttl = '차익 영수증 · ' + (dt.getMonth() + 1) + '월 ' + dt.getDate() + '일 (' + DOWS[dt.getDay()] + ')' + (R.rank ? ' 그날 실현 기여 ' + R.rank + '위' : '');
    let body;
    if (d && d.empty) body = '<div class="empty"><div class="eic">' + IC.cal + '</div><b>그날 ' + esc(R.sym) + ' 기록이 없어요</b></div>';
    else if (d) body = rcptBody(R, d) + (c.st === 'load' ? '<div class="cap">새 기록으로 다시 계산하는 중…</div>' : c.st === 'err' ? '<div class="fbnote">새로 불러오지 못해 직전 영수증을 보여 줘요</div>' : '');
    else if (c.st === 'err') body = '<div class="empty"><div class="eic">' + IC.alert + '</div><b>' + (c.old ? '서버를 업데이트하면 볼 수 있어요' : '영수증을 불러오지 못했어요') + '</b>' + (c.old ? '' : '<button class="btn sm" data-a="rcptRetry" style="margin-top:10px">' + IC.undo + ' 다시 시도</button>') + '</div>';
    else body = '<div class="rload" aria-busy="true"><i></i><i></i><i></i><span class="cap">영수증 불러오는 중…</span></div>';
    const rz9 = d && !d.empty && d.realized ? KV(num(d.realized.usd), d.realized.krw != null ? num(d.realized.krw) : null) : null;
    const rsum = rz9 != null ? '<span class="rsum num"><b>' + esc(R.sym) + '</b> <span class="' + cls(rz9) + '">' + m(rz9, { sign: true, compact: true }) + '</span></span>' : '';
    return '<div class="drawer-bg" data-a="drawerClose"></div><aside class="drawer rcpt" role="dialog" aria-modal="true" aria-label="' + esc(R.sym + ' 차익 영수증') + '"><div class="dh"><span class="cap rtop">' + esc(ttl) + '</span>' + rsum + '<span class="sp"></span><button class="iconbtn" data-a="drawerClose" aria-label="닫기">' + IC.close + '</button></div>' + body + '</aside>';
  }

  const FR_IVS = [['5m', '5분봉'], ['1m', '1분봉']];
  const frOn = R => S.drawer === 'frcpt' && S.frc && S.frc.key === R.key;
  const frSide = s => (s === 'LONG' ? '롱' : s === 'SHORT' ? '숏' : '');
  const frMD = ts => { const x = new Date((ts + 32400) * 1000); return pad2(x.getUTCMonth() + 1) + '-' + pad2(x.getUTCDate()) + ' ' + pad2(x.getUTCHours()) + ':' + pad2(x.getUTCMinutes()); };
  function openFutRcpt(iso, exKey, rank) {
    if (!S.D || !isISO(iso)) return;
    const first = S.drawer !== 'frcpt';
    const ae = document.activeElement, back = first ? (ae && ae.getAttribute && ae.getAttribute('data-a') ? { el: ae, a: ae.getAttribute('data-a'), v: (ae.getAttribute('data-fv') || ae.getAttribute('data-v')) } : null) : (S.frc && S.frc.back);
    S.drawer = 'frcpt'; S.pop = null; S.modal = null;
    S.frc = { iso, key: iso, ex: String(exKey || ''), rank: +rank || 0, coin: '', iv: '5m', venue: '', back };
    if (first) drawerHist();
    frLoad();
    renderOverlay();
    if (first) { const b = $('#overlay .drawer [data-a="drawerClose"]'); if (b) b.focus(); }
  }
  function frLoad(force) {
    const R = S.frc; if (!R || !S.D) return;
    const C = S.frC || (S.frC = {}), c = C[R.key];
    if (!force && c && (c.st === 'load' || (c.st === 'ok' && c.at === S.D.builtAt))) { if (c.st === 'ok') frPick(R, c.d); return; }
    const at = S.D.builtAt;
    C[R.key] = { st: 'load', at, d: c && c.d };
    if (c && c.d && !c.d.empty) frPick(R, c.d);
    fetch('/api/fut_receipt?date=' + R.iso, { cache: 'no-store' })
      .then(r => { if (r.status === 401) { onUnauthorized(); throw new Error('401'); } if (r.status === 404) { const e = new Error('old'); e.old = true; throw e; } return r.json().catch(() => null).then(d => { if (r.status === 503) { const e = new Error('색인을 만드는 중 — 잠시 뒤 다시'); e.idx = true; throw e; } if (!r.ok || !d || !d.ok) throw new Error((d && d.error) || ('HTTP ' + r.status)); return d; }); })
      .then(d => { C[R.key] = { st: 'ok', at, d }; if (frOn(R)) frPick(S.frc, d); })
      .catch(e => { C[R.key] = { st: 'err', at: 0, old: !!(e && e.old), msg: String((e && e.message) || e), d: C[R.key] && C[R.key].d }; })
      .then(() => { if (frOn(R)) renderOverlay(); });
  }
  function frPick(R, d) {
    const cs = arr(d && d.coins);
    if (!cs.length) return;
    const fl = frExKey(R, d) ? frCoins(R, d) : null;
    if (!R.coin || !(fl || cs).some(c => c.coin === R.coin)) {
      const byEx = fl ? fl : R.ex ? cs.filter(c => arr(c.venues).some(v => v.exKey === R.ex)).sort((a, b) => Math.abs(num(arr(b.venues).filter(v => v.exKey === R.ex).reduce((s0, v) => s0 + num(v.usd), 0))) - Math.abs(num(arr(a.venues).filter(v => v.exKey === R.ex).reduce((s0, v) => s0 + num(v.usd), 0)))) : [];
      R.coin = (byEx[0] || cs[0]).coin;
      R.venue = R.ex && byEx[0] ? R.ex : '';
    }
    frChart();
  }
  const frK = R => R.key + '|' + R.coin + '|' + R.iv + '|' + (R.venue || '');
  function frChart(force) {
    const R = S.frc; if (!R || !R.coin || !S.D) return;
    const k = frK(R), C = S.frX || (S.frX = {}), c = C[k];
    if (!force && c && (c.st === 'load' || c.st === 'prep' || c.st === 'old' || (c.st === 'ok' && c.at === S.D.builtAt))) { if (c.st === 'ok') frPrefetch(R); return; }
    const gen = (S.frGen = (S.frGen || 0) + 1);
    C[k] = { st: 'load', gen, at: S.D.builtAt, n: 0, d: c && c.d };
    frFetch(R, k, { coin: R.coin, iv: R.iv, venue: R.venue }, gen, 0);
  }
  function frPrefetch(R) {
    if (!R || !frOn(R) || R.preOff || !S.D || R.iv !== '5m') return;
    const d = ((S.frC || {})[R.key] || {}).d, X = S.frX || {};
    const P = S.frPre, pc = P && X[P.k];
    if (pc && pc.gen === P.gen && (pc.st === 'load' || pc.st === 'prep')) return;
    const vk = d ? frExKey(R, d) : '';
    const c = (d ? frCoins(R, d) : []).slice(0, 3).map(x => x.coin).filter(x => x !== R.coin).map(x => ({ coin: x, k: R.key + '|' + x + '|5m|' + vk })).find(x => !X[x.k]);
    if (!c) return;
    const gen = (S.frGen = (S.frGen || 0) + 1);
    X[c.k] = { st: 'load', gen, at: S.D.builtAt, n: 0, pre: true };
    S.frPre = { k: c.k, gen };
    frFetch(R, c.k, { coin: c.coin, iv: '5m', venue: vk }, gen, 0);
  }
  function frFetch(R, k, v, gen, n) {
    const C = S.frX, live = () => !!C[k] && C[k].gen === gen, pre = !!(C[k] && C[k].pre);
    const url = '/api/receipt_chart?side=fut&date=' + R.iso + '&sym=' + encodeURIComponent(v.coin) + '&iv=' + v.iv + (v.venue ? '&venue=' + encodeURIComponent(v.venue) : '');
    fetch(url, { cache: 'no-store' })
      .then(r => {
        if (r.status === 401) { onUnauthorized(); throw new Error('로그인이 필요해요'); }
        if (r.status === 404) { const e = new Error('old'); e.old = true; throw e; }
        return r.json().catch(() => null).then(d => {
          if ((r.status === 202 && d && d.ok) || r.status === 503) return { prep: d || {}, idx: r.status === 503 };
          if (!r.ok || !d || !d.ok) throw new Error((d && d.error) || ('HTTP ' + r.status));
          return { d };
        });
      })
      .then(x => {
        if (!live()) return;
        if (x.prep) {
          if (pre && x.prep.status === 'busy' && !(S.frc && frK(S.frc) === k)) { delete C[k]; R.preOff = true; return; }
          if (n + 1 >= RC_TRIES) { C[k] = { st: 'err', gen, at: 0, msg: '시세를 1분 넘게 받는 중이에요 — 잠시 뒤 다시 눌러 주세요', d: C[k].d }; return; }
          C[k] = Object.assign({}, C[k], { st: 'prep', n: n + 1, busy: x.prep.status === 'busy', idx: !!x.idx });
          setTimeout(() => { if (!live()) return; if (!frOn(R)) { delete C[k]; return; } frFetch(S.frc, k, v, gen, n + 1); }, Math.min(10, Math.max(1, num(x.prep.retryAfter) || 3)) * 1000);
          return;
        }
        C[k] = { st: 'ok', gen, at: C[k].at, d: x.d };
      })
      .catch(e => { if (live()) C[k] = { st: e && e.old ? 'old' : 'err', gen, at: 0, msg: e && e.old ? '' : String((e && e.message) || e), d: C[k].d }; })
      .then(() => { if (S.frc && frOn(R) && frK(S.frc) === k) renderOverlay(); if (pre || (S.frc && frK(S.frc) === k)) frPrefetch(S.frc); });
  }
  function futRcptDrawer() {
    const R = S.frc; if (!R) return '';
    const c = (S.frC || {})[R.key] || {}, d = c.d;
    const dt = new Date(R.iso + 'T00:00:00');
    const ttl = '선물 영수증 · ' + (dt.getMonth() + 1) + '월 ' + dt.getDate() + '일 (' + DOWS[dt.getDay()] + ')', rkT = R.rank ? '그날 실현 기여 ' + R.rank + '위' : '';
    let body;
    if (d && d.empty) body = '<div class="empty"><div class="eic">' + IC.cal + '</div><b>그날 선물 정산이 없어요</b><span class="cap">기여 줄에도 선물 줄이 없어요</span></div>';
    else if (d) body = futRcptBody(R, d) + (c.st === 'load' ? '<div class="cap">새 기록으로 다시 계산하는 중…</div>' : c.st === 'err' ? '<div class="fbnote">새로 불러오지 못해 직전 영수증을 보여 줘요 <button class="link" data-a="frRetry">다시 시도</button></div>' : '');
    else if (c.st === 'err') body = '<div class="empty"><div class="eic">' + IC.alert + '</div><b>' + (c.old ? '서버를 업데이트하면 볼 수 있어요' : '영수증을 불러오지 못했어요') + '</b>' + (c.old ? '' : '<span class="cap">' + esc(errTxt(c.msg || '')) + '</span><button class="btn sm" data-a="frRetry" style="margin-top:10px">' + IC.undo + ' 다시 시도</button>') + '</div>';
    else body = '<div class="rload" aria-busy="true"><i></i><i></i><i></i><span class="cap">영수증 불러오는 중…</span></div>';
    const fx = d && !d.empty ? frFocus(R, d) : null;
    const tv = d && !d.empty && d.total ? (fx ? KV(num(fx.usd), fx.krw) : KV(num(d.total.usd), d.total.krw != null ? num(d.total.krw) : null)) : null;
    const rsum = tv != null ? '<span class="rsum num"><b>' + (fx ? esc(fx.ex) : '선물') + '</b> <span class="' + cls(tv) + '">' + m(tv, { sign: true, compact: true }) + '</span></span>' : '';
    return '<div class="drawer-bg" data-a="drawerClose"></div><aside class="drawer rcpt frc" role="dialog" aria-modal="true" aria-label="선물 영수증"><div class="dh"><span class="cap rtop"><span class="rtm">' + esc(ttl) + '</span>' + (rkT ? '<span class="rtsub"> ' + esc(rkT) + '</span>' : '') + '</span>' + rsum + '<span class="sp"></span><button class="iconbtn" data-a="drawerClose" aria-label="닫기">' + IC.close + '</button></div>' + body + '</aside>';
  }
  const frFocus = (R, d) => { const exs = arr(d && d.byEx); return R && R.ex && exs.length > 1 && d.exKinds && d.exKinds[R.ex] ? exs.find(x => x.exKey === R.ex) || null : null; };
  const frExKey = (R, d) => { const fx = frFocus(R, d); return fx && arr(d.coins).some(c => c && c.exStats) ? fx.exKey : ''; };
  const frCoins = (R, d) => { const k = frExKey(R, d), cs = arr(d && d.coins); return k ? cs.filter(c => c.exStats && c.exStats[k]).sort((a, b) => Math.abs(num(b.exStats[k].usd)) - Math.abs(num(a.exStats[k].usd))) : cs; };
  function futRcptBody(R, d) {
    const t = d.total || {}, tv = KV(num(t.usd), t.krw != null ? num(t.krw) : null);
    const rk = num(t.usd) ? tv / num(t.usd) : 1, V = (u, kw) => (kw != null && isFinite(kw) ? KV(num(u), num(kw)) : num(u) * rk);
    const exs = arr(d.byEx), coins = arr(d.coins);
    const fx = frFocus(R, d), xk = fx && d.exKinds && d.exKinds[fx.exKey] || null;
    const H = xk ? { v: KV(num(fx.usd), fx.krw), r: V(xk.realized, xk.realizedKrw), f: V(xk.fee, xk.feeKrw), u: V(xk.funding, xk.fundingKrw), ff: V(num(xk.fee) + num(xk.funding), xk.feeKrw != null && xk.fundingKrw != null ? num(xk.feeKrw) + num(xk.fundingKrw) : null), c: num(xk.closes), w: num(xk.wins), l: num(xk.losses) }
      : { v: tv, r: V(t.realized, t.realizedKrw), f: V(t.fee, t.feeKrw), u: V(t.funding, t.fundingKrw), ff: V(num(t.fee) + num(t.funding), t.feeKrw != null && t.fundingKrw != null ? num(t.feeKrw) + num(t.fundingKrw) : null), c: num(t.closes), w: num(t.wins), l: num(t.losses) };
    const nEv = xk ? num(fx.n) : exs.reduce((a, x) => a + num(x.n), 0);
    const bb = coins.some(c => arr(c.trades).some(x => x.feeIncl));
    const unX = xk ? arr(d.unpriced).filter(u => u.exKey === fx.exKey) : arr(d.unpriced);
    const pr = xk ? [Math.max(0, num(xk.closes) - unX.reduce((a, u) => a + num(u.n), 0)), num(xk.closes)] : coins.reduce((a, c) => [a[0] + num((c.priced || {}).n), a[1] + num((c.priced || {}).of)], [0, 0]);
    const head = '<div class="rch"><div class="rcl"><div class="row gap8 rcn"><span class="ic sm" style="background:var(--surface3);color:var(--text2)">' + IC.scale.replace('<svg', '<svg width="14" height="14"') + '</span><b class="rsym">선물 정산</b>'
      + (xk ? '<span class="pill a sm">' + esc(fx.ex) + '</span>' : exs.length ? '<span class="pill g sm">' + esc(exs.map(x => x.ex).join(' · ')) + '</span>' : '') + (pr[1] ? '<span class="pill ' + (pr[0] === pr[1] ? 'a' : 'g') + ' sm pvx">가격 확인 ' + pr[1] + '건 중 ' + pr[0] + '건</span>' : '')
      + (arr(d.stale).length ? '<span class="pill w sm">수집 지연</span>' : '') + '</div>'
      + '<div class="rbig num ' + cls(H.v) + '">' + m(H.v, { sign: true }) + '</div>'
      + '<div class="cap num sans"><span class="nowrap">' + (xk ? esc(fx.ex) + ' ' : '') + '실현 ' + mN(H.r, { sign: true }) + ' ·</span> <span class="nowrap">수수료 ' + mN(H.f, { sign: true }) + ' ·</span> <span class="nowrap">펀딩 ' + mN(H.u, { sign: true }) + (S.cur === 'USD' ? '' : ' ·') + '</span>' + (S.cur === 'USD' ? '' : ' <span class="nowrap">정산 시각 환율</span>') + '</div>'
      + (exs.length > 1 || bb ? '<div class="cap num frex">' + (xk ? '그날 선물 전체 <b class="' + clsV(tv) + '">' + m(tv, { sign: true, compact: true }) + '</b> = ' : '')
        + exs.map(x => esc(x.ex) + ' <b class="' + clsV(KV(num(x.usd), x.krw)) + '">' + m(KV(num(x.usd), x.krw), { sign: true, compact: true }) + '</b>' + (num(x.n) ? '<span class="mut pvx"> 정산 ' + num(x.n) + '건</span>' : '')).join(' · ') + (bb ? ' · 바이빗은 실현에 수수료 포함' : '') + (xk ? ' <button class="link" data-a="frAll">전체 보기</button>' : '') + '</div>' : '') + '</div>';
    const hs = coins.flatMap(c => arr(c.trades)).filter(x => x.holdS != null && (!xk || x.exKey === fx.exKey));
    const avgH = hs.length ? hs.reduce((a, x) => a + num(x.holdS), 0) / hs.length : null;
    const st = '<div class="rst"><div title="청산 = 주문 단위 · 정산 = 체결마다의 실현 줄(일별 기록의 건수)"><span class="l">' + (xk ? esc(fx.ex) + ' 청산' : '청산') + '</span><b class="num">' + H.c + '건</b><span class="s num sans"><span class="nowrap">' + H.w + '승 ' + H.l + '패' + (nEv && nEv !== H.c ? ' ·' : '') + '</span>' + (nEv && nEv !== H.c ? ' <span class="nowrap">정산 ' + nEv + '건</span>' : '') + '</span></div>'
      + '<div><span class="l">수수료·펀딩</span><b class="num ' + clsV(H.ff) + '">' + m(H.ff, { sign: true, compact: true }) + '</b><span class="s num sans nowrap">펀딩 ' + m(H.u, { sign: true, compact: true }) + '</span></div>'
      + (hs.length ? '<div><span class="l">평균 보유</span><b class="num rhold">' + durTxt(avgH) + '</b><span class="s num sans nowrap">진입 시각 있는 ' + hs.length + '건</span></div>' : '') + '</div>';
    const fk = frExKey(R, d), cl = frCoins(R, d), cE = x => (fk && x.exStats && x.exStats[fk]) || x, kl = fk ? esc(fx.ex) + ' 종목' : '종목';
    const c = cl.find(x => x.coin === R.coin) || cl[0];
    if (!c) return head + st + '</div>';
    const chips = cl.length > 1 ? '<div class="rkvn frch" role="group" aria-label="' + kl + '"><span class="cap rkvl">' + kl + '</span>' + cl.map(x => { const on = x.coin === c.coin, e = cE(x), v = KV(num(e.usd), e.krw);
      return '<button class="chip' + (on ? ' on' : '') + '" data-a="frCoin" data-v="' + esc(x.coin) + '" aria-pressed="' + on + '">' + esc(x.label) + ' <span class="num ' + clsV(v) + '">' + m(v, { sign: true, compact: true }) + '</span> <span class="mut num">· ' + num(e.closes) + '건</span></button>'; }).join('') + '</div>' : '';
    const sec = '<section class="rsec rkc frk"><div class="row rtth rkh"><span class="rtt">실제 시세 위 내 진입·청산</span><span class="sp"></span><div class="seg rkseg" role="group" aria-label="봉 간격">'
      + FR_IVS.map(o => '<button data-a="frIv" data-v="' + o[0] + '" class="' + (R.iv === o[0] ? 'on' : '') + '" aria-pressed="' + (R.iv === o[0]) + '">' + o[1] + '</button>').join('') + '</div></div>' + chips + rkFut(R, d, c) + '</section>';
    const ce = cE(c), ctr = fk ? arr(c.trades).filter(x => x.exKey === fk) : arr(c.trades), cfr = fk ? arr(c.fundingRows).filter(f => f.exKey === fk) : arr(c.fundingRows);
    const cv = KV(num(ce.usd), ce.krw), crk = num(ce.usd) ? cv / num(ce.usd) : rk, CV = (u, kw) => (kw != null && isFinite(kw) ? KV(num(u), num(kw)) : num(u) * crk);
    const tile = (l, vh, s0, c0) => '<div class="rkt"><span class="l">' + l + '</span><b class="num ' + (c0 || '') + '">' + vh + '</b><span class="s num">' + s0 + '</span></div>';
    const tiles = '<div class="rk4">' + tile((fk ? esc(fx.ex) + ' ' : '') + '순손익', m(cv, { sign: true, compact: true }), '실현 + 수수료 + 펀딩', clsV(cv)) + tile('실현', m(CV(ce.realized, ce.realizedKrw), { sign: true, compact: true }), num(ce.closes) + '건 · ' + num(ce.wins) + '승 ' + num(ce.losses) + '패', clsV(ce.realized))
      + tile('수수료', num(ce.fee) ? m(CV(ce.fee, ce.feeKrw), { sign: true, compact: true }) : '—', bb && ctr.some(x => x.feeIncl) ? '바이빗 몫은 실현에 포함' : '진입 + 청산', clsV(ce.fee))
      + tile('펀딩', num(ce.funding) ? m(CV(ce.funding, ce.fundingKrw), { sign: true, compact: true }) : '—', cfr.length ? cfr.length + '회' : '그날 펀딩 없음', clsV(ce.funding)) + '</div>';
    const cb = String(c.coin);
    const row = x => {
      const pv = KV(num(x.pnl), x.pnlKrw), fv = KV(num(x.fee), x.feeKrw);
      const sd = x.side ? '<span class="pill ' + (x.side === 'LONG' ? 'up' : 'down') + ' sm">' + (x.side === 'LONG' ? '▲ 롱' : '▼ 숏') + (x.lev ? ' ×' + esc(String(x.lev)) : '') + '</span>' : '<span class="pill g sm">방향 없음</span>';
      const pc = x.entryPx && x.exitPx ? (x.exitPx / x.entryPx - 1) * 100 * (x.side === 'SHORT' ? -1 : 1) : null;
      const l2 = x.px !== 'none' && x.exitPx
        ? q(num(x.qty)) + ' ' + esc(cb) + ' · 진입 <b>' + px(num(x.entryPx)) + '</b> → 청산 <b>' + px(num(x.exitPx)) + '</b>' + (pc != null ? ' <span class="' + cls(pc) + '">(' + pctS(pc, 1) + ')</span>' : '')
          + ' · ' + (x.entryTs ? (x.entryTs < num(x.exitTs) - 86400 || kstHM(x.entryTs) > kstHM(x.exitTs) ? frMD(x.entryTs) : kstHM(x.entryTs)) + ' → ' + kstHM(num(x.exitTs)) + (x.holdS != null ? ' (' + durTxt(num(x.holdS)) + ')' : '') + (x.entryEst ? ' · 진입 시각 추정' : '') : kstHM(num(x.exitTs)) + ' 청산 · 진입 시각 모름') + (x.px === 'derived' ? ' · 진입가는 정산 내역에서 계산했어요' : '') + (x.fundMaybe ? ' · 펀딩 포함 가능' : '')
        : '가격 없음 — 정산 금액만(' + esc(x.why || '가격 칸 없음') + ') · ' + kstHM(num(x.exitTs)) + ' 정산' + (num(x.rows) > 1 ? ' · ' + x.rows + '행 묶음' : '');
      return '<div class="frow" data-frt="' + esc(x.id) + '" tabindex="0">' + exLogo(x.exKey) + '<div class="fqm"><div class="row gap8"><b>' + esc(futSym(x.symbol)) + '</b>' + sd + (x.liq ? '<span class="pill w sm">강제청산</span>' : '') + '</div><div class="cap num">' + l2 + '</div></div>'
        + '<div class="fqr num"><b class="' + clsV(pv) + '">' + m(pv, { sign: true }) + '</b><span class="cap">' + (x.feeIncl ? '수수료 포함' + (x.feeInfo ? ' ' + m(num(x.feeInfo), { sign: true }) : '') : num(x.fee) ? '수수료 ' + m(fv, { sign: true }) : '') + '</span></div></div>';
    };
    const trs = ctr, tTot = fk ? num((c.tradesTotalEx || {})[fk]) : num(c.tradesTotal), cpr = ce.priced || {};
    const lst = '<section class="rsec frl"><div class="row rtth"><span class="rtt">' + (fk ? esc(fx.ex) + ' ' : '') + '청산 ' + trs.length + '건 · ' + esc(c.label) + '</span><span class="sp"></span><span class="cap num pvx">가격 ' + num(cpr.n) + '/' + num(cpr.of) + '</span></div>'
      + (trs.length ? uiPaged('frt:' + R.key + ':' + c.coin + ':' + fk, trs, x => row(x), { unit: '건' }) : '<div class="cap">그날 ' + (fk ? esc(fx.ex) + ' ' : '') + '이 종목 청산 없음 — 수수료·펀딩만</div>') + (tTot > trs.length ? '<div class="cap">큰 손익 ' + trs.length + '건만 표시 · 전체 ' + tTot + '건(합계는 전 건)</div>' : '')
      + (cfr.length ? uiFold('frc:fund', { cls: 'plain', head: '<b>펀딩 ' + cfr.length + '회</b><span class="cap num">' + mN(CV(ce.funding, ce.fundingKrw), { sign: true }) + '</span>', label: '펀딩 내역',
        body: () => uiPaged('frf:' + R.key + ':' + c.coin + ':' + fk, cfr, f => '<div class="row frf num"><span class="cap">' + kstHM(num(f.ts)) + ' · ' + esc(f.ex || f.exKey) + '</span><span class="sp"></span><b class="' + clsV(f.usd) + '">' + m(KV(num(f.usd), f.krw), { sign: true }) + '</b></div>', { unit: '회' }) }) : '') + '</section>';
    const un = unX;
    const ftxt = (pr[1] ? '가격 있는 청산 ' + pr[0] + '/' + pr[1] + '건' : '') + (un.length ? ' · ' + un.map(u => esc(u.ex) + ' ' + u.n + '건은 ' + esc(u.reason)).join(' · ') + '이라 정산 금액만' : '') + (d.other && num(d.other.usd) ? ' · 종목 없는 정산 ' + m(KV(num(d.other.usd), d.other.krw), { sign: true }) : '')
      + (num(d.coinEst) ? ' · 코인 정산 ' + num(d.coinEst) + '건은 지금 시세로 추정' : '');
    const foot = '<div class="rft"><span class="cap pvx">' + ftxt + '</span><span class="sp"></span><button class="btn sm" data-a="frFut">선물 상세 ›</button><button class="btn sm" data-a="frDay">그날 기록 보기</button></div>';
    return head + st + '</div>' + sec + tiles + lst + foot;
  }
  function rkFut(R, d, c) {
    const C = S.frX || {}, ch0 = C[frK(R)] || {};
    const loading = ch0.st === 'load' || ch0.st === 'prep';
    const x = ch0.st === 'ok' ? ch0.d : loading && ch0.d ? ch0.d : null;
    const H0 = 30 + (S.mobile ? 210 : 270) + 8 + (S.mobile ? 40 : 52) + 22;
    const skel = msg => '<div class="rscw rkw rksk"><div class="rkskb" style="height:' + H0 + 'px" aria-hidden="true"><i></i></div><div class="rkov"><span class="rkwait" role="status" aria-live="polite"><i class="spin" aria-hidden="true"></i>' + msg + '</span></div></div>';
    if (!x) {
      if (loading) return skel(ch0.idx ? '기록 색인을 만드는 중 — 잠시 뒤 다시 확인해요' : ch0.busy ? '다른 차트를 먼저 받는 중 — 차례를 기다려요' : esc(c.label) + ' ' + (RC_IVK[R.iv] || '') + ' 시세 받는 중…' + (ch0.n ? ' <span class="mut">(' + ch0.n + '번째 확인)</span>' : ''));
      if (ch0.st === 'err') return '<div class="rkwhy cap" role="status">실제 시세를 받지 못해 진입·청산 점만 보여 줘요 · ' + esc(errTxt(ch0.msg || '오류')) + ' <button class="link" data-a="frChartRetry">다시 받기</button></div>';
      return '';
    }
    const ch = x.chart || {}, cs0 = arr(ch.candles).filter(r => Array.isArray(r) && r.length >= 6 && isFinite(r[2]) && isFinite(r[3]));
    const marks = arr(x.marks).filter(k => k && k.ts), spans = arr(x.spans).filter(s0 => s0 && num(s0.entryPx) > 0 && num(s0.exitPx) > 0);
    const vns = arr(x.venues);
    const vchips = vns.length > 1 ? '<div class="rkvn" role="group" aria-label="거래소 — 그 거래소 봉과 진입·청산"><span class="cap rkvl">거래소</span>' + vns.map(o => { const on = o.key === x.venue; return '<button class="chip' + (on ? ' on' : '') + '" data-a="frVenue" data-v="' + esc(o.key) + '" aria-pressed="' + on + '">' + esc(o.label) + ' <span class="mut num">' + num(o.n) + '건</span></button>'; }).join('') + '</div>' : '';
    if (!ch.ok && !marks.length) return '<div class="rkwhy cap" role="status">' + esc(ch.why || '그릴 진입·청산이 없어요') + '</div>';
    if (!ch.ok || !cs0.length) {
      const why = ch.why || '봉을 받지 못했어요';
      const pts = marks.filter(k => num(k.px) > 0);
      return vchips + '<div class="rkwhy cap" role="status" title="' + esc(arr(ch.tried).map(t9 => t9.label + ': ' + (t9.note || t9.why)).join('\n')) + '">실제 시세를 받지 못해 진입·청산 점만 보여 줘요 · ' + esc(why) + ' <button class="link" data-a="frChartRetry">다시 받기</button></div>'
        + (pts.length ? '<div class="cap num frpts">' + pts.slice(0, 12).map(k => kstHM(num(k.ts)) + ' ' + (k.kind === 'open' ? (k.side === 'LONG' ? '▲' : '▼') + ' 진입' : (k.approx ? '◌' : '○') + ' 청산') + ' ' + '<span class="num">' + px(num(k.px)) + '</span>').join(' · ') + '</div>' : '');
    }
    const src = ch.src || {}, w = x.window || {};
    const ivS = { '1m': 60, '5m': 300, '1h': 3600 }[src.iv] || 300;
    const Wd = Math.round(Math.max(300, Math.min(756, S.mobile ? (window.innerWidth || 390) - 34 : 756)));
    const PH = S.mobile ? 210 : 270, VH = S.mobile ? 40 : 52, GAP = 8, AX = 22, T = 30, Rp = 10;
    const H = T + PH + GAP + VH + AX;
    const t0 = num(w.from) || cs0[0][0], t1 = (num(w.to) || cs0[cs0.length - 1][0]) + ivS;
    const inView = cs0.filter(r => r[0] + ivS > t0 && r[0] < t1), cv0 = inView.length ? inView : cs0;
    const ys = [];
    cv0.forEach(r => ys.push(r[2], r[3]));
    marks.forEach(k => { if (num(k.px) > 0) ys.push(num(k.px)); });
    spans.forEach(s0 => ys.push(num(s0.entryPx), num(s0.exitPx)));
    let y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
    const pad = (y1 - y0) * 0.07 || y1 * 0.05 || 1; y0 = Math.max(0, y0 - pad); y1 += pad;
    const Y = p => T + (1 - (p - y0) / (y1 - y0)) * PH;
    const yt = rcTicks(y0, y1, S.mobile ? 3 : 4).filter(p => Y(p) > T + 8 && Y(p) < T + PH - 4);
    const gut = S.mobile && yt.length ? Math.ceil(Math.max.apply(null, yt.map(p => rkTw(px(p), 11.5)))) + 8 : 0, Lp = gut ? gut + 8 : 8;
    const bn = rcBin(cv0, Math.floor((Wd - Lp - Rp) / 2.5)), cs = bn.cs, bS = ivS * bn.k;
    const X = t => Lp + (Math.max(t0, Math.min(t1, t)) - t0) / (t1 - t0) * (Wd - Lp - Rp);
    const vmax = Math.max.apply(null, cs.map(r => num(r[5]))) || 1, VB = T + PH + GAP + VH;
    const bw = Math.max(1, Math.min(9, 0.68 * (Wd - Lp - Rp) * bS / (t1 - t0)));
    const grid = yt.map(p => '<line x1="' + Lp + '" x2="' + (Wd - Rp) + '" y1="' + Y(p).toFixed(1) + '" y2="' + Y(p).toFixed(1) + '" class="gl"/><text x="' + (gut ? gut - 4 : Lp + 4) + '" y="' + (gut ? Y(p) + 4 : Y(p) - 4).toFixed(1) + '"' + (gut ? ' text-anchor="end"' : '') + ' class="tk">' + esc(px(p)) + '</text>').join('');
    const stp = [5, 10, 15, 30, 60, 120, 180, 360, 720, 1440].find(s0 => (t1 - t0) / 60 / s0 <= (S.mobile ? 4 : 7)) || 1440;
    const xt = []; for (let t = Math.ceil((t0 + 32400) / (stp * 60)) * stp * 60 - 32400; t <= t1; t += stp * 60) xt.push(t);
    const xax = xt.map(t => '<text x="' + X(t).toFixed(1) + '" y="' + (H - 6) + '" text-anchor="' + (X(t) < 24 ? 'start' : X(t) > Wd - 24 ? 'end' : 'middle') + '" class="tk">' + (stp >= 1440 ? frMD(t).slice(0, 5) : kstHM(t)) + '</text>').join('');
    const cbx = [];
    const candles = cs.map(r => {
      const xm = X(r[0] + bS / 2), up = r[4] >= r[1], yo = Y(Math.max(r[1], r[4])), yc = Y(Math.min(r[1], r[4])), vh = num(r[5]) / vmax * VH;
      cbx.push([xm - Math.max(1, bw / 2), Y(r[2]), xm + Math.max(1, bw / 2), Y(r[3])]);
      return '<g class="' + (up ? 'cu' : 'cd') + '"><line x1="' + xm.toFixed(1) + '" x2="' + xm.toFixed(1) + '" y1="' + Y(r[2]).toFixed(1) + '" y2="' + Y(r[3]).toFixed(1) + '"/><rect x="' + (xm - bw / 2).toFixed(1) + '" y="' + yo.toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + Math.max(1, yc - yo).toFixed(1) + '"/>'
        + '<rect class="vb" x="' + (xm - bw / 2).toFixed(1) + '" y="' + (VB - vh).toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + Math.max(0.5, vh).toFixed(1) + '"/>'
        + '<title>' + esc(kstHM(r[0]) + (bn.k > 1 ? ' (' + bn.k + '봉 묶음)' : '') + ' · 시 ' + px(r[1]) + ' · 고 ' + px(r[2]) + ' · 저 ' + px(r[3]) + ' · 종 ' + px(r[4])) + '</title></g>';
    }).join('');
    const occ = [], early = [];
    const zones = spans.map(s0 => {
      const xa = s0.from ? X(num(s0.from)) : Lp, xb = X(num(s0.to)), ya = Y(num(s0.entryPx)), yb = Y(num(s0.exitPx));
      if (s0.from && num(s0.from) < t0) early.push(s0);
      return '<g class="fsp" data-fk="' + esc(s0.id) + '"><rect x="' + Math.min(xa, xb).toFixed(1) + '" y="' + Math.min(ya, yb).toFixed(1) + '" width="' + Math.max(1, Math.abs(xb - xa)).toFixed(1) + '" height="' + Math.max(1, Math.abs(yb - ya)).toFixed(1) + '" class="' + (num(s0.pnl) >= 0 ? 'fz' : 'fn') + '"/>'
        + '<line x1="' + xa.toFixed(1) + '" x2="' + xb.toFixed(1) + '" y1="' + ya.toFixed(1) + '" y2="' + ya.toFixed(1) + '" class="fe"/></g>';
    }).join('');
    const earlyLab = early.length ? (() => { const e0 = early.reduce((a, b) => (num(b.from) < num(a.from) ? b : a)); return '<text x="' + (Lp + 4) + '" y="' + (Y(num(e0.entryPx)) - 5).toFixed(1) + '" class="ucx">← 진입 ' + esc(frMD(num(e0.from))) + '</text>'; })() : '';
    const qmx = Math.max.apply(null, marks.map(k => num(k.q))) || 1;
    const tri = (k, xm, ym) => { const s0 = Math.max(8, Math.min(16, 8 + 8 * Math.sqrt(num(k.q) / qmx))), h0 = s0 * 0.9, up = k.side === 'LONG';
      const p = up ? [[xm, ym - h0 * 0.15], [xm - s0 / 2, ym + h0 * 0.85], [xm + s0 / 2, ym + h0 * 0.85]] : [[xm, ym + h0 * 0.15], [xm - s0 / 2, ym - h0 * 0.85], [xm + s0 / 2, ym - h0 * 0.85]];
      return '<path d="M' + p.map(z => z[0].toFixed(1) + ' ' + z[1].toFixed(1)).join('L') + 'Z" class="fo ' + (up ? 'fl' : 'fs') + '"><title>' + esc(kstHM(num(k.ts)) + ' ' + (up ? '롱' : '숏') + ' 진입 · ' + px(num(k.px)) + (num(k.fills) > 1 ? '(평균)' : '') + (k.q ? ' · ' + q(num(k.q)) + ' ' + c.coin : '') + (num(k.fills) > 1 ? ' · 한 주문 ' + num(k.fills) + '체결' : '') + ' · ' + (EX_NAMES[k.exKey] || k.exKey)) + '</title></path>'; };
    const opens = marks.filter(k => k.kind === 'open' && num(k.px) > 0 && num(k.ts) >= t0 && num(k.ts) <= t1).map(k => tri(k, X(num(k.ts)), Y(num(k.px)))).join('');
    const pills = [], trById = {};
    arr(c.trades).forEach(t9 => { if (t9 && t9.id) trById[t9.id] = t9; });
    const closes = marks.filter(k => k.kind === 'close' && num(k.px) > 0).map(k => {
      const tr0 = trById[k.id], xm = X(num(k.ts)), ym = Y(num(k.px)), pv = KV(num(k.pnl), tr0 ? tr0.pnlKrw : null);
      const full = kstHM(num(k.ts)) + ' ' + (k.side ? frSide(k.side) + ' 청산' : '청산(방향 없음)') + ' · ' + (k.approx ? '≈' : '') + px(num(k.px)) + (k.approx ? '(그 시각 봉 종가)' : '') + (k.q ? ' · ' + q(num(k.q)) + ' ' + c.coin : '') + ' · ' + m(pv, { sign: true }) + ' · ' + (EX_NAMES[k.exKey] || k.exKey);
      if (!k.approx) { const lab = m(pv, { sign: true, compact: true }), tw0 = rkTw(lab, 10.5) + 12;
        const cand = [{ x: xm + 7, y: ym - 9, w: tw0, h: 17 }, { x: xm - 7 - tw0, y: ym - 9, w: tw0, h: 17 }, { x: xm - tw0 / 2, y: ym + 9, w: tw0, h: 17 }, { x: xm - tw0 / 2, y: ym - 26, w: tw0, h: 17 }].filter(z => z.y >= 2 && z.y + 17 <= T + PH);
        const cc = rkFit(occ, cand, Lp + 2, Wd - Rp - 2, cbx) || rkFit(occ, cand, Lp + 2, Wd - Rp - 2, null);
        if (cc) pills.push('<g class="fpl ' + (num(k.pnl) >= 0 ? 'p' : 'n') + '" data-fk="' + esc(k.id) + '"><rect x="' + cc.x.toFixed(1) + '" y="' + cc.y.toFixed(1) + '" width="' + cc.w.toFixed(1) + '" height="17" rx="5"/><text x="' + (cc.x + 6).toFixed(1) + '" y="' + (cc.y + 12.5).toFixed(1) + '">' + esc(lab) + '</text></g>'); }
      return '<circle cx="' + xm.toFixed(1) + '" cy="' + ym.toFixed(1) + '" r="' + (k.approx ? 4.5 : 5.2) + '" class="fc ' + (k.approx || !k.side ? 'fx' : k.side === 'LONG' ? 'fl' : 'fs') + '" data-fk="' + esc(k.id) + '"><title>' + esc(full) + '</title></circle>';
    }).join('');
    const nAp = marks.filter(k => k.kind === 'close' && k.approx).length;
    const aria = (c.label || '') + ' ' + (src.label || '') + ' ' + (RC_IVK[src.iv] || '') + ' 위에 진입 ' + marks.filter(k => k.kind === 'open').length + '회 · 청산 ' + marks.filter(k => k.kind === 'close').length + '회';
    const svg = '<svg class="rsc rkg fut" width="' + Wd + '" height="' + H + '" viewBox="0 0 ' + Wd + ' ' + H + '" role="img" aria-label="' + esc(aria) + '">' + grid + '<line x1="' + Lp + '" x2="' + (Wd - Rp) + '" y1="' + VB + '" y2="' + VB + '" class="gl"/>'
      + zones + candles + earlyLab + opens + closes + pills.join('') + xax + '</svg>';
    const leg = '<div class="rkleg cap frleg"><span><i class="lg fl tri" aria-hidden="true">▲</i>롱 진입</span><span><i class="lg fs tri" aria-hidden="true">▼</i>숏 진입</span><span><i class="lg fcl" aria-hidden="true"></i>청산(테 색 = 방향)</span><span><i class="lg fe" aria-hidden="true"></i>평균 진입가</span><span><i class="lg fz" aria-hidden="true"></i>수익 구간</span><span><i class="lg fn" aria-hidden="true"></i>손실 구간</span>' + (nAp ? '<span><i class="lg fx" aria-hidden="true"></i>가격 없음(≈)</span>' : '') + '</div>';
    const tr = arr(ch.tried);
    let st = (src.fallback && tr.length ? tr[0].label + ' 봉 없음 → ' : '') + (src.label || '') + ' ' + (RC_IVK[src.iv] || src.iv || '');
    if (src.iv && src.iv !== x.iv) st += ' · ' + (src.iv === '1h' ? '창이 길어 1시간봉(저해상도)' : (RC_IVK[x.iv] || x.iv) + '이 없어 저해상도');
    if (x.srcNote) st += ' · ' + x.srcNote;
    if (x.capNote) st += ' · ' + x.capNote;
    st += ' · 가격축 USDT(선물 상세와 같은 규칙)';
    if (nAp) st += ' · 가격 없는 청산 ' + nAp + '건은 그 시각 봉 종가에 빈 점';
    if (bn.k > 1) st += ' · ' + bn.k + '봉씩 묶어 그림';
    const srcLine = '<div class="rksrc cap"><span title="' + esc(tr.length ? '시도: ' + tr.map(t9 => t9.label + ' — ' + (t9.note || t9.why)).join('\n') : '') + '">' + esc(st) + '</span></div>';
    return vchips + leg + '<div class="rscw rkw' + (loading ? ' rkld' : '') + '">' + (loading ? rkRe('새로 받는 중') : '') + svg + '</div>' + srcLine;
  }
  function frChipFix() {
    const row = $('#overlay .frc .frch'); if (!row || row.scrollWidth <= row.clientWidth + 1) { if (row) row.classList.remove('fl', 'fr'); return; }
    const R = S.frc, on = row.querySelector('.chip.on');
    if (R && on && R._chipAt !== R.coin) {
      R._chipAt = R.coin;
      if (on.offsetLeft < row.scrollLeft || on.offsetLeft + on.offsetWidth > row.scrollLeft + row.clientWidth) row.scrollLeft = Math.max(0, on.offsetLeft - 32);
    }
    dpFade(row);
  }
  document.addEventListener('scroll', ev => { const t = ev.target; if (t && t.classList && t.classList.contains('frch')) dpFade(t); }, true);
  const frHl = (id) => { const g = document.querySelector('#overlay .frc svg.rkg.fut'); if (!g) return;
    g.classList.toggle('hl', !!id); g.querySelectorAll('[data-fk]').forEach(n => n.classList.toggle('on', !!id && n.getAttribute('data-fk') === id)); };
  ['mouseover', 'focusin'].forEach(tp => document.addEventListener(tp, ev => { const r = ev.target && ev.target.closest ? ev.target.closest('#overlay .frc [data-frt]') : null; if (r) frHl(r.getAttribute('data-frt')); }));
  ['mouseout', 'focusout'].forEach(tp => document.addEventListener(tp, ev => { const r = ev.target && ev.target.closest ? ev.target.closest('#overlay .frc [data-frt]') : null; if (r && !(ev.relatedTarget && r.contains(ev.relatedTarget))) frHl(null); }));
  return {
    frChart, frChipFix, frExKey, frLoad, futRcptDrawer, openFutRcpt, openReceipt, postJ, rcbLoad, rcEvalPost, rcLoad, rcOn, rcptDrawer, rcSK, rcV,
    topRcptSym
  };
};
