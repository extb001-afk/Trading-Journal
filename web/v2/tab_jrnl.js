'use strict';
(window.__tjTabs = window.__tjTabs || {}).jrnl = function (X) {
  const {
    ageTxt, arr, attOf, AUSD, cardReal, cardRealV, chainBadge, clps, cls, clsP, clsV, DOWS, eok, esc, evA, evDH, evDT, evNm, evQ, evSkel, EX_NAMES,
    EX_ORDER, exLogo, feedFull, feedMoreLoad, fsKchip, gBounds, gMatch, gPass, gRange, habitsHTML, IC, icon, impChip, isAirQ, isISO, isoDay, isZ,
    J_SORTS, jo, krw, KRW_BASIS, KS, KV, lpDetail, lpIcon, lpNm, lpNmHTML, lpStatePill, m, mCell, mCellF, mdOf, mN, mvDest, N, nf, num,
    onUnauthorized, pad2, pAgg, parseMoney, pctS, periodName, PERIODS, perMonthAligned, plCur, plCY, plPx, plQ, plSnap, prTxt, PVM, pvOn, pvW, px,
    pxC, pxr, q, rate, renderView, rfrTag, rollMinISO, rw, S, short, srcAgg, srcPass, sum, taxNmHTML, term, todayISO, UI_CHEV, UI_SHEETS, uiCell,
    uiFold, uiHidChip, uiOpen, uiPaged, uiPgBar, uiPgReset, uiPgSlice, venueLogo, wowSlot, ymOf, ymPass
  } = X;
  let gasRuleTxt, locH, ownH, ownNm, payChip, saleBox, xferBox;
  const __late = L => {
    if ('gasRuleTxt' in L) gasRuleTxt = L.gasRuleTxt;
    if ('locH' in L) locH = L.locH;
    if ('ownH' in L) ownH = L.ownH;
    if ('ownNm' in L) ownNm = L.ownNm;
    if ('payChip' in L) payChip = L.payChip;
    if ('saleBox' in L) saleBox = L.saleBox;
    if ('xferBox' in L) xferBox = L.xferBox;
  };
  function evPill(k) {
    const c = /매도/.test(k) ? 'up' : /매수/.test(k) ? 'a' : k === '입금 확인' || k === '수수료 청구' || k === '스테이킹 보상' ? 'ok' : /유동성|범위|리워드/.test(k) ? 'w' : 'g';
    return '<span class="pill ' + c + ' sm">' + esc(term(k)) + '</span>';
  }
  const sigDig = t => { const d = String(t == null ? '' : t).replace(/[^0-9.]/g, '').replace('.', '').replace(/^0+/, ''); return d.length; };
  function unitRaw(e) {
    if (e.un != null && isFinite(+e.un) && +e.un > 0) return { v: +e.un, krw: false };
    const a = parseMoney(e.a), qn = parseMoney(e.q);
    if (!a || !qn || sigDig(e.q) < 3 || sigDig(e.a) < 3) return null;
    return { v: Math.abs(a / qn), krw: String(e.a || '').indexOf('₩') >= 0 };
  }
  function unitPx(e) {
    const u = unitRaw(e);
    if (!u) return '—';
    if (u.krw) return S.hide ? krw(u.v) : '₩' + rw(nf('ko-KR', null, u.v >= 100 ? 0 : 2).format(u.v));
    return '@' + px4(u.v);
  }
  function px4(n) {
    if (S.hide || !(n > 0) || !isFinite(n) || n < 1) return px(n);
    const d = n >= 1000 ? 0 : n >= 100 ? 1 : n >= 10 ? 2 : 3;
    return '$' + rw(nf('en-US', d, d).format(n));
  }
  function unitKrw(e) {
    const u = unitRaw(e);
    if (S.cur !== 'KRW' || !u || u.krw) return '';
    const ua = AUSD.test(String(e.a || '').trim()) ? parseMoney(e.a) : 0;
    const w = u.v * (e.aK != null && isFinite(e.aK) && ua > 0 ? num(e.aK) / ua : rate());
    return w >= 1 ? '<span class="sub2">' + (S.hide ? krw(w) : '₩' + rw(nf('ko-KR', null, w >= 100 ? 0 : 2).format(w))) + '</span>' : '';
  }
  function jBase() {
    const D = S.D;
    const touched = p => (S.src.mode === 'all' && S.g.period === 'all') || (p.srcAct ? srcAgg(p).any : arr(p.events).some(e => srcPass(e) && gPass(e.t))) || (S.src.mode === 'all' && pAgg(p).any);
    const realIn = p => cardReal(p) !== 0 || (S.g.period === 'all' ? pAgg(p).allU : pAgg(p).inU) > 0;
    const ql = S.j.q.trim().toUpperCase();
    return D.merged.concat(D.lpCycles).filter(p => (Math.max(num(p.cost), p._heldVal) >= S.dust || S.dust <= 0 || realIn(p)) && touched(p) && (!ql || String(p.sym).toUpperCase().indexOf(ql) >= 0));
  }
  function jList() {
    const base = jBase();
    const st = S.j.status;
    const list = base.filter(p => st === 'all' || (st === 'open' && p._st !== '종료') || (st === 'held' && p._st === '보유') || (st === 'partial' && p._st === '부분 매도') || (st === 'closed' && p._st === '종료' && !p._mv) || (st === 'moved' && !!p._mv));
    const k = S.j.sort;
    const val = p => k === 'cost' ? num(p.cost) : k === 'realized' ? cardRealV(p) : k === 'unreal' ? (p.held > 0 ? num(p.unreal) : -Infinity) : 0;
    const rec = (a, b) => (a._last < b._last ? 1 : a._last > b._last ? -1 : 0);
    const nv = p => (p._now ? p._now.v : -1);
    list.sort((a, b) => k === 'recent' ? rec(a, b) : k === 'value' ? (nv(b) - nv(a) || rec(a, b)) : k === 'sym' ? String(a.sym).localeCompare(String(b.sym)) : val(b) - val(a));
    return { base, list };
  }
  function gasList() {
    const D = S.D, byM = D.gasByMonth;
    if (!byM || !Object.keys(byM).length) return D.gasByChain.map(g => ({ chain: g.chain, spot: num(g.spot), lp: num(g.lp), tx: num(g.tx), kind: g.kind || '', ex: g.ex || '' }));
    const acc = {};
    Object.keys(byM).forEach(ym => {
      if (!ymPass(ym)) return;
      arr(byM[ym]).forEach(g => { const e = acc[g.chain] || (acc[g.chain] = { chain: g.chain, spot: 0, lp: 0, tx: 0, kind: g.kind || '', ex: g.ex || '' }); e.spot += num(g.spot); e.lp += num(g.lp); e.tx += num(g.tx); });
    });
    return Object.keys(acc).map(k => acc[k]).sort((a, b) => (b.spot + b.lp) - (a.spot + a.lp));
  }
  const gasCnt = gas => { const nc = gas.filter(g => g.kind !== 'exfee').length, ne = new Set(gas.filter(g => g.kind === 'exfee').map(g => g.ex || String(g.chain || '').replace(/ (체결|출금) 수수료$/, ''))).size; return nc + '개 체인' + (ne ? ' · 거래소 ' + ne + '곳' : ''); };
  const gasScope = () => (S.D.gasByMonth && Object.keys(S.D.gasByMonth).length) ? ((S.g.period === 'custom' ? '≈ ' : '') + periodName()) : '전체 누적';
  const popBox = (title, inner, extra) => (S.mobile ? '<div class="sheet-bg" data-a="popClose"></div>' : '') + '<div class="pop' + (extra ? ' ' + extra : '') + '" role="dialog" aria-label="' + esc(title) + '"><div class="ptl">' + esc(title) + '</div>' + inner + '</div>';
  const optCk = '<svg class="ck" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5 9-10"/></svg>';
  function searchBox(key, ph, val) {
    return '<label class="search">' + IC.search + '<input class="field" type="search" placeholder="' + ph + '" data-draft="' + key + '" data-input="' + key + '" value="' + esc(val) + '" aria-label="' + ph + '">'
      + (val ? '<button class="clr" data-a="qClear" data-v="' + key + '" aria-label="검색어 지우기">' + IC.close + '</button>' : '') + '</label>';
  }
  function filterBar(mode, counts) {
    const withStatus = mode === 'journal';
    const perLbl = periodName();
    let h = '<div class="filters' + (withStatus ? ' jfl' : '') + '">';
    if (withStatus) {
      h += '<div class="' + (S.mobile ? 'hscroll' : 'row gap8') + '" role="group" aria-label="상태">' + [['all', '전체'], ['open', '진행 중'], ['held', '보유 중'], ['partial', '부분 매도'], ['closed', '종료']].concat(counts.moved || S.j.status === 'moved' ? [['moved', '이동']] : []).map(x => '<button class="fbtn' + (S.j.status === x[0] ? ' on' : '') + '" data-a="jStatus" data-v="' + x[0] + '" aria-pressed="' + (S.j.status === x[0]) + '">' + x[1] + ' <span class="n">' + counts[x[0]] + '</span></button>').join('') + '</div>';
    }
    h += '<div class="sp"></div>';
    if (withStatus) h += searchBox('jq', '코인 검색', S.j.q);
    h += srcBtn();
    if (mode !== 'daily') h += '<div class="popw"><button class="fbtn' + (S.g.period !== 'all' ? ' act' : '') + '" data-a="pop" data-v="period" aria-haspopup="dialog" aria-expanded="' + (S.pop === 'period' || S.pop === 'range') + '" title="기간 · ' + esc(perLbl) + '">' + IC.cal + ' <span class="fbl">' + esc(perLbl) + '</span>' + IC.chev.replace('<svg', '<svg class="cv"') + '</button>' + (S.pop === 'period' ? periodPop() : S.pop === 'range' ? rangePop() : '') + '</div>';
    return h;
  }
  function srcBtn() {
    const lbl = S.src.mode === 'all' ? '' : (S.src.mode === 'dex' ? '지갑' : '거래소') + (S.src.key ? ' · ' + srcKeyLabel() : '');
    const nmS = S.src.mode === 'dex' && !!S.src.key, lblH = nmS ? '지갑 · ' + ownH(srcKeyLabel()) : esc(lbl);
    return '<div class="popw"><button class="fbtn' + (S.src.mode !== 'all' ? ' act' : '') + '" data-a="pop" data-v="src" aria-haspopup="dialog" aria-expanded="' + (S.pop === 'src') + '"' + (lbl ? (nmS ? ' data-pvl="w"' : '') + ' title="' + esc(nmS ? '지갑 · ' + ownNm(srcKeyLabel()) : lbl) + '"' : ' aria-label="전체 소스"') + '>' + (lbl ? '<span class="fbl">' + lblH + '</span>' : '<span class="hide-sm">전체 </span>소스') + IC.chev.replace('<svg', '<svg class="cv"') + '</button>' + (S.pop === 'src' ? srcPop() : '') + '</div>';
  }
  const ownV = (o, k) => (o && Object.prototype.hasOwnProperty.call(o, k) && typeof o[k] === 'string' ? o[k] : '');
  function srcKeyLabel() {
    const k = String(S.src.key);
    if (S.src.mode === 'cex') return ownV(EX_NAMES, k) || k;
    return ownV(S.D.walletAlias, k) || ownV(S.D.walletAlias, k.toLowerCase()) || short(k);
  }
  function walletChips() {
    const wa = S.D.walletAlias, keys = Object.keys(wa), dup = {};
    keys.forEach(k => { dup[wa[k]] = (dup[wa[k]] || 0) + 1; });
    return keys.map(k => ({ key: k, label: dup[wa[k]] > 1 ? wa[k] + ' ' + String(k).slice(0, 6) : wa[k] })).sort((a, b) => a.label < b.label ? -1 : 1);
  }
  function srcPop() {
    const o = (mode, key, label, lg) => {
      const raw = mode === 'dex' && key ? ownV(S.D.walletAlias, key) : '';
      const name = mode === 'dex' && key ? ownH(raw || label) + (raw && label !== raw ? ' ' + esc(String(key).slice(0, 6)) : '') : esc(label);
      return '<button class="opt' + (S.src.mode === mode && S.src.key === key ? ' on' : '') + '" data-a="setSrc" data-m="' + mode + '" data-k="' + esc(key) + '">' + (lg || '') + name + optCk + '</button>';
    };
    return popBox('소스', '<div class="scroll">' + o('all', '', '전체 소스')
      + '<div class="grp">온체인 지갑</div>' + o('dex', '', '지갑 전체') + walletChips().map(c => o('dex', c.key, c.label)).join('')
      + '<div class="grp">거래소</div>' + o('cex', '', '거래소 전체') + EX_ORDER.map(k => o('cex', k, EX_NAMES[k], exLogo(k))).join('') + '</div>'
      + (!S.D.hasSrc ? '<div class="sep"></div><div class="cap" style="padding:4px 10px">소스 표시가 없는 데이터라 필터가 비어 보일 수 있어요</div>' : ''));
  }
  function periodPop() {
    return popBox('기간', PERIODS.map(p => '<button class="opt' + (S.g.period === p.k ? ' on' : '') + '" data-a="setPeriod" data-v="' + p.k + '">' + esc(p.label) + (p.k === 'custom' && S.g.period === 'custom' ? ' <span class="cap">' + esc(periodName()) + '</span>' : '') + optCk + '</button>').join(''));
  }
  function rangePop() {
    if (!S.rp.ym) S.rp.ym = (isISO(S.g.to) ? S.g.to : todayISO()).slice(0, 7);
    const ym = S.rp.ym, y = +ym.slice(0, 4), mo = +ym.slice(5) - 1;
    const first = new Date(y, mo, 1).getDay(), dim = new Date(y, mo + 1, 0).getDate();
    const lo = rollMinISO(), hi = todayISO(), r = gRange();
    let cells = DOWS.map(d => '<span>' + d + '</span>').join('');
    for (let i = 0; i < first; i++) cells += '<span></span>';
    for (let d = 1; d <= dim; d++) {
      const iso = ym + '-' + pad2(d);
      const dis = iso < lo || iso > hi;
      const isLo = iso === r.lo, isHi = iso === r.hi, inr = r.lo && r.hi && iso > r.lo && iso < r.hi;
      const wk = (first + d - 1) % 7;
      cells += '<button class="' + ((isLo || isHi) ? 'edge' + (isLo ? ' lo' : '') + (isHi ? ' hi' : '') : inr ? 'in' + (wk === 0 ? ' wk0' : '') : '') + '" data-a="rpPick" data-v="' + iso + '"' + (dis ? ' disabled' : '') + '>' + d + '</button>';
    }
    const canPrev = ym > lo.slice(0, 7), canNext = ym < hi.slice(0, 7);
    return popBox('기간 직접 지정', '<div class="rp-f">'
      + '<button class="' + (S.rp.which === 'from' ? 'on' : '') + '" data-a="rpWhich" data-v="from">시작<b class="num">' + esc(S.g.from || '—') + '</b></button>'
      + '<button class="' + (S.rp.which === 'to' ? 'on' : '') + '" data-a="rpWhich" data-v="to">끝<b class="num">' + esc(S.g.to || '—') + '</b></button></div>'
      + '<div class="mh"><button data-a="rpMonth" data-v="-1"' + (canPrev ? '' : ' disabled') + ' aria-label="이전 달">' + IC.left + '</button><span class="sp" style="text-align:center">' + y + '년 ' + (mo + 1) + '월</span><button data-a="rpMonth" data-v="1"' + (canNext ? '' : ' disabled') + ' aria-label="다음 달">' + IC.right + '</button></div>'
      + '<div class="g">' + cells + '</div><div class="cap" style="margin-top:8px">같은 날을 두 번 고르면 그 하루만 봐요</div>'
      + '<div class="ft"><button class="btn sm" data-a="setPeriod" data-v="all">초기화</button><button class="btn sm pri" data-a="popClose">적용</button></div>', 'rp');
  }
  function vJournal() {
    const D = S.D;
    const { base, list } = jList();
    const counts = { all: base.length, open: base.filter(p => p._st !== '종료').length, held: base.filter(p => p._st === '보유').length, partial: base.filter(p => p._st === '부분 매도').length, closed: base.filter(p => p._st === '종료' && !p._mv).length, moved: base.filter(p => p._mv).length };
    const ql = S.j.q.trim();
    const rSpot = sum(Object.keys(D.f.realizedByDate || {}).filter(k => gPass(k)), k => num(D.f.realizedByDate[k]));
    const rFut = sum(Object.keys(D.fut.realizedByDate || {}).filter(k => gPass(k)), k => num(D.fut.realizedByDate[k]));
    const cardSum = sum(base, p => cardReal(p));
    const narrowed = !!ql || S.src.mode !== 'all';
    let realized = rSpot + rFut;
    if (ql) realized = sum(base, p => cardReal(p));
    else if (S.src.mode !== 'all') realized = cardSum;
    let winSum = 0, loseSum = 0;
    let win = 0, lose = 0, even = 0, sellsN = 0, payN = 0, depN = 0, closedN = 0, unvN = 0, unvP = 0, unkC = 0, lpC = 0;
    base.forEach(p => { if (p._lp) return; const a = pAgg(p); unvN += S.g.period === 'all' ? a.allU : a.inU; unvP += S.g.period === 'all' ? a.allUP : a.inUP; });
    D.merged.forEach(p => {
      if (ql && String(p.sym).toUpperCase().indexOf(ql.toUpperCase()) < 0) return;
      let touched = false, sE = 0;
      const sa = srcAgg(p);
      if (sa) { touched = sa.any; sE = sa.s; depN += sa.dep; }
      else arr(p.events).forEach(e => { if (!srcPass(e) || !gPass(e.t)) return; touched = true; if (/매도/.test(e.k)) sE++; if (e.k === '입금 확인') depN++; });
      if (S.src.mode === 'all' && p.actByDay) { const a = pAgg(p); sellsN += a.inS; payN += a.inP; touched = touched || a.any; } else sellsN += sE;
      const a9 = pAgg(p), sold9 = S.g.period === 'all' ? num(p.soldQty) > 0 || Math.abs(num(p.realized)) >= 0.005 : a9.inS > 0 || a9.inU > 0 || Math.abs(a9.inR) >= 0.005;
      if (touched && sold9 && p._st === '종료' && p.kind !== 'gas' && p.kind !== 'stable' && p.kind !== 'quarantined') {
        closedN++; const r = cardReal(p), a = a9;
        if (p._noCost || (Math.abs(r) < 0.005 && (S.g.period === 'all' ? a.allU : a.inU) > 0)) unkC++;
        else { const v = cardRealV(p); if (isZ(v)) even++; else if (v > 0) { win++; winSum += v; } else { lose++; loseSum -= v; } }
      }
    });
    const lpG = new Map();
    D.lpCycles.forEach(l => {
      if (l.status !== '종료' || S.src.mode !== 'all' || (ql && String(l.sym).toUpperCase().indexOf(ql.toUpperCase()) < 0)) return;
      const rb = l.realizedByDay || {}, ks = Object.keys(rb).filter(k => S.g.period === 'all' || gPass(k));
      if (!ks.length) return;
      const gk = String(l.sym) + '|' + (l.chain || '') + '|' + ks.map(k => isoDay(k) || k).sort().pop();
      const g0 = lpG.get(gk) || { r: 0, rk: 0, hasK: true }, rkb = l.realizedKrwByDay;
      g0.r += sum(ks, k => num(rb[k])); if (rkb && ks.every(k => rkb[k] != null)) g0.rk += sum(ks, k => num(rkb[k])); else g0.hasK = false;
      lpG.set(gk, g0);
    });
    lpG.forEach(g0 => { const r = g0.r, v = KV(r, g0.hasK ? g0.rk : null); closedN++; lpC++; if (isZ(v)) even++; else if (v > 0) { win++; winSum += v; } else { lose++; loseSum -= v; } });
    const gap = !narrowed && D.merged.some(p => p.realizedByDay != null) ? cardSum - rSpot : 0;
    const rSpotK = D.hasKrw ? sum(Object.keys(D.f.realizedKrwByDate || {}).filter(k => gPass(k)), k => num(D.f.realizedKrwByDate[k])) : null;
    const rFutK = D.hasKrw ? sum(Object.keys(D.fut.realizedByDate || {}).filter(k => gPass(k)), k => (D.fut.realizedKrwByDate || {})[k] != null ? num(D.fut.realizedKrwByDate[k]) : num(D.fut.realizedByDate[k]) * rate()) : null;
    const realizedV = !D.hasKrw ? realized : (ql ? sum(base, p => cardRealV(p)) : (S.src.mode !== 'all' ? sum(base, p => cardRealV(p)) : KV(realized, rSpotK + rFutK)));
    const fsKs = narrowed ? [] : Object.keys(D.fsRbd || {}).filter(k => gPass(k));
    const fsU = sum(fsKs, k => num(arr(D.fsRbd[k])[0])), fsV = KV(fsU, D.hasKrw ? sum(fsKs, k => num(arr(D.fsRbd[k])[1])) : null);
    const fsWaitN = narrowed || !D.firstSeen || !D.firstSeen.on ? 0 : num(D.firstSeen.wait);
    S.jLast = { period: S.g.period, from: S.g.from, to: S.g.to, status: S.j.status, realized, rSpot, rFut, cardSum, gap, unvN, unvP, sellsN, n: base.length, realizedV, rSpotK, rFutK, cur: S.cur, rate: rate() };
    const brk = narrowed ? '보이는 카드 기간 실현 합 · 선물 제외'
      : '현물 ' + m(KV(rSpot, rSpotK), { sign: true, compact: true }) + ' · 선물 ' + m(KV(rFut, rFutK), { sign: true, compact: true })
        + (unvN && S.g.period === 'all' ? '<br><span title="기간 안 원가 미확인 매도 체결 수 — 미매칭 목록(코인별 행)과 단위가 달라요">원가 미확인 매도 ' + unvN + '회 ' + m(unvP, { compact: true }) + ' 실현 제외</span>' : '')
        + (Math.abs(gap) >= 1 ? ' <span class="wtxt">· 카드 합과 ' + m(gap, { sign: true, compact: true }) + ' 차이</span>' : '');
    const openU = base.filter(p => p.held > 0 && p._st !== '종료'), unreal = sum(openU, p => num(p.unreal));
    const pmkt = (() => {
      if (S.g.period === 'all' || narrowed || !D.daily.length) return null;
      const av = D.daily.filter(x => x._prev && x.att && typeof x.att === 'object');
      let mk = 0, n = 0, v2 = 0; const by = new Map();
      av.filter(x => gPass(x.date)).forEach(x => { const a = attOf(x.date); if (!a) return; n++; mk += a.mk; if (a.v2) v2++; a.top.forEach(t => by.set(t.sym, (by.get(t.sym) || 0) + t.v)); });
      if (!n) return null;
      const b = gBounds(), f0 = av.length ? isoDay(av[0].date) : '';
      const part = !b || !b.lo || !f0 || f0 > b.lo;
      const top = Array.from(by.entries()).filter(e => Math.abs(e[1]) >= 0.5).sort((x, y) => Math.abs(y[1]) - Math.abs(x[1])).slice(0, 3).map(e => ({ sym: e[0], v: e[1] }));
      return { mk, n, part, top, v2 };
    })();
    const gas = gasList(), gasT = sum(gas, g => g.spot + g.lp);
    S.jLast.sum = { realized, realizedV, unreal, pmkt, openN: openU.length, gasT, gasN: gas.filter(g => g.kind !== 'exfee').length, unvN: D.unvN, closedN, win, lose, even, unkC, lpC, sellsN };
    const bar = filterBar('journal', counts) + '</div>';
    const wr = (win + lose) ? Math.round(win / (win + lose) * 100) : null;
    const sgc = v => m(v, { sign: true, compact: true });
    const capMain = (narrowed ? '보이는 카드 기간 실현 합 · 선물 제외' : '<span class="nowrap">현물 ' + sgc(KV(rSpot, rSpotK)) + ' ·</span> <span class="nowrap">선물 ' + sgc(KV(rFut, rFutK)) + '</span>')
      + (closedN ? '<span class="pvx"> <span class="nowrap">· 승 ' + win + ' · 패 ' + lose + (wr != null ? ' (' + wr + '%)' : '') + '</span></span>' : '')
      + (Math.abs(gap) >= 1 ? ' <span class="wtxt">· 카드 합과 ' + sgc(gap) + ' 차이</span>' : '');
    const allP = S.g.period === 'all';
    const openTop = openU.filter(p => Math.abs(num(p.unreal)) >= 0.005).sort((a, b) => Math.abs(num(b.unreal)) - Math.abs(num(a.unreal)));
    const openTopTxt = openTop.slice(0, 3).map(p => esc(p._lp ? lpNm(p.sym, p._lp.key) : p.sym) + ' <span class="' + cls(num(p.unreal)) + '">' + sgc(num(p.unreal)) + '</span>').join(' · ') + (openTop.length > 3 ? ' · 외 ' + (openTop.length - 3) + '개' : '');
    const mktTip = pmkt ? esc(periodName()) + ' 날마다 총자산 변동 중 시세 몫의 합(' + (pmkt.v2 ? '평가 변화 — 전일 보유 × 가격 변화 · 판 코인 평가 손익은 실현으로 옮겨가 뺌 · 입출금 제외' : '전일 마감 수량 × 가격 변화 · 입출금·매매 제외') + (S.cur !== 'USD' ? ' · 지난날 = 그날 마감 환율 원화' : '') + ')' + (pmkt.part ? ' — 분해는 최근 ' + pmkt.n + '일만 있어 그 날들만 합했어요' : '') : '';
    const unrTip = allP ? '지금 보유 중인 진행 사이클의 매수 후 누적 평가손익(현재가 − 평균 매수가) — 기간 손익이 아니에요'
      : '선택 기간에 거래한 사이클 중 지금 보유 중인 것의 매수 후 누적 평가손익(현재가 − 평균 매수가) — 이 기간 동안의 변화가 아니에요. 전체 보유 기준은 대시보드 평가손익과 같아요';
    const c1 = !allP && pmkt
      ? uiCell(esc(periodName()) + ' 시세 변동' + (pmkt.part ? ' <span class="mut">≈</span>' : ''), '<span class="' + cls(pmkt.mk) + '">' + N('j:mkt', pmkt.mk, 'sc') + '</span>', 'jStatus', 'open', mktTip)
      : uiCell(allP ? '지금 평가손익' : '평가손익(거래 코인)', '<span class="' + cls(unreal) + '">' + N('j:unr', unreal, 'sc') + '</span>', 'jStatus', 'open', unrTip);
    const gasTip = '가스·체결 수수료 전부(매수·매도·이동·실패). 명세의 \'수수료·비용\'은 그중 매도 쪽과 매매 외 가스만, 사이클 \'가스 비용\'은 매매 외 가스만이에요';
    const unvTip = '건 = 미매칭 목록의 원가 미확인 매도 행(코인별 1행) · 회 = 그 매도의 체결 횟수 — 기간 필터와 무관한 전체 기간 값이에요';
    const cells = '<div class="ucells jcells">' + c1 + uiCell('가스·수수료', m(gasT, { compact: true }), 'jView', 'gas', gasTip)
      + uiCell('원가 미확인', '<span class="wtxt">' + D.unvN + '건</span>', 'goPend', 'unv', unvTip) + '</div>';
    const dr = (k, v, tip) => '<div class="jsr"' + (tip ? ' title="' + esc(tip) + '"' : '') + '><span class="k">' + k + '</span><span class="v num">' + v + '</span></div>';
    const jsOpen = uiOpen('jsum', false);
    const det = () => '<div class="jsdl">'
      + (pmkt ? dr(esc(periodName()) + ' 총손익', '<b class="' + cls(realizedV + pmkt.mk) + '">' + sgc(realizedV + pmkt.mk) + '</b> = 실현 ' + sgc(realizedV) + ' + 시세 변동 ' + sgc(pmkt.mk), '기간 총손익 = 매도로 확정된 실현 + 그 기간 날마다 시세 변동(자산 변동 분해의 시세 몫 합 · ' + (pmkt.v2 ? '입출금 제외 · 판 코인의 평가 손익은 실현으로 옮겨가 실현에만 셈' : '입출금·매매 효과 제외') + ')' + (pmkt.part ? ' · 시세 분해는 최근 ' + pmkt.n + '일만 있어요' : '')) : '')
      + dr('실현 구성', brk)
      + dr('청산', closedN ? '<span class="pvx" title="청산(종료)된 매매 사이클' + (lpC ? '·LP ' + lpC + '개 포함' : '') + ' — 스테이블 환전·가스 제외 · 원가 미확인 = 원가를 몰라 실현에서 빠진 사이클(승률 계산 제외)">청산 ' + closedN + '건 · 승 ' + win + ' · 패 ' + lose + (even ? ' · 본전 ' + even : '') + (unkC ? ' · 원가 미확인 ' + unkC : '') + (wr != null ? ' (승률 ' + wr + '%)' : '') + '</span>' : '청산 완료 없음')
      + dr('매도 체결', '<span title="거래소 부분 체결을 각각 센 매도 체결 수(코인을 사며 대금으로 나간 스테이블·네이티브 = 스왑 지불은 따로) — 일별 기록의 매도 기록 수와 단위가 달라요">' + nf('ko-KR').format(sellsN) + '회' + (payN ? ' · 스왑 지불 ' + nf('ko-KR').format(payN) + '회' : '') + '</span>')
      + (win + lose ? dr('이익 / 손실', '이익 합 <span class="' + cls(winSum) + '">' + sgc(winSum) + '</span> / 손실 합 <span class="' + cls(-loseSum) + '">' + sgc(-loseSum) + '</span>' + (loseSum > 0.005 ? ' · 손익비 ' + (winSum / loseSum).toFixed(winSum / loseSum >= 10 ? 0 : 1) : ''), '승 ' + win + '건 이익 합 ÷ 패 ' + lose + '건 손실 합 — 1 보다 크면 번 돈이 잃은 돈보다 많아요' + (lpC ? ' · 청산 LP 는 같은 풀·같은 날을 한 건으로 셌어요' : '')) : '')
      + (!allP && pmkt
        ? (pmkt.top.length ? dr('시세 변동 큰 코인', pmkt.top.map(t => esc(t.sym) + ' <span class="' + cls(t.v) + '">' + sgc(t.v) + '</span>').join(' · ')) : '')
          + dr('거래 코인 보유분', '평가손익(매수 후 누적) <span class="' + cls(unreal) + '">' + sgc(unreal) + '</span> · 전체 보유 <span class="' + cls(D.unreal) + '">' + sgc(D.unreal) + '</span>', unrTip)
        : dr(allP ? '평가손익 큰 코인' : '평가손익 기준', (openTopTxt || '진행 중 ' + openU.length + '개') + (allP ? '' : ' · 매수 후 누적 · 현재가 기준 · 전체 보유 <span class="' + cls(D.unreal) + '">' + sgc(D.unreal) + '</span>'))
          + (allP ? dr('대시보드와 차이', '대시보드 평가손익 <span class="nowrap ' + cls(D.unreal) + '">' + sgc(D.unreal) + '</span>은 원가 확인 수량만 · 여기는 사이클 평균 매수가 기준') : ''))
      + dr('가스·수수료', '<span class="pvx">' + esc(gasScope()) + ' · ' + gasCnt(gas) + '</span>')
      + dr('원가 미확인', (allP ? '원가 미확인 매도 · 코인별' + (unvN ? ' · 체결 ' + nf('ko-KR').format(unvN) + '회' : '') + ' · 손익에서 빠짐' : esc(periodName()) + ' 원가 미확인 매도 ' + nf('ko-KR').format(unvN) + '회' + (unvP >= 1 ? ' ' + m(unvP, { compact: true }) : '') + ' · 손익에서 빠짐') + (D.unvHidN ? ' · 소액 ' + D.unvHidN + '건은 숨김' : ''), unvTip)
      + tgapD + '</div>';
    let tgapD = '';
    const tgapL = (() => {
      if (narrowed) return '';
      if (D.taxFull && !perMonthAligned()) return '<div class="cap jsgap">양도차익 명세는 월 단위로 묶어 이 기간과 직접 비교하지 않아요 — 명세에서 월별로 보세요</div>';
      let gS, gO, gT; try { gS = taxGroups('spot'); gT = taxGroups('st'); gS = gS.concat(gT); gO = taxGroups('inc').concat(taxGroups('fut')); } catch (e) { return ''; }
      const stx = sum(gT, g => g.pnlV - g.pnlV0);
      const tp = sum(gS, g => g.pnlV), sep = sum(gO, g => g.pnlV), fx = tp - sum(gS, g => g.pnlV0) + sep - sum(gO, g => g.pnlV0) - stx, gap = tp - realizedV;
      if (isZ(gap)) return '';
      const rest = gap + sep - fx - stx;
      const nb = v => '<span class="num nowrap">' + m(v, { sign: true }) + '</span>';
      tgapD = dr('명세 기준과 차이', '양도차익(명세 기준) ' + nb(tp))
        + (!isZ(stx) ? dr('스테이블 원화 환차', nb(stx) + ' · 명세에만(실현손익엔 안 들어가요)') : '')
        + (!isZ(sep) ? dr('기타 소득·선물', nb(sep) + ' · 명세에서 따로 표') : '')
        + (!isZ(fx) ? dr('환율 몫', (!isZ(rest) || !isZ(sep) || !isZ(stx) ? nb(fx) + ' · ' : '') + '명세는 원가를 취득 시점 환율로 셈') : '')
        + (!isZ(rest) ? dr('그 밖', D.taxFull ? '집계 차이 ' + nb(rest) : '명세는 최근 ' + nf('ko-KR').format(arr(D.tax).length) + '건만 받아 일부예요') : '');
      return '<div class="cap jsgap">명세 기준과 차이 <b class="num nowrap">' + m(gap, { sign: true }) + '</b>' + (jsOpen ? '' : ' <span class="mut">· 내역은 자세히</span>') + '</div>';
    })();
    const sumc = '<div class="card jsum">'
      + '<button type="button" class="jsm" data-a="jView" data-v="tax" title="누르면 양도차익 명세"><span class="l">' + (ql ? '검색 결과' : esc(periodName())) + ' 실현손익<span class="go">명세' + IC.right + '</span></span><span class="v num ' + clsV(realizedV) + '">' + N('j:real', realizedV, S.mobile ? 'sc' : 's') + '</span></button>'
      + '<div class="jscap"><span class="cap num sans">' + capMain + '</span><button type="button" class="link jsmore" data-a="uiFold" data-v="jsum" aria-expanded="' + jsOpen + '">' + (jsOpen ? '접기' : '자세히') + UI_CHEV + '</button></div>'
      + tgapL + (Math.abs(fsU) >= 0.005 || fsWaitN ? '<div class="cap num jsfs" title="최초 인식 시가 = 원가를 모르던 수량(기초 잔고·원가 없는 입금·에어드랍 등)을 그 수량이 장부에 처음 생긴 날 시가로 잡은 원가 — 처음 인식이 산 날보다 늦으면 그 전 상승분은 빠져요'
        + (fsWaitN ? ' · 시세 대기 = 그날 시세를 아직 못 받아 원가 미확인으로 둔 매도(받으면 자동 반영)' : '') + ' · 설정 › 원가 계산에서 끌 수 있어요">'
        + (Math.abs(fsU) >= 0.005 ? '이 중 최초 인식 시가로 계산된 실현 <span class="' + cls(fsU) + '">' + sgc(fsV) + '</span>' : '')
        + (fsWaitN ? '<span class="pvx">' + (Math.abs(fsU) >= 0.005 ? ' · ' : '최초 인식 시가 ') + '시세 대기 ' + nf('ko-KR').format(fsWaitN) + '건</span>' : '') + '</div>' : '')
      + cells + (jsOpen ? clps('uf:jsum', det()) : '') + '</div>';
    const tabs = '<div class="subtabs" role="tablist">' + [['cycles', '사이클', list.length], ['habits', '습관', null], ['tax', '양도차익 명세', null], ['gas', '가스·수수료', null], ['feed', '전체 이벤트', null]].concat(D.krw ? [['krw', '원화 입출금', null]] : []).map(t => '<button role="tab" aria-selected="' + (S.j.view === t[0]) + '" class="' + (S.j.view === t[0] ? 'on' : '') + '" data-a="jView" data-v="' + t[0] + '">' + t[1] + (t[2] != null ? '<span class="n">' + t[2] + '</span>' : '') + '</button>').join('') + '</div>';
    let body;
    if (S.j.view === 'habits') body = habitsHTML();
    else if (S.j.view === 'tax') body = taxHTML();
    else if (S.j.view === 'gas') body = gasHTML(gas);
    else if (S.j.view === 'feed') body = feedHTML();
    else if (S.j.view === 'krw' && D.krw) body = krwHTML();
    else body = cyclesHTML(list, depN);
    const jw = wowSlot('journal.head');
    return bar + sumc + (S.mobile || !jw ? jw + tabs : '<div class="stw jstw">' + tabs + jw + '</div>') + body;
  }
  function cyclesHTML(list) {
    const sortSel = '<div class="row" style="margin:-4px 0 12px;gap:8px;flex-wrap:wrap"><span class="cap pvx">' + list.length + '개 · 같은 코인은 한 카드로 묶었어요</span><span class="sp"></span><span class="cap hide-sm">정렬</span>'
      + '<div class="seg" role="group" aria-label="정렬">' + J_SORTS.map(x => '<button data-a="jSort" data-v="' + x[0] + '" class="' + (S.j.sort === x[0] ? 'on' : '') + '" aria-pressed="' + (S.j.sort === x[0]) + '"' + (x[0] === 'value' ? ' title="평가금액 큰 순 — 남은 수량 × 현재가(보유표와 같은 평가) · 다 판 사이클은 맨 뒤"' : '') + '>' + x[1] + '</button>').join('') + '</div></div>';
    if (!list.length) return sortSel + '<div class="card empty"><div class="eic">' + IC.search + '</div><b>조건에 맞는 사이클이 없어요</b>' + (S.j.q ? '"' + esc(S.j.q) + '" 검색 결과가 없어요. ' : '기간·소스·상태 필터를 넓혀 보세요. ') + '<button class="link" data-a="jReset">필터 초기화</button></div>';
    const items = lpGroupItems(list);
    const jSig = [S.j.q, S.j.status, S.j.sort, S.g.period, S.g.from, S.g.to, S.src.mode, S.src.key].join('|');
    if (S.j.pgSig !== jSig) { S.j.pgSig = jSig; uiPgReset('jcy'); }
    const pgJ = uiPgSlice('jcy', items), shown = pgJ.rows;
    const perOn = S.g.period !== 'all';
    const head = '<div class="cychead" aria-hidden="true"><span>코인</span><span>경로 · 진행</span><span>' + (perOn ? '기간 실현' : '실현') + '</span><span>원가</span><span title="남은 수량 × 현재가 — 보유표와 같은 평가">평가금액</span><span>평가손익</span><span title="(누적 실현 + 평가손익) ÷ 원가">수익률</span><span></span></div>';
    return sortSel + (pgJ.last > 0 ? '<div class="upga" data-pga="jcy"></div>' : '') + head + shown.map(x => x._grp ? lpGrpCard(x) : cycCard(x)).join('') + uiPgBar('jcy', items.length, { unit: '개', cls: 'jmore' });
  }
  const lpGrpKey = p => { const l = p._lp; if (!l || !(l.state === 'closed' || (p._st || p.status) === '종료')) return null;
    return [String(lpNm(p.sym, l.key)).replace(/\s+#\S+$/, '').replace(/\s*\/\s*/g, '/'), l.protocol || '', l.chain || ''].join('|'); };
  function lpGroupItems(list) {
    const by = new Map();
    list.forEach(p => { const k = lpGrpKey(p); if (k) { if (!by.has(k)) by.set(k, []); by.get(k).push(p); } });
    const out = [], seen = new Set();
    list.forEach(p => { const k = lpGrpKey(p); if (!k || by.get(k).length < 2) { out.push(p); return; } if (seen.has(k)) return; seen.add(k); out.push({ _grp: k, ms: by.get(k) }); });
    return out;
  }
  function lpGrpCard(g) {
    const ms = g.ms, l0 = ms[0]._lp, nm = g._grp.split('|')[0];
    S.j.grpM[g._grp] = ms.map(p => p.key);
    const open = S.j.lpGrp.has(g._grp) || ms.some(p => S.j.open.has(p.key));
    const perOn = S.g.period !== 'all';
    const rMs = ms.filter(p => cardReal(p)), rv = sum(rMs, p => cardRealV(p));
    const ds = ms.map(p => String(p._lp.opened || p.opened || '')).filter(Boolean).sort();
    const rng = ds.length ? (ds[0] === ds[ds.length - 1] ? ds[0] : ds[0] + ' ~ ' + ds[ds.length - 1]) : '';
    const rt0 = ['LP', l0.protocol, l0.chain].filter(Boolean).join(' · '), rt = rt0 + (rng ? ' · ' + rng : '');
    const rlN = rMs.length ? '실현 있는 포지션 ' + rMs.length + '개' : '';
    const mt = '<span class="pill g sm gpl2">종료</span><span class="pvx">포지션 ' + ms.length + '개 · 모두 인출 완료' + (rlN ? '<span class="gmore"> · ' + rlN + '</span>' : '') + '</span>';
    const rTip = (perOn ? '선택한 기간에 체결된 ' : '') + '종료 LP ' + ms.length + '개 실현의 합 — 펼치면 포지션별';
    const dash = t => '<div class="n num mut"' + (t ? ' title="' + esc(t) + '"' : '') + '>—</div>';
    const realCell = rMs.length ? '<div class="n num ' + cls(rv) + '" title="' + esc(rTip) + '">' + m(rv, { sign: true }) + '</div>' : dash(rTip);
    const kc = (k, c) => '<div class="kcol"><div class="k">' + k + '</div>' + c + '</div>';
    return '<div class="card cyc lpgrp' + (open ? ' open' : '') + '"><div class="hd" role="button" tabindex="0" aria-expanded="' + open + '" data-a="jGrp" data-k="' + esc(g._grp) + '" aria-label="' + esc(nm + ' LP 종료 ' + ms.length + '개 — ' + (open ? '접기' : '펼치기')) + '">'
      + '<div class="asset">' + lpIcon(l0) + '<div class="ell"><div class="sym ell lpsym" title="' + esc(nm + ' LP · 종료 ' + ms.length + '개') + '"><b class="tnm lpn"><span class="nm">' + esc(nm) + '</span> <span class="id pvx">×' + ms.length + '</span></b> <span class="pill g sm gpl1">종료</span></div></div></div>'
      + '<div class="stepcol"><div class="rt ell" title="' + esc(rt) + '">' + esc(rt0) + (rng ? '<span class="grng"> · ' + esc(rng) + '</span>' : '') + '</div><div class="mt">' + mt + '</div></div>'
      + kc(perOn ? '기간 실현 합' : '실현 합', realCell)
      + '<div class="gspan"><div class="rt num">' + esc(rng) + '</div><div class="mt pvx">' + esc(rlN ? rlN + ' · ' : '') + '원가·평가금액은 펼쳐서 포지션별로</div></div>'
      + '<div class="kcol gdash"><div class="k">원가</div>' + dash('포지션마다 같은 자금을 다시 넣어 합치면 부풀어요 — 펼쳐서 포지션별로') + '</div>'
      + ['평가금액', '평가손익', '수익률'].map(x => '<div class="kcol gdash"><div class="k">' + x + '</div>' + dash('') + '</div>').join('')
      + '<div class="mcol"><div class="n num ' + (rMs.length ? cls(rv) : 'mut') + '">' + (rMs.length ? m(rv, { sign: true, compact: true }) : '—') + '</div><div class="k">' + (perOn ? '기간 실현 합' : '실현 합') + '</div></div>'
      + '<div class="chev' + (open ? ' o' : '') + '">' + IC.chev + '</div></div>'
      + (open ? '<div class="lpgm">' + ms.map(cycCard).join('') + '</div>' : '') + '</div>';
  }
  function statusPill(p) {
    if (p.kind === 'stable') return '<span class="pill g sm" title="스테이블 매도의 원가·정산 차이 — 사이클이 아니라 날짜별 요약">스테이블 환전</span>';
    if (p.kind === 'quarantined') return '<span class="pill w sm">격리 자산</span>';
    if (p.kind === 'gas') return '<span class="pill g sm" title="매매에 붙지 않은 온체인 가스(실패·승인·전송·브릿지·LP) — 사이클이 아니라 날짜별 비용 요약 · 명세 \'기타 비용(가스)\'와 같은 값, 가스·수수료 탭 전체의 일부">가스 비용</span>';
    if (p.kind === 'stake') return '<span class="pill g sm" title="받은 시각 시가 = 소득 실현(원가도 그 시가) — 사이클이 아니라 날짜별 보상 요약">스테이킹 보상</span>';
    const st = p._st || p.status;
    if (st === '종료' && p._mv) return '<span class="pill a sm" title="매수분을 전량 ' + esc(p._mv) + jo(p._mv, '으로', '로') + ' 옮겼어요 — 판 게 아니라 보유·원가가 도착한 곳 카드에서 이어져요">이동 → ' + esc(p._mv) + '</span>';
    if (st === '종료') return p._dustLeft ? '<span class="pill g sm" title="' + esc('남은 평가 ' + m(num(p._heldVal)) + ' · 그 평가손익 ' + m(num(p.unreal), { sign: true }) + ' — 둘 다 소액 기준($' + Math.max(1, S.dust || 0) + ') 미만이라 종료로 봐요(평가손익 합계 밖)') + '">종료 · 잔여 소액</span>' : '<span class="pill g sm">종료</span>';
    return st === '보유' ? '<span class="pill a sm">보유 중</span>' : '<span class="pill w sm">부분 매도</span>';
  }
  const STEP_CHIP = { '온체인 매수': 'w', '거래소 매수': 'a', '토큰 세일 매수': 'a' };
  const plainT = h => String(h).replace(/<[^>]+>/g, '').replace(/&(amp|lt|gt|quot|#39);/g, (x, k) => ({ amp: '&', lt: '<', gt: '>', quot: '"', '#39': "'" })[k]);
  const jDurTxt = sec => { const mi = Math.round(sec / 60); return mi < 60 ? mi + '분' : mi < 48 * 60 ? Math.round(mi / 60) + '시간' : Math.round(mi / 1440) + '일'; };
  function cycLines(p, perOn, ag, done) {
    const sg = v => m(v, { sign: true, compact: S.mobile });
    if (p._lp) {
      const l = p._lp, raw = l.raw || {}, ot = num(raw.openedTs), lt = num(raw.lastTs);
      const rt = ['LP', l.protocol, l.chain].filter(Boolean).join(' · ') + ' · ' + (l.opened || p.opened || '—') + (done ? (ot > 0 && lt > ot ? ' · ' + jDurTxt(lt - ot) : '') : ' 시작');
      const st = arr(p.steps).map(x => term(x).replace(/^유동성 /, '')).join(' → ');
      const rng = !done && l.lo > 0 && l.hi > l.lo ? ' · 범위 ' + pxr(l.lo) + ' ~ ' + pxr(l.hi) + (l.price > 0 ? ' · 현재 ' + pxr(l.price) : '') : '';
      return [esc(rt), esc(st + rng)];
    }
    const legs = p._nLegs > 1 ? ' · 포지션 ' + p._nLegs + '개 합산' : '';
    const last = p._last ? p._last.slice(5, 10) : '';
    const aside = [];
    if (perOn) {
      if (ag.befR) aside.push('이전 실현 <span class="num">' + esc(sg(ag.hasK ? KV(ag.befR, ag.befRK) : ag.befR)) + '</span>');
      if (ag.aftD.length) { const d = ag.aftD.length > 1 ? mdOf(ag.aftD[0]) + '~' + mdOf(ag.aftD[ag.aftD.length - 1]) : mdOf(ag.aftD[0]);
        aside.push('이후 ' + esc(d) + (done ? ' 전량 매도' : ' 매도') + (ag.aftR ? ' <span class="num">' + esc(sg(ag.hasK ? KV(ag.aftR, ag.aftRK) : ag.aftR)) + '</span>' : '') + ' (기간 밖)'); }
    }
    const rt = '<span class="rtp">' + esc(p.chain === '?' ? '거래소' : p.chain) + ' · ' + (done ? esc(p.opened) + ' ~ ' + esc(last) : esc(p.opened) + ' 시작') + (legs ? '<span class="pvx">' + esc(legs) + '</span>' : '') + '</span>' + (aside.length ? '<span class="rta num">\u00A0· ' + aside.join(' · ') + '</span>' : '');
    const steps = arr(p.steps).map(term), s0 = steps[0] || '';
    const chip = s0 && s0 !== String(p.sym) ? '<span class="pill ' + (STEP_CHIP[s0] || 'g') + ' sm"' + (steps.length > 1 ? ' title="경로: ' + esc(steps.join(' → ')) + '"' : '') + '>' + esc(s0) + '</span>' : '';
    let prog;
    if (p.kind === 'stable') prog = '매도 시 원가(매수가)와 정산액 차이';
    else if (p.kind === 'gas') prog = '실패·승인·전송·브릿지·LP 가스 — 그날 실현에서 차감';
    else if (p.kind === 'stake') prog = '에폭 보상·MEV 팁 — 받은 날 시가로 실현(소득) · 시가 없는 보상은 0';
    else if (p.kind === 'quarantined') prog = '격리 자산 매도분';
    else if (p._noCost && !(num(p.soldQty) > 0)) prog = '원가 미확인 · 매수 기록 없는 유입';
    else if (p._mv) prog = '매도 없음 · 전량 이동 → ' + esc(p._mv);
    else if (p._soldPct <= 0) prog = (perOn ? ag.inU : ag.allU) > 0 ? '원가 확인분 매도 없음' : '아직 매도 없음';
    else prog = '<span class="mb" aria-hidden="true"><i style="width:' + Math.max(2, p._soldPct).toFixed(1) + '%"></i></span>매도 진행 ' + (p._soldPct >= 99.5 && p._soldPct < 100 ? '99.5%↑' : p._soldPct < 0.5 ? '1% 미만' : Math.round(p._soldPct) + '%');
    const cnt = [];
    if (ag.inB) cnt.push('매수 ' + nf('ko-KR').format(ag.inB));
    if (ag.inS) cnt.push('매도 ' + nf('ko-KR').format(ag.inS));
    const real = cardReal(p), unvN = perOn ? ag.inU : ag.allU;
    const unv = real && unvN ? ' · <span class="wtxt" title="회 = 매도 체결 횟수">원가 미확인 매도 ' + nf('ko-KR').format(unvN) + '회 (실현 제외)</span>' : '';
    return [rt, chip + '<span class="ell">' + prog + (cnt.length ? '<span class="pvx"> · ' + (perOn ? '이 기간 ' : '') + cnt.join(' · ') + '</span>' : '')    + unv + '</span>'];
  }
  const cKrw = (p, f) => { if (p._nLegs > 1 || p._lp) return null; const v = num(p[f]); return v > 0 ? v : null; };
  const rKrw = p => { if (p._lp || num(p.realizedFb) || !p.realizedKrwByDay) return null; const ks = Object.keys(p.realizedByDay || {});
    if (Math.abs(sum(ks, k => num(p.realizedByDay[k])) - num(p.realized)) > 0.05 || ks.some(k => p.realizedKrwByDay[k] == null)) return null; return sum(ks, k => num(p.realizedKrwByDay[k])); };
  function cycCard(p) {
    const open = S.j.open.has(p.key);
    const real = cardReal(p), realV = cardRealV(p);
    const perOn = S.g.period !== 'all' && p.realizedByDay != null;
    const ag = pAgg(p), unvN = perOn ? ag.inU : ag.allU;
    const done = (p._st || p.status) === '종료';
    const unr = p.held > 0 && !done ? num(p.unreal) : null;
    const unvOnly = !real && (unvN > 0 || (!perOn && num(p.unvProceeds) > 0));
    const covP = !p._lp && !done && num(p.held) > 0 && num(p.unknownQty) > 0 ? Math.max(0, Math.min(100, (1 - num(p.unknownQty) / num(p.held)) * 100)) : null;
    const covTxt = covP != null && covP < 50 ? '원가 확인 ' + (covP < 1 ? '1% 미만' : Math.round(covP) + '%') : '';
    const covTip = covTxt ? ' title="보유 ' + esc(q(num(p.held)) + ' ' + p.sym) + ' 중 ' + esc(q(num(p.unknownQty))) + '개가 원가 미확인 — 원가는 원가 확인된 수량 몫만"' : '';
    const unkQ = covP != null && unr != null && !p._noCost ? num(p.unknownQty) : 0;
    const unkTxt = unkQ > 0 ? '원가 모르는 ' + (S.hide || S.rand || !(unkQ >= 1 && unkQ < 1000) ? q(unkQ) : nf('ko-KR', null, 2).format(unkQ)) + '개 제외' : '';
    const unkTip = unkTxt ? ' title="' + esc('남은 ' + q(num(p.held)) + ' ' + p.sym + ' 중 ' + q(unkQ) + '개는 원가를 몰라 원가·평가손익에서 빠졌어요 — 평가금액은 남은 수량 전부') + '"' : '';
    const fsE = p.fsEst && (num(p.fsEst.cost) >= 0.005 || Math.abs(num(p.fsEst.real)) >= 0.005) ? p.fsEst : null;
    const fsChip = fsE ? '<span class="kchip pvx" data-pvt="1" title="' + esc((num(fsE.cost) >= 0.005 ? '이 카드 원가 중 ' + m(num(fsE.cost)) + (num(fsE.qty) ? '(' + q(num(fsE.qty)) + '개)' : '') + '는' : '이 카드로 옮겨 온 원가 일부는')
      + ' 최초 인식 시가(원가를 모르던 수량을 그 수량이 장부에 처음 생긴 날 시가로 잡은 값)예요' + (Math.abs(num(fsE.real)) >= 0.005 ? ' — 이 중 최초 인식 시가로 계산된 실현 ' + m(num(fsE.real), { sign: true }) : '') + ' · 설정 › 원가 계산에서 끌 수 있어요') + '">최초 인식 시가</span>' : '';
    const costCell = p.kind === 'gas' || p.kind === 'stake' ? '<div class="n num mut">—</div>' : p._noCost && !p._lp ? '<div class="n w">원가 미확인</div>' : '<div class="n num"' + covTip + '>' + m(KV(num(p.cost), cKrw(p, 'costKrw'))) + (fsChip ? '<div>' + fsChip + '</div>' : '') + '</div>'
      + (covTxt ? '<div class="cov"' + covTip + '><b><i style="width:' + Math.max(covP, 2).toFixed(0) + '%"></i></b>' + covTxt + '</div>' : '');
    const ceTip = '이 카드를 계산하다 예외를 건너뛴 자리가 있어요(' + p.calcErr + ') — 숫자가 실제와 조금 다를 수 있어요';
    const ceChip = p.calcErr ? ' <span class="kchip hi" title="' + esc(ceTip) + '">계산 오류</span>' : '';
    const oaChip = p.offcA ? '<span class="kchip pvx" data-pvt="1" title="' + esc('이 카드 매도 중 ' + q(num(p.offcA.qty)) + '개의 원가는 오프체인 이체를 내 다른 계정으로 가정해 이어받은 값이에요(설정·보낸 내역에서 끄거나 주소별로 뺄 수 있어요)') + '">오프체인 원가 이어받음 · 가정</span>' : '';
    const realCell = real ? '<div class="n num ' + clsV(realV) + '">' + m(realV, { sign: true }) + (oaChip ? '<div>' + oaChip + '</div>' : '') + '</div>' : (unvOnly ? '<div class="n w" title="원가를 모르는 수량의 매도 — 실현손익에서 빠짐 (정산 ' + esc(m(perOn ? ag.inUP : (ag.has ? ag.allUP : num(p.unvProceeds)))) + ')">원가 미확인 매도 ' + (unvN ? nf('ko-KR').format(unvN) + '회' : m(num(p.unvProceeds), { compact: true })) + '<br><span class="mut" style="font-weight:500">실현 제외</span></div>' : '<div class="n num mut">—</div>');
    const roiCell = (() => {
      if (p.kind === 'gas' || p.kind === 'stake' || p.kind === 'stable' || p.kind === 'quarantined') return '<div class="n num mut">—</div>';
      if (p._noCost && !p._lp) return '<div class="n"><span class="kchip">원가 미확인</span></div>';
      if (covTxt) return '<div class="n"' + covTip + '><span class="kchip">원가 대부분 미확인</span></div>';
      const c = num(p.cost);
      if (!(c > 0)) return '<div class="n num mut">—</div>';
      const tot = num(p.realized) + num(p.realizedFb) + (unr != null ? unr : 0), pct = tot / c * 100, apx = covP != null && covP < 99.5;
      return '<div class="n num ' + cls(pct) + '" title="사이클 수익률 = (누적 실현 ' + esc(m(num(p.realized) + num(p.realizedFb), { sign: true })) + (unr != null ? ' + 지금 평가손익 ' + esc(m(unr, { sign: true })) : '') + ') ÷ 원가 ' + esc(m(c)) + ' — 기간 필터와 무관' + (apx ? ' · 보유 일부 원가 미확인(원가 확인분 기준)' : '') + '">' + (apx ? '≈ ' : '') + pctS(pct, 1) + '</div>';
    })();
    const nw = p._now, nwAp = !!(nw && (nw.stale || nw.unpQ > 0));
    const nwTip = !nw ? (!done && num(p.held) > 0 && p.kind !== 'gas' && p.kind !== 'stable' ? '시세 없음 — 보유표도 평가 제외' : '')
      : p._lp ? 'LP 현재 가치(미청구 수수료 제외) — LP 표와 같은 값'
      : '남은 ' + q(num(p.held)) + ' ' + p.sym + ' × 현재가 — 보유표와 같은 평가' + (nw.stale ? ' · DEX 가격이 ' + ageTxt(nw.stale) + ' 값' : '') + (nw.unpQ > 0 ? ' · ' + q(nw.unpQ) + '개는 시세 없음(평가 제외)' : '');
    const nowCell = '<div class="n num' + (nw ? '' : ' mut') + '"' + (nwTip ? ' title="' + esc(nwTip) + '"' : '') + '>' + (nw ? (nwAp ? '≈ ' : '') + m(nw.v) : '—') + '</div>';
    const ln = cycLines(p, perOn, ag, done);
    const nm = p._lp ? lpNmHTML(String(lpNm(p.sym, p._lp.key)).replace(/\s*\/\s*/g, '/'), true) : esc(p.sym);
    const pillH = p._lp ? lpStatePill(p._lp) : statusPill(p), pillDup = !p._lp && plainT(pillH).trim() === String(p.sym).trim();
    const pillTip = pillDup ? (/title="([^"]*)"/.exec(pillH) || [])[1] || '' : '';
    return '<div class="card cyc' + (open ? ' open' : '') + '" data-anc="cycle:' + esc(p.key) + '"><div class="hd" role="button" tabindex="0" aria-expanded="' + open + '" data-a="jTog" data-k="' + esc(p.key) + '">'
      + '<div class="asset">' + (p._lp ? lpIcon(p._lp) : icon(p.sym, false, S.D.symLogo[String(p.sym).toUpperCase()] || {}))
      + '<div class="ell"><div class="sym ell' + (p._lp ? ' lpsym' : '') + '"' + (pillTip ? ' title="' + pillTip + '"' : '') + '>'
      + nm + impChip(p) + ceChip + (pillDup ? '' : ' ' + pillH) + '</div></div></div>'
      + '<div class="stepcol"><div class="rt ell' + (ln[0].indexOf('class="rtp"') >= 0 ? ' rtf' : '') + '" title="' + esc(plainT(ln[0])) + '">' + ln[0] + '</div><div class="mt" title="' + esc(plainT(ln[1])) + '">' + ln[1] + '</div></div>'
      + '<div class="kcol"><div class="k" title="' + (perOn ? '선택한 기간에 체결된 매도의 실현손익' : '사이클 시작부터 누적') + '">' + (perOn ? '기간 실현' : '실현') + '</div>' + realCell + '</div>'
      + '<div class="kcol"><div class="k">원가</div>' + costCell + '</div>'
      + '<div class="kcol"><div class="k">평가금액</div>' + nowCell + '</div>'
      + '<div class="kcol"><div class="k">평가손익</div>' + (unr != null && !unr && p._noCost ? '<div class="n w">원가 미확인</div>' : '<div class="n num ' + (unr == null ? 'mut' : cls(unr)) + '">' + (unr == null ? '—' : m(unr, { sign: true })) + '</div>' + (unkTxt ? '<div class="cov"' + unkTip + '>' + esc(unkTxt) + '</div>' : '')) + '</div>'
      + '<div class="kcol"><div class="k">수익률</div>' + roiCell + '</div>'
      + (() => { const showU = unr != null && !(perOn && (real || unvOnly)); return '<div class="mcol"><div class="n num ' + (showU ? cls(unr) : clsV(realV)) + '">' + (showU ? (!unr && p._noCost ? '<span class="mut">원가 미확인</span>' : m(unr, { sign: true, compact: true })) : (real ? m(realV, { sign: true, compact: true }) : (unvOnly ? '<span class="mut">원가 미확인</span>' : '—'))) + '</div><div class="k">' + (showU ? '평가손익' : (perOn ? '기간 실현' : '실현')) + (p._noCost || p.kind === 'gas' || p.kind === 'stake' ? '' : ' · 원가 ' + m(KV(num(p.cost), cKrw(p, 'costKrw')), { compact: true }) + (covTxt ? '<span' + covTip + '>(' + covTxt + ')</span>' : '')) + '</div>' + (nw ? '<div class="k"' + (nwTip ? ' title="' + esc(nwTip) + '"' : '') + '>평가금액 ' + (nwAp ? '≈ ' : '') + m(nw.v, { compact: true }) + '</div>' : '') + (showU && unkTxt && !covTxt ? '<div class="k"' + unkTip + '>' + esc(unkTxt) + '</div>' : '') + (fsChip ? '<div class="k">' + fsChip + '</div>' : '') + '</div>'; })()
      + '<div class="chev' + (open ? ' o' : '') + '">' + IC.chev + '</div></div>'
      + (open ? clps('j:' + p.key, p._lp ? '<div class="detail" style="display:block">' + lpDetail(p._lp) + '</div>' : cycDetail(p)) : '') + '</div>';
  }
  function routeBox(p) {
    if (p._lp || p.kind) return '';
    const legs = (arr(p._legP).length ? p._legP : [p]).slice();
    if (legs.length < 2 && !arr(p.movedTo).length && !arr(p.inFrom).length) return '';
    const unit = String(p.sym).length <= 8 ? ' ' + esc(p.sym) : '';
    const rows = legs.map(l => {
      const inQ = sum(arr(l.inFrom), x => num(x[1])), inC = sum(arr(l.inFrom), x => num(x[2]));
      const ownQ = Math.max(0, num(l.bought) - inQ), ownC = Math.max(0, num(l.cost) - inC), mv = mvDest(l);
      const inK = arr(l.inFrom).every(x => x[3] != null) ? sum(arr(l.inFrom), x => num(x[3])) : null;
      const ck = num(l.costKrw) > 0 && (inK != null || !arr(l.inFrom).length) && num(l.costKrw) - num(inK) > 0 ? num(l.costKrw) - num(inK) : null;
      const pill = mv ? '<span class="pill a sm">이동 → ' + esc(mv) + '</span>' : num(l.held) > 0 ? (num(l.soldQty) > 0 ? '<span class="pill w sm">부분 매도</span>' : '<span class="pill a sm">보유 중</span>') : '<span class="pill g sm">종료</span>';
      const ln = [];
      if (arr(l.inFrom).length) ln.push('받음 ' + q(inQ) + unit + ' ← ' + arr(l.inFrom).map(x => esc(x[0]) + ' ' + q(num(x[1]))).join(' · ') + (inC > 0 ? ' · 원가 승계 ' + m(KV(inC, inK)) : ''));
      if (ownQ > 0 && (num(l.nBuy) > 0 || ownC > 0)) ln.push((num(l.nBuy) > 0 ? '매수 ' + nf('ko-KR').format(num(l.nBuy)) + '건 · ' : '유입 · ') + q(ownQ) + unit + (ownC > 0 ? ' · ' + m(KV(ownC, ck)) : ''));
      else if (ownQ > 0) ln.push('원가 미확인 유입 ' + q(ownQ) + unit);
      arr(l.movedTo).forEach(x => ln.push('→ ' + (x[2] === false ? '<span class="wtxt">' + esc(x[0]) + '</span>' : esc(x[0])) + ' ' + q(num(x[1])) + unit));
      if (num(l.soldQty) > 0) ln.push('매도 ' + q(num(l.soldQty)) + unit);
      const nm = l.chain === '?' || !l.chain ? '거래소' : l.chain;
      return { ots: num(l._ots), mv: !!mv, held: num(l.held), html: '<div class="rleg"><div class="row gap8"><b>' + esc(nm) + '</b>' + pill + '<span class="sp"></span>' + (num(l.held) > 0 ? '<span class="num t2">보유 ' + q(num(l.held)) + '</span>' : '') + '</div>'
        + ln.map(t => '<div class="sub num">' + t + '</div>').join('') + '</div>' };
    }).sort((a, b) => (a.ots - b.ots) || ((b.mv ? 1 : 0) - (a.mv ? 1 : 0)) || (a.held - b.held));
    return '<div class="pbox route"><div class="ttl">경로 · 조각별 <span class="cap">산 곳 → 옮긴 곳 → 지금</span></div>' + rows.map(r => r.html).join('') + '</div>';
  }
  function cycDetail(p) {
    const D = S.D;
    const evsAll = arr(p.events).filter(e => srcPass(e) && gPass(e.t)).map(e => e.sym ? e : Object.assign({}, e, { sym: p.sym }));
    const cyK = 'cyev:' + p.key, cyP = uiPgSlice(cyK, evsAll.slice().reverse()), evs = cyP.rows;
    const rbK = p.kind ? Object.keys(p.realizedByDay || {}).filter(k => gPass(k)).sort((x, y) => isoDay(x) < isoDay(y) ? 1 : -1) : [];
    const rbRow = k => '<tr><td class="l mut num">' + esc(mdOf(k)) + '</td><td class="l">' + evPill(p.kind === 'gas' ? '가스 비용' : p.kind === 'stake' ? '스테이킹 보상' : '스테이블 매도') + '</td><td class="num">' + (p.kind === 'gas' ? num(arr(S.D.gasExp[isoDay(k)])[1]) + '건' : p.kind === 'stake' ? num((p.rwdByDay || {})[k]) + '건' : (num(arr((p.actByDay || {})[k])[1]) + num((p.payByDay || {})[k])) + '건') + '</td><td class="num ' + clsV(KV(num(p.realizedByDay[k]), (p.realizedKrwByDay || {})[k])) + '">' + m(KV(num(p.realizedByDay[k]), (p.realizedKrwByDay || {})[k]), { sign: true }) + '</td></tr>';
    const evHead = (cyP.last > 0 ? '<div class="upga" data-pga="' + esc(cyK) + '"></div>' : '') + '<div class="cyrh"><b>최근 기록</b><span class="cap num pvx">' + nf('ko-KR').format(evsAll.length) + '건</span><span class="sp"></span></div>';
    const evMoreBtn = uiPgBar(cyK, evsAll.length, { unit: '건' });
    const evHTML = !evsAll.length && rbK.length ? '<table class="ev"><thead><tr><th scope="col" class="l">날짜</th><th scope="col" class="l">종류</th><th scope="col">' + (p.kind === 'gas' ? '가스' : p.kind === 'stake' ? '보상' : '매도') + '</th><th scope="col">' + (p.kind === 'gas' ? '비용' : '실현') + '</th></tr></thead><tbody>'
        + uiPaged('cyr:' + p.key, rbK, rbRow, { tr: 4, unit: '일' }) + '</tbody></table>'
      : !evsAll.length ? '<div class="empty" style="padding:24px 0">' + (num(p.evN) > arr(p.events).length ? '최근 ' + arr(p.events).length + '건 중엔 이 기간·소스 이벤트가 없어요 · 전체 ' + num(p.evN) + '건은 일별 기록에서' : '이 기간·소스에 해당하는 이벤트가 없어요') + '</div>'
      : evHead
        + (cyP.p === cyP.last && num(p.evN) > arr(p.events).length ? '<div class="cap" style="margin:4px 0 8px">카드에는 최근 ' + arr(p.events).length + '건만 실려요 · 전체 ' + num(p.evN) + '건은 일별 기록에서 날짜별로</div>' : '')
        + (S.mobile ? '<div class="erows cyev">' + evs.map(e => '<div class="erow cr"><span class="ek">' + evPill(e.k) + '</span><span class="et num">' + esc(e.t) + '</span><span class="ea num">' + evA(e) + '</span>'
            + '<span class="ed ell">' + evDH(e) + ' · ' + esc(unitPx(e)) + '</span><span class="eq num">' + esc(evQ(e)) + '</span></div>').join('') + '</div>'
          : '<table class="ev"><thead><tr><th scope="col" class="l">시각</th><th scope="col" class="l">종류</th><th scope="col" class="l">내용</th><th scope="col">수량</th><th scope="col">단가</th><th scope="col">금액</th><th scope="col">참조</th></tr></thead><tbody>'
          + evs.map(e => '<tr><td class="l mut num nowrap">' + esc(e.t) + '</td><td class="l">' + evPill(e.k) + '</td><td class="l"><div class="ell" style="max-width:300px" title="' + esc(evDT(e)) + '">' + evDH(e) + '</div></td><td class="num nowrap">' + esc(evQ(e)) + '</td><td class="num nowrap t2">' + esc(unitPx(e)) + unitKrw(e) + '</td><td class="num nowrap">' + evA(e) + '</td><td class="tx num nowrap">' + (e.tx && e.tx !== '—' ? '<button data-a="copy" data-v="' + esc(e.tx) + '" title="복사 · ' + esc(e.tx) + '">' + esc(short(e.tx)) + '</button>' : '—') + '</td></tr>').join('') + '</tbody></table>')
        + evMoreBtn;
    const real = num(p.realized) + num(p.realizedFb);
    const fb = (num(p.unknownQty) > 0 ? '보유 중 원가 미확인 ' + q(num(p.unknownQty)) + ' ' + p.sym + (num(p.fbAvg) > 0 ? ' → 평균 매수가 ' + px(num(p.fbAvg)) + ' 적용 (원가 ' + m(num(p.fbCost)) + ')' : ' (평균가 없음 · 미확인 유지)') : '')
      + (num(p.unvQty) > 0 ? (num(p.unknownQty) > 0 ? ' · ' : '') + '원가 미확인 매도 ' + q(num(p.unvQty)) + ' ' + p.sym + ' 정산 ' + m(num(p.unvProceeds)) + (num(p.fbAvg) > 0 ? ' → 평균가 기준 손익 ' + m(num(p.realizedFb), { sign: true }) : ' (평균가 없음 · 손익 제외)') : '');
    const held = num(p.held) > 0, sold = num(p.soldQty) > 0;
    const realTxt = sold || Math.abs(real) >= 0.005 ? '<span class="' + clsV(KV(real, rKrw(p))) + '">' + mCellF(KV(real, rKrw(p)), { sign: true }) + '</span>' : '—';
    const six = '<div class="ucells cy6">'
      + uiCell('평균 매수가', px(num(p.avg)))
      + (held ? uiCell('보유', q(num(p.held))) + uiCell('현재가', px(p._price)) : uiCell('평균 매도가', sold && num(p.soldProceeds) > 0 ? px(num(p.avgSell)) : '—') + uiCell('총 매도', sold && num(p.soldProceeds) > 0 ? mCellF(KV(num(p.soldProceeds), cKrw(p, 'soldProceedsKrw'))) : '—'))
      + uiCell('원가', p._noCost ? '<span class="mut">원가 미확인</span>' : mCellF(KV(num(p.cost), cKrw(p, 'costKrw'))) + fsKchip(p.fsEst && p.fsEst.cost))
      + uiCell('가스·수수료', mCell(parseMoney(p.fee)))
      + uiCell('실현', realTxt + (p.fsEst && Math.abs(num(p.fsEst.real)) >= 0.005 && realTxt !== '—' ? '<span class="kchip pvx" data-pvt="1" title="' + esc('실현 중 ' + m(num(p.fsEst.real), { sign: true }) + '는 최초 인식 시가로 잡은 원가로 계산됐어요 · 설정 › 원가 계산에서 끌 수 있어요') + '">추정</span>' : ''),
        null, null, '실현 = 매도 − 원가' + (num(p.realizedFb) ? ' · 평균가 대체 ' + m(num(p.realizedFb), { sign: true }) + ' 포함' : '')) + '</div>';
    const xkv = (l, v, tip) => '<div class="kv"><span' + (tip ? ' title="' + esc(tip) + '"' : '') + '>' + l + '</span><b class="num">' + v + '</b></div>';
    const extra = xkv('총 매수', q(num(p.bought)) + ' ' + esc(p.sym))
      + (sold ? xkv('평균 매도가', num(p.soldProceeds) > 0 ? px(num(p.avgSell)) : '—') + xkv('총 매도', q(num(p.soldQty)) + ' · ' + (num(p.soldProceeds) > 0 ? m(KV(num(p.soldProceeds), cKrw(p, 'soldProceedsKrw'))) : '—')) : '')
      + (num(p.lpConvQty) > 0 ? xkv('LP 전환', q(num(p.lpConvQty))) : '')
      + (num(p.paidQty) > 0 ? xkv('스왑 지불', q(num(p.paidQty)) + ' · ' + m(num(p.paidUsd)), '다른 코인을 사며 대금으로 함께 나간 수량 — 처분이라 실현·양도차익 명세엔 들어가고, 매도 수량·평균 매도가에선 빠져요') : '')
      + xkv('실현 (매도 − 원가)', (sold || Math.abs(real) >= 0.005 ? '<span class="' + clsV(KV(real, rKrw(p))) + '">' + m(KV(real, rKrw(p)), { sign: true }) + '</span>' + (num(p.realizedFb) ? ' <span class="cap">(평균가 대체 ' + m(num(p.realizedFb), { sign: true }) + ')</span>' : '') : '—'))
      + (held ? xkv('보유 · 현재가', q(num(p.held)) + ' · ' + px(p._price)) : '')
      + (fb ? '<div class="fbnote">' + esc(fb) + '</div>' : '')
      + (S.cur !== 'USD' ? '<div class="cap" style="margin-top:6px">원화 = 체결 시각 환율(원화 마켓은 실제 체결 원화) · 단가는 달러</div>' : '');
    const extraF = uiFold('cyx:' + p.key, { mem: false, cls: 'plain cyx', head: '<span class="cap">세부 숫자 · 총 매수' + (sold ? '·매도' : '') + (num(p.paidQty) > 0 ? '·스왑 지불' : '') + (fb ? '·원가 미확인' : '') + '</span>', body: () => '<div class="cyxb">' + extra + '</div>' });
    const g = held && !p._lp ? D.groups.find(x => gMatch(x, p.sym, p.key)) : null;
    const cust = g && g.locList.length ? '<button type="button" class="cyst" data-a="uiGo" data-v="coin:' + esc(g.key) + '" title="대시보드 보유 목록에서 이 코인 보기"><span class="mut">보관처</span> <span class="ell num">' + g.locList.slice(0, 3).map(L => locH(L.w.replace(/ 지갑$/, '')) + ' ' + q(L.qty)).join(' · ') + (g.locList.length > 3 ? ' 외 ' + (g.locList.length - 3) + '곳' : '') + '</span>' + IC.right + '</button>' : '';
    const pl = D.plans[p.key], price = p._price, memo = (D.memos && D.memos[p.key]) || (pl && pl.memo) || '';
    const plTxt = pl ? '목표 ' + plPx(pl.target) + (price > 0 ? ' <span class="' + clsP((pl.target - price) / price * 100) + '">' + pctS((pl.target - price) / price * 100, 1) + '</span>' : '') + ' · 손절 ' + plPx(pl.stop) + (price > 0 ? ' <span class="' + clsP((pl.stop - price) / price * 100) + '">' + pctS((pl.stop - price) / price * 100, 1) + '</span>' : '') + (memo ? ' · 메모 있음' : '')
      : memo ? '메모 · ' + prTxt(memo) : '비어 있음 — 눌러서 적기';
    const planRow = '<button type="button" class="cypl" data-a="planSheet" data-k="' + esc(p.key) + '" aria-haspopup="dialog"><span class="tx"><b>목표가 · 손절 · 메모' + (pl ? ' <span class="pill ok sm">감시 중</span>' : '') + '</b><span class="cap ell num">' + plTxt + '</span></span>' + IC.right + '</button>';
    return '<div class="detail"><div class="cyevw" style="min-width:0">' + evHTML + '</div><div class="cyside">' + six + extraF + cust + planRow + routeBox(p) + saleBox(p) + xferBox(p) + '</div></div>';
  }
  UI_SHEETS.plan = key => {
    const D = S.D, p = D && (D.merged.find(x => x.key === key) || D.lpCycles.find(x => x.key === key));
    if (!p) return '<div class="cap">이 카드를 찾지 못했어요 — 새로 고친 뒤 다시 열어 주세요</div>';
    const pl = D.plans[key], price = p._price, k = esc(key);
    const planView = pl ? (() => {
      const span = pl.target - pl.stop, pos = span > 0 && price > 0 ? Math.max(2, Math.min(98, (price - pl.stop) / span * 100)) : 50;
      return '<div class="kv"><span>목표가</span><b class="num">' + plPx(pl.target) + ' <span class="' + (price > 0 ? clsP((pl.target - price) / price * 100) : 'mut') + '">' + (price > 0 ? pctS((pl.target - price) / price * 100, 1) : '') + '</span></b></div>'
        + '<div class="kv"><span>손절선</span><b class="num">' + plPx(pl.stop) + ' <span class="' + (price > 0 ? clsP((pl.stop - price) / price * 100) : 'mut') + '">' + (price > 0 ? pctS((pl.stop - price) / price * 100, 1) : '') + '</span></b></div>'
        + '<div class="tpbar"><i style="left:' + pos + '%"></i></div><div class="sub">' + esc(pl.src === 'DEX' ? 'DEX 가격 추적' : 'CEX 가격 추적') + ' · ' + esc(pl.venue || '감시 중') + (price > 0 ? ' · 현재 ' + pxC(price) : '') + '</div>'
        + (arr(pl.tags).length ? '<div class="chips" style="margin-top:8px;gap:6px">' + arr(pl.tags).map(t => '<span class="pill g sm">' + esc(t) + '</span>').join('') + '</div>' : '');
    })() : '<div class="sub">목표가·손절선을 둘 다 넣으면 1분 간격으로 감시하고, 닿으면 알림을 보내요.' + (price > 0 ? ' 현재 ' + pxC(price) : '') + '</div>';
    const live = plCY() ? plSnap(key).live : true, prt = plCY() ? plSnap(key).rt : rate();
    const cu = plCur(key), uL = cu === 'KRW' ? '₩' : '$', uN = cu === 'KRW' ? '원화' : 'USD';
    const curSeg = plCY() ? '<span class="sp"></span><span class="seg plcur" role="group" aria-label="입력 통화">' + [['KRW', '₩ 원화'], ['USD', '$ 달러']].map(o => '<button type="button" data-a="planCcy" data-k="' + k + '" data-v="' + o[0] + '" class="' + (cu === o[0] ? 'on' : '') + '" aria-pressed="' + (cu === o[0]) + '"' + (o[0] === 'KRW' && !live ? ' disabled title="지금 환율을 아직 못 받았어요"' : '') + '>' + o[1] + '</button>').join('') + '</span>' : '';
    const planBox = '<div class="pbox"><div class="ttl">목표가 · 손절선' + (pl ? ' <span class="pill ok sm">감시 중</span>' : '') + curSeg + '</div>' + planView
      + '<div class="frm"><input class="field num" data-pv="1" inputmode="decimal" placeholder="목표 ' + uL + '" data-draft="t:' + k + '" data-enter="savePlan" data-k="' + k + '" aria-label="목표가 (' + uN + ')"><input class="field num" data-pv="1" inputmode="decimal" placeholder="손절 ' + uL + '" data-draft="s:' + k + '" data-enter="savePlan" data-k="' + k + '" aria-label="손절선 (' + uN + ')"></div>'
      + '<div class="cap num plq" id="plQ">' + esc(plQ(key)) + '</div>'
      + (cu === 'KRW' && !pvOn() ? '<div class="cap">원화로 넣으면 지금 환율(₩' + nf('ko-KR', 0, 0).format(prt) + '/$)로 달러로 바꿔 저장해요 — 감시·알림은 달러 시세 기준</div>' : '')
      + (plCY() && !live ? '<div class="cap">지금 환율을 아직 못 받아 원화 입력은 잠시 막아 뒀어요 — 달러로 넣어 주세요</div>' : '')
      + '<div class="frm"><button class="btn sm pri" data-a="savePlan" data-k="' + k + '">저장</button>' + (pl ? '<button class="btn sm" data-a="clearPlan" data-k="' + k + '">해제</button>' : '') + '<span class="cap">0 &lt; 손절 &lt; 목표</span></div></div>';
    const memo = (D.memos && D.memos[key]) || (pl && pl.memo) || '';
    const memoBox = '<div class="pbox"><div class="ttl">메모</div>' + (memo ? '<div class="t2" style="font-size:14px;margin-bottom:6px;white-space:pre-wrap">' + prTxt(memo) + '</div>' : '')
      + '<div class="frm"><input class="field" data-pr="1" placeholder="진입 근거·계획" data-draft="m:' + k + '" data-enter="saveMemo" data-k="' + k + '" aria-label="메모"><button class="btn sm" data-a="saveMemo" data-k="' + k + '">저장</button></div></div>';
    return planBox + memoBox;
  }
  const isGasTax = r => String(r.ex || '') === '기타 비용(가스)';
  function taxDetailValues(r, c) {
    const acq = num(r.acq), disp = num(r.disp), fee = num(r.fee);
    const k9 = num(r.rate) > 0 ? num(r.rate) : null;
    let av = KV(acq, k9 ? (r.akr != null ? num(r.akr) : acq * k9) : null);
    let dv = KV(disp, k9 ? disp * k9 : null), fv = KV(fee, k9 ? fee * k9 : null);
    if (r.fut && S.cur !== 'USD') {
      av = c.acq ? acq * c.acqV / c.acq : 0;
      dv = c.disp ? disp * c.dispV / c.disp : 0;
      const cf = c.disp - c.acq - c.pnl;
      fv = cf ? fee * c.feeV / cf : 0;
    }
    return { acq: av, disp: dv, fee: fv, pnl: dv - av - fv };
  }
  const TAX_INC_EX = ['스테이킹 보상', '유동성 수수료', '유동성 리워드'];
  const taxKind = r => (r.fut || r.futFee) ? 'fut' : r.tk === 'st' ? 'st' : (r.tk === 'inc' || TAX_INC_EX.indexOf(String(r.ex || '')) >= 0) ? 'inc' : 'spot';
  const taxNs = kind => (kind === 'spot' ? '' : kind + ':');
  const taxEstEx = ex => (String(ex || '') === '평균가 폴백' ? 'fb' : /매수가=매도가$/.test(String(ex || '')) ? 'be' : /최초 인식 시가$/.test(String(ex || '')) ? 'fs' : '');
  const TAX_EST_TIP = { fb: '추정 — 원가를 모르는 수량의 원가를 이 코인 평균 매수가로 잡은 행이에요(평균가 폴백 설정)', be: '추정 — 원가를 모르는 수량을 매수가 = 매도가(손익 0)로 처리한 행이에요(손익 0 처리 설정)',
    fs: '추정 — 취득가액의 일부(1% 이상)가 최초 인식 시가(원가를 모르던 수량을 그 수량이 장부에 처음 생긴 날 시가로 잡은 값)예요(스테이블은 원화 취득가액을 그때 환율로) · 설정 › 원가 계산에서 끌 수 있어요' };
  const taxEstPill = k => (k ? ' <span class="pill w sm" title="' + esc(TAX_EST_TIP[k]) + '">추정</span>' : '');
  const kdHead = k => {
    if (!k || !k.on) return '';
    const n = v => nf('ko-KR').format(Math.round(num(v))), off = num(k.skip) + num(k.none);
    if (k.state === 'before' || !k.state) return '<br>한국 의제취득가액 켬 · 기준 ' + esc(String(k.at)) + ' 23:59 전이라 그때 시가가 정해지면 적용돼요';
    const amt = pvOn() ? '<span class="pv">' + PVM.krw + '</span>' : n(k.add);
    return '<br>한국 의제취득가액 켬 · 기준 ' + esc(String(k.at)) + ' 23:59 · 적용 ' + n(k.rows) + '행(<span class="pvm">+₩' + amt + '</span>)'
      + (num(k.wait) ? ' · 시가 대기 ' + n(k.wait) + '종' : '') + (off ? ' · 적용 안 함 ' + n(off) + '종' : '');
  };
  const kdRowTip = r => {
    const at = S.D.krDeemed && S.D.krDeemed.at, u = r.kdu != null ? ' ₩' + nf('ko-KR').format(Math.round(num(r.kdu))) + '/개' : '';
    return '의제취득가액 — 기준' + (at ? ' ' + at : '') + ' 23:59 시가' + u
      + '가 실제 산 가격보다 높아 이 행의 원화 취득가액에 그 차이를 더했어요 · 달러 손익·머리·달력 원화 실현은 그대로예요';
  };
  function taxGroups(kind) {
    kind = kind || 'spot';
    const D = S.D, ns = taxNs(kind);
    const rk = r => num(r.rate) > 0 ? num(r.rate) : null;
    const src = (D.taxFull ? D.taxSum.filter(r => ymPass(r.ym) && taxKind(r) === kind) : D.tax.filter(r => gPass(r.sold) && taxKind(r) === kind).map(r => ({ ym: ymOf(r.sold) || '기타', sym: r.sym, ex: r.ex, n: 1, qty: num(r.qty), acq: num(r.acq), disp: num(r.disp), fee: num(r.fee),
        pk: rk(r) ? (num(r.disp) - num(r.acq) - num(r.fee)) * rk(r) : null, ak: rk(r) ? num(r.acq) * rk(r) : null, dk: rk(r) ? num(r.disp) * rk(r) : null,
        ak2: rk(r) && r.akr != null ? num(r.akr) : null, pk2: rk(r) && r.akr != null ? (num(r.disp) - num(r.fee)) * rk(r) - num(r.akr) : null })))
      .map(r => Object.assign({}, r, { acqV: KV(r.acq, r.ak2 != null ? r.ak2 : r.ak), dispV: KV(r.disp, r.dk), pnlV: KV(r.disp - r.acq - r.fee, r.pk2 != null ? r.pk2 : r.pk),
        pnlV0: KV(r.disp - r.acq - r.fee, r.pk) }))
      .map(r => Object.assign(r, { feeV: r.dispV - r.acqV - r.pnlV }));
    const gm = {};
    src.forEach(r => { (gm[r.ym] || (gm[r.ym] = [])).push(r); });
    const yms = Object.keys(gm).sort().reverse();
    if (!S.taxOpen) { S.taxOpen = new Set(); if (kind === 'spot' && yms.length) S.taxOpen.add(yms[0]); }
    const detail = D.tax.filter(r => gPass(r.sold) && taxKind(r) === kind);
    return yms.map(ym => {
      const rs = gm[ym], bySym = {};
      rs.forEach(r => (bySym[r.sym] || (bySym[r.sym] = [])).push(r));
      const coins = Object.keys(bySym).map(sym => {
        const cr = bySym[sym], exs = [];
        cr.forEach(r => { if (exs.indexOf(r.ex) < 0) exs.push(r.ex); });
        const rows = detail.filter(r => r.sym === sym && (ymOf(r.sold) || '기타') === ym).sort((a, b) => isoDay(a.sold) < isoDay(b.sold) ? 1 : -1);
        return { sym, rows, n: sum(cr, r => r.n), exs, qty: sum(cr, r => r.qty), acq: sum(cr, r => r.acq), disp: sum(cr, r => r.disp), pnl: sum(cr, r => r.disp - r.acq - r.fee),
          acqV: sum(cr, r => r.acqV), dispV: sum(cr, r => r.dispV), pnlV: sum(cr, r => r.pnlV), feeV: sum(cr, r => r.feeV), ck: ns + ym + '|' + sym, gas: cr.every(r => isGasTax(r)), tx: sum(cr, r => num(r.tx)) };
      }).sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl));
      return { ym, key: ns + ym, coins, n: sum(rs, r => r.n), acq: sum(rs, r => r.acq), disp: sum(rs, r => r.disp), pnl: sum(rs, r => r.disp - r.acq - r.fee),
        acqV: sum(rs, r => r.acqV), dispV: sum(rs, r => r.dispV), pnlV: sum(rs, r => r.pnlV), feeV: sum(rs, r => r.feeV), pnlV0: sum(rs, r => r.pnlV0), akfb: sum(rs, r => num(r.akfb)),
        est: sum(rs, r => (taxEstEx(r.ex) ? r.n : 0)) };
    });
  }
  function taxLazy(ym, sym, have, need) {
    const D = S.D;
    if (!D.taxFull || have >= need || !/^\d{4}-\d{2}$/.test(String(ym))) return null;
    const C = S.taxLz || (S.taxLz = {}), k = ym + '|' + sym, c = C[k];
    if (c && (c.at === D.builtAt || c.st === 'load' || c.st === 'none')) return c.st === 'none' ? null : c;
    const nc = C[k] = { at: D.builtAt, st: 'load', rows: c && c.rows, total: c && c.total };
    fetch('/api/tax_rows?ym=' + encodeURIComponent(ym) + '&sym=' + encodeURIComponent(sym), { cache: 'no-store' }).then(r => {
      if (r.status === 401) { onUnauthorized(); return null; }
      if (r.status === 404) return { none: true };
      return r.ok ? r.json() : null;
    }).catch(() => null).then(j => {
      if (C[k] !== nc) return;
      if (j && j.none) nc.st = 'none';
      else if (j && j.ok) { nc.st = 'ok'; nc.rows = arr(j.rows); nc.total = num(j.total); }
      else nc.st = 'err';
      if (S.tab === 'journal' && S.j.view === 'tax') renderView();
    });
    return nc;
  }
  function taxUnv() {
    let n = 0, p = 0;
    arr(S.D.merged).forEach(c => { if (c._lp) return; const a = pAgg(c); n += S.g.period === 'all' ? a.allU : a.inU; p += S.g.period === 'all' ? a.allUP : a.inUP; });
    return { n, p };
  }
  const TAX_START = '2027-01-01';
  const taxStart = () => {
    const kd = S.D && S.D.krDeemed, at = kd && kd.on && isISO(kd.at) ? kd.at : null;
    if (!at) return TAX_START;
    const d = new Date(at + 'T00:00:00Z');
    d.setUTCDate(d.getUTCDate() + 1);
    return d.toISOString().slice(0, 10);
  };
  const taxStartTxt = () => { const ts = taxStart();
    return '가상자산 과세는 ' + ts.slice(0, 4) + '년 ' + (+ts.slice(5, 7)) + '월부터 '
      + (todayISO() < ts ? '시행 예정이고(일정은 법 개정으로 바뀔 수 있어요)' : '시행 중이고'); };
  const TAX_COST_TIP = '원가 방식: 이동평균(선입선출 아님)이에요. 체인 기본 코인(그 체인 공식 랩 토큰 WETH 등 포함)·정품 스테이블은 체인을 넘어 한 묶음, 그 밖 토큰은 컨트랙트마다, 거래소 보유는 거래소·코인마다 따로 평균을 내요(내 지갑·거래소 사이 이동은 출발지 원가를 그대로 들고 감). 팔 때 그때까지의 평균 매수가 × 판 수량이 취득가액이고, 원가를 아는 수량부터 떼요. 원가를 모르는 수량의 매도는 명세에서 빠지거나(원가 미확인) 설정에 따라 \'추정\' 행으로 들어가요. 원화 취득가액은 사들일 때 원화(원화 마켓은 낸 원화), 원화 양도가액은 판 때 원화예요. 기본공제 같은 세법 규칙은 반영하지 않았어요. 시행 전 보유분 취득가 특례(의제취득가액)는 설정 › 원가 계산 › 한국 의제취득가액으로 켤 수 있어요.';
  const TAX_ST_TIP = '스테이블(USDT·USDC 등)을 원화로 팔거나 다른 코인을 사는 대금으로 쓴 처분이에요. 원화 취득가액 = 사들일 때 원화(원화 마켓은 낸 원화 · 그 밖은 받은 때 원화 시가)의 이동평균, 처분가액 = 처분 때 원화 시가 — 그 차이가 원화 환차손익이에요(손실도 그대로). 스테이블로 산 코인의 원화 취득가 = 그때 낸 스테이블의 원화 시가라 이중으로 세지 않아요. 처분마다 양도 표에 넣으면 같은 돈이 양도가액(스테이블)·취득가액(산 코인)에 두 번 잡혀 합계가 부풀어서 따로 모았어요 — 손익은 위 양도차익(명세 기준)에 더해져 있어요. 매매일지·대시보드의 실현손익(매도 시각 환율 환산)에는 이 원화 환차가 들어가지 않아요(명세에만 · 매매일지 머리 아래 차이 줄에 따로 보여요).';
  const TAX_INC_TIP = '스테이킹 보상·유동성 수수료·리워드는 받은 때 시가가 소득이에요(양도가 아님). 그 시가가 그 코인의 원가가 돼서 나중에 팔면 그 위 차익만 양도 표에 들어가요. 세법상 어떻게 신고하는지는 세무 확인이 필요해요.';
  const TAX_FUT_TIP = '거래소 정산(실현 손익·수수료·펀딩) 기준이에요. 이익을 양도가액·손실을 취득가액에 넣으면 양쪽 합계가 부풀어서 양도 표와 따로 합계를 내요.';
  const taxTip = (t, lbl) => '<button type="button" class="tipb" data-a="tipShow" data-v="' + esc(t) + '" title="' + esc(t) + '" aria-label="' + esc(lbl) + '">' + IC.info + '</button>';
  function taxStFx() {
    const sf = S.D.taxStableFx; if (!sf) return null;
    const a = [0, 0, 0, 0, 0];
    Object.keys(sf).forEach(ym => { if (!ymPass(ym)) return; const v = arr(sf[ym]); for (let i = 0; i < 5; i++) a[i] += num(v[i]); });
    return a[0] ? { n: a[0], nk: a[1], fx: a[2], nKrw: a[3], fxKrw: a[4] } : null;
  }
  const STFX_ID = new WeakMap();
  let stfxN = 0;
  const stFxKey = r => { let k = STFX_ID.get(r); if (!k) { k = 'sx' + (++stfxN); STFX_ID.set(r, k); } return k; };
  function stFxReg(r) { (S.stfxReg || (S.stfxReg = {}))[stFxKey(r)] = r; }
  const stKw = (w, sg) => { if (w == null || !isFinite(w)) return '—'; const v = KS(w), s = sg ? (v >= 0.5 ? '+' : v <= -0.5 ? '−' : '') : (v <= -0.5 ? '−' : ''); return S.hide ? s + '₩' + pvW(PVM.krw) : s + '₩' + rw(nf('ko-KR').format(Math.round(Math.abs(v)))); };
  const stKr = x => (x == null || !isFinite(x) ? '—' : S.hide ? '₩' + pvW(PVM.px) : '₩' + rw(nf('ko-KR', 2, 2).format(num(x))));
  const stQ = n => (n == null || !isFinite(n) ? '—' : S.hide ? pvW(PVM.q) : rw(nf('ko-KR', 0, 2).format(Math.abs(KS(n)))));
  const r2 = x => Math.round(num(x) * 100) / 100;
  const ST_AVG_TIP = '평균 취득 환율 = 이 처분 때까지 산 이 스테이블(같은 코인 묶음)의 원화 원가를 이동평균한 값이에요. 특정 날 산 것을 고른 게 아니라, 남아 있던 전체의 평균에서 이 수량만큼 뗀 거예요. 거래소·지갑 사이 이동은 원가를 그대로 이어받아요.';
  UI_SHEETS.stfx = k => {
    const r = S.stfxOpen && S.stfxOpen.k === k ? S.stfxOpen.r : (S.stfxReg || {})[k];
    if (!r || !r.fx) return '<div class="cap">이 처분 행을 다시 찾지 못했어요 — 표를 다시 펼쳐 주세요</div>';
    const fx = r.fx, rt = num(r.rate), qty = num(r.qty), disp = num(r.disp), fee = num(r.fee);
    const pnlK = rt > 0 ? (r.akr != null ? disp * rt - num(r.akr) - fee * rt : (disp - num(r.acq) - fee) * rt) : null;
    const kq = fx.kq != null ? num(fx.kq) : null, hasA = fx.a != null && kq != null && kq > 0;
    const fxK = hasA && fx.d != null ? (r2(fx.d) - r2(fx.a)) * r2(kq) : null, feeK = fee * rt, mq = hasA ? Math.max(0, qty - kq) : qty;
    const rest = pnlK != null && fxK != null ? pnlK - fxK + feeK : null;
    const kv = (a, b, t) => '<div class="kv"><span>' + a + (t ? taxTip(t, a + ' 설명') : '') + '</span><b class="num">' + b + '</b></div>';
    const big = '<div class="stfxh"><span class="l">환차손익</span><b class="num ' + cls(pnlK) + '">' + stKw(pnlK, true) + '</b><span class="cap">' + esc((isoDay(r.sold) || r.sold) + ' · ' + term(r.ex)) + '</span></div>';
    const what = '<div class="blk"><div class="ttl">무엇에 썼나</div>' + kv('용도', esc(fx.u || '처분')) + kv('처분 수량', q(qty) + '개')
      + kv('처분 환율', stKr(fx.d)) + kv('처분가액', stKw(rt > 0 ? disp * rt : null)) + '</div>';
    const fsOn = !!(S.D.firstSeen && S.D.firstSeen.on);
    const noK = fsOn ? '<span title="이동 승계·그날 환율 기록 없음 등 — 액면 입금·기초 잔고는 최초 인식 시가가 켜져 있어 들어온 때 환율로 위 평균에 들어가요">원화 원가 기록도 들어온 때 환율도 없는 몫이라 처분 환율로 뒀어요(환차 0)</span>'
      : '<span title="액면 입금·기초 잔고·브릿지 도착 — 설정 › 원가 계산에서 최초 인식 시가를 켤 수 있어요">원화 원가 기록이 없는 몫이라 처분 환율로 뒀어요(환차 0) · 최초 인식 시가를 켜면 들어온 때 환율로</span>';
    const cost = '<div class="blk"><div class="ttl">언제 산 것인가</div>'
      + (hasA ? kv('평균 취득 환율', stKr(fx.a), ST_AVG_TIP) + kv('원화 기록 수량', q(kq) + '개') : '<div class="cap">' + noK + '</div>')
      + (hasA && mq > 1e-9 ? '<div class="cap" style="margin-top:4px">나머지 ' + q(mq) + '개는 ' + noK + '</div>' : '')
      + (arr(fx.l).length ? '<div class="stfxl"><div class="cap" style="margin:8px 0 4px">이 평균을 만든 주요 매수 — 산 날 · 출처 · 그때 환율 · 이 처분에 섞인 수량 · 비중(이동평균)</div>'
        + arr(fx.l).map(l => '<div class="stfxr"><span class="num pvx">' + esc(String(l[0] || '').slice(2).replace(/-/g, '.')) + '</span><span class="ell">' + esc(l[1] || '') + '</span><span class="num">' + stKr(l[3]) + '</span><span class="num">' + q(num(l[2])) + '개</span><span class="num pvx">' + nf('ko-KR', 0, 1).format(num(l[4])) + '%</span></div>').join('')
        + (num(fx.o) >= 0.5 ? '<div class="cap" style="margin-top:4px">그 밖 <span class="pvx">' + nf('ko-KR', 0, 1).format(num(fx.o)) + '%</span> = 작은 매수들·이동해 온 몫 중 세부를 안 실은 것</div>' : '') + '</div>' : '')
      + '</div>';
    const fml = '<div class="blk"><div class="ttl">계산</div>'
      + (fxK != null ? '<div class="stfxf num">(' + stKr(r2(fx.d)) + ' − ' + stKr(r2(fx.a)) + ') × ' + stQ(r2(kq)) + '개 = <b class="' + cls(fxK) + '">' + stKw(fxK, true) + '</b></div>' : '')
      + (feeK >= 0.5 ? '<div class="stfxf num">− 수수료 ' + stKw(feeK) + '</div>' : '')
      + (rest != null && Math.abs(rest) >= 1 ? '<div class="stfxf num">' + (rest > 0 ? '+ ' : '− ') + (mq > 1e-9 ? '그 밖(원화 기록 없는 몫·시세 차·반올림) ' : '그 밖(시세 차·반올림) ') + stKw(Math.abs(rest)) + '</div>' : '')
      + '<div class="stfxf num">= 환차손익 <b class="' + cls(pnlK) + '">' + stKw(pnlK, true) + '</b></div>'
      + '<div class="cap" style="margin-top:6px">처분 환율 = 처분가액 ÷ 수량(그때 원화 시세) · 평균 취득 환율 = 사들일 때 원화(원화 마켓은 낸 원화)의 이동평균</div></div>';
    return big + what + cost + fml;
  };
  const wbrN = h => (S.mobile && !S.hide && !S.rand ? String(h).split(/(<[^>]*>)/).map((p, i) => (i % 2 ? p : p.replace(/,(?=\d)/g, ',<wbr>'))).join('') : h);
  function taxTableHTML(kind, groups, o) {
    const D = S.D;
    const tc = op => '<svg class="tc' + (op ? ' o' : '') + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>';
    const r6 = (a, b, c, d, e, f2, extra, attrs) => '<div class="tax-r ' + extra + '"' + (attrs || '') + '><span class="ell">' + a + '</span><span class="hm">' + b + '</span><span class="hm">' + c + '</span><span class="hm">' + d + '</span><span>' + wbrN(e) + '</span><span>' + wbrN(f2) + '</span></div>';
    const unit = kind === 'inc' || kind === 'fut' ? '건' : '행', cols = o.cols;
    return '<div class="card' + (kind === 'spot' ? '' : ' taxx') + '"><div class="tblhead"><h2 class="h2">' + esc(o.title) + '</h2><span class="cap">' + o.cap + '</span></div>'
      + r6(cols[0], cols[1], cols[2], cols[3], cols[4], cols[5], 'h')
      + groups.map(g => {
        const open = S.taxOpen.has(g.key);
        const ym9 = String(g.ym == null ? '' : g.ym), lbl = esc(ym9 === '기타' || !/^\d{4}-\d{2}$/.test(ym9) ? (ym9 || '기타') : ym9.slice(0, 4) + '년 ' + (+ym9.slice(5)) + '월');
        return '<div class="tax-g">' + r6(tc(open) + lbl, nf('ko-KR').format(g.n) + unit, '', m(g.acqV), m(g.dispV), '<b class="' + cls(g.pnlV) + '">' + m(g.pnlV, { sign: true }) + '</b>', 'm', ' role="button" tabindex="0" aria-expanded="' + open + '" data-a="taxTog" data-v="' + esc(g.key) + '"')
          + (open ? clps('tax:' + g.key, g.coins.filter(c => c.gas || !(isZ(c.acqV) && isZ(c.dispV) && isZ(c.pnlV))).map(c => {
            const co = S.taxCoinOpen.has(c.ck);
            const lz = co ? taxLazy(g.ym, c.sym, c.rows.length, c.sym === '선물 수수료·펀딩' ? Infinity : c.n) : null;
            const lzR = lz && lz.rows ? lz.rows.filter(r => gPass(r.sold) && taxKind(r) === kind) : null;
            const dRows0 = lzR && (lzR.length || !c.rows.length) ? lzR : c.rows;
            const allFees = c.sym === '선물 수수료·펀딩' && lz && lz.st === 'ok'
              && lz.total === arr(lz.rows).length && dRows0.length === arr(lz.rows).length;
            const feeGap = allFees ? c.disp - c.acq - c.pnl - sum(dRows0, r => num(r.fee)) : 0;
            const dRows = Math.abs(feeGap) > 1e-8 ? dRows0.concat([{ sold: g.ym + '-01', sym: c.sym,
              ex: '월 합계 반올림 보정', qty: 0, acq: 0, disp: 0, fee: feeGap, fut: true, futFee: true }]) : dRows0;
            const lzNote = !lz ? '' : lz.st === 'load' && !lz.rows ? '<div class="tax-r d"><span class="mut">체결 상세 불러오는 중…</span></div>'
              : lz.st === 'err' ? '<div class="tax-r d"><span class="mut">체결 상세를 못 불러왔어요' + (lz.rows ? '' : ' — 합계에는 포함돼 있어요') + ' <button class="link" data-a="taxLzRetry" data-v="' + esc(g.ym + '|' + c.sym) + '">다시 시도</button></span></div>'
              : lz.st === 'ok' && lz.total > arr(lz.rows).length ? '<div class="tax-r d"><span class="mut num">최근 ' + nf('ko-KR').format(arr(lz.rows).length) + ' / ' + nf('ko-KR').format(lz.total) + '건만 표시 — 나머지는 합계에 포함</span></div>'
              : lz.st === 'ok' && !(lzR || []).length && !c.rows.length ? '<div class="tax-r d"><span class="mut">이 달 체결 상세를 찾지 못했어요 — 합계에는 포함돼 있어요</span></div>' : '';
            return r6(tc(co) + (c.gas ? '<b>가스 비용</b>' : taxNmHTML(lpNm(c.sym))) + ' ' + (c.gas ? '<span class="pill g sm" title="매매 외 가스(실패·승인·전송·브릿지·LP) — 그날 실현에서 뺀 비용(수수료 열)">기타 비용</span>' : c.exs.slice(0, 3).map(x => { const ek = taxEstEx(x); return '<span class="pill ' + (ek ? 'w' : String(x).indexOf('온체인') >= 0 ? 'a' : 'g') + ' sm"' + (ek ? ' title="' + esc(TAX_EST_TIP[ek]) + '"' : '') + '>' + esc(term(x)) + '</span>'; }).join(' ')), c.gas && c.tx > 0 ? nf('ko-KR').format(c.tx) + '건' : c.n ? nf('ko-KR').format(c.n) + unit : '—', c.qty ? q(c.qty) : '—', c.gas ? '—' : m(c.acqV), c.gas ? '—' : m(c.dispV), '<span class="' + cls(c.pnlV) + '">' + m(c.pnlV, { sign: true }) + '</span>', 'c', ' role="button" tabindex="0" aria-expanded="' + co + '" data-a="taxCoin" data-v="' + esc(c.ck) + '"')
              + (co ? lzNote + (dRows.length ? uiPaged('taxd:' + c.ck, dRows, r => { const v9 = taxDetailValues(r, c), pp = v9.pnl; const gr = isGasTax(r); const ff = !!r.futFee; const sk9 = kind === 'st' && r.fx ? stFxKey(r) : ''; if (sk9) stFxReg(r); return r6(esc((isoDay(r.sold) || r.sold) + (r.t ? ' ' + r.t : '') + ' · ' + (gr ? '가스 비용' : term(r.ex)) + (num(r.n) > 1 ? ' · ' + nf('ko-KR').format(num(r.n)) + '건 묶음' : '') + (r.fut && r.ticker ? ' · ' + String(r.ticker).replace(/ · 선물$/, '') : '') + (sk9 && r.fx.u ? ' · ' + r.fx.u : '')) + (gr ? '' : taxEstPill(r.be ? 'be' : taxEstEx(r.ex))) + (num(r.kd) > 0 && !gr ? ' <span class="pill w sm">의제</span>' + taxTip(kdRowTip(r), '의제취득가액 설명') : '') + (r.oa != null && !gr ? ' <span class="pill g sm pvx" data-pvt="1" title="' + esc('이 매도의 취득원가 중 ' + q(num(r.oa)) + '개 몫은 오프체인 이체를 내 다른 계정으로 가정해 이어받은 값이에요(설정·보낸 내역에서 끄거나 주소별로 뺄 수 있어요)') + '">오프체인 원가 · 가정</span>' : ''), '', num(r.qty) ? q(num(r.qty)) : '—', gr || ff ? '—' : m(v9.acq), gr || ff ? '—' : m(v9.disp), '<span class="' + cls(pp) + '"' + (num(r.fee) > 0 && !gr ? ' title="수수료 ' + esc(m(v9.fee)) + ' 차감"' : '') + '>' + m(pp, { sign: true }) + '</span>' + (sk9 ? IC.right.replace('<svg', '<svg class="stfxi" aria-hidden="true"') : ''), 'd' + (sk9 ? ' stfx' : ''),
                sk9 ? ' role="button" tabindex="0" data-a="stFx" data-v="' + esc(sk9) + '" title="누르면 이 처분의 환차 상세(언제 산 평균 환율 · 처분 환율 · 용도 · 식)"' : ''); }, { unit: '행' })
                : (lz && lz.st !== 'none' ? '' : '<div class="tax-r d"><span class="mut">체결 상세는 최근 100건만 받아요 — 이 종목의 이 달 체결은 합계에만 포함돼 있어요</span></div>')) : '');
          }).join('')) : '') + '</div>';
      }).join('') + '</div>';
  }
  function taxHTML() {
    const D = S.D;
    S.stfxReg = {};
    const groups = taxGroups('spot'), gSt = taxGroups('st'), gInc = taxGroups('inc'), gFut = taxGroups('fut');
    const tot = gs => ({ n: sum(gs, g => g.n), acq: sum(gs, g => g.acqV), disp: sum(gs, g => g.dispV), pnl: sum(gs, g => g.pnlV), fee: sum(gs, g => g.feeV), pnl0: sum(gs, g => g.pnlV0),
      feeU: sum(gs, g => g.disp - g.acq - g.pnl), est: sum(gs, g => g.est) });
    const T = tot(groups), TS = tot(gSt), TI = tot(gInc), TF = tot(gFut);
    const n = T.n, acq = T.acq, disp = T.disp, fee = T.fee, pnl = T.pnl + TS.pnl;
    const fxGap = (T.pnl - T.pnl0) + (TS.pnl - TS.pnl0);
    const gasFee = sum(groups, g => sum(g.coins.filter(c => c.gas), c => c.feeV));
    const tg = D.taxGas, gOn = !tg || tg.on !== false;
    const scope = D.taxFull ? esc(periodName()) : '최근 ' + D.tax.length + '건 기준 <span class="pill w sm">일부</span>';
    const unv = taxUnv();
    const sfx = taxStFx();
    const feeNote = gOn && tg && typeof tg.exFee === 'number' ? (S.g.period === 'all' && D.taxFull ? (() => { const panel = num(tg.total) + num(tg.exFee) + num(tg.wdFee), feeU = T.feeU + TS.feeU;
          return ' 가스·수수료 탭 전체 ' + m(panel) + ' 중 나머지 ' + m(panel - feeU) + '은 매수 쪽(매수 가스 ' + m(num(tg.inCost)) + ' + 매수 체결 수수료)이라 취득가액에 들어 있어요' + (S.cur !== 'USD' ? '(달러 기준 차를 지금 환율로 — 위 수수료 칸은 체결 시각 환율이라 원화로 빼면 환율 차만큼 달라요)' : '') + '.'; })()
          : ' 매수 쪽 가스·체결 수수료는 취득가액에 들어 있어요(전체 기간을 고르면 가스·수수료 탭 전체와 금액으로 비교해 보여요).') : '';
    const head = '<div class="disc">참고용 집계예요 — ' + taxStartTxt() + ', 실제 신고는 거래소 공식 내역과 세무 기준을 따르세요.<br>' + esc(KRW_BASIS) + ' · 원가 = 코인 묶음별 이동평균(선입선출 아님)' + taxTip(TAX_COST_TIP, '원가 방식 설명') + kdHead(D.krDeemed) + '</div>'
      + '<div class="sum4' + (TS.n ? ' s5' : '') + '"><div class="card"><div class="l">양도가액</div><div class="v num">' + m(disp, { compact: S.mobile }) + '</div><div class="cap">매도 정산액(수수료 전)' + (TS.n ? ' · 스테이블 처분 제외' : '') + '</div></div>'
      + '<div class="card"><div class="l">취득가액</div><div class="v num">' + m(acq, { compact: S.mobile }) + '</div><div class="cap">' + (gOn ? '매수 원가 + 매수 스왑 가스·체결 수수료' : '매수 원가 + 체결 수수료(가스 제외)') + '</div></div>'
      + '<div class="card" title="가스·수수료 탭 전체 중 매도 쪽 가스·체결 수수료와 매매 외 가스(기타 비용)만 — 매수 쪽은 취득가액에 들어 있어요"><div class="l">수수료·비용</div><div class="v num">' + m(fee, { compact: S.mobile }) + '</div><div class="cap">' + (gOn ? '매도 가스·체결 수수료' + (Math.abs(gasFee) >= 0.005 ? ' + 기타 비용(가스) ' + m(gasFee, { compact: true }) : '') : '매도 체결 수수료')
        + '</div></div>'
      + (TS.n ? '<div class="card"><div class="l">스테이블 환차손익</div><div class="v num ' + cls(TS.pnl) + '">' + m(TS.pnl, { sign: true, compact: S.mobile }) + '</div><div class="cap">USDT·USDC 등 처분 ' + nf('ko-KR').format(TS.n) + '행 · 수수료 차감 · 아래 표</div></div>' : '')
      + '<div class="card' + (TS.n ? ' jwide' : '') + '"><div class="l">양도차익(명세 기준)</div><div class="v num ' + cls(pnl) + '">' + m(pnl, { sign: true, compact: S.mobile }) + '</div><div class="cap num sans"><span class="nw">양도 − 취득 − 수수료' + (TS.n ? ' + 스테이블 환차손익' : '') + ' ·</span> <span class="nw" title="원가가 붙은 매도(부분 체결·스왑 레그·LP)를 한 행씩 센 수 — 수수료로 쓴 코인은 하루·코인마다 한 행 · 매매일지 매도 체결 횟수·그날 기록 매도 건수와 단위가 달라요">명세 ' + nf('ko-KR').format(n) + '행</span>'
        + (T.est ? ' <span class="nw" title="원가를 모르는 수량의 원가를 처음 장부에 생긴 날 시가로 잡거나(최초 인식 시가) 평균 매수가로 잡거나(평균가 폴백) 매수가 = 매도가로 처리한 행 — 표에 \'추정\' 표시">· 추정 ' + nf('ko-KR').format(T.est) + '행 포함</span>' : '') + ' <span class="nw">· ' + scope + '</span></div></div></div>'
      + (tg ? '<div style="margin:-6px 2px 14px">' + (S.cur !== 'USD' && Math.abs(fxGap) >= 0.5 ? '<div class="cap">원화 실현이 매매일지·대시보드와 <b class="num">' + m(fxGap, { sign: true }) + '</b> 달라요 — 원가 환율 기준이 달라서</div>' : '')
        + uiFold('taxrule', { cls: 'plain', head: '<span class="cap">계산 규약 · 가스 · 매수 수수료 · 원화 환율</span>', label: '세금 명세 계산 규약',
          body: () => '<div class="cap" style="line-height:1.6;padding:0 2px 6px">' + esc(gasRuleTxt(tg)) + '.' + (feeNote ? '<br>' + feeNote.trim() : '') + '<br>원화 양도가액·수수료는 체결(정산) 시각 환율, 원화 취득가액은 취득 시점 환율(사이클 매수 원가의 원화 기록 · 스테이블 포함)이에요.'
            + (S.cur !== 'USD' && Math.abs(fxGap) >= 0.5 ? '<br>매매일지·대시보드는 매도 시각 환율로 환산 · 원화 마켓 매수분만 실지불 원화예요.' : '') + '</div>' }) + '</div>' : '')
      + (TI.n || TF.n ? '<div class="cap num" style="margin:-8px 2px 14px">양도차익 ' + mN(pnl, { sign: true, compact: S.mobile }) + (TI.n ? ' · 기타 소득 ' + mN(TI.pnl, { sign: true, compact: S.mobile }) : '') + (TF.n ? ' · 선물 손익 ' + mN(TF.pnl, { sign: true, compact: S.mobile }) : '')
        + ' — 모두 더하면 ' + mN(pnl + TI.pnl + TF.pnl, { sign: true, compact: S.mobile }) + '(매매일지 실현손익과 같은 셈' + (S.cur !== 'USD' ? ' · 원화는 위 환율 기준 차만큼 달라요' : '') + ')</div>' : '')
      + (unv.n ? '<div class="cap num sans" style="margin:-8px 2px 14px"><span title="회 = 매도 체결 횟수(매매일지 머리와 같은 단위) — 미매칭 목록은 같은 체결을 코인별 1행으로 묶어 세요">원가 미확인 매도 ' + nf('ko-KR').format(unv.n) + '회</span> ' + mN(unv.p, { compact: S.mobile }) + '은 명세에서 빠져 있어요</div>' : '');
    if (!groups.length && !gSt.length && !gInc.length && !gFut.length) return head + '<div class="card empty"><b>' + esc(periodName()) + ' 확정된 실현손익이 없어요</b>기간을 넓히면 이전 매도 건이 보여요</div>';
    const futCap = D.taxFull && num(D.fut.realizedRowsTotal) > arr(D.fut.realizedRows).length ? ' · 체결 상세는 최근 ' + arr(D.fut.realizedRows).length + '건' : '';
    const stCap = 'USDT·USDC 등 처분 — 위 양도차익(명세 기준)에 포함' + (S.cur !== 'USD' ? ' · 원화 환차는 매매일지 실현손익엔 안 들어가요' : '') + (sfx && S.cur !== 'USD' ? ' · 원화 환차 ' + m(sfx.fx / rate(), { sign: true, compact: S.mobile }) + ' = 원화 매도 ' + m(sfx.fxKrw / rate(), { sign: true, compact: true }) + ' + 코인 매수 대금 등 ' + m((sfx.fx - sfx.fxKrw) / rate(), { sign: true, compact: true })
      + (sfx.n > sfx.nk ? ' · 원화 원가 기록이 없어 처분 때 환율로 둔 ' + nf('ko-KR').format(sfx.n - sfx.nk) + '행' : '') : '') + taxTip(TAX_ST_TIP, '스테이블 환차손익 설명');
    return head + (groups.length ? taxTableHTML('spot', groups, { title: '양도차익 명세', cap: '월 → 종목 → 체결 · 가상자산 양도(스테이블 처분·기타 소득·선물은 아래 따로)', cols: ['월 · 종목', '명세 행', '수량', '취득가액', '양도가액', '손익(수수료 차감)'] }) : '')
      + (gSt.length ? taxTableHTML('st', gSt, { title: '스테이블 환차손익', cap: stCap, cols: ['월 · 종목', '처분 행', '수량', '취득가액', '처분가액', '환차손익(수수료 차감)'] }) : '')
      + (gInc.length ? taxTableHTML('inc', gInc, { title: '기타 소득', cap: '스테이킹 보상·유동성 수수료 — 받은 때 시가 · 양도 합계와 따로' + taxTip(TAX_INC_TIP, '기타 소득 설명'), cols: ['월 · 종목', '건수', '수량', '차감', '받은 때 시가', '소득'] }) : '')
      + (gFut.length ? taxTableHTML('fut', gFut, { title: '선물 손익', cap: '거래소 정산 기준 · 양도 합계와 따로' + futCap + taxTip(TAX_FUT_TIP, '선물 손익 설명'), cols: ['월 · 종목', '건수', '수량', '손실', '이익', '손익'] }) : '');
  }
  function gasHTML(gas) {
    const mx = gas.reduce((a, g) => Math.max(a, g.spot + g.lp), 0);
    const tot = sum(gas, g => g.spot + g.lp);
    if (!gas.length) return '<div class="card empty"><b>' + esc(gasScope()) + ' 가스 기록이 없어요</b>기간을 넓혀 보세요</div>';
    const tg = S.D.taxGas;
    const rule = tg ? '<div class="cap" style="padding:0 24px 12px;line-height:1.55">' + esc(gasRuleTxt(tg)) + (tg.on !== false ? '.<br>전체 누적: 취득 원가 ' + m(num(tg.inCost)) + ' · 매도 실현 차감 ' + m(num(tg.inRealized)) + ' · 그날 가스 비용 ' + m(num(tg.expense)) + (Math.abs(num(tg.separate) - num(tg.expense)) >= 0.5 ? ' · 시가 미상 ' + m(num(tg.separate) - num(tg.expense)) : '') : '') + (num(tg.exFee) > 0 ? '.<br>거래소 체결 수수료 ' + m(num(tg.exFee)) + '는 그 체결의 원가·매도 실현에 이미 반영돼 있어요(업비트는 체결 원화에서 차감)' : '') + '</div>'
      + (S.cur !== 'USD' ? '<div class="cap mut" style="padding:0 24px 12px;margin-top:-6px">원화는 지금 환율로 환산했어요 — 사이클 카드·양도차익 명세의 \'가스 비용\'은 그날 환율 원화라 조금 달라요</div>' : '') : '';
    const ruleF = rule ? '<div class="gasrf">' + uiFold('gasrule', { cls: 'plain', head: '<span class="cap">계산 규약 · 전체 누적(취득 원가 · 매도 차감 · 그날 비용)</span>', body: () => rule, label: '가스 계산 규약·전체 누적' }) + '</div>' : '';
    return '<div class="card"><div class="tblhead"><h2 class="h2">가스·수수료</h2><span class="cap">' + esc(gasScope()) + ' · 체인·거래소별</span><div class="sp"></div><b class="num">' + m(tot) + '</b><span class="cap num">' + nf('ko-KR').format(sum(gas, g => g.tx)) + '건</span></div>' + ruleF
      + gas.map(g => { const v = g.spot + g.lp, z = isZ(v);
        const cb9 = g.kind === 'exfee' ? '' : chainBadge(g.chain).replace('class="cb"', 'class="cb gcb"');
        return '<div class="gas-r"><span class="row gap8">' + (g.kind === 'exfee' ? venueLogo(g.chain) : '<span class="ic xs gph" aria-hidden="true">' + esc(String(g.chain === '?' ? '?' : g.chain).slice(0, 1).toUpperCase()) + cb9 + '</span>') + '<b>' + esc(g.chain === '?' ? '미분류' : g.chain) + '</b></span><span class="hm">' + (z ? '' : '<div class="mini" style="margin:0"><i style="width:' + (mx > 0 ? Math.max(1, v / mx * 100) : 0).toFixed(1) + '%;background:var(--warn)"></i></div>') + '</span><span class="mut">' + nf('ko-KR').format(g.tx) + '건</span><span><b>' + m(v) + '</b></span></div>'; }).join('') + '</div>';
  }
  function kw(w, o) {
    o = o || {};
    w = KS(num(w));
    const a = Math.abs(w), s = o.sign ? (a < 0.5 ? '' : w > 0 ? '+' : '−') : (w < 0 && a >= 0.5 ? '−' : '');
    if (S.hide || S.rand) return s + '₩' + pvW(o.compact ? PVM.krwC : PVM.krw);
    return s + '₩' + rw(o.compact ? eok(a) : nf('ko-KR').format(Math.round(a)));
  }
  const kwFee = w => (S.rand ? '₩' + pvW(PVM.krw) : kw(w));
  const krwDir = r => r.src === 'int' ? (r.note || '거래소 내부 지급') + ' · ' + r.ex : r.dir === 'in' ? '원화 입금 · 은행 → ' + r.ex : '원화 출금 · ' + r.ex + ' → 은행';
  function krwAgg(rows) {
    const a = { in: 0, out: 0, fee: 0, intIn: 0, n: 0, nIn: 0, nOut: 0, fail: 0, wait: 0 };
    rows.forEach(r => {
      if (r.st !== 'done') { a[r.st === 'fail' ? 'fail' : 'wait']++; return; }
      a.n++;
      if (r.src === 'int') a.intIn += num(r.amt);
      else if (r.dir === 'in') { a.in += num(r.amt); a.nIn++; }
      else { a.out += num(r.amt); a.fee += num(r.fee); a.nOut++; }
    });
    a.net = a.in - a.out;
    return a;
  }
  const krwSel = () => arr(S.D.krw && S.D.krw.rows).filter(r => gPass(String(r.d || '').slice(0, 10)));
  function krwCovNote() {
    const cv = (S.D.krw && S.D.krw.cov) || {}, b = cv.bithumb, u = cv.upbit, out = [];
    if (u && !u.on) out.push('업비트는 아직 연결 전이에요');
    if (b && b.on && !num(b.n)) out.push('빗썸 원화 입출금은 아직 수집하지 못해요(빗썸은 원화 내역을 별도 목록으로 줘서 수집기에 추가가 필요해요) — 지금 보이는 건 업비트뿐이에요');
    return out.join(' · ');
  }
  function krwHTML() {
    const D = S.D, K = D.krw, T = K.total || {};
    const rows = krwSel(), A = krwAgg(rows), cmp = S.mobile;
    const cov = krwCovNote();
    const kOpen = uiOpen('krwsum', false);
    const allTxt = S.g.period !== 'all' && T.first ? '전체 기간(' + esc(T.first) + ' 부터) 넣은 원화 <b>' + kw(T.in) + '</b> · 뺀 원화 <b>' + kw(T.out) + '</b> · 순투입 <b>' + kw(T.net, { sign: true }) + '</b>' : '';
    const head = '<div class="card ofs1 krws1"><div class="ucells krwcells">'
      + uiCell('넣은 원화', mCell(A.in, null, kw)) + uiCell('뺀 원화', mCell(A.out, null, kw)) + uiCell('순투입', mCell(A.net, { sign: true }, kw)) + uiCell('거래소 내부 지급', mCell(A.intIn, null, kw)) + '</div>'
      + '<div class="jscap"><span class="cap">매매 손익 아님 · 완료만 합 · 원화 그대로(환율 환산 없음)</span><button type="button" class="link jsmore" data-a="uiFold" data-v="krwsum" aria-expanded="' + kOpen + '">' + (kOpen ? '접기' : '자세히') + UI_CHEV + '</button></div>'
      + (cov ? '<div class="cap wtxt krwcov">' + esc(cov) + '</div>' : '')
      + (kOpen ? clps('uf:krwsum', '<div class="jsdl">' + [['넣은 원화', '은행 → 거래소 · ' + A.nIn + '건'], ['뺀 원화', '거래소 → 은행 · ' + A.nOut + '건' + (A.fee ? ' · 출금 수수료 ' + kwFee(A.fee) + ' 별도' : '')],
          ['순투입', '넣은 원화 − 뺀 원화 · + 면 더 넣었고 − 면 더 뺐어요'], ['내부 지급', '예치금 이용료 등 · 은행 돈이 아니라 순투입에서 빼요']].concat(allTxt ? [['전체 기간', allTxt]] : []).map(x => '<div class="jsr"><span class="k">' + x[0] + '</span><span class="v num">' + x[1] + '</span></div>').join('')
        + '<div class="cap krwdisc">원화 입출금은 매매 손익이 아니에요 — 쓰려고 뺀 돈·새로 넣은 돈이에요. 실현손익·시장 변동에는 들어가지 않고, 총자산 변동에서는 \'입출금\'으로 따로 빼요.</div></div>') : '') + '</div>';
    if (!rows.length) return '<div class="krwv">' + head + '<div class="card empty"><b>' + esc(periodName()) + ' 원화 입출금이 없어요</b>기간을 넓히면 이전 기록이 보여요</div></div>';
    const gm = {};
    rows.forEach(r => { const ym = String(r.d).slice(0, 7); (gm[ym] || (gm[ym] = [])).push(r); });
    const yms = Object.keys(gm).sort().reverse();
    if (!S.krwOpen) { S.krwOpen = new Set(); S.krwOpen.add(yms[0]); }
    const tc = o => '<svg class="tc' + (o ? ' o' : '') + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>';
    const r5 = (a, b, c, d, e, extra, attrs) => '<div class="tax-r krw ' + extra + '"' + (attrs || '') + '><span class="ell">' + a + '</span><span class="hm">' + b + '</span><span>' + c + '</span><span>' + d + '</span><span>' + e + '</span></div>';
    const det = r => {
      const off = r.st !== 'done', sg = r.dir === 'in' ? 1 : -1;
      const pill = r.st === 'fail' ? '<span class="pill w sm">' + (r.dir === 'in' ? '입금 안 됨' : '출금 실패·취소') + ' · 합계 제외</span>' : r.st === 'wait' ? '<span class="pill w sm">진행 중 · 합계 제외</span>' : r.src === 'int' ? '<span class="pill g sm">은행 아님</span>' : '';
      return '<div class="krw-d' + (off ? ' x' : '') + '"><span class="t num">' + esc(String(r.d).slice(5)) + '</span><span class="k"><span>' + esc(krwDir(r)) + '</span>' + pill
        + (num(r.fee) && !off ? '<span class="mut num">수수료 ' + kwFee(r.fee) + '</span>' : '') + '</span><span class="a num">' + kw(sg * num(r.amt), { sign: true }) + '</span></div>';
    };
    return '<div class="krwv">' + head + '<div class="card"><div class="tblhead"><h2 class="h2">원화 입출금 · 은행 ↔ 거래소</h2><span class="cap">월 → 건별 · 업비트·빗썸 · ' + esc(periodName()) + '</span></div>'
      + r5('월', '건수', '넣은 원화', '뺀 원화', '순투입', 'h')
      + yms.map(ym => {
        const g = krwAgg(gm[ym]), open = S.krwOpen.has(ym), lbl = (S.mobile ? ym.slice(2, 4) : ym.slice(0, 4)) + '년 ' + (+ym.slice(5)) + '월';
        const offTxt = !g.n ? [g.fail ? '실패 ' + g.fail + '건' : '', g.wait ? '진행 중 ' + g.wait + '건' : ''].filter(Boolean).join(' · ') : '';
        return '<div class="tax-g">' + r5(tc(open) + esc(lbl), offTxt ? '<span class="mut">' + offTxt + '</span>' : g.n + '건', g.in ? kw(g.in, { compact: cmp }) : '—', g.out ? kw(g.out, { compact: cmp }) : '—', g.in || g.out ? kw(g.net, { sign: true, compact: cmp }) : offTxt && S.mobile ? '<span class="mut" style="font-weight:500">' + offTxt + '</span>' : '—', 'm', ' role="button" tabindex="0" aria-expanded="' + open + '" data-a="krwTog" data-v="' + esc(ym) + '"')
          + (open ? clps(ym, '<div class="krw-ds">' + uiPaged('krwm:' + ym, gm[ym], r => det(r), { unit: '건' })
            + ((g.fee || g.intIn) && gm[ym].length > 1 ? '<div class="krw-d s"><span class="t"></span><span class="k mut">' + [g.fee ? '출금 수수료 ' + kwFee(g.fee) + '(예수금에서 따로 빠짐)' : '', g.intIn ? '내부 지급 ' + kw(g.intIn) + '(순투입 제외)' : ''].filter(Boolean).join(' · ') + '</span><span class="a"></span></div>' : '') + '</div>') : '') + '</div>';
      }).join('') + '</div></div>';
  }
  function krwDayHTML(iso) {
    const K = S.D && S.D.krw;
    if (!K || !iso) return '';
    const rs = arr(K.rows).filter(r => String(r.d || '').slice(0, 10) === iso);
    if (!rs.length) return '';
    const done = rs.filter(r => r.st === 'done'), bits = [];
    const grp = (f, lbl, sg) => { const g = done.filter(f); if (!g.length) return; const fee = sum(g, r => num(r.fee));
      bits.push('<span class="nw">' + lbl + ' <b>' + kw(sg * sum(g, r => num(r.amt)), { sign: true }) + '</b>' + (g.length > 1 ? ' <span class="mut">' + g.length + '건</span>' : '') + (fee ? ' <span class="mut">· 수수료 ' + kwFee(fee) + '</span>' : '') + '</span>'); };
    grp(r => r.src !== 'int' && r.dir === 'in', '원화 입금(은행에서)', 1);
    grp(r => r.src !== 'int' && r.dir === 'out', '원화 출금(은행으로)', -1);
    grp(r => r.src === 'int', '거래소 내부 지급', 1);
    if (rs.length > done.length) bits.push('<span class="nw mut">실패·진행 중 ' + (rs.length - done.length) + '건(합계 제외)</span>');
    return '<div class="krwday cap num">' + bits.map((x, i) => i ? '<span class="nw">· </span>' + x : x).join(' ') + ' <span class="nw mut">— 매매 손익 아님</span> <button class="link" data-a="goKrw" data-v="' + esc(iso.slice(0, 7)) + '">원화 입출금' + IC.right.replace('<svg', '<svg width="13" height="13"') + '</button></div>';
  }
  function feedHTML() {
    const ff = feedFull();
    const fq = S.feedFull;
    if (!ff && S.D.dayActs && fq && fq.st === 'load' && !fq.evs) return '<div class="eghd" aria-busy="true"><span class="cap num pvx" role="status" aria-live="polite">' + esc(periodName()) + ' 기록 받는 중…</span><span class="sp"></span></div><div class="card egl">' + evSkel(8, 4) + '</div>';
    const ffRe = !!(ff && fq && fq.st === 'load');
    const list = feedPayMerge((ff ? ff.evs : S.D.events).filter(e => srcPass(e) && gPass(e.iso || e.t)));
    const hidEv = arr(ff ? ff.hid : S.D.eventsHid).filter(e => srcPass(e) && gPass(e.iso || e.t));
    const hidAir = hidEv.filter(e => e.hideKind !== 'dust' && isAirQ(e.hide)).length;
    const hidDust = hidEv.filter(e => e.hideKind === 'dust').length, hidScam = hidEv.length - hidDust - hidAir;
    const hidPart = !!(ff && ff.paged && ff.nHid != null && ff.nHid > arr(ff.hid).length);
    const hidN = hidPart ? ff.nHid : hidEv.length;
    const hidKinds = (hidScam ? '<span class="pill g sm">스캠 ' + hidScam + '</span>' : '') + (hidAir ? '<span class="pill g sm" title="실매수 이력 없이 들어온 토큰이라 격리 — 스캠 확증은 없어요">에어드랍 의심 ' + hidAir + '</span>' : '') + (hidDust ? '<span class="pill g sm">소액 ' + hidDust + '</span>' : '');
    const hidChip = hidEv.length ? uiHidChip(hidN, 'evHidden', !!S.j.evHid, '자동으로 숨긴 이벤트 ' + nf('ko-KR').format(hidN) + '건' + (hidPart ? ' (최근 ' + nf('ko-KR').format(hidEv.length) + '건 불러옴)' : '') + ' — 스캠·에어드랍 의심·소액 입출금') : '';
    const hidTbl = S.j.evHid && hidEv.length ? '<div class="card hidlist"><div class="tblhead"><h2 class="h2">숨긴 이벤트 <span class="cnt num pvx">' + nf('ko-KR').format(hidN) + '</span></h2><span class="cnts hidk">' + hidKinds + '</span><span class="cap" title="스팸 격리 토큰은 원래 총자산·손익 밖, 소액 입출금은 잔고·손익에 그대로">목록에서만 뺀 기록 · 복원 = 미매칭 › 숨긴 항목' + (hidPart ? ' · 최근 ' + nf('ko-KR').format(hidEv.length) + '건 불러옴(칩 건수는 그 기준)' : '') + '</span></div>' + (() => { const all9 = groupRecon(hidEv.slice().reverse()), pg9 = uiPgSlice('evhid', all9);
        return (pg9.last > 0 ? '<div class="upga" data-pga="evhid"></div>' : '') + evTable(pg9.rows, true) + uiPgBar('evhid', all9.length, { unit: '줄' }); })() + '</div>' : '';
    const pgMore = !!(ff && ff.paged && ff.more), unf = S.src.mode === 'all' && S.g.period === 'all';
    const head = n => '<div class="eghd"><span class="cap num pvx">' + esc(periodName()) + ' ' + n + ' · 날짜별</span>' + (ffRe ? rfrTag() : '') + '<span class="sp"></span>' + hidChip + '</div>';
    if (!list.length && !pgMore) return head('0건') + hidTbl + '<div class="card empty"><b>이벤트가 없어요</b>기간·소스 필터를 넓혀 보세요</div>';
    const evc = x => 1 + arr(x._payc).length;
    const tot = pgMore ? (unf && ff.n ? nf('ko-KR').format(ff.n) : nf('ko-KR').format(sum(list, evc)) + '+') : nf('ko-KR').format(sum(list, evc));
    const days = feedDays(list);
    const evSig = [S.g.period, S.g.from, S.g.to, S.src.mode, S.src.key].join('|');
    if (S.j.evPgSig !== evSig) { S.j.evPgSig = evSig; uiPgReset('evdays'); }
    const pgE = uiPgSlice('evdays', days), shownDays = pgE.from + pgE.rows.length;
    if (pgMore && shownDays >= days.length - 1) feedMoreLoad();
    const body = uiPaged('evdays', days, (g, i) => feedDayHTML(g, i === 0, pgMore && i === days.length - 1), { unit: '일' });
    return head(tot + '건') + hidTbl + '<div class="card egl">' + body + (pgMore ? '<div class="foot"><span class="cap num">불러온 ' + nf('ko-KR').format(arr(ff.evs).length) + '건 · 더 불러오는 중…</span></div>' : '') + '</div>';
  }
  function feedDays(list) {
    const out = [], at = new Map();
    list.forEach(e => { const k = String(e.iso || '').slice(0, 10) || String(e.day || e.t || '').slice(0, 5); let g = at.get(k); if (!g) { g = { iso: k, evs: [] }; at.set(k, g); out.push(g); } g.evs.push(e); });
    return out;
  }
  const EV_KIND = [[/매도/, '매도'], [/매수/, '매수'], [/입금/, '입금'], [/전송|출금|이동/, '전송'], [/유동성|LP|범위|리워드|수수료 청구/, 'LP'], [/스테이킹/, '보상']];
  function feedKinds(evs) {
    const c = new Map(); let pay = 0;
    evs.forEach(e => { const k = (EV_KIND.find(x => x[0].test(String(e.k || ''))) || [0, '기타'])[1]; c.set(k, (c.get(k) || 0) + 1); pay += arr(e._payc).length; });
    if (pay) c.set('스왑 지불', pay);
    return Array.from(c.entries()).sort((a, b) => b[1] - a[1]).slice(0, 3).map(x => x[0] + ' ' + nf('ko-KR').format(x[1])).join(' · ');
  }
  const dayLbl = iso => { if (!isISO(iso)) return String(iso); const d = new Date(iso + 'T00:00:00'); return iso.slice(5) + ' (' + DOWS[d.getDay()] + ')'; };
  function feedDayHTML(g, latest, partial) {
    const key = 'evd:' + g.iso, open = uiOpen(key, latest), n = sum(g.evs, x => 1 + arr(x._payc).length);
    const hd = '<div class="egh' + (open ? ' open' : '') + '" data-anc="evday:' + esc(g.iso) + '"><button type="button" class="egt" data-a="uiFold" data-v="' + esc(key) + '" aria-expanded="' + open + '">'
      + '<b class="num">' + esc(dayLbl(g.iso)) + '</b><span class="num pvx">' + nf('ko-KR').format(n) + (partial ? '+' : '') + '건</span><span class="cap ell pvx">' + esc(feedKinds(g.evs)) + '</span><span class="sp"></span>' + UI_CHEV + '</button>'
      + (open ? '<button type="button" class="link egd" data-a="evDayGo" data-v="' + esc(g.iso) + '" title="일별 기록에서 이날 보기">일별' + IC.right + '</button>' : '') + '</div>';
    if (!open) return hd;
    return hd + clps('uf:' + key, '<div class="erows">' + uiPaged('evr:' + g.iso, g.evs, e => feedRow(e), { unit: '건' }) + '</div>');
  }
  function feedRow(e) {
    const tm = String(e.iso || '').length > 11 ? String(e.iso).slice(11, 16) : String(e.t || '').slice(6);
    return '<div class="erow"><span class="et num">' + esc(tm) + '</span><span class="ek">' + evPill(e.k) + '</span><b class="es ell">' + esc(evNm(e)) + impChip(e) + '</b>'
      + '<span class="ed ell" title="' + esc(evDT(e)) + '">' + evDH(e) + (e._payc ? payChip(e._payc) : '') + '</span><span class="eq num">' + esc(evQ(e)) + '</span><span class="ea num">' + evA(e) + '</span>'
      + '<span class="ex num">' + (e.tx && e.tx !== '—' ? '<button type="button" data-a="copy" data-v="' + esc(e.tx) + '" title="복사 · ' + esc(e.tx) + '">' + esc(short(e.tx)) + '</button>' : '') + '</span></div>';
  }
  function groupRecon(list) {
    const key = e => /잔고 정정/.test(String(e.d || '')) ? String(e.iso || e.t || '').slice(0, e.iso ? 10 : 5) + '|' + e.sym + '|' + (e.src || '') + '|' + e.d : null;
    const val = e => { const t = String(e.q == null ? '' : e.q).trim().replace(/,/g, '').replace(/^−/, '-'); return /^-?\d+(\.\d+)?$/.test(t) ? parseFloat(t) : NaN; };
    const G = {};
    list.forEach(e => { const k = key(e); if (k) (G[k] || (G[k] = [])).push(e); });
    const done = {};
    return list.reduce((o, e) => {
      const k = key(e), g = k ? G[k] : null;
      if (!g || g.length < 2 || g.some(x => !isFinite(val(x)))) { o.push(e); return o; }
      if (done[k]) return o;
      done[k] = 1;
      const tot = sum(g, val), qs = q(tot);
      o.push(Object.assign({}, e, { q: g.length + '회 · 합 ' + (tot > 0 && /[1-9]/.test(qs) ? '+' : '') + qs, tx: '—' }));
      return o;
    }, []);
  }
  function feedPayMerge(evs) {
    const payKey = e => (e.src || '') + '|' + (e.tx || '');
    const buys = new Map();
    evs.forEach(e => { if (e.k === '온체인 매수' && e.tx && e.tx !== '—' && /지불/.test(String(e.d || ''))) buys.set(payKey(e), e); });
    if (!buys.size) return evs;
    const pays = new Map();
    const rest = evs.filter(e => { if (e.k === '온체인 매도' && e.tx && buys.has(payKey(e))) { const b = buys.get(payKey(e)); (pays.get(b) || pays.set(b, []).get(b)).push(e); return false; } return true; });
    return rest.map(e => pays.has(e) ? Object.assign({}, e, { _payc: pays.get(e) }) : e);
  }
  function evTable(list, withDate) {
    if (S.mobile) return '<div style="padding:4px 16px">' + list.map(e => '<div style="padding:11px 0;border-bottom:1px solid var(--line);font-size:14px"><div class="row gap8">' + evPill(e.k) + '<b>' + esc(evNm(e)) + '</b>' + impChip(e) + '<span class="sp"></span><span class="mut num" style="font-size:12.5px">' + esc(withDate ? e.t : String(e.t).slice(6)) + '</span></div><div class="t2" style="margin-top:3px;font-size:13.5px">' + evDH(e) + (e._payc ? payChip(e._payc) : '') + '</div><div class="row sub num"><span>' + esc(evQ(e)) + '</span><span class="sp"></span><span>' + evA(e) + '</span></div></div>').join('') + '</div>';
    return '<div style="overflow-x:auto"><table class="ev" style="margin:0 24px;width:calc(100% - 48px)"><thead><tr><th scope="col" class="l">시각</th><th scope="col" class="l">종류</th><th scope="col" class="l">자산</th><th scope="col" class="l">내용</th><th scope="col">수량</th><th scope="col">금액</th><th scope="col">참조</th></tr></thead><tbody>'
      + list.map(e => '<tr><td class="l mut num nowrap">' + esc(withDate ? e.t : String(e.t).slice(6)) + '</td><td class="l">' + evPill(e.k) + '</td><td class="l"><b>' + esc(evNm(e)) + '</b>' + impChip(e) + '</td><td class="l"><div class="ell" style="max-width:340px" title="' + esc(evDT(e)) + '">' + evDH(e) + (e._payc ? payChip(e._payc) : '') + '</div></td><td class="num nowrap">' + esc(evQ(e)) + '</td><td class="num nowrap">' + evA(e) + '</td><td class="tx num nowrap">' + (e.tx && e.tx !== '—' ? '<button data-a="copy" data-v="' + esc(e.tx) + '" title="복사 · ' + esc(e.tx) + '">' + esc(short(e.tx)) + '</button>' : '—') + '</td></tr>').join('') + '</tbody></table></div>';
  }
  return {
    evPill, jBase, jList, krwDayHTML, lpGroupItems, optCk, plainT, popBox, px4, searchBox, srcBtn, taxTip, vJournal, __late
  };
};
