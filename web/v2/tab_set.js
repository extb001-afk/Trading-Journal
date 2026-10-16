'use strict';
(window.__tjTabs = window.__tjTabs || {}).set = function (X) {
  const {
    $, ago, alLoad, arr, CHAIN_KO, clearCache, DUST_OPTS, errTxt, esc, EX_NAMES, exLogo, fmtTs, fxNote, hs, IC, isISO, KST_MS, lockOut, logError,
    logosOff, LS, m, MK_RE, mN, nf, num, ofAuto, onbHidden, onUnauthorized, pad2, pctS, plainT, prTxt, PV_PROT, PVM, pvm, pvOn, pvW, px, q, render,
    renderView, revTxt, rkFix, S, scanText, short, sum, sv, sxAlertsBody, syncUrl, taxTip, thSys, toast, uiDate, uiFold, uiPaged, uiPageSize, uiPgBar,
    uiPgReveal, uiPgS, uiPgSlice, uiPick, venueLogo
  } = X;
  let AL_PRE, brokersBody, oaNeed;
  const __late = L => {
    if ('AL_PRE' in L) AL_PRE = L.AL_PRE;
    if ('brokersBody' in L) brokersBody = L.brokersBody;
    if ('oaNeed' in L) oaNeed = L.oaNeed;
  };
  const copyBtn = (v, lbl) => '<button class="cpy" data-a="copy" data-v="' + esc(v) + '" aria-label="' + (lbl || '주소 복사') + '" title="' + (lbl || '주소 복사') + '">' + IC.copy + '</button>';
  function gasRuleTxt(tg) {
    if (!tg) return '';
    if (tg.on === false) return '가스는 원가·실현에 넣지 않고 따로 보여 줘요(설정에서 켜면 전부 비용 처리)';
    return '가스는 전부 비용이에요 — 스왑 매수 가스는 취득가액(원가)에, 스왑 매도 가스는 그 매도의 수수료로, 매매 외 가스(실패·승인·전송·브릿지·LP)는 그날 실현에서 \'가스 비용\'으로 빠져요';
  }
  function gasSwitchHTML() {
    const tg = S.D.taxGas;
    if (!tg) return '';
    const on = tg.on !== false;
    return '<div class="srow"><div style="min-width:0"><b>가스를 원가·실현에 반영</b><div class="cap">' + (on ? '켬 · ' + esc(gasRuleTxt(tg)) + ' · 반영 ' + m(Math.min(num(tg.total), num(tg.inCost) + num(tg.inRealized) + num(tg.expense))) + ' / 온체인 가스 ' + m(num(tg.total)) : '끔 · 가스는 가스·수수료 탭에 따로 표시만 해요(실현·세금 명세는 가스 전 · 거래소 체결 수수료는 끔과 무관하게 원가·실현에 그대로)') + '</div></div><span class="sp"></span><button class="sw2' + (on ? ' on' : '') + '" data-a="gasCost" role="switch" aria-checked="' + on + '" aria-label="가스를 원가·실현에 반영"></button></div>';
  }
  const offcDesc = n => n + ' 사용자끼리 체인 밖 이체예요. 내 다른 ' + n + ' 계정과 주고받은 것이면 켜세요 — 보낸 코인의 원가가 돌아온 입금에 이어져요(내 계정으로 가정). 남에게 보낸 게 섞여 있으면 켜지 마세요.';
  function offcStat(o) {
    if (o.on) return '<span class="pvx">가정 중 · 돌아온 입금 ' + o.inhN + '/' + o.depN + '건 원가 이어받음' + (o.excessN ? ' · 보낸 것보다 많이 온 ' + o.excessN + '건은 초과분만 원가 미확인' : '') + (o.exclN ? ' · 남의 주소로 뺀 출금 ' + o.exclN + '건' : '') + '</span> · 이어받은 코인 원가 ' + m(o.inhCoin, { compact: true })
      + (o.leftN ? ' · 아직 안 돌아온 원가 ' + m(o.leftCost, { compact: true }) + ' <span class="pvx">(' + o.leftN + '묶음)</span>' : '');
    return '<span class="pvx">' + (o.answered ? '끔(아니요로 답함)' : '아직 답하지 않음 · 종전대로') + ' · 출금 ' + o.wdN + '건 · 입금 ' + o.depN + '건 · ' + o.syms + '종</span>' + (o.coinCost >= 1 ? ' · <span class="pvx">받는 주소 미상으로 빠진 코인 원가</span> ' + m(o.coinCost, { compact: true }) : '');
  }
  function offcSwitchHTML() {
    return (S.D.offc || []).map(o => '<div class="srow"><div style="min-width:0"><b>' + esc(o.name) + ' 오프체인 이체를 내 계정 간 이동으로 가정</b><div class="cap">' + esc(offcDesc(o.name)) + '</div><div class="cap num" style="margin-top:4px">' + offcStat(o) + '</div></div><span class="sp"></span>'
      + '<button class="sw2' + (o.on ? ' on' : '') + '" data-a="offcSelf" data-v="' + esc(o.ex) + '" role="switch" aria-checked="' + o.on + '" aria-label="' + esc(o.name + ' 오프체인 이체를 내 계정 간 이동으로 가정') + '"></button></div>').join('');
  }
  function offcAsk() {
    return (S.D.offc || []).filter(o => !o.answered && (o.wdN || o.depN)).map(o => '<div class="card offcban" role="region" aria-label="' + esc(o.name + ' 오프체인 이체 확인') + '"><div class="row gap8" style="align-items:flex-start;flex-wrap:wrap"><span class="aic a">' + IC.send + '</span>'
      + '<div style="min-width:0;flex:1"><b class="pvx">' + esc(o.name) + ' 오프체인 이체 ' + (o.wdN + o.depN) + '건 — 내 다른 ' + esc(o.name) + ' 계정과 주고받은 건가요?</b>'
      + '<div class="cap" style="margin-top:4px">' + esc(offcDesc(o.name)) + '</div><div class="cap num" style="margin-top:4px">' + offcStat(o) + '</div></div>'
      + '<div class="offcbtns"><button class="btn sm pri pvx" data-a="offcSelf" data-v="' + esc(o.ex) + '" data-m="on">내 계정 간 이동으로 가정</button><button class="btn sm pvx" data-a="offcNo" data-v="' + esc(o.ex) + '">아니요</button></div></div></div>').join('');
  }
  function offcGroup() {
    return (S.D.offc || []).filter(o => o.on).map(o => {
      const k = 'offc:' + o.ex, open = S.of.open.has(k), nm = esc(o.name);
      const head = '<div class="oh" role="button" tabindex="0" data-a="ofTog" data-k="' + esc(k) + '" aria-expanded="' + open + '"><div class="who"><span class="aic ok">' + IC.check + '</span><div style="min-width:0"><div class="row gap8"><b class="pvx ell">내 다른 ' + nm + ' 계정</b><span class="pill ok sm pvx">가정 중</span></div>'
        + '<div class="sub ell" title="' + esc(plainT(offcStat(o))) + '"><span class="pvx">오프체인 ' + o.wdN + '건 보냄 · ' + o.inhN + '건 돌아옴</span></div></div></div><span class="chev' + (open ? ' o' : '') + '">' + IC.chev + '</span></div>';
      if (!open) return '<div class="card of offcgrp">' + head + '</div>';
      const syms = o.bySym.slice(0, 20).map(b => '<div class="kv" style="font-size:13px"><span>' + esc(b.sym) + (b.stable ? ' <span class="cap">(액면)</span>' : '') + '</span><span class="num" style="margin-left:auto;text-align:right"><span class="pvx">' + num(b.wdN) + '건 보냄 · ' + num(b.inhN) + '건 돌아옴</span> · 보낸 원가 ' + m(num(b.wdCost), { compact: true }) + ' · 이어받음 ' + m(num(b.inhCost), { compact: true }) + (num(b.leftCost) >= 1 ? ' · 남음 ' + m(num(b.leftCost), { compact: true }) : '') + '</span></div>').join('');
      const adr = o.byAddr.slice(0, 20).map(b => '<div class="kv" style="font-size:13px;align-items:center;flex-wrap:wrap;gap:6px">' + (b.addr ? '<button class="addr mono" data-a="copy" data-v="' + esc(b.addr) + '" title="복사 · ' + esc(b.addr) + '">' + esc(short(b.addr)) + '</button>' : '<span class="cap">받는 주소 없음</span>')
        + '<span class="num cap"><span class="pvx">' + num(b.n) + '건</span> · 원가 ' + m(num(b.cost), { compact: true }) + '</span>' + (b.excl ? '<span class="pill w sm pvx">남의 주소로 뺌</span>' : '') + '<span class="sp"></span>'
        + (b.addr ? '<button class="btn sm pvx" data-a="offcAddr" data-v="' + esc(o.ex) + '" data-k="' + esc(b.addr) + '" data-m="' + (b.excl ? 'off' : 'on') + '">' + (b.excl ? '되돌리기(내 계정으로 가정)' : '이 주소는 남이에요') + '</button>' : '') + '</div>').join('');
      const body = '<div class="ob"><div class="cap num" style="margin-bottom:6px">' + offcStat(o) + '</div><div class="cap pvx" style="margin-bottom:8px">오프체인 출금 원가를 같은 코인의 뒤에 돌아온 ' + nm + ' 오프체인 입금이 먼저 보낸 것부터 이어받아요(가정). 이어받은 원가로 계산된 매도엔 ‘오프체인 이어받음(내 계정으로 가정)’이 붙어요.</div>'
        + '<div class="blk"><div class="ttl">코인별</div>' + syms + '</div><div class="blk" style="margin-top:10px"><div class="ttl">받는 주소별 — 남에게 보낸 주소면 빼세요(그 출금은 받는 주소 미상으로 돌아가요)</div>' + adr + '</div>'
        + '<div class="row" style="margin-top:12px"><span class="sp"></span><button class="btn sm pvx" data-a="offcSelf" data-v="' + esc(o.ex) + '">가정 끄기(종전대로)</button></div></div>';
      return '<div class="card of offcgrp open">' + head + body + '</div>';
    }).join('');
  }
  const SXI = {
    key: sv('<circle cx="8" cy="15" r="4"/><path d="M10.8 12.2L20 3M16 7l3 3M14 9l2 2"/>'),
    bell: sv('<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/>'),
    spark: sv('<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>'),
    db: sv('<ellipse cx="12" cy="5.5" rx="8" ry="2.5"/><path d="M4 5.5v13c0 1.4 3.6 2.5 8 2.5s8-1.1 8-2.5v-13M4 12c0 1.4 3.6 2.5 8 2.5s8-1.1 8-2.5"/>'),
    lock: sv('<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>'),
    sliders: sv('<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>'),
    pulse: sv('<path d="M3 12h4l3-8 4 16 3-8h4"/>'),
    plus: sv('<path d="M12 5v14M5 12h14"/>')
  };
  const SX_META = {
    keys: { t: '연결 · 키', ic: 'key', c: 'w' }, wallets: { t: '지갑 · 주소', ic: 'wallet', c: 'v' }, alerts: { t: '알림', ic: 'bell', c: 'a' },
    display: { t: '화면 · 표시', ic: 'eye', c: 'ok' }, cost: { t: '원가 계산', ic: 'scale', c: 'g' }, ai: { t: 'AI 리뷰', ic: 'spark', c: 'v' },
    data: { t: '데이터 · 수집', ic: 'db', c: 'g' }, account: { t: '계정 · 로그인', ic: 'lock', c: 'g' }, advanced: { t: '고급', ic: 'sliders', c: 'g' } };
  const SX_GROUPS = [['연결', ['keys', 'wallets', 'alerts']], ['보기 · 계산', ['display', 'cost', 'ai']], ['데이터 · 계정', ['data', 'account', 'advanced']]];
  const SX_SUBS = {
    keys: { exchanges: '거래소 조회 키', telegram: '텔레그램 알림 봇' },
    wallets: { perp: '퍼프 덱스 주소', deposits: '거래소 입금 주소', rabby: 'Rabby 대조', whitelist: '발신 주소 화이트리스트', names: '추적 안 하는 주소에 이름', tokens: '토큰 매핑' },
    cost: { rules: '매칭 규칙' }, data: { history: '과거 데이터 더 가져오기', limits: '수집 한계' }, advanced: { brokers: '증권사 연결' } };
  const sxIcon = k => SXI[k] || IC[k] || '';
  const sxPill = (c, t) => '<span class="pill ' + c + ' sm pvx">' + t + '</span>';
  const sxUsd = v => '$<span class="sx-usd">' + (S.hide || S.rand ? '<span class="pv">' + PVM.usd + '</span>' : nf('en-US').format(num(v))) + '</span>';
  const sxDust = () => sxUsd(S.dust);
  const sxId = k => String(k == null ? '' : k).replace(/[^\w-]/g, '_');
  const mqW = (() => { try { return window.matchMedia('(min-width: 1000px)'); } catch (e) { return null; } })();
  const sxWide = () => !!(mqW && mqW.matches);
  function sxParse(h) {
    const p = String(h == null ? '' : h).replace(/^#/, '').split('/');
    const tab = p[0] || '';
    if (tab !== 'settings') return { tab, sec: '', sub: '' };
    const sec = Object.prototype.hasOwnProperty.call(SX_META, p[1]) ? p[1] : '';
    const sub = sec && SX_SUBS[sec] && Object.prototype.hasOwnProperty.call(SX_SUBS[sec], p[2]) ? p[2] : '';
    return { tab, sec, sub };
  }
  const sxHash = (sec, sub) => 'settings' + (sec ? '/' + sec + (sub ? '/' + sub : '') : '');
  const sxDepth = r => (r.sec ? (r.sub ? 2 : 1) : 0);
  const sxLast = () => { const v = LS.get('tj_v2_sxsec'); return Object.prototype.hasOwnProperty.call(SX_META, v) ? v : 'keys'; };
  const suU = () => { try { const su = window.__tjSetup; return su && su.U ? su.U : null; } catch (e) { return null; } };
  const suSt = () => { const U = suU(); return U && U.st && U.st.explorers && U.st.exchanges ? U.st : null; };
  function sxKeys() {
    const st = suSt();
    if (!st) return null;
    const XO = ['helius', 'etherscan', 'alchemy', 'ankr', 'coingecko', 'opensea'];
    const NODE = st.nodes && typeof st.nodes === 'object' ? Object.keys(st.nodes) : [];
    const xp = st.explorers, ex = st.exchanges, xk = Object.keys(xp).filter(k => !NODE.includes(k) || (xp[k] && xp[k].set) || (k === 'alchemy' && st.evmNeedsAlchemy) || (k === 'ankr' && st.evmNeedsAnkr)).sort((a, b) => (XO.indexOf(a) + 1 || 99) - (XO.indexOf(b) + 1 || 99)), ek = Object.keys(ex);
    const empty = xk.filter(k => !(xp[k] && xp[k].set)), exSet = ek.filter(k => ex[k] && ex[k].set), tg = st.telegram || {};
    const P = st.perp || {}, pw = arr(P.wallets), stt = P.state || {};
    const pBad = pw.filter(w => { const s9 = ((stt[w.dex] || {}).accts || {})[w.address] || {}; return s9.err || (stt[w.dex] || {}).wait; }).length;
    const pBy = {}; pw.forEach(w => { pBy[w.name || w.dex] = (pBy[w.name || w.dex] || 0) + 1; });
    return { xs: xk.length - empty.length, xn: xk.length, es: exSet.length, en: ek.length, ek, exSet, empty, emptyNames: empty.map(k => String((xp[k] && xp[k].name) || k).replace(/\s*\(.*$/, '')),
      tg: !!tg.connected, tgBot: String(tg.bot || ''), tgChat: String(tg.chatName || ''), pN: pw.length, pBad, pErr: P.error ? String(P.error) : '', pBy, apply: st.apply || {} };
  }
  const sxHealthSum = () => { try { const T = window.TJHealth; return T && typeof T.summary === 'function' ? T.summary() : null; } catch (e) { return null; } };
  const alD = () => { const d = S.al && S.al.d; return d && d.prefs && typeof d.prefs === 'object' && d.prefs.cats && typeof d.prefs.cats === 'object' && Array.isArray(d.cats) ? d : null; };
  const alTier = c => (c && (c.tier === 'now' || c.tier === 'daily' || c.tier === 'web') ? c.tier : c && c.crit ? 'now' : 'daily');
  const alOn = (d, k) => (((d && d.prefs && d.prefs.cats) || {})[k] || 'on') !== 'off';
  const sxAlCount = d => { const cs = arr(d && d.cats).filter(c => alTier(c) !== 'web');
    return { on: cs.filter(c => alOn(d, c.key)).length, n: cs.length, now: cs.filter(c => alTier(c) === 'now' && c.key !== 'arrive' && alOn(d, c.key)).length, daily: cs.some(c => alTier(c) === 'daily' && alOn(d, c.key)) }; };
  function sxWalRows() {
    const st = suSt(), by = new Map(), out = [];
    S.D.wallets.forEach(w => { const r = { k: String(w.key || w.addr || ''), w, s: null, alias: String(w.alias || '') }; by.set(r.k, r); out.push(r); });
    if (st) {
      const wait = [];
      arr(st.wallets).forEach(s => { const a = String(s.address || ''), k = s.kind === 'sol' ? a : a.toLowerCase(), r = by.get(k) || by.get(a);
        if (r) r.s = s; else { const r2 = { k, w: null, s, alias: String(s.label || ''), wait: true }; by.set(k, r2); wait.push(r2); } });
      out.unshift(...wait);
      arr(st.chainWallets).forEach(c => out.push({ k: c.chain + ':' + c.key, w: null, s: null, cw: c, alias: String(c.label || '') }));
    }
    return out;
  }
  const sxSlotWait = () => '<div class="sx-wait" aria-hidden="true"><i></i><i></i><i></i></div>';
  const sxSeg = (a, opts, label, full) => '<span class="seg sx-seg' + (full ? ' full' : '') + '" role="group" aria-label="' + esc(label) + '">'
    + opts.map(o => '<button data-a="' + a + '" data-v="' + esc(o[0]) + '" class="' + (o[2] ? 'on' : '') + '" aria-pressed="' + !!o[2] + '">' + o[1] + '</button>').join('') + '</span>';
  const rkCtl = () => {
    const f = rkFix();
    if (S.rand) return '<div class="row gap8 rkrow" style="margin-top:8px;flex-wrap:wrap"><span class="cap" style="min-width:0;flex:1 1 200px">배수: ' + (f ? '고정됨 — 값은 랜덤값을 끄면 보여요' : '열 때마다 무작위') + '</span>'
      + (f ? '<button class="btn sm" data-a="rkClear" style="margin-left:auto">고정 풀기</button>' : '') + '</div>';
    return '<div class="frm" style="margin-top:8px"><input class="field num" inputmode="decimal" placeholder="배수 고정 (예: 2.4)" data-draft="rk" data-enter="rkSet" aria-label="랜덤값 배수 고정" style="max-width:170px" value="' + (f ? esc(String(f)) : '') + '">'
      + '<button class="btn sm" data-a="rkSet">고정</button>' + (f ? '<button class="btn sm" data-a="rkClear">풀기</button>' : '') + '</div>'
      + '<div class="cap">비우면 열 때마다 무작위 · 고정하면 캡처 여러 장의 숫자가 서로 맞아요(배수를 아는 사람은 실제 값을 계산할 수 있어요) · 0.2~5 (0.8~1.25 제외)</div>';
  };
  const sxSw = (a, on, label, attrs) => '<button class="sw2' + (on ? ' on' : '') + '" data-a="' + a + '" role="switch" aria-checked="' + !!on + '" aria-label="' + esc(label) + '"' + (attrs || '') + '></button>';
  const sxGrp = (t, cap) => '<div class="sx-grp pvx">' + t + (cap ? '<span class="cap">' + cap + '</span>' : '') + '</div>';
  function sxIt(id, t, cap, right, o) {
    o = o || {};
    const tx = '<span class="tx"><b>' + t + '</b>' + (cap ? '<span class="cap">' + cap + '</span>' : '') + '</span>';
    if (o.href) return '<a class="sx-it sx-lk" id="' + id + '" href="' + o.href + '">' + (o.lead || '') + tx + (right || '') + '<span class="sx-ch">' + IC.right + '</span></a>';
    const open = !!o.exp && S.set.open.has(id);
    const head = o.exp ? '<button class="sx-itx" data-a="sxTog" data-v="' + id + '" aria-expanded="' + open + '" aria-controls="' + id + '-d">' + tx + (o.val || '') + '<span class="sx-ch sx-chd' + (open ? ' o' : '') + '">' + IC.chev + '</span></button>'
      : '<div class="sx-itx">' + tx + (o.val || '') + '</div>';
    return '<div class="sx-it' + (open ? ' open' : '') + (o.cls ? ' ' + o.cls : '') + '" id="' + id + '">' + (o.lead || '') + head + (right ? '<span class="sx-r">' + right + '</span>' : '')
      + (open ? '<div class="sx-itd" id="' + id + '-d">' + o.exp() + '</div>' : '') + '</div>';
  }
  const sxTrow = (id, ic, c, t, cap, btn) => '<div class="sx-trow" id="' + id + '"><span class="aic ' + c + '">' + sxIcon(ic) + '</span><span class="tx"><b>' + t + '</b>' + (cap ? '<span class="cap">' + cap + '</span>' : '') + '</span>' + btn + '</div>';

  const legacyOn = k => !!(S.D && S.D.legacy && S.D.legacy[k]);
  function sxSum(k) {
    const D = S.D, K = sxKeys(), wait = '불러오는 중…';
    if (k === 'keys') return K ? '탐색기 ' + K.xs + '/' + K.xn + ' · 거래소 ' + K.es + '/' + K.en + ' · 텔레그램' + (K.tg ? '' : ' 미연결') : wait;
    if (k === 'wallets') return '지갑 ' + sxWalRows().length + (K ? ' · 퍼프 ' + K.pN : '') + ' · 입금 주소 ' + D.deposits.length;
    if (k === 'alerts') {
      const L = S.al, d = alD();
      if (!d) return L && L.st === 'none' ? '텔레그램 알림' : L && (L.st === 'err' || L.d) ? '불러오지 못했어요' : wait;
      const c = sxAlCount(d), dt = String((d.prefs.th || {}).digest_time || '');
      return esc(d.preset === 'custom' ? '직접 설정' : (AL_PRE[d.preset] || d.preset)) + ' · 즉시 ' + c.now + '가지 · ' + (c.daily ? '하루 요약' + (dt ? ' ' + esc(dt) : '') : '하루 요약 끔');
    }
    if (k === 'display') {
      const light = document.documentElement.getAttribute('data-theme') === 'light', glob = document.documentElement.getAttribute('data-scheme') === 'global';
      return (light ? '라이트' : '다크') + ' · ' + (S.cur === 'USD' ? '$' : '₩') + ' · ' + (glob ? '글로벌' : '국내식') + ' · 소액 ' + (S.dust > 0 ? sxDust() : '전체');
    }
    if (k === 'cost') return (D.taxGas ? '가스 ' + (D.taxGas.on !== false ? '켬' : '끔') + ' · ' : '') + (D.firstSeen ? '시가 ' + (D.firstSeen.on ? '켬' : '끔') + ' · ' : '') + '평균가 ' + (D.fallbackOn ? '켬' : '끔') + (D.costOv.length ? ' · 지정 ' + D.costOv.length : '');
    if (k === 'ai') {
      const rl = D.reviewLen, rf = D.reviewFill;
      if (!rl) return '이 서버는 분량 설정 없음';
      const nm = x => ((REV_LEN.daily.find(y => y[0] === x) || [x, x])[1]);
      return (rl.daily === rl.weekly ? '일간·주간 ' + nm(rl.daily) : '일간 ' + nm(rl.daily) + ' · 주간 ' + nm(rl.weekly)) + (rf ? ' · ' + (num(rf.parallel) > 1 ? '동시에 ' + num(rf.parallel) + '건' : rf.order === 'oldest' ? '오래된 날부터' : '최근부터') : '');
    }
    if (k === 'data') { const bs = D.bfSince; return sxChainN() + '체인 · 거래소 ' + D.exN + (bs && bs.windowStart ? ' · ' + esc(String(bs.windowStart).slice(5).replace('-', '/').replace(/^0/, '').replace('/0', '/')) + '부터' : ''); }
    if (k === 'account') {
      const c = S.auth, d = c && c.d;
      if (!d) return c && (c.st === 'none' || c.st === 'err') ? '이 서버는 로그인 없음' : wait;
      return d.enabled ? (d.authed ? esc(fmtTs(d.exp).slice(0, 5)) + '까지 · 기기 ' + num(d.sessions) : '로그인 필요') : (d.demo ? '데모 모드' : '꺼짐 · 누구나 볼 수 있음');
    }
    if (k === 'advanced') return '선물 · 증권사(실험) · 적용 방식';
    return '';
  }
  function sxBadge(k) {
    const D = S.D, K = sxKeys();
    if (k === 'keys') return K ? (K.empty.length ? sxPill('w', '빈 키 ' + K.empty.length) : sxPill('ok', '모두 저장')) : '';
    if (k === 'wallets') { const n = sxWalRows().filter(r => r.wait).length; return n ? sxPill('a', '수집 대기 ' + n) : ''; }
    if (k === 'alerts') { const d = alD(); return d ? (d.tg && d.tg.connected ? sxPill('ok', '연결됨') : sxPill('g', '미연결')) : ''; }
    if (k === 'display') return sxPill('g', '이 기기');
    if (k === 'cost') { const n = arr(D.offc).filter(o => o.on).length; return n ? sxPill('a', '가정 ' + n) : ''; }
    if (k === 'ai') { const P = D.reviewProg; if (D.reviewPause && D.reviewPause.on) return sxPill('w', '자동 멈춤'); return D.reviewLen ? (P && arr(P.runs).length ? sxPill('a', '쓰는 중') : sxPill('g', '대기 없음')) : ''; }
    if (k === 'data') return D.bc ? (D.bcConfirmed.length ? sxPill('w', '불일치 ' + D.bcConfirmed.length) : sxPill('ok', '불일치 0')) : '';
    if (k === 'account') { const d = S.auth && S.auth.d; return d ? (d.enabled ? sxPill('ok', '켜짐') : sxPill('g', '꺼짐')) : ''; }
    return '';
  }
  function sxChainN() { const s = new Set(); S.D.wallets.forEach(w => String(w.chains || '').split(/\s*[,·\/]\s*/).filter(Boolean).forEach(c => s.add(c))); return s.size; }

  function sxHero() {
    const K = sxKeys(), al = alD(), alc = al ? sxAlCount(al) : null, H = sxHealthSum(), nW = sxWalRows().length;
    const n = (k, v, t) => (v == null ? '<b class="sx-dim">—</b>' : '<b data-sxk="' + k + '" data-sxv="' + v + '/' + (t == null ? '' : t) + '">' + v + (t != null ? '<small>/' + t + '</small>' : '') + '</b>');
    const big = '<div class="sx-big3">'
      + '<a href="#settings/keys" class="sx-bn">' + n('keys', K ? K.xs + K.es : null, K ? K.xn + K.en : null) + '<span>연결된 키</span></a>'
      + '<a href="#settings/wallets" class="sx-bn">' + n('wal', nW) + '<span>추적 지갑</span></a>'
      + '<a href="#settings/alerts" class="sx-bn">' + n('al', alc ? alc.on : null, alc ? alc.n : null) + '<span>켜진 알림</span></a></div>';
    const rows = [];
    if (K && K.empty.length) rows.push(sxTrow('sx-att-keys', 'key', 'w', '빈 키 ' + K.empty.length + '개', esc(K.emptyNames.length > 2 ? K.emptyNames.slice(0, 2).join(' · ') + ' 외 ' + (K.emptyNames.length - 2) + '개' : K.emptyNames.join(' · ')), '<button class="btn sm pri" data-a="sxKeyFill">키 넣기</button>'));
    if (H && H.loaded && H.crit + H.warn > 0) rows.push(sxTrow('sx-att-health', 'pulse', (H.crit ? 'e' : 'w') + ' sx-live', '상태 · ' + esc(H.label), H.known ? '닫은 주의 ' + H.known : H.ext ? '외부 서비스 원인 포함' : '60초마다 점검한 결과', '<button class="btn sm" data-a="sxHealth">상태 패널</button>'));
    if (K && !K.tg) rows.push(sxTrow('sx-att-tg', 'bell', 'w', '알림 봇 미연결', '오류가 나도 텔레그램으로 알릴 곳이 없어요', '<a class="btn sm" href="#settings/keys/telegram">연결</a>'));
    const ok = K && H && H.loaded && !rows.length ? '<div class="sx-okl"><span class="dot"></span>손댈 것이 없어요' + (H.known ? ' · 알려진 사항 ' + H.known + '건' : '') + '</div>' : '';
    return '<section class="card sx-hero pvx" aria-label="설정 요약">' + big + (rows.length || ok ? '<div class="sx-att">' + rows.join('') + ok + '</div>' : '') + '</section>';
  }
  const sxSafe = (f, k) => { try { return f(k); } catch (e) { logError('[tj] 설정 요약 실패(' + k + ')', e); return ''; } };
  function sxNavRow(k, cur, wide) {
    const M = SX_META[k], on = cur === k;
    return '<a class="sx-row pvx' + (on ? ' on' : '') + '" href="#' + sxHash(k) + '" data-sx-sec="' + k + '"' + (on ? ' aria-current="page"' : '') + '><span class="aic ' + M.c + '">' + sxIcon(M.ic) + '</span>'
      + '<span class="tx"><b>' + M.t + '</b><span class="cap">' + sxSafe(sxSum, k) + '</span></span>' + sxSafe(sxBadge, k) + (wide ? '' : '<span class="sx-ch">' + IC.right + '</span>') + '</a>';
  }
  const sxNav = (cur, wide) => SX_GROUPS.map(g => '<div class="sx-glab">' + g[0] + '</div>' + (wide ? '' : '<div class="card sx-list">') + g[1].map(k => sxNavRow(k, cur, wide)).join('') + (wide ? '' : '</div>')).join('');

  const SX = {
    keys: {
      cap: '비밀값은 서버 .env(600)에만 · 화면엔 •••• 만',
      act: () => (onbHidden() ? '<button class="btn sm" data-a="onbShow">처음 설정 안내 다시 보기</button> ' : '') + '<button class="btn sm" data-su="wizard">설정 마법사 열기</button>',
      body(wide) {
        const K = sxKeys(), tg = K && K.tg;
        const exRow = sxIt('sx-keys-ex', '거래소 ' + (K ? K.en : '') + '곳' + (K && K.exSet.length ? ' <span class="sx-vst" aria-hidden="true">' + K.exSet.map(k => exLogo(k)).join('') + '</span>' : ''), '조회 전용 키 · 입금 주소 자동 수집',
          K ? sxPill(K.es ? 'ok' : 'g', K.es + '/' + K.en + ' 연결') : '', { href: '#settings/keys/exchanges' });
        const ip = '<div class="sx-it" id="sx-keys-ip"><div class="sx-itx"><span class="tx"><b>이 서버 공인 IP</b><span class="cap">거래소 키 IP 허용 목록에 넣을 값</span></span></div><span class="sx-r" data-su-slot="ip"></span></div>';
        const tgRow = '<div class="sx-it sx-lk2" id="sx-keys-tg"><a class="sx-itx sx-stretch" href="#settings/keys/telegram"><span class="tx"><b>알림 봇</b><span class="cap">'
          + (K ? (tg ? (K.tgBot ? '@' + ownH(K.tgBot) + (K.tgChat ? ' → ' + ownH(K.tgChat) : '') : '연결됨') + ' · 알림 종류는 ‘알림’에서' : '연결 안 됨 · BotFather 토큰으로 연결해요') : '불러오는 중…') + '</span></span></a>'
          + (K ? sxPill(tg ? 'ok' : 'g', tg ? '연결됨' : '미연결') : '') + (tg ? '<button class="btn sm sx-up" data-su="tgtest">테스트</button>' : '') + '<span class="sx-ch">' + IC.right + '</span></div>';
        return '<div class="sx-card sx-cols"><div>' + sxGrp('탐색기 키') + '<div class="sx-slot sx-keyslot" data-su-slot="keys">' + sxSlotWait() + '</div></div>'
          + '<div>' + sxGrp('거래소 조회 키') + exRow + ip + sxGrp('텔레그램') + tgRow + '</div></div>'
          + (wide ? '' : '<div class="sx-foot">' + (onbHidden() ? '<button class="btn sm" data-a="onbShow">처음 설정 안내 다시 보기</button>' : '') + '<button class="btn sm" data-su="wizard">설정 마법사 열기</button><span class="cap">비밀값은 서버 .env(600)에만</span></div>');
      },
      subs: {
        exchanges: { cap: '조회(읽기) 권한만 켠 키 · 이 봇은 주문·출금을 하지 않아요 · 저장하면 1분 안에 동기화', body: () => '<div class="sx-card"><div class="sx-slot sx-exslot" data-su-slot="exchanges">' + sxSlotWait() + '</div></div>' },
        telegram: { cap: '연결하지 않아도 모든 기능이 동작해요 · 연결한 순간부터 새 알림만', body: () => '<div class="sx-card"><div class="sx-slot sx-tgslot" data-su-slot="telegram">' + sxSlotWait() + '</div></div>' }
      }
    },
    wallets: {
      cap: '주소만 읽어요 — 서명·송금 권한은 요청하지 않아요',
      body: sxWalletsBody,
      subs: {
        perp: { cap: '주소만으로 포지션·거래·펀딩·청산 · 담보는 총자산에 더하지 않아요(표시 전용)', body: () => '<div class="sx-card"><div class="sx-slot sx-perpslot" data-su-slot="perp">' + sxSlotWait() + '</div></div>' },
        deposits: { cap: '온체인 전송의 목적지가 이 주소면 거래소 입금으로 봐요', body: sxDepBody },
        rabby: { cap: 'Rabby(DeBank) 합과 봇 합 · 봇이 모르는 몫(추적 안 하는 체인·프로토콜·놓친 토큰)은 총자산에 ‘Rabby 기준’으로 · 스캠 제외 · 지갑마다 하루 1회', body: wide => rbAddedHTML(wide) + '<div class="sx-card">' + rabbyBody() + '</div>' },
        whitelist: { cap: '믿을 수 있는 발신 주소(추적 안 하는 내 지갑 등)는 스팸·에어드랍 판정에서 빠져요', body: sxWlBody },
        names: { cap: '화면에 보일 이름만 붙여요 — 추적은 하지 않아요', body: sxNamesBody },
        tokens: { cap: '심볼은 위조가 가능해 컨트랙트 주소(CA)로 매칭해요 · 읽기 전용', body: sxTokBody }
      }
    },
    alerts: { cap: '서버에 저장 — 모든 기기에서 같아요 · 텔레그램 연결은 ‘연결 · 키’에서', body: sxAlertsBody },
    display: { cap: '이 기기에만 저장돼요', body: sxDisplayBody },
    cost: { cap: '바꾸면 원장을 다시 계산해요 — 원장 자체는 그대로', body: sxCostBody, subs: { rules: { cap: '수집기·원장이 지금 쓰는 값 · 읽기 전용', body: sxRulesBody } } },
    ai: { cap: '서버에 저장 — 새로 쓰는 리뷰부터 적용돼요', body: sxAiBody },
    data: { cap: '수집기가 보고한 상태 · 수집 주기는 서버가 관리해요', body: sxDataBody,
      subs: { history: { cap: '더 이른 날짜를 고르면 그 구간만 더 가져오고, 끝나면 원장을 자동으로 다시 계산해요', body: sxHistBody },
        limits: { cap: '옛 기록을 어디까지 주는지 · 봇이 실제로 어디부터 가져왔는지(하루 한 번 갱신)', body: () => '<div class="sx-card">' + coverageBody() + '</div>' } } },
    account: { cap: '로컬 웹 로그인(비밀번호 하나) · 켜기·끄기는 config.json web.login', body: () => '<div class="sx-card">' + loginBody() + '</div>' },
    advanced: { cap: '실험 기능 · 설정을 바꾼 뒤 적용되는 방식', body: sxAdvBody,
      subs: { brokers: { cap: '보유 종목·예수금을 읽기만 · 미검증(실험 안 함) · 켜기 = 서버 config.json brokers', body: () => '<div class="sx-card">' + brokersBody() + '</div>' } } }
  };

  function sxWalletsBody() {
    const D = S.D, K = sxKeys(), rows = sxWalRows(), U = suU();
    const addOpen = S.set.open.has('wadd') || !!(U && (U.d && U.d.w_addr || U.wRes || (U.busy && U.busy.wadd)));
    const big = '<div class="sx-tiles pvx"><div><b>' + rows.length + '</b><span>추적 지갑</span></div><div><b>' + (K ? K.pN : '—') + '</b><span>퍼프 덱스</span></div><div><b>' + D.deposits.length + '</b><span>입금 주소</span></div></div>';
    const acts = '<div class="sx-acts"><button class="btn sm' + (addOpen ? '' : ' pri') + '" data-a="sxTog" data-v="wadd" aria-expanded="' + addOpen + '" aria-controls="sx-wallets-add">' + (addOpen ? IC.close + ' 추가 닫기' : SXI.plus + ' 지갑 추가') + '</button>'
      + '<a class="btn sm" href="#settings/wallets/perp">' + SXI.plus + ' 퍼프 덱스 주소</a></div>';
    const add = addOpen ? '<div class="sx-card sx-add" id="sx-wallets-add"><div class="sx-slot sx-waddslot" data-su-slot="wadd">' + sxSlotWait() + '</div></div>' : '';
    const nw = newWallets(), dup = {}; rows.forEach(r => { dup[r.alias] = (dup[r.alias] || 0) + 1; });
    if (S.set.walAll) { S.set.walAll = false; if (S.set.walOpen) { const k9 = S.set.walOpen; uiPgReveal('sxw', r => !!r && r.k === k9); } else delete uiPgS().sxw; }
    const LIM = 5, q = S.set.walQ || '', all = !!q, pgW = uiPgSlice('sxw', rows), pgA = pgW.from, pgB = pgW.from + pgW.rows.length;
    const shown = rows.filter(r => !sxWalHit(r, q)).length;
    const list = rows.length ? rows.map((r, i) => sxWalRow(r, dup, nw, i < pgA || i >= pgB, q, i)).join('') : '<div class="sx-empty">추적 중인 지갑이 없어요 · ‘지갑 추가’로 넣어요</div>';
    const search = rows.length > LIM ? '<label class="sx-qb sx-wq">' + IC.search + '<input class="sx-qi" type="search" id="sxWq" data-input="walq" placeholder="지갑 이름·주소 찾기" aria-label="지갑 이름·주소 찾기" value="' + esc(q) + '" autocomplete="off" spellcheck="false" autocapitalize="off"></label>' : '';
    const more = pgW.last > 0 ? '<div class="sx-more"' + (q ? ' hidden' : '') + '>' + uiPgBar('sxw', rows.length, { unit: '개' }) + '</div>' : '';
    const listCard = '<div class="sx-card" id="walCard" data-pgh="sxw">' + sxGrp('추적 지갑', '이름을 누르면 바로 바꿔요 · 화면 전용') + search
      + '<div class="sx-wl' + (all ? ' all' : '') + '" id="sxWl">' + list + '<div class="sx-empty sx-nomatch"' + (q && rows.length && !shown ? '' : ' hidden') + '>맞는 지갑이 없어요</div></div>' + more + '</div>';
    const rb = D.rabby, rbW = rb ? arr(rb.wallets) : [], wl = D.whitelist || S.wl;
    const rbGap = rbW.filter(w => w.gapSince).length;
    const perpCap = K ? (K.pErr ? '설정을 읽지 못했어요' : K.pN ? Object.keys(K.pBy).map(n9 => esc(n9) + ' ' + K.pBy[n9] + '개').join(' · ') + ' · 수집 중' : '주소만으로 포지션·펀딩·청산 · 키 필요 없음') : '불러오는 중…';
    const mg = '<div class="sx-card">' + sxGrp('주소 관리')
      + sxIt('sx-wallets-perp', '퍼프 덱스 주소', perpCap, K && K.pN ? sxPill(K.pBad ? 'w' : 'ok', K.pBad ? '지연 ' + K.pBad : '정상') : '', { href: '#settings/wallets/perp' })
      + sxIt('sx-wallets-dep', '거래소 입금 주소', '거래소 키로 자동 수집 · 이 주소로 보내면 입금', '<span class="sx-val num">' + D.deposits.length + '</span>', { href: '#settings/wallets/deposits' })
      + (rbW.length ? sxIt('sx-wallets-rabby', 'Rabby 대조', '지갑 ' + rbW.length + '개 · 하루 1회 · 봇과 차이 비교', rbGap ? sxPill('w', '차이 ' + rbGap) : '<span class="sx-val num">' + rbW.length + '</span>', { href: '#settings/wallets/rabby' }) : '')
      + sxIt('sx-wallets-wl', '발신 주소 화이트리스트', '내 다른 지갑 → 스팸 판정 제외', '<span class="sx-val num">' + (wl ? wl.length : '—') + '</span>', { href: '#settings/wallets/whitelist' })
      + sxIt('sx-wallets-names', '추적 안 하는 주소에 이름', '화면 표시용 이름만', '', { href: '#settings/wallets/names' })
      + sxIt('sx-wallets-tok', '토큰 매핑', '컨트랙트 ↔ 거래소 티커 · 읽기 전용', '<span class="sx-val num">' + D.aliases.length + '</span>', { href: '#settings/wallets/tokens' }) + '</div>';
    const tierCard = '<div class="sx-card" id="sx-wallets-tier">' + sxGrp('확인 주기 · 예상 사용량', '오래 안 쓴 주소도 1시간마다 확인해요 · 내가 보내면 바로 지금 주기') + '<div class="sx-slot sx-tierslot" data-su-slot="tier">' + sxSlotWait() + '</div></div>';
    const chainCard = '<div class="sx-card" id="sx-wallets-chains"><div class="sx-slot sx-chainslot" data-su-slot="chains">' + sxSlotWait() + '</div></div>';
    return big + acts + add + listCard + mg + chainCard + tierCard;
  }
  const sxWalHay = r => { if (r.cw) return (r.alias + ' ' + (r.cw.display || '') + ' ' + (r.cw.name || '')).toLowerCase();
    const w = r.w, s = r.s, a = w ? w.addr : s && s.address; return (r.alias + ' ' + (a || '') + ' ' + (w ? w.chains : arr(s && s.chains).join(' '))).toLowerCase(); };
  const sxWalHit = (r, q) => !!q && sxWalHay(r).indexOf(String(q).toLowerCase().trim()) < 0;
  function sxAliasIsAddr(al, addr) {
    const a = String(al || '').trim().toLowerCase(), d = String(addr || '').trim().toLowerCase();
    if (!a || !d) return false;
    if (a === d) return true;
    const m9 = a.match(/^([0-9a-z]{3,})(?:…|\.\.\.)([0-9a-z]{3,})$/);
    return !!m9 && d.indexOf(m9[1]) === 0 && d.slice(-m9[2].length) === m9[2];
  }
  function sxWalRow(r, dup, nw, more, q, i) {
    if (r.cw) return sxCwRow(r, more, q, i);
    const w = r.w, s = r.s, addr = String(w ? w.addr : s.address || ''), sol = s ? s.kind === 'sol' : !/^0x/i.test(addr);
    const chains = w ? String(w.chains || '').split(/\s*[,·\/]\s*/).filter(Boolean) : arr(s.chains).map(c => CHAIN_KO[c] || c);
    const isNew = nw.has(r.k) || !!(s && nw.has(s.address)) || !!(w && nw.has(w.addr));
    const recon = !!(s && arr(s.reconDone).length), open = S.set.walOpen === r.k, ed = w && S.aliasEdit === (w.key || w.addr);
    const tag = r.wait ? sxPill('g', '수집 대기') : isNew ? sxPill('w', '새로 추가') : recon ? sxPill('w', '재구축 필요') : dup[r.alias] > 1 ? sxPill('a', sol ? 'Solana' : 'EVM') : '';
    const cap = (sol ? 'Solana' : 'EVM ' + chains.length + '체인') + ' · ' + (w ? esc(scanText(w.last)) : (s && s.applyWait) || ofAuto() ? '곧 자동으로 수집 시작' : '수집기를 다시 시작하면 수집해요');
    const det = !open ? '' : '<div class="sx-wd" id="sxwd' + i + '"><div class="sx-wa"><span class="mono">' + esc(addr) + '</span>' + copyBtn(addr) + '</div>'
      + '<div class="chn">' + chains.map(c => '<span class="pill g sm">' + esc(c) + '</span>').join(' ') + '</div>'
      + (recon ? '<div class="cap wtxt">기초잔고 대조 뒤 추가된 체인(' + esc(arr(s.reconDone).map(c => CHAIN_KO[c] || c).join(', ')) + ') — 옛 기록 수집이 끝난 뒤 재구축하면 과거 보유분까지 맞춰져요</div>' : '')
      + '<div data-su-slot="tierw" data-w="' + esc(addr) + '"></div>'
      + '<div class="sx-acts"><span class="sx-twb" data-su-slot="tierwbtn" data-w="' + esc(addr) + '"></span>' + (w ? '<button class="btn sm" data-a="aliasEdit" data-k="' + esc(w.key || w.addr) + '">이름 바꾸기</button>' : '')
      + (s ? '<button class="btn sm danger" data-su="wdel" data-v="' + esc(s.address) + '">추적에서 빼기</button>' : '<span class="cap">추적에서 빼기는 연결 정보를 불러온 뒤에 할 수 있어요</span>') + '</div></div>';
    return '<div class="sx-wr' + (more ? ' more' : '') + (isNew ? ' newrow' : '') + (open ? ' open' : '') + '" data-wq="' + esc(r.k) + '"' + (sxWalHit(r, q) ? ' hidden' : '') + '>'
      + '<div class="sx-wm"><div class="sx-wt"><b>' + (w ? aliasCell(!ed && sxAliasIsAddr(w.alias, addr) ? Object.assign({}, w, { alias: '' }) : w) : r.alias && !sxAliasIsAddr(r.alias, addr) ? ownH(r.alias) : '(이름 없음)') + '</b><span class="mono sx-wad">' + esc(short(addr)) + '</span>' + tag + '</div><div class="cap pvx">' + cap + '</div></div>'
      + (w && !ed && !open ? '<button class="sx-wbtn" data-a="aliasEdit" data-k="' + esc(w.key || w.addr) + '" tabindex="-1" aria-hidden="true">이름 바꾸기</button>' : '')
      + '<button class="sx-wx' + (open ? ' o' : '') + '" data-a="sxWal" data-v="' + esc(r.k) + '" aria-expanded="' + open + '" data-pvl="w" aria-label="' + esc(ownNm(r.alias || short(addr)) + ' 자세히') + '">' + IC.chev + '</button>' + det + '</div>';
  }
  function sxCwRow(r, more, q, i) {
    const c = r.cw, open = S.set.walOpen === r.k, addr = String(c.display || ''), v = esc(c.chain + '|' + c.key);
    const cap = esc(c.name) + (c.chain === 'btc' ? (c.mode === 'descriptor' ? ' · HD 지갑(받는·잔돈 주소)' : ' · 이 주소만') : '') + ' · ' + (c.available === false ? '준비 중' : '읽기 전용 수집');
    const det = !open ? '' : '<div class="sx-wd" id="sxwd' + i + '"><div class="sx-wa"><span class="mono">' + esc(addr) + '</span>' + (c.mode === 'descriptor' ? '' : copyBtn(addr)) + '</div>'
      + '<div class="sx-acts"><button class="btn sm" data-su="cwlabel" data-v="' + v + '">이름 바꾸기</button><button class="btn sm danger" data-su="cwdel" data-v="' + v + '">추적에서 빼기</button></div></div>';
    return '<div class="sx-wr' + (more ? ' more' : '') + (open ? ' open' : '') + '" data-wq="' + esc(r.k) + '"' + (sxWalHit(r, q) ? ' hidden' : '') + '>'
      + '<div class="sx-wm"><div class="sx-wt"><b>' + (r.alias ? ownH(r.alias) : '(이름 없음)') + '</b><span class="mono sx-wad">' + esc(short(addr)) + '</span>' + sxPill('g', c.name) + '</div><div class="cap pvx">' + cap + '</div></div>'
      + '<button class="sx-wx' + (open ? ' o' : '') + '" data-a="sxWal" data-v="' + esc(r.k) + '" aria-expanded="' + open + '" data-pvl="w" aria-label="' + esc(ownNm(r.alias || short(addr)) + ' 자세히') + '">' + IC.chev + '</button>' + det + '</div>';
  }
  function sxDepBody() {
    const D = S.D;
    return '<div class="sx-card">' + (D.deposits.length ? sFold(D.deposits.map(d => '<div class="srow">' + venueLogo(d.ex) + '<div style="min-width:0;flex:1"><b>' + esc(d.ex) + '</b> <span class="pill ' + (d.net === 'EVM' ? 'a' : 'g') + ' sm">' + esc(d.net) + '</span><div class="addr" title="' + esc(d.addr) + '">' + esc(short(d.addr)) + (d.memo && d.memo !== '—' ? ' · 메모 ' + prTxt(d.memo) : '') + '</div></div><span class="pill ' + (d.ok ? 'ok' : 'g') + ' sm">' + (d.ok ? '등록됨' : '미등록') + '</span>' + copyBtn(d.addr) + '</div>'), 'deps')
      : '<div class="sx-empty">등록된 입금 주소가 없어요 · 거래소 조회 키를 넣으면 자동으로 모아요</div>') + '</div>';
  }
  function sxWlBody() {
    const D = S.D, wlist = D.whitelist || S.wl || [];
    return '<div class="sx-card">' + (wlist.length ? sFold(wlist.map(a => '<div class="srow"><span class="addr" title="' + esc(a) + '">' + esc(short(a)) + '</span>' + copyBtn(a) + '<span class="sp"></span><button class="btn sm" data-a="wlRemove" data-v="' + esc(a) + '">제거</button></div>'), 'wl')
      : '<div class="sx-empty">' + (D.whitelist ? '등록된 주소가 없어요' : '목록을 불러오지 못했어요') + '</div>')
      + '<div class="frm"><input class="field" placeholder="0x… 또는 Solana 주소" data-draft="wl" data-enter="wlAdd" aria-label="발신 주소" autocomplete="off" spellcheck="false"><button class="btn sm pri" data-a="wlAdd">추가</button></div></div>';
  }
  function sxNamesBody() {
    return '<div class="sx-card"><div class="frm" style="flex-wrap:wrap"><input class="field" style="flex:2;min-width:220px" placeholder="0x… 또는 Solana 주소" data-draft="naddr" aria-label="지갑 주소" autocomplete="off" spellcheck="false"><input class="field" style="flex:1;min-width:140px" placeholder="표시 이름" data-draft="nalias" data-enter="addAlias" aria-label="표시 이름"><button class="btn pri" data-a="addAlias">이름 저장</button></div>'
      + '<div class="cap" style="margin-top:8px">보낸 내역·미매칭에서 이 주소가 이름으로 보여요</div></div>';
  }
  function sxTokBody() {
    const D = S.D;
    return '<div class="sx-card">' + (D.aliases.length ? sFold(D.aliases.map(a => '<div class="srow"><b>' + esc(a.onchain) + '</b><span class="addr" title="' + esc(a.ca) + '">' + esc(short(a.ca)) + '</span><span class="sp"></span><span class="cap">' + esc(a.chain) + ' → ' + esc(a.ex) + ' ' + esc(a.ticker) + '</span></div>'), 'tok')
      : '<div class="sx-empty"><b>등록된 매핑 없음</b>수집기 설정에서 관리해요</div>') + '</div>';
  }

  function sxDisplayBody() {
    const D = S.D, light = document.documentElement.getAttribute('data-theme') === 'light', glob = document.documentElement.getAttribute('data-scheme') === 'global';
    const hiddenN = D.groups.filter(g => g.value > 0 && S.dust > 0 && g.value < S.dust).length;
    const dust = sxIt('sx-display-dust', '소액 기준', S.dust > 0 ? '<span class="pvx">' + sxDust() + ' 미만 ' + hiddenN + '종 목록에서 숨김(합계엔 포함)</span>' : '전체 표시', '', {
      val: '<span class="sx-val num pvx">' + (S.dust > 0 ? sxDust() : '전체') + '</span>',
      exp: () => '<div class="chiprow">' + DUST_OPTS.map(v => '<button class="fbtn' + (S.dust === v ? ' on' : '') + '" data-a="setDust" data-v="' + v + '" aria-pressed="' + (S.dust === v) + '">' + (v === 0 ? '전체 표시' : '$' + v) + '</button>').join('') + '</div>'
        + '<div class="frm"><input class="field num" inputmode="numeric" placeholder="직접 입력 $" data-draft="dust" data-enter="dustCustom" aria-label="소액 기준 직접 입력" style="max-width:160px"><button class="btn sm" data-a="dustCustom">적용</button></div>'
        + '<div class="cap" style="margin-top:8px">미매칭 자동 숨김도 같은 기준 — 원가 미확인 매도·창 밖 처분은 작아도 숨기지 않아요</div>' });
    return '<div class="sx-card">'
      + sxIt('sx-display-theme', '테마', '', sxSeg('themeSet', [['system', '시스템', thSys()], ['dark', '다크', !thSys() && !light], ['light', '라이트', !thSys() && light]], '테마'))
      + sxIt('sx-display-cur', '기준 통화', S.cur === 'USD' ? '온체인 원가 기준' : 'USDT ₩' + nf('ko-KR').format(D.rate) + ' 환산 · 김프 포함', sxSeg('cur', [['KRW', '₩', S.cur === 'KRW'], ['USD', '$', S.cur === 'USD']], '기준 통화'))
      + sxIt('sx-display-scheme', '손익 색', glob ? '상승 <span style="color:var(--upc)">초록</span> · 하락 <span style="color:var(--downc)">빨강</span>' : '상승 <span style="color:var(--upc)">빨강</span> · 하락 <span style="color:var(--downc)">파랑</span>', sxSeg('scheme', [['kr', '국내식', !glob], ['global', '글로벌', glob]], '손익 색'))
      + sxIt('sx-display-hide', '금액 가리기', '밖에서 보여 줄 때 · 상단 눈 버튼 · Shift+H', sxSw('hideToggle', S.hide, '금액 가리기'))
      + sxIt('sx-display-pgsize', '목록 한 쪽', '긴 목록을 이만큼씩 넘겨 봐요 · 이 기기만', sxSeg('pgSize', [['10', '10개', uiPageSize() === 10], ['20', '20개', uiPageSize() === 20]], '목록 한 쪽 개수'))
      + sxIt('sx-display-logo', '토큰 로고', logosOff() ? '꺼짐 — 글자 아이콘만(외부 요청 없음)' : '외부(jsDelivr)에서 받음 — 끄면 로고 요청을 안 보내요', sxSw('logoToggle', !logosOff(), '토큰 로고'))
      + sxIt('sx-display-rand', '금액 랜덤값', '예시 화면용 · 가리기와 둘 중 하나', sxSw('randToggle', S.rand, '금액 랜덤값'), { exp: () => '<div class="cap">금액·수량에 열 때마다 바뀌는 같은 배수를 곱해 실제와 다른 숫자로 보여요(합계·차트는 서로 맞고 %·단가는 그대로) · 화면에 ‘랜덤값’ 표시 · 탐색기 링크 없음</div>' + rkCtl() })
      + dust
      + (legacyOn("classic") ? '<a class="sx-it sx-lk" id="sx-display-classic" href="/classic"><span class="tx"><b>클래식 화면</b><span class="cap">이전 디자인 · 같은 데이터</span></span><span class="sx-ch">' + IC.ext + '</span></a>' : '')
      + '</div>';
  }

  const FS_TIPS = ['최초 인식 시가 = 원가를 모르는 수량(기초 잔고·원가 없는 입금·에어드랍)을 장부에 처음 생긴 날(창 시작 전 보유는 창 시작일) 시가로 잡은 원가예요.',
    '한 번 잡은 값은 고정 — 지난 손익이 나중에 바뀌지 않아요. 그날 시세를 아직 못 받았으면 \'시세 대기\'로 두고 받으면 반영해요.',
    '안 쓰는 경우: 보냈다가 같은 주소에서 돌아온 코인(보낼 때 원가를 이어받음) · 확인 안 된 토큰 · 판 값의 10배 넘는 시세. 받은 날 판 몫은 판 값이 원가예요.',
    '직접 넣은 원가 · 손익 0 처리 · 평균가 대체가 먼저예요. 산 날보다 늦게 인식되면 그 전 오른 몫은 빠져요 · 스테이블은 원화 취득가액만 그때 환율로.'];
  const FS_TIP = FS_TIPS[0] + ' · 자세히는 펼쳐서 봐요';
  const fsHoldTxt = fs => { const h = fs.hold && typeof fs.hold === 'object' ? fs.hold : {}, n = k => nf('ko-KR').format(num(h[k]));
    const xs = [['wait', '시세 받는 중'], ['ret', '돌아온 코인인지 확인 못 함'], ['unv', '확인 안 된 토큰'], ['cap', '판 값의 10배 넘는 시세']].filter(x => num(h[x[0]])).map(x => x[1] + ' ' + n(x[0]) + '건');
    return xs.length ? ' · 안 매긴 유입: ' + xs.join(' · ') : ''; };
  const fsStat = fs => '최초 인식 시가 ' + nf('ko-KR').format(num(fs.n)) + '건 ' + pvm(m(num(fs.usd), { compact: true })) + ' · 이 중 최초 인식 시가로 계산된 실현 ' + pvm(m(num(fs.real), { sign: true, compact: true }))
    + ' · 명세 추정 ' + nf('ko-KR').format(num(fs.rows)) + '행' + (num(fs.miss) ? ' · 그날 시세 기록이 없어 원가 미확인으로 남긴 유입 ' + nf('ko-KR').format(num(fs.miss)) + '건' : '')
    + fsHoldTxt(fs) + (num(fs.wait) ? ' · 시세 대기 매도 ' + nf('ko-KR').format(num(fs.wait)) + '건' : '')
    + (num(fs.ret) ? ' · 돌아온 코인 원가 승계 ' + nf('ko-KR').format(num(fs.ret)) + '건' : '') + (num(fs.sd) ? ' · 받은 날 판 값이 원가 ' + nf('ko-KR').format(num(fs.sd)) + '건' : '')
    + (num(fs.stN) ? ' · 스테이블 원화 원가 ' + nf('ko-KR').format(num(fs.stN)) + '건' : '')
    + (fs.fill && num(fs.fill.specs) ? ' · 옛날 시세 채우는 중(남는 사용량으로 천천히) — 남은 코인 ' + nf('ko-KR').format(num(fs.fill.specs)) + '개 · ' + nf('ko-KR').format(num(fs.fill.days)) + '일' + (fs.fill.since ? ' · ' + esc(String(fs.fill.since)) + '부터' : '')
      : fs.fill && num(fs.fill.done) ? ' · 옛날 시세 채우기 끝(' + nf('ko-KR').format(num(fs.fill.done)) + '개 코인)' : '');
  function sxCostBody() {
    const D = S.D, tg = D.taxGas;
    let h = '';
    if (tg) {
      const on = tg.on !== false;
      h += sxIt('sx-cost-gas', '가스를 원가·실현에 반영', on ? '반영 ' + m(Math.min(num(tg.total), num(tg.inCost) + num(tg.inRealized) + num(tg.expense)), { compact: true }) + ' / 온체인 가스 ' + m(num(tg.total), { compact: true }) : '끔 · 가스는 가스·수수료 탭에 따로 표시만',
        sxSw('gasCost', on, '가스를 원가·실현에 반영'), { exp: () => '<div class="cap">' + (on ? esc(gasRuleTxt(tg)) : '가스는 가스·수수료 탭에 따로 표시만 해요(실현·세금 명세는 가스 전 · 거래소 체결 수수료는 끔과 무관하게 원가·실현에 그대로)') + '</div>' });
    }
    h += (D.offc || []).map(o => sxIt('sx-cost-offc-' + sxId(o.ex), esc(o.name) + ' 오프체인 = 내 계정 간 이동',
      '<span class="pvx">' + (o.on ? '가정 중 · ' + o.inhN + '/' + o.depN + '건 원가 이어받음' : (o.answered ? '끔' : '아직 답 안 함') + ' · 출금 ' + o.wdN + ' · 입금 ' + o.depN) + '</span>',
      sxSw('offcSelf', o.on, o.name + ' 오프체인 이체를 내 계정 간 이동으로 가정', ' data-v="' + esc(o.ex) + '"'),
      { exp: () => '<div class="cap">' + esc(offcDesc(o.name)) + '</div><div class="cap num" style="margin-top:4px">' + offcStat(o) + '</div>' })).join('');
    const fs = D.firstSeen;
    if (fs) h += sxIt('sx-cost-firstseen', '원가 미확인 → 최초 인식 시가',
      '<span class="pvx">' + (fs.on ? (fs.eff === false ? '켬 · 평균가 대체가 켜져 있어 그쪽이 먼저' : '켬 · 최초 인식 시가 ' + nf('ko-KR').format(num(fs.n)) + '건' + (num(fs.wait) ? ' · 시세 대기 ' + nf('ko-KR').format(num(fs.wait)) + '건' : '')) : '끔 · 원가 미확인은 실현에서 빼요') + '</span>',
      taxTip(FS_TIP, '최초 인식 시가 설명') + sxSw('firstSeen', !!fs.on, '원가 미확인 최초 인식 시가'),
      { exp: () => FS_TIPS.map((t, i) => '<div class="cap"' + (i ? ' style="margin-top:4px"' : '') + '>' + esc(t) + '</div>').join('') + (fs.on ? '<div class="cap pvx" style="margin-top:6px">' + fsStat(fs) + '</div>' : '') });
    h += sxIt('sx-cost-fallback', '원가 미확인 → 평균가 대체', D.fallbackOn ? '켬 · 종목 평균 매수가로 평가·손익 반영' : '끔 · 원가 추적 우선', sxSw('fallback', D.fallbackOn, '원가 미확인 평균가 대체'),
      { exp: () => '<div class="cap">' + (D.fallbackOn ? '원가 없는 보유·매도를 종목 평균 매수가로 평가·손익·실현에 반영 중이에요' : '원가 미확인은 손익에서 빼고 표시만 해요(원가 추적이 우선)') + '</div>' });
    const ov = D.costOv;
    h += sxIt('sx-cost-ov', '원가 지정', ov.length ? '미매칭에서 지정한 건 · 여기서 되돌려요' : '미매칭 › 원가 미확인 항목에서 지정해요', '', {
      val: '<span class="sx-val num">' + ov.length + '건</span>',
      exp: () => ov.length ? ov.map(r => { const be = r.mode === 'breakeven';
        return '<div class="row gap8 sx-ovr"><span class="pill ' + (be ? 'ok' : 'a') + ' sm">' + esc(r.sym) + '</span><span class="cap num">' + (be ? '<span class="pvx">손익 0 처리</span>' + (num(r.qty) ? ' · ' + q(num(r.qty)) + '개 매도 · 정산 ' + mN(num(r.cost)) : ' · 처리된 매도 없음') : esc(r.mode === 'market' ? '당시 시세' : '개당 ' + px(num(r.unit))) + (num(r.qty) ? ' · ' + q(num(r.qty)) + '개 · ' + mN(num(r.cost)) : ' · 적용된 유입 없음')) + '</span><span class="sp"></span>'
          + '<button class="btn sm" data-a="costClearKey" data-k="' + esc(be ? r.gkey || '' : r.key) + '" data-s="' + esc(r.sym) + '"' + (be ? ' data-m="breakeven"' : '') + '>' + (be ? '되돌리기' : '해제') + '</button></div>'; }).join('')
        : '<div class="cap">지정한 원가가 없어요</div>' });
    h += sxIt('sx-cost-rules', '매칭 규칙', '입금 판정·수량 오차·시간 창 · 지금 설정값', '', { href: '#settings/cost/rules' });
    return '<div class="sx-card">' + h + '</div>';
  }
  function sxRulesBody() {
    const D = S.D, tg = D.taxGas, offOn = arr(D.offc).filter(o => o.on).map(o => o.name);
    const kv = (k, v) => '<div class="kv"><span>' + k + '</span><b>' + v + '</b></div>';
    return '<div class="sx-card">' + sxGrp('지금 설정에 따라')
      + kv('가스·수수료 원가 포함', tg ? (tg.on !== false ? '켜짐' : '꺼짐') : '켜짐(이 서버 기본)')
      + (D.firstSeen ? kv('원가 미확인 → 최초 인식 시가', D.firstSeen.on ? (D.firstSeen.eff === false ? '켜짐 · 평균가 대체가 먼저' : '켜짐') : '꺼짐') : '')
      + kv('원가 미확인 → 평균가 대체', D.fallbackOn ? '켜짐' : '꺼짐')
      + kv('오프체인 이체 = 내 계정 간 이동', offOn.length ? esc(offOn.join(' · ')) + ' 가정' : '가정 안 함')
      + kv('소액 기준(목록 숨김)', S.dust > 0 ? sxDust() + ' 미만' : '전체 표시')
      + kv('원가 지정', D.costOv.length + '건')
      + sxGrp('수집기 고정값')
      + kv('거래소 입금 판정', 'txid 일치 → 수량·시간 → 입금 주소')
      + kv('수량 오차 허용', '보낸 수량 −0.5% (스테이블 −2개)')
      + kv('시간 창', '보낸 뒤 −2분 ~ 6시간')
      + kv('브릿지 → 내 지갑', '0~60분 · −1%')
      + kv('되돌려 받음 = 전액 상쇄', '보낸 값의 98% 이상')
      + kv('토큰 매핑', '컨트랙트 주소(CA) 우선')
      + kv('평균 매수가 계산', '이동평균(가중평균)')
      + kv('LP 예치·인출 사이클', '분리')
      + '<div class="cap" style="margin-top:10px">후보가 여럿이거나 확실하지 않으면 자동으로 묶지 않고 보낸 내역·미매칭에 ‘확인’으로 남겨요</div></div>';
  }

  function sxAiBody() {
    const D = S.D, rl = D.reviewLen;
    if (!rl) return '<div class="sx-card"><div class="sx-empty">이 서버는 AI 리뷰 분량·순서 설정을 지원하지 않아요</div></div>';
    const rf = D.reviewFill, rfKey = rf ? (num(rf.parallel) > 1 ? 'recent:3' : rf.order + ':1') : '';
    const row = (id, lab, a, opts, cur, pre) => { const it = opts.find(x => (pre ? pre + x[0] : x[0]) === cur) || null;
      return '<div class="sx-segrow" id="' + id + '"><div class="lab">' + lab + '</div>' + sxSeg(a, opts.map(x => [(pre || '') + x[0], esc(x[1]), (pre ? pre + x[0] : x[0]) === cur]), lab, true) + (it ? '<div class="cap">' + esc(it[2]) + '</div>' : '') + '</div>'; };
    const rp = D.reviewPause;
    const pause = rp ? sxIt('sx-ai-pause', '자동 생성 잠시 멈춤', rp.on ? '<span class="wtxt">멈춤 중' + (rp.at ? ' · ' + esc(fmtTs(rp.at)) + '부터' : '') + '</span> — 새로 쓰는 AI 리뷰·평가 없음(지금 쓰는 한 건은 끝까지)'
        : '켜면 오늘 리뷰·지난 리뷰 다시 쓰기·주간·영수증 AI 평가를 바로 멈춰요', sxSw('revPause', rp.on, 'AI 리뷰 자동 생성 잠시 멈춤'),
      { exp: () => '<div class="cap">자동으로는 원래도 한꺼번에 많이 쓰지 않아요 — 최근 3일 + 지난 날은 데이터가 바뀐 날만 하루 최대 5일 · 프롬프트 문구만 바뀐 건 다시 쓰지 않아요. '
        + '멈춤은 그것까지 전부 세우는 스위치예요. 풀면 다음 회차(매일 23:50 · 기동 때)부터 이어서 써요. 영수증 서랍의 ‘평가’ 버튼처럼 직접 누르는 건 멈춤 중에도 돼요.</div>' }) : '';
    return '<div class="sx-card">' + revProgHTML(D.reviewProg, rf) + pause
      + row('sx-ai-daily', '일간 분량', 'revLen', REV_LEN.daily, 'daily:' + rl.daily, 'daily:')
      + row('sx-ai-weekly', '주간 분량', 'revLen', REV_LEN.weekly, 'weekly:' + rl.weekly, 'weekly:')
      + (rf ? row('sx-ai-fill', '채우는 순서', 'revFill', REV_FILL, rfKey, '') : '')
      + '<div class="cap sx-note">바꾼 분량·순서는 새로 쓰는 리뷰부터 적용돼요 · 기존 리뷰는 그대로</div></div>';
  }

  function sxDataBody() {
    const D = S.D, bs = D.bfSince, cov = covLoad(), cd = cov && cov.d;
    const big = '<div class="sx-tiles pvx"><div><b>' + sxChainN() + '</b><span>체인</span></div><div><b>' + D.exN + '</b><span>거래소</span></div><div><b' + (D.bcConfirmed.length ? ' class="wtxt"' : '') + '>' + (D.bc ? D.bcConfirmed.length : '—') + '</b><span>잔고 불일치</span></div></div>';
    const src = D.srcChips.map((s, i) => '<div class="sx-it" id="sx-data-src' + i + '"><span class="dot"></span><div class="sx-itx"><span class="tx"><b>' + esc(hs(s.label)) + '</b><span class="cap">' + esc(scanText(hs(s.addr))) + '</span></span></div></div>').join('');
    const up = '<div class="sx-it" id="sx-data-upbit"><span class="dot' + (D.upbit ? '' : ' w') + '"></span><div class="sx-itx"><span class="tx"><b>업비트 · 조회 전용</b><span class="cap">' + (D.upbit ? '연결됨 · 60초 동기화' : '‘연결 · 키’에서 조회 전용 키를 넣어요') + '</span></span></div>' + sxPill(D.upbit ? 'ok' : 'g', D.upbit ? '연결됨' : '키 대기') + '</div>';
    const bc = D.bc, bcCap = bc ? esc(fmtTs(bc.checkedAt) || '—') + (bc.pairs != null ? ' · <span class="pvx">대상 ' + num(bc.pairs) + '쌍' + (bc.checked != null ? ' · ' + num(bc.checked) + '개 대조' : '') + '</span>' : bc.checked != null ? ' · <span class="pvx">' + num(bc.checked) + '개 대조</span>' : '')
      + (bc.unchecked ? ' · <span class="wtxt pvx">이번 판 미대조 ' + bc.unchecked + '쌍</span>' : bc.capped ? ' · 호출 상한 도달' : '') + (bc.errors ? ' · 오류 ' + bc.errors + '건' : '') + (D.bcWatch.length ? ' · 관찰 ' + D.bcWatch.length : '') : '아직 대조 결과가 없어요';
    const bcRow = '<div class="sx-it" id="sx-data-bc"><span class="dot' + (!bc || D.bcConfirmed.length || bc.errors ? ' w' : '') + '"></span><div class="sx-itx"><span class="tx"><b>온체인 잔고 대조</b><span class="cap num">' + bcCap + '</span></span></div>'
      + (bc && bc.mismatches.length ? '<button class="btn sm" data-a="goPend" data-v="bal">보기</button>' : bc ? sxPill(D.bcConfirmed.length ? 'w' : 'ok', '불일치 ' + D.bcConfirmed.length) : '') + '</div>';
    const fx = '<div class="sx-it" id="sx-data-fx"><span class="dot ' + (D.rateSrc === 'live' ? 'i' : 'w') + '"></span><div class="sx-itx"><span class="tx"><b>환율</b><span class="cap num">USDT <span class="num">₩' + nf('ko-KR').format(D.rate) + '</span> · 매매기준율 <span class="num">₩' + nf('ko-KR', null, 1).format(D.fx) + '</span>' + (D.rateSrc === 'fallback' ? '' : ' · 김프 <span class="num">' + pctS(D.kimp, 2) + '</span>') + fxNote(D) + '</span></span></div></div>';
    const un = cd ? arr(cd.unavailable) : [], cnt = k => un.filter(u => u.severity === k).length;
    const limCap = cd ? 'API 한도 ' + cnt('hard') + ' · 일부 누락 ' + cnt('partial') + ' · 그 밖 ' + (un.length - cnt('hard') - cnt('partial')) : cov && cov.st === 'err' ? '불러오지 못했어요' : '불러오는 중…';
    return big + '<div class="sx-card">' + sxGrp('수집 상태') + src + up + bcRow + fx + '</div>'
      + '<div class="sx-card">' + sxGrp('과거 · 한계')
      + (bs ? sxIt('sx-data-hist', '과거 데이터 더 가져오기', '지금 <span class="num">' + esc(bs.windowStart) + '</span>부터 · 날짜 고르면 그 구간만', bs.rebuildRunning || arr(bs.jobs).some(j => j.phase !== 'done') ? sxPill('a', '진행 중') : '', { href: '#settings/data/history' }) : '')
      + sxIt('sx-data-lim', '수집 한계', limCap, sxPill('g', '하루 1회'), { href: '#settings/data/limits' })
      + '<div class="sx-acts sx-pad"><button class="btn sm" data-a="reload">지금 새로고침</button><span class="cap">화면 데이터를 다시 불러와요</span></div></div>';
  }
  const BF_LIM = [
    { ex: 'okx', t: 'OKX 체결은', at: n => new Date(n.getFullYear(), n.getMonth() - 3, 1) },
    { ex: 'bybit', t: '바이비트 체결·손익은', at: n => new Date(n.getFullYear(), n.getMonth(), n.getDate() - 730) },
    { ex: 'kucoin', t: '쿠코인 체결은 약', at: n => new Date(n.getFullYear() - 1, n.getMonth(), n.getDate()) },
    { ex: 'binance', t: '바이낸스 선물 손익은 약', at: n => new Date(n.getFullYear() - 1, n.getMonth(), n.getDate()) }
  ];
  function bfLimitWarn(from) {
    const st = suSt();
    if (!st || !isISO(from)) return '';
    const now = new Date(), iso = d => d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
    const shown = c => (c.slice(0, 4) === String(now.getFullYear()) ? (+c.slice(5, 7)) + '/' + (+c.slice(8, 10)) : c);
    const L9 = BF_LIM.filter(x => st.exchanges[x.ex] && st.exchanges[x.ex].set).map(x => [x, iso(x.at(now))]).filter(z => from < z[1]).map(z => esc(z[0].t + ' ' + shown(z[1]) + ' 이전 못 받아요'));
    const hl = arr((st.perp || {}).wallets).some(w => w && w.dex === 'hyperliquid');
    const ws = S.D && S.D.bfSince && S.D.bfSince.windowStart;
    if (hl && isISO(ws) && from < ws) L9.push('Hyperliquid 체결은 최근 1만 건까지만 받아요');
    if (!L9.length) return '';
    return '<div class="cap wtxt bfwarn pvx" role="status" style="margin-top:8px">' + L9.join('<br>') + '<br><a href="#settings/data/limits">자세히 = 수집 한계</a></div>';
  }
  function sxHistBody() {
    const bs = S.D.bfSince;
    if (!bs) return '<div class="sx-card"><div class="sx-empty">이 서버는 과거 구간 추가 가져오기를 지원하지 않아요</div></div>';
    const SECN = { eth: 'Ethereum', base: 'Base', arbitrum: 'Arbitrum', optimism: 'Optimism', polygon: 'Polygon', scroll: 'Scroll', zksync: 'zkSync', gnosis: 'Gnosis', robinhood: 'Robinhood', arc: 'Arc', bsc: 'BNB Chain', sol: 'Solana', upbit: '업비트', monad: 'Monad', megaeth: 'MegaETH', plasma: 'Plasma', xlayer: 'X Layer', kaia: 'Kaia', fraxtal: 'Fraxtal', bob: 'BOB', story: 'Story', somnia: 'Somnia', avalanche: 'Avalanche', stable: 'Stable' };
    return '<div class="sx-card"><div class="sx-it first"><div class="sx-itx"><span class="tx"><b>지금 <span class="num">' + esc(bs.windowStart) + '</span>부터 추적해요</b><span class="cap">' + (bs.windowStart !== bs.defaultStart ? '기본 ' + esc(bs.defaultStart) : '기본 ' + num(bs.months) + '개월') + ' · 다시 계산하는 몇 분 동안 새 거래 반영이 잠시 멈춰요</span></span></div></div>'
      + '<div class="frm" style="flex-wrap:wrap">' + uiDate('bfDate', S.drafts.bfDate, { label: '시작 날짜' })
      + uiPick('bfSec', [['', '전체 체인·거래소']].concat(arr(bs.sections).map(x => [x, SECN[x] || CHAIN_KO[x] || (String(x).charAt(0).toUpperCase() + String(x).slice(1))])), S.drafts.bfSec || '', '범위', { act: true })
      + '<button class="btn sm pri" data-a="bfReq">가져오기</button></div>'
      + bfLimitWarn(isISO(S.drafts.bfDate) ? S.drafts.bfDate : bs.windowStart)
      + histPerHTML(bs.per, SECN) + histJobsHTML(arr(bs.jobs))
      + (Object.keys(bs.pendingRebuild || {}).length ? '<div class="cap" style="margin-top:8px">원장 재계산 대기: ' + Object.entries(bs.pendingRebuild).map(([k, v]) => esc(SECN[k] || k) + ' 옛 거래 ' + esc(v) + '건').join(' · ') + ' — 가져오기가 모두 끝나면 자동으로 시작해요</div>' : '')
      + (bs.rebuildRunning ? '<div class="cap" style="margin-top:6px">원장 재계산 중이에요 — 끝나면 자동으로 다시 불러와요</div>' : '')
      + (bs.rebuildNotBefore ? '<div class="cap" style="margin-top:6px">배포 직후라 재계산은 ' + esc(fmtTs(bs.rebuildNotBefore) || '') + ' 이후에 해요</div>' : '')
      + (bs.rebuildFails ? '<div class="cap wtxt" style="margin-top:6px">자동 재계산 실패 ' + num(bs.rebuildFails) + '회' + (bs.rebuildFailAt ? ' (마지막 ' + esc(fmtTs(bs.rebuildFailAt) || '') + ')' : '') + ' · 원장은 그대로이고 ' + (bs.rebuildDiskRetry ? '디스크 여유가 생기면 바로 다시 시도해요' : '잠시 뒤 다시 시도해요') + (bs.rebuildFailLabel ? '<br>원인: ' + esc(bs.rebuildFailLabel) : '') + (bs.rebuildLastError ? '<br>사유: ' + esc(errTxt(String(bs.rebuildLastError).slice(0, 200))) : '') + '</div>' : '')
      + (bs.rebuiltAt ? '<div class="cap" style="margin-top:6px">마지막 자동 재계산 ' + esc(fmtTs(bs.rebuiltAt) || '') + '</div>' : '') + '</div>';
  }

  function sxAdvBody() {
    const K = sxKeys(), bl = arr(S.oa.d && S.oa.d.brokers), bOn = bl.filter(b => b.enabled).length;
    oaNeed(300000);
    return '<div class="sx-card">' + sxGrp('그 밖')
      + (legacyOn("futures") ? '<a class="sx-it sx-lk" id="sx-adv-fut" href="/futures"><span class="tx"><b>선물 페이지</b><span class="cap">거래소·퍼프 덱스 선물 손익 · 별도 화면</span></span><span class="sx-ch">' + IC.ext + '</span></a>' : '')
      + sxIt('sx-adv-brokers', '증권사 연결', (bl.length ? bl.length + '곳 · ' + (bOn ? bOn + '곳 켜짐' : '모두 꺼짐') : '읽기 전용 보유 동기화') + ' · config.json 에서 켬', sxPill('w', '실험'), { href: '#settings/advanced/brokers' })
      + sxIt('sx-adv-apply', '설정 적용 방식', K ? (K.apply.runner ? (K.apply.mode === 'reload' ? '자동 재시작 · 지갑을 넣으면 약 30초 안에 수집기가 다시 시작 · 탐색기 키는 재시작 1번' : '수집기 자동 재시작 · 바꾸면 약 30초 안에 스스로 다시 시작') : '러너 없음 · 지갑·탐색기 키를 바꾸면 재시작 1번') : '불러오는 중…',
        K && !K.apply.runner && K.apply.manual ? '<button class="btn sm" data-su="copy" data-v="' + esc(K.apply.manual) + '">명령 복사</button>' : '',
        { exp: () => '<div class="sx-slot sx-applyslot" data-su-slot="apply">' + sxSlotWait() + '</div>' })
      + '</div>';
  }

  function sxHead(sec, sub, wide) {
    const M = SX_META[sec], D0 = SX[sec], sd = sub && D0.subs && D0.subs[sub];
    const title = sub ? SX_SUBS[sec][sub] : M.t;
    const back = sub ? '<button class="sx-back" data-a="sxBack" data-v="' + sxHash(sec) + '">' + IC.left + esc(M.t) + '</button>' : wide ? '' : '<button class="sx-back" data-a="sxBack" data-v="settings">' + IC.left + '설정</button>';
    const ic = wide && !sub ? '<span class="aic ' + M.c + '">' + sxIcon(M.ic) + '</span>' : '';
    const cap = sd ? sd.cap : D0.cap;
    return back + '<div class="sx-ph">' + ic + '<h1 class="sx-title" id="sxH" tabindex="-1">' + esc(title) + '</h1>' + (sub ? '' : sxSafe(sxBadge, sec)) + '<span class="sp"></span>' + (wide && !sub && D0.act ? D0.act() : '') + '</div>'
      + (cap ? '<div class="cap sx-pcap">' + cap + '</div>' : '');
  }
  function sxBody(sec, sub, wide) { const D0 = SX[sec], sd = sub && D0.subs && D0.subs[sub]; return sd ? sd.body(wide) : D0.body(wide); }
  function vSettings() {
    const wide = sxWide();
    let sec = S.set.sec, sub = S.set.sub;
    if (wide && !sec) { sec = sxLast(); sub = ''; }
    alLoad(false); authLoad();
    if (sec === 'keys' && !sub) { const u = suU(), K = sxKeys(); if (u && K && u.xp == null) u.xp = K.empty[0] || ''; }
    const anim = S.set.anim, ac = anim ? ' sx-in-' + anim : '';
    S.set.sig = sxSig();
    if (wide) {
      return '<div class="sx sx-wide" data-su-scope><div class="sx-dh"><h2 class="sx-title sx-t0">설정</h2><span class="sp"></span>' + sxSearchHTML() + '</div>'
        + '<div class="sx-grid"><aside class="sx-side">' + sxHero() + '<nav class="card sx-nav" aria-label="설정 메뉴">' + sxNav(sec, true) + '</nav>' + sxVer() + '</aside>'
        + '<section class="card sx-det' + ac + '" aria-labelledby="sxH" data-sx-route="' + esc(sxHash(sec, sub)) + '">' + sxHead(sec, sub, true) + '<div class="sx-body">' + sxBody(sec, sub, true) + '</div></section></div></div>';
    }
    if (!sec) return '<div class="sx sx-home' + ac + '" data-su-scope data-sx-route="settings"><h1 class="sx-title" id="sxH" tabindex="-1">설정</h1>' + sxSearchHTML() + sxHero() + sxNav('', false) + sxVer() + '</div>';
    return '<div class="sx sx-page' + ac + '" data-su-scope data-sx-route="' + esc(sxHash(sec, sub)) + '">' + sxHead(sec, sub, false) + '<div class="sx-body">' + sxBody(sec, sub, false) + '</div></div>';
  }
  const sxVer = () => { const H = sxHealthSum(); return H && H.version ? '<div class="cap pvx" style="padding:10px 4px 0;color:var(--muted);font-size:12px">버전 ' + esc(H.version)
    + (H.dataRev != null ? ' · 데이터 개정 ' + esc(String(H.dataRev)) : '') + '</div>' : ''; };
  function sxSig() {
    const st = suSt(), H = sxHealthSum();
    let a = '';
    if (st) {
      const P = st.perp || {};
      a = JSON.stringify([arr(st.wallets).map(w => w.address + ':' + arr(w.chains).length + ':' + arr(w.reconDone).length), arr(st.chainWallets).map(c => c.chain + ':' + c.key + ':' + (c.label || '')), Object.keys(st.explorers).map(k => st.explorers[k].set ? 1 : 0), Object.keys(st.exchanges).map(k => st.exchanges[k].set ? 1 : 0),
        st.telegram && [st.telegram.connected, st.telegram.bot, st.telegram.chatName], arr(P.wallets).length, P.error || '', (sxKeys() || {}).pBad, st.apply && st.apply.runner]);
    }
    return a + '|' + (H ? [H.loaded, H.crit, H.warn, H.known, H.label, H.version].join(',') : '');
  }

  const Finder = {
    norm: s => String(s == null ? '' : s).toLowerCase().replace(/<[^>]*>/g, '').replace(/[\s·・,.\-_/()'’‘"`›>|:]+/g, ''),
    cho(s) { const C = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ'; let o = ''; for (const ch of String(s)) { const c = ch.charCodeAt(0) - 0xAC00; o += c >= 0 && c < 11172 ? C.charAt(Math.floor(c / 588)) : ch; } return o; },
    isCho: s => /^[ㄱ-ㅎ]+$/.test(s),
    score(e, toks) {
      const n = Finder.norm(e.t), k = Finder.norm(e.k), p = Finder.norm(e.path || '');
      let tot = 0;
      for (const t of toks) {
        let s = 0;
        if (Finder.isCho(t)) s = Finder.cho(n).indexOf(t) >= 0 ? 45 : Finder.cho(k).indexOf(t) >= 0 ? 25 : 0;
        else s = n === t ? 100 : n.indexOf(t) === 0 ? 80 : n.indexOf(t) > 0 ? 60 : k.indexOf(t) >= 0 ? 40 : p.indexOf(t) >= 0 ? 20 : 0;
        if (!s) return 0;
        tot += s;
      }
      return tot;
    },
    find(entries, q, max) {
      const toks = String(q || '').split(/\s+/).map(Finder.norm).filter(Boolean);
      if (!toks.length) return [];
      return entries.map((e, i) => ({ e, s: Finder.score(e, toks), i })).filter(x => x.s > 0).sort((a, b) => b.s - a.s || a.i - b.i).slice(0, max || 8).map(x => x.e);
    },
    mark(t, q) { const raw = String(q || '').trim().split(/\s+/)[0] || '', i = raw ? String(t).toLowerCase().indexOf(raw.toLowerCase()) : -1;
      return i < 0 ? esc(t) : esc(t.slice(0, i)) + '<mark>' + esc(t.slice(i, i + raw.length)) + '</mark>' + esc(t.slice(i + raw.length)); }
  };
  function sxIndex() {
    const E = [], D = S.D;
    const add = (s, sub, t, k, sel, pre) => E.push({ s, sub: sub || '', t, k: k || '', sel: sel || '', pre: pre || null, path: SX_META[s].t + (sub ? ' › ' + SX_SUBS[s][sub] : '') });
    const openIt = id => () => S.set.open.add(id);
    const xpOpen = k => () => { const u = suU(); if (u) u.xp = k; };
    const exOpen = k => () => { const u = suU(); if (u) u.ex = k; };
    [['helius', 'Helius (Solana)', '솔라나 sol 탐색기 api 키 key'], ['etherscan', 'Etherscan', '이더스캔 evm 가속 백필 api 키 key 필수'], ['alchemy', 'Alchemy', '알케미 evm 토큰 잔고 찾기 노드 api 키 key 필수 무료 cu'], ['ankr', 'Ankr', '앵커 evm 받은 토큰 확인 bsc base 옛 기록 노드 api 키 key 필수 무료 크레딧'], ['coingecko', 'CoinGecko', '코인게코 시세 dex 게코터미널 차트 nft 바닥가 데모 프로 무료 유료 api 키 key'], ['opensea', 'OpenSea', '오픈시 nft 바닥가 api 키 key']]
      .forEach(x => add('keys', '', x[1] + ' 키', x[2], '[data-su="xp"][data-v="' + x[0] + '"]', xpOpen(x[0])));
    add('keys', 'exchanges', '거래소 조회 키', '거래소 api 키 key 업비트 바이낸스 조회 전용 read only', '.sx-exslot');
    [['upbit', '업비트'], ['bithumb', '빗썸'], ['binance', '바이낸스 Binance'], ['bybit', '바이빗 Bybit'], ['okx', 'OKX'], ['kucoin', '쿠코인 KuCoin'], ['gate', '게이트 Gate']]
      .forEach(x => add('keys', 'exchanges', x[1] + ' 키', '거래소 api key 조회 입금주소 입금 주소', '[data-su="ex"][data-v="' + x[0] + '"]', exOpen(x[0])));
    add('keys', '', '이 서버 공인 IP', 'ip 아이피 화이트리스트 허용 목록 거래소', '#sx-keys-ip');
    add('keys', 'telegram', '텔레그램 알림 봇', 'telegram 봇 bot 토큰 token botfather chat', '.sx-tgslot');
    add('keys', '', '설정 마법사', '처음 설정 wizard 마법사 온보딩', '.sx [data-su="wizard"]');
    add('wallets', '', '지갑 추가', '주소 추가 등록 wallet add evm solana 여러 개', '#sx-wallets-add', () => S.set.open.add('wadd'));
    add('wallets', '', '추적 지갑 목록', '지갑 이름 바꾸기 별명 alias 삭제 빼기 주소 복사', '#walCard');
    add('wallets', 'perp', '퍼프 덱스 주소', 'perp dex 하이퍼리퀴드 hyperliquid dydx 선물 포지션', '.sx-perpslot');
    add('wallets', 'deposits', '거래소 입금 주소', '입금 주소 deposit 거래소', '');
    if (D.rabby && arr(D.rabby.wallets).length) add('wallets', 'rabby', 'Rabby 대조', 'rabby 래비 debank 디뱅크 차이 대조', '');
    add('wallets', 'whitelist', '발신 주소 화이트리스트', 'whitelist 스팸 에어드랍 발신', '');
    add('wallets', 'names', '추적 안 하는 주소에 이름', '주소 이름 별명 alias 표시 이름', '');
    add('wallets', 'tokens', '토큰 매핑', '컨트랙트 ca 티커 ticker 매핑', '');
    add('alerts', '', '알림 추천값', '프리셋 추천 최소 전부 preset 알림', '#sx-al-pre');
    if (alD() && alOn(alD(), 'move')) add('alerts', '', '조용한 시간', '방해 금지 밤 quiet 무음 시간 급등락 모아', '#sx-al-quiet', openIt('sx-al-quiet'));
    add('alerts', '', '하루 요약 시각', '하루 요약 digest 아침 09:00 무음 한 통 시각', '#sx-al-daily');
    add('alerts', '', '테스트 알림 보내기', '테스트 test 텔레그램', '#sx-al-pre');
    arr(alD() && alD().cats).forEach(c => { const t = alTier(c), id = 'sx-al-' + sxId(c.key === 'weekly' ? 'review' : c.key);
      add('alerts', '', String(c.label), '알림 ' + (t === 'now' ? '즉시 ' : t === 'daily' ? '하루 요약 ' : '시스템 ') + String(c.desc || '') + ' ' + String(c.key), t === 'web' ? '#sx-al-sys' : '#' + id, t === 'now' ? openIt(id) : null); });
    add('display', '', '테마', '다크 라이트 dark light 밝은 어두운 모드', '#sx-display-theme');
    add('display', '', '기준 통화', '원화 달러 krw usd 통화 환산 ₩ $', '#sx-display-cur');
    add('display', '', '손익 색', '국내식 글로벌 빨강 파랑 초록 색상 색깔', '#sx-display-scheme');
    add('display', '', '금액 가리기', '숨김 가리기 hide 눈 shift+h 프라이버시', '#sx-display-hide');
    add('display', '', '금액 랜덤값', '랜덤 random 예시 스크린샷 주사위', '#sx-display-rand');
    add('ai', '', '자동 생성 잠시 멈춤', 'ai 리뷰 멈춤 정지 끄기 일시정지 pause 대량 재작성 자동', '#sx-ai-pause');
    add('display', '', '토큰 로고', '로고 아이콘 jsdelivr 외부 요청 프라이버시 logo', '#sx-display-logo');
    add('display', '', '목록 한 쪽', '쪽 넘김 페이지 10개 20개 목록 개수 다음 이전 page size', '#sx-display-pgsize');
    add('display', '', '소액 기준', '소액 먼지 dust 숨김 기준 $50 소액기준', '#sx-display-dust', openIt('sx-display-dust'));
    if (legacyOn("classic")) add('display', '', '클래식 화면', '이전 디자인 classic 옛 화면 기존 화면', '#sx-display-classic');
    add('cost', '', '가스를 원가·실현에 반영', '가스 gas 수수료 원가 비용', '#sx-cost-gas');
    arr(D.offc).forEach(o => add('cost', '', o.name + ' 오프체인 이체 가정', '오프체인 내 계정 이동 가정 offchain', '#sx-cost-offc-' + sxId(o.ex), openIt('sx-cost-offc-' + sxId(o.ex))));
    if (D.firstSeen) add('cost', '', '원가 미확인 → 최초 인식 시가', '최초 인식 시가 처음 인식 추정 원가 미확인 기초 잔고 에어드랍 first seen', '#sx-cost-firstseen', openIt('sx-cost-firstseen'));
    add('cost', '', '원가 미확인 → 평균가 대체', '평균가 대체 폴백 fallback 원가 미확인', '#sx-cost-fallback');
    add('cost', '', '원가 지정', '원가 지정 해제 되돌리기 손익 0', '#sx-cost-ov', openIt('sx-cost-ov'));
    add('cost', 'rules', '매칭 규칙', '매칭 규칙 수량 오차 시간 창 입금 판정 평단 평균 매수가', '');
    add('ai', '', 'AI 리뷰 진행 상황', 'ai 리뷰 진행 대기 review', '.rvprog');
    add('ai', '', '일간 리뷰 분량', 'ai 리뷰 분량 간단히 보통 자세히 daily', '#sx-ai-daily');
    add('ai', '', '주간 리뷰 분량', 'ai 리뷰 분량 weekly', '#sx-ai-weekly');
    add('ai', '', '리뷰 채우는 순서', 'ai 리뷰 순서 최근 오래된 동시에', '#sx-ai-fill');
    add('data', '', '수집 상태', '데이터 소스 수집 스캔 blockscout rpc', '#sx-data-upbit');
    add('data', '', '환율 · 김프', '환율 김프 usdt 매매기준율 fx', '#sx-data-fx');
    add('data', '', '온체인 잔고 대조', '잔고 대조 불일치 balance', '#sx-data-bc');
    add('data', '', '지금 새로고침', '새로고침 reload 다시 불러오기', '.sx [data-a="reload"]');
    add('data', 'history', '과거 데이터 더 가져오기', '백필 backfill 과거 가져오기 날짜', '');
    add('data', 'limits', '수집 한계', '수집 한계 api 한도 누락 coverage', '');
    add('account', '', '로그인 · 비밀번호', '비밀번호 바꾸기 password 로그인 login', '#sx-acc-state');
    add('account', '', '로그아웃', '로그아웃 logout 모든 기기', '#sx-acc-btns');
    if (legacyOn("futures")) add('advanced', '', '선물 페이지', '선물 futures', '#sx-adv-fut');
    add('advanced', 'brokers', '증권사 연결', '증권사 broker 주식 키움 한국투자 토스', '');
    add('advanced', '', '설정 적용 방식', '재시작 restart 적용 러너 pm2', '#sx-adv-apply');
    return E;
  }
  function sxResultsHTML(q) {
    const R = S.set.qr = Finder.find(sxIndex(), q, 8), a = Math.min(S.set.qi || 0, Math.max(0, R.length - 1));
    if (!R.length) return '<div class="sx-qe">‘' + esc(q) + '’와 맞는 설정이 없어요</div>';
    return R.map((e, i) => '<button class="sx-qo' + (i === a ? ' on' : '') + '" id="sxQo' + i + '" role="option" aria-selected="' + (i === a) + '" data-a="sxPick" data-v="' + i + '"><b>' + Finder.mark(e.t, q) + '</b><span>' + esc(e.path) + '</span></button>').join('');
  }
  function sxSearchHTML() {
    const q = S.set.q || '', op = !!q && S.set.qOpen;
    return '<div class="sx-q" role="search"><label class="sx-qb">' + IC.search + '<input id="sxQ" class="sx-qi" type="search" data-input="sxq" placeholder="설정 찾기 — 키, 텔레그램, 소액 기준…" autocomplete="off" spellcheck="false" autocapitalize="off" enterkeyhint="go"'
      + ' role="combobox" aria-label="설정 찾기" aria-expanded="' + op + '" aria-controls="sxQr" aria-autocomplete="list"' + (op ? ' aria-activedescendant="sxQo' + (S.set.qi || 0) + '"' : '') + ' value="' + esc(q) + '"><kbd class="sx-kbd" aria-hidden="true">/</kbd></label>'
      + '<div class="sx-qr" id="sxQr" role="listbox" aria-label="설정 찾기 결과"' + (op ? '' : ' hidden') + '>' + (op ? sxResultsHTML(q) : '') + '</div></div>';
  }
  function sxSearchPaint() {
    const q = S.set.q || '', op = !!q && S.set.qOpen, r = $('#sxQr'), i = $('#sxQ');
    if (!r) return;
    r.hidden = !op; r.innerHTML = op ? sxResultsHTML(q) : '';
    if (i) { i.setAttribute('aria-expanded', String(op)); if (op && S.set.qr && S.set.qr.length) i.setAttribute('aria-activedescendant', 'sxQo' + (S.set.qi || 0)); else i.removeAttribute('aria-activedescendant'); }
    const on = $('#sxQo' + (S.set.qi || 0)); if (on && on.scrollIntoView) on.scrollIntoView({ block: 'nearest' });
  }
  function sxPick(i) {
    const e = S.set.qr && S.set.qr[i];
    if (!e) return;
    S.set.q = ''; S.set.qi = 0; S.set.qOpen = false;
    const ae = document.activeElement; if (ae && ae.id === 'sxQ') ae.blur();
    sxGo(e.s, e.sub, { pre: e.pre, hl: e.sel });
  }
  function sxGo(sec, sub, o) {
    o = o || {};
    if (o.pre) { try { o.pre(); } catch (e) {  } }
    S.set.hl = o.hl || ''; S.set.focus = o.focus || '';
    const h = sxHash(sec, sub);
    if (S.tab === 'settings' && location.hash.replace('#', '') === h) { renderView(); return; }
    location.hash = h;
  }
  function sxRoute(r) {
    const pk = sxHash(S.set.sec, S.set.sub), nk = sxHash(r.sec, r.sub);
    if (pk === nk) { renderView(); return; }
    const dp = sxDepth({ sec: S.set.sec, sub: S.set.sub }), dn = sxDepth(r);
    S.set.y[pk] = window.scrollY || 0;
    S.set.anim = dn > dp ? 'fwd' : dn < dp ? 'back' : 'swap';
    S.set.restoreY = dn < dp ? (S.set.y[nk] || 0) : 0;
    S.set.from = dn < dp ? (S.set.sub ? S.set.sub : S.set.sec) : '';
    S.set.fromSub = dn < dp && !!S.set.sub;
    S.set.prev = pk;
    S.set.sec = r.sec; S.set.sub = r.sub; S.set.q = ''; S.set.qi = 0; S.pop = null; S.aliasEdit = null;
    if (r.sec !== 'wallets') S.set.walOpen = '';
    if (r.sec) LS.set('tj_v2_sxsec', r.sec);
    { const ae = document.activeElement, v9 = $('#view'); if (ae && v9 && v9.contains(ae) && /^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName)) ae.blur(); }
    syncUrl();
    render();
  }
  function sxTick() {
    const P = S.set.nums || (S.set.nums = {});
    document.querySelectorAll('.sx [data-sxk]').forEach(el => { const k = el.getAttribute('data-sxk'), v = el.getAttribute('data-sxv');
      if (P[k] != null && P[k] !== v) { el.classList.remove('sx-tick'); void el.offsetWidth; el.classList.add('sx-tick'); }
      P[k] = v; });
  }
  function sxAfter() {
    sxTick();
    const job = { hl: S.set.hl, focus: S.set.focus, y: S.set.restoreY, from: S.set.from, fromSub: S.set.fromSub, anim: S.set.anim };
    S.set.anim = ''; S.set.hl = ''; S.set.focus = ''; S.set.restoreY = null; S.set.from = ''; S.set.fromSub = false;
    if (!job.hl && !job.focus && job.y == null && !job.from && !job.anim) return;
    setTimeout(() => {
      if (S.tab !== 'settings') return;
      const wide = sxWide();
      if (job.y != null) {
        if (!wide) window.scrollTo(0, job.y);
        else { const d = $('.sx-det'); if (d && d.getBoundingClientRect().top < 72) window.scrollTo(0, 0); }
      }
      const fo = el => { try { el.focus({ preventScroll: true }); } catch (e) {  } };
      if (job.hl) sxFlash(job.hl, job.focus);
      else if (job.focus) { const f = $(job.focus); if (f) fo(f); }
      else if (job.from) { const a = job.fromSub ? $('.sx #sx-' + S.set.sec + '-' + job.from) || $('.sx a[href="#' + sxHash(S.set.sec, job.from) + '"]') : $('.sx [data-sx-sec="' + job.from + '"]'); if (a) fo(a); }
      else if (job.anim) { const h = $('#sxH'); if (h) fo(h); }
    }, 30);
  }
  function sxFlash(sel, focusSel) {
    let el = null; try { el = $(sel); } catch (e) { el = null; }
    if (!el) return;
    const row = (el.closest && el.closest('.sx-it, .su-acc, .sx-wr, .sx-trow, .sx-segrow, .sx-card')) || el;
    const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    try { row.scrollIntoView({ block: 'center', behavior: reduce ? 'auto' : 'smooth' }); } catch (e) {  }
    row.classList.remove('sx-hl'); void row.offsetWidth; row.classList.add('sx-hl');
    setTimeout(() => row.classList.remove('sx-hl'), 2400);
    let f = null; try { f = focusSel ? $(focusSel) : null; } catch (e) { f = null; }
    if (!f && el.matches && el.matches('button, a[href], input, select, textarea')) f = el;
    if (f) { try { f.focus({ preventScroll: true }); } catch (e) {  } }
  }
  function histPerHTML(per, SECN) {
    const ent = Object.entries(per || {});
    if (!ent.length) return '';
    const vals = Array.from(new Set(ent.map(e => String(e[1]))));
    return '<div class="cap num" style="margin-top:8px">' + (vals.length === 1 && ent.length > 1 ? '범위별 시작: 모든 범위(' + ent.length + '곳) ' + esc(vals[0])
      : '범위별 시작: ' + ent.map(([k, v]) => esc(SECN[k] || k) + ' ' + esc(v)).join(' · ')) + '</div>';
  }
  function histJobsHTML(jobs) {
    const row = j => { const pc = j.total ? Math.max(0, Math.min(100, num(j.done) / num(j.total) * 100)) : null; return '<div class="srow"><span class="dot' + (j.phase === 'done' ? '' : ' w') + '"></span><div style="min-width:0;flex:1"><b>' + esc(String(j.key).replace(/:extend$|:job$/, '')) + '</b><div class="cap num">' + (j.phase === 'done' ? '완료' + (j.note ? ' · ' + esc(hs(j.note)) : '') : '가져오는 중' + (pc != null ? ' ' + pc.toFixed(0) + '%' : '') + (j.eta ? ' · 약 ' + Math.max(1, Math.round(num(j.eta) / 60)) + '분 남음' : '')) + '</div></div></div>'; };
    const run = jobs.filter(j => j.phase !== 'done'), done = jobs.filter(j => j.phase === 'done');
    if (done.length <= 3) return jobs.map(row).join('');
    return run.map(row).join('') + '<div class="sfold">' + uiFold('sx:hjobs', { cls: 'plain', head: '<span class="cap">끝난 가져오기 ' + done.length + '건</span>', body: () => done.map(row).join(''), label: '끝난 가져오기 ' + done.length + '건', mem: false }) + '</div>';
  }
  function sFold(rows, key) {
    return uiPaged('sx:' + (key || 'fold'), rows, x => x, { unit: '개' });
  }
  const REV_FILL = [['recent:1', '최근부터 채우기', '최근 날부터 · 한 건씩'], ['oldest:1', '오래된 날부터', '차례로 · 한 건씩'], ['recent:3', '동시에 여러\u00a0건', '3건씩 · 더 빠르게(사용량 같음)']];
  const rpDur = s => { s = Math.max(0, Math.round(num(s))); if (s < 60) return s + '초'; if (s < 3600) return Math.floor(s / 60) + '분' + (s % 60 ? ' ' + (s % 60) + '초' : ''); const h = Math.floor(s / 3600), mi = Math.floor((s % 3600) / 60); return h + '시간' + (mi ? ' ' + mi + '분' : ''); };
  const clockTxt = t => { const ms = num(t) * 1000, d = new Date(ms + KST_MS), hm = pad2(d.getUTCHours()) + ':' + pad2(d.getUTCMinutes());
    const dd = Math.floor((ms + KST_MS) / 864e5) - Math.floor((Date.now() + KST_MS) / 864e5);
    return dd === 0 ? hm : dd === 1 ? '내일 ' + hm : dd === -1 ? '어제 ' + hm : (d.getUTCMonth() + 1) + '월 ' + d.getUTCDate() + '일 ' + hm; };
  const revItemTxt = c => c.kind === 'weekly' ? (c.label || c.key) + ' 주간' : (/^\d{4}-\d{2}-\d{2}$/.test(String(c.key)) ? +String(c.key).slice(5, 7) + '월 ' + +String(c.key).slice(8, 10) + '일' : String(c.key)) + ' 일간';
  function revProgHTML(P, rf) {
    if (!P) return '';
    const runs = arr(P.runs), now = Date.now() / 1000;
    const qD = sum(runs, r => num((r.q || {}).daily)), qW = sum(runs, r => num((r.q || {}).weekly));
    const cur = [].concat(...runs.map(r => arr(r.current)));
    const par = Math.max(1, ...runs.map(r => num(r.parallel) || 1));
    const avg = P.avgSec ? '한 건 평균 ' + rpDur(P.avgSec) : '';
    const eta = Math.max(0, ...runs.map(r => num(r.etaAt)));
    const bl = P.backlog || {}, bd = bl.daily || {}, bw = bl.weekly || {};
    let h = '<div class="rvprog">';
    if (runs.length) {
      const c0 = cur[0];
      h += '<div class="rph pvx"><span class="dot pulse"></span><b>' + (c0 ? '지금 쓰는 중' : '다음 건 준비 중') + '</b>' + (c0 ? '<span class="num">' + esc(revItemTxt(c0)) + (cur.length > 1 ? ' 외 ' + (cur.length - 1) + '건' : '') + '</span>' : '')
        + (c0 && c0.startedAt ? '<span class="sp"></span><span class="cap num">' + rpDur(now - num(c0.startedAt)) + '째</span>' : '') + '</div>';
      const bits = [(qD || qW) ? '대기 일간 ' + qD + ' · 주간 ' + qW : '남은 대기 없음', avg, eta ? '예상 완료 약 ' + clockTxt(eta) : '', par > 1 ? '동시에 ' + par + '건' : ''].filter(Boolean);
      h += '<div class="cap num rpl pvx">' + esc(bits.join(' · ')) + '</div>';
      const dn = sum(runs, r => num(r.done)), rg = sum(runs, r => num(r.regen)), fl = sum(runs, r => num(r.fail));
      if (dn || rg || fl) h += '<div class="cap num rpl pvx">이번 작업 ' + dn + '건 완료' + (rg ? ' · 다시 쓴 것 ' + rg + '건' : '') + (fl ? ' · 실패 ' + fl + '건' : '') + '</div>';
      const er = runs.map(r => r.lastError).filter(Boolean)[0];
      if (er) h += '<div class="cap wtxt rpl">마지막 오류 · ' + esc(errTxt(String(er).slice(0, 120))) + '</div>';
    } else {
      const L = P.last;
      h += '<div class="rph pvx"><span class="dot' + (L && num(L.fail) ? ' w' : '') + '"></span><b>대기 없음</b>' + (avg ? '<span class="sp"></span><span class="cap num">' + esc(avg) + '</span>' : '') + '</div>';
      if (L && L.ended_at) h += '<div class="cap num rpl pvx">마지막 작업 ' + esc(clockTxt(L.ended_at)) + ' · ' + num(L.done) + '건 · ' + esc(rpDur(L.secs)) + (num(L.regen) ? ' · 다시 쓴 것 ' + num(L.regen) + '건' : '') + (num(L.fail) ? ' · 실패 ' + num(L.fail) + '건' : '') + '</div>';
      if (L && L.fail && L.last_error) h += '<div class="cap wtxt rpl">마지막 오류 · ' + esc(errTxt(String(L.last_error).slice(0, 120))) + '</div>';
    }
    const aD = num(bd.auto), aW = num(bw.auto), mD = num(bd.manual), mW = num(bw.manual);
    const kb = (d9, w9) => [d9 ? '일간 ' + d9 : '', w9 ? '주간 ' + w9 : ''].filter(Boolean).join(' · ');
    if (aD || aW || mD || mW) {
      const bits = [];
      if (aD || aW) {
        const om = Math.max(1, num(bd.oldMax) || 5), od = bd.old != null ? num(bd.old) : 0, rd = bd.recent != null ? num(bd.recent) : aD - od;
        const pr = Math.max(1, num(bw.perRun) || 2), tD = rd + Math.min(od, om), tW = Math.min(aW, pr), restD = od - Math.min(od, om), restW = aW - tW;
        const days = Math.max(restD ? Math.ceil(restD / om) : 0, restW ? Math.ceil(restW / pr) : 0);
        bits.push('자동 ' + kb(aD, aW) + '건은 오늘 밤 23:50 전후 최대 일간 ' + tD + '건' + (aW ? ' · 주간 ' + tW + '건' : '')
          + (restD || restW ? ', 이후 하루 ' + [restD ? (restW ? '일간 ' : '') + om + '일씩' : '', restW ? '주간 ' + pr + '건씩' : ''].filter(Boolean).join(' · ') + '(약 ' + days + '일)' : ''));
      }
      if (mD || mW) bits.push('수동 ' + kb(mD, mW) + '건은 리뷰 방식이 바뀌었거나 빠진 옛 리뷰라 전체 채우기로 ' + (rf && rf.order === 'oldest' ? '오래된 날부터' : '최근 날부터') + ' 써요');
      const rpz = S.D && S.D.reviewPause && S.D.reviewPause.on;
      const fb = !(mD || mW) || runs.length ? '' : P.fillReq ? '<div class="cap num" style="margin-top:6px">전체 채우기 요청함 · 1분 안에 시작해요</div>'
        : rpz ? '<div class="cap" style="margin-top:6px">자동 생성 멈춤을 풀면 전체 채우기를 쓸 수 있어요</div>'
        : '<div style="margin-top:8px"><button class="btn sm" data-a="revFillAll">전체 채우기</button></div>';
      h += '<div class="rpm pvx"><b class="num">다시 쓸 리뷰 · ' + kb(aD + mD, aW + mW) + '</b><div class="cap num">' + bits.join(' · ') + (mD || mW ? '' : ' 다시 써요') + '</div>' + fb + '</div>';
    }
    return h + '</div>';
  }
  const REV_LEN = {
    daily: [['short', '간단히', '요약 한 줄 · 관찰 1~2개'], ['normal', '보통', '원인 · 관찰 3개까지'], ['long', '자세히', '원인·흐름 · 관찰 4개 · 다음 할 일']],
    weekly: [['short', '간단히', '흐름 한 줄 · 패턴 1~2개'], ['normal', '보통', '흐름 · 패턴 2~3개 · 규칙'], ['long', '자세히', '흐름 · 패턴 3~4개 · 다음 할 일']] };
  function authLoad(force) {
    const c = S.auth;
    if (!force && c && (c.st === 'load' || Date.now() - c.t < 60000)) return c;
    const nc = S.auth = { st: 'load', t: Date.now(), d: c && c.d };
    fetch('/api/auth/status', { cache: 'no-store', credentials: 'same-origin' }).then(r => r.ok ? r.json() : null).then(j => {
      if (S.auth !== nc) return;
      nc.st = j && j.ok ? 'ok' : 'none'; nc.d = j && j.ok ? j : null; nc.t = Date.now();
      if (S.tab === 'settings' && !S.locked) renderView();
    }).catch(() => { if (S.auth === nc) { nc.st = 'err'; nc.t = Date.now(); if (S.tab === 'settings' && !S.locked) renderView(); } });
    return nc;
  }
  const AU_KEYS = ['au:cur', 'au:new', 'au:new2'];
  function loginBody() {
    const c = authLoad(), d = c && c.d;
    if (!d) return c && (c.st === 'none' || c.st === 'err') ? '<div class="sx-empty">' + (c.st === 'none' ? '이 서버는 웹 로그인 기능이 없어요' : '로그인 상태를 불러오지 못했어요') + '</div>' : sxSlotWait();
    if (d.enabled && !d.authed) return '<div class="sx-empty">로그인이 필요해요</div>';
    if (!d.enabled) {
      return sxIt('sx-acc-state', '로그인 꺼짐', d.demo ? '데모 모드 — 로그인 없이 합성 데이터만 보여 줘요' : '지금은 이 주소에 닿는 사람은 누구나 화면을 볼 수 있어요', '',
        d.demo ? null : { exp: () => '<div class="cap" title="처음 켤 땐 이 컴퓨터에서 비밀번호를 만들어요">켜기 = config.json web.login.enabled 를 true 로 → pm2 restart tj-web</div>' });
    }
    const lab = (id, t, mt) => '<label class="lab" for="' + id + '" style="display:block' + (mt ? ';margin-top:10px' : '') + '">' + esc(t) + '</label>';
    const inp = (id, key, ac, enter) => '<input class="field" style="width:100%" id="' + id + '" type="password" autocomplete="' + ac + '" maxlength="256" spellcheck="false" autocapitalize="off" data-draft="' + key + '"' + (enter ? ' data-enter="authPwSave"' : '') + (S.authBusy ? ' disabled' : '') + '>';
    const form = !S.authPw ? '' : '<div class="sx-pw">'
      + lab('auCur', '지금 비밀번호') + inp('auCur', AU_KEYS[0], 'current-password')
      + lab('auNew', '새 비밀번호 (' + num(d.pwMin || 10) + '자 이상)', true) + inp('auNew', AU_KEYS[1], 'new-password')
      + lab('auNew2', '새 비밀번호 한 번 더', true) + inp('auNew2', AU_KEYS[2], 'new-password', true)
      + (S.authErr ? '<div class="cap etxt" role="alert" style="margin-top:8px">' + esc(errTxt(S.authErr)) + '</div>' : '')
      + '<div class="frm"><button class="btn sm pri" data-a="authPwSave"' + (S.authBusy ? ' disabled' : '') + '>' + (S.authBusy ? '바꾸는 중…' : '바꾸기') + '</button><button class="btn sm" data-a="authPw">취소</button><span class="cap">바꾸면 이 기기 말고는 모두 로그아웃돼요</span></div></div>';
    return sxIt('sx-acc-state', '이 기기', '<span class="num">' + esc(fmtTs(d.exp)) + '</span>까지 · ' + num(d.idleDays) + '일 안 쓰면 다시 물어요 · 기기 ' + num(d.sessions) + '개', sxPill('ok', '로그인'))
      + '<div class="sx-acts" id="sx-acc-btns"><button class="btn sm" data-a="authPw" aria-expanded="' + !!S.authPw + '">비밀번호 바꾸기</button><button class="btn sm" data-a="authLogoutAll">모든 기기 로그아웃</button><span class="sp"></span><button class="btn sm danger" data-a="authLogout">로그아웃</button></div>'
      + form
      + '<div class="cap sx-note">잊었으면 tj-bot 이 도는 컴퓨터에서 <span class="mono">python3 tools/reset_password.py</span> · 켜기·끄기 = config.json web.login 후 tj-web 재시작</div>';
  }
  async function authPost(path, body) {
    const d0 = S.auth && S.auth.d, hd = { 'Content-Type': 'application/json' };
    if (d0 && d0.csrf) hd['X-TJ-CSRF'] = d0.csrf;
    const r = await fetch(path, { method: 'POST', credentials: 'same-origin', cache: 'no-store', headers: hd, body: JSON.stringify(body || {}) });
    let d = null;
    try { d = await r.json(); } catch (e) { d = null; }
    return { st: r.status, d: d || {} };
  }
  function wipeLocal() {
    const KEEP = { tj_v2_theme: 1, tj_v2_scheme: 1, tj_v2_hide: 1, tj_v2_rand: 1, tj_v2_pgsize: 1 };
    [[window.localStorage, KEEP], [window.sessionStorage, null]].forEach(([st, keep]) => {
      try { const ks = []; for (let i = 0; i < st.length; i++) { const k = st.key(i); if (k && k.indexOf('tj_') === 0 && !(keep && keep[k])) ks.push(k); } ks.forEach(k => { try { st.removeItem(k); } catch (e) {  } }); } catch (e) {  }
    });
  }
  async function authLogout(all) {
    if (S.authBusy) return;
    S.authBusy = true;
    lockOut('logout');
    let ok = false;
    try { const x = await authPost(all ? '/api/auth/logout_all' : '/api/logout', {}); ok = (x.st === 200 && x.d.ok) || x.st === 401; } catch (e) { ok = false; }
    try { await Promise.race([clearCache(), new Promise(res => setTimeout(res, 2000))]); } catch (e) {  }
    wipeLocal();
    S.authBusy = false;
    if (ok) { location.replace('/login'); return; }
    lockOut('logoutFail');
  }
  async function authPwSave() {
    if (S.authBusy) return;
    const cur = S.drafts[AU_KEYS[0]] || '', nw = S.drafts[AU_KEYS[1]] || '', nw2 = S.drafts[AU_KEYS[2]] || '';
    const min = (S.auth && S.auth.d && S.auth.d.pwMin) || 10;
    const err = !cur ? '지금 비밀번호를 넣어 주세요' : nw.length < min ? '새 비밀번호는 ' + min + '자 이상이어야 해요' : nw !== nw2 ? '새 비밀번호 두 칸이 달라요' : nw === cur ? '지금과 다른 비밀번호로 바꿔 주세요' : '';
    if (err) { S.authErr = err; renderView(); return; }
    S.authBusy = true; S.authErr = ''; renderView();
    let x = null;
    try { x = await authPost('/api/auth/password', { current: cur, new: nw }); } catch (e) { x = null; }
    S.authBusy = false;
    if (S.locked) return;
    if (x && x.st === 200 && x.d.ok) {
      AU_KEYS.forEach(k => { delete S.drafts[k]; });
      S.authPw = false; S.authErr = '';
      if (x.d.csrf && S.auth && S.auth.d) S.auth.d.csrf = x.d.csrf;
      S.csrf = '';
      try { const st9 = window.__tjSetup && window.__tjSetup.U && window.__tjSetup.U.st; if (st9) st9.csrf = ''; } catch (e) {  }
      toast('비밀번호를 바꿨어요' + (x.d.revoked ? ' · 다른 기기 ' + num(x.d.revoked) + '개는 로그아웃됐어요' : ''));
      authLoad(true); renderView();
      return;
    }
    if (x && x.st === 401) return;
    S.authErr = x ? String((x.d && x.d.error) || ('바꾸지 못했어요 (HTTP ' + x.st + ')')) : '서버에 연결하지 못했어요';
    if (x && x.st === 403) delete S.drafts[AU_KEYS[0]];
    renderView();
  }
  const COV_SEV = { hard: ['e', 'API 한도'], partial: ['w', '일부 누락 가능'], bot_cap: ['a', '봇 한계'], not_collected: ['g', '미수집'], no_permission: ['g', '키 권한 없음'] };
  const COV_ST = { done: ['ok', '가져옴'], running: ['w', '가져오는 중'], window_only: ['g', '기본 범위만'] };
  const covDur = s9 => { s9 = num(s9); if (!(s9 > 0)) return '—'; if (s9 < 90) return Math.max(1, Math.round(s9)) + '초'; if (s9 < 5400) return Math.round(s9 / 60) + '분'; return (s9 / 3600).toFixed(s9 < 36000 ? 1 : 0) + '시간'; };
  const etaTxt = e9 => !e9 ? '—' : (Math.round(num(e9[0])) === Math.round(num(e9[1])) ? covDur(e9[0]) : covDur(e9[0]) + '~' + covDur(e9[1]));
  function covLoad() {
    const c = S.cov;
    if (c && (c.st === 'load' || Date.now() - c.t < 600000)) return c;
    const nc = S.cov = { st: 'load', t: Date.now(), d: c && c.d };
    fetch('/api/coverage_limits', { cache: 'no-store' }).then(r => r.status === 401 ? (onUnauthorized(), null) : r.ok ? r.json() : null).then(j => {
      if (S.cov !== nc) return;
      nc.st = j && j.ok && j.data ? 'ok' : 'err'; if (j && j.ok) nc.d = j.data; nc.t = Date.now();
      if (S.tab === 'settings') renderView();
    }).catch(() => { if (S.cov === nc) { nc.st = 'err'; nc.t = Date.now(); if (S.tab === 'settings') renderView(); } });
    return nc;
  }
  function covSplit(t) {
    t = String(t || '').trim();
    const mm = t.length > 48 ? /^(.{12,}?)(?:\.\s+|\s—\s)/.exec(t) : null;
    if (!mm || t.length - mm[0].length < 12) return [t, ''];
    return [mm[1].replace(/\.$/, ''), t.slice(mm[0].length)];
  }
  function coverageBody() {
    const c = covLoad(), d = c && c.d;
    const head = '<div class="cap covgen">' + (d && d.generated_at ? esc(ago(d.generated_at)) + ' 갱신 · 하루 한 번 · ' : '') + '이 한계보다 이른 매수는 원가 미확인으로 남을 수 있어요</div>';
    if (!d) return '<div class="covcard">' + (c && c.st === 'err' ? '<div class="sx-empty">수집 한계를 불러오지 못했어요 · <button class="link" data-a="covRetry">다시 시도</button></div>' : sxSlotWait()) + '</div>';
    const un = arr(d.unavailable);
    const rollTxt = u => u.rolling_kind === 'calendar_month' ? ' <span class="cap num">달력 3개월(매월 1일 기준) · 달마다 앞으로 밀려요</span>' : u.rolling_days ? ' <span class="cap num">지금 기준 ' + num(u.rolling_days) + '일 · 날마다 앞으로 밀려요</span>' : '';
    const unRow = u => { const sv = COV_SEV[u.severity] || ['g', u.severity || '—'], rs9 = covSplit(hs(u.reason_ko || ''));
      const top = '<b>' + esc(u.label || u.source_id) + '</b>' + (u.before ? ' <span class="num">' + esc(u.before) + ' 이전</span>' : '') + ' <span class="pill ' + sv[0] + ' sm">' + esc(sv[1]) + '</span>' + rollTxt(u) + '<div class="cap">' + esc(rs9[0]) + '</div>';
      return rs9[1] ? '<details class="covd covun"><summary><div style="min-width:0;flex:1">' + top.replace('<div class="cap">', '<div class="cap" style="margin-left:0">') + '</div></summary><div class="cap" style="margin:2px 0 4px">' + esc(rs9[1]) + '</div></details>'
        : '<div class="srow"><div style="min-width:0;flex:1">' + top + '</div></div>'; };
    const unMain = un.filter(u => u.severity === 'hard' || u.severity === 'partial'), unRest = un.filter(u => !(u.severity === 'hard' || u.severity === 'partial'));
    const sevCnt = Object.keys(COV_SEV).map(k => [k, un.filter(u => u.severity === k).length]).filter(x => x[1]).map(x => '<span class="pill ' + COV_SEV[x[0]][0] + ' sm">' + esc(COV_SEV[x[0]][1]) + ' ' + x[1] + '</span>').join(' ');
    const unH = un.length ? '<div class="lab">이 기간 이전은 가져올 수 없음</div><div class="chiprow" style="margin:2px 0 6px">' + sevCnt + '</div>' + unMain.map(unRow).join('')
      + (unRest.length ? '<details class="covd"><summary><b>그 밖의 한계</b> <span class="cap num">봇 한계·미수집·키 권한 ' + unRest.length + '가지</span></summary>' + unRest.map(unRow).join('') + '</details>' : '') : '';
    const srcs = arr(d.sources);
    const chainH = srcs.filter(x => x.kind === 'chain').map(x => {
      const ws = arr(x.wallets);
      const rows = ws.map(w => { const st9 = COV_ST[w.status] || ['g', w.status || '—'];
        return '<div class="kv"><span>' + ownH(w.label || short(w.wallet)) + ' <span class="pill ' + st9[0] + ' sm">' + esc(st9[1]) + '</span></span><span class="num">' + esc(w.achieved_start || '—') + (w.first_record ? ' <span class="mut">· 첫 기록 ' + esc(w.first_record) + '</span>' : '') + '</span></div>'; }).join('');
      return '<details class="covd"><summary><b>' + esc(x.label || x.chain) + '</b> <span class="cap num">가장 이른 날 ' + esc(x.earliest_retrievable || '—') + ' · 지갑 ' + ws.length + '개</span></summary>'
        + '<div class="cap" style="margin:6px 0 4px">' + esc(hs(x.reason_ko || '')) + '</div>' + rows + '</details>'; }).join('');
    const exS = srcs.filter(x => x.kind === 'exchange' && x.bot_uses !== false);
    const exH = exS.length ? '<details class="covd"><summary><b>거래소 · 가장 이른 날 → 봇이 가져온 시작일</b> <span class="cap num">' + exS.length + '개 항목</span></summary>' + exS.map(x =>
      '<div class="kv"><span>' + esc(x.label || x.id) + '</span><span class="num">' + esc(x.earliest_retrievable || '—') + ' → ' + esc(x.achieved_start || '기본 범위') + (x.rolling_kind === 'calendar_month' ? ' <span class="pill e sm">달력 3개월 한도</span>' : x.rolling_limit_days ? ' <span class="pill e sm">' + num(x.rolling_limit_days) + '일 한도</span>' : '') + (x.collector_error ? ' <span class="pill w sm" title="' + esc(errTxt(String(x.collector_error))) + '">최근 오류</span>' : '') + '</span></div>').join('') + '</details>' : '';
    const etaRows = srcs.filter(x => x.eta && x.kind === 'chain');
    const etaH = etaRows.length ? '<details class="covd"><summary><b>과거 데이터 가져오는 데 걸리는 시간(예상)</b> <span class="cap">지갑 1개 기준 · 활동이 많을수록 오래</span></summary>'
      + (S.mobile ? etaRows.map(x => '<div class="kv"><span>' + esc(x.label) + '</span><span class="num">' + ['1y', '5y', '9y'].map(y => y.replace('y', '년') + ' ' + etaTxt(x.eta[y])).join(' · ') + '</span></div>').join('')
        : '<table class="stbl"><thead><tr><th scope="col" class="l">체인</th><th scope="col">1년</th><th scope="col">2년</th><th scope="col">5년</th><th scope="col">9년</th></tr></thead><tbody>' + etaRows.map(x => '<tr><td class="l">' + esc(x.label) + '</td>' + ['1y', '2y', '5y', '9y'].map(y => '<td class="num">' + etaTxt(x.eta[y]) + '</td>').join('') + '</tr>').join('') + '</tbody></table>') + '</details>' : '';
    const ny = d.nine_year;
    const nyH = ny && ny.verdict_ko ? '<div class="cap" style="margin-top:10px">' + esc(hs(ny.verdict_ko)) + '</div>' : '';
    const rs = arr(d.cost_unknown_reasons);
    const rsH = rs.length ? '<details class="covd"><summary><b>원가 미확인으로 남을 수 있는 이유</b> <span class="cap num">' + rs.length + '가지</span></summary>' + rs.map(r => '<div class="srow"><div style="min-width:0;flex:1">' + esc(hs(r.reason_ko || '')) + (r.count != null ? ' <span class="cap num">(원장 ' + nf('ko-KR').format(num(r.count)) + '건)</span>' : '') + '</div></div>').join('') + '</details>' : '';
    return '<div class="covcard">' + head + unH
      + (chainH ? '<div class="lab" style="margin-top:16px">체인 · 지갑별로 가져온 시작일</div>' + chainH : '')
      + (exH || etaH || rsH ? '<div style="margin-top:12px">' + exH + etaH + rsH + '</div>' : '') + covApiH(d.api_limits) + nyH + '</div>';
  }
  function covApiH(t) {
    if (!t || !arr(t.exchanges).length) return '';
    const act = t.actions || {}, col = t.columns || {};
    const actName = c => String(act[c] || c).split(' — ')[0];
    const rowH = r => { const todo = String(r.todo || '').split(',').map(x => x.trim()).filter(Boolean);
      return '<div class="covx"><div class="covxk">' + esc(r.kind || '') + '</div><dl>'
        + [['api', r.api], ['bot', r.bot], ['miss', r.miss]].filter(x => x[1]).map(x => '<dt>' + esc(col[x[0]] || x[0]) + '</dt><dd' + (x[0] === 'miss' && !/^없음/.test(x[1]) ? ' class="wtxt"' : '') + '>' + esc(x[1]) + '</dd>').join('')
        + (todo.length ? '<dt>' + esc(col.todo || '이용자가 할 일') + '</dt><dd>' + todo.map(c => '<span class="pill a sm" title="' + esc(act[c] || '') + '">' + esc(actName(c)) + '</span>').join(' ') + '</dd>' : '') + '</dl></div>'; };
    const srcH = e => '<details class="covd covxs"><summary><b>' + esc(e.name || e.id) + '</b>' + (e.used ? ' <span class="pill ok sm">사용 중</span>' : '') + ' <span class="cap num">' + arr(e.rows).length + '가지</span></summary>'
      + (e.perm ? '<div class="cap covxp">키 권한 · ' + esc(e.perm) + '</div>' : '') + arr(e.rows).map(rowH).join('') + '</details>';
    const grp = (list, title) => { const L = arr(list); if (!L.length) return '';
      const hasUsed = L.some(e => e.used === true || e.used === false), used = hasUsed ? L.filter(e => e.used) : L, rest = hasUsed ? L.filter(e => !e.used) : [];
      return '<div class="lab" style="margin-top:12px">' + esc(title) + '</div>' + used.map(srcH).join('')
        + (rest.length ? '<details class="covd"><summary><b>그 밖의 ' + esc(title) + '</b> <span class="cap num">연결 안 함 · ' + rest.length + '곳</span></summary>' + rest.map(srcH).join('') + '</details>' : ''); };
    const acts = Object.keys(act).map(c => '<div class="srow"><div style="min-width:0;flex:1"><b>' + esc(actName(c)) + '</b><div class="cap">' + esc(String(act[c]).split(' — ').slice(1).join(' — ')) + '</div></div></div>').join('');
    return '<details class="covd covapi"><summary><b>거래소·체인별 한계 정리</b> <span class="cap">API 로 되는 것 · 안 되는 것 · 내가 할 일</span></summary>'
      + '<div class="cap" style="margin:6px 0 2px">봇은 API 한도를 우회하지 않아요(거래소 아카이브 신청·CSV 가져오기 없음). 못 받는 부분은 아래 \'이용자가 할 일\'로 직접 정해 주세요. ' + esc(t.window_note || '') + '</div>'
      + grp(t.exchanges, '거래소') + grp(t.chains, '체인') + grp(t.perps, '퍼프 덱스')
      + (acts ? '<details class="covd"><summary><b>이용자가 할 수 있는 일</b> <span class="cap num">' + Object.keys(act).length + '가지</span></summary>' + acts + '</details>' : '')
      + (t.updated ? '<div class="cap" style="margin-top:8px">정리 기준일 <span class="num">' + esc(t.updated) + '</span></div>' : '') + '</details>';
  }
  function locName(s0) {
    let t = String(s0 == null ? '' : s0);
    if (pvOn() && typeof ownIn === 'function') t = ownIn(t);
    if (!pvOn() || !/\d/.test(t)) return t;
    return t.split(/(0x[0-9a-fA-F]{6,40}|[A-Za-z0-9]{3,10}…[A-Za-z0-9]{3,6}|[1-9A-HJ-NP-Za-km-z]{32,44}|[A-Za-z]{2,}\s[vV]\d{1,2}(?![\d,.]))/).map((x, i) => (i % 2 ? x : x.replace(/\d[\d,.]*/g, () => pvW(PVM.n)))).join('');
  }
  function pvNameRe() {
    if (!(S.hide || S.rand)) return null;
    const D = S.D, su = typeof window !== 'undefined' ? window.__tjSetup : null, st = su && su.U && su.U.st, oa = S.oa && S.oa.d ? S.oa.d : null;
    const cov9 = S.cov && S.cov.d, lkc9 = (S.of && S.of.lkc) || {};
    const k = [D && D.walletAlias, D && D.wallets, D && D.rabby && D.rabby.wallets, st && st.wallets, st && st.perp && st.perp.wallets, D && D.of,
      D && D.venues, D && D.rbDebts, D && D.deposits, D && D.memos, D && D.plans, D && D.dayMemos, S.dm && S.dm.local, oa, D && D.f && D.f.coins, cov9,
      st && st.telegram, su && su.U && su.U.tg && su.U.tg.bot];
    Object.keys(lkc9).sort().forEach(a9 => k.push(lkc9[a9] && lkc9[a9].rows));
    const C = pvNameRe;
    if (C.k && C.k.length === k.length && k.every((x, i) => x === C.k[i])) return C.re;
    const forms = t => { const o = [t]; try { if (typeof hs === 'function') o.push(hs(t, 0, 1)); if (typeof revTxt === 'function') o.push(revTxt(t, 1)); } catch (e) {  } return o; };
    const cl = x => String(x == null ? '' : x).replace(/\s+/g, ' ').trim();
    const gen = x => /^(?:지갑|메모)(?: [A-Z]{1,3})?$/i.test(x) || (typeof ownGen === 'function' && ownGen(x));
    if (!C.letter) { try { C.letter = new RegExp('\\p{L}', 'u'); } catch (e) { C.letter = /[A-Za-z\u00C0-\uFFFF]/; } }
    const hasL = x => C.letter.test(x);
    const set = new Set(), setB = new Set(), groups = [], mset = new Set(), A9 = v => (Array.isArray(v) ? v : []), adr = x => /^(?:0x[0-9a-fA-F]{6,64}|[A-Za-z0-9]{3,12}…[A-Za-z0-9]{3,10})$/.test(x);
    const base = x => typeof ownBase === 'function' && ownBase(x);
    const add = v => { const g = []; forms(cl(v)).forEach(x => { x = cl(x); if (x && (x.length >= 2 || hasL(x)) && g.indexOf(x) < 0 && !gen(x) && !adr(x)) { g.push(x); (base(x) ? setB : set).add(x); } }); if (g.length) groups.push(g); };
    const addM = v => { const t0 = cl(v && typeof v === 'object' ? v.memo : v); if (!t0 || t0 === '—') return;
      [t0, t0.slice(0, 40).trim()].forEach(t1 => forms(t1).forEach(x => { x = cl(x); if (x.length >= 3 && hasL(x) && !gen(x) && !base(x)) mset.add(x); })); };
    if (k[0] && typeof k[0] === 'object') Object.keys(k[0]).forEach(a => add(k[0][a]));
    [k[1], k[2], k[3], k[4], k[5]].forEach((A, i) => { if (Array.isArray(A)) A.forEach(w => add(w && (i === 0 || i === 4 ? w.alias : w.label))); });
    A9(k[6]).forEach(v => { if (v && v.kind === 'wallet' && v.name) add(String(v.name).replace(/ · 스테이킹$/, '').replace(/ ?지갑$/, '')); });
    A9(k[7]).forEach(x => add(x && x.wallet));
    const isEx9 = t9 => typeof EX_NAMES !== 'undefined' && Object.keys(EX_NAMES).some(e9 => EX_NAMES[e9] === t9 || e9 === String(t9).toLowerCase());
    const addW = v => { const t9 = cl(v).replace(/ · 스테이킹$/, ''); if (t9 && !isEx9(t9)) add(t9); };
    A9(k[5]).forEach(r => { if (!r) return; addM(r.memo);
      A9(r.hints).forEach(h9 => { if (h9 && h9.kind === 'my_wallet') add(h9.label); });
      A9(r.flags).forEach(f9 => { if (f9 && f9.kind === 'lookalike') add(f9.label); });
      ['links', 'candTop', 'returned'].forEach(f9 => A9(r[f9]).forEach(x9 => addW(x9 && x9.where))); });
    A9(cov9 && cov9.sources).forEach(s9 => A9(s9 && s9.wallets).forEach(w9 => add(w9 && w9.label)));
    Object.keys(lkc9).forEach(a9 => A9(lkc9[a9] && lkc9[a9].rows).forEach(x9 => addW(x9 && x9.where)));
    A9(k[8]).forEach(d => addM(d && d.memo));
    [k[9], k[11], k[12]].forEach(O => { if (O && typeof O === 'object') Object.keys(O).forEach(q9 => addM(O[q9])); });
    if (k[10] && typeof k[10] === 'object') Object.keys(k[10]).forEach(q9 => addM(k[10][q9] && k[10][q9].memo));
    if (oa) A9(oa.items).forEach(o => addM(o && o.memo));
    { const tg9 = k[16] || {}; [tg9.bot, tg9.chatName, tg9.pending && tg9.pending.bot, k[17] && k[17].username].forEach(v9 => { if (v9) add(v9); }); }
    const lo = new Set(Array.from(set).map(x => x.toLowerCase()));
    C.memo = new Set(Array.from(mset).map(x => x.toLowerCase()).filter(x => !lo.has(x)));
    C.tick = new Set(A9(k[14]).filter(c => c && +c.price > 0 && c.sym).map(c => String(c.sym).toUpperCase()));
    C.pub = new Set(); const pub9 = v => { const t9 = cl(v); if (t9) C.pub.add(t9.toUpperCase()); };
    if (typeof CHAIN_KO !== 'undefined' && CHAIN_KO) Object.keys(CHAIN_KO).forEach(c9 => { pub9(c9); pub9(CHAIN_KO[c9]); });
    A9(k[14]).forEach(c => A9(c && c.locs).forEach(l9 => { if (l9) { pub9(l9.ch); pub9(l9.pname); pub9(l9.iname); if (l9.pname && l9.iname) pub9(l9.pname + ' ' + l9.iname); } }));
    A9(k[7]).forEach(d9 => { if (d9) { pub9(d9.where); pub9(d9.chain); } });
    const reL = A => Array.from(new Set(A)).sort((a, b) => b.length - a.length).map(x => x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/ /g, '\\s+'));
    const L = reL(Array.from(set).concat(Array.from(mset)));
    const mkRe = L9 => (L9.length ? new RegExp('(^|[^\\d,.]|[,.](?!\\d))(' + L9.join('|') + ')(?!\\d|[,.]\\d)( ?지갑(?![가-힣A-Za-z0-9]))?', 'gi') : null);
    C.k = k; C.re = mkRe(L);
    C.reN = setB.size ? mkRe(reL(Array.from(set).concat(Array.from(setB), Array.from(mset)))) : C.re;
    if (typeof ownSeed === 'function') ownSeed(groups);
    return C.re;
  }
  function locMask(t) {
    return String(t).split(/(0x[0-9a-fA-F]{6,40}|[A-Za-z0-9]{3,10}…[A-Za-z0-9]{3,6}|[1-9A-HJ-NP-Za-km-z]{32,44})/).map((x, i) => (i % 2 ? x : x.replace(/\d[\d,.]*/g, () => pvW(PVM.n)))).join('');
  }
  function nmKey(s0) { let h = 5381; const t = String(s0 == null ? '' : s0); for (let i = 0; i < t.length; i++) h = ((h * 33) ^ t.charCodeAt(i)) >>> 0; return 'n' + h.toString(36) + '_' + t.length; }
  function locH(s0) { return '<span class="pvl">' + esc(locNameM(s0)) + '</span>'; }
  const locNameM = t => String(t == null ? '' : t).split(MK_RE).map((x, i) => (i % 2 ? x : locName(x))).join('');
  const OWN_MEMO = '메모';
  const ownNorm = t => String(t == null ? '' : t).replace(/\s+/g, ' ').trim();
  const ownKey = t => ownNorm(t).replace(/ ?지갑$/, '').toLowerCase() || ownNorm(t).toLowerCase();
  const ownGen = t => { const n = ownNorm(t); return /^(?:지갑|메모)(?: [A-Z]{1,3})?$/i.test(n) || /^(?:지갑|메모)(?: [A-Z]{1,3})?$/i.test(n.replace(/ ?지갑$/, '')); };
  const ownBase = t => { const n = ownNorm(t); return /^(?:지갑|wallet|월렛|account|계정)\s?#?\s?\d{1,3}(?:\s?번)?$/i.test(n) || /^\d{1,3}\s?(?:번\s?)?(?:지갑|wallet|월렛)$/i.test(n); };
  const ownAddr = t => /^(?:0x[0-9a-fA-F]{6,64}|[A-Za-z0-9]{3,12}…[A-Za-z0-9]{3,10}|[1-9A-HJ-NP-Za-km-z]{32,44})$/.test(t);
  function ownLet(i) { let o = ''; for (let n = i + 1; n > 0; n = Math.floor((n - 1) / 26)) o = String.fromCharCode(65 + (n - 1) % 26) + o; return o; }
  function ownSt() { const C = ownTok; if (!C.map) { C.map = new Map(); C.out = new Set(); C.n = 0; } return C; }
  function ownNew() {
    const C = ownSt(), R = pvNameRe, re = R.reN || R.re;
    for (let g = 0; g < 2000; g++) {
      const v = '지갑 ' + ownLet(C.n++);
      if (re) { re.lastIndex = 0; let hit = false; v.replace(re, (a, pre, nm, suf, off, all) => { if (ownEdge(nm, pre, all.slice(off + pre.length + nm.length))) hit = true; return a; }); re.lastIndex = 0; if (hit) continue; }
      C.out.add(v); return v;
    }
    const v = '지갑 ' + ownLet(C.n++); C.out.add(v); return v;
  }
  function ownSeed(groups) {
    const C = ownSt();
    (groups || []).map(g => g.map(ownNorm).filter(x => x && !ownGen(x))).filter(g => g.length).sort((a, b) => (nmKey(a[0]) < nmKey(b[0]) ? -1 : nmKey(a[0]) > nmKey(b[0]) ? 1 : 0)).forEach(g => {
      const hit = g.map(x => C.map.get(ownKey(x))).find(Boolean), v = hit || ownNew();
      g.forEach(x => { const k9 = ownKey(x); if (!C.map.has(k9) && !C.out.has(ownNorm(x))) C.map.set(k9, v); });
    });
  }
  function ownTok(t0) {
    const C = ownSt(), t = ownNorm(t0);
    if (!t || C.out.has(t) || ownGen(t)) return t;
    const k9 = ownKey(t);
    if (!C.map.has(k9) && typeof pvNameRe === 'function') pvNameRe();
    let v = C.map.get(k9);
    if (!v && ownAddr(t)) return t;
    if (!v) { v = ownNew(); C.map.set(k9, v); }
    return v;
  }
  const ownEdge = (nm, pre, nx) => /\d/.test(nm) || (!/[A-Za-z0-9가-힣]$/.test(String(pre || '')) && !(nm.length === 1 ? /^[A-Za-z0-9가-힣]/ : /^[A-Za-z0-9]/).test(String(nx || '')));
  const ownCommon = t => { const R = pvNameRe, u = ownNorm(t).toUpperCase(); return !!(R.tick && R.tick.has(u)) || !!(R.pub && R.pub.has(u)) || (typeof EX_NAMES !== 'undefined' && Object.keys(EX_NAMES).some(k => EX_NAMES[k] === t || k === String(t).toLowerCase())); };
  function ownProt(x) {
    const C = ownProt; if (!C.re) C.re = new RegExp('0x[0-9a-fA-F]{6,64}|[A-Za-z0-9]{3,12}…[A-Za-z0-9]{3,10}|\\b[1-9A-HJ-NP-Za-km-z]{32,44}\\b' + (typeof PV_PROT !== 'undefined' ? '|' + PV_PROT.source : ''), 'g');
    const R9 = []; C.re.lastIndex = 0; let m9; while ((m9 = C.re.exec(x))) { R9.push([m9.index, m9.index + m9[0].length]); if (!m9[0].length) C.re.lastIndex++; }
    return R9;
  }
  function ownRep(x, re, T9, names) {
    const R = pvNameRe, P9 = /\d/.test(x) || /…/.test(x) ? ownProt(x) : [];
    const inside = (L9, a9, b9) => L9.some(r9 => a9 >= r9[0] && b9 <= r9[1]);
    return x.replace(re, (a, pre, nm, suf, off, all) => {
      const st9 = off + pre.length, en9 = st9 + nm.length;
      if (inside(T9 || [], st9, en9) || P9.some(r9 => st9 >= r9[0] && en9 <= r9[1] && r9[1] - r9[0] > en9 - st9)) return a;
      if (!ownEdge(nm, pre, all.slice(off + pre.length + nm.length))) return a;
      if (!suf && typeof ownBase === 'function' && ownBase(nm) && /^\s?(?:개(?!월)|곳|건|군데|종(?![가료목합]))/.test(all.slice(off + a.length))) return a;
      const lo = ownNorm(nm).toLowerCase();
      if (!names && ownCommon(nm)) return a;
      if (R.memo && R.memo.has(lo)) return pre + OWN_MEMO + (suf || '');
      return pre + ownTok(nm);
    });
  }
  function ownScrub(t, names) {
    const s = String(t == null ? '' : t);
    if (!s || !(S.hide || S.rand)) return s;
    const re0 = typeof pvNameRe === 'function' ? pvNameRe() : null, C = ownSt(), n = ownNorm(s);
    const re = names && pvNameRe.reN !== undefined ? pvNameRe.reN : re0, strict = names === true;
    if (n && !C.out.has(n)) {
      const R = pvNameRe, lo = n.toLowerCase(), nk = C.map.get(ownKey(n));
      const whole = nk || (R.memo && R.memo.has(lo) ? OWN_MEMO : '');
      const pubW = () => !strict && typeof ownCommon === 'function' && ownCommon(n);
      if (whole && !pubW()) return s.replace(/^(\s*)[^]*?(\s*)$/, (a, l, r) => l + whole + r);
    }
    if (!re) return s;
    const T9 = [], tr = /지갑 [A-Z]{1,3}(?![A-Za-z0-9])/g; let m9;
    while ((m9 = tr.exec(s))) if (C.out.has(m9[0])) T9.push([m9.index, m9.index + m9[0].length]);
    return ownRep(s, re, T9, strict).replace(/(지갑 [A-Z]{1,3}) ?지갑(?![가-힣A-Za-z0-9])/g, '$1');
  }
  const ownScrubM = (t, names) => String(t == null ? '' : t).split(MK_RE).map((x, i) => (i % 2 ? x : ownScrub(x, names))).join('');
  function ownIn(t) {
    const re = typeof pvNameRe === 'function' ? pvNameRe() : null, C = ownSt(), n = ownNorm(t);
    if (!n || C.out.has(n)) return t;
    const whole = C.map.get(ownKey(n));
    if (whole) return whole;
    if (re && pvNameRe.memo && pvNameRe.memo.has(n.toLowerCase())) return OWN_MEMO;
    return re || pvNameRe.reN ? ownScrub(t, 'in') : t;
  }
  function ownNm(s0, kind) {
    const t = String(s0 == null ? '' : s0);
    if (!pvOn() || !t.trim()) return t;
    if (kind === 'm') return OWN_MEMO;
    const R = typeof pvNameRe === 'function' ? (pvNameRe(), pvNameRe) : null, C = ownSt(), n = ownNorm(t);
    if (R && R.memo && R.memo.has(n.toLowerCase()) && !C.map.has(ownKey(n))) return OWN_MEMO;
    const stk9 = n.match(/^(.+) · 스테이킹$/);
    if (stk9 && !C.map.has(ownKey(n))) return ownNm(stk9[1], kind) + ' · 스테이킹';
    return ownTok(t);
  }
  const ownH = (s0, kind) => '<span class="pvl" data-pk="' + (kind === 'm' ? 'm' : 'w') + '">' + esc(ownNm(s0, kind)) + '</span>';
  const ownSeg = (x, pk) => String(x).replace(/^(\s*)([^]*?)(\s*)$/, (a, l, c, r) => l + (c ? (pk ? ownNm(c, pk) : locName(c)) : '') + r);
  const NET_W = typeof WeakMap === 'function' ? new WeakMap() : null;
  function netOk(key, sub, v, w) {
    if (!NET_W || !key || typeof key !== 'object') return true;
    const m9 = NET_W.get(key) || {}, r9 = m9[sub], re9 = !!(r9 && r9.outs.has(v)), n9 = re9 ? r9.n : 0;
    if (n9 >= 8) return false;
    m9[sub] = { outs: re9 ? r9.outs.add(w) : new Set([w]), n: n9 + 1 }; NET_W.set(key, m9);
    return true;
  }
  const OWN_ATTRS = ['title', 'aria-label', 'placeholder', 'data-l'];
  const OWN_AC = typeof WeakMap === 'function' ? new WeakMap() : null;
  function ownAttrs(el) {
    if (!(S.hide || S.rand) || !el || !el.getAttribute) return;
    for (const a of OWN_ATTRS) {
      const v = el.getAttribute(a); if (!v) continue;
      const w = ownScrubM(v, el.getAttribute('data-pvl') === 'w'); if (w === v) continue;
      if (!netOk(el, a, v, w)) continue;
      el.setAttribute(a, w);
    }
  }
  function rbAddedHTML(wide) {
    const D = S.D; if (!D || !D.f) return '';
    const rows = [];
    let at = 0;
    arr(D.f.coins).forEach(c => {
      if (!c || !c.rabby || typeof c.rabby !== 'object') return;
      const px9 = num(c.price);
      if (num(c.rabby.at) > 0) at = at ? Math.min(at, num(c.rabby.at)) : num(c.rabby.at);
      arr(c.locs).forEach(l => {
        const q9 = num(l.qty), parts = String(l.sub || '').split(' · ');
        const pn = l.pname != null ? (String(l.pname || '') + (l.iname ? ' ' + l.iname : '')).trim() : (parts.length >= 4 ? parts[1].replace(/ #\d+$/, '') : '');
        const kd = l.rbKind != null ? String(l.rbKind || '') : (/봇 미추적 토큰/.test(String(l.sub || '')) ? '미추적 토큰' : pn ? '예치' : '');
        const w9 = String(l.w || ''), w0 = w9.replace(/ 지갑$/, '');
        rows.push({ ch: String(l.ch || ''), pn, kd: kd || '지갑 보유', sym: String(c.sym || ''), qty: q9, usd: l.usd != null ? num(l.usd) : q9 * px9, w: w0.indexOf('지갑') >= 0 ? w0 : w9 });
      });
    });
    arr(D.rbDebts).forEach(x => { if (num(x.at) > 0) at = at ? Math.min(at, num(x.at)) : num(x.at);
      rows.push({ ch: String(x.chain || ''), pn: String(x.where || ''), kd: '차입', sym: String(x.sym || ''), qty: -Math.abs(num(x.qty)), usd: -Math.abs(num(x.usd)), w: String(x.wallet || ''), debt: true }); });
    if (!rows.length) return '';
    rows.sort((a, b) => Math.abs(b.usd) - Math.abs(a.usd));
    const tot = sum(rows, r => r.usd), dTot = sum(rows.filter(r => r.debt), r => r.usd);
    const kdP = r => '<span class="pill ' + (r.debt ? 'down' : 'g') + ' sm pvx">' + esc(r.kd) + '</span>';
    const pnSafe = t => !/\d{4,}|\d[,.]\d/.test(t);
    const pnS = r => r.pn ? (pnSafe(r.pn) ? '<span class="pvx">' + esc(r.pn) + '</span>' : locH(r.pn)) : '';
    const head = '<div class="sx-rbh"><b>Rabby로 더한 자산</b> <span class="cap pvx">' + rows.length + '건</span></div>'
      + '<div class="cap sx-rbn">봇이 직접 못 읽는 프로토콜 안 자산이라 Rabby(DeBank) 값으로 총자산에 더해요' + (at ? ' · 마지막 갱신 ' + esc(ago(at)) : '') + '</div>';
    const body = wide
      ? '<div class="sx-rbw"><table class="mini-t sx-rbt"><thead><tr><th scope="col">체인</th><th scope="col">프로토콜 · 성격</th><th scope="col">토큰</th><th scope="col" class="r">수량</th><th scope="col" class="r">금액</th><th scope="col">지갑</th></tr></thead><tbody>'
        + rows.map(r => '<tr><td' + (pnSafe(r.ch) ? ' class="pvx">' + esc(r.ch) : '>' + locH(r.ch)) + '</td><td>' + (r.pn ? pnS(r) + ' ' : '') + kdP(r) + '</td><td><b>' + esc(r.sym) + '</b></td><td class="r num">' + q(r.qty) + '</td><td class="r num ' + (r.debt ? 'down' : '') + '">' + m(r.usd, { sign: r.debt }) + '</td><td class="cap">' + ownH(r.w) + '</td></tr>').join('')
        + '</tbody><tfoot><tr><td colspan="4"><b>합계</b>' + (dTot ? ' <span class="cap">(차입 ' + m(dTot, { sign: true }) + ' 포함)</span>' : '') + '</td><td class="r num"><b>' + m(tot) + '</b></td><td></td></tr></tfoot></table></div>'
      : '<div class="sx-rbl">' + rows.map(r => '<div class="sx-rbr"><div class="l1"><b>' + esc(r.sym) + '</b>' + (r.pn ? '<span class="pn' + (pnSafe(r.pn) ? ' pvx">' + esc(r.pn) : ' pvl">' + esc(locName(r.pn))) + '</span>' : '') + kdP(r) + '<span class="sp"></span><b class="num ' + (r.debt ? 'down' : '') + '">' + m(r.usd, { sign: r.debt }) + '</b></div>'
        + '<div class="cap"><span' + (pnSafe(r.ch) ? ' class="pvx">' + esc(r.ch) : ' class="pvl">' + esc(locName(r.ch))) + ' · </span>' + ownH(r.w) + ' · <span class="num">' + q(r.qty) + '</span></div></div>').join('')
        + '<div class="sx-rbr tot"><div class="l1"><b>합계</b>' + (dTot ? '<span class="cap">차입 ' + m(dTot, { sign: true }) + ' 포함</span>' : '') + '<span class="sp"></span><b class="num">' + m(tot) + '</b></div></div></div>';
    return '<div class="sx-card sx-rbadd" id="sx-rbadd">' + head + body + '</div>';
  }
  const RB_STALE_H = 30;
  function rabbyBody() {
    const rb = S.D.rabby;
    if (!rb || !arr(rb.wallets).length) return '<div class="sx-empty">Rabby 대조 자료가 아직 없어요</div>';
    const st = rb.status || {}, now = Date.now() / 1000;
    const cool = num(st.backoffUntil) > now ? '<div class="cap wtxt" style="margin-top:8px">Rabby 요청 한도(429)로 ' + esc(fmtTs(st.backoffUntil)) + '까지 쉬는 중 — 그동안 마지막 값을 나이와 함께 계속 써요</div>' : '';
    const off = st.enabled === false ? '<div class="cap" style="margin-top:8px" title="설정 파일 rabby.enabled">수집 꺼짐 — 마지막 값만 표시해요</div>' : '';
    const minTxt = num(st.minUsd) > 0 ? '<div class="cap" style="margin-top:8px" title="Rabby 요청 한도 8시간에 약 9번 · 지갑당 1~2번 요청 · 기준 = 봇 평가와 Rabby 마지막 값 중 큰 쪽 (설정 파일 rabby.min_wallet_usd)">Rabby 요청 한도가 작아 ' + m(num(st.minUsd), { compact: true }) + ' 이상 지갑만 봐요</div>' : '';
    const rbAge = ts => { const s0 = Math.max(0, now - num(ts)); return s0 < 3600 ? ago(ts) : s0 < 72 * 3600 ? Math.floor(s0 / 3600) + '시간 전' : Math.floor(s0 / 86400) + '일 전'; };
    const rows = arr(rb.wallets).map(w => {
      const B = num(w.bot), Rb = num(w.rabby), gap = Rb - B, over = !!w.gapSince, lim = Math.max(200, 0.05 * Math.max(B, Rb, 0));
      const botOver = !over && -gap > lim, stale = num(w.fetchedAt) > 0 && now - num(w.fetchedAt) > RB_STALE_H * 3600;
      const old = stale && (over || botOver || gap > lim);
      const miss = arr(w.top).slice(0, 3).map(x => esc(x.sym) + ' ' + esc(x.chain) + ' ' + m(num(x.usd), { compact: true })).join(', ');
      const gapTxt = over || gap > lim ? 'Rabby 쪽이 ' + mN(gap, { compact: true }) + ' 많음' : botOver ? '봇 쪽이 ' + mN(-gap, { compact: true }) + ' 많음' : '차이 ' + mN(gap, { sign: true, compact: true });
      return '<div class="srow"><span class="dot' + (over ? ' w' : botOver ? ' i' : '') + '"></span><div style="min-width:0;flex:1"><b>' + ownH(w.label || short(w.addr)) + '</b> <span class="addr" title="' + esc(w.addr) + '">' + esc(short(w.addr)) + '</span>'
        + (old ? ' <span class="pill w sm" title="Rabby 자료가 ' + RB_STALE_H + '시간 넘게 새로 안 왔어요 — 그 뒤 들어오거나 나간 돈은 대조에 안 보여요">대조 자료 낡음</span>' : '')
        + '<div class="cap num">봇 ' + mN(B, { compact: true }) + ' · Rabby ' + mN(Rb, { compact: true }) + ' · ' + gapTxt
        + (miss ? ' <span class="mut">(빠진 것: ' + miss + ')</span>' : '') + '</div>'
        + '<div class="cap">' + (num(w.only) + num(w.onlyDebt) ? 'Rabby 기준으로 더함 ' + m(num(w.only) + num(w.onlyDebt), { sign: true, compact: true }) + ' · ' : '') + 'Rabby 자료 ' + esc(rbAge(w.fetchedAt))
        + (over ? ' · 차이 큼(' + esc(ago(w.gapSince)) + '부터)' : '') + (botOver ? ' · ' + (old ? 'Rabby 자료 뒤에 들어온 돈일 수 있어요' : 'Rabby 가 못 본 토큰·시세 차일 수 있어요') : '')
        + (w.err ? ' · <span class="wtxt">최근 실패: ' + esc(errTxt((String(w.err).replace(/\s*https?:\/\/\S+/g, '').trim() || String(w.err)).slice(0, 60))) + '</span>' : '') + '</div></div></div>';
    }).join('');
    return rows + cool + off + minTxt;
  }
  function aliasCell(w) {
    const k = w.key || w.addr || '';
    if (S.aliasEdit === k) return '<input class="field" style="height:34px;width:100%" data-alias="' + esc(k) + '" data-cur="' + esc(w.alias) + '" value="' + esc(w.alias) + '" aria-label="표시 이름" autofocus>';
    return '<span class="editable pvl"' + (w.alias ? ' data-pk="w"' : '') + ' role="button" tabindex="0" data-a="aliasEdit" data-k="' + esc(k) + '" title="눌러서 이름 바꾸기">' + esc(w.alias ? ownNm(w.alias) : '(이름 없음)') + '</span>';
  }
  function newWallets() { try { const v = JSON.parse(sessionStorage.getItem('tj_new_wallets') || 'null'); if (v && Array.isArray(v.keys) && Date.now() - v.ts < 7200000) return new Set(v.keys); } catch (e) {  } return new Set(); }
  function unmarkNewWallet(k) { try { const v = JSON.parse(sessionStorage.getItem('tj_new_wallets') || 'null'); if (v && Array.isArray(v.keys) && v.keys.indexOf(k) >= 0) { v.keys = v.keys.filter(x => x !== k); sessionStorage.setItem('tj_new_wallets', JSON.stringify(v)); } } catch (e) {  } }
  return {
    alD, alOn, alTier, authLoad, authLogout, authPwSave, copyBtn, Finder, gasRuleTxt, legacyOn, locH, locMask, locName, locNameM, mqW, netOk, nmKey,
    offcAsk, offcGroup, ownAttrs, ownH, ownIn, ownNm, ownScrub, ownScrubM, ownSeg, pvNameRe, REV_FILL, REV_LEN, rpDur, suSt, suU, sxAfter, sxGo,
    sxHash, SXI, sxId, sxIndex, sxIt, sxKeys, sxParse, sxPick, sxPill, sxRoute, sxSearchPaint, sxSeg, sxSig, sxSlotWait, sxSw, sxWalHay, sxWalRows,
    sxWide, unmarkNewWallet, vSettings, __late
  };
};
