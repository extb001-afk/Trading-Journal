(function () {
  'use strict';
  const K = window.TJWow && window.TJWow._kit; if (!K) return;
  const { X, st, A, VIEWS, paint, closeAndGo, num, arr, M, P, cls, ICO, chCol, KX, todayISO, KST, $, reduce, locSumH, taxYtd, slRate } = K;
  const esc = TJDOM.esc;
  const FL_DST = { 'now:coin_w': 'var(--k2)', 'now:coin_ex': 'var(--k5)', 'now:stable': 'var(--k1)', 'now:lp': 'var(--k4)',
    'now:cash': 'var(--k3)',
    'now:krw_out': 'var(--k6)', 'now:sent': 'var(--k6)', 'now:toex': 'var(--muted)', 'now:fee': 'var(--k6)', 'now:bridge': 'var(--k8)' };
  const FL_EST = { 'now:loss': 1, 'now:unexpl': 1 }, FL_RING = { 'now:fee': 1 };
  const FL_WHY = { krw: '은행 → 거래소 원화 입금', coin_in: '밖에서 받은 코인(전송·보상·에어드랍 · 받은 날 가격)', open: '수집 시작 때 있던 코인 · 거래소 대사 보정(그날 가격)',
    route: '거래소 출금 → 내 지갑 도착(출금 날 가격 · 오간 것 상계)', back: '내 지갑 → 거래소 입금(상계하고 남은 몫)', hold: '지금 보유(지금 시세)', cash: '거래소 원화 예수금(지금 환율)',
    krw_out: '거래소 → 은행 원화 출금', sent: '밖으로 보낸 돈(보낸 날 값 · 거래소 외부 출금 포함)', fee: '체인에 낸 가스',
    gain: '들어온 것보다 지금·나간 것이 많은 만큼(시세·매매 + 짝 못 찾은 기록 — 추정)', loss: '들어온 것보다 지금·나간 것이 적은 만큼(시세·매매 + 짝 못 찾은 기록 — 추정)',
    bridge_in: '다른 체인·내 지갑에서 브릿지로 옮겨 온 코인(출발과 짝지은 것 — 밖에서 받은 돈 아님 · 도착 날 가격)',
      bridge_out: '브릿지로 다른 체인에 옮긴 코인(도착과 짝지은 것 · 도착 쪽 금액 — 차이는 수수료)',
    unexpl: '브릿지·내 다른 지갑으로 보냈는데 도착을 못 찾은 것 — 손실이 아니라 아직 설명 안 된 이동(보낸 날 가격)' };
  const FL_PER = [['all', '전체'], ['year', '올해'], ['month', '이번 달']];
  const FL_SHORT_SRC = { 'in:krw': '원화', 'in:coin': '코인', 'in:open': '시작 보유', 'in:back': '되돌림', 'in:bridge': '옮겨 옴', 'in:gain': '늘어남' };
  const FL_SHORT = { Ethereum: '이더리움', Arbitrum: '아비트럼', Optimism: '옵티미즘', Polygon: '폴리곤', Avalanche: '아발란체', 'BNB Chain': 'BNB',
    'BNB Smart Chain': 'BNB',
    Hyperliquid: '하이퍼', HyperEVM: '하이퍼', Berachain: '베라', Unichain: '유니체인', Abstract: '앱스트랙', Scroll: '스크롤', Linea: '리니아', Solana: '솔라나',
      Mantle: '맨틀', Monad: '모나드', Sonic: '소닉', zkSync: 'zkSync', 'zkSync Era': 'zkSync', Blast: 'Blast', Kaia: '카이아' };
  const flSince = p => (p === 'year' ? todayISO().slice(0, 4) + '-01-01' : p === 'month' ? todayISO().slice(0, 8) + '01' : '');
  VIEWS.fl = {
    head: () => ({ k: '자금 흐름 지도 · ' + (st.fl.per === 'year' ? '올해' : st.fl.per === 'month' ? '이번 달' : '처음부터 지금까지'),
      t: '넣은 돈이 지금 어디에 얼마나 있나',
      act: '<span class="wseg" role="group" aria-label="기간">' + FL_PER.map(o => '<button type="button" class="'
        + (st.fl.per === o[0] ? 'on' : '') + '" aria-pressed="' + (st.fl.per === o[0]) + '" data-w="flPer" data-v="' + o[0] + '">' + o[1]
        + '</button>').join('') + '</span>' }),
    load: () => {
      const F = st.fl, per = F.per;
      if (F.cache[per] || F.busy === per) return;
      F.busy = per; F.err = '';
      const q = flSince(per);
      fetch('/api/wow/flows' + (q ? '?since=' + q : ''), { cache: 'no-store', credentials: 'same-origin' }).then(r => r.json()).then(j => {
        if (F.busy === per) F.busy = '';
        if (j && j.ok) F.cache[per] = j; else F.err = (j && j.error) || '만들지 못했어요';
        if (st.view === 'fl' && F.per === per) paint();
      }).catch(() => { if (F.busy === per) F.busy = ''; F.err = '불러오지 못했어요 — 잠시 뒤 다시'; if (st.view === 'fl') paint(); });
    },
    body: () => {
      const F = st.fl, d = F.cache[F.per];
      if (!d) return F.err ? '<div class="wempty">' + esc(F.err)
        + '</div>' : '<div class="wcard"><div class="wskel" style="height:440px;border-radius:14px"></div></div>';
      const t = d.totals || {};
      if (!arr(d.links).length) return '<div class="wempty">이 기간엔 그릴 흐름이 없어요 — 입출금·보유가 쌓이면 보여요</div>';
      const sc = (l, v, big) => '<div' + (big ? ' class="big"' : '') + '><span class="l">' + l + '</span><span class="v">' + M(v,
        { compact: true }) + '</span></div>';
      const tot = '<section class="wcard wfl-tot" aria-label="흐름 합계">' + sc('원화로 넣은 돈', t.in_krw) + sc('지금 있는 돈', t.now, 1)
        + sc('원화로 돌아온 돈', t.out_krw)
        + (num(t.in_coin) ? sc('코인으로 받은 몫', t.in_coin) : '') + (num(t.in_open) ? sc('시작 보유 · 대사 보정', t.in_open) : '')
        + (num(t.bridge) ? sc('체인끼리 옮김', t.bridge) : '') + (num(t.unexpl) ? sc('설명 안 됨', t.unexpl) : '') + '</section>';
      return tot + '<div class="wfl-wrap" id="wflWrap"><div class="wfl-cols" id="wflCols"></div>'
        + '<div id="wflMap" style="position:relative"></div></div>'
        + '<div class="wfl-sel" id="wflSel" aria-live="polite">' + flSelHTML() + '</div>'
        + '<details class="wnote wnd"><summary><span class="t">띠 굵기 = 금액 · 띠를 누르면 그 길의 전송 목록 · 늘어난·줄어든 몫은 추정(손익 아님)</span>'
        + '<span class="wndm">자세한 설명' + ICO.dn + '</span></summary>'
        + '<div class="wndb">띠 굵기 = 금액(그날 가격) · 띠를 누르면 그 길의 전송 목록 · 거래소 ↔ 지갑 = 출금과 도착을 짝지은 것(<span class="pvx">' + num(t.routes)
        + '건</span> · 내 거래소끼리 옮긴 <span class="pvx">' + num(t.internal) + '건</span>은 뺐어요) · 체인끼리 옮긴 것 = 브릿지 출발과 도착 짝(<span class="pvx">'
        + num(t.bridgeN) + '건</span> · 못 찾은 것 = 설명 안 됨) · 지금 있는 곳 = 지금 시세 · '
        + (t.pxDay != null ? '이동 금액 중 그날 가격 ' + P(num(t.pxDay) * 100, 0) + (num(t.pxDay) < 0.995 ? '(나머지는 그날 가격이 없어 지금 시세)' : '')
        + (num(t.pxNone) ? ' · 가격 없어 뺀 기록 <span class="pvx">' + num(t.pxNone) + '건</span>' : '') + ' · ' : '')
        + '<b>' + (F.per === 'all' ? '늘어난 몫' : '그 전부터 있던 돈 · 늘어난 몫') + '</b> / <b>줄어든 몫</b>(흐린 점선) = 들어온 것과 지금·나간 것의 차이 — '
        + '시세·매매 손익에 원장에서 짝을 못 찾은 이동·거래소 대사 보정이 섞인 추정이라 손익으로 읽지 마세요(손익은 매매일지·대시보드)</div></details>';
    },
    after: el => {
      const w = $('#wflWrap', el); if (!w) return;
      flDraw();
      w.addEventListener('mouseover',
        ev => { const b = ev.target.closest && ev.target.closest('.wfl-band'); if (b) flHi(+b.getAttribute('data-i'), false); });
      w.addEventListener('mouseleave', () => flHi(-1, false));
      w.addEventListener('keydown', ev => {
        const b = ev.target.closest && ev.target.closest('.wfl-band');
        if (b && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); flHi(+b.getAttribute('data-i'), true); }
      });
    }
  };
  let flRsz = 0;
  window.addEventListener('resize', () => { if (st.view !== 'fl') return; clearTimeout(flRsz); flRsz = setTimeout(flDraw, 120); });
  function flLayout(d, W, H, mob) {
    const nodes = arr(d.nodes).map(n => Object.assign({}, n, { inV: 0, outV: 0 })), byId = {};
    nodes.forEach(n => { byId[n.id] = n; });
    const links = arr(d.links).filter(l => byId[l.s] && byId[l.t] && num(l.usd) > 0).map((l, i) => Object.assign({ i }, l));
    links.forEach(l => { byId[l.s].outV += l.usd; byId[l.t].inV += l.usd; });
    nodes.forEach(n => { n.v = Math.max(n.inV, n.outV); });
    const cols = [[], [], [], []];
    nodes.forEach(n => cols[Math.max(0, Math.min(3, n.col))].push(n));
    cols.forEach(c => c.sort((a,
      b) => (a.kind === 'gain' || a.id === 'now:loss') - (b.kind === 'gain' || b.id === 'now:loss') || b.v - a.v));
    const pad = 14, maxN = Math.max(...cols.map(c => c.length)), avail = H - pad * Math.max(0, maxN - 1) - 20;
    const maxSum = Math.max(...cols.map(c => c.reduce((a, n) => a + n.v, 0))) || 1;
    let k = avail / maxSum;
    const sizeUp = () => {
      links.forEach(l => { l.h = Math.max(1, l.usd * k); });
      nodes.forEach(n => { let hi = 0,
        ho = 0; links.forEach(l => { if (l.t === n.id) hi += l.h; if (l.s === n.id) ho += l.h; }); n.h = Math.max(2, hi, ho); });
      return Math.max(...cols.map(c => c.reduce((a, n) => a + n.h, 0)));
    };
    for (let t = 0; t < 3; t++) { const top = sizeUp(); if (top <= avail + 0.5) break; k *= Math.max(0.2,
      (avail - (top - maxSum * k)) / (maxSum * k)); }
    const nw = W < 400 ? 8 : 12, f9 = W < 400 ? [0.3, 0.6] : [0.34, 0.67], colX = [0, (W - nw) * f9[0], (W - nw) * f9[1], W - nw];
    cols.forEach((c, ci) => { const tot = c.reduce((a, n) => a + n.h, 0) + pad * Math.max(0, c.length - 1); let y = Math.max(0,
      (H - tot) / 2); c.forEach(n => { n.x = colX[ci]; n.y = y; y += n.h + pad; n.oy = n.y; n.iy = n.y; }); });
    links.sort((a, b) => byId[a.t].y - byId[b.t].y);
    links.forEach(l => { const s = byId[l.s]; l.y0 = s.oy; s.oy += l.h; });
    links.slice().sort((a, b) => byId[a.s].y - byId[b.s].y).forEach(l => { const t = byId[l.t]; l.y1 = t.iy; t.iy += l.h; });
    const usedK = new Set();
    const chOf = n => { const c = chCol(n.label) || KX.find(k => !usedK.has(k)) || 'var(--k6)'; usedK.add(c); return c; };
    cols.forEach(c => c.forEach(n => {
      n.est = n.kind === 'gain' || !!FL_EST[n.id]; n.ring = !!FL_RING[n.id];
      n.color = n.est ? 'var(--muted)' : n.kind === 'src' ? (n.id === 'in:krw' ? 'var(--text)' : 'var(--muted)')
        : n.kind === 'ex' ? 'var(--text2)'
        : n.kind === 'ch' ? chOf(n) : n.kind === 'dst' ? (FL_DST[n.id] || 'var(--k6)') : 'var(--k6)';
    }));
    return { nodes, links, byId, nw, k, colX };
  }
  function flDraw() {
    const F = st.fl, d = F.cache[F.per], map = $('#wflMap'), colsEl = $('#wflCols'); if (!d || !map) return;
    const r = flMap(d, Math.max(300, map.clientWidth));
    map.style.height = r.H + 'px'; TJDOM.set(map, r.map);
    if (colsEl) TJDOM.set(colsEl, r.cols);
    flFit(map);
  }
  function flFit(map) {
    const F = st.fl, L = F.L, leg = []; if (!L) return;
    const last = {};
    Array.from(map.querySelectorAll('.wfl-lb')).map(e => ({ e, r: e.getBoundingClientRect(), c: e.getAttribute('data-c') })).sort((a,
      b) => a.c - b.c || a.r.top - b.r.top).forEach(x => {
      const b = x.e.querySelector('b'), over = b && (b.scrollWidth > b.clientWidth || b.scrollHeight > b.clientHeight + 1);
      if (over || (last[x.c] != null && x.r.top < last[x.c]
        + 2)) { const n = L.byId[x.e.getAttribute('data-id')]; if (n) leg.push(n); x.e.remove(); return; }
      last[x.c] = x.r.bottom;
    });
    let lg = map.parentNode && map.parentNode.querySelector('.wfl-legend');
    if (!lg && map.parentNode) { lg = document.createElement('div'); lg.className = 'wfl-legend'; map.parentNode.appendChild(lg); }
    if (!lg) return;
    const tot = F.tot || 1;
    TJDOM.set(lg, leg.length ? '<span class="k">작은 칸</span>' + leg.sort((a,
      b) => a.col - b.col || a.y - b.y).map(n => { const sh = n.v / tot * 100;
      return '<span data-n="' + esc(n.id) + '"><i' + (n.est ? ' class="es"' : n.ring ? ' class="rg" style="border-color:' + n.color
        + '"' : ' style="background:' + n.color + '"')
        + '></i>' + esc(n.label) + ' <span class="pvx">' + sh.toFixed(sh < 10 ? 1 : 0) + '%</span></span>'; }).join('') : '');
  }
  function flMap(d, cw) {
    const F = st.fl, mob = cw < 640, Rm = mob ? 78 : Math.min(230, Math.round(cw * 0.2)), H = mob ? 600 : 520;
    const L = flLayout(d, cw - Rm, H); F.L = L;
    const tot = L.nodes.filter(n => n.col === 0).reduce((a, n) => a + n.outV, 0) || 1;
    const bands = L.links.map(l => { const s = L.byId[l.s], t = L.byId[l.t], x0 = s.x + L.nw, x1 = t.x, xm = (x0 + x1) / 2,
      est = l.kind === 'gain' || l.kind === 'loss' || t.est;
      return '<path class="wfl-band' + (est ? ' est' : '') + (F.sel === l.i ? ' on' : '') + '" data-w="flSel" data-i="' + l.i
        + '" tabindex="0" role="button" aria-label="' + esc(s.label + ' → ' + t.label) + '" d="M' + x0.toFixed(1) + ' ' + l.y0.toFixed(1)
        + ' C' + xm.toFixed(1) + ' ' + l.y0.toFixed(1) + ' ' + xm.toFixed(1) + ' ' + l.y1.toFixed(1) + ' ' + x1.toFixed(1) + ' '
        + l.y1.toFixed(1)
        + ' L' + x1.toFixed(1) + ' ' + (l.y1 + l.h).toFixed(1) + ' C' + xm.toFixed(1) + ' ' + (l.y1 + l.h).toFixed(1) + ' ' + xm.toFixed(1)
        + ' ' + (l.y0 + l.h).toFixed(1) + ' ' + x0.toFixed(1) + ' ' + (l.y0 + l.h).toFixed(1)
        + 'Z" fill="' + (est ? 'var(--muted)' : s.color) + '"' + (est ? ' stroke="var(--muted)" stroke-dasharray="3 4"' : '')
        + '/>'; }).join('');
    const rects = L.nodes.map(n => '<rect x="' + n.x.toFixed(1) + '" y="' + n.y.toFixed(1) + '" width="' + L.nw + '" height="'
      + n.h.toFixed(1) + '" rx="4" fill="'
      + (n.est || n.ring ? 'var(--surface2)" stroke="' + n.color + '" stroke-width="1.5"'
      + (n.est ? ' stroke-dasharray="3 3"' : '') : n.color + '"') + '/>').join('');
    const labs = L.nodes.map(n => {
      const thin = n.h < (mob ? 13 : 11);
      const gx = mob ? 4 : 6, right = n.col === 3, maxW = right ? Rm - 8 : (L.colX[n.col + 1] - n.x - L.nw - gx - (mob ? 2 : 4)),
        sh = n.v / tot * 100;
      const two = !thin && n.h >= (right ? 30 : 34);
      return '<div class="wfl-lb' + (right ? ' r' : '') + (thin ? ' thin' : '') + '" data-c="' + n.col + '" data-id="' + esc(n.id)
        + '" style="left:' + (n.x + L.nw + gx).toFixed(1) + 'px;top:' + (n.y + n.h / 2).toFixed(1) + 'px;max-width:' + Math.max(40,
        maxW).toFixed(0) + 'px">'
        + '<b>' + esc(mob && n.kind === 'ch' ? n.label.replace(/ 지갑$/, '') : n.label) + '</b>' + (two ? '<span>'
        + ((right || n.col === 0) && !mob ? M(n.v, { compact: true }) + ' · ' : '') + '<span class="pvx">' + sh.toFixed(sh < 10 ? 1 : 0)
        + '%</span></span>' : '') + '</div>';
    }).join('');
    F.tot = tot;
    return { H, map: '<svg width="' + cw + '" height="' + H + '" viewBox="0 0 ' + cw + ' ' + H
      + '" role="img" aria-label="자금 흐름 지도"><g id="wflBands"' + (F.sel >= 0 ? ' class="wfl-dim"' : '') + '>' + bands + '</g>' + rects
      + '</svg>' + labs,
      cols: [['넣은 돈', 0], ['거래소', 1], ['체인 · 지갑', 2], ['지금 있는 곳', 3]].map(c => '<span style="left:' + (L.colX[c[1]]).toFixed(1) + 'px">'
        + c[0] + '</span>').join('') };
  }
  const fdate = ts => { if (!ts) return ''; const d = new Date(num(ts) * 1000 + KST); return String(d.getUTCFullYear()).slice(2) + '.'
    + (d.getUTCMonth() + 1) + '.' + d.getUTCDate(); };
  function flSelHTML() {
    const L = st.fl.L, i = st.fl.sel;
    if (!L || i < 0) return '<div class="wfl-hint">띠를 누르면 그 길로 간 돈과 전송 목록을 보여 줘요</div>';
    const l = L.links.find(z => z.i === i); if (!l) return '';
    const s = L.byId[l.s], t = L.byId[l.t], rows = arr(l.rows), n = num(l.n) || rows.length;
    const x9 = X(), Q = v => (x9 && typeof x9.q === 'function' ? x9.q(v) : '');
    const rowOf = r => (Array.isArray(r) ? { t: r[0], sym: r[1], usd: null, qty: null, note: '' } : r || {});
    const sentNameH = v => {
      const a0 = window.__tjSearchApi, s0 = String(v || '').trim(), D9 = a0 && a0.S && a0.S.D;
      const named = !!D9 && arr(D9.of).some(o => o && String(o.alias || o.label || '').trim().slice(0, 40) === s0);
      const pk = named || /^(?:0x[0-9a-fA-F]{6,64}|[A-Za-z0-9]{3,12}…[A-Za-z0-9]{3,10}|[1-9A-HJ-NP-Za-km-z]{32,44})$/.test(s0) ? 'w' : 'm';
      return '<span class="pvl" data-pk="' + pk + '">' + esc(a0 && typeof a0.ownNm === 'function' ? a0.ownNm(s0, pk) : s0) + '</span>';
    };
    const sentCh = l.kind === 'sent' && s && s.kind === 'ch';
    const list = rows.length ? '<div class="wfl-rows">' + rows.map(rowOf).map(r => '<div class="wfl-r"><span class="d pvx">'
      + esc(fdate(r.t)) + '</span><span class="n' + (l.kind === 'sent' && !sentCh ? ' pvl' : '') + '">'
      + (sentCh ? sentNameH(r.sym) : esc(r.sym || ''))
        + (r.qty != null && num(r.qty) ? ' <small class="num">' + Q(num(r.qty)) + '</small>' : '') + (r.note ? ' <small>' + esc(r.note)
        + '</small>' : '') + '</span><span class="v">' + (r.usd != null ? M(num(r.usd), { compact: true }) : '—')
        + '</span></div>').join('')
      + (n > rows.length ? '<div class="wnote">최근·큰 순 <span class="pvx">' + rows.length + '건</span>만 · 전체 <span class="pvx">' + n
      + '건</span></div>' : '') + '</div>' : '';
    return '<div class="wfl-sh"><span class="sw" style="background:' + s.color + '"></span><b>' + esc(s.label) + ' → ' + esc(t.label)
      + '</b><span class="amt">'
      + M(l.usd, { compact: true }) + '</span><span class="sp"></span>'
      + (l.kind === 'sent' ? '<button type="button" class="wbtn" data-w="flGo" data-v="outflows">보낸 내역</button>' : '')
      + '<button type="button" class="wbtn" data-w="flSel" data-i="-1">전체 보기</button></div>'
      + '<div class="wnote">' + esc(FL_WHY[l.kind] || '') + (n ? ' · <span class="pvx">' + n + '건</span>' : '') + '</div>' + list;
  }
  function flHi(i, sticky) {
    if (sticky) st.fl.sel = i;
    const g = $('#wflBands'); if (!g) return;
    const on = i >= 0 ? i : st.fl.sel;
    g.classList.toggle('wfl-dim', on >= 0);
    g.querySelectorAll('.wfl-band').forEach(b => b.classList.toggle('on', +b.getAttribute('data-i') === on));
    if (sticky) { const s = $('#wflSel'); if (s) { TJDOM.set(s,
      flSelHTML()); if (i >= 0 && X() && X().S.mobile) { try { s.scrollIntoView({ block: 'nearest',
      behavior: reduce() ? 'auto' : 'smooth' }); } catch (e) {  } } } }
  }
  Object.assign(A, {
    flSel: el => flHi(+el.getAttribute('data-i'), true),
    flPer: el => { st.fl.per = el.getAttribute('data-v') || 'all'; st.fl.sel = -1; paint(); VIEWS.fl.load(); },
    flGo: el => { const v = el.getAttribute('data-v'); closeAndGo(() => { location.hash = '#' + v; }); }
  });

  function feeRate(sym) {
    const x = X(), D = x && x.S.D; if (!D) return { r: 0.001, src: 'def' };
    const spot = r => !r.fut && !r.futFee && !/ 무기한$/.test(String(r.sym || '')) && !/^(기타 비용|스테이킹 보상|유동성)/.test(String(r.ex || ''));
    const rows = arr(D.taxSum).filter(spot), sy = String(sym || '').toUpperCase();
    const agg = rs => rs.reduce((a, r) => [a[0] + num(r.fee), a[1] + num(r.disp)], [0, 0]);
    const mine = agg(rows.filter(r => String(r.sym || '').toUpperCase() === sy)), all = agg(rows);
    if (mine[1] > 0 && mine[0] >= 0) return { r: mine[0] / mine[1], src: 'sym' };
    if (all[1] > 0 && all[0] >= 0) return { r: all[0] / all[1], src: 'all' };
    return { r: 0.001, src: 'def' };
  }
  function sellCalc() {
    const x = X(), D = x && x.S.D; if (!D) return null;
    const g = arr(D.groups).find(z => z.key === st.sell.key); if (!g || num(g.qty) <= 0 || num(g.value) <= 0) return null;
    const f = st.sell.f, price = g.value / g.qty, unk = Math.min(num(g.unkQty), g.qty), kq = Math.max(0, g.qty - unk), sq = f * g.qty;
    const useK = Math.min(sq, kq), unkSell = Math.max(0, sq - useK), uc = kq > 0 ? num(g.cost) / kq : 0;
    const fr = feeRate(g.sym), sell = f * g.value, fee = sell * fr.r, costPart = useK * uc;
    const est = useK * (price - uc) - fee;
    const ytd = taxYtd(todayISO().slice(0, 4));
    const pog = x.planOfGroup(g), cyc = arr(D.merged).find(p => num(p.held) > 0 && x.gMatch(g, p.sym, p.key));
    const pkey = pog ? pog.key : cyc ? cyc.key : '';
    return { g, f, price, est, pct: costPart > 0 ? est / costPart * 100 : null, unkSell, ytd, pkey,
      plan: pog ? pog.plan : (pkey && D.plans[pkey]) || null, sell, fee, fr, uc };
  }
  VIEWS.sell = {
    head: () => { const c = sellCalc(); return { k: '팔기 전 미리보기', t: c ? esc(c.g.sym) + ' 지금 팔면' : '지금 팔면' }; },
    body: () => {
      const c = sellCalc(), x = X();
      if (!c) return '<div class="wempty wemp"><span class="eic">' + ICO.sell
        + '</span><b>이 코인의 보유·시세를 찾지 못했어요</b><span>다음 수집 뒤 보유 코인에서 다시 열어 주세요</span>'
        + '<button type="button" class="wbtn" data-w="close">닫기</button></div>';
      const g = c.g, pcv = Math.round(c.f * 100), plan = c.plan;
      const tgt = plan && num(plan.target) > 0 ? plan.target : null, stp = plan && num(plan.stop) > 0 ? plan.stop : null, pv = x.pvOn();
      const sn = slSnap(x, tgt, stp), live = sn.live, cu = sn.cu, rt = sn.rt, inV = (d,
        o) => (d != null ? String(d) : o == null ? '' : cu === 'USD' ? String(o) : slIn(num(o), cu, rt));
      const vT = pv ? '' : inV(st.sell.dT, sn.oT), vS = pv ? '' : inV(st.sell.dS, sn.oS), uL = cu === 'KRW' ? '원화' : 'USD';
      const lg9 = x.S.D && x.S.D.symLogo && x.S.D.symLogo[g.sym];
      const av = typeof x.icon === 'function' ? x.icon(g.sym, 'sm', lg9 ? { ck: lg9.ck, ca: lg9.ca } : {}) : '<span class="av n">'
        + esc(String(g.sym).slice(0, 1)) + '</span>';
      return '<div class="wsl-h">' + av + '<span class="t">보유 ' + x.q(num(g.qty)) + ' ' + esc(g.sym) + ' · ' + M(num(g.value),
        { compact: true }) + ' · ' + locSumH(g)
          + ' · <span class="pvx">원가 확인 ' + Math.round((1 - Math.min(1, num(g.unkPct))) * 100) + '%</span></span></div>'
        + '<div class="wsl-kv wsl-amt"><span>팔 양</span><span><b class="pvx" id="wslPct">' + pcv + '%</b> <span class="mut" id="wslQty">= '
        + x.q(c.f * num(g.qty)) + ' ' + esc(g.sym) + '</span></span></div>'
        + '<div class="wsl-tr" id="wslTr" tabindex="0" role="slider" aria-label="팔 양" aria-valuemin="1" aria-valuemax="100" aria-valuenow="'
        + pcv + '" aria-valuetext="' + pcv + '%"><span class="tk"></span><span class="fi" style="width:' + pcv
        + '%"></span><span class="th" style="left:' + pcv + '%"></span></div>'
        + '<div class="wseg wsl-q" role="group" aria-label="빠른 선택">' + [[0.25, '25%'], [0.5, '50%'], [1,
        '전부']].map(o => '<button type="button" class="' + (Math.abs(c.f - o[0]) < 0.001 ? 'on' : '') + '" aria-pressed="'
        + (Math.abs(c.f - o[0]) < 0.001) + '" data-w="slQ" data-v="' + o[0] + '">' + o[1] + '</button>').join('') + '</div>'
        + '<div class="wsl-res"><span class="wcap">예상 실현손익</span><span class="big ' + cls(c.est) + '" id="wslBig">' + M(c.est, { sign: true,
        compact: true }) + '</span>'
        + '<span class="full ' + cls(c.est) + '" id="wslFull">' + M(c.est, { sign: true }) + '</span><div class="wnote" id="wslSub">'
        + sellSub(c) + '</div>'
        + '<div class="wsl-hr"></div><div class="wsl-kv"><span>올해 누적 양도차익(명세 기준)</span><span id="wslYtd">' + sellYtd(c) + '</span></div>'
        + (num(g.unkQty) > 0 ? '<div class="wsl-kv"><span>원가 모르는 수량</span><span id="wslUnk">' + x.q(c.unkSell) + ' ' + esc(g.sym)
          + ' 포함</span></div>'
          + '<div class="wnote" title="장부처럼 원가 아는 수량부터 판다고 계산했어요 — 원가 모르는 몫(아는 몫을 다 판 뒤)은 손익 0 · '
          + '미매칭에서 원가를 정하면 더 정확해져요">원가 아는 수량부터 판다고 계산 · 모르는 몫은 손익 0</div>' : '') + '</div>'
        + (c.pkey ? '<div class="wsl-plh"><span>목표가 · 손절선</span><span class="wseg" role="group" aria-label="입력 통화">' + [['KRW', '₩ 원화'],
        ['USD', '$ 달러']].map(o => '<button type="button" class="' + (cu === o[0] ? 'on' : '') + '" aria-pressed="' + (cu === o[0])
        + '" data-w="slCur" data-v="' + o[0] + '"' + (o[0] === 'KRW' && !live ? ' disabled title="지금 환율을 아직 못 받았어요"' : '') + '>' + o[1]
        + '</button>').join('') + '</span></div>'
          + (live ? '' : '<div class="wnote">지금 환율을 아직 못 받아 원화 입력은 잠시 막아 뒀어요 — 달러로 넣어 주세요</div>')
          + '<div class="wsl-pl"><label><span class="wcap">목표가 (' + uL + ')</span><span class="wsl-fld"><span class="u">'
          + (cu === 'KRW' ? '₩' : '$') + '</span><input inputmode="decimal" id="wslT" data-pv value="' + esc(vT) + '" placeholder="'
          + (pv ? '숨김 중' : esc(slIn(c.price * 1.25, cu, rt))) + '" autocomplete="off"' + (pv ? ' disabled' : '')
          + '></span><span class="wsl-eq" id="wslTq">' + (pv ? '' : esc(slEq(vT, cu, rt))) + '</span></label>'
          + '<label><span class="wcap">손절선 (' + uL + ' · 선택)</span><span class="wsl-fld"><span class="u">' + (cu === 'KRW' ? '₩' : '$')
          + '</span><input inputmode="decimal" id="wslS" data-pv value="' + esc(vS) + '" placeholder="'
          + (pv ? '숨김 중' : esc(slIn(c.price * 0.9, cu, rt))) + '" autocomplete="off"' + (pv ? ' disabled' : '')
          + '></span><span class="wsl-eq" id="wslSq">' + (pv ? '' : esc(slEq(vS, cu, rt))) + '</span></label></div>'
          + (cu === 'KRW' && !pv ? '<div class="wnote">원화로 넣으면 지금 환율(₩' + (typeof x.nf === 'function' ? x.nf('ko-KR', 0,
          0).format(rt) : Math.round(rt)) + '/$)로 달러로 바꿔 저장해요 — 감시·알림은 달러 시세 기준</div>' : '')
          + '<div class="wsl-act"><button type="button" class="wbtn" style="flex:1" data-w="close">닫기</button>'
          + '<button type="button" class="wbtn pri" style="flex:1.4" data-w="slSave"' + (pv ? ' disabled title="숨김 중엔 저장할 수 없어요"' : '')
          + '>목표가로 저장</button></div>'
          : '<div class="wsl-act"><button type="button" class="wbtn" style="flex:1" data-w="close">닫기</button></div>')
        + (st.sell.saveMsg ? '<div class="wsl-msg"><span class="wdot ' + (/^저장했어요/.test(st.sell.saveMsg) ? 'ok' : 'e') + '"></span>'
        + esc(st.sell.saveMsg) + '</div>' : '')
        + '<div class="wnote wsl-ft">이 봇은 주문을 넣지 않아요 · 계산만 해요</div>';
    },
    after: el => {
      [['#wslT', 'dT'], ['#wslS', 'dS']].forEach(([id9, k9]) => { const i9 = $(id9,
        el); if (i9 && !i9.disabled) i9.addEventListener('input', () => { st.sell[k9] = i9.value;
        const q9 = $(id9 + 'q', el), sn9 = st.sell.snap; if (q9 && sn9) q9.textContent = slEq(i9.value, sn9.cu, sn9.rt); }); });
      const tr = $('#wslTr', el); if (!tr) return;
      let drag = false;
      const pick = ev => { const r = tr.getBoundingClientRect(); return Math.max(0.01, Math.min(1, (ev.clientX - r.left) / r.width)); };
      const live = f => { const pc = Math.round(f * 100); const fi = $('.fi', tr), th = $('.th', tr); if (fi) fi.style.width = pc
        + '%'; if (th) th.style.left = pc + '%';
        st.sell.f = Math.round(f * 100) / 100; const c = sellCalc(); if (!c) return; const x = X();
        const set = (id, h) => { const e = $(id); if (e) TJDOM.set(e, h); };
        set('#wslPct', pc + '%'); set('#wslBig', M(c.est, { sign: true, compact: true })); set('#wslFull', M(c.est,
          { sign: true })); set('#wslSub', sellSub(c)); set('#wslYtd', sellYtd(c));
        if (x) { set('#wslUnk', x.q(c.unkSell) + ' ' + esc(c.g.sym) + ' 포함'); set('#wslQty', '= ' + x.q(c.f * num(c.g.qty)) + ' '
          + esc(c.g.sym)); }
        const b = $('#wslBig'), b2 = $('#wslFull'); if (b) b.className = 'big ' + cls(c.est); if (b2) b2.className = 'full '
          + cls(c.est); tr.setAttribute('aria-valuenow', String(pc)); tr.setAttribute('aria-valuetext', pc + '%'); };
      tr.addEventListener('pointerdown',
        ev => { drag = true; try { tr.setPointerCapture(ev.pointerId); } catch (e) {  } live(pick(ev)); });
      tr.addEventListener('pointermove', ev => { if (drag) live(pick(ev)); });
      const refocus = () => { const t = $('#wslTr'); if (t) t.focus({ preventScroll: true }); };
      tr.addEventListener('pointerup', ev => {
        if (!drag) return; drag = false; st.sell.f = Math.round(pick(ev) * 100) / 100; paint(); refocus();
      });
      tr.addEventListener('keydown', ev => {
        if (ev.key !== 'ArrowLeft' && ev.key !== 'ArrowRight') return;
        ev.preventDefault();
        st.sell.f = Math.max(0.01, Math.min(1, Math.round((st.sell.f + (ev.key === 'ArrowRight' ? 0.05 : -0.05)) * 100) / 100));
        paint(); refocus();
      });
    }
  };
  const sellSub = c => (num(c.uc) > 0 ? '평균 매수 ' + M(c.uc, { compact: true }) + ' → 지금 ' + M(c.price, { compact: true }) + ' · ' : '')
    + (c.pct != null ? '평균 매수가 대비 <span class="num ' + cls(c.pct) + '">' + P(c.pct, 1, true) + '</span> · ' : '') + '받을 돈 ' + M(c.sell,
    { compact: true })
    + ' · 수수료 ≈ ' + M(num(c.fee), { compact: true }) + ' ('
    + (c.fr && c.fr.src === 'sym' ? '이 코인 지난 매도 평균 ' : c.fr && c.fr.src === 'all' ? '지난 매도 평균 ' : '기본 ')
    + P(num(c.fr && c.fr.r) * 100, 2) + ')';
  const sellYtd = c => '<span class="num ' + cls(c.ytd) + '">' + M(c.ytd, { compact: true, sign: true }) + '</span>'
    + ICO.to.replace('aria-hidden="true"', 'role="img" aria-label="에서"')
    + '<b class="num ' + cls(c.ytd + c.est) + '">' + M(c.ytd + c.est, { compact: true, sign: true }) + '</b>';
  const sigf = v => { if (!(v > 0)) return ''; const d = v >= 100 ? 2 : v >= 1 ? 4 : 8; return String(+v.toFixed(d)); };
  const slLive = x => !(x && typeof x.rateLive === 'function') || !!x.rateLive();
  function slSnap(x, tgt, stp) {
    if (st.sell.snap) return st.sell.snap;
    const rt = slRate(x), live = slLive(x);
    return (st.sell.snap = { rt, live, cu: live && !(x && x.S.cur === 'USD') ? 'KRW' : 'USD', oT: tgt, oS: stp,
      pT: tgt != null ? slIn(num(tgt), 'KRW', rt) : null, pS: stp != null ? slIn(num(stp), 'KRW', rt) : null });
  }
  const sigK = v => {
    if (!(v > 0)) return '';
    return v >= 1000 ? String(Math.round(v)) : v >= 1 ? String(+v.toFixed(2)) : String(+v.toPrecision(4));
  };
  const slIn = (usd, cu, rt) => (cu === 'KRW' ? sigK(usd * rt) : sigf(usd));
  const slNum = t => { const v = String(t == null ? '' : t).replace(/[,\s$₩]/g, ''); return v === '' ? null : parseFloat(v); };
  const slEq = (t, cu, rt) => { const v = slNum(t); if (!(v != null && isFinite(v) && v > 0)) return ''; return cu === 'KRW' ? '≈ $'
    + (v / rt >= 1000 ? (v / rt).toLocaleString('en-US', { maximumFractionDigits: 2 }) : sigf(v / rt)) : '≈ ₩'
    + (v * rt >= 1000 ? Math.round(v * rt).toLocaleString('ko-KR') : sigK(v * rt)); };
  Object.assign(A, {
    slQ: el => { st.sell.f = num(el.getAttribute('data-v')) || 0.5; paint(); },
    slCur: el => {
      const sn = st.sell.snap, to = el.getAttribute('data-v') === 'USD' ? 'USD' : 'KRW'; if (!sn || to === sn.cu) return;
      if (!(sn.live && sn.rt > 0)) return;
      ['dT', 'dS'].forEach(k9 => {
        const v = slNum(st.sell[k9]);
        if (st.sell[k9] != null && v != null && isFinite(v) && v > 0) st.sell[k9] = slIn(sn.cu === 'KRW' ? v / sn.rt : v, to, sn.rt);
      });
      sn.cu = to; st.sell.saveMsg = ''; paint();
    },
    slSave: () => {
      const c = sellCalc(), x = X(); if (!c || !c.pkey || !x || x.pvOn()) return;
      const sn = st.sell.snap; if (!sn) return;
      const cu = sn.cu, rt = sn.rt;
      if (cu === 'KRW' && !(sn.live && rt > 0)) { st.sell.saveMsg = '지금 환율을 받지 못해 원화로는 저장할 수 없어요 — 달러로 넣어 주세요'; paint(); return; }
      const rd = (id, o, pf) => { const raw = String(($(id) || {}).value || '').trim(),
        v = slNum(raw); if (v == null || cu === 'USD') return v;
        if (num(o) > 0 && pf != null && raw === pf) return num(o);
        return isFinite(v) && v > 0 ? +(v / rt).toPrecision(8) : v; };
      const t = rd('#wslT', sn.oT, sn.pT), s = rd('#wslS', sn.oS, sn.pS);
      if (!(t != null && isFinite(t) && t > 0)) { st.sell.saveMsg = '목표가를 숫자로 넣어 주세요'; paint(); return; }
      if (s != null && !(isFinite(s) && s > 0 && s < t)) { st.sell.saveMsg = '손절선은 0보다 크고 목표가보다 낮아야 해요'; paint(); return; }
      const body = { key: c.pkey, target: t }; if (s != null) body.stop = s;
      const cur = (x.S.D.plans || {})[c.pkey] || {}, both = s != null || num(cur.stop) > 0;
      x.post('/api/plan', body, both ? '목표가·손절선을 저장했어요 — 닿으면 알려 드려요' : '목표가를 저장했어요 · 손절선까지 채우면 감시해요')
        .then(d => { st.sell.saveMsg = d ? '저장했어요' : ''; if (st.view === 'sell') paint(); });
    }
  });
  Object.assign(window.TJWow, { ccy: { inp: slIn, num: slNum, eq: slEq }, _sellCalc: sellCalc,
    _flLayout: flLayout, _flMap: flMap, _flSelHTML: flSelHTML });
})();
