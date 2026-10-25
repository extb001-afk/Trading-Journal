'use strict';
(window.__tjTabs = window.__tjTabs || {}).other = function (X) {
  const {
    $, A, ago, arr, CHAIN_KO, cls, clsP, clsV, drawerHist, errTxt, esc, exLinked, exLogo, fmtTs, IC, isISO, LS, m, mN, nf, num,
    onUnauthorized, pad2, pctS, post, prTxt, PVM, pvMoney, pvOn, pvW, px, q, rate, renderAuto, renderOverlay, renderView, rw, S, sparkSVG,
    sum, sxGo, sync, toast, todayISO, trimZeros, UI_SHEETS, uiCell, uiDate, uiFold, uiPaged, uiPgBar, uiPgReveal, uiPgS, uiPgSlice, uiPick,
    uiRe, uiSheetClose, uiSheetOpen, vib
  } = X;
  const OA_CATS = [['realestate', '부동산', 'var(--c1)'], ['stock', '주식', 'var(--c2)'], ['gold', '금', 'var(--c3)'], ['car', '자동차', 'var(--c4)'],
    ['cash', '현금', 'var(--muted)'], ['etc', '기타', 'var(--ext)'], ['debt', '부채', '']];
  const OA_CN = {}; OA_CATS.forEach(c => { OA_CN[c[0]] = c[1]; });
  const OA_CC = {}; OA_CATS.forEach(c => { OA_CC[c[0]] = c[2]; });
  const OA_UNVER = '미검증 — 공개 문서만 보고 작성, 실제 계정으로 시험 안 함(완벽하지 않음)';
  const oaV = (v, cur) => (v == null || v === '' || !isFinite(+v)) ? NaN : cur === 'USD' ? +v : +v / rate();
  const oaItems = () => arr(S.oa.d && S.oa.d.items);
  const oaUnv = o => !isFinite(oaV(o.value, o.cur));
  const oaItemV = o => oaV(o.value, o.cur) * (o.liab ? -1 : 1);
  function oaPx(v, cur) {
    if (v == null || !isFinite(v)) return '—';
    const sym = cur === 'KRW' ? '₩' : '$';
    if (S.hide) return sym + pvW(PVM.px);
    return sym + rw(cur === 'KRW' ? nf('ko-KR', 0, 0).format(Math.round(v)) : nf('en-US', 2, 2).format(v));
  }
  const oaBrkPend = () => arr(S.oa.d && S.oa.d.brokers).filter(b => b.enabled && !(b.status && (b.status.ok === true || b.status.gate)));
  function oaTot() {
    const it = oaItems(), D = S.D, A0 = it.filter(o => !o.liab), L0 = it.filter(o => o.liab);
    const pa = A0.filter(oaUnv), pd = L0.filter(oaUnv), pend = pa.concat(pd);
    const bp = oaBrkPend(), brkFail = bp.filter(b => b.status && b.status.ok === false).length;
    const assets = pa.length || bp.length ? NaN : sum(A0, o => oaV(o.value, o.cur)), debt = pd.length || bp.length ? NaN : sum(L0, o => oaV(o.value, o.cur));
    const coin = D ? num(D.total) : 0;
    const NI = nftIncl(), nft = NI.on ? NI.usd : 0;
    return { coin, assets, debt, nft, nftOn: NI.on, nfMask: NI.on && S.rand, net: coin + assets + nft - debt, n: it.length, pend: pend.length + bp.length + (NI.on ? NI.pend + (NI.err ? 1 : 0) : 0),
      pendAuto: pend.filter(o => o.auto).length, pendBrk: bp.length, brkFail, pendNft: NI.on ? NI.pend : 0, nftErr: NI.on && NI.err ? 1 : 0 };
  }
  const oaPendTxt = T => !T.pend ? '' : '<span class="pvx oapend">' + [T.pendAuto ? '시세 대기 ' + T.pendAuto + '개' : '', T.pend - T.pendAuto - T.pendBrk - (T.pendNft || 0) - (T.nftErr || 0) ? '평가 대기 ' + (T.pend - T.pendAuto - T.pendBrk - (T.pendNft || 0) - (T.nftErr || 0)) + '개' : '',
    T.brkFail ? '증권사 동기화 실패 ' + T.brkFail + '곳' : '', T.pendBrk - T.brkFail ? '증권사 첫 동기화 대기 ' + (T.pendBrk - T.brkFail) + '곳' : '',
    T.pendNft ? 'NFT 바닥가 대기 ' + T.pendNft + '개' : '', T.nftErr ? 'NFT 조회 실패' : ''].filter(Boolean).join(' · ') + '</span>';
  function levS() { if (!S.lev) S.lev = { st: '', d: null, at: 0, err: '', tab: 'all' }; return S.lev; }
  function levLoad(force) {
    const L = levS();
    if (L.st === 'loading' || L.st === 'none') return;
    if (!force && L.at && Date.now() - L.at < 60000) return;
    L.st = 'loading';
    const ac = typeof AbortController === 'function' ? new AbortController() : null;
    const tmo = setTimeout(() => { if (ac) ac.abort(); }, 30000);
    fetch('/api/leverage', ac ? { cache: 'no-store', signal: ac.signal } : { cache: 'no-store' }).then(r => {
      if (r.status === 401) { onUnauthorized(); throw new Error('HTTP 401'); }
      if (r.status === 404) { L.st = 'none'; L.d = null; return null; }
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json().then(j => { if (!j || j.v !== 1 || !Array.isArray(j.rows)) throw new Error('응답 형식 오류'); L.d = j; L.st = 'ok'; L.err = ''; L.okAt = Date.now(); });
    }).catch(e => { L.st = 'err'; L.d = null; L.err = (e && e.name === 'AbortError') ? '응답이 30초 넘게 없어요' : ((e && e.message) || String(e)); })
      .then(() => { clearTimeout(tmo); L.at = Date.now(); if (S.D && S.tab === 'dash') renderAuto(); if (S.drawer === 'lev') renderOverlay(); });
  }
  function levData() {
    const L = levS();
    if (L.d && L.okAt && Date.now() - L.okAt > 300000) { L.d = null; if (L.st !== 'loading') L.st = 'err'; L.err = '5분 넘게 새 값을 못 받았어요'; }
    return L.d;
  }
  const levNeed = ms => { const L = levS(); if (L.st !== 'loading' && L.st !== 'none' && (!L.at || Date.now() - L.at >= (ms || 60000))) levLoad(true); };
  setInterval(() => { if (!document.hidden && !S.locked && S.D && (S.tab === 'dash' || S.drawer === 'lev')) levNeed(60000); }, 15000);
  const LEV_ST = { safe: '안전', warn: '주의', danger: '위험', unknown: '확인 못 함', nothr: '기준 모름' };
  const LEV_OFF = { MARGIN_CALL: '마진콜', PRE_LIQUIDATION: '청산 직전', FORCE_LIQUIDATION: '청산 진행', LIQUIDATION: '청산 진행', BANKRUPTCY: '파산', Liq: '청산 진행', Adl: '자동 감축(ADL)' };
  const LEV_MN = { ltv: 'LTV', margin_level: '레벨', debt_ratio: '부채 비율', risk_rate: '위험률', mgn_ratio: '증거금 비율', mm_rate: '유지증거금률' };
  const levPv = t => '<span class="pvx">' + esc(t) + '</span>';
  const levSide = r => r.side === 'SHORT' ? '숏' : r.side === 'LONG' ? '롱' : '방향 모름';
  const levTitle = r => r.kind === 'fut' ? esc(r.base || r.sym || '') + ' ' + levSide(r) + (r.lev ? ' <span class="pvx">×' + esc(String(+(+r.lev).toFixed(2))) + '</span>' : '') : esc(r.kindKo || '');
  function levMetric(r) {
    if (r.kind === 'fut') return r.liq ? '청산가 ' + px(r.liq) : '<span class="mut">청산가 없음</span>';
    const mt = r.metric;
    if (!mt) return '<span class="mut">—</span>';
    return levPv(mt.inf ? (LEV_MN[mt.name] || '') + ' 부채 없음' : mt.txt.replace(/^마진 레벨/, '레벨'));
  }
  function levLine(r, short) {
    if (short && r.state !== 'unknown') {
      const off9 = r.official && r.official.level >= 1 ? (LEV_OFF[r.official.v] || r.official.v) + ' · ' : '';
      const pre9 = r.state === 'danger' ? '위험 · ' : r.state === 'warn' ? '주의 · ' : '';
      return esc(off9) + pre9 + (r.state === 'nothr' && r.kind !== 'fut' ? '기준 모름' : levPv(r.dropShort || r.drop || ''));
    }
    if (r.state === 'unknown') return (short ? '값 못 받음(' : '지금 값을 못 받았어요(') + ago(r.measuredAt) + ' 값' + (r.kind === 'fut' ? (r.liq ? ' · 청산가 ' + px(r.liq) : '') : r.metric ? ' · ' + levPv(r.metric.txt) : '') + ')' + (short ? '' : ' — 받을 때까지 안전·위험 판정을 하지 않아요');
    const off = r.official && r.official.level >= 1 ? (LEV_OFF[r.official.v] || r.official.v) + ' · ' : '';
    const pre = r.state === 'danger' ? '위험 · ' : r.state === 'warn' ? '주의 · ' : r.state === 'nothr' && r.kind !== 'fut' ? '기준 모름 · ' : '';
    const d = r.drop ? levPv(r.drop) : r.kind === 'fut' ? '' : levPv('거래소가 마진콜·청산 기준을 주지 않아 값만 보여요');
    return esc(off) + pre + d;
  }
  const levAgeT = (r, full) => (r.sent ? '<span class="lvsent" title="' + esc(r.sent.label + ' — 빠른 감시가 텔레그램으로 알렸어요 · 값 측정 ' + ago(r.measuredAt)) + '">' + (full ? esc(r.sent.label) : '알림 보냄') + ' · ' + ago(r.sent.at) + '</span>' : ago(r.measuredAt));
  function levGauge(r) {
    const g = r.gauge, L9 = r.lbl || {};
    if (!g || r.state === 'unknown') return '<div class="lvg none" aria-hidden="true"></div><div class="lvgl"><span>' + (r.state === 'unknown' ? '판정 보류' : levPv(L9.now || '기준 모름')) + '</span><span>' + (r.state === 'unknown' ? '' : '기준 모름') + '</span></div>';
    const pc = v => Math.round(Math.max(0, Math.min(1, num(v))) * 1000) / 10 + '%';
    const end = r.kind === 'fut' ? '청산 ' + (r.liq ? px(r.liq) : '') : levPv(L9.end || '');
    return '<div class="lvg" role="img" aria-label="' + esc((L9.now || '') + ' · ' + (L9.mark || '') + ' · ' + (L9.end || '')) + '"><i class="f" style="width:' + pc(g.fill) + '"></i>' + (g.at != null ? '<i class="c" style="left:' + pc(g.at) + '"></i>' : '') + '<i class="e"></i></div>'
      + '<div class="lvgl num"><span>' + levPv(L9.now || '') + '</span><span>' + (L9.mark ? levPv(L9.mark) + ' · ' : '') + end + '</span></div>';
  }
  function levSub(r) {
    if (r.kind === 'fut') return (r.mode ? (r.mode === 'cross' ? '교차' : '격리') + ' · ' : '') + '진입 ' + px(r.entry) + ' · 마크 ' + px(r.mark);
    const ds = arr(r.debts), cs = arr(r.coll), yr = ds.find(x => x.yr != null);
    if (r.kind === 'loan') return '담보 ' + esc(cs.map(c => c.ccy).join('·') || '—') + ' → 부채 ' + esc(ds.map(x => x.ccy).join('·') || '—') + (yr ? ' · ' + levPv('연 ' + pctS(yr.yr * 100, 1).replace('+', '')) : '');
    return '차입 ' + esc(ds.map(x => x.ccy).join('·') || '—') + (num(r.dayUsd) > 0 ? ' · 하루 이자 ≈ ' + m(r.dayUsd) : '');
  }
  function levDebtHTML(cls) {
    const D = S.D;
    if (!D || !arr(D.debts).length) return '';
    return '<span class="lvdebt' + (cls ? ' ' + cls : '') + '" title="' + esc(D.debtLbl + ' — ' + D.debtTip() + ' · 상환 전 · 총자산에 이미 빠져 있어요') + '"><span class="mut">빌린 돈</span> <b class="num down">' + m(D.debtUsd, { sign: true, compact: true }) + '</b> <span class="mut">(총자산에 반영됨)</span></span>';
  }
  function levHTML() {
    levNeed(60000);
    const L = levS(), d = levData();
    const icon = '<svg class="lvic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12h4l3-8 4 16 3-8h4"/></svg>';
    const debtH = levDebtHTML();
    if (L.st === 'none' || (!d && L.st !== 'err')) return debtH ? '<section class="card lev lvone" aria-label="레버리지 · 대출">' + icon + '<b>레버리지 · 대출</b>' + debtH + '<span class="sp"></span>' + (L.st === 'none' ? '' : '<span class="cap" role="status">불러오는 중…</span>') + '</section>' : '';
    if (!d) return '<section class="card lev lvone" aria-label="레버리지 · 대출">' + icon + '<b>레버리지 · 대출</b>' + debtH + '<span class="mut" role="status">불러오지 못했어요 · ' + esc(errTxt(L.err)) + '</span><span class="sp"></span><button class="link" data-a="levRetry">다시 시도</button></section>';
    const C = d.counts || {}, rows = arr(d.rows), top = rows[0];
    const unc = num(C.unconfirmed), age = d.levTs ? ago(d.levTs) : '';
    const pills = (num(C.danger) ? '<span class="lvp danger pvx">위험 ' + C.danger + '</span>' : '') + (num(C.warn) ? '<span class="lvp warn pvx">주의 ' + C.warn + '</span>' : '') + (num(C.unknown) ? '<span class="lvp unk pvx">확인 못 함 ' + C.unknown + '</span>' : '');
    const day = d.dayUsd != null && num(d.dayUsd) > 0 ? '하루 이자 ≈ ' + m(d.dayUsd) : '';
    if (!rows.length) {
      const msg = d.missing ? (exLinked() ? '수집 전' : '거래소 연결 전') : '열린 것 없음 · <span class="pvx">' + num(d.exchanges) + '개 거래소</span> ' + age;
      return '<section class="card lev lvone" aria-label="레버리지 · 대출">' + icon + '<b>레버리지 · 대출</b>' + (debtH ? debtH + '<span class="mut lvmsg">' + (d.missing ? (exLinked() ? '수집 전' : '거래소 연결 전') : age) + '</span>' : '<span class="mut lvmsg">' + msg + '</span>') + '<span class="sp"></span>'
        + (unc ? '<span class="cap pvx">확인 못 한 곳 ' + unc + '</span>' : '') + '<button class="link" data-a="levOpen">전체 보기' + IC.right + '</button></section>';
    }
    const stc = top ? top.state : 'safe';
    if (S.mobile) {
      const next = rows.slice(1, 2).map(r => '<span class="lvmr"><span>' + esc(r.exKo) + ' ' + levTitle(r) + ' · ' + levMetric(r) + '</span><span class="lvmd st-' + r.state + '">' + (r.state === 'unknown' ? '확인 못 함' : r.kind === 'fut' ? (r.dist != null ? levPv(r.dist <= 0 ? '청산가 지남' : '청산까지 ' + (r.side === 'SHORT' ? '+' : '−') + (r.dist * 100).toFixed(1) + '%') : '청산가 없음') : r.dropCall != null && r.dropCall > 0 ? levPv('콜까지 −' + Math.round(r.dropCall * 100) + '%') : r.dropLiq != null && r.dropLiq > 0 ? levPv('청산까지 −' + Math.round(r.dropLiq * 100) + '%') : esc(LEV_ST[r.state])) + '</span></span>').join('');
      const pills2 = (num(C.danger) ? '<span class="lvp danger pvx">위험 ' + C.danger + '</span>' : '') + (num(C.warn) ? '<span class="lvp warn pvx">주의 ' + C.warn + '</span>' : '') + (!num(C.danger) && !num(C.warn) && num(C.unknown) ? '<span class="lvp unk pvx">확인 못 함 ' + C.unknown + '</span>' : '');
      return '<button type="button" class="card lev lvm st-' + stc + '" data-a="levOpen" aria-label="레버리지 · 대출 — 전체 보기"><span class="lvh"><b>레버리지 · 대출</b>' + (pills2 || '<span class="lvp pvx">열린 것 ' + rows.length + '</span>') + '<span class="sp"></span><span class="cap lvcnt pvx">' + rows.length + '개' + IC.right + '</span></span>'
        + (debtH ? levDebtHTML('lvmdebt') : '') + '<span class="lvml st-' + stc + '">' + esc(top.exKo) + ' ' + levTitle(top) + ' — ' + levLine(top, true) + '</span>' + (top.state !== 'unknown' && top.gauge ? '<span class="lvgw">' + levGauge(top) + '</span>' : '')
        + (next ? '<span class="lvml2">' + next + '</span>' : '')
        + (rows.length > 2 ? '<span class="lvmm"><span class="uchev" aria-hidden="true">' + IC.chev + '</span><b class="pvx">' + (rows.length - 2) + '개 더</b><span class="ell"> · ' + rows.slice(2, 4).map(r => esc(r.exKo + ' ' + (r.kind === 'fut' ? (r.base || '') + ' ' + levSide(r) : r.kindKo))).join(' · ') + (rows.length > 4 ? ' 외' : '') + '</span></span>' : '') + '<span class="lvmf"><span>' + (day || '&nbsp;') + '</span><span>' + (unc ? '<span class="pvx">확인 못 한 곳 ' + unc + '</span> · ' : '') + levAgeT(top, true) + '</span></span></button>';
    }
    const row = r => '<button type="button" class="lvr st-' + r.state + '" data-a="levOpen" data-v="' + esc(r.id) + '"><span class="lvn"><b>' + esc(r.exKo) + ' <span class="k">· ' + (r.kind === 'fut' ? levTitle(r) : esc(r.kindKo)) + '</span></b><span class="cap">' + levSub(r) + '</span></span>'
      + '<span class="lvgw">' + levGauge(r) + '</span><span class="lvv num">' + levMetric(r) + '</span><span class="lvd st-' + r.state + '">' + levLine(r, true) + '</span><span class="lva">' + levAgeT(r) + '</span></button>';
    const more = rows.length > 2 ? uiPaged('lev:dash', rows.slice(2), r => row(r), { unit: '개', cls: 'lvmore', more: (rest) => '<span class="pvx">' + rest + '개 더</span> · ' + rows.slice(2, 4).map(r => esc(r.exKo + ' ' + (r.kind === 'fut' ? (r.base || '') + ' ' + levSide(r) : r.kindKo))).join(' · ') + (rest > 2 ? ' 외' : '') }) : '';
    return '<section class="card lev st-' + stc + '" aria-label="레버리지 · 대출"><div class="lvh">' + icon + '<h2>레버리지 · 대출</h2><span class="lvp pvx">열린 것 ' + rows.length + '</span>' + (day ? '<span class="lvp num">' + day + '</span>' : '') + pills + (debtH ? '<span class="lvp lvpd">' + debtH + '</span>' : '')
      + '<span class="sp"></span>' + (unc ? '<span class="cap pvx" title="키 권한·조회 실패로 위험을 확인하지 못한 곳(전체 보기에서 이유)">확인 못 한 곳 ' + unc + '</span>' : '') + '<button class="link" data-a="levOpen">전체 보기' + IC.right + '</button></div>'
      + '<div class="lvrows">' + rows.slice(0, 2).map(row).join('') + more + '</div></section>';
  }
  function levCard(r) {
    const kv = [];
    const add = (k, v) => { if (v != null && v !== '') kv.push('<div><span>' + esc(k) + '</span><b class="num">' + v + '</b></div>'); };
    const ds = arr(r.debts), cs = arr(r.coll), mt = r.metric;
    const rateT = x => (x && x.yr != null ? levPv('연 ' + (x.yr * 100).toFixed(x.yr < 0.1 ? 2 : 1) + '%') : '<span class="mut">모름</span>');
    if (r.kind === 'fut') {
      add('수량', q(r.qty) + ' ' + esc(r.qtyUnit === 'contract' ? '계약' : r.qtyUnit === 'usd' ? 'USD' : (r.base || '')));
      add('진입', px(r.entry)); add('마크', px(r.mark)); add('청산가', r.liq ? px(r.liq) : '<span class="mut">없음</span>');
      add('평가손익', r.upnlUsd != null ? '<span class="' + clsV(r.upnlUsd) + '">' + m(r.upnlUsd, { sign: true }) + '</span>' : '—');
      add('레버리지', r.lev ? levPv('×' + String(+(+r.lev).toFixed(2))) : '—');
      add('증거금', r.mode === 'cross' ? '교차' : r.mode === 'isolated' ? '격리' : '—');
      if (r.acctMm != null) add('계정 유지증거금률', levPv((r.acctMm * 100).toFixed(1) + '%'));
    } else {
      if (r.kind === 'loan') {
        add('담보', cs.map(c => q(c.qty) + ' ' + esc(c.ccy)).join(' · ') || '—');
        ds.forEach(x => add('부채 ' + x.ccy, q(x.total)));
      }
      if (mt) add(LEV_MN[mt.name] || '지표', levPv(mt.inf ? '부채 없음' : String(mt.txt || '').split(' ').pop()));
      if (mt && (mt.call != null || mt.liq != null || mt.warn != null)) add(mt.call != null ? '마진콜 · 청산' : '경고 · 청산', levPv([mt.call != null ? mt.call : mt.warn, mt.liq].filter(v => v != null).map(v => mt.unit === 'frac' ? (v * 100).toFixed(1) + '%' : String(+v.toFixed(2))).join(' · ')));
      ds.slice(0, 3).forEach(x => add((r.kind === 'loan' ? '원금 · 이자' : x.ccy + ' 원금 · 이자') + (r.kind === 'loan' && ds.length > 1 ? ' ' + x.ccy : ''), x.principal != null ? q(x.principal) + ' · ' + q(x.interest) : q(x.total) + ' <span class="mut pvx">(합)</span>'));
      if (ds.length) add('이자율', rateT(ds.find(x => x.yr != null) || ds[0]));
      if (num(r.dayUsd) > 0) add('하루 이자', '≈ ' + m(r.dayUsd));
      if (r.liqPx) add('청산가', esc(String(r.liqPair || '').split(/[-/_]/)[0]) + ' ' + px(r.liqPx));
      if (r.pairDist != null) add('청산가까지', levPv((r.pairDist * 100).toFixed(1) + '%'));
    }
    add('기준', '<span' + (r.note ? ' title="' + esc(r.note) + '"' : '') + '>' + (r.thr === 'api' ? '거래소 제공' : r.thr === 'doc' ? '공식 문서' : r.thr === 'config' ? '내 설정' : r.thr === 'tj' ? 'tj-bot 기본(거래소가 마진콜 기준을 주지 않음)' : '<span class="mut">기준 모름</span>') + '</span>');
    add('측정', ago(r.measuredAt));
    const off = r.fresh && r.state !== 'unknown' && r.official && r.official.level >= 1 ? '<span class="lvp ' + (r.official.level >= 2 ? 'danger' : 'warn') + '" title="거래소가 알려 준 상태">' + esc(LEV_OFF[r.official.v] || r.official.v) + '</span>' : '';
    return '<article class="lvc st-' + r.state + '" data-lid="' + esc(r.id) + '" tabindex="-1"><div class="lvch"><b>' + esc(r.exKo) + ' ' + (r.kind === 'fut' ? '선물' : esc(r.kindKo)) + '</b><span class="cap">' + (r.kind === 'fut' ? levTitle(r) + (r.mode ? ' · ' + (r.mode === 'cross' ? '교차' : '격리') : '') : levSub(r)) + '</span><span class="sp"></span>' + off + '<span class="lvp ' + esc(r.state) + '">' + esc(LEV_ST[r.state] || r.state) + '</span></div>'
      + '<div class="lvkv">' + kv.join('') + '</div>' + (r.state === 'unknown' ? '' : '<div class="lvgw">' + levGauge(r) + '</div>')
      + '<div class="lvd st-' + r.state + '">' + levLine(r, false) + (r.sent ? ' · ' + levAgeT(r, true) : '') + '</div></article>';
  }
  function levDrawer() {
    const L = levS(), d = levData();
    const head = '<div class="drawer-bg" data-a="drawerClose"></div><aside class="drawer lev" role="dialog" aria-modal="true" aria-label="레버리지 · 대출"><div class="dh"><h2 class="h2">레버리지 · 대출</h2><span class="sp"></span><button class="iconbtn" data-a="drawerClose" aria-label="닫기">' + IC.close + '</button></div>';
    if (!d) return head + '<div class="cap" role="status">' + (L.st === 'err' ? '불러오지 못했어요 · ' + esc(errTxt(L.err)) + ' <button class="link" data-a="levRetry">다시 시도</button>' : '불러오는 중…') + '</div></aside>';
    const rows = arr(d.rows), T = d.tabs || {}, tab = ['all', 'fut', 'margin', 'loan'].indexOf(L.tab) >= 0 ? L.tab : 'all';
    const seg = '<div class="seg lvseg" role="group" aria-label="종류">' + [['all', '전체'], ['fut', '선물'], ['margin', '마진'], ['loan', '대출']].map(x => '<button data-a="levTab" data-v="' + x[0] + '" class="' + (tab === x[0] ? 'on' : '') + '" aria-pressed="' + (tab === x[0]) + '">' + x[1] + ' <span class="num pvx">' + num(T[x[0]]) + '</span></button>').join('') + '</div>';
    const cap = '<div class="cap lvcap"><span class="pvx">' + num(d.exchanges) + '개 거래소</span> · 마진·대출·선물 10분마다 확인' + (d.levTs ? ' · 마지막 확인 ' + ago(d.levTs) : '') + (d.missing ? ' · 아직 수집 전' : '') + '</div>';
    const DD = S.D && arr(S.D.debts).length ? S.D : null;
    const tiles = '<div class="lvtiles">' + uiCell('빌린 돈 합계', DD ? '<span class="down">' + m(DD.debtUsd, { sign: true, compact: true }) + '</span>' : d.debtUsd != null && num(d.debtUsd) > 0 ? '<span class="down">' + m(-num(d.debtUsd), { compact: true }) + '</span>' : '<span class="mut">없음</span>', null, null, DD ? DD.debtLbl + ' — 총자산에 이미 빠져 있어요 · ' + DD.debtTip() + ' · 상환 전' : '')
      + uiCell('하루 이자 (추정)', d.dayUsd != null && num(d.dayUsd) > 0 ? '≈ ' + m(d.dayUsd, { compact: true }) : '<span class="mut">—</span>')
      + uiCell('선물 평가손익', d.upnlUsd != null ? '<span class="' + clsV(d.upnlUsd) + '">' + m(d.upnlUsd, { sign: true, compact: true }) + '</span>' : '<span class="mut">' + (d.tabs && d.tabs.fut ? '모름' : '포지션 없음') + '</span>') + '</div>'
      + (() => {
        const p9 = [d.dayPartial ? '시세나 이자율을 모르는 통화는 하루 이자에서 빠졌어요' : '', d.debtStale ? '확인 못 한 줄은 마지막 값으로 더했어요' : '', d.upnlPartial && d.upnlUsd != null ? '평가손익을 모르는 포지션은 선물 평가손익 합에서 빠졌어요' : '',
          DD ? '빌린 돈은 총자산에 이미 빠져 있어요(상환 전) · 거래소·코인별은 아래 카드' : ''].filter(Boolean);
        return '<div class="cap lvpart"' + (p9.length > 1 ? ' title="' + esc(p9.join(' · ')) + '"' : '') + '>' + esc(p9[0] || '') + (p9.length > 1 ? ' <span class="mut pvx">외 ' + (p9.length - 1) + '가지</span>' : '') + '</div>'; })();
    const list = rows.filter(r => tab === 'all' || r.kind === tab);
    const cards = list.length ? uiPaged('lev:dr:' + tab, list, r => levCard(r), { unit: '개' })
      : '<div class="futnone">' + IC.info.replace('<svg', '<svg width="18" height="18"') + '<span>' + (tab === 'all' ? '열린 선물·마진 차입·대출이 없어요' : '이 종류는 열린 것이 없어요') + '</span></div>';
    const U = arr(d.unconfirmed), N = arr(d.unsupported);
    const fl = (U.length || N.length) ? '<div class="lvfold">' + uiFold('lev:unc', {
      cls: 'plain', label: '확인 못 한 곳과 지원 안 함',
      head: '<b class="pvx nowrap">확인 못 한 곳 ' + U.length + ' · 지원 안 함 ' + N.length + '</b><span class="cap">이유는 펼쳐서</span>',
      body: () => U.concat(N).map(x => '<div class="kv"><span class="row gap8">' + exLogo(x.ex) + '<span><b style="color:var(--text)">' + esc(x.exKo) + '</b> ' + esc(x.productKo) + '</span></span><span class="' + (U.indexOf(x) >= 0 ? 'wtxt' : 'mut') + '">' + esc(x.reason) + '</span></div>').join('')
        + '<div class="cap" style="margin-top:8px">확인 못 한 곳은 위험이 있어도 이 화면에 안 보일 수 있어요 — 키 권한(읽기)·연결을 확인해 주세요. 지원 안 함 = 거래소가 공개 API 를 주지 않거나 계정을 열지 않은 곳이에요.</div>'
    }) + '</div>' : '';
    return head + cap + seg + tiles + '<div class="lvcards">' + cards + '</div>' + fl + '</aside>';
  }
  function levOpen(el) {
    const ae = document.activeElement;
    S.levBack = ae && ae.getAttribute && ae.getAttribute('data-a') ? { el: ae, a: ae.getAttribute('data-a'), v: ae.getAttribute('data-v') } : null;
    const L = levS(), id = el && el.dataset ? el.dataset.v : '';
    if (id && L.d) { const r = arr(L.d.rows).find(x => x.id === id); if (r && L.tab !== 'all' && r.kind !== L.tab) L.tab = 'all';
      if (r) { const lst = arr(L.d.rows).filter(x => L.tab === 'all' || x.kind === L.tab), i = lst.indexOf(r); if (i >= 0) uiPgReveal('lev:dr:' + L.tab, x => x === r); } }
    S.drawer = 'lev';
    drawerHist();
    renderOverlay();
    const c = id ? [...document.querySelectorAll('#overlay .lvc')].find(x => x.getAttribute('data-lid') === id) : null;
    if (c) { try { c.scrollIntoView({ block: 'center' }); c.focus({ preventScroll: true }); } catch (e) {  } }
    else { const b = $('#overlay .drawer [data-a="drawerClose"]'); if (b) b.focus(); }
    levNeed(30000);
  }
  Object.assign(A, {
    levOpen: el => levOpen(el),
    levTab: el => { const L = levS(), v = el.dataset.v; if (['all', 'fut', 'margin', 'loan'].indexOf(v) < 0) return; L.tab = v; vib(); renderOverlay(); },
    levRetry: () => { const L = levS(); L.st = ''; L.at = 0; levLoad(true); renderView(); if (S.drawer === 'lev') renderOverlay(); },
  });
  function oaLoad(force) {
    const O = S.oa;
    if (O.st === 'none') return; if (O.st === 'loading') { if (force) O.again = true; return; }
    if (!force && O.at && Date.now() - O.at < 60000) return;
    const st0 = O.st, stale = sync.rd(O); let used = false;
    O.st = 'loading';
    fetch('/api/other_assets', { cache: 'no-store' }).then(r => {
      if (r.status === 401) { onUnauthorized(); throw new Error('HTTP 401'); }
      if (stale()) return null;
      if (r.status === 404) { O.st = 'none'; O.d = null; used = true; return null; }
      return r.json().then(j => { if (stale()) return; if (!j || !j.ok) throw new Error((j && j.error) || ('HTTP ' + r.status)); O.d = j; O.st = 'ok'; O.err = ''; used = true; if (arr(j.items).length) O.had = true; });
    }).catch(e => { if (stale()) return; O.st = 'err'; O.d = null; O.err = (e && e.message) || String(e); used = true; })
      .then(() => { if (used) O.at = Date.now(); else if (O.st === 'loading') O.st = st0; const again = O.again; O.again = false; if (again && !O.pend && O.st !== 'none') oaLoad(true); if (S.D && (S.tab === 'other' || S.tab === 'dash' || S.tab === 'settings')) (S.tab === 'dash' ? renderAuto : renderView)(); });
  }
  const oaNeed = ms => { if (S.oa.st !== 'loading' && S.oa.st !== 'none' && !S.oa.pend && (!S.oa.at || Date.now() - S.oa.at > (ms || 60000))) oaLoad(true); };
  function oaDate(d, o) {
    if (!isISO(d)) return '—';
    if (d === todayISO()) {
      const qt = o && o.quote && o.quote.t;
      if (qt && o.auto === 'stock') {
        const t = new Date((num(qt) + num(o.quote.off)) * 1000), tz = String(o.quote.tz || '');
        return '오늘 ' + pad2(t.getUTCHours()) + ':' + pad2(t.getUTCMinutes()) + (/^E[DS]T$/.test(tz) ? ' ET' : tz && tz !== 'KST' ? ' ' + esc(tz) : '');
      }
      return '오늘';
    }
    return (d.slice(0, 4) === todayISO().slice(0, 4) ? '' : d.slice(2, 4) + '/') + d.slice(5, 7) + '/' + d.slice(8, 10);
  }
  function oaSub(o) {
    const bits = [OA_CN[o.cat] || '기타'];
    if (o.auto === 'stock') bits.push(q(num(o.qty)) + '주' + (o.quote && o.quote.px ? ' × ' + oaPx(o.quote.px, o.quote.cur || o.cur) : ''));
    else if (o.cat === 'gold' && o.qty) bits.push(q(num(o.qty)) + (o.unit === 'ozt' ? 'ozt' : 'g'));
    else if (o.cat === 'stock' && !o.ticker) bits.push('코드 없음');
    else if (o.qty) bits.push(q(num(o.qty)) + esc(o.unit || ''));
    if (o.memo) bits.push((o.cat === 'realestate' ? '메모: ' : '') + prTxt(o.memo));
    return bits.join(' · ');
  }
  function oaChg(o) {
    if (o.auto && o.dday && isFinite(oaV(o.dday.v, o.cur))) return { v: oaV(o.dday.v, o.cur), pct: o.quote && o.quote.chg, auto: true };
    if (o.auto === 'gold' && o.quote && o.quote.chg != null && !oaUnv(o)) return { v: oaV(o.value, o.cur) * (o.quote.chg / (100 + o.quote.chg)), pct: o.quote.chg, auto: true };
    if (o.dprev && o.dprev.v != null && isFinite(oaV(o.dprev.v, o.cur))) { const v = oaV(o.dprev.v, o.cur) * (o.liab ? -1 : 1); return { v, pct: null, auto: false, rep: o.liab && v > 0 }; }
    return null;
  }
  function oaChgHTML(o) {
    const c = oaChg(o);
    if (!c || (Math.abs(c.v) < 1e-9 && c.pct == null)) return '<span class="mut">—</span>';
    if (c.auto && c.pct != null) return '<span class="' + cls(c.pct) + '" title="' + esc('오늘 ' + m(c.v, { sign: true })) + '">' + pctS(c.pct, 1) + ' 오늘</span>';
    return '<span class="' + cls(c.v) + '">' + m(c.v, { sign: true, compact: true }) + (c.rep ? ' (상환)' : '') + '</span>';
  }
  function oaMethod(o) {
    const st = o.quote && o.quote.stale ? ' <span class="pill w sm" title="' + esc(errTxt((o.quote.err || '마지막 시세 그대로') + ' — 마지막 값을 보여주는 중')) + '">시세 오래됨</span>' : '';
    if (o.broker) return '<span class="pill a sm" title="' + esc(OA_UNVER) + '">증권사 · ' + esc(o.bname || o.broker) + '</span>' + st;
    if (o.auto === 'gold') return '<span class="pill ok sm" title="' + esc('1 트로이온스 = ' + (o.quote && o.quote.src === 'GC=F' ? '금 선물(GC=F)' : 'PAXG') + ' 시세') + '">금 시세 자동</span>' + st;
    if (o.auto === 'stock') return '<span class="pill ok sm">시세 자동</span>' + st;
    return '<span class="pill sm">직접 입력</span>';
  }
  function oaIcon(o) {
    const col = o.cat === 'stock' && !o.ticker ? 'color-mix(in srgb,var(--c2) 60%,var(--surface3))' : (OA_CC[o.cat] || 'var(--muted)');
    return o.liab ? '<span class="oaic liab" aria-hidden="true"></span>' : '<span class="oaic" style="background:' + col + '" aria-hidden="true"></span>';
  }
  const OA_NAME_NUM = /[₩$]?\s?[+\-−]?\d[\d,.]*(?:\s?[^\s\d,.()·|/]{0,4})?/g;
  const oaTk0 = o => { const nm = String(o.name || ''), tk = String(o.ticker || ''); return tk && nm.toUpperCase().indexOf(tk.toUpperCase()) === 0 ? nm.slice(0, tk.length) : ''; };
  function oaNameTxt(o) {
    const nm = String(o.name || '');
    if (!pvOn()) return nm;
    const tk = oaTk0(o);
    return tk + nm.slice(tk.length).replace(OA_NAME_NUM, () => pvW(PVM.n));
  }
  function oaName(o) {
    const nm = String(o.name || '');
    if (!pvOn()) return esc(nm);
    const tk = oaTk0(o);
    return (tk ? '<span class="pvx">' + esc(tk) + '</span>' : '') + esc(nm.slice(tk.length).replace(OA_NAME_NUM, () => pvW(PVM.n)));
  }
  function oaTitle(o) {
    const tk = o.ticker && String(o.name || '').toUpperCase().indexOf(o.ticker) !== 0 ? '<span class="pvx">' + esc(o.ticker) + '</span> ' : '';
    return tk + oaName(o);
  }
  function oaRows(list) {
    if (!list.length) return '<div class="empty" style="padding:28px 0">' + (oaItems().length ? '이 종류의 자산이 없어요' : '아직 기타 자산이 없어요 — 오른쪽 위 ‘자산 추가’로 부동산·주식·금·자동차·현금·부채를 넣어 보세요') + '</div>';
    return '<div class="oatb" role="table" aria-label="기타 자산 목록"><div class="oar oah" role="row"><span role="columnheader">자산</span><span role="columnheader" class="r">평가금액</span><span role="columnheader" class="r">지난 평가 대비</span><span role="columnheader">평가 방식</span><span role="columnheader">평가일</span></div>'
      + list.map(o => '<button class="oar' + (S.oa.sel === o.id ? ' on' : '') + '" role="row" data-a="oaSel" data-v="' + esc(o.id) + '" data-anc="other:' + esc(o.id) + '" aria-pressed="' + (S.oa.sel === o.id) + '" aria-haspopup="dialog">'
        + '<span class="oan" role="cell">' + oaIcon(o) + '<span class="oat"><b>' + oaTitle(o) + '</b><small>' + oaSub(o) + '</small></span></span>'
        + '<span class="r num oav" role="cell">' + (oaUnv(o) ? '<span class="mut">' + (o.auto ? '시세 대기' : '평가 대기') + '</span>' : '<span class="' + (o.liab ? 'down' : '') + '">' + m(oaItemV(o), { compact: true }) + '</span>') + '</span>'
        + '<span class="r num oac" role="cell">' + oaChgHTML(o) + '</span>'
        + '<span class="oam" role="cell">' + oaMethod(o) + '</span>'
        + '<span class="num oad mut" role="cell">' + oaDate(o.date, o) + '</span></button>').join('') + '</div>';
  }
  function oaAlloc() {
    const it = oaItems().filter(o => !o.liab && !oaUnv(o)), tot = sum(it, o => Math.max(0, oaV(o.value, o.cur)));
    if (!(tot > 0)) return '';
    const by = OA_CATS.filter(c => c[0] !== 'debt').map(c => ({ k: c[0], l: c[1], col: c[2], v: sum(it.filter(o => o.cat === c[0]), o => Math.max(0, oaV(o.value, o.cur))) })).filter(x => x.v > 0);
    return '<div class="oabar" role="img" aria-label="' + esc('기타 자산 비중 ' + by.map(x => x.l + ' ' + Math.round(x.v / tot * 100) + '%').join(' · ')) + '">' + by.map(x => '<i style="width:' + (x.v / tot * 100).toFixed(2) + '%;background:' + x.col + '"></i>').join('') + '</div>'
      + '<div class="oaleg">' + by.map(x => '<span><i style="background:' + x.col + '"></i>' + x.l + ' <b style="color:' + x.col + '">' + Math.round(x.v / tot * 100) + '%</b></span>').join('') + '</div>';
  }
  function oaRe() { renderView(); if (S.sheet && S.sheet.k === 'oa') renderOverlay(); }
  UI_SHEETS.oa = () => (S.oa.form ? oaForm() : '');
  function oaForm() {
    const F = S.oa.form, ed = F.id ? oaItems().find(o => o.id === F.id) : null, brk = !!(ed && ed.broker);
    const dv = k => esc(S.drafts['oa:' + k] != null ? S.drafts['oa:' + k] : '');
    const isStock = F.cat === 'stock', isGold = F.cat === 'gold';
    const tk = String(S.drafts['oa:ticker'] || '').trim();
    const auto = (isStock && tk) || (isGold && String(S.drafts['oa:qty'] || '').trim());
    const lk = S.oa.lk;
    const lkTxt = !isStock ? '' : tk && lk && lk.t === tk.toUpperCase() ? (lk.st === 'loading' ? '<span class="mut">확인 중…</span>' : lk.st === 'ok' ? '<span class="oaok">' + IC.check + esc(lk.r.ticker) + ' · ' + esc(lk.r.name) + (lk.r.exch ? ' (' + esc(lk.r.exch) + ')' : '') + ' · ' + oaPx(lk.r.px, lk.r.cur) + '</span>' : '<span class="etxt">' + esc(errTxt(lk.err || '확인 실패')) + '</span>') : '<button class="link" data-a="oaLookup">종목 확인</button>';
    const chips = OA_CATS.map(c => '<button class="fbtn' + (F.cat === c[0] ? ' on' : '') + '" data-a="oaCat" data-v="' + c[0] + '" aria-pressed="' + (F.cat === c[0]) + '"' + (brk && F.cat !== c[0] ? ' disabled' : '') + '>' + c[1] + '</button>').join('');
    const unit = isStock ? '<span class="oaunit">주</span>' : isGold ? '<span class="seg oaseg" role="group" aria-label="금 단위">' + [['g', 'g'], ['ozt', 'ozt']].map(u => '<button data-a="oaUnit" data-v="' + u[0] + '" class="' + (F.unit === u[0] ? 'on' : '') + '" aria-pressed="' + (F.unit === u[0]) + '">' + u[1] + '</button>').join('') + '</span>' : '';
    const curSeg = '<span class="seg oaseg" role="group" aria-label="평가 통화">' + [['KRW', '₩ 원'], ['USD', '$ 달러']].map(c => '<button data-a="oaCur" data-v="' + c[0] + '" class="' + (F.cur === c[0] ? 'on' : '') + '" aria-pressed="' + (F.cur === c[0]) + '">' + c[1] + '</button>').join('') + '</span>';
    return '<section class="oaform oash" aria-label="자산 추가·수정"><div class="oah2">' + (ed ? oaTitle(ed) + ' <span class="mut oahs">고치는 중</span>' : '새 자산') + '</div>'
      + '<label class="oalab" for="oaName">이름</label><input id="oaName" class="field" data-pr="1" data-draft="oa:name" maxlength="60" placeholder="예) 잠실 아파트 · 금 골드바 · 주택담보대출" value="' + dv('name') + '">'
      + '<div class="oalab">종류</div><div class="chiprow oachips">' + chips + '</div>'
      + (isStock ? '<label class="oalab" for="oaTk">종목 코드(주식) — 넣으면 시세 자동</label><div class="oarow"><input id="oaTk" class="field num" data-draft="oa:ticker" data-enter="oaLookup" maxlength="12" autocapitalize="characters" spellcheck="false" placeholder="AAPL · 005930 · 035720.KQ" value="' + dv('ticker') + '"' + (brk ? ' disabled' : '') + '></div><div class="cap oalk" role="status">' + lkTxt + '</div>' : '')
      + '<label class="oalab" for="oaQty">수량' + (isGold || isStock ? '' : ' (선택)') + '</label><div class="oarow"><input id="oaQty" class="field num" data-pv="1" inputmode="decimal" data-draft="oa:qty" placeholder="' + (isStock ? '120' : isGold ? '1000' : '') + '" value="' + dv('qty') + '"' + (brk ? ' disabled' : '') + '>' + unit + '</div>'
      + (auto ? '<div class="cap">평가금액 = 수량 × 시세 (자동, 15분 지연) · ' + (isGold ? '1 트로이온스 = 31.1035g · PAXG 시세(없으면 금 선물)' : '코드 없으면 직접 입력') + '</div>'
        : '<label class="oalab" for="oaVal">평가금액</label><div class="oarow"><input id="oaVal" class="field num" data-pv="1" inputmode="decimal" data-draft="oa:value" placeholder="' + (F.cur === 'USD' ? '25000' : '730000000') + '" value="' + dv('value') + '">' + curSeg + '</div>'
          + '<label class="oalab" for="oaDate">평가일</label>' + uiDate('oa:date', S.drafts['oa:date'], { id: 'oaDate', label: '평가일', max: todayISO() }))
      + '<label class="oalab" for="oaMemo">메모</label><input id="oaMemo" class="field" data-pr="1" autocomplete="off" data-draft="oa:memo" maxlength="300" placeholder="예) KB시세 기준 · 키움 해외주식" value="' + dv('memo') + '">'
      + (brk ? '<div class="cap" style="margin-top:6px">' + esc((ed.bname || ed.broker) + '에서 가져온 항목 — 수량·코드는 다음 동기화가 덮어써요 · ' + OA_UNVER) + '</div>' : '')
      + '<div class="oabtns">' + (ed ? '<button class="btn" data-a="oaDel"' + (S.oa.busy ? ' disabled' : '') + '>' + (S.oa.delArm === ed.id ? '정말 삭제' : '삭제') + '</button>' : '') + (ed ? '<button class="btn ghost" data-a="oaNew">새로 추가</button>' : '') + '<button class="btn pri" data-a="oaSave"' + (S.oa.busy ? ' disabled' : '') + '>저장</button></div></section>';
  }
  function oaHist() {
    const o = oaItems().find(x => x.id === S.oa.sel) || oaItems()[0];
    if (!o) return '';
    const toV = v => o.cur === 'USD' ? num(v) : num(v) / rate();
    const ser = arr(o.series).filter(p => isISO(p[0]) && isFinite(+p[1]));
    let svg = '';
    if (ser.length > 1) {
      const W0 = 300, H0 = 70, vs = ser.map(p => toV(p[1])), lo = Math.min.apply(null, vs), hi = Math.max.apply(null, vs), sp = hi - lo || 1;
      const pts = vs.map((v, i) => (i / (vs.length - 1) * W0).toFixed(1) + ',' + (H0 - 4 - (v - lo) / sp * (H0 - 10)).toFixed(1));
      const col = o.liab ? 'var(--accent)' : (OA_CC[o.cat] || 'var(--accent)');
      svg = '<svg class="oasv" viewBox="0 0 ' + W0 + ' ' + H0 + '" preserveAspectRatio="none" role="img" aria-label="' + esc(oaNameTxt(o) + ' 평가 기록 ' + ser.length + '개 점 · ' + ser[0][0] + ' ~ ' + ser[ser.length - 1][0]) + '"><polyline fill="none" stroke="' + col + '" stroke-width="2" vector-effect="non-scaling-stroke" stroke-linejoin="round" points="' + pts.join(' ') + '"/><circle cx="' + pts[pts.length - 1].split(',')[0] + '" cy="' + pts[pts.length - 1].split(',')[1] + '" r="3" fill="' + col + '"/></svg>'
        + '<div class="oasx num"><span>' + oaDate(ser[0][0]) + '</span><span>' + oaDate(ser[ser.length - 1][0]) + '</span></div>';
    } else svg = '<div class="cap" style="margin:6px 0 10px">' + (o.auto ? '시세가 쌓이면 일별 종가로 차트를 그려요' : '평가금액을 고칠 때마다 기록이 쌓여 차트가 돼요') + '</div>';
    const H = arr(o.hist).slice().reverse();
    const lines = H.slice(0, 8).map((x, i) => {
      const nx = H[i + 1], qch = nx && x.qty != null && nx.qty != null && x.qty !== nx.qty;
      const v = m(toV(x.value) * (o.liab ? -1 : 1), { compact: true });
      const body = x.px && x.qty != null ? oaPx(x.px, x.cur) + ' × ' + q(num(x.qty)) + ' · ' + v : (x.qty != null && o.cat !== 'realestate' ? q(num(x.qty)) + esc(o.unit || '') + ' · ' : '') + v;
      const tag = qch ? ' (수량 변경)' : x.src === 'manual' ? ' (직접)' : x.src === 'broker' ? ' (증권사)' : '';
      return '<div class="oahl num"><span class="mut">' + oaDate(x.date) + '</span><span>' + body + '<span class="mut">' + tag + '</span></span></div>';
    }).join('');
    return '<section class="card oahist" aria-label="평가 기록"><div class="oah2">평가 기록 · ' + oaTitle(o) + ' <span class="mut oahs">(' + (o.auto ? '일별 종가 자동' : o.broker ? '증권사' : '직접 입력') + ')</span><span class="sp"></span><button class="link oaedl" data-a="oaSel" data-v="' + esc(o.id) + '" aria-haspopup="dialog">고치기</button></div>' + svg + (lines || '<div class="cap">기록 없음</div>') + '</section>';
  }
  function vOther() {
    const sb = '<div class="subtabs oasub" role="group" aria-label="기타 자산 보기">' + [['assets', '부동산 · 주식 · 금 · 현금 · 부채'], ['nft', 'NFT']].map(x =>
      '<button data-a="oaSub" data-v="' + x[0] + '" class="' + (S.oa.sub === x[0] ? 'on' : '') + '" aria-pressed="' + (S.oa.sub === x[0]) + '">' + x[1] + '</button>').join('') + '</div>';
    return sb + (S.oa.sub === 'nft' ? vNft() : vOtherAssets());
  }
  function vOtherAssets() {
    oaNeed(60000);
    const O = S.oa;
    if (O.st === 'none') return '<div class="card empty" style="margin-top:40px"><div class="eic">' + IC.info + '</div><b>이 서버는 아직 기타 자산을 지원하지 않아요</b><div class="cap" style="margin-top:6px">서버를 새 버전으로 올리면 부동산·주식·금·자동차·현금·부채를 함께 볼 수 있어요.</div></div>';
    if (!O.d) return O.st === 'err' ? '<div class="card empty" style="margin-top:40px"><div class="eic">' + IC.alert + '</div><b>기타 자산을 불러오지 못했어요</b><div class="cap" style="margin:6px 0 14px">' + esc(errTxt(O.err)) + '</div><button class="btn pri" data-a="oaReload">다시 시도</button></div>'
      : '<div class="kpis4"><div class="skel" style="height:112px"></div><div class="skel" style="height:112px"></div><div class="skel" style="height:112px"></div><div class="skel" style="height:112px"></div></div><div class="skel" style="height:420px;margin-top:20px"></div>';
    if (!S.oa.form) oaFormReset();
    const it = oaItems(), T = oaTot();
    const autoN = it.filter(o => o.auto), stN = autoN.filter(o => o.auto === 'stock').length, gN = autoN.filter(o => o.auto === 'gold').length;
    const debts = it.filter(o => o.liab);
    const chs = it.map(o => ({ o, c: oaChg(o) })).filter(x => x.c);
    const chA = sum(chs.filter(x => x.c.auto), x => x.c.v), chM = sum(chs.filter(x => !x.c.auto), x => x.c.v), chT = chA + chM;
    const kq = '<div class="kpis4 oak">'
      + '<div class="card kq oanet"><span class="ql">전체 순자산 <i>(코인 + 기타' + (T.nftOn ? ' + NFT' : '') + ' − 부채)</i></span><span class="qv num">' + (T.nfMask && isFinite(T.net) ? pvMoney('', true) : m(T.net, { compact: true })) + '</span><span class="qs num"><span class="nowrap">코인 ' + mN(T.coin, { compact: true }) + ' ·</span> <span class="nowrap">기타 ' + mN(T.assets, { compact: true }) + ' ·</span>' + (T.nftOn ? ' <span class="nowrap">NFT ' + (T.nfMask && isFinite(T.nft) ? pvMoney('', true) : mN(T.nft, { compact: true })) + ' ·</span>' : '') + ' <span class="nowrap">부채 ' + mN(-T.debt, { compact: true }) + (T.pend ? ' ·' : '') + '</span>' + (T.pend ? ' ' + oaPendTxt(T) : '') + '</span></div>'
      + '<div class="card kq"><span class="ql">기타 자산</span><span class="qv num">' + m(T.assets, { compact: true }) + '</span><span class="qs"><span class="pvx">' + (it.length - debts.length) + '개 · 시세 자동 ' + autoN.length + '개' + (autoN.length ? '(' + [stN ? '주식 ' + stN : '', gN ? '금 ' + gN : ''].filter(Boolean).join('·') + ')' : '') + ' · 직접 입력 ' + (it.length - debts.length - autoN.length) + '개</span></span></div>'
      + '<div class="card kq"><span class="ql">부채</span><span class="qv num oadebt">' + m(-T.debt, { compact: true }) + '</span><span class="qs">' + (debts.length ? debts.slice(0, 3).map(oaName).join(' · ') + (debts.length > 3 ? ' 외 ' + (debts.length - 3) : '') : '없음') + '</span></div>'
      + '<div class="card kq"><span class="ql">지난 평가 대비</span><span class="qv num ' + cls(chT) + '">' + (chs.length ? m(chT, { sign: true, compact: true }) : '—') + '</span><span class="qs num"><span class="nowrap">시세 자동 <span class="' + cls(chA) + '">' + mN(chA, { sign: true, compact: true }) + '</span> ·</span> <span class="nowrap">직접 수정 <span class="' + cls(chM) + '">' + mN(chM, { sign: true, compact: true }) + '</span></span></span></div></div>';
    const used = new Set(it.map(o => o.cat));
    const filt = [['all', '전체']].concat(OA_CATS.filter(c => c[0] !== 'etc' || used.has('etc')).map(c => [c[0], c[1]]));
    const list = S.oa.filter === 'all' ? it : it.filter(o => o.cat === S.oa.filter);
    const card = '<section class="card oamain" aria-label="기타 자산"><div class="oahd"><h2>기타 자산</h2><span class="sp"></span><div class="seg oaflt" role="group" aria-label="종류 거르기">'
      + filt.map(f => '<button data-a="oaFilter" data-v="' + f[0] + '" class="' + (S.oa.filter === f[0] ? 'on' : '') + '" aria-pressed="' + (S.oa.filter === f[0]) + '">' + f[1] + '</button>').join('') + '</div>'
      + '<button class="btn pri oaadd" data-a="oaNew">+ 자산 추가</button></div>'
      + oaAlloc() + oaRows(list)
      + '<div class="oanote">주식(종목 코드 있으면)·금은 시세 자동, 부동산·자동차·비상장은 직접 입력 — 값·수량을 고치면 이전 값이 기록으로 남아요' + (arr(O.d.brokers).some(b => b.enabled) ? ' · 증권사 연결은 ' + esc(OA_UNVER) : '') + '</div></section>';
    const oh9 = oaHist();
    return kq + '<div class="oagrid' + (oh9 ? '' : ' one') + '">' + card + (oh9 ? '<div class="oaside">' + oh9 + '</div>' : '') + '</div>';
  }
  function oaFormReset(o) {
    ['name', 'ticker', 'qty', 'value', 'date', 'memo'].forEach(k => { delete S.drafts['oa:' + k]; });
    S.oa.delArm = null; S.oa.lk = null;
    if (!o) { S.oa.form = { id: null, cat: S.oa.filter !== 'all' ? S.oa.filter : 'realestate', cur: 'KRW', unit: 'g' }; S.drafts['oa:date'] = todayISO(); return; }
    S.oa.form = { id: o.id, cat: o.cat, cur: o.cur || 'KRW', unit: o.cat === 'gold' ? (o.unit === 'ozt' ? 'ozt' : 'g') : (o.unit || '') };
    const d = { name: o.name, ticker: o.ticker || '', qty: o.qty != null ? String(o.qty) : '', value: o.auto ? '' : (o.value != null ? String(Math.round(num(o.value) * 100) / 100) : ''), date: o.auto ? '' : (o.date || ''), memo: o.memo || '' };
    Object.keys(d).forEach(k => { S.drafts['oa:' + k] = d[k]; });
  }
  async function oaLookup() {
    const t = String(S.drafts['oa:ticker'] || '').trim().toUpperCase();
    if (!t) return;
    if (!/^(?:[0-9][0-9A-Z]{5}(?:\.(?:KS|KQ))?|[A-Z]{1,6}(?:[.\-][A-Z]{1,2})?)$/.test(t)) { S.oa.lk = { t, st: 'err', err: '종목 코드 형식이 아니에요(미국 AAPL · 국내 005930)' }; oaRe(); return; }
    const tok = S.oa.lk = { t, st: 'loading' }; oaRe();
    try {
      const r = await fetch('/api/other_assets/quote?t=' + encodeURIComponent(t), { cache: 'no-store' });
      if (r.status === 401) { onUnauthorized(); return; }
      const j = await r.json().catch(() => null);
      if (S.oa.lk !== tok) return;
      S.oa.lk = j && j.ok ? { t, st: 'ok', r: j } : { t, st: 'err', err: (j && j.error) || ('HTTP ' + r.status) };
      if (j && j.ok && !String(S.drafts['oa:name'] || '').trim()) S.drafts['oa:name'] = (j.ticker + ' ' + (j.name || '')).trim().slice(0, 60);
    } catch (e) { if (S.oa.lk !== tok) return; S.oa.lk = { t, st: 'err', err: '연결 실패' }; }
    oaRe();
  }
  async function oaSave() {
    const F = S.oa.form, dr = k => String(S.drafts['oa:' + k] == null ? '' : S.drafts['oa:' + k]).trim();
    const body = { name: dr('name'), cat: F.cat, cur: F.cur, memo: dr('memo') };
    if (F.id) body.id = F.id;
    if (F.cat === 'stock') body.ticker = dr('ticker').toUpperCase();
    if (F.cat === 'gold') body.unit = F.unit;
    const qv = dr('qty').replace(/,/g, ''), vv = dr('value').replace(/,/g, '');
    const auto = (F.cat === 'stock' && body.ticker) || (F.cat === 'gold' && qv);
    const ed = F.id ? oaItems().find(o => o.id === F.id) : null;
    if (!(ed && ed.broker)) body.qty = qv === '' ? null : +qv;
    if (!auto) { body.value = vv === '' ? null : +vv; body.date = dr('date') || todayISO(); }
    if (!body.name) { toast('이름을 넣어 주세요', true); return; }
    if ((body.qty != null && !isFinite(body.qty)) || (body.value != null && !isFinite(body.value))) { toast('수량·평가금액은 숫자로 넣어 주세요', true); return; }
    const sn = oaSnap(F), done = sync.wr(S.oa);
    S.oa.busy = true; oaRe();
    const d = await post('/api/other_assets/save', body, F.id ? '고쳤어요 · 이전 값은 기록으로 남아요' : '추가했어요');
    done(); S.oa.busy = false;
    if (d) { S.oa.sel = d.id; if (S.oa.form === F && oaSnap(F) === sn) { oaFormReset(); if (S.sheet && S.sheet.k === 'oa') uiSheetClose(); } else if (S.oa.form === F && !F.id) F.id = d.id; S.oa.at = 0; oaLoad(true); } else oaRe();
  }
  const oaSnap = F => JSON.stringify([F.cat, F.cur, F.unit, ...['name', 'ticker', 'qty', 'value', 'date', 'memo'].map(k => S.drafts['oa:' + k])]);
  async function oaDel() {
    const F = S.oa.form;
    if (!F.id || S.oa.busy) return;
    if (S.oa.delArm !== F.id) { S.oa.delArm = F.id; oaRe(); return; }
    const done = sync.wr(S.oa); S.oa.busy = true; oaRe();
    const d = await post('/api/other_assets/delete', { id: F.id }, '지웠어요');
    done(); S.oa.busy = false;
    if (d) { if (S.oa.sel === F.id) S.oa.sel = null; if (S.oa.form === F || (S.oa.form && S.oa.form.id === F.id)) { oaFormReset(); if (S.sheet && S.sheet.k === 'oa') uiSheetClose(); } S.oa.at = 0; oaLoad(true); } else oaRe();
  }
  function oaDashLine() {
    oaNeed(300000);
    nftNeed(300000);
    if (S.oa.st === 'err' && S.oa.had) return '<a class="oaln" href="#other" aria-label="전체 순자산 — 기타 자산 조회 실패 · 기타 자산 탭으로"><span class="mut">전체 순자산</span> <b class="num">—</b> <span class="mut oalnx" role="status">기타 자산 조회 실패 · ' + esc(errTxt(S.oa.err)) + '</span><span class="sp"></span><span class="link">기타 자산 ' + IC.right + '</span></a>';
    const nOn = nftIncl().on;
    if ((!S.oa.d && !nOn) || (!oaItems().length && !oaBrkPend().length && !nOn)) return '';
    const T = oaTot();
    return '<a class="oaln" href="#other" aria-label="전체 순자산 — 기타 자산 탭으로"><span class="mut">전체 순자산</span> <b class="num">' + (T.nfMask && isFinite(T.net) ? pvMoney('', true) : m(T.net, { compact: true })) + '</b> <span class="mut num oalnx">= <span class="nowrap">코인 ' + m(T.coin, { compact: true }) + '</span> <span class="nowrap">+ 기타 ' + m(T.assets, { compact: true }) + '</span>' + (T.nftOn ? ' <span class="nowrap">+ NFT ' + (T.nfMask && isFinite(T.nft) ? pvMoney('', true) : m(T.nft, { compact: true })) + '</span>' : '') + ' <span class="nowrap">− 부채 ' + m(T.debt, { compact: true }) + '</span>' + (T.pend ? ' · ' + oaPendTxt(T) : '') + '</span><span class="sp"></span><span class="link">기타 자산 ' + IC.right + '</span></a>';
  }
  function brokersBody() {
    oaNeed(300000);
    const bl = arr(S.oa.d && S.oa.d.brokers);
    const rows = bl.length ? bl.map(b => '<div class="srow"><span class="dot' + (b.enabled ? (b.status && b.status.ok === false || b.ack ? ' w' : '') : ' off') + '"></span><div style="min-width:0;flex:1"><b>' + esc(b.name) + '</b> <span class="pill w sm" title="' + esc(b.note || OA_UNVER) + '">실험(미검증)</span>'
      + '<div class="cap">' + (b.enabled ? (b.status && b.status.gate ? esc(b.ack) : b.status && b.status.at ? (b.status.ok ? '마지막 동기화 ' + esc(fmtTs(b.status.at)) + ' · <span class="pvx">' + num(b.status.n) + '종목</span>' : '동기화 실패 · ' + esc(errTxt(b.status.err || ''))) : '켜짐 · 첫 동기화 대기') : '꺼짐') + (b.configured ? '' : ' · 설정 필드: ' + esc(arr(b.fields).join(', '))) + (b.status && b.status.noack ? ' · ' + esc(b.ack) : '') + '</div></div>'
      + (b.docs ? '<a class="link" href="' + esc(TJDOM.safeUrl(b.docs)) + '" target="_blank" rel="noopener noreferrer">문서</a>' : '') + '</div>').join('') : '<div class="cap">' + (S.oa.st === 'none' ? '이 서버는 아직 지원하지 않아요' : S.oa.st === 'err' ? '불러오지 못했어요 · ' + esc(errTxt(S.oa.err)) : '불러오는 중…') + '</div>';
    return rows + '<div class="cap sx-note">주문 기능 없음 · ' + esc(OA_UNVER) + ' · 필드는 src/brokers/README.md · 키·토큰은 화면·로그·저장 파일에 남지 않아요</div>';
  }
  Object.assign(A, {
    oaSel: el => { const o = oaItems().find(x => x.id === el.dataset.v); if (!o) return; S.oa.sel = o.id; oaFormReset(o); vib(); renderView(); uiSheetOpen('oa', o.id, '자산 수정', el); },
    oaNew: el => { oaFormReset(); renderView(); uiSheetOpen('oa', 'new', '자산 추가', el); },
    oaFilter: el => { S.oa.filter = el.dataset.v; renderView(); },
    oaCat: el => { const F = S.oa.form; if (!F || !OA_CN[el.dataset.v]) return; F.cat = el.dataset.v; if (F.cat === 'gold' && F.unit !== 'ozt') F.unit = 'g'; oaRe(); },
    oaCur: el => { if (S.oa.form) { S.oa.form.cur = el.dataset.v === 'USD' ? 'USD' : 'KRW'; oaRe(); } },
    oaUnit: el => { if (S.oa.form) { S.oa.form.unit = el.dataset.v === 'ozt' ? 'ozt' : 'g'; oaRe(); } },
    oaLookup: () => oaLookup(),
    oaSave: () => oaSave(),
    oaDel: () => oaDel(),
    oaReload: () => { S.oa.st = ''; S.oa.at = 0; oaLoad(true); renderView(); }
  });

  const NFT_CH = { eth: '이더리움', base: '베이스', arbitrum: '아비트럼', optimism: '옵티미즘', polygon: '폴리곤', bsc: 'BSC', sol: '솔라나', scroll: '스크롤',
    zksync: 'zkSync', gnosis: '노시스', hyperevm: 'HyperEVM', avalanche: '아발란체', blast: '블라스트', abstract: '앱스트랙트', berachain: '베라체인',
    robinhood: '로빈후드', megaeth: 'MegaETH', kaia: '카이아', apechain: 'ApeChain', ronin: '로닌', os: '오픈시' };
  const nftCh = c => NFT_CH[c] || CHAIN_KO[c] || String(c || '');
  const NFT_SPAM = { lure: '링크·보상 미끼 이름', desc_lure: '설명 미끼', unicode: '유니코드 위장', free_noprice: '공짜로 받음·시세 없음', mass_airdrop: '대량 에어드랍',
    mass_holders: '보유자 5만+·시세 없음', rep_scam: '탐색기 스캠 표시' };
  const NFT_SRC = { me: '매직에덴', cg: '코인게코', os: '오픈시' };
  const NFT_COL = ['#C8A46B', '#9FD3B0', '#E3B5D9', '#F0A36B', '#8FB3F0', '#B9B0F0', '#7FD0D0', '#E6C36A'];
  const nftMask = () => S.hide || S.rand;
  const nQ = v => (nftMask() ? pvW(PVM.q) : q(v));
  const nM = (v, o) => { if (v == null || !isFinite(v)) return '—'; if (!nftMask()) return m(v, o); const sg = o && o.sign ? (v > 0 ? '+' : v < 0 ? '−' : '') : (v < 0 ? '−' : ''); return pvMoney(sg, o && o.compact); };
  function nftLoad(force) {
    const N = S.nft;
    if (N.st === 'none') return;
    if (N.inflight) { if (force) N.again = true; return; }
    if (!force && N.at && Date.now() - N.at < 60000) return;
    N.inflight = true;
    if (!N.d) N.st = 'loading';
    const stale = sync.rd(N); let used = false;
    fetch('/api/nft', { cache: 'no-store' }).then(r => {
      if (r.status === 401) { onUnauthorized(); throw new Error('HTTP 401'); }
      if (stale()) return null;
      if (r.status === 404) { N.st = 'none'; N.d = null; N.inc = false; used = true; return null; }
      return r.json().then(j => { if (stale()) return; if (!j || !j.ok) throw new Error((j && j.error) || ('HTTP ' + r.status)); nftSet(j); used = true; });
    }).catch(e => { if (stale()) return; N.st = 'err'; N.d = null; N.err = (e && e.message) || String(e); used = true; })
      .then(() => {
        N.inflight = false;
        if (used) N.at = Date.now(); else if (N.st === 'loading') N.st = '';
        const again = N.again; N.again = false;
        if (again && !N.pend && N.st !== 'none') nftLoad(true);
        if (S.D && (S.tab === 'other' || S.tab === 'dash')) (S.tab === 'dash' ? renderAuto : renderView)();
      });
  }
  function nftSet(j) { const N = S.nft; N.d = j; N.st = 'ok'; N.err = ''; N.inc = j.include_in_total === true; N.at = Date.now(); }
  const nftNeed = ms => { const N = S.nft; if (!N.inflight && !N.pend && N.st !== 'none' && (!N.at || Date.now() - N.at > (ms || 60000))) nftLoad(true); };
  function nftIncl() {
    const N = S.nft;
    if (N.st === 'none' || !N.inc) return { on: false, usd: 0, pend: 0, err: false };
    if (!N.d) return { on: true, usd: NaN, pend: 0, err: N.st === 'err' };
    const t = N.d.totals || {}, pend = num(t.pending);
    return { on: true, usd: pend ? NaN : num(t.incl_usd), pend, err: false };
  }
  function nftNat(v, sym) {
    if (v == null || !isFinite(v) || v < 0) return '—';
    const u = sym ? ' ' + esc(sym) : '';
    if (S.hide) return pvW(PVM.px) + u;
    const t = v === 0 ? '0' : v >= 1000 ? nf('en-US', 0, 0).format(v) : v >= 1 ? nf('en-US', 0, 3).format(v) : v >= 1e-4 ? trimZeros(v.toPrecision(3)) : v.toExponential(2);
    return rw(t) + u;
  }
  const nftIni = r => { const c = String(r.name || r.sym || '?').replace(/^[^0-9A-Za-zㄱ-힣]+/, '').charAt(0) || '?'; return esc(c.toUpperCase()); };
  const nftColor = k => { let h = 0; for (const ch of String(k || '')) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return NFT_COL[h % NFT_COL.length]; };
  const nftThumb = r => '<span class="nftic" style="background:' + nftColor(r.key) + '" aria-hidden="true">' + nftIni(r) + '</span>';
  function nftAcq(r) {
    const a = r.acq; if (!a || !a.kind) return '';
    const paid = a.paid != null && isFinite(a.paid) && a.paid > 0 ? ' ' + nQ(a.paid) + (a.sym ? ' ' + esc(a.sym) : '') : '';
    return ({ bought: '산 것', mint_paid: '유료 민팅', mint_free: '직접 민팅(무료)', claim: '직접 수령(무료)', internal: '내 다른 지갑에서 옮김', received: '남이 보낸 것',
      airdrop_mass: '대량 에어드랍', unknown: '들어온 경위 모름' }[a.kind] || esc(a.kind_ko || a.kind)) + paid;
  }
  function nftTrade(r) {
    const t = r && r.trade;
    if (!t || (!t.exact && num(t.within) <= 7)) return '';
    const txt = t.exact ? (num(t.days) < 1 ? '오늘 거래' : '마지막 거래 ' + num(t.days) + '일 전') : num(t.within) === 30 ? '30일 거래' + (num(t.n) ? ' ' + num(t.n) + '건' : '') : '최근 ' + num(t.within) + '일 안 거래';
    const old = num(t.days) > 90, out = r.reason === 'thin_old' && !r.promoted && !r.watch;
    return '<span class="' + (old ? 'wtxt' : 'mut') + '" title="' + esc('거래가 뜸한 컬렉션 — 바닥가(리스팅)로 평가 · 근거 = 오픈시 30일 체결 수·마지막 체결' + (out ? ' · 마지막 거래 90일+ 라 총자산에서는 뺐어요' : '')) + '">' + txt + (out ? ' · 총자산 제외' : '') + '</span>';
  }
  const nftSer = r => { const x = r && r.series; if (!x || !x.plat) return ''; return esc(x.plat) + (x.split ? ' · 시리즈 나누는 중' : ''); };
  function nftTrackRows(d) {
    const seen = new Set(), out = [];
    arr(d.tracked).concat(arr(d.watch)).forEach(r => { if (r && r.key && !seen.has(r.key)) { seen.add(r.key); out.push(r); } });
    return out;
  }
  function nftRow(r) {
    const fp = r.fp || null, held = num(r.count) > 0, v = r.value || null, dd = r.dday || null;
    const sub = [nftCh(r.chain), nftSer(r), r.watch && !held ? '지켜보기 · 보유 없음' : r.promoted ? '직접 고름' : nftAcq(r)].filter(Boolean).join(' · ');
    const undo = r.watch ? '<button class="link nftun" data-a="nftOp" data-op="watch_remove" data-k="' + esc(r.key) + '">지켜보기 해제</button>'
      : r.promoted ? '<button class="link nftun" data-a="nftOp" data-op="unpromote" data-k="' + esc(r.key) + '">추적 해제</button>' : '';
    const trd = nftTrade(r);
    const fp2 = fp && fp.native ? esc((fp.basis === 'last' ? '마지막 체결가 · ' : '') + (NFT_SRC[fp.src] || fp.src_ko || fp.src || '') + (fp.at ? ' · ' + ago(fp.at) : '')) + (fp.stale ? ' · <span class="wtxt">오래됨</span>' : '') + (trd ? ' · ' + trd : '') : '';
    const fpTxt = fp && fp.native ? '<div class="num">' + nftNat(fp.native, fp.sym) + (fp.usd != null ? ' · ' + px(fp.usd) : '') + '</div><div class="nfts nftf2" title="' + esc(fp2.replace(/<[^>]*>/g, '')) + '">' + fp2 + '</div>'
      : '<div class="mut">—</div><div class="nfts">' + (r.neg ? '시세 출처에 없음' : '바닥가 받는 중') + '</div>';
    const vol = fp && fp.vol7 != null ? nftNat(fp.vol7, fp.sym) : fp && fp.vol24 != null ? '<span class="nfts">24h</span> ' + nftNat(fp.vol24, fp.sym) : '—';
    const day = dd && dd.pct != null && isFinite(dd.pct) ? '<span class="' + clsP(dd.pct) + '" title="' + esc('어제 대비 바닥가(달러) ' + pctS(dd.pct, 2) + (dd.usd != null ? ' · 평가 ' + nM(dd.usd, { sign: true }) : '')) + '">' + pctS(dd.pct, 1) + '</span>' : '<span class="mut">—</span>';
    const sp = sparkSVG(arr(r.series7).map(x => num(x && x[1])), 84, 26) || '<span class="mut" title="7일 추이 없음 — 일별 바닥가가 쌓이면 보여요">—</span>';
    return '<div class="nftr" role="row" data-anc="nft:' + esc(r.key) + '"><div class="nftn" role="cell">' + nftThumb(r) + '<div class="nftnm"><b title="' + esc(r.name) + '">' + esc(r.name) + '</b><small>' + sub + (undo ? ' · ' + undo : '') + '</small></div></div>'
      + '<div class="r num nftq" role="cell" data-l="개수">' + (held ? nQ(num(r.count)) : '—') + '</div>'
      + '<div class="r nftf" role="cell" data-l="바닥가">' + fpTxt + '</div>'
      + '<div class="r num nftvo" role="cell" data-l="거래량">' + vol + '</div>'
      + '<div class="r num nftd" role="cell" data-l="오늘">' + day + '</div>'
      + '<div class="c nftsp" role="cell">' + sp + '</div>'
      + '<div class="r num nftv" role="cell">' + (held && v && v.usd != null ? nM(v.usd) : '—') + '</div></div>';
  }
  function nftCand(r) {
    const fp = r.fp || null, v = r.value || null, n9 = num(r.count);
    const sub = [nftCh(r.chain), r.std, n9 ? nQ(n9) + '개' : ''].filter(Boolean).join(' · ');
    const hint = !fp && r.chain !== 'sol' && r.reason !== 'checking' && S.nft.d && !(S.nft.d.sources && S.nft.d.sources.opensea && S.nft.d.sources.opensea.key) ? ' · EVM 바닥가 출처 없음 — 오픈시 키 필요' : '';
    const acq = nftAcq(r);
    const trd = nftTrade(r), ser = r.series && r.series.plat && !r.series.split ? esc(r.series.plat) : '';
    const why = (ser ? ser + ' · ' : '') + esc(r.reason_ko || r.reason || '') + (acq && r.reason !== 'checking' ? ' · ' + acq : '') + (trd ? ' · ' + trd : '') + hint;
    const fpT = fp && fp.native ? nftNat(fp.native, fp.sym) + (n9 > 1 || nftMask() ? ' × ' + nQ(n9) : '') + (v && v.usd != null ? ' ≈ ' + nM(v.usd) : '') : '—';
    const btn = (op, t, c) => '<button class="btn sm' + (c ? ' ' + c : '') + '" data-a="nftOp" data-op="' + op + '" data-k="' + esc(r.key) + '"' + (S.nft.busy ? ' disabled' : '') + '>' + t + '</button>';
    return '<div class="nftc" data-anc="nft:' + esc(r.key) + '">' + nftThumb(r) + '<div class="nftct"><div><b>' + esc(r.name) + '</b> <span class="nfts">' + sub + '</span></div><div class="nftwhy pvx">' + why + '</div></div>'
      + '<div class="nftcf num">' + fpT + '</div><div class="nftcb">' + btn('promote', '추적', 'pri') + (r.notspam ? btn('spam', '스팸으로') : btn('hide', '숨김')) + '</div></div>';
  }
  function nftWatchForm() {
    const d = S.nft.d || {}, N = S.nft;
    const wch = arr(d.watch_chains).filter(c => c !== 'sol');
    const wsel = uiPick('nft:wch', (wch.length ? wch : ['eth']).map(c => [c, nftCh(c)]), S.drafts['nft:wch'] || 'eth', '체인(주소로 넣을 때)', { cls: 'nftwch' });
    return '<div class="nftwatch"><label for="nftWatch">컬렉션 주소 또는 링크</label><input id="nftWatch" class="field" type="text" data-draft="nft:watch" placeholder="컬렉션 주소 또는 매직에덴·오픈시 링크" autocomplete="off" spellcheck="false">'
      + wsel + '<button class="btn pri" data-a="nftWatch"' + (N.busy ? ' disabled' : '') + '>지켜보기</button></div><div class="nfts" style="margin-top:8px">0x 주소면 체인을 고르고 · 솔라나 주소·매직에덴 심볼·링크는 그대로</div>';
  }
  UI_SHEETS.nftw = () => nftWatchForm();
  function vNft() {
    nftNeed(60000);
    const N = S.nft, d = N.d;
    if (N.st === 'none') return '<div class="card empty" style="margin-top:20px"><div class="eic">' + IC.info + '</div><b>이 서버는 아직 NFT 를 지원하지 않아요</b><div class="cap" style="margin-top:6px">서버를 새 버전으로 올리면 지갑의 NFT 와 바닥가를 볼 수 있어요.</div></div>';
    if (!d) return N.st === 'err' ? '<div class="card empty" style="margin-top:20px"><div class="eic">' + IC.alert + '</div><b>NFT 를 불러오지 못했어요</b><div class="cap" style="margin:6px 0 14px">' + esc(errTxt(N.err)) + '</div><button class="btn pri" data-a="nftReload">다시 시도</button></div>'
      : '<div class="skel" style="height:96px;margin-top:16px"></div><div class="skel" style="height:260px;margin-top:16px"></div><div class="skel" style="height:200px;margin-top:16px"></div>';
    const T = d.totals || {}, tr = nftTrackRows(d), cands = arr(d.candidates), sp = d.spam || { n: 0, items: [] }, hid = arr(d.hidden), inc = d.include_in_total === true;
    const sc = d.scan || {}, prog = sc.total && sc.done < sc.total ? ' · 첫 발견 ' + num(sc.done) + '/' + num(sc.total) + '쌍' : '';
    const lpn = num(d.lp_items) || num(d.lp_excluded);
    const sumC = '<section class="card nftsum" aria-label="NFT 요약"><div class="nfth"><h2>NFT</h2><div class="nftcnt pvx">추적 <b>' + tr.filter(r => num(r.count) > 0).length + '</b> · 후보 <b>' + cands.length + '</b> · 스팸으로 거름 <b>' + num(sp.n) + '</b>'
      + (lpn ? ' · LP 포지션 NFT ' + lpn + '개는 LP 화면에서' : '') + prog + '</div></div>'
      + '<div class="nftsr"><div><div class="nftl">추적 중 평가(바닥가 × 개수)</div><div class="nftbig num">' + nM(num(T.usd), { compact: true }) + '</div>'
      + (num(T.pending) ? '<div class="nfts pvx">바닥가 대기 ' + num(T.pending) + '개 — 합계에서 빠짐</div>' : '')
      + (num(T.old_n) ? '<div class="nfts pvx" title="거래가 뜸한 컬렉션 중 마지막 거래가 90일 넘은 것 — 여기 평가엔 넣고 총자산(전체 순자산)에서는 뺐어요 · 직접 추적에 넣으면 포함">마지막 거래 90일+ ' + num(T.old_n) + '개(' + nM(num(T.old_usd), { compact: true }) + ') — 총자산에선 뺌</div>' : '')
      + (num(T.split) ? '<div class="nfts pvx">아트블럭 시리즈 나누는 중 ' + num(T.split) + '개 — 다음 발견 때 시리즈별 바닥가로</div>' : '') + '</div>'
      + '<div class="nftincw"><div class="nftinc"><span>총자산에 포함</span><button class="sw2' + (inc ? ' on' : '') + '" data-a="nftInc" role="switch" aria-checked="' + inc + '" aria-label="NFT 평가를 총자산(전체 순자산)에 포함"' + (N.busy ? ' disabled' : '') + '></button></div>'
      + '<div class="nfts">' + (inc ? '켜짐 — 대시보드·기타 자산의 \'전체 순자산\'에 NFT 줄이 더해져요(코인 총자산 숫자는 그대로)' : '꺼짐 — NFT 는 여기서만 따로 보여요') + '</div></div></div></section>';
    const head = '<div class="nftr nfthd" role="row"><div role="columnheader">컬렉션</div><div class="r" role="columnheader">개수</div><div class="r" role="columnheader">바닥가</div><div class="r" role="columnheader">거래량 7일</div><div class="r" role="columnheader">오늘 변동</div><div class="c" role="columnheader">7일 추이</div><div class="r" role="columnheader">평가</div></div>';
    const pgT = uiPgSlice('nftt', tr);
    const trC = '<section class="card nftsec" aria-label="추적 중"><div class="nftsh"><h3>추적 중</h3><span class="nfts nft1" title="바닥가·거래량 확인된 컬렉션은 자동 · 후보에서 고른 것 · 지켜보기">자동 · 고른 것 · 지켜보기</span></div>'
      + (pgT.last > 0 ? '<div class="upga" data-pga="nftt"></div>' : '') + '<div class="nfttw" tabindex="0" aria-label="추적 중 표 — 좁은 화면에선 옆으로 밀어 보기"><div class="nftt" role="table">' + head + (tr.length ? pgT.rows.map(r => nftRow(r)).join('') : '<div class="nftempty">아직 추적 중인 컬렉션이 없어요 — 아래 후보에서 고르거나 지켜보기로 넣어 주세요</div>') + '</div></div>'
      + uiPgBar('nftt', tr.length, { unit: '개' })
      + '<div class="nftwadd"><button type="button" class="btn sm" data-a="nftWatchOpen" aria-haspopup="dialog">+ 지켜보기 추가</button><span class="nfts">보유 없이 바닥가만 볼 컬렉션 — 주소·매직에덴·오픈시 링크</span></div></section>';
    const caC = '<section class="card nftsec" aria-label="후보"><div class="nftsh"><h3>후보 <span class="nfts pvx">' + cands.length + '</span></h3><span class="nfts nft1" title="가격·거래량이 애매하거나 시세 출처가 없는 것 — 고르면 추적 시작">애매한 것 — 고르면 추적 시작</span></div>'
      + '<div class="nftcl">' + (cands.length ? uiPaged('nftc', cands, r => nftCand(r), { unit: '개' }) : '<div class="nftempty">후보가 없어요</div>') + '</div></section>';
    const byR = {}; arr(sp.items).forEach(x => { const k = x.reason || 'etc'; byR[k] = (byR[k] || 0) + 1; });
    const chips = Object.keys(byR).sort((a, b) => byR[b] - byR[a]).map(k => '<span class="nftchip pvx">' + esc(NFT_SPAM[k] || k) + ' <b>' + byR[k] + '</b></span>').join('');
    const spRow = x => '<div class="nftsi" data-anc="nft:' + esc(x.key) + '"><span class="nftsn" title="' + esc(x.name) + '">' + esc(x.name || x.sym || x.key) + '</span><span class="nfts">' + esc(nftCh(x.chain)) + '</span><span class="nftchip pvx">' + esc(NFT_SPAM[x.reason] || x.reason_ko || x.reason) + '</span><span class="sp"></span><button class="btn sm" data-a="nftOp" data-op="notspam" data-k="' + esc(x.key) + '"' + (N.busy ? ' disabled' : '') + '>정상으로</button></div>';
    const spList = N.spamOpen ? '<div class="nftsl">' + uiPaged('nftsp', arr(sp.items), spRow, { unit: '개' }) + '</div>' : '';
    const spC = '<section class="card nftsec nftspam" aria-label="스팸으로 거른 것"><div class="nftsph"><button class="btn sm" data-a="nftSpam" aria-expanded="' + N.spamOpen + '">' + (N.spamOpen ? '스팸 목록 접기' : '스팸으로 거른 <span class="pvx">' + num(sp.n) + '</span>개 보기') + ' <span aria-hidden="true">' + (N.spamOpen ? '▴' : '▾') + '</span></button><div class="nftchips">' + chips + '</div></div>'
      + '<div class="nfts">잘못 걸렀으면 펼쳐서 \'정상으로\' 누르면 후보로 옮겨요</div>' + spList + '</section>';
    const hiC = hid.length ? '<section class="card nftsec" aria-label="숨긴 컬렉션"><button class="link" data-a="nftHid" aria-expanded="' + N.hidOpen + '">숨긴 컬렉션 <span class="pvx">' + hid.length + '</span>개 ' + (N.hidOpen ? '접기' : '보기') + '</button>'
      + (N.hidOpen ? '<div class="nftsl">' + uiPaged('nfth', hid, x => '<div class="nftsi" data-anc="nft:' + esc(x.key) + '"><span class="nftsn">' + esc(x.name) + '</span><span class="nfts">' + esc(nftCh(x.chain)) + '</span><span class="sp"></span><button class="btn sm" data-a="nftOp" data-op="unhide" data-k="' + esc(x.key) + '">다시 보기</button></div>', { unit: '개' }) + '</div>' : '') + '</section>' : '';
    const srcs = d.sources || {}, uns = arr(sc.unsupported).map(u => nftCh(u.chain)).filter(Boolean), cg = srcs.coingecko || {};
    const osk = !!(srcs.opensea && srcs.opensea.key), cgPl = cg.plan === 'pro' ? '프로' : '데모', cgTxt = '코인게코 NFT(' + (cg.key ? (cg.key_bad ? cgPl + ' 키 거부 — 무키로 조회 중' : cgPl + ' 키') : '무키 — 무료 데모 키를 넣으면 빨라져요') + ')';
    const noteT = '바닥가 출처: 솔라나 = 매직에덴(1시간마다) · EVM = ' + (osk ? '오픈시만(추적 15분 · 나머지 6시간) · 그 밖 체인 ' + cgTxt : cgTxt + ' · 오픈시 키를 넣으면 오픈시를 먼저 써서 NFT 추적이 더 원활해요(설정 › 연결·키)')
      + (uns.length ? ' · ' + uns.join('·') + ' NFT 는 무료 탐색기 API 미지원이라 제외' : '') + ' · 이미지는 외부 주소라 기본 숨김(머리글자 표시)';
    const note = '<div class="nftnote" title="' + esc(noteT) + '">바닥가 출처: 솔라나 = 매직에덴 · EVM = ' + (osk ? '오픈시 · 그 밖 체인 ' : '') + '코인게코' + (cg.key && cg.key_bad ? '(' + cgPl + ' 키 거부 — 무키로 조회 중)' : '') + (osk ? '' : ' · 오픈시 키를 넣으면 더 원활해요') + '</div>';
    return '<div class="nftw">' + nftNotice(d) + sumC + trC + caC + spC + hiC + note + '</div>';
  }
  function nftNotice(d) {
    const n = d && d.notice;
    if (!n || !n.text) return '';
    const bad = n.kind === 'key_bad', w = num(n.waiting);
    const sub = [w > 0 ? '바닥가를 기다리는 EVM 컬렉션 ' + w + '개' : '', n.blocked_until ? '코인게코 무키 호출 쉼 ' + fmtTs(n.blocked_until).slice(6) + '까지' : ''].filter(Boolean).join(' · ');
    return '<div class="bnr nftbn ' + (bad ? 'e' : 'w') + '" role="status" title="' + esc(n.text + (sub ? ' — ' + sub : '')) + '"><div class="nftbt"><b>' + esc(n.text) + '</b>' + (sub ? '<span class="bd pvx"> · ' + esc(sub) + '</span>' : '') + '</div>'
      + '<button class="btn sm pri" data-a="nftKeys">' + (bad ? '키 다시 넣기' : '무료 키 넣기') + '</button></div>';
  }
  function nftWatchBody(v, ch) {
    v = String(v || '').trim();
    if (!v) return null;
    if (/^https?:\/\//i.test(v) || /(?:magiceden\.io|opensea\.io|scan\.(?:io|org|com)|blockscout\.com|etherscan\.io)\//i.test(v)) return { op: 'watch_add', link: v };
    if (/^0x[0-9a-fA-F]{40}$/.test(v)) return { op: 'watch_add', chain: ch || 'eth', address: v };
    if (/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(v)) return { op: 'watch_add', chain: 'sol', address: v };
    if (/^[A-Za-z0-9_\-]{1,80}$/.test(v)) return { op: 'watch_add', symbol: v };
    return null;
  }
  async function nftPost(body, msg) {
    const N = S.nft;
    if (N.busy) return null;
    N.busy = true; const done = sync.wr(N); uiRe();
    let d = null;
    try { d = await post('/api/nft/prefs', body, msg); } finally { done(); N.busy = false; }
    if (d) nftSet(d);
    else if (!N.pend) { N.at = 0; nftLoad(true); }
    uiRe();
    return d;
  }
  const NFT_OPMSG = { promote: '추적에 넣었어요', unpromote: '추적에서 뺐어요', hide: '숨겼어요', unhide: '다시 보여요', notspam: '후보로 옮겼어요', spam: '스팸으로 되돌렸어요', watch_remove: '지켜보기에서 뺐어요' };
  Object.assign(A, {
    oaSub: el => { S.oa.sub = el.dataset.v === 'nft' ? 'nft' : 'assets'; LS.set('tj_v2_oa_sub', S.oa.sub); renderView(); },
    nftReload: () => { S.nft.st = ''; S.nft.at = 0; nftLoad(true); renderView(); },
    nftOp: el => { const op = el.dataset.op, k = el.dataset.k; if (!NFT_OPMSG[op] || !k) return null; return nftPost({ op, key: k }, NFT_OPMSG[op]); },
    nftInc: () => { const on = !(S.nft.d && S.nft.d.include_in_total === true); return nftPost({ op: 'include', on }, on ? '총자산(전체 순자산)에 NFT 를 포함했어요' : '총자산에서 NFT 를 뺐어요'); },
    nftWatch: async () => {
      const b = nftWatchBody(S.drafts['nft:watch'], S.drafts['nft:wch'] || 'eth');
      if (!b) { toast('컬렉션 주소(0x…·솔라나)나 매직에덴·오픈시 링크를 넣어 주세요', true); return; }
      const sn = sync.snap(S.drafts, ['nft:watch']), ch = S.drafts['nft:wch'], sh = S.sheet, d = await nftPost(b, '지켜보기에 넣었어요 — 바닥가는 곧 받아요');
      if (d && S.drafts['nft:wch'] === ch && S.sheet === sh && !sync.done(S.drafts, sn)) { const i = $('#nftWatch'); if (i) i.value = ''; if (S.sheet && S.sheet.k === 'nftw') uiSheetClose(); }
    },
    nftWatchOpen: el => uiSheetOpen('nftw', 'add', '지켜보기 추가', el),
    nftSpam: () => { S.nft.spamOpen = !S.nft.spamOpen; renderView(); },
    nftSpamMore: () => { const P = uiPgS(); P.nftsp = (P.nftsp | 0) + 1; renderView(); },
    nftHid: () => { S.nft.hidOpen = !S.nft.hidOpen; renderView(); },
    nftKeys: () => {
      sxGo('keys', '', { pre: () => { const su = window.__tjSetup; if (su && su.U) { su.U.panelOpen = true; su.U.where = 'keys'; su.U.xp = 'coingecko'; } }, hl: '[data-su="xp"][data-v="coingecko"]' });
      setTimeout(() => { try { const su = window.__tjSetup; if (su && su.render) su.render(); } catch (e) {  } }, 60);
    }
  });
  return {
    brokersBody, levDrawer, levHTML, nftLoad, oaDashLine, oaItems, oaNameTxt, oaNeed, oaTot, oaV, vOther
  };
};
